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
    from . import comptes_terrain, pages

    return (f'<form method="get" action="{pages.e(prefixe)}/crm/journal-equipes/absence" class="pile">'
            '<h3>Consulter une absence signalée</h3>'
            f'<input type="hidden" name="jour" value="{pages.e(jour)}">'
            '<label>Identifiant historique de personne<input name="personne_id" maxlength="64" '
            'autocomplete="off" required></label><p>Consultation seulement, par identifiant exact. '
            'Un signalement n’est pas une absence mesurée; son absence ne prouve aucune présence.</p>'
            '<button type="submit">Consulter le signalement et son historique</button></form>'
            f'<p><a href="{pages.e(comptes_terrain.url_jour(jour, prefixe))}">'
            'Choisir un compte interne par son nom actuel</a></p>')


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



def url_declaration(jour, personne_id, prefixe):
    from urllib.parse import urlencode

    return prefixe + '/crm/journal-equipes/absence?' + urlencode(dict(jour=jour, personne_id=personne_id))


def contenu_formulaire(cnx, vue, session, prefixe):
    import uuid

    from m4_field_ops import absences_ecriture, absences_journalieres

    from . import pages

    if vue['revision'] == 0:
        try:
            absences_ecriture._cible_initiale(cnx, vue['personne_id'])
        except absences_journalieres.Refus:
            return '<p>Première déclaration indisponible : compte interne humain non confirmé.</p>'
    chemin = url_declaration(vue['jour'], vue['personne_id'], prefixe)

    def forme(statut, bouton):
        return (f'<form method="post" action="{pages.e(chemin)}" class="pile">'
                f'<input type="hidden" name="csrf" value="{pages.e(session.csrf)}">'
                f'<input type="hidden" name="revision_attendue" value="{vue["revision"]}">'
                f'<input type="hidden" name="mutation_id" value="{uuid.uuid4()}">'
                f'<input type="hidden" name="statut_declaration" value="{statut}">'
                f'<button type="submit">{bouton}</button></form>')

    corps = ('<section><h3>Validation administrative pour cette journée et cet identifiant</h3>'
             '<p>Votre action signe un signalement déclaré, sans prouver une absence mesurée ou un emploi passé. '
             'Aucun compte réactivé, motif de santé, heure ou effet de paie. Les versions restent conservées.</p>'
             + forme('signalee', 'Signaler l’absence pour ce jour'))
    if vue['etat_declaration'] == 'signalee':
        corps += ('<p>Retirer le signalement rend l’état inconnu; cela ne signifie pas présent.</p>'
                  + forme('retiree', 'Retirer le signalement pour ce jour'))
    return corps + '</section>'

def creer_router(*, session_page, cnx_factory, deps, prefixe, rendre, verifier_formulaire):
    from fastapi import APIRouter, HTTPException, Request
    from fastapi.responses import RedirectResponse

    from . import annotations_cedule_ui as saisie
    from . import compositions_equipes, metier

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
                corps = contenu(vue, prefixe, args['limite']) + contenu_formulaire(cnx, vue, session, prefixe)
                reponse = rendre(session, 'Absence signalée', corps)
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

    @router.post('/crm/journal-equipes/absence')
    async def enregistrer(request: Request):
        import uuid

        session = session_page(request)
        try:
            if set(request.query_params) != {'jour', 'personne_id'}:
                raise ValueError('jour et personne explicites requis')
            args = arguments(request.query_params)
        except (ValueError, TypeError):
            raise HTTPException(400, 'Choisir un jour et une personne valides') from None
        champs = await saisie._formulaire(request, champ='statut_declaration')
        verifier_formulaire(champs, session)
        try:
            if (str(uuid.UUID(champs['mutation_id'])) != champs['mutation_id']
                    or champs['statut_declaration'] not in {'signalee', 'retiree'}):
                raise ValueError('déclaration invalide')
            revision = saisie._entier(champs['revision_attendue'])
        except ValueError:
            raise HTTPException(400, 'Déclaration invalide') from None
        try:
            with cnx_factory() as cnx:
                autorite._admin(cnx, session)
                with cnx.begin_nested():
                    reponse = metier.executer(cnx, deps, session, 'm4_declarer_absence_journaliere_console',
                        dict(jour=args['jour'], personne_id=args['personne_id'], revision_attendue=revision,
                             statut_declaration=champs['statut_declaration']), mutation_id=champs['mutation_id'])
                    compositions_equipes.confirmer(reponse, prefixe='REJ-ABSENCE-')
                    autorite._admin(cnx, session)
        except PermissionError:
            raise HTTPException(403, 'Accès admin requis') from None
        except (lecture.Refus, KeyError, RuntimeError):
            raise HTTPException(503, 'Signalement indisponible; relire la journée') from None
        except ValueError:
            raise HTTPException(400, 'Déclaration invalide') from None
        return RedirectResponse(url_declaration(args['jour'], args['personne_id'], prefixe), status_code=303)

    return router
