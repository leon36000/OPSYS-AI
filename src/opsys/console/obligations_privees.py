"""Déclarations humaines paie/DAS chiffrées; aucune paie officielle ni écriture de paiement."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Callable, Mapping
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Connection

from opsys import cles_chiffrement, stockage
from opsys.stockage.maillons import EcritureConcurrente

DEPARTEMENT = "m05-financecore"
REGISTRE = "obligations_paies_das_privees"
PORTEE_CLE = "m05/obligations-paies-das"
MAX_ENTREES = 4096
CHAMPS = frozenset({
    "type", "montant_cad", "periode_debut", "periode_fin", "date_paie", "echeance",
    "reference_piece", "autorite", "source_consultee_le", "applicable_du", "applicable_au", "version",
})
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_MONTANT = re.compile(r"^(?:0|[1-9][0-9]{0,8})\.[0-9]{2}$")
_HEX_64 = re.compile(r"^[a-f0-9]{64}$")
_ID = re.compile(r"^[a-f0-9]{32}$")


class RefusObligation(ValueError):
    """Entrée invalide, conflit de révision ou impossibilité de vérifier la déclaration."""


def _json(objet: Any) -> bytes:
    return json.dumps(objet, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _date(valeur: Any, nom: str) -> str:
    if not isinstance(valeur, str) or not _DATE.fullmatch(valeur):
        raise RefusObligation(f"{nom} invalide")
    try:
        if date.fromisoformat(valeur).isoformat() != valeur:
            raise ValueError
    except ValueError as exc:
        raise RefusObligation(f"{nom} invalide") from exc
    return valeur


def normaliser(payload: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(payload, Mapping) or set(payload) != CHAMPS:
        raise RefusObligation("champs obligatoires ou inattendus")
    resultat = dict(payload)
    if not isinstance(resultat["type"], str) or resultat["type"] not in {"paies", "das"}:
        raise RefusObligation("type invalide")
    if not isinstance(resultat["montant_cad"], str) or not _MONTANT.fullmatch(resultat["montant_cad"]):
        raise RefusObligation("montant déclaré invalide")
    for champ in (
        "periode_debut", "periode_fin", "date_paie", "echeance",
        "source_consultee_le", "applicable_du", "applicable_au",
    ):
        resultat[champ] = _date(resultat[champ], champ)
    if resultat["periode_fin"] < resultat["periode_debut"]:
        raise RefusObligation("période de travail inversée")
    if resultat["date_paie"] < resultat["periode_fin"] or resultat["echeance"] < resultat["date_paie"]:
        raise RefusObligation("date de paie ou échéance antérieure à sa période déclarée")
    if resultat["applicable_au"] < resultat["applicable_du"]:
        raise RefusObligation("fenêtre d’applicabilité inversée")
    if not (resultat["applicable_du"] <= resultat["date_paie"] <= resultat["applicable_au"]):
        raise RefusObligation("date de paie hors fenêtre d’applicabilité déclarée")
    if resultat["source_consultee_le"] > date.today().isoformat():
        raise RefusObligation("date de consultation future")
    for champ, maximum in (("reference_piece", 240), ("autorite", 120), ("version", 80)):
        valeur = resultat[champ]
        if not isinstance(valeur, str) or not valeur.strip() or len(valeur) > maximum:
            raise RefusObligation(f"{champ} invalide")
        resultat[champ] = valeur.strip()
    return resultat


def _aead():
    try:
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    except ImportError as exc:
        raise RefusObligation("chiffrement indisponible; écriture refusée") from exc
    return AESGCM


def _enveloppes() -> list[dict[str, Any]]:
    regist = stockage.maillons(DEPARTEMENT, REGISTRE)
    if len(regist) > MAX_ENTREES:
        raise RefusObligation("registre trop volumineux; revue requise")
    resultat = list(regist)
    if len(resultat) > MAX_ENTREES:
        raise RefusObligation("registre trop volumineux; revue requise")
    return resultat


_MODES_RAPPROCHEMENT = {"LEGACY_IDENTIQUE", "PROVISION_CREDIT", "PROVISION_HORS_PAIE", "NOUVELLE_COMPOSANTE"}


def _forme_rapprochement(payload: Mapping[str, Any]) -> None:
    """Contrôles intrinsèques rejouables sans le catalogue financier courant."""
    if payload["schema_evenement"] != 3 or payload["action"] != "RAPPROCHER":
        raise RefusObligation("événement de rapprochement invalide")
    if not isinstance(payload["mode"], str) or payload["mode"] not in _MODES_RAPPROCHEMENT:
        raise RefusObligation("mode de rapprochement invalide")
    for cle in ("finance_snapshot_id", "obligations_sha256", "source_sha256"):
        if not isinstance(payload[cle], str) or not _HEX_64.fullmatch(payload[cle]):
            raise RefusObligation("empreinte d'événement invalide")
    oid = payload["obligation_id"]
    if payload["mode"] == "PROVISION_HORS_PAIE":
        if oid is not None:
            raise RefusObligation("cible inattendue pour une provision hors paie")
    elif not isinstance(oid, str) or not _ID.fullmatch(oid):
        raise RefusObligation("référence d'obligation invalide")
    if not isinstance(payload["source_kind"], str) or not isinstance(payload["source_ref"], str):
        raise RefusObligation("source de rapprochement invalide")
    if not isinstance(payload["montant_cad"], str) or not _MONTANT.fullmatch(payload["montant_cad"]):
        raise RefusObligation("montant rapproché invalide")
    modes_source = {
        "LEGACY_IDENTIQUE": ("legacy", True), "PROVISION_CREDIT": ("provision", True),
        "PROVISION_HORS_PAIE": ("provision", True), "NOUVELLE_COMPOSANTE": ("none", False),
    }
    kind, needs_ref = modes_source[payload["mode"]]
    if payload["source_kind"] != kind or (needs_ref and not payload["source_ref"]) \
            or (not needs_ref and payload["source_ref"]):
        raise RefusObligation("source incompatible avec le mode")
    if payload["mode"] == "LEGACY_IDENTIQUE" and payload["source_ref"] not in {"paies", "das"}:
        raise RefusObligation("catégorie legacy inconnue")
    if payload["mode"] in {"PROVISION_CREDIT", "PROVISION_HORS_PAIE"} \
            and not _HEX_64.fullmatch(payload["source_ref"]):
        raise RefusObligation("identifiant provision invalide")
    if payload["mode"] in {"PROVISION_CREDIT", "PROVISION_HORS_PAIE"} and payload["montant_cad"] == "0.00":
        raise RefusObligation("montant provision nul")
    if payload["mode"] == "NOUVELLE_COMPOSANTE" and payload["source_sha256"] != "0" * 64:
        raise RefusObligation("empreinte inattendue pour une nouvelle composante")


def _snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Valide un snapshot exact fourni par le caller depuis la transaction courante."""
    if not isinstance(snapshot, Mapping) or set(snapshot) != {"finance_snapshot_id", "obligations_sha256", "sources"}:
        raise RefusObligation("snapshot financier invalide")
    finance_id = snapshot["finance_snapshot_id"]
    obligations_hash = snapshot["obligations_sha256"]
    sources = snapshot["sources"]
    if not isinstance(finance_id, str) or not _HEX_64.fullmatch(finance_id):
        raise RefusObligation("empreinte du snapshot financier invalide")
    if not isinstance(obligations_hash, str) or not _HEX_64.fullmatch(obligations_hash):
        raise RefusObligation("empreinte des obligations invalide")
    if not isinstance(sources, Mapping) or set(sources) != {"legacy", "provisions"}:
        raise RefusObligation("sources du snapshot invalides")
    legacy, provisions = sources["legacy"], sources["provisions"]
    if not isinstance(legacy, Mapping) or set(legacy) - {"paies", "das"} or not isinstance(provisions, Mapping):
        raise RefusObligation("catalogue financier invalide")
    def source(valeur: Any) -> dict[str, str]:
        if not isinstance(valeur, Mapping) or set(valeur) != {"sha256", "montant_cad"}:
            raise RefusObligation("référence financière invalide")
        if not isinstance(valeur["sha256"], str) or not _HEX_64.fullmatch(valeur["sha256"]):
            raise RefusObligation("empreinte de source invalide")
        montant = valeur["montant_cad"]
        if not isinstance(montant, str) or not _MONTANT.fullmatch(montant):
            raise RefusObligation("montant source invalide")
        return {"sha256": valeur["sha256"], "montant_cad": montant}
    legacy_ok = {cle: source(valeur) for cle, valeur in legacy.items()}
    provisions_ok = {}
    for ref, valeur in provisions.items():
        if not isinstance(ref, str) or not _HEX_64.fullmatch(ref):
            raise RefusObligation("identifiant provision invalide")
        provisions_ok[ref] = source(valeur)
    return {"finance_snapshot_id": finance_id, "obligations_sha256": obligations_hash,
            "sources": {"legacy": legacy_ok, "provisions": provisions_ok}}


