"""Opérateur Core des politiques de service M4 → M5 (D1, étape E4 de CONCEPTION-ROUTAGE-COUT-CERTIFIE).

Trois opérations, un seul consommateur (`m05-financecore`) :

- `m4.verifier_v3` : relire les faits M4 pour M5 (exigée par le recalcul) ;
- `m4.recalculer_v3` : rejouer la publication certifiée après coup (moteur, réconciliateur) ;
- `m4.relire_faits_pour_m5_v1` : revalider à la lecture, sans écriture.

Règles (DECISIONS-ARCHITECTE-r1 §2, D1) :

- octroi, renouvellement et révocation sont faits par une personne `admin` ACTIVE relue en base, depuis la console
  (session serveur, jeton CSRF vérifié par la route) ; JAMAIS par un agent : un appel depuis le transport MCP, sous
  l'identité d'un département ou d'un appareil est refusé avant tout accès ;
- chaque octroi ou renouvellement expire 90 jours plus tard (`DUREE_S`) ; on renouvelle explicitement ;
- la révocation est immédiate : elle ajoute une révision inactive, et chaque garde (`service_capability`,
  moteur de recalcul, `service_lecture_m4`) relit la DERNIÈRE révision à chaque vérification ;
- chaque geste écrit une ligne du journal append-only `service_politiques_journal` (acteur, motif, instant,
  révision, expiration), liée par clé étrangère à la révision qu'il a créée ; la révocation écrit aussi l'audit
  `revocation` historique de `service_audit` ;
- SQLite et PostgreSQL (verrou d'instance de la famille sous PostgreSQL) ; tout autre moteur est refusé.

Ce module est une convention entre composants de confiance, pas une frontière contre du Python arbitraire.
"""

from __future__ import annotations

from time import time

from sqlalchemy import insert, select

from . import contexte, stockage
from . import service_capability as sc
from .stockage.exclusion import engager
from .stockage.portabilite import DIALECTES_QUALIFIES
from .stockage.schema import OPSYS_INSTANCE, SERVICE_AUDIT, SERVICE_POLITIQUES
from .stockage.schema import SERVICE_POLITIQUES_JOURNAL as JOURNAL

CONSOMMATEUR = sc._CONSOMMATEUR
OPERATIONS = ("m4.verifier_v3", "m4.recalculer_v3", "m4.relire_faits_pour_m5_v1")
DUREE_S = 90 * 86400
MOTIF_MAX = 500
ACTIONS = ("octroyer", "renouveler", "revoquer")


class RefusOperateur(sc.RefusAutorite):
    """Refus typé de l'opérateur ; `code` est stable, aucun contenu métier."""

    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code, self.detail = code, detail


def _exiger_contexte(cnx, session):
    # Jamais un agent : ni transport MCP, ni département appelant, ni identité d'appareil ou de cron.
    if (
        contexte.appel_provient_du_mcp()
        or contexte.DEPARTEMENT_APPELANT.get() is not None
        or contexte.identite_appelante() is not None
    ):
        raise RefusOperateur("APPEL_AGENT_INTERDIT", "geste réservé à un admin de la console")
    if cnx.engine.dialect.name not in DIALECTES_QUALIFIES:
        raise RefusOperateur("BACKEND_NON_QUALIFIE", "opérateur qualifié pour SQLite et PostgreSQL seulement")
    if cnx is not stockage.connexion_courante() or cnx.get_transaction() is None:
        raise RefusOperateur("CONTEXTE_INVALIDE", "transaction de la connexion courante requise")
    # PostgreSQL : octroyer / renouveler / révoquer lisent la dernière révision puis écrivent la suivante (clé
    # (instance, opération, révision)) ; le verrou d'instance de la famille les sérialise avec les portées de service.
    engager(cnx)
    from .console.securite import Session

    if type(session) is not Session:
        raise RefusOperateur("SESSION_INVALIDE", "session console serveur requise")
    from .console.memoire_chantier import _admin

    try:
        _admin(cnx, session)  # personne active, rôle admin relu en base, session non expirée
    except PermissionError as exc:
        raise RefusOperateur("ADMIN_REQUIS", "admin actif requis") from exc
    instance = cnx.execute(select(OPSYS_INSTANCE.c.instance_id).where(OPSYS_INSTANCE.c.id == 1)).scalar_one_or_none()
    if type(instance) is not str or not instance:
        raise RefusOperateur("CONTEXTE_INVALIDE", "instance absente")
    return instance


def _operation(operation):
    if type(operation) is not str or operation not in OPERATIONS:
        raise RefusOperateur("OPERATION_INCONNUE", "opération hors des trois politiques de service")
    return operation


def _motif(motif):
    if type(motif) is not str:
        raise RefusOperateur("MOTIF_INVALIDE", "motif texte requis")
    propre = " ".join(motif.split())
    if not 3 <= len(propre) <= MOTIF_MAX or not propre.isprintable():
        raise RefusOperateur("MOTIF_INVALIDE", f"motif de 3 à {MOTIF_MAX} caractères imprimables")
    return propre


def derniere(cnx, instance, operation):
    """Dernière révision de la politique (ou `None`) : la seule qui fait foi."""
    return cnx.execute(
        select(SERVICE_POLITIQUES)
        .where(
            SERVICE_POLITIQUES.c.instance_id == instance,
            SERVICE_POLITIQUES.c.consommateur == CONSOMMATEUR,
            SERVICE_POLITIQUES.c.operation == operation,
        )
        .order_by(SERVICE_POLITIQUES.c.revision.desc())
        .limit(1)
    ).first()


