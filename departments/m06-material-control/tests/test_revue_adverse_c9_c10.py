"""Revue adverse C9/C10 (vague 14) : les huit défauts prouvés par un autre modèle, gardés comme tests permanents.

Chaque test part d'un état réel (base SQLite migrée, vrais registres durables, vrais outils sauf la consommation de
fixture qui amorce une incohérence de lieux) et des données FICTIVES. Les assertions de refus sont conservées ; le
préambule de D1/D2 est adapté parce que D8 interdit désormais l'ajustement GLOBAL qui rendrait `inconnu` négatif :
l'incohérence est amorcée par une consommation, puis l'ajustement localisé refuse sans écrire.

Rouge-avant : ces tests échouent sur le code d'avant la correction (D1-D8), puis restent verts.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from m6_material_control import alertes_approvisionnement as alertes
from m6_material_control import pertes_appareil, preuves_pertes_bris_appareil, reapprovisionnement_appareil
from m6_material_control.registre import Registre

from opsys import stockage
from opsys.outils import executer_atomique

_spec = importlib.util.spec_from_file_location(
    "fixture_revue_adverse_c9_c10", Path(__file__).with_name("test_reservation_outils.py"))
aide = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(aide)
base, m6 = aide.base, aide.m6

H = "2026-10-08T10:00:00-04:00"
MON = "2026-10-20T12:00:00+00:00"
GOUTTIERE = aide.GOUTTIERE


def _outil(nom, arguments):
    outil = next(o for o in aide.m6_outils.outils() if o.nom == nom)
    reponse = executer_atomique(outil, arguments)
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _seuil(monkeypatch, valeur):
    monkeypatch.setattr(aide.m6_outils, "_seuil_ajustement_stock", lambda: valeur)


def _dem(**remplacements):
    demande = {"ajustement_id": "AJ-REV", "materiau_id": GOUTTIERE, "motif": "correction",
               "quantite_apres": 8, "horodatage": H, "acteur": "agent"}
    demande.update(remplacements)
    return demande


def _consommer(materiau_id, quantite):
    """Amorce une sortie non localisée dans le VRAI registre durable (fixture, pas un outil d'ajustement)."""
    with stockage.transaction():
        registre = Registre(stockage.maillons(aide._DEPARTEMENT, "principal"))
        _, erreur = registre.ajouter({
            "type_mouvement": "CONSOMMATION", "chantier_id": "CH-REV-FICT", "materiau_id": materiau_id,
            "quantite": quantite, "cout_unitaire": None,
        })
    assert erreur is None


def _maillons(nom="principal"):
    with stockage.transaction():
        return list(stockage.maillons(aide._DEPARTEMENT, nom))


def _etat_incoherent(m6):
    """total 0, dépôt 2, inconnu -2 : réception 10, rangement 10, ajustement localisé à 2, consommation 2."""
    aide._recevoir(m6, GOUTTIERE, 10.0, "PO-REV-INCOHERENT")
    _outil("m6_transferer_stock", {
        "transfert_id": "T-REV-INCOHERENT", "materiau_id": GOUTTIERE, "quantite": 10.0,
        "de": {"type": "inconnu"}, "vers": {"type": "depot"}, "motif": "ranger", "horodatage": H,
    })
    _outil("m6_ajuster_stock", {"ajustement": {
        **_dem(ajustement_id="AJ-REV-SEED"), "emplacement": {"type": "depot"}, "quantite_apres": 2,
    }})
    _consommer(GOUTTIERE, -2.0)


# D1 — l'ajustement n'est pas écrit quand son transfert localisé est refusé (tout-ou-rien).
def test_D1_echec_transfert_n_ecrit_aucun_ajustement(base, m6, monkeypatch):
    _seuil(monkeypatch, Decimal("100"))
    _etat_incoherent(m6)
    avant_principal = len(_maillons())
    avant_emplacements = len(_maillons("emplacements"))
    resultat = _outil("m6_ajuster_stock", {"ajustement": {
        **_dem(ajustement_id="AJ-REV-D1d"), "emplacement": {"type": "depot"}, "quantite_apres": 0,
    }})
    assert resultat["accepte"] is False, resultat
    assert resultat["verdict"]["code"] == "REJ-TRANSFERT-STOCK-LOCALISE-INCOHERENT", resultat
    assert len(_maillons()) == avant_principal, (
        f"ATTENDU : refus sans écriture (atomicité). OBSERVE : "
        f"{len(_maillons()) - avant_principal} maillon(s) ajouté(s) malgré le refus")
    assert len(_maillons("emplacements")) == avant_emplacements


# D2 — même atomicité, autre refus : le résidu non localisé est insuffisant.
def test_D2_stock_insuffisant_n_ecrit_aucun_ajustement(base, m6, monkeypatch):
    _seuil(monkeypatch, Decimal("100"))
    _etat_incoherent(m6)
    avant_principal = len(_maillons())
    avant_emplacements = len(_maillons("emplacements"))
    resultat = _outil("m6_ajuster_stock", {"ajustement": {
        **_dem(ajustement_id="AJ-REV-D2d"), "emplacement": {"type": "depot"}, "quantite_apres": 5,
    }})
    assert resultat["accepte"] is False and resultat["verdict"]["code"] == "REJ-TRANSFERT-STOCK-INSUFFISANT", resultat
    assert len(_maillons()) == avant_principal, (
        f"ATTENDU : refus sans écriture. OBSERVE : {len(_maillons()) - avant_principal} maillon(s) ajouté(s)")
    assert len(_maillons("emplacements")) == avant_emplacements


# D3 — aucun flottant dans la quantité auditée : l'audit égale le stock réel.
def test_D3_audit_apres_egal_stock_reel_meme_avec_un_flottant_d_entree(base, m6, monkeypatch):
    _seuil(monkeypatch, Decimal("100"))
    aide._recevoir(m6, GOUTTIERE, 10.0, "PO-REV-D3")
    resultat = _outil("m6_ajuster_stock", {"ajustement": _dem(ajustement_id="AJ-REV-D3", quantite_apres=0.1 + 0.2)})
    assert resultat["accepte"] is True, resultat
    audit = resultat["ajustement"]
    stock = _outil("m6_lire_disponibilite", {"materiau_ids": [GOUTTIERE]})["resultat"]["articles"][0][
        "stock_theorique"]
    assert stock == audit["quantite_apres"], (
        f"ATTENDU : stock réel == après audité. OBSERVE : audit dit {audit['quantite_apres']}, stock réel {stock}")
    mouvement = _maillons()[-1]
    assert type(mouvement["quantite"]) is Decimal, "la quantité écrite reste décimale exacte, jamais un flottant"


# D4 — une quantité corrompue ne fait pas lever : la règle dépendante est dite non évaluée.
def test_D4_quantite_corrompue_donne_un_verdict_fail_closed():
    maintenant = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
    mouvements = [
        {"index": 0, "type_mouvement": "RECEPTION", "chantier_id": "CH", "materiau_id": "M",
         "quantite": "dix", "cout_unitaire": None, "hash_precedent": "", "hash_maillon": "a" * 64},
    ]
    resultat = alertes.calculer(mouvements=mouvements, bons_commande=(), fournisseurs=(), wct_recus=(),
                                seuil_repetition=2, fenetre_jours=30, maintenant=maintenant)
    assert not [a for a in resultat["alertes"] if a["type"] == "commande_recue_stock_disparu"]
    assert any("quantite" in n["cle"] for n in resultat["non_evaluees"]), resultat["non_evaluees"]


# D5 — un booléen n'est pas une quantité : il ne compte pas comme variance.
def test_D5_variance_booleenne_ou_textuelle_n_est_pas_un_ecart():
    maintenant = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)

    def mv(q):
        return {"index": 0, "type_mouvement": "VARIANCE_INVENTAIRE", "chantier_id": "CH", "materiau_id": "M",
                "quantite": q, "cout_unitaire": None, "hash_precedent": "", "hash_maillon": "a" * 64}

    for hostile in (True, "x"):
        resultat = alertes.calculer(mouvements=[mv(hostile), mv(hostile)], bons_commande=(), fournisseurs=(),
                                    wct_recus=(), seuil_repetition=2, fenetre_jours=30, maintenant=maintenant)
        assert resultat["alertes"] == [], (
            f"ATTENDU : aucune alerte (un booléen/texte n'est pas une quantité). OBSERVE : {resultat['alertes']}")
        assert resultat["non_evaluees"]


