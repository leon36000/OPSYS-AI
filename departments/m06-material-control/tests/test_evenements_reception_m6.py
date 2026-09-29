"""PLAN T4.15 (M6.16) : `m6_receptionner_commande` publie `m6.reception_enregistree` dans LA MÊME transaction
que la réception, sur une base SQLite réelle et les vrais registres durables de M6 (fournisseurs, livre de prix,
besoins prévus, bons de commande, stock).

Ce que ces tests fixent :
- un événement par réception d'un PO PERSISTÉ, et un seul : deux livraisons du même PO, deux identifiants ;
- l'atomicité : si la publication échoue, ni le stock ni la transition du PO ne restent écrits ;
- rien n'est publié pour une réception « éphémère » (aucun PO persisté, donc aucun fournisseur) ni pour une
  réception qui n'apparie aucune ligne ;
- une quantité négative ou un horodatage sans fuseau est refusé AVANT toute écriture au stock ;
- aucune unité n'est inventée ni convertie, aucun montant n'est calculé par M6.

Identifiants, fournisseurs et prix fictifs (AGENTS.md).
"""

from __future__ import annotations

import math

import m6_material_control.outils as m6_outils
import pytest
from sqlalchemy import select

from opsys import stockage
from opsys.evenements.schemas import erreurs_charge
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS

FICTIF = True
_DEPARTEMENT = "m06-material-control"
TYPE = "m6.reception_enregistree"
HORODATAGE_RECEPTION_1 = "2026-09-29T09:15:00-04:00"
HORODATAGE_RECEPTION_2 = "2026-10-06T14:30:00-04:00"


@pytest.fixture
def base(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys-m6-reception.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    try:
        yield url
    finally:
        stockage.liberer()


def _outil(nom):
    return next(o for o in m6_outils.outils() if o.nom == nom)


def _reception(po_id="PO-FICT-1", chantier_id="CH-FICT-1", gouttiere=40.0, vis=0.0, horodatage=HORODATAGE_RECEPTION_1):
    return {"po_id": po_id, "chantier_id": chantier_id, "horodatage": horodatage,
            "lignes_recues": [{"materiau_id": "gouttiere-5po", "quantite_recue": gouttiere},
                              {"materiau_id": "vis-inox", "quantite_recue": vis}]}


def _bon_demande(po_id="PO-FICT-1", chantier_id="CH-FICT-1"):
    return {"po_id": po_id, "chantier_id": chantier_id,
            "lignes_demandees": [{"materiau_id": "gouttiere-5po", "quantite_demandee": 100.0},
                                 {"materiau_id": "vis-inox", "quantite_demandee": 20.0}],
            "horodatage": "2026-09-01T08:00:00-04:00"}


def _po_envoye(po_id="PO-FICT-1", devis_id="DEVIS-FICT-1", chantier_id="CH-FICT-1", prix_vis=0.35):
    """Un PO persisté jusqu'à `sent_to_supplier` : 100 gouttières à 8,50 $ et 20 vis à 0,35 $, chez Gentek."""
    with stockage.transaction():
        for reponse in (
            m6_outils.enregistrer_fournisseur("gentek", "Gentek", "2026-01-01T00:00:00Z",
                                              courriel_commande="commandes@gentek.exemple-fictif.test"),
            m6_outils.enregistrer_prix("gouttiere-5po", "gentek", 8.5, "CAD", "2026-01-01"),
            m6_outils.enregistrer_prix("vis-inox", "gentek", prix_vis, "CAD", "2026-01-01"),
            m6_outils.enregistrer_besoins_prevus(chantier_id, devis_id, [
                {"materiau_id": "gouttiere-5po", "quantite_estimee": 100.0, "unite": "pi"},
                {"materiau_id": "vis-inox", "quantite_estimee": 20.0, "unite": "boite"}]),
            m6_outils.creer_po_brouillon(po_id, devis_id, "gentek", "2026-09-01T08:00:00-04:00"),
            m6_outils.approuver_po(po_id, "2026-09-01T09:00:00-04:00"),
            m6_outils.generer_courriel_po(po_id, "2026-09-01T10:00:00-04:00", "Entreprise Fictive"),
            m6_outils.marquer_po_envoye(po_id, "2026-09-01T11:00:00-04:00"),
        ):
            assert reponse["accepte"] is True, reponse
    return po_id


def _receptionner(reception, bon_demande=None, catalogue=None):
    arguments = {"bon_demande": bon_demande or _bon_demande(), "reception_po": reception}
    if catalogue is not None:
        arguments["catalogue_materiaux"] = catalogue
    return executer_atomique(_outil("m6_receptionner_commande"), arguments)


def _catalogue(gouttiere=8.5, vis=0.35):
    return {"version": "v1", "unite_monetaire": "CAD",
            "postes": {"gouttiere-5po": {"cout_unitaire": gouttiere, "libelle": "Gouttière 5 po"},
                       "vis-inox": {"cout_unitaire": vis, "libelle": "Vis inox"}}}


def _publies():
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS).where(
            EVENEMENTS_SORTANTS.c.type_evenement == TYPE)).mappings().all()
    return [(ligne["evenement_id"], ligne["producteur"], codec.decoder(ligne["charge"])) for ligne in lignes]


