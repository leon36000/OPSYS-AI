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

import copy

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


def _reception_ephem(lignes, details, *, lieu=None):
    """Charge entièrement fictive pour exercer l'entrée publique sans PO persisté."""
    po_id = "PO-EPHEM-COUVERTURE"
    demandees = [
        {"materiau_id": ligne["materiau_id"], "quantite_demandee": ligne["quantite_recue"]}
        for ligne in lignes
    ]
    arguments = {
        "bon_demande": {
            "po_id": po_id, "chantier_id": CHANTIER, "lignes_demandees": demandees,
            "horodatage": "2026-10-06T14:00:00-04:00",
        },
        "reception_po": {
            "po_id": po_id, "chantier_id": CHANTIER, "lignes_recues": lignes,
            "horodatage": "2026-10-06T14:30:00-04:00",
        },
        "details_reception": details,
    }
    if lieu is not None:
        arguments["lieu_livraison"] = lieu
    return executer_atomique(_outil("m6_receptionner_commande"), arguments)


def _assert_aucune_ecriture_reception():
    with stockage.transaction():
        assert len(stockage.maillons(_DEPARTEMENT, "principal")) == 0
        assert len(stockage.maillons(_DEPARTEMENT, "emplacements")) == 0
    assert _publies() == []


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


def test_endommage_reste_hors_disponible_et_rejeu_po_refuse(base_durable_m6):
    _po_envoye()
    arguments = {
        "bon_demande": {
            "po_id": PO_ID, "chantier_id": CHANTIER,
            "lignes_demandees": [{"materiau_id": "gouttiere-5po", "quantite_demandee": 10.0}],
            "horodatage": "2026-09-01T08:00:00-04:00"},
        "reception_po": {
            "po_id": PO_ID, "chantier_id": CHANTIER,
            "lignes_recues": [{"materiau_id": "gouttiere-5po", "quantite_recue": 8.0}],
            "horodatage": HORODATAGE},
        "details_reception": [{
            "materiau_id": "gouttiere-5po", "statut_ligne": "endommage", "photos": [PHOTO_CAS]}],
    }
    reception = executer_atomique(_outil("m6_receptionner_commande"), arguments)
    assert reception["ok"] and reception["resultat"]["accepte"] is True
    assert len(reception["resultat"]["transferts_emplacements"]) == 1
    transfert = reception["resultat"]["transferts_emplacements"][0]
    assert transfert["de"] == {"type": "inconnu", "reference": None}
    assert transfert["vers"] == {"type": "rebut", "reference": None}
    hash_reception = reception["resultat"]["resultat"]["accuse_reception"]["hash_maillon"]
    reference_publique = transfert["reference_source"]
    assert reference_publique["hash_reception"] == hash_reception
    assert reference_publique["mouvement"]["registre"] == "principal"
    assert reference_publique["mouvement"]["hash_maillon"]
    assert reference_publique["statut_ligne"] == "endommage"
    assert "preuves_cas" not in reference_publique  # déjà visibles dans details_lignes; pas de doublon de sortie
    with stockage.transaction():
        principal = list(stockage.maillons(_DEPARTEMENT, "principal"))
        transferts_durables = stockage.maillons(_DEPARTEMENT, "emplacements")
    rebut_durable = next(t for t in transferts_durables if t["vers"]["type"] == "rebut")
    assert rebut_durable["motif"] == transfert["motif"]
    assert rebut_durable["reference_source"]["hash_reception"] == hash_reception
    assert rebut_durable["reference_source"]["mouvement"]["hash_maillon"] == principal[-1]["hash_maillon"]
    assert rebut_durable["reference_source"]["preuves_cas"] == [PHOTO_CAS]
    assert m6_outils.emplacements.valider_chaine(transferts_durables) == (True, "")

    rejeu = executer_atomique(_outil("m6_receptionner_commande"), arguments)
    assert rejeu["ok"] and rejeu["resultat"]["accepte"] is False
    assert rejeu["resultat"]["verdict"]["code"] == "REJ-RECEPTION-DEJA-ENREGISTREE"

    lecture = executer_atomique(_outil("m6_lire_disponibilite"), {"materiau_ids": ["gouttiere-5po"]})
    assert lecture["ok"] and lecture["resultat"]["accepte"] is True
    article = lecture["resultat"]["resultat"]["articles"][0]
    assert article["stock_theorique"] == "8"
    assert article["en_main"] == "0"
    assert article["disponible"] == "0"
    assert article["par_emplacement"] == {"rebut": "8", "inconnu": "0"}


