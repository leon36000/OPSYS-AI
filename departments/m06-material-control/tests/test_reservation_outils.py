"""PLAN T4.14 (M6.8, M6.9, M6.4) : réservation par chantier, emplacements et « matériel prêt », par les outils et le
consommateur de `m3.devis_accepte`, sur une base SQLite réelle et les vrais registres durables de M6.

Ce que ces tests fixent :
- le devis accepté réserve, dans la MÊME transaction que le prévu, et publie `m6.materiel_pret` (`pret`, `partiel`,
  `a_commander`, avec les lignes manquantes) ; un prévu vide, une estimation, un rejeu ne publient rien de faux ;
- pas de double réservation ; deux chantiers ne se partagent jamais la même unité ; le disponible est en main -
  réservé ;
- une réception complète les réservations, une sortie de stock les fait céder, la déclaration des matériaux les clôt,
  la libération (N2) remet le stock au disponible : à chaque fois `m6.materiel_pret`, jamais un stock négatif ;
- les transferts d'emplacement sont audités et la chaîne de mouvements de stock ne bouge pas d'un octet ;
- le disponible alimente le réapprovisionnement ; AUCUN bon de commande n'est créé seul.

Identifiants, quantités et fournisseurs fictifs (`fictif: true` au sens d'AGENTS.md).
"""

from __future__ import annotations

from decimal import Decimal

import m6_material_control.outils as m6_outils
import pytest
import yaml
from m6_material_control import acces, emplacements, reservations
from m6_material_control.registre import Registre
from sqlalchemy import select

from opsys import evenements, stockage
from opsys.evenements.schemas import erreurs_charge
from opsys.outils import Niveau, executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS

FICTIF = True
_DEPARTEMENT = "m06-material-control"
TYPE = "m6.materiel_pret"
GOUTTIERE = "gouttiere-5po"
VIS = "vis-inox"
H_DEVIS = "2026-09-30T10:00:00-04:00"
H_RECEPTION = "2026-10-05T09:00:00-04:00"
H_ACTION = "2026-10-06T11:00:00-04:00"


@pytest.fixture
def base(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-m6-reservation.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    try:
        yield url
    finally:
        stockage.liberer()


@pytest.fixture
def m6():
    return {o.nom: o for o in m6_outils.outils()}


# ---------------------------------------------------------------------------------------------- aides
def _devis(devis_id="DEVIS-FICT-1", chantier_id="CH-FICT-1", gouttiere="100", vis="20"):
    lignes = [{"reference_ligne": f"{devis_id}-L{i}", "description": "ligne fictive", "quantite": quantite,
               "unite": unite, "prix_unitaire": "10.00", "prix_ligne": "10.00", "reference_besoin_materiau": materiau}
              for i, (materiau, quantite, unite) in enumerate(
                  [(GOUTTIERE, gouttiere, "pi"), (VIS, vis, "boite")]) if quantite is not None]
    return {"devis_id": devis_id, "lead_id": "lead-fictif", "chantier_id": chantier_id, "lignes": lignes,
            "cout_total": "100.00", "prix_total": "135.00", "taux_marge": "0.35",
            "horodatage_acceptation": H_DEVIS}


def _accepter(charge):
    """Ce que le répartiteur fait : le consommateur de `m3.devis_accepte`, dans une transaction."""
    with stockage.transaction():
        return m6_outils._recevoir_devis_accepte(charge)


def _outil(m6, nom, arguments):
    reponse = executer_atomique(m6[nom], arguments)
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _recevoir(m6, materiau_id, quantite, po_id, chantier_id="CH-DEPOT-FICT"):
    """Une réception éphémère (aucun PO persisté) : du stock entre, et les réservations se complètent."""
    return _outil(m6, "m6_receptionner_commande", {
        "bon_demande": {"po_id": po_id, "chantier_id": chantier_id, "horodatage": "2026-09-01T00:00:00Z",
                        "lignes_demandees": [{"materiau_id": materiau_id, "quantite_demandee": quantite}]},
        "reception_po": {"po_id": po_id, "chantier_id": chantier_id, "horodatage": H_RECEPTION,
                         "lignes_recues": [{"materiau_id": materiau_id, "quantite_recue": quantite}]},
        "catalogue_materiaux": {"version": "v1-fictif", "unite_monetaire": "CAD",
                                "postes": {materiau_id: {"cout_unitaire": 5.0, "libelle": materiau_id}}},
    })


def _publies(devis_id=None):
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS).where(
            EVENEMENTS_SORTANTS.c.type_evenement == TYPE).order_by(EVENEMENTS_SORTANTS.c.cree_le)).mappings().all()
    charges = [codec.decoder(ligne["charge"]) for ligne in lignes]
    return [c for c in charges if devis_id is None or c["devis_id"] == devis_id]


def _maillons(nom):
    with stockage.transaction():
        return list(stockage.maillons(_DEPARTEMENT, nom))


def _etat(devis_id="DEVIS-FICT-1"):
    return reservations.etat(devis_id, _maillons("reservations"))


def _disponibilite(m6, *materiaux):
    resultat = _outil(m6, "m6_lire_disponibilite", {"materiau_ids": list(materiaux)})["resultat"]
    return {a["materiau_id"]: a for a in resultat["articles"]}, resultat


