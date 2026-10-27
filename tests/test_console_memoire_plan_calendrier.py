"""fictif: true — contexte civil depuis inscriptions M4 réelles, sans date ni mutation."""
import importlib.util
from importlib import import_module
from pathlib import Path

import pytest

from opsys.console.securite import Session
from opsys.departements import charger_departements

spec = importlib.util.spec_from_file_location('memoire_plan_manuel_fixture',
    Path(__file__).with_name('test_console_dates_cedule.py'))
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)
b = d.base
client_crm, planning = d.client_crm, d.planning
AUTH = Session('admin.fictif', frozenset({'admin'}), 'csrf-fictif', 4102444800)


def test_plan_manuel_inconnu_dans_m10_reste_explicitement_sans_devis(planning, session):
    port = import_module('opsys.console.memoire_plan_calendrier')
    avant = b.base._instantane_base(session)
    with session() as cnx:
        r = port.lire(cnx, charger_departements(), AUTH, planning[2]['plan_id'])
        r2 = port.lire(cnx, charger_departements(), AUTH, planning[2]['plan_id'])
    assert len(r['liaisons']) == len(r['vue']['visites']) == 3
    assert all(lien['origine'] == 'manuelle' and lien['devis_id'] is None for lien in r['liaisons'])
    assert len(r['affaires']) == 3
    assert all(a['paquet']['affaire']['verdict'] == 'AMONT-AFFAIRE-INCONNUE' for a in r['affaires'])
    assert r['empreinte_plan'] == r2['empreinte_plan'] and r['empreinte_memoire'] == r2['empreinte_memoire']
    assert b.base._instantane_base(session) == avant


spec_mixte = importlib.util.spec_from_file_location('memoire_plan_mixte_fixture',
    Path(__file__).with_name('test_console_proposition_chantier.py'))
p = importlib.util.module_from_spec(spec_mixte)
spec_mixte.loader.exec_module(p)
pret, affaire, catalogue = p.pret, p.affaire, p.catalogue


def _manuel(m4, lead, devis, horaire):
    args = dict(contrat=dict(schema_version=2, lead_id=lead, conversation_id='C-FICTIF-' + horaire[-8:],
        service='gouttieres', ville='Laval', canal='telephone',
        contact={'nom': 'Client FICTIF'}, urgence_declaree=False),
        marqueur=dict(readiness_ok=True, lead_id=lead, hash_tete_registre=None,
            horodatage=horaire, empreinte='ab'*32), horodatage=horaire, sel='sel-fictif',
        techniciens_disponibles=['eq-fictive'],
        fenetres_disponibles=[dict(debut='2030-06-03T08:00:00-04:00', fin='2030-06-03T17:00:00-04:00')],
        devis_id=devis)
    r = b.terrain._appeler(m4, 'm4_planifier_intervention', args)
    assert r['ok'] is True and r['resultat']['accepte'] is True, r
    return r['resultat']['intervention_id']


