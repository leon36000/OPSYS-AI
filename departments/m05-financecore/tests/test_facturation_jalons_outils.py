"""Facturation par jalons, numérotation, échéance et PDF (M5-FACT-1, M5-FACT-2) sur le VRAI socle : outils, file
d'approbation, registres durables, panne et reprise, concurrence, mentions, portée d'appareil fermée.

Base SQLite temporaire migrée, vrai manifeste de M5, vraie file d'approbation (`Capacites`, `decider`). Aucun réseau.
Entreprise, client, identifiants et montants fictifs (AGENTS.md). L'horloge est celle de l'appelant (arguments).
"""

from __future__ import annotations

import dataclasses
import hashlib
import io
import json
import threading
from decimal import Decimal
from pathlib import Path

import m5_financecore.outils as m5_outils
import pytest
import yaml
from m5_financecore import analyse, facturation, facturation_jalons, taux_fiscaux
from m5_financecore import registre as registre_module
from sqlalchemy import select

from opsys import approbations as opsys_approbations
from opsys import contexte, identite, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.departements import lire_manifeste
from opsys.outils import Autonomie, Niveau, executer_atomique
from opsys.stockage.maillons import MaillonsDurables
from opsys.stockage.schema import EVENEMENTS_SORTANTS

FICTIF = True
D = Decimal
DEPARTEMENT = "m05-financecore"
_RACINE_M5 = Path(__file__).resolve().parents[1]
H = "2026-11-02T10:00:00-05:00"
ENTREPRISE = {
    "raison_sociale": "Entreprise Fictive Inc.",
    "adresse": ["123, rue Exemple", "Québec (Québec) A1A 1A1"],
    "numero_tps": "123456789 RT0001",
    "numero_tvq": "1234567890 TQ0001",
}
DESTINATAIRE = {"nom": "Madame Cliente Fictive", "adresse": ["45, avenue Exemple", "Lévis (Québec) B2B 2B2"]}
FACTURATION = {
    "numerotation": {"prefixe": "F-", "premier_numero": 1000, "largeur": 5},
    "conditions_paiement": {"delai_jours": 30},
    "entreprise": ENTREPRISE,
}
CONFIG = {
    "operations": {"relances": {"delai_echeance_jours": 30, "paliers_jours_apres_echeance": [7, 21, 45]}},
    "facturation": FACTURATION,
}
JALONS = [
    {
        "libelle": "Acompte à l'acceptation",
        "declencheur": "acceptation",
        "pourcentage": "30",
        "delai_paiement_jours": 0,
    },
    {"libelle": "Mi-chantier", "declencheur": "chantier", "pourcentage": "40"},
    {"libelle": "Solde à la fin des travaux", "declencheur": "fin_travaux", "pourcentage": "30"},
]
OUTILS_NOUVEAUX = {
    "m5_declarer_plan_facturation": (Autonomie.T1, Niveau.N3),
    "m5_revoquer_plan_facturation": (Autonomie.T1, Niveau.N3),
    "m5_creer_facture_jalon": (Autonomie.T1, Niveau.N1),
    "m5_lire_plan_facturation": (Autonomie.T0, None),
    "m5_verifier_numerotation_factures": (Autonomie.T0, None),
    "m5_preparer_pdf_facture": (Autonomie.T1, Niveau.N1),
    "m5_preparer_etat_compte_client": (Autonomie.T1, Niveau.N1),
}


@pytest.fixture(autouse=True)
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm5-fact.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    stockage.migrer(url)
    m5_outils.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(
            cnx, "nathan", "Nathan Propriétaire (fictif)", "mot-de-passe-nathan-1234", ["nathan_owner", "admin"]
        )
        identite.creer_personne(
            cnx, "comptable", "Une Comptable (fictive)", "mot-de-passe-compta-1234", ["finance", "admin"]
        )
        identite.creer_personne(cnx, "employe1", "Un Employé (fictif)", "mot-de-passe-employe-1234", ["employee"])
    yield url
    stockage.liberer()


@pytest.fixture
def dep():
    return lire_manifeste(_RACINE_M5)


@pytest.fixture
def par_nom():
    return {o.nom: o for o in m5_outils.outils()}


@pytest.fixture
def declare(tmp_path, monkeypatch):
    def _declarer(configuration):
        manifeste = tmp_path / "department.yaml"
        manifeste.write_text(yaml.safe_dump({"configuration": configuration}, allow_unicode=True), encoding="utf-8")
        monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)

    _declarer(CONFIG)
    return _declarer


def _taux():
    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(m5_outils._CHEMIN_TAUX_FISCAUX)
    assert erreurs == []
    return dictionnaire


# ---------------------------------------------------------------------------------------------------- assistants
def recevoir_devis(devis_id="D-1", prix="10000.00", chantier=None):
    """Le consommateur RÉEL de `m3.devis_accepte` (charge du catalogue) : M5 garde le devis accepté."""
    charge = {
        "devis_id": devis_id,
        "lead_id": "lead-" + devis_id,
        "chantier_id": chantier,
        "lignes": [
            {
                "reference_ligne": devis_id + "-L0",
                "description": "Gouttières (fictif)",
                "quantite": "40",
                "unite": "pi",
                "prix_unitaire": format(D(prix) / 40, "f"),
                "prix_ligne": prix,
                "reference_besoin_materiau": None,
            }
        ],
        "cout_total": "7000.00",
        "prix_total": prix,
        "taux_marge": "0.30",
        "duree_estimee_minutes": "100",
        "horodatage_acceptation": "2026-10-20T09:00:00-04:00",
    }
    with stockage.transaction():
        return m5_outils._recevoir_devis_accepte(charge)


def recevoir_travaux_termines(devis_id="D-1"):
    charge = {
        "wct_id": "wct-" + devis_id,
        "intervention_id": "int-" + devis_id,
        "lead_id": "lead-" + devis_id,
        "technicien_id": "tech-fictif-a",
        "horodatage_completion": "2026-11-20T14:00:00-05:00",
        "fix_gps_completion": {"latitude": 45.75, "longitude": -73.5},
        "duree_reelle_minutes": 120,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": "deadbeef",
        "consommateurs_cibles": ["M8"],
        "devis_id": devis_id,
        "statut": "completed_verified",
    }
    with stockage.transaction():
        return m5_outils._recevoir_travaux_termines(charge)


def decider(dep, nom, arguments, *, par="comptable", approuver=True):
    """L'agent PROPOSE l'appel (file d'approbation du socle) ; la personne `par` le décide. Rend (demande, décision)."""
    capacites = Capacites({DEPARTEMENT: dep}, stockage.transaction)
    reponse = capacites.appeler(nom, arguments)
    assert reponse["statut"] == "en_attente_approbation", reponse
    disponibles = outils_executables({DEPARTEMENT: dep}, stockage.transaction)
    with stockage.transaction() as cnx:
        decision = opsys_approbations.decider(
            cnx, reponse["demande_id"], approuver, par, disponibles, {DEPARTEMENT: dep}
        )
    return reponse["demande_id"], decision


def resultat(decision):
    """La réponse de l'outil exécuté par la décision (refus métier compris : le socle le range « echec »)."""
    assert decision["statut"] in ("executee", "echec") and decision["reponse"]["ok"] is True, decision
    return decision["reponse"]["resultat"]


def declarer_plan(dep, jalons=None, devis_id="D-1", chantier_id="CH-1", horodatage=H, **kw):
    _, decision = decider(
        dep,
        "m5_declarer_plan_facturation",
        {"devis_id": devis_id, "jalons": jalons or JALONS, "chantier_id": chantier_id, "horodatage": horodatage},
        **kw,
    )
    return resultat(decision)


