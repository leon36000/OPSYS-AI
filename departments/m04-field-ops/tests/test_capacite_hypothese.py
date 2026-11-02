"""`m4.projection_capacite` : la capacité sous hypothèses déclarées, calculée par M4 avec un reçu rejouable (fictif).

Calcul pur (`capacite_hypothese`) puis les VRAIS outils `m4_projeter_capacite_hypotheses` et
`m4_verifier_recu_projection_capacite` sur le vrai profil `entreprise.yaml`. Données fictives (`fictif: true`)."""

import copy
import importlib.util
from pathlib import Path

import pytest
import yaml
from m4_field_ops import capacite_hypothese as ch
from m4_field_ops.outils import outils

from opsys import equipes as equipes_entreprise
from opsys.outils import Autonomie

_spec = importlib.util.spec_from_file_location(
    "fixture_projection_sql", Path(__file__).with_name("test_cedule_tournees_outils.py")
)
aide = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(aide)
instance, par_nom, interventions = aide.instance, aide.par_nom, aide.interventions
FICTIF = True
LUNDI = "2030-06-10"
REFERENCE = "2030-06-09T09:30:00-04:00"
_PLAGE = [{"debut": "07:00", "fin": "15:00"}]
_SEMAINE = {
    "fuseau": "America/Montreal",
    "lundi": _PLAGE,
    "mardi": _PLAGE,
    "mercredi": _PLAGE,
    "jeudi": _PLAGE,
    "vendredi": _PLAGE,
    "samedi": [],
    "dimanche": [],
}


def _base(effectif_a=2, effectif_b=3, duree=480):
    return {
        "unite": "heures_declarees",
        "semaine_debut": LUNDI,
        "portee": "semaine_type",
        "duree_jour_personne_minutes": duree,
        "equipes": [
            {
                "equipe_id": "eq-a",
                "minutes_disponibles": 2400,
                "minutes_planifiees": 1200,
                "effectif_planifie": effectif_a,
                "perte_jours_bloques_minutes": 480,
            },
            {
                "equipe_id": "eq-b",
                "minutes_disponibles": 2400,
                "minutes_planifiees": 600,
                "effectif_planifie": effectif_b,
                "perte_jours_bloques_minutes": 480,
            },
        ],
    }


def _lignes(resultat):
    return {ligne["equipe_id"]: ligne for ligne in resultat["equipes"]}


# ------------------------------------------------------------------------------------------------ calcul pur
def test_absences_converties_en_heures_d_equipe_par_la_conversion_declaree_seulement():
    r = ch.appliquer(_base(), {"absences": [{"equipe_id": "eq-a", "personnes": 1, "jours": 2}]})
    a = _lignes(r)["eq-a"]
    # 1 personne × 2 jours × 480 min / effectif 2 = 480 min = 8 h d'équipe perdues sur 40 h
    assert a["perte_absences_heures"] == "8.00" and a["heures_disponibles_projetees"] == "32.00"
    assert a["heures_planifiees_projetees"] == "20.00" and a["solde_heures"] == "12.00" and a["statut"] == "SUFFISANTE"
    assert a["utilisation_pct"] == "62.5"
    b = _lignes(r)["eq-b"]
    assert b["perte_absences_heures"] == "0.00" and b["heures_disponibles_projetees"] == "40.00"


def test_deux_employes_absents_trois_jours_font_basculer_l_equipe_en_surcharge():
    r = ch.appliquer(
        _base(), {"absences": [{"equipe_id": "eq-a", "personnes": 2, "jours": 3}], "hausse_demande_pct": "50"}
    )
    a = _lignes(r)["eq-a"]
    # 2 × 3 × 480 / 2 = 1440 min = 24 h perdues ; disponibles 40 − 24 = 16 h ; planifiées 20 × 1,5 = 30 h
    assert a["perte_absences_heures"] == "24.00" and a["heures_disponibles_projetees"] == "16.00"
    assert a["heures_planifiees_projetees"] == "30.00" and a["solde_heures"] == "-14.00"
    assert a["statut"] == "SURCHARGE" and a["utilisation_pct"] == "187.5"
    assert r["equipes_en_surcharge"] == ["eq-a"]


