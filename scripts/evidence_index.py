#!/usr/bin/env python3
"""Index rebuildable des preuves/registres (R4-S11, issue #593) — D-038 style.

Ne JAMAIS éditer les fichiers sous docs/audit/ produits par ce script à la main :
relancer `python3 scripts/evidence_index.py` (et committer le résultat), exactement
comme scripts/structure_lint.py pour registries/frameworks.yaml.

Périmètre indexé (unité = un fichier VERSIONNÉ, via `git ls-files`) :
    evidence/**  (hors evidence/tasks/EXT-AUD-001-A1-R12-CANDIDATE/ — territoire actif
                  de la PR #566, laissé intact et non indexé)
    registries/**
    Registres/**

`reviews/**` est explicitement EXCLU de ce lot, cf. #591, en attente de décision Nathan.
Ce script ne le lit ni ne le liste — la phrase ci-dessus est la SEULE mention de
`reviews/**` que ce lot produit, dans ce fichier et dans les index générés.

Méthode de liaison (nommée, rejouable — même discipline que le forensics de #591) :

  1. champ-explicite : le fichier (JSON, y compris une ligne de JSONL) porte un champ du
     vocabulaire de liaison au code, mesuré exhaustivement sur ce périmètre (cf.
     docs/audit/README.md) :
       - base, reviewed_commit                -> doit résoudre en commit Git réel
       - reviewed_tree, base_tree              -> doit résoudre en tree Git réel
       - branche, branch                       -> doit résoudre en ref Git réelle
       - code_diff_sha256 + preuves_jointes    -> recalcul sha256 d'un export committé
         (full.diff ou équivalent nommé *diff*) et comparaison à la valeur déclarée
     Chaque candidat est vérifié par une commande Git réelle (`git cat-file -e`,
     `git rev-parse --verify`, `git ls-remote` en repli) ou par un recalcul de sha256 sur
     un fichier committé — jamais accepté sur la seule forme (leçon #591 : un motif
     hexadécimal n'est pas une preuve tant qu'il ne résout pas vers un objet réel).

     LIMITE ASSUMÉE, différente en nature des trois autres champs : `branche`/`branch`
     preuve une ref, pas un objet. Un commit ou un tree, une fois créés, restent des
     objets Git stables ; une BRANCHE peut être supprimée par une opération de routine
     (nettoyage post-merge) — ce que ce script ne peut pas empêcher, et qu'aucune
     re-exécution future ne peut garantir de retrouver. `"verifie": true` sur ce champ
     atteste donc « cette branche existait au moment de cette mesure », jamais une
     garantie permanente comme pour un commit ou un tree. Documenté plutôt que tu.
     Deux vocabulaires supplémentaires sont reconnus mais NE COMPTENT PAS comme lien au
     CODE (même distinction que #591 sur prompt_sha256, "scelle le prompt, pas l'arbre") :
     preuves_jointes.prompt.txt (scelle un prompt) et sha256_du_texte~texte (auto-
     cohérence d'une réponse brute de modèle). Ils sont recensés, jamais comptés.
     Les champs de texte libre (ex. payload.evenement des lignes de
     registries/ledger/*.jsonl) ne sont PAS scannés pour des sous-chaînes hexadécimales :
     cela reproduirait le risque de faux positif que #591 documente sur les mots
     « commit/diff/arbre » trouvés en prose. Seul le vocabulaire nommé ci-dessus est lu.

  2. commit-introducteur : à défaut de méthode 1, le commit qui a ajouté ce chemin
     (`git log --diff-filter=A --follow --format=%H -- <chemin>`, le plus ancien si
     plusieurs) est identifié ; son message COMPLET (`git log -1 --format=%B`) est
     scanné pour un motif hexadécimal de 7 à 40 caractères, à l'exclusion du hash du
     commit introducteur lui-même, et chaque candidat est vérifié comme en méthode 1.

Si aucune des deux méthodes ne prouve de liaison vers du CODE (commit/tree/ref/diff) :
statut NON_PROUVE, avec la raison consignée. Jamais une liaison inventée, jamais un
silence.

Usage :
    python3 scripts/evidence_index.py            # régénère docs/audit/*.json + *.md
    python3 scripts/evidence_index.py --check     # vérifie que le comité est à jour ; rc=1 si dérive
"""
import hashlib
import json
import os
import re
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
ROOTS_INDEXES = ["evidence", "registries", "Registres"]
EXCLUS_PREFIXES = ["evidence/tasks/EXT-AUD-001-A1-R12-CANDIDATE/"]
OUT_DIR = os.path.join(ROOT, "docs", "audit")
OUT_JSON = os.path.join(OUT_DIR, "evidence-link-index.json")
OUT_MD = os.path.join(OUT_DIR, "EVIDENCE-LINK-INDEX.md")

