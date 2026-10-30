from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class Publication:
    source_url: str
    url: str
    title: str | None = None
    text: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    source_type: str | None = None
    metadata: dict = field(default_factory=dict)