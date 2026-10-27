"""CRM secrétariat : répertoire et dossier client/projet (CRM-04, CRM-05), sur la vérité M2.

Ajout de notes internes authentifiées.

- `GET /crm` : répertoire paginé des leads/clients (statut, propriétaire, travaux, ville, dernière activité,
  prochaine action, segments) ; chaque ligne mène au dossier.
- `GET /crm/lead/{lead_id}` : dossier d'un client à partir d'un de ses leads — contact, opportunités (plusieurs projets
  d'un même client), activités récentes, et les neuf sections du dossier avec leur état réel (affichée, source existante
  non branchée, non disponible). Une section sans primitive ne montre ni donnée ni faux bouton.

Aucune donnée métier n'est stockée ici : lectures et notes passent par `metier.executer` (listes fermées).
Les outils M2 de lecture et `m2_enregistrer_interaction` sont appelés sous l'identité `admin`
confirmée en base.
Les fonctions `contenu_*` sont pures ; toute valeur dynamique passe par `pages.e`.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from .. import idempotence, tableau_de_bord
from . import metier, pages
from .securite import Session

LIMITE_PAGE = 20  # = m2_revenue_crm.liste_leads.LIMITE_DEFAUT : la page que M2 rend sans argument de taille
DECALAGE_MAX = 1_000_000
FUSEAU = "America/Montreal"
# Vocabulaire d'affichage des statuts de M2 (`m2_revenue_crm.statuts.STATUTS`, un test garde l'alignement). Le
# filtre est aussi validé par le schéma de l'outil M2 : une valeur inconnue n'atteint jamais le registre.
STATUTS = {
    "nouveau": "Nouveau",
    "qualifie": "Qualifié",
    "converti": "Converti",
    "perdu": "Perdu",
    "cedule": "Cédulé",
    "chantier": "Chantier",
    "facture": "Facturé",
    "paiement": "Paiement",
    "avis": "Avis",
}
_IDENTIFIANT = re.compile(r"[\w.:@\-]{1,200}")

ETATS_SECTION = {
    "affiche": ("Affichée", "badge-ok"),
    "existant": ("Source existante, pas encore branchée", "badge-alerte"),
    "partiel": ("Source partielle, pas encore branchée", "badge-alerte"),
    "manquant": ("Non disponible", "badge-danger"),
}
# (clé, libellé du brief CRM-05, source de vérité, état réel, explication). Aucun nom d'outil à l'écran : la
# traçabilité outil par outil vit dans docs/grs/crm/EXIGENCES-SECRETARIAT-3EN1.md. « Vérification » n'est pas recopiée :
# le brief ne la valide pas comme exigence métier.
SECTIONS = (
    ("activites", "Activités", "M2 — notes internes et suivi", "affiche",
     "Notes et interactions consignées dans M2 (les plus récentes du client), affichées plus bas."),
    ("suivi", "Suivi client", "M2 / M1 — courriels", "manquant",
     "Aucun journal des courriels envoyés et reçus par client : rien n'est présenté comme « envoyé » ou « livré »."),
    ("rencontres", "Rencontres", "Agenda (à trancher)", "manquant",
     "Pas d'agenda ni de rendez-vous reliés au dossier."),
    ("soumissions", "Soumissions", "M3 — estimation", "existant",
     "La lecture des devis existe dans M3 ; le dossier ne l'affiche pas encore. "
     "Modèles et clauses versionnés : à créer."),
    ("bons_commande", "Bons de commande", "M6 — matériaux", "partiel",
     "Bons de commande structurés par articles dans M6 ; la grosse note libre n'existe pas encore."),
    ("bons_travail", "Bons de travail", "M4 — planning", "existant",
     "Interventions et cédule dans M4 ; la fenêtre planifiée n'y est pas encore publiée."),
    ("couts", "Coûts des travaux", "M5 — finance (avec M6 et M4)", "existant",
     "Rentabilité et écarts prévu/réel dans M5, M3 et M6 ; non affichés ici pour l'instant."),
    ("factures", "Factures", "M5 — finance", "partiel",
     "Factures client dans M5 ; la correction tracée d'une facture émise n'existe pas encore."),
    ("fichiers", "Photos et fichiers", "M10 / M4 — documents d'affaire", "partiel",
     "Dépôt et lecture de documents existent dans M10 et M4 ; pas encore d'aperçu ni de rattachement ici."),
)


# -- présentation (fonctions pures) ----------------------------------------------------------------


def _montreal(iso: Any) -> str:
    """L'instant en heure de Montréal ; une valeur absente ou illisible est rendue telle quelle, jamais devinée."""
    if not isinstance(iso, str) or not iso:
        return "—"
    try:
        moment = datetime.fromisoformat(iso)
        if moment.tzinfo is None:
            return iso
        return f"{moment.astimezone(ZoneInfo(FUSEAU)):%Y-%m-%d %H:%M}"
    except (ValueError, ZoneInfoNotFoundError):
        return iso


