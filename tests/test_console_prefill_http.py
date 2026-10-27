"""Formulaires HTTP réels et SQLite, données fictives exclusivement."""
import html
import importlib.util
import io
import re
from pathlib import Path
from urllib.parse import urlencode

import pytest

from opsys import identite, stockage

spec = importlib.util.spec_from_file_location(
    'fixture_prefill_http', Path(__file__).with_name('test_console_prefill_ports.py'))
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
client_crm = p.client_crm
catalogue = p.catalogue
FICTIF = True
ROUTE = '/crm/lead/lead-fictif-001/soumission-preremplie'


def form(page):
    assert page.status_code == 200, page.text
    action, corps = next((action, corps) for action, corps in re.findall(
        r'<form method="post" action="([^"]+)"(.*?)</form>', page.text, re.S) if 'name="modele_source"' in corps)
    valeurs = {}
    for champ in re.findall(r'<input ([^>]+)>', corps):
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', champ))
        valeurs[attrs['name']] = html.unescape(attrs.get('value', ''))
    for nom, contenu in re.findall(r'<select name="([^"]+)"[^>]*>(.*?)</select>', corps, re.S):
        valeurs[nom] = html.unescape(re.search(r'<option value="([^"]*)">', contenu)[1])
    for attrs, contenu in re.findall(r'<textarea ([^>]+)>(.*?)</textarea>', corps, re.S):
        nom = re.search(r'name="([^"]+)"', attrs)[1]
        # Règle HTML : le premier LF immédiatement après textarea est ignoré.
        valeurs[nom] = html.unescape(contenu.removeprefix('\n'))
    return html.unescape(action).removeprefix(p.m.base.PREFIXE), valeurs


def preparer(client, session):
    initial = p.preparer(session)
    query = urlencode({k: initial[k] for k in ('modele_id', 'modele_revision', 'modele_source')})
    action, choix = form(client.get(ROUTE + '?' + query))
    assert choix['quantite_0'] == choix['fournisseur_id_0'] == choix['taux_marge'] == ''
    choix.update(quantite_0='2', fournisseur_id_0='fourn-fictif', taux_marge='0.2')
    avant = p.m.base._instantane_base(session)
    page = client.post(action, data=choix)
    assert p.m.base._instantane_base(session) == avant  # préparer ne crée rien
    assert page.headers['cache-control'] == 'no-store'
    assert '12.5 CAD' in page.text and 'prix-fictif.pdf' in page.text
    action_finale, donnees = form(page)
    assert not any('cout' in k for k in donnees)
    return action_finale, donnees, action, choix


def test_parcours_devis_documents_et_rejeu(catalogue, session):
    from pypdf import PdfReader

    action, donnees, _, _ = preparer(catalogue, session)
    r = catalogue.post(action, data=donnees, follow_redirects=False)
    assert r.status_code == 303, r.text
    detail = r.headers['location'].removeprefix(p.m.base.PREFIXE)
    stockage.liberer()
    avant = p.m.base._instantane_base(session)
    assert catalogue.post(action, data=donnees, follow_redirects=False).headers['location'] == r.headers['location']
    assert p.m.base._instantane_base(session) == avant
    for fmt in ('html', 'pdf'):
        document = catalogue.get(detail + '/document/' + fmt)
        assert document.status_code == 200
        texte = (document.text if fmt == 'html' else '\n'.join(
            page.extract_text() for page in PdfReader(io.BytesIO(document.content)).pages))
        assert 'Pose FICTIVE' in texte
        for secret in ('12.5', '12,5', 'fourn-fictif', 'prix-fictif.pdf', donnees['tarif_empreinte_0']):
            assert secret not in texte
    assert p.m.base._instantane_base(session) == avant
    p.prix(session, 17)
    assert catalogue.post(action, data=donnees, follow_redirects=False).status_code == 303


@pytest.mark.parametrize('cas', ['csrf', 'source', 'prix', 'doublon', 'quantite', 'cout', 'supplement', 'fournisseur'])
def test_refus_final_sans_effet(catalogue, session, cas):
    action, donnees, _, _ = preparer(catalogue, session)
    if cas == 'csrf':
        donnees['csrf'] = 'invalide'
    elif cas == 'source':
        donnees['lignes_source'] = '0' * 64
    elif cas == 'prix':
        p.prix(session, 14)
    elif cas == 'doublon':
        donnees['nombre_lignes'] = '2'
        for k in ('ligne_modele_id', 'quantite', 'fournisseur_id', 'tarif_rang', 'tarif_empreinte'):
            donnees[k + '_1'] = donnees[k + '_0']
    elif cas == 'quantite':
        donnees['quantite_0'] = '0'
    elif cas == 'cout':
        donnees['cout_unitaire_0'] = '0.01'
    elif cas == 'supplement':
        donnees['quantite_19'] = '1'
    else:
        donnees['fournisseur_id_0'] = 'inconnu'
    avant = p.m.base._instantane_base(session)
    assert catalogue.post(action, data=donnees).status_code in {400, 403, 409, 503}
    assert p.m.base._instantane_base(session) == avant


