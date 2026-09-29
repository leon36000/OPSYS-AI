"""PLAN T4.15-c : E2E de la correction, de l'annulation et des factures sans PO, par la porte d'appareil et par le
VRAI bus (DEFINITION-PRODUIT §7 M5.2 « comptes à payer » et §9.5 M5 « dépenses à valider »).

Le core ne tourne pas ici : ces tests prouvent tout ce qui est À PARTIR du moteur, par le vrai chemin réseau du moteur
(`tests/fixtures/harnais_e2e.py` : vraie application HTTP MCP sur un vrai uvicorn, base temporaire migrée, dix
départements réels, porte d'appareil refaite d'après le fork, personnes et appareils créés par les commandes réelles
du socle).

Le trajet, chiffré à la cent près (entreprise fictive ; PO de 320.00 $ chez Gentek, 60 gouttières à 5.00 $ reçues :
300.00 $ ; solde 20000.00 $ ; facture cliente envoyée de 5000.00 $, taxes 748.75 $ ; paies, DAS, dettes et réserves
déclarés à zéro) :

    reçu, rien de facturé            : taxes 748.75, à payer 344.93, cash libre 18906.32
    facture saisie (N3, direct)      : crédits 15.00 + 29.93 : taxes 703.82, à payer 344.93, cash libre 18951.25
    correction à 310.00 (N4)         : crédits 15.50 + 30.92 : taxes 702.33, à payer 356.42, cash libre 18941.25
    annulation (N4)                  : aucun crédit, l'attendu redevient dû : 748.75, 344.93, cash libre 18906.32
    la bonne facture ressaisie (N3)  : comme la facture saisie : 703.82, 344.93, cash libre 18951.25
    facture SANS PO de 100.00 (N3)   : 114.98 dû, crédits 5.00 + 9.98 : 688.84, à payer 459.91, cash libre 18851.25

1. corriger et annuler sont N4 : depuis le téléphone de l'admin, l'appel ATTEND dans la file du propriétaire, rien n'est
   écrit ; rejoué avec la même clé d'idempotence, il ne fait rien de plus ; le propriétaire décide depuis son téléphone
   (`m9_decider_demande_approbation`) et la pièce porte son nom ;
2. un REJEU (la même correction demandée de nouveau, la même annulation) est refusé par l'outil à la décision : rien
   n'est écrit ;
3. la facture sans PO se saisit directement (N3) avec une catégorie de la liste configurée ; sans liste : « catégories à
   configurer » ;
4. l'employé n'a aucune portée sur ces trois outils (fermé à la porte) ; l'agent ne fait jamais seul (en `ombre` et
   `supervise` sa demande attend, en `autonome` l'outil refuse) ;
5. rien n'a été décaissé, rien n'a été tronqué par `Capacites` (6 000 caractères).

Données fictives (AGENTS.md).
"""

from __future__ import annotations

import dataclasses
from typing import Any

import m5_financecore.outils as m5_outils
import pytest
import yaml
from harnais_e2e import Moteur, Reponse, iso
from m5_financecore import facturation, taux_fiscaux

from opsys import stockage
from opsys.capacites import Capacites
from opsys.outils import executer_atomique

FICTIF = True
SQLITE_SEULEMENT = pytest.mark.parametrize("moteur", ["sqlite"], indirect=True)

PO = "PO-E2E-CO-1"
DEVIS = "DEVIS-E2E-CO-1"
CHANTIER = "CHANTIER-E2E-CO-1"
FOURNISSEUR = "gentek-fictif"
GOUTTIERE = "gouttiere-5po-fictif"
VIS = "vis-inox-fictif"
CATALOGUE = {"version": "v1", "unite_monetaire": "CAD",
             "postes": {GOUTTIERE: {"cout_unitaire": 5.0, "libelle": "Gouttière 5 po"},
                        VIS: {"cout_unitaire": 0.5, "libelle": "Vis inox"}}}
