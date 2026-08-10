"""C00-001 — Tests RED→GREEN pour geler le dépôt, la branche et le worktree."""
from __future__ import annotations

import csv
import errno
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
    _verifier_confinement,
    _sha256_par_blocs,
    _ouverture_atomique_confinee,
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
            # DeepSeek-V4-Pro, MAJEURE, mesurée vraie (revue tour 4) : le tri
            # déterministe avait disparu au refactor CSV du tour 3. Ce test
            # lit la SORTIE RÉELLE produite par _produire_sorties() — pas la
            # fonction utilitaire en isolation — pour prouver l'ordre au
            # vrai point d'entrée, même motif que les 2 trous déjà fermés.
            chemins = [r["chemin"] for r in rows]
            assert chemins == sorted(chemins), "FILE-INVENTORY.csv n'est pas trié par chemin"

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
        _ecrire_sans_suivre_symlink(link, "evil", tmp_path)


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


# ---------------------------------------------------------------------------
# Tour 2 — revue scellée : 1 CRITIQUE (Qwen3.7-Max) + 2 MAJEURE (Gemini-3.1-Pro)
# mesurées réelles, corrigées. Tests écrits par l'Orchestrateur (vérification,
# pas implémentation) car le codeur crew n'a pas livré cette partie du tour.
# ---------------------------------------------------------------------------

def test_confinement_refuse_un_parent_symlinke(tmp_path):
    """Reproduit EXACTEMENT le scénario de Qwen3.7-Max (CRITIQUE, revue
    scellée) : `is_symlink()` sur le seul composant final ne voit pas un
    PARENT symlinké. `audit/` -> répertoire hors dépôt ; `secret.txt.is_symlink()`
    renvoie False alors que le contenu lu est bien celui de la cible externe."""
    coffre = tmp_path / "coffre"
    coffre.mkdir()
    (coffre / "secret.txt").write_text("SECRET HORS DEPOT", encoding="utf-8")
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    (worktree / "audit").symlink_to(coffre)
    cible = worktree / "audit" / "secret.txt"

    # Le symptôme que la garde precedente laissait passer :
    assert cible.is_symlink() is False, "précondition du test : la feuille n'est pas un symlink"
    assert cible.read_bytes() == b"SECRET HORS DEPOT", "précondition : le contenu externe est bien lisible"

    # La garde de confinement doit lever malgré tout :
    with pytest.raises(EcritureViaSymlinkRefusee, match="confinement"):
        _verifier_confinement(cible, worktree)


