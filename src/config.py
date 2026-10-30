from pathlib import Path

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCES_FILE = PROJECT_ROOT / "sources.yaml"

FIELDS = ("title", "text", "author", "published_at")
METHODS = ("adapter", "trafilatura", "css")
DISCOVERY_MODES = ("links", "rss", "sitemap")


def load_sources(path: Path = SOURCES_FILE) -> dict[str, dict]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    defaults = data.get("defaults", {})

    sources = {}
    for raw in data["sources"]:
        cfg = {**defaults, **raw}
        validate_source(cfg)

        if cfg["id"] in sources:
            raise ValueError(f"duplicate source id: {cfg['id']}")
        sources[cfg["id"]] = cfg

    return sources


def get_source(source_id: str) -> dict:
    sources = load_sources()
    if source_id not in sources:
        raise KeyError(f"unknown source: {source_id}")
    return sources[source_id]


def validate_source(cfg: dict) -> None:
    source_id = cfg.get("id")
    if not source_id:
        raise ValueError("source without id")

    if not cfg.get("start_urls"):
        raise ValueError(f"{source_id}: start_urls is empty")

    cfg.setdefault("discovery", {})
    cfg["discovery"].setdefault("mode", "links")
    if cfg["discovery"]["mode"] not in DISCOVERY_MODES:
        raise ValueError(f"{source_id}: unknown discovery mode {cfg['discovery']['mode']}")

    cfg.setdefault("selectors", {})
    cfg.setdefault("field_priority", {})

    for field, methods in cfg["field_priority"].items():
        if field not in FIELDS:
            raise ValueError(f"{source_id}: unknown field in field_priority: {field}")
        unknown = set(methods) - set(METHODS)
        if unknown:
            raise ValueError(f"{source_id}: unknown methods for {field}: {unknown}")
