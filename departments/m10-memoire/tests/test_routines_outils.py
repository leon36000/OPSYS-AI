"""Les quatre outils de routine de M10 : déclaration, refus typés, lecture seule (`ecrire` faux), idempotence, rapport
recalculé
côté serveur, lecture du bus. Base SQLite jetable ; données FICTIVES ; aucun HTTP ni fournisseur."""

from __future__ import annotations

import datetime as dt

import pytest
import yaml
from m10_memoire import outils, routines, routines_outils
from sqlalchemy import insert

from opsys import contexte, evenements, stockage
from opsys import service_acteur_systeme as systeme
from opsys.outils import Autonomie, Niveau
from opsys.stockage.schema import EVENEMENTS_RECUS

FICTIF = True
HORO = "2026-11-16T04:35:00-05:00"


def _apres(jours: int) -> str:
    """Un instant `jours` jours après la publication faite maintenant par le test (le bus date par l'horloge de la
    machine ;
    ces tests-ci ne dépendent que de l'écart, jamais d'une date absolue)."""
    return (dt.datetime.now(dt.UTC) + dt.timedelta(days=jours)).isoformat()


CYCLE = ("2026-11-16T05:00:00+00:00", "2026-11-17T05:00:00+00:00")


def _outil(nom):
    return next(o for o in outils.outils() if o.nom == nom)


@pytest.fixture
def monde(tmp_path, monkeypatch):
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'fictif.db'}")
    stockage.migrer()
    yield tmp_path
    stockage.liberer()


def _rapports():
    with stockage.transaction():
        return list(stockage.maillons("m10-memoire", "rapports_routine"))


def test_les_quatre_outils_sont_declares_n0_ou_n2_agent_seulement_et_le_manifeste_les_connait():
    attendus = {
        "m10_lister_affaires_a_consolider": (Autonomie.T0, Niveau.N0),
        "m10_executer_audit_non_oubli": (Autonomie.T1, Niveau.N2),
        "m10_calculer_kpis": (Autonomie.T1, Niveau.N2),
        "m10_lire_rapports_routine": (Autonomie.T0, Niveau.N0),
        "m10_consolider_affaire": (Autonomie.T1, Niveau.N2),
    }
    for nom, (autonomie, niveau) in attendus.items():
        outil = _outil(nom)
        assert outil.autonomie is autonomie and outil.niveau is niveau and outil.roles_appareil == frozenset(), nom
        assert not outil.frontiere_humaine and outil.parametres["additionalProperties"] is False, nom
    manifeste = yaml.safe_load(
        (
            routines.__file__ and __import__("pathlib").Path(routines.__file__).resolve().parents[2] / "department.yaml"
        ).read_text(encoding="utf-8")
    )
    declares = {o for r in manifeste["routines_planifiees"] for o in r["outils"]}
    assert declares == set(attendus) - {"m10_lire_rapports_routine"}  # la lecture sert aux personnes, pas à une routine
    assert {k["id"] for k in manifeste["kpis"]} == set(routines.kpi_ids())


