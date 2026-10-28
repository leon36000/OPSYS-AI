"""fictif: true — devis accepté et bus réels, lecture de préparation sans effet."""
import importlib.util
from pathlib import Path

import pytest
from m1_front_office import outils as m1
from sqlalchemy import delete, select, update

from opsys import contexte, identite, stockage, taxonomie
from opsys.capacites import Capacites
from opsys.console import preparation_chantier as port
from opsys.console.securite import Session
from opsys.departements import charger_departements
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS, REGISTRES


def charger(nom, fichier):
    spec = importlib.util.spec_from_file_location(nom, Path(__file__).with_name(fichier))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


m = charger('preparation_chantier_crm', 'test_console_modeles_soumission.py')
b = charger('preparation_chantier_bus', 'test_cascade_devis_accepte.py')
client_crm = m.client_crm
catalogue = m.catalogue
LEAD = 'lead-fictif-001'
DEVIS = 'DEVIS-CRM08-FICTIF'
ROUTE = f'/crm/lead/{LEAD}/soumissions/{DEVIS}/preparation-chantier'
AUTH = Session('admin.fictif', frozenset({'admin'}), 'csrf-fictif', 4102444800)


def test_acceptation_en_attente_ne_cree_pas_de_chantier(catalogue, session):
    b._devis_accepte(charger_departements(), LEAD, DEVIS)
    avant = m.base._instantane_base(session)
    page = catalogue.get(ROUTE)
    assert page.status_code == 200, page.text
    assert 'Réception M4 en attente' in page.text
    assert 'Source M1 absente' in page.text
    assert m.base._instantane_base(session) == avant


@pytest.fixture
def affaire(catalogue, session, declarer_services):
    declarer_services()
    taxonomie.enregistrer_zone_desservie(['Laval', 'Québec'])
    m1.utiliser_stockage_durable()
    deps = charger_departements()
    reponse = Capacites(deps, stockage.transaction, filtre={'m01-front-office'}, memoire=False).appeler(
        'm1_recevoir_message_canal', b.SMS)
    assert reponse['ok'] and reponse['resultat']['decision'] == 'TRANSMETTRE_M2', reponse
    lead = reponse['resultat']['lead']['lead_id']
    assert b._drainer(deps, b.DEBUT)['quarantaines'] == 0
    b._qualifier(deps, lead)
    evenement = b._devis_accepte(deps, lead, DEVIS)
    total = b._drainer(deps, b.DEBUT)
    assert total['echecs'] == total['quarantaines'] == 0, total
    try:
        yield dict(deps=deps, lead=lead, devis=DEVIS, evenement=evenement,
                   route=f'/crm/lead/{lead}/soumissions/{DEVIS}/preparation-chantier')
    finally:
        m1.reinitialiser_registre()


def test_vrai_bus_affiche_intervention_et_preparation_bloquee_sans_prix(affaire, catalogue, session):
    avant = m.base._instantane_base(session)
    page = catalogue.get(affaire['route'])
    assert page.status_code == 200, page.text
    assert page.headers['cache-control'] == 'no-store'
    assert 'Réception M4 confirmée' in page.text and 'Source M1 vérifiée' in page.text
    assert 'a_planifier' in page.text and 'Préparation M4 : bloque' in page.text
    for volet in ('adresse', 'equipe', 'materiel', 'meteo'):
        assert f'{volet} :' in page.text
    for prive in (b.NUMERO, '600.00', '8.00', '160.00', 'cout_total', 'prix_total', 'taux_marge'):
        assert prive not in page.text
    assert 'prévision du créneau' in page.text
    assert m.base._instantane_base(session) == avant
    fiche = catalogue.get(affaire['route'].removesuffix('/preparation-chantier'))
    assert fiche.status_code == 200 and 'Préparer la planification' in fiche.text


def test_quarantaine_sans_fait_m1_reste_visible_sans_reparation(catalogue, session):
    deps = charger_departements()
    ident = b._devis_accepte(deps, LEAD, DEVIS)
    b._drainer(deps, b.DEBUT)
    assert b._recu(ident, 'm04-field-ops')['statut'] == 'quarantaine'
    avant = m.base._instantane_base(session)
    page = catalogue.get(ROUTE)
    assert page.status_code == 200 and 'Réception M4 en quarantaine' in page.text
    assert 'Source M1 absente' in page.text and 'Aucune intervention M4 trouvée' in page.text
    assert m.base._instantane_base(session) == avant


