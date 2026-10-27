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


def contenu_formulaire(vue, session, prefixe):
    """La saisie historique reste distincte de la configuration actuelle et des présences."""
    import uuid

    from m4_field_ops import composition_ecriture, composition_journaliere

    from .. import identite
    from . import pages

    if vue['revision'] == 0:
        try:
            profil, _ = composition_ecriture._profil()
            initiale = (identite.identifiant_valide(vue['equipe_id'])
                        and vue['equipe_id'] in {e['id'] for e in profil.get('liste', [])})
        except (composition_journaliere.Refus, OSError):
            initiale = False
        if not initiale:
            return '<p>Déclaration initiale indisponible : équipe actuelle non confirmée.</p>'
    chemin = url_journal(vue['jour'], vue['equipe_id'], prefixe)

    def debut(statut):
        return (f'<form method="post" action="{pages.e(chemin)}" class="pile">'
                f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
                f'<input type="hidden" name="revision_attendue" value="{vue["revision"]}">'
                f'<input type="hidden" name="mutation_id" value="{uuid.uuid4()}">'
                f'<input type="hidden" name="statut_declaration" value="{statut}">')

    membres = '\n'.join(vue['membres']) if vue['composition_connue'] else ''
    corps = ('<section><h3>Déclarer ou corriger la composition de cette journée</h3>'
             '<p>Saisir un identifiant de compte connu par ligne, 50 au plus. Une liste vide signifie '
             'explicitement aucun membre déclaré. Un compte inactif peut être cité pour l’historique; '
             'cette déclaration ne le réactive pas et ne change aucun accès.</p>'
             + debut('declaree')
             + '<label>Identifiants des membres déclarés<textarea name="membres" rows="6" maxlength="3250">'
             + pages.e(membres) + '</textarea></label><button type="submit">Enregistrer la déclaration</button></form>')
    if vue['composition_connue']:
        corps += (debut('retiree') + '<input type="hidden" name="membres" value="">'
                  '<p>Retirer la déclaration rend la composition inconnue et conserve les anciennes versions.</p>'
                  '<button type="submit">Retirer la déclaration</button></form>')
    return corps + '</section>'


async def formulaire(request):
    import uuid
    from urllib.parse import parse_qs

    from fastapi import HTTPException

    from .annotations_cedule_ui import _entier

    if request.headers.get('content-type', '').split(';')[0] != 'application/x-www-form-urlencoded':
        raise HTTPException(415, 'Formulaire requis')
    corps = bytearray()
    async for bloc in request.stream():
        corps.extend(bloc)
        if len(corps) > 12000:
            raise HTTPException(413, 'Formulaire trop volumineux')
    try:
        p = parse_qs(corps.decode('utf-8'), keep_blank_values=True, strict_parsing=True,
                     max_num_fields=5, errors='strict')
        if (set(p) != {'csrf', 'membres', 'revision_attendue', 'mutation_id', 'statut_declaration'}
                or any(len(v) != 1 for v in p.values())):
            raise ValueError('champs invalides')
        champs = {k: v[0] for k, v in p.items()}
        if str(uuid.UUID(champs['mutation_id'])) != champs['mutation_id']:
            raise ValueError('intention invalide')
        if champs['statut_declaration'] not in {'declaree', 'retiree'}:
            raise ValueError('statut invalide')
        if champs['statut_declaration'] == 'retiree' and champs['membres'] != '':
            raise ValueError('retrait sans liste')
        brut = champs['membres'].replace('\r\n', '\n').removesuffix('\n')
        membres = None
        if champs['statut_declaration'] == 'declaree':
            membres = [] if champs['membres'] == '' else brut.split('\n')
        return champs, dict(membres=membres, revision_attendue=_entier(champs['revision_attendue']),
                            statut_declaration=champs['statut_declaration'])
    except (ValueError, UnicodeError):
        raise HTTPException(400, 'Déclaration invalide') from None


def confirmer(reponse):
    from fastapi import HTTPException

    r = reponse.get('resultat') if isinstance(reponse, dict) and reponse.get('ok') is True else None
    if not isinstance(r, dict):
        raise HTTPException(503, 'Déclaration indisponible')
    if r.get('accepte') is True and isinstance(r.get('resultat'), dict):
        return
    code = r.get('verdict', {}).get('code', '').removeprefix('REJ-COMPOSITION-')
    if code == 'IDENTITE':
        raise HTTPException(403, 'Accès admin requis')
    if code in {'REVISION-PERIMEE', 'MUTATION-CONFLIT', 'SOURCE-MODIFIEE'}:
        raise HTTPException(409, 'Déclaration modifiée : relire la journée avant de recommencer')
    if code in {'ARGUMENTS', 'DECLARATION-INVALIDE', 'IDENTITES-NON-CONFIRMEES', 'MUTATION-ABSENTE'}:
        raise HTTPException(400, 'Déclaration ou identifiants invalides')
    raise HTTPException(503, 'Source indisponible; aucune nouvelle déclaration confirmée')


def creer_router(*, session_page, cnx_factory, deps, prefixe, rendre, verifier_formulaire):
    from fastapi import APIRouter, HTTPException, Request
    from fastapi.responses import RedirectResponse

    from . import metier

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
                corps = contenu(vue, prefixe, args['limite']) + contenu_formulaire(vue, session, prefixe)
                reponse = rendre(session, 'Composition déclarée', corps)
                if len(reponse.body) > 131072:
                    raise HTTPException(503, 'Historique trop volumineux; réduire la page')
                autorite._admin(cnx, session)
        except PermissionError:
            raise HTTPException(403, 'Accès admin requis') from None
        except (lecture.Refus, ValueError, KeyError, TypeError):
            raise HTTPException(503, 'Composition indisponible; relire depuis le journal ou réduire la page') from None
        return reponse

    @router.post('/crm/journal-equipes/composition')
    async def enregistrer(request: Request):
        session = session_page(request)
        try:
            if set(request.query_params) != {'jour', 'equipe_id'}:
                raise ValueError('jour et équipe requis')
            args = arguments(request.query_params)
        except (ValueError, TypeError):
            raise HTTPException(400, 'Choisir une journée et une équipe valides') from None
        champs, declaration = await formulaire(request)
        verifier_formulaire(champs, session)
        try:
            with cnx_factory() as cnx:
                autorite._admin(cnx, session)
                with cnx.begin_nested():
                    reponse = metier.executer(cnx, deps, session, 'm4_declarer_composition_journaliere_console',
                        dict(jour=args['jour'], equipe_id=args['equipe_id'], **declaration),
                        mutation_id=champs['mutation_id'])
                    confirmer(reponse)
                    autorite._admin(cnx, session)
        except PermissionError:
            raise HTTPException(403, 'Accès admin requis') from None
        except ValueError:
            raise HTTPException(400, 'Déclaration invalide') from None
        except (lecture.Refus, KeyError, RuntimeError):
            raise HTTPException(503, 'Déclaration indisponible; relire la journée') from None
        return RedirectResponse(url_journal(args['jour'], args['equipe_id'], prefixe), status_code=303)

    return router
