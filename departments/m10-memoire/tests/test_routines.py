"""routines.py : l'énumérateur des affaires touchées, l'attendu de l'audit « non-oubli » relu du bus, le rapport
d'audit et les KPI.
Module pur, registres en mémoire, instants fournis. Données FICTIVES."""

from __future__ import annotations

import pytest
from m10_memoire import consolidation, registre, revision, routines, variance, wct

FICTIF = True
JOUR = "2026-11-09"
EVT = "2026-11-09T14:00:00-05:00"
CONSO = "2026-11-10T03:05:00-05:00"


def _wct(wct_id, lead_id, horodatage=EVT):
    return {
        "wct_id": wct_id,
        "intervention_id": f"int-{wct_id}",
        "lead_id": lead_id,
        "technicien_id": "T1",
        "horodatage_completion": horodatage,
        "fix_gps_completion": {"latitude": 46.8, "longitude": -71.2},
        "duree_reelle_minutes": 90,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": "a" * 64,
        "consommateurs_cibles": ["M10"],
        "devis_id": f"devis-{wct_id}",
    }


def _variance(evenement_id, wct_id, horodatage=EVT):
    return {
        "evenement_id": evenement_id,
        "wct_id": wct_id,
        "intervention_id": f"int-{wct_id}",
        "chantier_id": "CH-1",
        "statut_variance": "evaluee",
        "signal_critique": False,
        "seuil_pourcentage": 0.1,
        "horodatage_completion": horodatage,
        "lignes": [],
    }


def _lead(reg, lead_id, horodatage=EVT):
    reg.ajouter(
        {
            "type_entree": "evenement_memorise",
            "type_evenement": "m1.lead_qualifie",
            "lead_id": lead_id,
            "service": "gouttieres",
            "canal": "texte",
            "urgence_declaree": False,
            "horodatage": horodatage,
        }
    )


def _mondes():
    return registre.Registre(), registre.Registre()


def _enumerer(ev, af, jour=JOUR, limite=50):
    return routines.enumerer(jour, limite, ev.lire(), af.lire())


# -- 1. l'énumérateur
# --------------------------------------------------------------------------------------------------------
def test_aucune_affaire_touchee_donne_une_liste_vide_pas_une_erreur():
    ev, af = _mondes()
    assert _enumerer(ev, af) == {
        "jour": JOUR,
        "touchees": 0,
        "a_consolider": [],
        "reste": 0,
        "deja_consolidees": 0,
        "affaires_refusees": 0,
    }


def test_seules_les_affaires_touchees_le_jour_demande_sont_designees_triees():
    ev, af = _mondes()
    _lead(ev, "zeta")
    _lead(ev, "alpha")
    _lead(ev, "autre-jour", "2026-11-08T23:59:59-05:00")
    _lead(ev, "lendemain", "2026-11-10T00:00:00-05:00")
    assert _enumerer(ev, af)["a_consolider"] == ["alpha", "zeta"]
    assert _enumerer(ev, af, "2026-11-08")["a_consolider"] == ["autre-jour"]
    # l'ordre du registre ne change pas la liste
    ev2, af2 = _mondes()
    for lead in ("alpha", "zeta"):
        _lead(ev2, lead)
    assert _enumerer(ev2, af2)["a_consolider"] == _enumerer(ev, af)["a_consolider"]


def test_une_variance_et_une_rentabilite_touchent_l_affaire_de_leur_wct():
    ev, af = _mondes()
    wct.memoriser_wct(_wct("w1", "aff-wct", horodatage="2026-11-08T10:00:00-05:00"), ev)  # le WCT est de la veille
    variance.memoriser_variance(_variance("v1", "w1"), ev)  # la variance, elle, est du jour
    resultat = _enumerer(ev, af)
    assert resultat["a_consolider"] == ["aff-wct"]
    # une variance dont le WCT est inconnu ne désigne aucune affaire (jamais devinée)
    variance.memoriser_variance(_variance("v2", "wct-inconnu"), ev)
    assert _enumerer(ev, af)["a_consolider"] == ["aff-wct"]


