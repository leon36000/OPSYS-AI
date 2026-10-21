"""Qualification opt-in HTTP→ClientEmbeddings→PostgreSQL avec le vrai modèle local.

Exécuter seulement dans une fenêtre ROOT dédiée avec assets R35 en RAM et Docker disponible.
Cette intégration sur données fictives n'est pas un benchmark de qualité produit.
"""

from __future__ import annotations

import contextlib
import json
import math
import os
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

import pytest
from memoire.doubles import postgres_ephemere, raison_sans_docker, vider

from opsys.memoire import MemoireEntreprise
from opsys.memoire.embeddings import ClientEmbeddings

RACINE = Path(__file__).resolve().parents[1]
ACTIFS_DEFAUT = Path("/dev/shm/opsys-r35-20261002-onnx")
PYTHON_DEFAUT = ACTIFS_DEFAUT / "venv/bin/python"
TAILLE_GIB = 1024**3
RESERVE_CGROUP = 512 * 1024**2
RSS_MAX = 2 * TAILLE_GIB
MARGE_DEMARRAGE_MIN = RSS_MAX + RESERVE_CGROUP
MARGE_PG_MIN = 1024**3  # conteneur PostgreSQL plafonné à 512 MiB + réserve cgroup 512 MiB
ACTIVER = os.environ.get("OPSYS_R41_REAL_PG") == "1"
RAISON_DOCKER = raison_sans_docker() if ACTIVER else "test opt-in: OPSYS_R41_REAL_PG=1 requis"

def _cgroup_entetes() -> tuple[int, int]:
    racine = Path("/sys/fs/cgroup")
    courant = int((racine / "memory.current").read_text().strip())
    maximum_brut = (racine / "memory.max").read_text().strip()
    if maximum_brut == "max":
        raise RuntimeError("cgroup sans plafond mémoire mesurable")
    return courant, int(maximum_brut)


def _mem_available() -> int:
    for ligne in Path("/proc/meminfo").read_text().splitlines():
        if ligne.startswith("MemAvailable:"):
            return int(ligne.split()[1]) * 1024
    raise RuntimeError("MemAvailable absent")


def _lire_status_processus(pid: int) -> str | None:
    try:
        return Path(f"/proc/{pid}/status").read_text()
    except (FileNotFoundError, ProcessLookupError):
        return None


def _rss_octets(pid: int, lire_status=_lire_status_processus) -> int | None:
    """Retourne None après sortie/zombie; un processus vivant sans VmRSS reste une erreur."""
    status = lire_status(pid)
    if status is None:
        return None
    etat = None
    rss = None
    for ligne in status.splitlines():
        if ligne.startswith("State:"):
            champs = ligne.split()
            etat = champs[1] if len(champs) > 1 else None
        elif ligne.startswith("VmRSS:"):
            rss = int(ligne.split()[1]) * 1024
    if etat in {"Z", "X"}:
        return None
    if rss is not None:
        return rss
    raise RuntimeError("VmRSS du provider absent")


def _terminer_si_actif(processus: subprocess.Popen[str]) -> None:
    if processus.poll() is None:
        with contextlib.suppress(ProcessLookupError):
            processus.terminate()


def _python_venv(path: str | Path) -> Path:
    """Préserve le lien venv: le résoudre déréférence python et perd ses dépendances."""
    executable = Path(path).expanduser().absolute()
    if not executable.is_file():
        raise FileNotFoundError(f"interpréteur du venv absent: {executable}")
    return executable


def _surveiller(
    processus: subprocess.Popen[str],
    stop: threading.Event,
    erreurs: list[str],
    rss_observe: list[int],
    marge_observee: list[int],
    lire_rss=_rss_octets,
) -> None:
    while not stop.wait(0.1):
        try:
            rss = lire_rss(processus.pid)
            if rss is None:
                return
            courant, maximum = _cgroup_entetes()
            rss_observe.append(rss)
            marge_observee.append(maximum - courant)
            if rss > RSS_MAX:
                erreurs.append(f"RSS provider supérieur à 2 GiB: {rss}")
            elif maximum - courant < RESERVE_CGROUP:
                erreurs.append(f"réserve cgroup sous 512 MiB: {maximum - courant}")
            if erreurs:
                _terminer_si_actif(processus)
                return
        except RuntimeError as exc:
            erreurs.append(f"surveillance provider impossible: {exc}")
            _terminer_si_actif(processus)
            return
        except (FileNotFoundError, ProcessLookupError):
            return


