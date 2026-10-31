"""M9.6–7 — vingt sections de direction : faits cités, manques nommés, rien de fabriqué, figé en fin de période."""

import json

import pytest
from m9_strategic_intelligence import capture_strategique as cs
from m9_strategic_intelligence import catalogue_producteurs as cat
from m9_strategic_intelligence import rapport_direction as rd
from m9_strategic_intelligence import revue_periodique as rp

FICTIF = True
PERIODE = rp.bornes("hebdomadaire", "2026-10-21", "America/Toronto")  # 19 → 26 octobre, fin 2026-10-26T04:00Z
DANS = "2026-10-22T12:00:00Z"
APRES = "2026-10-27T12:00:00Z"


def _env(contenu):
    return {"ok": True, "resultat": {"accepte": True, "resultat": contenu}}


def _chaine(*specs):
    chaine, precedent = [], cs.HASH_INITIAL
    for index, (lecture, reponse, recu, arguments) in enumerate(specs):
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


def _monde(recu=DANS):
    tresorerie = _env(
        {
            "type": "PREVISION_TRESORERIE", "calculable": True, "alerte": {"statut": "ALERTE"},
            "premiere_semaine_en_deficit": 3, "horizon_semaines": 13, "semaines": [], "prochain_depart": None,
            "reserves": ["r1"], "prevision_id": "p1",
        }
    )  # fmt: skip
    return _chaine(
        ("m5.prevision_tresorerie", tresorerie, recu, {"aujourd_hui": "2026-10-22"}),
        ("m6.disponibilite", _env({"articles": [], "tronque": False, "reservations_actives": [
            {"devis_id": "D1", "chantier_id": "C1", "statut": "a_commander", "lignes_manquantes": []}]}), recu, {}),
        ("m4.retards_incidents", _env({
            "reports": {"liste": [], "reste": 0},
            "incidents": {"liste": [{"demande_id": "R1", "bloquee": True, "depuis": DANS}], "reste": 0}}),
         recu, {"horodatage_reference": DANS}),
        ("m8.mesures_chantier", {"ok": True, "resultat": {"trouve": True, "mesures": [
            {"metric_id": "m8_marge_reelle_cad", "valeur": "114.00"},
            {"metric_id": "m8_ecart_marge_cad", "valeur": "-6.00"}]}}, recu, {"wct_id": "W1"}),
    )  # fmt: skip


def _sections(captures, **registres):
    return rd.sections(captures=captures, sessions=[], periode=PERIODE, **registres)


def test_vingt_sections_dans_l_ordre_meme_sans_aucune_donnee_et_rien_n_est_invente():
    res = _sections([])
    assert res["ids"] == [i for i, _ in rd.SECTIONS] and len(res["ids"]) == 20
    s = res["sections"]
    assert all(v["statut"] in rd.STATUTS and v["titre"] for v in s.values())
    non_resume = [v for k, v in s.items() if k != "resume"]
    assert all(v["manques"] for v in non_resume), "sans donnée, chaque section dit ce qui manque"
    assert s["resume"]["statut"] == "RENSEIGNEE" and s["resume"]["contenu"]["plans"] == 0
    assert len(s["resume"]["contenu"]["lectures_attendues_non_presentes"]) >= 10
    assert "faits" not in json.dumps(s["revenus_cash_marge"]["contenu"]["indicateurs"][0]).replace('"faits": []', "")


def test_faits_des_proprietaires_cites_risques_et_domaines_rattaches_a_leur_section():
    s = _sections(_monde())["sections"]
    marge = {i["id"]: i for i in s["revenus_cash_marge"]["contenu"]["indicateurs"]}
    assert marge["gross_margin"]["lignage"] == "FAITS_CITES"
    assert {f["valeur"] for f in marge["gross_margin"]["faits"]} == {"114.00"}
    assert marge["revenue"]["statut_definition"] == "A_DEFINIR_PAR_LE_PROPRIETAIRE" and marge["revenue"]["faits"] == []
    assert (
        s["revenus_cash_marge"]["statut"] == "PARTIELLE"
    )  # des faits cités, mais des définitions et lectures manquent
    assert any(r["regle"] == "cash_alerte_seuil" for r in s["revenus_cash_marge"]["contenu"]["risques_signales"])
    assert any(
        r["regle"] == "qualite_ecart_marge_negatif" for r in s["revenus_cash_marge"]["contenu"]["risques_signales"]
    )
    assert [r["regle"] for r in s["production_cedule"]["contenu"]["risques_signales"]] == ["capacite_incident_ouvert"]
    assert [r["regle"] for r in s["inventaire_fournisseurs"]["contenu"]["risques_signales"]] == [
        "materiaux_reservation_incomplete"
    ]
    risques = s["risques"]
    assert risques["statut"] == "RENSEIGNEE" and risques["contenu"]["presents"] >= 4
    assert risques["contenu"]["origine_etablie"] is False and risques["contenu"]["grille"].startswith(
        "PROPOSEE_NON_VALIDEE"
    )
    assert all(p["preuve"].count("#") == 1 for p in risques["contenu"]["premiers"])
    assert s["production_cedule"]["statut"] in ("PARTIELLE", "RENSEIGNEE")


