"""M1.9 contre le VRAI M4 (base SQLite migrée, vrais outils de cédule, vrai profil des équipes, vrai port privé de
lecture).

Le port `lecteur_capacite_m4` donne à M1 exactement deux lectures T0 de M4 (la capacité et la semaine datée de la
cédule) ;
rien d'autre, et seulement depuis le contexte de M1. Données fictives (scénario de Repentigny à Joliette de M4)."""

from __future__ import annotations

import contextlib
import importlib.util
from pathlib import Path

import pytest
import yaml

from opsys import contexte, idempotence, identite, stockage, taxonomie
from opsys import equipes as equipes_entreprise
from opsys.capacites import Capacites
from opsys.departements import lire_manifeste

RACINE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "aide_cedule_m4", RACINE / "departments" / "m04-field-ops" / "tests" / "test_cedule_tournees_outils.py"
)
aide = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(aide)
instance, par_nom, interventions = aide.instance, aide.par_nom, aide.interventions

LUNDI = "2030-06-03"
SUIVANT = "2030-06-10"
MAINTENANT = "2030-06-01T09:00:00-04:00"
ADMIN = aide.ADMIN


def _profil(instance_dir):
    equipes = aide._equipes()
    liste = []
    for e in equipes:
        liste.append(
            {
                **e,
                "membres": [f"{e['id'].replace('-', '.')}.fictif"],
                "semaine_type": {
                    "fuseau": "America/Montreal",
                    **{
                        j: [{"debut": "08:00", "fin": "16:00"}]
                        for j in ("lundi", "mardi", "mercredi", "jeudi", "vendredi")
                    },
                    "samedi": [],
                    "dimanche": [],
                },
            }
        )
    brut = {"liste": liste, "feries": {"annees": [2030], "jours": []}}
    chemin = instance_dir / "home" / "entreprise.yaml"
    existant = yaml.safe_load(chemin.read_text(encoding="utf-8")) if chemin.exists() else {}
    existant["equipes"] = equipes_entreprise.normaliser_equipes(brut)
    chemin.write_text(yaml.safe_dump(existant, allow_unicode=True), encoding="utf-8")


@pytest.fixture
def monde(instance, par_nom, interventions):
    from m1_front_office import outils as outils_m1

    outils_m1.utiliser_stockage_durable()
    taxonomie.enregistrer_services(taxonomie.codes_catalogue())
    taxonomie.enregistrer_zone_desservie(["Laval"])
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan Fictif", "mot-de-passe-nathan-12345", ["nathan_owner"])
    deps = {d: lire_manifeste(RACINE / "departments" / d) for d in ("m01-front-office", "m04-field-ops")}
    capacites = Capacites(deps, stockage.transaction, memoire=False)
    _sms(capacites)
    yield capacites
    outils_m1.reinitialiser_registre()


def _sms(capacites):
    r = capacites.appeler(
        "m1_recevoir_message_canal",
        {
            "canal": "sms",
            "expediteur": "+15145550142",
            "message_id": "SM-1",
            "recu_le": "2030-06-01T08:00:00-04:00",
            "texte": "Bonjour, quand pouvez-vous venir évaluer?",
        },
    )
    assert r["ok"], r
    return "sms:SM-1"


def _meta(cle):
    return idempotence.Meta(cle=cle, appareil="tel-admin-1", horodatage_appareil="2000-01-01T00:00:00+00:00")


def _admin(capacites, nom, arguments, cle="c-1"):
    with contextlib.ExitStack() as pile:
        pile.enter_context(contexte.appele_par_appareil(ADMIN))
        return capacites.appeler(nom, arguments, _meta(cle))


def _proposer(monde, cle="k-reel-1", duree=60, semaines=(LUNDI,)):
    return monde.appeler(
        "m1_proposer_fenetres_rdv",
        {
            "cle": cle,
            "signal_id": "sms:SM-1",
            "motif": "visite_evaluation",
            "duree_minutes": duree,
            "semaines": list(semaines),
            "horodatage": MAINTENANT,
        },
    )


def test_le_vrai_m4_sans_profil_dit_ce_qui_manque_et_m1_ne_propose_aucune_capacite(monde):
    r = _proposer(monde)
    assert r["ok"] and r["resultat"]["accepte"], r
    (o,) = r["resultat"]["resultat"]["options"]
    assert (
        o["statut"] == "non_calculable" and "profil_equipes_non_declare" in o["manque"] and o["minutes_libres"] is None
    )