@pytest.mark.parametrize(
    "forge", ["x y", "a\nb", "a;DROP", "../x", "é", "", "a" * 65, "~opp~x", "a~opp~", "a" * 64 + "~opp~" + "b" * 129]
)
def test_une_affaire_forgee_dans_un_evenement_n_est_jamais_designee_mais_comptee(forge):
    ev, af = _mondes()
    _lead(ev, "bonne")
    wct.memoriser_wct(_wct("w-forge", forge), ev)
    resultat = _enumerer(ev, af)
    assert resultat["a_consolider"] == ["bonne"] and resultat["touchees"] == 1
    assert resultat["affaires_refusees"] == 1


def test_la_limite_borne_la_liste_et_dit_le_surplus():
    ev, af = _mondes()
    for i in range(5):
        _lead(ev, f"aff-{i}")
    page = _enumerer(ev, af, limite=2)
    assert page["a_consolider"] == ["aff-0", "aff-1"] and page["reste"] == 3 and page["touchees"] == 5


def test_une_affaire_consolidee_n_est_plus_designee_et_une_source_tardive_la_redesigne():
    ev, af = _mondes()
    _lead(ev, "a1")
    _lead(ev, "a2")
    assert consolidation.consolider_affaire("a1", JOUR, CONSO, ev, af)["ecrit"] is True
    assert _enumerer(ev, af)["a_consolider"] == ["a2"] and _enumerer(ev, af)["deja_consolidees"] == 1
    wct.memoriser_wct(_wct("tard", "a1", horodatage="2026-11-09T22:00:00-05:00"), ev)  # source tardive
    assert _enumerer(ev, af)["a_consolider"] == ["a1", "a2"]
    assert consolidation.consolider_affaire("a1", JOUR, CONSO, ev, af)["ecrit"] is True
    assert _enumerer(ev, af)["a_consolider"] == ["a2"]


def test_la_designation_coincide_exactement_avec_ce_que_la_consolidation_ecrirait():
    """Pour chaque affaire du registre : désignée « à consolider » <=> `consolider_affaire` ajoute un maillon."""
    ev, af = _mondes()
    for lead in ("a1", "a2", "a3", "a4"):
        _lead(ev, lead)
    wct.memoriser_wct(_wct("w", "a2"), ev)
    consolidation.consolider_affaire("a3", JOUR, CONSO, ev, af)
    consolidation.consolider_affaire("a4", JOUR, CONSO, ev, af)
    wct.memoriser_wct(_wct("w2", "a4", horodatage="2026-11-09T20:00:00-05:00"), ev)  # a4 : source tardive
    designees = set(_enumerer(ev, af)["a_consolider"])
    for lead in ("a1", "a2", "a3", "a4", "inconnue"):
        ecrit = consolidation.consolider_affaire(lead, JOUR, CONSO, ev, af)["ecrit"]
        assert ecrit == (lead in designees), lead


# -- 2. l'attendu relu du bus
# -------------------------------------------------------------------------------------------------
def _pub(type_evenement, charge, recu="traite"):
    return {"type_evenement": type_evenement, "charge": charge, "recu": recu}


def test_seul_un_evenement_traite_est_attendu_les_autres_statuts_sont_dits_pas_comptes_comme_oublis():
    wct_charge = _wct("w1", "l1")
    bus = routines.attendus_du_bus(
        [
            _pub("m4.travaux_termines", wct_charge),
            _pub("m4.travaux_termines", _wct("w2", "l1"), "echec"),
            _pub("m4.travaux_termines", _wct("w3", "l1"), "quarantaine"),
            _pub("m4.travaux_termines", _wct("w4", "l1"), None),
            _pub("m9.fait_strategique", {}),
            _pub("m6.variance_chantier", {"evenement_id": "v1"}),
            _pub("m5.rentabilite_chantier", {"evenement_id": "r1"}),
        ]
    )
    assert bus["attendus"] == [
        {"type_evenement": "m4.travaux_termines", "identifiant": "w1"},
        {"type_evenement": "m6.variance_chantier", "identifiant": "v1"},
        {"type_evenement": "m5.rentabilite_chantier", "identifiant": "r1"},
    ]
    assert bus["livraison"] == {
        "en_attente": 1,
        "en_echec": 1,
        "quarantaine": 1,
        "refuses_par_forme": 0,
        "hors_perimetre": 1,
    }


