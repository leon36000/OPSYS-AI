"""Vérification RÉELLE du scellement des Evidence Bundles/revues
(proof-sealed, C02-005) — remplace le placeholder BLOCKED de
core-ci.yml.

CONVENTION DE COMMIT (chantier CI-hardening, directive Nathan — dépôt
PRIVÉ, confirmé) : un sous-ensemble MINIMAL de l'Evidence Bundle et des
verdicts de revue scellés est commité dans CE dépôt, sous
`evidence/tasks/<ID>/` — jamais le bundle complet (receipts/stdout.bin,
stderr.bin, copies de fichiers source déjà trackés) qui vit
EXCLUSIVEMENT dans le pack harnais local, hors d'atteinte d'un runner CI
GitHub par construction (mesuré : aucun accès réseau vers la machine
locale depuis un runner GitHub Actions). Ce qui EST commité :

  evidence/tasks/<ID>/evidence.json       — manifeste finalisé
  evidence/tasks/<ID>/reviews/*.json      — verdict(s) civ_review.py (sceau)

RÉVISION 2 (ce fichier) — DÉFAUT STRUCTUREL TROUVÉ PAR REVUE SCELLÉE
INDÉPENDANTE, PAS PAR AUTO-RELECTURE : la revision 1 de ce script (commit
3c2f717) a été soumise à 4 voix indépendantes (GPT-5.6-Terra-Pro,
Muse-Spark-1.2, Qwen3.8-Max via civ_review.py + Claude Opus 5 via
subagent architecte natif, même pack scellé, prompt_sha256 identique
d25fe0276dd72c8d64fb1d59e42a58d80c082406b0692b8dce5814ab96eff9dc). 3/4
REJECT, le 4e APPROVE-avec-objections-majeures. LES 4, INDÉPENDAMMENT,
ont trouvé la MÊME faille centrale : le script vérifiait la COHÉRENCE
INTERNE d'un dossier evidence/tasks/<ID>/ (sceau, vendors, objections)
mais ne liait JAMAIS ce dossier au CODE RÉELLEMENT MODIFIÉ par la PR —
n'importe quel evidence bundle valide, même sans rapport avec le diff
courant, satisfaisait le gate. Corrigé ci-dessous par un manifeste
cryptographique (voir `_diff_sha256_actuel` et le champ
`code_diff_sha256` d'evidence.json) — jamais une rustine cosmétique.

Ce script vérifie, pour le commit HEAD du repo (celui que CI construit) :
  1. `evidence.json` déclare `code_diff_sha256` = sha256 du diff RÉEL
     (texte complet, pas seulement la liste de fichiers) entre
     `origin/main` et HEAD sur le périmètre scellé (`_PATHSPEC_SCELLE`).
     Recalculé indépendamment par ce script et comparé — lie l'evidence
     au code EFFECTIVEMENT livré, ferme le contournement "coller une
     evidence valide mais sans rapport" trouvé par les 4 reviewers.
  2. `evidence.json` déclare un manifeste `reviews` = {nom_fichier:
     sha256} EXHAUSTIF des fichiers sous `reviews/` : tout fichier
     déclaré doit exister avec le hash exact (empêche la SUPPRESSION
     silencieuse d'un verdict gênant après scellement — trouvé
     indépendamment par le reviewer architecte) ; tout fichier PRÉSENT
     doit être déclaré (empêche l'AJOUT après coup d'un faux verdict).
  3. Le(s) verdict(s) de revue partagent le MÊME prompt_sha256 (sceau —
     preuve qu'ils ont vu le pack byte-identique).
  4. Aucune objection "critique" NI "majeure" parmi les objections
     listées (durci en révision 2 — 3/4 reviewers ont jugé le choix
     initial "majeure non bloquante" comme une dette de sécurité
     invisible ; sans mécanisme de résolution cross-round, la lecture
     conservatrice correcte est : présente = non résolue = bloquante).
  5. TOUT verdict != APPROVE bloque (consensus = unanimité, pas un
     comptage de majorité).
  6. Au moins N vendors DISTINCTS (anti-Sybil, `_vendor_of`) ont voté
     APPROVE — N configurable via --min-vendors (défaut 1).

LIMITATION CONNUE ET ASSUMÉE : ce script vérifie la COHÉRENCE
CRYPTOGRAPHIQUE ET STRUCTURELLE du sceau commité, PAS que le contenu
d'un verdict est authentiquement sorti du LLM nommé (aucune
re-vérification cryptographique de provenance LiteLLM depuis ce dépôt —
la même limitation existe déjà côté harnais local, non aggravée ici).

SCHÉMA RÉEL (vérifié contre ~/proof-method/scripts/civ_review.py et
reviews/TEMPLATE-prompt-revue-neutre.md le 2026-08-11 — PAS deviné) :
un verdict brut civ_review.py porte `verdict` (APPROVE|REJECT),
`objections` (liste de {"severite": "critique|majeure|mineure", "fichier",
"description", "preuve"} — EN FRANÇAIS, PAS de champ "status"), et
`reviewer_model` (jamais "vendor" — la famille de vendor se DÉRIVE du nom
de modèle, cf. `_vendor_of` ci-dessous). Le sceau est `prompt_sha256`
(mode neutre) — le mode `--roles` n'est pas couvert par ce script : hors
périmètre des revues neutres utilisées pour ce chantier.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EVIDENCE_ROOT = _REPO_ROOT / "evidence" / "tasks"

# Périmètre scellé : core/ (le code) + le workflow CI lui-même + scripts/
# racine — élargi en révision 2 (un des 4 reviewers a démontré qu'une PR
# modifiant SEULEMENT .github/workflows/core-ci.yml, sans toucher core/,
# contournait entièrement le gate puisque CODE_CHANGE ne portait que sur
# core/). Le gate qui institue le scellement doit lui-même être dans son
# propre périmètre scellé, sinon il peut être désactivé sans preuve.
_PATHSPEC_SCELLE = ("core/", ".github/workflows/core-ci.yml", "scripts/")

# Copie volontaire de tally_reviews.py::_VENDOR — COMPLÈTE (pas un sous-
# ensemble "minimal" : la révision 1 copiait un sous-ensemble et a dérivé
# du canon, trouvé par revue indépendante ; une copie exhaustive élimine
# le jugement "est-ce que ce modèle est assez utilisé pour mériter d'être
# copié", seule source de la dérive). Ce script tourne sur un runner CI
# GitHub sans accès à ~/proof-method — import cross-repo impossible, à
# tenir synchronisé manuellement si le tableau canonique évolue (source :
# ~/proof-method/scripts/tally_reviews.py::_VENDOR).
_VENDOR = {
    "glm": "zhipu",
    "glm-5.2": "zhipu",
    "glm52": "zhipu",
    "memory-quality": "zhipu",
    "deepseek": "deepseek",
    "deepseek-v4-pro": "deepseek",
    "deepseek-v4-flash": "deepseek",
    "kimi": "moonshot",
    "kimi-2.7": "moonshot",
    "kimi-k2.7-code": "moonshot",
    "kimi-k3": "moonshot",
    "composer": "xai",
    "composer-2.5": "xai",
    "grok": "xai",
    "grok-4.5": "xai",
    "gemini": "google",
    "gemini-3.1-pro": "google",
    "gemini-3.1-pro-or": "google",
    "qwen": "alibaba",
    "qwen3.7-max": "alibaba",
    "qwen3.8-max": "alibaba",
    "gpt-5.6-terra-pro": "openai",
    "gpt-5.6-luna-pro": "openai",
    "gpt": "openai",
    "longcat": "meituan",
    "longcat-2.0": "meituan",
    "mimo": "xiaomi",
    "mimo-pro-v2": "xiaomi",
    "mimo-v2.5-pro": "xiaomi",
    "minimax-m3": "minimax",
    "nemotron": "nvidia",
    "tencent-hy3": "tencent",
    "hy3": "tencent",
    # Voix hors roster LiteLLM (subagent Claude natif, jamais dans le
    # canon tally_reviews.py puisque non appelable par civ_review.py).
    "claude-opus-5-native-architecte": "anthropic-native",
}


def _vendor_of(model_or_vendor: str) -> str:
    """Retourne la famille de vendor d'un identifiant de modèle/reviewer.
    Modèle absent du tableau : traité comme son propre vendor singleton
    (jamais fusionné à tort avec un autre — fail-closed sur l'inconnu,
    même choix par défaut que tally_reviews.py::vendor_of)."""
    key = (model_or_vendor or "").strip().lower()
    return _VENDOR.get(key, key)


class ScellementInvalide(ValueError):
    """Le sceau d'une revue committée est structurellement invalide."""


