"""M9.3 — indicateurs exécutifs : définitions officielles reliées, absences nommées, lignage sans calcul (fictif)."""

import glob
import json
from pathlib import Path

import pytest
import yaml
from m9_strategic_intelligence import capture_strategique as cs
from m9_strategic_intelligence import catalogue_producteurs as cat
from m9_strategic_intelligence import metriques_executives as me

FICTIF = True
CONNAISSANCE = "2026-10-28T13:00:00Z"
M8_METRIQUES = Path(__file__).resolve().parents[2] / "m08-analytics" / "metrics"
DEPARTEMENTS = {
    "m01-front-office", "m02-revenue-crm", "m03-estimation", "m04-field-ops", "m05-financecore",
    "m06-material-control", "m07-marketing", "m08-analytics", "m09-strategic-intelligence", "m10-memoire",
}  # fmt: skip


def _chaine(*specs):
    """specs : (lecture_id, contenu de resultat, recu_a, arguments)."""
    chaine, precedent = [], cs.HASH_INITIAL
    for index, (lecture, contenu, recu, arguments) in enumerate(specs):
        reponse = {"ok": True, "resultat": {"accepte": True, **contenu}}
        capture = cs.construire(
            cat.obtenir(lecture),
            arguments,
            [reponse],
            recu_a=recu,
            reference=None,
            index=index,
            hash_precedent=precedent,
        )
        chaine.append(capture)
        precedent = capture["hash_maillon"]
    return chaine


def _ids_m8():
    ids = set()
    for fichier in glob.glob(str(M8_METRIQUES / "*.yaml")):
        metriques = yaml.safe_load(Path(fichier).read_text(encoding="utf-8"))["metrics"]
        ids |= set(metriques) if isinstance(metriques, dict) else {m["id"] for m in metriques}
    return ids


def test_dix_sept_indicateurs_uniques_statuts_valides_et_proprietaires_connus():
    ids = [i["id"] for i in me.REGISTRE]
    assert len(ids) == 17 and len(set(ids)) == 17
    assert {i["statut_definition"] for i in me.REGISTRE} <= me.STATUTS
    assert {i["proprietaire"] for i in me.REGISTRE} <= DEPARTEMENTS
    comptes = {s: sum(1 for i in me.REGISTRE if i["statut_definition"] == s) for s in me.STATUTS}
    assert comptes == {
        "DEFINIE_M8": 4, "DEFINIE_CHEZ_LE_PROPRIETAIRE": 3, "SIGNAL_M9": 1, "A_DEFINIR_PAR_LE_PROPRIETAIRE": 9,
    }  # fmt: skip


def test_chaque_metrique_m8_reliee_existe_dans_le_dictionnaire_de_m8():
    """Garde de dérive : si M8 renomme une métrique, ce test échoue au lieu de laisser un lien mort."""
    connues = _ids_m8()
    assert len(connues) >= 20
    reliees = {m for i in me.REGISTRE for m in i["metriques_m8"]}
    assert reliees and reliees <= connues, reliees - connues


def test_lectures_sources_du_catalogue_et_regles_de_forme():
    for indicateur in me.REGISTRE:
        for lecture in indicateur["lectures_sources"]:
            cat.obtenir(lecture)  # lève si la lecture n'existe pas
        if indicateur["statut_definition"] == "A_DEFINIR_PAR_LE_PROPRIETAIRE":
            assert not indicateur["metriques_m8"] and not indicateur["lectures_sources"], indicateur["id"]
        if indicateur["statut_definition"] == "DEFINIE_M8":
            assert indicateur["metriques_m8"], indicateur["id"]
        assert indicateur["note"].strip()


def test_sans_aucune_capture_rien_n_est_suppose_ni_calcule():
    res = me.lignage([], connaissance=CONNAISSANCE)
    assert res["registre_m8_capture"] is False and len(res["indicateurs"]) == 17
    assert all(i["calcule_par_m9"] is False for i in res["indicateurs"])
    par_id = {i["id"]: i for i in res["indicateurs"]}
    assert set(par_id["gross_margin"]["metriques_m8"].values()) == {"REGISTRE_NON_CAPTURE"}
    assert par_id["gross_margin"]["lignage"] == "AUCUN_FAIT_CAPTURE" and par_id["gross_margin"]["faits"] == []
    assert (
        "faits" not in par_id["revenue"] and par_id["revenue"]["statut_definition"] == "A_DEFINIR_PAR_LE_PROPRIETAIRE"
    )
    assert res["par_statut"]["A_DEFINIR_PAR_LE_PROPRIETAIRE"] == 9 and len(res["lignage_id"]) == 64


