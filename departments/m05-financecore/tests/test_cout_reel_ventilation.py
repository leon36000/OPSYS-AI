"""Contrat fictif M4 : la fixture ne prouve pas une jonction réelle."""
import json
from copy import deepcopy
from pathlib import Path

from m5_financecore import cout_reel, encodage


def pieces():
    fixture = Path(__file__).parents[3] / 'docs/grs/crm/CRM01-18-FIXTURE-TEMPS-V2.json'
    p = json.loads(fixture.read_text())["projection"]
    w = {"wct_id": p["wct"]["wct_id"], "intervention_id": p["intervention_id"],
         "duree_reelle_minutes": p["wct"]["duree_reelle_minutes"],
         "horodatage_completion": p["wct"]["horodatage_completion"], "hash_maillon": p["wct"]["hash_maillon"]}
    tarifs = [{"equipe_id": equipe, "taux": taux, "unite": "heure-equipe", "devise": "CAD",
               "source": "tarif-fictif", "version": "1", "date_effet": "2030-01-01", "date_fin": "2030-12-31"}
              for equipe, taux in [("equipe-A-fictive", "100"), ("equipe-B-fictive", "120")]]
    return p, w, tarifs


def calculer(p, w, tarifs, sources=None):
    sources = p["sources"] if sources is None else sources
    cas = encodage.empreinte('m4.temps_certifies.cas.v2', p['instance_id'], p['wct']['wct_id'],
                             *[p['sources'][k]['empreinte_snapshot'] for k in ('principal', 'visites', 'compositions')])
    return cout_reel.calculer_cout_reel(w, {"statut_variance": "evaluee", "lignes": []}, [], None,
                                       projection=p, tarifs_equipes=tarifs, instance_id=p['instance_id'],
                                       source_attendue=cas, sources_actuelles=sources)


def verifier(p):
    p["revue_chantier"]["statut"] = "verifiee"
    p["empreinte"] = encodage.empreinte('m4.temps_certifies.v2', {k: v for k, v in p.items() if k != 'empreinte'})


def test_revue_verifiee_ne_prouve_pas_les_equipes_pointees():
    p, w, tarifs = pieces()
    verifier(p)
    r = calculer(p, w, tarifs)
    assert not r['complet'] and r['cout_total'] is None
    assert r['main_d_oeuvre']['lignes'] == []
    assert r['manque']
    assert r['entrees']['ventilation']['empreinte'] == p['empreinte']


def test_revue_en_attente_ne_produit_pas_de_total_certifie():
    p, w, tarifs = pieces()
    r = calculer(p, w, tarifs)
    assert not r['complet'] and r['cout_total'] is None and r['manque']
    assert r['main_d_oeuvre']['lignes'] == []


def test_tarif_manquant_ne_permet_pas_imputation_d_une_equipe_inconnue():
    p, w, tarifs = pieces()
    verifier(p)
    r = calculer(p, w, tarifs[:1])
    assert not r['complet'] and r['cout_total'] is None
    assert r['main_d_oeuvre']['cout'] is None
    assert r['main_d_oeuvre']['lignes'] == []


def test_source_perimee_et_wct_different_refusent_toute_imputation():
    p, w, tarifs = pieces()
    verifier(p)
    sources = deepcopy(p['sources'])
    sources['principal']['empreinte_snapshot'] = 'a' * 64
    for piece, source in [(w, sources), ({**w, 'intervention_id': 'autre'}, p['sources'])]:
        r = calculer(p, piece, tarifs, source)
        assert not r['complet'] and r['main_d_oeuvre']['cout'] is None
        assert r['cout_total'] is None and r['manque']


def test_tarif_different_ne_certifie_pas_une_equipe_non_identifiee():
    p, w, tarifs = pieces()
    verifier(p)
    nouveau = deepcopy(tarifs)
    nouveau[0]['version'] = '2'
    a, b = calculer(p, w, tarifs), calculer(p, w, nouveau)
    assert a['cout_total'] is None and b['cout_total'] is None
    assert a['main_d_oeuvre']['lignes'] == b['main_d_oeuvre']['lignes'] == []


def test_tarif_non_selectionne_ne_cree_pas_de_cout_certifie():
    p, w, tarifs = pieces()
    verifier(p)
    ancien = tarifs + [tarifs[0] | {'equipe_id': 'equipe-C-fictive', 'version': '1'}]
    nouveau = deepcopy(ancien)
    nouveau[-1]['version'] = '2'
    a, b = calculer(p, w, ancien), calculer(p, w, nouveau)
    assert a['cout_total'] is None and b['cout_total'] is None
    assert a['main_d_oeuvre']['lignes'] == b['main_d_oeuvre']['lignes'] == []