HEX_RE = re.compile(r"\b[0-9a-fA-F]{7,40}\b")

CHAMPS_COMMIT = ["base", "reviewed_commit"]
CHAMPS_TREE = ["reviewed_tree", "base_tree"]
CHAMPS_REF = ["branche", "branch"]
CHAMP_DIFF_SHA256 = "code_diff_sha256"
CHAMP_EXPORTS = "preuves_jointes"

CODE_LINK_TYPES = {"commit", "tree", "ref", "diff"}

REVIEWS_EXCLUSION_LINE = "reviews/** : exclu de ce lot, cf. #591, en attente de décision Nathan."


def sh(args, cwd=ROOT):
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True)


def git_tracked_files(roots):
    r = sh(["git", "ls-files", "--"] + roots)
    if r.returncode != 0:
        raise RuntimeError(f"git ls-files a échoué : {r.stderr}")
    paths = [p for p in r.stdout.splitlines() if p.strip()]
    return sorted(paths)


def est_exclu(path):
    return any(path.startswith(pfx) for pfx in EXCLUS_PREFIXES)


def git_object_exists(sha, kind):
    r = sh(["git", "cat-file", "-e", f"{sha}^{{{kind}}}"])
    return r.returncode == 0


def git_ref_exists(ref):
    """Vraie si `ref` résout vers un commit, en local d'abord puis sur le remote.

    BUG mesuré (reproduit par clonage à branche unique, la forme de checkout
    réelle de `actions/checkout` sans configuration explicite) : un clone qui
    n'a récupéré QUE la branche de cette PR ne porte localement aucun ref pour
    les AUTRES branches citées dans les fichiers indexés (`refs/remotes/origin/*`
    absent), alors que ces 6 branches existent bel et bien sur GitHub au moment
    de ce correctif (vérifié une à une via `gh api repos/.../branches/<nom>`).
    La complétude du clone local n'est pas une propriété du dépôt : elle ne
    doit pas décider `verifie`. D'où le repli sur `git ls-remote`, qui
    interroge le remote directement, indépendamment de ce qui a été fetché.
    """
    for candidate in (f"refs/remotes/origin/{ref}", f"refs/heads/{ref}", ref):
        r = sh(["git", "rev-parse", "--verify", "--quiet", candidate])
        if r.returncode == 0:
            return True, r.stdout.strip()
    r = sh(["git", "ls-remote", "--exit-code", "origin", f"refs/heads/{ref}"])
    if r.returncode == 0 and r.stdout.strip():
        return True, r.stdout.split()[0]
    return False, None


def extract_hex_candidates(text):
    if not isinstance(text, str):
        return []
    seen = []
    for m in HEX_RE.finditer(text):
        c = m.group(0).lower()
        if c not in seen:
            seen.append(c)
    return seen


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    with open(path, "rb") as f:
        return sha256_bytes(f.read())


def charger_json_docs(path_abs, path_rel):
    """Retourne la liste des documents JSON portés par ce fichier (1 pour .json, N pour
    .jsonl — une entrée par ligne non vide). Liste vide si non-JSON ou illisible."""
    docs = []
    try:
        with open(path_abs, "r", encoding="utf-8") as f:
            contenu = f.read()
    except (UnicodeDecodeError, OSError):
        return docs
    if path_rel.endswith(".jsonl"):
        for ligne in contenu.splitlines():
            ligne = ligne.strip()
            if not ligne:
                continue
            try:
                d = json.loads(ligne)
            except json.JSONDecodeError:
                continue
            if isinstance(d, dict):
                docs.append(d)
    elif path_rel.endswith(".json"):
        try:
            d = json.loads(contenu)
        except json.JSONDecodeError:
            return docs
        if isinstance(d, dict):
            docs.append(d)
    return docs


