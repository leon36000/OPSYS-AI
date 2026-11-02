"""Ingestion de la mémoire de projet (M10-03) sur un dépôt Git FICTIF : directives, ADR, règles d'agent, condensés,
matrices. Idempotente, sourcée (chemin, empreinte, date), expurgée (aucun secret ni renseignement personnel rangé),
jamais de suppression (versions, archives, retraits), consultable par le preflight de développement existant, et
branchée à la détection de contradictions. Base SQLite migrée ; aucun réseau."""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from m10_memoire import contradictions as c
from m10_memoire import contradictions_outils as co
from m10_memoire import developpement as dev
from m10_memoire import ingestion_projet as ing
from m10_memoire import verite

from opsys import contexte, identite, stockage
from opsys.memoire_developpement_cli import main as cli_main

FICTIF = True
ADMIN = contexte.IdentiteAppelante("admin.dev", "admin")
EMPLOYE = contexte.IdentiteAppelante("estimation.dev", "employee")
H1, H2, H3 = "2026-11-02T10:00:00+00:00", "2026-11-03T10:00:00+00:00", "2026-11-04T10:00:00+00:00"
# Valeurs FACTICES construites à l'exécution : aucune valeur ressemblant à un secret réel dans le dépôt.
SECRET = "jeton" + "-fictif-" + "x" * 24
COURRIEL = "jean.tremblay" + "@example.test"
TELEPHONE = "418-555" + "-0137"

DIRECTIVES = f"""# Directives fictives de Nathan

Préambule ignoré.

## Construire à partir de briques existantes

Avant de développer une capacité importante, rechercher ce qui fonctionne déjà. Contact fictif : {COURRIEL},
{TELEPHONE}.
OPSYS_TOKEN: {SECRET}

## Validations humaines

Les validations humaines restent en vigueur pour l'argent réel et les publications.

## Économiser les jetons

Calculs déterministes et contexte ciblé.
"""
ADR_1 = """# ADR-0001 — Premier choix du cœur

Statut: Accepted (immuable — changer = nouvel ADR qui supersede)
Date: 2026-07-17

## Décision

Le cœur est construit sur la brique Alpha.
"""
ADR_2 = """# ADR-0002 — Le cœur devient Beta

- Statut : **Accepté** (chef de projet)
- Remplace : ADR-0001 (conservé à titre historique)
- Date : 2026-09-28

## Décisions

1. Le cœur est construit sur la brique Beta, fork maintenu.
"""
ADR_3 = """# ADR-0003 — Précision sur Beta

- Statut : **Proposé**
- Remplace : le point 1 de l'ADR-0002 (« brique Beta »). Le reste d'ADR-0002 reste en vigueur.
- Date : 2026-09-30

## Décision

Le fork de Beta garde ses licences d'origine.
"""
AGENTS = """# AGENTS fictif

## Interdits

Aucun secret dans git.

## Git

Messages en français.
"""
CONDENSE_M7 = """# M7 — Marketing et croissance (condensé fictif)

Publier du contenu de marque après approbation humaine ; mesurer l'attribution.
"""
CONDENSE_M10 = """# M10 — Mémoire (condensé fictif)

Le cerveau permanent : rien d'important n'est oublié.
"""
MATRICE = json.dumps(
    {
        "schema": "opsys.mission.requirements.v1",
        "module": "M10",
        "requirements": [
            {"id": "M10.5", "current_status": "PARTIEL"},
            {"id": "M10.6", "current_status": "ABSENT"},
            {"id": "M10.7", "current_status": "statut avec espaces"},
        ],
    },
    indent=1,
)
DOC_AVEC_BLOC = """# Rapport d'architecture fictif

Ancien rapport.

```m10-affirmations
[{"sujet": "exigence:M10.5", "attribut": "statut", "valeur": "FAIT_PROUVE"},
 {"sujet": "exigence:M10.6", "attribut": "statut", "valeur": "ABSENT"}]
```
"""


def _git(depot, *args):
    subprocess.run(["git", "-C", str(depot), *args], check=True, capture_output=True)


