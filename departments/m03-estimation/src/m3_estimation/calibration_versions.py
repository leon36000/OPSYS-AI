"""Cycle de vie pur des candidates de calibration M3, jamais appliquées sans approbation N4.

Les candidats sont issus du train d'un rapport M3/M4 exact; l'évaluation n'accepte qu'un
holdout ultérieur inédit. Le journal durable et l'appel N4 restent dans outils.py.
"""

from __future__ import annotations

import hashlib
import json
import math
import random
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import (
    ROUND_HALF_EVEN,
    Clamped,
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    FloatOperation,
    InvalidOperation,
    Overflow,
    Underflow,
    localcontext,
)
from typing import Any

__all__ = [
    "POLITIQUE_INITIALE", "proposer_candidate", "evaluer_candidate", "activer_candidate",
    "revoquer_candidate", "version_active", "lire_candidate", "valider_journal",
    "empreinte_identifiant_wct",
]

POLITIQUE_INITIALE = {
    "version": "m3-time-promotion-policy/1",
    "minimum_chantiers_train": 30,
    "minimum_chantiers_holdout": 30,
    "couverture_minimale": "0.90",
    "amelioration_relative_minimale": "0.10",
    "amelioration_minutes_minimale": "1",
    "borne_confiance": "0.95",
    "replications_bootstrap": 10000,
    "p80_regression_maximale": "0.05",
    "resolution_mesure_minutes": 1,
    "qualification_empirique": "non_qualifiee_empiriquement",
}
_POLITIQUE_V1_VERROUILLEE = tuple(sorted(POLITIQUE_INITIALE.items()))
_CHAMPS_POLITIQUE_V1 = frozenset(cle for cle, _ in _POLITIQUE_V1_VERROUILLEE)

_HASH = re.compile(r"[0-9a-f]{64}\Z")
_DECIMAL = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?\Z")
_MAX_ENTRIES = 500
_MAX_EVENT_BYTES = 262144
_MAX_ROWS = 2000
_MAX_CHANTIERS = 500
_CALCUL_CONTEXTE = Context(prec=64, rounding=ROUND_HALF_EVEN, Emin=-999, Emax=999)
for _signal in _CALCUL_CONTEXTE.traps:
    _CALCUL_CONTEXTE.traps[_signal] = _signal in {
        Clamped, DivisionByZero, FloatOperation, InvalidOperation, Overflow, Underflow,
    }


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _json_borne(value: Any, limite_octets: int, limite_noeuds: int = 50000) -> bool:
    """Préflight itératif strict avant sérialisation/hash d'entrées potentiellement grandes."""
    pile = [(value, 0)]
    octets = 2
    noeuds = 0
    while pile:
        element, profondeur = pile.pop()
        noeuds += 1
        if noeuds > limite_noeuds or profondeur > 24:
            return False
        if isinstance(element, dict):
            octets += 2
            for cle, contenu in element.items():
                if not isinstance(cle, str) or len(cle) > limite_octets:
                    return False
                octets += len(cle.encode("utf-8")) + 4
                pile.append((contenu, profondeur + 1))
        elif isinstance(element, list):
            octets += 2 + len(element)
            pile.extend((contenu, profondeur + 1) for contenu in element)
        elif isinstance(element, str):
            if len(element) > limite_octets:
                return False
            octets += len(element.encode("utf-8")) + 2
        elif element is None or type(element) is bool:
            octets += 5
        elif type(element) is int:
            if element.bit_length() > 128:
                return False
            octets += 40
        elif type(element) is float and math.isfinite(element):
            octets += len(repr(element))
        else:
            return False
        if octets > limite_octets:
            return False
    return True


def _utc(value: Any) -> datetime | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        return None
    return parsed.astimezone(UTC)


def _number(value: Any, field: str) -> tuple[Decimal | None, str | None]:
    if not isinstance(value, str) or len(value) > 64 or _DECIMAL.fullmatch(value) is None:
        return None, f"{field}_invalide"
    try:
        canonical_value = value.rstrip("0").rstrip(".") if "." in value else value
        number = Decimal(canonical_value)
    except InvalidOperation:
        return None, f"{field}_invalide"
    if not number.is_finite() or number <= 0:
        return None, f"{field}_hors_bornes"
    return number, None


def _politique(value: Any) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(value, dict) or set(value) != _CHAMPS_POLITIQUE_V1:
        return None, "politique_forme_invalide"
    # R1 est un protocole fixe et non qualifié empiriquement : les paramètres ne peuvent pas être
    # abaissés sous le même identifiant de version. Une politique différente exige une nouvelle version
    # logicielle et un holdout indépendant, jamais une configuration locale réécrite.
    if value != dict(_POLITIQUE_V1_VERROUILLEE):
        return None, "politique_version_ou_parametres_invalides"
    for field in ("minimum_chantiers_train", "minimum_chantiers_holdout", "replications_bootstrap",
                  "resolution_mesure_minutes"):
        if type(value.get(field)) is not int or value[field] <= 0:
            return None, f"politique_{field}_invalide"
    if value["replications_bootstrap"] < 1000 or value["replications_bootstrap"] > 50000:
        return None, "politique_replications_bootstrap_hors_bornes"
    for field in ("couverture_minimale", "amelioration_relative_minimale", "amelioration_minutes_minimale",
                  "borne_confiance", "p80_regression_maximale"):
        number, reason = _number(value.get(field), field)
        if reason or number is None:
            return None, reason
        if field in {"couverture_minimale", "amelioration_relative_minimale", "borne_confiance",
                     "p80_regression_maximale"} and number > 1:
            return None, f"politique_{field}_hors_bornes"
    return dict(value), None


