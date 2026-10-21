"""Lecture console des observations M7 de performance, sans calcul financier local."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

from . import frontoffice_marketing, metier, pages
from .securite import Session

_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_PARAMETRES = frozenset({"debut", "fin"})


def _periode(request: Request) -> tuple[str, str]:
    items = request.query_params.multi_items()
    if any(cle not in _PARAMETRES for cle, _ in items):
        raise HTTPException(400, "seuls debut et fin sont acceptés")
    valeurs: dict[str, str] = {}
    for cle, valeur in items:
        if cle in valeurs:
            raise HTTPException(400, f"paramètre {cle} répété")
        valeurs[cle] = valeur
    if not valeurs:
        fin = datetime.now(UTC).date()
        debut = fin - timedelta(days=29)
    elif set(valeurs) != _PARAMETRES:
        raise HTTPException(400, "debut et fin doivent être fournis ensemble")
    else:
        try:
            debut = _lire_date(valeurs["debut"], "debut")
            fin = _lire_date(valeurs["fin"], "fin")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    if debut > fin:
        raise HTTPException(400, "la période est inversée")
    if (fin - debut).days + 1 > 366:
        raise HTTPException(400, "la période ne peut dépasser 366 jours")
    return debut.isoformat(), fin.isoformat()


def _lire_date(valeur: str, nom: str) -> date:
    if not isinstance(valeur, str) or not _DATE.fullmatch(valeur):
        raise ValueError(f"{nom} doit être une date AAAA-MM-JJ")
    try:
        resultat = date.fromisoformat(valeur)
    except ValueError as exc:
        raise ValueError(f"{nom} invalide") from exc
    if resultat.isoformat() != valeur:
        raise ValueError(f"{nom} invalide")
    return resultat


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
    """Monte les routes HTML et JSON de performance M7 en lecture seule."""
    del ecriture_api, formulaire, objet_json  # Aucune route de mutation ou de body dans cet écran.
    router = APIRouter()

    def lire(session: Session, periode: tuple[str, str]) -> Mapping[str, Any]:
        try:
            with cnx_factory() as cnx:
                reponse = metier.executer(
                    cnx,
                    deps,
                    session,
                    "m7_lire_performance_campagnes",
                    {"debut": periode[0], "fin": periode[1]},
                )
        except PermissionError as exc:
            raise HTTPException(403, "accès métier refusé") from exc
        except KeyError as exc:
            raise HTTPException(404, "lecture M7 indisponible") from exc
        except ValueError as exc:
            raise HTTPException(403 if "REJ-" in str(exc) else 400, "lecture métier refusée") from exc
        ok, charge, erreur = frontoffice_marketing.resultat_metier(reponse)
        if not ok or not isinstance(charge, Mapping):
            raise HTTPException(409, erreur.get("message", "résultat M7 indisponible"))
        return charge

    @router.get("/marketing/performance", response_class=HTMLResponse)
    def page_performance(request: Request) -> HTMLResponse:
        session = session_page(request)
        periode = _periode(request)
        rapport = lire(session, periode)
        contenu = _contenu(rapport)
        return HTMLResponse(pages.gabarit(
            "Performance marketing observée",
            contenu,
            prefixe=prefixe,
            session=session,
            actif="marketing",
        ))

    @router.get("/api/marketing/performance")
    def api_performance(request: Request) -> JSONResponse:
        session = session_api(request)
        periode = _periode(request)
        rapport = lire(session, periode)
        return JSONResponse({"ok": True, "resultat": rapport})

    return router


def _liste(valeurs: Any) -> str:
    if not isinstance(valeurs, (list, tuple)) or not valeurs:
        return "<p>Aucune donnée manquante déclarée.</p>"
    lignes = "".join(f"<li>{pages.e(_description(item))}</li>" for item in valeurs)
    return f"<ul>{lignes}</ul>"


def _description(valeur: Any) -> str:
    if isinstance(valeur, Mapping):
        for cle in ("description", "detail", "libelle", "code"):
            if valeur.get(cle) is not None:
                return str(valeur[cle])
        return "Indisponible"
    return _simple(valeur, "Indisponible")


def _simple(valeur: Any, defaut: str) -> str:
    """N'affiche jamais la représentation Python d'une structure mal formée."""
    if isinstance(valeur, str):
        return valeur
    if type(valeur) is int or isinstance(valeur, float):
        return str(valeur)
    return defaut


def _compte(valeur: Any) -> str:
    if type(valeur) is int and valeur >= 0:
        return str(valeur)
    return "Indisponible"


def _references(valeurs: Any) -> str:
    if not isinstance(valeurs, (list, tuple)) or not valeurs:
        return "<p>Source de détail non fournie.</p>"
    lignes = []
    for item in valeurs:
        if not isinstance(item, Mapping):
            continue
        sequence = item.get("sequence")
        suffixe = f" · séquence {pages.e(_compte(sequence))}" if sequence is not None else ""
        lignes.append(
            f"<li>{pages.e(_simple(item.get('type'), 'Source'))} : "
            f"{pages.e(_simple(item.get('reference'), '—'))}{suffixe}</li>"
        )
    return "<ul>" + "".join(lignes) + "</ul>" if lignes else "<p>Source de détail non fournie.</p>"


def _contenu(rapport: Mapping[str, Any]) -> str:
    periode = rapport.get("periode", {})
    periode = periode if isinstance(periode, Mapping) else {}
    campagnes = rapport.get("campagnes", [])
    contenu = [
        '<section class="carte pile"><h2>Performance marketing observée</h2>',
        f"<p>Période : {pages.e(_simple(periode.get('debut'), '—'))} au "
        f"{pages.e(_simple(periode.get('fin'), '—'))}</p>",
        f"<p>Couverture des données : {pages.e(_simple(rapport.get('couverture'), 'INCONNUE'))}</p>",
        "<p>Les associations proviennent des faits M2; les devis acceptés sont des observations M3. "
        "La marge affichée est une marge constatée M5, sans preuve d’encaissement. "
        "Les coûts publicitaires, le coût par lead et le ROI ne sont pas reliés et restent inconnus.</p>",
    ]
    if not isinstance(campagnes, (list, tuple)):
        contenu.append('<p class="message message-alerte">Liste des campagnes indisponible.</p>')
    elif not campagnes:
        contenu.append('<p class="vide">Aucune observation de campagne connue pour cette période.</p>')
    else:
        lignes = [campagne for campagne in campagnes if isinstance(campagne, Mapping)]
        if len(lignes) != len(campagnes):
            contenu.append('<p class="message message-alerte">Une ou plusieurs observations sont mal formées.</p>')
        contenu.append('<div class="table-defilante"><table><thead><tr>'
                       '<th>Source</th><th>Campagne</th><th>Leads associés observés M2</th>'
                       '<th>Devis acceptés M3</th><th>Chantiers à marge constatée</th>'
                       '<th>Marge constatée M5 (CAD)</th><th>Coûts publicitaires</th>'
                       '<th>Coût par lead</th><th>ROI</th><th>Couverture</th>'
                       '<th>État et manquants</th><th>Sources</th>'
                       '</tr></thead><tbody>')
        for campagne in lignes:
            marge = campagne.get("marge_constatee_M5_cad")
            cout_ads = campagne.get("cout_ads_cad")
            cout_lead = campagne.get("cout_par_lead_cad")
            roi = campagne.get("roi")
            contenu.append(
                "<tr>"
                f"<th scope='row'>{pages.e(_simple(campagne.get('source'), 'Source inconnue'))}</th>"
                f"<td>{pages.e(_simple(campagne.get('campagne'), 'Campagne inconnue'))}</td>"
                f"<td>{pages.e(_compte(campagne.get('leads_associes_observes')))}</td>"
                f"<td>{pages.e(_compte(campagne.get('devis_acceptes')))}</td>"
                f"<td>{pages.e(_compte(campagne.get('chantiers_marge_constatee')))}</td>"
                f"<td>{pages.e(_simple(marge, 'Inconnue'))}</td>"
                f"<td>{pages.e(_simple(cout_ads, 'Inconnu'))}</td>"
                f"<td>{pages.e(_simple(cout_lead, 'Inconnu'))}</td>"
                f"<td>{pages.e(_simple(roi, 'Inconnu'))}</td>"
                f"<td>{pages.e(_simple(campagne.get('couverture'), 'INCONNUE'))}</td>"
                f"<td>{pages.e(_simple(campagne.get('statut_financier'), 'INCONNU'))}<br>"
                f"{_liste(campagne.get('manque'))}</td>"
                f"<td>{_references(campagne.get('source_refs'))}</td>"
                "</tr>"
            )
        contenu.append("</tbody></table></div>")
    contenu.append("<h3>Manquants pour l’ensemble de la période</h3>" + _liste(rapport.get("manque")))
    exclusions = rapport.get("exclusions")
    contenu.append("<h3>Exclusions du calcul</h3>")
    if isinstance(exclusions, Mapping) and exclusions:
        details = "".join(
            f"<li>{pages.e(_simple(cle, 'Exclusion'))} : {pages.e(_compte(nombre))}</li>"
            for cle, nombre in exclusions.items()
        )
        contenu.append(f"<ul>{details}</ul>")
    else:
        contenu.append("<p>Aucune exclusion ou détail d’exclusion fourni.</p>")
    contenu.append("<h3>Références de source</h3>" + _references(rapport.get("source_refs")))
    contenu.append("</section>")
    return "".join(contenu)
