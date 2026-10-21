"""État d'un contenu de chantier, calculé des registres append-only (PLAN T4.17).

Rien ne se modifie : une proposition, une décision, un export et un retrait sont chacun un maillon écrit une
fois. L'état d'un contenu est le PLIAGE de ces maillons, recalculé à chaque lecture. Le retrait l'emporte sur
tout : un contenu dont le chantier a un retrait de consentement est `CONSENTEMENT_RETIRE`, qu'il ait été
proposé, approuvé ou exporté (Loi 25 : un retrait bloque aussi un paquet déjà proposé).

Statuts : les trois du contrat `content-item.v1` (`PROPOSE`, `APPROVED`, `REJECTED`) et `CONSENTEMENT_RETIRE`.

Module pur : aucune entrée-sortie, aucun import `opsys`.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from .retrait import retrait_applicable

STATUT_PROPOSE = "PROPOSE"
STATUT_APPROUVE = "APPROVED"
STATUT_REJETE = "REJECTED"
STATUT_RETIRE = "CONSENTEMENT_RETIRE"
STATUTS = (STATUT_PROPOSE, STATUT_APPROUVE, STATUT_REJETE, STATUT_RETIRE)


def fraicheur_marque(proposition: Mapping[str, Any], preuve_courante: Any) -> str:
    """Projection pure ; n'attribue jamais une marque courante à un ancien brouillon."""
    preuve = proposition.get("marque_source")
    if not isinstance(preuve, Mapping) or set(preuve) != {"source", "revision", "sha256"}:
        return "preuve_absente"
    if preuve.get("source") not in {"brand_profiles", "yaml_legacy"} or not isinstance(preuve.get("sha256"), str) \
            or not re.fullmatch(r"[0-9a-f]{64}", preuve["sha256"]) or (
                preuve["source"] == "brand_profiles" and (type(preuve["revision"]) is not int or preuve["revision"] < 1)
            ) or (preuve["source"] == "yaml_legacy" and preuve["revision"] is not None):
        return "preuve_absente"
    return "courante" if dict(preuve) == preuve_courante else "perimee"


def dernieres_revisions(
    propositions: Iterable[Mapping[str, Any]], wct_id: str | None = None,
) -> list[Mapping[str, Any]]:
    """La dernière révision de chaque (chantier, plateforme), de la plus ancienne à la plus récente.

    Une révision naît après un rejet (nouveau texte) ou une reproposition explicite avec
    une marque différente/non prouvée. Les précédentes restent au registre."""
    courantes: dict[tuple[str, str], Mapping[str, Any]] = {}
    for proposition in propositions:
        if wct_id is not None and proposition["wct_id"] != wct_id:
            continue
        cle = (proposition["wct_id"], proposition["plateforme"])
        courantes.pop(cle, None)  # la révision la plus récente prend la place de la plus récente
        courantes[cle] = proposition
    return list(courantes.values())


def proposition_par_id(propositions: Iterable[Mapping[str, Any]], contenu_id: str) -> Mapping[str, Any] | None:
    for proposition in propositions:
        if proposition["contenu_id"] == contenu_id:
            return proposition
    return None


def est_derniere_revision(proposition: Mapping[str, Any], propositions: Iterable[Mapping[str, Any]]) -> bool:
    cle = (proposition["wct_id"], proposition["plateforme"])
    plus_recente = max(
        (p["revision"] for p in propositions if (p["wct_id"], p["plateforme"]) == cle), default=proposition["revision"],
    )
    return proposition["revision"] >= plus_recente


