"""Montage de QA de la planification autonome (tests seulement) : une instance SQLite migrée, un admin fictif, les VRAIS
départements demandés et le VRAI planificateur. Seuls les transports (réseau, modèles) sont des doubles ; l'horloge est
avancée à la main. Personnes et données fictives."""

from __future__ import annotations

import dataclasses
import time
from pathlib import Path
from typing import Any

from opsys import identite, stockage
from opsys.connecteurs_planification import etat, planificateur
from opsys.connecteurs_planification.planificateur import Ports
from opsys.console.securite import Session
from opsys.departements import lire_manifeste

RACINE = Path(__file__).resolve().parents[2]
ADMIN = "nathan"


@dataclasses.dataclass
class Horloge:
    t: float = dataclasses.field(default_factory=time.time)

    def __call__(self) -> float:
        return self.t

    def avancer(self, secondes: float) -> None:
        self.t += secondes


def session_admin(utilisateur: str = ADMIN) -> Session:
    return Session(utilisateur=utilisateur, roles=frozenset({"admin", "nathan_owner"}), csrf="c" * 32,
                   expire=int(time.time()) + 3600)


@dataclasses.dataclass
class Planif:
    horloge: Horloge
    ports: Ports
    departements: dict[str, Any]

    def tour(self, avance: float = 400.0, **options: Any) -> dict[str, Any]:
        """Un tour ; l'horloge avance d'abord pour que le créneau soit échu."""
        self.horloge.avancer(avance)
        return planificateur.tour(self.departements, ports=self.ports, **options)

    def activer(self, executeur: str, mode: str = "actif", *, intervalle_s: int = 30, motif: str = "essai fictif"
                ) -> dict[str, Any]:
        """Un geste d'admin ; un exécuteur irréversible passe par l'aperçu et la confirmation, comme à la console."""
        extra: dict[str, Any] = {}
        definition = etat.definition(executeur)
        if definition is not None and definition.irreversible and mode == "actif":
            apercu = planificateur.apercu(executeur, ports=self.ports, departements=self.departements)
            extra = {"apercu_empreinte": apercu["empreinte"], "confirme_irreversible": True,
                     "apercu_courant": lambda: (apercu["empreinte"], apercu["nombre"])}
        with stockage.transaction() as cnx:
            return etat.appliquer(cnx, session_admin(), executeur, mode, motif=motif, intervalle_s=intervalle_s,
                                  maintenant=self.horloge(), **extra)

    def ligne(self, executeur: str) -> Any:
        with stockage.transaction() as cnx:
            return etat.ligne(cnx, executeur)


def monter(tmp_path, monkeypatch, departements: tuple[str, ...] = (), **ports: Any) -> Planif:
    url = f"sqlite:///{tmp_path / 'planif.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, ADMIN, "Nathan Propriétaire (fictif)", "mot-de-passe-nathan-1234",
                                ["nathan_owner", "admin"])
    deps = {}
    for nom in departements:
        dep = lire_manifeste(RACINE / "departments" / nom)
        deps[dep.id] = dep
    horloge = Horloge()
    planificateur.reinitialiser_arret()
    return Planif(horloge, Ports(horloge=horloge, **ports), deps)


def demonter() -> None:
    planificateur.reinitialiser_arret()
    stockage.liberer()