def test_inventorier_refuse_un_fichier_tracke_derriere_un_parent_symlinke(tmp_path):
    """Ferme le trou que le test précédent NE couvre PAS : tester
    `_verifier_confinement` en isolation ne prouve pas qu'`inventorier()`
    L'APPELLE réellement. Mesuré par mutation (revue post-tour-2, avant
    soumission) : retirer l'appel à `_verifier_confinement` À L'INTÉRIEUR
    d'`inventorier()` ne faisait échouer AUCUN test existant — ce test ferme
    ce trou en exerçant le VRAI point d'entrée, pas seulement l'utilitaire."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "b"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "audit").mkdir()
    (repo / "audit" / "fichier.txt").write_text("contenu tracké", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    # Tampering post-checkout : le répertoire tracké `audit/` est remplacé
    # par un symlink pointant vers un répertoire HORS du dépôt, qui contient
    # un fichier de même nom mais de contenu différent.
    coffre = tmp_path / "coffre_externe"
    coffre.mkdir()
    (coffre / "fichier.txt").write_text("contenu FALSIFIE hors dépôt", encoding="utf-8")
    import shutil
    shutil.rmtree(repo / "audit")
    (repo / "audit").symlink_to(coffre)

    with pytest.raises(EcritureViaSymlinkRefusee, match="confinement"):
        inventorier(repo)


def test_confinement_accepte_un_chemin_legitime(tmp_path):
    """Contre-exemple obligatoire : un chemin normal, sans aucun symlink,
    ne doit PAS être refusé — sinon la garde bloquerait tout, pas seulement
    l'attaque qu'elle cible."""
    (tmp_path / "sous_dir").mkdir()
    fichier = tmp_path / "sous_dir" / "normal.txt"
    fichier.write_text("rien de suspect", encoding="utf-8")
    resolu = _verifier_confinement(fichier, tmp_path)
    assert resolu == fichier.resolve()


def test_ecrire_sans_suivre_symlink_exige_racine(tmp_path):
    """`racine` est un paramètre positionnel OBLIGATOIRE depuis la revue
    tour 2 — l'appeler sans lui doit être un TypeError à l'appel, pas une
    garde silencieusement contournable. Ferme le repli `racine=None` retiré
    (comparer un chemin résolu à SON PROPRE PARENT résolu est tautologiquement
    toujours vrai — mesuré, ne défendait rien dans le scénario exact ci-dessus)."""
    with pytest.raises(TypeError):
        _ecrire_sans_suivre_symlink(tmp_path / "x.txt", "contenu")  # type: ignore[call-arg]


def test_inventorier_detecte_le_retargeting_d_un_symlink(tmp_path):
    """Un symlink suivi par git EST un objet du dépôt (son contenu = la
    chaîne cible). L'ignorer (comportement retiré) rend `verifier_inventaire()`
    aveugle si sa cible change. Correctif : hacher `os.readlink()`."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "b"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "cible_a.txt").write_text("a", encoding="utf-8")
    (repo / "cible_b.txt").write_text("b", encoding="utf-8")
    (repo / "lien.txt").symlink_to(repo / "cible_a.txt")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    inv = inventorier(repo)
    entree_lien = next((e for e in inv if e["chemin"] == "lien.txt"), None)
    assert entree_lien is not None, "le symlink doit apparaître dans l'inventaire (jamais ignoré)"
    assert verifier_inventaire(repo, inv) == [], "inventaire fidèle : aucun écart"

    # Re-cible le lien vers un autre fichier (retargeting) :
    (repo / "lien.txt").unlink()
    (repo / "lien.txt").symlink_to(repo / "cible_b.txt")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "retarget"], cwd=repo, check=True, capture_output=True)

    ecarts = verifier_inventaire(repo, inv)
    assert any(e["chemin"] == "lien.txt" and "empreinte" in e["motif"] for e in ecarts), (
        f"le retargeting du symlink n'a pas été détecté ; écarts={ecarts}"
    )


def test_hachage_par_blocs_identique_a_read_bytes(tmp_path):
    """`_sha256_par_blocs` (jamais tout le fichier en mémoire) doit produire
    EXACTEMENT le même hash que `hashlib.sha256(read_bytes())` — non-régression
    de correction, pas seulement de performance."""
    fichier = tmp_path / "gros.bin"
    contenu = bytes(range(256)) * 5000  # 1.28 Mo, traverse plusieurs blocs de 1 Mo
    fichier.write_bytes(contenu)

    hash_par_blocs, taille = _sha256_par_blocs(fichier, taille_bloc=1_048_576)
    hash_read_bytes = hashlib.sha256(fichier.read_bytes()).hexdigest()

    assert hash_par_blocs == hash_read_bytes, "hash divergent entre les deux méthodes"
    assert taille == len(contenu)


def test_protection_de_branche_suit_default_branch(tmp_path, monkeypatch):
    """La branche par défaut codée en dur ('main') a été retirée — l'appel
    `gh api .../branches/<branche>/protection` doit utiliser la VRAIE
    default_branch du dépôt, pas un littéral."""
    import custody as c

    appels_gh = []

    def fake_gh(args):
        appels_gh.append(args)
        if args == ["api", "user"]:
            return {"login": "leon36000", "id": 1, "node_id": "U_x"}
        if args == ["api", "repos/leon36000/OPSYS-AI"]:
            return {"id": 1, "node_id": "R_x", "full_name": "leon36000/OPSYS-AI",
                     "default_branch": "develop", "private": True, "visibility": "private"}
        if args[0] == "api" and "protection" in args[1]:
            return {"ok": True}
        return {}

    monkeypatch.setattr(c, "_gh_json", fake_gh)
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: type(
        "R", (), {"returncode": 0, "stdout": '{"nameWithOwner":"leon36000/OPSYS-AI"}', "stderr": ""})())
    monkeypatch.setattr(c, "_git", lambda *a, **kw: "b\n")
    monkeypatch.setattr(c, "geler", lambda *a, **kw: TargetCustody(
        commit="c" * 40, tree="t" * 40, branch="b", worktree=str(tmp_path), dirty=False))
    monkeypatch.setattr(c, "inventorier", lambda *a, **kw: [])

    c._produire_sorties(tmp_path, tmp_path / "out")

    appel_protection = next((a for a in appels_gh if a[0] == "api" and "protection" in a[1]), None)
    assert appel_protection is not None, "aucun appel de protection de branche capturé"
    assert "branches/develop/protection" in appel_protection[1], (
        f"la branche par défaut réelle (develop) n'est pas utilisée : {appel_protection[1]}"
    )
    assert "branches/main/protection" not in appel_protection[1]


