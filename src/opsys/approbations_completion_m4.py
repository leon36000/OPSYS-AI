"""Provenance de la revue M4 DEVICE : lectures SQL, corrélation D, aucune autorité Meta.

Les arguments et le maillon métier sont vérifiés par M4. Ce module vérifie les
sources du socle : demande, journal de création, claims et signataire SQL.
"""
from __future__ import annotations

import contextlib
import contextvars
import datetime as dt
import json
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, select

from . import approbations, approbations_appareil, contexte, idempotence, stockage
from .stockage.schema import APPROBATIONS, JOURNAL

OUTIL = "m4_resoudre_revue_completion_sources"
DEPARTEMENT = "m04-field-ops"
DECIDER = "m9_decider_demande_approbation"


@dataclass(frozen=True)
class _Decision:
    meta: idempotence.Meta
    arguments: dict[str, Any]


_DECISION: contextvars.ContextVar[_Decision | None] = contextvars.ContextVar("decision_completion_m4", default=None)


def _texte(v, maximum=256):
    return type(v) is str and bool(v.strip()) and len(v) <= maximum


def _hora(v):
    if not _texte(v):
        return False
    try:
        date = dt.datetime.fromisoformat(v)
        return date.tzinfo is not None and date.utcoffset() is not None
    except (ValueError, TypeError):
        return False


def _refus(code="REJ-SOURCES-CHANGEES"):
    return {"code": code, "detail": "La signature SQL ou la provenance propre de cette intention n’est pas établie."}


def _copie(v):
    return json.loads(json.dumps(v, ensure_ascii=False, allow_nan=False))


@contextlib.contextmanager
def contexte_decision(meta: idempotence.Meta, arguments: dict[str, Any]):
    """Transport authentifié en amont ; le contexte ne vaut jamais une signature."""
    if not isinstance(meta, idempotence.Meta) or type(arguments) is not dict:
        raise ValueError("corrélation D invalide")
    copie = _copie(arguments)
    token = _DECISION.set(_Decision(meta, copie))
    try:
        yield
    finally:
        _DECISION.reset(token)


def _args_p(v):
    return (
        type(v) is dict and set(v) == {"intervention_id", "decision", "horodatage", "motif", "sources"}
        and _texte(v["intervention_id"]) and type(v["decision"]) is str and v["decision"] in {"verifiee", "correction"}
        and _hora(v["horodatage"]) and _texte(v["motif"], 500) and type(v["sources"]) is dict
    )


def _demande(cnx, ident):
    if cnx is None or not _texte(ident, 32):
        return None
    row = cnx.execute(select(APPROBATIONS).where(APPROBATIONS.c.id == ident)).mappings().one_or_none()
    if row is None:
        return None
    data = dict(row)
    try:
        data["arguments"] = json.loads(data["arguments"])
        data["resultat"] = None if data["resultat"] is None else json.loads(data["resultat"])
    except (ValueError, TypeError):
        return None
    if (data["outil"], data["departement"], data["niveau"]) != (OUTIL, DEPARTEMENT, "N4"):
        return None
    if not _args_p(data["arguments"]):
        return None
    return data


def cible_revue(cnx, ident):
    """Discrimine sans décoder le métier : une demande corrompue reste spécialisée."""
    if cnx is None or not _texte(ident, 32):
        return False
    return cnx.execute(select(APPROBATIONS.c.outil).where(APPROBATIONS.c.id == ident)).scalar_one_or_none() == OUTIL


def accuse_revue(reponse):
    if type(reponse) is not dict or type(reponse.get("resultat")) is not dict:
        return False
    accuse = reponse["resultat"].get("resultat")
    return type(accuse) is dict and accuse.get("outil") == OUTIL


def preuve_proposition(cnx: Connection | None, demande_id: str, arguments: dict[str, Any]):
    """Prouve la création passée ; le statut courant APP ne prouve pas une décision D."""
    demande = _demande(cnx, demande_id)
    if demande is None or not _args_p(arguments) or not _args_p(demande["arguments"]):
        return None, _refus()
    empreinte = idempotence.empreinte_arguments(arguments)
    if idempotence.empreinte_arguments(demande["arguments"]) != empreinte:
        return None, _refus()
    rows = cnx.execute(select(JOURNAL).where(
        JOURNAL.c.action == "approbation.demander_humain", JOURNAL.c.cible == demande_id,
    )).mappings().all()
    if len(rows) != 1:
        return None, _refus()
    row = rows[0]
    try:
        details = json.loads(row["details"])
    except (ValueError, TypeError):
        return None, _refus()
    if type(details) is not dict or set(details) != {
        "role", "appareil", "request_id", "departement", "outil", "niveau", "arguments_sha256",
    } or (details["departement"], details["outil"], details["niveau"], details["role"]) != (
        DEPARTEMENT, OUTIL, "N4", "admin",
    ) or details["arguments_sha256"] != empreinte:
        return None, _refus()
    if not all(_texte(v) for v in (row["par"], details["appareil"], details["request_id"])):
        return None, _refus()
    # L'heure P n'est pas une attestation du journal : elle n'entre pas dans cette preuve.
    meta_p = idempotence.Meta(details["request_id"], details["appareil"], "")
    claim = idempotence._lire(cnx, meta_p)
    if claim is None or claim["outil"] != OUTIL or claim["empreinte_arguments"] != empreinte:
        return None, _refus()
    if claim["statut"] not in {"en_cours", "en_attente_approbation"}:
        return None, _refus()
    preuve = {"demande_id": demande_id, "departement": DEPARTEMENT, "outil": OUTIL, "niveau": "N4",
              "empreinte_arguments": empreinte, "proposant": {"personne": row["par"], "role": details["role"],
              "appareil_id": details["appareil"], "intention_uuid": details["request_id"]}}
    return preuve, None


