"""fictif: true — ancres métier du vrai plan avant sa toute première date."""
import importlib.util
from pathlib import Path

import pytest
from m4_field_ops import calendrier_civil, registre
from m4_field_ops.outils import outils
from sqlalchemy import update

from opsys import stockage
from opsys.stockage import codec
from opsys.stockage.schema import REGISTRES

spec = importlib.util.spec_from_file_location('premiere_date_integrite_fixture',
    Path(__file__).with_name('test_console_dates_cedule.py'))
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)
b = d.base
client_crm = d.client_crm


@pytest.fixture
def sans_date(client_crm, session):
    par_nom = {o.nom: o for o in outils()}
    ids = {}
    for i, original in enumerate(b.terrain.SCENARIO['leads'][:3]):
        lead = {**original, 'lead_id': f'premiere-date-fictive-{i}'}
        ids[lead['lead_id']] = b.terrain._inscrire(par_nom, lead)
        b.terrain._resultat(b.terrain._confirmer(par_nom, lead))
    plan_id = b.terrain._resultat(b.terrain._proposer(par_nom, ids))['plan_id']
    b.terrain._resultat(b.terrain._appliquer(par_nom, plan_id))
    b.base._connecter(client_crm, 'admin.fictif')
    assert client_crm.get('/crm/cedule/plan/' + plan_id).status_code == 200
    with session() as cnx:
        chaine = registre.Registre(stockage.maillons('m04-field-ops', 'principal'))
        assert not any(m['type_entree'] == 'cedule_datee' for m in chaine.lire())
        nouvelle = registre.Registre()
        for ligne in chaine.lire():
            if ligne['type_entree'] == 'cedule_proposee' and ligne['plan_id'] == plan_id:
                ligne['sortie']['plan'][0]['visites'][0]['fin_min'] += 1
            nouvelle.ajouter(ligne)
        nouvelle.assert_chaine()
        for rang, ligne in enumerate(nouvelle.lire()):
            cnx.execute(update(REGISTRES).where((REGISTRES.c.departement == 'm04-field-ops')
                & (REGISTRES.c.registre == 'principal') & (REGISTRES.c.rang == rang)).values(
                    maillon=codec.encoder(ligne)))
    return plan_id


def test_premiere_date_lecture_refuse_empreinte_metier_alteree(client_crm, sans_date, session):
    avant = b.base._instantane_base(session)
    page = client_crm.get('/crm/cedule/plan/' + sans_date)
    assert page.status_code == 503, page.text
    assert b.base._instantane_base(session) == avant


def test_premiere_date_confirmation_refuse_empreinte_metier_alteree(sans_date, session):
    avant = b.base._instantane_base(session)
    with session(), pytest.raises(ValueError):
        chaine = registre.Registre(stockage.maillons('m04-field-ops', 'principal'))
        calendrier_civil.confirmer(chaine, sans_date, {'0': '2030-06-03'}, 0,
                                   'admin.fictif', b.terrain.RECU_LE.isoformat())
    assert b.base._instantane_base(session) == avant


@pytest.mark.parametrize('defaut', ['proposition_dupliquee', 'application_dupliquee', 'application_avant_proposition'])
def test_ancres_uniques_et_ordonnees_sans_date(defaut):
    from m4_field_ops import cedule_tournees

    source = Path(__file__).parents[1] / 'departments/m04-field-ops/tests/test_calendrier_civil.py'
    spec_pur = importlib.util.spec_from_file_location('premiere_date_ancres_pures_fixture', source)
    pur = importlib.util.module_from_spec(spec_pur)
    spec_pur.loader.exec_module(pur)
    propre, _, plan_id = pur.monde_date()
    lignes = propre.lire()
    ip = next(i for i, m in enumerate(lignes) if m['type_entree'] == cedule_tournees.TYPE_PROPOSEE)
    ia = next(i for i, m in enumerate(lignes) if m['type_entree'] == cedule_tournees.TYPE_APPLIQUEE)
    if defaut == 'proposition_dupliquee':
        lignes.append(lignes[ip])
    elif defaut == 'application_dupliquee':
        lignes.append(lignes[ia])
    else:
        lignes[ip], lignes[ia] = lignes[ia], lignes[ip]
    faux = registre.Registre()
    for ligne in lignes:
        faux.ajouter(ligne)
    faux.assert_chaine()
    avant = faux.lire()
    for action in ('lecture', 'confirmation'):
        with pytest.raises(cedule_tournees.PreuvePlanInvalide, match='dupliqu|antérieure'):
            if action == 'lecture':
                calendrier_civil.lire_plan(faux, plan_id)
            else:
                calendrier_civil.confirmer(faux, plan_id, {'0': '2030-06-03'}, 0,
                                           'admin.fictif', pur.HORODATAGE)
    assert faux.lire() == avant