# ---------------------------------------------------------------------------
# Tour 3 — revue scellée : 1 CRITIQUE (Gemini) + 3 MAJEURE (Gemini + convergence
# DeepSeek/Gemini/Qwen sur l'encodage) mesurées réelles, corrigées.
# ---------------------------------------------------------------------------

def test_confinement_via_sortie_dir_refuse_le_scenario_reel(tmp_path):
    """Le CRITIQUE du tour 3 (Gemini-3.1-Pro, mesuré vrai) : le correctif du
    CRITIQUE du tour 2 (racine obligatoire) ne suffisait pas — les VRAIS
    sites d'appel dans _produire_sorties() passaient `sortie_dir`, qui EST
    le parent immédiat de chaque fichier écrit. Ce test exerce
    `_ecrire_sans_suivre_symlink` avec le racine RÉEL désormais utilisé
    (`worktree`, pas `sortie_dir`) sur le scénario exact : `sortie_dir`
    lui-même symlinké hors du worktree."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "b"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "x.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "i"], cwd=repo, check=True, capture_output=True)

    coffre = tmp_path / "coffre_externe"
    coffre.mkdir()
    sortie_dir_externe = coffre / "sortie"
    sortie_dir_externe.mkdir()
    (repo / "audit_out").symlink_to(sortie_dir_externe)

    with pytest.raises(EcritureViaSymlinkRefusee, match="confinement"):
        _ecrire_sans_suivre_symlink((repo / "audit_out") / "TARGET.json", "contenu", repo)


def test_ecriture_est_idempotente_sur_fichier_regulier_preexistant(tmp_path):
    """DeepSeek-V4-Pro + Gemini-3.1-Pro, MAJEURE, mesurée vraie (revue tour
    3) : une première version utilisait O_EXCL, qui cassait l'idempotence —
    une ré-exécution sur une sortie déjà produite plantait au lieu
    d'écraser, changement de contrat non documenté. O_TRUNC (sans O_EXCL)
    restaure l'écrasement d'un fichier RÉGULIER préexistant, tout en
    conservant le refus d'un symlink (O_NOFOLLOW seul y suffit, voir
    test_symlink_a_la_feuille_est_toujours_refuse_sans_o_excl)."""
    cible = tmp_path / "reproductible.txt"
    _ecrire_sans_suivre_symlink(cible, "première écriture", tmp_path)
    _ecrire_sans_suivre_symlink(cible, "seconde écriture, plus longue", tmp_path)
    assert cible.read_text(encoding="utf-8") == "seconde écriture, plus longue"


def test_symlink_a_la_feuille_est_toujours_refuse_sans_o_excl(tmp_path):
    """O_NOFOLLOW SEUL (sans O_EXCL) suffit à refuser un symlink à la
    feuille — mesuré directement : `errno.ELOOP`. Ce test isole cette
    propriété du reste (confinement, idempotence)."""
    cible_reelle = tmp_path / "ailleurs.txt"
    cible_reelle.write_text("contenu externe", encoding="utf-8")
    lien = tmp_path / "lien.txt"
    lien.symlink_to(cible_reelle)
    with pytest.raises(EcritureViaSymlinkRefusee):
        _ecrire_sans_suivre_symlink(lien, "tentative via le lien", tmp_path)
    assert cible_reelle.read_text(encoding="utf-8") == "contenu externe", (
        "le fichier externe a été modifié à travers le symlink malgré le refus attendu"
    )


def test_ecriture_normale_reussit_toujours(tmp_path):
    """Contre-exemple obligatoire : un chemin normal, sans rien de
    préexistant ni de symlink, doit continuer à s'écrire avec succès."""
    cible = tmp_path / "nouveau.txt"
    _ecrire_sans_suivre_symlink(cible, "contenu normal", tmp_path)
    assert cible.read_text(encoding="utf-8") == "contenu normal"


