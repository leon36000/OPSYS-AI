"""Les exécuteurs des départements et de la vérification : ce qui était livré (outils N0 à N2, calculs, constats) mais
qu'aucun planificateur ne déclenchait (docs/architecture/PLANIFICATION.md).

- `m8.entrepot` : reconstruction de l'entrepôt dérivé de M8, publication des faits consolidés, santé de l'entreprise ;
- `m5.cycle` : cycle d'opérations comptables de M5 (brouillons, relances PRÉPARÉES, flux fournisseurs, préclôture,
  mesures) : jamais un paiement, un envoi ni une clôture ;
- `m10.mnemo` : le « mnemo-quotidien » du manifeste de M10 (soi, synchronisation du graphe, leçons, surveillance) ;
- `m10.connaissances.reindexation` : bascule vers l'espace d'embeddings courant (transport d'embeddings requis) ;
- `sauvegarde.verification` : authentification de la plus récente archive chiffrée, sans rien écrire ;
- `peremptions.balayage` : constat des sources périmées et des échéances de rétention en retard.

Règle commune : un outil de département n'est appelé que s'il figure dans la liste fermée de l'exécuteur ET s'il est
déclaré N0, N1 ou N2 (`appeler_outil`). L'appel est DIRECT (`executer_atomique` : une transaction par outil) et non
par le répartiteur d'outils, qui poserait l'identité d'un département et fermerait l'acteur système. Une étape refusée
arrête la séquence et son code typé est journalisé ; une étape rejouée ne crée rien de plus (idempotence propre aux
outils, prouvée par leurs tests).
"""

from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

from .. import service_acteur_systeme as systeme
from .. import stockage
from ..outils import Niveau, executer_atomique
from . import journal
from .bail import Bail
from .planificateur import Contexte, EnAttenteTransport, NiveauInterdit, RefusExecuteur

NIVEAUX_AUTOMATIQUES = frozenset({Niveau.N0, Niveau.N1, Niveau.N2})
_CODE = re.compile(r"REJ-[A-Z0-9]+(?:-[A-Z0-9]+)+")


def appeler_outil(ctx: Contexte, nom: str, arguments: dict[str, Any], *, autorises: frozenset[str]) -> Any:
    """Appelle un outil de département N0 à N2 de la liste `autorises` et rend son résultat (JSON). Tout refus devient
    un `RefusExecuteur` typé (le tour le journalise) ; un outil N3 ou plus lève `NiveauInterdit` AVANT tout appel."""
    if nom not in autorises:
        raise NiveauInterdit("REJ-PLAN-OUTIL-HORS-LISTE")
    outil = ctx.outils().get(nom)
    if outil is None:
        raise RefusExecuteur("REJ-PLAN-OUTIL-ABSENT")
    if outil.niveau_effectif not in NIVEAUX_AUTOMATIQUES or outil.frontiere_humaine:
        raise NiveauInterdit("REJ-PLAN-NIVEAU-INTERDIT")
    reponse = executer_atomique(outil, arguments)
    if not reponse.get("ok"):
        trouve = _CODE.search(str(reponse.get("details") or reponse.get("erreur") or ""))
        raise RefusExecuteur(trouve.group(0) if trouve else "REJ-PLAN-OUTIL-REFUSE")
    return reponse["resultat"]


