"""Candidat privé, non routé : portée de recalcul SQLite sous double politique.

La session vient exclusivement du serveur. Ce module est une convention entre
composants de confiance, pas une frontière contre du Python arbitraire.
Les intentions et attestations sont conservées par Core ; le port M5 vérifie
ses registres et sa trace. Ne pas router sans décision et qualification.
"""

import json
import re
import threading
from time import monotonic, time

from sqlalchemy import LargeBinary, cast, func, insert, select
from sqlalchemy.exc import IntegrityError

from . import service_capability as sc
from . import stockage
from .stockage import codec
from .stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS, OPSYS_INSTANCE, SERVICE_AUDIT, SERVICE_POLITIQUES
from .stockage.schema import SERVICE_RECALCUL_ATTESTATIONS as ATTESTATIONS
from .stockage.schema import SERVICE_RECALCUL_INTENTIONS as INTENTIONS
from .stockage.schema import SERVICE_RECALCUL_RESULTATS as RESULTATS

_OPERATION = "m4.recalculer_v3"
_HEX = re.compile(r"[0-9a-f]{64}\Z")


def _politique(cnx, instance):
    return cnx.execute(
        select(SERVICE_POLITIQUES)
        .where(
            SERVICE_POLITIQUES.c.instance_id == instance,
            SERVICE_POLITIQUES.c.consommateur == sc._CONSOMMATEUR,
            SERVICE_POLITIQUES.c.operation == _OPERATION,
        )
        .order_by(SERVICE_POLITIQUES.c.revision.desc())
        .limit(1)
    ).first()


def _admin(cnx, session):
    from .console.memoire_chantier import _admin as verifier

    verifier(cnx, session)


class _PorteeRecalcul:
    def __init__(self, cnx, session, evenement, recu, instance, policy):
        self.cnx, self.session, self.evenement, self.recu = cnx, session, dict(evenement), dict(recu)
        self.instance, self.policy = instance, policy
        self.acteur = session.utilisateur
        self.racine, self.sauvegarde = cnx.get_transaction(), cnx.get_nested_transaction()
        self.thread, self.date_limite = threading.get_ident(), monotonic() + sc._DELAI_MAX
        self.consommateur, self.fermee = sc._CONSOMMATEUR, False

    def _verifier(self):
        c = self.cnx
        if (
            self.fermee
            or sc._COURANTE.get() is not self
            or threading.get_ident() != self.thread
            or monotonic() >= self.date_limite
            or stockage.connexion_courante() is not c
            or c.closed
            or c.engine.dialect.name != "sqlite"
            or self.racine is None
            or not self.racine.is_active
            or c.get_transaction() is not self.racine
            or self.sauvegarde is None
            or not self.sauvegarde.is_active
            or c.get_nested_transaction() is not self.sauvegarde
        ):
            raise sc.RefusAutorite("portée recalcul non vérifiable")
        _admin(c, self.session)
        if self.session.utilisateur != self.acteur:
            raise sc.RefusAutorite("acteur modifié")
        if (
            time() >= self.policy.expire_le
            or _politique(c, self.instance) != self.policy
            or c.execute(select(OPSYS_INSTANCE.c.instance_id).where(OPSYS_INSTANCE.c.id == 1)).scalar_one_or_none()
            != self.instance
        ):
            raise sc.RefusAutorite("politique recalcul révoquée ou instance modifiée")
        event = (
            c.execute(
                select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.evenement_id == self.evenement["evenement_id"])
            )
            .mappings()
            .one_or_none()
        )
        recu = (
            c.execute(
                select(EVENEMENTS_RECUS).where(
                    EVENEMENTS_RECUS.c.evenement_id == self.evenement["evenement_id"],
                    EVENEMENTS_RECUS.c.consommateur == self.consommateur,
                )
            )
            .mappings()
            .one_or_none()
        )
        if event is None or dict(event) != self.evenement or recu is None or dict(recu) != self.recu:
            raise sc.RefusAutorite("publication ou réception modifiée")

    def __copy__(self):
        raise sc.RefusAutorite("copie interdite")

    def __deepcopy__(self, memo):
        raise sc.RefusAutorite("copie interdite")

    def __reduce__(self):
        raise sc.RefusAutorite("sérialisation interdite")


