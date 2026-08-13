import yaml
from pathlib import Path


def load_fixture(slug: str, base_fixtures: str = ".") -> dict:
    base_root = Path(base_fixtures).resolve()
    base = (base_root / slug).resolve()
    if base != base_root and base_root not in base.parents:
        raise ValueError(f"slug hors du répertoire de fixtures autorisé : {slug!r}")

    meta_path = base / "meta.yaml"
    index_path = base / "index.html"
    robots_path = base / "robots.txt"
    sitemap_path = base / "sitemap.xml"
    for f in [meta_path, index_path, robots_path, sitemap_path]:
        if not f.is_file():
            raise FileNotFoundError(f"fichier manquant : {f.name}")
    with open(meta_path, 'r', encoding='utf-8') as fh:
        meta = yaml.safe_load(fh)
    if not (isinstance(meta, dict) and meta.get('fictif') is True):
        raise ValueError("Le champ 'fictif' doit être true pour le concurrent fictif")
    with open(index_path, 'r', encoding='utf-8') as fh:
        index_html = fh.read()
    with open(robots_path, 'r', encoding='utf-8') as fh:
        robots_txt = fh.read()
    with open(sitemap_path, 'r', encoding='utf-8') as fh:
        sitemap_xml = fh.read()
    return {
        "slug": slug,
        "meta": meta,
        "index_html": index_html,
        "robots_txt": robots_txt,
        "sitemap_xml": sitemap_xml,
    }
