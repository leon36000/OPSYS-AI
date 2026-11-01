"""Console « Plateforme > Connaissances » : état des bases de connaissances par département, en LECTURE seule.

Aucune écriture, aucun formulaire : l'ingestion, la revue, la publication et le retrait des sources passent par les
outils
du département M10 (niveaux N2/N3, journalisés) ; le registre des fournisseurs d'embeddings se règle dans la Plateforme.
Métadonnées seulement : nombre de sources par état, sources périmées ou à réviser, date du dernier index, fournisseur
d'embeddings actif (et s'il est raccordé), couverture vectorielle. Aucun texte de source n'est rendu (le titre, venu
d'un
tiers, passe par le filtre anti-injection). Session obligatoire, rôle d'administration relu avant ET après la lecture
(même règle que la Plateforme), `Cache-Control: no-store`.

Routes : /plateforme/connaissances (page) ; /api/plateforme/connaissances (JSON).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from ..connaissances import lecture, service
from ..connaissances.codes import ErreurConnaissances
from . import pages
from .securite import Session

ENTETES = {"Cache-Control": "no-store", "Pragma": "no-cache"}
ONGLET = "plateforme/fournisseurs"


def _fournisseur(f: Mapping[str, Any]) -> str:
    e = pages.e
    if f["statut"] != "selectionne":
        return f'<span class="badge badge-alerte">aucun</span> <code>{e(f["code"])}</code>'
    raccorde = ('<span class="badge badge-ok">raccordé</span>' if f["raccorde"] else
                '<span class="badge badge-alerte">non raccordé</span>')
    return f'<code>{e(f["identifiant"])}</code> {raccorde}<br><small>{e(f["modele"])} · {e(f["qualification"])}</small>'


def contenu(vue: Mapping[str, Any], *, prefixe: str) -> str:
    e = pages.e
    if not vue["bases"]:
        corps = "<p>Aucune base de connaissances : aucune source n'a encore été ingérée.</p>"
    else:
        lignes = []
        for b in vue["bases"]:
            s = b["sources_par_etat"]
            perimees = "".join(f"<li>{e(p['titre'])} (v{int(p['version'])}, {e(p['motif'])})</li>"
                               for p in b["sources_perimees"]) or "<li>aucune</li>"
            a_reviser = "".join(f"<li>{e(p['titre'])} (révision le {e(p['revision_due_le'])})</li>"
                                for p in b["revisions_a_venir"]) or "<li>aucune</li>"
            espace = b["espace_actif"]
            vecteurs = (f"<code>{e(espace['fournisseur_id'])}</code> · {int(espace['dimension'])} dimensions"
                        if espace else "aucun espace vectoriel")
            c = b["couverture_vectorielle"]
            alerte = (' <span class="badge badge-danger">réindexation requise</span>'
                      if b["reindexation_requise"] else "")
            fictif = (' <span class="badge badge-alerte">démonstration fictive</span>'
                      if b["contient_demonstration_fictive"] else "")
            lignes.append(
                f"<tr><td><code>{e(b['departement'])}</code>{fictif}</td><td>{int(b['sources'])}</td>"
                f"<td>brouillon {int(s['brouillon'])} · revu {int(s['revu'])} · publié {int(s['publie'])} · "
                f"retiré {int(s['retire'])}</td>"
                f"<td><ul>{perimees}</ul></td><td><ul>{a_reviser}</ul></td>"
                f"<td>lexical {e((b['derniere_indexation']['lexical'] or '—')[:19])}<br>"
                f"vectoriel {e((b['derniere_indexation']['vectoriel'] or '—')[:19])}</td>"
                f"<td>{_fournisseur(b['embeddings'])}{alerte}<br><small>{vecteurs} · "
                f"{int(c['avec_vecteur'])}/{int(c['fragments_publies'])} fragments</small></td>"
                f"<td>{int(b['versions_suspectes'])}</td></tr>")
        corps = ("<table><thead><tr><th>Base</th><th>Sources</th><th>Par état (versions)</th><th>Périmées</th>"
                 f"<th>À réviser ({int(vue['jours_avant_revision'])} jours)</th><th>Dernier index</th>"
                 "<th>Embeddings actifs</th><th>Suspectes</th></tr></thead>"
                 f"<tbody>{''.join(lignes)}</tbody></table>")
    return (
        f'<p><a href="{e(prefixe)}/plateforme/fournisseurs">Fournisseurs</a> · '
        f'<a href="{e(prefixe)}/plateforme/avatars">Avatars</a> · Connaissances · '
        f'<a href="{e(prefixe)}/plateforme/mnemo">Mnémo</a></p>'
        f'<p class="note">Lecture seule. L\'ingestion, la revue et le retrait se font par les outils M10 '
        f'(journalisés). '
        f'{e(vue["mention_professionnelle"])}.</p>' + corps)


def creer_router(*, session_page: Callable[..., Session], session_api: Callable[..., Session],
                 cnx_factory: Callable[[], Any], prefixe: str) -> APIRouter:
    router = APIRouter(tags=["connaissances"])

    def lire() -> dict[str, Any]:
        with cnx_factory() as cnx:
            return lecture.etat_bases(cnx, maintenant=service.maintenant())

    @router.get("/plateforme/connaissances", response_class=HTMLResponse)
    def page_connaissances(request: Request) -> Response:
        session = session_page(request)
        try:
            vue = lire()
            corps = contenu(vue, prefixe=prefixe)
        except ErreurConnaissances:
            corps = "<p>Les bases de connaissances ne peuvent pas être lues.</p>"
        session_page(request)
        return HTMLResponse(pages.gabarit("Plateforme — connaissances", corps, prefixe=prefixe, session=session,
                                          actif=ONGLET), headers=ENTETES)

    @router.get("/api/plateforme/connaissances")
    def api_connaissances(request: Request) -> Response:
        session_api(request)
        vue = lire()
        session_api(request)
        return JSONResponse(vue, headers=ENTETES)

    return router
