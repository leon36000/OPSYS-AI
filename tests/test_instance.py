"""Préparation de l'instance locale par l'installateur (PLAN T0.11) : `opsys.instance`,
`opsys-metier instance initialiser`.

Ce que ces tests prouvent : le `.env` (0600, secrets jamais régénérés, aucune valeur dans une sortie), le verdict
fail-closed qui dit quoi fournir, la configuration du core et `metier.json` générés puis relus sans changement, le
dossier d'instance `~/.opsys/core` (T0.7 lot 3) et le refus, avec la marche à suivre, d'un état resté à l'ancien
emplacement `~/.openclaw-opsys` (son déplacement est celui de Doctor, dans le core).
Ce qu'ils ne prouvent pas : que le core accepte cette configuration et lance le moteur, ni que Doctor déplace bien
l'état (job `installateur` de la CI, avec le vrai core).
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

from opsys import cli, instance, openclaw

FICTIF = True  # aucune valeur ci-dessous n'est réelle (AGENTS.md)

RACINE = Path(__file__).resolve().parents[1]
EMBEDDINGS = {"OPSYS_EMBEDDINGS_URL": "http://127.0.0.1:11434/v1", "OPSYS_EMBEDDINGS_MODELE": "bge-m3"}
SECRETS_ATTENDUS = [
    "OPSYS_MCP_JETON", "OPSYS_CONTEXT_MCP_JETON", "OPENCLAW_GATEWAY_TOKEN", "OPSYS_CLE_M1",
]


def _mode(chemin: Path) -> int:
    return stat.S_IMODE(chemin.stat().st_mode)


def _chemin_absolu_attendu(chemin: str) -> Path:
    """Résout les entrées HOME POSIX comme le fait le code sous l'OS courant."""
    return Path(os.path.abspath(chemin))


def _espionner_chmod_posix(monkeypatch):
    appels = []
    chmod_reel = os.chmod

    def espion(chemin, mode):
        appels.append((Path(chemin), mode))
        chmod_reel(chemin, mode)

    monkeypatch.setattr(instance, "_sous_windows", lambda: False)
    monkeypatch.setattr(instance.os, "chmod", espion)
    return appels


def _valeurs_secretes(chemin: Path) -> list[str]:
    env = instance.lire_env(chemin)
    return [valeur for nom, valeur in env.items() if re.search(r"JETON|TOKEN|CLE", nom) and len(valeur) >= 12]


def _contenu_de_tout(dossier: Path) -> dict[str, bytes]:
    return {str(p.relative_to(dossier)): p.read_bytes() for p in sorted(dossier.rglob("*")) if p.is_file()}


@pytest.fixture(autouse=True)
def hote(tmp_path, monkeypatch) -> Path:
    """Le dossier personnel du poste fictif : l'état du core (`~/.opsys/core`) n'est JAMAIS celui de l'hôte."""
    dossier = tmp_path / "hote"
    dossier.mkdir()
    monkeypatch.setenv("HOME", str(dossier))
    monkeypatch.delenv("USERPROFILE", raising=False)
    for nom in instance.VARIABLES_ECARTEES:
        monkeypatch.delenv(nom, raising=False)
    return dossier


@pytest.fixture
def etat_core(hote) -> Path:
    """Le dossier d'état du profil `opsys` du core, tel que le core le calcule (`resolveOpsysCoreStateDir`)."""
    return hote / ".opsys" / "core"


@pytest.fixture
def palier_standard():
    from opsys import modeles

    modeles.enregistrer_paliers({"standard": {"provider": "anthropic", "model": "claude-sonnet-5"}})


# -- assurer_env ------------------------------------------------------------------------------------------------------
def test_env_cree_en_0600_avec_les_secrets_manquants(tmp_path, verifier_acces_prive):
    chemin = tmp_path / "core" / ".env"
    ancien_umask = os.umask(0)  # le pire cas : aucun droit retiré par le système
    try:
        rapport = instance.assurer_env(chemin, SECRETS_ATTENDUS, {})
    finally:
        os.umask(ancien_umask)

    verifier_acces_prive(chemin, mode=0o600)
    assert rapport.generees == tuple(SECRETS_ATTENDUS)
    env = instance.lire_env(chemin)
    assert len(env["OPSYS_MCP_JETON"]) >= 24 and not re.search(r"\s", env["OPSYS_MCP_JETON"])  # exigé par le moteur
    assert env["OPSYS_CLE_M1"].startswith("sk-opsys-m1-")
    assert len({env[nom] for nom in SECRETS_ATTENDUS}) == 4  # quatre secrets indépendants


def test_une_instance_existante_garde_son_bearer_public_et_genere_le_bearer_contexte(tmp_path):
    chemin = tmp_path / "core" / ".env"
    chemin.parent.mkdir()
    public = "bearer-public-existant-fictif-123456"
    chemin.write_text(f"OPSYS_MCP_JETON={public}\n", encoding="utf-8")

    rapport = instance.assurer_env(chemin, SECRETS_ATTENDUS, {})
    env = instance.lire_env(chemin)

    assert env["OPSYS_MCP_JETON"] == public
    assert len(env["OPSYS_CONTEXT_MCP_JETON"]) >= 24
    assert env["OPSYS_CONTEXT_MCP_JETON"] != public
    assert "OPSYS_CONTEXT_MCP_JETON" in rapport.generees
    assert public not in repr(rapport) and env["OPSYS_CONTEXT_MCP_JETON"] not in repr(rapport)


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


