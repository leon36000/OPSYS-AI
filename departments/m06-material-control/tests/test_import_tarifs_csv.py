"""fictif: true — CSV synthétique; aucune pièce jointe réelle ni prix appliqué."""
import hashlib
import importlib
import importlib.util
import json

import pytest

MAPPING = dict(materiau_id='SKU', unite='Unite', prix_unitaire_decimal='Prix', devise='Devise', date_effet='Date')
SOURCE = b'SKU;Unite;Prix;Devise;Date;Note\ngouttiere.fictive;ft;12.500001;CAD;2026-01-01;PRIVE-FICTIF\n'


def module():
    assert importlib.util.find_spec('m6_material_control.import_tarifs_csv') is not None, 'adaptateur CSV absent'
    return importlib.import_module('m6_material_control.import_tarifs_csv')


def preparer(source=SOURCE, **kw):
    options = dict(mapping_colonnes=MAPPING, separateur=';', fournisseur_id='gentek.fictif',
                   source_document='liste-fictive.csv', jour_reference='2026-10-27')
    options.update(kw)
    return module().preparer(source, **options)


def test_csv_mappe_explicitement_vers_candidats_sources_sans_colonne_privee():
    r = preparer(SOURCE + b'soffite.fictif;ft;1.230000;CAD;2025-01-01;NOTE-SECRETE-FICTIVE\n')
    lot = r['lot']
    assert lot['statut'] == 'A_REVOIR' and lot['candidats_prets'] == 2
    assert [x['numero_ligne'] for x in lot['lignes']] == [2, 3]
    assert [x['candidat']['prix_unitaire_decimal'] for x in lot['lignes']] == ['12.500001', '1.230000']
    assert r['extraction']['mapping_colonnes'] == MAPPING and r['extraction']['separateur'] == ';'
    assert 'PRIVE-FICTIF' not in str(r) and 'NOTE-SECRETE-FICTIVE' not in str(r)


def test_bom_et_lignes_physiques_apres_cellule_citee_multiligne():
    source = b'\xef\xbb\xbfSKU,Unite,Prix,Devise,Date,Note\ngouttiere.fictive,ft,12.50,CAD,2026-01-01,"a\nb"\n'
    source += b'soffite.fictif,ft,1.25,CAD,2025-01-01,note\n'
    r = preparer(source, separateur=',')
    assert [x['numero_ligne'] for x in r['lot']['lignes']] == [2, 4]
    assert r['lot']['source_sha256'] == hashlib.sha256(source).hexdigest()


def test_prix_virgule_reste_a_corriger_sans_conversion_locale():
    r = preparer(SOURCE.replace(b'12.500001', b'12,50'))
    assert r['lot']['statut'] == 'A_CORRIGER' and r['lot']['lignes'][0]['candidat'] is None
    assert r['lot']['lignes'][0]['erreurs'] == ['MONTANT_INVALIDE']


def test_configuration_liee_meme_si_valeurs_mappees_identiques():
    source = b'SKU;SKU2;Unite;Prix;Devise;Date\nmat.fictif;mat.fictif;ft;2.50;CAD;2026-01-01\n'
    r = preparer(source)
    autre = preparer(source, mapping_colonnes=dict(MAPPING, materiau_id='SKU2'))
    assert r['lot'] == autre['lot']
    assert r['extraction']['mapping_colonnes_sha256'] != autre['extraction']['mapping_colonnes_sha256']
    assert r['preparation_sha256'] != autre['preparation_sha256']
    r['extraction']['mapping_colonnes']['materiau_id'] = 'CORROMPU'
    assert preparer(source)['extraction']['mapping_colonnes'] == MAPPING


@pytest.mark.parametrize('source,code', [
    (b'', 'SOURCE_INVALIDE'), (b'\xff', 'CSV_INVALIDE'), (b'x' * 1048577, 'SOURCE_TROP_VOLUMINEUSE'),
    (SOURCE.replace(b'SKU;', b'Prix;'), 'ENTETES_INVALIDES'),
    (SOURCE.replace(b';PRIVE-FICTIF', b''), 'CSV_LIGNE_INVALIDE'),
    (SOURCE.replace(b';PRIVE-FICTIF', b';PRIVE-FICTIF;extra'), 'CSV_LIGNE_INVALIDE'),
    (SOURCE + b'\n', 'CSV_LIGNE_INVALIDE'), (SOURCE + b'"ouvert', 'CSV_INVALIDE'),
    (SOURCE.split(b'\n')[0] + b'\n', 'MAPPING_INVALIDE'),
    (SOURCE.replace(b'PRIVE-FICTIF', b'x' * 4097), 'CSV_TROP_VOLUMINEUX'),
    (SOURCE.split(b'\n')[0] + b'\n' + (SOURCE.split(b'\n')[1] + b'\n') * 51, 'CSV_TROP_VOLUMINEUX'),
])
def test_csv_invalide_refuse_sans_lot_partiel(source, code):
    with pytest.raises(ValueError, match='^' + code + '$'):
        preparer(source)


@pytest.mark.parametrize('options,code', [
    (dict(separateur='auto'), 'ARGUMENTS'), (dict(mapping_colonnes={}), 'MAPPING_COLONNES_INVALIDE'),
    (dict(mapping_colonnes=dict(MAPPING, unite='Absente')), 'MAPPING_COLONNES_INVALIDE'),
    (dict(mapping_colonnes=dict(MAPPING, unite='SKU')), 'MAPPING_COLONNES_INVALIDE'),
    (dict(limite_sortie=True), 'ARGUMENTS'), (dict(limite_sortie=1), 'SORTIE_TROP_VOLUMINEUSE'),
])
def test_mapping_et_quota_explicites(options, code):
    with pytest.raises(ValueError, match='^' + code + '$'):
        preparer(**options)


def test_quota_enveloppe_csv_comprend_la_configuration_pas_seulement_le_lot():
    r = preparer()
    taille_lot = len(json.dumps(r['lot'], ensure_ascii=False, sort_keys=True,
                                separators=(',', ':')).encode('utf-8'))
    with pytest.raises(ValueError, match='^SORTIE_TROP_VOLUMINEUSE$'):
        preparer(limite_sortie=taille_lot)


@pytest.mark.parametrize('source,code', [
    (SOURCE.replace(b'PRIVE-FICTIF', b'\x00PRIVE-FICTIF'), 'CSV_INVALIDE'),
    ((';'.join(['SKU', 'Unite', 'Prix', 'Devise', 'Date'] + [f'Libre-{i}' for i in range(46)])
      + '\n').encode(), 'CSV_TROP_VOLUMINEUX'),
])
def test_binaire_et_nombre_colonnes_bornes(source, code):
    with pytest.raises(ValueError, match='^' + code + '$'):
        preparer(source)


def test_cinquante_enregistrements_acceptes_sans_copier_les_notes():
    source = SOURCE.split(b'\n')[0] + b'\n' + ''.join(
        f'mat-fictif-{i};ft;12.50;CAD;2026-01-01;PRIVE-FICTIF\n' for i in range(50)).encode()
    r = preparer(source)
    assert r['lot']['statut'] == 'A_REVOIR' and r['lot']['candidats_prets'] == 50
    assert r['lot']['lignes'][-1]['numero_ligne'] == 51 and 'PRIVE-FICTIF' not in str(r)
