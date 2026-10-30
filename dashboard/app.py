"""Дашборд медиамониторинга по витринам mart.*

    streamlit run dashboard/app.py
"""
import re
import sys
from datetime import date
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# путь нужен, чтобы запускать "streamlit run dashboard/app.py" из корня проекта

from src.db.connection import connect


st.set_page_config(page_title="Медиамониторинг", layout="wide")

STATUS_LABELS = {
    "success": "работает",
    "empty": "нет публикаций",
    "unavailable": "недоступен",
    "failed": "ошибка",
}
GROUP_LABELS = {
    "security_vendor": "Вендоры защитного ПО",
    "password_manager": "Менеджеры паролей",
    "bank": "Банки",
    "marketplace": "Маркетплейсы",
}
NO_CATEGORY = "Без категории"
TIMEZONE = "Europe/Moscow"


def explain_reason(reason: str | None) -> str:
    """Причина недоступности из ops.source_runs в читаемом виде."""
    # pandas отдаёт пустую причину как NaN
    if not isinstance(reason, str) or not reason:
        return ""
    parts = []
    for host in re.findall(r"robots_forbidden:([\w.-]+)", reason):
        parts.append(f"запрещено robots.txt ({host})")
    for code in re.findall(r"'(\d{3})'", reason):
        parts.append(f"HTTP {code}")
    redirect = re.search(r"redirected to ([\w.-]+)", reason)
    if redirect:
        parts.append(f"перенаправление на {redirect.group(1)}")
    if "Timeout" in reason:
        parts.append("таймаут")
    return ", ".join(parts) or reason


def query(sql: str, params: tuple = ()) -> pd.DataFrame:
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params)
        columns = [c.name for c in cur.description]
        return pd.DataFrame(cur.fetchall(), columns=columns)


@st.cache_data(ttl=300)
def load_data() -> dict[str, pd.DataFrame]:
    publications = query("""
        SELECT publication_id, source_id, source_name, source_type, publication_url,
               title, author, published_at, published_date, first_seen_date,
               text_preview, word_count, primary_category, primary_category_name,
               rating, product, is_duplicate, duplicate_of, categories, brands, keywords
        FROM mart.publications
    """)
    for column in ("published_date", "first_seen_date"):
        publications[column] = pd.to_datetime(publications[column])
    # в БД timestamptz, показываем по Москве, как и даты в витринах
    publications["published_at"] = pd.to_datetime(publications["published_at"], utc=True).dt.tz_convert(TIMEZONE)
    publications["rating"] = publications["rating"].astype(float)
    publications["primary_category_name"] = publications["primary_category_name"].fillna(NO_CATEGORY)

    return {
        "publications": publications,
        "categories": query("""
            SELECT pc.publication_id, pc.category, c.name AS category_name, pc.is_primary
            FROM staging.publication_categories AS pc
            JOIN staging.categories AS c USING (category)
        """),
        "keywords": query("SELECT publication_id, keyword, weight FROM mart.publication_keywords"),
        "brands": query("SELECT publication_id, brand, brand_group, mentions FROM mart.brand_mentions"),
        "health": query("SELECT * FROM mart.source_health ORDER BY publications DESC, source_id"),
        "last_run": query("""
            SELECT run_id, status, finished_at, sources_total, sources_success
            FROM ops.pipeline_runs WHERE finished_at IS NOT NULL
            ORDER BY finished_at DESC LIMIT 1
        """),
    }


@st.cache_data(ttl=300)
def load_text(publication_id: int) -> str:
    df = query("SELECT text FROM mart.publications WHERE publication_id = %s", (publication_id,))
    return df["text"].iloc[0] if not df.empty else ""


