from pathlib import Path
import json

import trafilatura


PROJECT_ROOT = Path(__file__).resolve().parents[2]
html = (PROJECT_ROOT / "data" / "raw" / "irecommend.html").read_text(encoding="utf-8")

result = trafilatura.extract(
    html,
    output_format="json",
    with_metadata=True,
    include_comments=False,
)

if result:
    data = json.loads(result)

    print("Title:", data.get("title"))
    print("Author:", data.get("author"))
    print("Date:", data.get("date"))
    print("Text length:", len(data.get("text") or ""))
    print("\nText preview:")
    print((data.get("text") or "")[:1000])
else:
    print("Trafilatura could not extract content")