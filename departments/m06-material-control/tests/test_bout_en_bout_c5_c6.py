"""C5 puis C6 de bout en bout (BRIEF M6) : les VRAIS outils, registres et bus du dépôt.

PO persisté (SQLite réelle migrée, registres durables M6) → réception enrichie C5
(substitué nommé, endommagé avec photo CAS, lieu fermé `chantier`, prix BL +20 % au
seuil DÉCLARÉ 0.15 → signaux `BON_LIVRAISON`) → événement `m6.reception_enregistree`
publié dans la MÊME transaction → achat terrain C6 sous plafond (25.50 ≤ 150) tracé
au registre durable `achats_terrain` avec attente M5 `depense_terrain_a_saisir` SANS
paiement, puis achat au-delà du plafond (200 > 150) en attente admin N3 tracée AVANT
toute entrée au stock. Données fictives, horloges injectées (les horodatages sont des
arguments, M6 n'a pas d'horloge). NEUTRALITÉ : aucun message d'accusation, l'employé
ne voit aucun coût d'autrui, aucun paiement ni envoi n'est exécuté.
"""

from __future__ import annotations

import m6_material_control.outils as m6_outils
import pytest
from sqlalchemy import select

from opsys import stockage
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS

FICTIF = True
_DEPARTEMENT = "m06-material-control"
PO_ID = "PO-C5C6-FICT-1"
CHANTIER = "CH-C5C6-FICT-1"


@pytest.fixture
def base_durable_m6(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-c5c6.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    try:
        yield url
    finally:
        stockage.liberer()


RECU_CAS = "fichier:sha256:" + "ab" * 32
RECU_CAS_2 = "fichier:sha256:" + "cd" * 32
PHOTO_CAS = "fichier:sha256:" + "ef" * 32
HORODATAGE = "2026-10-06T14:30:00-04:00"


def _outil(nom):
    return next(o for o in m6_outils.outils() if o.nom == nom)


def _po_envoye():
    with stockage.transaction():
        for reponse in (
            m6_outils.enregistrer_fournisseur(
                "gentek", "Gentek", "2026-01-01T00:00:00Z",
                courriel_commande="commandes@gentek.exemple-fictif.test"),
            m6_outils.enregistrer_prix("gouttiere-5po", "gentek", 10.0, "CAD", "2026-01-01"),
            m6_outils.enregistrer_besoins_prevus(CHANTIER, "DEVIS-C5C6-FICT-1", [
                {"materiau_id": "gouttiere-5po", "quantite_estimee": 10.0, "unite": "pi"}]),
            m6_outils.creer_po_brouillon(PO_ID, "DEVIS-C5C6-FICT-1", "gentek",
                                         "2026-09-01T08:00:00-04:00", "2099-12-31", "ramassage"),
            m6_outils.approuver_po(PO_ID, "2026-09-01T09:00:00-04:00"),
            m6_outils.generer_courriel_po(PO_ID, "2026-09-01T10:00:00-04:00", "Entreprise Fictive"),
            m6_outils.marquer_po_envoye(PO_ID, "2026-09-01T11:00:00-04:00"),
        ):
            assert reponse["accepte"] is True, reponse


def _publies():
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS).where(
            EVENEMENTS_SORTANTS.c.type_evenement == "m6.reception_enregistree")).mappings().all()
    return [(ligne["evenement_id"], codec.decoder(ligne["charge"])) for ligne in lignes]


