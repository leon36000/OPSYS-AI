"""PLAN T4.16-d : E2E de la prévision de trésorerie (M5.7), par la porte d'appareil et par le VRAI bus
(DEFINITION-PRODUIT §7 M5 : la trésorerie se lit sur le téléphone du propriétaire ; §9.5 « admin : trésorerie »).

Le core ne tourne pas ici : ces tests prouvent tout ce qui est À PARTIR du moteur, par le vrai chemin réseau du moteur
(`tests/fixtures/harnais_e2e.py` : vraie application HTTP MCP sur un vrai uvicorn, base temporaire migrée, dix
départements réels, porte d'appareil refaite d'après le fork, personnes et appareils créés par les commandes réelles
du socle).

Le trajet, chiffré à la cent près (entreprise fictive, trimestrielle, exercice au 31 décembre, remise faite jusqu'au
30 juin ; aujourd'hui, le mardi 2026-09-29 ; horizon de six semaines ; délais de paiement de 30 jours, déclarés) :

    solde 20000.00 (un encaissement) ; réserve 500.00 (un mouvement de réserve)
    facture cliente envoyée le 14 septembre : 5000.00 + TPS 250.00 + TVQ 498.75 = 5748.75 -> due le 10-14 (semaine 3)
    réception de M6 par le vrai bus le 14 septembre : 60 gouttières à 5.00 = 300.00, à payer 344.93 (attendu non
    facturé) -> 10-14 (semaine 3)
    taxes du trimestre : TPS 250.00 + TVQ 498.75 = 748.75, limite de paiement le 11-02 (semaine 5)
    paies 3000.00 le 10-09 (semaine 2), DAS 900.00 le 10-15 (semaine 3), dettes 400.00 le 10-31 (semaine 5)

    semaine 1 : rien                                      20000.00
    semaine 2 : sorties 3000.00                           20000.00 - 3000.00                   = 17000.00
    semaine 3 : entrées 5748.75, sorties 344.93 + 900.00  17000.00 + 5748.75 - 1244.93         = 21503.82
    semaine 4 : rien                                                                           = 21503.82
    semaine 5 : sorties 400.00 + 748.75                   21503.82 - 1148.75                   = 20355.07
    semaine 6 : rien                                                                           = 20355.07
    alerte sous 18000.00 : la semaine 2 seulement
    cash libre d'aujourd'hui (T4.16) 20000.00 - (748.75 + 3000.00 + 900.00 + 344.93 + 400.00 + 500.00) = 14106.32 ;
    cash libre prévu = 14106.32 (semaines 1 et 2) puis + 5748.75 = 19855.07 (3 à 6) ; 20355.07 - 500.00 = 19855.07

1. l'admin lit la prévision sur son téléphone : les six soldes, l'alerte, le même cash libre que `m5_etat_tresorerie` ;
2. les lignes de la semaine 3, chacune avec sa source ;
3. l'employé n'a aucune portée ; la vue sans droit ne montre aucun montant ;
4. le manifeste livré (rien de déclaré) : l'horizon est refusé, puis « non calculable dès la semaine 1 » ;
5. 26 semaines se lisent page par page, jamais tronquées par `Capacites` (6 000 caractères) ;
6. rien n'a été écrit : aucun décaissement, aucune remise, aucun événement.

Données fictives (AGENTS.md).
"""

from __future__ import annotations

import json

import m5_financecore.outils as m5_outils
import pytest
import yaml
from harnais_e2e import Moteur
from m5_financecore import facturation, taux_fiscaux
from m5_financecore.analyse import MENTION_ANALYSE_PREPARATOIRE as MENTION

from opsys import evenements, stockage
from opsys.outils import executer_atomique

FICTIF = True
SQLITE_SEULEMENT = pytest.mark.parametrize("moteur", ["sqlite"], indirect=True)

PO = "PO-E2E-PV-1"
FOURNISSEUR = "gentek-fictif"
AUJOURD_HUI = "2026-09-29"
SOLDES = ["20000.00", "17000.00", "21503.82", "21503.82", "20355.07", "20355.07"]

