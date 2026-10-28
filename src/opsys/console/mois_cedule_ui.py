"""Aperçu de trois mois, compté depuis un seul instantané M4, sans mutation."""
import calendar
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request

from . import annotations_cedule_ui as notes
from . import pages

MOIS = ('Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin', 'Juillet', 'Août',
        'Septembre', 'Octobre', 'Novembre', 'Décembre')
JOURS = ('Lu', 'Ma', 'Me', 'Je', 'Ve', 'Sa', 'Di')
FUSEAU = 'America/Montreal'


def premier(valeur):
    if type(valeur) is not str or re.fullmatch(r'[0-9]{4}-[0-9]{2}', valeur) is None:
        raise ValueError('mois ISO requis')
    jour = date.fromisoformat(valeur+'-01')
    if not date(1900, 1, 1) <= jour <= date(2199, 10, 1):
        raise ValueError('trois mois complets entre 1900 et 2199 requis')
    return jour


def decaler(jour, n):
    valeur = jour.year*12+jour.month-1+n
    return date(valeur//12, valeur % 12+1, 1)


def _compteurs(objet):
    for k in ('total', 'date_confirmee', 'a_reconfirmer'):
        if type(objet[k]) is not int or not 0 <= objet[k] <= 10000:
            raise ValueError('compteur invalide')
    if objet['total'] != objet['date_confirmee']+objet['a_reconfirmer']:
        raise ValueError('compteurs incohérents')


def contenu(vue, prefixe):
    debut = premier(vue['premier_mois'])
    if vue['fuseau'] != FUSEAU or type(vue['mois']) is not list or len(vue['mois']) != 3:
        raise ValueError('aperçu invalide')
    for k in ('source_nombre', 'total_sans_date', 'total_interventions'):
        if type(vue[k]) is not int or not 0 <= vue[k] <= 10000:
            raise ValueError('compteur invalide')
    if vue['source_nombre'] == 0:
        if vue['source_tete'] is not None or vue['total_sans_date'] or vue['total_interventions']:
            raise ValueError('registre vide incohérent')
    elif type(vue['source_tete']) is not str or re.fullmatch('[0-9a-f]{64}', vue['source_tete']) is None:
        raise ValueError('source invalide')
    if (type(vue['avertissements']) is not list or len(vue['avertissements']) > 10
            or any(type(x) is not str or len(x) > 500 for x in vue['avertissements'])):
        raise ValueError('avertissements invalides')
    tableaux, total = [], 0
    for rang, mois in enumerate(vue['mois']):
        d = decaler(debut, rang)
        code = d.strftime('%Y-%m')
        _compteurs(mois)
        if mois['mois'] != code or type(mois['jours']) is not list:
            raise ValueError('mois inattendu')
        attendus = [date(d.year, d.month, n).isoformat() for n in range(1, calendar.monthrange(d.year, d.month)[1]+1)]
        if [x['jour'] for x in mois['jours']] != attendus:
            raise ValueError('jours manquants ou dupliqués')
        for item in mois['jours']:
            _compteurs(item)
        for k in ('total', 'date_confirmee', 'a_reconfirmer'):
            if mois[k] != sum(x[k] for x in mois['jours']):
                raise ValueError('total du mois incohérent')
        total += mois['total']
        par_jour = {int(x['jour'][-2:]): x for x in mois['jours']}
        rangees = []
        for semaine in calendar.Calendar(firstweekday=0).monthdayscalendar(d.year, d.month):
            cases = []
            for n in semaine:
                if not n:
                    cases.append('<td class="hors-mois"></td>')
                    continue
                item = par_jour[n]
                jour = date(d.year, d.month, n)
                lundi = jour-timedelta(days=jour.weekday())
                classe = 'mois-a-reconfirmer' if item['a_reconfirmer'] else 'mois-jour'
                titre = f'{n} {MOIS[d.month-1]} {d.year}'
                libelle = (f'{item["date_confirmee"]} confirmé(s) · '
                           f'{item["a_reconfirmer"]} à reconfirmer')
                # La vue semaine existante exige sa fin exclusive dans ses bornes civiles.
                if lundi.year >= 1900 and (lundi+timedelta(days=7)).year <= 2199:
                    lien = f'{prefixe}/crm/cedule?debut_semaine={lundi.isoformat()}'
                    label = pages.e(titre+" : "+libelle+". Voir la semaine")
                    bloc = (f'<a href="{pages.e(lien)}" aria-label="{label}">'
                            f'<strong>{n}</strong><span>{pages.e(libelle)}</span></a>')
                else:
                    bloc = f'<strong>{n}</strong><span>{pages.e(libelle)}. Détail semaine hors bornes.</span>'
                cases.append(f'<td class="{classe}" data-jour="{jour.isoformat()}">{bloc}</td>')
            rangees.append('<tr>'+''.join(cases)+'</tr>')
        entete = ''.join(f'<th scope="col">{nom}</th>' for nom in JOURS)
        tableaux.append('<section class="carte"><h3>'+f'{MOIS[d.month-1]} {d.year}</h3>'
                        f'<p>{mois["total"]} créneau(x) · {mois["date_confirmee"]} date(s) interne(s) confirmée(s) · '
                        f'{mois["a_reconfirmer"]} à reconfirmer.</p>'
                        '<div class="table-defilante" role="region" tabindex="0" '
                        f'aria-label="{MOIS[d.month-1]} {d.year}"><table class="cedule-mois">'
                        f'<caption>Créneaux M4 par date de début — {MOIS[d.month-1]} {d.year}</caption>'
                        f'<thead><tr>{entete}</tr></thead><tbody>{"".join(rangees)}</tbody></table></div></section>')
    if total != vue['total_interventions']:
        raise ValueError('total de période incohérent')
    navigation = []
    for offset, label in [(-1, 'Mois précédent'), (1, 'Mois suivant')]:
        cible = decaler(debut, offset)
        if date(1900, 1, 1) <= cible <= date(2199, 10, 1):
            navigation.append(f'<a href="{pages.e(prefixe)}/crm/cedule/mois?premier_mois={cible:%Y-%m}">{label}</a>')
    avertissements = ''.join(f'<li>{pages.e(x)}</li>' for x in vue['avertissements'])
    return ('<section class="carte"><h2>Cédule sur trois mois</h2>'
            '<p>Planification interne. Aucun créneau affiché ne prouve une disponibilité, '
            'une confirmation client ou des travaux terminés.</p>'
            '<p>Chaque créneau compte une fois à sa date de début. '
            'Le repère couleur manuel d’un chantier ne change aucun de ces comptes.</p>'
            f'<p>{vue["total_interventions"]} créneau(x) daté(s) sur les trois mois.</p>'
            f'<p>Sans date dans tout le carnet : {vue["total_sans_date"]}. Hors des totaux mensuels.</p>'
            '<p>Légende : orange et texte « à reconfirmer » signalent une ancienne date à revoir.</p>'
            '<nav aria-label="Navigation des mois">'+' · '.join(navigation)+'</nav>'
            f'<form method="get" action="{pages.e(prefixe)}/crm/cedule/mois" class="cedule-navigation">'
            f'<label>Premier mois<input type="month" name="premier_mois" value="{debut:%Y-%m}" '
            'min="1900-01" max="2199-10" required></label><button type="submit">Afficher</button></form>'
            f'<p><a href="{pages.e(prefixe)}/crm/cedule">Vue semaine</a></p>'
            f'<details><summary>Source de cet aperçu</summary><p>M4 · {vue["source_nombre"]} maillon(s) · '
            f'{pages.e(vue["source_tete"] or "Registre vide")}</p><ul>{avertissements}</ul></details></section>'
            '<div class="cedule-multimois">'+''.join(tableaux)+'</div>')


def creer_router(*, session_page, cnx_factory, deps, prefixe, rendre):
    router = APIRouter()

    @router.get('/crm/cedule/mois')
    def apercu(request: Request):
        session = session_page(request)
        p = request.query_params
        if set(p) - {'premier_mois'} or len(p.getlist('premier_mois')) > 1:
            raise HTTPException(400, 'Choisir un seul premier mois.')
        valeur = p.get('premier_mois', datetime.now(ZoneInfo(FUSEAU)).strftime('%Y-%m'))
        try:
            premier(valeur)
        except ValueError:
            raise HTTPException(400, 'Mois au format AAAA-MM, de 1900-01 à 2199-10.') from None
        vue = notes.appeler(cnx_factory, deps, session, 'm4_lire_apercu_mois', {'premier_mois': valeur})
        try:
            if vue.get('premier_mois') != valeur:
                raise ValueError('période différente')
            corps = contenu(vue, prefixe)
        except (KeyError, TypeError, ValueError, AttributeError):
            raise HTTPException(503, 'Aperçu M4 indisponible : aucun calendrier vide déduit.') from None
        return rendre(session, 'Cédule multi-mois', corps)

    return router
