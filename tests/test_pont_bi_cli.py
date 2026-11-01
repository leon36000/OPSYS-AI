"""CLI `opsys-metier pont-bi …` : émettre et révoquer sont des gestes HUMAINS (step-up personnel, terminal interactif).

Prouve : sans terminal interactif (un agent, un script) l'émission est refusée sans rien écrire ; avec une personne
authentifiée admin elle réussit et rend le jeton UNE fois sur la sortie standard ; un employé ne peut pas émettre ; la
liste, le journal et les jeux sont en lecture seule et ne montrent jamais un secret ; la commande est déclarée au core.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from opsys import cli, identite
from opsys.pont_bi import service
from opsys.secrets_coffre import cle_maitresse

FICTIF = True
MOT_DE_PASSE = "mot-de-passe-pont-cli-fictif-2026"


@pytest.fixture
def instance(session, tmp_path, monkeypatch):
    dossier = tmp_path / "cles"
    dossier.mkdir(mode=0o700)
    cle_maitresse.generer_fichier(dossier / "coffre.cle")
    monkeypatch.setenv(cle_maitresse.ENV_FICHIER, str(dossier / "coffre.cle"))
    monkeypatch.delenv(cle_maitresse.ENV_CLE, raising=False)
    with session() as cnx:
        identite.creer_personne(cnx, "admin_fictif", "Admin fictif", MOT_DE_PASSE, ["admin"])
        identite.creer_personne(cnx, "employe_fictif", "Employé fictif", MOT_DE_PASSE, ["employee"])
    return session


def _humain(monkeypatch, mot_de_passe=MOT_DE_PASSE):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True, raising=False)
    monkeypatch.setattr(cli, "_lire_mot_de_passe_personne", lambda: mot_de_passe)


def _lancer(*arguments):
    return cli.main(["pont-bi", *arguments])


def _tokens(session):
    with session() as cnx:
        return service.lister(cnx)


def test_sans_terminal_interactif_l_emission_est_refusee_et_rien_n_est_ecrit(instance, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False, raising=False)
    code = _lancer("jeton-emettre", "--par", "admin_fictif", "--libelle", "Metabase fictif", "--jeux", "chantiers")
    sortie = capsys.readouterr()
    assert code == 1 and "authentification personnelle requise" in sortie.err and "opsys-bi:v1:" not in sortie.out
    assert _tokens(instance) == []


@pytest.mark.parametrize(
    ("personne", "mot_de_passe"),
    [("employe_fictif", MOT_DE_PASSE), ("admin_fictif", "mauvais"), ("inconnu", MOT_DE_PASSE)],
)
def test_une_personne_non_admin_ou_mal_authentifiee_n_emet_rien(instance, capsys, monkeypatch, personne, mot_de_passe):
    _humain(monkeypatch, mot_de_passe)
    code = _lancer("jeton-emettre", "--par", personne, "--libelle", "Metabase fictif", "--jeux", "chantiers")
    sortie = capsys.readouterr()
    assert code == 1 and "opsys-bi:v1:" not in sortie.out and _tokens(instance) == []


def test_l_admin_authentifie_emet_un_jeton_rendu_une_fois_puis_le_revoque(instance, capsys, monkeypatch):
    _humain(monkeypatch)
    code = _lancer(
        "jeton-emettre",
        "--par",
        "admin_fictif",
        "--libelle",
        "Metabase fictif",
        "--jeux",
        "chantiers,mesures_courantes",
        "--quota-requetes",
        "10",
        "--duree-jours",
        "7",
    )
    sortie = capsys.readouterr()
    assert code == 0 and "UNE fois" in sortie.err
    resultat = json.loads(sortie.out)
    assert re.fullmatch(r"opsys-bi:v1:[0-9a-f]{32}\.[A-Za-z0-9_-]{43}", resultat["jeton"])
    assert resultat["jeux"] == ["chantiers", "mesures_courantes"] and resultat["quota_requetes_heure"] == 10
    assert resultat["financier"] is False
    # la liste ne montre jamais le secret
    assert _lancer("jetons") == 0
    liste = capsys.readouterr().out
    assert resultat["jeton"].split(".")[1] not in liste and json.loads(liste)[0]["etat"] == "actif"
    assert _lancer("jeton-revoquer", "--par", "admin_fictif", resultat["jeton_id"]) == 0
    capsys.readouterr()
    assert _tokens(instance)[0]["etat"] == "revoque"


@pytest.mark.parametrize(
    "arguments",
    [
        ["--libelle", "ab", "--jeux", "chantiers"],
        ["--libelle", "Metabase fictif", "--jeux", "inconnu"],
        ["--libelle", "Metabase fictif", "--jeux", "chantiers", "--quota-requetes", "0"],
        ["--libelle", "Metabase fictif", "--jeux", "chantiers", "--duree-jours", "0"],
    ],
)
def test_une_emission_invalide_sort_en_refus_type(instance, capsys, monkeypatch, arguments):
    _humain(monkeypatch)
    assert _lancer("jeton-emettre", "--par", "admin_fictif", *arguments) == 2
    erreur = capsys.readouterr().err
    assert re.search(r"^[a-z_]+ : ", erreur) and "opsys-bi:v1:" not in erreur  # un refus typé, sans jeton
    assert _tokens(instance) == []


def test_jeux_et_journal_sont_en_lecture_seule(instance, capsys):
    assert _lancer("jeux") == 0
    jeux = json.loads(capsys.readouterr().out)
    assert {j["jeu"] for j in jeux} >= {"mesures_courantes", "chantiers", "devis", "leads", "contenus", "constructions"}
    financieres = {c["nom"] for j in jeux for c in j["colonnes"] if c["financiere"]}
    assert financieres == {"verdict_marge", "marge_reelle_cad", "prix_total_cad"}
    assert _lancer("journal", "--limite", "5") == 0
    assert json.loads(capsys.readouterr().out) == []


def test_la_commande_est_declaree_au_core_et_a_l_installateur():
    racine = Path(__file__).resolve().parents[1]
    assert '"pont-bi"' in (racine / "core/src/cli/opsys-metier-argv.ts").read_text(encoding="utf-8")
    assert '"pont-bi"' in (racine / "tests/installateur/faux_core.py").read_text(encoding="utf-8")
