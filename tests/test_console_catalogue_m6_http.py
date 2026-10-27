"""fictif: true — catalogue HTTP réel et jonction M6 → lignes M3 → devis prérempli."""
import html
import importlib.util
import re
from pathlib import Path
from urllib.parse import urlencode

import pytest

from opsys import identite, stockage

spec = importlib.util.spec_from_file_location('fixtures_catalogue_http',
                                              Path(__file__).with_name('test_console_prefill_http.py'))
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
client_crm = h.client_crm
catalogue = h.catalogue
BASE = '/crm/materiaux'


def form(page, marque='name="nom"'):
    assert page.status_code == 200, page.text
    action, contenu = next((a, c) for a, c in re.findall(
        r'<form method="post" action="([^"]+)"(.*?)</form>', page.text, re.S) if marque in c)
    valeurs = {}
    for champ in re.findall(r'<input ([^>]+)>', contenu):
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', champ))
        valeurs[attrs['name']] = html.unescape(attrs.get('value', ''))
    for nom, options in re.findall(r'<select name="([^"]+)"[^>]*>(.*?)</select>', contenu, re.S):
        choix = re.findall(r'<option value="([^"]*)"([^>]*)>', options)
        valeurs[nom] = html.unescape(next((v for v, attrs in choix if 'selected' in attrs), choix[0][0]))
    for nom, texte in re.findall(r'<textarea name="([^"]+)"[^>]*>(.*?)</textarea>', contenu, re.S):
        valeurs[nom] = html.unescape(texte.removeprefix('\n'))
    return html.unescape(action).removeprefix(h.p.m.base.PREFIXE), valeurs


def creer(client, *, nom='Matériau FICTIF', unite='pi'):
    action, donnees = form(client.get(BASE))
    donnees.update(nom=nom, unite=unite, raison='Ajout FICTIF')
    r = client.post(action, data=donnees, follow_redirects=False)
    assert r.status_code == 303, r.text
    return r.headers['location'].removeprefix(h.p.m.base.PREFIXE), action, donnees


def test_catalogue_creation_versions_historique_et_inactivation(catalogue, session):
    lien, action, donnees = creer(catalogue, nom='Matériau FICTIF <script>nom</script>')
    page = catalogue.get(lien)
    assert '&lt;script&gt;nom&lt;/script&gt;' in page.text and '<script>nom</script>' not in page.text
    assert page.headers['cache-control'] == 'no-store'
    avant = h.p.m.base._instantane_base(session)
    assert catalogue.post(action, data=donnees, follow_redirects=False).headers['location'].endswith('?version=1')
    assert h.p.m.base._instantane_base(session) == avant
    action, revision = form(page)
    assert revision['actif'] == 'true'
    revision.update(nom='Nom corrigé FICTIF', actif='false', raison='Désactivation FICTIVE')
    r = catalogue.post(action, data=revision, follow_redirects=False)
    assert r.status_code == 303
    courant = catalogue.get(r.headers['location'].removeprefix(h.p.m.base.PREFIXE))
    assert 'Inactif' in courant.text and form(courant)[1]['actif'] == 'false'
    historique = catalogue.get(lien)
    assert 'Version 1 sur 2' in historique.text and 'name="nom"' not in historique.text
    assert 'Nom corrigé FICTIF' in catalogue.get(BASE).text
    avant = h.p.m.base._instantane_base(session)
    assert catalogue.post(action, data={**revision, 'mutation_id': 'conflit-fictif'}).status_code == 409
    assert h.p.m.base._instantane_base(session) == avant


@pytest.mark.parametrize('cas', ['csrf', 'extra', 'unite', 'actif', 'revision', 'duplique', 'corps'])
def test_refus_catalogue_sans_effet(catalogue, session, cas):
    lien, _, _ = creer(catalogue)
    action, p = form(catalogue.get(lien))
    p['raison'] = 'Correction FICTIVE'
    if cas == 'csrf':
        p['csrf'] = 'faux'
    elif cas == 'extra':
        p['prix'] = '0.01'
    elif cas == 'unite':
        p['unite'] = 'm'
    elif cas == 'actif':
        p['actif'] = 'oui'
    elif cas == 'revision':
        p['revision_attendue'] = '0'
    avant = h.p.m.base._instantane_base(session)
    if cas == 'duplique':
        r = catalogue.post(action, content=urlencode(p) + '&nom=duplication',
                           headers={'content-type': 'application/x-www-form-urlencoded'})
    elif cas == 'corps':
        r = catalogue.post(action, content=b'x'*131073,
                           headers={'content-type': 'application/x-www-form-urlencoded'})
    else:
        r = catalogue.post(action, data=p)
    assert r.status_code in {400, 403, 409, 413}
    assert h.p.m.base._instantane_base(session) == avant