# ---------------------------------------------------------------------- le devis accepté réserve
def test_devis_accepte_sans_stock_publie_a_commander_avec_les_lignes_manquantes(base):
    reponse = _accepter(_devis())

    assert reponse["accepte"] is True
    assert reponse["reservation"]["statut"] == "creee"
    (charge,) = _publies()
    assert erreurs_charge(TYPE, charge) == []
    assert (charge["statut"], charge["revision"], charge["declencheur"], charge["reservation_active"]) == (
        "a_commander", 1, "devis_accepte", True)
    assert (charge["devis_id"], charge["chantier_id"], charge["horodatage"]) == ("DEVIS-FICT-1", "CH-FICT-1", H_DEVIS)
    assert [(m["materiau_id"], m["quantite_manquante"]) for m in charge["lignes_manquantes"]] == [
        (GOUTTIERE, "100"), (VIS, "20")]
    assert reponse["reservation"]["statut"] == "creee" and charge["evenement_id"] == "m6-materiel-pret-DEVIS-FICT-1-1"


def test_aucun_bon_de_commande_n_est_cree_seul(base):
    """`a_commander` dit ce qui manque ; commander reste le geste d'un humain."""
    _accepter(_devis())
    assert _maillons("bons_commande") == [] and _maillons("fournisseurs") == [] and _maillons("livre_prix") == []


def test_stock_partiel_reserve_ce_qui_existe(base, m6):
    _recevoir(m6, GOUTTIERE, 60.0, "PO-DEPOT-1")

    _accepter(_devis())

    (charge,) = _publies()
    assert charge["statut"] == "partiel"
    assert {ligne["materiau_id"]: ligne["quantite_reservee"] for ligne in charge["lignes"]} == {
        GOUTTIERE: "60", VIS: "0"}
    assert [(m["materiau_id"], m["quantite_manquante"]) for m in charge["lignes_manquantes"]] == [
        (GOUTTIERE, "40"), (VIS, "20")]


def test_stock_suffisant_est_pret(base, m6):
    _recevoir(m6, GOUTTIERE, 150.0, "PO-DEPOT-1")
    _recevoir(m6, VIS, 25.0, "PO-DEPOT-2")

    _accepter(_devis())

    (charge,) = _publies()
    assert (charge["statut"], charge["lignes_manquantes"]) == ("pret", [])
    assert erreurs_charge(TYPE, charge) == []
    lecture = _outil(m6, "m6_lire_disponibilite", {"materiau_ids": [GOUTTIERE]})["resultat"]
    assert lecture["articles"][0]["reserve"] == "100"


def test_un_devis_sans_ligne_de_materiau_ne_reserve_rien_et_ne_publie_rien(base):
    """Prévu vide connu : dire « prêt » ferait partir une équipe sans avoir rien vérifié."""
    reponse = _accepter(_devis(gouttiere=None, vis=None))

    assert reponse["reservation"] == {"accepte": True, "statut": "aucun_besoin_connu"}
    assert _publies() == [] and _maillons("reservations") == []


def test_le_meme_devis_redelivre_n_ecrit_rien_de_plus(base, m6):
    _recevoir(m6, GOUTTIERE, 150.0, "PO-DEPOT-1")
    _accepter(_devis())
    avant = (_maillons("reservations"), _publies(), _maillons("besoins_prevus"))

    rejeu = _accepter(_devis())

    assert rejeu["accepte"] is False, "le prévu est déjà rangé : refus nommé, comme avant T4.14"
    assert rejeu["reservation"]["statut"] == "deja_reservee"
    assert (_maillons("reservations"), _publies(), _maillons("besoins_prevus")) == avant


def test_deux_devis_ne_se_partagent_jamais_la_meme_unite(base, m6):
    _recevoir(m6, GOUTTIERE, 100.0, "PO-DEPOT-1")

    _accepter(_devis("DEVIS-A", "CH-A", gouttiere="70", vis=None))
    _accepter(_devis("DEVIS-B", "CH-B", gouttiere="50", vis=None))

    assert _publies("DEVIS-A")[0]["statut"] == "pret"
    charge_b = _publies("DEVIS-B")[0]
    assert charge_b["statut"] == "partiel" and charge_b["lignes"][0]["quantite_reservee"] == "30"
    chiffres, _ = _disponibilite(m6, GOUTTIERE)
    assert (chiffres[GOUTTIERE]["en_main"], chiffres[GOUTTIERE]["reserve"], chiffres[GOUTTIERE]["disponible"]) == (
        "100", "100", "0")


def test_une_estimation_ne_reserve_jamais(base, m6):
    """Le prévu provisoire (`m3.besoins_materiaux`) n'engage personne : ni le bus ni l'outil ne réservent."""
    with stockage.transaction():
        m6_outils._recevoir_besoins_materiaux({
            "devis_id": "DEVIS-EST", "lead_id": "lead-fictif", "estimation_id": "a" * 64, "rang_registre": 0,
            "bareme_version": "b-fictif", "niveau_confiance": 0.8, "facteurs_perte_absents": [],
            "lignes": [{"materiau": GOUTTIERE, "quantite_estimee": "10", "unite": "pi", "facteur_perte": "0.1"}]})

    reponse = _outil(m6, "m6_reserver_materiel", {"devis_id": "DEVIS-EST", "horodatage": H_ACTION})

    assert reponse["accepte"] is False and reponse["verdict"]["code"] == "REJ-RESERVATION-PREVU-PROVISOIRE"
    assert _maillons("reservations") == [] and _publies() == []


def test_un_devis_accepte_apres_la_declaration_de_ses_materiaux_ne_reserve_plus(base, m6):
    """Ordre inversé du bus : les matériaux du chantier sont déjà déclarés quand `m3.devis_accepte` arrive. Une
    réservation resterait active à jamais pour un chantier terminé."""
    _recevoir(m6, GOUTTIERE, 100.0, "PO-DEPOT-1", chantier_id="CH-FICT-1")
    _wct_declare(m6, "WCT-FICT-1", "DEVIS-FICT-1", "CH-FICT-1", 40.0)

    reponse = _accepter(_devis())

    assert reponse["reservation"] == {"accepte": True, "statut": "chantier_deja_declare"}
    assert _maillons("reservations") == [] and _publies() == []