def test_un_fichier_pose_a_la_main_avec_des_droits_larges_est_resserre(tmp_path, verifier_acces_prive):
    chemin = tmp_path / ".env"
    chemin.write_text("OPSYS_MCP_JETON=jeton-existant-1234567890\n", encoding="utf-8")
    chemin.chmod(0o644)

    instance.assurer_env(chemin, ["OPSYS_MCP_JETON"], {})

    verifier_acces_prive(chemin, mode=0o600)
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
    assert not (etat_core / "opsys.json").exists() and not (etat_core / "openclaw.json").exists()
    assert not (etat_core / "opsys").exists()
    assert not (opsys_home / "core").exists()  # l'état du core n'est pas sous cet OPSYS_HOME-ci


def test_avec_paliers_et_embeddings_la_configuration_du_core_est_generee(opsys_home, etat_core, palier_standard):
    resultat = _initialiser(opsys_home, environ=EMBEDDINGS, port_gateway=18790, port_moteur=8766)

    assert resultat.etat == "pret" and resultat.manque == ()
    assert (resultat.port_gateway, resultat.port_moteur) == (18790, 8766)
    assert resultat.dossier_core == etat_core and resultat.en_json()["dossier_core"] == str(etat_core)
    assert not (opsys_home / "core").exists()
    core = etat_core
    assert resultat.fichiers["openclaw"] == str(core / "opsys.json")  # le fichier de configuration du core
    assert (core / "opsys.json").is_file() and not (core / "openclaw.json").exists()
    racine = json.loads((core / "opsys.json").read_text(encoding="utf-8"))
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
    assert env["OPSYS_EMBEDDINGS_MODELE"] == "bge-m3"
    assert "OPSYS_PASSERELLE_URL" not in env  # aucun LiteLLM implicite en mode natif
    assert "OPSYS_MODE_FOURNISSEUR" not in env
    agents = json.loads((core / "opsys" / "agents.json").read_text(encoding="utf-8"))
    models = json.loads((core / "opsys" / "models.json").read_text(encoding="utf-8"))
    assert agents["entries"]["m01-front-office"]["model"] == "anthropic/claude-sonnet-5"
    assert models["providers"]["anthropic"]["apiKey"] == "${ANTHROPIC_API_KEY}"


def test_une_url_litellm_ancienne_seule_ne_bascule_pas_le_mode_natif(opsys_home, etat_core, palier_standard):
    chemin_env = etat_core / ".env"
    chemin_env.parent.mkdir(parents=True, exist_ok=True)
    chemin_env.write_text("OPSYS_PASSERELLE_URL=http://127.0.0.1:4000/v1\n", encoding="utf-8")

    resultat = _initialiser(opsys_home, environ=EMBEDDINGS)

    assert resultat.etat == "pret"
    agents = json.loads((etat_core / "opsys" / "agents.json").read_text(encoding="utf-8"))
    models = json.loads((etat_core / "opsys" / "models.json").read_text(encoding="utf-8"))
    assert agents["entries"]["m01-front-office"]["model"] == "anthropic/claude-sonnet-5"
    assert all(not nom.startswith("opsys-m") for nom in models["providers"])
    assert instance.lire_env(chemin_env)["OPSYS_PASSERELLE_URL"] == "http://127.0.0.1:4000/v1"


def test_mode_litellm_est_opte_et_persiste_seulement_si_explicite(opsys_home, etat_core, palier_standard):
    resultat = _initialiser(
        opsys_home,
        environ={**EMBEDDINGS, "OPSYS_MODE_FOURNISSEUR": "litellm",
                 "OPSYS_PASSERELLE_URL": "http://127.0.0.1:4500/v1"},
    )

    assert resultat.etat == "pret"
    agents = json.loads((etat_core / "opsys" / "agents.json").read_text(encoding="utf-8"))
    models = json.loads((etat_core / "opsys" / "models.json").read_text(encoding="utf-8"))
    assert agents["entries"]["m01-front-office"]["model"] == "opsys-m1/opsys-standard"
    assert models["providers"]["opsys-m1"]["baseUrl"] == "http://127.0.0.1:4500/v1"
    assert instance.lire_env(etat_core / ".env")["OPSYS_MODE_FOURNISSEUR"] == "litellm"


def test_la_cli_instance_recoit_le_mode_litellm_seulement_avec_les_deux_options(
    opsys_home, etat_core, palier_standard, monkeypatch, capsys
):
    for nom, valeur in EMBEDDINGS.items():
        monkeypatch.setenv(nom, valeur)
    monkeypatch.delenv("OPSYS_MODE_FOURNISSEUR", raising=False)
    monkeypatch.delenv("OPSYS_PASSERELLE_URL", raising=False)

    code = cli.main([
        "instance", "initialiser", "--source", str(RACINE), "--mode-fournisseur", "litellm",
        "--url-passerelle", "http://127.0.0.1:4500/v1",
    ])

    assert code == 0, capsys.readouterr()
    agents = json.loads((etat_core / "opsys" / "agents.json").read_text(encoding="utf-8"))
    assert agents["entries"]["m01-front-office"]["model"] == "opsys-m1/opsys-standard"


def test_mode_litellm_sans_url_echoue_avant_migration_et_ecriture(opsys_home, etat_core, palier_standard):
    with pytest.raises(instance.ErreurInstance, match="exige une URL explicite"):
        _initialiser(opsys_home, mode_fournisseur="litellm", environ=EMBEDDINGS)

    assert not (opsys_home / "opsys.db").exists()
    assert not (etat_core / ".env").exists()