def _texte(valeur: Any) -> str:
    affichable = isinstance(valeur, str | int | float) and not isinstance(valeur, bool) and valeur != ""
    return pages.e(valeur) if affichable else "—"


def _badge_statut(statut: Any) -> str:
    return pages._badge(STATUTS.get(statut, str(statut)) if isinstance(statut, str) else "—")


def _noms_segments(entrees: Any) -> list[str]:
    noms: list[str] = []
    for entree in entrees if isinstance(entrees, Iterable) and not isinstance(entrees, str | bytes) else ():
        nom = entree.get("segment") if isinstance(entree, Mapping) else entree
        if isinstance(nom, str) and nom:
            noms.append(nom)
    return noms


def _action(action: Any) -> str:
    if not isinstance(action, Mapping):
        return "—"
    echeance = action.get("echeance")
    suite = f" ({pages.e(_montreal(echeance))})" if echeance else ""
    return f"{_texte(action.get('description'))}{suite}"


def _lien_dossier(lead_id: str, prefixe: str) -> str:
    return f'<a href="{pages.e(prefixe)}/crm/lead/{pages._segment(lead_id)}">{pages.e(lead_id)}</a>'


def _lien_repertoire(prefixe: str, statut: str, decalage: int) -> str:
    requete = []
    if statut:
        requete.append(f"statut={pages._segment(statut)}")
    if decalage:
        requete.append(f"decalage={decalage}")
    return f"{pages.e(prefixe)}/crm" + (("?" + "&amp;".join(requete)) if requete else "")


def contenu_repertoire(page: Mapping[str, Any], *, statut: str, prefixe: str) -> str:
    """Le répertoire : filtre par statut, tableau, pagination fidèle au `decalage` de M2."""
    options = "".join(
        f'<option value="{pages.e(cle)}"{" selected" if cle == statut else ""}>{pages.e(libelle)}</option>'
        for cle, libelle in STATUTS.items()
    )
    filtre = (
        f'<form method="get" action="{pages.e(prefixe)}/crm" class="pile">'
        '<label for="statut">Statut</label>'
        f'<select id="statut" name="statut"><option value="">Tous</option>{options}</select>'
        '<button type="submit">Filtrer</button></form>'
    )
    leads = page.get("leads") if isinstance(page.get("leads"), list) else []
    total = page.get("total") if isinstance(page.get("total"), int) else 0
    decalage = page.get("decalage") if isinstance(page.get("decalage"), int) else 0
    if not leads:
        corps = pages._vide("Aucun lead ne correspond à ce filtre." if statut else "Aucun lead enregistré dans M2.")
    else:
        lignes = []
        for lead in leads:
            if not isinstance(lead, Mapping) or not isinstance(lead.get("lead_id"), str):
                continue
            segments = " ".join(pages._badge(nom) for nom in _noms_segments(lead.get("segments"))) or "—"
            lignes.append(
                f"<tr><td>{_lien_dossier(lead['lead_id'], prefixe)}</td><td>{_badge_statut(lead.get('statut'))}</td>"
                f"<td>{_texte(lead.get('proprietaire'))}</td><td>{_texte(lead.get('travaux'))}</td>"
                f"<td>{_texte(lead.get('ville'))}</td><td>{pages.e(_montreal(lead.get('ingere_le')))}</td>"
                f"<td>{pages.e(_montreal(lead.get('derniere_activite')))}</td>"
                f"<td>{_action(lead.get('prochaine_action'))}</td><td>{segments}</td></tr>"
            )
        corps = (
            '<div class="table-defilante"><table><thead><tr><th>Dossier</th><th>Statut</th><th>Propriétaire</th>'
            "<th>Travaux</th><th>Ville</th><th>Reçu (heure de Montréal)</th><th>Dernière activité</th>"
            "<th>Prochaine action</th><th>Segments</th></tr></thead><tbody>"
            + "".join(lignes) + "</tbody></table></div>"
        )
    navigation = []
    if decalage:
        navigation.append(f'<a href="{_lien_repertoire(prefixe, statut, 0)}">Revenir au début</a>')
    suivant = page.get("suivant")
    if isinstance(suivant, int) and not isinstance(suivant, bool):
        navigation.append(f'<a href="{_lien_repertoire(prefixe, statut, suivant)}">Page suivante</a>')
    message = page.get("message")
    notes = [
        f"<p>{total} lead(s) correspondent ; ordre : {_texte(page.get('ordre'))}.</p>",
        f'<p class="note">{pages.e(message)}</p>' if isinstance(message, str) and message else "",
    ]
    non_calculables = _noms_segments(page.get("segments_non_calculables"))
    if non_calculables:
        notes.append(
            '<p class="note">Segments non calculables faute de seuil ou de donnée dans M2 : '
            f"{pages.e(', '.join(non_calculables))}. Aucune valeur n'est devinée.</p>"
        )
    return (
        '<section class="carte"><h2>Répertoire clients et prospects</h2>'
        '<p class="note">Lecture seule de M2 (vérité commerciale). Pas de recherche par nom ni de correction '
        "de coordonnées pour l'instant : ces capacités n'existent pas encore dans M2.</p>"
        + filtre + "".join(notes) + corps
        + (f"<p>{' · '.join(navigation)}</p>" if navigation else "")
        + "</section>"
    )