def appeler(par_nom, nom, arguments, identite_appelante=None):
    outil = par_nom[nom]
    if identite_appelante is None:
        return executer_atomique(outil, arguments)
    with contexte.appele_par_appareil(identite_appelante):
        return executer_atomique(outil, arguments)


def utile(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def refus(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]


def creer_jalon(par_nom, rang, devis_id="D-1", horodatage=H):
    return appeler(par_nom, "m5_creer_facture_jalon", {"devis_id": devis_id, "rang": rang, "horodatage": horodatage})


def facture_id(plan_id, rang):
    return f"fac-{plan_id}-J{rang}"


def emettre(dep, fid, horodatage=H, **kw):
    _, decision = decider(dep, "m5_envoyer_facture", {"facture_id": fid, "horodatage": horodatage}, **kw)
    return decision


def etat_facture(fid):
    with stockage.transaction():
        return facturation._etat_facture(m5_outils._registre_factures(None), fid)


def registre(nom):
    with stockage.transaction():
        return registre_module.Registre(maillons=stockage.maillons(DEPARTEMENT, nom)).lire()


def monde_a_trois_jalons(dep, par_nom, *, emettre_jalons=()):
    recevoir_devis()
    plan_id = declarer_plan(dep)["resultat"]["plan_id"]
    for rang in (1, 2):
        utile(creer_jalon(par_nom, rang))
    for rang in emettre_jalons:
        assert emettre(dep, facture_id(plan_id, rang))["statut"] == "executee"
    return plan_id


# ============================================================================================ niveaux et portée
def test_niveaux_autonomie_et_portee_des_outils_de_facturation(par_nom):
    for nom, (autonomie, niveau) in OUTILS_NOUVEAUX.items():
        outil = par_nom[nom]
        assert outil.autonomie is autonomie and outil.niveau == niveau, nom
        assert outil.roles_appareil == frozenset(), f"{nom} : portée d'appareil fermée"
        assert nom in analyse.SORTIES_D_ANALYSE or nom in analyse.SORTIES_HORS_ANALYSE
    assert par_nom["m5_envoyer_facture"].niveau_effectif is Niveau.N4  # l'émission reste N4
    assert par_nom["m5_enregistrer_paiement_facture"].niveau_effectif is Niveau.N5
    # déclarer ou révoquer un plan engage envers un client : jamais en dessous de N3 ; rien ne s'envoie ni ne se paie
    # ici
    for nom in ("m5_declarer_plan_facturation", "m5_revoquer_plan_facturation"):
        assert par_nom[nom].niveau_effectif is Niveau.N3


def test_les_outils_de_facturation_refusent_un_appel_d_appareil(par_nom, declare, dep):
    recevoir_devis()
    plan_id = declarer_plan(dep)["resultat"]["plan_id"]
    appelante = contexte.IdentiteAppelante(personne="comptable", role="admin")
    for nom, arguments in (
        ("m5_creer_facture_jalon", {"devis_id": "D-1", "rang": 1, "horodatage": H}),
        ("m5_lire_plan_facturation", {"devis_id": "D-1"}),
        ("m5_verifier_numerotation_factures", {}),
        ("m5_preparer_pdf_facture", {"facture_id": "x", "langue": "fr", "destinataire": DESTINATAIRE, "horodatage": H}),
        (
            "m5_preparer_etat_compte_client",
            {"client_id": "c", "au": "2026-11-02", "langue": "fr", "destinataire": DESTINATAIRE, "horodatage": H},
        ),
    ):
        verdict = refus(appeler(par_nom, nom, arguments, appelante))
        assert verdict["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE", nom
    assert registre("factures") == [] and plan_id


def test_aucun_outil_de_facturation_ne_nomme_le_registre_des_mouvements_ni_n_envoie_rien():
    from m5_financecore import conformite

    racine = _RACINE_M5 / "src" / "m5_financecore"
    assert conformite.verifier_aucun_decaissement(racine) == (True, "")
    assert conformite.verifier_conformite(racine)["conforme"] is True


# =============================================================================================== le plan (N3)
def test_declarer_un_plan_passe_par_la_file_et_une_personne_l_ecrit_un_agent_seul_jamais(par_nom, declare, dep):
    recevoir_devis()
    arguments = {"devis_id": "D-1", "jalons": JALONS, "chantier_id": "CH-1", "horodatage": H}
    capacites = Capacites({DEPARTEMENT: dep}, stockage.transaction)
    reponse = capacites.appeler("m5_declarer_plan_facturation", arguments)
    assert reponse["statut"] == "en_attente_approbation" and registre("plans_facturation") == []
    # exécuté directement (hors file) : refusé, comme pour toute décision humaine requise
    verdict = refus(appeler(par_nom, "m5_declarer_plan_facturation", arguments))
    assert verdict["code"] == "REJ-OPS-HUMAIN-REQUIS" and registre("plans_facturation") == []
    # un employé ne décide pas
    disponibles = outils_executables({DEPARTEMENT: dep}, stockage.transaction)
    with stockage.transaction() as cnx, pytest.raises(ValueError, match="aucun rôle autorisé"):
        opsys_approbations.decider(cnx, reponse["demande_id"], True, "employe1", disponibles, {DEPARTEMENT: dep})
    assert registre("plans_facturation") == []
    with stockage.transaction() as cnx:
        decision = opsys_approbations.decider(
            cnx, reponse["demande_id"], True, "comptable", disponibles, {DEPARTEMENT: dep}
        )
    corps = resultat(decision)["resultat"]
    assert corps["statut"] == "ecrit" and corps["declare_par"] == {"par": "comptable", "role": "finance"}
    assert [j["montant_avant_taxes"] for j in corps["jalons"]] == ["3000.00", "4000.00", "3000.00"]
    assert corps["mention"] == analyse.MENTION_ANALYSE_PREPARATOIRE and "CPA" in corps["mention_comptable"]
    [maillon] = registre("plans_facturation")
    assert maillon["type_entree"] == "plan_facturation_declare" and maillon["declare_par"]["par"] == "comptable"


def test_refuser_la_demande_n_ecrit_aucun_plan(par_nom, declare, dep):
    recevoir_devis()
    _, decision = decider(
        dep,
        "m5_declarer_plan_facturation",
        {"devis_id": "D-1", "jalons": JALONS, "chantier_id": "CH-1", "horodatage": H},
        approuver=False,
    )
    assert decision["statut"] == "refusee" and registre("plans_facturation") == []


def test_redeclarer_le_meme_plan_ne_cree_rien_et_un_autre_plan_actif_est_refuse(par_nom, declare, dep):
    recevoir_devis()
    premier = declarer_plan(dep)
    rejeu = declarer_plan(dep)
    assert rejeu["resultat"]["statut"] == "deja" and rejeu["resultat"]["plan_id"] == premier["resultat"]["plan_id"]
    assert len(registre("plans_facturation")) == 1
    autre = [{**JALONS[0], "pourcentage": "20"}, JALONS[1], {**JALONS[2], "pourcentage": "40"}]
    verdict = declarer_plan(dep, jalons=autre)["verdict"]
    assert verdict["code"] == "REJ-PLAN-DEJA-DECLARE" and len(registre("plans_facturation")) == 1


def test_les_refus_du_plan_disent_quoi_declarer(par_nom, declare, dep):
    inconnu = declarer_plan(dep, devis_id="D-INCONNU")["verdict"]
    assert inconnu["code"] == "REJ-PLAN-DEVIS-INCONNU" and "m3.devis_accepte" in inconnu["detail"]
    recevoir_devis()
    assert declarer_plan(dep, chantier_id=None)["verdict"]["code"] == "REJ-PLAN-CHANTIER-A-DECLARER"
    fausse = [{**JALONS[0], "pourcentage": "30"}, JALONS[1], {**JALONS[2], "pourcentage": "29"}]
    assert declarer_plan(dep, jalons=fausse)["verdict"]["code"] == "REJ-PLAN-SOMME-POURCENTAGES"
    montants = [
        {"libelle": "A", "declencheur": "acceptation", "montant_avant_taxes": "3000.00"},
        {"libelle": "B", "declencheur": "fin_travaux", "montant_avant_taxes": "6999.99"},
    ]
    verdict = declarer_plan(dep, jalons=montants)["verdict"]
    assert verdict["code"] == "REJ-PLAN-SOMME-INCORRECTE" and "écart -0.01 $" in verdict["detail"]
    assert registre("plans_facturation") == []


def test_sans_conditions_de_paiement_declarees_le_refus_dit_quoi_declarer(par_nom, declare, dep):
    declare({**CONFIG, "facturation": {k: v for k, v in FACTURATION.items() if k != "conditions_paiement"}})
    recevoir_devis()
    sans_delai = [{k: v for k, v in j.items() if k != "delai_paiement_jours"} for j in JALONS]
    verdict = declarer_plan(dep, jalons=sans_delai)["verdict"]
    assert verdict["code"] == "REJ-PLAN-DELAI-A-DECLARER"
    assert "configuration.facturation.conditions_paiement.delai_jours" in verdict["detail"]
    # le délai peut aussi se déclarer sur CHAQUE jalon
    avec_delai = [{**j, "delai_paiement_jours": 15} for j in JALONS]
    assert declarer_plan(dep, jalons=avec_delai)["resultat"]["statut"] == "ecrit"


def test_des_conditions_declarees_mais_mal_formees_sont_un_refus_jamais_ignorees(par_nom, declare, dep):
    declare({**CONFIG, "facturation": {**FACTURATION, "conditions_paiement": {"delai_jours": -3}}})
    recevoir_devis()
    assert declarer_plan(dep)["verdict"]["code"] == "REJ-CONDITIONS-A-DECLARER"


def test_un_devis_deja_facture_en_bloc_ne_recoit_plus_de_plan(par_nom, declare, dep):
    recevoir_devis(chantier="CH-1")
    recevoir_travaux_termines()  # facture globale BROUILLON automatique (comportement historique)
    assert etat_facture("fac-D-1")["statut"] == "BROUILLON"
    verdict = declarer_plan(dep)["verdict"]
    assert verdict["code"] == "REJ-PLAN-DEVIS-DEJA-FACTURE" and "AVANT la fin des travaux" in verdict["detail"]


def test_le_plan_porte_le_chantier_du_devis_ou_celui_qu_on_declare(par_nom, declare, dep):
    recevoir_devis(devis_id="D-2", chantier="CH-DU-DEVIS")
    corps = declarer_plan(dep, devis_id="D-2", chantier_id=None)["resultat"]
    assert registre("plans_facturation")[0]["chantier_id"] == "CH-DU-DEVIS" and corps["statut"] == "ecrit"
    recevoir_devis(devis_id="D-3", chantier="CH-DU-DEVIS")
    assert (
        declarer_plan(dep, devis_id="D-3", chantier_id="CH-AUTRE")["verdict"]["code"] == "REJ-PLAN-CHANTIER-A-DECLARER"
    )


def test_revoquer_un_plan_sans_facture_puis_en_declarer_un_autre(par_nom, declare, dep):
    recevoir_devis()
    plan_id = declarer_plan(dep)["resultat"]["plan_id"]
    _, decision = decider(
        dep, "m5_revoquer_plan_facturation", {"plan_id": plan_id, "motif": "pourcentages à revoir", "horodatage": H}
    )
    assert resultat(decision)["resultat"]["statut"] == "REVOQUE"
    autre = [{**JALONS[0], "pourcentage": "50"}, {**JALONS[2], "pourcentage": "50"}]
    nouveau = declarer_plan(dep, jalons=autre)["resultat"]
    assert nouveau["statut"] == "ecrit" and nouveau["plan_id"] != plan_id and nouveau["plan_id"].endswith("-v2")
    _, decision = decider(dep, "m5_revoquer_plan_facturation", {"plan_id": plan_id, "motif": "encore", "horodatage": H})
    assert resultat(decision)["verdict"]["code"] == "REJ-PLAN-DEJA-REVOQUE"


def test_un_plan_qui_a_donne_une_facture_ne_se_revoque_plus(par_nom, declare, dep):
    recevoir_devis()
    plan_id = declarer_plan(dep)["resultat"]["plan_id"]
    utile(creer_jalon(par_nom, 1))
    _, decision = decider(
        dep, "m5_revoquer_plan_facturation", {"plan_id": plan_id, "motif": "trop tard", "horodatage": H}
    )
    assert resultat(decision)["verdict"]["code"] == "REJ-PLAN-REVOCATION-IMPOSSIBLE"
    assert len(registre("plans_facturation")) == 1


def test_un_registre_des_plans_altere_bloque_toute_lecture_et_toute_ecriture(par_nom, declare, dep):
    recevoir_devis()
    declarer_plan(dep)
    from sqlalchemy import update

    from opsys.stockage import codec
    from opsys.stockage.schema import REGISTRES

    filtre = (REGISTRES.c.departement == DEPARTEMENT) & (REGISTRES.c.registre == "plans_facturation")
    with stockage.transaction() as cnx:
        ligne = codec.decoder(cnx.execute(select(REGISTRES.c.maillon).where(filtre)).scalar_one())
        ligne["jalons"][0]["montant_avant_taxes"] = "1.00"
        cnx.execute(update(REGISTRES).where(filtre).values(maillon=codec.encoder(ligne)))
    assert refus(creer_jalon(par_nom, 1))["code"] == "REJ-PLAN-CHAINE-INVALIDE"
    assert (
        refus(appeler(par_nom, "m5_lire_plan_facturation", {"devis_id": "D-1"}))["code"] == "REJ-PLAN-CHAINE-INVALIDE"
    )
    assert declarer_plan(dep)["verdict"]["code"] == "REJ-PLAN-CHAINE-INVALIDE"
    assert registre("factures") == []


# =========================================================================================== factures de jalon
def test_la_facture_d_un_jalon_porte_le_montant_du_plan_et_les_taxes_du_moteur(par_nom, declare, dep):
    recevoir_devis()
    plan_id = declarer_plan(dep)["resultat"]["plan_id"]
    corps = utile(creer_jalon(par_nom, 1))
    facture = corps["facture"]
    assert (
        corps["statut"] == "creee"
        and facture["statut"] == "BROUILLON"
        and facture["facture_id"] == facture_id(plan_id, 1)
    )
    assert facture["montant_avant_taxes"] == "3000.00" and facture["total_taxes"] == "449.25"
    assert facture["montant_apres_taxes"] == "3449.25" and facture["numero_facture"] is None
    assert {t["id"]: t["montant"] for t in facture["taxes"]} == {"tps_federale": "150.00", "tvq_quebec": "299.25"}
    assert "mention_comptable" in corps and "BROUILLON" in corps["a_faire"]
    etat = etat_facture(facture_id(plan_id, 1))
    assert (etat["plan_id"], etat["jalon_rang"], etat["devis_id"], etat["chantier_id"]) == (plan_id, 1, "D-1", "CH-1")


def test_creer_deux_fois_le_meme_jalon_ne_cree_rien_meme_a_un_autre_instant(par_nom, declare, dep):
    recevoir_devis()
    declarer_plan(dep)
    utile(creer_jalon(par_nom, 1))
    taille = len(registre("factures"))
    rejeu = utile(creer_jalon(par_nom, 1, horodatage="2026-11-03T08:00:00-05:00"))
    assert rejeu["statut"] == "deja" and len(registre("factures")) == taille


def test_ordre_des_jalons_travaux_termines_et_plan_absent(par_nom, declare, dep):
    assert refus(creer_jalon(par_nom, 1))["code"] == "REJ-PLAN-INTROUVABLE"
    recevoir_devis()
    declarer_plan(dep)
    assert refus(creer_jalon(par_nom, 2))["code"] == "REJ-PLAN-JALON-HORS-ORDRE"
    utile(creer_jalon(par_nom, 1))
    utile(creer_jalon(par_nom, 2))
    solde = refus(creer_jalon(par_nom, 3))
    assert solde["code"] == "REJ-PLAN-TRAVAUX-NON-TERMINES"
    recevoir_travaux_termines()
    corps = utile(creer_jalon(par_nom, 3))
    assert corps["facture"]["montant_avant_taxes"] == "3000.00"


def test_la_facture_globale_est_refusee_ou_non_creee_pour_un_devis_facture_par_jalons(par_nom, declare, dep):
    recevoir_devis()
    plan_id = declarer_plan(dep)["resultat"]["plan_id"]
    ligne = [
        {
            "description": "x",
            "quantite": "1",
            "unite": "forfait",
            "prix_unitaire": "10000.00",
            "reference_ligne_devis": "r",
        }
    ]
    verdict = refus(
        appeler(
            par_nom,
            "m5_creer_facture_brouillon",
            {
                "facture_id": "fac-D-1",
                "chantier_id": "CH-1",
                "devis_id": "D-1",
                "client_id": "c",
                "lignes": ligne,
                "horodatage": H,
            },
        )
    )
    assert verdict["code"] == "REJ-PLAN-FACTURATION-PAR-JALONS" and plan_id in verdict["detail"]
    # le consommateur de la fin des travaux ne crée pas non plus la facture globale automatique
    suite = recevoir_travaux_termines()
    assert suite["statut"] == "facturation_par_jalons" and suite["plan_id"] == plan_id
    assert registre("factures") == []
    assert m5_outils.lister_attentes_facturation()["attentes_devis"] == []


def test_les_attentes_listent_encore_un_devis_sans_plan(par_nom, declare, dep):
    recevoir_devis(devis_id="D-9", chantier=None)
    assert [a["devis_id"] for a in m5_outils.lister_attentes_facturation()["attentes_devis"]] == ["D-9"]


def test_le_prix_facture_pour_la_rentabilite_est_celui_du_contrat_pas_celui_du_premier_acompte(par_nom, declare, dep):
    recevoir_devis()
    declarer_plan(dep)
    utile(creer_jalon(par_nom, 1))
    with stockage.transaction():
        source = m5_outils._sources_cout_reel()["factures"]["D-1"]
    assert source["montant_avant_taxes"] == D("10000.00") and source["statut"] == "BROUILLON"


# ==================================================================================== émission : numéro, échéance
def test_l_emission_fixe_le_numero_et_l_echeance_et_la_suite_ne_saute_rien(par_nom, declare, dep):
    plan_id = monde_a_trois_jalons(dep, par_nom)
    decision = emettre(dep, facture_id(plan_id, 1), horodatage="2026-11-02T10:00:00-05:00")
    assert decision["statut"] == "executee"
    premiere = etat_facture(facture_id(plan_id, 1))
    assert (premiere["statut"], premiere["numero_facture"], premiere["sequence_facture"]) == (
        "ENVOYEE",
        "F-01000",
        1000,
    )
    assert (premiere["echeance"], premiere["delai_paiement_jours"]) == (
        "2026-11-02",
        0,
    )  # acompte payable à la réception
    emettre(dep, facture_id(plan_id, 2), horodatage="2026-11-09T10:00:00-05:00")
    deuxieme = etat_facture(facture_id(plan_id, 2))
    assert (deuxieme["numero_facture"], deuxieme["echeance"], deuxieme["delai_paiement_jours"]) == (
        "F-01001",
        "2026-12-09",
        30,
    )
    numeros = registre("numerotation_factures")
    assert [(m["sequence"], m["numero_facture"], m["facture_id"]) for m in numeros] == [
        (1000, "F-01000", facture_id(plan_id, 1)),
        (1001, "F-01001", facture_id(plan_id, 2)),
    ]
    verification = utile(appeler(par_nom, "m5_verifier_numerotation_factures", {}))
    assert verification["ok"] is True and verification["premier"] == 1000 and verification["dernier"] == 1001
    assert verification["factures_numerotees_hors_registre"] == [] and verification["numeros_sans_facture_emise"] == []


def test_emettre_exige_une_personne_meme_quand_le_departement_est_autonome(par_nom, declare, dep):
    plan_id = monde_a_trois_jalons(dep, par_nom)
    fid = facture_id(plan_id, 1)
    # appel direct de l'outil : jamais sans la décision d'une personne (plafond d'envoi automatique : zéro)
    verdict = refus(appeler(par_nom, "m5_envoyer_facture", {"facture_id": fid, "horodatage": H}))
    assert verdict["code"] == "REJ-OPS-HUMAIN-REQUIS" and etat_facture(fid)["statut"] == "BROUILLON"
    # mode « autonome » : le socle n'intercepte plus N4, l'outil exige encore la personne
    autonome = dataclasses.replace(dep, mode="autonome")
    reponse = Capacites({DEPARTEMENT: autonome}, stockage.transaction).appeler(
        "m5_envoyer_facture", {"facture_id": fid, "horodatage": H}
    )
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-OPS-HUMAIN-REQUIS"
    assert etat_facture(fid)["statut"] == "BROUILLON" and registre("numerotation_factures") == []
    # en mode normal, l'agent ne fait que PROPOSER ; seule la décision d'une personne émet
    capacites = Capacites({DEPARTEMENT: dep}, stockage.transaction)
    assert (
        capacites.appeler("m5_envoyer_facture", {"facture_id": fid, "horodatage": H})["statut"]
        == "en_attente_approbation"
    )
    assert etat_facture(fid)["statut"] == "BROUILLON" and registre("numerotation_factures") == []
    assert emettre(dep, fid)["statut"] == "executee" and etat_facture(fid)["numero_facture"] == "F-01000"


def test_emettre_deux_fois_ou_une_facture_inconnue_ne_consomme_aucun_numero(par_nom, declare, dep):
    plan_id = monde_a_trois_jalons(dep, par_nom, emettre_jalons=(1,))
    deja = resultat(emettre(dep, facture_id(plan_id, 1)))["verdict"]
    assert deja["code"] == "REJ-FACTURE-TRANSITION-ILLEGALE"
    inconnue = resultat(emettre(dep, "fac-inconnue"))["verdict"]
    assert inconnue["code"] == "REJ-FACTURE-INTROUVABLE"
    assert [m["sequence"] for m in registre("numerotation_factures")] == [1000]
    assert emettre(dep, facture_id(plan_id, 2))["statut"] == "executee"
    assert etat_facture(facture_id(plan_id, 2))["numero_facture"] == "F-01001"  # la suite n'a pas sauté un numéro


def test_sans_numerotation_declaree_une_facture_de_jalon_ne_s_emet_pas_et_dit_quoi_declarer(par_nom, declare, dep):
    declare({**CONFIG, "facturation": {k: v for k, v in FACTURATION.items() if k != "numerotation"}})
    plan_id = monde_a_trois_jalons(dep, par_nom)
    decision = emettre(dep, facture_id(plan_id, 1))
    verdict = resultat(decision)["verdict"]
    assert verdict["code"] == "REJ-NUMEROTATION-A-DECLARER" and "premier_numero" in verdict["detail"]
    assert etat_facture(facture_id(plan_id, 1))["statut"] == "BROUILLON" and registre("numerotation_factures") == []


def test_une_numerotation_declaree_mais_mal_formee_est_toujours_un_refus(par_nom, declare, dep):
    declare(
        {**CONFIG, "facturation": {**FACTURATION, "numerotation": {"prefixe": "F-", "premier_numero": 0, "largeur": 5}}}
    )
    plan_id = monde_a_trois_jalons(dep, par_nom)
    assert resultat(emettre(dep, facture_id(plan_id, 1)))["verdict"]["code"] == "REJ-NUMEROTATION-A-DECLARER"


def test_une_facture_ordinaire_garde_son_comportement_tant_que_la_numerotation_n_est_pas_declaree(
    par_nom, declare, dep
):
    declare({"operations": CONFIG["operations"]})
    ligne = [
        {
            "description": "x",
            "quantite": "1",
            "unite": "forfait",
            "prix_unitaire": "600.00",
            "reference_ligne_devis": "r",
        }
    ]
    utile_ = appeler(
        par_nom,
        "m5_creer_facture_brouillon",
        {
            "facture_id": "F-LEG",
            "chantier_id": "CH",
            "devis_id": "D-LEG",
            "client_id": "c",
            "lignes": ligne,
            "horodatage": H,
        },
    )
    assert utile_["resultat"]["accepte"] is True
    assert emettre(dep, "F-LEG")["statut"] == "executee"
    etat = etat_facture("F-LEG")
    assert etat["statut"] == "ENVOYEE" and "numero_facture" not in etat and "echeance" not in etat
    assert registre("numerotation_factures") == []


def test_une_facture_ordinaire_est_numerotee_et_recoit_une_echeance_des_que_le_proprietaire_l_a_declare(
    par_nom, declare, dep
):
    ligne = [
        {
            "description": "x",
            "quantite": "1",
            "unite": "forfait",
            "prix_unitaire": "600.00",
            "reference_ligne_devis": "r",
        }
    ]
    appeler(
        par_nom,
        "m5_creer_facture_brouillon",
        {
            "facture_id": "F-LEG",
            "chantier_id": "CH",
            "devis_id": "D-LEG",
            "client_id": "c",
            "lignes": ligne,
            "horodatage": H,
        },
    )
    assert emettre(dep, "F-LEG", horodatage="2026-11-02T10:00:00-05:00")["statut"] == "executee"
    etat = etat_facture("F-LEG")
    assert (etat["numero_facture"], etat["echeance"]) == ("F-01000", "2026-12-02")


# ------------------------------------------------------------------------------------------ panne et reprise
def test_une_panne_pendant_l_emission_ne_consomme_aucun_numero(par_nom, declare, dep, monkeypatch):
    plan_id = monde_a_trois_jalons(dep, par_nom)
    fid = facture_id(plan_id, 1)
    original = MaillonsDurables.append

    def panne_apres_le_numero(self, maillon, *, rang_attendu=None):
        if (self.departement, self.registre) == (DEPARTEMENT, "factures") and maillon.get("statut") == "ENVOYEE":
            raise ConnectionError("panne simulée entre l'attribution du numéro et le statut")
        return original(self, maillon, rang_attendu=rang_attendu)

    monkeypatch.setattr(MaillonsDurables, "append", panne_apres_le_numero)
    decision = emettre(dep, fid)
    assert decision["statut"] == "echec" and "panne simulée" in decision["reponse"]["details"]
    stockage.liberer()
    assert registre("numerotation_factures") == [] and etat_facture(fid)["statut"] == "BROUILLON"
    monkeypatch.setattr(MaillonsDurables, "append", original)
    assert emettre(dep, fid)["statut"] == "executee"
    assert etat_facture(fid)["numero_facture"] == "F-01000"  # le premier numéro de la suite, pas le deuxième
    assert [m["sequence"] for m in registre("numerotation_factures")] == [1000]
    assert emettre(dep, facture_id(plan_id, 2))["statut"] == "executee"
    assert etat_facture(facture_id(plan_id, 2))["numero_facture"] == "F-01001"


def test_un_numero_deja_attribue_a_la_facture_est_repris_apres_une_demi_ecriture(par_nom, declare, dep):
    plan_id = monde_a_trois_jalons(dep, par_nom)
    fid = facture_id(plan_id, 1)
    # demi-écriture hors transaction d'émission : le numéro est au registre, le statut n'a pas suivi
    with stockage.transaction():
        copie = registre_module.Registre(maillons=stockage.maillons(DEPARTEMENT, "numerotation_factures")[:])
        resultat_, refus_ = facturation_jalons.attribuer_numero(copie, FACTURATION["numerotation"], fid, H)
        assert refus_ is None
        stockage.maillons(DEPARTEMENT, "numerotation_factures").append(resultat_["numero"], rang_attendu=0)
    assert emettre(dep, fid)["statut"] == "executee"
    assert etat_facture(fid)["numero_facture"] == "F-01000"
    assert [m["sequence"] for m in registre("numerotation_factures")] == [1000]  # rien de consommé en double
    emettre(dep, facture_id(plan_id, 2))
    assert [m["sequence"] for m in registre("numerotation_factures")] == [1000, 1001]
    assert utile(appeler(par_nom, "m5_verifier_numerotation_factures", {}))["ok"] is True


def test_la_verification_dit_un_numero_sans_facture_emise_et_une_facture_hors_registre(par_nom, declare, dep):
    plan_id = monde_a_trois_jalons(dep, par_nom)
    with stockage.transaction():
        copie = registre_module.Registre(maillons=stockage.maillons(DEPARTEMENT, "numerotation_factures")[:])
        resultat_, _ = facturation_jalons.attribuer_numero(
            copie, FACTURATION["numerotation"], facture_id(plan_id, 1), H
        )
        stockage.maillons(DEPARTEMENT, "numerotation_factures").append(resultat_["numero"], rang_attendu=0)
    verification = utile(appeler(par_nom, "m5_verifier_numerotation_factures", {}))
    assert verification["ok"] is False and verification["numeros_sans_facture_emise"] == [facture_id(plan_id, 1)]


def test_un_trou_dans_la_suite_bloque_toute_emission_et_la_verification_le_dit(par_nom, declare, dep):
    plan_id = monde_a_trois_jalons(dep, par_nom)
    fantome = {
        "type_entree": "numero_facture_attribue",
        "facture_id": "fantome",
        "sequence": 1005,
        "numero_facture": "F-01005",
        "prefixe": "F-",
        "largeur": 5,
        "premier_numero": 1000,
        "horodatage": H,
    }
    with stockage.transaction():
        copie = registre_module.Registre()
        copie.ajouter(fantome)
        stockage.maillons(DEPARTEMENT, "numerotation_factures").append(copie.lire()[0], rang_attendu=0)
    verification = utile(appeler(par_nom, "m5_verifier_numerotation_factures", {}))
    assert verification["ok"] is False and verification["trous"][:3] == [1000, 1001, 1002]
    verdict = resultat(emettre(dep, facture_id(plan_id, 1)))["verdict"]
    assert (
        verdict["code"] == "REJ-NUMEROTATION-CHAINE-INVALIDE"
        and etat_facture(facture_id(plan_id, 1))["statut"] == "BROUILLON"
    )


def test_le_premier_numero_declare_ne_change_plus_une_fois_la_suite_commencee(par_nom, declare, dep):
    plan_id = monde_a_trois_jalons(dep, par_nom)
    emettre(dep, facture_id(plan_id, 1))
    declare(
        {
            **CONFIG,
            "facturation": {**FACTURATION, "numerotation": {"prefixe": "F-", "premier_numero": 5000, "largeur": 5}},
        }
    )
    verdict = resultat(emettre(dep, facture_id(plan_id, 2)))["verdict"]
    assert verdict["code"] == "REJ-NUMEROTATION-PREMIER-CHANGE" and "1000" in verdict["detail"]
    assert len(registre("numerotation_factures")) == 1


# ---------------------------------------------------------------------------------------------- concurrence
def test_deux_emissions_simultanees_recoivent_deux_numeros_distincts_sans_trou(par_nom, declare, dep):
    plan_id = monde_a_trois_jalons(dep, par_nom)
    capacites = Capacites({DEPARTEMENT: dep}, stockage.transaction)
    demandes = [
        capacites.appeler("m5_envoyer_facture", {"facture_id": facture_id(plan_id, r), "horodatage": H})["demande_id"]
        for r in (1, 2)
    ]
    disponibles = outils_executables({DEPARTEMENT: dep}, stockage.transaction)
    barriere = threading.Barrier(2)
    decisions: dict[str, dict] = {}
    erreurs: list[BaseException] = []

    def decider_en_parallele(demande):
        try:
            barriere.wait(timeout=10)
            with stockage.transaction() as cnx:
                decisions[demande] = opsys_approbations.decider(
                    cnx, demande, True, "comptable", disponibles, {DEPARTEMENT: dep}
                )
        except BaseException as erreur:  # noqa: BLE001
            erreurs.append(erreur)

    fils = [threading.Thread(target=decider_en_parallele, args=(d,)) for d in demandes]
    for fil in fils:
        fil.start()
    for fil in fils:
        fil.join(timeout=30)
    assert erreurs == [] and all(d["statut"] == "executee" for d in decisions.values()), (erreurs, decisions)
    stockage.liberer()
    numeros = {etat_facture(facture_id(plan_id, r))["numero_facture"] for r in (1, 2)}
    assert numeros == {"F-01000", "F-01001"}
    suite = registre("numerotation_factures")
    assert sorted(m["sequence"] for m in suite) == [1000, 1001]
    assert registre_module.Registre(maillons=suite).valider_chaine() == (True, "")
    assert utile(appeler(par_nom, "m5_verifier_numerotation_factures", {}))["ok"] is True


def test_les_ecritures_de_l_emission_portent_la_precondition_de_rang(par_nom, declare, dep, monkeypatch):
    """Le numéro et le statut s'écrivent avec la précondition de rang : deux écrivains qui ont lu le même état ne se
    superposent jamais (la clé primaire du registre porte la même garde, ceci prouve qu'on s'en sert aussi)."""
    plan_id = monde_a_trois_jalons(dep, par_nom)
    original = MaillonsDurables.append
    appels = []

    def espion(self, maillon, *, rang_attendu=None):
        if (self.departement, self.registre) in ((DEPARTEMENT, "numerotation_factures"), (DEPARTEMENT, "factures")):
            appels.append((self.registre, rang_attendu, len(self)))
        return original(self, maillon, rang_attendu=rang_attendu)

    monkeypatch.setattr(MaillonsDurables, "append", espion)
    assert emettre(dep, facture_id(plan_id, 1))["statut"] == "executee"
    assert appels and all(rang is not None and rang == taille for _, rang, taille in appels), appels
    assert {registre_ for registre_, _, _ in appels} == {"numerotation_factures", "factures"}


def test_une_ecriture_concurrente_pendant_l_emission_clot_la_demande_sans_consommer_de_numero(
    par_nom, declare, dep, monkeypatch
):
    plan_id = monde_a_trois_jalons(dep, par_nom)
    fid = facture_id(plan_id, 1)
    original = MaillonsDurables.append
    declenche = []

    def concurrent(self, maillon, *, rang_attendu=None):
        # Un autre écrivain prend le rang du numéro juste avant nous (chemin de PostgreSQL : le rang est déjà écrit).
        if (self.departement, self.registre) == (DEPARTEMENT, "numerotation_factures") and not declenche:
            declenche.append(True)
            intrus = dict(maillon, facture_id="intrus", ligne_id="x" * 64)
            original(self, intrus, rang_attendu=None)
        return original(self, maillon, rang_attendu=rang_attendu)

    monkeypatch.setattr(MaillonsDurables, "append", concurrent)
    decision = emettre(dep, fid)
    assert decision["statut"] == "echec" and decision["reponse"]["details"].startswith("EcritureConcurrente:")
    stockage.liberer()
    assert registre("numerotation_factures") == [] and etat_facture(fid)["statut"] == "BROUILLON"


# ----------------------------------------------------------------------------- retard, relances, comptes à recevoir
def test_le_retard_est_calcule_a_la_date_injectee_et_n_enregistre_aucun_statut(par_nom, declare, dep):
    plan_id = monde_a_trois_jalons(dep, par_nom, emettre_jalons=(2,))
    arguments = {"role": "admin", "autorise_couts": True}
    veille = utile(appeler(par_nom, "m5_lire_comptes_a_recevoir", {**arguments, "aujourd_hui": "2026-12-02"}))
    assert veille["en_retard"]["nombre"] == 0 and D(veille["en_retard"]["total"]) == 0
    [facture] = veille["factures"]
    assert (facture["numero_facture"], facture["echeance"], facture["statut_effectif"]) == (
        "F-01000",
        "2026-12-02",
        "ENVOYEE",
    )
    lendemain = utile(appeler(par_nom, "m5_lire_comptes_a_recevoir", {**arguments, "aujourd_hui": "2026-12-03"}))
    [facture] = lendemain["factures"]
    assert (facture["statut_effectif"], facture["jours_de_retard"]) == ("EN_RETARD", 1)
    assert lendemain["en_retard"]["nombre"] == 1 and D(lendemain["en_retard"]["total"]) == D("4599.00")
    sans_date = utile(appeler(par_nom, "m5_lire_comptes_a_recevoir", arguments))
    assert sans_date["en_retard"] is None and sans_date["factures"][0]["statut_effectif"] == "ENVOYEE"
    assert etat_facture(facture_id(plan_id, 2))["statut"] == "ENVOYEE"  # le statut ENREGISTRÉ ne change pas


def test_la_relance_suit_l_echeance_propre_de_la_facture_pas_le_delai_general_de_la_politique(par_nom, declare, dep):
    plan_id = monde_a_trois_jalons(
        dep, par_nom, emettre_jalons=(1,)
    )  # acompte payable à la réception, émis le 2 novembre
    corps = utile(appeler(par_nom, "m5_preparer_relances_clients", {"aujourd_hui": "2026-11-10", "horodatage": H}))
    # échéance du jour d'émission (délai 0) : 8 jours de retard, palier 7 atteint ; le délai général de 30 jours
    # n'aurait
    # produit aucune relance avant le 9 décembre
    assert corps["creees"] == 1
    [brouillon] = corps["brouillons"]
    assert (brouillon["facture_id"], brouillon["niveau"], brouillon["jours_retard"]) == (facture_id(plan_id, 1), 1, 8)
    assert "F-01000" in brouillon["brouillon"] and "2026-11-02" in brouillon["brouillon"]


def test_une_facture_sans_echeance_garde_le_delai_general_de_la_politique(par_nom, declare, dep):
    declare({"operations": CONFIG["operations"]})  # ni numérotation ni conditions : comportement d'avant
    ligne = [
        {
            "description": "x",
            "quantite": "1",
            "unite": "forfait",
            "prix_unitaire": "600.00",
            "reference_ligne_devis": "r",
        }
    ]
    appeler(
        par_nom,
        "m5_creer_facture_brouillon",
        {
            "facture_id": "F-LEG",
            "chantier_id": "CH",
            "devis_id": "D-LEG",
            "client_id": "c",
            "lignes": ligne,
            "horodatage": H,
        },
    )
    emettre(dep, "F-LEG", horodatage="2026-11-02T10:00:00-05:00")
    avant = utile(appeler(par_nom, "m5_preparer_relances_clients", {"aujourd_hui": "2026-11-10", "horodatage": H}))
    assert avant["creees"] == 0 and avant["sans_retard"] == 1
    apres = utile(appeler(par_nom, "m5_preparer_relances_clients", {"aujourd_hui": "2026-12-10", "horodatage": H}))
    assert apres["creees"] == 1


# ------------------------------------------------------------------------------------------------- lecture du plan
def test_lire_le_plan_dit_ou_il_en_est_et_ce_qui_reste_a_declarer(par_nom, declare, dep):
    plan_id = monde_a_trois_jalons(dep, par_nom, emettre_jalons=(1,))
    corps = utile(appeler(par_nom, "m5_lire_plan_facturation", {"devis_id": "D-1", "aujourd_hui": "2026-11-05"}))
    assert corps["plan_id"] == plan_id and corps["facture_avant_taxes"] == "7000.00"  # jalons 1 et 2 ont une facture
    assert corps["solde_a_facturer_avant_taxes"] == "3000.00" and corps["a_declarer"] == []
    etats = [(j["rang"], j["etat"], j.get("numero_facture")) for j in corps["jalons"]]
    assert etats == [(1, "ENVOYEE", "F-01000"), (2, "BROUILLON", None), (3, "A_FACTURER", None)]
    assert corps["jalons"][0]["statut_effectif"] == "EN_RETARD" and corps["jalons"][0]["jours_de_retard"] == 3
    declare({"operations": CONFIG["operations"]})
    manques = utile(appeler(par_nom, "m5_lire_plan_facturation", {"devis_id": "D-1"}))["a_declarer"]
    assert {m["declaration"] for m in manques} == {
        "configuration.facturation.numerotation",
        "configuration.facturation.conditions_paiement",
        "configuration.facturation.entreprise",
    }
    assert refus(appeler(par_nom, "m5_lire_plan_facturation", {"devis_id": "D-X"}))["code"] == "REJ-PLAN-INTROUVABLE"
    assert refus(appeler(par_nom, "m5_lire_plan_facturation", {"devis_id": "D-1", "aujourd_hui": "demain"}))[
        "code"
    ] == ("REJ-FACTURATION-DATE-INVALIDE")


# ===================================================================================================== PDF (outils)
def pdf_facture(par_nom, fid, langue="fr", destinataire=DESTINATAIRE, horodatage=H):
    return appeler(
        par_nom,
        "m5_preparer_pdf_facture",
        {"facture_id": fid, "langue": langue, "destinataire": destinataire, "horodatage": horodatage},
    )


@pytest.fixture
def brique():
    from m5_financecore import facture_pdf

    installe, raison = facture_pdf.pdf_installe()
    if not installe:
        pytest.skip(raison)
    pytest.importorskip("pypdf")


def _fichier(corps):
    return stockage.dossier_opsys() / corps["fichier"]["chemin_relatif"]


def _lire_pdf(corps):
    from pypdf import PdfReader

    octets = _fichier(corps).read_bytes()
    texte = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(octets)).pages)
    return octets, " ".join(texte.replace(" ", " ").split())


