"""fictif: true — snapshots privés M10 par préparation, vrais T0 et SQL bornés."""
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import event

from opsys.console import memoire_chantier, memoire_plan_calendrier
from opsys.departements import charger_departements

spec = importlib.util.spec_from_file_location('capture_m10_volume_reel_fixture',
    Path(__file__).with_name('test_console_volume_memoire_dates_civiles.py'))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
client_crm = f.client_crm
FICTIF = True


def test_preparation_24_borne_lectures_sql_completes_par_source(
        client_crm, session, monkeypatch, record_testsuite_property):
    _m4, _ids, plan, _preparation = f._plan_reel(session, 24)
    lectures, appels = [], []
    original = memoire_chantier._paquet

    def paquet(*args):
        appels.append(args[2])
        return original(*args)

    def compter(cnx, cursor, statement, parameters, context, executemany):
        if (statement.lstrip().startswith('SELECT registres_maillons.maillon')
                and 'ORDER BY registres_maillons.rang' in statement and 'm10-memoire' in parameters):
            lectures.append(statement)

    monkeypatch.setattr(memoire_chantier, '_paquet', paquet)
    avant = f.f.b.base._instantane_base(session)
    with session() as cnx:
        event.listen(cnx, 'before_cursor_execute', compter)
        try:
            r = memoire_plan_calendrier.lire(cnx, charger_departements(), f.f.AUTH, plan['plan_id'])
        finally:
            event.remove(cnx, 'before_cursor_execute', compter)
    assert r['synthese']['affaires'] == len(set(appels)) == len(appels) == 24
    assert len(lectures) <= 6, len(lectures)
    record_testsuite_property('capture_24', str(dict(affaires=24, appels_t0=len(appels), lectures_m10=len(lectures))))
    assert f.f.b.base._instantane_base(session) == avant


# Réutilise le vrai devis accepté de M3 et son événement M10, sans nouveaux doubles métier.
p = f.f.p
pret, affaire, catalogue = p.pret, p.affaire, p.catalogue
HEURE = '2030-06-03T08:00:00-04:00'


def _lire(lead):
    from m10_memoire import outils

    return outils.lire_paquet_affaire_appareil(lead, HEURE)


def test_capture_equivalente_t0_ordinaire_et_copies_sans_alias(pret, session):
    from m10_memoire import outils

    from opsys import contexte

    avant = p.m.base._instantane_base(session)
    acteur = contexte.IdentiteAppelante(p.AUTH.utilisateur, 'admin', source='console')
    with session() as cnx, contexte.appele_par_appareil(acteur):
        ordinaire = _lire(pret['lead'])
        with outils.capture_paquets_appareil(cnx):
            assert _lire(pret['lead']) == ordinaire
            source = outils.sources_capture_paquets_appareil()
            assert source['evenements'] and source['source_registres'] == ordinaire['source_registres']
            source['evenements'][0]['lead_id'] = 'FAUX-ALIAS-FICTIF'
            source['source_registres']['evenements'] = None
            copie = _lire(pret['lead'])
            copie['couches'].clear()
            assert _lire(pret['lead']) == ordinaire
            assert outils.sources_capture_paquets_appareil()['source_registres'] == ordinaire['source_registres']
        assert _lire(pret['lead']) == ordinaire
    assert p.m.base._instantane_base(session) == avant


def test_capture_ne_remplace_pas_authorite_sql_par_t0(pret, session):
    import pytest
    from m10_memoire import outils

    from opsys import identite

    with session() as cnx, memoire_chantier.capture_paquets(cnx, p.AUTH):
        assert _lire(pret['lead'])['affaire_id'] == pret['lead']
        identite.ajouter_role(cnx, p.AUTH.utilisateur, 'nathan_owner')
        identite.retirer_role(cnx, p.AUTH.utilisateur, 'admin')
        refus = _lire(pret['lead'])
        assert refus['accepte'] is False and 'couches' not in refus
        with pytest.raises(PermissionError):
            outils.sources_capture_paquets_appareil()


def test_capture_exception_nesting_et_contexte_herite_inactif(pret, session):
    import contextvars

    import pytest
    from m10_memoire import outils

    with session() as cnx:
        with pytest.raises(RuntimeError, match='interruption-fictive'), memoire_chantier.capture_paquets(cnx, p.AUTH):
            herite = contextvars.copy_context()
            with pytest.raises(ValueError, match='CAPTURE-M10-INDISPONIBLE'), outils.capture_paquets_appareil(cnx):
                pytest.fail('capture imbriquée admise')
            raise RuntimeError('interruption-fictive')
        assert outils._CAPTURE_PAQUETS_APPAREIL.get() is None
        refus = herite.run(_lire, pret['lead'])
        assert refus['verdict']['code'] == 'REJ-PAQUET-AFFAIRE-CAPTURE-INVALIDE' and 'couches' not in refus
        with pytest.raises(ValueError, match='CAPTURE-M10-INDISPONIBLE'):
            herite.run(outils.sources_capture_paquets_appareil)
        with memoire_chantier.capture_paquets(cnx, p.AUTH):
            assert _lire(pret['lead'])['affaire_id'] == pret['lead']


