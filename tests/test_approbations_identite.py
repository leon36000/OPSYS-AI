"""Approbations N3-N5 par rôle, attestation N5, et file du propriétaire (ADR-0009 §4/§5, PLAN T1.3-a).

Complète `tests/test_approbations_journal.py` (mécanique générale de la file, T2/N4, aucune
identité) : ici, la politique par département, l'identité et l'attestation N5 sont le sujet.
"""

from __future__ import annotations

import dataclasses
import json
import shutil

import demo_outils
import pytest
import yaml

from opsys import approbations, cli, identite
from opsys.departements import DEFAUT_ROLES_NIVEAU, PolitiqueApprobation, lire_manifeste, verifier_attentes
from opsys.outils import Autonomie, Niveau, Outil, niveau_par_defaut
from opsys.politiques import approbation_requise, approbation_requise_niveau

_SCHEMA = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}


def _ok(x: int) -> dict:
    return {"x": x}


OUTIL_N4 = Outil("m9_ok", "Réussit.", _SCHEMA, _ok, Autonomie.T2)  # niveau par défaut : N4


# -- N (ADR-0009 §4) : correspondance par défaut depuis T, aucune régression --------------------


@pytest.mark.parametrize(
    ("autonomie", "niveau_attendu"),
    [(Autonomie.T0, Niveau.N0), (Autonomie.T1, Niveau.N3), (Autonomie.T2, Niveau.N4), (Autonomie.T3, Niveau.N5)],
)
def test_correspondance_par_defaut_documentee(autonomie, niveau_attendu):
    assert niveau_par_defaut(autonomie) is niveau_attendu
    outil = Outil("m9_test", "x", _SCHEMA, _ok, autonomie)
    assert outil.niveau is None and outil.niveau_effectif is niveau_attendu


def test_niveau_explicite_prevaut_sur_le_defaut():
    outil = Outil("m9_test", "x", _SCHEMA, _ok, Autonomie.T1, niveau=Niveau.N2)
    assert outil.niveau_effectif is Niveau.N2  # T1 vaudrait N3 par défaut


def test_niveau_invalide_refuse():
    with pytest.raises(ValueError, match="niveau invalide"):
        Outil("m9_test", "x", _SCHEMA, _ok, Autonomie.T1, niveau="N9")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("niveau", "ombre", "supervise", "autonome"),
    [
        (Niveau.N0, False, False, False), (Niveau.N2, False, False, False),
        (Niveau.N3, True, False, False), (Niveau.N4, True, True, False), (Niveau.N5, True, True, True),
    ],
)
def test_regle_d_approbation_exprimee_en_n(niveau, ombre, supervise, autonome):
    assert approbation_requise_niveau(niveau, "ombre") is ombre
    assert approbation_requise_niveau(niveau, "supervise") is supervise
    assert approbation_requise_niveau(niveau, "autonome") is autonome


@pytest.mark.parametrize("autonomie", list(Autonomie))
@pytest.mark.parametrize("mode", ["ombre", "supervise", "autonome"])
def test_t_delegue_a_n_sans_regression(autonomie, mode):
    """`approbation_requise` (T, compatibilité) == `approbation_requise_niveau` via la correspondance
    par défaut : aucun appelant existant ne change de comportement."""
    assert approbation_requise(autonomie, mode) == approbation_requise_niveau(niveau_par_defaut(autonomie), mode)


# -- politique de département (ADR-0009 §5) : bloc `approbations` du manifeste ------------------


def _copie(racine_demo, tmp_path):
    cible = tmp_path / "departements"
    shutil.copytree(racine_demo, cible)
    return cible / "m09-demo"


def _modifier(dossier, **changements):
    chemin = dossier / "department.yaml"
    donnees = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    donnees.update(changements)
    chemin.write_text(yaml.safe_dump(donnees, allow_unicode=True), encoding="utf-8")


