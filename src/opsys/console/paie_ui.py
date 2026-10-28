"""Écran propriétaire de préparation du brut régulier; aucune paie officielle."""

from __future__ import annotations

import json
import re
import secrets
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from sqlalchemy import Connection

from .. import identite
from . import metier, obligations_privees, pages, paie_admission_ui, paie_dossier_ui, securite
from .securite import Session

_OUTIL = "m5_preparer_brut_regulier"
_CHAMPS = frozenset(
    {
        "employee_person_id",
        "debut",
        "fin",
        "fuseau",
        "politique_arrondi",
        "hypothese_arrondi",
        "sources_attendues",
    }
)
_CHAMPS_FORMULAIRE = _CHAMPS | {"csrf", "action"}
_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_POLITIQUE = "centime_demi_superieur"
_MAX_HYPOTHESE = 300
_CHAMPS_WEBRAS = _CHAMPS | {
    "date_paie",
    "periodes_annuelles",
    "revenu_imposable_cad",
    "reference_revenu_imposable",
}
_CHAMPS_WEBRAS_FORM = _CHAMPS_WEBRAS | {"csrf"}
_FREQUENCES_ANNUELLES = frozenset({12, 24, 26, 52})


def _owner(cnx: Connection, session: Session) -> identite.Personne:
    personne = identite.personne_active(cnx, session.utilisateur)
    if personne is None or "nathan_owner" not in personne.roles:
        raise HTTPException(403, "préparation de paie réservée au propriétaire actif")
    return personne


def _texte(data: Mapping[str, Any], cle: str, maximum: int) -> str:
    valeur = data.get(cle)
    if not isinstance(valeur, str) or not valeur.strip() or len(valeur) > maximum:
        raise HTTPException(400, f"{cle} invalide")
    return valeur.strip()


def _snapshot(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, Mapping) or set(value) != {"heures_m4", "contrat_m5"}:
        raise HTTPException(400, "sources_attendues invalide")
    m4, m5 = value.get("heures_m4"), value.get("contrat_m5")
    if (
        not isinstance(m4, Mapping)
        or set(m4) != {"ligne_id", "revision", "empreinte_sources"}
        or not isinstance(m5, Mapping)
        or set(m5) != {"contrat_id", "revision", "ligne_id"}
    ):
        raise HTTPException(400, "références de snapshot invalides")
    for key in ("ligne_id", "empreinte_sources"):
        if not isinstance(m4.get(key), str) or len(m4[key]) != 64:
            raise HTTPException(400, "référence M4 invalide")
    if type(m4.get("revision")) is not int or m4["revision"] < 1:
        raise HTTPException(400, "révision M4 invalide")
    if not isinstance(m5.get("contrat_id"), str) or not m5["contrat_id"] or len(m5["contrat_id"]) > 64:
        raise HTTPException(400, "contrat M5 invalide")
    if not isinstance(m5.get("ligne_id"), str) or len(m5["ligne_id"]) != 64:
        raise HTTPException(400, "ligne M5 invalide")
    if type(m5.get("revision")) is not int or m5["revision"] < 1:
        raise HTTPException(400, "révision M5 invalide")
    return {"heures_m4": dict(m4), "contrat_m5": dict(m5)}


def _arguments(data: Mapping[str, Any]) -> dict[str, Any]:
    if set(data) != _CHAMPS:
        raise HTTPException(400, "les sept arguments canoniques sont requis")
    debut, fin = _texte(data, "debut", 10), _texte(data, "fin", 10)
    if not _DATE.fullmatch(debut) or not _DATE.fullmatch(fin):
        raise HTTPException(400, "dates inclusives au format AAAA-MM-JJ requises")
    try:
        if date.fromisoformat(debut) > date.fromisoformat(fin):
            raise HTTPException(400, "la période doit être ordonnée")
    except ValueError as exc:
        raise HTTPException(400, "date invalide") from exc
    politique = _texte(data, "politique_arrondi", 64)
    if politique != _POLITIQUE:
        raise HTTPException(400, "politique d'arrondi non prise en charge")
    return {
        "employee_person_id": _texte(data, "employee_person_id", 128),
        "debut": debut,
        "fin": fin,
        "fuseau": _texte(data, "fuseau", 64),
        "politique_arrondi": politique,
        "hypothese_arrondi": _texte(data, "hypothese_arrondi", _MAX_HYPOTHESE),
        "sources_attendues": _snapshot(data.get("sources_attendues")),
    }


