"""PLAN T4.27-a2 : un rejeu de la même clé rend le même résultat, avec la même heure (celle de la PREMIÈRE réception),
jamais une nouvelle heure, pour `m4_signaler_report` et `m4_creer_demande_ecart`.

Le rejeu est celui du socle (`Capacites._appeler_idempotent`, `docs/architecture/IDEMPOTENCE.md`) : une mutation
d'appareil porte une clé dans `_meta` ; un renvoi de la même clé, du même outil et des mêmes arguments rend la réponse
ENREGISTRÉE, sans ré-exécuter. Ces tests passent par `Capacites.appeler` avec un `_meta` réel (`idempotence.Meta`),
les vrais outils de M4, une base SQLite migrée et une horloge de test du serveur que le test avance à la main : ce que
M4 y ajoute, c'est que l'accusé rend l'heure de la première réception, donc que la réponse rejouée la porte aussi.

Ce que ce fichier prouve :
  * le renvoi de la même clé, deux heures plus tard, rend la MÊME réponse (heure de la première réception, heure de
    l'appareil de la première fois), marquée `rejoue`, sans rien écrire de plus (mêmes maillons, une seule ligne de
    mutation, l'heure de réception de la première) ;
  * il en va de même si l'appareil renvoie avec une autre horloge, ou après qu'un autre geste ait eu lieu entre-temps ;
  * une autre clé pour le même report est refusée (le report existe déjà) et ne change pas son heure ; la même clé avec
    d'autres arguments est un conflit nommé qui ne change rien ;
  * le relevé des retards lit toujours l'heure de la première réception après un renvoi.
Données fictives (`fictif: true`).
"""

from __future__ import annotations

import datetime as dt
import types

import pytest
from m4_field_ops import encodage
from m4_field_ops import registre as registre_m4
from sqlalchemy import select

from opsys import capacites as module_capacites
from opsys import contexte, etat, idempotence, identite, stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.stockage.schema import MUTATIONS_APPLIQUEES

FICTIF = True
M4 = "m04-field-ops"
SEL = "sel-t4-27-a2-fictif"
FENETRE = {"debut": "2025-06-02T07:00:00+00:00", "fin": "2025-06-02T19:00:00+00:00"}
MARC = contexte.IdentiteAppelante(personne="marc.fictif", role="employee")
ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
HEURE_ECRITE = "2001-02-03T04:05:06+00:00"  # ce que l'app écrit : jamais lu pendant un appel d'appareil
APPAREIL_A = "2000-01-01T00:00:00+00:00"  # l'horloge de l'appareil au premier envoi (fausse)
APPAREIL_B = "2000-01-01T00:07:00+00:00"  # la même horloge au renvoi, sept minutes plus tard
PREMIERE_RECEPTION = dt.datetime(2025, 6, 5, 9, 0, 0, tzinfo=dt.UTC)
VERSION_PREVUE = {"duree_minutes": 60, "perimetre": "perimetre prevu", "materiaux": ["m1"]}
VERSION_DECLAREE = {"duree_minutes": 90, "perimetre": "perimetre declare", "materiaux": ["m2"]}


class Horloge:
    """L'horloge du serveur pour le test : `Capacites._appeler_idempotent` lit `dt.datetime.now(dt.UTC)` pour l'heure de
    réception (`recu_le`). On remplace `dt` dans `opsys.capacites` par un substitut dont `datetime.now` rend l'heure du
    test, que le test avance à la main : ni sommeil ni heure réelle."""

    def __init__(self, debut: dt.datetime) -> None:
        self.maintenant = debut

    def avancer(self, **duree: float) -> None:
        self.maintenant += dt.timedelta(**duree)

    def installer(self, monkeypatch) -> None:
        horloge = self

        class _DateHeure(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return horloge.maintenant.astimezone(tz) if tz is not None else horloge.maintenant.replace(tzinfo=None)

        monkeypatch.setattr(
            module_capacites,
            "dt",
            types.SimpleNamespace(datetime=_DateHeure, UTC=dt.UTC, timedelta=dt.timedelta),
        )


@pytest.fixture
def monde(base_durable, monkeypatch):
    horloge = Horloge(PREMIERE_RECEPTION)
    horloge.installer(monkeypatch)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "marc.fictif", "Marc Fictif", "mot-de-passe-marc-1234", ["employee"])
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
    departements = charger_departements()
    capacites = Capacites(departements, etat.session, filtre={M4}, appelant=M4, memoire=False)
    return types.SimpleNamespace(capacites=capacites, horloge=horloge)


def _planifier(monde, lead_id: str) -> str:
    """Agent : inscrit et cédule l'intervention de Marc (hors appareil : `m4_planifier_intervention` lui est fermé)."""
    reponse = executer_atomique(
        monde.capacites.index["m4_planifier_intervention"][1],
        {
            "contrat": {
                "lead_id": lead_id,
                "conversation_id": "C1",
                "type_travaux": "renovation_totale",
                "ville": "Montreal",
                "canal": "telephone",
                "contact": {"nom": "Client fictif", "telephone": "0102030405"},
                "urgence_declaree": False,
            },
            "marqueur": {
                "readiness_ok": True,
                "lead_id": lead_id,
                "hash_tete_registre": None,
                "horodatage": "2025-06-01T12:00:00+00:00",
                "empreinte": "ab" * 32,
            },
            "horodatage": "2025-06-02T06:00:00+00:00",
            "sel": SEL,
            "techniciens_disponibles": ["marc.fictif"],
            "fenetres_disponibles": [FENETRE],
        },
    )
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["intervention_id"]


