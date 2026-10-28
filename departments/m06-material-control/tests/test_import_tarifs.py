"""fictif: true — candidats purs, aucune liste fournisseur réelle ni écriture de prix."""
import hashlib
import importlib
import importlib.util
from copy import deepcopy

import pytest
from m6_material_control import livre_prix


def module():
    assert importlib.util.find_spec('m6_material_control.import_tarifs') is not None, 'préparateur de lot absent'
    return importlib.import_module('m6_material_control.import_tarifs')


def ligne(**kw):
    return dict(dict(numero_ligne=2, materiau_id='gouttiere.fictive', unite='ft',
                     prix_unitaire_decimal='12.500001', devise='CAD', date_effet='2026-01-01'), **kw)


def preparer(lignes=None, **kw):
    options = dict(fournisseur_id='gentek.fictif', source_document='liste-fictive.csv',
                   source_octets=b'SOURCE FICTIVE, mapping declare', jour_reference='2026-10-27')
    options.update(kw)
    return module().preparer([ligne()] if lignes is None else lignes, **options)


def test_candidats_exacts_ordre_source_sans_prix_applique_ni_mutation():
    lignes = [ligne(numero_ligne=8), ligne(numero_ligne=4, materiau_id='soffite.fictif',
                                         date_effet='2025-01-01', prix_unitaire_decimal='1.230000')]
    avant = deepcopy(lignes)
    r = preparer(lignes)
    assert r['statut'] == 'A_REVOIR' and r['candidats_prets'] == 2 and r['lignes_a_corriger'] == 0
    assert [x['numero_ligne'] for x in r['lignes']] == [8, 4]
    assert [x['candidat']['prix_unitaire_decimal'] for x in r['lignes']] == ['12.500001', '1.230000']
    assert all(x['statut'] == 'PRET_POUR_REVUE' and x['erreurs'] == [] for x in r['lignes'])
    assert set(r['avertissements']) == {'EXTRACTION_NON_VERIFIEE', 'CATALOGUE_NON_VERIFIE',
                                       'FOURNISSEUR_NON_VERIFIE', 'AUCUN_PRIX_APPLIQUE'}
    assert r['source_sha256'] == hashlib.sha256(b'SOURCE FICTIVE, mapping declare').hexdigest()
    assert lignes == avant and preparer(lignes) == r


@pytest.mark.parametrize('champ,valeur,code', [
    ('prix_unitaire_decimal', True, 'MONTANT_INVALIDE'),
    ('prix_unitaire_decimal', 12.5, 'MONTANT_INVALIDE'),
    ('prix_unitaire_decimal', '12,50', 'MONTANT_INVALIDE'),
    ('prix_unitaire_decimal', '-1', 'MONTANT_INVALIDE'),
    ('prix_unitaire_decimal', '0', 'MONTANT_INVALIDE'),
    ('prix_unitaire_decimal', 'NaN', 'MONTANT_INVALIDE'),
    ('prix_unitaire_decimal', 'Infinity', 'MONTANT_INVALIDE'),
    ('prix_unitaire_decimal', '1e2', 'MONTANT_INVALIDE'),
    ('prix_unitaire_decimal', '1000000000', 'MONTANT_INVALIDE'),
    ('prix_unitaire_decimal', '1.0000001', 'MONTANT_INVALIDE'),
    ('materiau_id', ' mat.fictif', 'MATERIAU_INVALIDE'),
    ('materiau_id', '..', 'MATERIAU_INVALIDE'),
    ('unite', None, 'UNITE_INVALIDE'),
    ('unite', '', 'UNITE_INVALIDE'),
    ('devise', 'USD', 'DEVISE_NON_SUPPORTEE'),
    ('devise', 'cad', 'DEVISE_NON_SUPPORTEE'),
    ('date_effet', '2026-02-30', 'DATE_INVALIDE'),
    ('date_effet', '2027-01-01', 'DATE_FUTURE'),
    ('numero_ligne', True, 'NUMERO_LIGNE_INVALIDE'),
    ('numero_ligne', 0, 'NUMERO_LIGNE_INVALIDE'),
])
def test_refus_par_ligne_sans_conversion_ou_fallback(champ, valeur, code):
    r = preparer([ligne(**{champ: valeur})])
    assert r['statut'] == 'A_CORRIGER' and r['candidats_prets'] == 0 and r['lignes_a_corriger'] == 1
    assert r['lignes'][0]['candidat'] is None and code in r['lignes'][0]['erreurs']


