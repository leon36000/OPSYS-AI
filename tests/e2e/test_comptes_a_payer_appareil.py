"""PLAN T4.15 : E2E des comptes à payer, par la porte d'appareil et par le VRAI bus (DEFINITION-PRODUIT §6 « flux des
matériaux » : « fournisseur confirme -> réception (complète ou partielle) -> [...] M5 »).

Le core ne tourne pas ici : ces tests prouvent tout ce qui est À PARTIR du moteur, par le vrai chemin réseau du
moteur (`tests/fixtures/harnais_e2e.py` : vraie application HTTP MCP sur un vrai uvicorn, base temporaire migrée, dix
départements réels, porte d'appareil refaite d'après le fork, personnes et appareils créés par les commandes réelles
du socle).

Le trajet, chiffré à la cent près (PO de 320.00 $ chez Gentek : 60 gouttières à 5.00 $ et 40 vis à 0.50 $) :

1. M6 prépare un PO PERSISTÉ, jusqu'à `sent_to_supplier` (fournisseur, prix, prévu, PO, approbation, courriel,
   envoi : des gestes d'agent, sans portée d'appareil) ;
2. l'admin réceptionne PARTIELLEMENT sur son téléphone (60 gouttières, aucune vis) : `m6_receptionner_commande`
   publie `m6.reception_enregistree` dans la transaction de la réception ;
3. le bus livre l'événement à M5 : « à payer attendu » PARTIEL, 300.00 $ avant taxes, 44.93 $ de taxes (TVQ :
   29.925 $ monte à 29.93 $, ROUND_HALF_UP), 344.93 $ à payer, verdict `SANS_FACTURE` ;
4. l'admin SAISIT la facture (elle ne peut pas venir d'un agent seul) : `CONCORDANT` ; le même geste rejoué avec la
   même clé d'idempotence ne fait rien de plus ; le même contenu sous une autre clé est un DOUBLON, refusé ;
5. l'employé n'a aucune portée sur ces deux outils (fermé à la porte) ;
6. la deuxième livraison (40 vis) donne un attendu de 320.00 $ : `ECART` dans le sens « facture inférieure au
   reçu », 367.93 $ à payer ; la deuxième facture le ramène à `CONCORDANT` ;
7. RIEN n'a été écrit au registre des mouvements ni aux factures clients : aucun DECAISSEMENT n'existe.

Un scénario lit 40 PO par pages : aucune page n'est tronquée par `Capacites` (6 000 caractères), chaque PO est lu
une fois. Un autre montre qu'une personne désactivée ne saisit rien. Données fictives (AGENTS.md).
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import pytest
from harnais_e2e import Moteur, Reponse, iso
from sqlalchemy import select

from opsys import approbations, evenements, identite, stockage
from opsys.capacites import Capacites, outils_executables
from opsys.outils import executer_atomique
from opsys.stockage.schema import APPROBATIONS

FICTIF = True
SQLITE_SEULEMENT = pytest.mark.parametrize("moteur", ["sqlite"], indirect=True)
LIMITE_TRONCATURE = 6000  # `jetons.LIMITE_SORTIE_DEFAUT`

PO = "PO-E2E-AP-1"
DEVIS = "DEVIS-E2E-AP-1"
CHANTIER = "CHANTIER-E2E-AP-1"
FOURNISSEUR = "gentek-fictif"
GOUTTIERE = "gouttiere-5po-fictif"
VIS = "vis-inox-fictif"
CATALOGUE = {"version": "v1", "unite_monetaire": "CAD",
             "postes": {GOUTTIERE: {"cout_unitaire": 5.0, "libelle": "Gouttière 5 po"},
                        VIS: {"cout_unitaire": 0.5, "libelle": "Vis inox"}}}


# ------------------------------------------------------------------------------------------ petits outils
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
    _agent(m6["m6_enregistrer_prix"], {
        "materiau_id": GOUTTIERE, "fournisseur_id": FOURNISSEUR, "prix_unitaire": 5.0, "devise": "CAD",
        "date_effet": "2026-09-01"})
    _agent(m6["m6_enregistrer_prix"], {
        "materiau_id": VIS, "fournisseur_id": FOURNISSEUR, "prix_unitaire": 0.5, "devise": "CAD",
        "date_effet": "2026-09-01"})
    _agent(m6["m6_enregistrer_besoins_prevus"], {
        "chantier_id": CHANTIER, "devis_id": DEVIS, "lignes": [
            {"materiau_id": GOUTTIERE, "quantite_estimee": 60.0, "unite": "pi"},
            {"materiau_id": VIS, "quantite_estimee": 40.0, "unite": "boite"}]})
    creation = _agent(m6["m6_creer_po_brouillon"], {
        "po_id": PO, "devis_id": DEVIS, "fournisseur_id": FOURNISSEUR, "horodatage": iso(maintenant)})
    assert creation["po"]["montant_total_prevu"] == 320.0, creation
    _agent(m6["m6_approuver_po"], {"po_id": PO, "horodatage": iso(maintenant, 60)})
    _agent(m6["m6_generer_courriel_po"], {
        "po_id": PO, "horodatage": iso(maintenant, 120), "nom_entreprise": "Entreprise Fictive"})
    envoi = _agent(m6["m6_marquer_po_envoye"], {"po_id": PO, "horodatage": iso(maintenant, 180)})
    assert envoi["po"]["statut"] == "sent_to_supplier"


def _livraison(moteur: Moteur, appareil: Any, gouttieres: float, vis: float, cle: str) -> Reponse:
    """La réception que l'admin fait sur son téléphone (`m6_receptionner_commande`, portée `admin`)."""
    maintenant = moteur.horloge.maintenant
    return appareil.appeler("m6_receptionner_commande", {
        "bon_demande": {"po_id": PO, "chantier_id": CHANTIER, "horodatage": iso(maintenant), "lignes_demandees": [
            {"materiau_id": GOUTTIERE, "quantite_demandee": 60.0}, {"materiau_id": VIS, "quantite_demandee": 40.0}]},
        "reception_po": {"po_id": PO, "chantier_id": CHANTIER, "horodatage": iso(maintenant), "lignes_recues": [
            {"materiau_id": GOUTTIERE, "quantite_recue": gouttieres}, {"materiau_id": VIS, "quantite_recue": vis}]},
        "catalogue_materiaux": CATALOGUE,
    }, cle=cle, horodatage_appareil=iso(maintenant))


