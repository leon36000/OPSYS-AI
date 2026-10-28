"""Détail et saisie explicite des dates M4; aucune seconde vérité de planning."""
import re
import uuid
from datetime import date
from urllib.parse import parse_qs

from fastapi import HTTPException, Request

from . import pages
from .cedule_ui import FUSEAU

PLAN_ID = re.compile(r"[0-9a-f]{64}")
BLOQUANTS = {
    'plan_remplace': 'Le plan a été remplacé pour une intervention.',
    'intervention_non_planifiee': 'Une intervention ne peut plus recevoir de dates dans ce plan.',
    'equipe_reassignee': 'Une équipe a changé : préparer un nouveau plan.',
}


def valider(vue, plan_id):
    """Une réponse partielle ou illisible ne devient jamais un formulaire permis."""
    if vue['plan_id'] != plan_id or vue['fuseau'] != FUSEAU:
        raise ValueError('source calendrier inattendue')
    if type(vue['revision']) is not int or vue['revision'] < 0:
        raise ValueError('révision invalide')
    jours, visites = vue['jours'], vue['visites']
    if (not isinstance(jours, list) or any(type(j) is not int or not 0 <= j <= 99999 for j in jours)
            or jours != sorted(set(jours)) or not isinstance(visites, list)):
        raise ValueError('jours ou visites invalides')
    for cle, lignes, borne in [('total_jours', jours, 31), ('total_visites', visites, 200)]:
        if type(vue[cle]) is not int or vue[cle] < len(lignes) or len(lignes) > borne:
            raise ValueError('projection hors borne')
    tronque = vue['total_jours'] > len(jours) or vue['total_visites'] > len(visites)
    if type(vue['tronque']) is not bool or vue['tronque'] != tronque:
        raise ValueError('troncature incohérente')
    if not isinstance(vue['bloquants'], list) or any(c not in BLOQUANTS for c in vue['bloquants']):
        raise ValueError('blocage inconnu')
    calendrier = vue['calendrier']
    if not isinstance(calendrier, dict) or set(calendrier) - {str(j) for j in jours}:
        raise ValueError('calendrier incohérent')
    if (vue['revision'] == 0 and calendrier) or (vue['revision'] > 0 and set(calendrier) != {str(j) for j in jours}):
        raise ValueError('dates absentes ou non sourcées')
    for valeur in calendrier.values():
        _date(valeur)
    for cle in ['source_application_id', 'source_proposition_id']:
        if not isinstance(vue[cle], str) or not vue[cle]:
            raise ValueError('source manquante')
    if vue['revision'] > 0 and not isinstance(vue['source_ligne_id'], str):
        raise ValueError('source de date manquante')
    for visite in visites:
        for cle in ['intervention_id', 'equipe_id']:
            if not isinstance(visite[cle], str) or not visite[cle]:
                raise ValueError('visite illisible')
        if type(visite['jour']) is not int or (not tronque and visite['jour'] not in jours):
            raise ValueError('jour illisible')
        if (any(type(visite[k]) is not int for k in ['debut_min', 'fin_min'])
                or not 0 <= visite['debut_min'] < visite['fin_min'] <= 1440):
            raise ValueError('horaires illisibles')
    return not tronque and not vue['bloquants'] and bool(jours) and bool(visites)


def _date(valeur):
    if not isinstance(valeur, str) or len(valeur) != 10:
        raise ValueError('date explicite requise')
    jour = date.fromisoformat(valeur)
    if jour.isoformat() != valeur or not 1900 <= jour.year <= 2199:
        raise ValueError('date hors limites')
    return valeur


async def formulaire(request: Request):
    """31 dates + csrf/révision/id/preuve, doublons refusés avant toute action."""
    if request.headers.get('content-type', '').split(';')[0] != 'application/x-www-form-urlencoded':
        raise HTTPException(415, 'formulaire requis')
    corps = bytearray()
    async for morceau in request.stream():
        corps.extend(morceau)
        if len(corps) > 8192:
            raise HTTPException(413, 'formulaire trop volumineux')
    try:
        champs = parse_qs(corps.decode('utf-8'), keep_blank_values=True, max_num_fields=35,
                          strict_parsing=True, errors='strict')
        if any(len(v) != 1 for v in champs.values()):
            raise ValueError('doublon')
    except (ValueError, UnicodeError):
        raise HTTPException(400, 'formulaire illisible ou dupliqué') from None
    return {k: v[0] for k, v in champs.items()}


