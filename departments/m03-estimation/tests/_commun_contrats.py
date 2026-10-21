"""Extracteur unique des clés d'un bloc yaml de l'architecture M3.

Ce fichier existe pour qu'il n'y ait QU'UN extracteur de cette notion dans
tout le module : deux extracteurs d'une même notion peuvent diverger, et un
relecteur l'a relevé en MAJEURE — ``test_qualite_photos`` factorisait son
extracteur pendant que ``test_signaux`` réécrivait la même extraction en
ligne. Tout test de contrat aligné sur l'architecture importe
``cles_du_bloc_yaml`` d'ici et n'en réimplémente jamais une variante.

Il n'est pas nommé ``conftest.py`` parce que ce dépôt impose
``--import-mode=importlib``, sous lequel le dossier d'un conftest n'est pas
dans ``sys.path`` — mesuré : ``from _commun_contrats import ...`` échouerait
alors à l'import. Les fichiers de tests insèrent donc explicitement leur
propre dossier dans ``sys.path`` avant d'importer ce module.
"""

import re
from pathlib import Path

import pytest


def _masquer_blocs(texte):
    """Remplace le contenu de chaque bloc clôturé — clôtures comprises — par
    des espaces, caractère pour caractère, en préservant les sauts de ligne.

    La longueur totale est préservée : tout caractère hors saut de ligne
    devient un espace et tout saut de ligne est conservé, donc tout offset
    mesuré sur la vue masquée reste valide pour trancher le texte D'ORIGINE.
    """
    return re.sub(
        r"```[^\n]*\n.*?```",
        lambda correspondance: re.sub(r"[^\n]", " ", correspondance.group(0)),
        texte,
        flags=re.DOTALL,
    )


def cles_du_bloc_yaml(motif_titre, niveau_titre_suivant):
    """Extrait l'ensemble des clés du premier bloc yaml d'une section.

    Extracteur de référence pour les tests de contrat alignés sur
    l'architecture : deux extracteurs d'une même notion peuvent diverger, et
    un test passerait ou échouerait selon la variante qu'il utilise — toute
    extraction de clés d'un bloc yaml de ``03-ARCHITECTURE.md`` passe par ICI
    et nulle part ailleurs.

    ``motif_titre`` est une expression régulière compilée qui localise le
    titre de la section par son NOM — jamais par son numéro, une
    renumérotation a déjà cassé un test ancré sur un numéro. La section doit
    apparaître EXACTEMENT une fois. ``niveau_titre_suivant`` est un ENTIER :
    la profondeur maximale du titre qui ferme la section.

    Les DEUX recherches de titre — celui de la section et celui qui la ferme —
    se font sur une vue où le contenu de chaque bloc clôturé est masqué par
    ``_masquer_blocs`` ; le contenu découpé vient toujours du texte
    d'origine, les offsets de la vue y restant valides.

    Les commentaires sont exclus et le tiret de liste est toléré devant une
    clé. L'extracteur est fail-closed : titre absent ou dupliqué, ou aucune
    clé extraite (extracteur vide), fait échouer le test appelant au lieu de
    passer en silence.
    """
    # Le motif peut être une chaîne ou un motif déjà compilé : imposer la compilation
    # aux appelants ferait remonter un détail d'implémentation de cet extracteur.
    if isinstance(motif_titre, str):
        motif_titre = re.compile(motif_titre, re.MULTILINE)
    chemin_architecture = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "bmad"
        / "03-ARCHITECTURE.md"
    )
    texte = chemin_architecture.read_text(encoding="utf-8")

    # Un « # » en colonne 0 à l'intérieur d'un bloc clôturé est du CODE, pas
    # un titre : sans masquage, il fermerait la section avant son bloc yaml.
    vue = _masquer_blocs(texte)

    titres = list(motif_titre.finditer(vue))
    if len(titres) != 1:
        pytest.fail(
            "la section d'architecture localisée par son nom doit apparaître "
            f"EXACTEMENT une fois, trouvée {len(titres)} fois"
        )

    debut_section = titres[0].end()
    # Le niveau est un ENTIER, pas un motif : un appelant passant « #{1,3} » sans ancre
    # faisait matcher le premier « # » venu — y compris celui d'un commentaire DANS le
    # bloc yaml, ce qui coupait la section après sa première ligne (mesuré). Construire
    # le motif ici rend cette faute impossible.
    if not isinstance(niveau_titre_suivant, int):
        pytest.fail(
            "niveau_titre_suivant doit être un ENTIER (profondeur maximale du titre "
            f"qui ferme la section), reçu {type(niveau_titre_suivant).__name__}"
        )
    titre_suivant = re.compile(
        rf"^#{{1,{niveau_titre_suivant}}}\s", re.MULTILINE
    ).search(vue, debut_section)
    fin_section = titre_suivant.start() if titre_suivant else len(texte)
    section = texte[debut_section:fin_section]

    bloc = re.search(
        r"```(?:yaml|yml)?[^\S\n]*\n(.*?)```", section, re.DOTALL
    )
    contenu = bloc.group(1) if bloc else section

    cles_extraites = set()
    for ligne in contenu.splitlines():
        if ligne.lstrip().startswith("#"):
            continue
        correspondance = re.match(r"^\s*-?\s*([a-z_][a-z0-9_]*)\s*:", ligne)
        if correspondance:
            cles_extraites.add(correspondance.group(1))

    if not cles_extraites:
        pytest.fail(
            "extracteur vide : aucune clé extraite du bloc yaml de la section"
        )

    return cles_extraites