CONFIGURATION = {
    "fiscal": {"frequence_tps_tvq": "trimestrielle", "mois_fin_exercice": 12, "taxes_remises_jusqu_au": "2026-06-30"},
    "obligations_declarees": {
        n: {"montant": "0.00", "source": "aucune (fictif)", "au": "2026-09-25"}
        for n in ("paies", "das", "dettes", "reserves")},
    "categories_depense_sans_po": ["carburant", "outils"],
}


# ------------------------------------------------------------------------------------------ petits outils
def _m5(moteur: Moteur) -> dict[str, Any]:
    return {o.nom: o for o in moteur.departements["m05-financecore"].charger_outils()}


def _m6(moteur: Moteur) -> dict[str, Any]:
    return {o.nom: o for o in moteur.departements["m06-material-control"].charger_outils()}


def _agent(outil: Any, arguments: dict[str, Any]) -> Any:
    reponse = executer_atomique(outil, arguments)
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]


def _preparer_po(moteur: Moteur) -> None:
    """Le PO PERSISTÉ de M6, jusqu'à `sent_to_supplier` : des gestes d'agent, appelés comme le fait T1.5-d."""
    m6 = _m6(moteur)
    maintenant = moteur.horloge.maintenant
    _agent(m6["m6_enregistrer_fournisseur"], {
        "fournisseur_id": FOURNISSEUR, "nom": "Gentek (fictif)", "horodatage": iso(maintenant),
        "courriel_commande": "commandes@gentek.exemple-fictif.test"})
    for materiau, prix in ((GOUTTIERE, 5.0), (VIS, 0.5)):
        _agent(m6["m6_enregistrer_prix"], {
            "materiau_id": materiau, "fournisseur_id": FOURNISSEUR, "prix_unitaire": prix, "devise": "CAD",
            "date_effet": "2026-09-01"})
    _agent(m6["m6_enregistrer_besoins_prevus"], {
        "chantier_id": CHANTIER, "devis_id": DEVIS, "lignes": [
            {"materiau_id": GOUTTIERE, "quantite_estimee": 60.0, "unite": "pi"},
            {"materiau_id": VIS, "quantite_estimee": 40.0, "unite": "boite"}]})
    _agent(m6["m6_creer_po_brouillon"], {
        "po_id": PO, "devis_id": DEVIS, "fournisseur_id": FOURNISSEUR, "horodatage": iso(maintenant)})
    _agent(m6["m6_approuver_po"], {"po_id": PO, "horodatage": iso(maintenant, 60)})
    _agent(m6["m6_generer_courriel_po"], {
        "po_id": PO, "horodatage": iso(maintenant, 120), "nom_entreprise": "Entreprise Fictive"})
    assert _agent(m6["m6_marquer_po_envoye"], {"po_id": PO, "horodatage": iso(maintenant, 180)})["po"][
        "statut"] == "sent_to_supplier"


def _preparer_le_solde_et_les_taxes(moteur: Moteur) -> None:
    """20000.00 $ au registre, et la facture cliente envoyée de 5000.00 $ (TPS 250.00, TVQ 498.75)."""
    reponse = _agent(_m5(moteur)["m5_enregistrer_mouvement"], {
        "montant": "20000.00", "type_mouvement": "ENCAISSEMENT", "horodatage": "2026-09-10T12:00:00-04:00",
        "classe_retention": "STANDARD", "source": "e2e-fictif"})
    assert reponse["accepte"] is True
    taux, erreurs = taux_fiscaux.charger_taux_fiscaux(m5_outils._CHEMIN_TAUX_FISCAUX)
    assert erreurs == []
    with stockage.transaction():
        factures = m5_outils._registre_factures(None)
        _, verdict = facturation.creer_facture_brouillon(
            "F-E2E-CO-1", "CH-E2E-2", "D-E2E-2", "C-E2E-2",
            [{"description": "gouttières (fictif)", "quantite": "1", "unite": "forfait", "prix_unitaire": "5000.00",
              "reference_ligne_devis": "L-1"}], "2026-08-10T09:00:00-04:00", taux, factures)
        assert verdict is None, verdict
        assert facturation.envoyer_facture("F-E2E-CO-1", "2026-08-10T09:30:00-04:00", factures)[1] is None