def _events(journal: Any) -> tuple[list[dict[str, Any]] | None, str | None]:
    try:
        if len(journal) > _MAX_ENTRIES:
            return None, "journal_limite_depassee"
        entries = list(journal)
    except (TypeError, ValueError, RecursionError, OverflowError):
        return None, "journal_illisible"
    previous = "0" * 64
    valid: list[dict[str, Any]] = []
    allowed_kinds = {"candidate_proposee", "candidate_evaluee", "candidate_activee", "candidate_revoquee"}
    for index, item in enumerate(entries):
        if not isinstance(item, dict) or set(item) != {
            "rang", "type_entree", "charge", "hash_precedent", "hash_maillon"
        }:
            return None, "journal_forme_invalide"
        if (type(item["rang"]) is not int or item["rang"] != index
                or item["hash_precedent"] != previous or not isinstance(item["charge"], dict)):
            return None, "journal_ordre_ou_chaine_invalide"
        if not isinstance(item["type_entree"], str) or item["type_entree"] not in allowed_kinds:
            return None, "journal_type_entree_invalide"
        charge = item["charge"]
        if not isinstance(charge.get("candidate_id"), str) or _HASH.fullmatch(charge["candidate_id"]) is None:
            return None, "journal_candidate_id_invalide"
        if "scope_id" in charge and (
            not isinstance(charge["scope_id"], str) or _HASH.fullmatch(charge["scope_id"]) is None
        ):
            return None, "journal_scope_id_invalide"
        if not _json_borne(charge, _MAX_EVENT_BYTES):
            return None, "journal_charge_limite_depassee"
        if item["type_entree"] == "candidate_proposee" and (
            set(charge) != {"candidate_id", "scope", "scope_id", "taux_minutes_par_unite_candidat",
                            "rapport_source_sha256", "rapport_source_cutoff_utc", "source_horizon_utc",
                            "holdout_cutoff_utc", "protocole_version", "politique", "politique_sha256",
                            "train_chantiers", "source_wct_prefix",
                            "source_wct_hashes_vus", "source_chantier_hashes_train", "candidate_active"}
            or not isinstance(charge.get("scope"), dict)
        ):
            return None, "journal_candidate_forme_invalide"
        if item["type_entree"] == "candidate_proposee":
            sans_id = {key: value for key, value in charge.items() if key != "candidate_id"}
            policy, policy_error = _politique(charge.get("politique"))
            scope = charge["scope"]
            scope_names = ("type_service", "unite_quantite", "bareme_version")
            segment_names_valide = all(
                isinstance(scope.get(key), str) and 0 < len(scope[key]) <= 128
                and all(char.isprintable() for char in scope[key]) for key in scope_names
            )
            reference, ref_error = _number(scope.get("taux_minutes_par_unite_reference"), "taux_reference")
            candidate_rate, candidate_error = _number(charge.get("taux_minutes_par_unite_candidat"), "taux_candidat")
            quantity, quantity_error = _number(scope.get("quantite_exacte"), "quantite")
            parent = scope.get("parent_calibration_version_id")
            prefix = charge.get("source_wct_prefix")
            prefix_valid = (
                isinstance(prefix, dict)
                and set(prefix) == {"count", "sha256", "wct_id_hashes"}
                and type(prefix.get("count")) is int and 0 <= prefix["count"] <= _MAX_ROWS
                and isinstance(prefix.get("sha256"), str) and _HASH.fullmatch(prefix["sha256"]) is not None
                and isinstance(prefix.get("wct_id_hashes"), list)
                and len(prefix["wct_id_hashes"]) == prefix["count"]
                and prefix["wct_id_hashes"] == sorted(set(prefix["wct_id_hashes"]))
                and all(isinstance(v, str) and _HASH.fullmatch(v) is not None for v in prefix["wct_id_hashes"])
            )
            if (
                set(charge["scope"]) != {"type_service", "unite_quantite", "bareme_version", "empreinte_bareme",
                                          "quantite_exacte", "taux_minutes_par_unite_reference",
                                          "parent_calibration_version_id"}
                or _hash(charge["scope"]) != charge["scope_id"]
                or _hash(sans_id) != charge["candidate_id"]
                or policy_error is not None or policy is None
                or _hash(policy) != charge["politique_sha256"]
                or charge.get("candidate_active") is not False
                or not segment_names_valide
                or not isinstance(scope.get("empreinte_bareme"), str)
                or _HASH.fullmatch(scope["empreinte_bareme"]) is None
                or (parent is not None and (not isinstance(parent, str) or _HASH.fullmatch(parent) is None))
                or ref_error is not None or reference is None or candidate_error is not None or candidate_rate is None
                or quantity_error is not None or quantity is None
                or type(charge.get("train_chantiers")) is not int
                or not 1 <= charge["train_chantiers"] <= _MAX_CHANTIERS
                or charge.get("protocole_version") != "cohortes-r32-v1"
                or _utc(charge.get("rapport_source_cutoff_utc")) is None
                or _utc(charge.get("source_horizon_utc")) is None
                or _utc(charge.get("holdout_cutoff_utc")) is None
                or _utc(charge["holdout_cutoff_utc"]) < _utc(charge["source_horizon_utc"])
                or not isinstance(charge.get("rapport_source_sha256"), str)
                or _HASH.fullmatch(charge["rapport_source_sha256"]) is None
                or not prefix_valid
                or not isinstance(charge.get("source_wct_hashes_vus"), list)
                or len(charge["source_wct_hashes_vus"]) > _MAX_ROWS
                or any(not isinstance(v, str) or _HASH.fullmatch(v) is None for v in charge["source_wct_hashes_vus"])
                or charge["source_wct_hashes_vus"] != sorted(set(charge["source_wct_hashes_vus"]))
                or charge["source_wct_hashes_vus"] != prefix.get("wct_id_hashes")
                or not isinstance(charge.get("source_chantier_hashes_train"), list)
                or len(charge["source_chantier_hashes_train"]) > _MAX_CHANTIERS
                or any(not isinstance(v, str) or _HASH.fullmatch(v) is None
                       for v in charge["source_chantier_hashes_train"])
                or charge["source_chantier_hashes_train"] != sorted(set(charge["source_chantier_hashes_train"]))
            ):
                return None, "journal_candidate_integrite_invalide"
        if item["type_entree"] == "candidate_evaluee" and (
            set(charge) != {"candidate_id", "statut", "holdout_sha256", "holdout_wct_hashes",
                            "holdout_chantiers", "couverture_numerateur", "couverture_denominateur",
                            "couverture", "mae_baseline_minutes", "mae_candidate_minutes",
                            "amelioration_relative", "p80_baseline_minutes", "p80_candidate_minutes",
                            "borne_basse_amelioration_minutes", "replications_bootstrap", "politique_sha256",
                            "raisons", "compteurs_refus_holdout", "candidate_active"}
        ):
            return None, "journal_evaluation_forme_invalide"
        if item["type_entree"] == "candidate_evaluee":
            hashes = charge.get("holdout_wct_hashes")
            if (
                charge.get("candidate_active") is not False
                or charge.get("statut") not in {"acceptable", "insuffisant"}
                or not isinstance(hashes, list) or len(hashes) > _MAX_ROWS
                or hashes != sorted(hashes)
                or any(not isinstance(v, str) or _HASH.fullmatch(v) is None for v in hashes)
                or charge.get("holdout_sha256") != _hash(hashes)
                or not isinstance(charge.get("politique_sha256"), str)
                or _HASH.fullmatch(charge["politique_sha256"]) is None
            ):
                return None, "journal_evaluation_integrite_invalide"
        if item["type_entree"] in {"candidate_activee", "candidate_revoquee"} and (
            set(charge) != {"candidate_id", "scope_id", "active_version_precedente",
                            "active_version_attendue", "approbateur", "role_approbateur", "candidate_active"}
            if item["type_entree"] == "candidate_activee"
            else set(charge) != {"candidate_id", "scope_id", "version_cible", "active_version_attendue",
                                "approbateur", "role_approbateur", "candidate_active"}
        ):
            return None, "journal_decision_forme_invalide"
        if item["type_entree"] in {"candidate_activee", "candidate_revoquee"}:
            active = item["type_entree"] == "candidate_activee"
            if (
                charge.get("candidate_active") is not active
                or charge.get("role_approbateur") != "nathan_owner"
                or not isinstance(charge.get("approbateur"), str)
                or not charge["approbateur"] or len(charge["approbateur"]) > 128
                or (active and charge.get("active_version_attendue") != charge.get("active_version_precedente"))
            ):
                return None, "journal_decision_integrite_invalide"
        body = {key: item[key] for key in ("rang", "type_entree", "charge", "hash_precedent")}
        try:
            if not _json_borne(body, _MAX_EVENT_BYTES):
                return None, "journal_charge_limite_depassee"
            expected_hash = _hash(body)
        except (TypeError, ValueError, RecursionError, OverflowError):
            return None, "journal_charge_invalide"
        if not isinstance(item["hash_maillon"], str) or expected_hash != item["hash_maillon"]:
            return None, "journal_hash_invalide"
        previous = item["hash_maillon"]
        valid.append(item)
    return valid, None