def test_reception_mixte_localise_le_conforme_et_met_le_dommage_au_rebut(base_durable_m6):
    args = {
        "bon_demande": {
            "po_id": "PO-EPHEM-MIXTE", "chantier_id": CHANTIER,
            "lignes_demandees": [
                {"materiau_id": "mat-endommage-fictif", "quantite_demandee": 5.0},
                {"materiau_id": "mat-conforme-fictif", "quantite_demandee": 5.0}],
            "horodatage": "2026-10-06T14:00:00-04:00"},
        "reception_po": {
            "po_id": "PO-EPHEM-MIXTE", "chantier_id": CHANTIER,
            "lignes_recues": [
                {"materiau_id": "mat-endommage-fictif", "quantite_recue": 5.0},
                {"materiau_id": "mat-conforme-fictif", "quantite_recue": 5.0}],
            "horodatage": "2026-10-06T14:30:00-04:00"},
        "details_reception": [
            {"materiau_id": "mat-endommage-fictif", "statut_ligne": "endommage", "photos": [PHOTO_CAS]},
            {"materiau_id": "mat-conforme-fictif", "statut_ligne": "conforme"}],
        "lieu_livraison": {"type": "depot"},
    }
    reception = executer_atomique(_outil("m6_receptionner_commande"), args)
    assert reception["ok"] and reception["resultat"]["accepte"] is True
    assert len(reception["resultat"]["transferts_emplacements"]) == 3

    lecture = executer_atomique(_outil("m6_lire_disponibilite"), {
        "materiau_ids": ["mat-endommage-fictif", "mat-conforme-fictif"]})
    assert lecture["ok"] and lecture["resultat"]["accepte"] is True
    articles = {a["materiau_id"]: a for a in lecture["resultat"]["resultat"]["articles"]}
    assert articles["mat-endommage-fictif"]["stock_theorique"] == "5"
    assert articles["mat-endommage-fictif"]["disponible"] == "0"
    assert articles["mat-endommage-fictif"]["par_emplacement"] == {"rebut": "5", "inconnu": "0"}
    assert articles["mat-conforme-fictif"]["stock_theorique"] == "5"
    assert articles["mat-conforme-fictif"]["disponible"] == "5"
    assert articles["mat-conforme-fictif"]["par_emplacement"] == {"depot": "5", "inconnu": "0"}


def test_receptions_ephemeres_repetees_creent_un_transfert_distinct_par_fait(base_durable_m6):
    args = {
        "bon_demande": {
            "po_id": "PO-EPHEM-REJEU", "chantier_id": CHANTIER,
            "lignes_demandees": [{"materiau_id": "mat-endommage-rejoue", "quantite_demandee": 5.0}],
            "horodatage": "2026-10-06T14:00:00-04:00"},
        "reception_po": {
            "po_id": "PO-EPHEM-REJEU", "chantier_id": CHANTIER,
            "lignes_recues": [{"materiau_id": "mat-endommage-rejoue", "quantite_recue": 5.0}],
            "horodatage": "2026-10-06T14:30:00-04:00"},
        "details_reception": [{
            "materiau_id": "mat-endommage-rejoue", "statut_ligne": "endommage", "photos": [PHOTO_CAS]}],
    }
    premieres_reponses = [executer_atomique(_outil("m6_receptionner_commande"), args) for _ in range(2)]
    assert all(r["ok"] and r["resultat"]["accepte"] for r in premieres_reponses)
    identifiants = [r["resultat"]["transferts_emplacements"][0]["transfert_id"] for r in premieres_reponses]
    assert len(set(identifiants)) == 2

    lecture = executer_atomique(_outil("m6_lire_disponibilite"), {
        "materiau_ids": ["mat-endommage-rejoue"]})
    article = lecture["resultat"]["resultat"]["articles"][0]
    assert article["stock_theorique"] == "10"
    assert article["en_main"] == "0" and article["disponible"] == "0"
    assert article["par_emplacement"] == {"rebut": "10", "inconnu": "0"}


