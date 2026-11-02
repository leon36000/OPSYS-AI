"""M2-C1 : l'assemblage du filet (module pur `filet.py`) : les registres lus deviennent des dossiers, puis le scan SLA
et l'audit d'intégrité.

Prouvé : une source illisible (`None`) rend la règle ou le contrôle qui en dépend NON ÉVALUÉ, jamais « aucune
violation » ; les faits d'un lead sont rangés pour LUI (propriétaire courant, qualification, notes humaines,
satisfaction, photos du client) ; les entrées ne sont pas modifiées. Données fictives (`fictif: true`)."""

from __future__ import annotations

import copy

from m2_revenue_crm import filet, registre, sla
from test_integrite import ACTION, auditer, ingerer, qualifier  # noqa: F401 — fabriques d'un vrai registre en mémoire

FICTIF = True
MAINT = "2026-11-02T12:00:00-05:00"
TOUS = {
    "heures_premiere_action": 24,
    "heures_lead_chaud": 4,
    "heures_demande_photos": 48,
    "heures_relance_soumission": 24,
    "heures_escalade_plainte": 12,
    "heures_assignation": 24,
    "heures_retard_tolerance": 6,
}
REGLAGES = sla.lire_reglages(TOUS, {"jours_soumission_perimee": {"etat": "ok", "valeur": 14}})


def _produire(reg, **plus):
    sources = {"devis": [], "preparees": [], "satisfactions": [], "maillons_propriete": [], "devis_integrite": []}
    return filet.produire(reg.lire(), maintenant=MAINT, reglages=REGLAGES, **{**sources, **plus})


def _regle(rapport, nom):
    return next(r for r in rapport["sla"]["regles"] if r["regle"] == nom)


def test_chaque_source_illisible_rend_sa_regle_non_evaluee_les_autres_continuent():
    reg = registre.Registre()
    ingerer(reg, "ancien", horodatage="2026-08-01T09:00:00-04:00")
    cas = {
        "satisfactions": "plainte_non_escaladee",
        "maillons_propriete": "photos_non_recues",
        "devis": "soumission_non_relancee",
        "preparees": "soumission_non_relancee",
    }
    for source, regle in cas.items():
        rapport = _produire(reg, **{source: None})
        assert _regle(rapport, regle)["etat"] == "non_evaluee" and _regle(rapport, regle)["violations"] is None, source
        autres = [r for r in rapport["sla"]["regles"] if r["regle"] != regle]
        assert all(r["etat"] != "non_evaluee" for r in autres), "une source illisible n'éteint que ses règles"
    assert all(r["etat"] == "evaluee" for r in _produire(reg)["sla"]["regles"])


def test_les_devis_de_l_audit_illisibles_rendent_les_soumissions_orphelines_non_evaluees():
    reg = registre.Registre()
    ingerer(reg, "l1")
    audit = _produire(reg, devis_integrite=None)["integrite"]
    controle = next(c for c in audit["controles"] if c["controle"] == "soumission_orpheline")
    assert controle["etat"] == "non_evalue" and controle["anomalies"] is None


def test_les_faits_d_un_lead_sont_ranges_pour_lui_proprietaire_courant_qualification_notes_et_photos():
    reg = registre.Registre()
    ingerer(reg, "l1", horodatage="2026-10-01T09:00:00-04:00")
    qualifier(reg, "l1", owner="vendeur.un", horodatage="2026-10-01T10:00:00-04:00")
    reg.ajouter(
        {
            "type_entree": "reassignation",
            "horodatage": "2026-10-02T09:00:00-04:00",
            "lead_id": "l1",
            "rang": 2,
            "nouveau_proprietaire": "vendeur.deux",
            "motif": "Reprise du dossier",
            "decide_par": "admin",
        }
    )
    reg.ajouter(
        {
            "type_entree": "interaction",
            "horodatage": "2026-10-03T09:00:00-04:00",
            "lead_id": "l1",
            "auteur": "vendeur.deux",
            "resume": "Appel",
        }
    )
    reg.ajouter(
        {
            "type_entree": "interaction",
            "horodatage": "2026-10-04T09:00:00-04:00",
            "lead_id": "l1",
            "auteur": "system:m3",
            "resume": "Note système",
        }
    )
    (dossier,) = filet.construire_dossiers(reg.lire(), devis=[], preparees=[], satisfactions=[], maillons_propriete=[])
    assert dossier["proprietaire"] == "vendeur.deux", "le propriétaire courant est celui de la dernière réassignation"
    assert dossier["qualifie_le"] == "2026-10-01T10:00:00-04:00" and dossier["statut"] == "qualifie"
    assert dossier["interactions"] == ["2026-10-03T09:00:00-04:00"], "une note du système n'est pas un contact humain"
    assert dossier["prochaine_action"] == ACTION and dossier["photos"] == 0 and dossier["satisfaction"] == {}


def test_les_devis_et_les_relances_preparees_ne_vont_qu_a_leur_lead():
    reg = registre.Registre()
    ingerer(reg, "l1")
    ingerer(reg, "l2", contact={"nom": "Deux", "telephone": "418-555-0102"}, ville="Lévis")
    devis = [
        {"devis_id": "d1", "lead_id": "l1", "statut_devis": "envoye", "horodatage_devis": "2026-09-01T09:00:00-04:00"}
    ]
    preparees = [
        {"lead_id": "l2", "regle": "relance_devis_sans_reponse", "prepare_le": "2026-09-20T09:00:00-04:00"},
        {"lead_id": "l2", "regle": "relance_lead_dormant", "prepare_le": "2026-09-21T09:00:00-04:00"},
    ]
    dossiers = {
        d["lead_id"]: d
        for d in filet.construire_dossiers(
            reg.lire(), devis=devis, preparees=preparees, satisfactions=[], maillons_propriete=[]
        )
    }
    assert [x["devis_id"] for x in dossiers["l1"]["devis"]] == ["d1"] and dossiers["l2"]["devis"] == []
    assert dossiers["l2"]["relances_preparees"] == ["2026-09-20T09:00:00-04:00"], "seule la relance de devis compte"
    assert dossiers["l1"]["relances_preparees"] == []


def test_un_lead_sans_statut_n_est_pas_un_dossier_de_sla_c_est_l_audit_qui_le_dit():
    reg = registre.Registre()
    reg.ajouter(
        {
            "type_entree": "lead_ingere",
            "horodatage": "2026-09-01T09:00:00-04:00",
            "lead_id": "casse",
            "contrat": {"lead_id": "casse", "contact": {"nom": "x"}},
        }
    )
    rapport = _produire(reg)
    assert rapport["sla"]["examines"] == 0
    assert [a["controle"] for a in rapport["integrite"]["anomalies"]][:1] == ["lead_sans_statut"]


def test_le_rapport_ne_modifie_pas_ses_entrees_et_deux_appels_sont_identiques():
    reg = registre.Registre()
    ingerer(reg, "l1", horodatage="2026-08-01T09:00:00-04:00")
    avant = copy.deepcopy(reg.lire())
    premier = _produire(reg)
    assert reg.lire() == avant and _produire(reg) == premier


def test_un_instant_de_reference_sans_fuseau_est_refuse():
    import pytest

    with pytest.raises(ValueError):
        filet.produire(
            [],
            maintenant="2026-11-02T12:00:00",
            reglages=REGLAGES,
            devis=[],
            preparees=[],
            satisfactions=[],
            maillons_propriete=[],
            devis_integrite=[],
        )
