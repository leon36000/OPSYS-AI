"""PLAN T2.1-a — un SMS de client traverse M1 puis M2 par le vrai bus, et sa session se lie à son affaire par un humain.

Trajet prouvé, sans réseau ni core (le core ne s'exécute pas ici) :

    message reçu par le canal (champs que la plateforme donne à l'agent)
      -> `Capacites.appeler("m1_recevoir_message_canal")`   (vrai manifeste de M1, mode ombre, N2 : sans approbation)
      -> registre anti-perte de M1 + événement `m1.lead_qualifie` (même transaction)
      -> `evenements.repartir` (vrai répartiteur, idempotent)
      -> `m2.ingerer_lead` (vraie fonction de M2 : contrat v2, Client 360, événement `m2.client_associe`)

M2 ne déclare pas encore qu'il consomme `m1.lead_qualifie` (M2 est hors de cette tranche) : le test greffe, sur le
VRAI manifeste de M2, une fonction consommatrice de trois lignes qui appelle `m2.ingerer_lead`. C'est la greffe
que M2 fera dans son manifeste (`evenements.consomme`) et son `consommateurs()` ; tout le reste est réel.

Puis, avec les vrais outils de M10 : la clé de session que M1 a calculée est liée au `lead_id` par une décision
humaine (approbation de nathan), jamais par le texte du client. Données fictives.
"""

from __future__ import annotations

import dataclasses
import datetime as dt

import pytest
from m1_front_office import outils as m1
from m1_front_office import reception
from m2_revenue_crm import outils as m2
from sqlalchemy import select

from opsys import approbations, evenements, identite, stockage, taxonomie
from opsys.capacites import Capacites, outils_executables
from opsys.departements import Departement, charger_departements
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS

DEBUT = dt.datetime(2026, 9, 29, 9, 30, tzinfo=dt.timezone(dt.timedelta(hours=-4)))
NUMERO = "+15145550142"
RECU_LE = "2026-09-29T09:15:00-04:00"
SMS = {
    "canal": "sms", "expediteur": NUMERO, "message_id": "SMfictif0001", "recu_le": RECU_LE,
    "texte": "Bonjour, mes gouttières fuient à Laval, c'est urgent.",
}
MOTIF = "Le client a écrit par SMS : son affaire est le lead qui vient d'être qualifié."


def _consommateur_lead_de_m1(charge: dict) -> dict:
    """Ce que M2 branchera : le lead que M1 publie est ingéré par la VRAIE `m2_ingerer_lead`."""
    resultat = m2.ingerer_lead(charge["lead"], charge["horodatage"])
    if not resultat["accepte"]:
        raise ValueError(f"M2 refuse le lead de M1 : {resultat['verdict']}")
    return resultat


class _M2QuiConsommeLeadsDeM1(Departement):
    def charger_consommateurs(self):
        return {**super().charger_consommateurs(), "m1.lead_qualifie": _consommateur_lead_de_m1}


def _departements() -> dict[str, Departement]:
    deps = charger_departements()
    m2_reel = deps["m02-revenue-crm"]
    champs = {f.name: getattr(m2_reel, f.name) for f in dataclasses.fields(m2_reel)}
    champs["evenements_consomme"] = (*m2_reel.evenements_consomme, "m1.lead_qualifie")
    deps["m02-revenue-crm"] = _M2QuiConsommeLeadsDeM1(**champs)
    return deps


@pytest.fixture
def instance(tmp_path, monkeypatch, declarer_services):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    declarer_services()
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    m1.utiliser_stockage_durable()
    m2.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan Fictif", "mot-de-passe-nathan-12345", ["nathan_owner"])
    yield _departements()
    m1.reinitialiser_registre()
    m2.reinitialiser_registre()
    stockage.liberer()