CONFIGURATION = {
    "fiscal": {"frequence_tps_tvq": "trimestrielle", "mois_fin_exercice": 12, "taxes_remises_jusqu_au": "2026-06-30"},
    "obligations_declarees": {
        "paies": {"montant": "3000.00", "source": "brouillon de paie (fictif)", "au": "2026-09-25"},
        "das": {"montant": "900.00", "source": "estimation du CPA (fictive)", "au": "2026-09-25"},
        "dettes": {"montant": "400.00", "source": "relevé du prêt camion (fictif)", "au": "2026-09-01"},
    },
    "prevision": {
        "horizon_semaines": 6,
        "seuil_alerte": {"montant": "18000.00", "source": "décision de Nathan (fictive)", "au": "2026-09-25"},
        "delai_encaissement_clients_jours": 30, "delai_paiement_fournisseurs_jours": 30,
        "echeances_obligations": {"paies": "2026-10-09", "das": "2026-10-15", "dettes": "2026-10-31"},
    },
}


def _declarer(tmp_path, monkeypatch, configuration):
    manifeste = tmp_path / "department-m5-prevision-e2e.yaml"
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
            "F-E2E-PV-1", "CH-E2E-1", "D-E2E-1", "C-E2E-1",
            [{"description": "gouttières (fictif)", "quantite": "1", "unite": "forfait", "prix_unitaire": "5000.00",
              "reference_ligne_devis": "L-1"}], "2026-09-14T09:00:00-04:00", taux, registre_factures)
        assert verdict is None, verdict
        assert facturation.envoyer_facture("F-E2E-PV-1", "2026-09-14T09:30:00-04:00", registre_factures)[1] is None
        charge = {
            "evenement_id": "evt-e2e-pv-1", "po_id": PO, "fournisseur_id": FOURNISSEUR, "chantier_id": "CH-E2E-1",
            "horodatage_reception": "2026-09-14T09:00:00-04:00", "verdict_reception": "CONFORME",
            "statut_po": "received", "hash_maillon": "c" * 64, "seuil_ecart_prix_pourcentage": None,
            "lignes": [{"materiau_id": "gouttiere-5po-fictif", "quantite_demandee": "60", "quantite_recue": "60",
                        "prix_unitaire_prevu": "5.00", "devise_prevue": "CAD", "verdict_prix_po": "PRIX_LIVRE",
                        "prix_unitaire_reception": None, "verdict_prix_reception": "INDETERMINE",
                        "ecart_prix_critique": None}]}
        evenements.publier("m6.reception_enregistree", "m06-material-control", charge,
                           evenement_id=charge["evenement_id"])
    resume = moteur.drainer_bus(moteur.horloge.maintenant)
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume


@SQLITE_SEULEMENT
def test_la_prevision_du_proprietaire_semaine_par_semaine_a_la_cent_pres(moteur, equipe, tmp_path, monkeypatch):
    admin = equipe["admin"]
    _declarer(tmp_path, monkeypatch, CONFIGURATION)
    _preparer(moteur)

    reponse = admin.appeler("m5_prevoir_tresorerie", {"aujourd_hui": AUJOURD_HUI})

    assert reponse.ok and reponse.metier["accepte"] is True, reponse.corps
    page = reponse.resultat
    assert page["role"] == "admin" and page["mention"] == MENTION and page["type"] == "PREVISION_TRESORERIE"
    assert [s["solde_fin"] for s in page["semaines"]] == SOLDES
    assert [(s["entrees"], s["sorties"]) for s in page["semaines"]] == [
        ("0.00", "0.00"), ("0.00", "3000.00"), ("5748.75", "1244.93"), ("0.00", "0.00"), ("0.00", "1148.75"),
        ("0.00", "0.00")]
    assert [s["cash_libre_prevu"] for s in page["semaines"]] == [
        "14106.32", "14106.32", "19855.07", "19855.07", "19855.07", "19855.07"]
    assert page["calculable"] is True and page["manque"] == [] and page["fin_horizon"] == "2026-11-09"
    assert page["alerte"] == {"statut": "ALERTE", "seuil": "18000.00", "semaines": [2], "source_du_seuil": {
        "source": "décision de Nathan (fictive)", "au": "2026-09-25"}}
    assert page["plus_bas"] == {"semaine": 2, "solde": "17000.00"}
    assert page["reserves"] == ["REJ-AP-UNITE-PRIX-NON-CONFIRMEE"] and len(page["limites"]) == 7

    # une seule vérité : le point de départ et le cash libre sont ceux de l'état de trésorerie
    etat = admin.appeler("m5_etat_tresorerie", {}).resultat
    assert etat["cash_libre"]["cash_libre"] == page["cash_libre_aujourd_hui"]["montant"] == "14106.32"
    assert etat["solde"] == page["solde_initial"]["montant"] == "20000.00"

    # rien n'a été tronqué par Capacites (6 000 caractères)
    assert moteur.bilan()["troncatures"] == []


