"""PLAN T1.4-k, partie pure de M4 : l'assignation consignée au registre (`etats.assigner_technicien`,
`etats.technicien_assigne`) et la décision d'accès (`acces.py`), sans base ni identité réelle.

Les tests qui passent par les VRAIS outils, avec une identité d'appareil (`contexte.appele_par_appareil`),
sont dans `test_acces_par_intervention.py`. Données fictives (AGENTS.md).
"""

from __future__ import annotations

import pytest
from m4_field_ops import acces, digest, etats, outbox
from m4_field_ops.registre import Registre

FICTIF = True
SEL = "sel-t1-4-k-fictif"
H1 = "2025-06-02T08:00:00+00:00"
H2 = "2025-06-02T09:00:00+00:00"
H3 = "2025-06-02T10:00:00+00:00"

MARC = acces.Acteur(personne="marc.fictif", role="employee")
LEA = acces.Acteur(personne="lea.fictif", role="employee")
ADMIN = acces.Acteur(personne="admin.fictif", role="admin")


def _contrat(lead_id: str) -> dict:
    return {
        "lead_id": lead_id, "conversation_id": "C1", "type_travaux": "renovation_totale",
        "ville": "Montreal", "canal": "telephone",
        "contact": {"nom": "Client fictif", "telephone": "0102030405"}, "urgence_declaree": False,
    }


def _marqueur(lead_id: str) -> dict:
    return {
        "readiness_ok": True, "lead_id": lead_id, "hash_tete_registre": None,
        "horodatage": "2025-06-01T12:00:00+00:00", "empreinte": "ab" * 32,
    }


def _inscrire(registre: Registre, lead_id: str, horodatage: str = H1) -> str:
    accuse, verdict = etats.inscrire_intervention(_contrat(lead_id), _marqueur(lead_id), registre, horodatage, SEL)
    assert verdict is None, verdict
    return accuse["intervention_id"]


def _en_route(registre: Registre, intervention_id: str, technicien_id: str, horodatage: str = H3) -> None:
    accuse, verdict = etats.transitionner(
        intervention_id, "en_route", registre, horodatage,
        assignation={"intervention_id": intervention_id, "technicien_id": technicien_id},
    )
    assert verdict is None, verdict


# -- etats.assigner_technicien / etats.technicien_assigne ---------------------------------------------
def test_aucune_assignation_avant_que_quelqu_un_ne_soit_assigne():
    registre = Registre()
    i_id = _inscrire(registre, "L1")

    assert etats.technicien_assigne(registre, i_id) is None
    assert etats.technicien_assigne(registre, "intervention-inconnue") is None


def test_assigner_consigne_le_technicien_sans_changer_le_statut():
    registre = Registre()
    i_id = _inscrire(registre, "L1")

    accuse, verdict = etats.assigner_technicien(i_id, "marc.fictif", registre, H2)

    assert verdict is None
    assert accuse["intervention_id"] == i_id and accuse["technicien_id"] == "marc.fictif"
    assert accuse["horodatage"] == H2 and accuse["ligne_id"] and accuse["tete_chaine"]
    assert etats.technicien_assigne(registre, i_id) == "marc.fictif"
    assert etats.statut_courant(registre, i_id) == "planifiee"  # ce n'est pas une transition
    maillons = [m for m in registre.lire() if m["type_entree"] == etats.TYPE_ASSIGNATION]
    assert [(m["intervention_id"], m["technicien_id"]) for m in maillons] == [(i_id, "marc.fictif")]
    assert registre.valider_chaine() is True


def test_l_assignation_d_une_intervention_n_est_pas_celle_d_une_autre():
    registre = Registre()
    i1, i2 = _inscrire(registre, "L1"), _inscrire(registre, "L2", H2)
    etats.assigner_technicien(i1, "marc.fictif", registre, H2)
    etats.assigner_technicien(i2, "lea.fictif", registre, H2)

    assert etats.technicien_assigne(registre, i1) == "marc.fictif"
    assert etats.technicien_assigne(registre, i2) == "lea.fictif"


def test_le_dernier_fait_d_assignation_l_emporte_planification_puis_depart():
    """Planifiée pour Marc ; l'admin envoie Léa (transition en_route) : c'est Léa qui est en route."""
    registre = Registre()
    i_id = _inscrire(registre, "L1")
    etats.assigner_technicien(i_id, "marc.fictif", registre, H2)
    assert etats.technicien_assigne(registre, i_id) == "marc.fictif"

    _en_route(registre, i_id, "lea.fictif")

    assert etats.technicien_assigne(registre, i_id) == "lea.fictif"


