"""Capacités MCP de la mémoire d'entreprise : opsys_memoire_rechercher (T0), _ajouter (T1), _oublier (T3).

Elles passent par `opsys.outils.executer`, comme dans `Capacites`. Le PostgreSQL + pgvector est réel
(conteneur éphémère). L'endpoint d'embeddings est un double local, car c'est un service externe.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from memoire.doubles import DOSSIER, port_ferme, postgres_ephemere, raison_sans_docker, serveur_embeddings, vider

from opsys.memoire import MemoireEntreprise
from opsys.memoire import outils as module_outils
from opsys.outils import Autonomie, executer

RAISON_SANS_DOCKER = raison_sans_docker()
avec_docker = pytest.mark.skipif(RAISON_SANS_DOCKER is not None, reason=str(RAISON_SANS_DOCKER))
DEPARTEMENTS = DOSSIER / "departements"
RACINE = Path(__file__).resolve().parents[1]


def _outil(nom):
    return {o.nom: o for o in module_outils.outils()}[nom]


def _appel(nom, **arguments):
    return executer(_outil(nom), arguments)


def _dans(jours):
    return (dt.date.today() + dt.timedelta(days=jours)).isoformat()


@pytest.fixture
def environnement(monkeypatch):
    for variable in ("OPSYS_DATABASE_URL", "OPSYS_DEPARTEMENT", "OPSYS_EMBEDDINGS_URL", "OPSYS_EMBEDDINGS_MODELE",
                     "OPSYS_EMBEDDINGS_CLE", "OPSYS_EMBEDDINGS_LOCAL"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("OPSYS_DEPARTMENTS", str(DEPARTEMENTS))
    return monkeypatch


@pytest.fixture(scope="module")
def url_pg():
    if RAISON_SANS_DOCKER is not None:
        pytest.skip(RAISON_SANS_DOCKER)
    with postgres_ephemere() as url:
        MemoireEntreprise(url).migrer()
        yield url


@pytest.fixture
def base(url_pg, environnement):
    vider(url_pg)
    environnement.setenv("OPSYS_DATABASE_URL", url_pg)
    environnement.setenv("OPSYS_DEPARTEMENT", "m03-memoire-demo")
    return environnement


@pytest.fixture
def embeddings(base):
    with serveur_embeddings() as serveur:
        base.setenv("OPSYS_EMBEDDINGS_URL", serveur.url)
        base.setenv("OPSYS_EMBEDDINGS_MODELE", "BAAI/bge-m3")
        base.setenv("OPSYS_EMBEDDINGS_LOCAL", "1")
        yield serveur


# -- catalogue -----------------------------------------------------------------------------------------
def test_catalogue_trois_outils_avec_autonomie_et_schemas_stricts():
    catalogue = {o.nom: o for o in module_outils.outils()}
    assert {nom: o.autonomie for nom, o in catalogue.items()} == {
        "opsys_memoire_rechercher": Autonomie.T0,
        "opsys_memoire_ajouter": Autonomie.T1,
        "opsys_memoire_oublier": Autonomie.T3,
    }
    for outil in catalogue.values():
        assert outil.parametres["additionalProperties"] is False
        assert len(outil.description) <= 300  # payée à chaque tour
    assert catalogue["opsys_memoire_ajouter"].parametres["properties"]["sensibilite"]["enum"] == [
        "publique", "interne", "confidentielle", "personnelle"]


# -- refus explicites sans configuration (pas besoin de docker) -----------------------------------------
def test_sans_url_de_base_refus_explicite(environnement):
    environnement.setenv("OPSYS_DEPARTEMENT", "m03-memoire-demo")
    reponse = _appel("opsys_memoire_rechercher", requete="toiture")
    assert reponse["ok"] is False and reponse["erreur"] == "refus_metier"
    assert "OPSYS_DATABASE_URL" in reponse["details"]


def test_sans_departement_appelant_refus_explicite(environnement):
    environnement.setenv("OPSYS_DATABASE_URL", "postgresql://postgres:x@127.0.0.1:1/postgres")
    reponse = _appel("opsys_memoire_rechercher", requete="toiture")
    assert reponse["ok"] is False and "OPSYS_DEPARTEMENT" in reponse["details"]
    environnement.setenv("OPSYS_DEPARTEMENT", "m07-inexistant")
    assert "manifeste" in _appel("opsys_memoire_rechercher", requete="toiture")["details"]


def test_base_injoignable_refus_explicite(environnement):
    environnement.setenv("OPSYS_DEPARTEMENT", "m03-memoire-demo")
    environnement.setenv("OPSYS_DATABASE_URL", f"postgresql://postgres:secret-pg@127.0.0.1:{port_ferme()}/postgres")
    reponse = _appel("opsys_memoire_rechercher", requete="toiture")
    assert reponse["ok"] is False and "PostgreSQL injoignable" in reponse["details"]
    assert "secret-pg" not in reponse["details"]


# -- parcours réels -------------------------------------------------------------------------------------
@avec_docker
def test_ajouter_puis_rechercher_en_mode_hybride(embeddings):
    ajout = _appel("opsys_memoire_ajouter", texte="Estimation E-2026-031 : six fenêtres coulissantes.",
                   source="fictif:estimation/E-2026-031", portee="estimations", sensibilite="interne",
                   titre="Estimation E-2026-031")
    assert ajout["ok"] is True, ajout
    assert ajout["resultat"]["vectorise"] is True and ajout["resultat"]["departement"] == "m03-memoire-demo"
    reponse = _appel("opsys_memoire_rechercher", requete="fenetre coulisante", k=3)
    assert reponse["ok"] is True, reponse
    resultat = reponse["resultat"]
    assert resultat["mode"] == "hybride" and "avertissement" not in resultat
    (premier,) = resultat["resultats"]
    assert premier["source"] == "fictif:estimation/E-2026-031" and premier["titre"] == "Estimation E-2026-031"
    assert premier["portee"] == "estimations"
    assert [r["corps"]["input"] for r in embeddings.requetes] == [
        ["Estimation E-2026-031 : six fenêtres coulissantes."], ["fenetre coulisante"]]


@avec_docker
def test_portees_bornees_par_le_manifeste_du_departement_appelant(base, embeddings):
    hors_ecriture = _appel("opsys_memoire_ajouter", texte="x", source="s", portee="clients", sensibilite="interne")
    assert hors_ecriture["ok"] is False and "écriture" in hors_ecriture["details"]
    hors_lecture = _appel("opsys_memoire_rechercher", requete="toiture", portees=["procedures"])
    assert hors_lecture["ok"] is False and "procedures" in hors_lecture["details"]
    # M2 (démo) écrit dans « clients » ; M3 (démo) lit « clients » mais pas l'inverse pour « estimations »
    base.setenv("OPSYS_DEPARTEMENT", "m02-memoire-demo")
    assert _appel("opsys_memoire_ajouter", texte="Client C-0042 joignable par texto.", source="fictif:crm/C-0042",
                  portee="clients", sensibilite="interne", sujets=["client:C-0042"])["ok"] is True
    base.setenv("OPSYS_DEPARTEMENT", "m03-memoire-demo")
    assert _appel("opsys_memoire_ajouter", texte="Estimation pour C-0042.", source="fictif:estimation/E-9",
                  portee="estimations", sensibilite="interne", sujets=["client:C-0042"])["ok"] is True
    vu_par_m3 = _appel("opsys_memoire_rechercher", requete="C-0042", sujet="client:C-0042")["resultat"]
    assert sorted(r["portee"] for r in vu_par_m3["resultats"]) == ["clients", "estimations"]
    base.setenv("OPSYS_DEPARTEMENT", "m02-memoire-demo")
    vu_par_m2 = _appel("opsys_memoire_rechercher", requete="C-0042")["resultat"]
    assert [r["portee"] for r in vu_par_m2["resultats"]] == ["clients"]


@avec_docker
def test_departement_appelant_fixe_par_le_serveur_prime_sur_l_environnement(embeddings):
    with module_outils.appeler_en_tant_que("m02-memoire-demo"):
        reponse = _appel("opsys_memoire_ajouter", texte="Client C-0001 : accès par la ruelle.",
                         source="fictif:crm/C-0001", portee="clients", sensibilite="interne")
    assert reponse["ok"] is True and reponse["resultat"]["departement"] == "m02-memoire-demo"
    assert module_outils.DEPARTEMENT_APPELANT.get() is None


@avec_docker
def test_mode_plein_texte_explicite_sans_embeddings_ou_en_panne(base):
    assert _appel("opsys_memoire_ajouter", texte="Estimation : toiture en bardeaux.", source="fictif:e1",
                  portee="estimations", sensibilite="interne")["resultat"]["vectorise"] is False
    sans = _appel("opsys_memoire_rechercher", requete="toiture bardeaux")["resultat"]
    assert sans["mode"] == "plein_texte" and "OPSYS_EMBEDDINGS_URL" in sans["avertissement"]
    assert len(sans["resultats"]) == 1
    base.setenv("OPSYS_EMBEDDINGS_URL", f"http://127.0.0.1:{port_ferme()}/v1")
    base.setenv("OPSYS_EMBEDDINGS_MODELE", "BAAI/bge-m3")
    panne = _appel("opsys_memoire_rechercher", requete="toiture bardeaux")["resultat"]
    assert panne["mode"] == "plein_texte" and "indisponibles" in panne["avertissement"]
    assert len(panne["resultats"]) == 1


@avec_docker
def test_donnee_personnelle_jamais_envoyee_a_un_endpoint_hors_vps(base, embeddings):
    base.delenv("OPSYS_EMBEDDINGS_LOCAL")
    personnel = _appel("opsys_memoire_ajouter", texte="Estimation pour Mme Tremblay, 514-555-0199.",
                       source="fictif:estimation/E-10", portee="estimations", sensibilite="personnelle",
                       sujets=["client:C-0042"], expire_le=_dans(365))
    assert personnel["ok"] is True
    assert personnel["resultat"]["vectorise"] is False and "hors VPS" in personnel["resultat"]["note"]
    assert embeddings.requetes == []
    incomplet = _appel("opsys_memoire_ajouter", texte="Téléphone de C-0043.", source="fictif:e11",
                       portee="estimations", sensibilite="personnelle", sujets=["client:C-0043"])
    assert incomplet["ok"] is False and "expire_le" in incomplet["details"]
    assert embeddings.requetes == []  # validation avant tout appel au service d'embeddings
    # appel direct (sans la validation de schéma d'executer) : la sensibilité normalisée fait foi
    direct = module_outils.ajouter(texte="Adresse de C-0044.", source="fictif:e12", portee="estimations",
                                   sensibilite=" personnelle ", sujets=["client:C-0044"], expire_le=_dans(30))
    assert direct["vectorise"] is False
    assert embeddings.requetes == []


@avec_docker
def test_texte_trop_long_refuse_avant_tout_appel_d_embeddings(embeddings):
    reponse = _appel("opsys_memoire_ajouter", texte="x" * 20_001, source="fictif:long", portee="estimations",
                     sensibilite="interne")
    assert reponse["ok"] is False and "découper" in reponse["details"]
    assert embeddings.requetes == []


@avec_docker
def test_oublier_par_sujet_puis_plus_rien(embeddings):
    for numero in (1, 2):
        assert _appel("opsys_memoire_ajouter", texte=f"Estimation {numero} pour C-0042 : toiture.",
                      source=f"fictif:estimation/E-{numero}", portee="estimations", sensibilite="personnelle",
                      sujets=["client:C-0042"], expire_le=_dans(365))["ok"] is True
    oubli = _appel("opsys_memoire_oublier", sujet="client:C-0042", demandeur="client C-0042 (courriel)",
                   motif="demande de suppression, LPRPSP art. 28")
    assert oubli == {"ok": True, "resultat": {"fragments_effaces": 2, "filtres": {"sujet": "client:C-0042"}}}
    assert _appel("opsys_memoire_rechercher", requete="toiture", sujet="client:C-0042")["resultat"]["resultats"] == []
    sans_selecteur = _appel("opsys_memoire_oublier", demandeur="patron", motif="ménage")
    assert sans_selecteur["ok"] is False and "sujet, source ou document_id" in sans_selecteur["details"]


@avec_docker
def test_sortie_de_recherche_tient_dans_le_budget_de_tokens(embeddings):
    for numero in range(12):
        texte = f"Estimation {numero} : toiture en bardeaux, " + "détail du métré et des matériaux. " * 60
        assert _appel("opsys_memoire_ajouter", texte=texte, source=f"fictif:long/{numero}", portee="estimations",
                      sensibilite="interne")["ok"] is True
    resultat = _appel("opsys_memoire_rechercher", requete="toiture bardeaux", k=10)["resultat"]
    textes = [r["texte"] for r in resultat["resultats"]]
    assert all(len(t) <= module_outils.EXTRAIT_MAX for t in textes)
    assert sum(len(t) for t in textes) <= module_outils.TEXTE_SORTIE_MAX
    assert resultat["omis_budget"] == 10 - len(textes) > 0
    assert len(json.dumps(resultat, ensure_ascii=False)) < 6000  # sous la troncature de Capacites


# -- exploitation ---------------------------------------------------------------------------------------
def _cli(*arguments, env):
    return subprocess.run([sys.executable, "-m", "opsys.memoire", *arguments], capture_output=True, text=True,
                          env=env, cwd=RACINE, timeout=120, check=False)


def test_cli_sans_url_refuse_avec_code_2():
    env = {k: v for k, v in os.environ.items() if k != "OPSYS_DATABASE_URL"}
    sortie = _cli("etat", env=env)
    assert sortie.returncode == 2 and "OPSYS_DATABASE_URL" in sortie.stderr


@avec_docker
def test_cli_migrer_etat_purger(url_pg):
    vider(url_pg)
    env = {**os.environ, "OPSYS_DATABASE_URL": url_pg}
    migration = _cli("migrer", env=env)
    assert migration.returncode == 0, migration.stderr
    assert json.loads(migration.stdout)["migre"] is True
    assert json.loads(_cli("etat", env=env).stdout)["fragments"] == 0
    assert json.loads(_cli("purger", env=env).stdout) == {"purges": 0}