def test_identite_exacte_et_connexion_canonique_de_capture(pret, session):
    from importlib import import_module

    from m10_memoire import outils

    from opsys import contexte

    moteur = import_module('opsys.stockage.moteur')

    with session() as cnx, memoire_chantier.capture_paquets(cnx, p.AUTH):
        with contexte.appele_par_appareil(contexte.IdentiteAppelante(p.AUTH.utilisateur, 'admin', source='autre')):
            assert _lire(pret['lead'])['verdict']['code'] == 'REJ-PAQUET-AFFAIRE-CAPTURE-INVALIDE'
        with cnx.engine.connect() as autre:
            jeton = moteur._CONNEXION.set(autre)
            try:
                assert _lire(pret['lead'])['verdict']['code'] == 'REJ-PAQUET-AFFAIRE-CAPTURE-INVALIDE'
            finally:
                moteur._CONNEXION.reset(jeton)
        assert outils.sources_capture_paquets_appareil()['source_registres'] == _lire(pret['lead'])['source_registres']


def test_savepoint_origine_ferme_refuse_meme_si_transaction_active(pret, session):
    from m10_memoire import outils

    with session() as cnx:
        origine = cnx.begin_nested()
        with memoire_chantier.capture_paquets(cnx, p.AUTH):
            with cnx.begin_nested():
                assert _lire(pret['lead'])['affaire_id'] == pret['lead']
            origine.commit()
            assert cnx.in_transaction()
            assert _lire(pret['lead'])['verdict']['code'] == 'REJ-PAQUET-AFFAIRE-CAPTURE-INVALIDE'
        assert outils._CAPTURE_PAQUETS_APPAREIL.get() is None


def test_capture_heritee_apres_fin_transaction_refuse_avant_sql(pret, session, monkeypatch):
    import contextvars

    from m10_memoire import outils

    with session() as cnx, memoire_chantier.capture_paquets(cnx, p.AUTH):
        herite = contextvars.copy_context()
        capture = outils._CAPTURE_PAQUETS_APPAREIL.get()
    # Même une référence héritée artificiellement réactivée ne survit pas à sa transaction.
    capture.active = True
    monkeypatch.setattr(outils, '_refus_lecture_admin', lambda: (_ for _ in ()).throw(
        AssertionError('SQL autorité exécuté après invalidation de transaction')))
    refus = herite.run(_lire, pret['lead'])
    assert refus['verdict']['code'] == 'REJ-PAQUET-AFFAIRE-CAPTURE-INVALIDE'


def _ajouter_evenement_fictif(lead):
    from m10_memoire import amont, registre

    from opsys import stockage

    reg = registre.Registre(stockage.maillons('m10-memoire', 'evenements'))
    assert amont.memoriser('m1.lead_qualifie', dict(lead=dict(lead_id=lead,
        service='gouttieres', canal='telephone', urgence_declaree=False), horodatage=HEURE), reg)[1] is None
    return reg


def test_capture_consomme_a_et_cite_a_pendant_b_puis_restoration(pret, session):
    from m10_memoire import outils
    from sqlalchemy import delete

    from opsys import contexte
    from opsys.stockage.schema import REGISTRES

    acteur = contexte.IdentiteAppelante(p.AUTH.utilisateur, 'admin', source='console')
    lead_b = 'capture-affaire-b-fictive'
    with session() as cnx, contexte.appele_par_appareil(acteur):
        paquet_a = _lire(lead_b)
        with outils.capture_paquets_appareil(cnx):
            reg = _ajouter_evenement_fictif(lead_b)
            assert reg.tete() != paquet_a['source_registres']['evenements']
            assert _lire(lead_b) == paquet_a
            rang_b = len(reg.lire()) - 1
            cnx.execute(delete(REGISTRES).where((REGISTRES.c.departement == 'm10-memoire')
                & (REGISTRES.c.registre == 'evenements') & (REGISTRES.c.rang == rang_b)))
            assert _lire(lead_b) == paquet_a
        assert _lire(lead_b) == paquet_a
        with outils.capture_paquets_appareil(cnx):
            _ajouter_evenement_fictif(lead_b)
        paquet_b = _lire(lead_b)
        assert paquet_b != paquet_a and paquet_b['affaire']['origine_recue'] is True
        with outils.capture_paquets_appareil(cnx):
            assert _lire(lead_b) == paquet_b