class GitIndisponible(RuntimeError):
    """git n'a pas pu produire le diff attendu — fail-closed, jamais un
    hash vide interprété comme "aucun changement"."""


def _diff_sha256_actuel(*, base: str = "origin/main") -> str:
    """Sha256 du diff RÉEL (texte complet, verbatim) entre `base` et HEAD
    sur `_PATHSPEC_SCELLE`. MÊME fonction utilisée pour (a) calculer la
    valeur embarquée dans evidence.json au moment du scellement local et
    (b) la revérification côté CI — garantit la reproductibilité, jamais
    deux implémentations parallèles qui pourraient diverger."""
    resultat = subprocess.run(
        ["git", "diff", f"{base}...HEAD", "--", *_PATHSPEC_SCELLE],
        capture_output=True, text=True, cwd=_REPO_ROOT, timeout=60,
    )
    if resultat.returncode != 0:
        raise GitIndisponible(f"git diff a échoué (rc={resultat.returncode}) : {resultat.stderr.strip()}")
    return hashlib.sha256(resultat.stdout.encode("utf-8")).hexdigest()


def _charger_verdicts(dossier_task: Path) -> list[dict]:
    dossier_reviews = dossier_task / "reviews"
    if not dossier_reviews.is_dir():
        return []
    verdicts = []
    for fichier in sorted(dossier_reviews.glob("*.json")):
        try:
            verdicts.append(json.loads(fichier.read_text(encoding="utf-8")))
        except json.JSONDecodeError as exc:
            raise ScellementInvalide(f"{fichier} : JSON invalide ({exc})") from None
    return verdicts


