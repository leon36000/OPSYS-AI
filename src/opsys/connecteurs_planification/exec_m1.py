"""Les routines planifiées de M1 (réception) : le digest quotidien de la réceptionniste, les alertes internes (rappels
échus,
conversations sans suivi, urgences non prises en charge) et le calcul des KPI. Déclarées au manifeste de M1 (bloc
`routines_planifiees`), déclenchées par le planificateur durable (docs/architecture/PLANIFICATION.md §10).

Ce que ces exécuteurs font : LIRE le registre de M1 (`m1_lire_attentes_reception`, N0) et CONSIGNER des avis internes
qui
deviennent des attentes « À voir » (`m1_consigner_a_voir_reception`, N2), ou calculer des KPI (`m1_calculer_kpis`, N2).
Ce qu'ils
ne font jamais : écrire, appeler ou notifier un client, demander l'envoi d'un brouillon, clore un transfert (décision de
personne). En ombre, ils ne lisent que (l'écriture n'est jamais appelée) et journalisent « aurait ».
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from .bail import Bail
from .planificateur import Contexte
from .routines import ExecuteurRoutine

LIRE = "m1_lire_attentes_reception"
CONSIGNER = "m1_consigner_a_voir_reception"
KPIS = "m1_calculer_kpis"
FENETRE_KPI_JOURS = 30


class DigestReception(ExecuteurRoutine):
    """Une fois par jour prévu, à l'heure du cron suivi : le digest de la réception, vers « À voir »."""

    def ressources(self, ctx: Contexte) -> list[str]:
        super().ressources(ctx)
        self._verifier(ctx)
        due, jour = self.echeance(ctx)
        return [jour] if due and not self.deja_fait(jour, ctx) else []

    def constater(self, ressource: str, ctx: Contexte) -> dict[str, Any]:
        lecture = self.resultat(self._appeler(ctx, LIRE, {"maintenant": self.instant_iso(ctx), "jour": ressource}))
        aurait = int(lecture["a_consigner"]["digest"] or 0)
        self._journaliser_aurait(ressource, aurait=aurait)
        return {"aurait": aurait}

    def traiter(self, ressource: str, ctx: Contexte, bail: Bail) -> dict[str, Any]:
        ctx.exiger_actif(bail)
        ecrit = self.resultat(
            self._appeler(ctx, CONSIGNER, {"groupe": "digest", "maintenant": self.instant_iso(ctx), "jour": ressource})
        )["ecrits"]
        self._clore(ressource, None, etapes=1, notices=ecrit)
        return {"etapes": 1, "notices": ecrit}


class _Alertes(ExecuteurRoutine):
    """Sondage à intervalle : ne fait rien tant que rien n'est à consigner (le journal ne grossit pas à vide)."""

    GROUPE = ""

    def _arguments(self, ctx: Contexte) -> dict[str, Any]:
        return {"maintenant": self.instant_iso(ctx)}

    def ressources(self, ctx: Contexte) -> list[str]:
        super().ressources(ctx)
        self._verifier(ctx)
        lecture = self.resultat(self._appeler(ctx, LIRE, self._arguments(ctx)))
        if not lecture["a_consigner"][self.GROUPE]:
            return []
        lot = f"{self.GROUPE}-{lecture['lots'][self.GROUPE]}"
        return [] if self.deja_fait(lot, ctx) and getattr(ctx, "mode", "actif") == "ombre" else [lot]

    def constater(self, ressource: str, ctx: Contexte) -> dict[str, Any]:
        lecture = self.resultat(self._appeler(ctx, LIRE, self._arguments(ctx)))
        aurait = int(lecture["a_consigner"][self.GROUPE] or 0)
        self._journaliser_aurait(ressource, aurait=aurait)
        return {"aurait": aurait}

    def traiter(self, ressource: str, ctx: Contexte, bail: Bail) -> dict[str, Any]:
        ctx.exiger_actif(bail)
        ecrit = self.resultat(self._appeler(ctx, CONSIGNER, {"groupe": self.GROUPE, **self._arguments(ctx)}))["ecrits"]
        self._clore(ressource, None, etapes=1, notices=ecrit)
        return {"etapes": 1, "notices": ecrit}


class RappelsEtSuivis(_Alertes):
    """Un rappel dont l'échéance (choisie par une personne) est passée ; une conversation dont la fenêtre est terminée
    sans que la prochaine action soit faite."""

    GROUPE = "echeances"


class Urgences(_Alertes):
    """Une urgence de sécurité encore ouverte après un intervalle COMPLET de contrôle (celui que l'administrateur a
    réglé :
    aucun délai de service n'est inventé)."""

    GROUPE = "urgences"

    def _arguments(self, ctx: Contexte) -> dict[str, Any]:
        return {"maintenant": self.instant_iso(ctx), "delai_controle_s": self._intervalle()}


class KpisReception(ExecuteurRoutine):
    """Une fois par jour : les KPI de réception des 30 jours finissant la veille, vers un résultat consultable."""

    def ressources(self, ctx: Contexte) -> list[str]:
        super().ressources(ctx)
        self._verifier(ctx)
        due, jour = self.echeance(ctx)
        return [jour] if due and not self.deja_fait(jour, ctx) else []

    @staticmethod
    def _veille(ressource: str) -> str:
        return (date.fromisoformat(ressource) - timedelta(days=1)).isoformat()

    def constater(self, ressource: str, ctx: Contexte) -> dict[str, Any]:
        calcul = self.resultat(
            self._appeler(
                ctx,
                KPIS,
                {
                    "jour": self._veille(ressource),
                    "maintenant": self.instant_iso(ctx),
                    "jours": FENETRE_KPI_JOURS,
                    "ecrire": False,
                },
            )
        )
        calculables = sum(1 for k in calcul["kpis"].values() if k.get("calculable"))
        self._journaliser_aurait(ressource, aurait=1, elements=calculables)
        return {"aurait": 1}

    def traiter(self, ressource: str, ctx: Contexte, bail: Bail) -> dict[str, Any]:
        ctx.exiger_actif(bail)
        calcul = self.resultat(
            self._appeler(
                ctx,
                KPIS,
                {"jour": self._veille(ressource), "maintenant": self.instant_iso(ctx), "jours": FENETRE_KPI_JOURS},
            )
        )
        self._clore(ressource, None, etapes=1, notices=1 if calcul["ecrit"] else 0)
        return {"etapes": 1, "notices": 1 if calcul["ecrit"] else 0}


ROUTINES = {
    "m1:digest-reception": DigestReception,
    "m1:rappels-et-suivis": RappelsEtSuivis,
    "m1:urgences": Urgences,
    "m1:kpis-reception": KpisReception,
}
