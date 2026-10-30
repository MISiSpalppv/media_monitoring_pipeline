# media_monitoring_pipeline

Прототип сбора публикаций из интернет-источников для медиамониторинга.
Источник описывается в `sources.yaml`, код паука для нового источника не пишется.

```
sources.yaml -> PublicationSpider(source_id)
                  discovery: links | rss | sitemap
                  extract_publication: Trafilatura + CSS-селекторы, приоритет по полям
                  нормализация даты, хэш содержимого, проверка качества
             -> data/processed/<run_id>/<source_id>.jsonl + summary.json
             -> raw.publications (версии) -> staging.publications
             -> ops.source_runs, ops.pipeline_runs (статусы запусков)
```

## Запуск

```bash
cp .env.example .env    # задать пароль
docker compose -f compose.yaml -f compose.airflow.yaml up -d
python -m src.db.migrate
```

Миграции можно применять локально (`.venv`, host `localhost`) или из контейнера:
`docker exec media_airflow python -m src.db.migrate`.
БД `airflow` для метаданных Airflow создаётся init-скриптом
`docker/postgres/init/01_airflow_db.sql` при первом старте Postgres на пустом томе.
Если том уже существовал без неё: `docker exec media_postgres createdb -U media_user airflow`.

Airflow UI: http://localhost:8080, DAG `media_monitoring_elt`.

Без Airflow тот же пайплайн запускается так:

```bash
python -m src.pipeline --run-id manual_1
python -m src.pipeline --run-id manual_2 --sources livejournal_5koleso
```

Один источник отдельно, без записи в БД:

```bash
python -m src.extract.spider --source livejournal_5koleso --run-id debug_1
```

Тесты работают офлайн на сохранённых страницах из `tests/fixtures/`:

```bash
pip install -r requirements-dev.txt
pytest
```

## Конфигурация источника

```yaml
- id: livejournal_5koleso
  start_urls: [https://5koleso.livejournal.com/]
  download_delay: 10            # Crawl-delay из robots.txt
  max_pages: 2
  discovery:
    mode: links                 # links | rss | sitemap
    area: article.entryunit h3  # где на листинге искать ссылки
    link_pattern: '^https://5koleso\.livejournal\.com/\d+\.html$'
    next_page: .j-page-nav-item-prev a::attr(href)
  selectors:
    title: h1.aentry-post__title
    author: .aentry-head__username .ljuser
  field_priority:
    author: [css, trafilatura]
```

CSS-селектор берёт первый найденный элемент. Без суффикса берётся весь текст внутри
элемента, `::text` - только его собственный текст, `::attr(name)` - атрибут.
Другие параметры: `follow_pattern` (промежуточные листинги, например каталог -> страница
банка), `metadata_selectors` (дополнительные поля в `metadata`, в хэш не входят),
`text_cut_markers`, `text_drop_lines`, `block_markers`, `date_order` (по умолчанию DMY).

Значения по умолчанию заданы в `defaults` в начале файла.

**Приоритет полей.** Для каждого поля (`title`, `text`, `author`, `published_at`) берётся
первое непустое значение, прошедшее проверку: заголовок не длиннее 500 символов, текст
не короче `min_text_length`, дата разбирается. По умолчанию первой идёт Trafilatura, CSS
используется как запасной вариант. Откуда взято каждое поле, пишется в `extraction`.
Если данных нет ни в HTML, ни в метаданных (например, они лежат в JSON внутри страницы),
пишется адаптер в `src/extract/adapters/` и подключается через `adapter: <имя>`.

**Даты.** Разбираются в Python через `dateparser` (ru, en), часовой пояс по умолчанию
Europe/Moscow, задаётся полем `timezone`. Относительные даты («вчера в 14:30») считаются
от момента получения страницы (`fetched_at`). Исходная строка хранится в
`published_at_raw`. Если дата не разобралась, `published_at = null` и флаг `date_not_parsed`.

