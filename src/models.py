from dataclasses import dataclass, field


@dataclass
class Publication:
    source_id: str
    source_url: str
    url: str
    fetched_at: str
    run_id: str
    title: str | None = None
    text: str | None = None
    author: str | None = None
    published_at: str | None = None
    published_at_raw: str | None = None
    source_type: str | None = None
    content_hash: str | None = None
    # откуда взято каждое поле: {"title": "trafilatura", "author": "css", ...}
    extraction: dict = field(default_factory=dict)
    quality_flags: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
