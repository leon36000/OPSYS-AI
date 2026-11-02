"""M2-C1 : l'audit d'intégrité des données (module pur `integrite.py`), nourri d'un VRAI registre en mémoire rempli par
les
vraies fonctions de M2 (ingestion, liens client, transitions, signalements), puis abîmé comme le ferait une donnée
héritée.

Prouvé : huit contrôles, chacun déclenché par exactement sa donnée défectueuse et jamais par un lead sain ; les doublons
reprennent le critère et la fenêtre de l'ingestion, sont listés (jamais fusionnés), et un arbitrage « distincts » les
écarte ;
un contrôle dont la source est illisible est « non évalué » (jamais zéro) ; le registre n'est jamais modifié ; l'ordre
de
sortie est total ; aucune donnée personnelle ne sort. Données fictives (`fictif: true`).
"""

from __future__ import annotations

import copy
import json

import pytest
from m2_revenue_crm import clients, doublons, ingestion, integrite, interactions, registre, statuts

FICTIF = True
ACTION = {"description": "Appeler le client", "echeance": "2026-09-05T09:00:00-04:00"}
H = "2026-09-01T09:00:00-04:00"


def _contrat(lead_id, contact=None, ville="Québec", type_travaux="renovation_totale"):
    return {
        "lead_id": lead_id,
        "conversation_id": f"conv-{lead_id}",
        "contact": contact
        if contact is not None
        else {"nom": f"Client {lead_id}", "courriel": f"{lead_id}@example.test"},
        "type_travaux": type_travaux,
        "ville": ville,
        "urgence_declaree": False,
        "canal": "telephone",
    }


def ingerer(reg, lead_id, horodatage=H, lier=True, **plus):
    contrat = _contrat(lead_id, **plus)
    _, verdict = ingestion.ingerer(contrat, reg, horodatage)
    assert verdict is None, verdict
    if lier:
        _, verdict = clients.lier_lead(reg, lead_id, contrat, horodatage)
        assert verdict is None, verdict


def qualifier(reg, lead_id, owner="vendeur.un", horodatage="2026-09-01T10:00:00-04:00"):
    _, verdict = statuts.transitionner(lead_id, "qualifie", reg, horodatage, owner=owner, prochaine_action=ACTION)
    assert verdict is None, verdict


def auditer(reg, devis=()):
    return integrite.auditer(reg.lire(), devis=None if devis is None else list(devis))


def anomalies(audit, controle=None):
    return [a for a in audit["anomalies"] if controle is None or a["controle"] == controle]


def controle(audit, nom):
    return next(c for c in audit["controles"] if c["controle"] == nom)


@pytest.fixture
def reg():
    return registre.Registre()


@pytest.fixture
def sain(reg):
    ingerer(reg, "nouveau-1")
    ingerer(reg, "qualifie-1", contact={"nom": "Q", "telephone": "418-555-0101"}, ville="Lévis")
    qualifier(reg, "qualifie-1")
    ingerer(reg, "converti-1", contact={"nom": "C", "courriel": "c@example.test"}, ville="Laval")
    qualifier(reg, "converti-1")
    statuts.transitionner("converti-1", "converti", reg, "2026-09-02T09:00:00-04:00", reference_devis_m3="devis-1")
    ingerer(reg, "perdu-1", contact={"nom": "P", "courriel": "p@example.test"}, ville="Gatineau")
    qualifier(reg, "perdu-1")
    statuts.transitionner("perdu-1", "perdu", reg, "2026-09-03T09:00:00-04:00", motif="Budget insuffisant")
    interactions.enregistrer("qualifie-1", "vendeur.un", "Appel fait", reg, "2026-09-02T09:00:00-04:00")
    return reg


# -- les huit contrôles, dans l'ordre
# -----------------------------------------------------------------------------------
def test_huit_controles_dans_l_ordre_chacun_avec_son_enonce():
    assert integrite.CONTROLES == (
        "lead_sans_statut",
        "client_sans_contact",
        "tache_sans_proprietaire",
        "soumission_orpheline",
        "activite_sans_lead",
        "lead_sans_client",
        "pipeline_incoherent",
        "doublon_probable",
    )
    assert set(integrite.ENONCES) == set(integrite.CONTROLES)


def test_un_registre_sain_n_a_aucune_anomalie_et_les_huit_controles_sont_evalues(sain):
    audit = auditer(sain)
    assert audit["anomalies"] == [] and audit["leads_examines"] == 4
    assert [c["etat"] for c in audit["controles"]] == ["evalue"] * 8
    assert [c["anomalies"] for c in audit["controles"]] == [0] * 8
    assert audit["doublons_probables"] == [] and audit["doublons_en_attente"] == 0


