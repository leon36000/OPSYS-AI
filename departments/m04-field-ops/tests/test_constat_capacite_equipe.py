"""D2 : M4 publie, pour M8, la capacité d'une semaine (`m4.capacite_equipe_constatee`).

Vrais outils, vraie base migrée, vrai profil `entreprise.yaml`, vrai bus (outbox). Prouve : deux totaux (heures d'équipe
DÉCLARÉES, heures de cédule planifiées) et rien d'autre ; une semaine non calculable ne porte aucun total (absence n'est
jamais zéro) et dit ses causes en codes fermés sans suffixe ; rejouer le même constat ne publie rien ; aucune équipe ni
aucun
nom ne part  ; le calcul est celui de la lecture T0. Données FICTIVES.
"""

import importlib.util
import json
from pathlib import Path

import yaml
from m4_field_ops.outils import outils
from sqlalchemy import select

from opsys import equipes as equipes_entreprise
from opsys import stockage
from opsys.outils import Autonomie, Niveau
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS

_spec = importlib.util.spec_from_file_location(
    "fixture_constat_capacite", Path(__file__).with_name("test_cedule_tournees_outils.py")
)
aide = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(aide)
instance, par_nom, interventions = aide.instance, aide.par_nom, aide.interventions
FICTIF = True
TYPE = "m4.capacite_equipe_constatee"
LUNDI = "2030-06-03"
REFERENCE = "2030-06-02T09:30:00-04:00"


