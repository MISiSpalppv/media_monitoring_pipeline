import re
from urllib.parse import urljoin, urlparse

from parsel import Selector


def discover_links(html: str, base_url: str, pattern: str | None = None) -> list[str]:
    """
    Извлекает уникальные внутренние ссылки из HTML.
    Если задан pattern, оставляет только ссылки, подходящие под регулярку.
    """
    base_domain = urlparse(base_url).netloc
    regex = re.compile(pattern) if pattern else None

    links = []
    for href in Selector(text=html).css("a::attr(href)").getall():
        absolute_url = urljoin(base_url, href.strip())
        parsed = urlparse(absolute_url)

        if parsed.scheme not in ("http", "https"):
            continue

        if parsed.netloc != base_domain:
            continue

        # Убираем якоря, чтобы не создавать дубликаты
        clean_url = parsed._replace(fragment="").geturl()

        if regex and not regex.search(clean_url):
            continue

        if clean_url not in links:
            links.append(clean_url)

    # порядок как на странице: на листинге сверху обычно свежие публикации
    return links


def feed_links(xml: str, mode: str, pattern: str | None = None) -> list[str]:
    """Ссылки из RSS/Atom-ленты или sitemap.xml."""
    sel = Selector(text=xml, type="xml")
    sel.remove_namespaces()

    if mode == "rss":
        links = sel.xpath("//item/link/text() | //entry/link/@href").getall()
    elif mode == "sitemap":
        links = sel.xpath("//url/loc/text()").getall()
    else:
        raise ValueError(f"unknown feed mode: {mode}")

    regex = re.compile(pattern) if pattern else None
    result = []
    for link in (link.strip() for link in links):
        if link and link not in result and (not regex or regex.search(link)):
            result.append(link)
    return result