def _arguments_webras(data: Mapping[str, Any]) -> dict[str, Any]:
    if set(data) != _CHAMPS_WEBRAS:
        raise HTTPException(400, "champs du dossier WebRAS invalides")
    base = _arguments({cle: data[cle] for cle in _CHAMPS})
    date_paie = _texte(data, "date_paie", 10)
    if not _DATE.fullmatch(date_paie):
        raise HTTPException(400, "date de paie au format AAAA-MM-JJ requise")
    try:
        if date.fromisoformat(date_paie).isoformat() != date_paie or date_paie < base["fin"]:
            raise HTTPException(400, "date de paie canonique égale ou postérieure à la période requise")
    except ValueError as exc:
        raise HTTPException(400, "date de paie invalide") from exc
    periodes = data.get("periodes_annuelles")
    if type(periodes) is not int or periodes not in _FREQUENCES_ANNUELLES:
        raise HTTPException(400, "fréquence annuelle explicite requise")
    assiette = data.get("revenu_imposable_cad")
    reference = data.get("reference_revenu_imposable")
    if assiette is not None and (
        not isinstance(assiette, str)
        or not re.fullmatch(r"(?:0|[1-9][0-9]{0,8})\.[0-9]{2}", assiette)
        or not isinstance(reference, str)
        or not 1 <= len(reference.strip()) <= 240
    ):
        raise HTTPException(400, "assiette facultative: montant CAD au centime et référence requis si fournie")
    if assiette is None and reference is not None:
        raise HTTPException(400, "référence d'assiette sans montant refusée")
    return {
        **base,
        "date_paie": date_paie,
        "periodes_annuelles": periodes,
        "revenu_imposable_cad": assiette,
        "reference_revenu_imposable": reference,
    }


def _refus(reponse: Mapping[str, Any]) -> str:
    valeur = reponse.get("resultat")
    corps = valeur if isinstance(valeur, Mapping) else reponse
    verdict = corps.get("verdict")
    if isinstance(verdict, Mapping):
        return str(verdict.get("code", "demande_refusee"))
    return str(corps.get("erreur", "demande_refusee"))


def _corps(reponse: Mapping[str, Any]) -> Mapping[str, Any] | None:
    valeur = reponse.get("resultat")
    if not isinstance(valeur, Mapping) or valeur.get("accepte") is not True:
        return None
    resultat = valeur.get("resultat")
    return resultat if isinstance(resultat, Mapping) else None


def _sources_reference(resultat: Mapping[str, Any]) -> dict[str, Any] | None:
    sources = resultat.get("sources")
    if not isinstance(sources, Mapping):
        return None
    m4, m5 = sources.get("heures_m4"), sources.get("contrat_m5")
    if not isinstance(m4, Mapping) or not isinstance(m5, Mapping):
        return None
    return {
        "heures_m4": {
            "ligne_id": m4.get("ligne_id"),
            "revision": m4.get("revision"),
            "empreinte_sources": m4.get("empreinte_sources"),
        },
        "contrat_m5": {
            "contrat_id": m5.get("contrat_id"),
            "revision": m5.get("revision"),
            "ligne_id": m5.get("ligne_id"),
        },
    }


def _rendu_resultat(resultat: Mapping[str, Any] | None, erreur: str = "") -> str:
    if resultat is None:
        return f'<p class="message message-erreur">{pages.e(erreur)}</p>' if erreur else ""
    sources = resultat.get("sources", {})
    m4 = sources.get("heures_m4", {}) if isinstance(sources, Mapping) else {}
    m5 = sources.get("contrat_m5", {}) if isinstance(sources, Mapping) else {}
    hypotheses = resultat.get("hypotheses", [])
    hypothese = hypotheses[0] if isinstance(hypotheses, list) and hypotheses else {}
    fraction = resultat.get("brut_exact_fraction")
    fraction_txt = "—"
    if isinstance(fraction, Mapping):
        fraction_txt = (
            f"{pages.e(fraction.get('numerateur_centimes'))} centimes / {pages.e(fraction.get('denominateur'))}"
        )
    brut = resultat.get("brut_brouillon")
    minutes = resultat.get("minutes_regulieres")
    ref_hypothese = hypothese.get("reference_humaine", "") if isinstance(hypothese, Mapping) else ""
    politique = hypothese.get("politique_arrondi", "") if isinstance(hypothese, Mapping) else ""
    mention = resultat.get("mention")
    return (
        '<section class="carte pile" aria-labelledby="resultat-paie">'
        '<h2 id="resultat-paie">Brouillon préparatoire</h2>'
        f"<p>Brut régulier arrondi : <strong>{pages.e(brut)} CAD</strong></p>"
        f"<p>Fraction exacte avant arrondi : {fraction_txt}; minutes régulières : {pages.e(minutes)}.</p>"
        f"<p>Source M4 : ligne {pages.e(m4.get('ligne_id'))}, révision {pages.e(m4.get('revision'))}, "
        f"empreinte {pages.e(m4.get('empreinte_sources'))}.</p>"
        f"<p>Contrat M5 : {pages.e(m5.get('contrat_id'))}, ligne {pages.e(m5.get('ligne_id'))}, "
        f"révision {pages.e(m5.get('revision'))}.</p>"
        f"<p>Arrondi : {pages.e(politique)}. Hypothèse déclarée, non vérifiée : "
        f"{pages.e(ref_hypothese)}</p>"
        + (f"<p>{pages.e(mention)}</p>" if mention else "")
        + '<p class="message message-alerte">Préparatoire seulement : validation humaine requise. '
        + "Retenues, cotisations, DAS, net et paiement ne sont pas calculés; "
        + "aucune action officielle n’est possible ici.</p>"
        "</section>"
    )


