"""Parcours M03 HTTP→BGE-M3 local→pgvector, opt-in ROOT et sur contenu fictif."""

from __future__ import annotations

import os
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from memoire.doubles import postgres_ephemere, vider

from opsys.contexte import appeler_en_tant_que
from opsys.memoire import MemoireEntreprise
from opsys.memoire import outils as outils_memoire
from opsys.memoire.embeddings import ClientEmbeddings, EmbeddingsProfil, ErreurEmbeddings, _valider_profil
from opsys.memoire.profil_embeddings_local import (
    DIMENSION_LOCALE,
    MODELE_LOCAL,
    PROFILE_SHA256,
    recette_embedding,
)

ACTIVER = os.environ.get("OPSYS_M03_REAL_PG") == "1"
RAISON = "opt-in réservé: OPSYS_M03_REAL_PG=1"
TESTS_PG_FICTIFS = os.environ.get("OPSYS_M03_PG_TESTS") == "1"


@pytest.mark.skipif(not ACTIVER, reason=RAISON)
def test_m03_admission_active_vectorisee_recherche_citation_et_oubli_sur_provider_reel(monkeypatch, record_property):
    # Réutilise seulement le harnais R41 déjà qualifié; aucune copie de ses assertions ou preuve n'est modifiée.
    from tests import test_memoire_embeddings_local_postgres as r41

    actifs = Path(os.environ.get("OPSYS_R41_ASSETS_DIR", r41.ACTIFS_DEFAUT)).resolve(strict=True)
    python = r41._python_venv(os.environ.get("OPSYS_R41_PYTHON", r41.PYTHON_DEFAUT))
    cle = os.environ.get("OPSYS_EMBEDDINGS_CLE", "")
    assert len(cle) >= 24, "OPSYS_EMBEDDINGS_CLE doit être un jeton de test privé"
    courant, maximum = r41._cgroup_entetes()
    assert maximum - courant >= r41.MARGE_DEMARRAGE_MIN
    assert r41._mem_available() >= r41.MARGE_DEMARRAGE_MIN

    port = r41._port_libre()
    env = dict(os.environ)
    env.update(
        {
            "PYTHONPATH": str(r41.RACINE / "src"),
            "OPSYS_EMBEDDINGS_ASSETS": str(actifs),
            "OPSYS_EMBEDDINGS_CLE": cle,
            "OPSYS_EMBEDDINGS_HOST": "127.0.0.1",
            "OPSYS_EMBEDDINGS_PORT": str(port),
            "OPSYS_EMBEDDINGS_DELAI_S": "25",
            "OMP_NUM_THREADS": "2",
            "OPENBLAS_NUM_THREADS": "1",
            "TOKENIZERS_PARALLELISM": "false",
            "TMPDIR": "/dev/shm/opsys-r35-20261002-onnx/tmp",
        }
    )
    provider = subprocess.Popen(
        [str(python), "-m", "opsys.memoire.serveur_embeddings_local"],
        cwd=r41.RACINE,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        preexec_fn=r41._limiter_processus,
    )
    record_property("m03_provider_pid", provider.pid)
    stop = threading.Event()
    erreurs: list[str] = []
    rss: list[int] = []
    marges: list[int] = []
    surveillant = threading.Thread(target=r41._surveiller, args=(provider, stop, erreurs, rss, marges), daemon=True)
    surveillant.start()
    base = f"http://127.0.0.1:{port}/v1"
    try:
        sante = r41._attendre_sante(base, cle, provider)
        assert sante["opsys_embedding_profile"]["recipe"]["model_revision"].endswith(
            "4de13258303883538bd53b696b452bf8099f0858"
        )
        record_property("m03_provider_started", "true")
        record_property("m03_provider_profile", sante["opsys_embedding_profile"]["id"])
        record_property("m03_provider_profile_sha256", sante["opsys_embedding_profile"]["id"])
        record_property("m03_provider_model_sha256", sante["model_sha256"])
        record_property("m03_provider_tokenizer_sha256", sante["tokenizer_sha256"])
        courant, maximum = r41._cgroup_entetes()
        assert maximum - courant >= r41.MARGE_PG_MIN

        with postgres_ephemere(stockage_en_memoire=True) as url:
            memoire = MemoireEntreprise(url)
            memoire.migrer()
            vider(url)
            procedures = memoire.procedures()
            corps = (
                "# Inspection des solins\n\n"
                "Vérifier les solins de cuivre et les fixations avant de fermer la toiture.\n"
            ).encode()
            admis = procedures.admettre(
                corps,
                "Procédure fictive des solins",
                auteur="admin:test-m03",
                cle_admission="cle-m03-vectorisation-fictive-0001",
            )
            procedures.indexer(admis.document_id, admis.sha256)
            procedures.activer(admis.document_id, admis.sha256, attendu_sha256=None, auteur="admin:test-m03")
            client = ClientEmbeddings(base, "BAAI/bge-m3", cle=cle, local=True, taille_lot=1, delai_s=30)
            etat = memoire.vectoriser_procedures(admis.document_id, admis.sha256, client, limite=8)
            assert etat["vectorises"] == 1 and etat["trop_longs"] == 0
            record_property("m03_provider_model_started", "true")

            monkeypatch.setenv("OPSYS_DATABASE_URL", url)
            monkeypatch.setenv("OPSYS_DEPARTEMENT", "m03-estimation")
            monkeypatch.setenv("OPSYS_DEPARTMENTS", str(r41.RACINE / "departments"))
            monkeypatch.setenv("OPSYS_EMBEDDINGS_URL", base)
            monkeypatch.setenv("OPSYS_EMBEDDINGS_MODELE", "BAAI/bge-m3")
            monkeypatch.setenv("OPSYS_EMBEDDINGS_LOCAL", "1")
            monkeypatch.setenv("OPSYS_EMBEDDINGS_TAILLE_LOT", "1")
            monkeypatch.setenv("OPSYS_EMBEDDINGS_CLE", cle)
            with appeler_en_tant_que("m03-estimation"):
                resultat = outils_memoire.rechercher(
                    "Comment vérifier les solins de cuivre?", portees=["procedures"], k=5
                )
            assert resultat["mode"] == "hybride", resultat
            citations = resultat["resultats"][0]["citations_verifiees"]
            citation = citations[0]
            assert citation["document_id"] == admis.document_id
            assert citation["version_sha256"] == admis.sha256
            position = citation["positions"][0]
            assert corps[position["debut_octets"] : position["fin_octets"]].decode("utf-8").strip()

            procedures.oublier(admis.document_id, demandeur="admin:test-m03", motif="fin de test fictif")
            assert memoire.etat()["fragments"] == 0
            with appeler_en_tant_que("m03-estimation"):
                apres_oubli = outils_memoire.rechercher(
                    "Comment vérifier les solins de cuivre?", portees=["procedures"], k=5
                )
            assert apres_oubli["mode"] == "plein_texte"
            assert apres_oubli["resultats"] == []
            fragments_apres_oubli = memoire.etat()["fragments"]
            assert rss and marges, "surveillance provider sans mesures observées"
            record_property("m03_provider_http_port", port)
            record_property("m03_embedding_method", "http-client-postgres-procedures")
            record_property("m03_provider_rss_peak_bytes", max(rss))
            record_property("m03_cgroup_headroom_min_bytes", min(marges))
            record_property("m03_procedure_fragments_vectorised", etat["vectorises"])
            record_property("m03_procedure_fragments_too_long", etat["trop_longs"])
            record_property("m03_hybrid_search_mode", resultat["mode"])
            record_property("m03_hybrid_search_result_count", len(resultat["resultats"]))
            record_property("m03_verified_citation_count", len(citations))
            record_property("m03_fragments_after_forget", fragments_apres_oubli)
            record_property("m03_post_forget_search_mode", apres_oubli["mode"])
            record_property("m03_post_forget_search_result_count", len(apres_oubli["resultats"]))
    finally:
        stop.set()
        surveillant.join(2)
        if provider.poll() is None:
            provider.terminate()
        try:
            provider.wait(timeout=10)
        except subprocess.TimeoutExpired:
            provider.kill()
            provider.wait(timeout=5)
        if erreurs:
            pytest.fail("surveillance provider M03: " + "; ".join(erreurs))


