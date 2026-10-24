"""Candidate isolé QA : trois communs de département et aucune donnée réelle."""

from __future__ import annotations

import json
import re

import pytest
from agents_base_qa import provisionner_base_qa

from opsys import admission_agents, agents, agents_base, approbations, canaux, jetons, openclaw
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.outils import Niveau

COMMONS = ("opsys_lire_artefact", "opsys_etat_budget", "opsys_demandes_approbation")


@pytest.mark.parametrize("nom", COMMONS)
def test_common_base_runtime_et_scope(nom, session, opsys_home):
    deps = charger_departements()
    profils = provisionner_base_qa(session, deps)
    own = "m03-estimation"
    foreign = "m04-field-ops"
    profil = profils[own]
    cap = Capacites(deps, session, filtre={own}, appelant=own)
    with session() as cnx:
        if nom == "opsys_lire_artefact":
            own_out = jetons.tronquer(cnx, "FICTIF A " * 1000, "qa-source", limite=100, departement=own, origine=own)
            foreign_out = jetons.tronquer(
                cnx, "FICTIF B " * 1000, "qa-source", limite=100, departement=foreign, origine=foreign
            )
            own_id = re.search(r"artefact ([0-9a-f]{16})", own_out).group(1)
            foreign_id = re.search(r"artefact ([0-9a-f]{16})", foreign_out).group(1)
            args = {"id": own_id, "longueur": 32}
        elif nom == "opsys_etat_budget":
            jetons.enregistrer_usage(cnx, own, "qa-model-usage", {"input_tokens": 17, "output_tokens": 3})
            jetons.enregistrer_usage(cnx, foreign, "qa-model-usage", {"input_tokens": 90, "output_tokens": 10})
            args = {}
        else:
            own_id = approbations.creer_demande(cnx, own, "m3-qa", {"fictif": True}, niveau=Niveau.N4)
            foreign_id = approbations.creer_demande(cnx, foreign, "m4-qa", {"fictif": True}, niveau=Niveau.N4)
            args = {}
    direct = cap.appeler(nom, args)
    assert direct["ok"] is True
    if nom == "opsys_lire_artefact":
        assert direct["resultat"]["id"] == own_id
        negative = cap.appeler(nom, {"id": foreign_id})
        assert negative["ok"] is False
    elif nom == "opsys_etat_budget":
        assert len(direct["resultat"]) == 1
        assert direct["resultat"][0]["departement"] == own
        assert direct["resultat"][0]["jour"]["utilise"] == 20
    else:
        assert [d["id"] for d in direct["resultat"]] == [own_id]
        assert foreign_id not in str(direct)
    runtime = cap.appeler_profil_runtime(
        nom, args, None, None, profile_id=profil["id"], profile_revision=profil["revision"], server="opsys_m3"
    )
    wrong_server = cap.appeler_profil_runtime(
        nom, args, None, None, profile_id=profil["id"], profile_revision=profil["revision"], server="opsys_m4"
    )
    assert wrong_server["ok"] is False
    config = openclaw.generer(
        deps,
        opsys_home / "core",
        {"standard": {"provider": "anthropic", "model": "qa-no-provider"}},
        environ={"OPSYS_EMBEDDINGS_URL": "http://embeddings-qa:11434/v1", "OPSYS_EMBEDDINGS_MODELE": "qa"},
        cnx_factory=session,
    )
    policy = json.loads(config["agents"].read_text())["entries"][own]["tools"]
    assert runtime["ok"] is True
    assert "allow" not in policy
    assert f"opsys_m3__{nom}" not in policy["deny"]
    # Same call must refuse after current SQL revocation, regardless of retained object.
    with session() as cnx:
        agents.definir_actif(
            cnx,
            profil["id"],
            deps,
            False,
            par="base-admin-fictif",
            mutation_id="qa-common-disable-001",
            revision_attendue=profil["revision"],
        )
    assert (
        cap.appeler_profil_runtime(
            nom, args, None, None, profile_id=profil["id"], profile_revision=profil["revision"], server="opsys_m3"
        )["ok"]
        is False
    )


