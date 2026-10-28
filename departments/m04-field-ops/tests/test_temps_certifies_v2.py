"""M4 V2 : scénarios et identités entièrement fictifs ; aucun calcul économique."""
import importlib.util
from pathlib import Path

import pytest
from m4_field_ops import calendrier_civil, cedule, cedule_tournees, encodage, etats, outbox, pointage, visites_chantier
from m4_field_ops.registre import Registre

from opsys import contexte, identite, stockage

_spec = importlib.util.spec_from_file_location(
    'fixture_visites_v2', Path(__file__).with_name('test_visites_reprise.py'))
_base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_base)


@pytest.fixture
def chantier_termine(base_durable):
    initial, ids, positions = _base.fixture.pur._monde(leads=('ch-01',))
    with stockage.transaction(base_durable) as cnx:
        identite.creer_personne(cnx, 'admin.fictif', 'Admin fictif', 'Fictif#12345678', roles=['admin'])
        principal = Registre(stockage.maillons('m04-field-ops', 'principal'))
        for m in initial.lire():
            principal.ajouter({k: v for k, v in m.items() if k not in {'ligne_id', 'precedent_ligne_id'}})
        plan1 = _base.fixture.pur._reussi(_base.fixture.pur._proposer(principal, ids, positions))['plan_id']
        _base.fixture.pur._reussi(cedule_tournees.appliquer(principal, plan1, positions,
                                                           _base.fixture.pur.HORODATAGE, 'admin.fictif'))
        calendrier_civil.confirmer(principal, plan1, {'0': '2030-06-03'}, 0,
                                   'admin.fictif', _base.fixture.pur.HORODATAGE)
        ligne = calendrier_civil.lire_semaine(principal, '2030-06-03')['interventions'][0]
        ancre = {k: ligne[k] for k in _base.fixture.CHAMPS_ANCRE}
        iid, equipe = ancre['intervention_id'], ligne['equipe_id']
        visites = Registre(stockage.maillons('m04-field-ops', 'visites_chantier'))
        ref = {cedule.tokeniser_ville('sel-fictif', 'Repentigny'): {
            'latitude': 45.75, 'longitude': -73.45, 'rayon_km': 25.0}}
        def executer(ancre_jour, revision, cle, jour, pauses):
            prev = _base.ecrire(principal, visites, ancre_jour, revision=revision, cle=cle,
                                heure=f'{jour}T07:30:00-04:00')
            equipe_jour = _base.fixture.notes._creneau(_base.fixture.notes._sources(principal), ancre_jour)['equipe_id']
            assign = {'intervention_id': iid, 'technicien_id': equipe_jour}
            visites_chantier.ouvrir(principal, visites, prev['visite_id'], f'{jour}T08:00:00-04:00')
            assert etats.transitionner(iid, 'en_route', principal, f'{jour}T08:30:00-04:00',
                                      assignation=assign)[1] is None
            fenetre = {'debut': f'{jour}T08:00:00-04:00', 'fin': f'{jour}T18:00:00-04:00'}
            actions = [('arrivee', '09:00:00'), *pauses, ('depart', '12:00:00' if pauses else '13:00:00')]
            for action, heure in actions:
                _, erreur = pointage.enregistrer_pointage(iid, equipe_jour, action, f'{jour}T{heure}-04:00',
                    {'latitude': 45.75, 'longitude': -73.45}, {'fictif': True, 'appareil_id': 'fictif'},
                    assign, fenetre, ref, 'Repentigny', 'sel-fictif', principal)
                assert erreur is None, erreur
            visites_chantier.fermer(principal, visites, prev['visite_id'], f'{jour}T{actions[-1][1][:2]}:01:00-04:00')
            return equipe_jour
        equipe1 = executer(ancre, 0, 'lundi-fictif', '2030-06-03',
                            [('pause_debut', '10:00:00'), ('pause_fin', '10:30:00')])
        assert etats.transitionner(iid, 'reportee', principal, '2030-06-03T12:02:00-04:00',
                                    motif='meteo', registre_visites=visites)[1] is None
        assert etats.transitionner(iid, 'planifiee', principal, '2030-06-03T12:03:00-04:00')[1] is None
        equipe2 = next(e for e in _base.fixture.pur._aide._equipes() if e['id'] != equipe)
        plan_args = _base.fixture.pur._aide._arguments(ids, equipes=[equipe2])
        plan2 = _base.fixture.pur._reussi(_base.fixture.pur._proposer(principal, ids, positions, plan_args))['plan_id']
        _base.fixture.pur._reussi(cedule_tournees.appliquer(principal, plan2, positions,
                                                           '2030-06-03T12:04:00-04:00', 'admin.fictif'))
        datee = calendrier_civil.confirmer(principal, plan2, {'0': '2030-06-07'}, 0,
                                           'admin.fictif', '2030-06-03T12:05:00-04:00')
        ancre2 = {'intervention_id': iid, 'plan_id': plan2,
                  'source_application_id': next(m['source_application_id'] for m in principal.lire()
                                                if m.get('ligne_id') == datee['ligne_id']),
                  'source_ligne_id': datee['ligne_id']}
        equipe2_id = executer(ancre2, 1, 'vendredi-fictif', '2030-06-07', [])
        accuse, erreur = outbox.completer_intervention(iid, '2030-06-07T13:02:00-04:00', principal,
            ecart_detecte=False, verification_en_attente=True, registre_visites=visites)
        assert erreur is None, erreur
    return {'url': base_durable, 'iid': iid, 'wct_id': accuse['wct_id'], 'equipes': [equipe1, equipe2_id]}