def decision_de(contenu_id: str, decisions: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    trouvee = None
    for decision in decisions:
        if decision["contenu_id"] == contenu_id:
            trouvee = decision
    return trouvee


def export_de(contenu_id: str, exports: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    for export in exports:
        if export["contenu_id"] == contenu_id:
            return export
    return None


def statut(
    proposition: Mapping[str, Any], decisions: Iterable[Mapping[str, Any]], retraits: Iterable[Mapping[str, Any]],
) -> str:
    """Le statut d'une proposition : le retrait de son chantier, sinon sa décision, sinon `PROPOSE`."""
    if retrait_applicable(proposition["wct_id"], proposition.get("lead_id"), retraits) is not None:
        return STATUT_RETIRE
    decision = decision_de(proposition["contenu_id"], decisions)
    if decision is None:
        return STATUT_PROPOSE
    return STATUT_APPROUVE if decision["decision"] == STATUT_APPROUVE else STATUT_REJETE


def vue(
    proposition: Mapping[str, Any], decisions: Iterable[Mapping[str, Any]], exports: Iterable[Mapping[str, Any]],
    retraits: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """La proposition, avec son statut du moment, sa décision (qui, quand) et si elle a été exportée."""
    decisions = list(decisions)
    retraits = list(retraits)
    decision = decision_de(proposition["contenu_id"], decisions)
    return {
        **proposition,
        "approval_status": statut(proposition, decisions, retraits),
        "decision": None if decision is None else {
            "decision": decision["decision"], "par": decision["par"], "role": decision["role"],
            "source": decision["source"], "motif": decision["motif"], "horodatage": decision["horodatage"],
        },
        "exporte": export_de(proposition["contenu_id"], exports) is not None,
    }


def etat_dossier_medias(evenements: Iterable[Mapping[str, Any]], contenu_id: str) -> dict[str, Any]:
    """Plie les préparations et revues médias append-only d'un contenu, sans IO ni octets."""
    dossier: list[Mapping[str, Any]] = []
    revision = 0
    decision_revue: str | None = None
    preparation_apres_revue = False
    remis = False
    snapshot_epoch: str | None = None
    preparations_courantes: dict[str, str] = {}
    for evenement in evenements:
        if not isinstance(evenement, Mapping):
            return {"valide": False, "statut": "DOSSIER_INCOHERENT", "revision": revision, "medias": []}
        if evenement.get("contenu_id") != contenu_id:
            continue
        type_maillon = evenement.get("type_maillon")
        if type(evenement.get("revision")) is not int or evenement.get("revision") != revision + 1 or not isinstance(
            type_maillon, str,
        ) or type_maillon not in {
            "media_reprise", "media_prepare", "media_revue", "media_remise",
        }:
            return {"valide": False, "statut": "DOSSIER_INCOHERENT", "revision": revision, "medias": []}
        snapshot_sha = evenement.get("snapshot_sha256")
        if not _horodatage_medias_valide(evenement.get("horodatage")) or not _sha256_valide(snapshot_sha):
            return {"valide": False, "statut": "DOSSIER_INCOHERENT", "revision": revision, "medias": []}
        if type_maillon == "media_reprise":
            if snapshot_epoch == snapshot_sha:
                return {"valide": False, "statut": "DOSSIER_INCOHERENT", "revision": revision, "medias": []}
            snapshot_epoch = snapshot_sha
            preparations_courantes = {}
        elif snapshot_epoch is None:
            snapshot_epoch = snapshot_sha
        elif snapshot_epoch != snapshot_sha:
            return {"valide": False, "statut": "DOSSIER_INCOHERENT", "revision": revision, "medias": []}
        if remis:
            return {"valide": False, "statut": "DOSSIER_FIGE", "revision": revision, "medias": []}
        if type_maillon == "media_prepare":
            if (
                not _reference_medias_valide(evenement.get("source_ref"))
                or not _reference_medias_valide(evenement.get("prepared_ref"))
                or not _sha256_valide(evenement.get("source_sha256"))
                or not _sha256_valide(evenement.get("prepared_sha256"))
                or not isinstance(evenement.get("prepared_mime"), str)
                or evenement["prepared_mime"] not in {"image/jpeg", "image/png"}
                or type(evenement.get("prepared_taille")) is not int
                or not 1 <= evenement["prepared_taille"] <= 10 * 1024 * 1024
                or not isinstance(evenement.get("attestation_humaine"), str)
                or not 20 <= len(evenement["attestation_humaine"]) <= 500
                or not _personne_media_valide(evenement.get("prepare_par"))
            ):
                return {"valide": False, "statut": "DOSSIER_INCOHERENT", "revision": revision, "medias": []}
            preparations_courantes[evenement["source_ref"]] = evenement["prepared_ref"]
            preparation_apres_revue = True
        elif type_maillon == "media_revue":
            if (
                not isinstance(evenement.get("decision"), str)
                or evenement["decision"] not in {"approuver", "rejeter"}
                or not isinstance(evenement.get("attestation_humaine"), str)
                or not 20 <= len(evenement["attestation_humaine"]) <= 500
                or not _personne_media_valide(evenement.get("par"))
                or evenement.get("role") != "nathan_owner"
                or evenement.get("source") != "approbation"
            ):
                return {"valide": False, "statut": "DOSSIER_INCOHERENT", "revision": revision, "medias": []}
        elif type_maillon == "media_remise":
            refs = evenement.get("prepared_refs")
            if (
                decision_revue != "approuver" or preparation_apres_revue or remis
                or not isinstance(refs, list) or not refs or not all(_reference_medias_valide(r) for r in refs)
                or len(set(refs)) != len(refs)
                or not _texte_court(evenement.get("media_export_id"), 200)
                or not _texte_court(evenement.get("export_id"), 200)
                or not _texte_court(evenement.get("creneau_id"), 200)
                or not _personne_media_valide(evenement.get("remis_par"))
                or not _sha256_valide(evenement.get("empreinte_texte"))
                or not isinstance(evenement.get("wct_id"), str)
                or refs != sorted(set(preparations_courantes.values()))
            ):
                return {"valide": False, "statut": "DOSSIER_INCOHERENT", "revision": revision, "medias": []}
            remis = True
        else:
            if remis or not _personne_media_valide(evenement.get("prepare_par")):
                return {"valide": False, "statut": "DOSSIER_FIGE", "revision": revision, "medias": []}
            decision_revue = None
            preparation_apres_revue = False
        if type_maillon in {"media_reprise", "media_revue", "media_remise"}:
            try:
                empreinte_prefixe = _empreinte_dossier(dossier)
            except (TypeError, ValueError, UnicodeError, RecursionError):
                return {"valide": False, "statut": "DOSSIER_INCOHERENT", "revision": revision, "medias": []}
            if (
                type(evenement.get("revision_cible")) is not int
                or evenement.get("revision_cible") != revision
                or not _sha256_valide(evenement.get("empreinte_cible"))
                or evenement.get("empreinte_cible") != empreinte_prefixe
            ):
                return {"valide": False, "statut": "REVUE_PERIMEE", "revision": revision, "medias": []}
        if type_maillon == "media_revue":
            decision_revue = evenement["decision"]
            preparation_apres_revue = False
        revision += 1
        dossier.append(evenement)
    medias: dict[str, Mapping[str, Any]] = {}
    revue = None
    preparation_apres_revue = False
    remises: list[Mapping[str, Any]] = []
    actifs: list[Mapping[str, Any]] = []
    for evenement in dossier:
        if evenement["type_maillon"] == "media_reprise":
            actifs = [evenement]
            medias = {}
            revue = None
            preparation_apres_revue = False
            continue
        actifs.append(evenement)
        if evenement["type_maillon"] == "media_prepare":
            medias[evenement["source_ref"]] = evenement
            preparation_apres_revue = True
        elif evenement["type_maillon"] == "media_revue":
            revue = evenement
            preparation_apres_revue = False
        else:
            remises.append(evenement)
    try:
        empreinte = _empreinte_dossier(dossier)
    except (TypeError, ValueError, UnicodeError, RecursionError):
        return {"valide": False, "statut": "DOSSIER_INCOHERENT", "revision": revision, "medias": []}
    statut = "EN_ATTENTE_REVUE"
    if revue is not None and not preparation_apres_revue:
        statut = "APPROUVE" if revue.get("decision") == "approuver" else "REJETE"
    if any(e["type_maillon"] == "media_remise" for e in dossier):
        statut = "REMIS"
    return {
        "valide": True,
        "statut": statut,
        "revision": revision,
        "empreinte_dossier": empreinte,
        "medias": [dict(m) for m in medias.values()],
        "evenements": [dict(e) for e in actifs],
        "remises": [dict(e) for e in remises],
    }


def _sha256_valide(valeur: Any) -> bool:
    return isinstance(valeur, str) and len(valeur) == 64 and all(c in "0123456789abcdef" for c in valeur)


def _texte_court(valeur: Any, maximum: int) -> bool:
    return isinstance(valeur, str) and 1 <= len(valeur) <= maximum and bool(valeur.strip())


def _personne_media_valide(valeur: Any) -> bool:
    return isinstance(valeur, str) and re.fullmatch(r"[a-z][a-z0-9_.-]{1,63}", valeur) is not None


def _horodatage_medias_valide(valeur: Any) -> bool:
    if not isinstance(valeur, str) or len(valeur) > 80:
        return False
    try:
        instant = datetime.fromisoformat(valeur.replace("Z", "+00:00"))
    except ValueError:
        return False
    return instant.tzinfo is not None and instant.utcoffset() is not None


def _reference_medias_valide(valeur: Any) -> bool:
    prefixe = "fichier:sha256:"
    return isinstance(valeur, str) and valeur.startswith(prefixe) and _sha256_valide(valeur[len(prefixe):])


def _empreinte_dossier(dossier: list[Mapping[str, Any]]) -> str:
    canonique = json.dumps(dossier, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(canonique.encode("utf-8")).hexdigest()
