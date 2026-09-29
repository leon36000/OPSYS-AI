"""`opsys-metier equipes lister|declarer` (PLAN T4.12) : le profil des équipes se déclare depuis un fichier, sous un
nom, avec des membres qui sont des personnes OPSYS existantes. Fixture FICTIVE (`fictif: true`)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from opsys import cli, equipes, etat, identite, taxonomie

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "equipes_fictives.json").read_text(encoding="utf-8"))
MOT_DE_PASSE = "mot-de-passe-fictif-1234"


@pytest.fixture
def instance(session):
    """Base migrée, avec les trois personnes fictives du profil."""
    with session() as cnx:
        for identifiant in ("alice.fictif", "bruno.fictif", "chloe.fictif"):
            identite.creer_personne(cnx, identifiant, identifiant.title(), MOT_DE_PASSE, ["employee"])


def _fichier(tmp_path, profil=None, nom="equipes.yaml") -> str:
    assert FIXTURE["fictif"] is True
    chemin = tmp_path / nom
    chemin.write_text(yaml.safe_dump(FIXTURE["profil"] if profil is None else profil, allow_unicode=True),
                      encoding="utf-8")
    return str(chemin)


def _journal():
    with etat.session() as cnx:
        return etat.lire_journal(cnx)


def test_lister_sans_profil_dit_qu_aucun_n_est_declare_et_quoi_declarer(instance, capsys):
    assert cli.main(["equipes", "lister"]) == 0
    sortie = json.loads(capsys.readouterr().out)
    assert sortie["declare"] is False and sortie["profil"] is None
    assert sortie["fichier"] == str(taxonomie.fichier_profil())
    assert len(sortie["a_declarer"]) == 1 and "opsys-metier equipes declarer" in sortie["a_declarer"][0]


def test_declarer_ecrit_le_profil_signe_au_journal_et_lister_le_montre(instance, tmp_path, capsys, declarer_services):
    declarer_services("gouttieres", "revetement")
    assert cli.main(["equipes", "declarer", "--depuis", _fichier(tmp_path), "--par", "nathan"]) == 0
    assert capsys.readouterr().out.strip() == str(taxonomie.fichier_profil())
    assert equipes.lire_equipes() == FIXTURE["profil"]
    (entree, *_) = _journal()
    assert entree["par"] == "nathan" and entree["action"] == "entreprise.equipes"
    assert entree["details"]["equipes"] == ["equipe-nord", "equipe-sud"]

    assert cli.main(["equipes", "lister"]) == 0
    sortie = json.loads(capsys.readouterr().out)
    assert sortie["declare"] is True and sortie["profil"] == FIXTURE["profil"]
    # 'reparation' a une durée dans le profil, mais n'est pas un service déclaré : ce n'est pas un manque à céduler
    assert sortie["a_declarer"] == []


def test_lister_dit_ce_qui_manque_a_un_profil_partiel(instance, tmp_path, capsys, declarer_services):
    declarer_services("gouttieres", "revetement")
    partiel = {"liste": FIXTURE["profil"]["liste"]}
    assert cli.main(["equipes", "declarer", "--depuis", _fichier(tmp_path, partiel), "--par", "nathan"]) == 0
    capsys.readouterr()
    assert cli.main(["equipes", "lister"]) == 0
    manques = json.loads(capsys.readouterr().out)["a_declarer"]
    assert any("par service" in m for m in manques) and any("cédule" in m for m in manques)


def test_declarer_exige_un_fichier_et_un_nom(instance, tmp_path, capsys):
    assert cli.main(["equipes", "declarer", "--par", "nathan"]) == 2
    assert cli.main(["equipes", "declarer", "--depuis", _fichier(tmp_path)]) == 2
    assert "--depuis" in capsys.readouterr().err
    assert equipes.lire_equipes() is None and _journal() == []


def test_un_membre_qui_n_est_pas_une_personne_opsys_est_refuse_sans_ecriture(instance, tmp_path, capsys):
    profil = json.loads(json.dumps(FIXTURE["profil"]))
    profil["liste"][1]["membres"] = ["chloe.fictif", "fantome.fictif"]
    assert cli.main(["equipes", "declarer", "--depuis", _fichier(tmp_path, profil), "--par", "nathan"]) == 1
    assert "personne inconnue 'fantome.fictif'" in capsys.readouterr().err
    assert not taxonomie.fichier_profil().exists() and _journal() == []


def test_un_membre_desactive_est_refuse_sans_ecriture(instance, tmp_path, capsys, session):
    with session() as cnx:
        identite.activer(cnx, "chloe.fictif", False)
    assert cli.main(["equipes", "declarer", "--depuis", _fichier(tmp_path), "--par", "nathan"]) == 1
    assert "désactivée" in capsys.readouterr().err
    assert not taxonomie.fichier_profil().exists()


def test_une_cle_de_donnee_rh_est_refusee_sans_ecriture(instance, tmp_path, capsys):
    profil = json.loads(json.dumps(FIXTURE["profil"]))
    profil["liste"][0]["salaire"] = 1
    assert cli.main(["equipes", "declarer", "--depuis", _fichier(tmp_path, profil), "--par", "nathan"]) == 1
    assert "clés inconnues" in capsys.readouterr().err
    assert not taxonomie.fichier_profil().exists() and _journal() == []


def test_un_fichier_absent_ou_illisible_est_refuse(instance, tmp_path, capsys):
    assert cli.main(["equipes", "declarer", "--depuis", str(tmp_path / "absent.yaml"), "--par", "nathan"]) == 1
    illisible = tmp_path / "casse.yaml"
    illisible.write_text("liste: [\n", encoding="utf-8")
    assert cli.main(["equipes", "declarer", "--depuis", str(illisible), "--par", "nathan"]) == 1
    assert "illisible" in capsys.readouterr().err
    vide = tmp_path / "vide.yaml"
    vide.write_text("", encoding="utf-8")
    assert cli.main(["equipes", "declarer", "--depuis", str(vide), "--par", "nathan"]) == 1
    assert not taxonomie.fichier_profil().exists()


def test_declarer_accepte_du_json_et_remplace_le_profil(instance, tmp_path):
    (tmp_path / "equipes.json").write_text(json.dumps(FIXTURE["profil"]), encoding="utf-8")
    assert cli.main(["equipes", "declarer", "--depuis", str(tmp_path / "equipes.json"), "--par", "nathan"]) == 0
    seule = {"fenetre_par_defaut": {"jours": [3], "debut_min": 0, "fin_min": 60}}
    assert cli.main(["equipes", "declarer", "--depuis", _fichier(tmp_path, seule), "--par", "nathan"]) == 0
    assert equipes.lire_equipes() == seule


def test_sans_base_migree_le_refus_dit_de_migrer(opsys_home, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("OPSYS_BASE_URL", f"sqlite:///{tmp_path / 'absente' / 'opsys.db'}")
    assert cli.main(["equipes", "declarer", "--depuis", _fichier(tmp_path), "--par", "nathan"]) == 1
    assert "opsys-metier base migrer" in capsys.readouterr().err
    assert not taxonomie.fichier_profil().exists()


def test_lister_refuse_un_profil_invalide_au_lieu_de_le_montrer_comme_absent(opsys_home, capsys):
    taxonomie.fichier_profil().parent.mkdir(parents=True)
    taxonomie.fichier_profil().write_text("equipes:\n  salaire: 1\n", encoding="utf-8")
    assert cli.main(["equipes", "lister"]) == 1
    assert "clés inconnues" in capsys.readouterr().err


def test_opsys_verifier_refuse_un_profil_d_equipes_invalide_une_seule_fois(opsys_home, capsys):
    taxonomie.fichier_profil().parent.mkdir(parents=True)
    taxonomie.fichier_profil().write_text("equipes: {liste: [\n", encoding="utf-8")
    assert cli.main(["verifier"]) == 1
    erreurs = [ligne for ligne in capsys.readouterr().err.splitlines() if "illisible" in ligne]
    assert len(erreurs) == 1


def test_opsys_verifier_refuse_une_duree_pour_un_service_non_declare(opsys_home, capsys, declarer_services):
    declarer_services("gouttieres")
    equipes.enregistrer_equipes({"services": {"revetement": {"duree_min": 60, "competences": []}}})
    assert cli.main(["verifier"]) == 1
    assert "'revetement', que l'entreprise ne déclare pas" in capsys.readouterr().err
    declarer_services("gouttieres", "revetement")
    assert cli.main(["verifier"]) == 0