def _appeler(monde, nom, arguments, cle, identite_appelante=MARC, horloge_appareil=APPAREIL_A):
    """Un appel d'appareil tel que le serveur MCP le fait : l'identité authentifiée, puis `Capacites.appeler` avec le
    `_meta` d'idempotence (clé, appareil, heure de l'appareil)."""
    meta = idempotence.Meta(cle=cle, appareil="tel-fictif-t4-27-a2", horodatage_appareil=horloge_appareil)
    with contexte.appele_par_appareil(identite_appelante):
        return monde.capacites.appeler(nom, arguments, meta)


def _report(monde, intervention_id, cle, motif="meteo", horloge_appareil=APPAREIL_A):
    return _appeler(
        monde,
        "m4_signaler_report",
        {"intervention_id": intervention_id, "motif": motif, "horodatage": HEURE_ECRITE},
        cle,
        horloge_appareil=horloge_appareil,
    )


def _ecart(monde, intervention_id, cle, horloge_appareil=APPAREIL_A):
    return _appeler(
        monde,
        "m4_creer_demande_ecart",
        {
            "intervention_id": intervention_id,
            "version_prevue": VERSION_PREVUE,
            "version_declaree": VERSION_DECLAREE,
            "horodatage": HEURE_ECRITE,
        },
        cle,
        horloge_appareil=horloge_appareil,
    )


