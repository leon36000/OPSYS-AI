"""Portée interne d'une livraison ; aucun droit de service n'est activé.

Ce module prépare seulement la liaison au répartiteur. La présence d'une portée
n'atteste ni l'état du WCT, ni une politique ou un droit d'accès à M4.
"""

from __future__ import annotations

import copy
import json
import os
import stat
import threading
from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic, time

from sqlalchemy import event, insert, select

from .stockage import connexion_courante, moteur
from .stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS, OPSYS_INSTANCE, SERVICE_AUDIT, SERVICE_POLITIQUES


class RefusAutorite(PermissionError):
    """Absence ou perte de preuve ; ne contient pas les données métier."""


_COURANTE = ContextVar("opsys_service_livraison", default=None)
_DELAI_MAX = 30.0
_OPERATION = "m4.verifier_v3"
_CONSOMMATEUR = "m05-financecore"


class _Portee:
    __slots__ = (
        "cnx",
        "racine",
        "sauvegarde",
        "thread",
        "date_limite",
        "evenement",
        "consommateur",
        "tentatives",
        "fermee",
        "garde_rollback",
    )

    def __init__(self, cnx, evenement, consommateur, tentatives):
        self.cnx = cnx
        self.racine = cnx.get_transaction()
        self.sauvegarde = cnx.get_nested_transaction()
        self.thread = threading.get_ident()
        self.date_limite = monotonic() + _DELAI_MAX
        self.evenement = dict(evenement)
        self.consommateur = consommateur
        self.tentatives = tentatives
        self.fermee = False
        self.garde_rollback = None

    def __copy__(self):
        raise RefusAutorite("copie interdite")

    def __deepcopy__(self, memo):
        raise RefusAutorite("copie interdite")

    def __reduce__(self):
        raise RefusAutorite("sérialisation interdite")

    def _verifier(self):
        cnx = self.cnx
        if (
            self.fermee
            or _COURANTE.get() is not self
            or threading.get_ident() != self.thread
            or monotonic() >= self.date_limite
            or connexion_courante() is not cnx
            or cnx.closed
            or cnx.engine.dialect.name != "sqlite"
            or self.racine is None
            or not self.racine.is_active
            or cnx.get_transaction() is not self.racine
            or self.sauvegarde is None
            or not self.sauvegarde.is_active
            or cnx.get_nested_transaction() is not self.sauvegarde
        ):
            raise RefusAutorite("portée transactionnelle non vérifiable")
        # Relecture dans la connexion réclamée, jamais la copie passée au consommateur.
        ident = self.evenement["evenement_id"]
        from .evenements.repartiteur import _CLE_PAIRES_EN_VOL

        garde = cnx.info.get(_CLE_PAIRES_EN_VOL, {}).get(cnx, set())
        if (ident, self.consommateur) not in garde:
            raise RefusAutorite("réclamation de livraison absente")
        event = (
            cnx.execute(select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.evenement_id == ident))
            .mappings()
            .one_or_none()
        )
        recu = (
            cnx.execute(
                select(EVENEMENTS_RECUS).where(
                    (EVENEMENTS_RECUS.c.evenement_id == ident) & (EVENEMENTS_RECUS.c.consommateur == self.consommateur)
                )
            )
            .mappings()
            .one_or_none()
        )
        if (
            event is None
            or dict(event) != self.evenement
            or recu is None
            or recu["statut"] != "echec"
            or recu["tentatives"] != self.tentatives
        ):
            raise RefusAutorite("livraison non vérifiable")


@contextmanager
def _livraison(cnx, evenement, consommateur, tentatives):
    """Interne au répartiteur, sans création d'autorité ou de politique."""
    portee = _Portee(cnx, evenement, consommateur, tentatives)
    jeton = _COURANTE.set(portee)
    try:
        yield
    finally:
        portee.fermee = True
        if portee.garde_rollback is not None:
            event.remove(cnx, "rollback_savepoint", portee.garde_rollback)
        _COURANTE.reset(jeton)


