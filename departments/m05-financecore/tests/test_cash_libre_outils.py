"""PLAN T4.16 : le cash libre et le calendrier fiscal sur le VRAI socle : `m5_etat_tresorerie` (évolution ADDITIVE :
le cash libre et sa décomposition accompagnent toujours `argent_disponible`) et `m5_lire_echeances_fiscales` (T0,
`admin`).

Base SQLite temporaire migrée, registres durables réels (mouvements, factures clients, comptes à payer), vrai
manifeste de M5 ou un manifeste de test qui déclare ce que le propriétaire décide (`configuration.fiscal`,
`configuration.obligations_declarees`). Le cas de référence est celui de `test_cash_libre.py` (calculé à la main) :
solde 37654.33, taxes 1981.69, paies 4200.00, DAS 1350.75, comptes à payer 459.91, dettes 800.00, réserves 1000.00,
cash libre 27861.98. Personnes, montants et identifiants fictifs (AGENTS.md).
"""

from __future__ import annotations

import contextlib
import json
from decimal import Decimal
from pathlib import Path

import m5_financecore.outils as m5_outils
import pytest
import yaml
from m5_financecore import (
    calendrier_fiscal,
    comptes_a_payer,
    etat_financier,
    facturation,
    registre,
    taux_fiscaux,
)
from m5_financecore.analyse import MENTION_ANALYSE_PREPARATOIRE as MENTION
from sqlalchemy import select

from opsys import contexte, identite, stockage
from opsys.capacites import Capacites
from opsys.departements import lire_manifeste
from opsys.outils import Autonomie, executer_atomique
from opsys.stockage.schema import META

FICTIF = True
D = Decimal
_RACINE_M5 = Path(__file__).resolve().parents[1]
DEPARTEMENT = "m05-financecore"
AUJOURD_HUI = "2026-09-29"

ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
MARC = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")
VENDEUR = contexte.IdentiteAppelante(personne="vendeur.fictif", role="seller")

CONFIGURATION_COMPLETE = {
    "fiscal": {"frequence_tps_tvq": "trimestrielle", "mois_fin_exercice": 12, "taxes_remises_jusqu_au": "2026-06-30"},
    "obligations_declarees": {
        "paies": {"montant": "4200.00", "source": "brouillon de paie du 2026-09-25 (fictif)", "au": "2026-09-25"},
        "das": {"montant": "1350.75", "source": "estimation du CPA (fictive)", "au": "2026-09-25"},
        "dettes": {"montant": "800.00", "source": "relevé du prêt camion (fictif)", "au": "2026-09-01"},
    },
}


# ------------------------------------------------------------------------------------------- installation
@pytest.fixture(autouse=True)
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm5-cash-libre.db'}"
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


def _mouvement(reg, montant, type_mouvement, horodatage="2026-08-01T12:00:00-04:00"):
    registre.enregistrer_mouvement({"montant": D(montant), "type_mouvement": type_mouvement, "horodatage": horodatage,
                                    "classe_retention": "STANDARD", "source": "test-fictif"}, reg)


def _peupler_mouvements():
    with stockage.transaction():
        reg = m5_outils._registre_mouvements(None)
        _mouvement(reg, "50000.00", "ENCAISSEMENT")
        _mouvement(reg, "-12345.67", "DECAISSEMENT", "2026-08-15T12:00:00-04:00")
        _mouvement(reg, "1000.00", "PROVISION", "2026-09-10T12:00:00-04:00")


def _peupler_factures_clients(taux):
    lignes = (
        ("F-1", "D-1", "10000.00", "2026-07-15", "ENVOYEE"), ("F-2", "D-2", "3333.33", "2026-08-20", "PAYEE"),
        ("F-3", "D-3", "1000.00", "2026-06-10", "ENVOYEE"), ("F-4", "D-4", "500.00", "2026-09-01", "BROUILLON"),
        ("F-5", "D-5", "200.00", "2026-07-01", "ENVOYEE"), ("F-6", "D-6", "100.00", "2026-06-30", "ENVOYEE"),
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
                payee = facturation.marquer_facture_payee(facture_id, "nathan", "2026-09-05T09:00:00-04:00", reg)
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
                                                    ("e-2", "PO-2", "20", "2026-09-16T09:00:00-04:00")):
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


def _appeler(par_nom, nom, arguments, identite_appelante=ADMIN):
    with _appareil(identite_appelante):
        return executer_atomique(par_nom[nom], arguments)


def _etat(par_nom, arguments=None, identite_appelante=ADMIN):
    reponse = _appeler(par_nom, "m5_etat_tresorerie", arguments or {}, identite_appelante)
    assert reponse["ok"] is True and "verdict" not in reponse["resultat"], reponse
    return reponse["resultat"]


def _cash(par_nom, arguments=None, identite_appelante=ADMIN):
    return _etat(par_nom, arguments, identite_appelante)["cash_libre"]


def _composantes(cash):
    return {c["id"]: c for c in cash["composantes"]}


def _manques(cash):
    """Le manque de la vue, par composante : `{"paies": "REJ-CASH-PAIE-A-DECLARER", ...}`."""
    return dict(ligne.split(" : ") for ligne in cash["manque"])


def _echeances(par_nom, arguments=None, identite_appelante=ADMIN):
    reponse = _appeler(par_nom, "m5_lire_echeances_fiscales",
                       {"aujourd_hui": AUJOURD_HUI, **(arguments or {})}, identite_appelante)
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _instantane_base():
    with stockage.transaction() as cnx:
        return {nom: sorted(tuple(map(str, ligne)) for ligne in cnx.execute(select(table)).fetchall())
                for nom, table in META.tables.items()}