def _accuse(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _maillons():
    with stockage.transaction():
        return registre_m4.Registre(stockage.maillons(M4, "principal")).lire()


def _ecritures():
    """Ce qu'un renvoi ne doit JAMAIS changer : chaque maillon du registre, octet pour octet."""
    return [dict(m) for m in _maillons()]


def _mutation(cle):
    with stockage.transaction() as cnx:
        lignes = cnx.execute(
            select(MUTATIONS_APPLIQUEES.c.outil, MUTATIONS_APPLIQUEES.c.recu_le, MUTATIONS_APPLIQUEES.c.statut).where(
                MUTATIONS_APPLIQUEES.c.cle_idempotence == cle
            )
        ).all()
    return [tuple(ligne) for ligne in lignes]


def _lire(monde, reference="2025-06-05T13:30:00+00:00"):
    with contexte.appele_par_appareil(ADMIN):
        reponse = monde.capacites.appeler("m4_lire_retards_incidents", {"horodatage_reference": reference})
    return _accuse(reponse)


# =========================================================================================
# 1. Le renvoi de la même clé rend la même heure : celle de la première réception
# =========================================================================================
def test_un_renvoi_de_la_meme_cle_rend_le_meme_report_avec_l_heure_de_la_premiere_reception(monde):
    intervention = _planifier(monde, "L-A")

    premiere = _report(monde, intervention, "cle-report-1")
    assert premiere["ok"] is True and premiere["rejoue"] is False, premiere
    accuse = _accuse(premiere)
    assert accuse["horodatage"] == PREMIERE_RECEPTION.isoformat() and accuse["horodatage_appareil"] == APPAREIL_A
    ecritures = _ecritures()

    monde.horloge.avancer(hours=2)  # le renvoi arrive deux heures plus tard
    renvoi = _report(monde, intervention, "cle-report-1")

    assert renvoi["ok"] is True and renvoi["rejoue"] is True, renvoi
    assert renvoi["resultat"] == premiere["resultat"], "exactement la réponse enregistrée"
    assert _accuse(renvoi)["horodatage"] == PREMIERE_RECEPTION.isoformat(), "jamais une nouvelle heure"
    assert _ecritures() == ecritures, "rien n'est écrit de plus"
    assert _mutation("cle-report-1") == [("m4_signaler_report", PREMIERE_RECEPTION.isoformat(), "ok")]


def test_un_renvoi_de_la_meme_cle_rend_la_meme_demande_d_ecart_avec_l_heure_de_la_premiere_reception(monde):
    intervention = _planifier(monde, "L-B")

    premiere = _ecart(monde, intervention, "cle-ecart-1")
    assert premiere["ok"] is True and premiere["rejoue"] is False, premiere
    accuse = _accuse(premiere)
    assert accuse["horodatage"] == PREMIERE_RECEPTION.isoformat() and accuse["horodatage_appareil"] == APPAREIL_A
    assert accuse["demande_id"] == encodage.empreinte("demande_revue", intervention, PREMIERE_RECEPTION.isoformat())
    ecritures = _ecritures()

    monde.horloge.avancer(hours=2)
    renvoi = _ecart(monde, intervention, "cle-ecart-1")

    assert renvoi["ok"] is True and renvoi["rejoue"] is True, renvoi
    assert renvoi["resultat"] == premiere["resultat"], "même demande_id, même heure, même tête de chaîne"
    assert _ecritures() == ecritures, "une seule demande d'écart, jamais deux"
    assert len([m for m in _maillons() if m["type_entree"] == "demande_revue"]) == 1
    assert _mutation("cle-ecart-1") == [("m4_creer_demande_ecart", PREMIERE_RECEPTION.isoformat(), "ok")]


def test_le_renvoi_rend_aussi_l_heure_de_l_appareil_du_premier_envoi_pas_celle_du_renvoi(monde):
    """L'appareil renvoie avec son horloge d'alors : la réponse enregistrée garde l'heure du premier envoi."""
    intervention = _planifier(monde, "L-A")
    premiere = _report(monde, intervention, "cle-report-1", horloge_appareil=APPAREIL_A)
    monde.horloge.avancer(minutes=7)
    renvoi = _report(monde, intervention, "cle-report-1", horloge_appareil=APPAREIL_B)
    assert renvoi["rejoue"] is True and renvoi["resultat"] == premiere["resultat"]
    assert _accuse(renvoi)["horodatage_appareil"] == APPAREIL_A != APPAREIL_B


def test_un_autre_geste_entre_les_deux_ne_change_pas_l_heure_du_renvoi(monde):
    """Le premier geste garde SON heure, même quand un autre a été reçu plus tard : chaque fait a la sienne."""
    a, b = _planifier(monde, "L-A"), _planifier(monde, "L-B")
    premier = _report(monde, a, "cle-a")
    monde.horloge.avancer(hours=1)
    second = _report(monde, b, "cle-b", motif="client_absent")
    monde.horloge.avancer(hours=1)
    renvoi_du_premier = _report(monde, a, "cle-a")
    assert _accuse(premier)["horodatage"] == "2025-06-05T09:00:00+00:00"
    assert _accuse(second)["horodatage"] == "2025-06-05T10:00:00+00:00"
    assert renvoi_du_premier["rejoue"] is True and renvoi_du_premier["resultat"] == premier["resultat"]
    assert _accuse(renvoi_du_premier)["horodatage"] == "2025-06-05T09:00:00+00:00"


# =========================================================================================
# 2. Une autre clé, ou d'autres arguments : refusés, l'heure du premier report ne bouge pas
# =========================================================================================
def test_une_autre_cle_pour_le_meme_report_est_refusee_et_l_heure_du_premier_reste(monde):
    intervention = _planifier(monde, "L-A")
    _accuse(_report(monde, intervention, "cle-report-1"))
    monde.horloge.avancer(hours=2)

    seconde = _report(monde, intervention, "cle-report-2")

    assert seconde["ok"] is True and seconde["rejoue"] is False
    assert seconde["resultat"]["accepte"] is False
    assert seconde["resultat"]["verdict"]["code"] == "REJ-TRANSITION-ILLEGALE"
    (maillon,) = [m for m in _maillons() if m.get("statut") == "reportee"]
    assert maillon["horodatage"] == PREMIERE_RECEPTION.isoformat(), "l'heure du premier report ne bouge pas"


def test_la_meme_cle_avec_d_autres_arguments_est_un_conflit_nomme_qui_ne_change_rien(monde):
    intervention = _planifier(monde, "L-A")
    _accuse(_report(monde, intervention, "cle-report-1", motif="meteo"))
    ecritures = _ecritures()
    monde.horloge.avancer(hours=2)

    conflit = _report(monde, intervention, "cle-report-1", motif="client_absent")

    assert conflit["ok"] is False and conflit["erreur"] == "mutation_conflit"
    assert _ecritures() == ecritures
    assert _mutation("cle-report-1") == [("m4_signaler_report", PREMIERE_RECEPTION.isoformat(), "ok")]


# =========================================================================================
# 3. Après un renvoi, le relevé lit toujours l'heure de la première réception
# =========================================================================================
def test_apres_un_renvoi_le_releve_lit_toujours_l_heure_de_la_premiere_reception(monde):
    a, b = _planifier(monde, "L-A"), _planifier(monde, "L-B")
    _report(monde, a, "cle-report-1")
    _ecart(monde, b, "cle-ecart-1")
    monde.horloge.avancer(hours=4)
    _report(monde, a, "cle-report-1")  # renvoi
    _ecart(monde, b, "cle-ecart-1")  # renvoi

    releve = _lire(monde, "2025-06-05T13:30:00+00:00")

    (report,) = releve["reports"]["liste"]
    (incident,) = releve["incidents"]["liste"]
    assert (report["depuis"], report["heures_ecoulees"], report["origine_heure"]) == (
        PREMIERE_RECEPTION.isoformat(),
        4,
        "serveur",
    )
    assert (incident["depuis"], incident["heures_ecoulees"], incident["origine_heure"]) == (
        PREMIERE_RECEPTION.isoformat(),
        4,
        "serveur",
    )
    assert releve["reports"]["total"] == 1 and releve["incidents"]["total"] == 1