def _formulaire(
    prefixe: str,
    csrf: str,
    employees: list[identite.Personne],
    values: Mapping[str, Any] | None = None,
    *,
    sources: Mapping[str, Any] | None = None,
) -> str:
    values = values or {}
    choix = "".join(
        f'<option value="{pages.e(employee.identifiant)}"'
        f"{' selected' if values.get('employee_person_id') == employee.identifiant else ''}>"
        f"{pages.e(employee.nom)}</option>"
        for employee in employees
    )
    if not choix:
        choix = '<option value="">Aucun salarié actif</option>'
    action = f"{pages.e(prefixe)}/finance/paie"
    inputs = (
        f'<label for="employee_person_id">Salarié actif</label><select id="employee_person_id" '
        f'name="employee_person_id" required>{choix}</select>'
        f'<label for="debut">Premier jour inclus</label><input id="debut" name="debut" type="date" '
        f'required value="{pages.e(values.get("debut", ""))}">'
        f'<label for="fin">Dernier jour inclus</label><input id="fin" name="fin" type="date" '
        f'required value="{pages.e(values.get("fin", ""))}">'
        f'<label for="fuseau">Fuseau horaire IANA</label><input id="fuseau" name="fuseau" required maxlength="64" '
        f'placeholder="America/Montreal" value="{pages.e(values.get("fuseau", ""))}">'
        '<label for="politique_arrondi">Politique d’arrondi</label><select id="politique_arrondi" '
        f'name="politique_arrondi" required><option value="" disabled'
        f"{' selected' if values.get('politique_arrondi') != _POLITIQUE else ''}>"
        'Choisir une politique</option><option value="centime_demi_superieur"'
        f"{' selected' if values.get('politique_arrondi') == _POLITIQUE else ''}>"
        "Centime, demi supérieur</option></select>"
        '<label for="hypothese_arrondi">Référence ou hypothèse d’arrondi</label>'
        f'<input id="hypothese_arrondi" name="hypothese_arrondi" required maxlength="300" '
        f'value="{pages.e(values.get("hypothese_arrondi", ""))}">'
    )
    snapshot_value = "" if sources is None else json.dumps(sources, separators=(",", ":"))
    snapshot_field = f'<input type="hidden" name="sources_attendues" value="{pages.e(snapshot_value)}">'
    hidden = f'<input type="hidden" name="csrf" value="{pages.e(csrf)}">{snapshot_field}'
    return (
        '<form method="post" class="carte pile">'
        + inputs
        + hidden
        + f'<button type="submit" name="action" value="lire_courant" formaction="{action}">'
        "Lire les sources courantes</button></form>"
    )