class _ParOutils:
    """Un exécuteur qui enchaîne les outils N0 à N2 d'UN département, sur une ressource unique (« instance »)."""

    nom = ""
    departement = ""
    outils: tuple[str, ...] = ()

    def ressources(self, ctx: Contexte) -> list[str]:
        if ctx.departements is None or self.departement not in ctx.departements:
            raise RefusExecuteur("REJ-PLAN-DEPARTEMENT-ABSENT")
        return ["instance"]

    def cle_bail(self, ressource: str) -> str:
        return f"{self.nom}:{ressource}"

    def _verifier(self, ctx: Contexte) -> None:
        for nom in self.outils:
            outil = ctx.outils().get(nom)
            if outil is None:
                raise RefusExecuteur("REJ-PLAN-OUTIL-ABSENT")
            if outil.niveau_effectif not in NIVEAUX_AUTOMATIQUES or outil.frontiere_humaine:
                raise NiveauInterdit("REJ-PLAN-NIVEAU-INTERDIT")

    def constater(self, ressource: str, ctx: Contexte) -> dict[str, Any]:
        """Ombre : les outils existent et sont de niveau automatique ; RIEN n'est appelé."""
        self._verifier(ctx)
        with stockage.transaction() as cnx:
            journal.journaliser(cnx, self.nom, "aurait", systeme.IDENTIFIANT, ressource=ressource, mode="ombre",
                                details={"aurait": len(self.outils)})
        return {"aurait": len(self.outils)}

    def _appeler(self, ctx: Contexte, nom: str, arguments: dict[str, Any]) -> Any:
        return appeler_outil(ctx, nom, arguments, autorises=frozenset(self.outils))

    def _clore(self, ressource: str, code: str | None, **details: int) -> None:
        with stockage.transaction() as cnx:
            journal.journaliser(cnx, self.nom, "ressource", systeme.IDENTIFIANT, ressource=ressource, mode="actif",
                                statut="erreur" if code else "ok", code=code, details=details)


class EntrepotM8(_ParOutils):
    nom = "m8.entrepot"
    departement = "m08-analytics"
    outils = ("m8_construire_entrepot", "m8_publier_faits_consolides", "m8_enregistrer_sante_entreprise")

    def traiter(self, ressource: str, ctx: Contexte, bail: Bail) -> dict[str, Any]:
        maintenant = ctx.maintenant_dt().isoformat()
        etapes = inchanges = 0
        code = None
        construit = self._appeler(ctx, "m8_construire_entrepot", {"maintenant": maintenant})
        etapes += 1
        statut = construit.get("statut")
        if statut == "inchange":
            inchanges += 1
        elif statut == "concurrent":
            code = "REJ-PLAN-ENTREPOT-CONCURRENT"  # une autre construction a gagné : rien d'écrit, on reprend plus tard
        ctx.exiger_actif(bail)
        publie = self._appeler(ctx, "m8_publier_faits_consolides", {"maintenant": maintenant})
        etapes += 1
        inchanges += 0 if publie.get("nouvelle") else 1
        ctx.exiger_actif(bail)
        self._appeler(ctx, "m8_enregistrer_sante_entreprise", {"maintenant": maintenant})
        etapes += 1
        self._clore(ressource, code, etapes=etapes, inchanges=inchanges)
        return {"etapes": etapes, "inchanges": inchanges, "code": code}


class CycleM5(_ParOutils):
    nom = "m5.cycle"
    departement = "m05-financecore"
    outils = ("m5_executer_cycle_comptable",)

    @staticmethod
    def periode_precedente(aujourd_hui: str) -> str:
        """Le mois qui vient de se terminer (AAAA-MM) : celui qu'on préclôture. Calcul pur sur la date du jour."""
        premier = aujourd_hui[:7] + "-01"
        from datetime import date

        veille = date.fromisoformat(premier) - timedelta(days=1)
        return veille.isoformat()[:7]

    def traiter(self, ressource: str, ctx: Contexte, bail: Bail) -> dict[str, Any]:
        aujourd_hui = ctx.aujourd_hui()
        recu = self._appeler(ctx, "m5_executer_cycle_comptable", {
            "aujourd_hui": aujourd_hui, "horodatage": ctx.maintenant_dt().isoformat(),
            "periode": self.periode_precedente(aujourd_hui)})
        if not recu.get("accepte"):
            raise RefusExecuteur("REJ-PLAN-CYCLE-REFUSE")
        etapes = recu["resultat"]["etapes"]
        faites = sum(1 for e in etapes if e.get("issue") == "FAIT")
        refusees = [e for e in etapes if e.get("issue") == "REFUSEE"]
        a_declarer = [e for e in etapes if e.get("issue") == "A_DECLARER"]
        # Une étape REFUSÉE est une erreur visible ; une étape À DÉCLARER (politique de relance non renseignée) n'en est
        # pas une, mais son code reste affiché : le propriétaire sait ce qu'il doit déclarer.
        code = (refusees[0].get("code") if refusees else a_declarer[0].get("code") if a_declarer else None)
        self._clore(ressource, code if refusees else None, etapes=faites, erreurs=len(refusees))
        return {"etapes": faites, "erreurs": len(refusees), "code": code}


