from datetime import datetime, timezone

import pytest

from src.transform.enrich import (
    category_scores, duplicate_groups, enrich, filter_latin, find_brands,
    keyword_candidates, lemmas, load_analytics, tfidf_keywords,
)


@pytest.fixture(scope="module")
def cfg():
    return load_analytics()


def test_lemmas_normalize_word_forms():
    assert lemmas("Менеджеров паролей") == lemmas("менеджер пароля") == ["менеджер", "пароль"]


def test_category_phrase_matches_any_form(cfg):
    scores = category_scores("Обзор менеджеров паролей", None, cfg)
    assert "passwords_encryption" in scores


def test_title_hit_counts_more_than_text(cfg):
    # одно упоминание в тексте ниже порога, в заголовке - выше
    assert "fraud" not in category_scores("Отзыв", "Похоже на мошенничество.", cfg)
    assert "fraud" in category_scores("Мошенники", "Текст без ключевых слов.", cfg)


def test_machine_learning_is_not_auto(cfg):
    text = "Антивирус использует машинное обучение и машинный анализ угроз."
    assert "auto" not in category_scores("Антивирус", text, cfg)


def test_brands_with_aliases(cfg):
    found = find_brands("Сравнение", "Касперский против Dr.Web и ESET NOD32. Kaspersky лучше.", cfg)
    assert found == {"Kaspersky": 2, "Dr.Web": 1, "ESET": 2}


def test_brand_word_boundaries(cfg):
    # "avg" внутри слова, "озонатор" и "сбережения" брендами не считаются
    assert find_brands(None, "savgol filter, озонатор воздуха, сбережения", cfg) == {}
    found = find_brands(None, "Купил в Озоне, перевёл через Сбербанк Онлайн, ozon.travel", cfg)
    assert found == {"Ozon": 2, "Сбер": 1}


def test_tfidf_prefers_specific_words():
    docs = {
        1: ["банк", "вклад", "вклад", "ставка"],
        2: ["банк", "кредит"],
        3: ["банк", "карта"],
    }
    top = tfidf_keywords(docs, {1, 2, 3}, top_n=2)
    # "банк" есть во всех документах, "вклад" только в первом
    assert top[1][0][0] == "вклад"
    assert "банк" not in [word for word, _ in top[1]]


def test_latin_nicknames_are_dropped(cfg):
    candidates = {
        1: keyword_candidates("Cryptomator", "Cryptomator шифрует файлы. Версия 2.0 (Katafrakt)",
                              cfg["stop_lemmas"]),
        2: keyword_candidates("KeePassDX", "Хранит пароли. Синхронизация через Cryptomator.",
                              cfg["stop_lemmas"]),
    }
    docs = filter_latin(candidates, {1: "Cryptomator", 2: "KeePassDX"})
    assert "katafrakt" not in docs[1]
    assert "cryptomator" in docs[1] and "cryptomator" in docs[2]


def test_forum_credits_are_not_keywords(cfg):
    # частые выкладывающие встречаются во многих темах, df-фильтр их не отсекает
    text = "Версия: 4.0 Key | Paid (Katafrakt) Версия: 3.9 (alex0047) сборка от alex0047"
    words = [lemma for lemma, _ in keyword_candidates("Тема", text, cfg["stop_lemmas"])]
    assert "katafrakt" not in words
    assert "alex0047" not in words


def test_near_duplicates_grouped_to_earliest():
    text = "Что воровали с автомобилей в СССР и как с этим боролись: колеса, дворники, зеркала. " * 5
    groups = duplicate_groups(
        [10, 20, 30],
        {10: text, 20: text + " Подписывайтесь.", 30: "Совсем другой текст про шины и бензин."},
        threshold=0.7,
    )
    assert groups == {10: 10, 20: 10, 30: 30}


def test_enrich_rows(cfg):
    rows = [
        {"id": 1, "title": "Мошенники", "text": "Банк списал деньги, мошенники звонили. " * 3,
         "published_at": datetime(2026, 10, 1, tzinfo=timezone.utc), "metadata": {"rating": "1"}},
        {"id": 2, "title": "Антивирус Kaspersky", "text": "Антивирус Kaspersky нашёл троян. " * 3,
         "published_at": datetime(2026, 10, 2, tzinfo=timezone.utc), "metadata": {}},
    ]
    result = enrich(rows, cfg)
    features = {row[0]: row for row in result["features"]}

    assert features[1][3] == "fraud"
    assert features[1][4] == 1.0
    assert features[2][3] == "security_software"
    assert features[2][4] is None
    # одно упоминание в заголовке и три в тексте
    assert (2, "Kaspersky", "security_vendor", 4) in result["brands"]
    assert all(row[5] is None for row in result["features"])
