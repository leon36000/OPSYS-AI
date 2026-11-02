"""L'exécuteur du rapport marketing hebdomadaire de M7 (boucle B) : `m7.rapport-hebdo`.

Même patron que les constats planifiés de M8 (`constats.py`) : inactif par défaut, ombre d'abord, niveau N2, acteur
système,
aucun envoi externe. Il COMPOSE deux lectures de départements différents, ce qu'un constat à outil unique ne peut pas
faire :

- les MESURES de l'entrepôt de M8 (`m8_lire_mesures`, `m8_lire_mesures_contenus` : N0, liste fermée de
`appeler_outil`, sans
  identité d'appareil ni droit élargi) : coût par lead, leads et devis par contenu. M7 n'importe jamais le code de M8 ;
- le dossier de M7 lui-même (performance des campagnes, calendrier, avis, croissance), lu par
`m7_marketing.rapport_hebdo.sources`.

Puis `m7_marketing.rapport_hebdo.service.constater` compose, enregistre UN rapport par semaine, crée les tâches
internes de
niveau bas et annonce les observations de mémoire (`m7.apprentissage_marketing_constate`), dans une seule transaction.

- **La semaine** est la dernière semaine ISO complète avant la date locale du jour : le planificateur peut passer
chaque jour,
  la semaine ne change que le lundi, et le rapport est écrit UNE fois (idempotence par semaine, au-dessus de
  l'idempotence
  de l'identifiant d'événement). Un passage de plus dans la même semaine ne lit même pas M8.
- **Ombre** : constate qu'il pourrait lire M8, quelle semaine il rapporterait et s'il existe déjà ; n'écrit rien, ne
publie rien.
- **Panne et reprise** : si M8 ne répond pas, RIEN n'est écrit (un rapport dégradé ne verrouillerait pas la semaine) ;
le tour
  suivant reprend. Une source qui répond « non calculable » est une donnée, pas une panne : le rapport le dit.
- **Aucun effet externe** : ni publication, ni dépense, ni envoi ; les recommandations sont des lignes internes.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from .. import service_acteur_systeme as systeme
from .. import stockage
from . import journal
from .bail import Bail
from .exec_departements import _ParOutils, appeler_outil
from .planificateur import Contexte, RefusExecuteur

M7, M8 = "m07-marketing", "m08-analytics"
PAGES_MAX = 60


def _m7() -> dict[str, Any]:
    try:
        from m7_marketing.rapport_hebdo import composition, semaine, service, sources
    except ImportError:
        raise RefusExecuteur("REJ-PLAN-M7-ABSENT") from None
    return {"composition": composition, "semaine": semaine, "service": service, "sources": sources}


class RapportHebdoM7(_ParOutils):
    nom = "m7.rapport-hebdo"
    departement = M7
    outils = ("m8_lire_mesures", "m8_lire_mesures_contenus")

    def ressources(self, ctx: Contexte) -> list[str]:
        if ctx.departements is None or M7 not in ctx.departements or M8 not in ctx.departements:
            raise RefusExecuteur("REJ-PLAN-DEPARTEMENT-ABSENT")
        return ["rapport"]

    def _semaine(self, ctx: Contexte) -> tuple[str, str, str]:
        semaine = _m7()["semaine"]
        debut, fin = semaine.derniere_semaine_complete(dt.date.fromisoformat(ctx.aujourd_hui()))
        return debut.isoformat(), fin.isoformat(), ctx.maintenant_dt().isoformat(timespec="seconds")

    def _existe(self, debut: str) -> bool:
        with stockage.transaction():
            return _m7()["service"].rapport_de(debut) is not None

    def constater(self, ressource: str, ctx: Contexte) -> dict[str, Any]:
        """Ombre : les outils de M8 existent (N0 à N2), M7 est présent ; quelle semaine, déjà rapportée ou non. RIEN
        n'est lu
        chez M8, rien n'est écrit, rien n'est publié."""
        self._verifier(ctx)
        debut, _fin, _ = self._semaine(ctx)
        aurait = 0 if self._existe(debut) else 1
        with stockage.transaction() as cnx:
            journal.journaliser(
                cnx,
                self.nom,
                "aurait",
                systeme.IDENTIFIANT,
                ressource=ressource,
                mode="ombre",
                details={"aurait": aurait},
            )
        return {"aurait": aurait}

    def _lire_m8(
        self, ctx: Contexte, composition: Any, maintenant: str
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        mesures: list[dict[str, Any]] = []
        depart = 0
        for _ in range(PAGES_MAX):
            page = appeler_outil(
                ctx,
                "m8_lire_mesures",
                {"maintenant": maintenant, "depart": depart, "metric_ids": list(composition.MESURES_M8)},
                autorises=frozenset(self.outils),
            )
            mesures.extend(page.get("mesures", []))
            depart = page.get("prochain_depart")
            if depart is None:
                break
        else:
            raise RefusExecuteur("REJ-PLAN-RAPPORT-PAGINATION")
        contenus: list[dict[str, Any]] = []
        depart = 0
        for _ in range(PAGES_MAX):
            page = appeler_outil(ctx, "m8_lire_mesures_contenus", {"depart": depart}, autorises=frozenset(self.outils))
            contenus.extend(page.get("contenus", []))
            affichage = page.get("affichage", {})
            depart = affichage.get("prochain_depart")
            if depart is None:
                break
        else:
            raise RefusExecuteur("REJ-PLAN-RAPPORT-PAGINATION")
        return mesures, contenus

    def traiter(self, ressource: str, ctx: Contexte, bail: Bail) -> dict[str, Any]:
        m7 = _m7()
        debut, fin, maintenant = self._semaine(ctx)
        if self._existe(debut):  # un seul rapport par semaine : on ne relit même pas M8
            self._clore(ressource, None, ignores=1)
            return {"ignores": 1}
        bail = ctx.exiger_actif(bail) or bail
        try:
            mesures, contenus = self._lire_m8(ctx, m7["composition"], maintenant)
        except RefusExecuteur as exc:
            # M8 ne répond pas : rien n'est écrit, la semaine reste libre pour le tour suivant
            self._clore(ressource, exc.code, erreurs=1)
            raise
        ctx.exiger_actif(bail)
        with stockage.transaction():
            propres, anomalies = m7["sources"].lire(dt.date.fromisoformat(debut), dt.date.fromisoformat(fin))
            resultat = m7["service"].constater(
                {**propres, "m8_mesures": mesures, "m8_contenus": contenus}, debut, maintenant
            )
        code = (
            None
            if resultat["statut"] in ("enregistre", "deja_present")
            else resultat.get("code", "REJ-PLAN-RAPPORT-REFUSE")
        )
        self._clore(
            ressource,
            code,
            traites=1 if resultat["statut"] == "enregistre" else 0,
            ignores=1 if resultat["statut"] == "deja_present" else 0,
            erreurs=len(anomalies),
        )
        return {"traites": 1 if resultat["statut"] == "enregistre" else 0, "code": code, "anomalies": sorted(anomalies)}