def _appel(cnx, cas, **kwargs):
    from m4_field_ops import temps_certifies_v2
    with (contexte.appele_par_appareil(contexte.IdentiteAppelante('admin.fictif', 'admin', source='console')),
          contexte.appeler_en_tant_que('m04-field-ops', origine='console')):
        return temps_certifies_v2.projeter(cnx, cas['iid'], cas['wct_id'], **kwargs)


def test_projection_lundi_vendredi_liee_au_wct_et_relue(chantier_termine):
    import json

    cas = chantier_termine
    with stockage.transaction(cas['url']) as cnx:
        resultat = _appel(cnx, cas)
        projection = resultat['projection']
        modele = json.loads((Path(__file__).parents[3] / 'docs/grs/crm/CRM01-17-FIXTURE-TEMPS-V2.json')
                            .read_text())['projection']
        assert set(projection) == set(modele)
        assert all(set(projection[k]) == set(modele[k]) for k in ('wct', 'sources', 'totaux', 'revue_chantier'))
        for visite in projection['visites']:
            assert set(visite) == set(modele['visites'][0])
            for champ in ('ancre', 'equipe_pointee', 'ouverture', 'fermeture', 'composition_declaree',
                          'presence_individuelle', 'minutes'):
                assert set(visite[champ]) == set(modele['visites'][0][champ])
            assert all(set(e) == set(modele['visites'][0]['evenements'][0]) for e in visite['evenements'])
        assert projection['wct']['wct_id'] == cas['wct_id']
        assert projection['totaux'] == {'travail': 390, 'pause': 30, 'deplacement': 60}
        assert [v['minutes']['travail'] for v in projection['visites']] == [150, 240]
        assert [v['identifiant_pointe'] for v in projection['visites']] == cas['equipes']
        assert all(v['presence_individuelle'] == {'statut': 'inconnue'} for v in projection['visites'])
        assert projection['empreinte'] == encodage.empreinte('m4.temps_certifies.v2',
            {k: v for k, v in projection.items() if k != 'empreinte'})
    stockage.liberer()
    with stockage.transaction(cas['url']) as cnx:
        relu = _appel(cnx, cas, source_attendue=resultat['source'])
        assert relu == resultat


def test_projection_refuse_identite_source_perimee_et_wct_inconnu(chantier_termine):
    from m4_field_ops import temps_certifies_v2
    from sqlalchemy import select

    from opsys.stockage.schema import META

    cas = chantier_termine
    with stockage.transaction(cas['url']) as cnx:
        def toutes_tables():
            return tuple((table.name, tuple(tuple(row) for row in cnx.execute(select(table)).all()))
                         for table in META.sorted_tables)
        avant = toutes_tables()
        with pytest.raises(temps_certifies_v2.Refus, match='IDENTITE'):
            temps_certifies_v2.projeter(cnx, cas['iid'], cas['wct_id'])
        with pytest.raises(temps_certifies_v2.Refus, match='SOURCE-PERIMEE'):
            _appel(cnx, cas, source_attendue='f' * 64)
        with pytest.raises(temps_certifies_v2.Refus, match='WCT-ABSENT-OU-AMBIGU'):
            _appel(cnx, {**cas, 'wct_id': 'f' * 64})
        assert toutes_tables() == avant
        identite.retirer_role(cnx, 'admin.fictif', 'admin')
        apres_retrait = toutes_tables()
        with pytest.raises(temps_certifies_v2.Refus, match='IDENTITE'):
            _appel(cnx, cas)
        assert toutes_tables() == apres_retrait


