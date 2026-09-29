"""PLAN T4.16-d : la prévision de trésorerie sur le VRAI socle : `m5_prevoir_tresorerie` (T0, `admin`).

Base SQLite temporaire migrée, registres durables réels (mouvements, factures clientes, comptes à payer), vrai manifeste
de M5 ou un manifeste de test qui déclare ce que le propriétaire décide (`configuration.fiscal`,
`configuration.obligations_declarees`, `configuration.prevision`). Le cas de référence est celui de `test_prevision.py`
(calculé à la main, à la cent près) : solde 20000.00 ; semaines 19885.02, 15685.02, 18013.46, 20312.96, 18464.71 et
18464.71 ; alerte en semaine 2 sous le seuil de 16000.00 ; cash libre d'aujourd'hui 10566.21, celui que
`m5_etat_tresorerie` rend aussi. Personnes, montants et identifiants fictifs (AGENTS.md).
"""

from __future__ import annotations

import contextlib
import json
from decimal import Decimal
from pathlib import Path

import m5_financecore.outils as m5_outils
import pytest
import yaml
from m5_financecore import comptes_a_payer, facturation, registre, taux_fiscaux
from m5_financecore.analyse import MENTION_ANALYSE_PREPARATOIRE as MENTION
from sqlalchemy import select

from opsys import contexte, identite, stockage
from opsys.outils import Autonomie, executer_atomique
from opsys.stockage.schema import META

FICTIF = True
D = Decimal
_RACINE_M5 = Path(__file__).resolve().parents[1]
AUJOURD_HUI = "2026-09-29"

ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
MARC = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")
VENDEUR = contexte.IdentiteAppelante(personne="vendeur.fictif", role="seller")

SEUIL = {"montant": "16000.00", "source": "décision de Nathan (fictive)", "au": "2026-09-25"}
PREVISION = {
    "horizon_semaines": 6, "seuil_alerte": SEUIL, "delai_encaissement_clients_jours": 30,
    "delai_paiement_fournisseurs_jours": 30,
    "echeances_obligations": {"paies": "2026-10-09", "das": "2026-10-15", "dettes": "2026-10-31"},
}
CONFIGURATION_COMPLETE = {
    "fiscal": {"frequence_tps_tvq": "trimestrielle", "mois_fin_exercice": 12, "taxes_remises_jusqu_au": "2026-06-30"},
    "obligations_declarees": {
        "paies": {"montant": "4200.00", "source": "brouillon de paie du 2026-09-25 (fictif)", "au": "2026-09-25"},
        "das": {"montant": "1350.75", "source": "estimation du CPA (fictive)", "au": "2026-09-25"},
        "dettes": {"montant": "800.00", "source": "relevé du prêt camion (fictif)", "au": "2026-09-01"},
    },
    "prevision": PREVISION,
}
SOLDES_DU_CAS = ["19885.02", "15685.02", "18013.46", "20312.96", "18464.71", "18464.71"]


# ------------------------------------------------------------------------------------------- installation
@pytest.fixture(autouse=True)
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm5-prevision.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    m5_outils.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "marc.fictif", "Marc Fictif", "mot-de-passe-marc-1234", ["employee"])
        identite.creer_personne(cnx, "vendeur.fictif", "Vendeur Fictif", "mot-de-passe-vendeur-123", ["seller"])
    yield url
    stockage.liberer()


@pytest.fixture
def par_nom():
    return {o.nom: o for o in m5_outils.outils()}


@pytest.fixture
def taux():
    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(m5_outils._CHEMIN_TAUX_FISCAUX)
    assert erreurs == []
    return dictionnaire