def valider_journal(journal: Any) -> tuple[bool, str | None]:
    _, reason = _events(journal)
    return reason is None, reason


def lire_candidate(journal: Any, candidate_id: str) -> dict[str, Any] | None:
    """Lit une candidate préenregistrée après validation complète du journal durable."""
    if not isinstance(candidate_id, str) or _HASH.fullmatch(candidate_id) is None:
        return None
    events, reason = _events(journal)
    if reason or events is None:
        raise ValueError(reason or "journal_illisible")
    candidates, _ = _candidate_state(events)
    return candidates.get(candidate_id)


def _append(journal: Any, kind: str, payload: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    events, reason = _events(journal)
    if reason:
        return None, reason
    assert events is not None
    previous = events[-1]["hash_maillon"] if events else "0" * 64
    body = {"rang": len(events), "type_entree": kind, "charge": payload, "hash_precedent": previous}
    try:
        if not _json_borne(body, _MAX_EVENT_BYTES):
            return None, "journal_charge_limite_depassee"
    except (TypeError, ValueError, RecursionError, OverflowError):
        return None, "journal_charge_invalide"
    event = {**body, "hash_maillon": _hash(body)}
    _, validation_error = _events([*events, event])
    if validation_error:
        return None, validation_error
    try:
        if len(journal) >= _MAX_ENTRIES:
            return None, "journal_limite_depassee"
        if isinstance(journal, list):
            journal.append(event)
        else:
            journal.append(event, rang_attendu=len(events))
    except Exception as exc:  # durable CAS conflict is converted to a fail-closed result by the adapter
        return None, f"ecriture_concurrente:{type(exc).__name__}"
    return event, None


def _id_hash(value: Any) -> str | None:
    return empreinte_identifiant_wct(value)


def empreinte_identifiant_wct(value: Any) -> str | None:
    """Empreinte publique stable d'un identifiant WCT selon le canon JSON du journal."""
    return _hash(value) if isinstance(value, str) and value else None


def _candidate_state(events: list[dict[str, Any]]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    candidates: dict[str, dict[str, Any]] = {}
    evaluations: dict[str, dict[str, Any]] = {}
    for event in events:
        payload = event["charge"]
        if event["type_entree"] == "candidate_proposee":
            candidates[payload["candidate_id"]] = payload
        elif event["type_entree"] == "candidate_evaluee":
            evaluations[payload["candidate_id"]] = payload
    return candidates, evaluations


def _active(events: list[dict[str, Any]], scope: dict[str, Any]) -> str | None:
    current = None
    for event in events:
        payload = event["charge"]
        if event["type_entree"] not in {"candidate_activee", "candidate_revoquee"}:
            continue
        if payload.get("scope_id") == scope["scope_id"]:
            current = payload.get("candidate_id") if event["type_entree"] == "candidate_activee" else None
    return current


def proposer_candidate(journal: Any, rapport: Any, *, politique: Any) -> dict[str, Any]:
    events, reason = _events(journal)
    if reason:
        return {"statut": "refuse", "raisons": [reason], "candidate_active": False}
    policy, reason = _politique(politique)
    if reason or policy is None:
        return {"statut": "refuse", "raisons": [reason or "politique_invalide"], "candidate_active": False}
    if (
        not isinstance(rapport, dict) or rapport.get("statut") != "candidate"
        or rapport.get("candidate_active") is not False
        or rapport.get("protocole_version") != "cohortes-r32-v1"
        or not isinstance(rapport.get("rapport_sha256"), str)
        or _HASH.fullmatch(rapport["rapport_sha256"]) is None
    ):
        return {"statut": "insuffisant", "raisons": ["rapport_source_non_admissible"], "candidate_active": False}
    rapport_sans_hash = {key: value for key, value in rapport.items()
                         if key not in {"rapport_sha256", "observations_qualifiees", "_observations_qualifiees"}}
    if not _json_borne(rapport_sans_hash, 1_048_576) or _hash(rapport_sans_hash) != rapport["rapport_sha256"]:
        return {"statut": "refuse", "raisons": ["rapport_source_hash_invalide"], "candidate_active": False}
    cutoff = _utc(rapport.get("coupure_utc"))
    horizon = _utc(rapport.get("source_horizon_utc"))
    holdout_cutoff = _utc(rapport.get("holdout_cutoff_utc"))
    provenance = rapport.get("provenance_observations")
    segments = rapport.get("segments")
    source_prefix = rapport.get("source_wct_prefix")
    if (cutoff is None or horizon is None or holdout_cutoff is None or holdout_cutoff < horizon
            or not isinstance(provenance, list)
            or len(provenance) > _MAX_ROWS or not isinstance(segments, list) or len(segments) > _MAX_CHANTIERS
            or not isinstance(source_prefix, dict)
            or set(source_prefix) != {"count", "sha256", "wct_id_hashes"}
            or type(source_prefix.get("count")) is not int or not 0 <= source_prefix["count"] <= _MAX_ROWS
            or not isinstance(source_prefix.get("sha256"), str)
            or _HASH.fullmatch(source_prefix["sha256"]) is None
            or not isinstance(source_prefix.get("wct_id_hashes"), list)
            or len(source_prefix["wct_id_hashes"]) != source_prefix["count"]
            or source_prefix["wct_id_hashes"] != sorted(set(source_prefix["wct_id_hashes"]))
            or any(not isinstance(v, str) or _HASH.fullmatch(v) is None for v in source_prefix["wct_id_hashes"])):
        return {"statut": "refuse", "raisons": ["provenance_rapport_incomplete"], "candidate_active": False}
    known_wcts: list[str] = []
    train_chantiers: set[str] = set()
    for row in provenance:
        if (not isinstance(row, dict) or not isinstance(row.get("wct_id"), str)
                or not row["wct_id"] or len(row["wct_id"]) > 256):
            return {"statut": "refuse", "raisons": ["provenance_wct_invalide"], "candidate_active": False}
        wct_hash = _id_hash(row["wct_id"])
        if wct_hash in known_wcts:
            return {"statut": "refuse", "raisons": ["wct_source_duplique"], "candidate_active": False}
        known_wcts.append(wct_hash)
        if row.get("partition") not in {"train", "holdout"}:
            return {"statut": "refuse", "raisons": ["partition_source_invalide"], "candidate_active": False}
        chantier_hash = row.get("chantier_sha256")
        if not isinstance(chantier_hash, str) or _HASH.fullmatch(chantier_hash) is None:
            return {"statut": "refuse", "raisons": ["chantier_source_hash_invalide"], "candidate_active": False}
        if row.get("partition") == "train":
            train_chantiers.add(chantier_hash)
    for row in rapport.get("exclusions", []):
        if isinstance(row, dict) and isinstance(row.get("wct_id"), str):
            known_wcts.append(_id_hash(row["wct_id"]))
    for row in rapport.get("refus_projection_m4", []):
        if isinstance(row, dict) and isinstance(row.get("wct_id"), str):
            known_wcts.append(_id_hash(row["wct_id"]))
    known_wcts.extend(source_prefix["wct_id_hashes"])
    if len(known_wcts) != len(set(known_wcts)):
        known_wcts = sorted(set(known_wcts))
    if known_wcts != source_prefix["wct_id_hashes"]:
        return {"statut": "refuse", "raisons": ["prefixe_wct_rapport_non_concordant"],
                "candidate_active": False}
    if len(train_chantiers) > _MAX_CHANTIERS:
        return {"statut": "refuse", "raisons": ["limite_chantiers_train_depassee"], "candidate_active": False}
    candidates = []
    for index, segment in enumerate(segments):
        if not isinstance(segment, dict) or segment.get("statut") != "candidate":
            continue
        train = segment.get("train")
        try:
            train_count = train["chantiers"]
        except (TypeError, KeyError):
            train_count = 0
        if type(train_count) is not int or train_count < policy["minimum_chantiers_train"]:
            continue
        required = ("type_service", "unite_quantite", "bareme_version", "quantite_exacte",
                    "taux_minutes_par_unite_source", "taux_minutes_par_unite_candidat", "empreinte_bareme")
        if any(not isinstance(segment.get(key), str) for key in required):
            continue
        if _HASH.fullmatch(segment["empreinte_bareme"]) is None:
            continue
        baseline, why_base = _number(segment["taux_minutes_par_unite_source"], "taux_reference")
        proposed, why_proposal = _number(segment["taux_minutes_par_unite_candidat"], "taux_candidat")
        quantity, why_quantity = _number(segment["quantite_exacte"], "quantite")
        if why_base or why_proposal or why_quantity or baseline is None or proposed is None or quantity is None:
            continue
        if proposed <= 0 or quantity <= 0:
            continue
        candidates.append((index, segment, train_count, baseline, proposed, quantity))
    if not candidates:
        return {"statut": "insuffisant", "raisons": ["minimum_train_ou_segment_non_atteint"],
                "candidate_active": False}
    made: list[dict[str, Any]] = []
    prior_candidates, _ = _candidate_state(events)
    for _index, segment, train_count, baseline, proposed, quantity in candidates:
        scope = {
            "type_service": segment["type_service"], "unite_quantite": segment["unite_quantite"],
            "bareme_version": segment["bareme_version"], "empreinte_bareme": segment["empreinte_bareme"],
            "quantite_exacte": format(quantity, "f"),
            "taux_minutes_par_unite_reference": format(baseline, "f"),
            "parent_calibration_version_id": segment.get("calibration_version_id"),
        }
        scope_id = _hash(scope)
        payload_without_id = {
            "scope": scope, "scope_id": scope_id, "taux_minutes_par_unite_candidat": format(proposed, "f"),
            "rapport_source_sha256": rapport["rapport_sha256"], "rapport_source_cutoff_utc": rapport["coupure_utc"],
            "source_horizon_utc": rapport["source_horizon_utc"],
            "holdout_cutoff_utc": rapport["holdout_cutoff_utc"],
            "protocole_version": rapport.get("protocole_version"),
            "politique": policy, "politique_sha256": _hash(policy), "train_chantiers": train_count,
            "source_wct_hashes_vus": sorted(known_wcts), "source_chantier_hashes_train": sorted(train_chantiers),
            "source_wct_prefix": source_prefix,
            "candidate_active": False,
        }
        candidate_id = _hash(payload_without_id)
        payload = {"candidate_id": candidate_id, **payload_without_id}
        existing = prior_candidates.get(candidate_id)
        if existing is not None:
            if existing != payload:
                return {"statut": "refuse", "raisons": ["candidate_id_conflit"], "candidate_active": False}
            made.append(existing)
            continue
        _, append_error = _append(journal, "candidate_proposee", payload)
        if append_error:
            return {"statut": "refuse", "raisons": [append_error], "candidate_active": False}
        made.append(payload)
    return {"statut": "proposee", "candidates": made, "candidate_active": False,
            "politique_version": policy["version"], "politique_sha256": _hash(policy)}


def _validate_holdout_row(row: Any) -> tuple[dict[str, Any] | None, str | None]:
    required = {"wct_id", "chantier_id", "intervention_id", "devis_id", "horodatage_debut",
                "horodatage_completion", "statut", "duree_estimee_minutes", "duree_reelle_minutes",
                "type_service", "quantite", "unite_quantite", "taux_minutes_par_unite", "bareme_version",
                "empreinte_bareme", "calibration_version_id", "preuve"}
    optional = {"taux_minutes_par_unite_source"}
    if not isinstance(row, dict) or not required <= set(row) or set(row) - required - optional:
        return None, "observation_forme_invalide"
    proof = row["preuve"]
    if (not isinstance(proof, dict) or proof.get("liaison_exacte") is not True
            or proof.get("chaine_m3_valide") is not True):
        return None, "preuve_source_invalide"
    if proof.get("schema_trace") not in (2, 3) or proof.get("semantique_trace") != "duree_ecoulee_intervention":
        return None, "trace_non_qualifiee"
    if proof.get("semantique_reel") != "duree_ecoulee_intervention" or proof.get("unite_duree_estimee") != "minute" \
            or proof.get("unite_duree_reelle") != "minute":
        return None, "semantique_ou_unite_non_qualifiee"
    if proof.get("schema_trace") == 3:
        source_rate, source_reason = _number(row.get("taux_minutes_par_unite_source"), "taux_source")
        if source_reason or source_rate is None:
            return None, "taux_source_trace3_invalide"
    for key in ("m3_source_hash", "m4_wct_hash"):
        if not isinstance(proof.get(key), str) or _HASH.fullmatch(proof[key]) is None:
            return None, f"{key}_invalide"
    required_text = (
        "wct_id", "chantier_id", "intervention_id", "devis_id", "type_service", "unite_quantite",
        "bareme_version",
    )
    if any(not isinstance(row[key], str) or not row[key].strip() for key in required_text):
        return None, "identite_observation_invalide"
    if any(len(row[key]) > 256 or not all(char.isprintable() for char in row[key]) for key in required_text):
        return None, "identite_observation_hors_bornes"
    if not isinstance(row["empreinte_bareme"], str) or _HASH.fullmatch(row["empreinte_bareme"]) is None:
        return None, "empreinte_bareme_invalide"
    if row["statut"] != "completed_verified":
        return None, "statut_m4_non_verifie"
    start, end = _utc(row["horodatage_debut"]), _utc(row["horodatage_completion"])
    if start is None or end is None or end < start:
        return None, "chronologie_invalide"
    estimated, why = _number(row["duree_estimee_minutes"], "duree_estimee")
    if why or estimated is None:
        return None, why
    if type(row["duree_reelle_minutes"]) is not int or row["duree_reelle_minutes"] <= 0:
        return None, "duree_reelle_invalide"
    quantity, why = _number(row["quantite"], "quantite")
    if why or quantity is None:
        return None, why
    rate, why = _number(row["taux_minutes_par_unite"], "taux_reference")
    if why or rate is None:
        return None, why
    with localcontext() as ctx:
        ctx.prec = 64
        if quantity * rate != estimated:
            return None, "duree_estimee_non_concordante"
    if row["calibration_version_id"] is not None and (
        not isinstance(row["calibration_version_id"], str) or _HASH.fullmatch(row["calibration_version_id"]) is None
    ):
        return None, "calibration_version_id_invalide"
    return {**row, "_debut": start, "_fin": end, "_estime": estimated,
            "_reel": Decimal(row["duree_reelle_minutes"]), "_quantite": quantity, "_taux": rate}, None


def _nearest_rank(values: list[Decimal], percent: int) -> Decimal:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * percent / 100) - 1)]


