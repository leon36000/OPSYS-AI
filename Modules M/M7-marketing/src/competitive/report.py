import re
from collections import OrderedDict

from loader import load_fixture
from analyzers import analyze_page, analyze_robots, analyze_sitemap
from compare import calculate_coverage


def _strip_html(html: str) -> str:
    """Supprime les balises HTML et normalise les espaces."""
    return re.sub(r"<[^>]+>", " ", html).strip()


def generate_report(slugs, notre_site="", base_fixtures=".", stopwords_path="", timestamp=None):
    """Génère le rapport d'analyse concurrentielle.
    Retourne un dict avec 'timestamp' et une liste 'concurrents' triée par slug.
    Aucune clé ni valeur ne contient la sous-chaîne 'score'."""
    concurrents = []
    # nettoyer le texte de notre site pour la couverture
    notre_texte = _strip_html(notre_site)
    for slug in sorted(slugs):
        try:
            data = load_fixture(slug, base_fixtures)
        except Exception as e:
            # fixture illisible
            entry = {
                "slug": slug,
                "verdicts": [{"regle": "LOAD", "verdict": "KO", "detail": f"Erreur chargement fixture '{slug}'"}],
                "couverture": 0.0,
                "verdict_couverture": "non_conforme",
            }
            concurrents.append(entry)
            continue

        # verdicts C-01 à C-05
        page_verdicts = analyze_page(data['index_html'], data['meta']['url'])
        verdicts = []
        for code in sorted(page_verdicts.keys()):
            verdicts.append({
                "regle": code,
                "verdict": page_verdicts[code],
                "detail": f"{code} analysé",
            })

        # C-06 robots
        robots_result = analyze_robots(data['robots_txt'])
        verdicts.append({
            "regle": "C-06",
            "verdict": robots_result["C-06"],
            "detail": robots_result.get("detail_C-06", ""),
        })

        # C-07 sitemap
        sitemap_result = analyze_sitemap(data['sitemap_xml'])
        verdicts.append({
            "regle": "C-07",
            "verdict": sitemap_result["C-07"],
            "detail": sitemap_result.get("detail_C-07", ""),
        })

        # couverture
        texte_concurrent = _strip_html(data['index_html'])
        couverture = calculate_coverage(notre_texte, texte_concurrent, stopwords_path)
        verdict_couverture = "conforme" if couverture >= 0.5 else "non_conforme"

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
