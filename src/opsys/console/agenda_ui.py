"""Agenda commercial interne M2, console admin; aucun connecteur ou droit vendeur implicite."""
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs, urlencode
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse

from .. import identite
from . import metier, pages

FUSEAU = 'America/Montreal'
IDENTIFIANT = re.compile(r'[A-Za-z0-9_.:@-]{1,200}')
CHAMPS = {'rendez_vous_id', 'lead_id', 'vendeur_id', 'debut', 'fin', 'titre', 'statut', 'revision_attendue'}


def extraire(reponse):
    r = reponse.get('resultat') if isinstance(reponse, dict) and reponse.get('ok') is True else None
    if not isinstance(r, dict):
        raise HTTPException(503, 'Agenda temporairement indisponible')
    if r.get('accepte') is True and isinstance(r.get('resultat'), dict):
        return r['resultat']
    code = r.get('verdict', {}).get('code', '').removeprefix('REJ-AGENDA-')
    codes = {'IDENTITE': 403, 'ARGUMENTS': 400, 'HORODATAGE-INVALIDE': 400,
             'REVISION-PERIMEE': 409, 'MUTATION-CONFLIT': 409, 'CONFLIT-HORAIRE': 409,
             'PROPRIETAIRE-MODIFIE': 409, 'VENDEUR-INACTIF': 409, 'VENDEUR-INCONNU': 404,
             'RENDEZ-VOUS-INCONNU': 404}
    messages = {'CONFLIT-HORAIRE': 'Un autre rendez-vous occupe ce créneau : choisir une autre heure.',
                'PROPRIETAIRE-MODIFIE': 'Le lead ne correspond plus au vendeur : relire son assignation.',
                'REVISION-PERIMEE': 'Le rendez-vous a changé : relire avant de modifier.',
                'MUTATION-CONFLIT': 'Cette intention a déjà servi à une autre saisie.',
                'ARGUMENTS': 'Saisie invalide : vérifier dates, fuseau, durée et références.',
                'SORTIE-TROP-VOLUMINEUSE': 'Trop de rendez-vous : choisir une période plus courte.'}
    raise HTTPException(codes.get(code, 503), messages.get(code, 'Agenda indisponible ou accès refusé'))


def periode(jour, vue):
    try:
        d = date.fromisoformat(jour)
        if d.isoformat() != jour or not 1900 <= d.year <= 2199:
            raise ValueError('date')
        if vue == 'jour':
            debut, fin = d, d + timedelta(days=1)
        elif vue == 'semaine':
            debut = d - timedelta(days=d.weekday())
            fin = debut + timedelta(days=7)
        elif vue == 'mois':
            debut = d.replace(day=1)
            fin = (debut.replace(day=28) + timedelta(days=4)).replace(day=1)
        else:
            raise ValueError('vue')
        if debut.year < 1900 or fin > date(2200, 1, 1):
            raise ValueError('bornes')
        return debut, fin
    except (ValueError, TypeError, OverflowError):
        raise HTTPException(400, 'Période invalide') from None


def lien(prefixe, vendeur, jour, vue='semaine'):
    return prefixe + '/crm/agenda?' + urlencode({'vendeur_id': vendeur, 'jour': jour, 'vue': vue})


def _formulaire(session, prefixe, vendeur, rdv=None):
    r = rdv or {'rendez_vous_id': str(uuid.uuid4()), 'lead_id': '', 'vendeur_id': vendeur,
                'debut': '', 'fin': '', 'titre': '', 'statut': 'actif', 'revision': 0}
    texte = (f'<form method="post" action="{pages.e(prefixe)}/crm/agenda/enregistrer" class="pile">'
             f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
             f'<input type="hidden" name="mutation_id" value="{uuid.uuid4()}">'
             f'<input type="hidden" name="revision_attendue" value="{r["revision"]}">')
    for k in ('rendez_vous_id', 'vendeur_id'):
        texte += f'<input type="hidden" name="{k}" value="{pages.e(r[k])}">'
    for k, label, taille in [('lead_id', 'Référence du lead attribué à ce vendeur', 200),
                             ('titre', 'Objet du rendez-vous', 200),
                             ('debut', 'Début, heure de Montréal avec décalage UTC', 32),
                             ('fin', 'Fin, heure de Montréal avec décalage UTC', 32)]:
        readonly = ' readonly' if rdv and k == 'lead_id' else ''
        texte += (f'<label>{label}<input name="{k}" maxlength="{taille}" value="{pages.e(r[k])}" '
                  f'required{readonly}></label>')
    texte += ('<p>Format : AAAA-MM-JJTHH:MM-04:00 en heure avancée, -05:00 en heure normale. '
              'Le décalage doit correspondre à Montréal à cette date. Durée maximale : 12 heures.</p>'
              '<label>État<select name="statut"><option value="actif">Planifié en interne</option>')
    if rdv:
        texte += '<option value="annule">Annuler (historique conservé)</option>'
    texte += '</select></label><button type="submit">Enregistrer</button></form>'
    return texte