def _ecrire_profil(instance_dir, equipes):
    brut = {"liste": [{**e, "membres": [f"{e['id'].replace('-', '.')}.fictif"]} for e in equipes]}
    (instance_dir / "home" / "entreprise.yaml").write_text(
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


def _constater(par_nom, acteur=None, semaine=LUNDI, portee="journees_datees_seulement", horodatage=REFERENCE):
    return aide._appeler(
        par_nom,
        "m4_constater_capacite_equipe",
        {"debut_semaine": semaine, "portee": portee, "horodatage": horodatage},
        acteur,
    )


def _publies():
    with stockage.transaction() as cnx:
        lignes = cnx.execute(
            select(EVENEMENTS_SORTANTS.c.evenement_id, EVENEMENTS_SORTANTS.c.charge)
            .where(EVENEMENTS_SORTANTS.c.type_evenement == TYPE)
            .order_by(EVENEMENTS_SORTANTS.c.evenement_id)
        ).all()
    return [(i, codec.decoder(c)) for i, c in lignes]


def test_agent_seulement_aucun_droit_d_appareil():
    outil = next(o for o in outils() if o.nom == "m4_constater_capacite_equipe")
    assert (outil.autonomie, outil.niveau_effectif) == (Autonomie.T1, Niveau.N2) and not outil.roles_appareil
    assert outil.parametres["required"] == ["debut_semaine", "portee", "horodatage"]
    assert outil.parametres["additionalProperties"] is False


def test_profil_et_cedule_datee_publient_les_deux_totaux_et_rien_d_autre(par_nom, interventions, instance):
    _ecrire_profil(instance, aide._equipes())
    _dater(par_nom, interventions)
    lue = aide._resultat(
        aide._appeler(
            par_nom, "m4_lire_capacite_equipe", {"debut_semaine": LUNDI, "horodatage_reference": REFERENCE}, aide.ADMIN
        )
    )
    retour = aide._resultat(_constater(par_nom))
    assert retour["publie"] is True and retour["calculable"] is True and retour["manque"] == []
    ((identifiant, charge),) = _publies()
    assert identifiant == retour["evenement_id"] == charge["evenement_id"]
    assert charge["heures_disponibles"] == lue["heures_disponibles"] and float(charge["heures_disponibles"]) > 0
    assert charge["heures_planifiees"] == lue["heures_planifiees"] and float(charge["heures_planifiees"]) > 0
    assert charge["semaine_debut"] == LUNDI and charge["portee"] == "journees_datees_seulement"
    assert charge["manque"] == [] and charge["constate_le"] == REFERENCE
    texte = json.dumps(charge, ensure_ascii=False)
    assert "eq-a" not in texte and "eq-b" not in texte and ".fictif" not in texte
    assert set(charge) == {
        "evenement_id",
        "semaine_debut",
        "portee",
        "calculable",
        "heures_disponibles",
        "heures_planifiees",
        "manque",
        "constate_le",
        "version_donnees",
    }


def test_semaine_non_calculable_ne_porte_aucun_total_et_des_codes_sans_suffixe(par_nom, interventions, instance):
    _ecrire_profil(instance, aide._equipes())
    aide._resultat(aide._appliquer(par_nom, aide._resultat(aide._proposer(par_nom, interventions))["plan_id"]))
    retour = aide._resultat(_constater(par_nom))
    assert retour["calculable"] is False
    ((_, charge),) = _publies()
    assert (
        charge["calculable"] is False and charge["heures_disponibles"] is None and charge["heures_planifiees"] is None
    )
    assert charge["manque"] == sorted(charge["manque"]) and charge["manque"]
    assert all(":" not in code for code in charge["manque"])
    assert "interventions_planifiees_sans_date" in charge["manque"]


def test_sans_profil_declare_la_capacite_n_est_pas_zero(par_nom, interventions):
    _dater(par_nom, interventions)
    aide._resultat(_constater(par_nom))
    ((_, charge),) = _publies()
    assert charge["calculable"] is False and charge["manque"] == ["profil_equipes_non_declare"]
    assert charge["heures_disponibles"] is None and charge["heures_planifiees"] is None


def test_rejouer_le_meme_constat_ne_publie_rien_un_autre_instant_est_un_evenement_de_plus(
    par_nom, interventions, instance
):
    _ecrire_profil(instance, aide._equipes())
    _dater(par_nom, interventions)
    premier = aide._resultat(_constater(par_nom))
    assert aide._resultat(_constater(par_nom))["evenement_id"] == premier["evenement_id"] and len(_publies()) == 1
    plus_tard = aide._resultat(_constater(par_nom, horodatage="2030-06-02T10:00:00-04:00"))
    assert plus_tard["version_donnees"] == premier["version_donnees"]
    assert plus_tard["evenement_id"] != premier["evenement_id"] and len(_publies()) == 2


def test_un_retour_a_une_version_anterieure_publie_un_evenement_distinct_de_la_premiere(
    par_nom, interventions, instance
):
    """A, puis B, puis A : la troisième publication ne doit pas se confondre avec la première (même version)."""
    _ecrire_profil(instance, aide._equipes())
    _dater(par_nom, interventions)
    a1 = aide._resultat(_constater(par_nom, horodatage="2030-06-02T09:00:00-04:00"))
    _ecrire_profil(instance, aide._equipes()[:1])
    b = aide._resultat(_constater(par_nom, horodatage="2030-06-02T10:00:00-04:00"))
    _ecrire_profil(instance, aide._equipes())
    a2 = aide._resultat(_constater(par_nom, horodatage="2030-06-02T11:00:00-04:00"))
    assert a1["version_donnees"] == a2["version_donnees"] != b["version_donnees"]
    assert len({a1["evenement_id"], b["evenement_id"], a2["evenement_id"]}) == 3 and len(_publies()) == 3


def test_une_donnee_changee_est_une_version_de_plus(par_nom, interventions, instance):
    _ecrire_profil(instance, aide._equipes())
    _dater(par_nom, interventions)
    premier = aide._resultat(_constater(par_nom))
    _ecrire_profil(instance, aide._equipes()[:1])
    second = aide._resultat(_constater(par_nom))
    assert second["version_donnees"] != premier["version_donnees"]
    assert {i for i, _ in _publies()} == {premier["evenement_id"], second["evenement_id"]}


def test_semaine_illisible_ou_non_lundi_est_refusee_sans_rien_publier(par_nom, interventions, instance):
    _ecrire_profil(instance, aide._equipes())
    for semaine in ("2030-06-04", "pas-une-date"):
        reponse = _constater(par_nom, semaine=semaine)
        assert reponse["resultat"]["accepte"] is False, semaine
    assert _publies() == []