def _wct_declare(m6, wct_id, devis_id, chantier_id, quantite, materiau=GOUTTIERE, type_ligne="non_prevu"):
    """Le WCT reçu par M6 (bus) puis la déclaration des matériaux, par les vrais outils."""
    charge = {
        "wct_id": wct_id, "intervention_id": f"int-{wct_id}", "lead_id": "lead-fictif", "technicien_id": "t1",
        "horodatage_completion": "2026-10-07T12:00:00+00:00",
        "fix_gps_completion": {"latitude": 45.5, "longitude": -73.5},
        "duree_reelle_minutes": 120, "ecart_signale": False, "revue_id": None, "hash_maillon": "a" * 16,
        "consommateurs_cibles": ["M6"], "devis_id": devis_id, "statut": "completed_pending_review",
    }
    with stockage.transaction():
        evenements.publier("m4.travaux_termines", "m04-field-ops", charge, evenement_id=wct_id)
        m6_outils._recevoir_travaux_termines({k: v for k, v in charge.items() if k != "statut"})
    return _outil(m6, "m6_declarer_materiaux_utilises", {
        "wct_id": wct_id,
        "formulaire": {"wct_id": wct_id, "intervention_id": f"int-{wct_id}", "chantier_id": chantier_id,
                       "lignes_materiaux": [{"type_ligne": type_ligne, "materiau_id": materiau, "quantite": quantite,
                                             "unite": "pi"}]}})


# ------------------------------------------------------------------------ réconciliation du stock
def test_une_reception_complete_la_reservation_puis_le_devis_est_pret(base, m6):
    _accepter(_devis())

    partielle = _recevoir(m6, GOUTTIERE, 100.0, "PO-DEPOT-1")
    complete_gouttiere = _publies()[-1]
    assert partielle["evenements_materiel_pret"] == [complete_gouttiere["evenement_id"]]
    assert (complete_gouttiere["statut"], complete_gouttiere["declencheur"], complete_gouttiere["revision"]) == (
        "partiel", "stock_recu", 2)
    complete = _recevoir(m6, VIS, 20.0, "PO-DEPOT-2")

    dernier = _publies()[-1]
    assert complete["evenements_materiel_pret"] == [dernier["evenement_id"]]
    assert (dernier["statut"], dernier["revision"], dernier["lignes_manquantes"]) == ("pret", 3, [])
    assert [c["statut"] for c in _publies("DEVIS-FICT-1")] == ["a_commander", "partiel", "pret"]
    assert all(erreurs_charge(TYPE, c) == [] for c in _publies())


def test_une_reception_sans_reservation_ne_publie_rien_comportement_d_avant(base, m6):
    reponse = _recevoir(m6, GOUTTIERE, 100.0, "PO-DEPOT-1")
    assert "evenements_materiel_pret" not in reponse and _publies() == [] and _maillons("reservations") == []


def test_le_stock_qui_arrive_complete_d_abord_le_devis_le_plus_ancien(base, m6):
    _accepter(_devis("DEVIS-A", "CH-A", gouttiere="50", vis=None))
    _accepter(_devis("DEVIS-B", "CH-B", gouttiere="50", vis=None))

    _recevoir(m6, GOUTTIERE, 70.0, "PO-DEPOT-1")

    assert {devis: _publies(devis)[-1]["lignes"][0]["quantite_reservee"] for devis in ("DEVIS-A", "DEVIS-B")} == {
        "DEVIS-A": "50", "DEVIS-B": "20"}


def test_la_declaration_des_materiaux_cloture_la_reservation_sans_evenement_et_rend_le_disponible(base, m6):
    _recevoir(m6, GOUTTIERE, 100.0, "PO-DEPOT-1", chantier_id="CH-FICT-1")
    _accepter(_devis(gouttiere="100", vis=None))
    assert _etat()["actif"] is True
    avant = len(_publies())

    _wct_declare(m6, "WCT-FICT-1", "DEVIS-FICT-1", "CH-FICT-1", 40.0, type_ligne="non_prevu")

    etat = _etat()
    assert (etat["actif"], etat["evenement"], etat["wct_id"]) == (False, "cloturee", "WCT-FICT-1")
    assert len(_publies()) == avant, "le chantier est terminé : aucun m6.materiel_pret"
    chiffres, _ = _disponibilite(m6, GOUTTIERE)
    assert (chiffres[GOUTTIERE]["en_main"], chiffres[GOUTTIERE]["reserve"], chiffres[GOUTTIERE]["disponible"]) == (
        "60", "0", "60")


def test_un_autre_chantier_qui_consomme_du_stock_reserve_fait_ceder_la_reservation_la_plus_recente(base, m6):
    """Le stock n'est jamais négatif : 100 en main, A en a réservé 100. Un chantier sans réservation en consomme 30
    (la réalité ne se refuse pas) : le réservé cède à 70, jamais au-delà de l'en main."""
    _recevoir(m6, GOUTTIERE, 100.0, "PO-DEPOT-1", chantier_id="CH-AUTRE")
    _accepter(_devis("DEVIS-A", "CH-A", gouttiere="100", vis=None))
    assert _publies("DEVIS-A")[-1]["statut"] == "pret"

    _wct_declare(m6, "WCT-AUTRE", "DEVIS-SANS-RESERVATION", "CH-AUTRE", 30.0)

    dernier = _publies("DEVIS-A")[-1]
    assert (dernier["statut"], dernier["declencheur"], dernier["revision"]) == ("partiel", "stock_sorti", 2)
    assert dernier["lignes"][0]["quantite_reservee"] == "70"
    chiffres, _ = _disponibilite(m6, GOUTTIERE)
    assert (chiffres[GOUTTIERE]["en_main"], chiffres[GOUTTIERE]["reserve"], chiffres[GOUTTIERE]["disponible"]) == (
        "70", "70", "0")