def test_six_partages_base_exacts_sous_revision_et_departement(session):
    deps = charger_departements()
    profil = provisionner_base_qa(session, deps)["m03-estimation"]
    with session() as cnx:
        custom = agents.creer(
            cnx,
            deps,
            {
                "id": "qa-custom-no-common",
                "departement": "m03-estimation",
                "responsabilite": "QA aucun droit commun implicite",
                "palier_modele": "standard",
                "outils": [],
                "budget_jour": 1000,
                "budget_mois": 10000,
                "limite_tours": 8,
                "limite_reessais": 2,
                "limite_concurrence": 1,
                "declencheurs": [{"type": "manuel"}],
            },
            par="base-admin-fictif",
            mutation_id="qa-common-custom-create",
        )
        agents.definir_actif(
            cnx,
            custom["id"],
            deps,
            True,
            par="base-admin-fictif",
            mutation_id="qa-common-custom-enable",
            revision_attendue=1,
        )
        for nom in agents_base.OUTILS_PARTAGES_RUNTIME:
            assert (
                admission_agents.verifier_outil_runtime(cnx, profil["id"], deps, f"opsys_m3__{nom}", 2)["autorise"]
                is True
            )
            with pytest.raises(admission_agents.AdmissionRefusee, match="serveur hors"):
                admission_agents.verifier_outil_runtime(cnx, profil["id"], deps, f"opsys_m4__{nom}", 2)
            with pytest.raises(admission_agents.AdmissionRefusee, match="capacité absente"):
                admission_agents.verifier_outil_runtime(cnx, custom["id"], deps, f"opsys_m3__{nom}", 2)
        with pytest.raises(admission_agents.AdmissionRefusee, match="capacité absente"):
            admission_agents.verifier_outil_runtime(cnx, profil["id"], deps, "opsys_m3__opsys_outil_invente", 2)
        with pytest.raises(admission_agents.AdmissionRefusee, match="périmée"):
            admission_agents.verifier_outil_runtime(cnx, profil["id"], deps, "opsys_m3__opsys_etat_budget", 1)


def test_base_restaure_frontieres_historiques_sans_reouvrir_outils_metier_retires(session, opsys_home):
    deps = charger_departements()
    profils = provisionner_base_qa(session, deps)
    for dep_id in ("m03-estimation", "m01-front-office"):
        profil = profils[dep_id]
        with session() as cnx:
            agents.modifier(
                cnx,
                profil["id"],
                deps,
                {"id": profil["id"], "outils": []},
                par="base-admin-fictif",
                mutation_id=f"qa-base-remove-{dep_id}",
                revision_attendue=2,
            )
    fichiers = openclaw.generer(
        deps,
        opsys_home / "core",
        {"standard": {"provider": "anthropic", "model": "qa-no-provider"}},
        environ={"OPSYS_EMBEDDINGS_URL": "http://embeddings-qa:11434/v1", "OPSYS_EMBEDDINGS_MODELE": "qa"},
        cnx_factory=session,
    )
    config = json.loads(fichiers["agents"].read_text())["entries"]
    for dep_id in ("m03-estimation", "m01-front-office"):
        policy = config[dep_id]["tools"]
        server = openclaw.serveur_mcp(deps[dep_id])
        retires = {f"{server}__{o.nom}" for o in deps[dep_id].charger_outils()}
        assert retires <= set(policy["deny"])
        assert "*" not in policy["deny"]
        for commun in agents_base.OUTILS_PARTAGES_RUNTIME:
            assert f"{server}__{commun}" not in policy["deny"]
        if dep_id == "m03-estimation":
            assert "allow" not in policy
            assert not {"read", "exec", "memory_search", "memory_get"} & set(policy["deny"])
        else:
            assert policy["allow"] == [f"{server}__*"]
            assert set(canaux.OUTILS_MESSAGERIE_REFUSES) <= set(policy["deny"])


def test_memoire_commune_garde_portee_et_effacement_humain(session):
    deps = charger_departements()
    profil = provisionner_base_qa(session, deps)["m03-estimation"]
    cap = Capacites(deps, session, filtre={"m03-estimation"}, appelant="m03-estimation")
    commun = dict(profile_id=profil["id"], profile_revision=profil["revision"], server="opsys_m3")
    recherche = cap.appeler_profil_runtime(
        "opsys_memoire_rechercher", {"requete": "fictif", "portees": ["portee-interdite-fictive"]}, None, None, **commun
    )
    assert recherche["ok"] is False and "hors du manifeste" in recherche["details"]
    oubli = cap.appeler_profil_runtime(
        "opsys_memoire_oublier",
        {"motif": "QA refus automatique", "demandeur": "fictif", "sujet": "client-fictif"},
        None,
        None,
        **commun,
    )
    assert oubli["statut"] == "en_attente_approbation"
    with session() as cnx:
        demandes = approbations.lister(cnx)
        assert len(demandes) == 1 and demandes[0]["outil"] == "opsys_memoire_oublier"
        assert demandes[0]["statut"] == "en_attente"