def _declarer(tmp_path, monkeypatch, configuration) -> None:
    manifeste = tmp_path / "department-m5-e2e.yaml"
    manifeste.write_text(yaml.safe_dump({"configuration": configuration}, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)


def _reception_partielle(moteur: Moteur, admin) -> None:
    maintenant = moteur.horloge.maintenant
    reponse = admin.appeler("m6_receptionner_commande", {
        "bon_demande": {"po_id": PO, "chantier_id": CHANTIER, "horodatage": iso(maintenant), "lignes_demandees": [
            {"materiau_id": GOUTTIERE, "quantite_demandee": 60.0}, {"materiau_id": VIS, "quantite_demandee": 40.0}]},
        "reception_po": {"po_id": PO, "chantier_id": CHANTIER, "horodatage": iso(maintenant), "lignes_recues": [
            {"materiau_id": GOUTTIERE, "quantite_recue": 60.0}, {"materiau_id": VIS, "quantite_recue": 0.0}]},
        "catalogue_materiaux": CATALOGUE,
    }, cle="cle-reception-1", horodatage_appareil=iso(maintenant))
    assert reponse.ok and reponse.metier["accepte"] is True, reponse.corps
    resume = moteur.drainer_bus(moteur.horloge.maintenant)
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume


def _facture(moteur: Moteur, admin, cle: str) -> Reponse:
    return admin.appeler("m5_saisir_facture_fournisseur", {
        "po_id": PO, "fournisseur_id": FOURNISSEUR, "numero_facture": "F-1001", "date_facture": "2026-09-14",
        "montant_avant_taxes": "300.00", "total_facture": "344.93", "horodatage": iso(moteur.horloge.maintenant),
    }, cle=cle, horodatage_appareil=iso(moteur.horloge.maintenant))


def _corriger(moteur: Moteur, admin, ident: str, cle: str, montant: str = "310.00") -> Reponse:
    return admin.appeler("m5_corriger_facture_fournisseur", {
        "facture_fournisseur_id": ident, "motif": "Faute de frappe sur le montant, facture papier relue (fictif)",
        "numero_facture": None, "date_facture": None, "montant_avant_taxes": montant, "total_facture": None,
        "horodatage": iso(moteur.horloge.maintenant),
    }, cle=cle, horodatage_appareil=iso(moteur.horloge.maintenant))


def _annuler(moteur: Moteur, admin, ident: str, cle: str) -> Reponse:
    return admin.appeler("m5_annuler_facture_fournisseur", {
        "facture_fournisseur_id": ident, "motif": "Facture reçue en double du fournisseur (fictif)",
        "horodatage": iso(moteur.horloge.maintenant),
    }, cle=cle, horodatage_appareil=iso(moteur.horloge.maintenant))


def _sans_po(moteur: Moteur, admin, cle: str, **surcharges) -> Reponse:
    args = {"fournisseur_id": "Pétro-Nord (fictif)", "categorie": "carburant", "numero_facture": "C-4001",
            "date_facture": "2026-09-14", "montant_avant_taxes": "100.00", "total_facture": "114.98",
            "horodatage": iso(moteur.horloge.maintenant)}
    args.update(surcharges)
    return admin.appeler("m5_saisir_facture_sans_po", args, cle=cle, horodatage_appareil=iso(moteur.horloge.maintenant))


def _decider(moteur: Moteur, admin, demande_id: str, cle: str) -> Reponse:
    return admin.appeler("m9_decider_demande_approbation", {
        "demande_id": demande_id, "decision": "approuver", "motif": "Vérifié sur la facture papier (fictif)."},
        cle=cle, horodatage_appareil=iso(moteur.horloge.maintenant))


def _le_po(admin) -> dict[str, Any]:
    page = admin.appeler("m5_lister_comptes_a_payer", {"po_id": PO}).resultat
    assert page["total"] == 1
    return page["comptes"][0]


def _cash(admin) -> tuple[str, str, str]:
    """(cash libre, TPS/TVQ à remettre, comptes à payer) tels que l'admin les lit sur son téléphone."""
    cash = admin.appeler("m5_etat_tresorerie", {}).metier["cash_libre"]
    composantes = {c["id"]: c["montant"] for c in cash["composantes"]}
    return cash["cash_libre"], composantes["taxes_a_remettre"], composantes["comptes_a_payer"]


@pytest.fixture
def pret(moteur, equipe, tmp_path, monkeypatch):
    """Le PO reçu (300.00 $), le solde, la facture cliente, la configuration du propriétaire."""
    _declarer(tmp_path, monkeypatch, CONFIGURATION)
    _preparer_po(moteur)
    _preparer_le_solde_et_les_taxes(moteur)
    _reception_partielle(moteur, equipe["admin"])
    return equipe["admin"], equipe["employe"]


# ============================================================================================ le trajet
def test_correction_annulation_et_facture_sans_po_de_bout_en_bout(moteur, pret):
    admin, _employe = pret
    assert _cash(admin) == ("18906.32", "748.75", "344.93")

    # la facture saisie (N3 : l'humain qui agit lui-même, direct)
    saisie = _facture(moteur, admin, "cle-facture-1")
    assert saisie.ok and saisie.metier["accepte"] is True, saisie.corps
    ident = saisie.metier["resultat"]["facture"]["facture_fournisseur_id"]
    assert _cash(admin) == ("18951.25", "703.82", "344.93")

    # 1. corriger : N4, l'appel ATTEND dans la file du propriétaire ; rien n'est écrit
    avant = moteur.empreinte_etat()
    demande = _corriger(moteur, admin, ident, "cle-correction-1")
    assert demande.ok and demande.enveloppe["statut"] == "en_attente_approbation", demande.corps
    apres_demande = moteur.empreinte_etat()
    assert apres_demande["registres"] == avant["registres"], "aucune pièce écrite"
    assert apres_demande["approbations"] == avant["approbations"] + 1
    assert _cash(admin) == ("18951.25", "703.82", "344.93"), "proposer ne change rien"
    (en_attente,) = admin.appeler("m9_lister_demandes_approbation", {}).resultat["demandes"]
    assert en_attente["outil"] == "m5_corriger_facture_fournisseur" and en_attente["niveau"] == "N4"
    assert en_attente["decidable"] is True and en_attente["arguments"]["facture_fournisseur_id"] == ident
    assert en_attente["arguments"]["motif"].startswith("Faute de frappe")

    # le même geste rejoué (même clé) ne fait rien de plus : la même demande, aucune autre
    rejoue = _corriger(moteur, admin, ident, "cle-correction-1")
    assert rejoue.ok and rejoue.enveloppe["rejoue"] is True
    assert rejoue.enveloppe["demande_id"] == demande.enveloppe["demande_id"]
    assert moteur.empreinte_etat() == apres_demande

    # le propriétaire décide depuis son téléphone : la pièce porte son nom, la voie de l'approbation
    decision = _decider(moteur, admin, demande.enveloppe["demande_id"], "cle-decision-1")
    assert decision.metier["accepte"] is True
    assert (decision.resultat["statut"], decision.resultat["decide_par"], decision.resultat["role"]) == (
        "executee", "nathan", "nathan_owner")
    assert decision.resultat["issue"]["accepte"] is True
    with stockage.transaction():
        (piece,) = [m for m in stockage.maillons("m05-financecore", "comptes_a_payer")
                    if m["type_entree"] == "correction_facture_fournisseur"]
    assert (piece["corrige_par"], piece["role"], piece["voie"]) == ("nathan", "nathan_owner", "approbation")
    assert str(piece["avant"]["montant_avant_taxes"]) == "300.00"
    assert str(piece["apres"]["montant_apres_taxes"]) == "356.42"
    ligne = _le_po(admin)
    assert ligne["factures"] == {"nombre": 1, "avant_taxes": "310.00", "taxes": "46.42", "apres_taxes": "356.42"}
    assert ligne["a_payer_apres_taxes"] == "356.42" and ligne["rapprochement"]["verdict"] == "ECART"
    assert ligne["factures_saisies"][0]["statut"] == "CORRIGEE"
    assert _cash(admin) == ("18941.25", "702.33", "356.42"), "taxes, à payer et cash libre lisent l'état courant"

    # la décision rejouée (même clé) ne ré-exécute rien ; une autre clé sur une demande décidée : refus nommé
    apres_decision = moteur.empreinte_etat()
    assert _decider(moteur, admin, demande.enveloppe["demande_id"], "cle-decision-1").enveloppe["rejoue"] is True
    assert moteur.empreinte_etat() == apres_decision
    deja = _decider(moteur, admin, demande.enveloppe["demande_id"], "cle-decision-2")
    assert deja.metier["accepte"] is False and deja.metier["verdict"]["code"] == "deja_decidee"
    assert moteur.empreinte_etat()["registres"] == apres_decision["registres"]

    # 2. le REJEU de la même correction (autre clé : un autre geste) : l'outil refuse à la décision, rien n'est écrit
    rejeu = _corriger(moteur, admin, ident, "cle-correction-2")
    assert rejeu.enveloppe["statut"] == "en_attente_approbation"
    avant_rejeu = moteur.empreinte_etat()["registres"]
    decide_rejeu = _decider(moteur, admin, rejeu.enveloppe["demande_id"], "cle-decision-3")
    assert decide_rejeu.resultat["statut"] == "executee" and decide_rejeu.resultat["issue"]["accepte"] is False
    assert moteur.empreinte_etat()["registres"] == avant_rejeu, "un rejeu n'écrit aucune pièce de plus"
    assert _cash(admin) == ("18941.25", "702.33", "356.42")

    # annuler : N4 aussi ; la dette ne disparaît pas (l'attendu redevient dû), les crédits de taxes oui
    annulation = _annuler(moteur, admin, ident, "cle-annulation-1")
    assert annulation.enveloppe["statut"] == "en_attente_approbation"
    _decider(moteur, admin, annulation.enveloppe["demande_id"], "cle-decision-4")
    ligne = _le_po(admin)
    assert ligne["factures"]["nombre"] == 0 and ligne["factures_annulees"] == 1
    assert ligne["rapprochement"]["verdict"] == "SANS_FACTURE" and ligne["a_payer_apres_taxes"] == "344.93"
    assert [f["statut"] for f in ligne["factures_saisies"]] == ["ANNULEE"]
    assert ligne["factures_saisies"][0]["derniere_modification"]["motif"].startswith("Facture reçue en double")
    assert _cash(admin) == ("18906.32", "748.75", "344.93")

    # l'annulation rejouée est refusée à la décision, sans rien écrire ; une annulée ne se corrige plus
    apres_annulation = moteur.empreinte_etat()["registres"]
    for cle, demander in (("cle-annulation-2", lambda c: _annuler(moteur, admin, ident, c)),
                          ("cle-correction-3", lambda c: _corriger(moteur, admin, ident, c, "320.00"))):
        demande_rejeu = demander(cle)
        decide = _decider(moteur, admin, demande_rejeu.enveloppe["demande_id"], f"cle-decision-{cle}")
        assert decide.resultat["issue"]["accepte"] is False, cle
    assert moteur.empreinte_etat()["registres"] == apres_annulation

    # la facture ressaisie, bonne cette fois : l'identifiant n'est pas celui de l'annulée
    resaisie = _facture(moteur, admin, "cle-facture-2")
    assert resaisie.metier["accepte"] is True
    assert resaisie.metier["resultat"]["facture"]["facture_fournisseur_id"] != ident
    assert _cash(admin) == ("18951.25", "703.82", "344.93")

    # 3. la facture SANS PO : directe (N3), catégorie de la liste configurée
    sans_po = _sans_po(moteur, admin, "cle-sans-po-1")
    assert sans_po.ok and sans_po.metier["accepte"] is True, sans_po.corps
    facture = sans_po.metier["resultat"]["facture"]
    assert (facture["categorie_depense"], facture["po_id"], facture["montant_apres_taxes"]) == (
        "carburant", None, "114.98")
    assert facture["saisi_par"] == "nathan" and facture["voie"] == "appareil"
    assert sans_po.metier["resultat"]["sans_po"]["apres_taxes"] == "114.98"
    assert _cash(admin) == ("18851.25", "688.84", "459.91"), "la dette de 114.98 entre en entier ; crédits 5.00 + 9.98"

    liste = admin.appeler("m5_lister_comptes_a_payer", {"sans_po": True}).resultat
    assert liste["total"] == 1 and liste["factures"][0]["facture_fournisseur_id"] == facture["facture_fournisseur_id"]
    totaux = admin.appeler("m5_lister_comptes_a_payer", {}).resultat["totaux"]
    assert totaux["sans_po"]["par_categorie"] == {"carburant": {"nombre": 1, "apres_taxes": "114.98"}}
    assert totaux["a_payer_apres_taxes"] == "459.91"

    # le geste rejoué (même clé) ne fait rien de plus ; le même contenu sous une autre clé est un doublon ; une
    # catégorie hors liste est refusée
    apres_sans_po = moteur.empreinte_etat()
    assert _sans_po(moteur, admin, "cle-sans-po-1").enveloppe["rejoue"] is True
    assert moteur.empreinte_etat() == apres_sans_po
    doublon = _sans_po(moteur, admin, "cle-sans-po-2")
    assert doublon.metier["accepte"] is False and doublon.metier["verdict"]["code"] == "REJ-AP-FACTURE-DOUBLON"
    hors = _sans_po(moteur, admin, "cle-sans-po-3", categorie="divertissement", numero_facture="C-4002")
    assert hors.metier["verdict"]["code"] == "REJ-AP-CATEGORIE-INCONNUE"
    assert moteur.empreinte_etat()["registres"] == apres_sans_po["registres"]

    # 5. RIEN n'a été décaissé : le registre des mouvements n'a que l'encaissement, et rien n'a été tronqué
    registres = moteur.empreinte_etat()["registres"]
    assert registres["m05-financecore/principal"] == 1, "l'encaissement du départ, rien d'autre"
    assert registres["m05-financecore/factures"] == 2, "la facture cliente : sa création et son envoi"
    with stockage.transaction():
        maillons = list(stockage.maillons("m05-financecore", "comptes_a_payer"))
        mouvements = list(stockage.maillons("m05-financecore", "principal"))
    assert "DECAISSEMENT" not in str(maillons) and [m["type_mouvement"] for m in mouvements] == ["ENCAISSEMENT"]
    assert {m["type_entree"] for m in maillons} >= {
        "correction_facture_fournisseur", "annulation_facture_fournisseur", "facture_fournisseur_saisie"}
    assert moteur.bilan()["troncatures"] == []


@SQLITE_SEULEMENT
def test_sans_liste_de_categories_la_facture_sans_po_dit_categories_a_configurer(moteur, equipe, tmp_path, monkeypatch):
    _declarer(tmp_path, monkeypatch, {"fiscal": CONFIGURATION["fiscal"]})
    admin = equipe["admin"]
    avant = moteur.empreinte_etat()

    refus = _sans_po(moteur, admin, "cle-sans-liste")

    assert refus.ok and refus.metier["accepte"] is False
    assert refus.metier["verdict"]["code"] == "REJ-AP-CATEGORIES-A-CONFIGURER"
    assert "catégories à configurer" in refus.metier["verdict"]["detail"]
    assert moteur.empreinte_etat()["registres"] == avant["registres"]


# ===================================================================================== employé et agent
@SQLITE_SEULEMENT
def test_l_employe_n_a_aucune_portee_sur_les_trois_outils_ni_sur_la_lecture(moteur, pret):
    admin, employe = pret
    ident = _facture(moteur, admin, "cle-facture-1").metier["resultat"]["facture"]["facture_fournisseur_id"]
    avant = moteur.empreinte_etat()

    for outil, args in (
        ("m5_corriger_facture_fournisseur", {
            "facture_fournisseur_id": ident, "motif": "je veux corriger", "numero_facture": None,
            "date_facture": None, "montant_avant_taxes": "1.00", "total_facture": None,
            "horodatage": iso(moteur.horloge.maintenant)}),
        ("m5_annuler_facture_fournisseur", {
            "facture_fournisseur_id": ident, "motif": "je veux annuler", "horodatage": iso(moteur.horloge.maintenant)}),
        ("m5_saisir_facture_sans_po", {
            "fournisseur_id": "X", "categorie": "carburant", "numero_facture": "Z", "date_facture": "2026-09-14",
            "montant_avant_taxes": "1.00", "total_facture": None, "horodatage": iso(moteur.horloge.maintenant)}),
        ("m5_lister_comptes_a_payer", {"sans_po": True}),
    ):
        refuse = employe.appeler(outil, args, cle="cle-employe" if outil != "m5_lister_comptes_a_payer" else None)
        assert refuse.statut == 403 and refuse.ok is False, (outil, refuse.corps)
    assert moteur.empreinte_etat() == avant, "rien n'est lu ni écrit"


@SQLITE_SEULEMENT
def test_l_agent_ne_corrige_ni_n_annule_seul_il_propose_ou_l_outil_refuse(moteur, pret):
    admin, _employe = pret
    ident = _facture(moteur, admin, "cle-facture-1").metier["resultat"]["facture"]["facture_fournisseur_id"]
    arguments = {"facture_fournisseur_id": ident, "motif": "proposé par l'agent (fictif)", "numero_facture": None,
                 "date_facture": None, "montant_avant_taxes": "310.00", "total_facture": None,
                 "horodatage": iso(moteur.horloge.maintenant)}
    avant = moteur.empreinte_etat()

    # ombre et supervise : la demande attend le propriétaire, rien n'est écrit
    for mode in ("ombre", "supervise"):
        departements = dict(moteur.departements)
        departements["m05-financecore"] = dataclasses.replace(departements["m05-financecore"], mode=mode)
        reponse = Capacites(departements, stockage.transaction).appeler("m5_corriger_facture_fournisseur", arguments)
        assert reponse["statut"] == "en_attente_approbation", (mode, reponse)
        assert moteur.empreinte_etat()["registres"] == avant["registres"]

    # autonome : un N4 s'exécute SANS file, c'est l'outil qui refuse l'agent
    autonome = dict(moteur.departements)
    autonome["m05-financecore"] = dataclasses.replace(autonome["m05-financecore"], mode="autonome")
    capacites = Capacites(autonome, stockage.transaction)
    for outil, args in (("m5_corriger_facture_fournisseur", arguments), ("m5_annuler_facture_fournisseur", {
            "facture_fournisseur_id": ident, "motif": "proposé par l'agent (fictif)",
            "horodatage": iso(moteur.horloge.maintenant)})):
        reponse = capacites.appeler(outil, args)
        assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
        assert reponse["resultat"]["verdict"]["code"] == "REJ-AP-HUMAIN-REQUIS"
    assert moteur.empreinte_etat()["registres"] == avant["registres"]
    assert _le_po(admin)["factures"]["apres_taxes"] == "344.93", "la facture n'a pas bougé"

    # le propriétaire approuve la demande de l'agent : la pièce porte SON nom
    capacites_ombre = Capacites(moteur.departements, stockage.transaction)
    demande = capacites_ombre.appeler("m5_annuler_facture_fournisseur", {
        "facture_fournisseur_id": ident, "motif": "proposé par l'agent (fictif)",
        "horodatage": iso(moteur.horloge.maintenant)})
    decision = _decider(moteur, admin, demande["demande_id"], "cle-decision-agent")
    assert decision.resultat["statut"] == "executee" and decision.resultat["issue"]["accepte"] is True
    with stockage.transaction():
        (piece,) = [m for m in stockage.maillons("m05-financecore", "comptes_a_payer")
                    if m["type_entree"] == "annulation_facture_fournisseur"]
    assert (piece["annule_par"], piece["voie"]) == ("nathan", "approbation")
