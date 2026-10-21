"""PLAN T4.14 — « devis accepté -> M6 réserve -> stock insuffisant -> `a_commander` -> réception -> `pret` », par le
VRAI bus (`evenements.publier` puis `evenements.repartir`), les vrais départements M6 (`charger_departements`) et une
base SQLite migrée.

Le trajet :

    `m3.devis_accepte` (M3, simulé par `publier` : ce test prouve la mécanique M6 et le bus, pas la logique de M3)
      -> M6 garde le prévu ET réserve dans la même transaction : stock nul, donc `a_commander`
      -> `m6.materiel_pret` (révision 1) livré à un consommateur (le lecteur de M4, voir plus bas)
      -> l'admin demande un brouillon de PO (outil, jamais seul) : il commande ce qui MANQUE à la réservation
      -> approbation, courriel, envoi (gestes d'admin) ; réception PARTIELLE -> `partiel` (révision 2)
      -> réception qui COMPLÈTE le PO (livraisons cumulées, T4.15-b) -> `pret` (révision 3)

Le lecteur de M4 : `departments/m04-field-ops/` n'est pas de ce ressort (un autre agent modifie `preparation.py`). Un
consommateur de test, abonné à `m6.materiel_pret` par le vrai bus, tient lieu de M4 et fait ce que M4 devra faire :
retenir, par `devis_id`, la charge de plus grande `revision`. La charge est prouvée par son JSON Schema
(`erreurs_charge`, et `publier` la refuse si elle ne s'y conforme pas) et par sa livraison réelle.

Identifiants, quantités et fournisseurs fictifs (`fictif: true` au sens d'AGENTS.md).
"""

from __future__ import annotations

import dataclasses
import importlib
import sys
from pathlib import Path

import pytest
from sqlalchemy import select

from opsys import departements, evenements, stockage
from opsys.evenements.schemas import erreurs_charge
from opsys.outils import executer_atomique
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS

FICTIF = True
M6, LECTEUR = "m06-material-control", "m04-lecteur-test"
GOUTTIERE, VIS = "gouttiere-5po", "vis-inox"
DEVIS, CHANTIER, PO = "DEVIS-E2E-1", "CH-E2E-1", "PO-E2E-1"
FOURNISSEUR = "gentek"

_MODULE_LECTEUR = '''"""Consommateur de test : ce que M4 devra faire de m6.materiel_pret."""
LUES = []


def _retenir(charge):
    LUES.append(charge)
    return {"traite": True, "devis_id": charge["devis_id"], "revision": charge["revision"]}


def consommateurs():
    return {"m6.materiel_pret": _retenir}


def outils():
    return ()
'''


