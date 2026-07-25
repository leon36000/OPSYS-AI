"""M7-S010 — Génération du rapport d'audit concurrentiel SEO (snapshots locaux)."""
from __future__ import annotations

import re
from collections import OrderedDict
from pathlib import Path
from typing import Any, Dict, List

import sys

# Ajout du chemin racine du package competitive si nécessaire
_curr = Path(__file__).resolve().parent
if str(_curr) not in sys.path:
    sys.path.insert(0, str(_curr))

from loader import load_fixture
from analyzers import analyze_page, analyze_robots, analyze_sitemap
from compare import calculate_coverage


def _strip_html(html: str) -> str:
    """Supprime les balises HTML et normalise les espaces."""
    return re.sub(r"<[^>]+>", " ", html).strip()


def _extraire_texte_cible(html: str) -> str:
    """Extrait le texte cible pour le calcul de couverture : title + meta description + h1 + 500 premiers caractères du corps."""
    if not html:
        return ""

    # 1. Extraire le contenu de <title>
    title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    title = title_match.group(1).strip() if title_match else ""

    # 2. Extraire meta description (attribute content)
    meta_match = re.search(
        r'<meta\s+[^>]*name=["\']description["\'][^>]*content=["\']([^"\']*)["\']',
        html,
        re.IGNORECASE
    )
    meta_desc = meta_match.group(1).strip() if meta_match else ""

    # 3. Extraire tous les h1 (contenu textuel entre les balises)
    h1_matches = re.findall(r"<h1[^>]*>(.*?)</h1>", html, re.IGNORECASE | re.DOTALL)
    h1_texts = [re.sub(r"<[^>]+>", "", h).strip() for h in h1_matches]
    h1_combined = " ".join(h1_texts)

    # 4. Corps de la page : exclure head, scripts et styles
    body_html = re.sub(r"<head[^>]*>.*?</head>", "", html, flags=re.IGNORECASE | re.DOTALL)
    body_html = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", body_html, flags=re.IGNORECASE | re.DOTALL)
    body_text = _strip_html(body_html)
    body_first500 = body_text[:500] if body_text else ""

    # Concaténation des composants
    target = f"{title} {meta_desc} {h1_combined} {body_first500}"
    # Normalisation des espaces multiples
    target = re.sub(r"\s+", " ", target).strip()
    return target


def generate_report(
    slugs: List[str],
    notre_site: str = "",
    base_fixtures: str = ".",
    stopwords_path: str = "",
    timestamp: str = None,
) -> Dict[str, Any]:
    """Génère le rapport d'analyse concurrentielle.

    Retourne un dict avec 'timestamp' et une liste 'concurrents' triée par slug.
    Aucune clé ni valeur ne contient la sous-chaîne 'score'.
    """
    concurrents = []
    notre_texte_cible = _extraire_texte_cible(notre_site) if notre_site else ""

    for slug in sorted(slugs):
        try:
            data = load_fixture(slug, base_fixtures)
        except Exception as e:
            entry = {
                "slug": slug,
                "verdicts": [
                    {
                        "regle": "LOAD",
                        "verdict": "KO",
                        "detail": f"Erreur chargement fixture '{slug}'",
                    }
                ],
                "couverture": 0.0,
                "verdict_couverture": "non_conforme",
            }
            concurrents.append(entry)
            continue

        # verdicts C-01 à C-05
        page_verdicts = analyze_page(data["index_html"], data["meta"]["url"])
        verdicts: List[Dict[str, str]] = []
        for code in sorted(page_verdicts.keys()):
            verdicts.append(
                {
                    "regle": code,
                    "verdict": page_verdicts[code],
                    "detail": f"{code} analysé",
                }
            )

        # C-06 robots
        robots_result = analyze_robots(data["robots_txt"])
        verdicts.append(
            {
                "regle": "C-06",
                "verdict": robots_result["C-06"],
                "detail": robots_result.get("detail_C-06", ""),
            }
        )

        # C-07 sitemap
        sitemap_result = analyze_sitemap(data["sitemap_xml"])
        verdicts.append(
            {
                "regle": "C-07",
                "verdict": sitemap_result["C-07"],
                "detail": sitemap_result.get("detail_C-07", ""),
            }
        )

        # couverture calculée à partir du texte cible
        concurrent_texte_cible = _extraire_texte_cible(data["index_html"])
        couverture = calculate_coverage(
            notre_texte_cible, concurrent_texte_cible, stopwords_path
        )
        verdict_couverture = "conforme" if couverture >= 0.5 else "non_conforme"

        # Ajout de la règle C-08 dans les verdicts
        verdicts.append(
            {
                "regle": "C-08",
                "verdict": verdict_couverture,
                "detail": f"couverture {couverture:.3f} (cible title+meta+h1+500c)",
            }
        )

        entry = {
            "slug": slug,
            "verdicts": verdicts,
            "couverture": couverture,
            "verdict_couverture": verdict_couverture,
        }
        concurrents.append(entry)

    return {
        "timestamp": timestamp,
        "concurrents": concurrents,
    }