def _drainer(deps, *, max_tours: int = 10) -> dict[str, int]:
    """Livre le bus jusqu'à quiescence, sur TOUS les départements (boucle bornée)."""
    total = {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    for tour in range(max_tours):
        resume = evenements.repartir(deps, maintenant=(DEBUT + dt.timedelta(seconds=90 * tour)).isoformat())
        for cle in total:
            total[cle] += resume[cle]
        if resume["livres"] == 0:
            return total
    raise AssertionError(f"le bus n'a pas atteint la quiescence : {total}")


def _recu(evenement_id: str, consommateur: str) -> dict | None:
    with stockage.transaction() as cnx:
        ligne = cnx.execute(select(EVENEMENTS_RECUS).where(
            (EVENEMENTS_RECUS.c.evenement_id == evenement_id) & (EVENEMENTS_RECUS.c.consommateur == consommateur)
        )).mappings().first()
    return None if ligne is None else dict(ligne)


def _maillons_m2() -> list[dict]:
    with stockage.transaction():
        return list(stockage.maillons("m02-revenue-crm", "principal"))


def _contrat_ingere(lead_id: str) -> dict:
    """Le contrat que M2 a copié tel quel dans son maillon `lead_ingere`."""
    trouves = [m for m in _maillons_m2() if m.get("type_entree") == "lead_ingere" and m.get("lead_id") == lead_id]
    assert len(trouves) == 1, trouves
    return trouves[0]["contrat"]


def _client_de(lead_id: str) -> str:
    with stockage.transaction():
        return evenements.charge_publiee("m2.client_associe", f"m2-client-associe-{lead_id}")["client_id"]


def test_un_sms_traverse_m1_puis_m2_par_le_vrai_bus_avec_le_canal_pour_source(instance):
    deps = instance
    capacites = Capacites(deps, stockage.transaction, filtre={"m01-front-office"}, memoire=False)

    reponse = capacites.appeler("m1_recevoir_message_canal", SMS)
    assert reponse["ok"] is True and reponse["resultat"]["decision"] == "TRANSMETTRE_M2", reponse
    lead = reponse["resultat"]["lead"]
    evenement_id = f"m1-lead-qualifie-{lead['lead_id']}"

    # Avant la livraison : M2 ne sait rien. Le lead voyage par le bus, jamais par un appel direct de M1.
    assert [m for m in _maillons_m2() if m.get("lead_id") == lead["lead_id"]] == []

    resume = _drainer(deps)
    assert resume["echecs"] == 0 and resume["quarantaines"] == 0, resume
    assert evenements.etat()["quarantaine"] == []

    recu = _recu(evenement_id, "m02-revenue-crm")
    assert recu["statut"] == "traite" and recu["tentatives"] == 1
    ingere = codec.decoder(recu["resultat"])
    assert ingere["accepte"] is True and ingere["lead_id"] == lead["lead_id"] and ingere["client_id"]

    # M2 a ingéré le lead tel que M1 l'a émis : `source` = le canal du core, service de la taxonomie, contact du canal.
    contrat = _contrat_ingere(lead["lead_id"])
    assert contrat == lead
    assert (contrat["source"], contrat["canal"], contrat["service"]) == ("sms", "texte", "gouttieres")
    assert contrat["contact"] == {"telephone": NUMERO} and contrat["schema_version"] == 2

    # M2 a fait son travail à lui : Client 360, et l'événement que M5 consomme.
    assert _client_de(lead["lead_id"]) == ingere["client_id"]


def test_un_message_rejoue_ne_donne_ni_second_lead_ni_seconde_livraison(instance):
    deps = instance
    capacites = Capacites(deps, stockage.transaction, filtre={"m01-front-office"}, memoire=False)
    premier = capacites.appeler("m1_recevoir_message_canal", SMS)["resultat"]["lead"]["lead_id"]
    _drainer(deps)

    rejoue = capacites.appeler("m1_recevoir_message_canal", SMS)
    assert rejoue["resultat"]["doublon"] is True and rejoue["resultat"]["lead"]["lead_id"] == premier
    assert _drainer(deps)["livres"] == 0
    assert len([m for m in _maillons_m2() if m.get("type_entree") == "lead_ingere"]) == 1


def test_un_second_message_qualifie_du_meme_client_est_une_autre_opportunite_du_meme_client(instance):
    deps = instance
    capacites = Capacites(deps, stockage.transaction, filtre={"m01-front-office"}, memoire=False)
    premier = capacites.appeler("m1_recevoir_message_canal", SMS)["resultat"]["lead"]["lead_id"]
    suite = {**SMS, "message_id": "SMfictif0002", "texte": "Aussi le soffite à Laval, merci."}
    second = capacites.appeler("m1_recevoir_message_canal", suite)["resultat"]["lead"]["lead_id"]
    assert second != premier
    assert _drainer(deps)["quarantaines"] == 0
    assert _client_de(second) == _client_de(premier), "même numéro : M2 rattache les deux opportunités à un seul client"


def test_un_client_qui_se_retire_ne_cree_rien_chez_m2(instance):
    deps = instance
    capacites = Capacites(deps, stockage.transaction, filtre={"m01-front-office"}, memoire=False)
    reponse = capacites.appeler("m1_recevoir_message_canal", {**SMS, "message_id": "SM-STOP", "texte": "STOP"})
    assert reponse["resultat"]["decision"] == "RETRAIT_CONSENTEMENT"
    assert _drainer(deps)["livres"] == 0
    with stockage.transaction():
        assert list(stockage.maillons("m02-revenue-crm", "principal")) == []


def test_la_session_du_client_se_lie_a_son_affaire_par_une_decision_humaine_avec_la_cle_de_m1(instance):
    deps = instance
    capacites = Capacites(deps, stockage.transaction, filtre={"m01-front-office", "m10-memoire"}, memoire=False)
    resultat = capacites.appeler("m1_recevoir_message_canal", SMS)["resultat"]
    cle, lead_id = resultat["cle_session"], resultat["lead"]["lead_id"]
    assert cle == f"agent:m01-front-office:sms:direct:{NUMERO}" == reception.preparer(
        "sms", NUMERO, "x", RECU_LE, "t").cle_session

    # Avant tout lien, le core travaille sans affaire pour cette session (paquet indisponible, actions N3+ bloquées).
    assert capacites.appeler("m10_affaire_de_la_session", {"cle_session": cle})["resultat"] == {
        "lie": False, "affaire_id": None}

    # M1 (ni son texte, ni son outil) ne lie rien : le lien est une demande qui attend une personne.
    lien = {"cle_session": cle, "affaire_id": lead_id, "motif": MOTIF, "horodatage": RECU_LE}
    demande = capacites.appeler("m10_lier_session_affaire", lien)
    assert demande["statut"] == "en_attente_approbation", demande
    assert capacites.appeler("m10_affaire_de_la_session", {"cle_session": cle})["resultat"]["lie"] is False

    with stockage.transaction() as cnx:
        approbations.decider(cnx, demande["demande_id"], True, "nathan",
                             outils_executables(capacites.departements, stockage.transaction), capacites.departements)
    lue = capacites.appeler("m10_affaire_de_la_session", {"cle_session": cle})["resultat"]
    assert (lue["lie"], lue["affaire_id"], lue["lie_par"]) == (True, lead_id, "nathan")


def test_le_bus_est_coherent_avec_le_vrai_m1_qui_publie_le_lead_du_canal():
    deps = charger_departements()
    assert "m1.lead_qualifie" in evenements.types_connus()
    assert deps["m01-front-office"].evenements_publie == ("m1.lead_qualifie",)
    assert evenements.verifier_coherence(deps) == []
