"""Console privée des prévisions et visites M4, sans déduction de présence individuelle."""
import json
from urllib.parse import urlencode

from m4_field_ops import (
    annotations_calendrier,
    composition_durable,
    encodage,
    etats,
    journal_durable,
    visites_chantier,
    visites_durables,
    visites_ecriture,
)
from m4_field_ops.registre import Registre

from . import memoire_chantier as autorite
from . import pages
from . import preparation_chantier as lecture

M4 = 'm04-field-ops'
NOM = 'm4_lire_visites_console'


def url(intervention_id, prefixe):
    return prefixe + '/crm/visites?' + urlencode({'intervention_id': intervention_id})


def source_consultation(principal, visites, compositions, intervention_id):
    return encodage.empreinte('visites_console_v2', principal.empreinte_snapshot_calculee,
                             visites.empreinte_snapshot_calculee, compositions.empreinte_snapshot_calculee,
                             intervention_id)


def lire(cnx, deps, session, intervention_id, *, debut=0, limite=50, source_attendue=None):
    autorite._admin(cnx, session)
    try:
        p = journal_durable.capturer(cnx)
        v = visites_ecriture.capturer_visites(cnx)
        c = composition_durable.capturer(cnx)
        reg, prev = Registre([x.maillon for x in p.lignes]), Registre([x.maillon for x in v.lignes])
        source_console = source_consultation(p, v, c, intervention_id)
        if (debut and source_attendue is None) or (source_attendue is not None and source_attendue != source_console):
            raise lecture.Refus('SOURCE-MODIFIEE')
        source_m4 = encodage.empreinte('visites_prevues_v1', reg.tete(), prev.tete(), intervention_id)
        arguments = dict(intervention_id=intervention_id, debut=debut, limite=limite,
                         source_attendue=source_m4 if source_attendue is not None else None)
        attendu = visites_durables.lire(reg, prev, **arguments)
        attendu['source_sql'] = encodage.empreinte('visites_sql_v1', p.empreinte_snapshot_calculee,
                                                   v.empreinte_snapshot_calculee)
        if visites_ecriture.empreinte_sources(cnx) != attendu['source_sql']:
            raise lecture.Refus('SOURCE-MODIFIEE')
        obtenu = lecture._appel(deps, session.utilisateur, M4, NOM, arguments)
        if obtenu != attendu:
            raise lecture.Refus('SOURCE-REPONSE-INCOHERENTE')
        attendu['source'] = source_console
        _, courantes = annotations_calendrier._sources(reg)
        attendues = [ligne for ligne in courantes.values()
                     if ligne['intervention_id'] == intervention_id and ligne['validite'] == 'date_confirmee']
        if len(attendues) > 1:
            raise lecture.Refus('ANCRE-AMBIGUE')
        courant = attendues[0] if attendues else None
        sources = {x.maillon['ligne_id']: x.maillon for x in p.lignes}
        rangs = {x.maillon['ligne_id']: n for n, x in enumerate(p.lignes)}
        previsions = {x.maillon['ligne_id']: x.maillon for x in v.lignes}
        ouvertures_liste = [m for m in sources.values()
                            if m.get('type_entree') == 'visite_ouverte' and m.get('intervention_id') == intervention_id]
        fermetures_liste = [m for m in sources.values()
                            if m.get('type_entree') == 'visite_fermee' and m.get('intervention_id') == intervention_id]
        ouvertures = {m['visite_id']: m for m in ouvertures_liste}
        fermetures = {m['visite_id']: m for m in fermetures_liste}
        if (len(ouvertures) != len(ouvertures_liste) or len(fermetures) != len(fermetures_liste)
                or len(ouvertures) > 1000 or len(fermetures) > 1000):
            raise lecture.Refus('SOURCE-VISITE-INVALIDE')
        for ident, m in ouvertures.items():
            prevision_source = previsions.get(ident)
            if (prevision_source is None or prevision_source['ancre']['intervention_id'] != intervention_id
                    or m.get('source_calendrier') != prevision_source['ancre']['source_ligne_id']
                    or m.get('source_application') != prevision_source['ancre']['source_application_id']
                    or m.get('equipe_id') != prevision_source['creneau']['equipe_id']
                    or rangs.get(m['source_calendrier'], len(rangs)) >= rangs[m['ligne_id']]):
                raise lecture.Refus('SOURCE-VISITE-INVALIDE')
        for ident, m in fermetures.items():
            ouverture, depart = ouvertures.get(ident), sources.get(m.get('source_depart'))
            if (ouverture is None or m.get('ouverture_id') != ouverture['ligne_id'] or depart is None
                    or depart.get('type_entree') != 'pointage' or depart.get('action') != 'depart'
                    or depart.get('visite_id') != ident or depart.get('intervention_id') != intervention_id
                    or not rangs[ouverture['ligne_id']] < rangs[depart['ligne_id']] < rangs[m['ligne_id']]):
                raise lecture.Refus('SOURCE-VISITE-INVALIDE')
        # Un ancien pointage sans identité reste consultable dans le journal, jamais attribué.
        anciens = any(m.get('type_entree') == 'pointage' and m.get('intervention_id') == intervention_id
                      and not m.get('visite_id') for m in sources.values())
        active = visites_chantier.visite_active(reg, intervention_id)
        resultat_temps = None
        if fermetures:
            # Une visite ouverte reste inconnue ; seules les sessions fermées sont projetées.
            resultat_temps = visites_chantier.calculer_faits_certifies(
                reg, prev, intervention_id, ignorer_anciens=anciens, omettre_ouverte=True)
        calculs = {x['visite_id']: x for x in resultat_temps['visites']} if resultat_temps else {}
        reports = [m for m in sources.values() if m.get('type_entree') == 'transition_statut'
                   and m.get('intervention_id') == intervention_id and m.get('statut') == 'reportee']
        interruptions = {}
        for report in reports:
            ident = report.get('visite_id')
            if ident is None:  # report historique non rattaché à une visite précise
                continue
            fermeture = fermetures.get(ident)
            if (fermeture is None or ident in interruptions or report.get('motif') not in etats.MOTIFS_REPORT
                    or report.get('source_fermeture') != fermeture['ligne_id']
                    or rangs[fermeture['ligne_id']] >= rangs[report['ligne_id']]):
                raise lecture.Refus('SOURCE-VISITE-INVALIDE')
            interruptions[ident] = {'motif': report['motif'], 'instant': report['horodatage'],
                                     'source': report['ligne_id']}
        for ligne in attendu['visites']:
            ident = ligne['visite_id']
            ligne['etat_visite'] = ('fermee' if ident in fermetures else
                                    'ouverte' if active and ident == active['visite_id'] else 'prevue')
            calc = calculs.get(ident)
            ligne['temps'] = calc
            ligne['interruption'] = interruptions.get(ident)
            ligne['pointages'] = ([{'action': sources[x].get('action'), 'instant': sources[x]['horodatage'],
                                    'technicien_id': sources[x].get('technicien_id'), 'source': x}
                                   for x in calc['sources'] if sources[x].get('type_entree') == 'pointage']
                                  if calc else None)
            jour = ligne['creneau']['debut'][:10]
            equipe = ligne['creneau']['equipe_id']
            composition = composition_durable.projeter(c, jour, equipe)
            declaration = [x.maillon for x in c.lignes if x.maillon.get('jour') == jour
                           and x.maillon.get('equipe_id') == equipe
                           and x.maillon.get('revision') == composition['revision']]
            if composition['revision']:
                if (len(declaration) != 1 or
                        (composition['composition_connue'] and declaration[0]['membres'] != composition['membres'])):
                    raise lecture.Refus('SOURCE-COMPOSITION-INVALIDE')
                composition['declaration_source'] = declaration[0]['ligne_id']
            else:
                composition['declaration_source'] = None
            ligne['composition'] = composition
        attendu['ancre_courante'] = ({k: courant[k] for k in (
            'intervention_id', 'plan_id', 'source_application_id', 'source_ligne_id')} if courant else None)
        attendu['deja_prevue'] = bool(courant and any(
            m.maillon['ancre'] == attendu['ancre_courante'] for m in v.lignes))
        attendu['faits_anciens_non_attribues'] = anciens
        attendu['intervention_id'] = intervention_id
        attendu['limite'] = limite
        attendu['etat_chantier'] = etats.statut_courant(reg, intervention_id)
        attendu['derniere_fermeture'] = fermetures_liste[-1]['visite_id'] if fermetures_liste else None
        attendu['dernier_report'] = reports[-1]['ligne_id'] if reports else None
        attendu['avertissement'] = ('Composition déclarée : elle ne prouve pas la présence individuelle. '
                                    'Sans sources complètes et arbitrées, la durée reste inconnue.')
        if (visites_ecriture.empreinte_sources(cnx) != attendu['source_sql']
                or composition_durable.capturer(cnx).empreinte_snapshot_calculee != c.empreinte_snapshot_calculee):
            raise lecture.Refus('SOURCE-MODIFIEE')
        if len(json.dumps(attendu, ensure_ascii=False).encode()) > 65536:
            raise lecture.Refus('SORTIE-TROP-VOLUMINEUSE')
    except (annotations_calendrier.Refus, journal_durable.Refus) as exc:
        raise lecture.Refus('SOURCE-VISITE-INVALIDE') from exc
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, lecture.Refus):
            raise
        raise lecture.Refus('SOURCE-VISITE-INVALIDE') from exc
    autorite._admin(cnx, session)
    return attendu


