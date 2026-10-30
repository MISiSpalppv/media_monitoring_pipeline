import hashlib
import json
import re
from datetime import datetime
from urllib.parse import parse_qsl, urlencode, urlparse
from zoneinfo import ZoneInfo

import dateparser


TRACKING_PARAMS = ("utm_", "yclid", "gclid", "fbclid")


def collapse_spaces(value: str | None) -> str | None:
    if value is None:
        return None
    value = re.sub(r"\s+", " ", value).strip()
    return value or None


def clean_text(text: str | None) -> str | None:
    """Схлопывает пробелы внутри строк, абзацы сохраняет."""
    if not text:
        return None
    lines = (collapse_spaces(line) for line in text.splitlines())
    text = "\n".join(line for line in lines if line)
    return text or None


def canonical_url(url: str) -> str:
    parsed = urlparse(url)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith(TRACKING_PARAMS)
    ]
    return parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        query=urlencode(query),
        fragment="",
    ).geturl()


def parse_date(raw: str | None, fetched_at: datetime, timezone: str,
               date_order: str = "DMY") -> datetime | None:
    """Разбирает дату публикации.

    Относительные даты ("вчера в 14:30", "5 минут назад") считаются
    от момента получения страницы, а не от текущего времени.
    """
    if not raw or not raw.strip():
        return None

    tz = ZoneInfo(timezone)
    raw = raw.strip()

    # ISO 8601 (meta-теги, datetime у <time>) dateparser с DATE_ORDER=DMY не разбирает
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        parsed = None
    if parsed is not None:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=tz)
        return parsed.astimezone(tz)

    parsed = dateparser.parse(
        raw,
        languages=["ru", "en"],
        settings={
            "TIMEZONE": timezone,
            "RETURN_AS_TIMEZONE_AWARE": True,
            "RELATIVE_BASE": fetched_at.astimezone(tz).replace(tzinfo=None),
            "PREFER_DATES_FROM": "past",
            # 05.01.25 на русскоязычных сайтах это 5 января, а не 1 мая
            "DATE_ORDER": date_order,
        },
    )
    if parsed is None:
        return None
    return parsed.astimezone(tz)


def content_hash(url: str, title: str | None, author: str | None,
                 text: str | None, published_at: str | None) -> str:
    # В хэш входит только содержимое публикации: время сбора, run_id,
    # счётчики лайков и просмотров сюда не попадают, иначе каждый
    # повторный сбор давал бы новую версию.
    parts = [
        canonical_url(url),
        collapse_spaces(title) or "",
        collapse_spaces(author) or "",
        collapse_spaces(text) or "",
        published_at or "",
    ]
    payload = json.dumps(parts, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