def _declarer(tmp_path, monkeypatch, configuration):
    """Le manifeste de test : ce que le propriétaire a écrit sous `configuration`, relu à chaque appel."""
    manifeste = tmp_path / "department.yaml"
    manifeste.write_text(yaml.safe_dump({"configuration": configuration}, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)
    return manifeste


@pytest.fixture
def declare(tmp_path, monkeypatch):
    return lambda configuration: _declarer(tmp_path, monkeypatch, configuration)


def _mouvement(reg, montant, type_mouvement, horodatage):
    registre.enregistrer_mouvement({"montant": D(montant), "type_mouvement": type_mouvement, "horodatage": horodatage,
                                    "classe_retention": "STANDARD", "source": "test-fictif"}, reg)


def _peupler_mouvements():
    with stockage.transaction():
        reg = m5_outils._registre_mouvements(None)
        _mouvement(reg, "25000.00", "ENCAISSEMENT", "2026-08-01T12:00:00-04:00")
        _mouvement(reg, "-5000.00", "DECAISSEMENT", "2026-08-15T12:00:00-04:00")
        _mouvement(reg, "1000.00", "PROVISION", "2026-09-10T12:00:00-04:00")


def _peupler_factures_clients(taux):
    lignes = (
        ("C-1", "D-1", "4000.00", "2026-09-14", "ENVOYEE"), ("C-2", "D-2", "2000.00", "2026-09-20", "ENVOYEE"),
        ("C-3", "D-3", "1000.00", "2026-08-20", "ENVOYEE"), ("C-4", "D-4", "500.00", "2026-09-01", "BROUILLON"),
        ("C-5", "D-5", "300.00", "2026-08-01", "PAYEE"),
    )
    with stockage.transaction():
        reg = m5_outils._registre_factures(None)
        for facture_id, devis, prix, jour, statut in lignes:
            _, verdict = facturation.creer_facture_brouillon(
                facture_id, "CH-1", devis, "C-1",
                [{"description": "travaux (fictif)", "quantite": "1", "unite": "u", "prix_unitaire": prix,
                  "reference_ligne_devis": "L-1"}], f"{jour}T09:00:00-04:00", taux, reg)
            assert verdict is None, verdict
            if statut in ("ENVOYEE", "PAYEE"):
                assert facturation.envoyer_facture(facture_id, f"{jour}T09:30:00-04:00", reg)[1] is None
            if statut == "PAYEE":
                payee = facturation.marquer_facture_payee(facture_id, "nathan", "2026-08-20T09:00:00-04:00", reg)
                assert payee[1] is None


def _charge(evenement_id, po_id, quantite, horodatage, prix="5.00"):
    return {
        "evenement_id": evenement_id, "po_id": po_id, "fournisseur_id": "gentek", "chantier_id": "CH-1",
        "horodatage_reception": horodatage, "verdict_reception": "CONFORME", "statut_po": "received",
        "hash_maillon": "a" * 64, "seuil_ecart_prix_pourcentage": 0.15,
        "lignes": [{"materiau_id": "gouttiere-5po", "quantite_demandee": quantite, "quantite_recue": quantite,
                    "prix_unitaire_prevu": prix, "devise_prevue": "CAD", "verdict_prix_po": "PRIX_LIVRE",
                    "prix_unitaire_reception": prix, "verdict_prix_reception": "PRIX_CATALOGUE",
                    "ecart_prix_critique": False}],
    }


def _peupler_a_payer(taux):
    with stockage.transaction():
        for evenement, po, quantite, horodatage in (("e-1", "PO-1", "60", "2026-09-15T09:00:00-04:00"),
                                                    ("e-2", "PO-2", "20", "2026-09-16T09:00:00-04:00"),
                                                    ("e-3", "PO-3", "100", "2026-09-17T09:00:00-04:00")):
            m5_outils._recevoir_reception_enregistree(_charge(evenement, po, quantite, horodatage))
        reg = m5_outils._registre_comptes_a_payer()
        for po, numero, jour, montant in (("PO-1", "F-1001", "2026-09-14", "300.00"),
                                          ("PO-2", "F-2001", "2026-06-20", "100.00")):
            _, verdict = comptes_a_payer.saisir_facture_fournisseur(
                po_id=po, fournisseur_id="gentek", numero_facture=numero, date_facture=jour,
                montant_avant_taxes=montant, total_facture=None, saisi_par="nathan", voie="appareil",
                horodatage="2026-09-20T10:00:00-04:00", dictionnaire_taux=taux, registre_cible=reg)
            assert verdict is None, verdict


@pytest.fixture
def cas_fictif(taux, declare):
    """Le cas de référence complet : registres durables peuplés et manifeste qui déclare tout."""
    declare(CONFIGURATION_COMPLETE)
    _peupler_mouvements()
    _peupler_factures_clients(taux)
    _peupler_a_payer(taux)


@contextlib.contextmanager
def _appareil(identite_appelante):
    with contextlib.ExitStack() as pile:
        if identite_appelante is not None:
            pile.enter_context(contexte.appele_par_appareil(identite_appelante))
        yield


def _appeler(par_nom, arguments=None, identite_appelante=ADMIN, nom="m5_prevoir_tresorerie"):
    """Un appel de l'outil de prévision (avec `aujourd_hui` sauf si l'appel le fournit) ou d'un autre outil."""
    arguments = dict(arguments or {})
    if nom == "m5_prevoir_tresorerie":
        arguments = {"aujourd_hui": AUJOURD_HUI, **arguments}
    with _appareil(identite_appelante):
        return executer_atomique(par_nom[nom], arguments)


def _prevision(par_nom, arguments=None, identite_appelante=ADMIN):
    reponse = _appeler(par_nom, arguments, identite_appelante)
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _refus(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]["code"]


def _instantane_base():
    with stockage.transaction() as cnx:
        return {nom: sorted(tuple(map(str, ligne)) for ligne in cnx.execute(select(table)).fetchall())
                for nom, table in META.tables.items()}


# ============================================================================== 1. le cas fictif, par l'outil
def test_l_outil_rend_le_cas_fictif_chiffre_a_la_cent_pres(par_nom, cas_fictif):
    page = _prevision(par_nom)

    assert page["role"] == "admin" and page["type"] == "PREVISION_TRESORERIE"
    assert [s["solde_fin"] for s in page["semaines"]] == SOLDES_DU_CAS
    assert [(s["entrees"], s["sorties"]) for s in page["semaines"]] == [
        ("0.00", "114.98"), ("0.00", "4200.00"), ("4599.00", "2270.56"), ("2299.50", "0.00"), ("0.00", "1848.25"),
        ("0.00", "0.00")]
    assert page["solde_initial"]["montant"] == "20000.00" and page["calculable"] is True
    assert page["horizon_semaines"] == 6 and page["fin_horizon"] == "2026-11-09" and page["manque"] == []
    assert [s.get("cash_libre_prevu") for s in page["semaines"]] == [
        "10566.21", "10566.21", "15165.21", "17464.71", "17464.71", "17464.71"]


def test_l_alerte_est_en_semaine_2_sous_le_seuil_du_proprietaire(par_nom, cas_fictif):
    page = _prevision(par_nom)

    assert page["alerte"] == {"statut": "ALERTE", "seuil": "16000.00", "semaines": [2], "source_du_seuil": {
        "source": "décision de Nathan (fictive)", "au": "2026-09-25"}}
    assert page["plus_bas"] == {"semaine": 2, "solde": "15685.02"}
    assert [s["semaine"] for s in page["semaines"] if s.get("sous_seuil")] == [2]
    assert "Alerte : sous le seuil de 16000.00 $ en semaine(s) 2." in page["lecture"]


def test_la_prevision_et_l_etat_de_tresorerie_disent_le_meme_solde_et_le_meme_cash_libre(par_nom, cas_fictif):
    """Une seule vérité (T4.16) : le point de départ et le cash libre sont ceux de `m5_etat_tresorerie`."""
    etat = _appeler(par_nom, {"autorise_couts": True}, ADMIN, "m5_etat_tresorerie")
    assert etat["ok"] is True
    cash = etat["resultat"]["cash_libre"]

    page = _prevision(par_nom)

    assert cash["cash_libre"] == "10566.21" and page["cash_libre_aujourd_hui"]["montant"] == "10566.21"
    assert etat["resultat"]["solde"] == page["solde_initial"]["montant"] == "20000.00"
    assert cash["solde"]["fraicheur"] == page["solde_initial"]["fraicheur"]


def test_la_mention_l_empreinte_et_les_limites_accompagnent_la_reponse(par_nom, cas_fictif):
    page = _prevision(par_nom)

    assert page["mention"] == MENTION and len(page["prevision_id"]) == 64
    assert len(page["limites"]) == 7 and any("aucune projection statistique" in ligne for ligne in page["limites"])
    assert page["reserves"] == ["REJ-AP-UNITE-PRIX-NON-CONFIRMEE"]
    assert page["encaissements_non_comptes"][0]["code"] == "REJ-PREVISION-ENCAISSEMENT-ECHU"


def test_les_lignes_de_la_semaine_3_se_lisent_avec_leur_source(par_nom, cas_fictif):
    page = _prevision(par_nom, {"semaine": 3})

    assert page["type"] == "PREVISION_TRESORERIE_SEMAINE" and page["mention"] == MENTION
    assert (page["entrees"], page["sorties"], page["solde_fin"]) == ("4599.00", "2270.56", "18013.46")
    assert [(ligne["sens"], ligne["montant"], ligne["date"]) for ligne in page["lignes"]] == [
        ("SORTIE", "344.93", "2026-10-14"), ("ENTREE", "4599.00", "2026-10-14"), ("SORTIE", "1350.75", "2026-10-15"),
        ("SORTIE", "574.88", "2026-10-17")]
    assert all(ligne["source"] and ligne["regle_de_date"] for ligne in page["lignes"])
    assert page["lignes"][0]["source"] == "facture fournisseur gentek n° F-1001 du 2026-09-14"


def test_deux_appels_donnent_la_meme_reponse_et_la_meme_empreinte(par_nom, cas_fictif):
    premiere = _prevision(par_nom)
    deuxieme = _prevision(par_nom)

    assert premiere == deuxieme and premiere["prevision_id"] == deuxieme["prevision_id"]


def test_la_configuration_est_relue_a_chaque_appel_sans_redemarrage(par_nom, cas_fictif, declare):
    avant = _prevision(par_nom)

    declare({**CONFIGURATION_COMPLETE, "prevision": {**PREVISION, "seuil_alerte": {**SEUIL, "montant": "10000.00"}}})
    apres = _prevision(par_nom)

    assert avant["alerte"]["statut"] == "ALERTE" and apres["alerte"]["statut"] == "AUCUNE"
    assert apres["alerte"]["seuil"] == "10000.00"


# ======================================================================= 2. l'horizon : jamais supposé
def test_l_horizon_est_l_argument_sinon_celui_du_proprietaire(par_nom, cas_fictif):
    assert len(_prevision(par_nom)["semaines"]) == 6
    page = _prevision(par_nom, {"horizon_semaines": 4})

    assert page["horizon_semaines"] == 4 and len(page["semaines"]) == 4 and page["fin_horizon"] == "2026-10-26"
    assert [s["solde_fin"] for s in page["semaines"]] == SOLDES_DU_CAS[:4]
    assert page["au_dela_de_l_horizon"]["sorties"] == {"nombre": 2, "total": "1848.25"}


def test_sans_horizon_ni_argument_ni_configuration_l_outil_refuse_et_dit_quoi_declarer(par_nom, cas_fictif, declare):
    declare({**CONFIGURATION_COMPLETE, "prevision": {k: v for k, v in PREVISION.items() if k != "horizon_semaines"}})

    reponse = _appeler(par_nom)

    assert _refus(reponse) == "REJ-PREVISION-HORIZON-A-CONFIGURER"
    assert "configuration.prevision.horizon_semaines" in reponse["resultat"]["verdict"]["detail"]
    assert _appeler(par_nom, {"horizon_semaines": 3})["resultat"]["accepte"] is True


@pytest.mark.parametrize("horizon", [0, 27, -1, 1000])
def test_un_horizon_hors_bornes_est_un_refus_nomme_du_code(par_nom, cas_fictif, horizon):
    """Le schéma du socle ne vérifie que les types : les bornes (1 à 26) sont celles du code, avec un verdict qui dit
    quoi corriger."""
    reponse = _appeler(par_nom, {"horizon_semaines": horizon})

    assert _refus(reponse) == "REJ-PREVISION-HORIZON-INVALIDE"
    assert "de 1 à 26" in reponse["resultat"]["verdict"]["detail"]


@pytest.mark.parametrize("horizon", ["13", 13.5, True, [13]])
def test_un_horizon_qui_n_est_pas_un_entier_est_refuse_par_le_schema_et_par_le_code(par_nom, cas_fictif, horizon):
    assert _appeler(par_nom, {"horizon_semaines": horizon})["erreur"] == "arguments_invalides"
    with _appareil(ADMIN), stockage.transaction():
        assert m5_outils.prevoir_tresorerie(AUJOURD_HUI, horizon_semaines=horizon)["verdict"]["code"] == (
            "REJ-PREVISION-HORIZON-INVALIDE"), "la fonction, appelée sans le schéma, refuse aussi"


def test_un_horizon_declare_illisible_est_refuse_meme_si_l_argument_est_omis(par_nom, cas_fictif, declare):
    declare({**CONFIGURATION_COMPLETE, "prevision": {**PREVISION, "horizon_semaines": 99}})

    assert _refus(_appeler(par_nom)) == "REJ-PREVISION-HORIZON-INVALIDE"
    assert _appeler(par_nom, {"horizon_semaines": 5})["resultat"]["accepte"] is True, "l'argument prime"


@pytest.mark.parametrize("valeur", ["2026-9-29", "29/09/2026", "", "demain", "2026-02-30", "2026-09-29T09:00:00"])
def test_aujourd_hui_illisible_est_refuse_jamais_devine(par_nom, cas_fictif, valeur):
    assert _refus(_appeler(par_nom, {"aujourd_hui": valeur})) == "REJ-PREVISION-DATE-INVALIDE"


def test_aujourd_hui_est_requis_par_le_schema(par_nom, cas_fictif):
    with _appareil(ADMIN):
        assert executer_atomique(par_nom["m5_prevoir_tresorerie"], {})["erreur"] == "arguments_invalides"


def test_aujourd_hui_change_les_semaines_et_les_echeances_le_code_n_a_pas_d_horloge(par_nom, cas_fictif):
    page = _prevision(par_nom, {"aujourd_hui": "2026-10-06"})

    # une semaine plus tard : la facture échue et les paies (10-09) sont dans la semaine 1
    assert page["aujourd_hui"] == "2026-10-06" and page["semaines"][0]["du"] == "2026-10-06"
    assert page["semaines"][0]["sorties"] == str(D("114.98") + D("4200.00"))


def test_une_semaine_apres_la_fin_de_l_horizon_est_refusee_par_le_code(par_nom, cas_fictif):
    reponse = _appeler(par_nom, {"semaine": 7, "horizon_semaines": 6})

    assert _refus(reponse) == "REJ-PREVISION-SEMAINE-INVALIDE"
    assert "de 1 à 6" in reponse["resultat"]["verdict"]["detail"]


@pytest.mark.parametrize("semaine", [0, 27, -1])
def test_une_semaine_hors_bornes_est_un_refus_nomme_du_code(par_nom, cas_fictif, semaine):
    assert _refus(_appeler(par_nom, {"semaine": semaine})) == "REJ-PREVISION-SEMAINE-INVALIDE"


def test_un_type_faux_est_refuse_par_le_schema_avant_l_outil(par_nom, cas_fictif):
    for arguments in ({"semaine": "3"}, {"depart": "0"}, {"horizon_semaines": "6"}, {"autorise_couts": "oui"},
                      {"montant": "1.00"}, {"seuil": "1.00"}, {"aujourd_hui": 20260929}):
        assert _appeler(par_nom, arguments)["erreur"] == "arguments_invalides", arguments


@pytest.mark.parametrize("semaine", [0, -2, 7, True, "3", 2.0])
def test_la_fonction_refuse_aussi_une_semaine_hostile_sans_passer_par_le_schema(par_nom, cas_fictif, semaine):
    with _appareil(ADMIN), stockage.transaction():
        reponse = m5_outils.prevoir_tresorerie(AUJOURD_HUI, horizon_semaines=6, semaine=semaine)

    assert reponse["verdict"]["code"] == "REJ-PREVISION-SEMAINE-INVALIDE"


def test_un_rang_de_depart_hors_de_la_serie_est_refuse(par_nom, cas_fictif):
    assert _refus(_appeler(par_nom, {"depart": 6})) == "REJ-PREVISION-DEPART-INVALIDE"
    assert _refus(_appeler(par_nom, {"depart": 4, "semaine": 3})) == "REJ-PREVISION-DEPART-INVALIDE"


# ==================================== 3. ce que le propriétaire décide : absent, dit quoi déclarer, rien n'est supposé
def test_avec_le_manifeste_livre_rien_n_est_declare_et_la_prevision_est_non_calculable_des_la_semaine_1(par_nom, taux):
    """Le vrai `department.yaml` : ni seuil, ni délais, ni dates de sortie, ni fréquence de production (GATE NATHAN).
    La prévision le dit code par code ; elle ne suppose rien. L'horizon est fourni en argument."""
    _peupler_mouvements()
    _peupler_factures_clients(taux)
    _peupler_a_payer(taux)

    page = _prevision(par_nom, {"horizon_semaines": 6})

    assert page["calculable"] is False and page["non_calculable_a_partir_de"] == 1
    assert {g["code"]: g["a_partir_de_semaine"] for g in page["manque"]} == {
        "REJ-CASH-DAS-A-DECLARER": 1, "REJ-CASH-DETTES-A-DECLARER": 1, "REJ-CASH-PAIE-A-DECLARER": 1,
        "REJ-FISCAL-FREQUENCE-A-DECLARER": 1, "REJ-PREVISION-DELAI-FOURNISSEURS-A-DECLARER": 1,
        "REJ-PREVISION-ECHEANCE-A-DECLARER": 1}
    assert all(s["statut"] == "NON_CALCULABLE" and "solde_fin" not in s for s in page["semaines"])
    assert page["alerte"]["statut"] == "SEUIL_A_CONFIGURER" and page["alerte"]["seuil"] is None
    assert page["alerte"]["manque"]["code"] == "REJ-PREVISION-SEUIL-A-CONFIGURER"
    assert [g["code"] for g in page["encaissements_non_comptes"]] == ["REJ-PREVISION-DELAI-CLIENTS-A-DECLARER"]
    assert page["plus_bas"] is None and page["cash_libre_aujourd_hui"]["montant"] is None
    assert page["lecture"].startswith("Prévision non calculable dès la semaine 1")


def test_le_manifeste_livre_ne_declare_aucun_reglage_de_prevision_rien_n_est_suppose():
    """GATE NATHAN : horizon, seuil, délais et dates de sortie ne sont écrits nulle part par défaut."""
    manifeste = yaml.safe_load((_RACINE_M5 / "department.yaml").read_text(encoding="utf-8"))

    assert "configuration" not in manifeste or "prevision" not in manifeste["configuration"]


@pytest.mark.parametrize("contenu", ["", "configuration: []", "configuration: 5", "[", "pas: de configuration"])
def test_un_manifeste_illisible_rend_tout_a_declarer_et_l_horizon_est_requis(par_nom, tmp_path, monkeypatch, contenu):
    manifeste = tmp_path / "department.yaml"
    manifeste.write_text(contenu, encoding="utf-8")
    monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)
    _peupler_mouvements()

    assert _refus(_appeler(par_nom)) == "REJ-PREVISION-HORIZON-A-CONFIGURER"
    page = _prevision(par_nom, {"horizon_semaines": 2})
    assert page["non_calculable_a_partir_de"] == 1 and page["alerte"]["statut"] == "SEUIL_A_CONFIGURER"


