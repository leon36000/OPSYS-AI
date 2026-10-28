"""Fondation des prévisions identifiées : toutes les données sont fictives."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import pytest
from m4_field_ops import encodage, visites_durables
from m4_field_ops.registre import Registre

spec = importlib.util.spec_from_file_location('fixture_notes_visites',
                                               Path(__file__).with_name('test_annotations_calendrier.py'))
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)


def ecrire(principal, visites, ancre, revision=0, cle='fictif-1'):
    args = {'ancre': deepcopy(ancre), 'revision_attendue': revision}
    mutation = {'appareil': 'console-fictive', 'cle': cle, 'empreinte_arguments': encodage.empreinte(args)}
    return visites_durables.prevoir(principal, visites, **args, auteur=fixture.AUTEUR,
                                    mutation=mutation, horodatage=fixture.pur.HORODATAGE)


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