def test_une_reassignation_avant_le_depart_remplace_la_precedente():
    registre = Registre()
    i_id = _inscrire(registre, "L1")
    etats.assigner_technicien(i_id, "marc.fictif", registre, H2)
    etats.assigner_technicien(i_id, "lea.fictif", registre, H3)

    assert etats.technicien_assigne(registre, i_id) == "lea.fictif"


def test_le_technicien_assigne_reste_apres_un_report():
    """Fait historique (« à qui elle est »), à lire aux côtés du statut."""
    registre = Registre()
    i_id = _inscrire(registre, "L1")
    etats.assigner_technicien(i_id, "marc.fictif", registre, H2)
    etats.transitionner(i_id, "reportee", registre, H3, motif="meteo")

    assert etats.statut_courant(registre, i_id) == "reportee"
    assert etats.technicien_assigne(registre, i_id) == "marc.fictif"


def test_lister_interventions_rend_le_technicien_assigne_avant_le_depart():
    registre = Registre()
    i1, i2 = _inscrire(registre, "L1"), _inscrire(registre, "L2", H2)
    etats.assigner_technicien(i1, "marc.fictif", registre, H2)

    par_id = {e["intervention_id"]: e for e in etats.lister_interventions(registre)}

    assert par_id[i1]["technicien_assigne"] == "marc.fictif" and par_id[i1]["statut"] == "planifiee"
    assert par_id[i2]["technicien_assigne"] is None


def test_le_maillon_d_assignation_ne_perturbe_ni_les_invariants_de_l_outbox_ni_le_digest():
    """Un maillon sans `statut` : les fonctions qui rejouent le registre (statut courant, invariants
    de complétion, digest) l'ignorent, jamais ne le confondent avec une transition."""
    registre = Registre()
    i_id = _inscrire(registre, "L1")
    etats.assigner_technicien(i_id, "marc.fictif", registre, H2)
    _en_route(registre, i_id, "marc.fictif")

    assert outbox.verifier_invariants_outbox(registre) == (True, "")
    assert etats.statut_courant(registre, i_id) == "en_route"
    resultat, verdict = digest.produire_digest(registre, "2025-06-02", "2025-06-03T00:00:00+00:00")
    assert verdict is None and resultat is not None


@pytest.mark.parametrize(("technicien_id", "code"), [
    ("", "REJ-CHAMP-VIDE"),
    (None, "REJ-CONTRAT-INVALIDE"),
    (12, "REJ-CONTRAT-INVALIDE"),
    (["marc.fictif"], "REJ-CONTRAT-INVALIDE"),
])
def test_assigner_refuse_un_technicien_absent_ou_mal_forme_sans_rien_ecrire(technicien_id, code):
    registre = Registre()
    i_id = _inscrire(registre, "L1")
    avant = registre.lire()

    accuse, verdict = etats.assigner_technicien(i_id, technicien_id, registre, H2)

    assert accuse is None and verdict["code"] == code
    assert registre.lire() == avant


def test_assigner_refuse_une_intervention_inexistante():
    registre = Registre()

    accuse, verdict = etats.assigner_technicien("intervention-fantome", "marc.fictif", registre, H2)

    assert accuse is None and verdict["code"] == "REJ-TRANSITION-ILLEGALE"
    assert registre.lire() == []


def test_assigner_refuse_une_intervention_annulee():
    registre = Registre()
    i_id = _inscrire(registre, "L1")
    etats.transitionner(i_id, "annulee", registre, H2)
    avant = registre.lire()

    accuse, verdict = etats.assigner_technicien(i_id, "marc.fictif", registre, H3)

    assert accuse is None and verdict["code"] == "REJ-TRANSITION-ILLEGALE"
    assert registre.lire() == avant


def test_assigner_refuse_un_horodatage_sans_fuseau():
    registre = Registre()
    i_id = _inscrire(registre, "L1")
    avant = registre.lire()

    accuse, verdict = etats.assigner_technicien(i_id, "marc.fictif", registre, "2025-06-02T08:00:00")

    assert accuse is None and verdict["code"] == "REJ-HORODATAGE-INVALIDE"
    assert registre.lire() == avant


# -- acces.acteur_de -------------------------------------------------------------------------------------
@pytest.mark.parametrize("role", ["employee", "admin"])
def test_acteur_de_accepte_les_deux_roles_de_terrain(role):
    acteur, verdict = acces.acteur_de("marc.fictif", role)

    assert verdict is None and acteur == acces.Acteur("marc.fictif", role)


