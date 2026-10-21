"""Vue propriétaire du plan M7.11a, projection et programme humain durable."""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable, Mapping
from datetime import date, timedelta
from typing import Any
from urllib.parse import parse_qs, quote, urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from m7_marketing import cmo_strategie, plan_cmo
from starlette.concurrency import run_in_threadpool

from . import couts_marketing, frontoffice_marketing, marketing_rapport, metier, pages, securite
from .marketing_growth_ui import _corps_borne, _objet_sans_doublon
from .securite import Session

_DATE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
_PARAMETRES = frozenset({"date_depart", "debut", "fin"})
_NO_STORE = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _date(valeur: str, nom: str) -> date:
    if not isinstance(valeur, str) or not _DATE.fullmatch(valeur):
        raise ValueError(f"{nom} doit être une date AAAA-MM-JJ")
    try:
        resultat = date.fromisoformat(valeur)
    except ValueError as exc:
        raise ValueError(f"{nom} invalide") from exc
    if resultat.isoformat() != valeur:
        raise ValueError(f"{nom} invalide")
    return resultat


def _parametres(request: Request) -> dict[str, str]:
    items = request.query_params.multi_items()
    if any(cle not in _PARAMETRES for cle, _ in items):
        raise HTTPException(400, "seuls date_depart, debut et fin sont acceptés")
    valeurs: dict[str, str] = {}
    for cle, valeur in items:
        if cle in valeurs:
            raise HTTPException(400, f"paramètre {cle} répété")
        valeurs[cle] = valeur
    if set(valeurs) != _PARAMETRES:
        raise HTTPException(400, "date_depart, debut et fin sont obligatoires")
    try:
        depart = _date(valeurs["date_depart"], "date_depart")
        debut, fin = _date(valeurs["debut"], "debut"), _date(valeurs["fin"], "fin")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if debut > fin:
        raise HTTPException(400, "la période observée est inversée")
    if (fin - debut).days > 365:
        raise HTTPException(400, "la période observée ne peut dépasser 366 jours")
    if depart > date.max - timedelta(days=89):
        raise HTTPException(400, "la date de départ dépasse la borne du plan à 90 jours")
    return valeurs


