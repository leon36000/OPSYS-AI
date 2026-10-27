"""fictif: true — lecture M10 du devis réel, port privé sans effet ni décision."""
import importlib.util
from importlib import import_module
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('memoire_chantier_fixture',
    Path(__file__).with_name('test_console_proposition_chantier.py'))
p = importlib.util.module_from_spec(spec)
spec.loader.exec_module(p)
pret, affaire, catalogue, client_crm = p.pret, p.affaire, p.catalogue, p.client_crm


def test_memoire_du_devis_exact_par_vrai_t0_sans_ecriture(pret, session):
    port = import_module('opsys.console.memoire_chantier')
    avant = p.m.base._instantane_base(session)
    with session() as cnx:
        r = port.lire(cnx, pret['deps'], p.AUTH, pret['lead'], p.DEVIS)
        r2 = port.lire(cnx, pret['deps'], p.AUTH, pret['lead'], p.DEVIS)
    assert r['etat'] == 'LIE' and r['affaire_id'] == pret['lead']
    assert r['paquet']['affaire_id'] == pret['lead']
    assert r['paquet']['confidentialite']['agent'] is None
    assert r['reference_devis'] and r['empreinte'] == r2['empreinte']
    assert len(r['paquet']['couches']) == 4
    for couche in r['paquet']['couches']:
        assert couche['nb_total'] == couche['nb_inclus'] + couche['nb_omis']
        assert all(f['confidentialite'] not in {'FINANCIAL', 'CLIENT_PRIVATE'} for f in couche['faits'])
    assert p.m.base._instantane_base(session) == avant


def _reecrire(cnx, changer):
    from m10_memoire import registre
    from sqlalchemy import delete

    from opsys import stockage
    from opsys.stockage.schema import REGISTRES

    lignes = registre.Registre(stockage.maillons('m10-memoire', 'evenements')).lire()
    nouvelles = changer(lignes)
    cnx.execute(delete(REGISTRES).where((REGISTRES.c.departement == 'm10-memoire')
        & (REGISTRES.c.registre == 'evenements')))
    reg = registre.Registre(stockage.maillons('m10-memoire', 'evenements'))
    for ligne in nouvelles:
        reg.ajouter(ligne)
    assert reg.valider_chaine()[0] is True


@pytest.mark.parametrize('defaut', ['absent', 'autre_lead', 'autre_heure', 'autre_chantier'])
def test_ancre_devis_absente_ou_contradictoire(pret, session, defaut):
    from m10_memoire import etapes

    port = import_module('opsys.console.memoire_chantier')

    def changer(lignes):
        presentes = []
        for ligne in lignes:
            if ligne.get('devis_id') == p.DEVIS:
                if defaut == 'absent':
                    continue
                if ligne.get('type_evenement') == etapes.TYPE_DEVIS_ACCEPTE:
                    if defaut == 'autre_lead':
                        ligne['lead_id'] = 'autre-affaire-fictive'
                    elif defaut == 'autre_chantier':
                        ligne['chantier_id'] = 'CHANTIER-ETRANGER-FICTIF'
                    else:
                        ligne['horodatage'] = '2020-01-01T00:00:00+00:00'
            presentes.append(ligne)
        return presentes

    with session() as cnx:
        _reecrire(cnx, changer)
    avant = p.m.base._instantane_base(session)
    with session() as cnx:
        if defaut == 'absent':
            r = port.lire(cnx, pret['deps'], p.AUTH, pret['lead'], p.DEVIS)
            assert r['etat'] == 'DEVIS_NON_MEMORISE' and r['reference_devis'] is None
            assert r['paquet']['affaire_id'] == pret['lead']
        else:
            with pytest.raises(p.v.port.Refus, match='MEMOIRE-ANCRE-INCOHERENTE'):
                port.lire(cnx, pret['deps'], p.AUTH, pret['lead'], p.DEVIS)
    assert p.m.base._instantane_base(session) == avant