class _CapaciteRecalcul(sc._Capacite):
    __slots__ = ("intention", "audit_recalcul")

    def __init__(self, *args, intention, audit_recalcul):
        super().__init__(*args)
        self.intention, self.audit_recalcul = intention, audit_recalcul

    def attester_trace_m4(self, enveloppe, trace_rang):
        raise sc.RefusAutorite("attestation historique incompatible avec recalcul")

    def attester_recalcul_m4(self, enveloppe, trace_rang, trace_empreinte):
        """Liaison M4 fraîche ; l'empreinte de trace est une déclaration M5."""
        if (
            type(trace_rang) is not int
            or not 0 <= trace_rang < 1000
            or type(trace_empreinte) is not str
            or not _HEX.fullmatch(trace_empreinte)
        ):
            raise sc.RefusAutorite("déclaration M5 invalide")
        audit_service = self.verifier_projection(enveloppe)
        faits = enveloppe["faits"]
        if (
            type(faits) is not list
            or len(faits) != 8
            or faits[3] != self.intention["wct_id"]
            or any(type(faits[i]) is not str or not _HEX.fullmatch(faits[i]) for i in (3, 4, 5, 7))
            or type(faits[6]) is not str
            or not 1 <= len(faits[6]) <= 64
        ):
            raise sc.RefusAutorite("faits M4 invalides")
        p = self.portee
        ligne = dict(
            intention_id=self.intention["intention_id"],
            audit_recalcul_id=self.audit_recalcul,
            audit_service_id=audit_service["id"],
            revision_recalcul=p.policy.revision,
            revision_service=self.revision,
            trace_rang=trace_rang,
            trace_empreinte=trace_empreinte,
            source_m4=faits[5],
            projection_m4=faits[7],
            wct_hash=faits[4],
            version_m4=faits[6],
        )
        try:
            p.cnx.execute(insert(ATTESTATIONS).values(**ligne))
        except IntegrityError as exc:
            raise sc.RefusAutorite("attestation déjà créée ou invalide") from exc
        self.verifier_projection(enveloppe)
        return _reference(self.intention, ligne)


_REFERENCE_CHAMPS = frozenset(
    {
        "schema",
        "operation",
        "intention_id",
        "instance_id",
        "acteur",
        "wct_id",
        "devis_id",
        "audit_recalcul_id",
        "audit_service_id",
        "revision_recalcul",
        "revision_service",
        "trace_rang",
        "trace_empreinte",
        "source_m4",
        "projection_m4",
        "wct_hash",
        "version_m4",
        "trace_statut",
    }
)


def valider_reference_v2(reference):
    """Valide chaque champ et type exact ; ne confère aucune autorité."""
    if type(reference) is not dict or set(reference) != _REFERENCE_CHAMPS:
        raise sc.RefusAutorite("référence recalcul invalide")
    if (
        type(reference["schema"]) is not str
        or reference["schema"] != "opsys.core.m4.recalcul-attestation.v2"
        or type(reference["operation"]) is not str
        or reference["operation"] != _OPERATION
        or type(reference["trace_statut"]) is not str
        or reference["trace_statut"] != "declaration_m5_non_verifiee_par_core"
    ):
        raise sc.RefusAutorite("référence recalcul invalide")
    for nom in ("intention_id", "wct_id", "trace_empreinte", "source_m4", "projection_m4", "wct_hash"):
        if type(reference[nom]) is not str or not _HEX.fullmatch(reference[nom]):
            raise sc.RefusAutorite("référence recalcul invalide")
    for nom, borne in (("instance_id", 36), ("acteur", 256), ("devis_id", 256), ("version_m4", 64)):
        if type(reference[nom]) is not str or not 1 <= len(reference[nom]) <= borne:
            raise sc.RefusAutorite("référence recalcul invalide")
    for nom in ("audit_recalcul_id", "audit_service_id", "revision_recalcul", "revision_service"):
        if type(reference[nom]) is not int or not 0 < reference[nom] <= 2**63 - 1:
            raise sc.RefusAutorite("référence recalcul invalide")
    if (
        reference["audit_recalcul_id"] == reference["audit_service_id"]
        or type(reference["trace_rang"]) is not int
        or not 0 <= reference["trace_rang"] < 1000
    ):
        raise sc.RefusAutorite("référence recalcul invalide")
    try:
        json.dumps(reference, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
            "utf-8"
        )
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise sc.RefusAutorite("référence recalcul invalide") from exc
    return None