def test_le_vrai_m4_avec_profil_donne_la_capacite_semaine_type_moins_le_planifie_date(
    instance, monde, par_nom, interventions
):
    _profil(instance)
    r = _proposer(monde, semaines=(LUNDI, SUIVANT))
    options = {o["semaine"]: o for o in r["resultat"]["resultat"]["options"]}
    # aucune cédule appliquée : la semaine type est calculable mais M4 déclare la cédule non appliquée -> manque nommé
    assert all(o["statut"] in ("non_calculable", "disponible") for o in options.values())
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
    r2 = monde.appeler(
        "m1_proposer_fenetres_rdv",
        {
            "cle": "k-reel-2",
            "signal_id": "sms:SM-1",
            "motif": "visite_evaluation",
            "duree_minutes": 60,
            "semaines": [LUNDI, SUIVANT],
            "horodatage": MAINTENANT,
        },
    )
    o2 = {o["semaine"]: o for o in r2["resultat"]["resultat"]["options"]}
    assert o2[LUNDI]["statut"] == "disponible" and o2[SUIVANT]["statut"] == "disponible"
    # 5 jours de 480 min par équipe, deux équipes ; le lundi daté porte le planifié de la cédule appliquée
    assert o2[SUIVANT]["minutes_libres"] == 2 * 5 * 480
    assert 0 < o2[LUNDI]["minutes_libres"] < 2 * 5 * 480


def test_le_port_n_ouvre_que_deux_lectures_de_m4_depuis_le_contexte_de_m1(instance, monde):
    lecteur = monde.departements["m01-front-office"].charger_outils(
        ports_prives={"lecteur_capacite_m4": Capacites._lecteur_capacite_m4(monde.departements, stockage.transaction)}
    )
    assert any(o.nom == "m1_proposer_fenetres_rdv" for o in lecteur)
    port = Capacites._lecteur_capacite_m4(monde.departements, stockage.transaction)
    hors_contexte = port("m4_lire_capacite_equipe", {"debut_semaine": LUNDI})
    assert hors_contexte["erreur"] == "contexte_m1_requis"
    with contexte.appeler_en_tant_que("m01-front-office"):
        for interdit in (
            "m4_lire_journal_quotidien",
            "m4_proposer_cedule",
            "m4_appliquer_cedule",
            "m4_pointer",
            "m4_lire_position_gps",
            "m6_lire_disponibilite",
            "opsys_demandes_approbation",
        ):
            assert port(interdit, {})["erreur"] == "lecture_non_autorisee", interdit
        assert port("m4_lire_capacite_equipe", "pas un objet")["erreur"] == "arguments_invalides"
        ok = port("m4_lire_capacite_equipe", {"debut_semaine": LUNDI})
        assert ok["ok"] is True
    with contexte.appeler_en_tant_que("m05-financecore"):
        assert port("m4_lire_capacite_equipe", {"debut_semaine": LUNDI})["erreur"] == "contexte_m1_requis"
    # chacun des deux contrôles (département appelant ET origine fiable du point d'accès) suffit à refuser
    with contexte.appeler_en_tant_que("m05-financecore", origine="m01-front-office"):
        assert port("m4_lire_capacite_equipe", {"debut_semaine": LUNDI})["erreur"] == "contexte_m1_requis"
    with contexte.appeler_en_tant_que("m01-front-office", origine="m05-financecore"):
        assert port("m4_lire_capacite_equipe", {"debut_semaine": LUNDI})["erreur"] == "contexte_m1_requis"


def test_un_appareil_autre_que_admin_ne_lit_pas_la_cedule_par_le_port_de_m1(instance, monde):
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "marc.fictif2", "Marc Deux", "mot-de-passe-marc-12345", ["employee"])
    marc = contexte.IdentiteAppelante(personne="marc.fictif2", role="employee")
    port = Capacites._lecteur_capacite_m4(monde.departements, stockage.transaction)
    with contexte.appeler_en_tant_que("m01-front-office"), contexte.appele_par_appareil(marc):
        r = port("m4_lire_cedule_semaine", {"debut_semaine": LUNDI})
    assert r["ok"] is True and r["resultat"]["accepte"] is False


def test_confirmation_contre_la_vraie_cedule_de_m4(instance, monde, par_nom, interventions):
    _profil(instance)
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
    r = _proposer(monde, semaines=(LUNDI,))
    rid = r["resultat"]["resultat"]["rdv_id"]
    assert r["resultat"]["resultat"]["options"][0]["statut"] == "disponible"
    monde.appeler("m1_retenir_fenetre_rdv", {"rdv_id": rid, "semaine": LUNDI, "horodatage": MAINTENANT})
    iid = next(iter(interventions.values()))
    ok = _admin(monde, "m1_confirmer_rendez_vous", {"rdv_id": rid, "intervention_id": iid, "horodatage": MAINTENANT})
    assert ok["ok"] and ok["resultat"]["accepte"], ok
    c = ok["resultat"]["resultat"]["confirme"]
    assert c["intervention_id"] == iid and c["debut"].startswith("2030-06-03T") and c["fin"] > c["debut"]
    inconnue = _admin(
        monde,
        "m1_confirmer_rendez_vous",
        {"rdv_id": rid, "intervention_id": "i-inexistante", "horodatage": MAINTENANT},
        cle="c-2",
    )
    assert inconnue["ok"] is False
