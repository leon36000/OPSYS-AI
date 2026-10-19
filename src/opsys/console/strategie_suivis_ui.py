"""Console des suivis stratégiques M9 en lecture seule."""

from __future__ import annotations

import json
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
_PARAMETRES_BILAN = frozenset({"debut", "fin", "depart", "vue_attendue"})
_PARAMETRES_RAPPORT = frozenset({"debut", "fin", "depart", "vue_attendue"})
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

    def lien_bilan(**parametres: Any) -> str:
        cible = f"{prefixe}/strategie/bilan"
        return f"{cible}?{urlencode(parametres)}" if parametres else cible

    @router.get("/strategie/bilan", response_class=HTMLResponse)
    def page_bilan(request: Request) -> HTMLResponse:
        session = session_page(request)
        # Le callback recharge les rôles SQL, mais accepte aussi le propriétaire sans admin.
        # Cette nouvelle surface exige admin, même avant le formulaire vide.
        if "admin" not in session.roles:
            raise HTTPException(403, "accès métier refusé")
        valeurs = _valeurs(request, _PARAMETRES_BILAN)
        if not valeurs:
            return page(session, _formulaire_bilan(prefixe, "", ""))
        if not {"debut", "fin"} <= valeurs.keys():
            raise HTTPException(400, "debut et fin explicites requis ensemble")
        debut, fin = valeurs["debut"], valeurs["fin"]
        arguments: dict[str, Any] = {"debut": debut, "fin": fin}
        if "depart" in valeurs:
            if not _DEPART.fullmatch(valeurs["depart"]):
                raise HTTPException(400, "depart doit être un entier décimal positif ou nul")
            arguments["depart"] = int(valeurs["depart"])
        if "vue_attendue" in valeurs:
            arguments["vue_attendue"] = valeurs["vue_attendue"]
        reprise = arguments.get("depart", 0) > 0 or "vue_attendue" in arguments
        try:
            rapport = lire(session, "m9_bilan_suivis_decision", arguments)
        except _Refus as refus:
            return page(session, _refus_html(
                "Lecture historique refusée. Recommencez le bilan pour la même période."
                if reprise else "Bilan refusé par M9 pour cette période.",
                refus.code,
                lien_bilan(debut=debut, fin=fin),
                "Recommencer le bilan avec la même période",
            ), 409 if reprise or not refus.invalide else 400)
        suivant = None
        prochain, vue = rapport.get("prochain_depart"), rapport.get("vue")
        if type(prochain) is int and prochain > 0 and isinstance(vue, str):
            suivant = lien_bilan(debut=debut, fin=fin, depart=prochain, vue_attendue=vue)
        return page(session, _formulaire_bilan(prefixe, debut, fin) + _bilan(rapport, suivant))

    def lien_rapport(**parametres: Any) -> str:
        cible = f"{prefixe}/strategie/rapport"
        return f"{cible}?{urlencode(parametres)}" if parametres else cible

    @router.get("/strategie/rapport", response_class=HTMLResponse)
    def page_rapport(request: Request) -> HTMLResponse:
        session = session_page(request)
        # Même garde que le bilan : admin SQL rechargé, avant le formulaire vide et toute analyse.
        if "admin" not in session.roles:
            raise HTTPException(403, "accès métier refusé")
        valeurs = _valeurs(request, _PARAMETRES_RAPPORT)
        if not valeurs:
            return page(session, _formulaire_rapport(prefixe, "", ""))
        if not {"debut", "fin"} <= valeurs.keys():
            raise HTTPException(400, "debut et fin explicites requis ensemble")
        debut, fin = valeurs["debut"], valeurs["fin"]
        arguments: dict[str, Any] = {"debut": debut, "fin": fin}
        if "depart" in valeurs:
            if not _DEPART.fullmatch(valeurs["depart"]):
                raise HTTPException(400, "depart doit être un entier décimal positif ou nul")
            arguments["depart"] = int(valeurs["depart"])
        if "vue_attendue" in valeurs:
            arguments["vue_attendue"] = valeurs["vue_attendue"]
        reprise = arguments.get("depart", 0) > 0 or "vue_attendue" in arguments
        recommencer = lien_rapport(debut=debut, fin=fin)
        try:
            rapport = lire(session, "m9_rapport_periode", arguments)
        except _Refus as refus:
            return page(session, _refus_html(
                "Reprise refusée : la vue a changé ou est invalide. Recommencez la synthèse pour la même période."
                if reprise else "Synthèse refusée par M9 pour cette période.",
                refus.code,
                recommencer,
                "Recommencer la synthèse avec la même période",
            ), 409 if reprise or not refus.invalide else 400)
        # Aucun rendu partiel d'une réponse dont le type, la partialité ou les bornes diffèrent de la demande.
        if (rapport.get("type") != "RAPPORT_PERIODE" or rapport.get("rapport_complet") is not False
                or rapport.get("debut") != debut or rapport.get("fin") != fin):
            return page(session, _refus_html(
                "Réponse M9 non conforme : rien n’est affiché. Recommencez la synthèse pour la même période.",
                "",
                recommencer,
                "Recommencer la synthèse avec la même période",
            ), 409)
        alertes = rapport.get("alertes_periode")
        alertes = alertes if isinstance(alertes, Mapping) else {}
        suivant = None
        prochain, vue = alertes.get("prochain_depart"), rapport.get("vue")
        if type(prochain) is int and prochain > 0 and isinstance(vue, str):
            suivant = lien_rapport(debut=debut, fin=fin, depart=prochain, vue_attendue=vue)
        return page(session, _formulaire_rapport(prefixe, debut, fin) + _rapport(rapport, suivant))

    def lien_observations(**parametres: Any) -> str:
        cible = f"{prefixe}/strategie/observations"
        return f"{cible}?{urlencode(parametres)}" if parametres else cible

    @router.get("/strategie/observations", response_class=HTMLResponse)
    def page_observations(request: Request) -> HTMLResponse:
        session = session_page(request)
        if "admin" not in session.roles:
            raise HTTPException(403, "accès métier refusé")
        valeurs = _valeurs(request, _PARAMETRES_RAPPORT)
        if any(len(valeur) > 1024 for valeur in valeurs.values()):
            raise HTTPException(400, "paramètre trop long refusé")
        if not valeurs:
            return page(session, _formulaire_observations(prefixe, "", ""))
        if not {"debut", "fin"} <= valeurs.keys():
            raise HTTPException(400, "debut et fin explicites requis ensemble")
        debut, fin = valeurs["debut"], valeurs["fin"]
        arguments: dict[str, Any] = {"debut": debut, "fin": fin}
        if "depart" in valeurs:
            if not _DEPART.fullmatch(valeurs["depart"]):
                raise HTTPException(400, "depart doit être un entier décimal positif ou nul")
            arguments["depart"] = int(valeurs["depart"])
        if "vue_attendue" in valeurs:
            arguments["vue_attendue"] = valeurs["vue_attendue"]
        reprise = arguments.get("depart", 0) > 0 or "vue_attendue" in arguments
        recommencer = lien_observations(debut=debut, fin=fin)

        def refuser(message: str, code: str = "", statut: int = 409) -> HTMLResponse:
            return page(session, _refus_html(
                message, code, recommencer, "Recommencer les observations avec la même période",
            ), statut)

        try:
            rapport = lire(session, "m9_observations_chantier_periode", arguments)
        except _Refus as refus:
            return refuser(
                "Reprise refusée. Recommencez les observations pour la même période."
                if reprise else "Observations refusées par M9 pour cette période.",
                refus.code or "REJ-OBSERVATIONS-LECTURE", 409 if reprise or not refus.invalide else 400,
            )
        if not _observations_valides(rapport, debut, fin, arguments.get("depart", 0)):
            return refuser("Réponse M9 non conforme : aucune observation affichée.")
        suivant = None
        if rapport["prochain_depart"] is not None:
            suivant = lien_observations(
                debut=debut, fin=fin, depart=rapport["prochain_depart"], vue_attendue=rapport["vue"],
            )
        try:
            reponse = page(session, _formulaire_observations(prefixe, debut, fin) + _observations(rapport, suivant))
        except (ValueError, TypeError, RecursionError):
            return refuser("Preuves M9 illisibles : aucune observation affichée.")
        if len(reponse.body) > 128 * 1024:
            return refuser("Preuves M9 trop grandes pour cette page : aucune troncature effectuée.")
        return reponse

    return router


