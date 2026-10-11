"""Pont interne entre un site de confiance et le contrat canonique d'entrée M1.

Cette route n'est pas destinée à l'extrait HTML du navigateur. Le serveur/site appelant
authentifie la charge par HMAC; la fonction injectée doit être le vrai
`Capacites.appeler("m1_recevoir_message_canal", ...)` de l'instance.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .. import contexte, taxonomie

_MAX_CORPS = 24_000
_MAX_MESSAGE = 4_000
_MAX_CONTACT = 254
_MAX_UTM = 200
_SITE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_NONCE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
_TIMESTAMP = re.compile(r"^[0-9]{1,12}$")
_SIGNATURE = re.compile(r"^[0-9a-f]{64}$")
_UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign", "utm_content")
_BODY_KEYS = frozenset({"nom", "courriel", "telephone", "message", *_UTM_KEYS})
_REFUS_CONFIGURATION = frozenset({
    taxonomie.VERDICT_SERVICE_NON_CONFIGURE,
    taxonomie.VERDICT_SERVICE_INCONNU,
    taxonomie.VERDICT_SERVICE_INVALIDE,
    taxonomie.VERDICT_PROFIL_INVALIDE,
    taxonomie.VERDICT_ZONE_NON_CONFIGUREE,
    taxonomie.VERDICT_FENETRE_NON_CONFIGUREE,
})


def _object_sans_doublon(paires: list[tuple[str, Any]]) -> dict[str, Any]:
    objet: dict[str, Any] = {}
    for cle, valeur in paires:
        if cle in objet:
            raise ValueError("duplicate json key")
        objet[cle] = valeur
    return objet


def _json_strict(corps: bytes) -> Any:
    try:
        texte = corps.decode("utf-8", errors="strict")
        return json.loads(
            texte,
            object_pairs_hook=_object_sans_doublon,
            parse_constant=lambda _valeur: (_ for _ in ()).throw(ValueError("invalid json constant")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
        raise HTTPException(400, "requête invalide") from None


def _valider_charge(charge: Any) -> dict[str, Any]:
    if not isinstance(charge, dict) or set(charge) - _BODY_KEYS:
        raise HTTPException(400, "requête invalide")
    for cle, valeur in charge.items():
        if not isinstance(valeur, str):
            raise HTTPException(400, "requête invalide")
        limite = _MAX_MESSAGE if cle == "message" else _MAX_UTM if cle in _UTM_KEYS else _MAX_CONTACT
        try:
            taille = len(valeur.encode("utf-8"))
        except UnicodeEncodeError:
            raise HTTPException(400, "requête invalide") from None
        if taille > limite:
            raise HTTPException(400, "requête invalide")
        if cle in _UTM_KEYS and not valeur:
            raise HTTPException(400, "requête invalide")
    courriel = charge.get("courriel")
    message = charge.get("message")
    if not isinstance(courriel, str) or not courriel.strip() or not isinstance(message, str) or not message.strip():
        raise HTTPException(400, "requête invalide")
    # Ces champs figurent dans le gabarit mais le contrat canonique M1 ne sait pas
    # les conserver comme contact : ne jamais les jeter ni les injecter dans le texte.
    if charge.get("nom", "") or charge.get("telephone", ""):
        raise HTTPException(400, "requête invalide")
    utm = {cle: charge[cle] for cle in _UTM_KEYS if cle in charge}
    if utm:
        return {"courriel": courriel, "message": message, "utm": utm}
    return {"courriel": courriel, "message": message, "utm": None}


def _canonique(site_id: str, timestamp: str, nonce: str, corps: bytes) -> bytes:
    return f"v1\nPOST\n/interne/m1/formulaire\n{site_id}\n{timestamp}\n{nonce}\n".encode("ascii") + corps


def creer_router(
    *,
    invoquer: Callable[[str, Mapping[str, Any]], Mapping[str, Any]],
    site_id: str | None,
    secret: bytes | None,
    horloge: Callable[[], float] = time.time,
) -> APIRouter:
    """Crée le pont fermé. `site_id`/`secret` sont fournis par l'opérateur, jamais le corps.

    Une absence de configuration laisse la route montée mais indisponible, afin de prouver
    qu'elle n'appelle aucun outil avant configuration. Ne pas exposer en public sans une
    intégration serveur-à-serveur et une politique de limitation propres à l'instance.
    """
    router = APIRouter()

    @router.post("/interne/m1/formulaire")
    async def recevoir(request: Request) -> JSONResponse:
        if (
            not isinstance(site_id, str) or not _SITE.fullmatch(site_id)
            or not isinstance(secret, bytes) or len(secret) < 32
        ):
            return JSONResponse({"ok": False, "error": "unavailable"}, status_code=503,
                                headers={"Cache-Control": "no-store"})
        content_types = request.headers.getlist("content-type")
        if len(content_types) != 1:
            return JSONResponse({"ok": False, "error": "invalid_request"}, status_code=400,
                                headers={"Cache-Control": "no-store"})
        content_type = content_types[0].lower()
        if content_type not in {"application/json", "application/json; charset=utf-8"}:
            return JSONResponse({"ok": False, "error": "invalid_request"}, status_code=400,
                                headers={"Cache-Control": "no-store"})
        lengths = request.headers.getlist("content-length")
        if len(lengths) > 1:
            return JSONResponse({"ok": False, "error": "invalid_request"}, status_code=400,
                                headers={"Cache-Control": "no-store"})
        advertised = lengths[0] if lengths else ""
        if advertised and (not re.fullmatch(r"[0-9]{1,6}", advertised) or int(advertised) > _MAX_CORPS):
            return JSONResponse({"ok": False, "error": "invalid_request"}, status_code=400,
                                headers={"Cache-Control": "no-store"})
        morceaux: list[bytes] = []
        taille = 0
        async for morceau in request.stream():
            taille += len(morceau)
            if taille > _MAX_CORPS:
                return JSONResponse({"ok": False, "error": "invalid_request"}, status_code=400,
                                    headers={"Cache-Control": "no-store"})
            morceaux.append(morceau)
        corps = b"".join(morceaux)
        authentification = {
            nom: request.headers.getlist(nom)
            for nom in ("x-m1-site", "x-m1-timestamp", "x-m1-nonce", "x-m1-signature")
        }
        if any(len(valeurs) != 1 for valeurs in authentification.values()):
            return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403,
                                headers={"Cache-Control": "no-store"})
        entete_site = authentification["x-m1-site"][0]
        timestamp = authentification["x-m1-timestamp"][0]
        nonce = authentification["x-m1-nonce"][0]
        signature = authentification["x-m1-signature"][0]
        if (
            entete_site != site_id or not _TIMESTAMP.fullmatch(timestamp)
            or not _NONCE.fullmatch(nonce) or not _SIGNATURE.fullmatch(signature)
        ):
            return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403,
                                headers={"Cache-Control": "no-store"})
        epoch = int(timestamp)
        try:
            ecart = abs(int(horloge()) - epoch)
        except (TypeError, ValueError, OverflowError):
            return JSONResponse({"ok": False, "error": "unavailable"}, status_code=503,
                                headers={"Cache-Control": "no-store"})
        if ecart > 300 or not hmac.compare_digest(
            hmac.new(secret, _canonique(site_id, timestamp, nonce, corps), hashlib.sha256).hexdigest(), signature,
        ):
            return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403,
                                headers={"Cache-Control": "no-store"})
        try:
            charge = _valider_charge(_json_strict(corps))
            horodatage = datetime.fromtimestamp(epoch, UTC).isoformat(timespec="seconds")
            arguments = {
                "canal": "formulaire",
                "expediteur": charge["courriel"],
                "message_id": f"{site_id}:{nonce}",
                "recu_le": horodatage,
                "texte": charge["message"],
                "utm": charge["utm"],
            }

            def invoquer_signe() -> Mapping[str, Any]:
                # Le token appartient au worker, même si l'attente HTTP est interrompue.
                with contexte.reception_formulaire_signee(f"formulaire:{site_id}:{nonce}", charge["utm"]):
                    return invoquer("m1_recevoir_message_canal", arguments)

            resultat = await run_in_threadpool(invoquer_signe)
            if (
                not isinstance(resultat, Mapping)
                or resultat.get("ok") is not True
                or "statut" in resultat
                or not isinstance(resultat.get("resultat"), Mapping)
            ):
                # Le répartiteur traduit aussi les erreurs de profil/zone/services
                # en refus_metier. Elles ne doivent pas faire abandonner l'amont.
                details = resultat.get("details") if isinstance(resultat, Mapping) else None
                code = details.partition(":")[0] if isinstance(details, str) else None
                if code in _REFUS_CONFIGURATION:
                    return JSONResponse({"ok": False, "error": "unavailable"}, status_code=503,
                                        headers={"Cache-Control": "no-store"})
                if isinstance(resultat, Mapping) and resultat.get("erreur") in {
                    "refus_metier", "arguments_invalides",
                }:
                    return JSONResponse({"ok": False, "error": "invalid_request"}, status_code=400,
                                        headers={"Cache-Control": "no-store"})
                return JSONResponse({"ok": False, "error": "unavailable"}, status_code=503,
                                    headers={"Cache-Control": "no-store"})
        except HTTPException:
            return JSONResponse({"ok": False, "error": "invalid_request"}, status_code=400,
                                headers={"Cache-Control": "no-store"})
        except Exception:
            return JSONResponse({"ok": False, "error": "unavailable"}, status_code=503,
                                headers={"Cache-Control": "no-store"})
        return JSONResponse({"ok": True, "received": True}, status_code=202,
                            headers={"Cache-Control": "no-store"})

    return router
