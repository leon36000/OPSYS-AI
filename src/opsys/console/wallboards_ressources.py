"""Feuille de style et script des wallboards (M8.8), servis par la console (`/statique/wallboard.css` et
`wallboard.js`).

Les fichiers vivent dans `statique_wallboards/` (embarqués dans le paquet) : aucun CDN, aucune police externe, aucun
script en
ligne (la CSP n'autorise que l'origine de la console). Accessibilité (WCAG 2.2 AA) visée et vérifiée par tests :
rapports de
contraste calculés sur les paires ci-dessous, qui sont AUSSI celles que le CSS sert (le modèle de feuille de style n'a
que des
marqueurs) ; l'état n'est jamais porté par la couleur seule (texte, symbole, motif) ; navigation au clavier, focus
visible,
bouton de pause (2.2.2) ; mouvement réduit respecté ; une seule région `aria-live` (la bannière) ; mode TV à grande
échelle.

Le script manipule le DOM par `textContent` et `classList` SEULEMENT (jamais `innerHTML`) : une valeur hostile ne
devient jamais
du balisage. Il n'a aucune dépendance et s'exporte (`module.exports`) pour être exercé sous Node par les tests.
"""

from pathlib import Path

_DOSSIER = Path(__file__).resolve().parent / "statique_wallboards"

# (couleur du texte, couleur du fond) : chaque paire est vérifiée à ≥ 4,5:1 (texte normal).
PAIRES_CLAIR = {
    "texte": ("#14181d", "#ffffff"),
    "attenue": ("#4a5560", "#ffffff"),
    "ok": ("#ffffff", "#0b5d1e"),
    "attention": ("#1a1a1a", "#ffd966"),
    "critique": ("#ffffff", "#8c0020"),
    "perime": ("#1a1a1a", "#e3e6ea"),
    "inconnu": ("#1a1a1a", "#d7dce2"),
    "pause": ("#ffffff", "#0a4aa8"),
}
PAIRES_SOMBRE = {
    "texte": ("#f2f5f8", "#10151b"),
    "attenue": ("#b4bec8", "#10151b"),
    "ok": ("#ffffff", "#1c7a35"),
    "attention": ("#14181d", "#f0c14b"),
    "critique": ("#ffffff", "#c4202f"),
    "perime": ("#f2f5f8", "#3a424c"),
    "inconnu": ("#f2f5f8", "#434c57"),
    "pause": ("#14181d", "#8ab6ff"),
}


def _variables(paires: dict[str, tuple[str, str]]) -> str:
    return " ".join(f"--{nom}-fg: {fg}; --{nom}-bg: {bg};" for nom, (fg, bg) in paires.items())


CSS = (
    (_DOSSIER / "wallboard.css.modele")
    .read_text(encoding="utf-8")
    .replace("/*VARIABLES_CLAIR*/", _variables(PAIRES_CLAIR))
    .replace("/*VARIABLES_SOMBRE*/", _variables(PAIRES_SOMBRE))
)
JS = (_DOSSIER / "wallboard.js").read_text(encoding="utf-8")