@pytest.fixture
def base(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-cascade-materiel.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    try:
        yield url
    finally:
        stockage.liberer()


@pytest.fixture
def lecteur(tmp_path, monkeypatch):
    """Le module du lecteur de M4 (fichier temporaire, importé par nom comme le fait le socle) ; ses charges lues."""
    (tmp_path / "m4_lecteur_test_materiel_pret.py").write_text(_MODULE_LECTEUR, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("m4_lecteur_test_materiel_pret", None)
    module = importlib.import_module("m4_lecteur_test_materiel_pret")
    module.LUES.clear()
    yield module
    sys.modules.pop("m4_lecteur_test_materiel_pret", None)


@pytest.fixture
def bus(base, lecteur):
    """M6 réel et le lecteur de M4, abonné à `m6.materiel_pret` : les seuls départements que `repartir` route ici."""
    reels = departements.charger_departements()
    faux_m4 = dataclasses.replace(
        reels["m04-field-ops"], id=LECTEUR, module_outils="m4_lecteur_test_materiel_pret",
        evenements_publie=(), evenements_consomme=("m6.materiel_pret",))
    return {M6: reels[M6], LECTEUR: faux_m4}


def _m6(bus):
    return {o.nom: o for o in bus[M6].charger_outils()}


def _repartir(bus, *, max_tours=8):
    total = {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    for _ in range(max_tours):
        resume = evenements.repartir(bus)
        for cle in total:
            total[cle] += resume[cle]
        if resume["livres"] == 0:
            assert total["echecs"] == 0 and total["quarantaines"] == 0, total
            return total
    raise AssertionError(f"le bus n'a pas atteint la quiescence : {total}")


def _admin(outil, arguments):
    reponse = executer_atomique(outil, arguments)
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]


def _devis_accepte():
    charge = {
        "devis_id": DEVIS, "lead_id": "lead-fictif", "chantier_id": CHANTIER,
        "lignes": [{"reference_ligne": f"{DEVIS}-L{i}", "description": "ligne fictive", "quantite": quantite,
                    "unite": unite, "prix_unitaire": "10.00", "prix_ligne": "10.00",
                    "reference_besoin_materiau": materiau}
                   for i, (materiau, quantite, unite) in enumerate([(GOUTTIERE, "100", "pi"), (VIS, "20", "boite")])],
        "cout_total": "100.00", "prix_total": "135.00", "taux_marge": "0.35",
        "horodatage_acceptation": "2026-09-30T10:00:00-04:00"}
    evenements.publier("m3.devis_accepte", "m03-estimation", charge, evenement_id=f"m3-devis-accepte-{DEVIS}")


def _maillons(nom):
    with stockage.transaction():
        return list(stockage.maillons(M6, nom))


def _livraison(m6, gouttieres, vis, horodatage):
    return executer_atomique(m6["m6_receptionner_commande"], {
        "bon_demande": {"po_id": PO, "chantier_id": CHANTIER, "horodatage": "2026-10-01T08:00:00-04:00",
                        "lignes_demandees": [{"materiau_id": GOUTTIERE, "quantite_demandee": 100.0},
                                             {"materiau_id": VIS, "quantite_demandee": 20.0}]},
        "reception_po": {"po_id": PO, "chantier_id": CHANTIER, "horodatage": horodatage,
                         "lignes_recues": [{"materiau_id": GOUTTIERE, "quantite_recue": gouttieres},
                                           {"materiau_id": VIS, "quantite_recue": vis}]},
        "catalogue_materiaux": {"version": "v1-fictif", "unite_monetaire": "CAD", "postes": {
            GOUTTIERE: {"cout_unitaire": 8.5, "libelle": "Gouttière 5 po"},
            VIS: {"cout_unitaire": 0.35, "libelle": "Vis inox"}}}})["resultat"]


def _derniere_revision(lues, devis_id=DEVIS):
    """Ce que M4 lit : la charge de plus grande révision du devis."""
    return max((c for c in lues if c["devis_id"] == devis_id), key=lambda c: c["revision"])


def _invariants(m6):
    """Le stock n'est jamais négatif : réservé <= en main, disponible >= 0, aucun emplacement négatif."""
    lecture = executer_atomique(m6["m6_lire_disponibilite"], {"materiau_ids": [GOUTTIERE, VIS]})
    resultat = lecture["resultat"]["resultat"]
    for article in resultat["articles"]:
        assert float(article["reserve"]) <= float(article["en_main"]), article
        assert float(article["disponible"]) >= 0, article
        assert all(float(q) >= 0 for q in article["par_emplacement"].values()), article
    return {a["materiau_id"]: a for a in resultat["articles"]}


# ------------------------------------------------------------------------------------------- le trajet
def test_devis_accepte_stock_insuffisant_a_commander_puis_reception_partielle_puis_pret(bus, lecteur):
    m6 = _m6(bus)

    # 1. devis accepté, stock nul : M6 réserve (rien) et dit « à commander », sans créer de bon de commande
    _devis_accepte()
    _repartir(bus)
    (premiere,) = lecteur.LUES
    assert erreurs_charge("m6.materiel_pret", premiere) == []
    assert (premiere["statut"], premiere["revision"], premiere["declencheur"], premiere["reservation_active"]) == (
        "a_commander", 1, "devis_accepte", True)
    assert [(m["materiau_id"], m["quantite_manquante"]) for m in premiere["lignes_manquantes"]] == [
        (GOUTTIERE, "100"), (VIS, "20")]
    assert (premiere["devis_id"], premiere["chantier_id"]) == (DEVIS, CHANTIER)
    assert _maillons("bons_commande") == [], "aucun bon de commande n'est créé seul"
    assert _invariants(m6)[GOUTTIERE]["reserve"] == "0"

    # 2. l'admin décide de commander : le brouillon vient de ce qui MANQUE à la réservation
    _admin(m6["m6_enregistrer_fournisseur"], {"fournisseur_id": FOURNISSEUR, "nom": "Gentek (fictif)",
                                              "horodatage": "2026-10-01T07:00:00-04:00"})
    for materiau, prix in ((GOUTTIERE, 8.5), (VIS, 0.35)):
        _admin(m6["m6_enregistrer_prix"], {"materiau_id": materiau, "fournisseur_id": FOURNISSEUR,
                                           "prix_unitaire": prix, "devise": "CAD", "date_effet": "2026-01-01"})
    brouillon = _admin(m6["m6_creer_po_brouillon"], {
        "po_id": PO, "devis_id": DEVIS, "fournisseur_id": FOURNISSEUR, "horodatage": "2026-10-01T08:00:00-04:00"})
    assert brouillon["quantites_depuis"] == "reservation" and brouillon["po"]["statut"] == "draft"
    assert [(ligne["materiau_id"], ligne["quantite_demandee"]) for ligne in brouillon["po"]["lignes"]] == [
        (GOUTTIERE, 100.0), (VIS, 20.0)]
    for outil, arguments in (
        ("m6_approuver_po", {}), ("m6_generer_courriel_po", {"nom_entreprise": "Entreprise Fictive"}),
        ("m6_marquer_po_envoye", {}),
    ):
        assert _admin(m6[outil], {"po_id": PO, "horodatage": "2026-10-01T09:00:00-04:00", **arguments})["po"]

    # 3. réception PARTIELLE : les gouttières arrivent, les vis pas encore -> partiel
    partielle = _livraison(m6, 100.0, 0.0, "2026-10-05T09:00:00-04:00")
    assert partielle["accepte"] is True and partielle["po"]["statut"] == "partially_received"
    _repartir(bus)
    seconde = _derniere_revision(lecteur.LUES)
    assert (seconde["statut"], seconde["revision"], seconde["declencheur"]) == ("partiel", 2, "stock_recu")
    assert [m["materiau_id"] for m in seconde["lignes_manquantes"]] == [VIS]
    assert _invariants(m6)[GOUTTIERE]["reserve"] == "100"

    # 4. la livraison qui COMPLÈTE le PO : cumulé, le PO est reçu, et le matériel est PRÊT
    complete = _livraison(m6, 0.0, 20.0, "2026-10-12T09:00:00-04:00")
    assert complete["accepte"] is True and complete["po"]["statut"] == "received", "livraisons cumulées (T4.15-b)"
    _repartir(bus)
    prete = _derniere_revision(lecteur.LUES)
    assert erreurs_charge("m6.materiel_pret", prete) == []
    assert (prete["statut"], prete["revision"], prete["declencheur"], prete["lignes_manquantes"]) == (
        "pret", 3, "stock_recu", [])
    assert [c["statut"] for c in sorted(lecteur.LUES, key=lambda c: c["revision"])] == [
        "a_commander", "partiel", "pret"]
    assert _invariants(m6)[VIS]["reserve"] == "20"

    # le bus a livré chaque révision une fois, sans échec ni quarantaine
    with stockage.transaction() as cnx:
        recus = cnx.execute(select(EVENEMENTS_RECUS.c.evenement_id, EVENEMENTS_RECUS.c.statut).where(
            EVENEMENTS_RECUS.c.consommateur == LECTEUR)).all()
    assert sorted(recus) == [(f"m6-materiel-pret-{DEVIS}-{n}", "traite") for n in (1, 2, 3)]
    # et l'unique bon de commande est celui que l'admin a demandé
    assert [m["po_id"] for m in _maillons("bons_commande") if m["type_entree"] == "po_cree"] == [PO]


def test_rejouer_le_bus_ou_redelivrer_le_devis_ne_change_rien(bus, lecteur):
    _devis_accepte()
    _repartir(bus)
    avant = (list(lecteur.LUES), _maillons("reservations"), _maillons("besoins_prevus"))

    _devis_accepte()  # même evenement_id : no-op du bus
    _repartir(bus)

    assert (list(lecteur.LUES), _maillons("reservations"), _maillons("besoins_prevus")) == avant
    with stockage.transaction() as cnx:
        publies = cnx.execute(select(EVENEMENTS_SORTANTS.c.evenement_id).where(
            EVENEMENTS_SORTANTS.c.type_evenement == "m6.materiel_pret")).all()
    assert len(publies) == 1


def test_l_evenement_publie_est_conforme_a_son_schema_et_lisible_par_son_identifiant(bus, lecteur):
    _devis_accepte()
    _repartir(bus)

    with stockage.transaction():
        charge = evenements.charge_publiee("m6.materiel_pret", f"m6-materiel-pret-{DEVIS}-1")
        introuvable = evenements.charge_publiee("m6.materiel_pret", f"m6-materiel-pret-{DEVIS}-2")

    assert charge is not None and erreurs_charge("m6.materiel_pret", charge) == []
    assert charge == lecteur.LUES[0] and introuvable is None
    with stockage.transaction() as cnx:
        ligne = cnx.execute(select(EVENEMENTS_SORTANTS.c.producteur).where(
            EVENEMENTS_SORTANTS.c.type_evenement == "m6.materiel_pret")).one()
    assert ligne[0] == M6


def test_une_charge_qui_sort_du_schema_est_refusee_par_le_bus(base):
    """Le schéma est fermé : une clé de plus, un statut inconnu ou une propriété manquante n'entrent pas au bus."""
    charge = {
        "evenement_id": "m6-materiel-pret-D-1", "devis_id": "D", "chantier_id": None, "revision": 1,
        "statut": "pret", "reservation_active": True, "declencheur": "devis_accepte", "horodatage": "h",
        "lignes": [{"materiau_id": "m", "unite": None, "quantite_besoin": "1", "quantite_reservee": "1",
                    "quantite_manquante": "0"}],
        "lignes_manquantes": []}
    assert erreurs_charge("m6.materiel_pret", charge) == []
    invalides = [
        {**charge, "prix": "1.00"},
        {**charge, "statut": "presque_pret"},
        {**charge, "declencheur": "au-hasard"},
        {**charge, "revision": 0},
        {key: value for key, value in charge.items() if key != "lignes_manquantes"},
        {**charge, "lignes": [{**charge["lignes"][0], "quantite_reservee": "-1"}]},
        {**charge, "lignes": [{**charge["lignes"][0], "quantite_reservee": 1}]},
        {**charge, "lignes": []},
    ]
    for invalide in invalides:
        assert erreurs_charge("m6.materiel_pret", invalide) != [], invalide
        with pytest.raises(evenements.ChargeInvalide), stockage.transaction():
            evenements.publier("m6.materiel_pret", M6, invalide, evenement_id="x")


def test_le_disponible_ne_devient_jamais_negatif_sur_tout_le_trajet(bus, lecteur):
    """Deux devis pour le même stock, une réception, une libération : à chaque étape, réservé <= en main."""
    m6 = _m6(bus)
    _devis_accepte()
    evenements.publier("m3.devis_accepte", "m03-estimation", {
        "devis_id": "DEVIS-E2E-2", "lead_id": "lead-fictif-2", "chantier_id": "CH-E2E-2",
        "lignes": [{"reference_ligne": "DEVIS-E2E-2-L0", "description": "ligne fictive", "quantite": "80",
                    "unite": "pi", "prix_unitaire": "10.00", "prix_ligne": "10.00",
                    "reference_besoin_materiau": GOUTTIERE}],
        "cout_total": "50.00", "prix_total": "70.00", "taux_marge": "0.35",
        "horodatage_acceptation": "2026-09-30T11:00:00-04:00"}, evenement_id="m3-devis-accepte-DEVIS-E2E-2")
    _repartir(bus)
    _invariants(m6)

    executer_atomique(m6["m6_receptionner_commande"], {
        "bon_demande": {"po_id": "PO-DEPOT", "chantier_id": "CH-DEPOT", "horodatage": "2026-10-01T00:00:00Z",
                        "lignes_demandees": [{"materiau_id": GOUTTIERE, "quantite_demandee": 120.0}]},
        "reception_po": {"po_id": "PO-DEPOT", "chantier_id": "CH-DEPOT", "horodatage": "2026-10-02T00:00:00Z",
                         "lignes_recues": [{"materiau_id": GOUTTIERE, "quantite_recue": 120.0}]},
        "catalogue_materiaux": {"version": "v1-fictif", "unite_monetaire": "CAD",
                                "postes": {GOUTTIERE: {"cout_unitaire": 8.5, "libelle": "g"}}}})
    _repartir(bus)
    chiffres = _invariants(m6)
    assert (chiffres[GOUTTIERE]["en_main"], chiffres[GOUTTIERE]["reserve"], chiffres[GOUTTIERE]["disponible"]) == (
        "120", "120", "0")
    # le devis le plus ancien passe d'abord : 100 sur 100 ; le second n'en a que 20 sur 80
    assert _derniere_revision(lecteur.LUES, DEVIS)["lignes"][0]["quantite_reservee"] == "100"
    second = _derniere_revision(lecteur.LUES, "DEVIS-E2E-2")
    assert (second["statut"], second["lignes"][0]["quantite_reservee"]) == ("partiel", "20")

    _admin(m6["m6_liberer_reservation"], {"devis_id": DEVIS, "motif": "client parti chez un concurrent",
                                          "horodatage": "2026-10-03T09:00:00-04:00"})
    _repartir(bus)
    _invariants(m6)
    assert _derniere_revision(lecteur.LUES, DEVIS)["statut"] == "a_commander"
    assert _derniere_revision(lecteur.LUES, DEVIS)["reservation_active"] is False
    second = _derniere_revision(lecteur.LUES, "DEVIS-E2E-2")
    assert (second["statut"], second["lignes"][0]["quantite_reservee"]) == ("pret", "80")


def test_le_module_du_lecteur_n_importe_aucun_departement(lecteur):
    """M4 lira `m6.materiel_pret` par le bus, sans importer M6 : le lecteur de test n'importe que la bibliothèque
    standard, comme un consommateur de M4 le fera."""
    source = Path(lecteur.__file__).read_text(encoding="utf-8")
    assert "m6_material_control" not in source and "import opsys" not in source
