"""Génération de la configuration LiteLLM depuis les rôles, alias des clés de département, fichier d'environnement."""

from __future__ import annotations

import os
import stat

import pytest
import yaml
from faux_litellm import CLE_FICTIVE
from modeles_aide import (
    ALIAS,
    AMONT,
    CLE_AMONT,
    PROPRIETAIRE,
    affecter,
    fournisseur_local,
)

from opsys import passerelle
from opsys.roles_modeles import codes, generation, service
from opsys.roles_modeles.codes import ModelesErreur

FICTIF = True
PALIERS = {
    "rapide": {"provider": "anthropic", "model": "claude-haiku-4-5-20251001"},
    "standard": {"provider": "anthropic", "model": "claude-sonnet-5"},
    "local": {"provider": "custom", "model": "qwen3:8b", "base_url": "http://ollama:11434/v1"},
}


def _config(session, paliers=None):
    with session() as cnx:
        return generation.config_depuis_roles(cnx, PALIERS if paliers is None else paliers)


def _par_nom(config):
    return {m["model_name"]: m["litellm_params"] for m in config["model_list"]}


def test_sans_role_ni_palier_aucune_configuration(session):
    with pytest.raises(ValueError, match="aucun palier"):
        _config(session, {})


def test_sans_role_les_paliers_historiques_sont_inchanges(session):
    assert _config(session) == passerelle.config_litellm(PALIERS)


def test_roles_et_alias_de_palier_et_aucune_cle_dans_le_yaml(pret):
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"], amont=AMONT["llm_rapide"])
    affecter(pret, "llm_fort", ALIAS["llm_fort"], amont=AMONT["llm_fort"])
    affecter(pret, "embeddings", ALIAS["embeddings"], amont=AMONT["embeddings"])
    modeles = _par_nom(_config(pret))
    assert modeles["opsys-haiku-5-5"] == {
        "model": "openrouter/anthropic/claude-haiku-5.5",
        "api_key": "os.environ/OPENROUTER_API_KEY",
    }
    # un palier lit l'alias du rôle correspondant : rapide ← llm_rapide ; standard et fort ← llm_fort
    assert modeles["opsys-rapide"] == modeles["opsys-haiku-5-5"]
    assert modeles["opsys-standard"] == modeles["opsys-fort"] == modeles["opsys-sonnet-5-5"]
    assert modeles["opsys-embed-e5-multilingue"]["model"] == "openrouter/intfloat/multilingual-e5-large"
    assert modeles["opsys-local"]["api_base"] == "http://ollama:11434/v1"  # palier sans rôle : conservé
    texte = yaml.safe_dump(_config(pret))
    assert CLE_FICTIVE not in texte and CLE_AMONT not in texte


def test_les_roles_l_emportent_sur_un_palier_de_meme_alias_sans_doublon(pret):
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"], amont=AMONT["llm_rapide"])
    noms = [m["model_name"] for m in _config(pret)["model_list"]]
    assert noms.count("opsys-rapide") == 1  # deux entrées de même nom seraient équilibrées en charge par LiteLLM
    assert _par_nom(_config(pret))["opsys-rapide"]["model"].startswith("openrouter/")


def test_le_raisonnement_n_est_dans_la_configuration_que_s_il_est_actif(pret):
    affecter(pret, "llm_raisonnement", ALIAS["llm_raisonnement"], amont=AMONT["llm_raisonnement"])
    assert "opsys-opus-5-5" not in _par_nom(_config(pret))
    with pret() as cnx:
        service.appliquer(
            cnx,
            acteur=PROPRIETAIRE,
            operation=service.OP_RAISONNEMENT_ACTIVER,
            niveau_confirme="N3",
            parametres={},
            motif="Analyse contractuelle complexe du dossier fictif",
        )
    modeles = _par_nom(_config(pret))
    assert modeles["opsys-opus-5-5"]["model"] == "openrouter/anthropic/claude-opus-5.5"
    # aucun palier ne mène au raisonnement, même actif
    assert modeles["opsys-fort"] != modeles["opsys-opus-5-5"] if "opsys-fort" in modeles else True
    assert all(
        modeles[p].get("model") != "openrouter/anthropic/claude-opus-5.5"
        for p in ("opsys-rapide", "opsys-standard", "opsys-fort")
        if p in modeles
    )


