"""CLI `fournisseurs …` et `coffre …` : authentification personnelle, aucune valeur affichée (données fictives)."""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from opsys import cli, identite
from opsys.fournisseurs import cli as plateforme_cli
from opsys.fournisseurs import sondes
from opsys.secrets_coffre import cle_maitresse

FICTIF = True
_MDP = "mot-de-passe-cli-plateforme-fictif-2026"
VALEUR = "valeur-fictive-cli-cle-api-0123456789-AZERTY"


@pytest.fixture
def operateur(session, tmp_path, monkeypatch):
    dossier = tmp_path / "cles"
    dossier.mkdir(mode=0o700)
    cle_maitresse.generer_fichier(dossier / "coffre.cle")
    monkeypatch.setenv(cle_maitresse.ENV_FICHIER, str(dossier / "coffre.cle"))
    with session() as cnx:
        identite.creer_personne(cnx, "admin_fictif", "Admin fictif", _MDP, ["admin"])
        identite.creer_personne(cnx, "vendeur_fictif", "Vendeur fictif", _MDP, ["seller"])
    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(cli, "_lire_mot_de_passe_personne", lambda: _MDP)
    monkeypatch.setattr(plateforme_cli.getpass, "getpass", lambda invite="": VALEUR)
    monkeypatch.setattr(sondes, "_ouvrir_reel", lambda *a, **k: pytest.fail("appel réseau réel interdit"))
    return dossier


def _executer(capsys, *argv):
    code = cli.main(list(argv))
    sortie = capsys.readouterr()
    return code, sortie.out, sortie.err


def test_secrets_definir_lister_revoquer_sans_jamais_afficher_la_valeur(operateur, capsys):
    code, out, err = _executer(capsys, "coffre", "definir", "quickbooks.api", "--service", "quickbooks",
                               "--par", "admin_fictif")
    assert code == 0 and json.loads(out)["etat"] == "actif"
    sorties = [out, err]
    for argv in (("coffre", "lister"), ("coffre", "journal"), ("coffre", "journal", "quickbooks.api"),
                 ("coffre", "rotation", "quickbooks.api", "--par", "admin_fictif"),
                 ("coffre", "revoquer", "quickbooks.api", "--confirmer", "--par", "admin_fictif"),
                 ("fournisseurs", "lister"), ("fournisseurs", "lister", "--json")):
        code, out, err = _executer(capsys, *argv)
        assert code == 0, argv
        sorties += [out, err]
    assert all(VALEUR not in s and VALEUR[:16] not in s for s in sorties)
    assert json.loads(_executer(capsys, "coffre", "lister")[1])[0]["etat"] == "revoque"


def test_valeur_jamais_en_argument_et_confirmation(operateur, capsys, monkeypatch):
    for argv in (["coffre", "definir", "meta.ads", "--service", "meta", "--valeur", VALEUR, "--par", "admin_fictif"],
                 ["coffre", "definir", "meta.ads", VALEUR, "--service", "meta", "--par", "admin_fictif"],
                 ["coffre", "rotation", "meta.ads", "--valeur=" + VALEUR, "--par", "admin_fictif"]):
        with pytest.raises(SystemExit):
            cli.main(argv)
        sortie = capsys.readouterr()
        assert VALEUR not in sortie.out + sortie.err and "refusée en argument" in sortie.err
    reponses = iter([VALEUR, VALEUR + "x"])
    monkeypatch.setattr(plateforme_cli.getpass, "getpass", lambda invite="": next(reponses))
    code, out, err = _executer(capsys, "coffre", "definir", "meta.ads", "--service", "meta", "--par", "admin_fictif")
    assert code == 1 and "COFFRE_CONFIRMATION_DIFFERENTE" in err and VALEUR not in out + err
    assert json.loads(_executer(capsys, "coffre", "lister")[1]) == []