def test_l_identifiant_attendu_de_l_amont_est_celui_que_m10_garde_une_charge_hors_forme_n_est_pas_un_oubli():
    lead = {
        "lead": {"lead_id": "l1", "service": "gouttieres", "canal": "texte", "urgence_declaree": False},
        "horodatage": EVT,
    }
    bus = routines.attendus_du_bus(
        [
            _pub("m1.lead_qualifie", lead),
            _pub(
                "m3.devis_accepte",
                {
                    "devis_id": "d1",
                    "lead_id": "l2",
                    "chantier_id": None,
                    "horodatage_acceptation": EVT,
                    "prix_total": "1.00",
                    "cout_total": "1.00",
                    "taux_marge": "0.1",
                },
            ),
            _pub("m1.lead_qualifie", {"lead": {"lead_id": "mauvais id"}, "horodatage": EVT}),  # M10 l'aurait refusée
            _pub("m4.travaux_termines", {"wct_id": ""}),
        ]
    )
    assert bus["attendus"] == [
        {"type_evenement": "m1.lead_qualifie", "identifiant": "l1"},
        {"type_evenement": "m3.devis_accepte", "identifiant": "d1"},
    ]
    assert bus["livraison"]["refuses_par_forme"] == 2


# -- 3. le rapport d'audit
# ----------------------------------------------------------------------------------------------------
def _audit(ev, af, bus, fin="2026-11-16T09:35:00+00:00", jours=7):
    return routines.rapport_audit(fin, jours, bus, ev.lire(), af.lire(), {"evenements": ev, "affaires": af})


def _questions(rapport):
    return {q["id"]: q for q in rapport["questions"]}


def test_un_audit_sans_attendu_dit_qu_il_n_a_rien_verifie_jamais_tout_va_bien():
    ev, af = _mondes()
    rapport = _audit(ev, af, routines.attendus_du_bus([]))
    q = _questions(rapport)["trace_des_evenements_livres"]
    assert (q["numerateur"], q["denominateur"], q["reponse"]) == (0, 0, None) and "rien n'a été vérifié" in q["note"]
    assert _questions(rapport)["jours_consolides"]["reponse"] is None  # aucun couple (affaire, jour) : ni oui ni non
    assert _questions(rapport)["fraicheur_memoire"]["heures"] is None


def test_l_audit_nomme_l_oubli_compte_les_traces_et_borne_la_liste():
    ev, af = _mondes()
    wct.memoriser_wct(_wct("w1", "l1"), ev)
    attendus = [_pub("m4.travaux_termines", _wct("w1", "l1"))] + [
        _pub("m4.travaux_termines", _wct(f"perdu-{i}", "l1")) for i in range(25)
    ]
    rapport = _audit(ev, af, routines.attendus_du_bus(attendus))
    q = _questions(rapport)["trace_des_evenements_livres"]
    assert (q["numerateur"], q["denominateur"], q["reponse"]) == (1, 26, False)
    assert rapport["nb_oublis"] == 25 and len(rapport["oublis"]) == routines.OUBLIS_MAX and rapport["oublis_omis"] == 5
    assert rapport["oublis"][0] == {
        "type_evenement": "m4.travaux_termines",
        "identifiant": "perdu-0",
        "verdict": "REJ-AUDIT-TRACE-ABSENTE",
    }


def test_une_chaine_alteree_est_dite_non_intacte():
    ev, af = _mondes()
    _lead(ev, "l1")
    _lead(ev, "l2")
    assert _questions(_audit(ev, af, routines.attendus_du_bus([])))["chaines_intactes"]["reponse"] is True
    ev._chain[0]["lead_id"] = "falsifie"  # altération silencieuse d'un maillon
    assert _questions(_audit(ev, af, routines.attendus_du_bus([])))["chaines_intactes"]["reponse"] is False