@SQLITE_SEULEMENT
def test_les_lignes_de_la_semaine_3_portent_leur_source_et_la_regle_de_leur_date(moteur, equipe, tmp_path, monkeypatch):
    admin = equipe["admin"]
    _declarer(tmp_path, monkeypatch, CONFIGURATION)
    _preparer(moteur)

    page = admin.appeler("m5_prevoir_tresorerie", {"aujourd_hui": AUJOURD_HUI, "semaine": 3}).resultat

    assert page["type"] == "PREVISION_TRESORERIE_SEMAINE" and page["mention"] == MENTION
    assert (page["entrees"], page["sorties"], page["solde_fin"]) == ("5748.75", "1244.93", "21503.82")
    # à date égale, les sorties passent avant les entrées (l'ordre est total et stable)
    assert [(ligne["sens"], ligne["nature"], ligne["montant"], ligne["date"]) for ligne in page["lignes"]] == [
        ("SORTIE", "attendu_fournisseur", "344.93", "2026-10-14"),
        ("ENTREE", "facture_client", "5748.75", "2026-10-14"), ("SORTIE", "das", "900.00", "2026-10-15")]
    assert all(ligne["source"] and ligne["regle_de_date"] for ligne in page["lignes"])
    assert all("délai déclaré par le propriétaire" in ligne["regle_de_date"] for ligne in page["lignes"][:2])
    assert page["lignes"][0]["reserves"] == ["REJ-AP-UNITE-PRIX-NON-CONFIRMEE"]
    assert "reserves" not in page["lignes"][1]
    assert moteur.bilan()["troncatures"] == []


@SQLITE_SEULEMENT
def test_l_employe_n_a_aucune_portee_et_la_vue_sans_droit_ne_montre_aucun_montant(moteur, equipe, tmp_path,
                                                                                  monkeypatch):
    admin, employe = equipe["admin"], equipe["employe"]
    _declarer(tmp_path, monkeypatch, CONFIGURATION)
    _preparer(moteur)
    avant = moteur.empreinte_etat()

    refuse = employe.appeler("m5_prevoir_tresorerie", {"aujourd_hui": AUJOURD_HUI})
    assert refuse.statut == 403 and refuse.ok is False, refuse.corps
    assert "20000" not in json.dumps(refuse.corps) and "semaines" not in json.dumps(refuse.corps)

    masque = admin.appeler("m5_prevoir_tresorerie", {"aujourd_hui": AUJOURD_HUI, "autorise_couts": False}).resultat
    assert masque == {"role": "admin", "montants_masques": True, "horizon_semaines": 6, "mention": MENTION}
    assert moteur.empreinte_etat() == avant, "lire n'écrit rien : ni registre, ni approbation, ni événement"


