"""Préparation de l'instance locale par l'installateur (PLAN T0.11) : `opsys.instance`,
`opsys-metier instance initialiser`.

Ce que ces tests prouvent : le `.env` (0600, secrets jamais régénérés, aucune valeur dans une sortie), le verdict
fail-closed qui dit quoi fournir, la configuration du core et `metier.json` générés puis relus sans changement.
Ce qu'ils ne prouvent pas : que le core accepte cette configuration et lance le moteur (job `installateur` de la CI).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
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


@pytest.fixture(autouse=True)
def hote(tmp_path, monkeypatch) -> Path:
    """Le dossier personnel du poste fictif : l'état du core (`~/.openclaw-opsys`) n'est JAMAIS celui de l'hôte."""
    dossier = tmp_path / "hote"
    dossier.mkdir()
    monkeypatch.setenv("HOME", str(dossier))
    monkeypatch.delenv("USERPROFILE", raising=False)
    for nom in instance.VARIABLES_ECARTEES:
        monkeypatch.delenv(nom, raising=False)
    return dossier


@pytest.fixture
def etat_core(hote) -> Path:
    """Le dossier d'état du profil `opsys` du core, tel que le core le calcule (`resolveProfileStateDir`)."""
    return hote / ".openclaw-opsys"


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
    """`instance.initialiser` avec l'environnement d'un poste : HOME (l'hôte fictif) plus ce que le test fournit."""
    environ = {"HOME": os.environ["HOME"], **surcharge.pop("environ", {})}
    reglages = {"source": RACINE, "python": Path(sys.executable), "port_gateway": None, "port_moteur": None,
                "environ": environ}
    reglages.update(surcharge)
    return instance.initialiser(opsys_home, **reglages)


def test_sans_paliers_ni_embeddings_le_verdict_dit_quoi_fournir_et_rien_d_autre_n_est_ecrit(opsys_home, etat_core):
    resultat = _initialiser(opsys_home)

    assert resultat.etat == "en_attente"
    assert len(resultat.manque) == 2
    assert any("opsys-metier paliers definir" in ligne for ligne in resultat.manque)
    assert any("OPSYS_EMBEDDINGS_URL" in ligne and "OPSYS_EMBEDDINGS_MODELE" in ligne for ligne in resultat.manque)
    assert (etat_core / ".env").is_file()
    assert not (etat_core / "openclaw.json").exists()
    assert not (etat_core / "opsys").exists()
    assert not (opsys_home / "core").exists()  # l'état du core n'est pas sous OPSYS_HOME


def test_avec_paliers_et_embeddings_la_configuration_du_core_est_generee(opsys_home, etat_core, palier_standard):
    resultat = _initialiser(opsys_home, environ=EMBEDDINGS, port_gateway=18790, port_moteur=8766)

    assert resultat.etat == "pret" and resultat.manque == ()
    assert (resultat.port_gateway, resultat.port_moteur) == (18790, 8766)
    assert resultat.dossier_core == etat_core and resultat.en_json()["dossier_core"] == str(etat_core)
    assert not (opsys_home / "core").exists()
    core = etat_core
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
    # `opsys metier <commande>` (T0.7 lot 2) : le même interpréteur, la CLI du moteur ; le core y ajoute les arguments
    assert metier["commande_cli"] == [sys.executable, "-m", "opsys.cli"]
    assert metier["env"] == {"OPSYS_HOME": str(opsys_home)}
    env = instance.lire_env(core / ".env")
    assert env["OPSYS_EMBEDDINGS_MODELE"] == "bge-m3" and env["OPSYS_PASSERELLE_URL"] == "http://127.0.0.1:4000/v1"


def test_aucun_secret_dans_la_configuration_generee_ni_dans_la_sortie(opsys_home, etat_core, palier_standard,
                                                                     monkeypatch, capsys):
    for nom, valeur in EMBEDDINGS.items():
        monkeypatch.setenv(nom, valeur)

    assert cli.main(["instance", "initialiser", "--source", str(RACINE)]) == 0

    secrets_ecrits = _valeurs_secretes(etat_core / ".env")
    assert len(secrets_ecrits) >= 12  # jetons du moteur et du Gateway, dix clés de départements

    for nom, contenu in _contenu_de_tout(etat_core).items():
        if nom == ".env":
            continue
        for secret in secrets_ecrits:
            assert secret.encode() not in contenu, f"un secret est écrit dans core/{nom}"
    assert b"${OPSYS_MCP_JETON}" in (etat_core / "opsys" / "mcp.json").read_bytes()
    sortie = capsys.readouterr()
    for secret in secrets_ecrits:
        assert secret not in sortie.out + sortie.err


