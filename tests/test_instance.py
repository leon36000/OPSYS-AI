"""Préparation de l'instance locale par l'installateur (PLAN T0.11) : `opsys.instance`, `opsys instance initialiser`.

Ce que ces tests prouvent : le `.env` (0600, secrets jamais régénérés, aucune valeur dans une sortie), le verdict
fail-closed qui dit quoi fournir, la configuration du core et `metier.json` générés puis relus sans changement.
Ce qu'ils ne prouvent pas : que le core accepte cette configuration et lance le moteur (job `installateur` de la CI).
"""

from __future__ import annotations

import json
import os
import re
import stat
import sys
from pathlib import Path

import pytest

from opsys import cli, instance

FICTIF = True  # aucune valeur ci-dessous n'est réelle (AGENTS.md)

RACINE = Path(__file__).resolve().parents[1]
EMBEDDINGS = {"OPSYS_EMBEDDINGS_URL": "http://127.0.0.1:11434/v1", "OPSYS_EMBEDDINGS_MODELE": "bge-m3"}
SECRETS_ATTENDUS = ["OPSYS_MCP_JETON", "OPENCLAW_GATEWAY_TOKEN", "OPSYS_CLE_M1"]


def _mode(chemin: Path) -> int:
    return stat.S_IMODE(chemin.stat().st_mode)


def _valeurs_secretes(chemin: Path) -> list[str]:
    env = instance.lire_env(chemin)
    return [valeur for nom, valeur in env.items() if re.search(r"JETON|TOKEN|CLE", nom) and len(valeur) >= 12]


def _contenu_de_tout(dossier: Path) -> dict[str, bytes]:
    return {str(p.relative_to(dossier)): p.read_bytes() for p in sorted(dossier.rglob("*")) if p.is_file()}


@pytest.fixture
def palier_standard():
    from opsys import modeles

    modeles.enregistrer_paliers({"standard": {"provider": "anthropic", "model": "claude-sonnet-5"}})


# -- assurer_env ------------------------------------------------------------------------------------------------------
def test_env_cree_en_0600_avec_les_secrets_manquants(tmp_path):
    chemin = tmp_path / "core" / ".env"
    ancien_umask = os.umask(0)  # le pire cas : aucun droit retiré par le système
    try:
        rapport = instance.assurer_env(chemin, SECRETS_ATTENDUS, {})
    finally:
        os.umask(ancien_umask)

    assert _mode(chemin) == 0o600
    assert rapport.generees == tuple(SECRETS_ATTENDUS)
    env = instance.lire_env(chemin)
    assert len(env["OPSYS_MCP_JETON"]) >= 24 and not re.search(r"\s", env["OPSYS_MCP_JETON"])  # exigé par le moteur
    assert env["OPSYS_CLE_M1"].startswith("sk-opsys-m1-")
    assert len({env[nom] for nom in SECRETS_ATTENDUS}) == 3  # trois secrets, trois valeurs


def test_aucune_valeur_dans_le_rapport(tmp_path):
    chemin = tmp_path / ".env"
    rapport = instance.assurer_env(chemin, SECRETS_ATTENDUS, {"OPSYS_PASSERELLE_URL": "http://127.0.0.1:4000/v1"})

    texte = repr(rapport) + json.dumps({"g": rapport.generees, "c": rapport.conservees, "r": rapport.reglees})
    for valeur in instance.lire_env(chemin).values():
        assert valeur not in texte


def test_un_secret_present_n_est_jamais_regenere(tmp_path):
    chemin = tmp_path / ".env"
    instance.assurer_env(chemin, SECRETS_ATTENDUS, {})
    avant = chemin.read_bytes()

    rapport = instance.assurer_env(chemin, SECRETS_ATTENDUS, {}, fabrique=lambda nom: "AUTRE-" + nom)

    assert rapport.generees == ()
    assert rapport.conservees == tuple(SECRETS_ATTENDUS)
    assert chemin.read_bytes() == avant


