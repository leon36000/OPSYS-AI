"""Jonction privée QA sur faits et registres fictifs, sans facturation finale."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest
from m4_field_ops import outbox
from m4_field_ops.registre import Registre
from m5_financecore import outils

from opsys import evenements, stockage
from opsys.console import rentabilite_chantier as console
from opsys.departements import charger_departements

ROOT = Path(__file__).resolve().parents[1]
if not (ROOT / 'departments/m04-field-ops/tests/test_temps_certifies_v2.py').exists():
    pytest.skip('producteur M4 V2 non intégré à cette branche ; composition QA requise', allow_module_level=True)
spec_conftest = importlib.util.spec_from_file_location(
    'qa_m4_conftest', ROOT / 'departments/m04-field-ops/tests/conftest.py')
conftest = importlib.util.module_from_spec(spec_conftest)
spec_conftest.loader.exec_module(conftest)
base_durable = conftest.base_durable
sockets_bloques = conftest.sockets_bloques
spec = importlib.util.spec_from_file_location(
    'qa_m4_producteur', ROOT / 'departments/m04-field-ops/tests/test_temps_certifies_v2.py')
producteur = importlib.util.module_from_spec(spec)
spec.loader.exec_module(producteur)
chantier_termine = producteur.chantier_termine


def _pieces(cas):
    with stockage.transaction(cas['url']):
        principal = Registre(stockage.maillons('m04-field-ops', 'principal'))
        wct = next(m[outbox.CLE_WCT] for m in principal.lire()
                   if m.get(outbox.CLE_WCT, {}).get('wct_id') == cas['wct_id'])
        evenements.publier('m4.travaux_termines', 'm04-field-ops', wct, evenement_id=wct['wct_id'])
    deps = charger_departements()
    resume = evenements.repartir({'m05-financecore': deps['m05-financecore']},
                                 maintenant='2030-06-07T18:00:00-04:00')
    assert resume['traites'] == 1 and resume['echecs'] == 0
    with stockage.transaction(cas['url']):
        recu = next(m for m in stockage.maillons('m05-financecore', 'wct_recus') if m['wct_id'] == cas['wct_id'])
    return recu



def _ventilation(cnx, session, recu):
    charge = console.lecture._publication(cnx, recu["wct_id"], "m4.travaux_termines", "m04-field-ops")
    return console._ventilation_m4(cnx, session, recu, charge["lead_id"])


def test_projection_reelle_sans_imputation_ni_divulgation(chantier_termine, sockets_bloques):
    cas = chantier_termine
    recu = _pieces(cas)
    with stockage.transaction(cas['url']) as cnx:
        principal = Registre(stockage.maillons('m04-field-ops', 'principal'))
        _, erreur = outbox.confirmer_verification(cas['iid'], '2030-06-07T13:03:00-04:00', principal,
                                                 evenement_id_variance='variance-fictive')
        assert erreur is None
        session = SimpleNamespace(utilisateur='admin.fictif', expire=4102444800)
        resultat = _ventilation(cnx, session, recu)
        assert resultat['statut'] == 'INCOMPLET'
        assert resultat['minutes_travail'] == 390 and resultat['cout_main_oeuvre'] is None
        assert resultat['equipes_indeterminees'] == 2
        assert 'composition_declaree' not in str(resultat) and 'membres' not in str(resultat)


def test_wct_divergent_ou_recu_ancien_refuse(chantier_termine):
    cas = chantier_termine
    recu = _pieces(cas)
    with stockage.transaction(cas['url']) as cnx:
        session = SimpleNamespace(utilisateur='admin.fictif', expire=4102444800)
        with pytest.raises(console.lecture.Refus):
            _ventilation(cnx, session, {**recu, 'empreinte_charge': 'f' * 64})
        ancien = {k: v for k, v in recu.items() if k != 'empreinte_charge'}
        assert _ventilation(cnx, session, ancien)['statut'] == 'RECU_HISTORIQUE_NON_VERIFIABLE'


def test_tarifs_modifies_avant_sortie_refuses(chantier_termine, monkeypatch):
    cas = chantier_termine
    recu = _pieces(cas)
    original = outils._lire_tarifs_equipes
    appels = []
    def interposer():
        snapshot = original()
        appels.append(1)
        return snapshot if len(appels) == 1 else {**snapshot, 'source': 'f' * 64}
    monkeypatch.setattr(outils, '_lire_tarifs_equipes', interposer)
    with stockage.transaction(cas['url']) as cnx, pytest.raises(console.lecture.Refus) as erreur:
        _ventilation(cnx, SimpleNamespace(utilisateur='admin.fictif', expire=4102444800), recu)
    assert erreur.value.code == 'SOURCE-MODIFIEE'


def test_recu_bus_traite_mais_wct_different_est_refuse(chantier_termine):
    from sqlalchemy import update

    from opsys.stockage import codec
    from opsys.stockage.schema import EVENEMENTS_RECUS

    cas = chantier_termine
    recu = _pieces(cas)
    with stockage.transaction(cas['url']) as cnx:
        cnx.execute(update(EVENEMENTS_RECUS).where(EVENEMENTS_RECUS.c.evenement_id == cas['wct_id']).values(
            resultat=codec.encoder({'traite': True, 'wct_id': 'autre-fictif', 'statut': 'wct_sans_devis_id'})))
        with pytest.raises(console.lecture.Refus):
            _ventilation(cnx, SimpleNamespace(utilisateur='admin.fictif', expire=4102444800), recu)


def test_instance_modifiee_apres_capture_tarifs_refusee(chantier_termine, monkeypatch):
    from sqlalchemy import update

    from opsys.stockage.schema import OPSYS_INSTANCE

    cas = chantier_termine
    recu = _pieces(cas)
    original = outils._lire_tarifs_equipes
    def modifier_instance():
        snapshot = original()
        stockage.connexion_courante().execute(update(OPSYS_INSTANCE).where(OPSYS_INSTANCE.c.id == 1)
                                             .values(instance_id='instance-fictive-modifiee'))
        return snapshot
    monkeypatch.setattr(outils, '_lire_tarifs_equipes', modifier_instance)
    with stockage.transaction(cas['url']) as cnx, pytest.raises(console.lecture.Refus):
        _ventilation(cnx, SimpleNamespace(utilisateur='admin.fictif', expire=4102444800), recu)


def test_role_admin_revoque_refuse_avant_divulgation(chantier_termine):
    from opsys import identite

    cas = chantier_termine
    recu = _pieces(cas)
    with stockage.transaction(cas['url']) as cnx:
        identite.retirer_role(cnx, 'admin.fictif', 'admin')
        with pytest.raises(PermissionError):
            _ventilation(cnx, SimpleNamespace(utilisateur='admin.fictif', expire=4102444800), recu)


def test_producteur_non_installe_donne_un_statut_explicite(chantier_termine, monkeypatch):
    cas = chantier_termine
    recu = _pieces(cas)
    def absent(nom):
        raise ModuleNotFoundError(name=nom)
    monkeypatch.setattr(console.importlib, 'import_module', absent)
    with stockage.transaction(cas['url']) as cnx:
        vue = _ventilation(cnx, SimpleNamespace(utilisateur='admin.fictif', expire=4102444800), recu)
    assert vue == {'statut': 'PRODUCTEUR_INDISPONIBLE'}


def test_projection_falsifiee_identique_aux_deux_lectures_ne_divulgue_rien(chantier_termine, monkeypatch):
    from m4_field_ops import temps_certifies_v2

    cas = chantier_termine
    recu = _pieces(cas)
    original = temps_certifies_v2.projeter
    def projection_falsifiee(*args, **kwargs):
        resultat = original(*args, **kwargs)
        resultat['projection']['totaux']['travail'] = 999
        return resultat
    monkeypatch.setattr(temps_certifies_v2, 'projeter', projection_falsifiee)
    with stockage.transaction(cas['url']) as cnx, pytest.raises(console.lecture.Refus):
        _ventilation(cnx, SimpleNamespace(utilisateur='admin.fictif', expire=4102444800), recu)


def test_lead_wct_different_de_l_ancre_refuse(chantier_termine):
    cas = chantier_termine
    recu = _pieces(cas)
    with stockage.transaction(cas['url']) as cnx, pytest.raises(console.lecture.Refus):
        console._ventilation_m4(cnx, SimpleNamespace(utilisateur='admin.fictif', expire=4102444800),
                                recu, 'lead-autre-fictif')


def test_lead_projection_meme_recalcule_ne_peut_diverger_du_wct(chantier_termine, monkeypatch):
    from m4_field_ops import encodage, temps_certifies_v2

    cas = chantier_termine
    recu = _pieces(cas)
    original = temps_certifies_v2.projeter
    def projection_autre_lead(*args, **kwargs):
        resultat = original(*args, **kwargs)
        p = resultat['projection']
        p['lead_id'] = 'lead-autre-fictif'
        p['empreinte'] = encodage.empreinte('m4.temps_certifies.v2', {k: v for k, v in p.items() if k != 'empreinte'})
        return resultat
    monkeypatch.setattr(temps_certifies_v2, 'projeter', projection_autre_lead)
    with stockage.transaction(cas['url']) as cnx, pytest.raises(console.lecture.Refus):
        _ventilation(cnx, SimpleNamespace(utilisateur='admin.fictif', expire=4102444800), recu)


def test_port_v3_proprietaire_est_relu_pour_faits_historiques(chantier_termine, monkeypatch):
    """Une ancienne visite reste indéterminée même lorsque V3 est disponible."""
    from m4_field_ops import temps_certifies_v3

    appels = []
    original = temps_certifies_v3.projeter

    def noter(*args, **kwargs):
        appels.append(kwargs.get('source_attendue'))
        return original(*args, **kwargs)

    monkeypatch.setattr(temps_certifies_v3, 'projeter', noter)
    cas = chantier_termine
    recu = _pieces(cas)
    with stockage.transaction(cas['url']) as cnx:
        resultat = _ventilation(cnx, SimpleNamespace(utilisateur='admin.fictif', expire=4102444800), recu)
    assert resultat['statut'] == 'INCOMPLET' and resultat['equipes_indeterminees'] == 2
    assert len(appels) == 2 and appels[0] is None and isinstance(appels[1], str)
