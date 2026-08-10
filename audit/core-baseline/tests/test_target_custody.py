"""C00-001 — Tests RED→GREEN pour geler le dépôt, la branche et le worktree."""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

# parents[0]=tests parents[1]=core-baseline parents[2]=audit parents[3]=racine
# du worktree — mesuré (offset d'un cran trouvé en revue avant soumission :
# parents[2] pointait sur audit/, pas la racine ; les tests passaient quand
# même par coïncidence, git -C <sous-répertoire> + chemins relatifs
# s'annulant, mais TargetCustody.worktree mentait sur le chemin réel).
WORKTREE = Path(__file__).resolve().parents[3]
BASE = Path(__file__).resolve().parent.parent

# Import custody depuis audit/core-baseline
sys.path.insert(0, str(BASE))
import custody
from custody import (
    BrancheInterdite,
    WorktreeSale,
    EcritureViaSymlinkRefusee,
    BlockedWrongRepository,
    TargetCustody,
    geler,
    inventorier,
    verifier_inventaire,
    _chemin_depuis_ligne_porcelain,
    _ecrire_sans_suivre_symlink,
    _produire_sorties,
)

# ---------------------------------------------------------------------------
# 3 cas RED obligatoires (noms imposés)
# ---------------------------------------------------------------------------

def test_geler_le_d_p_t_la_branche_et_le_worktree_1():
    """Refuser main/master (et HEAD détaché) comme branche de gel — lever une exception NOMMÉE."""
    for branche in ("main", "master", "HEAD", "Main", "MASTER", "head"):
        with pytest.raises(BrancheInterdite):
            geler(WORKTREE, branche_observee=branche, statut_observe=[])
    # Une branche légitime ne doit PAS lever
    # On utilise un statut vide pour isoler le test de branche
    garde = geler(WORKTREE, branche_observee="opsys-core/task/c00-001-geler-le-depot-la-branche-et-le-worktree", statut_observe=[])
    assert garde.branch == "opsys-core/task/c00-001-geler-le-depot-la-branche-et-le-worktree"
    # Vérifie que supprimer la garde ferait passer main (RED proof)
    # Si la garde BrancheInterdite était commentée, ce test échouerait car aucune exception ne serait levée


def test_geler_le_d_p_t_la_branche_et_le_worktree_2():
    """Refuser un worktree sale dont AU MOINS UN chemin modifié n'est PAS sur allowlist explicite."""
    # Cas 1 : un chemin sale non allowlisté doit lever WorktreeSale
    with pytest.raises(WorktreeSale) as exc:
        geler(WORKTREE, branche_observee="feature/x", statut_observe=["1 M. N... 100644 100644 100644 abc def audit/core-baseline/TARGET.json"], chemins_autorises=())
    assert "audit/core-baseline/TARGET.json" in str(exc.value)

    # Cas 2 : allowlist explicite par chemins nommés un par un — tolère exactement ce chemin
    garde = geler(WORKTREE, branche_observee="feature/x", statut_observe=["1 M. N... 100644 100644 100644 abc def audit/core-baseline/TARGET.json"], chemins_autorises=("audit/core-baseline/TARGET.json",))
    assert garde.dirty is True
    assert "audit/core-baseline/TARGET.json" in garde.chemins_sales_tolerés

    # Cas 3 : motif large ne doit PAS être accepté — allowlist exige des chemins exacts
    with pytest.raises(WorktreeSale):
        geler(WORKTREE, branche_observee="feature/x", statut_observe=["1 M. N... 100644 100644 100644 abc def audit/core-baseline/TARGET.json"], chemins_autorises=("audit/*",))

    # Cas 4 : deux chemins sales, un seul allowlisté → doit refuser (AU MOINS UN non allowlisté)
    with pytest.raises(WorktreeSale) as exc2:
        geler(WORKTREE, branche_observee="feature/x", statut_observe=[
            "1 M. N... 100644 100644 100644 abc def audit/core-baseline/TARGET.json",
            "1 M. N... 100644 100644 100644 abc def README.md",
        ], chemins_autorises=("audit/core-baseline/TARGET.json",))
    assert "README.md" in str(exc2.value)

    # Cas 5 : chemin avec espaces — maxsplit=8 doit préserver le chemin complet
    ligne_avec_espace = "1 M. N... 100644 100644 100644 abc def attacker_prefix audit/core-baseline/TARGET.json"
    chemin = _chemin_depuis_ligne_porcelain(ligne_avec_espace)
    assert chemin == "attacker_prefix audit/core-baseline/TARGET.json"
    # Ce chemin complet n'est PAS dans l'allowlist qui ne contient que TARGET.json → doit lever
    with pytest.raises(WorktreeSale):
        geler(WORKTREE, branche_observee="feature/x", statut_observe=[ligne_avec_espace], chemins_autorises=("audit/core-baseline/TARGET.json",))


