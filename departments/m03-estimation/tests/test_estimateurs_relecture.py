"""Relecture adverse (autre modèle) de M3.8b : trois défauts prouvés, corrigés, gardés en tests permanents.

D1 verdict qui accusait des entrées valides quand le calcul dépasse la capacité Decimal ; D2 drapeau
`minimum_applique` faux quand le minimum relève la borne basse ; D4a `verifier_recu` qui laissait échapper une
AttributeError sur un reçu aux blocs non dictionnaires. Limites assumées, non corrigées (doc M3-ESTIMATEURS-SERVICE) :
prix calculé à partir du coût probable arrondi (D3), reçu isolé dont l'empreinte est recalculée (D4b, D5).
"""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import _commun_estimateurs as ce  # noqa: E402
from m3_estimation import estimateurs_service as es  # noqa: E402


def test_un_produit_enorme_dit_quoi_reduire_au_lieu_d_accuser_les_entrees():
    """DÉFAUT : des entrées DÉCLARÉES et VALIDES (format accepté à la déclaration)
    font échouer le calcul par dépassement de précision Decimal (prec=28), et le
    verdict dit « une valeur est absente ou mal formée » — ce qui est FAUX.
    Attendu fail-closed : un verdict qui dit quoi fournir (ex. réduire la magnitude
    ou découper l'estimation), jamais une accusation d'entrée mal formée.
    CE TEST ÉCHOUE sur le code livré : il exige le verdict adéquat."""
    version, journal = ce.declarer_ok([]), []
    mod = deepcopy(version)
    # 3 facteurs au maximum du format déclaré (9 chiffres + 6 décimales, acceptés
    # par _DECIMAL/_DECIMAL_SIGNE à la déclaration) : le produit fait ~1e27.
    mod["parametres"]["estimateurs"][ce.SOFFITE] = {
        "unite_ouvrage": "pi.lin",
        "composantes": [dict(grandeur="g", unite="unite", coefficient="999999999.999999",
                             facteur_conversion="999999999.999999",
                             source_ecrite="Déclaration fictive (essai)")],
    }
    mesure = ce.mesurer_ok(journal, mesure_id="big", grandeur="g", valeur="999999999.999999",
                           unite="unite", borne_basse="999999999.999999",
                           borne_haute="999999999.999999", service=ce.SOFFITE)
    resultat, verdict = es.estimer(version=mod, service=ce.SOFFITE, lead_id=ce.LEAD,
                                   mesures=[mesure], maintenant=ce.MAINTENANT)
    assert resultat is None
    # Le grief : le verdict actuel accuse les entrées (« absente ou mal formée »)
    # alors qu'elles sont valides — exiger un verdict qui dit quoi fournir.
    # Le code reste générique, mais le détail ne prétend plus que l'entrée est mal formée : il dit quoi faire.
    assert verdict["code"] == "REJ-ESTIMATEUR-INVALIDE"
    assert "magnitude" in verdict["detail"] and "découper" in verdict["detail"]


def test_une_borne_basse_relevee_par_le_minimum_est_dite_dans_le_recu():
    """DÉFAUT : quand le minimum déclaré relève la borne BASSE alors que la quantité
    retenue dépasse déjà le minimum, le reçu affirme ``minimum_applique: False``
    bien qu'une borne ait été relevée (ici de 70 à 100). Le drapeau ne reflète
    que la retenue (``retenue < minimum``), pas les bornes affichées.
    CE TEST ÉCHOUE sur le code livré : il exige un drapeau fidèle."""
    version, journal = ce.declarer_ok([]), []
    mod = deepcopy(version)
    mod["parametres"]["estimateurs"][ce.REVETEMENT] = {
        "unite_ouvrage": "pi2",
        "composantes": [dict(grandeur="surface_brute", unite="pi2", coefficient="1",
                             source_ecrite="d (essai)"),
                        dict(grandeur="ouverture", unite="pi2", coefficient="-1",
                             source_ecrite="d (essai)")],
        "quantite_minimum": "100",
    }
    surface = ce.mesurer_ok(journal, mesure_id="s", grandeur="surface_brute", valeur="200",
                            unite="pi2", borne_basse="160", borne_haute="200",
                            service=ce.REVETEMENT)
    ouverture = ce.mesurer_ok(journal, mesure_id="o", grandeur="ouverture", valeur="80",
                              unite="pi2", borne_basse="70", borne_haute="90",
                              service=ce.REVETEMENT)
    resultat, verdict = es.estimer(version=mod, service=ce.REVETEMENT, lead_id=ce.LEAD,
                                   mesures=[surface, ouverture], maintenant=ce.MAINTENANT)
    assert verdict is None
    # basse brute = 160 − 90 = 70, relevée à 100 par le minimum ; retenue 120 ≥ 100.
    assert resultat["quantite"]["basse"] == "100"
    assert resultat["recu"]["quantite"]["minimum_applique"] is True


