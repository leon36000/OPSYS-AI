"""Les routines planifiées de M10 (mémoire) : la consolidation nocturne des affaires touchées la veille ou déjà
engagées, l'audit hebdomadaire
« non-oubli » et le calcul des KPI du manifeste. Déclarées au manifeste de M10 (bloc `routines_planifiees`),
déclenchées par le
planificateur durable (docs/architecture/PLANIFICATION.md §10).

La consolidation n'est plus un tour d'agent : l'ÉNUMÉRATEUR (`m10_lister_affaires_a_consolider`, N0) désigne les
affaires dont
le fait durable de la veille manque ou ne cite pas toutes les sources, et chacune est consolidée par l'outil existant
(`m10_consolider_affaire`, N2, idempotent) sous son propre bail : l'échec d'une affaire n'arrête pas les autres.
L'audit et les KPI
écrivent un rapport au registre `rapports_routine` (consultable par `m10_lire_rapports_routine`). Aucun contact
externe, aucune
promotion ni confirmation (décisions humaines). En ombre, la lecture n'écrit aucun fait métier ; le journal
opérationnel conserve les observations et le curseur de parcours.

Le journal du planificateur ne porte jamais l'identifiant d'une affaire : la ressource est `<jour>|<empreinte de
l'affaire>`.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select

from .. import service_acteur_systeme as systeme
from .. import stockage
from ..stockage.schema import PLANIFICATEUR_JOURNAL
from . import journal
from .bail import Bail
from .planificateur import RESSOURCES_PAR_PASSAGE, Contexte, RefusExecuteur
from .routines import ExecuteurRoutine

LISTER = "m10_lister_affaires_a_consolider"
CONSOLIDER = "m10_consolider_affaire"
AUDIT = "m10_executer_audit_non_oubli"
KPIS = "m10_calculer_kpis"
RAFRAICHIR = "m10_rafraichir_contradictions"
JOURS_AUDIT = 7


class ConsolidationAffaires(ExecuteurRoutine):
    """Pour chaque jour engagé : un fait durable qui cite ses sources (rien de plus si déjà fait)."""

    def __init__(self, declaration: Any) -> None:
        super().__init__(declaration)
        self._cibles: dict[str, tuple[str, str]] = {}

    @staticmethod
    def _pseudonyme(affaire: str) -> str:
        return hashlib.sha256(affaire.encode("utf-8")).hexdigest()[:16]

    def _decalage(self, mode: str) -> int:
        """Le prochain index circulaire global, séparé par mode, dans le journal append-only."""
        with stockage.transaction() as cnx:
            brut = cnx.execute(
                select(PLANIFICATEUR_JOURNAL.c.details)
                .where(
                    PLANIFICATEUR_JOURNAL.c.executeur == self.nom[:40],
                    PLANIFICATEUR_JOURNAL.c.evenement == "curseur",
                    PLANIFICATEUR_JOURNAL.c.ressource == "arriere|rotation",
                    PLANIFICATEUR_JOURNAL.c.mode == mode,
                )
                .order_by(PLANIFICATEUR_JOURNAL.c.id.desc())
                .limit(1)
            ).scalar_one_or_none()
        if brut is None:
            return 0
        try:
            valeur = json.loads(brut).get("decalage")
        except (TypeError, ValueError):
            valeur = None
        if type(valeur) is not int or valeur < 0:
            raise RefusExecuteur("REJ-PLAN-ROUTINE-CURSEUR-INVALIDE")
        return valeur

    def _jours_eligibles(self, jusqua: str, mode: str) -> list[str]:
        """Le jour dû et les jours antérieurs dont un curseur prouve que le travail avait commencé."""
        with stockage.transaction() as cnx:
            ressources = cnx.execute(
                select(PLANIFICATEUR_JOURNAL.c.ressource)
                .where(
                    PLANIFICATEUR_JOURNAL.c.executeur == self.nom[:40],
                    PLANIFICATEUR_JOURNAL.c.evenement == "curseur",
                    PLANIFICATEUR_JOURNAL.c.mode == mode,
                )
                .distinct()
            ).scalars()
            marquees = list(ressources)
        jours = {jusqua}
        for ressource in marquees:
            if not isinstance(ressource, str):
                continue
            jour, separateur, type_curseur = ressource.partition("|")
            if separateur != "|" or type_curseur != "rotation":
                continue
            try:
                if date.fromisoformat(jour).isoformat() != jour:
                    continue
            except ValueError:
                continue
            if jour < jusqua:
                jours.add(jour)
        return sorted(jours)

    def _marquer_jour_engage(self, jour: str, mode: str) -> None:
        """Un jour ne devient rattrapable que si son snapshot contient du travail pendant un passage dû."""
        ressource = f"{jour}|rotation"
        with stockage.transaction() as cnx:
            deja_marquee = cnx.execute(
                select(PLANIFICATEUR_JOURNAL.c.id)
                .where(
                    PLANIFICATEUR_JOURNAL.c.executeur == self.nom[:40],
                    PLANIFICATEUR_JOURNAL.c.evenement == "curseur",
                    PLANIFICATEUR_JOURNAL.c.ressource == ressource,
                    PLANIFICATEUR_JOURNAL.c.mode == mode,
                )
                .limit(1)
            ).first()
            if deja_marquee is None:
                journal.journaliser(
                    cnx, self.nom, "curseur", systeme.IDENTIFIANT,
                    ressource=ressource, mode=mode, statut="engage",
                )

    def _avancer_decalage(self, mode: str, decalage: int, reste: int, ressources: int) -> None:
        """Avance AVANT le traitement : un lot qui échoue ne bloque donc pas le prochain lot."""
        with stockage.transaction() as cnx:
            journal.journaliser(
                cnx,
                self.nom,
                "curseur",
                systeme.IDENTIFIANT,
                ressource="arriere|rotation",
                mode=mode,
                statut="avance",
                details={"decalage": decalage, "reste": reste, "ressources": ressources},
            )

    def ressources(self, ctx: Contexte) -> list[str]:
        super().ressources(ctx)
        self._verifier(ctx)
        due, aujourd_hui = self.echeance(ctx)
        if not due:
            return []
        veille = (date.fromisoformat(aujourd_hui) - timedelta(days=1)).isoformat()
        mode = getattr(ctx, "mode", "actif")
        decalage = self._decalage(mode)
        jours = self._jours_eligibles(veille, mode)
        from m10_memoire.routines_outils import enumeration_arriere_interne

        with enumeration_arriere_interne(veille, jours, decalage):
            liste = self.resultat(
                self._appeler(ctx, LISTER, {"jour": veille, "limite": RESSOURCES_PAR_PASSAGE})
            )
        self._cibles = {}
        affaires = liste["a_consolider"]
        pendantes = int(liste["pendantes"])
        prochain_decalage = (decalage % pendantes + len(affaires)) % pendantes if pendantes else 0
        if veille in liste["jours"]:
            self._marquer_jour_engage(veille, mode)
        for couple in affaires:
            jour, affaire = couple["jour"], couple["affaire_id"]
            ressource = f"{jour}|{self._pseudonyme(affaire)}"
            if mode == "ombre" and self.deja_fait(ressource, ctx):
                continue
            self._cibles[ressource] = (jour, affaire)
        if affaires and (self._cibles or liste["reste"]):
            self._avancer_decalage(mode, prochain_decalage, int(liste["reste"]), len(affaires))
        return sorted(self._cibles)

    def constater(self, ressource: str, ctx: Contexte) -> dict[str, Any]:
        self._journaliser_aurait(ressource, aurait=1)
        return {"aurait": 1}

    def traiter(self, ressource: str, ctx: Contexte, bail: Bail) -> dict[str, Any]:
        cible = self._cibles.get(ressource)
        if cible is None:
            raise RefusExecuteur("REJ-PLAN-ROUTINE-RESSOURCE-INCONNUE")
        jour, affaire = cible
        ctx.exiger_actif(bail)
        reponse = self._appeler(
            ctx, CONSOLIDER, {"affaire_id": affaire, "jour": jour, "horodatage": self.instant_iso(ctx)}
        )
        if reponse.get("verdict"):
            raise RefusExecuteur(str(reponse["verdict"]))
        ecrit = 1 if reponse.get("ecrit") else 0
        self._clore(ressource, None, etapes=1, affaires=ecrit)
        return {"etapes": 1, "affaires": ecrit}


class AuditNonOubli(ExecuteurRoutine):
    """Une fois par semaine prévue : l'audit « non-oubli », rapport consultable."""

    def ressources(self, ctx: Contexte) -> list[str]:
        super().ressources(ctx)
        self._verifier(ctx)
        due, jour = self.echeance(ctx)
        return [jour] if due and not self.deja_fait(jour, ctx) else []

    def constater(self, ressource: str, ctx: Contexte) -> dict[str, Any]:
        rapport = self.resultat(
            self._appeler(ctx, AUDIT, {"fin": self.instant_iso(ctx), "jours": JOURS_AUDIT, "ecrire": False})
        )
        self._journaliser_aurait(ressource, aurait=1, oublis=int(rapport["nb_oublis"]))
        return {"aurait": 1}

    def traiter(self, ressource: str, ctx: Contexte, bail: Bail) -> dict[str, Any]:
        ctx.exiger_actif(bail)
        rapport = self.resultat(self._appeler(ctx, AUDIT, {"fin": self.instant_iso(ctx), "jours": JOURS_AUDIT}))
        self._clore(ressource, None, etapes=1, oublis=int(rapport["nb_oublis"]), rapports=1 if rapport["ecrit"] else 0)
        return {"etapes": 1, "oublis": int(rapport["nb_oublis"]), "rapports": 1 if rapport["ecrit"] else 0}