def _empreinte_obligations(etat: Mapping[str, Any]) -> str:
    actives = sorted(
        ({"id": x["id"], "obligation": x["obligation"]} for x in etat["actives"]),
        key=lambda x: x["id"],
    )
    return hashlib.sha256(_json(actives)).hexdigest()


def _valider_rapprochement(
    payload: Mapping[str, Any], etat: Mapping[str, Any], snapshot: Mapping[str, Any],
) -> dict[str, Any]:
    champs = {"schema_evenement", "action", "obligation_id", "finance_snapshot_id", "obligations_sha256",
              "mode", "source_kind", "source_ref", "source_sha256", "montant_cad"}
    if not isinstance(payload, Mapping) or set(payload) != champs:
        raise RefusObligation("événement de rapprochement invalide")
    _forme_rapprochement(payload)
    mode = payload["mode"]
    if not isinstance(mode, str) or mode not in _MODES_RAPPROCHEMENT:
        raise RefusObligation("mode de rapprochement invalide")
    if payload["finance_snapshot_id"] != snapshot["finance_snapshot_id"]:
        raise RefusObligation("snapshot financier modifié")
    if payload["obligations_sha256"] != _empreinte_obligations(etat) \
            or payload["obligations_sha256"] != snapshot["obligations_sha256"]:
        raise RefusObligation("snapshot des obligations modifié")
    amount = payload["montant_cad"]
    if not isinstance(amount, str) or not _MONTANT.fullmatch(amount):
        raise RefusObligation("montant rapproché invalide")
    if mode in {"PROVISION_CREDIT", "PROVISION_HORS_PAIE"} and amount == "0.00":
        raise RefusObligation("montant rapproché nul")
    source_kind, source_ref, source_hash = payload["source_kind"], payload["source_ref"], payload["source_sha256"]
    if not isinstance(source_kind, str) or not isinstance(source_ref, str):
        raise RefusObligation("référence de source invalide")
    if not isinstance(source_hash, str) or not _HEX_64.fullmatch(source_hash):
        raise RefusObligation("empreinte rapprochée invalide")
    obligation_id = payload["obligation_id"]
    obligation = next((x for x in etat["actives"] if x["id"] == obligation_id), None) if obligation_id else None
    if mode == "PROVISION_HORS_PAIE":
        if (
            obligation_id is not None or source_kind != "provision"
            or source_ref not in snapshot["sources"]["provisions"]
        ):
            raise RefusObligation("classification de provision invalide")
        source = snapshot["sources"]["provisions"][source_ref]
        if source_hash != source["sha256"] or amount != source["montant_cad"]:
            raise RefusObligation("source de provision modifiée")
    else:
        if obligation is None:
            raise RefusObligation("obligation active absente")
        montant_obligation = obligation["obligation"]["montant_cad"]
        if mode == "LEGACY_IDENTIQUE":
            if source_kind != "legacy" or source_ref != obligation["obligation"]["type"]:
                raise RefusObligation("source legacy incompatible")
            source = snapshot["sources"]["legacy"].get(source_ref)
            if source is None or source_hash != source["sha256"] or amount != source["montant_cad"] \
                    or amount != montant_obligation:
                raise RefusObligation("déclaration legacy non identique")
        elif mode == "PROVISION_CREDIT":
            if source_kind != "provision" or source_ref not in snapshot["sources"]["provisions"]:
                raise RefusObligation("provision absente")
            source = snapshot["sources"]["provisions"][source_ref]
            if source_hash != source["sha256"] or Decimal(amount) > Decimal(montant_obligation) \
                    or Decimal(amount) > Decimal(source["montant_cad"]):
                raise RefusObligation("crédit de provision supérieur au montant prouvé")
        elif mode == "NOUVELLE_COMPOSANTE":
            if source_kind != "none" or source_ref != "" or source_hash != "0" * 64 \
                    or obligation["obligation"]["type"] in snapshot["sources"]["legacy"] \
                    or amount != montant_obligation:
                raise RefusObligation("nouvelle composante ambiguë ou non identique")
    return dict(payload)


