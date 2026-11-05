"""Analyse statique bornée du code pour le preflight de développement.

Le module ne charge jamais les modules analysés. Les imports littéraux AST forment seulement
des liens probables; les imports calculés, le dispatch dynamique et les effets d'exécution
restent explicitement inconnus. Aucun extrait ou contenu source n'est rendu.
"""

from __future__ import annotations

import ast
import hashlib
import re
import subprocess
from collections import deque
from collections.abc import Callable
from pathlib import Path

MAX_FICHIERS = 500
MAX_OCTETS_FICHIER = 256_000
MAX_OCTETS_TOTAL = 8_000_000
MAX_ITEMS = 20
MAX_TARGETS = 10
MAX_SYMBOLS_PAR_CIBLE = 10
MAX_ROUTES = 20
MAX_CHEMIN_RENDU = 80
MAX_NOM_RENDU = 48

_DECLARATION_OUTILS = re.compile(r"(?m)^outils:\s*([A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*)\s*$")


def _rendre_borne(value: str, limite: int) -> tuple[str, bool]:
    return (value, False) if len(value) <= limite else (value[: limite - 3] + "...", True)


def _module_pour_chemin(path: str) -> str | None:
    """Traduit un chemin Python source en module sans importer le paquet."""
    parts = Path(path).with_suffix("").parts
    try:
        index = parts.index("src") + 1
        parts = parts[index:]
    except ValueError:
        pass
    if not parts or any(not part.isidentifier() for part in parts):
        return None
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts) or None


def _imports(arbre: ast.Module, module: str | None, *, package_file: bool = False) -> set[str]:
    result: set[str] = set()
    package = module if package_file else (module or "").rpartition(".")[0]
    for node in ast.walk(arbre):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                if not module:
                    continue
                morceaux = package.split(".") if package else []
                retrait = node.level - 1
                # ``level`` compte aussi le paquet courant : ``from ..x`` est hors
                # racine quand le paquet n'a qu'un composant. Ne pas le rabattre sur
                # un import absolu de ``x`` dans le graphe statique.
                if node.level > len(morceaux):
                    continue
                base = morceaux[: len(morceaux) - retrait]
                if node.module:
                    base.extend(node.module.split("."))
                prefixe = ".".join(base)
            else:
                prefixe = node.module or ""
            if prefixe:
                result.add(prefixe)
                result.update(f"{prefixe}.{alias.name}" for alias in node.names if alias.name != "*")
            else:
                result.update(alias.name for alias in node.names if alias.name != "*")
    return result


def _routes(arbre: ast.Module) -> tuple[list[dict[str, str]], bool]:
    found: set[tuple[str, str]] = set()
    for node in ast.walk(arbre):
        if not isinstance(node, ast.Call) or not (
            (isinstance(node.func, ast.Name) and node.func.id == "Outil")
            or (isinstance(node.func, ast.Attribute) and node.func.attr == "Outil")
        ):
            continue
        name = next(
            (
                kw.value.value
                for kw in node.keywords
                if kw.arg == "nom" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str)
            ),
            None,
        )
        handler = next(
            (kw.value.id for kw in node.keywords if kw.arg == "fonction" and isinstance(kw.value, ast.Name)),
            None,
        )
        if name and handler:
            found.add((name, handler))
            if len(found) > MAX_ROUTES:
                break
    routes = [{"name": name, "handler": handler} for name, handler in sorted(found)]
    return routes[:MAX_ROUTES], len(routes) > MAX_ROUTES