def test_l_outil_ferme_m6_consommer_materiaux_cloture_aussi_la_reservation_de_son_devis(base, m6):
    """`m6_consommer_materiaux` (WCT fourni par l'appelant, fermé aux appareils) sort du stock comme la déclaration : la
    réservation du devis du WCT est clôturée, et les autres se réconcilient."""
    _recevoir(m6, GOUTTIERE, 100.0, "PO-DEPOT-1", chantier_id="CH-FICT-1")
    _accepter(_devis("DEVIS-A", "CH-FICT-1", gouttiere="60", vis=None))
    _accepter(_devis("DEVIS-B", "CH-B", gouttiere="60", vis=None))
    assert _publies("DEVIS-B")[-1]["lignes"][0]["quantite_reservee"] == "40"
    wct = {"wct_id": "WCT-CONS-1", "intervention_id": "int-1", "lead_id": "lead-fictif", "technicien_id": "t1",
           "horodatage_completion": "2026-10-07T12:00:00+00:00",
           "fix_gps_completion": {"latitude": 1.0, "longitude": 2.0},
           "duree_reelle_minutes": 30, "ecart_signale": False, "revue_id": None, "hash_maillon": "a" * 64,
           "consommateurs_cibles": ["M6"], "devis_id": "DEVIS-A"}

    reponse = _outil(m6, "m6_consommer_materiaux", {"wct": wct, "formulaire": {
        "wct_id": "WCT-CONS-1", "intervention_id": "int-1", "chantier_id": "CH-FICT-1",
        "lignes_consommees": [{"materiau_id": GOUTTIERE, "quantite": 20.0}]}})

    assert reponse["accepte"] is True
    assert reservations.etat("DEVIS-A", _maillons("reservations"))["evenement"] == "cloturee"
    dernier_b = _publies("DEVIS-B")[-1]
    assert (dernier_b["lignes"][0]["quantite_reservee"], dernier_b["statut"], dernier_b["declencheur"]) == (
        "60", "pret", "stock_recu"), "80 en main, la réservation de A rendue : B se complète"


# ---------------------------------------------------------------------------------------- libération
def test_liberer_remet_le_stock_au_disponible_et_complete_le_devis_suivant(base, m6):
    _recevoir(m6, GOUTTIERE, 100.0, "PO-DEPOT-1")
    _accepter(_devis("DEVIS-A", "CH-A", gouttiere="100", vis=None))
    _accepter(_devis("DEVIS-B", "CH-B", gouttiere="60", vis=None))
    assert _publies("DEVIS-B")[-1]["statut"] == "a_commander"

    reponse = _outil(m6, "m6_liberer_reservation",
                     {"devis_id": "DEVIS-A", "motif": "chantier annulé par le client", "horodatage": H_ACTION})

    assert reponse["accepte"] is True and reponse["statut"] == "liberee"
    assert reponse["liberees"] == [{"materiau_id": GOUTTIERE, "quantite": "100"}]
    libere = _publies("DEVIS-A")[-1]
    assert (libere["statut"], libere["reservation_active"], libere["declencheur"]) == (
        "a_commander", False, "liberation")
    assert len(libere["lignes_manquantes"]) == 1, "rien n'est plus tenu de côté : jamais prêt"
    suivant = _publies("DEVIS-B")[-1]
    assert (suivant["statut"], suivant["declencheur"]) == ("pret", "stock_recu")
    assert len(reponse["evenements_materiel_pret"]) == 2
    etat = _etat("DEVIS-A")
    assert (etat["actif"], etat["motif"], etat["acteur"]) == (False, "chantier annulé par le client", "agent")


def test_liberer_deux_fois_ne_fait_rien_de_plus(base, m6):
    _accepter(_devis())
    arguments = {"devis_id": "DEVIS-FICT-1", "motif": "annulé", "horodatage": H_ACTION}
    _outil(m6, "m6_liberer_reservation", arguments)
    avant = (_maillons("reservations"), _publies())

    rejeu = _outil(m6, "m6_liberer_reservation", arguments)

    assert rejeu["accepte"] is True and rejeu["statut"] == "deja_liberee"
    assert (_maillons("reservations"), _publies()) == avant


@pytest.mark.parametrize("arguments, code", [
    ({"devis_id": "DEVIS-INCONNU", "motif": "x", "horodatage": H_ACTION}, "REJ-RESERVATION-INTROUVABLE"),
    ({"devis_id": "DEVIS-FICT-1", "motif": "  ", "horodatage": H_ACTION}, "REJ-RESERVATION-MOTIF-VIDE"),
    ({"devis_id": "DEVIS-FICT-1", "motif": "x", "horodatage": ""}, "REJ-RESERVATION-HORODATAGE-VIDE"),
])
def test_liberer_refuse_sans_reservation_sans_motif_sans_horodatage(base, m6, arguments, code):
    _accepter(_devis())
    avant = _maillons("reservations")

    reponse = _outil(m6, "m6_liberer_reservation", arguments)

    assert reponse["accepte"] is False and reponse["verdict"]["code"] == code
    assert _maillons("reservations") == avant


def test_le_bus_ne_re_reserve_pas_apres_une_liberation_mais_l_outil_le_peut(base, m6):
    _recevoir(m6, GOUTTIERE, 100.0, "PO-DEPOT-1")
    _accepter(_devis(gouttiere="100", vis=None))
    _outil(m6, "m6_liberer_reservation", {"devis_id": "DEVIS-FICT-1", "motif": "annulé", "horodatage": H_ACTION})
    apres_liberation = (_maillons("reservations"), _publies())

    rejeu_bus = _accepter(_devis(gouttiere="100", vis=None))
    assert rejeu_bus["reservation"]["statut"] == "deja_traitee"
    assert (_maillons("reservations"), _publies()) == apres_liberation

    manuel = _outil(m6, "m6_reserver_materiel", {"devis_id": "DEVIS-FICT-1", "horodatage": H_ACTION})
    assert manuel["statut"] == "creee" and manuel["reservation"]["statut"] == "pret"
    dernier = _publies()[-1]
    assert (dernier["revision"], dernier["declencheur"], dernier["reservation_active"]) == (
        3, "reservation_manuelle", True)