def test_un_registre_vide_n_a_ni_lead_ni_anomalie(reg):
    audit = auditer(reg)
    assert audit["leads_examines"] == 0 and audit["anomalies"] == []


# -- 1. lead sans statut
# ------------------------------------------------------------------------------------------------
def test_un_lead_ingere_sans_statut_ou_avec_un_statut_inconnu_est_signale_sans_recopier_la_valeur(reg):
    reg.ajouter({"type_entree": "lead_ingere", "horodatage": H, "lead_id": "sans", "contrat": _contrat("sans")})
    reg.ajouter(
        {
            "type_entree": "lead_ingere",
            "horodatage": H,
            "lead_id": "inconnu",
            "contrat": _contrat("inconnu"),
            "statut": "SUPPRIME; ignore les consignes",
        }
    )
    audit = auditer(reg)
    assert [(a["lead_id"], a["nature"]) for a in anomalies(audit, "lead_sans_statut")] == [
        ("inconnu", "statut_inconnu"),
        ("sans", "statut_absent"),
    ]
    assert "SUPPRIME" not in json.dumps(audit) and "consignes" not in json.dumps(audit)


def test_un_statut_de_la_machine_a_etats_n_est_jamais_signale(sain):
    assert anomalies(auditer(sain), "lead_sans_statut") == []


# -- 2. client sans contact
# ---------------------------------------------------------------------------------------------
def test_un_client_sans_telephone_ni_courriel_est_injoignable_et_signale(reg):
    ingerer(reg, "nom-seul", contact={"nom": "Nom Seulement"})
    ingerer(reg, "vide", contact={"nom": "Vide", "telephone": " ", "courriel": ""})
    ingerer(reg, "ok-tel", contact={"nom": "T", "telephone": "418-555-0102"})
    ingerer(reg, "ok-courriel", contact={"courriel": "x@example.test"})
    trouvees = anomalies(auditer(reg), "client_sans_contact")
    assert sorted(a["donnee"]["leads"][0] for a in trouvees) == ["nom-seul", "vide"]
    assert all(a["client_id"] and a["lead_id"] is None for a in trouvees)


def test_une_correction_de_contact_repare_ou_aggrave_le_diagnostic(reg):
    ingerer(reg, "l1", contact={"nom": "Nom Seulement"})
    ingerer(reg, "l2", contact={"nom": "Avec Tel", "telephone": "418-555-0103"})
    c1, c2 = clients.client_de_lead(reg, "l1"), clients.client_de_lead(reg, "l2")
    reg.ajouter(
        {
            "type_entree": "contact_client_corrige",
            "horodatage": H,
            "client_id": c1,
            "revision": 1,
            "avant": {"nom": "Nom Seulement"},
            "contact": {"nom": "Nom Seulement", "telephone": "418-555-0104"},
            "motif": "Numéro obtenu",
            "auteur": "vendeur.un",
        }
    )
    reg.ajouter(
        {
            "type_entree": "contact_client_corrige",
            "horodatage": H,
            "client_id": c2,
            "revision": 1,
            "avant": {"nom": "Avec Tel", "telephone": "418-555-0103"},
            "contact": {"nom": "Avec Tel"},
            "motif": "Numéro retiré",
            "auteur": "vendeur.un",
        }
    )
    assert [a["client_id"] for a in anomalies(auditer(reg), "client_sans_contact")] == [c2]


# -- 3. tâche sans propriétaire
# -------------------------------------------------------------------------------------------
def test_une_prochaine_action_sans_proprietaire_sur_un_lead_avance_est_signalee(reg):
    ingerer(reg, "orphelin")
    reg.ajouter(
        {
            "type_entree": "transition_statut",
            "horodatage": H,
            "lead_id": "orphelin",
            "statut": "qualifie",
            "statut_precedent": "nouveau",
            "prochaine_action": ACTION,
        }
    )
    ingerer(reg, "ok")
    qualifier(reg, "ok")
    ingerer(reg, "nouveau-sans-action")
    assert [(a["lead_id"], a["nature"]) for a in anomalies(auditer(reg), "tache_sans_proprietaire")] == [
        ("orphelin", "action_sans_proprietaire")
    ]


