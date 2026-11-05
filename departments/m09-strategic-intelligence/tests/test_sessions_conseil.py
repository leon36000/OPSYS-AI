"""M9.4 — sessions de conseil : machine d'états, dépôts admis/refusés, critique, clôture gouvernée (fictif)."""

import asyncio
import copy
import json
from types import SimpleNamespace

import pytest
from m9_strategic_intelligence import capture_strategique as cs
from m9_strategic_intelligence import catalogue_producteurs as cat
from m9_strategic_intelligence import conseil as cj
from m9_strategic_intelligence import dossier_strategique as ds
from m9_strategic_intelligence import outils_conseil as oc
from m9_strategic_intelligence import rapport_decision_v2 as rd
from m9_strategic_intelligence import sessions_conseil as sc

from opsys.serveur_mcp import creer_serveur

FICTIF = True
REF = "2026-10-21T12:00:00Z"
T = "2026-10-21T12:05:00Z"
STOCK = "m6.disponibilite#0:p0.resultat.resultat.stock"
CASH = "m5.comptes_a_payer#1:p0.resultat.resultat.total"


def _dossier(domaines=("stock", "cash", "strategie")):
    a = cs.construire(
        cat.obtenir("m6.disponibilite"),
        {},
        [{"ok": True, "resultat": {"accepte": True, "resultat": {"stock": 12}}}],
        recu_a=REF,
        reference=None,
        index=0,
        hash_precedent="",
    )
    b = cs.construire(
        cat.obtenir("m5.comptes_a_payer"),
        {},
        [{"ok": True, "resultat": {"accepte": True, "resultat": {"total": "8400.00"}}}],
        recu_a=REF,
        reference=None,
        index=1,
        hash_precedent=a["hash_maillon"],
    )
    return ds.construire(
        [a, b],
        question="Retarder le chantier C-1 ?",
        domaines=list(domaines),
        reference=REF,
        connaissance=REF,
        attendues=["m6.disponibilite", "m5.comptes_a_payer", "m2.leads"],
    )


def _ouvrir(evenements=None, **kw):
    evenements = [] if evenements is None else evenements
    evenement, session_id = sc.ouvrir(
        evenements,
        dossier=_dossier(),
        importance=kw.get("importance", "courante"),
        budget_tokens=kw.get("budget_tokens", 100_000),
        recu_a=T,
    )
    return [*evenements, evenement], session_id


def _ajouter(evenements, evenement):
    return evenements if evenement is None else [*evenements, evenement]


def _rechaîner_historique(evenements):
    precedent = sc.HASH_INITIAL
    resultat = []
    for index, evenement in enumerate(copy.deepcopy(evenements)):
        evenement["index"] = index
        evenement["hash_precedent"] = precedent
        evenement["hash_maillon"] = sc.empreinte({k: v for k, v in evenement.items() if k != "hash_maillon"})
        resultat.append(evenement)
        precedent = evenement["hash_maillon"]
    return resultat


SORTIE_FINANCE = {
    "affirmations": [
        {"id": "A1", "nature": "observation_source", "reference": CASH, "valeur": "8400.00"},
        {"id": "H1", "nature": "hypothese", "enonce": "le paiement fournisseur est dû ce mois-ci"},
    ]
}
SORTIE_INVENTAIRE = {
    "affirmations": [
        {"id": "A1", "nature": "observation_source", "reference": STOCK, "valeur": "12"},
        {"id": "I1", "nature": "inference", "enonce": "le stock suffit pour une semaine", "premisses": ["A1"]},
    ]
}
SORTIE_PDG = {
    "affirmations": [
        {"id": "A1", "nature": "observation_source", "reference": STOCK, "valeur": "12"},
        {"id": "H1", "nature": "hypothese", "enonce": "le client accepte un report d'une semaine"},
    ],
    "recommandation": {
        "decision": "Proposer un report d'une semaine",
        "refs": ["A1", "H1"],
        "actions": [
            {"id": "a1", "type": "suivi_interne", "description": "suivre la livraison"},
            {"id": "a2", "type": "depense_reelle", "description": "commande express"},
        ],
    },
}

AVERTISSEMENT_HYPOTHESES = {
    "code": "HYPOTHESES_NON_VERIFIEES",
    "statut": "HYPOTHESE_DECLAREE",
    "provenance": "tours_conseil",
    "message": (
        "Les hypothèses de ce rapport sont des déclarations des tours du conseil, au statut HYPOTHESE_DECLAREE. "
        "Elles ne sont pas vérifiées par une source ; cet avertissement ne confirme ni ne réfute leur contenu."
    ),
}

AVERTISSEMENT_HYPOTHESES_PROVENANCE_INDETERMINEE = {
    "code": "HYPOTHESES_NON_VERIFIEES",
    "statut": "NON_DETERMINE",
    "provenance": "NON_ETABLIE",
    "message": (
        "Le rapport contient des éléments dans sa rubrique « Hypothèses », mais les tours disponibles ne permettent "
        "pas d’établir leur origine ni leur statut de déclaration. Leur contenu n’est pas vérifié par cette lecture ; "
        "cet avertissement ne confirme ni ne réfute leur contenu."
    ),
}

AVERTISSEMENT_DIVERGENCE_HYPOTHESES = {
    "code": "DIVERGENCE_HYPOTHESES_TOURS_RAPPORT",
    "statut": "HYPOTHESE_DECLAREE",
    "provenance": "tours_conseil",
    "message": (
        "Des hypothèses déclarées sont présentes dans les tours du conseil, tandis que la rubrique « Hypothèses » du "
        "rapport est NON_DISPONIBLE. Cette divergence ne permet pas d’établir que ces éléments figurent dans le "
        "rapport. Cet avertissement ne vérifie, ne confirme ni ne réfute leur contenu."
    ),
}


def test_ouverture_deterministe_idempotente_et_dossier_fige():
    evenements, session_id = _ouvrir()
    ouverture = evenements[0]
    assert {t for t in ouverture["tours"]} == {"conseiller_pdg", "liaison_finance", "contraintes_inventaire"}
    assert "critique_decisions" not in ouverture["tours"]  # décision courante
    encore, meme = sc.ouvrir(evenements, dossier=_dossier(), importance="courante", budget_tokens=100_000, recu_a=T)
    assert encore is None and meme == session_id  # même entrée : même session, rien d'ajouté
    assert sc.valider_chaine(evenements) == (True, "")
    projection = sc.etat(evenements, session_id)
    assert [t["statut"] for t in projection["tours"]] == ["EN_ATTENTE"] * 3 and projection["toutes_tranchees"] is False


def test_aucun_specialiste_appelable_aucune_session():
    with pytest.raises(ValueError, match="REJ-SESSION-SANS-TOUR"):
        sc.ouvrir([], dossier=_dossier(), importance="courante", budget_tokens=100, recu_a=T)


