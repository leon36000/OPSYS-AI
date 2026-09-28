"""Passerelle de modèles LiteLLM (cœur MIT) : un point d'accès unique, des budgets durs.

- Les paliers OPSYS deviennent des alias LiteLLM (`opsys-local`, `opsys-rapide`,
  `opsys-standard`, `opsys-fort`) : le moteur d'agents ne voit que ces 4 noms, et changer de
  fournisseur (cloud ou local) ne touche que ce fichier généré.
- Chaque département reçoit une clé virtuelle LiteLLM avec plafond de tokens par jour
  (`tpd_limit`), et en option un budget en dollars (`max_budget` sur `budget_duration`).
  LiteLLM applique ces plafonds lui-même ; OPSYS lit la dépense par clé pour le dashboard.
Champs de l'API vérifiés dans le code source de LiteLLM (`GenerateRequestBase`, `/key/info`).
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterable, Mapping
from typing import Any

from . import jetons
from .departements import PALIERS, Departement

_CLE_ENV_FOURNISSEUR = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "xai": "XAI_API_KEY",
    "groq": "GROQ_API_KEY",
    "moonshot": "MOONSHOT_API_KEY",
}


def alias_palier(palier: str) -> str:
    return f"opsys-{palier}"


def modele_litellm(conf: Mapping[str, str]) -> dict[str, Any]:
    """`litellm_params` d'un palier (voir opsys.modeles.valider_palier pour le schéma)."""
    fournisseur, modele = conf["provider"], conf["model"]
    if fournisseur == "custom":  # Ollama / vLLM / llama.cpp en mode compatible OpenAI
        return {"model": f"openai/{modele}", "api_base": conf["base_url"], "api_key": "local"}
    if fournisseur == "ollama":
        return {"model": f"ollama_chat/{modele}", "api_base": conf.get("base_url", "http://ollama:11434")}
    params: dict[str, Any] = {
        "model": f"{fournisseur}/{modele}",
        "api_key": f"os.environ/{_CLE_ENV_FOURNISSEUR.get(fournisseur, fournisseur.upper() + '_API_KEY')}",
    }
    if "base_url" in conf:
        params["api_base"] = conf["base_url"]
    return params


def config_litellm(paliers: Mapping[str, Mapping[str, str]], hote_cache: str = "valkey") -> dict[str, Any]:
    """Configuration LiteLLM (proxy_config.yaml) générée depuis les paliers configurés."""
    if not paliers:
        raise ValueError("aucun palier configuré : renseigne au moins 'standard' dans le dashboard")
    return {
        "model_list": [
            {"model_name": alias_palier(nom), "litellm_params": modele_litellm(conf)}
            for nom, conf in sorted(paliers.items(), key=lambda kv: PALIERS.index(kv[0]))
        ],
        "litellm_settings": {
            "drop_params": True,
            "cache": True,
            "cache_params": {"type": "redis", "host": hote_cache, "port": 6379},
        },
        "general_settings": {
            "master_key": "os.environ/LITELLM_MASTER_KEY",
            "database_url": "os.environ/DATABASE_URL",
        },
    }


def empreinte_cle(cle: str) -> str:
    """LiteLLM recommande de passer l'empreinte sha256 de la clé, jamais la clé, dans l'URL."""
    return hashlib.sha256(cle.encode("utf-8")).hexdigest()


