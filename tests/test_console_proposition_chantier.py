"""fictif: true — port privé de proposition mono-intervention, sources et bus réels."""
import importlib.util
from importlib import import_module
from pathlib import Path

import pytest
from m4_field_ops import etats, registre
from sqlalchemy import select, update

from opsys import contexte, equipes, identite, meteo, stockage
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import MUTATIONS_APPLIQUEES

spec = importlib.util.spec_from_file_location('crm08_proposition_fixture',
                                            Path(__file__).with_name('test_console_preparation_chantier.py'))
v = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v)
AUTH, DEVIS, b, m = v.AUTH, v.DEVIS, v.b, v.m
affaire, catalogue, client_crm = v.affaire, v.catalogue, v.client_crm


@pytest.fixture
def pret(affaire, session):
    equipes.enregistrer_equipes({
        'liste': [{'id': 'eq-fictive', 'membres': ['admin.fictif'], 'competences': ['gouttieres'],
                   'depot': {'id': 'depot-fictif', 'latitude_microdegres': 45580000,
                             'longitude_microdegres': -73750000},
                   'quarts': [{'jour': 0, 'debut_min': 480, 'fin_min': 1020}]}],
        'services': {'gouttieres': {'duree_min': 90, 'competences': ['gouttieres']}},
        'cedule': {'facteur_detour_milliemes': 1300, 'vitesse_moyenne_kmh': 50,
                   'marge_par_trajet_secondes': 60, 'iterations': 10, 'cout_non_cedule_m': 500000},
        'fenetre_par_defaut': {'jours': [0], 'debut_min': 480, 'fin_min': 1020}})
    meteo.enregistrer_meteo({'fuseau': 'America/Montreal', 'services': {
        'gouttieres': {'seuils': {'vent_kmh': {'validation': 25, 'blocage': 40},
            'pluie_mm_h': {'blocage': 3}, 'gel_c': {'blocage': 0}, 'verglas': {'blocage': True},
            'chaleur_c': {'blocage': 35}}}}})
    m4 = b._outils(affaire['deps'], 'm04-field-ops')
    m6 = b._outils(affaire['deps'], 'm06-material-control')
    with contexte.appele_par_appareil(contexte.IdentiteAppelante(AUTH.utilisateur, 'admin', source='console')):
        b._ok(executer_atomique(m4['m4_confirmer_localisation'], dict(
            chantier_id=affaire['lead'], action='confirmee', horodatage=b.ACCEPTE_LE,
            confirme_par=AUTH.utilisateur,
            adresse={'numero_municipal': '100', 'odonyme': 'rue Fictive', 'municipalite': 'Laval'},
            source='manuel', latitude_microdegres=45590000, longitude_microdegres=-73740000,
            motif='Coordonnées FICTIVES saisies par admin pour QA')))
        b._ok(executer_atomique(m6['m6_receptionner_commande'], dict(
            bon_demande=dict(po_id='PO-PROP-FICTIF', chantier_id='depot-fictif', horodatage=b.ACCEPTE_LE,
                lignes_demandees=[dict(materiau_id=b.MATERIAU_ID, quantite_demandee=40)]),
            reception_po=dict(po_id='PO-PROP-FICTIF', chantier_id='depot-fictif', horodatage=b.ACCEPTE_LE,
                lignes_recues=[dict(materiau_id=b.MATERIAU_ID, quantite_recue=40)]),
            catalogue_materiaux=dict(version='v1', unite_monetaire='CAD', postes={
                b.MATERIAU_ID: dict(cout_unitaire=8, libelle='Matériau FICTIF')}))))
    assert b._drainer(affaire['deps'], b.DEBUT)['quarantaines'] == 0
    return affaire


def test_proposition_privee_depuis_devis_reel_sans_assignation(pret, session):
    port = import_module('opsys.console.proposition_chantier')
    avant = m.base._instantane_base(session)
    with session() as cnx:
        apercu = port.preparer(cnx, pret['deps'], AUTH, pret['lead'], DEVIS)
    assert apercu['vue']['preparation']['pret'] is True
    assert m.base._instantane_base(session) == avant
    with session() as cnx:
        res = port.proposer(cnx, pret['deps'], AUTH, pret['lead'], DEVIS, apercu['empreinte'], 'prop-fictive')
        chaine = registre.Registre(stockage.maillons('m04-field-ops', 'principal'))
        iid = apercu['vue']['intervention']['intervention_id']
        assert etats.statut_courant(chaine, iid) == 'a_planifier'
        assert etats.technicien_assigne(chaine, iid) is None
        propositions = [i for i in chaine.lire() if i['type_entree'] == 'cedule_proposee']
    assert len(propositions) == 1
    assert res['proposition']['propose_par'] == AUTH.utilisateur
    assert res['proposition']['totaux']['chantiers_cedules'] == 1
    assert res['proposition']['mode_bride'] is True
    assert 'approximatives' in res['proposition']['avertissement']
    apres = m.base._instantane_base(session)
    with session() as cnx:
        rejoue = port.proposer(cnx, pret['deps'], AUTH, pret['lead'], DEVIS, apercu['empreinte'], 'prop-fictive')
    assert rejoue['rejoue'] is True and rejoue['historique'] is True
    assert m.base._instantane_base(session) == apres


