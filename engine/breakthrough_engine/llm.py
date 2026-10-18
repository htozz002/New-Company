"""Claude access for the engine: structured JSON calls and web-research calls.

Every call sets server-side refusal fallbacks ("default"), so a request that one
model's safety classifier declines is retried on Anthropic's recommended
fallback model. A refusal from the whole chain raises RefusalError.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import anthropic

from .config import DEFAULT_MODEL

FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_CONTINUATIONS = 5

# Claude Opus 5.5 list prices per million tokens, for the run's cost estimate.
PRICE_PER_MTOK = {"claude-opus-5-5": (4.00, 20.00)}


class LLMError(RuntimeError):
    pass


class RefusalError(LLMError):
    pass


@dataclass
class Research:
    text: str
    sources: list[dict] = field(default_factory=list)  # [{"title": ..., "url": ...}]


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    calls: int = 0
    web_searches: int = 0

    def add(self, usage) -> None:
        self.calls += 1
        self.input_tokens += getattr(usage, "input_tokens", 0) or 0
        self.input_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.input_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.output_tokens += getattr(usage, "output_tokens", 0) or 0
        server = getattr(usage, "server_tool_use", None)
        self.web_searches += (getattr(server, "web_search_requests", 0) or 0) if server else 0

    def estimated_cost(self, model: str) -> float | None:
        prices = PRICE_PER_MTOK.get(model)
        if not prices:
            return None
        # Web search is billed separately at $10 per 1,000 searches.
        return (self.input_tokens * prices[0] + self.output_tokens * prices[1]) / 1e6 + self.web_searches * 0.01


class LLM:
    def __init__(self, model: str = DEFAULT_MODEL, client: anthropic.Anthropic | None = None):
        self.model = model
        self.client = client or anthropic.Anthropic()
        self.usage = Usage()

    def structured(self, name: str, system: str, prompt: str, schema: dict, effort: str = "medium",
                   max_tokens: int = 32000) -> dict:
        """One call whose answer must match `schema`. `name` labels the call in errors and tests."""
        message = self._run(
            system=system,
            messages=[{"role": "user", "content": prompt}],
            output_config={"effort": effort, "format": {"type": "json_schema", "schema": schema}},
            max_tokens=max_tokens,
            label=name,
        )
        text = "".join(b.text for b in message.content if b.type == "text")
        try:
            return json.loads(text)
        except json.JSONDecodeError as err:
            raise LLMError(f"{name}: response was not valid JSON ({err})") from err

    def research(self, name: str, system: str, prompt: str, effort: str = "high", max_searches: int = 8,
                 max_tokens: int = 32000) -> Research:
        """A call that may search the web. Returns the written findings plus every source it saw."""
        tools = [{"type": "web_search_20260209", "name": "web_search", "max_uses": max_searches}]
        messages: list[dict] = [{"role": "user", "content": prompt}]
        sources: dict[str, str] = {}
        text_parts: list[str] = []
        for _ in range(MAX_CONTINUATIONS + 1):
            message = self._run(system=system, messages=messages, tools=tools,
                                output_config={"effort": effort}, max_tokens=max_tokens, label=name)
            for block in message.content:
                if block.type == "text":
                    text_parts.append(block.text)
                    for citation in getattr(block, "citations", None) or []:
                        url = getattr(citation, "url", None)
                        if url:
                            sources.setdefault(url, getattr(citation, "title", None) or url)
                elif block.type == "web_search_tool_result" and isinstance(block.content, list):
                    for result in block.content:
                        sources.setdefault(result.url, result.title)
            if message.stop_reason != "pause_turn":
                break
            # The server paused a long search loop; send the turn back to resume it.
            messages = [messages[0], {"role": "assistant", "content": message.content}]
        else:
            raise LLMError(f"{name}: research did not finish after {MAX_CONTINUATIONS} continuations")
        return Research(text="".join(text_parts).strip(), sources=[{"title": t, "url": u} for u, t in sources.items()])

    def _run(self, *, system: str, messages: list[dict], max_tokens: int, label: str, **kwargs):
        try:
            # Streaming avoids HTTP timeouts on long, high-effort answers.
            with self.client.beta.messages.stream(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=messages,
                betas=[FALLBACK_BETA],
                fallbacks="default",
                **kwargs,
            ) as stream:
                message = stream.get_final_message()
        except anthropic.AuthenticationError as err:
            raise LLMError("Claude API key is invalid. Check ANTHROPIC_API_KEY.") from err
        except TypeError as err:
            # The SDK raises TypeError when it finds no credentials at all.
            if "authentication" not in str(err).lower():
                raise
            raise LLMError("No Claude API credentials found. Set ANTHROPIC_API_KEY or run `ant auth login`.") from err
        except anthropic.RateLimitError as err:
            raise LLMError(f"{label}: rate limited by the Claude API; try again shortly") from err
        except anthropic.APIStatusError as err:
            raise LLMError(f"{label}: Claude API error {err.status_code}: {err.message}") from err
        except anthropic.APIConnectionError as err:
            raise LLMError(f"{label}: could not reach the Claude API ({err})") from err
        self.usage.add(message.usage)
        if message.stop_reason == "refusal":
            details = getattr(message, "stop_details", None)
            raise RefusalError(f"{label}: declined ({getattr(details, 'category', None) or 'no category'})")
        if message.stop_reason == "max_tokens":
            raise LLMError(f"{label}: answer was cut off at max_tokens={max_tokens}")
        return message