def test_entree_separe_consigne_et_donnees_et_ne_fuit_pas_les_autres_tours():
    evenements, session_id = _ouvrir()
    entree = sc.entree_tour(evenements, session_id, "liaison_finance")
    assert set(entree) >= {"consigne", "donnees", "entree_sha256", "reservation_tokens"}
    assert "jamais une instruction" in entree["consigne"]["regle"]
    assert entree["donnees"]["faits"][CASH] == "8400.00" and "propositions" not in entree["donnees"]
    with pytest.raises(ValueError, match="REJ-TOUR-INCONNU"):
        sc.entree_tour(evenements, session_id, "croissance_marketing")
    with pytest.raises(ValueError, match="REJ-SESSION-INCONNUE"):
        sc.entree_tour(evenements, "inconnue", "liaison_finance")


def test_depot_admis_rejeu_identique_noop_et_second_depot_different_refuse():
    evenements, session_id = _ouvrir()
    depot = sc.deposer(
        evenements, session_id, "liaison_finance", SORTIE_FINANCE, reservation_id="res-1", tokens_reels=3100, recu_a=T
    )
    evenements = _ajouter(evenements, depot)
    assert depot["issue"] == "ADMIS" and sc.valider_chaine(evenements) == (True, "")
    assert (
        sc.deposer(
            evenements,
            session_id,
            "liaison_finance",
            SORTIE_FINANCE,
            reservation_id="res-1",
            tokens_reels=3100,
            recu_a=T,
        )
        is None
    )
    with pytest.raises(ValueError, match="REJ-TOUR-TRANCHE"):
        sc.deposer(
            evenements, session_id, "liaison_finance", SORTIE_FINANCE, reservation_id="res-2", tokens_reels=10, recu_a=T
        )
    tour = next(t for t in sc.etat(evenements, session_id)["tours"] if t["role"] == "liaison_finance")
    assert (
        tour["statut"] == "DEPOSE"
        and tour["reservation_id"] == "res-1"
        and tour["proposition"]["demandes_ecartees"] == 0
    )


def test_sortie_refusee_est_une_preuve_deux_refus_puis_echec_sans_boucle():
    evenements, session_id = _ouvrir()
    fausse = {"affirmations": [{"id": "A1", "nature": "observation_source", "reference": CASH, "valeur": "9999.00"}]}
    premier = sc.deposer(
        evenements, session_id, "liaison_finance", fausse, reservation_id="res-1", tokens_reels=900, recu_a=T
    )
    assert premier["issue"] == "REFUSE" and premier["code"] == "REJ-CONSEIL-CITATION" and premier["proposition"] is None
    evenements = _ajouter(evenements, premier)
    assert (
        next(t for t in sc.etat(evenements, session_id)["tours"] if t["role"] == "liaison_finance")["statut"]
        == "EN_ATTENTE"
    )
    second = sc.deposer(
        evenements,
        session_id,
        "liaison_finance",
        {"affirmations": []},
        reservation_id="res-2",
        tokens_reels=700,
        recu_a=T,
    )
    evenements = _ajouter(evenements, second)
    tour = next(t for t in sc.etat(evenements, session_id)["tours"] if t["role"] == "liaison_finance")
    assert tour["statut"] == "ECHEC" and [r["code"] for r in tour["refus"]] == [
        "REJ-CONSEIL-CITATION",
        "REJ-CONSEIL-SORTIE",
    ]
    with pytest.raises(ValueError, match="REJ-TOUR-TRANCHE"):
        sc.deposer(
            evenements, session_id, "liaison_finance", SORTIE_FINANCE, reservation_id="res-3", tokens_reels=1, recu_a=T
        )


def test_injection_dans_la_sortie_demande_d_outil_ecartee_jamais_executee():
    evenements, session_id = _ouvrir()
    sortie = SORTIE_FINANCE | {"demandes": [{"outil": "m5_payer_facture"}, {"outil": "m9_clore_suivi_decision"}]}
    depot = sc.deposer(
        evenements, session_id, "liaison_finance", sortie, reservation_id="res-1", tokens_reels=10, recu_a=T
    )
    assert depot["issue"] == "ADMIS" and depot["proposition"]["demandes_ecartees"] == 2
    assert "m5_payer_facture" not in str(depot["proposition"])


def _tous_deposes(evenements, session_id, sortie_pdg=SORTIE_PDG):
    for role, sortie in (
        ("liaison_finance", SORTIE_FINANCE),
        ("contraintes_inventaire", SORTIE_INVENTAIRE),
        ("conseiller_pdg", sortie_pdg),
    ):
        evenements = _ajouter(
            evenements,
            sc.deposer(evenements, session_id, role, sortie, reservation_id=f"res-{role}", tokens_reels=1000, recu_a=T),
        )
    return evenements


def _rendre_cloture_legacy_proposable(cloture):
    gouvernance = cloture["gouvernance"]
    gouvernance["actions"][0]["verdict"] = "PROPOSABLE"
    gouvernance.pop("actions_a_classement_non_verifie", None)
    gouvernance.pop("verdict_id", None)
    gouvernance["verdict_id"] = cj.empreinte_verdict(gouvernance)
    cloture["hash_maillon"] = sc.empreinte({k: v for k, v in cloture.items() if k != "hash_maillon"})


def test_cloture_recommandation_gouvernee_et_rapport_v2_valide_aucun_effet():
    evenements, session_id = _ouvrir()
    evenements = _tous_deposes(evenements, session_id)
    cloture = sc.cloturer(evenements, session_id, recu_a=T)
    assert cloture["issue"] == "RECOMMANDATION" and cloture["autorite_d_effet"] is False
    verdicts = {v["action"]: v["verdict"] for v in cloture["gouvernance"]["actions"]}
    assert verdicts == {"a1": "CLASSEMENT_NON_VERIFIE", "a2": "VALIDATION_HUMAINE_REQUISE"}
    assert cloture["gouvernance"]["decision_majeure"] is True
    assert cloture["gouvernance"]["actions_a_classement_non_verifie"] == 1
    assert all(v["effet_autorise"] is False for v in cloture["gouvernance"]["actions"])
    rapport = cloture["rapport"]
    assert (
        rd.valider_rapport_decision_v2(rapport) == (True, None)
        and rapport["statut_contrat"] == "RETENU_PAR_DELEGATION"
    )
    assert rapport["sections"]["decision_recommandee"]["statut"] == "RENSEIGNEE"
    assert any(d["texte"].endswith("= 8400.00") for d in rapport["sections"]["donnees_utilisees"]["contenu"])
    assert "[inférence non validée]" in rapport["sections"]["diagnostic"]["contenu"][0]["texte"]
    assert rd.vers_contrat_historique(rapport)["recommandations"][0]["id"] == "DR1"
    evenements = _ajouter(evenements, cloture)
    assert sc.cloturer(evenements, session_id, recu_a=T) is None and sc.valider_chaine(evenements) == (True, "")
    with pytest.raises(ValueError, match="REJ-TOUR-TRANCHE"):
        sc.deposer(
            evenements, session_id, "liaison_finance", SORTIE_FINANCE, reservation_id="res-9", tokens_reels=1, recu_a=T
        )


