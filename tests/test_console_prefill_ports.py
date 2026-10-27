"""Ports privés sur SQLite réel, données fictives; aucun parcours HTTP revendiqué."""
import importlib.util
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

import pytest

from opsys import contexte, idempotence, stockage

spec = importlib.util.spec_from_file_location(
    'fixture_prefill', Path(__file__).with_name('test_console_modeles_soumission.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
client_crm = m.client_crm
catalogue = m.catalogue
FICTIF = True


def appel(session, nom, args, *, cle='prefill-fictif', quota=65536, origine='console'):
    from m3_estimation import outils

    now = datetime(2030, 6, 1, tzinfo=UTC)
    meta = idempotence.Meta(cle, 'console:admin.fictif', now.isoformat())
    with (session(), contexte.appele_par_appareil(contexte.IdentiteAppelante('admin.fictif', 'admin', source=origine)),
          contexte.appeler_en_tant_que('m03-estimation', origine=origine), contexte.sortie_bornee(quota),
          outils.contexte_modeles(meta), contexte.receptionne_de(contexte.HorodatageAppareil(meta.appareil, now, now))):
        return getattr(outils, nom)(**args)


def prix(session, valeur=12.5):
    from m6_material_control.livre_prix import enregistrer_prix

    with session():
        _, refus = enregistrer_prix('mat-fictif', 'fourn-fictif', valeur, 'CAD', '2026-01-01',
                                    stockage.maillons('m06-material-control', 'livre_prix'),
                                    source_document='prix-fictif.pdf', unite='pi')
        assert refus is None


def preparer(session):
    from m6_material_control.fournisseurs import enregistrer_fournisseur

    r = m.direct(session)
    assert r['accepte'], r
    modele = r['resultat']
    ancre = dict(modele_id=modele['modele_id'], modele_revision=modele['revision'], modele_source=modele['source_id'])
    lignes = [dict(ligne_id='ligne-fictive', description='Pose FICTIVE', materiau_id='mat-fictif', unite='pi')]
    enregistrement = appel(session, 'enregistrer_lignes_modele',
                           dict(**ancre, lignes=lignes, revision_attendue=0), cle='lignes-fictives')
    assert enregistrement['accepte'], enregistrement
    with session():
        _, refus = enregistrer_fournisseur('fourn-fictif', 'Fournisseur FICTIF', '2026-01-01T00:00:00+00:00',
                                           stockage.maillons('m06-material-control', 'fournisseurs'))
        assert refus is None
    prix(session)
    tarif = appel(session, 'lire_tarif_modele',
                  dict(materiau_id='mat-fictif', fournisseur_id='fourn-fictif', unite='pi'))
    assert tarif['accepte'], tarif
    t = tarif['resultat']
    jeu = enregistrement['resultat']
    return dict(**ancre, devis_id='devis-prefill-fictif', lead_id='lead-fictif-001', chantier_id=None,
                taux_marge='0.2', lignes_revision=jeu['revision'], lignes_source=jeu['source_id'],
                selections=[dict(ligne_modele_id='ligne-fictive', quantite='2', fournisseur_id='fourn-fictif',
                                 tarif_rang=t['tarif_rang'], tarif_empreinte=t['tarif_empreinte'])])


def test_devis_sql_sources_rejeu_et_reouverture(catalogue, session):
    from m3_estimation import devis_durable, outils

    p = preparer(session)
    r = appel(session, 'creer_devis_prefill', p)
    assert r['accepte'], r
    prix(session, 15)
    avant = m.base._instantane_base(session)
    assert appel(session, 'creer_devis_prefill', p) == r
    assert m.base._instantane_base(session) == avant
    stockage.liberer()
    with session():
        d, v = devis_durable.lire_devis(outils.registre_devis_production(), p['devis_id'])
        assert v is None and str(d['prix_total']) == '30.00'
        assert d['provenance_tarifs']['tarifs'][0]['cout_unitaire_decimal'] == '12.5'
        assert d['provenance_tarifs']['lignes_source'] == p['lignes_source']
    assert '12.5' not in repr(r)


@pytest.mark.parametrize('cas', ['prix_change', 'source', 'doublon', 'quantite',
                                 'cout_injecte', 'fournisseur', 'ligne', 'lead', 'quota', 'origine'])
def test_refus_sans_effet(catalogue, session, cas):
    p = preparer(session)
    kw = {}
    if cas == 'prix_change':
        prix(session, 13)
    elif cas == 'source':
        p['lignes_source'] = '0' * 64
    elif cas == 'doublon':
        p['selections'] *= 2
    elif cas == 'quantite':
        p['selections'][0]['quantite'] = '0'
    elif cas == 'cout_injecte':
        p['selections'][0]['cout_unitaire'] = '0.01'
    elif cas == 'fournisseur':
        p['selections'][0]['fournisseur_id'] = 'inconnu'
    elif cas == 'ligne':
        p['selections'][0]['ligne_modele_id'] = 'inconnue'
    elif cas == 'lead':
        p['lead_id'] = 'inconnu'
    elif cas == 'quota':
        kw['quota'] = 8
    else:
        kw['origine'] = 'm03-estimation'
    avant = m.base._instantane_base(session)
    assert appel(session, 'creer_devis_prefill', p, **kw)['accepte'] is False
    assert m.base._instantane_base(session) == avant


def test_audit_atomique_et_intention_non_reutilisable(catalogue, session, monkeypatch):
    from opsys import etat

    p = preparer(session)
    avant = m.base._instantane_base(session)
    with monkeypatch.context() as mp:
        def panne(*args, **kwargs):
            raise RuntimeError('audit fictif')
        mp.setattr(etat, 'journaliser', panne)
        with pytest.raises(RuntimeError, match='audit fictif'):
            appel(session, 'creer_devis_prefill', p)
    assert m.base._instantane_base(session) == avant
    assert appel(session, 'creer_devis_prefill', p)['accepte']
    avant = m.base._instantane_base(session)
    q = deepcopy(p)
    q['selections'][0]['quantite'] = '3'
    assert appel(session, 'creer_devis_prefill', q)['accepte'] is False
    assert m.base._instantane_base(session) == avant


def test_ports_generiques_fermes(session):
    from opsys.capacites import Capacites

    cap = Capacites({}, cnx_factory=session)
    for nom in ('m3_enregistrer_lignes_modele', 'm3_lire_lignes_modele',
                'm3_lire_tarif_modele', 'm3_creer_devis_prefill'):
        assert cap.appeler(nom, {}) == {'ok': False, 'erreur': 'port_console_prive_requis'}


def test_acceptation_transmet_le_materiau_au_consommateur_m6(catalogue, session):
    from m3_estimation import devis_durable, outils
    from m6_material_control import outils as m6

    p = preparer(session)
    assert appel(session, 'creer_devis_prefill', p)['accepte']
    with session():
        d, v = devis_durable.marquer_devis_accepte(p['devis_id'], 'client.fictif',
                                                  '2030-06-02T00:00:00+00:00', outils.registre_devis_production())
        assert v is None
        charge = devis_durable.charge_evenement_devis_accepte(d)
        assert charge['lignes'][0]['reference_besoin_materiau'] == 'mat-fictif'
        assert 'provenance_tarifs' not in charge
        r = m6._recevoir_devis_accepte(charge)
        assert r['reservation']['statut'] == 'creee', r
        assert 'mat-fictif' in repr(r) and 'a_commander' in repr(r), r
    avant = m.base._instantane_base(session)
    with session():
        m6._recevoir_devis_accepte(charge)
    assert m.base._instantane_base(session) == avant


def test_dispatch_console_et_revocation_sur_rejeu(catalogue, session):
    from opsys import departements, identite
    from opsys.console import metier
    from opsys.console.securite import Session

    p = preparer(session)
    deps = departements.charger_departements()
    auth = Session('admin.fictif', frozenset({'admin'}), 'csrf-fictif', 4102444800)
    with session() as cnx:
        r = metier.executer(cnx, deps, auth, 'm3_lire_tarif_modele',
                            dict(materiau_id='mat-fictif', fournisseur_id='fourn-fictif', unite='pi'))
        assert r['ok'] and r['resultat']['accepte'], r
        r = metier.executer(cnx, deps, auth, 'm3_creer_devis_prefill', p, mutation_id='dispatch-fictif')
        assert r['ok'] and r['resultat']['accepte'], r
    with session() as cnx:
        identite.retirer_role(cnx, 'admin.fictif', 'admin')
    avant = m.base._instantane_base(session)
    with session() as cnx, pytest.raises(PermissionError):
        metier.executer(cnx, deps, auth, 'm3_creer_devis_prefill', p, mutation_id='dispatch-fictif')
    assert appel(session, 'creer_devis_prefill', p, cle='dispatch-fictif')['accepte'] is False
    assert m.base._instantane_base(session) == avant
