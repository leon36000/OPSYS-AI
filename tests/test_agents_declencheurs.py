"""Intention cron réelle SQLite et identité humaine DB, sans cron/provider exécuté."""

from __future__ import annotations

import importlib
import json
import sys

import pytest
from alembic import command, op
from alembic.script import ScriptDirectory
from sqlalchemy import event, insert, inspect, select, update

from opsys import agents, identite, stockage
from opsys.departements import charger_departements
from opsys.outils import Autonomie, Niveau
from opsys.stockage.schema import AGENTS_CONFIGURABLES as PROFILS
from opsys.stockage.schema import AGENTS_DECLENCHEURS_COMMANDES as COMMANDES
from opsys.stockage.schema import AGENTS_DECLENCHEURS_INTENTIONS as INTENTIONS
from opsys.stockage.schema import JOURNAL


@pytest.fixture(autouse=True)
def _base_isolee(monkeypatch, opsys_home):
    monkeypatch.delenv("OPSYS_BASE_URL", raising=False)
    monkeypatch.setenv("OPENCLAW_CONFIG_DIR", str(opsys_home / "core"))


@pytest.fixture
def profil(session, nathan, opsys_home):
    deps = charger_departements()
    with session() as cnx:
        agents.creer(cnx, deps, {
            "id": "dossiers-fictifs", "departement": "m03-estimation",
            "responsabilite": "Préparer les dossiers fictifs sans envoi externe",
            "palier_modele": "standard", "outils": [], "budget_jour": 1000, "budget_mois": 10000,
            "limite_tours": 8, "limite_reessais": 2, "limite_concurrence": 1,
            "declencheurs": [{"type": "cron", "expression": "0 7 * * 1-5"}],
        }, par=nathan, mutation_id="creation-cron-fictive")
        agents.definir_actif(cnx, "dossiers-fictifs", deps, True, par=nathan,
                             mutation_id="activation-cron-fictive", revision_attendue=1)
    policy = {
        "version": 1, "departements": {"m03-estimation": "global"},
        "agents": {"opsys-agent-dossiers-fictifs": {"departement": "m03-estimation", "mode": "global"}},
        "procedures_globales": ["procedures"],
    }
    dossier = opsys_home / "core" / "opsys"
    dossier.mkdir(parents=True)
    fichier = dossier / "memoire-autorites.json"
    fichier.write_text(json.dumps(policy), encoding="utf-8")
    return deps, fichier


def _module():
    return importlib.import_module("opsys.agents_declencheurs")


def _demander(deps, mutation="demande-cron-fictive", **kwargs):
    return _module().demander(
        deps, "dossiers-fictifs", par="nathan", revision_attendue=2,
        fuseau="America/Toronto", mutation_id=mutation, **kwargs,
    )


def _modifier(cnx, deps, changements, mutation):
    courant = agents.obtenir(cnx, "dossiers-fictifs")
    spec = {k: courant[k] for k in (
        "id", "departement", "responsabilite", "palier_modele", "outils", "budget_jour", "budget_mois",
        "limite_tours", "limite_reessais", "limite_concurrence", "declencheurs",
    )}
    spec.update(changements)
    return agents.modifier(cnx, "dossiers-fictifs", deps, spec, par="nathan",
                           mutation_id=mutation, revision_attendue=courant["revision"])


def _choisir_outils(profil, session, departement, noms):
    """Configure un mandat fictif avec les métadonnées du catalogue réel, sans appeler ses outils."""
    deps, fichier = profil
    with session() as cnx:
        resultat = _modifier(cnx, deps, {"departement": departement, "outils": noms},
                             "selection-outils-cron-fictive")
    politique = json.loads(fichier.read_text())
    politique["departements"][departement] = "global"
    politique["agents"]["opsys-agent-dossiers-fictifs"] = {"departement": departement, "mode": "global"}
    fichier.write_text(json.dumps(politique))
    return resultat["revision"]


def _aucune_remise_ni_trace_cron(session):
    with session() as cnx:
        assert cnx.scalar(select(INTENTIONS.c.id)) is None
        assert cnx.scalar(select(COMMANDES.c.mutation_id)) is None
        assert cnx.scalar(select(JOURNAL.c.id).where(JOURNAL.c.action.like("agents.cron.%"))) is None


