"""Grille hebdomadaire du secrétariat : projection des seuls créneaux datés M4.

Aucune mutation, aucun calendrier externe, aucune disponibilité déduite d'une cellule vide.
"""
import re
from collections.abc import Mapping
from datetime import date, datetime, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from . import annotations_cedule_ui, couleurs_cedule_ui, pages

FUSEAU = "America/Montreal"
JOURS = ("Lundi", "Mardi", "Mercredi", "Jeudi", "Vendredi", "Samedi", "Dimanche")
STATUTS = {"planifiee": "Planifié", "en_route": "En route", "sur_site": "Sur le chantier",
           "en_revue": "En revue", "reportee": "Reporté", "annulee": "Annulé",
           "completed_pending_review": "Terminé — en attente de revue", "completed_verified": "Terminé — vérifié"}


def lundi(valeur: str) -> date:
    if not isinstance(valeur, str) or len(valeur) != 10:
        raise ValueError("lundi ISO requis")
    jour = date.fromisoformat(valeur)
    if jour.isoformat() != valeur or jour.weekday() != 0 or not 1900 <= jour.year <= 2199:
        raise ValueError("lundi ISO entre 1900 et 2199 requis")
    return jour


def arguments_page(params, semaine):
    resultat = {"debut_semaine": semaine}
    for k in ("offset_interventions", "offset_sans_date"):
        brut = params.get(k, "0")
        if type(brut) is not str or re.fullmatch(r"0|[1-9][0-9]{0,4}", brut) is None:
            raise ValueError("page invalide")
        n = int(brut)
        if n > 10000 or n % 25:
            raise ValueError("page invalide")
        resultat[k] = n
    source = params.get("source_attendue")
    if source is not None and (type(source) is not str or re.fullmatch('[0-9a-f]{64}', source) is None):
        raise ValueError("source invalide")
    if (resultat['offset_interventions'] or resultat['offset_sans_date']) and not source:
        raise ValueError("source requise")
    # Une continuation doit conserver aussi sa semaine explicite.
    if source and 'debut_semaine' not in params:
        raise ValueError("semaine requise")
    resultat['source_attendue'] = source
    return resultat


def pagination(vue, prefixe):
    if 'taille_page' not in vue:
        return '', ''  # ancien contrat, conservé pour les consommateurs existants
    if type(vue['taille_page']) is not int or vue['taille_page'] != 25:
        raise ValueError("taille de page invalide")
    source = vue['source_tete']
    if source is not None and (type(source) is not str or re.fullmatch('[0-9a-f]{64}', source) is None):
        raise ValueError("source invalide")
    nombre = vue['source_nombre']
    if type(nombre) is not int or not 0 <= nombre <= 10000 or (source is None) != (nombre == 0):
        raise ValueError("source incohérente")
    liens_par_liste = []
    for cle, total, lignes, label in [
        ('offset_interventions', 'total_interventions', 'interventions', 'Créneaux'),
        ('offset_sans_date', 'total_sans_date', 'sans_date', 'Sans date'),
    ]:
        offset, n = vue[cle], vue[total]
        if (type(offset) is not int or offset < 0 or offset > 10000 or offset % 25
                or type(n) is not int or not 0 <= n <= 10000
                or (offset >= n and offset != 0)
                or len(vue[lignes]) != min(25, n-offset)
                or (source is None and n)):
            raise ValueError("pagination incohérente")
        liens = []
        for cible, titre in [(offset-25, 'Page précédente'), (offset+25, 'Page suivante')]:
            if 0 <= cible < n:
                args = {k: vue[k] for k in ('debut_semaine', 'offset_interventions', 'offset_sans_date')}
                args.update({cle: cible, 'source_attendue': source})
                url = prefixe+'/crm/cedule?'+urlencode(args)
                liens.append(f'<a href="{pages.e(url)}">{titre} — {label}</a>')
        compte = f'{offset+1}–{offset+len(vue[lignes])}' if n else '0'
        liens_par_liste.append(f'<p>{label} : {compte} sur {n}.</p>'
                               f'<nav aria-label="Pages {label}">'+" · ".join(liens)+'</nav>')
    return tuple(liens_par_liste)


def _navigation(jour: date, prefixe: str) -> str:
    base = pages.e(prefixe) + "/crm/cedule"
    liens = [f'<a href="{pages.e(prefixe)}/crm/cedule/mois?premier_mois={jour:%Y-%m}">Vue trois mois</a>']
    if jour > date(2199, 10, 1):
        liens = [f'<a href="{pages.e(prefixe)}/crm/cedule/mois?premier_mois=2199-10">Vue trois mois</a>']
    for decalage, label in [(-7, "Semaine précédente"), (7, "Semaine suivante")]:
        cible = jour + timedelta(days=decalage)
        if cible.year >= 1900 and (cible + timedelta(days=7)).year <= 2199:
            liens.append(f'<a href="{base}?debut_semaine={cible.isoformat()}">{label}</a>')
    liens.append(f'<a href="{base}">Semaine courante</a>')
    return ('<nav class="cedule-navigation" aria-label="Navigation des semaines">' + " · ".join(liens) + '</nav>'
            f'<form method="get" action="{base}" class="cedule-navigation">'
            '<label for="debut-semaine">Lundi de la semaine</label>'
            f'<input type="date" id="debut-semaine" name="debut_semaine" value="{jour.isoformat()}" required>'
            '<button type="submit">Afficher</button></form>')


