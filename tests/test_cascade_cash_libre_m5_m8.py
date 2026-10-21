"""PLAN T4.19-b — le cash libre que M5 constate jusqu'à la vue exécutive de M8 (DEFINITION-PRODUIT §7 M5 « source de
vérité financière », §7 M8 « pour la finance, M8 consomme M5 et ne recalcule pas »), par le VRAI bus, sur les VRAIS
départements, sans doublure.

M5 calcule le cash libre d'après ses registres durables et les déclarations du propriétaire, et le publie quand l'admin
le lui fait constater (`m5_constater_cash_libre`, T1 : l'admin le lance depuis son appareil, identité confirmée en
base) → `m5.cash_libre_constate` → le bus livre à M8 → `m8_lire_vue_executive` le montre tel quel, avec son âge.

Ce que ce fichier prouve, de bout en bout :
- M5 calcule et publie, M8 le montre : les mêmes montants, à la cent près, que la lecture de M5 (`m5_etat_tresorerie`) ;
- un cash libre « non calculable, manque X » passe tel quel jusqu'à la vue (statut, manque, repère `au_plus`), jamais un
  zéro ; il devient un cash libre calculé quand la déclaration arrive ;
- le rejeu ne fait aucun doublon : redire un constat ne publie rien, un rejeu du bus ne livre rien, M8 garde un fait ;
- un retour à des données antérieures (A, B, puis A) est un nouveau constat, et le dernier est celui qu'on voit ;
- un constat vieillit : le lendemain, la vue dit un jour de plus, sans que M8 n'ait d'horloge ;
- ni l'employé ni le vendeur ne peuvent le constater ni le lire ; M8 ne publie rien et sa lecture n'écrit rien.

Fichier NOUVEAU : le patron des helpers est celui de `test_cascade_mesure_m8_m9.py` et des tests de M5, recopié pour ne
pas dépendre de fichiers que d'autres agents modifient. Identifiants, personnes et montants fictifs. Le cas de
référence est celui de `departments/m05-financecore/tests/test_cash_libre.py` (calculé à la main) : solde 37654.33,
TPS/TVQ 1981.69, paies 4200.00, DAS 1350.75, comptes à payer 459.91, dettes 800.00, réserves 1000.00, donc un cash
libre de 27861.98.
"""

from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal

import m5_financecore.outils as m5_outils
import pytest
import yaml
from m5_financecore import comptes_a_payer, facturation, registre, taux_fiscaux
from m5_financecore.analyse import MENTION_ANALYSE_PREPARATOIRE as MENTION
from m8_analytics import outils as m8_outils
from sqlalchemy import select

from opsys import contexte, evenements, idempotence, identite, stockage
from opsys.capacites import Capacites
from opsys.contexte import IdentiteAppelante
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS, META

FICTIF = True
D = Decimal
TYPE = "m5.cash_libre_constate"
M5, M8 = "m05-financecore", "m08-analytics"
JOUR = "2026-09-29"
LENDEMAIN = "2026-09-30"
MOT_DE_PASSE = "un-mot-de-passe-suffisamment-long"
ADMIN = IdentiteAppelante(personne="proprio", role="admin")
EMPLOYE = IdentiteAppelante(personne="employe.un", role="employee")
VENDEUR = IdentiteAppelante(personne="vendeur.un", role="seller")
CONFIDENCES = ("Marc Tremblay", "brouillon de paie", "estimation du CPA", "relevé du prêt", "Employé Un", "Vendeur Un")

CONFIGURATION = {
    "fiscal": {"frequence_tps_tvq": "trimestrielle", "mois_fin_exercice": 12, "taxes_remises_jusqu_au": "2026-06-30"},
    "obligations_declarees": {
        "paies": {"montant": "4200.00", "source": "brouillon de paie de Marc Tremblay (fictif)", "au": "2026-09-25"},
        "das": {"montant": "1350.75", "source": "estimation du CPA (fictive)", "au": "2026-09-25"},
        "dettes": {"montant": "800.00", "source": "relevé du prêt camion (fictif)", "au": "2026-09-01"},
    },
}