def _bootstrap_lower(groups: dict[str, list[Decimal]], *, seed: int, repetitions: int, confidence: Decimal) -> Decimal:
    means = [sum(values) / Decimal(len(values)) for _, values in sorted(groups.items())]
    rng = random.Random(seed)
    distribution: list[Decimal] = []
    count = len(means)
    with localcontext() as ctx:
        ctx.prec = 64
        for _ in range(repetitions):
            sample = [means[rng.randrange(count)] for _ in range(count)]
            distribution.append(sum(sample) / Decimal(count))
    tail_rank = max(1, math.ceil(repetitions * (Decimal(1) - confidence) / 2))
    return sorted(distribution)[tail_rank - 1]


def _holdout_fingerprint(rows: list[dict[str, Any]]) -> tuple[str, list[str]]:
    hashes = sorted(_hash(row["wct_id"]) for row in rows)
    return _hash(hashes), hashes


def _evaluer_candidate(
    journal: Any,
    candidate_id: str,
    observations: Any,
    *,
    couverture_numerateur: int | None = None,
    couverture_denominateur: int | None = None,
) -> dict[str, Any]:
    if not isinstance(candidate_id, str) or _HASH.fullmatch(candidate_id) is None:
        return {"statut": "refuse", "raisons": ["candidate_id_invalide"], "candidate_active": False}
    events, reason = _events(journal)
    if reason:
        return {"statut": "refuse", "raisons": [reason], "candidate_active": False}
    assert events is not None
    candidates, evaluations = _candidate_state(events)
    candidate = candidates.get(candidate_id)
    if candidate is None:
        return {"statut": "refuse", "raisons": ["candidate_introuvable"], "candidate_active": False}
    if candidate_id in evaluations:
        return {"statut": "refuse", "raisons": ["candidate_deja_evaluee"], "candidate_active": False}
    if not isinstance(observations, list) or len(observations) > _MAX_ROWS:
        return {"statut": "refuse", "raisons": ["holdout_forme_ou_limite_invalide"], "candidate_active": False}
    denominator = len(observations) if couverture_denominateur is None else couverture_denominateur
    requested_numerator = couverture_numerateur
    if (type(denominator) is not int or denominator < 0 or denominator > 2000
            or (requested_numerator is not None
                and (type(requested_numerator) is not int or not 0 <= requested_numerator <= denominator))):
        return {"statut": "refuse", "raisons": ["couverture_invalide"], "candidate_active": False}
    seen_before = {h for event in events if event["type_entree"] == "candidate_evaluee"
                   for h in event["charge"].get("holdout_wct_hashes", [])}
    source_seen = set(candidate["source_wct_hashes_vus"])
    train_chantiers = set(candidate["source_chantier_hashes_train"])
    start_after = _utc(candidate["holdout_cutoff_utc"])
    if start_after is None:
        return {"statut": "refuse", "raisons": ["horizon_source_invalide"], "candidate_active": False}
    scope = candidate["scope"]
    baseline, _ = _number(scope["taux_minutes_par_unite_reference"], "taux_reference")
    proposed, _ = _number(candidate["taux_minutes_par_unite_candidat"], "taux_candidat")
    quantity_expected, _ = _number(scope["quantite_exacte"], "quantite")
    accepted: list[dict[str, Any]] = []
    reasons: dict[str, int] = defaultdict(int)
    seen_ids: set[str] = set()
    has_replay = False
    for raw in observations:
        row, why = _validate_holdout_row(raw)
        if why:
            reasons[why] += 1
            continue
        assert row is not None
        wid_hash = _hash(row["wct_id"])
        chantier_hash = _hash(row["chantier_id"])
        if wid_hash in source_seen or wid_hash in seen_before:
            reasons["holdout_deja_utilise"] += 1
            has_replay = True
            continue
        if row["_debut"] <= start_after:
            reasons["holdout_pas_futur"] += 1
            continue
        if chantier_hash in train_chantiers:
            reasons["chantier_train_holdout"] += 1
            continue
        if row["wct_id"] in seen_ids:
            reasons["wct_duplique_holdout"] += 1
            continue
        seen_ids.add(row["wct_id"])
        if (row["type_service"], row["unite_quantite"], row["bareme_version"],
            row["empreinte_bareme"], row["_quantite"], row["_taux"], row["calibration_version_id"]) != (
            scope["type_service"], scope["unite_quantite"], scope["bareme_version"],
            scope["empreinte_bareme"], quantity_expected, baseline, scope["parent_calibration_version_id"],
        ):
            reasons["segment_holdout_divergent"] += 1
            continue
        accepted.append(row)
    if has_replay:
        return {"statut": "refuse", "raisons": ["holdout_deja_utilise"], "candidate_active": False}
    if any(count > 1 for count in [len([r for r in accepted if r["chantier_id"] == j])
                                   for j in {r["chantier_id"] for r in accepted}]):
        # Les clusters multiples sont admis, mais chaque chantier ne pèse qu'une unité dans le bootstrap.
        pass
    if len({row["chantier_id"] for row in accepted}) > _MAX_CHANTIERS:
        return {"statut": "refuse", "raisons": ["limite_chantiers_holdout_depassee"],
                "candidate_active": False}
    holdout_hash, holdout_hashes = _holdout_fingerprint(accepted)
    chantier_count = len({row["chantier_id"] for row in accepted})
    numerator = len(accepted) if requested_numerator is None else requested_numerator
    coverage = Decimal(numerator) / Decimal(denominator) if denominator else Decimal(0)
    base_errors: list[Decimal] = []
    candidate_errors: list[Decimal] = []
    improvements_by_job: dict[str, list[Decimal]] = defaultdict(list)
    assert baseline is not None and proposed is not None and quantity_expected is not None
    for row in accepted:
        actual = row["_reel"]
        base_prediction = row["_quantite"] * baseline
        candidate_prediction = row["_quantite"] * proposed
        base_error = abs(actual - base_prediction)
        candidate_error = abs(actual - candidate_prediction)
        base_errors.append(base_error)
        candidate_errors.append(candidate_error)
        improvements_by_job[row["chantier_id"]].append(base_error - candidate_error)
    reasons["observations_retenues"] = len(accepted)
    policy = candidate["politique"]
    if chantier_count < policy["minimum_chantiers_holdout"]:
        reasons["minimum_holdout_non_atteint"] += 1
    if coverage < Decimal(policy["couverture_minimale"]):
        reasons["couverture_insuffisante"] += 1
    if not accepted:
        reasons["holdout_vide"] += 1
    mae_base = sum(base_errors) / Decimal(len(base_errors)) if base_errors else None
    mae_candidate = sum(candidate_errors) / Decimal(len(candidate_errors)) if candidate_errors else None
    improvement = mae_base - mae_candidate if mae_base is not None and mae_candidate is not None else None
    relative = improvement / mae_base if improvement is not None and mae_base and mae_base > 0 else Decimal(0)
    if improvement is None or improvement < Decimal(policy["amelioration_minutes_minimale"]):
        reasons["amelioration_minutes_insuffisante"] += 1
    if relative < Decimal(policy["amelioration_relative_minimale"]):
        reasons["amelioration_relative_insuffisante"] += 1
    p80_base = _nearest_rank(base_errors, 80) if base_errors else None
    p80_candidate = _nearest_rank(candidate_errors, 80) if candidate_errors else None
    max_regression = Decimal(policy["p80_regression_maximale"])
    if (p80_base is not None and p80_candidate is not None
            and ((p80_base == 0 and p80_candidate > 0)
                 or (p80_base > 0 and p80_candidate > p80_base * (1 + max_regression)))):
        reasons["garde_p80_regression"] += 1
    fingerprint_seed = int(_hash({"candidate_id": candidate_id, "holdout": holdout_hash})[:16], 16)
    lower = (
        _bootstrap_lower(improvements_by_job, seed=fingerprint_seed,
                         repetitions=policy["replications_bootstrap"],
                         confidence=Decimal(policy["borne_confiance"]))
        if improvements_by_job else Decimal(0)
    )
    if lower <= 0:
        reasons["borne_bootstrap_non_positive"] += 1
    status = "acceptable" if not reasons.keys() - {"observations_retenues"} else "insuffisant"
    payload = {
        "candidate_id": candidate_id, "statut": status, "holdout_sha256": holdout_hash,
        "holdout_wct_hashes": holdout_hashes, "holdout_chantiers": chantier_count,
        "couverture_numerateur": numerator, "couverture_denominateur": denominator,
        "couverture": format(coverage, "f"),
        "mae_baseline_minutes": format(mae_base, "f") if mae_base is not None else None,
        "mae_candidate_minutes": format(mae_candidate, "f") if mae_candidate is not None else None,
        "amelioration_relative": format(relative, "f"),
        "p80_baseline_minutes": format(p80_base, "f") if p80_base is not None else None,
        "p80_candidate_minutes": format(p80_candidate, "f") if p80_candidate is not None else None,
        "borne_basse_amelioration_minutes": format(lower, "f"),
        "replications_bootstrap": policy["replications_bootstrap"],
        "politique_sha256": candidate["politique_sha256"],
        "raisons": sorted(k for k, v in reasons.items() if v and k != "observations_retenues"),
        "compteurs_refus_holdout": dict(sorted((k, v) for k, v in reasons.items() if k != "observations_retenues")),
        "candidate_active": False,
    }
    _, append_error = _append(journal, "candidate_evaluee", payload)
    if append_error:
        return {"statut": "refuse", "raisons": [append_error], "candidate_active": False}
    return payload