def test_le_pdf_de_la_facture_approuvee_est_scelle_rejouable_et_ne_porte_aucun_envoi(par_nom, declare, dep, brique):
    plan_id = monde_a_trois_jalons(dep, par_nom, emettre_jalons=(1,))
    fid = facture_id(plan_id, 1)
    corps = utile(pdf_facture(par_nom, fid))
    octets, texte = _lire_pdf(corps)
    assert hashlib.sha256(octets).hexdigest() == corps["sha256"]
    assert corps["fichier"]["taille_octets"] == len(octets) and corps["type_mime"] == "application/pdf"
    assert "pdf_base64" not in corps  # les octets ne passent jamais par le modèle
    assert corps["fichier"]["chemin_relatif"].startswith("exports/factures/facture-F-01000-fr-")
    assert (_fichier(corps).stat().st_mode & 0o777) == 0o600
    assert corps["scelle"]["statut"] == "nouveau" and "aucun" in corps["envoi"]
    for attendu in (
        "Facture F-01000",
        "3 449,25 $",
        "N° TPS 123456789 RT0001",
        "Madame Cliente Fictive",
        "Payable à la réception",
    ):
        assert attendu in texte, attendu
    assert "mention_comptable" in corps and corps["mention"] == analyse.MENTION_ANALYSE_PREPARATOIRE
    [scelle] = registre("documents_facturation")
    assert scelle["type_entree"] == "facture_pdf_scellee" and scelle["empreinte_pdf"] == corps["sha256"]
    assert scelle["facture_id"] == fid and scelle["numero_facture"] == "F-01000"
    # rejeu : mêmes octets, même empreinte, rien d'écrit de plus
    rejeu = utile(pdf_facture(par_nom, fid, horodatage="2026-11-09T10:00:00-05:00"))
    assert rejeu["scelle"]["statut"] == "deja" and rejeu["sha256"] == corps["sha256"]
    assert rejeu["fichier"] == corps["fichier"]
    assert len(registre("documents_facturation")) == 1
    # bilingue : un autre document, un autre scellé
    bilingue = utile(pdf_facture(par_nom, fid, langue="bilingue"))
    assert bilingue["sha256"] != corps["sha256"] and len(registre("documents_facturation")) == 2


