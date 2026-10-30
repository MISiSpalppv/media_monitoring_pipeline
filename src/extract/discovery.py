from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup


def discover_links(html: str, base_url: str) -> list[str]:
    """
    Извлекает уникальные внутренние ссылки из HTML.
    """

    soup = BeautifulSoup(html, "html.parser")
    base_domain = urlparse(base_url).netloc

    links = set()

    for tag in soup.select("a[href]"):
        href = tag.get("href")

        if not href:
            continue

        absolute_url = urljoin(base_url, href)
        parsed = urlparse(absolute_url)

        if parsed.scheme not in ("http", "https"):
            continue

        if parsed.netloc != base_domain:
            continue

        # Убираем якоря, чтобы не создавать дубликаты
        clean_url = parsed._replace(fragment="").geturl()

        links.add(clean_url)

    return sorted(links)