# ======================================================================= 1. le cas fictif, par l'outil
def test_l_outil_rend_le_cas_fictif_chiffre_a_la_cent_pres(par_nom, cas_fictif):
    etat = _etat(par_nom)
    cash = etat["cash_libre"]

    assert etat["solde"] == "37654.33" and etat["argent_disponible"] == "36654.33"
    assert cash["cash_libre"] == "27861.98" and cash["calculable"] is True and cash["en_deficit"] is False
    assert cash["solde"]["montant"] == "37654.33"
    assert {cid: c["montant"] for cid, c in _composantes(cash).items()} == {
        "taxes_a_remettre": "1981.69", "paies": "4200.00", "das": "1350.75",
        "comptes_a_payer": "459.91", "dettes": "800.00", "reserves": "1000.00",
    }
    assert cash["manque"] == [] and cash["reserves"] == ["REJ-AP-UNITE-PRIX-NON-CONFIRMEE"]
    assert cash["lecture"].startswith("Cash libre : 27861.98 $")


def test_le_detail_des_taxes_du_cas_fictif(par_nom, cas_fictif):
    detail = _composantes(_cash(par_nom))["taxes_a_remettre"]["detail"]

    assert detail["depuis"] == "2026-07-01" and detail["a_remettre"] == "1981.69"
    assert detail["tps"]["nette"] == "661.67" and detail["tvq"]["nette"] == "1320.02"
    assert (detail["factures_clients"], detail["factures_fournisseurs"]) == (3, 1)


def test_chaque_composante_de_l_outil_porte_sa_source_et_sa_fraicheur(par_nom, cas_fictif):
    cash = _cash(par_nom)

    for composante in [cash["solde"], *cash["composantes"]]:
        assert composante["source"]["de"] and composante["fraicheur"]["derniere_piece"]
        assert composante["fraicheur"]["pieces"] >= 1
    par_id = _composantes(cash)
    assert cash["solde"]["fraicheur"] == {"derniere_piece": "2026-09-10T12:00:00-04:00", "pieces": 3}
    assert par_id["comptes_a_payer"]["fraicheur"]["derniere_piece"] == "2026-09-20T10:00:00-04:00"
    assert par_id["paies"]["source"]["de"].startswith("déclaration du propriétaire")
    registres = {r["registre"] for r in par_id["taxes_a_remettre"]["source"]["registres"]}
    assert registres == {"factures", "comptes_a_payer"}


def test_la_mention_obligatoire_et_les_hypotheses_accompagnent_la_reponse(par_nom, cas_fictif):
    etat = _etat(par_nom)

    assert etat["mention"] == MENTION and etat["cash_libre"]["mention"] == MENTION
    assert len(etat["cash_libre"]["hypotheses"]) == 6
    assert "cash libre" in etat["argent_disponible_note"] and "PAS" in etat["argent_disponible_note"]


# ======================================= 2. non-régression : CA-M5-05, CA-M5-06 et le contrat gelé de l'état
def test_le_contrat_gele_de_l_etat_financier_n_a_pas_bouge(par_nom, cas_fictif):
    """`ETAT_FINANCIER` v1 : mêmes clés, mêmes valeurs, même `etat_id` que la fonction pure ; T4.16 n'ajoute que des
    clés sœurs (`cash_libre`, `argent_disponible_note`, `mention`)."""
    etat = _etat(par_nom)
    reg = registre.Registre()
    _mouvement(reg, "50000.00", "ENCAISSEMENT")
    _mouvement(reg, "-12345.67", "DECAISSEMENT")
    _mouvement(reg, "1000.00", "PROVISION")
    pur = etat_financier.construire_etat_financier(reg, [], role="admin", autorise_couts=True)

    gele = {cle: etat[cle] for cle in ("type", "role", "taux_utilises", "etat_id")}
    assert gele == {cle: pur[cle] for cle in gele}
    assert (etat["solde"], etat["argent_disponible"]) == ("37654.33", "36654.33")
    assert (D(etat["solde"]), D(etat["argent_disponible"])) == (pur["solde"], pur["argent_disponible"])
    assert set(etat) - set(pur) == {"cash_libre", "argent_disponible_note", "mention"}


def test_l_argent_disponible_reste_solde_moins_reserves_quoi_que_disent_les_autres_obligations(par_nom, cas_fictif):
    """CA-M5-06 : `argent_disponible` = solde - PROVISION, indifférent aux taxes, paies, comptes à payer : ce n'est
    pas le cash libre, et ce n'est plus jamais affiché seul."""
    etat = _etat(par_nom)

    assert D(etat["solde"]) - D("1000.00") == D(etat["argent_disponible"])
    assert D(etat["cash_libre"]["cash_libre"]) < D(etat["argent_disponible"])


# ================================== 3. « disponible » n'est jamais affiché sans la décomposition (ni sans droit)
@pytest.mark.parametrize("scenario", ["cas_fictif", "registres_vides", "sans_configuration", "mouvements_seuls"])
def test_argent_disponible_n_est_jamais_affiche_sans_la_decomposition(request, par_nom, taux, declare, scenario):
    if scenario == "cas_fictif":
        request.getfixturevalue("cas_fictif")
    elif scenario == "sans_configuration":
        _peupler_mouvements()
        _peupler_factures_clients(taux)
    elif scenario == "mouvements_seuls":
        declare(CONFIGURATION_COMPLETE)
        _peupler_mouvements()

    etat = _etat(par_nom)

    assert etat["argent_disponible"] is not None
    cash = etat["cash_libre"]
    assert cash is not None and [c["id"] for c in cash["composantes"]] == [
        "taxes_a_remettre", "paies", "das", "comptes_a_payer", "dettes", "reserves"]
    assert etat["argent_disponible_note"] and etat["mention"] == MENTION


