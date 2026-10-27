"""fictif: true — producteurs privés, outbox, dispatcher et mémoire de références réels."""
import hashlib
import importlib.util
import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest
from m10_memoire import references_configuration as references

from opsys import evenements, stockage
from opsys.departements import charger_departements


def charger(nom, fichier):
    spec = importlib.util.spec_from_file_location(nom, Path(__file__).with_name(fichier))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


h = charger('catalogue_m10_http', 'test_console_catalogue_m6_http.py')
b = charger('catalogue_m10_cascade', 'test_cascade_devis_accepte.py')
c = charger('catalogue_m10_ports', 'test_console_catalogue_m6.py')
client_crm = h.client_crm
catalogue = h.catalogue
INSTANT = datetime(2031, 1, 1, tzinfo=UTC)
TYPES = {'m3.catalogue_reference', 'm6.catalogue_reference'}


def memoire():
    with stockage.transaction():
        return list(stockage.maillons('m10-memoire', references.REGISTRE))


def publies(session):
    from sqlalchemy import select

    from opsys.stockage import codec
    from opsys.stockage.schema import EVENEMENTS_SORTANTS

    with session() as cnx:
        return [(r.evenement_id, r.type_evenement, codec.decoder(r.charge)) for r in cnx.execute(
            select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.type_evenement.in_(TYPES)))]


def test_cascade_catalogue_modeles_lignes_memoire_sans_contenu_prive(catalogue, session):
    action, choix, _, _, _ = h.preparer_lignes(catalogue, session)
    assert catalogue.post(action, data=choix, follow_redirects=False).status_code == 303
    publications = publies(session)
    assert len(publications) == 3
    assert {charge['source_genre'] for _, _, charge in publications} == set(references.SOURCES)
    for _, _, charge in publications:
        assert set(charge) == references.CHAMPS_REFERENCE
    assert memoire() == []  # publié ne signifie pas reçu
    deps = charger_departements()
    total = b._drainer(deps, INSTANT)
    assert total['echecs'] == total['quarantaines'] == 0, total
    for event_id, _, _ in publications:
        assert b._recu(event_id, 'm10-memoire')['statut'] == 'traite'
    stockage.liberer()
    lignes = memoire()
    assert len(lignes) == 3 and all(m['confidentialite'] == 'SENSITIVE' for m in lignes)
    contenu = json.dumps([publications, lignes], ensure_ascii=False)
    for canari in ('Pose FICTIVE', 'Gouttière FICTIVE', 'Longueur à renseigner', 'admin.fictif', 'prix', 'fournisseur'):
        assert canari not in contenu
    assert set(lignes[0]) == references.CHAMPS_REFERENCE | {
        'type_entree', 'confidentialite', 'ligne_id', 'precedent_ligne_id'}
    avant = h.h.p.m.base._instantane_base(session)
    assert catalogue.post(action, data=choix, follow_redirects=False).status_code == 303
    assert h.h.p.m.base._instantane_base(session) == avant
    for i, (_, type_event, charge) in enumerate(publications):
        producteur = references.SOURCES[charge['source_genre']][0]
        evenements.publier(type_event, producteur, charge, evenement_id=f'copie-fictive-{i}')
    assert b._drainer(deps, INSTANT)['quarantaines'] == 0
    assert memoire() == lignes  # autre ID de livraison, même fait métier
    r = c.executer(session, c.ECRIRE, c.args(materiau_id='mat-additionnel-fictif'),
                   'autre-fictif')
    assert r['resultat']['accepte'], r
    assert b._drainer(deps, INSTANT)['quarantaines'] == 0
    assert len(memoire()) == 4


@pytest.mark.parametrize('producteur', ['modele', 'lignes', 'materiau'])
def test_publication_panne_annule_source_audit_et_recu(catalogue, session, monkeypatch, producteur):
    if producteur == 'lignes':
        resultat = h.h.p.m.direct(session)['resultat']
    avant = h.h.p.m.base._instantane_base(session)

    def panne(*args, **kwargs):
        raise RuntimeError('publication fictive indisponible')

    with monkeypatch.context() as mp:
        mp.setattr(evenements, 'publier', panne)
        with pytest.raises(RuntimeError, match='publication fictive'):
            if producteur == 'modele':
                h.h.p.m.direct(session)
            elif producteur == 'materiau':
                c.direct(session)
            else:
                h.h.p.appel(session, 'enregistrer_lignes_modele', dict(
                    modele_id=resultat['modele_id'], modele_revision=1, modele_source=resultat['source_id'],
                    revision_attendue=0, lignes=[dict(ligne_id='fictif', description='FICTIF',
                                                    materiau_id='fictif', unite='pi')]))
    assert h.h.p.m.base._instantane_base(session) == avant


