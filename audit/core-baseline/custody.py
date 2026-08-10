"""C00-001 — Chaîne de custody du dépôt cible : geler la branche, le worktree
et l'inventaire avant toute écriture produit.

Trois refus nommés, aucune tolérance implicite :
  1. `main`/`master`/HEAD détaché ne sont jamais un ancrage acceptable — un
     gel dessus décrirait un état sur lequel écrire serait destructif.
  2. Un arbre sale n'est toléré que sur une allowlist EXPLICITE de chemins,
     nommés un par un — une allowlist par motif large rendrait le refus
     décoratif.
  3. Un inventaire dont une empreinte a changé, ou dont un fichier a
     disparu/apparu, est détecté dans LES DEUX SENS : ne vérifier que les
     entrées déclarées laisserait passer tout ajout non tracé.

Aucune logique métier M1-M10 n'est touchée ici — ce module ne fait que geler
un état déjà écrit ailleurs.
"""
from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

BRANCHES_INTERDITES = frozenset({"main", "master", "head"})


class BrancheInterdite(Exception):
    """La branche observée n'est jamais un ancrage acceptable pour un gel."""


class WorktreeSale(Exception):
    """Le worktree porte des modifications hors de l'allowlist explicite."""


class EcritureViaSymlinkRefusee(Exception):
    """Une sortie de la baseline pointerait, via un symlink, hors du dépôt."""


class BlockedWrongRepository(Exception):
    """Le dépôt ou l'identité GitHub observée n'est pas celle attendue."""


@dataclass(frozen=True)
class TargetCustody:
    """La garde produite par `geler()` — un instantané ancré, jamais recopié."""
    commit: str
    tree: str
    branch: str
    worktree: str
    dirty: bool
    chemins_sales_tolerés: tuple[str, ...] = ()


def _git(worktree: Path, *args: str, check: bool = True) -> str:
    cp = subprocess.run(
        ["git", "-C", str(worktree), *args],
        text=True, capture_output=True,
    )
    if check and cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or f"git {' '.join(args)} a échoué")
    return cp.stdout


def _gh_json(args: list[str]) -> dict:
    """Exécute `gh api ...` et parse le JSON. Lève RuntimeError si échec."""
    cp = subprocess.run(
        ["gh"] + args,
        text=True, capture_output=True,
    )
    if cp.returncode != 0:
        raise RuntimeError(cp.stderr.strip() or f"gh {' '.join(args)} a échoué")
    return json.loads(cp.stdout)


def _chemin_depuis_ligne_porcelain(ligne: str) -> str:
    """Extrait le chemin d'une ligne `git status --porcelain=v2` (format 1,
    entrées non renommées — seul cas couvert, portée minimale de C00-001).

    Revue tour 1 (Qwen3.7-Max, CRITIQUE, mesurée vraie) : `ligne.split()`
    sans limite scinde sur TOUS les espaces, y compris ceux DANS le chemin
    lui-même — un fichier réellement modifié nommé
    `"attacker_prefix audit/core-baseline/TARGET.json"` voyait son dernier
    MOT (pas son chemin complet) comparé à l'allowlist, contournant
    silencieusement la garde si ce mot correspondait à une entrée
    allowlistée. Le format porcelain=v2 (entrées non renommées) a exactement
    8 champs fixes avant le chemin (XY, sub, 3 modes, 2 hash) : `maxsplit=8`
    préserve tout espace interne au chemin dans le dernier élément."""
    parts = ligne.split(maxsplit=8)
    return parts[-1] if parts else ligne


def geler(
    worktree: str | Path,
    *,
    branche_observee: str,
    statut_observe: list[str] | None = None,
    chemins_autorises: tuple[str, ...] = (),
) -> TargetCustody:
    """Fige commit/tree/branch du worktree, en refusant nommément les deux
    états qu'un gel ne peut jamais décrire : une branche destructive, un
    arbre sale non explicitement toléré."""
    worktree = Path(worktree)
    if branche_observee.lower() in BRANCHES_INTERDITES:
        raise BrancheInterdite(
            f"branche interdite pour geler le dépôt : {branche_observee!r} — "
            "main/master/HEAD détaché ne sont jamais un ancrage acceptable, "
            "un gel dessus décrirait un état sur lequel écrire serait destructif"
        )

    if statut_observe is None:
        statut_observe = [l for l in _git(worktree, "status", "--porcelain=v2").splitlines() if l.strip()]
    else:
        statut_observe = [l for l in statut_observe if l.strip()]

    chemins_sales = [_chemin_depuis_ligne_porcelain(l) for l in statut_observe]
    non_tolérés = [c for c in chemins_sales if c not in chemins_autorises]
    if non_tolérés:
        raise WorktreeSale(
            "worktree sale, chemin(s) non allowlisté(s) : " + ", ".join(non_tolérés)
        )
    tolérés = tuple(c for c in chemins_sales if c in chemins_autorises)

    commit = _git(worktree, "rev-parse", "HEAD").strip()
    tree = _git(worktree, "rev-parse", "HEAD^{tree}").strip()
    return TargetCustody(
        commit=commit, tree=tree, branch=branche_observee,
        worktree=str(worktree), dirty=bool(tolérés),
        chemins_sales_tolerés=tolérés,
    )