def statut(ligne, maintenant=None):
    """`absente`, `revoquee`, `expiree` ou `active` pour une révision (relue, jamais mise en cache)."""
    maintenant = time() if maintenant is None else maintenant
    if ligne is None:
        return "absente"
    if not ligne.active:
        return "revoquee"
    if maintenant >= ligne.expire_le:
        return "expiree"
    return "active"


def _ecrire(cnx, instance, operation, *, revision, active, expire_le, action, acteur, motif, maintenant):
    cnx.execute(
        insert(SERVICE_POLITIQUES).values(
            instance_id=instance, consommateur=CONSOMMATEUR, operation=operation,
            revision=revision, active=active, expire_le=expire_le,
        )
    )
    cnx.execute(
        insert(JOURNAL).values(
            instance_id=instance, consommateur=CONSOMMATEUR, operation=operation, revision=revision,
            action=action, acteur=acteur, motif=motif, epoch=maintenant, expire_le=expire_le,
        )
    )
    if action == "revocation":
        cnx.execute(
            insert(SERVICE_AUDIT).values(
                instance_id=instance, consommateur=CONSOMMATEUR, operation=operation,
                revision=revision, evenement_id=None, action="revocation",
            )
        )
    return {"operation": operation, "revision": revision, "statut": "active" if active else "revoquee",
            "expire_le": expire_le, "action": action}


def octroyer(cnx, session, operation, *, motif):
    """Octroi : nouvelle révision active pour 90 jours. Refusé si une révision active non expirée existe déjà
    (renouveler explicitement : un octroi ne prolonge jamais en silence)."""
    instance = _exiger_contexte(cnx, session)
    operation, motif = _operation(operation), _motif(motif)
    maintenant = int(time())
    ligne = derniere(cnx, instance, operation)
    if statut(ligne, maintenant) == "active":
        raise RefusOperateur("DEJA_ACTIVE", "politique déjà active : la renouveler")
    return _ecrire(cnx, instance, operation, revision=(ligne.revision if ligne is not None else 0) + 1,
                   active=True, expire_le=maintenant + DUREE_S, action="octroi",
                   acteur=session.utilisateur, motif=motif, maintenant=maintenant)


def renouveler(cnx, session, operation, *, motif):
    """Renouvellement : la dernière révision doit être active (expirée ou non, jamais révoquée) ; la nouvelle
    révision expire 90 jours après MAINTENANT (pas après l'ancienne échéance : aucun cumul)."""
    instance = _exiger_contexte(cnx, session)
    operation, motif = _operation(operation), _motif(motif)
    maintenant = int(time())
    ligne = derniere(cnx, instance, operation)
    if statut(ligne, maintenant) in ("absente", "revoquee"):
        raise RefusOperateur("NON_RENOUVELABLE", "politique absente ou révoquée : l'octroyer")
    return _ecrire(cnx, instance, operation, revision=ligne.revision + 1, active=True,
                   expire_le=maintenant + DUREE_S, action="renouvellement",
                   acteur=session.utilisateur, motif=motif, maintenant=maintenant)


def revoquer(cnx, session, operation, *, motif):
    """Révocation immédiate : révision inactive (même échéance), audit `revocation` et journal."""
    instance = _exiger_contexte(cnx, session)
    operation, motif = _operation(operation), _motif(motif)
    maintenant = int(time())
    ligne = derniere(cnx, instance, operation)
    if ligne is None or not ligne.active:
        raise RefusOperateur("DEJA_INACTIVE", "politique absente ou déjà révoquée")
    return _ecrire(cnx, instance, operation, revision=ligne.revision + 1, active=False,
                   expire_le=ligne.expire_le, action="revocation",
                   acteur=session.utilisateur, motif=motif, maintenant=maintenant)


def appliquer(cnx, session, action, operation, *, motif):
    """Point d'entrée unique de la console (champs fermés)."""
    if type(action) is not str or action not in ACTIONS:
        raise RefusOperateur("ACTION_INCONNUE", "action : octroyer, renouveler ou revoquer")
    return {"octroyer": octroyer, "renouveler": renouveler, "revoquer": revoquer}[action](
        cnx, session, operation, motif=motif)


def etat(cnx, session, *, journal_max=20):
    """Vue admin : statut de chaque politique et dernières entrées du journal. N'écrit rien."""
    instance = _exiger_contexte(cnx, session)
    maintenant = int(time())
    politiques = []
    for operation in OPERATIONS:
        ligne = derniere(cnx, instance, operation)
        politiques.append({
            "operation": operation,
            "statut": statut(ligne, maintenant),
            "revision": None if ligne is None else ligne.revision,
            "expire_le": None if ligne is None else ligne.expire_le,
            "jours_restants": (None if ligne is None or statut(ligne, maintenant) != "active"
                               else (ligne.expire_le - maintenant) // 86400),
        })
    journal = [
        dict(r)
        for r in cnx.execute(
            select(JOURNAL.c.operation, JOURNAL.c.revision, JOURNAL.c.action, JOURNAL.c.acteur,
                   JOURNAL.c.motif, JOURNAL.c.epoch, JOURNAL.c.expire_le)
            .where(JOURNAL.c.instance_id == instance)
            .order_by(JOURNAL.c.id.desc())
            .limit(journal_max)
        ).mappings()
    ]
    return {"consommateur": CONSOMMATEUR, "duree_jours": DUREE_S // 86400, "politiques": politiques,
            "journal": journal}
