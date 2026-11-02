"""`opsys-metier modeles …` : authentification personnelle, N3 confirmé, aucune valeur de secret affichée."""

from __future__ import annotations

import json
import os
import stat

import pytest
from faux_litellm import CLE_FICTIVE
from modeles_aide import (
    ALIAS,
    CLE_AMONT,
    PROPRIETAIRE,
    declarer_profil,
    definir_secrets,
    preparer_identites,
)

from opsys import cli
from opsys.roles_modeles import cli as modeles_cli
from opsys.roles_modeles import service

FICTIF = True


@pytest.fixture
def humain(monkeypatch):
    """Simule le step-up personnel réussi (l'authentification réelle exige un terminal interactif)."""
    monkeypatch.setattr(modeles_cli, "_authentifier", lambda cnx, par: True)


def _lancer(capsys, *argv):
    code = cli.main(["modeles", *argv])
    sortie = capsys.readouterr()
    return code, sortie.out, sortie.err


def test_lecture_etat_et_economie_sans_authentification(session, capsys):
    code, out, _ = _lancer(capsys, "etat", "--json")
    vue = json.loads(out)
    assert code == 0 and len(vue["roles"]) == 10 and vue["passerelle"] == {"configuree": False}
    code, out, _ = _lancer(capsys, "etat")
    assert code == 0 and "passerelle : non configurée" in out and "raisonnement : inactif" in out
    assert out.count("inerte") == 10
    code, out, _ = _lancer(capsys, "economie")
    politique = json.loads(out)
    assert code == 0 and politique["statut"] == "recommandation_non_validee"
    assert politique["classes"]["classification"]["role"] == "llm_rapide"


def test_ecriture_sans_terminal_interactif_est_refusee(session, cle_coffre, capsys):
    preparer_identites(session)
    code, _, err = _lancer(capsys, "raisonnement", "desactiver", "--par", PROPRIETAIRE)
    assert code == 1 and "authentification personnelle requise" in err
    code, _, err = _lancer(capsys, "passerelle", "tester", "--par", PROPRIETAIRE)
    assert code == 1 and "authentification personnelle requise" in err


def test_geste_n3_sans_confirmer_n3_est_refuse(session, cle_coffre, faux, humain, capsys):
    preparer_identites(session)
    declarer_profil(session)
    definir_secrets(session, CLE_FICTIVE)
    code, _, err = _lancer(
        capsys,
        "passerelle",
        "connecter",
        "--mode",
        "integree",
        "--url",
        faux.url,
        "--secret-cle",
        "passerelle.cle",
        "--par",
        PROPRIETAIRE,
    )
    assert code == 1 and "REJ-MODELES-CONFIRMATION-N3-REQUISE" in err
    with session() as cnx:
        assert service.passerelle(cnx) is None


def test_parcours_cli_connecter_tester_affecter_config_env(session, cle_coffre, faux, humain, capsys, tmp_path):
    preparer_identites(session)
    declarer_profil(session)
    definir_secrets(session, CLE_FICTIVE)
    code, out, _ = _lancer(
        capsys,
        "passerelle",
        "connecter",
        "--mode",
        "integree",
        "--url",
        faux.url,
        "--secret-cle",
        "passerelle.cle",
        "--secret-amont",
        "openrouter=passerelle.openrouter",
        "--par",
        PROPRIETAIRE,
        "--confirmer-n3",
    )
    assert code == 0 and json.loads(out)["passerelle"]["secrets_amont"] == {"openrouter": "passerelle.openrouter"}
    code, out, _ = _lancer(capsys, "passerelle", "tester", "--par", PROPRIETAIRE)
    assert code == 0 and json.loads(out)["modeles"] == 6 and "opsys-haiku-5-5" in json.loads(out)["alias"]
    code, out, err = _lancer(
        capsys,
        "role",
        "connecter",
        "llm_rapide",
        "--alias",
        ALIAS["llm_rapide"],
        "--amont",
        "openrouter/anthropic/claude-haiku-5.5",
        "--efvp-ref",
        "EFVP-F-1",
        "--contrat-ref",
        "CONTRAT-F-1",
        "--plafond-jetons-jour",
        "5000",
        "--par",
        PROPRIETAIRE,
        "--confirmer-n3",
    )
    assert code == 0, err
    assert json.loads(out)["plafond_jetons_jour"] == 5000
    code, out, _ = _lancer(capsys, "role", "tester", "llm_rapide", "--par", PROPRIETAIRE)
    assert code == 0 and json.loads(out)["statut"] == "succes"
    code, out, _ = _lancer(capsys, "role", "plafonds", "llm_rapide", "--budget-usd-mois", "4", "--par", PROPRIETAIRE)
    assert code == 0 and json.loads(out)["budget_usd_mois"] == "4"
    sortie = tmp_path / "litellm.yaml"
    code, _, _ = _lancer(capsys, "passerelle", "config", "--sortie", str(sortie))
    texte = sortie.read_text()
    assert code == 0 and "openrouter/anthropic/claude-haiku-5.5" in texte
    assert CLE_FICTIVE not in texte and CLE_AMONT not in texte
    env = tmp_path / "litellm.env"
    code, out, _ = _lancer(capsys, "passerelle", "ecrire-env", "--fichier", str(env), "--par", PROPRIETAIRE)
    assert code == 0 and stat.S_IMODE(os.stat(env).st_mode) == 0o600
    assert CLE_FICTIVE not in out and CLE_AMONT not in out  # la sortie ne dit que les NOMS de variables
    assert json.loads(out)["variables"] == ["LITELLM_MASTER_KEY", "OPENROUTER_API_KEY"]
    code, out, _ = _lancer(capsys, "role", "retirer", "llm_rapide", "--par", PROPRIETAIRE, "--confirmer-n3")
    assert code == 0 and json.loads(out)["configure"] is False
    code, out, _ = _lancer(capsys, "role", "revenir", "role:llm_rapide", "--par", PROPRIETAIRE, "--confirmer-n3")
    assert code == 0 and json.loads(out)["configure"] is True
    code, out, _ = _lancer(capsys, "etat")
    assert code == 0 and "llm.passerelle.opsys-haiku-5-5" in out and CLE_FICTIVE not in out