def liaisons_champ_explicite(path_rel, path_abs):
    """Rejoue la méthode 1 sur tous les documents JSON portés par ce fichier."""
    liaisons = []
    docs = charger_json_docs(path_abs, path_rel)
    base_dir = os.path.dirname(path_abs)

    for data in docs:
        for champ in CHAMPS_COMMIT:
            if champ in data and isinstance(data[champ], str):
                candidats = extract_hex_candidates(data[champ])
                verifie_une_fois = False
                for c in candidats:
                    if git_object_exists(c, "commit"):
                        liaisons.append({
                            "champ": champ, "type": "commit", "valeur": c,
                            "methode": "champ-explicite", "verifie": True,
                        })
                        verifie_une_fois = True
                        break
                if not verifie_une_fois and candidats:
                    liaisons.append({
                        "champ": champ, "type": "commit", "valeur": candidats[0],
                        "methode": "champ-explicite", "verifie": False,
                        "detail": "candidat hex trouvé, ne résout vers aucun commit Git réel",
                    })

        for champ in CHAMPS_TREE:
            if champ in data and isinstance(data[champ], str):
                candidats = extract_hex_candidates(data[champ])
                verifie_une_fois = False
                for c in candidats:
                    if git_object_exists(c, "tree"):
                        liaisons.append({
                            "champ": champ, "type": "tree", "valeur": c,
                            "methode": "champ-explicite", "verifie": True,
                        })
                        verifie_une_fois = True
                        break
                if not verifie_une_fois and candidats:
                    liaisons.append({
                        "champ": champ, "type": "tree", "valeur": candidats[0],
                        "methode": "champ-explicite", "verifie": False,
                        "detail": "candidat hex trouvé, ne résout vers aucun tree Git réel",
                    })

        for champ in CHAMPS_REF:
            if champ in data and isinstance(data[champ], str):
                val = data[champ]
                ok, resolu = git_ref_exists(val)
                entree = {
                    "champ": champ, "type": "ref", "valeur": val,
                    "methode": "champ-explicite", "verifie": ok,
                }
                if ok:
                    entree["resolu_vers"] = resolu
                else:
                    entree["detail"] = "ref absente (probablement supprimée après fusion)"
                liaisons.append(entree)

        # code_diff_sha256 + preuves_jointes : recoupement par recalcul de sha256
        declare_diff = data.get(CHAMP_DIFF_SHA256)
        pj = data.get(CHAMP_EXPORTS) if isinstance(data.get(CHAMP_EXPORTS), dict) else {}
        diff_recoupe = False
        for fname, sha in (pj or {}).items():
            if not isinstance(sha, str):
                continue
            fpath = os.path.join(base_dir, fname)
            categorie = "diff" if "diff" in fname.lower() else (
                "prompt" if "prompt" in fname.lower() else "autre")
            if os.path.isfile(fpath):
                actual = sha256_file(fpath)
                verifie = actual.lower() == sha.lower()
                liaisons.append({
                    "champ": f"{CHAMP_EXPORTS}.{fname}",
                    "type": f"export:{categorie}" if categorie != "diff" else "diff",
                    "valeur": sha, "methode": "champ-explicite:export-recalcule",
                    "verifie": verifie,
                    "detail": f"sha256({fname}) recalculé et comparé à la valeur déclarée",
                })
                if categorie == "diff" and verifie:
                    diff_recoupe = True
            else:
                liaisons.append({
                    "champ": f"{CHAMP_EXPORTS}.{fname}",
                    "type": f"export:{categorie}" if categorie != "diff" else "diff",
                    "valeur": sha, "methode": "champ-explicite:export-recalcule",
                    "verifie": False,
                    "detail": f"fichier {fname} référencé mais absent du dépôt à ce chemin",
                })
        if declare_diff and not diff_recoupe:
            liaisons.append({
                "champ": CHAMP_DIFF_SHA256, "type": "diff-declare-non-recalculable",
                "valeur": declare_diff, "methode": "champ-explicite", "verifie": False,
                "detail": ("aucun export diff committé sous preuves_jointes ne recoupe cette "
                           "valeur dans ce lot ; pathspec scellé non reproduit ici "
                           "(core/scripts/verify_proof_sealed.py est hors périmètre de ce script)"),
            })

        # auto-cohérence sha256_du_texte~texte : recensé, ne compte jamais comme lien code
        if "sha256_du_texte" in data and isinstance(data.get("texte"), str):
            actual = sha256_bytes(data["texte"].encode("utf-8"))
            verifie = actual.lower() == str(data["sha256_du_texte"]).lower()
            liaisons.append({
                "champ": "sha256_du_texte~texte", "type": "export:raw-response",
                "valeur": data["sha256_du_texte"], "methode": "champ-explicite:auto-coherence-interne",
                "verifie": verifie,
                "detail": "scelle une réponse brute de modèle, pas un lien au code (cf. #591 sur prompt_sha256)",
            })

    return liaisons


