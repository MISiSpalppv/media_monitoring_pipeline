# Адаптеры для источников, которым не хватает Trafilatura и CSS-селекторов
# (например, данные лежат в JSON внутри страницы). Адаптер получает
# parsel.Selector и url и возвращает словарь с полями title, text, author,
# published_at. Подключается в sources.yaml через "adapter: <имя>".
ADAPTERS = {}