class Mnemo(_ParOutils):
    nom = "m10.mnemo"
    departement = "m10-memoire"
    outils = ("m10_construire_soi", "m10_synchroniser_graphe", "m10_extraire_lecons", "m10_surveiller_lecons")
    PAGES_GRAPHE_MAX = 200

    def traiter(self, ressource: str, ctx: Contexte, bail: Bail) -> dict[str, Any]:
        etapes = 0
        self._appeler(ctx, "m10_construire_soi", {})
        etapes += 1
        pages, decalage = 0, 0
        while True:  # la synchronisation est paginée : on suit `suivant` jusqu'à la fin, ou jusqu'à l'arrêt demandé
            bail = ctx.exiger_actif(bail)
            page = self._appeler(ctx, "m10_synchroniser_graphe", {"decalage": decalage, "limite": 500})
            pages += 1
            decalage = page.get("suivant")
            if decalage is None or pages >= self.PAGES_GRAPHE_MAX or ctx.arret_demande():
                break
        etapes += 1
        ctx.exiger_actif(bail)
        self._appeler(ctx, "m10_extraire_lecons", {})
        etapes += 1
        self._appeler(ctx, "m10_surveiller_lecons", {})
        etapes += 1
        self._clore(ressource, None, etapes=etapes, **{"pages": pages})
        return {"etapes": etapes, "pages": pages}


class ReindexationConnaissances:
    nom = "m10.connaissances.reindexation"

    def _bases_a_reindexer(self, ctx: Contexte) -> list[str]:
        from ..connaissances import lecture

        with stockage.transaction() as cnx:
            etat = lecture.etat_bases(cnx, maintenant=ctx.maintenant_dt())
        bases = etat["bases"]
        return [b["departement"] for b in bases if b["reindexation_requise"]]

    def ressources(self, ctx: Contexte) -> list[str]:
        bases = self._bases_a_reindexer(ctx)
        if bases and not (ctx.ports.embeddings_raccordes and ctx.ports.embeddings_raccordes()):
            # Le registre a changé de modèle mais aucun adaptateur d'embeddings n'est raccordé : on le DIT.
            raise EnAttenteTransport("REJ-CONN-EMBEDDINGS-NON-RACCORDE")
        return bases

    def cle_bail(self, ressource: str) -> str:
        return f"m10.connaissances:{ressource}"

    def constater(self, ressource: str, ctx: Contexte) -> dict[str, Any]:
        with stockage.transaction() as cnx:
            journal.journaliser(cnx, self.nom, "aurait", systeme.IDENTIFIANT, ressource=ressource, mode="ombre",
                                details={"aurait": 1})
        return {"aurait": 1}

    def traiter(self, ressource: str, ctx: Contexte, bail: Bail) -> dict[str, Any]:
        from ..connaissances import index, ports
        from ..connaissances.codes import EMBEDDINGS_NON_RACCORDE, ErreurConnaissances
        from ..connaissances.modele import instant_iso

        ctx.exiger_actif(bail)
        try:
            with stockage.transaction() as cnx:
                port = ports.resoudre_embeddeur(cnx, ressource)
                rapport = index.reindexer(cnx, departement=ressource, port=port, par=systeme.IDENTIFIANT,
                                          quand=instant_iso(ctx.maintenant_dt()))
        except ErreurConnaissances as exc:
            if exc.code == EMBEDDINGS_NON_RACCORDE:
                raise EnAttenteTransport(exc.code) from None
            raise RefusExecuteur(exc.code) from None
        ecrits = int(rapport["vecteurs_ecrits"])
        with stockage.transaction() as cnx:
            journal.journaliser(cnx, self.nom, "ressource", systeme.IDENTIFIANT, ressource=ressource, mode="actif",
                                statut="ok", details={"appels": ecrits, "traites": rapport["fragments_total"]})
        return {"appels": ecrits, "traites": int(rapport["fragments_total"])}