@pytest.mark.parametrize("prevision, code", [
    ({**PREVISION, "horizon_semaine": 6}, "REJ-PREVISION-CONFIGURATION-INVALIDE"),
    ([1, 2], "REJ-PREVISION-CONFIGURATION-INVALIDE"),
    ("13", "REJ-PREVISION-CONFIGURATION-INVALIDE"),
])
def test_une_configuration_de_prevision_illisible_ou_avec_une_cle_inconnue_est_refusee(
        par_nom, cas_fictif, declare, prevision, code):
    declare({**CONFIGURATION_COMPLETE, "prevision": prevision})

    reponse = _appeler(par_nom, {"horizon_semaines": 6})

    assert _refus(reponse) == code and "prevision" in reponse["resultat"]["verdict"]["detail"]


@pytest.mark.parametrize("cle, valeur, code", [
    ("delai_paiement_fournisseurs_jours", None, "REJ-PREVISION-DELAI-FOURNISSEURS-A-DECLARER"),
    ("delai_paiement_fournisseurs_jours", -3, "REJ-PREVISION-DELAI-INVALIDE"),
    ("delai_paiement_fournisseurs_jours", "30", "REJ-PREVISION-DELAI-INVALIDE"),
    ("echeances_obligations", {"paies": "2026-10-09"}, "REJ-PREVISION-ECHEANCE-A-DECLARER"),
    ("echeances_obligations", {"paies": "octobre", "das": "2026-10-15", "dettes": "2026-10-31"},
     "REJ-PREVISION-ECHEANCE-INVALIDE"),
])
def test_un_delai_ou_une_echeance_absente_ou_illisible_bloque_avec_son_code(
        par_nom, cas_fictif, declare, cle, valeur, code):
    reglages = {k: v for k, v in PREVISION.items() if k != cle}
    if valeur is not None:
        reglages[cle] = valeur
    declare({**CONFIGURATION_COMPLETE, "prevision": reglages})

    page = _prevision(par_nom)

    assert page["non_calculable_a_partir_de"] == 1 and code in {g["code"] for g in page["manque"]}


