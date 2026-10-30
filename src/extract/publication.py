import re
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse

import trafilatura
from parsel import Selector

from src.extract.adapters import ADAPTERS
from src.extract.normalize import canonical_url, clean_text, collapse_spaces, content_hash, parse_date
from src.models import Publication


DEFAULT_PRIORITY = ["trafilatura", "css"]
FIELDS = ("title", "text", "author", "published_at")

# С этими флагами запись не попадает в RAW
REJECT_FLAGS = {"missing_url", "missing_title", "text_too_short", "text_shorter_than_title"}

# Короткие служебные строки, которые иногда попадают в текст
JUNK_LINE = re.compile(
    r"cookie|куки|читать далее|читать полностью|показать полностью|подписывайтесь на наш",
    re.IGNORECASE,
)
JUNK_LINE_MAX_LEN = 200


def extract_publication(html: str, url: str, fetched_at: datetime, cfg: dict,
                        run_id: str = "") -> Publication:
    sel = Selector(text=html)
    url = canonical_url(find_canonical(sel, url) or url)

    candidates = {
        "trafilatura": trafilatura_fields(html, url),
        "css": css_fields(sel, cfg.get("selectors", {})),
    }
    adapter = cfg.get("adapter")
    if adapter:
        candidates["adapter"] = ADAPTERS[adapter](sel, url)

    timezone = cfg.get("timezone", "Europe/Moscow")
    min_text_length = cfg.get("min_text_length", 200)
    extraction = {}

    def priority(field):
        default = (["adapter"] if adapter else []) + DEFAULT_PRIORITY
        return cfg.get("field_priority", {}).get(field, default)

    title, extraction["title"] = pick(
        "title", candidates, priority("title"),
        prepare=collapse_spaces,
        check=lambda v: len(v) <= 500,
    )
    text, extraction["text"] = pick(
        "text", candidates, priority("text"),
        prepare=lambda v: prepare_text(v, title, cfg.get("text_cut_markers", [])),
        check=lambda v: len(v) >= min_text_length,
    )
    author, extraction["author"] = pick(
        "author", candidates, priority("author"),
        prepare=collapse_spaces,
        check=lambda v: len(v) <= 200,
    )
    published_raw, extraction["published_at"] = pick(
        "published_at", candidates, priority("published_at"),
        prepare=collapse_spaces,
        check=lambda v: parse_date(v, fetched_at, timezone) is not None,
    )

    published = parse_date(published_raw, fetched_at, timezone)
    published_at = published.isoformat() if published else None

    pub = Publication(
        source_id=cfg["id"],
        source_url=cfg["start_urls"][0],
        url=url,
        fetched_at=fetched_at.isoformat(),
        run_id=run_id,
        title=title,
        text=text,
        author=author,
        published_at=published_at,
        published_at_raw=published_raw,
        source_type=cfg.get("source_type"),
        extraction={k: v for k, v in extraction.items() if v},
    )
    pub.content_hash = content_hash(url, title, author, text, published_at)
    pub.quality_flags = quality_flags(pub, published, fetched_at, cfg)
    return pub


def is_rejected(pub: Publication) -> bool:
    return bool(REJECT_FLAGS & set(pub.quality_flags))


def pick(field, candidates, priority, prepare, check):
    """Первое значение по приоритету, прошедшее проверку.

    Если проверку не прошло ни одно, берётся первое непустое:
    тогда проблему увидит quality check, а не потеряется молча.
    """
    values = []
    for method in priority:
        value = candidates.get(method, {}).get(field)
        value = prepare(value) if value else None
        if value:
            values.append((value, method))

    for value, method in values:
        if check(value):
            return value, method
    return values[0] if values else (None, None)


def trafilatura_fields(html: str, url: str) -> dict:
    doc = trafilatura.bare_extraction(
        html,
        url=url,
        with_metadata=True,
        include_comments=False,
        favor_precision=True,
    )
    if doc is None:
        return {}
    return {
        "title": doc.title,
        "text": doc.text,
        "author": doc.author,
        "published_at": doc.date,
    }


def css_fields(sel: Selector, selectors: dict) -> dict:
    fields = {}
    for field in FIELDS:
        selector = selectors.get(field)
        if not selector:
            continue
        # без явного ::text / ::attr берём весь текст внутри элемента
        if "::" not in selector:
            selector += " ::text"
        parts = [part.strip() for part in sel.css(selector).getall()]
        fields[field] = " ".join(part for part in parts if part) or None
    return fields


def find_canonical(sel: Selector, url: str) -> str | None:
    href = sel.css('link[rel="canonical"]::attr(href)').get()
    if not href:
        return None
    href = urljoin(url, href.strip())
    # чужой домен в canonical не принимаем, это бывает у перепечаток
    if urlparse(href).netloc != urlparse(url).netloc:
        return None
    return href


def prepare_text(text: str, title: str | None, cut_markers: list[str]) -> str | None:
    text = clean_text(text)
    if not text:
        return None

    for marker in cut_markers:
        pos = text.find(marker)
        if pos != -1:
            text = text[:pos]

    lines = [
        line for line in text.split("\n")
        if not (len(line) < JUNK_LINE_MAX_LEN and JUNK_LINE.search(line))
    ]
    # Trafilatura часто повторяет заголовок первой строкой текста
    if title and lines and collapse_spaces(lines[0]) == title:
        lines = lines[1:]

    return clean_text("\n".join(lines))


def quality_flags(pub: Publication, published: datetime | None,
                  fetched_at: datetime, cfg: dict) -> list[str]:
    flags = []
    if not pub.url:
        flags.append("missing_url")
    if not pub.title:
        flags.append("missing_title")

    text_len = len(pub.text or "")
    if text_len < cfg.get("min_text_length", 200):
        flags.append("text_too_short")
    if pub.title and text_len <= len(pub.title):
        flags.append("text_shorter_than_title")

    if pub.published_at_raw and published is None:
        flags.append("date_not_parsed")
    elif not pub.published_at_raw:
        flags.append("date_missing")
    elif published > fetched_at + timedelta(hours=cfg.get("future_tolerance_hours", 24)):
        flags.append("date_in_future")

    if not pub.author:
        flags.append("author_missing")
    return flags