def test_planifie_egal_au_disponible_projete_n_est_pas_une_surcharge_et_un_minute_de_plus_en_est_une():
    egal = ch.appliquer(_base(), {"hausse_demande_pct": "100"})  # eq-a : 2400 min planifiées = 2400 disponibles
    a = _lignes(egal)["eq-a"]
    assert a["solde_heures"] == "0.00" and a["statut"] == "SUFFISANTE" and a["utilisation_pct"] == "100.0"
    assert "eq-a" not in egal["equipes_en_surcharge"]
    base = _base()
    base["equipes"][0]["minutes_planifiees"] = 1201
    plus = ch.appliquer(base, {"hausse_demande_pct": "100"})
    assert _lignes(plus)["eq-a"]["statut"] == "SURCHARGE" and "eq-a" in plus["equipes_en_surcharge"]


def test_jours_bloques_retirent_les_heures_de_chaque_equipe_et_la_hausse_les_planifiees():
    r = ch.appliquer(_base(), {"jours_bloques": ["2030-06-11"], "hausse_demande_pct": "10.5"})
    a, b = _lignes(r)["eq-a"], _lignes(r)["eq-b"]
    assert a["perte_jours_bloques_heures"] == "8.00" and a["heures_disponibles_projetees"] == "32.00"
    assert b["heures_planifiees_projetees"] == "11.05" and b["heures_disponibles_projetees"] == "32.00"
    sans_blocage = ch.appliquer(_base(), {"hausse_demande_pct": "0"})
    assert _lignes(sans_blocage)["eq-a"]["perte_jours_bloques_heures"] == "0.00", "pas d'hypothèse, pas de perte"


def test_capacite_epuisee_est_dite_jamais_ramenee_a_zero_en_silence():
    r = ch.appliquer(_base(), {"absences": [{"equipe_id": "eq-a", "personnes": 50, "jours": 7}]})
    a = _lignes(r)["eq-a"]
    assert a["capacite_epuisee"] is True and a["heures_disponibles_projetees"] == "0.00"
    assert a["statut"] == "SURCHARGE" and a["utilisation_pct"] is None
    assert _lignes(r)["eq-b"]["capacite_epuisee"] is False
    juste = _lignes(ch.appliquer(_base(), {"absences": [{"equipe_id": "eq-a", "personnes": 2, "jours": 5}]}))["eq-a"]
    assert juste["heures_disponibles_projetees"] == "0.00" and juste["capacite_epuisee"] is True, "zéro exact = épuisée"
    assert juste["statut"] == "SURCHARGE", "des heures planifiées sans aucune heure disponible"


@pytest.mark.parametrize(
    ("base", "manque"),
    [
        (_base(effectif_a=None), ["effectif_planifie_non_declare:eq-a"]),
        (_base(duree=None), ["duree_jour_personne_minutes_non_declaree"]),
        (
            _base(effectif_a=None, duree=None),
            ["duree_jour_personne_minutes_non_declaree", "effectif_planifie_non_declare:eq-a"],
        ),
    ],
)
def test_sans_effectif_ou_duree_declares_aucun_chiffre_et_le_manque_est_nomme(base, manque):
    r = ch.appliquer(base, {"absences": [{"equipe_id": "eq-a", "personnes": 1, "jours": 1}]})
    assert r == {"calculable": False, "manque": manque, "equipes": []}
    # sans absence, la conversion n'est pas requise : la projection se calcule
    assert ch.appliquer(base, {"hausse_demande_pct": "5"})["calculable"] is True


