"""CRM secrétariat : répertoire et dossier client/projet (CRM-04, CRM-05), sur la vérité M2.

Notes internes et corrections de coordonnées authentifiées, sur M2.

- `GET /crm` : répertoire paginé des leads/clients (statut, propriétaire, travaux, ville, dernière activité,
  prochaine action, segments) ; chaque ligne mène au dossier.
- `GET /crm/lead/{lead_id}` : dossier d'un client à partir d'un de ses leads — contact, opportunités (plusieurs projets
  d'un même client), activités récentes, et les neuf sections du dossier avec leur état réel (affichée, source existante
  non branchée, non disponible). Une section sans primitive ne montre ni donnée ni faux bouton.

Aucune donnée métier n'est stockée ici : lectures, notes et corrections passent par `metier.executer` (listes fermées).
Les outils M2 de lecture, `m2_enregistrer_interaction` et `m2_corriger_contact_client` utilisent
l'identité `admin` confirmée en base.
Les fonctions `contenu_*` sont pures ; toute valeur dynamique passe par `pages.e`.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Iterable, Mapping
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

from .. import idempotence, tableau_de_bord
from . import (
    agenda_ui,
    annotations_cedule_ui,
    catalogue_materiaux_ui,
    cedule_plan_ui,
    cedule_ui,
    couleurs_cedule_ui,
    devis_modele_ui,
    metier,
    modeles_soumission_ui,
    mois_cedule_ui,
    notes_commande_ui,
    pages,
    rencontres_ui,
)
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
    ("rencontres", "Rencontres", "M2 — agenda commercial", "affiche",
     "Rencontres du projet, tous vendeurs d’origine ; état courant et lien vers chaque historique."),
    ("soumissions", "Soumissions", "M3 — estimation", "affiche",
     "Consultation des soumissions du projet via le lien du dossier. "
     "Catalogue textuel versionné et création de brouillons avec modèle figé."),
    ("bons_commande", "Bons de commande", "M6 — matériaux", "partiel",
     "Notes d’achat libres accessibles depuis les soumissions avec chantier connu ; commandes fournisseurs séparées."),
    ("bons_travail", "Bons de travail", "M4 — planning", "existant",
     "Cédule hebdomadaire datée accessible depuis le répertoire CRM ; bons de travail détaillés non affichés ici."),
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


def _lien_repertoire(prefixe: str, statut: str, decalage: int, recherche: str = "") -> str:
    requete = []
    if statut:
        requete.append(f"statut={pages._segment(statut)}")
    if recherche:
        requete.append(f"q={pages._segment(recherche)}")
    if decalage:
        requete.append(f"decalage={decalage}")
    return f"{pages.e(prefixe)}/crm" + (("?" + "&amp;".join(requete)) if requete else "")


def contenu_repertoire(page: Mapping[str, Any], *, statut: str, prefixe: str, recherche: str = "") -> str:
    """Le répertoire : filtre par statut, tableau, pagination fidèle au `decalage` de M2."""
    options = "".join(
        f'<option value="{pages.e(cle)}"{" selected" if cle == statut else ""}>{pages.e(libelle)}</option>'
        for cle, libelle in STATUTS.items()
    )
    filtre = (
        f'<form method="get" action="{pages.e(prefixe)}/crm" class="pile">'
        '<label for="recherche">Nom, courriel, téléphone ou identifiant</label>'
        f'<input id="recherche" name="q" value="{pages.e(recherche)}" maxlength="120" type="search">'
        '<label for="statut">Statut</label>'
        f'<select id="statut" name="statut"><option value="">Tous</option>{options}</select>'
        '<button type="submit">Filtrer</button></form>'
    )
    leads = page.get("leads") if isinstance(page.get("leads"), list) else []
    total = page.get("total") if isinstance(page.get("total"), int) else 0
    decalage = page.get("decalage") if isinstance(page.get("decalage"), int) else 0
    if not leads:
        vide = "Aucun lead ne correspond à ce filtre." if statut or recherche else "Aucun lead enregistré dans M2."
        corps = pages._vide(vide)
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
        navigation.append(f'<a href="{_lien_repertoire(prefixe, statut, 0, recherche)}">Revenir au début</a>')
    suivant = page.get("suivant")
    if isinstance(suivant, int) and not isinstance(suivant, bool):
        navigation.append(f'<a href="{_lien_repertoire(prefixe, statut, suivant, recherche)}">Page suivante</a>')
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
        f'<p><a href="{pages.e(prefixe)}/crm/cedule">Cédule hebdomadaire des équipes</a></p>'
        f'<p><a href="{pages.e(prefixe)}/crm/agenda">Agenda des vendeurs</a></p>'
        '<p class="note">Lecture seule : recherche dans M2, sur tous les dossiers autorisés avant pagination. '
        'Les termes sont littéraux, sans distinction de casse ou d’accents. '
        'La correction des coordonnées reste à venir.</p>'
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


_STATUTS_DEVIS = {
    "brouillon": "Brouillon",
    "envoye": "Approuvé pour envoi — livraison non attestée",
    "accepte": "Accepté",
}


def _base_soumissions(lead_id: str, prefixe: str) -> str:
    return f"{prefixe}/crm/lead/{pages._segment(lead_id)}/soumissions"


def contenu_soumissions(lead_id: str, page: Mapping[str, Any], *, prefixe: str, decalage: int) -> str:
    base = _base_soumissions(lead_id, prefixe)
    lignes = []
    for devis in page["devis"]:
        ident = devis["devis_id"]
        lien = f"{base}/{pages._segment(ident)}"
        lignes.append(
            f'<tr><td><a href="{pages.e(lien)}">{pages.e(ident)}</a></td>'
            f'<td>{pages.e(_STATUTS_DEVIS.get(devis["statut"], devis["statut"]))}</td>'
            f'<td>{pages.e(devis["prix_total"])} CAD</td>'
            f'<td>{pages.e(_montreal(devis["horodatage"]))}</td></tr>'
        )
    tableau = (
        '<div class="table-defilante"><table><thead><tr><th>Soumission</th><th>Statut</th>'
        '<th>Prix total (source M3)</th><th>Date (Montréal)</th></tr></thead><tbody>'
        + "".join(lignes) + "</tbody></table></div>"
        if lignes else '<p>Aucune soumission sur cette page pour ce projet.</p>'
    )
    navigation = ""
    if decalage:
        navigation += f'<a href="{pages.e(base)}?decalage={max(0, decalage - LIMITE_PAGE)}">Page précédente</a> '
    suivant = page.get("decalage_suivant")
    if type(suivant) is int and 0 <= suivant <= DECALAGE_MAX:
        navigation += f'<a href="{pages.e(base)}?decalage={suivant}">Page suivante</a>'
    return (
        f'<p><a href="{pages.e(prefixe)}/crm/lead/{pages._segment(lead_id)}">Retour au dossier</a></p>'
        f'<p><a href="{pages.e(prefixe)}/crm/modeles-soumission">Modèles de soumission</a></p>'
        '<section class="carte"><h2>Soumissions de ce projet</h2>'
        '<p>Lecture des états courants de M3. Aucun envoi ni acceptation depuis cet écran. '
        'Le statut « approuvé pour envoi » ne prouve pas la réception par le client.</p>'
        + f'<p><a href="{pages.e(prefixe)}/crm/lead/{pages._segment(lead_id)}/nouvelle-soumission">'
        'Créer un brouillon depuis un modèle</a></p>'
        + tableau + '<nav aria-label="Pages de soumissions">' + navigation + '</nav></section>'
    )


def contenu_soumission(lead_id: str, devis: Mapping[str, Any], *, prefixe: str) -> str:
    lignes = []
    for ligne in devis["lignes"]:
        lignes.append("<tr>" + "".join(f"<td>{pages.e(ligne.get(k))}</td>" for k in (
            "description", "quantite", "unite", "prix_unitaire", "prix_ligne",
        )) + "</tr>")
    return (
        f'<p><a href="{pages.e(_base_soumissions(lead_id, prefixe))}">Retour aux soumissions</a></p>'
        f'<section class="carte"><h2>{pages.e(devis["devis_id"])}</h2>'
        f'<p>{pages.e(_STATUTS_DEVIS.get(devis["statut"], devis["statut"]))}</p>'
        '<p>Source : M3, état courant relu. Montants CAD tels que calculés par M3 ; '
        'aucun recalcul, ajout de taxes ni envoi depuis cet écran.</p>'
        '<div class="table-defilante"><table><thead><tr><th>Description</th><th>Quantité</th>'
        '<th>Unité</th><th>Prix unitaire</th><th>Prix de ligne</th></tr></thead><tbody>'
        + "".join(lignes) + '</tbody></table></div>'
        f'<p>Prix total M3 : {pages.e(devis["prix_total"])} CAD</p>'
        + ''.join(f'<p><a href="{pages.e(_base_soumissions(lead_id, prefixe))}/'
                  f'{pages._segment(devis["devis_id"])}/document/{fmt}">Brouillon {fmt.upper()}</a></p>'
                  for fmt in ('html', 'pdf')) +
        (f'<p>Modèle figé : {pages.e(devis["modele_soumission"]["titre"])} '
         f'— version {devis["modele_soumission"]["revision"]}</p>' if devis.get('modele_soumission') else '') +
        f'<p><a href="{pages.e(_base_soumissions(lead_id, prefixe))}/{pages._segment(devis["devis_id"])}/notes-achats">'
        'Notes d’achat du chantier</a></p>' +
        (f'<p><a href="{pages.e(_base_soumissions(lead_id, prefixe))}/{pages._segment(devis["devis_id"])}/'
         'preparation-chantier">Préparer la planification</a></p>' if devis['statut'] == 'accepte' else '') +
        '</section>'
    )


def contenu_historique_contact(lead_id: str, resultat: Mapping[str, Any], prefixe: str) -> str:
    """Historique administrateur : valeurs échappées, navigation dans la même révision maximale."""
    base = f"{prefixe}/crm/lead/{pages._segment(lead_id)}/contact/historique"
    corps = f'<h1>Historique des coordonnées</h1><p>{_lien_dossier(lead_id, prefixe)}</p>'
    corps += (f'<p><a href="{pages.e(prefixe)}/crm/lead/{pages._segment(lead_id)}/contact/memoire">'
              'Vérifier la transmission à M10</a></p>')
    corps += (f'<p>{resultat["total"]} corrections — jusqu’à la révision {resultat["revision_max"]}. '
              f'<a href="{pages.e(base)}">Actualiser l’historique</a></p>')
    for correction in resultat["corrections"]:
        corps += (f'<section class="carte"><h2>Révision {correction["revision"]}</h2>'
                  f'<p>{_texte(correction["auteur"])} — {pages.e(_montreal(correction["horodatage"]))}</p>'
                  f'<p>Motif : {_texte(correction["motif"])}</p><dl>')
        for titre, cle in [("Avant", "avant"), ("Après", "contact")]:
            corps += f'<dt>{titre}</dt><dd>' + ' ; '.join(
                f'{pages.e(k)} : {_texte(v)}' for k, v in correction[cle].items()) + '</dd>'
        corps += '</dl></section>'
    if not resultat["corrections"]:
        corps += pages._vide("Aucune correction sur cette page.")
    liens = []
    if resultat["decalage"]:
        liens.append(("Précédent", max(0, resultat["decalage"] - resultat["limite"])))
    if resultat["suivant"] is not None:
        liens.append(("Suivant", resultat["suivant"]))
    corps += '<nav aria-label="Pages de corrections">' + ' '.join(
        f'<a href="{pages.e(base)}?decalage={decalage}&amp;revision_max={resultat["revision_max"]}">{titre}</a>'
        for titre, decalage in liens) + '</nav>'
    return corps


def contenu_memoire_contact(lead_id: str, resultat: Mapping[str, Any], prefixe: str) -> str:
    base = f"{prefixe}/crm/lead/{pages._segment(lead_id)}/contact/memoire"
    libelles = {"NON_PUBLIE": "Publication absente", "EN_ATTENTE": "En attente de M10",
                "MEMORISE": "Présent dans M10", "CONFLIT": "Écart à examiner",
                "ECHEC_LIVRAISON": "Échec de livraison", "QUARANTAINE": "En quarantaine"}
    corps = (f'<h1>Transmission des corrections à M10</h1><p>{_lien_dossier(lead_id, prefixe)}</p>'
             '<p>Lecture seule de M2, du bus et de M10. Aucune reprise ni réparation automatique. '
             'Les projets liés après une correction sont exclus de cette correction.</p>'
             f'<p>{resultat["total_corrections"]} corrections ; {resultat["total_references"]} références par projet. '
             f'Jusqu’à la révision {resultat["revision_max"]}. '
             f'<a href="{pages.e(base)}">Actualiser le diagnostic</a></p>')
    for ref in resultat["references"]:
        corps += (f'<section class="carte"><h2>Révision {pages.e(ref["revision"])} — {pages.e(ref["lead_id"])}</h2>'
                  f'<p>{pages.e(libelles[ref["etat"]])}</p>'
                  f'<p>Référence : {pages.e(ref["fait_id"])}</p>'
                  f'<p>Source M2 : {pages.e(ref["source_ligne_id"])}</p></section>')
    if not resultat["references"]:
        corps += pages._vide("Aucune référence sur cette page.")
    if resultat["suivant"] is not None:
        corps += (f'<a href="{pages.e(base)}?decalage={resultat["suivant"]}'
                  f'&amp;revision_max={resultat["revision_max"]}">Suivant</a>')
    return corps


def formulaire_contact(lead_id: str, vue: Mapping[str, Any], csrf: str, prefixe: str) -> str:
    contact = vue.get("contact") or {}
    champs = "".join(f'<label>{pages.e(c.title())}<input name="{c}" maxlength="254" '
                     f'value="{pages.e(contact.get(c, ""))}"></label>' for c in ("nom", "courriel", "telephone"))
    return (
        '<section class="carte"><h2>Corriger les coordonnées</h2>'
        '<p>Cette correction concerne tous les projets de ce client. Les documents émis restent inchangés. '
        'Elle ne vaut pas consentement à contacter une nouvelle adresse.</p>'
        f'<form method="post" action="{pages.e(prefixe)}/crm/lead/{pages._segment(lead_id)}/contact" class="pile">'
        f'<input type="hidden" name="csrf" value="{pages.e(csrf)}">'
        f'<input type="hidden" name="mutation_id" value="{uuid.uuid4().hex}">'
        f'<input type="hidden" name="revision_attendue" value="{vue.get("revision_contact", 0)}">'
        + champs + '<label>Motif de correction<input name="motif" maxlength="300" required></label>'
        '<button type="submit">Enregistrer la correction</button></form></section>'
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
    "REJ-DEVIS-INTROUVABLE": 404,
    "REJ-CONVERSATION-CLOSE": 409,
    "REJ-CHAMP-VIDE": 400,
    "REJ-CONTRAT-INVALIDE": 400,
    "REJ-CONTACT-CONFLIT": 409,
    "REJ-LEAD-INCONNU": 404,
    "REJ-HUMAIN-REQUIS": 403,
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
        if code == "REJ-CONTACT-CONFLIT":
            detail = ("Correction non enregistrée : relire les coordonnées et leur révision. "
                      "Si elles sont inchangées ou déjà rattachées à un autre client, vérifier le dossier.")
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
        if set(parametres) - {"statut", "decalage", "q"}:
            raise HTTPException(400, "requête invalide")
        recherche = parametres.get("q", "")
        if len(recherche) > 120:
            raise HTTPException(400, "recherche limitée à 120 caractères")
        recherche = recherche.strip()
        statut = parametres.get("statut", "")
        if statut and statut not in STATUTS:
            raise HTTPException(400, "requête invalide")
        brut = parametres.get("decalage", "0")
        if len(brut) > len(str(DECALAGE_MAX)) or not brut.isascii() or not brut.isdigit() or int(brut) > DECALAGE_MAX:
            raise HTTPException(400, "requête invalide")
        arguments: dict[str, Any] = {"decalage": int(brut), "limite": LIMITE_PAGE}
        if statut:
            arguments["statut"] = statut
        if recherche:
            arguments["recherche"] = recherche
        page = lire(session, "m2_lister_leads", arguments)
        return rendre(session, "Répertoire CRM",
                      contenu_repertoire(page, statut=statut, prefixe=prefixe, recherche=recherche))

    @router.get("/crm/cedule", response_class=HTMLResponse)
    def cedule_semaine(request: Request) -> Response:
        session = session_page(request)
        params = request.query_params
        autorises = {"debut_semaine", "offset_interventions", "offset_sans_date", "source_attendue"}
        if set(params) - autorises or any(len(params.getlist(k)) > 1 for k in params):
            raise HTTPException(400, "requête invalide")
        brut = params.get("debut_semaine")
        if brut is None:
            aujourd_hui = datetime.now(ZoneInfo(FUSEAU)).date()
            brut = (aujourd_hui - timedelta(days=aujourd_hui.weekday())).isoformat()
        try:
            cedule_ui.lundi(brut)
            arguments = cedule_ui.arguments_page(params, brut)
        except ValueError:
            raise HTTPException(400, "Lundi, pages ou référence de source invalides.") from None
        try:
            vue = annotations_cedule_ui.appeler(cnx_factory, deps, session,
                                                "m4_lire_page_cedule_semaine", arguments)
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            corps = ('<section class="carte"><h2>La cédule a changé</h2>'
                     '<p>Les pages précédentes ne sont plus cohérentes avec la source actuelle.</p>'
                     f'<a href="{pages.e(prefixe)}/crm/cedule?debut_semaine={brut}">'
                     'Recommencer la lecture</a></section>')
            reponse = rendre(session, "Cédule modifiée", corps)
            reponse.status_code = 409
            return reponse
        if (vue.get("taille_page") != 25
                or any(vue.get(k) != arguments[k] for k in ("offset_interventions", "offset_sans_date"))
                or (arguments["source_attendue"] and vue.get("source_tete") != arguments["source_attendue"])):
            raise HTTPException(503, "Pagination M4 indisponible")
        if vue.get("debut_semaine") != brut or not isinstance(vue.get("interventions"), list):
            raise HTTPException(503, "Cédule M4 indisponible")
        # Valider la projection AVANT toute résolution de dossiers (borne de 25 créneaux incluse).
        try:
            cedule_ui.contenu(vue, set(), prefixe)
            leads = {ligne["lead_id"] for ligne in vue["interventions"]}
            if any(not isinstance(lead, str) for lead in leads):
                raise ValueError("lead M4 illisible")
        except (ValueError, KeyError, TypeError, AttributeError):
            raise HTTPException(503, "Cédule M4 indisponible") from None
        # Liens seulement vers les dossiers réellement reconnus par M2. Une absence n'est pas une panne.
        dossiers = set()
        for lead in sorted(leads):
            if not isinstance(lead, str) or _IDENTIFIANT.fullmatch(lead) is None:
                continue
            try:
                lien = lire(session, "m2_trouver_client_de_lead", {"lead_id": lead})
            except HTTPException as exc:
                if exc.status_code == 404:
                    continue
                raise
            if lien.get("lead_id") != lead or not lien.get("client_id"):
                raise HTTPException(503, "Lien CRM indisponible")
            dossiers.add(lead)
        annotations_cedule_ui.badges(cnx_factory, deps, session, vue)
        couleurs_cedule_ui.badges(cnx_factory, deps, session, vue)
        try:
            corps = cedule_ui.contenu(vue, dossiers, prefixe)
        except (ValueError, KeyError, TypeError):
            raise HTTPException(503, "Cédule M4 indisponible") from None
        return rendre(session, "Cédule hebdomadaire", corps)

    @router.get("/crm/cedule/plan/{plan_id}", response_class=HTMLResponse)
    def dates_plan(plan_id: str, request: Request) -> Response:
        session = session_page(request)
        if cedule_plan_ui.PLAN_ID.fullmatch(plan_id) is None:
            raise HTTPException(404, "plan introuvable")
        if request.query_params:
            raise HTTPException(400, "requête invalide")
        vue = lire(session, "m4_lire_calendrier_plan", {"plan_id": plan_id})
        with cnx_factory() as cnx:
            sqlite = cnx.dialect.name == "sqlite"
        try:
            corps = cedule_plan_ui.contenu(vue, plan_id, session.csrf, prefixe, sqlite)
        except (ValueError, KeyError, TypeError):
            raise HTTPException(503, "Détail M4 indisponible") from None
        return rendre(session, "Dates du plan appliqué", corps)

    @router.post("/crm/cedule/plan/{plan_id}")
    async def confirmer_dates_plan(plan_id: str, request: Request) -> Response:
        session = session_page(request)
        if cedule_plan_ui.PLAN_ID.fullmatch(plan_id) is None:
            raise HTTPException(404, "plan introuvable")
        if request.query_params:
            raise HTTPException(400, "requête invalide")
        champs = await cedule_plan_ui.formulaire(request)
        verifier_formulaire(champs, session)
        try:
            with cnx_factory() as cnx:
                if cnx.dialect.name != "sqlite":
                    raise HTTPException(503, "Modification des dates indisponible sur cette instance")
                vue = extraire_resultat(metier.executer(cnx, deps, session, "m4_lire_calendrier_plan",
                                                       {"plan_id": plan_id}))
                try:
                    permis = cedule_plan_ui.valider(vue, plan_id)
                except (ValueError, KeyError, TypeError):
                    raise HTTPException(503, "Détail M4 indisponible") from None
                if not permis:
                    raise HTTPException(409, "Plan bloqué ou incomplet : relire avant de confirmer")
                arguments, mutation = cedule_plan_ui.arguments(champs, vue['jours'])
                reponse = metier.executer(cnx, deps, session, "m4_confirmer_dates_cedule",
                                         {"plan_id": plan_id, **arguments}, mutation_id=mutation)
                try:
                    extraire_resultat(reponse)
                except HTTPException as exc:
                    if exc.status_code == 400:
                        raise HTTPException(409, "Dates non enregistrées : relire le plan et sa révision") from None
                    raise
        except PermissionError:
            raise HTTPException(403, "accès refusé") from None
        except ValueError as exc:
            if isinstance(exc.__cause__, idempotence.MutationConflit):
                raise HTTPException(409, "identifiant de saisie déjà utilisé") from None
            raise HTTPException(400, "dates ou formulaire invalides") from None
        except KeyError:
            raise HTTPException(503, "Confirmation M4 indisponible") from None
        return RedirectResponse(f"{prefixe}/crm/cedule/plan/{pages._segment(plan_id)}", status_code=303)

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
        with cnx_factory() as cnx:
            correction_disponible = cnx.dialect.name == "sqlite"
        edition = (formulaire_contact(lead_id, vue, session.csrf, prefixe) if correction_disponible
                   else '<p class="note">Correction de coordonnées indisponible sur cette instance.</p>')
        try:
            rencontres = lire_rencontres(session, lead_id, {"decalage": 0, "source_attendue": ""})
        except HTTPException as exc:
            if exc.status_code != 503:
                raise
            rencontres = None
        return rendre(session, "Dossier client",
                      contenu_dossier(lead_id, client_id, vue, prefixe=prefixe)
                      + rencontres_ui.contenu(lead_id, rencontres, prefixe)
                      + f'<p><a href="{pages.e(_base_soumissions(lead_id, prefixe))}">'
                      + "Voir les soumissions de ce projet</a></p>"
                      + formulaire_note(lead_id, session.csrf, prefixe)
                      + edition
                      + f'<p><a href="{pages.e(prefixe)}/crm/lead/{pages._segment(lead_id)}/contact/historique">'
                      + 'Historique des coordonnées</a></p>')

    @router.get("/crm/lead/{lead_id}/contact/historique", response_class=HTMLResponse)
    @router.get("/crm/lead/{lead_id}/contact/memoire", response_class=HTMLResponse)
    def historique_contact(lead_id: str, request: Request) -> Response:
        session = session_page(request)
        if _IDENTIFIANT.fullmatch(lead_id) is None:
            raise HTTPException(404, "dossier introuvable")
        parametres = request.query_params
        if set(parametres) - {"decalage", "revision_max"}:
            raise HTTPException(400, "requête invalide")
        arguments: dict[str, Any] = {"limite": LIMITE_PAGE}
        for cle, plafond in [("decalage", DECALAGE_MAX), ("revision_max", 1_000_001)]:
            if cle not in parametres:
                continue
            brut = parametres[cle]
            if len(brut) > 7 or not brut.isascii() or not brut.isdigit() or int(brut) > plafond:
                raise HTTPException(400, "pagination invalide")
            arguments[cle] = int(brut)
        lien = lire(session, "m2_trouver_client_de_lead", {"lead_id": lead_id})
        if request.url.path.endswith("/contact/memoire"):
            resultat = lire(session, "m2_reconcilier_memoire_contact_client",
                            {**arguments, "client_id": lien["client_id"]})
            corps = contenu_memoire_contact(lead_id, resultat, prefixe)
            return rendre(session, "Transmission des corrections à M10", corps)
        resultat = lire(session, "m2_lister_historique_contact_client", {**arguments, "client_id": lien["client_id"]})
        return rendre(session, "Historique des coordonnées", contenu_historique_contact(lead_id, resultat, prefixe))

    def verifier_lead(session: Session, lead_id: str) -> None:
        if _IDENTIFIANT.fullmatch(lead_id) is None:
            raise HTTPException(404, "dossier introuvable")
        lire(session, "m2_trouver_client_de_lead", {"lead_id": lead_id})

    def lire_rencontres(session, lead_id, arguments):
        try:
            with cnx_factory() as cnx:
                reponse = metier.executer(cnx, deps, session, "m2_lire_rencontres_lead",
                                         {"lead_id": lead_id, **arguments})
            return agenda_ui.extraire(reponse)
        except PermissionError:
            raise HTTPException(403, "Accès admin requis") from None
        except KeyError:
            raise HTTPException(503, "Rencontres indisponibles") from None
        except ValueError:
            raise HTTPException(400, "Pagination invalide") from None

    @router.get("/crm/lead/{lead_id}/rencontres", response_class=HTMLResponse)
    def rencontres_projet(lead_id: str, request: Request) -> Response:
        session = session_page(request)
        verifier_lead(session, lead_id)
        arguments = rencontres_ui.parametres(request.query_params)
        try:
            resultat = lire_rencontres(session, lead_id, arguments)
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            reponse = rendre(session, "Rencontres à relire",
                             '<p role="alert">Les sources M2 ont changé. Recommencer la lecture pour éviter '
                             'de manquer ou de compter deux fois une rencontre.</p>'
                             f'<a href="{pages.e(rencontres_ui.base_url(prefixe, lead_id))}">Recommencer</a>')
            reponse.status_code = 409
            return reponse
        return rendre(session, "Rencontres du projet", rencontres_ui.contenu(lead_id, resultat, prefixe))

    @router.get("/crm/lead/{lead_id}/soumissions", response_class=HTMLResponse)
    def soumissions(lead_id: str, request: Request) -> Response:
        session = session_page(request)
        verifier_lead(session, lead_id)
        params = request.query_params
        brut = params.get("decalage", "0")
        if (set(params) - {"decalage"} or len(brut) > len(str(DECALAGE_MAX))
                or not brut.isascii() or not brut.isdigit() or int(brut) > DECALAGE_MAX):
            raise HTTPException(400, "pagination invalide")
        decalage = int(brut)
        page = lire(session, "m3_lister_devis_lead_admin", {
            "lead_id": lead_id, "limite": LIMITE_PAGE, "decalage": decalage,
        })
        return rendre(session, "Soumissions du projet",
                      contenu_soumissions(lead_id, page, prefixe=prefixe, decalage=decalage))

    @router.get("/crm/lead/{lead_id}/soumissions/{devis_id}", response_class=HTMLResponse)
    def soumission(lead_id: str, devis_id: str, request: Request) -> Response:
        session = session_page(request)
        verifier_lead(session, lead_id)
        if _IDENTIFIANT.fullmatch(devis_id) is None or request.query_params:
            raise HTTPException(404, "soumission introuvable")
        devis = lire(session, "m3_lire_devis", {"devis_id": devis_id})
        if devis.get("lead_id") != lead_id:
            raise HTTPException(404, "soumission introuvable")
        return rendre(session, "Soumission", contenu_soumission(lead_id, devis, prefixe=prefixe))

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

    def corriger_contact(session: Session, lead_id: str, champs: Mapping[str, Any]) -> dict:
        if _IDENTIFIANT.fullmatch(lead_id) is None:
            raise HTTPException(404, "dossier introuvable")
        if not isinstance(champs, Mapping) or set(champs) != {"contact", "revision_attendue", "motif", "mutation_id"}:
            raise HTTPException(400, "champs de correction invalides")
        if type(champs["revision_attendue"]) is not int:
            raise HTTPException(400, "révision entière requise")
        try:
            with cnx_factory() as cnx:
                lien = extraire_resultat(metier.executer(cnx, deps, session, "m2_trouver_client_de_lead",
                                                        {"lead_id": lead_id}))
                arguments = {k: v for k, v in champs.items() if k != "mutation_id"}
                reponse = metier.executer(cnx, deps, session, "m2_corriger_contact_client",
                                         {**arguments, "client_id": lien["client_id"]},
                                         mutation_id=champs["mutation_id"])
                resultat = extraire_resultat(reponse)
        except PermissionError:
            raise HTTPException(403, "accès refusé") from None
        except KeyError:
            raise HTTPException(503, "correction indisponible") from None
        except ValueError as exc:
            if isinstance(exc.__cause__, idempotence.MutationConflit):
                raise HTTPException(409, "identifiant de saisie déjà utilisé") from None
            raise HTTPException(400, "correction invalide") from None
        return {"ok": True, "resultat": resultat, "rejoue": reponse.get("rejoue") is True}

    @router.post("/api/crm/lead/{lead_id}/contact")
    async def contact_api(lead_id: str, request: Request) -> Response:
        session = ecriture_api(request)
        return JSONResponse(corriger_contact(session, lead_id, await objet_json(request)))

    @router.post("/crm/lead/{lead_id}/contact")
    async def contact_formulaire(lead_id: str, request: Request) -> Response:
        session = session_page(request)
        champs = await formulaire(request)
        verifier_formulaire(champs, session)
        if set(champs) != {"csrf", "nom", "courriel", "telephone", "revision_attendue", "motif", "mutation_id"}:
            raise HTTPException(400, "champs de correction invalides")
        version = champs["revision_attendue"]
        if not isinstance(version, str) or not version.isascii() or not version.isdigit() or len(version) > 7:
            raise HTTPException(400, "révision invalide")
        corriger_contact(session, lead_id, {"contact": {k: champs[k] for k in ("nom", "courriel", "telephone")
                                                     if champs[k]},
                        "revision_attendue": int(version), "motif": champs["motif"],
                        "mutation_id": champs["mutation_id"]})
        return RedirectResponse(f"{prefixe}/crm/lead/{pages._segment(lead_id)}", status_code=303)

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

    from . import preparation_chantier

    router.include_router(preparation_chantier.creer_router(
        session_page=session_page, cnx_factory=cnx_factory, deps=deps, prefixe=prefixe, rendre=rendre))
    router.include_router(devis_modele_ui.creer_router(
        session_page=session_page, cnx_factory=cnx_factory, deps=deps, prefixe=prefixe,
        verifier_formulaire=verifier_formulaire, verifier_lead=verifier_lead, rendre=rendre))
    router.include_router(catalogue_materiaux_ui.creer_router(
        session_page=session_page, cnx_factory=cnx_factory, deps=deps, prefixe=prefixe,
        verifier_formulaire=verifier_formulaire, rendre=rendre))
    router.include_router(modeles_soumission_ui.creer_router(
        session_page=session_page, cnx_factory=cnx_factory, deps=deps, prefixe=prefixe,
        verifier_formulaire=verifier_formulaire, rendre=rendre))

    router.include_router(agenda_ui.creer_router(
        session_page=session_page, cnx_factory=cnx_factory, deps=deps, prefixe=prefixe,
        verifier_formulaire=verifier_formulaire, rendre=rendre))
    router.include_router(annotations_cedule_ui.creer_router(
        session_page=session_page, cnx_factory=cnx_factory, deps=deps, prefixe=prefixe,
        verifier_formulaire=verifier_formulaire, rendre=rendre))

    router.include_router(mois_cedule_ui.creer_router(
        session_page=session_page, cnx_factory=cnx_factory, deps=deps, prefixe=prefixe, rendre=rendre))

    router.include_router(couleurs_cedule_ui.creer_router(
        session_page=session_page, cnx_factory=cnx_factory, deps=deps, prefixe=prefixe,
        verifier_formulaire=verifier_formulaire, rendre=rendre))

    router.include_router(notes_commande_ui.creer_router(
        session_page=session_page, cnx_factory=cnx_factory, deps=deps, prefixe=prefixe,
        verifier_formulaire=verifier_formulaire, lire=lire, rendre=rendre, verifier_lead=verifier_lead))

    return router
