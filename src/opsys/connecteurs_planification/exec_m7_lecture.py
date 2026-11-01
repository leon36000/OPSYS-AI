"""Les exécuteurs de LECTURE de M7 : signaux marketing, veille concurrentielle, fonds du studio (modèles locaux).

Les tours existaient (`signaux.ingestion.tour_ingestion`, `veille.collecte.tour_veille`, `studio.executeur.executer`)
mais aucun planificateur ne les appelait. Ce module les raccorde SANS rien y changer : il choisit QUOI faire passer,
sous bail, et laisse chaque tour faire ses propres contrôles (curseur persisté, quota, robots.txt, tentatives).

Aucun transport réel n'existe pour eux dans cette version : les ports (`Ports.fabrique_signaux`, `fabrique_veille`,
`fabrique_studio`) sont `None` en production, et un exécuteur qui aurait du travail le DIT (« en attente de
transport »). Rien n'est simulé ; les tests y branchent des doubles.

`m7.studio.fonds` n'exécute que les demandes dont le modèle sélectionné est LOCAL (sans coût, sans transfert hors de
l'instance). Un modèle par API est payant et envoie l'invite hors du Québec : c'est un engagement (N3 et plus) ; sans
mécanisme d'approbation de dépense pour la génération, il n'est JAMAIS exécuté ici (compté « refusé », code typé).
"""

from __future__ import annotations

from typing import Any

from .. import service_acteur_systeme as systeme
from .. import stockage
from . import journal
from .bail import Bail
from .planificateur import Contexte, EnAttenteTransport, RefusExecuteur

CODE_PAYANT = "REJ-PLAN-GENERATION-PAYANTE-APPROBATION-REQUISE"


def _m7():
    try:
        from m7_marketing.signaux import comptes, ingestion
        from m7_marketing.signaux import registre as registre_signaux
        from m7_marketing.studio import actifs, modeles
        from m7_marketing.studio import executeur as exec_studio
        from m7_marketing.studio.service import FichiersStudio
        from m7_marketing.veille import collecte
        from m7_marketing.veille import registre as registre_veille
    except ImportError:
        raise RefusExecuteur("REJ-PLAN-M7-ABSENT") from None
    return {"comptes": comptes, "ingestion": ingestion, "registre_signaux": registre_signaux, "actifs": actifs,
            "modeles": modeles, "exec_studio": exec_studio, "FichiersStudio": FichiersStudio, "collecte": collecte,
            "registre_veille": registre_veille}


def _horodatage(ctx: Contexte) -> str:
    return ctx.maintenant_dt().strftime("%Y-%m-%dT%H:%M:%SZ")


class SignauxM7:
    nom = "m7.signaux"

    def _comptes(self) -> dict[tuple[str, str], Any]:
        m7 = _m7()
        return m7["comptes"].actifs(stockage.maillons(*m7["registre_signaux"].REGISTRE_COMPTES))

    def ressources(self, ctx: Contexte) -> list[str]:
        comptes = self._comptes()
        if comptes and ctx.ports.fabrique_signaux is None:
            raise EnAttenteTransport("REJ-SIGNAUX-TRANSPORT-NON-BRANCHE")
        return [f"{source}:{ref}" for source, ref in sorted(comptes)]

    def cle_bail(self, ressource: str) -> str:
        return f"m7.signaux:{ressource}"

    def constater(self, ressource: str, ctx: Contexte) -> dict[str, Any]:
        with stockage.transaction() as cnx:
            journal.journaliser(cnx, self.nom, "aurait", systeme.IDENTIFIANT, ressource=ressource, mode="ombre",
                                details={"aurait": 1})
        return {"aurait": 1}

    def traiter(self, ressource: str, ctx: Contexte, bail: Bail) -> dict[str, Any]:
        m7 = _m7()
        source, _, ref = ressource.partition(":")
        compte = self._comptes().get((source, ref))
        if compte is None:  # désactivé entre l'énumération et le bail : rien à faire
            return {"ignores": 1}
        if ctx.ports.fabrique_signaux is None:
            raise EnAttenteTransport("REJ-SIGNAUX-TRANSPORT-NON-BRANCHE")
        connecteur = ctx.ports.fabrique_signaux(compte, ctx.maintenant_dt)
        bilan = m7["ingestion"].tour_ingestion(connecteur, maintenant=ctx.maintenant_dt, arret=ctx.arret_demande)
        pages = erreurs = traites = 0
        code = None
        for flux in bilan["flux"]:
            pages += int(flux["pages"])
            traites += int(flux["faits_nouveaux"]) + int(flux["faits_revises"])
            if flux["statut"] == "echec":
                erreurs += 1
                code = (flux.get("erreur") or {}).get("code") or "REJ-PLAN-ECHEC"
        if code == "REJ-SIGNAUX-TRANSPORT-NON-BRANCHE":
            raise EnAttenteTransport(code)
        with stockage.transaction() as cnx:
            journal.journaliser(cnx, self.nom, "ressource", systeme.IDENTIFIANT, ressource=ressource, mode="actif",
                                statut="erreur" if erreurs else "ok", code=code,
                                details={"appels": pages, "traites": traites, "erreurs": erreurs})
        return {"appels": pages, "traites": traites, "erreurs": erreurs, "code": code}


