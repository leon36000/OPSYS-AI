"""Routes JSON pour la mémoire de développement M10, protégées par la session de console."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from m10_memoire import developpement as memoire

from opsys import contexte, etat, identite

_LIMITE_CORPS = 64 * 1024
_VERSION_MAX = 2_147_483_647
_IDENTIFIANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:_-]{0,127}$")
_MODULE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_JsonParser = Callable[[Request], Awaitable[dict[str, Any]]]


def _horodatage_serveur() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _corps(corps: Any, champs: set[str], *, optionnels: set[str] = frozenset()) -> Mapping[str, Any]:
    if not isinstance(corps, dict) or not champs <= set(corps) or set(corps) - (champs | optionnels):
        raise HTTPException(400, "champs de commande invalides")
    return corps


async def _objet_json_borne(request: Request) -> dict[str, Any]:
    """Lit un objet JSON avec une limite appliquée avant le décodage."""
    annonce = request.headers.get("content-length", "")
    if annonce.isdigit() and int(annonce) > _LIMITE_CORPS:
        raise HTTPException(413, "requête trop volumineuse")
    morceaux: list[bytes] = []
    taille = 0
    async for morceau in request.stream():
        taille += len(morceau)
        if taille > _LIMITE_CORPS:
            raise HTTPException(413, "requête trop volumineuse")
        morceaux.append(morceau)
    try:
        valeur = json.loads(b"".join(morceaux))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise HTTPException(400, "corps JSON invalide") from exc
    if not isinstance(valeur, dict):
        raise HTTPException(400, "objet JSON attendu")
    return valeur


def _chaine(data: Mapping[str, Any], cle: str, *, maximum: int = 8_000) -> str:
    value = data[cle]
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise HTTPException(400, f"{cle} doit être une chaîne non vide bornée")
    return value


def _identifiant(data: Mapping[str, Any], cle: str) -> str:
    value = _chaine(data, cle, maximum=128)
    if not _IDENTIFIANT.fullmatch(value):
        raise HTTPException(400, f"{cle} invalide")
    return value


def _module(data: Mapping[str, Any]) -> str:
    value = _chaine(data, "module", maximum=64)
    if not _MODULE.fullmatch(value):
        raise HTTPException(400, "module invalide")
    return value


def _version(data: Mapping[str, Any], cle: str = "version") -> int:
    value = data[cle]
    if type(value) is not int or not 1 <= value <= _VERSION_MAX:
        raise HTTPException(400, f"{cle} doit être un entier positif borné")
    return value


def _liste_textes(value: Any, cle: str, *, maximum_items: int = 500) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) > maximum_items
        or any(not isinstance(item, str) or not item.strip() or len(item) > 8_000 for item in value)
    ):
        raise HTTPException(400, f"{cle} doit être une liste bornée de chaînes non vides")
    return value


def _liste_objets(value: Any, cle: str, *, maximum_items: int = 500) -> list[dict[str, Any]]:
    if (
        not isinstance(value, list)
        or len(value) > maximum_items
        or any(not isinstance(item, dict) or not all(isinstance(key, str) and key for key in item) for item in value)
    ):
        raise HTTPException(400, f"{cle} doit être une liste bornée d'objets")
    return value


def _statut(data: Mapping[str, Any], *, defaut: str, permis: frozenset[str]) -> str:
    value = data.get("status", defaut)
    if not isinstance(value, str) or value not in permis:
        raise HTTPException(400, "status invalide")
    return value


def _verifier_objet(value: Any) -> None:
    """Refuse les valeurs JSON hors contrat dans les éléments structurés, sans coercition."""
    if isinstance(value, dict):
        if not all(isinstance(key, str) and key for key in value):
            raise HTTPException(400, "clé d'objet invalide")
        for item in value.values():
            _verifier_objet(item)
    elif isinstance(value, list):
        for item in value:
            _verifier_objet(item)
    elif type(value) is float and not math.isfinite(value):
        raise HTTPException(400, "nombre JSON non fini interdit")
    elif value is not None and type(value) not in {str, int, float, bool}:
        raise HTTPException(400, "valeur JSON invalide")


def _repository() -> Path:
    configured = os.environ.get("OPSYS_REPO_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    try:
        root = subprocess.check_output(
            ["git", "-C", str(Path.cwd()), "rev-parse", "--show-toplevel"], text=True, stderr=subprocess.DEVNULL
        )
        return Path(root.strip()).resolve()
    except (OSError, subprocess.CalledProcessError):
        return Path.cwd().resolve()


def creer_router(
    *,
    session_api: Callable[[Request], Any],
    ecriture_api: Callable[[Request], Any],
    cnx_factory: Callable[[], Any] = etat.session,
    objet_json: _JsonParser | None = None,
) -> APIRouter:
    """Construit les routes; les callbacks de console appliquent cookie live, admin et CSRF.

    Aucun argument d'identité n'est accepté. La lecture SQL de l'acteur est fermée avant tout appel
    M10 afin qu'aucune transaction externe ne soit tenue pendant l'écriture du registre canonique.
    """
    router = APIRouter(prefix="/api/memoire-developpement", tags=["mémoire de développement"])

    async def lire_objet(request: Request) -> dict[str, Any]:
        valeur = await (objet_json(request) if objet_json is not None else _objet_json_borne(request))
        if not isinstance(valeur, dict):
            raise HTTPException(400, "objet JSON attendu")
        return valeur

    def principal(request: Request, *, ecriture: bool) -> contexte.IdentiteAppelante:
        session = ecriture_api(request) if ecriture else session_api(request)
        with cnx_factory() as cnx:
            personne = identite.personne_active(cnx, session.utilisateur)
        if personne is None:
            raise HTTPException(401, "authentification requise")
        role = next((role for role in ("nathan_owner", "admin") if role in personne.roles), None)
        if role is None:
            raise HTTPException(403, "accès mémoire développement refusé")
        return contexte.IdentiteAppelante(personne.identifiant, role)

    def appeler(
        request: Request,
        action: Callable[..., Any],
        *args: Any,
        ecriture: bool = False,
        appelant: contexte.IdentiteAppelante | None = None,
        **kwargs: Any,
    ) -> Any:
        appelant = appelant or principal(request, ecriture=ecriture)
        try:
            with contexte.appele_par_appareil(appelant):
                return action(*args, **kwargs)
        except memoire.AccesDeveloppementRefuse as exc:
            raise HTTPException(403, "accès mémoire développement refusé") from exc
        except memoire.ConflitIdempotence as exc:
            raise HTTPException(409, str(exc)) from exc
        except (memoire.SourceDeveloppementRefusee, ValueError, KeyError, TypeError) as exc:
            raise HTTPException(400, "commande mémoire développement invalide") from exc

    @router.get("/audit")
    def audit(request: Request) -> dict[str, Any]:
        # L'authentification live précède toute interprétation des paramètres de la requête.
        appelant = principal(request, ecriture=False)
        items = list(request.query_params.multi_items())
        if any(cle != "limite" for cle, _ in items) or len(items) > 1:
            raise HTTPException(400, "paramètres d'audit invalides")
        limite = 100
        if items:
            valeur = items[0][1]
            if not re.fullmatch(r"[0-9]{1,3}", valeur):
                raise HTTPException(400, "limite d'audit invalide")
            limite = int(valeur)
        if not 1 <= limite <= 500:
            raise HTTPException(400, "limite d'audit invalide")
        return appeler(
            request,
            memoire.auditer_developpement,
            repository=_repository(),
            limite=limite,
            appelant=appelant,
        )

    @router.get("/status")
    def status(request: Request) -> dict[str, Any]:
        chaine = appeler(request, memoire.verifier_chaine)
        return {"domain": memoire.DOMAINE, "status": chaine["status"], "verified": chaine["verified"]}

    @router.post("/preflight")
    async def preflight(request: Request) -> dict[str, Any]:
        appelant = principal(request, ecriture=False)
        data = _corps(await lire_objet(request), {"module", "task", "files"})
        module = _module(data)
        task = _chaine(data, "task")
        files = _liste_textes(data["files"], "files")
        return appeler(
            request,
            memoire.preflight,
            module,
            task,
            files=files,
            repository=_repository(),
            appelant=appelant,
        )

    @router.post("/scan")
    async def scan(request: Request) -> dict[str, Any]:
        appelant = principal(request, ecriture=True)
        data = _corps(await lire_objet(request), set(), optionnels={"max_files", "max_bytes", "max_total_bytes"})
        limits = {}
        for key in ("max_files", "max_bytes", "max_total_bytes"):
            if key in data:
                plafond = {
                    "max_files": memoire.MAX_SCAN_FILES,
                    "max_bytes": memoire.MAX_FILE_BYTES,
                    "max_total_bytes": memoire.MAX_SCAN_BYTES,
                }[key]
                if type(data[key]) is not int or not 1 <= data[key] <= plafond:
                    raise HTTPException(400, "limite de scan invalide")
                limits[key] = data[key]
        return appeler(
            request,
            memoire.scanner_depot,
            _repository(),
            horodatage=_horodatage_serveur(),
            appelant=appelant,
            **limits,
        )

    @router.post("/prompts")
    async def enregistrer_prompt(request: Request) -> dict[str, Any]:
        appelant = principal(request, ecriture=True)
        data = _corps(
            await lire_objet(request),
            {"prompt_id", "content", "version", "module", "purpose"},
            optionnels={"source_refs", "status"},
        )
        prompt_id = _identifiant(data, "prompt_id")
        content = _chaine(data, "content", maximum=memoire.MAX_PROMPT_CHARS)
        version = _version(data)
        module = _module(data)
        purpose = _chaine(data, "purpose")
        source_refs = _liste_textes(data.get("source_refs", []), "source_refs")
        status = _statut(data, defaut="active", permis=memoire.STATUTS)
        return appeler(
            request,
            memoire.enregistrer_prompt,
            prompt_id,
            content,
            version=version,
            module=module,
            objectif=purpose,
            source_refs=source_refs,
            statut=status,
            horodatage=_horodatage_serveur(),
            appelant=appelant,
        )

    @router.post("/plans")
    async def enregistrer_plan(request: Request) -> dict[str, Any]:
        appelant = principal(request, ecriture=True)
        data = _corps(
            await lire_objet(request),
            {"plan_id", "version", "module", "prompt_id", "prompt_version", "objective", "steps", "files"},
            optionnels={"risks", "gaps", "owners", "status"},
        )
        plan_id = _identifiant(data, "plan_id")
        version = _version(data)
        module = _module(data)
        prompt_id = _identifiant(data, "prompt_id")
        prompt_version = _version(data, "prompt_version")
        objective = _chaine(data, "objective")
        steps = _liste_objets(data["steps"], "steps", maximum_items=200)
        if not steps or any(not {"id", "description"} <= set(step) for step in steps):
            raise HTTPException(400, "chaque étape doit avoir un id et une description")
        for step in steps:
            if (
                not isinstance(step["id"], str)
                or not step["id"].strip()
                or not isinstance(step["description"], str)
                or not step["description"].strip()
            ):
                raise HTTPException(400, "id et description d'étape doivent être des chaînes")
            if "statut" in step and (not isinstance(step["statut"], str) or not step["statut"].strip()):
                raise HTTPException(400, "statut d'étape invalide")
            _verifier_objet(step)
        files = _liste_textes(data["files"], "files")
        risks = _liste_textes(data.get("risks", []), "risks")
        gaps = _liste_textes(data.get("gaps", []), "gaps")
        owners = _liste_textes(data.get("owners", []), "owners")
        status = _statut(data, defaut="active", permis=memoire.STATUTS)
        return appeler(
            request,
            memoire.enregistrer_plan,
            plan_id,
            version=version,
            module=module,
            prompt_id=prompt_id,
            prompt_version=prompt_version,
            objectif=objective,
            etapes=steps,
            fichiers=files,
            risques=risks,
            ecarts=gaps,
            responsables=owners,
            statut=status,
            horodatage=_horodatage_serveur(),
            appelant=appelant,
        )

    @router.post("/decisions")
    async def enregistrer_decision(request: Request) -> dict[str, Any]:
        appelant = principal(request, ecriture=True)
        data = _corps(
            await lire_objet(request),
            {
                "decision_id",
                "version",
                "module",
                "context",
                "options",
                "reasons",
                "consequences",
                "authority",
                "source_refs",
            },
            optionnels={"status"},
        )
        decision_id = _identifiant(data, "decision_id")
        version = _version(data)
        module = _module(data)
        context_text = _chaine(data, "context")
        options = _liste_textes(data["options"], "options")
        reasons = _liste_textes(data["reasons"], "reasons")
        consequences = _liste_textes(data["consequences"], "consequences")
        authority = _chaine(data, "authority")
        source_refs = _liste_textes(data["source_refs"], "source_refs")
        status = _statut(data, defaut="active", permis=memoire.STATUTS)
        return appeler(
            request,
            memoire.enregistrer_decision,
            decision_id,
            version=version,
            module=module,
            contexte_decision=context_text,
            options=options,
            raisons=reasons,
            consequences=consequences,
            autorite=authority,
            source_refs=source_refs,
            statut=status,
            horodatage=_horodatage_serveur(),
            appelant=appelant,
        )

    @router.post("/postflight")
    async def enregistrer_postflight(request: Request) -> dict[str, Any]:
        appelant = principal(request, ecriture=True)
        data = _corps(
            await lire_objet(request),
            {"operation_id", "module", "plan_id", "status", "summary", "changes", "tests", "report_refs"},
            optionnels={"claim_key", "version", "diagnostic"},
        )
        operation_id = _identifiant(data, "operation_id")
        module = _module(data)
        plan_id = _identifiant(data, "plan_id")
        status = _statut(data, defaut="", permis=frozenset({"done", "partial", "failed", "blocked"}))
        summary = _chaine(data, "summary")
        changes = _liste_objets(data["changes"], "changes")
        for change in changes:
            if set(change) - {"fichier", "resume"} or not isinstance(change.get("fichier"), str):
                raise HTTPException(400, "changement invalide")
            if "resume" in change and not isinstance(change["resume"], str):
                raise HTTPException(400, "résumé de changement invalide")
        tests = _liste_objets(data["tests"], "tests")
        for test in tests:
            _verifier_objet(test)
            if "source" in test and not isinstance(test["source"], str):
                raise HTTPException(400, "source de test invalide")
        report_refs = _liste_textes(data["report_refs"], "report_refs")
        claim_key = data.get("claim_key")
        if claim_key is not None and (not isinstance(claim_key, str) or not claim_key.strip() or len(claim_key) > 256):
            raise HTTPException(400, "claim_key invalide")
        diagnostic = data.get("diagnostic")
        if diagnostic is not None:
            fields = {
                "incident_id", "symptom", "cause", "cause_status", "prevention", "source_refs", "observed_at"
            }
            if not isinstance(diagnostic, dict) or set(diagnostic) != fields:
                raise HTTPException(400, "diagnostic invalide : champs exacts requis")
            if not isinstance(diagnostic["incident_id"], str) or not _IDENTIFIANT.fullmatch(diagnostic["incident_id"]):
                raise HTTPException(400, "diagnostic.incident_id invalide")
            for field in ("symptom", "cause", "prevention"):
                if (
                    not isinstance(diagnostic[field], str)
                    or not diagnostic[field].strip()
                    or len(diagnostic[field]) > 2_000
                ):
                    raise HTTPException(400, f"diagnostic.{field} invalide")
            if not isinstance(diagnostic["cause_status"], str) or diagnostic["cause_status"] not in {
                "hypothesis", "supported", "confirmed", "disputed", "unknown"
            }:
                raise HTTPException(400, "diagnostic.cause_status invalide")
            diagnostic_refs = _liste_textes(diagnostic["source_refs"], "diagnostic.source_refs")
            if len(diagnostic_refs) > 50:
                raise HTTPException(400, "diagnostic.source_refs trop volumineux")
            if diagnostic["cause_status"] != "unknown" and not diagnostic_refs:
                raise HTTPException(400, "source requise pour un diagnostic autre qu'inconnu")
            if not isinstance(diagnostic["observed_at"], str):
                raise HTTPException(400, "diagnostic.observed_at invalide")
            try:
                memoire._valider_horodatage(diagnostic["observed_at"])
            except ValueError as exc:
                raise HTTPException(400, "diagnostic.observed_at doit inclure un fuseau") from exc
            _verifier_objet(diagnostic)
        version = _version(data) if "version" in data else 1
        return appeler(
            request,
            memoire.enregistrer_postflight,
            operation_id,
            module=module,
            plan_id=plan_id,
            statut=status,
            resume=summary,
            changements=changes,
            tests=tests,
            rapport_refs=report_refs,
            claim_key=claim_key,
            diagnostic=diagnostic,
            version=version,
            horodatage=_horodatage_serveur(),
            appelant=appelant,
        )

    return router
