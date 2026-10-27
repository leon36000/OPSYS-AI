"""fictif: true — réception tarif finalisée → outbox → référence M10 privée."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from sqlalchemy import update

from opsys import evenements, stockage
from opsys.departements import charger_departements
from opsys.stockage import codec
from opsys.stockage.schema import MUTATIONS_APPLIQUEES, REGISTRES


def charger(nom, fichier):
    spec = importlib.util.spec_from_file_location(nom, Path(__file__).with_name(fichier))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


h = charger('cascade_tarifs_http', 'test_console_prix_m6_http.py')
m = charger('cascade_tarifs_bus', 'test_cascade_catalogues_m10.py')
client_crm = h.client_crm
catalogue = h.catalogue
sources = h.sources
GENRE = 'm6_tarifs'


def publications(session):
    return [(eid, typ, c) for eid, typ, c in m.publies(session) if c['source_genre'] == GENRE]


def souvenirs():
    return [c for c in m.memoire() if c['source_genre'] == GENRE]


def test_http_tarifs_differees_vers_memoire_sans_couts(sources, catalogue, session):
    a, formulaire, _ = h.preparer(catalogue, session)
    assert catalogue.post(a, data=formulaire, follow_redirects=False).status_code == 303
    a2, suivant, _ = h.preparer(catalogue, session, prix_unitaire='17')
    assert catalogue.post(a2, data=suivant, follow_redirects=False).status_code == 303
    pub = publications(session)
    assert len(pub) == 2
    assert [c['source_revision'] for _, _, c in pub] == [1, 2]
    assert souvenirs() == []
    total = m.b._drainer(charger_departements(), m.INSTANT)
    assert total['echecs'] == total['quarantaines'] == 0, total
    stockage.liberer()
    souvenir = souvenirs()
    assert len(souvenir) == 2
    for eid, _, _ in pub:
        assert m.b._recu(eid, 'm10-memoire')['statut'] == 'traite'
    texte = json.dumps([pub, souvenir], ensure_ascii=False)
    for prive in ('12.500001', 'fourn-fictif', 'mat-fictif', 'tarif-FICTIF.pdf',
                  'admin.fictif', formulaire['mutation_id']):
        assert prive not in texte
    avant = h.p.c.m.base._instantane_base(session)
    assert catalogue.post(a, data=formulaire, follow_redirects=False).status_code == 303
    assert h.p.c.m.base._instantane_base(session) == avant
    for i, (_, typ, charge) in enumerate(pub):
        evenements.publier(typ, 'm06-material-control', charge, evenement_id=f'copie-tarif-fictive-{i}')
    total = m.b._drainer(charger_departements(), m.INSTANT)
    assert total['echecs'] == total['quarantaines'] == 0, total
    assert souvenirs() == souvenir


def test_publication_panne_apres_recu_final_annule_tout(sources, catalogue, session, monkeypatch):
    args = h.p.preparer(session)
    avant = h.p.c.m.base._instantane_base(session)

    def panne(*args, **kwargs):
        raise RuntimeError('publication tarif FICTIVE')

    monkeypatch.setattr(evenements, 'publier', panne)
    with pytest.raises(RuntimeError, match='publication tarif FICTIVE'):
        h.p.c.executer(session, h.p.CONFIRMER, args, 'panne-fictive')
    assert h.p.c.m.base._instantane_base(session) == avant


def test_recu_non_finalise_interdit_publication_et_annule_tout(sources, catalogue, session, monkeypatch):
    from opsys import idempotence

    args = h.p.preparer(session)
    avant = h.p.c.m.base._instantane_base(session)

    def oublier_finalisation(*args, **kwargs):
        return None

    monkeypatch.setattr(idempotence, 'finaliser', oublier_finalisation)
    r = h.p.c.executer(session, h.p.CONFIRMER, args, 'recu-non-finalise-fictif')
    assert r.get('ok') is False or r.get('resultat', {}).get('accepte') is False
    assert h.p.c.m.base._instantane_base(session) == avant


def test_ancien_prix_sans_reception_non_retro_memorise(sources, catalogue, session):
    from m6_material_control.livre_prix import enregistrer_prix

    with session():
        _, refus = enregistrer_prix('mat-fictif', 'fourn-fictif', 10, 'CAD', '2026-01-01',
                                    stockage.maillons('m06-material-control', 'livre_prix'), unite='pi')
        assert refus is None
    assert publications(session) == []
    r = h.p.c.executer(session, h.p.CONFIRMER, h.p.preparer(session), 'prix-apres-historique-fictif')
    assert r['resultat']['accepte'], r
    pub = publications(session)
    assert len(pub) == 1
    charge = pub[0][2]
    assert charge['source_rang'] == 0  # rang de la réception, pas du prix
    assert charge['source_revision'] == 2  # ordinal SQL du prix réel + 1, pas version commerciale
    with session():
        liaison = stockage.maillons('m06-material-control', 'receptions_tarifs')[0]
    assert charge['horodatage'] == liaison['recu_le']
    total = m.b._drainer(charger_departements(), m.INSTANT)
    assert total['echecs'] == total['quarantaines'] == 0, total
    assert len(souvenirs()) == 1


@pytest.mark.parametrize('cas', ['recu', 'liaison', 'prix', 'rang_sql'])
def test_consommateur_refuse_source_reception_alteree(sources, catalogue, session, cas):
    from m10_memoire import outils

    h.p.c.executer(session, h.p.CONFIRMER, h.p.preparer(session), 'source-tarif-fictive')
    _, typ, charge = publications(session)[0]
    with session() as cnx:
        if cas == 'recu':
            cnx.execute(update(MUTATIONS_APPLIQUEES).where(
                MUTATIONS_APPLIQUEES.c.cle_idempotence == 'source-tarif-fictive').values(statut='en_cours'))
        else:
            condition = ((REGISTRES.c.departement == 'm06-material-control')
                         & (REGISTRES.c.registre == ('livre_prix' if cas == 'prix' else 'receptions_tarifs'))
                         & (REGISTRES.c.rang == 0))
            if cas == 'rang_sql':
                cnx.execute(update(REGISTRES).where(condition).values(rang=3))
            else:
                registre = 'livre_prix' if cas == 'prix' else 'receptions_tarifs'
                maillon = stockage.maillons('m06-material-control', registre)[0]
                maillon['source_document' if cas == 'prix' else 'preuve_sha256'] = 'SOURCE-CORROMPUE-FICTIVE'
                cnx.execute(update(REGISTRES).where(condition).values(maillon=codec.encoder(maillon)))
    avant = h.p.c.m.base._instantane_base(session)
    with pytest.raises(ValueError, match='Source de référence'), session():
        outils.consommateurs()[typ](charge)
    assert souvenirs() == []
    assert h.p.c.m.base._instantane_base(session) == avant


@pytest.mark.parametrize('champ,valeur', [('source_rang', 9999), ('source_revision', 9999),
                                        ('source_sha256', 'f' * 64),
                                        ('horodatage', '2030-01-01T00:00:00+00:00')])
def test_reference_tarif_forgee_refusee(sources, catalogue, session, champ, valeur):
    from m10_memoire import outils

    h.p.c.executer(session, h.p.CONFIRMER, h.p.preparer(session), 'reference-fictive')
    _, typ, charge = publications(session)[0]
    faux = {**charge, champ: valeur}
    faux['fait_id'] = hashlib.sha256(
        f'catalogue-reference-v1:{GENRE}:{faux["source_rang"]}:'
        f'{faux["source_revision"]}:{faux["source_sha256"]}'.encode()).hexdigest()
    with pytest.raises(ValueError, match='Source de référence'), session():
        outils.consommateurs()[typ](faux)
    assert souvenirs() == []
    with pytest.raises(evenements.ChargeInvalide):
        evenements.publier(typ, 'm06-material-control', {**charge, 'cout': 'CANARI-PRIVE'},
                           evenement_id='cout-injecte-fictif')
