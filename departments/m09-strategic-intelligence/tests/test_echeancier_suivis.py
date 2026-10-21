"""Échéancier de suivis fictifs : bus M8/SQLite/approbations réels, lecture sans effet."""

from __future__ import annotations

import copy
import importlib
import importlib.util
import json
from datetime import datetime
from pathlib import Path

import pytest

from opsys import contexte, identite, stockage

_spec = importlib.util.spec_from_file_location(
    "_echeancier_cloture_base", Path(__file__).with_name("test_cloture_suivi_decisions.py")
)
h = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(h)
b = h.b
installation = h.installation
NOM = "m9_lister_suivis_decision"
REFERENCE = "2026-10-20T13:00:00+00:00"
DATES = ["2026-10-20T14:00:00+00:00", "2026-10-20T08:59:00-04:00", "2026-10-20T09:00:00-04:00"]


def _preparer(installation, nombre=3):
    cap, arguments, ident, alerte = b._proposer(installation, echeance=DATES[0])
    assert b._decider(cap, ident, "ouvrir-echeancier-" + ident)["resultat"]["resultat"]["statut"] == "executee"
    ids = [ident]
    for i in range(1, nombre):
        prop = cap.appeler(
            b.OUVRIR, arguments | {"action": "Revue fictive de durée " + str(i), "echeance": DATES[i % len(DATES)]}
        )
        assert prop["statut"] == "en_attente_approbation", prop
        ident = prop["demande_id"]
        assert b._decider(cap, ident, "ouvrir-echeancier-" + ident)["resultat"]["resultat"]["statut"] == "executee"
        ids.append(ident)
    return cap, ids, alerte


def _lire(cap, **args):
    assert NOM in cap.index, "M9_ECHEANCIER_CAPACITE_ABSENTE"
    return b._lire(cap, NOM, {"horodatage_reference": REFERENCE} | args)


def _clore(cap, ident, alerte):
    prep = b._lire(cap, h.PREPARER, {"suivi_id": ident, "evenement_id": alerte["evenement_id"]})
    prop = cap.appeler(
        h.CLORE,
        {
            "suivi_id": ident,
            "evenement_id": alerte["evenement_id"],
            "empreinte_suivi": prep["empreinte_suivi"],
            "empreinte_preuve": prep["preuve"]["empreinte_source"],
            "bilan": "Revue humaine fictive, aucun effet terrain attesté.",
        },
    )
    assert prop["statut"] == "en_attente_approbation", prop
    assert (
        b._decider(cap, prop["demande_id"], "clore-echeancier-" + ident)["resultat"]["resultat"]["statut"] == "executee"
    )


def _pure(plans, clotures=(), **args):
    module = importlib.import_module("m9_strategic_intelligence.echeancier_suivis")
    return module.lister_suivis_decision(
        plans,
        list(clotures),
        args.pop("horodatage_reference", REFERENCE),
        budget_caracteres=args.pop("budget_caracteres", 6000),
        **args,
    )


def _taille(obj):
    return len(json.dumps(obj, ensure_ascii=False, allow_nan=False))


def test_echeancier_natif_ordonne_et_source_sans_effet_puis_reouverture(installation):
    cap, ids, _ = _preparer(installation)
    page = _lire(cap)
    assert page["type"] == "SUIVIS_DECISION_OUVERTS" and page["horodatage_reference"] == REFERENCE
    assert page["total"] == 3 and page["depart"] == 0
    assert len(page["vue"]) == 64 and int(page["vue"], 16) >= 0
    lignes = page["suivis"]
    while page["prochain_depart"] is not None:
        page = _lire(cap, depart=page["prochain_depart"], vue_attendue=page["vue"])
        lignes += page["suivis"]
    plans = b._suivis()
    attendus = sorted(plans, key=lambda p: (datetime.fromisoformat(p["echeance"]), p["suivi_id"]))
    assert [r["suivi"] for r in lignes] == attendus
    assert {r["suivi"]["suivi_id"] for r in lignes} == set(ids)
    assert [r["statut_echeance"] for r in lignes] == ["EN_RETARD", "A_ECHEANCE", "A_VENIR"]
    assert all(r["empreinte_suivi"] == b.empreinte(r["suivi"]) for r in lignes)
    assert all(r["suivi"]["source"] in [p["source"] for p in plans] for r in lignes)
    stockage.liberer()
    assert _lire(b._capacites(installation)) == _lire(cap)


