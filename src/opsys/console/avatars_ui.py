"""Console « Plateforme > Avatars » : état de chaque avatar et registre des voix et visages, en LECTURE seule.

Aucune écriture, aucun contrôle d'appareil : le registre, les consentements et les déclarations de canal se gèrent par
l'API du module `opsys.avatars_voix` (administration authentifiée, journalisée). Session obligatoire, rôle
d'administration relu en base avant ET après la lecture (même règle que la Plateforme), `Cache-Control: no-store`.
Aucune empreinte vocale, aucune référence de locuteur, aucun chemin de fichier n'est rendu ; un profil d'entreprise
illisible ne montre aucune identité (fail-closed, comme `configuration_lecture`).

Routes : /plateforme/avatars (page) ; /api/plateforme/avatars (JSON).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from .. import avatars
from ..avatars_voix import lecture
from ..departements import Departement
from ..taxonomie import ProfilInvalide
from . import pages
from .securite import Session

ENTETES = {"Cache-Control": "no-store", "Pragma": "no-cache"}
ONGLET = "plateforme/fournisseurs"
_CLASSES = {"disponible": "badge-ok", "suspendu": "badge-danger", "qualifie": "badge-alerte",
            "configure": "badge-alerte", "prevu": ""}
_LIBELLES = {"disponible": "Disponible", "suspendu": "Suspendu", "qualifie": "Qualifié (connexion)",
             "configure": "Configuré", "prevu": "Prévu"}


def _badge(etat: str) -> str:
    return f'<span class="badge {pages.e(_CLASSES.get(etat, ""))}">{pages.e(_LIBELLES.get(etat, etat))}</span>'


def _cellule_canal(canal: Mapping[str, Any]) -> str:
    codes = "".join(f"<br><code>{pages.e(code)}</code>" for code in canal["codes"])
    return _badge(canal["etat"]) + codes


def _qualification(derniere: Mapping[str, Any] | None) -> str:
    if derniere is None:
        return "—"
    return pages.e(f"{derniere['nature']} · {derniere['statut']} · {derniere['quand']}")


def contenu(vue: Mapping[str, Any], *, prefixe: str) -> str:
    e = pages.e
    lignes = "".join(
        f"<tr><td>{e(a['nom'])}<br><small>{e(a['code'])} · {e(a['role'])}</small></td>"
        f"<td><code>{e(a['voix'])}</code><br><code>{e(a['visage'])}</code></td>"
        f"<td>{_badge(a['canaux']['messagerie']['etat'])}</td>"
        f"<td>{_cellule_canal(a['canaux']['voix'])}</td><td>{_cellule_canal(a['canaux']['audiovisuel'])}</td></tr>"
        for a in vue["avatars"])
    entrees = "".join(
        f"<tr><td><code>{e(r['identifiant'])}</code></td><td>{_badge(r['etat_effectif'])}</td>"
        f"<td>{e(r['fournisseur']['identifiant']) if r['fournisseur'] else '—'}</td>"
        f"<td>{e(r['langue'])}</td><td>{e(r['origine'])}</td>"
        f"<td>{int(r['consentements']['actifs'])} / {int(r['consentements']['total'])}</td>"
        f"<td>{_qualification(r['derniere_qualification'])}</td></tr>" for r in vue["registre"])
    registre = ("<table><thead><tr><th>Identifiant</th><th>État</th><th>Moteur</th><th>Langue</th><th>Origine</th>"
                "<th>Consentements actifs</th><th>Dernière qualification</th></tr></thead>"
                f"<tbody>{entrees}</tbody></table>") if entrees else "<p>Aucune entrée voix ou visage inscrite.</p>"
    return (
        pages.navigation_plateforme(prefixe, "avatars") +
        f'<p class="note">{e(vue["avertissement"])}</p>'
        "<h2>Avatars et canaux</h2><table><thead><tr><th>Avatar</th><th>Voix et visage (logiques)</th>"
        "<th>Messagerie</th><th>Voix</th><th>Audiovisuel</th></tr></thead>"
        f"<tbody>{lignes}</tbody></table>"
        f"<h2>Registre des voix et visages</h2>{registre}")


def creer_router(*, session_page: Callable[..., Session], session_api: Callable[..., Session],
                 cnx_factory: Callable[[], Any], deps: Mapping[str, Departement], prefixe: str) -> APIRouter:
    router = APIRouter(tags=["avatars"])

    def lire() -> dict[str, Any]:
        try:
            identites = avatars.identites_effectives(deps)
        except (ProfilInvalide, avatars.AvatarInvalide):
            return {"statut": "profil_invalide"}  # aucune identité, aucun chemin : ni les défauts ni le fichier
        with cnx_factory() as cnx:
            return {"statut": "ok", **lecture.etat_avatars(cnx, identites)}

    @router.get("/plateforme/avatars", response_class=HTMLResponse)
    def page_avatars(request: Request) -> Response:
        session = session_page(request)
        vue = lire()
        session_page(request)
        corps = (contenu(vue, prefixe=prefixe) if vue["statut"] == "ok" else
                 "<p>Les avatars ne peuvent pas être lus : le profil d'entreprise ou un manifeste est invalide "
                 "(<code>opsys-metier verifier</code>).</p>")
        return HTMLResponse(pages.gabarit("Plateforme — avatars", corps, prefixe=prefixe, session=session,
                                          actif=ONGLET), headers=ENTETES)

    @router.get("/api/plateforme/avatars")
    def api_avatars(request: Request) -> Response:
        session_api(request)
        vue = lire()
        session_api(request)
        return JSONResponse(vue, headers=ENTETES)

    return router