# D6 — la réception qui a disparu est bornée par la fenêtre déclarée.
def test_D6_commande_recue_stock_disparu_est_bornee_par_la_fenetre():
    maintenant = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
    mouvements = [
        {"index": 0, "type_mouvement": "RECEPTION", "chantier_id": "CH", "materiau_id": "M",
         "quantite": 10.0, "cout_unitaire": None, "hash_precedent": "", "hash_maillon": "a" * 64,
         "horodatage": "2020-01-01T00:00:00+00:00"},
        {"index": 1, "type_mouvement": "CONSOMMATION", "chantier_id": "CH", "materiau_id": "M",
         "quantite": -10.0, "cout_unitaire": None, "hash_precedent": "", "hash_maillon": "b" * 64,
         "horodatage": "2020-01-02T00:00:00+00:00"},
    ]
    resultat = alertes.calculer(mouvements=mouvements, bons_commande=(), fournisseurs=(), wct_recus=(),
                                seuil_repetition=999, fenetre_jours=30, maintenant=maintenant)
    assert resultat["alertes"] == [], (
        f"ATTENDU : aucune alerte (mouvements vieux de 6 ans, fenêtre 30 j). OBSERVE : {resultat['alertes']}")


# D7 — la fenêtre reste dans 1..365, au module pur comme à la lecture du manifeste.
def test_D7_fenetre_366_jours_est_non_evaluee():
    maintenant = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
    resultat = alertes.calculer(mouvements=(), bons_commande=(), fournisseurs=(), wct_recus=(),
                                seuil_repetition=2, fenetre_jours=366, maintenant=maintenant)
    assert resultat["non_evaluees"] != [], "ATTENDU : 366 j hors 1..365, non évalué"
    assert resultat["alertes"] == []
    accepte = alertes.calculer(mouvements=(), bons_commande=(), fournisseurs=(), wct_recus=(),
                               seuil_repetition=2, fenetre_jours=365, maintenant=maintenant)
    assert not [n for n in accepte["non_evaluees"] if "fenetre" in n["cle"]]