def _maillons(nom):
    with stockage.transaction():
        return list(stockage.maillons(_DEPARTEMENT, nom))


def _statut_po(po_id="PO-FICT-1"):
    with stockage.transaction():
        from m6_material_control import bons_commande
        return bons_commande.lire(stockage.maillons(_DEPARTEMENT, "bons_commande"), po_id)["statut"]


# -- nominal -----------------------------------------------------------------------------------------------
def test_une_reception_partielle_publie_un_evenement_dans_la_transaction_de_la_reception(base):
    _po_envoye()

    reponse = _receptionner(_reception(gouttiere=40.0, vis=0.0), catalogue=_catalogue())

    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    assert reponse["resultat"]["po"]["statut"] == "partially_received"
    ((evenement_id, producteur, charge),) = _publies()
    assert producteur == "m06-material-control"
    assert reponse["resultat"]["evenement_reception_id"] == evenement_id == charge["evenement_id"]
    assert erreurs_charge(TYPE, charge) == []
    assert (charge["po_id"], charge["fournisseur_id"], charge["chantier_id"]) == ("PO-FICT-1", "gentek", "CH-FICT-1")
    assert (charge["verdict_reception"], charge["statut_po"]) == ("RECEPTION_INFERIEURE", "partially_received")
    assert charge["horodatage_reception"] == HORODATAGE_RECEPTION_1
    gouttiere, vis = charge["lignes"]
    assert (gouttiere["quantite_demandee"], gouttiere["quantite_recue"]) == ("100.0", "40.0")
    assert (gouttiere["prix_unitaire_prevu"], gouttiere["prix_unitaire_reception"]) == ("8.5", "8.5")
    assert (vis["quantite_recue"], vis["prix_unitaire_prevu"]) == ("0.0", "0.35")
    # le hash du dernier mouvement de stock de CETTE réception lie l'événement à la piste d'audit du stock
    assert charge["hash_maillon"] == _maillons("principal")[-1]["hash_maillon"]
    assert charge["evenement_id"] == f"m6-reception-PO-FICT-1-{charge['hash_maillon'][:16]}"


def test_l_evenement_ne_porte_aucun_montant_ni_aucune_unite_convertie(base):
    _po_envoye()

    _receptionner(_reception(), catalogue=_catalogue())

    ((_, _, charge),) = _publies()
    cles = set(charge) | {cle for ligne in charge["lignes"] for cle in ligne}
    assert not {cle for cle in cles if "montant" in cle or "total" in cle or "taxe" in cle or "unite" in cle}
    assert all(isinstance(ligne["quantite_recue"], str) for ligne in charge["lignes"]), "du texte, pas un nombre"


def test_deux_livraisons_du_meme_po_publient_deux_evenements_distincts(base):
    _po_envoye()

    premiere = _receptionner(_reception(gouttiere=40.0, vis=0.0), catalogue=_catalogue())
    seconde = _receptionner(_reception(gouttiere=30.0, vis=20.0, horodatage=HORODATAGE_RECEPTION_2),
                            catalogue=_catalogue())

    assert premiere["resultat"]["accepte"] and seconde["resultat"]["accepte"]
    publies = _publies()
    assert len(publies) == 2
    identifiants = [evenement_id for evenement_id, _, _ in publies]
    assert len(set(identifiants)) == 2, "deux livraisons, deux identifiants"
    quantites = [[ligne["quantite_recue"] for ligne in charge["lignes"]] for _, _, charge in publies]
    assert quantites == [["40.0", "0.0"], ["30.0", "20.0"]], "chaque événement porte SA livraison, jamais le cumul"
    assert _statut_po() == "partially_received"


def test_une_reception_conforme_publie_le_statut_received(base):
    _po_envoye()

    reponse = _receptionner(_reception(gouttiere=100.0, vis=20.0), catalogue=_catalogue())

    assert reponse["resultat"]["po"]["statut"] == "received"
    ((_, _, charge),) = _publies()
    assert (charge["verdict_reception"], charge["statut_po"]) == ("CONFORME", "received")