def test_le_scelle_ne_garde_ni_les_octets_ni_le_nom_ni_l_adresse_du_client(par_nom, declare, dep, brique):
    plan_id = monde_a_trois_jalons(dep, par_nom, emettre_jalons=(1,))
    utile(pdf_facture(par_nom, facture_id(plan_id, 1)))
    texte = json.dumps(registre("documents_facturation"), ensure_ascii=False)
    for personnel in ("Cliente", "avenue Exemple", "Lévis", "pdf_base64", "%PDF"):
        assert personnel not in texte
    assert "empreinte_destinataire" in texte


def test_un_scelle_qui_ne_correspond_plus_au_rendu_est_un_conflit_jamais_reecrit(par_nom, declare, dep, brique):
    plan_id = monde_a_trois_jalons(dep, par_nom, emettre_jalons=(1,))
    fid = facture_id(plan_id, 1)
    utile(pdf_facture(par_nom, fid))
    from sqlalchemy import update

    from opsys.stockage import codec
    from opsys.stockage.schema import REGISTRES

    filtre = (REGISTRES.c.departement == DEPARTEMENT) & (REGISTRES.c.registre == "documents_facturation")
    avec_chaine_valide = registre_module.Registre()
    ancien = registre("documents_facturation")[0]
    corps = {k: v for k, v in ancien.items() if k not in ("ligne_id", "precedent_ligne_id")}
    corps["empreinte_pdf"] = "0" * 64
    avec_chaine_valide.ajouter(corps)
    with stockage.transaction() as cnx:
        cnx.execute(update(REGISTRES).where(filtre).values(maillon=codec.encoder(avec_chaine_valide.lire()[0])))
    verdict = refus(pdf_facture(par_nom, fid))
    assert verdict["code"] == "REJ-PDF-SCELLE-DIFFERENT"
    assert (
        registre("documents_facturation")[0]["empreinte_pdf"] == "0" * 64
        and len(registre("documents_facturation")) == 1
    )