def sidebar_filters(pubs: pd.DataFrame, health: pd.DataFrame) -> dict:
    st.sidebar.header("Фильтры")

    basis = st.sidebar.radio(
        "Дата",
        ["published_date", "first_seen_date"],
        format_func={"published_date": "публикации", "first_seen_date": "первого сбора"}.get,
        help="У тем 4PDA дата публикации - дата создания темы, она может быть старой. "
             "Дата первого сбора показывает, когда публикация попала в систему.",
    )

    dates = pubs[basis].dropna()
    min_date = dates.min().date() if not dates.empty else date.today()
    max_date = dates.max().date() if not dates.empty else date.today()
    # по умолчанию весь диапазон: иначе старые темы 4PDA молча выпадают из выборки
    period = st.sidebar.date_input("Период", (min_date, max_date),
                                   min_value=min_date, max_value=max_date)
    # пока пользователь выбирает вторую дату, date_input отдаёт одну
    start, end = (period[0], period[-1]) if isinstance(period, (tuple, list)) else (period, period)

    names = dict(zip(health["source_id"], health["source_name"]))
    with_data = health.loc[health["publications"] > 0, "source_id"].tolist()
    sources = st.sidebar.multiselect("Источники", list(names), default=with_data,
                                     format_func=names.get, placeholder="выберите источники")

    category_names = sorted(pubs["primary_category_name"].unique(), key=lambda c: (c == NO_CATEGORY, c))
    categories = st.sidebar.multiselect("Основная категория", category_names,
                                        placeholder="все категории")
    with_duplicates = st.sidebar.checkbox("Учитывать почти-дубли", value=False)

    return {
        "basis": basis,
        "start": pd.Timestamp(start),
        "end": pd.Timestamp(end),
        "sources": sources,
        "categories": categories,
        "with_duplicates": with_duplicates,
    }


def apply_filters(pubs: pd.DataFrame, f: dict) -> pd.DataFrame:
    mask = (
        pubs[f["basis"]].between(f["start"], f["end"])
        & pubs["source_id"].isin(f["sources"])
    )
    if f["categories"]:
        mask &= pubs["primary_category_name"].isin(f["categories"])
    if not f["with_duplicates"]:
        mask &= ~pubs["is_duplicate"]
    return pubs[mask]


def kpis(selected: pd.DataFrame, brands: pd.DataFrame, health: pd.DataFrame) -> None:
    available = (health["last_status"] == "success").sum()
    vendor_mentions = brands[
        brands["publication_id"].isin(selected["publication_id"])
        & (brands["brand_group"] == "security_vendor")
    ]
    ratings = selected["rating"].dropna()

    cols = st.columns(5)
    cols[0].metric("Публикаций", len(selected))
    cols[1].metric("Источников с данными", selected["source_id"].nunique())
    cols[2].metric("Источники доступны", f"{available} из {len(health)}",
                   help="По последнему запуску пайплайна")
    cols[3].metric("Публикаций с вендорами защитного ПО", vendor_mentions["publication_id"].nunique())
    cols[4].metric("Средняя оценка в отзывах", f"{ratings.mean():.2f}" if len(ratings) else "—",
                   help=f"Оценок в выборке: {len(ratings)}. Оценка есть только у отзывов Отзовика.")