def _instant(valeur):
    instant = datetime.fromisoformat(valeur)
    if instant.tzinfo is None:
        raise ValueError("créneau M4 sans fuseau")
    return instant.astimezone(ZoneInfo(FUSEAU))


def _lien_plan(plan_id, prefixe):
    return (f'<a href="{pages.e(prefixe)}/crm/cedule/plan/{pages._segment(plan_id)}">Voir les dates du plan</a>'
            if plan_id else 'Plan non appliqué')


def _carte(ligne, debut, fin, dossiers, prefixe):
    iid, lead = ligne["intervention_id"], ligne["lead_id"]
    if ligne["validite"] not in {"date_confirmee", "a_reconfirmer"}:
        raise ValueError("validité de créneau inconnue")
    perime = ligne["validite"] == "a_reconfirmer"
    classe = "cedule-perimee" if perime else "cedule-confirmee"
    qualite = "À reconfirmer — ancien créneau" if perime else "Date interne confirmée"
    dossier = (f'<a href="{pages.e(prefixe)}/crm/lead/{pages._segment(lead)}">Dossier {pages.e(lead)}</a>'
               if lead in dossiers else '<span class="note">Dossier M2 non relié</span>')
    annotation = ""
    if "annotation" in ligne:
        badge = ligne["annotation"]
        if any(type(badge.get(k)) is not int or badge[k] < 0 for k in ("total_ancre", "total_historique")):
            raise ValueError("compteurs d'annotations invalides")
        lien = annotations_cedule_ui.url(annotations_cedule_ui.ancre_de(ligne), prefixe)
        annotation = (f'<p><a href="{pages.e(lien)}" aria-label="Notes de ce créneau">'
                      f'{"●" if badge["total_ancre"] else "○"} Notes : {badge["total_ancre"]}'
                      f' · historique : {badge["total_historique"]}</a></p>')
    repere = ""
    if "couleur" in ligne:
        lien = couleurs_cedule_ui.url(annotations_cedule_ui.ancre_de(ligne), prefixe)
        repere = (f'<p>{couleurs_cedule_ui.marqueur(ligne["couleur"])}</p>'
                  f'<p><a href="{pages.e(lien)}" aria-label="Couleur de ce créneau">Changer le repère</a></p>')
    statut = STATUTS.get(ligne["statut"], ligne["statut"])
    return (
        f'<article class="cedule-job {classe}" data-intervention="{pages.e(iid)}">'
        f'<p><strong>{debut:%H:%M}–{fin:%H:%M}</strong></p><p>{pages.e(statut)}</p>'
        f'<p class="cedule-validite">{qualite}</p><p>{dossier}</p>'
        f'<p>{_lien_plan(ligne["plan_id"], prefixe)}</p>{repere}{annotation}'
        '<details><summary>Origine et confirmation</summary>'
        f'<p>Intervention : {pages.e(iid)}</p>'
        f'<p>Équipe actuelle : {pages.e(ligne["technicien_actuel"] or "Non assignée")}</p>'
        f'<p>Source M4 · Révision {pages.e(ligne["revision"])}</p>'
        f'<p>Confirmé le {pages.e(ligne["confirme_le"])}</p><p>Plan : {pages.e(ligne["plan_id"])}</p>'
        f'<p>Référence : {pages.e(ligne["source_ligne_id"])}</p>'
        f'<p>Application : {pages.e(ligne["source_application_id"])}</p></details></article>'
    )


