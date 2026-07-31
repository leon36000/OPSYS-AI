"""Tests M3-S002 — qualification des photos (phase RED).

Le sous-module ``m3_estimation.qualite_photos`` n'existe pas encore : ces
tests doivent ÉCHOUER à l'import. Ils définissent le contrat que
l'implémentation devra tenir :

- une photo porte EXACTEMENT six clés : ``photo_id`` (str),
  ``resolution_largeur`` (int > 0), ``resolution_hauteur`` (int > 0),
  ``eclairage`` (float, échelle 0-10), ``angle`` (str) et
  ``reference_echelle`` (dict ou None ; si dict :
  ``{type: str, dimensions_connues: bool}``) ;
- les seuils portent EXACTEMENT deux clés — ``resolution_minimale`` (int) et
  ``eclairage_minimal`` (float) — liste FERMÉE, aucune valeur par défaut ;
- une photo n'est acceptable que si ``min(largeur, hauteur)`` atteint le
  seuil : choix fail-closed, une très grande largeur ne compense jamais une
  hauteur insuffisante ;
- les bornes sont INCLUSIVES : exactement au seuil, la photo est acceptable ;
- toute déviation du contrat de seuils est rejetée ``REJ-SEUILS-INVALIDES``
  et toute photo malformée est rejetée ``REJ-PHOTOS-INVALIDES`` ;
- un lot bien formé mais insuffisant n'est PAS rejeté : il est disqualifié
  (``photos_acceptables`` faux, ``QUALITE_ENTREE_INSUFFISANTE``, prix bloqué,
  éléments manquants non vides).
"""

import re
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Localisation du paquet sous test : insertion du src/ de M3-estimation dans
# sys.path, dérivée de Path(__file__) — JAMAIS depuis le répertoire courant.
# ---------------------------------------------------------------------------
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import contrats, qualite_photos, verdicts

# ---------------------------------------------------------------------------
# Aides de construction — chaque appel retourne des dictionnaires NEUFS :
# jamais un littéral partagé qu'un test muterait pour les suivants.
# ---------------------------------------------------------------------------


def _photo_valide():
    """Retourne une photo NEUVE conforme au contrat, au-dessus des seuils."""
    return {
        "photo_id": "photo-000",
        "resolution_largeur": 4000,
        "resolution_hauteur": 3000,
        "eclairage": 8.5,
        "angle": "face",
        "reference_echelle": {
            "type": "piece_de_monnaie",
            "dimensions_connues": True,
        },
    }


def _lot_valide():
    """Retourne un lot NEUF de trois photos valides et distinctes.

    La troisième photo n'a pas de référence d'échelle : ``None`` est une
    valeur conforme du contrat, le cas nominal couvre ainsi les deux formes.
    """
    photos = []
    for index, angle in enumerate(("face", "profil", "trois_quarts")):
        photo = _photo_valide()
        photo["photo_id"] = "photo-%03d" % index
        photo["angle"] = angle
        photos.append(photo)
    photos[2]["reference_echelle"] = None
    return photos


def _seuils_valides():
    """Retourne des seuils NEUFS conformes : exactement les deux clés du contrat."""
    return {"resolution_minimale": 800, "eclairage_minimal": 4.0}


def _assert_verdict_rejet(verdict, code_attendu):
    """Asserte qu'un retour est un verdict du catalogue portant le code attendu."""
    assert verdict is not None
    assert verdicts.est_verdict(verdict["code"])
    assert verdict["code"] == code_attendu


# ---------------------------------------------------------------------------
# 1. Cas nominal.
# ---------------------------------------------------------------------------


def test_nominal_lot_valide_accepte():
    """Cas nominal : un lot entièrement au-dessus des deux seuils est accepté.

    Sans ce test, un module qui bloque TOUT passerait tous les cas de blocage.
    """
    qualification, verdict = qualite_photos.qualifier_photos(
        _lot_valide(), _seuils_valides()
    )
    assert verdict is None
    assert qualification is not None
    assert isinstance(qualification["photos_acceptables"], bool)
    assert isinstance(qualification["verdict_estimation"], str)
    assert isinstance(qualification["prix_bloque"], bool)
    assert isinstance(qualification["elements_manquants"], list)
    assert qualification["photos_acceptables"] is True
    assert qualification["prix_bloque"] is False
    assert qualification["elements_manquants"] == []


# ---------------------------------------------------------------------------
# 2. Les trois causes de blocage, chacune ISOLÉE.
# ---------------------------------------------------------------------------


def _lot_vide():
    """Retourne un lot vide : aucune photo transmise."""
    return []