def test_acceptation_historique_non_publiee_distincte_attente(catalogue, session):
    ident = b._devis_accepte(charger_departements(), LEAD, DEVIS)
    with session() as cnx:
        cnx.execute(delete(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.evenement_id == ident))
    avant = m.base._instantane_base(session)
    page = catalogue.get(ROUTE)
    assert page.status_code == 200 and 'Acceptation sans publication vers M4' in page.text
    assert 'Intervention non vérifiée' in page.text
    assert m.base._instantane_base(session) == avant


def test_devis_non_accepte_ou_lien_etranger_refuse(affaire, catalogue, session):
    avant = m.base._instantane_base(session)
    assert catalogue.get(affaire['route'].replace(affaire['lead'], LEAD)).status_code == 404
    assert catalogue.get(affaire['route'].replace(DEVIS, 'inconnu-fictif')).status_code == 404
    assert catalogue.post(affaire['route'], data={}).status_code == 405
    assert m.base._instantane_base(session) == avant


def test_brouillon_n_offre_aucun_raccourci_acceptation(catalogue, session):
    outil = b._outils(charger_departements(), b.M3)['m3_creer_devis']
    b._ok(executer_atomique(outil, dict(devis_id=DEVIS, lead_id=LEAD, chantier_id=None,
        lignes=[dict(description='Travaux FICTIFS', quantite='1', unite='pi', cout_unitaire='8',
                     reference_besoin_materiau=None)], taux_marge='0.25', horodatage=b.ACCEPTE_LE,
        prix_total='10.00')))
    avant = m.base._instantane_base(session)
    assert catalogue.get(ROUTE).status_code == 409
    page = catalogue.get(ROUTE.removesuffix('/preparation-chantier'))
    assert page.status_code == 200 and 'preparation-chantier' not in page.text
    assert m.base._instantane_base(session) == avant


def test_identite_revocation_et_expiration_avant_sources(affaire, catalogue, client_crm, session, monkeypatch):
    def interdit(*args, **kwargs):
        raise AssertionError('Lecture de source interdite avant contrôle du rôle')

    monkeypatch.setattr(port, '_borner', interdit)
    for utilisateur in ('employe', 'nathan'):
        m.base._connecter(client_crm, utilisateur)
        avant = m.base._instantane_base(session)
        assert client_crm.get(affaire['route']).status_code == 403
        assert m.base._instantane_base(session) == avant
    with pytest.raises(PermissionError), session() as cnx:
        port.lire(cnx, affaire['deps'], Session(AUTH.utilisateur, AUTH.roles, AUTH.csrf, 0), affaire['lead'], DEVIS)
    m.base._connecter(client_crm, 'admin.fictif')
    with session() as cnx:
        identite.retirer_role(cnx, 'admin.fictif', 'admin')
    avant = m.base._instantane_base(session)
    assert client_crm.get(affaire['route']).status_code == 403
    assert m.base._instantane_base(session) == avant


@pytest.mark.parametrize('cas', ['publication', 'recu', 'chaine', 'intervention_absente'])
def test_sources_incoherentes_ne_deviennent_pas_pretes(affaire, catalogue, session, cas):
    with session() as cnx:
        if cas == 'publication':
            condition = EVENEMENTS_SORTANTS.c.evenement_id == affaire['evenement']
            charge = codec.decoder(cnx.execute(select(EVENEMENTS_SORTANTS.c.charge).where(condition)).scalar_one())
            charge['lignes'][0]['description'] = 'CORRUPTION-FICTIVE'
            cnx.execute(update(EVENEMENTS_SORTANTS).where(condition).values(charge=codec.encoder(charge)))
        elif cas == 'recu':
            condition = ((EVENEMENTS_RECUS.c.evenement_id == affaire['evenement'])
                         & (EVENEMENTS_RECUS.c.consommateur == 'm04-field-ops'))
            resultat = codec.decoder(cnx.execute(select(EVENEMENTS_RECUS.c.resultat).where(condition)).scalar_one())
            resultat['intervention_id'] = 'ETRANGERE-FICTIVE'
            cnx.execute(update(EVENEMENTS_RECUS).where(condition).values(resultat=codec.encoder(resultat)))
        else:
            condition = (REGISTRES.c.departement == 'm04-field-ops') & (REGISTRES.c.registre == 'principal')
            if cas == 'intervention_absente':
                cnx.execute(delete(REGISTRES).where(condition))
            else:
                condition &= REGISTRES.c.rang == 0
                maillon = codec.decoder(cnx.execute(select(REGISTRES.c.maillon).where(condition)).scalar_one())
                maillon['ligne_id'] = 'f' * 64
                cnx.execute(update(REGISTRES).where(condition).values(maillon=codec.encoder(maillon)))
    avant = m.base._instantane_base(session)
    assert catalogue.get(affaire['route']).status_code == 503
    assert m.base._instantane_base(session) == avant