def _commit(depot, message="fictif"):
    _git(depot, "add", "-A")
    _git(depot, "commit", "-qm", message, "--allow-empty")


def _ecrire(depot, chemin, texte):
    fichier = depot / chemin
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fichier.write_text(texte, encoding="utf-8")


@pytest.fixture
def base_dev(tmp_path, monkeypatch):
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.dev", "Admin développement", "mot-de-passe-admin-dev-123", ["admin"])
        identite.creer_personne(
            cnx, "estimation.dev", "Estimation fictive", "mot-de-passe-estimation-123", ["employee"]
        )
    yield tmp_path
    stockage.liberer()


@pytest.fixture
def depot(tmp_path):
    racine = tmp_path / "repo"
    racine.mkdir()
    subprocess.run(["git", "init", "-q", str(racine)], check=True)
    _git(racine, "config", "user.email", "dev@example.test")
    _git(racine, "config", "user.name", "Dev Fixture")
    _ecrire(racine, "docs/produit/DIRECTIVES-NATHAN.md", DIRECTIVES)
    _ecrire(racine, "docs/decisions/ADR-0001-coeur.md", ADR_1)
    _ecrire(racine, "docs/decisions/ADR-0002-beta.md", ADR_2)
    _ecrire(racine, "docs/decisions/ADR-0003-precision.md", ADR_3)
    _ecrire(racine, "AGENTS.md", AGENTS)
    _ecrire(racine, "docs/reprise/PROMPTS-NATHAN-ANCIENS/M7-MARKETING.md", CONDENSE_M7)
    _ecrire(racine, "docs/reprise/PROMPTS-NATHAN-ANCIENS/M10-MEMOIRE.md", CONDENSE_M10)
    _ecrire(racine, "docs/reprise/MATRICES-20261031/MATRICE-EXIGENCES-M10.json", MATRICE)
    _ecrire(racine, "docs/architecture/RAPPORT-ANCIEN.md", DOC_AVEC_BLOC)
    _ecrire(racine, "src/code.py", "x = 1\n")  # hors périmètre
    _ecrire(racine, "data/leads.md", "Contact: client@example.test\n")  # chemin privé
    _commit(racine, "dépôt fictif")
    return racine


def ingerer(depot, horodatage=H1, **options):
    with contexte.appele_par_appareil(ADMIN):
        return ing.ingerer(depot, horodatage=horodatage, **options)


def preflight(module, tache, files=(), depot=None):
    with contexte.appele_par_appareil(ADMIN):
        return dev.preflight(module, tache, files=list(files), repository=depot)


def _maillons(nom):
    with stockage.transaction():
        return list(stockage.maillons("m10-memoire", nom))


def _evenements(type_evenement=None):
    paquets = [m["paquet"] for m in _maillons("developpement")]
    return [e for p in paquets for e in p["events"] if type_evenement in (None, e["event_type"])]


def _payload(entite):
    versions = [e for e in _evenements() if e["entity_id"] == entite]
    return [json.loads(e["payload_json"]) | {"_version": e["version"]} for e in versions]


# -- 1. autorité --------------------------------------------------------------------------------------------------
def test_l_ingestion_exige_une_personne_authentifiee_admin_ou_proprietaire(base_dev, depot):
    with pytest.raises(dev.AccesDeveloppementRefuse):
        ing.ingerer(depot, horodatage=H1)
    with contexte.appele_par_appareil(EMPLOYE), pytest.raises(dev.AccesDeveloppementRefuse):
        ing.ingerer(depot, horodatage=H1)
    assert _maillons("developpement") == [] and _maillons("affirmations") == []