def overview_tab(selected: pd.DataFrame, f: dict) -> None:
    left, right = st.columns([3, 2])

    with left:
        st.subheader("Динамика")
        span = (f["end"] - f["start"]).days
        default = "D" if span <= 60 else "W" if span <= 730 else "Y"
        steps = {"D": "день", "W": "неделя", "M": "месяц", "Y": "год"}
        step = st.radio("Шаг", list(steps), index=list(steps).index(default),
                        format_func=steps.get, horizontal=True, label_visibility="collapsed")
        label_format = {"D": "%d.%m.%Y", "W": "%d.%m.%Y", "M": "%m.%Y", "Y": "%Y"}[step]
        series = (
            selected.assign(period=selected[f["basis"]].dt.to_period(step).dt.start_time)
            .groupby(["period", "source_name"]).size().reset_index(name="publications")
            .sort_values("period")
        )
        series["label"] = series["period"].dt.strftime(label_format)
        # порядковая ось: на временной оси столбцы за редкие периоды получаются в пиксель шириной
        chart = alt.Chart(series).mark_bar().encode(
            x=alt.X("label:O", sort=None, title=None, axis=alt.Axis(labelAngle=0, labelOverlap=True)),
            y=alt.Y("publications:Q", title="Публикаций"),
            color=alt.Color("source_name:N", title="Источник", legend=alt.Legend(orient="bottom", columns=2)),
            tooltip=[alt.Tooltip("label:O", title="Период"), alt.Tooltip("source_name:N", title="Источник"),
                     alt.Tooltip("publications:Q", title="Публикаций")],
        )
        st.altair_chart(chart, width="stretch")

    with right:
        st.subheader("По источникам")
        by_source = selected.groupby("source_name").agg(
            publications=("publication_id", "count"),
            avg_words=("word_count", "mean"),
            last_date=(f["basis"], "max"),
        ).reset_index().sort_values("publications", ascending=False)
        st.dataframe(
            by_source,
            hide_index=True,
            width="stretch",
            column_config={
                "source_name": "Источник",
                "publications": "Публикаций",
                "avg_words": st.column_config.NumberColumn("Слов в среднем", format="%d"),
                "last_date": st.column_config.DateColumn("Последняя"),
            },
        )


def topics_tab(selected: pd.DataFrame, categories: pd.DataFrame, keywords: pd.DataFrame) -> None:
    left, right = st.columns(2)

    with left:
        st.subheader("Темы")
        st.caption("Публикация может относиться к нескольким темам, учитываются все.")
        cats = categories[categories["publication_id"].isin(selected["publication_id"])]
        counts = cats.groupby("category_name").size().reset_index(name="publications")
        chart = alt.Chart(counts).mark_bar().encode(
            x=alt.X("publications:Q", title="Публикаций"),
            y=alt.Y("category_name:N", sort="-x", title=None, axis=alt.Axis(labelLimit=250)),
            tooltip=[alt.Tooltip("category_name:N", title="Тема"),
                     alt.Tooltip("publications:Q", title="Публикаций")],
        )
        st.altair_chart(chart, width="stretch")

    with right:
        st.subheader("Ключевые слова")
        kw = keywords[keywords["publication_id"].isin(selected["publication_id"])]
        top = (
            kw.groupby("keyword")
            .agg(publications=("publication_id", "nunique"), weight=("weight", "sum"))
            .reset_index()
            .sort_values(["publications", "weight"], ascending=False)
            .head(25)
        )
        st.caption("Число публикаций, где слово входит в 10 самых значимых (TF-IDF).")
        chart = alt.Chart(top).mark_bar().encode(
            x=alt.X("publications:Q", title="Публикаций"),
            y=alt.Y("keyword:N", sort="-x", title=None),
            tooltip=[alt.Tooltip("keyword:N", title="Слово"),
                     alt.Tooltip("publications:Q", title="Публикаций"),
                     alt.Tooltip("weight:Q", title="Суммарный вес", format=".3f")],
        )
        st.altair_chart(chart, width="stretch")

    st.subheader("Темы по источникам")
    by_source = (
        cats.merge(selected[["publication_id", "source_name"]], on="publication_id")
        .groupby(["category_name", "source_name"]).size().reset_index(name="publications")
    )
    # в шапке карты полные названия не помещаются: "4PDA, форум «Безопасность»" -> "4PDA"
    by_source["source_short"] = by_source["source_name"].str.split(",").str[0]
    heatmap = alt.Chart(by_source).mark_rect().encode(
        x=alt.X("source_short:N", title=None, axis=alt.Axis(labelAngle=0, labelOverlap=False, orient="top")),
        y=alt.Y("category_name:N", title=None, axis=alt.Axis(labelLimit=250)),
        color=alt.Color("publications:Q", title="Публикаций", scale=alt.Scale(scheme="blues")),
        tooltip=[alt.Tooltip("category_name:N", title="Тема"), alt.Tooltip("source_name:N", title="Источник"),
                 alt.Tooltip("publications:Q", title="Публикаций")],
    )
    text = heatmap.mark_text().encode(text="publications:Q", color=alt.value("black"))
    st.altair_chart(heatmap + text, width="stretch")