@pytest.mark.parametrize('cause', ['empreinte', 'profil', 'materiel'])
def test_source_changee_refuse_sans_effet(pret, session, cause):
    port = import_module('opsys.console.proposition_chantier')
    with session() as cnx:
        apercu = port.preparer(cnx, pret['deps'], AUTH, pret['lead'], DEVIS)
    if cause == 'profil':
        profil, erreur = equipes.charger_equipes()
        assert erreur is None
        profil['services']['gouttieres']['duree_min'] += 10
        equipes.enregistrer_equipes(profil)
    elif cause == 'materiel':
        outil = b._outils(pret['deps'], 'm06-material-control')['m6_liberer_reservation']
        with contexte.appele_par_appareil(contexte.IdentiteAppelante(AUTH.utilisateur, 'admin', source='console')):
            b._ok(executer_atomique(outil, dict(devis_id=DEVIS, motif='Replanification FICTIVE',
                                               horodatage=b.ACCEPTE_LE)))
        assert b._drainer(pret['deps'], b.DEBUT)['quarantaines'] == 0
    else:
        apercu['empreinte'] = '0' * 64
    avant = m.base._instantane_base(session)
    with session() as cnx, pytest.raises(v.port.Refus, match='SOURCE-MODIFIEE'):
        port.proposer(cnx, pret['deps'], AUTH, pret['lead'], DEVIS, apercu['empreinte'], 'source-fictive')
    assert m.base._instantane_base(session) == avant


def test_non_pret_refuse_et_rejeu_revocation(affaire, session):
    port = import_module('opsys.console.proposition_chantier')
    with session() as cnx:
        apercu = port.preparer(cnx, affaire['deps'], AUTH, affaire['lead'], DEVIS)
    avant = m.base._instantane_base(session)
    with session() as cnx, pytest.raises(v.port.Refus, match='PREPARATION-NON-PRETE'):
        port.proposer(cnx, affaire['deps'], AUTH, affaire['lead'], DEVIS, apercu['empreinte'], 'pas-pret-fictif')
    assert m.base._instantane_base(session) == avant


@pytest.mark.parametrize('etape', ['audit', 'finaliser'])
def test_erreur_finale_annule_proposition_et_recu(pret, session, monkeypatch, etape):
    port = import_module('opsys.console.proposition_chantier')
    with session() as cnx:
        apercu = port.preparer(cnx, pret['deps'], AUTH, pret['lead'], DEVIS)
    def panne(*args, **kwargs):
        raise RuntimeError('Panne FICTIVE après le solveur')
    if etape == 'audit':
        monkeypatch.setattr(port, 'journaliser', panne)
    else:
        monkeypatch.setattr(port.idempotence, 'finaliser', panne)
    avant = m.base._instantane_base(session)
    # L'exception est attrapée à l'intérieur de la transaction extérieure : le savepoint porte le rollback.
    with session() as cnx, pytest.raises(RuntimeError, match='Panne FICTIVE'):
        port.proposer(cnx, pret['deps'], AUTH, pret['lead'], DEVIS, apercu['empreinte'], 'rollback-fictif')
    assert m.base._instantane_base(session) == avant


def test_intention_et_autorite_recontrolees_avant_rejeu(pret, session):
    port = import_module('opsys.console.proposition_chantier')
    with session() as cnx:
        apercu = port.preparer(cnx, pret['deps'], AUTH, pret['lead'], DEVIS)
        port.proposer(cnx, pret['deps'], AUTH, pret['lead'], DEVIS, apercu['empreinte'], 'autorite-fictive')
    avant = m.base._instantane_base(session)
    with session() as cnx, pytest.raises(v.port.Refus, match='MUTATION-CONFLIT'):
        port.proposer(cnx, pret['deps'], AUTH, pret['lead'], DEVIS, '0' * 64, 'autorite-fictive')
    assert m.base._instantane_base(session) == avant
    with session() as cnx:
        identite.retirer_role(cnx, AUTH.utilisateur, 'admin')
    avant = m.base._instantane_base(session)
    with session() as cnx, pytest.raises(PermissionError):
        port.proposer(cnx, pret['deps'], AUTH, pret['lead'], DEVIS, apercu['empreinte'], 'autorite-fictive')
    assert m.base._instantane_base(session) == avant