class ClientLiteLLM:
    """Client d'administration minimal (urllib) pour les clés virtuelles des départements."""

    def __init__(self, base_url: str, cle_maitre: str, delai: float = 15.0) -> None:
        if not cle_maitre:
            raise ValueError("clé maître LiteLLM absente (LITELLM_MASTER_KEY)")
        self._base = base_url.rstrip("/")
        self._entetes = {"Authorization": f"Bearer {cle_maitre}", "Content-Type": "application/json"}
        self._delai = delai

    def _appel(self, methode: str, chemin: str, corps: Mapping[str, Any] | None = None) -> tuple[int, Any]:
        donnees = json.dumps(corps).encode() if corps is not None else None
        requete = urllib.request.Request(f"{self._base}{chemin}", data=donnees, method=methode,
                                         headers=self._entetes)
        try:
            with urllib.request.urlopen(requete, timeout=self._delai) as reponse:  # noqa: S310 — URL interne
                return reponse.status, json.loads(reponse.read() or b"null")
        except urllib.error.HTTPError as erreur:
            return erreur.code, json.loads(erreur.read() or b"null")

    def info(self, cle: str) -> dict[str, Any] | None:
        statut, corps = self._appel("GET", f"/key/info?key={empreinte_cle(cle)}")
        if statut == 200:
            return corps
        if statut in (400, 404):
            return None
        raise RuntimeError(f"LiteLLM /key/info a répondu {statut} : {corps}")

    def enregistrer_departement(
        self, dep: Departement, cle: str, modeles: Iterable[str], budget_usd_mois: float | None = None
    ) -> str:
        """Crée ou met à jour la clé du département (idempotent). Renvoie 'cree' ou 'mis_a_jour'."""
        if len(cle) < 24:
            raise ValueError(f"{dep.id} : clé virtuelle trop courte (24 caractères minimum)")
        corps: dict[str, Any] = {
            "key": cle,
            "key_alias": f"opsys-{dep.id}",
            "models": sorted(modeles),
            "tpd_limit": dep.budget.tokens_jour,
            "metadata": {"opsys_departement": dep.id, "code": dep.code},
            "tags": ["opsys", dep.id],
            # Cache de prompt injecté par la passerelle pour les fournisseurs qui le supportent.
            "enable_prompt_caching": True,
        }
        if budget_usd_mois is not None:
            corps.update(max_budget=budget_usd_mois, budget_duration="30d")
        existe = self.info(cle) is not None
        statut, reponse = self._appel("POST", "/key/update" if existe else "/key/generate", corps)
        if statut != 200:
            raise RuntimeError(f"LiteLLM a refusé la clé de {dep.id} ({statut}) : {reponse}")
        return "mis_a_jour" if existe else "cree"

    def activite_quotidienne(self, tag: str, debut: dt.date, fin: dt.date) -> list[dict[str, Any]]:
        """Jours d'activité d'un tag (`/tag/daily/activity`, paginé) : dépense et tokens par modèle."""
        jours: list[dict[str, Any]] = []
        page = 1
        while True:
            requete = urllib.parse.urlencode({"tags": tag, "start_date": debut.isoformat(),
                                               "end_date": fin.isoformat(), "page": page, "page_size": 100})
            statut, corps = self._appel("GET", f"/tag/daily/activity?{requete}")
            if statut != 200:
                raise RuntimeError(f"LiteLLM /tag/daily/activity a répondu {statut} : {corps}")
            jours.extend(corps.get("results", []))
            if page >= int(corps.get("metadata", {}).get("total_pages", 1) or 1):
                return jours
            page += 1


def synchroniser_usage(
    client: ClientLiteLLM, cnx: sqlite3.Connection, departements: Iterable[Departement],
    debut: dt.date, fin: dt.date,
) -> int:
    """Recopie la consommation mesurée par LiteLLM (tag = id du département) dans l'état OPSYS.

    Idempotent : les valeurs sont absolues par jour, département et modèle (`litellm:<modèle>`).
    C'est ce qui alimente budgets, alertes et console quand le Core est OpenClaw.
    """
    lignes = 0
    for dep in departements:
        for jour in client.activite_quotidienne(dep.id, debut, fin):
            date = dt.date.fromisoformat(str(jour["date"])[:10])
            modeles = (jour.get("breakdown") or {}).get("models") or {"total": {"metrics": jour.get("metrics", {})}}
            for modele, donnees in modeles.items():
                m = donnees.get("metrics", {})
                jetons.fixer_usage(cnx, date, dep.id, f"litellm:{modele}", int(m.get("successful_requests", 0)), {
                    "tokens_entree": int(m.get("prompt_tokens", 0)),
                    "tokens_sortie": int(m.get("completion_tokens", 0)),
                    "tokens_cache_lus": int(m.get("cache_read_input_tokens", 0)),
                })
                lignes += 1
    return lignes
