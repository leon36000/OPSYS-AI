"""Les faits anciens restent sans visite ; une identité falsifiée est refusée."""
import importlib.util
from pathlib import Path

from m4_field_ops.registre import Registre

from opsys import stockage

spec = importlib.util.spec_from_file_location('journal_visites_fixture',
    Path(__file__).with_name('test_console_cedule.py'))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
client_crm, planning = f.client_crm, f.planning


def test_ancien_sans_identite_et_fait_falsifie(client_crm, planning, session):
    _, ids, _, _ = planning
    iid = ids['lead-fictif-001']
    f.base._connecter(client_crm, 'admin.fictif')
    with session():
        reg = Registre(stockage.maillons('m04-field-ops', 'principal'))
        reg.ajouter({'type_entree': 'pointage', 'intervention_id': iid, 'technicien_id': 'ancien.fictif',
                     'action': 'arrivee', 'horodatage': '2030-06-03T09:00:00-04:00'})
    page = client_crm.get('/crm/journal-equipes?jour=2030-06-03')
    assert page.status_code == 200 and 'ancien.fictif' in page.text
    assert 'Aucune ancre de visite démontrée' in page.text and '#visite-' not in page.text
    with session():
        reg = Registre(stockage.maillons('m04-field-ops', 'principal'))
        reg.ajouter({'type_entree': 'pointage', 'intervention_id': iid, 'technicien_id': 'fictif',
                     'action': 'depart', 'horodatage': '2030-06-03T10:00:00-04:00', 'visite_id': 'a' * 64})
    page = client_crm.get('/crm/journal-equipes?jour=2030-06-03')
    assert page.status_code == 503 and 'Visite identifiée' not in page.text


def test_snapshot_visites_modifie_pendant_lecture_refuse(client_crm, planning, session, monkeypatch):
    from datetime import timedelta

    from sqlalchemy import select

    from opsys.console import journal_visites
    from opsys.stockage.schema import REGISTRES

    f.base._connecter(client_crm, 'admin.fictif')
    # Une prévision explicite durable permet de modifier une métadonnée sans réécrire son fait.
    from m4_field_ops import calendrier_civil, encodage, visites_durables
    with session():
        reg = Registre(stockage.maillons('m04-field-ops', 'principal'))
        prev = Registre(stockage.maillons('m04-field-ops', visites_durables.REGISTRE))
        ligne = calendrier_civil.lire_semaine(reg, '2030-06-03')['interventions'][0]
        ancre = {k: ligne[k] for k in ('intervention_id', 'plan_id', 'source_application_id', 'source_ligne_id')}
        args = {'ancre': ancre, 'revision_attendue': 0}
        visites_durables.prevoir(reg, prev, **args, auteur={'personne': 'admin.fictif', 'role': 'admin'},
            mutation={'appareil': 'fictif', 'cle': 'snapshot-fictif', 'empreinte_arguments': encodage.empreinte(args)},
            horodatage='2030-06-03T07:00:00-04:00')
    original, nombre = journal_visites.visites_ecriture.capturer_visites, []
    def changer(cnx):
        snapshot = original(cnx)
        nombre.append(1)
        if len(nombre) == 1:
            condition = ((REGISTRES.c.departement == 'm04-field-ops')
                         & (REGISTRES.c.registre == visites_durables.REGISTRE))
            entree = cnx.execute(select(REGISTRES).where(condition)).mappings().one()
            cnx.execute(REGISTRES.update().where(condition & (REGISTRES.c.rang == entree['rang']))
                        .values(cree_le=entree['cree_le'] + timedelta(seconds=1)))
        return snapshot
    monkeypatch.setattr(journal_visites.visites_ecriture, 'capturer_visites', changer)
    reponse = client_crm.get('/crm/journal-equipes?jour=2030-06-03')
    assert reponse.status_code == 503 and 'Visite identifiée' not in reponse.text