def _reference_canonique(reference):
    valider_reference_v2(reference)
    try:
        return json.dumps(reference, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
            "utf-8"
        )
    except (TypeError, ValueError, UnicodeError, RecursionError) as exc:
        raise sc.RefusAutorite("référence recalcul invalide") from exc


def _reference(intention, attestation):
    return {
        "schema": "opsys.core.m4.recalcul-attestation.v2",
        "operation": _OPERATION,
        **intention,
        **{k: v for k, v in attestation.items() if k != "intention_id"},
        "trace_statut": "declaration_m5_non_verifiee_par_core",
    }


def _valider_source(cnx, wct_id, devis_id):
    taille_event = cnx.execute(
        select(func.length(cast(EVENEMENTS_SORTANTS.c.charge, LargeBinary))).where(
            EVENEMENTS_SORTANTS.c.evenement_id == wct_id
        )
    ).scalar_one_or_none()
    taille_recu = cnx.execute(
        select(func.length(cast(EVENEMENTS_RECUS.c.resultat, LargeBinary))).where(
            EVENEMENTS_RECUS.c.evenement_id == wct_id, EVENEMENTS_RECUS.c.consommateur == sc._CONSOMMATEUR
        )
    ).scalar_one_or_none()
    if (
        type(taille_event) is not int
        or not 0 <= taille_event <= 262144
        or type(taille_recu) is not int
        or not 0 <= taille_recu <= 262144
    ):
        raise sc.RefusAutorite("publication ou réception hors limite")
    evt = (
        cnx.execute(select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.evenement_id == wct_id))
        .mappings()
        .one_or_none()
    )
    recu = (
        cnx.execute(
            select(EVENEMENTS_RECUS).where(
                EVENEMENTS_RECUS.c.evenement_id == wct_id, EVENEMENTS_RECUS.c.consommateur == sc._CONSOMMATEUR
            )
        )
        .mappings()
        .one_or_none()
    )
    if (
        evt is None
        or evt["type_evenement"] != "m4.travaux_termines"
        or evt["producteur"] != "m04-field-ops"
        or recu is None
        or recu["statut"] != "traite"
    ):
        raise sc.RefusAutorite("publication ou réception absente")
    try:
        charge, resultat = codec.decoder_strict(evt["charge"]), codec.decoder_strict(recu["resultat"])
    except (TypeError, ValueError):
        raise sc.RefusAutorite("publication ou réception invalide") from None
    if (
        type(charge) is not dict
        or charge.get("wct_id") != wct_id
        or charge.get("devis_id") != devis_id
        or type(resultat) is not dict
        or resultat.get("traite") is not True
        or resultat.get("devis_id") != devis_id
    ):
        raise sc.RefusAutorite("liaison WCT devis réception invalide")
    return evt, recu


def _politiques(cnx, instance):
    p, service = _politique(cnx, instance), sc._politique(cnx, instance, sc._CONSOMMATEUR)
    if (
        p is None
        or not p.active
        or time() >= p.expire_le
        or service is None
        or not service.active
        or time() >= service.expire_le
    ):
        raise sc.RefusAutorite("politique recalcul ou service inactive")
    return p, service