def test_politique_absente_du_manifeste_est_la_plus_restrictive(departements_demo):
    dep = departements_demo["m09-demo"]  # aucun bloc `approbations` dans le manifeste de démo
    assert dep.roles_autorises(Niveau.N3) == DEFAUT_ROLES_NIVEAU == frozenset({"nathan_owner"})
    assert dep.roles_autorises(Niveau.N4) == DEFAUT_ROLES_NIVEAU
    assert dep.roles_autorises(Niveau.N5) == DEFAUT_ROLES_NIVEAU


def test_politique_declaree_valide_et_niveau_non_couvert_retombe_sur_le_defaut(racine_demo, tmp_path):
    dossier = _copie(racine_demo, tmp_path)
    _modifier(dossier, approbations={"n3": ["manager", "nathan_owner"], "n4": ["nathan_owner"]})
    dep = lire_manifeste(dossier)
    assert dep.roles_autorises(Niveau.N3) == {"manager", "nathan_owner"}
    assert dep.roles_autorises(Niveau.N4) == {"nathan_owner"}
    assert dep.roles_autorises(Niveau.N5) == DEFAUT_ROLES_NIVEAU  # n5 non déclaré : défaut


@pytest.mark.parametrize(
    ("bloc", "message"),
    [
        ("pas un objet", "approbations doit être un objet"),
        ({"n6": ["nathan_owner"]}, "clé\\(s\\) inconnue\\(s\\)"),
        ({"n3": []}, "liste non vide"),
        ({"n3": "nathan_owner"}, "liste non vide"),
        ({"n3": ["patron"]}, "rôle\\(s\\) inconnu\\(s\\)"),
        ({"n5": ["finance"]}, "ne se déclare pas"),
        ({"n5": ["nathan_owner"]}, "ne se déclare pas"),  # même une valeur "conforme" : n5 est fixe
    ],
)
def test_politique_invalide_refusee_au_chargement(racine_demo, tmp_path, bloc, message):
    dossier = _copie(racine_demo, tmp_path)
    _modifier(dossier, approbations=bloc)
    with pytest.raises(ValueError, match=message):
        lire_manifeste(dossier)


def test_politique_n5_toujours_nathan_owner_seul_jamais_configurable(racine_demo, tmp_path):
    """N5 est une frontière fixe de l'ADR (§5) : aucun bloc `approbations` (n3/n4 très permissifs
    par ailleurs) ne peut l'élargir — elle retombe toujours sur `DEFAUT_ROLES_NIVEAU`."""
    dossier = _copie(racine_demo, tmp_path)
    _modifier(dossier, approbations={"n3": ["employee", "client"], "n4": ["employee"]})
    dep = lire_manifeste(dossier)
    assert dep.roles_autorises(Niveau.N5) == frozenset({"nathan_owner"})


# -- approbations.decider : rôle autorisé par département, personne active, attestation N5 ------


def _dep_avec_politique(departements_demo, **roles_par_niveau: list[str]):
    politique = PolitiqueApprobation(roles={Niveau[cle.upper()]: frozenset(v) for cle, v in roles_par_niveau.items()})
    return dataclasses.replace(departements_demo["m09-demo"], politique_approbation=politique)


def test_employe_ne_peut_pas_approuver_n4_le_proprietaire_peut(session, departements_demo):
    dep = _dep_avec_politique(departements_demo, n4=["manager", "nathan_owner"])
    deps = {"m09-demo": dep}
    with session() as cnx:
        identite.creer_personne(cnx, "employe1", "Un Employé", "mot-de-passe-employe-1234", ["employee"])
        identite.creer_personne(cnx, "nathan", "Nathan", "mot-de-passe-nathan-1234", ["nathan_owner"])
        ident = approbations.creer_demande(cnx, "m09-demo", "m9_ok", {"x": 1}, niveau=Niveau.N4)
        with pytest.raises(ValueError, match="aucun rôle autorisé"):
            approbations.decider(cnx, ident, True, "employe1", {"m9_ok": OUTIL_N4}, deps)
        [encore] = approbations.lister(cnx, "en_attente")
        assert encore["id"] == ident  # fail-closed : rien exécuté, la demande reste en attente

        decision = approbations.decider(cnx, ident, True, "nathan", {"m9_ok": OUTIL_N4}, deps)
    assert decision["statut"] == "executee"


