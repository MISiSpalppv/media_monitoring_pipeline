from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup


PROJECT_ROOT = Path(__file__).resolve().parents[2]
html = (PROJECT_ROOT / "data/raw/irecommend.html").read_text(encoding="utf-8")

soup = BeautifulSoup(html, "html.parser")

patterns = Counter()

for tag in soup.find_all(["div", "article", "li"]):
    classes = tag.get("class", [])

    if not classes:
        continue

    # Сортируем классы, чтобы порядок в HTML не влиял на группировку
    signature = (tag.name, tuple(sorted(classes)))

    # Рассматриваем только блоки с текстом и ссылками
    if len(tag.get_text(" ", strip=True)) < 50:
        continue

    if not tag.find("a", href=True):
        continue

    patterns[signature] += 1

print("Наиболее распространённые HTML-структуры:\n")

for (tag, classes), count in patterns.most_common(20):
    print(f"{count:3} | {tag} | {' '.join(classes)}")


print("\nАнализ трёх наиболее частых структур:\n")

for (tag_name, classes), count in patterns.most_common(3):
    elements = soup.find_all(
        tag_name,
        class_=lambda value: value and all(
            cls in value.split() for cls in classes
        )
    )

    # Проверяем точное совпадение набора классов
    elements = [
        el for el in elements
        if tuple(sorted(el.get("class", []))) == classes
    ]

    print(f"СТРУКТУРА: {tag_name} | {' '.join(classes)}")
    print(f"Количество: {len(elements)}")

    if elements:
        example = elements[0]

        print("Текст:", example.get_text(" ", strip=True)[:300])
        print("Ссылок:", len(example.find_all("a", href=True)))
        print("Тегов time:", len(example.find_all("time")))
        print("Ссылок на изображения:", len(example.find_all("img")))

    print("-" * 60)

review_cards = soup.select("div.reviews-list-item")
list_items = soup.select("li.item")

nested_count = 0

for item in list_items:
    if item.find_parent("div", class_="reviews-list-item"):
        nested_count += 1

print("\nПроверка вложенности:")
print("Карточек отзывов:", len(review_cards))
print("Элементов li.item:", len(list_items))
print("li.item внутри карточек отзывов:", nested_count)