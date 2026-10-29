"""M9.4 — sessions de conseil : machine d'états, dépôts admis/refusés, critique, clôture gouvernée (fictif)."""

import pytest
from m9_strategic_intelligence import capture_strategique as cs
from m9_strategic_intelligence import catalogue_producteurs as cat
from m9_strategic_intelligence import dossier_strategique as ds
from m9_strategic_intelligence import rapport_decision_v2 as rd
from m9_strategic_intelligence import sessions_conseil as sc

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


def _tous_deposes(evenements, session_id):
    for role, sortie in (
        ("liaison_finance", SORTIE_FINANCE),
        ("contraintes_inventaire", SORTIE_INVENTAIRE),
        ("conseiller_pdg", SORTIE_PDG),
    ):
        evenements = _ajouter(
            evenements,
            sc.deposer(evenements, session_id, role, sortie, reservation_id=f"res-{role}", tokens_reels=1000, recu_a=T),
        )
    return evenements


def test_cloture_recommandation_gouvernee_et_rapport_v2_valide_aucun_effet():
    evenements, session_id = _ouvrir()
    evenements = _tous_deposes(evenements, session_id)
    cloture = sc.cloturer(evenements, session_id, recu_a=T)
    assert cloture["issue"] == "RECOMMANDATION" and cloture["autorite_d_effet"] is False
    verdicts = {v["action"]: v["verdict"] for v in cloture["gouvernance"]["actions"]}
    assert verdicts == {"a1": "PROPOSABLE", "a2": "VALIDATION_HUMAINE_REQUISE"}
    assert all(v["effet_autorise"] is False for v in cloture["gouvernance"]["actions"])
    rapport = cloture["rapport"]
    assert (
        rd.valider_rapport_decision_v2(rapport) == (True, None)
        and rapport["statut_contrat"] == "PROPOSITION_NON_RATIFIEE"
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
