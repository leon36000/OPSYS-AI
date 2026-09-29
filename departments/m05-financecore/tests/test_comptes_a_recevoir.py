"""PLAN T1.5-d : les comptes à recevoir (DEFINITION-PRODUIT §6, M5 « met à jour les comptes à recevoir »).

Une facture entre aux comptes à recevoir quand elle est ENVOYEE, et seulement alors. Comme l'envoi est la
décision humaine N4 du socle, la facture BROUILLON créée par la cascade n'y entre jamais. Il n'y a rien à
« mettre à jour » : `facturation.comptes_a_recevoir` est une vue de l'état courant du registre des factures.

Deux niveaux : la fonction pure (registre en mémoire), puis le parcours réel par les approbations du socle
(envoi N4 décidé par `finance`, paiement N5 décidé par `nathan_owner` avec attestation). Fictif (AGENTS.md).
"""

from __future__ import annotations

import contextlib
from decimal import Decimal
from pathlib import Path

import m5_financecore.outils as m5_outils
import pytest
from m5_financecore import facturation, registre, taux_fiscaux
from sqlalchemy import select

from opsys import approbations as opsys_approbations
from opsys import contexte, identite, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.departements import lire_manifeste
from opsys.outils import executer_atomique
from opsys.stockage.schema import META

FICTIF = True
HORODATAGE = "2026-08-03T12:00:00+00:00"
_RACINE_M5 = Path(__file__).resolve().parents[1]
_CHEMIN_TAUX = _RACINE_M5 / "contracts" / "taux_fiscaux.v1.yaml"
MONTANT_DU = Decimal("689.85")  # 600,00 avant taxes + TPS 30,00 + TVQ 59,85

ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
MARC = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")
VENDEUR = contexte.IdentiteAppelante(personne="vendeur.fictif", role="seller")
ATTESTATION = {"nom": "Alex Comptable (fictif)", "profession": "CPA", "reference_document": "DEPOT-4521-fictif"}


# -- niveau 1 : la fonction pure --------------------------------------------------------------------------
def _lignes():
    return [
        {"description": "Gouttières 5po aluminium", "quantite": "40", "unite": "pi", "prix_unitaire": "8.50",
         "reference_ligne_devis": "L1"},
        {"description": "Main d'oeuvre installation", "quantite": "1", "unite": "forfait",
         "prix_unitaire": "260.00", "reference_ligne_devis": "L2"},
    ]


def _brouillon(registre_cible, facture_id, devis_id, **surcharges):
    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(_CHEMIN_TAUX)
    assert erreurs == []
    _, verdict = facturation.creer_facture_brouillon(
        facture_id=facture_id, chantier_id=f"CH-{devis_id}", devis_id=devis_id, client_id="CLIENT-1-fictif",
        lignes=_lignes(), horodatage=HORODATAGE, dictionnaire_taux=dictionnaire, registre_cible=registre_cible,
        **surcharges)
    assert verdict is None, verdict


def _envoyee(registre_cible, facture_id, devis_id, date_envoi="2026-08-03T00:00:00+00:00"):
    _brouillon(registre_cible, facture_id, devis_id)
    _, verdict = facturation.envoyer_facture(facture_id, date_envoi, registre_cible)
    assert verdict is None, verdict


def test_registre_vide_rien_a_recevoir():
    resultat, verdict = facturation.comptes_a_recevoir(registre.Registre())

    assert verdict is None
    assert resultat["factures"] == [] and resultat["nombre"] == 0
    assert resultat["total_a_recevoir"] == Decimal("0") and resultat["total_complet"] is True


def test_seule_la_facture_envoyee_entre_aux_comptes_a_recevoir():
    reg = registre.Registre()
    _brouillon(reg, "FACT-BROUILLON", "D1")
    _envoyee(reg, "FACT-ENVOYEE", "D2")
    _envoyee(reg, "FACT-PAYEE", "D3")
    facturation.marquer_facture_payee("FACT-PAYEE", "Nathan", "2026-08-10T00:00:00+00:00", reg)
    _brouillon(reg, "FACT-ANNULEE", "D4")
    reg.ajouter({"type_entree": "transition_facture", "facture_id": "FACT-ANNULEE", "statut": "ANNULEE",
                 "horodatage": HORODATAGE})

    resultat, verdict = facturation.comptes_a_recevoir(reg)

    assert verdict is None
    assert [f["facture_id"] for f in resultat["factures"]] == ["FACT-ENVOYEE"]
    (ligne,) = resultat["factures"]
    assert ligne["montant_apres_taxes"] == MONTANT_DU and ligne["client_id"] == "CLIENT-1-fictif"
    assert (ligne["chantier_id"], ligne["devis_id"], ligne["date_envoi"]) == (
        "CH-D2", "D2", "2026-08-03T00:00:00+00:00")
    assert resultat["nombre"] == 1 and resultat["total_a_recevoir"] == MONTANT_DU