def test_un_fichier_du_meme_nom_aux_autres_octets_n_est_jamais_ecrase(par_nom, declare, dep, brique):
    plan_id = monde_a_trois_jalons(dep, par_nom, emettre_jalons=(1,))
    fid = facture_id(plan_id, 1)
    premier = utile(pdf_facture(par_nom, fid))
    chemin = _fichier(premier)
    original = chemin.read_bytes()
    chemin.write_bytes(b"%PDF-altere")
    stockage.liberer()
    verdict = refus(pdf_facture(par_nom, fid))
    assert verdict["code"] == "REJ-PDF-FICHIER-CONFLIT" and chemin.read_bytes() == b"%PDF-altere"
    assert len(registre("documents_facturation")) == 1
    chemin.write_bytes(original)
    assert utile(pdf_facture(par_nom, fid))["scelle"]["statut"] == "deja"


def test_le_dossier_d_export_doit_etre_un_dossier_ordinaire_jamais_un_lien(par_nom, declare, dep, brique, tmp_path):
    plan_id = monde_a_trois_jalons(dep, par_nom, emettre_jalons=(1,))
    exports = stockage.dossier_opsys() / "exports"
    exports.mkdir(parents=True, exist_ok=True)
    cible = tmp_path / "ailleurs"
    cible.mkdir()
    (exports / "factures").symlink_to(cible, target_is_directory=True)
    verdict = refus(pdf_facture(par_nom, facture_id(plan_id, 1)))
    assert verdict["code"] == "REJ-PDF-EXPORT-IMPOSSIBLE" and list(cible.iterdir()) == []
    assert registre("documents_facturation") == []