@pytest.mark.parametrize("departement,noms,metadonnees,natifs", [
    (
        "m03-estimation", ["m3_lire_devis", "m3_proposer_calibration_temps"],
        [(Autonomie.T0, Niveau.N0), (Autonomie.T1, Niveau.N2)],
        ["opsys_m3__m3_lire_devis", "opsys_m3__m3_proposer_calibration_temps"],
    ),
    (
        "m07-marketing", ["m7_proposer_contenus_chantier"],
        [(Autonomie.T1, Niveau.N1)], ["opsys_m7__m7_proposer_contenus_chantier"],
    ),
])
def test_outils_catalogue_reel_projetes_et_revalides_sans_execution(
    profil, session, monkeypatch, departement, noms, metadonnees, natifs,
):
    deps, _ = profil
    catalogue = {outil.nom: outil for outil in deps[departement].charger_outils()}
    assert [(catalogue[nom].autonomie, catalogue[nom].niveau_effectif) for nom in noms] == metadonnees
    revision = _choisir_outils(profil, session, departement, noms)
    module = _module()
    verifier = module.admission_agents.verifier_outil_runtime
    controles = []

    def observer_controle(cnx, agent_id, departements, outil, revision_profil, **kwargs):
        resultat = verifier(cnx, agent_id, departements, outil, revision_profil, **kwargs)
        controles.append((agent_id, outil, revision_profil, kwargs.get("verrouiller"), resultat["autorise"]))
        return resultat

    monkeypatch.setattr(module.admission_agents, "verifier_outil_runtime", observer_controle)
    demande = module.demander(deps, "dossiers-fictifs", par="nathan", revision_attendue=revision,
                             fuseau="America/Toronto", mutation_id="outils-valides-cron-fictif")
    projection = module.projeter(deps, demande["intentions"][0], par="nathan")
    assert projection["native"]["params"]["payload"]["toolsAllow"] == natifs
    argv = projection["argv"]
    assert argv[argv.index("--tools") + 1] == ",".join(natifs)
    assert set(controles) == {("dossiers-fictifs", natif, revision, True, True) for natif in natifs}
    assert len(controles) >= 2 * len(natifs)  # Admission de l'intention ET projection réellement contrôlées.
    assert projection["execute"] is False


@pytest.mark.parametrize("departement,nom,autonomie,niveau", [
    ("m03-estimation", "m3_creer_devis", Autonomie.T1, Niveau.N3),
    ("m05-financecore", "m5_corriger_facture_fournisseur", Autonomie.T2, Niveau.N4),
    ("m05-financecore", "m5_enregistrer_paiement_facture", Autonomie.T3, Niveau.N5),
])
def test_outils_catalogue_frontiere_humaine_refuses_sans_intention(
    profil, session, departement, nom, autonomie, niveau,
):
    deps, _ = profil
    outil = next(outil for outil in deps[departement].charger_outils() if outil.nom == nom)
    assert (outil.autonomie, outil.niveau_effectif) == (autonomie, niveau)
    revision = _choisir_outils(profil, session, departement, [nom])
    with pytest.raises(_module().DeclencheurRefuse, match="OUTIL-FRONTIERE-HUMAINE"):
        _module().demander(deps, "dossiers-fictifs", par="nathan", revision_attendue=revision,
                          fuseau="America/Toronto", mutation_id="frontiere-outil-cron-fictive")
    _aucune_remise_ni_trace_cron(session)


def test_outil_reel_etranger_refuse_par_profil_et_apres_alteration_sql(profil, session):
    deps, _ = profil
    finance = next(outil for outil in deps["m05-financecore"].charger_outils()
                   if outil.nom == "m5_calculer_taxes_tps_tvq")
    assert finance.autonomie == Autonomie.T0 and finance.niveau_effectif == Niveau.N0
    with pytest.raises(ValueError, match="hors du département"), session() as cnx:
        _modifier(cnx, deps, {"outils": [finance.nom]}, "outil-etranger-cron-fictif")
    with session() as cnx:
        assert agents.obtenir(cnx, "dossiers-fictifs")["revision"] == 2
        cnx.execute(update(PROFILS).values(outils=json.dumps([finance.nom])))
    with pytest.raises(_module().DeclencheurRefuse, match="PROFIL-INVALIDE"):
        _demander(deps)
    _aucune_remise_ni_trace_cron(session)