class VeilleM7:
    nom = "m7.veille"

    def _concurrents(self):
        m7 = _m7()
        reg = m7["registre_veille"]
        return reg.plier(stockage.maillons(*reg.REGISTRE))

    def ressources(self, ctx: Contexte) -> list[str]:
        reg = _m7()["registre_veille"]
        if not reg.sources_actives(self._concurrents()):
            return []
        if ctx.ports.fabrique_veille is None:
            raise EnAttenteTransport("REJ-VEILLE-TRANSPORT-NON-BRANCHE")
        return ["veille"]

    def cle_bail(self, ressource: str) -> str:
        return f"m7.veille:{ressource}"

    def constater(self, ressource: str, ctx: Contexte) -> dict[str, Any]:
        reg = _m7()["registre_veille"]
        n = len(reg.sources_actives(self._concurrents()))
        with stockage.transaction() as cnx:
            journal.journaliser(cnx, self.nom, "aurait", systeme.IDENTIFIANT, ressource=ressource, mode="ombre",
                                details={"aurait": n})
        return {"aurait": n}

    def traiter(self, ressource: str, ctx: Contexte, bail: Bail) -> dict[str, Any]:
        m7 = _m7()
        if ctx.ports.fabrique_veille is None:
            raise EnAttenteTransport("REJ-VEILLE-TRANSPORT-NON-BRANCHE")
        concurrents = self._concurrents()
        collecteur = ctx.ports.fabrique_veille(concurrents, ctx.maintenant_dt)  # un collecteur NEUF par tour
        journal_obs = stockage.maillons("m07-marketing", "observations_concurrents")
        bilan = m7["collecte"].tour_veille(collecteur, journal_obs, concurrents=concurrents,
                                           maintenant=ctx.maintenant_dt)
        echecs = bilan["echecs"]
        code = echecs[0]["code"] if echecs else None
        if code == "REJ-VEILLE-TRANSPORT-NON-BRANCHE":
            raise EnAttenteTransport(code)
        with stockage.transaction() as cnx:
            journal.journaliser(cnx, self.nom, "ressource", systeme.IDENTIFIANT, ressource=ressource, mode="actif",
                                statut="erreur" if echecs else "ok", code=code, details={
                                    "appels": collecteur.pages_demandees, "traites": bilan["nouvelles"],
                                    "ignores": bilan["deja_presentes"], "erreurs": len(echecs)})
        return {"appels": collecteur.pages_demandees, "traites": bilan["nouvelles"], "erreurs": len(echecs),
                "code": code}


