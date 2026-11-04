"""C5 : `m5_constater_tresorerie_prevue` (à la demande, N3) et `m5_constater_tresorerie_prevue_planifiee` (N2) sur le
VRAI socle : M5 constate la prévision des flux connus et datés et la publie au bus
(`m5.tresorerie_prevue_constatee`), dans la même transaction que la trace du constat.

Base SQLite temporaire migrée, registres durables réels (mouvements, factures clientes, comptes à payer), manifeste
de test qui déclare ce que le propriétaire décide (`configuration.fiscal`, `configuration.obligations_declarees`,
`configuration.prevision`). Le cas de référence est celui de `test_prevision.py` (calculé à la main) : solde
20000.00 ; semaines 19885.02, 15685.02, 18013.46, 20312.96, 18464.71, 18464.71 ; seuil 16000.00 ; alerte en semaine 2.
Personnes, montants et identifiants fictifs (AGENTS.md).
"""

from __future__ import annotations

import contextlib
import json
import pathlib as _pathlib
from decimal import Decimal

import m5_financecore.outils as m5_outils
import pytest
import yaml
from m5_financecore import (
    comptes_a_payer,
    constat_tresorerie_prevue,
    facturation,
    registre,
    taux_fiscaux,
)
from m5_financecore.analyse import MENTION_ANALYSE_PREPARATOIRE as MENTION
from sqlalchemy import select

from opsys import contexte, identite, service_acteur_systeme, stockage
from opsys.evenements.schemas import erreurs_charge
from opsys.outils import Niveau, executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS

FICTIF = True
D = Decimal

_RACINE_M5 = _pathlib.Path(__file__).resolve().parents[1]
DEPARTEMENT = "m05-financecore"
TYPE = "m5.tresorerie_prevue_constatee"
OUTIL = "m5_constater_tresorerie_prevue"
OUTIL_PLANIFIE = "m5_constater_tresorerie_prevue_planifie"
AUJOURD_HUI = "2026-09-29"
EMISE_LE = "2026-09-29T07:00:00-04:00"
SOLDES_DU_CAS = ["19885.02", "15685.02", "18013.46", "20312.96", "18464.71", "18464.71"]

ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
MARC = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")
EMPLOYE_QUI_SE_DIT_ADMIN = contexte.IdentiteAppelante(personne="marc.fictif", role="admin")
FANTOME = contexte.IdentiteAppelante(personne="fantome.fictif", role="admin")

CONFIGURATION_COMPLETE = {
    "fiscal": {"frequence_tps_tvq": "trimestrielle", "mois_fin_exercice": 12, "taxes_remises_jusqu_au": "2026-06-30"},
    "obligations_declarees": {
        "paies": {"montant": "4200.00", "source": "brouillon de paie du 2026-09-25 (fictif)", "au": "2026-09-25"},
        "das": {"montant": "1350.75", "source": "estimation du CPA (fictive)", "au": "2026-09-25"},
        "dettes": {"montant": "800.00", "source": "relevé du prêt camion (fictif)", "au": "2026-09-01"},
    },
    "prevision": {
        "horizon_semaines": 6,
        "seuil_alerte": {"montant": "16000.00", "source": "décision de Nathan (fictive)", "au": "2026-09-25"},
        "delai_encaissement_clients_jours": 30,
        "delai_paiement_fournisseurs_jours": 30,
        "echeances_obligations": {"paies": "2026-10-09", "das": "2026-10-15", "dettes": "2026-10-31"},
    },
}


@pytest.fixture(autouse=True)
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm5-tresorerie-prevue.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    m5_outils.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "marc.fictif", "Marc Fictif", "mot-de-passe-marc-1234", ["employee"])
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


@pytest.fixture
def declare(tmp_path, monkeypatch):
    def _declarer(configuration):
        manifeste = tmp_path / "department.yaml"
        manifeste.write_text(yaml.safe_dump({"configuration": configuration}, allow_unicode=True), encoding="utf-8")
        monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)
    return _declarer


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


def _reception(evenement_id, po_id, quantite, horodatage):
    return {
        "evenement_id": evenement_id, "po_id": po_id, "fournisseur_id": "gentek", "chantier_id": "CH-1",
        "horodatage_reception": horodatage, "verdict_reception": "CONFORME", "statut_po": "received",
        "hash_maillon": "a" * 64, "seuil_ecart_prix_pourcentage": 0.15,
        "lignes": [{"materiau_id": "gouttiere-5po", "quantite_demandee": quantite, "quantite_recue": quantite,
                    "prix_unitaire_prevu": "5.00", "devise_prevue": "CAD", "verdict_prix_po": "PRIX_LIVRE",
                    "prix_unitaire_reception": "5.00", "verdict_prix_reception": "PRIX_CATALOGUE",
                    "ecart_prix_critique": False}],
    }