def evaluer_candidate(
    journal: Any,
    candidate_id: str,
    observations: Any,
    *,
    couverture_numerateur: int | None = None,
    couverture_denominateur: int | None = None,
) -> dict[str, Any]:
    """Comparaison déterministe, isolée du contexte Decimal de l'appelant."""
    with localcontext(_CALCUL_CONTEXTE):
        try:
            return _evaluer_candidate(
                journal, candidate_id, observations,
                couverture_numerateur=couverture_numerateur,
                couverture_denominateur=couverture_denominateur,
            )
        except (DecimalException, ArithmeticError, InvalidOperation, OverflowError):
            return {"statut": "refuse", "raisons": ["arithmetique_calibration_invalide"],
                    "candidate_active": False}


def activer_candidate(
    journal: Any, candidate_id: str, *, active_version_attendue: str | None, approbateur: Any,
) -> dict[str, Any]:
    if not isinstance(candidate_id, str) or _HASH.fullmatch(candidate_id) is None:
        return {"accepte": False, "raisons": ["candidate_id_invalide"], "candidate_active": False}
    events, reason = _events(journal)
    if reason:
        return {"accepte": False, "raisons": [reason]}
    assert events is not None
    if not isinstance(approbateur, dict) or approbateur.get("role") != "nathan_owner" \
            or not isinstance(approbateur.get("personne"), str) or not approbateur["personne"]:
        return {"accepte": False, "raisons": ["approbateur_nathan_owner_requis"]}
    candidates, evaluations = _candidate_state(events)
    candidate = candidates.get(candidate_id)
    if candidate is None or evaluations.get(candidate_id, {}).get("statut") != "acceptable":
        return {"accepte": False, "raisons": ["candidate_non_evaluee_acceptable"]}
    scope = candidate["scope"]
    parent = candidate["scope"].get("parent_calibration_version_id")
    current = _active(events, {"scope_id": candidate["scope_id"]})
    if current == candidate_id:
        return {"accepte": True, "candidate_id": candidate_id, "active_version_precedente": parent,
                "deja_active": True, "candidate_active": True}
    if parent is None:
        parent_valid = active_version_attendue is None
    else:
        parent_candidate = candidates.get(parent)
        parent_valid = (
            parent_candidate is not None
            and _active(events, {"scope_id": parent_candidate["scope_id"]}) == parent
            and active_version_attendue == parent
            and parent_candidate["scope"]["type_service"] == scope["type_service"]
            and parent_candidate["scope"]["unite_quantite"] == scope["unite_quantite"]
            and parent_candidate["scope"]["bareme_version"] == scope["bareme_version"]
            and parent_candidate["scope"]["empreinte_bareme"] == scope["empreinte_bareme"]
            and parent_candidate["scope"]["quantite_exacte"] == scope["quantite_exacte"]
            and parent_candidate["taux_minutes_par_unite_candidat"] == scope["taux_minutes_par_unite_reference"]
        )
    # Refuse les branches concurrentes depuis la même version active; un enfant actif unique
    # rend la succession déterministe et le rollback restaure exactement son parent.
    enfants_actifs = [
        c["candidate_id"] for c in candidates.values()
        if c["scope"].get("parent_calibration_version_id") == parent
        and c["scope"].get("type_service") == scope["type_service"]
        and c["scope"].get("unite_quantite") == scope["unite_quantite"]
        and c["scope"].get("bareme_version") == scope["bareme_version"]
        and c["scope"].get("empreinte_bareme") == scope["empreinte_bareme"]
        and c["scope"].get("quantite_exacte") == scope["quantite_exacte"]
        and c["candidate_id"] != candidate_id
        and _active(events, {"scope_id": c["scope_id"]}) == c["candidate_id"]
    ]
    if current != (candidate_id if current == candidate_id else None) or not parent_valid or enfants_actifs:
        return {"accepte": False, "raisons": ["active_version_conflit"]}
    payload = {"candidate_id": candidate_id, "scope_id": candidate["scope_id"],
               "active_version_precedente": parent, "active_version_attendue": active_version_attendue,
               "approbateur": approbateur["personne"], "role_approbateur": approbateur["role"],
               "candidate_active": True}
    _, append_error = _append(journal, "candidate_activee", payload)
    if append_error:
        return {"accepte": False, "raisons": [append_error]}
    return {"accepte": True, "candidate_id": candidate_id, "active_version_precedente": parent,
            "candidate_active": True}