def test_rejeu_public_normalise_legacy_proposable_sans_modifier_la_cloture(monkeypatch):
    evenements, session_id = _ouvrir()
    evenements = _tous_deposes(evenements, session_id)
    cloture = sc.cloturer(evenements, session_id, recu_a=T)
    evenements = _ajouter(evenements, cloture)

    # Simule une clôture antérieure au changement de vocabulaire, avec chaîne intacte.
    _rendre_cloture_legacy_proposable(cloture)
    verdict_id_source = cloture["gouvernance"]["verdict_id"]
    cloture_legacy = copy.deepcopy(cloture)
    assert sc.valider_chaine(evenements) == (True, "")

    monkeypatch.setattr(oc, "exiger_admin_strict", lambda: None)
    outils = oc.construire_outils(budget_sortie=10000, captures_cible=[], sessions_cible=evenements)
    outil = next(o for o in outils if o.nom == "m9_cloturer_conseil")
    reponse = outil.fonction(session_id, T)

    assert reponse["rejoue"] is True
    assert reponse["gouvernance"]["actions"][0]["verdict"] == "CLASSEMENT_HISTORIQUE_NON_VERIFIE"
    assert reponse["gouvernance"]["actions_a_classement_non_verifie"] == 1
    assert reponse["gouvernance"]["projection_type"] == "opsys.m9.gouvernance_projection/v1"
    assert reponse["gouvernance"]["verdict_id_source"] == verdict_id_source
    assert reponse["gouvernance"]["verdict_id"] == cj.empreinte_verdict(reponse["gouvernance"])
    assert reponse["gouvernance"]["verdict_id"] != reponse["gouvernance"]["verdict_id_source"]
    assert cloture == cloture_legacy, "la projection publique ne réécrit pas l'événement historique"
    assert sc.valider_chaine(evenements) == (True, "")


def test_rejeu_public_conserve_le_verdict_id_actuel(monkeypatch):
    evenements, session_id = _ouvrir()
    evenements = _tous_deposes(evenements, session_id)
    cloture = sc.cloturer(evenements, session_id, recu_a=T)
    evenements = _ajouter(evenements, cloture)
    cloture_avant = copy.deepcopy(cloture)

    monkeypatch.setattr(oc, "exiger_admin_strict", lambda: None)
    outils = oc.construire_outils(budget_sortie=10000, captures_cible=[], sessions_cible=evenements)
    outil = next(o for o in outils if o.nom == "m9_cloturer_conseil")
    reponse = outil.fonction(session_id, T)

    assert reponse["rejoue"] is True
    assert reponse["gouvernance"] == cloture["gouvernance"]
    assert "verdict_id_source" not in reponse["gouvernance"]
    assert "projection_type" not in reponse["gouvernance"]
    assert reponse["gouvernance"]["verdict_id"] == cj.empreinte_verdict(reponse["gouvernance"])
    assert cloture == cloture_avant
    assert sc.valider_chaine(evenements) == (True, "")


def test_reponses_publiques_expliquent_false_et_ne_valident_ni_n_autorisent_une_action(monkeypatch):
    evenements, session_id = _ouvrir()
    sortie_pdg = SORTIE_PDG | {
        "recommandation": {
            "decision": "Augmenter la dépense publicitaire de la campagne fictive",
            "refs": ["A1", "H1"],
            "actions": [
                {
                    "id": "a_pub",
                    "type": "information",
                    "description": "augmenter la dépense publicitaire de la campagne fictive cmp-1",
                }
            ],
        }
    }
    evenements = _tous_deposes(evenements, session_id, sortie_pdg=sortie_pdg)
    cloture = sc.cloturer(evenements, session_id, recu_a=T)
    evenements = _ajouter(evenements, cloture)
    chaine_avant = copy.deepcopy(evenements)

    monkeypatch.setattr(oc, "exiger_admin_strict", lambda: None)
    outils = oc.construire_outils(budget_sortie=5900, captures_cible=[], sessions_cible=evenements)
    cloturer = next(o for o in outils if o.nom == "m9_cloturer_conseil")
    reponse = cloturer.fonction(session_id, T)
    assert len(json.dumps(reponse, ensure_ascii=False)) <= 5900
    message = reponse["avertissements"][0]["message"]

    assert reponse["rejoue"] is True
    assert reponse["gouvernance"]["decision_majeure"] is False
    assert reponse["gouvernance"]["actions_a_classement_non_verifie"] == 1
    assert reponse["gouvernance"]["actions"][0]["verdict"] == "CLASSEMENT_NON_VERIFIE"
    assert all(action["effet_autorise"] is False for action in reponse["gouvernance"]["actions"])
    assert reponse["cloture"]["autorite_d_effet"] is False
    assert "false ne garantit pas l'absence d'une action sensible" in message
    assert "ni validation humaine ni autorisation d'effet" in message

    lire_conseil = next(o for o in outils if o.nom == "m9_lire_conseil")
    projection = lire_conseil.fonction(session_id)
    assert len(json.dumps(projection, ensure_ascii=False)) <= 5900
    assert (
        "false ne garantit pas l'absence d'une action sensible"
        in projection["cloture"]["avertissements"][0]["message"]
    )

    lire_rapport = next(o for o in outils if o.nom == "m9_lire_rapport_conseil")
    page = lire_rapport.fonction(session_id)
    assert len(json.dumps(page, ensure_ascii=False)) <= 5900
    assert "false ne garantit pas l'absence d'une action sensible" in page["avertissements"][0]["message"]
    assert any(a["code"] == "CLASSEMENT_NON_VERIFIE" and a["actions"] == 1 for a in page["avertissements"])
    assert page["sha256"] == cs.empreinte(cloture["rapport"])
    assert page["contenu_json"] == cs.canonique(cloture["rapport"])

    assert evenements == chaine_avant
    assert sc.valider_chaine(evenements) == (True, "")
    assert cloture["autorite_d_effet"] is False
    assert all(action["effet_autorise"] is False for action in cloture["gouvernance"]["actions"])


def test_public_abstention_sans_decision_majeure_n_emet_pas_son_avertissement(monkeypatch):
    evenements, session_id = _ouvrir()
    for role, sortie in (("liaison_finance", SORTIE_FINANCE), ("contraintes_inventaire", SORTIE_INVENTAIRE)):
        evenements = _ajouter(
            evenements,
            sc.deposer(evenements, session_id, role, sortie, reservation_id=f"r-{role}", tokens_reels=5, recu_a=T),
        )
    evenements = _ajouter(
        evenements, sc.abandonner(evenements, session_id, "conseiller_pdg", "runtime indisponible", recu_a=T)
    )
    cloture = sc.cloturer(evenements, session_id, recu_a=T)
    evenements = _ajouter(evenements, cloture)
    chaine_avant = copy.deepcopy(evenements)
    assert cloture["issue"] == "ABSTENTION" and cloture["gouvernance"] is None

    monkeypatch.setattr(oc, "exiger_admin_strict", lambda: None)
    outils = {o.nom: o for o in oc.construire_outils(budget_sortie=5900, captures_cible=[], sessions_cible=evenements)}

    reponse = outils["m9_cloturer_conseil"].fonction(session_id, T)
    assert reponse["rejoue"] is True
    assert reponse["gouvernance"] is None
    assert reponse["avertissements"] == []
    assert reponse["cloture"]["avertissements"] == []
    assert "decision_majeure" not in reponse["cloture"]

    projection = outils["m9_lire_conseil"].fonction(session_id)
    assert projection["cloture"]["issue"] == "ABSTENTION"
    assert projection["cloture"]["avertissements"] == []
    page = outils["m9_lire_rapport_conseil"].fonction(session_id)
    assert page["actions_a_classement_non_verifie"] == 0
    assert page["avertissements"] == [AVERTISSEMENT_HYPOTHESES]
    assert page["sha256"] == cs.empreinte(cloture["rapport"])
    assert page["contenu_json"] == cs.canonique(cloture["rapport"])
    assert all(len(json.dumps(rep, ensure_ascii=False)) <= 5900 for rep in (reponse, projection, page))
    assert evenements == chaine_avant
    assert sc.valider_chaine(evenements) == (True, "")