def test_replis_locaux_deviennent_entrees_et_fallbacks_natifs(pret, faux_local):
    local = fournisseur_local(pret, "llm.local.fictif", "http://127.0.0.1:8000/v1")
    affecter(
        pret,
        "llm_rapide",
        ALIAS["llm_rapide"],
        amont=AMONT["llm_rapide"],
        replis=[{"fournisseur": local, "modele": "qwen-local-fictif"}],
    )
    config = _config(pret)
    modeles = _par_nom(config)
    assert modeles["opsys-haiku-5-5-repli1"] == {
        "model": "openai/qwen-local-fictif",
        "api_base": "http://127.0.0.1:8000/v1",
        "api_key": "local",
    }
    repli = {k: v for d in config["litellm_settings"]["fallbacks"] for k, v in d.items()}
    assert repli["opsys-haiku-5-5"] == ["opsys-haiku-5-5-repli1"]
    assert repli["opsys-rapide"] == ["opsys-haiku-5-5-repli1"]


def test_un_role_sans_amont_ou_hors_passerelle_n_ajoute_pas_d_entree(pret, faux_local):
    local = fournisseur_local(pret, "llm.local.fictif", "http://127.0.0.1:8000/v1")
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"])  # passerelle EXISTANTE : le client gère ses modèles
    with pret() as cnx:
        service.appliquer(
            cnx,
            acteur=PROPRIETAIRE,
            operation=service.OP_ROLE_AFFECTER,
            niveau_confirme="N3",
            parametres={"role": "llm_fort", "fournisseur_id": local, "modele_appel": "qwen-local-fictif"},
        )
    noms = set(_par_nom(_config(pret)))
    assert "opsys-haiku-5-5" not in noms and "qwen-local-fictif" not in noms
    assert noms == {"opsys-local", "opsys-rapide", "opsys-standard"}


def test_cles_virtuelles_des_departements_ne_portent_jamais_le_raisonnement_ni_un_repli(pret, faux_local):
    local = fournisseur_local(pret, "llm.local.fictif", "http://127.0.0.1:8000/v1")
    affecter(
        pret,
        "llm_rapide",
        ALIAS["llm_rapide"],
        amont=AMONT["llm_rapide"],
        replis=[{"fournisseur": local, "modele": "qwen-local-fictif"}],
    )
    affecter(pret, "llm_raisonnement", ALIAS["llm_raisonnement"], amont=AMONT["llm_raisonnement"])
    with pret() as cnx:
        service.appliquer(
            cnx,
            acteur=PROPRIETAIRE,
            operation=service.OP_RAISONNEMENT_ACTIVER,
            niveau_confirme="N3",
            parametres={},
            motif="Analyse contractuelle complexe du dossier fictif",
        )
        alias = generation.alias_pour_cles_departements(cnx, PALIERS)
    assert "opsys-opus-5-5" not in alias
    assert "opsys-haiku-5-5" in alias and {"opsys-rapide", "opsys-standard", "opsys-local"} <= set(alias)
    assert alias == sorted(alias)


# -- fichier d'environnement des clés ---------------------------------------------------------------------------------
def test_ecrire_env_depuis_le_coffre_en_0600_sans_rendre_de_valeur(pret, tmp_path):
    dossier = tmp_path / "partage"
    dossier.mkdir(mode=0o750)
    noms = generation.ecrire_env(pret, dossier / "litellm.env")
    assert noms == ["LITELLM_MASTER_KEY", "OPENROUTER_API_KEY"]  # des NOMS de variables, jamais de valeur
    contenu = (dossier / "litellm.env").read_text()
    assert contenu == f"LITELLM_MASTER_KEY={CLE_FICTIVE}\nOPENROUTER_API_KEY={CLE_AMONT}\n"
    assert stat.S_IMODE(os.stat(dossier / "litellm.env").st_mode) == 0o600
    assert [p.name for p in dossier.iterdir()] == ["litellm.env"]  # aucun temporaire laissé


def test_ecrire_env_remplace_atomiquement_et_reste_en_0600(pret, tmp_path):
    chemin = tmp_path / "litellm.env"
    chemin.write_text("ancien")
    os.chmod(chemin, 0o644)
    generation.ecrire_env(pret, chemin)
    assert stat.S_IMODE(os.stat(chemin).st_mode) == 0o600 and "ancien" not in chemin.read_text()


