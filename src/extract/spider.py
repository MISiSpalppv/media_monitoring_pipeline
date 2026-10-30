"""Один паук для всех источников из sources.yaml.

Запуск:
    python -m src.extract.spider --source livejournal_5koleso --run-id manual_1

Результат: data/processed/<run_id>/<source_id>.jsonl (принятые записи),
<source_id>.rejected.jsonl и <source_id>.summary.json со статусом источника.
"""
import argparse
import json
import logging
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import scrapy
from scrapy.crawler import CrawlerProcess
from scrapy.exceptions import IgnoreRequest
from scrapy.spidermiddlewares.httperror import HttpError

from src.config import PROJECT_ROOT, get_source
from src.extract.discovery import discover_links, feed_links
from src.extract.publication import extract_publication, is_rejected


OUTPUT_ROOT = PROJECT_ROOT / "data" / "processed"

SETTINGS = {
    "ROBOTSTXT_OBEY": True,
    "USER_AGENT": "media-monitoring-pipeline/0.1 (test assignment)",
    "AUTOTHROTTLE_ENABLED": True,
    "AUTOTHROTTLE_START_DELAY": 2,
    "AUTOTHROTTLE_MAX_DELAY": 30,
    "CONCURRENT_REQUESTS_PER_DOMAIN": 1,
    "RETRY_ENABLED": True,
    "RETRY_TIMES": 2,
    # 521 (Cloudflare: origin down) и 429 в стандартный список не входят
    "RETRY_HTTP_CODES": [500, 502, 503, 504, 520, 521, 522, 524, 408, 429],
    "DOWNLOAD_TIMEOUT": 30,
    "LOG_LEVEL": "INFO",
    "TELNETCONSOLE_ENABLED": False,
    "REMOTE_CONTROL_ENABLED": False,
}