def test_sans_droit_de_voir_les_couts_ni_argent_disponible_ni_cash_libre(par_nom, cas_fictif):
    masque = _etat(par_nom, {"autorise_couts": False})

    assert masque["solde"] is None and masque["argent_disponible"] is None and masque["cash_libre"] is None
    assert "argent_disponible_note" not in masque and masque["mention"] == MENTION
    texte = json.dumps(masque, ensure_ascii=False)
    for chiffre in ("37654.33", "36654.33", "27861.98", "1981.69", "4200.00", "459.91"):
        assert chiffre not in texte


@pytest.mark.parametrize("appelante", [MARC, VENDEUR])
def test_l_employe_et_le_vendeur_ne_voient_ni_l_un_ni_l_autre(par_nom, cas_fictif, appelante):
    reponse = _appeler(par_nom, "m5_etat_tresorerie", {}, appelante)

    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert "27861.98" not in json.dumps(reponse) and "cash_libre" not in json.dumps(reponse)


def test_un_agent_doit_demander_les_montants_explicitement(par_nom, cas_fictif):
    sans = _appeler(par_nom, "m5_etat_tresorerie", {}, None)
    avec = _appeler(par_nom, "m5_etat_tresorerie", {"autorise_couts": True, "role": "gestionnaire"}, None)

    assert sans["resultat"]["verdict"]["code"] == "REJ-AUTORISE-COUTS-REQUIS"
    assert avec["resultat"]["cash_libre"]["cash_libre"] == "27861.98"


# ==================================== 4. une composante inconnue : « non calculable, manque X », jamais zéro
def test_avec_le_manifeste_livre_rien_n_est_declare_et_le_cash_libre_n_est_pas_calculable(par_nom, taux):
    """Le vrai `department.yaml` : aucune fréquence, aucune remise, aucune déclaration (GATE NATHAN). Le cash libre le
    dit composante par composante ; il ne suppose rien."""
    _peupler_mouvements()
    _peupler_factures_clients(taux)
    _peupler_a_payer(taux)

    cash = _cash(par_nom)
    par_id = _composantes(cash)

    assert cash["cash_libre"] is None and cash["calculable"] is False and cash["en_deficit"] is None
    assert _manques(cash) == {
        "taxes_a_remettre": "REJ-FISCAL-FREQUENCE-A-DECLARER", "paies": "REJ-CASH-PAIE-A-DECLARER",
        "das": "REJ-CASH-DAS-A-DECLARER", "dettes": "REJ-CASH-DETTES-A-DECLARER"}
    for cle in ("taxes_a_remettre", "paies", "das", "dettes"):
        assert par_id[cle]["statut"] == "NON_CALCULABLE" and par_id[cle]["montant"] is None, cle
    assert par_id["comptes_a_payer"]["montant"] == "459.91" and par_id["reserves"]["montant"] == "1000.00"
    # 37654.33 - 459.91 - 1000.00 : les inconnus (taxes, paies, DAS, dettes) ne sont pas comptés comme zéro
    assert cash["au_plus"] == "36194.42"
    assert "PAS de l'argent disponible" in cash["lecture"]


def test_un_registre_sans_mouvement_n_a_pas_de_solde_connu(par_nom, declare):
    declare(CONFIGURATION_COMPLETE)

    etat = _etat(par_nom)

    assert etat["solde"] == "0", "le contrat gelé de l'état garde son comportement d'avant (CA-M5-05)"
    cash = etat["cash_libre"]
    assert cash["solde"]["statut"] == "NON_CALCULABLE" and cash["solde"]["montant"] is None
    assert cash["solde"]["manque"][0]["code"] == "REJ-CASH-SOLDE-ABSENT"
    assert cash["cash_libre"] is None and cash["au_plus"] is None


@pytest.mark.parametrize("fiscal, code", [
    ({}, "REJ-FISCAL-FREQUENCE-A-DECLARER"),
    ({"frequence_tps_tvq": "trimestrielle"}, "REJ-FISCAL-FIN-EXERCICE-A-DECLARER"),
    ({"frequence_tps_tvq": "annuelle", "mois_fin_exercice": 12}, "REJ-FISCAL-STATUT-INSCRIT-A-DECLARER"),
    ({"frequence_tps_tvq": "hebdomadaire"}, "REJ-FISCAL-CONFIGURATION-INVALIDE"),
    ({"frequence_tps_tvq": "trimestrielle", "mois_fin_exercice": 12}, "REJ-FISCAL-REMISE-A-DECLARER"),
    ({"frequence_tps_tvq": "trimestrielle", "mois_fin_exercice": 12, "taxes_remises_jusqu_au": "2026-06-29"},
     "REJ-FISCAL-REMISE-HORS-PERIODE"),
    ({"frequence_tps_tvq": "trimestrielle", "mois_fin_exercice": 12, "taxes_remises_jusqu_au": "2024-12-31"},
     "REJ-CALENDRIER-ANNEE-NON-DECLAREE"),
    ({"frequence_tps_tvq": "trimestrielle", "mois_fin_exercice": 12, "taxes_remises_jusqu_au": "juin"},
     "REJ-FISCAL-DATE-INVALIDE"),
    ({"frequence_tps_tvq": "mensuelle", "taxes_remises_jusqu_au": "2026-06-30"}, None),
    ({"frequence_tps_tvq": "annuelle", "mois_fin_exercice": 12, "particulier_en_affaires": True,
      "taxes_remises_jusqu_au": "2025-12-31"}, None),
])
def test_les_taxes_a_remettre_sont_non_calculables_sans_les_decisions_du_proprietaire(par_nom, declare, taux, fiscal,
                                                                                       code):
    declare({**CONFIGURATION_COMPLETE, "fiscal": fiscal})
    _peupler_mouvements()
    _peupler_factures_clients(taux)
    _peupler_a_payer(taux)

    taxes = _composantes(_cash(par_nom))["taxes_a_remettre"]

    if code is None:
        assert taxes["statut"] == "CALCULE" and taxes["montant"] is not None
    else:
        assert taxes["statut"] == "NON_CALCULABLE" and taxes["montant"] is None
        assert [m["code"] for m in taxes["manque"]] == [code]


