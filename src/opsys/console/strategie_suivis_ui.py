"""Console des suivis stratégiques M9 en lecture seule."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse

from . import frontoffice_marketing, metier, pages
from .securite import Session

_PARAMETRES_LISTE = frozenset({"horodatage_reference", "depart", "vue_attendue"})
_PARAMETRES_DETAIL = frozenset({"suivi_id"})
_DEPART = re.compile(r"0|[1-9][0-9]{0,8}")
_CODE_REFUS = re.compile(r"REJ-[A-Z0-9][A-Z0-9-]{0,80}")
_PROFONDEUR_MAX = 12


class _Refus(Exception):
    """Refus de lecture M9 : seul un code REJ- est conservé, jamais le texte brut de l'exception."""

    def __init__(self, code: str, *, invalide: bool) -> None:
        super().__init__(code)
        self.code = code
        self.invalide = invalide


def _code_refus(texte: str) -> str:
    trouve = _CODE_REFUS.search(texte)
    return trouve.group(0) if trouve else ""


def _valeurs(request: Request, permis: frozenset[str]) -> dict[str, str]:
    valeurs: dict[str, str] = {}
    for cle, valeur in request.query_params.multi_items():
        if cle not in permis:
            raise HTTPException(400, "paramètre inconnu refusé")
        if cle in valeurs:
            raise HTTPException(400, "paramètre répété refusé")
        valeurs[cle] = valeur
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
    """Monte l'échéancier et le détail des suivis M9 en HTML, sans route de mutation."""
    del session_api, ecriture_api, formulaire, objet_json  # Lecture HTML seule, aucun body ni POST.
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
            code = _code_refus(str(exc))
            if "IDENTITE" in code:
                raise HTTPException(403, "accès métier refusé") from exc
            raise _Refus(code, invalide=True) from exc
        ok, charge, erreur = frontoffice_marketing.resultat_metier(reponse)
        code: str | None = None
        if not ok:
            code = _code_refus(f"{erreur.get('code', '')} {erreur.get('message', '')}")
        elif isinstance(charge, Mapping) and charge.get("accepte") is False:
            verdict = charge.get("verdict")
            code = _code_refus(str(verdict.get("code", ""))) if isinstance(verdict, Mapping) else ""
        elif not isinstance(charge, Mapping):
            code = ""
        if code is not None:
            if "IDENTITE" in code:
                raise HTTPException(403, "accès métier refusé")
            raise _Refus(code, invalide=False)
        return charge

    def page(session: Session, contenu: str, statut: int = 200) -> HTMLResponse:
        return HTMLResponse(pages.gabarit(
            "Suivis stratégiques M9",
            contenu,
            prefixe=prefixe,
            session=session,
            actif="strategie",
        ), status_code=statut)

    def lien_liste(**parametres: Any) -> str:
        cible = f"{prefixe}/strategie"
        return f"{cible}?{urlencode(parametres)}" if parametres else cible

    @router.get("/strategie", response_class=HTMLResponse)
    def page_suivis(request: Request) -> HTMLResponse:
        session = session_page(request)
        valeurs = _valeurs(request, _PARAMETRES_LISTE)
        if not valeurs:
            return page(session, _formulaire(prefixe, ""))
        reference = valeurs.get("horodatage_reference")
        if reference is None:
            raise HTTPException(400, "horodatage_reference explicite requis")
        arguments: dict[str, Any] = {"horodatage_reference": reference}
        if "depart" in valeurs:
            if not _DEPART.fullmatch(valeurs["depart"]):
                raise HTTPException(400, "depart doit être un entier décimal positif ou nul")
            arguments["depart"] = int(valeurs["depart"])
        if "vue_attendue" in valeurs:
            arguments["vue_attendue"] = valeurs["vue_attendue"]
        reprise = arguments.get("depart", 0) > 0 or "vue_attendue" in arguments
        try:
            rapport = lire(session, "m9_lister_suivis_decision", arguments)
        except _Refus as refus:
            if reprise:
                # Aucune nouvelle tentative silencieuse : la personne relance depuis le début.
                return page(session, _refus_html(
                    "Reprise refusée par M9. Recommencez depuis le début pour relire l’état courant.",
                    refus.code,
                    lien_liste(horodatage_reference=reference),
                    "Recommencer depuis le début avec la même référence",
                ), 409)
            return page(session, _refus_html(
                "Lecture des suivis refusée par M9 pour cette référence.",
                refus.code,
                lien_liste(),
                "Saisir une autre référence",
            ), 400 if refus.invalide else 409)
        suivant = None
        prochain, vue = rapport.get("prochain_depart"), rapport.get("vue")
        if type(prochain) is int and prochain > 0 and isinstance(vue, str):
            suivant = lien_liste(horodatage_reference=reference, depart=prochain, vue_attendue=vue)
        return page(session, _formulaire(prefixe, reference) + _liste(rapport, reference, prefixe, suivant))

    @router.get("/strategie/suivi", response_class=HTMLResponse)
    def page_suivi(request: Request) -> HTMLResponse:
        session = session_page(request)
        valeurs = _valeurs(request, _PARAMETRES_DETAIL)
        if set(valeurs) != _PARAMETRES_DETAIL:
            raise HTTPException(400, "suivi_id requis")
        try:
            suivi = lire(session, "m9_lire_suivi_decision", {"suivi_id": valeurs["suivi_id"]})
        except _Refus as refus:
            if "INTROUVABLE" in refus.code:
                raise HTTPException(404, "suivi introuvable ou ambigu") from refus
            return page(session, _refus_html(
                "Lecture du suivi refusée par M9.", refus.code, lien_liste(), "Retour à l’échéancier",
            ), 400 if refus.invalide else 409)
        return page(session, _detail(suivi, lien_liste()))

    return router


