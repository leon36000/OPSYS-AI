"""P4-04 : régressions de la relecture adverse (défauts A3, A4, A5, A6).

Repris de `tests_relecture/` (assertions conservées) et complétés par les cas voisins qui ne doivent PAS changer :
une projection mixte (créneau daté + intervention sans date) compte les deux, et la borne 480 reste acceptée.

- A3 : un plan appliqué non daté ne donne pas « évalué, 0 en retard » ; ses interventions sont dans `sans_date`.
- A4 : un calendrier civil illisible rend un verdict nommé, jamais une cédule vide « évaluée à zéro ».
- A5 : quand `retards_cedule` mesure, la clé historique `retard_sur_cedule` n'est pas servie (une seule vérité).
- A6 : la tolérance déclarée est bornée à 480 ; 481 est refusée par le calcul ET par la lecture CFG-1.

Données fictives (`fictif: true`).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml
from m4_field_ops import calendrier_civil, cedule_tournees, retards

_TESTS = Path(__file__).resolve().parent


def _charger(nom, chemin):
    spec = importlib.util.spec_from_file_location(nom, chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_aide_cedule = _charger("rev_retards_cedule", _TESTS / "test_cedule_tournees.py")
_aide_p4 = _charger("rev_retards_p4", _TESTS / "test_p4_retard_replanification.py")
_monde = _aide_cedule._monde
_reussi = _aide_cedule._reussi
_monde_date = _aide_p4._monde_date

REFERENCE = "2030-06-03T18:00:00-04:00"
HORODATAGE = "2030-01-01T00:00:00+00:00"


def _plan_applique():
    reg, ids, positions = _monde()
    plan = _reussi(_aide_cedule._proposer(reg, ids, positions))["plan_id"]
    _reussi(cedule_tournees.appliquer(reg, plan, positions, HORODATAGE, "admin.fictif"))
    return reg, ids, plan, positions


# =========================================================================================
# A3 — plan appliqué non daté : les interventions sont comptées sans_date, jamais zéro
# =========================================================================================
def test_un_plan_applique_non_date_ne_donne_pas_zero_sans_date():
    reg, ids, _plan, _positions = _plan_applique()
    lignes, sans_date = calendrier_civil._projection(calendrier_civil._index(reg))
    assert lignes == [] and len(sans_date) == len(ids), (lignes, sans_date)

    releve, verdict = retards.lire(reg, REFERENCE, tolerance_minutes=30)
    if verdict is not None:
        texte = (verdict.get("code", "") + " " + verdict.get("detail", "")).lower()
        assert "date" in texte or "calendrier" in texte, verdict
        return
    bloc = releve["retards_cedule"]
    assert bloc["sans_date"] == len(ids), (
        "les interventions d'un plan appliqué non daté ne sont comptées nulle part : "
        f"projection sans_date={len(sans_date)}, bloc={bloc}")
    assert bloc["total"] == 0 and bloc["en_retard"] == 0, bloc


def test_la_projection_sans_date_s_ajoute_aux_creneaux_non_mesurables(monkeypatch):
    # Cas voisin de A3 : un créneau daté mesurable ET une intervention que la projection range d'emblée sans date.
    # Les deux comptent une seule fois (total 1, sans_date 1) ; jeter la liste de projection donnerait sans_date 0.
    reg, _ids, _plan = _monde_date()
    ligne = {"intervention_id": "datée", "lead_id": "l", "plan_id": "p", "equipe_id": "eq-a",
             "debut": "2030-06-03T08:00:00-04:00", "fin": "2030-06-03T10:00:00-04:00",
             "statut": "planifiee", "validite": "date_confirmee", "confirme_le": HORODATAGE}
    monkeypatch.setattr(
        calendrier_civil, "_projection",
        lambda _index: ([dict(ligne)], [{"intervention_id": "sans-date", "plan_id": None,
                                         "statut": "planifiee", "raison": "aucune_date_civile_confirmee"}]))
    bloc, verdict = retards.retards_cedule(reg, REFERENCE, 30)
    assert verdict is None
    assert bloc["total"] == 1 and bloc["sans_date"] == 1, bloc


# =========================================================================================
# A4 — calendrier civil illisible : verdict, jamais un zéro évalué
# =========================================================================================
def test_un_calendrier_illisible_ne_donne_pas_un_releve_evalue_a_zero():
    reg, _ids, plan, _positions = _plan_applique()
    calendrier_civil.confirmer(reg, plan, {"0": "2030-06-03"}, 0, "admin.fictif", HORODATAGE)
    source = next(m for m in reg.lire() if m["type_entree"] == calendrier_civil.TYPE_DATEE)
    casse = {cle: valeur for cle, valeur in source.items()
             if cle not in ("ligne_id", "precedent_ligne_id")}
    casse["calendrier"] = {"0": "pas-une-date"}
    casse["revision"] = source["revision"] + 1
    reg.ajouter(casse)

    releve, verdict = retards.lire(reg, REFERENCE, tolerance_minutes=30)
    if verdict is not None:
        texte = (verdict.get("code", "") + " " + verdict.get("detail", "")).lower()
        assert "date" in texte or "calendrier" in texte, verdict
        return
    bloc = releve["retards_cedule"]
    assert not (bloc["statut"] == "evalue" and bloc["total"] == 0), (
        "un calendrier civil illisible est converti en cédule vide « évaluée » à zéro : "
        f"{bloc} (le manque MANQUE_DATE_CIVILE existe mais n'est jamais rendu)")


# =========================================================================================
# A5 — la clé historique ne contredit pas le bloc mesuré
# =========================================================================================
def test_la_cle_retard_sur_cedule_ne_contredit_pas_le_bloc_mesure():
    reg, _ids, _plan = _monde_date()
    releve, verdict = retards.lire(reg, REFERENCE, tolerance_minutes=30)
    assert verdict is None, verdict
    bloc = releve["retards_cedule"]
    assert bloc["statut"] == "evalue" and bloc["en_retard"] == 3, bloc

    historique = releve.get("retard_sur_cedule")
    assert historique is None or historique.get("statut") != "non_mesurable", (
        "le même relevé dit le retard mesuré (retards_cedule=en_retard 3) et non mesurable "
        f"(retard_sur_cedule={historique!r}) ; un lecteur de la clé historique voit un verdict faux")


def test_sans_tolerance_la_cle_historique_reste_non_mesurable():
    # Cas voisin de A5 : sans tolérance, le bloc est « non évalué » et la clé historique garde son sens.
    reg, _ids, _plan = _monde_date()
    releve, verdict = retards.lire(reg, REFERENCE)
    assert verdict is None
    assert releve["retards_cedule"]["statut"] == "non_evalue"
    assert releve["retard_sur_cedule"] == {
        "statut": "non_mesurable", "manque": retards.MANQUE_RETARD_SUR_CEDULE}


# =========================================================================================
# A6 — borne max 480 : le calcul ET la lecture refusent 481
# =========================================================================================
def test_une_tolerance_de_481_refusee_par_le_module_pur():
    reg, _ids, _plan = _monde_date()
    releve, verdict = retards.lire(reg, REFERENCE, tolerance_minutes=481)
    assert verdict is not None and verdict["code"] == "REJ-RETARD-TOLERANCE-A-DECLARER", (
        "une tolérance de 481 minutes (au-delà du max déclaré 480) est acceptée et évaluée : "
        f"relevé={None if releve is None else releve['retards_cedule']}, verdict={verdict}")


def test_une_tolerance_de_480_reste_acceptee():
    reg, _ids, _plan = _monde_date()
    releve, verdict = retards.lire(reg, REFERENCE, tolerance_minutes=480)
    assert verdict is None
    assert releve["retards_cedule"]["tolerance_minutes"] == 480
    assert retards.attente_tolerance_retard(480) is None


def test_une_tolerance_de_481_dans_le_fichier_n_est_pas_servie(tmp_path, monkeypatch):
    from m4_field_ops import outils

    manifeste = yaml.safe_load(outils._MANIFESTE.read_text(encoding="utf-8"))
    manifeste["configuration"]["retard_cedule"]["tolerance_minutes"] = 481
    chemin = tmp_path / "department.yaml"
    chemin.write_text(yaml.safe_dump(manifeste, allow_unicode=True), encoding="utf-8")
    monkeypatch.setattr(outils, "_MANIFESTE", chemin)

    lue = outils._tolerance_retard_cedule()
    assert lue is None, (
        "le lecteur sert une tolérance de 481 minutes alors que le manifeste déclare max 480 "
        f"(valeur lue : {lue!r}) ; la console la classe pourtant fichier_invalide")