@pytest.mark.parametrize(
    "hypotheses",
    [
        {},
        {"inconnue": 1},
        {"absences": []},
        {"absences": [{"equipe_id": "eq-z", "personnes": 1, "jours": 1}]},
        {"absences": [{"equipe_id": "eq-a", "personnes": 0, "jours": 1}]},
        {"absences": [{"equipe_id": "eq-a", "personnes": 1, "jours": 8}]},
        {"absences": [{"equipe_id": "eq-a", "personnes": True, "jours": 1}]},
        {"absences": [{"equipe_id": "eq-a", "personnes": 1, "jours": 1, "nom": "x"}]},
        {"jours_bloques": ["2030-06-17"]},
        {"jours_bloques": []},
        {"jours_bloques": ["2030-06-11", "2030-06-11"]},
        {"hausse_demande_pct": 10},
        {"hausse_demande_pct": "-1"},
        {"hausse_demande_pct": "1001"},
        {"hausse_demande_pct": "NaN"},
        {"hausse_demande_pct": "1.234"},
    ],
)
def test_hypotheses_hors_forme_refusees_avec_un_refus_nomme(hypotheses):
    with pytest.raises(ValueError, match="REJ-PROJECTION-INVALIDE"):
        ch.valider_hypotheses(hypotheses, portee="semaine_type", semaine_debut=LUNDI, equipes={"eq-a", "eq-b"})


def test_jours_bloques_exigent_la_portee_semaine_type():
    with pytest.raises(ValueError, match="semaine_type"):
        ch.valider_hypotheses(
            {"jours_bloques": [LUNDI]}, portee="journees_datees_seulement", semaine_debut=LUNDI, equipes={"eq-a"}
        )


def test_le_recu_se_rejoue_a_partir_de_ses_seules_entrees_et_toute_retouche_est_vue():
    recu = ch.construire_recu(
        _base(),
        {"hausse_demande_pct": "20"},
        {"profil_empreinte": "e" * 64, "registre_tete": "ligne-1", "lu_a": REFERENCE},
    )
    assert ch.verifier_recu(recu) == {
        "empreinte_valide": True,
        "rejoue": True,
        "identique": True,
        "empreinte": recu["empreinte"],
    }
    retouche = copy.deepcopy(recu)
    retouche["resultat"]["equipes"][0]["heures_planifiees_projetees"] = "1.00"
    verdict = ch.verifier_recu(retouche)
    assert verdict["identique"] is False and verdict["empreinte_valide"] is False
    base_retouchee = copy.deepcopy(recu)
    base_retouchee["entrees"]["base"]["equipes"][0]["minutes_disponibles"] = 99
    assert ch.verifier_recu(base_retouchee)["identique"] is False
    empreinte_refaite = copy.deepcopy(base_retouchee)
    empreinte_refaite["empreinte"] = ch._empreinte(
        ch.METHODE, empreinte_refaite["entrees"], empreinte_refaite["resultat"]
    )
    verdict = ch.verifier_recu(empreinte_refaite)
    assert verdict["empreinte_valide"] is True and verdict["identique"] is False, "le résultat ne suit plus la base"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r.pop("empreinte"),
        lambda r: r.update(methode="autre"),
        lambda r: r["entrees"].pop("sources"),
        lambda r: r["entrees"]["base"].pop("equipes"),
        lambda r: r["entrees"]["base"]["equipes"][0].update(effectif_planifie=0, perte_jours_bloques_minutes="x"),
        lambda r: r["entrees"].update(
            hypotheses={"absences": [{"equipe_id": "eq-a", "personnes": 1, "jours": 1}], "x": 1}
        ),
        lambda r: r["entrees"]["hypotheses"].update(absences=[{"equipe_id": "eq-a"}]),
    ],
)
def test_un_recu_mal_forme_est_refuse_jamais_rejoue_au_hasard(mutation):
    recu = ch.construire_recu(_base(), {"absences": [{"equipe_id": "eq-a", "personnes": 1, "jours": 1}]}, {})
    mutation(recu)
    with pytest.raises(ValueError, match="REJ-PROJECTION-INVALIDE"):
        ch.verifier_recu(recu)