def test_creation_revoquee_et_payload_borne(catalogue, session):
    action, donnees, preview, choix = preparer(catalogue, session)
    avant = p.m.base._instantane_base(session)
    assert catalogue.post(action, content=b'x'*131073,
                          headers={'content-type': 'application/x-www-form-urlencoded'}).status_code == 413
    assert catalogue.post(preview, data={**choix, 'csrf': 'invalide'}).status_code == 403
    assert p.m.base._instantane_base(session) == avant
    assert catalogue.post(action, data=donnees, follow_redirects=False).status_code == 303
    with session() as cnx:
        identite.retirer_role(cnx, 'admin.fictif', 'admin')
    avant = p.m.base._instantane_base(session)
    assert catalogue.post(action, data=donnees).status_code == 403
    assert catalogue.post(preview, data=choix).status_code == 403
    assert p.m.base._instantane_base(session) == avant


def test_editor_lignes_csrf_revision_et_echappement(catalogue, session):
    r = p.m.direct(session)['resultat']
    route = '/crm/modeles-soumission/modele-fictif/lignes'
    query = urlencode(dict(modele_id=r['modele_id'], modele_revision=r['revision'], modele_source=r['source_id']))
    action, donnees = form(catalogue.get(route + '?' + query))
    donnees.update(description_0='\nFICTIF <script>texte</script>\nFinition', materiau_id_0='mat-fictif', unite_0='pi')
    avant = p.m.base._instantane_base(session)
    assert catalogue.post(action, data={**donnees, 'csrf': 'faux'}).status_code == 403
    assert p.m.base._instantane_base(session) == avant
    r = catalogue.post(action, data=donnees, follow_redirects=False)
    assert r.status_code == 303, r.text
    avant = p.m.base._instantane_base(session)
    assert catalogue.post(action, data=donnees, follow_redirects=False).status_code == 303
    assert p.m.base._instantane_base(session) == avant
    page = catalogue.get(r.headers['location'].removeprefix(p.m.base.PREFIXE))
    assert form(page)[1]['description_0'] == donnees['description_0']
    assert '&lt;script&gt;' in page.text and '<script>texte</script>' not in page.text
    assert catalogue.post(action, data={**donnees, 'mutation_id': 'autre', 'description_0': 'Autre'}).status_code == 409
    assert p.m.base._instantane_base(session) == avant


def test_aucune_ecriture_preview_invalide(catalogue, session):
    _, _, action, choix = preparer(catalogue, session)
    avant = p.m.base._instantane_base(session)
    assert catalogue.post(action, data={**choix, 'ligne_modele_id_0': 'autre'}).status_code == 409
    assert catalogue.post(action, data={**choix, 'quantite_0': 'NaN'}).status_code == 400
    assert catalogue.post(action, data={**choix, 'fournisseur_id_0': 'inconnu'}).status_code == 503
    assert p.m.base._instantane_base(session) == avant


def test_fournisseur_par_nom_sans_defaut_et_tarif_invalide_visible(catalogue, session):
    from m6_material_control.fournisseurs import enregistrer_fournisseur

    initial = p.preparer(session)
    query = urlencode({k: initial[k] for k in ('modele_id', 'modele_revision', 'modele_source')})
    with session():
        enregistrer_fournisseur('fourn-fictif', 'FICTIF <script>nom</script>', '2026-01-02T00:00:00+00:00',
                                stockage.maillons('m06-material-control', 'fournisseurs'))
    avant = p.m.base._instantane_base(session)
    page = catalogue.get(ROUTE + '?' + query)
    assert 'FICTIF &lt;script&gt;nom&lt;/script&gt;' in page.text
    assert '<script>nom</script>' not in page.text
    assert form(page)[1]['fournisseur_id_0'] == ''
    assert '<option value="fourn-fictif">' in page.text
    assert p.m.base._instantane_base(session) == avant

    # Un dernier prix futur bloque; l'ancien prix utilisable ne réapparaît pas.
    with session():
        journal = stockage.maillons('m06-material-control', 'livre_prix')
        journal.append({**list(journal)[-1], 'date_effet': '2099-01-01'})
    avant = p.m.base._instantane_base(session)
    page = catalogue.get(ROUTE + '?' + query)
    assert 'Aucun fournisseur avec tarif utilisable' in page.text
    assert 'Tarifs non sélectionnables' in page.text
    assert '<option value="fourn-fictif">' not in page.text
    assert '<button disabled>' in page.text
    assert p.m.base._instantane_base(session) == avant


def test_fournisseur_corrompu_apres_preview_bloque_creation(catalogue, session):
    action, donnees, _, _ = preparer(catalogue, session)
    with session():
        stockage.maillons('m06-material-control', 'fournisseurs').append(
            {'type_entree': 'fournisseur_maj', 'nom': 'Correction FICTIVE sans identité'})
    avant = p.m.base._instantane_base(session)
    assert catalogue.post(action, data=donnees).status_code == 503
    assert p.m.base._instantane_base(session) == avant
