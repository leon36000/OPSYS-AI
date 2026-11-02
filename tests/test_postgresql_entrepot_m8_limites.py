"""Entrepôt de M8 : les identifiants reçus du bus sont bornés par les colonnes `VARCHAR(256)` de l'entrepôt, sur
SQLite ET
sur PostgreSQL 17 réel.

Défaut (PostgreSQL seulement) : le schéma du catalogue accepte un `devis_id` / `lead_id` / `wct_id` de longueur
quelconque ; M8 le rangeait au registre (append-only) ; la construction suivante de l'entrepôt écrivait ce texte
dans une
colonne `VARCHAR(256)` : PostgreSQL refusait (`value too long`), SQLite non. Une seule valeur démesurée faisait donc
échouer
CHAQUE construction à vie (le planificateur journalisait un défaut d'exécuteur à chaque tour). La limite est posée à la
réception : l'événement est un refus typé (réessais puis quarantaine, visible), rien n'entre au registre, l'entrepôt
se bâtit.
"""

from __future__ import annotations

import interconnexion_monde as im
import pytest
from m8_analytics import entrepot_stockage
from pg_parite import base_pg, serveur_pg, url_base  # noqa: F401  (fixtures pytest)
from sqlalchemy import select

from opsys import evenements, stockage
from opsys.capacites import Capacites
from opsys.stockage.schema import EVENEMENTS_RECUS

FICTIF = True
M3, M8 = "m03-estimation", "m08-analytics"
LIMITE = entrepot_stockage.LONGUEURS_IDENTIFIANTS["devis_id"]


@pytest.fixture
def monde(url_base, tmp_path, monkeypatch):  # noqa: F811
    m = im.monter(tmp_path, monkeypatch, (M3, M8), url=url_base)
    yield m
    im.demonter()


def _devis_envoye(devis_id: str, lead_id: str = "lead-1") -> dict:
    return {"devis_id": devis_id, "lead_id": lead_id, "chantier_id": None,
            "horodatage_envoi": "2026-11-01T10:00:00-04:00"}


def _construire(monde):
    capacites = Capacites(monde.departements, stockage.transaction, filtre={M8}, memoire=False)
    return capacites.appeler("m8_construire_entrepot", {"maintenant": "2026-11-02T10:00:00+00:00"})


def test_la_limite_vient_des_colonnes_de_l_entrepot_et_vaut_256():
    assert entrepot_stockage.LONGUEURS_IDENTIFIANTS == {
        "lead_id": 256, "devis_id": 256, "wct_id": 256, "contenu_id": 256, "utm_content": 256}


@pytest.mark.parametrize("champ", ["devis_id", "lead_id"])
def test_un_identifiant_demesure_est_refuse_a_la_reception_et_l_entrepot_se_construit(monde, champ):
    hostile = "x" * (LIMITE + 1)
    charge = _devis_envoye("devis-sain", "lead-sain") | {champ: hostile}
    evenements.publier("m3.devis_envoye", M3, charge, evenement_id="hostile")
    evenements.publier("m3.devis_envoye", M3, _devis_envoye("devis-ok", "lead-ok"), evenement_id="sain")
    monde.repartir(passes=6)
    with stockage.transaction() as cnx:
        recus = {r.evenement_id: r for r in cnx.execute(select(EVENEMENTS_RECUS).where(
            EVENEMENTS_RECUS.c.consommateur == M8)).all()}
    assert recus["sain"].statut == "traite"
    assert recus["hostile"].statut in {"echec", "quarantaine"} and "REJ-ENTREPOT-IDENTIFIANT-TROP-LONG" in (
        recus["hostile"].derniere_erreur or "")
    assert monde.taille(M8, "faits_entonnoir") == 1  # seul le fait sain est entré au registre append-only
    reponse = _construire(monde)
    assert reponse["ok"] is True and reponse["resultat"]["statut"] == "construit", reponse


def test_un_identifiant_de_la_longueur_exacte_de_la_colonne_passe_et_l_entrepot_le_porte(monde):
    exact = "d" * LIMITE
    evenements.publier("m3.devis_envoye", M3, _devis_envoye(exact), evenement_id="exact")
    monde.repartir()
    assert monde.statut("exact", M8) == "traite"
    assert _construire(monde)["resultat"]["statut"] == "construit"
    with stockage.transaction() as cnx:
        devis = {ligne["devis_id"] for ligne in entrepot_stockage.lire_table(cnx, "m8_ent_fait_devis")}
    assert exact in devis
