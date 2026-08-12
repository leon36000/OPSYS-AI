#!/usr/bin/env python3
"""Phase C — distribution du pack aux modeles via la passerelle + collecte des verdicts scelles (C-02, brique no 13).
MODE LIVE: requiert la passerelle (P0-2). BLOCKED tant que la clef n'est pas tournee (R-002).
MODE --mock: auto-test du circuit collecte->tally avec verdicts factices (preuve du mecanisme)."""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

HERE = os.path.dirname(__file__)
PACK_PATH = os.path.join(HERE, "..", "PACK_CONSENSUS_GRS_v2.md")

# Table statique alias -> vendor (ANTI-FABRICATION)
VENDORS_TABLE: dict[str, str] = {
    "Kimi-2.7": "moonshot",
    "Kimi-K3": "moonshot",
    "DeepSeek-V4-Pro": "deepseek",
    "GLM-5.2": "zhipu",
    "Gemini-3.1-Pro": "google",
    "LongCat-2.0": "meituan",
    "Qwen3.7-Max": "alibaba",
    "MiMo-Pro-V2": "xiaomi",
    "Gemini-3.6-Flash": "google",
    "Grok-4.5": "xai",
    "Composer-2.5": "xai",
    "MiniMax-M3": "minimax",
}

DEFAULT_MODELS = [
    "Kimi-2.7",
    "Kimi-K3",
    "DeepSeek-V4-Pro",
    "GLM-5.2",
    "Gemini-3.1-Pro",
    "LongCat-2.0",
    "Qwen3.7-Max",
    "MiMo-Pro-V2",
    "Gemini-3.6-Flash",
    "Grok-4.5",
    "Composer-2.5",
    "MiniMax-M3",
]

PROMPT_PREAMBLE = """Vous etes un reviseur technique independant. Evaluez le pack ci-dessous.
REPONDEZ UNIQUEMENT avec un JSON strict (pas de texte autour).
Schema obligatoire :
{
  "reviewer": "VOTRE_ALIAS_ICI",
  "vendor": "VOTRE_VENDOR_ICI",
  "verdict": "APPROVE" ou "REJECT",
  "objections": [
    {"severite": "critique" | "majeure" | "mineure", "fichier": "...", "description": "...", "preuve": "..."}
  ],
  "dimensions": {...},
  "verdict_final": "...",
  "reserves": "...",
  "reponses_Q": {...}
}
Choix force : verdict doit etre exactement APPROVE ou REJECT.
Les objections sont obligatoires (liste vide si aucune). Chaque objection doit avoir severite dans {critique,majeure,mineure}, fichier, description, preuve.
Les champs reviewer, vendor, date_heure et prompt_sha256 seront normalises par le script collecteur."""


class TransportError(Exception):
    pass


def _extract_json(text: str) -> dict:
    search_start = 0
    while True:
        start = text.find("{", search_start)
        if start == -1:
            raise ValueError("aucun objet JSON trouve")
        count = 0
        in_string = False
        escape = False
        candidate_end = -1
        for i, ch in enumerate(text[start:], start=start):
            if in_string:
                if escape:
                    escape = False
                    continue
                if ch == "\\":
                    escape = True
                    continue
                if ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
                continue
            if ch == "{":
                count += 1
            elif ch == "}":
                count -= 1
                if count == 0:
                    candidate_end = i
                    break
        if candidate_end != -1:
            candidate = text[start : candidate_end + 1]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                pass
        search_start = start + 1


def _validate_verdict(data: dict) -> None:
    if not isinstance(data, dict):
        raise ValueError("le verdict n'est pas un objet JSON")
    if data.get("verdict") not in ("APPROVE", "REJECT"):
        raise ValueError("verdict hors enum")
    objections = data.get("objections")
    if not isinstance(objections, list):
        raise ValueError("objections non-liste")
    for idx, obj in enumerate(objections):
        if not isinstance(obj, dict):
            raise ValueError(f"objection {idx} non-objet")
        for key in ("severite", "fichier", "description", "preuve"):
            if key not in obj:
                raise ValueError(f"objection {idx} champ manquant '{key}'")
        if obj["severite"] not in ("critique", "majeure", "mineure"):
            raise ValueError(f"objection {idx} severite hors enum")


def _is_valid_verdict(data: dict) -> bool:
    try:
        _validate_verdict(data)
        return True
    except Exception:
        return False


def _parse_response(raw: str) -> dict:
    data = _extract_json(raw)
    _validate_verdict(data)
    return data


