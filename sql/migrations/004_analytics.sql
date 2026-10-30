-- Признаки публикаций (заполняет src/transform/enrich.py) и витрины MART.

-- metadata (название продукта, оценка в отзыве) нужна для аналитики, но в
-- хэш не входит, поэтому переносится в STAGING отдельной колонкой.
ALTER TABLE staging.publications
    ADD COLUMN metadata JSONB NOT NULL DEFAULT '{}'::JSONB;

UPDATE staging.publications AS s
SET metadata = r.payload -> 'metadata'
FROM raw.publications AS r
WHERE r.id = s.raw_id
  AND r.payload ? 'metadata';


-- Справочник источников из sources.yaml, обновляется при каждом запуске.
-- Нужен витринам, чтобы показывать и источники без единой публикации.
CREATE TABLE ops.sources (
    source_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_type TEXT,
    start_url TEXT NOT NULL,
    enabled BOOLEAN NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE ops.pipeline_runs
    ADD COLUMN enriched_rows INT,
    ADD COLUMN marts_refreshed_at TIMESTAMPTZ;


CREATE TABLE staging.categories (
    category TEXT PRIMARY KEY,
    name TEXT NOT NULL
);

CREATE TABLE staging.publication_features (
    publication_id BIGINT PRIMARY KEY REFERENCES staging.publications (id),
    char_count INT NOT NULL,
    word_count INT NOT NULL,
    primary_category TEXT,
    rating NUMERIC(3, 1),
    -- id более ранней публикации с почти тем же текстом
    duplicate_of BIGINT REFERENCES staging.publications (id),
    enriched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE staging.publication_categories (
    publication_id BIGINT NOT NULL REFERENCES staging.publications (id),
    category TEXT NOT NULL,
    score INT NOT NULL,
    is_primary BOOLEAN NOT NULL,
    PRIMARY KEY (publication_id, category)
);

CREATE TABLE staging.publication_keywords (
    publication_id BIGINT NOT NULL REFERENCES staging.publications (id),
    keyword TEXT NOT NULL,
    weight DOUBLE PRECISION NOT NULL,
    rank INT NOT NULL,
    PRIMARY KEY (publication_id, keyword)
);

CREATE TABLE staging.publication_brands (
    publication_id BIGINT NOT NULL REFERENCES staging.publications (id),
    brand TEXT NOT NULL,
    brand_group TEXT NOT NULL,
    mentions INT NOT NULL,
    PRIMARY KEY (publication_id, brand)
);


CREATE SCHEMA mart;

-- Карточка публикации: всё, что нужно дашборду для списка и просмотра.
-- Даты в витринах считаются по московскому времени.
CREATE MATERIALIZED VIEW mart.publications AS
SELECT
    p.id AS publication_id,
    p.source_id,
    COALESCE(src.name, p.source_id) AS source_name,
    src.source_type,
    p.publication_url,
    p.title,
    p.author,
    p.published_at,
    (p.published_at AT TIME ZONE 'Europe/Moscow')::DATE AS published_date,
    seen.first_seen_at,
    (seen.first_seen_at AT TIME ZONE 'Europe/Moscow')::DATE AS first_seen_date,
    p.text,
    LEFT(p.text, 300) AS text_preview,
    f.char_count,
    f.word_count,
    f.primary_category,
    cat.name AS primary_category_name,
    f.rating,
    p.metadata ->> 'product' AS product,
    f.duplicate_of,
    f.duplicate_of IS NOT NULL AS is_duplicate,
    COALESCE(c.categories, '{}') AS categories,
    COALESCE(b.brands, '{}') AS brands,
    COALESCE(k.keywords, '{}') AS keywords,
    p.quality_flags
FROM staging.publications AS p
LEFT JOIN ops.sources AS src ON src.source_id = p.source_id
LEFT JOIN staging.publication_features AS f ON f.publication_id = p.id
LEFT JOIN staging.categories AS cat ON cat.category = f.primary_category
LEFT JOIN LATERAL (
    SELECT MIN(r.fetched_at) AS first_seen_at
    FROM raw.publications AS r
    WHERE r.publication_url = p.publication_url
) AS seen ON TRUE
LEFT JOIN LATERAL (
    SELECT ARRAY_AGG(category ORDER BY score DESC) AS categories
    FROM staging.publication_categories WHERE publication_id = p.id
) AS c ON TRUE
LEFT JOIN LATERAL (
    SELECT ARRAY_AGG(brand ORDER BY mentions DESC) AS brands
    FROM staging.publication_brands WHERE publication_id = p.id
) AS b ON TRUE
LEFT JOIN LATERAL (
    SELECT ARRAY_AGG(keyword ORDER BY rank) AS keywords
    FROM staging.publication_keywords WHERE publication_id = p.id
) AS k ON TRUE;

CREATE UNIQUE INDEX ON mart.publications (publication_id);


-- Публикации по дням публикации, источникам и основной категории.
-- unique_publications не считает почти-дубли.
CREATE MATERIALIZED VIEW mart.daily_publications AS
SELECT
    published_date,
    source_id,
    COALESCE(primary_category, 'uncategorized') AS category,
    COUNT(*) AS publications,
    COUNT(*) FILTER (WHERE NOT is_duplicate) AS unique_publications,
    ROUND(AVG(word_count)) AS avg_word_count,
    ROUND(AVG(rating), 2) AS avg_rating
FROM mart.publications
WHERE published_date IS NOT NULL
GROUP BY published_date, source_id, COALESCE(primary_category, 'uncategorized');


-- Категории по неделям с учётом всех категорий публикации, а не только основной.
CREATE MATERIALIZED VIEW mart.category_weekly AS
SELECT
    DATE_TRUNC('week', p.published_date)::DATE AS week,
    p.source_id,
    pc.category,
    cat.name AS category_name,
    COUNT(*) AS publications,
    COUNT(*) FILTER (WHERE pc.is_primary) AS primary_publications
FROM mart.publications AS p
JOIN staging.publication_categories AS pc ON pc.publication_id = p.publication_id
LEFT JOIN staging.categories AS cat ON cat.category = pc.category
WHERE p.published_date IS NOT NULL
  AND NOT p.is_duplicate
GROUP BY 1, 2, 3, 4;


-- Ключевые слова на уровне публикации: дашборд агрегирует их под выбранные фильтры.
CREATE MATERIALIZED VIEW mart.publication_keywords AS
SELECT
    p.publication_id,
    p.source_id,
    p.published_date,
    p.primary_category,
    k.keyword,
    k.weight,
    k.rank
FROM mart.publications AS p
JOIN staging.publication_keywords AS k ON k.publication_id = p.publication_id
WHERE NOT p.is_duplicate;


-- Упоминания брендов: конкуренты, менеджеры паролей, банки.
CREATE MATERIALIZED VIEW mart.brand_mentions AS
SELECT
    p.publication_id,
    p.source_id,
    p.published_date,
    p.primary_category,
    b.brand,
    b.brand_group,
    b.mentions,
    p.rating
FROM mart.publications AS p
JOIN staging.publication_brands AS b ON b.publication_id = p.publication_id
WHERE NOT p.is_duplicate;


-- Состояние источников: последний запуск, доля успешных, объём данных.
-- Источник без публикаций попадает сюда с нулями и причиной недоступности.
CREATE MATERIALIZED VIEW mart.source_health AS
WITH runs AS (
    SELECT
        source_id,
        COUNT(*) AS runs_total,
        COUNT(*) FILTER (WHERE status = 'success') AS runs_success,
        MAX(finished_at) FILTER (WHERE status = 'success') AS last_success_at
    FROM ops.source_runs
    GROUP BY source_id
),
last_run AS (
    SELECT DISTINCT ON (source_id)
        source_id, status, reason, finished_at, accepted, rejected
    FROM ops.source_runs
    ORDER BY source_id, finished_at DESC NULLS LAST
),
pubs AS (
    SELECT
        source_id,
        COUNT(*) AS publications,
        COUNT(*) FILTER (WHERE NOT is_duplicate) AS unique_publications,
        MIN(published_date) AS first_published,
        MAX(published_date) AS last_published,
        MAX(first_seen_at) AS last_collected_at
    FROM mart.publications
    GROUP BY source_id
)
SELECT
    s.source_id,
    s.name AS source_name,
    s.source_type,
    s.start_url,
    s.enabled,
    lr.status AS last_status,
    lr.reason AS last_reason,
    lr.finished_at AS last_run_at,
    COALESCE(r.runs_total, 0) AS runs_total,
    COALESCE(r.runs_success, 0) AS runs_success,
    ROUND(r.runs_success::NUMERIC / NULLIF(r.runs_total, 0), 2) AS success_rate,
    r.last_success_at,
    COALESCE(p.publications, 0) AS publications,
    COALESCE(p.unique_publications, 0) AS unique_publications,
    p.first_published,
    p.last_published,
    p.last_collected_at
FROM ops.sources AS s
LEFT JOIN runs AS r ON r.source_id = s.source_id
LEFT JOIN last_run AS lr ON lr.source_id = s.source_id
LEFT JOIN pubs AS p ON p.source_id = s.source_id;
