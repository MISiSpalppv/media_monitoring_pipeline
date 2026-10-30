import httpx
from bs4 import BeautifulSoup


URL = (
    "https://irecommend.ru/content/"
    "vy-nikuda-ne-uletite-s-ozon-trevel-oba-puteshestviya-"
    "proval-podderzhka-za-dopolnitelnuyu-pla"
)

response = httpx.get(
    URL,
    follow_redirects=True,
    timeout=20
)
response.raise_for_status()

soup = BeautifulSoup(response.text, "html.parser")

keywords = ["review", "comment", "content", "text"]

for keyword in keywords:
    print(f"\n=== {keyword.upper()} ===")

    matches = soup.select(
        f'[class*="{keyword}"], [id*="{keyword}"]'
    )

    for element in matches[:15]:
        print(
            element.name,
            "class:", element.get("class"),
            "id:", element.get("id"),
            "text:", element.get_text(" ", strip=True)[:100]
        )