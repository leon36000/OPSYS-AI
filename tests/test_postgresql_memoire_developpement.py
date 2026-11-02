"""Magasin de développement M10 et jobs de consolidation en VRAIS PROCESSUS, sur SQLite ET sur PostgreSQL 17 réel.

Le garde « SQLite seulement » des jobs est levé. Ce qui le justifiait : la sérialisation des écrivains reposait sur
`BEGIN IMMEDIATE`. Sous PostgreSQL (READ COMMITTED), deux écrivains du magasin relisent le MÊME canon, calculent leur
chaîne d'événements sur la même tête (`previous_hash`) puis ajoutent chacun un maillon : la chaîne bifurque, ou le
perdant échoue en `EcritureConcurrente`, et deux écrivains du même prompt « gagnent » tous les deux. Le verrou de
transaction nommé `m10-developpement`, pris avant la relecture du canon, rend à PostgreSQL ce qu'a SQLite. Prouvé ici :
N écrivains concurrents (prompts distincts, prompt identique, versions en conflit) et N exécuteurs de job concurrents
(jamais deux rapports pour un créneau, jamais deux baux vivants), chaîne linéaire à la fin.
Données fictives, aucun réseau.
"""

from __future__ import annotations

import datetime as dt
import subprocess
from collections import Counter

import pytest
from m10_memoire import consolidation_developpement as job
from m10_memoire import developpement as dev
from pg_concurrence import lancer
from pg_dev import ecrire_prompt, executer_job
from pg_parite import base_pg, serveur_pg, url_base  # noqa: F401  (fixtures pytest)

from opsys import contexte, identite, stockage

FICTIF = True
N = 4
ADMIN = contexte.IdentiteAppelante("admin.dev", "admin")


@pytest.fixture
def base_dev(url_base, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setenv(stockage.ENV_URL, url_base)
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys-fictif"))
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.dev", "Admin fictif", "mot-de-passe-fictif-job-123", ["admin"])
    yield tmp_path
    stockage.liberer()


@pytest.fixture
def depot_git(tmp_path):
    depot = tmp_path / "depot-fictif"
    (depot / "departments/m10-memoire/docs").mkdir(parents=True)
    (depot / "departments/m10-memoire/docs/preuve.md").write_text("Mémoire M10 fictive, preuve sourcée.\n")
    for args in (["init", "-q"], ["config", "user.email", "fictif@example.test"], ["config", "user.name", "Fictif"],
                 ["add", "."], ["commit", "-qm", "fixture fictive"]):
        subprocess.run(["git", "-C", str(depot), *args], check=True)
    return depot


def _sans_panne(issues) -> None:
    assert [i for i in issues if i[0] == "PANNE"] == [], issues


def _evenements() -> list[dict]:
    """Tous les événements du canon, dans l'ordre des maillons."""
    return [e for m in stockage.maillons("m10-memoire", dev.REGISTRE_DURABLE) for e in m["paquet"]["events"]]


def _chaine_lineaire() -> None:
    evenements = _evenements()
    precedent = None
    for e in evenements:
        assert e["previous_hash"] == precedent, "la chaîne d'événements du magasin a bifurqué"
        precedent = e["event_hash"]


def test_n_ecrivains_de_prompts_distincts_la_chaine_d_evenements_reste_lineaire(base_dev):
    issues = lancer(ecrire_prompt, [(f"p{i}", "texte fictif", 1) for i in range(N)], delai_s=300)
    _sans_panne(issues)
    assert issues == [("ok", False)] * N
    assert len(_evenements()) == N
    _chaine_lineaire()
    with contexte.appele_par_appareil(ADMIN):  # le canon se relit (refus sinon : chaîne bifurquée)
        assert dev.enregistrer_prompt("suite", "fictif", version=1, module="M10", objectif="après course",
                                      horodatage="2026-09-30T15:00:00+00:00")["prompt_id"] == "suite"


def test_n_ecrivains_du_meme_prompt_un_seul_evenement_les_autres_rejouent(base_dev):
    issues = lancer(ecrire_prompt, [("meme", "texte fictif", 1)] * N, delai_s=300)
    _sans_panne(issues)
    assert Counter(issues) == {("ok", False): 1, ("ok", True): N - 1}, issues
    assert len(_evenements()) == 1


def test_n_ecrivains_de_deux_textes_pour_la_meme_version_un_gagnant_et_des_conflits_dits(base_dev):
    issues = lancer(ecrire_prompt, [("conflit", t, 1) for t in ("texte A", "texte B", "texte A", "texte B")],
                    delai_s=300)
    _sans_panne(issues)
    gagnants = [i for i in issues if i[0] == "ok" and i[1] is False]
    assert len(gagnants) == 1, issues
    assert all(i[0] == "refus" and i[1] == "ConflitIdempotence" or i[0] == "ok" for i in issues), issues
    assert len(_evenements()) == 1
    _chaine_lineaire()


def test_n_executeurs_du_meme_job_un_seul_rapport_et_pas_deux_baux_vivants(base_dev, depot_git):
    credential = base_dev / "job-credential.json"
    hier = (dt.datetime.now(dt.UTC) - dt.timedelta(days=1)).date().isoformat()
    with contexte.appele_par_appareil(ADMIN):
        job.autoriser("audit-dev", depot_git, credential, premier_jour=hier)
        dev.enregistrer_prompt("p", "texte fictif", version=1, module="M7", objectif="SEO",
                               horodatage="2026-09-30T15:00:00+00:00")
    issues = lancer(executer_job, [("audit-dev", str(credential))] * N, delai_s=600)
    _sans_panne(issues)
    rapports = [m["paquet"] for m in job._journal().lire() if m["paquet"]["kind"] == "report"]
    creneaux_dus = len(rapports)
    # chaque créneau dû (au plus deux : hier et aujourd'hui) a UN rapport ; jamais deux pour le même créneau
    assert 1 <= creneaux_dus <= 2 and len({r["slot"] for r in rapports}) == creneaux_dus
    baux = [m["paquet"] for m in job._journal().lire() if m["paquet"]["kind"] == "lease"]
    assert [b["epoch"] for b in baux if not b["finished"]] == sorted({b["epoch"] for b in baux if not b["finished"]})
    assert len({b["epoch"] for b in baux if not b["finished"]}) == len([b for b in baux if not b["finished"]])
    assert job._journal().valider_chaine() == (True, "")
    assert all(i[0] == "ok" or i[1] in {"ConflitJob"} for i in issues), issues
    assert any(i[0] == "ok" for i in issues)
