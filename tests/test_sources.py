from datetime import datetime, timezone
from pathlib import Path

import pytest
from scrapy.http import HtmlResponse
from scrapy.utils.test import get_crawler

from src.config import get_source, load_sources
from src.extract.discovery import discover_links
from src.extract.publication import extract_publication, is_rejected
from src.extract.spider import PublicationSpider


FIXTURES = Path(__file__).parent / "fixtures"
FETCHED_AT = datetime(2026, 10, 30, 18, 0, tzinfo=timezone.utc)


def read(path: str, encoding: str = "utf-8") -> str:
    return (FIXTURES / path).read_bytes().decode(encoding)


def test_all_sources_are_valid():
    assert set(load_sources()) == {
        "livejournal_5koleso", "irecommend", "fourpda_security",
        "otzovik_banks", "dzen_news_computers", "drive2_featured",
    }


def test_fourpda_topic_links():
    cfg = get_source("fourpda_security")
    links = discover_links(read("fourpda/listing.html", "cp1251"), cfg["start_urls"][0],
                           cfg["discovery"]["link_pattern"])
    assert len(links) == 30
    # страницы темы (&st=) и служебные ссылки (&view=) не считаются публикациями
    assert all("&" not in link for link in links)


@pytest.mark.parametrize("topic, title, author, published_at", [
    ("956751", "KeePassDX", "Флюгегехаймен", "2019-06-22T07:53:00+03:00"),
    ("775241", "Samsung Secure Folder", "freemaks", "2016-10-03T01:57:00+03:00"),
])
def test_fourpda_first_post(topic, title, author, published_at):
    cfg = get_source("fourpda_security")
    html = read(f"fourpda/topic_{topic}.html", "cp1251")
    pub = extract_publication(html, f"https://4pda.to/forum/index.php?showtopic={topic}", FETCHED_AT, cfg)

    assert pub.title.startswith(title)
    assert pub.author == author
    # дата "22.06.19, 07:53" в формате ДД.ММ.ГГ
    assert pub.published_at == published_at
    assert set(pub.extraction.values()) == {"css"}
    assert not is_rejected(pub)


def test_otzovik_two_level_discovery():
    cfg = get_source("otzovik_banks")
    discovery = cfg["discovery"]
    catalog = read("otzovik/listing.html")
    product = read("otzovik/product.html")

    banks = discover_links(catalog, cfg["start_urls"][0], discovery["follow_pattern"])
    assert len(banks) == 30
    assert discover_links(catalog, cfg["start_urls"][0], discovery["link_pattern"]) == []

    reviews = discover_links(product, "https://otzovik.com/reviews/onlayn_bank_sbera/",
                             discovery["link_pattern"])
    assert reviews == [
        "https://otzovik.com/review_18098197.html",
        "https://otzovik.com/review_18096769.html",
    ]


@pytest.mark.parametrize("review, title, author, rating", [
    ("18098197", "Удобно, что онлайн", "HotMar", "4"),
    ("18096769", "Мошенники", "Аноним3271223", "1"),
])
def test_otzovik_review(review, title, author, rating):
    cfg = get_source("otzovik_banks")
    pub = extract_publication(read(f"otzovik/review_{review}.html"),
                              f"https://otzovik.com/review_{review}.html", FETCHED_AT, cfg)

    assert pub.title == title
    assert pub.author == author
    assert pub.published_at == "2026-02-08T00:00:00+03:00"
    assert pub.text.startswith("Достоинства:")
    assert pub.extraction["text"] == "trafilatura"
    # оценка из отзыва, а не средняя по банку
    assert pub.metadata == {"product": "Онлайн банк Сбера", "rating": rating}
    assert not is_rejected(pub)


def test_metadata_does_not_change_hash():
    cfg = get_source("otzovik_banks")
    html = read("otzovik/review_18098197.html")
    url = "https://otzovik.com/review_18098197.html"
    a = extract_publication(html, url, FETCHED_AT, cfg)
    b = extract_publication(html.replace('content="4"', 'content="5"'), url, FETCHED_AT, cfg)
    assert a.metadata["rating"] != b.metadata["rating"]
    assert a.content_hash == b.content_hash


def test_redirect_to_other_domain_is_blocked(tmp_path):
    crawler = get_crawler(PublicationSpider)
    spider = PublicationSpider.from_crawler(
        crawler, source="dzen_news_computers", run_id="test", output_dir=str(tmp_path)
    )
    response = HtmlResponse(
        url="https://sso.passport.yandex.ru/push?retpath=https%3A%2F%2Fdzen.ru%2Fnews",
        body=read("dzen/listing.html").encode("utf-8"),
        encoding="utf-8",
    )
    assert spider.is_blocked(response)
    assert spider.source_status("finished") == ("unavailable", "redirected to sso.passport.yandex.ru")
