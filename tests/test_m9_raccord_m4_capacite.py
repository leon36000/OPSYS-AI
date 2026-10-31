"""Raccord M9 -> M4 : `m4.capacite_equipe` du VRAI M4 (solveur, registre durable, profil `entreprise.yaml`), port privé.

M4 est alimenté par ses propres outils (inscription, coordonnées confirmées, cédule proposée puis appliquée, dates
confirmées), via les fixtures de ses propres tests chargées telles quelles ; M9 capture ensuite la lecture par le port
privé `opsys.lecteurs_m9` sous l'identité admin console. Données fictives."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml
from m9_strategic_intelligence import capture_strategique as cs
from m9_strategic_intelligence import dossier_strategique as ds
from m9_strategic_intelligence import priorisation

from opsys import equipes as equipes_entreprise
from opsys.contexte import IdentiteAppelante

RACINE = Path(__file__).resolve().parents[1]


def _charger(nom: str, chemin: Path):
    spec = importlib.util.spec_from_file_location(nom, chemin)
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    spec.loader.exec_module(module)
    return module


aide = _charger("m9_raccord_m4_aide", RACINE / "departments/m04-field-ops/tests/test_cedule_tournees_outils.py")
H = _charger("m9_producteurs_b", Path(__file__).with_name("m9_producteurs_b.py"))
instance, par_nom, interventions = aide.instance, aide.par_nom, aide.interventions  # fixtures de M4, réutilisées
FICTIF = True
M4 = "m04-field-ops"
LECTURE = "m4.capacite_equipe"
LUNDI = "2030-06-03"
REFERENCE = "2030-06-02T09:30:00-04:00"
RECU = "2030-06-02T14:00:00Z"
ARGS = {"debut_semaine": LUNDI, "horodatage_reference": REFERENCE}


def _ecrire_profil(dossier, equipes):
    brut = {"liste": [{**e, "membres": [f"{e['id'].replace('-', '.')}.fictif"]} for e in equipes]}
    (dossier / "home" / "entreprise.yaml").write_text(
        yaml.safe_dump({"equipes": equipes_entreprise.normaliser_equipes(brut)}, allow_unicode=True), encoding="utf-8"
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


def _minutes_planifiees(plan):
    proposition = next(m for m in aide._du_type("cedule_proposee") if m["plan_id"] == plan)
    return sum(v["fin_min"] - v["debut_min"] for route in proposition["sortie"]["plan"] for v in route["visites"])


def _capture(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["capture"]


def _dossier(captures, connaissance="2030-06-03T00:00:00Z"):
    return ds.construire(
        captures,
        question="Quelle capacité ?",
        domaines=["capacite"],
        reference="2030-06-02T14:00:00Z",
        connaissance=connaissance,
        attendues=[LECTURE],
    )


def test_m4_sans_profil_ni_cedule_reel_est_non_calculable_sans_aucune_valeur(par_nom):
    cap = H.capacites(M4)
    capture = _capture(H.capturer(cap, H.ADMIN, LECTURE, dict(ARGS), RECU))
    assert (capture["verdict"], capture["code"], capture["complete"]) == ("ACCEPTEE", None, False)
    charge = H.page(0)["resultat"]["resultat"]
    assert charge["calculable"] is False and charge["equipes"] == [] and "heures_disponibles" not in charge
    dossier = _dossier(H.captures_stockees())
    assert dossier["couverture"]["lectures"][0]["statut"] == "PARTIELLE"
    assert not [a for a in dossier["faits"] if "heures" in a.rsplit(".", 1)[-1]]
    assert dossier["faits"][f"{LECTURE}#0:p0.resultat.resultat.manque[0]"] == "cedule_non_appliquee"


def test_m4_calculable_reel_est_cite_en_heures_declarees_date_et_sans_contradiction(par_nom, interventions, instance):
    _ecrire_profil(instance, aide._equipes())
    plan = _dater(par_nom, interventions)
    attendu = _minutes_planifiees(plan)
    cap = H.capacites(M4)
    premiere = _capture(H.capturer(cap, H.ADMIN, LECTURE, dict(ARGS), RECU))
    _capture(H.capturer(cap, H.ADMIN, LECTURE, dict(ARGS), "2030-06-02T14:00:05Z"))
    assert (premiere["verdict"], premiere["complete"]) == ("ACCEPTEE", True)
    assert premiere["instants_metier"]["nombre"] == 1 and premiere["reference"] == "2030-06-02T13:30:00Z"
    chaine = H.captures_stockees()
    assert cs.contradictions(chaine) == []
    dossier = _dossier(chaine)
    racine = f"{LECTURE}#1:p0.resultat.resultat"
    assert dossier["faits"][f"{racine}.unite"] == "heures_declarees"
    assert dossier["faits"][f"{racine}.heures_disponibles"] == "18.00"
    assert dossier["faits"][f"{racine}.heures_planifiees"] == H.page(1)["resultat"]["resultat"]["heures_planifiees"]
    assert H.page(1)["resultat"]["resultat"]["minutes_planifiees"] == attendu > 0
    assert dossier["couverture"]["lectures"][0]["statut"] == "PRESENTE"
    # M9 ne convertit jamais ces heures en jours-personnes : l'allocation les refuse comme capacité.
    candidat = [
        {
            "id": "c1",
            "libelle": "Rappel",
            "origine": "DECLAREE_PAR_LA_PERSONNE",
            "impact": 5,
            "urgence": 5,
            "confiance": 4,
            "effort_jours_personnes": "1",
        }
    ]
    with pytest.raises(ValueError, match="REJ-PRIORITE-UNITE"):
        priorisation.allouer(candidat, capacite="18.00", source_capacite=f"{racine}.heures_disponibles")


@pytest.mark.parametrize(
    "identite",
    [
        None,
        IdentiteAppelante("vendeur.fictif", "seller", source="console"),
        IdentiteAppelante("marc.fictif", "employee", source="console"),
        IdentiteAppelante("fantome.fictif", "admin", source="console"),
    ],
)
def test_m4_refus_d_identite_avant_toute_lecture(par_nom, identite):
    cap = H.capacites(M4)
    reponse = H.capturer(cap, identite, LECTURE, dict(ARGS), RECU)
    assert reponse["ok"] is False or reponse["resultat"].get("accepte") is False
    assert H.captures_stockees() == []


def test_m4_semaine_invalide_est_une_erreur_conservee_jamais_une_capacite(par_nom):
    cap = H.capacites(M4)
    capture = _capture(H.capturer(cap, H.ADMIN, LECTURE, {"debut_semaine": "2030-06-04"}, RECU))
    assert capture["verdict"] in {"REFUSEE", "ERREUR"} and capture["complete"] is False
    assert _dossier(H.captures_stockees())["faits"] == {}
