"""Grand livre (tranche 1) sur le VRAI socle : outils, file d'approbation N4, portée d'appareil fermée, mentions.

Base SQLite temporaire migrée, vrai manifeste de M5 (mode `ombre`), vraies approbations (`Capacites`, `decider`).
Les factures clientes sont écrites au registre durable des factures par `facturation.py` (le chemin réel des outils
M5.2), puis le grand livre en tire ses brouillons. Personnes, identifiants et montants fictifs (AGENTS.md).
"""

from __future__ import annotations

import contextlib
import dataclasses
import json
import threading
from decimal import Decimal
from pathlib import Path

import m5_financecore.outils as m5_outils
import m5_financecore.outils_operations as outils_operations
import pytest
import yaml
from m5_financecore import analyse, facturation, grand_livre, grand_livre_beancount, operations_registre, taux_fiscaux
from m5_financecore import registre as registre_module
from sqlalchemy import func, select

from opsys import approbations as opsys_approbations
from opsys import contexte, identite, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.departements import lire_manifeste
from opsys.outils import Autonomie, Niveau, executer_atomique
from opsys.stockage.maillons import MaillonsDurables
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
    # Les cinq outils de l'import QuickBooks sont aussi des sorties comptables (test_import_quickbooks_outils.py).
    outils_import = {nom for nom in analyse.SORTIES_COMPTABLES if nom.endswith("_quickbooks")}
    assert len(outils_import) == 5
    assert set(OUTILS_GL) | outils_import == analyse.SORTIES_COMPTABLES <= analyse.SORTIES_D_ANALYSE


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


def test_collision_reelle_note_et_facture_garde_le_brouillon_non_comptabilise(dep, par_nom):
    facture_note = "F-D2-BASE"
    reference_note = "NC-D2-COLLISION"
    identifiant_note = operations_registre.identifiant(
        "op_note_credit_proposee", f"nc:client:{facture_note}:{reference_note}"
    )
    _facturer(facture_note, payer=False)
    _facturer(identifiant_note, payer=False)

    generation = _generer(dep)
    etat = _etat_gl()
    ecriture_facture_base = next(
        brouillon["ecriture_id"]
        for brouillon in generation["brouillons_crees"]
        if etat["ecritures"][brouillon["ecriture_id"]]["piece"]["reference"] == facture_note
        and etat["ecritures"][brouillon["ecriture_id"]]["nature"] == "facture_emise"
    )
    _valider_par_la_file(dep, ecriture_facture_base)

    note = _accepte(
        _appeler(
            par_nom,
            "m5_proposer_note_credit",
            {
                "genre": "client",
                "facture_id": facture_note,
                "reference": reference_note,
                "montant_avant_taxes": "100.00",
                "date_effet": "2026-10-10",
                "motif": "Avoir fictif pour test de collision",
                "horodatage": H,
            },
        )
    )
    assert note["note_id"] == identifiant_note
    _valider_par_la_file(dep, note["ecriture_id"])

    rapprochement = _accepte(
        _appeler(par_nom, "m5_rapprocher_grand_livre", {"debut": "2026-10-01", "fin": "2026-10-31"})
    )
    assert rapprochement["verdict"] == "ECART"
    assert rapprochement["brouillons_non_comptabilises"] == 1
    for role, attendu in (("tps_a_percevoir", "30.00"), ("tvq_a_percevoir", "59.85")):
        result = rapprochement["taxes"][role]
        assert result["verdict"] == "ECART"
        assert any(
            ecart.get("facture_id") == identifiant_note
            and ecart.get("piece_type") == "facture_client"
            and ecart.get("attendu_taxes") == attendu
            and ecart.get("au_grand_livre") == "0.00"
            and ecart.get("raison") == "sans écriture définitive"
            for ecart in result["ecarts"]
        ), result["ecarts"]


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
    assert ecriture["plan_comptable_version"].startswith("2026-v2+client.")
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


