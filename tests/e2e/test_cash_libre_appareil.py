"""PLAN T4.16 : E2E du cash libre réel et du calendrier fiscal, par la porte d'appareil et par le VRAI bus
(DEFINITION-PRODUIT §7 M5 : « Solde bancaire ≠ argent disponible. Cash libre réel = solde bancaire - taxes - paies -
DAS - comptes à payer
- dettes
- obligations - réserves critiques »).

Le core ne tourne pas ici : ces tests prouvent tout ce qui est À PARTIR du moteur, par le vrai chemin réseau du moteur
(`tests/fixtures/harnais_e2e.py` : vraie application HTTP MCP sur un vrai uvicorn, base temporaire migrée, dix
départements réels, porte d'appareil refaite d'après le fork, personnes et appareils créés par les commandes réelles
du socle).

Le trajet, chiffré à la cent près (entreprise fictive, trimestrielle, exercice au 31 décembre, remise faite jusqu'au
30 juin) :

    solde 20000.00 (un encaissement) ; réserve 500.00 (un mouvement de réserve)
    facture cliente envoyée le 10 août : 5000.00 avant taxes, TPS 250.00, TVQ 498.75
    réception de M6 par le vrai bus : 60 gouttières a 5.00 = 300.00, a payer 344.93 (TPS 15.00, TVQ 29.925 -> 29.93)
    paies 3000.00, DAS 900.00, dettes 400.00 : déclarées par le propriétaire (M5.4 n'existe pas encore)

1. AVANT la facture fournisseur : taxes 250.00 + 498.75 = 748.75 ; cash libre 20000.00 - 748.75 - 3000.00 - 900.00
   - 344.93 - 400.00 - 500.00 = 14106.32 ;
2. le propriétaire SAISIT la facture fournisseur sur son téléphone : les crédits de taxes sur intrants (15.00 + 29.93
  = 44.93) baissent les taxes à 703.82 ; cash libre 14151.25 ;
3. `m5_lire_echeances_fiscales` : le trimestre du 30 septembre, dû le 2 novembre, avec ses 703.82 nets ;
4. sans les paies déclarées : « non calculable, manque paies », jamais zéro, avec un `au_plus` qui n'est pas de
  l'argent ;
5. l'employé n'a aucune portée sur ces deux outils ; la vue sans droit ne montre aucun montant ;
6. rien n'a été écrit, aucun décaissement n'existe, et rien n'a été tronqué par `Capacites` (6 000 caractères).

Données fictives (AGENTS.md).
"""

from __future__ import annotations

import json
from decimal import Decimal

import m5_financecore.outils as m5_outils
import pytest
import yaml
from harnais_e2e import Moteur, Reponse, iso
from m5_financecore import facturation, taux_fiscaux
from m5_financecore.analyse import MENTION_ANALYSE_PREPARATOIRE as MENTION

from opsys import evenements, stockage
from opsys.outils import executer_atomique

FICTIF = True
SQLITE_SEULEMENT = pytest.mark.parametrize("moteur", ["sqlite"], indirect=True)

PO = "PO-E2E-CL-1"
FOURNISSEUR = "gentek-fictif"
AUJOURD_HUI = "2026-09-29"

CONFIGURATION = {
    "fiscal": {"frequence_tps_tvq": "trimestrielle", "mois_fin_exercice": 12, "taxes_remises_jusqu_au": "2026-06-30"},
    "obligations_declarees": {
        "paies": {"montant": "3000.00", "source": "brouillon de paie (fictif)", "au": "2026-09-25"},
        "das": {"montant": "900.00", "source": "estimation du CPA (fictive)", "au": "2026-09-25"},
        "dettes": {"montant": "400.00", "source": "relevé du prêt camion (fictif)", "au": "2026-09-01"},
    },
}