def test_ecritures_exigent_un_admin_authentifie(operateur, capsys, monkeypatch):
    code, out, err = _executer(capsys, "coffre", "definir", "meta.ads", "--service", "meta", "--par",
                               "vendeur_fictif")
    assert code == 1 and "authentification personnelle requise" in err
    monkeypatch.setattr("sys.stdin", SimpleNamespace(isatty=lambda: False))
    code, _, err = _executer(capsys, "fournisseurs", "activer", "ocr.paddleocr.local", "--par", "admin_fictif")
    assert code == 1 and "authentification personnelle requise" in err


def test_fournisseurs_configurer_activer_refus_et_tester(operateur, capsys, monkeypatch):
    requetes = []
    # Sonde simulée : l'ouverture HTTP est remplacée (aucun réseau) ; on vérifie l'en-tête injecté côté serveur.
    monkeypatch.setattr(sondes, "_ouvrir_reel", lambda requete, delai: requetes.append(requete) or 200)
    code, _, _ = _executer(capsys, "fournisseurs", "profil", "--usage-commercial", "oui", "--revenu-usd", "2000000",
                           "--territoire", "CA", "--heberge-pour-tiers", "non", "--par", "admin_fictif")
    assert code == 0
    assert _executer(capsys, "fournisseurs", "configurer", "tts.fish-speech", "--par", "admin_fictif")[0] == 0
    code, out, _ = _executer(capsys, "fournisseurs", "activer", "tts.fish-speech", "--par", "admin_fictif")
    assert code == 1 and "SEUIL_REVENU_DEPASSE" in out and "FOURNISSEUR_ECARTE" in out
    _executer(capsys, "coffre", "definir", "azure.tts", "--service", "microsoft", "--par", "admin_fictif")
    code, out, err = _executer(capsys, "fournisseurs", "configurer", "tts.azure-fr-ca.api", "--point-acces",
                               "https://tts.fictif.example/v1", "--secret", "coffre:azure.tts", "--efvp-ref",
                               "efvp-fictive", "--contrat-ref", "contrat-fictif", "--par", "admin_fictif")
    assert code == 0, err
    assert json.loads(out)["politique"]["conforme"]
    code, out, _ = _executer(capsys, "fournisseurs", "tester", "tts.azure-fr-ca.api", "--par", "admin_fictif")
    assert code == 0 and json.loads(out)["statut"] == "succes" and VALEUR not in out
    [requete] = requetes
    assert requete.full_url == "https://tts.fictif.example/v1/models"
    assert requete.get_header("Authorization") == f"Bearer {VALEUR}"
    code, out, _ = _executer(capsys, "fournisseurs", "activer", "tts.azure-fr-ca.api", "--par", "admin_fictif")
    assert code == 0 and json.loads(out)["conforme"]
    code, out, _ = _executer(capsys, "fournisseurs", "selectionner", "tts", "tts.azure-fr-ca.api", "--departement",
                             "m01-front-office", "--par", "admin_fictif")
    assert code == 0 and json.loads(out)["portee"] == "m01-front-office"


def test_generer_cle_et_rechiffrer_sans_afficher_de_cle(operateur, capsys, monkeypatch):
    _executer(capsys, "coffre", "definir", "linkedin.api", "--service", "linkedin", "--par", "admin_fictif")
    nouvelle = operateur / "nouvelle.cle"
    code, out, _ = _executer(capsys, "coffre", "generer-cle-maitresse", "--fichier", str(nouvelle))
    assert code == 0 and nouvelle.read_text().strip() not in out
    code, out, err = _executer(capsys, "coffre", "rechiffrer", "--nouvelle-cle-fichier", str(nouvelle),
                               "--par", "admin_fictif")
    assert code == 0, err
    assert json.loads(out)["versions_reenveloppees"] == 1 and nouvelle.read_text().strip() not in out
    monkeypatch.setenv(cle_maitresse.ENV_FICHIER, str(nouvelle))
    from opsys.secrets_coffre import coffre

    with coffre.utiliser(nom="linkedin.api", usage="connecteur:linkedin", acteur="opsys-systeme") as valeur:
        assert valeur == VALEUR