def test_l_outil_reserve_un_prevu_saisi_a_la_main_sans_double(base, m6):
    _outil(m6, "m6_enregistrer_besoins_prevus", {
        "chantier_id": "CH-MANUEL", "devis_id": "DEVIS-MANUEL",
        "lignes": [{"materiau_id": GOUTTIERE, "quantite_estimee": 10.0, "unite": "pi"}]})
    assert _maillons("reservations") == [], "le prévu manuel ne réserve pas de lui-même"

    premiere = _outil(m6, "m6_reserver_materiel", {"devis_id": "DEVIS-MANUEL", "horodatage": H_ACTION})
    seconde = _outil(m6, "m6_reserver_materiel", {"devis_id": "DEVIS-MANUEL", "horodatage": H_ACTION})

    assert (premiere["statut"], premiere["reservation"]["statut"]) == ("creee", "a_commander")
    assert seconde["statut"] == "deja_reservee" and len(_maillons("reservations")) == 1 and len(_publies()) == 1


def test_reserver_un_devis_sans_prevu_est_refuse(base, m6):
    reponse = _outil(m6, "m6_reserver_materiel", {"devis_id": "DEVIS-SANS-PREVU", "horodatage": H_ACTION})
    assert reponse["accepte"] is False and reponse["verdict"]["code"] == "REJ-RESERVATION-PREVU-ABSENT"


# ------------------------------------------------------------------------------ le bon de commande
def test_le_brouillon_de_po_commande_ce_qui_manque_a_la_reservation_pas_l_ecart_au_stock_du_chantier(base, m6):
    """40 gouttières en main, tout réservé par le devis A ; B en veut 50 et n'en obtient rien. Le brouillon de B
    commande les 50 manquants, pas 50 - (stock du chantier) : le stock est réservé pour A."""
    _recevoir(m6, GOUTTIERE, 40.0, "PO-DEPOT-1", chantier_id="CH-B")
    _accepter(_devis("DEVIS-A", "CH-A", gouttiere="40", vis=None))
    _accepter(_devis("DEVIS-B", "CH-B", gouttiere="50", vis=None))
    for materiau, prix in ((GOUTTIERE, 8.5),):
        _outil(m6, "m6_enregistrer_prix", {"materiau_id": materiau, "fournisseur_id": "gentek", "prix_unitaire": prix,
                                           "devise": "CAD", "date_effet": "2026-01-01"})
    _outil(m6, "m6_enregistrer_fournisseur", {"fournisseur_id": "gentek", "nom": "Gentek", "horodatage": H_DEVIS})

    reponse = _outil(m6, "m6_creer_po_brouillon", {
        "po_id": "PO-FICT-B", "devis_id": "DEVIS-B", "fournisseur_id": "gentek", "horodatage": H_ACTION})

    assert reponse["accepte"] is True and reponse["quantites_depuis"] == "reservation"
    lignes = [(ligne["materiau_id"], ligne["quantite_demandee"]) for ligne in reponse["po"]["lignes"]]
    assert lignes == [(GOUTTIERE, 50.0)]
    assert reponse["po"]["statut"] == "draft", "un brouillon : ni approuvé ni envoyé"


def test_un_devis_pret_n_a_rien_a_commander(base, m6):
    _recevoir(m6, GOUTTIERE, 100.0, "PO-DEPOT-1")
    _accepter(_devis(gouttiere="100", vis=None))
    _outil(m6, "m6_enregistrer_fournisseur", {"fournisseur_id": "gentek", "nom": "Gentek", "horodatage": H_DEVIS})

    reponse = _outil(m6, "m6_creer_po_brouillon", {
        "po_id": "PO-FICT-A", "devis_id": "DEVIS-FICT-1", "fournisseur_id": "gentek", "horodatage": H_ACTION})

    assert reponse == {"accepte": True, "po": None, "statut": "aucun_achat_requis"}
    assert _maillons("bons_commande") == []


def test_sans_reservation_le_brouillon_de_po_est_celui_d_avant(base, m6):
    _outil(m6, "m6_enregistrer_besoins_prevus", {
        "chantier_id": "CH-MANUEL", "devis_id": "DEVIS-MANUEL",
        "lignes": [{"materiau_id": GOUTTIERE, "quantite_estimee": 10.0, "unite": "pi"}]})
    _outil(m6, "m6_enregistrer_fournisseur", {"fournisseur_id": "gentek", "nom": "Gentek", "horodatage": H_DEVIS})

    reponse = _outil(m6, "m6_creer_po_brouillon", {
        "po_id": "PO-FICT-M", "devis_id": "DEVIS-MANUEL", "fournisseur_id": "gentek", "horodatage": H_ACTION})

    assert "quantites_depuis" not in reponse
    assert [ligne["quantite_demandee"] for ligne in reponse["po"]["lignes"]] == [10.0]


# ------------------------------------------------------------------------------------------ transferts
def _transferer(m6, transfert_id, de, vers, quantite, materiau=GOUTTIERE, motif="rangement au dépôt"):
    return _outil(m6, "m6_transferer_stock", {
        "transfert_id": transfert_id, "materiau_id": materiau, "quantite": quantite, "de": de, "vers": vers,
        "motif": motif, "horodatage": H_ACTION})