def test_revision_outils_changee_refuse_ancienne_projection_et_rejeu(profil, session):
    deps, _ = profil
    revision = _choisir_outils(profil, session, "m03-estimation", ["m3_lire_devis"])
    with pytest.raises(_module().DeclencheurRefuse, match="REVISION-PERIMEE"):
        _demander(deps)
    _aucune_remise_ni_trace_cron(session)
    kwargs = {"par": "nathan", "revision_attendue": revision, "fuseau": "America/Toronto",
              "mutation_id": "revision-outils-cron-fictive"}
    demande = _module().demander(deps, "dossiers-fictifs", **kwargs)
    with session() as cnx:
        _modifier(cnx, deps, {"outils": []}, "retrait-outil-profil-fictif")
    with pytest.raises(_module().DeclencheurRefuse, match="REVISION-PERIMEE"):
        _module().projeter(deps, demande["intentions"][0], par="nathan")
    with pytest.raises(_module().DeclencheurRefuse, match="REVISION-PERIMEE"):
        _module().demander(deps, "dossiers-fictifs", **kwargs)
    with session() as cnx:
        assert list(cnx.scalars(select(INTENTIONS.c.id))) == demande["intentions"]
        assert list(cnx.scalars(select(COMMANDES.c.mutation_id))) == [kwargs["mutation_id"]]


@pytest.mark.parametrize("retrait", ["role", "revision", "outil"])
def test_retrait_pendant_verification_outil_reelle_annule_intention_et_recu(
    profil, session, monkeypatch, retrait,
):
    deps, _ = profil
    revision = _choisir_outils(profil, session, "m03-estimation", ["m3_lire_devis"])
    module = _module()
    verifier = module.admission_agents.verifier_outil_runtime
    controles = []

    def verifier_puis_retirer(cnx, agent_id, departements, outil, revision_profil, **kwargs):
        resultat = verifier(cnx, agent_id, departements, outil, revision_profil, **kwargs)
        controles.append((outil, revision_profil, resultat["autorise"]))
        assert kwargs == {"verrouiller": True}
        if retrait == "role":
            identite.retirer_role(cnx, "nathan", "nathan_owner")
        elif retrait == "revision":
            agents.definir_actif(cnx, agent_id, deps, False, par="nathan",
                                 mutation_id="retrait-pendant-checker-fictif", revision_attendue=revision)
        else:
            cnx.execute(update(PROFILS).where(PROFILS.c.id == agent_id).values(outils="[]"))
        return resultat

    monkeypatch.setattr(module.admission_agents, "verifier_outil_runtime", verifier_puis_retirer)
    erreur = PermissionError if retrait == "role" else module.DeclencheurRefuse
    motif = "administration active" if retrait == "role" else (
        "REVISION-PERIMEE" if retrait == "revision" else "SOURCE-MODIFIEE"
    )
    with pytest.raises(erreur, match=motif):
        module.demander(deps, "dossiers-fictifs", par="nathan", revision_attendue=revision,
                        fuseau="America/Toronto", mutation_id="retire-checker-intention-fictive")
    assert controles == [("opsys_m3__m3_lire_devis", revision, True)]
    _aucune_remise_ni_trace_cron(session)
    # Une injection dans la transaction SQLite ne constitue pas une concurrence PostgreSQL.
    with session() as cnx:
        profil_retabli = agents.obtenir(cnx, "dossiers-fictifs")
        assert profil_retabli["revision"] == revision and profil_retabli["actif"] is True
        assert profil_retabli["outils"] == ["m3_lire_devis"]
        assert identite.personne_active(cnx, "nathan").roles == {"nathan_owner"}