def _facture(moteur: Moteur, appareil: Any, numero: str, montant: str, cle: str, total: str | None = None) -> Reponse:
    return appareil.appeler("m5_saisir_facture_fournisseur", {
        "po_id": PO, "fournisseur_id": FOURNISSEUR, "numero_facture": numero, "date_facture": "2026-09-14",
        "montant_avant_taxes": montant, "total_facture": total, "horodatage": iso(moteur.horloge.maintenant),
    }, cle=cle, horodatage_appareil=iso(moteur.horloge.maintenant))


def _le_po(appareil: Any, po_id: str = PO) -> dict[str, Any]:
    page = appareil.appeler("m5_lister_comptes_a_payer", {"po_id": po_id}).resultat
    assert page["total"] == 1
    return page["comptes"][0]


def _livrer_le_bus(moteur: Moteur) -> None:
    resume = moteur.drainer_bus(moteur.horloge.maintenant)
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume


def _registres(moteur: Moteur) -> dict[str, int]:
    return moteur.empreinte_etat()["registres"]


# ============================================================================================ le trajet
def test_reception_partielle_a_payer_partiel_facture_saisie_doublon_refuse(moteur, equipe):
    admin, employe = equipe["admin"], equipe["employe"]
    _preparer_po(moteur)

    # 2. réception PARTIELLE sur le téléphone de l'admin : l'événement part dans la transaction de la réception
    partielle = _livraison(moteur, admin, gouttieres=60.0, vis=0.0, cle="cle-reception-1")
    assert partielle.ok and partielle.metier["accepte"] is True, partielle.corps
    assert partielle.metier["po"]["statut"] == "partially_received"
    evenement_id = partielle.metier["evenement_reception_id"]
    assert evenement_id.startswith(f"m6-reception-{PO}-")
    with stockage.transaction():
        charge = evenements.charge_publiee("m6.reception_enregistree", evenement_id)
    assert charge["lignes"][0]["quantite_recue"] == "60.0" and charge["lignes"][1]["quantite_recue"] == "0.0"
    assert not [cle for cle in charge if "montant" in cle or "total" in cle], "M6 ne dit aucun montant"

    # 3. le bus livre M5 : l'à payer ATTENDU, partiel, à la cent près
    _livrer_le_bus(moteur)
    apres_reception = _le_po(admin)
    assert apres_reception["attendu"] == {"avant_taxes": "300.00", "taxes": "44.93", "apres_taxes": "344.93"}
    assert apres_reception["a_payer_apres_taxes"] == "344.93"
    assert apres_reception["statut_po"] == "partially_received" and apres_reception["receptions"] == 1
    rapprochement = apres_reception["rapprochement"]
    assert rapprochement["statut"] == "PROPOSE" and rapprochement["verdict"] == "SANS_FACTURE"
    assert rapprochement["commande_avant_taxes"] == "320.00" and rapprochement["recu_moins_commande"] == "-20.00"
    assert rapprochement["reste_a_recevoir"] == [{"materiau_id": VIS, "quantite": "40.0"}]
    assert rapprochement["reserves"] == ["REJ-AP-UNITE-PRIX-NON-CONFIRMEE"], "l'unité des prix n'est pas déclarée"
    page = admin.appeler("m5_lister_comptes_a_payer", {}).resultat
    assert any("GATE NATHAN" in h for h in page["hypotheses"])
    assert page["taxes_versions"] == {"tps_federale": "2026-v1", "tvq_quebec": "2026-v1"}

    # 4. la facture est SAISIE par l'humain (son téléphone) ; le rapprochement est proposé, jamais appliqué
    avant_facture = moteur.empreinte_etat()
    saisie = _facture(moteur, admin, "F-1001", "300.00", cle="cle-facture-1", total="344.93")
    assert saisie.ok and saisie.metier["accepte"] is True, saisie.corps
    facture = saisie.metier["resultat"]["facture"]
    assert (facture["montant_apres_taxes"], facture["total_taxes"], facture["statut"]) == ("344.93", "44.93", "SAISIE")
    assert (facture["saisi_par"], facture["voie"]) == ("nathan", "appareil")
    assert saisie.metier["resultat"]["rapprochement"]["verdict"] == "CONCORDANT"
    assert _le_po(admin)["a_payer_apres_taxes"] == "344.93"
    apres_facture = moteur.empreinte_etat()
    assert apres_facture["registres"]["m05-financecore/comptes_a_payer"] == (
        avant_facture["registres"]["m05-financecore/comptes_a_payer"] + 1)

    # la validation humaine au départ est tracée par le socle (l'humain qui agit lui-même)
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(APPROBATIONS.c.statut, APPROBATIONS.c.decide_par).where(
            APPROBATIONS.c.outil == "m5_saisir_facture_fournisseur")).all()
    assert lignes == [("executee", "nathan")]

    # le même geste rejoué (même clé) ne fait rien de plus : aucun double effet
    rejoue = _facture(moteur, admin, "F-1001", "300.00", cle="cle-facture-1", total="344.93")
    assert rejoue.ok and rejoue.enveloppe["rejoue"] is True
    assert moteur.empreinte_etat() == apres_facture

    # le même contenu sous une AUTRE clé est un doublon : refusé, et rien n'est écrit
    doublon = _facture(moteur, admin, "F-1001", "300.00", cle="cle-facture-2")
    assert doublon.ok and doublon.metier["accepte"] is False
    assert doublon.metier["verdict"]["code"] == "REJ-AP-FACTURE-DOUBLON"
    assert facture["facture_fournisseur_id"] in doublon.metier["verdict"]["detail"]
    registres_apres_doublon = moteur.empreinte_etat()["registres"]
    assert registres_apres_doublon == apres_facture["registres"]

    # un total imprimé qui ne concorde pas : refusé avec les deux chiffres
    incoherent = _facture(moteur, admin, "F-1002", "300.00", cle="cle-facture-3", total="344.92")
    assert incoherent.metier["accepte"] is False
    assert incoherent.metier["verdict"]["code"] == "REJ-AP-FACTURE-TOTAL-INCOHERENT"
    assert moteur.empreinte_etat()["registres"] == apres_facture["registres"]

    # 5. l'employé n'a aucune portée sur les comptes à payer : fermé à la porte
    for outil, args in (("m5_lister_comptes_a_payer", {}), ("m5_saisir_facture_fournisseur", {
            "po_id": PO, "fournisseur_id": FOURNISSEUR, "numero_facture": "F-9", "date_facture": "2026-09-14",
            "montant_avant_taxes": "1.00", "total_facture": None, "horodatage": iso(moteur.horloge.maintenant)})):
        refuse = employe.appeler(outil, args, cle="cle-employe" if outil.startswith("m5_saisir") else None)
        assert refuse.statut == 403 and refuse.ok is False, (outil, refuse.corps)
    assert moteur.empreinte_etat()["registres"] == apres_facture["registres"]

    # 6. deuxième livraison : le reste (40 vis) ; attendu 320.00 $, facturé 300.00 $ : un ÉCART, dans le bon sens
    seconde = _livraison(moteur, admin, gouttieres=0.0, vis=40.0, cle="cle-reception-2")
    assert seconde.ok and seconde.metier["accepte"] is True, seconde.corps
    assert seconde.metier["evenement_reception_id"] != evenement_id, "deux livraisons, deux événements"
    _livrer_le_bus(moteur)
    deux_livraisons = _le_po(admin)
    assert deux_livraisons["receptions"] == 2
    assert deux_livraisons["attendu"] == {"avant_taxes": "320.00", "taxes": "47.92", "apres_taxes": "367.92"}
    rapprochement = deux_livraisons["rapprochement"]
    assert rapprochement["verdict"] == "ECART" and rapprochement["sens"] == "FACTURE_INFERIEURE_AU_RECU"
    assert rapprochement["facture_moins_recu"] == "-20.00" and "reste_a_recevoir" not in rapprochement
    assert deux_livraisons["a_payer_apres_taxes"] == "367.93", "344.93 facturé + 23.00 reçu non facturé, avec taxes"

    complete = _facture(moteur, admin, "F-1002", "20.00", cle="cle-facture-4", total="23.00")
    assert complete.metier["accepte"] is True, complete.corps
    final = _le_po(admin)
    assert final["rapprochement"]["verdict"] == "CONCORDANT" and final["a_payer_apres_taxes"] == "367.93"
    assert final["factures"] == {"nombre": 2, "avant_taxes": "320.00", "taxes": "47.93", "apres_taxes": "367.93"}

    # 7. AUCUN décaissement : le registre des mouvements et celui des factures clients n'ont jamais existé
    registres = _registres(moteur)
    assert "m05-financecore/principal" not in registres and "m05-financecore/factures" not in registres
    assert registres["m05-financecore/comptes_a_payer"] == 4  # deux réceptions, deux factures
    with stockage.transaction():
        maillons = list(stockage.maillons("m05-financecore", "comptes_a_payer"))
    assert {m["type_entree"] for m in maillons} == {"reception_recue", "facture_fournisseur_saisie"}
    assert "DECAISSEMENT" not in str(maillons)

    # rien de tout cela n'a été tronqué par Capacites (6 000 caractères)
    assert moteur.bilan()["troncatures"] == []


