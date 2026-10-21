"""Private Core-to-M6 photo transport; authority is rechecked before each emission."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Callable
from io import BytesIO
from threading import BoundedSemaphore

import anyio

from opsys import contexte

CHEMIN = "/mcp/fichiers/m6-preuves"
CHEMIN_REVALIDER = CHEMIN + "/revalider"
MAX_CORPS = 16384
MAX_PHOTO = 10 * 1024 * 1024
MAX_PIXELS = 16_000_000
MAX_DIMENSION = 8192
FRAGMENT = 65536
_SHA = re.compile(r"[a-f0-9]{64}\Z")
_TRAVAILLEURS = BoundedSemaphore(2)


class AutoritePhotoRetiree(RuntimeError):
    """The current stream may no longer emit bytes."""


def _travail_borne(operation, *arguments):
    # Keep the slot in the actual worker until it returns, including after ASGI cancellation.
    if not _TRAVAILLEURS.acquire(blocking=False):
        raise RuntimeError("travailleurs photo occupés")
    try:
        return operation(*arguments)
    finally:
        _TRAVAILLEURS.release()


async def _executer_travail(operation, *arguments):
    return await anyio.to_thread.run_sync(
        _travail_borne, operation, *arguments, abandon_on_cancel=True,
    )


def _objet_ferme(paires):
    resultat = {}
    for cle, valeur in paires:
        if cle in resultat:
            raise ValueError("champ dupliqué")
        resultat[cle] = valeur
    return resultat


def _texte(valeur, maximum=256):
    return (
        type(valeur) is str and bool(valeur.strip()) and len(valeur) <= maximum
        and not any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in valeur)
    )


def _valider_corps(brut):
    corps = json.loads(brut, object_pairs_hook=_objet_ferme)
    if type(corps) is not dict or set(corps) != {"selection", "identite", "appareil_id"}:
        raise ValueError("corps invalide")
    selection, identite = corps["selection"], corps["identite"]
    if type(identite) is not dict or set(identite) != {"personne", "role"}:
        raise ValueError("identité invalide")
    if not _texte(identite["personne"]) or identite["role"] != "admin" or not _texte(corps["appareil_id"]):
        raise ValueError("identité invalide")
    if type(selection) is not dict or set(selection) != {"wct_id", "preuve", "position_photo"}:
        raise ValueError("sélection invalide")
    preuve = selection["preuve"]
    if (
        not _texte(selection["wct_id"])
        or type(preuve) is not dict or set(preuve) != {"index", "hash_maillon"}
        or type(preuve["index"]) is not int or not 0 <= preuve["index"] <= 10000
        or type(preuve["hash_maillon"]) is not str or not _SHA.fullmatch(preuve["hash_maillon"])
        or type(selection["position_photo"]) is not int or not 0 <= selection["position_photo"] <= 2
    ):
        raise ValueError("sélection invalide")
    return selection, contexte.IdentiteAppelante(**identite, source="appareil")


def _blob_verifie(resultat):
    if type(resultat) is not dict or resultat.get("accepte") is not True:
        return False
    octets, empreinte = resultat.get("octets"), resultat.get("empreinte_sha256")
    mime = resultat.get("type_mime")
    return (
        type(octets) is bytes and 0 < len(octets) <= MAX_PHOTO
        and type(resultat.get("taille_octets")) is int and resultat["taille_octets"] == len(octets)
        and type(empreinte) is str and _SHA.fullmatch(empreinte) is not None
        and resultat.get("reference") == "fichier:sha256:" + empreinte
        and hashlib.sha256(octets).hexdigest() == empreinte
        and ((mime == "image/png" and octets.startswith(b"\x89PNG\r\n\x1a\n"))
             or (mime == "image/jpeg" and octets.startswith(b"\xff\xd8\xff")))
        and _image_decodable(octets, mime)
    )


def _image_decodable(octets, mime):
    """Verify structure and bounded pixels using the already locked runtime decoder."""
    try:
        from PIL import Image
    except ImportError:
        return False
    format_attendu = "PNG" if mime == "image/png" else "JPEG"
    try:
        with Image.open(BytesIO(octets), formats=[format_attendu]) as image:
            largeur, hauteur = image.size
            if (not 0 < largeur <= MAX_DIMENSION or not 0 < hauteur <= MAX_DIMENSION
                    or largeur * hauteur > MAX_PIXELS or getattr(image, "n_frames", 1) != 1):
                return False
            image.verify()
        with Image.open(BytesIO(octets), formats=[format_attendu]) as image:
            image.load()
    except (OSError, ValueError, Image.DecompressionBombError):
        return False
    return True


def _metadata_verifie(resultat, autorite):
    if type(resultat) is not dict or resultat.get("accepte") is not True:
        return False
    empreinte = resultat.get("empreinte_sha256")
    return (
        type(empreinte) is str and _SHA.fullmatch(empreinte) is not None
        and resultat.get("reference") == "fichier:sha256:" + empreinte
        and resultat.get("type_mime") in {"image/png", "image/jpeg"}
        and type(resultat.get("taille_octets")) is int and 0 < resultat["taille_octets"] <= MAX_PHOTO
        and resultat.get("autorite") == autorite
    )


async def _refuser(send, statut, code):
    octets = json.dumps({"ok": False, "erreur": code}, separators=(",", ":")).encode()
    await send({"type": "http.response.start", "status": statut, "headers": [
        (b"content-type", b"application/json"), (b"cache-control", b"no-store"),
        (b"content-length", str(len(octets)).encode()), (b"x-content-type-options", b"nosniff"),
    ]})
    await send({"type": "http.response.body", "body": octets, "more_body": False})


def creer_pont_photos_preuves(jeton: str, *, lecteur: Callable | None = None, revalider: Callable | None = None):
    """Create a private ASGI endpoint; its credential must be distinct from public MCP."""
    if not _texte(jeton, 4096) or len(jeton) < 24:
        raise ValueError("jeton privé photo invalide")
    if lecteur is None or revalider is None:
        from m6_material_control.outils import autoriser_et_lire_photo, revalider_autorite_photo
        lecteur = lecteur or autoriser_et_lire_photo
        revalider = revalider or revalider_autorite_photo

    async def application(scope, receive, send):
        if scope["type"] != "http":
            raise ValueError("transport HTTP requis")
        if scope.get("path") not in {CHEMIN, CHEMIN_REVALIDER} or scope.get("method") != "POST":
            await _refuser(send, 404, "photo_route_inconnue")
            return
        credentials = [v for k, v in scope.get("headers", []) if k.lower() == b"authorization"]
        attendu = ("Bearer " + jeton).encode()
        if len(credentials) != 1 or not hmac.compare_digest(credentials[0], attendu):
            await _refuser(send, 401, "photo_autorite_absente")
            return
        if scope.get("query_string"):
            await _refuser(send, 400, "photo_corps_invalide")
            return
        brut = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                await _refuser(send, 400, "photo_corps_invalide")
                return
            fragment = message.get("body", b"")
            if len(brut) + len(fragment) > MAX_CORPS:
                await _refuser(send, 413, "photo_corps_trop_volumineux")
                return
            brut.extend(fragment)
            if not message.get("more_body", False):
                break
        try:
            selection, identite = _valider_corps(brut)
        except (ValueError, UnicodeError, RecursionError):
            await _refuser(send, 400, "photo_corps_invalide")
            return
        arguments = (selection["wct_id"], selection["preuve"], selection["position_photo"])

        def appeler(callback):
            with contexte.appele_par_appareil(identite):
                return callback(*arguments)

        async def surveiller_deconnexion(groupe):
            while True:
                if (await receive())["type"] == "http.disconnect":
                    groupe.cancel_scope.cancel()
                    return

        async with anyio.create_task_group() as groupe:
            groupe.start_soon(surveiller_deconnexion, groupe)
            autorite = {"personne": identite.personne, "role": identite.role, "source": "appareil"}
            if scope["path"] == CHEMIN_REVALIDER:
                try:
                    verdict = await _executer_travail(appeler, revalider)
                except Exception:
                    await _refuser(send, 503, "photo_service_indisponible")
                else:
                    if not _metadata_verifie(verdict, autorite):
                        await _refuser(send, 403, "photo_autorite_retiree")
                    else:
                        from starlette.responses import JSONResponse

                        metadata = {k: verdict[k] for k in (
                            "accepte", "reference", "empreinte_sha256", "type_mime", "taille_octets", "autorite"
                        )}
                        await JSONResponse({"ok": True, "resultat": metadata}, headers={
                            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                        })(scope, receive, send)
                groupe.cancel_scope.cancel()
                return
            try:
                resultat = await _executer_travail(appeler, lecteur)
            except Exception:
                await _refuser(send, 503, "photo_service_indisponible")
                groupe.cancel_scope.cancel()
                return
            try:
                blob_valide = await _executer_travail(_blob_verifie, resultat)
            except Exception:
                await _refuser(send, 503, "photo_service_indisponible")
                groupe.cancel_scope.cancel()
                return
            if not blob_valide:
                await _refuser(send, 409, "photo_indisponible")
                groupe.cancel_scope.cancel()
                return
            autorite = {"personne": identite.personne, "role": identite.role, "source": "appareil"}

            async def actuel():
                try:
                    verdict = await _executer_travail(appeler, revalider)
                except Exception:
                    return None
                return (
                    type(verdict) is dict and verdict.get("accepte") is True
                    and verdict.get("autorite", autorite) == autorite
                    and all(verdict.get(k, resultat[k]) == resultat[k] for k in (
                        "reference", "empreinte_sha256", "type_mime", "taille_octets"
                    ))
                )

            validation = await actuel() if resultat.get("autorite", autorite) == autorite else False
            if validation is not True:
                await _refuser(send, 503 if validation is None else 403,
                              "photo_service_indisponible" if validation is None else "photo_autorite_retiree")
                groupe.cancel_scope.cancel()
                return
            octets = resultat["octets"]

            await send({"type": "http.response.start", "status": 200, "headers": [
                (b"content-type", resultat["type_mime"].encode()),
                (b"content-length", str(len(octets)).encode()),
                (b"x-opsys-sha256", resultat["empreinte_sha256"].encode()),
                (b"etag", ('"' + resultat["empreinte_sha256"] + '"').encode()),
                (b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff"),
            ]})
            for position in range(0, len(octets), FRAGMENT):
                if not await actuel():
                    raise AutoritePhotoRetiree("autorité photo retirée pendant le flux")
                await send({"type": "http.response.body", "body": octets[position:position + FRAGMENT],
                            "more_body": position + FRAGMENT < len(octets)})
            groupe.cancel_scope.cancel()

    async def application_bornee(scope, receive, send):
        entetes_emises = False

        async def envoyer(message):
            nonlocal entetes_emises
            if message["type"] == "http.response.start":
                entetes_emises = True
            await send(message)

        try:
            with anyio.fail_after(120):
                await application(scope, receive, envoyer)
        except TimeoutError:
            if entetes_emises:
                raise AutoritePhotoRetiree("délai du transport photo dépassé") from None
            await _refuser(send, 504, "photo_delai_depasse")

    return application_bornee
