"""Audit SEO technique local pour le module M7 — Marketing.

Mode ombre : aucune requête réseau. Stdlib uniquement.
"""
from __future__ import annotations

import html.parser
import json
import sys
from pathlib import Path


class _PageAuditor(html.parser.HTMLParser):
    """Collecte les éléments SEO pertinents d'une page HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.title_parts: list[str] = []
        self.meta_description: str = ""
        self.lang: str | None = None
        self.h1_count: int = 0
        self.script_srcs: list[str] = []
        self.json_ld_blocks: list[str] = []
        self.parse_error: str | None = None

        self._in_title: bool = False
        self._in_json_ld: bool = False
        self._json_ld_buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {name: (value or "") for name, value in attrs}

        if tag == "html":
            self.lang = attrs_dict.get("lang")
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            if attrs_dict.get("name", "").lower() == "description":
                self.meta_description = attrs_dict.get("content", "")
        elif tag == "h1":
            self.h1_count += 1
        elif tag == "script":
            src = attrs_dict.get("src")
            if src:
                self.script_srcs.append(src)
            if attrs_dict.get("type", "").lower() == "application/ld+json":
                self._in_json_ld = True
                self._json_ld_buffer = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "script" and self._in_json_ld:
            self.json_ld_blocks.append("".join(self._json_ld_buffer))
            self._in_json_ld = False
            self._json_ld_buffer = []

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title_parts.append(data)
        if self._in_json_ld:
            self._json_ld_buffer.append(data)


def _is_external_script(src: str) -> bool:
    """Détermine si une URL de script est externe (réseau)."""
    return src.startswith("//") or src.startswith(("http://", "https://"))


def _audit_page(page_path: Path, site_dir: Path) -> dict:
    auditor = _PageAuditor()

    try:
        content = page_path.read_text(encoding="utf-8")
    except Exception as exc:  # pragma: no cover - défense en profondeur
        auditor.parse_error = f"lecture du fichier impossible : {exc}"
        content = ""

    try:
        if content:
            auditor.feed(content)
    except Exception as exc:
        auditor.parse_error = f"erreur de parsing HTML : {exc}"

    title = "".join(auditor.title_parts).strip()
    description = auditor.meta_description.strip()

    verdicts: list[dict] = []

    # title non vide
    ok = bool(title)
    verdicts.append(
        {
            "regle": "title",
            "ok": ok,
            "detail": f"title présent ({title!r})" if ok else "title absent ou vide",
        }
    )

    # meta description non vide
    ok = bool(description)
    verdicts.append(
        {
            "regle": "meta_description",
            "ok": ok,
            "detail": "meta description présente" if ok else "meta description absente ou vide",
        }
    )

    # lang="fr"
    lang_value = (auditor.lang or "").strip()
    ok = lang_value.lower() == "fr"
    verdicts.append(
        {
            "regle": "lang_fr",
            "ok": ok,
            "detail": f"lang='{lang_value}'" if lang_value else "attribut lang absent",
        }
    )

    # exactement un h1
    ok = auditor.h1_count == 1
    verdicts.append(
        {
            "regle": "h1_unique",
            "ok": ok,
            "detail": f"{auditor.h1_count} balise(s) h1",
        }
    )

    # JSON-LD présent et valide
    json_ok = True
    json_detail = "aucun bloc JSON-LD détecté"
    if auditor.json_ld_blocks:
        for index, block in enumerate(auditor.json_ld_blocks, start=1):
            data = block.strip()
            if not data:
                continue
            try:
                json.loads(data)
            except json.JSONDecodeError as exc:
                json_ok = False
                json_detail = f"JSON-LD #{index} invalide : {exc}"
                break
        else:
            json_detail = f"{len(auditor.json_ld_blocks)} bloc(s) JSON-LD valide(s)"
    verdicts.append(
        {
            "regle": "json_ld_valide",
            "ok": json_ok,
            "detail": json_detail,
        }
    )

    # aucun script externe
    external_scripts = [src for src in auditor.script_srcs if _is_external_script(src)]
    ok = not external_scripts
    verdicts.append(
        {
            "regle": "script_externe",
            "ok": ok,
            "detail": "aucun script externe" if ok else f"script(s) externe(s) : {external_scripts}",
        }
    )

    # erreur de parsing capturée
    if auditor.parse_error:
        verdicts.append(
            {
                "regle": "parse_error",
                "ok": False,
                "detail": auditor.parse_error,
            }
        )

    return {
        "fichier": page_path.relative_to(site_dir).as_posix(),
        "verdicts": verdicts,
    }


def _audit_robots(site_dir: Path) -> dict:
    robots_path = site_dir / "robots.txt"
    verdicts: list[dict] = []

    if not robots_path.is_file():
        verdicts.append(
            {
                "regle": "robots_crawlable",
                "ok": False,
                "detail": "robots.txt absent",
            }
        )
        return {"fichier": "robots.txt", "verdicts": verdicts}

    try:
        lines = robots_path.read_text(encoding="utf-8").splitlines()
    except Exception as exc:  # pragma: no cover - défense en profondeur
        verdicts.append(
            {
                "regle": "robots_crawlable",
                "ok": False,
                "detail": f"lecture de robots.txt impossible : {exc}",
            }
        )
        return {"fichier": "robots.txt", "verdicts": verdicts}

    stripped = [line.strip() for line in lines]
    has_user_agent = "User-agent: *" in stripped
    has_allow = "Allow: /" in stripped
    ok = has_user_agent and has_allow

    missing: list[str] = []
    if not has_user_agent:
        missing.append("User-agent: * manquant")
    if not has_allow:
        missing.append("Allow: / manquant")

    verdicts.append(
        {
            "regle": "robots_crawlable",
            "ok": ok,
            "detail": "robots.txt conforme" if ok else "; ".join(missing),
        }
    )

    return {"fichier": "robots.txt", "verdicts": verdicts}


def audit_dir(site_dir: str | Path) -> dict:
    """Audite un répertoire de site statique et retourne le rapport JSON-serialisable."""
    site_dir = Path(site_dir).resolve()

    pages = [
        _audit_page(path, site_dir)
        for path in sorted(site_dir.rglob("*.html"))
    ]

    robots = _audit_robots(site_dir)

    regles_ko = sum(
        1 for page in pages for verdict in page["verdicts"] if not verdict["ok"]
    )
    regles_ko += sum(1 for verdict in robots["verdicts"] if not verdict["ok"])

    return {
        "pages": pages,
        "robots": robots,
        "resume": {
            "pages_auditees": len(pages),
            "regles_ko": regles_ko,
        },
    }


def main(argv: list[str] | None = None) -> int:
    site_dir = (Path(__file__).resolve().parent / "../site/static").resolve()
    rapport = audit_dir(site_dir)
    print(json.dumps(rapport, ensure_ascii=False, indent=2))
    return 0 if rapport["resume"]["regles_ko"] == 0 else 3


if __name__ == "__main__":
    sys.exit(main())
