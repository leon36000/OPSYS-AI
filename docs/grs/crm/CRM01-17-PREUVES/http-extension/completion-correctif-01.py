"""QA fictive : complétion M4 et vérification du WCT, sans réseau."""
import base64
import hashlib
import importlib.util
from datetime import UTC, datetime
from pathlib import Path

from m4_field_ops import outbox
from m4_field_ops.outils import outils
from m4_field_ops.registre import Registre
from opsys import contexte, stockage
from opsys.outils import executer_atomique

iid = 'c1ddea4e7b2f60b1bf43b9e635a8d85019549e5167723539e3969ee353aa81b6'
with stockage.transaction():
    reg = Registre(stockage.maillons('m04-field-ops', 'principal'))
    assert not [w for _, w in outbox.lire_outbox(reg) if w['intervention_id'] == iid]
fixture = importlib.util.spec_from_file_location('png_qa_fictive', Path('departments/m04-field-ops/tests/conftest.py'))
module = importlib.util.module_from_spec(fixture)
fixture.loader.exec_module(module)
png = module.png_minimal()
par_nom = {o.nom: o for o in outils()}
instant = datetime(2026, 10, 30, 13, 4, tzinfo=UTC)
def appeler(nom, args):
    with (stockage.transaction(), contexte.appele_par_appareil(
            contexte.IdentiteAppelante('admin.fictif', 'admin', source='console')),
          contexte.receptionne_de(contexte.HorodatageAppareil('console:admin.fictif', instant, instant))):
        return executer_atomique(par_nom[nom], args)
photo = appeler('m4_deposer_fichier', {'empreinte_sha256': hashlib.sha256(png).hexdigest(),
    'taille_octets': len(png), 'type_mime': 'image/png', 'index_bloc': 0, 'nombre_blocs': 1,
    'bloc_base64': base64.b64encode(png).decode('ascii')})
assert photo['ok'] and photo['resultat']['accepte'], photo
args = {'intervention_id': iid, 'horodatage': instant.isoformat(),
    'preuves_completion': {'checklist_complete': True,
        'photos_apres': [photo['resultat']['resultat']['reference']], 'notes': 'Fictif', 'signature': None},
    'signature_requise': False}
r = appeler('m4_completer_intervention', args)
assert r['ok'] and r['resultat']['accepte'], r
assert appeler('m4_completer_intervention', args)['resultat']['accepte'] is False
stockage.liberer()
with stockage.transaction():
    reg = Registre(stockage.maillons('m04-field-ops', 'principal'))
    wcts = [w for _, w in outbox.lire_outbox(reg) if w['intervention_id'] == iid]
    assert len(wcts) == 1 and wcts[0]['duree_reelle_minutes'] == 120
    print('QA_WCT_FICTIF=1 MINUTES=120 DOUBLE_REFUSE=OUI')
stockage.liberer()
