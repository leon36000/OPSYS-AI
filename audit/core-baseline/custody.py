import csv
import hashlib
import json
import os
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


def _verifier_confinement(chemin: Path, racine: Path) -> Path:
    """Résout la chaîne COMPLÈTE (tous les composants, pas seulement la
    feuille) et vérifie qu'elle reste sous `racine`. `is_symlink()` sur le
    seul composant final ne voit pas un PARENT symlinké — `Path.resolve()`
    suit toute la chaîne. Revue scellée, Qwen3.7-Max CRITIQUE, reproduit :
    un `audit/` symlinké vers un répertoire hors dépôt donnait
    is_symlink()=False sur le fichier final tout en lisant son contenu réel."""
    reel = chemin.resolve()
    racine_reelle = racine.resolve()
    try:
        reel.relative_to(racine_reelle)
    except ValueError:
        raise EcritureViaSymlinkRefusee(
            f"chemin hors confinement (symlink parent ou feuille) : "
            f"{chemin} résout vers {reel}, hors de {racine_reelle}")
    return reel


def _sha256_par_blocs(chemin: Path, taille_bloc: int = 1_048_576) -> tuple[str, int]:
    """Hache par blocs de 1 Mo — jamais tout le fichier en mémoire d'un
    coup, contrairement à read_bytes(). Retourne (hash, taille_totale)."""
    h = hashlib.sha256(); taille = 0
    with chemin.open("rb") as f:
        while bloc := f.read(taille_bloc):
            h.update(bloc); taille += len(bloc)
    return h.hexdigest(), taille


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
        # Revue scellée : confinement parent + hachage cible du symlink.
        if chemin.is_symlink():
            cible_lien = os.readlink(chemin)
            # Revue tour 3 (DeepSeek·Gemini·Qwen convergents, MAJEURE
            # mesurée vraie) : `.encode("utf-8")` plante (UnicodeEncodeError)
            # sur une cible contenant des octets non-UTF8 valides — git
            # AUTORISE nativement de tels octets dans un blob de symlink.
            # `os.readlink()` renvoie alors une chaîne avec des caractères
            # surrogate (`\udcXX`). `os.fsencode()` applique l'encodage du
            # système de fichiers avec `surrogateescape` — round-trip sans
            # perte, jamais de plantage, c'est l'idiome canonique pour ce cas.
            octets = os.fsencode(cible_lien)
            inventaire.append({
                "chemin": rel,
                "sha256": hashlib.sha256(octets).hexdigest(),
                "taille": len(octets),
            })
        elif chemin.is_file():
            _verifier_confinement(chemin, worktree)
            sha, taille = _sha256_par_blocs(chemin)
            inventaire.append({
                "chemin": rel,
                "sha256": sha,
                "taille": taille,
            })
        else:
            continue
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


