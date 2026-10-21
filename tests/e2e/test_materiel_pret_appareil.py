"""PLAN T4.14 : E2E de la réservation et du « matériel prêt », par la porte d'appareil et par le VRAI bus
(DEFINITION-PRODUIT §6 « flux des matériaux » : « M6 vérifie le stock, réserve, ou crée un besoin de commande » ;
§9.5 « chantiers sans matériel prêt », « stock réservé et disponible »).

Le core ne tourne pas ici : ces tests prouvent tout ce qui est À PARTIR du moteur, par le vrai chemin réseau du moteur
(`tests/fixtures/harnais_e2e.py` : vraie application HTTP MCP sur un vrai uvicorn, base temporaire migrée, dix
départements réels, personnes et appareils créés par les commandes réelles du socle).

Le trajet (quantités fictives : 100 gouttières et 20 boîtes de vis pour le devis accepté) :

1. `m3.devis_accepte` -> le bus livre M6 : stock nul, donc la réservation dit `a_commander` (révision 1) ; AUCUN
   bon de commande n'existe ;
2. l'admin lit sur son téléphone la disponibilité et la réservation qui manque de tout (`m6_lire_disponibilite`) ;
3. l'admin RÉCEPTIONNE 100 gouttières (partiel : `partiel`, révision 2), puis les vis : `pret` (révision 3) ;
4. l'admin DÉPLACE du stock vers le rebut (`m6_transferer_stock`, N3, exécuté par l'humain lui-même) : l'audit porte
   SA personne, l'en main baisse, la réservation cède (`partiel`, révision 4) ; la chaîne de mouvements de stock n'a
   pas bougé ; le même geste rejoué avec la même clé ne fait rien de plus, avec une autre clé et le même
   `transfert_id` non plus ;
5. l'admin LIBÈRE la réservation (`m6_liberer_reservation`, N2) : `a_commander`, `reservation_active` faux
   (révision 5) ;
6. l'employé n'a aucune portée sur ces quatre outils (fermé à la porte) ;
7. aucun bon de commande n'a été créé seul, et aucune réponse n'a été tronquée par `Capacites` (6 000 caractères).

Données fictives (AGENTS.md).
"""

from __future__ import annotations

from typing import Any

import pytest
from harnais_e2e import Moteur, iso
from m6_material_control import emplacements
from sqlalchemy import select

from opsys import evenements, stockage
from opsys.evenements.schemas import erreurs_charge
from opsys.stockage import codec
from opsys.stockage.schema import APPROBATIONS, EVENEMENTS_SORTANTS

FICTIF = True
SQLITE_SEULEMENT = pytest.mark.parametrize("moteur", ["sqlite"], indirect=True)
M6 = "m06-material-control"
DEVIS = "DEVIS-E2E-MP-1"
CHANTIER = "CHANTIER-E2E-MP-1"
GOUTTIERE = "gouttiere-5po-fictif"
VIS = "vis-inox-fictif"
CATALOGUE = {"version": "v1", "unite_monetaire": "CAD",
             "postes": {GOUTTIERE: {"cout_unitaire": 5.0, "libelle": "Gouttière 5 po"},
                        VIS: {"cout_unitaire": 0.5, "libelle": "Vis inox"}}}


def _devis_accepte(moteur: Moteur) -> None:
    charge = {
        "devis_id": DEVIS, "lead_id": "lead-fictif", "chantier_id": CHANTIER,
        "lignes": [{"reference_ligne": f"{DEVIS}-L{i}", "description": "ligne fictive", "quantite": quantite,
                    "unite": unite, "prix_unitaire": "10.00", "prix_ligne": "10.00",
                    "reference_besoin_materiau": materiau}
                   for i, (materiau, quantite, unite) in enumerate([(GOUTTIERE, "100", "pi"), (VIS, "20", "boite")])],
        "cout_total": "100.00", "prix_total": "135.00", "taux_marge": "0.35",
        "horodatage_acceptation": iso(moteur.horloge.maintenant)}
    evenements.publier("m3.devis_accepte", "m03-estimation", charge, evenement_id=f"m3-devis-accepte-{DEVIS}")


def _livrer_m6(moteur: Moteur) -> None:
    """Le vrai répartiteur, M6 SEUL : `m3.devis_accepte` est aussi consommé par M2, M4, M5 et M8, dont ce trajet
    n'est pas l'objet (un lead inconnu de M2 partirait en quarantaine, légitimement)."""
    for _ in range(6):
        resume = evenements.repartir({M6: moteur.departements[M6]}, maintenant=iso(moteur.horloge.maintenant))
        assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume
        if resume["livres"] == 0:
            return
    raise AssertionError("le bus n'a pas atteint le repos")


def _charges() -> list[dict[str, Any]]:
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS.c.charge).where(
            EVENEMENTS_SORTANTS.c.type_evenement == "m6.materiel_pret").order_by(EVENEMENTS_SORTANTS.c.cree_le)).all()
    return [codec.decoder(ligne[0]) for ligne in lignes]


def _maillons(nom: str) -> list[dict[str, Any]]:
    with stockage.transaction():
        return list(stockage.maillons(M6, nom))