def test_le_total_est_la_somme_exacte_des_montants_dus():
    reg = registre.Registre()
    for numero in range(3):
        _envoyee(reg, f"FACT-{numero}", f"D{numero}")

    resultat, _ = facturation.comptes_a_recevoir(reg)

    assert resultat["nombre"] == 3 and resultat["total_a_recevoir"] == MONTANT_DU * 3 == Decimal("2069.55")
    assert [f["facture_id"] for f in resultat["factures"]] == ["FACT-0", "FACT-1", "FACT-2"]  # ordre stable


def test_sans_date_du_jour_pas_d_age_et_la_date_n_est_jamais_devinee():
    reg = registre.Registre()
    _envoyee(reg, "FACT-1", "D1")

    resultat, _ = facturation.comptes_a_recevoir(reg)

    assert resultat["age"] is None and "jamais devinée" in resultat["age_non_calcule"]


def test_avec_la_date_du_jour_l_age_est_celui_de_calculer_age_creances():
    reg = registre.Registre()
    _envoyee(reg, "FACT-1", "D1", date_envoi="2026-08-03T00:00:00+00:00")
    _envoyee(reg, "FACT-2", "D2", date_envoi="2026-05-01T00:00:00+00:00")

    resultat, verdict = facturation.comptes_a_recevoir(reg, "2026-09-02")

    assert verdict is None and resultat["age_non_calcule"] is None
    assert resultat["age"] == facturation.calculer_age_creances(reg, "2026-09-02")[0]
    assert [f["facture_id"] for f in resultat["age"]["tranches"]["0-30"]] == ["FACT-1"]
    assert [f["facture_id"] for f in resultat["age"]["tranches"]["90+"]] == ["FACT-2"]
    assert resultat["nombre"] == 2  # l'âge ne change pas ce qui est à recevoir


@pytest.mark.parametrize("aujourd_hui", ["hier", "2026-13-45", "", 20260902])
def test_date_du_jour_invalide_refus_nomme_sans_rien_rendre(aujourd_hui):
    reg = registre.Registre()
    _envoyee(reg, "FACT-1", "D1")

    resultat, verdict = facturation.comptes_a_recevoir(reg, aujourd_hui)

    assert resultat is None and verdict["code"] == "REJ-CREANCES-AUJOURDHUI-INVALIDE"


def test_un_montant_du_illisible_n_entre_jamais_au_total():
    reg = registre.Registre()
    _envoyee(reg, "FACT-BONNE", "D1")
    _envoyee(reg, "FACT-CORROMPUE", "D2")
    reg.ajouter({"type_entree": "transition_facture", "facture_id": "FACT-CORROMPUE", "statut": "ENVOYEE",
                 "montant_apres_taxes": "beaucoup", "horodatage": HORODATAGE})

    resultat, verdict = facturation.comptes_a_recevoir(reg)

    assert verdict is None and resultat["total_complet"] is False
    assert [f["facture_id"] for f in resultat["factures"]] == ["FACT-BONNE"]
    assert resultat["total_a_recevoir"] == MONTANT_DU
    (illisible,) = resultat["illisibles"]
    assert illisible["facture_id"] == "FACT-CORROMPUE"
    assert illisible["verdict"]["code"] == "REJ-CREANCES-MONTANT-ILLISIBLE"


def test_la_vue_n_ecrit_rien():
    reg = registre.Registre()
    _envoyee(reg, "FACT-1", "D1")
    avant = reg.lire()

    facturation.comptes_a_recevoir(reg, "2026-09-02")

    assert reg.lire() == avant