def test_un_transfert_est_audite_et_la_chaine_de_mouvements_ne_bouge_pas_d_un_octet(base, m6):
    _recevoir(m6, GOUTTIERE, 100.0, "PO-DEPOT-1")
    principal_avant = _maillons("principal")
    tete = Registre(maillons=list(principal_avant)).hash_tete()

    premier = _transferer(m6, "T-FICT-1", {"type": "inconnu"}, {"type": "depot"}, 60.0)
    second = _transferer(m6, "T-FICT-2", {"type": "depot"}, {"type": "camion", "reference": "CAM-FICT-1"}, 25.0)

    assert premier["statut"] == "enregistre"
    assert premier["transfert"]["avant"] == {"de": "100", "vers": "0"}
    assert second["transfert"]["apres"] == {"de": "35", "vers": "25"}
    assert second["repartition"] == {"camion:CAM-FICT-1": "25", "depot": "35", "inconnu": "40"}
    transferts = _maillons("emplacements")
    assert [t["transfert_id"] for t in transferts] == ["T-FICT-1", "T-FICT-2"]
    assert (transferts[0]["acteur"], transferts[0]["motif"]) == ("agent", "rangement au dépôt")
    assert emplacements.valider_chaine(transferts) == (True, "")
    assert second["transfert"]["hash_maillon"] == emplacements.hash_tete(transferts)
    # la chaîne de mouvements de stock : mêmes maillons, même tête, toujours valide
    assert _maillons("principal") == principal_avant
    registre = Registre(maillons=_maillons("principal"))
    assert registre.hash_tete() == tete and registre.valider_chaine() == (True, "")


def test_un_transfert_rejoue_n_est_pas_deplace_deux_fois(base, m6):
    _recevoir(m6, GOUTTIERE, 100.0, "PO-DEPOT-1")
    _transferer(m6, "T-FICT-1", {"type": "inconnu"}, {"type": "depot"}, 60.0)

    rejeu = _transferer(m6, "T-FICT-1", {"type": "inconnu"}, {"type": "depot"}, 60.0)
    autre_geste = _outil(m6, "m6_transferer_stock", {
        "transfert_id": "T-FICT-1", "materiau_id": GOUTTIERE, "quantite": 61.0, "de": {"type": "inconnu"},
        "vers": {"type": "depot"}, "motif": "autre", "horodatage": H_ACTION})

    assert rejeu["statut"] == "deja_enregistre" and len(_maillons("emplacements")) == 1
    assert autre_geste["accepte"] is False and autre_geste["verdict"]["code"] == "REJ-TRANSFERT-ID-DEJA-UTILISE"


@pytest.mark.parametrize("arguments, code", [
    ({"quantite": 1000.0}, "REJ-TRANSFERT-STOCK-INSUFFISANT"),
    ({"quantite": -1.0}, "REJ-TRANSFERT-QUANTITE-INVALIDE"),
    ({"motif": ""}, "REJ-TRANSFERT-MOTIF-VIDE"),
    ({"vers": {"type": "garage"}}, "REJ-EMPLACEMENT-INCONNU"),
    ({"vers": {"type": "camion"}}, "REJ-EMPLACEMENT-REFERENCE-MANQUANTE"),
    ({"vers": {"type": "inconnu"}}, "REJ-TRANSFERT-MEME-EMPLACEMENT"),
])
def test_un_transfert_invalide_est_refuse_sans_rien_ecrire(base, m6, arguments, code):
    _recevoir(m6, GOUTTIERE, 100.0, "PO-DEPOT-1")
    complet = {"transfert_id": "T-FICT-1", "materiau_id": GOUTTIERE, "quantite": 10.0, "de": {"type": "inconnu"},
               "vers": {"type": "depot"}, "motif": "rangement", "horodatage": H_ACTION, **arguments}

    reponse = _outil(m6, "m6_transferer_stock", complet)

    assert reponse["accepte"] is False and reponse["verdict"]["code"] == code
    assert _maillons("emplacements") == []


def test_envoyer_du_stock_au_rebut_le_retire_de_l_en_main_et_fait_ceder_la_reservation(base, m6):
    _recevoir(m6, GOUTTIERE, 100.0, "PO-DEPOT-1")
    _accepter(_devis(gouttiere="100", vis=None))
    assert _publies()[-1]["statut"] == "pret"

    reponse = _transferer(m6, "T-REBUT-1", {"type": "inconnu"}, {"type": "rebut"}, 30.0, motif="gouttières bosselées")

    assert len(reponse["evenements_materiel_pret"]) == 1
    dernier = _publies()[-1]
    assert (dernier["statut"], dernier["declencheur"], dernier["lignes"][0]["quantite_reservee"]) == (
        "partiel", "stock_sorti", "70")
    chiffres, _ = _disponibilite(m6, GOUTTIERE)
    assert (chiffres[GOUTTIERE]["stock_theorique"], chiffres[GOUTTIERE]["hors_main"], chiffres[GOUTTIERE]["en_main"],
            chiffres[GOUTTIERE]["reserve"], chiffres[GOUTTIERE]["disponible"]) == ("100", "30", "70", "70", "0")

    retour = _transferer(m6, "T-REBUT-2", {"type": "rebut"}, {"type": "depot"}, 30.0, motif="finalement utilisables")
    assert len(retour["evenements_materiel_pret"]) == 1
    assert _publies()[-1]["statut"] == "pret" and _publies()[-1]["declencheur"] == "stock_recu"


def test_un_transfert_entre_emplacements_en_main_ne_touche_pas_aux_reservations(base, m6):
    _recevoir(m6, GOUTTIERE, 100.0, "PO-DEPOT-1")
    _accepter(_devis(gouttiere="100", vis=None))
    avant = len(_publies())

    reponse = _transferer(m6, "T-FICT-1", {"type": "inconnu"}, {"type": "camion", "reference": "CAM-FICT-1"}, 50.0)

    assert reponse["evenements_materiel_pret"] == [] and len(_publies()) == avant