COLLECTEURS = {"reviews", "reviews-context", "raw"}


def groupe_bundle(path_rel):
    """Dossier-bundle d'un chemin : son dossier parent, en rattachant les
    sous-dossiers collecteurs (reviews/, reviews-context/, raw/) à LEUR parent.
    Sert à borner la méthode 2 : une citation dans un commit introducteur ne
    compte que si TOUT ce que ce commit touche dans le périmètre indexé reste
    dans le même bundle — sinon le commit est un commit fourre-tout et une
    citation qu'il contient peut porter sur autre chose que ce fichier (cas
    mesuré : commit fbe2c813b87f, squash multi-parties touchant
    audit-000-cadrage/ ET audit-000-cadrage-tour2/, où deux hash cités en
    aparté sur un incident SonarCloud sans rapport auraient sinon été acceptés
    à tort comme lien au code de registries/verdicts/audit-000-cadrage/DeepSeek-V4-Pro.verdict.json)."""
    parts = os.path.dirname(path_rel).split("/") if os.path.dirname(path_rel) else []
    while parts and parts[-1] in COLLECTEURS:
        parts.pop()
    return "/".join(parts)


def commit_scope_ok(commit_hash, path_rel):
    """True si tous les fichiers du périmètre indexé touchés par ce commit
    partagent le même groupe_bundle() que path_rel (commit dédié à ce bundle,
    pas un commit fourre-tout)."""
    r = sh(["git", "show", "--format=", "--name-only", commit_hash])
    if r.returncode != 0:
        return False
    touches = [p for p in r.stdout.splitlines() if p.strip()
               and any(p.startswith(rt + "/") or p == rt for rt in ROOTS_INDEXES)]
    if not touches:
        return False
    groupe_cible = groupe_bundle(path_rel)
    return all(groupe_bundle(p) == groupe_cible for p in touches)


def commit_introducteur(path_rel):
    r = sh(["git", "log", "--diff-filter=A", "--follow", "--format=%H", "--", path_rel])
    hashes = [h for h in r.stdout.splitlines() if h.strip()]
    if hashes:
        h = hashes[-1]  # le plus ancien évènement d'ajout
    else:
        r2 = sh(["git", "log", "--format=%H", "--", path_rel])
        hashes2 = [x for x in r2.stdout.splitlines() if x.strip()]
        if not hashes2:
            return None
        h = hashes2[-1]
    date = sh(["git", "log", "-1", "--format=%ad", "--date=short", h]).stdout.strip()
    sujet = sh(["git", "log", "-1", "--format=%s", h]).stdout.strip()
    message = sh(["git", "log", "-1", "--format=%B", h]).stdout
    return {"hash": h, "date": date, "sujet": sujet, "message": message}


