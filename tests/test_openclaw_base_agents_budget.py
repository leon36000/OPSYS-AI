"""Agents départementaux : provisionnement explicite et admission réelle, données QA fictives."""
from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import select

from opsys import admission_agents, agents, agents_base, cli, identite, instance, jetons, modeles, openclaw
from opsys.departements import Budget, charger_departements
from opsys.stockage.schema import AGENTS_RESERVATIONS

FICTIF = True
PALIERS = {"standard": {"provider": "anthropic", "model": "qa-no-provider"}}
ENV = {"OPSYS_EMBEDDINGS_URL": "http://embeddings-qa:11434/v1", "OPSYS_EMBEDDINGS_MODELE": "qa"}


def test_aucun_agent_base_sans_profil_durable_avant_ecriture(departements_demo, tmp_path):
    cible = tmp_path / "config"
    with pytest.raises(ValueError, match="profils de base"):
        openclaw.generer(departements_demo, cible, PALIERS, environ=ENV)
    assert not cible.exists()


def _provisionner(cnx, deps, **changements):
    valeurs = dict(limite_tours=8, limite_reessais=2, limite_concurrence=1,
                   budget_entreprise_jour=10_000_000, budget_entreprise_mois=100_000_000)
    valeurs.update(changements)
    return agents_base.provisionner(cnx, deps, par="base-admin-qa", **valeurs)


def _admin(cnx):
    identite.creer_personne(cnx, "base-admin-qa", "Admin fictif", "qa-password-base-1234", ["admin"])


def test_dix_departements_provisionnes_generes_sans_mutation_cachee(session, tmp_path):
    deps = charger_departements()
    with session() as cnx:
        _admin(cnx)
        profils = _provisionner(cnx, deps)
        avant = agents.lister(cnx, inclure_inactifs=True)
        assert _provisionner(cnx, deps) == profils
    paliers = {nom: dict(PALIERS["standard"]) for nom in ("rapide", "standard", "fort", "local")}
    fichiers = openclaw.generer(deps, tmp_path, paliers, environ=ENV, cnx_factory=session)
    config = json.loads(fichiers["agents"].read_text())["entries"]
    assert set(config) == set(deps)
    assert len(config) == 10
    mcp = json.loads(fichiers["mcp"].read_text())["servers"]
    for dep_id, agent in config.items():
        profil = profils[dep_id]
        assert agent["opsysRuntimeAdmission"] == {"profileId": profil["id"], "profileRevision": 2}
        assert agent["runtime"] == {"type": "embedded"}
        assert profil["departement"] == dep_id
        assert profil["budget_jour"] == deps[dep_id].budget.tokens_jour
        assert profil["budget_mois"] == deps[dep_id].budget.tokens_mois
        # Même frontière historique : le public reste dans son serveur MCP; les
        # agents internes conservent les capacités Core sous leurs gardes natives.
        if "allow" in agent["tools"]:
            assert agent["tools"]["allow"] == [f"{openclaw.serveur_mcp(deps[dep_id])}__*"]
        assert not any(f"{openclaw.serveur_mcp(deps[dep_id])}__{n}" in agent["tools"]["deny"]
                       for n in profil["outils"])
        assert mcp[f"opsys_runtime_{profil['id']}"]["url"].endswith(f"/runtime/{profil['id']}")
    with session() as cnx:
        assert agents.lister(cnx, inclure_inactifs=True) == avant


def test_reservation_reelle_usage_concilie_et_refus_epuise(session, departements_demo):
    dep = next(iter(departements_demo.values()))
    deps = {dep.id: replace(dep, budget=Budget(100, 1000))}
    with session() as cnx:
        _admin(cnx)
        profil = _provisionner(cnx, deps)[dep.id]

    def reserver(cnx, execution, plafond):
        return admission_agents.admettre_cycle_runtime(
            cnx, profil["id"], deps, execution, f"{execution}:0:0", plafond,
            revision_profil=profil["revision"], attempt_id=f"{execution}:0",
            cycle_id=f"{execution}:0:0", candidate_index=0, stream_ordinal=0, is_fallback_retry=False,
        )

    with session() as cnx:
        accord = reserver(cnx, "qa-base-execution-01", 60)
        assert accord["accord_neuf"] is True and accord["statut"] == "reservee"
        concilie = admission_agents.concilier(cnx, accord["id"], 20)
        assert concilie["statut"] == "conciliee" and concilie["tokens_reels"] == 20
        assert jetons.etat_budget(cnx, dep.id, deps[dep.id].budget)["jour"]["utilise"] == 20
    with session() as cnx, pytest.raises(admission_agents.AdmissionRefusee, match="budget agent insuffisant"):
        reserver(cnx, "qa-base-execution-02", 90)
    with session() as cnx, pytest.raises(admission_agents.AdmissionRefusee, match="cycle déjà admis"):
        reserver(cnx, "qa-base-execution-01", 60)
    with session() as cnx:
        lignes = cnx.execute(select(AGENTS_RESERVATIONS)).mappings().all()
        assert len(lignes) == 1 and lignes[0]["tokens_reels"] == 20