def _sans(configuration, composante):
    obligations = {c: v for c, v in configuration["obligations_declarees"].items() if c != composante}
    return {**configuration, "obligations_declarees": obligations}


def _avec_dettes(configuration, montant):
    dettes = {**configuration["obligations_declarees"]["dettes"], "montant": montant}
    return {**configuration, "obligations_declarees": {**configuration["obligations_declarees"], "dettes": dettes}}


# ---------------------------------------------------------------------------------------------- installation
@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-t419b.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    m5_outils.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "vendeur.un", "Vendeur Un (fictif)", MOT_DE_PASSE, ["seller"])
        identite.creer_personne(cnx, "employe.un", "Employé Un (fictif)", MOT_DE_PASSE, ["employee"])
        identite.creer_personne(cnx, "proprio", "Propriétaire (fictif)", MOT_DE_PASSE, ["admin", "nathan_owner"])
    try:
        yield url
    finally:
        stockage.liberer()


@pytest.fixture
def declare(tmp_path, monkeypatch):
    """Ce que le propriétaire a écrit sous `configuration` dans le manifeste de M5, relu à chaque appel."""
    def _declarer(configuration):
        manifeste = tmp_path / "department-m5.yaml"
        manifeste.write_text(yaml.safe_dump({"configuration": configuration}, allow_unicode=True), encoding="utf-8")
        monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)
    return _declarer


@pytest.fixture
def deps():
    return charger_departements()


def _mouvement(reg, montant, type_mouvement, horodatage):
    registre.enregistrer_mouvement({"montant": D(montant), "type_mouvement": type_mouvement, "horodatage": horodatage,
                                    "classe_retention": "STANDARD", "source": "test-fictif"}, reg)


def _peupler_mouvements():
    with stockage.transaction():
        reg = m5_outils._registre_mouvements(None)
        _mouvement(reg, "50000.00", "ENCAISSEMENT", "2026-08-01T12:00:00-04:00")
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
                                                    ("e-2", "PO-2", "20", "2026-09-16T09:00:00-04:00")):
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
def cas_fictif(base_durable, declare):
    """Le cas de référence complet : registres durables de M5 peuplés, manifeste qui déclare tout."""
    taux, erreurs = taux_fiscaux.charger_taux_fiscaux(m5_outils._CHEMIN_TAUX_FISCAUX)
    assert erreurs == []
    declare(CONFIGURATION)
    _peupler_mouvements()
    _peupler_factures_clients(taux)
    _peupler_a_payer(taux)


# ---------------------------------------------------------------------------------------------- les étapes
def _iso(base: dt.datetime, secondes: int) -> str:
    return (base + dt.timedelta(seconds=secondes)).isoformat()


def _drainer(deps, base: dt.datetime, *, max_tours: int = 10, pas_s: int = 90) -> dict:
    """Livre le bus à M8 seul, jusqu'à quiescence (boucle bornée) : M5 n'a rien à recevoir ici."""
    t, total = base, {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0}
    for _ in range(max_tours):
        resume = evenements.repartir({M8: deps[M8]}, maintenant=_iso(t, 0))
        for cle in total:
            total[cle] += resume[cle]
        if resume["livres"] == 0:
            return total
        t = t + dt.timedelta(seconds=pas_s)
    raise AssertionError(f"le bus n'a pas atteint la quiescence après {max_tours} tours : {total}")


def _constater(deps, jour=JOUR, cle="cle-constat-1", appelante=ADMIN):
    """L'admin lance le constat depuis son appareil : le chemin réel des appels (`Capacites`), sans file."""
    capacites = Capacites({M5: deps[M5]}, stockage.transaction)
    meta = idempotence.Meta(cle=cle, appareil="tel-admin-t419b", horodatage_appareil="2026-09-29T10:00:00-04:00")
    with contexte.appele_par_appareil(appelante):
        return capacites.appeler("m5_constater_cash_libre", {"aujourd_hui": jour}, meta)