def lire_historique_v2(cnx, session, intention_id):
    """Lien historique, sans validation actuelle de M4 ni de la trace M5."""
    _admin(cnx, session)
    if (
        cnx is not stockage.connexion_courante()
        or cnx.get_transaction() is None
        or cnx.dialect.name != "sqlite"
        or type(intention_id) is not str
        or not _HEX.fullmatch(intention_id)
    ):
        raise sc.RefusAutorite("lecture non qualifiée")
    i = cnx.execute(select(INTENTIONS).where(INTENTIONS.c.intention_id == intention_id)).mappings().one_or_none()
    a = cnx.execute(select(ATTESTATIONS).where(ATTESTATIONS.c.intention_id == intention_id)).mappings().one_or_none()
    r = cnx.execute(select(RESULTATS).where(RESULTATS.c.intention_id == intention_id)).mappings().one_or_none()
    if i is None or a is None or r is None:
        raise sc.RefusAutorite("preuve historique absente")
    if (
        any(type(i[k]) is not str or not i[k] for k in ("instance_id", "acteur", "wct_id", "devis_id"))
        or type(i["intention_id"]) is not str
        or not _HEX.fullmatch(i["intention_id"])
        or not _HEX.fullmatch(i["wct_id"])
        or len(i["acteur"]) > 256
        or len(i["devis_id"]) > 256
        or any(
            type(a[k]) is not int or a[k] <= 0
            for k in ("audit_recalcul_id", "audit_service_id", "revision_recalcul", "revision_service")
        )
        or type(a["trace_rang"]) is not int
        or not 0 <= a["trace_rang"] < 1000
        or any(
            type(a[k]) is not str or not _HEX.fullmatch(a[k])
            for k in ("trace_empreinte", "source_m4", "projection_m4", "wct_hash")
        )
        or type(a["version_m4"]) is not str
        or not 1 <= len(a["version_m4"]) <= 64
        or r["statut"] != "publiee"
        or type(r["version"]) is not str
        or len(r["version"]) > 256
    ):
        raise sc.RefusAutorite("preuve historique invalide")
    instance = cnx.execute(select(OPSYS_INSTANCE.c.instance_id).where(OPSYS_INSTANCE.c.id == 1)).scalar_one_or_none()
    if i["instance_id"] != instance:
        raise sc.RefusAutorite("instance différente")
    for ident, operation, revision in (
        (a["audit_recalcul_id"], _OPERATION, a["revision_recalcul"]),
        (a["audit_service_id"], sc._OPERATION, a["revision_service"]),
    ):
        row = cnx.execute(select(SERVICE_AUDIT).where(SERVICE_AUDIT.c.id == ident)).mappings().one_or_none()
        if (
            row is None
            or type(ident) is not int
            or type(revision) is not int
            or row["instance_id"] != instance
            or row["consommateur"] != sc._CONSOMMATEUR
            or row["evenement_id"] != i["wct_id"]
            or row["operation"] != operation
            or row["revision"] != revision
            or row["action"] != "usage"
        ):
            raise sc.RefusAutorite("audit historique invalide")
    _admin(cnx, session)
    reference = _reference(dict(i), dict(a))
    valider_reference_v2(reference)
    return {"statut": "historique_non_revalidee", "attestation": reference, "resultat": dict(r)}


def ouvrir(cnx, session, *, wct_id, devis_id, intention_id):
    """Porte publique fermée : la décision de droit et la route manquent."""
    raise sc.RefusAutorite("RECALCUL_M4_NON_QUALIFIE")


