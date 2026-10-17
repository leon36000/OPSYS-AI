"""PLAN T4.15-b (M6.7) : `m6_receptionner_commande` CUMULE les livraisons d'un PO persisté, sur une base SQLite
réelle et les vrais registres durables de M6.

Le bogue : `reception.py` compare CHAQUE livraison à la commande entière, donc la livraison qui complète un PO déjà
partiel restait `RECEPTION_INFERIEURE` et le PO ne passait jamais à `received`. Ce que ces tests fixent :
- deux livraisons qui complètent le PO, trois livraisons, sur-réception : le statut découle du cumul ;
- l'événement `m6.reception_enregistree` garde sa définition (le verdict de CETTE livraison) et porte le statut cumulé ;
- le rejeu d'une livraison est refusé avant toute écriture (sinon une livraison partielle rejouée ferait passer le PO à
  `received` alors que la moitié seulement est arrivée) ;
- une quantité négative ou non finie est refusée avant toute écriture aussi pour une réception ÉPHÉMÈRE ;
- un PO dont une réception d'avant n'a pas gardé sa livraison ne devine pas son cumul.

Identifiants, fournisseurs et prix fictifs (AGENTS.md).
"""

from __future__ import annotations

import math
from decimal import Decimal

import m6_material_control.outils as m6_outils
import pytest
from m6_material_control import bons_commande, reservations
from m6_material_control.registre import Registre
from sqlalchemy import select

from opsys import stockage
from opsys.evenements.schemas import erreurs_charge
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS, META

FICTIF = True
_DEPARTEMENT = "m06-material-control"
TYPE = "m6.reception_enregistree"
H1 = "2026-09-29T09:15:00-04:00"
H2 = "2026-10-06T14:30:00-04:00"
H3 = "2026-10-13T10:00:00-04:00"


@pytest.fixture
def base(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-m6-cumul.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    try:
        yield url
    finally:
        stockage.liberer()


def _outil(nom):
    return next(o for o in m6_outils.outils() if o.nom == nom)


def _reception(gouttiere, vis, horodatage, po_id="PO-FICT-1", chantier_id="CH-FICT-1"):
    return {"po_id": po_id, "chantier_id": chantier_id, "horodatage": horodatage,
            "lignes_recues": [{"materiau_id": "gouttiere-5po", "quantite_recue": gouttiere},
                              {"materiau_id": "vis-inox", "quantite_recue": vis}]}


def _bon_demande(po_id="PO-FICT-1", chantier_id="CH-FICT-1", gouttiere=100.0, vis=20.0):
    return {"po_id": po_id, "chantier_id": chantier_id,
            "lignes_demandees": [{"materiau_id": "gouttiere-5po", "quantite_demandee": gouttiere},
                                 {"materiau_id": "vis-inox", "quantite_demandee": vis}],
            "horodatage": "2026-09-01T08:00:00-04:00"}


def _po_envoye(po_id="PO-FICT-1", devis_id="DEVIS-FICT-1", chantier_id="CH-FICT-1", gouttiere=100.0, vis=20.0):
    """Un PO persisté jusqu'à `sent_to_supplier` : 100 gouttières à 8,50 $ et 20 vis à 0,35 $ par défaut, chez
    Gentek."""
    with stockage.transaction():
        for reponse in (
            m6_outils.enregistrer_fournisseur("gentek", "Gentek", "2026-01-01T00:00:00Z",
                                              courriel_commande="commandes@gentek.exemple-fictif.test"),
            m6_outils.enregistrer_prix("gouttiere-5po", "gentek", 8.5, "CAD", "2026-01-01"),
            m6_outils.enregistrer_prix("vis-inox", "gentek", 0.35, "CAD", "2026-01-01"),
            m6_outils.enregistrer_besoins_prevus(chantier_id, devis_id, [
                {"materiau_id": "gouttiere-5po", "quantite_estimee": gouttiere, "unite": "pi"},
                {"materiau_id": "vis-inox", "quantite_estimee": vis, "unite": "boite"}]),
            m6_outils.creer_po_brouillon(po_id, devis_id, "gentek", "2026-09-01T08:00:00-04:00"),
            m6_outils.approuver_po(po_id, "2026-09-01T09:00:00-04:00"),
            m6_outils.generer_courriel_po(po_id, "2026-09-01T10:00:00-04:00", "Entreprise Fictive"),
            m6_outils.marquer_po_envoye(po_id, "2026-09-01T11:00:00-04:00"),
        ):
            assert reponse["accepte"] is True, reponse
    return po_id


def _catalogue():
    return {"version": "v1", "unite_monetaire": "CAD",
            "postes": {"gouttiere-5po": {"cout_unitaire": 8.5, "libelle": "Gouttière 5 po"},
                       "vis-inox": {"cout_unitaire": 0.35, "libelle": "Vis inox"}}}


def _recevoir(gouttiere, vis, horodatage, bon_demande=None):
    reponse = executer_atomique(_outil("m6_receptionner_commande"), {
        "bon_demande": bon_demande or _bon_demande(),
        "reception_po": _reception(gouttiere, vis, horodatage),
        "catalogue_materiaux": _catalogue()})
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _publies():
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS).where(
            EVENEMENTS_SORTANTS.c.type_evenement == TYPE)).mappings().all()
    return [codec.decoder(ligne["charge"]) for ligne in lignes]