def test_declaration_est_sourcee_et_ne_devient_pas_presence(chantier_termine):
    from m4_field_ops import composition_journaliere, temps_certifies_v2

    cas = chantier_termine
    with stockage.transaction(cas['url']) as cnx:
        avant = _appel(cnx, cas)
        compositions = Registre(stockage.maillons('m04-field-ops', composition_journaliere.REGISTRE))
        args = {'jour': '2030-06-03', 'equipe_id': cas['equipes'][0], 'membres': ['membre.fictif'],
                'revision_attendue': 0, 'statut_declaration': 'declaree'}
        recu = composition_journaliere.declarer(compositions, **args,
            auteur={'personne': 'admin.fictif', 'role': 'admin'},
            mutation={'appareil': 'fictif', 'cle': 'composition-v2-fictive',
                      'empreinte_arguments': encodage.empreinte(args)},
            horodatage='2030-06-08T08:00:00-04:00')
        with pytest.raises(temps_certifies_v2.Refus, match='SOURCE-PERIMEE'):
            _appel(cnx, cas, source_attendue=avant['source'])
        apres = _appel(cnx, cas)
        lundi, vendredi = apres['projection']['visites']
        assert lundi['composition_declaree']['source_ligne_id'] == recu['resultat']['declaration_id']
        assert lundi['composition_declaree']['membres'] == ['membre.fictif']
        assert lundi['composition_declaree']['horodatage'] == '2030-06-08T08:00:00-04:00'
        assert lundi['presence_individuelle'] == {'statut': 'inconnue'}
        assert vendredi['composition_declaree']['statut'] == 'inconnue'
        assert apres['projection']['totaux']['travail'] == 390


def test_source_ou_autorite_changee_en_fin_de_lecture_refuse(chantier_termine, monkeypatch):
    from dataclasses import replace

    from m4_field_ops import temps_certifies_v2

    cas = chantier_termine
    original = temps_certifies_v2._sources
    appels = []
    def changer(cnx):
        snapshots = original(cnx)
        appels.append(1)
        if len(appels) == 2:
            snapshots = (snapshots[0], snapshots[1], replace(snapshots[2], empreinte_snapshot_calculee='f' * 64))
        return snapshots
    with stockage.transaction(cas['url']) as cnx, monkeypatch.context() as patch:
        patch.setattr(temps_certifies_v2, '_sources', changer)
        with pytest.raises(temps_certifies_v2.Refus, match='SOURCE-MODIFIEE'):
            _appel(cnx, cas)
    original_autorite = temps_certifies_v2._autoriser
    appels.clear()
    def revoquer(cnx):
        appels.append(1)
        if len(appels) == 2:
            identite.retirer_role(cnx, 'admin.fictif', 'admin')
        return original_autorite(cnx)
    with (pytest.raises(temps_certifies_v2.Refus, match='IDENTITE'),
          stockage.transaction(cas['url']) as cnx, monkeypatch.context() as patch):
        patch.setattr(temps_certifies_v2, '_autoriser', revoquer)
        _appel(cnx, cas)


def test_connexion_etrangere_et_sortie_trop_petite_refusees(chantier_termine):
    from m4_field_ops import temps_certifies_v2
    from sqlalchemy import create_engine

    cas = chantier_termine
    moteur = create_engine(cas['url'])
    try:
        with (stockage.transaction(cas['url']), moteur.connect() as etrangere,
              pytest.raises(temps_certifies_v2.Refus, match='INSTANCE-NON-QUALIFIEE')):
            _appel(etrangere, cas)
        with (stockage.transaction(cas['url']) as cnx, contexte.sortie_bornee(1),
              pytest.raises(temps_certifies_v2.Refus, match='SORTIE-TROP-VOLUMINEUSE')):
            _appel(cnx, cas)
    finally:
        moteur.dispose()


def test_wct_rechaine_avec_lead_falsifie_refuse(chantier_termine):
    from dataclasses import replace

    from m4_field_ops import temps_certifies_v2

    cas = chantier_termine
    with stockage.transaction(cas['url']) as cnx:
        captures = temps_certifies_v2._sources(cnx)
        change = Registre()
        lignes = []
        for ligne in captures[0].lignes:
            m = {k: v for k, v in ligne.maillon.items() if k not in {'ligne_id', 'precedent_ligne_id'}}
            if 'wct' in m:
                m = {**m, 'wct': {**m['wct'], 'lead_id': 'autre-lead-fictif'}}
            change.ajouter(m)
            lignes.append(replace(ligne, maillon=change.lire()[-1]))
        falsifie = replace(captures[0], lignes=tuple(lignes))
        with pytest.raises(temps_certifies_v2.Refus, match='WCT-INVALIDE'):
            temps_certifies_v2._projection('instance-fictive', cas['iid'], cas['wct_id'],
                                            (falsifie, captures[1], captures[2]))