def contenu(vue, session, prefixe):
    import uuid

    from . import annotations_cedule_ui, compositions_equipes

    chemin = url(vue['intervention_id'], prefixe)
    corps = (f'<section><h2>Prévisions et visites — {pages.e(vue["intervention_id"])}</h2>'
             f'<p>{pages.e(vue["avertissement"])}</p>'
             '<p>Composition déclarée et présence observée sont distinctes.</p>')
    if vue['faits_anciens_non_attribues']:
        corps += '<p>Ancien pointage sans visite : durée globale inconnue ; voir le journal historique.</p>'
    if vue['etat_chantier'] == 'planifiee' and vue['total']:
        cible = prefixe + '/crm/visites/reprise?' + urlencode({'intervention_id': vue['intervention_id']})
        corps += (f'<p><a href="{pages.e(cible)}">Préparer une proposition de reprise</a>. '
                  'L’ancienne prévision reste dans l’historique.</p>')
    courant = vue['ancre_courante']
    if courant and not vue['deja_prevue']:
        corps += f'<form method="post" action="{pages.e(chemin)}">'
        champs = {**courant, 'operation': 'prevoir', 'revision_attendue': str(vue['total']),
                  'csrf': session.csrf, 'mutation_id': str(uuid.uuid4())}
        corps += ''.join(f'<input type="hidden" name="{pages.e(k)}" value="{pages.e(v)}">'
                         for k, v in champs.items())
        corps += '<button type="submit">Conserver cette prévision comme visite</button></form>'
    if not vue['visites']:
        corps += '<p>Aucune visite conservée sur cette page.</p>'
    for v in vue['visites']:
        creneau, composition = v['creneau'], v['composition']
        jour, equipe = creneau['debut'][:10], creneau['equipe_id']
        corps += (f'<article id="visite-{pages.e(v["visite_id"])}"><h3>Visite {pages.e(v["visite_id"])}</h3>'
                  f'<p>Prévu : {pages.e(creneau["debut"])} – {pages.e(creneau["fin"])} '
                  f'· Équipe prévue : {pages.e(equipe)} · État : {pages.e(v["etat_visite"])}</p>')
        if composition['composition_connue']:
            membres = ', '.join(composition['membres']) or 'Liste explicitement vide'
            corps += (f'<p>Composition déclarée : {pages.e(membres)} '
                      f'(équipe prévue {pages.e(equipe)}, révision {composition["revision"]}, '
                      f'source {pages.e(composition["declaration_source"])}).</p>')
        else:
            corps += '<p>Composition déclarée inconnue.</p>'
            if composition['declaration_source']:
                corps += (f'<p>Déclaration inconnue : révision {composition["revision"]}, '
                          f'source {pages.e(composition["declaration_source"])}.</p>')
        lien = compositions_equipes.url_journal(jour, equipe, prefixe)
        if lien:
            corps += f'<p><a href="{pages.e(lien)}">Composition et historique du jour</a></p>'
        if v['temps'] is None:
            corps += '<p>Temps pointé : inconnu ou non encore vérifié. Consulter le journal du jour.</p>'
        else:
            t = v['temps']
            corps += (f'<p>Pointé : {t["travail_minutes"]} min nettes · pause {t["pause_minutes"]} min '
                      f'· déplacement {t["deplacement_minutes"]} min.</p><ul>')
            for point in v['pointages']:
                corps += (f'<li>{pages.e(point["action"])} · {pages.e(point["instant"])} · '
                          f'{pages.e(point["technicien_id"])} · source {pages.e(point["source"])}</li>')
            corps += '</ul>'
        if v['interruption']:
            interruption = v['interruption']
            corps += (f'<p>Interruption : {pages.e(interruption["motif"])} · {pages.e(interruption["instant"])} '
                      f'· source {pages.e(interruption["source"])}</p>')
        notes_url = annotations_cedule_ui.url(v['ancre'], prefixe)
        corps += f'<p><a href="{pages.e(notes_url)}">Notes de cette prévision</a></p>'
        journal = prefixe + '/crm/journal-equipes?' + urlencode({'jour': jour})
        corps += f'<p><a href="{pages.e(journal)}">Journal de cette journée</a></p>'
        if (v['etat_visite'] == 'fermee' and v['visite_id'] == vue['derniere_fermeture']
                and vue['etat_chantier'] == 'sur_site'):
            champs = {'operation': 'interrompre', 'visite_id': v['visite_id'],
                      'source_attendue': vue['source_sql'], 'csrf': session.csrf, 'mutation_id': str(uuid.uuid4())}
            corps += f'<form method="post" action="{pages.e(chemin)}">'
            corps += ''.join(f'<input type="hidden" name="{pages.e(k)}" value="{pages.e(val)}">'
                             for k, val in champs.items())
            corps += ('<label>Motif <select name="motif"><option value="meteo">Météo</option>'
                      '<option value="client_absent">Client absent</option>'
                      '<option value="decision_admin">Décision administrative</option></select></label>'
                      '<button type="submit">Interrompre le chantier</button></form>')
        if (v['etat_visite'] == 'fermee' and v['visite_id'] == vue['derniere_fermeture']
                and vue['etat_chantier'] == 'reportee' and vue['dernier_report']):
            champs = {'operation': 'replanifier', 'visite_id': v['visite_id'],
                      'report_id': vue['dernier_report'], 'source_attendue': vue['source_sql'],
                      'csrf': session.csrf, 'mutation_id': str(uuid.uuid4())}
            corps += f'<form method="post" action="{pages.e(chemin)}">'
            corps += ''.join(f'<input type="hidden" name="{pages.e(k)}" value="{pages.e(val)}">'
                             for k, val in champs.items())
            corps += ('<button type="submit">Remettre à planifier</button>'
                      '<p>Une nouvelle date doit être confirmée ; l’ancienne reste historique.</p></form>')
        if v['etat_visite'] != 'fermee':
            op = 'fermer' if v['etat_visite'] == 'ouverte' else 'ouvrir'
            champs = {'operation': op, 'visite_id': v['visite_id'], 'source_attendue': vue['source_sql'],
                      'csrf': session.csrf, 'mutation_id': str(uuid.uuid4())}
            corps += f'<form method="post" action="{pages.e(chemin)}">'
            corps += ''.join(f'<input type="hidden" name="{pages.e(k)}" value="{pages.e(val)}">'
                             for k, val in champs.items())
            corps += f'<button type="submit">{op.capitalize()} la visite</button></form>'
        corps += '</article>'
    nav = []
    for debut, libelle in ((max(0, vue['debut'] - vue['limite']), 'Page précédente'),
                            (vue['suivant'], 'Page suivante')):
        if debut is not None and (debut != 0 or vue['debut']):
            cible = chemin + '&' + urlencode({'debut': debut, 'limite': vue['limite'],
                                              'source_attendue': vue['source']})
            nav.append(f'<a href="{pages.e(cible)}">{libelle}</a>')
    return corps + '<nav>' + ' · '.join(nav) + '</nav></section>'