def _lot_avec_resolution_sous_seuil():
    """Retourne un lot NEUF dont une photo est sous le seuil de résolution."""
    lot = _lot_valide()
    lot[1]["resolution_largeur"] = 100
    lot[1]["resolution_hauteur"] = 100
    return lot


def _lot_avec_eclairage_sous_seuil():
    """Retourne un lot NEUF dont une photo est sous le seuil d'éclairage."""
    lot = _lot_valide()
    lot[1]["eclairage"] = 0.5
    return lot


def _cles_du_bloc_yaml(motif_titre, niveaux_titre_suivant):
    """UNIQUE extracteur des clés d'un bloc yaml de l'architecture, partagé
    par tous les tests de non-dérive du fichier : deux extracteurs d'une même
    notion peuvent diverger — ce défaut a déjà été fermé trois fois dans ce
    dépôt, et un extracteur dupliqué à 74 % le réintroduirait.

    Fail-closed : si aucune clé n'est extraite, l'assertion finale échoue au
    lieu de laisser passer un contrôle vide en silence.
    """
    chemin_architecture = (
        Path(__file__).resolve().parents[1]
        / "docs"
        / "bmad"
        / "03-ARCHITECTURE.md"
    )
    texte = chemin_architecture.read_text(encoding="utf-8")

    titres = list(re.compile(motif_titre, re.MULTILINE).finditer(texte))
    assert len(titres) == 1, (
        f"le titre repéré par {motif_titre!r} doit apparaître EXACTEMENT une "
        f"fois dans l'architecture, trouvé {len(titres)} fois"
    )

    debut_section = titres[0].end()
    titre_suivant = re.compile(
        rf"^{niveaux_titre_suivant}\s", re.MULTILINE
    ).search(texte, debut_section)
    fin_section = titre_suivant.start() if titre_suivant else len(texte)
    section = texte[debut_section:fin_section]

    bloc_yaml = re.compile(
        r"^```yaml\s*\n(.*?)^```", re.MULTILINE | re.DOTALL
    ).search(section)
    cles = set()
    if bloc_yaml is not None:
        for ligne in bloc_yaml.group(1).splitlines():
            ligne = ligne.strip()
            if not ligne or ligne.startswith("#"):
                continue
            if ligne.startswith("- "):
                ligne = ligne[2:].strip()
            correspondance = re.match(r"^([a-z_][a-z0-9_]*)\s*:", ligne)
            if correspondance:
                cles.add(correspondance.group(1))
    assert cles, (
        f"aucune clé extraite du bloc yaml sous le titre repéré par "
        f"{motif_titre!r} — extracteur vide, contrôle non probant"
    )
    return cles


# Les deux motifs de titre DIFFÈRENT volontairement : ce n'est pas une
# incohérence mais le reflet des documents — mesuré, le titre SeuilsQualite
# est un titre de niveau 3 qui PORTE un numéro (« ### 2.4 Contrat d'entrée
# gelé — SeuilsQualite ») alors que le titre PhotosFournies est un titre de
# niveau 4 SANS numéro (« #### `PhotosFournies` — entrée SÉPARÉE »). Sans
# cette note, un relecteur verrait un défaut dans cette différence.
@pytest.mark.parametrize(
    "libelle, motif_titre, niveaux_titre_suivant, constante_attendue",
    [
        (
            "SeuilsQualite",
            r"^###\s+\d+(?:\.\d+)*[^\n]*SeuilsQualite[^\n]*$",
            r"#{1,3}",
            contrats.CHAMPS_SEUILS_QUALITE,
        ),
        (
            "PhotosFournies",
            r"^####\s[^\n]*PhotosFournies[^\n]*$",
            r"#{1,4}",
            contrats.CHAMPS_PHOTO,
        ),
    ],
    ids=["SeuilsQualite", "PhotosFournies"],
)
def test_les_constantes_de_contrat_sont_alignees_sur_l_architecture(
    libelle, motif_titre, niveaux_titre_suivant, constante_attendue
):
    """Ces constantes se dérivent du CADRAGE, jamais des fixtures de test :
    les fixtures décrivent le même monde que le code, donc sans ce test une
    divergence entre la constante et l'architecture resterait invisible.
    """
    cles_architecture = _cles_du_bloc_yaml(motif_titre, niveaux_titre_suivant)
    assert cles_architecture == set(constante_attendue), (
        f"cas « {libelle} » : les clés du bloc yaml de l'architecture "
        f"divergent de la constante — extraites {sorted(cles_architecture)}, "
        f"attendues {sorted(constante_attendue)}, écart "
        f"{sorted(cles_architecture ^ set(constante_attendue))}"
    )