def test_les_jours_a_consolider_sont_comptes_dans_la_fenetre_avant_le_jour_de_l_audit_seulement():
    ev, af = _mondes()
    _lead(ev, "a1", "2026-11-08T10:00:00-05:00")  # hors fenêtre (7 jours finissant le 16 : à partir du 9)
    _lead(ev, "a1", "2026-11-09T10:00:00-05:00")
    _lead(ev, "a2", "2026-11-12T10:00:00-05:00")
    _lead(ev, "a3", "2026-11-16T08:00:00-05:00")  # le jour de l'audit n'est pas encore à consolider
    consolidation.consolider_affaire("a1", "2026-11-09", CONSO, ev, af)
    q = _questions(_audit(ev, af, routines.attendus_du_bus([])))["jours_consolides"]
    assert (q["numerateur"], q["denominateur"], q["reponse"], q["plus_ancien_non_consolide"]) == (
        1,
        2,
        False,
        "2026-11-12",
    )


def test_les_revisions_en_attente_et_la_fraicheur_sont_des_comptes_pas_des_scores():
    ev, af = _mondes()
    _lead(ev, "a1")
    _lead(ev, "a2")
    consolidation.consolider_affaire("a1", JOUR, CONSO, ev, af)
    consolidation.consolider_affaire("a2", JOUR, CONSO, ev, af)
    fait_a, fait_b = [m["ligne_id"] for m in af.lire()]
    signal, _ = revision.signaler_revision(af, fait_a, fait_b, CONSO)
    revision.signaler_revision(af, fait_b, fait_a, CONSO)
    assert _questions(_audit(ev, af, routines.attendus_du_bus([])))["revisions_en_attente"]["valeur"] == 2
    revision.arbitrer_revision(af, signal["ligne_id"], "distincts_confirmes", CONSO)
    questions = _questions(_audit(ev, af, routines.attendus_du_bus([]), fin="2026-11-09T22:00:00-05:00"))
    assert questions["revisions_en_attente"]["valeur"] == 1
    assert questions["fraicheur_memoire"]["heures"] == 8  # dernier événement à 14 h, audit à 22 h


# -- 4. les KPI
# --------------------------------------------------------------------------------------------------------------------
def test_les_cinq_kpi_du_manifeste_sont_tous_la_chacun_calcule_ou_dit_non_calculable():
    ev, af = _mondes()
    resultat = routines.kpis("2026-11-10", "2026-11-10T05:00:00+00:00", "2026-11-11T05:00:00+00:00", af.lire(), [])
    assert set(resultat["kpis"]) == set(routines.kpi_ids()) and len(routines.kpi_ids()) == 5
    calculables = {k for k, v in resultat["kpis"].items() if v["calculable"]}
    assert calculables == {"nb_affaires_consolidees_jour"}  # un vrai zéro, pas un manque
    assert resultat["kpis"]["nb_affaires_consolidees_jour"]["valeur"] == 0


def test_les_affaires_consolidees_du_cycle_sont_celles_dont_un_fait_est_ecrit_dans_la_journee_locale():
    ev, af = _mondes()
    for lead in ("a1", "a2", "a3"):
        _lead(ev, lead)
    consolidation.consolider_affaire("a1", JOUR, "2026-11-10T03:05:00-05:00", ev, af)  # 08:05 UTC : dans le cycle
    consolidation.consolider_affaire("a2", JOUR, "2026-11-10T03:05:00-05:00", ev, af)
    consolidation.consolider_affaire("a3", JOUR, "2026-11-09T23:59:59-05:00", ev, af)  # 04:59:59 UTC : veille du cycle
    wct.memoriser_wct(_wct("tard", "a1", horodatage=EVT), ev)
    consolidation.consolider_affaire(
        "a1", JOUR, "2026-11-10T04:00:00-05:00", ev, af
    )  # a1 deux fois : une seule affaire
    cycle = ("2026-11-10T05:00:00+00:00", "2026-11-11T05:00:00+00:00")
    assert routines.kpis("2026-11-10", *cycle, af.lire(), [])["kpis"]["nb_affaires_consolidees_jour"]["valeur"] == 2
    fin_exclue = ("2026-11-10T05:00:00+00:00", "2026-11-10T08:05:00+00:00")  # [debut, fin[ : fin exclue
    assert (
        routines.kpis("2026-11-10", *fin_exclue, af.lire(), [])["kpis"]["nb_affaires_consolidees_jour"]["valeur"] == 0
    )


