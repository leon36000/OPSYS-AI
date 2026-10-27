"""fictif: true — mémoire réelle et dates civiles atomiques depuis la console."""
import importlib.util
from html.parser import HTMLParser
from pathlib import Path

import pytest

from opsys import idempotence
from opsys.console import memoire_plan_calendrier as memoire
from opsys.departements import charger_departements

spec = importlib.util.spec_from_file_location('memoire_dates_http_fixture',
    Path(__file__).with_name('test_console_memoire_plan_calendrier.py'))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
client_crm, planning = f.client_crm, f.planning


class Formulaire(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.dans = False
        self.champs = {}
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'form':
            self.dans = '/crm/cedule/plan/' in a.get('action', '') and not a['action'].endswith('/meteo')
        if tag == 'input' and self.dans:
            self.champs[a['name']] = a.get('value', '')

    def handle_endtag(self, tag):
        if tag == 'form':
            self.dans = False


def test_contexte_affaires_visible_avant_dates_sans_ecriture(client_crm, planning, session):
    f.b.base._connecter(client_crm, 'admin.fictif')
    avant = f.b.base._instantane_base(session)
    page = client_crm.get(f.d._url(planning))
    assert page.status_code == 200, page.text
    assert 'Mémoire avant les dates internes' in page.text
    assert page.text.index('Contexte actuel M10') < page.text.index('Confirmer les dates internes')
    assert 'CONTEXTE_AFFAIRE_SANS_DEVIS_VERIFIE' in page.text
    assert 'Mémoire d’affaire inconnue' in page.text
    champs = Formulaire(page.text).champs
    with session() as cnx:
        contexte = memoire.lire(cnx, charger_departements(), f.AUTH, planning[2]['plan_id'])
    attendu = idempotence.empreinte_arguments({k: contexte[k] for k in ('empreinte_plan', 'empreinte_memoire')})
    assert champs['empreinte_memoire_attendue'] == attendu
    assert f.b.base._instantane_base(session) == avant


def test_nouvelle_date_sans_preuve_memoire_est_refusee(client_crm, planning, session):
    f.b.base._connecter(client_crm, 'admin.fictif')
    champs = f.d._champs(client_crm)
    champs.pop('empreinte_memoire_attendue', None)
    avant = f.b.base._instantane_base(session)
    r = client_crm.post(f.d._url(planning), data=champs, follow_redirects=False)
    assert r.status_code == 409, r.text
    assert f.b.base._instantane_base(session) == avant



def _form(client, planning):
    r = client.get(f.d._url(planning))
    assert r.status_code == 200, r.text
    champs = Formulaire(r.text).champs
    champs['date_0'] = '2030-06-10'
    return champs


def _fait():
    from m10_memoire import amont, registre

    from opsys import stockage

    reg = registre.Registre(stockage.maillons('m10-memoire', 'evenements'))
    assert amont.memoriser('m1.lead_qualifie', dict(lead=dict(lead_id='qa-date-contexte-fictif',
        service='gouttieres', canal='telephone', urgence_declaree=False),
        horodatage='2030-06-03T08:00:00-04:00'), reg)[1] is None


def test_date_reelle_trace_preuve_et_rejeu_historique_apres_report(client_crm, planning, session):
    import json

    from m4_field_ops import etats
    from sqlalchemy import select

    from opsys.stockage.schema import JOURNAL, MUTATIONS_APPLIQUEES

    f.b.base._connecter(client_crm, 'admin.fictif')
    champs = _form(client_crm, planning)
    r = client_crm.post(f.d._url(planning), data=champs, follow_redirects=False)
    assert r.status_code == 303, r.text
    with session() as cnx:
        dates = [m for m in f.b.terrain._maillons() if m['type_entree'] == 'cedule_datee']
        assert len(dates) == 2 and dates[-1]['calendrier'] == {'0': '2030-06-10'}
        args = dict(plan_id=planning[2]['plan_id'], revision_attendue=1, calendrier={'0': '2030-06-10'})
        recu = cnx.execute(select(MUTATIONS_APPLIQUEES).where(
            MUTATIONS_APPLIQUEES.c.cle_idempotence == champs['mutation_id'])).mappings().one()
        assert recu['empreinte_arguments'] == idempotence.empreinte_arguments(dict(arguments=args,
            preuve_commande={'empreinte': champs['empreinte_memoire_attendue']}))
        audit = json.loads(cnx.execute(select(JOURNAL.c.details).where(
            JOURNAL.c.action == 'console.contexte_dates')).scalar_one())
        assert audit['empreinte'] == champs['empreinte_memoire_attendue']
        assert set(audit) == {'plan_id', 'mutation_id', 'empreinte', 'memoire_empreinte', 'sources_m10'}
        _fait()
        assert etats.transitionner(planning[1]['lead-fictif-001'], 'reportee', f.b.terrain._registre(),
            f.b.terrain.RECU_LE.isoformat(), motif='meteo')[1] is None
    avant = f.b.base._instantane_base(session)
    r = client_crm.post(f.d._url(planning), data=champs)
    assert r.status_code == 200 and 'Reçu historique' in r.text, r.text
    assert 'ne reconstitue pas la mémoire' in r.text
    assert f.b.base._instantane_base(session) == avant


def test_memoire_changee_apres_affichage_refuse_avant_date(client_crm, planning, session):
    f.b.base._connecter(client_crm, 'admin.fictif')
    champs = _form(client_crm, planning)
    with session():
        _fait()
    avant = f.b.base._instantane_base(session)
    r = client_crm.post(f.d._url(planning), data=champs)
    assert r.status_code == 409, r.text
    assert f.b.base._instantane_base(session) == avant
    assert _form(client_crm, planning)['empreinte_memoire_attendue'] != champs['empreinte_memoire_attendue']


@pytest.mark.parametrize('defaut', ['memoire', 'role', 'audit'])
def test_apres_effet_rollback_complet_meme_exception_capturee(client_crm, planning, session, monkeypatch, defaut):
    from opsys import identite
    from opsys.console import confirmation_dates_chantier as port

    f.b.base._connecter(client_crm, 'admin.fictif')
    champs = _form(client_crm, planning)
    original = port.metier.executer
    effets = []

    def perturber(cnx, deps, sess, nom, args, **kwargs):
        r = original(cnx, deps, sess, nom, args, **kwargs)
        if nom == port.NOM:
            assert r['ok'] is True and r['resultat']['accepte'] is True
            effets.append(True)
            if defaut == 'memoire':
                _fait()
            elif defaut == 'role':
                identite.ajouter_role(cnx, sess.utilisateur, 'nathan_owner')
                identite.retirer_role(cnx, sess.utilisateur, 'admin')
        return r

    def audit_refuse(*args, **kwargs):
        raise RuntimeError('audit fictif indisponible')

    monkeypatch.setattr(port.metier, 'executer', perturber)
    if defaut == 'audit':
        monkeypatch.setattr(port, 'journaliser', audit_refuse)
    avant = f.b.base._instantane_base(session)
    with session() as cnx:
        try:
            port.confirmer(cnx, charger_departements(), f.AUTH, planning[2]['plan_id'], champs)
        except (ValueError, PermissionError, RuntimeError):
            pass
        else:
            pytest.fail('confirmation attendue refusée')
    assert effets == [True]
    assert f.b.base._instantane_base(session) == avant


def test_ancien_recu_exact_seul_rejouable_sans_m10_et_aucun_fallback(client_crm, planning, session, monkeypatch):
    from m4_field_ops import etats

    from opsys.console import memoire_chantier, metier

    f.b.base._connecter(client_crm, 'admin.fictif')
    champs = f.d._champs(client_crm)
    args = dict(plan_id=planning[2]['plan_id'], revision_attendue=1, calendrier={'0': '2030-06-10'})
    with session() as cnx:
        r = metier.executer(cnx, charger_departements(), f.AUTH, 'm4_confirmer_dates_cedule',
                            args, mutation_id=champs['mutation_id'])
        assert r['ok'] is True and r['resultat']['accepte'] is True
        assert etats.transitionner(planning[1]['lead-fictif-001'], 'reportee', f.b.terrain._registre(),
            f.b.terrain.RECU_LE.isoformat(), motif='meteo')[1] is None

    def aucun_paquet(*args, **kwargs):
        pytest.fail('le reçu historique ne demande pas de nouveau paquet')

    monkeypatch.setattr(memoire_chantier, '_paquet', aucun_paquet)
    avant = f.b.base._instantane_base(session)
    r = client_crm.post(f.d._url(planning), data=champs)
    assert r.status_code == 200 and 'Reçu historique' in r.text, r.text
    for changement in [{'date_0': '2030-06-11'}, {'empreinte_memoire_attendue': 'ab'*32},
                       {'mutation_id': 'nouvelle-sans-preuve-fictive'}]:
        assert client_crm.post(f.d._url(planning), data={**champs, **changement}).status_code == 409
    assert f.b.base._instantane_base(session) == avant


@pytest.mark.parametrize('defaut', ['calendrier', 'ligne', 'taille', 'enveloppe'])
def test_recu_altere_ou_surdimensionne_ne_rejoue_pas(client_crm, planning, session, defaut):
    import json

    from sqlalchemy import select, update

    from opsys.stockage import codec
    from opsys.stockage.schema import MUTATIONS_APPLIQUEES

    f.b.base._connecter(client_crm, 'admin.fictif')
    champs = _form(client_crm, planning)
    assert client_crm.post(f.d._url(planning), data=champs, follow_redirects=False).status_code == 303
    with session() as cnx:
        condition = MUTATIONS_APPLIQUEES.c.cle_idempotence == champs['mutation_id']
        r = codec.decoder(cnx.execute(select(MUTATIONS_APPLIQUEES.c.reponse).where(condition)).scalar_one())
        if defaut == 'enveloppe':
            brut = codec.encoder(None)
        elif defaut == 'taille':
            brut = json.dumps({'fictif': 'x'*65537})
        else:
            resultat = r['resultat']['resultat']
            if defaut == 'ligne':
                resultat['ligne_id'] = 'ligne-inconnue-fictive'
            else:
                resultat['calendrier'] = {'0': '2030-06-11'}
            brut = codec.encoder(r)
        cnx.execute(update(MUTATIONS_APPLIQUEES).where(condition).values(reponse=brut))
    avant = f.b.base._instantane_base(session)
    assert client_crm.post(f.d._url(planning), data=champs).status_code == 503
    assert f.b.base._instantane_base(session) == avant


def test_parser_35_champs_exacts_et_refus_du_36e():
    import asyncio
    from urllib.parse import urlencode

    from fastapi import HTTPException, Request

    from opsys.console import cedule_plan_ui

    champs = dict(csrf='fictif', revision_attendue='0', mutation_id='fictif', empreinte_memoire_attendue='ab'*32)
    champs.update({f'date_{i}': '2030-06-03' for i in range(31)})

    async def lire(donnees):
        async def recevoir():
            return dict(type='http.request', body=urlencode(donnees).encode(), more_body=False)
        scope = dict(type='http', headers=[(b'content-type', b'application/x-www-form-urlencoded')])
        requete = Request(scope, recevoir)
        return await cedule_plan_ui.formulaire(requete)

    assert asyncio.run(lire(champs)) == champs
    assert len(cedule_plan_ui.arguments(champs, list(range(31)))[0]['calendrier']) == 31
    with pytest.raises(HTTPException) as e:
        asyncio.run(lire({**champs, 'inconnu': 'fictif'}))
    assert e.value.status_code == 400



def test_origine_m1_absente_et_consolidation_reste_visibles(client_crm, planning, session):
    from m10_memoire import amont, registre

    from opsys import stockage

    amont_spec = importlib.util.spec_from_file_location('memoire_dates_amont_reel_fixture',
        Path(__file__).parents[1] / 'departments/m10-memoire/tests/test_amont.py')
    amont_fixture = importlib.util.module_from_spec(amont_spec)
    amont_spec.loader.exec_module(amont_fixture)
    f.b.base._connecter(client_crm, 'admin.fictif')
    with session() as cnx:
        reg = registre.Registre(stockage.maillons('m10-memoire', 'evenements'))
        for i in range(5):
            charge = amont_fixture._devis_accepte(devis_id=f'DEVIS-SANS-ORIGINE-FICTIF-{i}',
                lead_id='lead-fictif-001', horodatage_acceptation=f'2030-06-0{i+1}T08:00:00-04:00')
            assert amont.memoriser('m3.devis_accepte', charge, reg)[1] is None
        contexte = memoire.lire(cnx, charger_departements(), f.AUTH, planning[2]['plan_id'])
        paquet = next(a['paquet'] for a in contexte['affaires'] if a['lead_id'] == 'lead-fictif-001')
        assert paquet['affaire']['connue'] is True and paquet['affaire']['origine_recue'] is False
        assert paquet['affaire']['verdict'] == 'AMONT-ORIGINE-NON-RECUE'
        assert paquet['consolidation']['nb_a_consolider'] > 0
    avant = f.b.base._instantane_base(session)
    r = client_crm.get(f.d._url(planning))
    assert r.status_code == 200, r.text
    assert 'Origine de l’affaire non reçue' in r.text
    assert 'Jours à consolider' in r.text
    assert 'Couche partielle' in r.text
    assert 'Confirmer les dates internes' in r.text  # Pas de politique bloquante inventée.
    assert f.b.base._instantane_base(session) == avant