def test_une_url_seule_explicitement_fournie_est_refusee(opsys_home, palier_standard):
    with pytest.raises(instance.ErreurInstance, match="réservée à --mode-fournisseur litellm"):
        _initialiser(
            opsys_home,
            url_passerelle="http://127.0.0.1:4000/v1",
            environ=EMBEDDINGS,
        )


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
    racine = etat_core / "opsys.json"
    config = json.loads(racine.read_text(encoding="utf-8"))
    config["gateway"]["port"] = 19999
    racine.write_text(json.dumps(config), encoding="utf-8")

    resultat = _initialiser(opsys_home, environ=EMBEDDINGS, port_gateway=18790)

    assert json.loads(racine.read_text(encoding="utf-8"))["gateway"]["port"] == 19999
    assert resultat.port_gateway == 19999
    assert any("19999" in ligne and "18790" in ligne and "opsys.json" in ligne for ligne in resultat.avertissements)


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


def test_les_dossiers_crees_sont_prives_et_un_dossier_ouvert_est_signale(
        tmp_path, verifier_acces_prive):
    neuf, neuf_core = tmp_path / "neuf", tmp_path / "hote" / ".opsys" / "core"
    assert instance._preparer_dossiers([neuf, neuf_core.parent, neuf_core]) == []
    verifier_acces_prive(neuf, mode=0o700)
    verifier_acces_prive(neuf_core, mode=0o700)
    verifier_acces_prive(neuf_core.parent, mode=0o700)  # le dossier d'instance est privé lui aussi

    ouvert = tmp_path / "ouvert"
    ouvert.mkdir(mode=0o755)
    ouvert.chmod(0o755)
    contenu_ouvert_avant = _contenu_de_tout(ouvert)
    mode_ouvert_avant = _mode(ouvert)
    avertissements = instance._preparer_dossiers([ouvert, neuf_core])
    if os.name == "nt":
        # Sous Windows, les ACL des dossiers préexistants ne sont ni inspectées ni modifiées.
        assert avertissements == []
    else:
        assert any(str(ouvert) in ligne and "chmod 700" in ligne for ligne in avertissements)
    assert _contenu_de_tout(ouvert) == contenu_ouvert_avant
    assert _mode(ouvert) == mode_ouvert_avant  # un dossier existant n'est jamais modifié


# -- le dossier d'état du core : `core/` dans le dossier d'instance du compte -------------------------------------
def test_le_dossier_du_core_est_celui_du_profil_opsys_sous_le_dossier_personnel():
    assert instance.dossier_core({"HOME": "/home/marie"}) == _chemin_absolu_attendu("/home/marie/.opsys/core")
    assert instance.dossier_core({"USERPROFILE": "/users/marie"}) == _chemin_absolu_attendu("/users/marie/.opsys/core")
    assert instance.dossier_core({"HOME": "/h/un", "USERPROFILE": "/h/deux"}) == (
        _chemin_absolu_attendu("/h/un/.opsys/core"))
    assert instance.dossier_core({"HOME": "/home/marie/../paul/"}) == _chemin_absolu_attendu("/home/paul/.opsys/core")
    # « undefined » et « null » se lisent comme absents, comme dans le core (`normalizeHomeDirValue`)
    assert instance.dossier_core({"HOME": "undefined", "USERPROFILE": "/h/deux"}) == (
        _chemin_absolu_attendu("/h/deux/.opsys/core"))


def test_l_ancien_dossier_du_profil_est_a_cote_du_dossier_personnel():
    assert instance.ancien_dossier_profil({"HOME": "/home/marie"}) == (
        _chemin_absolu_attendu("/home/marie/.openclaw-opsys"))
    assert instance.ancien_dossier_profil({"USERPROFILE": "/users/marie"}) == (
        _chemin_absolu_attendu("/users/marie/.openclaw-opsys"))
    with pytest.raises(instance.ErreurInstance, match="HOME"):
        instance.ancien_dossier_profil({"PATH": "/usr/bin"})


def test_openclaw_home_est_ecarte_comme_le_font_les_commandes_installees():
    environ = {"HOME": "/home/marie", "OPENCLAW_HOME": "/ailleurs", "OPENCLAW_STATE_DIR": "/autre/etat",
               "OPENCLAW_PROFILE": "autre"}

    assert instance.dossier_core(environ) == _chemin_absolu_attendu("/home/marie/.opsys/core")


def test_sans_dossier_personnel_le_dossier_du_core_est_refuse_jamais_devine():
    with pytest.raises(instance.ErreurInstance, match="HOME"):
        instance.dossier_core({"PATH": "/usr/bin"})
    with pytest.raises(instance.ErreurInstance, match="HOME"):
        instance.dossier_core({"HOME": "  ", "OPSYS_HOME": "/x"})


def test_l_environnement_du_processus_donne_le_dossier_personnel_du_poste(hote):
    assert instance.dossier_core() == hote / ".opsys" / "core"
    assert instance.dossier_core(None) == instance.dossier_core({"HOME": str(hote)})


def test_l_etat_du_core_suit_le_compte_pas_opsys_home_et_les_dossiers_sont_prives(
        opsys_home, hote, etat_core, palier_standard, verifier_acces_prive):
    resultat = _initialiser(opsys_home, environ=EMBEDDINGS)

    assert resultat.etat == "pret" and resultat.dossier_core == etat_core
    assert not (opsys_home / "core").exists()  # OPSYS_HOME est ailleurs : ses données restent chez lui
    assert (etat_core / ".env").is_file() and (etat_core / "opsys.json").is_file()
    assert (etat_core / "opsys" / "metier.json").is_file()
    verifier_acces_prive(etat_core, mode=0o700)
    verifier_acces_prive(etat_core / ".env", mode=0o600)
    verifier_acces_prive(hote / ".opsys", mode=0o700)  # créé avec l'état du core
    assert not [p for p in opsys_home.iterdir() if p.is_dir()]  # OPSYS_HOME ne garde que des fichiers de données
    assert any("OPSYS_HOME" in ligne and str(opsys_home) in ligne and str(etat_core) in ligne
               for ligne in resultat.avertissements)  # le core ne lit pas OPSYS_HOME : l'écart est dit