def _contact(contact: Any) -> str:
    if not isinstance(contact, Mapping):
        return pages._vide("Aucune coordonnée dans le contrat ingéré.")
    libelles = (("nom", "Nom"), ("courriel", "Courriel"), ("telephone", "Téléphone"), ("adresse", "Adresse"))
    lignes = [
        f"<dt>{pages.e(libelle)}</dt><dd>{pages.e(contact[cle])}</dd>"
        for cle, libelle in libelles
        if isinstance(contact.get(cle), str) and contact[cle]
    ]
    if not lignes:
        return pages._vide("Aucune coordonnée dans le contrat ingéré.")
    return "<dl>" + "".join(lignes) + "</dl>"


def _opportunites(vue: Mapping[str, Any], lead_courant: str, prefixe: str) -> str:
    opportunites = vue.get("opportunites") if isinstance(vue.get("opportunites"), list) else []
    lignes = []
    for opp in opportunites:
        if not isinstance(opp, Mapping) or not isinstance(opp.get("lead_id"), str):
            continue
        ici = " (affiché ici)" if opp["lead_id"] == lead_courant else ""
        travaux = opp.get("service") or opp.get("type_travaux")
        lignes.append(
            f"<tr><td>{_lien_dossier(opp['lead_id'], prefixe)}{pages.e(ici)}</td>"
            f"<td>{_badge_statut(opp.get('statut'))}</td>"
            f"<td>{_texte(travaux)}</td><td>{_texte(opp.get('ville'))}</td><td>{_texte(opp.get('canal'))}</td>"
            f"<td>{_texte(opp.get('source'))}</td><td>{_action(opp.get('prochaine_action'))}</td></tr>"
        )
    if not lignes:
        return pages._vide("Aucune opportunité visible pour ce client.")
    return (
        '<div class="table-defilante"><table><thead><tr><th>Lead</th><th>Statut</th><th>Travaux</th><th>Ville</th>'
        "<th>Canal</th><th>Source</th><th>Prochaine action</th></tr></thead><tbody>" + "".join(lignes)
        + "</tbody></table></div>"
    )


def _sections() -> str:
    lignes = []
    for _cle, libelle, source, etat, explication in SECTIONS:
        texte, classe = ETATS_SECTION[etat]
        lignes.append(
            f"<tr><td>{pages.e(libelle)}</td><td>{pages._badge(texte, classe)}</td><td>{pages.e(source)}</td>"
            f"<td>{pages.e(explication)}</td></tr>"
        )
    return (
        '<div class="table-defilante"><table><thead><tr><th>Section</th><th>État</th><th>Source de vérité</th>'
        "<th>Contenu</th></tr></thead><tbody>" + "".join(lignes) + "</tbody></table></div>"
    )


def _activites(vue: Mapping[str, Any]) -> str:
    interactions = vue.get("interactions_recentes") if isinstance(vue.get("interactions_recentes"), list) else []
    lignes = [
        f"<tr><td>{pages.e(_montreal(i.get('horodatage')))}</td><td>{_lien_court(i.get('lead_id'))}</td>"
        f"<td>{_texte(i.get('auteur'))}</td><td>{_texte(i.get('resume'))}</td></tr>"
        for i in reversed(interactions)
        if isinstance(i, Mapping)
    ]
    if not lignes:
        return pages._vide("Aucune note ni interaction consignée dans M2 pour ce client.")
    return (
        '<div class="table-defilante"><table><thead><tr><th>Date (heure de Montréal)</th><th>Lead</th><th>Auteur</th>'
        "<th>Résumé</th></tr></thead><tbody>" + "".join(lignes) + "</tbody></table></div>"
    )