def _formulaire_webras(prefixe: str, csrf: str, values: Mapping[str, Any], sources: Mapping[str, Any]) -> str:
    snapshot = json.dumps(sources, ensure_ascii=False, separators=(",", ":"))
    options = "".join(
        f'<option value="{n}"{" selected" if values.get("periodes_annuelles") == n else ""}>{n}</option>'
        for n in sorted(_FREQUENCES_ANNUELLES)
    )
    choix = (
        '<option value="" disabled selected>Choisir une fréquence</option>'
        if values.get("periodes_annuelles") not in _FREQUENCES_ANNUELLES
        else ""
    ) + options
    return (
        '<form method="post" class="carte pile" '
        f'action="{pages.e(prefixe)}/finance/paie/webras">'
        "<h2>Préparer le dossier WebRAS</h2>"
        "<p>Export privé pour saisie et calcul humains. Impôts, cotisations, retenues, net et DAS restent inconnus. "
        "Aucune déclaration ni action officielle n’est effectuée.</p>"
        f'<input type="hidden" name="employee_person_id" value="{pages.e(values["employee_person_id"])}">'
        f'<input type="hidden" name="debut" value="{pages.e(values["debut"])}">'
        f'<input type="hidden" name="fin" value="{pages.e(values["fin"])}">'
        f'<input type="hidden" name="fuseau" value="{pages.e(values["fuseau"])}">'
        f'<input type="hidden" name="politique_arrondi" value="{pages.e(values["politique_arrondi"])}">'
        f'<input type="hidden" name="hypothese_arrondi" value="{pages.e(values["hypothese_arrondi"])}">'
        f'<input type="hidden" name="sources_attendues" value="{pages.e(snapshot)}">'
        '<label for="date_paie">Date de paie</label>'
        '<input id="date_paie" name="date_paie" type="date" required>'
        '<label for="periodes_annuelles">Périodes de paie par année</label>'
        f'<select id="periodes_annuelles" name="periodes_annuelles" required>{choix}</select>'
        '<label for="revenu_imposable_cad">Revenu imposable déclaré (CAD, facultatif)</label>'
        '<input id="revenu_imposable_cad" name="revenu_imposable_cad" inputmode="decimal" '
        'pattern="(?:0|[1-9][0-9]{0,8})\\.[0-9]{2}">'
        '<label for="reference_revenu_imposable">Référence humaine de ce revenu (requise si montant fourni)</label>'
        '<input id="reference_revenu_imposable" name="reference_revenu_imposable" maxlength="240">'
        f'<input type="hidden" name="csrf" value="{pages.e(csrf)}">'
        '<button type="submit">Télécharger le dossier JSON</button></form>'
    )


