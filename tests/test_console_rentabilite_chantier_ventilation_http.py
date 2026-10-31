"""HTTP fictif : plusieurs WCT ne sont pas une ventilation du chantier."""
import importlib.util
from pathlib import Path

from opsys import stockage

spec = importlib.util.spec_from_file_location('ventilation_http_fixture',
    Path(__file__).with_name('test_console_rentabilite_chantier_http.py'))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
client_crm, catalogue, affaire, complet = f.client_crm, f.catalogue, f.affaire, f.complet


def test_plusieurs_wct_bloquent_volet_ventilation_et_export(complet, catalogue, session):
    with session():
        registre = stockage.maillons('m05-financecore', 'wct_recus')
        precedent = next(m for m in registre if m.get('devis_id') == f.f.f.DEVIS)
        registre.append({**precedent, 'wct_id': 'AUTRE-WCT-FICTIF'})
    r = catalogue.get(f._url(complet))
    assert r.status_code == 200
    assert 'plusieurs WCT' in r.text
    e = catalogue.get(f._url(complet) + '/export.json')
    assert e.status_code == 200 and e.json()['vue']['ventilation_m4']['statut'] == 'WCT_MULTIPLES'


def test_departement_m4_absent_est_signale_sans_import(complet, session):
    from opsys.console import rentabilite_chantier as port

    deps = {k: v for k, v in complet['deps'].items() if k != 'm04-field-ops'}
    with session() as cnx:
        vue = port.lire(cnx, deps, f.f.f.AUTH, complet['lead'], f.f.f.DEVIS)
    assert vue['ventilation_m4']['statut'] == 'PRODUCTEUR_INDISPONIBLE'
    assert 'producteur non installé' in port.contenu(vue, '')
