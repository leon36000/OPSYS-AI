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

Un exécuteur dont l'effet est IRRÉVERSIBLE (purge de rétention, Loi 25) ne passe en `actif` qu'APRÈS l'ombre, avec
l'empreinte de l'aperçu à blanc que l'admin a vu et une confirmation expresse : c'est la validation humaine N3 de la
première activation. Elle est consignée (`planificateur_approbations`, append-only), liée à la révision de l'exécuteur
et
expire avec lui ; sans elle l'exécuteur n'exécute rien (le contrôle est refait à chaque tour). Ensuite il purge
automatiquement selon la politique approuvée, jusqu'à l'expiration (renouvellement = nouvel aperçu, nouvelle décision).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import os
import time
from typing import Any

from sqlalchemy import func, insert, select, update

from .. import contexte, identite, stockage
from ..stockage.schema import PLANIFICATEUR_APPROBATIONS as APPROBATIONS_T
from ..stockage.schema import PLANIFICATEUR_EXECUTEURS as EXECUTEURS_T
from ..stockage.schema import PLANIFICATEUR_JOURNAL as JOURNAL_T
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
    famille: str = "connecteurs"
    # Nom d'un transport (clé de `TRANSPORTS`) sans lequel l'exécuteur ne peut RIEN faire : absent, le tour le dit
    # « en attente de transport » (jamais un échec silencieux, jamais un succès simulé).
    transport: str | None = None
    # L'effet est irréversible (purge) : première activation = validation humaine sur aperçu à blanc.
    irreversible: bool = False
    # Plafond d'appels (chez un fournisseur, un modèle, un moteur) par 24 h glissantes ; `None` = aucun appel externe.
    plafond_appels_jour: int | None = None


# Nom de transport -> attribut de `planificateur.Ports` qui doit être renseigné. Une valeur `None` = non raccordé.
# `embeddings` est particulier : l'attribut est un prédicat (`Ports.embeddings_raccordes()`).
TRANSPORTS: dict[str, str] = {
    "courriel": "service_courriel", "wordpress": "client_wordpress", "social": "adaptateurs_sociaux",
    "signaux": "fabrique_signaux", "veille": "fabrique_veille", "studio": "fabrique_studio",
    "embeddings": "embeddings_raccordes", "sauvegarde": "verifier_sauvegarde",
}
_LIBELLE_TRANSPORT = {
    "courriel": "service courriel (Gmail, Graph, IMAP)", "wordpress": "client WordPress", "social": "réseaux sociaux",
    "signaux": "connecteurs de signaux (Search Console, publicité…)", "veille": "transport de veille publique",
    "studio": "générateurs d'image du studio", "embeddings": "adaptateur d'embeddings",
    "sauvegarde": "dossier et clé de sauvegarde",
}


def transport_branche(ports: Any, nom: str | None) -> bool | None:
    """`None` si l'exécuteur n'exige aucun transport ; sinon vrai si le port correspondant est renseigné."""
    if nom is None:
        return None
    valeur = getattr(ports, TRANSPORTS[nom], None)
    if nom == "embeddings":
        return bool(valeur is not None and valeur())
    return valeur is not None