def _verifier_manifeste_reviews(dossier_task: Path, manifeste: dict) -> list[str]:
    """Vérifie que le manifeste `reviews` d'evidence.json correspond
    EXACTEMENT (bijection, pas seulement sous-ensemble) aux fichiers
    présents sous reviews/ — ferme la suppression silencieuse d'un
    verdict gênant ET l'ajout après coup d'un faux verdict (les 2
    attaques trouvées indépendamment par revue architecte)."""
    erreurs: list[str] = []
    if "reviews" not in manifeste:
        return ["  evidence.json : champ \"reviews\" (manifeste des verdicts) absent — RÉGRESSION vers la faille rev.1"]
    declares = manifeste.get("reviews")
    if not isinstance(declares, dict):
        return ["  evidence.json : champ \"reviews\" doit être un objet {nom_fichier: sha256}"]
    # declares == {} est valide EN SOI (0 déclaré) — si 0 fichier est aussi
    # présent sur disque, c'est cohérent ; le cas "aucun verdict du tout"
    # est un problème DISTINCT, détecté et rapporté plus clairement par
    # le contrôle "aucun verdict" en aval (_charger_verdicts), pas ici.

    dossier_reviews = dossier_task / "reviews"
    presents = {p.name for p in dossier_reviews.glob("*.json")} if dossier_reviews.is_dir() else set()

    for nom, sha_attendu in declares.items():
        chemin = dossier_reviews / nom
        if not chemin.exists():
            erreurs.append(f"  manifeste reviews : {nom} déclaré mais ABSENT du disque (verdict supprimé après scellement ?)")
            continue
        sha_reel = hashlib.sha256(chemin.read_bytes()).hexdigest()
        if sha_reel != sha_attendu:
            erreurs.append(f"  manifeste reviews : {nom} présent mais hash NE CORRESPOND PAS (attendu {sha_attendu[:12]}…, réel {sha_reel[:12]}…)")

    non_declares = presents - set(declares)
    if non_declares:
        erreurs.append(f"  manifeste reviews : fichier(s) présent(s) mais NON déclaré(s) (ajout après coup ?) : {sorted(non_declares)}")

    return erreurs


