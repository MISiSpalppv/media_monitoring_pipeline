-- STAGING: последняя версия каждой публикации из RAW.
-- Строка обновляется только если изменился хэш содержимого, поэтому
-- повторный запуск без новых данных ничего не трогает.
--
-- Дата разбирается в Python и лежит в payload в ISO 8601. Строки старого
-- формата (до миграции 002) не приводятся к timestamptz, а дают NULL:
-- трансформация не должна падать из-за одной кривой даты.

WITH latest AS (
    SELECT DISTINCT ON (publication_url)
        id,
        source_id,
        source_url,
        publication_url,
        content_hash,
        payload
    FROM raw.publications
    ORDER BY publication_url, fetched_at DESC, id DESC
)
INSERT INTO staging.publications (
    raw_id,
    source_id,
    source_url,
    publication_url,
    content_hash,
    title,
    author,
    published_at,
    published_at_raw,
    text,
    quality_flags,
    extraction,
    metadata
)
SELECT
    id,
    source_id,
    source_url,
    publication_url,
    content_hash,
    NULLIF(BTRIM(payload ->> 'title'), ''),
    NULLIF(BTRIM(payload ->> 'author'), ''),
    CASE
        WHEN payload ->> 'published_at' ~ '^\d{4}-\d{2}-\d{2}T'
            THEN (payload ->> 'published_at')::TIMESTAMPTZ
    END,
    COALESCE(payload ->> 'published_at_raw', payload ->> 'published_at'),
    NULLIF(BTRIM(payload ->> 'text'), ''),
    COALESCE(payload -> 'quality_flags', '[]'::JSONB),
    COALESCE(payload -> 'extraction', '{}'::JSONB),
    COALESCE(payload -> 'metadata', '{}'::JSONB)
FROM latest
ON CONFLICT (publication_url) DO UPDATE SET
    raw_id = EXCLUDED.raw_id,
    source_id = EXCLUDED.source_id,
    source_url = EXCLUDED.source_url,
    content_hash = EXCLUDED.content_hash,
    title = EXCLUDED.title,
    author = EXCLUDED.author,
    published_at = EXCLUDED.published_at,
    published_at_raw = EXCLUDED.published_at_raw,
    text = EXCLUDED.text,
    quality_flags = EXCLUDED.quality_flags,
    extraction = EXCLUDED.extraction,
    metadata = EXCLUDED.metadata,
    transformed_at = NOW()
WHERE staging.publications.content_hash IS DISTINCT FROM EXCLUDED.content_hash;