DEFINITIONS: tuple[Definition, ...] = (
    Definition("courriel.synchro", "Synchronisation courriel", 300, "N2",
               "Lit les nouveaux messages des comptes connectés (reprise sur curseur, quota, idempotence), les "
               "transmet à la file d'onboarding et, si le compte l'a demandé, à la réception de M1.",
               transport="courriel"),
    Definition("courriel.envoi", "Envoi des courriels approuvés", 60, "N3 : approbation consommée",
               "Envoie UNE fois chaque brouillon que la direction a approuvé (jeton lié à l'empreinte, approbation non "
               "expirée) ; rien d'autre ne part.", transport="courriel"),
    Definition("m7.wordpress.brouillons", "WordPress : brouillons", 120, "N2",
               "Transmet au site WordPress les brouillons d'article (statut brouillon ou en attente seulement).",
               transport="wordpress"),
    Definition("m7.wordpress.publication", "WordPress : publication approuvée", 60, "N3 : approbation consommée",
               "Publie les articles que la direction a approuvés, tant que l'approbation n'a pas expiré ; relit le "
               "site après une réponse perdue.", transport="wordpress"),
    Definition("m7.social.publication", "Réseaux sociaux : publication approuvée", 60, "N3/N4 : approbation consommée",
               "Publie à l'heure approuvée les publications planifiées, dans la fenêtre et le quota ; retrouve une "
               "publication d'issue incertaine avant tout nouvel envoi.", transport="social"),
    # -- planification autonome : ce qui était livré mais jamais déclenché (docs/architecture/PLANIFICATION.md) ------
    Definition("m8.entrepot", "M8 : entrepôt analytique", 3600, "N2",
               "Reconstruit l'entrepôt dérivé (inchangé si les registres n'ont pas bougé), publie les faits consolidés "
               "pour M10 et enregistre la santé de l'entreprise. Calcul et écriture dérivée, réversibles.",
               famille="departements"),
    Definition("m5.cycle", "M5 : cycle d'opérations comptables", 3600, "N2",
               "Brouillons d'écriture, relances de créances PRÉPARÉES, flux fournisseurs, préclôture du mois écoulé et "
               "mesures pour M8. Aucun paiement, aucun envoi, aucune clôture : ces gestes restent à la direction.",
               famille="departements"),
    Definition("m10.mnemo", "M10 : Mnémo (soi, graphe, leçons)", 21600, "N2",
               "Propose le modèle de soi, rattrape le graphe d'entités depuis les événements, extrait des leçons "
               "candidates et surveille les leçons promues. Rien n'est confirmé : c'est une décision humaine.",
               famille="departements"),
    Definition("m10.connaissances.reindexation", "M10 : réindexation des connaissances", 21600, "N2",
               "Recalcule les vecteurs d'une base dont le fournisseur d'embeddings a changé (bascule atomique de "
               "l'espace actif). Sans adaptateur d'embeddings raccordé : en attente de transport.",
               famille="departements", transport="embeddings", plafond_appels_jour=50000),
    Definition("m7.signaux", "M7 : signaux marketing (lecture)", 86400, "N2",
               "Lit chez les sources déclarées (Search Console, analytique, publicité) les chiffres du jour : reprise "
               "sur curseur, quota par source, événements sans valeur. Lecture seule chez le tiers.",
               famille="departements", transport="signaux", plafond_appels_jour=2000),
    Definition("m7.veille", "M7 : veille concurrentielle (lecture)", 86400, "N2",
               "Relit les pages publiques déclarées des concurrents (robots.txt, délai par hôte, pages bornées) et "
               "inscrit les observations. Contenu tiers traité comme donnée non fiable.",
               famille="departements", transport="veille", plafond_appels_jour=500),
    Definition("m7.studio.fonds", "M7 : génération de fonds du studio (modèles locaux)", 300,
               "N2 (local) ; payant = jamais",
               "Exécute les demandes de fond en attente dont le modèle sélectionné est LOCAL (sans coût). Une demande "
               "dont le modèle est payant n'est jamais exécutée ici : elle exige une approbation de dépense.",
               famille="departements", transport="studio", plafond_appels_jour=200),
    Definition("sauvegarde.verification", "Vérification périodique des sauvegardes", 86400, "N0",
               "Authentifie en entier la plus récente archive chiffrée (intégrité et bonne clé), sans rien écrire, et "
               "dit son âge. Ne crée, ne déplace ni ne supprime aucune sauvegarde.",
               famille="verification", transport="sauvegarde"),
    Definition("peremptions.balayage", "Revérification des péremptions", 86400, "N0",
               "Constate les sources de connaissances périmées ou à réviser (dont les sources fiscales) et les "
               "échéances de rétention en retard ; publie un constat, ne corrige rien.",
               famille="verification"),
    Definition("retention.courriel", "Rétention Loi 25 : courriel", 21600, "N3 humain à la 1re activation",
               "À l'échéance du compte, rend illisibles les contenus scellés de l'ingestion et des brouillons "
               "sortants, retire les archives en clair et ne garde que les empreintes qui évitent la réingestion.",
               famille="retention", irreversible=True),
    Definition("retention.cles", "Rétention Loi 25 : clés détruites à échéance", 21600, "N3 humain à la 1re activation",
               "Détruit à l'échéance la clé de chiffrement des enregistrements vocaux et des adresses de courriel "
               "reçues par M1 : les chaînes d'audit restent valides, le contenu devient illisible.",
               famille="retention", irreversible=True),
    Definition("retention.traces", "Rétention : traces d'observabilité", 86400, "N3 humain à la 1re activation",
               "Retire les segments de traces plus vieux que la rétention déclarée (ou au-delà de la taille permise), "
               "jamais le segment du jour, en consignant la purge.",
               famille="retention", irreversible=True),
    Definition("retention.effacements", "Reprise des effacements de clés autorisés", 3600, "N2",
               "Termine le nettoyage des fichiers de la base pour les effacements DÉJÀ autorisés (jamais un nouvel "
               "effacement). Reprise, pas décision.", famille="retention"),
)
NOMS = tuple(d.nom for d in DEFINITIONS)
_PAR_NOM = {d.nom: d for d in DEFINITIONS}