def test_bornes_refusent_sans_tronquer_et_lecture_directe_sans_effet(affaire, catalogue, session, monkeypatch):
    avant = m.base._instantane_base(session)
    with contexte.sortie_bornee(1), session() as cnx, pytest.raises(port.Refus, match='SORTIE-TROP-VOLUMINEUSE'):
        port.lire(cnx, affaire['deps'], AUTH, affaire['lead'], DEVIS)
    assert m.base._instantane_base(session) == avant
    monkeypatch.setattr(port, 'MAX_SOURCES', 0)
    assert catalogue.get(affaire['route']).status_code == 503
    assert m.base._instantane_base(session) == avant


def test_reservation_m6_reelle_reception_puis_liberation_relue(affaire, catalogue, session):
    def lire_volet():
        avant = m.base._instantane_base(session)
        with session() as cnx:
            vue = port.lire(cnx, affaire['deps'], AUTH, affaire['lead'], DEVIS)
        assert m.base._instantane_base(session) == avant
        return vue['preparation']['volets']['materiel']['statut']

    assert lire_volet() == 'manque'
    m6 = b._outils(affaire['deps'], 'm06-material-control')
    bon = dict(po_id='PO-CRM08-FICTIF', chantier_id='DEPOT-FICTIF', horodatage=b.ACCEPTE_LE,
               lignes_demandees=[dict(materiau_id=b.MATERIAU_ID, quantite_demandee=40)])
    reception = dict(po_id=bon['po_id'], chantier_id=bon['chantier_id'], horodatage=b.ACCEPTE_LE,
                     lignes_recues=[dict(materiau_id=b.MATERIAU_ID, quantite_recue=40)])
    catalogue_fictif = dict(version='v1', unite_monetaire='CAD',
                            postes={b.MATERIAU_ID: dict(cout_unitaire=8, libelle='Gouttière FICTIVE')})
    with contexte.appele_par_appareil(contexte.IdentiteAppelante(AUTH.utilisateur, 'admin', source='console')):
        recu = executer_atomique(m6['m6_receptionner_commande'], dict(
            bon_demande=bon, reception_po=reception, catalogue_materiaux=catalogue_fictif))
    b._ok(recu)
    assert b._drainer(affaire['deps'], b.DEBUT)['quarantaines'] == 0
    assert lire_volet() == 'ok'
    with contexte.appele_par_appareil(contexte.IdentiteAppelante(AUTH.utilisateur, 'admin', source='console')):
        libere = executer_atomique(m6['m6_liberer_reservation'], dict(
            devis_id=DEVIS, motif='Replanification FICTIVE', horodatage=b.ACCEPTE_LE))
    b._ok(libere)
    assert b._drainer(affaire['deps'], b.DEBUT)['quarantaines'] == 0
    assert lire_volet() != 'ok'


@pytest.mark.parametrize('champ', ['service', 'urgence_declaree', 'ville'])
def test_fait_m1_contradictoire_refuse_apres_bus_valide(affaire, catalogue, session, champ):
    with session() as cnx:
        condition = EVENEMENTS_SORTANTS.c.evenement_id == f"m1-lead-qualifie-{affaire['lead']}"
        charge = codec.decoder(cnx.execute(select(EVENEMENTS_SORTANTS.c.charge).where(condition)).scalar_one())
        if champ == 'service':
            charge['lead']['service'] = 'revetement'
        elif champ == 'ville':
            charge['lead']['ville'] = 'Québec'
        else:
            charge['lead']['urgence_declaree'] = not charge['lead']['urgence_declaree']
        assert not port.erreurs_charge('m1.lead_qualifie', charge)
        cnx.execute(update(EVENEMENTS_SORTANTS).where(condition).values(charge=codec.encoder(charge)))
    avant = m.base._instantane_base(session)
    assert catalogue.get(affaire['route']).status_code == 503
    assert m.base._instantane_base(session) == avant