# -- 2. ce qui est rangé, sourcé et expurgé -------------------------------------------------------------------------
def test_premiere_ingestion_range_directives_adr_regles_condenses_et_sources(base_dev, depot):
    rapport = ingerer(depot)
    classes = {f["chemin"]: (f["classe_source"], f["genre"]) for f in rapport["fichiers"]}
    assert classes == {
        "AGENTS.md": ("constitution", "regle"),
        "docs/produit/DIRECTIVES-NATHAN.md": ("decision_proprietaire", "directive"),
        "docs/decisions/ADR-0001-coeur.md": ("constitution", "adr"),
        "docs/decisions/ADR-0002-beta.md": ("constitution", "adr"),
        "docs/decisions/ADR-0003-precision.md": ("constitution", "adr"),
        "docs/reprise/MATRICES-20261031/MATRICE-EXIGENCES-M10.json": ("matrice_vivante", "matrice"),
        "docs/reprise/PROMPTS-NATHAN-ANCIENS/M7-MARKETING.md": ("memoire_ancienne", "condense"),
        "docs/reprise/PROMPTS-NATHAN-ANCIENS/M10-MEMOIRE.md": ("memoire_ancienne", "condense"),
        "docs/architecture/RAPPORT-ANCIEN.md": ("documentation", "document"),
    }
    assert rapport["fichiers_lus"] == 9 and rapport["inchanges"] == 0
    # ni le code, ni le chemin privé, ni un fichier non suivi n'entrent
    assert all(f["chemin"] not in ("src/code.py", "data/leads.md") for f in rapport["fichiers"])
    # 3 sections de directive + 3 sections de règles... AGENTS : 2 ; ADR : 3 ; condensés : 2 prompts
    assert rapport["ajoutes"] == 3 + 2 + 3 + 2
    decisions = {e["entity_id"] for e in _evenements("decision")}
    assert "decision:directive-construire-a-partir-de-briques-existantes" in decisions
    assert {"decision:adr-0001", "decision:adr-0002", "decision:adr-0003"} <= decisions
    assert {e["entity_id"] for e in _evenements("prompt")} == {
        "prompt:condense-m7-marketing",
        "prompt:condense-m10-memoire",
    }


def test_chaque_enregistrement_cite_chemin_empreinte_et_date_de_sa_source(base_dev, depot):
    ingerer(depot)
    sources = [json.loads(e["payload_json"]) for e in _evenements("source_snapshot")]
    adr = next(s for s in sources if s["path"] == "docs/decisions/ADR-0002-beta.md")
    assert len(adr["sha256"]) == 64 and adr["commit"] and adr["source_date"].startswith("20")
    assert adr["classe_source"] == "constitution" and adr["genre"] == "adr" and adr["module"] == "PROJET"
    [decision] = _payload("decision:adr-0002")
    assert decision["source_refs"] == ["docs/decisions/ADR-0002-beta.md"] and decision["module"] == "PROJET"
    assert (
        decision["autorite"].startswith("constitution")
        and "Accepté" in decision["autorite"]
        and "2026-09-28" in decision["autorite"]
    )
    assert decision["status"] == "active"
    assert _payload("decision:adr-0003")[0]["status"] == "draft"  # « Proposé »
    assert (
        _payload("decision:adr-0001")[0]["status"] == "active"
    )  # « Accepted (… qui supersede) » n'est pas un remplacement


def test_aucun_secret_ni_renseignement_personnel_n_est_range_et_la_sensibilite_est_classee(base_dev, depot):
    rapport = ingerer(depot)
    directives = next(f for f in rapport["fichiers"] if f["genre"] == "directive")
    assert directives["sensibilite"] == {"niveau": "masquee", "secrets": 1, "courriels": 1, "telephones": 1}
    propres = [f for f in rapport["fichiers"] if f["chemin"] != "docs/produit/DIRECTIVES-NATHAN.md"]
    assert all(f["sensibilite"]["niveau"] == "aucune" for f in propres)
    assert rapport["sensibilite"] == {"fichiers_masques": 1, "fichiers_propres": 8}
    stocke = json.dumps([m["paquet"] for m in _maillons("developpement")], ensure_ascii=False)
    for valeur in (SECRET, COURRIEL, TELEPHONE, "tremblay"):
        assert valeur not in stocke, valeur
    assert "[REDACTED]" in stocke and "[EMAIL_REDACTED]" in stocke and "[PHONE_REDACTED]" in stocke
    assert SECRET not in json.dumps(rapport) and COURRIEL not in json.dumps(rapport)  # le rapport non plus
    [section] = [p for p in _payload("decision:directive-construire-a-partir-de-briques-existantes")]
    assert section["status"] == "sensitive" and section["redacted"] is True


