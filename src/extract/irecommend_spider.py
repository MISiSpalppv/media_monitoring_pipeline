import json

import scrapy
import trafilatura


class IRecommendSpider(scrapy.Spider):
    name = "irecommend"

    start_urls = [
        "https://irecommend.ru/content/sait-ozontravel-0"
    ]

    custom_settings = {
        "DOWNLOAD_DELAY": 1,
        "ROBOTSTXT_OBEY": True,
    }

    def parse(self, response):
        cards = response.css("div.reviews-list-item")

        self.logger.info(
            "Найдено карточек отзывов: %s",
            len(cards)
        )

        if not cards:
            self.logger.warning("Карточки отзывов не найдены")
            return

        for card in cards:
            links = card.css('a[href*="/content/"]')

            main_link = max(
                links,
                key=lambda link: len(
                    " ".join(link.css("::text").getall()).strip()
                ),
                default=None
            )

            if main_link is None:
                continue

            review_url = response.urljoin(
                main_link.attrib["href"]
            )

            yield response.follow(
                review_url,
                callback=self.parse_review
            )

    def parse_review(self, response):
        author = " ".join(
            response.css(".reviewHeader .reviewer ::text").getall()
        ).strip()

        published_at = response.css(
            ".reviewHeader .dtreviewed::text"
        ).get()

        title = response.css("h2.reviewTitle").xpath("normalize-space(./a)").get()

        text_parts = response.css(
            ".reviewText ::text"
        ).getall()

        text = " ".join(
            part.strip()
            for part in text_parts
            if part.strip()
        )

        yield {
            "source_url": self.start_urls[0],
            "url": response.url,
            "title": title.strip() if title else None,
            "author": author.strip() if author else None,
            "published_at": published_at.strip() if published_at else None,
            "text": text,
        }