def test_plan_mixte_reel_devis_et_manuels_partageant_affaire(pret, session, monkeypatch, record_testsuite_property):
    import time

    from opsys.console import memoire_chantier as memoire
    from opsys.console import preparation_chantier as lecture

    port = import_module('opsys.console.memoire_plan_calendrier')
    m4 = p.b._outils(pret['deps'], 'm04-field-ops')
    with session() as cnx:
        vue = lecture.lire(cnx, pret['deps'], p.AUTH, pret['lead'], p.DEVIS)
    premier = vue['intervention']['intervention_id']
    meme_affaire = _manuel(m4, pret['lead'], 'DEVIS-DECLARE-NON-VERIFIE', '2030-01-01T00:00:01+00:00')
    autre_lead = 'manuel-sans-devis-fictif'
    autre = _manuel(m4, autre_lead, None, '2030-01-01T00:00:02+00:00')
    b.terrain._resultat(b.terrain._appeler(m4, 'm4_confirmer_localisation', dict(
        chantier_id=autre_lead, action='confirmee', horodatage=p.b.ACCEPTE_LE, confirme_par=p.AUTH.utilisateur,
        adresse=dict(numero_municipal='104', odonyme='rue Fictive', municipalite='Laval'), source='manuel',
        latitude_microdegres=45590000, longitude_microdegres=-73740000, motif='Position FICTIVE QA mixte')))
    plan = b.terrain._resultat(b.terrain._appeler(m4, 'm4_proposer_cedule', dict(
        intervention_ids=[premier, meme_affaire, autre], moteur='auto', horodatage=p.b.ACCEPTE_LE,
        chantiers=[dict(intervention_id=iid, fenetre=dict(jours=[0], debut_min=480, fin_min=1020),
                        creneau_fige=None) for iid in [premier, meme_affaire, autre]])))
    assert plan['totaux']['chantiers_cedules'] == 3, plan
    b.terrain._resultat(b.terrain._appeler(m4, 'm4_appliquer_cedule', dict(plan_id=plan['plan_id'],
        horodatage=p.b.ACCEPTE_LE, confirme_par=p.AUTH.utilisateur)))
    original = memoire._paquet
    appels = []

    def compter(*args):
        appels.append(args[2])
        return original(*args)

    monkeypatch.setattr(memoire, '_paquet', compter)
    avant = p.m.base._instantane_base(session)
    debut = time.perf_counter()
    with session() as cnx:
        r = port.lire(cnx, pret['deps'], p.AUTH, plan['plan_id'])
    duree = time.perf_counter() - debut
    liens = {lien['intervention_id']: lien for lien in r['liaisons']}
    assert len(liens) == 3 and len(r['affaires']) == 2 and len(appels) == len(set(appels)) == 2
    assert liens[premier]['origine'] == 'devis_accepte' and liens[premier]['devis_id'] == p.DEVIS
    assert liens[premier]['lien_m10'] == 'LIE' and liens[premier]['ancre_bus_complete'] is True
    assert liens[meme_affaire]['origine'] == 'manuelle' and liens[meme_affaire]['devis_id'] is None
    assert liens[meme_affaire]['devis_declare'] == 'DEVIS-DECLARE-NON-VERIFIE'
    assert liens[meme_affaire]['lien_m10'] == 'CONTEXTE_AFFAIRE_SANS_DEVIS_VERIFIE'
    assert liens[autre]['devis_id'] is None and r['vue']['revision'] == 0
    assert p.m.base._instantane_base(session) == avant
    record_testsuite_property('civil_m10_mixte_secondes', duree)
    record_testsuite_property('civil_m10_mixte_visites', 3)
    record_testsuite_property('civil_m10_mixte_affaires_et_appels', len(appels))


@pytest.mark.parametrize('defaut', ['lead_modifie', 'inscription_dupliquee', 'faux_devis_accepte',
                                   'travaux_modifies', 'urgence_modifiee'])