@pytest.fixture(scope="module")
def memoire_pg_fictive():
    if not TESTS_PG_FICTIFS:
        pytest.skip("opt-in réservé: OPSYS_M03_PG_TESTS=1")
    with postgres_ephemere(stockage_en_memoire=True) as url:
        memoire = MemoireEntreprise(url)
        memoire.migrer()
        yield memoire, url


class _EmbedderPgFictif:
    """Double réseau; les opérations de procédure et les assertions restent sur PostgreSQL réel."""

    local = True

    def __init__(self, apres_appel: Callable[[], None] | None = None, *, trop_long: bool = False):
        self.apres_appel = apres_appel
        self.trop_long = trop_long
        self.textes: list[str] = []
        self.profil = {"id": PROFILE_SHA256, "recipe": recette_embedding()}

    def verifier_profil_local(self) -> str:
        return _valider_profil(self.profil, MODELE_LOCAL, DIMENSION_LOCALE)

    def plonger_avec_profil(self, textes: list[str]) -> EmbeddingsProfil:
        assert len(textes) == 1
        self.textes.extend(textes)
        if self.apres_appel is not None:
            self.apres_appel()
        if self.trop_long:
            assert len(textes[0].split()) > 512
            raise ErreurEmbeddings(
                "limite de tokens du provider fictif",
                code="input_token_limit_exceeded",
                http_status=413,
            )
        vecteur = tuple([0.0, 1.0] + [0.0] * (DIMENSION_LOCALE - 2))
        return EmbeddingsProfil((vecteur,), PROFILE_SHA256)


