"""Port privé du journal M4 : vrai T0, projection attendue et admin courant, sans écran."""
from m4_field_ops import journal_durable

from . import memoire_chantier as autorite
from . import preparation_chantier as lecture

M4 = 'm04-field-ops'
NOM = 'm4_lire_journal_quotidien'


def _t0(deps, session, arguments):
    return lecture._appel(deps, session.utilisateur, M4, NOM, arguments)


def lire(cnx, deps, session, jour, *, debut=0, limite=50, source_attendue=None):
    autorite._admin(cnx, session)
    try:
        source = journal_durable.capturer(cnx)
        arguments = dict(jour=jour, debut=debut, limite=limite, source_attendue=source_attendue)
        attendu = journal_durable.projeter(source, **arguments)
        journal_durable.verifier_sortie(attendu)
        resultat = _t0(deps, session, arguments)
        if resultat != attendu:
            raise lecture.Refus('SOURCE-REPONSE-INCOHERENTE')
        if journal_durable.capturer(cnx).empreinte_snapshot_calculee != source.empreinte_snapshot_calculee:
            raise lecture.Refus('SOURCE-MODIFIEE')
        resultat = lecture._sortie(resultat)
    except journal_durable.Refus as exc:
        raise lecture.Refus(exc.code) from None
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, lecture.Refus):
            raise
        raise lecture.Refus('SOURCE-JOURNAL-INVALIDE') from None
    autorite._admin(cnx, session)
    return resultat


def arguments(params):
    import re

    from m4_field_ops import calendrier_civil

    items = list(params.multi_items())
    if (len(items) != len({k for k, _ in items}) or set(params) - {'jour', 'debut', 'limite', 'source_attendue'}
            or 'jour' not in params):
        raise ValueError('jour explicite et paramètres uniques requis')
    jour = calendrier_civil._date(params['jour']).isoformat()
    nombres = {}
    for nom, defaut, mini, maxi in [('debut', '0', 0, 11000), ('limite', '50', 1, 100)]:
        brut = params.get(nom, defaut)
        if re.fullmatch(r'0|[1-9][0-9]{0,4}', brut) is None or not mini <= int(brut) <= maxi:
            raise ValueError('page invalide')
        nombres[nom] = int(brut)
    source = params.get('source_attendue')
    if ((source is not None and re.fullmatch('[0-9a-f]{64}', source) is None)
            or (nombres['debut'] and source is None)):
        raise ValueError('source requise pour continuer')
    return dict(jour=jour, **nombres, source_attendue=source)


