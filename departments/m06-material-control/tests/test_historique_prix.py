"""fictif: true — historique propriétaire des versions, pas sélection de coût ou achat."""
import importlib
from copy import deepcopy
from decimal import Decimal

import pytest
from m6_material_control import livre_prix

FICTIF = True


def domaine():
    return importlib.import_module('m6_material_control.historique_prix')


def ligne(prix=10.25, *, materiau='gouttiere.fictive', fournisseur='gentek.fictif',
          jour='2030-06-03', unite='ft', devise='CAD', document='liste.fictive.pdf'):
    registre = []
    _, refus = livre_prix.enregistrer_prix(materiau, fournisseur, prix, devise, jour, registre,
                                          source_document=document, unite=unite)
    assert refus is None
    return registre[0]


def lire(lignes, **options):
    return domaine().lire(lignes, 'gouttiere.fictive', 'gentek.fictif', **options)


def test_ordre_ecritures_couple_exact_sans_reselection_par_date():
    lignes = [(0, ligne()), (1, ligne(99, fournisseur='royal.fictif')),
              (2, ligne(12.5, jour='2029-01-01')), (3, ligne(77, materiau='autre.fictif'))]
    avant = deepcopy(lignes)
    r = lire(lignes)
    assert r['total'] == 2 and r['suivant'] is None
    assert [x['rang_sql'] for x in r['lignes']] == [0, 2]
    assert [x['version_du_couple'] for x in r['lignes']] == [1, 2]
    assert [x['derniere_ecriture'] for x in r['lignes']] == [False, True]
    assert [x['prix_unitaire_decimal'] for x in r['lignes']] == ['10.25', '12.5']
    assert r['lignes'][-1]['date_effet'] == '2029-01-01' and lignes == avant
    assert all(len(x['source_entree']) == 64 for x in r['lignes'])


def test_unite_absente_devise_etrangere_date_declaree_et_source_non_authentifiee():
    r = lire([(0, ligne(unite=None, devise='USD', document=None, jour='date déclarée'))])
    x = r['lignes'][0]
    assert x['unite'] is None and 'UNITE_NON_DOCUMENTEE' in x['avertissements']
    assert x['devise'] == 'USD' and x['prix_unitaire_decimal'] == '10.25'
    assert x['date_effet'] == 'date déclarée' and 'DATE_NON_ISO_DECLAREE' in x['avertissements']
    assert x['marquage_source'] == 'FALLBACK_PRICE_BOOK' and x['source_document'] is None
    declaree = lire([(0, ligne(document='fichier.fictif.pdf'))])['lignes'][0]
    assert declaree['marquage_source'] == 'SOURCE_DECLAREE'
    assert 'document_verifie' not in declaree and 'horodatage_reception' not in declaree


def test_montants_sources_exacts_sans_arrondi_ou_zero_de_secours():
    r = lire([(0, ligne(0.0000001)), (1, ligne(10 ** 100)), (2, ligne(1e-300))])
    a, b, c = r['lignes']
    assert a['prix_unitaire_decimal'] == '0.0000001'
    assert Decimal(a['prix_unitaire_decimal']) == Decimal('0.0000001')
    for x in (b, c):
        assert x['prix_unitaire_decimal'] is None and 'PRIX_NON_REPRESENTABLE' in x['avertissements']
    assert c['derniere_ecriture'] is True


def test_pages_source_liee_au_couple_et_snapshot_entier():
    lignes = [(0, ligne()), (1, ligne(11)), (2, ligne(12))]
    premier = lire(lignes, limite=1)
    second = lire(lignes, debut=1, limite=1, source_attendue=premier['source'])
    assert premier['suivant'] == 1 and second['lignes'][0]['version_du_couple'] == 2
    fin = lire(lignes, debut=3, limite=1, source_attendue=premier['source'])
    assert fin['total'] == 3 and fin['lignes'] == [] and fin['suivant'] is None
    with pytest.raises(ValueError, match='SOURCE-PERIMEE'):
        domaine().lire(lignes, 'gouttiere.fictive', 'royal.fictif', debut=1, source_attendue=premier['source'])
    lignes.append((3, ligne(1, fournisseur='autre.fictif')))
    with pytest.raises(ValueError, match='SOURCE-PERIMEE'):
        lire(lignes, debut=1, source_attendue=premier['source'])


def test_couple_sans_tarif_et_copies_sans_mutation():
    lignes = [(0, ligne())]
    vide = domaine().lire(lignes, 'autre.fictif', 'gentek.fictif')
    assert vide['total'] == 0 and vide['lignes'] == []
    lu = lire(lignes)
    lu['lignes'][0]['prix_unitaire_decimal'] = '999'
    lu['avertissements'].clear()
    relu = lire(lignes)
    assert relu['lignes'][0]['prix_unitaire_decimal'] == '10.25' and relu['avertissements']
    assert lignes[0][1]['prix_unitaire'] == 10.25


@pytest.mark.parametrize('options', [{'debut': 1}, {'debut': True}, {'debut': -1}, {'limite': 0},
    {'limite': 51}, {'limite': True}, {'source_attendue': 'faux'}, {'limite_sortie': True}])
def test_parametres_fermes(options):
    with pytest.raises(ValueError, match='ARGUMENTS'):
        lire([(0, ligne())], **options)


@pytest.mark.parametrize('changement', ['bool', 'negatif', 'infini', 'cle', 'id', 'rang', 'ordre'])
def test_corruption_source_meme_hors_page_refusee(changement):
    lignes = [(0, ligne()), (1, ligne(11))]
    if changement == 'bool':
        lignes[1][1]['prix_unitaire'] = True
    elif changement == 'negatif':
        lignes[1][1]['prix_unitaire'] = -1
    elif changement == 'infini':
        lignes[1][1]['prix_unitaire'] = float('inf')
    elif changement == 'cle':
        lignes[1][1]['coordonnees_privees'] = 'NE PAS COPIER FICTIF'
    elif changement == 'id':
        lignes[1][1]['materiau_id'] = ''
    elif changement == 'rang':
        lignes[1] = (3, lignes[1][1])
    else:
        lignes.reverse()
    with pytest.raises(ValueError, match='SOURCE-INVALIDE'):
        lire(lignes, limite=1)


@pytest.mark.parametrize('quota', ['lignes', 'octets', 'sortie'])
def test_quotas_utf8_sources_et_sortie(monkeypatch, quota):
    m = domaine()
    lignes = [(0, ligne(document='é' * 200))]
    if quota == 'sortie':
        with pytest.raises(ValueError, match='SORTIE-TROP-VOLUMINEUSE'):
            lire(lignes, limite_sortie=10)
    else:
        monkeypatch.setattr(m, 'MAX_SOURCES' if quota == 'lignes' else 'MAX_OCTETS', 1)
        with pytest.raises(ValueError, match='SOURCES-TROP-VOLUMINEUSES'):
            lire(lignes if quota == 'octets' else lignes + [(1, ligne())])
