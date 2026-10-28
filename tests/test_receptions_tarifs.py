"""fictif: true — provenance de réception serveur liée au tarif réel, sans modifier son contrat."""
import importlib.util
from datetime import datetime
from pathlib import Path

import pytest
from sqlalchemy import delete, select, update

from opsys import idempotence, receptions_tarifs, stockage
from opsys.stockage import codec
from opsys.stockage.schema import MUTATIONS_APPLIQUEES, REGISTRES

spec = importlib.util.spec_from_file_location('receptions_tarifs_fixtures',
                                             Path(__file__).with_name('test_console_prix_m6.py'))
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
client_crm = p.client_crm
catalogue = p.catalogue
sources = p.sources


def test_confirmation_conserve_liaison_de_reception(sources, catalogue, session):
    r = p.c.executer(session, p.CONFIRMER, p.preparer(session), 'tarif-reception-fictive')
    assert r['resultat']['accepte'], r
    with session():
        liaisons = list(stockage.maillons('m06-material-control', 'receptions_tarifs'))
    assert len(liaisons) == 1
    assert liaisons[0]['tarif_rang'] == r['resultat']['resultat']['tarif_rang']
    stockage.liberer()
    with session() as cnx:
        liaison = receptions_tarifs.lire(cnx, 0)
        assert liaison == liaisons[0]
        recu = cnx.execute(select(MUTATIONS_APPLIQUEES).where(
            MUTATIONS_APPLIQUEES.c.cle_idempotence == 'tarif-reception-fictive')).mappings().one()
        assert liaison['recu_le'] == recu['recu_le']
        resultat = codec.decoder(recu['reponse'])['resultat']['resultat']
        assert resultat['tarif_source_sha256'] == liaison['tarif_empreinte']
        instant = datetime.fromisoformat(liaison['recu_le'])
        assert instant.utcoffset() is not None and instant.microsecond == 0
        livre = list(stockage.maillons('m06-material-control', 'livre_prix'))
        assert set(livre[0]) == {'materiau_id', 'fournisseur_id', 'prix_unitaire', 'devise',
                                 'date_effet', 'source_document', 'unite'}


def confirmer(session, *, cle='reception-fictive', **kw):
    args = p.preparer(session, **kw)
    r = p.c.executer(session, p.CONFIRMER, args, cle)
    assert r['resultat']['accepte'], r
    return args, r


def test_reprise_et_prix_suivant_conservent_provenance_originale(sources, catalogue, session):
    args, original = confirmer(session)
    with session() as cnx:
        premiere = receptions_tarifs.lire(cnx, 0)
    confirmer(session, cle='suivant-fictif', prix_unitaire='17')
    avant = p.c.m.base._instantane_base(session)
    assert p.c.executer(session, p.CONFIRMER, args, 'reception-fictive') == original
    with session() as cnx:
        assert receptions_tarifs.lire(cnx, 0) == premiere
        assert receptions_tarifs.lire(cnx, 1)['tarif_rang'] == 1
        assert len(stockage.maillons('m06-material-control', 'receptions_tarifs')) == 2
    assert p.c.m.base._instantane_base(session) == avant


@pytest.mark.parametrize('etape', ['liaison', 'audit', 'finalisation'])
def test_panne_apres_ecriture_annule_tarif_liaison_audit_recu(sources, catalogue, session, monkeypatch, etape):
    from opsys import etat

    args = p.preparer(session)
    module, nom = {'liaison': (receptions_tarifs, 'enregistrer'), 'audit': (etat, 'journaliser'),
                   'finalisation': (idempotence, 'finaliser')}[etape]
    fonction = getattr(module, nom)

    def panne(*args, **kwargs):
        fonction(*args, **kwargs)
        raise RuntimeError('après écriture FICTIVE')

    avant = p.c.m.base._instantane_base(session)
    monkeypatch.setattr(module, nom, panne)
    with pytest.raises(RuntimeError, match='après écriture FICTIVE'):
        p.c.executer(session, p.CONFIRMER, args, 'panne-fictive')
    assert p.c.m.base._instantane_base(session) == avant


@pytest.mark.parametrize('cas', ['absent', 'outil', 'statut', 'date_naive', 'date_autre', 'arguments',
                               'reponse_nulle', 'resultat_liste', 'montant_bool', 'rang_bool', 'unite'])