def _ecrire_sans_suivre_symlink(chemin: Path, texte: str, racine: Path) -> None:
    """Refuse d'écrire si `chemin` est un symlink existant, AVANT toute
    ouverture de fichier — `write_text()` seul suit les symlinks (revue
    tour 1, Qwen3.7-Max, CRITIQUE, mesurée vraie) : une sortie de la
    baseline remplacée par un lien vers un fichier hors du dépôt aurait été
    écrasée à travers ce lien.

    `racine` est OBLIGATOIRE (pas de valeur par défaut) — un repli
    "racine=None -> vérifier contre chemin.parent" a été retiré ici après
    mesure (revue scellée tour 2) : comparer un chemin résolu contre SON
    PROPRE PARENT résolu est tautologiquement toujours vrai. MAIS le
    paramètre obligatoire ne suffit pas à lui seul : si l'APPELANT passe
    encore le parent direct comme racine (ce que faisait `_produire_sorties`
    en passant `sortie_dir`, lui-même parent immédiat des fichiers écrits),
    la même tautologie reproduit intégralement le trou — mesurée vraie en
    revue tour 3 (Gemini-3.1-Pro, CRITIQUE) : `sortie_dir` symlinké vers un
    répertoire externe rendait `_verifier_confinement` inopérant. Corrigé
    aux appelants : `racine` doit être une ancre STABLE au-dessus de tout
    répertoire remplaçable (la racine du worktree), jamais le parent
    immédiat du fichier écrit.

    TOCTOU (revue tour 3, Gemini-3.1-Pro, MAJEURE, mesurée vraie) : vérifier
    `is_symlink()` PUIS ouvrir séparément laisse une fenêtre où un
    attaquant peut planter un symlink entre les deux appels — `write_text()`
    le suivrait. `O_EXCL|O_NOFOLLOW` rend vérification et écriture
    ATOMIQUES : le noyau échoue l'ouverture si quoi que ce soit existe déjà
    à ce chemin (fichier OU symlink), sans jamais suivre un lien — aucune
    fenêtre de course possible, contrairement à un check puis un open
    séparés."""
    if chemin.is_symlink():
        raise EcritureViaSymlinkRefusee(
            f"refus d'écrire à travers un symlink : {chemin}"
        )
    _verifier_confinement(chemin, racine)
    donnees = texte.encode("utf-8")
    try:
        fd = os.open(str(chemin), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    except OSError as e:
        raise EcritureViaSymlinkRefusee(
            f"écriture refusée (symlink planté pendant la fenêtre de vérification, "
            f"ou cible déjà existante) : {chemin} — {e}"
        ) from e
    with os.fdopen(fd, "wb") as f:
        f.write(donnees)


def _ecrire_csv_sans_suivre_symlink(chemin: Path, lignes: list[dict], racine: Path) -> None:
    """Même garde que `_ecrire_sans_suivre_symlink` (symlink + confinement +
    ouverture atomique O_EXCL|O_NOFOLLOW), mais via `csv.DictWriter` pour un
    échappement correct des champs — un `chemin` de fichier PEUT contenir
    une virgule, un guillemet ou un saut de ligne ; une construction
    manuelle par f-string ne les échapperait pas."""
    if chemin.is_symlink():
        raise EcritureViaSymlinkRefusee(
            f"refus d'écrire à travers un symlink : {chemin}"
        )
    _verifier_confinement(chemin, racine)
    try:
        fd = os.open(str(chemin), os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o644)
    except OSError as e:
        raise EcritureViaSymlinkRefusee(
            f"écriture refusée (symlink planté pendant la fenêtre de vérification, "
            f"ou cible déjà existante) : {chemin} — {e}"
        ) from e
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["chemin", "sha256", "taille"])
        writer.writeheader()
        writer.writerows(lignes)


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
        default_branch = repo_data.get("default_branch", "main")
        protection_data = _gh_json(["api", f"repos/leon36000/OPSYS-AI/branches/{default_branch}/protection"])
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
    #
    # `racine=worktree` (PAS `sortie_dir`) pour CHAQUE appel ci-dessous.
    # Revue tour 3 (Gemini-3.1-Pro, CRITIQUE, mesurée vraie) : `sortie_dir`
    # est le parent IMMÉDIAT de chaque fichier écrit — passer le parent
    # direct comme racine de confinement est la MÊME tautologie que le
    # repli `racine=None` déjà retiré au tour 2 (chemin résolu confiné dans
    # son propre parent résolu, toujours vrai). `worktree` est une ancre
    # STABLE, plusieurs niveaux au-dessus — un `audit/` ou
    # `audit/core-baseline/` remplacé par un symlink est maintenant détecté.
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
        worktree,
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
        worktree,
    )
    # FILE-INVENTORY.csv : même garde que _ecrire_sans_suivre_symlink, mais
    # via csv.DictWriter (échappement correct des champs — un chemin de
    # fichier PEUT contenir une virgule ou un guillemet ; une construction
    # manuelle par f-string ne les échapperait pas — corrigé avant même
    # d'être testé, aucune sortie mal formée n'a jamais existé).
    _ecrire_csv_sans_suivre_symlink(sortie_dir / "FILE-INVENTORY.csv", inventaire, worktree)

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
        worktree,
    )

    # GITHUB-AUTH.json — même principe d'allowlist (D-sécurité, cf. plus haut).
    auth_out: dict = {}
    for k in ("id", "login", "node_id"):
        if k in auth_data:
            auth_out[k] = auth_data[k]
    _ecrire_sans_suivre_symlink(
        sortie_dir / "GITHUB-AUTH.json",
        json.dumps(auth_out, ensure_ascii=False, indent=2) + "\n",
        worktree,
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
