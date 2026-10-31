"""Fictif : une modification sans lien change le CAS global V3."""
import importlib.util
from pathlib import Path

import pytest
from m4_field_ops import composition_journaliere, encodage, temps_certifies_v2, temps_certifies_v3
from m4_field_ops.registre import Registre
from opsys import contexte, stockage

spec = importlib.util.spec_from_file_location('fixture_v2', Path.cwd() /
    'departments/m04-field-ops/tests/test_temps_certifies_v2.py')
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
chantier_termine = base.chantier_termine
conf_spec = importlib.util.spec_from_file_location('fixture_conf', Path.cwd() /
    'departments/m04-field-ops/tests/conftest.py')
conf = importlib.util.module_from_spec(conf_spec)
conf_spec.loader.exec_module(conf)
base_durable = conf.base_durable


def test_composition_sans_lien_change_cas_v3(chantier_termine):
    cas = chantier_termine
    with (stockage.transaction(cas['url']) as cnx,
          contexte.appele_par_appareil(contexte.IdentiteAppelante('admin.fictif', 'admin', source='console')),
          contexte.appeler_en_tant_que('m04-field-ops', origine='console')):
        avant = temps_certifies_v3.projeter(cnx, cas['iid'], cas['wct_id'])
        args = {'jour': '2030-06-11', 'equipe_id': 'autre-equipe-fictive', 'membres': ['autre.fictif'],
                'revision_attendue': 0, 'statut_declaration': 'declaree'}
        compositions = Registre(stockage.maillons('m04-field-ops', composition_journaliere.REGISTRE))
        composition_journaliere.declarer(compositions, **args,
            auteur={'personne': 'admin.fictif', 'role': 'admin'},
            mutation={'appareil': 'fictif', 'cle': 'ailleurs-fictif', 'empreinte_arguments': encodage.empreinte(args)},
            horodatage='2030-06-11T08:00:00-04:00')
        with pytest.raises(temps_certifies_v2.Refus, match='SOURCE-PERIMEE'):
            temps_certifies_v3.projeter(cnx, cas['iid'], cas['wct_id'], source_attendue=avant['source'])
        apres = temps_certifies_v3.projeter(cnx, cas['iid'], cas['wct_id'])
        assert avant['source'] != apres['source']
        assert avant['projection']['totaux'] == apres['projection']['totaux']
