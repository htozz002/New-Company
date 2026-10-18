"""Plain data records passed between stages."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Paper:
    """One piece of research: a paper, a preprint, or a clinical trial."""

    source: str  # europepmc | biorxiv | medrxiv | clinicaltrials | web | manual
    source_id: str
    title: str
    abstract: str
    url: str = ""
    published: str = ""  # YYYY-MM-DD
    venue: str = ""
    authors: str = ""
    kind: str = "paper"  # paper | preprint | trial | idea
    extra: dict = field(default_factory=dict)

    @property
    def key(self) -> str:
        return f"{self.source}:{self.source_id}"

    def as_prompt_block(self, ref: str | None = None) -> str:
        """Render for a prompt. Research text is data, so it sits inside tags."""
        ref = ref or self.key
        return (
            f'<research ref="{ref}" kind="{self.kind}" source="{self.source}" '
            f'published="{self.published}" venue="{_attr(self.venue)}">\n'
            f"<title>{self.title}</title>\n"
            f"<abstract>{self.abstract}</abstract>\n"
            f"</research>"
        )


def _attr(value: str) -> str:
    return value.replace('"', "'")