@pytest.mark.parametrize(
    "appel, code",
    [
        (lambda: routines_outils.lister_affaires_a_consolider("2026-02-30"), "REJ-ROUTINE-JOUR-INVALIDE"),
        (lambda: routines_outils.lister_affaires_a_consolider("hier"), "REJ-ROUTINE-JOUR-INVALIDE"),
        (lambda: routines_outils.lister_affaires_a_consolider("2026-11-09", 0), "REJ-ROUTINE-LIMITE-INVALIDE"),
        (lambda: routines_outils.lister_affaires_a_consolider("2026-11-09", 201), "REJ-ROUTINE-LIMITE-INVALIDE"),
        (lambda: routines_outils.lister_affaires_a_consolider("2026-11-09", True), "REJ-ROUTINE-LIMITE-INVALIDE"),
        (lambda: routines_outils.executer_audit_non_oubli("2026-11-16T04:35:00"), "REJ-HORODATAGE-INVALIDE"),
        (lambda: routines_outils.executer_audit_non_oubli(HORO, 0), "REJ-ROUTINE-FENETRE-INVALIDE"),
        (lambda: routines_outils.executer_audit_non_oubli(HORO, 91), "REJ-ROUTINE-FENETRE-INVALIDE"),
        (lambda: routines_outils.executer_audit_non_oubli(HORO, 7, "oui"), "REJ-ROUTINE-FENETRE-INVALIDE"),
        (lambda: routines_outils.calculer_kpis("2026-11-16", CYCLE[1], CYCLE[0], HORO), "REJ-ROUTINE-CYCLE-INVALIDE"),
        (lambda: routines_outils.calculer_kpis("2026-11-16", CYCLE[0], CYCLE[0], HORO), "REJ-ROUTINE-CYCLE-INVALIDE"),
        (
            lambda: routines_outils.calculer_kpis("2026-11-16", "2026-11-16T05:00:00", CYCLE[1], HORO),
            "REJ-HORODATAGE-INVALIDE",
        ),
        (lambda: routines_outils.calculer_kpis("pas-un-jour", *CYCLE, HORO), "REJ-ROUTINE-JOUR-INVALIDE"),
        (lambda: routines_outils.lire_rapports_routine("tout"), "REJ-ROUTINE-GENRE-INCONNU"),
        (lambda: routines_outils.lire_rapports_routine("kpis", 15), "REJ-ROUTINE-LIMITE-INVALIDE"),
    ],
)
def test_une_entree_invalide_est_refusee_avant_toute_lecture_ou_ecriture(monde, appel, code):
    with stockage.transaction():
        refus = appel()
    assert refus["accepte"] is False and refus["verdict"]["code"] == code
    assert _rapports() == []