def inventorier(worktree: str | Path) -> list[dict]:
    """Le contenu réel de chaque fichier suivi par git — jamais un stat, une
    empreinte de CONTENU, seule chose qu'un remplacement furtif ne peut pas
    tromper."""
    worktree = Path(worktree)
    fichiers = [f for f in _git(worktree, "ls-files", "-z").split("\0") if f]
    inventaire = []
    for rel in fichiers:
        chemin = worktree / rel
        # Revue tour 1 (Qwen3.7-Max, MAJEURE, mesurée vraie) : `is_file()`
        # ET `read_bytes()` suivent les symlinks — un lien suivi de git
        # (ex: `git add -f` sur un lien pointant hors du dépôt) exposerait
        # l'empreinte d'un fichier de l'HÔTE dans l'inventaire, jamais du
        # dépôt lui-même. `is_symlink()` exclut ce cas AVANT toute lecture.
        if chemin.is_symlink() or not chemin.is_file():
            continue
        octets = chemin.read_bytes()
        inventaire.append({
            "chemin": rel,
            "sha256": hashlib.sha256(octets).hexdigest(),
            "taille": len(octets),
        })
    return inventaire


def verifier_inventaire(worktree: str | Path, inventaire: list[dict]) -> list[dict]:
    """Compare un inventaire figé au dépôt RÉEL, dans les deux sens : une
    empreinte modifiée, un fichier disparu (déclaré, absent du dépôt) et un
    fichier apparu (présent, jamais déclaré) sont trois écarts distincts."""
    actuel = {e["chemin"]: e for e in inventorier(worktree)}
    attendu = {e["chemin"]: e for e in inventaire}
    ecarts = []
    for chemin, entree in attendu.items():
        reel = actuel.get(chemin)
        if reel is None:
            ecarts.append({"chemin": chemin, "motif": "présent dans l'inventaire, absent du dépôt"})
        elif reel["sha256"] != entree["sha256"]:
            ecarts.append({"chemin": chemin, "motif": "empreinte différente"})
    for chemin in actuel:
        if chemin not in attendu:
            ecarts.append({"chemin": chemin, "motif": "présent dans le dépôt, absent de l'inventaire"})
    return ecarts


def _ecrire_sans_suivre_symlink(chemin: Path, texte: str) -> None:
    """Refuse d'écrire si `chemin` est un symlink existant, AVANT toute
    ouverture de fichier — `write_text()` seul suit les symlinks (revue
    tour 1, Qwen3.7-Max, CRITIQUE, mesurée vraie) : une sortie de la
    baseline remplacée par un lien vers un fichier hors du dépôt aurait été
    écrasée à travers ce lien."""
    if chemin.is_symlink():
        raise EcritureViaSymlinkRefusee(
            f"refus d'écrire à travers un symlink : {chemin}"
        )
    chemin.write_text(texte, encoding="utf-8")