def test_c5_puis_c6_bout_en_bout_registres_bus_reels(base_durable_m6):
    _po_envoye()
    reception = executer_atomique(_outil("m6_receptionner_commande"), {
        "bon_demande": {
            "po_id": PO_ID, "chantier_id": CHANTIER,
            "lignes_demandees": [{"materiau_id": "gouttiere-5po", "quantite_demandee": 10.0}],
            "horodatage": "2026-09-01T08:00:00-04:00"},
        "reception_po": {
            "po_id": PO_ID, "chantier_id": CHANTIER,
            "lignes_recues": [{"materiau_id": "gouttiere-5po", "quantite_recue": 8.0}],
            "horodatage": HORODATAGE},
        "catalogue_materiaux": {
            "version": "v1-fictif", "unite_monetaire": "CAD",
            "postes": {"gouttiere-5po": {"cout_unitaire": 10.0, "libelle": "Gouttière 5po (fictif)"}}},
        "details_reception": [
            {"materiau_id": "gouttiere-5po", "statut_ligne": "endommage", "photos": [PHOTO_CAS]}],
        "lieu_livraison": {"type": "chantier", "reference": CHANTIER},
        "prix_bl": {"gouttiere-5po": 12.0},
    })
    assert reception["ok"] and reception["resultat"]["accepte"], reception
    resultat = reception["resultat"]
    assert resultat["details_lignes"][0]["statut_ligne"] == "endommage"
    assert resultat["details_lignes"][0]["photos"] == [PHOTO_CAS]
    assert resultat["lieu_livraison"]["type"] == "chantier"
    signaux = resultat["signaux_prix_bl"]
    assert len(signaux) == 1 and signaux[0]["source_prix"] == "BON_LIVRAISON"
    assert signaux[0]["ecart_pourcentage"] >= 0.15
    publies = _publies()
    assert len(publies) == 1
    _, charge = publies[0]
    assert charge["po_id"] == PO_ID and charge["verdict_reception"] == "RECEPTION_INFERIEURE"

    sous_plafond = executer_atomique(_outil("m6_declarer_achat_terrain"), {"achat": {
        "materiau_id": "scellant-fictif", "quantite": 3.0, "montant": "25.50", "devise": "CAD",
        "fournisseur": "Quincaillerie Fictive", "raison": "urgence chantier",
        "chantier_id": CHANTIER, "recu": RECU_CAS}})
    assert sous_plafond["ok"] and sous_plafond["resultat"]["accepte"], sous_plafond
    declare = sous_plafond["resultat"]
    assert declare["decision"]["statut"] == "accepte"
    attente = declare["attente_m5"]
    assert attente["type"] == "depense_terrain_a_saisir"
    for cle_interdite in ("paiement", "remboursement", "ordre", "payer"):
        assert cle_interdite not in attente
    with stockage.transaction():
        traces = [m for m in stockage.maillons(_DEPARTEMENT, "achats_terrain")
                  if isinstance(m, dict) and m.get("recu") == RECU_CAS]
    assert len(traces) == 1 and traces[0].get("en_attente") is not True

    double = executer_atomique(_outil("m6_declarer_achat_terrain"), {"achat": {
        "materiau_id": "scellant-fictif", "quantite": 3.0, "montant": "25.50", "devise": "CAD",
        "fournisseur": "Quincaillerie Fictive", "raison": "urgence chantier",
        "chantier_id": CHANTIER, "recu": RECU_CAS}})
    assert double["ok"] and double["resultat"]["accepte"] is False
    assert double["resultat"]["verdict"]["code"] == "REJ-ACHAT-TERRAIN-DEJA-DECLARE"

    hors_plafond = executer_atomique(_outil("m6_declarer_achat_terrain"), {"achat": {
        "materiau_id": "scellant-fictif", "quantite": 3.0, "montant": "200.00", "devise": "CAD",
        "fournisseur": "Quincaillerie Fictive", "raison": "rupture terrain",
        "chantier_id": CHANTIER, "recu": RECU_CAS_2}})
    assert hors_plafond["ok"] and hors_plafond["resultat"]["accepte"] is False
    assert hors_plafond["resultat"]["verdict"]["code"] == "REJ-ACHAT-TERRAIN-EN-ATTENTE"
    with stockage.transaction():
        attentes = [m for m in stockage.maillons(_DEPARTEMENT, "achats_terrain")
                    if isinstance(m, dict) and m.get("recu") == RECU_CAS_2]
    assert len(attentes) == 1 and attentes[0].get("en_attente") is True

    abus = executer_atomique(_outil("m6_receptionner_commande"), {
        "bon_demande": {
            "po_id": PO_ID, "chantier_id": CHANTIER,
            "lignes_demandees": [{"materiau_id": "gouttiere-5po", "quantite_demandee": 10.0}],
            "horodatage": "2026-09-01T08:00:00-04:00"},
        "reception_po": {
            "po_id": PO_ID, "chantier_id": CHANTIER,
            "lignes_recues": [{"materiau_id": "gouttiere-5po", "quantite_recue": 8.0}],
            "horodatage": "2026-10-07T09:00:00-04:00"},
        "details_reception": [{"materiau_id": "gouttiere-5po",
                               "statut_ligne": "conforme'; DROP TABLE stock;--"}],
    })
    assert abus["ok"] and abus["resultat"]["accepte"] is False
    assert abus["resultat"]["verdict"]["code"] == "REJ-RECEPTION-STATUT-INCONNU"