def test_cloture_revue_humaine_exclue_sans_alterer_plan(installation):
    cap, ids, alerte = _preparer(installation, 1)
    _clore(cap, ids[0], alerte)
    avant = b._tables()
    page = _lire(cap)
    assert page["total"] == page["affichees"] == page["reste"] == 0
    assert page["suivis"] == [] and page["prochain_depart"] is None
    assert b._tables() == avant and b._suivis()[0]["suivi_id"] == ids[0]


def test_pagination_pure_bornee_complete_et_identite_de_vue(installation):
    _preparer(installation, 1)
    base = b._suivis()[0]
    plans = []
    for i in range(8):
        p = copy.deepcopy(base)
        p["suivi_id"] = "suivi-fictif-" + str(i)
        p["decision"]["demande_id"] = p["suivi_id"]
        p["echeance"] = DATES[i % 3]
        plans.append(p)
    avant = copy.deepcopy(plans)
    page = _pure(plans, budget_caracteres=3800)
    assert 0 < page["affichees"] < 8 and page["total"] == 8
    vue = page["vue"]
    tous = []
    while True:
        assert _taille(page) <= 3800 and page["vue"] == vue
        assert page["affichees"] == len(page["suivis"])
        assert page["reste"] == 8 - page["depart"] - page["affichees"]
        tous.extend(r["suivi"]["suivi_id"] for r in page["suivis"])
        if page["prochain_depart"] is None:
            break
        assert page["prochain_depart"] == page["depart"] + page["affichees"]
        page = _pure(plans, depart=page["prochain_depart"], vue_attendue=vue, budget_caracteres=3800)
    assert len(tous) == len(set(tous)) == 8 and plans == avant
    dernier = _pure(plans, depart=8, vue_attendue=vue, budget_caracteres=3800)
    assert dernier["suivis"] == [] and dernier["prochain_depart"] is None
    with pytest.raises(ValueError):
        _pure(plans, budget_caracteres=1)
    with pytest.raises(ValueError):
        _pure([], budget_caracteres=1)
    with pytest.raises(ValueError):
        _pure(plans, depart=1)
    with pytest.raises(ValueError):
        _pure(plans, depart=1, vue_attendue="0" * 64)
    modifies = copy.deepcopy(plans)
    modifies[-1]["action"] = "Autre action fictive sans changement du total"
    with pytest.raises(ValueError):
        _pure(modifies, depart=1, vue_attendue=vue)
    with pytest.raises(ValueError):
        _pure(plans, depart=1, vue_attendue=vue, horodatage_reference="2026-10-20T14:00:00+00:00")


def test_cloture_intervenue_invalide_reprise_native_sans_ecriture(installation, monkeypatch):
    cap, ids, alerte = _preparer(installation, 4)
    module = importlib.import_module("m9_strategic_intelligence.outils")
    monkeypatch.setattr(module, "BUDGET_SORTIE", 3800)
    page = _lire(cap)
    assert page["prochain_depart"] is not None
    _clore(cap, ids[-1], alerte)
    avant = b._tables()
    with contexte.appele_par_appareil(b.PROPRIO):
        reponse = cap.appeler(
            NOM, {"horodatage_reference": REFERENCE, "depart": page["prochain_depart"], "vue_attendue": page["vue"]}
        )
    assert reponse.get("ok") is False, reponse
    assert b._tables() == avant
    assert _lire(cap)["total"] == 3


def test_admin_sql_courant_et_employe_refuses_sur_capacites_conservees(installation):
    cap, _, _ = _preparer(installation, 1)
    assert _lire(cap)["total"] == 1
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, b.PROPRIO.personne, "admin")
    avant = b._tables()
    for qui in [
        b.PROPRIO,
        contexte.IdentiteAppelante(b.RESPONSABLE, "admin"),
        contexte.IdentiteAppelante(b.RESPONSABLE, "employee"),
    ]:
        with contexte.appele_par_appareil(qui):
            resultat = cap.appeler(NOM, {"horodatage_reference": REFERENCE})
        assert resultat.get("ok") is False, resultat
    assert b._tables() == avant


