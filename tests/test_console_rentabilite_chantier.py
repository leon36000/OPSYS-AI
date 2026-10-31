"""fictif: true — coûts d'un devis M3 exact, vrai M5, aucun effet financier de la lecture."""
import importlib.util
from importlib import import_module
from pathlib import Path

import pytest

from opsys import evenements, identite, stockage
from opsys.stockage import codec
from opsys.stockage.schema import REGISTRES

spec = importlib.util.spec_from_file_location('rentabilite_crm_fixture',
    Path(__file__).with_name('test_console_preparation_chantier.py'))
f = importlib.util.module_from_spec(spec)
spec.loader.exec_module(f)
client_crm, catalogue, affaire = f.client_crm, f.catalogue, f.affaire
FICTIF = True


def test_devis_reel_recu_m5_attend_wct_sans_ecriture(affaire, session):
    port = import_module('opsys.console.rentabilite_chantier')
    avant = f.m.base._instantane_base(session)
    with session() as cnx:
        r = port.lire(cnx, affaire['deps'], f.AUTH, affaire['lead'], f.DEVIS)
    assert r['lead_id'] == affaire['lead'] and r['devis_id'] == f.DEVIS
    assert r['reception_m5'] == 'TRAITE'
    assert r['chantier']['statut'] == 'en_attente_travaux_termines'
    assert 'rentabilite' not in r['chantier']
    assert r['source_calculee'] and len(r['source_calculee']) == 64
    assert f.m.base._instantane_base(session) == avant



spec_m5 = importlib.util.spec_from_file_location('rentabilite_contrat_m5_fixture',
    Path(__file__).parents[1] / 'departments/m05-financecore/tests/test_lecture_rentabilite.py')
b = importlib.util.module_from_spec(spec_m5)
spec_m5.loader.exec_module(b)


@pytest.fixture
def complet(affaire, session, tmp_path, monkeypatch):
    """M3 réel, complétion M4 contractuelle fictive, vrai bus/calcul M5; pas une exécution M4 prouvée."""
    from m5_financecore import outils as m5

    config = tmp_path / 'm5-crm10-fictif.yaml'
    config.write_text('configuration:\n  taux_horaire_main_d_oeuvre: "50.00"\n')
    monkeypatch.setattr(m5, '_MANIFESTE', config)
    b._prix_au_livre()
    charge = {**b._wct('WCT-CRM10-FICTIF', f.DEVIS), 'lead_id': affaire['lead']}
    evenements.publier('m4.travaux_termines', 'm04-field-ops', charge)
    var = b._variance('WCT-CRM10-FICTIF', 'CHANTIER-CRM10-FICTIF')
    evenements.publier('m6.variance_chantier', 'm06-material-control', var, evenement_id=var['evenement_id'])
    b._livrer()
    with session() as cnx:
        charge = f.port._publication(cnx, affaire['evenement'], 'm3.devis_accepte', 'm03-estimation')
        lignes = [dict(description=ligne['description'], quantite=ligne['quantite'], unite=ligne['unite'],
            prix_unitaire=ligne['prix_unitaire'], reference_ligne_devis=ligne['reference_ligne'])
            for ligne in charge['lignes']]
        taux, erreurs = m5.taux_fiscaux.charger_taux_fiscaux(m5._CHEMIN_TAUX_FISCAUX)
        assert not erreurs
        resultat, verdict = m5.facturation.creer_facture_brouillon('FAC-CRM10-FICTIF', 'CHANTIER-CRM10-FICTIF',
            f.DEVIS, affaire['lead'], lignes, b.COMPLETION, taux, m5._registre_factures(None),
            montant_avant_taxes_fourni=charge['prix_total'])
        assert verdict is None and resultat['statut'] == 'BROUILLON'
    return {**affaire, 'config': config}


def test_cout_partiel_de_vrai_m5_sans_effet(complet, session):
    """Le WCT fictif n'a qu'une durée scalaire : sans équipe pointée et certifiée, la main-d'oeuvre reste inconnue."""
    port = import_module('opsys.console.rentabilite_chantier')
    avant = f.m.base._instantane_base(session)
    with session() as cnx:
        r = port.lire(cnx, complet['deps'], f.AUTH, complet['lead'], f.DEVIS)
    rentabilite = r['chantier']['rentabilite']
    cout = rentabilite['cout_reel']
    assert (cout['complet'], cout['cout_total'], cout['cout_total_connu']) == (False, None, '336.00')
    assert cout['main_d_oeuvre']['statut'] == 'non_disponible' and cout['main_d_oeuvre']['cout'] is None
    assert [m['code'] for m in cout['manque']] == ['REJ-COUT-TEMPS-POINTE-ABSENT']
    assert rentabilite['marge_reelle'] is None and rentabilite['marge_partielle_plafond'] == '264.00'
    assert r['chantier']['rentabilite']['prix_definitif'] is False
    assert r['mention'] == b.MENTION
    assert f.m.base._instantane_base(session) == avant