def revoquer_candidate(
    journal: Any, *, active_version_attendue: str, approbateur: Any,
) -> dict[str, Any]:
    if not isinstance(active_version_attendue, str) or _HASH.fullmatch(active_version_attendue) is None:
        return {"accepte": False, "raisons": ["candidate_id_invalide"], "candidate_active": False}
    events, reason = _events(journal)
    if reason:
        return {"accepte": False, "raisons": [reason]}
    assert events is not None
    if not isinstance(approbateur, dict) or approbateur.get("role") != "nathan_owner" \
            or not isinstance(approbateur.get("personne"), str) or not approbateur["personne"]:
        return {"accepte": False, "raisons": ["approbateur_nathan_owner_requis"]}
    candidates, _ = _candidate_state(events)
    candidate = candidates.get(active_version_attendue)
    if candidate is None:
        return {"accepte": False, "raisons": ["version_active_inconnue"]}
    scope_id = candidate["scope_id"]
    if _active(events, {"scope_id": scope_id}) != active_version_attendue:
        return {"accepte": False, "raisons": ["active_version_conflit"]}
    if any(
        item["scope"].get("parent_calibration_version_id") == active_version_attendue
        and _active(events, {"scope_id": item["scope_id"]}) == item["candidate_id"]
        for item in candidates.values()
    ):
        return {"accepte": False, "raisons": ["candidate_enfant_active"]}
    payload = {"candidate_id": active_version_attendue, "scope_id": scope_id,
               "version_cible": None, "active_version_attendue": active_version_attendue,
               "approbateur": approbateur["personne"], "role_approbateur": approbateur["role"],
               "candidate_active": False}
    _, append_error = _append(journal, "candidate_revoquee", payload)
    if append_error:
        return {"accepte": False, "raisons": [append_error]}
    return {"accepte": True, "version_revoquee": active_version_attendue, "version_cible": None,
            "candidate_active": False}


def version_active(
    journal: Any, type_service: str, unite_quantite: str, bareme_version: str,
    empreinte_bareme: str, quantite: str, taux_reference: str,
    calibration_version_id: str | None = None,
) -> dict[str, Any] | None:
    events, reason = _events(journal)
    if reason or events is None:
        raise ValueError(reason or "journal_illisible")
    quantity, quantity_error = _number(quantite, "quantite")
    rate, rate_error = _number(taux_reference, "taux_reference")
    if quantity_error or rate_error or quantity is None or rate is None:
        raise ValueError(quantity_error or rate_error or "scope_numerique_invalide")
    candidates, _ = _candidate_state(events)
    scope = {
        "type_service": type_service, "unite_quantite": unite_quantite, "bareme_version": bareme_version,
        "empreinte_bareme": empreinte_bareme, "quantite_exacte": format(quantity, "f"),
        "taux_minutes_par_unite_reference": format(rate, "f"),
        "parent_calibration_version_id": calibration_version_id,
    }
    scope_id = _hash(scope)
    current = _active(events, {"scope_id": scope_id})
    return candidates.get(current) if current is not None else None