@SQLITE_SEULEMENT
def test_une_personne_desactivee_ne_saisit_rien_sa_demande_attend_l_approbation(moteur, equipe):
    """Le jeton d'appareil reste valide, mais la personne a été désactivée depuis l'appairage : le socle ne lui accorde
    aucun passe-droit (chemin normal, fail-closed). La saisie n'est PAS exécutée : elle attend une décision humaine
    dans la
    file, et aucune facture n'est rangée."""
    admin = equipe["admin"]
    _preparer_po(moteur)
    assert _livraison(moteur, admin, 60.0, 0.0, cle="cle-r1").metier["accepte"] is True
    _livrer_le_bus(moteur)
    avant = moteur.empreinte_etat()

    with stockage.transaction() as cnx:
        identite.activer(cnx, "nathan", False)
    reponse = _facture(moteur, admin, "F-1", "300.00", cle="cle-desactivee")

    assert reponse.ok and reponse.enveloppe["statut"] == "en_attente_approbation", reponse.corps
    apres = moteur.empreinte_etat()
    assert apres["registres"] == avant["registres"], "aucune facture n'est rangée"
    assert apres["approbations"] == avant["approbations"] + 1, "la demande attend un humain"
    with stockage.transaction() as cnx:
        (statut,) = cnx.execute(select(APPROBATIONS.c.statut).where(
            APPROBATIONS.c.id == reponse.enveloppe["demande_id"])).one()
    assert statut == "en_attente"