def test_une_reassignation_donne_un_proprietaire_au_lead(reg):
    ingerer(reg, "orphelin")
    reg.ajouter(
        {
            "type_entree": "transition_statut",
            "horodatage": H,
            "lead_id": "orphelin",
            "statut": "qualifie",
            "statut_precedent": "nouveau",
            "prochaine_action": ACTION,
        }
    )
    reg.ajouter(
        {
            "type_entree": "reassignation",
            "horodatage": H,
            "lead_id": "orphelin",
            "rang": 2,
            "nouveau_proprietaire": "vendeur.deux",
            "motif": "Reprise du dossier",
            "decide_par": "admin",
        }
    )
    assert anomalies(auditer(reg), "tache_sans_proprietaire") == []


# -- 4. soumission orpheline
# --------------------------------------------------------------------------------------------
def test_un_devis_dont_le_lead_est_inconnu_est_orphelin_un_devis_connu_non(sain):
    devis = [
        {"devis_id": "d-ok", "lead_id": "qualifie-1"},
        {"devis_id": "d-fantome", "lead_id": "fantome"},
        {"devis_id": "d-sans-lead", "lead_id": None},
        {"devis_id": "d-fantome", "lead_id": "fantome"},
    ]
    trouvees = anomalies(auditer(sain, devis), "soumission_orpheline")
    assert [a["donnee"]["devis_id"] for a in trouvees] == ["d-fantome", "d-sans-lead"], "un devis compté une fois"


def test_sans_la_lecture_des_devis_le_controle_est_non_evalue_pas_zero(sain):
    audit = auditer(sain, None)
    c = controle(audit, "soumission_orpheline")
    assert c["etat"] == "non_evalue" and c["anomalies"] is None and "devis_envoyes_recus" in c["manque"]
    assert anomalies(audit, "soumission_orpheline") == []


# -- 5. activité sans lead
# ----------------------------------------------------------------------------------------------
def test_une_activite_dont_le_lead_n_a_jamais_ete_ingere_est_signalee_par_lead_avec_ses_types(reg):
    ingerer(reg, "reel")
    reg.ajouter({"type_entree": "interaction", "horodatage": H, "lead_id": "fantome", "auteur": "x", "resume": "n"})
    reg.ajouter({"type_entree": "interaction", "horodatage": H, "lead_id": "fantome", "auteur": "x", "resume": "n2"})
    reg.ajouter(
        {
            "type_entree": "transition_statut",
            "horodatage": H,
            "lead_id": "fantome",
            "statut": "qualifie",
            "statut_precedent": "nouveau",
        }
    )
    reg.ajouter({"type_entree": "client_associe", "horodatage": H, "lead_id": "autre-fantome", "client_id": "c-x"})
    reg.ajouter(
        {
            "type_entree": "doublon_signale",
            "horodatage": H,
            "signalement_id": "s1",
            "lead_id_a": "reel",
            "lead_id_b": "fantome-b",
            "critere": "contact_identique",
            "arbitrage": "en_attente",
        }
    )
    trouvees = {a["lead_id"]: a["donnee"]["maillons"] for a in anomalies(auditer(reg), "activite_sans_lead")}
    assert trouvees == {
        "autre-fantome": {"client_associe": 1},
        "fantome": {"interaction": 2, "transition_statut": 1},
        "fantome-b": {"doublon_signale": 1},
    }


# -- 6. lead sans client
# ------------------------------------------------------------------------------------------------
def test_un_lead_ingere_sans_lien_client_est_signale(reg):
    ingerer(reg, "lie")
    ingerer(reg, "non-lie", lier=False)
    assert [a["lead_id"] for a in anomalies(auditer(reg), "lead_sans_client")] == ["non-lie"]


# -- 7. pipeline incohérent
# -------------------------------------------------------------------------------------------------
def _natures(reg, lead_id):
    return [a["nature"] for a in anomalies(auditer(reg), "pipeline_incoherent") if a["lead_id"] == lead_id]