def test_acces_catalogue_revoque_et_profils(client_crm, session):
    assert client_crm.get(BASE, follow_redirects=False).status_code == 303
    for utilisateur in ('employe', 'nathan'):
        h.p.m.base._connecter(client_crm, utilisateur)
        assert client_crm.get(BASE).status_code == 403
    h.p.m.base._connecter(client_crm, 'admin.fictif')
    _, action, p = creer(client_crm)
    with session() as cnx:
        identite.retirer_role(cnx, 'admin.fictif', 'admin')
    avant = h.p.m.base._instantane_base(session)
    assert client_crm.post(action, data=p).status_code == 403
    assert client_crm.get(BASE).status_code == 403
    assert h.p.m.base._instantane_base(session) == avant


def preparer_lignes(client, session):
    modele = h.p.m.direct(session)['resultat']
    lien, _, materiau = creer(client, nom='Gouttière FICTIVE <script>nom</script>')
    ancre = dict(modele_id=modele['modele_id'], modele_revision=modele['revision'], modele_source=modele['source_id'])
    route = '/crm/modeles-soumission/' + modele['modele_id'] + '/lignes/catalogue'
    page = client.get(route + '?' + urlencode(ancre))
    action, choix = form(page, 'name="selection_0"')
    options = re.findall(r'<option value="([^"]+)">', page.text)
    jeton = next(html.unescape(v) for v in options if v.startswith(materiau['materiau_id'] + '@'))
    assert choix['selection_0'] == ''  # aucun matériau imposé sur une ligne vide
    assert 'Gouttière FICTIVE &lt;script&gt;nom&lt;/script&gt;' in page.text
    choix.update(description_0='Pose FICTIVE', selection_0=jeton)
    return action, choix, ancre, lien, materiau


def test_material_name_to_template_then_priced_quote(catalogue, session):
    from m6_material_control.fournisseurs import enregistrer_fournisseur
    from m6_material_control.livre_prix import enregistrer_prix

    action, choix, ancre, _, materiau = preparer_lignes(catalogue, session)
    r = catalogue.post(action, data=choix, follow_redirects=False)
    assert r.status_code == 303, r.text
    page = catalogue.get(r.headers['location'].removeprefix(h.p.m.base.PREFIXE))
    assert form(page, 'name="selection_0"')[1]['selection_0'] == choix['selection_0']
    avant = h.p.m.base._instantane_base(session)
    assert catalogue.post(action, data=choix, follow_redirects=False).status_code == 303
    assert h.p.m.base._instantane_base(session) == avant
    with session():
        _, refus = enregistrer_fournisseur('fourn-fictif', 'Fournisseur FICTIF', '2026-01-01T00:00:00+00:00',
                                           stockage.maillons('m06-material-control', 'fournisseurs'))
        assert refus is None
        _, refus = enregistrer_prix(materiau['materiau_id'], 'fourn-fictif', 12.5, 'CAD', '2026-01-01',
                                    stockage.maillons('m06-material-control', 'livre_prix'),
                                    source_document='tarif-fictif.pdf', unite='pi')
        assert refus is None
    route = h.ROUTE + '?' + urlencode(ancre)
    action, p = h.form(catalogue.get(route))
    p.update(quantite_0='2', fournisseur_id_0='fourn-fictif', taux_marge='0.2')
    page = catalogue.post(action, data=p)
    assert 'data-total="vente">30.00</strong>' in page.text
    action, p = h.form(page)
    r = catalogue.post(action, data=p, follow_redirects=False)
    assert r.status_code == 303
    document = catalogue.get(r.headers['location'].removeprefix(h.p.m.base.PREFIXE) + '/document/html')
    assert 'Pose FICTIVE' in document.text and '30.00' in document.text
    assert 'fourn-fictif' not in document.text