def test_intention_durable_rejeu_et_projection_native_exacte(profil, session):
    deps, _ = profil
    premier = _demander(deps)
    assert _demander(deps) == premier
    assert len(premier["intentions"]) == 1
    ident = premier["intentions"][0]
    projection = _module().projeter(deps, ident, par="nathan")
    assert projection["native"]["method"] == "cron.add"
    params = projection["native"]["params"]
    assert params["agentId"] == "opsys-agent-dossiers-fictifs"
    assert params["sessionTarget"] == "isolated" and params["delivery"] == {"mode": "none"}
    assert params["schedule"] == {"kind": "cron", "expr": "0 7 * * 1-5", "tz": "America/Toronto"}
    assert "enabled" not in params
    assert params["payload"]["timeoutSeconds"] == 120
    assert projection["etat"] == "a_declarer" and projection["execute"] is False
    assert "--declaration-key" in projection["argv"] and "--no-deliver" in projection["argv"]
    with session() as cnx:
        assert cnx.exec_driver_sql("SELECT count(*) FROM agents_declencheurs_intentions").scalar() == 1


def test_retrait_role_apres_creation_refuse_meme_rejeu(profil, session):
    deps, _ = profil
    ident = _demander(deps)["intentions"][0]
    with session() as cnx:
        identite.retirer_role(cnx, "nathan", "nathan_owner")
    with pytest.raises(PermissionError):
        _module().projeter(deps, ident, par="nathan")
    with pytest.raises(PermissionError):
        _demander(deps)


@pytest.mark.parametrize("acteur", ["admin-inexistant", "employe-fictif", "agent-fictif"])
def test_identite_humaine_db_exigee_sans_faux_role(profil, session, acteur):
    deps, _ = profil
    with session() as cnx:
        identite.creer_personne(cnx, "employe-fictif", "Employé", "mot-de-passe-fictif-2026", ["employee"])
        identite.creer_personne(cnx, "agent-fictif", "Agent", "mot-de-passe-fictif-2026", ["system_agent"])
    with pytest.raises(PermissionError):
        _module().demander(deps, "dossiers-fictifs", par=acteur, revision_attendue=2,
                          fuseau="America/Toronto", mutation_id="humain-invalide-fictif")
    with session() as cnx:
        assert cnx.scalar(select(INTENTIONS.c.id)) is None
        assert cnx.scalar(select(COMMANDES.c.mutation_id)) is None


def test_meme_cle_fuseau_different_conflit_aucune_nouvelle_intention(profil, session):
    deps, _ = profil
    initial = _demander(deps)
    with pytest.raises(_module().DeclencheurRefuse, match="IDEMPOTENCE-CONFLIT"):
        _module().demander(deps, "dossiers-fictifs", par="nathan", revision_attendue=2,
                          fuseau="UTC", mutation_id="demande-cron-fictive")
    with session() as cnx:
        assert list(cnx.scalars(select(INTENTIONS.c.id))) == initial["intentions"]


@pytest.mark.parametrize("fuseau", ["", "inconnu/Fictif", "America/Toronto;commande", True])
def test_fuseau_explicite_pas_fallback_hote(profil, session, fuseau):
    deps, _ = profil
    with pytest.raises(_module().DeclencheurRefuse, match="FUSEAU-INVALIDE"):
        _module().demander(deps, "dossiers-fictifs", par="nathan", revision_attendue=2,
                          fuseau=fuseau, mutation_id="fuseau-invalide-fictif")
    with session() as cnx:
        assert cnx.scalar(select(INTENTIONS.c.id)) is None


@pytest.mark.parametrize("genre", ["client", "absente", "profil_absent"])
def test_ancienne_route_client_sans_contexte_refuse_pas_global(profil, session, genre):
    deps, fichier = profil
    if genre == "absente":
        fichier.unlink()
    else:
        policy = json.loads(fichier.read_text())
        if genre == "client":
            policy["departements"]["m03-estimation"] = "client_session"
            policy["agents"]["opsys-agent-dossiers-fictifs"]["mode"] = "client_session"
        else:
            policy["agents"] = {}
        fichier.write_text(json.dumps(policy))
    with pytest.raises(_module().DeclencheurRefuse, match="MEMOIRE"):
        _demander(deps)
    with session() as cnx:
        assert cnx.scalar(select(INTENTIONS.c.id)) is None


