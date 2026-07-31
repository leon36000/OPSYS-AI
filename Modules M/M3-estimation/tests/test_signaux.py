"""Tests M3 — signal de relance « DEMANDE_ENTREES_VISUELLES ».

Ces tests définissent le contrat du sous-module ``m3_estimation.signaux`` :

- le signal porte EXACTEMENT les cinq clés de ``signaux.CHAMPS_SIGNAL``,
  ``type`` vaut ``TYPE_SIGNAL`` et ``emission_count`` vaut toujours
  ``EMISSION_UNIQUE`` — un signal par estimation, jamais de relance en boucle ;
- ``elements_manquants`` est copié défensivement : muter la liste de
  l'appelant APRÈS l'appel ne modifie pas le signal déjà construit ;
- toute entrée invalide (identifiant vide ou non chaîne, liste absente, vide,
  ou contenant un élément non chaîne ou vide) est rejetée par un verdict
  ``REJ-SIGNAL-INVALIDE``, code qui appartient au catalogue fermé M3 ;
- les clés du signal restent alignées sur la section d'architecture
  « Signal de relance vers M2 », localisée par son NOM et non par son numéro.

Piège déjà coûteux sur une autre story : ``verdicts.est_verdict`` prend le
CODE du verdict, jamais le dict.
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

from m3_estimation import signaux, verdicts
import sys as _s2
from pathlib import Path as _P2
_s2.path.insert(0, str(_P2(__file__).resolve().parent))
from _commun_contrats import cles_du_bloc_yaml


# ---------------------------------------------------------------------------
# Aide de module (fixture)
# ---------------------------------------------------------------------------
def _elements_manquants_valides():
    """Rend une liste ``elements_manquants`` valide, neuve à chaque appel."""
    return ["photos_face_nord", "photos_combles"]


# ---------------------------------------------------------------------------
# 1. Nominal
# ---------------------------------------------------------------------------
def test_nominal_signal_conforme():
    """Nominal : clés exactes, type et compteur ratifiés, verdict None."""
    elements = _elements_manquants_valides()
    signal, verdict = signaux.construire_signal_relance("L1", "D1", elements)

    assert verdict is None
    assert isinstance(signal, dict)
    assert tuple(signal.keys()) == tuple(signaux.CHAMPS_SIGNAL)
    assert signal["type"] == signaux.TYPE_SIGNAL
    assert signal["type"] == "DEMANDE_ENTREES_VISUELLES"
    assert signal["lead_id"] == "L1"
    assert signal["devis_id"] == "D1"
    assert signal["elements_manquants"] == elements
    assert signal["emission_count"] == signaux.EMISSION_UNIQUE
    assert signal["emission_count"] == 1


# ---------------------------------------------------------------------------
# 2. Aucune boucle
# ---------------------------------------------------------------------------
def test_aucune_boucle_emission_toujours_unique():
    """Deux appels successifs portent chacun ``emission_count == 1``.

    Le cadrage fixe « toujours 1 en v1 » : un compteur qui s'incrémenterait
    entre appels le violerait.
    """
    premier, verdict_premier = signaux.construire_signal_relance(
        "L1", "D1", _elements_manquants_valides()
    )
    second, verdict_second = signaux.construire_signal_relance(
        "L1", "D1", _elements_manquants_valides()
    )

    assert verdict_premier is None
    assert verdict_second is None
    assert premier["emission_count"] == 1
    assert second["emission_count"] == 1
    assert premier["emission_count"] == signaux.EMISSION_UNIQUE
    assert second["emission_count"] == signaux.EMISSION_UNIQUE


# ---------------------------------------------------------------------------
# 3. Copie défensive
# ---------------------------------------------------------------------------
def test_copie_defensive_elements_manquants():
    """Muter la liste passée APRÈS l'appel ne modifie pas le signal.

    Sans copie, un appelant pourrait vider la liste du signal déjà construit.
    """
    elements = _elements_manquants_valides()
    instantane = list(elements)
    signal, verdict = signaux.construire_signal_relance("L1", "D1", elements)

    assert verdict is None
    elements.clear()
    elements.append("mutation_apres_construction")

    assert signal["elements_manquants"] is not elements
    assert signal["elements_manquants"] == instantane


# ---------------------------------------------------------------------------
# 4. Liste vide refusée
# ---------------------------------------------------------------------------
def test_liste_vide_refusee():
    """``elements_manquants == []`` est refusé : REJ-SIGNAL-INVALIDE.

    Un signal qui ne dit pas ce qui manque n'aide personne.
    """
    signal, verdict = signaux.construire_signal_relance("L1", "D1", [])

    assert signal is None
    assert verdict is not None
    assert verdict["code"] == "REJ-SIGNAL-INVALIDE"
    assert verdicts.est_verdict(verdict["code"])


# ---------------------------------------------------------------------------
# 5. Fautes — chaque cas n'introduit QU'UNE faute
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "champ_fautif,valeur_fautive",
    [
        ("lead_id", ""),
        ("devis_id", ""),
        ("lead_id", 42),
        ("elements_manquants", "photos_face_nord"),
        ("elements_manquants", ["photos_face_nord", 42]),
        ("elements_manquants", ["photos_face_nord", ""]),
    ],
    ids=[
        "lead_id_vide",
        "devis_id_vide",
        "lead_id_non_chaine",
        "elements_non_liste",
        "element_non_chaine",
        "element_chaine_vide",
    ],
)
def test_faute_unique_rejetee(champ_fautif, valeur_fautive):
    """Une faute unique par cas : rejet ``REJ-SIGNAL-INVALIDE``.

    Les trois arguments partent valides ; une seule surcharge introduit la
    faute du cas, ce qui garantit que le rejet vise bien cette faute-là.
    """
    arguments = {
        "lead_id": "L1",
        "devis_id": "D1",
        "elements_manquants": _elements_manquants_valides(),
    }
    arguments[champ_fautif] = valeur_fautive

    signal, verdict = signaux.construire_signal_relance(**arguments)

    assert signal is None
    assert verdict is not None
    assert verdict["code"] == "REJ-SIGNAL-INVALIDE"
    assert verdicts.est_verdict(verdict["code"])


# ---------------------------------------------------------------------------
# 6. Le code appartient au catalogue
# ---------------------------------------------------------------------------
def test_code_rejet_dans_catalogue():
    """``REJ-SIGNAL-INVALIDE`` figure dans le catalogue fermé des verdicts M3."""
    assert "REJ-SIGNAL-INVALIDE" in verdicts.CODES_M3_LIST
    assert verdicts.est_verdict("REJ-SIGNAL-INVALIDE")


# ---------------------------------------------------------------------------
# 7. Non-dérive du contrat : alignement sur l'architecture
# ---------------------------------------------------------------------------
def test_contrat_aligne_sur_architecture():
    """Les clés du signal restent celles de la section d'architecture.

    La section est localisée par son NOM — un titre de niveau 3 contenant
    « Signal de relance vers M2 », avec un numéro quelconque de la forme
    ``<entier>.<entier>`` — et non par son numéro : une renumérotation a déjà
    cassé un test ancré sur un numéro. L'extraction est déléguée à
    ``_commun_contrats.cles_du_bloc_yaml``, extracteur unique et fail-closed :
    s'il n'extrait aucune clé, le test échoue au lieu de passer en silence.
    """
    motif_titre = re.compile(
        r"^###\s+\d+\.\d+[^\n]*Signal de relance vers M2[^\n]*$",
        re.MULTILINE,
    )
    cles_extraites = cles_du_bloc_yaml(motif_titre, 3)

    assert len(signaux.CHAMPS_SIGNAL) == 5
    assert cles_extraites == set(signaux.CHAMPS_SIGNAL)