def _maillons(nom):
    with stockage.transaction():
        return list(stockage.maillons(_DEPARTEMENT, nom))


def _po(po_id="PO-FICT-1"):
    with stockage.transaction():
        return bons_commande.lire(stockage.maillons(_DEPARTEMENT, "bons_commande"), po_id)


# ------------------------------------------------------------------------------ le bogue, puis la règle
def test_deux_livraisons_qui_completent_le_po_le_font_passer_a_received(base):
    _po_envoye()

    premiere = _recevoir(40.0, 0.0, H1)
    seconde = _recevoir(60.0, 20.0, H2)

    assert premiere["accepte"] and seconde["accepte"], (premiere, seconde)
    assert premiere["po"]["statut"] == "partially_received"
    assert premiere["reception_cumulee"]["verdict_reception"] == "RECEPTION_INFERIEURE"
    # le bogue : la seconde livraison, seule contre la commande entière, reste inférieure ; le PO est pourtant reçu
    assert seconde["resultat"]["accuse_reception"]["verdict_reception"] == "RECEPTION_INFERIEURE"
    assert seconde["po"]["statut"] == "received"
    assert seconde["po"]["verdict_reception"] == "CONFORME"
    assert seconde["reception_cumulee"]["fiable"] is True
    assert seconde["reception_cumulee"]["verdict_reception"] == "CONFORME"
    assert [(ligne["materiau_id"], ligne["quantite_recue_cumulee"], ligne["ecart_cumule"])
            for ligne in seconde["reception_cumulee"]["lignes"]] == [
        ("gouttiere-5po", "100.0", "0.0"), ("vis-inox", "20.0", "0.0")]
    assert _po()["statut"] == "received"


def test_l_evenement_garde_sa_definition_verdict_de_la_livraison_et_statut_cumule(base):
    """`verdict_reception` reste celui de CETTE livraison contre la commande entière, comme le schéma du catalogue le
    dit ; `statut_po` porte le cumul. La charge reste conforme au schéma, sans clé de plus."""
    _po_envoye()
    _recevoir(40.0, 0.0, H1)

    seconde = _recevoir(60.0, 20.0, H2)

    premiere_charge, seconde_charge = _publies()
    assert erreurs_charge(TYPE, seconde_charge) == []
    assert (premiere_charge["verdict_reception"], premiere_charge["statut_po"]) == (
        "RECEPTION_INFERIEURE", "partially_received")
    assert (seconde_charge["verdict_reception"], seconde_charge["statut_po"]) == ("RECEPTION_INFERIEURE", "received")
    assert [ligne["quantite_recue"] for ligne in seconde_charge["lignes"]] == ["60.0", "20.0"], "SA livraison"
    assert seconde["evenement_reception_id"] == seconde_charge["evenement_id"]
    assert set(seconde_charge) == set(premiere_charge), "le schéma n'a pas changé"