def test_factures_actives_par_devis_une_relecture_meme_regle_que_facture_active_pour_devis():
    reg = registre.Registre()
    _brouillon(reg, "FACT-1", "D1")
    _envoyee(reg, "FACT-2", "D2")
    _brouillon(reg, "FACT-3", "D3")
    reg.ajouter({"type_entree": "transition_facture", "facture_id": "FACT-3", "statut": "ANNULEE",
                 "horodatage": HORODATAGE})

    actives = facturation.factures_actives_par_devis(reg)

    assert sorted(actives) == ["D1", "D2"], "une facture annulée n'est pas active"
    for devis_id, facture in actives.items():
        assert facture == facturation.facture_active_pour_devis(reg, devis_id)
    assert facturation.facture_active_pour_devis(reg, "D3") is None


# -- niveau 2 : le parcours réel par les approbations du socle -------------------------------------------
@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm5-creances.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    m5_outils.utiliser_stockage_durable()
    yield url
    stockage.liberer()


@pytest.fixture
def dep(base_durable):
    return lire_manifeste(_RACINE_M5)


@pytest.fixture
def personnes(base_durable):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "marc.fictif", "Marc Fictif", "mot-de-passe-marc-1234", ["employee"])
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur Fictif", "mot-de-passe-vendeur-123", ["seller"])
        identite.creer_personne(cnx, "financeuse", "Une Comptable (fictif)", "mot-de-passe-finance-1234",
                                ["finance"])
        identite.creer_personne(cnx, "nathan", "Nathan Propriétaire (fictif)", "mot-de-passe-nathan-1234",
                                ["nathan_owner"])


@pytest.fixture
def par_nom(personnes):
    return {o.nom: o for o in m5_outils.outils()}


@contextlib.contextmanager
def _appareil(identite_appelante):
    with contextlib.ExitStack() as pile:
        if identite_appelante is not None:
            pile.enter_context(contexte.appele_par_appareil(identite_appelante))
        yield


def _appeler(par_nom, nom, arguments, identite_appelante=None):
    with _appareil(identite_appelante):
        return executer_atomique(par_nom[nom], arguments)


def _a_recevoir(par_nom, arguments=None, identite_appelante=ADMIN):
    """Le contenu d'une lecture accordée : `{"ok", "resultat": {"accepte": vrai, "resultat": <la vue>}}`."""
    reponse = _appeler(par_nom, "m5_lire_comptes_a_recevoir", arguments or {}, identite_appelante)
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _brouillon_par_l_outil(par_nom, facture_id="FACT-SOCLE", devis_id="DEVIS-SOCLE"):
    reponse = executer_atomique(par_nom["m5_creer_facture_brouillon"], {
        "facture_id": facture_id, "chantier_id": "CHANTIER-SOCLE-fictif", "devis_id": devis_id,
        "client_id": "CLIENT-SOCLE-fictif", "lignes": _lignes(), "horodatage": HORODATAGE})
    assert reponse["ok"] and reponse["resultat"]["accepte"], reponse
    return facture_id


def test_parcours_complet_brouillon_envoyee_payee(dep, par_nom):
    """Le brouillon n'est pas à recevoir ; l'envoi décidé par `finance` (N4) l'y fait entrer ; le paiement décidé
    par `nathan_owner` (N5, attestation) l'en fait sortir. Aucune écriture d'un « compte à recevoir »."""
    facture_id = _brouillon_par_l_outil(par_nom)
    capacites = Capacites({"m05-financecore": dep}, stockage.transaction)
    outils_dispo = outils_executables({"m05-financecore": dep}, stockage.transaction)
    assert _a_recevoir(par_nom)["nombre"] == 0, "un brouillon n'est pas à recevoir"

    demande = capacites.appeler("m5_envoyer_facture", {"facture_id": facture_id, "horodatage": HORODATAGE})
    assert demande["statut"] == "en_attente_approbation"
    assert _a_recevoir(par_nom)["nombre"] == 0, "l'envoi attend une décision humaine : toujours pas à recevoir"

    with stockage.transaction() as cnx:
        opsys_approbations.decider(cnx, demande["demande_id"], True, "financeuse", outils_dispo,
                                   {"m05-financecore": dep})
    apres_envoi = _a_recevoir(par_nom, {"aujourd_hui": "2026-08-20"})
    assert apres_envoi["nombre"] == 1 and apres_envoi["total_a_recevoir"] == "689.85"
    assert apres_envoi["factures"][0]["facture_id"] == facture_id
    assert apres_envoi["age"]["tranches"]["0-30"][0]["age_jours"] == 17

    paiement = capacites.appeler("m5_enregistrer_paiement_facture", {
        "facture_id": facture_id, "montant_paye": "689.85", "approbateur": "nathan", "horodatage": HORODATAGE})
    assert paiement["statut"] == "en_attente_approbation"
    assert _a_recevoir(par_nom)["nombre"] == 1, "tant que le paiement n'est pas décidé, la facture reste due"
    with stockage.transaction() as cnx:
        opsys_approbations.decider(cnx, paiement["demande_id"], True, "nathan", outils_dispo,
                                   {"m05-financecore": dep}, attestation=ATTESTATION)
    assert _a_recevoir(par_nom)["nombre"] == 0 and _a_recevoir(par_nom)["total_a_recevoir"] == "0"


