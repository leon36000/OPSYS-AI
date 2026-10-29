"""Tableau de bord exécutif M9 (Direction IA) : briefings, sources, risques, scénarios, décisions, actions et suites.

Pages HTML servies à l'admin authentifié seulement. Presque tout est LECTURE : chaque panneau appelle un outil M9 de
lecture par ``metier.executer`` (rôle relu en base à chaque appel) et se dégrade seul — un panneau refusé dit son code,
il ne
cache ni n'invente rien. Aucune date n'est fabriquée : la personne saisit la connaissance et le jour ; les formulaires
ne
préremplissent rien.

Deux commandes internes seulement, chacune avec jeton CSRF, corps borné et ``mutation_id`` idempotent : noter un suivi
sur
un plan et annuler un plan. Une approbation d'action ne se décide pas ici : le lien renvoie à la file d'approbation
native.
Le rendu des preuves est un rendu structuré générique, entièrement échappé, borné en profondeur, en longueur et en
taille de
page ; une page trop grande est refusée, jamais tronquée en silence.
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from . import frontoffice_marketing, metier, pages
from .securite import Session

_INSTANT = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})")
_JOUR = re.compile(r"\d{4}-\d{2}-\d{2}")
_DEPART = re.compile(r"0|[1-9][0-9]{0,8}")
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:\-]{0,127}")
_CODE_REFUS = re.compile(r"REJ-[A-Z0-9][A-Z0-9-]{0,80}")
_JOURS = re.compile(r"[0-9]{1,4}")
_GRANULARITES = frozenset({"hebdomadaire", "mensuelle", "trimestrielle"})
_MAX_PAGE = 256 * 1024
_MAX_PROFONDEUR = 6
_MAX_ELEMENTS = 60
_MAX_TEXTE = 400
_MAX_JSON_SCENARIO = 4096
_PARAMS = {
    "accueil": frozenset({"connaissance", "jour"}),
    "risques": frozenset({"connaissance", "perime_apres_jours", "depart"}),
    "sources": frozenset({"reference", "depart", "lecture_id", "vue"}),
    "plans": frozenset({"connaissance", "jour"}),
    "actions": frozenset({"action_id"}),
    "conseil": frozenset({"session_id", "depart"}),
    "revues": frozenset({"depart", "granularite", "vue"}),
    "revue": frozenset({"index", "depart"}),
    "veille": frozenset({"connaissance", "decision_ref"}),
}
e = pages.e


class _Refus(Exception):
    """Refus de lecture M9 : seul un code REJ- est conservé, jamais le texte brut de l'exception."""

    def __init__(self, code: str, *, invalide: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.invalide = invalide


def _code(texte: str) -> str:
    trouve = _CODE_REFUS.search(texte)
    return trouve.group(0) if trouve else ""


def _valeurs(request: Request, permis: frozenset[str]) -> dict[str, str]:
    valeurs: dict[str, str] = {}
    for cle, valeur in request.query_params.multi_items():
        if cle not in permis:
            raise HTTPException(400, "paramètre inconnu refusé")
        if cle in valeurs:
            raise HTTPException(400, "paramètre répété refusé")
        if len(valeur) > 256:
            raise HTTPException(400, "paramètre trop long refusé")
        valeurs[cle] = valeur
    return valeurs


def _exiger(valeurs: Mapping[str, str], motif: re.Pattern[str], *noms: str) -> None:
    for nom in noms:
        if nom in valeurs and motif.fullmatch(valeurs[nom]) is None:
            raise HTTPException(400, f"{nom} : format invalide")


# -- rendu structuré générique, échappé et borné -----------------------------------------------------------------------
def _scalaire(valeur: object) -> str:
    if valeur is None:
        return '<span class="vide">—</span>'
    texte = valeur if isinstance(valeur, str) else json.dumps(valeur, ensure_ascii=False)
    suite = ""
    if len(texte) > _MAX_TEXTE:
        suite = f" … ({len(texte) - _MAX_TEXTE} caractères non affichés)"
        texte = texte[:_MAX_TEXTE]
    return f"<code>{e(texte)}</code>{e(suite)}"


def rendre(valeur: object, profondeur: int = 0) -> str:
    """Rendu générique d'une preuve : tout est échappé, la profondeur et le nombre d'éléments sont bornés."""
    if profondeur > _MAX_PROFONDEUR:
        return '<span class="vide">(profondeur maximale atteinte)</span>'
    if isinstance(valeur, Mapping):
        lignes = [f"<dt>{e(cle)}</dt><dd>{rendre(contenu, profondeur + 1)}</dd>" for cle, contenu in valeur.items()]
        return f'<dl class="preuve">{"".join(lignes)}</dl>' if lignes else '<span class="vide">{}</span>'
    if isinstance(valeur, list):
        if not valeur:
            return '<span class="vide">[]</span>'
        elements = "".join(f"<li>{rendre(x, profondeur + 1)}</li>" for x in valeur[:_MAX_ELEMENTS])
        reste = len(valeur) - _MAX_ELEMENTS
        note = f'<p class="vide">{reste} élément(s) non affiché(s) : utiliser la pagination.</p>' if reste > 0 else ""
        return f"<ol>{elements}</ol>{note}"
    return _scalaire(valeur)


def _refus_de_reponse(reponse: object) -> str | None:
    """Code du refus d'une réponse d'outil (échec d'exécution ou verdict non accepté), ``None`` si acceptée."""
    if not isinstance(reponse, Mapping):
        return "REJ-DIRECTION-REPONSE-INVALIDE"
    if reponse.get("ok") is False:
        details = reponse.get("details")
        return _code(str(details[0] if isinstance(details, list) and details else details)) or "REJ-DIRECTION-ECHEC"
    resultat = reponse.get("resultat")
    if isinstance(resultat, Mapping) and resultat.get("accepte") is False:
        verdict = resultat.get("verdict")
        code = verdict.get("code") if isinstance(verdict, Mapping) else None
        return (_code(code) if isinstance(code, str) else "") or "REJ-DIRECTION-REFUS"
    return None


def _gravite(valeur: object) -> str:
    return {"ELEVE": "badge-danger", "MOYEN": "badge-alerte", "FAIBLE": "", "INCONNU": "badge-alerte"}.get(
        str(valeur), ""
    )


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
    verifier_formulaire: Callable[[Mapping[str, str], Session], None],
) -> APIRouter:
    del session_api, ecriture_api, objet_json  # formulaires HTML seulement : jeton CSRF dans le champ ``csrf``
    router = APIRouter()

    def lire(session: Session, nom: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        try:
            with cnx_factory() as cnx:
                reponse = metier.executer(cnx, deps, session, nom, arguments)
        except PermissionError as exc:
            raise HTTPException(403, "accès métier refusé") from exc
        except KeyError as exc:
            raise HTTPException(404, "lecture M9 indisponible") from exc
        except ValueError as exc:
            code = _code(str(exc))
            if "IDENTITE" in code:
                raise HTTPException(403, "accès métier refusé") from exc
            raise _Refus(code, invalide=True) from exc
        ok, charge, erreur = frontoffice_marketing.resultat_metier(reponse)
        code: str | None = None
        if not ok:
            code = _code(f"{erreur.get('code', '')} {erreur.get('message', '')}")
        elif isinstance(charge, Mapping) and charge.get("accepte") is False:
            verdict = charge.get("verdict")
            code = _code(str(verdict.get("code", ""))) if isinstance(verdict, Mapping) else ""
        elif not isinstance(charge, Mapping):
            code = ""
        if code is not None:
            if "IDENTITE" in code:
                raise HTTPException(403, "accès métier refusé")
            raise _Refus(code)
        return charge

    def admin(session: Session) -> None:
        if "admin" not in session.roles:
            raise HTTPException(403, "accès métier refusé")

    def lien(chemin: str, **parametres: Any) -> str:
        cible = f"{prefixe}/direction{chemin}"
        return f"{cible}?{urlencode(parametres)}" if parametres else cible

    def page(session: Session, titre: str, contenu: str, statut: int = 200) -> HTMLResponse:
        reponse = HTMLResponse(
            pages.gabarit(titre, contenu, prefixe=prefixe, session=session, actif="direction"), status_code=statut
        )
        if len(reponse.body) > _MAX_PAGE:
            return HTMLResponse(
                pages.gabarit(
                    titre,
                    '<p class="message message-erreur">REJ-DIRECTION-BORNE : page trop grande, aucune troncature. '
                    "Réduire la fenêtre ou paginer.</p>",
                    prefixe=prefixe,
                    session=session,
                    actif="direction",
                ),
                status_code=409,
            )
        return reponse

    def suite(href: str, libelle: str = "Page suivante") -> str:
        return f'<p><a href="{e(href)}">{e(libelle)}</a></p>'

    def navigation(**parametres: Any) -> str:
        entrees = [
            ("", "Tableau de bord", ("connaissance", "jour")),
            ("/risques", "Risques", ("connaissance",)),
            ("/sources", "Sources", ()),
            ("/plans", "Plans et suites", ("connaissance", "jour")),
            ("/actions", "Actions et approbations", ()),
            ("/revues", "Briefings et revues", ()),
            ("/veille", "Veille", ("connaissance",)),
            ("/scenarios", "Scénarios", ()),
        ]
        items = []
        for chemin, libelle, cles in entrees:
            transmis = {c: parametres[c] for c in cles if c in parametres}
            items.append(f'<a href="{e(lien(chemin, **transmis))}">{e(libelle)}</a>')
        return f'<nav class="sous-nav" aria-label="Direction">{" · ".join(items)}</nav>'

    def refus_html(message: str, code: str, retour: str, libelle: str) -> str:
        suffixe = f" <code>{e(code)}</code>" if code else ""
        return (
            f'<section><p class="message message-erreur" role="alert">{e(message)}{suffixe}</p>'
            f'<p><a href="{e(retour)}">{e(libelle)}</a></p></section>'
        )

    def formulaire_dates(action: str, avec_jour: bool, connaissance: str, jour: str, extra: str = "") -> str:
        champ_jour = (
            f'<label>Jour civil <input name="jour" required pattern="\\d{{4}}-\\d{{2}}-\\d{{2}}" '
            f'placeholder="AAAA-MM-JJ" value="{e(jour)}"></label> '
            if avec_jour
            else ""
        )
        return (
            f'<form method="get" action="{e(action)}"><fieldset><legend>Instant de connaissance</legend>'
            '<label>Connaissance (fuseau explicite) <input name="connaissance" required size="30" '
            f'placeholder="2026-10-28T13:00:00Z" value="{e(connaissance)}"></label> {champ_jour}{extra}'
            '<button type="submit">Afficher</button></fieldset>'
            "<p>Aucune date n'est préremplie : M9 n'a pas d'horloge, la personne dit à quel instant elle veut voir "
            "l'état.</p>"
            "</form>"
        )

    # -- accueil
    # --------------------------------------------------------------------------------------------------------
    def panneau(titre: str, lien_detail: str, produire: Callable[[], str]) -> str:
        try:
            corps = produire()
        except _Refus as refus:
            corps = (
                '<p class="message message-erreur" role="alert">Lecture refusée par M9. '
                f"<code>{e(refus.code)}</code></p>"
            )
        except HTTPException as exc:
            if exc.status_code == 403:
                raise
            corps = f'<p class="message message-erreur" role="alert">Panneau indisponible ({exc.status_code}).</p>'
        return (
            f'<section class="panneau"><h2>{e(titre)}</h2>{corps}'
            f'<p><a href="{e(lien_detail)}">Voir le détail et les preuves</a></p></section>'
        )

    @router.get("/direction", response_class=HTMLResponse)
    def accueil(request: Request) -> HTMLResponse:
        session = session_page(request)
        admin(session)
        valeurs = _valeurs(request, _PARAMS["accueil"])
        _exiger(valeurs, _INSTANT, "connaissance")
        _exiger(valeurs, _JOUR, "jour")
        if not valeurs:
            return page(session, "Direction IA", formulaire_dates(lien(""), True, "", ""))
        if set(valeurs) != {"connaissance", "jour"}:
            raise HTTPException(400, "connaissance et jour requis ensemble")
        connaissance, jour = valeurs["connaissance"], valeurs["jour"]

        def salle() -> str:
            s = lire(session, "m9_salle_de_guerre", {"reference": connaissance})
            couverture = s.get("couverture") if isinstance(s.get("couverture"), Mapping) else {}
            manques = s.get("manques") if isinstance(s.get("manques"), list) else []
            decisions = s.get("decisions_en_attente") if isinstance(s.get("decisions_en_attente"), Mapping) else {}
            return (
                f"<p>Couverture complète : <strong>{'oui' if couverture.get('complete') is True else 'non'}</strong> · "
                f"sources manquantes ou douteuses : <strong>{len(manques)}</strong> · décisions de suivi en attente : "
                f"{_scalaire(decisions.get('total'))} · conseils en cours : "
                f"{_scalaire(s.get('conseils_en_cours_total'))}</p>"
            )

        def risques() -> str:
            r = lire(session, "m9_radar_risques", {"connaissance": connaissance})
            liste = r.get("risques") if isinstance(r.get("risques"), list) else []
            lignes = "".join(
                f'<li><span class="badge {e(_gravite(x.get("gravite")))}">{e(x.get("gravite"))}</span> '
                f"{e(x.get('domaine'))} — {e(x.get('sujet'))} <em>({e(x.get('statut'))})</em></li>"
                for x in liste[:5]
                if isinstance(x, Mapping)
            )
            non_evaluees = r.get("regles_non_evaluees") if isinstance(r.get("regles_non_evaluees"), list) else []
            return (
                f"<p>Risques signalés : <strong>{_scalaire(r.get('total_risques'))}</strong> · règles non évaluées "
                f"(risque inconnu, pas nul) : <strong>{len(non_evaluees)}</strong></p><ul>{lignes}</ul>"
            )

        def previsions() -> str:
            p = lire(session, "m9_previsions_consolidees", {"connaissance": connaissance})
            domaines = p.get("domaines") if isinstance(p.get("domaines"), list) else []
            lignes = "".join(
                f"<li>{e(d.get('domaine'))} : <strong>{e(d.get('statut'))}</strong> ({e(d.get('proprietaire'))})</li>"
                for d in domaines
                if isinstance(d, Mapping)
            )
            return f"<ul>{lignes}</ul>"

        def plans() -> str:
            p = lire(session, "m9_lire_plans", {"connaissance": connaissance, "jour": jour})
            liste = p.get("plans") if isinstance(p.get("plans"), list) else []
            lignes = "".join(
                f"<li>{e(x.get('plan_id'))} — <strong>{e(x.get('statut'))}</strong>, échéance {e(x.get('echeance'))}, "
                f"{len(x.get('sources_changees') or [])} source(s) changée(s)</li>"
                for x in liste[:8]
                if isinstance(x, Mapping)
            )
            return f"<p>Plans : {len(liste)}</p><ul>{lignes}</ul>"

        def actions() -> str:
            a = lire(session, "m9_lire_actions", {})
            etats = a.get("par_etat") if isinstance(a.get("par_etat"), Mapping) else {}
            texte = ", ".join(f"{e(k)} : {e(v)}" for k, v in etats.items()) or "aucune action proposée"
            return f"<p>Actions proposées ({_scalaire(a.get('total'))}) — {texte}</p>"

        def veille() -> str:
            v = lire(session, "m9_lire_veille", {"connaissance": connaissance})
            docs = v.get("documents") if isinstance(v.get("documents"), list) else []
            statuts: dict[str, int] = {}
            for d in docs:
                if isinstance(d, Mapping):
                    statuts[str(d.get("statut_courant"))] = statuts.get(str(d.get("statut_courant")), 0) + 1
            texte = ", ".join(f"{e(k)} : {e(n)}" for k, n in sorted(statuts.items())) or "aucun document importé"
            return f"<p>Documents de veille — {texte}</p>"

        contenu = navigation(connaissance=connaissance, jour=jour) + "".join(
            [
                panneau("Briefing — salle de guerre", lien("/sources", reference=connaissance), salle),
                panneau("Risques", lien("/risques", connaissance=connaissance), risques),
                panneau("Prévisions des propriétaires", lien("/risques", connaissance=connaissance), previsions),
                panneau("Plans et suites", lien("/plans", connaissance=connaissance, jour=jour), plans),
                panneau("Actions proposées et approbations", lien("/actions"), actions),
                panneau("Veille", lien("/veille", connaissance=connaissance), veille),
            ]
        )
        return page(session, "Direction IA", formulaire_dates(lien(""), True, connaissance, jour) + contenu)

    # -- risques
    # --------------------------------------------------------------------------------------------------------
    @router.get("/direction/risques", response_class=HTMLResponse)
    def page_risques(request: Request) -> HTMLResponse:
        session = session_page(request)
        admin(session)
        valeurs = _valeurs(request, _PARAMS["risques"])
        _exiger(valeurs, _INSTANT, "connaissance")
        _exiger(valeurs, _DEPART, "depart")
        _exiger(valeurs, _JOURS, "perime_apres_jours")
        if not valeurs:
            return page(session, "Risques", navigation() + formulaire_dates(lien("/risques"), False, "", ""))
        if "connaissance" not in valeurs:
            raise HTTPException(400, "connaissance explicite requise")
        arguments: dict[str, Any] = {"connaissance": valeurs["connaissance"]}
        if "perime_apres_jours" in valeurs:
            arguments["perime_apres_jours"] = int(valeurs["perime_apres_jours"])
        if "depart" in valeurs:
            arguments["depart"] = int(valeurs["depart"])
        try:
            radar = lire(session, "m9_radar_risques", arguments)
        except _Refus as refus:
            return page(
                session,
                "Risques",
                refus_html("Lecture du radar refusée par M9.", refus.code, lien("/risques"), "Recommencer"),
                409 if "depart" in arguments else 400,
            )
        suivant = ""
        if type(radar.get("prochain_depart")) is int:
            reste = {k: v for k, v in valeurs.items() if k != "depart"}
            suivant = suite(lien("/risques", **reste, depart=radar["prochain_depart"]))
        return page(
            session,
            "Risques",
            navigation(connaissance=valeurs["connaissance"])
            + formulaire_dates(lien("/risques"), False, valeurs["connaissance"], "")
            + f"<section><h2>Radar de risques</h2>{rendre(radar)}{suivant}</section>",
        )

    # -- sources
    # --------------------------------------------------------------------------------------------------------
    @router.get("/direction/sources", response_class=HTMLResponse)
    def page_sources(request: Request) -> HTMLResponse:
        session = session_page(request)
        admin(session)
        valeurs = _valeurs(request, _PARAMS["sources"])
        _exiger(valeurs, _INSTANT, "reference")
        _exiger(valeurs, _DEPART, "depart")
        _exiger(valeurs, _ID, "lecture_id", "vue")
        entete = navigation() + (
            f'<form method="get" action="{e(lien("/sources"))}"><label>Référence (fuseau explicite) '
            f'<input name="reference" required size="30" placeholder="2026-10-28T13:00:00Z" '
            f'value="{e(valeurs.get("reference", ""))}"></label> <button type="submit">Afficher</button></form>'
        )
        if "reference" not in valeurs:
            return page(session, "Sources", entete)
        contenu = entete
        try:
            couverture = lire(session, "m9_couverture_strategique", {"reference": valeurs["reference"]})
            contenu += f"<section><h2>Couverture des sources</h2>{rendre(couverture)}</section>"
        except _Refus as refus:
            contenu += refus_html("Couverture refusée par M9.", refus.code, lien("/sources"), "Recommencer")
        arguments: dict[str, Any] = {k: valeurs[k] for k in ("lecture_id", "vue") if k in valeurs}
        if "depart" in valeurs:
            arguments["depart"] = int(valeurs["depart"])
        try:
            captures = lire(session, "m9_lister_captures", arguments)
            contenu += f"<section><h2>Captures conservées</h2>{rendre(captures)}</section>"
            if type(captures.get("prochain_depart")) is int and isinstance(captures.get("vue"), str):
                filtre = {"lecture_id": valeurs["lecture_id"]} if "lecture_id" in valeurs else {}
                href = lien(
                    "/sources",
                    reference=valeurs["reference"],
                    depart=captures["prochain_depart"],
                    vue=captures["vue"],
                    **filtre,
                )
                contenu += suite(href)
        except _Refus as refus:
            contenu += refus_html(
                "Liste des captures refusée (la vue a pu changer : recommencer depuis le début).",
                refus.code,
                lien("/sources", reference=valeurs["reference"]),
                "Recommencer depuis le début",
            )
        return page(session, "Sources", contenu)

    # -- plans et suites
    # ----------------------------------------------------------------------------------------------------
    def formulaires_plan(session: Session, plan: Mapping[str, Any], connaissance: str, jour: str) -> str:
        if plan.get("statut") == "ANNULE":
            return ""
        plan_id = str(plan.get("plan_id", ""))
        resultats = [r for r in (plan.get("resultats_cles") or []) if isinstance(r, Mapping)]
        options = "".join(f'<option value="{e(r.get("id"))}">{e(r.get("libelle"))}</option>' for r in resultats)
        retour = (
            f'<input type="hidden" name="connaissance" value="{e(connaissance)}">'
            f'<input type="hidden" name="jour" value="{e(jour)}">'
        )
        return (
            f'<form method="post" action="{e(prefixe)}/direction/plans/suivi" class="commande">'
            f'<input type="hidden" name="csrf" value="{e(session.csrf)}">'
            f'<input type="hidden" name="plan_id" value="{e(plan_id)}">'
            f'<input type="hidden" name="mutation_id" value="{e(uuid.uuid4().hex)}">{retour}'
            f'<label>Résultat clé <select name="resultat_id" required>{options}</select></label> '
            "<label>Note de suivi (déclaration, pas un effet) "
            '<input name="note" required maxlength="500" size="40"></label> '
            '<button type="submit">Noter le suivi</button></form>'
            f'<form method="post" action="{e(prefixe)}/direction/plans/annuler" class="commande">'
            f'<input type="hidden" name="csrf" value="{e(session.csrf)}">'
            f'<input type="hidden" name="plan_id" value="{e(plan_id)}">'
            f'<input type="hidden" name="mutation_id" value="{e(uuid.uuid4().hex)}">{retour}'
            '<label>Motif d\'annulation <input name="motif" required maxlength="300" size="40"></label> '
            '<label><input type="checkbox" name="confirmer" value="oui" required> Je confirme l\'annulation</label> '
            '<button type="submit">Annuler le plan</button></form>'
        )

    @router.get("/direction/plans", response_class=HTMLResponse)
    def page_plans(request: Request) -> HTMLResponse:
        session = session_page(request)
        admin(session)
        valeurs = _valeurs(request, _PARAMS["plans"])
        _exiger(valeurs, _INSTANT, "connaissance")
        _exiger(valeurs, _JOUR, "jour")
        if not valeurs:
            return page(session, "Plans et suites", navigation() + formulaire_dates(lien("/plans"), True, "", ""))
        if set(valeurs) != {"connaissance", "jour"}:
            raise HTTPException(400, "connaissance et jour requis ensemble")
        connaissance, jour = valeurs["connaissance"], valeurs["jour"]
        try:
            vue = lire(session, "m9_lire_plans", {"connaissance": connaissance, "jour": jour})
        except _Refus as refus:
            return page(
                session,
                "Plans et suites",
                refus_html("Lecture des plans refusée par M9.", refus.code, lien("/plans"), "Recommencer"),
                400,
            )
        blocs = []
        for plan in vue.get("plans") or []:
            if not isinstance(plan, Mapping):
                continue
            blocs.append(
                f'<section class="plan"><h2>{e(plan.get("plan_id"))} — {e(plan.get("statut"))}</h2>'
                f"{rendre(plan)}{formulaires_plan(session, plan, connaissance, jour)}</section>"
            )
        corps = "".join(blocs) or "<p>Aucun plan déposé à cet instant.</p>"
        return page(
            session,
            "Plans et suites",
            navigation(connaissance=connaissance, jour=jour)
            + formulaire_dates(lien("/plans"), True, connaissance, jour)
            + corps,
        )

    def commande_plan(session: Session, nom: str, champs: Mapping[str, str], arguments: dict[str, Any]) -> Response:
        connaissance, jour = champs.get("connaissance", ""), champs.get("jour", "")
        if _INSTANT.fullmatch(connaissance) is None or _JOUR.fullmatch(jour) is None:
            raise HTTPException(400, "connaissance et jour requis pour revenir à la vue")
        mutation_id = champs.get("mutation_id", "")
        if _ID.fullmatch(mutation_id) is None:
            raise HTTPException(400, "mutation_id invalide")
        try:
            with cnx_factory() as cnx:
                reponse = metier.executer(cnx, deps, session, nom, arguments, mutation_id=mutation_id)
        except PermissionError as exc:
            raise HTTPException(403, "accès métier refusé") from exc
        except KeyError as exc:
            raise HTTPException(404, "commande M9 indisponible") from exc
        except ValueError as exc:
            code = _code(str(exc))
            if "IDENTITE" in code:
                raise HTTPException(403, "accès métier refusé") from exc
            if "conflit" in str(exc):
                raise HTTPException(409, "identifiant de commande déjà utilisé avec d'autres données") from exc
            return page(
                session,
                "Commande refusée",
                refus_html(
                    "Commande refusée par M9.",
                    code,
                    lien("/plans", connaissance=connaissance, jour=jour),
                    "Retour aux plans",
                ),
                409,
            )
        code_refus = _refus_de_reponse(reponse)
        if code_refus is not None:
            return page(
                session,
                "Commande refusée",
                refus_html(
                    "Commande refusée par M9 : rien n'a été enregistré.",
                    code_refus,
                    lien("/plans", connaissance=connaissance, jour=jour),
                    "Retour aux plans",
                ),
                409,
            )
        return RedirectResponse(lien("/plans", connaissance=connaissance, jour=jour), status_code=303)

    @router.post("/direction/plans/suivi")
    async def noter_suivi(request: Request) -> Response:
        session = session_page(request)
        admin(session)
        if request.query_params:
            raise HTTPException(400, "requête invalide")
        champs = await formulaire(request)
        verifier_formulaire(champs, session)
        _exiger(champs, _ID, "plan_id", "resultat_id")
        note = champs.get("note", "").strip()
        if not note or len(note) > 500 or champs.get("plan_id") is None or champs.get("resultat_id") is None:
            raise HTTPException(400, "formulaire invalide")
        return commande_plan(
            session,
            "m9_noter_suivi_plan",
            champs,
            {"plan_id": champs["plan_id"], "resultat_id": champs["resultat_id"], "note": note},
        )

    @router.post("/direction/plans/annuler")
    async def annuler_plan(request: Request) -> Response:
        session = session_page(request)
        admin(session)
        if request.query_params:
            raise HTTPException(400, "requête invalide")
        champs = await formulaire(request)
        verifier_formulaire(champs, session)
        _exiger(champs, _ID, "plan_id")
        motif = champs.get("motif", "").strip()
        if champs.get("confirmer") != "oui" or not motif or len(motif) > 300 or champs.get("plan_id") is None:
            raise HTTPException(400, "annulation non confirmée ou formulaire invalide")
        return commande_plan(session, "m9_annuler_plan", champs, {"plan_id": champs["plan_id"], "motif": motif})

    # -- actions et approbations ---------------------------------------------------------------------------------------
    @router.get("/direction/actions", response_class=HTMLResponse)
    def page_actions(request: Request) -> HTMLResponse:
        session = session_page(request)
        admin(session)
        valeurs = _valeurs(request, _PARAMS["actions"])
        _exiger(valeurs, _ID, "action_id")
        try:
            actions = lire(session, "m9_lire_actions", dict(valeurs))
        except _Refus as refus:
            return page(
                session,
                "Actions",
                refus_html("Lecture des actions refusée.", refus.code, lien("/actions"), "Recommencer"),
                400,
            )
        approbation = (
            f"<p>Les actions proposées par M9 attendent la décision d'un humain dans la "
            f'<a href="{e(prefixe)}/approbations">file d\'approbation native</a> ; '
            "M9 ne les exécute jamais et ne les rejoue pas.</p>"
        )
        return page(
            session, "Actions et approbations", navigation() + approbation + f"<section>{rendre(actions)}</section>"
        )

    # -- décisions du conseil
    # -------------------------------------------------------------------------------------------
    @router.get("/direction/conseil", response_class=HTMLResponse)
    def page_conseil(request: Request) -> HTMLResponse:
        session = session_page(request)
        admin(session)
        valeurs = _valeurs(request, _PARAMS["conseil"])
        _exiger(valeurs, _ID, "session_id")
        _exiger(valeurs, _DEPART, "depart")
        formulaire_session = (
            f'<form method="get" action="{e(lien("/conseil"))}"><label>Session de conseil '
            f'<input name="session_id" required size="40" value="{e(valeurs.get("session_id", ""))}"></label> '
            '<button type="submit">Afficher</button></form>'
        )
        if "session_id" not in valeurs:
            return page(session, "Décisions du conseil", navigation() + formulaire_session)
        contenu = navigation() + formulaire_session
        try:
            deroule = lire(session, "m9_lire_conseil", {"session_id": valeurs["session_id"]})
            contenu += f"<section><h2>Session</h2>{rendre(deroule)}</section>"
        except _Refus as refus:
            return page(
                session,
                "Décisions du conseil",
                contenu + refus_html("Session refusée par M9.", refus.code, lien("/conseil"), "Recommencer"),
                404,
            )
        arguments: dict[str, Any] = {"session_id": valeurs["session_id"]}
        if "depart" in valeurs:
            arguments["depart"] = int(valeurs["depart"])
        try:
            rapport = lire(session, "m9_lire_rapport_conseil", arguments)
            contenu += f"<section><h2>Rapport de décision (proposition non ratifiée)</h2>{rendre(rapport)}</section>"
            if type(rapport.get("prochain_depart")) is int:
                href = lien("/conseil", session_id=valeurs["session_id"], depart=rapport["prochain_depart"])
                contenu += suite(href, "Suite du rapport")
        except _Refus as refus:
            contenu += refus_html(
                "Aucun rapport lisible (session en cours ou reprise invalide).",
                refus.code,
                lien("/conseil", session_id=valeurs["session_id"]),
                "Recommencer",
            )
        return page(session, "Décisions du conseil", contenu)

    # -- briefings et revues
    # --------------------------------------------------------------------------------------------
    @router.get("/direction/revues", response_class=HTMLResponse)
    def page_revues(request: Request) -> HTMLResponse:
        session = session_page(request)
        admin(session)
        valeurs = _valeurs(request, _PARAMS["revues"])
        _exiger(valeurs, _DEPART, "depart")
        if "granularite" in valeurs and valeurs["granularite"] not in _GRANULARITES:
            raise HTTPException(400, "granularite inconnue")
        _exiger(valeurs, _ID, "vue")
        arguments: dict[str, Any] = {k: valeurs[k] for k in ("granularite", "vue") if k in valeurs}
        if "depart" in valeurs:
            arguments["depart"] = int(valeurs["depart"])
        try:
            revues = lire(session, "m9_lister_revues", arguments)
        except _Refus as refus:
            return page(
                session,
                "Briefings et revues",
                navigation()
                + refus_html(
                    "Liste refusée (recommencer depuis le début).", refus.code, lien("/revues"), "Recommencer"
                ),
                409,
            )
        contenu = navigation() + f"<section>{rendre(revues)}</section>"
        if type(revues.get("prochain_depart")) is int and isinstance(revues.get("vue"), str):
            filtre = {"granularite": valeurs["granularite"]} if "granularite" in valeurs else {}
            contenu += suite(lien("/revues", depart=revues["prochain_depart"], vue=revues["vue"], **filtre))
        contenu += (
            f'<form method="get" action="{e(lien("/revue"))}"><label>Index de revue '
            '<input name="index" required inputmode="numeric" pattern="\\d{1,9}" size="6"></label> '
            '<button type="submit">Lire la revue</button></form>'
        )
        return page(session, "Briefings et revues", contenu)

    @router.get("/direction/revue", response_class=HTMLResponse)
    def page_revue(request: Request) -> HTMLResponse:
        session = session_page(request)
        admin(session)
        valeurs = _valeurs(request, _PARAMS["revue"])
        _exiger(valeurs, _DEPART, "index", "depart")
        if "index" not in valeurs:
            raise HTTPException(400, "index requis")
        arguments: dict[str, Any] = {"index": int(valeurs["index"])}
        if "depart" in valeurs:
            arguments["depart"] = int(valeurs["depart"])
        try:
            revue = lire(session, "m9_lire_revue", arguments)
        except _Refus as refus:
            return page(
                session,
                "Revue",
                navigation() + refus_html("Revue refusée par M9.", refus.code, lien("/revues"), "Retour aux revues"),
                404,
            )
        suivante = ""
        if type(revue.get("prochain_depart")) is int:
            suivante = suite(
                lien("/revue", index=valeurs["index"], depart=revue["prochain_depart"]), "Suite de la revue"
            )
        return page(session, "Revue", navigation() + f"<section>{rendre(revue)}</section>{suivante}")

    # -- veille
    # -----------------------------------------------------------------------------------------------------------
    @router.get("/direction/veille", response_class=HTMLResponse)
    def page_veille(request: Request) -> HTMLResponse:
        session = session_page(request)
        admin(session)
        valeurs = _valeurs(request, _PARAMS["veille"])
        _exiger(valeurs, _INSTANT, "connaissance")
        _exiger(valeurs, _ID, "decision_ref")
        if not valeurs:
            return page(session, "Veille", navigation() + formulaire_dates(lien("/veille"), False, "", ""))
        if "connaissance" not in valeurs:
            raise HTTPException(400, "connaissance explicite requise")
        try:
            veille = lire(session, "m9_lire_veille", dict(valeurs))
        except _Refus as refus:
            return page(
                session,
                "Veille",
                navigation() + refus_html("Veille refusée par M9.", refus.code, lien("/veille"), "Recommencer"),
                400,
            )
        avertissement = (
            "<p>Documents importés par une personne, jamais récupérés par M9. Un document en quarantaine, remplacé ou "
            "périmé n'est pas citable.</p>"
        )
        return page(
            session,
            "Veille",
            navigation(connaissance=valeurs["connaissance"])
            + formulaire_dates(lien("/veille"), False, valeurs["connaissance"], "")
            + avertissement
            + f"<section>{rendre(veille)}</section>",
        )

    # -- scénarios (calcul en lecture seule, POST à cause de la taille et du jeton CSRF) ------------------------------
    def formulaire_scenario(session: Session, reference: str, bases: str, chocs: str) -> str:
        zone = f'rows="4" cols="70" maxlength="{_MAX_JSON_SCENARIO}" required'
        return (
            f'<form method="post" action="{e(prefixe)}/direction/scenarios">'
            "<fieldset><legend>Évaluer des chocs</legend>"
            f'<input type="hidden" name="csrf" value="{e(session.csrf)}">'
            '<label>Référence <input name="reference" required size="30" placeholder="2026-10-28T13:00:00Z" '
            f'value="{e(reference)}"></label><br>'
            "<label>Bases (JSON : nom → adresse de fait citable)<br>"
            f'<textarea name="bases" {zone}>{e(bases)}</textarea></label><br>'
            '<label>Chocs (JSON : liste de {"choc", "parametres"})<br>'
            f'<textarea name="chocs" {zone}>{e(chocs)}</textarea></label><br>'
            "<p>Sensibilités arithmétiques sur des faits cités : sans base, le calcul est refusé ; finance, capacité "
            "et stock restent à calculer par leur propriétaire.</p>"
            '<button type="submit">Évaluer</button></fieldset></form>'
        )

    @router.get("/direction/scenarios", response_class=HTMLResponse)
    def page_scenarios(request: Request) -> HTMLResponse:
        session = session_page(request)
        admin(session)
        _valeurs(request, frozenset())
        return page(session, "Scénarios", navigation() + formulaire_scenario(session, "", "", ""))

    @router.post("/direction/scenarios", response_class=HTMLResponse)
    async def evaluer_scenarios(request: Request) -> HTMLResponse:
        session = session_page(request)
        admin(session)
        if request.query_params:
            raise HTTPException(400, "requête invalide")
        champs = await formulaire(request)
        verifier_formulaire(champs, session)
        reference = champs.get("reference", "")
        bases_texte, chocs_texte = champs.get("bases", ""), champs.get("chocs", "")
        if (
            _INSTANT.fullmatch(reference) is None
            or len(bases_texte) > _MAX_JSON_SCENARIO
            or len(chocs_texte) > _MAX_JSON_SCENARIO
        ):
            raise HTTPException(400, "référence ou corps de scénario invalide")
        saisie = formulaire_scenario(session, reference, bases_texte, chocs_texte)
        try:
            bases, chocs = json.loads(bases_texte), json.loads(chocs_texte)
        except ValueError:
            return page(
                session,
                "Scénarios",
                navigation()
                + saisie
                + refus_html(
                    "JSON illisible : rien n'est évalué.", "REJ-DIRECTION-JSON", lien("/scenarios"), "Recommencer"
                ),
                400,
            )
        if not isinstance(bases, dict) or not isinstance(chocs, list):
            return page(
                session,
                "Scénarios",
                navigation()
                + saisie
                + refus_html("Bases = objet, chocs = liste.", "REJ-DIRECTION-JSON", lien("/scenarios"), "Recommencer"),
                400,
            )
        try:
            resultat = lire(session, "m9_evaluer_scenarios", {"reference": reference, "bases": bases, "chocs": chocs})
        except _Refus as refus:
            return page(
                session,
                "Scénarios",
                navigation()
                + saisie
                + refus_html("Évaluation refusée par M9.", refus.code, lien("/scenarios"), "Recommencer"),
                400,
            )
        return page(
            session, "Scénarios", navigation() + saisie + f"<section><h2>Résultat</h2>{rendre(resultat)}</section>"
        )

    return router