def test_inscription_exacte_necessaire(planning, session, defaut):
    from m4_field_ops import registre
    from sqlalchemy import update

    from opsys import stockage
    from opsys.stockage import codec
    from opsys.stockage.schema import REGISTRES

    port = import_module('opsys.console.memoire_plan_calendrier')
    with session() as cnx:
        reg = registre.Registre(stockage.maillons('m04-field-ops', 'principal'))
        lignes = reg.lire()
        cible = next(m for m in lignes if m['type_entree'] == 'intervention_inscrite')
        if defaut == 'lead_modifie':
            cible['lead_id'] = 'autre-affaire-fictive'
        elif defaut == 'inscription_dupliquee':
            lignes.append(cible)
        elif defaut == 'travaux_modifies':
            assert cible['type_travaux'] == 'ravalement'
            cible['type_travaux'] = 'toiture'
        elif defaut == 'urgence_modifiee':
            cible['urgence_declaree'] = not cible['urgence_declaree']
        else:
            cible['source'] = 'm3.devis_accepte'
            cible['devis_id'] = 'DEVIS-NON-ACCEPTE-FICTIF'
        nouvelle = registre.Registre()
        liens = {}
        for m in lignes:
            ancien = m['ligne_id']
            if 'source_application_id' in m:
                m['source_application_id'] = liens[m['source_application_id']]
            liens[ancien] = nouvelle.ajouter(m)
        nouvelle.assert_chaine()
        for rang, m in enumerate(nouvelle.lire()):
            if rang < len(reg.lire()):
                cnx.execute(update(REGISTRES).where((REGISTRES.c.departement == 'm04-field-ops')
                    & (REGISTRES.c.registre == 'principal') & (REGISTRES.c.rang == rang)).values(
                        maillon=codec.encoder(m)))
            else:
                stockage.maillons('m04-field-ops', 'principal').append(m)
    avant = b.base._instantane_base(session)
    with session() as cnx, pytest.raises(ValueError):
        port.lire(cnx, charger_departements(), AUTH, planning[2]['plan_id'])
    assert b.base._instantane_base(session) == avant


@pytest.mark.parametrize('defaut', ['m4', 'm10', 'role'])
def test_changement_pendant_lecture_refuse_retour(planning, session, monkeypatch, defaut):
    from m10_memoire import amont, registre

    from opsys import identite, stockage
    from opsys.console import memoire_chantier as memoire

    port = import_module('opsys.console.memoire_plan_calendrier')
    original = memoire._paquet
    injecte = []

    def perturber(*args):
        r = original(*args)
        if not injecte:
            cnx = stockage.connexion_courante()
            if defaut == 'm4':
                with session():
                    assert b.terrain.etats.transitionner(planning[1]['lead-fictif-001'], 'reportee',
                        b.terrain._registre(), b.terrain.RECU_LE.isoformat(), motif='meteo')[1] is None
            elif defaut == 'm10':
                reg = registre.Registre(stockage.maillons('m10-memoire', 'evenements'))
                assert amont.memoriser('m1.lead_qualifie', dict(lead=dict(lead_id='qa-nouveau-fictif',
                    service='gouttieres', canal='telephone', urgence_declaree=False),
                    horodatage='2030-06-03T08:00:00-04:00'), reg)[1] is None
            else:
                identite.ajouter_role(cnx, AUTH.utilisateur, 'nathan_owner')
                identite.retirer_role(cnx, AUTH.utilisateur, 'admin')
            injecte.append(True)
        return r

    monkeypatch.setattr(memoire, '_paquet', perturber)
    with session() as cnx, pytest.raises((ValueError, PermissionError)):
        port.lire(cnx, charger_departements(), AUTH, planning[2]['plan_id'])
    assert injecte


def test_details_tronques_et_quota_global_ne_deviennent_pas_contexte_complet(planning, session, monkeypatch):
    from opsys.console import preparation_chantier as lecture

    port = import_module('opsys.console.memoire_plan_calendrier')
    original = lecture._appel

    def tronquer(*args, **kwargs):
        r = original(*args, **kwargs)
        if args[3] == 'm4_lire_calendrier_plan':
            r.update(total_visites=201, tronque=True)
        return r

    avant = b.base._instantane_base(session)
    monkeypatch.setattr(lecture, '_appel', tronquer)
    with session() as cnx, pytest.raises(lecture.Refus, match='PLAN-INCOMPLET'):
        port.lire(cnx, charger_departements(), AUTH, planning[2]['plan_id'])
    monkeypatch.setattr(lecture, '_appel', original)
    monkeypatch.setattr(lecture, 'MAX_SORTIE_OCTETS', 4500)
    with session() as cnx, pytest.raises(lecture.Refus, match='SORTIE-TROP-VOLUMINEUSE'):
        port.lire(cnx, charger_departements(), AUTH, planning[2]['plan_id'])
    assert b.base._instantane_base(session) == avant


