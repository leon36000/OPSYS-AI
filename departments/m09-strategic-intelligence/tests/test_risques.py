"""M9.12 — radar de risques : signaux des propriétaires, faux positif, source périmée, absence de cause (fictif)."""

import pytest
from m9_strategic_intelligence import capture_strategique as cs
from m9_strategic_intelligence import catalogue_producteurs as cat
from m9_strategic_intelligence import risques as rk

FICTIF = True
CONNAISSANCE = "2026-10-28T13:00:00Z"


def _enveloppe(contenu):
    return {"ok": True, "resultat": {"accepte": True, "resultat": contenu}}


def _tresorerie(statut="ALERTE", deficit=None, calculable=True):
    return _enveloppe(
        {
            "type": "PREVISION_TRESORERIE",
            "calculable": calculable,
            "alerte": {"statut": statut},
            "premiere_semaine_en_deficit": deficit,
            "semaines": [],
            "prochain_depart": None,
        }
    )


def _disponibilite(statut):
    lignes = (
        [] if statut is None else [{"devis_id": "D1", "chantier_id": "C1", "statut": statut, "lignes_manquantes": []}]
    )
    return _enveloppe({"articles": [], "tronque": False, "reservations_actives": lignes})


def _retards(bloquee=True, motif="meteo"):
    return _enveloppe(
        {
            "reports": {
                "liste": [{"intervention_id": "I1", "motif": motif, "depuis": "2026-10-27T10:00:00Z"}],
                "reste": 0,
            },
            "incidents": {
                "liste": [{"demande_id": "R1", "bloquee": bloquee, "depuis": "2026-10-27T10:00:00Z"}],
                "reste": 0,
            },
        }
    )


def _mesures(valeur):
    return {
        "ok": True,
        "resultat": {"trouve": True, "mesures": [{"metric_id": "m8_ecart_marge_cad", "valeur": valeur}]},
    }


def _chaine(*specs):
    """specs : (lecture_id, réponse, recu_a, arguments)."""
    chaine, precedent = [], cs.HASH_INITIAL
    for index, (lecture, reponse, recu, arguments) in enumerate(specs):
        capture = cs.construire(
            cat.obtenir(lecture),
            arguments,
            reponse if isinstance(reponse, list) else [reponse],
            recu_a=recu,
            reference=None,
            index=index,
            hash_precedent=precedent,
        )
        chaine.append(capture)
        precedent = capture["hash_maillon"]
    return chaine


def _par_regle(res):
    return {(r["regle"], r["sujet"]): r for r in res["risques"]}


def test_quatre_domaines_signales_avec_gravite_preuves_et_sans_cause():
    chaine = _chaine(
        ("m5.prevision_tresorerie", _tresorerie(deficit=3), "2026-10-27T12:00:00Z", {"aujourd_hui": "2026-10-27"}),
        ("m6.disponibilite", _disponibilite("a_commander"), "2026-10-27T12:00:01Z", {}),
        ("m4.retards_incidents", _retards(), "2026-10-27T12:00:02Z", {"horodatage_reference": "2026-10-27T12:00:00Z"}),
        ("m8.mesures_chantier", _mesures("-6.00"), "2026-10-27T12:00:03Z", {"wct_id": "W1"}),
    )
    res = rk.evaluer(chaine, connaissance=CONNAISSANCE)
    r = _par_regle(res)
    assert r[("cash_alerte_seuil", "tresorerie")]["gravite"] == "ELEVE"
    assert r[("materiaux_reservation_incomplete", "devis:D1")]["gravite"] == "ELEVE"
    assert r[("capacite_incident_ouvert", "incident:R1")]["gravite"] == "ELEVE"
    assert r[("meteo_report_en_cours", "report:I1")]["gravite"] == "MOYEN"
    assert ("capacite_report_en_cours", "report:I1") not in r, "un report météo n'est pas un report de capacité"
    assert r[("qualite_ecart_marge_negatif", "rentabilite_chantier")]["gravite"] == "MOYEN"
    assert {x["domaine"] for x in res["risques"]} == {"cash", "materiaux", "capacite", "meteo", "qualite"}
    for risque in res["risques"]:
        assert (
            risque["statut"] == "ACTIF"
            and risque["origine_etablie"] is False
            and "non établie" in risque["explication"]
        )
        assert risque["preuves"] and all(
            p.startswith(risque["source"]["hash"][:0]) and "#" in p for p in risque["preuves"]
        )
    assert res["grille"]["statut"] == "PROPOSEE_NON_VALIDEE_PAR_NATHAN"
    cash = r[("cash_alerte_seuil", "tresorerie")]
    assert cash["preuves"][0] == "m5.prevision_tresorerie#0:p0.resultat.resultat.alerte.statut"
    assert res["regles_non_evaluees"] == [] and len(res["radar_id"]) == 64
    assert "cause" not in str(res.keys()) and not any("responsable" in str(x) for x in res["risques"])