def test_trois_livraisons_le_po_n_est_recu_qu_a_la_derniere(base):
    _po_envoye()

    une = _recevoir(40.0, 0.0, H1)
    deux = _recevoir(30.0, 10.0, H2)
    trois = _recevoir(30.0, 10.0, H3)

    assert [r["po"]["statut"] for r in (une, deux, trois)] == ["partially_received", "partially_received", "received"]
    assert [r["reception_cumulee"]["verdict_reception"] for r in (une, deux, trois)] == [
        "RECEPTION_INFERIEURE", "RECEPTION_INFERIEURE", "CONFORME"]
    assert [ligne["quantite_recue_cumulee"] for ligne in deux["reception_cumulee"]["lignes"]] == ["70.0", "10.0"]
    assert len(_publies()) == 3
    assert len(_maillons("principal")) == 6, "deux lignes de stock par livraison"


def test_une_sur_reception_cumulee_recoit_le_po(base):
    _po_envoye()
    _recevoir(60.0, 20.0, H1)

    seconde = _recevoir(60.0, 0.0, H2)

    assert seconde["reception_cumulee"]["verdict_reception"] == "RECEPTION_SUPERIEURE"
    assert seconde["po"]["statut"] == "received"
    assert seconde["po"]["verdict_reception"] == "RECEPTION_SUPERIEURE"
    assert [ligne["ecart_cumule"] for ligne in seconde["reception_cumulee"]["lignes"]] == ["20.0", "0.0"]


def test_une_ligne_qui_manque_garde_le_po_partiel_meme_si_l_autre_est_en_exces(base):
    _po_envoye()
    _recevoir(70.0, 0.0, H1)

    seconde = _recevoir(50.0, 0.0, H2)

    assert seconde["reception_cumulee"]["verdict_reception"] == "RECEPTION_MIXTE"
    assert seconde["po"]["statut"] == "partially_received"


def test_le_cumul_est_exact_en_decimal(base):
    """Un PO de 0,3 scellant reçu en 0,1 puis 0,2 : 0,1 + 0,2 vaut 0,30000000000000004 en flottant. Le PO doit être
    reçu, pas dépassé ni resté partiel."""
    with stockage.transaction():
        for reponse in (
            m6_outils.enregistrer_fournisseur("gentek", "Gentek", "2026-01-01T00:00:00Z"),
            m6_outils.enregistrer_prix("scellant", "gentek", 12.0, "CAD", "2026-01-01"),
            m6_outils.enregistrer_besoins_prevus("CH-FICT-1", "DEVIS-FICT-1", [
                {"materiau_id": "scellant", "quantite_estimee": 0.3, "unite": "tube"}]),
            m6_outils.creer_po_brouillon("PO-FICT-1", "DEVIS-FICT-1", "gentek", "2026-09-01T08:00:00-04:00"),
            m6_outils.approuver_po("PO-FICT-1", "2026-09-01T09:00:00-04:00"),
            m6_outils.generer_courriel_po("PO-FICT-1", "2026-09-01T10:00:00-04:00", "Entreprise Fictive"),
            m6_outils.marquer_po_envoye("PO-FICT-1", "2026-09-01T11:00:00-04:00"),
        ):
            assert reponse["accepte"] is True, reponse
    bon = {"po_id": "PO-FICT-1", "chantier_id": "CH-FICT-1", "horodatage": "2026-09-01T08:00:00-04:00",
           "lignes_demandees": [{"materiau_id": "scellant", "quantite_demandee": 0.3}]}

    def _livrer(quantite, horodatage):
        reponse = executer_atomique(_outil("m6_receptionner_commande"), {
            "bon_demande": bon, "reception_po": {
                "po_id": "PO-FICT-1", "chantier_id": "CH-FICT-1", "horodatage": horodatage,
                "lignes_recues": [{"materiau_id": "scellant", "quantite_recue": quantite}]}})
        assert reponse["resultat"]["accepte"] is True, reponse
        return reponse["resultat"]

    assert _livrer(0.1, H1)["po"]["statut"] == "partially_received"
    finale = _livrer(0.2, H2)

    assert finale["reception_cumulee"]["verdict_reception"] == "CONFORME"
    assert finale["po"]["statut"] == "received"


