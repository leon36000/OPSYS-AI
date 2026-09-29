"""PLAN T4.7 : la transition brouillon -> envoye du devis durable et la charge de `m3.devis_envoye`.

Registre EN MÉMOIRE (une liste Python), comme `test_devis_durable.py` : le passage par le stockage durable, la file
d'approbation et le bus est éprouvé par `test_envoi_devis_capacites.py`. Ici : ce que le maillon garde (qui a
approuvé, ce qui a été regardé), ce qu'il ne mélange pas (l'approbateur de l'ACCEPTATION), et ce que la charge de
l'événement ne porte JAMAIS (coût, marge, prix, lignes). Données fictives (AGENTS.md).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import pytest  # noqa: E402
from m3_estimation import devis_durable, revue_devis, soumission, verdicts  # noqa: E402

from opsys.evenements import schema  # noqa: E402
from opsys.evenements.schemas import erreurs_charge  # noqa: E402

FICTIF = True
_CREATION = "2026-09-28T14:00:00-04:00"
_DECISION = "2026-09-29T18:00:00+00:00"
_DEVIS = "M3-DEVIS-envoye-001"
_SYNTHESE = {"alerte_rouge": True, "motifs": ["PRIX_SOUS_MINIMUM_RENTABLE"], "non_evaluables": ["SERVICE_COMPLEXE"]}


def _registre_avec_un_devis(chantier_id=None):
    registre: list = []
    devis, verdict = devis_durable.creer_devis(
        _DEVIS, "lead-envoye-1", chantier_id,
        [{"description": "Gouttière alu 5 po", "quantite": "30", "unite": "pi_lin", "cout_unitaire": "10.00",
          "reference_besoin_materiau": None}],
        "0.20", _CREATION, registre,
    )
    assert verdict is None, verdict
    return registre


def _envoyer(registre, **kwargs):
    return devis_durable.marquer_devis_envoye(_DEVIS, _DECISION, registre, **kwargs)


# =========================================================================================
# La transition : ce que le maillon garde
# =========================================================================================
def test_l_envoi_garde_qui_a_approuve_a_quel_titre_et_ce_qui_a_ete_regarde_sans_perdre_le_devis():
    registre = _registre_avec_un_devis()

    devis, verdict = _envoyer(registre, approuve_par="proprio", approuve_role="nathan_owner", revue=_SYNTHESE)

    assert verdict is None
    assert devis["statut"] == "envoye" and devis["horodatage"] == _DECISION
    assert (devis["envoi_approuve_par"], devis["envoi_approuve_role"], devis["revue_envoi"]) == (
        "proprio", "nathan_owner", _SYNTHESE)
    assert str(devis["prix_total"]) == "360.00" and devis["lead_id"] == "lead-envoye-1"  # la fusion garde la création
    assert registre[-1]["type_entree"] == "transition_devis" and len(registre) == 2


def test_l_envoi_sans_trace_facultative_ecrit_exactement_le_maillon_d_avant_t4_7():
    registre = _registre_avec_un_devis()

    devis, verdict = _envoyer(registre)

    assert verdict is None
    assert registre[-1] == {
        "type_entree": "transition_devis", "devis_id": _DEVIS, "statut": "envoye", "horodatage": _DECISION}
    assert "envoi_approuve_par" not in devis and "revue_envoi" not in devis


@pytest.mark.parametrize(("nom", "valeur"), [
    ("approuve_par", ""), ("approuve_par", "   "), ("approuve_par", 12), ("approuve_par", ["proprio"]),
    ("approuve_role", ""), ("approuve_role", " "), ("approuve_role", False),
])
def test_un_nom_d_approbateur_fourni_mais_creux_est_refuse_sans_rien_ecrire(nom, valeur):
    registre = _registre_avec_un_devis()

    devis, verdict = _envoyer(registre, **{nom: valeur})

    assert devis is None and verdict["code"] == "REJ-DEVIS-APPROBATEUR-ABSENT" and nom in verdict["detail"]
    assert len(registre) == 1, "rien n'a été écrit"
    assert devis_durable.lire_devis(registre, _DEVIS)[0]["statut"] == "brouillon"


def test_on_n_envoie_qu_un_brouillon_et_un_devis_inconnu_ou_sans_horodatage_est_refuse():
    registre = _registre_avec_un_devis()
    assert _envoyer(registre)[1] is None

    assert _envoyer(registre)[1]["code"] == "REJ-DEVIS-TRANSITION-ILLEGALE"  # déjà envoyé : pas un no-op ici
    assert devis_durable.marquer_devis_envoye("inconnu", _DECISION, registre)[1]["code"] == "REJ-DEVIS-INTROUVABLE"
    assert devis_durable.marquer_devis_envoye(_DEVIS, "", registre)[1]["code"] == "REJ-DEVIS-HORODATAGE-VIDE"
    assert len(registre) == 2


def test_l_approbateur_de_l_envoi_ne_prend_pas_la_place_de_celui_de_l_acceptation():
    registre = _registre_avec_un_devis()
    _envoyer(registre, approuve_par="proprio", approuve_role="nathan_owner")

    accepte, verdict = devis_durable.marquer_devis_accepte(_DEVIS, "vendeur.un", "2026-10-02T09:00:00-04:00", registre)

    assert verdict is None and accepte["statut"] == "accepte"
    assert accepte["approbateur"] == "vendeur.un"  # celui de l'acceptation
    assert accepte["envoi_approuve_par"] == "proprio"  # celui de l'envoi, intact
    # L'acceptation (schéma fermé, PLAN T2.3-b) ne reprend rien de la trace d'envoi.
    charge = devis_durable.charge_evenement_devis_accepte(accepte)
    assert erreurs_charge("m3.devis_accepte", charge) == []
    assert not {"envoi_approuve_par", "envoi_approuve_role", "revue_envoi"} & set(charge)


def test_ni_la_vue_employe_ni_le_document_du_client_ne_montrent_la_trace_d_envoi():
    registre = _registre_avec_un_devis()
    devis, _ = _envoyer(registre, approuve_par="proprio", approuve_role="nathan_owner", revue=_SYNTHESE)

    employe, verdict = devis_durable.projeter_devis(devis, "employe")
    assert verdict is None
    client, verdict = soumission.contenu_client(devis)
    assert verdict is None

    for vue in (employe, client):
        assert not {"envoi_approuve_par", "envoi_approuve_role", "revue_envoi"} & set(vue)
    assert "revue_envoi" not in str(soumission.generer_brouillon_html(devis)[0])


# =========================================================================================
# La charge de m3.devis_envoye : un fait d'étape, sans montant
# =========================================================================================
def test_la_charge_de_l_evenement_porte_l_identite_du_devis_et_l_instant_de_l_envoi_seulement():
    registre = _registre_avec_un_devis(chantier_id="chantier-envoye-1")
    devis, _ = _envoyer(registre, approuve_par="proprio", approuve_role="nathan_owner", revue=_SYNTHESE)

    charge = devis_durable.charge_evenement_devis_envoye(devis)

    assert charge == {
        "devis_id": _DEVIS, "lead_id": "lead-envoye-1", "chantier_id": "chantier-envoye-1",
        "horodatage_envoi": _DECISION,  # celui de la transition, jamais celui de la création
    }
    assert charge["horodatage_envoi"] != _CREATION
    assert erreurs_charge("m3.devis_envoye", charge) == []
    texte = json.dumps(charge)
    assert not any(interdit in texte for interdit in ("360", "300", "0.20", "cout", "marge", "prix", "lignes", "revue"))


def test_la_charge_d_un_devis_sans_chantier_porte_un_chantier_nul():
    registre = _registre_avec_un_devis()
    devis, _ = _envoyer(registre)

    charge = devis_durable.charge_evenement_devis_envoye(devis)

    assert charge["chantier_id"] is None and erreurs_charge("m3.devis_envoye", charge) == []


def test_les_cles_de_la_charge_sont_exactement_celles_du_schema_du_catalogue():
    registre = _registre_avec_un_devis()
    devis, _ = _envoyer(registre)
    contrat = schema("m3.devis_envoye")

    charge = devis_durable.charge_evenement_devis_envoye(devis)

    assert set(charge) == set(contrat["required"]) == set(contrat["properties"])
    assert contrat["additionalProperties"] is False
    assert contrat["$id"] == "opsys.evenement/v1/m3.devis_envoye"


def test_les_codes_de_revue_et_d_envoi_du_catalogue_sont_nommes_et_exerces():
    """Un code déclaré mais jamais exercé serait un verdict orphelin : ceux de T4.7 sont exercés par
    test_revue_devis.py (revue) et test_envoi_devis_capacites.py (envoi sans décision)."""
    codes = {c for c in verdicts.CODES_M3_LIST if c.startswith(("REJ-REVUE-", "REJ-ENVOI-"))}

    assert codes == {"REJ-REVUE-DEVIS-INVALIDE", "REJ-REVUE-CONTEXTE-INVALIDE", "REJ-ENVOI-SANS-APPROBATION"}
    revue, verdict = revue_devis.evaluer_revue({}, None, None)
    assert revue is None and verdict["code"] == "REJ-REVUE-DEVIS-INVALIDE"
