"""Fondation des prévisions identifiées : toutes les données sont fictives."""
import importlib.util
from copy import deepcopy
from pathlib import Path

import pytest
from m4_field_ops import encodage, visites_durables
from m4_field_ops.registre import Registre

spec = importlib.util.spec_from_file_location('fixture_notes_visites',
                                               Path(__file__).with_name('test_annotations_calendrier.py'))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def ecrire(principal, visites, ancre, revision=0, cle='fictif-1', heure=None):
    args = {'ancre': deepcopy(ancre), 'revision_attendue': revision}
    mutation = {'appareil': 'console-fictive', 'cle': cle, 'empreinte_arguments': encodage.empreinte(args)}
    return visites_durables.prevoir(principal, visites, **args, auteur=fixture.AUTEUR,
                                    mutation=mutation, horodatage=fixture.pur.HORODATAGE if heure is None else heure)


def test_prevision_a_ancre_exacte_append_only_et_rejeu():
    principal, visites, ancre, _, _ = fixture.monde()
    avant = principal.lire()
    recu = ecrire(principal, visites, ancre)
    assert recu['rejoue'] is False
    assert principal.lire() == avant
    ligne = visites_durables.lire(principal, Registre(visites.lire()), ancre['intervention_id'])['visites'][0]
    assert ligne['ancre'] == ancre and ligne['visite_id'] == recu['visite_id']
    assert ligne['creneau']['debut'].startswith('2030-06-03T')
    assert ecrire(principal, visites, ancre)['rejoue'] is True
    assert visites.taille() == 1


def test_refuse_ancre_remplacee_et_revision_perimee_sans_ecriture():
    principal, visites, ancre, _, _ = fixture.monde()
    ecrire(principal, visites, ancre)
    with pytest.raises(visites_durables.Refus):
        ecrire(principal, visites, ancre, cle='fictif-2')
    assert visites.taille() == 1
    fixture.calendrier_civil.confirmer(principal, ancre['plan_id'], {'0': '2030-06-10'}, 1,
                                      'admin.fictif', fixture.pur.HORODATAGE)
    with pytest.raises(visites_durables.Refus):
        ecrire(principal, visites, ancre, revision=1, cle='fictif-3')
    assert visites.taille() == 1


def test_deux_previsions_demeurent_distinctes_et_pagination_perimee():
    principal, visites, ancienne, _, _ = fixture.monde()
    first = ecrire(principal, visites, ancienne)
    datee = fixture.calendrier_civil.confirmer(principal, ancienne['plan_id'], {'0': '2030-06-10'}, 1,
                                               'admin.fictif', fixture.pur.HORODATAGE)
    nouvelle = {**ancienne, 'source_ligne_id': datee['ligne_id']}
    seconde = ecrire(principal, visites, nouvelle, revision=1, cle='fictif-2')
    assert first['visite_id'] != seconde['visite_id']
    page = visites_durables.lire(principal, visites, ancienne['intervention_id'], limite=1)
    suite = visites_durables.lire(principal, visites, ancienne['intervention_id'],
                                  debut=page['suivant'], limite=1, source_attendue=page['source'])
    assert [page['visites'][0]['ancre'], suite['visites'][0]['ancre']] == [ancienne, nouvelle]
    fixture.calendrier_civil.confirmer(principal, ancienne['plan_id'], {'0': '2030-06-17'}, 2,
                                      'admin.fictif', fixture.pur.HORODATAGE)
    with pytest.raises(visites_durables.Refus):
        visites_durables.lire(principal, visites, ancienne['intervention_id'], debut=1,
                              source_attendue=page['source'])


def test_registre_semantiquement_altere_meme_rechaine_refuse():
    principal, visites, ancre, _, _ = fixture.monde()
    ecrire(principal, visites, ancre)
    maillon = visites.lire()[0]
    maillon['creneau']['equipe_id'] = 'autre-equipe-fictive'
    rechaine = Registre()
    rechaine.ajouter({k: v for k, v in maillon.items() if k not in {'ligne_id', 'precedent_ligne_id'}})
    with pytest.raises(visites_durables.Refus):
        visites_durables.lire(principal, rechaine, ancre['intervention_id'])