def test_le_taux_de_revisions_arbitrees_a_son_numerateur_son_denominateur_et_ignore_les_traces_de_preflight():
    ev, af = _mondes()
    _lead(ev, "a1")
    consolidation.consolider_affaire("a1", JOUR, CONSO, ev, af)
    wct.memoriser_wct(_wct("w", "a1"), ev)
    consolidation.consolider_affaire("a1", JOUR, "2026-11-10T04:00:00-05:00", ev, af)
    f1, f2 = [m["ligne_id"] for m in af.lire()][:2]
    s1, _ = revision.signaler_revision(af, f1, f2, CONSO)
    revision.signaler_revision(af, f2, f1, CONSO)
    s3, _ = revision.signaler_revision(af, f1, f2, CONSO)
    revision.arbitrer_revision(af, s1["ligne_id"], "obsolete_marquee", CONSO)
    revision.arbitrer_revision(
        af, s1["ligne_id"], "distincts_confirmes", CONSO
    )  # deux arbitrages : un seul signalement arbitré
    af.ajouter(
        {
            "type_entree": "revision_signalee",
            "horodatage": CONSO,
            "code_verdict": "REJ-CONTEXTE-STRUCTURE-INVALIDE",
            "verdict": {"code": "x"},
            "statut": "en_attente",
        }
    )  # trace de préflight : n'est PAS un signalement
    assert s3 is not None
    cycle = ("2026-11-10T05:00:00+00:00", "2026-11-11T05:00:00+00:00")
    kpis = routines.kpis("2026-11-10", *cycle, af.lire(), [])["kpis"]
    assert kpis["taux_revisions_arbitrees"] == {
        "calculable": True,
        "valeur_pct": 33.3,
        "numerateur": 1,
        "denominateur": 3,
    }
    assert (
        kpis["taux_preflight_insuffisant"]["refus_traces"] == 1
        and kpis["taux_preflight_insuffisant"]["calculable"] is False
    )


def test_les_oublis_du_dernier_audit_alimentent_le_kpi():
    ev, af = _mondes()
    rapports = [
        {
            "type_entree": routines.TYPE_RAPPORT,
            "genre": "audit_non_oubli",
            "fin": "2026-11-09T09:35:00+00:00",
            "contenu": {"nb_oublis": 4},
        },
        {"type_entree": routines.TYPE_RAPPORT, "genre": "kpis", "fin": "x", "contenu": {}},
        {
            "type_entree": routines.TYPE_RAPPORT,
            "genre": "audit_non_oubli",
            "fin": "2026-11-16T09:35:00+00:00",
            "contenu": {"nb_oublis": 1},
        },
    ]
    cycle = ("2026-11-10T05:00:00+00:00", "2026-11-11T05:00:00+00:00")
    kpi = routines.kpis("2026-11-10", *cycle, af.lire(), rapports)["kpis"]["nb_oublis_detectes_audit"]
    assert kpi == {"calculable": True, "valeur": 1, "audit_du": "2026-11-16T09:35:00+00:00"}


@pytest.mark.parametrize("valeur", ["2026-11-10", "2026-11-10T05:00:00", "", None, 3])
def test_un_instant_sans_fuseau_ou_illisible_est_refuse(valeur):
    with pytest.raises(ValueError, match="REJ-HORODATAGE-INVALIDE"):
        routines.instant(valeur)


def test_l_empreinte_ne_depend_pas_de_l_ordre_des_cles():
    assert routines.empreinte({"a": 1, "b": [1, 2]}) == routines.empreinte({"b": [1, 2], "a": 1})
    assert routines.empreinte({"a": 1}) != routines.empreinte({"a": 2})