**Качество.** Запись отклоняется, если нет URL или заголовка, текст короче
`min_text_length` или не длиннее заголовка. Короткие служебные строки (cookie,
«Читать далее») из текста вырезаются. Флаги `date_*` и `author_missing` запись не отклоняют.

Отклонённые записи в RAW не попадают: RAW хранит то, что считается публикацией, и
трансформации не должны каждый раз фильтровать мусор. Они сохраняются в
`<source_id>.rejected.jsonl` рядом с принятыми и считаются в `ops.source_runs.rejected`,
так что причину отказа можно разобрать.

## Слои данных

- `raw.publications` — версии публикаций. Ключ `(publication_url, content_hash)`, загрузка
  через `ON CONFLICT DO NOTHING`: повторная загрузка того же файла ничего не меняет,
  изменённый текст даёт новую версию.
- `content_hash` считается из канонического URL, заголовка, автора, текста (пробелы
  схлопнуты) и нормализованной даты. Время сбора, run_id, источник поля, лайки, просмотры
  и прочие счётчики в хэш не входят.
- `staging.publications` — последняя версия каждой публикации по `fetched_at`. Строка
  обновляется только при смене хэша. SQL: `sql/transform/staging_publications.sql`.
- `ops.source_runs`, `ops.pipeline_runs` — статусы источников и запусков.

## Статусы

Статус источника в запуске (`ops.source_runs.status`):

| статус | когда | задача extract в Airflow |
|---|---|---|
| success | принята хотя бы одна публикация | success |
| empty | страницы загрузились, но публикаций нет или все отклонены | failed без повторов |
| unavailable | листинг или все страницы публикаций не загрузились (HTTP-ошибки, таймауты, маркер блокировки) | failed после повторов |
| failed | ошибка в коде паука или паук не записал сводку | failed после повторов |

0 публикаций никогда не считается успехом.

Итог запуска (`ops.pipeline_runs.status`):

- `success` — все источники success, STAGING обновлён;
- `partial_success` — хотя бы один источник success, STAGING обновлён;
- `failed` — ни одного успешного источника или упала загрузка/трансформация.

В Airflow `extract` раскладывается по источникам через `.expand`, у каждой копии свои
повторы с растущей задержкой. `load_raw` запускается с `trigger_rule=all_done` и
загружает только источники со статусом success из `ops.source_runs`; если таких нет,
задача падает. Финальная задача `finish` пишет итог в `ops.pipeline_runs` и падает только
при `failed`. Поэтому при `partial_success` DAG run зелёный, а упавшие источники видны
красными копиями `extract` и в `ops.source_runs`.

## Ограничения сбора

`ROBOTSTXT_OBEY`, задержка между запросами (для LiveJournal 10 секунд по Crawl-delay),
AutoThrottle, повтор 429/5xx/521. Защита сайтов не обходится: капча, антибот и 521
означают статус `unavailable` с причиной.

## Состояние источников

| источник | id | статус |
|---|---|---|
| LiveJournal, 5 Колесо | `livejournal_5koleso` | работает, посты блога |
| 4PDA, «Безопасность» | `fourpda_security` | работает; публикация - тема форума (первый пост), дата - дата создания темы; ответы не собираются |
| Отзовик, банки | `otzovik_banks` | работает; каталог -> страница банка -> отзыв, в `metadata` название продукта и оценка из отзыва |
| iRecommend | `irecommend` | с 30.10.2026 отвечает 521 на всё, включая robots.txt |
| Дзен Новости | `dzen_news_computers` | без JavaScript перенаправляет на sso.passport.yandex.ru, а тот запрещён robots.txt |
| Drive2 | `drive2_featured` | robots.txt запрещает всё для `User-Agent: *` |

Недоступные источники остаются в конфиге: каждый запуск проверяет их и пишет статус
`unavailable` с причиной в `ops.source_runs`.

21 отзыв iRecommend, собранный до блокировки старым пауком, перезагружен скриптом
`scripts/reload_legacy_irecommend.py`: даты нормализованы, хэш посчитан так же, как у паука.
В RAW остались обе версии (старая с `run_id = legacy`), в STAGING по одной строке на отзыв.