def test_revalidation_apres_construction_retrait_vivant_aucune_projection(profil, session, monkeypatch):
    deps, _ = profil
    ident = _demander(deps)["intentions"][0]
    module = _module()
    original = module._declaration

    def construire_et_retirer(*args):
        plan = original(*args)
        with session() as cnx:
            identite.retirer_role(cnx, "nathan", "nathan_owner")
        return plan

    monkeypatch.setattr(module, "_declaration", construire_et_retirer)
    with pytest.raises(PermissionError):
        module.projeter(deps, ident, par="nathan")
    # L'injection est dans la transaction SQLite : ni retrait injecté ni état de remise ne commit.
    with session() as cnx:
        assert identite.personne_active(cnx, "nathan").roles == {"nathan_owner"}
        assert cnx.scalar(select(INTENTIONS.c.statut)) == "a_declarer"


def test_autre_admin_ne_ressuscite_pas_le_mandant_revoque(profil, session):
    deps, _ = profil
    ident = _demander(deps)["intentions"][0]
    with session() as cnx:
        identite.creer_personne(cnx, "admin-fictif", "Admin", "mot-de-passe-fictif-admin", ["admin"])
        identite.retirer_role(cnx, "nathan", "nathan_owner")
    with pytest.raises(PermissionError):
        _module().projeter(deps, ident, par="admin-fictif")


def test_profil_modifie_sans_revision_empreinte_refuse_rejeu_et_projection(profil, session):
    deps, _ = profil
    ident = _demander(deps)["intentions"][0]
    with session() as cnx:
        cnx.execute(update(PROFILS).where(PROFILS.c.id == "dossiers-fictifs").values(
            responsabilite="Mandat changé sans révision, fixture de corruption",
        ))
    with pytest.raises(_module().DeclencheurRefuse, match="SOURCE-MODIFIEE"):
        _module().projeter(deps, ident, par="nathan")
    with pytest.raises(_module().DeclencheurRefuse, match="SOURCE-MODIFIEE"):
        _demander(deps)


def test_modification_hors_binding_memoire_ne_revoque_pas_autres_profils(profil):
    deps, fichier = profil
    ident = _demander(deps)["intentions"][0]
    politique = json.loads(fichier.read_text())
    politique["departements"]["m04-field-ops"] = "global"
    politique["agents"]["opsys-agent-autre-fictif"] = {"departement": "m04-field-ops", "mode": "global"}
    fichier.write_text(json.dumps(politique))
    plan = _module().projeter(deps, ident, par="nathan")
    assert plan["native"]["params"]["agentId"] == "opsys-agent-dossiers-fictifs"


def test_revision_nouvelle_conserve_retrait_ancien_pas_transmission(profil, session):
    deps, _ = profil
    ancien = _demander(deps)["intentions"][0]
    with session() as cnx:
        _modifier(cnx, deps, {"declencheurs": [{"type": "cron", "expression": "0 8 * * 1-5"}]},
                  "revision-cron-fictive")
    nouveau = _module().demander(deps, "dossiers-fictifs", par="nathan", revision_attendue=3,
                                fuseau="America/Toronto", mutation_id="nouvelle-intention-fictive")["intentions"][0]
    assert nouveau != ancien
    retrait = _module().projeter(deps, ancien, par="nathan")
    assert retrait["etat"] == "a_retirer" and retrait["execute"] is False
    assert retrait["native"] is None and retrait["argv"] is None
    assert _module().projeter(deps, nouveau, par="nathan")["native"]["params"]["schedule"]["expr"] == "0 8 * * 1-5"
    with pytest.raises(_module().DeclencheurRefuse, match="REVISION-PERIMEE"):
        _demander(deps)


def test_retrait_idempotent_pas_rearmement_meme_revision(profil, session):
    deps, _ = profil
    ident = _demander(deps)["intentions"][0]
    module = _module()
    demande = module.retirer(deps, "dossiers-fictifs", par="nathan", revision_attendue=2,
                             mutation_id="retirer-cron-fictif")
    assert module.retirer(deps, "dossiers-fictifs", par="nathan", revision_attendue=2,
                          mutation_id="retirer-cron-fictif") == demande
    assert module.projeter(deps, ident, par="nathan")["etat"] == "a_retirer"
    with pytest.raises(module.DeclencheurRefuse, match="INTENTION-PERIMEE"):
        _demander(deps, "autre-demande-fictive")
    with session() as cnx:
        assert cnx.scalar(select(INTENTIONS.c.statut)) == "a_retirer"


