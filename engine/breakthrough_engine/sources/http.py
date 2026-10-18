"""Small JSON-over-HTTP helper with retries. Standard library only."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "breakthrough-engine/0.1 (research discovery; contact via project owner)"


class SourceError(RuntimeError):
    pass


def get_json(url: str, params: dict | None = None, timeout: float = 30.0, retries: int = 3) -> dict:
    if params:
        url = f"{url}?{urllib.parse.urlencode(params)}"
    return _request(urllib.request.Request(url, headers=_headers()), timeout, retries)


def post_json(url: str, body: dict, timeout: float = 30.0, retries: int = 3) -> dict:
    headers = {**_headers(), "Content-Type": "application/json"}
    request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    return _request(request, timeout, retries)


def _headers() -> dict:
    return {"User-Agent": USER_AGENT, "Accept": "application/json"}


def _request(request: urllib.request.Request, timeout: float, retries: int) -> dict:
    url = request.full_url
    delay = 2.0
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as err:
            # 4xx other than rate limiting will not get better on retry.
            if err.code != 429 and err.code < 500:
                raise SourceError(f"HTTP {err.code} for {url}") from err
            last = err
        except (urllib.error.URLError, TimeoutError) as err:
            last = err
        if attempt < retries:
            time.sleep(delay)
            delay *= 2
    raise SourceError(f"Failed after {retries + 1} attempts: {url} ({last})")