def _port_libre() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _limiter_processus() -> None:
    import resource

    plafond = 3 * TAILLE_GIB
    resource.setrlimit(resource.RLIMIT_AS, (plafond, plafond))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def _attendre_sante(base: str, cle: str, processus: subprocess.Popen[str]) -> dict:
    limite = time.monotonic() + 90
    derniere_erreur = "pas encore démarré"
    while time.monotonic() < limite:
        if processus.poll() is not None:
            stderr = processus.stderr.read() if processus.stderr else ""
            raise AssertionError(f"provider a quitté ({processus.returncode}): {stderr[-2000:]}")
        try:
            req = urllib.request.Request(
                f"{base.rsplit('/v1', 1)[0]}/healthz", headers={"Authorization": f"Bearer {cle}"}
            )
            with urllib.request.urlopen(req, timeout=2) as response:
                return json.loads(response.read())
        except Exception as exc:
            derniere_erreur = type(exc).__name__
            time.sleep(0.25)
    raise TimeoutError(f"provider pas prêt après 90 s ({derniere_erreur})")


def _texte_exactement_512_tokens(python: Path, tokenizer: Path) -> str:
    programme = """import json,sys
from tokenizers import Tokenizer
t=Tokenizer.from_file(sys.argv[1])
s=''
compte=len(t.encode(s, add_special_tokens=True).ids)
morceaux=('a',' le',' x','-test',' bleu','inspection',' 1',' foyer')
for _ in range(10000):
    for morceau in morceaux:
        candidat=s+morceau
        if len(candidat)>20000:
            break
        n=len(t.encode(candidat, add_special_tokens=True).ids)
        if n == 512:
            print(json.dumps(candidat, ensure_ascii=False))
            raise SystemExit(0)
        if compte < n < 512:
            s,compte=candidat,n
            break
    else:
        break
raise SystemExit('impossible de construire exactement 512 tokens')
"""
    resultat = subprocess.run(
        [str(python), "-c", programme, str(tokenizer)], capture_output=True, text=True, timeout=30, check=False
    )
    if resultat.returncode != 0:
        raise AssertionError(resultat.stderr.strip() or resultat.stdout.strip())
    return json.loads(resultat.stdout)