def test_une_date_yaml_sans_guillemets_n_est_jamais_reinterpretee(par_nom, tmp_path, monkeypatch, taux):
    manifeste = tmp_path / "department.yaml"
    manifeste.write_text(
        "configuration:\n  fiscal:\n    frequence_tps_tvq: trimestrielle\n    mois_fin_exercice: 12\n"
        "    taxes_remises_jusqu_au: 2026-06-30\n", encoding="utf-8")
    monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)
    _peupler_mouvements()

    taxes = _composantes(_cash(par_nom))["taxes_a_remettre"]

    assert taxes["montant"] is None and taxes["manque"][0]["code"] == "REJ-FISCAL-DATE-INVALIDE"
    assert "entre guillemets" in taxes["manque"][0]["detail"]


@pytest.mark.parametrize("contenu", ["", "configuration: []", "configuration: 5", "[", "pas: de configuration"])
def test_un_manifeste_illisible_ou_sans_configuration_rend_tout_a_declarer_sans_planter(par_nom, tmp_path, monkeypatch,
                                                                                         contenu):
    manifeste = tmp_path / "department.yaml"
    manifeste.write_text(contenu, encoding="utf-8")
    monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)
    _peupler_mouvements()

    cash = _cash(par_nom)

    assert cash["cash_libre"] is None
    assert set(_manques(cash)) == {"taxes_a_remettre", "paies", "das", "dettes"}


@pytest.mark.parametrize("obligations", ["oups", 5, [], [{"paies": "1.00"}]])
def test_des_obligations_declarees_qui_ne_sont_pas_un_dictionnaire_sont_ignorees_jamais_devinees(par_nom, declare,
                                                                                                    obligations):
    declare({"fiscal": CONFIGURATION_COMPLETE["fiscal"], "obligations_declarees": obligations})
    _peupler_mouvements()

    cash = _cash(par_nom)

    assert cash["cash_libre"] is None
    assert _manques(cash) == {"paies": "REJ-CASH-PAIE-A-DECLARER", "das": "REJ-CASH-DAS-A-DECLARER",
                              "dettes": "REJ-CASH-DETTES-A-DECLARER"}


def test_un_manifeste_absent_rend_tout_a_declarer(par_nom, tmp_path, monkeypatch):
    monkeypatch.setattr(m5_outils, "_MANIFESTE", tmp_path / "inexistant.yaml")
    _peupler_mouvements()

    assert _cash(par_nom)["cash_libre"] is None


@pytest.mark.parametrize("declaration", [
    {"montant": "12.5.0", "source": "x", "au": "2026-09-01"},
    {"montant": "-1.00", "source": "x", "au": "2026-09-01"},
    {"montant": "1.00", "source": "x"},
    "1.00",
])
def test_une_declaration_illisible_dans_le_manifeste_est_nommee_jamais_corrigee(par_nom, declare, taux, declaration):
    declare({**CONFIGURATION_COMPLETE, "obligations_declarees": {
        **CONFIGURATION_COMPLETE["obligations_declarees"], "das": declaration}})
    _peupler_mouvements()

    das = _composantes(_cash(par_nom))["das"]

    assert das["montant"] is None and das["manque"][0]["code"] == "REJ-CASH-DECLARATION-INVALIDE"


def test_un_zero_declare_par_le_proprietaire_avec_sa_source_est_un_zero_connu(par_nom, declare, taux):
    declaration = {"montant": "0.00", "source": "aucun employé au 2026-09-28 (fictif)", "au": "2026-09-28"}
    declare({**CONFIGURATION_COMPLETE, "obligations_declarees": {
        **CONFIGURATION_COMPLETE["obligations_declarees"], "paies": declaration, "das": declaration}})
    _peupler_mouvements()
    _peupler_factures_clients(taux)
    _peupler_a_payer(taux)

    cash = _cash(par_nom)

    # 37654.33 - 1981.69 (taxes) - 0.00 (paies) - 0.00 (DAS) - 459.91 - 800.00 (dettes) - 1000.00 = 33412.73
    assert _composantes(cash)["paies"]["montant"] == "0.00" and _composantes(cash)["das"]["montant"] == "0.00"
    assert cash["cash_libre"] == "33412.73"


def test_sans_reserve_au_registre_la_reserve_declaree_par_le_proprietaire_est_retranchee(par_nom, declare, taux):
    """Aucun mouvement de réserve : la déclaration du propriétaire (`obligations_declarees.reserves`) prend le relais,
    avec sa source. Sans elle : « à déclarer ». Aucune réserve posée n'est pas la décision de n'en avoir aucune."""
    with stockage.transaction():
        reg = m5_outils._registre_mouvements(None)
        _mouvement(reg, "50000.00", "ENCAISSEMENT")
        _mouvement(reg, "-12345.67", "DECAISSEMENT", "2026-08-15T12:00:00-04:00")
    _peupler_factures_clients(taux)
    _peupler_a_payer(taux)
    reserves = {"montant": "2500.00", "source": "décision de Nathan, fonds de roulement (fictif)", "au": "2026-09-01"}

    declare(CONFIGURATION_COMPLETE)
    sans = _composantes(_cash(par_nom))["reserves"]
    declare({**CONFIGURATION_COMPLETE, "obligations_declarees": {
        **CONFIGURATION_COMPLETE["obligations_declarees"], "reserves": reserves}})
    cash = _cash(par_nom)

    assert sans["montant"] is None and sans["manque"][0]["code"] == "REJ-CASH-RESERVES-A-DECLARER"
    assert _composantes(cash)["reserves"]["montant"] == "2500.00"
    assert "décision de Nathan" in _composantes(cash)["reserves"]["source"]["de"]
    # 37654.33 - 1981.69 (taxes) - 4200.00 (paies) - 1350.75 (DAS) - 459.91 - 800.00 (dettes) - 2500.00 = 26361.98
    assert cash["cash_libre"] == "26361.98"