def test_initialiser_est_idempotent_et_ne_regenere_aucun_secret(opsys_home, etat_core, palier_standard):
    _initialiser(opsys_home, environ=EMBEDDINGS)
    avant = _contenu_de_tout(etat_core)

    resultat = _initialiser(opsys_home, environ=EMBEDDINGS)

    assert resultat.etat == "pret"
    assert resultat.env.generees == () and resultat.env.reglees == ()
    assert _contenu_de_tout(etat_core) == avant


def test_les_reglages_gardes_dans_env_suffisent_a_la_relance(opsys_home, palier_standard):
    _initialiser(opsys_home, environ=EMBEDDINGS)

    resultat = _initialiser(opsys_home, environ={})  # l'opérateur ne les redonne pas

    assert resultat.etat == "pret"


def test_un_bloc_gateway_existant_n_est_jamais_modifie(opsys_home, etat_core, palier_standard):
    _initialiser(opsys_home, environ=EMBEDDINGS, port_gateway=18790)
    racine = etat_core / "openclaw.json"
    config = json.loads(racine.read_text(encoding="utf-8"))
    config["gateway"]["port"] = 19999
    racine.write_text(json.dumps(config), encoding="utf-8")

    resultat = _initialiser(opsys_home, environ=EMBEDDINGS, port_gateway=18790)

    assert json.loads(racine.read_text(encoding="utf-8"))["gateway"]["port"] == 19999
    assert resultat.port_gateway == 19999
    assert any("19999" in ligne and "18790" in ligne for ligne in resultat.avertissements)


def test_metier_json_garde_les_cles_de_l_operateur_et_suit_le_port(opsys_home, etat_core, palier_standard):
    _initialiser(opsys_home, environ=EMBEDDINGS, port_moteur=8766)
    chemin = etat_core / "opsys" / "metier.json"
    metier = json.loads(chemin.read_text(encoding="utf-8"))
    metier.update({"redemarrages_max": 3, "env": {"OPSYS_HOME": "/ancien", "MA_VARIABLE": "x"}})
    chemin.write_text(json.dumps(metier), encoding="utf-8")

    _initialiser(opsys_home, environ=EMBEDDINGS, port_moteur=8777)

    apres = json.loads(chemin.read_text(encoding="utf-8"))
    assert apres["redemarrages_max"] == 3
    assert apres["env"] == {"OPSYS_HOME": str(opsys_home), "MA_VARIABLE": "x"}
    assert apres["port"] == 8777 and apres["commande"][-1] == "8777"
    assert apres["commande_cli"] == [sys.executable, "-m", "opsys.cli"]


def test_une_url_de_base_dans_l_environnement_est_refusee(opsys_home):
    with pytest.raises(instance.ErreurInstance, match="PostgreSQL"):
        _initialiser(opsys_home, environ={"OPSYS_BASE_URL": "postgresql+psycopg://u:p@h/db"})


def test_un_dossier_qui_n_est_pas_un_depot_est_refuse(opsys_home, tmp_path):
    with pytest.raises(instance.ErreurInstance, match="dépôt OPSYS"):
        _initialiser(opsys_home, source=tmp_path)


def test_les_dossiers_crees_sont_prives_et_un_dossier_ouvert_est_signale(tmp_path):
    neuf, neuf_core = tmp_path / "neuf", tmp_path / "hote" / ".openclaw-opsys"
    assert instance._preparer_dossiers(neuf, neuf_core) == []
    assert _mode(neuf) == 0o700 and _mode(neuf_core) == 0o700

    ouvert = tmp_path / "ouvert"
    ouvert.mkdir(mode=0o755)
    ouvert.chmod(0o755)
    avertissements = instance._preparer_dossiers(ouvert, neuf_core)
    assert any(str(ouvert) in ligne and "chmod 700" in ligne for ligne in avertissements)
    assert _mode(ouvert) == 0o755  # un dossier existant n'est jamais modifié