def test_le_pdf_exige_une_facture_approuvee_et_les_donnees_declarees(par_nom, declare, dep, brique):
    plan_id = monde_a_trois_jalons(dep, par_nom)  # deux brouillons, rien d'émis
    brouillon = refus(pdf_facture(par_nom, facture_id(plan_id, 1)))
    assert brouillon["code"] == "REJ-PDF-FACTURE-NON-EMISE" and "approuvée (N4)" in brouillon["detail"]
    assert refus(pdf_facture(par_nom, "inconnue"))["code"] == "REJ-PDF-FACTURE-INTROUVABLE"
    emettre(dep, facture_id(plan_id, 1))
    for retire, mot in (
        ("raison_sociale", "raison_sociale"),
        ("numero_tps", "numero_tps"),
        ("numero_tvq", "numero_tvq"),
        ("adresse", "adresse"),
    ):
        declare(
            {
                **CONFIG,
                "facturation": {**FACTURATION, "entreprise": {k: v for k, v in ENTREPRISE.items() if k != retire}},
            }
        )
        verdict = refus(pdf_facture(par_nom, facture_id(plan_id, 1)))
        assert verdict["code"] == "REJ-PDF-ENTREPRISE-A-DECLARER" and mot in verdict["detail"].split(". ")[0]
        assert "configuration.facturation.entreprise" in verdict["detail"]
    declare(
        {"operations": CONFIG["operations"], "facturation": {k: v for k, v in FACTURATION.items() if k != "entreprise"}}
    )
    assert refus(pdf_facture(par_nom, facture_id(plan_id, 1)))["code"] == "REJ-PDF-ENTREPRISE-A-DECLARER"
    assert registre("documents_facturation") == []