def test_reference_absente_ou_incoherente_refusee_sans_memoire(catalogue, session):
    assert c.direct(session)['accepte']
    _, type_event, charge = publies(session)[0]
    from m10_memoire import outils

    consommateur = outils.consommateurs()[type_event]
    for champ, valeur in [('horodatage', '2030-01-01T00:00:00+00:00'), ('source_rang', 9999)]:
        faux = {**charge, champ: valeur}
        faux['fait_id'] = hashlib.sha256(
            f'catalogue-reference-v1:{faux["source_genre"]}:{faux["source_rang"]}:'
            f'{faux["source_revision"]}:{faux["source_sha256"]}'.encode()).hexdigest()
        with pytest.raises(ValueError, match='Source de référence'), session():
            consommateur(faux)
        assert memoire() == []
    with pytest.raises(evenements.ChargeInvalide):
        evenements.publier(type_event, 'm06-material-control', {**charge, 'nom': 'CANARI_PRIVE'},
                           evenement_id='faux-fictif')
    assert memoire() == []


def test_memoire_corrompue_et_contradiction_refusees(catalogue, session):
    assert c.direct(session)['accepte']
    b._drainer(charger_departements(), INSTANT)
    original = memoire()
    charge = publies(session)[0][2]
    faux = {**charge, 'source_sha256': '0'*64}
    faux['fait_id'] = hashlib.sha256(
        f'catalogue-reference-v1:{faux["source_genre"]}:{faux["source_rang"]}:'
        f'{faux["source_revision"]}:{faux["source_sha256"]}'.encode()).hexdigest()
    with pytest.raises(ValueError, match='contradictoire'), session():
        references.memoriser(stockage.maillons('m10-memoire', references.REGISTRE), faux)
    assert memoire() == original
    # Une chaîne abîmée n'est jamais « réparée » par la prochaine référence.
    class Journal(list):
        def append(self, valeur, *, rang_attendu):
            assert rang_attendu == len(self)
            super().append(valeur)
    j = Journal(deepcopy(original))
    j[0]['ligne_id'] = '0'*64
    avant = deepcopy(list(j))
    with pytest.raises(ValueError, match='Mémoire de configuration invalide'):
        references.memoriser(j, charge)
    assert j == avant


@pytest.mark.parametrize('genre,champ', [('m3_modeles', 'clauses'), ('m3_lignes', 'precedent'),
                                        ('m6_materiaux', 'nom')])
def test_journal_source_corrompu_refuse_avant_memoire(catalogue, session, genre, champ):
    from m10_memoire import outils
    from sqlalchemy import select, update

    from opsys.stockage import codec
    from opsys.stockage.schema import REGISTRES

    action, choix, _, _, _ = h.preparer_lignes(catalogue, session)
    assert catalogue.post(action, data=choix, follow_redirects=False).status_code == 303
    _, type_event, charge = next(r for r in publies(session) if r[2]['source_genre'] == genre)
    departement, registre, _ = references.SOURCES[genre]
    with session() as cnx:
        condition = ((REGISTRES.c.departement == departement) & (REGISTRES.c.registre == registre)
                     & (REGISTRES.c.rang == charge['source_rang']))
        m = codec.decoder(cnx.execute(select(REGISTRES.c.maillon).where(condition)).scalar_one())
        m[champ] = 'CORRUPTION_PRIVEE_FICTIVE'
        cnx.execute(update(REGISTRES).where(condition).values(maillon=codec.encoder(m)))
    with pytest.raises(ValueError, match='Source de référence configuration invalide'), session():
        outils.consommateurs()[type_event](charge)
    assert memoire() == []


def test_revisions_successives_et_rejeu_non_retroactif(catalogue, session):
    assert c.direct(session)['accepte']
    assert c.direct(session, cle='revision-fictive', valeur=c.args(revision_attendue=1, actif=False))['accepte']
    publications = publies(session)
    assert [charge['source_revision'] for _, _, charge in publications] == [1, 2]
    total = b._drainer(charger_departements(), INSTANT)
    assert total['quarantaines'] == total['echecs'] == 0
    assert [m['source_revision'] for m in memoire()] == [1, 2]
    avant = h.h.p.m.base._instantane_base(session)
    assert c.direct(session)['accepte']  # reçu d'origine conservé, pas une réactivation
    assert h.h.p.m.base._instantane_base(session) == avant
    with session():
        m = stockage.maillons('m06-material-control', 'catalogue_materiaux')
        assert list(m)[-1]['actif'] is False
