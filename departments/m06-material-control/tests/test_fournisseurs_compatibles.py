"""Choix fournisseur déterministe et sans défaut, sources fictives."""
from copy import deepcopy

import pytest
from m6_material_control.tarif_soumission import SelectionTarifRefusee, fournisseurs_compatibles


def sources(nombre=2):
    prix, fiches = [], []
    for i in range(nombre):
        ident = f'fictif-{i:03}'
        prix.append((i, dict(materiau_id='mat-fictif', fournisseur_id=ident, unite='pi',
                             prix_unitaire=10+i, devise='CAD', date_effet='2026-01-01')))
        fiches.append(dict(type_entree='fournisseur_cree', fournisseur_id=ident, nom=f'Fournisseur FICTIF {i}'))
    return prix, fiches


def test_noms_courants_sans_coordonnees_ni_prix_et_sans_mutation():
    prix, fiches = sources()
    fiches.append(dict(type_entree='fournisseur_maj', fournisseur_id='fictif-000', nom='Nom FICTIF corrigé',
                       courriel_commande='prive@example.test'))
    avant = deepcopy((prix, fiches))
    r = fournisseurs_compatibles(prix, fiches, 'mat-fictif', 'pi', '2026-10-27')
    assert r['fournisseurs'] == [dict(fournisseur_id='fictif-000', nom='Nom FICTIF corrigé'),
                                dict(fournisseur_id='fictif-001', nom='Fournisseur FICTIF 1')]
    assert r['indisponibles'] == [] and (prix, fiches) == avant
    assert 'prive@' not in repr(r) and 'prix_unitaire' not in repr(r)


@pytest.mark.parametrize('modif,raison', [({'date_effet':'2099-01-01'}, 'date_future'),
    ({'unite':'m'}, 'unite_absente_ou_differente'), ({'prix_unitaire':-1}, 'prix_invalide'),
    ({'devise':'USD'}, 'devise_non_supportee')])
def test_dernier_invalide_exclu_sans_repli(modif, raison):
    prix, fiches = sources()
    prix.append((2, {**prix[0][1], **modif}))
    r = fournisseurs_compatibles(prix, fiches, 'mat-fictif', 'pi', '2026-10-27')
    assert [f['fournisseur_id'] for f in r['fournisseurs']] == ['fictif-001']
    assert r['indisponibles'] == [dict(fournisseur_id='fictif-000', raison=raison)]


def test_absent_inconnu_et_limites():
    prix, fiches = sources(1)
    r = fournisseurs_compatibles(prix, [], 'mat-fictif', 'pi', '2026-10-27')
    assert r['fournisseurs'] == [] and r['indisponibles'][0]['raison'] == 'fournisseur_inconnu'
    assert fournisseurs_compatibles([], [], 'mat-fictif', 'pi', '2026-10-27')['fournisseurs'] == []
    assert len(fournisseurs_compatibles(*sources(100), 'mat-fictif', 'pi', '2026-10-27')['fournisseurs']) == 100
    with pytest.raises(SelectionTarifRefusee, match='sources_trop_volumineuses'):
        fournisseurs_compatibles(*sources(101), 'mat-fictif', 'pi', '2026-10-27')
    prix.append((1, {'prix_unitaire': 1}))
    with pytest.raises(SelectionTarifRefusee, match='source_invalide'):
        fournisseurs_compatibles(prix, fiches, 'mat-fictif', 'pi', '2026-10-27')


@pytest.mark.parametrize('maillon', [dict(type_entree='fournisseur_maj', nom='Correction FICTIVE'),
    dict(type_entree='inconnu', fournisseur_id='fictif-000'),
    dict(type_entree='fournisseur_maj', fournisseur_id='inconnu'),
    dict(type_entree='fournisseur_cree', fournisseur_id='fictif-000'), None])
def test_corruption_fournisseur_bloque_ancien_libelle(maillon):
    prix, fiches = sources()
    fiches.append(maillon)
    with pytest.raises(SelectionTarifRefusee, match='source_invalide'):
        fournisseurs_compatibles(prix, fiches, 'mat-fictif', 'pi', '2026-10-27')
