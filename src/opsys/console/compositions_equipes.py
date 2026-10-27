"""Lecture privée des compositions déclarées : source indépendante et admin SQL courant."""
from m4_field_ops import composition_durable

from . import memoire_chantier as autorite
from . import preparation_chantier as lecture

M4 = 'm04-field-ops'
NOM = 'm4_lire_composition_journaliere_console'


def _t0(deps, session, arguments):
    return lecture._appel(deps, session.utilisateur, M4, NOM, arguments)


def lire(cnx, deps, session, jour, equipe_id, *, debut=0, limite=50, source_attendue=None):
    autorite._admin(cnx, session)
    try:
        source = composition_durable.capturer(cnx)
        arguments = dict(jour=jour, equipe_id=equipe_id, debut=debut, limite=limite, source_attendue=source_attendue)
        attendu = composition_durable.projeter(source, **arguments)
        composition_durable.verifier_sortie(attendu)
        resultat = _t0(deps, session, arguments)
        if resultat != attendu:
            raise lecture.Refus('SOURCE-REPONSE-INCOHERENTE')
        if composition_durable.capturer(cnx).empreinte_snapshot_calculee != source.empreinte_snapshot_calculee:
            raise lecture.Refus('SOURCE-MODIFIEE')
        resultat = lecture._sortie(resultat)
    except composition_durable.Refus as exc:
        raise lecture.Refus(exc.code) from None
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, lecture.Refus):
            raise
        raise lecture.Refus('SOURCE-COMPOSITION-INVALIDE') from None
    autorite._admin(cnx, session)
    return resultat



def url_journal(jour, equipe_id, prefixe):
    from urllib.parse import urlencode

    from m4_field_ops import composition_journaliere as domaine

    try:
        jour, equipe_id = domaine._jour(jour), domaine._identifiant(equipe_id)
    except domaine.Refus:
        return None  # L'identifiant historique reste intact; aucune normalisation vers une autre équipe.
    return prefixe + '/crm/journal-equipes/composition?' + urlencode(dict(jour=jour, equipe_id=equipe_id))


def arguments(params):
    from m4_field_ops import composition_journaliere as domaine
    from starlette.datastructures import QueryParams

    from . import journal_equipes

    items = list(params.multi_items())
    if len(items) != len({k for k, _ in items}) or 'equipe_id' not in params:
        raise ValueError('équipe explicite et paramètres uniques requis')
    try:
        equipe = domaine._identifiant(params['equipe_id'])
    except domaine.Refus:
        raise ValueError('identifiant d’équipe invalide') from None
    resultat = journal_equipes.arguments(QueryParams([(k, v) for k, v in items if k != 'equipe_id']))
    return dict(resultat, equipe_id=equipe)


def contenu(vue, prefixe, limite):
    from urllib.parse import urlencode

    from . import pages

    def lien(debut, titre):
        args = dict(jour=vue['jour'], equipe_id=vue['equipe_id'], debut=debut, limite=limite,
                    source_attendue=vue['source'])
        return f'<a href="{pages.e(prefixe + "/crm/journal-equipes/composition?" + urlencode(args))}">{titre}</a>'

    retour = prefixe + '/crm/journal-equipes?' + urlencode(dict(jour=vue['jour']))
    corps = (f'<p><a href="{pages.e(retour)}">Retour au journal</a></p>'
             f'<section><h2>Composition déclarée — {pages.e(vue["equipe_id"])}</h2>'
             f'<p>Jour déclaré : {pages.e(vue["jour"])}</p><ul>')
    corps += ''.join(f'<li>{pages.e(a)}</li>' for a in vue['avertissements']) + '</ul>'
    if not vue['composition_connue']:
        corps += ('<p>Aucune déclaration pour cette équipe et cette journée; composition inconnue.</p>'
                  if vue['revision'] == 0 else '<p>Déclaration retirée; composition inconnue.</p>')
    elif not vue['membres']:
        corps += '<p>Liste déclarée explicitement vide.</p>'
    else:
        corps += '<h3>Identifiants actuellement déclarés pour ce jour</h3><ul>'
        corps += ''.join(f'<li>{pages.e(m)}</li>' for m in vue['membres']) + '</ul>'
    corps += '<p>Cette déclaration journalière ne prouve pas qui était présent à une intervention.</p>'
    nav = []
    if vue['debut']:
        nav.append(lien(max(0, vue['debut'] - limite), 'Page précédente'))
    if vue['suivant'] is not None:
        nav.append(lien(vue['suivant'], 'Page suivante'))
    corps += '<nav aria-label="Pages de l’historique déclaré">' + ' · '.join(nav) + '</nav>'
    if not vue['lignes'] and vue['total']:
        corps += '<p>Aucune révision sur cette page. ' + lien(0, 'Première page') + '</p>'
    corps += ('<h3>Historique des déclarations</h3><table><thead><tr><th>Révision</th><th>Déclaration</th>'
              '<th>Identifiants déclarés</th><th>Auteur déclaré</th><th>Instant d’enregistrement source</th>'
              '<th>État de la révision</th><th>Source</th></tr></thead><tbody>')
    for ligne in vue['lignes']:
        membres = ('Inconnue (retrait)' if ligne['membres'] is None else
                   ', '.join(ligne['membres']) if ligne['membres'] else 'Liste explicitement vide')
        valeurs = [f'Révision {ligne["revision"]}',
                   'Retrait' if ligne['statut_declaration'] == 'retiree' else 'Déclaration', membres,
                   ligne['auteur']['personne'], ligne['horodatage'],
                   'Courante' if ligne['courante'] else 'Historique', ligne['source_ligne_id']]
        corps += '<tr>' + ''.join(f'<td>{pages.e(v)}</td>' for v in valeurs) + '</tr>'
    corps += ('</tbody></table><details><summary>Source de consultation</summary>'
              f'<p>Empreinte calculée du snapshot : {pages.e(vue["source_snapshot"])}</p></details></section>')
    return corps


def creer_router(*, session_page, cnx_factory, deps, prefixe, rendre):
    from fastapi import APIRouter, HTTPException, Request

    router = APIRouter()

    @router.get('/crm/journal-equipes/composition')
    def page(request: Request):
        session = session_page(request)
        try:
            args = arguments(request.query_params)
        except (ValueError, TypeError):
            raise HTTPException(400, 'Choisir une journée, une équipe et une page valides') from None
        try:
            with cnx_factory() as cnx:
                vue = lire(cnx, deps, session, **args)
                reponse = rendre(session, 'Composition déclarée', contenu(vue, prefixe, args['limite']))
                if len(reponse.body) > 131072:
                    raise HTTPException(503, 'Historique trop volumineux; réduire la page')
                autorite._admin(cnx, session)
        except PermissionError:
            raise HTTPException(403, 'Accès admin requis') from None
        except (lecture.Refus, ValueError, KeyError, TypeError):
            raise HTTPException(503, 'Composition indisponible; relire depuis le journal ou réduire la page') from None
        return reponse

    return router
