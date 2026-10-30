from pathlib import Path
from collections import Counter
from urllib.parse import urlparse

from src.extract.discovery import discover_links


# Путь к корню проекта
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Загружаем сохранённый HTML
html = (PROJECT_ROOT / "data/raw/irecommend.html").read_text(
    encoding="utf-8"
)

# Извлекаем все внутренние ссылки
links = discover_links(
    html,
    base_url="https://irecommend.ru/content/sait-ozontravel-0"
)

print(f"Всего найдено ссылок: {len(links)}")

print("\nПервые 20 ссылок:")
for link in links[:20]:
    print(link)


# Анализируем структуру URL
categories = Counter()

for link in links:
    path = urlparse(link).path
    parts = path.strip("/").split("/")

    category = parts[0] if parts[0] else "root"
    categories[category] += 1

print("\nРаспределение ссылок по первому сегменту URL:")

for category, count in categories.most_common():
    print(f"{category}: {count}")