def _constat_accepte(deps, jour=JOUR, cle="cle-constat-1"):
    reponse = _constater(deps, jour, cle)
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _etat_de_tresorerie_de_m5(deps):
    """La lecture de M5 lui-même (T0, admin) : le cash libre que M8 ne doit ni recalculer ni contredire."""
    par_nom = {o.nom: o for o in deps[M5].charger_outils()}
    with contexte.appele_par_appareil(ADMIN):
        reponse = executer_atomique(par_nom["m5_etat_tresorerie"], {})
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]["cash_libre"]


def _vue_reponse(deps, appelante=ADMIN, aujourd_hui=None):
    par_nom = {o.nom: o for o in deps[M8].charger_outils()}
    arguments = {} if aujourd_hui is None else {"aujourd_hui": aujourd_hui}
    with contexte.appele_par_appareil(appelante):
        return executer_atomique(par_nom["m8_lire_vue_executive"], arguments)


def _vue(deps, aujourd_hui=None, appelante=ADMIN):
    reponse = _vue_reponse(deps, appelante, aujourd_hui)
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _publies():
    """Les charges `m5.cash_libre_constate` publiées, par rang."""
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS.c.evenement_id, EVENEMENTS_SORTANTS.c.charge).where(
            EVENEMENTS_SORTANTS.c.type_evenement == TYPE)).all()
    return sorted(((ligne.evenement_id, codec.decoder(ligne.charge)) for ligne in lignes),
                  key=lambda paire: paire[1]["sequence"])


def _types_publies() -> set[str]:
    with stockage.transaction() as cnx:
        return {ligne[0] for ligne in cnx.execute(select(EVENEMENTS_SORTANTS.c.type_evenement)).all()}


def _faits_de_m8():
    with stockage.transaction():
        return list(stockage.maillons(M8, "faits_cash_libre"))


def _recus_de_m8():
    with stockage.transaction() as cnx:
        return cnx.execute(select(EVENEMENTS_RECUS.c.evenement_id, EVENEMENTS_RECUS.c.statut,
                                  EVENEMENTS_RECUS.c.resultat).where(EVENEMENTS_RECUS.c.consommateur == M8)).all()


def _instantane_base():
    with stockage.transaction() as cnx:
        return {nom: sorted(tuple(map(str, ligne)) for ligne in cnx.execute(select(table)).fetchall())
                for nom, table in META.tables.items()}


BASE = dt.datetime(2026, 9, 29, 11, 0, 0, tzinfo=dt.timezone(dt.timedelta(hours=-4)))


# =============================================================================================
# 1. M5 calcule et publie, M8 le montre : les mêmes montants, à la cent près
# =============================================================================================
def test_m5_constate_le_bus_livre_et_la_vue_de_m8_montre_le_cash_libre_de_m5_tel_quel(cas_fictif, deps):
    corps = _constat_accepte(deps)
    assert (corps["publie"], corps["deja_constate"]) == (True, False)
    assert corps["mention"] == MENTION, "la réponse de M5 porte la mention obligatoire des analyses"
    total = _drainer(deps, BASE)
    assert total["traites"] == 1 and total["echecs"] == 0 and total["quarantaines"] == 0, total
    ((evenement_id, charge),) = _publies()
    assert [tuple(r[:2]) for r in _recus_de_m8()] == [(evenement_id, "traite")]
    resume_du_recu = json.loads(_recus_de_m8()[0].resultat)
    assert resume_du_recu["enregistre"] is True and resume_du_recu["deja_enregistre"] is False
    assert "27861.98" not in json.dumps(resume_du_recu) and "cash_libre_cad" not in resume_du_recu, (
        "le résumé du reçu, que le bus range, ne porte aucun montant")

    avant = _instantane_base()
    vue = _vue(deps, "2026-10-02")
    assert _instantane_base() == avant, "la lecture de la vue n'écrit rien et ne publie rien"

    section = vue["cash_libre"]
    constat = section["constat"]
    assert section["statut"] == "lu" and section["n_constats_recus"] == 1
    assert (constat["sequence"], constat["date_reference"]) == (1, JOUR)
    assert evenement_id.startswith(f"m5-cash-libre-1-{JOUR}-") and "evenement_id" not in constat
    assert (constat["statut"], constat["cash_libre_cad"], constat["au_plus_cad"]) == ("CALCULE", "27861.98", None)
    assert constat["en_deficit"] is False and constat["manque"] == []
    assert constat["composantes"] == {
        "solde": "37654.33", "taxes_a_remettre": "1981.69", "paies": "4200.00", "das": "1350.75",
        "comptes_a_payer": "459.91", "dettes": "800.00", "reserves": "1000.00",
    }
    assert constat["mention"] == MENTION and constat["reserves"] == ["REJ-AP-UNITE-PRIX-NON-CONFIRMEE"]
    assert section["age"] == {"jours": 3, "aujourd_hui": "2026-10-02"}
    assert [m for m in vue["manques"] if m["champ"] == "cash_libre"] == []
    # ce que la vue montre est la charge de M5, valeur pour valeur
    assert constat["lecture"] == charge["lecture"] and constat["cash_libre_cad"] == charge["cash_libre_cad"]
    assert list(constat["composantes"].values()) == [
        charge["solde"]["montant_cad"], *(c["montant_cad"] for c in charge["composantes"])]
    assert len(json.dumps(vue, ensure_ascii=False)) < m8_outils.BUDGET_SORTIE