def courante():
    """Émet une autorité seulement pour une livraison SQLite qualifiée et une politique active."""
    portee = _COURANTE.get()
    if portee is None:
        raise RefusAutorite("aucune livraison")
    if portee.cnx.engine.dialect.name != "sqlite":
        raise RefusAutorite("backend non qualifié")
    portee._verifier()
    if portee.consommateur != _CONSOMMATEUR:
        raise RefusAutorite("consommateur hors périmètre")
    cnx = portee.cnx
    identite_base = _base(cnx)
    instance = cnx.execute(select(OPSYS_INSTANCE.c.instance_id).where(OPSYS_INSTANCE.c.id == 1)).scalar_one_or_none()
    if not instance:
        raise RefusAutorite("instance absente")
    politique = _politique(cnx, instance, portee.consommateur)
    if politique is None or not politique.active or politique.expire_le <= time():
        raise RefusAutorite("politique inactive ou expirée")
    if portee.evenement["type_evenement"] != "m4.travaux_termines" or portee.evenement["producteur"] != "m04-field-ops":
        raise RefusAutorite("événement hors périmètre")
    if portee.garde_rollback is None:

        def annuler_sur_rollback(cnx, nom, contexte):
            portee.fermee = True

        event.listen(cnx, "rollback_savepoint", annuler_sur_rollback)
        portee.garde_rollback = annuler_sur_rollback
    faits = _figer_faits(_faits_m4_verifies(portee))
    portee._verifier()
    if (
        _base(cnx) != identite_base
        or time() >= politique.expire_le
        or cnx.execute(select(OPSYS_INSTANCE.c.instance_id).where(OPSYS_INSTANCE.c.id == 1)).scalar_one_or_none()
        != instance
        or _politique(cnx, instance, portee.consommateur) != politique
    ):
        raise RefusAutorite("liaison modifiée pendant la vérification")
    return _Capacite(portee, identite_base, instance, politique.revision, politique.expire_le, faits)


def _base(cnx):
    if (
        cnx.engine.dialect.name != "sqlite"
        or cnx.engine is not moteur()
        or not cnx.connection.driver_connection.in_transaction
    ):
        raise RefusAutorite("garde SQLite indisponible")
    lignes = cnx.exec_driver_sql("PRAGMA database_list").all()
    chemins = [ligne[2] for ligne in lignes if ligne[1] == "main"]
    if len(chemins) != 1 or not chemins[0]:
        raise RefusAutorite("base SQLite non durable")
    chemin = os.path.realpath(chemins[0])
    try:
        info = os.stat(chemin, follow_symlinks=False)
    except OSError as exc:
        raise RefusAutorite("identité de base indisponible") from exc
    if not stat.S_ISREG(info.st_mode):
        raise RefusAutorite("base SQLite non régulière")
    return chemin, info.st_dev, info.st_ino


def _politique(cnx, instance, consommateur):
    return cnx.execute(
        select(SERVICE_POLITIQUES)
        .where(
            (SERVICE_POLITIQUES.c.instance_id == instance)
            & (SERVICE_POLITIQUES.c.consommateur == consommateur)
            & (SERVICE_POLITIQUES.c.operation == _OPERATION)
        )
        .order_by(SERVICE_POLITIQUES.c.revision.desc())
        .limit(1)
    ).first()


def _faits_m4_verifies(portee):
    # Essai privé : non activé dans Source.
    from m4_field_ops.service_faits_m4 import lire

    from .service_source_m4 import _requete_pour_portee

    return lire(_requete_pour_portee(portee))


def _figer_faits(faits):
    if (
        type(faits) is not tuple
        or not 1 <= len(faits) <= 8
        or any(type(v) not in (str, int) or (type(v) is str and len(v) > 256) for v in faits)
    ):
        raise RefusAutorite("faits non qualifiés")
    return faits