def test_public_avertit_quand_decision_majeure_vaut_vrai_sans_autoriser_effet(monkeypatch):
    evenements, session_id = _ouvrir()
    sortie_pdg = SORTIE_PDG | {
        "recommandation": {
            "decision": "Proposer une dépense publicitaire fictive",
            "refs": ["A1", "H1"],
            "actions": [{"id": "a_pub", "type": "depense_reelle", "description": "dépense fictive"}],
        }
    }
    evenements = _tous_deposes(evenements, session_id, sortie_pdg=sortie_pdg)
    cloture = sc.cloturer(evenements, session_id, recu_a=T)
    evenements = _ajouter(evenements, cloture)
    chaine_avant = copy.deepcopy(evenements)

    monkeypatch.setattr(oc, "exiger_admin_strict", lambda: None)
    outils = {o.nom: o for o in oc.construire_outils(budget_sortie=5900, captures_cible=[], sessions_cible=evenements)}
    reponse = outils["m9_cloturer_conseil"].fonction(session_id, T)
    assert reponse["gouvernance"]["decision_majeure"] is True
    assert reponse["gouvernance"]["actions"][0]["verdict"] == "VALIDATION_HUMAINE_REQUISE"
    assert reponse["gouvernance"]["actions"][0]["effet_autorise"] is False
    assert reponse["cloture"]["autorite_d_effet"] is False
    assert reponse["avertissements"][0]["code"] == "PORTEE_DECISION_MAJEURE"
    assert "ni validation humaine ni autorisation d'effet" in reponse["avertissements"][0]["message"]

    projection = outils["m9_lire_conseil"].fonction(session_id)
    assert projection["cloture"]["avertissements"][0]["code"] == "PORTEE_DECISION_MAJEURE"
    page = outils["m9_lire_rapport_conseil"].fonction(session_id)
    assert page["avertissements"][0]["code"] == "PORTEE_DECISION_MAJEURE"
    assert all(len(json.dumps(rep, ensure_ascii=False)) <= 5900 for rep in (reponse, projection, page))
    assert evenements == chaine_avant
    assert sc.valider_chaine(evenements) == (True, "")


def test_public_rapport_mixte_garde_un_avertissement_exact_quand_decision_majeure_est_vraie(monkeypatch):
    evenements, session_id = _ouvrir()
    sortie_pdg = SORTIE_PDG | {
        "recommandation": {
            "decision": "Proposer une dépense fictive et un suivi interne",
            "refs": ["A1", "H1"],
            "actions": [
                {"id": "a_depense", "type": "depense_reelle", "description": "dépense fictive"},
                {"id": "a_suivi", "type": "information", "description": "suivi fictif non vérifié"},
            ],
        }
    }
    evenements = _tous_deposes(evenements, session_id, sortie_pdg=sortie_pdg)
    cloture = sc.cloturer(evenements, session_id, recu_a=T)
    evenements = _ajouter(evenements, cloture)
    chaine_avant = copy.deepcopy(evenements)
    assert cloture["gouvernance"]["decision_majeure"] is True
    assert cloture["gouvernance"]["actions_a_classement_non_verifie"] == 1

    monkeypatch.setattr(oc, "exiger_admin_strict", lambda: None)
    outils = {o.nom: o for o in oc.construire_outils(budget_sortie=5900, captures_cible=[], sessions_cible=evenements)}
    reponse = outils["m9_cloturer_conseil"].fonction(session_id, T)
    assert reponse["gouvernance"]["decision_majeure"] is True
    assert reponse["gouvernance"]["actions_a_classement_non_verifie"] == 1
    assert all(action["effet_autorise"] is False for action in reponse["gouvernance"]["actions"])

    page = outils["m9_lire_rapport_conseil"].fonction(session_id)
    assert [item["code"] for item in page["avertissements"]] == [
        "PORTEE_DECISION_MAJEURE",
        "CLASSEMENT_NON_VERIFIE",
        "HYPOTHESES_NON_VERIFIEES",
    ]
    assert page["avertissements"][2] == AVERTISSEMENT_HYPOTHESES
    message = page["avertissements"][1]["message"]
    assert "une valeur false de decision_majeure ne garantit pas" in message
    assert "decision_majeure=false" not in message
    assert page["sha256"] == cs.empreinte(cloture["rapport"])
    assert page["contenu_json"] == cs.canonique(cloture["rapport"])
    assert len(json.dumps(page, ensure_ascii=False)) <= 5900
    assert evenements == chaine_avant
    assert sc.valider_chaine(evenements) == (True, "")


def test_registre_mcp_conserve_description_et_schema_entree_des_outils_conseil():
    outils = oc.construire_outils(budget_sortie=5900, captures_cible=[], sessions_cible=[])
    capacites = SimpleNamespace(
        lister=lambda: list(outils),
        departements={"m09-strategic-intelligence": SimpleNamespace(code="M9")},
    )
    serveur = creer_serveur(capacites, garde=None, traceur=None)
    catalogue = asyncio.run(serveur._request_handlers["tools/list"].handler(None, None))
    outils_mcp = {outil.name: outil for outil in catalogue.tools}
    index = {outil.nom: outil for outil in outils}

    for nom in ("m9_cloturer_conseil", "m9_lire_conseil", "m9_lire_rapport_conseil"):
        assert nom in outils_mcp
        assert outils_mcp[nom].description == index[nom].description
        assert outils_mcp[nom].input_schema == index[nom].parametres
        assert getattr(outils_mcp[nom], "output_schema", None) is None
        assert "avertissement" not in outils_mcp[nom].description.lower()