def test_l_ecart_de_prix_est_porte_par_la_ligne_avec_le_seuil_utilise(base):
    _po_envoye()

    reponse = _receptionner(_reception(gouttiere=40.0, vis=0.0), catalogue=_catalogue(gouttiere=10.5))

    assert [s["materiau_id"] for s in reponse["resultat"]["signaux_ecart_prix"]] == ["gouttiere-5po"]
    ((_, _, charge),) = _publies()
    gouttiere, vis = charge["lignes"]
    assert charge["seuil_ecart_prix_pourcentage"] == 0.15
    assert (gouttiere["prix_unitaire_prevu"], gouttiere["prix_unitaire_reception"]) == ("8.5", "10.5")
    assert gouttiere["ecart_prix_critique"] is True and vis["ecart_prix_critique"] is False


# -- atomicité ---------------------------------------------------------------------------------------------
def test_si_la_publication_echoue_ni_le_stock_ni_le_po_ne_restent_ecrits(base, monkeypatch):
    _po_envoye()
    avant_stock = _maillons("principal")

    def _panne(*_args, **_kwargs):
        raise RuntimeError("panne du bus")

    monkeypatch.setattr(m6_outils.evenements, "publier", _panne)
    with pytest.raises(RuntimeError, match="panne du bus"):
        _receptionner(_reception(), catalogue=_catalogue())

    assert _maillons("principal") == avant_stock == []
    assert _statut_po() == "sent_to_supplier", "la transition du PO est annulée avec le reste"
    assert _publies() == []


def test_une_reception_non_publiable_annule_la_reception_entiere(base, monkeypatch):
    """Un accusé et un PO qui ne se correspondent pas trahissent un défaut interne : la réception est annulée
    (stock, PO), jamais laissée sans son événement, donc sans son « à payer attendu » chez M5."""
    _po_envoye()
    verdict = {"code": "REJ-RECEPTION-EVENEMENT-INCOHERENT", "detail": "défaut simulé"}
    monkeypatch.setattr(m6_outils.evenement_reception, "construire_charge", lambda *_a, **_k: (None, verdict))

    with pytest.raises(RuntimeError, match="non publiable"):
        _receptionner(_reception(), catalogue=_catalogue())

    assert _maillons("principal") == [] and _statut_po() == "sent_to_supplier" and _publies() == []


def test_republier_la_meme_reception_est_un_no_op_du_bus(base):
    _po_envoye()
    _receptionner(_reception(), catalogue=_catalogue())
    ((evenement_id, _, charge),) = _publies()
    po = {"po_id": "PO-FICT-1", "chantier_id": "CH-FICT-1", "fournisseur_id": "gentek", "statut": "partially_received",
          "lignes": [{"materiau_id": "gouttiere-5po", "quantite_demandee": 100.0, "verdict_prix": "PRIX_LIVRE",
                      "prix_unitaire_prevu": 8.5, "devise_prevue": "CAD", "montant_ligne_prevu": 850.0},
                     {"materiau_id": "vis-inox", "quantite_demandee": 20.0, "verdict_prix": "PRIX_LIVRE",
                      "prix_unitaire_prevu": 0.35, "devise_prevue": "CAD", "montant_ligne_prevu": 7.0}]}
    accuse = {"verdict_reception": "RECEPTION_INFERIEURE", "hash_maillon": charge["hash_maillon"],
              "lignes": [{"materiau_id": "gouttiere-5po", "quantite_demandee": 100.0, "quantite_recue": 40.0,
                          "verdict_resolution_prix": "PRIX_CATALOGUE", "cout_unitaire_resolu": 8.5},
                         {"materiau_id": "vis-inox", "quantite_demandee": 20.0, "quantite_recue": 0.0,
                          "verdict_resolution_prix": "PRIX_CATALOGUE", "cout_unitaire_resolu": 0.35}]}

    with stockage.transaction():
        rejoue = m6_outils._publier_reception(po, accuse, _reception(), 0.15, [])

    assert rejoue == evenement_id
    assert len(_publies()) == 1


# -- ce qui n'est PAS publié -------------------------------------------------------------------------------
def test_une_reception_ephemere_sans_po_persiste_ne_publie_rien(base):
    """Pas de PO persisté, donc pas de fournisseur : M5 n'aurait personne à qui devoir. Le comportement de la
    réception éphémère est celui d'avant : le stock est écrit, aucun événement ne part."""
    reponse = _receptionner(_reception(po_id="PO-EPHEMERE"), bon_demande=_bon_demande(po_id="PO-EPHEMERE"),
                            catalogue=_catalogue())

    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True
    assert "evenement_reception_id" not in reponse["resultat"] and "po" not in reponse["resultat"]
    assert len(_maillons("principal")) == 2, "le stock est écrit comme avant"
    assert _publies() == []


