"""Contrat fictif M4 : la fixture ne prouve pas une jonction réelle."""
import json
from copy import deepcopy
from decimal import Decimal
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


def test_deux_equipes_revue_verifiee_et_tarifs_sourcés():
    p, w, tarifs = pieces()
    verifier(p)
    r = calculer(p, w, tarifs)
    assert r['complet'] and r['cout_total'] == Decimal('730.00')
    assert [x['cout'] for x in r['main_d_oeuvre']['lignes']] == [Decimal('250.00'), Decimal('480.00')]
    assert r['entrees']['ventilation']['empreinte'] == p['empreinte']


def test_revue_en_attente_ne_produit_pas_de_total_certifie():
    p, w, tarifs = pieces()
    r = calculer(p, w, tarifs)
    assert not r['complet'] and r['cout_total'] is None and r['manque']
    assert r['main_d_oeuvre']['lignes'] == []


def test_tarif_manquant_preserve_la_part_sourcée_sans_inventer_de_total():
    p, w, tarifs = pieces()
    verifier(p)
    r = calculer(p, w, tarifs[:1])
    assert not r['complet'] and r['cout_total'] is None
    assert r['cout_total_connu'] == Decimal('250.00')
    assert r['main_d_oeuvre']['lignes'][1]['cout'] is None


def test_source_perimee_et_wct_different_refusent_toute_imputation():
    p, w, tarifs = pieces()
    verifier(p)
    sources = deepcopy(p['sources'])
    sources['principal']['empreinte_snapshot'] = 'a' * 64
    for piece, source in [(w, sources), ({**w, 'intervention_id': 'autre'}, p['sources'])]:
        r = calculer(p, piece, tarifs, source)
        assert not r['complet'] and r['main_d_oeuvre']['cout'] is None
        assert r['cout_total'] is None and r['manque']


def test_version_rentabilite_inclut_la_source_du_tarif_meme_si_montant_identique():
    p, w, tarifs = pieces()
    verifier(p)
    nouveau = deepcopy(tarifs)
    nouveau[0]['version'] = '2'
    a, b = calculer(p, w, tarifs), calculer(p, w, nouveau)
    assert a['cout_total'] == b['cout_total'] == Decimal('730.00')
    va = cout_reel.calculer_rentabilite(a, None, None, devis_id='fictif', chantier_id=None)['version_entrees']
    vb = cout_reel.calculer_rentabilite(b, None, None, devis_id='fictif', chantier_id=None)['version_entrees']
    assert va != vb


def test_version_inclut_le_snapshot_des_tarifs_non_selectionnes():
    p, w, tarifs = pieces()
    verifier(p)
    ancien = tarifs + [tarifs[0] | {'equipe_id': 'equipe-C-fictive', 'version': '1'}]
    nouveau = deepcopy(ancien)
    nouveau[-1]['version'] = '2'
    a, b = calculer(p, w, ancien), calculer(p, w, nouveau)
    va = cout_reel.calculer_rentabilite(a, None, None, devis_id='fictif', chantier_id=None)['version_entrees']
    vb = cout_reel.calculer_rentabilite(b, None, None, devis_id='fictif', chantier_id=None)['version_entrees']
    assert a['cout_total'] == b['cout_total'] == Decimal('730.00') and va != vb