def test_la_lecture_dit_ou_est_le_stock_et_quelles_reservations_le_retiennent(base, m6):
    _recevoir(m6, GOUTTIERE, 100.0, "PO-DEPOT-1")
    _transferer(m6, "T-FICT-1", {"type": "inconnu"}, {"type": "depot"}, 60.0)
    _accepter(_devis(gouttiere="70", vis="5"))

    chiffres, resultat = _disponibilite(m6, GOUTTIERE, VIS)

    assert chiffres[GOUTTIERE]["par_emplacement"] == {"depot": "60", "inconnu": "40"}
    assert (chiffres[GOUTTIERE]["en_main"], chiffres[GOUTTIERE]["reserve"], chiffres[GOUTTIERE]["disponible"]) == (
        "100", "70", "30")
    assert (chiffres[VIS]["en_main"], chiffres[VIS]["reserve"], chiffres[VIS]["disponible"]) == ("0", "0", "0")
    assert resultat["tronque"] is False
    (reservation,) = resultat["reservations_actives"]
    assert (reservation["devis_id"], reservation["statut"]) == ("DEVIS-FICT-1", "partiel")
    assert [m["materiau_id"] for m in reservation["lignes_manquantes"]] == [VIS]


def test_la_lecture_sans_liste_donne_les_articles_connus_par_pages(base, m6):
    for i in range(17):
        _recevoir(m6, f"article-fictif-{i:02d}", 1.0, f"PO-{i}")

    resultat = _outil(m6, "m6_lire_disponibilite", {})["resultat"]

    assert len(resultat["articles"]) == 15 and resultat["tronque"] is True
    assert [a["materiau_id"] for a in resultat["articles"]] == sorted(a["materiau_id"] for a in resultat["articles"])