def test_un_seuil_illisible_ne_bloque_pas_les_soldes_mais_l_alerte_dit_a_configurer(par_nom, cas_fictif, declare):
    declare({**CONFIGURATION_COMPLETE, "prevision": {**PREVISION, "seuil_alerte": {"montant": "16000.00"}}})

    page = _prevision(par_nom)

    assert [s["solde_fin"] for s in page["semaines"]] == SOLDES_DU_CAS
    assert page["alerte"]["statut"] == "SEUIL_A_CONFIGURER" and page["alerte"]["manque"]["code"] == (
        "REJ-PREVISION-SEUIL-INVALIDE")


def test_sans_delai_client_les_creances_ne_sont_pas_comptees_et_les_soldes_le_disent(par_nom, cas_fictif, declare):
    declare({**CONFIGURATION_COMPLETE, "prevision": {
        k: v for k, v in PREVISION.items() if k != "delai_encaissement_clients_jours"}})

    page = _prevision(par_nom)

    assert page["calculable"] is True
    assert [s["solde_fin"] for s in page["semaines"]][:4] == ["19885.02", "15685.02", "13414.46", "13414.46"]
    assert page["encaissements_non_comptes"] == [{
        "code": "REJ-PREVISION-DELAI-CLIENTS-A-DECLARER", "nombre": 3, "montant_connu": "8048.25",
        "exemples": ["client:C-1", "client:C-2", "client:C-3"]}]