def test_un_chemin_prive_dans_le_perimetre_est_ecarte_meme_s_il_correspond_a_un_motif(base_dev, depot):
    """`docs/architecture/data/…` correspond au motif de la documentation, mais « data » est un répertoire privé."""
    _ecrire(depot, "docs/architecture/data/exports.md", "# Exports\n\nNe doit pas entrer.\n")
    _commit(depot, "chemin privé")
    rapport = ingerer(depot)
    ecarte = {"chemin": "docs/architecture/data/exports.md", "raison": "chemin privé ou extension hors périmètre"}
    assert ecarte in rapport["ignores"]
    assert "Ne doit pas entrer" not in json.dumps([m["paquet"] for m in _maillons("developpement")])


def test_le_contenu_ne_sort_jamais_du_perimetre_chemin_prive_et_fichier_non_suivi(base_dev, depot):
    _ecrire(depot, "docs/decisions/ADR-0099-non-suivi.md", ADR_1)  # écrit mais jamais ajouté à Git
    rapport = ingerer(depot)
    assert "ADR-0099" not in json.dumps(rapport)
    assert "client@example.test" not in json.dumps([m["paquet"] for m in _maillons("developpement")])


def test_un_lien_symbolique_ou_un_fichier_trop_gros_est_ecarte_pas_ingere(base_dev, depot, tmp_path):
    exterieur = tmp_path / "secret-externe.md"
    exterieur.write_text("Contenu hors dépôt.\n", encoding="utf-8")
    os.symlink(exterieur, depot / "docs/decisions/ADR-0050-lien.md")
    _ecrire(depot, "docs/decisions/ADR-0051-gros.md", "# ADR-0051 — gros\n" + "x" * (dev.MAX_FILE_BYTES + 10))
    _commit(depot, "lien et gros fichier")
    rapport = ingerer(depot)
    ignores = {i["chemin"]: i["raison"] for i in rapport["ignores"]}
    assert "docs/decisions/ADR-0050-lien.md" in ignores and "docs/decisions/ADR-0051-gros.md" in ignores
    assert "Contenu hors dépôt" not in json.dumps([m["paquet"] for m in _maillons("developpement")])
    assert not any(e["entity_id"] in ("decision:adr-0050", "decision:adr-0051") for e in _evenements("decision"))


def test_les_bornes_de_l_ingestion_sont_refusees_au_dela_des_maximums(base_dev, depot):
    for options in (
        {"max_fichiers": 0},
        {"max_fichiers": ing.MAX_FICHIERS + 1},
        {"max_octets": 0},
        {"max_octets": ing.MAX_OCTETS_TOTAL + 1},
    ):
        with pytest.raises(ValueError):
            ingerer(depot, **options)
    with pytest.raises(ValueError):
        ingerer(depot, horodatage="demain")
    partiel = ingerer(depot, max_fichiers=2)
    assert partiel["fichiers_lus"] == 2 and any(i["raison"] == "limite de fichiers" for i in partiel["ignores"])


# -- 3. idempotence ---------------------------------------------------------------------------------------------
def test_reingerer_le_meme_depot_n_ajoute_rien_du_tout(base_dev, depot):
    premier = ingerer(depot, H1)
    avant = ([m["ligne_id"] for m in _maillons("developpement")], [m["ligne_id"] for m in _maillons("affirmations")])
    second = ingerer(depot, H2)
    apres = ([m["ligne_id"] for m in _maillons("developpement")], [m["ligne_id"] for m in _maillons("affirmations")])
    assert avant == apres  # pas un événement, pas un maillon de plus
    assert (
        second["ajoutes"],
        second["versions"],
        second["archives"],
        second["remplacements"],
        second["sources_nouvelles"],
    ) == (0, 0, 0, 0, 0)
    assert (
        second["inchanges"] == premier["ajoutes"]
        and second["affirmations"]["inchangees"] == premier["affirmations"]["ajoutees"]
    )
    with contexte.appele_par_appareil(ADMIN):
        assert dev.verifier_chaine()["status"] == "valid"