def test_le_pdf_valide_le_destinataire_et_la_langue(par_nom, declare, dep, brique):
    plan_id = monde_a_trois_jalons(dep, par_nom, emettre_jalons=(1,))
    fid = facture_id(plan_id, 1)
    assert (
        refus(pdf_facture(par_nom, fid, destinataire={"nom": "A", "adresse": []}))["code"]
        == "REJ-PDF-DESTINATAIRE-INVALIDE"
    )
    assert refus(pdf_facture(par_nom, fid, destinataire={"nom": "Ω", "adresse": ["a"]}))["code"] == (
        "REJ-PDF-CARACTERE-NON-SUPPORTE"
    )
    reponse = pdf_facture(par_nom, fid, langue="en")
    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides"  # fermé au schéma
    assert registre("documents_facturation") == []


def test_sans_la_brique_le_pdf_dit_quoi_installer_et_n_ecrit_aucun_scelle(par_nom, declare, dep, monkeypatch):
    from importlib import metadata

    from m5_financecore import facture_pdf

    plan_id = monde_a_trois_jalons(dep, par_nom, emettre_jalons=(1,))

    def absent(nom):
        raise metadata.PackageNotFoundError(nom)

    monkeypatch.setattr(facture_pdf.metadata, "version", absent)
    verdict = refus(pdf_facture(par_nom, facture_id(plan_id, 1)))
    assert verdict["code"] == "REJ-PDF-BRIQUE-ABSENTE" and "soumission" in verdict["detail"]
    assert registre("documents_facturation") == []