def test_les_dettes_non_declarees_bloquent_a_partir_de_la_semaine_5_les_quatre_premieres_restent_exactes(
        par_nom, cas_fictif, declare):
    declaration = {k: v for k, v in CONFIGURATION_COMPLETE["obligations_declarees"].items() if k != "dettes"}
    declare({**CONFIGURATION_COMPLETE, "obligations_declarees": declaration})

    page = _prevision(par_nom)

    assert page["non_calculable_a_partir_de"] == 5
    assert [s["solde_fin"] for s in page["semaines"][:4]] == SOLDES_DU_CAS[:4]
    assert [s["statut"] for s in page["semaines"][4:]] == ["NON_CALCULABLE", "NON_CALCULABLE"]
    assert page["manque"][0]["code"] == "REJ-CASH-DETTES-A-DECLARER" and page["manque"][0]["a_partir_de_semaine"] == 5
    assert page["alerte"]["statut"] == "ALERTE" and page["alerte"]["non_evaluee_a_partir_de"] == 5
    assert page["cash_libre_aujourd_hui"]["montant"] is None
    assert page["cash_libre_aujourd_hui"]["manque"] == ["dettes : REJ-CASH-DETTES-A-DECLARER"]


def test_une_facture_cliente_illisible_dans_les_registres_bloque_les_taxes_de_sa_periode(par_nom, cas_fictif):
    """La facture cassée (taxe illisible) est datée du 2026-08-30, dans le trimestre dû le 2 novembre (semaine 5)."""
    with stockage.transaction():
        m5_outils._registre_factures(None).ajouter({
            "type_entree": "facture_creee", "facture_id": "F-CASSEE", "chantier_id": "CH-1", "devis_id": "D-9",
            "client_id": "C-1", "lignes": [], "montant_avant_taxes": D("1.00"), "taxes": "illisible",
            "total_taxes": D("0.00"), "montant_apres_taxes": D("1.00"), "statut": "ENVOYEE",
            "date_envoi": "2026-08-30T09:00:00-04:00", "horodatage": "2026-08-30T09:00:00-04:00"})

    page = _prevision(par_nom)

    assert page["non_calculable_a_partir_de"] == 5
    groupe = next(g for g in page["manque"] if g["code"] == "REJ-CASH-FACTURE-ILLISIBLE")
    assert groupe["a_partir_de_semaine"] == 5 and groupe["exemples"] == ["taxes:2026-07-01:2026-09-30"]
    # son montant et sa date sont lisibles : c'est une créance de 1.00 due le 2026-09-29 (envoi du 08-30 + 30 jours),
    # comptée en semaine 1 ; les semaines 1 à 4 sont donc celles du cas, plus ce 1.00, à la cent près
    assert [s["solde_fin"] for s in page["semaines"][:4]] == ["19886.02", "15686.02", "18014.46", "20313.96"]
    assert all(s["statut"] == "NON_CALCULABLE" for s in page["semaines"][4:])


