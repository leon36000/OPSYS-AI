"""`opsys meteo lister|declarer` (PLAN T4.13) : le profil météo se déclare depuis un fichier, sous un nom, sans jamais
ouvrir un fournisseur payant par défaut. Fixture FICTIVE (`fictif: true`)."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from opsys import cli, etat, meteo, taxonomie

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "meteo_fictive.json").read_text(encoding="utf-8"))


def _fichier(tmp_path, profil=None, nom="meteo.yaml") -> str:
    assert FIXTURE["fictif"] is True
    chemin = tmp_path / nom
    chemin.write_text(
        yaml.safe_dump(FIXTURE["profil"] if profil is None else profil, allow_unicode=True), encoding="utf-8"
    )
    return str(chemin)


def _journal():
    with etat.session() as cnx:
        return etat.lire_journal(cnx)


def test_lister_sans_profil_dit_qu_aucun_n_est_declare_et_quoi_declarer(session, capsys):
    assert cli.main(["meteo", "lister"]) == 0
    sortie = json.loads(capsys.readouterr().out)
    assert sortie["declare"] is False and sortie["profil"] is None
    assert sortie["fichier"] == str(taxonomie.fichier_profil())
    assert len(sortie["a_declarer"]) == 1 and "opsys meteo declarer" in sortie["a_declarer"][0]


def test_declarer_ecrit_le_profil_signe_au_journal_et_lister_le_montre(session, tmp_path, capsys, declarer_services):
    declarer_services("gouttieres", "revetement")
    assert cli.main(["meteo", "declarer", "--depuis", _fichier(tmp_path), "--par", "nathan"]) == 0
    assert capsys.readouterr().out.strip() == str(taxonomie.fichier_profil())
    assert meteo.lire_meteo() == FIXTURE["profil"]
    (entree, *_) = _journal()
    assert entree["par"] == "nathan" and entree["action"] == "entreprise.meteo"
    assert entree["details"]["services"] == ["gouttieres", "revetement"]

    assert cli.main(["meteo", "lister"]) == 0
    sortie = json.loads(capsys.readouterr().out)
    assert sortie["declare"] is True and sortie["profil"] == FIXTURE["profil"]
    assert sortie["a_declarer"] == []


def test_lister_dit_les_risques_sans_decision_d_un_profil_partiel(session, tmp_path, capsys, declarer_services):
    declarer_services("gouttieres", "revetement")
    partiel = {"services": {"gouttieres": {"seuils": {"vent_kmh": {"blocage": 40}}}}}
    assert cli.main(["meteo", "declarer", "--depuis", _fichier(tmp_path, partiel), "--par", "nathan"]) == 0
    capsys.readouterr()
    assert cli.main(["meteo", "lister"]) == 0
    manques = json.loads(capsys.readouterr().out)["a_declarer"]
    assert any("'gouttieres'" in m and "seuil à configurer" in m for m in manques)
    assert any("'revetement'" in m for m in manques)


def test_declarer_exige_un_fichier_et_un_nom(session, tmp_path, capsys):
    assert cli.main(["meteo", "declarer", "--par", "nathan"]) == 2
    assert cli.main(["meteo", "declarer", "--depuis", _fichier(tmp_path)]) == 2
    assert "--depuis" in capsys.readouterr().err
    assert meteo.lire_meteo() is None and _journal() == []


def test_un_profil_invalide_est_refuse_sans_ecriture_ni_journal(session, tmp_path, capsys):
    invalide = {"services": {"gouttieres": {"seuils": {"vent_kmh": {"validation": 50, "blocage": 40}}}}}
    assert cli.main(["meteo", "declarer", "--depuis", _fichier(tmp_path, invalide), "--par", "nathan"]) == 1
    assert "au plus égale au blocage" in capsys.readouterr().err
    assert meteo.lire_meteo() is None and _journal() == []


def test_le_forfait_gratuit_d_open_meteo_est_refuse_par_la_commande(session, tmp_path, capsys):
    gratuit = {
        "fuseau": "America/Toronto",
        "fournisseur": "open_meteo",
        "open_meteo": {"forfait": "gratuit", "cle_env": "OPSYS_CLE_FICTIVE"},
    }
    assert cli.main(["meteo", "declarer", "--depuis", _fichier(tmp_path, gratuit), "--par", "nathan"]) == 1
    erreur = capsys.readouterr().err
    assert "non commercial" in erreur and "décision du propriétaire" in erreur
    assert meteo.lire_meteo() is None and _journal() == []


def test_un_fichier_absent_ou_illisible_est_une_erreur_nette(session, tmp_path, capsys):
    assert cli.main(["meteo", "declarer", "--depuis", str(tmp_path / "absent.yaml"), "--par", "nathan"]) == 1
    (tmp_path / "casse.yaml").write_text("meteo: [\n", encoding="utf-8")
    assert cli.main(["meteo", "declarer", "--depuis", str(tmp_path / "casse.yaml"), "--par", "nathan"]) == 1
    assert capsys.readouterr().err.count("ERREUR") == 2
    assert meteo.lire_meteo() is None


def test_lister_refuse_un_profil_invalide_avec_son_message(session, capsys):
    fichier = taxonomie.fichier_profil()
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fichier.write_text("meteo:\n  fuseau: 12\n", encoding="utf-8")
    assert cli.main(["meteo", "lister"]) == 1
    assert "base des fuseaux" in capsys.readouterr().err


def test_opsys_verifier_signale_un_profil_meteo_invalide(session, capsys):
    fichier = taxonomie.fichier_profil()
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fichier.write_text("meteo:\n  fuseau: 12\n", encoding="utf-8")
    assert cli.main(["verifier"]) == 1
    assert "base des fuseaux" in capsys.readouterr().err