def test_un_secret_vide_est_genere_et_le_reste_du_fichier_est_conserve(tmp_path):
    chemin = tmp_path / ".env"
    chemin.write_text(
        "# ma note\nOPSYS_MCP_JETON=\nMA_VARIABLE=abc\nOPENCLAW_GATEWAY_TOKEN=jeton-existant-1234567890\n",
        encoding="utf-8")

    rapport = instance.assurer_env(chemin, ["OPSYS_MCP_JETON", "OPENCLAW_GATEWAY_TOKEN"], {})

    assert rapport.generees == ("OPSYS_MCP_JETON",)
    assert rapport.conservees == ("OPENCLAW_GATEWAY_TOKEN",)
    lignes = chemin.read_text(encoding="utf-8").splitlines()
    assert lignes[0] == "# ma note" and lignes[2] == "MA_VARIABLE=abc"
    assert lignes[3] == "OPENCLAW_GATEWAY_TOKEN=jeton-existant-1234567890"
    assert len(instance.lire_env(chemin)["OPSYS_MCP_JETON"]) == 64


def test_un_fichier_pose_a_la_main_avec_des_droits_larges_est_resserre(tmp_path):
    chemin = tmp_path / ".env"
    chemin.write_text("OPSYS_MCP_JETON=jeton-existant-1234567890\n", encoding="utf-8")
    chemin.chmod(0o644)

    instance.assurer_env(chemin, ["OPSYS_MCP_JETON"], {})

    assert _mode(chemin) == 0o600
    assert chemin.read_text(encoding="utf-8") == "OPSYS_MCP_JETON=jeton-existant-1234567890\n"


def test_un_reglage_fourni_remplace_la_valeur_qui_differe_seulement(tmp_path):
    chemin = tmp_path / ".env"
    instance.assurer_env(chemin, [], {"OPSYS_EMBEDDINGS_URL": "http://a:1/v1"})

    identique = instance.assurer_env(chemin, [], {"OPSYS_EMBEDDINGS_URL": "http://a:1/v1"})
    change = instance.assurer_env(chemin, [], {"OPSYS_EMBEDDINGS_URL": "http://b:2/v1"})

    assert identique.reglees == ()
    assert change.reglees == ("OPSYS_EMBEDDINGS_URL",)
    assert instance.lire_env(chemin) == {"OPSYS_EMBEDDINGS_URL": "http://b:2/v1"}


@pytest.mark.parametrize("valeur", ["a b", 'x"y', "$HOME", "a\nB=c", "#c", "x`y`", "a\\b", "", "SECRET-MARQUE-é"])
def test_une_valeur_dangereuse_est_refusee_sans_etre_repetee(tmp_path, valeur):
    chemin = tmp_path / ".env"

    with pytest.raises(instance.ErreurInstance) as refus:
        instance.assurer_env(chemin, [], {"OPSYS_EMBEDDINGS_CLE": valeur})

    assert "OPSYS_EMBEDDINGS_CLE" in str(refus.value)
    if valeur.strip():
        assert valeur not in str(refus.value)
    assert not chemin.exists()


def test_lire_env_comprend_guillemets_export_et_commentaires(tmp_path):
    chemin = tmp_path / ".env"
    chemin.write_text('# c\nA="x y"\nexport B=z\n  \nC=\nD=1=2\n', encoding="utf-8")

    assert instance.lire_env(chemin) == {"A": "x y", "B": "z", "C": "", "D": "1=2"}
    assert instance.lire_env(tmp_path / "absent") == {}


# -- initialiser ------------------------------------------------------------------------------------------------------
def _initialiser(opsys_home, **surcharge):
    reglages = {"source": RACINE, "python": Path(sys.executable), "port_gateway": None, "port_moteur": None,
                "environ": {}}
    reglages.update(surcharge)
    return instance.initialiser(opsys_home, **reglages)


def test_sans_paliers_ni_embeddings_le_verdict_dit_quoi_fournir_et_rien_d_autre_n_est_ecrit(opsys_home):
    resultat = _initialiser(opsys_home)

    assert resultat.etat == "en_attente"
    assert len(resultat.manque) == 2
    assert any("opsys paliers definir" in ligne for ligne in resultat.manque)
    assert any("OPSYS_EMBEDDINGS_URL" in ligne and "OPSYS_EMBEDDINGS_MODELE" in ligne for ligne in resultat.manque)
    assert (opsys_home / "core" / ".env").is_file()
    assert not (opsys_home / "core" / "openclaw.json").exists()
    assert not (opsys_home / "core" / "opsys").exists()