def test_profil_desactive_bloque_projection_mais_permet_demande_retrait(profil, session):
    deps, _ = profil
    ident = _demander(deps)["intentions"][0]
    with session() as cnx:
        agents.definir_actif(cnx, "dossiers-fictifs", deps, False, par="nathan",
                             mutation_id="desactivation-cron-fictive", revision_attendue=2)
    with pytest.raises(_module().DeclencheurRefuse, match="REVISION-PERIMEE"):
        _module().projeter(deps, ident, par="nathan")
    _module().retirer(deps, "dossiers-fictifs", par="nathan", revision_attendue=3,
                     mutation_id="retirer-inactif-fictif")
    assert _module().projeter(deps, ident, par="nathan")["etat"] == "a_retirer"


def test_saturation_file_sql_rollback_avant_nouveau_recu(profil, session):
    deps, _ = profil
    ident = _demander(deps)["intentions"][0]
    with session() as cnx:
        row = dict(cnx.execute(select(INTENTIONS)).mappings().one())
        autres = [{**row, "id": f"{i:064x}", "declaration_key": f"opsys-profile:{i:064x}", "statut": "a_retirer"}
                  for i in range(99)]
        cnx.execute(insert(INTENTIONS), autres)
        _modifier(cnx, deps, {"responsabilite": "Révision de fixture"}, "saturation-revision-fictive")
    with pytest.raises(_module().DeclencheurRefuse, match="FILE-SATUREE"):
        _module().demander(deps, "dossiers-fictifs", par="nathan", revision_attendue=3,
                          fuseau="UTC", mutation_id="saturation-demande-fictive")
    with session() as cnx:
        assert cnx.scalar(select(INTENTIONS.c.statut).where(INTENTIONS.c.id == ident)) == "a_declarer"
        assert list(cnx.scalars(select(COMMANDES.c.mutation_id))) == ["demande-cron-fictive"]


def test_seizieme_declaration_admise_dix_septieme_refusee(profil, session):
    deps, fichier = profil
    declencheurs = [{"type": "cron", "expression": f"0 {heure} * * 1-5"} for heure in range(16)]
    with session() as cnx:
        _modifier(cnx, deps, {"declencheurs": declencheurs}, "seize-declencheurs-fictifs")
        agents.creer(cnx, deps, {
            "id": "second-fictif", "departement": "m03-estimation", "responsabilite": "Second mandat fictif",
            "palier_modele": "standard", "outils": [], "budget_jour": 1000, "budget_mois": 10000,
            "limite_tours": 8, "limite_reessais": 2, "limite_concurrence": 1,
            "declencheurs": [{"type": "cron", "expression": "0 9 * * *"}],
        }, par="nathan", mutation_id="second-profil-cron-fictif")
        agents.definir_actif(cnx, "second-fictif", deps, True, par="nathan",
                             mutation_id="second-actif-cron-fictif", revision_attendue=1)
    policy = json.loads(fichier.read_text())
    policy["agents"]["opsys-agent-second-fictif"] = {"departement": "m03-estimation", "mode": "global"}
    fichier.write_text(json.dumps(policy))
    resultat = _module().demander(deps, "dossiers-fictifs", par="nathan", revision_attendue=3,
                                 fuseau="UTC", mutation_id="seize-intentions-fictives")
    assert len(resultat["intentions"]) == 16
    with pytest.raises(_module().DeclencheurRefuse, match="FILE-SATUREE"):
        _module().demander(deps, "second-fictif", par="nathan", revision_attendue=2,
                          fuseau="UTC", mutation_id="dix-septieme-intention-fictive")
    with session() as cnx:
        assert len(cnx.execute(select(INTENTIONS.c.id)).all()) == 16
        assert list(cnx.scalars(select(COMMANDES.c.mutation_id))) == ["seize-intentions-fictives"]