_SCHEMAS_RESEAU_AUTORISES = frozenset({"http", "https"})


def _valider_schema_url(url: str) -> None:
    """Refuse toute URL dont le schéma n'est pas explicitement autorisé.

    LISTE BLANCHE, jamais liste noire : un schéma inconnu est refusé par défaut.
    L'URL est construite depuis LITELLM_BASE_URL, une variable d'environnement —
    rien ne garantit qu'elle porte un schéma réseau, et `file:` serait ouvert par
    `urlopen` sans cette garde. Extraite en fonction nommée pour être PROUVÉE par
    scripts/tests/test_consensus_run_scheme.py plutôt qu'affirmée en commentaire.
    """
    scheme = urllib.parse.urlsplit(url).scheme
    if scheme not in _SCHEMAS_RESEAU_AUTORISES:
        raise TransportError(
            f"Schéma refusé '{scheme}' pour l'URL issue de la variable d'environnement "
            "de la passerelle LITELLM_BASE_URL"
        )


def make_real_transport(timeout: int, max_tokens: int):
    base_url = os.environ.get("LITELLM_BASE_URL", "http://localhost:4000").rstrip("/")
    api_key = os.environ.get("LITELLM_API_KEY")  # proof:allow — lecture de variable d'environnement, aucun secret littéral
    url = base_url + "/v1/chat/completions"
    _valider_schema_url(url)

    def transport(alias: str, prompt: str) -> str:
        body = {
            "model": alias,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "max_tokens": max_tokens,
        }
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Authorization", f"Bearer {api_key}")
        try:
            # nosec B310 — le schéma est validé en LISTE BLANCHE ({http, https})
            # aux lignes 153-156, AVANT toute construction de requête : un schéma
            # file: ou custom lève TransportError et n'atteint jamais urlopen.
            # bandit est une règle statique qui ne suit pas cette garde en amont ;
            # la garde est prouvée par
            # scripts/tests/test_consensus_run_scheme.py, pas affirmée ici.
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 — schéma validé en liste blanche par _valider_schema_url avant toute requête, prouvé par test_consensus_run_scheme.py
                resp_text = resp.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            raise TransportError(f"HTTP {exc.code} depuis la passerelle") from None
        except urllib.error.URLError as exc:
            raise TransportError(f"erreur reseau: {exc.reason}") from None
        except Exception:
            raise TransportError("erreur de communication avec la passerelle") from None
        try:
            resp_json = json.loads(resp_text)
        except json.JSONDecodeError:
            raise TransportError("reponse non-JSON de la passerelle") from None
        try:
            content = resp_json["choices"][0]["message"]["content"]
        except Exception:
            raise TransportError("format de reponse inattendu") from None
        if not isinstance(content, str):
            raise TransportError("contenu de reponse non textuel") from None
        return content

    return transport