def test_recu_altere_refuse_sans_ecriture(sources, catalogue, session, cas):
    confirmer(session)
    with session() as cnx:
        condition = MUTATIONS_APPLIQUEES.c.cle_idempotence == 'reception-fictive'
        recu = cnx.execute(select(MUTATIONS_APPLIQUEES).where(condition)).mappings().one()
        reponse = codec.decoder(recu['reponse'])
        if cas == 'absent':
            cnx.execute(delete(MUTATIONS_APPLIQUEES).where(condition))
        elif cas == 'outil':
            cnx.execute(update(MUTATIONS_APPLIQUEES).where(condition).values(outil='m6_autre_fictif'))
        elif cas == 'statut':
            cnx.execute(update(MUTATIONS_APPLIQUEES).where(condition).values(statut='en_cours'))
        elif cas in {'date_naive', 'date_autre'}:
            date = '2030-01-01T00:00:00' + ('+00:00' if cas == 'date_autre' else '')
            cnx.execute(update(MUTATIONS_APPLIQUEES).where(condition).values(recu_le=date))
        elif cas == 'arguments':
            cnx.execute(update(MUTATIONS_APPLIQUEES).where(condition).values(empreinte_arguments='f' * 64))
        else:
            if cas == 'reponse_nulle':
                reponse = None
            elif cas == 'resultat_liste':
                reponse['resultat'] = []
            elif cas == 'montant_bool':
                reponse['resultat']['resultat']['prix_unitaire_decimal'] = True
            elif cas == 'rang_bool':
                reponse['resultat']['resultat']['tarif_rang'] = False
            else:
                reponse['resultat']['resultat']['unite'] = 'm'
            cnx.execute(update(MUTATIONS_APPLIQUEES).where(condition).values(reponse=codec.encoder(reponse)))
    avant = p.c.m.base._instantane_base(session)
    with pytest.raises(ValueError, match='Provenance de réception'), session() as cnx:
        receptions_tarifs.lire(cnx, 0)
    assert p.c.m.base._instantane_base(session) == avant


@pytest.mark.parametrize('cas', ['prix', 'doublon', 'preuve', 'autre_recu'])
def test_liaison_ou_prix_altere_refuse(sources, catalogue, session, cas):
    confirmer(session)
    if cas == 'autre_recu':
        confirmer(session, cle='autre-recu-fictif', prix_unitaire='17')
    with session() as cnx:
        condition = ((REGISTRES.c.departement == 'm06-material-control')
                     & (REGISTRES.c.registre == ('livre_prix' if cas == 'prix' else 'receptions_tarifs'))
                     & (REGISTRES.c.rang == 0))
        maillon = codec.decoder(cnx.execute(select(REGISTRES.c.maillon).where(condition)).scalar_one())
        if cas == 'prix':
            maillon['source_document'] = 'SOURCE-CORROMPUE-FICTIVE.pdf'
        elif cas == 'preuve':
            maillon['preuve_sha256'] = 'f' * 64
        elif cas == 'autre_recu':
            autre = stockage.maillons('m06-material-control', 'receptions_tarifs')[1]
            for k in ('appareil', 'cle_idempotence', 'empreinte_arguments', 'recu_le'):
                maillon[k] = autre[k]
            maillon['preuve_sha256'] = receptions_tarifs._sha({
                k: v for k, v in maillon.items() if k != 'preuve_sha256'})
        else:
            stockage.maillons('m06-material-control', 'receptions_tarifs').append(maillon)
        if cas != 'doublon':
            cnx.execute(update(REGISTRES).where(condition).values(maillon=codec.encoder(maillon)))
    avant = p.c.m.base._instantane_base(session)
    with pytest.raises(ValueError, match='Provenance de réception'), session() as cnx:
        receptions_tarifs.lire(cnx, 0)
    assert p.c.m.base._instantane_base(session) == avant


def test_tarif_historique_sans_liaison_reste_non_prouve(sources, catalogue, session):
    from m6_material_control.livre_prix import enregistrer_prix

    with session():
        _, refus = enregistrer_prix('mat-fictif', 'fourn-fictif', 12.5, 'CAD', '2026-01-01',
                                    stockage.maillons('m06-material-control', 'livre_prix'), unite='pi')
        assert refus is None
    avant = p.c.m.base._instantane_base(session)
    with session() as cnx:
        assert receptions_tarifs.lire(cnx, 0) is None
    assert p.c.m.base._instantane_base(session) == avant


@pytest.mark.parametrize('champ,valeur', [('source_document', 'AUTRE-SOURCE-FICTIVE.pdf'),
                                        ('fournisseur_id', 'AUTRE-FOURNISSEUR-FICTIF'),
                                        ('date_effet', '2026-01-02')])
def test_tarif_et_compagnon_rehashes_refusent_recu_intact(sources, catalogue, session, champ, valeur):
    confirmer(session)
    with session() as cnx:
        condition = ((REGISTRES.c.departement == 'm06-material-control')
                     & (REGISTRES.c.registre == 'livre_prix') & (REGISTRES.c.rang == 0))
        prix = codec.decoder(cnx.execute(select(REGISTRES.c.maillon).where(condition)).scalar_one())
        prix[champ] = valeur
        cnx.execute(update(REGISTRES).where(condition).values(maillon=codec.encoder(prix)))
        condition = ((REGISTRES.c.departement == 'm06-material-control')
                     & (REGISTRES.c.registre == 'receptions_tarifs') & (REGISTRES.c.rang == 0))
        liaison = codec.decoder(cnx.execute(select(REGISTRES.c.maillon).where(condition)).scalar_one())
        liaison['tarif_empreinte'] = receptions_tarifs._sha(dict(rang=0, maillon=prix))
        liaison['preuve_sha256'] = receptions_tarifs._sha({
            k: v for k, v in liaison.items() if k != 'preuve_sha256'})
        cnx.execute(update(REGISTRES).where(condition).values(maillon=codec.encoder(liaison)))
    avant = p.c.m.base._instantane_base(session)
    with pytest.raises(ValueError, match='Provenance de réception'), session() as cnx:
        receptions_tarifs.lire(cnx, 0)
    assert p.c.m.base._instantane_base(session) == avant
