"""Monde d'interconnexion (tests seulement) : base SQLite migrée, manifestes RÉELS des départements, VRAI bus.

Aucun consommateur factice : `repartir` appelle les `consommateurs()` réels des départements chargés. Seuls le réseau et
les serveurs externes sont absents. Données fictives. L'horloge du bus est celle de l'appelant (`maintenant`), avancée
d'une heure à chaque passe pour que les reprises après échec (backoff) soient dues.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
from collections.abc import Callable
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from sqlalchemy import select

from opsys import evenements, stockage
from opsys.departements import Departement, charger_departements
from opsys.stockage.maillons import MaillonsDurables
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS

RACINE = Path(__file__).resolve().parents[2]
DEBUT = dt.datetime(2026, 11, 2, 10, 0, tzinfo=dt.UTC)


# Consommateur réel en cours d'exécution (posé par l'enveloppe d'observation, vide hors livraison).
_COURANT: ContextVar[tuple[str, str] | None] = ContextVar("interconnexion_consommateur_courant", default=None)


class _DepartementObserve:
    """Enveloppe d'un département RÉEL : les fonctions de `consommateurs()` sont les vraies ; seule l'identité du
    consommateur en cours est posée pendant leur exécution, pour que `Monde.ecritures` dise QUI a écrit OÙ."""

    def __init__(self, departement: Departement) -> None:
        self._departement = departement

    def __getattr__(self, nom: str) -> Any:
        return getattr(self._departement, nom)

    def charger_consommateurs(self) -> dict[str, Callable]:
        def envelopper(type_evenement: str, fonction: Callable) -> Callable:
            def appeler(charge):
                jeton = _COURANT.set((self._departement.id, type_evenement))
                try:
                    return fonction(charge)
                finally:
                    _COURANT.reset(jeton)

            return appeler

        return {t: envelopper(t, f) for t, f in self._departement.charger_consommateurs().items()}


@dataclasses.dataclass
class Monde:
    departements: dict[str, Departement]
    horloge: dt.datetime = DEBUT
    ecritures: list[dict[str, str]] = dataclasses.field(default_factory=list)
    pannes: set[str] = dataclasses.field(default_factory=set)

    def surveiller(self, monkeypatch) -> None:
        """Observe chaque écriture de registre faite PAR un consommateur (qui, où) et permet `panne()`."""
        original = MaillonsDurables.append
        monde = self
        self.departements = {i: _DepartementObserve(d) for i, d in self.departements.items()}

        def append(registre, maillon, **options):
            courant = _COURANT.get()
            if courant is not None:
                if registre.departement in monde.pannes:
                    raise ConnectionError(f"panne simulée du stockage de {registre.departement}")
                monde.ecritures.append(
                    {
                        "consommateur": courant[0],
                        "type": courant[1],
                        "departement": registre.departement,
                        "registre": registre.registre,
                    }
                )
            return original(registre, maillon, **options)

        monkeypatch.setattr(MaillonsDurables, "append", append)

    def ecritures_hors_propriete(self) -> list[dict[str, str]]:
        """Écritures d'un consommateur dans le registre d'un AUTRE département (doit toujours être vide)."""
        return [e for e in self.ecritures if e["consommateur"] != e["departement"]]

    def taille(self, departement: str, registre: str) -> int:
        with stockage.transaction():
            return len(stockage.maillons(departement, registre))

    def repartir(
        self, passes: int = 6, limite: int = 500, departements: tuple[str, ...] | None = None
    ) -> dict[str, int]:
        """Plusieurs passes du vrai répartiteur : une chaîne de consommateurs publie des événements que la passe
        suivante livre. Retourne les totaux. `departements` restreint les abonnés (panne d'un département)."""
        deps = self.departements if departements is None else {d: self.departements[d] for d in departements}
        total = {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
        for _ in range(passes):
            self.horloge += dt.timedelta(hours=1)
            resume = evenements.repartir(deps, limite=limite, maintenant=self.horloge.isoformat())
            for cle in total:
                total[cle] += resume.get(cle, 0)
            if resume.get("livres", 0) == 0:
                break
        return total

    def recus(self, *, consommateur: str | None = None, statut: str | None = None) -> list[dict[str, Any]]:
        with stockage.transaction() as cnx:
            requete = select(EVENEMENTS_RECUS)
            if consommateur is not None:
                requete = requete.where(EVENEMENTS_RECUS.c.consommateur == consommateur)
            if statut is not None:
                requete = requete.where(EVENEMENTS_RECUS.c.statut == statut)
            return [dict(ligne) for ligne in cnx.execute(requete).mappings()]

    def quarantaines(self) -> list[dict[str, Any]]:
        return evenements.etat()["quarantaine"]

    def sortants(self, type_evenement: str | None = None) -> list[dict[str, Any]]:
        with stockage.transaction() as cnx:
            requete = select(EVENEMENTS_SORTANTS)
            if type_evenement is not None:
                requete = requete.where(EVENEMENTS_SORTANTS.c.type_evenement == type_evenement)
            return [dict(ligne) for ligne in cnx.execute(requete).mappings()]

    def registre(self, departement: str, nom: str) -> list[dict[str, Any]]:
        with stockage.transaction():
            return list(stockage.maillons(departement, nom))

    def statut(self, evenement_id: str, consommateur: str) -> str | None:
        for ligne in self.recus(consommateur=consommateur):
            if ligne["evenement_id"] == evenement_id:
                return ligne["statut"]
        return None


def monter(tmp_path, monkeypatch, departements: tuple[str, ...] | None = None) -> Monde:
    """Base migrée + manifestes réels (tous les départements, ou le sous-ensemble demandé)."""
    url = f"sqlite:///{tmp_path / 'interconnexion.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "instance-fictive"))
    stockage.migrer(url)
    tous = charger_departements(RACINE / "departments")
    choisis = {d: tous[d] for d in (departements or tuple(tous))}
    from m1_front_office import outils as m1
    from m2_revenue_crm import outils as m2
    from m5_financecore import outils as m5

    m1.utiliser_stockage_durable()
    m2.utiliser_stockage_durable()
    m5.utiliser_stockage_durable()
    return Monde(choisis)


def demonter() -> None:
    stockage.liberer()
