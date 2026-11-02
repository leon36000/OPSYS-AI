"""M6 de bout en bout (C1 + C2 + C3), VRAIS outils, vrai bus, vrai sas d'approbation, vrai M1 (courriel), M2, M3, M4,
M5 :

estimation M3 -> besoins M6 -> devis accepté (réservation « à commander ») -> PO MULTI-FOURNISSEURS commandables (perte
déclarée appliquée, unités, date requise, mode) -> courriel complet de M1 en BROUILLON -> envoi approuvé UNE fois (sas)
->
M6 prend acte (pas de seconde approbation) -> confirmation d'un fournisseur -> réceptions (une partielle, puis complète)
-> fin de chantier M4 -> déclaration des matériaux avec un article inédit, un achat sur place et une sortie du dépôt
(coût
DIT, jamais un refus) -> variance critique (+40 %) -> attente de l'admin avec le MESSAGE IMPOSÉ -> coût réel chez M5,
sans
prix inventé pour l'article sans prix.

Seuls le RÉSEAU et les serveurs de courrier sont des doubles (`lea_rosalie_qa`) ; personnes, fournisseurs, courriels et
montants sont fictifs. Niveau de preuve : SQLite, processus unique, client HTTP/Gmail simulés ; ni core, ni téléphone,
ni
fournisseur réel.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import cablage_qa as cq
import lea_rosalie_qa as lr
import m2_revenue_crm.outils as m2_outils
import m5_financecore.outils as m5_outils
import pytest
from m2_preparation_estimation import marqueur_m2
from sqlalchemy import select

from opsys import stockage
from opsys.courriel_connecteurs import envoi
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS

FICTIF = True
DT_TZ = dt.timezone(dt.timedelta(hours=-4))
BASE = dt.datetime(2026, 9, 15, 7, 0, 0, tzinfo=DT_TZ)
M1, M2, M3, M4, M5, M6 = ("m01-front-office", "m02-revenue-crm", "m03-estimation", "m04-field-ops",
                          "m05-financecore", "m06-material-control")
DEPARTEMENTS = (M1, M2, M3, M4, M5, M6)
LEAD, CHANTIER, VILLE = "LEAD-SA-fictif", "CH-SA-fictif", "Repentigny"
REV, SOF, VIS = "REV-ALU-SA-FICTIF", "SOFFITE-SA-FICTIVE", "VIS-INOX-SA-FICTIVE"
INEDIT, DEPOT_ART, MOULURE = "SCELLANT-INEDIT-SA-FICTIF", "COIN-EXT-DEPOT-SA-FICTIF", "MOULURE-SA-FICTIVE"
GENTEK, KAYCAN = "gentek-fictif", "kaycan-fictif"
COURRIEL_GENTEK = "commandes@gentek.exemple-fictif.test"
COURRIEL_KAYCAN = "commandes@kaycan.exemple-fictif.test"
# Le tri de M1 ne reconnaît une référence de bon de commande que sous la forme « PO-<chiffre>… » (tri_extraction._PO).
PO_GENTEK, PO_KAYCAN = "PO-2026-101", "PO-2026-102"
MESSAGE_IMPOSE = (
    "Écart matériaux critique — validation admin requise. Causes possibles : erreur d'estimation, changement terrain, "
    "perte, bris, mauvaise saisie, retour non déclaré ou usage non expliqué."
)
BAREME = {
    "version": "2026.1-fictif", "unite": "pi",
    "postes": {"renovation_totale": {
        "cout_unitaire_min": 800.0, "cout_unitaire_max": 1400.0,
        "materiaux": [
            {"materiau": "Revêtement aluminium (fictif)", "sku": REV, "quantite_par_unite": "1", "unite": "feuille",
             "facteur_perte": "0.08"},
            {"materiau": "Soffite (fictif)", "sku": SOF, "quantite_par_unite": "0.5", "unite": "piece",
             "facteur_perte": "0.10"},
            {"materiau": "Vis inox (fictif)", "sku": VIS, "quantite_par_unite": "0.25", "unite": "boite"},
        ],
    }},
}


def _iso(offset_s: int = 0) -> str:
    return (BASE + dt.timedelta(seconds=offset_s)).isoformat()


@pytest.fixture
def w(tmp_path, monkeypatch):
    monde = lr.monter(tmp_path, monkeypatch, departements=DEPARTEMENTS)
    m2_outils.utiliser_stockage_durable()
    m5_outils.utiliser_stockage_durable()
    yield monde
    m2_outils.reinitialiser_registre()
    cq.demonter()


def _outils(w, dep):
    return {o.nom: o for o in w.capacites.departements[dep].charger_outils()}


def _ok(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]


def _drainer(w, passes=6):
    for _ in range(passes):
        if w.repartir(passes=1)["livres"] == 0:
            return
    raise AssertionError("le bus n'a pas atteint la quiescence")


def _registre(w, dep, nom):
    return w.registre(dep, nom)


def _po(w, po_id):
    from m6_material_control import bons_commande

    return bons_commande.lire(_registre(w, M6, "bons_commande"), po_id)


def _publies(type_evenement):
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS.c.charge).where(
            EVENEMENTS_SORTANTS.c.type_evenement == type_evenement).order_by(EVENEMENTS_SORTANTS.c.cree_le)).all()
    return [codec.decoder(ligne.charge) for ligne in lignes]


def _brouillons(w):
    return [m for m in _registre(w, M1,
                                 "commandes_fournisseur") if m["type_entree"] == "commande_fournisseur_brouillon"]


def _approuver_en_sas(w, nom, **arguments):
    """Un outil N3 : l'agent propose, une personne approuve au sas, l'outil s'exécute à ce moment-là."""
    demande = w.appeler(nom, **arguments)
    assert demande.get("statut") == "en_attente_approbation", demande
    decision = w.decider(demande["demande_id"])
    assert decision["statut"] == "executee", decision
    return decision["reponse"]["resultat"]