# ===================================================== 5. les sources défaillantes ne plantent rien
def test_un_calendrier_invalide_rend_les_taxes_non_calculables_et_l_etat_reste_lisible(par_nom, cas_fictif, tmp_path,
                                                                                        monkeypatch):
    mauvais = tmp_path / "calendrier.yaml"
    mauvais.write_text("schema_version: 2\n", encoding="utf-8")
    monkeypatch.setattr(m5_outils, "_CHEMIN_CALENDRIER_FISCAL", mauvais)

    etat = _etat(par_nom)

    taxes = _composantes(etat["cash_libre"])["taxes_a_remettre"]
    assert taxes["montant"] is None and taxes["manque"][0]["code"] == "REJ-CALENDRIER-INVALIDE"
    assert etat["solde"] == "37654.33" and etat["cash_libre"]["cash_libre"] is None
    reponse = _appeler(par_nom, "m5_lire_echeances_fiscales", {"aujourd_hui": AUJOURD_HUI})
    assert reponse["resultat"]["verdict"]["code"] == "REJ-CALENDRIER-INVALIDE"


def test_un_fichier_de_taux_invalide_rend_les_comptes_a_payer_non_calculables(par_nom, cas_fictif, tmp_path,
                                                                                 monkeypatch):
    mauvais = tmp_path / "taux.yaml"
    mauvais.write_text("schema_version: 2\n", encoding="utf-8")
    monkeypatch.setattr(m5_outils, "_CHEMIN_TAUX_FISCAUX", mauvais)

    ap = _composantes(_cash(par_nom))["comptes_a_payer"]

    assert ap["montant"] is None and ap["manque"][0]["code"] == "REJ-TAUX-FICHIER-INVALIDE"


def test_une_facture_cliente_dont_la_taxe_est_illisible_rend_les_taxes_non_calculables(par_nom, cas_fictif, taux):
    with stockage.transaction():
        reg = m5_outils._registre_factures(None)
        reg.ajouter({"type_entree": "facture_creee", "facture_id": "F-CASSEE", "chantier_id": "CH-1", "devis_id": "D-9",
                     "client_id": "C-1", "lignes": [], "montant_avant_taxes": D("1.00"), "taxes": "illisible",
                     "total_taxes": D("0.00"), "montant_apres_taxes": D("1.00"), "statut": "ENVOYEE",
                     "date_envoi": "2026-08-30T09:00:00-04:00", "horodatage": "2026-08-30T09:00:00-04:00"})

    taxes = _composantes(_cash(par_nom))["taxes_a_remettre"]

    assert taxes["montant"] is None and taxes["manque"][0]["code"] == "REJ-CASH-FACTURE-ILLISIBLE"
    assert "F-CASSEE" in taxes["manque"][0]["detail"]


def test_un_po_dont_le_prix_manque_rend_les_comptes_a_payer_non_calculables_et_le_dit(par_nom, cas_fictif):
    with stockage.transaction():
        m5_outils._recevoir_reception_enregistree(_charge("e-9", "PO-9", "10", "2026-09-18T09:00:00-04:00", prix=None))

    cash = _cash(par_nom)
    ap = _composantes(cash)["comptes_a_payer"]

    assert ap["montant"] is None and ap["plancher"] == "459.91" and cash["cash_libre"] is None
    assert ap["detail"]["po_non_calculables"] == [{"po_id": "PO-9", "manque": ["REJ-AP-PRIX-PO-ABSENT"]}]
    assert cash["au_plus"] == "27861.98", "le plancher connu (459.91) est retranché ; le reste est inconnu, pas zéro"


# ============================================== 6. lecture pure : rien n'est écrit, rien ne sort de la caisse
def test_lire_le_cash_libre_et_les_echeances_n_ecrit_rien_nulle_part(par_nom, cas_fictif):
    avant = _instantane_base()

    _etat(par_nom)
    _etat(par_nom, {"autorise_couts": False})
    _echeances(par_nom)
    _echeances(par_nom, {"autorise_couts": False})

    assert _instantane_base() == avant, "aucun registre, aucune approbation, aucun journal n'a bougé"


def test_le_registre_des_mouvements_est_intact_apres_toute_lecture(par_nom, cas_fictif):
    with stockage.transaction():
        avant = (len(stockage.maillons(DEPARTEMENT, "principal")), stockage.maillons(DEPARTEMENT, "principal")[-1])

    _etat(par_nom)
    _echeances(par_nom)

    with stockage.transaction():
        apres = (len(stockage.maillons(DEPARTEMENT, "principal")), stockage.maillons(DEPARTEMENT, "principal")[-1])
    assert avant == apres and avant[0] == 3


def test_en_simulation_le_solde_vient_de_l_historique_transmis_et_le_reste_des_registres(par_nom, cas_fictif):
    """`mouvements_historique` (simulation en mémoire, comportement gardé) : le solde et les réserves viennent de
    l'historique ; taxes, comptes à payer et déclarations viennent toujours des registres et du manifeste."""
    historique = []
    for montant, type_mouvement in (("9000.00", "ENCAISSEMENT"), ("500.00", "PROVISION")):
        historique = _appeler(par_nom, "m5_enregistrer_mouvement", {
            "montant": montant, "type_mouvement": type_mouvement, "horodatage": "2026-09-01T12:00:00-04:00",
            "classe_retention": "STANDARD", "source": "simulation-fictive", "mouvements_historique": historique},
            None)["resultat"]["mouvements_historique"]

    cash = _cash(par_nom, {"mouvements_historique": historique})

    assert cash["solde"]["montant"] == "9000.00" and _composantes(cash)["reserves"]["montant"] == "500.00"
    assert _composantes(cash)["taxes_a_remettre"]["montant"] == "1981.69"
    # 9000.00 - 1981.69 - 4200.00 - 1350.75 - 459.91 - 800.00 - 500.00 = -292.35 : un déficit, rendu tel quel
    assert cash["cash_libre"] == "-292.35" and cash["en_deficit"] is True