@SQLITE_SEULEMENT
def test_un_agent_ne_saisit_pas_seul_il_propose_et_le_proprietaire_decide(moteur, equipe):
    """L'agent (sans jeton d'appareil : secret partagé du moteur) ne saisit jamais une facture fournisseur seul :
    en mode `ombre`, sa demande attend la décision d'un humain ; en mode `supervise`, où un N3 s'exécute sans file,
    l'outil lui-même refuse. Approuvée par le propriétaire, la facture porte SON nom et la voie `approbation`."""
    admin = equipe["admin"]
    _preparer_po(moteur)
    assert _livraison(moteur, admin, 60.0, 0.0, cle="cle-r1").metier["accepte"] is True
    _livrer_le_bus(moteur)
    arguments = {"po_id": PO, "fournisseur_id": FOURNISSEUR, "numero_facture": "F-AGENT", "date_facture": "2026-09-14",
                 "montant_avant_taxes": "300.00", "total_facture": None, "horodatage": iso(moteur.horloge.maintenant)}
    avant = moteur.empreinte_etat()

    # mode `supervise` : rien ne passe par la file, l'outil refuse lui-même
    supervise = dict(moteur.departements)
    supervise["m05-financecore"] = dataclasses.replace(supervise["m05-financecore"], mode="supervise")
    reponse = Capacites(supervise, stockage.transaction).appeler("m5_saisir_facture_fournisseur", arguments)
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-AP-HUMAIN-REQUIS"
    assert moteur.empreinte_etat()["registres"] == avant["registres"]

    # mode `ombre` : la demande attend, rien n'est saisi
    capacites = Capacites(moteur.departements, stockage.transaction)
    demande = capacites.appeler("m5_saisir_facture_fournisseur", arguments)
    assert demande["statut"] == "en_attente_approbation"
    assert moteur.empreinte_etat()["registres"] == avant["registres"]

    # le propriétaire décide : la facture est saisie, à son nom, par la voie de l'approbation
    with stockage.transaction() as cnx:
        decision = approbations.decider(cnx, demande["demande_id"], True, "nathan",
                                        outils_executables(moteur.departements, stockage.transaction),
                                        moteur.departements)
    assert decision["statut"] == "executee", decision
    facture = _le_po(admin)["factures_saisies"][0]
    assert facture["numero_facture"] == "F-AGENT" and facture["saisi_par"] == "nathan"
    assert _le_po(admin)["rapprochement"]["verdict"] == "CONCORDANT"
    with stockage.transaction():
        (maillon,) = [m for m in stockage.maillons("m05-financecore", "comptes_a_payer")
                      if m["type_entree"] == "facture_fournisseur_saisie"]
    assert maillon["voie"] == "approbation"


