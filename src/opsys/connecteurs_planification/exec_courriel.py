"""Les exécuteurs courriel : synchronisation incrémentale des comptes connectés, et envoi UNIQUE des brouillons
approuvés.

`courriel.synchro` (N2) : par compte connecté, sous bail, `IngestionCourriel` lit les nouvelles pages (reprise sur
curseur persisté APRÈS la page, quota de débit, idempotence par `Message-ID` et empreinte), dépose les pièces dans la
file d'onboarding (brouillons à confirmer) et, pour un compte qui l'a demandé, transmet les courriels ENTRANTS à M1.

`courriel.envoi` (N3, approbation consommée) : par compte, sous bail, chaque brouillon `APPROUVE` est envoyé par
`ServiceEnvoi.envoyer`, qui présente le jeton (demande du sas + empreinte) à l'adaptateur ; la garde du sas relit
l'approbation (humaine, exécutée, non expirée), la consomme par comparaison-échange AVANT le premier octet réseau, puis
l'adaptateur transmet. Une approbation expirée ou invalide rend le brouillon `ECHEC` (une nouvelle demande est requise)
sans toucher au réseau. Une réservation jamais terminée devient `INCERTAIN` (jamais de reprise automatique).

Un compte partage son bail entre les deux exécuteurs (`courriel.compte:<id>`) : jamais une synchronisation et un envoi
en même temps sur les mêmes jetons.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select, update

from .. import evenements, stockage
from .. import service_acteur_systeme as systeme
from ..courriel_connecteurs import comptes, envoi
from ..courriel_connecteurs.erreurs import ErreurCourriel
from ..courriel_connecteurs.ingestion import IngestionCourriel, LimiteurDebit
from ..stockage.schema import COURRIEL_BROUILLONS, COURRIEL_COMPTES
from . import journal
from .bail import Bail
from .planificateur import RefusExecuteur

TYPE_ENVOYE = "m1.courriel_envoye"
TYPE_ECHOUE = "m1.envoi_courriel_echoue"
PRODUCTEUR = "m01-front-office"


def _cle_compte(compte_id: str) -> str:
    return f"courriel.compte:{compte_id}"


class Synchro:
    nom = "courriel.synchro"

    def ressources(self, ctx: Any) -> list[str]:
        with stockage.transaction() as cnx:
            return [r[0] for r in cnx.execute(select(COURRIEL_COMPTES.c.compte_id).where(
                COURRIEL_COMPTES.c.etat == "connecte").order_by(COURRIEL_COMPTES.c.compte_id))]

    def cle_bail(self, ressource: str) -> str:
        return _cle_compte(ressource)

    def constater(self, ressource: str, ctx: Any) -> dict[str, Any]:
        with stockage.transaction() as cnx:
            journal.journaliser(cnx, self.nom, "aurait", systeme.IDENTIFIANT, ressource=ressource, mode="ombre",
                                details={"aurait": 1})
        return {"aurait": 1}

    def _limiteur(self, ctx: Any, compte_id: str) -> LimiteurDebit:
        ports = ctx.ports
        if compte_id not in ports.limiteurs:
            ports.limiteurs[compte_id] = LimiteurDebit(ports.messages_par_minute, ctx.ports.horloge)
        return ports.limiteurs[compte_id]

    def traiter(self, ressource: str, ctx: Any, bail: Bail) -> dict[str, Any]:
        if ctx.ports.service_courriel is None:
            raise RefusExecuteur("REJ-PLAN-COURRIEL-NON-RACCORDE")
        service = ctx.ports.service_courriel()
        courant = {"bail": bail}

        def entre_pages() -> None:
            courant["bail"] = ctx.exiger_actif(courant["bail"])

        try:
            fournisseur = service.fournisseur(ressource)
        except ErreurCourriel as exc:
            return {"erreurs": 1, "code": exc.code}
        ingestion = IngestionCourriel(
            stockage.transaction, acteur=systeme.IDENTIFIANT, limiteur=self._limiteur(ctx, ressource),
            taille_page=ctx.ports.taille_page, pages_max=ctx.ports.pages_par_passage,
            signaler=service.signaler_erreur, recepteur=ctx.ports.recepteur_m1, entre_pages=entre_pages)
        rapports = ingestion.synchroniser_compte(ressource, fournisseur)
        total = {"messages": 0, "pages": 0, "erreurs": 0, "recus_m1": 0, "contacts": 0}
        code = None
        for rapport in rapports.values():
            total["messages"] += rapport.nouveaux
            total["pages"] += rapport.pages
            total["recus_m1"] += rapport.recus_m1
            total["contacts"] += rapport.contacts
            if rapport.statut == "erreur":
                total["erreurs"] += 1
                code = rapport.code
        with stockage.transaction() as cnx:
            journal.journaliser(cnx, self.nom, "ressource", systeme.IDENTIFIANT, ressource=ressource, mode="actif",
                                statut="erreur" if code else "ok", code=code, details={
                                    "messages": total["messages"], "pages": total["pages"],
                                    "traites": total["recus_m1"], "ressources": len(rapports)})
        return {**total, "code": code}


class Envoi:
    nom = "courriel.envoi"

    def _approuves(self, compte_id: str | None = None) -> list[dict[str, Any]]:
        with stockage.transaction() as cnx:
            requete = select(COURRIEL_BROUILLONS.c.brouillon_id, COURRIEL_BROUILLONS.c.compte_id,
                             COURRIEL_BROUILLONS.c.empreinte, COURRIEL_BROUILLONS.c.demande_id).where(
                COURRIEL_BROUILLONS.c.statut == "APPROUVE").order_by(COURRIEL_BROUILLONS.c.cree_le,
                                                                      COURRIEL_BROUILLONS.c.brouillon_id)
            if compte_id is not None:
                requete = requete.where(COURRIEL_BROUILLONS.c.compte_id == compte_id)
            return [dict(r) for r in cnx.execute(requete).mappings()]

    def avant(self, ctx: Any) -> None:
        """Mode actif seulement : une réservation jamais terminée (réponse perdue) devient INCERTAINE, sans rejeu."""
        with stockage.transaction() as cnx:
            envoi.marquer_reservations_orphelines(cnx)

    def ressources(self, ctx: Any) -> list[str]:
        return sorted({b["compte_id"] for b in self._approuves()})

    def cle_bail(self, ressource: str) -> str:
        return _cle_compte(ressource)

    def _validite(self, ctx: Any) -> int:
        return ctx.ports.validite_envoi_s or envoi.VALIDITE_APPROBATION_S

    def constater(self, ressource: str, ctx: Any) -> dict[str, Any]:
        """Ombre : combien partiraient (approbation valable) et combien seraient refusés (expirée, invalide)."""
        partiraient = refuses = 0
        for b in self._approuves(ressource):
            with stockage.transaction() as cnx:
                try:
                    envoi.verifier_demande(cnx, b["demande_id"], validite_s=self._validite(ctx),
                                           horloge=ctx.ports.horloge)
                    partiraient += 1
                except ErreurCourriel:
                    refuses += 1
        with stockage.transaction() as cnx:
            journal.journaliser(cnx, self.nom, "aurait", systeme.IDENTIFIANT, ressource=ressource, mode="ombre",
                                details={"aurait": partiraient, "refuses": refuses})
        return {"aurait": partiraient, "refuses": refuses}

    def _marquer_echec(self, brouillon_id: str, code: str) -> None:
        with stockage.transaction() as cnx:
            resultat = cnx.execute(update(COURRIEL_BROUILLONS).where(
                COURRIEL_BROUILLONS.c.brouillon_id == brouillon_id, COURRIEL_BROUILLONS.c.statut == "APPROUVE").values(
                statut="ECHEC", code=code, termine_le=comptes.instant(), modifie_le=comptes.instant()))
            if resultat.rowcount == 1:
                ligne = cnx.execute(select(COURRIEL_BROUILLONS.c.compte_id).where(
                    COURRIEL_BROUILLONS.c.brouillon_id == brouillon_id)).scalar_one()
                comptes.journaliser(cnx, ligne, "envoi.refuse", systeme.IDENTIFIANT, code=code,
                                    details={"brouillon_id": brouillon_id})

    def _evenement_echec(self, b: dict[str, Any], issue: str, code: str) -> None:
        with stockage.transaction():
            evenements.publier(TYPE_ECHOUE, PRODUCTEUR, {
                "brouillon_id": b["brouillon_id"], "empreinte": b["empreinte"], "compte_id": b["compte_id"],
                "issue": issue, "code": code},
                evenement_id=f"m1-envoi-echoue-{b['brouillon_id']}-{b['empreinte'][:16]}")

    def traiter(self, ressource: str, ctx: Any, bail: Bail) -> dict[str, Any]:
        if ctx.ports.service_courriel is None:
            raise RefusExecuteur("REJ-PLAN-COURRIEL-NON-RACCORDE")
        envoyes = refuses = incertains = 0
        code = None
        courant = bail
        service = ctx.ports.service_courriel()
        for b in self._approuves(ressource):
            courant = ctx.exiger_actif(courant)
            # Garde du planificateur (en plus de celle de l'adaptateur) : l'acteur système n'envoie QUE sur une
            # approbation humaine exécutée et non expirée ; sinon le brouillon est refusé, le réseau n'est pas touché.
            with stockage.transaction() as cnx:
                try:
                    envoi.verifier_demande(cnx, b["demande_id"], validite_s=self._validite(ctx),
                                           horloge=ctx.ports.horloge)
                    refus = None
                except ErreurCourriel as exc:
                    refus = exc
            if refus is not None:
                self._marquer_echec(b["brouillon_id"], refus.code)
                self._evenement_echec(b, "refuse", refus.code)
                refuses += 1
                code = refus.code
                continue
            try:
                fournisseur = service.fournisseur(b["compte_id"])
                recu = envoi.ServiceEnvoi(stockage.transaction).envoyer(fournisseur, b["brouillon_id"])
            except ErreurCourriel as exc:
                code = exc.code
                if exc.code == "REJ-COURRIEL-LIMITE-DEBIT":
                    break  # rien n'est parti ; le même jeton resservira au prochain passage
                issue = "incertain" if exc.code == "REJ-COURRIEL-ENVOI-INCERTAIN" else "echec"
                incertains += issue == "incertain"
                refuses += issue != "incertain"
                self._evenement_echec(b, issue, exc.code)
                continue
            envoyes += 1
            with stockage.transaction():
                evenements.publier(TYPE_ENVOYE, PRODUCTEUR, {
                    "brouillon_id": b["brouillon_id"], "empreinte": b["empreinte"], "compte_id": b["compte_id"],
                    "fournisseur": recu.fournisseur, "envoye_le": recu.envoye_le},
                    evenement_id=f"m1-courriel-envoye-{b['brouillon_id']}-{b['empreinte'][:16]}")
        with stockage.transaction() as cnx:
            journal.journaliser(cnx, self.nom, "ressource", systeme.IDENTIFIANT, ressource=ressource, mode="actif",
                                statut="erreur" if code else "ok", code=code,
                                details={"envoyes": envoyes, "refuses": refuses, "erreurs": incertains})
        return {"envoyes": envoyes, "refuses": refuses, "erreurs": incertains, "code": code}
