"""Export de coûts fictifs : lecture admin seule et sources revalidées."""
import importlib.util
from pathlib import Path

from opsys import identite

spec = importlib.util.spec_from_file_location('couts_export_fixture',
    Path(__file__).with_name('test_console_rentabilite_chantier_http.py'))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
client_crm, catalogue, affaire, complet = f.client_crm, f.catalogue, f.affaire, f.complet
FICTIF = True


def url(contexte):
    return f._url(contexte) + '/export.json'


def test_export_admin_reproduit_vue_m5_partielle_sans_ecriture(complet, catalogue, session):
    avant = f.f.f.m.base._instantane_base(session)
    response = catalogue.get(url(complet))
    assert response.status_code == 200, response.text
    doc = response.json()
    assert doc['format'] == 'opsys.couts-travaux.export.v1'
    assert 'préparatoire' in doc['mention'].lower()
    vue = doc['vue']
    cout = vue['chantier']['rentabilite']['cout_reel']
    assert cout['complet'] is False and cout['cout_total'] is None
    assert cout['main_d_oeuvre']['cout'] is None
    assert cout['manque'] and vue['source_calculee']
    assert response.headers['cache-control'] == 'no-store'
    assert response.headers['x-content-type-options'] == 'nosniff'
    assert 'attachment;' in response.headers['content-disposition']
    assert 'application/json' in response.headers['content-type']
    assert f.f.f.m.base._instantane_base(session) == avant
    assert url(complet) in catalogue.get(f._url(complet)).text


def test_export_sans_source_materiau_ou_temps_ne_fabrique_pas_zero(complet, catalogue, monkeypatch):
    from opsys.console import rentabilite_chantier as port

    original = port.lire

    def vide(*args):
        vue = original(*args)
        cout = vue['chantier']['rentabilite']['cout_reel']
        cout['materiaux'].update(statut='non_disponible', lignes=[], cout_connu='0')
        cout['main_d_oeuvre'].update(statut='non_disponible', cout=None)
        cout.update(complet=False, cout_total=None, cout_total_connu='0')
        return vue

    monkeypatch.setattr(port, 'lire', vide)
    response = catalogue.get(url(complet))
    assert response.status_code == 200, response.text
    cout = response.json()['vue']['chantier']['rentabilite']['cout_reel']
    assert cout['cout_total_connu'] is None and cout['materiaux']['cout_connu'] is None


def test_export_non_admin_refuse_sans_ecriture(complet, catalogue, session):
    with session() as cnx:
        identite.ajouter_role(cnx, f.f.f.AUTH.utilisateur, 'nathan_owner')
        identite.retirer_role(cnx, f.f.f.AUTH.utilisateur, 'admin')
    avant = f.f.f.m.base._instantane_base(session)
    response = catalogue.get(url(complet))
    assert response.status_code == 403 and '336.00' not in response.text
    assert f.f.f.m.base._instantane_base(session) == avant


def test_export_refuse_source_modifiee_apres_serialisation(complet, catalogue, monkeypatch):
    from opsys.console import rentabilite_chantier as port

    original = port._exporter

    def modifier(vue):
        contenu = original(vue)
        complet['config'].write_text('configuration:\n  taux_horaire_main_d_oeuvre: "100.00"\n')
        return contenu

    monkeypatch.setattr(port, '_exporter', modifier)
    response = catalogue.get(url(complet))
    assert response.status_code == 503 and '336.00' not in response.text


def test_export_refuse_revocation_apres_serialisation(complet, catalogue, session, monkeypatch):
    from opsys.console import rentabilite_chantier as port

    original = port._exporter

    def modifier(vue):
        contenu = original(vue)
        with session() as cnx:
            identite.ajouter_role(cnx, f.f.f.AUTH.utilisateur, 'nathan_owner')
            identite.retirer_role(cnx, f.f.f.AUTH.utilisateur, 'admin')
        return contenu

    monkeypatch.setattr(port, '_exporter', modifier)
    response = catalogue.get(url(complet))
    assert response.status_code == 403 and '336.00' not in response.text


def test_export_borne_et_parametres_refuses(complet, catalogue, monkeypatch):
    from opsys.console import rentabilite_chantier as port

    assert catalogue.get(url(complet) + '?x=1').status_code == 400
    monkeypatch.setattr(port, '_exporter', lambda vue: b'x' * 131073)
    response = catalogue.get(url(complet))
    assert response.status_code == 503 and len(response.content) < 1024


def test_encodage_utf8_ne_mutile_pas_les_sources():
    import json

    from opsys.console import rentabilite_chantier as port

    vue = {'chantier': None, 'mention': 'Donnée fictive : Équipe Québec <test>', 'source_calculee': 'a' * 64}
    sortie = port._exporter(vue)
    assert 'Équipe Québec'.encode() in sortie
    assert json.loads(sortie)['vue'] == vue


def test_zero_documente_par_un_signal_complet_est_conserve():
    import json

    from opsys.console import rentabilite_chantier as port

    vue = {'chantier': {'statut': 'calculee', 'rentabilite': {'cout_reel': {
        'materiaux': {'statut': 'complet', 'lignes': [], 'cout_connu': '0'},
        'main_d_oeuvre': {'cout': None}, 'cout_total_connu': '0'}}}}
    cout = json.loads(port._exporter(vue))['vue']['chantier']['rentabilite']['cout_reel']
    assert cout['materiaux']['cout_connu'] == '0' and cout['cout_total_connu'] == '0'


def test_html_ne_fabrique_pas_zero_et_preserve_zero_atteste(complet, session):
    import copy

    from opsys.console import rentabilite_chantier as port

    with session() as cnx:
        vue = port.lire(cnx, complet['deps'], f.f.f.AUTH, complet['lead'], f.f.f.DEVIS)
    cout = vue['chantier']['rentabilite']['cout_reel']
    cout['materiaux'].update(statut='non_disponible', lignes=[], cout_connu='0')
    cout['main_d_oeuvre'].update(statut='non_disponible', cout=None)
    cout.update(complet=False, cout_total=None, cout_total_connu='0')
    original = copy.deepcopy(vue)
    html = port.contenu(vue, '')
    assert '<th>Coût total connu</th><td>Non disponible</td>' in html
    assert '<th>Matériaux connus</th><td>Non disponible</td>' in html
    assert vue == original
    cout['materiaux']['statut'] = 'complet'
    html = port.contenu(vue, '')
    assert '<th>Coût total connu</th><td>0</td>' in html
    assert '<th>Matériaux connus</th><td>0</td>' in html