def test_manifeste_yaml_invalide_ne_reactive_pas_un_compte_desactive(par_nom, tmp_path, monkeypatch):
    manifeste = tmp_path / "department.yaml"
    monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)
    saisie = {"date_effet": "2026-10-03", "libelle": "Écriture fictive", "piece_type": "manuelle",
              "piece_reference": "M-C3", "horodatage": H,
              "lignes": [{"compte": "5600", "debit": "10.00", "credit": None},
                         {"compte": "1010", "debit": None, "credit": "10.00"}]}

    # Sans manifeste, aucune extension restrictive ne peut être vérifiée.
    assert _code(_appeler(par_nom, "m5_proposer_ecriture_comptable", saisie)) == "REJ-GL-PLAN-INVALIDE"
    assert _maillons("grand_livre") == 0

    # Un manifeste présent mais illisible ne doit pas faire disparaître l'extension restrictive.
    manifeste.write_text("configuration: [\n", encoding="utf-8")
    assert _code(_appeler(par_nom, "m5_proposer_ecriture_comptable", {**saisie, "piece_reference": "M-C3-YAML"})) == (
        "REJ-GL-PLAN-INVALIDE"
    )

    # La configuration valide continue d'interdire explicitement le compte 5600.
    manifeste.write_text(yaml.safe_dump({"configuration": {"grand_livre": {
        "comptes_desactives": ["5600"]}}}), encoding="utf-8")
    assert _code(_appeler(par_nom, "m5_proposer_ecriture_comptable", {**saisie, "piece_reference": "M-C3-VALID"})) == (
        "REJ-GL-COMPTE-INACTIF"
    )


@pytest.mark.parametrize("contenu", [
    "- configuration\n- grand_livre\n",  # racine explicite non-mapping
    "configuration: []\n",                # configuration explicite non-mapping
    "configuration: {grand_livre: [5600]}\n",  # extension explicite mal typée
])
def test_manifeste_comptable_de_forme_invalide_refuse_sans_reactiver_compte(par_nom, tmp_path, monkeypatch,
                                                                            contenu):
    manifeste = tmp_path / "department.yaml"
    monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)
    saisie = {"date_effet": "2026-10-03", "libelle": "Écriture fictive", "piece_type": "manuelle",
              "piece_reference": "M-C3-SHAPE", "horodatage": H,
              "lignes": [{"compte": "5600", "debit": "10.00", "credit": None},
                         {"compte": "1010", "debit": None, "credit": "10.00"}]}
    manifeste.write_text(contenu, encoding="utf-8")
    resultat = _appeler(par_nom, "m5_proposer_ecriture_comptable", saisie)
    assert _code(resultat) == "REJ-GL-PLAN-INVALIDE"
    assert _maillons("grand_livre") == 0


@pytest.mark.parametrize("contenu", ["nom: M5 fictif\n", "configuration:\n  # aucune extension déclarée\n"])
def test_configuration_comptable_omise_dans_un_manifeste_mapping_garde_le_plan_base(par_nom, tmp_path,
                                                                                     monkeypatch, contenu):
    manifeste = tmp_path / "department.yaml"
    monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)
    manifeste.write_text(contenu, encoding="utf-8")
    saisie = {"date_effet": "2026-10-03", "libelle": "Écriture fictive", "piece_type": "manuelle",
              "piece_reference": "M-C3-OMIS", "horodatage": H,
              "lignes": [{"compte": "5600", "debit": "10.00", "credit": None},
                         {"compte": "1010", "debit": None, "credit": "10.00"}]}
    assert _accepte(_appeler(par_nom, "m5_proposer_ecriture_comptable", saisie))["ecriture"]