def definitions() -> tuple[Definition, ...]:
    """Tous les exécuteurs connus : ceux du socle (`DEFINITIONS`), les CONSTATS PLANIFIÉS que les manifestes des
    départements déclarent (`constats.py` ; cadence par défaut dérivée du catalogue de M8, aucun horaire dans le socle)
    puis leurs ROUTINES PLANIFIÉES (`routines.py` ; cadence déclarée ou suivie d'une planification)."""
    from . import constats, routines

    return DEFINITIONS + constats.definitions_declarees() + routines.definitions_declarees()


def noms() -> tuple[str, ...]:
    return tuple(d.nom for d in definitions())


def definition(nom: str) -> Definition | None:
    connue = _PAR_NOM.get(nom)
    if connue is not None or not isinstance(nom, str):
        return connue
    return next((d for d in definitions() if d.nom == nom), None)


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
              intervalle_s: Any = None, maintenant: float | None = None, apercu_empreinte: Any = None,
              apercu_courant: Any = None, confirme_irreversible: Any = False) -> dict[str, Any]:
    """Fixe le mode d'un exécuteur (inactif, ombre, actif) : octroi ou renouvellement pour 90 jours, ou désactivation
    immédiate. Champs fermés, motif obligatoire, journal append-only.

    Exécuteur IRRÉVERSIBLE (purge) en mode `actif` : l'ombre a dû précéder (mode effectif `ombre` ou `actif`),
    `apercu_empreinte` doit être celle de l'aperçu à blanc COURANT (`apercu_courant()` rend `(empreinte, nombre)` ; un
    aperçu qui a changé depuis que l'admin l'a lu est refusé : on n'approuve que ce qu'on a vu) et la confirmation
    expresse est requise. La décision est consignée, liée à la révision créée ici."""
    _exiger_contexte(cnx, session)
    trouvee = definition(executeur) if type(executeur) is str else None
    if trouvee is None:
        raise RefusOperateur("EXECUTEUR_INCONNU", "exécuteur hors de la liste fermée")
    if type(mode) is not str or mode not in MODES:
        raise RefusOperateur("MODE_INCONNU", "mode : inactif, ombre ou actif")
    motif = _motif(motif)
    actuelle = ligne(cnx, executeur)
    if intervalle_s is None:
        intervalle_s = actuelle["intervalle_s"] if actuelle is not None else trouvee.intervalle_defaut_s
    if type(intervalle_s) is not int or not 15 <= intervalle_s <= 86400:
        raise RefusOperateur("INTERVALLE_INVALIDE", "intervalle de 15 à 86400 secondes")
    maintenant = int(time.time() if maintenant is None else maintenant)  # injectable : tests, jamais la console
    ancien = "inactif" if actuelle is None else mode_effectif(actuelle, maintenant)
    if actuelle is not None and actuelle["mode"] == mode and mode == "inactif":
        raise RefusOperateur("DEJA_INACTIF", "exécuteur déjà inactif")
    nb_elements = 0
    if trouvee.irreversible and mode == "actif":
        if ancien not in ("ombre", "actif"):
            raise RefusOperateur("OMBRE_REQUISE", "un exécuteur irréversible passe d'abord par l'ombre")
        if confirme_irreversible is not True:
            raise RefusOperateur("CONFIRMATION_IRREVERSIBLE_REQUISE", "confirmation expresse requise")
        if type(apercu_empreinte) is not str or not callable(apercu_courant):
            raise RefusOperateur("APERCU_REQUIS", "l'aperçu à blanc doit avoir été consulté")
        empreinte_courante, nb_elements = apercu_courant()
        if apercu_empreinte != empreinte_courante:
            raise RefusOperateur("APERCU_CHANGE", "l'aperçu a changé depuis sa consultation : relire puis confirmer")
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
    if trouvee.irreversible and mode == "actif":
        cnx.execute(insert(APPROBATIONS_T).values(
            executeur=executeur, revision=revision, apercu_empreinte=apercu_empreinte, nb_elements=nb_elements,
            approuve_par=session.utilisateur, approuve_le=journal.instant(), expire_le=expire))
        journal.journaliser(cnx, executeur, "approbation_irreversible", session.utilisateur, mode=mode, details={
            "revision": revision, "elements": nb_elements, "empreinte": apercu_empreinte[:16]})
    return {"executeur": executeur, "mode": mode, "revision": revision, "expire_le": valeurs["expire_le"]}