def _reception(moteur: Moteur, appareil: Any, materiau: str, quantite: float, po_id: str, cle: str) -> Any:
    maintenant = moteur.horloge.maintenant
    return appareil.appeler("m6_receptionner_commande", {
        "bon_demande": {"po_id": po_id, "chantier_id": "CHANTIER-DEPOT", "horodatage": iso(maintenant),
                        "lignes_demandees": [{"materiau_id": materiau, "quantite_demandee": quantite}]},
        "reception_po": {"po_id": po_id, "chantier_id": "CHANTIER-DEPOT", "horodatage": iso(maintenant),
                         "lignes_recues": [{"materiau_id": materiau, "quantite_recue": quantite}]},
        "catalogue_materiaux": CATALOGUE,
    }, cle=cle, horodatage_appareil=iso(maintenant))


def _transfert(
    moteur: Moteur, appareil: Any, transfert_id: str, de: dict, vers: dict, quantite: float, cle: str
) -> Any:
    return appareil.appeler("m6_transferer_stock", {
        "transfert_id": transfert_id, "materiau_id": GOUTTIERE, "quantite": quantite, "de": de, "vers": vers,
        "motif": "gouttières bosselées au déchargement", "horodatage": iso(moteur.horloge.maintenant),
    }, cle=cle, horodatage_appareil=iso(moteur.horloge.maintenant))


# ============================================================================================ le trajet
def test_devis_accepte_a_commander_reception_pret_transfert_audite_liberation(moteur, equipe):
    admin, employe = equipe["admin"], equipe["employe"]

    # 1. le devis accepté : stock nul, `a_commander`, aucun bon de commande
    _devis_accepte(moteur)
    _livrer_m6(moteur)
    (premiere,) = _charges()
    assert erreurs_charge("m6.materiel_pret", premiere) == []
    assert (premiere["statut"], premiere["revision"], premiere["declencheur"]) == ("a_commander", 1, "devis_accepte")
    assert [m["quantite_manquante"] for m in premiere["lignes_manquantes"]] == ["100", "20"]
    assert "m06-material-control/bons_commande" not in moteur.empreinte_etat()["registres"]

    # 2. l'admin lit, sur son téléphone, ce qui est en main, réservé, disponible
    lecture = admin.appeler("m6_lire_disponibilite", {"materiau_ids": [GOUTTIERE, VIS]})
    assert lecture.ok, lecture.corps
    vue = lecture.resultat
    assert [(a["materiau_id"], a["en_main"], a["reserve"], a["disponible"]) for a in vue["articles"]] == [
        (GOUTTIERE, "0", "0", "0"), (VIS, "0", "0", "0")]
    (reservation,) = vue["reservations_actives"]
    assert (reservation["devis_id"], reservation["statut"]) == (DEVIS, "a_commander")

    # 3. réceptions : les gouttières (partiel), puis les vis (prêt)
    gouttieres = _reception(moteur, admin, GOUTTIERE, 100.0, "PO-E2E-MP-1", "cle-reception-1")
    assert gouttieres.ok and gouttieres.metier["accepte"] is True, gouttieres.corps
    assert len(gouttieres.metier["evenements_materiel_pret"]) == 1
    vis = _reception(moteur, admin, VIS, 20.0, "PO-E2E-MP-2", "cle-reception-2")
    assert vis.ok and vis.metier["accepte"] is True, vis.corps
    _livrer_m6(moteur)
    assert [(c["revision"], c["statut"], c["declencheur"]) for c in _charges()] == [
        (1, "a_commander", "devis_accepte"), (2, "partiel", "stock_recu"), (3, "pret", "stock_recu")]
    assert _charges()[-1]["lignes_manquantes"] == []

    # 4. transfert audité vers le rebut : l'en main baisse, la réservation cède ; la chaîne de mouvements ne bouge pas
    principal = _maillons("principal")
    transfert = _transfert(moteur, admin, "T-E2E-1", {"type": "inconnu"}, {"type": "rebut"}, 30.0, "cle-transfert-1")
    assert transfert.ok and transfert.metier["accepte"] is True, transfert.corps
    assert transfert.metier["statut"] == "enregistre" and len(transfert.metier["evenements_materiel_pret"]) == 1
    (maillon,) = _maillons("emplacements")
    assert (maillon["acteur"], maillon["motif"]) == ("nathan", "gouttières bosselées au déchargement")
    assert (maillon["avant"], maillon["apres"]) == ({"de": "100", "vers": "0"}, {"de": "70", "vers": "30"})
    assert emplacements.valider_chaine(_maillons("emplacements")) == (True, "")
    assert _maillons("principal") == principal, "la chaîne de mouvements de stock n'a pas bougé"
    derniere = _charges()[-1]
    assert (derniere["revision"], derniere["statut"], derniere["declencheur"]) == (4, "partiel", "stock_sorti")
    assert derniere["lignes"][0]["quantite_reservee"] == "70"

    # l'humain qui agit lui-même n'attend aucune approbation : tracé « executee » sous son nom
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(APPROBATIONS.c.statut, APPROBATIONS.c.decide_par).where(
            APPROBATIONS.c.outil == "m6_transferer_stock")).all()
    assert lignes == [("executee", "nathan")]

    # le même geste rejoué (même clé) ne fait rien de plus ; le même transfert_id sous une autre clé non plus
    apres_transfert = moteur.empreinte_etat()
    rejoue = _transfert(moteur, admin, "T-E2E-1", {"type": "inconnu"}, {"type": "rebut"}, 30.0, "cle-transfert-1")
    assert rejoue.ok and rejoue.enveloppe["rejoue"] is True
    assert moteur.empreinte_etat() == apres_transfert
    autre_cle = _transfert(moteur, admin, "T-E2E-1", {"type": "inconnu"}, {"type": "rebut"}, 30.0, "cle-transfert-2")
    assert autre_cle.metier["accepte"] is True and autre_cle.metier["statut"] == "deja_enregistre"
    assert len(_maillons("emplacements")) == 1 and len(_charges()) == 4

    # 5. libération (N2) : `a_commander`, plus active
    liberation = admin.appeler("m6_liberer_reservation", {
        "devis_id": DEVIS, "motif": "le client a annulé le chantier", "horodatage": iso(moteur.horloge.maintenant)},
        cle="cle-liberation-1", horodatage_appareil=iso(moteur.horloge.maintenant))
    assert liberation.ok and liberation.metier["accepte"] is True, liberation.corps
    assert liberation.metier["statut"] == "liberee"
    derniere = _charges()[-1]
    assert (derniere["revision"], derniere["statut"], derniere["reservation_active"]) == (5, "a_commander", False)
    assert erreurs_charge("m6.materiel_pret", derniere) == []
    disponibilite = admin.appeler("m6_lire_disponibilite", {"materiau_ids": [GOUTTIERE]}).resultat
    (article,) = disponibilite["articles"]
    assert (article["stock_theorique"], article["hors_main"], article["en_main"], article["reserve"],
            article["disponible"]) == ("100", "30", "70", "0", "70")
    assert disponibilite["reservations_actives"] == []

    # 6. l'employé n'a aucune portée sur ces quatre outils : fermé à la porte
    avant = moteur.empreinte_etat()
    for outil, arguments in (
        ("m6_lire_disponibilite", {}),
        ("m6_reserver_materiel", {"devis_id": DEVIS, "horodatage": iso(moteur.horloge.maintenant)}),
        ("m6_liberer_reservation", {"devis_id": DEVIS, "motif": "x", "horodatage": iso(moteur.horloge.maintenant)}),
        ("m6_transferer_stock", {"transfert_id": "T-EMPLOYE", "materiau_id": GOUTTIERE, "quantite": 1.0,
                                 "de": {"type": "inconnu"}, "vers": {"type": "depot"}, "motif": "x",
                                 "horodatage": iso(moteur.horloge.maintenant)}),
    ):
        refuse = employe.appeler(outil, arguments, cle=f"cle-employe-{outil}")
        assert refuse.statut == 403 and refuse.ok is False, (outil, refuse.corps)
    assert moteur.empreinte_etat() == avant

    # 7. aucun bon de commande créé seul ; rien de tronqué
    assert "m06-material-control/bons_commande" not in moteur.empreinte_etat()["registres"]
    assert moteur.bilan()["troncatures"] == []