class _Capacite:
    __slots__ = (
        "portee",
        "base",
        "instance",
        "revision",
        "expire_le",
        "date_limite",
        "faits",
        "en_cours",
        "projection_en_cours",
        "_liaison_projection",
    )

    def __init__(self, portee, base, instance, revision, expire_le, faits):
        self.portee, self.base, self.instance = portee, base, instance
        self.revision, self.expire_le, self.faits = revision, expire_le, faits
        self.date_limite = min(portee.date_limite, monotonic() + max(0.0, expire_le - time()))
        self.en_cours = False
        self.projection_en_cours = False
        self._liaison_projection = object()

    def __copy__(self):
        raise RefusAutorite("copie interdite")

    def __deepcopy__(self, memo):
        raise RefusAutorite("copie interdite")

    def __reduce__(self):
        raise RefusAutorite("sérialisation interdite")

    def projection_m4(self):
        """Copie de données liée à la livraison ; revalidation requise avant usage."""
        if self.projection_en_cours:
            raise RefusAutorite("réentrée projection interdite")
        self.projection_en_cours = True
        try:
            return self._projection_m4()
        finally:
            self.projection_en_cours = False

    def _projection_m4(self):
        self.verifier()
        if self.portee.cnx.engine.dialect.name != "sqlite":
            raise RefusAutorite("projection non qualifiée sur ce backend")
        from m4_field_ops.service_faits_m4 import projeter

        from .service_source_m4 import _requete_pour_portee
        from .stockage import codec

        faits, vue = projeter(_requete_pour_portee(self.portee))
        if _figer_faits(faits) != self.faits or type(vue) is not dict or set(vue) != {"source", "projection"}:
            raise RefusAutorite("projection ou faits divergents")
        p = vue["projection"]
        if (
            type(p) is not dict
            or type(p.get("wct")) is not dict
            or p.get("instance_id") != faits[1]
            or p.get("intervention_id") != faits[2]
            or p["wct"].get("wct_id") != faits[3]
            or p["wct"].get("hash_maillon") != faits[4]
            or vue.get("source") != faits[5]
            or p.get("version") != faits[6]
            or p.get("empreinte") != faits[7]
        ):
            raise RefusAutorite("liaison projection divergente")
        charge = codec.decoder(self.portee.evenement["charge"])
        if type(charge) is not dict or charge.get("wct_id") != faits[3]:
            raise RefusAutorite("charge WCT invalide")
        enveloppe = {"schema": "opsys.core.m4.projection.v1", "faits": list(faits), "vue": vue, "charge": charge}
        try:
            brut = json.dumps(
                enveloppe, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
        except (TypeError, ValueError, RecursionError) as exc:
            raise RefusAutorite("projection non encodable") from exc
        if len(brut) > 262144:
            raise RefusAutorite("projection hors limite")
        self.verifier()
        copie = copy.deepcopy(enveloppe)
        # Une copie ou désérialisation ne conserve pas cette identité de capacité.
        copie["liaison"] = self._liaison_projection
        return copie

    def verifier_projection(self, enveloppe):
        """Refuse une projection modifiée ou périmée, en portée active."""
        if type(enveloppe) is not dict or enveloppe.get("liaison") is not self._liaison_projection:
            raise RefusAutorite("projection invalide")
        actuelle = self.projection_m4()
        try:
            def encoder(v):
                return json.dumps(
                    v, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
                ).encode("utf-8")
            comparaison = encoder({k: v for k, v in enveloppe.items() if k != "liaison"})
            attendu = encoder({k: v for k, v in actuelle.items() if k != "liaison"})
            if len(comparaison) > 262144 or comparaison != attendu:
                raise RefusAutorite("projection modifiée ou périmée")
        except (TypeError, ValueError, RecursionError) as exc:
            raise RefusAutorite("projection non encodable") from exc
        self.verifier()
        p = self.portee
        audit = (
            p.cnx.execute(
                select(SERVICE_AUDIT)
                .where(
                    (SERVICE_AUDIT.c.instance_id == self.instance)
                    & (SERVICE_AUDIT.c.consommateur == p.consommateur)
                    & (SERVICE_AUDIT.c.operation == _OPERATION)
                    & (SERVICE_AUDIT.c.revision == self.revision)
                    & (SERVICE_AUDIT.c.evenement_id == p.evenement["evenement_id"])
                    & (SERVICE_AUDIT.c.action == "usage")
                )
                .order_by(SERVICE_AUDIT.c.id.desc())
                .limit(1)
            )
            .mappings()
            .one_or_none()
        )
        p._verifier()
        if (
            audit is None
            or type(audit["id"]) is not int
            or audit["id"] <= 0
            or time() >= self.expire_le
            or monotonic() >= self.date_limite
            or _base(p.cnx) != self.base
            or p.cnx.execute(select(OPSYS_INSTANCE.c.instance_id).where(OPSYS_INSTANCE.c.id == 1)).scalar_one_or_none()
            != self.instance
        ):
            raise RefusAutorite("audit ou liaison invalide")
        politique = _politique(p.cnx, self.instance, p.consommateur)
        if (
            politique is None
            or not politique.active
            or politique.revision != self.revision
            or politique.expire_le != self.expire_le
        ):
            raise RefusAutorite("politique révoquée ou remplacée")
        return {
            "schema": "opsys.core.m4.audit-usage.v1",
            "id": audit["id"],
            "instance_id": self.instance,
            "evenement_id": p.evenement["evenement_id"],
            "operation": _OPERATION,
            "revision": self.revision,
        }

    def attester_trace_m4(self, enveloppe, trace_rang):
        """Lier une trace M5 à des faits M4 pendant la livraison SQLite."""
        from .service_history_m4 import attester

        return attester(self, enveloppe, trace_rang)

    def verifier(self):
        if self.en_cours:
            raise RefusAutorite("réentrée interdite")
        self.en_cours = True
        try:
            p = self.portee
            p._verifier()
            cnx = p.cnx
            instance = cnx.execute(
                select(OPSYS_INSTANCE.c.instance_id).where(OPSYS_INSTANCE.c.id == 1)
            ).scalar_one_or_none()
            if (
                instance != self.instance
                or _base(cnx) != self.base
                or time() >= self.expire_le
                or monotonic() >= self.date_limite
            ):
                raise RefusAutorite("instance ou durée invalide")
            politique = _politique(cnx, instance, p.consommateur)
            if (
                politique is None
                or not politique.active
                or politique.revision != self.revision
                or politique.expire_le != self.expire_le
            ):
                raise RefusAutorite("politique révoquée ou remplacée")
            if _figer_faits(_faits_m4_verifies(p)) != self.faits:
                raise RefusAutorite("source modifiée ou incertaine")
            p._verifier()
            if (
                monotonic() >= self.date_limite
                or time() >= self.expire_le
                or _base(cnx) != self.base
                or cnx.execute(
                    select(OPSYS_INSTANCE.c.instance_id).where(OPSYS_INSTANCE.c.id == 1)
                ).scalar_one_or_none()
                != self.instance
                or _politique(cnx, self.instance, p.consommateur) != politique
            ):
                raise RefusAutorite("liaison modifiée pendant la vérification")
            cnx.execute(
                insert(SERVICE_AUDIT).values(
                    instance_id=instance,
                    consommateur=p.consommateur,
                    operation=_OPERATION,
                    revision=self.revision,
                    evenement_id=p.evenement["evenement_id"],
                    action="usage",
                )
            )
            # Ne jamais renvoyer une preuve de fraîcheur réutilisable hors du contexte.
            return None
        finally:
            self.en_cours = False


def _revoquer(cnx, instance, consommateur):
    """Primitive interne uniquement : aucune authentification administrative n'est fournie ici."""
    if connexion_courante() is not cnx or cnx.get_transaction() is None:
        raise RefusAutorite("transaction requise")
    if cnx.engine.dialect.name != "sqlite":
        raise RefusAutorite("backend non qualifié")
    _base(cnx)
    p = _politique(cnx, instance, consommateur)
    if p is None or not p.active:
        raise RefusAutorite("politique absente ou déjà inactive")
    cnx.execute(
        insert(SERVICE_POLITIQUES).values(
            instance_id=instance,
            consommateur=consommateur,
            operation=_OPERATION,
            revision=p.revision + 1,
            active=False,
            expire_le=p.expire_le,
        )
    )
    cnx.execute(
        insert(SERVICE_AUDIT).values(
            instance_id=instance,
            consommateur=consommateur,
            operation=_OPERATION,
            revision=p.revision + 1,
            evenement_id=None,
            action="revocation",
        )
    )