def test_un_commit_qui_ne_touche_pas_un_fichier_ne_le_reingere_pas(base_dev, depot):
    ingerer(depot, H1)
    _ecrire(depot, "src/code.py", "x = 2\n")
    _commit(depot, "autre changement")
    avant = len(_maillons("developpement"))
    ingerer(depot, H2)
    assert len(_maillons("developpement")) == avant  # la source est adressée par son contenu, pas par le commit


# -- 4. versions, archives, remplacements --------------------------------------------------------------------------
def test_un_fichier_modifie_ajoute_une_version_remplacee_dont_la_trace_reste(base_dev, depot):
    ingerer(depot, H1)
    _ecrire(
        depot,
        "docs/produit/DIRECTIVES-NATHAN.md",
        DIRECTIVES.replace("restent en vigueur", "demeurent en vigueur, sans exception"),
    )
    _commit(depot, "directive précisée")
    rapport = ingerer(depot, H2)
    assert rapport["versions"] == 1 and rapport["ajoutes"] == 0
    versions = _payload("decision:directive-validations-humaines")
    assert [v["_version"] for v in versions] == [1, 2]
    assert "restent en vigueur" in versions[0]["raisons"][0] and "sans exception" in versions[1]["raisons"][0]
    evenements = {e["event_id"]: e["entity_id"] for e in _evenements("decision")}
    relations = [
        (evenements[r["from_event"]], evenements[r["to_ref"]])
        for m in _maillons("developpement")
        for r in m["paquet"]["relations"]
        if r["relation_type"] == "superseded_by" and r["from_event"] in evenements
    ]
    assert ("decision:directive-validations-humaines", "decision:directive-validations-humaines") in relations
    sortie = preflight("M3", "validations humaines pour l'argent réel et les publications")
    visibles = [x for x in sortie["must_know"] if x["entity_id"] == "directive-validations-humaines"]
    assert [v["version"] for v in visibles if v["status"] != "superseded"] == [2]  # la version en vigueur


def test_une_section_retiree_ou_un_fichier_disparu_est_archive_jamais_supprime(base_dev, depot):
    ingerer(depot, H1)
    _ecrire(depot, "docs/produit/DIRECTIVES-NATHAN.md", DIRECTIVES.split("## Économiser les jetons")[0])
    _git(depot, "rm", "-q", "docs/reprise/PROMPTS-NATHAN-ANCIENS/M7-MARKETING.md")
    _commit(depot, "section et condensé retirés")
    rapport = ingerer(depot, H2)
    assert rapport["archives"] == 2
    section = _payload("decision:directive-economiser-les-jetons")
    assert [(v["_version"], v["status"]) for v in section] == [(1, "active"), (2, "archived")]
    assert section[1]["raisons"] == section[0]["raisons"]  # la trace d'origine est conservée telle quelle
    prompt = _payload("prompt:condense-m7-marketing")
    assert [(v["_version"], v["status"]) for v in prompt] == [(1, "active"), (2, "archived")]
    assert prompt[1]["content"] == prompt[0]["content"]
    assert ingerer(depot, H3)["archives"] == 0  # déjà archivé : rien de plus
    # une section qui revient redevient active (nouvelle version)
    _ecrire(depot, "docs/produit/DIRECTIVES-NATHAN.md", DIRECTIVES)
    _commit(depot, "retour")
    assert ingerer(depot, "2026-11-05T10:00:00+00:00")["versions"] >= 1
    assert _payload("decision:directive-economiser-les-jetons")[-1]["status"] == "active"


def test_un_fichier_non_traite_cette_fois_n_archive_rien(base_dev, depot):
    ingerer(depot, H1)
    partiel = ingerer(depot, H2, max_fichiers=1)  # le plus précis seulement ; les autres ne sont pas relus
    assert partiel["archives"] == 0
    assert all(v["status"] != "archived" for e in _evenements("decision") for v in [json.loads(e["payload_json"])])