# -- le dossier d'état du core : celui du profil `opsys`, jamais sous OPSYS_HOME ---------------------------------
def test_le_dossier_du_core_est_celui_du_profil_opsys_sous_le_dossier_personnel():
    assert instance.dossier_core({"HOME": "/home/marie"}) == Path("/home/marie/.openclaw-opsys")
    assert instance.dossier_core({"USERPROFILE": "/users/marie"}) == Path("/users/marie/.openclaw-opsys")
    assert instance.dossier_core({"HOME": "/h/un", "USERPROFILE": "/h/deux"}) == Path("/h/un/.openclaw-opsys")
    assert instance.dossier_core({"HOME": "/home/marie/../paul/"}) == Path("/home/paul/.openclaw-opsys")
    # « undefined » et « null » se lisent comme absents, comme dans le core (`normalizeHomeDirValue`)
    assert instance.dossier_core({"HOME": "undefined", "USERPROFILE": "/h/deux"}) == Path("/h/deux/.openclaw-opsys")


def test_openclaw_home_est_ecarte_comme_le_font_les_commandes_installees():
    environ = {"HOME": "/home/marie", "OPENCLAW_HOME": "/ailleurs", "OPENCLAW_STATE_DIR": "/autre/etat",
               "OPENCLAW_PROFILE": "autre"}

    assert instance.dossier_core(environ) == Path("/home/marie/.openclaw-opsys")


def test_sans_dossier_personnel_le_dossier_du_core_est_refuse_jamais_devine():
    with pytest.raises(instance.ErreurInstance, match="HOME"):
        instance.dossier_core({"PATH": "/usr/bin"})
    with pytest.raises(instance.ErreurInstance, match="HOME"):
        instance.dossier_core({"HOME": "  ", "OPSYS_HOME": "/x"})


def test_l_environnement_du_processus_donne_le_dossier_personnel_du_poste(hote):
    assert instance.dossier_core() == hote / ".openclaw-opsys"
    assert instance.dossier_core(None) == instance.dossier_core({"HOME": str(hote)})


def test_l_etat_du_core_n_est_jamais_sous_opsys_home_et_le_dossier_est_prive(opsys_home, etat_core, palier_standard):
    resultat = _initialiser(opsys_home, environ=EMBEDDINGS)

    assert resultat.etat == "pret" and resultat.dossier_core == etat_core
    assert not (opsys_home / "core").exists()
    assert (etat_core / ".env").is_file() and (etat_core / "openclaw.json").is_file()
    assert (etat_core / "opsys" / "metier.json").is_file()
    assert _mode(etat_core) == 0o700 and _mode(etat_core / ".env") == 0o600
    assert not [p for p in opsys_home.iterdir() if p.is_dir()]  # OPSYS_HOME ne garde que des fichiers de données


def test_une_variable_du_core_qui_sortirait_l_etat_du_dossier_canonique_est_ecartee_et_signalee(
        opsys_home, etat_core, palier_standard):
    resultat = _initialiser(opsys_home, environ={**EMBEDDINGS, "OPENCLAW_STATE_DIR": "/ailleurs/etat",
                                                 "OPENCLAW_PROFILE": "autre"})

    assert resultat.dossier_core == etat_core and (etat_core / ".env").is_file()
    assert not Path("/ailleurs/etat").exists()
    assert any("OPENCLAW_STATE_DIR" in ligne and "OPENCLAW_PROFILE" in ligne and str(etat_core) in ligne
               for ligne in resultat.avertissements)


# -- l'ancienne disposition ($OPSYS_HOME/core) : signalée, jamais migrée en silence ----------------------------
ANCIEN_JETON = "jeton-de-l-ancienne-installation-fictif-0123456789"


def _poser_ancienne_disposition(opsys_home: Path) -> Path:
    ancien = opsys_home / "core"
    (ancien / "opsys").mkdir(parents=True)
    (ancien / ".env").write_text(f"OPSYS_MCP_JETON={ANCIEN_JETON}\n", encoding="utf-8")
    (ancien / "openclaw.json").write_text("{}\n", encoding="utf-8")
    return ancien


def test_l_ancienne_disposition_est_refusee_avec_la_marche_a_suivre_et_rien_n_est_modifie(
        opsys_home, etat_core, palier_standard):
    ancien = _poser_ancienne_disposition(opsys_home)
    avant = _contenu_de_tout(ancien)

    with pytest.raises(instance.ErreurInstance) as refus:
        _initialiser(opsys_home, environ=EMBEDDINGS)

    message = str(refus.value)
    assert "ancienne disposition" in message and str(ancien) in message and str(etat_core) in message
    assert "Rien n'est migré en silence" in message
    assert "mv" in message and f"{ancien}.ancien" in message and "openclaw gateway stop" in message
    assert ANCIEN_JETON not in message
    assert _contenu_de_tout(ancien) == avant  # rien n'a bougé
    assert not etat_core.exists() and not (opsys_home / "opsys.db").exists()  # rien n'a été écrit non plus