# ===================================================== 7. la réponse tient sous la limite du socle
def _via_capacites(dep, nom, arguments):
    capacites = Capacites({DEPARTEMENT: dep}, stockage.transaction)
    with contexte.appele_par_appareil(ADMIN):
        return capacites.appeler(nom, arguments)


def test_le_cas_fictif_tient_sous_la_limite_de_6000_caracteres_du_socle(cas_fictif):
    dep = lire_manifeste(_RACINE_M5)

    reponse = _via_capacites(dep, "m5_etat_tresorerie", {})

    assert "tronque" not in reponse and reponse["ok"] is True
    assert len(json.dumps(reponse, ensure_ascii=False)) < 5000
    assert reponse["resultat"]["cash_libre"]["cash_libre"] == "27861.98"


def test_le_pire_cas_tient_encore_sous_la_limite(taux):
    """Rien n'est déclaré (tous les manques nommés), des PO non calculables plein le registre, un solde et une réserve
    : la plus longue réponse possible reste entière (`Capacites` tronquerait au-delà de 6 000 caractères)."""
    dep = lire_manifeste(_RACINE_M5)
    _peupler_mouvements()
    _peupler_factures_clients(taux)
    with stockage.transaction():
        for numero in range(1, 9):
            charge = _charge(f"e-{numero}", f"PO-LONG-IDENTIFIANT-{numero}", "10", "2026-09-18T09:00:00-04:00")
            charge["lignes"][0]["prix_unitaire_prevu"] = None
            m5_outils._recevoir_reception_enregistree(charge)

    reponse = _via_capacites(dep, "m5_etat_tresorerie", {})

    assert "tronque" not in reponse
    taille = len(json.dumps(reponse, ensure_ascii=False))
    assert taille <= m5_outils.BUDGET_SORTIE - 300, f"{taille} caractères"
    cash = reponse["resultat"]["cash_libre"]
    assert cash["cash_libre"] is None
    assert len(_composantes(cash)["comptes_a_payer"]["detail"]["po_non_calculables"]) == 3


def _essentiel(cash):
    """Tout ce qu'une réponse réduite ne doit JAMAIS perdre : les chiffres, les sources, les fraîcheurs, les manques,
    la lecture, la mention et l'empreinte."""
    return {
        "cash_libre": cash["cash_libre"], "au_plus": cash["au_plus"], "lecture": cash["lecture"],
        "manque": cash["manque"], "reserves": cash["reserves"], "mention": cash["mention"],
        "cash_libre_id": cash["cash_libre_id"],
        "composantes": [{cle: c[cle] for cle in ("id", "statut", "montant", "source", "fraicheur")}
                        for c in [cash["solde"], *cash["composantes"]]],
    }


def test_au_dela_du_budget_la_reponse_perd_d_abord_ses_hypotheses_puis_le_detail_jamais_un_chiffre(
        par_nom, cas_fictif, monkeypatch):
    complet = _etat(par_nom)
    taille_complete = len(json.dumps(complet, ensure_ascii=False))

    monkeypatch.setattr(m5_outils, "_BUDGET_ETAT_TRESORERIE", taille_complete)
    assert _etat(par_nom) == complet, "sous le budget : rien n'est retiré"

    monkeypatch.setattr(m5_outils, "_BUDGET_ETAT_TRESORERIE", taille_complete - 1)
    reduit = _etat(par_nom)
    assert reduit["cash_libre"]["hypotheses"] == [] and reduit["cash_libre"]["hypotheses_omises"] == 6
    assert all("detail" in c for c in reduit["cash_libre"]["composantes"][:1])
    assert _essentiel(reduit["cash_libre"]) == _essentiel(complet["cash_libre"])
    assert (reduit["solde"], reduit["argent_disponible"], reduit["mention"]) == (
        complet["solde"], complet["argent_disponible"], MENTION)

    monkeypatch.setattr(m5_outils, "_BUDGET_ETAT_TRESORERIE", len(json.dumps(reduit, ensure_ascii=False)))
    assert _etat(par_nom) == reduit, "juste assez de place sans les hypothèses : le détail des composantes reste"

    monkeypatch.setattr(m5_outils, "_BUDGET_ETAT_TRESORERIE", len(json.dumps(reduit, ensure_ascii=False)) - 1)
    minimal = _etat(par_nom)
    assert minimal["cash_libre"]["detail_omis"] is True and minimal["cash_libre"]["hypotheses"] == []
    assert all("detail" not in c for c in minimal["cash_libre"]["composantes"])
    assert _essentiel(minimal["cash_libre"]) == _essentiel(complet["cash_libre"])
    assert minimal["cash_libre"]["cash_libre"] == "27861.98"


def test_le_budget_ne_touche_pas_une_vue_sans_cash_libre(par_nom, cas_fictif, monkeypatch):
    monkeypatch.setattr(m5_outils, "_BUDGET_ETAT_TRESORERIE", 10)

    masque = _etat(par_nom, {"autorise_couts": False})

    assert masque["cash_libre"] is None and masque["mention"] == MENTION