def test_mandat_prive_ni_modele_ni_secret_dans_argv_projection(profil, session):
    deps, _ = profil
    with session() as cnx:
        _modifier(cnx, deps, {"responsabilite": "Mandat fictif privé avec sentinelle-cle-privee"},
                  "mandat-prive-cron-fictif")
    ident = _module().demander(deps, "dossiers-fictifs", par="nathan", revision_attendue=3,
                              fuseau="UTC", mutation_id="mandat-prive-intention-fictive")["intentions"][0]
    plan = _module().projeter(deps, ident, par="nathan")
    assert "sentinelle-cle-privee" not in json.dumps(plan)
    assert "model" not in plan["native"]["params"]["payload"]
    assert not set(plan["argv"]) & {"--token", "--command", "--command-argv", "--model", "--fallbacks"}


@pytest.mark.parametrize("expression", ["90 7 * * *", "0 28 * * *", "0 7 * * *;commande", "0 7 * * MON", "0 7 * * */0"])
def test_expression_cron_hors_sous_ensemble_refusee(profil, session, expression):
    deps, _ = profil
    with session() as cnx:
        _modifier(cnx, deps, {"declencheurs": [{"type": "cron", "expression": expression}]},
                  "expression-cron-fictive")
    with pytest.raises(_module().DeclencheurRefuse, match="EXPRESSION-INVALIDE"):
        _module().demander(deps, "dossiers-fictifs", par="nathan", revision_attendue=3,
                          fuseau="UTC", mutation_id="expression-intention-fictive")
    with session() as cnx:
        assert cnx.scalar(select(INTENTIONS.c.id)) is None


def test_cle_native_alteree_refuse_y_compris_retrait(profil, session):
    deps, _ = profil
    ident = _demander(deps)["intentions"][0]
    with session() as cnx:
        cnx.execute(update(INTENTIONS).values(declaration_key="opsys-profile-autre-fictif", statut="a_retirer"))
    with pytest.raises(_module().DeclencheurRefuse, match="INTENTION-ALTEREE"):
        _module().projeter(deps, ident, par="nathan")


def test_doubles_cles_json_profil_refusees_avant_validation_metier(profil, session):
    deps, _ = profil
    with session() as cnx:
        cnx.execute(update(PROFILS).values(declencheurs=(
            '[{"type":"cron","expression":"0 7 * * *","expression":"0 8 * * *"}]'
        )))
    with pytest.raises(_module().DeclencheurRefuse, match="DONNEES-INVALIDES"):
        _demander(deps)
    with session() as cnx:
        assert cnx.scalar(select(INTENTIONS.c.id)) is None


def test_doubles_cles_json_recu_ne_forgent_pas_execution(profil, session):
    deps, _ = profil
    _demander(deps)
    with session() as cnx:
        initial = cnx.scalar(select(COMMANDES.c.reponse))
        altere = initial.replace('"execute":false', '"execute":false,"execute":true')
        assert altere != initial
        cnx.execute(update(COMMANDES).values(reponse=altere))
    with pytest.raises(_module().DeclencheurRefuse, match="DONNEES-INVALIDES"):
        _demander(deps)


def test_classification_memoire_json_trop_imbriquee_refus_metier_ferme(profil, session):
    deps, fichier = profil
    profondeur = sys.getrecursionlimit() + 20
    texte = "[" * profondeur + "0" + "]" * profondeur
    assert len(texte.encode("utf-8")) <= 131072  # Dans la borne réelle du lecteur R33.
    fichier.write_text(texte)
    with pytest.raises(_module().DeclencheurRefuse, match="CLASSIFICATION-MEMOIRE-INDISPONIBLE"):
        _demander(deps)
    with session() as cnx:
        assert cnx.scalar(select(INTENTIONS.c.id)) is None