def _formulaire(prefixe: str, reference: str) -> str:
    return (
        '<section class="carte pile"><h2>Échéancier des suivis ouverts</h2>'
        f'<p><a href="{pages.e(prefixe)}/strategie/bilan">Bilan historique des suivis</a></p>'
        f'<p><a href="{pages.e(prefixe)}/strategie/rapport">Synthèse de période</a></p>'
        f'<p><a href="{pages.e(prefixe)}/strategie/observations">Observations de chantier</a></p>'
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


def _formulaire_bilan(prefixe: str, debut: str, fin: str) -> str:
    return (
        '<section class="carte pile"><h2>Bilan historique des suivis</h2>'
        f'<form method="get" action="{pages.e(prefixe)}/strategie/bilan" class="pile">'
        '<label for="debut">Début inclus — ISO 8601 avec fuseau explicite</label>'
        f'<input id="debut" name="debut" required value="{pages.e(debut)}">'
        '<label for="fin">Fin exclue — ISO 8601 avec fuseau explicite</label>'
        f'<input id="fin" name="fin" required value="{pages.e(fin)}">'
        '<p class="note">Les décisions humaines sont lues sur cette période et dans leur état juste avant sa fin. '
        'Aucune date n’est déduite de l’horloge ; une revue humaine n’atteste aucune action terrain.</p>'
        '<button type="submit" class="principal">Afficher le bilan historique</button></form></section>'
    )


def _bilan(rapport: Mapping[str, Any], suivant: str | None) -> str:
    compteurs = rapport.get("compteurs")
    compteurs = compteurs if isinstance(compteurs, Mapping) else {}
    contenu = ['<section class="carte pile"><h2>Décisions humaines sur la période</h2>']
    for cle, libelle in (
        ("ouverts_periode", "Suivis ouverts pendant la période"),
        ("clotures_periode", "Suivis clos par revue humaine pendant la période"),
        ("ouverts_fin", "Suivis encore ouverts juste avant la fin"),
    ):
        valeur = _compte(compteurs.get(cle))
        contenu.append(f'<p data-compteur="{cle}" data-valeur="{pages.e(valeur)}">'
                       f'{libelle} : {pages.e(valeur)}</p>')
    suivis = rapport.get("suivis")
    if not isinstance(suivis, (list, tuple)):
        contenu.append('<p class="message message-alerte">Bilan indisponible.</p>')
    elif not suivis:
        contenu.append('<p class="vide">Aucun suivi pertinent pour cette période.</p>')
    else:
        for ligne in suivis:
            ident = _brut(ligne, "suivi_id") if isinstance(ligne, Mapping) else None
            if not isinstance(ident, str):
                contenu.append('<p class="message message-alerte">Suivi illisible.</p>')
                continue
            contenu.append(f'<article class="carte pile" data-suivi-id="{pages.e(ident)}">'
                           f'<h3>Suivi {pages.e(ident)}</h3>'
                           f'<p>Ouvert pendant la période : {_arbre(ligne.get("ouvert_dans_periode"))} · '
                           f'Clos pendant la période : {_arbre(ligne.get("cloture_dans_periode"))} · '
                           f'Ouvert juste avant la fin : {_arbre(ligne.get("ouvert_fin"))}</p>'
                           f'<details><summary>Plan, preuve et décisions historiques</summary>{_arbre(ligne)}</details>'
                           '</article>')
    if suivant is not None:
        contenu.append(f'<p><a href="{pages.e(suivant)}">Page suivante (même période et même vue)</a></p>')
    contenu.append('</section>')
    return ''.join(contenu)


def _formulaire_rapport(prefixe: str, debut: str, fin: str) -> str:
    return (
        '<section class="carte pile"><h2>Synthèse de période</h2>'
        f'<form method="get" action="{pages.e(prefixe)}/strategie/rapport" class="pile">'
        '<label for="debut">Début inclus — ISO 8601 avec fuseau explicite</label>'
        f'<input id="debut" name="debut" required value="{pages.e(debut)}">'
        '<label for="fin">Fin exclue — ISO 8601 avec fuseau explicite</label>'
        f'<input id="fin" name="fin" required value="{pages.e(fin)}">'
        '<p class="note">Début inclus, fin exclue, fuseau explicite ; aucune date déduite de l’horloge.</p>'
        '<button type="submit" class="principal">Afficher la synthèse de période</button></form></section>'
    )


def _rapport(rapport: Mapping[str, Any], suivant: str | None) -> str:
    suivis = rapport.get("suivis")
    suivis = suivis if isinstance(suivis, Mapping) else {}
    compteurs = suivis.get("compteurs")
    compteurs = compteurs if isinstance(compteurs, Mapping) else {}
    alertes = rapport.get("alertes_periode")
    alertes = alertes if isinstance(alertes, Mapping) else {}
    contenu = [
        '<section class="carte pile"><h2>Limites de la synthèse</h2>',
        f'<p>Statut : {_arbre(rapport.get("statut"))} · '
        f'Actualité métier : {_arbre(rapport.get("actualite_metier"))} · '
        f'Rapport complet : {_arbre(rapport.get("rapport_complet"))}</p>',
        '<p class="message message-alerte" role="status">Synthèse interne partielle : alertes M8 connues à la '
        "lecture, filtrées sur l’instant de référence chantier. Ce n’est pas le rapport exécutif hebdomadaire "
        "M9.6 ; n’atteste ni action terrain, ni cause, ni fraîcheur, ni complétude.</p>",
        f'<p>Période : du {_arbre(rapport.get("debut"))} inclus au {_arbre(rapport.get("fin"))} exclu</p>',
        '<h3>Décisions humaines sur la période</h3>',
    ]
    for cle, libelle, brut in (
        ("ouverts_periode", "Suivis ouverts pendant la période", compteurs.get("ouverts_periode")),
        ("clotures_periode", "Suivis clos par revue humaine pendant la période", compteurs.get("clotures_periode")),
        ("ouverts_fin", "Suivis encore ouverts juste avant la fin", compteurs.get("ouverts_fin")),
        ("suivis_total", "Suivis pertinents pour la période", suivis.get("total")),
        ("alertes_total", "Alertes M8 connues à la lecture dans la période", alertes.get("total")),
    ):
        valeur = _compte(brut)
        contenu.append(f'<p data-compteur="{cle}" data-valeur="{pages.e(valeur)}">'
                       f'{libelle} : {pages.e(valeur)}</p>')
    contenu.append('<h3>Alertes M8 de cette page</h3>')
    for cle, libelle in (
        ("depart", "Position de départ de cette page"),
        ("affichees", "Alertes affichées sur cette page"),
        ("reste", "Alertes restant après cette page"),
    ):
        contenu.append(f'<p data-page="{cle}">{libelle} : {pages.e(_compte(alertes.get(cle)))}</p>')
    contenu.append(f'<p>Ordre natif : {_arbre(alertes.get("ordre"))}</p>')
    liste = alertes.get("alertes")
    if not isinstance(liste, (list, tuple)):
        contenu.append('<p class="message message-alerte">Alertes indisponibles.</p>')
    elif not liste:
        contenu.append('<p class="vide">Aucune alerte M8 sur cette page.</p>')
    else:
        for alerte in liste:
            ident = alerte.get("evenement_id") if isinstance(alerte, Mapping) else None
            if not isinstance(ident, str):
                contenu.append('<p class="message message-alerte">Alerte illisible.</p>')
                continue
            metrique = alerte.get("metric_id")
            contenu.append(f'<article class="carte pile" data-evenement-id="{pages.e(ident)}" '
                           f'data-metric-id="{pages.e(metrique if isinstance(metrique, str) else "")}">'
                           f'<h4>Alerte {pages.e(ident)}</h4>'
                           f'<p>Événement : {pages.e(ident)} · Métrique : {_arbre(metrique)}</p>'
                           '<p>Instant de référence chantier (pas de réception) : '
                           f'{_arbre(alerte.get("horodatage_reference"))}</p>'
                           f'<p>Alerte M8 originale et preuve complète :</p>{_arbre(alerte)}'
                           '</article>')
    contenu.append('<h3>Manques déclarés par M9</h3>')
    manques = rapport.get("manques")
    if not isinstance(manques, (list, tuple)):
        contenu.append('<p class="message message-alerte">Manques indisponibles.</p>')
    else:
        contenu.append('<ul>')
        for manque in manques:
            if isinstance(manque, Mapping):
                contenu.append(f'<li>{_arbre(manque.get("section"))} : {_arbre(manque.get("constat"))} — '
                               f'{_arbre(manque.get("verifie"))}</li>')
            else:
                contenu.append('<li class="message message-alerte">Manque illisible.</li>')
        contenu.append('</ul>')
    if suivant is not None:
        contenu.append(f'<p><a href="{pages.e(suivant)}">Page suivante (même période et même vue)</a></p>')
    elif alertes.get("prochain_depart") is not None:
        contenu.append('<p class="message message-alerte">Page suivante indisponible : reprise mal formée.</p>')
    else:
        contenu.append("<p>Fin des alertes connues à la lecture pour cette période.</p>")
    contenu.append('</section>')
    return ''.join(contenu)


def _formulaire_observations(prefixe: str, debut: str, fin: str) -> str:
    return (
        '<section class="carte pile"><h2>Observations de chantier</h2>'
        '<p>Faits liés à une publication du bus, connus à la lecture, filtrés sur leur instant métier d’origine. '
        'Ni réception historique ni authentification du producteur ne sont prouvées.</p>'
        f'<form method="get" action="{pages.e(prefixe)}/strategie/observations" class="pile">'
        '<label for="observations-debut">Début inclus, ISO 8601 avec fuseau explicite</label>'
        f'<input id="observations-debut" name="debut" required value="{pages.e(debut)}">'
        '<label for="observations-fin">Fin exclue, ISO 8601 avec fuseau explicite</label>'
        f'<input id="observations-fin" name="fin" required value="{pages.e(fin)}">'
        '<p>Format AAAA-MM-JJTHH:MM:SS suivi de Z ou ±HH:MM ; aucune date déduite de l’horloge.</p>'
        '<button type="submit" class="principal">Afficher les observations</button></form></section>'
    )


def _observations_valides(rapport: Mapping[str, Any], debut: str, fin: str, depart: int) -> bool:
    """Contrat de présentation, sans recalcul métier ; toute anomalie refuse la page entière."""
    if ("prochain_depart" not in rapport or rapport.get("type") != "OBSERVATIONS_CHANTIER_PERIODE"
            or rapport.get("rapport_complet") is not False or rapport.get("statut") != "NON_VALIDE"
            or rapport.get("actualite_metier") != "NON_EVALUEE"
            or rapport.get("debut") != debut or rapport.get("fin") != fin
            or not isinstance(rapport.get("vue"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", rapport["vue"])):
        return False
    for nom in ("total", "depart", "affichees", "reste", "snapshots_generiques_non_couverts"):
        if type(rapport.get(nom)) is not int or rapport[nom] < 0:
            return False
    lignes, manques = rapport.get("observations"), rapport.get("manques")
    if (not isinstance(lignes, list) or rapport["affichees"] != len(lignes)
            or rapport["depart"] != depart
            or rapport["depart"] + rapport["affichees"] + rapport["reste"] != rapport["total"]
            or not isinstance(rapport.get("ordre"), str) or not rapport["ordre"]
            or not isinstance(manques, list) or not manques):
        return False
    prochain = rapport.get("prochain_depart")
    if rapport["reste"]:
        if (type(prochain) is not int or prochain != depart + len(lignes)
                or not lignes or not _DEPART.fullmatch(str(prochain))):
            return False
    elif prochain is not None:
        return False
    if not all(isinstance(m, Mapping) and all(isinstance(m.get(k), str)
               for k in ("section", "constat", "verifie")) for m in manques):
        return False
    ids: set[str] = set()
    for ligne in lignes:
        if (not isinstance(ligne, Mapping)
                or set(ligne) != {"maillon", "publication", "nature", "authentification_producteur"}
                or ligne["nature"] != "source_bus_liee" or ligne["authentification_producteur"] != "NON_PROUVEE"):
            return False
        maillon, publication = ligne["maillon"], ligne["publication"]
        if not isinstance(maillon, Mapping) or not isinstance(publication, Mapping):
            return False
        valeurs, source, fait = maillon.get("valeurs"), publication.get("source_m8"), publication.get("snapshot")
        ident = publication.get("evenement_id")
        if (not isinstance(ident, str) or not re.fullmatch(r"m8-snapshot-chantier-[0-9a-f]{64}", ident)
                or ident in ids or not isinstance(valeurs, Mapping) or not isinstance(source, Mapping)
                or not isinstance(fait, Mapping) or not isinstance(fait.get("valeurs"), Mapping)
                or type(maillon.get("index")) is not int or maillon["index"] < 0
                or not all(isinstance(maillon.get(k), str) for k in ("hash_precedent", "hash_maillon", "horodatage"))):
            return False
        if (maillon.get("module_source") != "m04-field-ops" or fait.get("module_source") != "m04-field-ops"
                or fait.get("horodatage") != maillon["horodatage"]
                or valeurs.get("m8_snapshot_evenement_id") != ident
                or type(source.get("index")) is not int or source["index"] < 0
                or valeurs.get("m8_snapshot_index") != str(source["index"])
                or valeurs.get("m8_snapshot_hash_maillon") != source.get("hash_maillon")
                or ident != "m8-snapshot-chantier-" + str(source.get("hash_maillon"))):
            return False
        metadata = {"m8_snapshot_evenement_id", "m8_snapshot_index", "m8_snapshot_hash_maillon"}
        if ({k: v for k, v in valeurs.items() if k not in metadata} != fait["valeurs"]
                or not all(isinstance(fait["valeurs"].get(k), str) for k in (
                    "m4_wct_id", "m4_intervention_id", "m4_duree_reelle_minutes"))):
            return False
        ids.add(ident)
    return True


def _observations(rapport: Mapping[str, Any], suivant: str | None) -> str:
    compteurs = "".join(
        f'<p data-compteur="{nom}" data-valeur="{rapport[cle]}">{libelle} : {rapport[cle]}</p>'
        for nom, cle, libelle in (
            ("observations_total", "total", "Observations dans la période"),
            ("generiques_non_couverts", "snapshots_generiques_non_couverts",
             "Snapshots génériques non couverts, registre entier"),
            ("observations_affichees", "affichees", "Observations sur cette page"),
        )
    )
    limites = "".join(
        f'<li><strong>{pages.e(m["section"])}</strong> : {pages.e(m["constat"])} '
        f'— {pages.e(m["verifie"])}</li>' for m in rapport["manques"]
    )
    blocs = []
    for ligne in rapport["observations"]:
        maillon, publication = ligne["maillon"], ligne["publication"]
        valeurs = publication["snapshot"]["valeurs"]
        champs = [("WCT", valeurs["m4_wct_id"]), ("Intervention", valeurs["m4_intervention_id"]),
                  ("Durée déclarée en minutes", valeurs["m4_duree_reelle_minutes"]),
                  ("Instant métier d’origine", maillon["horodatage"])]
        if "m4_type_travaux" in valeurs:
            champs.append(("Type de travaux", valeurs["m4_type_travaux"]))
        detail = "".join(f'<dt>{pages.e(nom)}</dt><dd>{pages.e(valeur)}</dd>' for nom, valeur in champs)
        preuves = "".join(
            f'<h4>{titre}</h4><pre data-preuve="{nom}">'
            f'{pages.e(json.dumps(obj, ensure_ascii=False, allow_nan=False))}</pre>'
            for nom, titre, obj in (("maillon", "Maillon M9 original", maillon),
                                    ("publication", "Publication du bus originale", publication))
        )
        blocs.append(
            f'<article class="carte pile" data-evenement-id="{pages.e(publication["evenement_id"])}">'
            f'<h3>{pages.e(publication["evenement_id"])}</h3><dl>{detail}</dl>'
            '<p>source_bus_liee — authentification_producteur : NON_PROUVEE. '
            'Cette liaison ne prouve pas la réception par M9.</p>'
            f'<details><summary>Preuves originales complètes</summary>{preuves}</details></article>'
        )
    navigation = f'<p><a href="{pages.e(suivant)}">Page suivante des observations</a></p>' if suivant else ""
    vide = '<p>Aucune observation retenue dans cette période.</p>' if not rapport["total"] else ""
    return (
        '<section class="carte pile"><h2>Observations connues à la lecture</h2>'
        '<p>Statut : NON_VALIDE ; actualité métier : NON_EVALUEE ; rapport_complet : faux.</p>'
        '<p>Couverture partielle : aucun total financier ni état complet M1–M8 ou rapport hebdomadaire attesté.</p>'
        f'{compteurs}<p>Ordre : {pages.e(rapport["ordre"])}</p><ul>{limites}</ul></section>'
        + vide + "".join(blocs) + navigation
    )