@pytest.mark.parametrize(
    "args",
    [
        {"horodatage_reference": "2026-10-20"},
        {"horodatage_reference": "2026-10-20T13:00:00"},
        {"horodatage_reference": "illisible"},
        {"depart": True},
        {"depart": -1},
        {"depart": 2},
        {"budget_caracteres": True},
        {"budget_caracteres": 0},
        {"vue_attendue": "pas-une-empreinte"},
    ],
)
def test_arguments_refuses_sans_mutation(installation, args):
    _preparer(installation, 1)
    plans = b._suivis()
    avant = copy.deepcopy(plans)
    with pytest.raises(ValueError):
        _pure(plans, **args)
    assert plans == avant


@pytest.mark.parametrize(
    "cause",
    [
        "double_plan",
        "date_naive",
        "schema_plan",
        "double_cloture",
        "empreinte_cloture",
        "statut_cloture",
        "cloture_orpheline",
        "schema_cloture",
        "date_naive_cloturee",
        "schema_plan_booleen",
        "schema_cloture_booleen",
    ],
)
def test_etat_incoherent_refuse_sans_mutation(installation, cause):
    _preparer(installation, 1)
    plans = b._suivis()
    clotures = []
    if cause == "double_plan":
        plans.append(copy.deepcopy(plans[0]))
    elif cause == "date_naive":
        plans[0]["echeance"] = "2026-10-20T13:00:00"
    elif cause in {"schema_plan", "schema_plan_booleen"}:
        plans[0]["schema"] = True if cause == "schema_plan_booleen" else 99
    else:
        if cause == "date_naive_cloturee":
            plans[0]["echeance"] = "2026-10-20T13:00:00"
        c = {
            "schema": 1,
            "suivi_id": plans[0]["suivi_id"],
            "statut": "cloturee_par_revue_humaine",
            "empreinte_suivi": b.empreinte(plans[0]),
        }
        if cause in {"schema_cloture", "schema_cloture_booleen"}:
            c["schema"] = True if cause == "schema_cloture_booleen" else 99
        elif cause == "empreinte_cloture":
            c["empreinte_suivi"] = "0" * 64
        elif cause == "statut_cloture":
            c["statut"] = "executee_sur_terrain"
        elif cause == "cloture_orpheline":
            c["suivi_id"] = "suivi-fictif-inconnu"
        clotures = [c, copy.deepcopy(c)] if cause == "double_cloture" else [c]
    avant = copy.deepcopy((plans, clotures))
    with pytest.raises(ValueError):
        _pure(plans, clotures)
    assert (plans, clotures) == avant


@pytest.mark.parametrize("registre", ["suivi_decisions", "clotures_suivi_decisions"])
def test_registre_non_objet_refuse_en_natif_sans_normalisation(installation, registre):
    from sqlalchemy import update

    from opsys.stockage import codec
    from opsys.stockage.schema import REGISTRES

    cap, ids, alerte = _preparer(installation, 1)
    if registre == "clotures_suivi_decisions":
        _clore(cap, ids[0], alerte)
    with stockage.transaction():
        [plan] = list(stockage.maillons(b.DEPARTEMENT, registre))
    # JSON valide mais tableau de paires, jamais un objet de suivi : aucune coercition dict(...).
    with stockage.transaction() as cnx:
        cnx.execute(
            update(REGISTRES)
            .where(REGISTRES.c.departement == b.DEPARTEMENT, REGISTRES.c.registre == registre)
            .values(maillon=codec.encoder(list(plan.items())))
        )
    avant = b._tables()
    with contexte.appele_par_appareil(b.PROPRIO):
        reponse = cap.appeler(NOM, {"horodatage_reference": REFERENCE})
    assert reponse.get("ok") is False, reponse
    assert b._tables() == avant
