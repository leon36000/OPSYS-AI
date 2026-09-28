"""Taxonomie métier partagée (PLAN T0.13) : catalogue, profil d'entreprise, fail-closed."""

from __future__ import annotations

import pytest
import yaml

from opsys import etat, stockage, taxonomie
from opsys.taxonomie import ProfilInvalide, Service


def test_le_catalogue_porte_les_quatre_services_reels_du_premier_client():
    assert taxonomie.codes_catalogue() == ("gouttieres", "revetement", "soffite_fascia", "reparation")
    libelles = {s.code: s.libelle for s in taxonomie.CATALOGUE_REFERENCE}
    assert libelles == {
        "gouttieres": "Gouttières et descentes",
        "revetement": "Revêtement extérieur",
        "soffite_fascia": "Soffite et fascia",
        "reparation": "Réparation",
    }


def test_chaque_service_du_catalogue_a_un_code_stable_et_des_mots_cles():
    for service in taxonomie.CATALOGUE_REFERENCE:
        assert taxonomie._FORME_CODE.match(service.code)
        assert service.mots_cles, service.code


def test_sans_profil_aucun_service_n_est_accepte_pas_meme_ceux_du_catalogue(opsys_home):
    assert not taxonomie.fichier_profil().exists()
    for code in ("gouttieres", "revetement", "n_importe_quoi"):
        service, verdict = taxonomie.valider_service(code)
        assert service is None
        assert verdict["code"] == taxonomie.VERDICT_SERVICE_NON_CONFIGURE
        # Le verdict dit quoi configurer et où.
        assert str(taxonomie.fichier_profil()) in verdict["detail"]
        assert "services" in verdict["detail"]
        assert "gouttieres" in verdict["detail"]


def test_charger_services_sans_profil_rend_un_verdict_et_aucun_service_par_defaut(opsys_home):
    services, verdict = taxonomie.charger_services()
    assert services == ()
    assert verdict["code"] == taxonomie.VERDICT_SERVICE_NON_CONFIGURE


def test_un_profil_declare_un_sous_ensemble_du_catalogue(opsys_home, declarer_services):
    declarer_services("gouttieres", "soffite_fascia")
    service, verdict = taxonomie.valider_service("gouttieres")
    assert verdict is None
    assert service.libelle == "Gouttières et descentes"
    # Un service du catalogue que l'entreprise n'a pas déclaré est refusé, avec la marche à suivre.
    service, verdict = taxonomie.valider_service("revetement")
    assert service is None
    assert verdict["code"] == taxonomie.VERDICT_SERVICE_INCONNU
    assert "gouttieres, soffite_fascia" in verdict["detail"]
    assert str(taxonomie.fichier_profil()) in verdict["detail"]


def test_une_autre_pme_declare_ses_propres_services_sans_heriter_du_catalogue(opsys_home, declarer_services):
    declarer_services({"code": "pose_pergola", "libelle": "Pose de pergolas", "mots_cles": ["pergola"]})
    service, verdict = taxonomie.valider_service("pose_pergola")
    assert verdict is None
    assert service == Service("pose_pergola", "Pose de pergolas", ("pergola",))
    for code in taxonomie.codes_catalogue():
        assert taxonomie.valider_service(code)[1]["code"] == taxonomie.VERDICT_SERVICE_INCONNU


@pytest.mark.parametrize("valeur", [None, "", "  ", 3, ["gouttieres"], {"code": "gouttieres"}])
def test_un_service_qui_n_est_pas_un_code_est_invalide(opsys_home, declarer_services, valeur):
    declarer_services()
    service, verdict = taxonomie.valider_service(valeur)
    assert service is None
    assert verdict["code"] == taxonomie.VERDICT_SERVICE_INVALIDE


def test_pas_de_repli_sur_autre(opsys_home, declarer_services):
    declarer_services()
    service, verdict = taxonomie.valider_service("autre")
    assert service is None
    assert verdict["code"] == taxonomie.VERDICT_SERVICE_INCONNU


def test_valider_service_accepte_une_declaration_fournie_par_l_appelant(opsys_home):
    service, verdict = taxonomie.valider_service("revetement", taxonomie.CATALOGUE_REFERENCE)
    assert verdict is None and service.code == "revetement"
    _, verdict = taxonomie.valider_service("revetement", ())
    assert verdict["code"] == taxonomie.VERDICT_SERVICE_NON_CONFIGURE


def test_un_profil_illisible_donne_un_verdict_jamais_un_profil_vide(opsys_home):
    fichier = taxonomie.fichier_profil()
    fichier.parent.mkdir(parents=True)
    fichier.write_text("services: [gouttieres, service_du_catalogue_inexistant]\n", encoding="utf-8")
    with pytest.raises(ProfilInvalide, match="catalogue de référence"):
        taxonomie.lire_services()
    service, verdict = taxonomie.valider_service("gouttieres")
    assert service is None
    assert verdict["code"] == taxonomie.VERDICT_PROFIL_INVALIDE
    assert "service_du_catalogue_inexistant" in verdict["detail"]


