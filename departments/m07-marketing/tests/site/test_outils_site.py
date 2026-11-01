"""Outils M7 des sites web : portées fermées, T0/T1 pour lire, générer et préparer, N3 pour demander la publication.

La publication publique n'est jamais exécutée : la demande d'un agent attend la file d'approbation du socle ; approuvée
par le propriétaire, elle rend le plan approuvé, `execute: False`.
"""

from __future__ import annotations

import copy
import shutil
from pathlib import Path

import pytest
from m7_marketing import outils
from m7_marketing.site import service

from opsys import approbations, contexte, identite, stockage
from opsys.departements import lire_manifeste
from opsys.outils import Autonomie, Niveau, executer_atomique

FICTIF = True
_M7 = Path(__file__).resolve().parents[2]
_OUTILS = {o.nom: o for o in outils.outils()}
VERSION = "20261031T150000Z"
CIBLE = {"hote": "vps.revetements-horizon.example"}
DEMO = "revetements-horizon-fictif"


@pytest.mark.parametrize(("nom", "autonomie", "niveau"), [
    ("m7_valider_schema_site", Autonomie.T0, Niveau.N0),
    ("m7_generer_site_statique", Autonomie.T0, Niveau.N0),
    ("m7_preparer_paquet_site", Autonomie.T1, Niveau.N1),
    ("m7_demander_publication_site", Autonomie.T1, Niveau.N3),
])
def test_patron_des_outils_portees_fermees_et_niveaux(nom, autonomie, niveau):
    outil = _OUTILS[nom]
    assert (outil.autonomie, outil.niveau_effectif) == (autonomie, niveau)
    assert outil.roles_appareil == frozenset()  # aucun appareil : fermé par défaut
    assert not outil.frontiere_humaine


def test_le_manifeste_charge_les_outils_du_site():
    noms = {o.nom for o in lire_manifeste(_M7).charger_outils()}
    assert {"m7_valider_schema_site", "m7_generer_site_statique", "m7_preparer_paquet_site",
            "m7_demander_publication_site"} <= noms


def test_valider_la_demo_fictive():
    assert outils.valider_schema_site(schema_demo=DEMO, concurrents=["fort", "faible"]) == {
        "accepte": True, "site_id": DEMO, "refus": [], "qa_conforme": True,
    }


def test_exactement_une_source_de_schema(schema):
    for appel in ({}, {"schema": schema, "schema_demo": DEMO}):
        resultat = outils.valider_schema_site(**appel)
        assert [r["code"] for r in resultat["refus"]] == [service.REJ_SCHEMA_SOURCE]
    assert outils.valider_schema_site(schema_demo="autre")["refus"][0]["code"] == service.REJ_SCHEMA_SOURCE


def test_un_schema_fourni_lit_ses_images_dans_opsys_home(schema, tmp_path, monkeypatch):
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path))
    resultat = outils.valider_schema_site(schema=schema)
    assert {r["code"] for r in resultat["refus"]} == {"REJ-SITE-IMAGE-ABSENTE"}
    shutil.copytree(service.DOSSIER_DEMOS / DEMO / "actifs", tmp_path / "sites" / DEMO / "actifs")
    assert outils.valider_schema_site(schema=schema)["accepte"] is True


def test_un_refus_de_contenu_remonte_par_l_outil(schema, tmp_path, monkeypatch):
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path))
    shutil.copytree(service.DOSSIER_DEMOS / DEMO / "actifs", tmp_path / "sites" / DEMO / "actifs")
    schema["faq"][0]["reponse"]["fr-CA"] = "Soumission gratuite, le meilleur prix de Laval."
    codes = [r["code"] for r in outils.valider_schema_site(schema=schema)["refus"]]
    assert codes == ["REJ-SITE-PROMESSE-NON-SOURCEE", "REJ-SITE-EXAGERATION"]


def test_generer_le_site_en_memoire_avec_son_rapport(tmp_path, monkeypatch):
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path))
    resultat = outils.generer_site_statique(schema_demo=DEMO, fichier="en/faq/index.html")
    assert resultat["accepte"] and resultat["qa"]["conforme"]
    assert len(resultat["fichiers"]) == 25
    assert resultat["contenu"].startswith('<!DOCTYPE html>\n<html lang="en-CA">')
    assert "CONFORME" in resultat["rapport"]
    assert not any(tmp_path.iterdir())  # rien d'écrit
    assert outils.generer_site_statique(schema_demo=DEMO, fichier="../x")["contenu"] is None


def test_preparer_le_paquet_ecrit_l_artefact_sans_rien_executer(tmp_path, monkeypatch):
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path))
    resultat = outils.preparer_paquet_site(version=VERSION, cible=CIBLE, schema_demo=DEMO)
    assert resultat["accepte"] and resultat["deja_prepare"] is False
    assert Path(resultat["dossier"]) == tmp_path / "sites" / DEMO / "paquets" / VERSION
    assert resultat["plan"]["statut"] == "PLAN_NON_EXECUTE" and "caddyfile" not in resultat["plan"]
    assert (Path(resultat["dossier"]) / "Caddyfile").is_file()
    rejeu = outils.preparer_paquet_site(version=VERSION, cible=CIBLE, schema_demo=DEMO)
    assert rejeu["deja_prepare"] is True and rejeu["archive"] == resultat["archive"]
    refus = outils.preparer_paquet_site(version=VERSION, cible={**CIBLE, "utilisateur": "root"}, schema_demo=DEMO)
    assert [r["code"] for r in refus["refus"]] == ["REJ-DEPLOI-UTILISATEUR-ROOT"]