def _instance_par_defaut(hote: Path, monkeypatch) -> Path:
    """L'`OPSYS_HOME` par défaut, `~/.opsys` du poste fictif : le dossier d'instance du compte, paliers déjà choisis.
    (Le garde commun de `conftest.py` donne sinon à chaque test un `OPSYS_HOME` temporaire.)"""
    from opsys import modeles

    home = hote / ".opsys"
    monkeypatch.setenv("OPSYS_HOME", str(home))
    modeles.enregistrer_paliers({"standard": {"provider": "anthropic", "model": "claude-sonnet-5"}})
    # Le fixture établit l'ACL privée sur le dossier préexistant; initialiser() le laisse intact.
    instance.restreindre_dossier(home)
    return home


def test_avec_l_opsys_home_par_defaut_les_donnees_et_l_etat_du_core_sont_dans_le_meme_dossier_d_instance(
        hote, etat_core, monkeypatch, verifier_acces_prive):
    home = _instance_par_defaut(hote, monkeypatch)

    resultat = _initialiser(home, environ=EMBEDDINGS)

    assert resultat.etat == "pret" and resultat.dossier_core == home / "core" == etat_core
    assert (home / "opsys.db").is_file() and (home / "paliers.yaml").is_file()
    verifier_acces_prive(home, mode=0o700)
    verifier_acces_prive(etat_core, mode=0o700)
    assert not any("OPSYS_HOME" in ligne for ligne in resultat.avertissements)  # rien à signaler : un seul dossier


def test_un_etat_du_core_fourni_ne_cherche_rien_hors_de_lui(opsys_home, hote, tmp_path, palier_standard):
    _poser_etat_d_avant(hote)  # un ancien état à côté : sans importance pour un dossier d'état choisi par l'appelant
    autre = tmp_path / "autre-etat"

    resultat = _initialiser(opsys_home, environ=EMBEDDINGS, etat_core=autre)

    assert resultat.etat == "pret" and resultat.dossier_core == autre and (autre / "opsys.json").is_file()
    assert not (hote / ".opsys").exists()


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
    assert "mv" in message and f"{ancien}.ancien" in message and "opsys gateway stop" in message
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


def test_avec_l_opsys_home_par_defaut_l_ancien_sous_dossier_core_est_deja_le_dossier_canonique(
        hote, etat_core, monkeypatch):
    """`~/.opsys/core` : c'est là que la première version de l'installateur posait l'état, et c'est maintenant le
    dossier d'état du core. Un état qui s'y trouve est donc à sa place ; il garde ses secrets et son `openclaw.json`."""
    home = _instance_par_defaut(hote, monkeypatch)
    _poser_ancienne_disposition(home)
    assert instance.ancienne_disposition(home, etat_core) is None

    resultat = _initialiser(home, environ=EMBEDDINGS)

    assert resultat.etat == "pret"
    assert instance.lire_env(etat_core / ".env")["OPSYS_MCP_JETON"] == ANCIEN_JETON
    assert resultat.fichiers["openclaw"] == str(etat_core / "openclaw.json")  # lu en place, jamais renommé


def test_la_cli_dossier_ecrit_le_dossier_d_etat_du_core_et_rien_d_autre(etat_core, capsys):
    assert cli.main(["instance", "dossier"]) == 0

    assert capsys.readouterr().out == f"{etat_core}\n"


# -- le fichier de configuration du core : opsys.json, et l'openclaw.json d'avant reste lu ------------------
def test_le_fichier_de_configuration_est_opsys_json_ou_l_openclaw_json_qui_existe(etat_core):
    etat_core.mkdir(parents=True)
    assert instance.fichier_config(etat_core) == etat_core / "opsys.json"  # instance neuve

    (etat_core / "openclaw.json").write_text("{}\n", encoding="utf-8")
    assert instance.fichier_config(etat_core) == etat_core / "openclaw.json"  # lu en place, jamais renommé

    (etat_core / "opsys.json").write_text("{}\n", encoding="utf-8")
    assert instance.fichier_config(etat_core) == etat_core / "opsys.json"  # le canonique l'emporte, comme dans le core


def test_la_cli_fichier_config_ecrit_le_fichier_du_core_et_rien_d_autre(etat_core, capsys):
    assert cli.main(["instance", "fichier-config"]) == 0
    assert capsys.readouterr().out == f"{etat_core / 'opsys.json'}\n"

    etat_core.mkdir(parents=True)
    (etat_core / "openclaw.json").write_text("{}\n", encoding="utf-8")
    assert cli.main(["instance", "fichier-config"]) == 0
    assert capsys.readouterr().out == f"{etat_core / 'openclaw.json'}\n"


def test_le_fichier_racine_garde_le_nom_openclaw_json_hors_de_l_instance_et_prend_opsys_json_dans_l_instance(
        tmp_path):
    hors_instance = tmp_path / "docker"
    hors_instance.mkdir()
    assert openclaw.fichier_racine(hors_instance) == hors_instance / "openclaw.json"  # par défaut : rien ne change
    assert openclaw.racine_si_absente(hors_instance) == hors_instance / "openclaw.json"
    assert openclaw.racine_si_absente(hors_instance) is None

    neuve = tmp_path / "instance"
    neuve.mkdir()
    assert openclaw.racine_si_absente(neuve, nom_creation=instance.NOM_CONFIG) == neuve / "opsys.json"
    assert openclaw.racine_si_absente(neuve, nom_creation=instance.NOM_CONFIG) is None  # jamais deux fichiers racine
    assert not (neuve / "openclaw.json").exists()