class VerificationSauvegarde:
    nom = "sauvegarde.verification"
    AGE_MAX_S = 2 * 86400 + 3600

    def ressources(self, ctx: Contexte) -> list[str]:
        if ctx.ports.verifier_sauvegarde is None:
            raise EnAttenteTransport("REJ-PLAN-SAUVEGARDE-NON-CONFIGUREE")
        return ["sauvegardes"]

    def cle_bail(self, ressource: str) -> str:
        return f"{self.nom}:{ressource}"

    def constater(self, ressource: str, ctx: Contexte) -> dict[str, Any]:
        """La vérification est une LECTURE : l'ombre la fait aussi (c'est ce qui la rend utile), sans rien écrire."""
        return self._verifier(ctx)

    def _verifier(self, ctx: Contexte) -> dict[str, Any]:
        rapport = dict(ctx.ports.verifier_sauvegarde())  # type: ignore[misc]
        if not rapport.get("trouvee"):
            raise RefusExecuteur("REJ-PLAN-SAUVEGARDE-ABSENTE")
        if not rapport.get("authentique"):
            raise RefusExecuteur(str(rapport.get("code") or "REJ-PLAN-SAUVEGARDE-ALTEREE"))
        age = rapport.get("age_s")
        if type(age) is not int or age > getattr(ctx.ports, "sauvegarde_age_max_s", self.AGE_MAX_S):
            raise RefusExecuteur("REJ-PLAN-SAUVEGARDE-TROP-ANCIENNE")
        return {"traites": 1}

    def traiter(self, ressource: str, ctx: Contexte, bail: Bail) -> dict[str, Any]:
        try:
            resultat = self._verifier(ctx)
        except RefusExecuteur as exc:
            with stockage.transaction() as cnx:
                journal.journaliser(cnx, self.nom, "ressource", systeme.IDENTIFIANT, ressource=ressource,
                                    mode="actif", statut="erreur", code=exc.code)
            raise
        with stockage.transaction() as cnx:
            journal.journaliser(cnx, self.nom, "ressource", systeme.IDENTIFIANT, ressource=ressource, mode="actif",
                                statut="ok", details={"traites": 1})
        return resultat


class BalayagePeremptions:
    """Constate ce qui est périmé ; ne corrige RIEN (la révision d'une source, la purge d'une échéance et le
    renouvellement d'un consentement sont d'autres gestes, d'autres niveaux)."""

    nom = "peremptions.balayage"

    def ressources(self, ctx: Contexte) -> list[str]:
        return ["instance"]

    def cle_bail(self, ressource: str) -> str:
        return f"{self.nom}:{ressource}"

    def _constat(self, ctx: Contexte) -> dict[str, int]:
        from sqlalchemy import func, select

        from ..connaissances import lecture
        from ..stockage.schema import RETENTION_ECHEANCES

        with stockage.transaction() as cnx:
            etat = lecture.etat_bases(cnx, maintenant=ctx.maintenant_dt())
            bases = etat["bases"]
            echeances_en_retard = cnx.execute(select(func.count()).select_from(RETENTION_ECHEANCES).where(
                RETENTION_ECHEANCES.c.statut == "en_attente",
                RETENTION_ECHEANCES.c.echeance_epoch <= int(ctx.maintenant()))).scalar_one()
        return {"expires": sum(len(b["sources_perimees"]) for b in bases),
                "aurait": sum(len(b["revisions_a_venir"]) for b in bases),
                "purges": int(echeances_en_retard)}

    def constater(self, ressource: str, ctx: Contexte) -> dict[str, Any]:
        return self._constat(ctx)

    def traiter(self, ressource: str, ctx: Contexte, bail: Bail) -> dict[str, Any]:
        constat = self._constat(ctx)
        a_signaler = constat["expires"] + constat["purges"]
        code = "REJ-PLAN-PEREMPTION-DETECTEE" if a_signaler else None
        with stockage.transaction() as cnx:
            journal.journaliser(cnx, self.nom, "constat", systeme.IDENTIFIANT, ressource=ressource, mode="actif",
                                statut="ok", code=code, details=constat)
        return {"traites": 1, "code": code}