def arguments(params):
    import re

    items = list(params.multi_items())
    if (len(items) != len({k for k, _ in items}) or set(params) -
            {'intervention_id', 'debut', 'limite', 'source_attendue'} or 'intervention_id' not in params):
        raise ValueError('paramètres invalides')
    ident = params['intervention_id']
    if lecture.IDENTIFIANT.fullmatch(ident) is None:
        raise ValueError('intervention invalide')
    valeurs = {}
    for cle, defaut, minimum, maximum in (('debut', '0', 0, 10000), ('limite', '50', 1, 100)):
        brut = params.get(cle, defaut)
        if re.fullmatch(r'0|[1-9][0-9]{0,4}', brut) is None or not minimum <= int(brut) <= maximum:
            raise ValueError('pagination invalide')
        valeurs[cle] = int(brut)
    source = params.get('source_attendue')
    if (source is not None and re.fullmatch(r'[0-9a-f]{64}', source) is None) or (valeurs['debut'] and not source):
        raise ValueError('source invalide')
    return {'intervention_id': ident, **valeurs, 'source_attendue': source}


async def _formulaire(request):
    import uuid
    from urllib.parse import parse_qs

    from fastapi import HTTPException

    if request.headers.get('content-type', '').split(';')[0] != 'application/x-www-form-urlencoded':
        raise HTTPException(415, 'Formulaire requis')
    data = bytearray()
    async for bloc in request.stream():
        data.extend(bloc)
        if len(data) > 12000:
            raise HTTPException(413, 'Formulaire trop volumineux')
    try:
        brut = parse_qs(data.decode('utf-8'), keep_blank_values=True, strict_parsing=True,
                        max_num_fields=10, errors='strict')
        if any(len(v) != 1 for v in brut.values()):
            raise ValueError
        champs = {k: v[0] for k, v in brut.items()}
        if str(uuid.UUID(champs['mutation_id'])) != champs['mutation_id']:
            raise ValueError
        operation = champs.get('operation')
        commun = {'operation', 'csrf', 'mutation_id'}
        if operation == 'prevoir':
            requis = commun | {'intervention_id', 'plan_id', 'source_application_id', 'source_ligne_id',
                               'revision_attendue'}
        elif operation in {'ouvrir', 'fermer'}:
            requis = commun | {'visite_id', 'source_attendue'}
        elif operation == 'replanifier':
            requis = commun | {'visite_id', 'source_attendue', 'report_id'}
        elif operation == 'interrompre':
            requis = commun | {'visite_id', 'source_attendue', 'motif'}
            if champs.get('motif') not in etats.MOTIFS_REPORT:
                raise ValueError
        else:
            raise ValueError
        if set(champs) != requis:
            raise ValueError
        return champs
    except (KeyError, ValueError, UnicodeError):
        raise HTTPException(400, 'Formulaire de visite invalide') from None