def test_un_taux_fiscal_illisible_rend_les_dettes_fournisseurs_non_calculables_des_la_semaine_1(
        par_nom, cas_fictif, monkeypatch):
    monkeypatch.setattr(m5_outils, "_dictionnaire_taux", lambda: (None, {
        "code": "REJ-TAUX-FICHIER-INVALIDE", "detail": "fichier illisible (test)"}))

    page = _prevision(par_nom)

    assert page["non_calculable_a_partir_de"] == 1
    groupe = next(g for g in page["manque"] if g["code"] == "REJ-TAUX-FICHIER-INVALIDE")
    assert groupe["exemples"] == ["fournisseur:inconnu"] and groupe["a_partir_de_semaine"] == 1


def test_un_calendrier_fiscal_illisible_rend_les_taxes_non_calculables(par_nom, cas_fictif, monkeypatch, tmp_path):
    calendrier = tmp_path / "calendrier.yaml"
    calendrier.write_text("schema_version: 2\n", encoding="utf-8")
    monkeypatch.setattr(m5_outils, "_CHEMIN_CALENDRIER_FISCAL", calendrier)

    page = _prevision(par_nom)

    assert page["non_calculable_a_partir_de"] == 1
    assert "REJ-CALENDRIER-INVALIDE" in {g["code"] for g in page["manque"]}


# ================================================================================ 4. les registres ne bougent jamais
def test_la_prevision_n_ecrit_rien_nulle_part_ni_mouvement_ni_paiement(par_nom, cas_fictif):
    avant = _instantane_base()

    for arguments in ({}, {"semaine": 3}, {"horizon_semaines": 26}, {"autorise_couts": False}):
        _prevision(par_nom, arguments)
    _appeler(par_nom, {"horizon_semaines": 0})

    assert _instantane_base() == avant, "ni registre, ni approbation, ni journal, ni idempotence"


def test_aucun_decaissement_n_existe_apres_la_prevision_le_registre_des_mouvements_est_intact(par_nom, cas_fictif):
    with stockage.transaction():
        avant = (m5_outils._registre_mouvements(None).taille(), m5_outils._registre_mouvements(None).tete())

    _prevision(par_nom)

    with stockage.transaction():
        reg = m5_outils._registre_mouvements(None)
        assert (reg.taille(), reg.tete()) == avant
        types = [m["type_mouvement"] for m in reg.lire() if m.get("type_entree") == "mouvement_enregistre"]
    assert types == ["ENCAISSEMENT", "DECAISSEMENT", "PROVISION"]


