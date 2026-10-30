"""Validation structurelle V3 : ces données synthétiques n'authentifient pas le producteur."""
import json
from copy import deepcopy
from pathlib import Path

import pytest
from m5_financecore import encodage, validation_projection_visites


def _projection():
    fixture = Path(__file__).parents[3] / 'docs/grs/crm/CRM01-18-FIXTURE-TEMPS-V3.json'
    p = json.loads(fixture.read_text())['projection']
    p['revue_chantier']['statut'] = 'verifiee'
    return _rehacher(p)


def _rehacher(p):
    p['empreinte'] = encodage.empreinte('m4.temps_certifies.v3', {k: v for k, v in p.items() if k != 'empreinte'})
    return p


def _valider(p, source='a' * 64, source_relue='a' * 64):
    return validation_projection_visites.valider_projection_v3(
        p, instance_id=p['instance_id'], wct_id=p['wct']['wct_id'],
        source_attendue=source, source_relue=source_relue, sources_actuelles=p['sources'],
    )


def test_fixture_structurelle_avec_revue_et_preuves_completes():
    resultat = _valider(_projection())
    assert resultat['valide'] and resultat['exploitable']


def test_source_passee_au_consommateur_differe_de_la_source_relue():
    assert not _valider(_projection(), source_relue='b' * 64)['valide']


@pytest.mark.parametrize('attaque', ['absence', 'homonymie', 'audit_double', 'preuve_double', 'auteur'])
def test_preuves_typees_incompletes_ou_incoherentes_sont_refusees(attaque):
    p = _projection()
    equipes = [v['equipe_pointee'] for v in p['visites']]
    if attaque == 'absence':
        equipes[0]['preuves'].pop()
    elif attaque == 'homonymie':
        equipes[0]['identifiant'] = 'personne-homonyme'
    elif attaque == 'audit_double':
        equipes[1]['preuves'][0]['audit_id'] = equipes[0]['preuves'][0]['audit_id']
    elif attaque == 'preuve_double':
        equipes[1]['preuves'][0]['preuve_id'] = equipes[0]['preuves'][0]['preuve_id']
    else:
        equipes[0]['preuves'][0]['auteur']['role'] = 'technicien'
    assert not _valider(_rehacher(p))['valide']


def test_empreinte_ne_protege_pas_une_source_perimee():
    p = _projection()
    source_perimee = deepcopy(p['sources'])
    source_perimee['principal']['empreinte_snapshot'] = 'b' * 64
    resultat = validation_projection_visites.valider_projection_v3(
        p, instance_id=p['instance_id'], wct_id=p['wct']['wct_id'],
        source_attendue='a' * 64, source_relue='a' * 64, sources_actuelles=source_perimee,
    )
    assert not resultat['valide']