def _formulaire(prefixe: str, reference: str) -> str:
    return (
        '<section class="carte pile"><h2>Échéancier des suivis ouverts</h2>'
        f'<form method="get" action="{pages.e(prefixe)}/strategie" class="pile">'
        '<label for="horodatage_reference">Référence ISO 8601 avec fuseau explicite</label>'
        f'<input id="horodatage_reference" name="horodatage_reference" required value="{pages.e(reference)}">'
        '<p class="note">Format AAAA-MM-JJTHH:MM:SS suivi du fuseau (Z ou ±HH:MM). La console ne déduit '
        "aucune date de l’horloge : les états EN_RETARD, A_ECHEANCE et A_VENIR sont calculés par M9 "
        "face à la référence que vous fournissez.</p>"
        '<button type="submit" class="principal">Afficher les suivis ouverts</button></form></section>'
    )


def _refus_html(message: str, code: str, lien: str, libelle: str) -> str:
    detail = f"<p>Code : {pages.e(code)}</p>" if code else ""
    return (
        '<section class="carte pile">'
        f'<p class="message message-alerte" role="status">{pages.e(message)}</p>{detail}'
        f'<p><a href="{pages.e(lien)}">{pages.e(libelle)}</a></p></section>'
    )


def _compte(valeur: Any) -> str:
    if type(valeur) is int and valeur >= 0:
        return str(valeur)
    return "Indisponible"


def _brut(item: Mapping[str, Any], cle: str) -> Any:
    """Cherche un champ dans la ligne rendue par M9 puis dans son plan, sans le recalculer."""
    for source in (item, item.get("plan"), item.get("suivi")):
        if isinstance(source, Mapping) and source.get(cle) is not None:
            return source[cle]
    return None


def _champ(item: Mapping[str, Any], *cles: str) -> str:
    for cle in cles:
        valeur = _brut(item, cle)
        if isinstance(valeur, str) or type(valeur) is int:
            return str(valeur)
    return "—"


def _arbre(valeur: Any, profondeur: int = 0) -> str:
    """Rend toute la structure M9 en texte échappé : jamais de HTML brut ni de représentation Python."""
    if profondeur > _PROFONDEUR_MAX:
        return "<p>Structure trop profonde pour l’affichage.</p>"
    if isinstance(valeur, Mapping):
        if not valeur:
            return "<p>Aucun champ.</p>"
        lignes = "".join(
            f"<dt>{pages.e(str(cle))}</dt><dd>{_arbre(sous, profondeur + 1)}</dd>" for cle, sous in valeur.items()
        )
        return f"<dl>{lignes}</dl>"
    if isinstance(valeur, (list, tuple)):
        if not valeur:
            return "<p>Aucun élément.</p>"
        return "<ol>" + "".join(f"<li>{_arbre(sous, profondeur + 1)}</li>" for sous in valeur) + "</ol>"
    if isinstance(valeur, bool):
        return "vrai" if valeur else "faux"
    if valeur is None:
        return "—"
    if isinstance(valeur, (str, int, float)):
        return pages.e(str(valeur))
    return "Valeur illisible"