def _declarer(tmp_path, monkeypatch, configuration):
    manifeste = tmp_path / "department-m5-e2e.yaml"
    manifeste.write_text(yaml.safe_dump({"configuration": configuration}, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)


def _m5(moteur: Moteur):
    return {o.nom: o for o in moteur.departements["m05-financecore"].charger_outils()}


def _preparer(moteur: Moteur) -> None:
    """Le solde, la réserve, la facture cliente envoyée et la réception de M6 (par le vrai bus)."""
    m5 = _m5(moteur)
    for montant, type_mouvement in (("20000.00", "ENCAISSEMENT"), ("500.00", "PROVISION")):
        reponse = executer_atomique(m5["m5_enregistrer_mouvement"], {
            "montant": montant, "type_mouvement": type_mouvement, "horodatage": "2026-09-10T12:00:00-04:00",
            "classe_retention": "STANDARD", "source": "e2e-fictif"})
        assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    taux, erreurs = taux_fiscaux.charger_taux_fiscaux(m5_outils._CHEMIN_TAUX_FISCAUX)
    assert erreurs == []
    with stockage.transaction():
        registre_factures = m5_outils._registre_factures(None)
        _, verdict = facturation.creer_facture_brouillon(
            "F-E2E-1", "CH-E2E-1", "D-E2E-1", "C-E2E-1",
            [{"description": "gouttières (fictif)", "quantite": "1", "unite": "forfait", "prix_unitaire": "5000.00",
              "reference_ligne_devis": "L-1"}], "2026-08-10T09:00:00-04:00", taux, registre_factures)
        assert verdict is None, verdict
        assert facturation.envoyer_facture("F-E2E-1", "2026-08-10T09:30:00-04:00", registre_factures)[1] is None
        charge = {
            "evenement_id": "evt-e2e-cl-1", "po_id": PO, "fournisseur_id": FOURNISSEUR, "chantier_id": "CH-E2E-1",
            "horodatage_reception": "2026-09-14T09:00:00-04:00", "verdict_reception": "CONFORME",
            "statut_po": "received", "hash_maillon": "b" * 64, "seuil_ecart_prix_pourcentage": None,
            "lignes": [{"materiau_id": "gouttiere-5po-fictif", "quantite_demandee": "60", "quantite_recue": "60",
                        "prix_unitaire_prevu": "5.00", "devise_prevue": "CAD", "verdict_prix_po": "PRIX_LIVRE",
                        "prix_unitaire_reception": None, "verdict_prix_reception": "INDETERMINE",
                        "ecart_prix_critique": None}]}
        evenements.publier("m6.reception_enregistree", "m06-material-control", charge,
                           evenement_id=charge["evenement_id"])
    resume = moteur.drainer_bus(moteur.horloge.maintenant)
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume


def _saisir_la_facture_fournisseur(moteur: Moteur, admin) -> Reponse:
    reponse = admin.appeler("m5_saisir_facture_fournisseur", {
        "po_id": PO, "fournisseur_id": FOURNISSEUR, "numero_facture": "F-1001", "date_facture": "2026-09-14",
        "montant_avant_taxes": "300.00", "total_facture": "344.93", "horodatage": iso(moteur.horloge.maintenant),
    }, cle="cle-facture-e2e", horodatage_appareil=iso(moteur.horloge.maintenant))
    assert reponse.ok and reponse.metier["accepte"] is True, reponse.corps
    return reponse


def _composantes(cash):
    return {c["id"]: c for c in cash["composantes"]}


@SQLITE_SEULEMENT
def test_le_cash_libre_du_proprietaire_avant_et_apres_la_facture_fournisseur_a_la_cent_pres(
        moteur, equipe, tmp_path, monkeypatch):
    admin = equipe["admin"]
    _declarer(tmp_path, monkeypatch, CONFIGURATION)
    _preparer(moteur)

    # 1. avant la facture fournisseur : aucun crédit de taxe, le compte à payer est seulement ATTENDU
    etat = admin.appeler("m5_etat_tresorerie", {}).resultat
    assert (etat["solde"], etat["argent_disponible"]) == ("20000.00", "19500.00")
    cash = etat["cash_libre"]
    assert etat["mention"] == MENTION and cash["mention"] == MENTION
    assert {cid: c["montant"] for cid, c in _composantes(cash).items()} == {
        "taxes_a_remettre": "748.75", "paies": "3000.00", "das": "900.00", "comptes_a_payer": "344.93",
        "dettes": "400.00", "reserves": "500.00"}
    assert cash["cash_libre"] == "14106.32" and cash["calculable"] is True and cash["manque"] == []
    assert "cash_libre" in etat["argent_disponible_note"], "l'argent disponible n'est jamais montré seul"
    assert cash["reserves"] == ["REJ-AP-UNITE-PRIX-NON-CONFIRMEE"]

    # 2. le propriétaire saisit la facture sur son téléphone : les crédits de taxes sur intrants (15.00 + 29.93)
    avant_saisie = moteur.empreinte_etat()
    saisie = _saisir_la_facture_fournisseur(moteur, admin)
    assert saisie.metier["resultat"]["mention"] == MENTION
    cash = admin.appeler("m5_etat_tresorerie", {}).resultat["cash_libre"]
    taxes = _composantes(cash)["taxes_a_remettre"]
    assert taxes["montant"] == "703.82"
    assert taxes["detail"]["tps"] == {"collectee": "250.00", "credits_intrants": "15.00", "nette": "235.00",
                                      "a_remettre": "235.00"}
    assert taxes["detail"]["tvq"] == {"collectee": "498.75", "credits_intrants": "29.93", "nette": "468.82",
                                      "a_remettre": "468.82"}
    assert _composantes(cash)["comptes_a_payer"]["montant"] == "344.93", "la facture remplace l'attendu"
    assert cash["cash_libre"] == "14151.25"
    assert Decimal("14151.25") - Decimal("14106.32") == Decimal("44.93"), "l'écart : les crédits de taxes sur intrants"
    assert moteur.empreinte_etat()["registres"]["m05-financecore/comptes_a_payer"] == (
        avant_saisie["registres"]["m05-financecore/comptes_a_payer"] + 1)

    # chaque composante porte sa source et sa fraîcheur
    for composante in [cash["solde"], *cash["composantes"]]:
        assert composante["source"]["de"] and composante["fraicheur"]["derniere_piece"], composante["id"]
    assert cash["solde"]["fraicheur"] == {"derniere_piece": "2026-09-10T12:00:00-04:00", "pieces": 2}
    assert _composantes(cash)["paies"]["source"]["de"].startswith("déclaration du propriétaire")

    # rien n'a été tronqué par Capacites (6 000 caractères)
    assert moteur.bilan()["troncatures"] == []


@SQLITE_SEULEMENT
def test_le_calendrier_fiscal_par_l_appareil_avec_la_taxe_nette_du_trimestre(moteur, equipe, tmp_path, monkeypatch):
    admin = equipe["admin"]
    _declarer(tmp_path, monkeypatch, CONFIGURATION)
    _preparer(moteur)
    _saisir_la_facture_fournisseur(moteur, admin)

    reponse = admin.appeler("m5_lire_echeances_fiscales", {"aujourd_hui": AUJOURD_HUI})

    resultat = reponse.resultat
    assert resultat["mention"] == MENTION and resultat["role"] == "admin"
    assert [(e["periode_fin"], e["limite_paiement"], e["statut"], e["jours_avant_paiement"])
            for e in resultat["echeances"]] == [
        ("2026-09-30", "2026-11-02", "A_VENIR", 34), ("2026-12-31", "2027-02-01", "A_VENIR", 125)]
    trimestre = resultat["echeances"][0]
    assert trimestre["taxes_nettes"]["a_remettre"] == "703.82" and trimestre["periode_terminee"] is False
    assert resultat["echeances"][1]["taxes_nettes"]["a_remettre"] == "0.00"
    assert resultat["validation_cpa"] == {"2025": "A_VALIDER", "2026": "A_VALIDER"}
    assert any(source["organisme"] == "Revenu Québec" for source in resultat["sources"])
    assert moteur.bilan()["troncatures"] == []

    # une année non déclarée est refusée à la porte : aucune date n'est supposée
    refus = admin.appeler("m5_lire_echeances_fiscales", {"aujourd_hui": "2027-03-01"})
    assert refus.ok and refus.metier["accepte"] is False
    assert refus.metier["verdict"]["code"] == "REJ-CALENDRIER-ANNEE-NON-DECLAREE"
    assert "echeances" not in refus.metier


@SQLITE_SEULEMENT
def test_sans_les_paies_declarees_le_cash_libre_est_non_calculable_jamais_zero(moteur, equipe, tmp_path, monkeypatch):
    admin = equipe["admin"]
    sans_paies = {**CONFIGURATION, "obligations_declarees": {
        cle: v for cle, v in CONFIGURATION["obligations_declarees"].items() if cle != "paies"}}
    _declarer(tmp_path, monkeypatch, sans_paies)
    _preparer(moteur)
    _saisir_la_facture_fournisseur(moteur, admin)

    cash = admin.appeler("m5_etat_tresorerie", {}).resultat["cash_libre"]

    paies = _composantes(cash)["paies"]
    assert paies["statut"] == "NON_CALCULABLE" and paies["montant"] is None
    assert paies["manque"][0]["code"] == "REJ-CASH-PAIE-A-DECLARER"
    assert cash["cash_libre"] is None and cash["calculable"] is False
    assert cash["manque"] == ["paies : REJ-CASH-PAIE-A-DECLARER"]
    # 20000.00 - 703.82 - 900.00 - 344.93 - 400.00 - 500.00 : les paies inconnues ne sont pas comptées
    assert cash["au_plus"] == "17151.25"
    assert "PAS de l'argent disponible" in cash["lecture"]


@SQLITE_SEULEMENT
def test_le_manifeste_livre_ne_suppose_rien_la_frequence_est_au_proprietaire(moteur, equipe):
    """Sans déclaration du propriétaire (le vrai manifeste de M5, GATE NATHAN) : le calendrier refuse de nommer une
    échéance et le cash libre dit ce qui manque. Rien n'est supposé."""
    admin = equipe["admin"]
    _preparer(moteur)

    echeances = admin.appeler("m5_lire_echeances_fiscales", {"aujourd_hui": AUJOURD_HUI})
    assert echeances.metier["accepte"] is False
    assert echeances.metier["verdict"]["code"] == "REJ-FISCAL-FREQUENCE-A-DECLARER"
    cash = admin.appeler("m5_etat_tresorerie", {}).resultat["cash_libre"]

    assert cash["cash_libre"] is None
    assert set(dict(ligne.split(" : ") for ligne in cash["manque"])) == {"taxes_a_remettre", "paies", "das", "dettes"}
    assert _composantes(cash)["comptes_a_payer"]["montant"] == "344.93"
    assert _composantes(cash)["reserves"]["montant"] == "500.00"
    assert cash["au_plus"] == "19155.07", "20000.00 - 344.93 - 500.00"


@SQLITE_SEULEMENT
def test_l_employe_n_a_aucune_portee_et_la_vue_sans_droit_ne_montre_aucun_montant(moteur, equipe, tmp_path,
                                                                                  monkeypatch):
    admin, employe = equipe["admin"], equipe["employe"]
    _declarer(tmp_path, monkeypatch, CONFIGURATION)
    _preparer(moteur)
    avant = moteur.empreinte_etat()

    for outil, args in (("m5_etat_tresorerie", {}), ("m5_lire_echeances_fiscales", {"aujourd_hui": AUJOURD_HUI})):
        refuse = employe.appeler(outil, args)
        assert refuse.statut == 403 and refuse.ok is False, (outil, refuse.corps)
        assert "14106" not in json.dumps(refuse.corps) and "cash_libre" not in json.dumps(refuse.corps)

    masque = admin.appeler("m5_etat_tresorerie", {"autorise_couts": False}).resultat
    assert masque["solde"] is None and masque["argent_disponible"] is None and masque["cash_libre"] is None
    assert masque["mention"] == MENTION
    sans_montant = admin.appeler("m5_lire_echeances_fiscales", {"aujourd_hui": AUJOURD_HUI, "autorise_couts": False})
    assert "taxes_nettes" not in json.dumps(sans_montant.corps) and "748.75" not in json.dumps(sans_montant.corps)
    assert moteur.empreinte_etat() == avant, "lire n'écrit rien : ni registre, ni approbation, ni événement"


@SQLITE_SEULEMENT
def test_aucun_decaissement_aucune_remise_lire_ne_bouge_pas_un_cent(moteur, equipe, tmp_path, monkeypatch):
    admin = equipe["admin"]
    _declarer(tmp_path, monkeypatch, CONFIGURATION)
    _preparer(moteur)
    avant = moteur.empreinte_etat()
    with stockage.transaction():
        mouvements_avant = list(stockage.maillons("m05-financecore", "principal"))

    admin.appeler("m5_etat_tresorerie", {})
    admin.appeler("m5_lire_echeances_fiscales", {"aujourd_hui": AUJOURD_HUI})
    admin.appeler("m5_lire_echeances_fiscales", {"aujourd_hui": "2027-03-01"})

    assert moteur.empreinte_etat() == avant
    with stockage.transaction():
        mouvements_apres = list(stockage.maillons("m05-financecore", "principal"))
    assert mouvements_apres == mouvements_avant and len(mouvements_apres) == 2, "solde et réserve, rien d'autre"
    assert not [m for m in mouvements_apres if m["type_mouvement"] == "DECAISSEMENT"]
    assert moteur.bilan()["troncatures"] == []
