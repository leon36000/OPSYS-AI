"""Configuration durable du connecteur STT M1; seules des références sont conservées."""

from __future__ import annotations

import datetime as dt
import hashlib
import ipaddress
import json
import re
import secrets
from collections.abc import Mapping
from typing import Any

from sqlalchemy import Connection, delete, insert, select, update
from sqlalchemy.exc import IntegrityError

from . import etat, identite
from .stockage.schema import (
    CONNECTEURS_STT,
    CONNECTEURS_STT_COMMANDES,
    CONNECTEURS_STT_DIAGNOSTICS,
    CONNECTEURS_STT_HISTORIQUE,
)

_REF = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
_MUTATION = re.compile(r"^[A-Za-z0-9._:-]{8,128}$")
_CHAMPS = frozenset({"url", "modele", "cle", "local", "delai_s"})


def instant() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def _admin(cnx: Connection, acteur: str) -> None:
    personne = identite.personne_active(cnx, acteur)
    if personne is None:
        raise PermissionError("authentification requise")
    if not personne.roles.intersection({"nathan_owner", "admin"}):
        raise PermissionError("administration requise")


def references_valides(references: Any) -> dict[str, str]:
    if not isinstance(references, Mapping) or set(references) - _CHAMPS:
        raise ValueError("references doit contenir uniquement url, modele, cle, local et delai_s")
    if not {"url", "modele"}.issubset(references):
        raise ValueError("les références url et modele sont requises")
    if any(not isinstance(v, str) or not _REF.fullmatch(v) for v in references.values()):
        raise ValueError("chaque référence doit être un nom de variable valide")
    return dict(references)