def test_bus_m3_non_representable_conserve_vrai_lien_sans_projection_m10(pret, session):
    from opsys import contexte
    from opsys.outils import executer_atomique

    lead, devis = 'lead-fictif-é', 'DEVIS-UNICODE-CIVIL-FICTIF'
    # Publication M1 de fixture contractuelle; vrais M2/M3/M4/M6, pas un nouveau SMS M1.
    p.b._publier_lead(p.b._lead_v2(lead))
    p.b._drainer(pret['deps'], p.b.DEBUT)
    p.b._qualifier(pret['deps'], lead)
    evenement = p.b._devis_accepte(pret['deps'], lead, devis)
    p.b._drainer(pret['deps'], p.b.DEBUT)
    assert p.b._recu(evenement, 'm04-field-ops')['statut'] == 'traite'
    assert p.b._recu(evenement, 'm10-memoire')['statut'] == 'quarantaine'
    m4 = p.b._outils(pret['deps'], 'm04-field-ops')
    m6 = p.b._outils(pret['deps'], 'm06-material-control')
    with contexte.appele_par_appareil(contexte.IdentiteAppelante(AUTH.utilisateur, 'admin', source='console')):
        p.b._ok(executer_atomique(m4['m4_confirmer_localisation'], dict(
            chantier_id=lead, action='confirmee', horodatage=p.b.ACCEPTE_LE, confirme_par=AUTH.utilisateur,
            adresse=dict(numero_municipal='106', odonyme='rue Fictive', municipalite='Laval'), source='manuel',
            latitude_microdegres=45590000, longitude_microdegres=-73740000, motif='Position FICTIVE Unicode')))
        p.b._ok(executer_atomique(m6['m6_receptionner_commande'], dict(
            bon_demande=dict(po_id='PO-UNICODE-CIVIL-FICTIF', chantier_id='depot-fictif',
                horodatage=p.b.ACCEPTE_LE, lignes_demandees=[dict(materiau_id=p.b.MATERIAU_ID, quantite_demandee=80)]),
            reception_po=dict(po_id='PO-UNICODE-CIVIL-FICTIF', chantier_id='depot-fictif',
                horodatage=p.b.ACCEPTE_LE, lignes_recues=[dict(materiau_id=p.b.MATERIAU_ID, quantite_recue=80)]),
            catalogue_materiaux=dict(version='v1', unite_monetaire='CAD', postes={p.b.MATERIAU_ID:
                dict(cout_unitaire=8, libelle='Matériau FICTIF')}))))
    p.b._drainer(pret['deps'], p.b.DEBUT)
    with session():
        iid = p.etats.intervention_du_devis(b.terrain._registre(), devis)
    plan = b.terrain._resultat(b.terrain._appeler(m4, 'm4_proposer_cedule', dict(
        intervention_ids=[iid], moteur='auto', horodatage=p.b.ACCEPTE_LE)))
    assert plan['totaux']['chantiers_cedules'] == 1, plan
    b.terrain._resultat(b.terrain._appeler(m4, 'm4_appliquer_cedule', dict(plan_id=plan['plan_id'],
        horodatage=p.b.ACCEPTE_LE, confirme_par=AUTH.utilisateur)))
    port = import_module('opsys.console.memoire_plan_calendrier')
    avant = p.m.base._instantane_base(session)
    with session() as cnx:
        r = port.lire(cnx, pret['deps'], AUTH, plan['plan_id'])
    assert r['liaisons'][0]['origine'] == 'devis_accepte' and r['liaisons'][0]['devis_id'] == devis
    assert r['liaisons'][0]['lien_m10'] == 'NON_REPRESENTABLE'
    assert r['liaisons'][0]['reference_devis'] is None
    assert r['affaires'] == [dict(lead_id=lead, affaire_id=None, etat='NON_REPRESENTABLE', paquet=None)]
    assert p.m.base._instantane_base(session) == avant
