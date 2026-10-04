"""Capture financière privée, rapprochement humain et réutilisation du calculateur M5."""
from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from m5_financecore import encodage, outils
from sqlalchemy import LargeBinary, cast, func, select

from opsys import stockage
from opsys.stockage.schema import REGISTRES

_DEPARTEMENT = "m05-financecore"
_REGISTRES = ("principal", "factures", "comptes_a_payer")
_MAX_ROWS = 10_000
_MAX_BYTES = 8 * 1024 * 1024
_MAX_ROW_BYTES = 64 * 1024
_HEX64 = re.compile(r"^[a-f0-9]{64}$")
_AMOUNT = re.compile(r"^(?:0|[1-9][0-9]{0,8})\.[0-9]{2}$")


def _json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _unknown(reason: str) -> dict[str, Any]:
    # Ne jamais renvoyer l'exception, SQL, corps de journal ou le chiffre `au_plus`.
    return {"statut": "INCONNU", "cash_libre": None, "montant_utilisable": None, "raisons": [reason]}


def _cash(value: Any) -> str:
    if isinstance(value, Decimal):
        if not value.is_finite() or value < 0:
            raise ValueError("montant invalide")
        rounded = value.quantize(Decimal("0.01"))
        if rounded != value:
            raise ValueError("montant au-delà du cent")
        result = format(rounded, ".2f")
    elif isinstance(value, str):
        result = value
    else:
        raise ValueError("montant invalide")
    if not _AMOUNT.fullmatch(result):
        raise ValueError("montant invalide")
    return result


def _file_digest(path: Path) -> str:
    raw = path.read_bytes()
    return hashlib.sha256(raw).hexdigest()


def _guard_registers(cnx: Any) -> None:
    """Préborne avant l'appel aux lecteurs natifs; transaction SQLite bloque les auteurs."""
    if cnx.dialect.name != "sqlite":
        raise ValueError("backend non qualifié")
    octets = func.length(cast(REGISTRES.c.maillon, LargeBinary))
    count_expr = func.count()
    total_expr = func.coalesce(func.sum(octets), 0)
    max_expr = func.coalesce(func.max(octets), 0)
    total_rows = total_bytes = 0
    for name in _REGISTRES:
        filt = (REGISTRES.c.departement == _DEPARTEMENT) & (REGISTRES.c.registre == name)
        count, total, largest = cnx.execute(select(count_expr, total_expr, max_expr).where(filt)).one()
        if count > _MAX_ROWS or total > _MAX_BYTES or largest > _MAX_ROW_BYTES:
            raise ValueError("source hors borne")
        total_rows += count
        total_bytes += total
    if total_rows > len(_REGISTRES) * _MAX_ROWS or total_bytes > len(_REGISTRES) * _MAX_BYTES:
        raise ValueError("sources hors borne")


def _current_refs(cnx: Any) -> dict[str, dict[str, Any]]:
    """Relit seulement taille/tête courantes sous le même verrou, sans décoder l'historique."""
    from opsys.stockage import codec

    refs: dict[str, dict[str, Any]] = {}
    for name in _REGISTRES:
        filt = (REGISTRES.c.departement == _DEPARTEMENT) & (REGISTRES.c.registre == name)
        count, first, last = cnx.execute(select(
            func.count(), func.min(REGISTRES.c.rang), func.max(REGISTRES.c.rang),
        ).where(filt)).one()
        if count > _MAX_ROWS or (count and (first != 0 or last != count - 1)):
            raise ValueError("référence registre invalide")
        head = None
        if count:
            row = cnx.execute(select(REGISTRES.c.maillon).where(filt).order_by(REGISTRES.c.rang.desc()).limit(1)).one()
            last_link = codec.decoder(row[0])
            if not isinstance(last_link, dict) or not isinstance(last_link.get("ligne_id"), str):
                raise ValueError("tête de registre invalide")
            head = last_link["ligne_id"]
        refs[name] = {"taille": count, "tete": head}
    return refs


def _refs(lectures: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    names = ("maillons_mouvements", "maillons_factures", "maillons_a_payer")
    result: dict[str, dict[str, Any]] = {}
    for name, rows in zip(_REGISTRES, (lectures.get(k) for k in names), strict=True):
        if not isinstance(rows, list):
            raise ValueError("lecture absente")
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("ligne_id"), str):
                raise ValueError("maillon invalide")
        result[name] = {"taille": len(rows), "tete": rows[-1]["ligne_id"] if rows else None}
    return result


