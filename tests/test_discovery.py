from pathlib import Path

from parsel import Selector

from src.config import get_source
from src.extract.discovery import discover_links, feed_links


FIXTURES = Path(__file__).parent / "fixtures" / "livejournal"


def test_livejournal_listing_links():
    cfg = get_source("livejournal_5koleso")
    html = (FIXTURES / "listing.html").read_text(encoding="utf-8")

    area = "".join(Selector(text=html).css(cfg["discovery"]["area"]).getall())
    links = discover_links(area, "https://5koleso.livejournal.com/", cfg["discovery"]["link_pattern"])

    assert len(links) == 10
    assert links[0] == "https://5koleso.livejournal.com/190455.html"
    assert all(link.endswith(".html") for link in links)


def test_link_pattern_filters_service_pages():
    html = """
        <a href="/190455.html">пост</a>
        <a href="/190455.html#comments">комментарии</a>
        <a href="/tag/авто">тег</a>
        <a href="/?skip=10">дальше</a>
        <a href="https://other.livejournal.com/1.html">чужой блог</a>
        <a href="javascript:void(0)">js</a>
    """
    links = discover_links(html, "https://5koleso.livejournal.com/", r"/\d+\.html$")
    assert links == ["https://5koleso.livejournal.com/190455.html"]


def test_without_pattern_returns_internal_links():
    html = '<a href="/a">a</a><a href="/b">b</a><a href="https://ya.ru/">x</a>'
    assert discover_links(html, "https://site.ru/") == ["https://site.ru/a", "https://site.ru/b"]


def test_rss_links():
    xml = """<?xml version="1.0"?>
        <rss version="2.0"><channel>
          <item><link>https://site.ru/news/1</link></item>
          <item><link> https://site.ru/news/2 </link></item>
          <item><link>https://site.ru/about</link></item>
        </channel></rss>"""
    assert feed_links(xml, "rss", r"/news/") == ["https://site.ru/news/1", "https://site.ru/news/2"]


def test_atom_links():
    xml = """<?xml version="1.0"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry><link href="https://site.ru/p/1"/></entry>
        </feed>"""
    assert feed_links(xml, "rss") == ["https://site.ru/p/1"]


def test_sitemap_links():
    xml = """<?xml version="1.0"?>
        <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
          <url><loc>https://site.ru/p/1</loc></url>
          <url><loc>https://site.ru/p/1</loc></url>
        </urlset>"""
    assert feed_links(xml, "sitemap") == ["https://site.ru/p/1"]