def contenu(vue, prefixe, limite):
    from datetime import date, timedelta
    from urllib.parse import urlencode

    from . import absences_personnes, annotations_cedule_ui, cedule_ui, compositions_equipes, pages

    def lien(debut, titre):
        args = dict(jour=vue['jour'], debut=debut, limite=limite, source_attendue=vue['source'])
        return f'<a href="{pages.e(prefixe + "/crm/journal-equipes?" + urlencode(args))}">{titre}</a>'

    jour = date.fromisoformat(vue['jour'])
    semaine = (jour - timedelta(days=jour.weekday())).isoformat()
    corps = (f'<p><a href="{pages.e(prefixe)}/crm/cedule?debut_semaine={semaine}">Retour à la cédule</a></p>'
             f'<section><h2>Journal des équipes — {pages.e(vue["jour"])}</h2>'
             f'<p>Fuseau : {pages.e(vue["fuseau"])}</p><ul>')
    corps += ''.join(f'<li>{pages.e(a)}</li>' for a in vue['avertissements']) + '</ul>'
    corps += ('<p>Chaque ligne décrit un événement à son instant. Les déclarations et arbitrages terrain '
              'proviennent de M4; les décisions sur les extras facturables relèvent de M3/M5. '
              'L’identifiant assigné peut désigner une personne ou une équipe. Cette décision ne prouve pas '
              'la présence ou la composition réelle de l’équipe.</p>')
    corps += absences_personnes.formulaire_consultation(vue["jour"], prefixe)
    corps += f'<p>{len(vue["lignes"])} entrées affichées sur {vue["total"]}.</p>'
    nav = []
    if vue['debut']:
        nav.append(lien(max(0, vue['debut'] - limite), 'Page précédente'))
    if vue['suivant'] is not None:
        nav.append(lien(vue['suivant'], 'Page suivante'))
    corps += '<nav aria-label="Pages du journal">' + ' · '.join(nav) + '</nav>'
    if not vue['lignes']:
        corps += ('<p>Aucun fait ou prévision pour cette journée.</p>' if vue['total'] == 0 else
                  '<p>Aucune entrée sur cette page. ' + lien(0, 'Première page') + '</p>')
    corps += ('<table><thead><tr><th>Type</th><th>Intervention</th><th>Heure locale</th><th>Équipe prévue</th>'
              '<th>Personne ou équipe assignée</th><th>Technicien du pointage</th><th>État ou action</th>'
              '<th>Validité de la prévision</th>'
              '<th>Source</th><th>Consultations</th></tr></thead><tbody>')
    types = {'prevision': 'Prévision', 'pointage': 'Pointage', 'etat': 'Changement d’état',
             'ecart_declare': 'Écart déclaré', 'ecart_arbitre': 'Arbitrage d’écart',
             'assignation': 'Décision d’assignation'}
    arbitrages = {'en_attente': 'En attente d’arbitrage M4', 'validee': 'Arbitrage M4 validé',
                  'rejetee': 'Arbitrage M4 rejeté'}
    dimensions = {'duree_minutes': 'Durée déclarée', 'materiaux': 'Matériaux déclarés',
                  'perimetre': 'Périmètre déclaré'}
    validites = {'historique': 'Ancienne prévision', 'a_reconfirmer': 'À reconfirmer',
                 'date_confirmee': 'Date confirmée'}
    for ligne in vue['lignes']:
        etat = cedule_ui.STATUTS.get(ligne.get('statut'), ligne.get('action', 'Non applicable'))
        source = ligne['source_ligne_id']
        if ligne['type'] == 'assignation':
            etat = 'Assignation consignée'
        elif ligne.get('statut') == 'en_route' and 'technicien_assigne' in ligne:
            etat += ' · Départ consigné'
        if ligne['type'] in {'ecart_declare', 'ecart_arbitre'}:
            etat = arbitrages[ligne['statut_arbitrage']] + ' · ' + ', '.join(
                dimensions[k] for k in ligne['dimensions_modifiees'])
            source += ' · Demande : ' + ligne['demande_id'] + ' · Source de demande : ' + ligne['source_demande_id']
        if ligne.get('motif'):
            etat += ' · ' + ligne['motif']
        heure = ligne['instant'] if ligne['type'] != 'prevision' else ligne['debut'] + ' – ' + ligne['fin']
        assigne = ligne.get('technicien_assigne', 'Non applicable')
        if not assigne.strip():
            assigne = 'Identifiant à vérifier (espaces uniquement)'
        valeurs = [types[ligne['type']], ligne['intervention_id'], heure,
                   ligne.get('equipe_planifiee', 'Non applicable'), assigne,
                   ligne.get('technicien_id', 'Non applicable'),
                   etat, validites.get(ligne.get('validite'), 'Non applicable'), source]
        note = 'Aucune ancre de visite démontrée'
        if ligne['type'] == 'prevision':
            url = annotations_cedule_ui.url(annotations_cedule_ui.ancre_de(ligne), prefixe)
            note = f'<a href="{pages.e(url)}" aria-label="Notes de cette prévision">Notes et historique</a>'
            composition = compositions_equipes.url_journal(vue['jour'], ligne['equipe_planifiee'], prefixe)
            if composition is None:
                note += ' · Composition non consultable pour cet identifiant historique.'
            else:
                note += (f' · <a href="{pages.e(composition)}" '
                         'aria-label="Composition déclarée de l’équipe pour ce jour">Composition déclarée</a>')
        corps += '<tr>' + ''.join(f'<td>{pages.e(v)}</td>' for v in valeurs) + f'<td>{note}</td></tr>'
    corps += ('</tbody></table><details><summary>Sources de consultation</summary>'
              f'<p>Empreinte calculée du snapshot : {pages.e(vue["source_snapshot"])}</p></details></section>')
    return corps


def creer_router(*, session_page, cnx_factory, deps, prefixe, rendre):
    from fastapi import APIRouter, HTTPException, Request

    router = APIRouter()

    @router.get('/crm/journal-equipes')
    def page(request: Request):
        session = session_page(request)
        try:
            args = arguments(request.query_params)
        except (ValueError, TypeError):
            raise HTTPException(400, 'Choisir une journée et une page valides') from None
        try:
            with cnx_factory() as cnx:
                vue = lire(cnx, deps, session, **args)
                reponse = rendre(session, 'Journal des équipes', contenu(vue, prefixe, args['limite']))
                if len(reponse.body) > 131072:
                    raise HTTPException(503, 'Journal trop volumineux')
                autorite._admin(cnx, session)
        except PermissionError:
            raise HTTPException(403, 'Accès admin requis') from None
        except (lecture.Refus, ValueError, KeyError, TypeError):
            raise HTTPException(503, 'Journal indisponible; relire depuis la cédule') from None
        return reponse

    return router