def test_refus_localisation_annule_aussi_reception_po_et_evenement(base_durable_m6, monkeypatch):
    _po_envoye()

    def refuser_apres_ecriture_stock(*args, **kwargs):
        # Le garde de transfert est atteint après l'ajout RECEPTION, mais dans la même transaction publique.
        assert len(stockage.maillons(_DEPARTEMENT, "principal")) == 1
        return None, {"code": "REJ-TRANSFERT-STOCK-LOCALISE-INCOHERENT"}

    monkeypatch.setattr(m6_outils.emplacements, "construire_transfert", refuser_apres_ecriture_stock)
    reponse = executer_atomique(_outil("m6_receptionner_commande"), {
        "bon_demande": {
            "po_id": PO_ID, "chantier_id": CHANTIER,
            "lignes_demandees": [{"materiau_id": "gouttiere-5po", "quantite_demandee": 10.0}],
            "horodatage": "2026-09-01T08:00:00-04:00"},
        "reception_po": {
            "po_id": PO_ID, "chantier_id": CHANTIER,
            "lignes_recues": [{"materiau_id": "gouttiere-5po", "quantite_recue": 8.0}],
            "horodatage": HORODATAGE},
        "details_reception": [{
            "materiau_id": "gouttiere-5po", "statut_ligne": "endommage", "photos": [PHOTO_CAS]}],
    })
    assert reponse["ok"] is False and reponse["erreur"] == "refus_metier"
    assert "REJ-TRANSFERT-STOCK-LOCALISE-INCOHERENT" in reponse["details"]

    with stockage.transaction():
        assert len(stockage.maillons(_DEPARTEMENT, "principal")) == 0
        assert len(stockage.maillons(_DEPARTEMENT, "emplacements")) == 0
        po = m6_outils.bons_commande.lire(stockage.maillons(_DEPARTEMENT, "bons_commande"), PO_ID)
        assert po["statut"] == "sent_to_supplier"
    assert _publies() == []


@pytest.mark.parametrize("details", [
    [
        {"materiau_id": "mat-unique-fictif", "statut_ligne": "endommage", "photos": [PHOTO_CAS]},
        {"materiau_id": "mat-unique-fictif", "statut_ligne": "conforme"},
    ],
    [
        {"materiau_id": "mat-unique-fictif", "statut_ligne": "conforme"},
        {"materiau_id": "mat-unique-fictif", "statut_ligne": "endommage", "photos": [PHOTO_CAS]},
    ],
], ids=["endommage-puis-conforme", "conforme-puis-endommage"])
def test_details_dupliques_refuses_dans_les_deux_ordres_sans_ecriture(base_durable_m6, details):
    reponse = _reception_ephem(
        [{"materiau_id": "mat-unique-fictif", "quantite_recue": 8.0}], details
    )
    assert reponse["ok"] and reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-RECEPTION-DETAILS-DUPLIQUES"
    _assert_aucune_ecriture_reception()


def test_detail_d_un_id_inconnu_refuse_sans_rendre_la_vraie_ligne_conforme(base_durable_m6):
    reponse = _reception_ephem(
        [{"materiau_id": "mat-recu-fictif", "quantite_recue": 4.0}],
        [{"materiau_id": "mat-inconnu-fictif", "statut_ligne": "conforme"}],
    )
    assert reponse["ok"] and reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-RECEPTION-DETAILS-LIGNES-INCOHERENTES"
    _assert_aucune_ecriture_reception()


def test_detail_manquant_pour_une_ligne_recue_refuse_sans_ecriture(base_durable_m6):
    reponse = _reception_ephem(
        [
            {"materiau_id": "mat-a-fictif", "quantite_recue": 4.0},
            {"materiau_id": "mat-b-fictif", "quantite_recue": 3.0},
        ],
        [{"materiau_id": "mat-a-fictif", "statut_ligne": "conforme"}],
    )
    assert reponse["ok"] and reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-RECEPTION-DETAILS-INCOMPLETS"
    _assert_aucune_ecriture_reception()


