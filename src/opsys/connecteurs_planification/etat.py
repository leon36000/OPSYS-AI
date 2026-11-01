"""Les exécuteurs connus, leur mode et l'opérateur qui les active (console admin seulement).

Modèle (le même que le réconciliateur du coût certifié, E5/E8) :

- `inactif` (défaut, et valeur de toute ligne absente, expirée ou inconnue : fail-closed) : rien ne tourne ;
- `ombre` : le tour CONSTATE ce qu'il ferait (lecture de la base d'OPSYS seulement) et le journalise ; aucun appel à un
  fournisseur, aucun écrit métier ;
- `actif` : le tour exécute.

Activer, renouveler ou désactiver est un geste d'ADMIN depuis la console (session serveur, jeton CSRF vérifié par la
route, rôle relu en base), avec un motif obligatoire, une expiration à 90 jours (renouvellement explicite) et une ligne
du journal append-only. Un appel depuis le transport MCP, sous l'identité d'un département ou d'un appareil, est refusé
avant tout accès : aucun agent n'active un exécuteur.
"""

from __future__ import annotations

import dataclasses
import os
import time
from typing import Any

from sqlalchemy import insert, select, update

from .. import contexte, identite, stockage
from ..stockage.schema import PLANIFICATEUR_EXECUTEURS as EXECUTEURS_T
from . import journal

MODES = ("inactif", "ombre", "actif")
DUREE_S = 90 * 86400
MOTIF_MAX = 500
ENV_PLANIFICATEUR = "OPSYS_PLANIFICATEUR_CONNECTEURS"
_DESACTIVE = frozenset({"0", "non", "off", "false", "faux"})


@dataclasses.dataclass(frozen=True)
class Definition:
    nom: str
    libelle: str
    intervalle_defaut_s: int
    niveau: str
    description: str


DEFINITIONS: tuple[Definition, ...] = (
    Definition("courriel.synchro", "Synchronisation courriel", 300, "N2",
               "Lit les nouveaux messages des comptes connectés (reprise sur curseur, quota, idempotence), les "
               "transmet à la file d'onboarding et, si le compte l'a demandé, à la réception de M1."),
    Definition("courriel.envoi", "Envoi des courriels approuvés", 60, "N3 : approbation consommée",
               "Envoie UNE fois chaque brouillon que la direction a approuvé (jeton lié à l'empreinte, approbation non "
               "expirée) ; rien d'autre ne part."),
    Definition("m7.wordpress.brouillons", "WordPress : brouillons", 120, "N2",
               "Transmet au site WordPress les brouillons d'article (statut brouillon ou en attente seulement)."),
    Definition("m7.wordpress.publication", "WordPress : publication approuvée", 60, "N3 : approbation consommée",
               "Publie les articles que la direction a approuvés, tant que l'approbation n'a pas expiré ; relit le "
               "site après une réponse perdue."),
    Definition("m7.social.publication", "Réseaux sociaux : publication approuvée", 60, "N3/N4 : approbation consommée",
               "Publie à l'heure approuvée les publications planifiées, dans la fenêtre et le quota ; retrouve une "
               "publication d'issue incertaine avant tout nouvel envoi."),
)
NOMS = tuple(d.nom for d in DEFINITIONS)
_PAR_NOM = {d.nom: d for d in DEFINITIONS}