def test_sqlite_reouverture_rejeu_et_rollback_tardif(base_durable):
    from m4_field_ops import visites_ecriture
    from sqlalchemy import func, select

    from opsys import stockage
    from opsys.stockage.schema import JOURNAL
    principal, _, ancre, _, _ = fixture.monde()
    args = {'ancre': ancre, 'revision_attendue': 0}
    mutation = {'appareil': 'console-fictive', 'cle': 'sql-fictif',
                'empreinte_arguments': encodage.empreinte(args)}
    auteur = fixture.AUTEUR
    with stockage.transaction(base_durable) as cnx:
        durable = Registre(stockage.maillons('m04-field-ops', 'principal'))
        for maillon in principal.lire():
            durable.ajouter({k: v for k, v in maillon.items() if k not in {'ligne_id', 'precedent_ligne_id'}})
        recu = visites_ecriture.enregistrer(cnx, args, auteur, mutation, fixture.pur.HORODATAGE,
                                             lambda: auteur)
    stockage.liberer()
    with stockage.transaction(base_durable) as cnx:
        rejoue = visites_ecriture.enregistrer(cnx, args, auteur, mutation, fixture.pur.HORODATAGE,
                                              lambda: auteur)
        assert rejoue['rejoue'] is True and rejoue['visite_id'] == recu['visite_id']
        assert len(stockage.maillons('m04-field-ops', visites_durables.REGISTRE)) == 1
        source = visites_ecriture.capturer_visites(cnx)
        assert source.lignes[0].maillon['ligne_id'] == recu['visite_id']
    # Nouvelle base temporaire non nécessaire : simuler une panne tardive sur une seconde date.
    with stockage.transaction(base_durable) as cnx:
        principal_sql = Registre(stockage.maillons('m04-field-ops', 'principal'))
        datee = fixture.calendrier_civil.confirmer(principal_sql, ancre['plan_id'], {'0': '2030-06-10'}, 1,
                                                   'admin.fictif', fixture.pur.HORODATAGE)
        nouvelle = {**ancre, 'source_ligne_id': datee['ligne_id']}
        args2 = {'ancre': nouvelle, 'revision_attendue': 1}
        mutation2 = {'appareil': 'console-fictive', 'cle': 'sql-fictif-2',
                     'empreinte_arguments': encodage.empreinte(args2)}
        audit_avant = cnx.execute(select(func.count()).select_from(JOURNAL)).scalar_one()
        appels = []
        def autorite():
            appels.append(1)
            return auteur if len(appels) < 2 else {'personne': 'autre-fictif', 'role': 'admin'}
        with pytest.raises(visites_durables.Refus):
            visites_ecriture.enregistrer(cnx, args2, auteur, mutation2, fixture.pur.HORODATAGE, autorite)
        assert len(stockage.maillons('m04-field-ops', visites_durables.REGISTRE)) == 1

        assert cnx.execute(select(func.count()).select_from(JOURNAL)).scalar_one() == audit_avant


def test_ouverture_identifiee_liee_a_prevision_et_unique():
    from m4_field_ops import visites_chantier
    principal, visites, ancre, _, _ = fixture.monde()
    recu = ecrire(principal, visites, ancre)
    avant = principal.lire()
    ouvert = visites_chantier.ouvrir(principal, visites, recu['visite_id'],
                                     '2030-06-03T08:00:00-04:00')
    assert ouvert['visite_id'] == recu['visite_id']
    assert principal.lire()[:-1] == avant
    assert principal.lire()[-1]['type_entree'] == 'visite_ouverte'
    assert principal.lire()[-1]['intervention_id'] == ancre['intervention_id']
    with pytest.raises(ValueError):
        visites_chantier.ouvrir(principal, visites, recu['visite_id'], '2030-06-03T08:01:00-04:00')
    assert len(principal.lire()) == len(avant) + 1


def test_ouverture_refuse_source_remplacee_et_identite_inconnue():
    from m4_field_ops import visites_chantier
    principal, visites, ancre, _, _ = fixture.monde()
    recu = ecrire(principal, visites, ancre)
    fixture.calendrier_civil.confirmer(principal, ancre['plan_id'], {'0': '2030-06-10'}, 1,
                                      'admin.fictif', fixture.pur.HORODATAGE)
    avant = principal.lire()
    for ident in [recu['visite_id'], 'f' * 64]:
        with pytest.raises(ValueError):
            visites_chantier.ouvrir(principal, visites, ident, '2030-06-03T08:00:00-04:00')
    assert principal.lire() == avant