# ----------------------------------------------------------------------------------------- les vrais outils
def _ecrire_profil(instance_dir, *, effectif=2, duree=480, **extra):
    equipes = [
        {
            **e,
            "membres": [f"{e['id'].replace('-', '.')}.fictif"],
            "semaine_type": _SEMAINE,
            **({"effectif_planifie": effectif} if effectif else {}),
        }
        for e in aide._equipes()
    ]
    brut = {
        "liste": equipes,
        "feries": {"annees": [2030], "jours": []},
        **({"duree_jour_personne_minutes": duree} if duree else {}),
        **extra,
    }
    (instance_dir / "home" / "entreprise.yaml").write_text(
        yaml.safe_dump({"equipes": equipes_entreprise.normaliser_equipes(brut)}, allow_unicode=True), encoding="utf-8"
    )


def _projeter(par_nom, hypotheses, acteur=aide.ADMIN, semaine=LUNDI, **extra):
    return aide._appeler(
        par_nom,
        "m4_projeter_capacite_hypotheses",
        {"debut_semaine": semaine, "hypotheses": hypotheses, **extra},
        acteur,
    )


def _dater(par_nom, interventions):
    plan = aide._resultat(aide._proposer(par_nom, interventions))["plan_id"]
    aide._resultat(aide._appliquer(par_nom, plan))
    aide._resultat(
        aide._appeler(
            par_nom,
            "m4_confirmer_dates_cedule",
            {"plan_id": plan, "calendrier": {"0": LUNDI}, "revision_attendue": 0},
            aide.ADMIN,
        )
    )
    return plan


def test_les_deux_outils_sont_des_lectures_T0_sans_aucun_droit_d_appareil():
    for nom in ("m4_projeter_capacite_hypotheses", "m4_verifier_recu_projection_capacite"):
        outil = next(o for o in outils() if o.nom == nom)
        assert outil.autonomie is Autonomie.T0 and outil.roles_appareil == frozenset()
        assert outil.parametres["additionalProperties"] is False and len(outil.description) <= 1024


def test_sans_profil_la_projection_est_non_calculable_sans_aucun_chiffre(par_nom, interventions):
    _dater(par_nom, interventions)
    avant = aide._etat()
    r = aide._resultat(_projeter(par_nom, {"hausse_demande_pct": "10"}))
    assert r["calculable"] is False and r["recu"] is None and r["equipes"] == []
    assert r["manque"][0] == "base_non_calculable" and "profil_equipes_non_declare" in r["manque"]
    assert aide._etat() == avant


def test_deux_employes_absents_sur_le_vrai_profil_chiffres_par_m4_avec_un_recu_rejouable(
    par_nom, interventions, instance
):
    _ecrire_profil(instance)
    _dater(par_nom, interventions)
    avant = aide._etat()
    r = aide._resultat(
        _projeter(
            par_nom,
            {"absences": [{"equipe_id": "eq-a", "personnes": 2, "jours": 2}]},
            horodatage_reference=REFERENCE,
            portee="semaine_type",
        )
    )
    assert r["calculable"] is True and r["portee"] == "semaine_type" and r["lu_a"] == REFERENCE
    a = _lignes(r)["eq-a"]
    # 5 jours × 8 h = 40 h ; 2 personnes × 2 jours × 480 / effectif 2 = 960 min = 16 h perdues
    assert a["heures_disponibles_base"] == "40.00" and a["perte_absences_heures"] == "16.00"
    assert a["heures_disponibles_projetees"] == "24.00"
    assert _lignes(r)["eq-b"]["heures_disponibles_projetees"] == "40.00"
    recu = r["recu"]
    assert recu["methode"] == "m4.projection_capacite.v1" and len(recu["empreinte"]) == 64
    assert recu["entrees"]["sources"]["profil_empreinte"] and recu["entrees"]["sources"]["lu_a"] == REFERENCE
    verification = aide._resultat(
        aide._appeler(par_nom, "m4_verifier_recu_projection_capacite", {"recu": recu}, aide.ADMIN)
    )
    assert verification["identique"] is True and verification["empreinte"] == recu["empreinte"]
    rejoue = aide._resultat(
        _projeter(
            par_nom,
            {"absences": [{"equipe_id": "eq-a", "personnes": 2, "jours": 2}]},
            horodatage_reference=REFERENCE,
            portee="semaine_type",
        )
    )
    assert rejoue["recu"]["empreinte"] == recu["empreinte"], "même état, mêmes hypothèses, même empreinte"
    assert aide._etat() == avant, "lecture pure : rien n'est écrit"