def liaisons_commit_introducteur(path_rel):
    liaisons = []
    ci = commit_introducteur(path_rel)
    if ci is None:
        return liaisons, None
    if not commit_scope_ok(ci["hash"], path_rel):
        liaisons.append({
            "champ": f"message-commit-introducteur({ci['hash'][:12]})",
            "type": "commit-hors-portee", "valeur": None,
            "methode": "commit-introducteur", "verifie": False,
            "detail": (f"commit introducteur {ci['hash'][:12]} ({ci['date']}) touche d'autres bundles du "
                       "périmètre indexé que le sien : toute référence qu'il cite n'est pas retenue "
                       "(risque de citation hors-sujet dans un commit fourre-tout, cf. docstring groupe_bundle)"),
        })
        return liaisons, ci
    candidats = extract_hex_candidates(ci["message"])
    propre_hash = ci["hash"].lower()
    for c in candidats:
        if propre_hash.startswith(c):
            continue  # exclusion défensive : jamais le (préfixe du) hash du commit introducteur lui-même
        for kind in ("commit", "tree"):
            if git_object_exists(c, kind):
                liaisons.append({
                    "champ": f"message-commit-introducteur({ci['hash'][:12]})",
                    "type": kind, "valeur": c,
                    "methode": "commit-introducteur", "verifie": True,
                    "detail": f"cité dans le message du commit introducteur {ci['hash'][:12]} ({ci['date']}, commit dédié à ce bundle)",
                })
                break
    return liaisons, ci


def analyser_fichier(path_rel):
    path_abs = os.path.join(ROOT, path_rel)
    liaisons = []

    liaisons += liaisons_champ_explicite(path_rel, path_abs)

    ci_liaisons, ci = liaisons_commit_introducteur(path_rel)
    liaisons += ci_liaisons

    a_code_link = any(l.get("verifie") is True and l.get("type") in CODE_LINK_TYPES for l in liaisons)
    statut = "PROUVE" if a_code_link else "NON_PROUVE"

    entree = {
        "chemin": path_rel,
        "sha256_fichier": sha256_file(path_abs),
        "liaisons": liaisons,
        "statut": statut,
    }
    if ci is not None:
        entree["commit_introducteur"] = {"hash": ci["hash"], "date": ci["date"], "sujet": ci["sujet"]}
    if statut == "NON_PROUVE":
        hors_portee = any(l.get("type") == "commit-hors-portee" for l in liaisons)
        tentatives_champ = [f"{l['champ']} ({l['type']}, non résolu)" for l in liaisons
                             if l.get("verifie") is False and l.get("type") != "commit-hors-portee"]
        morceaux = [("champs tentés sans résolution : " + "; ".join(tentatives_champ))
                    if tentatives_champ else "aucun champ du vocabulaire connu trouvé"]
        if hors_portee:
            morceaux.append(f"commit introducteur {ci['hash'][:12]} ({ci['date']}) hors périmètre "
                             "(touche d'autres bundles du même lot) : citations non retenues")
        elif ci is not None:
            morceaux.append(f"commit introducteur {ci['hash'][:12]} ({ci['date']}) : aucune référence "
                             "Git résoluble dans son message (hors son propre hash)")
        else:
            morceaux.append("aucun commit introducteur trouvé dans l'historique")
        entree["non_preuve_raison"] = " ; ".join(morceaux) + "."
    return entree


class HistoriqueIncomplet(RuntimeError):
    """L'historique Git est superficiel et n'a pas pu être complété (pas de remote,
    pas de réseau). Levée plutôt que de laisser le script produire un résultat qui a
    l'air correct mais ne l'est pas — cf. assurer_historique_complet()."""


def assurer_historique_complet():
    """Complète un clone superficiel AVANT toute opération dépendant de l'historique.

    BUG mesuré, distinct de git_ref_exists() ci-dessus et plus profond : sur un clone
    à profondeur 1 (`--depth 1`, la valeur par défaut d'`actions/checkout` sans
    `fetch-depth` explicite — non touché ici, `.github/workflows/ci.yml` est hors
    périmètre de cette PR, actif sous #504), `git log -1 --format=%H -- <pathspec>`
    ne rend pas un résultat vide quand le seul commit disponible ne touche pas ce
    pathspec : il rend CE COMMIT quand même. Reproduit : sur un clone à profondeur 1
    de ce dépôt, `git log -1 --format=%H -- evidence registries Registres` rendait le
    commit qui AJOUTE ce correctif — qui ne touche ni evidence/ ni registries/ ni
    Registres/ — au lieu de rien. `dernier_commit_perimetre()` et `commit_introducteur()`
    en dépendent tous les deux : les deux rendaient un résultat FAUX, pas vide, donc
    aucun repli n'était déclenché. `git fetch --unshallow` avant toute lecture
    d'historique ferme la classe entière plutôt qu'un symptôme : vérifié en session,
    `git log` redevient correct après, sans autre changement.
    """
    r = sh(["git", "rev-parse", "--is-shallow-repository"])
    if r.stdout.strip() != "true":
        return
    r = sh(["git", "fetch", "--unshallow", "--quiet"])
    if r.returncode != 0:
        raise HistoriqueIncomplet(
            "clone superficiel et git fetch --unshallow a échoué "
            f"(rc={r.returncode}) : {r.stderr.strip()!r} — "
            "l'historique est insuffisant pour un résultat fiable, refus de produire "
            "un index construit sur un pathspec-log potentiellement faux."
        )


