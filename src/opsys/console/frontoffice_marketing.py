"""Écrans métier authentifiés M1 (réception) et M7 (réputation)."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import quote, urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from .. import stockage, tableau_de_bord
from . import metier, pages, securite
from .securite import Session

_APPELS = {
    "source", "evenement_id", "appel_id", "recu_le", "telephone", "statut",
    "transcription", "consentement_enregistrement",
}
_AVIS = {"plateforme", "avis_source_id", "date_avis", "note", "texte", "source_url"}
_STATUTS_AVIS = {
    "PROPOSE": "À réviser",
    "APPROUVE": "Approuvé par le propriétaire",
    "APPROUVE_PRIVE": "Traitement privé approuvé",
    "REJETE": "À corriger",
    "EXPORTE_MANUEL": "Paquet copié manuellement",
}
_CATEGORIES_AVIS = {"litige": "Plainte", "urgence": "Urgence", "eloge": "Éloge", "neutre": "Avis"}
_ETATS_TRANSFERT = {
    "plainte": "Plainte",
    "plainte_escaladee": "Plainte",
    "urgence": "Urgence",
    "urgence_escaladee": "Urgence",
    "ventes": "Rappel",
    "transfert_humain": "À traiter",
    "general": "À traiter",
}


def creer_router(
    *,
    session_page: Callable[..., Session],
    session_api: Callable[..., Session],
    ecriture_api: Callable[[Request], Session],
    _formulaire: Callable[[Request], Any],
    _objet_json: Callable[[Request], Any],
    cnx_factory: Callable[[], Any],
    deps: Mapping[str, Any],
    prefixe: str,
) -> APIRouter:
    """Construit les pages de réception/réputation et leurs alias JSON protégés."""
    router = APIRouter()

    def appeler(session: Session, nom: str, arguments: Mapping[str, Any], mutation_id: str | None = None):
        with cnx_factory() as cnx:
            return metier.executer(cnx, deps, session, nom, arguments, mutation_id=mutation_id)

    def reception_donnees(session: Session) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        with cnx_factory() as cnx:
            file = tableau_de_bord.file_proprietaire(cnx, deps)
            maillons = list(stockage.maillons("m01-front-office", "principal"))
        attentes = [
            item for item in file
            if item.get("departement") == "m01-front-office"
            and item.get("type") in {"transfert_humain", "plainte_escaladee", "urgence_escaladee"}
        ]
        appels = [item for item in maillons if item.get("type_entree") == "appel_importe"][-20:][::-1]
        return attentes, appels

    def lister_avis(session: Session) -> list[dict[str, Any]]:
        reponse = appeler(session, "m7_lister_inbox_reputation", {"limite": 100})
        ok, charge, erreur = resultat_metier(reponse)
        if not ok:
            raise HTTPException(409, erreur["message"])
        return charge.get("avis", []) if isinstance(charge, Mapping) else []

    def csrf_formulaire(champs: Mapping[str, Any], session: Session) -> None:
        if not securite.csrf_valide(champs.get("csrf"), session):
            raise HTTPException(403, "jeton CSRF absent ou invalide : rechargez la page")

    def erreur_http(exc: Exception) -> int:
        if isinstance(exc, PermissionError):
            return 403
        if isinstance(exc, KeyError):
            return 404
        if "conflit" in str(exc).lower() or "contradictoire" in str(exc).lower():
            return 409
        return 400

    def erreur_api(exc: Exception) -> JSONResponse:
        code = "CONFLIT" if erreur_http(exc) == 409 else "ACTION-INVALIDE"
        return JSONResponse({"ok": False, "erreur": {"code": code, "message": str(exc)}},
                            status_code=erreur_http(exc))

    def page_reception(
        session: Session,
        *,
        bandeau: pages.Bandeau | None = None,
        saisie: Mapping[str, Any] | None = None,
    ) -> HTMLResponse:
        attentes, appels = reception_donnees(session)
        contenu = [
            f'<p><a class="bouton" href="{pages.e(prefixe)}/reception/voicemail">'
            'Importer un message vocal</a></p>',
            f'<p><a class="bouton" href="{pages.e(prefixe)}/reception/digest">'
            'Résumé de réception</a></p>',
            '<section class="carte"><h2>À prendre en charge</h2>',
        ]
        if not attentes:
            contenu.append('<p class="vide">Aucun transfert humain M1 en attente.</p>')
        else:
            contenu.append('<ul class="liste-cartes">')
            for item in attentes:
                ident = str(item.get("id", ""))
                kind = _ETATS_TRANSFERT.get(str(item.get("type", "")), "À traiter")
                contenu.append(
                    '<li class="carte">'
                    f'<p><strong>{pages.e(kind)}</strong> · {pages.e(item.get("niveau", ""))}</p>'
                    f'<p>{pages.e(item.get("resume", ""))}</p>'
                    f'<p class="note">Reçu le {pages.e(item.get("depuis", "—"))}</p>'
                    f'<a class="bouton" href="{pages.e(prefixe)}/reception/transferts/{quote(ident, safe="")}">'
                    'Lire le dossier</a></li>'
                )
            contenu.append("</ul>")
        contenu.append("</section>")

        contenu.append('<section class="carte"><h2>Appels importés récemment</h2>')
        if not appels:
            contenu.append('<p class="vide">Aucun appel importé.</p>')
        else:
            contenu.append('<div class="table-defilante"><table><thead><tr>'
                           '<th>Source consultée</th><th>Référence</th><th>Statut</th><th>Reçu le</th>'
                           '</tr></thead><tbody>')
            for appel in appels:
                contenu.append(
                    "<tr>"
                    f"<td>{pages.e(appel.get('source', ''))}</td>"
                    f"<td>{pages.e(appel.get('appel_id', ''))}</td>"
                    f"<td>{pages.e('Appel manqué' if appel.get('statut') == 'manque' else 'Message vocal')}</td>"
                    f"<td>{pages.e(appel.get('horodatage', ''))}</td></tr>"
                )
            contenu.append("</tbody></table></div>")
        contenu.append("</section>")

        valeurs = saisie or {}
        contenu.extend([
            '<section class="carte"><h2>Importer un appel consulté manuellement</h2>',
            '<p>Recopiez un événement provenant d’un journal ou d’un export que vous avez consulté. '
            'Aucun appel ni message ne sera envoyé.</p>',
            f'<form method="post" action="{pages.e(prefixe)}/reception/appels" class="pile">',
            f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">',
            f'<input type="hidden" name="mutation_id" value="{pages.e(valeurs.get("mutation_id") or uuid.uuid4())}">',
            '<label>Source consultée<input name="source" required maxlength="120" autocomplete="off" '
            f'value="{pages.e(valeurs.get("source", ""))}"></label>',
            '<label>Identifiant de l’événement<input name="evenement_id" required maxlength="200" '
            f'value="{pages.e(valeurs.get("evenement_id", ""))}"></label>',
            '<label>Référence de l’appel<input name="appel_id" required maxlength="200" '
            f'value="{pages.e(valeurs.get("appel_id", ""))}"></label>',
            '<label>Reçu le (heure inscrite dans la source)<input name="recu_le" required '
            'placeholder="2026-09-30T09:15:00-04:00"></label>',
            '<label>Téléphone<input name="telephone" type="tel" required autocomplete="tel" '
            'placeholder="+15145550142"></label>',
            '<label>Événement<select name="statut" required><option value="manque">Appel manqué</option>'
            '<option value="voicemail">Message vocal reçu</option></select></label>',
            '<label>Transcription (facultative)<textarea name="transcription" maxlength="5000"></textarea></label>',
            '<label class="choix"><input type="checkbox" name="consentement_enregistrement" '
            'value="accorde">Consentement explicite à conserver le texte du message vocal</label>',
            '<button type="submit" class="principal">Enregistrer l’import</button></form>',
            '<p class="note">L’import est manuel. Aucun service téléphonique n’est connecté.</p></section>',
        ])
        return _html(prefixe, "Réception", "reception", "Réception", "".join(contenu), session, bandeau)

    def page_marketing(
        session: Session,
        *,
        bandeau: pages.Bandeau | None = None,
        erreur: str | None = None,
    ) -> HTMLResponse:
        avis = lister_avis(session)
        contenu = [
            f'<p><a class="bouton" href="{pages.e(prefixe)}/marketing/calendrier">'
            'Contenus et calendrier</a></p>',
            f'<p><a class="bouton" href="{pages.e(prefixe)}/marketing/performance">'
            'Performance observée</a></p>',
            f'<p><a class="bouton" href="{pages.e(prefixe)}/marketing/growth">'
            'Observations Growth</a></p>',
            f'<p><a class="bouton" href="{pages.e(prefixe)}/marketing/cmo">'
            'Plan CMO préparatoire</a></p>',
            f'<p><a class="bouton" href="{pages.e(prefixe)}/marketing/marque">'
            'Profil de marque</a></p>',
            '<section class="carte"><h2>Importer un avis consulté manuellement</h2>',
            '<p>La référence et le texte sont saisis depuis la source consultée. L’import ne publie rien.</p>',
            f'<form method="post" action="{pages.e(prefixe)}/marketing" class="pile">',
            f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">',
            '<input type="hidden" name="action" value="importer">',
            f'<input type="hidden" name="mutation_id" value="{uuid.uuid4()}">',
            '<label>Plateforme consultée<select name="plateforme" required>'
            '<option value="google_business_profile">Google Business Profile</option>'
            '<option value="facebook">Facebook</option><option value="autre">Autre</option></select></label>',
            '<label>Identifiant de l’avis<input name="avis_source_id" required maxlength="200"></label>',
            '<label>Date de l’avis<input name="date_avis" type="date" required></label>',
            '<label>Note<select name="note" required><option value="5">5 — très satisfait</option>'
            '<option value="4">4</option><option value="3">3</option><option value="2">2</option>'
            '<option value="1">1 — insatisfait</option></select></label>',
            '<label>Texte de l’avis<textarea name="texte" required maxlength="5000"></textarea></label>',
            '<label>Adresse HTTPS de référence<input name="source_url" type="url" required maxlength="2000" '
            'placeholder="https://…"></label>',
            '<button type="submit" class="principal">Importer l’avis</button></form>',
            '<p class="note">Les plaintes et urgences restent privées. Toute réponse approuvée est exportée '
            'pour copie manuelle; aucune publication automatique n’a lieu.</p></section>',
            '<section class="carte"><h2>Inbox de réputation</h2>',
        ]
        if erreur:
            contenu.append(f'<p class="message message-erreur" role="alert">{pages.e(erreur)}</p>')
        if not avis:
            contenu.append('<p class="vide">Aucun avis importé.</p>')
        for item in avis:
            avis_id = str(item.get("avis_id", ""))
            categorie = _CATEGORIES_AVIS.get(str(item.get("categorie", "")), "Avis")
            statut = _STATUTS_AVIS.get(str(item.get("statut", "")), "À vérifier")
            source_url = _url_http(item.get("source_url"))
            contenu.extend([
                '<article class="carte avis">',
                f'<header><h3>{pages.e(categorie)}</h3><span>{pages.e(item.get("note", "—"))}/5</span></header>',
                f'<p>{pages.e(item.get("texte", ""))}</p>',
                f'<p class="note">{pages.e(item.get("plateforme", ""))} · '
                f'{pages.e(item.get("date_avis", ""))} · {pages.e(statut)}</p>',
            ])
            if source_url:
                contenu.append(
                    f'<p><a href="{pages.e(source_url)}" rel="noreferrer">'
                    "Voir la référence consultée</a></p>"
                )
            prive = item.get("visibilite") == "privee"
            if prive:
                contenu.append(
                    '<p class="message message-alerte">Ce dossier reste privé; '
                    'aucune réponse publique ni export n’est permis.</p>'
                )
            reponse = item.get("reponse_texte")
            if reponse and not prive:
                contenu.append(f'<div class="reponse"><h4>Brouillon de réponse</h4><p>{pages.e(reponse)}</p></div>')
            if item.get("statut") == "PROPOSE" and not prive:
                contenu.extend([
                    '<div class="actions-avis">',
                    _form_avis(prefixe, session, avis_id, "approuver", "Approuver la réponse"),
                    _form_avis(prefixe, session, avis_id, "rejeter", "Demander une correction", motif=True),
                    "</div>",
                ])
            elif item.get("statut") == "APPROUVE":
                contenu.append(_form_avis(prefixe, session, avis_id, "exporter", "Préparer le paquet à copier"))
            contenu.append("</article>")
        contenu.append("</section>")
        return _html(prefixe, "Marketing et réputation", "marketing", "Marketing et réputation", "".join(contenu),
                     session, bandeau)

    def page_transfert(session: Session, transfert_id: str) -> HTMLResponse:
        reponse = appeler(session, "m1_lire_transfert", {"transfert_id": transfert_id})
        ok, charge, erreur = resultat_metier(reponse)
        if not ok or not isinstance(charge, Mapping):
            raise HTTPException(404 if erreur.get("code") == "REJ-TRANSFERT-INCONNU" else 409,
                                erreur["message"])
        contenu = [
            '<p><a href="' + pages.e(prefixe) + '/reception">Retour à la réception</a></p>',
            '<section class="carte">',
            f'<p>{pages.e(_ETATS_TRANSFERT.get(str(charge.get("type_transfert")), "Dossier"))} · '
            f'{pages.e(charge.get("statut", ""))}</p>',
            f'<h2>{pages.e(charge.get("resume", "Dossier de suivi"))}</h2>',
            f'<p class="note">Ouvert le {pages.e(charge.get("ouvert_le", ""))} · '
            f'{pages.e(charge.get("destinataire") or "Destinataire à configurer")}</p>',
        ]
        contact = charge.get("contact")
        if isinstance(contact, Mapping):
            contenu.append("<dl>")
            for cle, valeur in contact.items():
                contenu.append(f"<dt>{pages.e(cle.replace('_', ' ').capitalize())}</dt><dd>{pages.e(valeur)}</dd>")
            contenu.append("</dl>")
        for titre, cle in (("Messages reçus", "messages_couverts"), ("Messages suivants", "messages_suivants")):
            messages = charge.get(cle, [])
            if messages:
                contenu.append(f"<h3>{titre}</h3><ol>")
                for message in messages:
                    contenu.append(f'<li><p class="note">{pages.e(message.get("recu_le", ""))}</p>'
                                   f'<blockquote>{pages.e(message.get("texte", ""))}</blockquote></li>')
                contenu.append("</ol>")
        if charge.get("statut") == "ouvert":
            contenu.extend([
                f'<form method="post" action="{pages.e(prefixe)}/reception/transferts/'
                f'{quote(transfert_id, safe="")}/clore" '
                'class="pile">',
                f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">',
                f'<input type="hidden" name="mutation_id" value="{uuid.uuid4()}">',
                '<label>Note de prise en charge<input name="motif" required minlength="10" maxlength="500"></label>',
                '<button type="submit">Clore le transfert</button></form>',
            ])
        else:
            contenu.append('<p class="message message-ok">Ce dossier est clos.</p>')
        contenu.append("</section>")
        return _html(prefixe, "Dossier de réception", "reception", "Dossier de réception", "".join(contenu), session)

    @router.get("/reception", response_class=HTMLResponse)
    def reception(request: Request) -> Response:
        return page_reception(session_page(request))

    @router.post("/reception/appels")
    async def importer_appel_formulaire(request: Request) -> Response:
        session = session_page(request)
        champs = await _formulaire(request)
        csrf_formulaire(champs, session)
        if set(champs) - (_APPELS | {"csrf", "mutation_id"}):
            raise HTTPException(400, "champs de l’import invalides")
        try:
            _mutation_id(champs.get("mutation_id"))
            arguments = _arguments_appel(champs)
            reponse = appeler(session, "m1_importer_appel_manuellement", arguments,
                              mutation_id=champs["mutation_id"])
            ok, _charge, erreur = resultat_metier(reponse)
        except (ValueError, KeyError, PermissionError) as exc:
            return page_reception(session, bandeau=(f"Import refusé : {exc}", "erreur"), saisie=champs)
        if not ok:
            return page_reception(session, bandeau=(f"Import refusé : {erreur['message']}", "erreur"), saisie=champs)
        return RedirectResponse(f"{prefixe}/reception?ok=appel", status_code=303)

    @router.get("/reception/transferts/{transfert_id}", response_class=HTMLResponse)
    def lire_transfert_page(transfert_id: str, request: Request) -> Response:
        return page_transfert(session_page(request), transfert_id)

    @router.post("/reception/transferts/{transfert_id}/clore")
    async def clore_transfert_formulaire(transfert_id: str, request: Request) -> Response:
        session = session_page(request)
        champs = await _formulaire(request)
        csrf_formulaire(champs, session)
        if set(champs) - {"csrf", "mutation_id", "motif"}:
            raise HTTPException(400, "champs de clôture invalides")
        try:
            _mutation_id(champs.get("mutation_id"))
            reponse = appeler(session, "m1_clore_transfert",
                              {"transfert_id": transfert_id, "motif": champs.get("motif", "")},
                              mutation_id=champs["mutation_id"])
            ok, _charge, erreur = resultat_metier(reponse)
        except (ValueError, KeyError, PermissionError) as exc:
            raise HTTPException(erreur_http(exc), str(exc)) from exc
        if not ok:
            raise HTTPException(409, erreur["message"])
        return RedirectResponse(f"{prefixe}/reception", status_code=303)

    @router.get("/marketing", response_class=HTMLResponse)
    def marketing(request: Request) -> Response:
        return page_marketing(session_page(request))

    @router.post("/marketing")
    async def marketing_formulaire(request: Request) -> Response:
        session = session_page(request)
        champs = await _formulaire(request)
        csrf_formulaire(champs, session)
        action = champs.get("action", "importer")
        try:
            _mutation_id(champs.get("mutation_id"))
            if action == "importer":
                if set(champs) - (_AVIS | {"csrf", "mutation_id", "action"}):
                    raise ValueError("champs de l’avis invalides")
                reponse = appeler(session, "m7_importer_avis_manuel", _arguments_avis(champs),
                                  mutation_id=champs["mutation_id"])
            elif action in {"approuver", "rejeter", "exporter"}:
                reponse = appeler(session, *_commande_avis(champs), mutation_id=champs["mutation_id"])
            else:
                raise ValueError("action de réputation inconnue")
            ok, _charge, erreur = resultat_metier(reponse)
        except (ValueError, KeyError, PermissionError) as exc:
            return page_marketing(session, erreur=str(exc))
        if not ok:
            return page_marketing(session, erreur=erreur["message"])
        return RedirectResponse(f"{prefixe}/marketing?ok=action", status_code=303)

    @router.get("/api/reception/appels")
    def api_lister_appels(request: Request) -> dict[str, Any]:
        session = session_api(request)
        attentes, appels = reception_donnees(session)
        return {"attentes": attentes, "appels": [_appel_public(item) for item in appels]}

    @router.post("/api/reception/appels")
    async def api_importer_appel(request: Request) -> Response:
        session = ecriture_api(request)
        corps = await _objet_json(request)
        try:
            mutation_id = _mutation_id(corps.get("mutation_id"))
            arguments = _arguments_appel(corps)
            if set(corps) - (_APPELS | {"mutation_id"}):
                raise ValueError("champs de l’import invalides")
            reponse = appeler(session, "m1_importer_appel_manuellement", arguments, mutation_id=mutation_id)
            return _api_resultat(reponse)
        except (ValueError, KeyError, PermissionError) as exc:
            return erreur_api(exc)

    @router.get("/api/reception/transferts")
    def api_lire_transfert(transfert_id: str, request: Request) -> Response:
        session = session_api(request)
        try:
            reponse = appeler(session, "m1_lire_transfert", {"transfert_id": transfert_id})
            return _api_resultat(reponse)
        except (ValueError, KeyError, PermissionError) as exc:
            return erreur_api(exc)

    @router.post("/api/reception/transferts")
    async def api_clore_transfert(request: Request) -> Response:
        session = ecriture_api(request)
        corps = await _objet_json(request)
        if set(corps) != {"transfert_id", "motif", "mutation_id"}:
            return JSONResponse(
                {
                    "ok": False,
                    "erreur": {
                        "code": "CHAMPS-INVALIDES",
                        "message": "Identifiant, motif et clé de reprise requis.",
                    },
                },
                status_code=400,
            )
        try:
            mutation_id = _mutation_id(corps["mutation_id"])
            reponse = appeler(session, "m1_clore_transfert",
                              {"transfert_id": corps["transfert_id"], "motif": corps["motif"]},
                              mutation_id=mutation_id)
            return _api_resultat(reponse)
        except (ValueError, KeyError, PermissionError) as exc:
            return erreur_api(exc)

    @router.get("/api/marketing/avis")
    def api_lister_avis(request: Request) -> dict[str, Any]:
        return {"avis": lister_avis(session_api(request))}

    @router.post("/api/marketing/avis")
    async def api_action_avis(request: Request) -> Response:
        session = ecriture_api(request)
        corps = await _objet_json(request)
        action = corps.get("action", "importer")
        try:
            mutation_id = _mutation_id(corps.get("mutation_id"))
            if action == "importer":
                if set(corps) - (_AVIS | {"mutation_id", "action"}):
                    raise ValueError("champs de l’avis invalides")
                nom, arguments = "m7_importer_avis_manuel", _arguments_avis(corps)
            else:
                nom, arguments = _commande_avis(corps)
            return _api_resultat(appeler(session, nom, arguments, mutation_id=mutation_id))
        except (ValueError, KeyError, PermissionError) as exc:
            return erreur_api(exc)

    return router


def resultat_metier(reponse: Any) -> tuple[bool, Any, dict[str, str]]:
    """Déplie uniquement l’enveloppe de capacité et détecte les refus métier imbriqués."""
    refus = _trouver_refus(reponse)
    if refus is not None:
        return False, None, refus
    charge = reponse
    if isinstance(charge, Mapping) and charge.get("ok") is True:
        charge = charge.get("resultat")
    if isinstance(charge, Mapping) and "resultat" in charge:
        charge = charge["resultat"]
    return True, charge, {"code": "", "message": ""}


def _trouver_refus(valeur: Any) -> dict[str, str] | None:
    if not isinstance(valeur, Mapping):
        return {"code": "REPONSE-INVALIDE", "message": "La réponse du service est illisible."}
    if valeur.get("ok") is False:
        details = str(valeur.get("details") or valeur.get("erreur") or "Action métier refusée.")
        return {"code": str(valeur.get("erreur", "ACTION-REFUSEE")), "message": details}
    if valeur.get("accepte") is False:
        verdict = valeur.get("verdict")
        if isinstance(verdict, Mapping):
            return {"code": str(verdict.get("code", "ACTION-REFUSEE")),
                    "message": str(verdict.get("detail", "La demande a été refusée."))}
        return {"code": "ACTION-REFUSEE", "message": "La demande a été refusée."}
    if valeur.get("statut") in {"echec", "refusee"}:
        return {"code": "ACTION-REFUSEE", "message": "La demande n’a pas été exécutée."}
    for cle in ("resultat", "reponse"):
        if cle in valeur:
            refus = _trouver_refus(valeur[cle])
            if refus is not None:
                return refus
    return None


def _arguments_appel(champs: Mapping[str, Any]) -> dict[str, Any]:
    arguments: dict[str, Any] = {}
    for cle in ("source", "evenement_id", "appel_id", "recu_le", "telephone", "statut"):
        valeur = champs.get(cle)
        if not isinstance(valeur, str) or not valeur.strip():
            raise ValueError(f"Le champ « {cle.replace('_', ' ')} » est requis.")
        arguments[cle] = valeur.strip()
    transcription = champs.get("transcription")
    if isinstance(transcription, str) and transcription.strip():
        arguments["transcription"] = transcription.strip()
    consentement = champs.get("consentement_enregistrement")
    if consentement not in (None, "", "accorde"):
        raise ValueError("Le consentement doit être explicite.")
    if consentement == "accorde":
        arguments["consentement_enregistrement"] = consentement
    return arguments


def _arguments_avis(champs: Mapping[str, Any]) -> dict[str, Any]:
    arguments = {cle: champs.get(cle) for cle in _AVIS}
    if not isinstance(arguments["note"], str):
        # JSON note is numeric; form note is text. Both enter the canonical tool as an integer.
        if type(arguments["note"]) is not int:
            raise ValueError("La note doit être un entier de 1 à 5.")
    else:
        try:
            arguments["note"] = int(arguments["note"])
        except ValueError as exc:
            raise ValueError("La note doit être un entier de 1 à 5.") from exc
    for cle in _AVIS - {"note"}:
        if not isinstance(arguments[cle], str) or not arguments[cle].strip():
            raise ValueError(f"Le champ « {cle.replace('_', ' ')} » est requis.")
        arguments[cle] = arguments[cle].strip()
    return arguments


def _commande_avis(champs: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
    action = champs.get("action")
    avis_id = champs.get("avis_id")
    if not isinstance(avis_id, str) or not avis_id.strip():
        raise ValueError("L’avis ciblé est requis.")
    if action in {"approuver", "rejeter"}:
        allowed = {"action", "avis_id", "motif", "csrf", "mutation_id"}
        if set(champs) - allowed:
            raise ValueError("Champs de décision invalides.")
        arguments = {"avis_id": avis_id.strip(), "decision": action}
        motif = champs.get("motif")
        if motif:
            if not isinstance(motif, str):
                raise ValueError("Le motif doit être un texte.")
            arguments["motif"] = motif.strip()
        return "m7_decider_reponse_avis", arguments
    if action == "exporter":
        if set(champs) - {"action", "avis_id", "csrf", "mutation_id"}:
            raise ValueError("Champs d’export invalides.")
        return "m7_exporter_reponse_avis_manuel", {"avis_id": avis_id.strip()}
    raise ValueError("Action de réputation inconnue.")


def _mutation_id(valeur: Any) -> str:
    if not isinstance(valeur, str) or not 1 <= len(valeur) <= 200 or not valeur.strip():
        raise ValueError("Clé de reprise absente ou invalide.")
    return valeur


def _api_resultat(reponse: Any) -> JSONResponse:
    ok, charge, erreur = resultat_metier(reponse)
    if not ok:
        code_http = 409 if any(
            marqueur in f"{erreur['code']} {erreur['message']}".upper()
            for marqueur in ("CONFLIT", "CONTRADICTOIRE")
        ) else 400
        return JSONResponse({"ok": False, "erreur": erreur}, status_code=code_http)
    return JSONResponse({"ok": True, "resultat": charge})


def _appel_public(appel: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "source": appel.get("source", ""), "appel_id": appel.get("appel_id", ""),
        "statut": appel.get("statut", ""), "recu_le": appel.get("horodatage", ""),
    }


def _html(prefixe: str, titre: str, actif: str, titre_page: str, contenu: str, session: Session,
          bandeau: pages.Bandeau | None = None) -> HTMLResponse:
    return HTMLResponse(pages.gabarit(titre, contenu, prefixe=prefixe,
                                      session=session, actif=actif, bandeau=bandeau))


def _form_avis(prefixe: str, session: Session, avis_id: str, action: str, libelle: str,
               *, motif: bool = False) -> str:
    champs = [
        f'<form method="post" action="{pages.e(prefixe)}/marketing" class="inline-form">',
        f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">',
        f'<input type="hidden" name="mutation_id" value="{uuid.uuid4()}">',
        f'<input type="hidden" name="action" value="{pages.e(action)}">',
        f'<input type="hidden" name="avis_id" value="{pages.e(avis_id)}">',
    ]
    if motif:
        champs.append('<label>Correction souhaitée<input name="motif" required minlength="1" maxlength="500"></label>')
    champs.append(f'<button type="submit">{pages.e(libelle)}</button></form>')
    return "".join(champs)


def _url_http(valeur: Any) -> str | None:
    if not isinstance(valeur, str):
        return None
    try:
        url = urlsplit(valeur)
    except ValueError:
        return None
    if url.scheme not in {"https", "http"} or not url.hostname or url.username or url.password:
        return None
    return valeur
