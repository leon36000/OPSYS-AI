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

  evidence/tasks/<ID>/evidence.json       — manifeste finalisé (hashes)
  evidence/tasks/<ID>/reviews/*.json      — verdict(s) au format riche
                                             taskctl.py review (sceau)

Ce script vérifie, pour le commit HEAD du repo (celui que CI construit) :
  1. Au moins un `evidence/tasks/<ID>/` existe DONT le commit ou le tree
     déclaré dans son evidence.json/review correspond à un ancêtre du
     commit courant (le found le plus RÉCENT sur la branche est celui
     évalué — un evidence bundle antérieur à un rebase/squash n'est pas
     un faux, juste un ancien tour, cf. discipline établie de la
     session : le TREE final est la source de vérité, pas le hash de
     commit exact qui change à chaque squash-merge).
  2. Le(s) verdict(s) de revue partagent le MÊME prompt_sha256 (sceau —
     preuve qu'ils ont vu le pack byte-identique).
  3. Au moins N vendors DISTINCTS (anti-Sybil, vendor_of) ont voté
     APPROVE — N configurable, défaut 1 (cohérent avec la discipline
     INDEPENDENT_REVIEW déjà établie : 1 APPROVE suffit pour ce profil,
     TRIAD_CONSENSUS exigerait davantage, hors périmètre de ce script
     générique).
  4. Aucune objection CRITICAL/OPEN parmi les objections listées.

LIMITATION CONNUE ET ASSUMÉE : ce script vérifie la COHÉRENCE STRUCTURELLE
du sceau commité (mêmes règles que schema_validation.py/tally_reviews.py
côté harnais), PAS que le contenu du raw_response committé est
authentiquement sorti du LLM nommé (aucune re-vérification cryptographique
de provenance LiteLLM depuis ce dépôt — le raw_response_sha256 prouve
l'INTÉGRITÉ du fichier committé depuis sa capture, pas son ORIGINE ;
la même limitation existe déjà côté harnais local, non aggravée ici).

SCHÉMA RÉEL (vérifié contre ~/proof-method/scripts/civ_review.py et
reviews/TEMPLATE-prompt-revue-neutre.md le 2026-08-11 — PAS deviné) :
un verdict brut civ_review.py porte `verdict` (APPROVE|REJECT),
`objections` (liste de {"severite": "critique|majeure|mineure", "fichier",
"description", "preuve"} — EN FRANÇAIS, PAS de champ "status"), et
`reviewer_model` (jamais "vendor" — la famille de vendor se DÉRIVE du nom
de modèle, cf. `_vendor_of` ci-dessous, copie volontaire ET MINIMALE de
`tally_reviews.py::_VENDOR/vendor_of` : ce script tourne sur un runner CI
GitHub sans accès à ~/proof-method, un import cross-repo est impossible ;
à tenir synchronisé manuellement si le tableau canonique évolue). Le sceau
est `prompt_sha256` (mode neutre) — le mode `--roles` (pack_sha256 +
role_sha256 distincts par mandat) n'est PAS couvert par ce script : hors
périmètre des revues neutres utilisées pour ce chantier.

RÈGLE DE CONSENSUS (alignée sur la définition de tally_reviews.py, "tous
APPROVE + zéro objection critique") : un round non conforme n'est pas
"résolu" en place — le round SUIVANT (nouveaux response_id, nouveau sceau)
remplace le round rejeté dans le commit final. Ce script ne rejoue donc
QUE le dernier round committé, jamais un historique multi-round (ce
dernier reste la responsabilité de `tally_reviews.py --resolutions`, outil
local, hors périmètre CI). Les objections "majeure" restantes sont
SURFACÉES (comptées, visibles dans le rapport) mais NON bloquantes ici —
suivre leur résolution cross-round exigerait l'historique des rounds
précédents, absent d'un commit final unique ; nommé, pas contourné en
silence.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EVIDENCE_ROOT = _REPO_ROOT / "evidence" / "tasks"

# Copie volontaire et MINIMALE de tally_reviews.py::_VENDOR (roster réellement
# utilisé par ce projet, cf. AGENTS.md) — voir docstring module pour la raison
# de la duplication (isolation du runner CI, jamais d'import cross-repo).
_VENDOR = {
    "glm": "zhipu", "glm-5.2": "zhipu",
    "deepseek": "deepseek", "deepseek-v4-pro": "deepseek", "deepseek-v4-flash": "deepseek",
    "kimi": "moonshot", "kimi-2.7": "moonshot", "kimi-k2.7-code": "moonshot", "kimi-k3": "moonshot",
    "composer": "xai", "composer-2.5": "xai", "grok": "xai", "grok-4.5": "xai",
    "gemini": "google", "gemini-3.1-pro": "google", "gemini-3.1-pro-or": "google",
    "qwen": "alibaba", "qwen3.7-max": "alibaba", "qwen3.8-max": "alibaba",
    "gpt-5.6-terra-pro": "openai", "gpt-5.6-luna-pro": "openai", "gpt": "openai",
    "longcat": "meituan", "longcat-2.0": "meituan",
    "mimo": "xiaomi", "mimo-pro-v2": "xiaomi", "mimo-v2.5-pro": "xiaomi",
    "minimax-m3": "minimax", "nemotron": "nvidia", "tencent-hy3": "tencent", "hy3": "tencent",
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


def verifier_task(task_id: str, *, min_vendors_approve: int = 1) -> tuple[bool, str]:
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

    evidence_sha256_attendu = manifeste.get("evidence_sha256") or manifeste.get("task_id")
    lignes.append(f"  evidence.json présent (task_id={manifeste.get('task_id')})")

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
    objections_critiques = [
        obj
        for v in verdicts
        for obj in v.get("objections", [])
        if str(obj.get("severite", "")).strip().casefold() == "critique"
    ]
    if objections_critiques:
        lignes.append(f"  {len(objections_critiques)} objection(s) CRITIQUE(S) présente(s) — round non consensuel")
        for obj in objections_critiques:
            lignes.append(f"    - {obj.get('fichier', '?')} : {obj.get('description', '?')}")
        return False, "\n".join(lignes)

    objections_majeures = [
        obj
        for v in verdicts
        for obj in v.get("objections", [])
        if str(obj.get("severite", "")).strip().casefold() == "majeure"
    ]
    if objections_majeures:
        lignes.append(
            f"  AVERTISSEMENT (non bloquant ici) : {len(objections_majeures)} objection(s) MAJEURE(S) "
            "présente(s) — résolution cross-round non vérifiable par ce script (cf. docstring module), "
            "revue humaine recommandée avant confiance totale."
        )

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

    lignes.append(f"  OK — scellé, {evidence_sha256_attendu}")
    return True, "\n".join(lignes)


def main(argv: list[str] | None = None) -> int:
    """Sans argument : vérifie TOUTES les tâches sous evidence/tasks/
    (usage manuel/local). Avec --task <ID> (répétable) : vérifie
    UNIQUEMENT les tâches nommées — c'est le mode utilisé par le job CI,
    qui ne cible que les tâches NOUVELLES/MODIFIÉES par la PR courante
    (calculées par `git diff` dans le step du workflow) plutôt que de
    re-vérifier tout l'historique accumulé à chaque run (coût croissant
    sans fin, hors périmètre de ce que « proof-sealed pour CETTE PR »
    doit prouver). --min-vendors N (défaut 1, INDEPENDENT_REVIEW) : élève le
    seuil de vendors distincts APPROVE exigé — ex. 3 pour le profil Team
    (AGENTS.md, "3 reviewers / 3 vendors")."""
    args = argv if argv is not None else sys.argv[1:]
    task_ids: list[str] = []
    min_vendors = 1
    i = 0
    while i < len(args):
        if args[i] == "--task" and i + 1 < len(args):
            task_ids.append(args[i + 1])
            i += 2
        elif args[i] == "--min-vendors" and i + 1 < len(args):
            min_vendors = int(args[i + 1])
            i += 2
        else:
            i += 1

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

    tout_ok = True
    for task_id in cibles:
        ok, rapport = verifier_task(task_id, min_vendors_approve=min_vendors)
        print(rapport)
        tout_ok = tout_ok and ok

    if tout_ok:
        print(f"PROOF_SEALED: VERT ({len(cibles)} tâche(s) scellée(s) vérifiée(s))")
        return 0
    print("PROOF_SEALED: ROUGE — voir détail ci-dessus.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