# ------------------------------------------------------------------------------------------------ rejeu
def test_rejouer_une_livraison_est_refuse_avant_toute_ecriture(base):
    _po_envoye()
    _recevoir(40.0, 0.0, H1)
    stock_avant = _maillons("principal")
    po_avant = _po()

    rejeu = _recevoir(40.0, 0.0, H1)

    assert rejeu["accepte"] is False
    assert rejeu["verdict"]["code"] == "REJ-RECEPTION-DEJA-ENREGISTREE"
    assert H1 in rejeu["verdict"]["detail"]
    assert _maillons("principal") == stock_avant, "aucun mouvement de stock de plus"
    assert _po() == po_avant and len(_publies()) == 1


def test_le_rejeu_d_une_livraison_partielle_ne_fait_jamais_passer_le_po_a_received(base):
    """Le piège de l'addition : 50 + 50 = 100, donc un rejeu de la moitié d'un PO de 100 le ferait passer à
    `received` alors que la moitié seulement est arrivée."""
    with stockage.transaction():
        for reponse in (
            m6_outils.enregistrer_fournisseur("gentek", "Gentek", "2026-01-01T00:00:00Z"),
            m6_outils.enregistrer_prix("gouttiere-5po", "gentek", 8.5, "CAD", "2026-01-01"),
            m6_outils.enregistrer_besoins_prevus("CH-FICT-1", "DEVIS-FICT-1", [
                {"materiau_id": "gouttiere-5po", "quantite_estimee": 100.0, "unite": "pi"}]),
            m6_outils.creer_po_brouillon("PO-FICT-1", "DEVIS-FICT-1", "gentek", "2026-09-01T08:00:00-04:00"),
            m6_outils.approuver_po("PO-FICT-1", "2026-09-01T09:00:00-04:00"),
            m6_outils.generer_courriel_po("PO-FICT-1", "2026-09-01T10:00:00-04:00", "Entreprise Fictive"),
            m6_outils.marquer_po_envoye("PO-FICT-1", "2026-09-01T11:00:00-04:00"),
        ):
            assert reponse["accepte"] is True, reponse
    bon = {"po_id": "PO-FICT-1", "chantier_id": "CH-FICT-1", "horodatage": "2026-09-01T08:00:00-04:00",
           "lignes_demandees": [{"materiau_id": "gouttiere-5po", "quantite_demandee": 100.0}]}

    def _moitie():
        return executer_atomique(_outil("m6_receptionner_commande"), {
            "bon_demande": bon, "reception_po": {
                "po_id": "PO-FICT-1", "chantier_id": "CH-FICT-1", "horodatage": H1,
                "lignes_recues": [{"materiau_id": "gouttiere-5po", "quantite_recue": 50.0}]}})["resultat"]

    assert _moitie()["po"]["statut"] == "partially_received"
    rejeu = _moitie()

    assert rejeu["accepte"] is False and rejeu["verdict"]["code"] == "REJ-RECEPTION-DEJA-ENREGISTREE"
    assert _po()["statut"] == "partially_received"
    assert len(_maillons("principal")) == 1


def test_meme_quantites_a_un_autre_horodatage_est_une_autre_livraison(base):
    """Deux livraisons distinctes qui apportent les mêmes quantités ne sont pas un rejeu : l'horodatage les
    distingue."""
    _po_envoye()
    _recevoir(40.0, 5.0, H1)

    autre = _recevoir(40.0, 5.0, H2)

    assert autre["accepte"] is True
    assert [ligne["quantite_recue_cumulee"] for ligne in autre["reception_cumulee"]["lignes"]] == ["80.0", "10.0"]


