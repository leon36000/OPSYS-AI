"""fictif: true — contexte M10 courant avant décision N3 réelle; aucune date client."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('memoire_decision_http_fixture',
    Path(__file__).with_name('test_console_application_chantier_http.py'))
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
p = h.p
propose, pret, affaire, catalogue, client_crm = h.propose, h.pret, h.affaire, h.catalogue, h.client_crm


def test_revue_montre_memoire_courante_avant_confirmation(propose, catalogue, session):
    avant = p.m.base._instantane_base(session)
    page = catalogue.get(propose['revue_route'])
    assert page.status_code == 200, page.text
    assert 'Mémoire de l’affaire' in page.text
    assert 'Contexte actuel' in page.text and 'LIE' in page.text
    assert page.text.index('Mémoire de l’affaire') < page.text.index('Confirmer l’affectation interne')
    assert 'FINANCIAL' not in page.text and 'CLIENT_PRIVATE' not in page.text
    assert page.headers['cache-control'] == 'no-store'
    assert p.m.base._instantane_base(session) == avant


def _ajouter_fait(propose, suffixe='nouveau'):
    from m10_memoire import amont, etapes, registre

    from opsys import stockage
    from opsys.console import preparation_chantier as lecture

    cnx = stockage.connexion_courante()
    charge = lecture._publication(cnx, 'm3-devis-accepte-' + p.DEVIS, etapes.TYPE_DEVIS_ACCEPTE, lecture.M3)
    charge['devis_id'] = 'DEVIS-CONTEXTE-FICTIF-' + suffixe
    reg = registre.Registre(stockage.maillons('m10-memoire', 'evenements'))
    assert amont.memoriser(etapes.TYPE_DEVIS_ACCEPTE, charge, reg)[1] is None


def test_memoire_changee_apres_revue_refuse_avant_approbation(propose, catalogue, session):
    champs = h.Formulaire(catalogue.get(propose['revue_route']).text).champs
    with session():
        _ajouter_fait(propose)
    avant = p.m.base._instantane_base(session)
    reponse = catalogue.post(propose['revue_route'] + '/appliquer', data=champs)
    assert reponse.status_code == 409, reponse.text
    assert p.m.base._instantane_base(session) == avant
    nouvelle = h.Formulaire(catalogue.get(propose['revue_route']).text).champs
    assert nouvelle['empreinte_attendue'] != champs['empreinte_attendue']


def test_changement_pendant_decision_annule_tout_meme_exception_capturee(propose, session, monkeypatch):
    import pytest

    from opsys.console import application_chantier as port

    with session() as cnx:
        apercu = port.preparer(cnx, propose['deps'], p.AUTH, propose['lead'], p.DEVIS, propose['plan_id'])
    original = port.approbations.decider

    def decider_et_changer(*args, **kwargs):
        resultat = original(*args, **kwargs)
        assert resultat['statut'] == 'executee'
        _ajouter_fait(propose, 'pendant')
        return resultat

    monkeypatch.setattr(port.approbations, 'decider', decider_et_changer)
    avant = p.m.base._instantane_base(session)
    with session() as cnx, pytest.raises(p.v.port.Refus, match='SOURCE-MODIFIEE'):
        port.appliquer(cnx, propose['deps'], p.AUTH, propose['lead'], p.DEVIS, propose['plan_id'],
                       apercu['empreinte'], 'memoire-pendant-fictive')
    assert p.m.base._instantane_base(session) == avant


def test_decision_trace_empreinte_sans_copie_des_faits_et_rejeu_courant(propose, catalogue, session):
    import json

    from sqlalchemy import select

    from opsys.console import application_chantier as port
    from opsys.stockage.schema import APPROBATIONS, JOURNAL

    page = catalogue.get(propose['revue_route'])
    champs = h.Formulaire(page.text).champs
    with session() as cnx:
        memoire = port.preparer(cnx, propose['deps'], p.AUTH, propose['lead'], p.DEVIS, propose['plan_id'])['memoire']
    assert catalogue.post(propose['revue_route'] + '/appliquer', data=champs, follow_redirects=False).status_code == 303
    with session() as cnx:
        traces = cnx.execute(select(JOURNAL.c.details).where((JOURNAL.c.action == 'console.action_interne')
            & (JOURNAL.c.cible == port.NOM))).scalars().all()
        assert len(traces) == 1
        trace = json.loads(traces[0])
        assert trace['memoire_empreinte'] == memoire['empreinte']
        assert trace['memoire_sources'] == memoire['sources']
        assert trace['memoire_reference_devis'] == memoire['reference_devis']
        assert set(trace) == {'plan_id', 'approbation_id', 'mutation_id',
                             'memoire_empreinte', 'memoire_sources', 'memoire_reference_devis'}
        _ajouter_fait(propose, 'apres')
    avant = p.m.base._instantane_base(session)
    reponse = catalogue.post(propose['revue_route'] + '/appliquer', data=champs)
    assert reponse.status_code == 200, reponse.text
    assert 'Reçu historique' in reponse.text and 'Contexte actuel' in reponse.text
    assert 'ne reconstitue pas celui de la décision initiale' in reponse.text
    assert 'DEVIS-CONTEXTE-FICTIF-apres' in reponse.text
    assert 'Confirmer l’affectation interne' not in reponse.text
    assert p.m.base._instantane_base(session) == avant
    with session() as cnx:
        assert len(cnx.execute(select(APPROBATIONS.c.id).where(APPROBATIONS.c.outil == port.NOM)).all()) == 1


def test_six_signaux_reels_visibles_meme_si_detail_omis(propose, catalogue, session):
    from m10_memoire import registre, variance, wct

    from opsys import stockage

    spec_signaux = importlib.util.spec_from_file_location('memoire_decision_signaux_fixture',
        Path(__file__).parents[1] / 'departments/m10-memoire/tests/test_signaux.py')
    s = importlib.util.module_from_spec(spec_signaux)
    spec_signaux.loader.exec_module(s)
    with session():
        reg = registre.Registre(stockage.maillons('m10-memoire', 'evenements'))
        for i in range(6):
            ident = f'WCT-DECISION-FICTIF-{i}'
            assert wct.memoriser_wct(s._wct(ident, propose['lead']), reg)[1] is None
            assert variance.memoriser_variance(s._variance(f'VAR-DECISION-FICTIF-{i}', ident), reg)[1] is None
    avant = p.m.base._instantane_base(session)
    page = catalogue.get(propose['revue_route'])
    assert page.status_code == 200, page.text
    assert 'Signaux ouverts : 6' in page.text and 'Couche partielle' in page.text
    assert 'y compris ceux omis' in page.text
    assert 'Confirmer l’affectation interne' in page.text  # Aucune politique bloquante inventée.
    assert p.m.base._instantane_base(session) == avant


def test_devis_non_memorise_est_affiche_sans_inventer_blocage(propose, catalogue, session):
    from m10_memoire import registre
    from sqlalchemy import delete

    from opsys import stockage
    from opsys.stockage.schema import REGISTRES

    with session() as cnx:
        reg = registre.Registre(stockage.maillons('m10-memoire', 'evenements'))
        lignes = [m for m in reg.lire() if m.get('devis_id') != p.DEVIS]
        cnx.execute(delete(REGISTRES).where((REGISTRES.c.departement == 'm10-memoire')
            & (REGISTRES.c.registre == 'evenements')))
        for ligne in lignes:
            reg.ajouter(ligne)
    avant = p.m.base._instantane_base(session)
    page = catalogue.get(propose['revue_route'])
    assert page.status_code == 200, page.text
    assert 'DEVIS_NON_MEMORISE' in page.text and 'Le fait du devis exact manque' in page.text
    assert 'Confirmer l’affectation interne' in page.text
    assert p.m.base._instantane_base(session) == avant
    champs = h.Formulaire(page.text).champs
    r = catalogue.post(propose['revue_route'] + '/appliquer', data=champs, follow_redirects=False)
    assert r.status_code == 303, r.text  # Décision humaine interne, pas de règle M10 bloquante inventée.


def test_trace_ancien_format_sans_m10_reste_rejouable_historiquement(propose, catalogue, session):
    import json

    from sqlalchemy import select, update

    from opsys.console import application_chantier as port
    from opsys.stockage.schema import JOURNAL

    champs = h.Formulaire(catalogue.get(propose['revue_route']).text).champs
    assert catalogue.post(propose['revue_route'] + '/appliquer', data=champs, follow_redirects=False).status_code == 303
    with session() as cnx:
        condition = (JOURNAL.c.action == 'console.action_interne') & (JOURNAL.c.cible == port.NOM)
        ident, texte = cnx.execute(select(JOURNAL.c.id, JOURNAL.c.details).where(condition)).one()
        ancien = {k: v for k, v in json.loads(texte).items() if not k.startswith('memoire_')}
        assert set(ancien) == {'plan_id', 'approbation_id', 'mutation_id'}
        # Fixture de données de l'ancien format; aucun ancien binaire n'est rejoué.
        cnx.execute(update(JOURNAL).where(JOURNAL.c.id == ident).values(details=json.dumps(ancien)))
        _ajouter_fait(propose, 'apres-ancien-format')
    avant = p.m.base._instantane_base(session)
    page = catalogue.post(propose['revue_route'] + '/appliquer', data=champs)
    assert page.status_code == 200, page.text
    assert 'Reçu historique' in page.text and 'Contexte actuel' in page.text
    assert p.m.base._instantane_base(session) == avant