@pytest.mark.parametrize(('source', 'origine', 'mcp'), [
    ('appareil', 'console', False), ('console', 'm04-field-ops', False), ('console', 'console', True),
])
def test_export_refuse_transport_non_console(chantier_termine, source, origine, mcp):
    from contextlib import nullcontext

    from m4_field_ops import temps_certifies_v2

    cas = chantier_termine
    appelante = contexte.IdentiteAppelante('admin.fictif', 'admin', source=source)
    with (stockage.transaction(cas['url']) as cnx, contexte.appele_par_appareil(appelante),
          contexte.appeler_en_tant_que('m04-field-ops', origine=origine),
          contexte.transport_mcp() if mcp else nullcontext(),
          pytest.raises(temps_certifies_v2.Refus, match='IDENTITE')):
        temps_certifies_v2.projeter(cnx, cas['iid'], cas['wct_id'])


def test_revue_verifiee_ne_modifie_pas_le_wct_et_invalide_le_cas(chantier_termine):
    from m4_field_ops import temps_certifies_v2

    cas = chantier_termine
    with stockage.transaction(cas['url']) as cnx:
        avant = _appel(cnx, cas)
        assert avant['projection']['revue_chantier']['statut'] == 'en_attente'
        principal = Registre(stockage.maillons('m04-field-ops', 'principal'))
        recu, erreur = outbox.confirmer_verification(cas['iid'], '2030-06-07T13:03:00-04:00', principal,
                                                       evenement_id_variance='variance-fictive')
        assert erreur is None
        assert recu['statut'] == 'completed_verified'
        with pytest.raises(temps_certifies_v2.Refus, match='SOURCE-PERIMEE'):
            _appel(cnx, cas, source_attendue=avant['source'])
        apres = _appel(cnx, cas)
        assert apres['projection']['revue_chantier']['statut'] == 'verifiee'
        assert apres['projection']['revue_chantier']['source_ligne_id'] != avant['projection']['wct']['source_ligne_id']
        assert apres['projection']['wct'] == avant['projection']['wct']
        assert apres['projection']['totaux'] == avant['projection']['totaux']


def test_egalite_identifiant_personne_et_equipe_ne_prouve_pas_type_equipe(chantier_termine):
    cas = chantier_termine
    with stockage.transaction(cas['url']) as cnx:
        # Le domaine autorise explicitement une personne homonyme d'une équipe.
        identite.creer_personne(cnx, cas['equipes'][0], 'Personne fictive homonyme', 'Fictif#12345678')
        projection = _appel(cnx, cas)['projection']
        lundi = projection['visites'][0]
        assert lundi['identifiant_pointe'] == lundi['equipe_planifiee_id']
        assert lundi['equipe_pointee']['statut'] == 'inconnue'
        assert lundi['equipe_pointee']['identifiant'] is None
        assert {'code': 'equipe_pointee_indeterminee', 'visite_id': lundi['visite_id']} in projection['inconnus']


def test_wct_rechaine_avec_etat_precedent_impossible_refuse(chantier_termine):
    from dataclasses import replace

    from m4_field_ops import temps_certifies_v2

    cas = chantier_termine
    with stockage.transaction(cas['url']) as cnx:
        captures = temps_certifies_v2._sources(cnx)
        change, lignes = Registre(), []
        for ligne in captures[0].lignes:
            m = {k: v for k, v in ligne.maillon.items() if k not in {'ligne_id', 'precedent_ligne_id'}}
            if 'wct' in m:
                m = {**m, 'statut_precedent': 'annulee'}
                transition = {k: v for k, v in m.items() if k != 'wct'}
                m['wct'] = {**m['wct'], 'hash_maillon': encodage.empreinte(transition)}
            change.ajouter(m)
            lignes.append(replace(ligne, maillon=change.lire()[-1]))
        falsifie = replace(captures[0], lignes=tuple(lignes))
        with pytest.raises(temps_certifies_v2.Refus):
            temps_certifies_v2._projection('instance-fictive', cas['iid'], cas['wct_id'],
                                            (falsifie, captures[1], captures[2]))


def test_transition_verifiee_sans_justification_refusee(chantier_termine):
    from m4_field_ops import temps_certifies_v2

    cas = chantier_termine
    with stockage.transaction(cas['url']) as cnx:
        principal = Registre(stockage.maillons('m04-field-ops', 'principal'))
        principal.ajouter({'type_entree': 'transition_statut', 'intervention_id': cas['iid'],
                          'statut_precedent': 'completed_pending_review', 'statut': 'completed_verified',
                          'horodatage': '2030-06-07T13:03:00-04:00'})
        with pytest.raises(temps_certifies_v2.Refus):
            _appel(cnx, cas)