def arguments(champs, jours):
    attendus = {'csrf', 'revision_attendue', 'mutation_id'} | {f'date_{j}' for j in jours}
    if set(champs) not in (attendus, attendus | {'empreinte_memoire_attendue'}):
        raise ValueError('champs inattendus')
    brut = champs['revision_attendue']
    if not re.fullmatch(r'0|[1-9][0-9]{0,8}', brut):
        raise ValueError('révision invalide')
    mutation = champs['mutation_id']
    if not mutation.strip() or len(mutation) > 200:
        raise ValueError('identifiant invalide')
    return {'revision_attendue': int(brut),
            'calendrier': {str(j): _date(champs[f'date_{j}']) for j in jours}}, mutation


def contenu(vue, plan_id, csrf, prefixe, sqlite=True, empreinte_memoire=None):
    permis = valider(vue, plan_id) and sqlite and empreinte_memoire is not None
    lignes = ''.join(
        f'<tr><td>{pages.e(v["intervention_id"])}</td><td>{pages.e(v["equipe_id"])}</td>'
        f'<td>{pages.e(v["jour"] + 1)}</td>'
        f'<td>{v["debut_min"] // 60:02d}:{v["debut_min"] % 60:02d}–'
        f'{v["fin_min"] // 60:02d}:{v["fin_min"] % 60:02d}</td>'
        f'<td>{pages.e(v["statut"])}</td></tr>' for v in vue['visites'])
    champs = ''.join(
        f'<label>Jour {j + 1} du plan<input name="date_{j}" type="date" '
        f'min="1900-01-01" max="2199-12-31" value="{pages.e(vue["calendrier"].get(str(j), ""))}" '
        f'{"required" if permis else "disabled"}></label>' for j in vue['jours'])
    alertes = ''.join(f'<p class="message message-alerte">{pages.e(BLOQUANTS[c])}</p>' for c in vue['bloquants'])
    if vue['tronque']:
        alertes += '<p class="message message-alerte">Détail incomplet : confirmation bloquée.</p>'
    if not sqlite:
        alertes += '<p class="note">Modification des dates indisponible sur cette instance.</p>'
    formulaire_html = champs
    if permis:
        formulaire_html = (
            f'<form method="post" action="{pages.e(prefixe)}/crm/cedule/plan/{pages._segment(plan_id)}" class="pile">'
            f'<input type="hidden" name="csrf" value="{pages.e(csrf)}">'
            f'<input type="hidden" name="revision_attendue" value="{vue["revision"]}">'
            f'<input type="hidden" name="mutation_id" value="{uuid.uuid4()}">'
            + f'<input type="hidden" name="empreinte_memoire_attendue" value="{pages.e(empreinte_memoire)}">'
            + champs + '<button type="submit">Confirmer les dates internes</button></form>')
    return (
        '<section class="carte"><h2>Dates du plan appliqué</h2>'
        f'<p><a href="{pages.e(prefixe)}/crm/cedule">Retour à la cédule</a></p>'
        '<p>Cette saisie ne vaut ni confirmation client ni envoi des équipes. '
        'Les dates absentes restent à renseigner explicitement.</p>'
        f'<p>Fuseau : {FUSEAU} · Révision {vue["revision"]}</p>' + alertes + formulaire_html
        + '<div class="table-defilante"><table><thead><tr><th>Intervention</th><th>Équipe</th>'
        '<th>Jour du plan</th><th>Heures prévues</th><th>État actuel</th></tr></thead><tbody>'
        + lignes + '</tbody></table></div>'
        f'<p>{len(vue["visites"])} visite(s) affichée(s) sur {vue["total_visites"]}.</p>'
        '<details><summary>Provenance M4</summary>'
        f'<p>Plan : {pages.e(plan_id)}</p><p>Proposition : {pages.e(vue["source_proposition_id"])}</p>'
        f'<p>Application : {pages.e(vue["source_application_id"])}</p>'
        f'<p>Dates : {pages.e(vue["source_ligne_id"] or "Aucune confirmation")}</p></details>'
        + ''.join(f'<p class="note">{pages.e(a)}</p>' for a in vue['avertissements']) + '</section>')