def test_chaque_regle_de_la_machine_a_etats_a_son_anomalie(reg):
    cas = {
        "rompue": (
            {"statut": "converti", "statut_precedent": "qualifie", "reference_devis_m3": "d"},
            ["chaine_rompue"],
        ),
        "illegale": ({"statut": "cedule", "statut_precedent": "nouveau"}, ["transition_illegale"]),
        "q-sans-owner": (
            {"statut": "qualifie", "statut_precedent": "nouveau", "prochaine_action": ACTION},
            ["qualifie_sans_proprietaire"],
        ),
        "q-sans-action": (
            {"statut": "qualifie", "statut_precedent": "nouveau", "owner": "v"},
            ["qualifie_sans_action"],
        ),
        "q-action-invalide": (
            {
                "statut": "qualifie",
                "statut_precedent": "nouveau",
                "owner": "v",
                "prochaine_action": {"description": "x", "echeance": "demain"},
            },
            ["qualifie_sans_action"],
        ),
        "perdu-sans-motif": ({"statut": "perdu", "statut_precedent": "nouveau"}, ["perdu_sans_motif"]),
    }
    for lead_id, (transition, _) in cas.items():
        ingerer(reg, lead_id)
        reg.ajouter({"type_entree": "transition_statut", "horodatage": H, "lead_id": lead_id, **transition})
    for lead_id, (_, attendu) in cas.items():
        assert _natures(reg, lead_id) == attendu, lead_id


def test_converti_sans_devis_et_facture_sans_action_sont_signales(reg):
    ingerer(reg, "c")
    qualifier(reg, "c")
    reg.ajouter(
        {
            "type_entree": "transition_statut",
            "horodatage": H,
            "lead_id": "c",
            "statut": "converti",
            "statut_precedent": "qualifie",
            "reference_devis_m3": " ",
        }
    )
    reg.ajouter(
        {
            "type_entree": "transition_statut",
            "horodatage": H,
            "lead_id": "c",
            "statut": "cedule",
            "statut_precedent": "converti",
        }
    )
    reg.ajouter(
        {
            "type_entree": "transition_statut",
            "horodatage": H,
            "lead_id": "c",
            "statut": "chantier",
            "statut_precedent": "cedule",
        }
    )
    reg.ajouter(
        {
            "type_entree": "transition_statut",
            "horodatage": H,
            "lead_id": "c",
            "statut": "facture",
            "statut_precedent": "chantier",
        }
    )
    assert _natures(reg, "c") == ["converti_sans_devis", "facture_sans_action"]


def test_une_transition_apres_une_perte_est_illegale(reg):
    ingerer(reg, "p")
    qualifier(reg, "p")
    statuts.transitionner("p", "perdu", reg, H, motif="Budget insuffisant")
    reg.ajouter(
        {
            "type_entree": "transition_statut",
            "horodatage": H,
            "lead_id": "p",
            "statut": "converti",
            "statut_precedent": "perdu",
            "reference_devis_m3": "d",
        }
    )
    assert "transition_illegale" in _natures(reg, "p")


def test_un_historique_complet_et_legal_n_a_aucune_anomalie_de_pipeline(reg):
    ingerer(reg, "tout")
    qualifier(reg, "tout")
    for statut, extra in (
        ("converti", {"reference_devis_m3": "d"}),
        ("cedule", {}),
        ("chantier", {}),
        ("facture", {"prochaine_action": ACTION}),
        ("paiement", {}),
        ("avis", {}),
    ):
        _, verdict = statuts.transitionner("tout", statut, reg, "2026-09-10T09:00:00-04:00", **extra)
        assert verdict is None, verdict
    assert anomalies(auditer(reg), "pipeline_incoherent") == []


# -- 8. doublons probables (lecture seule)
# -------------------------------------------------------------------------------------
def _paire(reg, a="dup-a", b="dup-b", **plus_b):
    meme = {"nom": "Même Client", "telephone": "418-555-0199"}
    ingerer(reg, a, contact=meme, horodatage="2026-09-01T09:00:00-04:00")
    ingerer(
        reg,
        b,
        contact=plus_b.pop("contact", meme),
        horodatage=plus_b.pop("horodatage", "2026-09-03T09:00:00-04:00"),
        **plus_b,
    )


def test_deux_leads_au_meme_contact_dans_la_fenetre_non_signales_sont_une_anomalie(reg):
    _paire(reg)
    (anomalie,) = anomalies(auditer(reg), "doublon_probable")
    assert anomalie["lead_id"] == "dup-a" and anomalie["donnee"] == {
        "autre_lead_id": "dup-b",
        "critere": "contact_identique",
    }


def test_meme_ville_et_memes_travaux_sont_aussi_un_critere_comme_a_l_ingestion(reg):
    _paire(reg, contact={"nom": "Autre Personne", "telephone": "418-555-0188"})
    (anomalie,) = anomalies(auditer(reg), "doublon_probable")
    assert anomalie["donnee"]["critere"] == "ville_et_travaux"