def test_toctou_composant_intermediaire_ferme_apres_ouverture(tmp_path):
    """Convergence CRITIQUE ×3 (Qwen3.7-Max tour 3 ; DeepSeek-V4-Pro +
    Gemini-3.1-Pro tour 4, mesurée vraie) : une PREMIÈRE correction
    (revérifier via /proc/self/fd APRÈS os.open(..., O_CREAT, ...)) fermait
    la lecture/écriture de contenu mais PAS la création elle-même — Gemini
    a donné l'exemple concret de /etc/nologin (dont la seule EXISTENCE,
    même vide, bloque les connexions) : un déni de service réel, pas un
    "résidu acceptable". La réécriture par marche `dir_fd` composant par
    composant refuse AVANT toute création — ce test exige maintenant AUCUN
    fichier, pas seulement "aucun contenu"."""
    racine = tmp_path / "worktree"
    racine.mkdir()
    coffre = tmp_path / "coffre_externe"
    coffre.mkdir()
    (racine / "sous_dir").symlink_to(coffre)
    cible = racine / "sous_dir" / "sortie.txt"

    with pytest.raises(EcritureViaSymlinkRefusee, match="composant intermédiaire"):
        _ouverture_atomique_confinee(cible, racine)
    assert list(coffre.iterdir()) == [], (
        "un fichier (même vide) a été créé dans le coffre externe malgré le refus "
        "attendu AVANT toute création — régression du déni de service /etc/nologin"
    )


def test_toctou_intermediaire_ne_detruit_pas_un_contenu_externe_preexistant(tmp_path):
    """Contre-exemple obligatoire du test précédent : un fichier externe
    PRÉEXISTANT (pas seulement un chemin vide) au bout du composant
    intermédiaire compromis ne doit ni être créé À NOUVEAU, ni tronqué, ni
    modifié de quelque façon que ce soit."""
    racine = tmp_path / "worktree"
    racine.mkdir()
    coffre = tmp_path / "coffre_externe"
    coffre.mkdir()
    cible_preexistante = coffre / "sortie.txt"
    cible_preexistante.write_text("contenu externe légitime et précieux", encoding="utf-8")
    (racine / "sous_dir").symlink_to(coffre)
    cible = racine / "sous_dir" / "sortie.txt"

    with pytest.raises(EcritureViaSymlinkRefusee, match="composant intermédiaire"):
        _ouverture_atomique_confinee(cible, racine)

    assert cible_preexistante.read_text(encoding="utf-8") == "contenu externe légitime et précieux", (
        "le contenu externe préexistant a été détruit malgré le refus attendu"
    )


def test_permission_refusee_sur_composant_intermediaire_nest_pas_requalifiee(tmp_path):
    """Qwen3.7-Max, MINEURE, mesurée vraie : une erreur système RÉELLE
    (permission refusée sur un répertoire intermédiaire légitime, PAS un
    symlink) ne doit pas être requalifiée en refus de symlink — sinon les
    logs de sécurité confondent un problème de permissions avec une
    attaque. Utilise un VRAI répertoire sans droit d'exécution (`chmod
    000`), pas un mock — teste le comportement du narrowing errno réel
    (ENOTDIR/ELOOP uniquement) plutôt qu'un os.open entièrement remplacé,
    qui ne testait en réalité que le tout premier appel de la fonction."""
    racine = tmp_path / "worktree"
    racine.mkdir()
    sous_dir = racine / "prive"
    sous_dir.mkdir()
    cible = sous_dir / "sortie.txt"
    sous_dir.chmod(0o000)
    try:
        with pytest.raises(OSError) as exc:
            _ouverture_atomique_confinee(cible, racine)
        assert not isinstance(exc.value, EcritureViaSymlinkRefusee), (
            "une erreur de permission sur un VRAI répertoire a été requalifiée "
            "en refus de symlink"
        )
        assert exc.value.errno == errno.EACCES
    finally:
        # Restaurer les permissions AVANT que pytest ne tente de nettoyer
        # tmp_path — sinon la suppression du répertoire échoue elle-même.
        sous_dir.chmod(0o755)