# D8 — un ajustement GLOBAL qui rendrait `inconnu` négatif est refusé, sans écriture.
def test_D8_ajustement_global_qui_rend_inconnu_negatif_est_refuse(base, m6, monkeypatch):
    _seuil(monkeypatch, Decimal("100"))
    aide._recevoir(m6, GOUTTIERE, 10.0, "PO-REV-D8")
    _outil("m6_transferer_stock", {
        "transfert_id": "T-REV-D8", "materiau_id": GOUTTIERE, "quantite": 10.0,
        "de": {"type": "inconnu"}, "vers": {"type": "depot"}, "motif": "ranger", "horodatage": H,
    })
    avant = len(_maillons())
    resultat = _outil("m6_ajuster_stock", {"ajustement": _dem(ajustement_id="AJ-REV-D8", quantite_apres=0)})
    assert resultat["accepte"] is False and resultat["verdict"]["code"] == "REJ-AJUSTEMENT-STOCK-LOCALISE-INCOHERENT"
    assert len(_maillons()) == avant, "un refus ne laisse aucun maillon"
    article = _outil("m6_lire_disponibilite", {"materiau_ids": [GOUTTIERE]})["resultat"]["articles"][0]
    assert all(Decimal(v) >= 0 for v in article["par_emplacement"].values()), article["par_emplacement"]


# ---------------------------------------------------------------------------- cas voisins qui ne changent pas
def test_un_ajustement_localise_valide_ecrit_le_couple_ajustement_transfert(base, m6, monkeypatch):
    _seuil(monkeypatch, Decimal("100"))
    aide._recevoir(m6, GOUTTIERE, 10.0, "PO-REV-VALIDE")
    _outil("m6_transferer_stock", {
        "transfert_id": "T-REV-VALIDE", "materiau_id": GOUTTIERE, "quantite": 10.0,
        "de": {"type": "inconnu"}, "vers": {"type": "depot"}, "motif": "ranger", "horodatage": H,
    })
    principal = len(_maillons())
    emplacements = len(_maillons("emplacements"))
    resultat = _outil("m6_ajuster_stock", {"ajustement": {
        **_dem(ajustement_id="AJ-REV-VALIDE", quantite_apres=8), "emplacement": {"type": "depot"},
    }})
    assert resultat["accepte"] is True
    assert (len(_maillons()), len(_maillons("emplacements"))) == (principal + 1, emplacements + 1)
    assert resultat["ajustement"]["quantite_apres"] == "8"
    assert all(Decimal(v) >= 0 for v in resultat["repartition"].values())