def test_une_reception_qui_n_apparie_aucune_ligne_ne_publie_rien_et_n_ecrit_rien(base):
    _po_envoye()
    reception = _reception(po_id="PO-FICT-1", chantier_id="CH-AUTRE")  # chantier différent : INDETERMINE

    reponse = _receptionner(reception, catalogue=_catalogue())

    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True
    assert reponse["resultat"]["resultat"]["accuse_reception"]["verdict_reception"] == "INDETERMINE"
    assert reponse["resultat"]["evenement_reception_id"] is None
    assert _publies() == [] and _maillons("principal") == []
    assert _statut_po() == "sent_to_supplier"


def test_hors_transaction_aucun_evenement_n_est_publie_comportement_d_avant():
    """Appel direct des fonctions (tests unitaires qui ne montent aucune base) : rien à publier, l'historique en
    mémoire est retransmis comme avant, et la réponse ne porte pas `evenement_reception_id`."""
    fh = m6_outils.enregistrer_fournisseur("gentek", "Gentek", "2026-01-01T00:00:00Z")["fournisseurs_historique"]
    lph = m6_outils.enregistrer_prix("gouttiere-5po", "gentek", 8.5, "CAD", "2026-01-01")["livre_prix_historique"]
    lph = m6_outils.enregistrer_prix("vis-inox", "gentek", 0.35, "CAD", "2026-01-01",
                                     livre_prix_historique=lph)["livre_prix_historique"]
    bh = m6_outils.enregistrer_besoins_prevus("CH-FICT-1", "DEVIS-FICT-1", [
        {"materiau_id": "gouttiere-5po", "quantite_estimee": 100.0, "unite": "pi"},
        {"materiau_id": "vis-inox", "quantite_estimee": 20.0, "unite": "boite"}])["registre_historique"]
    creation = m6_outils.creer_po_brouillon(
        "PO-FICT-1", "DEVIS-FICT-1", "gentek", "2026-09-01T08:00:00-04:00",
        besoins_prevus_historique=bh, livre_prix_historique=lph, fournisseurs_historique=fh)
    bch = creation["bons_commande_historique"]
    for etape in (lambda h: m6_outils.approuver_po("PO-FICT-1", "2026-09-01T09:00:00-04:00",
                                                   bons_commande_historique=h),
                  lambda h: m6_outils.generer_courriel_po("PO-FICT-1", "2026-09-01T10:00:00-04:00", "Entreprise",
                                                          fournisseurs_historique=fh, bons_commande_historique=h),
                  lambda h: m6_outils.marquer_po_envoye("PO-FICT-1", "2026-09-01T11:00:00-04:00",
                                                        bons_commande_historique=h)):
        bch = etape(bch)["bons_commande_historique"]

    reponse = m6_outils.receptionner_commande(
        _bon_demande(), _reception(), catalogue_materiaux=_catalogue(), bons_commande_historique=bch)

    assert reponse["accepte"] is True and reponse["po"]["statut"] == "partially_received"
    assert "evenement_reception_id" not in reponse and "registre_historique" in reponse


# -- refusé AVANT d'écrire ---------------------------------------------------------------------------------
@pytest.mark.parametrize("quantite", [-1.0, -0.001, math.nan, math.inf, True, "40"])
def test_une_quantite_recue_invalide_est_refusee_avant_toute_ecriture(base, quantite):
    _po_envoye()

    reponse = _receptionner(_reception(gouttiere=quantite), catalogue=_catalogue())

    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-RECEPTION-QUANTITE-INVALIDE"
    assert _maillons("principal") == [], "rien n'est écrit au stock"
    assert _statut_po() == "sent_to_supplier" and _publies() == []


@pytest.mark.parametrize("horodatage", ["2026-09-29", "2026-09-29T09:15:00", "hier"])
def test_un_horodatage_sans_fuseau_est_refuse_avant_toute_ecriture(base, horodatage):
    _po_envoye()

    reponse = _receptionner(_reception(horodatage=horodatage), catalogue=_catalogue())

    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-RECEPTION-HORODATAGE-INVALIDE"
    assert _maillons("principal") == [] and _statut_po() == "sent_to_supplier" and _publies() == []


def test_un_po_deja_recu_completement_ne_recoit_plus_et_ne_publie_rien(base):
    _po_envoye()
    _receptionner(_reception(gouttiere=100.0, vis=20.0), catalogue=_catalogue())
    assert len(_publies()) == 1

    reponse = _receptionner(_reception(gouttiere=100.0, vis=20.0, horodatage=HORODATAGE_RECEPTION_2),
                            catalogue=_catalogue())

    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-PO-TRANSITION-ILLEGALE"
    assert len(_publies()) == 1 and len(_maillons("principal")) == 2
