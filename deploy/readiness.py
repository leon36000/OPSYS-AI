"""Compose health gate: schema, generated native model config, secrets, and local console."""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from opsys import departements, modeles, openclaw, stockage
from opsys.memoire.embeddings import ENV_MODELE, ENV_URL, ErreurEmbeddings


def main() -> int:
    problemes: list[str] = []
    attentes: list[str] = []
    paliers: dict = {}
    catalogue_pret = False
    mode = os.environ.get("OPSYS_MODE_FOURNISSEUR", "natif")
    config_dir = Path(os.environ.get("OPENCLAW_CONFIG_DIR", "/openclaw-config"))

    try:
        current = stockage.revision_courante()
        known = stockage.revision_connue(current)
        if current == "aucune" or not known:
            problemes.append("migrations: schéma absent ou révision inconnue")
        else:
            print(f"ready migrations: {current}")
    except Exception as exc:  # health output must never reveal database URLs
        problemes.append(f"migrations: indisponibles ({type(exc).__name__})")

    try:
        paliers = modeles.charger_paliers()
        deps = departements.charger_departements()
        requis = {dep.modeles[usage] for dep in deps.values()
                  for usage in dep.modeles}
        absents = sorted(requis - set(paliers))
        if absents:
            attentes.append(f"configuration: paliers non configurés ({', '.join(absents)})")
        else:
            racine = openclaw.fichier_racine(config_dir)
            model_file = config_dir / "opsys" / "models.json"
            if not racine.is_file() or openclaw.includes_manquants(config_dir):
                problemes.append("configuration: racine OpenClaw absente ou fragments OPSYS non inclus")
            elif not model_file.is_file():
                problemes.append("configuration: opsys/models.json absent")
            else:
                model_config = json.loads(model_file.read_text(encoding="utf-8"))
                providers = model_config.get("providers") if isinstance(model_config, dict) else None
                if mode == "litellm":
                    expected = {
                        f"opsys-{dep.prefixe_outils}": openclaw.fournisseur_departement(
                            dep, paliers, os.environ.get("OPSYS_PASSERELLE_URL", "")
                        ) for dep in deps.values()
                    }
                else:
                    # Même projection que generer(), notamment custom -> opsys-<palier>.
                    expected = openclaw._configuration_fournisseurs_natifs(paliers)
                if not isinstance(providers, dict) or any(
                    providers.get(nom) != conf for nom, conf in expected.items()
                ):
                    problemes.append("configuration: catalogue models.json absent ou périmé")
                else:
                    catalogue_pret = True
                    print("ready configuration: paliers et fragments présents")
    except Exception as exc:
        problemes.append(f"configuration: invalide ({type(exc).__name__})")

    if mode == "natif":
        secrets = openclaw.secrets_modeles_manquants(paliers, os.environ)
    elif mode == "litellm":
        secrets = [name for name in ("LITELLM_MASTER_KEY",) if not os.environ.get(name)]
        secrets.extend(f"OPSYS_CLE_M{i}" for i in range(1, 11) if not os.environ.get(f"OPSYS_CLE_M{i}"))
        if not os.environ.get("OPSYS_PASSERELLE_URL", "").startswith(("http://", "https://")):
            problemes.append("configuration: OPSYS_PASSERELLE_URL requise en mode litellm")
    else:
        secrets = []
        problemes.append("configuration: OPSYS_MODE_FOURNISSEUR invalide")
    if secrets:
        attentes.append(f"secrets: variables requises absentes ({', '.join(sorted(secrets))})")
    else:
        print("ready secrets: variables requises présentes")

    try:
        # Validation pure et partagée avec le générateur : aucun appel embeddings/ONNX.
        memoire_attendue = openclaw._configuration_memoire(os.environ)
    except Exception as exc:
        url = os.environ.get(ENV_URL, "").strip().rstrip("/")
        url_invalide = False
        if url:
            # Même parser et critères que ClientEmbeddings.__post_init__, même si
            # depuis_env s'arrête d'abord sur un modèle absent. Aucun modèle fictif.
            try:
                parties = urllib.parse.urlsplit(url)
                url_invalide = parties.scheme not in ("http", "https") or not parties.hostname
            except ValueError:
                url_invalide = True
        absentes = [nom for nom in (ENV_URL, ENV_MODELE) if not os.environ.get(nom, "").strip()]
        absence_contractuelle = (
            isinstance(exc, ValueError) and not url and str(exc).startswith(
                f"configuration mémoire (ADR-0010, Couche A) : {ENV_URL} absente"
            )
        ) or (
            isinstance(exc, ErreurEmbeddings) and url and not os.environ.get(ENV_MODELE, "").strip()
            and str(exc).startswith(f"{ENV_URL} est définie mais {ENV_MODELE} est absente")
        )
        if url_invalide:
            problemes.append(f"mémoire: {ENV_URL} invalide")
        elif absence_contractuelle and absentes:
            attentes.append(f"configuration: embeddings requis absents ({', '.join(absentes)})")
        else:
            problemes.append(f"mémoire: configuration invalide ({type(exc).__name__})")
    else:
        if catalogue_pret:
            try:
                memoire = json.loads((config_dir / "opsys" / "memory.json").read_text(encoding="utf-8"))
                if memoire != memoire_attendue:
                    problemes.append("mémoire: memory.json périmé")
                else:
                    print("ready mémoire: configuration embeddings et fragment cohérents")
            except Exception as exc:
                problemes.append(f"mémoire: fragment indisponible ou invalide ({type(exc).__name__})")

    if mode == "litellm":
        base = os.environ.get("OPSYS_PASSERELLE_URL", "").rstrip("/")
        if not base.startswith(("http://", "https://")):
            problemes.append("gateway: LiteLLM URL absente ou invalide")
        else:
            try:
                with urllib.request.urlopen(f"{base}/health/liveliness", timeout=2) as response:
                    if response.status < 500:
                        print("ready gateway: LiteLLM répond")
                    else:
                        problemes.append(f"gateway: LiteLLM HTTP {response.status}")
            except (OSError, urllib.error.URLError) as exc:
                problemes.append(f"gateway: LiteLLM indisponible ({type(exc).__name__})")

    try:
        with urllib.request.urlopen("http://127.0.0.1:8700/connexion", timeout=2) as response:
            if response.status != 200:
                problemes.append(f"console: HTTP {response.status}")
            else:
                print("ready console: /connexion HTTP 200")
    except (OSError, urllib.error.URLError) as exc:
        problemes.append(f"console: indisponible ({type(exc).__name__})")

    for probleme in problemes + attentes:
        print(f"not ready {probleme}", file=sys.stderr)
    # 3 est réservé aux paramètres opérateur absents ; tout problème runtime prime.
    return 1 if problemes else 3 if attentes else 0


if __name__ == "__main__":
    raise SystemExit(main())