def test_previsions_a_4_et_13_semaines_sont_celles_de_m5_citees_et_les_autres_domaines_nommes():
    s = _sections(_monde())["sections"]
    for identifiant in ("previsions_4_semaines", "previsions_13_semaines"):
        section = s[identifiant]
        assert section["statut"] == "RENSEIGNEE"
        assert section["contenu"]["tresorerie_m5"]["faits"]["horizon_semaines"].startswith("m5.prevision_tresorerie#")
        assert section["contenu"]["tresorerie_m5"]["incertitude"]["chiffree"] is False
        assert {d["domaine"] for d in section["contenu"]["autres_domaines"]} == {"leads", "capacite", "materiaux"}
        assert "pas une prévision de propriétaire" in section["contenu"]["tendances"]
    court = _chaine(
        ("m5.prevision_tresorerie", _env({"calculable": True, "alerte": {"statut": "OK"}, "horizon_semaines": 8,
                                           "semaines": [], "prevision_id": "p"}), DANS, {"aujourd_hui": "2026-10-22"}),
    )  # fmt: skip
    t = _sections(court)["sections"]
    assert (
        t["previsions_4_semaines"]["statut"] == "RENSEIGNEE"
        and t["previsions_13_semaines"]["statut"] == "NON_DISPONIBLE"
    )
    assert any("inférieur à 13 semaines" in m for m in t["previsions_13_semaines"]["manques"])


def test_revue_figee_une_capture_arrivee_apres_la_fin_n_entre_pas():
    avant = _sections(_monde(recu=APRES))["sections"]  # tout arrive APRÈS la fin de la semaine
    assert avant["risques"]["contenu"]["presents"] == 0 and avant["risques"]["statut"] == "PARTIELLE"
    marge = {i["id"]: i for i in avant["revenus_cash_marge"]["contenu"]["indicateurs"]}
    assert marge["gross_margin"]["faits"] == [] and avant["previsions_13_semaines"]["statut"] == "NON_DISPONIBLE"


def test_determinisme_et_aucun_flottant():
    a, b = _sections(_monde()), _sections(_monde())
    assert a == b and "." not in "".join(c for c in json.dumps(a["ids"]))
    assert json.loads(json.dumps(a)) == a


def test_periode_sans_fin_lisible_refusee():
    with pytest.raises(ValueError, match="REJ-DIRECTION-PERIODE"):
        rd.sections(captures=[], sessions=[], periode={"fin": "demain", "fin_local": "2026-10-26"})


def test_signaux_propres_a_m9_comptent_les_sorties_de_modele_refusees_par_le_code():
    evenements = [
        {"type": "TOUR", "session_id": "s1", "role": "croissance_marketing", "issue": "REFUSE", "recu_a": DANS,
         "code": "REJ-CONSEIL-SORTIE"},
        {"type": "TOUR", "session_id": "s1", "role": "inventaire", "issue": "ADMIS", "recu_a": DANS, "code": None},
        {"type": "TOUR", "session_id": "s2", "role": "conseiller_pdg", "issue": "REFUSE", "recu_a": APRES,
         "code": "REJ-CONSEIL-CITATION"},
    ]  # fmt: skip
    res = rd.sections(captures=[], sessions=evenements, periode=PERIODE)
    signaux = res["sections"]["risques"]["contenu"]["signaux_de_m9"]
    assert signaux["sorties_de_modele_refusees"] == 1 and signaux["par_code"] == {"REJ-CONSEIL-SORTIE": 1}
    assert signaux["lectures_attendues_non_presentes"] >= 1 and signaux["contradictions"] == 0