@pytest.mark.parametrize("role", ["seller", "client", "nathan_owner", "system_agent", "manager", "", "EMPLOYEE"])
def test_acteur_de_refuse_tout_autre_role_fail_closed(role):
    acteur, verdict = acces.acteur_de("marc.fictif", role)

    assert acteur is None and verdict["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert repr(role) in verdict["detail"]


# -- acces.controler_technicien ---------------------------------------------------------------------------
def test_employe_agit_sous_son_propre_identifiant():
    assert acces.controler_technicien(MARC, "marc.fictif") is None


@pytest.mark.parametrize("fourni", ["lea.fictif", "MARC.FICTIF", "marc.fictif ", "", None, 12])
def test_employe_sous_un_autre_identifiant_est_refuse_jamais_remplace(fourni):
    verdict = acces.controler_technicien(MARC, fourni)

    assert verdict["code"] == "REJ-IDENTITE-FOURNIE-DIFFERENTE"
    assert "technicien_id" in verdict["detail"]


def test_admin_dispatche_pour_autrui_et_l_absence_d_acteur_ne_controle_rien():
    assert acces.controler_technicien(ADMIN, "marc.fictif") is None
    assert acces.controler_technicien(ADMIN, "n-importe-quoi") is None
    assert acces.controler_technicien(None, "n-importe-quoi") is None


# -- acces.controler_consultant ---------------------------------------------------------------------------
def test_le_journal_d_acces_gps_nomme_la_personne_authentifiee():
    assert acces.controler_consultant(ADMIN, "admin.fictif") is None


@pytest.mark.parametrize("acteur", [ADMIN, MARC])
def test_accede_par_different_de_la_personne_authentifiee_est_refuse_meme_pour_l_admin(acteur):
    verdict = acces.controler_consultant(acteur, "quelqu.un.d.autre")

    assert verdict["code"] == "REJ-IDENTITE-FOURNIE-DIFFERENTE"
    assert "accede_par" in verdict["detail"]


def test_sans_acteur_accede_par_reste_celui_de_l_appelant():
    assert acces.controler_consultant(None, "agent.fictif") is None


# -- acces.controler_intervention / interventions_visibles -----------------------------------------------
def test_employe_agit_sur_son_intervention_seulement():
    registre = Registre()
    i_marc, i_lea, i_personne = _inscrire(registre, "L1"), _inscrire(registre, "L2", H2), _inscrire(registre, "L3", H3)
    etats.assigner_technicien(i_marc, "marc.fictif", registre, H3)
    etats.assigner_technicien(i_lea, "lea.fictif", registre, H3)

    assert acces.controler_intervention(registre, i_marc, MARC) is None
    for autre in (i_lea, i_personne, "intervention-inconnue"):
        verdict = acces.controler_intervention(registre, autre, MARC)
        assert verdict["code"] == "REJ-INTERVENTION-NON-ASSIGNEE", autre


def test_inconnue_assignee_a_un_autre_ou_a_personne_donnent_le_meme_refus_sans_sonder_l_existence():
    registre = Registre()
    i_lea, i_personne = _inscrire(registre, "L2"), _inscrire(registre, "L3", H2)
    etats.assigner_technicien(i_lea, "lea.fictif", registre, H3)

    refus = [acces.controler_intervention(registre, i, MARC) for i in (i_lea, i_personne, "inconnue")]

    assert refus[0] == refus[1] == refus[2]


def test_admin_et_absence_d_acteur_accedent_a_toute_intervention():
    registre = Registre()
    i_lea = _inscrire(registre, "L2")
    etats.assigner_technicien(i_lea, "lea.fictif", registre, H2)

    for acteur in (ADMIN, None):
        assert acces.controler_intervention(registre, i_lea, acteur) is None
        assert acces.controler_intervention(registre, "inconnue", acteur) is None


def test_interventions_visibles_filtre_pour_l_employe_seulement():
    registre = Registre()
    i_marc, i_lea, i_personne = _inscrire(registre, "L1"), _inscrire(registre, "L2", H2), _inscrire(registre, "L3", H3)
    etats.assigner_technicien(i_marc, "marc.fictif", registre, H3)
    etats.assigner_technicien(i_lea, "lea.fictif", registre, H3)
    toutes = etats.lister_interventions(registre)
    assert {e["intervention_id"] for e in toutes} == {i_marc, i_lea, i_personne}

    assert [e["intervention_id"] for e in acces.interventions_visibles(toutes, MARC)] == [i_marc]
    assert [e["intervention_id"] for e in acces.interventions_visibles(toutes, LEA)] == [i_lea]
    assert acces.interventions_visibles(toutes, ADMIN) == toutes
    assert acces.interventions_visibles(toutes, None) == toutes
    # Jamais l'objet d'origine : l'appelant peut modifier sa liste sans toucher celle de l'état.
    assert acces.interventions_visibles(toutes, ADMIN) is not toutes


def test_un_employe_sans_intervention_voit_une_liste_vide():
    registre = Registre()
    _inscrire(registre, "L2")

    assert acces.interventions_visibles(etats.lister_interventions(registre), MARC) == []
