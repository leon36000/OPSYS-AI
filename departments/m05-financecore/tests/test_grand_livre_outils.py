"""Grand livre (tranche 1) sur le VRAI socle : outils, file d'approbation N4, portée d'appareil fermée, mentions.

Base SQLite temporaire migrée, vrai manifeste de M5 (mode `ombre`), vraies approbations (`Capacites`, `decider`).
Les factures clientes sont écrites au registre durable des factures par `facturation.py` (le chemin réel des outils
M5.2), puis le grand livre en tire ses brouillons. Personnes, identifiants et montants fictifs (AGENTS.md).
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
from decimal import Decimal
from pathlib import Path

import m5_financecore.outils as m5_outils
import pytest
import yaml
from m5_financecore import analyse, facturation, grand_livre, grand_livre_beancount, taux_fiscaux
from m5_financecore import registre as registre_module
from sqlalchemy import func, select

from opsys import approbations as opsys_approbations
from opsys import contexte, identite, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.departements import lire_manifeste
from opsys.outils import Autonomie, Niveau, executer_atomique
from opsys.stockage.schema import REGISTRES

FICTIF = True
D = Decimal
_RACINE_M5 = Path(__file__).resolve().parents[1]
DEPARTEMENT = "m05-financecore"
H = "2026-10-25T10:00:00-04:00"
ADMIN = contexte.IdentiteAppelante(personne="nathan", role="admin")
OUTILS_GL = ("m5_lire_balance_verification", "m5_lire_grand_livre_compte", "m5_rapprocher_grand_livre",
             "m5_proposer_ecriture_comptable", "m5_generer_brouillons_comptables", "m5_proposer_contre_passation",
             "m5_valider_ecriture_comptable", "m5_clore_periode_comptable")


@pytest.fixture(autouse=True)
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'm5-gl.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    m5_outils.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan Propriétaire (fictif)", "mot-de-passe-nathan-1234",
                                ["nathan_owner", "admin"])
        identite.creer_personne(cnx, "comptable", "Une Comptable (fictive)", "mot-de-passe-compta-1234", ["finance"])
        identite.creer_personne(cnx, "gestion", "Une Gestionnaire (fictive)", "mot-de-passe-gestion-123",
                                ["manager", "admin"])
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
    return _declarer


def _taux():
    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(m5_outils._CHEMIN_TAUX_FISCAUX)
    assert erreurs == []
    return dictionnaire


def _lignes_facture(prix="260.00"):
    return [{"description": "Gouttières 5po (fictif)", "quantite": "40", "unite": "pi", "prix_unitaire": "8.50",
             "reference_ligne_devis": "L1"},
            {"description": "Main-d'oeuvre (fictif)", "quantite": "1", "unite": "forfait", "prix_unitaire": prix,
             "reference_ligne_devis": "L2"}]


def _facturer(facture_id="F-1", *, payer=True, envoi="2026-10-02T09:00:00-04:00"):
    """Une facture de 600.00 $ avant taxes (689.85 $) envoyée, et payée si `payer`, au registre DURABLE des factures."""
    with stockage.transaction():
        reg = registre_module.Registre(maillons=stockage.maillons(DEPARTEMENT, "factures"))
        for couple in (
            facturation.creer_facture_brouillon(facture_id, f"CH-{facture_id}", f"D-{facture_id}", "client-fictif",
                                                _lignes_facture(), "2026-10-01T09:00:00-04:00", _taux(), reg),
            facturation.envoyer_facture(facture_id, envoi, reg),
        ):
            assert couple[1] is None, couple
        if payer:
            assert facturation.enregistrer_paiement_facture(
                facture_id, "689.85", "nathan", "2026-10-20T09:00:00-04:00", reg)[1] is None


@contextlib.contextmanager
def _appareil(identite_appelante):
    with contextlib.ExitStack() as pile:
        if identite_appelante is not None:
            pile.enter_context(contexte.appele_par_appareil(identite_appelante))
        yield


def _appeler(par_nom, nom, arguments, identite_appelante=None):
    with _appareil(identite_appelante):
        return executer_atomique(par_nom[nom], arguments)


def _accepte(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    corps = reponse["resultat"]["resultat"]
    assert corps["mention"] == analyse.MENTION_ANALYSE_PREPARATOIRE
    assert corps["mention_comptable"] == "À valider auprès d'un comptable (CPA) / professionnel qualifié."
    return corps


def _code(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]["code"]


def _maillons(registre):
    with stockage.transaction() as cnx:
        return cnx.execute(select(func.count()).select_from(REGISTRES).where(
            (REGISTRES.c.departement == DEPARTEMENT) & (REGISTRES.c.registre == registre))).scalar_one()


def _etat_gl():
    with stockage.transaction():
        return grand_livre.etat_grand_livre(
            registre_module.Registre(maillons=stockage.maillons(DEPARTEMENT, "grand_livre")).lire())


def _demande_puis_decision(dep, nom, arguments, decideur, *, approuver=True, role=None):
    capacites = Capacites({DEPARTEMENT: dep}, stockage.transaction)
    demande = capacites.appeler(nom, arguments)
    assert demande["statut"] == "en_attente_approbation", demande
    with stockage.transaction() as cnx:
        decision = opsys_approbations.decider(
            cnx, demande["demande_id"], approuver, decideur,
            outils_executables({DEPARTEMENT: dep}, stockage.transaction), {DEPARTEMENT: dep}, role=role)
    return demande, decision


def _generer(dep):
    reponse = Capacites({DEPARTEMENT: dep}, stockage.transaction).appeler(
        "m5_generer_brouillons_comptables", {"horodatage": H})
    return _accepte(reponse)


def _valider_par_la_file(dep, ecriture_id, decideur="comptable"):
    _demande, decision = _demande_puis_decision(
        dep, "m5_valider_ecriture_comptable", {"ecriture_id": ecriture_id, "horodatage": H}, decideur)
    assert decision["statut"] == "executee", decision
    _accepte(decision["reponse"])  # les deux mentions, aussi sur l'écriture rendue définitive
    return decision["reponse"]


# ============================================================================================= le contrat
def test_les_huit_outils_ont_leur_niveau_et_aucune_portee_d_appareil(par_nom):
    attendus = {"m5_lire_balance_verification": ("T0", "N0"), "m5_lire_grand_livre_compte": ("T0", "N0"),
                "m5_rapprocher_grand_livre": ("T0", "N0"), "m5_proposer_ecriture_comptable": ("T1", "N1"),
                "m5_generer_brouillons_comptables": ("T1", "N1"), "m5_proposer_contre_passation": ("T1", "N1"),
                "m5_valider_ecriture_comptable": ("T2", "N4"), "m5_clore_periode_comptable": ("T2", "N4")}
    for nom, (autonomie, niveau) in attendus.items():
        outil = par_nom[nom]
        assert (outil.autonomie.value, outil.niveau_effectif.value) == (autonomie, niveau), nom
        assert outil.roles_appareil == frozenset(), "portée d'appareil fermée par défaut"
        assert not outil.frontiere_humaine and outil.parametres["additionalProperties"] is False
    assert par_nom["m5_valider_ecriture_comptable"].niveau is Niveau.N4, "le niveau est déclaré, pas déduit"
    assert par_nom["m5_valider_ecriture_comptable"].autonomie is Autonomie.T2
    assert set(OUTILS_GL) == analyse.SORTIES_COMPTABLES <= analyse.SORTIES_D_ANALYSE


@pytest.mark.parametrize("nom", OUTILS_GL)
def test_une_identite_d_appareil_meme_admin_est_refusee_sans_rien_ecrire(par_nom, nom):
    _facturer()
    arguments = {
        "m5_lire_balance_verification": {"au": "2026-10-31"},
        "m5_lire_grand_livre_compte": {"compte": "1010", "debut": "2026-10-01", "fin": "2026-10-31"},
        "m5_rapprocher_grand_livre": {"debut": "2026-10-01", "fin": "2026-10-31"},
        "m5_proposer_ecriture_comptable": {"date_effet": "2026-10-03", "libelle": "x", "piece_type": "manuelle",
                                           "piece_reference": "M-1", "horodatage": H,
                                           "lignes": [{"compte": "5600", "debit": "1.00", "credit": None},
                                                      {"compte": "1010", "debit": None, "credit": "1.00"}]},
        "m5_generer_brouillons_comptables": {"horodatage": H},
        "m5_proposer_contre_passation": {"ecriture_id": "gle-x", "date_effet": "2026-10-03", "motif": "m",
                                         "horodatage": H},
        "m5_valider_ecriture_comptable": {"ecriture_id": "gle-x", "horodatage": H},
        "m5_clore_periode_comptable": {"periode": "2026-09", "horodatage": H},
    }[nom]
    assert _code(_appeler(par_nom, nom, arguments, ADMIN)) == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert _maillons("grand_livre") == 0


# ============================================================================================= le parcours réel
def test_facture_emise_et_payee_jusqu_a_la_balance_le_rapprochement_et_l_export(dep, par_nom, tmp_path):
    _facturer("F-1")
    _facturer("F-2", payer=False)

    generation = _generer(dep)
    assert len(generation["brouillons_crees"]) == 3 and generation["sources_ignorees"] == []
    assert _maillons("grand_livre") == 3
    # Rien n'est encore comptabilisé : la balance est vide, et le dit.
    vide = _accepte(_appeler(par_nom, "m5_lire_balance_verification", {"au": "2026-10-31"}))
    assert vide["comptes"] == [] and vide["brouillons_non_comptabilises"] == 3

    for brouillon in generation["brouillons_crees"]:
        reponse = _valider_par_la_file(dep, brouillon["ecriture_id"])
        assert reponse["resultat"]["accepte"] is True
        ecriture = reponse["resultat"]["resultat"]["ecriture"]
        assert ecriture["validation"]["par"] == "comptable" and ecriture["validation"]["voie"] == "approbation"

    balance = _accepte(_appeler(par_nom, "m5_lire_balance_verification", {"au": "2026-10-31"}))
    assert balance["equilibree"] and balance["total_debits"] == balance["total_credits"] == "2069.55"
    soldes = {c["compte"]: (c["solde"], c["cote"]) for c in balance["comptes"]}
    assert soldes == {"1010": ("689.85", "debiteur"), "1100": ("689.85", "debiteur"),
                      "2300": ("60.00", "crediteur"), "2310": ("119.70", "crediteur"),
                      "4100": ("1200.00", "crediteur")}

    livre = _accepte(_appeler(par_nom, "m5_lire_grand_livre_compte",
                              {"compte": "1100", "debut": "2026-10-01", "fin": "2026-10-31"}))
    assert livre["solde_cloture_debiteur"] == "689.85" and livre["lignes_total"] == 3

    rapprochement = _accepte(_appeler(par_nom, "m5_rapprocher_grand_livre",
                                      {"debut": "2026-10-01", "fin": "2026-10-31"}))
    assert rapprochement["verdict"] == "CONCORDANT"
    assert rapprochement["taxes"]["tps_a_percevoir"]["attendu_taxes_py"] == "60.00"

    # Rejouer la génération ne recrée rien.
    redite = _generer(dep)
    assert redite["brouillons_crees"] == [] and redite["deja_proposes"] == 3 and _maillons("grand_livre") == 6

    # L'export Beancount du registre durable : trois transactions, chacune équilibrée.
    plan, _ = m5_outils._plan_comptable_effectif()
    texte = grand_livre_beancount.ecrire_fichier_beancount(tmp_path / "gl.beancount", _etat_gl(), plan).read_text(
        encoding="utf-8")
    assert texte.count(" * ") == 3 and "Assets:C1010-" in texte
    # Aucun mouvement d'argent : le registre des mouvements reste vide.
    assert _maillons("principal") == 0


def test_une_facture_emise_non_comptabilisee_est_un_ecart_de_rapprochement(dep, par_nom):
    _facturer("F-1", payer=False)
    _facturer("F-2", payer=False)
    generation = _generer(dep)
    _valider_par_la_file(dep, generation["brouillons_crees"][0]["ecriture_id"])
    rapprochement = _accepte(_appeler(par_nom, "m5_rapprocher_grand_livre",
                                      {"debut": "2026-10-01", "fin": "2026-10-31"}))
    assert rapprochement["verdict"] == "ECART"
    assert [e["raison"] for e in rapprochement["taxes"]["tvq_a_percevoir"]["ecarts"]] == ["sans écriture définitive"]


# ============================================================================================= l'humain exigé
def test_un_agent_seul_ne_valide_jamais(dep, par_nom):
    _facturer(payer=False)
    ident = _generer(dep)["brouillons_crees"][0]["ecriture_id"]
    avant = _maillons("grand_livre")

    direct = _appeler(par_nom, "m5_valider_ecriture_comptable", {"ecriture_id": ident, "horodatage": H})
    autonome = Capacites({DEPARTEMENT: dataclasses.replace(dep, mode="autonome")}, stockage.transaction).appeler(
        "m5_valider_ecriture_comptable", {"ecriture_id": ident, "horodatage": H})
    cloture = _appeler(par_nom, "m5_clore_periode_comptable", {"periode": "2026-09", "horodatage": H})

    assert _code(direct) == _code(autonome) == _code(cloture) == "REJ-GL-HUMAIN-REQUIS"
    assert _maillons("grand_livre") == avant


@pytest.mark.parametrize("mode", ["ombre", "supervise"])
def test_la_validation_attend_dans_la_file_sans_rien_ecrire(dep, mode):
    _facturer(payer=False)
    ident = _generer(dep)["brouillons_crees"][0]["ecriture_id"]
    avant = _maillons("grand_livre")
    demande = Capacites({DEPARTEMENT: dataclasses.replace(dep, mode=mode)}, stockage.transaction).appeler(
        "m5_valider_ecriture_comptable", {"ecriture_id": ident, "horodatage": H})
    assert demande["statut"] == "en_attente_approbation" and _maillons("grand_livre") == avant


def test_un_refus_dans_la_file_ne_change_rien_et_le_proprietaire_peut_valider(dep):
    _facturer(payer=False)
    ident = _generer(dep)["brouillons_crees"][0]["ecriture_id"]
    avant = _maillons("grand_livre")
    _d, refus = _demande_puis_decision(dep, "m5_valider_ecriture_comptable",
                                       {"ecriture_id": ident, "horodatage": H}, "nathan", approuver=False)
    assert refus["statut"] != "executee" and _maillons("grand_livre") == avant
    reponse = _valider_par_la_file(dep, ident, decideur="nathan")
    assert reponse["resultat"]["resultat"]["ecriture"]["validation"]["role"] == "nathan_owner"


def test_cloture_par_la_file_puis_periode_close_refusee(dep, par_nom):
    _facturer(payer=False, envoi="2026-09-29T09:00:00-04:00")
    ident = _generer(dep)["brouillons_crees"][0]["ecriture_id"]
    _valider_par_la_file(dep, ident)
    _d, decision = _demande_puis_decision(dep, "m5_clore_periode_comptable",
                                          {"periode": "2026-09", "horodatage": H}, "nathan")
    assert decision["statut"] == "executee", decision
    close = _accepte(decision["reponse"])
    assert close["verrou"] == "2026-09-30" and close["brouillons_laisses_en_plan"] == []
    ecrit = _appeler(par_nom, "m5_proposer_ecriture_comptable", {
        "date_effet": "2026-09-30", "libelle": "Oubli (fictif)", "piece_type": "manuelle", "piece_reference": "M-9",
        "horodatage": H, "lignes": [{"compte": "5990", "debit": "5.00", "credit": None},
                                    {"compte": "1010", "debit": None, "credit": "5.00"}]})
    assert _code(ecrit) == "REJ-GL-PERIODE-CLOSE"
    contre = _accepte(_appeler(par_nom, "m5_proposer_contre_passation", {
        "ecriture_id": ident, "date_effet": "2026-10-01", "motif": "facture refaite (fictif)", "horodatage": H}))
    assert contre["ecriture"]["contre_passe"] == ident and contre["ecriture"]["statut"] == "BROUILLON"


# ============================================================================================= saisie et plan
def test_saisie_manuelle_verifie_la_piece_m5_citee(par_nom):
    _facturer("F-1", payer=False)
    base = {"date_effet": "2026-10-03", "libelle": "Escompte accordé (fictif)", "horodatage": H,
            "lignes": [{"compte": "4100", "debit": "10.00", "credit": None},
                       {"compte": "1100", "debit": None, "credit": "10.00"}]}
    inconnue = _appeler(par_nom, "m5_proposer_ecriture_comptable",
                        {**base, "piece_type": "facture_client", "piece_reference": "F-404"})
    fournisseur = _appeler(par_nom, "m5_proposer_ecriture_comptable",
                           {**base, "piece_type": "facture_fournisseur", "piece_reference": "apf-404"})
    assert _code(inconnue) == _code(fournisseur) == "REJ-GL-PIECE-INTROUVABLE" and _maillons("grand_livre") == 0
    connue = _accepte(_appeler(par_nom, "m5_proposer_ecriture_comptable",
                               {**base, "piece_type": "facture_client", "piece_reference": "F-1"}))
    assert connue["ecriture"]["piece"]["verification"] == "verifiee"
    desequilibree = _appeler(par_nom, "m5_proposer_ecriture_comptable", {
        **base, "piece_type": "recu", "piece_reference": "R-1",
        "lignes": [{"compte": "5990", "debit": "10.00", "credit": None},
                   {"compte": "1010", "debit": None, "credit": "9.99"}]})
    assert _code(desequilibree) == "REJ-GL-ECRITURE-DESEQUILIBREE"


def test_l_extension_du_plan_vient_du_manifeste(par_nom, declare):
    saisie = {"date_effet": "2026-10-03", "libelle": "Location (fictif)", "piece_type": "recu",
              "piece_reference": "R-1", "horodatage": H,
              "lignes": [{"compte": "5450", "debit": "10.00", "credit": None},
                         {"compte": "1010", "debit": None, "credit": "10.00"}]}
    assert _code(_appeler(par_nom, "m5_proposer_ecriture_comptable", saisie)) == "REJ-GL-COMPTE-INCONNU"
    declare({"grand_livre": {"comptes_ajoutes": [{"numero": "5450", "nom": "Location d'équipement",
                                                   "type": "charges"}], "comptes_desactives": ["5600"]}})
    ecriture = _accepte(_appeler(par_nom, "m5_proposer_ecriture_comptable", saisie))["ecriture"]
    assert ecriture["plan_comptable_version"].startswith("2026-v1+client.")
    loyer = {**saisie, "piece_reference": "R-2", "lignes": [{"compte": "5600", "debit": "10.00", "credit": None},
                                                            {"compte": "1010", "debit": None, "credit": "10.00"}]}
    assert _code(_appeler(par_nom, "m5_proposer_ecriture_comptable", loyer)) == "REJ-GL-COMPTE-INACTIF"
    declare({"grand_livre": {"comptes_desactives": ["0000"]}})
    assert _code(_appeler(par_nom, "m5_lire_balance_verification", {"au": "2026-10-31"})) == "REJ-GL-PLAN-INVALIDE"


def test_sans_stockage_durable_le_grand_livre_refuse(par_nom):
    m5_outils.reinitialiser_stockage_mouvements()
    try:
        assert _code(_appeler(par_nom, "m5_lire_balance_verification", {"au": "2026-10-31"})) \
            == "REJ-GL-STOCKAGE-NON-DURABLE"
    finally:
        m5_outils.utiliser_stockage_durable()


def test_une_balance_large_tient_sous_la_limite_de_sortie_par_pages(par_nom, declare):
    ajoutes = [{"numero": f"59{index:02d}", "nom": f"Charge diverse fictive numéro {index} à ventiler",
                "type": "charges"} for index in range(51, 81)]
    declare({"grand_livre": {"comptes_ajoutes": ajoutes}})
    lignes = [{"compte": c["numero"], "debit": "1.00", "credit": None} for c in ajoutes]
    lignes.append({"compte": "1010", "debit": None, "credit": f"{len(ajoutes)}.00"})
    _accepte(_appeler(par_nom, "m5_proposer_ecriture_comptable", {
        "date_effet": "2026-10-03", "libelle": "Ventilation (fictif)", "piece_type": "manuelle",
        "piece_reference": "M-L", "horodatage": H, "lignes": lignes}))
    with stockage.transaction():
        reg = registre_module.Registre(maillons=stockage.maillons(DEPARTEMENT, "grand_livre"))
        plan, _ = m5_outils._plan_comptable_effectif()
        ident = grand_livre.etat_grand_livre(reg.lire())["ordre"][0]
        assert grand_livre.valider_ecriture(reg, plan, ecriture_id=ident, horodatage=H,
                                            humain={"par": "comptable", "role": "finance", "voie": "approbation"})[1] \
            is None
    reponse = _appeler(par_nom, "m5_lire_balance_verification", {"au": "2026-10-31", "limite": 20})
    balance = _accepte(reponse)
    assert len(json.dumps(reponse, ensure_ascii=False)) <= m5_outils.BUDGET_SORTIE
    assert balance["comptes_total"] == 31 and balance["prochain_depart"] is not None
    assert balance["equilibree"] and balance["total_debits"] == "30.00"
    assert _code(_appeler(par_nom, "m5_lire_balance_verification", {"au": "2026-10-31", "limite": 21})) \
        == "REJ-GL-LIMITE-INVALIDE"
    with stockage.transaction():
        assert m5_outils.lire_balance_verification("2026-10-31", limite=21)["verdict"]["code"] \
            == "REJ-GL-LIMITE-INVALIDE"
        assert m5_outils.lire_balance_verification("2026-10-31", depart=-1)["verdict"]["code"] \
            == "REJ-GL-LIMITE-INVALIDE"
