from pathlib import Path
from bs4 import BeautifulSoup

PROJECT_ROOT = Path(__file__).resolve().parent.parent

html = (PROJECT_ROOT / "data/raw/irecommend.html").read_text(
    encoding="utf-8"
)

soup = BeautifulSoup(html, "html.parser")

for link in soup.select('a[href*="/content/"]')[:15]:
    print("URL:", link.get("href"))
    print("TEXT:", link.get_text(" ", strip=True)[:100])

    parent = link.parent
    print("PARENT:", parent.name, parent.get("class") if parent else None)

    print("-" * 60)