def test_marche_a_suivre_1_deplacer_l_ancien_dossier_garde_les_secrets(opsys_home, etat_core, palier_standard):
    ancien = _poser_ancienne_disposition(opsys_home)
    with pytest.raises(instance.ErreurInstance):
        _initialiser(opsys_home, environ=EMBEDDINGS)

    shutil.move(str(ancien), str(etat_core))
    resultat = _initialiser(opsys_home, environ=EMBEDDINGS)

    assert resultat.etat == "pret"
    assert "OPSYS_MCP_JETON" in resultat.env.conservees and "OPSYS_MCP_JETON" not in resultat.env.generees
    assert instance.lire_env(etat_core / ".env")["OPSYS_MCP_JETON"] == ANCIEN_JETON
    assert not (opsys_home / "core").exists()


def test_marche_a_suivre_2_mettre_l_ancien_dossier_de_cote_repart_a_neuf(opsys_home, etat_core, palier_standard):
    ancien = _poser_ancienne_disposition(opsys_home)
    avant = _contenu_de_tout(ancien)
    with pytest.raises(instance.ErreurInstance):
        _initialiser(opsys_home, environ=EMBEDDINGS)

    ancien.rename(opsys_home / "core.ancien")
    resultat = _initialiser(opsys_home, environ=EMBEDDINGS)

    assert resultat.etat == "pret" and "OPSYS_MCP_JETON" in resultat.env.generees
    assert instance.lire_env(etat_core / ".env")["OPSYS_MCP_JETON"] != ANCIEN_JETON
    assert _contenu_de_tout(opsys_home / "core.ancien") == avant  # l'ancien état est intact, à détruire par un humain


def test_un_dossier_core_vide_ou_qui_est_l_etat_du_core_n_est_pas_l_ancienne_disposition(
        opsys_home, etat_core, palier_standard):
    (opsys_home / "core").mkdir(parents=True)  # laissé vide par une installation interrompue
    assert instance.ancienne_disposition(opsys_home, etat_core) is None
    assert _initialiser(opsys_home, environ=EMBEDDINGS).etat == "pret"

    (opsys_home / "core").rmdir()
    (opsys_home / "core").symlink_to(etat_core, target_is_directory=True)  # un lien vers l'état : déjà migré à la main
    assert instance.ancienne_disposition(opsys_home, etat_core) is None
    assert _initialiser(opsys_home, environ=EMBEDDINGS).etat == "pret"


def test_la_cli_refuse_l_ancienne_disposition_avec_le_code_1_et_la_marche_a_suivre(opsys_home, palier_standard,
                                                                                capsys, monkeypatch):
    for nom, valeur in EMBEDDINGS.items():
        monkeypatch.setenv(nom, valeur)
    _poser_ancienne_disposition(opsys_home)

    assert cli.main(["instance", "initialiser", "--source", str(RACINE)]) == 1

    erreur = capsys.readouterr().err
    assert erreur.startswith("ERREUR : ancienne disposition détectée") and "mv" in erreur


def test_la_cli_dossier_ecrit_le_dossier_d_etat_du_core_et_rien_d_autre(etat_core, capsys):
    assert cli.main(["instance", "dossier"]) == 0

    assert capsys.readouterr().out == f"{etat_core}\n"


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

    metier_cli_ts = (RACINE / "core/src/cli/opsys-metier-cli.ts").read_text(encoding="utf-8")

    assert f'OPSYS_MCP_TOKEN_ENV = "{instance.ENV_JETON_MCP}"' in metier_ts
    assert f"DEFAULT_PORT = {instance.PORT_MOTEUR_DEFAUT};" in metier_ts
    assert f"DEFAULT_GATEWAY_PORT = {instance.PORT_GATEWAY_DEFAUT};" in chemins_ts
    assert f'OPSYS_METIER_CLI_COMMAND_KEY = "{instance.CLE_COMMANDE_CLI}"' in metier_cli_ts