def dernier_commit_perimetre():
    """Dernier commit qui touche réellement evidence/**, registries/** ou Registres/**
    — PAS `HEAD`. HEAD inclurait, dès qu'il est committé, le commit qui ajoute cet
    index lui-même : un fichier ne peut pas contenir son propre hash (même principe
    que l'exclusion défensive du hash du commit introducteur en méthode 2). Ce commit
    d'index ne touche que docs/audit/ et scripts/, hors des racines indexées, donc cet
    ancrage reste stable avant et après qu'il soit committé."""
    r = sh(["git", "log", "-1", "--format=%H", "--"] + ROOTS_INDEXES)
    h = r.stdout.strip()
    if h:
        return h
    return sh(["git", "rev-parse", "HEAD"]).stdout.strip()  # repli : aucun commit ne touche encore ces racines


def construire_index():
    assurer_historique_complet()
    head = dernier_commit_perimetre()
    paths = git_tracked_files(ROOTS_INDEXES)
    paths = [p for p in paths if not est_exclu(p)]

    entrees = [analyser_fichier(p) for p in paths]
    n_prouve = sum(1 for e in entrees if e["statut"] == "PROUVE")
    n_non_prouve = len(entrees) - n_prouve

    stats_par_racine = {}
    for racine in ROOTS_INDEXES:
        sous = [e for e in entrees if e["chemin"] == racine or e["chemin"].startswith(racine + "/")]
        stats_par_racine[racine] = {
            "total": len(sous),
            "prouve": sum(1 for e in sous if e["statut"] == "PROUVE"),
            "non_prouve": sum(1 for e in sous if e["statut"] == "NON_PROUVE"),
        }

    index = {
        "genere_par": "scripts/evidence_index.py",
        "ne_pas_editer_a_la_main": True,
        "issue": "https://github.com/leon36000/OPSYS-AI/issues/593",
        "mesure_a_commit": head,
        "perimetre": {
            "inclus": [r + "/**" for r in ROOTS_INDEXES],
            "exclus": [
                {"chemin": "evidence/tasks/EXT-AUD-001-A1-R12-CANDIDATE/**",
                 "raison": "territoire actif de la PR #566, laissé intact"},
                {"chemin": "reviews/**", "raison": REVIEWS_EXCLUSION_LINE},
            ],
        },
        "granularite": "un fichier versionné (git ls-files) = une entrée",
        "vocabulaire_liaison_code": CHAMPS_COMMIT + CHAMPS_TREE + CHAMPS_REF + [CHAMP_DIFF_SHA256, CHAMP_EXPORTS],
        "vocabulaire_exclu_du_scan_prose": ["payload.evenement (registries/ledger/*.jsonl) et tout autre champ de texte libre"],
        "stats": {"total_entrees": len(entrees), "prouve": n_prouve, "non_prouve": n_non_prouve,
                   "par_racine": stats_par_racine},
        "entrees": entrees,
    }
    return index


