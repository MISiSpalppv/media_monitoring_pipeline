from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.config import get_source
from src.extract.publication import extract_publication, is_rejected, prepare_text


FIXTURES = Path(__file__).parent / "fixtures" / "livejournal"
FETCHED_AT = datetime(2026, 10, 30, 18, 0, tzinfo=timezone.utc)

POSTS = {
    "190455": ("Проехал почти 800 000 км", "2026-10-30T15:52:00+03:00"),
    "189957": ("Немцы сделали большой тест зимних шин", "2026-10-29T08:00:00+03:00"),
    "189195": ("Была ли наша «Победа» – победой?", "2026-08-26T08:00:00+03:00"),
}


@pytest.fixture(scope="module")
def lj_cfg():
    return get_source("livejournal_5koleso")


def extract(post_id, cfg):
    html = (FIXTURES / f"post_{post_id}.html").read_text(encoding="utf-8")
    url = f"https://5koleso.livejournal.com/{post_id}.html"
    return extract_publication(html, url, FETCHED_AT, cfg, run_id="test")


@pytest.mark.parametrize("post_id", POSTS)
def test_livejournal_post(post_id, lj_cfg):
    title_start, published_at = POSTS[post_id]
    pub = extract(post_id, lj_cfg)

    assert pub.url == f"https://5koleso.livejournal.com/{post_id}.html"
    assert pub.title.startswith(title_start)
    assert pub.author == "5koleso"
    assert pub.published_at == published_at
    assert pub.published_at_raw
    assert len(pub.text) > 2000
    assert pub.quality_flags == []
    assert not is_rejected(pub)
    assert pub.extraction == {
        "title": "trafilatura",
        "text": "trafilatura",
        "author": "css",
        "published_at": "css",
    }


@pytest.mark.parametrize("post_id", POSTS)
def test_livejournal_text_is_clean(post_id, lj_cfg):
    pub = extract(post_id, lj_cfg)
    # заголовок не дублируется в начале текста, блок "Что еще почитать" отрезан
    assert not pub.text.startswith(pub.title)
    assert "Что еще почитать" not in pub.text


def test_priority_css_first_for_title(lj_cfg):
    cfg = {**lj_cfg, "field_priority": {**lj_cfg["field_priority"], "title": ["css", "trafilatura"]}}
    pub = extract("190455", cfg)
    assert pub.extraction["title"] == "css"
    assert pub.title.startswith("Проехал почти 800 000 км")


def test_priority_falls_back_when_first_method_is_empty(lj_cfg):
    cfg = {**lj_cfg, "selectors": {**lj_cfg["selectors"], "published_at": ".no-such-element"}}
    pub = extract("190455", cfg)
    # CSS ничего не нашёл, дата взята у Trafilatura (без времени)
    assert pub.extraction["published_at"] == "trafilatura"
    assert pub.published_at == "2026-10-30T00:00:00+03:00"


def test_trafilatura_only_has_no_author(lj_cfg):
    cfg = {**lj_cfg, "field_priority": {"author": ["trafilatura"]}}
    pub = extract("190455", cfg)
    assert pub.author is None
    assert "author_missing" in pub.quality_flags
    assert not is_rejected(pub)


def test_short_text_is_rejected(lj_cfg):
    cfg = {**lj_cfg, "min_text_length": 100_000}
    pub = extract("189957", cfg)
    assert "text_too_short" in pub.quality_flags
    assert is_rejected(pub)


def test_page_without_publication_is_rejected(lj_cfg):
    html = "<html><head><title></title></head><body><p>Мы используем cookie</p></body></html>"
    pub = extract_publication(html, "https://5koleso.livejournal.com/1.html", FETCHED_AT, lj_cfg)
    assert is_rejected(pub)
    assert "missing_title" in pub.quality_flags


def test_hash_does_not_depend_on_fetch_and_run(lj_cfg):
    a = extract("190455", lj_cfg)
    html = (FIXTURES / "post_190455.html").read_text(encoding="utf-8")
    b = extract_publication(html, a.url, datetime(2026, 10, 30, 19, 0, tzinfo=timezone.utc),
                            lj_cfg, run_id="another")
    assert a.content_hash == b.content_hash


def test_hash_ignores_counters_in_metadata(lj_cfg):
    html = (FIXTURES / "post_190455.html").read_text(encoding="utf-8")
    # счётчики лайков и комментариев на странице меняются, хэш нет
    changed = html.replace("</body>", '<span class="likes">999</span></body>')
    a = extract_publication(html, "https://5koleso.livejournal.com/190455.html", FETCHED_AT, lj_cfg)
    b = extract_publication(changed, "https://5koleso.livejournal.com/190455.html", FETCHED_AT, lj_cfg)
    assert a.content_hash == b.content_hash


def test_date_in_future_is_flagged(lj_cfg):
    early = datetime(2026, 10, 1, tzinfo=timezone.utc)
    html = (FIXTURES / "post_190455.html").read_text(encoding="utf-8")
    pub = extract_publication(html, "https://5koleso.livejournal.com/190455.html", early, lj_cfg)
    assert "date_in_future" in pub.quality_flags
    assert not is_rejected(pub)


def test_prepare_text_drops_junk_lines():
    text = "Заголовок\nНормальный абзац текста.\nЧитать далее\nМы используем файлы cookie.\nЕщё абзац."
    assert prepare_text(text, "Заголовок", []) == "Нормальный абзац текста.\nЕщё абзац."