def _validate_projection_rapprochements(etat: dict[str, Any], snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Ne rend utilisables que les mappings les plus récents et toujours liés au snapshot courant."""
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    provisions_hors: dict[str, dict[str, Any]] = {}
    active = {x["id"]: x for x in etat["actives"]}
    for evt in etat["rapprochements"]:
        if evt["mode"] == "PROVISION_HORS_PAIE":
            provisions_hors[evt["source_ref"]] = evt
        elif evt["obligation_id"] in active:
            # Les liens d'une obligation remplacée/réglée restent dans l'historique chiffré,
            # mais ne sont ni reportés ni un motif permanent d'inconnu.
            classe = "credit" if evt["mode"] == "PROVISION_CREDIT" else "base"
            latest[(evt["obligation_id"], classe)] = evt
    reasons: list[str] = []
    for rang, gauche in enumerate(etat["actives"]):
        for droite in etat["actives"][rang + 1:]:
            a, b = gauche["obligation"], droite["obligation"]
            if a["type"] == b["type"] and max(a["periode_debut"], b["periode_debut"]) <= min(
                a["periode_fin"], b["periode_fin"]
            ):
                reasons.append("périodes actives chevauchantes; montant inutilisable")
    credits: dict[str, Decimal] = {}
    credits_obligations: dict[str, Decimal] = {}
    utilisees: set[tuple[str, str]] = set()
    lignes: list[dict[str, Any]] = []
    current_obligations = _empreinte_obligations(etat)
    for (oid, _classe), evt in latest.items():
        obligation = active.get(oid)
        if obligation is None:
            continue
        if (
            evt["finance_snapshot_id"] != snapshot["finance_snapshot_id"]
            or evt["obligations_sha256"] != current_obligations
        ):
            reasons.append("snapshot financier ou obligations modifiés")
            continue
        mode, ref = evt["mode"], evt["source_ref"]
        if mode == "LEGACY_IDENTIQUE":
            source = snapshot["sources"]["legacy"].get(ref)
            if source is None or source["sha256"] != evt["source_sha256"] \
                    or source["montant_cad"] != evt["montant_cad"]:
                reasons.append("déclaration legacy modifiée ou absente")
                continue
            cle_source = ("legacy", ref)
        elif mode == "PROVISION_CREDIT":
            source = snapshot["sources"]["provisions"].get(ref)
            if source is None or source["sha256"] != evt["source_sha256"] \
                    or Decimal(evt["montant_cad"]) > Decimal(source["montant_cad"]) \
                    or Decimal(evt["montant_cad"]) > Decimal(obligation["obligation"]["montant_cad"]):
                reasons.append("provision modifiée ou crédit hors limite")
                continue
            cle_source = ("provision", ref)
            credits[ref] = credits.get(ref, Decimal("0.00")) + Decimal(evt["montant_cad"])
            credits_obligations[oid] = credits_obligations.get(oid, Decimal("0.00")) + Decimal(evt["montant_cad"])
            if credits[ref] > Decimal(source["montant_cad"]):
                reasons.append("crédit cumulé supérieur à la provision")
                continue
            if credits_obligations[oid] > Decimal(obligation["obligation"]["montant_cad"]):
                reasons.append("crédit cumulé supérieur à l'obligation")
                continue
        else:
            if obligation["obligation"]["type"] in snapshot["sources"]["legacy"]:
                reasons.append("nouvelle composante en conflit avec une déclaration legacy")
                continue
            cle_source = ("none", oid)
        if cle_source in utilisees:
            reasons.append("source déjà affectée à une autre obligation ou catégorie")
            continue
        utilisees.add(cle_source)
        lignes.append({"obligation_id": oid, "mode": mode, "montant_cad": evt["montant_cad"],
                       "source_kind": evt["source_kind"], "source_ref": ref})
    for source_ref, source in snapshot["sources"]["provisions"].items():
        evt = provisions_hors.get(source_ref)
        if evt is None or evt["finance_snapshot_id"] != snapshot["finance_snapshot_id"] \
                or evt["source_sha256"] != source["sha256"] or evt["montant_cad"] != source["montant_cad"]:
            if source_ref not in credits:
                reasons.append("provision non classée ou périmée")
        elif ("provision", source_ref) in utilisees:
            reasons.append("provision déjà affectée au payroll et classée hors paie")
    for legacy_ref in snapshot["sources"]["legacy"]:
        if not any(x["mode"] == "LEGACY_IDENTIQUE" and x["source_ref"] == legacy_ref for x in lignes):
            reasons.append("déclaration legacy non rapprochée")
    for oid in active:
        if (oid, "base") not in latest:
            reasons.append("obligation privée non rapprochée")
    credits_texte = {ref: format(montant, ".2f") for ref, montant in credits.items()}
    lignes_utilisables = [] if reasons else [
        {"id": item["id"], "obligation": item["obligation"]} for item in etat["actives"]
    ]
    return {"statut": "CONNU" if not reasons else "INCONNU",
            "montant_utilisable": None if reasons else {
                "obligations": lignes_utilisables, "credits_provisions": credits_texte,
                "rapprochements": lignes,
            },
            "rapprochements": lignes if not reasons else [],
            "credits_provisions": credits_texte if not reasons else {},
            "raisons": sorted(set(reasons))}


def _verifier_lire_brut(cnx: Connection, enveloppes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evenements: list[dict[str, Any]] = []
    for rang, env in enumerate(enveloppes):
        champs_env = {
            "schema", "id", "rang", "precedent_sha256", "nonce", "ciphertext", "cipher_sha256", "mutation_mac",
            "acteur_mac", "revision_attendue",
        }
        if not isinstance(env, dict) or set(env) != champs_env:
            raise RefusObligation("enveloppe du registre invalide")
        if type(env["schema"]) is not int or env["schema"] != 1 or type(env["rang"]) is not int or env["rang"] != rang:
            raise RefusObligation("séquence du registre invalide")
        if not isinstance(env["id"], str) or not _ID.fullmatch(env["id"]):
            raise RefusObligation("identifiant du registre invalide")
        if not all(isinstance(env[k], str) and _HEX_64.fullmatch(env[k]) for k in (
            "precedent_sha256", "cipher_sha256", "mutation_mac", "acteur_mac",
        )):
            raise RefusObligation("empreinte du registre invalide")
        if type(env["revision_attendue"]) is not int or env["revision_attendue"] != rang:
            raise RefusObligation("révision d’origine invalide")
        precedent = hashlib.sha256(_json(enveloppes[rang - 1])).hexdigest() if rang else "0" * 64
        if env["precedent_sha256"] != precedent:
            raise RefusObligation("chaîne du registre invalide")
        try:
            nonce = bytes.fromhex(env["nonce"])
            cipher = bytes.fromhex(env["ciphertext"])
        except (TypeError, ValueError) as exc:
            raise RefusObligation("donnée chiffrée invalide") from exc
        if len(nonce) != 12 or len(cipher) < 16 or len(cipher) > 8192:
            raise RefusObligation("taille du ciphertext invalide")
        if hashlib.sha256(cipher).hexdigest() != env["cipher_sha256"]:
            raise RefusObligation("empreinte du ciphertext invalide")
        cle = cles_chiffrement.lire(cnx, PORTEE_CLE, env["id"])
        if cle is None:
            raise RefusObligation("clé absente; calendrier privé indisponible")
        aad = _json({
            "schema": 1, "id": env["id"], "rang": rang, "precedent_sha256": precedent,
            "mutation_mac": env["mutation_mac"], "acteur_mac": env["acteur_mac"],
        })
        try:
            ligne = json.loads(_aead()(cle).decrypt(nonce, cipher, aad).decode("utf-8"))
        except Exception as exc:
            raise RefusObligation("donnée chiffrée invalide") from exc
        if not isinstance(ligne, dict):
            raise RefusObligation("contenu privé invalide")
        acteur = ligne.get("confirme_par")
        if not isinstance(acteur, str) or not acteur:
            raise RefusObligation("identité privée invalide")
        if set(ligne) == CHAMPS | {"confirme_par", "confirme_le"}:
            # Format historique préservé; son empreinte continue d'être vérifiée sous l'ancien schéma.
            donnees = normaliser({champ: ligne[champ] for champ in CHAMPS})
            mac_payload = {"mutation_id": env["id"], "acteur": acteur, "revision_attendue": rang,
                           "payload": donnees}
            evenements.append({"action": "CREER", "id": env["id"], "obligation": donnees,
                               "confirme_par": acteur, "confirme_le": ligne["confirme_le"], "legacy": True})
        elif set(ligne) == {"schema_evenement", "action", "cible_id", "obligation", "reglee_le",
                            "confirme_par", "confirme_le"} and ligne["schema_evenement"] == 2:
            action = ligne["action"]
            cible_id = ligne["cible_id"]
            if (
                action not in {"REMPLACER", "REGLER"}
                or not isinstance(cible_id, str)
                or not _ID.fullmatch(cible_id)
            ):
                raise RefusObligation("événement privé invalide")
            donnees = normaliser(ligne["obligation"])
            if action == "REMPLACER" and ligne["reglee_le"] is not None:
                raise RefusObligation("date de règlement inattendue")
            if action == "REGLER":
                reglee = _date(ligne["reglee_le"], "reglee_le")
                if reglee < donnees["date_paie"] or reglee > date.today().isoformat():
                    raise RefusObligation("règlement déclaré hors des dates de la pièce")
            contenu_mac = {
                cle: ligne[cle]
                for cle in ("schema_evenement", "action", "cible_id", "obligation", "reglee_le")
            }
            mac_payload = {
                "mutation_id": env["id"],
                "acteur": acteur,
                "revision_attendue": rang,
                "payload": contenu_mac,
            }
            evenements.append({**ligne, "id": env["id"], "obligation": donnees, "legacy": False})
        elif set(ligne) == {"schema_evenement", "action", "obligation_id", "finance_snapshot_id",
                            "obligations_sha256", "mode", "source_kind", "source_ref", "source_sha256",
                            "montant_cad", "confirme_par", "confirme_le"} and ligne["schema_evenement"] == 3:
            contenu_mac = {cle: ligne[cle] for cle in (
                "schema_evenement", "action", "obligation_id", "finance_snapshot_id", "obligations_sha256",
                "mode", "source_kind", "source_ref", "source_sha256", "montant_cad",
            )}
            _forme_rapprochement(contenu_mac)
            mac_payload = {"mutation_id": env["id"], "acteur": acteur, "revision_attendue": rang,
                           "payload": contenu_mac}
            evenements.append({**ligne, "id": env["id"], "legacy": False})
        else:
            raise RefusObligation("contenu privé invalide")
        confirme_le = ligne.get("confirme_le")
        if not isinstance(confirme_le, str) or len(confirme_le) > 40:
            raise RefusObligation("horodatage privé invalide")
        try:
            horodatage = datetime.fromisoformat(confirme_le)
            if horodatage.utcoffset() is None:
                raise ValueError
        except ValueError as exc:
            raise RefusObligation("horodatage privé invalide") from exc
        mac = hmac.new(cle, _json(mac_payload), hashlib.sha256).hexdigest()
        acteur_mac = hmac.new(cle, acteur.encode("utf-8"), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(env["mutation_mac"], mac) or not hmac.compare_digest(env["acteur_mac"], acteur_mac):
            raise RefusObligation("authentification de l’enveloppe invalide")
    return evenements


def _verifier_lire(cnx: Connection, enveloppes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evenements = _verifier_lire_brut(cnx, enveloppes)
    _projeter(evenements)  # valide également l'intégrité sémantique avant lecture, rejeu ou append.
    return evenements


def _projeter(evenements: list[dict[str, Any]]) -> dict[str, Any]:
    par_id: dict[str, dict[str, Any]] = {}
    ids_evenements: set[str] = set()
    rapprochements: list[dict[str, Any]] = []
    for evt in evenements:
        action, eid = evt["action"], evt["id"]
        if eid in ids_evenements:
            raise RefusObligation("identifiant d'événement dupliqué")
        ids_evenements.add(eid)
        if action == "CREER":
            par_id[eid] = {"id": eid, "obligation": evt["obligation"], "statut": "ACTIVE",
                           "confirme_par": evt["confirme_par"], "confirme_le": evt["confirme_le"]}
            continue
        if action == "RAPPROCHER":
            cible = evt["obligation_id"]
            if evt["mode"] != "PROVISION_HORS_PAIE":
                precedent = par_id.get(cible)
                if precedent is None or precedent["statut"] != "ACTIVE":
                    raise RefusObligation("rapprochement vers obligation absente ou terminale")
                if evt["mode"] == "LEGACY_IDENTIQUE" and evt["source_ref"] != precedent["obligation"]["type"]:
                    raise RefusObligation("rapprochement legacy de catégorie incompatible")
            rapprochements.append(evt)
            continue
        cible = evt["cible_id"]
        precedent = par_id.get(cible)
        if precedent is None or precedent["statut"] != "ACTIVE":
            raise RefusObligation("référence absente ou déjà terminale")
        avant, apres = precedent["obligation"], evt["obligation"]
        cle_avant = (avant["type"], avant["periode_debut"], avant["periode_fin"])
        cle_apres = (apres["type"], apres["periode_debut"], apres["periode_fin"])
        if cle_avant != cle_apres:
            raise RefusObligation("catégorie ou période incompatible avec la référence")
        if action == "REGLER" and apres != avant:
            raise RefusObligation("un règlement déclaré ne peut modifier la pièce référencée")
        if action == "REMPLACER":
            precedent["statut"] = "REMPLACEE"
            precedent["remplace_par_id"] = eid
            par_id[eid] = {"id": eid, "obligation": apres, "statut": "ACTIVE",
                           "remplace_id": cible, "confirme_par": evt["confirme_par"], "confirme_le": evt["confirme_le"]}
        elif action == "REGLER":
            precedent["statut"] = "REGLEMENT_DECLARE_NON_RAPPROCHE"
            precedent["reglee_le"] = evt["reglee_le"]
            precedent["cible_id"] = cible
            precedent["reglement_declare_par"] = evt["confirme_par"]
    active = [ligne for ligne in par_id.values() if ligne["statut"] == "ACTIVE"]
    clefs = [
        (x["obligation"]["type"], x["obligation"]["periode_debut"], x["obligation"]["periode_fin"])
        for x in active
    ]
    ambigus = len(clefs) != len(set(clefs))
    raisons = ["configuration historique non réconciliée", "provisions non catégorisées non rapprochées"]
    if ambigus:
        raisons.append("doublons actifs de catégorie/période; montants non additionnés")
    return {
        "historique": evenements,
        "obligations": list(par_id.values()),
        "actives": active,
        "revision": len(evenements),
        "snapshot_reserves": {"statut": "INCONNU", "montant_cad": None, "raisons": raisons},
        "rapprochements": rapprochements,
    }


def lire(cnx: Connection) -> dict[str, Any]:
    if stockage.connexion_courante() is not cnx:
        raise RefusObligation("transaction de stockage courante requise")
    enveloppes = _enveloppes()
    return _projeter(_verifier_lire(cnx, enveloppes))


def ajouter(
    cnx: Connection,
    payload: Mapping[str, Any],
    *,
    revision_attendue: int,
    mutation_id: str,
    confirme_par: str,
    confirme_le: str,
    verifier_acteur: Callable[[Connection, str], None],
) -> dict[str, Any]:
    if stockage.connexion_courante() is not cnx:
        raise RefusObligation("transaction de stockage courante requise")
    if type(revision_attendue) is not int or revision_attendue < 0:
        raise RefusObligation("révision invalide")
    if not isinstance(mutation_id, str) or not _ID.fullmatch(mutation_id):
        raise RefusObligation("identifiant de mutation invalide")
    donnees = normaliser(payload)
    if not isinstance(confirme_par, str) or not confirme_par or len(confirme_par) > 128:
        raise RefusObligation("identité humaine absente")
    verifier_acteur(cnx, confirme_par)
    if not isinstance(confirme_le, str) or len(confirme_le) > 40:
        raise RefusObligation("horodatage de confirmation invalide")
    try:
        horodatage = datetime.fromisoformat(confirme_le)
        if horodatage.utcoffset() is None:
            raise ValueError
    except ValueError as exc:
        raise RefusObligation("horodatage de confirmation invalide") from exc

    historique = _enveloppes()
    _verifier_lire(cnx, historique)  # validation intégrale avant rejeu OU append
    existant = next((env for env in historique if env["id"] == mutation_id), None)
    if existant is not None:
        cle = cles_chiffrement.lire(cnx, PORTEE_CLE, mutation_id)
        if cle is None:
            raise RefusObligation("clé absente; rejeu refusé")
        attendu = hmac.new(cle, _json({
            "mutation_id": mutation_id, "acteur": confirme_par, "revision_attendue": revision_attendue,
            "payload": donnees,
        }), hashlib.sha256).hexdigest()
        if hmac.compare_digest(existant["mutation_mac"], attendu):
            return {"id": mutation_id, "revision": existant["rang"] + 1, "statut": "REJOUEE"}
        raise RefusObligation("identifiant rejoué avec acteur, révision ou contenu différent")
    if len(historique) != revision_attendue:
        raise RefusObligation("snapshot périmé; rechargez le calendrier")
    if len(historique) >= MAX_ENTREES:
        raise RefusObligation("registre plein; revue requise")
    cle = cles_chiffrement.obtenir_ou_creer(cnx, PORTEE_CLE, mutation_id, horodatage.isoformat())
    mac = hmac.new(cle, _json({
        "mutation_id": mutation_id, "acteur": confirme_par, "revision_attendue": revision_attendue,
        "payload": donnees,
    }), hashlib.sha256).hexdigest()
    acteur_mac = hmac.new(cle, confirme_par.encode("utf-8"), hashlib.sha256).hexdigest()
    precedent = hashlib.sha256(_json(historique[-1])).hexdigest() if historique else "0" * 64
    aad = _json({
        "schema": 1, "id": mutation_id, "rang": revision_attendue, "precedent_sha256": precedent,
        "mutation_mac": mac, "acteur_mac": acteur_mac,
    })
    nonce = secrets.token_bytes(12)
    ligne = {**donnees, "confirme_par": confirme_par, "confirme_le": confirme_le}
    cipher = _aead()(cle).encrypt(nonce, _json(ligne), aad)
    env = {
        "schema": 1, "id": mutation_id, "rang": revision_attendue, "precedent_sha256": precedent,
        "revision_attendue": revision_attendue, "nonce": nonce.hex(), "ciphertext": cipher.hex(),
        "cipher_sha256": hashlib.sha256(cipher).hexdigest(), "mutation_mac": mac, "acteur_mac": acteur_mac,
    }
    verifier_acteur(cnx, confirme_par)
    try:
        stockage.maillons(DEPARTEMENT, REGISTRE).append(env, rang_attendu=revision_attendue)
    except EcritureConcurrente as exc:
        raise RefusObligation("snapshot périmé; rechargez le calendrier") from exc
    return {"id": mutation_id, "revision": revision_attendue + 1, "statut": "CONFIRMEE"}


def rapprocher(
    cnx: Connection, payload: Mapping[str, Any], *,
    snapshot: Callable[[str], Mapping[str, Any]],
    revision_attendue: int, snapshot_id_attendu: str, mutation_id: str, confirme_par: str,
    confirme_le: str, verifier_acteur: Callable[[Connection, str], None],
) -> dict[str, Any]:
    """Append chiffré si CAS du journal et fingerprint affiché par l'interface sont encore exacts."""
    if stockage.connexion_courante() is not cnx:
        raise RefusObligation("transaction de stockage courante requise")
    if not callable(snapshot):
        raise RefusObligation("constructeur de snapshot financier requis")
    if type(revision_attendue) is not int or revision_attendue < 0 or not isinstance(mutation_id, str) \
            or not _ID.fullmatch(mutation_id) or not isinstance(snapshot_id_attendu, str) \
            or not _HEX_64.fullmatch(snapshot_id_attendu):
        raise RefusObligation("révision, snapshot ou identifiant invalide")
    if not isinstance(confirme_par, str) or not confirme_par or len(confirme_par) > 128:
        raise RefusObligation("identité humaine absente")
    verifier_acteur(cnx, confirme_par)
    try:
        horodatage = datetime.fromisoformat(confirme_le)
        if not isinstance(confirme_le, str) or len(confirme_le) > 40 or horodatage.utcoffset() is None:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise RefusObligation("horodatage de confirmation invalide") from exc
    historique = _enveloppes()
    evenements = _verifier_lire(cnx, historique)
    etat = _projeter(evenements)
    # Les événements historiques peuvent porter le snapshot qui prévalait alors; seul l'événement neuf doit
    # correspondre à la projection active actuelle.
    obligations_hash = _empreinte_obligations(etat)
    snapshot_valide = _snapshot(snapshot(obligations_hash))
    if snapshot_valide["obligations_sha256"] != obligations_hash:
        raise RefusObligation("le constructeur a fourni un autre snapshot d'obligations")
    if snapshot_valide["finance_snapshot_id"] != snapshot_id_attendu:
        raise RefusObligation("snapshot financier périmé; rechargez le rapprochement")
    corps = dict(payload) if isinstance(payload, Mapping) else {}
    corps.update({"schema_evenement": 3, "action": "RAPPROCHER",
        "finance_snapshot_id": snapshot_valide["finance_snapshot_id"], "obligations_sha256": obligations_hash})
    donnees = _valider_rapprochement(corps, etat, snapshot_valide)
    contenu_mac = donnees
    existant = next((env for env in historique if env["id"] == mutation_id), None)
    if existant is not None:
        cle = cles_chiffrement.lire(cnx, PORTEE_CLE, mutation_id)
        attendu = hmac.new(cle, _json({"mutation_id": mutation_id, "acteur": confirme_par,
            "revision_attendue": revision_attendue, "payload": contenu_mac}), hashlib.sha256).hexdigest() if cle else ""
        if hmac.compare_digest(existant["mutation_mac"], attendu):
            return {"id": mutation_id, "revision": existant["rang"] + 1, "statut": "REJOUEE"}
        raise RefusObligation("identifiant rejoué avec acteur, révision ou contenu différent")
    if len(historique) != revision_attendue or len(historique) >= MAX_ENTREES:
        raise RefusObligation("snapshot périmé ou registre plein")
    # Valide exclusivité cumulative contre les mappings encore en vigueur avant l'append.
    etat["rapprochements"].append({**donnees, "id": mutation_id, "confirme_par": confirme_par,
                                     "confirme_le": confirme_le})
    projection = _validate_projection_rapprochements(etat, snapshot_valide)
    if any("déjà affectée" in x or "crédit cumulé supérieur" in x for x in projection["raisons"]):
        raise RefusObligation("source déjà affectée ou crédit supérieur")
    cle = cles_chiffrement.obtenir_ou_creer(cnx, PORTEE_CLE, mutation_id, horodatage.isoformat())
    mac = hmac.new(cle, _json({"mutation_id": mutation_id, "acteur": confirme_par,
        "revision_attendue": revision_attendue, "payload": contenu_mac}), hashlib.sha256).hexdigest()
    acteur_mac = hmac.new(cle, confirme_par.encode("utf-8"), hashlib.sha256).hexdigest()
    rang = len(historique)
    precedent = hashlib.sha256(_json(historique[-1])).hexdigest() if historique else "0" * 64
    aad = _json({"schema": 1, "id": mutation_id, "rang": rang, "precedent_sha256": precedent,
                 "mutation_mac": mac, "acteur_mac": acteur_mac})
    nonce = secrets.token_bytes(12)
    ligne = {**contenu_mac, "confirme_par": confirme_par, "confirme_le": confirme_le}
    cipher = _aead()(cle).encrypt(nonce, _json(ligne), aad)
    env = {"schema": 1, "id": mutation_id, "rang": rang, "precedent_sha256": precedent,
           "revision_attendue": rang, "nonce": nonce.hex(), "ciphertext": cipher.hex(),
           "cipher_sha256": hashlib.sha256(cipher).hexdigest(), "mutation_mac": mac, "acteur_mac": acteur_mac}
    verifier_acteur(cnx, confirme_par)
    try:
        stockage.maillons(DEPARTEMENT, REGISTRE).append(env, rang_attendu=rang)
    except EcritureConcurrente as exc:
        raise RefusObligation("snapshot périmé; rechargez le calendrier") from exc
    return {"id": mutation_id, "revision": rang + 1, "statut": "CONFIRMEE"}


def lire_rapprochements(
    cnx: Connection, snapshot: Callable[[str], Mapping[str, Any]],
) -> dict[str, Any]:
    """Déchiffre une fois, puis construit le snapshot complet depuis le digest actif calculé."""
    if stockage.connexion_courante() is not cnx:
        raise RefusObligation("transaction de stockage courante requise")
    if not callable(snapshot):
        raise RefusObligation("constructeur de snapshot financier requis")
    enveloppes = _enveloppes()
    etat = _projeter(_verifier_lire(cnx, enveloppes))
    obligations_hash = _empreinte_obligations(etat)
    snap = _snapshot(snapshot(obligations_hash))
    if snap["obligations_sha256"] != obligations_hash:
        raise RefusObligation("le constructeur a fourni un autre snapshot d'obligations")
    resultat = _validate_projection_rapprochements(etat, snap)
    resultat.update({
        "revision": len(enveloppes),
        "paie_das_head": hashlib.sha256(_json(enveloppes[-1])).hexdigest() if enveloppes else "0" * 64,
        "obligations_sha256": _empreinte_obligations(etat),
        "obligations_actives": [
            {"id": item["id"], "statut": item["statut"], "obligation": item["obligation"]}
            for item in etat["actives"]
        ],
    })
    return resultat


def transition(
    cnx: Connection, action: str, cible_id: str, payload: Mapping[str, Any], *,
    revision_attendue: int, mutation_id: str, confirme_par: str, confirme_le: str,
    reglee_le: str | None = None, verifier_acteur: Callable[[Connection, str], None],
) -> dict[str, Any]:
    """Ajoute un remplacement ou règlement déclaré; aucune écriture de paiement."""
    if stockage.connexion_courante() is not cnx:
        raise RefusObligation("transaction de stockage courante requise")
    if action not in {"REMPLACER", "REGLER"}:
        raise RefusObligation("transition invalide")
    id_valide = isinstance(mutation_id, str) and _ID.fullmatch(mutation_id)
    if type(revision_attendue) is not int or revision_attendue < 0 or not id_valide:
        raise RefusObligation("révision ou identifiant invalide")
    donnees = normaliser(payload)
    if not isinstance(cible_id, str) or not _ID.fullmatch(cible_id):
        raise RefusObligation("référence canonique invalide")
    if action == "REGLER":
        reglee_le = _date(reglee_le, "reglee_le")
        if reglee_le < donnees["date_paie"] or reglee_le > date.today().isoformat():
            raise RefusObligation("règlement déclaré hors des dates de la pièce")
    elif reglee_le is not None:
        raise RefusObligation("date de règlement inattendue")
    if not isinstance(confirme_par, str) or not confirme_par or len(confirme_par) > 128:
        raise RefusObligation("identité humaine absente")
    verifier_acteur(cnx, confirme_par)
    if not isinstance(confirme_le, str) or len(confirme_le) > 40:
        raise RefusObligation("horodatage de confirmation invalide")
    try:
        horodatage = datetime.fromisoformat(confirme_le)
        if horodatage.utcoffset() is None:
            raise ValueError
    except (TypeError, ValueError) as exc:
        raise RefusObligation("horodatage de confirmation invalide") from exc
    historique = _enveloppes()
    evenements = _verifier_lire(cnx, historique)
    etat = _projeter(evenements)
    # Un rejeu n'est admissible qu'après validation de la chaîne entière, mais peut viser une cible
    # déjà terminale précisément parce que son événement a été appliqué lors du premier appel.
    existant = next((env for env in historique if env["id"] == mutation_id), None)
    ligne_payload = {"schema_evenement": 2, "action": action, "cible_id": cible_id,
                     "obligation": donnees, "reglee_le": reglee_le}
    if existant is not None:
        cle = cles_chiffrement.lire(cnx, PORTEE_CLE, mutation_id)
        contenu_mac = {
            "mutation_id": mutation_id,
            "acteur": confirme_par,
            "revision_attendue": revision_attendue,
            "payload": ligne_payload,
        }
        mac_attendu = hmac.new(cle, _json(contenu_mac), hashlib.sha256).hexdigest() if cle else ""
        if hmac.compare_digest(existant["mutation_mac"], mac_attendu):
            return {"id": mutation_id, "revision": existant["rang"] + 1, "statut": "REJOUEE"}
        raise RefusObligation("identifiant rejoué avec acteur, révision ou contenu différent")
    target = next((x for x in etat["obligations"] if x["id"] == cible_id), None)
    if target is None or target["statut"] != "ACTIVE":
        raise RefusObligation("référence absente ou déjà terminale")
    avant = target["obligation"]
    cle_avant = (avant["type"], avant["periode_debut"], avant["periode_fin"])
    cle_nouvelle = (donnees["type"], donnees["periode_debut"], donnees["periode_fin"])
    if cle_avant != cle_nouvelle:
        raise RefusObligation("catégorie ou période incompatible avec la référence")
    if action == "REGLER" and donnees != avant:
        raise RefusObligation("un règlement déclaré ne peut modifier la pièce référencée")
    if len(historique) != revision_attendue or len(historique) >= MAX_ENTREES:
        raise RefusObligation("snapshot périmé ou registre plein")
    cle = cles_chiffrement.obtenir_ou_creer(cnx, PORTEE_CLE, mutation_id, horodatage.isoformat())
    mac = hmac.new(cle, _json({"mutation_id": mutation_id, "acteur": confirme_par,
        "revision_attendue": revision_attendue, "payload": ligne_payload}), hashlib.sha256).hexdigest()
    acteur_mac = hmac.new(cle, confirme_par.encode("utf-8"), hashlib.sha256).hexdigest()
    rang = len(historique)
    precedent = hashlib.sha256(_json(historique[-1])).hexdigest() if historique else "0" * 64
    aad = _json({"schema": 1, "id": mutation_id, "rang": rang, "precedent_sha256": precedent,
                 "mutation_mac": mac, "acteur_mac": acteur_mac})
    nonce = secrets.token_bytes(12)
    ligne = {**ligne_payload, "confirme_par": confirme_par, "confirme_le": confirme_le}
    cipher = _aead()(cle).encrypt(nonce, _json(ligne), aad)
    env = {"schema": 1, "id": mutation_id, "rang": rang, "precedent_sha256": precedent,
           "revision_attendue": rang, "nonce": nonce.hex(), "ciphertext": cipher.hex(),
           "cipher_sha256": hashlib.sha256(cipher).hexdigest(), "mutation_mac": mac, "acteur_mac": acteur_mac}
    verifier_acteur(cnx, confirme_par)
    try:
        stockage.maillons(DEPARTEMENT, REGISTRE).append(env, rang_attendu=rang)
    except EcritureConcurrente as exc:
        raise RefusObligation("snapshot périmé; rechargez le calendrier") from exc
    return {"id": mutation_id, "revision": rang + 1, "statut": "CONFIRMEE"}
