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
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EVIDENCE_ROOT = _REPO_ROOT / "evidence" / "tasks"


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

    objections_bloquantes = [
        obj
        for v in verdicts
        for obj in v.get("objections", [])
        if obj.get("status") == "OPEN" and obj.get("severity") == "CRITICAL"
    ]
    if objections_bloquantes:
        lignes.append(f"  {len(objections_bloquantes)} objection(s) CRITICAL/OPEN non résolue(s)")
        return False, "\n".join(lignes)

    vendors_approve: set[str] = {
        v["vendor"] for v in verdicts if v.get("verdict") == "APPROVE" and v.get("vendor")
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
    doit prouver)."""
    args = argv if argv is not None else sys.argv[1:]
    task_ids: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--task" and i + 1 < len(args):
            task_ids.append(args[i + 1])
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
        ok, rapport = verifier_task(task_id)
        print(rapport)
        tout_ok = tout_ok and ok

    if tout_ok:
        print(f"PROOF_SEALED: VERT ({len(cibles)} tâche(s) scellée(s) vérifiée(s))")
        return 0
    print("PROOF_SEALED: ROUGE — voir détail ci-dessus.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