def verifier_task(task_id: str, *, min_vendors_approve: int = 1, diff_sha256_attendu: str | None) -> tuple[bool, str]:
    dossier_task = _EVIDENCE_ROOT / task_id
    lignes = [f"--- {task_id} ---"]

    evidence_json = dossier_task / "evidence.json"
    if not evidence_json.exists():
        lignes.append("  evidence.json absent — aucun scellement à vérifier pour cette tâche")
        return False, "\n".join(lignes)

    try:
        manifeste = json.loads(evidence_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        lignes.append(f"  evidence.json : JSON invalide ({exc})")
        return False, "\n".join(lignes)

    lignes.append(f"  evidence.json présent (task_id={manifeste.get('task_id')})")

    # --- Liaison cryptographique evidence <-> code réellement livré ---
    code_diff_declare = manifeste.get("code_diff_sha256")
    if not code_diff_declare:
        lignes.append("  evidence.json : champ \"code_diff_sha256\" absent — evidence non liée au code (RÉGRESSION vers la faille rev.1)")
        return False, "\n".join(lignes)
    if diff_sha256_attendu is None:
        lignes.append("  ERREUR INTERNE : diff_sha256_attendu non fourni par l'appelant (bug d'intégration, jamais un pass silencieux)")
        return False, "\n".join(lignes)
    if code_diff_declare != diff_sha256_attendu:
        lignes.append(
            f"  code_diff_sha256 NE CORRESPOND PAS au diff réel de cette PR "
            f"(déclaré {code_diff_declare[:12]}…, réel {diff_sha256_attendu[:12]}…) "
            "— cette evidence n'atteste PAS du code effectivement livré"
        )
        return False, "\n".join(lignes)
    lignes.append(f"  code_diff_sha256 conforme au diff réel : {diff_sha256_attendu[:12]}…")

    # --- Manifeste reviews (bijection déclaré <-> disque) ---
    erreurs_manifeste = _verifier_manifeste_reviews(dossier_task, manifeste)
    if erreurs_manifeste:
        lignes.extend(erreurs_manifeste)
        return False, "\n".join(lignes)

    verdicts = _charger_verdicts(dossier_task)
    if not verdicts:
        lignes.append("  aucun verdict de revue committé sous reviews/")
        return False, "\n".join(lignes)

    sceaux: set[str | None] = {v.get("prompt_sha256") for v in verdicts}
    if len(sceaux) != 1 or None in sceaux:
        lignes.append(f"  sceau prompt_sha256 INCOHÉRENT entre verdicts : {sceaux}")
        return False, "\n".join(lignes)
    sceau_unique = next(iter(sceaux))
    assert sceau_unique is not None  # narrowing : None déjà exclu par la condition ci-dessus
    lignes.append(f"  sceau prompt_sha256 identique sur {len(verdicts)} verdict(s) : {sceau_unique[:12]}…")

    # Champ réel : "severite" (français, critique|majeure|mineure) — jamais
    # "severity"/"status" (n'existent pas dans le schéma civ_review réel,
    # cf. TEMPLATE-prompt-revue-neutre.md, vérifié au module).
    for niveau in ("critique", "majeure"):
        objections_niveau = [
            obj
            for v in verdicts
            for obj in v.get("objections", [])
            if str(obj.get("severite", "")).strip().casefold() == niveau
        ]
        if objections_niveau:
            lignes.append(f"  {len(objections_niveau)} objection(s) {niveau.upper()}(S) présente(s) — round non consensuel")
            for obj in objections_niveau:
                lignes.append(f"    - {obj.get('fichier', '?')} : {obj.get('description', '?')}")
            return False, "\n".join(lignes)

    verdicts_rejet = [v for v in verdicts if v.get("verdict") != "APPROVE"]
    if verdicts_rejet:
        rejeteurs = sorted({str(v.get("reviewer_model", "?")) for v in verdicts_rejet})
        lignes.append(f"  {len(verdicts_rejet)} verdict(s) non-APPROVE (REJECT) — consensus non atteint : {rejeteurs}")
        return False, "\n".join(lignes)

    vendors_approve: set[str] = {
        _vendor_of(str(v.get("reviewer_model", "")))
        for v in verdicts
        if v.get("verdict") == "APPROVE" and v.get("reviewer_model")
    }
    lignes.append(f"  {len(vendors_approve)} vendor(s) distinct(s) APPROVE : {sorted(vendors_approve)}")
    if len(vendors_approve) < min_vendors_approve:
        lignes.append(f"  insuffisant (minimum requis : {min_vendors_approve})")
        return False, "\n".join(lignes)

    lignes.append("  OK — scellé et lié au code réel")
    return True, "\n".join(lignes)


def main(argv: list[str] | None = None) -> int:
    """Sans argument : vérifie TOUTES les tâches sous evidence/tasks/
    (usage manuel/local). Avec --task <ID> (répétable) : vérifie
    UNIQUEMENT les tâches nommées. --min-vendors N (défaut 1) : élève le
    seuil de vendors distincts APPROVE exigé. --diff-base REF (défaut
    origin/main) : base du diff scellé, pour usage local hors CI où
    origin/main peut différer. --emit-code-diff-sha256 : imprime UNIQUEMENT
    le hash du diff actuel et quitte (0) — mode utilitaire pour peupler
    evidence.json au moment du scellement, garantit que la même fonction
    calcule les 2 côtés de la comparaison (jamais 2 implémentations qui
    pourraient diverger)."""
    args = argv if argv is not None else sys.argv[1:]
    task_ids: list[str] = []
    min_vendors = 1
    diff_base = "origin/main"
    emettre_hash_seul = False
    i = 0
    while i < len(args):
        if args[i] == "--task" and i + 1 < len(args):
            task_ids.append(args[i + 1])
            i += 2
        elif args[i] == "--min-vendors" and i + 1 < len(args):
            min_vendors = int(args[i + 1])
            i += 2
        elif args[i] == "--diff-base" and i + 1 < len(args):
            diff_base = args[i + 1]
            i += 2
        elif args[i] == "--emit-code-diff-sha256":
            emettre_hash_seul = True
            i += 1
        elif args[i].startswith("--"):
            print(f"ERREUR: option inconnue: {args[i]}", file=sys.stderr)
            return 3
        else:
            i += 1

    if emettre_hash_seul:
        try:
            print(_diff_sha256_actuel(base=diff_base))
        except GitIndisponible as exc:
            print(f"ERREUR: {exc}", file=sys.stderr)
            return 1
        return 0

    if not _EVIDENCE_ROOT.is_dir():
        print(
            "PROOF_SEALED: ROUGE — evidence/tasks/ absent du dépôt "
            "(aucun Evidence Bundle committé pour cette PR).",
            file=sys.stderr,
        )
        return 1

    if task_ids:
        manquants = [t for t in task_ids if not (_EVIDENCE_ROOT / t).is_dir()]
        if manquants:
            print(f"PROOF_SEALED: ROUGE — dossier(s) evidence/tasks/ absent(s) pour : {manquants}", file=sys.stderr)
            return 1
        cibles = task_ids
    else:
        cibles = sorted(p.name for p in _EVIDENCE_ROOT.iterdir() if p.is_dir())
        if not cibles:
            print("PROOF_SEALED: ROUGE — evidence/tasks/ existe mais ne contient aucune tâche.", file=sys.stderr)
            return 1

    try:
        diff_sha256_attendu = _diff_sha256_actuel(base=diff_base)
    except GitIndisponible as exc:
        print(f"PROOF_SEALED: ROUGE — {exc}", file=sys.stderr)
        return 1

    tout_ok = True
    for task_id in cibles:
        ok, rapport = verifier_task(task_id, min_vendors_approve=min_vendors, diff_sha256_attendu=diff_sha256_attendu)
        print(rapport)
        tout_ok = tout_ok and ok

    if tout_ok:
        print(f"PROOF_SEALED: VERT ({len(cibles)} tâche(s) scellée(s) vérifiée(s), liées au code réel)")
        return 0
    print("PROOF_SEALED: ROUGE — voir détail ci-dessus.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