def test_avec_paliers_et_embeddings_la_configuration_du_core_est_generee(opsys_home, palier_standard):
    resultat = _initialiser(opsys_home, environ=EMBEDDINGS, port_gateway=18790, port_moteur=8766)

    assert resultat.etat == "pret" and resultat.manque == ()
    assert (resultat.port_gateway, resultat.port_moteur) == (18790, 8766)
    core = opsys_home / "core"
    racine = json.loads((core / "openclaw.json").read_text(encoding="utf-8"))
    assert {"models", "agents", "mcp", "tools", "memory", "plugins"} <= set(racine)
    assert racine["gateway"] == {
        "mode": "local", "port": 18790, "bind": "loopback", "auth": {"mode": "token"},
        "nodes": {"pairing": {"autoApproveLocal": False}},
    }
    mcp = json.loads((core / "opsys" / "mcp.json").read_text(encoding="utf-8"))
    assert all(serveur["url"].startswith("http://127.0.0.1:8766/mcp/") for serveur in mcp["servers"].values())
    metier = json.loads((core / "opsys" / "metier.json").read_text(encoding="utf-8"))
    assert metier["actif"] is True and metier["dossier"] == str(RACINE)
    assert metier["hote"] == "127.0.0.1" and metier["port"] == 8766
    assert metier["commande"] == [sys.executable, "-m", "opsys.serveur_mcp", "--http", "--hote", "127.0.0.1",
                                  "--port", "8766"]
    assert metier["env"] == {"OPSYS_HOME": str(opsys_home)}
    env = instance.lire_env(core / ".env")
    assert env["OPSYS_EMBEDDINGS_MODELE"] == "bge-m3" and env["OPSYS_PASSERELLE_URL"] == "http://127.0.0.1:4000/v1"


def test_aucun_secret_dans_la_configuration_generee_ni_dans_la_sortie(opsys_home, palier_standard, monkeypatch,
                                                                     capsys):
    for nom, valeur in EMBEDDINGS.items():
        monkeypatch.setenv(nom, valeur)

    assert cli.main(["instance", "initialiser", "--source", str(RACINE)]) == 0

    secrets_ecrits = _valeurs_secretes(opsys_home / "core" / ".env")
    assert len(secrets_ecrits) >= 12  # jetons du moteur et du Gateway, dix clés de départements

    for nom, contenu in _contenu_de_tout(opsys_home / "core").items():
        if nom == ".env":
            continue
        for secret in secrets_ecrits:
            assert secret.encode() not in contenu, f"un secret est écrit dans core/{nom}"
    assert b"${OPSYS_MCP_JETON}" in (opsys_home / "core" / "opsys" / "mcp.json").read_bytes()
    sortie = capsys.readouterr()
    for secret in secrets_ecrits:
        assert secret not in sortie.out + sortie.err


def test_initialiser_est_idempotent_et_ne_regenere_aucun_secret(opsys_home, palier_standard):
    _initialiser(opsys_home, environ=EMBEDDINGS)
    avant = _contenu_de_tout(opsys_home / "core")

    resultat = _initialiser(opsys_home, environ=EMBEDDINGS)

    assert resultat.etat == "pret"
    assert resultat.env.generees == () and resultat.env.reglees == ()
    assert _contenu_de_tout(opsys_home / "core") == avant


def test_les_reglages_gardes_dans_env_suffisent_a_la_relance(opsys_home, palier_standard):
    _initialiser(opsys_home, environ=EMBEDDINGS)

    resultat = _initialiser(opsys_home, environ={})  # l'opérateur ne les redonne pas

    assert resultat.etat == "pret"


def test_un_bloc_gateway_existant_n_est_jamais_modifie(opsys_home, palier_standard):
    _initialiser(opsys_home, environ=EMBEDDINGS, port_gateway=18790)
    racine = opsys_home / "core" / "openclaw.json"
    config = json.loads(racine.read_text(encoding="utf-8"))
    config["gateway"]["port"] = 19999
    racine.write_text(json.dumps(config), encoding="utf-8")

    resultat = _initialiser(opsys_home, environ=EMBEDDINGS, port_gateway=18790)

    assert json.loads(racine.read_text(encoding="utf-8"))["gateway"]["port"] == 19999
    assert resultat.port_gateway == 19999
    assert any("19999" in ligne and "18790" in ligne for ligne in resultat.avertissements)


def test_metier_json_garde_les_cles_de_l_operateur_et_suit_le_port(opsys_home, palier_standard):
    _initialiser(opsys_home, environ=EMBEDDINGS, port_moteur=8766)
    chemin = opsys_home / "core" / "opsys" / "metier.json"
    metier = json.loads(chemin.read_text(encoding="utf-8"))
    metier.update({"redemarrages_max": 3, "env": {"OPSYS_HOME": "/ancien", "MA_VARIABLE": "x"}})
    chemin.write_text(json.dumps(metier), encoding="utf-8")

    _initialiser(opsys_home, environ=EMBEDDINGS, port_moteur=8777)

    apres = json.loads(chemin.read_text(encoding="utf-8"))
    assert apres["redemarrages_max"] == 3
    assert apres["env"] == {"OPSYS_HOME": str(opsys_home), "MA_VARIABLE": "x"}
    assert apres["port"] == 8777 and apres["commande"][-1] == "8777"


