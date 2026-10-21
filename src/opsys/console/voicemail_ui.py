"""Upload admin borné de voicemail vers l'adaptateur canonique M1."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Mapping
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import FormData, UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from .. import stockage
from . import metier, pages, securite
from .securite import Session

_CHAMPS_REQUIS = frozenset({"source", "evenement_id", "appel_id", "recu_le", "telephone", "mutation_id", "csrf"})
_CHAMPS_OPTIONNELS = frozenset({"consentement_enregistrement", "consentement_transfert_externe"})
_CHAMP_FICHIER = "audio"
_MAX_AUDIO = 25 * 1024 * 1024
_MAX_FORMULAIRE = 64 * 1024
_MAX_CORPS = _MAX_AUDIO + _MAX_FORMULAIRE
_MAX_CHAMPS = 9
_MAX_PARTIE_OCTETS = 4096
_LOGGER = logging.getLogger(__name__)


def creer_router(
    *,
    session_page: Callable[[Request], Session],
    cnx_factory: Callable[[], Any] = stockage.transaction,
    deps: Mapping[str, Any],
    prefixe: str,
) -> APIRouter:
    """Construit la page et le handler upload sans modifier le parseur global de la console."""
    router = APIRouter()

    @router.get("/reception/voicemail", response_class=HTMLResponse)
    def page_voicemail(request: Request) -> HTMLResponse:
        session = session_page(request)
        return _page(prefixe, session)

    @router.post("/reception/voicemail", response_class=HTMLResponse)
    async def importer_voicemail(request: Request) -> HTMLResponse:
        session = session_page(request)
        formulaire = await _multipart_borne(request)
        try:
            champs, fichier = _extraire_champs(formulaire)
            if not securite.csrf_valide(champs["csrf"], session):
                raise HTTPException(403, "jeton CSRF absent ou invalide : rechargez la page")
            _valider_mutation(champs["mutation_id"])
            consentement = _consentement(champs.get("consentement_enregistrement"))
            transfert = _consentement(champs.get("consentement_transfert_externe"))
            nom_fichier = fichier.filename or ""
            suffixe = "." + nom_fichier.rsplit(".", 1)[-1].lower() if "." in nom_fichier else ""
            if suffixe != ".wav" or len(nom_fichier) > 200:
                raise HTTPException(400, "seuls les fichiers WAV sont acceptés")
            if fichier.size is not None and fichier.size > _MAX_AUDIO:
                raise HTTPException(413, "fichier audio au-delà de 25 MiB")
            audio = await fichier.read(_MAX_AUDIO + 1)
            if len(audio) > _MAX_AUDIO:
                raise HTTPException(413, "fichier audio au-delà de 25 MiB")

            from m1_front_office import voicemail_stt

            try:
                voicemail_stt.valider_metadonnees(
                    champs["source"], champs["evenement_id"], champs["appel_id"],
                    champs["recu_le"], champs["telephone"],
                )
                voicemail_stt.valider_wav(audio)
            except voicemail_stt.ErreurVoicemail as exc:
                raise HTTPException(400, exc.code) from None

            # L'opérateur peut être révoqué pendant le transfert client → console. Revalider après
            # lecture/validation du WAV et immédiatement avant son éventuel envoi au STT.
            session = session_page(request)
            mutation_id = champs["mutation_id"]
            try:
                configuration_stt = voicemail_stt.ConfigurationSTT.depuis_env()
            except voicemail_stt.ErreurVoicemail:
                configuration_stt = None
            empreinte_stt = voicemail_stt.empreinte_requete_stt(
                audio,
                suffixe=".wav",
                source=champs["source"],
                evenement_id=champs["evenement_id"],
                appel_id=champs["appel_id"],
                recu_le=champs["recu_le"],
                telephone=champs["telephone"],
                consentement_enregistrement=consentement,
                consentement_transfert_externe=transfert,
                configuration=configuration_stt,
            )

            from m1_front_office import outils as outils_m1

            reponse_rejouee = None
            if empreinte_stt is not None:
                with cnx_factory():
                    reponse_rejouee = outils_m1.rechercher_rejeu_voicemail_stt(
                        empreinte_stt, champs["source"], champs["evenement_id"], champs["appel_id"]
                    )
                if reponse_rejouee is not None:
                    # Revérifie l'autorité après lecture du registre, avant de rendre sa réponse.
                    session = session_page(request)

            def importer(arguments: Mapping[str, Any]) -> Mapping[str, Any]:
                # Nouvelle lecture de l'acteur après le réseau : aucun verrou de base ne reste pris pendant STT.
                session_finale = session_page(request)
                try:
                    with cnx_factory() as cnx:
                        return metier.executer(
                            cnx,
                            deps,
                            session_finale,
                            "m1_importer_appel_manuellement",
                            arguments,
                            mutation_id=mutation_id,
                        )
                except PermissionError:
                    raise HTTPException(403, "administration métier requise") from None
                except ValueError as exc:
                    code = 409 if "conflit" in str(exc).lower() or "contradictoire" in str(exc).lower() else 400
                    message = (
                        "conflit de reprise; première importation conservée" if code == 409 else "import M1 refusé"
                    )
                    raise HTTPException(code, message) from None

            if reponse_rejouee is not None:
                resultat = {
                    "statut": "transcrit",
                    "rejeu_stt": True,
                    "m1": {"ok": True, "resultat": reponse_rejouee, "rejoue": True},
                }
            else:
                resultat = await run_in_threadpool(
                    voicemail_stt.transcrire_et_importer,
                    audio,
                    suffixe=".wav",
                    source=champs["source"],
                    evenement_id=champs["evenement_id"],
                    appel_id=champs["appel_id"],
                    recu_le=champs["recu_le"],
                    telephone=champs["telephone"],
                    consentement_enregistrement=consentement,
                    consentement_transfert_externe=transfert,
                    configuration=configuration_stt,
                    importeur=importer,
                )
                m1 = resultat.get("m1")
                if (
                    empreinte_stt is not None
                    and resultat.get("statut") == "transcrit"
                    and isinstance(m1, Mapping)
                    and m1.get("ok") is True
                ):
                    try:
                        with cnx_factory():
                            outils_m1.enregistrer_rejeu_voicemail_stt(
                                empreinte_stt, champs["source"], champs["evenement_id"], champs["appel_id"]
                            )
                    except Exception:
                        # L'index de réutilisation est optionnel; aucun contenu ou hash n'est journalisé.
                        _LOGGER.warning("index de réutilisation STT M1 non écrit après import accepté")
            m1 = resultat.get("m1")
            if not isinstance(m1, Mapping) or m1.get("ok") is not True:
                raise HTTPException(409, "l'import canonique M1 a refusé cet événement")
            if resultat.get("statut") == "transcrit":
                message = "Message vocal importé; transcription reçue, à vérifier par une personne."
            else:
                message = "Message vocal importé sans transcription; rappel humain conservé."
            return _page(prefixe, session, message=message)
        finally:
            await formulaire.close()

    return router


async def _multipart_borne(request: Request) -> FormData:
    if not request.headers.get("content-type", "").lower().startswith("multipart/form-data"):
        raise HTTPException(400, "un formulaire multipart est requis")
    entete = request.headers.get("content-length", "")
    if entete.isdigit() and int(entete) > _MAX_CORPS:
        raise HTTPException(413, "requête audio au-delà de la limite")

    async def flux_borne():
        taille = 0
        async for bloc in request.stream():
            taille += len(bloc)
            if taille > _MAX_CORPS:
                raise HTTPException(413, "requête audio au-delà de la limite")
            yield bloc

    try:
        parseur = MultiPartParser(
            request.headers,
            flux_borne(),
            max_files=1,
            max_fields=_MAX_CHAMPS,
            max_part_size=_MAX_PARTIE_OCTETS,
        )
        return await parseur.parse()
    except MultiPartException as exc:
        raise HTTPException(400, "formulaire multipart invalide ou trop complexe") from exc


def _extraire_champs(formulaire: FormData) -> tuple[dict[str, str], UploadFile]:
    acceptes = _CHAMPS_REQUIS | _CHAMPS_OPTIONNELS | {_CHAMP_FICHIER}
    noms = [nom for nom, _ in formulaire.multi_items()]
    if set(noms) != acceptes.intersection(noms) or set(noms) - acceptes:
        raise HTTPException(400, "champs d'upload invalides")
    valeurs: dict[str, str] = {}
    for nom in _CHAMPS_REQUIS | _CHAMPS_OPTIONNELS:
        items = formulaire.getlist(nom)
        if nom in _CHAMPS_REQUIS and len(items) != 1:
            raise HTTPException(400, f"champ requis ou dupliqué : {nom}")
        if len(items) > 1:
            raise HTTPException(400, f"champ dupliqué : {nom}")
        if items:
            if not isinstance(items[0], str):
                raise HTTPException(400, f"champ invalide : {nom}")
            valeurs[nom] = items[0]
    fichiers = formulaire.getlist(_CHAMP_FICHIER)
    if len(fichiers) != 1 or not isinstance(fichiers[0], UploadFile):
        raise HTTPException(400, "un seul fichier audio est requis")
    if not _CHAMPS_REQUIS.issubset(valeurs):
        raise HTTPException(400, "champs d'upload incomplets")
    return valeurs, fichiers[0]


def _consentement(valeur: str | None) -> str | None:
    if valeur in (None, ""):
        return None
    if valeur != "accorde":
        raise HTTPException(400, "valeur de consentement invalide")
    return valeur


def _valider_mutation(valeur: str) -> None:
    if not valeur.strip() or len(valeur) > 200 or not valeur.isprintable():
        raise HTTPException(400, "identifiant de reprise invalide")


def _page(prefixe: str, session: Session, message: str | None = None) -> HTMLResponse:
    contenu = ['<section class="carte"><h2>Importer un message vocal</h2>']
    contenu.append(
        '<p>Import manuel d’un WAV déjà obtenu et autorisé. Le média est temporaire; aucun appel ni message '
        'n’est envoyé. Une transcription reçue doit être vérifiée par une personne.</p>'
    )
    if message:
        contenu.append(f'<p class="message message-ok" role="status">{pages.e(message)}</p>')
    contenu.extend([
        f'<form method="post" enctype="multipart/form-data" '
        f'action="{pages.e(prefixe)}/reception/voicemail" class="pile">',
        f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">',
        f'<input type="hidden" name="mutation_id" value="{pages.e(uuid.uuid4())}">',
        '<label>Source consultée<input name="source" maxlength="120" required></label>',
        '<label>Identifiant de l’événement<input name="evenement_id" maxlength="200" required></label>',
        '<label>Référence d’appel<input name="appel_id" maxlength="200" required></label>',
        '<label>Reçu le (heure de la source)<input name="recu_le" '
        'placeholder="2026-09-30T12:00:00-04:00" required></label>',
        '<label>Téléphone E.164<input name="telephone" type="tel" placeholder="+15145550142" required></label>',
        '<label>Fichier WAV<input name="audio" type="file" accept=".wav,audio/wav" required></label>',
        '<label class="choix"><input name="consentement_enregistrement" type="checkbox" value="accorde">'
        'Consentement explicite à traiter et conserver la transcription</label>',
        '<label class="choix"><input name="consentement_transfert_externe" type="checkbox" value="accorde">'
        'J’autorise séparément le transfert à l’endpoint STT externe configuré</label>',
        '<button type="submit" class="principal">Importer le voicemail</button></form>',
        '<p class="note">Sans configuration STT ou consentement applicable, le fait d’appel et le rappel restent; '
        'aucune transcription n’est inventée. Le média n’est pas conservé après traitement.</p></section>',
    ])
    return HTMLResponse(pages.gabarit("Voicemail", "".join(contenu), prefixe=prefixe,
                                      session=session, actif="reception"))
