"""fictif: true — application interne N3 réelle et reçu historique, aucune date promise."""
import importlib.util
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path

import pytest
from sqlalchemy import select, update

from opsys import contexte, equipes, identite, stockage
from opsys.capacites import Capacites
from opsys.stockage import codec
from opsys.stockage.schema import APPROBATIONS, MUTATIONS_APPLIQUEES, REGISTRES

spec = importlib.util.spec_from_file_location('crm08_application_fixture',
    Path(__file__).with_name('test_console_proposition_chantier_http.py'))
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)
p = h.p
pret, affaire, catalogue, client_crm = h.pret, h.affaire, h.catalogue, h.client_crm


@pytest.fixture
def propose(pret, catalogue):
    _, _, route = h._creer(pret, catalogue)
    return dict(pret, plan_id=route.rsplit('/', 1)[1], revue_route=route)


def test_application_privee_n3_signee_et_rejeu_sans_seconde_decision(propose, session):
    port = import_module('opsys.console.application_chantier')
    avant = p.m.base._instantane_base(session)
    with session() as cnx:
        apercu = port.preparer(cnx, propose['deps'], p.AUTH, propose['lead'], p.DEVIS, propose['plan_id'])
    assert apercu['peut_appliquer'] is True
    assert p.m.base._instantane_base(session) == avant
    with session() as cnx:
        res = port.appliquer(cnx, propose['deps'], p.AUTH, propose['lead'], p.DEVIS,
                             propose['plan_id'], apercu['empreinte'], 'appliquer-fictif')
        approbation = cnx.execute(select(APPROBATIONS).where(
            APPROBATIONS.c.id == res['approbation_id'])).mappings().one()
        chaine = p.registre.Registre(stockage.maillons('m04-field-ops', 'principal'))
        iid = apercu['revue']['intervention_id']
        assert p.etats.statut_courant(chaine, iid) == 'planifiee'
        assert p.etats.technicien_assigne(chaine, iid) == 'eq-fictive'
        assert len([i for i in chaine.lire() if i['type_entree'] == 'cedule_appliquee']) == 1
        assert not any(i['type_entree'] == 'cedule_datee' for i in chaine.lire())
    assert approbation['outil'] == 'm4_appliquer_cedule' and approbation['niveau'] == 'N3'
    assert approbation['statut'] == 'executee' and approbation['decide_par'] == p.AUTH.utilisateur
    assert approbation['decide_role'] == 'admin' and res['application']['appliquee_par'] == p.AUTH.utilisateur
    apres = p.m.base._instantane_base(session)
    with session() as cnx:
        rejoue = port.appliquer(cnx, propose['deps'], p.AUTH, propose['lead'], p.DEVIS,
                                propose['plan_id'], apercu['empreinte'], 'appliquer-fictif')
    assert rejoue['rejoue'] is True and rejoue['historique'] is True
    assert rejoue['approbation_id'] == res['approbation_id']
    assert p.m.base._instantane_base(session) == apres



def test_transition_rechainee_ne_peut_contredire_preparation_du_plan(propose, session):
    port = import_module('opsys.console.application_chantier')
    with session() as cnx:
        apercu = port.preparer(cnx, propose['deps'], p.AUTH, propose['lead'], p.DEVIS, propose['plan_id'])
        port.appliquer(cnx, propose['deps'], p.AUTH, propose['lead'], p.DEVIS,
                        propose['plan_id'], apercu['empreinte'], 'transition-fictive')
        chaine = p.registre.Registre(stockage.maillons('m04-field-ops', 'principal'))
        nouvelle = p.registre.Registre()
        cible = apercu['revue']['intervention_id']
        trouves = 0
        for ligne in chaine.lire():
            if ligne['type_entree'] == 'transition_statut' and ligne.get('intervention_id') == cible:
                ligne['empreinte_preparation'] = '0' * 64
                trouves += 1
            nouvelle.ajouter(ligne)
        assert trouves == 1
        nouvelle.assert_chaine()
        for rang, ligne in enumerate(nouvelle.lire()):
            cnx.execute(update(REGISTRES).where((REGISTRES.c.departement == 'm04-field-ops')
                & (REGISTRES.c.registre == 'principal') & (REGISTRES.c.rang == rang)).values(
                    maillon=codec.encoder(ligne)))
    avant = p.m.base._instantane_base(session)
    with session() as cnx, pytest.raises(p.v.port.Refus, match='SOURCE-INCOHERENTE'):
        port.appliquer(cnx, propose['deps'], p.AUTH, propose['lead'], p.DEVIS,
                        propose['plan_id'], apercu['empreinte'], 'transition-fictive')
    assert p.m.base._instantane_base(session) == avant