# ---------------------------------------------------------------------------
# Demande de publication (N3) : jamais exécutée
# ---------------------------------------------------------------------------
@pytest.fixture
def base(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys-home"))
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Propriétaire fictif", "mot-de-passe-test-1234", ["nathan_owner"])
        identite.creer_personne(cnx, "gestion", "Gestionnaire fictif", "mot-de-passe-test-1234", ["admin"])
    shutil.copytree(service.DOSSIER_DEMOS / DEMO / "actifs", tmp_path / "opsys-home" / "sites" / DEMO / "actifs")
    yield
    stockage.liberer()


@pytest.fixture
def schema_publiable(schema):
    """Copie EN MÉMOIRE du site de démonstration marquée publiable, pour exercer la file d'approbation. Le domaine
    reste réservé (.example) et rien n'est jamais déployé."""
    publiable = copy.deepcopy(schema)
    publiable["fictif"] = False
    return publiable


def _empreinte(schema_publiable):
    prepare = service.preparer_paquet(schema_publiable, service.resoudre_schema(None, DEMO)[1], VERSION, CIBLE)
    return prepare["manifeste"]["archive"]["sha256"]


def test_un_site_fictif_n_est_jamais_publie(base):
    resultat = outils.demander_publication_site(VERSION, "0" * 64, CIBLE, schema_demo=DEMO)
    assert [r["code"] for r in resultat["refus"]] == [service.REJ_PUBLICATION_FICTIF]


def test_un_agent_seul_ne_peut_pas_publier(base, schema_publiable):
    reponse = executer_atomique(_OUTILS["m7_demander_publication_site"], {
        "version": VERSION, "empreinte_archive": _empreinte(schema_publiable), "cible": CIBLE,
        "schema": schema_publiable,
    })
    refus = reponse["resultat"]["refus"]
    assert [r["code"] for r in refus] == ["REJ-HUMAIN-REQUIS"]
    assert "décision de la direction (N3+)" in refus[0]["detail"]


def test_un_appareil_admin_qui_n_est_pas_le_proprietaire_est_refuse(base, schema_publiable):
    with contexte.appele_par_appareil(contexte.IdentiteAppelante("gestion", "admin")), stockage.transaction():
        resultat = outils.demander_publication_site(
            VERSION, _empreinte(schema_publiable), CIBLE, schema=schema_publiable,
        )
    assert [r["code"] for r in resultat["refus"]] == ["REJ-HUMAIN-ROLE-INSUFFISANT"]


def _demande(schema_publiable, empreinte):
    arguments = {"version": VERSION, "empreinte_archive": empreinte, "cible": CIBLE, "schema": schema_publiable}
    with stockage.transaction() as cnx:
        return approbations.creer_demande(
            cnx, "m07-marketing", "m7_demander_publication_site", arguments, niveau=Niveau.N3,
        )


def test_approuvee_par_le_proprietaire_dans_la_file_le_plan_est_rendu_jamais_execute(base, schema_publiable):
    demande = _demande(schema_publiable, _empreinte(schema_publiable))
    with stockage.transaction() as cnx:
        sortie = approbations.decider(cnx, demande, True, "nathan", _OUTILS, {"m07-marketing": lire_manifeste(_M7)})
    assert sortie["statut"] == "executee"
    resultat = sortie["reponse"]["resultat"]
    assert resultat["statut"] == "PUBLICATION_APPROUVEE_NON_EXECUTEE" and resultat["execute"] is False
    assert resultat["approbation"] == {"par": "nathan", "role": "nathan_owner", "source": "approbation"}
    assert resultat["plan"]["statut"] == "PLAN_NON_EXECUTE"
    assert "aucune connexion SSH" in resultat["execution"]


def test_la_file_refuse_un_approbateur_hors_politique_n3(base, schema_publiable):
    demande = _demande(schema_publiable, _empreinte(schema_publiable))
    with pytest.raises(ValueError), stockage.transaction() as cnx:
        approbations.decider(cnx, demande, True, "gestion", _OUTILS, {"m07-marketing": lire_manifeste(_M7)})


def test_approuvee_mais_empreinte_differente_refusee(base, schema_publiable):
    demande = _demande(schema_publiable, "f" * 64)
    with stockage.transaction() as cnx:
        sortie = approbations.decider(cnx, demande, True, "nathan", _OUTILS, {"m07-marketing": lire_manifeste(_M7)})
    refus = sortie["reponse"]["resultat"]["refus"]
    assert [r["code"] for r in refus] == [service.REJ_PUBLICATION_EMPREINTE]