@SQLITE_SEULEMENT
def test_l_admin_re_reserve_apres_liberation_et_le_bus_ne_le_fait_pas(moteur, equipe):
    """Le bus ne défait jamais ce qu'un humain a libéré : rejouer `m3.devis_accepte` ne re-réserve pas. L'admin, lui, le
    peut sur son téléphone (`m6_reserver_materiel`)."""
    admin = equipe["admin"]
    _devis_accepte(moteur)
    _livrer_m6(moteur)
    assert _reception(moteur, admin, GOUTTIERE, 100.0, "PO-E2E-MP-1", "cle-r1").ok
    assert _reception(moteur, admin, VIS, 20.0, "PO-E2E-MP-2", "cle-r2").ok
    liberation = admin.appeler("m6_liberer_reservation", {
        "devis_id": DEVIS, "motif": "chantier reporté", "horodatage": iso(moteur.horloge.maintenant)},
        cle="cle-l1", horodatage_appareil=iso(moteur.horloge.maintenant))
    assert liberation.metier["accepte"] is True
    apres_liberation = len(_charges())

    _devis_accepte(moteur)  # même identifiant : no-op du bus
    _livrer_m6(moteur)
    assert len(_charges()) == apres_liberation

    reserve = admin.appeler("m6_reserver_materiel", {"devis_id": DEVIS, "horodatage": iso(moteur.horloge.maintenant)},
                            cle="cle-rr1", horodatage_appareil=iso(moteur.horloge.maintenant))
    assert reserve.ok and reserve.metier["accepte"] is True, reserve.corps
    dernier = _charges()[-1]
    assert (dernier["statut"], dernier["reservation_active"], dernier["declencheur"]) == (
        "pret", True, "reservation_manuelle")