def test_manager_autorise_par_le_departement_peut_decider(session, departements_demo):
    dep = _dep_avec_politique(departements_demo, n4=["manager", "nathan_owner"])
    deps = {"m09-demo": dep}
    with session() as cnx:
        identite.creer_personne(cnx, "mgr", "Une Gérante", "mot-de-passe-gerante-1234", ["manager"])
        ident = approbations.creer_demande(cnx, "m09-demo", "m9_ok", {"x": 2}, niveau=Niveau.N4)
        decision = approbations.decider(cnx, ident, True, "mgr", {"m9_ok": OUTIL_N4}, deps)
    assert decision["statut"] == "executee"
    with session() as cnx:
        [traitee] = approbations.lister(cnx, "executee")
    assert (traitee["decide_par"], traitee["decide_role"]) == ("mgr", "manager")


def test_personne_inactive_ne_peut_rien(session, departements_demo):
    with session() as cnx:
        identite.creer_personne(cnx, "suspendu", "Personne Suspendue", "mot-de-passe-suspendu-1234",
                                ["nathan_owner"], actif=False)
        ident = approbations.creer_demande(cnx, "m09-demo", "m9_ok", {"x": 3}, niveau=Niveau.N4)
        with pytest.raises(ValueError, match="inconnue ou inactive"):
            approbations.decider(cnx, ident, True, "suspendu", {"m9_ok": OUTIL_N4}, departements_demo)
        with pytest.raises(ValueError, match="inconnue ou inactive"):
            approbations.decider(cnx, ident, False, "suspendu", {}, departements_demo)  # refus : même garde
        [encore] = approbations.lister(cnx, "en_attente")
    assert encore["id"] == ident


def test_decision_sans_personne_refusee(session, departements_demo):
    with session() as cnx:
        ident = approbations.creer_demande(cnx, "m09-demo", "m9_ok", {"x": 4}, niveau=Niveau.N4)
        with pytest.raises(ValueError, match="signée par une personne"):
            approbations.decider(cnx, ident, True, "", {"m9_ok": OUTIL_N4}, departements_demo)
        with pytest.raises(ValueError, match="inconnue ou inactive"):
            approbations.decider(cnx, ident, True, "personne-jamais-creee", {"m9_ok": OUTIL_N4}, departements_demo)
        [encore] = approbations.lister(cnx, "en_attente")
    assert encore["id"] == ident


def test_n5_sans_attestation_refuse_avec_attestation_accepte(session, departements_demo):
    outil_n5 = Outil("m9_n5", "Frontière humaine.", _SCHEMA, _ok, Autonomie.T3)
    with session() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan", "mot-de-passe-nathan-1234", ["nathan_owner"])
        ident = approbations.creer_demande(cnx, "m09-demo", "m9_n5", {"x": 5}, niveau=Niveau.N5)
        with pytest.raises(ValueError, match="attestation du professionnel requise"):
            approbations.decider(cnx, ident, True, "nathan", {"m9_n5": outil_n5}, departements_demo)
        [encore] = approbations.lister(cnx, "en_attente")
        assert encore["id"] == ident  # fail-closed : rien exécuté sans attestation

        incomplete = {"nom": "Alex Comptable", "profession": ""}
        with pytest.raises(ValueError, match="champ requis manquant ou vide"):
            approbations.decider(cnx, ident, True, "nathan", {"m9_n5": outil_n5}, departements_demo,
                                 attestation=incomplete)

        attestation = {"nom": "Alex Comptable", "profession": "CPA", "reference_document": "recu.pdf"}
        decision = approbations.decider(cnx, ident, True, "nathan", {"m9_n5": outil_n5}, departements_demo,
                                        attestation=attestation)
    assert decision["statut"] == "executee"
    with session() as cnx:
        [traitee] = approbations.lister(cnx, "executee")
    assert traitee["attestation"] == attestation
    assert (traitee["decide_par"], traitee["decide_role"]) == ("nathan", "nathan_owner")