def test_ecrire_env_refuse_lien_symbolique_et_dossier_inscriptible_par_tous(pret, tmp_path):
    cible = tmp_path / "cible"
    cible.write_text("x")
    (tmp_path / "lien.env").symlink_to(cible)
    with pytest.raises(ModelesErreur) as exc:
        generation.ecrire_env(pret, tmp_path / "lien.env")
    assert exc.value.code == codes.DECLARATION_INVALIDE and cible.read_text() == "x"
    ouvert = tmp_path / "ouvert"
    ouvert.mkdir()
    os.chmod(ouvert, 0o777)
    with pytest.raises(ModelesErreur):
        generation.ecrire_env(pret, ouvert / "litellm.env")
    with pytest.raises(ModelesErreur):
        generation.ecrire_env(pret, tmp_path / "absent" / "litellm.env")


def test_ecrire_env_exige_une_passerelle_integree_et_des_secrets_valides(session, cle_coffre, tmp_path, faux):
    from modeles_aide import connecter_passerelle, declarer_profil, definir_secrets, preparer_identites

    with pytest.raises(ModelesErreur) as exc:
        generation.ecrire_env(session, tmp_path / "e.env")
    assert exc.value.code == codes.PASSERELLE_ABSENTE
    preparer_identites(session)
    declarer_profil(session)
    definir_secrets(session, CLE_FICTIVE)
    with session() as cnx:
        service.appliquer(
            cnx,
            acteur=PROPRIETAIRE,
            operation=service.OP_PASSERELLE_CONFIGURER,
            niveau_confirme="N3",
            parametres={"mode": "existante", "url_base": faux.url, "secret_cle": "passerelle.cle"},
        )
    with pytest.raises(ModelesErreur) as exc:  # la clé d'une passerelle existante reste chez le client
        generation.ecrire_env(session, tmp_path / "e.env")
    assert "existante" in exc.value.detail and not (tmp_path / "e.env").exists()
    connecter_passerelle(session, faux.url)
    from opsys.secrets_coffre import coffre

    with session() as cnx:
        coffre.revoquer(cnx, acteur=PROPRIETAIRE, nom="passerelle.openrouter")
    with pytest.raises(ModelesErreur) as exc:
        generation.ecrire_env(session, tmp_path / "e.env")
    assert exc.value.code == codes.SECRET_INDISPONIBLE and not (tmp_path / "e.env").exists()


# -- les rôles fournissent leurs paliers aux agents (mode LiteLLM) ----------------------------------------------------
def test_paliers_fournis_par_les_roles_sans_toucher_le_yaml(pret):
    with pret() as cnx:
        assert generation.paliers_depuis_roles(cnx) == {}
    affecter(pret, "llm_rapide", ALIAS["llm_rapide"], amont=AMONT["llm_rapide"])
    affecter(pret, "llm_fort", ALIAS["llm_fort"], amont=AMONT["llm_fort"])
    affecter(pret, "llm_raisonnement", ALIAS["llm_raisonnement"], amont=AMONT["llm_raisonnement"])
    with pret() as cnx:
        roles = generation.paliers_depuis_roles(cnx)
        effectifs = generation.paliers_effectifs(cnx, PALIERS)
    assert sorted(roles) == ["fort", "rapide", "standard"]  # jamais un palier vers le raisonnement
    assert roles["standard"]["model"] == "opsys-standard"
    assert effectifs["local"] == PALIERS["local"]  # un palier sans rôle reste celui du YAML
    assert effectifs["rapide"] == roles["rapide"]  # les rôles l'emportent


def test_openclaw_litellm_avec_roles_seulement_sans_paliers_yaml(pret, tmp_path, departements_demo, faux):
    import json

    from agents_base_qa import provisionner_base_qa

    from opsys import openclaw

    affecter(pret, "llm_fort", ALIAS["llm_fort"], amont=AMONT["llm_fort"])
    provisionner_base_qa(pret, departements_demo)
    with pret() as cnx:
        paliers = generation.paliers_effectifs(cnx, {})
    fichiers = openclaw.generer(
        departements_demo, tmp_path, paliers, mode_fournisseur="litellm", url_passerelle=faux.url + "/v1",
        environ={"OPSYS_EMBEDDINGS_URL": "http://embeddings-test:11434/v1", "OPSYS_EMBEDDINGS_MODELE": "bge-m3"},
        cnx_factory=pret)
    agents = json.loads(fichiers["agents"].read_text(encoding="utf-8"))["entries"]
    assert agents["m09-demo"]["model"] == "opsys-m9/opsys-standard"  # alias de `config_depuis_roles`
    assert "opsys-standard" in _par_nom(_config(pret, {}))