def test_une_url_de_base_dans_l_environnement_est_refusee(opsys_home):
    with pytest.raises(instance.ErreurInstance, match="PostgreSQL"):
        _initialiser(opsys_home, environ={"OPSYS_BASE_URL": "postgresql+psycopg://u:p@h/db"})


def test_un_dossier_qui_n_est_pas_un_depot_est_refuse(opsys_home, tmp_path):
    with pytest.raises(instance.ErreurInstance, match="dépôt OPSYS"):
        _initialiser(opsys_home, source=tmp_path)


def test_les_dossiers_crees_sont_prives_et_un_dossier_ouvert_est_signale(tmp_path):
    neuf = tmp_path / "neuf"
    assert instance._preparer_dossiers(neuf) == []
    assert _mode(neuf) == 0o700 and _mode(neuf / "core") == 0o700

    ouvert = tmp_path / "ouvert"
    ouvert.mkdir(mode=0o755)
    ouvert.chmod(0o755)
    avertissements = instance._preparer_dossiers(ouvert)
    assert any(str(ouvert) in ligne and "chmod 700" in ligne for ligne in avertissements)
    assert _mode(ouvert) == 0o755  # un dossier existant n'est jamais modifié


# -- la CLI ------------------------------------------------------------------------------------------------------------
def test_la_cli_rend_3_quand_il_manque_une_decision_et_0_quand_tout_est_pret(opsys_home, palier_standard, monkeypatch,
                                                                         capsys):
    argv = ["instance", "initialiser", "--source", str(RACINE)]

    assert cli.main(argv) == instance.CODE_EN_ATTENTE
    attente = capsys.readouterr()
    assert json.loads(attente.out)["etat"] == "en_attente"
    assert "À FAIRE : service d'embeddings" in attente.err

    for nom, valeur in EMBEDDINGS.items():
        monkeypatch.setenv(nom, valeur)
    assert cli.main(argv) == 0
    pret = json.loads(capsys.readouterr().out)
    assert pret["etat"] == "pret"
    assert pret["env"]["secrets_generes"] == [] and "OPSYS_MCP_JETON" in pret["env"]["secrets_conserves"]
    assert set(pret["env"]["reglages_ecrits"]) == {"OPSYS_EMBEDDINGS_URL", "OPSYS_EMBEDDINGS_MODELE"}


def test_la_cli_refuse_un_depot_invalide_avec_un_message_et_le_code_1(opsys_home, tmp_path, capsys):
    assert cli.main(["instance", "initialiser", "--source", str(tmp_path)]) == 1
    assert "ERREUR : " in capsys.readouterr().err


# -- ce que le core attend : les constantes recopiées du fork restent les siennes -------------------------
def test_les_constantes_recopiees_du_core_sont_celles_du_fork():
    metier_ts = (RACINE / "core/src/gateway/opsys-metier-config.ts").read_text(encoding="utf-8")
    chemins_ts = (RACINE / "core/src/config/paths.ts").read_text(encoding="utf-8")

    assert f'OPSYS_MCP_TOKEN_ENV = "{instance.ENV_JETON_MCP}"' in metier_ts
    assert f"DEFAULT_PORT = {instance.PORT_MOTEUR_DEFAUT};" in metier_ts
    assert f"DEFAULT_GATEWAY_PORT = {instance.PORT_GATEWAY_DEFAUT};" in chemins_ts


def test_chaque_cle_de_metier_json_est_documentee_dans_le_fichier_de_config_du_core(opsys_home, palier_standard):
    _initialiser(opsys_home, environ=EMBEDDINGS)
    metier = json.loads((opsys_home / "core" / "opsys" / "metier.json").read_text(encoding="utf-8"))
    entete = (RACINE / "core/src/gateway/opsys-metier-config.ts").read_text(encoding="utf-8").split("import ")[0]
    documentees = set(re.findall(r'^//\s+"([a-z_]+)":', entete, flags=re.MULTILINE))

    assert set(metier) <= documentees, sorted(set(metier) - documentees)
