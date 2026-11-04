"""M1-E : le bus reçoit un événement MINIMAL à chaque transfert ouvert, et une plainte a sa spécialisation.

Vrais outils, vrai manifeste, vraie base SQLite, vrai bus. Données fictives : numéro en 555, vocabulaire de test.
Ce que ces tests interdisent : un contact, un texte de client, un résumé ou un terme du vocabulaire dans la charge ;
deux événements pour un même transfert ; un événement de plainte pour un transfert ordinaire.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from m1_front_office import outils as outils_m1
from sqlalchemy import select

from opsys import identite, stockage, taxonomie
from opsys.capacites import Capacites
from opsys.departements import lire_manifeste
from opsys.stockage.schema import EVENEMENTS_SORTANTS

M1 = Path(__file__).resolve().parents[1]
NUMERO = "+15145550142"
DEBUT = dt.datetime(2031, 1, 15, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=-5)))
TYPES = ("m1.transfert_ouvert", "m1.plainte_ouverte")


def _a(minutes: float) -> str:
    return (DEBUT + dt.timedelta(minutes=minutes)).isoformat()


@pytest.fixture
def instance(tmp_path, monkeypatch, declarer_services, declarer_plaintes):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    declarer_services()
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    declarer_plaintes()
    outils_m1.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan Fictif", "mot-de-passe-nathan-12345", ["nathan_owner"])
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
    yield
    outils_m1.reinitialiser_registre()
    stockage.liberer()


@pytest.fixture
def capacites(instance):
    return Capacites({lire_manifeste(M1).id: lire_manifeste(M1)}, stockage.transaction, memoire=False)


def _sms(capacites, texte="Je suis déçu, mes gouttières fuient à Laval.", message_id="SM-1"):
    reponse = capacites.appeler("m1_recevoir_message_canal", {
        "canal": "sms", "expediteur": NUMERO, "message_id": message_id, "recu_le": _a(0), "texte": texte})
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _evenements(type_evenement=None):
    with stockage.transaction() as cnx:
        requete = select(EVENEMENTS_SORTANTS.c.type_evenement, EVENEMENTS_SORTANTS.c.evenement_id,
                         EVENEMENTS_SORTANTS.c.charge).order_by(EVENEMENTS_SORTANTS.c.evenement_id)
        if type_evenement is not None:
            requete = requete.where(EVENEMENTS_SORTANTS.c.type_evenement == type_evenement)
        return [dict(ligne) for ligne in cnx.execute(requete).mappings()]


def _charge(ligne):
    from opsys.stockage import codec

    return codec.decoder(ligne["charge"])


def test_une_plainte_publie_les_deux_evenements_minimaux(capacites):
    _sms(capacites)
    transfert = next(e for e in _evenements("m1.transfert_ouvert"))
    plainte = next(e for e in _evenements("m1.plainte_ouverte"))
    for evenement in (transfert, plainte):
        charge = _charge(evenement)
        assert set(charge) == {
            "evenement_id", "transfert_id", "conversation_id", "lead_id", "type_transfert", "categories",
            "niveau", "canal", "declenche_par", "horodatage",
        }
        assert charge["type_transfert"] == "plainte" and charge["categories"] == ["insatisfaction"]
        assert charge["niveau"] == "N4" and charge["declenche_par"] == "regles"
        assert charge["lead_id"] is None, "une plainte n'ouvre jamais de lead"
        # Loi 25 : ni contact, ni texte, ni terme, ni résumé.
        serialise = json.dumps(charge, ensure_ascii=False)
        for interdit in (NUMERO, "514-555-0142", "gouttière", "déçu", "Laval"):
            assert interdit not in serialise
    assert transfert["evenement_id"].startswith("m1-transfert-ouvert-tr-")
    assert plainte["evenement_id"].startswith("m1-plainte-ouverte-tr-")
    assert transfert["evenement_id"].removeprefix("m1-transfert-ouvert-") == charge["transfert_id"]


def test_un_transfert_ordinaire_ne_publie_pas_de_plainte(capacites):
    _sms(capacites, "Bonjour, je voudrais parler à un vendeur.")
    avec = capacites.appeler("m1_transferer", {
        "type_transfert": "ventes", "canal": "sms", "expediteur": NUMERO})
    assert avec["ok"] is True, avec
    assert len(_evenements("m1.transfert_ouvert")) == 1
    assert _evenements("m1.plainte_ouverte") == []


def test_le_rejeu_du_meme_message_ne_publie_rien_de_plus(capacites):
    _sms(capacites, message_id="SM-1")
    avant = len(_evenements("m1.transfert_ouvert")) + len(_evenements("m1.plainte_ouverte"))
    _sms(capacites, message_id="SM-1")
    apres = len(_evenements("m1.transfert_ouvert")) + len(_evenements("m1.plainte_ouverte"))
    assert (avant, apres) == (2, 2)


def test_une_urgence_de_securite_publie_une_plainte_d_urgence(capacites):
    _sms(capacites, "C'est dangereux, une gouttière tombe sur le trottoir à Laval.", message_id="SM-2")
    plainte = _charge(_evenements("m1.plainte_ouverte")[0])
    assert plainte["type_transfert"] == "urgence" and plainte["niveau"] == "N5"
    assert "securite" in plainte["categories"]
