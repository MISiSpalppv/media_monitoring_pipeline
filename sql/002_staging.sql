CREATE SCHEMA IF NOT EXISTS staging;

CREATE TABLE IF NOT EXISTS staging.publications (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    raw_id BIGINT NOT NULL REFERENCES raw.publications(id),
    source_url TEXT NOT NULL,
    publication_url TEXT NOT NULL UNIQUE,
    title TEXT,
    author TEXT,
    published_at TIMESTAMP WITHOUT TIME ZONE,
    text TEXT,
    transformed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

INSERT INTO staging.publications (
    raw_id,
    source_url,
    publication_url,
    title,
    author,
    published_at,
    text
)
SELECT DISTINCT ON (publication_url)
    id,
    source_url,
    publication_url,
    NULLIF(TRIM(payload ->> 'title'), ''),
    NULLIF(TRIM(payload ->> 'author'), ''),
    TO_TIMESTAMP(
        REGEXP_REPLACE(
            payload ->> 'published_at',
            '(Январь|Февраль|Март|Апрель|Май|Июнь|Июль|Август|Сентябрь|Октябрь|Ноябрь|Декабрь)',
            CASE
                WHEN payload ->> 'published_at' ILIKE '%Январь%' THEN 'January'
                WHEN payload ->> 'published_at' ILIKE '%Февраль%' THEN 'February'
                WHEN payload ->> 'published_at' ILIKE '%Март%' THEN 'March'
                WHEN payload ->> 'published_at' ILIKE '%Апрель%' THEN 'April'
                WHEN payload ->> 'published_at' ILIKE '%Май%' THEN 'May'
                WHEN payload ->> 'published_at' ILIKE '%Июнь%' THEN 'June'
                WHEN payload ->> 'published_at' ILIKE '%Июль%' THEN 'July'
                WHEN payload ->> 'published_at' ILIKE '%Август%' THEN 'August'
                WHEN payload ->> 'published_at' ILIKE '%Сентябрь%' THEN 'September'
                WHEN payload ->> 'published_at' ILIKE '%Октябрь%' THEN 'October'
                WHEN payload ->> 'published_at' ILIKE '%Ноябрь%' THEN 'November'
                WHEN payload ->> 'published_at' ILIKE '%Декабрь%' THEN 'December'
            END
        ),
        'DD FMMonth, YYYY - HH24:MI'
    )::TIMESTAMP,
    NULLIF(TRIM(payload ->> 'text'), '')
FROM raw.publications
ORDER BY publication_url, id DESC
ON CONFLICT (publication_url)
DO UPDATE SET
    raw_id = EXCLUDED.raw_id,
    source_url = EXCLUDED.source_url,
    title = EXCLUDED.title,
    author = EXCLUDED.author,
    published_at = EXCLUDED.published_at,
    text = EXCLUDED.text,
    transformed_at = NOW();