"""Console « Collecte » : POURQUOI une mesure de M8 est vide ou périmée, et quoi activer (chantier C2 de l'analyse
M8).

Lecture seule. La page ne calcule rien et n'invente aucune cause : elle montre ce que `m8_lire_etat_collecte` (outil
T0/N0 de M8, réservé à l'admin) rend, c'est-à-dire l'état du planificateur lu au planificateur lui-même et la
fraîcheur ordinaire des mesures. Elle n'active, ne déclenche et ne corrige rien : l'activation d'un constat se fait à
la page Connecteurs, avec son motif et son expiration. Aucune valeur de mesure n'est rendue (la page ne nomme que des
mesures, des constats, des modes et des codes), donc aucune donnée financière ni personnelle.

Gardes (mêmes que les wallboards) : session obligatoire, rôle `admin` RELU EN BASE avant ET après la lecture, en-têtes
`no-store`, aucun formulaire, aucune écriture, contrôle de secret avant de servir. La cause est écrite en toutes
lettres (jamais la couleur seule).

Routes : /collecte (page) ; /api/collecte (JSON : résumé, mesures à corriger, gestes d'activation restants)."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from .. import identite
from ..secrets_coffre import masquage
from . import metier, pages
from .securite import Session

ENTETES = {"Cache-Control": "no-store", "Pragma": "no-cache"}
_OUTIL = "m8_lire_etat_collecte"
_PAGES_MAX = 12
_LIBELLE_ETAT = {"actif": "Actif", "ombre": "En ombre", "inactif": "Inactif", "expire": "Activation échue"}
_LIBELLE_ETAT_COLLECTE = {
    "a_jour": "À jour",
    "planificateur_coupe": "Planificateur coupé",
    "constat_expire": "Activation échue",
    "constat_inactif": "Constat inactif",
    "constat_en_ombre": "Constat en ombre",
    "constat_en_erreur": "Constat en erreur",
    "jamais_recue": "Jamais reçue",
    "producteur_non_calculable": "Le département source dit « non calculable »",
    "source_perimee": "Source périmée",
    "fraicheur_inconnue": "Fraîcheur inconnue",
    "sans_constat_planifie": "Sans constat planifié",
}


def _maintenant() -> str:
    """L'instant du serveur (RFC 3339 avec fuseau) : M8 n'a pas d'horloge. Les tests remplacent cette fonction (résolue
    à l'appel, jamais figée à l'import)."""
    return datetime.now(UTC).isoformat(timespec="seconds")


def _ligne_constat(c: Mapping[str, Any]) -> str:
    dernier = pages.e(c.get("dernier_statut") or "aucun passage")
    code = f" ({pages.e(c['dernier_code'])})" if c.get("dernier_code") else ""
    return (
        f'<tr><th scope="row"><code>{pages.e(c["executeur"])}</code></th><td>{pages.e(_LIBELLE_ETAT[c["etat"]])}</td>'
        f"<td>{dernier}{code}</td><td>{int(c['mesures_a_jour'])} sur {int(c['mesures_total'])}</td></tr>"
    )


def _ligne_mesure(m: Mapping[str, Any]) -> str:
    constats = ", ".join(pages.e(x) for x in m["constats"]) or "aucun"
    return (
        f'<tr><th scope="row">{pages.e(m["nom"])}<br><code>{pages.e(m["metric_id"])}</code></th>'
        f"<td>{pages.e(_LIBELLE_ETAT_COLLECTE.get(m['etat_collecte'], m['etat_collecte']))}</td>"
        f"<td>{pages.e(m['phrase'])}</td>"
        f"<td>{pages.e(m['action'] or '')}</td><td>{constats}</td></tr>"
    )


def _ligne_etape(e: Mapping[str, Any]) -> str:
    return (
        f"<tr><td>{pages.e(e['constat'] or 'planificateur')}</td><td>{pages.e(e['etape'].replace('_', ' '))}</td>"
        f"<td>{pages.e(e['action'] or '')}</td></tr>"
    )


def rendre_contenu(etat: Mapping[str, Any]) -> str:
    """Le contenu de la page, rendu serveur complet (aucun script)."""
    resume = etat["resume"]
    causes = "".join(
        f"<li>{pages.e(_LIBELLE_ETAT_COLLECTE.get(cause, cause))} : {int(nombre)}</li>"
        for cause, nombre in resume["resume"].items() if nombre
    )
    coupe = "" if resume["planificateur_autorise"] else (
        '<p class="message message-erreur" role="alert">Le planificateur est coupé '
        "(OPSYS_PLANIFICATEUR_CONNECTEURS) : aucun constat ne tourne.</p>"
    )
    constats = "".join(_ligne_constat(c) for c in resume["constats"])
    mesures = "".join(_ligne_mesure(m) for m in etat["mesures"])
    etapes = "".join(_ligne_etape(e) for e in etat["etapes"])
    table_mesures = (
        '<div class="table-defilante"><table><caption>Mesures à corriger ou à comprendre</caption><thead><tr>'
        '<th scope="col">Mesure</th><th scope="col">État de la collecte</th><th scope="col">Pourquoi</th>'
        '<th scope="col">Quoi faire</th><th scope="col">Constats</th></tr></thead>'
        f"<tbody>{mesures}</tbody></table></div>"
        if mesures else "<p>Toutes les mesures sont calculées et à jour.</p>"
    )
    table_etapes = (
        '<div class="table-defilante"><table><caption>Gestes d\'activation restants</caption><thead><tr>'
        '<th scope="col">Constat</th><th scope="col">Étape</th><th scope="col">Quoi faire</th></tr></thead>'
        f"<tbody>{etapes}</tbody></table></div>"
        if etapes else "<p>Tous les constats planifiés sont activés et ont passé avec succès.</p>"
    )
    return (
        f"<p>{pages.e(resume['lecture'])} Cette page est en lecture seule : elle n'active et ne corrige rien ; "
        "l'activation d'un constat se fait à la page Connecteurs.</p>"
        f"{coupe}<h2>Résumé</h2><ul>{causes}</ul>"
        '<h2>Constats planifiés</h2><div class="table-defilante"><table><caption>Constats déclarés par les départements'
        '</caption><thead><tr><th scope="col">Constat</th><th scope="col">État</th><th scope="col">Dernier passage</th>'
        f'<th scope="col">Mesures à jour</th></tr></thead><tbody>{constats}</tbody></table></div>'
        f"<h2>Pourquoi les mesures sont vides</h2>{table_mesures}<h2>Liste de contrôle d'activation</h2>{table_etapes}"
    )


def creer_router(
    *,
    session_page: Callable[..., Session],
    session_api: Callable[..., Session],
    cnx_factory: Callable[[], Any],
    deps: Mapping[str, Any],
    prefixe: str,
    horloge: Callable[[], str] | None = None,
) -> APIRouter:
    router = APIRouter(tags=["collecte"])
    horloge = horloge or (lambda: _maintenant())
    masquage.installer()

    def exiger_admin(session: Session) -> None:
        with cnx_factory() as cnx:
            personne = identite.personne_active(cnx, session.utilisateur)
        if personne is None or "admin" not in personne.roles:
            raise HTTPException(403, "administration requise")

    def appeler_outil(session: Session, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            with cnx_factory() as cnx:
                reponse = metier.executer(cnx, deps, session, _OUTIL, arguments)
        except PermissionError as exc:
            raise HTTPException(403, "accès refusé") from exc
        except KeyError as exc:
            raise HTTPException(404, "analytique indisponible") from exc
        if not isinstance(reponse, Mapping) or reponse.get("ok") is not True:
            details = str(reponse.get("details", "")) if isinstance(reponse, Mapping) else ""
            if "REJ-IDENTITE" in details:
                raise HTTPException(403, "accès refusé")
            raise HTTPException(409, "lecture de la collecte refusée")
        return dict(reponse["resultat"])

    def pages_de(session: Session, instant: str, vue: str, cle: str) -> list[dict[str, Any]]:
        lignes: list[dict[str, Any]] = []
        depart = 0
        for _ in range(_PAGES_MAX):
            page = appeler_outil(session, {"maintenant": instant, "vue": vue, "depart": depart})
            lignes += page[cle]
            if page.get("prochain_depart") is None:
                return lignes
            depart = page["prochain_depart"]
        raise HTTPException(409, "collecte trop volumineuse")

    def lire(session: Session) -> dict[str, Any]:
        exiger_admin(session)
        instant = horloge()
        resume = appeler_outil(session, {"maintenant": instant, "vue": "resume"})
        return {
            "maintenant": instant,
            "resume": resume,
            "mesures": pages_de(session, instant, "mesures", "mesures"),
            "etapes": pages_de(session, instant, "liste_de_controle", "etapes"),
        }

    @router.get("/collecte", response_class=HTMLResponse)
    def page(request: Request) -> Response:
        session = session_page(request)
        etat = lire(session)
        exiger_admin(session_page(request))
        html = pages.gabarit("Collecte des mesures", rendre_contenu(etat), prefixe=prefixe, session=session,
                             actif="collecte")
        if masquage.contient_secret(html):
            raise HTTPException(500, "rendu refusé : contenu sensible détecté")
        return HTMLResponse(html, headers=ENTETES)

    @router.get("/api/collecte")
    def api(request: Request) -> Response:
        session = session_api(request)
        etat = lire(session)
        exiger_admin(session_api(request))
        return JSONResponse(masquage.masquer({"ok": True, **etat}), headers=ENTETES)

    return router