def _chaine_t12e():
    """Les étapes M2/M4 de la cascade « travaux terminés » (T1.2-e), réutilisées telles quelles (pas de copie)."""
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "cascade_t12e_pour_m6", Path(__file__).with_name("test_cascade_travaux_termines.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _recevoir_po(w, po_id, quantites, quand, prix=None):
    """Réception d'un PO persisté (N3 : une personne approuve) ; `prix` : prix lus du bon de livraison, par article."""
    from m6_material_control import bons_commande

    po = _po(w, po_id)
    bon = bons_commande.construire_bon_demande(po)
    arguments = {
        "bon_demande": bon,
        "reception_po": {"po_id": po_id, "chantier_id": po["chantier_id"], "horodatage": quand,
                         "lignes_recues": [{"materiau_id": m, "quantite_recue": q} for m, q in quantites.items()]},
        "catalogue_materiaux": {"version": "v1-fictif", "unite_monetaire": "CAD", "postes": {
            ligne["materiau_id"]: {"cout_unitaire": (prix or {}).get(ligne["materiau_id"],
                                                                     ligne["prix_unitaire_prevu"]),
                                   "libelle": ligne["materiau_id"]} for ligne in po["lignes"]}},
    }
    return _approuver_en_sas(w, "m6_receptionner_commande", **arguments)


def _derniere_rentabilite_m5(devis_id):
    traces = [m for m in stockage.maillons("m05-financecore", "rentabilite")
              if m.get("devis_id") == devis_id or m.get("rentabilite", {}).get("devis_id") == devis_id]
    assert traces, "M5 n'a tracé aucun coût réel pour ce devis"
    return traces[-1]["rentabilite"] if "rentabilite" in traces[-1] else traces[-1]


# ------------------------------------------------------------------------------------------ le décor amont
def _estimer_et_accepter_le_devis(w):
    m2, m3 = _outils(w, M2), _outils(w, M3)
    contrat = {"lead_id": LEAD, "conversation_id": f"conv-{LEAD}", "type_travaux": "renovation_totale", "ville": VILLE,
               "canal": "telephone", "contact": {"nom": "Client Fictif", "telephone": "418-555-0100"},
               "urgence_declaree": False}
    marqueur = marqueur_m2(LEAD, type_travaux="renovation_totale", ville=VILLE, contrat=contrat)
    estimation = _ok(executer_atomique(m3["m3_estimer_projet"], {
        "contrat": contrat, "marqueur": marqueur,
        "photos": [{"photo_id": "p1", "resolution_largeur": 3000, "resolution_hauteur": 2000, "eclairage": 7,
                    "angle": "face", "reference_echelle": {"type": "porte", "dimensions_connues": True}}],
        "seuils": {"resolution_minimale": 1000, "eclairage_minimal": 4}, "bareme": BAREME, "quantite": 40,
        "plancher_rentable": 1000}))
    besoins = estimation["besoins_materiaux"]
    devis_id = besoins["devis_id"]
    _drainer(w)  # M6 range le prévu PROVISOIRE de l'estimation (perte déclarée par le barème de M3)
    _ok(executer_atomique(m3["m3_creer_devis"], {
        "devis_id": devis_id, "lead_id": LEAD, "chantier_id": CHANTIER, "taux_marge": "0.25",
        "horodatage": _iso(200), "prix_total": "2118.80",
        "lignes": [
            {"description": "Revêtement aluminium (fictif)", "quantite": "40", "unite": "feuille",
             "cout_unitaire": "30.00", "reference_besoin_materiau": REV},
            {"description": "Soffite (fictif)", "quantite": "20", "unite": "piece", "cout_unitaire": "12.00",
             "reference_besoin_materiau": SOF},
            {"description": "Vis inox (fictif)", "quantite": "10", "unite": "boite", "cout_unitaire": "9.50",
             "reference_besoin_materiau": VIS},
            {"description": "Main d'oeuvre (fictif)", "quantite": "1", "unite": "forfait", "cout_unitaire": "160.00",
             "reference_besoin_materiau": None}]}))
    for statut, decalage, extra in (("converti", 300, {"reference_devis_m3": devis_id}),):
        _ok(executer_atomique(m2["m2_transitionner_statut"], {
            "lead_id": LEAD, "statut_cible": statut, "horodatage": _iso(decalage), **extra}))
    _ok(executer_atomique(m3["m3_marquer_devis_accepte"], {
        "devis_id": devis_id, "approbateur": "Nathan Proprietaire (fictif, T3)", "horodatage": _iso(600)}))
    _ok(executer_atomique(m2["m2_transitionner_statut"], {
        "lead_id": LEAD, "statut_cible": "cedule", "horodatage": _iso(660)}))
    _drainer(w)
    return devis_id, contrat, marqueur, besoins


def _declarer_fournisseurs_et_prix(w):
    m6 = _outils(w, M6)
    for fournisseur, nom, courriel in ((GENTEK, "Gentek (fictif)", COURRIEL_GENTEK),
                                       (KAYCAN, "Kaycan (fictif)", COURRIEL_KAYCAN)):
        _ok(executer_atomique(m6["m6_enregistrer_fournisseur"], {
            "fournisseur_id": fournisseur, "nom": nom, "horodatage": _iso(), "courriel_commande": courriel}))
    for materiau, fournisseur, prix, unite, source in (
        (REV, GENTEK, 30.0, "feuille", "grille-gentek-fictive.pdf"), (SOF, GENTEK, 12.0, "piece", None),
        (VIS, KAYCAN, 9.5, "boite", "grille-kaycan-fictive.pdf"),
        (MOULURE, GENTEK, 4.25, "piece", "grille-gentek-fictive.pdf"),  # article du livre, jamais reçu
    ):
        arguments = {"materiau_id": materiau, "fournisseur_id": fournisseur, "prix_unitaire": prix, "devise": "CAD",
                     "date_effet": "2026-09-01", "unite": unite}
        if source:
            arguments["source_document"] = source
        _ok(executer_atomique(m6["m6_enregistrer_prix"], arguments))


# ============================================================================================ le scénario
def test_de_l_estimation_au_cout_reel_avec_po_multi_fournisseurs_et_sortie_au_niveau_de_l_article(w):
    from m6_material_control import outils as m6_outils

    devis_id, contrat, marqueur, besoins = _estimer_et_accepter_le_devis(w)

    # -- 1. M3 -> M6 : le prévu provisoire porte les pertes DÉCLARÉES ; le devis accepté réserve et dit « à commander »
    # ---
    (provisoire,) = [m for m in _registre(w, M6, "besoins_prevus") if m.get("source") == "estimation_m3"]
    assert {d["materiau_id"]: d.get("facteur_perte") for d in provisoire["detail_lignes"]} == {
        REV: "0.08", SOF: "0.10", VIS: None}
    assert provisoire["facteurs_perte_absents"] == ["Vis inox (fictif)"], "la perte inconnue est signalée"
    assert _publies("m6.materiel_pret")[-1]["statut"] == "a_commander"

    # -- 2. fournisseurs et prix déclarés (aucune donnée réelle) ----------------------------------------------------
    _declarer_fournisseurs_et_prix(w)

    # -- 3. UN besoin, DEUX fournisseurs : deux PO commandables, tâche interne (N2, aucune approbation) ---------------
    creation = w.appeler("m6_creer_pos_depuis_besoin", devis_id=devis_id, horodatage=_iso(1000),
                         date_requise="2026-09-25", mode_livraison="livraison_chantier",
                         lieu_livraison="Chantier fictif, 12 rue des Érables", ville=VILLE,
                         repartition=[{"po_id": PO_GENTEK, "fournisseur_id": GENTEK, "materiau_ids": [REV, SOF]},
                                      {"po_id": PO_KAYCAN, "fournisseur_id": KAYCAN, "materiau_ids": [VIS]}])
    assert creation["ok"] is True and "demande_id" not in creation and creation["resultat"]["accepte"] is True, creation
    gentek, kaycan = _po(w, PO_GENTEK), _po(w, PO_KAYCAN)
    par = {ligne["materiau_id"]: ligne for ligne in gentek["lignes"] + kaycan["lignes"]}
    assert (par[REV]["quantite_nette"], par[REV]["quantite_demandee"], par[REV]["unite"]) == (40.0, 43.2, "feuille")
    assert (par[SOF]["quantite_nette"], par[SOF]["quantite_demandee"]) == (20.0, 22.0)
    assert (par[VIS]["facteur_perte"], par[VIS]["quantite_demandee"]) == (None,
                                                                          10.0), "perte non déclarée : non inventée"
    assert gentek["fournisseur_id"] == GENTEK and kaycan["fournisseur_id"] == KAYCAN
    assert gentek["montant_total_prevu"] == 1560.0 and kaycan["montant_total_prevu"] == 95.0

    # -- 4. approbation du PO (N3, une personne) puis courriel (N2) -> M1 prépare un BROUILLON par fournisseur
    # ----------
    for po_id in (PO_GENTEK, PO_KAYCAN):
        assert _approuver_en_sas(w, "m6_approuver_po", po_id=po_id, horodatage=_iso(1100))["accepte"] is True
        courriel = w.appeler("m6_generer_courriel_po", po_id=po_id, horodatage=_iso(1200),
                             nom_entreprise="Atelier Fictif inc.")
        assert courriel["ok"] is True and "demande_id" not in courriel, courriel
    _drainer(w)
    brouillons = {b["po_id"]: b for b in _brouillons(w)}
    assert set(brouillons) == {PO_GENTEK, PO_KAYCAN} and w.c.monde.gmail.envoyes == []
    with stockage.transaction() as cnx:
        contenu = envoi.lire_brouillon(cnx, brouillons[PO_GENTEK]["brouillon_id"]).contenu
    assert contenu.a == (COURRIEL_GENTEK,)
    assert contenu.objet == f"Commande matériaux — {PO_GENTEK} — {VILLE}"
    for attendu in ("43.2 feuille", "40 feuille nets + perte déclarée de 8 %", "22 piece", "Date requise : 2026-09-25",
                    "Livraison au chantier : Chantier fictif, 12 rue des Érables", PO_GENTEK):
        assert attendu in contenu.corps, attendu
    assert "$" not in contenu.corps and "30.0" not in contenu.corps, "aucun prix dans le courriel"

    # -- 5. UNE approbation d'envoi (sas de M1) ; M6 prend acte, sans seconde approbation (N4)
    # --------------------------
    for po_id in (PO_GENTEK, PO_KAYCAN):
        demande = w.appeler("m1_demander_envoi_courriel", brouillon_id=brouillons[po_id]["brouillon_id"],
                            contexte=f"Commande {po_id}")["resultat"]["resultat"]["demande_id"]
        assert w.decider(demande)["statut"] == "executee"
    w.c.activer("courriel.envoi")
    w.c.tour()
    assert len(w.c.monde.gmail.envoyes) == 2
    _drainer(w)
    assert _po(w, PO_GENTEK)["statut"] == "sent_to_supplier" == _po(w, PO_KAYCAN)["statut"]
    with stockage.transaction():
        assert not [a for a in m6_outils.attentes() if a["type"] == "po_envoye_a_marquer"]

    page = w.appeler("m6_lister_po", aujourd_hui="2026-09-20")["resultat"]["resultat"]
    assert page["comptes"] == {"sent_to_supplier": 2} and page["total"] == 2
    assert {p["po_id"]: (p["commandable"], p["en_retard"]) for p in page["pos"]} == {
        PO_GENTEK: (True, False), PO_KAYCAN: (True, False)}

    # -- 6. un fournisseur CONFIRME par courriel authentifié, depuis sa boîte de commande déclarée
    # ----------------------
    w.recevoir(f"Confirmation {PO_KAYCAN}",
               f"Confirmation de commande {PO_KAYCAN}. Nous avons bien reçu votre commande. "
               "Livraison prévue le 22 septembre 2026.", de=COURRIEL_KAYCAN, nom="Kaycan")
    _drainer(w)
    confs = [m for m in _registre(w, M6, "commandes_courriel") if m.get("type_entree") == "confirmation_fournisseur"]
    assert _po(w, PO_KAYCAN)["statut"] == "supplier_confirmed" and _po(w,
                                                                       PO_GENTEK)["statut"] == "sent_to_supplier", confs

    # -- 7. réceptions : Gentek en deux livraisons (partielle puis complète), Kaycan d'un coup, plus un article au
    # dépôt --
    _recevoir_po(w, PO_GENTEK, {REV: 30.0, SOF: 22.0}, _iso(3000), prix={SOF: 15.0})
    assert _po(w, PO_GENTEK)["statut"] == "partially_received"
    _recevoir_po(w, PO_GENTEK, {REV: 13.2, SOF: 0.0}, _iso(3100))
    assert _po(w, PO_GENTEK)["statut"] == "received"
    _recevoir_po(w, PO_KAYCAN, {VIS: 10.0}, _iso(3200))
    assert _po(w, PO_KAYCAN)["statut"] == "received"
    detail = w.appeler("m6_lire_po", po_id=PO_GENTEK)["resultat"]["resultat"]
    assert [h["statut"] for h in detail["historique"]] == [
        "approved", "email_ready", "sent_to_supplier", "partially_received", "received"]
    assert detail["historique"][2]["envoi_constate"]["source"] == "m1.commande_courriel_envoyee"
    assert {c["materiau_id"]: c["quantite_recue_cumulee"] for c in detail["reception_cumulee"]["lignes"]} == {
        REV: "43.2", SOF: "22.0"}
    # une livraison, un événement vers M5 : 2 (Gentek) + 1 (Kaycan)
    assert len(_publies("m6.reception_enregistree")) == 3
    _ok(executer_atomique(_outils(w, M6)["m6_receptionner_commande"], {
        "bon_demande": {"po_id": "PO-DEPOT-SA", "chantier_id": "DEPOT-SA-FICTIF",
                        "lignes_demandees": [{"materiau_id": DEPOT_ART, "quantite_demandee": 10.0}],
                        "horodatage": _iso(3300)},
        "reception_po": {"po_id": "PO-DEPOT-SA", "chantier_id": "DEPOT-SA-FICTIF",
                         "lignes_recues": [{"materiau_id": DEPOT_ART,
                                            "quantite_recue": 10.0}], "horodatage": _iso(3400)},
        "catalogue_materiaux": {"version": "v1-fictif", "unite_monetaire": "CAD",
                                "postes": {DEPOT_ART: {"cout_unitaire": 6.5, "libelle": "Coin extérieur (fictif)"}}}}))

    # -- 8. fin de chantier : M4 planifie, pointe, complète ; M6 déclare, AVEC un inédit, un achat sur place, le dépôt
    # ----
    t = _chaine_t12e()
    intervention_id = t._m4_planifier_router_pointer(_outils(w, M4), contrat, marqueur, devis_id, BASE)
    _ok(executer_atomique(_outils(w, M2)["m2_transitionner_statut"], {
        "lead_id": LEAD, "statut_cible": "chantier", "horodatage": _iso(840)}))
    wct_id = t._m4_completer(_outils(w, M4), intervention_id, BASE)["wct_id"]
    lignes = [
        {"type_ligne": "prevu", "materiau_id": REV, "quantite": 56.0, "unite": "feuille", "quantite_estimee": 40.0},
        {"type_ligne": "prevu", "materiau_id": SOF, "quantite": 20.0, "unite": "piece", "quantite_estimee": 20.0},
        {"type_ligne": "prevu", "materiau_id": VIS, "quantite": 10.0, "unite": "boite", "quantite_estimee": 10.0},
        {"type_ligne": "achat_terrain", "materiau_id": INEDIT, "quantite": 3.0, "unite": "tube",
         "photo_fournie": True, "recu_fourni": False},
        {"type_ligne": "non_prevu", "materiau_id": DEPOT_ART, "quantite": 2.0, "unite": "piece"},
        {"type_ligne": "non_prevu", "materiau_id": MOULURE, "quantite": 5.0, "unite": "piece"},
    ]
    declaration = _ok(executer_atomique(_outils(w, M6)["m6_declarer_materiaux_utilises"], {
        "wct_id": wct_id, "formulaire": {
            "wct_id": wct_id, "intervention_id": intervention_id, "chantier_id": CHANTIER, "lignes_materiaux":
            lignes}}))
    assert "REJ-COUT-UNITAIRE-INTROUVABLE" not in str(declaration)
    _drainer(w)
    couts = {m["materiau_id"]: (m["cout_unitaire"], m["origine_cout"]) for m in _registre(w, M6, "principal")
             if m.get("wct_id") == wct_id}
    assert couts[REV][0] == 30.0 and couts[REV][1]["source"] == "RECEPTION_CHANTIER"
    assert couts[SOF][0] == 15.0, "le prix de la dernière livraison, pas celui du livre"
    assert couts[DEPOT_ART] == (6.5, {"source": "RECEPTION_ARTICLE", "marquage": None,
                                     "reference": couts[DEPOT_ART][1]["reference"]})
    assert couts[MOULURE][0] == 4.25 and couts[MOULURE][1]["source"] == "LIVRE_PRIX"
    assert couts[MOULURE][1]["marquage"] == "SOURCE_DECLAREE"
    assert couts[INEDIT] == (None, {"source": "INCONNU", "motif": "AUCUN_PRIX", "marquage": None}), \
        "l'achat sur place inédit est accepté, son coût est dit inconnu"

    # -- 9. variance critique (+40 %) : M4 garde le chantier en revue ; l'admin a le MESSAGE IMPOSÉ
    # ----------------------
    variance = [v for v in _publies("m6.variance_chantier") if v["statut_variance"] == "evaluee"][-1]
    assert variance["signal_critique"] is True and variance["seuil_pourcentage"] == 0.3
    assert {ligne["materiau"]: ligne["critique"] for ligne in variance["lignes"] if ligne["materiau"] in (REV, SOF,
                                                                                                          VIS)} == {
        REV: True, SOF: False, VIS: False}
    statut = executer_atomique(_outils(w, M4)["m4_statut_intervention"], {"intervention_id": intervention_id})
    assert statut["resultat"]["statut"] == "completed_pending_review"
    with stockage.transaction():
        attentes = m6_outils.attentes()
    (critique,) = [a for a in attentes if a["type"] == "ecart_materiaux_critique"]
    assert critique["resume"].startswith(MESSAGE_IMPOSE) and REV in critique["resume"]
    assert "vol" not in critique["resume"].lower().replace("involontaire", "")
    (inconnu,) = [a for a in attentes if a["type"] == "cout_sortie_inconnu"]
    assert inconnu["id"] == f"cout_sortie_inconnu:{INEDIT}" and "m6_enregistrer_prix" in inconnu["action_proposee"]
    # Trois articles ont plus sorti que reçu : l'inédit, la moulure jamais reçue, et le revêtement (56 utilisés pour
    # 43,2 reçus). Aucun n'est une accusation : un stock à vérifier.
    assert sorted(a["id"] for a in attentes if a["type"] == "stock_negatif") == sorted(
        f"stock_negatif:{m}" for m in (INEDIT, MOULURE, REV))

    # -- 10. coût réel chez M5 : le livre de M6 valorise ce qui a un prix ; l'article sans prix est DIT, jamais inventé
    # ---
    rentabilite = _derniere_rentabilite_m5(devis_id)
    materiaux = rentabilite["cout_reel"]["materiaux"]
    par_materiau = {ligne["materiau"]: ligne for ligne in materiaux["lignes"]}
    assert materiaux["statut"] == "partiel", "un coût incomplet est dit partiel, jamais complété"
    assert materiaux["source_quantites"] == {"evenement": "m6.variance_chantier", "statut_variance": "evaluee",
                                            "signal_critique": True}, "les QUANTITÉS réelles viennent de M6"
    assert (par_materiau[REV]["quantite_reelle"], par_materiau[REV]["cout"]) == (Decimal("56.0"), Decimal("1680.00"))
    assert par_materiau[SOF]["cout"] == Decimal("240.00") and par_materiau[VIS]["cout"] == Decimal("95.00")
    assert par_materiau[MOULURE]["cout"] == Decimal("21.25")
    # L'article sans aucun prix reste « prix non disponible » chez M5 : aucun prix inventé entre M6 et M5.
    assert par_materiau[INEDIT]["statut"] == "PRIX_NON_DISPONIBLE" and par_materiau[INEDIT]["cout"] is None
    # Limite dite (C14) : M5 valorise au livre de prix, pas au coût de sortie rangé par M6 : l'article du dépôt (6,50 $
    # à la réception) n'a pas de tarif au livre, donc M5 le dit « non disponible » alors que M6 en connaît le coût.
    assert par_materiau[DEPOT_ART]["statut"] == "PRIX_NON_DISPONIBLE"
    assert materiaux["cout_connu"] == Decimal("2036.25")