def test_lien_visite_hors_premiere_page_conserve_la_source(client_crm, planning, session):
    import re
    from datetime import date, timedelta
    from html import unescape

    from m4_field_ops import calendrier_civil, encodage, visites_durables

    _, ids, confirmation, _ = planning
    iid = ids['lead-fictif-001']
    with session():
        reg = Registre(stockage.maillons('m04-field-ops', 'principal'))
        prev = Registre(stockage.maillons('m04-field-ops', visites_durables.REGISTRE))
        initial = next(x for x in calendrier_civil.lire_semaine(reg, '2030-06-03')['interventions']
                       if x['intervention_id'] == iid)
        ancre = {k: initial[k] for k in ('intervention_id', 'plan_id', 'source_application_id', 'source_ligne_id')}
        for i in range(51):
            jour = (date(2030, 6, 3) + timedelta(days=i)).isoformat()
            if i:
                datee = calendrier_civil.confirmer(reg, confirmation['plan_id'], {'0': jour}, i,
                                                    'admin.fictif', '2030-06-02T10:00:00+00:00')
                ancre = {**ancre, 'source_ligne_id': datee['ligne_id']}
            args = {'ancre': ancre, 'revision_attendue': i}
            resultat = visites_durables.prevoir(reg, prev, **args, auteur={'personne': 'admin.fictif', 'role': 'admin'},
                mutation={'appareil': 'fictif', 'cle': f'prevision-{i}',
                          'empreinte_arguments': encodage.empreinte(args)},
                horodatage='2030-06-02T10:01:00+00:00')
    f.base._connecter(client_crm, 'admin.fictif')
    page = client_crm.get('/crm/journal-equipes?jour=' + jour)
    assert page.status_code == 200, page.text
    cible = re.search(r'href="([^"]*#visite-' + resultat['visite_id'] + r')"', page.text)
    assert cible is not None
    lien = unescape(cible.group(1)).removeprefix(f.base.PREFIXE)
    assert 'debut=50' in lien and 'source_attendue=' in lien
    destination = client_crm.get(lien.split('#')[0])
    assert destination.status_code == 200 and 'id="visite-' + resultat['visite_id'] + '"' in destination.text
    from m4_field_ops import composition_journaliere
    with session():
        comp = Registre(stockage.maillons('m04-field-ops', composition_journaliere.REGISTRE))
        args_comp = {'jour': jour, 'equipe_id': initial['equipe_id'], 'membres': ['personne.fictive'],
                     'revision_attendue': 0, 'statut_declaration': 'declaree'}
        composition_journaliere.declarer(comp, **args_comp, auteur={'personne': 'admin.fictif', 'role': 'admin'},
            mutation={'appareil': 'fictif', 'cle': 'composition-pagination',
                      'empreinte_arguments': encodage.empreinte(args_comp)},
            horodatage='2030-06-02T10:02:00+00:00')
    assert client_crm.get(lien.split('#')[0]).status_code == 503
    with session():
        reg = Registre(stockage.maillons('m04-field-ops', 'principal'))
        reg.ajouter({'type_entree': 'variance_m6_recue', 'intervention_id': 'autre-fictif',
                     'horodatage': '2030-06-02T10:02:00+00:00', 'fictif': True})
    assert client_crm.get(lien.split('#')[0]).status_code == 503


def test_pagination_journal_refuse_changement_de_composition(client_crm, planning, session):
    import re
    from html import unescape

    from m4_field_ops import calendrier_civil, composition_journaliere, encodage, visites_durables

    f.base._connecter(client_crm, 'admin.fictif')
    # Une prévision explicite rend les liens du journal dépendants des compositions.
    with session():
        reg = Registre(stockage.maillons('m04-field-ops', 'principal'))
        ligne = calendrier_civil.lire_semaine(reg, '2030-06-03')['interventions'][0]
        ancre = {k: ligne[k] for k in ('intervention_id', 'plan_id', 'source_application_id', 'source_ligne_id')}
        args_visite = {'ancre': ancre, 'revision_attendue': 0}
        prev = Registre(stockage.maillons('m04-field-ops', visites_durables.REGISTRE))
        visites_durables.prevoir(reg, prev, **args_visite, auteur={'personne': 'admin.fictif', 'role': 'admin'},
            mutation={'appareil': 'fictif', 'cle': 'visite-pagination-composition',
                      'empreinte_arguments': encodage.empreinte(args_visite)},
            horodatage='2030-06-03T07:00:00-04:00')
    page = client_crm.get('/crm/journal-equipes?jour=2030-06-03&limite=1')
    assert page.status_code == 200
    lien = re.search(r'href="([^"]+)"[^>]*>Page suivante</a>', page.text)
    assert lien is not None
    suite = unescape(lien.group(1)).removeprefix(f.base.PREFIXE)
    assert client_crm.get(suite).status_code == 200
    with session():
        reg = Registre(stockage.maillons('m04-field-ops', 'principal'))
        equipe = calendrier_civil.lire_semaine(reg, '2030-06-03')['interventions'][0]['equipe_id']
        comp = Registre(stockage.maillons('m04-field-ops', composition_journaliere.REGISTRE))
        args = {'jour': '2030-06-03', 'equipe_id': equipe, 'membres': ['personne.fictive'],
                'revision_attendue': 0, 'statut_declaration': 'declaree'}
        composition_journaliere.declarer(comp, **args, auteur={'personne': 'admin.fictif', 'role': 'admin'},
            mutation={'appareil': 'fictif', 'cle': 'composition-journal',
                      'empreinte_arguments': encodage.empreinte(args)},
            horodatage='2030-06-03T08:00:00-04:00')
    assert client_crm.get(suite).status_code == 503