def _lien_court(lead_id: Any) -> str:
    return pages.e(lead_id) if isinstance(lead_id, str) else "—"


def contenu_dossier(lead_id: str, client_id: str, vue: Mapping[str, Any], *, prefixe: str) -> str:
    """Dossier client, projets, sections avec état réel et activités.

    La route authentifiée ajoute le formulaire de note.
    """
    return (
        f'<p><a href="{pages.e(prefixe)}/crm">Retour au répertoire</a></p>'
        f'<section class="carte"><h2>Client</h2><p class="note">Identifiant client M2 : {pages.e(client_id)}</p>'
        + _contact(vue.get("contact")) + "</section>"
        '<section class="carte"><h2>Projets et opportunités du client</h2>' + _opportunites(vue, lead_id, prefixe)
        + "</section>"
        '<section class="carte"><h2>Sections du dossier</h2>'
        '<p class="note">Chaque section dit sa source de vérité et son état réel. Les sections non branchées '
        "ne montrent aucune donnée et aucune action.</p>" + _sections() + "</section>"
        '<section class="carte" id="activites"><h2>Activités</h2>'
        '<p class="note">Dix interactions les plus récentes du client, tous projets confondus.</p>'
        + _activites(vue) + "</section>"
    )


def formulaire_note(lead_id: str, csrf: str, prefixe: str) -> str:
    return (
        '<section class="carte"><h2>Ajouter une note</h2>'
        '<p>Note interne sur cette demande active, visible dans les activités du client. '
        'Les notes déjà consignées restent dans l’historique.</p>'
        f'<form method="post" action="{pages.e(prefixe)}/crm/lead/{pages._segment(lead_id)}/notes" class="pile">'
        f'<input type="hidden" name="csrf" value="{pages.e(csrf)}">'
        f'<input type="hidden" name="mutation_id" value="{uuid.uuid4()}">'
        '<label for="resume-note">Votre note (300 caractères maximum)</label>'
        '<textarea id="resume-note" name="resume" maxlength="300" required rows="4"></textarea>'
        '<button type="submit">Enregistrer la note</button></form></section>'
    )


# -- routes ----------------------------------------------------------------------------------------

_HTTP_PAR_VERDICT = {
    "REJ-IDENTITE-APPAREIL-INVALIDE": 403,
    "REJ-LEAD-NON-ASSIGNE": 404,
    "REJ-TRANSITION-ILLEGALE": 404,
    "REJ-PAGINATION-INVALIDE": 400,
    "REJ-ENUM-INVALIDE": 400,
    "REJ-CONVERSATION-CLOSE": 409,
    "REJ-CHAMP-VIDE": 400,
    "REJ-CONTRAT-INVALIDE": 400,
}