def test_lecture_publique_avertit_sur_le_classement_legacy_sans_recrire_le_rapport(monkeypatch):
    evenements, session_id = _ouvrir()
    evenements = _tous_deposes(evenements, session_id)
    cloture = sc.cloturer(evenements, session_id, recu_a=T)
    evenements = _ajouter(evenements, cloture)

    # Simule une clôture historique valide : gouvernance et section de validation portent l'ancien libellé.
    _rendre_cloture_legacy_proposable(cloture)
    sections = copy.deepcopy(cloture["rapport"]["sections"])
    for action in sections["validation"].get("contenu", []):
        action["texte"] = action["texte"].replace("CLASSEMENT_NON_VERIFIE", "PROPOSABLE")
    cloture["rapport"] = rd.assembler(sections, version=cloture["rapport"]["version"])
    cloture["rapport_id"] = cloture["rapport"]["rapport_id"]
    cloture["hash_maillon"] = sc.empreinte({k: v for k, v in cloture.items() if k != "hash_maillon"})
    rapport_historique = copy.deepcopy(cloture["rapport"])
    assert rd.valider_rapport_decision_v2(rapport_historique) == (True, None)
    assert sc.valider_chaine(evenements) == (True, "")

    monkeypatch.setattr(oc, "exiger_admin_strict", lambda: None)
    outils = oc.construire_outils(budget_sortie=10000, captures_cible=[], sessions_cible=evenements)
    outil = next(o for o in outils if o.nom == "m9_lire_rapport_conseil")
    pages = []
    depart = 0
    while True:
        page = outil.fonction(session_id, depart)
        pages.append(page)
        depart = page["prochain_depart"]
        if depart is None:
            break

    contenu = "".join(page["contenu_json"] for page in pages)
    assert contenu == cs.canonique(rapport_historique)
    assert "PROPOSABLE" in contenu and "CLASSEMENT_HISTORIQUE_NON_VERIFIE" not in contenu
    for page in pages:
        assert page["actions_a_classement_non_verifie"] == 1
        assert page["avertissements"] == [
            {
                "code": "PORTEE_DECISION_MAJEURE",
                "message": (
                    "decision_majeure indique uniquement si un type d'action déclaré a été reconnu comme sensible ; "
                    "false ne garantit pas l'absence d'une action sensible. Ce booléen ne vaut ni validation humaine "
                    "ni autorisation d'effet."
                ),
            },
            {
                "code": "CLASSEMENT_NON_VERIFIE",
                "actions": 1,
                "message": (
                    "Un ou plusieurs types déclarés ne sont pas vérifiés ; une valeur false de decision_majeure "
                    "ne garantit pas l'absence d'une action sensible. Le rapport historique, son contenu paginé "
                    "et son empreinte sont restitués inchangés."
                ),
            },
            AVERTISSEMENT_HYPOTHESES,
        ]
        assert page["sha256"] == cs.empreinte(rapport_historique)
        assert page["rapport_id"] == rapport_historique["rapport_id"]
    assert cloture["rapport"] == rapport_historique, "le texte historique et son empreinte restent inchangés"
    assert sc.valider_chaine(evenements) == (True, "")


def test_lecture_publique_signale_portee_sans_action_a_classement_incertain(monkeypatch):
    evenements, session_id = _ouvrir()
    sortie_pdg = {
        **SORTIE_PDG,
        "recommandation": {**SORTIE_PDG["recommandation"], "actions": []},
    }
    evenements = _tous_deposes(evenements, session_id, sortie_pdg=sortie_pdg)
    cloture = sc.cloturer(evenements, session_id, recu_a=T)
    evenements = _ajouter(evenements, cloture)

    monkeypatch.setattr(oc, "exiger_admin_strict", lambda: None)
    outils = oc.construire_outils(budget_sortie=10000, captures_cible=[], sessions_cible=evenements)
    outil = next(o for o in outils if o.nom == "m9_lire_rapport_conseil")
    page = outil.fonction(session_id)

    assert page["actions_a_classement_non_verifie"] == 0
    assert page["avertissements"] == [
        {
            "code": "PORTEE_DECISION_MAJEURE",
            "message": (
                "decision_majeure indique uniquement si un type d'action déclaré a été reconnu comme sensible ; "
                "false ne garantit pas l'absence d'une action sensible. Ce booléen ne vaut ni validation humaine "
                "ni autorisation d'effet."
            ),
        },
        AVERTISSEMENT_HYPOTHESES,
    ]


def test_lecture_publique_signale_hypothese_declaree_sans_texte_ni_mutation(monkeypatch):
    evenements, session_id = _ouvrir()
    sortie_pdg = copy.deepcopy(SORTIE_PDG)
    sortie_pdg["affirmations"][1]["enonce"] = "il y a 0 plainte cette semaine"
    evenements = _tous_deposes(evenements, session_id, sortie_pdg=sortie_pdg)
    cloture = sc.cloturer(evenements, session_id, recu_a=T)
    evenements = _ajouter(evenements, cloture)
    chaine_avant = copy.deepcopy(evenements)
    rapport_avant = copy.deepcopy(cloture["rapport"])
    rapport_id_avant = cloture["rapport_id"]
    assert rd.valider_rapport_decision_v2(rapport_avant) == (True, None)

    monkeypatch.setattr(oc, "exiger_admin_strict", lambda: None)
    outil = next(
        o
        for o in oc.construire_outils(budget_sortie=5900, captures_cible=[], sessions_cible=evenements)
        if o.nom == "m9_lire_rapport_conseil"
    )
    page = outil.fonction(session_id, longueur=4000)
    avertissement = next(a for a in page["avertissements"] if a["code"] == "HYPOTHESES_NON_VERIFIEES")

    assert avertissement["statut"] == "HYPOTHESE_DECLAREE"
    assert avertissement["provenance"] == "tours_conseil"
    assert "ne sont pas vérifiées par une source" in avertissement["message"]
    assert "ne confirme ni ne réfute" in avertissement["message"]
    assert "il y a 0 plainte cette semaine" not in str(avertissement)
    assert "enonce" not in avertissement
    assert page["sha256"] == cs.empreinte(rapport_avant)
    assert page["rapport_id"] == rapport_id_avant
    assert page["contenu_json"] == cs.canonique(rapport_avant)
    assert len(json.dumps(page, ensure_ascii=False)) <= 5900
    assert evenements == chaine_avant
    assert sc.valider_chaine(evenements) == (True, "")


@pytest.mark.parametrize("suffixe", ["", "é 🧪"])
@pytest.mark.parametrize("longueur_demandee", [4000, 3900, 3800])
def test_lecture_publique_ajuste_page_au_budget_serialise_sans_perdre_contenu_ni_avertissement(
    monkeypatch, suffixe, longueur_demandee
):
    evenements, session_id = _ouvrir()
    sortie_pdg = copy.deepcopy(SORTIE_PDG)
    sortie_pdg["affirmations"][1]["enonce"] = "\\" * 400 + suffixe
    sortie_pdg["recommandation"]["actions"] = []
    evenements = _tous_deposes(evenements, session_id, sortie_pdg=sortie_pdg)
    cloture = sc.cloturer(evenements, session_id, recu_a=T)
    evenements = _ajouter(evenements, cloture)
    chaine_avant = copy.deepcopy(evenements)
    contenu_attendu = cs.canonique(cloture["rapport"])
    assert len(contenu_attendu) > 4000
    assert rd.valider_rapport_decision_v2(cloture["rapport"]) == (True, None)

    monkeypatch.setattr(oc, "exiger_admin_strict", lambda: None)
    outil = next(
        o
        for o in oc.construire_outils(budget_sortie=5900, captures_cible=[], sessions_cible=evenements)
        if o.nom == "m9_lire_rapport_conseil"
    )
    pages = []
    depart = 0
    while True:
        page = outil.fonction(session_id, depart, longueur_demandee)
        pages.append(page)
        assert page["depart"] == depart
        assert len(json.dumps(page, ensure_ascii=False, allow_nan=False)) <= 5900
        assert AVERTISSEMENT_HYPOTHESES in page["avertissements"]
        assert page["rapport_id"] == cloture["rapport_id"]
        assert page["sha256"] == cs.empreinte(cloture["rapport"])
        suivant = page["prochain_depart"]
        if suivant is None:
            assert depart + len(page["contenu_json"]) == len(contenu_attendu)
            break
        assert suivant == depart + len(page["contenu_json"])
        assert suivant > depart
        depart = suivant

    assert len(pages) > 1
    assert len(pages[0]["contenu_json"]) <= longueur_demandee
    if longueur_demandee in {4000, 3900}:
        assert len(pages[0]["contenu_json"]) < longueur_demandee
    assert "".join(page["contenu_json"] for page in pages) == contenu_attendu
    assert evenements == chaine_avant
    assert sc.valider_chaine(evenements) == (True, "")