def _executer_qa(cnx, session, *, wct_id, devis_id, intention_id):
    """Mécanique privée ; ne pas router ni activer sans décision et revue."""
    if (
        type(wct_id) is not str
        or not _HEX.fullmatch(wct_id)
        or type(devis_id) is not str
        or not 1 <= len(devis_id) <= 256
        or type(intention_id) is not str
        or not _HEX.fullmatch(intention_id)
    ):
        raise sc.RefusAutorite("identifiant invalide")
    if (
        cnx is not stockage.connexion_courante()
        or cnx.engine.dialect.name != "sqlite"
        or cnx.get_transaction() is None
        or not cnx.connection.dbapi_connection.in_transaction
        or sc._COURANTE.get() is not None
    ):
        raise sc.RefusAutorite("transaction ou contexte invalide")
    _admin(cnx, session)
    instance = cnx.execute(select(OPSYS_INSTANCE.c.instance_id).where(OPSYS_INSTANCE.c.id == 1)).scalar_one_or_none()
    if (
        type(instance) is not str
        or not instance
        or type(session.utilisateur) is not str
        or not 1 <= len(session.utilisateur) <= 256
    ):
        raise sc.RefusAutorite("instance ou acteur invalide")
    politique, service = _politiques(cnx, instance)
    intention = dict(
        intention_id=intention_id, instance_id=instance, acteur=session.utilisateur, wct_id=wct_id, devis_id=devis_id
    )
    ancienne = cnx.execute(select(INTENTIONS).where(INTENTIONS.c.intention_id == intention_id)).mappings().one_or_none()
    if ancienne is not None:
        if dict(ancienne) != intention:
            raise sc.RefusAutorite("intention en conflit")
        historique = lire_historique_v2(cnx, session, intention_id)
        if _politiques(cnx, instance) != (politique, service):
            raise sc.RefusAutorite("politique modifiée")
        return {"statut": "deja_executee", "historique": historique}
    try:
        with cnx.begin_nested():
            cnx.execute(insert(INTENTIONS).values(**intention))
            evt, recu = _valider_source(cnx, wct_id, devis_id)
            p = _PorteeRecalcul(cnx, session, evt, recu, instance, politique)
            token = sc._COURANTE.set(p)
            try:
                p._verifier()
                base = sc._base(cnx)
                faits = sc._figer_faits(sc._faits_m4_verifies(p))
                p._verifier()
                audit = cnx.execute(
                    insert(SERVICE_AUDIT).values(
                        instance_id=instance,
                        consommateur=sc._CONSOMMATEUR,
                        operation=_OPERATION,
                        revision=politique.revision,
                        evenement_id=wct_id,
                        action="usage",
                    )
                ).inserted_primary_key[0]
                cap = _CapaciteRecalcul(
                    p,
                    base,
                    instance,
                    service.revision,
                    service.expire_le,
                    faits,
                    intention=intention,
                    audit_recalcul=audit,
                )
                from m5_financecore.port_service_m4 import publier

                result = publier(devis_id, cap=cap)
                if (
                    type(result) is not dict
                    or result.get("statut") != "publiee"
                    or type(result.get("_controle_final")) is not type(lambda: None)
                    or type(result.get("attestation")) is not dict
                ):
                    raise sc.RefusAutorite("publication v2 incomplète")
                version = result.get("version")
                if type(version) is not str or len(version) > 256:
                    raise sc.RefusAutorite("version invalide")
                cnx.execute(insert(RESULTATS).values(intention_id=intention_id, statut="publiee", version=version))
                # Après toutes les écritures propres, y compris audit/intention/résultat,
                # M5 revalide projection et ses registres avant fermeture du savepoint.
                result["_controle_final"]()
                p._verifier()
                if _politiques(cnx, instance) != (politique, service):
                    raise sc.RefusAutorite("politique modifiée")
                histoire = lire_historique_v2(cnx, session, intention_id)
                if _reference_canonique(histoire["attestation"]) != _reference_canonique(result["attestation"]):
                    raise sc.RefusAutorite("attestation divergente")
                p._verifier()
                return {"statut": "publiee", "version": version, "attestation": histoire["attestation"]}
            finally:
                p.fermee = True
                sc._COURANTE.reset(token)
    except IntegrityError as exc:
        raise sc.RefusAutorite("intention concurrente ou incohérente") from exc
