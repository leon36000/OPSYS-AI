#!/usr/bin/env python3
"""Matrice SQLite / PostgreSQL d'une exécution du banc : agrège les journaux de deux dossiers de `banc.py`.

Usage : python3 matrice.py DOSSIER_PG DOSSIER_SQLITE [DOSSIER_SQLITE_PLUS_RECENT …] [--md SORTIE.md] [--json
SORTIE.json] (les dossiers SQLite suivants remplacent, fichier par fichier, les entrées du premier : reprise partielle
après correctif)

Preuve de portage : python3 matrice.py --portage DOSSIER_PG [DOSSIER_PG …] [--md SORTIE.md] [--json SORTIE.json]
Une garde levée n'est comptée « portée » que si au moins un test PostgreSQL RÉEL (au moins un ordre SQL émis vers
PostgreSQL), RÉUSSI, a franchi son point de passage (`suivi_gardes.py`) ; sinon elle est « non prouvée », et la commande
sort avec le code 1. Plusieurs dossiers s'additionnent (une exécution par tranche).

Lit, pour chaque fichier de test, l'issue de chaque test : le JSONL du plugiciel pour PostgreSQL (qui porte aussi la
mesure « ordres SQL réellement émis contre PostgreSQL » : un test qui n'a émis aucun ordre PostgreSQL ne prouve rien sur
PostgreSQL), la dernière ligne du journal pytest (« 3 failed, 120 passed, 2 skipped in 41s ») pour SQLite. Regroupe par
tranche (table `TRANCHES` : premier motif qui correspond au chemin du fichier). N'invente rien : un fichier sans
journal est compté « absent ».
"""

from __future__ import annotations

import argparse
import collections
import json
import re
from pathlib import Path

# (libellé, motif du chemin) : le premier qui correspond l'emporte.
TRANCHES: list[tuple[str, str]] = [
    ("Courriel connecteurs (0040)", r"test_courriel|test_cablage_courriel|courriel_"),
    ("Connaissances M10 (0041)", r"test_connaissances|test_m5_connaissances"),
    ("Graphe M10 (0052)", r"test_mnemo"),
    ("Planificateur (0044)", r"test_cablage_planificateur|planificateur"),
    ("Entrepôt M8 / pont BI (0046)", r"test_m8_|pont_bi|entrepot"),
    ("Vision (0049)", r"test_vision"),
    ("Mémoire M10 (couche B, PostgreSQL)", r"test_memoire_|m10-memoire"),
    ("Sas social / WordPress / studio / signaux M7", r"m07-marketing|test_console_marketing|test_m7"),
    ("Cron opérateur / agents", r"test_agents_|test_cron_|test_admission_agents|test_agent_"),
    ("Liaison de cibles / CFO / MCP",
     r"test_liaison|test_cfo_|test_serveur_mcp|test_suivi_m9|test_cloture|test_historique_cloture"),
    ("Consoles (HTTP)", r"test_console_"),
    ("Fusion / PDF / sauvegarde", r"test_fusion|test_sauvegarde|test_exportation|test_deploy"),
    ("E2E concurrence", r"tests/e2e/"),
    ("M1 front office", r"m01-front-office"),
    ("M2 revenue CRM", r"m02-revenue-crm"),
    ("M3 estimation", r"m03-estimation"),
    ("M4 field ops", r"m04-field-ops"),
    ("M5 financecore", r"m05-financecore"),
    ("M6 material control", r"m06-material-control"),
    ("M8 analytics", r"m08-analytics"),
    ("M9 strategic intelligence", r"m09-strategic-intelligence"),
    ("Socle (autres)", r"^tests/"),
]
RESUME = re.compile(r"(\d+) (passed|failed|skipped|error|errors|xfailed|xpassed|deselected)")


def tranche(chemin: str) -> str:
    for libelle, motif in TRANCHES:
        if re.search(motif, chemin):
            return libelle
    return "Autres"


