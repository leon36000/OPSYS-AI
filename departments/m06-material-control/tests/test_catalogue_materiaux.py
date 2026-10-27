"""fictif: true — aucune donnée ni prix fournisseur réel."""
from copy import deepcopy

import pytest
from m6_material_control import catalogue_materiaux as c


def fiche(**kw):
    return dict(materiau_id='mat-fictif', nom='Gouttière FICTIVE', unite='pi', actif=True,
                raison='Catalogue de test FICTIF', auteur='admin-fictif',
                horodatage='2026-10-27T10:00:00+00:00', revision_attendue=0, **kw)


def modifier(j, **kw):
    args = fiche()
    args.update(kw)
    return c.enregistrer(j, **args)


def test_versions_inactivation_reactivation_et_copies():
    j = []
    v1 = modifier(j)
    v1['nom'] = 'ne modifie pas le journal'
    assert c.lire(j, 'mat-fictif')['nom'] == 'Gouttière FICTIVE'
    modifier(j, revision_attendue=1, nom='Gouttière corrigée FICTIVE', actif=False)
    assert c.lister(j) == {'materiaux': [], 'total': 0, 'suivant': None}
    assert c.lire(j, 'mat-fictif', revision=1)['nom'] == 'Gouttière FICTIVE'
    assert c.lister(j, actifs_seulement=False)['total'] == 1
    modifier(j, revision_attendue=2)
    page = c.lister(j)
    assert page['materiaux'][0]['revision'] == 3
    page['materiaux'][0]['unite'] = 'm'
    assert c.lire(j, 'mat-fictif')['unite'] == 'pi'


@pytest.mark.parametrize('kw,code', [
    ({'revision_attendue': 0}, 'REVISION-PERIMEE'),
    ({'revision_attendue': 1, 'unite': 'm'}, 'UNITE-IMMUABLE'),
    ({'revision_attendue': True}, 'ARGUMENTS'),
    ({'nom': ''}, 'ARGUMENTS'), ({'nom': 'a\nb'}, 'ARGUMENTS'),
    ({'actif': 1}, 'ARGUMENTS'), ({'auteur': ''}, 'ARGUMENTS'),
    ({'raison': 'x' * 501}, 'ARGUMENTS'), ({'materiau_id': '../x'}, 'ARGUMENTS'),
    ({'horodatage': '2026-10-27'}, 'ARGUMENTS'), ({'horodatage': 'faux'}, 'ARGUMENTS'),
])
def test_refus_sans_effet(kw, code):
    j = []
    modifier(j)
    avant = deepcopy(j)
    with pytest.raises(c.CatalogueRefuse, match=code):
        modifier(j, **kw)
    assert j == avant


@pytest.mark.parametrize('cas', ['hash', 'rang', 'revision', 'type', 'unite', 'extra', 'ordre', 'auteur'])
def test_source_corrompue_bloque_lecture_liste_ecriture(cas):
    j = []
    modifier(j)
    modifier(j, revision_attendue=1, nom='Correction FICTIVE')
    if cas == 'ordre':
        j.reverse()
    else:
        cle, valeur = {'hash': ('source_id', '0'*64), 'rang': ('rang', True),
                       'revision': ('revision', 3), 'type': ('type_entree', 'autre'),
                       'unite': ('unite', 'm'), 'extra': ('prix', 3), 'auteur': ('auteur', '')}[cas]
        j[-1][cle] = valeur
        if cas in {'unite', 'revision'}:
            j[-1]['source_id'] = c._empreinte(j[-1])  # hash correct ne suffit pas
    avant = deepcopy(j)
    for operation in [lambda: c.lire(j, 'mat-fictif'), lambda: c.lister(j),
                      lambda: modifier(j, revision_attendue=2)]:
        with pytest.raises(c.CatalogueRefuse, match='SOURCE-INVALIDE'):
            operation()
        assert j == avant


def test_pagination_et_borne_avant_iteration():
    j = []
    for i in range(4):
        modifier(j, materiau_id=f'mat-fictif-{i}')
    page = c.lister(j, limite=2)
    assert [m['materiau_id'] for m in page['materiaux']] == ['mat-fictif-0', 'mat-fictif-1']
    assert page['total'] == 4 and page['suivant'] == 2
    assert c.lister(j, debut=2, limite=2)['suivant'] is None
    with pytest.raises(c.CatalogueRefuse, match='ARGUMENTS'):
        c.lister(j, limite=51)

    class TropGrand:
        def __len__(self):
            return c.MAX_SOURCES + 1

        def __iter__(self):
            raise AssertionError('Ne pas copier une source hors borne')

    with pytest.raises(c.CatalogueRefuse, match='SOURCES-TROP-VOLUMINEUSES'):
        c.lister(TropGrand())


def test_journal_sqlite_reouverture_rollback_et_cas(tmp_path, monkeypatch):
    from opsys import stockage

    url = f'sqlite:///{tmp_path / "catalogue-fictif.db"}'
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    with stockage.transaction():
        modifier(stockage.maillons('m06-material-control', c.REGISTRE))
    stockage.liberer()
    with stockage.transaction():
        journal = stockage.maillons('m06-material-control', c.REGISTRE)
        assert c.lire(journal, 'mat-fictif')['revision'] == 1
        modifier(journal, revision_attendue=1, nom='Corrigé FICTIF')
    with pytest.raises(RuntimeError, match='annulation fictive'), stockage.transaction():
        modifier(stockage.maillons('m06-material-control', c.REGISTRE), revision_attendue=2, actif=False)
        raise RuntimeError('annulation fictive')
    with stockage.transaction():
        journal = stockage.maillons('m06-material-control', c.REGISTRE)
        assert c.lire(journal, 'mat-fictif')['revision'] == 2
        assert c.lire(journal, 'mat-fictif')['actif'] is True
        with pytest.raises(c.CatalogueRefuse, match='REVISION-PERIMEE'):
            modifier(journal, revision_attendue=1)
        assert len(journal) == 2
