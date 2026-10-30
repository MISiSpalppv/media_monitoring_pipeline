-- Версионирование RAW: одна строка на (URL, содержимое).
-- fetched_at теперь означает время получения страницы, время загрузки
-- в БД пишется в loaded_at.

ALTER TABLE raw.publications
    ADD COLUMN source_id TEXT,
    ADD COLUMN run_id TEXT,
    ADD COLUMN content_hash TEXT,
    ADD COLUMN loaded_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- Строки, загруженные до миграции (iRecommend). Настоящий хэш считается
-- в Python, здесь воспроизвести его нельзя, поэтому у старых строк хэш
-- с префиксом legacy: он никогда не совпадёт с новым, и повторная
-- загрузка тех же отзывов создаст новую версию с нормализованной датой.
UPDATE raw.publications
SET
    source_id = CASE
        WHEN source_url LIKE '%irecommend.ru%' THEN 'irecommend'
        ELSE 'unknown'
    END,
    run_id = 'legacy',
    content_hash = 'legacy:' || MD5(payload::TEXT),
    loaded_at = fetched_at
WHERE content_hash IS NULL;

ALTER TABLE raw.publications
    ALTER COLUMN source_id SET NOT NULL,
    ALTER COLUMN run_id SET NOT NULL,
    ALTER COLUMN content_hash SET NOT NULL;

ALTER TABLE raw.publications
    ADD CONSTRAINT raw_publications_url_hash_key UNIQUE (publication_url, content_hash);

CREATE INDEX raw_publications_source_idx ON raw.publications (source_id);


ALTER TABLE staging.publications
    ADD COLUMN source_id TEXT,
    ADD COLUMN content_hash TEXT,
    ADD COLUMN published_at_raw TEXT,
    ADD COLUMN quality_flags JSONB NOT NULL DEFAULT '[]'::JSONB,
    ADD COLUMN extraction JSONB NOT NULL DEFAULT '{}'::JSONB;

-- Старые даты iRecommend разбирались без часового пояса, время на
-- странице московское.
ALTER TABLE staging.publications
    ALTER COLUMN published_at TYPE TIMESTAMPTZ
    USING published_at AT TIME ZONE 'Europe/Moscow';

UPDATE staging.publications AS s
SET
    source_id = r.source_id,
    content_hash = r.content_hash,
    published_at_raw = r.payload ->> 'published_at'
FROM raw.publications AS r
WHERE r.id = s.raw_id
  AND s.content_hash IS NULL;

ALTER TABLE staging.publications
    ALTER COLUMN source_id SET NOT NULL,
    ALTER COLUMN content_hash SET NOT NULL;
