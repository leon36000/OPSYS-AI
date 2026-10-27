"""fictif: true — formulaire HTTP, acceptation explicite et répartiteur SQL réels."""
import importlib.util
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlencode

from opsys import evenements, stockage, taxonomie
from opsys.capacites import Capacites
from opsys.outils import executer_atomique


def charger(nom, fichier):
    spec = importlib.util.spec_from_file_location(nom, Path(__file__).with_name(fichier))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


h = charger('prefill_http_bus', 'test_console_prefill_http.py')
b = charger('cascade_prefill_bus', 'test_cascade_devis_accepte.py')
client_crm = h.client_crm
catalogue = h.catalogue
INSTANT = datetime(2030, 6, 3, tzinfo=UTC)


def test_prefill_http_acceptation_bus_departements_et_relivraison(catalogue, session, declarer_services):
    declarer_services()
    taxonomie.enregistrer_zone_desservie(['Laval'])
    deps = b._departements()
    lead_id = 'lead-prefill-bus-fictif'
    b._publier_lead(b._lead_v2(lead_id))
    assert b._drainer(deps, INSTANT)['quarantaines'] == 0
    b._qualifier(deps, lead_id)
    initial = h.p.preparer(session)
    query = urlencode({k: initial[k] for k in ('modele_id', 'modele_revision', 'modele_source')})
    action, choix = h.form(catalogue.get(f'/crm/lead/{lead_id}/soumission-preremplie?{query}'))
    choix.update(quantite_0='2', fournisseur_id_0='fourn-fictif', taux_marge='0.2')
    action, donnees = h.form(catalogue.post(action, data=choix))
    assert catalogue.post(action, data=donnees, follow_redirects=False).status_code == 303
    devis_id = donnees['devis_id']
    # Un brouillon ne convertit ni ne réserve, même si on livre tout le bus.
    assert b._drainer(deps, INSTANT)['echecs'] == 0
    assert b._interventions(deps) == []
    assert b._maillons('m06-material-control', 'besoins_prevus') == []
    # Le prix est figé avant acceptation, malgré un nouveau tarif fournisseur.
    h.p.prix(session, 17)
    stockage.liberer()
    b._ok(executer_atomique(b._outils(deps, b.M3)['m3_marquer_devis_accepte'], {
        'devis_id': devis_id, 'approbateur': 'Nathan FICTIF, validation T3',
        'horodatage': '2030-06-02T12:00:00+00:00'}))
    event_id = f'm3-devis-accepte-{devis_id}'
    charge = b._charge_publiee(event_id)
    assert Decimal(charge['prix_total']) == Decimal('30.00')
    assert Decimal(charge['cout_total']) == Decimal('25.00')
    for prive in ('provenance_tarifs', 'fourn-fictif', 'prix-fictif.pdf', donnees['tarif_empreinte_0']):
        assert prive not in json.dumps(charge)
    total = b._drainer(deps, INSTANT)
    assert total['echecs'] == total['quarantaines'] == 0, total
    for consommateur in b.CONSOMMATEURS:
        assert b._recu(event_id, consommateur)['statut'] == 'traite'
    assert b.m2_statuts.statut_courant(b.m2_outils._obtenir_registre(), lead_id) == 'converti'
    intervention, = b._interventions(deps)
    assert intervention['devis_id'] == devis_id and intervention['lead_id'] == lead_id
    assert intervention['statut'] == 'a_planifier'
    assert intervention['technicien_assigne'] is intervention['fenetre_planifiee'] is None
    preparation = Capacites(deps, stockage.transaction, filtre={b.M4}, memoire=False).appeler(
        'm4_verifier_preparation', {'intervention_id': intervention['intervention_id']})['resultat']['resultat']
    assert preparation['pret'] is False and preparation['statut'] == 'bloque'
    assert 'materiel' in [f['volet'] for f in preparation['a_fournir']]
    for dep, registre in [('m05-financecore', 'devis_recus'), ('m08-analytics', 'faits_chantier')]:
        assert [m['devis_id'] for m in b._maillons(dep, registre)] == [devis_id]
    besoin, = b._maillons('m06-material-control', 'besoins_prevus')
    assert besoin['devis_id'] == devis_id
    ligne, = besoin['lignes']
    assert ligne['materiau_id'] == 'mat-fictif' and ligne['unite'] == 'pi'
    assert Decimal(str(ligne['quantite_estimee'])) == 2
    from m6_material_control import reservations
    reservation = reservations.etat(devis_id, b._maillons('m06-material-control', 'reservations'))
    assert reservation is not None
    assert reservations.statut_pret(reservation['lignes']) == 'a_commander'
    assert Decimal(reservation['lignes'][0]['quantite_reservee']) == 0
    avant = b._empreinte_etat()
    evenements.publier('m3.devis_accepte', b.M3, charge, evenement_id=event_id)
    assert b._drainer(deps, INSTANT)['livres'] == 0
    assert b._empreinte_etat() == avant
    evenements.publier('m3.devis_accepte', b.M3, charge, evenement_id='redelivery-prefill-fictif')
    total = b._drainer(deps, INSTANT)
    assert total['echecs'] == total['quarantaines'] == 0
    assert b._empreinte_etat()['registres'] == avant['registres']
    assert len(b._interventions(deps)) == 1