def _sources(lectures: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    declared = lectures.get("declarees")
    if not isinstance(declared, Mapping):
        raise ValueError("déclarations absentes")
    legacy: dict[str, dict[str, str]] = {}
    for category in ("paies", "das"):
        if category not in declared:
            continue
        triple = declared[category]
        if not isinstance(triple, Mapping) or set(triple) != {"montant", "source", "au"}:
            raise ValueError("déclaration illisible")
        amount = _cash(triple["montant"])
        if not isinstance(triple["source"], str) or not triple["source"].strip() or not isinstance(triple["au"], str):
            raise ValueError("déclaration illisible")
        legacy[category] = {"sha256": encodage.empreinte(dict(triple)), "montant_cad": amount}

    provisions: dict[str, dict[str, str]] = {}
    rows = lectures.get("maillons_mouvements")
    if not isinstance(rows, list):
        raise ValueError("mouvements absents")
    for row in rows:
        if row.get("type_entree") != "mouvement_enregistre" or row.get("type_mouvement") != "PROVISION":
            continue
        ref = row.get("ligne_id")
        if not isinstance(ref, str) or not _HEX64.fullmatch(ref):
            raise ValueError("provision sans identifiant stable")
        if ref in provisions:
            raise ValueError("provision dupliquée")
        provisions[ref] = {"sha256": encodage.empreinte(row), "montant_cad": _cash(row.get("montant"))}
    return {"legacy": legacy, "provisions": provisions}


def _snapshot_builder(config_hash: str, register_refs: Mapping[str, Any], sources: Mapping[str, Any],
                      extra_config: Mapping[str, str]) -> Callable[[str], dict[str, Any]]:
    def build(obligations_sha256: str) -> dict[str, Any]:
        if not isinstance(obligations_sha256, str) or not _HEX64.fullmatch(obligations_sha256):
            raise ValueError("empreinte obligations invalide")
        identity = {
            "schema": 1,
            "configuration_sha256": config_hash,
            "fichiers_financiers_sha256": dict(extra_config),
            "registres": register_refs,
            "obligations_sha256": obligations_sha256,
        }
        finance_id = hashlib.sha256(_json(identity)).hexdigest()
        return {
            "finance_snapshot_id": finance_id,
            "obligations_sha256": obligations_sha256,
            "sources": sources,
        }
    return build


def _private_declarations(lectures: dict[str, Any], projection: Mapping[str, Any]) -> dict[str, Any]:
    """Substitue uniquement les déclarations de paie/DAS et le crédit de réserves; aucun calcul ici."""
    amount = projection.get("montant_utilisable")
    if not isinstance(amount, Mapping):
        raise ValueError("projection absente")
    obligations = amount.get("obligations")
    mappings = amount.get("rapprochements")
    credits = amount.get("credits_provisions")
    if not isinstance(obligations, list) or not isinstance(mappings, list) or not isinstance(credits, Mapping):
        raise ValueError("projection mal formée")

    by_id = {x.get("id"): x.get("obligation") for x in obligations if isinstance(x, Mapping)}
    if len(by_id) != len(obligations) or any(
        not isinstance(k, str) or not isinstance(v, Mapping) for k, v in by_id.items()
    ):
        raise ValueError("obligations invalides")
    bases: dict[str, list[Mapping[str, Any]]] = {"paies": [], "das": []}
    used_legacy: set[str] = set()
    for mapping in mappings:
        if not isinstance(mapping, Mapping):
            raise ValueError("mapping invalide")
        mode = mapping.get("mode")
        if mode == "PROVISION_HORS_PAIE":
            if mapping.get("obligation_id") is not None or mapping.get("source_kind") != "provision":
                raise ValueError("classification de réserve invalide")
            continue
        if mapping.get("obligation_id") not in by_id:
            raise ValueError("mapping invalide")
        obligation = by_id[mapping["obligation_id"]]
        kind = obligation.get("type")
        if kind not in bases:
            raise ValueError("type d'obligation invalide")
        if mode == "LEGACY_IDENTIQUE":
            if mapping.get("source_ref") != kind or kind in used_legacy:
                raise ValueError("déclaration legacy réutilisée")
            used_legacy.add(kind)
        elif mode == "NOUVELLE_COMPOSANTE":
            bases[kind].append(obligation)
        elif mode not in {"PROVISION_CREDIT", "PROVISION_HORS_PAIE"}:
            raise ValueError("mode de rapprochement invalide")

    adapted = dict(lectures)
    adapted["declarees"] = dict(lectures["declarees"])
    for kind, components in bases.items():
        if not components:
            continue
        if kind in adapted["declarees"]:
            raise ValueError("composante legacy ambigüe")
        total = sum((Decimal(item["montant_cad"]) for item in components), Decimal("0.00"))
        consultation_dates = [item["source_consultee_le"] for item in components]
        if any(not isinstance(day, str) for day in consultation_dates):
            raise ValueError("date de source invalide")
        # Le libellé reste non normatif; la traçabilité détaillée demeure dans l'objet privé humain.
        adapted["declarees"][kind] = {
            "montant": format(total, ".2f"),
            "source": "rapprochement privé confirmé",
            "au": max(consultation_dates),
        }

    original_total, count, latest = adapted["provisions"]
    credit_total = sum((Decimal(_cash(value)) for value in credits.values()), Decimal("0.00"))
    remaining = original_total - credit_total
    if remaining < 0:
        raise ValueError("crédits supérieurs aux provisions")
    adapted["provisions"] = (remaining, count, latest)
    return adapted


@dataclass(frozen=True)
class CaptureFinancePrivee:
    """Contexte interne à une requête humaine; ne jamais sérialiser les lectures ou le callback."""

    sources: Mapping[str, Any]
    registres: Mapping[str, Any]
    snapshot_builder: Callable[[str], dict[str, Any]]
    verifier_sources_courantes: Callable[[], bool]
    _lectures: dict[str, Any]


def capturer_snapshot_prive(cnx: Any) -> CaptureFinancePrivee:
    """Capture M5 une seule fois, sans ouvrir/déchiffrer le journal d'obligations.

    Le caller autorisé projette ensuite avec `journal.lire_rapprochements(cnx, capture.snapshot_builder)`.
    """
    if stockage.connexion_courante() is not cnx or cnx.dialect.name != "sqlite":
        raise ValueError("capture financière indisponible")
    if not getattr(outils, "_stockage_durable_actif", False):
        raise ValueError("capture financière indisponible")
    _guard_registers(cnx)
    manifest_raw = outils._MANIFESTE.read_bytes()
    config_hash = hashlib.sha256(manifest_raw).hexdigest()
    manifest = yaml.safe_load(manifest_raw)
    config = manifest.get("configuration") if isinstance(manifest, dict) else None
    if not isinstance(config, dict):
        raise ValueError("capture financière indisponible")
    fiscal_hashes = {
        "calendrier": _file_digest(Path(outils._CHEMIN_CALENDRIER_FISCAL)),
        "taux": _file_digest(Path(outils._CHEMIN_TAUX_FISCAUX)),
    }
    lectures = outils._lectures_finance(
        outils._registre_mouvements(None), configuration=config, validateur_snapshot=outils._valider_chaines_cfo,
    )
    if lectures.get("verdict_chaine") is not None:
        raise ValueError("capture financière indisponible")
    refs = _refs(lectures)
    catalogs = _sources(lectures)
    # Détecte une modification de fichier ou de registre pendant la lecture native.
    if hashlib.sha256(outils._MANIFESTE.read_bytes()).hexdigest() != config_hash:
        raise ValueError("capture financière indisponible")
    if _file_digest(Path(outils._CHEMIN_CALENDRIER_FISCAL)) != fiscal_hashes["calendrier"] \
            or _file_digest(Path(outils._CHEMIN_TAUX_FISCAUX)) != fiscal_hashes["taux"]:
        raise ValueError("capture financière indisponible")
    _guard_registers(cnx)
    builder = _snapshot_builder(config_hash, refs, catalogs, fiscal_hashes)

    def verifier_sources_courantes() -> bool:
        """Garde terminale à appeler après chiffrement et juste avant l'append privé."""
        try:
            return (
                stockage.connexion_courante() is cnx
                and cnx.dialect.name == "sqlite"
                and getattr(outils, "_stockage_durable_actif", False)
                and hashlib.sha256(outils._MANIFESTE.read_bytes()).hexdigest() == config_hash
                and _file_digest(Path(outils._CHEMIN_CALENDRIER_FISCAL)) == fiscal_hashes["calendrier"]
                and _file_digest(Path(outils._CHEMIN_TAUX_FISCAUX)) == fiscal_hashes["taux"]
                and _guard_registers(cnx) is None
                and _current_refs(cnx) == refs
            )
        except Exception:
            return False

    return CaptureFinancePrivee(catalogs, refs, builder, verifier_sources_courantes, lectures)


def presenter_capture_privee(capture: CaptureFinancePrivee, projection: Mapping[str, Any]) -> dict[str, Any]:
    """Rend les sources et l’ID au formulaire même si la projection n’est pas encore utilisable."""
    digest = projection.get("obligations_sha256")
    snapshot = capture.snapshot_builder(digest) if isinstance(digest, str) and _HEX64.fullmatch(digest) else None
    connu = projection.get("statut") == "CONNU" and snapshot is not None
    return {
        "statut": "CONNU" if connu else "INCONNU",
        "finance_snapshot_id": snapshot["finance_snapshot_id"] if snapshot is not None else None,
        "snapshot": snapshot,
        "sources": capture.sources,
        "registres": capture.registres,
        "obligations_sha256": digest if snapshot is not None else None,
        "paie_das_revision": projection.get("revision"),
        "revision": projection.get("revision"),
        "paie_das_head": projection.get("paie_das_head"),
        "obligations_actives": projection.get("obligations_actives", []),
        "rapprochements": projection.get("rapprochements", []),
        "credits_provisions": projection.get("credits_provisions", {}),
        "raisons": projection.get("raisons", []) if not connu else [],
        "montant_utilisable": None,
    }


def calculer_capture_privee(capture: CaptureFinancePrivee, projection: Mapping[str, Any]) -> dict[str, Any]:
    """Réutilise une capture et un déchiffrement; le propriétaire M5 calcule une seule fois."""
    presentation = presenter_capture_privee(capture, projection)
    try:
        if not capture.verifier_sources_courantes():
            raise ValueError("sources modifiées")
        if presentation["statut"] != "CONNU":
            return {**presentation, "cash_libre": None, "montant_utilisable": None}
        adapted = _private_declarations(capture._lectures, projection)
        cash = outils._resultat_cash_libre(adapted)
        if not capture.verifier_sources_courantes():
            raise ValueError("sources modifiées")
        if not isinstance(cash, dict) or cash.get("cash_libre") is None:
            libelles = {"solde": "Solde", "taxes_a_remettre": "TPS/TVQ à remettre", "paies": "Paies",
                        "das": "DAS", "comptes_a_payer": "Comptes à payer", "dettes": "Dettes",
                        "reserves": "Réserves critiques"}
            manques = cash.get("manque", []) if isinstance(cash, dict) else []
            composants = {item.get("composante") for item in manques
                          if isinstance(item, Mapping) and item.get("composante") in libelles}
            raisons = ["Composante financière non calculable : " + libelles[k] for k in sorted(composants)]
            return {**presentation, "statut": "INCONNU", "cash_libre": None, "montant_utilisable": None,
                    "raisons": raisons or ["Composantes financières non calculables"]}
        return {**presentation, "cash_libre": cash, "montant_utilisable": cash.get("cash_libre")}
    except Exception:
        return {**presentation, "statut": "INCONNU", "cash_libre": None, "montant_utilisable": None,
                "raisons": ["Sources ou composantes financières non calculables"]}


def calculer_vue_privee(cnx: Any, journal: Any) -> dict[str, Any]:
    """Orchestre capture M5, unique projection du journal et calculateur M5 existant."""
    try:
        capture = capturer_snapshot_prive(cnx)
        projection = journal.lire_rapprochements(cnx, capture.snapshot_builder)
        return calculer_capture_privee(capture, projection)
    except Exception:
        return _unknown("Instantané financier ou rapprochement indisponible")