def test_n5_refus_n_exige_pas_d_attestation(session, departements_demo):
    with session() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan", "mot-de-passe-nathan-1234", ["nathan_owner"])
        ident = approbations.creer_demande(cnx, "m09-demo", "m9_n5", {"x": 6}, niveau=Niveau.N5)
        refus = approbations.decider(cnx, ident, False, "nathan", {}, departements_demo, "non merci")
    assert refus == {"id": ident, "statut": "refusee"}


# -- file du propriétaire (ADR-0009 §5, PLAN T1.3-a §6) ------------------------------------------


@pytest.fixture(autouse=True)
def _vider_attentes_demo():
    demo_outils.ATTENTES_DEMO.clear()
    yield
    demo_outils.ATTENTES_DEMO.clear()


def test_file_proprietaire_agrege_demandes_et_attentes(session, departements_demo):
    demo_outils.ATTENTES_DEMO.append({
        "type": "chantier_a_reviser", "id": "wct-1", "resume": "Écart matériaux 42 %",
        "niveau": "N4", "depuis": "2026-09-01T00:00:00+00:00", "action_proposee": "réviser et approuver",
    })
    with session() as cnx:
        ident = approbations.creer_demande(cnx, "m09-demo", "m9_ok", {"x": 7}, niveau=Niveau.N4)
        file = approbations.file_proprietaire(cnx, departements_demo)
    types = {item["type"] for item in file}
    assert types == {"approbation", "chantier_a_reviser"}
    for item in file:
        assert set(item) == {"type", "id", "resume", "niveau", "depuis", "action_proposee", "departement"}
        assert item["departement"] == "m09-demo"
    # Triée par « depuis » croissant : l'attente déclarée (2026-09-01) précède la demande socle
    # (créée pendant le test, donc plus récente).
    assert [item["id"] for item in file] == ["wct-1", ident]


def test_file_proprietaire_ignore_un_departement_dont_attentes_plante(session, departements_demo):
    casse = dataclasses.replace(departements_demo["m09-demo"], module_outils="module_absent_opsys")
    with session() as cnx:
        file = approbations.file_proprietaire(cnx, {"m09-demo": casse})
    assert file == []  # ni exception, ni demi-résultat : signalé (journal), jamais bloquant


def test_file_proprietaire_signale_une_attente_mal_formee(session, departements_demo):
    demo_outils.ATTENTES_DEMO.append({"type": "incomplet"})  # champs manquants
    with session() as cnx:
        file = approbations.file_proprietaire(cnx, departements_demo)
    assert file == []  # la forme invalide est journalisée, jamais insérée telle quelle


def test_verifier_attentes_signale_un_attentes_non_appelable(departements_demo, monkeypatch):
    monkeypatch.setattr(demo_outils, "attentes", "pas une fonction")
    problemes = verifier_attentes(departements_demo)
    assert any("attentes() illisible" in p for p in problemes)


def test_charger_attentes_absent_rend_none(departements_demo, monkeypatch):
    monkeypatch.delattr(demo_outils, "attentes")
    assert departements_demo["m09-demo"].charger_attentes() is None
    assert verifier_attentes(departements_demo) == []


# -- CLI -------------------------------------------------------------------------------------------


def test_cli_approbations_file(racine_demo, session, monkeypatch, capsys):
    monkeypatch.setenv("OPSYS_DEPARTMENTS", str(racine_demo))
    with session() as cnx:
        approbations.creer_demande(cnx, "m09-demo", "m9_ok", {"x": 8}, niveau=Niveau.N4)
    capsys.readouterr()
    assert cli.main(["approbations", "file"]) == 0
    sortie = json.loads(capsys.readouterr().out)
    assert len(sortie) == 1 and sortie[0]["type"] == "approbation"


def test_cli_approbations_file_ne_requiert_pas_d_id(racine_demo, session, monkeypatch, capsys):
    monkeypatch.setenv("OPSYS_DEPARTMENTS", str(racine_demo))
    assert cli.main(["approbations", "file"]) == 0