# =========================================================== 5. qui peut lire : l'admin authentifié, jamais l'employé
def test_l_outil_est_de_lecture_seule_reserve_a_l_admin_sans_montant_ni_date_en_argument(par_nom):
    outil = par_nom["m5_prevoir_tresorerie"]

    assert outil.autonomie == Autonomie.T0 and outil.roles_appareil == frozenset({"admin"})
    assert outil.parametres["required"] == ["aujourd_hui"] and outil.parametres["additionalProperties"] is False
    assert set(outil.parametres["properties"]) == {
        "aujourd_hui", "horizon_semaines", "semaine", "depart", "role", "autorise_couts"}
    assert "Aucune projection" in outil.description and "Analyse préparatoire" in outil.description
    assert "jamais zéro" in outil.description and "GATE NATHAN" in outil.description
    assert not {"montant", "solde", "seuil", "delai", "date_limite"} & set(outil.parametres["properties"])


@pytest.mark.parametrize("appelante", [MARC, VENDEUR], ids=["employe", "vendeur"])
def test_l_employe_et_le_vendeur_n_obtiennent_rien(par_nom, cas_fictif, appelante):
    avant = _instantane_base()

    reponse = _appeler(par_nom, {"autorise_couts": True}, appelante)

    assert _refus(reponse) == "REJ-IDENTITE-APPAREIL-INVALIDE"
    texte = json.dumps(reponse, ensure_ascii=False)
    for chiffre in ("20000.00", "15685.02", "10566.21", "4200.00"):
        assert chiffre not in texte
    assert _instantane_base() == avant


def test_un_role_different_de_celui_du_jeton_est_refuse_jamais_remplace(par_nom, cas_fictif):
    assert _refus(_appeler(par_nom, {"role": "gestionnaire"})) == "REJ-IDENTITE-FOURNIE-DIFFERENTE"
    assert _prevision(par_nom, {"role": "admin"})["role"] == "admin"


def test_un_agent_doit_demander_les_montants_explicitement(par_nom, cas_fictif):
    sans = _appeler(par_nom, {}, None)
    avec = _appeler(par_nom, {"autorise_couts": True, "role": "gestionnaire"}, None)

    assert _refus(sans) == "REJ-AUTORISE-COUTS-REQUIS"
    assert avec["resultat"]["accepte"] is True and avec["resultat"]["resultat"]["role"] == "gestionnaire"
    assert [s["solde_fin"] for s in avec["resultat"]["resultat"]["semaines"]] == SOLDES_DU_CAS


def test_sans_droit_de_voir_les_couts_aucun_montant_aucune_alerte_seulement_l_horizon(par_nom, cas_fictif):
    page = _prevision(par_nom, {"autorise_couts": False})

    assert page == {"role": "admin", "montants_masques": True, "horizon_semaines": 6, "mention": MENTION}
    assert page == _prevision(par_nom, {"autorise_couts": False, "horizon_semaines": 6})
    assert _prevision(par_nom, {"autorise_couts": False, "horizon_semaines": 3})["horizon_semaines"] == 3


@pytest.mark.parametrize("valeur", ["false", "true", "", 0, 1, [], {}])
def test_autorise_couts_n_est_jamais_interprete_par_sa_verite(par_nom, cas_fictif, valeur):
    with _appareil(ADMIN), stockage.transaction():
        reponse = m5_outils.prevoir_tresorerie(AUJOURD_HUI, autorise_couts=valeur)

    assert reponse["verdict"]["code"] == "REJ-AUTORISE-COUTS-REQUIS"


def test_les_refus_viennent_avant_toute_lecture_des_registres(par_nom, cas_fictif, monkeypatch):
    def interdit(*_args, **_kwargs):
        raise AssertionError("le registre des mouvements ne doit pas être ouvert avant l'accord")

    monkeypatch.setattr(m5_outils, "_registre_mouvements", interdit)

    assert _refus(_appeler(par_nom, {}, MARC)) == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert _refus(_appeler(par_nom, {"aujourd_hui": "hier"})) == "REJ-PREVISION-DATE-INVALIDE"
    assert _refus(_appeler(par_nom, {"role": "autre"})) == "REJ-IDENTITE-FOURNIE-DIFFERENTE"
    assert _refus(_appeler(par_nom, {}, None)) == "REJ-AUTORISE-COUTS-REQUIS"
    assert _prevision(par_nom, {"autorise_couts": False})["montants_masques"] is True


def test_une_identite_desactivee_est_refusee_avant_la_lecture(par_nom, cas_fictif):
    with stockage.transaction() as cnx:
        identite.activer(cnx, "admin.fictif", False)

    assert _refus(_appeler(par_nom)) == "REJ-IDENTITE-APPAREIL-INVALIDE"


# ======================================================================= 6. la réponse tient sous la limite du socle
def _taille(reponse):
    return len(json.dumps(reponse, ensure_ascii=False))


def test_un_horizon_de_13_semaines_tient_sous_la_limite_du_socle(par_nom, cas_fictif):
    reponse = _appeler(par_nom, {"horizon_semaines": 13})

    assert reponse["resultat"]["accepte"] is True and _taille(reponse) <= 6000
    assert reponse["resultat"]["resultat"]["prochain_depart"] is None