def test_les_includes_se_lisent_dans_le_fichier_racine_que_le_core_lit(tmp_path):
    dossier = tmp_path / "instance"
    dossier.mkdir()
    (dossier / "openclaw.json").write_text(json.dumps(openclaw.FICHIER_RACINE_MODELE), encoding="utf-8")
    assert openclaw.includes_manquants(dossier) == []

    (dossier / "opsys.json").write_text("{}\n", encoding="utf-8")  # opsys.json l'emporte, comme dans le core
    assert set(openclaw.includes_manquants(dossier)) == set(openclaw.FICHIER_RACINE_MODELE)


def test_la_cli_configurer_nomme_le_fichier_racine_qui_existe_et_cree_openclaw_json_sinon(
        palier_standard, tmp_path, monkeypatch, capsys):
    for nom, valeur in EMBEDDINGS.items():
        monkeypatch.setenv(nom, valeur)
    neuf = tmp_path / "docker"
    assert cli.main(["openclaw", "configurer", "--config-dir", str(neuf)]) == 0
    assert "openclaw.json : créé avec les $include OPSYS" in capsys.readouterr().out
    assert (neuf / "openclaw.json").is_file() and not (neuf / "opsys.json").exists()

    dossier_d_instance = tmp_path / "instance"
    dossier_d_instance.mkdir()
    (dossier_d_instance / "opsys.json").write_text(json.dumps(openclaw.FICHIER_RACINE_MODELE), encoding="utf-8")
    assert cli.main(["openclaw", "configurer", "--config-dir", str(dossier_d_instance)]) == 0
    assert "opsys.json : existant, non modifié" in capsys.readouterr().out
    assert not (dossier_d_instance / "openclaw.json").exists()


def test_un_openclaw_json_existant_est_complete_en_place_sans_creer_opsys_json(
        opsys_home, etat_core, palier_standard):
    etat_core.mkdir(parents=True)
    racine = etat_core / "openclaw.json"
    racine.write_text(json.dumps({"agents": {"defaults": {"nom": "garde"}}}), encoding="utf-8")

    resultat = _initialiser(opsys_home, environ=EMBEDDINGS, port_gateway=18790)

    assert resultat.etat == "pret" and resultat.fichiers["openclaw"] == str(racine)
    assert not (etat_core / "opsys.json").exists()
    config = json.loads(racine.read_text(encoding="utf-8"))
    assert config["agents"] == {"defaults": {"nom": "garde"}}  # rien de l'opérateur n'est écrasé
    assert config["gateway"]["port"] == 18790  # le bloc gateway manquant est ajouté au fichier qui existe


# -- l'ancien dossier du profil (~/.openclaw-opsys) : refusé tant que Doctor ne l'a pas déplacé -----------
JETON_D_AVANT = "jeton-de-l-etat-d-avant-le-lot-3-fictif-0123456789"


def _poser_etat_d_avant(hote: Path) -> Path:
    """L'état qu'une installation faite depuis T0.11-b a posé dans `~/.openclaw-opsys` (le profil `opsys`)."""
    ancien = hote / ".openclaw-opsys"
    (ancien / "opsys").mkdir(parents=True)
    (ancien / ".env").write_text(f"OPSYS_MCP_JETON={JETON_D_AVANT}\n", encoding="utf-8")
    (ancien / "openclaw.json").write_text("{}\n", encoding="utf-8")
    return ancien


def _simuler_doctor(hote: Path) -> Path:
    """Ce que fait Doctor (`core/src/infra/state-migrations.opsys-instance.ts`) : un renommage, puis un lien."""
    ancien, etat = hote / ".openclaw-opsys", hote / ".opsys" / "core"
    etat.parent.mkdir(parents=True, exist_ok=True)
    ancien.rename(etat)
    ancien.symlink_to(etat, target_is_directory=True)
    return etat


def test_l_etat_reste_a_l_ancien_emplacement_est_refuse_avec_la_marche_a_suivre_et_rien_n_est_modifie(
        opsys_home, hote, etat_core, palier_standard):
    ancien = _poser_etat_d_avant(hote)
    avant = _contenu_de_tout(ancien)

    with pytest.raises(instance.ErreurInstance) as refus:
        _initialiser(opsys_home, environ=EMBEDDINGS)

    message = str(refus.value)
    assert "ancien emplacement détecté" in message and str(ancien) in message and str(etat_core) in message
    assert "Rien n'a été modifié" in message
    assert "opsys gateway stop" in message and "opsys doctor --non-interactive" in message
    assert "openclaw" in message  # installation d'avant T0.7 lot 2 : `opsys` y est encore le moteur
    assert "un seul renommage" in message and "ni supprimé" in message
    assert JETON_D_AVANT not in message
    assert _contenu_de_tout(ancien) == avant and not ancien.is_symlink()  # rien n'a bougé
    assert not (hote / ".opsys").exists() and not (opsys_home / "opsys.db").exists()  # rien n'a été écrit non plus


def test_deux_etats_l_ancien_et_le_nouveau_sont_un_conflit_qui_ne_fusionne_ni_ne_supprime_rien(
        opsys_home, hote, etat_core, palier_standard):
    ancien = _poser_etat_d_avant(hote)
    etat_core.mkdir(parents=True)
    (etat_core / ".env").write_text("OPSYS_MCP_JETON=jeton-du-nouvel-etat-fictif-0123456789\n", encoding="utf-8")
    avant_ancien, avant_neuf = _contenu_de_tout(ancien), _contenu_de_tout(etat_core)

    with pytest.raises(instance.ErreurInstance) as refus:
        _initialiser(opsys_home, environ=EMBEDDINGS)

    message = str(refus.value)
    assert "ancien emplacement en conflit" in message and str(ancien) in message and str(etat_core) in message
    assert f"{ancien}.old" in message and f"{etat_core}.old" in message and "décision humaine" in message
    assert "Rien n'a été modifié, fusionné ni supprimé" in message
    assert _contenu_de_tout(ancien) == avant_ancien and _contenu_de_tout(etat_core) == avant_neuf


