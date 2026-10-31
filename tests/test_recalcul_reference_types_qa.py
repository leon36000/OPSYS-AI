import pytest

from opsys import service_recalcul_m4 as r
from opsys.service_capability import RefusAutorite


def reference():
    return {'schema':'opsys.core.m4.recalcul-attestation.v2','operation':'m4.recalculer_v3',
        'intention_id':'a'*64,'instance_id':'instance-fictive','acteur':'admin-fictif',
        'wct_id':'b'*64,'devis_id':'devis-fictif','audit_recalcul_id':1,'audit_service_id':2,
        'revision_recalcul':1,'revision_service':1,'trace_rang':0,'trace_empreinte':'c'*64,
        'source_m4':'d'*64,'projection_m4':'e'*64,'wct_hash':'f'*64,'version_m4':'v3',
        'trace_statut':'declaration_m5_non_verifiee_par_core'}


def test_reference_complete_valide_et_canonique():
    valeur=reference()
    assert r.valider_reference_v2(valeur) is None
    assert r._reference_canonique(valeur)==r._reference_canonique(dict(reversed(list(valeur.items()))))


@pytest.mark.parametrize('nom,valeur', [
    ('revision_recalcul',True),('revision_recalcul',1.0),('revision_service',False),
    ('audit_recalcul_id',True),('audit_service_id',2.0),('audit_service_id',1),
    ('trace_rang',False),('trace_rang',1000),('wct_id','g'*64),('trace_empreinte','x'*64),
    ('acteur',''),('acteur','x'*257),('acteur','\ud800'),('instance_id',True),
    ('version_m4','x'*65),('trace_statut','frais'),('operation','m4.verifier_v3'),
])
def test_refuse_types_valeurs_ou_identites_invalides(nom,valeur):
    ref=reference();ref[nom]=valeur
    with pytest.raises(RefusAutorite): r.valider_reference_v2(ref)
    with pytest.raises(RefusAutorite): r._reference_canonique(ref)


@pytest.mark.parametrize('changement', ['absent','supplementaire'])
def test_refuse_schema_ouvert(changement):
    ref=reference()
    if changement=='absent': del ref['revision_service']
    else: ref['autre']=1
    with pytest.raises(RefusAutorite): r.valider_reference_v2(ref)