def test_un_po_recu_completement_ne_recoit_plus(base):
    _po_envoye()
    _recevoir(100.0, 20.0, H1)

    apres = _recevoir(1.0, 0.0, H2)

    assert apres["accepte"] is False and apres["verdict"]["code"] == "REJ-PO-TRANSITION-ILLEGALE"
    assert len(_publies()) == 1


# ----------------------------------------------------------------------- réception éphémère : quantités
@pytest.mark.parametrize("quantite", [-1.0, -0.001, math.nan, math.inf, -math.inf, True, "40"])
def test_une_quantite_invalide_est_refusee_avant_toute_ecriture_aussi_pour_une_reception_ephemere(base, quantite):
    """Aucun PO persisté : `PO-EPHEMERE` n'est connu de personne. Avant T4.15-b, la quantité négative entrait au
    stock."""
    reponse = executer_atomique(_outil("m6_receptionner_commande"), {
        "bon_demande": _bon_demande(po_id="PO-EPHEMERE"),
        "reception_po": _reception(quantite, 0.0, H1, po_id="PO-EPHEMERE"),
        "catalogue_materiaux": _catalogue()})

    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-RECEPTION-QUANTITE-INVALIDE"
    assert _maillons("principal") == [], "rien n'est écrit au stock"
    assert _publies() == []


def test_une_quantite_invalide_est_refusee_hors_transaction_pour_une_reception_ephemere():
    """Appel direct (aucune base) : le même refus, avant toute écriture au registre en mémoire."""
    reponse = m6_outils.receptionner_commande(
        _bon_demande(po_id="PO-EPHEMERE"), _reception(-5.0, 0.0, H1, po_id="PO-EPHEMERE"),
        catalogue_materiaux=_catalogue())

    assert reponse["accepte"] is False
    assert reponse["verdict"]["code"] == "REJ-RECEPTION-QUANTITE-INVALIDE"
    assert "registre_historique" not in reponse


def test_une_reception_ephemere_valide_se_comporte_comme_avant(base):
    reponse = executer_atomique(_outil("m6_receptionner_commande"), {
        "bon_demande": _bon_demande(po_id="PO-EPHEMERE"),
        "reception_po": _reception(40.0, 0.0, "2026-09-29", po_id="PO-EPHEMERE"),
        "catalogue_materiaux": _catalogue()})

    assert reponse["resultat"]["accepte"] is True
    assert "po" not in reponse["resultat"] and "reception_cumulee" not in reponse["resultat"]
    assert len(_maillons("principal")) == 2, "l'horodatage sans fuseau reste permis hors PO persisté"


def test_une_reception_ephemere_rejouee_n_est_pas_refusee_comme_avant(base):
    """Le refus du rejeu ne vaut que pour un PO persisté (P5 : additif). Une réception éphémère n'a pas de
    cumul à protéger."""
    for _ in range(2):
        reponse = executer_atomique(_outil("m6_receptionner_commande"), {
            "bon_demande": _bon_demande(po_id="PO-EPHEMERE"),
            "reception_po": _reception(40.0, 0.0, H1, po_id="PO-EPHEMERE"),
            "catalogue_materiaux": _catalogue()})
        assert reponse["resultat"]["accepte"] is True
    assert len(_maillons("principal")) == 4


# ----------------------------------------------------------------------- PO d'avant : cumul inconnu
def test_un_po_dont_une_reception_d_avant_n_a_pas_de_detail_ne_devine_pas_son_cumul(base):
    """Une réception enregistrée avant T4.15-b n'a pas gardé sa livraison (le stock ne porte pas le `po_id`) : ses
    quantités sont introuvables. La livraison suivante ne peut pas affirmer que le PO est complet : le verdict reste
    celui de cette livraison, et le cumul se dit non fiable."""
    _po_envoye()
    with stockage.transaction():
        registre_po = stockage.maillons(_DEPARTEMENT, "bons_commande")
        registre_po.append({"type_entree": "transition_po", "po_id": "PO-FICT-1", "statut": "partially_received",
                            "horodatage": H1, "verdict_reception": "RECEPTION_INFERIEURE"})

    seconde = _recevoir(60.0, 20.0, H2)

    assert seconde["accepte"] is True
    assert seconde["po"]["statut"] == "partially_received"
    assert seconde["reception_cumulee"]["fiable"] is False
    assert "sans détail" in seconde["reception_cumulee"]["raison"]
    assert seconde["reception_cumulee"]["verdict_reception"] == "RECEPTION_INFERIEURE"


