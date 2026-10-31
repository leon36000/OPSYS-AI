import json
from decimal import Decimal
from pathlib import Path
from m5_financecore.ventilation_couts_visites import chiffrer_visites

base = Path(__file__).resolve().parents[1]
x = json.loads((base / 'v3-preuve-reelle-01/test_pointage_v3_enregistre_pr0/projection-v3-reelle-fictive.json').read_text())
p = x['projection']
tarifs = [{'equipe_id': equipe, 'taux': taux, 'unite': 'heure-equipe', 'devise': 'CAD',
           'source': 'tarif-fictif', 'version': 'v1-fictive', 'date_effet': '2030-01-01',
           'date_fin': '2030-12-31', 'ligne_id': marque * 64}
          for equipe, taux, marque in [('eq-a', '100', 'a'), ('eq-b', '120', 'b')]]
r = chiffrer_visites(p['visites'], tarifs)
assert r['complet'] and r['cout_total'] == Decimal('730.00')
assert [ligne['cout'] for ligne in r['lignes']] == [Decimal('250.00'), Decimal('480.00')]
print('calcul_pur_fictif_CAD=250.00+480.00=730.00')
print('limite=validation V3 et adaptateur de confiance absents; aucun coût certifié')
