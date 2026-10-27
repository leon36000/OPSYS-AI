"""fictif: true — référence historique, sans coordonnées dans la projection."""
from copy import deepcopy

import pytest
from m6_material_control import fournisseurs
from m6_material_control import references_fournisseurs as references


def journal():
    lignes = []
    _, refus = fournisseurs.enregistrer_fournisseur('fictif', 'FICTIF', '2026-01-01T00:00:00+00:00', lignes,
        telephone='514\n5550142', categories_vendues=['FICTIF'] * 26, delai_habituel_jours=4000)
    assert refus is None
    lignes.append(dict(fournisseur_id='fictif', type_entree='fournisseur_maj', nom='Corrigé FICTIF',
                       horodatage='2026-01-02T00:00:00+00:00'))
    return lignes


def test_projection_couvre_heritage_et_reste_historique():
    lignes = journal()
    avant = deepcopy(lignes)
    premier, second = references.projeter(lignes, 0), references.projeter(lignes, 1)
    assert premier['revision'] == 1 and second['revision'] == 2
    assert premier['source_id'] != second['source_id']
    assert set(second) == {'source_id', 'revision', 'horodatage'}
    assert second == references.projeter([dict(reversed(list(ligne.items()))) for ligne in lignes], 1)
    assert lignes == avant
    lignes.append(dict(fournisseur_id='autre-fictif', nom='Autre FICTIF', type_entree='fournisseur_cree',
                       horodatage='2026-01-03T00:00:00+00:00'))
    assert references.projeter(lignes, 1) == second
    assert references.projeter(lignes, 2)['revision'] == 1
    lignes[0]['telephone'] = 'AUTRE FICTIF'
    assert references.projeter(lignes, 1)['source_id'] != second['source_id']


@pytest.mark.parametrize('cas', ['rang', 'bool', 'orphelin', 'doublon', 'champ', 'date', 'fiche'])
def test_sources_invalides_refusees_sans_mutation(cas):
    lignes = journal()
    rang = 1
    if cas == 'rang':
        rang = 2
    elif cas == 'bool':
        rang = True
    elif cas == 'orphelin':
        lignes[0]['type_entree'] = 'fournisseur_maj'
    elif cas == 'doublon':
        lignes[1]['type_entree'] = 'fournisseur_cree'
    elif cas == 'champ':
        lignes[0]['prix'] = 50
    elif cas == 'date':
        lignes[1]['horodatage'] = '2026-01-02T00:00:00'
    else:
        lignes[0]['categories_vendues'] = [12]
    avant = deepcopy(lignes)
    with pytest.raises(ValueError, match='Source de référence fournisseur'):
        references.projeter(lignes, rang)
    assert lignes == avant


def test_bornes_avant_iteration_et_sur_octets(monkeypatch):
    class TropGrand:
        def __len__(self):
            return 10001

        def __iter__(self):
            raise AssertionError('Ne doit pas lire au-delà de la borne')

    with pytest.raises(ValueError, match='hors borne'):
        references.projeter(TropGrand(), 0)
    monkeypatch.setattr(references, 'MAX_OCTETS', 50)
    with pytest.raises(ValueError, match='invalide'):
        references.projeter(journal(), 1)
