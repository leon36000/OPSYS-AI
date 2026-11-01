"""Quotas : limites DÉCLARÉES par la classe de connecteur, appliquées AVANT l'envoi, jamais en dormant.

Un `Quota` dit combien de requêtes un fournisseur accepte (par minute, par jour) pour un compte. Le `LimiteurQuota`
compte les requêtes que NOUS envoyons ; s'il en manque, il REFUSE (`REJ-SIGNAUX-QUOTA-LOCAL`, reprenable, avec le délai
d'attente en secondes) au lieu de dormir ou d'envoyer quand même : un tour d'ingestion s'arrête proprement et reprend à
son curseur. Le compte du jour est PERSISTÉ avec le curseur (`curseurs.py`) pour survivre à un redémarrage ; la minute
glissante n'est tenue qu'en mémoire.

AVERTISSEMENT sur les chiffres : ils viennent de la recherche R4 (§3.2, §3.4, niveaux de preuve V/S/H) ou sont un
plafond INTERNE prudent là où aucune valeur officielle n'a été retenue. AUCUN n'a été revérifié contre la
documentation du
fournisseur au moment d'écrire ce module : `a_verifier=True` partout. Le plafond appliqué est le plus bas des deux : le
nôtre ne remplace jamais celui du fournisseur, il s'ajoute.

Module pur : l'horloge est injectée.
"""

from __future__ import annotations

import collections
import dataclasses
from datetime import UTC, datetime, timedelta

from .erreurs import refus


@dataclasses.dataclass(frozen=True)
class Quota:
    par_minute: int | None
    par_jour: int | None
    source: str
    a_verifier: bool = True

    def __post_init__(self) -> None:
        for valeur in (self.par_minute, self.par_jour):
            if valeur is not None and (type(valeur) is not int or valeur < 1):
                raise ValueError("quota : entier >= 1 ou None")


class LimiteurQuota:
    """Compte des requêtes pour UN compte. `deja_aujourdhui` : requêtes déjà comptées ce jour UTC (reprises du curseur
    persisté) ; `jour` : ce jour UTC (AAAA-MM-JJ)."""

    def __init__(self, quota: Quota, *, deja_aujourdhui: int = 0, jour: str | None = None) -> None:
        self._quota = quota
        self._minute: collections.deque[datetime] = collections.deque()
        self._jour = jour
        self._compte_jour = max(0, deja_aujourdhui) if jour is not None else 0

    def restaurer(self, jour: str | None, compte: int) -> None:
        """Reprend le compte du jour persisté avec le curseur (le plus élevé gagne : un redémarrage ne remet jamais le
        compteur à zéro, et le compte d'un autre jour est ignoré)."""
        if jour is None or type(compte) is not int or compte < 0:
            return
        if self._jour in (None, jour):
            self._jour, self._compte_jour = jour, max(self._compte_jour if self._jour == jour else 0, compte)

    @property
    def compte_du_jour(self) -> tuple[str | None, int]:
        return self._jour, self._compte_jour

    def reserver(self, maintenant: datetime) -> None:
        """Compte UNE requête ou refuse avant tout envoi."""
        if maintenant.tzinfo is None:
            raise refus("REJ-SIGNAUX-ARGUMENT-INVALIDE", "horloge sans fuseau", 500)
        maintenant = maintenant.astimezone(UTC)
        aujourd_hui = maintenant.date().isoformat()
        if self._jour != aujourd_hui:
            self._jour, self._compte_jour = aujourd_hui, 0
        q = self._quota
        if q.par_jour is not None and self._compte_jour >= q.par_jour:
            minuit = datetime.combine(maintenant.date() + timedelta(days=1), datetime.min.time(), tzinfo=UTC)
            raise refus(
                "REJ-SIGNAUX-QUOTA-LOCAL",
                f"plafond du jour atteint ({q.par_jour} requêtes) : reprise demain",
                429,
                reprenable=True,
                reessayer_apres_s=max(1, int((minuit - maintenant).total_seconds())),
            )
        if q.par_minute is not None:
            while self._minute and (maintenant - self._minute[0]).total_seconds() >= 60:
                self._minute.popleft()
            if len(self._minute) >= q.par_minute:
                attente = 60 - (maintenant - self._minute[0]).total_seconds()
                raise refus(
                    "REJ-SIGNAUX-QUOTA-LOCAL",
                    f"plafond de la minute atteint ({q.par_minute} requêtes)",
                    429,
                    reprenable=True,
                    reessayer_apres_s=max(1, int(attente) + 1),
                )
            self._minute.append(maintenant)
        self._compte_jour += 1


__all__ = ["LimiteurQuota", "Quota"]