def test_recu_proposition_reussie_est_finalise_ok(pret, session):
    port = import_module('opsys.console.proposition_chantier')
    with session() as cnx:
        apercu = port.preparer(cnx, pret['deps'], AUTH, pret['lead'], DEVIS)
        port.proposer(cnx, pret['deps'], AUTH, pret['lead'], DEVIS, apercu['empreinte'], 'statut-fictif')
        statut = cnx.execute(select(MUTATIONS_APPLIQUEES.c.statut).where(
            MUTATIONS_APPLIQUEES.c.cle_idempotence == 'statut-fictif')).scalar_one()
    assert statut == 'ok'


def test_profil_change_pendant_solveur_refuse_et_annule_sql(pret, session, monkeypatch):
    port = import_module('opsys.console.proposition_chantier')
    with session() as cnx:
        apercu = port.preparer(cnx, pret['deps'], AUTH, pret['lead'], DEVIS)
    original = port.executer_atomique
    def changer_puis_executer(outil, args):
        profil, erreur = equipes.charger_equipes()
        assert erreur is None
        profil['services']['gouttieres']['duree_min'] = 120
        equipes.enregistrer_equipes(profil)
        return original(outil, args)
    monkeypatch.setattr(port, 'executer_atomique', changer_puis_executer)
    avant = m.base._instantane_base(session)
    with session() as cnx, pytest.raises(v.port.Refus, match='SOURCE-MODIFIEE'):
        port.proposer(cnx, pret['deps'], AUTH, pret['lead'], DEVIS, apercu['empreinte'], 'course-fictive')
    assert m.base._instantane_base(session) == avant
    # La configuration fichier modifiée est une source indépendante, pas un rollback promis par SQLite.
    assert equipes.charger_equipes()[0]['services']['gouttieres']['duree_min'] == 120


@pytest.mark.parametrize('champ', ['enveloppe', 'horodatage'])
def test_recu_historique_ne_restitue_aucune_charge_libre(pret, session, champ):
    port = import_module('opsys.console.proposition_chantier')
    with session() as cnx:
        apercu = port.preparer(cnx, pret['deps'], AUTH, pret['lead'], DEVIS)
        port.proposer(cnx, pret['deps'], AUTH, pret['lead'], DEVIS, apercu['empreinte'], 'cache-fictif')
        cible = MUTATIONS_APPLIQUEES.c.cle_idempotence == 'cache-fictif'
        charge = codec.decoder(cnx.execute(select(MUTATIONS_APPLIQUEES.c.reponse).where(cible)).scalar_one())
        if champ == 'enveloppe':
            charge['trace_privee'] = 'MARQUEUR-FICTIF-A-NE-PAS-EXPOSER'
        else:
            charge['proposition']['horodatage_appareil'] = {'secret': 'MARQUEUR-FICTIF-A-NE-PAS-EXPOSER'}
        cnx.execute(update(MUTATIONS_APPLIQUEES).where(cible).values(reponse=codec.encoder(charge)))
    avant = m.base._instantane_base(session)
    with session() as cnx, pytest.raises(v.port.Refus):
        port.proposer(cnx, pret['deps'], AUTH, pret['lead'], DEVIS, apercu['empreinte'], 'cache-fictif')
    assert m.base._instantane_base(session) == avant


@pytest.mark.parametrize('cas', ['recu_trop_grand', 'sortie_trop_grande'])
def test_bornes_recu_avant_decode_et_rollback_sortie(pret, session, monkeypatch, cas):
    port = import_module('opsys.console.proposition_chantier')
    with session() as cnx:
        apercu = port.preparer(cnx, pret['deps'], AUTH, pret['lead'], DEVIS)
        if cas == 'recu_trop_grand':
            port.proposer(cnx, pret['deps'], AUTH, pret['lead'], DEVIS, apercu['empreinte'], 'borne-fictive')
            cnx.execute(update(MUTATIONS_APPLIQUEES).where(
                MUTATIONS_APPLIQUEES.c.cle_idempotence == 'borne-fictive').values(reponse='x' * 70000))
    if cas == 'recu_trop_grand':
        def interdit(*args, **kwargs):
            raise AssertionError('Le gros reçu ne doit pas atteindre le décodeur')
        monkeypatch.setattr(port.idempotence, 'reclamer', interdit)
    else:
        original = port.lecture._sortie
        def quota(valeur):
            if 'proposition' in valeur:
                raise v.port.Refus('SORTIE-TROP-VOLUMINEUSE')
            return original(valeur)
        monkeypatch.setattr(port.lecture, '_sortie', quota)
    avant = m.base._instantane_base(session)
    with session() as cnx, pytest.raises(v.port.Refus):
        port.proposer(cnx, pret['deps'], AUTH, pret['lead'], DEVIS, apercu['empreinte'], 'borne-fictive')
    assert m.base._instantane_base(session) == avant