def _produire_sorties(worktree: Path, sortie_dir: Path) -> TargetCustody:
    """Point d'entrée exécutable : produit les 5 sorties exactes de C00-001
    dans `sortie_dir`, sans modifier quoi que ce soit hors de ce répertoire."""
    # --- Garde GitHub AVANT toute écriture ---
    # 1) gh repo view doit réussir (vérifie que le dépôt existe et est accessible)
    cp_view = subprocess.run(
        ["gh", "repo", "view", "leon36000/OPSYS-AI", "--json", "nameWithOwner"],
        text=True, capture_output=True,
    )
    if cp_view.returncode != 0:
        raise BlockedWrongRepository(
            f"gh repo view leon36000/OPSYS-AI a échoué : {cp_view.stderr.strip()}"
        )
    # 2) gh api user — login doit être exactement leon36000
    try:
        auth_data = _gh_json(["api", "user"])
    except Exception as e:
        raise BlockedWrongRepository(f"gh api user a échoué : {e}") from e
    login = auth_data.get("login")
    if login != "leon36000":
        raise BlockedWrongRepository(
            f"login GitHub inattendu : {login!r} != 'leon36000' — arrêt BLOCKED_WRONG_REPOSITORY"
        )
    # 3) gh api repos/leon36000/OPSYS-AI
    try:
        repo_data = _gh_json(["api", "repos/leon36000/OPSYS-AI"])
    except Exception as e:
        raise BlockedWrongRepository(f"gh api repos/leon36000/OPSYS-AI a échoué : {e}") from e
    # 4) protections de la branche par défaut (non bloquant si échec)
    protection_data: dict | None = None
    protection_error: str | None = None
    try:
        protection_data = _gh_json(["api", "repos/leon36000/OPSYS-AI/branches/main/protection"])
    except Exception as e:
        protection_error = str(e)

    branche = _git(worktree, "rev-parse", "--abbrev-ref", "HEAD").strip()
    # `geler()` s'exécute AVANT toute écriture ci-dessous — au moment de cet
    # appel, le worktree doit déjà être propre (custody.py/conftest.py
    # committés en amont) : aucune tolérance nécessaire ici, exactement le
    # même contrat que le contre-exemple 1 du test.
    garde = geler(worktree, branche_observee=branche)
    inventaire = inventorier(worktree)

    sortie_dir.mkdir(parents=True, exist_ok=True)

    # --- Écritures (toutes via garde symlink) ---
    _ecrire_sans_suivre_symlink(
        sortie_dir / "TARGET.json",
        json.dumps({
            "commit": garde.commit,
            "tree": garde.tree,
            "branch": garde.branch,
            "worktree": garde.worktree,
            "dirty": garde.dirty,
            "chemins_sales_tolerés": list(garde.chemins_sales_tolerés),
            "fichiers_inventories": len(inventaire),
        }, ensure_ascii=False, indent=2) + "\n",
    )
    remotes = _git(worktree, "remote", "-v", check=False)
    refs = _git(worktree, "show-ref", check=False)
    _ecrire_sans_suivre_symlink(
        sortie_dir / "GIT-REFS.txt",
        f"commit {garde.commit}\n"
        f"tree {garde.tree}\n"
        f"branch {garde.branch}\n"
        "\n[remotes]\n" + remotes +
        "\n[refs]\n" + refs,
    )
    csv_path = sortie_dir / "FILE-INVENTORY.csv"
    if csv_path.is_symlink():
        raise EcritureViaSymlinkRefusee(f"refus d'écrire à travers un symlink : {csv_path}")
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["chemin", "sha256", "taille"])
        writer.writeheader()
        writer.writerows(sorted(inventaire, key=lambda e: e["chemin"]))

    # GITHUB-REPOSITORY.json — ALLOWLIST stricte, jamais un dump du JSON brut.
    #
    # `gh api repos/<owner>/<repo>` peut renvoyer `temp_clone_token` — un
    # jeton COURT TERME actif, pas un identifiant. Mesuré sur ce dépôt : non
    # vide, capturé par gitleaks au commit (generic-api-key, entropie 4.05).
    # Un dump `_raw` du JSON complet expose CE champ et tout champ sensible
    # que GitHub ajouterait demain — une allowlist explicite ne peut fuiter
    # que ce qu'elle nomme.
    repo_out: dict = {}
    for k in ("id", "node_id", "full_name", "default_branch", "private", "visibility"):
        if k in repo_data:
            repo_out[k] = repo_data[k]
    if protection_data is not None:
        repo_out["branch_protection"] = protection_data
    else:
        repo_out["branch_protection_error"] = protection_error or "non capturée"
    _ecrire_sans_suivre_symlink(
        sortie_dir / "GITHUB-REPOSITORY.json",
        json.dumps(repo_out, ensure_ascii=False, indent=2) + "\n",
    )

    # GITHUB-AUTH.json — même principe d'allowlist (D-sécurité, cf. plus haut).
    auth_out: dict = {}
    for k in ("id", "login", "node_id"):
        if k in auth_data:
            auth_out[k] = auth_data[k]
    _ecrire_sans_suivre_symlink(
        sortie_dir / "GITHUB-AUTH.json",
        json.dumps(auth_out, ensure_ascii=False, indent=2) + "\n",
    )

    return garde


if __name__ == "__main__":
    import sys
    worktree = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2]
    sortie_dir = Path(__file__).resolve().parent
    garde = _produire_sorties(worktree, sortie_dir)
    print(json.dumps({
        "commit": garde.commit, "tree": garde.tree, "branch": garde.branch,
        "dirty": garde.dirty, "chemins_sales_tolerés": list(garde.chemins_sales_tolerés),
    }, ensure_ascii=False, indent=2))