class KpisMemoire(ExecuteurRoutine):
    """Une fois par jour, après la consolidation : les KPI du manifeste, vers un résultat consultable."""

    def ressources(self, ctx: Contexte) -> list[str]:
        super().ressources(ctx)
        self._verifier(ctx)
        due, jour = self.echeance(ctx)
        return [jour] if due and not self.deja_fait(jour, ctx) else []

    @staticmethod
    def _cycle(jour: str, fuseau: str) -> tuple[str, str]:
        """La journée locale du cycle de consolidation, en UTC : `[minuit local, minuit local suivant[`."""
        zone = ZoneInfo(fuseau)
        debut = datetime.combine(date.fromisoformat(jour), datetime.min.time(), zone)
        fin = datetime.combine(date.fromisoformat(jour) + timedelta(days=1), datetime.min.time(), zone)
        return debut.astimezone(UTC).isoformat(), fin.astimezone(UTC).isoformat()

    def _arguments(self, ressource: str, ctx: Contexte) -> dict[str, Any]:
        debut, fin = self._cycle(ressource, ctx.ports.fuseau)
        return {"jour": ressource, "debut_cycle": debut, "fin_cycle": fin, "horodatage": self.instant_iso(ctx)}

    def constater(self, ressource: str, ctx: Contexte) -> dict[str, Any]:
        calcul = self.resultat(self._appeler(ctx, KPIS, {**self._arguments(ressource, ctx), "ecrire": False}))
        self._journaliser_aurait(
            ressource, aurait=1, elements=sum(1 for k in calcul["kpis"].values() if k.get("calculable"))
        )
        return {"aurait": 1}

    def traiter(self, ressource: str, ctx: Contexte, bail: Bail) -> dict[str, Any]:
        ctx.exiger_actif(bail)
        calcul = self.resultat(self._appeler(ctx, KPIS, self._arguments(ressource, ctx)))
        self._clore(ressource, None, etapes=1, rapports=1 if calcul["ecrit"] else 0)
        return {"etapes": 1, "rapports": 1 if calcul["ecrit"] else 0}