def test_lignes_recues_dupliquees_sont_refusees_comme_ambigues_si_details_fournis(base_durable_m6):
    po_id = "PO-EPHEM-DETAILS-AMBIGUS"
    reponse = executer_atomique(_outil("m6_receptionner_commande"), {
        "bon_demande": {
            "po_id": po_id, "chantier_id": CHANTIER,
            "lignes_demandees": [{"materiau_id": "mat-ambigu-fictif", "quantite_demandee": 4.0}],
            "horodatage": "2026-10-06T14:00:00-04:00",
        },
        "reception_po": {
            "po_id": po_id, "chantier_id": CHANTIER,
            "lignes_recues": [
                {"materiau_id": "mat-ambigu-fictif", "quantite_recue": 2.0},
                {"materiau_id": "mat-ambigu-fictif", "quantite_recue": 2.0},
            ],
            "horodatage": "2026-10-06T14:30:00-04:00",
        },
        "details_reception": [{"materiau_id": "mat-ambigu-fictif", "statut_ligne": "conforme"}],
    })
    assert reponse["ok"] and reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-RECEPTION-DETAILS-LIGNES-AMBIGUES"
    _assert_aucune_ecriture_reception()


def test_details_reordonnees_restent_associees_par_id_et_le_lien_durable_est_visible(base_durable_m6):
    reponse = _reception_ephem(
        [
            {"materiau_id": "mat-a-fictif", "quantite_recue": 4.0},
            {"materiau_id": "mat-b-fictif", "quantite_recue": 3.0},
        ],
        [
            {"materiau_id": "mat-b-fictif", "statut_ligne": "endommage", "photos": [PHOTO_CAS],
             "contenu_photo": "FAUX-OCTETS-SECRET"},
            {"materiau_id": "mat-a-fictif", "statut_ligne": "conforme"},
        ],
        lieu={"type": "depot"},
    )
    assert reponse["ok"] and reponse["resultat"]["accepte"] is True, reponse
    resultat = reponse["resultat"]
    assert "transferts_emplacements" in resultat, reponse
    hash_reception = resultat["resultat"]["accuse_reception"]["hash_maillon"]
    par_article = {t["materiau_id"]: t for t in resultat["transferts_emplacements"] if t["vers"]["type"] == "rebut"}
    assert set(par_article) == {"mat-b-fictif"}
    rebut = par_article["mat-b-fictif"]
    assert rebut["reference_source"]["hash_reception"] == hash_reception
    assert rebut["reference_source"]["mouvement"]["registre"] == "principal"
    assert rebut["reference_source"]["statut_ligne"] == "endommage"
    assert "preuves_cas" not in rebut["reference_source"]
    assert "FAUX-OCTETS-SECRET" not in repr(reponse)
    with stockage.transaction():
        principal = list(stockage.maillons(_DEPARTEMENT, "principal"))
        durable = stockage.maillons(_DEPARTEMENT, "emplacements")
    mouvement_b = next(m for m in principal if m["materiau_id"] == "mat-b-fictif")
    assert rebut["reference_source"]["mouvement"]["hash_maillon"] == mouvement_b["hash_maillon"]
    rebut_durable = next(t for t in durable if t["vers"]["type"] == "rebut")
    assert rebut_durable["reference_source"]["mouvement"]["index"] == mouvement_b["index"]
    assert rebut_durable["reference_source"]["preuves_cas"] == [PHOTO_CAS]
    assert "FAUX-OCTETS-SECRET" not in repr(durable)
    assert m6_outils.emplacements.valider_chaine(durable) == (True, "")
    touche = copy.deepcopy(list(durable))
    next(t for t in touche if t["vers"]["type"] == "rebut")["reference_source"]["preuves_cas"][0] = (
        "fichier:sha256:" + "ff" * 32
    )
    assert m6_outils.emplacements.valider_chaine(touche)[0] is False
    lecture = executer_atomique(_outil("m6_lire_disponibilite"), {
        "materiau_ids": ["mat-a-fictif", "mat-b-fictif"]})
    articles = {a["materiau_id"]: a for a in lecture["resultat"]["resultat"]["articles"]}
    assert articles["mat-a-fictif"]["disponible"] == "4"
    assert articles["mat-b-fictif"]["disponible"] == "0"