def test_le_montant_de_la_vue_est_celui_que_m5_lit_lui_meme_aucun_second_calcul(cas_fictif, deps):
    lu_par_m5 = _etat_de_tresorerie_de_m5(deps)

    _constat_accepte(deps)
    _drainer(deps, BASE)
    constat = _vue(deps)["cash_libre"]["constat"]

    assert constat["cash_libre_cad"] == lu_par_m5["cash_libre"] == "27861.98"
    assert constat["en_deficit"] == lu_par_m5["en_deficit"] and constat["lecture"] == lu_par_m5["lecture"]
    assert constat["composantes"] == {"solde": lu_par_m5["solde"]["montant"],
                                      **{c["id"]: c["montant"] for c in lu_par_m5["composantes"]}}


def test_aucun_texte_du_proprietaire_ni_aucune_personne_n_arrive_dans_la_vue(cas_fictif, deps):
    _constat_accepte(deps)
    _drainer(deps, BASE)

    texte = json.dumps(_vue(deps, JOUR), ensure_ascii=False)
    faits = json.dumps(_faits_de_m8(), ensure_ascii=False)

    for confidence in CONFIDENCES:
        assert confidence not in texte and confidence not in faits, confidence
    assert "crédits de taxes sur intrants" not in texte, "les hypothèses ne sont pas reprises dans la vue"


# =============================================================================================
# 2. « Non calculable, manque X » passe tel quel, jamais un zéro
# =============================================================================================
def test_un_cash_libre_non_calculable_de_m5_passe_tel_quel_jusqu_a_la_vue(cas_fictif, deps, declare):
    declare(_sans(CONFIGURATION, "paies"))
    corps = _constat_accepte(deps)
    assert corps["constat"]["statut"] == "NON_CALCULABLE"
    _drainer(deps, BASE)

    vue = _vue(deps, LENDEMAIN)

    section = vue["cash_libre"]
    constat = section["constat"]
    assert section["statut"] == "lu", "M8 a reçu un constat : c'est M5 qui dit « non calculable »"
    assert (constat["statut"], constat["cash_libre_cad"], constat["en_deficit"]) == ("NON_CALCULABLE", None, None)
    assert constat["au_plus_cad"] == "32061.98"
    assert constat["manque"] == ["paies : REJ-CASH-PAIE-A-DECLARER"]
    assert constat["composantes"]["paies"] is None and constat["composantes"]["das"] == "1350.75"
    assert "PAS de l'argent disponible" in constat["lecture"]
    assert section["age"] == {"jours": 1, "aujourd_hui": LENDEMAIN}
    assert [m["raison"] for m in vue["manques"] if m["champ"] == "cash_libre"] == [
        "M5 a constaté le cash libre « non calculable » le 2026-09-29 : voir cash_libre.constat.manque"]
    assert '"cash_libre_cad": "0' not in json.dumps(vue, ensure_ascii=False)