def test_l_etat_de_compte_du_client_est_scelle_et_rejouable(par_nom, declare, dep, brique):
    plan_id = monde_a_trois_jalons(dep, par_nom, emettre_jalons=(1, 2))
    client = etat_facture(facture_id(plan_id, 1))["client_id"]
    arguments = {"client_id": client, "au": "2026-12-10", "langue": "fr", "destinataire": DESTINATAIRE, "horodatage": H}
    corps = utile(appeler(par_nom, "m5_preparer_etat_compte_client", arguments))
    octets, texte = _lire_pdf(corps)
    assert corps["scelle"]["statut"] == "nouveau" and hashlib.sha256(octets).hexdigest() == corps["sha256"]
    # acompte 3449.25 (échu le 2 novembre) + jalon 2 : 4000 + 599.00 = 4599.00 (échu le 9 décembre... émis le 2
    # novembre : 2 décembre)
    for attendu in (
        "État de compte",
        "Au 10 décembre 2026",
        "F-01000",
        "F-01001",
        "En retard de 38 j",
        "En retard de 8 j",
        "8 048,25 $",
    ):
        assert attendu in texte, attendu
    rejeu = utile(appeler(par_nom, "m5_preparer_etat_compte_client", arguments))
    assert rejeu["scelle"]["statut"] == "deja" and rejeu["sha256"] == corps["sha256"]
    plus_tard = utile(appeler(par_nom, "m5_preparer_etat_compte_client", {**arguments, "au": "2026-12-11"}))
    assert plus_tard["sha256"] != corps["sha256"]
    assert refus(appeler(par_nom, "m5_preparer_etat_compte_client", {**arguments, "client_id": "autre"}))["code"] == (
        "REJ-PDF-ETAT-COMPTE-VIDE"
    )
    assert refus(appeler(par_nom, "m5_preparer_etat_compte_client", {**arguments, "au": "10 décembre"}))["code"] == (
        "REJ-FACTURATION-DATE-INVALIDE"
    )


# ------------------------------------------------------------------- rien de personnel dans le bus ni les journaux
def test_rien_de_personnel_ne_sort_ni_au_bus_ni_dans_les_journaux(par_nom, declare, dep, brique, caplog):
    import logging

    caplog.set_level(logging.DEBUG)
    plan_id = monde_a_trois_jalons(dep, par_nom, emettre_jalons=(1,))
    utile(pdf_facture(par_nom, facture_id(plan_id, 1)))
    client = etat_facture(facture_id(plan_id, 1))["client_id"]
    utile(
        appeler(
            par_nom,
            "m5_preparer_etat_compte_client",
            {"client_id": client, "au": "2026-12-10", "langue": "fr", "destinataire": DESTINATAIRE, "horodatage": H},
        )
    )
    appeler(par_nom, "m5_preparer_relances_clients", {"aujourd_hui": "2026-12-10", "horodatage": H})
    appeler(par_nom, "m5_constater_factures_emises", {"horodatage": H})
    with stockage.transaction() as cnx:
        sortants = " ".join(str(ligne.charge) for ligne in cnx.execute(select(EVENEMENTS_SORTANTS)).all())
    for personnel in ("Cliente", "avenue Exemple", "Lévis", "123456789", "1234567890", "Entreprise Fictive"):
        assert personnel not in sortants and personnel not in caplog.text, personnel
    assert (
        "m5-facture-emise" in sortants
    )  # le constat des factures émises, lui, part (identifiants opaques et montants)
