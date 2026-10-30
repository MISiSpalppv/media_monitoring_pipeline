from datetime import datetime, timezone

import pytest

from src.extract.normalize import canonical_url, clean_text, content_hash, parse_date


FETCHED_AT = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)  # 15:00 по Москве
TZ = "Europe/Moscow"


@pytest.mark.parametrize("raw, expected", [
    ("21 Май, 2026 - 17:10", "2026-05-21T17:10:00+03:00"),
    ("15 Март, 2025 - 01:17", "2025-03-15T01:17:00+03:00"),
    ("October 30 2026, 15:52", "2026-10-30T15:52:00+03:00"),
    ("2026-08-26", "2026-08-26T00:00:00+03:00"),
    ("2026-10-30T10:00:00+00:00", "2026-10-30T13:00:00+03:00"),
    ("30 октября 2026 в 09:15", "2026-10-30T09:15:00+03:00"),
])
def test_parse_absolute_dates(raw, expected):
    assert parse_date(raw, FETCHED_AT, TZ).isoformat() == expected


@pytest.mark.parametrize("raw, expected", [
    ("вчера в 14:30", "2026-10-29T14:30:00+03:00"),
    ("5 минут назад", "2026-10-30T14:55:00+03:00"),
    ("сегодня, 09:15", "2026-10-30T09:15:00+03:00"),
])
def test_relative_dates_count_from_fetched_at(raw, expected):
    assert parse_date(raw, FETCHED_AT, TZ).isoformat() == expected


def test_relative_date_does_not_depend_on_current_time():
    old_fetch = datetime(2025, 1, 10, 12, 0, tzinfo=timezone.utc)
    assert parse_date("вчера в 10:00", old_fetch, TZ).isoformat() == "2025-01-09T10:00:00+03:00"


def test_timezone_from_config():
    parsed = parse_date("2026-05-21 17:10", FETCHED_AT, "Asia/Yekaterinburg")
    assert parsed.isoformat() == "2026-05-21T17:10:00+05:00"


@pytest.mark.parametrize("raw", [None, "", "   ", "мусор", "Читать далее"])
def test_unparseable_date_returns_none(raw):
    assert parse_date(raw, FETCHED_AT, TZ) is None


def hash_args(**overrides):
    args = {
        "url": "https://example.com/post/1",
        "title": "Заголовок",
        "author": "автор",
        "text": "Первый абзац.\nВторой абзац.",
        "published_at": "2026-10-30T15:52:00+03:00",
    }
    args.update(overrides)
    return args


def test_hash_ignores_whitespace():
    base = content_hash(**hash_args())
    spaced = content_hash(**hash_args(
        title="  Заголовок ",
        text="Первый   абзац.\n\n  Второй абзац.  ",
    ))
    assert base == spaced


def test_hash_ignores_tracking_params_and_fragment():
    base = content_hash(**hash_args())
    assert base == content_hash(**hash_args(url="https://example.com/post/1?utm_source=tg#comments"))


def test_hash_changes_with_text():
    assert content_hash(**hash_args()) != content_hash(**hash_args(text="Другой текст"))


def test_hash_changes_with_date():
    assert content_hash(**hash_args()) != content_hash(**hash_args(published_at=None))


def test_canonical_url_keeps_meaningful_params():
    assert canonical_url("HTTPS://Example.com/forum?showtopic=5&utm_medium=x") == \
        "https://example.com/forum?showtopic=5"


def test_clean_text_keeps_paragraphs():
    assert clean_text("  один   два \n\n\n три ") == "один два\nтри"