def creer_router(
    *,
    session_page: Callable[..., Session],
    cnx_factory: Callable[[], Any],
    deps: Mapping[str, Any],
    prefixe: str,
    ecriture_api: Callable[..., Session],
    formulaire: Callable[..., Any],
    objet_json: Callable[..., Any],
    verifier_formulaire: Callable[..., None],
) -> APIRouter:
    router = APIRouter()

    def lire(session: Session, nom: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        """Un outil de lecture M2 par la surface fermée de la console : résultat accepté, ou erreur HTTP sobre."""
        try:
            with cnx_factory() as cnx:
                reponse = metier.executer(cnx, deps, session, nom, arguments)
        except PermissionError:
            raise HTTPException(403, "accès refusé") from None
        except KeyError:
            raise HTTPException(503, "CRM indisponible") from None
        except ValueError:
            raise HTTPException(400, "requête invalide") from None
        return extraire_resultat(reponse)

    def extraire_resultat(reponse: Any) -> Mapping[str, Any]:
        sortie = reponse.get("resultat") if isinstance(reponse, Mapping) and reponse.get("ok") is True else None
        if not isinstance(sortie, Mapping):
            raise HTTPException(503, "CRM temporairement indisponible")
        if sortie.get("accepte") is True and isinstance(sortie.get("resultat"), Mapping):
            return sortie["resultat"]
        verdict = sortie.get("verdict")
        code = verdict.get("code") if isinstance(verdict, Mapping) else None
        statut_http = _HTTP_PAR_VERDICT.get(code, 503)
        detail = "CRM indisponible" if statut_http == 503 else "dossier introuvable ou accès refusé"
        if code == "REJ-CONVERSATION-CLOSE":
            detail = "Cette demande est close : les nouvelles notes sont réservées aux demandes actives."
        raise HTTPException(statut_http, detail)

    def rendre(session: Session, titre: str, corps: str) -> HTMLResponse:
        with cnx_factory() as cnx:
            en_attente = tableau_de_bord.nombre_en_attente(cnx, pages.PLAFOND_PASTILLE)
        page = pages.gabarit(titre, corps, prefixe=prefixe, session=session, actif="crm", en_attente=en_attente)
        return HTMLResponse(page, headers={"Cache-Control": "no-store"})

    @router.get("/crm", response_class=HTMLResponse)
    def repertoire(request: Request) -> Response:
        session = session_page(request)
        parametres = request.query_params
        if set(parametres) - {"statut", "decalage"}:
            raise HTTPException(400, "requête invalide")
        statut = parametres.get("statut", "")
        if statut and statut not in STATUTS:
            raise HTTPException(400, "requête invalide")
        brut = parametres.get("decalage", "0")
        if len(brut) > len(str(DECALAGE_MAX)) or not brut.isascii() or not brut.isdigit() or int(brut) > DECALAGE_MAX:
            raise HTTPException(400, "requête invalide")
        arguments: dict[str, Any] = {"decalage": int(brut), "limite": LIMITE_PAGE}
        if statut:
            arguments["statut"] = statut
        page = lire(session, "m2_lister_leads", arguments)
        return rendre(session, "Répertoire CRM", contenu_repertoire(page, statut=statut, prefixe=prefixe))

    @router.get("/crm/lead/{lead_id}", response_class=HTMLResponse)
    def dossier(lead_id: str, request: Request) -> Response:
        session = session_page(request)
        if _IDENTIFIANT.fullmatch(lead_id) is None:
            raise HTTPException(404, "dossier introuvable")
        lien = lire(session, "m2_trouver_client_de_lead", {"lead_id": lead_id})
        client_id = lien.get("client_id")
        if not isinstance(client_id, str) or not client_id:
            raise HTTPException(503, "CRM temporairement indisponible")
        vue = lire(session, "m2_obtenir_client_360", {"client_id": client_id})
        return rendre(session, "Dossier client",
                      contenu_dossier(lead_id, client_id, vue, prefixe=prefixe)
                      + formulaire_note(lead_id, session.csrf, prefixe))

    def ajouter_note(session: Session, lead_id: str, champs: Mapping[str, Any]) -> dict:
        if _IDENTIFIANT.fullmatch(lead_id) is None:
            raise HTTPException(404, "dossier introuvable")
        if not isinstance(champs, Mapping) or set(champs) != {"resume", "mutation_id"}:
            raise HTTPException(400, "champs de la note invalides")
        resume, mutation = champs["resume"], champs["mutation_id"]
        if (not isinstance(resume, str) or not resume.strip() or len(resume) > 300
                or not isinstance(mutation, str) or not mutation.strip() or len(mutation) > 200):
            raise HTTPException(400, "note ou identifiant de saisie invalide")
        try:
            with cnx_factory() as cnx:
                reponse = metier.executer(cnx, deps, session, "m2_enregistrer_interaction",
                                         {"lead_id": lead_id, "resume": resume}, mutation_id=mutation)
                resultat = extraire_resultat(reponse)
        except PermissionError:
            raise HTTPException(403, "accès refusé") from None
        except KeyError:
            raise HTTPException(503, "notes temporairement indisponibles") from None
        except ValueError as exc:
            if isinstance(exc.__cause__, idempotence.MutationConflit):
                raise HTTPException(409, "identifiant de saisie déjà utilisé pour une autre note") from None
            raise HTTPException(400, "note invalide") from None
        return {"ok": True, "resultat": resultat, "rejoue": reponse.get("rejoue") is True}

    @router.post("/api/crm/lead/{lead_id}/notes")
    async def note_api(lead_id: str, request: Request) -> Response:
        session = ecriture_api(request)
        return JSONResponse(ajouter_note(session, lead_id, await objet_json(request)))

    @router.post("/crm/lead/{lead_id}/notes")
    async def note_formulaire(lead_id: str, request: Request) -> Response:
        session = session_page(request)
        champs = await formulaire(request)
        verifier_formulaire(champs, session)
        ajouter_note(session, lead_id, {k: v for k, v in champs.items() if k != "csrf"})
        return RedirectResponse(f"{prefixe}/crm/lead/{pages._segment(lead_id)}#activites", status_code=303)

    return router