def test_produire_sorties_refuse_reellement_sortie_dir_symlinke(tmp_path, monkeypatch):
    """Ferme le trou que `test_confinement_via_sortie_dir_refuse_le_scenario_reel`
    NE couvre PAS : appeler `_ecrire_sans_suivre_symlink` directement avec la
    bonne racine ne prouve pas que `_produire_sorties()` (le VRAI point
    d'entrée) l'utilise correctement. Mesuré par mutation avant soumission :
    remettre `sortie_dir` au lieu de `worktree` sur UN SEUL site d'appel
    (TARGET.json) ne faisait échouer aucun test existant. Ce test appelle
    `_produire_sorties()` de bout en bout avec un `sortie_dir` symlinké hors
    du worktree."""
    import custody as c

    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "b"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "x.txt").write_text("x", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "i"], cwd=repo, check=True, capture_output=True)

    coffre = tmp_path / "coffre_externe"
    coffre.mkdir()  # sortie_dir pointera ici, existe déjà donc mkdir(exist_ok=True) ne le recrée pas

    def fake_gh(args):
        if args == ["api", "user"]:
            return {"login": "leon36000", "id": 1, "node_id": "U_x"}
        if args == ["api", "repos/leon36000/OPSYS-AI"]:
            return {"id": 1, "node_id": "R_x", "full_name": "leon36000/OPSYS-AI",
                     "default_branch": "main", "private": True, "visibility": "private"}
        return {"ok": True}

    monkeypatch.setattr(c, "_gh_json", fake_gh)

    # subprocess.run global mock trop risqué ici (geler()/inventorier() en
    # dépendent réellement pour git) : mocker seulement `gh repo view`, tout
    # le reste (git) passe réellement.
    _run_reel = c.subprocess.run

    def run_selectif(argv, *a, **kw):
        if argv[:3] == ["gh", "repo", "view"]:
            return type("R", (), {"returncode": 0, "stdout": '{"nameWithOwner":"leon36000/OPSYS-AI"}', "stderr": ""})()
        return _run_reel(argv, *a, **kw)

    monkeypatch.setattr(c.subprocess, "run", run_selectif)

    # Le symlink doit être TRACKÉ ET COMMITÉ pour que geler() (appelé en
    # interne par _produire_sorties) le voie comme un worktree propre —
    # c'est le scénario réaliste : git AUTORISE un symlink comme entrée de
    # tree (mode 120000), le "tampering" est un commit légitime du point de
    # vue de git, pas un fichier non suivi.
    sortie_dir_symlinke = repo / "audit_faux"
    sortie_dir_symlinke.symlink_to(coffre)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "tampering: audit_faux -> coffre externe"],
                    cwd=repo, check=True, capture_output=True)

    with pytest.raises(EcritureViaSymlinkRefusee, match="confinement"):
        c._produire_sorties(repo, sortie_dir_symlinke)

    assert list(coffre.iterdir()) == [], (
        "des fichiers ont été écrits dans le coffre externe malgré le refus attendu"
    )


def test_inventorier_hache_une_cible_de_symlink_non_utf8_sans_planter(tmp_path):
    """Convergence ×3 (DeepSeek/Gemini/Qwen, MAJEURE, mesurée vraie) :
    `.encode("utf-8")` plantait sur une cible de symlink contenant des
    octets non-UTF8 valides — git les autorise nativement dans un blob de
    symlink. `os.fsencode()` doit accepter ce cas sans exception."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-b", "b"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t.t"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)

    cible_octets = b"\x80\x81cible-non-utf8"
    lien = repo / "lien.txt"
    import os as _os
    _os.symlink(cible_octets, lien)
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "symlink non-utf8"], cwd=repo, check=True, capture_output=True)

    # Ne doit PAS lever UnicodeEncodeError.
    inv = inventorier(repo)
    entree = next((e for e in inv if e["chemin"] == "lien.txt"), None)
    assert entree is not None, "le symlink non-UTF8 a disparu de l'inventaire au lieu d'être haché"
    assert len(entree["sha256"]) == 64


def test_csv_echappe_correctement_un_chemin_avec_virgule(tmp_path):
    """Défaut trouvé par l'Orchestrateur lui-même avant tout test : une
    construction manuelle du CSV par f-string (première tentative de ce
    correctif) n'échapperait pas un chemin contenant une virgule. Vérifie
    que csv.DictWriter (via _ecrire_csv_sans_suivre_symlink) le fait
    correctement — round-trip par csv.DictReader."""
    import custody as c
    inventaire = [
        {"chemin": "dossier, avec virgule/fichier.txt", "sha256": "a" * 64, "taille": 10},
        {"chemin": 'nom "avec" guillemets.txt', "sha256": "b" * 64, "taille": 20},
    ]
    dest = tmp_path / "out.csv"
    c._ecrire_csv_sans_suivre_symlink(dest, inventaire, tmp_path)

    with dest.open(encoding="utf-8", newline="") as f:
        lignes = list(csv.DictReader(f))
    assert lignes[0]["chemin"] == "dossier, avec virgule/fichier.txt"
    assert lignes[1]["chemin"] == 'nom "avec" guillemets.txt'