def test_un_horizon_de_26_semaines_se_lit_page_par_page_sans_jamais_depasser_la_limite(par_nom, cas_fictif):
    semaines = []
    depart = 0
    while depart is not None:
        reponse = _appeler(par_nom, {"horizon_semaines": 26, "depart": depart})
        assert _taille(reponse) <= 6000
        page = reponse["resultat"]["resultat"]
        semaines.extend(page["semaines"])
        depart = page["prochain_depart"]
    assert [s["semaine"] for s in semaines] == list(range(1, 27))
    assert semaines[-1]["du"] == "2027-03-23"


def test_la_premiere_page_de_26_semaines_dit_qu_il_en_reste_et_ou_reprendre(par_nom, cas_fictif):
    page = _prevision(par_nom, {"horizon_semaines": 26})

    assert page["total"] == 26 and 0 < page["affichees"] < 26 and page["prochain_depart"] == page["affichees"]
    assert page["reste"] == 26 - page["affichees"] and f"depart={page['prochain_depart']}" in page["message"]


# =========================================== 7. les bornes que la mutation ciblée a montrées (adaptateur de l'outil)
def test_un_calendrier_fiscal_illisible_dit_le_motif_du_chargeur_pas_un_texte_de_repli(
        par_nom, cas_fictif, monkeypatch, tmp_path):
    calendrier = tmp_path / "calendrier.yaml"
    calendrier.write_text("schema_version: 2\n", encoding="utf-8")
    monkeypatch.setattr(m5_outils, "_CHEMIN_CALENDRIER_FISCAL", calendrier)

    page = _prevision(par_nom)

    groupe = next(g for g in page["manque"] if g["code"] == "REJ-CALENDRIER-INVALIDE")
    assert groupe["detail"] and "n'a pas pu être lu" not in groupe["detail"]


def test_les_lignes_d_une_semaine_se_lisent_page_par_page_sans_jamais_depasser_la_limite(par_nom, cas_fictif, taux):
    """Trente factures envoyées le même jour tombent la même semaine que les quatre du cas : 34 lignes, trop pour une
    réponse de 6 000 caractères."""
    with stockage.transaction():
        reg = m5_outils._registre_factures(None)
        for k in range(30):
            identifiant = f"X-{k:02d}"
            _, verdict = facturation.creer_facture_brouillon(
                identifiant, "CH-1", f"DX-{k:02d}", "C-1",
                [{"description": "travaux (fictif)", "quantite": "1", "unite": "u", "prix_unitaire": "10.00",
                  "reference_ligne_devis": "L-1"}], "2026-09-14T09:00:00-04:00", taux, reg)
            assert verdict is None, verdict
            assert facturation.envoyer_facture(identifiant, "2026-09-14T09:30:00-04:00", reg)[1] is None

    lignes, pages, depart = [], 0, 0
    while depart is not None:
        reponse = _appeler(par_nom, {"semaine": 3, "depart": depart})
        assert _taille(reponse) <= 6000
        page = reponse["resultat"]["resultat"]
        lignes.extend(page["lignes"])
        depart = page["prochain_depart"]
        pages += 1

    assert pages > 1 and len(lignes) == 34 and len({ligne["id"] for ligne in lignes}) == 34


def test_toute_la_prevision_part_d_un_seul_instantane_du_manifeste(par_nom, cas_fictif, monkeypatch):
    """Le manifeste peut changer entre deux lectures : la prévision lit ce que le propriétaire a décidé UNE fois (le
    seuil, l'horizon, les délais, les montants déclarés et la fiscalité viennent de la même version)."""
    lectures = []

    def lire_le_manifeste():
        lectures.append(1)
        return CONFIGURATION_COMPLETE if len(lectures) == 1 else {}

    monkeypatch.setattr(m5_outils, "_configuration_manifeste", lire_le_manifeste)

    page = _prevision(par_nom)

    assert [s["solde_fin"] for s in page["semaines"]] == SOLDES_DU_CAS and page["alerte"]["statut"] == "ALERTE"
    assert len(lectures) == 1


def test_un_employe_n_apprend_rien_de_la_configuration_les_refus_d_identite_passent_avant(par_nom, cas_fictif, declare):
    """Sans horizon déclaré, l'admin apprend quoi déclarer ; l'employé, le vendeur et un rôle usurpé n'apprennent que
    leur refus : ni l'état de la configuration, ni la validité de leurs arguments ne sont dits avant l'identité."""
    declare({**CONFIGURATION_COMPLETE, "prevision": {k: v for k, v in PREVISION.items() if k != "horizon_semaines"}})

    assert _refus(_appeler(par_nom)) == "REJ-PREVISION-HORIZON-A-CONFIGURER"
    assert _refus(_appeler(par_nom, identite_appelante=MARC)) == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert _refus(_appeler(par_nom, {"aujourd_hui": "demain"}, VENDEUR)) == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert _refus(_appeler(par_nom, {"role": "employee", "horizon_semaines": 99})) == (
        "REJ-IDENTITE-FOURNIE-DIFFERENTE")


def test_le_cash_libre_de_l_etat_nomme_les_registres_lus_par_composante(par_nom, cas_fictif):
    etat = _appeler(par_nom, {"autorise_couts": True}, ADMIN, "m5_etat_tresorerie")
    cash = etat["resultat"]["cash_libre"]

    composantes = {c["id"]: [r["registre"] for r in c["source"].get("registres", [])] for c in cash["composantes"]}

    assert composantes["comptes_a_payer"] == ["comptes_a_payer"]
    assert composantes["taxes_a_remettre"] == ["factures", "comptes_a_payer"]
    assert [r["registre"] for r in cash["solde"]["source"]["registres"]] == ["mouvements"]