def test_verifier_recu_rend_un_verdict_sur_un_recu_aux_blocs_non_dictionnaires():
    """DÉFAUT : ``verifier_recu`` promet (docstring) de « refaire l'arithmétique »
    et de rendre ``(False, verdict)`` sur un reçu altéré ; mais si ``quantite``,
    ``couts`` ou ``duree`` n'est pas un dict (liste, str, None), un
    ``AttributeError`` S'ÉCHAPPE au lieu du verdict ``REJ-ESTIMATEUR-RECU-ALTERE``.
    Le ``except`` final ne capte pas ``AttributeError`` (ni les accès ``.get``
    sur ces blocs).
    CE TEST ÉCHOUE sur le code livré : l'AttributeError s'échappe."""
    version, journal = ce.declarer_ok([]), []
    resultat, _ = es.estimer(version=version, service=ce.GOUTTIERES, lead_id=ce.LEAD,
                             mesures=ce.mesures_gouttieres(journal), maintenant=ce.MAINTENANT)
    assert resultat is not None
    for bloc in ("quantite", "couts", "duree"):
        for hostile in (["pas-un-dict"], "x", None):
            faux = deepcopy(resultat["recu"])
            faux[bloc] = hostile
            faux["empreinte"] = es._empreinte(faux)
            intact, verdict = es.verifier_recu(faux)
            assert intact is False and verdict["code"] == "REJ-ESTIMATEUR-RECU-ALTERE", (
                f"bloc {bloc}={hostile!r} : attendu (False, REJ-ESTIMATEUR-RECU-ALTERE), "
                f"reçu {(intact, verdict)}")


def test_le_drapeau_du_minimum_reste_faux_quand_aucune_borne_n_est_relevee_et_le_recu_reste_verifiable():
    version, journal = ce.declarer_ok([]), []
    mod = deepcopy(version)
    mod["parametres"]["estimateurs"][ce.REVETEMENT] = {
        "unite_ouvrage": "pi2",
        "composantes": [dict(grandeur="surface_brute", unite="pi2", coefficient="1", source_ecrite="d (essai)")],
        "quantite_minimum": "100",
    }
    surface = ce.mesurer_ok(journal, mesure_id="s", grandeur="surface_brute", valeur="200", unite="pi2",
                            borne_basse="160", borne_haute="240", service=ce.REVETEMENT)
    resultat, verdict = es.estimer(version=mod, service=ce.REVETEMENT, lead_id=ce.LEAD, mesures=[surface],
                                   maintenant=ce.MAINTENANT)
    assert verdict is None and resultat["recu"]["quantite"]["minimum_applique"] is False
    assert es.verifier_recu(resultat["recu"]) == (True, None)
    # et le reçu dont la borne basse a été relevée se vérifie aussi (même règle au recalcul)
    version2 = deepcopy(mod)
    surface2 = ce.mesurer_ok(journal, mesure_id="s2", grandeur="surface_brute", valeur="105", unite="pi2",
                             borne_basse="95", borne_haute="115", service=ce.REVETEMENT)
    resultat2, verdict2 = es.estimer(version=version2, service=ce.REVETEMENT, lead_id=ce.LEAD, mesures=[surface2],
                                     maintenant=ce.MAINTENANT)
    assert verdict2 is None and resultat2["recu"]["quantite"]["minimum_applique"] is True
    assert es.verifier_recu(resultat2["recu"]) == (True, None)


def test_le_minimum_exactement_egal_a_la_borne_basse_n_est_pas_applique():
    version, journal = ce.declarer_ok([]), []
    mod = deepcopy(version)
    mod["parametres"]["estimateurs"][ce.REVETEMENT] = {
        "unite_ouvrage": "pi2",
        "composantes": [dict(grandeur="surface_brute", unite="pi2", coefficient="1", source_ecrite="d (essai)")],
        "quantite_minimum": "100",
    }
    surface = ce.mesurer_ok(journal, mesure_id="s3", grandeur="surface_brute", valeur="105", unite="pi2",
                            borne_basse="100", borne_haute="110", service=ce.REVETEMENT)
    resultat, verdict = es.estimer(version=mod, service=ce.REVETEMENT, lead_id=ce.LEAD, mesures=[surface],
                                   maintenant=ce.MAINTENANT)
    assert verdict is None and resultat["quantite"]["basse"] == "100"
    assert resultat["recu"]["quantite"]["minimum_applique"] is False  # égalité sur la borne la plus basse
    assert es.verifier_recu(resultat["recu"]) == (True, None)
