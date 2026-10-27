"""Lecture privée des absences signalées : source indépendante et admin SQL courant."""
from m4_field_ops import absences_durables

from . import memoire_chantier as autorite
from . import preparation_chantier as lecture

M4 = 'm04-field-ops'
NOM = 'm4_lire_absence_journaliere_console'


def _t0(deps, session, arguments):
    return lecture._appel(deps, session.utilisateur, M4, NOM, arguments)


def lire(cnx, deps, session, jour, personne_id, *, debut=0, limite=50, source_attendue=None):
    autorite._admin(cnx, session)
    try:
        source = absences_durables.capturer(cnx)
        arguments = dict(jour=jour, personne_id=personne_id, debut=debut, limite=limite,
                         source_attendue=source_attendue)
        attendu = absences_durables.projeter(source, **arguments)
        absences_durables.verifier_sortie(attendu)
        resultat = _t0(deps, session, arguments)
        if resultat != attendu:
            raise lecture.Refus('SOURCE-REPONSE-INCOHERENTE')
        if absences_durables.capturer(cnx).empreinte_snapshot_calculee != source.empreinte_snapshot_calculee:
            raise lecture.Refus('SOURCE-MODIFIEE')
        resultat = lecture._sortie(resultat)
    except absences_durables.Refus as exc:
        raise lecture.Refus(exc.code) from None
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, lecture.Refus):
            raise
        raise lecture.Refus('SOURCE-ABSENCE-INVALIDE') from None
    autorite._admin(cnx, session)
    return resultat


def arguments(params):
    from m4_field_ops import absences_journalieres as domaine
    from starlette.datastructures import QueryParams

    from . import journal_equipes

    items = list(params.multi_items())
    if len(items) != len({k for k, _ in items}) or 'personne_id' not in params:
        raise ValueError('personne explicite et paramètres uniques requis')
    try:
        personne = domaine._identifiant(params['personne_id'])
    except domaine.Refus:
        raise ValueError('identifiant historique invalide') from None
    resultat = journal_equipes.arguments(QueryParams([(k, v) for k, v in items if k != 'personne_id']))
    return dict(resultat, personne_id=personne)


def formulaire_consultation(jour, prefixe):
    from . import pages

    return (f'<form method="get" action="{pages.e(prefixe)}/crm/journal-equipes/absence" class="pile">'
            '<h3>Consulter une absence signalée</h3>'
            f'<input type="hidden" name="jour" value="{pages.e(jour)}">'
            '<label>Identifiant historique de personne<input name="personne_id" maxlength="64" '
            'autocomplete="off" required></label><p>Consultation seulement, par identifiant exact. '
            'Un signalement n’est pas une absence mesurée; son absence ne prouve aucune présence.</p>'
            '<button type="submit">Consulter le signalement et son historique</button></form>')


def contenu(vue, prefixe, limite):
    from urllib.parse import urlencode

    from . import pages

    def lien(debut, titre):
        args = dict(jour=vue['jour'], personne_id=vue['personne_id'], debut=debut,
                    limite=limite, source_attendue=vue['source'])
        chemin = prefixe + '/crm/journal-equipes/absence?' + urlencode(args)
        return f'<a href="{pages.e(chemin)}">{titre}</a>'

    retour = prefixe + '/crm/journal-equipes?' + urlencode(dict(jour=vue['jour']))
    corps = (f'<p><a href="{pages.e(retour)}">Retour au journal</a></p>'
             '<section><h2>Absence signalée — déclaration administrative</h2>'
             f'<p>Identifiant historique : {pages.e(vue["personne_id"])} · Jour déclaré : '
             f'{pages.e(vue["jour"])}</p><ul>')
    corps += ''.join(f'<li>{pages.e(a)}</li>' for a in vue['avertissements']) + '</ul>'
    etats = {'aucun_signalement': 'Aucune absence signalée pour cet identifiant et ce jour.',
             'signalee': 'Absence signalée par un administrateur; déclaration seulement.',
             'retiree': 'Signalement retiré; aucune présence déduite.'}
    corps += f'<p>{pages.e(etats[vue["etat_declaration"]])}</p>'
    nav = []
    if vue['debut']:
        nav.append(lien(max(0, vue['debut'] - limite), 'Page précédente'))
    if vue['suivant'] is not None:
        nav.append(lien(vue['suivant'], 'Page suivante'))
    corps += '<nav aria-label="Pages des signalements">' + ' · '.join(nav) + '</nav>'
    if not vue['lignes'] and vue['total']:
        corps += '<p>Aucune version sur cette page. ' + lien(0, 'Première page') + '</p>'
    corps += ('<h3>Historique des signalements</h3><table><thead><tr><th>Révision</th>'
              '<th>Déclaration</th><th>Jour déclaré</th><th>Auteur consigné</th>'
              '<th>Instant d’enregistrement source</th><th>Version</th><th>Source</th></tr></thead><tbody>')
    for ligne in vue['lignes']:
        valeurs = [f'Révision {ligne["revision"]}',
                   'Signalée' if ligne['statut_declaration'] == 'signalee' else 'Retirée',
                   ligne['jour'], ligne['auteur']['personne'], ligne['horodatage'],
                   'Courante' if ligne['courante'] else 'Historique', ligne['source_ligne_id']]
        corps += '<tr>' + ''.join(f'<td>{pages.e(v)}</td>' for v in valeurs) + '</tr>'
    corps += ('</tbody></table><details><summary>Source de consultation</summary>'
              f'<p>Empreinte calculée du snapshot : {pages.e(vue["source_snapshot"])}</p></details></section>')
    return corps


def creer_router(*, session_page, cnx_factory, deps, prefixe, rendre):
    from fastapi import APIRouter, HTTPException, Request

    router = APIRouter()

    @router.get('/crm/journal-equipes/absence')
    def page(request: Request):
        session = session_page(request)
        try:
            args = arguments(request.query_params)
        except (ValueError, TypeError):
            raise HTTPException(400, 'Choisir un jour, une personne et une page valides') from None
        try:
            with cnx_factory() as cnx:
                vue = lire(cnx, deps, session, **args)
                reponse = rendre(session, 'Absence signalée', contenu(vue, prefixe, args['limite']))
                if len(reponse.body) > 131072:
                    raise HTTPException(503, 'Historique trop volumineux; réduire la page')
                if absences_durables.capturer(cnx).empreinte_snapshot_calculee != vue['source_snapshot']:
                    raise lecture.Refus('SOURCE-MODIFIEE')
                autorite._admin(cnx, session)
        except PermissionError:
            raise HTTPException(403, 'Accès admin requis') from None
        except (lecture.Refus, ValueError, KeyError, TypeError):
            raise HTTPException(503, 'Signalement indisponible; relire depuis le journal') from None
        return reponse

    return router