def test_un_po_d_avant_recoit_encore_une_livraison_qui_couvre_tout(base):
    _po_envoye()
    with stockage.transaction():
        stockage.maillons(_DEPARTEMENT, "bons_commande").append(
            {"type_entree": "transition_po", "po_id": "PO-FICT-1", "statut": "partially_received",
             "horodatage": H1, "verdict_reception": "RECEPTION_INFERIEURE"})

    complete = _recevoir(100.0, 20.0, H2)

    assert complete["po"]["statut"] == "received"
    assert complete["reception_cumulee"]["fiable"] is False


# --------------------------------------------------------- deux devis réservent, trois livraisons, réouverture
def _accepter_devis(devis_id, chantier_id, gouttiere, vis):
    """`m3.devis_accepte` fictif, par le consommateur de M6 : sans stock, la réservation naît `a_commander`."""
    lignes = [{"reference_ligne": f"{devis_id}-L{i}", "description": "ligne fictive", "quantite": quantite,
               "unite": unite, "prix_unitaire": "10.00", "prix_ligne": "10.00", "reference_besoin_materiau": materiau}
              for i, (materiau, quantite, unite) in enumerate([("gouttiere-5po", gouttiere, "pi"),
                                                               ("vis-inox", vis, "boite")])]
    with stockage.transaction():
        reponse = m6_outils._recevoir_devis_accepte({
            "devis_id": devis_id, "lead_id": "lead-fictif", "chantier_id": chantier_id, "lignes": lignes,
            "cout_total": "100.00", "prix_total": "135.00", "taux_marge": "0.35",
            "horodatage_acceptation": "2026-09-15T10:00:00-04:00"})
    assert reponse["reservation"]["statut"] == "creee", reponse


def _instantane_complet():
    """Toutes les lignes de toutes les tables de l'instance, relues par une connexion NEUVE (moteurs libérés)."""
    stockage.liberer()
    with stockage.transaction() as cnx:
        return {table.name: sorted(repr(tuple(ligne)) for ligne in cnx.execute(select(table)))
                for table in META.sorted_tables}