def test_chaque_cle_de_metier_json_est_documentee_dans_le_fichier_de_config_du_core(opsys_home, etat_core,
                                                                                    palier_standard):
    _initialiser(opsys_home, environ=EMBEDDINGS)
    metier = json.loads((etat_core / "opsys" / "metier.json").read_text(encoding="utf-8"))
    entete = (RACINE / "core/src/gateway/opsys-metier-config.ts").read_text(encoding="utf-8").split("import ")[0]
    documentees = set(re.findall(r'^//\s+"([a-z_]+)":', entete, flags=re.MULTILINE))

    assert set(metier) <= documentees, sorted(set(metier) - documentees)


def test_le_profil_et_les_noms_de_service_recopies_du_fork_sont_les_siens():
    """Le profil `opsys` n'est acceptable que si le fork le traite comme on le suppose : lu dans son code."""
    profil = (RACINE / "core/src/cli/profile-utils.ts").read_text(encoding="utf-8")
    chemins = (RACINE / "core/src/config/paths.ts").read_text(encoding="utf-8")
    constantes = (RACINE / "core/src/daemon/constants.ts").read_text(encoding="utf-8")

    # dossier d'état : `~/.openclaw-<profil>`
    assert 'const suffix = normalizeLowercaseStringOrEmpty(trimmed) === "default" ? "" : `-${trimmed}`;' in profil
    assert "`.openclaw${suffix}`" in profil
    assert instance.PREFIXE_DOSSIER_PROFIL == ".openclaw-"
    nom_valide = re.search(r"PROFILE_NAME_RE = /(.+?)/i;", profil)
    assert nom_valide and re.fullmatch(nom_valide.group(1), instance.PROFIL_CORE, flags=re.IGNORECASE)
    # ni un profil réservé (étiquettes launchd du core et du poste de travail d'origine), ni « default »
    assert 'profile === "gateway" || profile === "node"' in chemins
    assert instance.PROFIL_CORE not in ("gateway", "node", "default")
    # le service porte un nom distinct de celui du core d'origine
    assert "`openclaw-gateway${suffix}`" in constantes and '"openclaw-gateway"' in constantes
    assert "`ai.openclaw.${normalized}`" in constantes and '"ai.openclaw.gateway"' in constantes
    assert "`OpenClaw Gateway (${normalized})`" in constantes and '"OpenClaw Gateway"' in constantes


def test_le_profil_ne_se_projette_que_par_l_option_racine_et_pas_par_la_seule_variable():
    """Pourquoi les commandes du core passent `--profile opsys` et non `OPENCLAW_PROFILE=opsys` : lu dans le fork.

    `resolveStateDir` (dossier d'état) ignore OPENCLAW_PROFILE ; seul `applyCliProfileEnv`, appelé pour l'option
    racine `--profile`, pose OPENCLAW_STATE_DIR et OPENCLAW_CONFIG_PATH au dossier canonique du profil. Avec la seule
    variable, l'état resterait `~/.openclaw` et `isDefaultInstallIdentity` refuserait le service.
    """
    etat = (RACINE / "core/src/config/state-dir.ts").read_text(encoding="utf-8")
    profil = (RACINE / "core/src/cli/profile.ts").read_text(encoding="utf-8")
    entree = (RACINE / "core/src/entry.ts").read_text(encoding="utf-8")
    chemins = (RACINE / "core/src/config/paths.ts").read_text(encoding="utf-8")

    assert "OPENCLAW_PROFILE" not in etat
    assert "env.OPENCLAW_STATE_DIR = stateDir;" in profil
    assert "env.OPENCLAW_CONFIG_PATH = resolveProfileConfigPath(profile, stateDir);" in profil
    assert "applyCliProfileEnv({ profile: earlyProfile.profile });" in entree
    assert 'resolveProfileStateDir(env.OPENCLAW_PROFILE ?? "default", env, homedir)' in chemins
    assert "resolveStateDir(env, envHomedir(env))" in chemins


def test_le_dossier_personnel_se_lit_comme_dans_le_core():
    """`dossier_core` lit HOME puis USERPROFILE, et écarte OPENCLAW_HOME : l'ordre du fork, relu ici."""
    dossier_personnel = (RACINE / "core/packages/normalization-core/src/home-dir.ts").read_text(encoding="utf-8")

    brut = dossier_personnel.split("function resolveRawOsHomeDir")[1].split("}")[0]
    assert brut.index("env.HOME") < brut.index("env.USERPROFILE")
    assert 'trimmed !== "undefined" && trimmed !== "null"' in dossier_personnel
    assert "const explicitHome = normalizeHomeDirValue(env.OPENCLAW_HOME);" in dossier_personnel
    chemins = (RACINE / "core/src/config/paths.ts").read_text(encoding="utf-8")
    assert "if (normalizeHomeDirValue(env.OPENCLAW_HOME)) {\n    return false;" in chemins  # sinon aucun service


