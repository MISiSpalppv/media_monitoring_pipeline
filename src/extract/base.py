from abc import ABC, abstractmethod
from typing import Any
from src.models import Publication


class BaseScraper(ABC):
    """Базовый интерфейс для всех парсеров."""

    def __init__(self, source_url: str):
        self.source_url = source_url

    @abstractmethod
    def fetch(self) -> str:
        """Получить HTML страницы."""
        pass

    @abstractmethod
    def parse(self, html: str) -> list[Publication]:
        """Извлечь публикации из HTML."""
        pass

    def run(self) -> list[Publication]:
        """Запустить полный цикл сбора данных."""
        html = self.fetch()
        return self.parse(html)