def brands_tab(selected: pd.DataFrame, brands: pd.DataFrame) -> None:
    br = brands[brands["publication_id"].isin(selected["publication_id"])].merge(
        selected[["publication_id", "source_name", "rating"]], on="publication_id"
    )
    if br.empty:
        st.info("В выбранных публикациях брендов из словаря не найдено.")
        return

    summary = br.groupby(["brand", "brand_group"]).agg(
        publications=("publication_id", "nunique"),
        mentions=("mentions", "sum"),
        sources=("source_name", lambda s: ", ".join(sorted(set(s)))),
        avg_rating=("rating", "mean"),
    ).reset_index().sort_values("publications", ascending=False)
    summary["brand_group"] = summary["brand_group"].map(GROUP_LABELS).fillna(summary["brand_group"])

    groups = ["Все группы"] + sorted(summary["brand_group"].unique())
    group = st.selectbox("Группа брендов", groups)
    if group != groups[0]:
        summary = summary[summary["brand_group"] == group]

    left, right = st.columns(2)
    with left:
        st.subheader("Упоминания брендов")
        chart = alt.Chart(summary).mark_bar().encode(
            x=alt.X("publications:Q", title="Публикаций"),
            y=alt.Y("brand:N", sort="-x", title=None, axis=alt.Axis(labelLimit=200)),
            color=alt.Color("brand_group:N", title=None, legend=alt.Legend(orient="bottom", columns=2)),
            tooltip=[alt.Tooltip("brand:N", title="Бренд"),
                     alt.Tooltip("publications:Q", title="Публикаций"),
                     alt.Tooltip("mentions:Q", title="Упоминаний")],
        )
        st.altair_chart(chart, width="stretch")
    with right:
        st.subheader("Детали")
        st.dataframe(
            summary,
            hide_index=True,
            width="stretch",
            column_config={
                "brand": "Бренд",
                "brand_group": "Группа",
                "publications": "Публикаций",
                "mentions": "Упоминаний",
                "sources": "Источники",
                "avg_rating": st.column_config.NumberColumn("Средняя оценка", format="%.2f",
                                                            help="Только для отзывов с оценкой"),
            },
        )


def sources_tab(health: pd.DataFrame, last_run: pd.DataFrame) -> None:
    if not last_run.empty:
        run = last_run.iloc[0]
        st.caption(
            f"Последний запуск: {run['finished_at'].tz_convert(TIMEZONE):%d.%m.%Y %H:%M} МСК, "
            f"статус {run['status']}, успешных источников {run['sources_success']} из {run['sources_total']}"
        )

    table = health.assign(
        last_status=health["last_status"].map(STATUS_LABELS).fillna("не запускался"),
        last_reason=health["last_reason"].map(explain_reason),
        success_rate=health["success_rate"].astype(float),
    )
    st.dataframe(
        table[["source_name", "last_status", "last_reason", "publications", "unique_publications",
               "success_rate", "runs_total", "last_success_at", "last_published", "start_url"]],
        hide_index=True,
        width="stretch",
        column_config={
            "source_name": "Источник",
            "last_status": "Статус",
            "last_reason": st.column_config.TextColumn("Причина", width="large"),
            "publications": "Публикаций",
            "unique_publications": "Без дублей",
            "success_rate": st.column_config.ProgressColumn("Успешных запусков", format="percent",
                                                            min_value=0, max_value=1),
            "runs_total": "Запусков",
            "last_success_at": st.column_config.DatetimeColumn("Последний успех", format="DD.MM.YYYY HH:mm"),
            "last_published": st.column_config.DateColumn("Последняя публикация"),
            "start_url": st.column_config.LinkColumn("Адрес"),
        },
    )
    unavailable = health[(health["last_status"] != "success") & (health["publications"] == 0)]
    if not unavailable.empty:
        st.warning(
            "Нет данных: " + ", ".join(unavailable["source_name"])
            + ". Эти источники проверяются при каждом запуске, причина указана в таблице."
        )