def test_pg_saisie_et_generation_publiques_concurrentes_preservent_la_chaine_gl(
    monkeypatch, par_nom, m5_postgres_doubles
):
    raison = m5_postgres_doubles.raison_sans_docker()
    if raison is not None:
        pytest.skip(raison)

    with m5_postgres_doubles.postgres_ephemere(stockage_en_memoire=True) as url:
        monkeypatch.setenv(stockage.ENV_URL, url)
        stockage.migrer(url)
        m5_outils.utiliser_stockage_durable()
        _facturer("FICTIF-FACTURE-GENERATION")
        barriere = threading.Barrier(2)
        premiere_terminee = threading.Event()
        verrou_observations = threading.Lock()
        threads_generation_alignes = set()
        original = MaillonsDurables.append
        observations = []

        def aligner_maillons(self, maillon, *, rang_attendu=None):
            manuel = maillon.get("origine") == "saisie"
            genere = maillon.get("origine") == "generation_automatique"
            if (self.departement, self.registre) == (DEPARTEMENT, "grand_livre") and manuel:
                observations.append(maillon.get("origine"))
                barriere.wait(30)
                return original(self, maillon, rang_attendu=rang_attendu)
            if (self.departement, self.registre) == (DEPARTEMENT, "grand_livre") and genere:
                ident_thread = threading.get_ident()
                with verrou_observations:
                    premier = ident_thread not in threads_generation_alignes
                    threads_generation_alignes.add(ident_thread)
                if premier:
                    observations.append(maillon.get("origine"))
                    barriere.wait(30)
                    if not premiere_terminee.wait(30):
                        raise TimeoutError("la saisie manuelle n'a pas terminé")
                    return original(self, maillon, rang_attendu=rang_attendu)
                if not premiere_terminee.wait(30):
                    raise TimeoutError("la saisie manuelle n'a pas terminé")
                return original(self, maillon, rang_attendu=rang_attendu)
            return original(self, maillon, rang_attendu=rang_attendu)

        monkeypatch.setattr(MaillonsDurables, "append", aligner_maillons)
        resultats = {}
        erreurs = {}
        outil_manuel = par_nom["m5_proposer_ecriture_comptable"]
        outil_generation = par_nom["m5_generer_brouillons_comptables"]

        def saisir():
            try:
                resultats["saisie"] = executer_atomique(outil_manuel, {
                    "date_effet": "2026-10-03", "libelle": "Écriture manuelle fictive",
                    "piece_type": "manuelle", "piece_reference": "FICTIF-MANUEL", "horodatage": H,
                    "lignes": [
                        {"compte": "5600", "debit": "10.00", "credit": None},
                        {"compte": "1010", "debit": None, "credit": "10.00"},
                    ],
                })
            except BaseException as exc:
                erreurs["saisie"] = exc
            finally:
                premiere_terminee.set()

        def generer():
            try:
                resultats["generation"] = executer_atomique(outil_generation, {"horodatage": H})
            except BaseException as exc:
                erreurs["generation"] = exc

        threads = [threading.Thread(target=saisir), threading.Thread(target=generer)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(60)
        assert all(not thread.is_alive() for thread in threads), "threads stalled"
        chaine = registre_module.Registre(maillons=stockage.maillons(DEPARTEMENT, "grand_livre")).valider_chaine()
        assert chaine == (True, ""), chaine
        assert set(erreurs) == {"generation"}, erreurs
        assert set(observations) == {"saisie", "generation_automatique"}, observations
        assert isinstance(erreurs["generation"], stockage.EcritureConcurrente), erreurs
        assert set(resultats) == {"saisie"}, resultats
        assert resultats["saisie"]["ok"] and resultats["saisie"]["resultat"]["accepte"]
        assert _maillons("grand_livre") == 1
        stockage.liberer(url)


def test_rapprochement_public_refuse_creation_cliente_dupliquee_apres_faux_concordant(par_nom):
    facture_id = "FICTIF-FACTURE-DOUBLON"
    _facturer(facture_id)
    avant = _accepte(_appeler(
        par_nom, "m5_rapprocher_grand_livre", {"debut": "2026-10-01", "fin": "2026-10-31"}
    ))
    assert avant["verdict"] == "ECART"
    assert avant["taxes"]["tps_a_percevoir"]["attendu_taxes_py"] == "30.00"

    with stockage.transaction():
        registre_cible = m5_outils._registre_factures(None)
        registre_cible.ajouter({
            "type_entree": "facture_creee", "facture_id": facture_id, "statut": "ANNULEE", "horodatage": H,
        })
        assert registre_cible.valider_chaine() == (True, "")

    refus = _appeler(par_nom, "m5_rapprocher_grand_livre", {"debut": "2026-10-01", "fin": "2026-10-31"})
    assert _code(refus) == "REJ-GL-SOURCE-ILLISIBLE"
    assert "deuxième fois" in refus["resultat"]["verdict"]["detail"]


def test_rapprochement_public_refuse_transition_payee_qui_remplace_le_montant(par_nom):
    facture_id = "FICTIF-FACTURE-TRANSITION"
    _facturer(facture_id, payer=False)
    avant = _accepte(_appeler(
        par_nom, "m5_rapprocher_grand_livre", {"debut": "2026-10-01", "fin": "2026-10-31"}
    ))
    assert avant["verdict"] == "ECART"
    assert avant["taxes"]["tps_a_percevoir"]["attendu_taxes_py"] == "30.00"
    assert avant["taxes"]["tvq_a_percevoir"]["attendu_taxes_py"] == "59.85"

    with stockage.transaction():
        registre_cible = m5_outils._registre_factures(None)
        registre_cible.ajouter({
            "type_entree": "transition_facture", "facture_id": facture_id, "statut": "PAYEE",
            "date_paiement": "2026-10-20T10:00:00-04:00", "approbateur": "nathan-fictif",
            "montant_avant_taxes": D("1000.00"), "horodatage": "2026-10-20T10:00:00-04:00",
        })
        assert registre_cible.valider_chaine() == (True, "")

    refus = _appeler(par_nom, "m5_rapprocher_grand_livre", {"debut": "2026-10-01", "fin": "2026-10-31"})
    assert _code(refus) == "REJ-GL-SOURCE-ILLISIBLE"
    assert "montant_avant_taxes" in refus["resultat"]["verdict"]["detail"]


def test_rapprochement_refuse_reenvoi_qui_deplace_date_envoi(par_nom):
    facture_id = "FICTIF-RENVOI-IMPOSSIBLE"
    _facturer(facture_id, payer=True)
    avant = _accepte(_appeler(
        par_nom, "m5_rapprocher_grand_livre", {"debut": "2026-10-01", "fin": "2026-10-31"}
    ))
    assert avant["taxes"]["tps_a_percevoir"]["attendu_taxes_py"] == "30.00"
    with stockage.transaction():
        m5_outils._registre_factures(None).ajouter({
            "type_entree": "transition_facture", "facture_id": facture_id, "statut": "ENVOYEE",
            "date_envoi": "2026-11-15T09:00:00-04:00", "horodatage": H,
        })

    refus = _appeler(par_nom, "m5_rapprocher_grand_livre", {"debut": "2026-10-01", "fin": "2026-10-31"})
    assert _code(refus) == "REJ-GL-SOURCE-ILLISIBLE"
    assert "impossible depuis le statut courant" in refus["resultat"]["verdict"]["detail"]


def test_rapprochement_refuse_annulation_apres_emission(par_nom):
    facture_id = "FICTIF-ANNULATION-EMISE"
    _facturer(facture_id, payer=False)
    with stockage.transaction():
        m5_outils._registre_factures(None).ajouter({
            "type_entree": "transition_facture", "facture_id": facture_id, "statut": "ANNULEE",
            "horodatage": H,
        })

    refus = _appeler(par_nom, "m5_rapprocher_grand_livre", {"debut": "2026-10-01", "fin": "2026-10-31"})
    assert _code(refus) == "REJ-GL-SOURCE-ILLISIBLE"
    detail = refus["resultat"]["verdict"]["detail"]
    assert "ne vérifie pas le traitement fiscal de la contrepartie d'annulation" in detail


def test_rapprochement_refuse_creation_annulee_historique_avec_date_envoi(par_nom):
    facture_id = "FICTIF-ANNULEE-HISTORIQUE-EMISE"
    with stockage.transaction():
        m5_outils._registre_factures(None).ajouter({
            "type_entree": "facture_creee", "facture_id": facture_id, "statut": "ANNULEE",
            "date_envoi": "2026-10-10T09:00:00-04:00", "horodatage": H,
        })

    refus = _appeler(par_nom, "m5_rapprocher_grand_livre", {"debut": "2026-10-01", "fin": "2026-10-31"})
    assert _code(refus) == "REJ-GL-SOURCE-ILLISIBLE"
    detail = refus["resultat"]["verdict"]["detail"]
    assert "porte une date_envoi" in detail
    assert "ne vérifie pas le traitement fiscal de la contrepartie d'annulation" in detail


def test_rapprochement_refuse_annulation_brouillon_historique_portant_date_envoi(par_nom):
    facture_id = "FICTIF-BROUILLON-DATE-ANNULE"
    with stockage.transaction():
        registre_cible = m5_outils._registre_factures(None)
        registre_cible.ajouter({
            "type_entree": "facture_creee", "facture_id": facture_id, "statut": "BROUILLON",
            "date_envoi": "2026-10-10T09:00:00-04:00", "horodatage": H,
        })
        registre_cible.ajouter({
            "type_entree": "transition_facture", "facture_id": facture_id, "statut": "ANNULEE",
            "horodatage": H,
        })
        assert registre_cible.valider_chaine() == (True, "")

    refus = _appeler(par_nom, "m5_rapprocher_grand_livre", {"debut": "2026-10-01", "fin": "2026-10-31"})
    assert _code(refus) == "REJ-GL-SOURCE-ILLISIBLE"
    detail = refus["resultat"]["verdict"]["detail"]
    assert "annulation" in detail
    assert "date_envoi" in detail
    assert "ne vérifie pas le traitement fiscal de la contrepartie d'annulation" in detail


def test_rapprochement_preserve_creation_annulee_historique_sans_date_envoi(par_nom):
    with stockage.transaction():
        m5_outils._registre_factures(None).ajouter({
            "type_entree": "facture_creee", "facture_id": "FICTIF-ANNULEE-SANS-ENVOI", "statut": "ANNULEE",
            "horodatage": H,
        })

    resultat = _accepte(_appeler(
        par_nom, "m5_rapprocher_grand_livre", {"debut": "2026-10-01", "fin": "2026-10-31"}
    ))
    assert resultat["taxes"]["tps_a_percevoir"]["attendu_taxes_py"] == "0.00"


def test_rapprochement_refuse_facture_emise_partielle(par_nom, dep):
    facture_id = "FICTIF-FACTURE-PARTIELLE"
    with stockage.transaction():
        m5_outils._registre_factures(None).ajouter({
            "type_entree": "facture_creee", "facture_id": facture_id, "statut": "ENVOYEE",
            "date_envoi": "2026-10-10T09:00:00-04:00", "montant_avant_taxes": D("1000.00"),
            "horodatage": H,
        })

    saisie = _appeler(par_nom, "m5_proposer_ecriture_comptable", {
        "date_effet": "2026-10-10", "libelle": "Taxe fictive de facture partielle",
        "piece_type": "facture_client", "piece_reference": facture_id, "horodatage": H,
        "lignes": [
            {"compte": "1100", "debit": "1149.75", "credit": None},
            {"compte": "4100", "debit": None, "credit": "1000.00"},
            {"compte": "2300", "debit": None, "credit": "50.00"},
            {"compte": "2310", "debit": None, "credit": "99.75"},
        ],
    })
    ecriture = _accepte(saisie)["ecriture"]
    _valider_par_la_file(dep, ecriture["ecriture_id"])

    refus = _appeler(par_nom, "m5_rapprocher_grand_livre", {"debut": "2026-10-01", "fin": "2026-10-31"})
    assert _code(refus) == "REJ-GL-SOURCE-ILLISIBLE"
    assert "montants ou taxes" in refus["resultat"]["verdict"]["detail"]


def test_rapprochement_refuse_facture_emise_avec_montants_sous_cent(par_nom):
    with stockage.transaction():
        registre = m5_outils._registre_factures(None)
        registre.ajouter({
            "type_entree": "facture_creee", "facture_id": "FICTIF-MONTANTS-SOUS-CENT",
            "statut": "ENVOYEE", "date_envoi": "2026-10-10T09:00:00-04:00",
            "montant_avant_taxes": D("100.005"), "total_taxes": D("14.975"),
            "montant_apres_taxes": D("114.980"),
            "taxes": [
                {"id": "tps_federale", "montant": D("5.000")},
                {"id": "tvq_quebec", "montant": D("9.975")},
            ],
            "horodatage": H,
        })
        assert registre.valider_chaine() == (True, "")

    refus = _appeler(par_nom, "m5_rapprocher_grand_livre", {"debut": "2026-10-01", "fin": "2026-10-31"})
    assert _code(refus) == "REJ-GL-SOURCE-ILLISIBLE"
    assert "montants ou taxes" in refus["resultat"]["verdict"]["detail"]


def test_lecture_montants_facture_preserve_taxes_nulles_au_cent():
    piece = {
        "montant_avant_taxes": D("100.00"),
        "total_taxes": D("0.00"),
        "montant_apres_taxes": D("100.00"),
        "taxes": [
            {"id": "tps_federale", "montant": D("0.00")},
            {"id": "tvq_quebec", "montant": D("0.00")},
        ],
    }
    resultat = grand_livre.lire_montants_facture(piece, "client")
    assert resultat == (D("100.00"), D("100.00"), {
        "tps_a_percevoir": D("0.00"), "tvq_a_percevoir": D("0.00"),
    })


def test_lecture_montants_facture_refuse_taxes_sous_cent_meme_si_total_au_cent():
    piece = {
        "montant_avant_taxes": D("100.00"),
        "total_taxes": D("0.01"),
        "montant_apres_taxes": D("100.01"),
        "taxes": [
            {"id": "tps_federale", "montant": D("0.005")},
            {"id": "tvq_quebec", "montant": D("0.005")},
        ],
    }
    assert grand_livre.lire_montants_facture(piece, "client") is None


def test_lecture_montants_facture_refuse_sous_total_sous_cent_sans_taxes():
    piece = {
        "montant_avant_taxes": D("100.005"),
        "total_taxes": D("0.00"),
        "montant_apres_taxes": D("100.005"),
        "taxes": [],
    }
    assert grand_livre.lire_montants_facture(piece, "client") is None


def test_rapprochement_refuse_date_envoi_illisible(par_nom):
    facture_id = "FICTIF-ENVOI-INVALIDE"
    with stockage.transaction():
        registre_cible = m5_outils._registre_factures(None)
        _, verdict = facturation.creer_facture_brouillon(
            facture_id, f"CH-{facture_id}", f"D-{facture_id}", "client-fictif",
            _lignes_facture(), "2026-10-01T09:00:00-04:00", _taux(), registre_cible,
        )
        assert verdict is None
        registre_cible.ajouter({
            "type_entree": "transition_facture", "facture_id": facture_id, "statut": "ENVOYEE",
            "date_envoi": "2026-99-99", "horodatage": H,
        })

    refus = _appeler(par_nom, "m5_rapprocher_grand_livre", {"debut": "2026-10-01", "fin": "2026-10-31"})
    assert _code(refus) == "REJ-GL-SOURCE-ILLISIBLE"
    assert "date_envoi illisible" in refus["resultat"]["verdict"]["detail"]


@pytest.mark.parametrize("date_envoi", ["2026-10-10T09:00:00-04:00", None])
def test_rapprochement_verifie_date_creation_historique_emise(par_nom, date_envoi):
    with stockage.transaction():
        m5_outils._registre_factures(None).ajouter({
            "type_entree": "facture_creee", "facture_id": "FICTIF-CREATION-EMISE-DATE",
            "statut": "ENVOYEE", "date_envoi": date_envoi, "horodatage": H,
            "montant_avant_taxes": D("100.00"), "total_taxes": D("0.00"),
            "montant_apres_taxes": D("100.00"), "taxes": [],
        })
    reponse = _appeler(par_nom, "m5_rapprocher_grand_livre", {"debut": "2026-10-01", "fin": "2026-10-31"})
    if date_envoi is None:
        assert _code(reponse) == "REJ-GL-SOURCE-ILLISIBLE"
        assert "sans date_envoi lisible" in reponse["resultat"]["verdict"]["detail"]
    else:
        _accepte(reponse)


def test_rapprochement_refuse_brouillon_partiel_lors_transition_envoyee(par_nom):
    facture_id = "FICTIF-BROUILLON-PARTIEL"
    with stockage.transaction():
        registre_cible = m5_outils._registre_factures(None)
        registre_cible.ajouter({
            "type_entree": "facture_creee", "facture_id": facture_id, "statut": "BROUILLON", "horodatage": H,
        })
        registre_cible.ajouter({
            "type_entree": "transition_facture", "facture_id": facture_id, "statut": "ENVOYEE",
            "date_envoi": "2026-10-10T09:00:00-04:00", "horodatage": H,
        })

    refus = _appeler(par_nom, "m5_rapprocher_grand_livre", {"debut": "2026-10-01", "fin": "2026-10-31"})
    assert _code(refus) == "REJ-GL-SOURCE-ILLISIBLE"
    assert "sans montants ou taxes cohérents" in refus["resultat"]["verdict"]["detail"]


def test_controle_taxes_sans_capture_epingle_projection_apres_validation(monkeypatch):
    ctx, refus = outils_operations.contexte_operations()
    assert refus is None and "registre_factures_cloture" not in ctx
    registre_live = m5_outils._registre_factures(None)
    verifier = m5_outils._verifier_sources_rapprochement
    projetes = {}

    def verifier_puis_intercaler(nom, maillons):
        resultat = verifier(nom, maillons)
        if nom == m5_outils._NOM_REGISTRE_FACTURES:
            registre_live.ajouter({
                "type_entree": "facture_creee", "facture_id": "FICTIF-INTERCALE", "statut": "ENVOYEE",
                "date_envoi": "2026-10-10T09:00:00-04:00", "montant_avant_taxes": D("1000.00"),
                "horodatage": H,
            })
        return resultat

    def rapprocher_capture(etat, plan, factures, taux, **kwargs):
        projetes["factures"] = list(factures)
        return {"verdict": "CONCORDANT"}, None

    monkeypatch.setattr(m5_outils, "_verifier_sources_rapprochement", verifier_puis_intercaler)
    monkeypatch.setattr(grand_livre, "rapprocher", rapprocher_capture)
    resultat, refus = outils_operations.controle_taxes_bornes(ctx, "2026-10-01", "2026-10-31")

    assert refus is None and resultat == {"verdict": "CONCORDANT"}
    assert projetes["factures"] == []


def test_rapprochement_preserve_annulation_historique_depuis_brouillon(par_nom):
    facture_id = "FICTIF-ANNULATION-BROUILLON"
    with stockage.transaction():
        registre_cible = m5_outils._registre_factures(None)
        _, verdict = facturation.creer_facture_brouillon(
            facture_id, f"CH-{facture_id}", f"D-{facture_id}", "client-fictif",
            _lignes_facture(), "2026-10-01T09:00:00-04:00", _taux(), registre_cible,
        )
        assert verdict is None
        registre_cible.ajouter({
            "type_entree": "transition_facture", "facture_id": facture_id, "statut": "ANNULEE", "horodatage": H,
        })

    resultat = _accepte(_appeler(
        par_nom, "m5_rapprocher_grand_livre", {"debut": "2026-10-01", "fin": "2026-10-31"}
    ))
    assert resultat["taxes"]["tps_a_percevoir"]["attendu_taxes_py"] == "0.00"


@pytest.mark.parametrize("statut", [[], {"statut": "PAYEE"}])
@pytest.mark.parametrize("type_entree", ["facture_creee", "transition_facture"])
def test_rapprochement_refuse_statut_non_textuel_sans_exception(par_nom, statut, type_entree):
    facture_id = "FICTIF-STATUT-NON-TEXTUEL"
    _facturer(facture_id, payer=False)
    with stockage.transaction():
        m5_outils._registre_factures(None).ajouter({
            "type_entree": type_entree,
            "facture_id": facture_id,
            "statut": statut,
            "horodatage": H,
        })

    refus = _appeler(par_nom, "m5_rapprocher_grand_livre", {"debut": "2026-10-01", "fin": "2026-10-31"})
    assert _code(refus) == "REJ-GL-SOURCE-ILLISIBLE"
    assert "statut" in refus["resultat"]["verdict"]["detail"]


@pytest.mark.parametrize("identifiant", [None, 7, []])
def test_rapprochement_refuse_identifiant_transition_non_textuel(par_nom, identifiant):
    with stockage.transaction():
        m5_outils._registre_factures(None).ajouter({
            "type_entree": "transition_facture", "facture_id": identifiant,
            "statut": "ENVOYEE", "horodatage": H,
        })
    refus = _appeler(par_nom, "m5_rapprocher_grand_livre", {"debut": "2026-10-01", "fin": "2026-10-31"})
    assert _code(refus) == "REJ-GL-SOURCE-ILLISIBLE"


def test_rapprochement_refuse_transition_sans_facture_preexistante(par_nom):
    with stockage.transaction():
        m5_outils._registre_factures(None).ajouter({
            "type_entree": "transition_facture", "facture_id": "FICTIF-INCONNU",
            "statut": "ENVOYEE", "horodatage": H,
        })
    refus = _appeler(par_nom, "m5_rapprocher_grand_livre", {"debut": "2026-10-01", "fin": "2026-10-31"})
    assert _code(refus) == "REJ-GL-SOURCE-ILLISIBLE"


def test_rapprochement_accepte_transition_envoyee_avec_tous_champs_emission_historiques(par_nom):
    facture_id = "FICTIF-EMISSION-HISTORIQUE"
    with stockage.transaction():
        registre_cible = m5_outils._registre_factures(None)
        _, verdict = facturation.creer_facture_brouillon(
            facture_id, f"CH-{facture_id}", f"D-{facture_id}", "client-fictif",
            _lignes_facture(), "2026-10-01T09:00:00-04:00", _taux(), registre_cible,
        )
        assert verdict is None
        _, verdict = facturation.envoyer_facture(
            facture_id,
            "2026-10-02T09:00:00-04:00",
            registre_cible,
            {
                "numero_facture": "FICTIF-2026-001",
                "sequence_facture": 1,
                "echeance": "2026-10-31",
                "delai_paiement_jours": 30,
            },
        )
        assert verdict is None

    resultat = _accepte(_appeler(
        par_nom, "m5_rapprocher_grand_livre", {"debut": "2026-10-01", "fin": "2026-10-31"}
    ))
    assert resultat["taxes"]["tps_a_percevoir"]["attendu_taxes_py"] == "30.00"


def test_rapprochement_ignore_type_entree_hors_projection_factures(par_nom):
    _facturer("FICTIF-EVENEMENT-AUTRE-FAMILLE")
    with stockage.transaction():
        m5_outils._registre_factures(None).ajouter({
            "type_entree": "demande_creee", "horodatage": H, "libelle_fictif": "hors projection factures",
        })

    resultat = _accepte(_appeler(
        par_nom, "m5_rapprocher_grand_livre", {"debut": "2026-10-01", "fin": "2026-10-31"}
    ))
    assert resultat["taxes"]["tps_a_percevoir"]["attendu_taxes_py"] == "30.00"
