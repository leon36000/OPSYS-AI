"""Montage de QA du câblage des connecteurs (tests seulement) : le monde des connecteurs courriel (`courriel_qa`)
plus M1
(registre durable, profil d'entreprise), le sas d'approbation, le bus et le planificateur.

Vrai socle : base SQLite migrée, vrai coffre, vraie file d'onboarding, vrai sas, vrai registre de M1, vrai bus. Seuls le
RÉSEAU et les serveurs de courrier sont des doubles. Personnes et courriels fictifs.
"""

from __future__ import annotations

import dataclasses
import time
from pathlib import Path
from typing import Any

import courriel_doubles as dbl
import courriel_qa as qa

from opsys import approbations, stockage, taxonomie
from opsys.capacites import Capacites, outils_executables
from opsys.connecteurs_planification import etat, planificateur
from opsys.connecteurs_planification.planificateur import Ports
from opsys.console.securite import Session
from opsys.departements import lire_manifeste

RACINE = Path(__file__).resolve().parents[2]
M1 = RACINE / "departments" / "m01-front-office"
ADMIN = qa.ADMIN


@dataclasses.dataclass
class Horloge:
    """Horloge du planificateur : le temps réel, avancé à la main."""

    t: float = dataclasses.field(default_factory=time.time)

    def __call__(self) -> float:
        return self.t

    def avancer(self, secondes: float) -> None:
        self.t += secondes


@dataclasses.dataclass
class Cablage:
    monde: qa.Monde
    horloge: Horloge
    ports: Ports
    capacites: Capacites
    dep: Any

    def tour(self, avance: float = 400.0, **options: Any) -> dict[str, Any]:
        """Un tour du planificateur ; l'horloge avance d'abord pour que le créneau soit échu."""
        self.horloge.avancer(avance)
        return planificateur.tour(None, ports=self.ports, **options)

    def activer(self, executeur: str, mode: str = "actif", motif: str = "essai fictif", intervalle_s: int = 30) -> None:
        with stockage.transaction() as cnx:
            etat.appliquer(cnx, session_admin(), executeur, mode, motif=motif, intervalle_s=intervalle_s,
                           maintenant=self.horloge())

    def decider(self, demande_id: str, approuver: bool = True, par: str = ADMIN) -> dict[str, Any]:
        outils = outils_executables(self.capacites.departements, stockage.transaction)
        with stockage.transaction() as cnx:
            return approbations.decider(cnx, demande_id, approuver, par, outils, self.capacites.departements)


def session_admin(utilisateur: str = ADMIN) -> Session:
    return Session(utilisateur=utilisateur, roles=frozenset({"admin", "nathan_owner"}), csrf="c" * 32,
                   expire=int(time.time()) + 3600)


def monter(tmp_path, monkeypatch, *, recepteur: bool = True, debut: float | None = None, **options: Any) -> Cablage:
    from m1_front_office import outils as outils_m1
    from m1_front_office.courriel_outils import recevoir_courriel_connecteur

    monde = qa.preparer(tmp_path, monkeypatch, **options)
    taxonomie.enregistrer_services(taxonomie.codes_catalogue())
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    outils_m1.utiliser_stockage_durable()
    horloge = Horloge() if debut is None else Horloge(debut)
    ports = Ports(service_courriel=lambda: monde.service, recepteur_m1=recevoir_courriel_connecteur if recepteur
                  else None, horloge=horloge)
    dep = lire_manifeste(M1)
    capacites = Capacites({dep.id: dep}, stockage.transaction, memoire=False)
    planificateur.reinitialiser_arret()
    return Cablage(monde, horloge, ports, capacites, dep)


def demonter() -> None:
    from m1_front_office import outils as outils_m1

    outils_m1.reinitialiser_registre()
    planificateur.reinitialiser_arret()
    stockage.liberer()


def courriel_client(i: int = 1, **options: Any) -> bytes:
    champs = {"objet": f"Question {i}", "corps": "Bonjour, mes gouttières fuient à Laval.",
              "message_id": f"<q{i}@client.example.test>"}
    champs.update(options)
    return dbl.courriel_brut(**champs)


def lignes_m1() -> list[dict[str, Any]]:
    from m1_front_office import outils as outils_m1

    with stockage.transaction():
        return outils_m1._obtenir_registre().lire()
