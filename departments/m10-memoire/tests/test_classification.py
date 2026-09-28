"""classification.py : distinguer WCT et variance dans le registre Événements, résoudre l'affaire.

MÊME registre, MÊME ``type_entree`` (``evenement_memorise``) pour les deux — la distinction se
fait uniquement par les champs structurellement propres à chacun (jamais un tag ajouté après
coup). Régression ciblée : une variance porte AUSSI un ``wct_id`` (pour retrouver son WCT), donc un
classifieur naïf pourrait confondre les deux types sur ce seul champ — `test_identifiant_*`
ci-dessous couvre ce piège explicitement.
"""

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m10_memoire import classification


HORODATAGE = "2026-09-15T14:00:00-04:00"


def _wct_maillon(wct_id="WCT-1", lead_id="LEAD-1", ligne_id="ligne-wct-1", **overrides):
    base = {
        "type_entree": "evenement_memorise",
        "horodatage": HORODATAGE,
        "ligne_id": ligne_id,
        "wct_id": wct_id,
        "lead_id": lead_id,
        "intervention_id": "INT-1",
        "duree_reelle_minutes": 90,
        "ecart_signale": False,
        "devis_id": "DEV-1",
    }
    base.update(overrides)
    return base


def _variance_maillon(wct_id="WCT-1", evenement_id="EVT-VAR-1", ligne_id="ligne-var-1", **overrides):
    base = {
        "type_entree": "evenement_memorise",
        "horodatage": HORODATAGE,
        "ligne_id": ligne_id,
        "evenement_id": evenement_id,
        "wct_id": wct_id,
        "statut_variance": "evaluee",
        "signal_critique": False,
        "chantier_id": "CH-1",
        "lignes": [],
    }
    base.update(overrides)
    return base


def test_type_evenement_reconnait_un_wct():
    assert classification.type_evenement(_wct_maillon()) == classification.TYPE_WCT


def test_type_evenement_reconnait_une_variance():
    assert classification.type_evenement(_variance_maillon()) == classification.TYPE_VARIANCE


def test_type_evenement_none_pour_une_decision():
    maillon = {"type_entree": "decision_enregistree", "horodatage": HORODATAGE, "statut": "validee"}
    assert classification.type_evenement(maillon) is None


def test_type_evenement_none_pour_une_valeur_non_dict():
    assert classification.type_evenement(None) is None
    assert classification.type_evenement("texte") is None


def test_identifiant_wct_est_wct_id_jamais_ligne_id():
    maillon = _wct_maillon(wct_id="WCT-42", ligne_id="ligne-interne")
    assert classification.identifiant(maillon) == "WCT-42"


def test_identifiant_variance_est_evenement_id_jamais_wct_id():
    """Régression : une variance porte AUSSI wct_id (pour retrouver son WCT) — son identifiant
    PUBLIC reste evenement_id, jamais le wct_id qu'elle référence."""
    maillon = _variance_maillon(wct_id="WCT-42", evenement_id="m6-variance-WCT-42-evaluee")
    assert classification.identifiant(maillon) == "m6-variance-WCT-42-evaluee"
    assert classification.identifiant(maillon) != "WCT-42"


def test_identifiant_none_pour_un_type_non_classifie():
    assert classification.identifiant({"type_entree": "revision_signalee", "horodatage": HORODATAGE}) is None


def test_index_lead_id_par_wct_id_ignore_les_variances():
    maillons = [
        _wct_maillon(wct_id="WCT-1", lead_id="LEAD-A"),
        _variance_maillon(wct_id="WCT-1", evenement_id="EVT-1"),
    ]
    index = classification.index_lead_id_par_wct_id(maillons)
    assert index == {"WCT-1": "LEAD-A"}


def test_lead_id_direct_pour_un_wct():
    maillon = _wct_maillon(lead_id="LEAD-A")
    assert classification.lead_id(maillon, {}) == "LEAD-A"


def test_lead_id_resolu_pour_une_variance_via_wct_id():
    index = {"WCT-1": "LEAD-A"}
    maillon = _variance_maillon(wct_id="WCT-1")
    assert classification.lead_id(maillon, index) == "LEAD-A"


def test_lead_id_none_pour_une_variance_dont_le_wct_est_inconnu():
    """La variance est arrivée avant son WCT (ou le WCT n'a jamais été mémorisé) : jamais deviné."""
    maillon = _variance_maillon(wct_id="WCT-INCONNU")
    assert classification.lead_id(maillon, {}) is None


def test_evenements_de_laffaire_regroupe_wct_et_variance_de_la_meme_affaire():
    maillons = [
        _wct_maillon(wct_id="WCT-1", lead_id="LEAD-A", ligne_id="l1"),
        _variance_maillon(wct_id="WCT-1", evenement_id="EVT-1", ligne_id="l2"),
        _wct_maillon(wct_id="WCT-2", lead_id="LEAD-B", ligne_id="l3"),
    ]

    evenements = classification.evenements_de_laffaire("LEAD-A", maillons)

    assert [m["ligne_id"] for m in evenements] == ["l1", "l2"]


def test_evenements_de_laffaire_vide_si_aucune_correspondance():
    maillons = [_wct_maillon(wct_id="WCT-1", lead_id="LEAD-A")]
    assert classification.evenements_de_laffaire("LEAD-INCONNUE", maillons) == []


def test_evenements_de_laffaire_ignore_les_maillons_non_evenements():
    maillons = [
        _wct_maillon(wct_id="WCT-1", lead_id="LEAD-A", ligne_id="l1"),
        {"type_entree": "decision_enregistree", "horodatage": HORODATAGE, "statut": "validee", "ligne_id": "l2"},
    ]
    evenements = classification.evenements_de_laffaire("LEAD-A", maillons)
    assert [m["ligne_id"] for m in evenements] == ["l1"]