def test_reprise_preserve_profil_modifie_et_ne_reactive_pas(session, departements_demo, tmp_path):
    deps = departements_demo
    dep_id = next(iter(deps))
    with session() as cnx:
        _admin(cnx)
        profil = _provisionner(cnx, deps)[dep_id]
        profil = agents.modifier(cnx, profil["id"], deps,
                                 {"id": profil["id"], "budget_jour": 5, "budget_mois": 50, "outils": []},
                                 par="base-admin-qa", mutation_id="qa-base-restrict-001", revision_attendue=2)
        assert _provisionner(cnx, deps)[dep_id] == profil
    fichiers = openclaw.generer(deps, tmp_path, PALIERS, environ=ENV, cnx_factory=session)
    agent = json.loads(fichiers["agents"].read_text())["entries"][dep_id]
    assert agent["opsysRuntimeAdmission"]["profileRevision"] == 3
    assert "allow" not in agent["tools"] and "*" not in agent["tools"]["deny"]
    assert all(f"{openclaw.serveur_mcp(deps[dep_id])}__{outil.nom}" in agent["tools"]["deny"]
               for outil in deps[dep_id].charger_outils())
    with session() as cnx:
        agents.definir_actif(cnx, profil["id"], deps, False, par="base-admin-qa",
                             mutation_id="qa-base-disable-001", revision_attendue=3)
    with session() as cnx, pytest.raises(ValueError, match="incompatible"):
        _provisionner(cnx, deps)
    with pytest.raises(ValueError, match="profils de base"):
        openclaw.generer(deps, tmp_path / "refused", PALIERS, environ=ENV, cnx_factory=session)
    assert not (tmp_path / "refused").exists()


def test_provisionnement_refuse_non_admin_et_limites_absentes(session, departements_demo):
    with session() as cnx, pytest.raises(PermissionError):
        _provisionner(cnx, departements_demo)
    with session() as cnx:
        _admin(cnx)
    with session() as cnx, pytest.raises(ValueError, match="limite_tours"):
        _provisionner(cnx, departements_demo, limite_tours=0)
    with session() as cnx:
        assert agents.lister(cnx, inclure_inactifs=True) == []


def test_migration_instance_attend_choix_puis_prepare_profils_reels(opsys_home, tmp_path):
    deps = charger_departements()
    modeles.enregistrer_paliers({nom: dict(PALIERS["standard"]) for nom in ("rapide", "standard", "fort", "local")})
    kwargs = dict(source=Path(__file__).resolve().parents[1], python=Path(sys.executable),
                  port_gateway=None, port_moteur=None, environ=ENV, etat_core=tmp_path / "core")
    attente = instance.initialiser(opsys_home, **kwargs)
    assert attente.etat == "en_attente"
    assert len(attente.manque) == 1 and "agents-base provisionner" in attente.manque[0]
    assert not (tmp_path / "core/opsys/agents.json").exists()
    from opsys import stockage
    try:
        with stockage.transaction() as cnx:
            _admin(cnx)
            _provisionner(cnx, deps)
        pret = instance.initialiser(opsys_home, **kwargs)
        assert pret.etat == "pret" and pret.manque == ()
        assert len(json.loads((tmp_path / "core/opsys/agents.json").read_text())["entries"]) == 10
        assert instance.initialiser(opsys_home, **kwargs).etat == "pret"
    finally:
        stockage.liberer()


def test_cli_provisionnement_exige_limites_et_authentification(session, monkeypatch):
    import io
    args = ["agents-base", "provisionner", "--par", "base-admin-qa", "--limite-tours", "8",
            "--limite-reessais", "2", "--limite-concurrence", "1",
            "--budget-entreprise-jour", "10000000", "--budget-entreprise-mois", "100000000"]
    with pytest.raises(SystemExit) as exc:
        cli.construire_parseur().parse_args(args[:-2])
    assert exc.value.code == 2
    with session() as cnx:
        _admin(cnx)
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert cli.main(args) == 1
    with session() as cnx:
        assert agents.lister(cnx, inclure_inactifs=True) == []

    class TerminalQA(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stdin", TerminalQA())
    monkeypatch.setattr(cli, "_lire_mot_de_passe_personne", lambda: "qa-password-base-1234")
    assert cli.main(args) == 0
    with session() as cnx:
        assert len(agents_base.lire(cnx, charger_departements())) == 10