def live(models, transport, outdir, vendor_auteur, pack_path):
    bad = [m for m in models if m not in VENDORS_TABLE]
    if bad:
        print(f"INVALIDE: alias hors table: {', '.join(bad)}", file=sys.stderr)
        return 2

    try:
        pack = Path(pack_path).read_text(encoding="utf-8")
    except Exception as exc:
        print(f"INVALIDE: impossible de lire le pack: {exc}", file=sys.stderr)
        return 2

    prompt = PROMPT_PREAMBLE + "\n\nPACK (VERBATIM):\n" + pack
    prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()

    outdir_path = Path(outdir)
    raw_dir = outdir_path / "raw"
    outdir_path.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    tmp_prefix = ".tmp-"
    to_call = []
    reused = []

    for alias in models:
        tmp_file = outdir_path / f"{tmp_prefix}{alias}"
        if tmp_file.exists():
            try:
                data = json.loads(tmp_file.read_text(encoding="utf-8"))
                if (
                    isinstance(data, dict)
                    and data.get("prompt_sha256") == prompt_sha256
                    and _is_valid_verdict(data)
                ):
                    reused.append(alias)
                    continue
            except (OSError, ValueError):
                # Cache illisible ou JSON invalide : on retombe sur le rappel
                # du modèle. Rétréci pour ne plus masquer le reste.
                pass
        to_call.append(alias)

    if reused:
        print(
            f"Relance: {len(reused)} modele(s) reutilise(s): {', '.join(reused)}",
            file=sys.stderr,
        )

    lock = threading.Lock()

    def process(alias: str):
        try:
            raw = transport(alias, prompt)
            try:
                (raw_dir / f"{alias}.txt").write_text(raw, encoding="utf-8")
            except OSError as exc:
                # L'archive brute est un ARTEFACT DE PREUVE : sa perte doit
                # être visible, jamais silencieuse. Best-effort conservé.
                print(
                    f"AVERTISSEMENT: archive brute {alias}.txt non écrite ({exc}) — "
                    "artefact de preuve manquant",
                    file=sys.stderr,
                )
            data = _parse_response(raw)
            verdict = {
                **data,
                "reviewer": alias,
                "vendor": VENDORS_TABLE[alias],
                "prompt_sha256": prompt_sha256,
                "date_heure": datetime.now(timezone.utc).isoformat(),
            }
            tmp_file = outdir_path / f"{tmp_prefix}{alias}"
            tmp_file.write_text(json.dumps(verdict, ensure_ascii=False), encoding="utf-8")
            with lock:
                pass
            return alias, verdict
        except Exception as exc:
            print(f"{alias}: INVALIDE ({exc})", file=sys.stderr)
            return alias, None

    if to_call:
        max_workers = min(6, len(to_call))
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(process, alias): alias for alias in to_call}
            for future in as_completed(futures):
                future.result()

    missing = [
        alias
        for alias in models
        if not (outdir_path / f"{tmp_prefix}{alias}").exists()
    ]
    if missing:
        print(f"Manquants: {', '.join(missing)}", file=sys.stderr)
        return 2

    for alias in models:
        src = outdir_path / f"{tmp_prefix}{alias}"
        dst = outdir_path / f"{alias}.json"
        os.replace(str(src), str(dst))

    tally_script = os.path.join(HERE, "tally.py")
    rc = subprocess.call([sys.executable, tally_script, str(outdir_path), vendor_auteur])
    if rc == 0:
        print("PREUVE: consensus live -> tally APPROVED")
    elif rc == 3:
        print("PREUVE: consensus live -> tally REJECTED (suite: debat cible D-017)")
    else:
        print(f"BLOCKED: tally a retourne rc={rc}", file=sys.stderr)
    return rc


def mock():
    d = os.path.join(HERE, "..", "registries", "verdicts", "mock-phaseC")
    os.makedirs(d, exist_ok=True)
    for r, vend, verdict, obj in [("glm-5.2","zhipu","APPROVE",[]),
                                  ("gemini-3.1-pro","google","APPROVE",[]),
                                  ("longcat-2.0","meituan","APPROVE",[{"severite":"mineure","fichier":"pack","description":"exemple","preuve":"n/a"}])]:
        json.dump({"reviewer":r,"vendor":vend,"verdict":verdict,"objections":obj},
                  open(os.path.join(d, r + ".json"), "w", encoding="utf-8"), ensure_ascii=False)
    rc = subprocess.call([sys.executable, os.path.join(HERE,"tally.py"), d, "deepseek"])
    print("PREUVE: circuit collecte->tally =", "OK" if rc == 0 else f"echec rc={rc}")
    sys.exit(rc)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Phase C — consensus outille")
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--models", default=None)
    parser.add_argument("--outdir", default=None)
    parser.add_argument("--vendor-auteur", default="anthropic")
    parser.add_argument("--timeout", type=int, default=420)
    parser.add_argument("--max-tokens", type=int, default=8000)
    args = parser.parse_args(argv)

    if args.mock:
        mock()

    if not args.live:
        print("BLOCKED: mode live requiert la passerelle configuree (P0-2) et la clef tournee (P0-4/R-002).")
        sys.exit(4)

    if args.models:
        models = [m.strip() for m in args.models.split(",") if m.strip()]
    else:
        models_env = os.environ.get("CONSENSUS_MODELS")
        if models_env:
            models = [m.strip() for m in models_env.split(",") if m.strip()]
        else:
            models = DEFAULT_MODELS

    outdir = args.outdir
    if outdir is None:
        outdir = os.path.join(HERE, "..", "registries", "verdicts", "phaseC-live")

    api_key = os.environ.get("LITELLM_API_KEY")  # proof:allow — lecture de variable d'environnement, aucun secret littéral
    if not api_key:  # proof:allow — nom de variable, aucun secret littéral
        print("BLOCKED: LITELLM_API_KEY manquante.", file=sys.stderr)
        sys.exit(2)

    transport = make_real_transport(args.timeout, args.max_tokens)
    rc = live(models, transport, outdir, args.vendor_auteur, PACK_PATH)
    sys.exit(rc)


if __name__ == "__main__":
    main()
