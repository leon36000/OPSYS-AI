"""Lecture privée des déclarations quotidiennes : source indépendante et admin SQL courant."""
from m4_field_ops import absences_durables

from . import memoire_chantier as autorite
from . import preparation_chantier as lecture

M4 = 'm04-field-ops'
NOM = 'm4_lire_absences_jour_console'


def _t0(deps, session, arguments):
    return lecture._appel(deps, session.utilisateur, M4, NOM, arguments)


def lire(cnx, deps, session, jour, *, debut=0, limite=50, source_attendue=None):
    autorite._admin(cnx, session)
    try:
        source = absences_durables.capturer(cnx)
        arguments = dict(jour=jour, debut=debut, limite=limite,
                         source_attendue=source_attendue)
        attendu = absences_durables.projeter_jour(source, **arguments)
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


def url_jour(jour, prefixe):
    from urllib.parse import urlencode

    return prefixe + '/crm/journal-equipes/absences?' + urlencode(dict(jour=jour))


def contenu(vue, prefixe, limite):
    from urllib.parse import urlencode

    from . import absences_personnes, pages

    def lien(debut, titre):
        args = dict(jour=vue['jour'], debut=debut, limite=limite, source_attendue=vue['source'])
        return f'<a href="{pages.e(prefixe + "/crm/journal-equipes/absences?" + urlencode(args))}">{titre}</a>'

    retour = prefixe + '/crm/journal-equipes?' + urlencode(dict(jour=vue['jour']))
    corps = (f'<p><a href="{pages.e(retour)}">Retour au journal</a></p>'
             f'<section><h2>Signalements d’absence — {pages.e(vue["jour"])}</h2><ul>')
    corps += ''.join(f'<li>{pages.e(a)}</li>' for a in vue['avertissements']) + '</ul>'
    corps += ('<p>Cette liste ne représente pas l’annuaire complet du personnel.</p>'
              f'<p>{len(vue["lignes"])} personnes affichées sur {vue["total"]} ayant une déclaration.</p>'
              f'<form method="get" action="{pages.e(prefixe)}/crm/journal-equipes/absences" class="pile">'
              f'<label>Jour<input type="date" name="jour" value="{pages.e(vue["jour"])}" required></label>'
              '<button type="submit">Afficher cette journée</button></form>')
    nav = []
    if vue['debut']:
        nav.append(lien(max(0, vue['debut'] - limite), 'Page précédente'))
    if vue['suivant'] is not None:
        nav.append(lien(vue['suivant'], 'Page suivante'))
    corps += '<nav aria-label="Pages des déclarations quotidiennes">' + ' · '.join(nav) + '</nav>'
    if not vue['lignes']:
        corps += ('<p>Aucun signalement documenté pour cette journée.</p>' if vue['total'] == 0 else
                  '<p>Aucune déclaration sur cette page. ' + lien(0, 'Première page') + '</p>')
    corps += ('<table><thead><tr><th>Identifiant historique</th><th>Déclaration</th><th>Révision</th>'
              '<th>Auteur consigné</th><th>Instant d’enregistrement source</th><th>Source</th>'
              '<th>Consultation</th></tr></thead><tbody>')
    for ligne in vue['lignes']:
        valeurs = [ligne['personne_id'], 'Signalement déclaré' if ligne['etat_declaration'] == 'signalee'
                   else 'Retiré — présence inconnue', ligne['revision'], ligne['auteur']['personne'],
                   ligne['horodatage'], ligne['source_ligne_id']]
        cible = absences_personnes.url_declaration(vue['jour'], ligne['personne_id'], prefixe)
        corps += ('<tr>' + ''.join(f'<td>{pages.e(v)}</td>' for v in valeurs)
                  + f'<td><a href="{pages.e(cible)}">Historique individuel</a></td></tr>')
    corps += ('</tbody></table><details><summary>Source de consultation</summary>'
              f'<p>Empreinte calculée du snapshot : {pages.e(vue["source_snapshot"])}</p></details></section>')
    return corps + absences_personnes.formulaire_consultation(vue['jour'], prefixe)


def creer_router(*, session_page, cnx_factory, deps, prefixe, rendre):
    from fastapi import APIRouter, HTTPException, Request

    from . import journal_equipes

    router = APIRouter()

    @router.get('/crm/journal-equipes/absences')
    def page(request: Request):
        session = session_page(request)
        try:
            args = journal_equipes.arguments(request.query_params)
        except (ValueError, TypeError):
            raise HTTPException(400, 'Choisir un jour et une page valides') from None
        try:
            with cnx_factory() as cnx:
                vue = lire(cnx, deps, session, **args)
                reponse = rendre(session, 'Signalements quotidiens', contenu(vue, prefixe, args['limite']))
                if len(reponse.body) > 131072:
                    raise HTTPException(503, 'Liste trop volumineuse; réduire la page')
                if absences_durables.capturer(cnx).empreinte_snapshot_calculee != vue['source_snapshot']:
                    raise lecture.Refus('SOURCE-MODIFIEE')
                autorite._admin(cnx, session)
        except PermissionError:
            raise HTTPException(403, 'Accès admin requis') from None
        except (lecture.Refus, ValueError, KeyError, TypeError):
            raise HTTPException(503, 'Liste indisponible; relire la journée') from None
        return reponse

    return router