def test_lecture_publique_n_emet_pas_avertissement_hypothese_sans_hypothese(monkeypatch):
    evenements, session_id = _ouvrir()
    brouillon_refuse = sc.deposer(
        evenements,
        session_id,
        "liaison_finance",
        {"affirmations": [{"id": "H0", "nature": "hypothese", "enonce": "hypothèse non admise", "extra": True}]},
        reservation_id="hypothese-refusee",
        tokens_reels=5,
        recu_a=T,
    )
    assert brouillon_refuse["issue"] == "REFUSE"
    evenements = _ajouter(evenements, brouillon_refuse)
    finance = {
        "affirmations": [{"id": "A1", "nature": "observation_source", "reference": CASH, "valeur": "8400.00"}]
    }
    pdg = {"affirmations": [{"id": "A1", "nature": "observation_source", "reference": STOCK, "valeur": "12"}]}
    for role, sortie in (
        ("liaison_finance", finance),
        ("contraintes_inventaire", SORTIE_INVENTAIRE),
        ("conseiller_pdg", pdg),
    ):
        evenements = _ajouter(
            evenements,
            sc.deposer(
                evenements,
                session_id,
                role,
                sortie,
                reservation_id=f"no-h-{role}",
                tokens_reels=10,
                recu_a=T,
            ),
        )
    cloture = sc.cloturer(evenements, session_id, recu_a=T)
    evenements = _ajouter(evenements, cloture)

    monkeypatch.setattr(oc, "exiger_admin_strict", lambda: None)
    outil = next(
        o
        for o in oc.construire_outils(budget_sortie=5900, captures_cible=[], sessions_cible=evenements)
        if o.nom == "m9_lire_rapport_conseil"
    )
    page = outil.fonction(session_id)
    assert "HYPOTHESES_NON_VERIFIEES" not in {a["code"] for a in page["avertissements"]}
    assert "DIVERGENCE_HYPOTHESES_TOURS_RAPPORT" not in {a["code"] for a in page["avertissements"]}


def test_classement_incertain_ne_copie_pas_la_description_vers_rapport_meme_sur_4000_caracteres():
    evenements, session_id = _ouvrir()
    description = "X" * 4000
    sortie_pdg = SORTIE_PDG | {
        "recommandation": {
            "decision": "Étudier une hausse du budget publicitaire",
            "refs": ["A1"],
            "actions": [{"id": "a_pub", "type": "information", "description": description}],
        }
    }
    evenements = _tous_deposes(evenements, session_id, sortie_pdg=sortie_pdg)
    cloture = sc.cloturer(evenements, session_id, recu_a=T)
    action = cloture["gouvernance"]["actions"][0]
    assert action["verdict"] == "CLASSEMENT_NON_VERIFIE"
    assert cloture["gouvernance"]["decision_majeure"] is False
    assert type(cloture["gouvernance"]["decision_majeure"]) is bool
    assert cloture["gouvernance"]["actions_a_classement_non_verifie"] == 1
    assert "description" not in action
    assert description not in str(cloture["gouvernance"])
    assert description not in str(cloture["rapport"])
    assert rd.valider_rapport_decision_v2(cloture["rapport"]) == (True, None)


def test_abstention_quand_le_conseiller_du_pdg_est_absent_et_cloture_exige_tous_les_tours():
    evenements, session_id = _ouvrir()
    with pytest.raises(ValueError, match="REJ-SESSION-EN-COURS"):
        sc.cloturer(evenements, session_id, recu_a=T)
    for role, sortie in (("liaison_finance", SORTIE_FINANCE), ("contraintes_inventaire", SORTIE_INVENTAIRE)):
        evenements = _ajouter(
            evenements,
            sc.deposer(evenements, session_id, role, sortie, reservation_id=f"r-{role}", tokens_reels=5, recu_a=T),
        )
    evenements = _ajouter(
        evenements, sc.abandonner(evenements, session_id, "conseiller_pdg", "runtime indisponible", recu_a=T)
    )
    assert sc.abandonner(evenements, session_id, "conseiller_pdg", "runtime indisponible", recu_a=T) is None  # rejeu
    cloture = sc.cloturer(evenements, session_id, recu_a=T)
    assert (
        cloture["issue"] == "ABSTENTION"
        and cloture["gouvernance"] is None
        and "conseiller du PDG" in cloture["raison_abstention"]
    )
    assert cloture["rapport"]["sections"]["decision_recommandee"]["statut"] == "NON_DISPONIBLE"
    assert rd.valider_rapport_decision_v2(cloture["rapport"]) == (True, None)


def test_critique_attend_les_specialistes_et_recoit_leurs_propositions_comme_donnees():
    evenements, session_id = _ouvrir(importance="majeure")
    assert "critique_decisions" in evenements[0]["tours"]
    with pytest.raises(ValueError, match="REJ-TOUR-PREMATURE"):
        sc.entree_tour(evenements, session_id, "critique_decisions")
    evenements = _tous_deposes(evenements, session_id)
    assert sc.etat(evenements, session_id)["critique_ouvert"] is True
    entree = sc.entree_tour(evenements, session_id, "critique_decisions")
    assert set(entree["donnees"]["propositions"]) == {"liaison_finance", "contraintes_inventaire", "conseiller_pdg"}
    assert entree["donnees"]["recommandation"]["decision"] == "Proposer un report d'une semaine"
    objection = {
        "affirmations": [{"id": "H1", "nature": "hypothese", "enonce": "le report coûte un client"}],
        "objections": [{"id": "O1", "texte": "le report n'est pas sourcé côté client", "refs": []}],
    }
    evenements = _ajouter(
        evenements,
        sc.deposer(
            evenements, session_id, "critique_decisions", objection, reservation_id="r-c", tokens_reels=50, recu_a=T
        ),
    )
    cloture = sc.cloturer(evenements, session_id, recu_a=T)
    assert cloture["issue"] == "RECOMMANDATION" and cloture["tokens_reels_total"] == 3050


def test_recommandation_sans_ancrage_ou_hors_sortie_refusee():
    evenements, session_id = _ouvrir()
    sans = SORTIE_PDG | {"recommandation": {"decision": "x", "actions": [], "refs": []}}
    depot = sc.deposer(evenements, session_id, "conseiller_pdg", sans, reservation_id="r", tokens_reels=1, recu_a=T)
    assert depot["issue"] == "REFUSE" and depot["code"] == "REJ-CONSEIL-RECOMMANDATION"
    inconnue = SORTIE_PDG | {"recommandation": {"decision": "x", "actions": [], "refs": ["ZZ"]}}
    depot = sc.deposer(evenements, session_id, "conseiller_pdg", inconnue, reservation_id="r", tokens_reels=1, recu_a=T)
    assert depot["code"] == "REJ-CONSEIL-RECOMMANDATION"
    mauvais_type = SORTIE_PDG | {
        "recommandation": {"decision": "x", "actions": [{"id": "a", "type": "x", "description": "d"}], "refs": ["A1"]}
    }
    assert (
        sc.deposer(
            evenements, session_id, "conseiller_pdg", mauvais_type, reservation_id="r", tokens_reels=1, recu_a=T
        )["issue"]
        == "ADMIS"
    )
    # Un type d'action inconnu est admis comme proposition mais REFUSÉ par la gouvernance, jamais autorisé.


