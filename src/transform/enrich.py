"""Аналитические признаки публикаций из STAGING.

Для каждой публикации: объём текста, категории по словарю, упоминания
брендов, ключевые слова (TF-IDF по леммам) и почти-дубли (шинглы).
Словари лежат в analytics.yaml.

Признаки пересчитываются целиком при каждом запуске: IDF и группы дублей
зависят от всего корпуса, а на объёмах прототипа это секунды.
"""
import logging
import math
import re
from collections import Counter
from functools import lru_cache
from pathlib import Path

import pymorphy3
import yaml

from src.config import PROJECT_ROOT


ANALYTICS_FILE = PROJECT_ROOT / "analytics.yaml"

TOKEN = re.compile(r"[a-zа-яё][a-zа-яё0-9+]*(?:-[a-zа-яё0-9]+)*", re.IGNORECASE)
URL = re.compile(r"https?://\S+|www\.\S+")
# одно латинское слово в скобках: на форумах так подписывают автора сборки, "Paid (Nick)"
NICK_IN_PARENS = re.compile(r"\(\s*[a-z0-9_.@-]+\s*\)", re.IGNORECASE)
HAS_DIGIT = re.compile(r"\d")
SHINGLE_SIZE = 5
# части речи, из которых берутся ключевые слова; LATN - слова латиницей (названия)
KEYWORD_TAGS = ("NOUN", "LATN")
# pymorphy3 приводит "деньги" к редкой форме единственного числа
LEMMA_FIXES = {"деньга": "деньги"}

log = logging.getLogger(__name__)

_morph = None


def load_analytics(path: Path = ANALYTICS_FILE) -> dict:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    for category in cfg["categories"].values():
        category["lemma_terms"] = [" ".join(lemmas(term)) for term in category["terms"]]
    for brand in cfg["brands"].values():
        brand["regex"] = [re.compile(p) for p in brand["patterns"]]
    cfg["stop_lemmas"] = set(cfg.get("stop_lemmas", []))
    return cfg


def tokenize(text: str | None) -> list[str]:
    if not text:
        return []
    return TOKEN.findall(URL.sub(" ", text.lower().replace("ё", "е")))


@lru_cache(maxsize=200_000)
def parse_word(word: str) -> tuple[str, str]:
    global _morph
    if _morph is None:
        _morph = pymorphy3.MorphAnalyzer()
    parsed = _morph.parse(word)[0]
    tag = "LATN" if "LATN" in parsed.tag else str(parsed.tag.POS or "")
    lemma = parsed.normal_form.replace("ё", "е")
    return LEMMA_FIXES.get(lemma, lemma), tag


def lemmas(text: str | None) -> list[str]:
    return [parse_word(word)[0] for word in tokenize(text)]


def category_scores(title: str | None, text: str | None, cfg: dict) -> dict[str, int]:
    title_lemmas = " " + " ".join(lemmas(title)) + " "
    text_lemmas = " " + " ".join(lemmas(text)) + " "

    scores = {}
    for category_id, category in cfg["categories"].items():
        score = 0
        for term in category["lemma_terms"]:
            needle = f" {term} "
            score += title_lemmas.count(needle) * cfg["title_weight"]
            score += text_lemmas.count(needle)
        if score >= cfg["min_score"]:
            scores[category_id] = score
    return scores


def find_brands(title: str | None, text: str | None, cfg: dict) -> dict[str, int]:
    haystack = f"{title or ''}\n{text or ''}".lower()
    found = {}
    for name, brand in cfg["brands"].items():
        count = sum(len(regex.findall(haystack)) for regex in brand["regex"])
        if count:
            found[name] = count
    return found


def keyword_candidates(title: str | None, text: str | None, stop: set[str]) -> list[tuple[str, str]]:
    text = NICK_IN_PARENS.sub(" ", text or "")
    result = []
    for word in tokenize(f"{title or ''} {text}"):
        if HAS_DIGIT.search(word):
            continue
        lemma, tag = parse_word(word)
        if tag in KEYWORD_TAGS and len(lemma) >= 3 and lemma not in stop:
            result.append((lemma, tag))
    return result


def filter_latin(candidates: dict[int, list[tuple[str, str]]],
                 titles: dict[int, str | None]) -> dict[int, list[str]]:
    """Латинское слово остаётся ключевым, если оно есть в заголовке или
    встречается хотя бы в двух публикациях. Так проходят названия продуктов,
    а ники пользователей и мусор из списков версий отсекаются."""
    latin_df = Counter()
    for words in candidates.values():
        latin_df.update({lemma for lemma, tag in words if tag == "LATN"})

    result = {}
    for doc_id, words in candidates.items():
        title_words = set(tokenize(titles[doc_id]))
        result[doc_id] = [
            lemma for lemma, tag in words
            if tag != "LATN" or lemma in title_words or latin_df[lemma] >= 2
        ]
    return result


def tfidf_keywords(docs: dict[int, list[str]], idf_docs: set[int],
                   top_n: int) -> dict[int, list[tuple[str, float]]]:
    """TF-IDF по леммам. IDF считается только по idf_docs (без дублей),
    иначе перепечатки занижали бы вес своих же слов."""
    df = Counter()
    for doc_id in idf_docs:
        df.update(set(docs[doc_id]))
    n = len(idf_docs)

    result = {}
    for doc_id, words in docs.items():
        if not words:
            result[doc_id] = []
            continue
        tf = Counter(words)
        weights = {
            word: count / len(words) * (math.log((n + 1) / (df[word] + 1)) + 1)
            for word, count in tf.items()
        }
        top = sorted(weights.items(), key=lambda item: (-item[1], item[0]))[:top_n]
        result[doc_id] = [(word, round(weight, 6)) for word, weight in top]
    return result