def test_sans_signal_aucun_risque_mais_lecture_absente_est_un_risque_inconnu():
    chaine = _chaine(("m6.disponibilite", _disponibilite(None), "2026-10-27T12:00:00Z", {}))
    res = rk.evaluer(chaine, connaissance=CONNAISSANCE)
    assert res["risques"] == []
    absentes = {n["regle"] for n in res["regles_non_evaluees"] if n["raison"] == "ABSENTE"}
    assert {"cash_alerte_seuil", "capacite_incident_ouvert", "qualite_ecart_marge_negatif"} <= absentes
    assert "materiaux_reservation_incomplete" not in absentes, "lecture présente, règle évaluée, aucun signal"


def test_faux_positif_leve_par_une_lecture_plus_recente_les_deux_preuves_citees():
    chaine = _chaine(
        ("m6.disponibilite", _disponibilite("partiel"), "2026-10-26T12:00:00Z", {}),
        ("m6.disponibilite", _disponibilite("pret"), "2026-10-27T12:00:00Z", {}),
    )
    risque = rk.evaluer(chaine, connaissance=CONNAISSANCE)["risques"][0]
    assert risque["statut"] == "LEVE" and risque["gravite"] == "MOYEN"
    assert risque["source"]["capture"] == 0 and risque["elements_contraires"][0]["capture"] == 1
    # Connaissance antérieure à la seconde lecture : le risque est encore ACTIF (rien d'infirmant n'était connu).
    avant = rk.evaluer(chaine, connaissance="2026-10-26T18:00:00Z")["risques"][0]
    assert avant["statut"] == "ACTIF" and avant["elements_contraires"] == []


def test_source_perimee_est_a_reconfirmer_et_non_affirmee():
    chaine = _chaine(("m6.disponibilite", _disponibilite("partiel"), "2026-10-10T12:00:00Z", {}))
    res = rk.evaluer(chaine, connaissance=CONNAISSANCE, perime_apres_jours=7)
    risque = res["risques"][0]
    assert risque["statut"] == "A_RECONFIRMER" and risque["source"]["age_jours"] == 18
    assert (
        risque["donnees_manquantes"]
        and rk.evaluer(chaine, connaissance=CONNAISSANCE)["risques"][0]["statut"] == "ACTIF"
    )


def test_lecture_refusee_partielle_ou_contradictoire_n_est_jamais_evaluee():
    refus = {"ok": False, "erreur": "refus_metier", "details": "x"}
    partielle = _tresorerie()
    partielle["resultat"]["resultat"]["prochain_depart"] = 16  # page suivante non lue
    chaine = _chaine(
        ("m4.retards_incidents", refus, "2026-10-27T12:00:00Z", {"horodatage_reference": "2026-10-27T12:00:00Z"}),
        ("m5.prevision_tresorerie", partielle, "2026-10-27T12:00:01Z", {"aujourd_hui": "2026-10-27"}),
    )
    res = rk.evaluer(chaine, connaissance=CONNAISSANCE)
    raisons = {n["regle"]: n["raison"] for n in res["regles_non_evaluees"]}
    assert raisons["capacite_incident_ouvert"] == "REFUSEE" and raisons["cash_alerte_seuil"] == "PARTIELLE"
    assert not [x for x in res["risques"] if x["domaine"] in ("capacite", "cash")], (
        "aucun signal tiré d'une lecture douteuse"
    )


def test_cash_non_evaluable_est_une_donnee_manquante_de_gravite_inconnue():
    chaine = _chaine(
        (
            "m5.prevision_tresorerie",
            _tresorerie("SEUIL_A_CONFIGURER"),
            "2026-10-27T12:00:00Z",
            {"aujourd_hui": "2026-10-27"},
        )
    )
    risque = rk.evaluer(chaine, connaissance=CONNAISSANCE)["risques"][0]
    assert (risque["regle"], risque["gravite"]) == ("cash_non_evaluable", "INCONNU")


@pytest.mark.parametrize("valeur", [-1, "7", 4000])
def test_peremption_invalide_refusee(valeur):
    with pytest.raises(ValueError, match="REJ-RISQUE-PEREMPTION"):
        rk.evaluer([], connaissance=CONNAISSANCE, perime_apres_jours=valeur)


def test_ecart_de_marge_positif_ou_illisible_n_est_pas_un_risque():
    chaine = _chaine(("m8.mesures_chantier", _mesures("6.00"), "2026-10-27T12:00:00Z", {"wct_id": "W1"}))
    assert rk.evaluer(chaine, connaissance=CONNAISSANCE)["risques"] == []
    chaine = _chaine(("m8.mesures_chantier", _mesures("abc"), "2026-10-27T12:00:00Z", {"wct_id": "W1"}))
    assert rk.evaluer(chaine, connaissance=CONNAISSANCE)["risques"] == []