def test_faits_cites_registre_m8_et_valeurs_nulles_de_m7_restent_nulles():
    chaine = _chaine(
        ("m8.mesures_chantier", {"trouve": True, "mesures": [
            {"metric_id": "m8_marge_reelle_cad", "valeur": "114.00"},
            {"metric_id": "m8_ecart_marge_cad", "valeur": "-6.00"},
            {"metric_id": "m8_ecart_duree_minutes", "valeur": "12"},
        ]}, "2026-10-27T12:00:00Z", {"wct_id": "W1"}),
        ("m8.definitions_metriques", {"definitions": [
            {"metric_id": "m8_marge_reelle_cad", "unite": "CAD", "version": 1},
        ], "total": 1}, "2026-10-27T12:00:01Z", {}),
        ("m7.performance_campagnes", {"resultat": {"campagnes": [
            {"campagne_id": "C1", "cout_par_lead_cad": None, "roi": None},
        ]}}, "2026-10-27T12:00:02Z", {"debut": "2026-10-01", "fin": "2026-10-27"}),
    )  # fmt: skip
    res = me.lignage(chaine, connaissance=CONNAISSANCE)
    par_id = {i["id"]: i for i in res["indicateurs"]}
    assert res["registre_m8_capture"] is True
    marge = par_id["gross_margin"]
    assert marge["metriques_m8"] == {"m8_marge_reelle_cad": "AU_REGISTRE", "m8_marge_prevue_cad": "ABSENTE_DU_REGISTRE"}
    assert {f["valeur"] for f in marge["faits"]} == {"114.00"}
    assert marge["faits"][0]["adresse"] == "m8.mesures_chantier#0:p0.resultat.mesures[0].valeur"
    profit = par_id["job_profitability"]
    assert {f["metric_id"]: f["valeur"] for f in profit["faits"]} == {
        "m8_marge_reelle_cad": "114.00", "m8_ecart_marge_cad": "-6.00",
    }  # fmt: skip
    # M7 publie null tant que l'attribution manque : la valeur reste « null », jamais zéro.
    assert [f["valeur"] for f in par_id["cost_per_lead"]["faits"]] == ["null"]
    assert par_id["cost_per_lead"]["faits"][0]["adresse"].endswith(".cout_par_lead_cad")
    assert [f["valeur"] for f in par_id["marketing_roi"]["faits"]] == ["null"]
    assert "faits" not in par_id["risk_score"] and par_id["risk_score"]["statut_definition"] == "SIGNAL_M9"


def test_capture_refusee_partielle_ou_future_ne_produit_aucun_lignage():
    avant = _chaine(
        ("m8.mesures_chantier", {"trouve": True, "mesures": [{"metric_id": "m8_marge_reelle_cad", "valeur": "1.00"}]},
         "2026-10-29T12:00:00Z", {"wct_id": "W1"}),
    )  # fmt: skip
    res = me.lignage(avant, connaissance=CONNAISSANCE)  # reçue APRÈS l'instant de connaissance
    marge = {i["id"]: i for i in res["indicateurs"]}["gross_margin"]
    assert marge["faits"] == [] and marge["lignage"] == "AUCUN_FAIT_CAPTURE"


def test_deterministe_et_aucun_flottant_dans_la_sortie():
    chaine = _chaine(
        ("m8.mesures_chantier", {"trouve": True, "mesures": [{"metric_id": "m8_marge_reelle_cad", "valeur": "114.00"}]},
         "2026-10-27T12:00:00Z", {"wct_id": "W1"}),
    )  # fmt: skip
    a, b = me.lignage(chaine, connaissance=CONNAISSANCE), me.lignage(chaine, connaissance=CONNAISSANCE)
    assert a == b and a["lignage_id"] == b["lignage_id"]
    assert "." not in "".join(c for c in json.dumps(a["par_statut"]))
    with pytest.raises(ValueError):
        me.lignage(chaine, connaissance="demain")