def test_vraies_primitives_attachent_route_et_pointages_a_ouverture():
    from m4_field_ops import cedule, etats, pointage, visites_chantier
    principal, visites, ancre, _, _ = fixture.monde()
    prevision = ecrire(principal, visites, ancre)
    visites_chantier.ouvrir(principal, visites, prevision['visite_id'], '2030-06-03T08:00:00-04:00')
    ligne = visites_durables.lire(principal, visites, ancre['intervention_id'])['visites'][0]
    equipe = ligne['creneau']['equipe_id']
    assign = {'intervention_id': ancre['intervention_id'], 'technicien_id': equipe}
    route, erreur = etats.transitionner(ancre['intervention_id'], 'en_route', principal,
                                        '2030-06-03T08:30:00-04:00', assignation=assign)
    assert erreur is None
    ref = {cedule.tokeniser_ville('sel-fictif', 'Repentigny'): {
        'latitude': 45.75, 'longitude': -73.45, 'rayon_km': 25.0}}
    fenetre = {'debut': '2030-06-03T08:00:00-04:00', 'fin': '2030-06-03T18:00:00-04:00'}
    for action, instant in [('arrivee', '2030-06-03T09:00:00-04:00'),
                            ('pause_debut', '2030-06-03T10:00:00-04:00'),
                            ('pause_fin', '2030-06-03T10:30:00-04:00'),
                            ('depart', '2030-06-03T12:00:00-04:00')]:
        recu, erreur = pointage.enregistrer_pointage(
            ancre['intervention_id'], equipe, action, instant,
            {'latitude': 45.75, 'longitude': -73.45}, {'fictif': True, 'appareil_id': 'fictif'},
            assign, fenetre, ref, 'Repentigny', 'sel-fictif', principal)
        assert erreur is None, erreur
        assert (next(m for m in principal.lire() if m['ligne_id'] == recu['ligne_id'])['visite_id']
                == prevision['visite_id'])
    assert (next(m for m in principal.lire() if m['ligne_id'] == route['ligne_id'])['visite_id']
            == prevision['visite_id'])
    assert visites_chantier.calculer_faits(principal, ancre['intervention_id'])['travail_minutes'] == 150


def test_fermeture_de_session_sans_completion_ni_wct():
    from m4_field_ops import cedule, etats, outbox, pointage, visites_chantier
    principal, visites, ancre, _, _ = fixture.monde()
    prevision = ecrire(principal, visites, ancre)
    iid = ancre['intervention_id']
    visites_chantier.ouvrir(principal, visites, prevision['visite_id'], '2030-06-03T08:00:00-04:00')
    equipe = visites_durables.lire(principal, visites, iid)['visites'][0]['creneau']['equipe_id']
    assign = {'intervention_id': iid, 'technicien_id': equipe}
    assert etats.transitionner(iid, 'en_route', principal, '2030-06-03T08:30:00-04:00', assignation=assign)[1] is None
    ref = {cedule.tokeniser_ville('sel-fictif', 'Repentigny'): {
        'latitude': 45.75, 'longitude': -73.45, 'rayon_km': 25.0}}
    fenetre = {'debut': '2030-06-03T08:00:00-04:00', 'fin': '2030-06-03T18:00:00-04:00'}
    def pointer(action, instant):
        return pointage.enregistrer_pointage(iid, equipe, action, instant,
            {'latitude': 45.75, 'longitude': -73.45}, {'fictif': True, 'appareil_id': 'fictif'},
            assign, fenetre, ref, 'Repentigny', 'sel-fictif', principal)
    assert pointer('arrivee', '2030-06-03T09:00:00-04:00')[1] is None
    avant = principal.lire()
    with pytest.raises(ValueError):
        visites_chantier.fermer(principal, visites, prevision['visite_id'], '2030-06-03T11:00:00-04:00')
    assert principal.lire() == avant
    assert pointer('depart', '2030-06-03T12:00:00-04:00')[1] is None
    fermeture = visites_chantier.fermer(principal, visites, prevision['visite_id'], '2030-06-03T12:01:00-04:00')
    assert fermeture['visite_id'] == prevision['visite_id']
    assert visites_chantier.visite_active(principal, iid) is None
    apres_fermeture = principal.lire()
    assert pointer('depart', '2030-06-03T12:02:00-04:00')[1] is not None
    assert principal.lire() == apres_fermeture
    assert etats.statut_courant(principal, iid) == 'sur_site'
    assert not any('wct' in m for m in principal.lire())
    assert visites_chantier.calculer_faits_certifies(principal, visites, iid)['travail_minutes'] == 180
    assert outbox.calculer_duree_reelle(principal, iid, registre_visites=visites) == (180, None)
    avant = principal.lire()
    with pytest.raises(ValueError):
        visites_chantier.fermer(principal, visites, prevision['visite_id'], '2030-06-03T12:02:00-04:00')
    assert principal.lire() == avant


