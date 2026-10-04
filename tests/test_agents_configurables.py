from __future__ import annotations

import pytest

from opsys import agents, identite


def _personnes(session):
    with session() as cnx:
        identite.creer_personne(cnx, "profil-admin", "Administrateur", "test-password-admin-1234", ["admin"])
        identite.creer_personne(cnx, "profil-staff", "Employé", "test-password-staff-1234", ["employee"])


def _spec(ident="m09-recherche"):
    return {
        "id": ident,
        "departement": "m09-demo",
        "responsabilite": "Analyser les demandes et préparer une synthèse.",
        "palier_modele": "standard",
        "outils": ["m9_additionner"],
        "budget_jour": 10000,
        "budget_mois": 100000,
        "limite_tours": 12,
        "limite_reessais": 2,
        "limite_concurrence": 3,
        "declencheurs": [{"type": "manuel"}],
    }


def test_creation_revision_activation_relecture_et_suppression_logique(session, departements_demo):
    _personnes(session)
    with session() as cnx:
        profil = agents.creer(cnx, departements_demo, _spec(), par="profil-admin", mutation_id="create-req-0001")
        assert profil["revision"] == 1 and profil["actif"] is False
        assert agents.lister(cnx) == []
        actif = agents.definir_actif(
            cnx, profil["id"], departements_demo, True, par="profil-admin", mutation_id="activate-0001",
            revision_attendue=1,
        )
        assert actif["actif"] and actif["revision"] == 2
        assert agents.historique(cnx, profil["id"]) == [profil, actif]
    # Nouvelle transaction simule une relecture après redémarrage.
    with session() as cnx:
        assert agents.obtenir(cnx, profil["id"]) == actif
        supprime = agents.supprimer(
            cnx, profil["id"], departements_demo, par="profil-admin", mutation_id="delete-0001",
            revision_attendue=2,
        )
        assert supprime["supprime"] is True and supprime["actif"] is False
        assert agents.obtenir(cnx, profil["id"]) is None
        assert agents.obtenir(cnx, profil["id"], inclure_supprime=True) == supprime
        assert len(agents.historique(cnx, profil["id"])) == 3


def test_profils_distincts_dans_meme_departement_replay_et_conflit_revision(session, departements_demo):
    _personnes(session)
    premier = _spec("m09-analyse")
    second = _spec("m09-relecture")
    with session() as cnx:
        a = agents.creer(cnx, departements_demo, premier, par="profil-admin", mutation_id="create-req-0002")
        replay = agents.creer(cnx, departements_demo, premier, par="profil-admin", mutation_id="create-req-0002")
        b = agents.creer(cnx, departements_demo, second, par="profil-admin", mutation_id="create-req-0003")
        assert replay == a and a["id"] != b["id"] and a["departement"] == b["departement"]
        actif = agents.definir_actif(cnx, a["id"], departements_demo, True, par="profil-admin",
                                     mutation_id="activate-0002", revision_attendue=1)
        assert agents.definir_actif(cnx, a["id"], departements_demo, True, par="profil-admin",
                                    mutation_id="activate-0002", revision_attendue=1) == actif
        agents.definir_actif(cnx, a["id"], departements_demo, False, par="profil-admin",
                             mutation_id="deactivate-0002", revision_attendue=2)
        assert agents.creer(cnx, departements_demo, premier, par="profil-admin",
                            mutation_id="create-req-0002") == a
        assert agents.definir_actif(cnx, a["id"], departements_demo, True, par="profil-admin",
                                    mutation_id="activate-0002", revision_attendue=1) == actif
        with pytest.raises(ValueError, match="conflit de révision"):
            agents.definir_actif(cnx, a["id"], departements_demo, False, par="profil-admin",
                                 mutation_id="stale-0001", revision_attendue=1)
        assert len(agents.historique(cnx, a["id"])) == 3


@pytest.mark.parametrize("champ,valeur,erreur", [
    ("outils", ["m1_lire_finances"], "hors du département"),
    ("palier_modele", "mystere", "palier_modele"),
    ("budget_jour", True, "budget_jour"),
    ("budget_jour", 10_000_000_001, "budget_jour"),
    ("budget_mois", 9999, "budget_mois"),
    ("limite_reessais", -1, "limite_reessais"),
    ("declencheurs", [{"type": "cron", "expression": "demain"}], "cron invalide"),
    ("api_key", "must-never-be-persisted", "non pris en charge"),
])
def test_rejette_specification_invalide_et_outils_financiers_hors_departement(
    session, departements_demo, champ, valeur, erreur
):
    _personnes(session)
    spec = _spec()
    spec[champ] = valeur
    with session() as cnx, pytest.raises(ValueError, match=erreur):
        agents.creer(cnx, departements_demo, spec, par="profil-admin", mutation_id="bad-spec-0001")


@pytest.mark.parametrize("acteur,roles,actif", [("profil-staff", ["employee"], True),
                                                    ("profil-admin", ["admin"], False)])
def test_refuse_acteur_non_admin_ou_inactif(session, departements_demo, acteur, roles, actif):
    with session() as cnx:
        identite.creer_personne(cnx, acteur, "Personne", "test-password-personne-1234", roles, actif=actif)
        with pytest.raises(PermissionError, match="personne active admin"):
            agents.creer(cnx, departements_demo, _spec(), par=acteur, mutation_id="denied-req-0001")


def test_revision_et_revisionnement_logique_preservent_budgets_declarations(session, departements_demo):
    _personnes(session)
    with session() as cnx:
        profil = agents.creer(cnx, departements_demo, _spec(), par="profil-admin", mutation_id="create-req-0004")
        modifie = _spec()
        modifie["responsabilite"] = "Relire les résultats de l'analyse."
        v2 = agents.modifier(cnx, profil["id"], departements_demo, modifie, par="profil-admin",
                             mutation_id="update-0001", revision_attendue=1)
        assert v2["revision"] == 2 and v2["budget_jour"] == 10000 and v2["limite_tours"] == 12
        assert v2["actif"] is False  # budgets persistés, aucune promesse d'enforcement dans ce lot