@SQLITE_SEULEMENT
def test_le_manifeste_livre_ne_declare_rien_l_horizon_est_refuse_puis_tout_est_non_calculable(moteur, equipe):
    """Sans déclaration du propriétaire (le vrai manifeste de M5, GATE NATHAN) : aucun horizon, aucun délai, aucun
    seuil ne sont supposés ; la prévision dit ce qui manque, jamais zéro, jamais une moyenne."""
    admin = equipe["admin"]
    _preparer(moteur)

    refus = admin.appeler("m5_prevoir_tresorerie", {"aujourd_hui": AUJOURD_HUI})
    assert refus.ok and refus.metier["accepte"] is False
    assert refus.metier["verdict"]["code"] == "REJ-PREVISION-HORIZON-A-CONFIGURER"
    assert "semaines" not in refus.metier

    page = admin.appeler("m5_prevoir_tresorerie", {"aujourd_hui": AUJOURD_HUI, "horizon_semaines": 4}).resultat

    assert page["calculable"] is False and page["non_calculable_a_partir_de"] == 1
    assert all(s["statut"] == "NON_CALCULABLE" and "solde_fin" not in s for s in page["semaines"])
    assert page["alerte"]["statut"] == "SEUIL_A_CONFIGURER" and page["alerte"]["manque"]["code"] == (
        "REJ-PREVISION-SEUIL-A-CONFIGURER")
    codes = {m["code"] for m in page["manque"]}
    assert {"REJ-PREVISION-DELAI-FOURNISSEURS-A-DECLARER", "REJ-FISCAL-FREQUENCE-A-DECLARER",
            "REJ-CASH-PAIE-A-DECLARER"} <= codes
    assert {e["code"] for e in page["encaissements_non_comptes"]} == {"REJ-PREVISION-DELAI-CLIENTS-A-DECLARER"}
    assert "aucun chiffre n'est donné" in page["lecture"]
    assert moteur.bilan()["troncatures"] == []


@SQLITE_SEULEMENT
def test_vingt_six_semaines_se_lisent_page_par_page_sans_jamais_etre_tronquees(moteur, equipe, tmp_path, monkeypatch):
    admin = equipe["admin"]
    _declarer(tmp_path, monkeypatch, CONFIGURATION)
    _preparer(moteur)

    semaines, depart, pages = [], 0, 0
    while depart is not None:
        page = admin.appeler("m5_prevoir_tresorerie", {
            "aujourd_hui": AUJOURD_HUI, "horizon_semaines": 26, "depart": depart}).resultat
        semaines.extend(page["semaines"])
        depart, pages = page["prochain_depart"], pages + 1
        assert page["mention"] == MENTION

    assert pages > 1 and [s["semaine"] for s in semaines] == list(range(1, 27))
    assert [s["solde_fin"] for s in semaines[:6]] == SOLDES and {s["solde_fin"] for s in semaines[5:]} == {"20355.07"}
    assert moteur.bilan()["troncatures"] == [], "chaque page tient sous la limite du socle : rien n'a été coupé"


@SQLITE_SEULEMENT
def test_aucun_decaissement_aucune_remise_prevoir_ne_bouge_pas_un_cent(moteur, equipe, tmp_path, monkeypatch):
    admin = equipe["admin"]
    _declarer(tmp_path, monkeypatch, CONFIGURATION)
    _preparer(moteur)
    avant = moteur.empreinte_etat()
    with stockage.transaction():
        mouvements_avant = list(stockage.maillons("m05-financecore", "principal"))

    admin.appeler("m5_prevoir_tresorerie", {"aujourd_hui": AUJOURD_HUI})
    admin.appeler("m5_prevoir_tresorerie", {"aujourd_hui": AUJOURD_HUI, "semaine": 3})
    admin.appeler("m5_prevoir_tresorerie", {"aujourd_hui": AUJOURD_HUI, "horizon_semaines": 26})

    assert moteur.empreinte_etat() == avant
    with stockage.transaction():
        mouvements_apres = list(stockage.maillons("m05-financecore", "principal"))
    assert mouvements_apres == mouvements_avant and len(mouvements_apres) == 2, "solde et réserve, rien d'autre"
    assert not [m for m in mouvements_apres if m["type_mouvement"] == "DECAISSEMENT"]
    assert moteur.bilan()["troncatures"] == []