@pytest.mark.parametrize('cas', ['revision', 'inactive', 'source', 'unite_injectee', 'csrf'])
def test_selection_source_exacte_et_refus_sans_effet(catalogue, session, cas):
    action, choix, _, lien, _ = preparer_lignes(catalogue, session)
    if cas in {'revision', 'inactive'}:
        a, p = form(catalogue.get(lien))
        p.update(nom='Corrigé FICTIF', raison='Correction FICTIVE', actif='false' if cas == 'inactive' else 'true')
        assert catalogue.post(a, data=p, follow_redirects=False).status_code == 303
    elif cas == 'source':
        choix['selection_0'] = choix['selection_0'].rsplit('@', 1)[0] + '@' + '0'*64
    elif cas == 'unite_injectee':
        choix['unite_0'] = 'm'
    else:
        choix['csrf'] = 'faux'
    avant = h.p.m.base._instantane_base(session)
    assert catalogue.post(action, data=choix).status_code in {400, 403, 409}
    assert h.p.m.base._instantane_base(session) == avant


def test_inactif_exclu_des_nouveaux_choix(catalogue, session):
    action, _, ancre, lien, materiau = preparer_lignes(catalogue, session)
    a, p = form(catalogue.get(lien))
    p.update(actif='false', raison='FICTIF')
    assert catalogue.post(a, data=p, follow_redirects=False).status_code == 303
    page = catalogue.get(action + '?' + urlencode(ancre))
    assert materiau['materiau_id'] + '@' not in page.text
    assert 'Ancienne référence' not in page.text  # modèle encore vide


def test_pagination_et_ligne_existante_hors_page(catalogue, session):
    from m6_material_control import catalogue_materiaux as domaine

    action, choix, ancre, _, materiau = preparer_lignes(catalogue, session)
    assert catalogue.post(action, data=choix, follow_redirects=False).status_code == 303
    # Données de catalogue fictives préparées dans le domaine réel, sans passer par 26 formulaires.
    with session():
        journal = stockage.maillons('m06-material-control', domaine.REGISTRE)
        for i in range(26):
            domaine.enregistrer(journal, materiau_id=f'zz-fictif-{i:02}', nom=f'Autre FICTIF {i}', unite='pi',
                                actif=True, raison='Pagination FICTIVE', auteur='admin.fictif',
                                horodatage='2026-10-27T10:00:00+00:00', revision_attendue=0)
    page = catalogue.get(BASE)
    assert 'Page suivante' in page.text
    assert 'Autre FICTIF 25' not in page.text
    page = catalogue.get(BASE + '?debut=25')
    assert 'Autre FICTIF 25' in page.text
    page = catalogue.get(action + '?' + urlencode({**ancre, 'debut': 25}))
    assert form(page, 'name="selection_0"')[1]['selection_0'] == choix['selection_0']
    assert materiau['materiau_id'] + '@' in page.text
    assert catalogue.get(BASE + '?debut=25&debut=0').status_code == 400


@pytest.mark.parametrize('reference', ['mat-fictif', 'matériau-fictif', 'x'*101])
def test_ancienne_reference_inconnue_reste_lisible(catalogue, session, reference):
    initial = h.p.preparer(session)  # ligne M3 historique sans fiche nommée M6
    route = '/crm/modeles-soumission/' + initial['modele_id'] + '/lignes/catalogue?'
    ancre = {k: initial[k] for k in ('modele_id', 'modele_revision', 'modele_source')}
    revisions = 1
    if reference != 'mat-fictif':
        r = h.p.appel(session, 'enregistrer_lignes_modele', dict(**ancre, revision_attendue=1,
                     lignes=[dict(ligne_id='ligne-fictive', description='Pose FICTIVE',
                                  materiau_id=reference, unite='pi')]), cle='legacy-fictif')
        assert r['accepte'], r
        revisions = 2
    page = catalogue.get(route + urlencode(ancre))
    assert page.status_code == 200
    assert 'Ancienne référence indisponible' in page.text
    assert form(page, 'name="selection_0"')[1]['description_0'] == 'Pose FICTIVE'
    # Le modèle original n'a pas été réécrit par la lecture du nouvel éditeur.
    with session():
        journal = stockage.maillons('m03-estimation', 'modeles_lignes_soumission')
        assert len(journal) == revisions