def _json(objet: Any) -> str:
    return json.dumps(objet, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def lire(cnx: Connection) -> dict[str, Any] | None:
    ligne = cnx.execute(select(CONNECTEURS_STT).where(CONNECTEURS_STT.c.id == "stt-m1")).mappings().first()
    if ligne is None:
        return None
    observation = cnx.execute(select(CONNECTEURS_STT_DIAGNOSTICS.c.resultat).where(
        CONNECTEURS_STT_DIAGNOSTICS.c.statut == "termine",
        CONNECTEURS_STT_DIAGNOSTICS.c.resultat.is_not(None),
    ).order_by(CONNECTEURS_STT_DIAGNOSTICS.c.cree_le.desc()).limit(1)).scalar_one_or_none()
    return {
        "id": "stt-m1", "actif": ligne["actif"], "references": json.loads(ligne["references"]),
        "revision": ligne["revision"], "modifie_le": ligne["modifie_le"],
        "modifie_par": ligne["modifie_par"],
        "derniere_observation": json.loads(observation) if observation else None,
    }


def modifier(cnx: Connection, *, acteur: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    _admin(cnx, acteur)
    cles = {"actif", "references", "revision_attendue", "mutation_id"}
    if not isinstance(payload, Mapping) or set(payload) != cles:
        raise ValueError("configuration STT : champs absents ou inconnus")
    if type(payload["actif"]) is not bool:
        raise ValueError("actif doit être booléen")
    attendu = payload["revision_attendue"]
    if type(attendu) is not int or attendu < 0:
        raise ValueError("revision_attendue doit être un entier positif ou nul")
    mutation = payload["mutation_id"]
    if not isinstance(mutation, str) or not _MUTATION.fullmatch(mutation):
        raise ValueError("mutation_id invalide")
    refs = references_valides(payload["references"])
    hash_payload = hashlib.sha256(_json({"actif": payload["actif"], "references": refs,
                                         "revision_attendue": attendu}).encode()).hexdigest()
    replay = cnx.execute(select(CONNECTEURS_STT_COMMANDES).where(
        CONNECTEURS_STT_COMMANDES.c.mutation_id == mutation
    )).mappings().first()
    if replay:
        if replay["acteur"] != acteur:
            raise PermissionError("mutation déjà utilisée par une autre identité")
        if replay["empreinte"] != hash_payload:
            raise ValueError("mutation_id déjà utilisé avec un autre contenu")
        _admin(cnx, acteur)
        return json.loads(replay["reponse"])
    ligne = cnx.execute(select(CONNECTEURS_STT).where(
        CONNECTEURS_STT.c.id == "stt-m1"
    ).with_for_update()).mappings().first()
    courante = ligne["revision"] if ligne else 0
    if courante != attendu:
        raise ValueError(f"conflit de révision : attendue {attendu}, courante {courante}")
    rev = courante + 1
    date = instant()
    reponse = {"id": "stt-m1", "actif": payload["actif"], "references": refs, "revision": rev,
               "modifie_le": date, "modifie_par": acteur, "complet": False}
    valeurs = {"actif": payload["actif"], "references": _json(refs), "revision": rev,
               "modifie_le": date, "modifie_par": acteur, "mutation_id": mutation,
               "mutation_hash": hash_payload}
    if ligne:
        resultat = cnx.execute(update(CONNECTEURS_STT).where(
            CONNECTEURS_STT.c.id == "stt-m1", CONNECTEURS_STT.c.revision == attendu
        ).values(**valeurs))
        if resultat.rowcount != 1:
            raise ValueError("conflit de révision")
    else:
        try:
            cnx.execute(insert(CONNECTEURS_STT).values(id="stt-m1", **valeurs))
        except IntegrityError as exc:
            raise ValueError("conflit de révision pendant la création") from exc
    cnx.execute(insert(CONNECTEURS_STT_HISTORIQUE).values(revision=rev, instantane=_json(reponse)))
    cnx.execute(insert(CONNECTEURS_STT_COMMANDES).values(
        mutation_id=mutation, acteur=acteur, empreinte=hash_payload, reponse=_json(reponse)))
    etat.journaliser(cnx, acteur, "connecteur.stt.configuration", "stt-m1", {
        "revision": rev, "actif": payload["actif"], "references": sorted(refs),
        "mutation_id": mutation,
    })
    _admin(cnx, acteur)
    return reponse


def diagnostic_reserver(cnx: Connection, *, acteur: str, revision: int, mutation_id: str) -> dict[str, Any] | None:
    _admin(cnx, acteur)
    if (type(revision) is not int or revision <= 0 or not isinstance(mutation_id, str)
            or not _MUTATION.fullmatch(mutation_id)):
        raise ValueError("révision ou mutation_id de diagnostic invalide")
    cnx.execute(select(CONNECTEURS_STT).where(
        CONNECTEURS_STT.c.id == "stt-m1"
    ).with_for_update()).mappings().first()
    config = lire(cnx)
    replay = cnx.execute(select(CONNECTEURS_STT_DIAGNOSTICS).where(
        CONNECTEURS_STT_DIAGNOSTICS.c.mutation_id == mutation_id
    ).with_for_update()).mappings().first()
    now = instant()
    if replay:
        if replay["acteur"] != acteur:
            raise PermissionError("diagnostic déjà utilisé par une autre identité")
        if replay["revision"] != revision:
            raise ValueError("mutation_id de diagnostic réutilisé pour une autre révision")
    if replay and replay["statut"] != "en_cours":
        return json.loads(replay["resultat"])
    if replay and replay["expire_le"] > now:
        raise RuntimeError("un diagnostic identique est déjà en cours")
    if config is None or config["revision"] != revision or not config["actif"]:
        raise ValueError("configuration STT active ou révision courante requise")
    autre = cnx.execute(select(CONNECTEURS_STT_DIAGNOSTICS).where(
        CONNECTEURS_STT_DIAGNOSTICS.c.statut == "en_cours",
        CONNECTEURS_STT_DIAGNOSTICS.c.expire_le > now,
    ).with_for_update()).first()
    if autre:
        raise RuntimeError("un diagnostic STT est déjà en cours")
    jeton = secrets.token_hex(24)
    vals = {"revision": revision, "acteur": acteur, "jeton": jeton,
            "statut": "en_cours", "resultat": None,
            "expire_le": (dt.datetime.now(dt.UTC) + dt.timedelta(seconds=15)).isoformat(timespec="seconds"),
            "cree_le": now}
    if replay:
        cnx.execute(update(CONNECTEURS_STT_DIAGNOSTICS).where(
            CONNECTEURS_STT_DIAGNOSTICS.c.mutation_id == mutation_id).values(**vals))
    else:
        cnx.execute(insert(CONNECTEURS_STT_DIAGNOSTICS).values(mutation_id=mutation_id, **vals))
    _admin(cnx, acteur)
    return {"_jeton_reservation": jeton}


def diagnostic_terminer(cnx: Connection, *, acteur: str, revision: int, mutation_id: str, jeton: str,
                        statut: str) -> dict[str, Any]:
    _admin(cnx, acteur)
    if statut not in {
        "endpoint_rejoignable", "identifiants_absents", "identifiants_refuses",
        "diagnostic_indisponible", "references_incompletes", "configuration_invalide",
    }:
        raise ValueError("statut de diagnostic non pris en charge")
    cnx.execute(select(CONNECTEURS_STT).where(
        CONNECTEURS_STT.c.id == "stt-m1"
    ).with_for_update()).mappings().first()
    config = lire(cnx)
    if config is None or config["revision"] != revision or not config["actif"]:
        raise ValueError("configuration remplacée pendant le diagnostic")
    resultat = {"statut": statut, "revision": revision, "date": instant(), "stt_verifie": False}
    mise_a_jour = cnx.execute(update(CONNECTEURS_STT_DIAGNOSTICS).where(
        CONNECTEURS_STT_DIAGNOSTICS.c.mutation_id == mutation_id,
        CONNECTEURS_STT_DIAGNOSTICS.c.acteur == acteur,
        CONNECTEURS_STT_DIAGNOSTICS.c.jeton == jeton,
        CONNECTEURS_STT_DIAGNOSTICS.c.statut == "en_cours",
        CONNECTEURS_STT_DIAGNOSTICS.c.expire_le > instant(),
    ).values(statut="termine", resultat=_json(resultat), expire_le=instant()))
    if mise_a_jour.rowcount != 1:
        raise ValueError("réservation du diagnostic expirée ou remplacée")
    _admin(cnx, acteur)
    return resultat


def diagnostic_abandonner(cnx: Connection, mutation_id: str, jeton: str) -> None:
    cnx.execute(delete(CONNECTEURS_STT_DIAGNOSTICS).where(
        CONNECTEURS_STT_DIAGNOSTICS.c.mutation_id == mutation_id,
        CONNECTEURS_STT_DIAGNOSTICS.c.jeton == jeton,
        CONNECTEURS_STT_DIAGNOSTICS.c.statut == "en_cours",
    ))


def construire_configuration(references: Mapping[str, str], environ: Mapping[str, str]):
    from m1_front_office.voicemail_stt import (
        ENV_CLE,
        ENV_DELAI,
        ENV_LOCAL,
        ENV_MODELE,
        ENV_URL,
        ConfigurationSTT,
        ErreurVoicemail,
    )
    mapping = {"url": ENV_URL, "modele": ENV_MODELE, "cle": ENV_CLE,
               "local": ENV_LOCAL, "delai_s": ENV_DELAI}
    valeurs: dict[str, str] = {}
    manquantes = []
    for champ, variable in references.items():
        valeur = environ.get(variable, "")
        if valeur == "":
            if champ in {"url", "modele"}:
                manquantes.append(champ)
            continue
        valeurs[mapping[champ]] = valeur
    if manquantes:
        raise ErreurVoicemail("REJ-STT-REFERENCES", "référence(s) requise(s) non résolue(s): " + ", ".join(manquantes))
    return ConfigurationSTT.depuis_env(valeurs)


def verifier_adresse_diagnostic(configuration: Any) -> None:
    """Refuse les adresses IP non publiques d'un endpoint déclaré distant."""
    from urllib.parse import urlsplit

    hote = (urlsplit(configuration.base_url).hostname or "").rstrip(".").lower()
    if configuration.local:
        return
    if hote in {"localhost", "localhost.localdomain"} or hote.endswith(".localhost"):
        raise ValueError("endpoint local refusé pour une configuration distante")
    try:
        adresse = ipaddress.ip_address(hote)
    except ValueError:
        return
    if not adresse.is_global:
        raise ValueError("adresse IP privée ou spéciale refusée pour le diagnostic distant")