def test_calcul_certifie_refuse_pointages_orphelins_et_ancre_falsifiee():
    from m4_field_ops import visites_chantier
    principal, visites, ancre, _, _ = fixture.monde()
    prevision = ecrire(principal, visites, ancre)
    visites_chantier.ouvrir(principal, visites, prevision['visite_id'], '2030-06-03T08:00:00-04:00')
    maillons = principal.lire()
    maillons[-1]['source_calendrier'] = 'f' * 64
    rechaine = Registre()
    for m in maillons:
        rechaine.ajouter({k: v for k, v in m.items() if k not in {'ligne_id', 'precedent_ligne_id'}})
    with pytest.raises(ValueError):
        visites_chantier.calculer_faits_certifies(rechaine, visites, ancre['intervention_id'])
    assert visites.taille() == 1


def test_depart_gps_arbitre_garde_la_session_et_sa_preuve():
    from m4_field_ops import cedule, ecarts, etats, pointage, visites_chantier
    principal, visites, ancre, _, _ = fixture.monde()
    prev = ecrire(principal, visites, ancre)
    iid = ancre['intervention_id']
    visites_chantier.ouvrir(principal, visites, prev['visite_id'], '2030-06-03T08:00:00-04:00')
    equipe = visites_durables.lire(principal, visites, iid)['visites'][0]['creneau']['equipe_id']
    assign = {'intervention_id': iid, 'technicien_id': equipe}
    assert etats.transitionner(iid, 'en_route', principal, '2030-06-03T08:30:00-04:00', assignation=assign)[1] is None
    ref = {cedule.tokeniser_ville('sel-fictif', 'Repentigny'): {
        'latitude': 45.75, 'longitude': -73.45, 'rayon_km': 25.0}}
    fenetre = {'debut': '2030-06-03T08:00:00-04:00', 'fin': '2030-06-03T18:00:00-04:00'}
    def pointer(action, instant, gps):
        return pointage.enregistrer_pointage(iid, equipe, action, instant, gps,
            {'fictif': True, 'appareil_id': 'fictif'}, assign, fenetre, ref, 'Repentigny', 'sel-fictif', principal)
    proche, loin = {'latitude': 45.75, 'longitude': -73.45}, {'latitude': 46.81, 'longitude': -71.2}
    assert pointer('arrivee', '2030-06-03T09:00:00-04:00', proche)[1] is None
    assert pointer('depart', '2030-06-03T12:00:00-04:00', proche)[1] is None
    anomalie, erreur = pointer('depart', '2030-06-03T12:05:00-04:00', loin)
    assert erreur is None and anomalie['demande_id']
    with pytest.raises(ValueError):
        visites_chantier.fermer(principal, visites, prev['visite_id'], '2030-06-03T12:06:00-04:00')
    assert ecarts.resoudre_demande(anomalie['demande_id'], 'validee', '2030-06-03T12:10:00-04:00', principal)[1] is None
    visites_chantier.fermer(principal, visites, prev['visite_id'], '2030-06-03T12:11:00-04:00')
    resultat = visites_chantier.calculer_faits_certifies(principal, visites, iid)
    assert resultat['travail_minutes'] == 185
    assert anomalie['ligne_id'] in resultat['visites'][0]['sources']
    bruts = principal.lire()
    resolution = next(m for m in bruts if m.get('type_entree') == 'resolution_revue')
    resolution['decision'] = 'rejetee'
    rechaine = Registre()
    for m in bruts:
        rechaine.ajouter({k: v for k, v in m.items() if k not in {'ligne_id', 'precedent_ligne_id'}})
    with pytest.raises(ValueError):
        visites_chantier.calculer_faits_certifies(rechaine, visites, iid)