def test_raisonnement_par_la_cli_exige_motif_et_n3(session, cle_coffre, faux, humain, capsys):
    preparer_identites(session)
    declarer_profil(session)
    definir_secrets(session, CLE_FICTIVE)
    _lancer(
        capsys,
        "passerelle",
        "connecter",
        "--mode",
        "integree",
        "--url",
        faux.url,
        "--secret-cle",
        "passerelle.cle",
        "--par",
        PROPRIETAIRE,
        "--confirmer-n3",
    )
    _lancer(
        capsys,
        "role",
        "connecter",
        "llm_raisonnement",
        "--alias",
        ALIAS["llm_raisonnement"],
        "--efvp-ref",
        "E-1",
        "--contrat-ref",
        "C-1",
        "--par",
        PROPRIETAIRE,
        "--confirmer-n3",
    )
    code, _, err = _lancer(
        capsys, "raisonnement", "activer", "--motif", "Analyse contractuelle complexe", "--par", PROPRIETAIRE
    )
    assert code == 1 and "CONFIRMATION-N3-REQUISE" in err
    code, _, err = _lancer(capsys, "raisonnement", "activer", "--par", PROPRIETAIRE, "--confirmer-n3")
    assert code == 1 and "CONFIRMATION-N3-REQUISE" in err  # sans motif
    code, out, _ = _lancer(
        capsys,
        "raisonnement",
        "activer",
        "--motif",
        "Analyse contractuelle complexe",
        "--par",
        PROPRIETAIRE,
        "--confirmer-n3",
    )
    assert code == 0 and json.loads(out)["raisonnement"]["actif"] is True
    code, out, _ = _lancer(capsys, "raisonnement", "desactiver", "--par", PROPRIETAIRE)
    assert code == 0 and json.loads(out)["raisonnement"]["actif"] is False


def test_importer_cle_copie_une_variable_autorisee_vers_le_coffre_sans_l_afficher(
    session, cle_coffre, humain, monkeypatch, capsys
):
    from opsys.secrets_coffre import coffre

    preparer_identites(session)
    monkeypatch.setenv("LITELLM_MASTER_KEY", CLE_FICTIVE)
    code, out, err = _lancer(
        capsys,
        "passerelle",
        "importer-cle",
        "--depuis-env",
        "LITELLM_MASTER_KEY",
        "--nom",
        "passerelle.cle",
        "--par",
        PROPRIETAIRE,
    )
    assert code == 0 and CLE_FICTIVE not in out + err
    with session() as cnx:
        assert [m["nom"] for m in coffre.lister(cnx)] == ["passerelle.cle"]
    with coffre.utiliser(nom="passerelle.cle", usage="fournisseur:test", acteur="test") as valeur:
        assert valeur == CLE_FICTIVE
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    code, _, err = _lancer(
        capsys,
        "passerelle",
        "importer-cle",
        "--depuis-env",
        "OPENROUTER_API_KEY",
        "--nom",
        "passerelle.openrouter",
        "--par",
        PROPRIETAIRE,
    )
    assert code == 1 and "vide" in err
    with pytest.raises(SystemExit):  # seules les variables de clés connues sont importables
        cli.main(["modeles", "passerelle", "importer-cle", "--depuis-env", "HOME", "--nom", "x.y.z", "--par", "p"])


def test_commandes_passerelle_existantes_lisent_la_cle_du_coffre(
    session, cle_coffre, faux, humain, capsys, monkeypatch
):
    """`passerelle cles` : la clé d'administration vient du coffre quand la passerelle est connectée, sinon de l'env."""
    from opsys.roles_modeles import acces

    preparer_identites(session)
    declarer_profil(session)
    definir_secrets(session, CLE_FICTIVE)
    monkeypatch.setenv("LITELLM_MASTER_KEY", "cle-env-fictive-0123456789-ZZZZZZ")
    with acces.cle_maitre(session) as cle:
        assert cle == "cle-env-fictive-0123456789-ZZZZZZ"  # pas de passerelle connectée : l'environnement, comme avant
    _lancer(
        capsys,
        "passerelle",
        "connecter",
        "--mode",
        "existante",
        "--url",
        faux.url,
        "--secret-cle",
        "passerelle.cle",
        "--par",
        PROPRIETAIRE,
        "--confirmer-n3",
    )
    with acces.cle_maitre(session) as cle:
        assert cle == CLE_FICTIVE  # le coffre l'emporte
    monkeypatch.delenv("LITELLM_MASTER_KEY")
    from opsys.secrets_coffre import coffre

    with session() as cnx:
        coffre.revoquer(cnx, acteur=PROPRIETAIRE, nom="passerelle.cle")
    with acces.cle_maitre(session) as cle:
        assert cle == ""  # rien : le client d'administration la refusera
