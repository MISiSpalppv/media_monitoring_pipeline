import pytest
from scrapy.utils.test import get_crawler

from src.extract.spider import PublicationSpider


@pytest.fixture
def spider(tmp_path):
    crawler = get_crawler(PublicationSpider)
    return PublicationSpider.from_crawler(
        crawler, source="livejournal_5koleso", run_id="test", output_dir=str(tmp_path)
    )


def test_success_when_something_accepted(spider):
    spider.listing_pages_ok = 1
    spider.accepted = [{"url": "x"}]
    assert spider.source_status("finished")[0] == "success"


def test_unavailable_when_listing_failed(spider):
    spider.http_errors["521"] = 1
    status, reason = spider.source_status("finished")
    assert status == "unavailable"
    assert "521" in reason


def test_unavailable_when_all_publications_failed(spider):
    spider.listing_pages_ok = 1
    spider.seen_urls = {"a", "b"}
    spider.http_errors["429"] = 2
    assert spider.source_status("finished")[0] == "unavailable"


def test_empty_is_not_success(spider):
    spider.listing_pages_ok = 1
    assert spider.source_status("finished")[0] == "empty"


def test_all_rejected_is_empty(spider):
    spider.listing_pages_ok = 1
    spider.publication_pages_ok = 1
    spider.rejected = [{"url": "x"}]
    assert spider.source_status("finished")[0] == "empty"


def test_failed_on_spider_exceptions(spider):
    spider.listing_pages_ok = 1
    spider.crawler.stats.open_spider()
    spider.crawler.stats.set_value("spider_exceptions/count", 3)
    assert spider.source_status("finished")[0] == "failed"


def test_closed_writes_summary(spider, tmp_path):
    spider.crawler.stats.open_spider()
    spider.listing_pages_ok = 1
    spider.accepted = [{"url": "x"}]
    spider.closed("finished")
    assert (tmp_path / "livejournal_5koleso.summary.json").is_file()
    assert (tmp_path / "livejournal_5koleso.jsonl").read_text(encoding="utf-8").count("\n") == 1
