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
from m9_strategic_intelligence import orchestrateur
from m9_strategic_intelligence import outils_actions as oa
from m9_strategic_intelligence import outils_conseil as oc
from m9_strategic_intelligence import outils_memoire as om
from m9_strategic_intelligence import rapport_decision_v2 as rd
from m9_strategic_intelligence import sessions_conseil as sc

from opsys.idempotence import empreinte_arguments
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
    assert page["avertissements"][:-1] == [AVERTISSEMENT_HYPOTHESES]
    assert page["avertissements"][-1]["code"] == "VALIDITE_RAPPORT_ARCHIVE"
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
        "VALIDITE_RAPPORT_ARCHIVE",
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
        assert page["avertissements"][:-1] == [
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
        assert page["avertissements"][-1]["code"] == "VALIDITE_RAPPORT_ARCHIVE"
        assert page["avertissements"][-1]["statut"] == "RAPPORT_V2_SCHEMA_ET_ID_CONCORDANTS"
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
    assert page["avertissements"][:-1] == [
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
    assert page["avertissements"][-1]["code"] == "VALIDITE_RAPPORT_ARCHIVE"


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
    divergence = next(
        a for a in pages[0]["avertissements"] if a["code"] == "DIVERGENCE_HYPOTHESES_TOURS_RAPPORT"
    )
    assert "ne permet pas d’établir que ces éléments figurent dans le rapport" in divergence["message"]
    assert "HYPOTHESE_DECLAREE" not in divergence["message"]
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


def _historique(mode):
    evenements, session_id = _ouvrir()
    evenements = _tous_deposes(evenements, session_id)
    cloture = sc.cloturer(evenements, session_id, recu_a=T)
    evenements = [*evenements, cloture]

    if mode == "rapport_v2_invalide":
        rapport = copy.deepcopy(cloture["rapport"])
        rapport["sections"]["question"]["statut"] = "SCHEMA_CORROMPU"
        rapport["rapport_id"] = rd.identifiant(rapport)
        cloture["rapport"] = rapport
        cloture["rapport_id"] = rapport["rapport_id"]
    elif mode == "id_cloture_contradictoire":
        cloture["rapport_id"] = "f" * 64
    elif mode == "projection_legacy_15_cles":
        cloture["rapport"] = rd.vers_contrat_historique(cloture["rapport"])
    else:
        raise AssertionError("mode de fixture inattendu")

    return _rechaîner_historique(evenements), session_id


def _outil_preparer(evenements, monkeypatch):
    monkeypatch.setattr(om, "exiger_admin_strict", lambda: None)
    outils = om.construire_outils(
        budget_sortie=20_000, sessions_cible=evenements, captures_cible=[], actions_cible=[]
    )
    return next(o.fonction for o in outils if o.nom == "m9_preparer_memoire_decision")


@pytest.mark.parametrize(
    "mode",
    ["rapport_v2_invalide", "id_cloture_contradictoire", "projection_legacy_15_cles"],
)
def test_preparation_memoire_refuse_rapport_non_verifiable_sans_bloquer_lecture_brute(mode, monkeypatch):
    evenements, session_id = _historique(mode)
    avant = copy.deepcopy(evenements)
    cloture = evenements[-1]
    valide, _ = rd.valider_rapport_decision_v2(cloture["rapport"])

    if mode == "rapport_v2_invalide":
        assert valide is False
        assert cloture["rapport_id"] == cloture["rapport"]["rapport_id"]
    elif mode == "id_cloture_contradictoire":
        assert valide is True
        assert cloture["rapport_id"] != cloture["rapport"]["rapport_id"]
    else:
        assert valide is False
        assert len(cloture["rapport"]) == 15

    with pytest.raises(
        ValueError,
        match=r"^REJ-MEMOIRE-RAPPORT-INVALIDE : rapport de clôture non vérifiable$",
    ):
        _outil_preparer(evenements, monkeypatch)(session_id, "proposee", T)

    # Le garde ne réécrit ni ne cache l'historique; la lecture brute reste disponible séparément.
    monkeypatch.setattr(oc, "exiger_admin_strict", lambda: None)
    outils_lecture = oc.construire_outils(
        budget_sortie=20_000, captures_cible=[], sessions_cible=evenements
    )
    lire = next(o.fonction for o in outils_lecture if o.nom == "m9_lire_rapport_conseil")
    page = lire(session_id)
    assert page["accepte"] is True
    assert page["rapport_id"] == cloture["rapport_id"]
    assert page["sha256"] == cs.empreinte(cloture["rapport"])
    assert evenements == avant
    assert sc.valider_chaine(evenements) == (True, "")


def test_preparation_memoire_valide_cite_exactement_le_rapport_v2(monkeypatch):
    evenements, session_id = _ouvrir()
    evenements = _tous_deposes(evenements, session_id)
    cloture = sc.cloturer(evenements, session_id, recu_a=T)
    evenements = [*evenements, cloture]
    avant = copy.deepcopy(evenements)

    assert rd.valider_rapport_decision_v2(cloture["rapport"]) == (True, None)
    preparer = _outil_preparer(evenements, monkeypatch)
    resultat = preparer(session_id, "proposee", T, options_ecartees="aucune (fictif)")

    assert resultat["accepte"] is True
    assert resultat["ecrit"] is False
    assert resultat["rapport_id"] == cloture["rapport_id"] == cloture["rapport"]["rapport_id"]
    assert resultat["a_proposer"]["departement"] == "m10-memoire"
    assert resultat["a_proposer"]["outil"] == "m10_journaliser_decision"
    assert resultat["a_proposer"]["sources"] == [f"conseil:{cloture['rapport_id']}"]
    decision = resultat["a_proposer"]["arguments"]["decision"]
    assert decision["decision_id"] == f"m9:{session_id}"
    assert f"rapport {cloture['rapport_id']}" in decision["raison"]
    assert evenements == avant
def _outil_lecture_rapport(monkeypatch, historique, *, budget=5900):
    monkeypatch.setattr(oc, "exiger_admin_strict", lambda: None)
    return next(
        outil
        for outil in oc.construire_outils(budget_sortie=budget, captures_cible=[], sessions_cible=historique)
        if outil.nom == "m9_lire_rapport_conseil"
    )


def _historique_cloture_fictif():
    evenements, session_id = _ouvrir()
    evenements = _tous_deposes(evenements, session_id)
    cloture = sc.cloturer(evenements, session_id, recu_a=T)
    return _rechaîner_historique([*evenements, cloture]), session_id


def test_lecture_publique_signale_v2_valide_sans_affirmer_authenticite(monkeypatch):
    historique, session_id = _historique_cloture_fictif()
    rapport = copy.deepcopy(historique[-1]["rapport"])
    historique_avant = copy.deepcopy(historique)

    page = _outil_lecture_rapport(monkeypatch, historique).fonction(session_id)

    assert page["validite_rapport"] == {
        "statut": "RAPPORT_V2_SCHEMA_ET_ID_CONCORDANTS",
        "format": rd.SCHEMA,
        "contrat_v2": "VALIDE",
        "id_cloture": "CONCORDANT",
        "code_validation": None,
        "authenticite": "NON_ETABLIE",
    }
    assert page["contenu_json"] == cs.canonique(rapport)
    assert page["sha256"] == cs.empreinte(rapport)
    assert any(a["code"] == "VALIDITE_RAPPORT_ARCHIVE" for a in page["avertissements"])
    assert len(json.dumps(page, ensure_ascii=False, allow_nan=False)) <= 5900
    assert historique == historique_avant and sc.valider_chaine(historique) == (True, "")


def test_lecture_publique_restitue_v2_invalide_comme_brut_non_fiable(monkeypatch):
    historique, session_id = _historique_cloture_fictif()
    cloture = historique[-1]
    rapport = copy.deepcopy(cloture["rapport"])
    rapport["sections"]["question"]["statut"] = "SCHEMA_CORROMPU"
    rapport["rapport_id"] = rd.identifiant(rapport)
    cloture["rapport"] = rapport
    cloture["rapport_id"] = rapport["rapport_id"]
    historique = _rechaîner_historique(historique)
    assert sc.valider_chaine(historique) == (True, "")
    valide, code = rd.valider_rapport_decision_v2(rapport)
    assert valide is False and code == "REJ-RAPPORT-V2-SECTION"
    historique_avant = copy.deepcopy(historique)

    page = _outil_lecture_rapport(monkeypatch, historique).fonction(session_id)

    assert page["accepte"] is True
    assert page["validite_rapport"]["statut"] == "RAPPORT_V2_NON_FIABLE_VALIDATION_REFUSEE"
    assert page["validite_rapport"]["contrat_v2"] == "INVALIDE"
    assert page["validite_rapport"]["code_validation"] == code
    assert page["validite_rapport"]["authenticite"] == "NON_ETABLIE"
    assert page["contenu_json"] == cs.canonique(rapport) and "SCHEMA_CORROMPU" in page["contenu_json"]
    assert page["sha256"] == cs.empreinte(rapport)
    assert any(a["code"] == "VALIDITE_RAPPORT_ARCHIVE" for a in page["avertissements"])
    assert len(json.dumps(page, ensure_ascii=False, allow_nan=False)) <= 5900
    assert historique == historique_avant and sc.valider_chaine(historique) == (True, "")


def test_lecture_publique_signale_id_cloture_divergent_sur_chaque_page(monkeypatch):
    historique, session_id = _historique_cloture_fictif()
    rapport = copy.deepcopy(historique[-1]["rapport"])
    historique[-1]["rapport_id"] = "f" * 64
    historique = _rechaîner_historique(historique)
    historique_avant = copy.deepcopy(historique)
    assert rd.valider_rapport_decision_v2(rapport) == (True, None)
    assert sc.valider_chaine(historique) == (True, "")
    outil = _outil_lecture_rapport(monkeypatch, historique)

    for depart in (0, 100):
        page = outil.fonction(session_id, depart)
        assert page["accepte"] is True
        assert page["rapport_id"] == "f" * 64
        assert page["validite_rapport"]["statut"] == "RAPPORT_V2_NON_FIABLE_ID_CLOTURE_NON_CONCORDANT"
        assert page["validite_rapport"]["id_cloture"] == "DIVERGENT"
        assert page["contenu_json"] == cs.canonique(rapport)[depart : depart + len(page["contenu_json"])]
        assert page["sha256"] == cs.empreinte(rapport)
        assert any(a["code"] == "VALIDITE_RAPPORT_ARCHIVE" for a in page["avertissements"])
        assert len(json.dumps(page, ensure_ascii=False, allow_nan=False)) <= 5900

    assert historique == historique_avant and sc.valider_chaine(historique) == (True, "")


def test_lecture_publique_legacy_15_cles_est_structure_seule_et_non_convertie(monkeypatch):
    historique, session_id = _historique_cloture_fictif()
    rapport_legacy = {cle: None for cle in rd.contrats.CHAMPS_RAPPORT_STRATEGIQUE}
    historique[-1]["rapport"] = rapport_legacy
    # Un jeu de clés exactes ne prouve pas le contenu; l'ID v2 de la clôture n'est pas attribué au legacy.
    historique = _rechaîner_historique(historique)
    assert rd.rapport_strategique.valider_rapport_strategique(rapport_legacy) == (True, None)
    historique_avant = copy.deepcopy(historique)

    page = _outil_lecture_rapport(monkeypatch, historique).fonction(session_id)

    assert page["validite_rapport"] == {
        "statut": "FORMAT_LEGACY_15_CLES_STRUCTURE_SEULEMENT",
        "format": "historique_15_cles",
        "contrat_v2": "NON_APPLICABLE",
        "id_cloture": "NON_VERIFIABLE",
        "code_validation": "INFO-RAPPORT-LEGACY-STRUCTURE-SEULEMENT",
        "authenticite": "NON_ETABLIE",
    }
    assert page["contenu_json"] == cs.canonique(rapport_legacy)
    assert page["sha256"] == cs.empreinte(rapport_legacy)
    assert len(json.dumps(page, ensure_ascii=False, allow_nan=False)) <= 5900
    assert historique == historique_avant and sc.valider_chaine(historique) == (True, "")


def test_lecture_publique_id_v2_absent_est_signale_divergent_et_conserve_le_brut(monkeypatch):
    historique, session_id = _historique_cloture_fictif()
    rapport = copy.deepcopy(historique[-1]["rapport"])
    del historique[-1]["rapport_id"]
    historique = _rechaîner_historique(historique)
    historique_avant = copy.deepcopy(historique)

    page = _outil_lecture_rapport(monkeypatch, historique).fonction(session_id)

    assert page["rapport_id"] is None
    assert page["validite_rapport"]["statut"] == "RAPPORT_V2_NON_FIABLE_ID_CLOTURE_NON_CONCORDANT"
    assert page["validite_rapport"]["id_cloture"] == "NON_VERIFIABLE"
    assert page["contenu_json"] == cs.canonique(rapport)
    assert page["sha256"] == cs.empreinte(rapport)
    assert historique == historique_avant and sc.valider_chaine(historique) == (True, "")


@pytest.mark.parametrize("mode", ["deux_absents", "types_anormaux"])
def test_lecture_publique_ne_declare_pas_concordants_deux_ids_absents_ou_mal_formes(monkeypatch, mode):
    historique, session_id = _historique_cloture_fictif()
    cloture = historique[-1]
    rapport = copy.deepcopy(cloture["rapport"])
    if mode == "deux_absents":
        rapport.pop("rapport_id")
        cloture.pop("rapport_id")
    else:
        rapport["rapport_id"] = 42
        cloture["rapport_id"] = 42
    cloture["rapport"] = rapport
    historique = _rechaîner_historique(historique)
    assert sc.valider_chaine(historique) == (True, "")
    assert rd.valider_rapport_decision_v2(rapport)[0] is False
    historique_avant = copy.deepcopy(historique)

    page = _outil_lecture_rapport(monkeypatch, historique).fonction(session_id)

    assert page["validite_rapport"]["statut"] == "RAPPORT_V2_NON_FIABLE_VALIDATION_REFUSEE"
    assert page["validite_rapport"]["id_cloture"] == "NON_VERIFIABLE"
    assert page["validite_rapport"]["id_cloture"] != "CONCORDANT"
    assert page["contenu_json"] == cs.canonique(rapport)
    assert page["sha256"] == cs.empreinte(rapport)
    assert historique == historique_avant and sc.valider_chaine(historique) == (True, "")


def test_lecture_publique_format_inconnu_restitue_le_brut_sans_validation(monkeypatch):
    historique, session_id = _historique_cloture_fictif()
    rapport_inconnu = {"schema": "opsys.m9.rapport_decision/v999", "contenu_fictif": [1, 2]}
    historique[-1]["rapport"] = rapport_inconnu
    historique = _rechaîner_historique(historique)
    historique_avant = copy.deepcopy(historique)

    page = _outil_lecture_rapport(monkeypatch, historique).fonction(session_id)

    assert page["validite_rapport"]["statut"] == "FORMAT_INCONNU_NON_VALIDE"
    assert page["validite_rapport"]["contrat_v2"] == "NON_RECONNU"
    assert page["validite_rapport"]["authenticite"] == "NON_ETABLIE"
    assert page["contenu_json"] == cs.canonique(rapport_inconnu)
    assert page["sha256"] == cs.empreinte(rapport_inconnu)
    assert any(a["code"] == "VALIDITE_RAPPORT_ARCHIVE" for a in page["avertissements"])
    assert len(json.dumps(page, ensure_ascii=False, allow_nan=False)) <= 5900
    assert historique == historique_avant and sc.valider_chaine(historique) == (True, "")


def test_validite_et_avertissements_persistent_sur_pagination_sans_perte(monkeypatch):
    historique, session_id = _historique_cloture_fictif()
    cloture = historique[-1]
    sections = copy.deepcopy(cloture["rapport"]["sections"])
    sections["question"]["contenu"]["texte"] = "Q" * 3000
    rapport = rd.assembler(sections, version=cloture["rapport"]["version"])
    cloture["rapport"] = rapport
    cloture["rapport_id"] = rapport["rapport_id"]
    historique = _rechaîner_historique(historique)
    contenu = cs.canonique(rapport)
    assert len(contenu) > 4000 and rd.valider_rapport_decision_v2(rapport) == (True, None)
    historique_avant = copy.deepcopy(historique)
    outil = _outil_lecture_rapport(monkeypatch, historique)
    pages = []
    depart = 0

    while True:
        page = outil.fonction(session_id, depart)
        pages.append(page)
        assert page["validite_rapport"]["statut"] == "RAPPORT_V2_SCHEMA_ET_ID_CONCORDANTS"
        assert any(a["code"] == "VALIDITE_RAPPORT_ARCHIVE" for a in page["avertissements"])
        assert page["sha256"] == cs.empreinte(rapport)
        assert len(json.dumps(page, ensure_ascii=False, allow_nan=False)) <= 5900
        suivant = page["prochain_depart"]
        if suivant is None:
            break
        assert suivant == depart + len(page["contenu_json"]) > depart
        depart = suivant

    assert len(pages) > 1 and "".join(page["contenu_json"] for page in pages) == contenu
    assert historique == historique_avant and sc.valider_chaine(historique) == (True, "")


def test_borne_publique_mesure_les_caracteres_json_pas_les_octets_utf8(monkeypatch):
    historique, session_id = _historique_cloture_fictif()
    cloture = historique[-1]
    sections = copy.deepcopy(cloture["rapport"]["sections"])
    sections["question"]["contenu"]["texte"] = "中" * 2100
    rapport = rd.assembler(sections, version=cloture["rapport"]["version"])
    cloture["rapport"] = rapport
    cloture["rapport_id"] = rapport["rapport_id"]
    historique = _rechaîner_historique(historique)
    historique_avant = copy.deepcopy(historique)

    outil = _outil_lecture_rapport(monkeypatch, historique, budget=5900)
    pages = []
    depart = 0
    while True:
        page = outil.fonction(session_id, depart)
        pages.append(page)
        json_externe = json.dumps(page, ensure_ascii=False, allow_nan=False)
        assert len(json_externe) <= 5900
        assert page["sha256"] == cs.empreinte(rapport)
        assert page["validite_rapport"]["statut"] == "RAPPORT_V2_SCHEMA_ET_ID_CONCORDANTS"
        suivant = page["prochain_depart"]
        if suivant is None:
            break
        assert suivant == depart + len(page["contenu_json"]) > depart
        depart = suivant

    assert len(json.dumps(pages[0], ensure_ascii=False, allow_nan=False).encode("utf-8")) > 5900
    assert "".join(page["contenu_json"] for page in pages) == cs.canonique(rapport)
    assert historique == historique_avant and sc.valider_chaine(historique) == (True, "")

def _outils_proposition_action(monkeypatch, sessions, *, actions=None, budget_sortie=20_000):
    class RegistreActions(list):
        def append(self, maillon, *, rang_attendu):
            assert rang_attendu == len(self)
            super().append(maillon)

    monkeypatch.setattr(oa, "exiger_admin_strict", lambda: None)
    actions = RegistreActions() if actions is None else actions
    appels = []

    def port(operation, **valeurs):
        assert operation == "proposer"
        appels.append(valeurs)
        return {
            "ok": True,
            "demande_id": f"{len(appels):012x}",
            "niveau": "N3",
            "arguments_sha256": empreinte_arguments(valeurs["arguments"]),
        }

    outils = oa.construire_outils(
        budget_sortie=budget_sortie,
        proposeur=port,
        actions_cible=actions,
        sessions_cible=sessions,
    )
    fonctions = {outil.nom: outil.fonction for outil in outils}
    return fonctions, appels, actions


def _proposition_m10(*, source, decision_id="DECISION-FICTIVE-01", raison="motif fictif sans lien implicite"):
    return {
        "departement": "m10-memoire",
        "outil": "m10_journaliser_decision",
        "arguments": {
            "decision": {
                "decision_id": decision_id,
                "raison": raison,
                "statut": "proposee",
                "options_ecartees": "",
            },
            "horodatage": T,
        },
        "sources": [source],
        "motif": "test fictif de provenance",
        "horodatage": T,
    }


def _session_closee_fictive():
    evenements, session_id = _ouvrir()
    evenements = _tous_deposes(evenements, session_id)
    cloture = sc.cloturer(evenements, session_id, recu_a=T)
    return [*evenements, cloture], cloture


def test_m9_proposer_action_verifie_une_source_conseil_m10_avant_le_port(monkeypatch):
    historique, cloture = _session_closee_fictive()
    fonctions, appels, actions = _outils_proposition_action(monkeypatch, historique)
    proposition = _proposition_m10(source=f"conseil:{cloture['rapport_id']}")

    resultat = fonctions["m9_proposer_action"](**proposition)

    assert resultat["accepte"] is True and resultat["execute"] is False
    assert len(appels) == 1 and len(actions) == 1
    assert sc.valider_chaine(historique) == (True, "")


@pytest.mark.parametrize(
    "mode",
    ["inconnu", "rapport_v2_invalide", "ids_incoherents", "chaine_invalide", "id_raccourci", "sessions_indisponibles"],
)
def test_source_conseil_m10_non_verifiable_refuse_avant_port_ou_registre(mode, monkeypatch):
    historique, cloture = _session_closee_fictive()
    if mode == "rapport_v2_invalide":
        rapport = copy.deepcopy(cloture["rapport"])
        rapport["sections"]["question"]["statut"] = "SCHEMA_CORROMPU"
        rapport["rapport_id"] = rd.identifiant(rapport)
        cloture["rapport"] = rapport
        cloture["rapport_id"] = rapport["rapport_id"]
        historique = _rechaîner_historique(historique)
        source_id = cloture["rapport_id"]
        assert rd.valider_rapport_decision_v2(rapport)[0] is False
    elif mode == "ids_incoherents":
        source_id = cloture["rapport"]["rapport_id"]
        cloture["rapport_id"] = "f" * 64
        historique = _rechaîner_historique(historique)
        assert sc.valider_chaine(historique) == (True, "")
    elif mode == "chaine_invalide":
        source_id = cloture["rapport_id"]
        historique[-1]["hash_maillon"] = "f" * 64
        assert sc.valider_chaine(historique)[0] is False
    elif mode == "id_raccourci":
        source_id = cloture["rapport_id"][:12]
    elif mode == "sessions_indisponibles":
        source_id = cloture["rapport_id"]
    else:
        source_id = "0" * 64

    sessions = historique
    if mode == "sessions_indisponibles":
        class RegistreSessionsIndisponible:
            def __iter__(self):
                raise OSError("détail fictif masqué")

        sessions = RegistreSessionsIndisponible()
    fonctions, appels, actions = _outils_proposition_action(monkeypatch, sessions)
    proposition = _proposition_m10(source=f"conseil:{source_id}")
    attendu = (
        r"^REJ-ACTION-CONSEIL-REFERENCE : fournir le rapport_id complet \(64 hex\) "
        r"d'une clôture M9 v2 vérifiable$"
    )

    with pytest.raises(
        ValueError,
        match=attendu,
    ) as refus:
        fonctions["m9_proposer_action"](**proposition)

    assert "rapport_id complet (64 hex)" in str(refus.value)
    assert appels == []
    assert actions == []


def test_source_conseil_valide_ne_masque_pas_une_autre_reference_invalide(monkeypatch):
    historique, cloture = _session_closee_fictive()
    fonctions, appels, actions = _outils_proposition_action(monkeypatch, historique)
    proposition = _proposition_m10(source=f"conseil:{cloture['rapport_id']}")
    proposition["sources"].append("conseil:" + "0" * 64)

    with pytest.raises(ValueError, match="^REJ-ACTION-CONSEIL-REFERENCE"):
        fonctions["m9_proposer_action"](**proposition)

    assert appels == []
    assert actions == []


def test_source_conseil_valide_ne_prouve_pas_la_correlation_semantique_des_arguments(monkeypatch):
    historique, cloture = _session_closee_fictive()
    fonctions, appels, actions = _outils_proposition_action(monkeypatch, historique)
    proposition = _proposition_m10(
        source=f"conseil:{cloture['rapport_id']}",
        decision_id="DECISION-ARBITRAIRE-FICTIVE",
        raison="aucune référence au rapport dans ce texte fictif",
    )

    resultat = fonctions["m9_proposer_action"](**proposition)

    assert resultat["accepte"] is True
    assert len(appels) == 1 and len(actions) == 1


def test_sources_generiques_et_propositions_existantes_ne_sont_pas_elargies(monkeypatch):
    class RegistreIndisponible:
        def __iter__(self):
            raise AssertionError("aucune lecture conseil attendue")

    fonctions, appels, actions = _outils_proposition_action(monkeypatch, RegistreIndisponible())
    generique = _proposition_m10(
        source="playbook:" + "a" * 64,
        decision_id="m9:" + "b" * 32,
        raison="rapport " + "c" * 64,
    )
    resultat = fonctions["m9_proposer_action"](**generique)
    assert resultat["accepte"] is True and len(appels) == 1 and len(actions) == 1

    proposition_m2 = _proposition_m10(source="conseil:" + "d" * 64)
    proposition_m2["departement"] = "m02-revenue-crm"
    proposition_m2["outil"] = "m2_reassigner_lead"
    resultat_m2 = fonctions["m9_proposer_action"](**proposition_m2)
    assert resultat_m2["accepte"] is True and len(appels) == 2 and len(actions) == 2

    historique, cloture = _session_closee_fictive()
    fonctions, appels, actions = _outils_proposition_action(monkeypatch, historique)
    proposition = _proposition_m10(source=f"conseil:{cloture['rapport_id']}")
    resultat = fonctions["m9_proposer_action"](**proposition)
    action_id = resultat["action_id"]
    historique.clear()  # la source devient indisponible après la première demande

    with pytest.raises(ValueError, match="^REJ-ACTION-REJEU"):
        fonctions["m9_proposer_action"](**proposition)
    lecture = fonctions["m9_lire_actions"](action_id=action_id)

    assert len(appels) == 1
    assert len(actions) == 1
    assert lecture["actions"][0]["action_id"] == action_id


def test_action_historique_a_source_conseil_courte_reste_lisible_sans_registre_sessions(monkeypatch):
    source = "conseil:" + "e" * 12
    proposition = _proposition_m10(source=source)
    arguments_sha256 = empreinte_arguments(proposition["arguments"])
    historique_actions = [
        orchestrateur.proposition(
            [],
            departement=proposition["departement"],
            outil=proposition["outil"],
            arguments_sha256=arguments_sha256,
            demande_id="123456789abc",
            niveau="N3",
            sources=[source],
            motif=proposition["motif"],
            recu_a=T,
            propose_par="admin.fictif",
        )
    ]

    class RegistreIndisponible:
        def __iter__(self):
            raise AssertionError("lecture brute d'action ne doit pas relire les sessions")

    fonctions, appels, actions = _outils_proposition_action(
        monkeypatch, RegistreIndisponible(), actions=historique_actions
    )
    action_id = historique_actions[0]["action_id"]

    with pytest.raises(ValueError, match="^REJ-ACTION-REJEU"):
        fonctions["m9_proposer_action"](**proposition)
    lecture = fonctions["m9_lire_actions"](action_id=action_id)

    assert appels == []
    assert lecture["actions"][0]["action_id"] == action_id
    assert lecture["actions"][0]["sources"] == [source]
    assert actions == historique_actions


def _actions_fictives_proches_borne(suffixe_source: int, *, longueurs_motif=(300, 300)):
    source = "m9.metrics#0:p0." + "a" * suffixe_source
    sources = [source] * 12
    actions = []
    for index in range(2):
        actions.append(
            orchestrateur.proposition(
                actions,
                departement="m10-memoire",
                outil="m10_journaliser_decision",
                arguments_sha256=f"{index + 1:064x}",
                demande_id=f"{index + 1:012x}",
                niveau="N3",
                sources=sources,
                motif="m" * longueurs_motif[index],
                recu_a=T,
                propose_par="admin.fictif",
            )
        )
    return actions


def test_m9_lire_actions_signale_limites_et_borne_exacte_5900_5901(monkeypatch):
    limites_anterieures = (
        "M9 propose ; l'exécution appartient à la file d'approbation native et au département cible, sous leurs rôles.",
        "Les arguments ne sont pas conservés ici (seule leur empreinte) ; un effet inconnu ne se rejoue jamais.",
    )
    taille_limites_anterieures = len(json.dumps(limites_anterieures, ensure_ascii=False, allow_nan=False))
    taille_limites_courantes = len(json.dumps(orchestrateur._LIMITES, ensure_ascii=False, allow_nan=False))
    assert taille_limites_anterieures == 219
    assert taille_limites_courantes == 218
    assert taille_limites_courantes < taille_limites_anterieures

    actions_n148 = _actions_fictives_proches_borne(148)
    avant_n148 = copy.deepcopy(actions_n148)
    fonctions, _, actions = _outils_proposition_action(
        monkeypatch, [], actions=actions_n148, budget_sortie=5900
    )
    page = fonctions["m9_lire_actions"]()
    assert page["limites"] == list(orchestrateur._LIMITES)
    assert "Sources déclarées :" in page["limites"][1]
    assert "lien aux arguments, vérité et authenticité non prouvés" in page["limites"][1]
    assert page["limites"][1].endswith("vérification partielle.")
    assert len(json.dumps(page, ensure_ascii=False, allow_nan=False)) < 5900
    assert actions == avant_n148

    actions_a_5900 = _actions_fictives_proches_borne(155, longueurs_motif=(299, 299))
    avant_a_5900 = copy.deepcopy(actions_a_5900)
    fonctions, _, actions = _outils_proposition_action(
        monkeypatch, [], actions=actions_a_5900, budget_sortie=5900
    )
    page_a_5900 = fonctions["m9_lire_actions"]()
    assert len(json.dumps(page_a_5900, ensure_ascii=False, allow_nan=False)) == 5900
    assert actions == avant_a_5900

    actions_a_5901 = _actions_fictives_proches_borne(155, longueurs_motif=(299, 300))
    avant_a_5901 = copy.deepcopy(actions_a_5901)
    fonctions_large, _, _ = _outils_proposition_action(
        monkeypatch, [], actions=actions_a_5901, budget_sortie=20_000
    )
    page_a_5901 = fonctions_large["m9_lire_actions"]()
    assert len(json.dumps(page_a_5901, ensure_ascii=False, allow_nan=False)) == 5901

    fonctions, _, actions = _outils_proposition_action(
        monkeypatch, [], actions=actions_a_5901, budget_sortie=5900
    )
    with pytest.raises(ValueError, match="^REJ-TISSU-BORNE"):
        fonctions["m9_lire_actions"]()
    assert actions == avant_a_5901


def test_source_conseil_valide_ne_masque_pas_une_cloture_incoherente_de_meme_id(monkeypatch):
    historique, cloture = _session_closee_fictive()
    ouverture_incoherente = copy.deepcopy(historique[0])
    ouverture_incoherente["session_id"] = "e" * 32
    cloture_incoherente = copy.deepcopy(cloture)
    cloture_incoherente["session_id"] = ouverture_incoherente["session_id"]
    cloture_incoherente["rapport"]["sections"]["question"]["statut"] = "SCHEMA_CORROMPU"
    historique = _rechaîner_historique([*historique, ouverture_incoherente, cloture_incoherente])
    assert sc.valider_chaine(historique) == (True, "")
    assert rd.valider_rapport_decision_v2(historique[-1]["rapport"])[0] is False
    fonctions, appels, actions = _outils_proposition_action(monkeypatch, historique)
    proposition = _proposition_m10(source=f"conseil:{cloture['rapport_id']}")
    with pytest.raises(ValueError, match="^REJ-ACTION-CONSEIL-REFERENCE"):
        fonctions["m9_proposer_action"](**proposition)
    assert appels == [] and actions == []


def test_source_conseil_courte_refuse_avant_consultation_des_sessions(monkeypatch):
    class RegistreSessionsSonde:
        lectures = 0

        def __iter__(self):
            self.lectures += 1
            raise OSError("lecture fictive indisponible")

    sessions = RegistreSessionsSonde()
    fonctions, appels, actions = _outils_proposition_action(monkeypatch, sessions)
    with pytest.raises(ValueError, match="^REJ-ACTION-CONSEIL-REFERENCE"):
        fonctions["m9_proposer_action"](**_proposition_m10(source="conseil:" + "a" * 12))
    assert sessions.lectures == 0
    assert appels == [] and actions == []
