"""Candidate SQLite-only historical linkage; not a current service authority."""

import hashlib
import json
import re

from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError

from . import stockage
from .service_capability import RefusAutorite
from .stockage import codec
from .stockage.schema import OPSYS_INSTANCE, REGISTRES, SERVICE_ATTESTATIONS_M4, SERVICE_AUDIT

_HEX = re.compile("[0-9a-f]{64}\\Z")
_OP = "m4.verifier_v3"


def _canon(trace):
    try:
        raw = json.dumps(
            json.loads(codec.encoder(trace)), sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    except (ValueError, TypeError, RecursionError) as exc:
        raise RefusAutorite("trace non encodable") from exc
    if len(raw) > 262144:
        raise RefusAutorite("trace hors limite")
    return raw


def _hash_trace(trace):
    return hashlib.sha256(_canon(trace)).hexdigest()


def _decode_strict(raw):
    if type(raw) is not str or len(raw.encode("utf-8")) > 262144:
        raise RefusAutorite("JSON hors limite")

    def unique(pairs):
        out = {}
        for k, v in pairs:
            if k in out:
                raise ValueError("clé dupliquée")
            out[k] = v
        return out

    try:
        json.loads(
            raw, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nombre invalide"))
        )
        return codec.decoder(raw)
    except (ValueError, TypeError, RecursionError, KeyError) as exc:
        raise RefusAutorite("JSON invalide") from exc


def _lignes(cnx, registre):
    rows = cnx.execute(
        select(REGISTRES.c.maillon)
        .where((REGISTRES.c.departement == "m05-financecore") & (REGISTRES.c.registre == registre))
        .order_by(REGISTRES.c.rang)
        .limit(1001)
    ).all()
    if len(rows) > 1000:
        raise RefusAutorite("registre hors limite")
    return [_decode_strict(row[0]) for row in rows]


def _trace(rang):
    if type(rang) is not int or not 0 <= rang < 1000:
        raise RefusAutorite("rang invalide")
    cnx = stockage.connexion_courante()
    if cnx is None:
        raise RefusAutorite("transaction absente")
    registre = stockage.maillons("m05-financecore", "rentabilite")
    if len(registre) > 1000:
        raise RefusAutorite("registre hors limite")
    raw = cnx.execute(
        select(REGISTRES.c.maillon).where(
            (REGISTRES.c.departement == "m05-financecore")
            & (REGISTRES.c.registre == "rentabilite")
            & (REGISTRES.c.rang == rang)
        )
    ).scalar_one_or_none()
    if raw is None:
        raise RefusAutorite("trace absente")
    trace = _decode_strict(raw)
    if type(trace) is not dict:
        raise RefusAutorite("trace invalide")
    return trace


def attester(cap, enveloppe, rang):
    """Candidate called only by already-authorized delivery; same DB transaction."""
    cap.verifier_projection(enveloppe)
    trace = _trace(rang)
    v = trace.get("provenance_service_v1")
    faits = enveloppe.get("faits") if type(enveloppe) is dict else None
    if (
        type(faits) is not list
        or len(faits) != 8
        or type(v) is not dict
        or trace.get("wct_id") != faits[3]
        or any(
            v.get(k) != x
            for k, x in (
                ("instance_id", faits[1]),
                ("wct_id", faits[3]),
                ("source_m4", faits[5]),
                ("version", faits[6]),
                ("empreinte_projection", faits[7]),
            )
        )
    ):
        raise RefusAutorite("trace ou provenance incohérente")
    if (
        any(type(faits[i]) is not str or not _HEX.fullmatch(faits[i]) for i in (3, 5, 7))
        or type(faits[6]) is not str
        or len(faits[6]) > 64
    ):
        raise RefusAutorite("faits invalides")
    digest = _hash_trace(trace)
    ref = cap.verifier_projection(enveloppe)
    if _hash_trace(_trace(rang)) != digest:
        raise RefusAutorite("trace modifiée")
    cnx = stockage.connexion_courante()
    if cnx is None or cnx.engine.dialect.name != "sqlite":
        raise RefusAutorite("backend non qualifié")
    try:
        cnx.execute(
            insert(SERVICE_ATTESTATIONS_M4).values(
                audit_id=ref["id"],
                instance_id=faits[1],
                evenement_id=faits[3],
                revision=ref["revision"],
                trace_rang=rang,
                trace_sha256=digest,
                source_m4=faits[5],
                projection_sha256=faits[7],
                version_m4=faits[6],
            )
        )
    except IntegrityError as exc:
        raise RefusAutorite("attestation déjà présente ou invalide") from exc
    return ref


def lire_historique(cnx, session, recu):
    """Console admin admission; checks historic linkage, never current freshness."""
    from m5_financecore.encodage import empreinte

    from .console.memoire_chantier import _admin

    _admin(cnx, session)
    if cnx is not stockage.connexion_courante() or cnx.get_transaction() is None or cnx.engine.dialect.name != "sqlite":
        raise RefusAutorite("transaction non qualifiée")
    if (
        type(recu) is not dict
        or set(recu)
        != {"type", "instance_id", "wct_id", "reference_core", "trace_rang", "trace_empreinte", "empreinte"}
        or recu.get("type") != "publication_service_v1"
    ):
        raise RefusAutorite("reçu invalide")
    ref = recu["reference_core"]
    rang = recu["trace_rang"]
    if (
        type(ref) is not dict
        or set(ref) != {"schema", "id", "instance_id", "evenement_id", "operation", "revision"}
        or ref.get("schema") != "opsys.core.m4.audit-usage.v1"
        or type(ref.get("id")) is not int
        or ref["id"] <= 0
        or type(ref.get("revision")) is not int
        or ref["revision"] <= 0
        or ref.get("operation") != _OP
        or type(rang) is not int
        or not 0 <= rang < 1000
    ):
        raise RefusAutorite("référence invalide")
    instance = cnx.execute(select(OPSYS_INSTANCE.c.instance_id).where(OPSYS_INSTANCE.c.id == 1)).scalar_one_or_none()
    if (
        not instance
        or recu["instance_id"] != instance
        or ref["instance_id"] != instance
        or recu["wct_id"] != ref["evenement_id"]
    ):
        raise RefusAutorite("instance ou événement incompatible")
    trace = _trace(rang)
    if recu["trace_empreinte"] != empreinte(trace) or recu["empreinte"] != empreinte(
        "m5.publication_service.v1", {k: v for k, v in recu.items() if k != "empreinte"}
    ):
        raise RefusAutorite("empreinte incohérente")
    registres = _lignes(cnx, "rentabilite_service_v1")
    if any(
        type(item) is not dict or type(item.get("trace_rang")) is not int or item["trace_rang"] < 0
        for item in registres
    ):
        raise RefusAutorite("rang de reçu invalide")
    candidats = [item for item in registres if item["trace_rang"] == rang]
    if len(candidats) != 1:
        raise RefusAutorite("reçu absent ou rejoué")
    stocke = candidats[0]
    sr = stocke.get("reference_core")
    if (
        set(stocke) != {"type", "instance_id", "wct_id", "reference_core", "trace_rang", "trace_empreinte", "empreinte"}
        or stocke.get("type") != "publication_service_v1"
        or type(sr) is not dict
        or set(sr) != {"schema", "id", "instance_id", "evenement_id", "operation", "revision"}
        or sr.get("schema") != "opsys.core.m4.audit-usage.v1"
        or type(sr.get("id")) is not int
        or sr["id"] <= 0
        or type(sr.get("revision")) is not int
        or sr["revision"] <= 0
        or sr.get("operation") != _OP
        or type(stocke.get("trace_rang")) is not int
        or stocke.get("trace_empreinte") != empreinte(trace)
        or stocke.get("empreinte")
        != empreinte("m5.publication_service.v1", {k: v for k, v in stocke.items() if k != "empreinte"})
        or _canon(stocke) != _canon(recu)
    ):
        raise RefusAutorite("reçu stocké invalide ou divergent")
    audit = cnx.execute(select(SERVICE_AUDIT).where(SERVICE_AUDIT.c.id == ref["id"])).mappings().one_or_none()
    if audit is None or any(
        audit[k] != v
        for k, v in (
            ("instance_id", instance),
            ("consommateur", "m05-financecore"),
            ("operation", _OP),
            ("revision", ref["revision"]),
            ("evenement_id", ref["evenement_id"]),
            ("action", "usage"),
        )
    ):
        raise RefusAutorite("audit incohérent")
    att = (
        cnx.execute(select(SERVICE_ATTESTATIONS_M4).where(SERVICE_ATTESTATIONS_M4.c.audit_id == ref["id"]))
        .mappings()
        .one_or_none()
    )
    if att is None:
        _admin(cnx, session)
        return {"preuve_core": "historique_non_verifiable", "fraicheur": "historique_non_revalidee"}
    prov = trace.get("provenance_service_v1")
    if (
        type(prov) is not dict
        or any(
            att[k] != v
            for k, v in (
                ("instance_id", instance),
                ("evenement_id", ref["evenement_id"]),
                ("revision", ref["revision"]),
                ("trace_rang", rang),
                ("trace_sha256", _hash_trace(trace)),
                ("source_m4", prov.get("source_m4")),
                ("projection_sha256", prov.get("empreinte_projection")),
                ("version_m4", prov.get("version")),
            )
        )
        or prov.get("instance_id") != instance
        or prov.get("wct_id") != ref["evenement_id"]
        or trace.get("wct_id") != ref["evenement_id"]
    ):
        raise RefusAutorite("attestation incohérente")
    _admin(cnx, session)
    return {
        "preuve_core": "liaison_historique_verifiee",
        "fraicheur": "historique_non_revalidee",
        "tarifs": "declaration_m5_non_verifiee_par_core",
    }