class PublicationSpider(scrapy.Spider):
    name = "publications"

    def __init__(self, source: str, run_id: str, output_dir: str | None = None, **kwargs):
        super().__init__(**kwargs)
        self.cfg = get_source(source)
        self.source_id = source
        self.run_id = run_id
        self.output_dir = Path(output_dir) if output_dir else OUTPUT_ROOT / run_id

        self.started_at = datetime.now(timezone.utc)
        self.listing_pages_ok = 0
        self.publication_pages_ok = 0
        self.http_errors = Counter()
        self.other_errors = Counter()
        self.block_reason = None
        self.domain = urlparse(self.cfg["start_urls"][0]).netloc.removeprefix("www.")
        self.listing_pages_requested = 0
        self.seen_listings = set()
        self.seen_urls = set()
        self.accepted = []
        self.rejected = []

    async def start(self):
        for url in self.cfg["start_urls"]:
            yield self.listing_request(url)

    def listing_request(self, url):
        self.listing_pages_requested += 1
        return scrapy.Request(
            url,
            callback=self.parse_listing,
            errback=self.on_error,
            meta={"page": self.listing_pages_requested, "kind": "listing"},
        )

    def can_request_listing(self) -> bool:
        return self.listing_pages_requested < self.cfg["max_pages"]

    def parse_listing(self, response):
        if self.is_blocked(response):
            return
        self.listing_pages_ok += 1

        discovery = self.cfg["discovery"]
        mode = discovery["mode"]

        if mode == "links":
            area = discovery.get("area")
            html = "".join(response.css(area).getall()) if area else response.text
            links = discover_links(html, response.url, discovery.get("link_pattern"))
        else:
            links = feed_links(response.text, mode, discovery.get("link_pattern"))

        self.logger.info("%s: страница %s, найдено ссылок: %s",
                         self.source_id, response.meta["page"], len(links))

        for link in links:
            if len(self.seen_urls) >= self.cfg["max_items"]:
                return
            if link in self.seen_urls:
                continue
            self.seen_urls.add(link)
            yield scrapy.Request(
                link,
                callback=self.parse_publication,
                errback=self.on_error,
                meta={"kind": "publication"},
            )

        # Промежуточные листинги: например, каталог банков -> страница банка -> отзыв
        follow_pattern = discovery.get("follow_pattern")
        if mode == "links" and follow_pattern:
            for link in discover_links(html, response.url, follow_pattern):
                if not self.can_request_listing():
                    break
                if link not in self.seen_listings:
                    self.seen_listings.add(link)
                    yield self.listing_request(link)

        next_selector = discovery.get("next_page")
        if next_selector and self.can_request_listing():
            next_url = response.css(next_selector).get()
            if next_url:
                yield self.listing_request(response.urljoin(next_url))

    def parse_publication(self, response):
        if self.is_blocked(response):
            return
        self.publication_pages_ok += 1

        pub = extract_publication(
            response.text,
            response.url,
            fetched_at=datetime.now(timezone.utc),
            cfg=self.cfg,
            run_id=self.run_id,
        )
        if is_rejected(pub):
            self.logger.info("%s: отклонено %s %s", self.source_id, pub.url, pub.quality_flags)
            self.rejected.append(asdict(pub))
        else:
            self.accepted.append(asdict(pub))

    def is_blocked(self, response) -> bool:
        # Редирект на чужой домен (авторизация, антибот) вместо контента
        host = urlparse(response.url).netloc
        if host != self.domain and not host.endswith("." + self.domain):
            self.block_reason = f"redirected to {host}"
            self.logger.warning("%s: %s", self.source_id, self.block_reason)
            return True

        markers = self.cfg.get("block_markers", [])
        text = response.text.lower()
        for marker in markers:
            if marker.lower() in text:
                self.block_reason = f"block marker '{marker}' on {response.url}"
                self.logger.warning("%s: %s", self.source_id, self.block_reason)
                return True
        return False

    def on_error(self, failure):
        request = failure.request
        if failure.check(HttpError):
            code = failure.value.response.status
            self.http_errors[str(code)] += 1
            self.logger.warning("%s: HTTP %s %s", self.source_id, code, request.url)
        elif failure.check(IgnoreRequest):
            self.other_errors[f"robots_forbidden:{urlparse(request.url).netloc}"] += 1
            self.logger.warning("%s: запрещено robots.txt %s", self.source_id, request.url)
        else:
            name = failure.type.__name__
            self.other_errors[name] += 1
            self.logger.warning("%s: %s %s", self.source_id, name, request.url)

    def closed(self, reason):
        status, status_reason = self.source_status(reason)
        summary = {
            "run_id": self.run_id,
            "source_id": self.source_id,
            "status": status,
            "reason": status_reason,
            "started_at": self.started_at.isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "listing_pages_ok": self.listing_pages_ok,
            "publication_pages_ok": self.publication_pages_ok,
            "links_found": len(self.seen_urls),
            "accepted": len(self.accepted),
            "rejected": len(self.rejected),
            "http_errors": dict(self.http_errors),
            "other_errors": dict(self.other_errors),
            "spider_exceptions": self.crawler.stats.get_value("spider_exceptions/count", 0),
        }

        self.output_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(self.output_dir / f"{self.source_id}.jsonl", self.accepted)
        write_jsonl(self.output_dir / f"{self.source_id}.rejected.jsonl", self.rejected)
        (self.output_dir / f"{self.source_id}.summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        self.logger.info("%s: статус %s, принято %s, отклонено %s",
                         self.source_id, status, len(self.accepted), len(self.rejected))

    def source_status(self, close_reason: str) -> tuple[str, str | None]:
        if self.accepted:
            return "success", None

        if self.block_reason:
            return "unavailable", self.block_reason

        errors = {**self.http_errors, **self.other_errors}
        if errors and self.listing_pages_ok == 0:
            return "unavailable", f"no listing page loaded, errors: {errors}"
        if errors and self.seen_urls and self.publication_pages_ok == 0:
            return "unavailable", f"no publication page loaded, errors: {errors}"

        exceptions = self.crawler.stats.get_value("spider_exceptions/count", 0)
        if close_reason != "finished" or exceptions:
            return "failed", f"close reason {close_reason}, spider exceptions {exceptions}"

        if self.rejected:
            return "empty", f"all {len(self.rejected)} publications rejected by quality check"
        return "empty", f"no publications found, links: {len(self.seen_urls)}"


def write_jsonl(path: Path, records: list[dict]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def run(source_id: str, run_id: str, output_dir: str | None = None) -> Path:
    cfg = get_source(source_id)
    settings = {**SETTINGS, "DOWNLOAD_DELAY": cfg["download_delay"]}
    process = CrawlerProcess(settings, install_root_handler=True)
    process.crawl(PublicationSpider, source=source_id, run_id=run_id, output_dir=output_dir)
    process.start()

    out = Path(output_dir) if output_dir else OUTPUT_ROOT / run_id
    return out / f"{source_id}.summary.json"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-dir")
    args = parser.parse_args()

    summary_path = run(args.source, args.run_id, args.output_dir)
    if not summary_path.is_file():
        logging.error("summary was not written: %s", summary_path)
        raise SystemExit(1)