def test_la_declaration_qui_arrive_apres_coup_donne_un_constat_calcule_qui_remplace_le_non_calculable(
        cas_fictif, deps, declare):
    declare(_sans(CONFIGURATION, "paies"))
    _constat_accepte(deps, cle="cle-1")
    _drainer(deps, BASE)
    assert _vue(deps)["cash_libre"]["constat"]["statut"] == "NON_CALCULABLE"

    declare(CONFIGURATION)  # le propriétaire a déclaré les paies
    corps = _constat_accepte(deps, cle="cle-2")
    _drainer(deps, BASE + dt.timedelta(minutes=5))

    vue = _vue(deps)
    assert corps["publie"] is True and [c["sequence"] for _, c in _publies()] == [1, 2]
    assert vue["cash_libre"]["constat"]["statut"] == "CALCULE"
    assert vue["cash_libre"]["constat"]["cash_libre_cad"] == "27861.98" and vue["cash_libre"]["n_constats_recus"] == 2
    assert [m for m in vue["manques"] if m["champ"] == "cash_libre"] == []


def test_sans_aucune_declaration_le_manifeste_livre_donne_un_constat_non_calculable_pas_un_chiffre(base_durable, deps):
    """Le vrai manifeste de M5 (GATE NATHAN) ne déclare rien : taxes, paies, DAS, dettes manquent, le constat le dit."""
    _peupler_mouvements()

    corps = _constat_accepte(deps)
    _drainer(deps, BASE)
    constat = _vue(deps)["cash_libre"]["constat"]

    assert corps["constat"]["statut"] == "NON_CALCULABLE"
    assert constat["statut"] == "NON_CALCULABLE" and constat["cash_libre_cad"] is None
    assert {m.split(" : ")[0] for m in constat["manque"]} >= {"paies", "das", "dettes"}


def test_le_tout_premier_jour_sans_solde_ni_declaration_la_vue_montre_le_constat_et_tient_sous_la_borne(
        base_durable, deps):
    """L'installation : aucun mouvement, aucune déclaration, aucun fait dans M8. C'est le premier constat que
    l'admin fera constater, donc le premier que la vue devra montrer : six manques, aucun chiffre. La vue ne doit ni se
    refuser ni perdre sa décomposition : elle garde plus de 150 caractères de marge sous la borne du socle."""
    corps = _constat_accepte(deps)
    _drainer(deps, BASE)

    vue = _vue(deps, JOUR)

    constat = vue["cash_libre"]["constat"]
    assert corps["constat"]["statut"] == "NON_CALCULABLE" and corps["constat"]["au_plus_cad"] is None
    assert (constat["statut"], constat["cash_libre_cad"], constat["au_plus_cad"]) == ("NON_CALCULABLE", None, None)
    assert [m.split(" : ")[0] for m in constat["manque"]] == [
        "solde", "taxes_a_remettre", "paies", "das", "dettes", "reserves"]
    assert constat["composantes"]["solde"] is None and constat["composantes"]["comptes_a_payer"] == "0.00"
    assert "composantes_omises" not in constat
    assert len(json.dumps(vue, ensure_ascii=False)) < m8_outils.BUDGET_SORTIE - 150


# =============================================================================================
# 3. Le rejeu ne fait aucun doublon
# =============================================================================================
def test_redire_le_constat_ne_publie_rien_et_un_rejeu_du_bus_ne_livre_rien(cas_fictif, deps):
    _constat_accepte(deps, cle="cle-1")
    _drainer(deps, BASE)
    apres_le_premier = _instantane_base()

    second = _constat_accepte(deps, cle="cle-2")  # une autre clé d'appareil : la déduplication est celle de M5

    assert (second["publie"], second["deja_constate"]) == (False, True)
    assert second["constat"]["sequence"] == 1 and second["constat"]["evenement_id"] == _publies()[0][0]
    changees = {nom for nom, lignes in _instantane_base().items() if lignes != apres_le_premier[nom]}
    # la clé d'appareil, la validation du N3 et son journal : aucun événement, aucun registre de M5 ni de M8
    assert changees <= {"mutations_appliquees", "approbations", "journal"}, changees
    assert len(_publies()) == 1
    assert _drainer(deps, BASE + dt.timedelta(minutes=5))["livres"] == 0, "rien de neuf à livrer"
    assert len(_faits_de_m8()) == 1 and len(_recus_de_m8()) == 1