def test_trois_livraisons_et_deux_reservations_se_conservent_apres_reouverture(base):
    """M6-R1 : PO de 10 gouttières et 6 vis livré 3/1, 4/2 puis 3/3 ; deux devis acceptés avant (A : 6/4, plus
    ancien ; B : 5/3) se complètent du plus ancien au plus récent, jamais au-delà de l'en main. Entre deux
    livraisons, un rejeu et une ligne invalide en SECONDE position sont refusés sans rien écrire. Relu par une
    connexion neuve : cumul, livraisons, réservations, événements et chaîne de stock sont exacts."""
    _po_envoye(gouttiere=10.0, vis=6.0)
    _accepter_devis("DEVIS-A-FICT", "CH-A-FICT", "6", "4")
    _accepter_devis("DEVIS-B-FICT", "CH-B-FICT", "5", "3")
    bon = _bon_demande(gouttiere=10.0, vis=6.0)

    une = _recevoir(3.0, 1.0, H1, bon_demande=bon)
    deux = _recevoir(4.0, 2.0, H2, bon_demande=bon)
    avant_refus = _instantane_complet()
    rejeu = _recevoir(3.0, 1.0, H1, bon_demande=bon)
    invalide = executer_atomique(_outil("m6_receptionner_commande"), {
        "bon_demande": bon, "reception_po": _reception(3.0, -1.0, H3), "catalogue_materiaux": _catalogue()})
    assert _instantane_complet() == avant_refus, "deux refus : aucune table ne bouge"
    trois = _recevoir(3.0, 3.0, H3, bon_demande=bon)

    assert (rejeu["accepte"], rejeu["verdict"]["code"]) == (False, "REJ-RECEPTION-DEJA-ENREGISTREE")
    assert invalide["ok"] is True and invalide["resultat"]["accepte"] is False
    assert invalide["resultat"]["verdict"]["code"] == "REJ-RECEPTION-QUANTITE-INVALIDE"
    assert [r["po"]["statut"] for r in (une, deux, trois)] == ["partially_received", "partially_received", "received"]
    assert [r["evenements_materiel_pret"] for r in (une, deux, trois)] == [
        ["m6-materiel-pret-DEVIS-A-FICT-2"],
        ["m6-materiel-pret-DEVIS-A-FICT-3", "m6-materiel-pret-DEVIS-B-FICT-2"],
        ["m6-materiel-pret-DEVIS-A-FICT-4", "m6-materiel-pret-DEVIS-B-FICT-3"]]

    stockage.liberer()
    with stockage.transaction():
        principal = list(stockage.maillons(_DEPARTEMENT, "principal"))
        chaine = Registre(maillons=stockage.maillons(_DEPARTEMENT, "principal")).valider_chaine()
        registre_po = list(stockage.maillons(_DEPARTEMENT, "bons_commande"))
        faits = list(stockage.maillons(_DEPARTEMENT, "reservations"))
    assert chaine == (True, "") and len(principal) == 6
    # Calcul indépendant : 3 + 4 + 3 = 10 gouttières, 1 + 2 + 3 = 6 vis.
    entre = {}
    for maillon in principal:
        materiau_id = maillon["materiau_id"]
        entre[materiau_id] = entre.get(materiau_id, Decimal(0)) + Decimal(str(maillon["quantite"]))
    assert entre == {"gouttiere-5po": Decimal(10), "vis-inox": Decimal(6)}
    livrees = [[Decimal(ligne["quantite_recue"]) for ligne in livraison["lignes"]]
               for livraison in bons_commande.livraisons(registre_po, "PO-FICT-1")]
    assert livrees == [[3, 1], [4, 2], [3, 3]], "chaque livraison garde la sienne, jamais le cumul"
    assert bons_commande.lire(registre_po, "PO-FICT-1")["statut"] == "received"
    # Chaque événement porte SA livraison et le hash du dernier mouvement de stock qu'elle a écrit.
    charges = _publies()
    assert [[Decimal(ligne["quantite_recue"]) for ligne in c["lignes"]] for c in charges] == livrees
    assert [c["statut_po"] for c in charges] == ["partially_received", "partially_received", "received"]
    assert [c["hash_maillon"] for c in charges] == [principal[i]["hash_maillon"] for i in (1, 3, 5)]
    assert all(erreurs_charge(TYPE, c) == [] for c in charges)
    # Plus anciens d'abord : A (6/4) complet, B (5/3) reçoit le reste, 4/2.
    etats = {devis: reservations.etat(devis, faits) for devis in ("DEVIS-A-FICT", "DEVIS-B-FICT")}
    assert {devis: (e["revision"], [Decimal(ligne["quantite_reservee"]) for ligne in e["lignes"]])
            for devis, e in etats.items()} == {"DEVIS-A-FICT": (4, [6, 4]), "DEVIS-B-FICT": (3, [4, 2])}
    assert [reservations.statut_pret(e["lignes"]) for e in etats.values()] == ["pret", "partiel"]
    lecture = executer_atomique(_outil("m6_lire_disponibilite"), {"materiau_ids": ["gouttiere-5po", "vis-inox"]})
    chiffres = {a["materiau_id"]: tuple(Decimal(a[cle]) for cle in ("en_main", "reserve", "disponible"))
                for a in lecture["resultat"]["resultat"]["articles"]}
    assert chiffres == {"gouttiere-5po": (10, 10, 0), "vis-inox": (6, 6, 0)}


