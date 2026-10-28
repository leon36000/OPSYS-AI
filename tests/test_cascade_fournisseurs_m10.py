"""fictif: true — sources fournisseurs privées, outbox et mémoire SQL réelles."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from m6_material_control import fournisseurs

from opsys import evenements, stockage
from opsys.departements import charger_departements

spec = importlib.util.spec_from_file_location('memoire_fournisseurs_http',
                                             Path(__file__).with_name('test_console_fournisseurs_m6_http.py'))
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
spec = importlib.util.spec_from_file_location('memoire_fournisseurs_bus',
                                             Path(__file__).with_name('test_cascade_catalogues_m10.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
client_crm = h.client_crm
catalogue = h.catalogue
GENRE = 'm6_fournisseurs'


def publications(session):
    return [(eid, type_event, charge) for eid, type_event, charge in m.publies(session)
            if charge['source_genre'] == GENRE]


def test_http_versions_differees_et_rejeu_sans_contacts(catalogue, session):
    lien, creation, original = h.creer(catalogue)
    action, correction = h.h.form(catalogue.get(lien))
    correction.update(nom='Corrigé FICTIF', nom_action='remplacer')
    assert catalogue.post(action, data=correction, follow_redirects=False).status_code == 303
    pub = publications(session)
    assert len(pub) == 2
    assert [c['source_revision'] for _, _, c in pub] == [1, 2]
    assert m.memoire() == []
    total = m.b._drainer(charger_departements(), m.INSTANT)
    assert total['echecs'] == total['quarantaines'] == 0, total
    stockage.liberer()
    souvenir = m.memoire()
    assert len(souvenir) == 2
    assert [c['source_revision'] for c in souvenir] == [1, 2]
    for eid, _, _ in pub:
        assert m.b._recu(eid, 'm10-memoire')['statut'] == 'traite'
    texte = json.dumps([pub, souvenir], ensure_ascii=False)
    for prive in (original['fournisseur_id'], original['nom'], original['telephone'],
                  original['courriel_commande'], 'Corrigé FICTIF'):
        assert prive not in texte
    avant = h.instantane(session)
    assert catalogue.post(creation, data=original, follow_redirects=False).status_code == 303
    assert h.instantane(session) == avant
    assert m.memoire() == souvenir
    for i, (_, type_event, charge) in enumerate(pub):
        evenements.publier(type_event, 'm06-material-control', charge, evenement_id=f'copie-fournisseur-fictive-{i}')
    total = m.b._drainer(charger_departements(), m.INSTANT)
    assert total['echecs'] == total['quarantaines'] == 0, total
    assert m.memoire() == souvenir


def test_noop_ne_publie_pas_et_panne_annule_tout(catalogue, session, monkeypatch):
    def panne(*args, **kwargs):
        raise RuntimeError('outbox fournisseur FICTIVE indisponible')

    avant = h.instantane(session)
    with monkeypatch.context() as mp:
        mp.setattr(evenements, 'publier', panne)
        with pytest.raises(RuntimeError, match='outbox fournisseur FICTIVE'):
            h.creer(catalogue)
    assert h.instantane(session) == avant
    lien, _, _ = h.creer(catalogue)
    action, correction = h.h.form(catalogue.get(lien))
    correction['nom_action'] = 'remplacer'  # même valeur, intention distincte
    avant = publications(session)
    with session():
        avant_source = list(stockage.maillons('m06-material-control', 'fournisseurs'))
    assert catalogue.post(action, data=correction, follow_redirects=False).status_code == 303
    assert publications(session) == avant
    with session():
        assert list(stockage.maillons('m06-material-control', 'fournisseurs')) == avant_source


def test_ancien_prefixe_preserve_sans_backfill(catalogue, session):
    with session():
        _, refus = fournisseurs.enregistrer_fournisseur('ancien-fictif', 'Ancien FICTIF',
            '2026-01-01T00:00:00+00:00', stockage.maillons('m06-material-control', 'fournisseurs'),
            telephone='ancien\\ncontact FICTIF', categories_vendues=['FICTIF'] * 26,
            delai_habituel_jours=4000)
        assert refus is None
    assert publications(session) == []
    h.creer(catalogue)  # autre identité : le rang global n'est pas une révision de la fiche
    action, correction = h.h.form(catalogue.get(h.BASE + '/ancien-fictif'))
    correction.update(nom='Ancien corrigé FICTIF', nom_action='remplacer')
    assert catalogue.post(action, data=correction, follow_redirects=False).status_code == 303
    pub = publications(session)
    assert [(c['source_rang'], c['source_revision']) for _, _, c in pub] == [(1, 1), (2, 2)]
    total = m.b._drainer(charger_departements(), m.INSTANT)
    assert total['echecs'] == total['quarantaines'] == 0, total
    assert len(m.memoire()) == 2


@pytest.mark.parametrize('champ,valeur', [('source_rang', 9999), ('source_revision', 42),
                                        ('source_sha256', 'f' * 64),
                                        ('horodatage', '2030-01-01T00:00:00+00:00')])
def test_reference_alteree_refusee_sans_memoire(catalogue, session, champ, valeur):
    from m10_memoire import outils

    h.creer(catalogue)
    _, type_event, charge = publications(session)[0]
    faux = {**charge, champ: valeur}
    faux['fait_id'] = hashlib.sha256(
        f'catalogue-reference-v1:{GENRE}:{faux["source_rang"]}:'
        f'{faux["source_revision"]}:{faux["source_sha256"]}'.encode()).hexdigest()
    with pytest.raises(ValueError, match='Source de référence'), session():
        outils.consommateurs()[type_event](faux)
    assert m.memoire() == []
    with pytest.raises(evenements.ChargeInvalide):
        evenements.publier(type_event, 'm06-material-control', {**charge, 'courriel': 'CANARI FICTIF'},
                           evenement_id='champ-prive-fictif')


@pytest.mark.parametrize('corruption', ['champ_herite', 'rang_sql'])
def test_prefixe_sql_corrompu_refuse_meme_si_derniere_entree_intacte(catalogue, session, corruption):
    from m10_memoire import outils
    from sqlalchemy import select, update

    from opsys.stockage import codec
    from opsys.stockage.schema import REGISTRES

    lien, _, _ = h.creer(catalogue)
    action, correction = h.h.form(catalogue.get(lien))
    correction.update(nom='Corrigé FICTIF', nom_action='remplacer')
    assert catalogue.post(action, data=correction, follow_redirects=False).status_code == 303
    _, type_event, charge = publications(session)[-1]
    with session() as cnx:
        condition = ((REGISTRES.c.departement == 'm06-material-control') &
                     (REGISTRES.c.registre == 'fournisseurs') & (REGISTRES.c.rang == 0))
        if corruption == 'champ_herite':
            maillon = codec.decoder(cnx.execute(select(REGISTRES.c.maillon).where(condition)).scalar_one())
            maillon['telephone'] = 'CONTACT-CORROMPU-FICTIF'
            cnx.execute(update(REGISTRES).where(condition).values(maillon=codec.encoder(maillon)))
        else:
            cnx.execute(update(REGISTRES).where(condition).values(rang=3))
    avant = h.instantane(session)
    with pytest.raises(ValueError, match='Source de référence'), session():
        outils.consommateurs()[type_event](charge)
    assert m.memoire() == []
    assert h.instantane(session) == avant