def shingles(text: str | None, size: int = SHINGLE_SIZE) -> set[tuple[str, ...]]:
    words = tokenize(text)
    if len(words) < size:
        return {tuple(words)} if words else set()
    return {tuple(words[i:i + size]) for i in range(len(words) - size + 1)}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def duplicate_groups(order: list[int], texts: dict[int, str | None],
                     threshold: float) -> dict[int, int]:
    """Для каждой публикации возвращает id оригинала группы почти-дублей.

    order задаёт приоритет: первая публикация группы считается оригиналом
    (вызывающий код сортирует по дате публикации). Сравнение попарное,
    O(n^2): для прототипа достаточно, для больших объёмов нужен MinHash/LSH.
    """
    sets = {doc_id: shingles(texts[doc_id]) for doc_id in order}
    parent = {doc_id: doc_id for doc_id in order}

    def find(doc_id):
        while parent[doc_id] != doc_id:
            parent[doc_id] = parent[parent[doc_id]]
            doc_id = parent[doc_id]
        return doc_id

    position = {doc_id: i for i, doc_id in enumerate(order)}
    for i, a in enumerate(order):
        for b in order[i + 1:]:
            if jaccard(sets[a], sets[b]) >= threshold:
                root_a, root_b = find(a), find(b)
                if root_a != root_b:
                    # корнем остаётся более ранняя публикация
                    if position[root_a] < position[root_b]:
                        parent[root_b] = root_a
                    else:
                        parent[root_a] = root_b

    return {doc_id: find(doc_id) for doc_id in order}


def enrich(rows: list[dict], cfg: dict) -> dict[str, list[tuple]]:
    """rows: id, title, text, published_at, metadata. Возвращает строки для таблиц признаков."""
    order = [row["id"] for row in sorted(
        rows, key=lambda r: (r["published_at"] is None, r["published_at"] or 0, r["id"])
    )]
    by_id = {row["id"]: row for row in rows}

    canonical = duplicate_groups(order, {i: by_id[i]["text"] for i in order},
                                 cfg["duplicate_threshold"])
    originals = {doc_id for doc_id, root in canonical.items() if doc_id == root}

    candidates = {i: keyword_candidates(by_id[i]["title"], by_id[i]["text"], cfg["stop_lemmas"])
                  for i in order}
    docs = filter_latin(candidates, {i: by_id[i]["title"] for i in order})
    keywords = tfidf_keywords(docs, originals, cfg["keywords_per_publication"])

    features, categories, keyword_rows, brand_rows = [], [], [], []
    for doc_id in order:
        row = by_id[doc_id]
        scores = category_scores(row["title"], row["text"], cfg)
        primary = max(scores, key=lambda c: (scores[c], c)) if scores else None
        brands = find_brands(row["title"], row["text"], cfg)
        rating = (row.get("metadata") or {}).get("rating")

        features.append((
            doc_id,
            len(row["text"] or ""),
            len(tokenize(row["text"])),
            primary,
            float(rating) if rating not in (None, "") else None,
            canonical[doc_id] if canonical[doc_id] != doc_id else None,
        ))
        categories.extend((doc_id, c, s, c == primary) for c, s in scores.items())
        keyword_rows.extend((doc_id, word, weight, rank)
                            for rank, (word, weight) in enumerate(keywords[doc_id], 1))
        brand_rows.extend((doc_id, name, cfg["brands"][name]["group"], count)
                          for name, count in brands.items())

    return {
        "features": features,
        "categories": categories,
        "keywords": keyword_rows,
        "brands": brand_rows,
    }


def run(conn) -> int:
    cfg = load_analytics()
    rows = conn.execute(
        "SELECT id, title, text, published_at, metadata FROM staging.publications"
    ).fetchall()
    columns = ("id", "title", "text", "published_at", "metadata")
    result = enrich([dict(zip(columns, row)) for row in rows], cfg)

    conn.execute("""
        TRUNCATE staging.publication_features, staging.publication_categories,
                 staging.publication_keywords, staging.publication_brands
    """)
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO staging.publication_features "
            "(publication_id, char_count, word_count, primary_category, rating, duplicate_of) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            result["features"],
        )
        cur.executemany(
            "INSERT INTO staging.publication_categories (publication_id, category, score, is_primary) "
            "VALUES (%s, %s, %s, %s)",
            result["categories"],
        )
        cur.executemany(
            "INSERT INTO staging.publication_keywords (publication_id, keyword, weight, rank) "
            "VALUES (%s, %s, %s, %s)",
            result["keywords"],
        )
        cur.executemany(
            "INSERT INTO staging.publication_brands (publication_id, brand, brand_group, mentions) "
            "VALUES (%s, %s, %s, %s)",
            result["brands"],
        )

    sync_categories(conn, cfg)
    log.info("признаки: %s публикаций, дублей %s, категорий %s, брендов %s",
             len(result["features"]),
             sum(1 for f in result["features"] if f[5] is not None),
             len(result["categories"]), len(result["brands"]))
    return len(result["features"])


def sync_categories(conn, cfg: dict) -> None:
    """Справочник категорий для витрин: человекочитаемые названия."""
    conn.execute("DELETE FROM staging.categories")
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO staging.categories (category, name) VALUES (%s, %s)",
            [(cid, c["name"]) for cid, c in cfg["categories"].items()],
        )