# --------------------------------------------------------------------------------- rien n'apparie
def test_une_livraison_qui_n_apparie_rien_n_ecrit_rien_et_ne_range_aucune_livraison(base):
    _po_envoye()
    reception_autre_chantier = _reception(40.0, 0.0, H1, chantier_id="CH-AUTRE")

    reponse = executer_atomique(_outil("m6_receptionner_commande"), {
        "bon_demande": _bon_demande(), "reception_po": reception_autre_chantier, "catalogue_materiaux": _catalogue()})

    assert reponse["resultat"]["accepte"] is True
    assert reponse["resultat"]["reception_cumulee"]["fiable"] is None
    assert reponse["resultat"]["po"]["statut"] == "sent_to_supplier"
    with stockage.transaction():
        assert bons_commande.livraisons(stockage.maillons(_DEPARTEMENT, "bons_commande"), "PO-FICT-1") == []
    assert _maillons("principal") == [] and _publies() == []


# ------------------------------------------------------------------------------ hors transaction
def test_hors_transaction_deux_livraisons_completent_le_po_en_memoire():
    """Appel direct des fonctions, sans base : les historiques en mémoire se retransmettent comme avant, et le
    cumul s'y lit aussi."""
    fh = m6_outils.enregistrer_fournisseur("gentek", "Gentek", "2026-01-01T00:00:00Z")["fournisseurs_historique"]
    lph = m6_outils.enregistrer_prix("gouttiere-5po", "gentek", 8.5, "CAD", "2026-01-01")["livre_prix_historique"]
    lph = m6_outils.enregistrer_prix("vis-inox", "gentek", 0.35, "CAD", "2026-01-01",
                                     livre_prix_historique=lph)["livre_prix_historique"]
    bh = m6_outils.enregistrer_besoins_prevus("CH-FICT-1", "DEVIS-FICT-1", [
        {"materiau_id": "gouttiere-5po", "quantite_estimee": 100.0, "unite": "pi"},
        {"materiau_id": "vis-inox", "quantite_estimee": 20.0, "unite": "boite"}])["registre_historique"]
    bch = m6_outils.creer_po_brouillon(
        "PO-FICT-1", "DEVIS-FICT-1", "gentek", "2026-09-01T08:00:00-04:00",
        besoins_prevus_historique=bh, livre_prix_historique=lph, fournisseurs_historique=fh)["bons_commande_historique"]
    for etape in (lambda h: m6_outils.approuver_po("PO-FICT-1", "2026-09-01T09:00:00-04:00",
                                                   bons_commande_historique=h),
                  lambda h: m6_outils.generer_courriel_po("PO-FICT-1", "2026-09-01T10:00:00-04:00", "Entreprise",
                                                          fournisseurs_historique=fh, bons_commande_historique=h),
                  lambda h: m6_outils.marquer_po_envoye("PO-FICT-1", "2026-09-01T11:00:00-04:00",
                                                        bons_commande_historique=h)):
        bch = etape(bch)["bons_commande_historique"]

    premiere = m6_outils.receptionner_commande(
        _bon_demande(), _reception(40.0, 0.0, H1), catalogue_materiaux=_catalogue(), bons_commande_historique=bch)
    seconde = m6_outils.receptionner_commande(
        _bon_demande(), _reception(60.0, 20.0, H2), catalogue_materiaux=_catalogue(),
        registre_historique=premiere["registre_historique"],
        bons_commande_historique=premiere["bons_commande_historique"])
    rejeu = m6_outils.receptionner_commande(
        _bon_demande(), _reception(60.0, 20.0, H2), catalogue_materiaux=_catalogue(),
        registre_historique=seconde["registre_historique"],
        bons_commande_historique=seconde["bons_commande_historique"])

    assert premiere["po"]["statut"] == "partially_received"
    assert seconde["po"]["statut"] == "received" and seconde["reception_cumulee"]["verdict_reception"] == "CONFORME"
    assert rejeu["accepte"] is False and rejeu["verdict"]["code"] in (
        "REJ-PO-TRANSITION-ILLEGALE", "REJ-RECEPTION-DEJA-ENREGISTREE")