def test_un_ancien_chemin_qui_est_un_fichier_ou_un_lien_ailleurs_est_refuse_sans_y_toucher(
        opsys_home, hote, etat_core, tmp_path, palier_standard):
    ancien = hote / ".openclaw-opsys"
    ancien.write_text("pas un dossier\n", encoding="utf-8")
    with pytest.raises(instance.ErreurInstance, match="ancien emplacement inattendu"):
        _initialiser(opsys_home, environ=EMBEDDINGS)
    assert ancien.read_text(encoding="utf-8") == "pas un dossier\n"

    ancien.unlink()
    ailleurs = tmp_path / "ailleurs"
    ailleurs.mkdir()
    ancien.symlink_to(ailleurs, target_is_directory=True)
    with pytest.raises(instance.ErreurInstance, match="ancien emplacement inattendu"):
        _initialiser(opsys_home, environ=EMBEDDINGS)
    assert ancien.is_symlink() and not (hote / ".opsys").exists()


def test_apres_doctor_le_lien_laisse_a_l_ancien_chemin_n_est_plus_un_obstacle_et_les_secrets_sont_gardes(
        opsys_home, hote, etat_core, palier_standard):
    _poser_etat_d_avant(hote)
    with pytest.raises(instance.ErreurInstance):
        _initialiser(opsys_home, environ=EMBEDDINGS)

    _simuler_doctor(hote)
    resultat = _initialiser(opsys_home, environ=EMBEDDINGS)

    assert resultat.etat == "pret"
    assert "OPSYS_MCP_JETON" in resultat.env.conservees and "OPSYS_MCP_JETON" not in resultat.env.generees
    assert instance.lire_env(etat_core / ".env")["OPSYS_MCP_JETON"] == JETON_D_AVANT
    assert resultat.fichiers["openclaw"] == str(etat_core / "openclaw.json")  # la configuration d'avant reste lue
    assert not (etat_core / "opsys.json").exists()  # ... et n'est jamais renommée par ce module
    assert (hote / ".openclaw-opsys").is_symlink()  # le lien de Doctor est intact
    assert instance.disposition_du_profil_d_avant(etat_core, hote / ".openclaw-opsys") is None
    assert _initialiser(opsys_home, environ=EMBEDDINGS).etat == "pret"  # relançable


def test_un_ancien_dossier_vide_ou_absent_n_est_pas_un_obstacle(opsys_home, hote, etat_core, palier_standard):
    ancien = hote / ".openclaw-opsys"
    assert instance.disposition_du_profil_d_avant(etat_core, ancien) is None  # absent

    ancien.mkdir()  # vide : Doctor le retirera, il ne porte aucun état à sauver
    assert instance.disposition_du_profil_d_avant(etat_core, ancien) is None
    assert _initialiser(opsys_home, environ=EMBEDDINGS).etat == "pret"
    assert ancien.is_dir() and not any(ancien.iterdir())  # jamais touché ici


def test_le_classement_de_l_ancien_dossier_suit_celui_de_doctor(hote, etat_core, tmp_path):
    ancien = _poser_etat_d_avant(hote)
    assert instance.disposition_du_profil_d_avant(etat_core, ancien) == "a_migrer"

    etat_core.mkdir(parents=True)  # un dossier canonique vide n'est pas un état : Doctor le remplace
    assert instance.disposition_du_profil_d_avant(etat_core, ancien) == "a_migrer"

    (etat_core / "quelque-chose").write_text("x", encoding="utf-8")
    assert instance.disposition_du_profil_d_avant(etat_core, ancien) == "conflit"

    (etat_core / "quelque-chose").unlink()
    etat_core.rmdir()
    etat_core.write_text("un fichier là où l'état devrait être", encoding="utf-8")  # ni dossier ni vide
    assert instance.disposition_du_profil_d_avant(etat_core, ancien) == "conflit"


def test_la_cli_refuse_l_etat_a_l_ancien_emplacement_avec_le_code_1_et_la_marche_a_suivre(
        opsys_home, hote, palier_standard, capsys, monkeypatch):
    for nom, valeur in EMBEDDINGS.items():
        monkeypatch.setenv(nom, valeur)
    _poser_etat_d_avant(hote)

    assert cli.main(["instance", "initialiser", "--source", str(RACINE)]) == 1

    erreur = capsys.readouterr().err
    assert erreur.startswith("ERREUR : ancien emplacement détecté")
    assert "opsys doctor --non-interactive" in erreur and JETON_D_AVANT not in erreur


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