def contenu(vue: Mapping, dossiers: set[str], prefixe: str) -> str:
    """Une réponse illisible ne devient pas une semaine vide : le routeur rend 503."""
    jour = lundi(vue["debut_semaine"])
    if vue["fuseau"] != FUSEAU:
        raise ValueError("fuseau M4 inattendu")
    lignes, sans_date = vue["interventions"], vue["sans_date"]
    if not isinstance(lignes, list) or not isinstance(sans_date, list):
        raise ValueError("projection M4 illisible")
    for cle, liste, borne in [("total_interventions", lignes, 200), ("total_sans_date", sans_date, 50)]:
        if type(vue[cle]) is not int or vue[cle] < len(liste) or len(liste) > borne:
            raise ValueError("total M4 incohérent")
    pages_datees, pages_sans_date = pagination(vue, prefixe)
    jours = [jour + timedelta(days=i) for i in range(7)]
    cellules = {}
    ids = set()
    for ligne in lignes:
        if ligne["intervention_id"] in ids:
            raise ValueError("intervention dupliquée")
        ids.add(ligne["intervention_id"])
        debut, fin = _instant(ligne["debut"]), _instant(ligne["fin"])
        if (debut >= fin or debut.date() not in jours
                or fin.date() not in {debut.date(), debut.date() + timedelta(days=1)}):
            raise ValueError("créneau hors contrat")
        if fin.date() != debut.date() and (fin.hour or fin.minute or fin.second):
            raise ValueError("visite multi-jour non qualifiée")
        equipe = ligne["equipe_id"]
        if not isinstance(equipe, str) or not equipe:
            raise ValueError("équipe manquante")
        cellules.setdefault(equipe, {}).setdefault(debut.date(), []).append(
            _carte(ligne, debut, fin, dossiers, prefixe))
    entete = ''.join(f'<th scope="col" data-jour="{j.isoformat()}">{nom}<br>{j:%d/%m}<br>'
                     f'<a href="{pages.e(prefixe)}/crm/journal-equipes?jour={j.isoformat()}">Journal</a></th>'
                     for nom, j in zip(JOURS, jours, strict=True))
    rangees = []
    vide = '<span class="vide">Aucun créneau daté affiché</span>'
    for equipe in sorted(cellules):
        cases = ''.join('<td>' + ''.join(cellules[equipe].get(j, [vide]))
                        + '</td>' for j in jours)
        rangees.append(f'<tr><th scope="row">{pages.e(equipe)}</th>{cases}</tr>')
    if not rangees:
        rangees.append('<tr><td colspan="8" class="vide">Aucun créneau daté dans cette semaine.</td></tr>')
    partiel = (vue["total_interventions"] > len(lignes) or vue["total_sans_date"] > len(sans_date))
    if type(vue["tronque"]) is not bool or vue["tronque"] != partiel:
        raise ValueError("troncature M4 incohérente")
    limite = ('<p class="message message-alerte">Vue incomplète : limites de lecture atteintes. '
              'Les éléments non affichés doivent être consultés avant toute planification.</p>' if partiel else '')
    if partiel and 'taille_page' in vue:
        limite = ('<p class="message message-alerte">Vue incomplète : cette page ne montre pas tout le carnet. '
                  'Utiliser les pages suivantes pour consulter les autres éléments.</p>')
    attente = ''.join(
        f'<li>Intervention {pages.e(ligne["intervention_id"])} · {pages.e(ligne["statut"])} · '
        f'{_lien_plan(ligne["plan_id"], prefixe)} · Aucune date civile confirmée</li>'
        for ligne in sans_date)
    carnet = f'<ul>{attente}</ul>' if attente else '<p>Aucune intervention non datée signalée par M4.</p>'
    return (
        '<section class="carte"><h2>Équipes × jours</h2>'
        f'<p>Semaine du {jour:%d/%m/%Y} au {jours[-1]:%d/%m/%Y} · {FUSEAU}</p>'
        f'<p><a href="{pages.e(prefixe)}/crm">Répertoire CRM</a></p>' + _navigation(jour, prefixe)
        + '<p class="note">Une cellule vide ne prouve aucune disponibilité. '
        'Seules les équipes portant un créneau dans cette vue sont affichées.</p>'
        '<p class="note">Légende : bleu — date interne confirmée ; orange — ancien créneau à reconfirmer. '
        'Cette bordure ne signifie pas que le client a confirmé ou que le chantier est prêt.</p>'
        '<p class="note">Repère administratif : sans repère, bleu, violet, vert, rose, ambre ou gris. '
        'Choisir sa couleur depuis la carte; ce repère reste indépendant du statut et de la bordure de validité.</p>'
        + limite + f'<p>{len(lignes)} créneau(x) affiché(s) sur {vue["total_interventions"]} pour cette semaine.</p>'
        + pages_datees + '<div class="table-defilante" role="region" aria-label="Cédule hebdomadaire" tabindex="0">'
        '<table class="cedule-semaine"><caption>Planification interne — source M4</caption>'
        f'<thead><tr><th scope="col">Équipe</th>{entete}</tr></thead><tbody>{"".join(rangees)}</tbody></table></div>'
        '<ul class="note">' + ''.join(f'<li>{pages.e(a)}</li>' for a in vue["avertissements"]) + '</ul></section>'
        '<section class="carte"><h2>Sans date — tout le carnet</h2>'
        f'<p>{len(sans_date)} affichée(s) sur {vue["total_sans_date"]}. '
        'Ces interventions ne sont rattachées à aucun jour par cette vue.</p>' + pages_sans_date + carnet
        + '</section>'
    )