def creer_router(
    *,
    session_page: Callable[..., Session],
    session_api: Callable[..., Session],
    formulaire: Callable[[Request], Any],
    objet_json: Callable[[Request], Any],
    cnx_factory: Callable[[], Any],
    deps: Mapping[str, Any],
    prefixe: str,
) -> APIRouter:
    router = APIRouter(tags=["paie préparatoire"])
    router.include_router(paie_admission_ui.creer_router(
        session_page=session_page, session_api=session_api, formulaire=formulaire,
        objet_json=objet_json, cnx_factory=cnx_factory, deps=deps, prefixe=prefixe,
    ))
    router.include_router(paie_dossier_ui.creer_router(
        session_page=session_page, session_api=session_api, formulaire=formulaire,
        objet_json=objet_json, cnx_factory=cnx_factory, deps=deps, prefixe=prefixe,
    ))

    def employees_actifs(cnx: Connection, session: Session) -> list[identite.Personne]:
        _owner(cnx, session)
        return [p for p in identite.lister(cnx) if p.actif and "employee" in p.roles]

    def appeler(
        cnx: Connection,
        session: Session,
        args: Mapping[str, Any],
        outil: str = _OUTIL,
    ) -> dict[str, Any]:
        _owner(cnx, session)
        return metier.executer(cnx, deps, session, outil, args)

    def page(
        session: Session,
        *,
        values: Mapping[str, Any] | None = None,
        resultat: Mapping[str, Any] | None = None,
        erreur: str = "",
        pinned: Mapping[str, Any] | None = None,
    ) -> HTMLResponse:
        with cnx_factory() as cnx:
            employees = employees_actifs(cnx, session)
        content = (
            "<p>Préparation du brut régulier à partir des sources M4/M5. Les dates de la période sont inclusives. "
            "Une nouvelle lecture et le recalcul d’un snapshot épinglé sont deux actions distinctes.</p>"
            f'<p><a class="bouton" href="{pages.e(prefixe)}/finance/paie/obligations">'
            "Calendrier privé des montants paie/DAS confirmés</a></p>"
            f'<p><a href="{pages.e(prefixe)}/finance/paie/admission">'
            "Vérifier les préconditions documentaires</a></p>"
            f'<p><a class="bouton" href="{pages.e(prefixe)}/finance/paie/dossiers">'
            "Dossiers de paie préparatoires (calcul composé, versions, revue, export CPA)</a></p>"
            + _formulaire(prefixe, session.csrf, employees, values)
            + _rendu_resultat(resultat, erreur)
        )
        if resultat is not None and pinned is not None and values is not None:
            args_values = {**values, "sources_attendues": pinned}
            content += (
                '<section class="carte pile"><h2>Actions sur les sources</h2>'
                '<form method="post" class="pile">'
                f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
                f'<input type="hidden" name="employee_person_id" value="{pages.e(args_values["employee_person_id"])}">'
                f'<input type="hidden" name="debut" value="{pages.e(args_values["debut"])}">'
                f'<input type="hidden" name="fin" value="{pages.e(args_values["fin"])}">'
                f'<input type="hidden" name="fuseau" value="{pages.e(args_values["fuseau"])}">'
                f'<input type="hidden" name="politique_arrondi" value="{pages.e(args_values["politique_arrondi"])}">'
                f'<input type="hidden" name="hypothese_arrondi" value="{pages.e(args_values["hypothese_arrondi"])}">'
                f'<input type="hidden" name="sources_attendues" '
                f'value="{pages.e(json.dumps(pinned, separators=(",", ":")))}">'
                '<button type="submit" name="action" value="recalculer_epingle" '
                f'formaction="{pages.e(prefixe)}/finance/paie">Recalculer ce snapshot</button></form>' + "</section>"
            )
            content += _formulaire_webras(prefixe, session.csrf, values, pinned)
        return HTMLResponse(
            pages.gabarit("Préparer un brut régulier", content, prefixe=prefixe, session=session, actif="finance")
        )

    @router.get("/finance/paie", response_class=HTMLResponse)
    def page_paie(request: Request) -> HTMLResponse:
        session = session_page(request, administrateur=False)
        with cnx_factory() as cnx:
            employees_actifs(cnx, session)
        return page(session)

    @router.post("/finance/paie", response_class=HTMLResponse)
    async def paie_formulaire(request: Request) -> Response:
        session = session_page(request, administrateur=False)
        data = await formulaire(request)
        if not isinstance(data, Mapping) or set(data) != _CHAMPS_FORMULAIRE:
            raise HTTPException(400, "champs du formulaire invalides")
        if not securite.csrf_valide(data.get("csrf"), session):
            raise HTTPException(403, "jeton CSRF absent ou invalide")
        action = data.get("action")
        if action not in {"lire_courant", "recalculer_epingle"}:
            raise HTTPException(400, "action de lecture invalide")
        source_valeur: Any = data.get("sources_attendues")
        if source_valeur in (None, ""):
            source_valeur = None
        else:
            try:
                source_valeur = json.loads(source_valeur)
            except (ValueError, TypeError) as exc:
                raise HTTPException(400, "snapshot illisible") from exc
        canonical = {key: data.get(key) for key in _CHAMPS}
        canonical["sources_attendues"] = source_valeur
        args = _arguments(canonical)
        if action == "lire_courant":
            args["sources_attendues"] = None
        elif args["sources_attendues"] is None:
            raise HTTPException(400, "un snapshot existant est requis pour le recalcul épinglé")
        with cnx_factory() as cnx:
            employees = employees_actifs(cnx, session)
            if args["employee_person_id"] not in {p.identifiant for p in employees}:
                raise HTTPException(400, "salarié actif introuvable")
            reponse = appeler(cnx, session, args)
        resultat = _corps(reponse)
        erreur = "" if resultat is not None else _refus(reponse)
        return page(
            session,
            values=args,
            resultat=resultat,
            erreur=erreur,
            pinned=_sources_reference(resultat) if resultat is not None else None,
        )

    @router.post("/api/finance/paie/brut")
    async def paie_json(request: Request) -> JSONResponse:
        session = session_api(request, administrateur=False)
        if not securite.csrf_valide(request.headers.get("x-csrf-token"), session):
            raise HTTPException(403, "jeton CSRF absent ou invalide")
        data = await objet_json(request)
        args = _arguments(data)
        with cnx_factory() as cnx:
            employees = employees_actifs(cnx, session)
            if args["employee_person_id"] not in {p.identifiant for p in employees}:
                raise HTTPException(400, "salarié actif introuvable")
            reponse = appeler(cnx, session, args)
        return JSONResponse(reponse)

    @router.post("/finance/paie/webras")
    async def dossier_webras_formulaire(request: Request) -> Response:
        session = session_page(request, administrateur=False)
        data = await formulaire(request)
        if not isinstance(data, Mapping) or set(data) != _CHAMPS_WEBRAS_FORM:
            raise HTTPException(400, "champs du formulaire WebRAS invalides")
        if not securite.csrf_valide(data.get("csrf"), session):
            raise HTTPException(403, "jeton CSRF absent ou invalide")
        source_valeur = data.get("sources_attendues")
        try:
            sources = json.loads(source_valeur) if isinstance(source_valeur, str) else None
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, "snapshot illisible") from exc
        canonical = {key: data.get(key) for key in _CHAMPS}
        canonical["sources_attendues"] = sources
        canonical.update({key: data.get(key) for key in _CHAMPS_WEBRAS - _CHAMPS})
        for key in ("revenu_imposable_cad", "reference_revenu_imposable"):
            if canonical[key] == "":
                canonical[key] = None
        periodes = canonical.get("periodes_annuelles")
        if (
            not isinstance(periodes, str)
            or len(periodes) > 2
            or not re.fullmatch(r"[0-9]{1,2}", periodes)
            or int(periodes) not in _FREQUENCES_ANNUELLES
        ):
            raise HTTPException(400, "fréquence annuelle invalide")
        canonical["periodes_annuelles"] = int(periodes)
        args = _arguments_webras(canonical)
        with cnx_factory() as cnx:
            _owner(cnx, session)
            employees = employees_actifs(cnx, session)
            if args["employee_person_id"] not in {p.identifiant for p in employees}:
                raise HTTPException(400, "salarié actif introuvable")
            reponse = appeler(cnx, session, args, "m5_preparer_dossier_webras")
        dossier = _corps(reponse)
        if dossier is None:
            return JSONResponse(reponse, status_code=409, headers={"Cache-Control": "no-store"})
        return Response(
            content=json.dumps(dossier, ensure_ascii=False, separators=(",", ":")),
            media_type="application/json",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": f'attachment; filename="dossier-webras-{args["date_paie"]}.json"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    @router.post("/api/finance/paie/webras")
    async def dossier_webras_json(request: Request) -> Response:
        session = session_api(request, administrateur=False)
        if not securite.csrf_valide(request.headers.get("x-csrf-token"), session):
            raise HTTPException(403, "jeton CSRF absent ou invalide")
        data = await objet_json(request)
        args = _arguments_webras(data)
        with cnx_factory() as cnx:
            _owner(cnx, session)
            employees = employees_actifs(cnx, session)
            if args["employee_person_id"] not in {p.identifiant for p in employees}:
                raise HTTPException(400, "salarié actif introuvable")
            reponse = appeler(cnx, session, args, "m5_preparer_dossier_webras")
        dossier = _corps(reponse)
        if dossier is None:
            return JSONResponse(reponse, status_code=409, headers={"Cache-Control": "no-store"})
        contenu = json.dumps(dossier, ensure_ascii=False, separators=(",", ":"))
        nom = f"dossier-webras-{args['date_paie']}.json"
        return Response(
            content=contenu,
            media_type="application/json",
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": f'attachment; filename="{nom}"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    champs_obligation = {
        "type", "montant_cad", "periode_debut", "periode_fin", "date_paie", "echeance",
        "reference_piece", "autorite", "source_consultee_le", "applicable_du", "applicable_au", "version",
        "revision_attendue", "mutation_id", "csrf",
    }

    def finance_active(cnx: Connection, session: Session) -> identite.Personne:
        personne = identite.personne_active(cnx, session.utilisateur)
        if personne is None or not (personne.roles & {"finance", "nathan_owner"}):
            raise HTTPException(403, "calendrier privé réservé à finance ou au propriétaire actif")
        return personne

    def calendrier_prive(session: Session) -> HTMLResponse:
        with cnx_factory() as cnx:
            finance_active(cnx, session)
            try:
                instantane = obligations_privees.lire(cnx)
            except obligations_privees.RefusObligation as exc:
                raise HTTPException(409, str(exc)) from exc
            finance_active(cnx, session)  # revalidation après déchiffrement, avant de rendre les montants privés
        colonnes = (
            "type", "montant_cad", "periode_debut", "periode_fin", "date_paie", "echeance",
            "reference_piece", "autorite", "version", "confirme_le",
        )
        def commandes_cycle(ligne: Mapping[str, Any]) -> str:
            if ligne["statut"] != "ACTIVE":
                return ""
            valeurs = ligne["obligation"]
            modifiables = {"montant_cad", "date_paie", "echeance", "reference_piece", "autorite",
                           "source_consultee_le", "applicable_du", "applicable_au", "version"}
            champs_remplacement = "".join(
                f'<label>{pages.e(cle)}<input name="{pages.e(cle)}" value="{pages.e(valeur)}" required></label>'
                if cle in modifiables else
                f'<input type="hidden" name="{pages.e(cle)}" value="{pages.e(valeur)}">'
                for cle, valeur in valeurs.items()
            )
            champs_reglement = "".join(
                f'<input type="hidden" name="{pages.e(cle)}" value="{pages.e(valeur)}">'
                for cle, valeur in valeurs.items()
            )
            commun = (f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
                + f'<input type="hidden" name="revision_attendue" value="{instantane["revision"]}">'
                + f'<input type="hidden" name="cible_id" value="{pages.e(ligne["id"])}">')
            return (
                f'<form method="post" action="{pages.e(prefixe)}/finance/paie/obligations/transition">'
                + champs_remplacement + commun
                + f'<input type="hidden" name="mutation_id" value="{secrets.token_hex(16)}">'
                + '<input type="hidden" name="action" value="REMPLACER">'
                + '<input type="hidden" name="reglee_le" value="">'
                + '<button type="submit">Déclarer un remplacement</button></form>'
                f'<form method="post" action="{pages.e(prefixe)}/finance/paie/obligations/transition">'
                + champs_reglement + commun
                + f'<input type="hidden" name="mutation_id" value="{secrets.token_hex(16)}">'
                + '<input type="hidden" name="action" value="REGLER">'
                + '<label>Date du règlement déclaré<input name="reglee_le" type="date" required></label>'
                + '<button type="submit">Déclarer réglée (déclaration humaine, non rapprochée)</button></form>'
            )

        lignes = "".join(
            "<tr><td>" + pages.e(ligne["id"]) + "</td><td>" + pages.e(ligne["statut"]) + "</td>"
            + "".join(f"<td>{pages.e(ligne['obligation'][champ])}</td>" for champ in colonnes[:-1])
            + f"<td>{pages.e(ligne['confirme_le'])}</td>"
            + f"<td>{pages.e(ligne.get('reglee_le', ''))}</td>"
            + f"<td>{pages.e(ligne.get('remplace_id', ligne.get('remplace_par_id', ligne.get('cible_id', ''))))}</td>"
            + f"<td>{commandes_cycle(ligne)}</td></tr>"
            for ligne in instantane["obligations"]
        )
        champs = (
            ("Type (paies ou DAS)",
             '<select name="type"><option value="paies">Paies</option>'
             '<option value="das">DAS</option></select>'),
            ("Montant déclaré CAD (ex. 1250.00)", '<input name="montant_cad" inputmode="decimal" required>'),
            ("Début de période", '<input name="periode_debut" type="date" required>'),
            ("Fin de période", '<input name="periode_fin" type="date" required>'),
            ("Date de paie", '<input name="date_paie" type="date" required>'),
            ("Échéance déclarée", '<input name="echeance" type="date" required>'),
            ("Référence de la pièce confirmée", '<input name="reference_piece" maxlength="240" required>'),
            ("Autorité déclarée", '<input name="autorite" maxlength="120" required>'),
            ("Date de consultation", '<input name="source_consultee_le" type="date" required>'),
            ("Applicabilité déclarée, début", '<input name="applicable_du" type="date" required>'),
            ("Applicabilité déclarée, fin", '<input name="applicable_au" type="date" required>'),
            ("Version déclarée", '<input name="version" maxlength="80" required>'),
        )
        formulaire_html = "".join(f"<label>{pages.e(label)}{control}</label>" for label, control in champs)
        formulaire_html += (
            f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
            f'<input type="hidden" name="revision_attendue" value="{instantane["revision"]}">'
            f'<input type="hidden" name="mutation_id" value="{secrets.token_hex(16)}">'
            '<button type="submit">Confirmer la déclaration humaine</button>'
        )
        contenu = (
            '<p>Déclarations humaines confirmées; métadonnées de source déclaratives, sans validation officielle. '
            'Aucune paie nette, retenue, remise ou paiement n’est calculé. '
            'Un règlement affiché reste une déclaration humaine, non rapprochée.</p>'
            '<table><thead><tr><th>ID canonique</th><th>État</th><th>Type</th><th>Montant CAD</th>'
            '<th>Période début</th><th>Période fin</th><th>Date paie</th><th>Échéance</th><th>Pièce</th>'
            '<th>Autorité</th><th>Version</th><th>Confirmée</th><th>Règlement déclaré le</th>'
            '<th>Référence de cycle</th><th>Cycle humain</th>'
            f'</tr></thead><tbody>{lignes}</tbody></table>'
            '<p>Réserves utilisables : INCONNU; configuration historique et provisions non catégorisées '
            'non réconciliées. Aucun montant agrégé.</p>'
            f'<form method="post" class="pile">{formulaire_html}</form>'
        )
        return HTMLResponse(
            pages.gabarit("Calendrier privé paie/DAS", contenu, prefixe=prefixe, session=session, actif="finance"),
            headers={"Cache-Control": "no-store"},
        )

    @router.get("/finance/paie/obligations", response_class=HTMLResponse)
    def page_obligations(request: Request) -> HTMLResponse:
        session = session_page(request, administrateur=False)
        if request.query_params:
            raise HTTPException(400, "aucun paramètre de requête accepté")
        return calendrier_prive(session)

    @router.post("/finance/paie/obligations", response_class=HTMLResponse)
    async def confirmer_obligation(request: Request) -> Response:
        session = session_page(request, administrateur=False)
        if request.query_params:
            raise HTTPException(400, "aucun paramètre de requête accepté")
        with cnx_factory() as cnx:
            finance_active(cnx, session)
        data = await formulaire(request)
        if not isinstance(data, Mapping) or set(data) != champs_obligation:
            raise HTTPException(400, "champs de confirmation invalides")
        if not securite.csrf_valide(data.get("csrf"), session):
            raise HTTPException(403, "jeton CSRF absent ou invalide")
        try:
            revision = int(data["revision_attendue"])
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, "révision invalide") from exc
        payload = {cle: data[cle] for cle in obligations_privees.CHAMPS}

        def verifier_acteur(cnx: Connection, identifiant: str) -> None:
            if identifiant != session.utilisateur:
                raise HTTPException(403, "acteur de confirmation invalide")
            finance_active(cnx, session)

        with cnx_factory() as cnx:
            personne = finance_active(cnx, session)
            try:
                obligations_privees.ajouter(
                    cnx,
                    payload,
                    revision_attendue=revision,
                    mutation_id=data["mutation_id"],
                    confirme_par=personne.identifiant,
                    confirme_le=datetime.now(UTC).isoformat(timespec="seconds"),
                    verifier_acteur=verifier_acteur,
                )
            except obligations_privees.RefusObligation as exc:
                raise HTTPException(409, str(exc)) from exc
        return calendrier_prive(session)

    champs_transition = champs_obligation | {"action", "cible_id", "reglee_le"}

    @router.post("/finance/paie/obligations/transition", response_class=HTMLResponse)
    async def transition_obligation(request: Request) -> Response:
        session = session_page(request, administrateur=False)
        if request.query_params:
            raise HTTPException(400, "aucun paramètre de requête accepté")
        with cnx_factory() as cnx:
            finance_active(cnx, session)
        data = await formulaire(request)
        if not isinstance(data, Mapping) or set(data) != champs_transition:
            raise HTTPException(400, "champs de transition invalides")
        if not securite.csrf_valide(data.get("csrf"), session):
            raise HTTPException(403, "jeton CSRF absent ou invalide")
        try:
            revision = int(data["revision_attendue"])
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, "révision invalide") from exc
        payload = {cle: data[cle] for cle in obligations_privees.CHAMPS}
        action = data["action"]
        if action not in {"REMPLACER", "REGLER"}:
            raise HTTPException(400, "transition invalide")

        def verifier_acteur(cnx: Connection, identifiant: str) -> None:
            if identifiant != session.utilisateur:
                raise HTTPException(403, "acteur de confirmation invalide")
            finance_active(cnx, session)

        with cnx_factory() as cnx:
            personne = finance_active(cnx, session)
            try:
                obligations_privees.transition(
                    cnx, action, data["cible_id"], payload,
                    revision_attendue=revision, mutation_id=data["mutation_id"],
                    confirme_par=personne.identifiant, confirme_le=datetime.now(UTC).isoformat(timespec="seconds"),
                    reglee_le=data["reglee_le"] or None, verifier_acteur=verifier_acteur,
                )
            except obligations_privees.RefusObligation as exc:
                raise HTTPException(409, str(exc)) from exc
        return calendrier_prive(session)

    return router