@pytest.mark.parametrize("contenu, motif", [
    ("services: []\n", "vide"),
    ("services: gouttieres\n", "liste"),
    ("services: [gouttieres, gouttieres]\n", "double"),
    ("services: [{code: reparation, libelle: Réparation}]\n", "catalogue"),
    ("services: [{code: Pose Pergola, libelle: X}]\n", "invalide"),
    ("services: [{code: pose_pergola}]\n", "libelle"),
    ("services: [{code: pose_pergola, libelle: X, prix: 5}]\n", "inconnues"),
    ("services: [{code: pose_pergola, libelle: X, mots_cles: [1]}]\n", "mot-clé"),
    ("- gouttieres\n", "objet YAML"),
    ("services: [gouttieres\n", "illisible"),
])
def test_un_profil_mal_forme_est_refuse_avec_la_raison(opsys_home, contenu, motif):
    fichier = taxonomie.fichier_profil()
    fichier.parent.mkdir(parents=True)
    fichier.write_text(contenu, encoding="utf-8")
    with pytest.raises(ProfilInvalide, match=motif):
        taxonomie.lire_services()
    assert taxonomie.verifier_profil() != []


def test_un_profil_sans_la_cle_services_ne_declare_rien(opsys_home):
    fichier = taxonomie.fichier_profil()
    fichier.parent.mkdir(parents=True)
    fichier.write_text("nom_commercial: Exemple fictif\n", encoding="utf-8")
    assert taxonomie.lire_services() == ()
    assert taxonomie.verifier_profil() == []
    assert taxonomie.valider_service("gouttieres")[1]["code"] == taxonomie.VERDICT_SERVICE_NON_CONFIGURE


def test_enregistrer_services_conserve_les_autres_cles_et_les_relit_a_l_identique(opsys_home):
    fichier = taxonomie.fichier_profil()
    fichier.parent.mkdir(parents=True)
    fichier.write_text("nom_commercial: Exemple fictif\n", encoding="utf-8")
    ecrit = taxonomie.enregistrer_services(
        ["revetement", {"code": "pose_pergola", "libelle": "Pose de pergolas", "mots_cles": ["pergola"]}]
    )
    assert ecrit == fichier
    contenu = yaml.safe_load(fichier.read_text(encoding="utf-8"))
    assert contenu["nom_commercial"] == "Exemple fictif"
    assert contenu["services"] == [
        "revetement", {"code": "pose_pergola", "libelle": "Pose de pergolas", "mots_cles": ["pergola"]},
    ]
    assert [s.code for s in taxonomie.lire_services()] == ["revetement", "pose_pergola"]


def test_enregistrer_services_valide_avant_d_ecrire(opsys_home):
    with pytest.raises(ProfilInvalide):
        taxonomie.enregistrer_services([])
    with pytest.raises(ProfilInvalide):
        taxonomie.enregistrer_services(["service_inexistant"])
    assert not taxonomie.fichier_profil().exists()


def test_enregistrer_services_signe_le_changement_au_journal(opsys_home):
    stockage.migrer()
    taxonomie.enregistrer_services(["gouttieres", "reparation"], par="nathan")
    with etat.session() as cnx:
        journal = etat.lire_journal(cnx)
    assert journal[0]["par"] == "nathan"
    assert journal[0]["action"] == "entreprise.services"
    assert journal[0]["details"] == {"services": ["gouttieres", "reparation"]}


def test_le_profil_de_l_instance_suit_opsys_home(tmp_path, monkeypatch):
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "a"))
    taxonomie.enregistrer_services(["gouttieres"])
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "b"))
    assert taxonomie.lire_services() == ()
    assert taxonomie.fichier_profil() == tmp_path / "b" / "entreprise.yaml"


def test_cli_services_declare_puis_liste_et_signe_au_journal(opsys_home, capsys):
    import json

    from opsys import cli

    stockage.migrer()
    assert cli.main(["services", "lister"]) == 0
    vide = json.loads(capsys.readouterr().out)
    assert vide["declares"] == [] and [c["code"] for c in vide["catalogue_de_reference"]] == list(
        taxonomie.codes_catalogue())
    assert vide["fichier"] == str(opsys_home / "entreprise.yaml")

    assert cli.main(["services", "declarer", "gouttieres", "revetement", "--par", "nathan"]) == 0
    capsys.readouterr()
    assert cli.main(["services", "lister"]) == 0
    assert [s["code"] for s in json.loads(capsys.readouterr().out)["declares"]] == ["gouttieres", "revetement"]
    with etat.session() as cnx:
        assert etat.lire_journal(cnx)[0]["action"] == "entreprise.services"


def test_cli_services_refuse_un_code_hors_catalogue_et_exige_par(opsys_home, capsys):
    from opsys import cli

    assert cli.main(["services", "declarer", "service_inexistant", "--par", "nathan"]) == 1
    assert "catalogue de référence" in capsys.readouterr().err
    assert not taxonomie.fichier_profil().exists()
    assert cli.main(["services", "declarer", "gouttieres"]) == 2
    assert cli.main(["services", "declarer", "--par", "nathan"]) == 2


def test_cli_services_lister_signale_un_profil_illisible(opsys_home, capsys):
    from opsys import cli

    fichier = taxonomie.fichier_profil()
    fichier.parent.mkdir(parents=True)
    fichier.write_text("services: [gouttieres, gouttieres]\n", encoding="utf-8")
    assert cli.main(["services", "lister"]) == 1
    assert "double" in capsys.readouterr().err


def test_enregistrer_services_refuse_d_ecraser_un_profil_illisible(opsys_home):
    fichier = taxonomie.fichier_profil()
    fichier.parent.mkdir(parents=True)
    fichier.write_text("nom_commercial: [non ferme\n", encoding="utf-8")
    with pytest.raises(ProfilInvalide, match="illisible"):
        taxonomie.enregistrer_services(["gouttieres"])
    assert fichier.read_text(encoding="utf-8") == "nom_commercial: [non ferme\n"