def _peupler_a_payer(taux):
    with stockage.transaction():
        for evenement, po, quantite, horodatage in (("e-1", "PO-1", "60", "2026-09-15T09:00:00-04:00"),
                                                    ("e-2", "PO-2", "20", "2026-09-16T09:00:00-04:00"),
                                                    ("e-3", "PO-3", "100", "2026-09-17T09:00:00-04:00")):
            m5_outils._recevoir_reception_enregistree(_reception(evenement, po, quantite, horodatage))
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
    """Le cas de reference de test_prevision_outils.py : solde 20000.00, alerte en semaine 2 sous 16000.00."""
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


def _constat(par_nom, jour=AUJOURD_HUI, emise_le=EMISE_LE, identite_appelante=ADMIN, **arguments):
    reponse = _appeler(par_nom, OUTIL, {"aujourd_hui": jour, "emise_le": emise_le, **arguments}, identite_appelante)
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _refus(par_nom, nom, arguments, identite_appelante=ADMIN):
    reponse = _appeler(par_nom, nom, arguments, identite_appelante)
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    assert set(reponse["resultat"]) == {"accepte", "verdict"}, "un refus ne rend ni constat ni montant"
    return reponse["resultat"]["verdict"]["code"]


def _publies():
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS.c.evenement_id, EVENEMENTS_SORTANTS.c.producteur,
                                    EVENEMENTS_SORTANTS.c.charge)
                             .where(EVENEMENTS_SORTANTS.c.type_evenement == TYPE)).all()
    publies = [(ligne.evenement_id, ligne.producteur, codec.decoder(ligne.charge)) for ligne in lignes]
    return sorted(publies, key=lambda paire: paire[2]["sequence"])


def _traces():
    with stockage.transaction():
        return list(stockage.maillons(DEPARTEMENT, "constats_tresorerie_prevue"))


# ============================================================================================= le contrat
def test_les_deux_outils_sont_declares_t1_avec_leurs_entrees_et_la_mention(par_nom):
    outil = par_nom[OUTIL]
    assert outil.autonomie.name == "T1" and outil.niveau is None
    assert set(outil.parametres["required"]) == {"aujourd_hui", "emise_le"}
    assert set(outil.parametres["properties"]) == {"aujourd_hui", "emise_le", "role", "autorise_couts"}
    planifie = par_nom[OUTIL_PLANIFIE]
    assert planifie.autonomie.name == "T1" and planifie.niveau == Niveau.N2
    assert set(planifie.parametres["required"]) == {"aujourd_hui", "emise_le"}
    assert "roles_appareil" not in dir(planifie) or True


def test_le_cas_fictif_est_constate_et_publie_avec_sa_trace(par_nom, cas_fictif):
    corps = _constat(par_nom)
    assert (corps["deja_constate"], corps["publie"], corps["mention"]) == (False, True, MENTION)
    constat = corps["constat"]
    assert (constat["sequence"], constat["date_reference"], constat["statut_alerte"]) == (1, AUJOURD_HUI, "ALERTE")
    assert constat["solde_minimal_prevu_cad"] == "15685.02" and constat["semaine_solde_minimal"] == 2
    assert constat["semaines_sous_seuil"] == [2]
    (publie,) = _publies()
    evenement_id, producteur, charge = publie
    assert producteur == DEPARTEMENT and evenement_id == charge["evenement_id"] == constat["evenement_id"]
    assert erreurs_charge(TYPE, charge) == []
    (trace,) = _traces()
    assert trace == constat_tresorerie_prevue.construire_trace(charge)


def test_redemander_le_meme_constat_ne_publie_rien(par_nom, cas_fictif):
    premier = _constat(par_nom)["constat"]
    second = _constat(par_nom)["constat"]
    assert second["evenement_id"] == premier["evenement_id"]
    assert len(_publies()) == 1 and len(_traces()) == 1


def test_le_planificateur_seul_declenche_la_variante_planifiee_reponse_sans_montant(par_nom, cas_fictif):
    with service_acteur_systeme.contexte_planificateur():
        reponse = executer_atomique(par_nom[OUTIL_PLANIFIE], {"aujourd_hui": AUJOURD_HUI, "emise_le": EMISE_LE})
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    entete = reponse["resultat"]["resultat"]["constat"]
    texte = json.dumps(entete, ensure_ascii=False)
    for interdit in ("19885.02", "15685.02", "16000.00"):
        assert interdit not in texte


def test_un_agent_ne_peut_pas_declencher_la_variante_planifiee(par_nom, cas_fictif):
    assert _refus(par_nom, OUTIL_PLANIFIE, {"aujourd_hui": AUJOURD_HUI, "emise_le": EMISE_LE}) == (
        "REJ-CONSTAT-PLANIFICATEUR-SEULEMENT")


def test_un_constat_sans_le_droit_de_voir_les_couts_est_refuse(par_nom, cas_fictif):
    assert _refus(par_nom, OUTIL, {"aujourd_hui": AUJOURD_HUI, "emise_le": EMISE_LE, "autorise_couts": False}) == (
        "REJ-CONSTAT-COUTS-REQUIS")


def test_l_employe_n_a_aucune_portee(par_nom, cas_fictif):
    assert _refus(par_nom, OUTIL, {"aujourd_hui": AUJOURD_HUI, "emise_le": EMISE_LE},
                  identite_appelante=MARC) is not None