class FondsStudio:
    nom = "m7.studio.fonds"

    def _a_faire(self) -> list[str]:
        m7 = _m7()
        executeur = m7["exec_studio"]
        jobs, refus = executeur.charger(stockage.maillons("m07-marketing", "jobs_studio"))
        if refus is not None:
            raise RefusExecuteur(refus["refus"][0]["code"])
        return sorted(j for j, e in jobs.items() if e.etat in ("en_attente", "echec")
                      and e.echecs < executeur.TENTATIVES_MAX)

    def ressources(self, ctx: Contexte) -> list[str]:
        jobs = self._a_faire()
        if jobs and ctx.ports.fabrique_studio is None:
            raise EnAttenteTransport("REJ-STUDIO-ADAPTATEUR-ABSENT")
        return jobs

    def cle_bail(self, ressource: str) -> str:
        return f"m7.studio:{ressource}"

    def _selection(self, genre: str) -> Any:
        m7 = _m7()
        try:
            with stockage.transaction() as cnx:
                return m7["modeles"].selectionner(cnx, genre)
        except m7["modeles"].ModeleRefuse as exc:
            raise RefusExecuteur(exc.code) from None

    def _genre(self, job_id: str) -> str:
        jobs, _ = _m7()["exec_studio"].charger(stockage.maillons("m07-marketing", "jobs_studio"))
        return jobs[job_id].demande["demande"]["genre"]

    def constater(self, ressource: str, ctx: Contexte) -> dict[str, Any]:
        """Ombre : combien de demandes partiraient (modèle local) et combien seraient refusées (modèle payant)."""
        payant = self._selection(self._genre(ressource)).fournisseur.mode != "local"
        with stockage.transaction() as cnx:
            journal.journaliser(cnx, self.nom, "aurait", systeme.IDENTIFIANT, ressource=ressource, mode="ombre",
                                details={"refuses": 1} if payant else {"aurait": 1})
        return {"refuses": 1} if payant else {"aurait": 1}

    def traiter(self, ressource: str, ctx: Contexte, bail: Bail) -> dict[str, Any]:
        m7 = _m7()
        if ctx.ports.fabrique_studio is None:
            raise EnAttenteTransport("REJ-STUDIO-ADAPTATEUR-ABSENT")
        selection = self._selection(self._genre(ressource))
        if selection.fournisseur.mode != "local":
            # Payant et hors instance : engagement N3+, jamais exécuté par l'acteur système sans approbation.
            with stockage.transaction() as cnx:
                journal.journaliser(cnx, self.nom, "ressource", systeme.IDENTIFIANT, ressource=ressource,
                                    mode="actif", statut="refuse", code=CODE_PAYANT, details={"refuses": 1})
            return {"refuses": 1, "code": CODE_PAYANT}
        adaptateurs = ctx.ports.fabrique_studio()
        fichiers = m7["FichiersStudio"](stockage.dossier_opsys() / "studio")
        ctx.exiger_actif(bail)
        resultat = m7["exec_studio"].executer(
            stockage.maillons("m07-marketing", "jobs_studio"), stockage.maillons("m07-marketing", "provenance_studio"),
            stockage.maillons("m07-marketing", "actifs_studio"), ressource, adaptateurs=adaptateurs,
            resoudre_modele=lambda genre: selection,
            ecrire_fond=lambda sha, octets, fmt: fichiers.ecrire(
                f"fonds/{m7['actifs'].identifiant_fond(sha)}.{fmt}", octets),
            par=systeme.IDENTIFIANT, horodatage=_horodatage(ctx), maintenant=ctx.maintenant_dt())
        accepte = bool(resultat.get("accepte"))
        code = None if accepte else resultat["refus"][0]["code"]
        with stockage.transaction() as cnx:
            journal.journaliser(cnx, self.nom, "ressource", systeme.IDENTIFIANT, ressource=ressource, mode="actif",
                                statut="ok" if accepte else "erreur", code=code,
                                details={"appels": 0 if resultat.get("deja_execute") else 1, "traites": 1})
        return {"appels": 0 if resultat.get("deja_execute") else 1, "traites": 1 if accepte else 0,
                "erreurs": 0 if accepte else 1, "code": code}