class RefusOperateur(PermissionError):
    """Refus typé de l'opérateur ; `code` est stable, aucun contenu métier."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code, self.detail = code, detail


def planificateur_autorise() -> bool:
    return os.environ.get(ENV_PLANIFICATEUR, "1").strip().lower() not in _DESACTIVE


def ligne(cnx: Any, executeur: str) -> Any:
    return cnx.execute(select(EXECUTEURS_T).where(EXECUTEURS_T.c.executeur == executeur)).mappings().first()


def mode_effectif(ligne_executeur: Any, maintenant: float | None = None) -> str:
    """`inactif` si la ligne est absente, expirée ou de mode inconnu ; sinon son mode. Relu à chaque tour."""
    maintenant = time.time() if maintenant is None else maintenant
    if ligne_executeur is None or not planificateur_autorise():
        return "inactif"
    mode = ligne_executeur["mode"]
    if mode not in MODES or mode == "inactif":
        return "inactif"
    expire = ligne_executeur["expire_le"]
    return mode if expire is not None and maintenant < expire else "inactif"


def _exiger_contexte(cnx: Any, session: Any) -> None:
    if (contexte.appel_provient_du_mcp() or contexte.DEPARTEMENT_APPELANT.get() is not None
            or contexte.identite_appelante() is not None):
        raise RefusOperateur("APPEL_AGENT_INTERDIT", "geste réservé à un admin de la console")
    if cnx is not stockage.connexion_courante() or cnx.get_transaction() is None:
        raise RefusOperateur("CONTEXTE_INVALIDE", "transaction de la connexion courante requise")
    from ..console.securite import Session

    if type(session) is not Session or session.expire <= time.time():
        raise RefusOperateur("SESSION_INVALIDE", "session console serveur requise")
    personne = identite.personne_active(cnx, session.utilisateur)
    if personne is None or not personne.roles.intersection({"admin", "nathan_owner"}):
        raise RefusOperateur("ADMIN_REQUIS", "admin actif requis")


def _motif(motif: Any) -> str:
    if type(motif) is not str:
        raise RefusOperateur("MOTIF_INVALIDE", "motif texte requis")
    propre = " ".join(motif.split())
    if not 3 <= len(propre) <= MOTIF_MAX or not propre.isprintable():
        raise RefusOperateur("MOTIF_INVALIDE", f"motif de 3 à {MOTIF_MAX} caractères imprimables")
    return propre


def appliquer(cnx: Any, session: Any, executeur: Any, mode: Any, *, motif: Any,
              intervalle_s: Any = None, maintenant: float | None = None) -> dict[str, Any]:
    """Fixe le mode d'un exécuteur (inactif, ombre, actif) : octroi ou renouvellement pour 90 jours, ou désactivation
    immédiate. Champs fermés, motif obligatoire, journal append-only."""
    _exiger_contexte(cnx, session)
    if type(executeur) is not str or executeur not in _PAR_NOM:
        raise RefusOperateur("EXECUTEUR_INCONNU", "exécuteur hors de la liste fermée")
    if type(mode) is not str or mode not in MODES:
        raise RefusOperateur("MODE_INCONNU", "mode : inactif, ombre ou actif")
    motif = _motif(motif)
    definition = _PAR_NOM[executeur]
    actuelle = ligne(cnx, executeur)
    if intervalle_s is None:
        intervalle_s = actuelle["intervalle_s"] if actuelle is not None else definition.intervalle_defaut_s
    if type(intervalle_s) is not int or not 15 <= intervalle_s <= 86400:
        raise RefusOperateur("INTERVALLE_INVALIDE", "intervalle de 15 à 86400 secondes")
    maintenant = int(time.time() if maintenant is None else maintenant)  # injectable : tests, jamais la console
    ancien = "inactif" if actuelle is None else mode_effectif(actuelle, maintenant)
    if actuelle is not None and actuelle["mode"] == mode and mode == "inactif":
        raise RefusOperateur("DEJA_INACTIF", "exécuteur déjà inactif")
    expire = None if mode == "inactif" else maintenant + DUREE_S
    valeurs = {"mode": mode, "intervalle_s": intervalle_s, "expire_le": expire,
               "prochain_passage": maintenant, "modifie_par": session.utilisateur, "modifie_le": journal.instant(),
               "motif": motif}
    if actuelle is None:
        cnx.execute(insert(EXECUTEURS_T).values(executeur=executeur, revision=1, **valeurs))
        revision = 1
    else:
        revision = actuelle["revision"] + 1
        cnx.execute(update(EXECUTEURS_T).where(EXECUTEURS_T.c.executeur == executeur,
                                               EXECUTEURS_T.c.revision == actuelle["revision"]).values(
            revision=revision, **valeurs))
    journal.journaliser(cnx, executeur, "mode", session.utilisateur, mode=mode, details={
        "ancien_mode": ancien, "revision": revision, "intervalle_s": intervalle_s,
        "expire_le": valeurs["expire_le"], "motif": motif[:64]})
    return {"executeur": executeur, "mode": mode, "revision": revision, "expire_le": valeurs["expire_le"]}


def vue(cnx: Any, maintenant: float | None = None) -> list[dict[str, Any]]:
    """Tous les exécuteurs (même ceux qui n'ont jamais été activés), leur mode EFFECTIF et leur dernier passage."""
    maintenant = time.time() if maintenant is None else maintenant
    sortie = []
    for definition in DEFINITIONS:
        l_ = ligne(cnx, definition.nom)
        sortie.append({
            "executeur": definition.nom, "libelle": definition.libelle, "niveau": definition.niveau,
            "description": definition.description,
            "mode": mode_effectif(l_, maintenant),
            "mode_demande": "inactif" if l_ is None else l_["mode"],
            "expire_le": None if l_ is None else l_["expire_le"],
            "expire": bool(l_ is not None and l_["mode"] != "inactif" and mode_effectif(l_, maintenant) == "inactif"
                           and planificateur_autorise()),
            "intervalle_s": definition.intervalle_defaut_s if l_ is None else l_["intervalle_s"],
            "dernier_passage": None if l_ is None else l_["dernier_passage"],
            "dernier_statut": None if l_ is None else l_["dernier_statut"],
            "dernier_code": None if l_ is None else l_["dernier_code"],
            "revision": 0 if l_ is None else l_["revision"],
            "modifie_par": None if l_ is None else l_["modifie_par"],
        })
    return sortie