@pytest.mark.skipif(not ACTIVER or RAISON_DOCKER is not None, reason=RAISON_DOCKER or "opt-in requis")
def test_bge_local_reel_http_client_pg_512_tokens_avec_budget_borne(record_property):
    actifs = Path(os.environ.get("OPSYS_R41_ASSETS_DIR", ACTIFS_DEFAUT)).resolve(strict=True)
    python = _python_venv(os.environ.get("OPSYS_R41_PYTHON", PYTHON_DEFAUT))
    tokenizer = actifs / "tokenizer.json"
    modele = actifs / "model-int8.onnx"
    cle = os.environ.get("OPSYS_EMBEDDINGS_CLE", "")
    assert len(cle) >= 24, "OPSYS_EMBEDDINGS_CLE doit être un jeton de test privé d'au moins 24 caractères"
    assert tokenizer.is_file() and modele.is_file()

    courant, maximum = _cgroup_entetes()
    marge_initiale = maximum - courant
    disponible_hote = _mem_available()
    assert marge_initiale >= MARGE_DEMARRAGE_MIN, (
        f"marge initiale cgroup sous RSS provider 2 GiB + réserve 512 MiB: {marge_initiale}"
    )
    assert disponible_hote >= MARGE_DEMARRAGE_MIN, f"MemAvailable hôte sous 2,5 GiB: {disponible_hote}"
    port = _port_libre()
    environnement = dict(os.environ)
    environnement.update(
        {
            "PYTHONPATH": str(RACINE / "src"),
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
    processus = subprocess.Popen(
        [str(python), "-m", "opsys.memoire.serveur_embeddings_local"],
        cwd=RACINE,
        env=environnement,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        preexec_fn=_limiter_processus,
    )
    stop = threading.Event()
    erreurs: list[str] = []
    rss_observe: list[int] = []
    marge_observee: list[int] = []
    surveillant = threading.Thread(
        target=_surveiller, args=(processus, stop, erreurs, rss_observe, marge_observee), daemon=True
    )
    surveillant.start()
    base = f"http://127.0.0.1:{port}/v1"
    try:
        sante = _attendre_sante(base, cle, processus)
        assert sante["model"] == "BAAI/bge-m3"
        assert sante["dimension"] == 1024
        assert sante["model_sha256"] == "0826f8c1ab9edf1801db86c61919d4d108e8bfc0b809ec823ad366882ff0b77d"
        assert sante["tokenizer_sha256"] == "6710678b12670bc442b99edc952c4d996ae309a7020c1fa0096dd245c2faf790"

        texte512 = _texte_exactement_512_tokens(python, tokenizer)
        requete = urllib.request.Request(
            f"{base}/embeddings",
            data=json.dumps({"model": "BAAI/bge-m3", "input": texte512}).encode("utf-8"),
            headers={"Authorization": f"Bearer {cle}", "Content-Type": "application/json"},
            method="POST",
        )
        debut = time.monotonic()
        with urllib.request.urlopen(requete, timeout=30) as response:
            sortie512 = json.loads(response.read())
        duree512_ms = (time.monotonic() - debut) * 1000
        assert sortie512["usage"]["prompt_tokens"] == 512
        assert len(sortie512["data"][0]["embedding"]) == 1024

        courant_pg, maximum_pg = _cgroup_entetes()
        assert maximum_pg - courant_pg >= MARGE_PG_MIN, (
            "marge cgroup avant PostgreSQL sous conteneur PG 512 MiB + réserve 512 MiB"
        )

        with postgres_ephemere(stockage_en_memoire=True) as url_pg:
            memoire = MemoireEntreprise(url_pg)
            memoire.migrer()
            vider(url_pg)
            client = ClientEmbeddings(
                base_url=base, modele="BAAI/bge-m3", cle=cle, local=True, taille_lot=1, delai_s=30
            )
            texte = "Fragment fictif R41 : procédure de pose des solins cuivre avant inspection du toit."
            debut = time.monotonic()
            vecteur = client.plonger([texte])[0]
            insertion_ms = (time.monotonic() - debut) * 1000
            assert len(vecteur) == 1024
            assert all(math.isfinite(value) for value in vecteur)
            identifiant = memoire.ajouter(
                texte,
                {
                    "departement": "m10-memoire",
                    "portee": "procedures",
                    "source": "fictif:r41:fragment-1",
                    "sensibilite": "interne",
                    "sujets": [],
                },
                vecteur,
            )
            vecteur_requete = client.plonger(["Comment inspecter les solins en cuivre?"])[0]
            resultat = memoire.rechercher(
                "Comment inspecter les solins en cuivre?", vecteur_requete, 5, {"portee": "procedures"}
            )
            assert resultat.mode == "hybride"
            assert resultat.resultats and resultat.resultats[0].fragment_id == identifiant
            assert resultat.resultats[0].source == "fictif:r41:fragment-1"

        courant_final, maximum_final = _cgroup_entetes()
        rss_final = _rss_octets(processus.pid)
        rss_mesures = [*rss_observe, *([] if rss_final is None else [rss_final])]
        assert rss_mesures, "aucune mesure RSS disponible pour le provider"
        rss_max = max(rss_mesures)
        assert rss_max <= RSS_MAX
        marge_min = min(marge_observee, default=maximum_final - courant_final)
        assert marge_min >= RESERVE_CGROUP
        assert not erreurs, "; ".join(erreurs)
        record_property("r41_modele_sha256", "0826f8c1ab9edf1801db86c61919d4d108e8bfc0b809ec823ad366882ff0b77d")
        record_property("r41_tokenizer_sha256", "6710678b12670bc442b99edc952c4d996ae309a7020c1fa0096dd245c2faf790")
        record_property("r41_exact_512_tokens_ms_observe", round(duree512_ms, 2))
        record_property("r41_client_embedding_insert_ms_observe", round(insertion_ms, 2))
        record_property("r41_provider_rss_max_bytes", rss_max)
        record_property("r41_cgroup_headroom_min_bytes", min(marge_min, maximum_final - courant_final))
    finally:
        stop.set()
        surveillant.join(2)
        if processus.poll() is None:
            processus.terminate()
        try:
            processus.wait(timeout=10)
        except subprocess.TimeoutExpired:
            processus.kill()
            processus.wait(timeout=5)
        if erreurs:
            pytest.fail("surveillance mémoire R41: " + "; ".join(erreurs))


def test_python_venv_preserve_symlink(tmp_path):
    """Le lien du venv doit rester le chemin passé au sous-processus."""
    executable = tmp_path / "venv" / "bin" / "python"
    executable.parent.mkdir(parents=True)
    cible = tmp_path / "python-base"
    cible.write_text("placeholder")
    executable.symlink_to(cible)
    resultat = _python_venv(executable)
    assert resultat == executable
    assert resultat.is_symlink()


def test_rss_absent_sur_zombie_ou_processus_termine_ne_leve_pas():
    def status_zombie(pid):
        return "State:\tZ (zombie)\nVmRSS:\t2048 kB\n"

    assert _rss_octets(123, status_zombie) is None
    assert _rss_octets(123, lambda pid: None) is None


def test_rss_absent_sur_processus_vivant_reste_une_erreur():
    def status_vivant(pid):
        return "State:\tR (running)\n"

    with pytest.raises(RuntimeError, match="VmRSS du provider absent"):
        _rss_octets(123, status_vivant)


def test_surveillance_rss_vivant_invalide_enregistre_erreur_et_arrete_provider():
    class FauxStop:
        def wait(self, delai):
            return False

    class FauxProcessus:
        pid = 123
        termine = False

        def poll(self):
            return None if not self.termine else 1

        def terminate(self):
            self.termine = True

    def rss_invalide(pid):
        raise RuntimeError("VmRSS du provider absent")

    processus = FauxProcessus()
    erreurs = []
    _surveiller(processus, FauxStop(), erreurs, [], [], lire_rss=rss_invalide)
    assert erreurs == ["surveillance provider impossible: VmRSS du provider absent"]
    assert processus.termine