def test_un_ajustement_global_qui_garde_le_residu_positif_passe(base, m6, monkeypatch):
    _seuil(monkeypatch, Decimal("100"))
    aide._recevoir(m6, GOUTTIERE, 10.0, "PO-REV-RESIDU")
    _outil("m6_transferer_stock", {
        "transfert_id": "T-REV-RESIDU", "materiau_id": GOUTTIERE, "quantite": 5.0,
        "de": {"type": "inconnu"}, "vers": {"type": "depot"}, "motif": "ranger", "horodatage": H,
    })
    resultat = _outil("m6_ajuster_stock", {"ajustement": _dem(ajustement_id="AJ-REV-RESIDU", quantite_apres=7)})
    assert resultat["accepte"] is True
    article = _outil("m6_lire_disponibilite", {"materiau_ids": [GOUTTIERE]})["resultat"]["articles"][0]
    assert article["par_emplacement"] == {"depot": "5", "inconnu": "2"}


def test_une_reception_recente_dans_la_fenetre_alerte_encore():
    maintenant = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
    mouvements = [
        {"index": 0, "type_mouvement": "RECEPTION", "chantier_id": "CH", "materiau_id": "M",
         "quantite": 10.0, "cout_unitaire": None, "hash_precedent": "", "hash_maillon": "a" * 64,
         "horodatage": (maintenant - timedelta(days=10)).isoformat()},
        {"index": 1, "type_mouvement": "CONSOMMATION", "chantier_id": "CH", "materiau_id": "M",
         "quantite": -10.0, "cout_unitaire": None, "hash_precedent": "", "hash_maillon": "b" * 64,
         "horodatage": (maintenant - timedelta(days=9)).isoformat()},
    ]
    resultat = alertes.calculer(mouvements=mouvements, bons_commande=(), fournisseurs=(), wct_recus=(),
                                seuil_repetition=999, fenetre_jours=30, maintenant=maintenant)
    (alerte,) = [a for a in resultat["alertes"] if a["type"] == "commande_recue_stock_disparu"]
    assert alerte["quantite_recue"] == "10" and alerte["stock_actuel"] == "0"


def test_un_maillon_sans_horodatage_est_signale_sans_etre_invente():
    maintenant = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
    mouvements = [{"index": 0, "type_mouvement": "RECEPTION", "chantier_id": "CH", "materiau_id": "M",
                   "quantite": 10.0, "cout_unitaire": None, "hash_precedent": "", "hash_maillon": "a" * 64},
                  {"index": 1, "type_mouvement": "CONSOMMATION", "chantier_id": "CH", "materiau_id": "M",
                   "quantite": -10.0, "cout_unitaire": None, "hash_precedent": "", "hash_maillon": "b" * 64}]
    resultat = alertes.calculer(mouvements=mouvements, bons_commande=(), fournisseurs=(), wct_recus=(),
                                seuil_repetition=999, fenetre_jours=30, maintenant=maintenant)
    assert any("horodatage" in n["action"].lower() for n in resultat["non_evaluees"]), resultat["non_evaluees"]


def test_les_lecteurs_appareil_acceptent_la_quantite_decimale_d_un_ajustement(base, m6, monkeypatch):
    """Un AJUSTEMENT stocke sa quantité en Decimal exact : les lecteurs mobiles ne doivent pas le refuser."""
    _seuil(monkeypatch, Decimal("100"))
    aide._recevoir(m6, GOUTTIERE, 10.0, "PO-REV-DECIMAL")
    resultat = _outil("m6_ajuster_stock", {"ajustement": _dem(ajustement_id="AJ-REV-DECIMAL", quantite_apres=8)})
    assert resultat["accepte"] is True
    mouvements = _maillons()
    preuves_pertes_bris_appareil.valider_snapshots(mouvements, [])
    pertes_appareil._mouvements(mouvements)
    chiffres: list[Decimal] = []
    reapprovisionnement_appareil._principal(mouvements, chiffres)
    assert Decimal("10") in chiffres and Decimal("-2") in chiffres



def test_un_instant_sans_fuseau_est_refuse_et_un_instant_avec_fuseau_est_accepte():
    # Régression trouvée à l'intégration : une inversion de `utcoffset() is None` rejetait tout instant AVEC fuseau.
    from datetime import UTC, datetime

    from m6_material_control import alertes_approvisionnement as alertes

    kw = {"mouvements": [], "bons_commande": [], "fournisseurs": [], "wct_recus": [], "seuil_repetition": 2,
          "fenetre_jours": 30}
    avec = alertes.calculer(maintenant=datetime(2026, 10, 20, 12, 0, tzinfo=UTC), **kw)
    sans = alertes.calculer(maintenant=datetime(2026, 10, 20, 12, 0), **kw)
    assert {n["regle"] if "regle" in n else n.get("type") for n in avec["non_evaluees"]} != {"horodatage"}
    assert [n for n in sans["non_evaluees"] if "maintenant" in str(n)] != []
    assert sans["alertes"] == []