def test_la_lecture_n_ecrit_rien_dans_aucune_table(par_nom):
    _brouillon_par_l_outil(par_nom)
    avant = _instantane_base()

    _a_recevoir(par_nom, {"aujourd_hui": "2026-09-01"})

    assert _instantane_base() == avant


def _instantane_base():
    with stockage.transaction() as cnx:
        return {nom: sorted(tuple(map(str, ligne)) for ligne in cnx.execute(select(table)).fetchall())
                for nom, table in META.tables.items()}


# -- l'outil : même règle d'accès que la trésorerie ------------------------------------------------------
def test_l_admin_authentifie_lit_les_comptes_a_recevoir_sans_rien_fournir(par_nom):
    vue = _a_recevoir(par_nom)

    assert vue["role"] == "admin" and vue["nombre"] == 0 and vue["total_a_recevoir"] == "0"


@pytest.mark.parametrize("appelante", [MARC, VENDEUR], ids=["employe", "vendeur"])
@pytest.mark.parametrize("arguments", [{}, {"autorise_couts": True}, {"autorise_couts": False}],
                         ids=["rien", "veut_les_couts", "vue_sans_montant"])
def test_employe_et_vendeur_n_obtiennent_rien_et_rien_n_est_lu_ni_ecrit(
        par_nom, monkeypatch, appelante, arguments):
    _brouillon_par_l_outil(par_nom)
    avant = _instantane_base()

    def _interdit(*_args, **_kwargs):
        raise AssertionError("le registre des factures a été ouvert avant le refus")

    with monkeypatch.context() as remplacement:
        remplacement.setattr(m5_outils, "_registre_factures", _interdit)
        reponse = _appeler(par_nom, "m5_lire_comptes_a_recevoir", arguments, appelante)

    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert _instantane_base() == avant


def test_l_admin_ne_peut_que_restreindre_la_vue(par_nom):
    demande_elargie = _appeler(par_nom, "m5_lire_comptes_a_recevoir", {"role": "employee"}, ADMIN)
    assert demande_elargie["resultat"]["verdict"]["code"] == "REJ-IDENTITE-FOURNIE-DIFFERENTE"

    assert _a_recevoir(par_nom, {"autorise_couts": False}) == {"role": "admin", "nombre": 0, "montants_masques": True}


def test_sans_appareil_autorise_couts_reste_obligatoire(par_nom):
    sans = _appeler(par_nom, "m5_lire_comptes_a_recevoir", {})
    assert sans["resultat"]["verdict"]["code"] == "REJ-AUTORISE-COUTS-REQUIS"

    avec = _a_recevoir(par_nom, {"autorise_couts": True, "role": "gestionnaire"}, identite_appelante=None)
    assert avec["role"] == "gestionnaire" and avec["nombre"] == 0


def test_date_du_jour_invalide_est_un_refus_nomme_de_l_outil(par_nom):
    reponse = _appeler(par_nom, "m5_lire_comptes_a_recevoir", {"aujourd_hui": "demain"}, ADMIN)

    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-CREANCES-AUJOURDHUI-INVALIDE"


def test_aucun_montant_ne_se_passe_en_argument(par_nom):
    for argument in ({"total_a_recevoir": "0.00"}, {"factures": []}, {"montant": "1.00"}):
        assert _appeler(par_nom, "m5_lire_comptes_a_recevoir", argument, ADMIN)["erreur"] == "arguments_invalides"


def test_lecture_masquee_ne_porte_aucun_montant(dep, par_nom):
    facture_id = _brouillon_par_l_outil(par_nom)
    with stockage.transaction():
        facturation.envoyer_facture(facture_id, HORODATAGE, m5_outils._registre_factures(None))

    masque = _a_recevoir(par_nom, {"autorise_couts": False})

    assert masque == {"role": "admin", "nombre": 1, "montants_masques": True}