def test_les_noms_du_dossier_d_instance_recopies_du_core_sont_ceux_du_fork():
    """Le module feuille `opsys-instance.ts` dit où est l'état du profil `opsys` et comment s'appelle sa config."""
    instance_ts = (RACINE / "core/src/config/opsys-instance.ts").read_text(encoding="utf-8")
    maintenance_ts = (RACINE / "core/src/cli/program/register.maintenance.ts").read_text(encoding="utf-8")

    assert f'OPSYS_PROFILE = "{instance.PROFIL_CORE}";' in instance_ts
    assert f'OPSYS_INSTANCE_DIRNAME = "{instance.DOSSIER_INSTANCE}";' in instance_ts
    assert f'OPSYS_CORE_DIRNAME = "{instance.SOUS_DOSSIER_CORE}";' in instance_ts
    assert f'OPSYS_LEGACY_PROFILE_DIRNAME = "{instance.ANCIEN_DOSSIER_PROFIL}";' in instance_ts
    assert f'OPSYS_CONFIG_FILENAME = "{instance.NOM_CONFIG}";' in instance_ts
    assert f'OPSYS_LEGACY_CONFIG_FILENAME = "{instance.NOM_CONFIG_ANCIEN}";' in instance_ts
    # le dossier canonique gagne dès qu'il porte un état ; sinon l'ancien, tant qu'il en porte un (repli du core)
    assert "if (dirHasEntries(canonical)) {\n    return canonical;\n  }" in instance_ts
    assert "return dirHasEntries(legacy) ? legacy : canonical;" in instance_ts
    # la configuration : opsys.json d'abord, puis l'openclaw.json qui existe, jamais renommé
    assert instance_ts.index("pathExists(canonical)") < instance_ts.index("pathExists(legacy)")
    # la marche à suivre des refus : Doctor, sans questions (« safe migrations only »)
    assert '.option("--non-interactive", "Run without prompts (safe migrations only)", false)' in maintenance_ts


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

    # dossier d'état : `~/.opsys/core` pour le profil `opsys` (T0.7 lot 3), `~/.openclaw-<profil>` pour les autres
    assert 'const suffix = normalizeLowercaseStringOrEmpty(trimmed) === "default" ? "" : `-${trimmed}`;' in profil
    assert "`.openclaw${suffix}`" in profil
    assert "if (isOpsysProfile(trimmed)) {" in profil
    assert "return resolveOpsysProfileStateDir(resolveRequiredHomeDir(env, homedir));" in profil
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


# -- restreindre_acces : 0600 sous POSIX, DACL privée sous Windows --------------------------------------------------
def test_restreindre_acces_pose_0600_hors_de_windows(tmp_path, monkeypatch):
    fichier = tmp_path / "secret"
    fichier.write_text("x", encoding="utf-8")
    fichier.chmod(0o644)
    appels = _espionner_chmod_posix(monkeypatch)

    instance.restreindre_acces(fichier)

    assert appels == [(fichier, 0o600)]
    if os.name != "nt":
        assert _mode(fichier) == 0o600


def test_restreindre_acces_sous_windows_construit_une_dacl_privee(tmp_path, monkeypatch):
    appels: list[tuple[list[str], dict[str, str]]] = []

    def faux(commande, **options):
        appels.append((list(commande), options["env"]))
        assert options["check"] is False and options["capture_output"] is True
        assert options["timeout"] == 30
        return subprocess.CompletedProcess(commande, 0, "", "")

    monkeypatch.setattr(instance, "_sous_windows", lambda: True)
    monkeypatch.setattr(instance.shutil, "which", lambda executable: "powershell.exe")
    monkeypatch.setattr(instance.subprocess, "run", faux)
    fichier = tmp_path / ".env"
    fichier.write_text("x", encoding="utf-8")
    fichier.chmod(0o644)
    mode_avant = _mode(fichier)

    instance.restreindre_acces(fichier)

    assert len(appels) == 1
    commande, environnement = appels[0]
    assert commande == ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
                        instance._SCRIPT_ACL_WINDOWS]
    assert environnement["OPSYS_INSTANCE_ACL_PATH"] == str(fichier)
    assert environnement["OPSYS_INSTANCE_ACL_DIRECTORY"] == "0"
    assert str(fichier) not in commande[-1]  # le chemin n'est jamais interpolé dans le script PowerShell
    assert "SetAccessRuleProtection($true, $false)" in commande[-1]
    assert "RemoveAccessRuleSpecific" in commande[-1] and "Set-Acl -LiteralPath $path" in commande[-1]
    assert _mode(fichier) == mode_avant  # PowerShell simulé : le mode Unix ne prouve pas une ACL Windows
    assert fichier.read_text(encoding="utf-8") == "x"


@pytest.mark.parametrize("pwsh_disponible", [True, False])
def test_acl_windows_utilise_les_modules_de_sa_propre_version(tmp_path, monkeypatch, pwsh_disponible):
    fichier = tmp_path / "chemin avec espaces et accent é.env"
    fichier.write_text("contenu fictif", encoding="utf-8")
    monkeypatch.setattr(instance, "_sous_windows", lambda: True)
    nom_modules = "PSModulePath"  # orthographe native de PowerShell, aussi testée sous POSIX
    monkeypatch.setenv(nom_modules, "modules-incompatibles-du-shell-parent")
    monkeypatch.setenv("OPSYS_TEST_ENV_CONSERVE", "temoin-fictif")
    recherches = []

    def trouver(nom):
        recherches.append(nom)
        if nom == "pwsh" and not pwsh_disponible:
            return None
        return nom + ".exe"

    def executer(commande, **options):
        assert commande[0] == ("pwsh.exe" if pwsh_disponible else "powershell.exe")
        assert not any(nom.casefold() == "psmodulepath" for nom in options["env"])
        assert options["env"]["OPSYS_TEST_ENV_CONSERVE"] == "temoin-fictif"
        assert options["env"]["OPSYS_INSTANCE_ACL_PATH"] == str(fichier)
        return subprocess.CompletedProcess(commande, 0, "", "")

    monkeypatch.setattr(instance.shutil, "which", trouver)
    monkeypatch.setattr(instance.subprocess, "run", executer)
    instance.restreindre_acces(fichier)
    assert recherches == (["pwsh"] if pwsh_disponible else ["pwsh", "powershell"])
    assert os.environ[nom_modules] == "modules-incompatibles-du-shell-parent"
    assert fichier.read_text(encoding="utf-8") == "contenu fictif"