def _apercu(port, propose, session):
    with session() as cnx:
        return port.preparer(cnx, propose['deps'], p.AUTH, propose['lead'], p.DEVIS, propose['plan_id'])


def _appliquer(port, propose, session, apercu, cle='action-fictive'):
    with session() as cnx:
        return port.appliquer(cnx, propose['deps'], p.AUTH, propose['lead'], p.DEVIS,
                              propose['plan_id'], apercu['empreinte'], cle)


@pytest.mark.parametrize('cause', ['materiel', 'profil', 'localisation'])
def test_sources_retires_entre_revue_et_decision_sans_effet(propose, session, cause):
    port = import_module('opsys.console.application_chantier')
    apercu = _apercu(port, propose, session)
    if cause == 'profil':
        profil, erreur = equipes.charger_equipes()
        assert erreur is None
        profil['services']['gouttieres']['duree_min'] = 120
        equipes.enregistrer_equipes(profil)
    else:
        with contexte.appele_par_appareil(contexte.IdentiteAppelante(p.AUTH.utilisateur, 'admin', source='console')):
            if cause == 'materiel':
                outil = p.b._outils(propose['deps'], 'm06-material-control')['m6_liberer_reservation']
                p.b._ok(p.executer_atomique(outil, dict(devis_id=p.DEVIS, motif='Retrait FICTIF',
                                                       horodatage=p.b.ACCEPTE_LE)))
            else:
                outil = p.b._outils(propose['deps'], 'm04-field-ops')['m4_confirmer_localisation']
                p.b._ok(p.executer_atomique(outil, dict(chantier_id=propose['lead'], action='retiree',
                    confirme_par=p.AUTH.utilisateur, motif='Retrait FICTIF', horodatage=p.b.ACCEPTE_LE)))
        assert p.b._drainer(propose['deps'], p.b.DEBUT)['quarantaines'] == 0
    avant = p.m.base._instantane_base(session)
    with pytest.raises(p.v.port.Refus, match='SOURCE-MODIFIEE'):
        _appliquer(port, propose, session, apercu)
    assert p.m.base._instantane_base(session) == avant


@pytest.mark.parametrize('etape', ['audit', 'finaliser', 'quota', 'decision'])
def test_panne_apres_application_annule_aussi_approbation(propose, session, monkeypatch, etape):
    port = import_module('opsys.console.application_chantier')
    apercu = _apercu(port, propose, session)
    def panne(*args, **kwargs):
        raise RuntimeError('Panne FICTIVE finale')
    if etape == 'audit':
        monkeypatch.setattr(port, 'journaliser', panne)
    elif etape == 'finaliser':
        monkeypatch.setattr(port.idempotence, 'finaliser', panne)
    elif etape == 'decision':
        original = port.approbations.decider
        def decider_puis_panne(*args, **kwargs):
            original(*args, **kwargs)
            panne()
        monkeypatch.setattr(port.approbations, 'decider', decider_puis_panne)
    else:
        original = port.lecture._sortie
        def quota(valeur):
            if 'application' in valeur:
                panne()
            return original(valeur)
        monkeypatch.setattr(port.lecture, '_sortie', quota)
    avant = p.m.base._instantane_base(session)
    with session() as cnx, pytest.raises(RuntimeError, match='Panne FICTIVE'):
        port.appliquer(cnx, propose['deps'], p.AUTH, propose['lead'], p.DEVIS,
                        propose['plan_id'], apercu['empreinte'], 'panne-fictive')
    assert p.m.base._instantane_base(session) == avant


def test_profil_change_apres_decision_annule_mutation_sql(propose, session, monkeypatch):
    port = import_module('opsys.console.application_chantier')
    apercu = _apercu(port, propose, session)
    original = port.approbations.decider
    def decider_puis_changer(*args, **kwargs):
        res = original(*args, **kwargs)
        profil, erreur = equipes.charger_equipes()
        assert erreur is None
        profil['services']['gouttieres']['duree_min'] = 120
        equipes.enregistrer_equipes(profil)
        return res
    monkeypatch.setattr(port.approbations, 'decider', decider_puis_changer)
    avant = p.m.base._instantane_base(session)
    with pytest.raises(p.v.port.Refus, match='SOURCE-MODIFIEE'):
        _appliquer(port, propose, session, apercu)
    assert p.m.base._instantane_base(session) == avant
    assert equipes.charger_equipes()[0]['services']['gouttieres']['duree_min'] == 120