def creer_router(*, session_page, cnx_factory, deps, prefixe, rendre, verifier_formulaire):
    from fastapi import APIRouter, HTTPException, Request
    from fastapi.responses import RedirectResponse

    from . import metier

    router = APIRouter()
    from . import reprise_visite
    router.include_router(reprise_visite.creer_router(session_page=session_page, cnx_factory=cnx_factory,
        deps=deps, prefixe=prefixe, rendre=rendre, verifier_formulaire=verifier_formulaire))

    @router.get('/crm/visites')
    def page(request: Request):
        session = session_page(request)
        try:
            args = arguments(request.query_params)
        except (ValueError, TypeError):
            raise HTTPException(400, 'Choisir un chantier et une page valides') from None
        try:
            with cnx_factory() as cnx:
                vue = lire(cnx, deps, session, **args)
                reponse = rendre(session, 'Visites du chantier', contenu(vue, session, prefixe))
                if len(reponse.body) > 131072:
                    raise HTTPException(503, 'Historique trop volumineux')
                autorite._admin(cnx, session)
                return reponse
        except PermissionError:
            raise HTTPException(403, 'Accès admin requis') from None
        except (lecture.Refus, ValueError, KeyError, TypeError):
            raise HTTPException(503, 'Visites indisponibles ; relire la cédule') from None

    @router.post('/crm/visites')
    async def modifier(request: Request):
        session = session_page(request)
        try:
            args = arguments(request.query_params)
            if set(request.query_params) != {'intervention_id'}:
                raise ValueError
        except (ValueError, TypeError):
            raise HTTPException(400, 'Chantier invalide') from None
        champs = await _formulaire(request)
        verifier_formulaire(champs, session)
        if champs['operation'] == 'prevoir':
            ancre = {k: champs[k] for k in ('intervention_id', 'plan_id', 'source_application_id', 'source_ligne_id')}
            if ancre['intervention_id'] != args['intervention_id']:
                raise HTTPException(400, 'Chantier incohérent')
            try:
                revision = int(champs['revision_attendue'])
                if str(revision) != champs['revision_attendue'] or not 0 <= revision <= 10000:
                    raise ValueError
            except ValueError:
                raise HTTPException(400, 'Révision invalide') from None
            nom, payload = 'm4_prevoir_visite_console', {'ancre': ancre, 'revision_attendue': revision}
        elif champs['operation'] == 'replanifier':
            nom, payload = 'm4_replanifier_visite_console', {'intervention_id': args['intervention_id'],
                'visite_id': champs['visite_id'], 'report_id': champs['report_id'],
                'source_attendue': champs['source_attendue']}
        elif champs['operation'] == 'interrompre':
            nom, payload = 'm4_signaler_report', {'intervention_id': args['intervention_id'],
                'motif': champs['motif'], 'visite_id': champs['visite_id'],
                'source_attendue': champs['source_attendue']}
        else:
            nom, payload = 'm4_evenement_visite_console', {k: champs[k] for k in (
                'operation', 'visite_id', 'source_attendue')}
        try:
            with cnx_factory() as cnx:
                autorite._admin(cnx, session)
                with cnx.begin_nested():
                    if champs['operation'] != 'prevoir':
                        ps, vs = journal_durable.capturer(cnx), visites_ecriture.capturer_visites(cnx)
                        _, lignes, _, _, _, _ = visites_durables._charger(
                            Registre([x.maillon for x in ps.lignes]), Registre([x.maillon for x in vs.lignes]))
                        cibles = [m for m in lignes if m['ligne_id'] == champs['visite_id']]
                        if len(cibles) != 1 or cibles[0]['ancre']['intervention_id'] != args['intervention_id']:
                            raise HTTPException(400, 'Visite étrangère à ce chantier')
                    reponse = metier.executer(cnx, deps, session, nom, payload, mutation_id=champs['mutation_id'])
                    res = reponse.get('resultat') if reponse.get('ok') is True else None
                    if not isinstance(res, dict) or res.get('accepte') is not True:
                        raise HTTPException(409, 'Visite modifiée ou opération impossible ; relire le chantier')
                    autorite._admin(cnx, session)
        except PermissionError:
            raise HTTPException(403, 'Accès admin requis') from None
        except (ValueError, KeyError, RuntimeError, annotations_calendrier.Refus, journal_durable.Refus):
            raise HTTPException(503, 'Opération indisponible ; aucune modification confirmée') from None
        return RedirectResponse(url(args['intervention_id'], prefixe), status_code=303)

    return router