def rendre_markdown(index):
    lignes = []
    lignes.append("# Index des liaisons preuves/registres -> code (R4-S11)")
    lignes.append("")
    lignes.append(f"Généré par `{index['genere_par']}` — **ne pas éditer à la main**, relancer le script.")
    lignes.append(f"Issue : {index['issue']}")
    lignes.append(f"Mesuré à commit `{index['mesure_a_commit']}`.")
    lignes.append("")
    lignes.append(f"**{REVIEWS_EXCLUSION_LINE}**")
    lignes.append("")
    lignes.append("`evidence/tasks/EXT-AUD-001-A1-R12-CANDIDATE/**` : territoire actif de la PR #566, laissé intact et non indexé.")
    lignes.append("")
    s = index["stats"]
    lignes.append(f"## Statistiques ({s['total_entrees']} entrées)")
    lignes.append("")
    lignes.append("| Racine | Entrées | PROUVÉ | NON_PROUVÉ |")
    lignes.append("|---|---:|---:|---:|")
    for racine, st in s["par_racine"].items():
        lignes.append(f"| `{racine}/` | {st['total']} | {st['prouve']} | {st['non_prouve']} |")
    lignes.append(f"| **total** | **{s['total_entrees']}** | **{s['prouve']}** | **{s['non_prouve']}** |")
    lignes.append("")
    lignes.append("Granularité : " + index["granularite"] + ".")
    lignes.append("")
    lignes.append("## Méthode (résumé — détail complet dans l'en-tête de `scripts/evidence_index.py`)")
    lignes.append("")
    lignes.append("1. **champ-explicite** — vocabulaire : `" + "`, `".join(index["vocabulaire_liaison_code"]) + "`.")
    lignes.append("2. **commit-introducteur** — commit qui a ajouté le chemin ; message complet scanné.")
    lignes.append("")
    lignes.append("Champs de texte libre jamais scannés (risque de faux positif, cf. #591) : " +
                   "; ".join(index["vocabulaire_exclu_du_scan_prose"]) + ".")
    lignes.append("")
    lignes.append("## Entrées NON_PROUVÉES")
    lignes.append("")
    non_prouve = [e for e in index["entrees"] if e["statut"] == "NON_PROUVE"]
    if not non_prouve:
        lignes.append("(aucune)")
    else:
        lignes.append("| Chemin | Raison |")
        lignes.append("|---|---|")
        for e in non_prouve:
            raison = e.get("non_preuve_raison", "").replace("|", "\\|")
            lignes.append(f"| `{e['chemin']}` | {raison} |")
    lignes.append("")
    lignes.append("## Entrées PROUVÉES")
    lignes.append("")
    prouve = [e for e in index["entrees"] if e["statut"] == "PROUVE"]
    if not prouve:
        lignes.append("(aucune)")
    else:
        lignes.append("| Chemin | Liaisons vérifiées |")
        lignes.append("|---|---|")
        for e in prouve:
            verifs = [f"{l['type']}:{l['valeur'][:12]}…({l['methode']})" for l in e["liaisons"] if l.get("verifie") is True and l.get("type") in CODE_LINK_TYPES]
            lignes.append(f"| `{e['chemin']}` | {', '.join(verifs)} |")
    lignes.append("")
    return "\n".join(lignes) + "\n"


def rendre_json(index):
    return json.dumps(index, ensure_ascii=False, indent=2) + "\n"


def main():
    check = "--check" in sys.argv[1:]
    index = construire_index()
    json_txt = rendre_json(index)
    md_txt = rendre_markdown(index)

    if check:
        derive = []
        if not os.path.isfile(OUT_JSON) or open(OUT_JSON, encoding="utf-8").read() != json_txt:
            derive.append(OUT_JSON)
        if not os.path.isfile(OUT_MD) or open(OUT_MD, encoding="utf-8").read() != md_txt:
            derive.append(OUT_MD)
        if derive:
            print("EVIDENCE_INDEX: ROUGE — dérive détectée, relancer sans --check pour régénérer :")
            for d in derive:
                print(" -", os.path.relpath(d, ROOT))
            return 1
        print(f"EVIDENCE_INDEX: VERT ({index['stats']['total_entrees']} entrées, "
              f"{index['stats']['prouve']} prouvées, {index['stats']['non_prouve']} non prouvées)")
        return 0

    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        f.write(json_txt)
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write(md_txt)
    print(f"EVIDENCE_INDEX: régénéré ({index['stats']['total_entrees']} entrées, "
          f"{index['stats']['prouve']} prouvées, {index['stats']['non_prouve']} non prouvées) "
          f"-> {os.path.relpath(OUT_JSON, ROOT)}, {os.path.relpath(OUT_MD, ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