def test_chaine_alteree_detectee():
    evenements, session_id = _ouvrir()
    evenements = _tous_deposes(evenements, session_id)
    altere = [dict(e) for e in evenements]
    altere[1]["tokens_reels"] = 1
    assert sc.valider_chaine(altere)[0] is False


# --- Sorties RÉELLES de modèles (conseil réel, ronde 1) : verbatim, données fictives ---------------------------------
# Deux modèles ont reçu l'entrée du tour telle que le runtime la donnait ALORS (consigne « format » seule, sans schéma
# exact). Leurs sorties, soignées sur le fond (manques nommés, rien d'inventé), ont été refusées par le code pour
# leur FORME : ce défaut de consigne a motivé le champ « schema ».
def _sortie_reelle(nom):
    import json
    from pathlib import Path

    return json.loads((Path(__file__).parent / "sorties_reelles" / nom).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "fichier, code",
    [
        ("ronde1-croissance_marketing.json", "REJ-CONSEIL-SORTIE"),
        ("ronde1-contraintes_inventaire.json", "REJ-CONSEIL-AFFIRMATION"),
    ],
)
def test_sorties_reelles_sans_schema_exact_sont_refusees_pour_leur_forme(fichier, code):
    with pytest.raises(ValueError, match=code):
        sc.conseil.admettre_proposition(_sortie_reelle(fichier), sources={})


def test_la_consigne_porte_le_schema_exact_que_le_code_admet():
    evenements, session_id = _ouvrir()
    schema = sc.entree_tour(evenements, session_id, "liaison_finance")["consigne"]["schema"]
    assert set(schema["affirmations"]) == set(sc.conseil.NATURES)
    assert "fait" not in schema["affirmations"] and "manque" not in schema["affirmations"]
    assert "recommandation" not in schema and "objections" not in schema
    assert "aucune autre clé" in schema["racine"]
    # Une sortie bâtie littéralement sur ce schéma, avec une citation exacte, est admise.
    adresse = next(iter(_dossier()["faits"]))
    sortie = {
        "affirmations": [
            {"id": "O1", "nature": "observation_source", "reference": adresse, "valeur": _dossier()["faits"][adresse]},
            {"id": "H1", "nature": "hypothese", "enonce": "la lecture m4.interventions est absente"},
            {"id": "I1", "nature": "inference", "enonce": "aucun achat sans lecture M6", "premisses": ["O1", "H1"]},
        ],
        "demandes": [],
    }
    assert sc.conseil.admettre_proposition(sortie, sources=_dossier()["faits"])["type"] == "PROPOSITION_ADMISE"


def test_schema_du_conseiller_du_pdg_et_du_critique_portent_leurs_extras():
    for role, extra in (("conseiller_pdg", "recommandation"), ("critique_decisions", "objections")):
        schema = sc._schema_sortie(role)
        assert extra in schema and extra in schema["racine"]
    assert "suivi_interne" in sc._schema_sortie("conseiller_pdg")["recommandation"]["actions"][0]["type"]


def test_la_borne_d_affirmations_de_la_consigne_est_celle_du_code():
    racine = sc._schema_sortie("liaison_finance")["racine"]
    assert f"1 à {sc.conseil.MAX_AFFIRMATIONS} éléments" in racine
    trop = [{"id": f"H{i}", "nature": "hypothese", "enonce": "x"} for i in range(sc.conseil.MAX_AFFIRMATIONS + 1)]
    with pytest.raises(ValueError, match="REJ-CONSEIL-SORTIE"):
        sc.conseil.admettre_proposition({"affirmations": trop}, sources={})


def test_ronde_2_reelle_forme_conforme_admise_et_excedent_d_affirmations_refuse():
    """Avec le schéma dans la consigne : l'inventaire (9 sorties citées exactes) est admis sans source à vérifier ici
    (la citation exacte est prouvée dans le test d'intégration), la croissance (35 affirmations) dépasse la borne."""
    croissance = _sortie_reelle("ronde2-croissance_marketing.json")
    assert len(croissance["affirmations"]) > sc.conseil.MAX_AFFIRMATIONS
    with pytest.raises(ValueError, match="REJ-CONSEIL-SORTIE"):
        sc.conseil.admettre_proposition(croissance, sources={})
    inventaire = _sortie_reelle("ronde2-contraintes_inventaire.json")
    assert {a["nature"] for a in inventaire["affirmations"]} <= set(sc.conseil.NATURES)
    assert set(inventaire) == {"affirmations", "demandes"}


@pytest.mark.parametrize("roles_conserves", [[], ["liaison_finance"]])
def test_rapport_historique_signale_hypotheses_sans_inventer_provenance_des_tours(monkeypatch, roles_conserves):
    evenements, session_id = _ouvrir()
    evenements = _tous_deposes(evenements, session_id)
    cloture = sc.cloturer(evenements, session_id, recu_a=T)
    rapport_historique = copy.deepcopy(cloture["rapport"])
    assert rd.valider_rapport_decision_v2(rapport_historique) == (True, None)
    assert len(rapport_historique["sections"]["hypotheses"]["contenu"]) == 2

    ouverture = copy.deepcopy(evenements[0])
    ouverture["tours"] = {role: ouverture["tours"][role] for role in roles_conserves}
    tours = [
        evenement
        for evenement in evenements[1:]
        if evenement["type"] == "TOUR" and evenement["role"] in roles_conserves and evenement["issue"] == "ADMIS"
    ]
    historique = _rechaîner_historique([ouverture, *tours, cloture])
    projection = sc.etat(historique, session_id)
    assert len(projection["tours"]) == len(roles_conserves)
    assert projection["cloture"]["rapport"] == rapport_historique
    assert sc.valider_chaine(historique) == (True, "")

    historique_avant = copy.deepcopy(historique)
    monkeypatch.setattr(oc, "exiger_admin_strict", lambda: None)
    outil = next(
        o
        for o in oc.construire_outils(budget_sortie=5900, captures_cible=[], sessions_cible=historique)
        if o.nom == "m9_lire_rapport_conseil"
    )
    page = outil.fonction(session_id)
    avertissements = [a for a in page["avertissements"] if a["code"] == "HYPOTHESES_NON_VERIFIEES"]

    assert avertissements == [AVERTISSEMENT_HYPOTHESES_PROVENANCE_INDETERMINEE]
    assert "tours_conseil" not in str(avertissements[0])
    assert "HYPOTHESE_DECLAREE" not in str(avertissements[0])
    assert all(
        hypothese["texte"] not in str(avertissements[0])
        for hypothese in rapport_historique["sections"]["hypotheses"]["contenu"]
    )
    assert page["contenu_json"] == cs.canonique(rapport_historique)
    assert page["rapport_id"] == rapport_historique["rapport_id"]
    assert page["sha256"] == cs.empreinte(rapport_historique)
    assert len(json.dumps(page, ensure_ascii=False, allow_nan=False)) <= 5900
    assert historique == historique_avant
    assert sc.valider_chaine(historique) == (True, "")