@pytest.mark.parametrize('defaut', ['role', 'expire', 'devis_etranger'])
def test_authorite_et_devis_exacts_avant_registres_m10(pret, session, monkeypatch, defaut):
    from dataclasses import replace

    from opsys import identite

    port = import_module('opsys.console.memoire_chantier')
    auth = p.AUTH
    if defaut == 'role':
        with session() as cnx:
            identite.ajouter_role(cnx, auth.utilisateur, 'nathan_owner')
            identite.retirer_role(cnx, auth.utilisateur, 'admin')
    elif defaut == 'expire':
        auth = replace(auth, expire=0)
    monkeypatch.setattr(port, '_sources', lambda *_: pytest.fail('source M10 lue avant autorité/ancre'))
    avant = p.m.base._instantane_base(session)
    with session() as cnx, pytest.raises((PermissionError, p.v.port.Refus)):
        devis = 'devis-fictif-absent' if defaut == 'devis_etranger' else p.DEVIS
        port.lire(cnx, pret['deps'], auth, pret['lead'], devis)
    assert p.m.base._instantane_base(session) == avant


@pytest.mark.parametrize('defaut', ['affaire', 'couches', 'compteurs', 'confidentialite', 'volume'])
def test_projection_refusee_sans_perdre_les_avertissements(pret, session, monkeypatch, defaut):
    port = import_module('opsys.console.memoire_chantier')
    original = port._paquet

    def alterer(*args):
        r = original(*args)
        if defaut == 'affaire':
            r['affaire_id'] = 'autre-affaire-fictive'
        elif defaut == 'couches':
            r['couches'].pop()
        elif defaut == 'compteurs':
            r['couches'][0]['nb_omis'] += 1
        elif defaut == 'confidentialite':
            r['confidentialite']['agent'] = 'm04-field-ops'
        else:
            r['consolidation']['hors_borne'] = 'x'*66000
        return r

    monkeypatch.setattr(port, '_paquet', alterer)
    avant = p.m.base._instantane_base(session)
    with session() as cnx, pytest.raises(p.v.port.Refus):
        port.lire(cnx, pret['deps'], p.AUTH, pret['lead'], p.DEVIS)
    assert p.m.base._instantane_base(session) == avant


def test_tetes_changent_pendant_lecture_refus(pret, session, monkeypatch):
    from m10_memoire import registre

    from opsys import stockage

    port = import_module('opsys.console.memoire_chantier')
    original = port._paquet

    def changer(*args):
        r = original(*args)
        reg = registre.Registre(stockage.maillons('m10-memoire', 'evenements'))
        copie = next(m for m in reg.lire() if m.get('devis_id') == p.DEVIS)
        copie['devis_id'] = 'DEVIS-NOUVEAU-FICTIF'
        reg.ajouter(copie)
        return r

    monkeypatch.setattr(port, '_paquet', changer)
    with session() as cnx, pytest.raises(p.v.port.Refus, match='SOURCE-MODIFIEE'):
        port.lire(cnx, pret['deps'], p.AUTH, pret['lead'], p.DEVIS)


def test_snapshot_reellement_consomme_ne_peut_etre_substitue_puis_restaure(pret, session, monkeypatch):
    from m10_memoire import registre
    from sqlalchemy import delete

    from opsys import stockage
    from opsys.stockage.schema import REGISTRES

    port = import_module('opsys.console.memoire_chantier')
    original = port._paquet

    def substituer(*args):
        reg = registre.Registre(stockage.maillons('m10-memoire', 'evenements'))
        rang_initial = len(reg.lire())
        copie = next(m for m in reg.lire() if m.get('devis_id') == p.DEVIS)
        copie['devis_id'] = 'DEVIS-SUBSTITUE-FICTIF'
        reg.ajouter(copie)
        try:
            return original(*args)
        finally:
            cnx = stockage.connexion_courante()
            cnx.execute(delete(REGISTRES).where((REGISTRES.c.departement == 'm10-memoire')
                & (REGISTRES.c.registre == 'evenements') & (REGISTRES.c.rang >= rang_initial)))

    monkeypatch.setattr(port, '_paquet', substituer)
    avant = p.m.base._instantane_base(session)
    with session() as cnx, pytest.raises(p.v.port.Refus, match='SOURCE-MODIFIEE'):
        port.lire(cnx, pret['deps'], p.AUTH, pret['lead'], p.DEVIS)
    assert p.m.base._instantane_base(session) == avant