def test_configuration_aba_ne_peut_citer_a_pour_couts_b(complet, session, monkeypatch):
    port = import_module('opsys.console.rentabilite_chantier')
    config, source = complet['config'], complet['config'].read_bytes()
    original_ancre, original_m5 = port._ancre, port._m5
    appels = []

    def ancre(*args):
        r = original_ancre(*args)
        if not appels:
            config.write_text('configuration:\n  taux_horaire_main_d_oeuvre: "100.00"\n')
        appels.append(1)
        return r

    def m5(*args):
        r = original_m5(*args)
        config.write_bytes(source)
        return r

    monkeypatch.setattr(port, '_ancre', ancre)
    monkeypatch.setattr(port, '_m5', m5)
    with session() as cnx, pytest.raises(f.port.Refus):
        port.lire(cnx, complet['deps'], f.AUTH, complet['lead'], f.DEVIS)
    assert config.read_bytes() == source


def test_facture_alteree_sans_rechainer_refuse(complet, session):
    from sqlalchemy import select, update

    port = import_module('opsys.console.rentabilite_chantier')
    with session() as cnx:
        condition = ((REGISTRES.c.departement == 'm05-financecore') & (REGISTRES.c.registre == 'factures'))
        ligne = codec.decoder(cnx.execute(select(REGISTRES.c.maillon).where(condition)).scalar_one())
        ligne['montant_avant_taxes'] = '999.00'
        cnx.execute(update(REGISTRES).where(condition).values(maillon=codec.encoder(ligne)))
    with session() as cnx, pytest.raises(f.port.Refus):
        port.lire(cnx, complet['deps'], f.AUTH, complet['lead'], f.DEVIS)


def test_revocation_pendant_derniere_relecture_refuse(affaire, session, monkeypatch):
    port = import_module('opsys.console.rentabilite_chantier')
    original = port._reception
    appels = []

    def reception(*args):
        r = original(*args)
        appels.append(1)
        if len(appels) == 2:
            cnx = stockage.connexion_courante()
            identite.ajouter_role(cnx, f.AUTH.utilisateur, 'nathan_owner')
            identite.retirer_role(cnx, f.AUTH.utilisateur, 'admin')
        return r

    monkeypatch.setattr(port, '_reception', reception)
    with session() as cnx, pytest.raises(PermissionError):
        port.lire(cnx, affaire['deps'], f.AUTH, affaire['lead'], f.DEVIS)


def test_prix_courant_et_taux_absent_restent_explicites(complet, session):
    from sqlalchemy import select, update

    port = import_module('opsys.console.rentabilite_chantier')
    with session() as cnx:
        a = port.lire(cnx, complet['deps'], f.AUTH, complet['lead'], f.DEVIS)
        condition = ((REGISTRES.c.departement == 'm06-material-control')
                     & (REGISTRES.c.registre == 'livre_prix'))
        ligne = codec.decoder(cnx.execute(select(REGISTRES.c.maillon).where(condition)).scalar_one())
        ligne['prix_unitaire'] = 16.0
        cnx.execute(update(REGISTRES).where(condition).values(maillon=codec.encoder(ligne)))
    avant = f.m.base._instantane_base(session)
    with session() as cnx:
        b = port.lire(cnx, complet['deps'], f.AUTH, complet['lead'], f.DEVIS)
    cout_b = b['chantier']['rentabilite']['cout_reel']
    assert (cout_b['cout_total'], cout_b['cout_total_connu']) == (None, '672.00')  # matériaux au nouveau prix du livre
    assert b['chantier']['trace']['a_jour'] is False and b['source_calculee'] != a['source_calculee']
    assert f.m.base._instantane_base(session) == avant
    complet['config'].write_text('configuration: {}\n')
    with session() as cnx:
        partiel = port.lire(cnx, complet['deps'], f.AUTH, complet['lead'], f.DEVIS)
    cout = partiel['chantier']['rentabilite']['cout_reel']
    assert cout['complet'] is False and cout['cout_total'] is None
    assert cout['main_d_oeuvre']['statut'] == 'non_disponible'
    assert partiel['chantier']['rentabilite']['marge_reelle'] is None