def _suivis(rapport: Mapping[str, Any]) -> Any:
    valeurs = rapport.get("suivis")
    if isinstance(valeurs, (list, tuple)):
        return valeurs
    candidates = [
        v for v in rapport.values()
        if isinstance(v, (list, tuple)) and v and all(isinstance(s, Mapping) and "suivi_id" in s for s in v)
    ]
    return candidates[0] if len(candidates) == 1 else None


def _liste(rapport: Mapping[str, Any], reference: str, prefixe: str, suivant: str | None) -> str:
    suivis = _suivis(rapport)
    contenu = [
        '<section class="carte pile"><h2>Suivis ouverts</h2>',
        f"<p>Référence fournie : {pages.e(reference)}</p>",
        f"<p>Total ouvert : {pages.e(_compte(rapport.get('total')))} · "
        f"Reste après cette page : {pages.e(_compte(rapport.get('reste')))}</p>",
        "<p>Lecture M9 pure des plans approuvés et non clos par revue humaine. "
        "Elle n’atteste ni action terrain ni actualité métier.</p>",
    ]
    if suivis is None:
        contenu.append('<p class="message message-alerte">Liste des suivis indisponible.</p>')
    elif not suivis:
        contenu.append('<p class="vide">Aucun suivi ouvert rendu par M9 pour cette page.</p>')
    else:
        lignes = [s for s in suivis if isinstance(s, Mapping)]
        if len(lignes) != len(suivis):
            contenu.append('<p class="message message-alerte">Un ou plusieurs suivis sont mal formés.</p>')
        contenu.append('<div class="table-defilante"><table><thead><tr>'
                       "<th>Suivi</th><th>Action</th><th>Responsable</th><th>Échéance originale</th>"
                       "<th>État face à la référence</th><th>Plan, preuve et empreinte</th>"
                       "</tr></thead><tbody>")
        for item in lignes:
            ident = _brut(item, "suivi_id")
            if isinstance(ident, str):
                cible = f"{prefixe}/strategie/suivi?{urlencode({'suivi_id': ident})}"
                cellule = f'<a href="{pages.e(cible)}">{pages.e(ident)}</a>'
            else:
                cellule = "Identifiant indisponible"
            contenu.append(
                "<tr>"
                f"<th scope='row'>{cellule}</th>"
                f"<td>{pages.e(_champ(item, 'action'))}</td>"
                f"<td>{pages.e(_champ(item, 'responsable_id'))}</td>"
                f"<td>{pages.e(_champ(item, 'echeance'))}</td>"
                f"<td>{pages.e(_champ(item, 'statut_echeance'))}</td>"
                f"<td><details><summary>Voir le rendu M9</summary>{_arbre(item)}</details></td>"
                "</tr>"
            )
        contenu.append("</tbody></table></div>")
    if suivant is not None:
        contenu.append(f'<p><a href="{pages.e(suivant)}">Page suivante (même référence et même vue)</a></p>')
    elif rapport.get("prochain_depart") not in (None, 0):
        contenu.append('<p class="message message-alerte">Page suivante indisponible : reprise mal formée.</p>')
    else:
        contenu.append("<p>Fin de la liste pour cette référence.</p>")
    contenu.append("</section>")
    return "".join(contenu)


def _detail(suivi: Mapping[str, Any], retour: str) -> str:
    return (
        '<section class="carte pile">'
        f"<h2>Suivi {pages.e(_champ(suivi, 'suivi_id'))}</h2>"
        f"<p>Action : {pages.e(_champ(suivi, 'action'))}</p>"
        f"<p>Responsable : {pages.e(_champ(suivi, 'responsable_id'))}</p>"
        f"<p>Échéance originale : {pages.e(_champ(suivi, 'echeance'))}</p>"
        "<p>La preuve source est historique, telle que conservée par M9 lors de l’approbation ; "
        "elle n’affirme aucune actualité métier. La clôture par revue humaine éventuelle figure ci-dessous.</p>"
        "<h3>Plan, preuve source et clôture éventuelle (rendu M9 complet)</h3>"
        f"{_arbre(suivi)}"
        f'<p><a href="{pages.e(retour)}">Retour à l’échéancier</a></p></section>'
    )