def _preparer_memoire_pg(url: str) -> None:
    vider(url)
    import psycopg

    with psycopg.connect(url) as cnx:
        cnx.execute("DELETE FROM memoire.procedure_admission_oubliees")


def _admettre_activer(memoire: MemoireEntreprise, corps: bytes, cle: str, *, document_id: str | None = None):
    procedures = memoire.procedures()
    admission = procedures.admettre(
        corps,
        "Procédure fictive CAS",
        auteur="admin:test-m03-pg",
        cle_admission=cle,
        document_id=document_id,
    )
    procedures.indexer(admission.document_id, admission.sha256)
    procedures.activer(
        admission.document_id,
        admission.sha256,
        attendu_sha256=None if document_id is None else _sha_courant(memoire, document_id),
        auteur="admin:test-m03-pg",
    )
    return admission


def _sha_courant(memoire: MemoireEntreprise, document_id: str) -> str | None:
    return memoire.procedures().lire_etat(document_id).courante


def _fragment_etat(url: str, document_id: str, sha256: str) -> tuple[Any, ...] | None:
    import psycopg

    with psycopg.connect(url) as cnx:
        return cnx.execute(
            "SELECT f.embedding_status,f.embedding_profile_sha256,f.embedding::text "
            "FROM memoire.fragments f JOIN memoire.documents d ON d.id=f.document_id "
            "JOIN memoire.procedure_versions v ON v.document_id=d.id "
            "WHERE v.document_uuid=%s::uuid AND v.sha256=%s",
            (document_id, sha256),
        ).fetchone()


@pytest.mark.skipif(not TESTS_PG_FICTIFS, reason="opt-in réservé: OPSYS_M03_PG_TESTS=1")
def test_cas_revalide_activation_pendant_appel_embedding_sur_postgres(memoire_pg_fictive):
    memoire, url = memoire_pg_fictive
    _preparer_memoire_pg(url)
    procedures = memoire.procedures()
    corps_v1 = b"# Version active\n\nVerifier les solins cuivre avant pose.\n"
    v1 = _admettre_activer(memoire, corps_v1, "m03pg-cas-activation-v1")
    v2 = procedures.admettre(
        b"# Version suivante\n\nVerifier les attaches zinc avant pose.\n",
        "Procédure fictive CAS",
        auteur="admin:test-m03-pg",
        cle_admission="m03pg-cas-activation-v2",
        document_id=v1.document_id,
    )
    procedures.indexer(v2.document_id, v2.sha256)

    def activer_v2_pendant_embedding() -> None:
        courant = _sha_courant(memoire, v2.document_id)
        assert courant == v1.sha256
        procedures.activer(
            v2.document_id,
            v2.sha256,
            attendu_sha256=courant,
            auteur="admin:test-m03-pg",
        )

    embedder = _EmbedderPgFictif(activer_v2_pendant_embedding)
    resultat = memoire.vectoriser_procedures(v1.document_id, v1.sha256, embedder, limite=1)

    assert embedder.textes and resultat["vectorises"] == 0 and resultat["ignores_cas"] == 1
    assert _fragment_etat(url, v1.document_id, v1.sha256) == ("pending", None, None)
    assert procedures.lire_etat(v1.document_id).courante == v2.sha256


@pytest.mark.skipif(not TESTS_PG_FICTIFS, reason="opt-in réservé: OPSYS_M03_PG_TESTS=1")
def test_cas_oubli_pendant_appel_embedding_ne_ressuscite_pas_le_fragment(memoire_pg_fictive):
    memoire, url = memoire_pg_fictive
    _preparer_memoire_pg(url)
    admission = _admettre_activer(
        memoire,
        b"# Oubli pendant le calcul\n\nSupprimer les fragments apres le calcul.\n",
        "m03pg-cas-oubli-v1",
    )

    def oublier_pendant_embedding() -> None:
        memoire.procedures().oublier(
            admission.document_id,
            demandeur="admin:test-m03-pg",
            motif="oubli au milieu du calcul fictif",
        )

    embedder = _EmbedderPgFictif(oublier_pendant_embedding)
    resultat = memoire.vectoriser_procedures(admission.document_id, admission.sha256, embedder, limite=1)

    assert embedder.textes and resultat["vectorises"] == 0 and resultat["ignores_cas"] == 1
    assert _fragment_etat(url, admission.document_id, admission.sha256) is None
    assert memoire.etat()["fragments"] == 0