def test_un_remplacement_total_lie_l_adr_remplace_un_remplacement_partiel_est_seulement_consigne(base_dev, depot):
    rapport = ingerer(depot)
    assert rapport["remplacements"] == 1  # ADR-0001 -> ADR-0002 ; le « point 1 » de ADR-0003 ne remplace pas ADR-0002
    anciens = {e["entity_id"]: e["event_id"] for e in _evenements("decision")}
    relations = [
        r for m in _maillons("developpement") for r in m["paquet"]["relations"] if r["relation_type"] == "superseded_by"
    ]
    assert [(r["from_event"], r["to_ref"]) for r in relations] == [
        (anciens["decision:adr-0001"], anciens["decision:adr-0002"])
    ]
    [adr3] = _payload("decision:adr-0003")
    assert any("partiellement" in x and "ADR-0002" in x for x in adr3["consequences"])
    sortie = preflight("OPSYS", "le coeur est construit sur la brique", ["docs/decisions/ADR-0001-coeur.md"])
    etats = {x["entity_id"]: x["status"] for x in sortie["must_know"]}
    assert etats["adr-0001"] == "superseded" and etats["adr-0002"] == "active"
    assert (
        sortie["counts"]["lineage_endpoints"] >= 1
    )  # la lignée de remplacement part de l'ADR remplacé vers le courant


def test_la_ligne_remplace_est_lue_sans_confondre_une_simple_mention(base_dev):
    assert ing.remplacements("Remplace : l'ADR-0007 (OpenClaw) et le point 1 de l'ADR-0006.") == {
        "total": ["0007"],
        "partiel": ["0006"],
    }
    assert ing.remplacements("Remplace : ADR-0001 à ADR-0005, programme « Core-first »")["total"] == [
        f"{n:04d}" for n in range(1, 6)
    ]
    assert ing.remplacements("Remplace : les obligations; l'exclusion (ADR-0008, réponse au point 5).") == {
        "total": [],
        "partiel": [],
    }
    assert ing.remplacements("Remplace : ADR-0009 à ADR-0001") == {"total": [], "partiel": []}  # plage à l'envers
    assert ing.remplacements(None) == {"total": [], "partiel": []}
    assert ing.statut_adr("Accepted (immuable — changer = nouvel ADR qui supersede)") == "active"
    assert (
        ing.statut_adr("Proposé") == "draft"
        and ing.statut_adr("Rejeté") == "rejected"
        and ing.statut_adr(None) == "requires_review"
    )
    assert ing.statut_adr("Remplacé par ADR-0009") == "superseded"


# -- 5. consultation par le preflight de développement --------------------------------------------------------------
def test_le_preflight_rend_la_directive_en_vigueur_pour_n_importe_quel_module(base_dev, depot):
    ingerer(depot)
    sortie = preflight(
        "M3", "Avant de développer une capacité importante, réutiliser les briques existantes", [], depot
    )
    assert sortie["status"] == "available"
    directive = next(
        x for x in sortie["must_know"] if x["entity_id"] == "directive-construire-a-partir-de-briques-existantes"
    )
    assert directive["payload"]["autorite"] == "decision_proprietaire" and directive["payload"]["module"] == "PROJET"
    assert all(SECRET not in json.dumps(x) for x in sortie["must_know"])
    sources = {e["path"]: e["freshness"] for e in sortie["evidence"]}
    assert sources.get("docs/produit/DIRECTIVES-NATHAN.md") == "current"  # la fraîcheur se vérifie par l'empreinte


def test_avant_de_coder_m7_le_condense_de_m7_est_la_et_pas_celui_de_m10(base_dev, depot):
    ingerer(depot)
    sortie = preflight("M7", "marketing contenu de marque approbation humaine attribution")
    ids = {x["entity_id"] for x in sortie["must_know"]}
    assert "condense-m7-marketing" in ids and "condense-m10-memoire" not in ids
    assert (
        preflight("M10", "cerveau permanent rien d'important n'est oublié")["must_know"][0]["entity_id"]
        == "condense-m10-memoire"
    )


def test_une_ancre_de_fichier_exacte_retrouve_l_adr(base_dev, depot):
    ingerer(depot)
    sortie = preflight("CORE", "n'importe quoi", ["docs/decisions/ADR-0002-beta.md"])
    assert any(x["entity_id"] == "adr-0002" for x in sortie["must_know"])