def approbation_valide(cnx: Any, executeur: str, maintenant: float | None = None) -> dict[str, Any] | None:
    """La décision humaine qui autorise l'exécuteur irréversible dans son état ACTUEL (même révision, non expirée), ou
    `None`. Relue à chaque tour : sans elle, aucun effacement, quel que soit le mode inscrit."""
    maintenant = time.time() if maintenant is None else maintenant
    l_ = ligne(cnx, executeur)
    if l_ is None or mode_effectif(l_, maintenant) != "actif":
        return None
    ap = cnx.execute(select(APPROBATIONS_T).where(
        APPROBATIONS_T.c.executeur == executeur, APPROBATIONS_T.c.revision == l_["revision"],
        APPROBATIONS_T.c.expire_le > maintenant).order_by(APPROBATIONS_T.c.id.desc()).limit(1)).mappings().first()
    return None if ap is None else dict(ap)


def echecs_recents(cnx: Any, executeur: str, depuis_iso: str) -> int:
    """Passages en erreur ou refus depuis `depuis_iso` (instant ISO UTC) : lecture du journal append-only."""
    return int(cnx.execute(select(func.count()).select_from(JOURNAL_T).where(
        JOURNAL_T.c.executeur == executeur, JOURNAL_T.c.evenement == "passage",
        JOURNAL_T.c.statut.in_(("erreur", "refus")), JOURNAL_T.c.quand >= depuis_iso)).scalar_one())


def vue(cnx: Any, maintenant: float | None = None, ports: Any = None) -> list[dict[str, Any]]:
    """Tous les exécuteurs (même ceux qui n'ont jamais été activés), leur mode EFFECTIF, leur dernier et prochain
    passage, leurs échecs récents et l'état de leur transport (`ports` : ceux de l'hôte, pour dire « en attente de
    transport » même quand l'exécuteur est inactif)."""
    maintenant = time.time() if maintenant is None else maintenant
    depuis = dt.datetime.fromtimestamp(maintenant - 86400, dt.UTC).isoformat(timespec="seconds")
    sortie = []
    for definition in definitions():
        l_ = ligne(cnx, definition.nom)
        mode = mode_effectif(l_, maintenant)
        branche = None if ports is None else transport_branche(ports, definition.transport)
        approbation = approbation_valide(cnx, definition.nom, maintenant) if definition.irreversible else None
        sortie.append({
            "executeur": definition.nom, "libelle": definition.libelle, "niveau": definition.niveau,
            "description": definition.description, "famille": definition.famille,
            "mode": mode,
            "mode_demande": "inactif" if l_ is None else l_["mode"],
            "expire_le": None if l_ is None else l_["expire_le"],
            "expire": bool(l_ is not None and l_["mode"] != "inactif" and mode == "inactif"
                           and planificateur_autorise()),
            "intervalle_s": definition.intervalle_defaut_s if l_ is None else l_["intervalle_s"],
            "prochain_passage": None if l_ is None or mode == "inactif" else l_["prochain_passage"],
            "dernier_passage": None if l_ is None else l_["dernier_passage"],
            "dernier_statut": None if l_ is None else l_["dernier_statut"],
            "dernier_code": None if l_ is None else l_["dernier_code"],
            "echecs_24h": echecs_recents(cnx, definition.nom, depuis),
            "transport": definition.transport,
            "transport_libelle": None if definition.transport is None else _LIBELLE_TRANSPORT[definition.transport],
            "transport_branche": branche,
            "en_attente_transport": bool(branche is False or (l_ is not None and l_["dernier_statut"]
                                                               == "attente_transport")),
            "irreversible": definition.irreversible,
            "approbation": None if approbation is None else {k: approbation[k] for k in (
                "approuve_par", "approuve_le", "nb_elements", "expire_le")},
            "revision": 0 if l_ is None else l_["revision"],
            "modifie_par": None if l_ is None else l_["modifie_par"],
        })
    return sortie
