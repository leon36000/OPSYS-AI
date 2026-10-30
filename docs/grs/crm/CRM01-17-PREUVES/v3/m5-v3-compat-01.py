import json
from pathlib import Path
from m5_financecore.validation_projection_visites import valider_projection

base = Path(__file__).resolve().parents[1]
x = json.loads((base / 'v3-preuve-reelle-01/test_pointage_v3_enregistre_pr0/projection-v3-reelle-fictive.json').read_text())
p = x['projection']
r = valider_projection(p, instance_id=p['instance_id'], wct_id=p['wct']['wct_id'],
                       source_attendue=x['source'], sources_actuelles=p['sources'])
print(json.dumps(r, ensure_ascii=False, sort_keys=True))
assert not r['valide']