def test_le_renvoi_de_la_meme_cle_d_appareil_rejoue_la_reponse_sans_rien_publier(cas_fictif, deps):
    premiere = _constater(deps, cle="cle-unique")
    assert premiere["ok"] is True and premiere["rejoue"] is False

    renvoi = _constater(deps, cle="cle-unique")

    assert renvoi["rejoue"] is True and renvoi["resultat"] == premiere["resultat"]
    assert len(_publies()) == 1


def test_le_meme_evenement_republie_sous_le_meme_identifiant_de_bus_n_est_livre_qu_une_fois(cas_fictif, deps):
    _constat_accepte(deps)
    ((evenement_id, charge),) = _publies()
    _drainer(deps, BASE)

    with stockage.transaction():
        evenements.publier(TYPE, M5, charge, evenement_id=evenement_id)  # un producteur qui rejoue après une panne

    assert len(_publies()) == 1
    assert _drainer(deps, BASE + dt.timedelta(minutes=5))["livres"] == 0
    assert len(_faits_de_m8()) == 1


# =============================================================================================
# 4. A, puis B, puis A : trois constats, le dernier est celui qu'on voit
# =============================================================================================
def test_un_retour_a_des_donnees_anterieures_est_un_nouveau_constat_que_la_vue_montre(cas_fictif, deps, declare):
    """Dettes 800 -> 900 -> 800, le même jour : la troisième version est celle de la première. Sans le rang dans
    l'identifiant, le bus avalerait le troisième événement et la vue resterait sur les 27761.98 $ du deuxième."""
    un = _constat_accepte(deps, cle="cle-1")["constat"]
    declare(_avec_dettes(CONFIGURATION, "900.00"))
    deux = _constat_accepte(deps, cle="cle-2")["constat"]
    _drainer(deps, BASE)
    assert _vue(deps)["cash_libre"]["constat"]["cash_libre_cad"] == "27761.98"

    declare(CONFIGURATION)
    trois = _constat_accepte(deps, cle="cle-3")["constat"]
    _drainer(deps, BASE + dt.timedelta(minutes=5))

    section = _vue(deps)["cash_libre"]
    assert (un["cash_libre_cad"], deux["cash_libre_cad"], trois["cash_libre_cad"]) == (
        "27861.98", "27761.98", "27861.98")
    assert trois["version_donnees"] == un["version_donnees"], "la même version qu'au départ"
    assert len({e for e, _ in _publies()}) == 3 and len(_faits_de_m8()) == 3
    assert section["constat"]["sequence"] == 3 and section["constat"]["cash_libre_cad"] == "27861.98"
    assert section["n_constats_recus"] == 3


# =============================================================================================
# 5. Un constat vieillit ; le lendemain, un nouveau constat le remplace
# =============================================================================================
def test_le_lendemain_la_vue_dit_un_jour_de_plus_puis_un_nouveau_constat_la_remplace(cas_fictif, deps):
    _constat_accepte(deps, JOUR, cle="cle-1")
    _drainer(deps, BASE)

    aujourd_hui = _vue(deps, JOUR)["cash_libre"]
    lendemain = _vue(deps, LENDEMAIN)["cash_libre"]
    sans_date = _vue(deps)["cash_libre"]

    assert aujourd_hui["age"]["jours"] == 0 and lendemain["age"]["jours"] == 1
    assert sans_date["age"] == {"jours": None, "raison": "aujourd_hui non fourni : M8 n'a pas d'horloge"}
    assert aujourd_hui["constat"] == lendemain["constat"] == sans_date["constat"], "seul l'âge change"

    _constat_accepte(deps, LENDEMAIN, cle="cle-2")  # les mêmes données, un autre jour : un nouveau constat
    _drainer(deps, BASE + dt.timedelta(days=1))
    section = _vue(deps, LENDEMAIN)["cash_libre"]
    assert [c["date_reference"] for _, c in _publies()] == [JOUR, LENDEMAIN]
    assert section["constat"]["date_reference"] == LENDEMAIN and section["age"]["jours"] == 0
    assert section["n_constats_recus"] == 2