def test_quota_m10_avant_decodage_ou_assemblage(pret, session, monkeypatch):
    from m10_memoire import registre
    from sqlalchemy import update

    from opsys.stockage.schema import REGISTRES

    port = import_module('opsys.console.memoire_chantier')
    with session() as cnx:
        cnx.execute(update(REGISTRES).where((REGISTRES.c.departement == 'm10-memoire')
            & (REGISTRES.c.registre == 'evenements') & (REGISTRES.c.rang == 0)).values(maillon='x' * 8388609))
    monkeypatch.setattr(registre, 'Registre', lambda *_: pytest.fail('décodage M10 avant quota SQL'))
    avant = p.m.base._instantane_base(session)
    with session() as cnx, pytest.raises(p.v.port.Refus, match='SOURCE-TROP-VOLUMINEUSE'):
        port.lire(cnx, pret['deps'], p.AUTH, pret['lead'], p.DEVIS)
    assert p.m.base._instantane_base(session) == avant


def test_chaine_m10_cassee_refusee(pret, session):
    import json

    from sqlalchemy import select, update

    from opsys.stockage.schema import REGISTRES

    port = import_module('opsys.console.memoire_chantier')
    condition = ((REGISTRES.c.departement == 'm10-memoire') & (REGISTRES.c.registre == 'evenements')
                 & (REGISTRES.c.rang == 0))
    with session() as cnx:
        ligne = json.loads(cnx.execute(select(REGISTRES.c.maillon).where(condition)).scalar_one())
        ligne['horodatage'] = '2020-01-01T00:00:00+00:00'
        cnx.execute(update(REGISTRES).where(condition).values(maillon=json.dumps(ligne)))
    avant = p.m.base._instantane_base(session)
    with session() as cnx, pytest.raises(p.v.port.Refus, match='MEMOIRE-SOURCE-INCOHERENTE'):
        port.lire(cnx, pret['deps'], p.AUTH, pret['lead'], p.DEVIS)
    assert p.m.base._instantane_base(session) == avant


def test_omissions_ne_masquent_pas_signaux_ouverts_reels(pret, session):
    from m10_memoire import registre, variance, wct

    from opsys import stockage

    spec_signaux = importlib.util.spec_from_file_location('memoire_chantier_signaux_fixture',
        Path(__file__).parents[1] / 'departments/m10-memoire/tests/test_signaux.py')
    s = importlib.util.module_from_spec(spec_signaux)
    spec_signaux.loader.exec_module(s)
    port = import_module('opsys.console.memoire_chantier')
    with session():
        reg = registre.Registre(stockage.maillons('m10-memoire', 'evenements'))
        for i in range(6):
            ident = f'WCT-MEMOIRE-FICTIF-{i}'
            assert wct.memoriser_wct(s._wct(ident, pret['lead']), reg)[1] is None
            assert variance.memoriser_variance(s._variance(f'VAR-MEMOIRE-FICTIF-{i}', ident), reg)[1] is None
    avant = p.m.base._instantane_base(session)
    with session() as cnx:
        r = port.lire(cnx, pret['deps'], p.AUTH, pret['lead'], p.DEVIS)
    signaux = next(c for c in r['paquet']['couches'] if c['nom'] == 'signaux_non_resolus')
    assert r['etat'] == 'LIE' and r['paquet']['signaux']['nb_ouverts'] == 6
    assert signaux['nb_total'] == 6 and signaux['nb_inclus'] < 6
    assert signaux['nb_omis'] > 0 and signaux['tronque'] is True
    assert p.m.base._instantane_base(session) == avant
