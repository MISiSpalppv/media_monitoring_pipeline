-- Схема в том виде, в каком она создавалась вручную до появления миграций.
-- IF NOT EXISTS позволяет применить файл и к существующей, и к пустой БД.

CREATE SCHEMA IF NOT EXISTS raw;

CREATE TABLE IF NOT EXISTS raw.publications (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_url TEXT NOT NULL,
    publication_url TEXT NOT NULL,
    payload JSONB NOT NULL,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

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