# ========================================================================================== la pagination
@SQLITE_SEULEMENT
def test_quarante_po_se_lisent_par_pages_sans_troncature(moteur, equipe):
    admin = equipe["admin"]
    with stockage.transaction():
        for numero in range(1, 41):
            charge = {
                "evenement_id": f"evt-e2e-{numero:02d}", "po_id": f"PO-E2E-{numero:02d}", "fournisseur_id": FOURNISSEUR,
                "chantier_id": f"CH-E2E-{numero:02d}",
                "horodatage_reception": f"2026-09-{(numero - 1) % 14 + 1:02d}T09:00:00-04:00",
                "verdict_reception": "CONFORME", "statut_po": "received", "hash_maillon": f"{numero:064x}",
                "seuil_ecart_prix_pourcentage": None,
                "lignes": [{"materiau_id": GOUTTIERE, "quantite_demandee": "10", "quantite_recue": "10",
                            "prix_unitaire_prevu": "5.00", "devise_prevue": "CAD", "verdict_prix_po": "PRIX_LIVRE",
                            "prix_unitaire_reception": None, "verdict_prix_reception": "INDETERMINE",
                            "ecart_prix_critique": None}]}
            evenements.publier("m6.reception_enregistree", "m06-material-control", charge,
                               evenement_id=charge["evenement_id"])
    _livrer_le_bus(moteur)
    depuis = len(moteur.mesures)
    vus, depart, pages = [], 0, 0

    while depart is not None:
        reponse = admin.appeler("m5_lister_comptes_a_payer", {"depart": depart})
        assert reponse.ok and reponse.mesure.tronque is False and reponse.mesure.octets_texte <= LIMITE_TRONCATURE
        page = reponse.resultat
        assert page["total"] == 40 and page["totaux"]["nombre_po"] == 40 and page["totaux"]["complet"] is True
        assert page["totaux"]["a_payer_apres_taxes"] == "2299.60"  # 40 x 57.49
        vus.extend(c["po_id"] for c in page["comptes"])
        depart, pages = page["prochain_depart"], pages + 1
        assert pages <= 40, "la lecture doit progresser"

    assert pages > 1, "40 PO ne tiennent pas dans une seule page de 6 000 caractères"
    assert len(vus) == 40 and len(set(vus)) == 40
    assert moteur.bilan(depuis)["troncatures"] == []
    reste = json.dumps([m.octets_texte for m in moteur.mesures[depuis:]])
    assert max(m.octets_texte for m in moteur.mesures[depuis:]) <= LIMITE_TRONCATURE, reste