def test_lire_en_attente_count_et_limit_sql_omis_explicitement(profil, session, monkeypatch):
    deps, _ = profil
    _demander(deps)
    statements = []

    def noter(_cnx, _cursor, statement, _params, _context, _many):
        statements.append(statement.lower())

    moteur = stockage.moteur()
    event.listen(moteur, "before_cursor_execute", noter)
    try:
        lecture = _module().lire_en_attente(par="nathan", limite=1)
    finally:
        event.remove(moteur, "before_cursor_execute", noter)
    assert lecture["total"] == 1 and lecture["retournes"] == 1 and lecture["omis"] == 0
    assert lecture["execution_core"] == "non_observee"
    assert any("count(" in sql and "agents_declencheurs_intentions" in sql for sql in statements)
    assert any("limit" in sql and "agents_declencheurs_intentions" in sql for sql in statements)
    for invalide in (0, 11, True):
        with pytest.raises(_module().DeclencheurRefuse, match="LIMITE-INVALIDE"):
            _module().lire_en_attente(par="nathan", limite=invalide)


def test_pg_refuse_avant_ouverture_et_ecriture(profil, monkeypatch):
    deps, _ = profil
    monkeypatch.setattr(stockage, "url_base", lambda: "postgresql://fictif.invalid/base")

    def ouverture_interdite(*_args, **_kwargs):
        pytest.fail("le backend refusé ne doit pas ouvrir une transaction")

    monkeypatch.setattr(stockage, "transaction", ouverture_interdite)
    with pytest.raises(_module().DeclencheurRefuse, match="SQLITE-REQUIS"):
        _demander(deps)


def test_migration_reelle_0018_vers_0019_preserve_ancienne_base(tmp_path):
    url = f"sqlite:///{tmp_path / 'migration-fictive.db'}"
    with stockage.moteur(url).begin() as cnx:
        conf = stockage._config()
        conf.attributes["connection"] = cnx
        command.upgrade(conf, "0018")
        identite.creer_personne(cnx, "migration-fictive", "Avant migration", "mot-de-passe-migration-fictif", ["admin"])
        ident = cnx.exec_driver_sql("SELECT * FROM opsys_instance").one()
        personne = cnx.exec_driver_sql("SELECT * FROM personnes").one()
    assert stockage.revision_courante(url) == "0018"
    # Éprouver la migration historique elle-même, puis la tête actuelle sans la figer.
    with stockage.moteur(url).begin() as cnx:
        conf = stockage._config()
        conf.attributes["connection"] = cnx
        command.upgrade(conf, "0019")
    assert stockage.revision_courante(url) == "0019"
    assert stockage.migrer(url) == ScriptDirectory.from_config(stockage._config()).get_current_head()
    assert stockage.migrer(url) == ScriptDirectory.from_config(stockage._config()).get_current_head()
    with stockage.moteur(url).begin() as cnx:
        assert cnx.exec_driver_sql("SELECT * FROM opsys_instance").one() == ident
        assert cnx.exec_driver_sql("SELECT * FROM personnes").one() == personne
        for table in (INTENTIONS, COMMANDES):
            assert {c["name"] for c in inspect(cnx).get_columns(table.name)} == set(table.c.keys())


def test_erreur_migration_rollback_tables_et_revision_avant_reprise(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'migration-erreur-fictive.db'}"
    with stockage.moteur(url).begin() as cnx:
        conf = stockage._config()
        conf.attributes["connection"] = cnx
        command.upgrade(conf, "0018")
    original = op.create_table

    def creer_et_refuser(nom, *args, **kwargs):
        if nom == "agents_declencheurs_commandes":
            raise RuntimeError("panne de migration fictive après première table")
        return original(nom, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(op, "create_table", creer_et_refuser)
        with pytest.raises(RuntimeError, match="panne de migration fictive"):
            stockage.migrer(url)
    assert stockage.revision_courante(url) == "0018"
    with stockage.moteur(url).begin() as cnx:
        assert INTENTIONS.name not in inspect(cnx).get_table_names()
        assert COMMANDES.name not in inspect(cnx).get_table_names()
    # Éprouver la migration historique elle-même, puis la tête actuelle sans la figer.
    with stockage.moteur(url).begin() as cnx:
        conf = stockage._config()
        conf.attributes["connection"] = cnx
        command.upgrade(conf, "0019")
    assert stockage.revision_courante(url) == "0019"
    assert stockage.migrer(url) == ScriptDirectory.from_config(stockage._config()).get_current_head()