@pytest.mark.parametrize('source', ['evenements', 'affaires'])
@pytest.mark.parametrize('quota', ['octets', 'maillons'])
def test_quotas_deux_sources_avant_premier_decodage(pret, session, monkeypatch, source, quota):
    from m10_memoire import outils, registre
    from sqlalchemy import update

    from opsys import contexte
    from opsys.stockage.schema import REGISTRES

    acteur = contexte.IdentiteAppelante(p.AUTH.utilisateur, 'admin', source='console')
    with session() as cnx, contexte.appele_par_appareil(acteur):
        # Le dépassement appartient bien à la source ciblée, même si affaires est bornée en second.
        from sqlalchemy import LargeBinary, cast, func, select

        evenements = (REGISTRES.c.departement == 'm10-memoire') & (REGISTRES.c.registre == 'evenements')
        nombre, octets = cnx.execute(select(func.count(), func.sum(func.length(cast(
            REGISTRES.c.maillon, LargeBinary)))).where(evenements)).one()
        if source == 'affaires':
            cnx.execute(REGISTRES.insert(), [dict(departement='m10-memoire', registre=source,
                rang=i, maillon='x') for i in range(nombre + 1)])
        if quota == 'octets':
            cnx.execute(update(REGISTRES).where((REGISTRES.c.departement == 'm10-memoire')
                & (REGISTRES.c.registre == source) & (REGISTRES.c.rang == 0)).values(maillon='é' * (octets + 1)))
            monkeypatch.setattr(outils, '_MAX_CAPTURE_OCTETS', octets)
        else:
            monkeypatch.setattr(outils, '_MAX_CAPTURE_MAILLONS', nombre if source == 'affaires' else nombre - 1)
        monkeypatch.setattr(registre, 'Registre', lambda *_: pytest.fail('décodage avant quotas des deux sources'))
        with (pytest.raises(ValueError, match='CAPTURE-M10-SOURCE-TROP-VOLUMINEUSE'),
              outils.capture_paquets_appareil(cnx)):
            pytest.fail('source trop volumineuse admise')


def test_chaine_capture_corrompue_refuse_sans_fallback(pret, session):
    from m10_memoire import outils
    from sqlalchemy import update

    from opsys import contexte
    from opsys.stockage.schema import REGISTRES

    with session() as cnx, contexte.appele_par_appareil(
            contexte.IdentiteAppelante(p.AUTH.utilisateur, 'admin', source='console')):
        cnx.execute(update(REGISTRES).where((REGISTRES.c.departement == 'm10-memoire')
            & (REGISTRES.c.registre == 'evenements') & (REGISTRES.c.rang == 0)).values(maillon='{}'))
        with pytest.raises(ValueError, match='CAPTURE-M10-SOURCE-INVALIDE'), outils.capture_paquets_appareil(cnx):
            pytest.fail('chaîne corrompue admise')
        assert outils._CAPTURE_PAQUETS_APPAREIL.get() is None


@pytest.mark.parametrize('role', [None, 'field_employee', 'nathan_owner'])
def test_capture_n_octroie_pas_role_appareil(pret, session, role):
    from m10_memoire import outils

    from opsys import contexte

    with session() as cnx:
        acteur = None if role is None else contexte.IdentiteAppelante(p.AUTH.utilisateur, role, source='console')
        with (contexte.appele_par_appareil(acteur), pytest.raises(PermissionError),
              outils.capture_paquets_appareil(cnx)):
            pytest.fail('capture a octroyé admin')
        assert outils._CAPTURE_PAQUETS_APPAREIL.get() is None


def test_nouvelle_transaction_sur_meme_connexion_ne_reactive_pas_capture(pret, session):
    from importlib import import_module

    from m10_memoire import outils

    from opsys import contexte

    moteur = import_module('opsys.stockage.moteur')
    with session() as source:
        engine = source.engine
    with engine.connect() as cnx:
        token = moteur._CONNEXION.set(cnx)
        try:
            with contexte.appele_par_appareil(
                    contexte.IdentiteAppelante(p.AUTH.utilisateur, 'admin', source='console')):
                transaction = cnx.begin()
                with outils.capture_paquets_appareil(cnx):
                    assert _lire(pret['lead'])['affaire_id'] == pret['lead']
                    transaction.commit()
                    with cnx.begin():
                        assert cnx.get_transaction() is not transaction
                        refus = _lire(pret['lead'])
                        assert refus['verdict']['code'] == 'REJ-PAQUET-AFFAIRE-CAPTURE-INVALIDE'
                        with pytest.raises(ValueError, match='CAPTURE-M10-INDISPONIBLE'):
                            outils.sources_capture_paquets_appareil()
        finally:
            moteur._CONNEXION.reset(token)