def test_restreindre_acces_sous_windows_refuse_si_powershell_absent_ou_refuse(tmp_path, monkeypatch):
    fichier = tmp_path / ".env"
    fichier.write_text("x", encoding="utf-8")
    monkeypatch.setattr(instance, "_sous_windows", lambda: True)
    monkeypatch.setattr(instance.shutil, "which", lambda executable: None)

    with pytest.raises(instance.ErreurInstance, match="PowerShell est absent"):
        instance.restreindre_acces(fichier)

    monkeypatch.setattr(instance.shutil, "which", lambda executable: "powershell.exe")
    monkeypatch.setattr(instance.subprocess, "run",
                        lambda commande, **_: subprocess.CompletedProcess(commande, 5, "", "Access is denied."))
    with pytest.raises(instance.ErreurInstance, match="PowerShell a refusé de restreindre l'accès.*Access is denied"):
        instance.restreindre_acces(fichier)


def test_restreindre_dossier_pose_0700_hors_de_windows(tmp_path, monkeypatch):
    dossier = tmp_path / "etat"
    dossier.mkdir()
    dossier.chmod(0o755)
    appels = _espionner_chmod_posix(monkeypatch)

    instance.restreindre_dossier(dossier)

    assert appels == [(dossier, 0o700)]
    if os.name != "nt":
        assert _mode(dossier) == 0o700


def test_restreindre_acces_et_dossier_protegent_effectivement_le_chemin(tmp_path, verifier_acces_prive):
    fichier = tmp_path / ".env"
    fichier.write_text("secret fictif\n", encoding="utf-8")
    instance.restreindre_acces(fichier)
    verifier_acces_prive(fichier, mode=0o600)

    dossier = tmp_path / "core"
    dossier.mkdir()
    instance.restreindre_dossier(dossier)
    verifier_acces_prive(dossier, mode=0o700)


def test_sous_windows_les_dossiers_crees_recoivent_une_dacl_privee_avec_heritage(tmp_path, hote, monkeypatch):
    """Le service écrit ses propres fichiers dans l'état du core (`gateway.cmd` porte les valeurs de `.env`) : leur
    protection est celle du dossier, que les fichiers hériteront (`(OI)(CI)`)."""
    appels: list[tuple[list[str], dict[str, str]]] = []

    def faux(commande, **options):
        appels.append((list(commande), options["env"]))
        return subprocess.CompletedProcess(commande, 0, "", "")

    monkeypatch.setattr(instance, "_sous_windows", lambda: True)
    monkeypatch.setattr(instance.shutil, "which", lambda executable: "powershell.exe")
    monkeypatch.setattr(instance.subprocess, "run", faux)
    home, etat = tmp_path / "instance", hote / ".opsys" / "core"
    existant = tmp_path / "existant"
    existant.mkdir()

    instance._preparer_dossiers([home, etat.parent, etat])
    instance._preparer_dossiers([existant, existant])  # un dossier existant n'est jamais modifié

    assert [env["OPSYS_INSTANCE_ACL_PATH"] for _, env in appels] == [str(home), str(etat.parent), str(etat)]
    assert [env["OPSYS_INSTANCE_ACL_DIRECTORY"] for _, env in appels] == ["1", "1", "1"]
    assert all(commande == ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
                           instance._SCRIPT_ACL_WINDOWS] for commande, _ in appels)
    assert "InheritanceFlags]::ContainerInherit" in instance._SCRIPT_ACL_WINDOWS
    assert "InheritanceFlags]::ObjectInherit" in instance._SCRIPT_ACL_WINDOWS
    assert home.is_dir() and etat.is_dir()
    assert _contenu_de_tout(existant) == {}


def test_restreindre_acces_retirer_une_ace_explicite_etrangere(tmp_path, verifier_acces_prive):
    """Sur Windows, une ACE Everyone réellement ajoutée doit disparaître de la DACL finale."""
    fichier = tmp_path / ".env"
    contenu = "OPSYS_MCP_JETON=secret-fictif\n"
    fichier.write_text(contenu, encoding="utf-8")

    if os.name == "nt":
        powershell = shutil.which("pwsh") or shutil.which("powershell")
        assert powershell is not None
        env = {nom: valeur for nom, valeur in os.environ.items() if nom.casefold() != "psmodulepath"}
        env["OPSYS_TEST_ACL_PATH"] = str(fichier)
        ajout = subprocess.run(
            ["icacls", str(fichier), "/grant", "*S-1-1-0:(R)"],
            capture_output=True, text=True, check=False, timeout=30,
        )
        assert ajout.returncode == 0, ajout.stderr
        verifie_ace = r"""
$ErrorActionPreference = 'Stop'
$acl = Get-Acl -LiteralPath $env:OPSYS_TEST_ACL_PATH
$rules = @($acl.GetAccessRules($true, $false, [System.Security.Principal.SecurityIdentifier]) |
    Where-Object { $_.IdentityReference.Value -eq 'S-1-1-0' -and
                   $_.AccessControlType -eq [System.Security.AccessControl.AccessControlType]::Allow })
if ($rules.Count -lt 1) { exit 7 }
exit 0
"""
        avant = subprocess.run(
            [powershell, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", verifie_ace],
            env=env, capture_output=True, text=True, check=False, timeout=30,
        )
        assert avant.returncode == 0, avant.stderr
    else:
        fichier.chmod(0o644)

    instance.restreindre_acces(fichier)
    verifier_acces_prive(fichier, mode=0o600)
    assert fichier.read_text(encoding="utf-8") == contenu