# -------------------------------------------------------------------------- le réapprovisionnement
def _configurer_seuils(monkeypatch, tmp_path, articles):
    chemin = tmp_path / "department-m6-seuils.yaml"
    chemin.write_text(yaml.safe_dump({"schema": "opsys.departement/v1", "configuration": {
        "seuil_variance_chantier_pourcentage": 0.3, "reapprovisionnement": {"articles": articles}}},
        allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(m6_outils, "_MANIFESTE", chemin)


def _constats():
    return _maillons("besoins_commande")


def test_le_disponible_alimente_le_reapprovisionnement(base, m6, monkeypatch, tmp_path):
    """200 en main, seuil 150 : sans réservation, 200 - 10 = 190 n'est pas bas. Avec 100 réservés pour un devis,
    le DISPONIBLE (190 - 100 = 90) est sous le seuil : besoin de commande, sur le disponible."""
    _configurer_seuils(monkeypatch, tmp_path, {GOUTTIERE: {"seuil_reapprovisionnement": 150, "quantite_cible": 300}})
    _recevoir(m6, GOUTTIERE, 200.0, "PO-DEPOT-1", chantier_id="CH-AUTRE")
    _accepter(_devis("DEVIS-A", "CH-A", gouttiere="100", vis=None))

    _wct_declare(m6, "WCT-AUTRE", "DEVIS-SANS-RESERVATION", "CH-AUTRE", 10.0)

    (constat,) = _constats()
    assert constat["type_entree"] == "besoin_commande"
    assert (Decimal(constat["stock_theorique"]), Decimal(constat["stock_reserve"]),
            Decimal(constat["stock_disponible"])) == (190, 100, 90)
    assert Decimal(constat["quantite_a_commander"]) == 210, "cible 300 - disponible 90"
    with stockage.transaction():
        (attente,) = m6_outils.attentes()
    assert "réservé" in attente["resume"] and "90" in attente["resume"]


def test_sans_reservation_le_reapprovisionnement_est_celui_d_avant(base, m6, monkeypatch, tmp_path):
    _configurer_seuils(monkeypatch, tmp_path, {GOUTTIERE: {"seuil_reapprovisionnement": 150, "quantite_cible": 300}})
    _recevoir(m6, GOUTTIERE, 200.0, "PO-DEPOT-1", chantier_id="CH-AUTRE")

    _wct_declare(m6, "WCT-AUTRE", "DEVIS-SANS-RESERVATION", "CH-AUTRE", 10.0)

    assert _constats() == [], "190 en main, seuil 150 : pas bas"


def test_les_attentes_de_l_admin_utilisent_le_disponible(base, m6, monkeypatch, tmp_path):
    _configurer_seuils(monkeypatch, tmp_path, {GOUTTIERE: {"seuil_reapprovisionnement": 150, "quantite_cible": 300}})
    _recevoir(m6, GOUTTIERE, 100.0, "PO-DEPOT-1", chantier_id="CH-AUTRE")
    _wct_declare(m6, "WCT-AUTRE", "DEVIS-SANS-RESERVATION", "CH-AUTRE", 5.0)  # 95 en main, sous 150 : besoin
    with stockage.transaction():
        (attente,) = m6_outils.attentes()
    assert "95.0 pi en main, sous le seuil" in attente["resume"] and "réservé" not in attente["resume"]

    _accepter(_devis("DEVIS-A", "CH-A", gouttiere="60", vis=None))
    with stockage.transaction():
        (attente,) = m6_outils.attentes()
    assert "95.0 pi en main dont 60 pi réservé(s)" in attente["resume"] and "35.0 pi disponible(s)" in attente["resume"]
    assert "265.0 pi pour atteindre 300 pi" in attente["resume"], "cible 300 - disponible 35"


# ----------------------------------------------------------------------------- portes et politique
def test_les_quatre_outils_sont_admin_seulement_liberer_et_reserver_sont_n2(m6):
    assert {nom: (m6[nom].autonomie.value, m6[nom].niveau_effectif, sorted(m6[nom].roles_appareil)) for nom in (
        "m6_reserver_materiel", "m6_liberer_reservation", "m6_transferer_stock", "m6_lire_disponibilite")} == {
        "m6_reserver_materiel": ("T1", Niveau.N2, ["admin"]),
        "m6_liberer_reservation": ("T1", Niveau.N2, ["admin"]),
        "m6_transferer_stock": ("T1", Niveau.N3, ["admin"]),
        "m6_lire_disponibilite": ("T0", Niveau.N0, ["admin"]),
    }


@pytest.mark.parametrize("nom, arguments", [
    ("reserver_materiel", {"devis_id": "D", "horodatage": H_ACTION}),
    ("liberer_reservation", {"devis_id": "D", "motif": "m", "horodatage": H_ACTION}),
    ("transferer_stock", {"transfert_id": "T", "materiau_id": GOUTTIERE, "quantite": 1.0, "de": {"type": "inconnu"},
                          "vers": {"type": "depot"}, "motif": "m", "horodatage": H_ACTION}),
    ("lire_disponibilite", {}),
])
def test_hors_transaction_les_quatre_outils_refusent_sans_rien_lire_ni_ecrire(nom, arguments):
    reponse = getattr(m6_outils, nom)(**arguments)
    assert reponse["accepte"] is False and reponse["verdict"]["code"] == "REJ-M6-TRANSACTION-REQUISE"


@pytest.mark.parametrize("nom, arguments", [
    ("reserver_materiel", {"devis_id": "D", "horodatage": H_ACTION}),
    ("liberer_reservation", {"devis_id": "D", "motif": "m", "horodatage": H_ACTION}),
    ("transferer_stock", {"transfert_id": "T", "materiau_id": GOUTTIERE, "quantite": 1.0, "de": {"type": "inconnu"},
                          "vers": {"type": "depot"}, "motif": "m", "horodatage": H_ACTION}),
    ("lire_disponibilite", {}),
])
def test_un_role_d_appareil_autre_qu_admin_est_refuse_dans_le_code_meme_en_lecture(base, monkeypatch, nom, arguments):
    """Le socle n'applique pas `roles_appareil` à un outil T0 hors du core : le code refuse lui aussi l'employé."""
    monkeypatch.setattr(m6_outils, "_declarant_appareil", lambda: (acces.Acteur("etienne", "employee"), None))

    with stockage.transaction():
        reponse = getattr(m6_outils, nom)(**arguments)

    assert reponse["accepte"] is False and reponse["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert _maillons("reservations") == [] and _maillons("emplacements") == []


def test_l_admin_authentifie_est_le_nom_de_l_acteur_de_l_audit(base, monkeypatch):
    monkeypatch.setattr(m6_outils, "_declarant_appareil", lambda: (acces.Acteur("nathan", "admin"), None))
    with stockage.transaction():
        reponse = m6_outils.transferer_stock(
            "T-ADMIN", GOUTTIERE, 0.0001, {"type": "inconnu"}, {"type": "depot"}, "rangement", H_ACTION)
    assert reponse["verdict"]["code"] == "REJ-TRANSFERT-STOCK-INSUFFISANT", "aucun stock : refus, pas d'écriture"

    with stockage.transaction():
        m6_outils.receptionner_commande(
            {"po_id": "PO-1", "chantier_id": "CH", "horodatage": "2026-09-01T00:00:00Z",
             "lignes_demandees": [{"materiau_id": GOUTTIERE, "quantite_demandee": 10.0}]},
            {"po_id": "PO-1", "chantier_id": "CH", "horodatage": H_RECEPTION,
             "lignes_recues": [{"materiau_id": GOUTTIERE, "quantite_recue": 10.0}]})
        reponse = m6_outils.transferer_stock(
            "T-ADMIN-2", GOUTTIERE, 4.0, {"type": "inconnu"}, {"type": "depot"}, "rangement", H_ACTION)

    assert reponse["accepte"] is True
    (maillon,) = _maillons("emplacements")
    assert maillon["acteur"] == "nathan"


def test_l_evenement_est_declare_par_le_departement_et_son_type_est_au_catalogue():
    donnees = yaml.safe_load((m6_outils._MANIFESTE).read_text(encoding="utf-8"))
    assert "m6.materiel_pret" in donnees["evenements"]["publie"]
    assert "m6.materiel_pret" in evenements.types_connus()
    assert reservations.TYPE_EVENEMENT_MATERIEL_PRET == "m6.materiel_pret"


def test_les_disponibilites_utilisent_des_decimaux_exacts(base, m6):
    _recevoir(m6, "scellant", 0.3, "PO-DEPOT-1")
    _accepter({**_devis(gouttiere=None, vis=None), "lignes": [
        {"reference_ligne": "L1", "description": "s", "quantite": "0.1", "unite": "tube", "prix_unitaire": "1.00",
         "prix_ligne": "1.00", "reference_besoin_materiau": "scellant"}]})
    _accepter({**_devis("DEVIS-B", gouttiere=None, vis=None), "lignes": [
        {"reference_ligne": "L1", "description": "s", "quantite": "0.2", "unite": "tube", "prix_unitaire": "1.00",
         "prix_ligne": "1.00", "reference_besoin_materiau": "scellant"}]})

    chiffres, _ = _disponibilite(m6, "scellant")

    assert (chiffres["scellant"]["reserve"], chiffres["scellant"]["disponible"]) == ("0.3", "0")
    assert Decimal(chiffres["scellant"]["disponible"]) == 0
    assert all(c["statut"] == "pret" for c in _publies())