@pytest.mark.parametrize('defaut', ['role', 'expire', 'autre_devis', 'autre_lead', 'doublon',
                                   'recu', 'publication', 'quota'])
def test_sources_et_acces_negatifs_sans_reparation(affaire, session, monkeypatch, defaut):
    from dataclasses import replace

    from sqlalchemy import select, update

    from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS

    port = import_module('opsys.console.rentabilite_chantier')
    auth, lead, devis = f.AUTH, affaire['lead'], f.DEVIS
    with session() as cnx:
        if defaut == 'role':
            identite.ajouter_role(cnx, auth.utilisateur, 'nathan_owner')
            identite.retirer_role(cnx, auth.utilisateur, 'admin')
        elif defaut == 'expire':
            auth = replace(auth, expire=0)
        elif defaut == 'autre_devis':
            devis += '-ABSENT'
        elif defaut == 'autre_lead':
            lead = 'LEAD-ETRANGER-FICTIF'
        elif defaut == 'doublon':
            copie = list(stockage.maillons('m05-financecore', 'devis_recus'))[0]
            stockage.maillons('m05-financecore', 'devis_recus').append(copie)
        elif defaut == 'recu':
            cnx.execute(update(EVENEMENTS_RECUS).where(
                EVENEMENTS_RECUS.c.evenement_id == affaire['evenement'],
                EVENEMENTS_RECUS.c.consommateur == 'm05-financecore').values(
                    resultat=codec.encoder(dict(traite=True, devis_id='DEVIS-ETRANGER-FICTIF'))))
        elif defaut == 'publication':
            condition = EVENEMENTS_SORTANTS.c.evenement_id == affaire['evenement']
            charge = codec.decoder(cnx.execute(select(EVENEMENTS_SORTANTS.c.charge).where(condition)).scalar_one())
            charge['prix_total'] = '999.00'
            cnx.execute(update(EVENEMENTS_SORTANTS).where(condition).values(charge=codec.encoder(charge)))
        else:
            cnx.execute(REGISTRES.insert().values(departement='m06-material-control', registre='livre_prix',
                rang=0, maillon='x' * 8388609))
    if defaut in ('role', 'expire', 'quota'):
        monkeypatch.setattr(port, 'copier_maillons_avec_metadonnees',
            lambda *a, **k: pytest.fail('décodage avant autorité ou toutes les bornes'))
    avant = f.m.base._instantane_base(session)
    with session() as cnx, pytest.raises((PermissionError, f.port.Refus)):
        port.lire(cnx, affaire['deps'], auth, lead, devis)
    assert f.m.base._instantane_base(session) == avant


def test_m5_reponse_modifiee_refusee(complet, session, monkeypatch):
    port = import_module('opsys.console.rentabilite_chantier')
    original = port._m5

    def modifier(*args):
        r = original(*args)
        r['chantiers'][0]['rentabilite']['marge_reelle'] = '999.00'
        return r

    monkeypatch.setattr(port, '_m5', modifier)
    avant = f.m.base._instantane_base(session)
    with session() as cnx, pytest.raises(f.port.Refus, match='REPONSE-INCOHERENTE'):
        port.lire(cnx, complet['deps'], f.AUTH, complet['lead'], f.DEVIS)
    assert f.m.base._instantane_base(session) == avant


def test_vrai_t0_m5_refuse_aussi_facture_corrompue(complet, session):
    from m5_financecore import outils as m5
    from sqlalchemy import select, update

    with session() as cnx:
        condition = ((REGISTRES.c.departement == 'm05-financecore') & (REGISTRES.c.registre == 'factures'))
        ligne = codec.decoder(cnx.execute(select(REGISTRES.c.maillon).where(condition)).scalar_one())
        ligne['montant_avant_taxes'] = '999.00'
        cnx.execute(update(REGISTRES).where(condition).values(maillon=codec.encoder(ligne)))
    avant = f.m.base._instantane_base(session)
    response = b._appeler({o.nom: o for o in m5.outils()}, dict(devis_id=f.DEVIS))
    assert response['ok'] is False
    assert f.m.base._instantane_base(session) == avant