def association_decision(cnx: Connection | None, *, fraiche=False):
    captured = _DECISION.get()
    if cnx is None or captured is None:
        return None, _refus("REJ-HUMAIN-REQUIS")
    meta, args = captured.meta, captured.arguments
    if not all(_texte(v) for v in (meta.appareil, meta.cle)) or not _hora(meta.horodatage_appareil):
        return None, _refus()
    if not {"demande_id", "decision"} <= set(args) <= {"demande_id", "decision", "motif"}:
        return None, _refus()
    if (not _texte(args["demande_id"], 32) or type(args["decision"]) is not str
            or args["decision"] not in {"approuver", "refuser"}):
        return None, _refus()
    if "motif" in args and (type(args["motif"]) is not str or len(args["motif"].strip()) > 500):
        return None, _refus()
    claim = idempotence._lire(cnx, meta)
    if (claim is None or claim["outil"] != DECIDER
            or claim["empreinte_arguments"] != idempotence.empreinte_arguments(args)):
        return None, _refus()
    if claim["horodatage_appareil"] != meta.horodatage_appareil or not _hora(claim["horodatage_appareil"]):
        return None, _refus()
    if claim["statut"] not in ({"en_cours"} if fraiche else {"en_cours", "ok", "refus_metier"}):
        return None, _refus()
    return {"appareil_id": meta.appareil, "intention_uuid": meta.cle,
            "empreinte_arguments": claim["empreinte_arguments"],
            "horodatage_appareil_declare": claim["horodatage_appareil"]}, None


def donnees_execution(cnx, outil, departement, arguments):
    if (outil, departement) != (OUTIL, DEPARTEMENT):
        return None, _refus()
    signataire = approbations.approbateur_en_cours(cnx, outil, departement, roles=frozenset({"nathan_owner"}))
    ident = contexte.demande_approuvee_en_cours()
    demande = _demande(cnx, ident)
    if signataire is None or demande is None or demande["statut"] != "en_cours" or not _hora(demande["decide_le"]):
        return None, _refus("REJ-HUMAIN-REQUIS")
    preuve, refus = preuve_proposition(cnx, ident, arguments)
    if refus is not None:
        return None, refus
    association, refus = association_decision(cnx, fraiche=True)
    captured = _DECISION.get()
    if refus is not None or captured.arguments["demande_id"] != ident or captured.arguments["decision"] != "approuver":
        return None, refus or _refus()
    return {"demande_approbation_id": ident, "empreinte_arguments_proposition": preuve["empreinte_arguments"],
            "proposant": preuve["proposant"], "approuve_par": signataire.personne,
            "role_approbateur": signataire.role, "horodatage_decision_serveur": demande["decide_le"],
            "association_decision": association}, None


def donnees_historique(cnx, outil, departement, intervention_id, demande_id):
    appelante = contexte.identite_appelante()
    signataire = approbations.signataire_valide(cnx, appelante) if cnx is not None else None
    if signataire is None or signataire.source != "appareil" or signataire.role != "admin":
        return None, _refus("REJ-HUMAIN-REQUIS")
    demande = _demande(cnx, demande_id)
    if (outil, departement) != (OUTIL, DEPARTEMENT) or demande is None:
        return None, _refus()
    arguments = demande["arguments"]
    if not _args_p(arguments) or arguments["intervention_id"] != intervention_id:
        return None, _refus()
    preuve, refus = preuve_proposition(cnx, demande_id, arguments)
    if refus is not None:
        return None, refus
    projection = {k: _copie(demande[k]) for k in (
        "id", "cree_le", "departement", "outil", "niveau", "arguments", "statut", "decide_par",
        "decide_role", "decide_le", "motif_decision",
    )}
    from m4_field_ops import registre, revue_completion_sources

    reg = registre.Registre(stockage.maillons(DEPARTEMENT, "principal"))
    if not reg.valider_chaine():
        return None, _refus()
    resolution, refus = revue_completion_sources.preuve_resolution_historique(
        reg.lire(), demande_id, arguments, preuve, projection,
    )
    if refus is not None:
        return None, refus
    if resolution is not None and not _resultat_conforme(demande, resolution):
        return None, _refus()
    issue = None if demande["resultat"] is None else approbations_appareil._issue(demande["resultat"])
    return {"demande": projection, "proposition": preuve, "issue": issue, "preuve_completion": resolution}, None