# ======================================================= 8. m5_lire_echeances_fiscales : l'outil du calendrier
def test_registres_absents_ne_confirment_pas_un_zero_de_taxes(par_nom, declare):
    """Un calendrier configuré ne prouve pas la couverture des livres de factures vides."""
    declare(CONFIGURATION_COMPLETE)

    echeances = _echeances(par_nom)["resultat"]["echeances"]

    assert len(echeances) == 2
    assert all(e["taxes_nettes"] is None for e in echeances)
    assert all(e["manque"][0]["code"] == "REJ-FISCAL-COUVERTURE-ABSENTE" for e in echeances)
    assert all("aucune attestation de couverture" in e["manque"][0]["detail"] for e in echeances)


@pytest.mark.parametrize("piece", ["brouillon", "evenement_technique"])
def test_aucune_piece_admissible_ne_confirme_pas_un_zero_de_taxes(par_nom, declare, taux, piece):
    """Un maillon quelconque ne prouve pas qu'une pièce fiscale utilisable couvre les registres."""
    declare(CONFIGURATION_COMPLETE)
    with stockage.transaction():
        reg = m5_outils._registre_factures(None)
        if piece == "brouillon":
            _, verdict = facturation.creer_facture_brouillon(
                "F-BROUILLON", "CH-1", "D-BROUILLON", "C-1",
                [{"description": "service (fictif)", "quantite": "1", "unite": "u", "prix_unitaire": "10.00",
                  "reference_ligne_devis": "L-1"}], "2026-09-01T09:00:00-04:00", taux, reg,
            )
            assert verdict is None, verdict
        else:
            reg.ajouter({"type_entree": "demande_creee", "demande_id": "TECH-1",
                         "horodatage": "2026-09-01T09:00:00-04:00"})

    echeances = _echeances(par_nom)["resultat"]["echeances"]

    assert all(e["taxes_nettes"] is None for e in echeances)
    assert all(e["manque"][0]["code"] == "REJ-FISCAL-COUVERTURE-ABSENTE" for e in echeances)


def test_l_outil_est_de_lecture_seule_reserve_a_l_admin(par_nom):
    outil = par_nom["m5_lire_echeances_fiscales"]

    assert outil.autonomie == Autonomie.T0 and outil.roles_appareil == frozenset({"admin"})
    assert outil.parametres["required"] == ["aujourd_hui"] and outil.parametres["additionalProperties"] is False
    assert {"montant", "taux", "date_limite", "echeances"}.isdisjoint(outil.parametres["properties"])


def test_les_echeances_du_cas_fictif_avec_la_taxe_nette_de_chaque_periode(par_nom, cas_fictif):
    resultat = _echeances(par_nom)["resultat"]

    assert [(e["periode_fin"], e["limite_paiement"], e["statut"]) for e in resultat["echeances"]] == [
        ("2026-09-30", "2026-11-02", "A_VENIR"), ("2026-12-31", "2027-02-01", "A_VENIR")]
    troisieme, quatrieme = resultat["echeances"]
    assert troisieme["taxes_nettes"]["a_remettre"] == "1981.69"
    assert troisieme["taxes_nettes"]["tps"] == {"collectee": "676.67", "credits_intrants": "15.00", "nette": "661.67",
                                                "a_remettre": "661.67"}
    assert quatrieme["taxes_nettes"]["a_remettre"] == "0.00"
    assert quatrieme["taxes_nettes"]["couverture"]["statut"] == "PARTIELLE"
    assert troisieme["periode_terminee"] is False, "le trimestre est encore ouvert : le chiffre est partiel"
    assert resultat["mention"] == MENTION and resultat["role"] == "admin"


def test_une_facture_illisible_dans_la_periode_rend_la_taxe_de_cette_echeance_non_calculable(par_nom, cas_fictif):
    """Jamais un chiffre à demi : la facture cassée est datée du 2026-08-30 (3e trimestre). L'échéance de sa période
    n'a plus de `taxes_nettes` et dit quoi corriger ; celle d'une autre période garde son chiffre."""
    with stockage.transaction():
        m5_outils._registre_factures(None).ajouter({
            "type_entree": "facture_creee", "facture_id": "F-CASSEE", "chantier_id": "CH-1", "devis_id": "D-9",
            "client_id": "C-1", "lignes": [], "montant_avant_taxes": D("1.00"), "taxes": "illisible",
            "total_taxes": D("0.00"), "montant_apres_taxes": D("1.00"), "statut": "ENVOYEE",
            "date_envoi": "2026-08-30T09:00:00-04:00", "horodatage": "2026-08-30T09:00:00-04:00"})

    troisieme, quatrieme = _echeances(par_nom)["resultat"]["echeances"]

    assert troisieme["periode_fin"] == "2026-09-30" and troisieme["taxes_nettes"] is None
    assert [m["code"] for m in troisieme["manque"]] == ["REJ-CASH-FACTURE-ILLISIBLE"]
    assert "1 facture(s) illisible(s)" in troisieme["manque"][0]["detail"]
    assert quatrieme["taxes_nettes"]["a_remettre"] == "0.00" and "manque" not in quatrieme


def test_l_argument_limite_borne_le_nombre_d_echeances_rendues_et_le_dit(par_nom, cas_fictif):
    resultat = _echeances(par_nom, {"limite": 1})["resultat"]

    assert [e["periode_fin"] for e in resultat["echeances"]] == ["2026-09-30"]
    assert resultat["non_affichees"] == 1, "le nombre d'échéances tues est dit, jamais passé sous silence"