# =============================================================================================
# 6. Qui peut constater, qui peut lire ; M8 ne publie rien
# =============================================================================================
@pytest.mark.parametrize("appelante", [EMPLOYE, VENDEUR])
def test_ni_l_employe_ni_le_vendeur_ne_peuvent_constater_ni_lire(cas_fictif, deps, appelante):
    avant = _instantane_base()

    refus_m5 = _constater(deps, appelante=appelante)
    refus_m8 = _vue_reponse(deps, appelante)

    assert refus_m5["ok"] is False and refus_m5["erreur"] == "hors_portee_role", refus_m5
    assert refus_m8["ok"] is False and refus_m8["erreur"] == "refus_metier", refus_m8
    assert refus_m8["details"].startswith("REJ-IDENTITE-APPAREIL-INVALIDE") and "resultat" not in refus_m8
    assert _publies() == []
    changees = {nom for nom, lignes in _instantane_base().items() if lignes != avant[nom]}
    assert changees <= {"mutations_appliquees"}, changees


def test_m8_ne_publie_rien_en_recevant_le_constat_et_m5_en_publie_un_seul_type(cas_fictif, deps):
    _constat_accepte(deps)
    _drainer(deps, BASE)
    _vue(deps, JOUR)

    assert _types_publies() == {TYPE}


def test_avant_tout_constat_la_vue_dit_manque_puis_le_constat_le_remplace(cas_fictif, deps):
    avant = _vue(deps, JOUR)["cash_libre"]
    assert avant["statut"] == "manque" and "constat" not in avant and avant["manque"] == ["cash_libre"]

    _constat_accepte(deps)
    _drainer(deps, BASE)

    assert _vue(deps, JOUR)["cash_libre"]["statut"] == "lu"


def test_les_manifestes_reels_sont_coherents_m5_publie_m8_consomme(deps):
    assert TYPE in deps[M5].evenements_publie and TYPE in deps[M8].evenements_consomme
    assert TYPE in deps[M8].charger_consommateurs()
    assert evenements.verifier_coherence(deps) == []