def _resultat_conforme(demande, preuve):
    attendu = {"ok": True, "resultat": {"accepte": True, "version_schema": 2, "resultat": preuve}}
    try:
        return json.dumps(demande["resultat"], sort_keys=True, ensure_ascii=False, allow_nan=False) == json.dumps(
            attendu, sort_keys=True, ensure_ascii=False, allow_nan=False,
        )
    except (TypeError, ValueError):
        return False


def autoriser_legacy(cnx, outil, departement):
    appelante = contexte.identite_appelante()
    if _DECISION.get() is not None or (appelante is not None and appelante.source == "appareil"):
        return _refus()
    ident = contexte.demande_approuvee_en_cours()
    if cnx is None or ident is None:
        return None  # mémoire pure/console v1 explicitement non liée
    rows = cnx.execute(select(JOURNAL.c.id).where(
        JOURNAL.c.action == "approbation.demander_humain", JOURNAL.c.cible == ident,
    )).all()
    if rows:
        return _refus()  # provenance DEVICE prouvée ou altérée : aucune promotion legacy
    return None


def verifier_rejeu_proposition(cnx, arguments, reponse, meta, personne):
    if type(reponse) is not dict or set(reponse) != {
        "ok", "version_schema", "statut", "demande_id", "details", "preuve_proposition",
    } or reponse["ok"] is not True or type(reponse["version_schema"]) is not int or reponse["version_schema"] != 1:
        return False
    if reponse["statut"] != "en_attente_approbation":
        return False
    claim = idempotence._lire(cnx, meta)
    if claim is None or not _hora(meta.horodatage_appareil) or claim["horodatage_appareil"] != meta.horodatage_appareil:
        return False  # Cohérence SQL avec l'heure originale ; aucune attestation cryptographique P.
    preuve, refus = preuve_proposition(cnx, reponse["demande_id"], arguments)
    if refus is not None or preuve != reponse["preuve_proposition"]:
        return False
    proposant = preuve["proposant"]
    return (proposant["appareil_id"], proposant["intention_uuid"], proposant["personne"]) == (
        meta.appareil, meta.cle, personne,
    )


def decision_revue_en_cours(cnx):
    capture = _DECISION.get()
    return capture is not None and cible_revue(cnx, capture.arguments.get("demande_id"))


def verifier_rejeu_decision(cnx, arguments, reponse):
    signataire, _ = approbations_appareil._signataire(cnx, contexte.identite_appelante())
    if signataire is None or not signataire.proprietaire:
        return False
    association, refus = association_decision(cnx)
    demande = _demande(cnx, arguments.get("demande_id"))
    if refus is not None or demande is None:
        return False
    if type(reponse) is not dict or set(reponse) != {"ok", "resultat"} or reponse["ok"] is not True:
        return False
    metier = reponse["resultat"]
    if type(metier) is not dict or set(metier) != {"accepte", "resultat"} or metier["accepte"] is not True:
        return False
    accuse = metier["resultat"]
    requis = {"demande_id", "decision", "statut", "outil", "departement", "niveau", "decide_par",
              "role", "decide_le", "preuve_completion"}
    if type(accuse) is not dict or not requis <= set(accuse) <= requis | {"issue"}:
        return False
    if (accuse["demande_id"], accuse["decision"], accuse["statut"], accuse["outil"], accuse["departement"],
            accuse["niveau"], accuse["decide_par"], accuse["role"], accuse["decide_le"]) != (
        demande["id"], "approuver", "executee", OUTIL, DEPARTEMENT, "N4", demande["decide_par"],
        demande["decide_role"], demande["decide_le"],
    ) or demande["statut"] != "executee" or demande["decide_par"] != signataire.personne.identifiant:
        return False
    if arguments.get("decision") != "approuver" or demande["motif_decision"] != arguments.get("motif", "").strip():
        return False
    historique, refus = donnees_historique(cnx, OUTIL, DEPARTEMENT,
                                         demande["arguments"]["intervention_id"], demande["id"])
    if refus is not None or historique["preuve_completion"] is None:
        return False
    preuve = historique["preuve_completion"]
    if preuve != accuse["preuve_completion"] or preuve["association_decision"] != association:
        return False
    if not _resultat_conforme(demande, preuve):
        return False
    return accuse.get("issue") == historique["issue"]