def test_doublons_symetriques_sans_garder_automatiquement_le_dernier():
    r = preparer([ligne(), ligne(numero_ligne=3, prix_unitaire_decimal='99'),
                 ligne(materiau_id='soffite.fictif'), ligne(numero_ligne=9, materiau_id='vis.fictive')])
    assert r['candidats_prets'] == 1 and r['lignes_a_corriger'] == 3
    assert 'DOUBLON_MATERIAU' in r['lignes'][0]['erreurs'] and 'DOUBLON_MATERIAU' in r['lignes'][1]['erreurs']
    assert 'DOUBLON_LIGNE' in r['lignes'][0]['erreurs'] and 'DOUBLON_LIGNE' in r['lignes'][2]['erreurs']
    assert r['lignes'][3]['candidat']['materiau_id'] == 'vis.fictive'


def test_hashes_couvrent_mapping_source_identite_reference_et_jour():
    r = preparer()
    for options in [dict(source_octets=b'AUTRE SOURCE FICTIVE'), dict(fournisseur_id='royal.fictif'),
                    dict(source_document='autre-fictif.csv'), dict(jour_reference='2026-10-28')]:
        assert preparer(**options)['lot_sha256'] != r['lot_sha256']
    autre = preparer([ligne(prix_unitaire_decimal='12.500002')])
    assert autre['source_sha256'] == r['source_sha256']
    assert autre['mapping_sha256'] != r['mapping_sha256'] and autre['lot_sha256'] != r['lot_sha256']
    # La copie ne peut pas modifier une préparation ultérieure ou le mapping d’entrée.
    r['lignes'][0]['candidat']['unite'] = 'UNITE-CORROMPUE'
    r['avertissements'].clear()
    assert preparer()['lignes'][0]['candidat']['unite'] == 'ft' and preparer()['avertissements']


@pytest.mark.parametrize('lignes,code', [([], 'MAPPING_INVALIDE'), ([ligne()] * 51, 'MAPPING_TROP_VOLUMINEUX'),
    ([dict(ligne(), champ_surprise='fictif')], 'MAPPING_INVALIDE'), ([None], 'MAPPING_INVALIDE'),
    ([ligne(unite={'unite': 'ft'})], 'MAPPING_INVALIDE'), ([ligne(unite='x' * 4097)], 'MAPPING_TROP_VOLUMINEUX')])
def test_structure_globale_bornee_sans_reparer_le_mapping(lignes, code):
    with pytest.raises(module().Refus, match='^' + code + '$'):
        preparer(lignes)


@pytest.mark.parametrize('options,code', [
    (dict(source_octets=b''), 'SOURCE_INVALIDE'), (dict(source_octets='fictif'), 'SOURCE_INVALIDE'),
    (dict(source_octets=b'x' * (1048576 + 1)), 'SOURCE_TROP_VOLUMINEUSE'),
    (dict(source_document=None), 'SOURCE_INVALIDE'), (dict(fournisseur_id=''), 'ARGUMENTS'),
    (dict(jour_reference='2026-02-30'), 'ARGUMENTS'), (dict(limite_sortie=True), 'ARGUMENTS'),
    (dict(limite_sortie=1), 'SORTIE_TROP_VOLUMINEUSE'),
])
def test_enveloppe_source_et_quota(options, code):
    with pytest.raises(module().Refus, match='^' + code + '$'):
        preparer(**options)


def test_candidat_conserve_contrat_du_livre_sans_ecrire_dans_un_journal_externe():
    r = preparer()
    c = r['lignes'][0]['candidat']
    journal_prive = []
    entree, refus = livre_prix.enregistrer_prix(c['materiau_id'], c['fournisseur_id'],
        float(c['prix_unitaire_decimal']), c['devise'], c['date_effet'], journal_prive,
        source_document=c['source_document'], unite=c['unite'])
    assert refus is None and len(journal_prive) == 1 and entree['prix_unitaire'] == 12.500001
    assert r['statut'] == 'A_REVOIR' and 'AUCUN_PRIX_APPLIQUE' in r['avertissements']


def test_snapshot_mapping_reste_lie_aux_candidats_si_appelant_change_ses_lignes(monkeypatch):
    lignes = [ligne(), ligne(numero_ligne=3, materiau_id='soffite.fictif', prix_unitaire_decimal='2.000000')]
    original = livre_prix.enregistrer_prix
    avant = preparer(deepcopy(lignes))

    def valider(*args, **kw):
        lignes[1]['prix_unitaire_decimal'] = '99'
        return original(*args, **kw)

    monkeypatch.setattr(livre_prix, 'enregistrer_prix', valider)
    r = preparer(lignes)
    assert r['mapping_sha256'] == avant['mapping_sha256']
    assert r == avant