def test_geler_le_d_p_t_la_branche_et_le_worktree_3(tmp_path):
    """Détecter un hash d'inventaire modifié — dans LES DEUX SENS."""
    # On crée un mini dépôt temporaire pour tester inventorier/verifier_inventaire en isolation
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "test-branch"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test.test"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True)
    (repo / "a.txt").write_text("hello", encoding="utf-8")
    (repo / "b.txt").write_text("world", encoding="utf-8")
    subprocess.run(["git", "add", "a.txt", "b.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    inv = inventorier(repo)
    assert len(inv) == 2
    # Aucun écart sur inventaire fidèle
    assert verifier_inventaire(repo, inv) == []

    # Sens 1 : fichier dont le contenu a changé (empreinte différente)
    (repo / "a.txt").write_text("HELLO MODIFIED", encoding="utf-8")
    ecarts = verifier_inventaire(repo, inv)
    assert any(e["chemin"] == "a.txt" and "empreinte" in e["motif"] for e in ecarts), f"écarts={ecarts}"

    # Restaurer a.txt
    (repo / "a.txt").write_text("hello", encoding="utf-8")

    # Sens 2 : fichier apparu qui n'était pas dans l'inventaire déclaré
    (repo / "c.txt").write_text("new file", encoding="utf-8")
    subprocess.run(["git", "add", "c.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "add c"], cwd=repo, check=True, capture_output=True)
    ecarts2 = verifier_inventaire(repo, inv)
    assert any(e["chemin"] == "c.txt" and "absent de l'inventaire" in e["motif"] for e in ecarts2), f"écarts2={ecarts2}"

    # Sens 3 : fichier disparu (présent dans inventaire, absent du dépôt)
    subprocess.run(["git", "rm", "b.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "rm b"], cwd=repo, check=True, capture_output=True)
    ecarts3 = verifier_inventaire(repo, inv)
    assert any(e["chemin"] == "b.txt" and "absent du dépôt" in e["motif"] for e in ecarts3), f"écarts3={ecarts3}"


# ---------------------------------------------------------------------------
# Tests complémentaires : garde symlink, garde GitHub, production des 5 sorties
# ---------------------------------------------------------------------------

class TestWorktreePropreAvantProduction:
    """Vérifie la propreté du worktree AVANT que la fixture custody_produite ne s'exécute."""

    def test_worktree_propre_avant_production(self):
        # Le worktree doit être propre au moment du collect (avant fixture)
        # On vérifie que geler() avec l'état réel ne lève pas WorktreeSale
        # (les fichiers non suivis comme __pycache__ ne sont pas dans porcelain v2 type 1)
        branche = subprocess.run(["git", "-C", str(WORKTREE), "rev-parse", "--abbrev-ref", "HEAD"], text=True, capture_output=True).stdout.strip()
        # Si on est sur la bonne branche, geler doit réussir
        assert branche == "opsys-core/task/c00-001-geler-le-depot-la-branche-et-le-worktree"
        garde = geler(WORKTREE, branche_observee=branche)
        assert garde.branch == branche


class TestProductionSorties:
    """Exerce la PRODUCTION des 5 sorties — dépend de la fixture custody_produite."""

    @pytest.fixture(scope="class", autouse=True)
    def custody_produite(self):
        sys.path.insert(0, str(BASE))
        try:
            import custody as _c
            _c._produire_sorties(WORKTREE, BASE)
        finally:
            if str(BASE) in sys.path:
                sys.path.remove(str(BASE))
        yield

    def test_target_json_existe_et_coherent(self):
        p = BASE / "TARGET.json"
        assert p.is_file() and not p.is_symlink()
        data = json.loads(p.read_text(encoding="utf-8"))
        assert "commit" in data and len(data["commit"]) == 40
        assert "tree" in data and len(data["tree"]) == 40
        assert data["branch"] == "opsys-core/task/c00-001-geler-le-depot-la-branche-et-le-worktree"
        assert "fichiers_inventories" in data

    def test_git_refs_existe(self):
        p = BASE / "GIT-REFS.txt"
        assert p.is_file() and not p.is_symlink()
        txt = p.read_text(encoding="utf-8")
        assert "commit" in txt
        assert "[refs]" in txt

    def test_file_inventory_existe(self):
        p = BASE / "FILE-INVENTORY.csv"
        assert p.is_file() and not p.is_symlink()
        with p.open(encoding="utf-8") as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames == ["chemin", "sha256", "taille"]
            rows = list(reader)
            assert len(rows) > 0
            for r in rows:
                assert len(r["sha256"]) == 64

    def test_github_repository_json(self):
        p = BASE / "GITHUB-REPOSITORY.json"
        assert p.is_file() and not p.is_symlink(), "GITHUB-REPOSITORY.json manquant"
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data.get("full_name") == "leon36000/OPSYS-AI"
        assert data.get("private") is True
        assert data.get("visibility") == "private"
        assert "branch_protection" in data or "branch_protection_error" in data

    def test_aucun_secret_dans_les_sorties_github(self):
        """gitleaks a trouvé `temp_clone_token` (jeton actif, non vide) dans
        un dump `_raw` de `gh api repos/...` — corrigé par allowlist stricte.
        Ce test verrouille l'absence de dump brut, pas seulement ce champ
        nommé : un `_raw`/`raw` réintroduit exposerait le PROCHAIN champ
        sensible que GitHub ajoute, que ce test ne connaît pas encore."""
        for nom in ("GITHUB-REPOSITORY.json", "GITHUB-AUTH.json"):
            data = json.loads((BASE / nom).read_text(encoding="utf-8"))
            interdits = {"_raw", "raw", "token", "temp_clone_token"}
            trouves = interdits & set(data.keys())
            assert not trouves, f"{nom} : clé(s) interdite(s) trouvée(s) {trouves}"

    def test_github_auth_json(self):
        p = BASE / "GITHUB-AUTH.json"
        assert p.is_file() and not p.is_symlink(), "GITHUB-AUTH.json manquant"
        data = json.loads(p.read_text(encoding="utf-8"))
        assert data.get("login") == "leon36000"
        assert data.get("id") == 216249790


def test_ecriture_via_symlink_refusee(tmp_path):
    target = tmp_path / "real.txt"
    target.write_text("real", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(target)
    with pytest.raises(EcritureViaSymlinkRefusee):
        _ecrire_sans_suivre_symlink(link, "evil")


def test_github_auth_garde_login(tmp_path, monkeypatch):
    """Si login != leon36000, _produire_sorties doit lever BlockedWrongRepository AVANT d'écrire."""
    import custody as c
    orig_gh = c._gh_json
    orig_git = c._git

    def fake_gh(args):
        if args == ["api", "user"]:
            return {"login": "attacker", "id": 999, "node_id": "U_fake"}
        if args == ["api", "repos/leon36000/OPSYS-AI"]:
            return {"id": 1, "node_id": "R_fake", "full_name": "leon36000/OPSYS-AI", "default_branch": "main", "private": True, "visibility": "private"}
        return {}

    def fake_git(worktree, *a, check=True):
        return "ok"

    monkeypatch.setattr(c, "_gh_json", fake_gh)
    # gh repo view doit réussir pour atteindre la garde login
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: type("R", (), {"returncode": 0, "stdout": '{"nameWithOwner":"leon36000/OPSYS-AI"}', "stderr": ""})())

    with pytest.raises(BlockedWrongRepository, match="login"):
        c._produire_sorties(tmp_path, tmp_path / "out")
    # Vérifie qu'aucun fichier n'a été écrit
    assert not (tmp_path / "out" / "TARGET.json").exists()
    assert not (tmp_path / "out" / "GITHUB-AUTH.json").exists()