def test_meme_capacite_admin_relit_seulement_les_constats_livres_sans_mutation(cas_fictif, deps, declare):
    """Un lecteur public conservé ne transforme ni publication en réception, ni âge inconnu en zéro.

    SQLite, M5, le bus et M8 sont réels ; les registres financiers et l'identité sont fictifs.
    Ce n'est ni une preuve bancaire, ni une session Core, ni une mesure de fraîcheur du corpus entier.
    """
    capacites = Capacites(deps, stockage.transaction, filtre={M8}, memoire=False)

    def lire(arguments):
        avant = _instantane_base()
        with contexte.appele_par_appareil(ADMIN):
            reponse = capacites.appeler("m8_lire_vue_executive", arguments)
        assert reponse["ok"] is True, reponse
        assert _instantane_base() == avant, "chaque lecture laisse toutes les tables inchangées"
        return reponse["resultat"]

    initiale = lire({"aujourd_hui": JOUR})
    assert initiale["cash_libre"]["statut"] == "manque"
    assert initiale["cash_libre"]["manque"] == ["cash_libre"]
    assert "constat" not in initiale["cash_libre"]
    seuils = initiale["entonnoir"]["seuils"]
    # Sans source de l'entonnoir, ses mesures manquent : aucun zéro ni seuil évalué.
    assert seuils == {"a_configurer": [], "invalides": [], "ignores": [], "evalues": []}
    mesures = initiale["entonnoir"]["mesures"]
    assert len(mesures) == 8
    assert all(m["statut"] == "non_calculable" and m["valeur"] is None for m in mesures)
    manques_hors_cash = [m for m in initiale["manques"] if m["champ"] != "cash_libre"]
    assert manques_hors_cash

    premier = _constat_accepte(deps, JOUR, cle="cf033-premier")
    assert premier["publie"] is True
    assert len(_publies()) == 1 and _recus_de_m8() == [] and _faits_de_m8() == []
    publie_non_recu = lire({"aujourd_hui": JOUR})
    assert publie_non_recu["cash_libre"] == initiale["cash_libre"]
    assert publie_non_recu["entonnoir"]["seuils"] == seuils

    livraison = _drainer(deps, BASE)
    assert livraison["traites"] == 1 and livraison["echecs"] == livraison["quarantaines"] == 0
    ((evenement_un, charge_un),) = _publies()
    assert [(r.evenement_id, r.statut) for r in _recus_de_m8()] == [(evenement_un, "traite")]
    premiere_reception = lire({"aujourd_hui": JOUR})
    section = premiere_reception["cash_libre"]
    assert section["statut"] == "lu" and section["n_constats_recus"] == 1
    assert section["constat"]["cash_libre_cad"] == charge_un["cash_libre_cad"] == "27861.98"
    assert section["constat"]["date_reference"] == charge_un["date_reference"] == JOUR
    assert section["age"] == {"jours": 0, "aujourd_hui": JOUR}
    assert section["constat"]["mention"] == MENTION
    assert not any(m["champ"] == "cash_libre" for m in premiere_reception["manques"])

    declare(_avec_dettes(CONFIGURATION, "900.00"))
    second = _constat_accepte(deps, LENDEMAIN, cle="cf033-lendemain")
    assert second["publie"] is True and len(_publies()) == 2
    assert second["constat"]["cash_libre_cad"] == "27761.98"
    assert len(_recus_de_m8()) == len(_faits_de_m8()) == 1
    encore_ancien = lire({"aujourd_hui": LENDEMAIN})
    assert encore_ancien["cash_libre"]["constat"] == section["constat"]
    assert encore_ancien["cash_libre"]["n_constats_recus"] == 1
    assert encore_ancien["cash_libre"]["age"] == {"jours": 1, "aujourd_hui": LENDEMAIN}

    livraison = _drainer(deps, BASE + dt.timedelta(days=1))
    assert livraison["traites"] == 1 and livraison["echecs"] == livraison["quarantaines"] == 0
    recus = {(r.evenement_id, r.statut) for r in _recus_de_m8()}
    assert recus == {(evenement, "traite") for evenement, _ in _publies()}
    assert len(recus) == len(_faits_de_m8()) == 2
    courante = lire({"aujourd_hui": LENDEMAIN})
    assert courante["cash_libre"]["n_constats_recus"] == 2
    assert courante["cash_libre"]["constat"]["sequence"] == 2
    assert courante["cash_libre"]["constat"]["date_reference"] == LENDEMAIN
    assert courante["cash_libre"]["constat"]["cash_libre_cad"] == "27761.98"
    assert courante["cash_libre"]["constat"]["cash_libre_cad"] == _publies()[-1][1]["cash_libre_cad"]
    assert courante["cash_libre"]["age"] == {"jours": 0, "aujourd_hui": LENDEMAIN}

    sans_horloge = lire({})
    assert sans_horloge["cash_libre"]["constat"] == courante["cash_libre"]["constat"]
    assert sans_horloge["cash_libre"]["age"] == {
        "jours": None, "raison": "aujourd_hui non fourni : M8 n'a pas d'horloge",
    }
    for vue in (premiere_reception, encore_ancien, courante, sans_horloge):
        assert vue["entonnoir"]["seuils"] == seuils
        assert vue["entonnoir"]["mesures"] == mesures
        assert [m for m in vue["manques"] if m["champ"] != "cash_libre"] == manques_hors_cash
    assert _types_publies() == {TYPE}, "aucune nouvelle alerte ni décision provoquée par les lectures"