def publications_tab(selected: pd.DataFrame, category_names: dict[str, str], f: dict) -> None:
    search = st.text_input("Поиск по заголовку и началу текста")
    rows = selected
    if search:
        needle = search.lower()
        rows = rows[
            rows["title"].str.lower().str.contains(needle, regex=False, na=False)
            | rows["text_preview"].str.lower().str.contains(needle, regex=False, na=False)
        ]
    rows = rows.sort_values(f["basis"], ascending=False)
    st.caption(f"Найдено: {len(rows)}. Выберите строку, чтобы открыть публикацию.")

    event = st.dataframe(
        rows[["title", "source_name", "published_at", "primary_category_name", "rating", "brands"]],
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "title": "Заголовок",
            "source_name": "Источник",
            "published_at": st.column_config.DatetimeColumn("Опубликовано", format="DD.MM.YYYY HH:mm"),
            "primary_category_name": "Тема",
            "rating": st.column_config.NumberColumn("Оценка", format="%.0f"),
            "brands": "Бренды",
        },
    )

    if not event.selection.rows:
        return
    pub = rows.iloc[event.selection.rows[0]]
    st.divider()
    st.subheader(pub["title"] or "(без заголовка)")
    meta = [pub["source_name"], pub["author"] or "автор не указан"]
    if pd.notna(pub["published_at"]):
        meta.append(f"{pub['published_at']:%d.%m.%Y %H:%M}")
    if isinstance(pub["product"], str):
        meta.append(f"продукт: {pub['product']}")
    if pd.notna(pub["rating"]):
        meta.append(f"оценка: {pub['rating']:.0f} из 5")
    st.caption(" · ".join(meta))
    st.markdown(f"[Открыть оригинал]({pub['publication_url']})")

    cols = st.columns(3)
    topics = [category_names.get(c, c) for c in pub["categories"]]
    cols[0].markdown("**Темы:** " + (", ".join(topics) or "нет"))
    cols[1].markdown("**Бренды:** " + (", ".join(pub["brands"]) or "нет"))
    cols[2].markdown("**Ключевые слова:** " + (", ".join(pub["keywords"]) or "нет"))
    if pub["is_duplicate"]:
        st.info(f"Почти-дубль публикации #{int(pub['duplicate_of'])}.")
    st.text(load_text(int(pub["publication_id"])))


def main() -> None:
    st.title("Медиамониторинг")
    data = load_data()
    pubs, health = data["publications"], data["health"]

    if pubs.empty:
        st.warning("В витринах нет публикаций. Запустите DAG media_monitoring_elt.")
        sources_tab(health, data["last_run"])
        return

    f = sidebar_filters(pubs, health)
    selected = apply_filters(pubs, f)

    kpis(selected, data["brands"], health)

    tabs = st.tabs(["Обзор", "Темы и ключевые слова", "Бренды", "Источники", "Публикации"])
    with tabs[3]:
        sources_tab(health, data["last_run"])
    if selected.empty:
        for tab in (tabs[0], tabs[1], tabs[2], tabs[4]):
            tab.info("Под выбранные фильтры публикаций нет. Измените период, источники или категории.")
        return
    with tabs[0]:
        overview_tab(selected, f)
    with tabs[1]:
        topics_tab(selected, data["categories"], data["keywords"])
    with tabs[2]:
        brands_tab(selected, data["brands"])
    with tabs[4]:
        names = dict(zip(data["categories"]["category"], data["categories"]["category_name"]))
        publications_tab(selected, names, f)


main()