def test_jour_bloque_recalcule_la_semaine_type_comme_un_conge_de_toutes_les_equipes(par_nom, interventions, instance):
    _ecrire_profil(
        instance, conges=[{"equipes": ["eq-a"], "du": "2030-06-12", "au": "2030-06-12", "motif": "formation"}]
    )
    _dater(par_nom, interventions)
    r = aide._resultat(_projeter(par_nom, {"jours_bloques": ["2030-06-11", "2030-06-12"]}, portee="semaine_type"))
    a, b = _lignes(r)["eq-a"], _lignes(r)["eq-b"]
    # eq-a : 4 jours de base (congé le 12) ; le 12 est déjà à zéro : seul le 11 est perdu. eq-b : 5 jours, deux perdus.
    assert a["heures_disponibles_base"] == "32.00" and a["perte_jours_bloques_heures"] == "8.00"
    assert b["heures_disponibles_base"] == "40.00" and b["perte_jours_bloques_heures"] == "16.00"
    assert b["heures_disponibles_projetees"] == "24.00"


def test_sans_effectif_declare_les_absences_ne_sont_pas_chiffrees(par_nom, interventions, instance):
    _ecrire_profil(instance, effectif=None)
    _dater(par_nom, interventions)
    r = aide._resultat(
        _projeter(par_nom, {"absences": [{"equipe_id": "eq-a", "personnes": 1, "jours": 1}]}, portee="semaine_type")
    )
    assert r["calculable"] is False and r["manque"] == ["effectif_planifie_non_declare:eq-a"] and r["equipes"] == []
    seulement_demande = aide._resultat(_projeter(par_nom, {"hausse_demande_pct": "25"}, portee="semaine_type"))
    assert seulement_demande["calculable"] is True


def test_refus_hypotheses_invalides_portee_datee_et_identites_sans_ecriture(par_nom, interventions, instance):
    _ecrire_profil(instance)
    _dater(par_nom, interventions)
    avant = aide._etat()
    for hypotheses, extra in (
        ({"jours_bloques": ["2030-06-11"]}, {"portee": "journees_datees_seulement"}),
        ({"absences": [{"equipe_id": "eq-z", "personnes": 1, "jours": 1}]}, {"portee": "semaine_type"}),
        ({"hausse_demande_pct": "-3"}, {"portee": "semaine_type"}),
    ):
        reponse = _projeter(par_nom, hypotheses, **extra)
        assert aide._code_refus(reponse) == "REJ-CONTRAT-INVALIDE", (hypotheses, reponse)
    for acteur in (aide.VENDEUR, aide.MARC, aide.FANTOME):
        reponse = aide._appeler(
            par_nom,
            "m4_projeter_capacite_hypotheses",
            {"debut_semaine": LUNDI, "hypotheses": {"hausse_demande_pct": "1"}},
            acteur,
        )
        assert aide._code_refus(reponse) == "REJ-IDENTITE-APPAREIL-INVALIDE"
        verification = aide._appeler(par_nom, "m4_verifier_recu_projection_capacite", {"recu": {}}, acteur)
        assert aide._code_refus(verification) == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert aide._etat() == avant