def test_reprise_lundi_vendredi_avec_un_seul_wct_et_minutes_reelles():
    from m4_field_ops import cedule, etats, outbox, pointage, visites_chantier
    principal, ids, positions = fixture.pur._monde(leads=('ch-01',))
    plan_initial = fixture.pur._reussi(fixture.pur._proposer(principal, ids, positions))['plan_id']
    fixture.pur._reussi(fixture.cedule_tournees.appliquer(principal, plan_initial, positions,
                        fixture.pur.HORODATAGE, 'admin.fictif'))
    fixture.calendrier_civil.confirmer(principal, plan_initial, {'0': '2030-06-03'}, 0,
                                      'admin.fictif', fixture.pur.HORODATAGE)
    ligne = fixture.calendrier_civil.lire_semaine(principal, '2030-06-03')['interventions'][0]
    ancre = {k: ligne[k] for k in fixture.CHAMPS_ANCRE}
    visites = Registre()
    iid = ancre['intervention_id']
    equipe = fixture.notes._creneau(fixture.notes._sources(principal), ancre)['equipe_id']
    ref = {cedule.tokeniser_ville('sel-fictif', 'Repentigny'): {
        'latitude': 45.75, 'longitude': -73.45, 'rayon_km': 25.0}}
    gps = {'latitude': 45.75, 'longitude': -73.45}
    def session(ancre_jour, revision, cle, jour, pauses):
        prev = ecrire(principal, visites, ancre_jour, revision=revision, cle=cle, heure=f'{jour}T07:30:00-04:00')
        equipe_jour = fixture.notes._creneau(fixture.notes._sources(principal), ancre_jour)['equipe_id']
        assign = {'intervention_id': iid, 'technicien_id': equipe_jour}
        visites_chantier.ouvrir(principal, visites, prev['visite_id'], f'{jour}T08:00:00-04:00')
        assert etats.transitionner(iid, 'en_route', principal, f'{jour}T08:30:00-04:00', assignation=assign)[1] is None
        fenetre = {'debut': f'{jour}T08:00:00-04:00', 'fin': f'{jour}T18:00:00-04:00'}
        actions = [('arrivee', '09:00:00'), *pauses, ('depart', '12:00:00' if pauses else '13:00:00')]
        for action, heure in actions:
            recu, erreur = pointage.enregistrer_pointage(iid, equipe_jour, action, f'{jour}T{heure}-04:00', gps,
                {'fictif': True, 'appareil_id': 'fictif'}, assign, fenetre, ref,
                'Repentigny', 'sel-fictif', principal)
            assert erreur is None, erreur
        visites_chantier.fermer(principal, visites, prev['visite_id'], f'{jour}T{actions[-1][1][:2]}:01:00-04:00')
    session(ancre, 0, 'lundi-fictif', '2030-06-03', [('pause_debut', '10:00:00'), ('pause_fin', '10:30:00')])
    recu, erreur = etats.transitionner(iid, 'reportee', principal, '2030-06-03T12:02:00-04:00',
                                        motif='meteo', registre_visites=visites)
    assert erreur is None, erreur
    assert not outbox.lire_outbox(principal)
    assert etats.transitionner(iid, 'planifiee', principal, '2030-06-03T12:03:00-04:00')[1] is None
    autre_equipe = next(e for e in fixture.pur._aide._equipes() if e['id'] != equipe)
    args = fixture.pur._aide._arguments(ids, equipes=[autre_equipe])
    plan = fixture.pur._reussi(fixture.pur._proposer(principal, ids, positions, args))['plan_id']
    fixture.pur._reussi(fixture.cedule_tournees.appliquer(principal, plan, positions,
                        '2030-06-03T12:04:00-04:00', 'admin.fictif'))
    datee = fixture.calendrier_civil.confirmer(principal, plan, {'0': '2030-06-07'}, 0,
                                               'admin.fictif', '2030-06-03T12:05:00-04:00')
    seconde_ancre = {'intervention_id': iid, 'plan_id': plan,
                      'source_application_id': next(m['source_application_id'] for m in principal.lire()
                                                    if m.get('ligne_id') == datee['ligne_id']),
                      'source_ligne_id': datee['ligne_id']}
    session(seconde_ancre, 1, 'vendredi-fictif', '2030-06-07', [])
    resultat = visites_chantier.calculer_faits_certifies(principal, visites, iid)
    assert (resultat['travail_minutes'], resultat['pause_minutes'], resultat['deplacement_minutes']) == (390, 30, 60)
    avant_completion = principal.lire()
    assert outbox.completer_intervention(iid, '2030-06-07T13:02:00-04:00', principal,
                                        ecart_detecte=False)[1] is not None
    assert principal.lire() == avant_completion
    assert outbox.completer_intervention(iid, '2030-06-07T13:00:00-04:00', principal,
                                        ecart_detecte=False, registre_visites=visites)[1] is not None
    assert principal.lire() == avant_completion
    accuse, erreur = outbox.completer_intervention(iid, '2030-06-07T13:02:00-04:00', principal,
                                                    ecart_detecte=False, registre_visites=visites)
    assert erreur is None, erreur
    assert len(outbox.lire_outbox(principal)) == 1
    assert outbox.lire_outbox(principal)[0][1]['duree_reelle_minutes'] == 390
    assert outbox.lire_outbox(principal)[0][1]['technicien_id'] == autre_equipe['id']
    assert autre_equipe['id'] != equipe
    assert outbox.completer_intervention(iid, '2030-06-07T13:03:00-04:00', principal,
                                        ecart_detecte=False, registre_visites=visites)[1] is not None