def test_rejeu_apres_report_est_historique_et_revoque_refuse(propose, session):
    port = import_module('opsys.console.application_chantier')
    apercu = _apercu(port, propose, session)
    _appliquer(port, propose, session, apercu)
    with session():
        reg = p.registre.Registre(stockage.maillons('m04-field-ops', 'principal'))
        _, erreur = p.etats.transitionner(apercu['revue']['intervention_id'], 'reportee', reg,
                                        p.b.ACCEPTE_LE, motif='meteo')
        assert erreur is None
    avant = p.m.base._instantane_base(session)
    assert _appliquer(port, propose, session, apercu)['historique'] is True
    with pytest.raises(p.v.port.Refus, match='MUTATION-CONFLIT'):
        _appliquer(port, propose, session, dict(apercu, empreinte='0' * 64))
    courant = _apercu(port, propose, session)
    assert courant['peut_appliquer'] is False
    with pytest.raises(p.v.port.Refus, match='APPLICATION-NON-PERMISE'):
        _appliquer(port, propose, session, courant, 'nouvelle-fictive')
    assert p.m.base._instantane_base(session) == avant
    with session() as cnx:
        identite.retirer_role(cnx, p.AUTH.utilisateur, 'admin')
    avant = p.m.base._instantane_base(session)
    with pytest.raises(PermissionError):
        _appliquer(port, propose, session, apercu)
    assert p.m.base._instantane_base(session) == avant


@pytest.mark.parametrize('cas', ['cle_libre', 'application', 'signataire', 'resultat', 'taille', 'absente'])
def test_cache_et_decision_corrompus_ne_deviennent_pas_preuves(propose, session, cas):
    port = import_module('opsys.console.application_chantier')
    apercu = _apercu(port, propose, session)
    res = _appliquer(port, propose, session, apercu, 'cache-application-fictif')
    with session() as cnx:
        if cas in {'cle_libre', 'application'}:
            cible = MUTATIONS_APPLIQUEES.c.cle_idempotence == 'cache-application-fictif'
            charge = codec.decoder(cnx.execute(select(MUTATIONS_APPLIQUEES.c.reponse).where(cible)).scalar_one())
            if cas == 'cle_libre':
                charge['secret'] = 'NE-PAS-RESTITUER-FICTIF'
            else:
                charge['application']['assignations'][0]['technicien_id'] = 'ETRANGER-FICTIF'
            cnx.execute(update(MUTATIONS_APPLIQUEES).where(cible).values(reponse=codec.encoder(charge)))
        else:
            cible = APPROBATIONS.c.id == res['approbation_id']
            if cas == 'signataire':
                cnx.execute(update(APPROBATIONS).where(cible).values(decide_par='ETRANGER-FICTIF'))
            elif cas == 'taille':
                cnx.execute(update(APPROBATIONS).where(cible).values(resultat='x' * 70000))
            elif cas == 'absente':
                from sqlalchemy import delete
                cnx.execute(delete(APPROBATIONS).where(cible))
            else:
                cnx.execute(update(APPROBATIONS).where(cible).values(resultat='{"ok": false}'))
    avant = p.m.base._instantane_base(session)
    with pytest.raises(p.v.port.Refus):
        _appliquer(port, propose, session, apercu, 'cache-application-fictif')
    assert p.m.base._instantane_base(session) == avant