class RafraichirContradictions(ExecuteurRoutine):
    """Une fois par jour : détecte, range et marque les contradictions entre affirmations de sources différentes, et
    ouvre au sas la demande d'approbation d'une contradiction critique. Ne supprime rien, ne tranche rien seule.

    En ombre, seul le calcul à blanc est appelé (`ecrire` faux) : l'exécuteur dit ce qu'il AURAIT rangé et demandé."""

    def ressources(self, ctx: Contexte) -> list[str]:
        super().ressources(ctx)
        self._verifier(ctx)
        due, jour = self.echeance(ctx)
        return [jour] if due and not self.deja_fait(jour, ctx) else []

    def constater(self, ressource: str, ctx: Contexte) -> dict[str, Any]:
        bilan = self.resultat(self._appeler(ctx, RAFRAICHIR, {"horodatage": self.instant_iso(ctx), "ecrire": False}))
        self._journaliser_aurait(
            ressource, aurait=1, contradictions=int(bilan["nouvelles"]), demandes=int(bilan["demandes_a_ouvrir"]),
            traites=int(bilan["auto_resolues"]),
        )
        return {"aurait": 1}

    def traiter(self, ressource: str, ctx: Contexte, bail: Bail) -> dict[str, Any]:
        ctx.exiger_actif(bail)
        bilan = self.resultat(self._appeler(ctx, RAFRAICHIR, {"horodatage": self.instant_iso(ctx)}))
        resume = {
            "etapes": 1, "contradictions": int(bilan["nouvelles"]), "traites": int(bilan["auto_resolues"]),
            "demandes": int(bilan["demandes_ouvertes"]), "differees": int(bilan["demandes_differees"]),
        }
        self._clore(ressource, None, **resume)
        return resume


ROUTINES = {
    "m10:contradictions-memoire": RafraichirContradictions,
    "m10:consolidation-affaires": ConsolidationAffaires,
    "m10:audit-non-oubli": AuditNonOubli,
    "m10:kpis-memoire": KpisMemoire,
}