def test_prevision_ne_peut_predater_sa_source_civile():
    principal, visites, ancre, _, _ = fixture.monde()
    datee = fixture.calendrier_civil.confirmer(principal, ancre['plan_id'], {'0': '2030-06-10'}, 1,
                                               'admin.fictif', '2030-02-01T00:00:00+00:00')
    nouvelle = {**ancre, 'source_ligne_id': datee['ligne_id']}
    with pytest.raises(visites_durables.Refus):
        ecrire(principal, visites, nouvelle, heure='2030-01-01T00:00:00+00:00')
    assert visites.taille() == 0


def test_ouverture_sqlite_cas_rejeu_et_revocation_tardive(base_durable):
    from m4_field_ops import visites_ecriture
    from sqlalchemy import func, select

    from opsys import stockage
    from opsys.stockage.schema import JOURNAL

    principal, _, ancre, _, _ = fixture.monde()
    auteur = fixture.AUTEUR
    with stockage.transaction(base_durable) as cnx:
        durable = Registre(stockage.maillons('m04-field-ops', 'principal'))
        for m in principal.lire():
            durable.ajouter({k: v for k, v in m.items() if k not in {'ligne_id', 'precedent_ligne_id'}})
        args = {'ancre': ancre, 'revision_attendue': 0}
        mutation = {'appareil': 'console-fictive', 'cle': 'prevision-fictive',
                    'empreinte_arguments': encodage.empreinte(args)}
        prev = visites_ecriture.enregistrer(cnx, args, auteur, mutation, fixture.pur.HORODATAGE, lambda: auteur)
    with stockage.transaction(base_durable) as cnx:
        source = visites_ecriture.empreinte_sources(cnx)
        args = {'operation': 'ouvrir', 'visite_id': prev['visite_id'], 'source_attendue': source}
        mutation = {'appareil': 'console-fictive', 'cle': 'ouvrir-fictif',
                    'empreinte_arguments': encodage.empreinte(args)}
        audit_avant = cnx.execute(select(func.count()).select_from(JOURNAL)).scalar_one()
        appels = []
        def revoque():
            appels.append(1)
            return auteur if len(appels) < 2 else {'personne': 'autre-fictif', 'role': 'admin'}
        with pytest.raises(visites_durables.Refus):
            visites_ecriture.executer_evenement(cnx, args, auteur, mutation, '2030-06-03T08:00:00-04:00', revoque)
        assert not any(m['type_entree'] == 'visite_ouverte' for m in stockage.maillons('m04-field-ops', 'principal'))
        assert cnx.execute(select(func.count()).select_from(JOURNAL)).scalar_one() == audit_avant
        result = visites_ecriture.executer_evenement(cnx, args, auteur, mutation, '2030-06-03T08:00:00-04:00',
                                                       lambda: auteur)
        assert result['rejoue'] is False
    stockage.liberer()
    with stockage.transaction(base_durable) as cnx:
        rejoue = visites_ecriture.executer_evenement(cnx, args, auteur, mutation, '2030-06-03T08:01:00-04:00',
                                                       lambda: auteur)
        assert rejoue['rejoue'] is True and rejoue['resultat'] == result['resultat']
        with pytest.raises(visites_durables.Refus):
            visites_ecriture.executer_evenement(cnx, args, auteur, mutation, '2030-06-03T08:01:00-04:00',
                                                lambda: auteur, limite_sortie=1)
        autres = {**args, 'source_attendue': 'f' * 64}
        mutation2 = {'appareil': 'console-fictive', 'cle': 'source-perimee',
                     'empreinte_arguments': encodage.empreinte(autres)}
        with pytest.raises(visites_durables.Refus):
            visites_ecriture.executer_evenement(cnx, autres, auteur, mutation2, '2030-06-03T08:02:00-04:00',
                                                lambda: auteur)
        args_collision = {'ancre': ancre, 'revision_attendue': 1}
        meme_cle = {'appareil': 'console-fictive', 'cle': 'ouvrir-fictif',
                    'empreinte_arguments': encodage.empreinte(args_collision)}
        with pytest.raises(visites_durables.Refus, match='MUTATION-CONFLIT'):
            visites_ecriture.enregistrer(cnx, args_collision, auteur, meme_cle,
                                         '2030-06-03T08:03:00-04:00', lambda: auteur)
        from m4_field_ops import cedule, etats, pointage
        reg = Registre(stockage.maillons('m04-field-ops', 'principal'))
        prev_reg = Registre(stockage.maillons('m04-field-ops', visites_durables.REGISTRE))
        equipe = visites_durables.lire(reg, prev_reg, ancre['intervention_id'])['visites'][0]['creneau']['equipe_id']
        assign = {'intervention_id': ancre['intervention_id'], 'technicien_id': equipe}
        assert etats.transitionner(ancre['intervention_id'], 'en_route', reg,
                                   '2030-06-03T08:30:00-04:00', assignation=assign)[1] is None
        ref = {cedule.tokeniser_ville('sel-fictif', 'Repentigny'): {
            'latitude': 45.75, 'longitude': -73.45, 'rayon_km': 25.0}}
        fenetre = {'debut': '2030-06-03T08:00:00-04:00', 'fin': '2030-06-03T18:00:00-04:00'}
        for action, instant in [('arrivee', '2030-06-03T09:00:00-04:00'),
                                ('depart', '2030-06-03T12:00:00-04:00')]:
            assert pointage.enregistrer_pointage(ancre['intervention_id'], equipe, action, instant,
                {'latitude': 45.75, 'longitude': -73.45}, {'fictif': True, 'appareil_id': 'fictif'},
                assign, fenetre, ref, 'Repentigny', 'sel-fictif', reg)[1] is None
        fermer_args = {'operation': 'fermer', 'visite_id': prev['visite_id'],
                        'source_attendue': visites_ecriture.empreinte_sources(cnx)}
        fermer_mutation = {'appareil': 'console-fictive', 'cle': 'fermer-fictif',
                            'empreinte_arguments': encodage.empreinte(fermer_args)}
        ferme = visites_ecriture.executer_evenement(cnx, fermer_args, auteur, fermer_mutation,
                                                    '2030-06-03T12:01:00-04:00', lambda: auteur)
        assert ferme['rejoue'] is False
    stockage.liberer()
    with stockage.transaction(base_durable) as cnx:
        rejoue_fin = visites_ecriture.executer_evenement(cnx, fermer_args, auteur, fermer_mutation,
                                                          '2030-06-03T12:02:00-04:00', lambda: auteur)
        assert rejoue_fin['rejoue'] is True and rejoue_fin['resultat'] == ferme['resultat']
        assert len([m for m in stockage.maillons('m04-field-ops', 'principal')
                    if m['type_entree'] == 'visite_fermee']) == 1
        from m4_field_ops import visites_chantier
        principal_relu = Registre(stockage.maillons('m04-field-ops', 'principal'))
        visites_relues = Registre(stockage.maillons('m04-field-ops', visites_durables.REGISTRE))
        assert visites_chantier.calculer_faits_certifies(
            principal_relu, visites_relues, ancre['intervention_id'])['travail_minutes'] == 180
