"""fictif: true — consultation admin des coûts, vrais M3/M5, aucun formulaire financier."""
import importlib.util
from pathlib import Path

import pytest

from opsys import identite, stockage

spec = importlib.util.spec_from_file_location('couts_http_fixture',
    Path(__file__).with_name('test_console_rentabilite_chantier.py'))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
client_crm, catalogue, affaire, complet = f.client_crm, f.catalogue, f.affaire, f.complet
FICTIF = True


def _url(contexte):
    return f'/crm/lead/{contexte["lead"]}/soumissions/{f.f.DEVIS}/couts-travaux'


def test_attente_sourcee_et_lien_depuis_devis(affaire, catalogue, session):
    avant = f.f.m.base._instantane_base(session)
    r = catalogue.get(_url(affaire))
    assert r.status_code == 200, r.text
    assert 'En attente des travaux terminés' in r.text and 'Coûts des travaux' in r.text
    assert r.headers['cache-control'] == 'no-store'
    fiche = catalogue.get(_url(affaire).removesuffix('/couts-travaux'))
    assert _url(affaire) in fiche.text
    assert f.f.m.base._instantane_base(session) == avant


def test_couts_m5_et_limites_affiches_sans_effet(complet, catalogue, session):
    avant = f.f.m.base._instantane_base(session)
    r = catalogue.get(_url(complet))
    assert r.status_code == 200, r.text
    for texte in ('480.00', '600.00', '486.00', '336.00', '150.00', '114.00', 'Source : M5', 'Analyse préparatoire IA',
                  'Prix non définitif', 'Trace de calcul antérieure', 'Hypothèses M5'):
        assert texte in r.text
    assert 'content-security-policy' in r.headers and r.headers['cache-control'] == 'no-store'
    assert catalogue.post(_url(complet), data={'prix_total': '999.00'}).status_code == 405
    assert f.f.m.base._instantane_base(session) == avant


def test_cout_partiel_n_est_pas_zero(complet, catalogue):
    complet['config'].write_text('configuration: {}\n')
    r = catalogue.get(_url(complet))
    assert r.status_code == 200, r.text
    assert 'Coût partiel' in r.text and 'Non disponible' in r.text and 'Manques M5' in r.text


@pytest.mark.parametrize('suffixe,statut', [('?prix=999', 400), ('?role=admin&role=seller', 400),
                                           ('/inconnu', 404)])
def test_parametres_et_chemin_refuses(affaire, catalogue, session, suffixe, statut):
    avant = f.f.m.base._instantane_base(session)
    assert catalogue.get(_url(affaire) + suffixe).status_code == statut
    assert f.f.m.base._instantane_base(session) == avant


def test_identite_sql_revoquee_ne_voit_pas_couts(complet, catalogue, session):
    with session() as cnx:
        identite.ajouter_role(cnx, f.f.AUTH.utilisateur, 'nathan_owner')
        identite.retirer_role(cnx, f.f.AUTH.utilisateur, 'admin')
    r = catalogue.get(_url(complet))
    assert r.status_code == 403 and '486.00' not in r.text


def test_revocation_derniere_lecture_http_refuse(complet, catalogue, monkeypatch):
    from opsys.console import rentabilite_chantier as port

    original, appels = port._reception, []

    def reception(*args):
        r = original(*args)
        appels.append(1)
        if len(appels) == 2:
            cnx = stockage.connexion_courante()
            identite.ajouter_role(cnx, f.f.AUTH.utilisateur, 'nathan_owner')
            identite.retirer_role(cnx, f.f.AUTH.utilisateur, 'admin')
        return r

    monkeypatch.setattr(port, '_reception', reception)
    r = catalogue.get(_url(complet))
    assert r.status_code == 403 and '486.00' not in r.text


def test_rendu_echappe_faits_et_hypotheses(complet, session):
    from opsys.console import rentabilite_chantier as port

    with session() as cnx:
        vue = port.lire(cnx, complet['deps'], f.f.AUTH, complet['lead'], f.f.DEVIS)
    vue['chantier']['rentabilite']['cout_reel']['hypotheses'] = ['<script>fictif()</script>']
    vue['chantier']['rentabilite']['cout_reel']['materiaux']['lignes'][0]['materiau'] = '<img src=x>'
    html = port.contenu(vue, '')
    assert '<script>' not in html and '<img src=x>' not in html
    assert '&lt;script&gt;' in html and '&lt;img src=x&gt;' in html


def test_revocation_pendant_rendu_ne_renvoie_pas_chiffres(complet, catalogue, session, monkeypatch):
    from opsys.console import rentabilite_chantier as port

    original = port.contenu

    def rendu(*args):
        html = original(*args)
        with session() as cnx:
            identite.ajouter_role(cnx, f.f.AUTH.utilisateur, 'nathan_owner')
            identite.retirer_role(cnx, f.f.AUTH.utilisateur, 'admin')
        return html

    monkeypatch.setattr(port, 'contenu', rendu)
    r = catalogue.get(_url(complet))
    assert r.status_code == 403 and '486.00' not in r.text


def test_html_trop_volumineux_ne_sort_pas(complet, catalogue, monkeypatch):
    from opsys.console import rentabilite_chantier as port

    monkeypatch.setattr(port, 'contenu', lambda *a: '<p>' + 'x' * 131073 + '</p>')
    r = catalogue.get(_url(complet))
    assert r.status_code == 503 and len(r.content) < 1024