def _parametres_rapport(request: Request) -> dict[str, str]:
    valeurs: dict[str, str] = {}
    for cle, valeur in request.query_params.multi_items():
        if cle not in {"debut", "fin"} or cle in valeurs:
            raise HTTPException(400, "seuls debut et fin uniques sont acceptés")
        valeurs[cle] = valeur
    if set(valeurs) != {"debut", "fin"}:
        raise HTTPException(400, "debut et fin sont obligatoires")
    try:
        debut, fin = _date(valeurs["debut"], "debut"), _date(valeurs["fin"], "fin")
        if not 0 <= (fin - debut).days <= 365:
            raise ValueError("période inclusive de 366 jours maximum attendue")
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return valeurs


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
    router = APIRouter(tags=["marketing CMO M7"])
    router.include_router(couts_marketing.creer_router(
        session_page=session_page, session_api=session_api, ecriture_api=ecriture_api, formulaire=formulaire,
        objet_json=objet_json, cnx_factory=cnx_factory, deps=deps, prefixe=prefixe,
    ))

    def appeler(session: Session, nom: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            with cnx_factory() as cnx:
                reponse = metier.executer(cnx, deps, session, nom, arguments)
        except PermissionError as exc:
            raise HTTPException(403, "accès métier refusé") from exc
        except KeyError as exc:
            raise HTTPException(404, "source M7 indisponible") from exc
        except ValueError as exc:
            raise HTTPException(403 if "REJ-" in str(exc) else 400, "lecture métier refusée") from exc
        ok, charge, erreur = frontoffice_marketing.resultat_metier(reponse)
        if not ok or not isinstance(charge, Mapping):
            raise HTTPException(409, erreur.get("message", "source M7 indisponible ou invalide"))
        if charge.get("tronque") is True or charge.get("truncated") is True:
            raise HTTPException(409, "une source M7 est tronquée; projection refusée")
        return charge

    def lire(session: Session, valeurs: Mapping[str, str]) -> dict[str, Any]:
        marque = appeler(session, "m7_lire_profil_marque_courant", {})
        calendrier = appeler(session, "m7_lister_calendrier", {})
        performance = appeler(session, "m7_lire_performance_campagnes", {
            "debut": valeurs["debut"], "fin": valeurs["fin"],
        })
        try:
            return plan_cmo.projeter(
                date_depart=valeurs["date_depart"],
                debut=valeurs["debut"],
                fin=valeurs["fin"],
                profil_marque=marque,
                calendrier=calendrier,
                performance=performance,
            )
        except ValueError as exc:
            raise HTTPException(409, "source M7 incomplète ou période incompatible") from exc

    @router.get("/marketing/cmo", response_class=HTMLResponse)
    def page_cmo(request: Request) -> HTMLResponse:
        session = session_page(request)
        if not request.query_params:
            contenu = _formulaire_vide(prefixe) + _historique_cmo(strategies(session), prefixe, session)
            html = pages.gabarit("Plan CMO préparatoire", contenu, prefixe=prefixe, session=session, actif="marketing")
            return HTMLResponse(html, headers=_NO_STORE)
        valeurs = _parametres(request)
        plan = lire(session, valeurs)
        courant = strategies(session, projection=plan)
        contenu = (_contenu(plan, prefixe) + _formulaire_strategie(courant, valeurs, prefixe, session)
                   + _historique_cmo(courant, prefixe, session, parametres=valeurs))
        html = pages.gabarit("Plan CMO préparatoire", contenu, prefixe=prefixe, session=session, actif="marketing")
        return HTMLResponse(html, headers=_NO_STORE)

    @router.get("/api/marketing/cmo/plan")
    def api_plan_cmo(request: Request) -> JSONResponse:
        session = session_api(request)
        valeurs = _parametres(request)
        return JSONResponse({"ok": True, "resultat": lire(session, valeurs)}, headers=_NO_STORE)

    def lire_rapport(session: Session, valeurs: Mapping[str, str]) -> dict[str, Any]:
        try:
            return marketing_rapport.construire(session, deps, cnx_factory, **dict(valeurs))
        except PermissionError as exc:
            raise HTTPException(403, "accès au rapport retiré") from exc
        except marketing_rapport.SourceIndisponible as exc:
            raise HTTPException(409, "source du rapport absente, invalide ou au-delà des bornes") from exc
        except ValueError as exc:
            raise HTTPException(400, "période du rapport invalide") from exc

    @router.get("/api/marketing/cmo/rapport")
    def api_rapport(request: Request) -> JSONResponse:
        session = session_api(request)
        valeurs = _parametres_rapport(request)
        return JSONResponse({"ok": True, "resultat": lire_rapport(session, valeurs)}, headers=_NO_STORE)

    @router.get("/marketing/cmo/rapport", response_class=HTMLResponse)
    def page_rapport(request: Request) -> HTMLResponse:
        session = session_page(request)
        valeurs = _parametres_rapport(request)
        rapport = lire_rapport(session, valeurs)
        html = pages.gabarit("Acquisition observée", _rapport_html(rapport, prefixe),
                            prefixe=prefixe, session=session, actif="marketing")
        if len(html.encode("utf-8")) > marketing_rapport.MAX_OCTETS:
            raise HTTPException(409, "rendu HTML au-delà de la borne; consulter le rapport JSON privé")
        return HTMLResponse(html, headers=_NO_STORE)

    def strategies(session, *, projection=None):
        try:
            with cnx_factory() as cnx:
                return metier.lire_strategies_cmo(cnx, deps, session, projection=projection)
        except PermissionError as exc:
            raise HTTPException(403, "accès CMO retiré") from exc
        except (ValueError, TypeError, KeyError, ArithmeticError, RecursionError) as exc:
            raise HTTPException(409, "registre ou sources CMO invalides; aucune écriture") from exc

    @router.get("/api/marketing/cmo/strategies")
    def api_strategies(request: Request):
        session = session_api(request)
        if request.query_params:
            raise HTTPException(400, "aucun paramètre pour l’historique")
        return JSONResponse({"ok": True, "resultat": strategies(session)}, headers=_NO_STORE)

    @router.get("/api/marketing/cmo/strategies/contexte")
    def api_contexte(request: Request):
        session = session_api(request)
        valeurs = _parametres(request)
        plan = lire(session, valeurs)
        return JSONResponse({"ok": True, "resultat": strategies(session, projection=plan)}, headers=_NO_STORE)

    @router.get("/marketing/cmo/strategies/{programme_id}/reviser", response_class=HTMLResponse)
    def page_reviser(request: Request, programme_id: str):
        session = session_page(request)
        valeurs = _parametres(request)
        plan = lire(session, valeurs)
        courant = strategies(session, projection=plan)
        versions = courant["programmes"].get(programme_id)
        if not versions:
            raise HTTPException(404, "programme inconnu")
        c = versions[-1]["proposition"]["charge"]
        if len(c["objectifs"]) != 1 or len(c["actions"]) != 1:
            raise HTTPException(409, "la révision de plusieurs objectifs exige une saisie complète")
        contenu = _contenu(plan, prefixe) + _formulaire_strategie(
            courant, valeurs, prefixe, session, version=versions[-1],
        )
        return HTMLResponse(pages.gabarit("Réviser le programme CMO", contenu, prefixe=prefixe,
                                         session=session, actif="marketing"), headers=_NO_STORE)

    def ecrire_cmo(session, action, corps):
        try:
            with cnx_factory() as cnx:
                return metier.executer(cnx, deps, session, _NOMS_CMO[action], corps["arguments"],
                                       mutation_id=corps["mutation_id"])
        except PermissionError as exc:
            raise HTTPException(403, "autorité CMO retirée") from exc
        except (ValueError, TypeError, KeyError, ArithmeticError, RecursionError) as exc:
            raise HTTPException(409, "commande CMO refusée; relire sa version et ses sources") from exc

    async def recevoir_cmo(request, action, *, programme_id=None, api=False):
        session = await run_in_threadpool(ecriture_api if api else session_page, request)
        # Autorité DB avant transfert/décodage du corps, pas seulement le rôle dans le cookie.
        await run_in_threadpool(strategies, session)
        try:
            brut = await _corps_borne(request)
        except HTTPException as exc:
            raise HTTPException(exc.status_code, "commande CMO trop volumineuse") from exc
        try:
            if api:
                corps = _json_cmo(brut.decode("utf-8"))
            else:
                paires = parse_qs(brut.decode("utf-8"), keep_blank_values=True, max_num_fields=40, errors="strict")
                if any(len(v) != 1 for v in paires.values()):
                    raise ValueError("champ répété")
                champs = {k: v[0] for k, v in paires.items()}
                if not securite.csrf_valide(champs.pop("csrf", None), session):
                    raise HTTPException(403, "jeton CSRF invalide")
                corps = _commande_formulaire_cmo(action, champs)
            cmo_strategie._objet(corps, {"mutation_id", "arguments"})
            cmo_strategie.valider_commande(action, corps["arguments"])
            if programme_id is not None and corps["arguments"]["programme_id"] != programme_id:
                raise ValueError("programme de la route différent")
        except (ValueError, TypeError, KeyError, UnicodeError, ArithmeticError, RecursionError) as exc:
            raise HTTPException(400, "commande CMO fermée attendue") from exc
        resultat = await run_in_threadpool(ecrire_cmo, session, action, corps)
        if api:
            return JSONResponse({"ok": True, "resultat": resultat}, headers=_NO_STORE)
        return RedirectResponse(prefixe + "/marketing/cmo", status_code=303, headers=_NO_STORE)

    @router.post("/marketing/cmo/strategies")
    async def proposer_form(request: Request):
        return await recevoir_cmo(request, "proposer")

    @router.post("/api/marketing/cmo/strategies")
    async def proposer_api(request: Request):
        return await recevoir_cmo(request, "proposer", api=True)

    @router.post("/marketing/cmo/strategies/{programme_id}/decisions")
    async def decider_form(request: Request, programme_id: str):
        return await recevoir_cmo(request, "decider", programme_id=programme_id)

    @router.post("/api/marketing/cmo/strategies/{programme_id}/decisions")
    async def decider_api(request: Request, programme_id: str):
        return await recevoir_cmo(request, "decider", programme_id=programme_id, api=True)

    @router.post("/marketing/cmo/strategies/{programme_id}/revues")
    async def revoir_form(request: Request, programme_id: str):
        return await recevoir_cmo(request, "revoir", programme_id=programme_id)

    @router.post("/api/marketing/cmo/strategies/{programme_id}/revues")
    async def revoir_api(request: Request, programme_id: str):
        return await recevoir_cmo(request, "revoir", programme_id=programme_id, api=True)

    return router


def _formulaire_vide(prefixe: str) -> str:
    return (
        f'<p><a href="{pages.e(prefixe)}/marketing/cmo/couts">Coûts de campagne sur pièces M5</a></p>'
        f'<p><a href="{pages.e(prefixe)}/marketing/growth">Observations Growth déclarées</a></p>'
        '<section class="carte pile"><h2>Plan CMO préparatoire</h2>'
        f'<form method="get" action="{pages.e(prefixe)}/marketing/cmo" class="formulaire">'
        '<label>Date de départ <input type="date" name="date_depart" required value=""></label>'
        '<label>Début des faits observés <input type="date" name="debut" required value=""></label>'
        '<label>Fin des faits observés <input type="date" name="fin" required value=""></label>'
        '<button type="submit">Afficher les faits et proposer les fenêtres</button></form>'
        '<p>Choisissez explicitement les dates; aucun jour courant ni fait métier n’est deviné.</p></section>'
        + _formulaire_rapport(prefixe)
    )


def _formulaire_rapport(prefixe: str) -> str:
    return (
        '<section class="carte pile"><h2>Rapport d’acquisition observée</h2>'
        '<p>Consultez la cohorte M7, les statuts CRM courants et les sources financières disponibles. '
        'Les données manquantes restent inconnues; aucun ROI ni effet causal n’est calculé.</p>'
        f'<form method="get" action="{pages.e(prefixe)}/marketing/cmo/rapport" class="formulaire">'
        '<label>Début de période métier <input type="date" name="debut" required></label>'
        '<label>Fin de période métier <input type="date" name="fin" required></label>'
        '<button type="submit">Lire le rapport privé</button></form></section>'
    )


def _rapport_html(rapport: Mapping[str, Any], prefixe: str) -> str:
    periode, observation = rapport["periode_metier"], rapport["observation_source"]
    morceaux = [f'<p><a href="{pages.e(prefixe)}/marketing/cmo">Retour au CMO</a></p>',
                '<section class="carte pile"><h2>Acquisition observée</h2>',
                f'<p>Période métier : {_texte(periode["debut"])} au {_texte(periode["fin"])}. '
                f'Lecture : {_texte(rapport["lue_le"])}.</p>',
                '<p>Les faits étaient disponibles à la lecture, y compris les corrections arrivées tard. '
                'Ce rapport ne décrit pas ce qui était connu à la fin de la période. Historique non scellé.</p>',
                f'<p>Dernière insertion M7 : {_texte(observation.get("dernier_cree_le_sql"), "Inconnue")} '
                f'({_texte(observation.get("fuseau_cree_le_sql"))}).</p>',
                '<h3>Campagnes et marge M5 publiée observée · CAD</h3>']
    if not rapport["campagnes"]:
        morceaux.append('<p>Aucune campagne observée; couverture inconnue, pas une preuve de zéro activité.</p>')
    for campagne in rapport["campagnes"]:
        morceaux.append(
            f'<article><h4>{_texte(campagne["source"], "Source inconnue")} · '
            f'{_texte(campagne["campagne"], "Campagne inconnue")}</h4>'
            f'<p>Leads associés observés : {_texte(campagne["leads_associes_observes"])} · '
            f'Devis acceptés : {_texte(campagne["devis_acceptes"])} · '
            f'Marge publiée observée CAD : {_texte(campagne["marge_constatee_M5_cad"], "Inconnue")}.</p>'
            '<p>Dépenses publicitaires, coût par lead et ROI : inconnus.</p>'
            f'<p>Manques : {", ".join(_texte(m) for m in campagne["manque"])}</p></article>'
        )
        refs = [rapport["references"][i] for i in campagne["references_indices"]]
        morceaux.append('<p>Références : ' + '; '.join(
            f'{_texte(r["type"])} : {_texte(r["reference"])}' for r in refs
        ) + '</p>')
    for cle, titre in (("crm_courant", "Statuts CRM courants"),
                       ("contenus_cumules", "Contenus M8 cumulés · sans fenêtre de période"),
                       ("finance_courante", "Finance M5 courante · CAD, distincte des faits publiés")):
        section = rapport[cle]
        morceaux.append(f'<h3>{titre}</h3><p>Source : {_texte(section["statut"])}.</p><ul>')
        for ligne in section["lignes"]:
            if cle == "crm_courant":
                texte = f'{_texte(ligne["lead_id"])} : {_texte(ligne["statut"])}'
            elif cle == "contenus_cumules":
                texte = (f'{_texte(ligne["utm_content"], "Clé inconnue")} · {_texte(ligne["canal"])} : '
                         f'leads {_texte(ligne["leads"], "Inconnus")}, '
                         f'devis acceptés {_texte(ligne["devis_acceptes"], "Inconnus")}')
            else:
                texte = (f'{_texte(ligne["devis_id"])} : {_texte(ligne["statut"])} · '
                         f'prix facture CAD {_texte(ligne.get("prix_facture"), "Inconnu")} · '
                         f'marge réelle CAD {_texte(ligne.get("marge_reelle"), "Inconnue")}')
                if "prix_definitif" in ligne:
                    texte += ' · prix définitif' if ligne["prix_definitif"] else ' · prix provisoire'
                    texte += ' · trace à jour' if ligne["trace"]["a_jour"] else ' · trace non à jour'
                    texte += ' · manques : ' + ', '.join(_texte(m) for m in ligne.get("manque", []))
            morceaux.append(f'<li>{texte}</li>')
        morceaux.append('</ul>')
    morceaux.append('<h3>Références observées</h3><ul>')
    morceaux.extend(f'<li>{_texte(r["type"])} : {_texte(r["reference"])}</li>' for r in rapport["references"])
    morceaux.append('</ul><h3>Omissions du rendu</h3><ul>')
    morceaux.extend(f'<li>{_texte(k)} : {_texte(v)}</li>' for k, v in rapport["omissions"].items())
    morceaux.append('</ul><h3>Limites</h3><ul>')
    morceaux.extend(f'<li>{_texte(limite)}</li>' for limite in rapport["limites"])
    morceaux.append('</ul></section>')
    return ''.join(morceaux)


def _texte(valeur: Any, defaut: str = "Indisponible") -> str:
    return pages.e(valeur if isinstance(valeur, (str, int, float)) and not isinstance(valeur, bool) else defaut)


def _contenu(plan: Mapping[str, Any], prefixe: str) -> str:
    periode = plan.get("periode_observee")
    periode = periode if isinstance(periode, Mapping) else {}
    sections = [
        f'<p><a href="{pages.e(prefixe)}/marketing/growth">Observations Growth déclarées</a></p>',
        '<section class="carte pile"><h2>Plan CMO préparatoire</h2>',
        f'<form method="get" action="{pages.e(prefixe)}/marketing/cmo" class="formulaire">',
        '<label>Date de départ <input type="date" name="date_depart" required '
        f'value="{_texte(plan.get("date_depart"), "")}"></label>',
        '<label>Début des faits observés <input type="date" name="debut" required '
        f'value="{_texte(periode.get("debut"), "")}"></label>',
        '<label>Fin des faits observés <input type="date" name="fin" required '
        f'value="{_texte(periode.get("fin"), "")}"></label>',
        '<button type="submit">Actualiser la projection</button></form>',
        f"<p>Départ : {_texte(plan.get('date_depart'))} · Période de faits : "
        f"{_texte((plan.get('periode_observee') or {}).get('debut'))} au "
        f"{_texte((plan.get('periode_observee') or {}).get('fin'))}</p>",
        '<p class="note">Les fenêtres organisent les actions; elles ne constituent pas une prévision. '
        "Les suggestions et leurs dates proposées restent à arbitrer. Aucune publication ni écriture n'est faite.</p>",
        f"<p>Marque : {_texte((plan.get('profil_marque') or {}).get('statut'))}; révision "
        f"{_texte((plan.get('profil_marque') or {}).get('revision'), 'Aucune')}.</p>",
        f"<p>Couverture de performance : {_texte((plan.get('performance') or {}).get('couverture'), 'INCONNUE')}.</p>",
    ]
    manques = plan.get("manques")
    if isinstance(manques, list) and manques:
        liste_manques = "".join(f"<li>{_texte(item)}</li>" for item in manques)
        sections.append(f"<h3>Manques observés</h3><ul>{liste_manques}</ul>")
    else:
        sections.append("<h3>Manques observés</h3><p>Aucun manque déclaré par la source.</p>")
    sections.append("<h3>Fenêtres de travail</h3>")
    fenetres = plan.get("fenetres")
    if not isinstance(fenetres, list):
        sections.append('<p class="message message-alerte">Fenêtres indisponibles.</p>')
    else:
        for fenetre in fenetres:
            if not isinstance(fenetre, Mapping):
                continue
            cal = fenetre.get("calendrier")
            cal = cal if isinstance(cal, Mapping) else {}
            sections.append(
                f"<article><h4>{_texte(fenetre.get('id'))} · {_texte(fenetre.get('debut'))} au "
                f"{_texte(fenetre.get('fin'))}</h4><p>Calendrier : {_texte(cal.get('statut'))}</p></article>"
            )
    actions = plan.get("actions")
    sections.append("<h3>Actions suggérées à arbitrer</h3>")
    if not isinstance(actions, list) or not actions:
        sections.append("<p>Aucune action déterministe déclenchée par les faits et manques observés.</p>")
    else:
        sections.append("<ul>")
        for action in actions:
            if not isinstance(action, Mapping):
                continue
            sections.append(
                f"<li><strong>{_texte(action.get('fenetre'))}</strong> — {_texte(action.get('action'))} "
                f"<span>{_texte(action.get('motif'))}</span> · date proposée pour arbitrage : "
                f"{_texte(action.get('date_arbitrage'))} · {_texte(action.get('statut'))} "
                f"<small>Sources : {_sources_html(action.get('sources'))}</small></li>"
            )
        sections.append("</ul>")
    performance = plan.get("performance")
    campaigns = performance.get("campagnes") if isinstance(performance, Mapping) else None
    sections.append("<h3>Campagnes observées</h3>")
    if isinstance(campaigns, list) and campaigns:
        sections.append('<div class="table-defilante"><table><thead><tr><th>Source</th><th>Campagne</th>'
                        '<th>Leads M2</th><th>Devis acceptés M3</th><th>Marge observée M5 CAD</th>'
                        '<th>Coûts</th><th>ROI</th><th>Manques</th></tr></thead><tbody>')
        for item in campaigns:
            if not isinstance(item, Mapping):
                continue
            item_missing = item.get("manque")
            if isinstance(item_missing, list):
                missing_html = "<ul>" + "".join(f"<li>{_texte(m)}</li>" for m in item_missing) + "</ul>"
            else:
                missing_html = "Inconnu"
            sections.append(
                "<tr>"
                f"<td>{_texte(item.get('source'), 'Inconnue')}</td><td>{_texte(item.get('campagne'), 'Inconnue')}</td>"
                f"<td>{_texte(item.get('leads_associes_observes'))}</td>"
                f"<td>{_texte(item.get('devis_acceptes'))}</td>"
                f"<td>{_texte(item.get('marge_constatee_M5_cad'))}</td>"
                f"<td>{_texte(item.get('cout_ads_cad'))}</td><td>{_texte(item.get('roi'))}</td>"
                f"<td>{missing_html}</td></tr>"
            )
        sections.append("</tbody></table></div>")
        sections.append("<h4>Références campagne</h4><ul>")
        for item in campaigns:
            if not isinstance(item, Mapping):
                continue
            refs = item.get("source_refs")
            if not isinstance(refs, list):
                continue
            for ref in refs:
                if isinstance(ref, Mapping):
                    sequence = ref.get("sequence")
                    suffixe = f" · séquence {_texte(sequence)}" if type(sequence) is int else ""
                    sections.append(
                        f"<li>{_texte(ref.get('type'), 'Source')} : "
                        f"{_texte(ref.get('reference'))}{suffixe}</li>"
                    )
        sections.append("</ul>")
    else:
        sections.append("<p>Aucune campagne attribuable observée sur la période; cela ne prouve pas zéro activité.</p>")
    limites_sources = plan.get("sources_tronquees")
    if isinstance(limites_sources, Mapping) and any(limites_sources.values()):
        sections.append(
            '<p class="message message-alerte">Certaines références ou listes sources ont été bornées; '
            'les compteurs de total et marqueurs de troncature sont visibles dans la réponse JSON.</p>'
        )
    limits = plan.get("limites")
    if isinstance(limits, list):
        sections.append("<h3>Limites</h3><ul>" + "".join(f"<li>{_texte(item)}</li>" for item in limits) + "</ul>")
    sections.append("</section>")
    return "".join(sections) + _formulaire_rapport(prefixe)


def _sources_html(sources: Any) -> str:
    if not isinstance(sources, list) or not sources:
        return "aucune référence détaillée"
    details: list[str] = []
    for source in sources:
        if not isinstance(source, Mapping):
            continue
        outil = _texte(source.get("outil"), "Source")
        references = source.get("references")
        refs = ", ".join(_texte(item) for item in references) if isinstance(references, list) else ""
        details.append(f"{outil}" + (f" ({refs})" if refs else ""))
    return pages.e("; ".join(details)) if not details else "; ".join(details)

_NOMS_CMO = {"proposer": "m7_proposer_strategie_humaine", "decider": "m7_decider_strategie_humaine",
             "revoir": "m7_revoir_strategie_humaine"}


def _json_cmo(texte):
    return json.loads(texte, object_pairs_hook=_objet_sans_doublon)


def _cache_cmo(nom, valeur):
    texte = json.dumps(valeur, ensure_ascii=False, allow_nan=False) if isinstance(valeur, (dict, list)) else str(valeur)
    return f'<input type="hidden" name="{pages.e(nom)}" value="{pages.e(texte)}">'


def _champ_cmo(nom, label, valeur="", maximum=400):
    return (f'<label>{pages.e(label)}<input name="{pages.e(nom)}" maxlength="{maximum}" '
            f'value="{pages.e(str(valeur))}" required></label>')


def _select_observation(contexte, *, nom="baseline"):
    options = ['<option value="">Inconnue / aucune observation sélectionnée</option>']
    for o in contexte["observations"]:
        ref = json.dumps({k: o[k] for k in ("observation_id", "empreinte")})
        label = (f'{o["observation_id"]}: {o["metrique"]} {o["valeur"]} {o["unite"]} '
                 f'({o["periode"]["debut"]}–{o["periode"]["fin"]})')
        options.append(f'<option value="{pages.e(ref)}">{pages.e(label)}</option>')
    borne = ('<p>100 observations proposées ici; les autres restent consultables dans Growth.</p>'
             if contexte["observations_selecteur_limite"] else "")
    return f'<label>Observation déclarée<select name="{pages.e(nom)}">{"".join(options)}</select></label>' + borne


def _formulaire_strategie(courant, parametres, prefixe, session, *, version=None):
    c = version["proposition"]["charge"] if version else None
    objectif = c["objectifs"][0] if c else {}
    action = c["actions"][0] if c else {}
    caches = {"csrf": session.csrf, "mutation_id": str(uuid.uuid4()), "tete": courant["tete"],
              "growth_tete": courant["growth_tete"], "parametres": parametres,
              "projection_attendue": courant["projection_attendue"],
              "programme_id": c["programme_id"] if c else str(uuid.uuid4()),
              "revision_attendue": c["revision"] if c else 0,
              "empreinte_revision_attendue": version["proposition"]["empreinte"] if c else "",
              "objectif_id": objectif.get("objectif_id", "objectif-principal"),
              "action_id": action.get("action_id", "action-principale")}
    champs = "".join(_cache_cmo(k, v) for k, v in caches.items())
    champs += _champ_cmo("titre", "Nom du programme", c["titre"] if c else "", 200)
    champs += _champ_cmo("hypothese", "Hypothèse déclarée", c["hypothese"] if c else "")
    champs += _champ_cmo("intitule", "Objectif", objectif.get("intitule", ""), 200)
    champs += _champ_cmo("metrique", "Métrique littérale", objectif.get("metrique", ""), 200)
    champs += _champ_cmo("unite", "Unité littérale", objectif.get("unite", ""), 200)
    cible = objectif.get("cible")
    champs += ('<label>Cible déclarée (facultative)<input name="cible" maxlength="40" value="'
               + pages.e(str(cible) if cible is not None else "") + '"></label>')
    champs += _select_observation(courant)
    champs += _champ_cmo("livrable", "Livrable attendu", action.get("livrable", ""))
    champs += _champ_cmo("responsable", "Identifiant du responsable interne actif", action.get("responsable", ""), 64)
    champs += _champ_cmo(
        "capacite_declaree", "Capacité déclarée, sans disponibilité M4 garantie", action.get("capacite_declaree", ""),
    )
    champs += ('<label>Fenêtre<select name="fenetre">'
               + "".join(f'<option>{f}</option>' for f in ("J1-30", "J31-60", "J61-90")) + '</select></label>')
    return ('<section class="carte"><h3>Proposer une version du programme CMO</h3>'
            '<p>Saisie simple : un objectif et une action. La baseline doit être sélectionnée explicitement; '
            'inconnue ne vaut pas zéro. Une révision n’hérite d’aucune approbation. Source déclarée non vérifiée.</p>'
            f'<form method="post" action="{pages.e(prefixe)}/marketing/cmo/strategies">{champs}'
            '<button type="submit">Conserver la proposition</button></form></section>')


def _commande_formulaire_cmo(action, f):
    communs = {"mutation_id", "programme_id", "tete", "growth_tete"}
    if action == "proposer":
        attendus = communs | {"revision_attendue", "empreinte_revision_attendue", "parametres", "projection_attendue",
                             "titre", "hypothese", "objectif_id", "action_id", "intitule", "metrique", "unite", "cible",
                             "baseline", "livrable", "responsable", "capacite_declaree", "fenetre"}
    else:
        attendus = communs | {"revision", "empreinte_revision"} | (
            {"decision", "motif", "projection_attendue"} if action == "decider" else
            {"debut", "fin", "conclusion", "observation"}
        )
    cmo_strategie._objet(f, attendus)
    a = {"programme_id": f["programme_id"], "tete": _json_cmo(f["tete"]), "growth_tete": _json_cmo(f["growth_tete"])}
    if action == "proposer":
        a.update({k: f[k] for k in ("titre", "hypothese", "projection_attendue")})
        a.update(revision_attendue=int(f["revision_attendue"]),
                 empreinte_revision_attendue=f["empreinte_revision_attendue"] or None,
                 parametres=_json_cmo(f["parametres"]),
                 objectifs=[{k: f[k] for k in ("objectif_id", "intitule", "metrique", "unite")} | {
                     "cible": float(f["cible"]) if f["cible"] else None,
                     "baseline": _json_cmo(f["baseline"]) if f["baseline"] else None,
                 }], actions=[{k: f[k] for k in (
                     "action_id", "objectif_id", "fenetre", "livrable", "responsable", "capacite_declaree",
                 )}])
    else:
        a.update(revision=int(f["revision"]), empreinte_revision=f["empreinte_revision"])
        if action == "decider":
            a.update({k: f[k] for k in ("decision", "motif", "projection_attendue")})
        else:
            a.update({k: f[k] for k in ("debut", "fin", "conclusion")})
            a["observations"] = [_json_cmo(f["observation"])] if f["observation"] else []
    return {"mutation_id": f["mutation_id"], "arguments": a}


def _historique_cmo(courant, prefixe, session, *, parametres=None):
    sections = ['<section class="carte"><h3>Programmes CMO conservés</h3><p>Déclarations et arbitrages humains; '
                'aucun ROI, calcul de croissance ou publication. L’affectation ne donne aucun droit.</p>']
    for programme, versions in courant["programmes"].items():
        for v in versions:
            e, d = v["proposition"], v["decision"]
            c = e["charge"]
            statut = d["charge"]["decision"] if d else "proposé"
            sections.append(f'<h4>{pages.e(c["titre"])} — version {c["revision"]}: {pages.e(statut)}</h4>')
            sections.append(
                f'<p>{pages.e(c["hypothese"])} — saisie par {pages.e(e["auteur"]["personne"])} '
                f'à {pages.e(e["horodatage"])}</p>'
            )
            for o in c["objectifs"]:
                s = c["baselines"][o["objectif_id"]]
                valeur = "inconnue" if s is None else str(s["valeur"]) + " " + s["unite"]
                cible = "inconnue" if o["cible"] is None else str(o["cible"]) + " " + o["unite"]
                sections.append(f'<p>{pages.e(o["intitule"])} : baseline déclarée {pages.e(valeur)}; '
                                f'cible déclarée {pages.e(cible)}.</p>')
            for action in c["actions"]:
                sections.append(
                    f'<p>{pages.e(action["fenetre"])} : {pages.e(action["livrable"])} — '
                    f'{pages.e(action["responsable"])}; capacité déclarée {pages.e(action["capacite_declaree"])}</p>'
                )
            for revue in v["revues"]:
                r = revue["charge"]
                sections.append(f'<p>Revue {pages.e(r["debut"])}–{pages.e(r["fin"])} : {pages.e(r["conclusion"])}; '
                                f'{len(r["observations"])} observation(s) déclarée(s), sans vérification externe.</p>')
            query = urlencode(c["parametres"])
            cible_url = prefixe + "/marketing/cmo/strategies/" + quote(programme, safe="") + "/reviser?" + query
            if v is versions[-1] and len(c["objectifs"]) == len(c["actions"]) == 1:
                sections.append(f'<p><a href="{pages.e(cible_url)}">Préparer une nouvelle révision</a></p>')
            if parametres is None:
                continue
            caches = {"csrf": session.csrf, "mutation_id": str(uuid.uuid4()), "programme_id": programme,
                      "tete": courant["tete"], "growth_tete": courant["growth_tete"],
                      "revision": c["revision"], "empreinte_revision": e["empreinte"]}
            chemin = prefixe + "/marketing/cmo/strategies/" + quote(programme, safe="")
            if v is versions[-1] and d is None and c["parametres"] == parametres:
                champs = "".join(_cache_cmo(k, val) for k, val in caches.items())
                champs += _cache_cmo("projection_attendue", courant["projection_attendue"])
                champs += ('<select name="decision"><option value="approuver">Approuver</option>'
                           '<option value="rejeter">Refuser</option></select>')
                champs += _champ_cmo("motif", "Motif de la décision humaine")
                sections.append(f'<form method="post" action="{pages.e(chemin)}/decisions">{champs}'
                                '<button>Décider (propriétaire)</button></form>')
            if d and d["charge"]["decision"] == "approuver":
                caches["mutation_id"] = str(uuid.uuid4())
                champs = "".join(_cache_cmo(k, val) for k, val in caches.items())
                champs += _cache_cmo("debut", parametres["debut"]) + _cache_cmo("fin", parametres["fin"])
                champs += _champ_cmo("conclusion", "Conclusion déclarée de la revue", maximum=800)
                champs += _select_observation(courant, nom="observation")
                sections.append(f'<form method="post" action="{pages.e(chemin)}/revues">{champs}'
                                '<button>Conserver la revue humaine</button></form>')
    if not courant["programmes"]:
        sections.append('<p>Aucun programme conservé. Choisir les dates pour proposer un objectif et une action.</p>')
    sections.append('</section>')
    resultat = "".join(sections)
    if len(resultat.encode("utf-8")) > 512 * 1024:
        raise HTTPException(409, "historique trop grand pour la page; consulter sa lecture JSON privée")
    return resultat