def _slug(cible: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", cible)


def lire_dossier(dossier: Path) -> dict[str, dict]:
    resume = json.loads((dossier / "resume.json").read_text(encoding="utf-8"))
    sortie = {}
    for entree in resume:
        compte: collections.Counter = collections.Counter()
        jsonl = dossier / f"{_slug(entree['cible'])}.jsonl"
        if jsonl.exists():  # exécution PostgreSQL : une ligne par test, issue exacte
            for ligne in jsonl.read_text(encoding="utf-8").splitlines():
                d = json.loads(ligne)
                if d["phase"] == "call":
                    compte[{"passed": "passed", "failed": "failed", "skipped": "skipped"}[d["issue"]]] += 1
                elif d["issue"] == "failed":
                    compte["error"] += 1  # échec de mise en place ou de démontage
                elif d["issue"] == "skipped":
                    compte["skipped"] += 1
        else:
            for nombre, genre in RESUME.findall(entree["derniere_ligne"]):
                compte["error" if genre == "errors" else genre] += int(nombre)
        sortie[entree["cible"]] = {"code": entree["code"], "tests": compte}
    return sortie


def ordres_pg(dossier: Path) -> dict[str, tuple[int, int]]:
    """Par fichier : (tests rapportés, tests ayant émis au moins un ordre PostgreSQL)."""
    res: dict[str, tuple[int, int]] = {}
    for jsonl in dossier.glob("*.jsonl"):
        total = touches = 0
        fichier = None
        for ligne in jsonl.read_text(encoding="utf-8").splitlines():
            d = json.loads(ligne)
            if d["phase"] != "call":
                continue
            fichier = d["nodeid"].split("::")[0]
            total += 1
            touches += d["ordres_pg"] > 0
        if fichier:
            res[fichier] = (total, touches)
    return res


def matrice(pg: Path, sqlite: Path | list[Path], redirige: Path | None = None) -> list[dict]:
    """Une ligne par tranche. `pg` : la suite telle quelle ; `redirige` (facultatif) : la même suite avec les URL SQLite
    explicites des tests redirigées vers des bases PostgreSQL (`--redirige`)."""
    dossiers = [sqlite] if isinstance(sqlite, Path) else list(sqlite)
    sources: dict[str, dict[str, dict]] = {"pg": lire_dossier(pg)}
    ordres: dict[str, dict[str, tuple[int, int]]] = {"pg": ordres_pg(pg)}
    if redirige is not None:
        sources["pgr"], ordres["pgr"] = lire_dossier(redirige), ordres_pg(redirige)
    sources["sqlite"] = {}
    for dossier in dossiers:  # les plus récents remplacent les plus anciens
        sources["sqlite"].update(lire_dossier(dossier))
    lignes: dict[str, dict] = collections.defaultdict(lambda: collections.defaultdict(int))
    for cible in sorted(set().union(*(set(v) for v in sources.values()))):
        t = lignes[tranche(cible)]
        t["fichiers"] += 1
        for cle, source in sources.items():
            entree = source.get(cible)
            if entree is None:
                t[f"{cle}_absent"] += 1
                continue
            for genre in ("passed", "failed", "error", "skipped"):
                t[f"{cle}_{genre}"] += entree["tests"].get(genre, 0)
            t[f"{cle}_fichiers_rouges"] += entree["code"] not in (0, 5)
        for cle, table in ordres.items():
            total, touches = table.get(cible, (0, 0))
            t[f"{cle}_rapportes"] += total
            t[f"{cle}_touchent_pg"] += touches
    return [{"tranche": k, **dict(v)} for k, v in sorted(lignes.items())]


def _cellule(g, cle: str) -> str:
    return f"{g(cle + '_passed', 0)} / {g(cle + '_failed', 0) + g(cle + '_error', 0)} / {g(cle + '_skipped', 0)}"


def markdown(lignes: list[dict]) -> str:
    avec_redirection = any("pgr_rapportes" in ligne for ligne in lignes)
    colonnes = ["Tranche", "Fichiers", "SQLite : réussis / échecs / ignorés", "PostgreSQL, suite telle quelle",
                "tests ayant émis du SQL PG"]
    if avec_redirection:
        colonnes += ["PostgreSQL, URL SQLite des tests redirigées", "tests ayant émis du SQL PG (redirigé)"]
    texte = "| " + " | ".join(colonnes) + " |\n|" + "|".join(["---", "---:"] + ["---"] * (len(colonnes) - 2)) + "|\n"
    tot: collections.Counter = collections.Counter()

    def rang(g) -> list[str]:
        cellules = [_cellule(g, "sqlite"), _cellule(g, "pg"), f"{g('pg_touchent_pg', 0)} sur {g('pg_rapportes', 0)}"]
        if avec_redirection:
            cellules += [_cellule(g, "pgr"), f"{g('pgr_touchent_pg', 0)} sur {g('pgr_rapportes', 0)}"]
        return cellules

    for ligne in lignes:
        texte += "| " + " | ".join([ligne["tranche"], str(ligne.get("fichiers", 0)), *rang(ligne.get)]) + " |\n"
        for k, v in ligne.items():
            if k != "tranche":
                tot[k] += v
    texte += "| " + " | ".join(["**Total**", f"**{tot['fichiers']}**", *rang(tot.get)]) + " |\n"
    return texte


def preuves_portage(dossiers: list[Path], portees: list[dict]) -> list[dict]:
    """Par point de contrôle porté : les tests PostgreSQL réussis qui l'ont franchi (cinq cités, total compté)."""
    franchis: dict[str, list[str]] = collections.defaultdict(list)
    for dossier in dossiers:
        for jsonl in dossier.glob("*.jsonl"):
            for ligne in jsonl.read_text(encoding="utf-8").splitlines():
                d = json.loads(ligne)
                if d["phase"] != "call" or d["issue"] != "passed" or d.get("ordres_pg", 0) <= 0:
                    continue
                for ident in d.get("gardes_passees", ()):
                    franchis[ident].append(d["nodeid"])
    return [{**p, "tests": len(franchis[p["id"]]), "exemples": franchis[p["id"]][:5]} for p in portees]


def markdown_portage(preuves: list[dict]) -> str:
    prouvees = [p for p in preuves if p["tests"]]
    texte = (f"{len(prouvees)} points de contrôle portés prouvés sur {len(preuves)} "
             f"({len(preuves) - len(prouvees)} non prouvés)\n\n"
             "| Fichier | Fonction | Ligne | Tests PostgreSQL réussis qui l'ont franchi | Premier test |\n"
             "|---|---|---:|---:|---|\n")
    for p in preuves:
        premier = p["exemples"][0] if p["exemples"] else "**NON PROUVÉ**"
        texte += f"| `{p['fichier']}` | `{p['fonction']}` | {p['ligne']} | {p['tests']} | `{premier}` |\n"
    return texte


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("pg", type=Path, nargs="?")
    ap.add_argument("sqlite", type=Path, nargs="*")
    ap.add_argument("--portage", type=Path, nargs="+", metavar="DOSSIER_PG",
                    help="preuve de portage des gardes levées, à partir d'un ou plusieurs dossiers `suites`")
    ap.add_argument("--redirige", type=Path, help="dossier de l'exécution `suites --redirige`")
    ap.add_argument("--md", type=Path)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    if a.portage:
        import gardes

        preuves = preuves_portage(a.portage, gardes.portees())
        texte = markdown_portage(preuves)
        if a.md:
            a.md.write_text(texte, encoding="utf-8")
        if a.json:
            a.json.write_text(json.dumps(preuves, ensure_ascii=False, indent=1), encoding="utf-8")
        print(texte.splitlines()[0])
        return 0 if all(p["tests"] for p in preuves) else 1
    if a.pg is None or not a.sqlite:
        ap.error("DOSSIER_PG et au moins un DOSSIER_SQLITE sont requis (ou --portage)")
    lignes = matrice(a.pg, a.sqlite, a.redirige)
    texte = markdown(lignes)
    if a.md:
        a.md.write_text(texte, encoding="utf-8")
    if a.json:
        a.json.write_text(json.dumps(lignes, ensure_ascii=False, indent=1), encoding="utf-8")
    print(texte)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