def test_rapport_sans_hypotheses_ne_requalifie_pas_les_tours_hypothese(monkeypatch):
    evenements_avec_hypotheses, session_id = _ouvrir()
    evenements_avec_hypotheses = _tous_deposes(evenements_avec_hypotheses, session_id)
    assert any(
        affirmation["nature"] == "hypothese"
        for tour in sc.etat(evenements_avec_hypotheses, session_id)["tours"]
        if tour["proposition"] is not None
        for affirmation in tour["proposition"]["affirmations"]
    )

    evenements_sans_hypotheses, session_id_sans_hypotheses = _ouvrir()
    assert session_id_sans_hypotheses == session_id
    finance = {
        "affirmations": [{"id": "A1", "nature": "observation_source", "reference": CASH, "valeur": "8400.00"}]
    }
    pdg = {"affirmations": [{"id": "A1", "nature": "observation_source", "reference": STOCK, "valeur": "12"}]}
    for role, sortie in (
        ("liaison_finance", finance),
        ("contraintes_inventaire", SORTIE_INVENTAIRE),
        ("conseiller_pdg", pdg),
    ):
        evenements_sans_hypotheses = _ajouter(
            evenements_sans_hypotheses,
            sc.deposer(
                evenements_sans_hypotheses,
                session_id,
                role,
                sortie,
                reservation_id=f"sans-h-{role}",
                tokens_reels=10,
                recu_a=T,
            ),
        )
    cloture = sc.cloturer(evenements_sans_hypotheses, session_id, recu_a=T)
    rapport_sans_hypotheses = cloture["rapport"]
    assert rd.valider_rapport_decision_v2(rapport_sans_hypotheses) == (True, None)
    assert rapport_sans_hypotheses["sections"]["hypotheses"]["statut"] == "NON_DISPONIBLE"
    sections = copy.deepcopy(rapport_sans_hypotheses["sections"])
    sections["question"]["contenu"]["texte"] = "Q" * 3000
    rapport_sans_hypotheses = rd.assembler(sections, version=rapport_sans_hypotheses["version"])
    assert rd.valider_rapport_decision_v2(rapport_sans_hypotheses) == (True, None)
    assert len(cs.canonique(rapport_sans_hypotheses)) > 4000
    cloture["rapport"] = rapport_sans_hypotheses
    cloture["rapport_id"] = rapport_sans_hypotheses["rapport_id"]

    tours_avec_hypotheses = [e for e in evenements_avec_hypotheses if e["type"] == "TOUR"]
    historique = _rechaîner_historique([evenements_avec_hypotheses[0], *tours_avec_hypotheses, cloture])
    projection = sc.etat(historique, session_id)
    assert any(
        affirmation["nature"] == "hypothese"
        for tour in projection["tours"]
        if tour["proposition"] is not None
        for affirmation in tour["proposition"]["affirmations"]
    )
    assert projection["cloture"]["rapport"]["sections"]["hypotheses"]["statut"] == "NON_DISPONIBLE"
    assert sc.valider_chaine(historique) == (True, "")

    historique_avant = copy.deepcopy(historique)
    monkeypatch.setattr(oc, "exiger_admin_strict", lambda: None)
    outil = next(
        o
        for o in oc.construire_outils(budget_sortie=5900, captures_cible=[], sessions_cible=historique)
        if o.nom == "m9_lire_rapport_conseil"
    )
    contenu_attendu = cs.canonique(rapport_sans_hypotheses)
    pages = []
    depart = 0
    while True:
        page = outil.fonction(session_id, depart)
        pages.append(page)
        assert page["depart"] == depart
        assert len(json.dumps(page, ensure_ascii=False, allow_nan=False)) <= 5900
        assert AVERTISSEMENT_DIVERGENCE_HYPOTHESES in page["avertissements"]
        assert not any(a["code"] == "HYPOTHESES_NON_VERIFIEES" for a in page["avertissements"])
        assert page["rapport_id"] == rapport_sans_hypotheses["rapport_id"]
        assert page["sha256"] == cs.empreinte(rapport_sans_hypotheses)
        suivant = page["prochain_depart"]
        if suivant is None:
            assert depart + len(page["contenu_json"]) == len(contenu_attendu)
            break
        assert suivant == depart + len(page["contenu_json"]) > depart
        depart = suivant
    assert len(pages) > 1
    assert "le client accepte un report d'une semaine" not in str(pages[0]["avertissements"])
    assert (
        "ne permet pas d’établir que ces éléments figurent dans le rapport"
        in pages[0]["avertissements"][-1]["message"]
    )
    assert "HYPOTHESE_DECLAREE" not in pages[0]["avertissements"][-1]["message"]
    assert "DIVERGENCE_HYPOTHESES_TOURS_RAPPORT" in pages[0]["avertissements"][-1]["code"]
    assert "".join(page["contenu_json"] for page in pages) == contenu_attendu
    assert historique == historique_avant
    assert sc.valider_chaine(historique) == (True, "")


def test_rapport_legacy_quinze_cles_sans_section_signale_hypotheses_sans_origine(monkeypatch):
    evenements, session_id = _ouvrir()
    evenements = _tous_deposes(evenements, session_id)
    cloture = sc.cloturer(evenements, session_id, recu_a=T)
    rapport_legacy = rd.vers_contrat_historique(cloture["rapport"])
    assert set(rapport_legacy) == set(rd.contrats.CHAMPS_RAPPORT_STRATEGIQUE)
    assert len(rapport_legacy["hypotheses"]) == 2
    assert rd.rapport_strategique.valider_rapport_strategique(rapport_legacy) == (True, None)

    ouverture = copy.deepcopy(evenements[0])
    ouverture["tours"] = {}
    cloture["rapport"] = rapport_legacy
    historique = _rechaîner_historique([ouverture, cloture])
    assert sc.valider_chaine(historique) == (True, "")

    historique_avant = copy.deepcopy(historique)
    monkeypatch.setattr(oc, "exiger_admin_strict", lambda: None)
    outil = next(
        o
        for o in oc.construire_outils(budget_sortie=5900, captures_cible=[], sessions_cible=historique)
        if o.nom == "m9_lire_rapport_conseil"
    )
    page = outil.fonction(session_id)
    assert [a for a in page["avertissements"] if a["code"] == "HYPOTHESES_NON_VERIFIEES"] == [
        AVERTISSEMENT_HYPOTHESES_PROVENANCE_INDETERMINEE
    ]
    assert page["contenu_json"] == cs.canonique(rapport_legacy)
    assert page["sha256"] == cs.empreinte(rapport_legacy)
    assert len(json.dumps(page, ensure_ascii=False, allow_nan=False)) <= 5900
    assert historique == historique_avant
    assert sc.valider_chaine(historique) == (True, "")