async def _champs(request):
    if request.headers.get('content-type', '').split(';')[0] != 'application/x-www-form-urlencoded':
        raise HTTPException(415, 'Formulaire requis')
    corps = bytearray()
    async for bloc in request.stream():
        corps.extend(bloc)
        if len(corps) > 16000:
            raise HTTPException(413, 'Formulaire trop volumineux')
    try:
        p = parse_qs(corps.decode('utf-8'), keep_blank_values=True, strict_parsing=True,
                     max_num_fields=10, errors='strict')
        if set(p) != CHAMPS | {'csrf', 'mutation_id'} or any(len(v) != 1 for v in p.values()):
            raise ValueError('champs')
        return {k: v[0] for k, v in p.items()}
    except (ValueError, UnicodeError):
        raise HTTPException(400, 'Formulaire invalide') from None


def creer_router(*, session_page, cnx_factory, deps, prefixe, verifier_formulaire, rendre):
    router = APIRouter()

    def admin(request):
        session = session_page(request)
        with cnx_factory() as cnx:
            personne = identite.personne_active(cnx, session.utilisateur)
            if (personne is None or 'admin' not in personne.roles
                    or session.expire <= datetime.now(UTC).timestamp()):
                raise HTTPException(403, 'Accès admin requis')
        return session

    def agir(session, nom, args, mutation=None):
        try:
            with cnx_factory() as cnx:
                return extraire(metier.executer(cnx, deps, session, nom, args, mutation_id=mutation))
        except PermissionError:
            raise HTTPException(403, 'Accès refusé') from None
        except KeyError:
            raise HTTPException(503, 'Agenda indisponible') from None
        except ValueError:
            raise HTTPException(400, 'Saisie invalide') from None

    def ecriture():
        with cnx_factory() as cnx:
            return cnx.dialect.name == 'sqlite'

    @router.get('/crm/agenda')
    def agenda(request: Request):
        session = admin(request)
        p = request.query_params
        if set(p) - {'vendeur_id', 'jour', 'vue'} or any(len(p.getlist(k)) != 1 for k in p):
            raise HTTPException(400, 'Paramètres invalides')
        vendeur = p.get('vendeur_id', '')
        jour = p.get('jour', datetime.now(ZoneInfo(FUSEAU)).date().isoformat())
        vue = p.get('vue', 'semaine')
        debut, fin = periode(jour, vue)
        if vendeur and not IDENTIFIANT.fullmatch(vendeur):
            raise HTTPException(400, 'Référence vendeur invalide')
        corps = ('<section class="carte"><h2>Agenda des vendeurs</h2>'
                 '<p>Rendez-vous commerciaux internes · America/Montreal. '
                 'La confirmation client et la synchronisation Google ne sont pas actives.</p>'
                 f'<form method="get" action="{pages.e(prefixe)}/crm/agenda" class="pile">'
                 f'<label>Identifiant du vendeur<input name="vendeur_id" value="{pages.e(vendeur)}" '
                 'maxlength="200" required></label>'
                 f'<label>Date<input type="date" name="jour" value="{pages.e(jour)}" required></label>'
                 '<label>Vue<select name="vue">')
        for cle, label in [('jour', 'Jour'), ('semaine', 'Semaine'), ('mois', 'Mois')]:
            choisi = ' selected' if cle == vue else ''
            corps += f'<option value="{cle}"{choisi}>{label}</option>'
        corps += '</select></label><button>Afficher</button></form></section>'
        if not vendeur:
            return rendre(session, 'Agenda commercial', corps)
        r = agir(session, 'm2_lire_agenda_vendeur', {'vendeur_id': vendeur, 'debut_periode': debut.isoformat(),
                                                   'fin_periode': fin.isoformat()})
        if (r.get('vendeur_id') != vendeur or r.get('debut_periode') != debut.isoformat()
                or r.get('fin_periode') != fin.isoformat() or r.get('fuseau') != FUSEAU
                or not isinstance(r.get('rendez_vous'), list)):
            raise HTTPException(503, 'Réponse agenda incohérente')
        corps += f'<h3>{pages.e(vendeur)} · {pages.e(debut)} au {pages.e(fin - timedelta(days=1))}</h3>'
        for label, d in [('Précédent', debut - timedelta(days=1)), ('Suivant', fin)]:
            try:
                periode(d.isoformat(), vue)
            except HTTPException:
                continue
            corps += f'<a href="{pages.e(lien(prefixe, vendeur, d.isoformat(), vue))}">{label}</a> '
        corps += '<div class="grille">'
        for n in range((fin - debut).days):
            d = debut + timedelta(days=n)
            corps += f'<section class="carte"><h4>{d.isoformat()}</h4>'
            for item in r['rendez_vous']:
                # Les instants fournis par M2 sont déjà validés en heure civile Montréal.
                a = datetime.fromisoformat(item['debut']).astimezone(ZoneInfo(FUSEAU))
                b = datetime.fromisoformat(item['fin']).astimezone(ZoneInfo(FUSEAU))
                if not (a.date() <= d <= (b - timedelta(microseconds=1)).date()):
                    continue
                chemin = prefixe + '/crm/agenda/rendez-vous/' + pages._segment(item['rendez_vous_id'])
                corps += (f'<article><a href="{pages.e(chemin)}">{pages.e(item["titre"])}</a>'
                          f'<p>{pages.e(item["debut"])} → {pages.e(item["fin"])}</p>'
                          f'<p>{pages.e(item["statut"])} · Lead {pages.e(item["lead_id"])}</p>')
                if not item['propriete_courante']:
                    corps += '<p>Assignation modifiée : rendez-vous à revoir.</p>'
                corps += '</article>'
            corps += '</section>'
        corps += '</div>'
        if not r['rendez_vous']:
            corps += '<p>Aucun rendez-vous enregistré sur cette période.</p>'
        corps += f'<p>Source agenda : {pages.e(r["source_tete"] or "registre vide")}</p>'
        if ecriture():
            corps += '<section class="carte"><h3>Nouveau rendez-vous</h3>' + _formulaire(session, prefixe, vendeur)
            corps += '</section>'
        else:
            corps += '<p>Lecture seule : écriture non qualifiée sur ce backend.</p>'
        return rendre(session, 'Agenda commercial', corps)

    @router.post('/crm/agenda/enregistrer')
    async def enregistrer(request: Request):
        session = admin(request)
        champs = await _champs(request)
        verifier_formulaire(champs, session)
        if not re.fullmatch(r'0|[1-9][0-9]{0,4}', champs['revision_attendue']):
            raise HTTPException(400, 'Révision invalide')
        args = {k: champs[k] for k in CHAMPS}
        args['revision_attendue'] = int(args['revision_attendue'])
        r = agir(session, 'm2_enregistrer_rendez_vous', args, champs['mutation_id'])
        return RedirectResponse(prefixe + '/crm/agenda/rendez-vous/' + pages._segment(r['rendez_vous_id']), 303)

    @router.get('/crm/agenda/rendez-vous/{rendez_vous_id}')
    def detail(request: Request, rendez_vous_id: str):
        session = admin(request)
        if request.query_params or not IDENTIFIANT.fullmatch(rendez_vous_id):
            raise HTTPException(400, 'Référence invalide')
        r = agir(session, 'm2_historique_rendez_vous', {'rendez_vous_id': rendez_vous_id})
        if not r.get('revisions') or r.get('rendez_vous_id') != rendez_vous_id:
            raise HTTPException(404, 'Rendez-vous introuvable')
        courant = r['revisions'][-1]
        corps = (f'<section class="carte"><h2>{pages.e(courant["titre"])}</h2>'
                 '<p>Rendez-vous commercial interne. Aucune notification client envoyée.</p>'
                 f'<p><a href="{pages.e(lien(prefixe, courant["vendeur_id"], courant["debut"][:10]))}">'
                 'Retour à l’agenda</a></p>')
        if not courant['propriete_courante']:
            corps += '<p>Assignation modifiée : rendez-vous à revoir. Annuler pour libérer ce créneau.</p>'
        if courant['statut'] == 'actif' and ecriture():
            corps += _formulaire(session, prefixe, courant['vendeur_id'], courant)
        corps += '<h3>Historique</h3>'
        for item in reversed(r['revisions']):
            corps += (f'<article><h4>Révision {item["revision"]} · {pages.e(item["statut"])}</h4>'
                      f'<p>{pages.e(item["titre"])} · {pages.e(item["debut"])} → {pages.e(item["fin"])}</p>'
                      f'<p>Lead {pages.e(item["lead_id"])} · Vendeur {pages.e(item["vendeur_id"])}</p>'
                      f'<p>{pages.e(item["auteur"]["personne"])} · {pages.e(item["horodatage"])}</p>'
                      f'<p>Source : {pages.e(item["source_id"])}</p></article>')
        return rendre(session, 'Rendez-vous', corps + '</section>')

    return router