@pytest.mark.skipif(not TESTS_PG_FICTIFS, reason="opt-in réservé: OPSYS_M03_PG_TESTS=1")
def test_limite_exacte_tokens_persiste_trop_long_mais_recherche_lexicale(memoire_pg_fictive):
    memoire, url = memoire_pg_fictive
    _preparer_memoire_pg(url)
    texte = " ".join(["zinc"] * 600)
    admission = _admettre_activer(
        memoire,
        f"# Fragment long\n\n{texte}\n".encode(),
        "m03pg-trop-long-v1",
    )
    embedder = _EmbedderPgFictif(trop_long=True)

    resultat = memoire.vectoriser_procedures(admission.document_id, admission.sha256, embedder, limite=1)

    assert len(embedder.textes[0].split()) > 512
    assert resultat["trop_longs"] == 1 and resultat["vectorises"] == 0
    etat = _fragment_etat(url, admission.document_id, admission.sha256)
    assert etat is not None and etat[0:2] == ("trop_long", PROFILE_SHA256) and etat[2] is None
    recherche = memoire.rechercher("zinc", None, 5, {"portee": "procedures"})
    assert recherche.resultats and recherche.resultats[0].source == f"opsys-document://{admission.document_id}/{admission.sha256}"
    assert recherche.resultats[0].citations_verifiees


@pytest.mark.skipif(not TESTS_PG_FICTIFS, reason="opt-in réservé: OPSYS_M03_PG_TESTS=1")
def test_recherche_profilee_exclut_embedding_legacy_unknown(memoire_pg_fictive):
    memoire, url = memoire_pg_fictive
    _preparer_memoire_pg(url)
    admission = _admettre_activer(
        memoire,
        b"# Solins cuivre\n\nVerifier les solins cuivre avant la pose.\n",
        "m03pg-legacy-exclusion-v1",
    )
    embedder = _EmbedderPgFictif()
    assert memoire.vectoriser_procedures(admission.document_id, admission.sha256, embedder, limite=1)["vectorises"] == 1
    legacy_id = memoire.ajouter(
        "Archive historique sans rapport lexical avec la question.",
        {
            "departement": "m03-estimation",
            "portee": "procedures",
            "source": "fictif://legacy-embedding-m03",
            "sensibilite": "interne",
        },
        embedding=[1.0] + [0.0] * (DIMENSION_LOCALE - 1),
    )

    recherche = memoire.rechercher(
        "solins cuivre",
        [1.0] + [0.0] * (DIMENSION_LOCALE - 1),
        5,
        {"portee": "procedures"},
        embedding_profile_sha256=PROFILE_SHA256,
    )

    assert any(ligne.source.startswith("opsys-document://") for ligne in recherche.resultats)
    assert all(ligne.fragment_id != legacy_id for ligne in recherche.resultats)


@pytest.mark.skipif(not TESTS_PG_FICTIFS, reason="opt-in réservé: OPSYS_M03_PG_TESTS=1")
def test_sha_obsolete_et_offsets_corrompus_refuses_avant_embedding(memoire_pg_fictive):
    memoire, url = memoire_pg_fictive
    _preparer_memoire_pg(url)
    admission = _admettre_activer(
        memoire,
        b"# Provenance\n\nVerifier la provenance de chaque fragment.\n",
        "m03pg-provenance-v1",
    )
    stale = _EmbedderPgFictif()
    with pytest.raises(ValueError, match="version absente, non INDEXE ou inactive"):
        memoire.vectoriser_procedures(admission.document_id, "f" * 64, stale, limite=1)
    assert stale.textes == []

    import psycopg

    with psycopg.connect(url) as cnx:
        cnx.execute(
            "UPDATE memoire.procedure_occurrences SET debut_octets=debut_octets+1 "
            "WHERE version_id=%s",
            (admission.version_id,),
        )
    corrompu = _EmbedderPgFictif()
    with pytest.raises(ValueError, match="provenance de fragment"):
        memoire.vectoriser_procedures(admission.document_id, admission.sha256, corrompu, limite=1)
    assert corrompu.textes == []
    assert _fragment_etat(url, admission.document_id, admission.sha256) == ("pending", None, None)