def test_travail_minuscule_une_phrase_modifiee_dans_un_petit_fichier_est_retrouvee(base_dev, depot):
    ingerer(depot, H1)
    _ecrire(
        depot,
        "AGENTS.md",
        AGENTS.replace("Messages en français.", "Messages en français, décrivant le pourquoi du changement."),
    )
    _commit(depot, "une phrase")
    assert ingerer(depot, H2)["versions"] == 1
    sortie = preflight("OPSYS", "messages de commit en français décrivant le pourquoi")
    texte = json.dumps(sortie["must_know"], ensure_ascii=False)
    assert "décrivant le pourquoi du changement" in texte


# -- 6. contradictions : matrice vivante contre ancien rapport ----------------------------------------------------
def test_la_matrice_vivante_l_emporte_sur_l_ancien_rapport_et_la_contradiction_est_rangee(base_dev, depot):
    rapport = ingerer(depot)
    assert rapport["affirmations"] == {
        "ajoutees": 4,
        "remplacees": 0,
        "inchangees": 0,
        "retirees": 0,
        "refusees": {"REJ-AFFIRMATION-VALEUR-INVALIDE": 1},
    }
    with stockage.transaction():
        liste = c.affirmations(co._REGISTRE_AFFIRMATIONS.lire())
    classes = {(a["sujet"], a["classe"]): a["valeur"] for a in liste}
    assert (
        classes[("exigence:M10.5", "matrice_vivante")] == "PARTIEL"
        and classes[("exigence:M10.5", "documentation")] == "FAIT_PROUVE"
    )
    ordre = verite.charger()
    actives = c.actives(liste)
    detections = c.detecter(actives, set(), ordre, H1)
    assert [d["cle"] for d in detections] == [
        "developpement|exigence:M10.5|statut"
    ]  # M10.6 s'accorde, M10.7 est refusée
    [detection] = detections
    assert (
        detection["a"]["classe"] == "matrice_vivante"
        and detection["traitement"] == "auto"
        and detection["proposition"]["retenue"] == "a"
    )


def test_un_fichier_qui_change_remplace_ses_affirmations_et_en_retire_ce_qu_il_n_affirme_plus(base_dev, depot):
    ingerer(depot, H1)
    nouvelle = json.dumps(
        {"requirements": [{"id": "M10.5", "current_status": "FAIT_PROUVE"}]}
    )  # M10.6 et M10.7 disparaissent
    _ecrire(depot, "docs/reprise/MATRICES-20261031/MATRICE-EXIGENCES-M10.json", nouvelle)
    _commit(depot, "matrice mise à jour")
    rapport = ingerer(depot, H2)
    assert rapport["affirmations"]["remplacees"] == 1 and rapport["affirmations"]["retirees"] == 1
    with stockage.transaction():
        liste = c.affirmations(co._REGISTRE_AFFIRMATIONS.lire())
    matrice = [a for a in liste if a["classe"] == "matrice_vivante"]
    assert sorted((a["sujet"], a["valeur"], a["active"]) for a in matrice) == [
        ("exigence:M10.5", "FAIT_PROUVE", True),
        ("exigence:M10.5", "PARTIEL", False),
        ("exigence:M10.6", "ABSENT", False),
    ]
    assert len([m for m in _maillons("affirmations") if m["type_entree"] == "affirmation_retiree"]) == 1
    # la matrice et l'ancien rapport s'accordent maintenant : plus de contradiction
    assert c.detecter(c.actives(liste), set(), verite.charger(), H2) == []


def test_un_fichier_disparu_retire_ses_affirmations(base_dev, depot):
    ingerer(depot, H1)
    _git(depot, "rm", "-q", "docs/architecture/RAPPORT-ANCIEN.md")
    _commit(depot, "rapport retiré")
    rapport = ingerer(depot, H2)
    assert rapport["affirmations"]["retirees"] == 2
    with stockage.transaction():
        assert [a["emetteur"] for a in c.actives(c.affirmations(co._REGISTRE_AFFIRMATIONS.lire()))] == [
            "fichier:docs/reprise/MATRICES-20261031/MATRICE-EXIGENCES-M10.json"
        ] * 2