def test_un_appareil_non_admin_ne_lit_ni_n_ecrit(monde):
    employe = contexte.IdentiteAppelante("employe-fictif", "employee")
    with stockage.transaction(), contexte.appele_par_appareil(employe):
        for refus in (
            routines_outils.lister_affaires_a_consolider("2026-11-09"),
            routines_outils.executer_audit_non_oubli(HORO),
            routines_outils.calculer_kpis("2026-11-16", *CYCLE, HORO),
            routines_outils.lire_rapports_routine("kpis"),
        ):
            assert refus["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert _rapports() == []


def test_l_ecriture_est_reservee_au_planificateur_un_agent_ne_peut_pas_forger_un_rapport(monde):
    """Un agent qui appellerait l'outil avec un instant forgé occuperait la clé d'un rapport : refusé avant toute
    lecture. Le calcul à blanc (`ecrire` faux) et la lecture restent ouverts."""
    with stockage.transaction():
        for refus in (
            routines_outils.executer_audit_non_oubli("2099-12-31T04:35:00-05:00"),
            routines_outils.calculer_kpis("2099-12-31", *CYCLE, HORO),
        ):
            assert refus["verdict"]["code"] == "REJ-ROUTINE-PLANIFICATEUR-REQUIS"
        assert routines_outils.executer_audit_non_oubli(HORO, 7, False)["accepte"] is True
        assert routines_outils.calculer_kpis("2026-11-16", *CYCLE, HORO, False)["accepte"] is True
    assert _rapports() == []
    with systeme.contexte_planificateur():
        pass  # un tour fini : l'acteur système fermé ne vaut plus rien
    with stockage.transaction():
        assert routines_outils.executer_audit_non_oubli(HORO)["verdict"]["code"] == "REJ-ROUTINE-PLANIFICATEUR-REQUIS"


def test_ecrire_faux_ne_laisse_aucune_trace_et_ecrire_vrai_est_idempotent(monde):
    with stockage.transaction():
        blanc = routines_outils.executer_audit_non_oubli(HORO, 7, False)["resultat"]
        assert blanc["ecrit"] is False and blanc["nb_oublis"] == 0
        kpi_blanc = routines_outils.calculer_kpis("2026-11-16", *CYCLE, HORO, False)["resultat"]
        assert kpi_blanc["ecrit"] is False
    assert _rapports() == []
    with systeme.contexte_planificateur(), stockage.transaction():
        premiers = (
            routines_outils.executer_audit_non_oubli(HORO)["resultat"]["ecrit"],
            routines_outils.calculer_kpis("2026-11-16", *CYCLE, HORO)["resultat"]["ecrit"],
        )
        seconds = (
            routines_outils.executer_audit_non_oubli(HORO)["resultat"]["ecrit"],
            routines_outils.calculer_kpis("2026-11-16", *CYCLE, HORO)["resultat"]["ecrit"],
        )
    assert premiers == (True, True) and seconds == (False, False)
    assert sorted(r["genre"] for r in _rapports()) == ["audit_non_oubli", "kpis"]
    with stockage.transaction():
        lu = routines_outils.lire_rapports_routine("audit_non_oubli")["resultat"]
        assert lu["rapports"][0]["contenu"]["total_attendus"] == 0
        assert routines_outils.lire_rapports_routine("kpis", 3)["resultat"]["rapports"][0]["fin"] == "2026-11-16"
        assert routines_outils.lire_rapports_routine("consolidation")["resultat"]["jours"] == []


def test_le_rapport_est_recalcule_cote_serveur_un_appelant_ne_peut_pas_y_mettre_son_contenu(monde):
    parametres = _outil("m10_executer_audit_non_oubli").parametres["properties"]
    assert set(parametres) == {"fin", "jours", "ecrire"}  # aucun paramètre ne porte le contenu du rapport
    parametres = _outil("m10_calculer_kpis").parametres["properties"]
    assert set(parametres) == {"jour", "debut_cycle", "fin_cycle", "horodatage", "ecrire"}


def test_l_audit_lit_le_bus_un_evenement_traite_sans_trace_est_un_oubli_une_publication_non_livree_n_en_est_pas_un(
    monde,
):
    charge = {
        "wct_id": "wct-x",
        "intervention_id": "i",
        "lead_id": "aff-x",
        "technicien_id": "t",
        "horodatage_completion": "2026-11-15T10:00:00-05:00",
        "fix_gps_completion": {"latitude": 45.0, "longitude": -73.0},
        "duree_reelle_minutes": 60,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": "a" * 64,
        "consommateurs_cibles": ["M10"],
        "devis_id": "d",
        "statut": "completed_verified",
    }
    with stockage.transaction():
        perdu = evenements.publier("m4.travaux_termines", "m04-field-ops", charge)
        evenements.publier("m4.travaux_termines", "m04-field-ops", {**charge, "wct_id": "wct-en-route"})
    with stockage.transaction() as cnx:
        cnx.execute(
            insert(EVENEMENTS_RECUS).values(
                evenement_id=perdu, consommateur="m10-memoire", statut="traite", tentatives=1, resultat="{}"
            )
        )
    with stockage.transaction():
        rapport = routines_outils.executer_audit_non_oubli(_apres(1), 90, False)["resultat"]
    assert rapport["oublis"] == [
        {"type_evenement": "m4.travaux_termines", "identifiant": "wct-x", "verdict": "REJ-AUDIT-TRACE-ABSENTE"}
    ]
    assert rapport["livraison"]["en_attente"] == 1 and rapport["total_attendus"] == 1
    # La fenêtre est celle demandée : une publication plus ancienne que `jours` n'est pas attendue.
    with stockage.transaction():
        vide = routines_outils.executer_audit_non_oubli(_apres(30), 7, False)["resultat"]
    assert vide["total_attendus"] == 0


def test_une_fenetre_trop_grande_est_refusee_pas_lue_en_partie(monde, monkeypatch):
    monkeypatch.setattr(routines_outils, "PUBLICATIONS_MAX", 1)
    charge = {
        "wct_id": "w",
        "intervention_id": "i",
        "lead_id": "l",
        "technicien_id": "t",
        "horodatage_completion": "2026-11-15T10:00:00-05:00",
        "fix_gps_completion": {"latitude": 45.0, "longitude": -73.0},
        "duree_reelle_minutes": 60,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": "a" * 64,
        "consommateurs_cibles": ["M10"],
        "devis_id": "d",
        "statut": "completed_verified",
    }
    with stockage.transaction():
        evenements.publier("m4.travaux_termines", "m04-field-ops", charge)
        evenements.publier("m4.travaux_termines", "m04-field-ops", {**charge, "wct_id": "w2"})
        refus = routines_outils.executer_audit_non_oubli(_apres(1), 90, False)
    assert refus["verdict"]["code"] == "REJ-AUDIT-FENETRE-TROP-GRANDE" and _rapports() == []


def test_l_enumerateur_est_en_lecture_seule(monde):
    with stockage.transaction():
        outil = _outil("m10_lister_affaires_a_consolider")
        assert outil.fonction("2026-11-09")["resultat"]["touchees"] == 0
    assert _rapports() == []