def test_un_doublon_deja_signale_est_liste_en_attente_jamais_compte_comme_anomalie(reg):
    _paire(reg)
    signalement, verdict = doublons.signaler(reg, "dup-a", "dup-b", "2026-09-03T09:00:00-04:00")
    assert verdict is None
    audit = auditer(reg)
    assert anomalies(audit, "doublon_probable") == []
    assert audit["doublons_en_attente"] == 1 and audit["doublons_probables"] == [
        {
            "lead_id_a": "dup-a",
            "lead_id_b": "dup-b",
            "critere": "contact_identique",
            "signale": True,
            "arbitrage": "en_attente",
        }
    ]
    doublons.arbitrer(reg, signalement["signalement_id"], "distincts_confirmes", "2026-09-04T09:00:00-04:00")
    apres = auditer(reg)
    assert apres["doublons_probables"] == [] and apres["doublons_en_attente"] == 0, "un humain a tranché"


def test_hors_de_la_fenetre_de_sept_jours_ou_sans_donnee_commune_rien_n_est_rapproche(reg):
    _paire(reg, horodatage="2026-09-20T09:00:00-04:00")
    ingerer(
        reg,
        "autre-ville",
        contact={"nom": "Z", "telephone": "418-555-0177"},
        ville="Rimouski",
        horodatage="2026-09-03T09:00:00-04:00",
    )
    assert anomalies(auditer(reg), "doublon_probable") == []


def test_le_meme_critere_et_la_meme_fenetre_que_la_detection_de_l_ingestion(reg):
    _paire(reg)
    assert doublons.detecter(reg, "dup-b") == ["dup-a"]
    assert [a["lead_id"] for a in anomalies(auditer(reg), "doublon_probable")] == ["dup-a"]


def test_le_travail_de_rapprochement_est_borne_et_le_dit(reg, monkeypatch):
    for k in range(6):
        ingerer(
            reg,
            f"l{k}",
            contact={"nom": f"N{k}", "telephone": f"418-555-01{k:02d}"},
            ville="Québec",
            horodatage=f"2026-09-0{k + 1}T09:00:00-04:00",
        )
    monkeypatch.setattr(integrite, "MAX_PAIRES_EXAMINEES", 3)
    c = controle(auditer(reg), "doublon_probable")
    assert c["etat"] == "partiel" and "paires" in c["manque"]


# -- propriétés générales
# -----------------------------------------------------------------------------------------------------
def test_l_audit_ne_modifie_jamais_le_registre_et_deux_audits_sont_identiques(sain):
    sain.ajouter({"type_entree": "interaction", "horodatage": H, "lead_id": "fantome", "auteur": "x", "resume": "n"})
    avant = copy.deepcopy(sain.lire())
    premier = auditer(sain)
    assert sain.lire() == avant and sain.valider_chaine()
    assert auditer(sain) == premier


def test_les_anomalies_sont_triees_par_controle_puis_par_identifiants(reg):
    ingerer(reg, "b", lier=False)
    ingerer(reg, "a", lier=False)
    reg.ajouter({"type_entree": "interaction", "horodatage": H, "lead_id": "z-fantome", "auteur": "x", "resume": "n"})
    audit = auditer(reg)
    rang = {c: i for i, c in enumerate(integrite.CONTROLES)}
    assert [rang[a["controle"]] for a in audit["anomalies"]] == sorted(rang[a["controle"]] for a in audit["anomalies"])
    assert [a["lead_id"] for a in anomalies(audit, "lead_sans_client")] == ["a", "b"]


def test_aucune_donnee_personnelle_ne_sort_de_l_audit(reg):
    ingerer(reg, "pers", contact={"nom": "Jeanne Tremblay"}, lier=True)
    reg.ajouter(
        {
            "type_entree": "interaction",
            "horodatage": H,
            "lead_id": "fantome",
            "auteur": "jeanne.t",
            "resume": "Appeler Jeanne au 418-555-0100",
        }
    )
    texte = json.dumps(auditer(reg, [{"devis_id": "d", "lead_id": "fantome", "contact": "x@example.test"}]))
    for personnel in ("Jeanne", "Tremblay", "418-555", "example.test", "jeanne.t", "Appeler"):
        assert personnel not in texte


def test_le_module_est_pur_aucun_import_opsys_ni_horloge():
    from pathlib import Path

    source = Path(integrite.__file__).read_text(encoding="utf-8")
    assert "import opsys" not in source and "from opsys" not in source
    for interdit in ("datetime.now", "datetime.utcnow", "time.time", "import random"):
        assert interdit not in source