def test_un_bloc_d_affirmations_forge_dans_un_fichier_ne_donne_que_la_classe_de_sa_place(base_dev, depot):
    """Un fichier de documentation qui prétend être la constitution : sa classe vient de SON CHEMIN, pas de son "
    "contenu."""
    _ecrire(
        depot,
        "docs/architecture/FAUX.md",
        '# Faux\n\n```m10-affirmations\n'
        '[{"sujet": "regle:x", "attribut": "gate_humain", "valeur": "oui", "classe": "constitution"}]\n```\n',
    )
    _commit(depot, "faux")
    rapport = ingerer(depot)
    with stockage.transaction():
        liste = c.affirmations(co._REGISTRE_AFFIRMATIONS.lire())
    assert not any(a["sujet"] == "regle:x" for a in liste)  # champ « classe » hors schéma : bloc ignoré
    assert rapport["affirmations"]["ajoutees"] == 4  # seules les affirmations légitimes de l'autre fichier sont entrées


def test_une_valeur_personnelle_dans_un_bloc_est_refusee_et_comptee(base_dev, depot):
    _ecrire(
        depot,
        "docs/architecture/PII.md",
        '# PII\n\n```m10-affirmations\n'
        f'[{{"sujet": "regle:x", "attribut": "contact", "valeur": "{TELEPHONE}"}}]\n```\n',
    )
    _commit(depot, "pii")
    rapport = ingerer(depot)
    assert rapport["affirmations"]["refusees"].get("REJ-AFFIRMATION-DONNEE-PERSONNELLE") == 1
    with stockage.transaction():
        assert not any(a["sujet"] == "regle:x" for a in c.affirmations(co._REGISTRE_AFFIRMATIONS.lire()))
    assert TELEPHONE not in json.dumps([m for m in _maillons("affirmations")])


def test_un_secret_dans_un_bloc_d_affirmations_est_refuse_et_ne_va_pas_au_registre(base_dev, depot):
    secret = "sk-" + "a1b2c3d4" * 4
    _ecrire(
        depot,
        "docs/architecture/SECRET.md",
        '# Secret\n\n```m10-affirmations\n'
        f'[{{"sujet": "regle:x", "attribut": "acces", "valeur": "{secret}"}}]\n```\n',
    )
    _commit(depot, "secret")
    rapport = ingerer(depot)
    assert rapport["affirmations"]["refusees"].get("REJ-AFFIRMATION-SECRET") == 1
    assert secret not in json.dumps(_maillons("affirmations")) and secret not in json.dumps(rapport)


# -- 7. ligne de commande ----------------------------------------------------------------------------------------------
def test_la_commande_ingerer_projet_authentifie_interactivement_et_rend_le_rapport(
    base_dev, depot, monkeypatch, capsys
):
    class Terminal(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setattr(sys, "stdin", Terminal())
    monkeypatch.setattr("builtins.input", lambda _prompt: "admin.dev")
    monkeypatch.setattr("getpass.getpass", lambda _prompt: "mot-de-passe-admin-dev-123")
    assert cli_main(["memoire-developpement", "ingerer-projet", "--depot", str(depot)]) == 0
    sortie = json.loads(capsys.readouterr().out)
    assert sortie["fichiers_lus"] == 9 and sortie["ajoutes"] == 10
    assert cli_main(["memoire-developpement", "ingerer-projet", "--depot", str(depot)]) == 0
    assert json.loads(capsys.readouterr().out)["ajoutes"] == 0


def test_la_commande_refuse_sans_terminal_interactif(base_dev, depot, monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO())
    assert cli_main(["memoire-developpement", "ingerer-projet", "--depot", str(depot)]) == 1
    assert "connexion interactive" in capsys.readouterr().err
    assert _maillons("developpement") == []


def test_un_depot_inaccessible_est_un_refus_pas_une_ingestion_vide(base_dev, tmp_path):
    with contexte.appele_par_appareil(ADMIN), pytest.raises(ValueError, match="dépôt Git"):
        ing.ingerer(tmp_path / "pas-un-depot", horodatage=H1)
    assert Path(tmp_path).exists()