def analyser(
    repository: str | Path,
    targets: list[str],
    *,
    lire: Callable[[Path, Path, int], bytes],
    chemin_interdit: Callable[[str], bool],
) -> dict:
    """Analyse le dépôt Git local sous des bornes; `lire` doit refuser symlinks/non-réguliers."""
    root = Path(repository).expanduser().resolve()
    try:
        top = Path(
            subprocess.check_output(
                ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
                text=True,
                stderr=subprocess.DEVNULL,
            ).strip()
        ).resolve()
        commit = subprocess.check_output(
            ["git", "-C", str(top), "rev-parse", "HEAD"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        tracked = subprocess.check_output(["git", "-C", str(top), "ls-files", "-z"], stderr=subprocess.DEVNULL)
    except (OSError, subprocess.CalledProcessError):
        return {
            "status": "unavailable",
            "reason": "dépôt Git local inaccessible",
            "targets": [],
        }
    try:
        root.relative_to(top)
    except ValueError:
        return {
            "status": "unavailable",
            "reason": "dépôt hors racine Git",
            "targets": [],
        }

    try:
        paths_git = tracked.decode("utf-8", errors="strict").split("\0")
    except UnicodeDecodeError:
        return {
            "status": "unavailable",
            "reason": "nom de fichier Git non UTF-8 dans le périmètre",
            "targets": [],
        }

    prefix = root.relative_to(top).as_posix()
    candidates = []
    for raw in paths_git:
        if not raw or (prefix != "." and raw != prefix and not raw.startswith(prefix + "/")):
            continue
        path = Path(raw)
        if chemin_interdit(raw):
            continue
        if path.suffix == ".py" or path.name == "department.yaml":
            candidates.append(raw)
    candidates.sort()
    # Les fichiers explicitement demandés et les manifestes doivent garder la priorité quand
    # le dépôt dépasse le plafond; sinon l'analyse pourrait sembler vide par simple ordre lexical.
    priority = [target.split("#", 1)[0] for target in targets if target.split("#", 1)[0] in candidates]
    manifests = [path for path in candidates if Path(path).name == "department.yaml"]
    candidates = list(dict.fromkeys([*priority, *manifests, *candidates]))
    omitted_files = max(0, len(candidates) - MAX_FICHIERS)
    candidates = candidates[:MAX_FICHIERS]
    files_selected = len(candidates)
    # Une racine `src` imbriquée peut désigner soit le début du chemin de paquet
    # (pkg.x), soit un sous-paquet importable (outer.src.pkg.x). Sans métadonnée
    # de packaging, choisir l'un des deux serait une affirmation non prouvée.
    nested_src_roots = {
        "/".join(Path(raw).parts[:index + 1])
        for raw in candidates
        if Path(raw).suffix == ".py"
        for index, part in enumerate(Path(raw).parts)
        if part == "src" and index > 0
    }
    files_examined = 0
    total = 0
    parsed: dict[str, ast.Module] = {}
    modules: dict[str, str] = {}
    file_hashes: dict[str, str] = {}
    yaml_text: dict[str, str] = {}
    errors: list[dict[str, str]] = []
    dynamic: list[dict[str, int | str]] = []
    dynamic_names = {"__import__"}
    unmapped_paths = 0
    for raw in candidates:
        remaining = MAX_OCTETS_TOTAL - total
        # Un octet restant ne suffit pas à lire du contenu tout en réservant la sentinelle.
        if remaining <= 1:
            omitted_files += 1
            continue
        try:
            files_examined += 1
            # Le lecteur peut consommer un octet sentinelle pour détecter une croissance
            # post-stat. Réserver cette place garantit que la lecture réelle reste sous le total.
            limite_lecture = min(MAX_OCTETS_FICHIER, max(0, remaining - 1))
            data = lire(top, Path(raw), limite_lecture)
            total += len(data)
            file_hashes[raw] = hashlib.sha256(data).hexdigest()
            text = data.decode("utf-8")
        except (OSError, ValueError, UnicodeError) as exc:
            # Les lecteurs locaux précisent les octets déjà consommés avant l'échec.
            # Ne pas débiter une réservation conservatrice comme des octets effectivement lus.
            total += min(remaining, max(0, getattr(exc, "octets_lus", 0)))
            errors.append({"path": raw, "reason": "illisible ou hors limite"})
            continue
        if raw.endswith(".yaml"):
            yaml_text[raw] = text
            continue
        module = _module_pour_chemin(raw)
        if module is None:
            unmapped_paths += 1
        try:
            arbre = ast.parse(text, filename=raw)
        except SyntaxError:
            errors.append({"path": raw, "reason": "syntaxe Python non analysable"})
            continue
        parsed[raw] = arbre
        if module is not None:
            modules[raw] = module
        for node in ast.walk(arbre):
            if isinstance(node, ast.ImportFrom) and node.module == "importlib":
                dynamic_names.update(
                    alias.asname or alias.name for alias in node.names if alias.name == "import_module"
                )
            if isinstance(node, ast.Call):
                is_dynamic = (isinstance(node.func, ast.Name) and node.func.id in dynamic_names) or (
                    isinstance(node.func, ast.Attribute) and node.func.attr == "import_module"
                )
                if is_dynamic:
                    rendered_path, rendered_path_truncated = _rendre_borne(raw, MAX_CHEMIN_RENDU)
                    dynamic.append(
                        {
                            "path": rendered_path,
                            "path_truncated": rendered_path_truncated,
                            "sha256": file_hashes[raw],
                            "line": node.lineno,
                        }
                    )

    paths_by_module: dict[str, list[str]] = {}
    for path, module in modules.items():
        paths_by_module.setdefault(module, []).append(path)

    edges: dict[str, set[str]] = {path: set() for path in parsed}
    ambiguous_imports: set[tuple[str, str]] = set()
    for path, arbre in parsed.items():
        referenced = _imports(
            arbre,
            modules.get(path),
            package_file=Path(path).name == "__init__.py",
        )
        for module_ref in referenced:
            matches = paths_by_module.get(module_ref, [])
            if len(matches) == 1:
                edges[path].add(matches[0])
            elif len(matches) > 1:
                ambiguous_imports.add((path, module_ref))

    target_records = []
    known_targets = set()
    unavailable_targets = 0
    targets_omitted = max(0, len(targets) - MAX_TARGETS)
    for target in targets[:MAX_TARGETS]:
        normalized = Path(target).as_posix()
        display_path, path_truncated = _rendre_borne(normalized, MAX_CHEMIN_RENDU)
        tree = parsed.get(normalized)
        if tree is None:
            unavailable_targets += 1
            target_records.append(
                {
                    "path": display_path,
                    "status": "unavailable",
                    "symbols": [],
                    "imports": [],
                    "path_truncated": path_truncated,
                }
            )
            continue
        known_targets.add(normalized)
        symbols = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name, name_truncated = _rendre_borne(node.name, MAX_NOM_RENDU)
                symbols.append(
                    {
                        "name": name,
                        "name_truncated": name_truncated,
                        "kind": "class" if isinstance(node, ast.ClassDef) else "function",
                        "line": node.lineno,
                    }
                )
        target_imports = sorted(edges[normalized])
        target_records.append(
            {
                "path": display_path,
                "status": "parsed",
                "sha256": file_hashes[normalized],
                "symbols": symbols[:MAX_SYMBOLS_PAR_CIBLE],
                "symbols_omitted": max(0, len(symbols) - MAX_SYMBOLS_PAR_CIBLE),
                "imports": [
                    {
                        "path": _rendre_borne(path, MAX_CHEMIN_RENDU)[0],
                        "path_truncated": _rendre_borne(path, MAX_CHEMIN_RENDU)[1],
                        "sha256": file_hashes[path],
                    }
                    for path in target_imports[:MAX_ITEMS]
                ],
                "imports_omitted": max(0, len(target_imports) - MAX_ITEMS),
                "path_truncated": path_truncated,
            }
        )

    # Inverse closure: paths that directly or transitively import a target.
    reverse: dict[str, set[str]] = {path: set() for path in parsed}
    for importer, imported in edges.items():
        for imported_path in imported:
            reverse.setdefault(imported_path, set()).add(importer)
    distance = {path: 0 for path in known_targets}
    queue = deque(sorted(known_targets))
    while queue and len(distance) < MAX_ITEMS:
        current = queue.popleft()
        for importer in sorted(reverse.get(current, ())):
            if importer not in distance:
                distance[importer] = distance[current] + 1
                queue.append(importer)
    traversal_truncated = bool(queue)
    impact_paths = sorted(
        (path for path in distance if path not in known_targets),
        key=lambda path: (distance[path], path),
    )
    impact_omitted = max(0, len(impact_paths) - MAX_ITEMS)
    impact_paths = impact_paths[:MAX_ITEMS]
    importers = []
    for path in impact_paths:
        rendered_path, path_truncated = _rendre_borne(path, MAX_CHEMIN_RENDU)
        importers.append(
            {
                "path": rendered_path,
                "path_truncated": path_truncated,
                "sha256": file_hashes[path],
                "distance": distance[path],
            }
        )
    tests = []
    for path in impact_paths:
        if any(part.lower() == "tests" or part.lower().startswith("test_") for part in Path(path).parts) or Path(
            path
        ).name.startswith("test_"):
            tests.append(
                {
                    "path": _rendre_borne(path, MAX_CHEMIN_RENDU)[0],
                    "path_truncated": _rendre_borne(path, MAX_CHEMIN_RENDU)[1],
                    "sha256": file_hashes[path],
                    "distance": distance[path],
                }
            )

    routes = []
    route_truncated = False
    manifest_gaps = []
    for manifest_path, text in yaml_text.items():
        match = _DECLARATION_OUTILS.search(text)
        if match is None:
            continue
        providers = paths_by_module.get(match.group(1), [])
        if len(providers) != 1:
            rendered_manifest, manifest_truncated = _rendre_borne(manifest_path, MAX_CHEMIN_RENDU)
            rendered_provider, provider_truncated = _rendre_borne(match.group(1), MAX_NOM_RENDU)
            manifest_gaps.append(
                {
                    "manifest": rendered_manifest,
                    "manifest_truncated": manifest_truncated,
                    "provider": rendered_provider,
                    "provider_truncated": provider_truncated,
                    "reason": "provider absent" if not providers else "provider ambigu",
                }
            )
            continue
        for provider in providers:
            if provider not in distance:
                continue
            provider_routes, provider_truncated = _routes(parsed[provider])
            route_truncated = route_truncated or provider_truncated
            for route in provider_routes:
                rendered_name, name_truncated = _rendre_borne(route["name"], MAX_NOM_RENDU)
                rendered_handler, handler_truncated = _rendre_borne(route["handler"], MAX_NOM_RENDU)
                rendered_manifest, manifest_path_truncated = _rendre_borne(manifest_path, MAX_CHEMIN_RENDU)
                rendered_provider, provider_path_truncated = _rendre_borne(provider, MAX_CHEMIN_RENDU)
                routes.append(
                    {
                        "name": rendered_name,
                        "name_truncated": name_truncated,
                        "handler": rendered_handler,
                        "handler_truncated": handler_truncated,
                        "manifest": rendered_manifest,
                        "manifest_truncated": manifest_path_truncated,
                        "provider": rendered_provider,
                        "provider_truncated": provider_path_truncated,
                        "manifest_sha256": file_hashes[manifest_path],
                        "provider_sha256": file_hashes[provider],
                        "distance": distance[provider],
                    }
                )
    routes.sort(key=lambda item: (item["manifest"], item["name"], item["handler"]))
    routes_omitted = max(0, len(routes) - MAX_ROUTES) + int(route_truncated)

    limitations = [
        "imports dynamiques et dépendances transitives non prouvées",
        "liens tests déduits uniquement des imports Python littéraux",
        "routes reconnues uniquement via `outils:` simple et appels AST `Outil(nom=..., fonction=...)`",
        "les collisions de noms de modules sont laissées non résolues",
        "un provider absent ou ambigu ne permet pas de lister ses routes",
        "aucun code exécuté; l'impact est une piste de lecture, pas une preuve de comportement",
    ]
    if dynamic:
        limitations.append("imports dynamiques détectés")
    if nested_src_roots:
        limitations.append(
            "racines `src` imbriquées : le mapping des modules Python est ambigu sans métadonnée de packaging"
        )
    target_symbols_omitted = sum(item.get("symbols_omitted", 0) for item in target_records)
    target_imports_omitted = sum(item.get("imports_omitted", 0) for item in target_records)
    if target_symbols_omitted or target_imports_omitted:
        limitations.append("symboles ou imports de cible omis par les plafonds; consulter les compteurs par cible")
    truncated = bool(
        omitted_files
        or errors
        or target_symbols_omitted
        or target_imports_omitted
        or impact_omitted
        or routes_omitted
        or (len(ambiguous_imports) > MAX_ITEMS)
        or dynamic
        or unavailable_targets
        or targets_omitted
        or traversal_truncated
        or route_truncated
        or manifest_gaps
    )
    return {
        "status": "partial",
        "analysis": "bounded_static",
        "commit": commit,
        "snapshot": "worktree suivi lu fichier par fichier; les empreintes identifient les sources lues",
        "targets": target_records,
        "importers": importers,
        "tests": tests,
        "routes": routes[:MAX_ROUTES],
        "ambiguous_imports": [
            {
                "path": _rendre_borne(path, MAX_CHEMIN_RENDU)[0],
                "path_truncated": _rendre_borne(path, MAX_CHEMIN_RENDU)[1],
                "module": _rendre_borne(module, MAX_NOM_RENDU)[0],
                "module_truncated": _rendre_borne(module, MAX_NOM_RENDU)[1],
            }
            for path, module in sorted(ambiguous_imports)[:MAX_ITEMS]
        ],
        "dynamic_imports": dynamic[:MAX_ITEMS],
        "errors": [
            {
                "path": _rendre_borne(item["path"], MAX_CHEMIN_RENDU)[0],
                "path_truncated": _rendre_borne(item["path"], MAX_CHEMIN_RENDU)[1],
                "reason": item["reason"],
            }
            for item in errors[:MAX_ITEMS]
        ],
        "manifest_gaps": manifest_gaps[:MAX_ITEMS],
        "limits": {
            "files": MAX_FICHIERS,
            "bytes": MAX_OCTETS_TOTAL,
            "items": MAX_ITEMS,
            "targets": MAX_TARGETS,
        },
        "counts": {
            "files_examined": files_examined,
            "files_selected": files_selected,
            "bytes_examined": total,
            "importers": len(distance) - len(known_targets),
            "importers_omitted": impact_omitted + len(queue),
            "importers_omitted_exact": not traversal_truncated,
            "routes": len(routes),
            "routes_omitted": routes_omitted,
            "routes_omitted_exact": not route_truncated,
            "errors": len(errors),
            "files_omitted": omitted_files,
            "dynamic_imports": len(dynamic),
            "targets_unavailable": unavailable_targets,
            "targets_omitted": targets_omitted,
            "importer_traversal_truncated": traversal_truncated,
            "ambiguous_imports": len(ambiguous_imports),
            "ambiguous_imports_omitted": max(0, len(ambiguous_imports) - MAX_ITEMS),
            "manifest_gaps": len(manifest_gaps),
            "manifest_gaps_omitted": max(0, len(manifest_gaps) - MAX_ITEMS),
            "unmapped_paths": unmapped_paths,
            "nested_src_roots": len(nested_src_roots),
            "target_symbols_omitted": target_symbols_omitted,
            "target_imports_omitted": target_imports_omitted,
        },
        "truncated": truncated,
        "limitations": limitations,
    }
