"""M9.12 — radar de risques : signaux des propriétaires, faux positif, source périmée, absence de cause (fictif)."""

import importlib.util
import sys
from dataclasses import FrozenInstanceError
from decimal import Decimal
from pathlib import Path

import pytest
from m9_strategic_intelligence import capture_strategique as cs
from m9_strategic_intelligence import catalogue_producteurs as cat
from m9_strategic_intelligence import risques as rk

FICTIF = True
CONNAISSANCE = "2026-10-28T13:00:00Z"


def _charger_aide():
    if "aide_radar" in sys.modules:
        return sys.modules["aide_radar"]
    spec = importlib.util.spec_from_file_location("aide_radar", Path(__file__).with_name("aide_radar.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules["aide_radar"] = module
    spec.loader.exec_module(module)
    return module


A = _charger_aide()


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
    historiques = {
        "cash_alerte_seuil",
        "cash_non_evaluable",
        "materiaux_reservation_incomplete",
        "capacite_incident_ouvert",
        "capacite_report_en_cours",
        "meteo_report_en_cours",
        "qualite_ecart_marge_negatif",
    }
    assert [n for n in res["regles_non_evaluees"] if n["regle"] in historiques] == [] and len(res["radar_id"]) == 64
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


# --- Ce qui a changé depuis la veille (delta) -----------------------------------------------------------------------
def test_delta_apparu_leve_et_gravite_changee_sur_deux_etats_connus():
    hier = "2026-10-27T10:00:00Z"
    aujourd_hui = "2026-10-28T10:00:00Z"
    chaine = _chaine(
        ("m4.retards_incidents", _retards(bloquee=False, motif="manuel"), hier, {"horodatage_reference": hier}),
        ("m6.disponibilite", _disponibilite("partiel"), aujourd_hui, {}),
        (
            "m4.retards_incidents",
            _retards(bloquee=True, motif="manuel"),
            aujourd_hui,
            {"horodatage_reference": aujourd_hui},
        ),
    )
    res = rk.delta(chaine, connaissance="2026-10-28T12:00:00Z")
    assert res["connaissance_precedente"] == "2026-10-27T12:00:00Z"
    assert [(r["regle"], r["sujet"]) for r in res["apparus"]] == [("materiaux_reservation_incomplete", "devis:D1")]
    assert res["leves"] == [] and res["gravite_changee"][0]["sujet"] == "incident:R1"
    assert (
        res["gravite_changee"][0]["gravite_precedente"] == "FAIBLE" and res["gravite_changee"][0]["gravite"] == "ELEVE"
    )
    assert res["inchanges"] >= 0 and "pourquoi" in " ".join(res["limites"])


def test_delta_un_signal_disparu_est_leve_et_une_capture_future_est_ignoree():
    hier = "2026-10-27T10:00:00Z"
    aujourd_hui = "2026-10-28T10:00:00Z"
    chaine = _chaine(
        ("m6.disponibilite", _disponibilite("partiel"), hier, {}),
        ("m6.disponibilite", _disponibilite(None), aujourd_hui, {}),
    )
    res = rk.delta(chaine, connaissance="2026-10-28T12:00:00Z")
    assert [r["sujet"] for r in res["leves"]] == ["devis:D1"] and res["apparus"] == []
    futur = _chaine(("m6.disponibilite", _disponibilite("partiel"), "2026-10-28T11:00:00Z", {}))
    assert rk.delta(futur, connaissance="2026-10-28T12:00:00Z")["apparus"][0]["sujet"] == "devis:D1"
    ancien = rk.delta(futur, connaissance="2026-10-28T10:30:00Z")
    assert ancien["apparus"] == [], "une capture reçue après l'instant de connaissance n'existe pas encore"


@pytest.mark.parametrize("jours", [0, 32, "1", None, True])
def test_delta_refuse_un_nombre_de_jours_invalide_et_un_instant_sans_fuseau(jours):
    with pytest.raises(ValueError, match="REJ-RISQUE-DELTA"):
        rk.delta([], connaissance=CONNAISSANCE, jours=jours)
    with pytest.raises(ValueError, match="REJ-RISQUE-DELTA"):
        rk.delta([], connaissance="2026-10-28T13:00:00")


# --- Objets publics immuables et construction des règles (bornes de défense) ---------------------------------------
def test_les_objets_publics_du_radar_sont_immuables():
    reglage = rk.REGLAGES["plaintes_seuil_nombre"]
    with pytest.raises(FrozenInstanceError):
        reglage.nom = "autre"
    contexte = rk.Contexte({"plaintes_seuil_nombre": Decimal("3")}, None, None)
    with pytest.raises(FrozenInstanceError):
        contexte.multiple = Decimal("2")
    signal = rk.Signal("MOYEN", "sujet", ("champ",), "raison")
    with pytest.raises(FrozenInstanceError):
        signal.gravite = "ELEVE"
    regle = next(r for r in rk.REGLES if r.id == "cash_alerte_seuil")
    with pytest.raises(FrozenInstanceError):
        regle.id = "autre"


def _regle(**plus):
    champs = {"id": "r", "domaine": "cash", "lecture_id": "m5.prevision_tresorerie", "lignes": "x",
              "signal": lambda ligne, ctx: None}
    champs.update(plus)
    return rk.Regle(**champs)


@pytest.mark.parametrize(
    "champs",
    [{"id": ""}, {"domaine": ""}, {"lignes": ""}, {"seuils": ("inconnu",)}],
)
def test_une_regle_incomplete_est_refusee(champs):
    with pytest.raises(ValueError, match="règle de risque incomplète"):
        _regle(**champs)


def test_une_regle_qui_declare_tous_les_seuils_est_valide():
    regle = _regle(seuils=tuple(rk.REGLAGES))
    assert set(regle.seuils) == set(rk.REGLAGES)


# --- Statuts et bornes des signaux -----------------------------------------------------------------------------------
def test_un_cash_libre_non_calculable_est_inconnu_meme_avec_un_statut_d_alerte_ordinaire():
    chaine = _chaine(
        (
            "m5.prevision_tresorerie",
            _tresorerie(statut="ORDINAIRE", calculable=False),
            "2026-10-27T12:00:00Z",
            {"aujourd_hui": "2026-10-27"},
        )
    )
    res = rk.evaluer(chaine, connaissance=CONNAISSANCE)
    r = _par_regle(res)[("cash_non_evaluable", "tresorerie")]
    assert r["gravite"] == "INCONNU"
    ordinaire = _chaine(
        (
            "m5.prevision_tresorerie",
            _tresorerie(statut="ORDINAIRE", calculable=None),
            "2026-10-27T12:00:00Z",
            {"aujourd_hui": "2026-10-27"},
        )
    )
    assert not [x for x in rk.evaluer(ordinaire, connaissance=CONNAISSANCE)["risques"]
                if x["regle"] == "cash_non_evaluable"]


def test_une_reservation_partielle_est_de_gravite_moyenne_et_a_commander_elevee():
    for statut, gravite in (("partiel", "MOYEN"), ("a_commander", "ELEVE")):
        chaine = _chaine(("m6.disponibilite", _disponibilite(statut), "2026-10-27T12:00:00Z", {}))
        r = _par_regle(rk.evaluer(chaine, connaissance=CONNAISSANCE))[
            ("materiaux_reservation_incomplete", "devis:D1")
        ]
        assert r["gravite"] == gravite
        assert ("à commander" if statut == "a_commander" else "partielle") in r["raison"]


def test_un_report_meteo_sans_identifiant_d_intervention_n_est_pas_un_risque():
    page = _enveloppe(
        {
            "reports": {"liste": [{"motif": "meteo", "depuis": "2026-10-27T10:00:00Z"}], "reste": 0},
            "incidents": {"liste": [], "reste": 0},
        }
    )
    chaine = _chaine(
        ("m4.retards_incidents", page, "2026-10-27T12:00:00Z", {"horodatage_reference": "2026-10-27T12:00:00Z"})
    )
    res = rk.evaluer(chaine, connaissance=CONNAISSANCE)
    assert not [r for r in res["risques"] if r["regle"] == "meteo_report_en_cours"]


@pytest.mark.parametrize("valeur", ["0.00", "0.50"])
def test_un_ecart_de_marge_nul_ou_positif_inferieur_a_un_n_est_jamais_un_risque(valeur):
    chaine = _chaine(("m8.mesures_chantier", _mesures(valeur), "2026-10-27T12:00:00Z", {"wct_id": "W1"}))
    assert not [r for r in rk.evaluer(chaine, connaissance=CONNAISSANCE)["risques"]
                if r["regle"] == "qualite_ecart_marge_negatif"]


def test_des_plaintes_sans_nombre_declare_ne_sont_pas_un_afflux():
    page = A.page_plaintes(3)
    page["resultat"]["resultat"]["comptes"]["declarees"] = None
    chaine: list = []
    A.capturer(chaine, "m1.plaintes_structurees", page)
    res = A.radar(chaine, seuils={"plaintes_seuil_nombre": 3})
    assert not [r for r in res["risques"] if r["regle"] == "plaintes_afflux"]


@pytest.mark.parametrize(
    "modif",
    [{"statut": "clos"}, {"plainte_id": None}, {"categories": None}, {"categories": ["degat"]}],
)
def test_une_plainte_sensible_exige_statut_ouvert_identifiant_et_categorie_sensible(modif):
    page = A.page_plaintes(1, categories=("avocat",), statut="ouvert")
    page["resultat"]["resultat"]["plaintes"][0].update(modif)
    chaine: list = []
    A.capturer(chaine, "m1.plaintes_structurees", page)
    res = A.radar(chaine, seuils={})
    assert not [r for r in res["risques"] if r["regle"] == "plaintes_sensibles_ouvertes"]


@pytest.mark.parametrize(
    "modif",
    [
        {"minutes_planifiees": None},
        {"minutes_disponibles": None},
        {"equipe_id": 1},
        {"minutes_planifiees": 0},
        {"minutes_disponibles": -1},
    ],
)
def test_une_surcharge_exige_des_minutes_entieres_positives_et_un_identifiant(modif):
    page = A.page_capacite([("eq-a", 600, 540)])
    page["resultat"]["resultat"]["equipes"][0].update(modif)
    chaine: list = []
    A.capturer(chaine, "m4.capacite_equipe", page)
    res = A.radar(chaine, seuils={"capacite_utilisation_seuil_pct": 90})
    assert not [r for r in res["risques"] if r["regle"] == "capacite_surcharge_cedule"]


def test_une_minute_planifiee_au_seuil_reste_une_surcharge():
    page = A.page_capacite([("eq-a", 1, 1)])
    chaine: list = []
    A.capturer(chaine, "m4.capacite_equipe", page)
    res = A.radar(chaine, seuils={"capacite_utilisation_seuil_pct": 90})
    assert [r["sujet"] for r in res["risques"] if r["regle"] == "capacite_surcharge_cedule"] == ["equipe:eq-a"]


@pytest.mark.parametrize(
    "modif",
    [
        {"serie": "pas un objet"},
        {"serie": {"nom": "leads_qualifies"}},
        {"par_periode": "pas une liste"},
    ],
)
def test_les_leads_exigent_la_serie_ingeres_et_une_liste_de_periodes(modif):
    page = A.page_prevision(haut="4.00")
    page["resultat"]["resultat"].update(modif)
    chaine: list = []
    A.capturer(chaine, "m2.prevision_pipeline", page)
    res = A.radar(chaine, seuils={"leads_plancher_par_semaine": 5})
    assert not [r for r in res["risques"] if r["regle"] == "leads_sous_plancher"]


def test_le_seuil_des_leads_n_est_pas_un_seuil_critique_par_multiple():
    chaine: list = []
    A.capturer(chaine, "m2.prevision_pipeline", A.page_prevision(haut="4.00"))
    res = A.radar(chaine, seuils={"leads_plancher_par_semaine": 5, "multiple_seuil_critique": 2})
    r = A.par_regle(res)[("leads_sous_plancher", "periode:1")]
    assert "critique_si_au_moins" not in r["seuil"]


@pytest.mark.parametrize(
    "report",
    [
        ("I1", "manuel", None),
        (None, "manuel", "2026-10-20T10:00:00Z"),
    ],
)
def test_un_retard_exige_un_identifiant_et_un_instant_lisibles(report):
    chaine: list = []
    A.capturer(chaine, "m4.retards_incidents", A.page_retards(reports=[report]))
    res = A.radar(chaine, seuils={"retard_chantier_jours": 1})
    assert not [r for r in res["risques"] if r["regle"] == "chantier_retard_prolonge"]


def test_un_cash_libre_pile_au_plancher_n_est_pas_sous_le_plancher_et_sous_le_plancher_n_est_pas_critique():
    pile: list = []
    A.capturer(pile, "m8.vue_executive", A.page_cash_libre("5000.00"))
    res = A.radar(pile, seuils={"cash_libre_plancher_cad": 5000, "multiple_seuil_critique": 2})
    assert not [r for r in res["risques"] if r["regle"] == "cash_libre_sous_plancher"]

    sous: list = []
    A.capturer(sous, "m8.vue_executive", A.page_cash_libre("4999.99"))
    res = A.radar(sous, seuils={"cash_libre_plancher_cad": 5000, "multiple_seuil_critique": 2})
    r = A.par_regle(res)[("cash_libre_sous_plancher", "cash_libre")]
    assert "critique_si_au_moins" not in r["seuil"]


def test_les_regles_sla_amont_ignorent_les_entrees_hors_forme_et_ne_gardent_que_les_valides():
    page = A.page_sla(non_evaluees=("lead_chaud_non_contacte",))
    page["resultat"]["resultat"]["regles"].extend(
        ["pas un objet", {"etat": "non_evaluee", "regle": 1}, {"etat": "evaluee", "regle": "autre"}]
    )
    chaine: list = []
    A.capturer(chaine, "m2.sla_filet", page)
    res = A.radar(chaine)
    raisons = [n for n in res["regles_non_evaluees"] if n["raison"] == "NON_EVALUEE_PAR_LE_PROPRIETAIRE"]
    assert raisons == [{
        "regle": "filet_sla_violation:lead_chaud_non_contacte", "domaine": "ventes",
        "raison": "NON_EVALUEE_PAR_LE_PROPRIETAIRE", "a_declarer_chez": "m02-revenue-crm",
    }]


# --- Bornes de péremption, d'âge et de delta -------------------------------------------------------------------------
@pytest.mark.parametrize("jours", [0, 3650])
def test_la_peremption_accepte_ses_bornes_exactes(jours):
    assert rk.evaluer([], connaissance=CONNAISSANCE, perime_apres_jours=jours)["perime_apres_jours"] == jours


@pytest.mark.parametrize("jours", [-1, 3651, "7", True])
def test_la_peremption_refuse_un_jour_hors_bornes(jours):
    with pytest.raises(ValueError, match="REJ-RISQUE-PEREMPTION"):
        rk.evaluer([], connaissance=CONNAISSANCE, perime_apres_jours=jours)


def test_un_multiple_critique_de_un_est_declare_valide():
    res = rk.evaluer([], connaissance=CONNAISSANCE, seuils={"multiple_seuil_critique": 1})
    assert res["escalade"]["multiple_declare"] == "1"


def test_un_age_pile_a_la_peremption_reste_actif():
    chaine = _chaine(("m6.disponibilite", _disponibilite("partiel"), "2026-10-21T13:00:00Z", {}))
    res = rk.evaluer(chaine, connaissance=CONNAISSANCE, perime_apres_jours=7)
    risque = next(r for r in res["risques"] if r["regle"] == "materiaux_reservation_incomplete")
    assert risque["source"]["age_jours"] == 7 and risque["statut"] == "ACTIF"


def test_un_risque_leve_n_a_pas_de_donnee_manquante_de_peremption():
    chaine = _chaine(
        ("m6.disponibilite", _disponibilite("partiel"), "2026-10-26T12:00:00Z", {}),
        ("m6.disponibilite", _disponibilite("pret"), "2026-10-27T12:00:00Z", {}),
    )
    leve = next(r for r in rk.evaluer(chaine, connaissance=CONNAISSANCE)["risques"] if r["statut"] == "LEVE")
    assert leve["donnees_manquantes"] == []


def test_un_risque_de_gravite_inconnue_est_rendu_apres_les_gravites_connues():
    chaine = _chaine(
        ("m6.disponibilite", _disponibilite("partiel"), "2026-10-27T12:00:00Z", {}),
        ("m5.prevision_tresorerie", _tresorerie("SEUIL_A_CONFIGURER"), "2026-10-27T12:00:01Z",
         {"aujourd_hui": "2026-10-27"}),
    )
    risques = rk.evaluer(chaine, connaissance=CONNAISSANCE)["risques"]
    assert risques and risques[-1]["gravite"] == "INCONNU" and risques[-1]["regle"] == "cash_non_evaluable"


def test_la_peremption_des_lectures_n_est_pas_un_seuil_critique_et_ne_cree_pas_de_donnee_manquante():
    chaine = _chaine(("m6.disponibilite", _disponibilite("partiel"), "2026-10-10T12:00:00Z", {}))
    res = rk.evaluer(
        chaine,
        connaissance=CONNAISSANCE,
        seuils={"donnees_perimees_jours": 7, "multiple_seuil_critique": 2},
    )
    r = next(x for x in res["risques"] if x["regle"] == "donnees_perimees")
    assert "critique_si_au_moins" not in r["seuil"] and r["donnees_manquantes"] == []


# --- Groupes de lectures et adresses de preuves ----------------------------------------------------------------------
def test_le_groupe_ignore_l_argument_de_reference_mais_pas_les_autres():
    base = {"lecture_id": "m2.prevision_pipeline", "arguments": {"horodatage": "2026-10-28T12:00:00Z"},
            "arguments_sha256": "inutilise"}
    assert rk._groupe(base) == cs.empreinte({})
    assert rk._groupe({**base, "arguments": {"horodatage": "2026-10-29T12:00:00Z"}}) == rk._groupe(base)
    assert rk._groupe({**base, "arguments": {"horodatage": "2026-10-28T12:00:00Z", "serie": "leads_ingeres"}}) != (
        rk._groupe(base)
    )
    assert rk._groupe({"lecture_id": "inconnue", "arguments": {}, "arguments_sha256": "abc"}) == "abc"
    assert rk._groupe({"lecture_id": "m2.prevision_pipeline", "arguments": ["pas", "un", "objet"],
                       "arguments_sha256": "abc"}) == "abc"


def test_une_adresse_de_preuve_de_liste_pointe_sur_le_rang_exact():
    capture = {"lecture_id": "m6.disponibilite", "index": 2}
    assert rk._adresse(capture, 0, "resultat.resultat.lignes[*]", 3, "statut") == (
        "m6.disponibilite#2:p0.resultat.resultat.lignes[3].statut"
    )


def test_l_age_d_une_capture_illisible_est_inconnu_meme_avec_un_instant_valide():
    assert rk._age_jours({"recu_a": "pas un instant"}, cs.instant(CONNAISSANCE)) is None


def test_le_delta_accepte_ses_bornes_de_jours():
    for jours in (1, 31):
        res = rk.delta([], connaissance=CONNAISSANCE, jours=jours)
        assert res["type"] == "DELTA_RISQUES" and res["connaissance"]


def test_le_delta_compte_les_inchanges_et_les_leves_par_le_radar_sans_les_additionner():
    chaine: list = []
    A.capturer(chaine, "m1.plaintes_structurees", A.page_plaintes(4), recu="2026-10-27T12:00:00Z")
    A.capturer(chaine, "m6.disponibilite", _disponibilite("partiel"), recu="2026-10-27T12:00:01Z")
    A.capturer(chaine, "m1.plaintes_structurees", A.page_plaintes(6), recu="2026-10-28T12:00:00Z")
    A.capturer(chaine, "m6.disponibilite", _disponibilite("partiel"), recu="2026-10-28T12:00:01Z")
    res = rk.delta(chaine, connaissance=CONNAISSANCE, jours=1, seuils=A.SEUILS)
    assert len(res["gravite_changee"]) == 1 and res["inchanges"] == 1
    assert res["leves_par_le_radar"] == 0


def test_les_gardes_de_forme_des_signaux_ignorent_les_lignes_incompletes():
    ctx = rk.Contexte(
        {k: Decimal(str(v)) for k, v in A.SEUILS.items() if k != "multiple_seuil_critique"},
        cs.instant(CONNAISSANCE),
        Decimal("1.5"),
    )
    cas = [
        (rk._signal_plaintes_afflux, {"comptes": {"declarees": None}, "etat": "BRANCHEE"}),
        (rk._signal_plainte_sensible, {"plainte_id": "P1", "statut": "clos", "categories": ["avocat"]}),
        (rk._signal_plainte_sensible, {"plainte_id": None, "statut": "ouvert", "categories": ["avocat"]}),
        (rk._signal_plainte_sensible, {"plainte_id": "P1", "statut": "ouvert", "categories": None}),
        (rk._signal_plainte_sensible, {"plainte_id": "P1", "statut": "ouvert", "categories": ["degat"]}),
        (rk._signal_surcharge, {"equipe_id": "eq-a", "minutes_planifiees": None, "minutes_disponibles": 1}),
        (rk._signal_surcharge, {"equipe_id": "eq-a", "minutes_planifiees": 1, "minutes_disponibles": None}),
        (rk._signal_surcharge, {"equipe_id": 1, "minutes_planifiees": 1, "minutes_disponibles": 1}),
        (rk._signal_surcharge, {"equipe_id": "eq-a", "minutes_planifiees": 1, "minutes_disponibles": -1}),
        (rk._signal_leads_plancher, {"serie": "pas un objet", "par_periode": []}),
        (rk._signal_leads_plancher,
         {"serie": {"nom": "leads_qualifies"}, "par_periode": [{"periode": "1", "intervalle": {"haut": "4"}}]}),
        (rk._signal_leads_plancher, {"serie": {"nom": "leads_ingeres"}, "par_periode": "pas une liste"}),
        (rk._signal_cash_libre_plancher, {"constat": {"statut": "CALCULE"}}),
    ]
    for fonction, ligne in cas:
        assert fonction(ligne, ctx) is None, (fonction.__name__, ligne)


def test_l_ordre_place_les_actifs_avant_les_a_reconfirmer():
    chaine: list = []
    A.capturer(
        chaine,
        "m4.retards_incidents",
        A.page_retards(incidents=[{"demande_id": "R1", "bloquee": True, "depuis": "2026-10-20T10:00:00Z"}]),
        recu="2026-10-20T12:00:00Z",
    )
    A.capturer(chaine, "m6.disponibilite", _disponibilite("partiel"), recu="2026-10-27T12:00:00Z")
    res = A.radar(chaine, perime_apres_jours=1)
    ordre = [
        r["statut"]
        for r in res["risques"]
        if r["regle"] in ("capacite_incident_ouvert", "materiaux_reservation_incomplete")
    ]
    assert ordre == ["ACTIF", "A_RECONFIRMER"]


def test_l_ordre_place_les_a_reconfirmer_avant_les_leves():
    chaine = _chaine(
        ("m6.disponibilite", _disponibilite("a_commander"), "2026-10-20T12:00:00Z", {}),
        ("m6.disponibilite", _disponibilite("pret"), "2026-10-27T12:00:00Z", {}),
        ("m8.mesures_chantier", _mesures("-6.00"), "2026-10-20T12:00:01Z", {"wct_id": "W1"}),
    )
    res = rk.evaluer(chaine, connaissance=CONNAISSANCE, perime_apres_jours=1)
    ordre = [r["statut"] for r in res["risques"] if r["regle"] in ("materiaux_reservation_incomplete",
                                                                  "qualite_ecart_marge_negatif")]
    assert ordre == ["A_RECONFIRMER", "LEVE"]
