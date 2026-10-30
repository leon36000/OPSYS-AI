"""Jeu de données V3 synthétique partagé par les tests de calcul purs."""

import json
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from m5_financecore import cout_reel, encodage


def _signal_defaut():
    return {"wct_id": "WCT-1", "chantier_id": "CH-1", "statut_variance": "evaluee",
            "signal_critique": False, "lignes": [{"materiau": "gouttiere-alu-5po-fictif",
            "unite": "pi", "quantite_prevue": "40.0", "quantite_reelle": "42.0",
            "ecart_pourcentage": "0.05", "critique": False}]}


def _prix_defaut():
    return {"materiau_id": "gouttiere-alu-5po-fictif", "fournisseur_id": "gentek-fictif",
            "prix_unitaire": 8.0, "devise": "CAD", "date_effet": "2026-09-01",
            "source_document": None, "unite": "pi"}


def _calculer_cout_v3(*, minutes=180, taux='50.00', signal=None, livre=None,
             completion='2026-09-15T15:00:00+00:00'):
    """Fixture structurelle fictive : elle ne prouve pas l'origine du producteur M4."""
    fichier = Path(__file__).parents[3] / 'docs/grs/crm/CRM01-18-FIXTURE-TEMPS-V3.json'
    p = json.loads(fichier.read_text())['projection']
    visite = deepcopy(p['visites'][1])
    p['intervention_id'] = 'INT-1'
    visite['ancre']['intervention_id'] = p['intervention_id']
    depart = datetime.fromisoformat(completion)
    arrivee = depart - timedelta(minutes=minutes)
    visite['ouverture']['horodatage'] = (arrivee - timedelta(minutes=40)).isoformat()
    visite['composition_declaree']['jour'] = arrivee.date().isoformat()
    visite['composition_declaree']['horodatage'] = (arrivee - timedelta(minutes=45)).isoformat()
    visite['evenements'][0]['horodatage'] = (arrivee - timedelta(minutes=30)).isoformat()
    visite['evenements'][1]['horodatage'] = arrivee.isoformat()
    visite['evenements'][2]['horodatage'] = depart.isoformat()
    visite['fermeture']['horodatage'] = (depart + timedelta(minutes=1)).isoformat()
    visite['minutes']['travail'] = minutes
    p['visites'] = [visite]
    p['totaux'] = {'travail': minutes, 'pause': 0, 'deplacement': 30}
    p['wct'].update(wct_id='WCT-1', duree_reelle_minutes=minutes, horodatage_completion=depart.isoformat(),
                    horodatage_transition=(depart + timedelta(minutes=2)).isoformat())
    p['revue_chantier']['statut'] = 'verifiee'
    p['inconnus'] = [{'code': 'chantier_id_indisponible', 'visite_id': None},
                     {'code': 'presence_individuelle_non_observee', 'visite_id': visite['visite_id']}]
    p['empreinte'] = encodage.empreinte('m4.temps_certifies.v3', {k: v for k, v in p.items() if k != 'empreinte'})
    wct = {'wct_id': p['wct']['wct_id'], 'intervention_id': p['intervention_id'],
           'hash_maillon': p['wct']['hash_maillon'], 'duree_reelle_minutes': minutes,
           'horodatage_completion': p['wct']['horodatage_completion']}
    tarif = {'equipe_id': visite['equipe_pointee']['identifiant'], 'taux': taux, 'unite': 'heure-equipe',
             'devise': 'CAD', 'source': 'tarif-fictif', 'version': '1',
             'date_effet': '2026-01-01', 'date_fin': '2026-12-31'}
    signal = deepcopy(_signal_defaut() if signal is None else signal)
    signal['horodatage_completion'] = depart.isoformat()
    return cout_reel.calculer_cout_reel(
        wct, signal, [_prix_defaut()] if livre is None else livre, None,
        projection=p, tarifs_equipes=[tarif], instance_id=p['instance_id'], source_attendue='a' * 64,
        source_relue='a' * 64, sources_actuelles=p['sources'])


@pytest.fixture
def cout_v3():
    return _calculer_cout_v3