# -- restreindre_acces : 0600 sous POSIX, icacls sous Windows --------------------------------------------------------
def test_restreindre_acces_pose_0600_hors_de_windows(tmp_path):
    fichier = tmp_path / "secret"
    fichier.write_text("x", encoding="utf-8")
    fichier.chmod(0o644)

    instance.restreindre_acces(fichier)

    assert _mode(fichier) == 0o600


def test_restreindre_acces_sous_windows_coupe_l_heritage_et_ne_garde_que_l_utilisateur(tmp_path, monkeypatch):
    appels: list[list[str]] = []

    def faux(commande, **options):
        appels.append(list(commande))
        assert options["check"] is False and options["capture_output"] is True
        return subprocess.CompletedProcess(commande, 0, "", "")

    monkeypatch.setattr(instance, "_sous_windows", lambda: True)
    monkeypatch.setattr(instance.subprocess, "run", faux)
    monkeypatch.setenv("USERNAME", "sylvie-fictif")
    fichier = tmp_path / ".env"
    fichier.write_text("x", encoding="utf-8")
    fichier.chmod(0o644)

    instance.restreindre_acces(fichier)

    assert appels == [["icacls", str(fichier), "/inheritance:r", "/grant:r", "sylvie-fictif:(F)"]]
    assert _mode(fichier) == 0o644  # os.chmod ne sert à rien sous Windows : seul icacls agit


def test_restreindre_acces_sous_windows_refuse_sans_utilisateur_et_sur_refus_d_icacls(tmp_path, monkeypatch):
    fichier = tmp_path / ".env"
    fichier.write_text("x", encoding="utf-8")
    monkeypatch.setattr(instance, "_sous_windows", lambda: True)
    monkeypatch.delenv("USERNAME", raising=False)

    with pytest.raises(instance.ErreurInstance, match="USERNAME est absent"):
        instance.restreindre_acces(fichier)

    monkeypatch.setenv("USERNAME", "sylvie-fictif")
    monkeypatch.setattr(instance.subprocess, "run",
                        lambda commande, **_: subprocess.CompletedProcess(commande, 5, "", "Access is denied."))
    with pytest.raises(instance.ErreurInstance, match="icacls a refusé de restreindre l'accès.*Access is denied"):
        instance.restreindre_acces(fichier)


def test_restreindre_dossier_pose_0700_hors_de_windows(tmp_path):
    dossier = tmp_path / "etat"
    dossier.mkdir()
    dossier.chmod(0o755)

    instance.restreindre_dossier(dossier)

    assert _mode(dossier) == 0o700


def test_sous_windows_les_dossiers_crees_ont_une_acl_heritee_reduite_a_l_utilisateur(tmp_path, hote, monkeypatch):
    """Le service écrit ses propres fichiers dans l'état du core (`gateway.cmd` porte les valeurs de `.env`) : leur
    protection est celle du dossier, que les fichiers hériteront (`(OI)(CI)`)."""
    appels: list[list[str]] = []

    def faux(commande, **_options):
        appels.append(list(commande))
        return subprocess.CompletedProcess(commande, 0, "", "")

    monkeypatch.setattr(instance, "_sous_windows", lambda: True)
    monkeypatch.setattr(instance.subprocess, "run", faux)
    monkeypatch.setenv("USERNAME", "sylvie-fictif")
    home, etat = tmp_path / "instance", hote / ".openclaw-opsys"
    existant = tmp_path / "existant"
    existant.mkdir()

    instance._preparer_dossiers(home, etat)
    instance._preparer_dossiers(existant, existant)  # un dossier existant n'est jamais modifié

    assert appels == [
        ["icacls", str(home), "/inheritance:r", "/grant:r", "sylvie-fictif:(OI)(CI)(F)"],
        ["icacls", str(etat), "/inheritance:r", "/grant:r", "sylvie-fictif:(OI)(CI)(F)"],
    ]
    assert home.is_dir() and etat.is_dir()