def test_deux_plans_meme_equipe_ne_promettent_pas_de_date_et_conflit_civil_refuse(propose, session):
    port = import_module('opsys.console.application_chantier')
    prop = import_module('opsys.console.proposition_chantier')
    premier = _apercu(port, propose, session)
    _appliquer(port, propose, session, premier, 'premiere-affectation-fictive')
    # Deuxième affaire réelle : autre message/client, M2 qualifie, M3 accepte, M4 crée, M6 réserve.
    nouveau = Capacites(propose['deps'], stockage.transaction, filtre={'m01-front-office'}, memoire=False).appeler(
        'm1_recevoir_message_canal', dict(p.b.SMS, expediteur='+15145550143', message_id='SMapplicationautrefictif'))
    assert nouveau['ok'] and nouveau['resultat']['decision'] == 'TRANSMETTRE_M2', nouveau
    lead2, devis2 = nouveau['resultat']['lead']['lead_id'], 'DEVIS-APPLICATION-AUTRE-FICTIF'
    assert p.b._drainer(propose['deps'], p.b.DEBUT)['quarantaines'] == 0
    p.b._qualifier(propose['deps'], lead2)
    p.b._devis_accepte(propose['deps'], lead2, devis2)
    assert p.b._drainer(propose['deps'], p.b.DEBUT)['quarantaines'] == 0
    m4 = p.b._outils(propose['deps'], 'm04-field-ops')
    m6 = p.b._outils(propose['deps'], 'm06-material-control')
    acteur = contexte.IdentiteAppelante(p.AUTH.utilisateur, 'admin', source='console')
    with contexte.appele_par_appareil(acteur):
        p.b._ok(p.executer_atomique(m4['m4_confirmer_localisation'], dict(
            chantier_id=lead2, action='confirmee', horodatage=p.b.ACCEPTE_LE, confirme_par=p.AUTH.utilisateur,
            adresse={'numero_municipal': '102', 'odonyme': 'rue Fictive', 'municipalite': 'Laval'}, source='manuel',
            latitude_microdegres=45590000, longitude_microdegres=-73740000, motif='Seconde position FICTIVE')))
        p.b._ok(p.executer_atomique(m6['m6_receptionner_commande'], dict(
            bon_demande=dict(po_id='PO-APPLICATION-AUTRE-FICTIF', chantier_id='depot-fictif', horodatage=p.b.ACCEPTE_LE,
                lignes_demandees=[dict(materiau_id=p.b.MATERIAU_ID, quantite_demandee=40)]),
            reception_po=dict(po_id='PO-APPLICATION-AUTRE-FICTIF', chantier_id='depot-fictif',
                horodatage=p.b.ACCEPTE_LE,
                lignes_recues=[dict(materiau_id=p.b.MATERIAU_ID, quantite_recue=40)]),
            catalogue_materiaux=dict(version='v1', unite_monetaire='CAD', postes={
                p.b.MATERIAU_ID: dict(cout_unitaire=8, libelle='Matériau FICTIF')}))))
    assert p.b._drainer(propose['deps'], p.b.DEBUT)['quarantaines'] == 0
    with session() as cnx:
        apercu2 = prop.preparer(cnx, propose['deps'], p.AUTH, lead2, devis2)
        proposition2 = prop.proposer(cnx, propose['deps'], p.AUTH, lead2, devis2,
                                     apercu2['empreinte'], 'autre-proposition-fictive')
        plan2 = proposition2['proposition']['plan_id']
        application2 = port.preparer(cnx, propose['deps'], p.AUTH, lead2, devis2, plan2)
        res2 = port.appliquer(cnx, propose['deps'], p.AUTH, lead2, devis2, plan2,
                              application2['empreinte'], 'seconde-affectation-fictive')
        lignes = p.registre.Registre(stockage.maillons('m04-field-ops', 'principal')).lire()
    route1 = premier['revue']['proposition']['plan'][0]
    route2 = proposition2['proposition']['plan'][0]
    assert route1['equipe'] == route2['equipe'] == res2['application']['assignations'][0]['technicien_id']
    assert route1['jour'] == route2['jour'] == 0
    assert route1['visites'][0]['debut_min'] == route2['visites'][0]['debut_min']
    assert len([i for i in lignes if i['type_entree'] == 'cedule_appliquee']) == 2
    assert not any(i['type_entree'] == 'cedule_datee' for i in lignes)
    instant = datetime.now(UTC)
    with (contexte.appele_par_appareil(acteur),
          contexte.receptionne_de(contexte.HorodatageAppareil('console:admin.fictif', instant, instant))):
        p.b._ok(p.executer_atomique(m4['m4_confirmer_dates_cedule'], dict(
            plan_id=propose['plan_id'], calendrier={'0': '2030-06-03'}, revision_attendue=0)))
        avant = p.m.base._instantane_base(session)
        refus = p.executer_atomique(m4['m4_confirmer_dates_cedule'], dict(
            plan_id=plan2, calendrier={'0': '2030-06-03'}, revision_attendue=0))
    assert refus['ok'] is True and refus['resultat']['accepte'] is False, refus
    assert 'conflit' in str(refus).lower()
    assert p.m.base._instantane_base(session) == avant
