"""Console M7 de révision du contenu de chantier et du calendrier manuel.

Toutes les lectures et mutations traversent les outils M7 durables via `console.metier`. Cette
surface propose des brouillons, recueille les décisions du propriétaire et remet un paquet manuel;
elle ne programme et ne publie jamais.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy import select
from starlette.datastructures import FormData, UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser

from .. import identite
from ..stockage.schema import MUTATIONS_APPLIQUEES
from . import metier, pages, securite
from .securite import Session

_LIMITE_CONTENUS = 8
_MAX_ID = 200
_MAX_MOTIF = 500
_MAX_PLANIFICATION = timedelta(days=365)
_MAX_CORPS_MEDIA = 10 * 1024 * 1024 + 32 * 1024
_DECISIONS = {"approuver", "rejeter"}
_ACTIONS = {
    "proposer_contenus",
    "decider_contenu",
    "proposer_creneau",
    "decider_creneau",
    "exporter_creneau",
    "decider_medias",
    "remettre_medias",
    "reviser_texte",
}
_LIBELLES_STATUTS = {
    "PROPOSE": "À réviser",
    "APPROVED": "Approuvé par le propriétaire",
    "REJECTED": "Rejeté",
    "RETIRE": "Consentement retiré",
    "BROUILLON": "Créneau brouillon",
    "CONFLIT_SOURCE": "Source en conflit",
    "CONTENU_NON_APPROUVE": "Texte non approuvé",
}


def creer_router(
    *,
    session_page: Callable[..., Session],
    session_api: Callable[..., Session],
    ecriture_api: Callable[[Request], Session],
    formulaire: Callable[[Request], Any],
    objet_json: Callable[[Request], Any],
    cnx_factory: Callable[[], Any],
    deps: Mapping[str, Any],
    prefixe: str,
) -> APIRouter:
    """Routes HTML et JSON protégées par les sessions, rôles et outils métier canoniques."""
    router = APIRouter(tags=["marketing calendrier M7"])

    def appeler(session: Session, nom: str, arguments: Mapping[str, Any], mutation_id: str | None = None):
        try:
            with cnx_factory() as cnx:
                if mutation_id is not None:
                    personne = identite.personne_active(cnx, session.utilisateur)
                    if personne is None or not personne.roles.intersection({"nathan_owner", "admin"}):
                        raise PermissionError("administration métier requise")
                    if nom in metier.DECISIONS_HUMAINES and "nathan_owner" not in personne.roles:
                        raise PermissionError("propriétaire actif requis")
                    from m7_marketing.usine import service

                    # Lecture de présence seulement ; le moteur existant vérifie ensuite
                    # le conflit, rejoue/finalise son reçu et garde la trace des appels frais.
                    deja_recu = cnx.execute(select(MUTATIONS_APPLIQUEES.c.cle_idempotence).where(
                        MUTATIONS_APPLIQUEES.c.appareil == f"console:{personne.identifiant}",
                        MUTATIONS_APPLIQUEES.c.cle_idempotence == mutation_id,
                    )).first() is not None
                    refus_source = service.verifier_marque_commande(nom, arguments, rejeu=deja_recu)
                    if refus_source is not None:
                        return refus_source
                return metier.executer(cnx, deps, session, nom, arguments, mutation_id=mutation_id)
        except PermissionError as exc:
            raise HTTPException(403, "accès métier refusé") from exc
        except KeyError as exc:
            raise HTTPException(404, "outil M7 indisponible") from exc
        except ValueError as exc:
            detail = str(exc).casefold()
            code = 403 if "aucun rôle autorisé" in detail else 409 if "conflit" in detail else 400
            raise HTTPException(code, "demande métier refusée") from exc

    def resultat(reponse: Any) -> tuple[bool, Any, str]:
        refus = _refus(reponse)
        if refus is not None:
            return False, None, refus
        valeur = reponse
        while isinstance(valeur, Mapping) and "resultat" in valeur:
            valeur = valeur["resultat"]
        if not isinstance(valeur, Mapping):
            return False, None, "Réponse métier invalide."
        return True, valeur, ""

    def donnees(session: Session, decalage: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        lecture = appeler(
            session,
            "m7_lister_contenus_chantier",
            {"limite": _LIMITE_CONTENUS, "decalage": decalage},
        )
        ok, contenu, erreur = resultat(lecture)
        if not ok:
            raise HTTPException(409, erreur)
        slots = appeler(session, "m7_lister_calendrier", {})
        ok_slots, calendrier, erreur_slots = resultat(slots)
        if not ok_slots:
            raise HTTPException(409, erreur_slots)
        return dict(contenu), list(calendrier.get("creneaux", []))

    def page(
        session: Session,
        *,
        decalage: int = 0,
        message: str = "",
        erreur: str = "",
        mutation_id: str | None = None,
        paquet: Mapping[str, Any] | None = None,
        status_code: int = 200,
    ) -> HTMLResponse:
        liste, slots = donnees(session, decalage)
        contenus = liste.get("contenus", [])
        par_contenu = {item.get("contenu_id"): item for item in contenus}
        creneaux_approuves = {s.get("contenu_id"): s for s in slots if s.get("statut") == "APPROVED"}
        sections = [
            f'<p><a href="{pages.e(prefixe)}/marketing">Retour au marketing</a></p>',
            '<p class="note">Les textes proviennent des WCT reçus et restent des brouillons jusqu’à '
            'l’approbation du propriétaire. Un créneau approuvé ne programme ni ne publie un post.</p>',
        ]
        if message:
            sections.append(f'<p class="message message-ok" role="status">{pages.e(message)}</p>')
        if erreur:
            sections.append(f'<p class="message message-erreur" role="alert">{pages.e(erreur)}</p>')
        if paquet is not None:
            sections.append(_paquet_html(paquet))

        sections.extend([
            '<section class="carte"><h2>Préparer des brouillons depuis un chantier terminé</h2>',
            '<p>Le WCT doit déjà exister dans le registre M7 et porter un consentement marketing valide. '
            'La proposition ne l’approuve pas.</p>',
            f'<form method="post" action="{pages.e(prefixe)}/marketing/calendrier" class="pile">',
            f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">',
            f'<input type="hidden" name="mutation_id" value="{pages.e(mutation_id or uuid.uuid4().hex)}">',
            '<input type="hidden" name="action" value="proposer_contenus">',
            '<label>Identifiant du WCT reçu<input name="wct_id" required maxlength="200"></label>',
            '<button type="submit">Proposer les brouillons</button></form></section>',
            '<section class="carte"><h2>Contenus de chantier</h2>',
        ])
        if not contenus:
            sections.append('<p class="vide">Aucun contenu de chantier proposé.</p>')
        for item in contenus:
            contenu_id = str(item.get("contenu_id", ""))
            statut = str(item.get("approval_status", ""))
            decision = item.get("decision")
            preuve = item.get("consentement") if isinstance(item.get("consentement"), Mapping) else {}
            marque = item.get("marque_source") if isinstance(item.get("marque_source"), Mapping) else {}
            marque_courante = liste.get("marque_courante") if isinstance(liste.get("marque_courante"), Mapping) else {}
            fraicheur = item.get("fraicheur_marque")
            sections.extend([
                '<article class="carte contenu-calendrier">',
                f'<h3>{pages.e(item.get("plateforme", "Contenu"))} · '
                f'révision {pages.e(item.get("revision", "—"))}</h3>',
                f'<p class="note">Source WCT : {pages.e(item.get("wct_id", "—"))} · '
                f'Origine du texte : {pages.e(item.get("origine_texte", "—"))} · '
                f'{pages.e(_LIBELLES_STATUTS.get(statut, statut or "État inconnu"))}</p>',
                f'<p class="texte-contenu">{pages.e(item.get("texte", ""))}</p>',
                f'<p class="note">Consentement : {pages.e(preuve.get("recueilli_par", "—"))} · '
                f'{pages.e(preuve.get("recueilli_le", "—"))} · '
                f'{pages.e(preuve.get("version_texte", "—"))}</p>',
            ])
            sections.append(f'<p class="note">Marque source : {pages.e(marque.get("source", "preuve absente"))} · '
                            f'révision {pages.e(marque.get("revision", "—"))} · '
                            f'empreinte {pages.e(marque.get("sha256", "—"))} · '
                            f'état {pages.e(fraicheur or "inconnu")} · '
                            f'révision courante {pages.e(marque_courante.get("revision", "—"))}</p>')
            if fraicheur != "courante":
                sections.append('<p class="note">Historique non qualifié pour une nouvelle revue ou remise. '
                                'La reprise crée des brouillons à approuver de nouveau.</p>')
                sections.append(_formulaire(prefixe, session, "proposer_contenus",
                                            {"wct_id": str(item.get("wct_id", ""))},
                                            "Reproposer avec la marque courante"))
            if isinstance(decision, Mapping):
                sections.append(
                    f'<p class="note">Décision : {pages.e(decision.get("decision", ""))} par '
                    f'{pages.e(decision.get("par", ""))}, le {pages.e(decision.get("horodatage", ""))}</p>'
                )
            try:
                edition_reponse = appeler(session, "m7_lire_edition_texte_humain", {"contenu_id": contenu_id})
                edition_ok, edition, _ = resultat(edition_reponse)
            except HTTPException:
                edition_ok = False
            if edition_ok:
                sections.append(_formulaire_edition_texte(prefixe, session, edition))
            if statut == "PROPOSE" and fraicheur == "courante":
                sections.append(_formulaire(
                    prefixe, session, "decider_contenu",
                    {"contenu_id": contenu_id, "decision": "approuver"}, "Approuver ce texte",
                ))
            if statut == "PROPOSE":
                sections.append(_formulaire(
                    prefixe, session, "decider_contenu",
                    {"contenu_id": contenu_id, "decision": "rejeter"}, "Rejeter ce texte", motif=True,
                ))
            if statut == "APPROVED" and fraicheur == "courante":
                sections.extend([
                    '<h4>Proposer un créneau</h4>',
                    _formulaire(
                        prefixe, session, "proposer_creneau",
                        {"contenu_id": contenu_id}, "Créer un brouillon de créneau", date=True,
                    ),
                ])
                media_reponse = appeler(session, "m7_lire_dossier_medias", {"contenu_id": contenu_id})
                media_ok, medias, _erreur_media = resultat(media_reponse)
                if media_ok:
                    slot_media = creneaux_approuves.get(contenu_id)
                    sections.extend(_section_medias(
                        prefixe, session, contenu_id, medias,
                        slot_media.get("creneau_id") if isinstance(slot_media, Mapping) else None,
                    ))
            sections.append("</article>")
        sections.append(_pagination(prefixe, liste))
        sections.append("</section>")

        sections.append('<section class="carte"><h2>Calendrier éditorial</h2>')
        if not slots:
            sections.append('<p class="vide">Aucun créneau proposé.</p>')
        for slot in slots:
            contenu = par_contenu.get(slot.get("contenu_id"), {})
            source = slot.get("source") if isinstance(slot.get("source"), Mapping) else {}
            statut = str(slot.get("statut", ""))
            sections.extend([
                '<article class="carte creneau-calendrier">',
                f'<h3>{pages.e(contenu.get("plateforme", slot.get("plateforme", "Créneau")))} · '
                f'{pages.e(slot.get("planifie_le", "Date absente"))}</h3>',
                f'<p class="note">Source WCT : {pages.e(source.get("wct_id", slot.get("wct_id", "—")))} · '
                f'Contenu : {pages.e(slot.get("contenu_id", "—"))} · '
                f'{pages.e(_LIBELLES_STATUTS.get(statut, statut or "État inconnu"))}</p>',
            ])
            texte = contenu.get("texte")
            if isinstance(texte, str):
                sections.append(f'<p class="texte-contenu">{pages.e(texte)}</p>')
            sections.append(f'<p class="note">Source WCT vérifiée : {pages.e(source.get("wct_hash", "—"))}</p>')
            decision = slot.get("decision")
            if isinstance(decision, Mapping):
                sections.append(
                    f'<p class="note">Décision : {pages.e(decision.get("decision", ""))} par '
                    f'{pages.e(decision.get("par", ""))}, le {pages.e(decision.get("horodatage", ""))}</p>'
                )
            if statut == "BROUILLON" and slot.get("fraicheur_marque") == "courante":
                sections.append(_formulaire(
                    prefixe, session, "decider_creneau",
                    {"creneau_id": str(slot.get("creneau_id", "")), "decision": "approuver"},
                    "Approuver ce créneau",
                ))
                sections.append(_formulaire(
                    prefixe, session, "decider_creneau",
                    {"creneau_id": str(slot.get("creneau_id", "")), "decision": "rejeter"},
                    "Rejeter ce créneau", motif=True,
                ))
            elif statut == "APPROVED" and slot.get("fraicheur_marque") == "courante":
                sections.append(_formulaire(
                    prefixe, session, "exporter_creneau",
                    {"creneau_id": str(slot.get("creneau_id", ""))}, "Remettre le paquet manuel",
                ))
            sections.append("</article>")
        sections.append("</section>")
        html = pages.gabarit(
            "Calendrier marketing",
            "".join(sections),
            prefixe=prefixe,
            session=session,
            actif="marketing",
        )
        return HTMLResponse(html, status_code=status_code)

    @router.get("/marketing/calendrier", response_class=HTMLResponse)
    def calendrier_page(request: Request) -> Response:
        session = session_page(request)
        decalage = _decalage(request.query_params)
        return page(session, decalage=decalage)

    @router.post("/marketing/calendrier", response_class=HTMLResponse)
    async def calendrier_formulaire(request: Request) -> Response:
        session = session_page(request)
        champs = await formulaire(request)
        _csrf_formulaire(champs, session)
        commande = _commande(champs, formulaire=True)
        try:
            reponse = appeler(
                session,
                commande["outil"],
                commande["arguments"],
                mutation_id=commande["mutation_id"],
            )
            ok, corps, erreur = resultat(reponse)
        except HTTPException as exc:
            return page(
                session,
                erreur=str(exc.detail),
                mutation_id=commande["mutation_id"],
                status_code=exc.status_code,
            )
        if not ok:
            return page(session, erreur=erreur, mutation_id=commande["mutation_id"], status_code=409)
        manuel = corps.get("paquet") if commande["outil"] == "m7_exporter_creneau_manuel" else None
        return page(
            session,
            message="Action enregistrée. Aucune publication ou programmation automatique.",
            paquet=manuel if isinstance(manuel, Mapping) else None,
        )

    @router.get("/api/marketing/calendrier")
    def api_lire_calendrier(request: Request) -> Response:
        session = session_api(request)
        decalage = _decalage(request.query_params)
        liste, slots = donnees(session, decalage)
        return JSONResponse({
            "ok": True,
            "resultat": {
                "contenus": liste.get("contenus", []),
                "marque_courante": liste.get("marque_courante"),
                "pagination": {k: liste.get(k) for k in ("total", "decalage", "suivant", "reste")},
                "creneaux": slots,
                "publication": "aucune publication ni programmation automatique",
            },
        })

    @router.get("/api/marketing/calendrier/textes/{contenu_id}")
    def api_lire_edition_texte(contenu_id: str, request: Request) -> Response:
        session = session_api(request)
        reponse = appeler(session, "m7_lire_edition_texte_humain", {"contenu_id": contenu_id})
        ok, valeur, erreur = resultat(reponse)
        return JSONResponse(
            {"ok": ok, "resultat": valeur if ok else None, "erreur": None if ok else {"message": erreur}},
            status_code=200 if ok else 409,
            headers={"Cache-Control": "private, no-store, max-age=0", "Pragma": "no-cache"},
        )


    @router.get("/api/marketing/calendrier/medias/{contenu_id}")
    def api_lire_dossier_medias(contenu_id: str, request: Request) -> Response:
        session = session_api(request)
        try:
            reponse = appeler(session, "m7_lire_dossier_medias", {"contenu_id": contenu_id})
        except HTTPException as exc:
            return JSONResponse({"ok": False, "erreur": {"message": str(exc.detail)}}, status_code=exc.status_code)
        ok, _valeur, erreur = resultat(reponse)
        return JSONResponse(
            {"ok": ok, "resultat": reponse if ok else None, "erreur": None if ok else {"message": erreur}},
            status_code=200 if ok else 409,
            headers={"Cache-Control": "private, no-store, max-age=0", "Pragma": "no-cache"},
        )

    @router.post("/api/marketing/calendrier")
    async def api_action_calendrier(request: Request) -> Response:
        session = ecriture_api(request)
        corps = await objet_json(request)
        if not isinstance(corps, Mapping):
            raise HTTPException(400, "objet JSON attendu")
        commande = _commande(corps, formulaire=False)
        try:
            reponse = appeler(
                session,
                commande["outil"],
                commande["arguments"],
                mutation_id=commande["mutation_id"],
            )
        except HTTPException as exc:
            return JSONResponse({"ok": False, "erreur": {"message": str(exc.detail)}}, status_code=exc.status_code)
        ok, _corps_reponse, erreur = resultat(reponse)
        if not ok:
            return JSONResponse(
                {"ok": False, "erreur": {"message": erreur}, "resultat": reponse}, status_code=409
            )
        return JSONResponse({"ok": True, "resultat": reponse})

    def verifier_proprietaire(session: Session) -> None:
        try:
            with cnx_factory() as cnx:
                metier.exiger_proprietaire_media(cnx, session)
        except PermissionError as exc:
            raise HTTPException(403, "accès médias refusé") from exc

    async def recevoir_preparation(request: Request, session: Session, *, formulaire_html: bool) -> Response:
        # L'identité propriétaire est revérifiée avant de parser/tamponner le fichier transmis.
        verifier_proprietaire(session)
        try:
            formulaire = await _multipart_media_borne(request)
            noms = [nom for nom, _valeur in formulaire.multi_items()]
            attendus = {
                "mutation_id", "contenu_id", "source_ref", "revision_attendue", "empreinte_attendue",
                "snapshot_attendu", "attestation_humaine", "fichier",
            } | ({"csrf"} if formulaire_html else set())
            if set(noms) != attendus or len(noms) != len(attendus):
                raise HTTPException(400, "champs de préparation absents, dupliqués ou inattendus")
            champs: dict[str, Any] = {}
            for nom in attendus - {"fichier"}:
                valeur = formulaire.getlist(nom)
                if len(valeur) != 1 or not isinstance(valeur[0], str):
                    raise HTTPException(400, f"champ invalide ou dupliqué : {nom}")
                champs[nom] = valeur[0]
            if formulaire_html and not securite.csrf_valide(champs.get("csrf"), session):
                raise HTTPException(403, "CSRF invalide")
            fichiers_form = formulaire.getlist("fichier")
            if len(fichiers_form) != 1 or not isinstance(fichiers_form[0], UploadFile):
                raise HTTPException(400, "un fichier préparé requis")
            televersement = fichiers_form[0]
            from opsys.fichiers import TAILLE_MAX_OCTETS

            octets = await televersement.read(TAILLE_MAX_OCTETS + 1)
            if not isinstance(octets, bytes) or len(octets) > TAILLE_MAX_OCTETS:
                raise HTTPException(413, "fichier préparé hors limite")
            verifier_proprietaire(session)
            revision = _entier_formulaire(champs.get("revision_attendue"), "revision_attendue")
            arguments = {
                "contenu_id": _texte(champs, "contenu_id"),
                "source_ref": _texte(champs, "source_ref"),
                "revision_attendue": revision,
                "empreinte_attendue": _texte(champs, "empreinte_attendue", maximum=64),
                "snapshot_attendu": _texte(champs, "snapshot_attendu", maximum=64),
                "attestation_humaine": _texte(champs, "attestation_humaine", maximum=500),
                "fichier_sha256": hashlib.sha256(octets).hexdigest(),
            }
            mutation_id = _texte(champs, "mutation_id")
            with cnx_factory() as cnx:
                reponse = metier.executer(
                    cnx, deps, session, "m7_preparer_media_humain", arguments,
                    mutation_id=mutation_id, octets_prives=octets,
                )
        except PermissionError as exc:
            raise HTTPException(403, "accès médias refusé") from exc
        except (KeyError, ValueError) as exc:
            raise HTTPException(409, "préparation média refusée") from exc
        finally:
            if "formulaire" in locals():
                await formulaire.close()
        ok, _corps, erreur = resultat(reponse)
        if formulaire_html:
            return page(session, message="Préparé humain enregistré dans le dossier privé." if ok else "",
                        erreur="" if ok else erreur, status_code=200 if ok else 409)
        return JSONResponse({"ok": ok, "resultat": reponse}, status_code=200 if ok else 409)

    @router.post("/marketing/calendrier/medias", response_class=HTMLResponse)
    async def preparer_media_formulaire(request: Request) -> Response:
        return await recevoir_preparation(request, session_page(request), formulaire_html=True)

    @router.post("/api/marketing/calendrier/medias")
    async def preparer_media_api(request: Request) -> Response:
        return await recevoir_preparation(request, ecriture_api(request), formulaire_html=False)

    @router.get("/marketing/calendrier/medias/{contenu_id}")
    def lire_media_http(contenu_id: str, request: Request, reference: str, mode: str) -> Response:
        session = session_api(request)
        try:
            with cnx_factory() as cnx:
                media = metier.lire_media_prive(cnx, deps, session, contenu_id, reference, mode=mode)
        except PermissionError as exc:
            raise HTTPException(403, "accès médias refusé") from exc
        if media is None:
            raise HTTPException(404, "média privé indisponible")
        octets, type_mime = media
        if len(octets) > 10 * 1024 * 1024:
            raise HTTPException(404, "média privé indisponible")
        nom = "media-prepare.png" if type_mime == "image/png" else "media-prepare.jpg"
        disposition = "inline" if mode == "apercu" else "attachment"
        return Response(octets, media_type=type_mime, headers={
            "Cache-Control": "private, no-store, max-age=0",
            "Pragma": "no-cache",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": f'{disposition}; filename="{nom}"',
        })

    return router


def _entier_formulaire(valeur: Any, nom: str) -> int:
    if not isinstance(valeur, str) or not valeur.isascii() or not valeur.isdigit() or len(valeur) > 8:
        raise HTTPException(400, f"{nom} invalide")
    return int(valeur)


async def _multipart_media_borne(request: Request) -> FormData:
    if not request.headers.get("content-type", "").lower().startswith("multipart/form-data"):
        raise HTTPException(400, "un formulaire multipart est requis")
    entete = request.headers.get("content-length", "")
    if entete and (not entete.isascii() or not entete.isdigit() or len(entete) > 16):
        raise HTTPException(400, "longueur de requête invalide")
    if entete and int(entete) > _MAX_CORPS_MEDIA:
        raise HTTPException(413, "requête médias au-delà de la limite")

    async def flux_borne():
        taille = 0
        async for bloc in request.stream():
            taille += len(bloc)
            if taille > _MAX_CORPS_MEDIA:
                raise HTTPException(413, "requête médias au-delà de la limite")
            yield bloc

    try:
        parseur = MultiPartParser(
            request.headers, flux_borne(), max_files=1, max_fields=8, max_part_size=1024,
        )
        return await parseur.parse()
    except MultiPartException as exc:
        raise HTTPException(400, "formulaire médias invalide ou trop complexe") from exc


def _section_medias(
    prefixe: str, session: Session, contenu_id: str, dossier: Mapping[str, Any], creneau_id: str | None,
) -> list[str]:
    sources = dossier.get("sources", [])
    prepares = dossier.get("medias", [])
    par_source = {m.get("source_ref"): m for m in prepares if isinstance(m, Mapping)}
    resultat_html = [
        '<section class="carte medias-prives"><h4>Médias · revue humaine privée</h4>',
        '<p class="note">Les fichiers préparés sont fournis par un humain. OPSYS ne décode pas les images et '
        'ne supprime pas leurs métadonnées EXIF. Vérifiez manuellement visages, plaques, adresse et métadonnées '
        'avant d’approuver. Une approbation atteste cette revue humaine, pas une analyse automatique.</p>',
        f'<p class="note">Dossier : {pages.e(dossier.get("statut", "inconnu"))}, révision '
        f'{pages.e(dossier.get("revision", "—"))} · WCT {pages.e(dossier.get("wct_id", "—"))}</p>',
    ]
    for source in sources if isinstance(sources, list) else []:
        if not isinstance(source, Mapping):
            continue
        source_ref = source.get("source_ref")
        prepare = par_source.get(source_ref)
        resultat_html.extend(['<div class="media-paire">', '<h5>Source WCT</h5>'])
        if isinstance(source_ref, str):
            url_source = (
                f"{prefixe}/marketing/calendrier/medias/{quote(contenu_id, safe='')}?"
                f"reference={quote(source_ref, safe='')}&mode=apercu"
            )
            resultat_html.append(
                f'<a href="{pages.e(url_source)}">Ouvrir la source privée</a>'
                f'<img loading="lazy" alt="Source WCT privée" src="{pages.e(url_source)}">'
            )
        if isinstance(prepare, Mapping) and isinstance(prepare.get("prepared_ref"), str):
            prepare_ref = prepare["prepared_ref"]
            url_prepare = (
                f"{prefixe}/marketing/calendrier/medias/{quote(contenu_id, safe='')}?"
                f"reference={quote(prepare_ref, safe='')}&mode=apercu"
            )
            resultat_html.extend([
                '<h5>Préparé fourni par un humain</h5>',
                f'<a href="{pages.e(url_prepare)}">Ouvrir le préparé privé</a>'
                f'<img loading="lazy" alt="Préparé fourni par un humain" src="{pages.e(url_prepare)}">',
                f'<p class="note">Attestation de préparation : {pages.e(prepare.get("attestation_humaine", ""))}</p>',
            ])
        else:
            resultat_html.append(
                f'<form method="post" enctype="multipart/form-data" '
                f'action="{pages.e(prefixe)}/marketing/calendrier/medias" class="pile">'
                f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
                f'<input type="hidden" name="mutation_id" value="{pages.e(uuid.uuid4().hex)}">'
                f'<input type="hidden" name="contenu_id" value="{pages.e(contenu_id)}">'
                f'<input type="hidden" name="source_ref" value="{pages.e(source_ref)}">'
                f'<input type="hidden" name="revision_attendue" value="{pages.e(dossier.get("revision", 0))}">'
                f'<input type="hidden" name="empreinte_attendue" '
                f'value="{pages.e(dossier.get("empreinte_dossier", ""))}">'
                f'<input type="hidden" name="snapshot_attendu" value="{pages.e(dossier.get("snapshot_sha256", ""))}">'
                '<label>Fichier JPEG/PNG préparé par un humain<input type="file" name="fichier" '
                'accept="image/jpeg,image/png" required></label>'
                '<label>Attestation de préparation humaine (20 à 500 caractères)'
                '<input name="attestation_humaine" required maxlength="500"></label>'
                '<button type="submit">Ajouter au dossier privé</button></form>'
            )
        resultat_html.append('</div>')
    if sources and len(par_source) == len(sources) and dossier.get("statut") not in {"APPROUVE", "REMIS"}:
        resultat_html.append(
            '<form method="post" action="' + pages.e(prefixe) + '/marketing/calendrier" class="pile">'
            f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
            f'<input type="hidden" name="mutation_id" value="{pages.e(uuid.uuid4().hex)}">'
            '<input type="hidden" name="action" value="decider_medias">'
            f'<input type="hidden" name="contenu_id" value="{pages.e(contenu_id)}">'
            '<input type="hidden" name="decision" value="approuver">'
            f'<input type="hidden" name="revision_attendue" value="{pages.e(dossier.get("revision", 0))}">'
            f'<input type="hidden" name="empreinte_attendue" value="{pages.e(dossier.get("empreinte_dossier", ""))}">'
            f'<input type="hidden" name="snapshot_attendu" value="{pages.e(dossier.get("snapshot_sha256", ""))}">'
            '<label>Attestation de revue manuelle complète (visages, plaques, adresse, EXIF)'
            '<input name="attestation_humaine" required maxlength="500" minlength="20"></label>'
            '<button type="submit">Approuver le dossier médias</button></form>'
        )
    if dossier.get("statut") == "APPROUVE" and creneau_id is not None:
        resultat_html.append(
            '<form method="post" action="' + pages.e(prefixe) + '/marketing/calendrier" class="pile">'
            f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
            f'<input type="hidden" name="mutation_id" value="{pages.e(uuid.uuid4().hex)}">'
            '<input type="hidden" name="action" value="remettre_medias">'
            f'<input type="hidden" name="creneau_id" value="{pages.e(creneau_id)}">'
            '<button type="submit">Sceller la remise manuelle au propriétaire</button></form>'
        )
    if dossier.get("statut") == "REMIS":
        for media in prepares:
            if isinstance(media, Mapping) and isinstance(media.get("prepared_ref"), str):
                url = (
                    f"{prefixe}/marketing/calendrier/medias/{quote(contenu_id, safe='')}?"
                    f"reference={quote(media['prepared_ref'], safe='')}&mode=remise"
                )
                resultat_html.append(f'<a class="bouton" href="{pages.e(url)}">Remettre le préparé manuellement</a>')
    resultat_html.append('</section>')
    return resultat_html


def _refus(valeur: Any) -> str | None:
    if not isinstance(valeur, Mapping):
        return "Réponse métier invalide."
    if valeur.get("ok") is False:
        return str(valeur.get("details") or valeur.get("erreur") or "Action refusée.")
    if valeur.get("accepte") is False:
        verdict = valeur.get("verdict")
        return (
            str(verdict.get("detail", "Action métier refusée."))
            if isinstance(verdict, Mapping)
            else "Action métier refusée."
        )
    if valeur.get("statut") in {"echec", "refusee"}:
        return "La demande a été approuvée, mais le service a refusé l’action."
    if valeur.get("statut") in {
        "consentement_retire",
        "nature_inconnue",
        "profil_marque_non_configure",
        "wct_inconnu",
    }:
        return str(valeur.get("motif") or "Action métier refusée.")
    for cle in ("resultat", "reponse"):
        if cle in valeur:
            refus = _refus(valeur[cle])
            if refus:
                return refus
    return None


def _commande(corps: Mapping[str, Any], *, formulaire: bool) -> dict[str, Any]:
    allowed = {"action", "mutation_id", "csrf"} if formulaire else {"action", "mutation_id"}
    action = corps.get("action")
    if not isinstance(action, str) or action not in _ACTIONS:
        raise HTTPException(400, "action calendrier inconnue")
    schemas = {
        "reviser_texte": ({"contenu_id", "revision_attendue", "empreinte_texte_attendue", "snapshot_attendu", "texte"},
                          "m7_reviser_texte_humain"),
        "proposer_contenus": ({"wct_id"}, "m7_proposer_contenus_chantier"),
        "decider_contenu": ({"contenu_id", "decision", "motif"}, "m7_decider_contenu"),
        "proposer_creneau": ({"contenu_id", "planifie_le"}, "m7_proposer_creneau_calendrier"),
        "decider_creneau": ({"creneau_id", "decision", "motif"}, "m7_decider_creneau_calendrier"),
        "exporter_creneau": ({"creneau_id"}, "m7_exporter_creneau_manuel"),
        "decider_medias": ({"contenu_id", "decision", "revision_attendue", "empreinte_attendue",
                            "snapshot_attendu", "attestation_humaine"}, "m7_decider_dossier_medias"),
        "remettre_medias": ({"creneau_id"}, "m7_remettre_dossier_medias_manuel"),
    }
    optional, outil = schemas[action]
    champs_requis = {
        "reviser_texte": {"contenu_id", "revision_attendue", "empreinte_texte_attendue", "snapshot_attendu", "texte"},
        "proposer_contenus": {"wct_id"},
        "decider_contenu": {"contenu_id", "decision"},
        "proposer_creneau": {"contenu_id", "planifie_le"},
        "decider_creneau": {"creneau_id", "decision"},
        "exporter_creneau": {"creneau_id"},
        "decider_medias": {"contenu_id", "decision", "revision_attendue", "empreinte_attendue",
                           "snapshot_attendu", "attestation_humaine"},
        "remettre_medias": {"creneau_id"},
    }[action]
    champs_attendus = allowed | champs_requis | (optional - champs_requis)
    if set(corps) - champs_attendus or not champs_attendus.issuperset(set(corps)):
        raise HTTPException(400, "champs de commande invalides")
    mutation_id = _texte(corps, "mutation_id", maximum=_MAX_ID)
    arguments: dict[str, Any] = {}
    champs_texte = champs_requis - {"decision", "planifie_le"}
    if action in {"decider_medias", "reviser_texte"}:
        champs_texte = champs_texte - {"revision_attendue"}
    for cle in champs_texte:
        arguments[cle] = _texte(corps, cle, maximum=2000 if cle == "texte" else _MAX_ID)
    if "decision" in champs_requis:
        decision = _texte(corps, "decision", maximum=20)
        if decision not in _DECISIONS:
            raise HTTPException(400, "decision invalide")
        arguments["decision"] = decision
    if action in {"decider_medias", "reviser_texte"}:
        arguments["revision_attendue"] = _entier_commande(corps.get("revision_attendue"))
        for cle in (("empreinte_texte_attendue", "snapshot_attendu") if action == "reviser_texte"
                    else ("empreinte_attendue", "snapshot_attendu")):
            empreinte = _texte(corps, cle, maximum=64)
            if len(empreinte) != 64 or any(c not in "0123456789abcdef" for c in empreinte):
                raise HTTPException(400, f"{cle} invalide")
            arguments[cle] = empreinte
        if action == "decider_medias":
            arguments["attestation_humaine"] = _texte(corps, "attestation_humaine", maximum=500)
    if "motif" in corps:
        motif = corps["motif"]
        if not isinstance(motif, str) or len(motif) > _MAX_MOTIF:
            raise HTTPException(400, "motif invalide")
        if motif.strip():
            arguments["motif"] = motif.strip()
    if action == "proposer_creneau":
        arguments["planifie_le"] = _planification(_texte(corps, "planifie_le", maximum=40))
    return {"outil": outil, "arguments": arguments, "mutation_id": mutation_id}


def _texte(corps: Mapping[str, Any], cle: str, *, maximum: int = _MAX_ID) -> str:
    valeur = corps.get(cle)
    if not isinstance(valeur, str) or not valeur.strip() or len(valeur) > maximum:
        raise HTTPException(400, f"{cle} invalide")
    return valeur.strip()


def _entier_commande(valeur: Any) -> int:
    if type(valeur) is int and valeur >= 0:
        return valeur
    if isinstance(valeur, str) and valeur.isascii() and valeur.isdigit() and len(valeur) <= 8:
        return int(valeur)
    raise HTTPException(400, "revision_attendue invalide")


def _planification(valeur: str) -> str:
    try:
        date = datetime.fromisoformat(valeur.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(400, "planifie_le doit être une date ISO 8601 avec fuseau") from exc
    if date.tzinfo is None or date.utcoffset() is None:
        raise HTTPException(400, "planifie_le doit inclure un fuseau horaire")
    offset = date.utcoffset()
    if offset is None or offset < -timedelta(hours=12) or offset > timedelta(hours=14):
        raise HTTPException(400, "fuseau horaire hors limites")
    maintenant = datetime.now(UTC)
    date_utc = date.astimezone(UTC)
    if date_utc <= maintenant or date_utc > maintenant + _MAX_PLANIFICATION:
        raise HTTPException(400, "planifie_le doit être futur et à moins de 365 jours")
    return valeur


def _decalage(query: Mapping[str, str]) -> int:
    elements = getattr(query, "multi_items", None)
    if callable(elements):
        couples = list(elements())
        if len(couples) != len({cle for cle, _ in couples}):
            raise HTTPException(400, "paramètre répété")
    if set(query) - {"decalage"}:
        raise HTTPException(400, "paramètre de lecture inconnu")
    valeur = query.get("decalage", "0")
    if not valeur.isascii() or not valeur.isdigit() or len(valeur) > 7 or int(valeur) > 1_000_000:
        raise HTTPException(400, "decalage invalide")
    return int(valeur)


def _csrf_formulaire(champs: Mapping[str, Any], session: Session) -> None:
    if not isinstance(champs, Mapping) or not securite.csrf_valide(champs.get("csrf"), session):
        raise HTTPException(403, "jeton CSRF absent ou invalide")


def _formulaire(
    prefixe: str,
    session: Session,
    action: str,
    arguments: Mapping[str, str],
    libelle: str,
    *,
    motif: bool = False,
    date: bool = False,
) -> str:
    champs = [
        f'<form method="post" action="{pages.e(prefixe)}/marketing/calendrier" class="inline-form">',
        f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">',
        f'<input type="hidden" name="mutation_id" value="{uuid.uuid4().hex}">',
        f'<input type="hidden" name="action" value="{pages.e(action)}">',
    ]
    champs.extend(
        f'<input type="hidden" name="{pages.e(cle)}" value="{pages.e(valeur)}">'
        for cle, valeur in arguments.items()
    )
    if date:
        champs.append(
            '<label>Heure locale ISO 8601 avec fuseau<input name="planifie_le" required maxlength="40" '
            'placeholder="2026-10-04T18:30:00-04:00"></label>'
        )
    if motif:
        champs.append('<label>Motif du rejet<input name="motif" maxlength="500"></label>')
    champs.append(f'<button type="submit">{pages.e(libelle)}</button></form>')
    return "".join(champs)


def _pagination(prefixe: str, liste: Mapping[str, Any]) -> str:
    liens = []
    suivant = liste.get("suivant")
    if type(suivant) is int:
        liens.append(f'<a href="{pages.e(prefixe)}/marketing/calendrier?decalage={suivant}">Suivant</a>')
    return f'<nav aria-label="Pages de contenus">{" · ".join(liens)}</nav>' if liens else ""


def _paquet_html(paquet: Mapping[str, Any]) -> str:
    """Rend uniquement les champs utiles au propriétaire pour sa remise manuelle."""
    preuve_marque = paquet.get("marque_source")
    marque_html = ""
    if isinstance(preuve_marque, Mapping):
        marque_html = (
            f'<p class="note">Marque de ce paquet : {pages.e(preuve_marque.get("source", "—"))} · '
            f'révision {pages.e(preuve_marque.get("revision", "—"))} · '
            f'empreinte {pages.e(preuve_marque.get("sha256", "—"))}</p>'
        )
    texte = paquet.get("texte_a_copier")
    if not isinstance(texte, str):
        return (
            '<section class="carte"><p role="alert">Paquet manuel illisible; '
            "vérifiez les approbations.</p></section>"
        )
    sections = [
        '<section class="carte paquet-manuel"><h2>Paquet remis pour copie manuelle</h2>',
        marque_html,
        f'<p>{pages.e(paquet.get("libelle", paquet.get("plateforme", "Contenu")))} · '
        f'Approuvé par {pages.e(paquet.get("approuve_par", "—"))} le '
        f'{pages.e(paquet.get("approuve_le", "—"))}</p>',
        '<h3>Texte complet à copier</h3>',
        f'<pre>{pages.e(texte)}</pre>',
    ]
    medias = paquet.get("medias")
    if isinstance(medias, list) and medias:
        sections.append('<h3>Médias à préparer</h3><ul>')
        for media in medias:
            if isinstance(media, Mapping):
                sections.append(
                    f'<li>{pages.e(media.get("reference", "Référence absente"))} · '
                    f'{pages.e(media.get("instruction", "Vérification manuelle requise"))}</li>'
                )
        sections.append("</ul>")
    instructions = paquet.get("instructions")
    if isinstance(instructions, list) and instructions:
        sections.append('<h3>Étapes sur la plateforme officielle</h3><ul>')
        sections.extend(f"<li>{pages.e(item)}</li>" for item in instructions if isinstance(item, str))
        sections.append("</ul>")
    sections.append(
        f'<p class="message message-alerte">{pages.e(paquet.get("publication", "Remise manuelle seulement."))}</p>'
        "</section>"
    )
    return "".join(sections)


def _formulaire_edition_texte(prefixe: str, session: Session, edition: Mapping[str, Any]) -> str:
    provenance = edition.get("edition_humaine")
    note = ""
    if isinstance(provenance, Mapping):
        note = (f'<p class="note">Dernière correction : {pages.e(provenance.get("par", "—"))} · '
                f'{pages.e(provenance.get("horodatage", "—"))}</p>')
    champs = {
        "action": "reviser_texte",
        "csrf": session.csrf,
        "mutation_id": str(uuid.uuid4()),
        "contenu_id": edition["contenu_id"],
        "revision_attendue": edition["revision"],
        "empreinte_texte_attendue": edition["empreinte_texte"],
        "snapshot_attendu": edition["snapshot_sha256"],
    }
    return (
        "<details><summary>Modifier le texte</summary><p>La correction conserve une nouvelle version "
        "à approuver de nouveau. Les autres plateformes restent inchangées.</p>"
        + note
        + f'<form method="post" action="{pages.e(prefixe)}/marketing/calendrier" class="pile">'
        + "".join(f'<input type="hidden" name="{pages.e(k)}" value="{pages.e(v)}">' for k, v in champs.items())
        + f"<label>Texte (plafond interne : {pages.e(edition['longueur_max'])} caractères)"
        f'<textarea name="texte" required maxlength="{pages.e(edition["longueur_max"])}">'
        f"{pages.e(edition['texte'])}</textarea></label>"
        '<button type="submit">Enregistrer une nouvelle version</button></form></details>'
    )
