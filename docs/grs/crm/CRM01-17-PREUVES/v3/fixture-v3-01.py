import hashlib
import json
from pathlib import Path
from m4_field_ops import encodage

path = Path('docs/grs/crm/CRM01-17-FIXTURE-TEMPS-V2.json')
data = json.loads(path.read_text())
data['description'] = 'Fixture V3 purement fictive ; les références de preuve sont synthétiques, sans base réelle.'
p = data['projection']
p['version'] = 'opsys.m4.temps_certifies.v3'
p['inconnus'] = [x for x in p['inconnus'] if x['code'] != 'equipe_pointee_indeterminee']
for i, visite in enumerate(p['visites']):
    preuves = []
    for j, e in enumerate(x for x in visite['evenements'] if x['type'] != 'en_route'):
        ident = hashlib.sha256(f'preuve-fictive-{i}-{j}'.encode()).hexdigest()
        profil = hashlib.sha256(f'profil-fictif-{i}'.encode()).hexdigest()
        preuves.append({'pointage_id': e['source_ligne_id'], 'preuve_id': ident,
                        'auteur': {'personne': 'admin.fictif', 'role': 'admin'},
                        'profil_empreinte': profil, 'audit_id': 100 + i * 10 + j})
    visite['equipe_pointee'] = {'statut': 'identifiee', 'identifiant': visite['identifiant_pointe'],
                               'justification': 'pointages_attestes_v3', 'preuves': preuves}
p['empreinte'] = encodage.empreinte('m4.temps_certifies.v3', {k: v for k, v in p.items() if k != 'empreinte'})
out = Path('docs/grs/crm/CRM01-17-FIXTURE-TEMPS-V3.json')
out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
print('empreinte_projection=' + p['empreinte'])
print('sha256_fichier=' + hashlib.sha256(out.read_bytes()).hexdigest())