def test_un_trimestre_non_remis_est_en_retard_avec_sa_taxe_nette(par_nom, cas_fictif, declare):
    declare({**CONFIGURATION_COMPLETE, "fiscal": {**CONFIGURATION_COMPLETE["fiscal"],
                                                   "taxes_remises_jusqu_au": "2026-03-31"}})

    resultat = _echeances(par_nom)["resultat"]

    retard = resultat["echeances"][0]
    assert (retard["periode_debut"], retard["periode_fin"], retard["statut"], retard["jours_avant_paiement"]) == (
        "2026-04-01", "2026-06-30", "EN_RETARD", -60)
    # F-3 (1000.00, 2026-06-10) et F-6 (100.00, 2026-06-30) moins la facture fournisseur PO-2 (100.00, 2026-06-20) :
    # TPS 55.00 - 5.00 = 50.00 ; TVQ 109.73 - 9.98 = 99.75 ; à remettre 149.75
    assert retard["taxes_nettes"]["a_remettre"] == "149.75"
    assert retard["taxes_nettes"]["tps"]["nette"] == "50.00" and retard["taxes_nettes"]["tvq"]["nette"] == "99.75"
    assert resultat["echeances"][1]["taxes_nettes"]["a_remettre"] == "1981.69"


def test_sans_date_de_remise_aucune_taxe_n_est_chiffree_par_echeance(par_nom, cas_fictif, declare):
    declare({**CONFIGURATION_COMPLETE, "fiscal": {"frequence_tps_tvq": "trimestrielle", "mois_fin_exercice": 12}})

    resultat = _echeances(par_nom)["resultat"]

    assert all("taxes_nettes" not in e for e in resultat["echeances"])
    assert [m["code"] for m in resultat["manque"]] == ["REJ-FISCAL-REMISE-A-DECLARER"]


def test_la_vue_sans_droit_donne_les_dates_sans_aucun_montant(par_nom, cas_fictif):
    resultat = _echeances(par_nom, {"autorise_couts": False})["resultat"]

    assert [e["limite_paiement"] for e in resultat["echeances"]] == ["2026-11-02", "2027-02-01"]
    texte = json.dumps(resultat, ensure_ascii=False)
    assert "taxes_nettes" not in texte and "1981.69" not in texte


def test_le_manifeste_livre_refuse_les_echeances_et_dit_quoi_declarer(par_nom):
    reponse = _appeler(par_nom, "m5_lire_echeances_fiscales", {"aujourd_hui": AUJOURD_HUI})

    assert reponse["resultat"]["accepte"] is False
    verdict = reponse["resultat"]["verdict"]
    assert verdict["code"] == "REJ-FISCAL-FREQUENCE-A-DECLARER" and "GATE NATHAN" in verdict["detail"]


@pytest.mark.parametrize("aujourd_hui, code", [
    ("2027-03-01", "REJ-CALENDRIER-ANNEE-NON-DECLAREE"),
    ("2028-01-01", "REJ-CALENDRIER-ANNEE-NON-DECLAREE"),
    ("2024-01-01", "REJ-CALENDRIER-ANNEE-NON-DECLAREE"),
    ("demain", "REJ-FISCAL-DATE-INVALIDE"),
    ("2026-02-30", "REJ-FISCAL-DATE-INVALIDE"),
])
def test_une_annee_non_declaree_ou_une_date_illisible_est_refusee_par_l_outil(par_nom, cas_fictif, aujourd_hui, code):
    reponse = _appeler(par_nom, "m5_lire_echeances_fiscales", {"aujourd_hui": aujourd_hui})

    assert reponse["resultat"]["accepte"] is False and reponse["resultat"]["verdict"]["code"] == code
    assert set(reponse["resultat"]) == {"accepte", "verdict"}, "aucune échéance rendue, aucune date supposée"


def test_la_date_du_jour_est_obligatoire_et_aucun_montant_ne_se_passe_en_argument(par_nom):
    assert _appeler(par_nom, "m5_lire_echeances_fiscales", {})["erreur"] == "arguments_invalides"
    for argument in ({"limite_paiement": "2026-11-02"}, {"taux": "0.05"}, {"echeances": []}, {"montant": "1.00"}):
        reponse = _appeler(par_nom, "m5_lire_echeances_fiscales", {"aujourd_hui": AUJOURD_HUI, **argument})
        assert reponse["erreur"] == "arguments_invalides", argument


@pytest.mark.parametrize("appelante", [MARC, VENDEUR])
def test_l_employe_et_le_vendeur_n_ont_pas_le_calendrier(par_nom, cas_fictif, appelante):
    reponse = _appeler(par_nom, "m5_lire_echeances_fiscales", {"aujourd_hui": AUJOURD_HUI}, appelante)

    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"


def test_un_agent_doit_demander_les_echeances_avec_autorise_couts(par_nom, cas_fictif):
    sans = _appeler(par_nom, "m5_lire_echeances_fiscales", {"aujourd_hui": AUJOURD_HUI}, None)
    avec = _appeler(par_nom, "m5_lire_echeances_fiscales", {"aujourd_hui": AUJOURD_HUI, "autorise_couts": True}, None)

    assert sans["resultat"]["verdict"]["code"] == "REJ-AUTORISE-COUTS-REQUIS"
    assert avec["resultat"]["accepte"] is True and avec["resultat"]["resultat"]["role"] is None


def test_l_admin_ne_peut_pas_elargir_ni_changer_son_role(par_nom, cas_fictif):
    assert _appeler(par_nom, "m5_lire_echeances_fiscales",
                    {"aujourd_hui": AUJOURD_HUI, "role": "employee"})["resultat"]["verdict"]["code"] == (
        "REJ-IDENTITE-FOURNIE-DIFFERENTE")


def test_l_outil_lit_le_calendrier_versionne_du_paquet(par_nom, cas_fictif):
    """L'outil lit `contracts/calendrier_fiscal.v1.yaml` (patron des taux) : un autre fichier, une autre année."""
    assert m5_outils._CHEMIN_CALENDRIER_FISCAL == _RACINE_M5 / "contracts" / "calendrier_fiscal.v1.yaml"
    calendrier, erreurs = calendrier_fiscal.charger_calendrier_fiscal(m5_outils._CHEMIN_CALENDRIER_FISCAL)
    assert erreurs == [] and sorted(calendrier) == [2025, 2026]
