"""Les exécuteurs de rétention (Loi 25) : purger ce que la politique déclarée demande de ne plus conserver.

Une purge est IRRÉVERSIBLE. Gouvernance (docs/architecture/PLANIFICATION.md §5) :

1. inactif par défaut ; l'ombre CONSTATE ce qui serait purgé et le journalise ;
2. le passage en `actif` est un geste d'admin humain, depuis la console, APRÈS l'aperçu à blanc : l'empreinte de la
   liste
   vue est liée à la décision (`planificateur_approbations`), qui expire avec l'exécuteur (90 jours) ;
3. ensuite la purge est automatique, selon la politique déclarée (rétention du compte, échéance inscrite à l'écriture,
   rétention des traces) ;
4. sans décision valide, l'exécuteur n'efface RIEN, même s'il est inscrit `actif` : le contrôle est refait ici, à chaque
   passage, en plus de celui du planificateur.

Aucun exécuteur ne détruit une clé hors de la liste fermée de `opsys.retention.echeances` : la rétention GPS de M4 (N5,
attestation d'un professionnel) reste un geste humain de M4. Le journal ne porte que des identifiants et des compteurs.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from .. import service_acteur_systeme as systeme
from .. import stockage
from ..stockage.schema import EFFACEMENTS_CLES
from . import etat, journal
from .bail import Bail
from .planificateur import Contexte, EnAttenteTransport, RefusExecuteur

CODE_SANS_APPROBATION = "REJ-PLAN-APPROBATION-IRREVERSIBLE-ABSENTE"
LIMITE_CLES_PAR_PASSAGE = 50


def exiger_approbation(nom: str, ctx: Contexte) -> None:
    with stockage.transaction() as cnx:
        if etat.approbation_valide(cnx, nom, ctx.maintenant()) is None:
            raise RefusExecuteur(CODE_SANS_APPROBATION)


class _Retention:
    nom = ""

    def ressources(self, ctx: Contexte) -> list[str]:
        return ["politique"]

    def cle_bail(self, ressource: str) -> str:
        return f"{self.nom}:{ressource}"

    def constater(self, ressource: str, ctx: Contexte) -> dict[str, Any]:
        """Ombre : combien d'éléments seraient purgés ; RIEN n'est écrit au métier."""
        n = len(self.apercu(ctx))
        with stockage.transaction() as cnx:
            journal.journaliser(cnx, self.nom, "aurait", systeme.IDENTIFIANT, ressource=ressource, mode="ombre",
                                details={"aurait": n})
        return {"aurait": n}

    def _clore(self, ressource: str, **details: int) -> None:
        with stockage.transaction() as cnx:
            journal.journaliser(cnx, self.nom, "ressource", systeme.IDENTIFIANT, ressource=ressource, mode="actif",
                                statut="ok", details=details)


class RetentionCourriel(_Retention):
    nom = "retention.courriel"

    def apercu(self, ctx: Contexte) -> list[dict[str, Any]]:
        from ..retention import courriel

        with stockage.transaction() as cnx:
            return courriel.apercu(cnx, int(ctx.maintenant()))

    def traiter(self, ressource: str, ctx: Contexte, bail: Bail) -> dict[str, Any]:
        from ..ingestion_onboarding import depot
        from ..retention import courriel

        exiger_approbation(self.nom, ctx)
        ctx.exiger_actif(bail)
        with stockage.transaction() as cnx:
            resume = courriel.purger(cnx, int(ctx.maintenant()), depot.dossier_depot(), systeme.IDENTIFIANT)
        total = resume["lots"] + resume["sortants"] + resume["archives"]
        self._clore(ressource, purges=total, documents=resume["documents"], archives=resume["archives"])
        return {"purges": total}


class RetentionCles(_Retention):
    nom = "retention.cles"
    DOMAINES = ("voix", "m1_courriel")

    def _dues(self, ctx: Contexte) -> list[dict[str, Any]]:
        from ..retention import echeances

        sortie: list[dict[str, Any]] = []
        with stockage.transaction() as cnx:
            for domaine in self.DOMAINES:
                sortie += echeances.dues(cnx, domaine, int(ctx.maintenant()), LIMITE_CLES_PAR_PASSAGE)
        return sortie

    def apercu(self, ctx: Contexte) -> list[dict[str, Any]]:
        return [{"categorie": d["domaine"], "ref": d["ref"], "echeance_epoch": d["echeance_epoch"]}
                for d in self._dues(ctx)]

    def traiter(self, ressource: str, ctx: Contexte, bail: Bail) -> dict[str, Any]:
        from ..retention import echeances, voix

        exiger_approbation(self.nom, ctx)
        purgees = 0
        for echeance in self._dues(ctx):
            ctx.exiger_actif(bail)
            quand = echeances.instant(int(ctx.maintenant()))
            with stockage.transaction() as cnx:  # une transaction par clé : le nettoyage de fichiers suit chaque commit
                echeances.detruire(cnx, echeance, quand)
            if echeance["domaine"] == "voix":
                session_id, _, portee = echeance["identifiant"].rpartition("/")
                voix.effacer_fichier(session_id, portee)
            purgees += 1
        self._clore(ressource, purges=purgees)
        return {"purges": purgees}


class RetentionTraces(_Retention):
    nom = "retention.traces"

    def _journal(self, ctx: Contexte) -> Any:
        if ctx.ports.dossier_traces is None:
            raise EnAttenteTransport("REJ-PLAN-TRACES-NON-CONFIGUREES")
        return ctx.ports.dossier_traces()

    def ressources(self, ctx: Contexte) -> list[str]:
        return ["traces"] if self._journal(ctx) is not None else []

    def apercu(self, ctx: Contexte) -> list[dict[str, Any]]:
        journal_traces = self._journal(ctx)
        if journal_traces is None:
            return []
        return [{"categorie": "segment_traces", "ref": nom} for nom in journal_traces.appliquer_retention(a_blanc=True)]

    def traiter(self, ressource: str, ctx: Contexte, bail: Bail) -> dict[str, Any]:
        exiger_approbation(self.nom, ctx)
        ctx.exiger_actif(bail)
        noms = self._journal(ctx).appliquer_retention(a_blanc=False)
        self._clore(ressource, purges=len(noms))
        return {"purges": len(noms)}


class EffacementsReprise:
    """Termine le nettoyage de fichiers d'effacements DÉJÀ autorisés (jamais un nouvel effacement)."""

    nom = "retention.effacements"

    def ressources(self, ctx: Contexte) -> list[str]:
        with stockage.transaction() as cnx:
            n = cnx.execute(select(func.count()).select_from(EFFACEMENTS_CLES).where(
                EFFACEMENTS_CLES.c.etat_fichiers == "en_attente")).scalar_one()
        return ["effacements"] if n else []

    def cle_bail(self, ressource: str) -> str:
        return f"{self.nom}:{ressource}"

    def constater(self, ressource: str, ctx: Contexte) -> dict[str, Any]:
        with stockage.transaction() as cnx:
            n = cnx.execute(select(func.count()).select_from(EFFACEMENTS_CLES).where(
                EFFACEMENTS_CLES.c.etat_fichiers == "en_attente")).scalar_one()
            journal.journaliser(cnx, self.nom, "aurait", systeme.IDENTIFIANT, ressource=ressource, mode="ombre",
                                details={"aurait": int(n)})
        return {"aurait": int(n)}

    def traiter(self, ressource: str, ctx: Contexte, bail: Bail) -> dict[str, Any]:
        from ..cles_chiffrement import reprendre_effacements

        ctx.exiger_actif(bail)
        resultats = reprendre_effacements(limite=4)  # hors transaction : la maintenance l'exige
        termines = sum(1 for r in resultats if r.get("etat_fichiers") == "termine")
        restes = [r for r in resultats if r.get("etat_fichiers") == "en_attente"]
        code = f"EFFACEMENT-{restes[0].get('motif') or 'EN-ATTENTE'}"[:64] if restes else None
        with stockage.transaction() as cnx:
            journal.journaliser(cnx, self.nom, "ressource", systeme.IDENTIFIANT, ressource=ressource, mode="actif",
                                statut="ok", code=code, details={"traites": termines, "ignores": len(restes)})
        return {"traites": termines, "ignores": len(restes), "code": code}
