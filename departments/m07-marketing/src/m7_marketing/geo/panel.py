"""Panel de questions posées aux moteurs d'IA par leurs API OFFICIELLES : ce que le moteur dit de la marque du client.

R4 §4.4 : 20 à 50 questions types, chacune posée N fois à chaque moteur, avec recherche web activée, par l'API
OFFICIELLE du fournisseur. JAMAIS par l'interface grand public d'un moteur, jamais par un service tiers qui la copie
: la liste des moteurs est FERMÉE ; tout autre identifiant (`chatgpt_ui`, `gemini_web`, `google_aio`…) est refusé
(`REJ-GEO-MOTEUR-INTERFACE`). Le dépôt ne contient aucun transport : `PortMoteurNonBranche` refuse, et un
fournisseur d'API réel reste à brancher (jamais exercé ici).

- `planifier_panel` calcule le COÛT d'avance à partir des tarifs que le CLIENT déclare ; un tarif inconnu rend un coût
  `inconnu`, jamais zéro, et un plafond mensuel connu refuse un plan dont le coût dépasse ou ne peut pas être établi.
- `executer_panel` pose les questions et ne GARDE RIEN du texte des réponses (donnée non fiable d'un tiers, qui peut
contenir
  une injection) : seulement `mentionne`, `cite`, les domaines cités, l'empreinte sha256, le moteur et la version
  déclarés. Le jeton sort d'un fournisseur de secret le temps d'UN appel ; il n'est gardé ni écrit nulle part.

Module sans entrée-sortie : le port est injecté.
"""

from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
import re
import unicodedata
import urllib.parse
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from .robots_ia import ErreurGeo

MOTEURS: Mapping[str, str] = {
    "openai_responses_web_search": "OpenAI : API Responses avec l'outil de recherche web",
    "perplexity_sonar": "Perplexity : API Sonar",
    "gemini_grounding": "Google : API Gemini avec ancrage Google Search",
    "anthropic_web_search": "Anthropic : API avec l'outil de recherche web",
}
SOURCE_MOTEURS = "R4 §4.4 (H pour les noms exacts des produits) : à revérifier dans la documentation de chaque éditeur"
PROMPTS_MIN, PROMPTS_MAX = 20, 50
REPETITIONS_MIN, REPETITIONS_MAX = 1, 10
TEXTE_PROMPT_MAX = 300
TEXTE_REPONSE_MAX = 100_000
CITATIONS_MAX = 50
ALIAS_MAX = 10

FournisseurSecret = Callable[[], contextlib.AbstractContextManager[str]]
_ID_PROMPT = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
_DOMAINE = re.compile(r"^(?=.{4,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_NOM = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")


@dataclasses.dataclass(frozen=True)
class ReponseMoteur:
    texte: str
    citations: tuple[str, ...]
    tokens: int
    version_modele: str


class ErreurMoteur(Exception):
    """Échec d'un appel de moteur. `code` : REJ-GEO-MOTEUR-AUTH | -LIMITE | -INDISPONIBLE ; `transitoire` : un
    nouvel essai a
    un sens. Le message d'un transport n'est jamais recopié."""

    def __init__(self, code: str, transitoire: bool = False) -> None:
        super().__init__(code)
        self.code, self.transitoire = code, transitoire


class PortMoteurIA(Protocol):
    def interroger(self, prompt: str, moteur: str, jeton: str) -> ReponseMoteur:
        """Pose UNE question au moteur par son API officielle, recherche web activée, et rend la réponse."""


class PortMoteurNonBranche:
    """Le port par défaut : il n'y en a pas. Aucune question n'est posée à aucun moteur."""

    def interroger(self, prompt: str, moteur: str, jeton: str) -> ReponseMoteur:
        raise ErreurGeo("REJ-GEO-PORT-NON-BRANCHE", "aucun fournisseur d'API de moteur n'est branché : le panel n'a "
                        "jamais été exécuté contre un vrai service")


def valider_moteur(moteur: Any) -> str:
    if moteur not in MOTEURS:
        raise ErreurGeo("REJ-GEO-MOTEUR-INTERFACE", f"moteur {moteur!r} hors de la liste fermée des API officielles "
                        f"{sorted(MOTEURS)} : aucune interface grand public n'est interrogée, jamais")
    return moteur


def valider_domaine(domaine: Any) -> str:
    if not isinstance(domaine, str) or not _DOMAINE.fullmatch(domaine.strip().lower()):
        raise ErreurGeo("REJ-GEO-DOMAINE-INVALIDE", "nom de domaine public attendu (sans schéma ni chemin)")
    return domaine.strip().lower()


def _plier(texte: str) -> str:
    sans_accents = "".join(c for c in unicodedata.normalize("NFKD", texte) if not unicodedata.combining(c))
    return sans_accents.casefold()


def valider_alias(alias: Any) -> tuple[str, ...]:
    if (not isinstance(alias, Sequence) or isinstance(alias, str) or not 1 <= len(alias) <= ALIAS_MAX
            or any(not isinstance(a, str) or len(_plier(a).strip()) < 3 or len(a) > 80 for a in alias)):
        raise ErreurGeo("REJ-GEO-ALIAS-INVALIDES", f"1 à {ALIAS_MAX} alias de marque de 3 caractères ou plus")
    return tuple(dict.fromkeys(_plier(a).strip() for a in alias))


def mentionne(texte: str, alias: Sequence[str]) -> bool:
    """Vrai si un alias (déjà plié) paraît dans le texte comme MOT entier, sans accent ni casse. Linéaire par alias."""
    plie = _plier(texte[:TEXTE_REPONSE_MAX])
    return any(re.search(rf"(?<![0-9a-z]){re.escape(a)}(?![0-9a-z])", plie) is not None for a in alias)


def domaines_cites(citations: Sequence[str]) -> tuple[str, ...]:
    """Les noms d'hôte des URL citées (identifiants, ports et chemins ignorés), sans doublon, au plus 20."""
    hotes = []
    for url in citations[:CITATIONS_MAX]:
        try:
            hote = urllib.parse.urlsplit(url if "//" in url else f"//{url}").hostname
        except ValueError:
            continue
        if hote and hote.rstrip(".") not in hotes:
            hotes.append(hote.rstrip(".").lower())
    return tuple(hotes[:20])


def cite(hotes: Sequence[str], domaine: str) -> bool:
    """Le domaine est cité s'il est EXACTEMENT un hôte cité ou son parent : `blog.exemple.com` cite `exemple.com`, mais
    `exemple.com.evil.test` et `monexemple.com` ne le citent pas."""
    return any(h == domaine or h.endswith("." + domaine) for h in hotes)


def valider_prompts(prompts: Any) -> list[dict[str, str]]:
    if not isinstance(prompts, Sequence) or isinstance(prompts, str) or not PROMPTS_MIN <= len(prompts) <= PROMPTS_MAX:
        raise ErreurGeo("REJ-GEO-PANEL-PROMPTS", f"{PROMPTS_MIN} à {PROMPTS_MAX} questions attendues (R4 §4.4)")
    propres, ids, textes = [], set(), set()
    for p in prompts:
        if (not isinstance(p, Mapping) or set(p) != {"id", "texte", "langue"} or not isinstance(p["id"], str)
                or not _ID_PROMPT.fullmatch(p["id"]) or not isinstance(p["texte"], str)
                or not 5 <= len(p["texte"].strip()) <= TEXTE_PROMPT_MAX or p["langue"] not in ("fr", "en")):
            raise ErreurGeo("REJ-GEO-PANEL-PROMPTS", "chaque question : {id, texte (5 à 300 caractères), langue fr|en}")
        texte = p["texte"].strip()
        if p["id"] in ids or _plier(texte) in textes:
            raise ErreurGeo("REJ-GEO-PANEL-PROMPTS", "identifiant ou texte de question en double")
        ids.add(p["id"])
        textes.add(_plier(texte))
        propres.append({"id": p["id"], "texte": texte, "langue": p["langue"]})
    return propres


def planifier_panel(prompts: Any, moteurs: Any, repetitions: Any, cout_par_appel_cents_par_moteur: Any,
                    plafond_mensuel_cents: Any) -> dict[str, Any]:
    """Le plan d'un passage mensuel du panel et son coût d'avance. `cout_par_appel_cents_par_moteur` : {moteur:
    entier de
    cents | None} déclaré par le client (None : tarif inconnu). `plafond_mensuel_cents` : entier de cents ou None (aucun
    plafond déclaré)."""
    questions = valider_prompts(prompts)
    if not isinstance(moteurs, Sequence) or isinstance(moteurs, str) or not 1 <= len(moteurs) <= len(MOTEURS):
        raise ErreurGeo("REJ-GEO-PANEL-MOTEURS", "1 à 4 moteurs attendus")
    liste = [valider_moteur(m) for m in moteurs]
    if len(set(liste)) != len(liste):
        raise ErreurGeo("REJ-GEO-PANEL-MOTEURS", "moteur en double")
    if type(repetitions) is not int or not REPETITIONS_MIN <= repetitions <= REPETITIONS_MAX:
        raise ErreurGeo("REJ-GEO-PANEL-REPETITIONS", f"répétitions : entier de {REPETITIONS_MIN} à {REPETITIONS_MAX}")
    if not isinstance(cout_par_appel_cents_par_moteur, Mapping) or set(cout_par_appel_cents_par_moteur) - set(MOTEURS):
        raise ErreurGeo("REJ-GEO-PANEL-COUT", "tarifs déclarés par moteur attendus ({moteur: cents | null})")
    if plafond_mensuel_cents is not None and (type(plafond_mensuel_cents) is not int or plafond_mensuel_cents < 0):
        raise ErreurGeo("REJ-GEO-PANEL-PLAFOND", "plafond mensuel : entier de cents >= 0 ou null")
    par_moteur, total, inconnu = [], 0, False
    for m in liste:
        tarif = cout_par_appel_cents_par_moteur.get(m)
        if tarif is not None and (type(tarif) is not int or tarif < 0):
            raise ErreurGeo("REJ-GEO-PANEL-COUT", f"tarif de {m} : entier de cents >= 0 ou null (inconnu)")
        appels = len(questions) * repetitions
        cout = None if tarif is None else tarif * appels
        inconnu = inconnu or cout is None
        total += cout or 0
        par_moteur.append({"moteur": m, "appels": appels, "cout_par_appel_cents": tarif, "cout_cents": cout})
    cout_total = None if inconnu else total
    if plafond_mensuel_cents is not None:
        if cout_total is None:
            raise ErreurGeo("REJ-GEO-PANEL-COUT-INCONNU", "un plafond est déclaré mais le coût d'un moteur est "
                                                          "inconnu : "
                            "déclarer son tarif avant de lancer (un coût inconnu n'est pas un coût nul)")
        if cout_total > plafond_mensuel_cents:
            raise ErreurGeo("REJ-GEO-PANEL-PLAFOND", f"coût mensuel {cout_total} cents au-dessus du plafond "
                            f"{plafond_mensuel_cents} cents")
    plan = {
        "type": "PLAN_PANEL_IA", "prompts": questions, "moteurs": liste, "repetitions": repetitions,
        "appels_total": len(questions) * repetitions * len(liste), "par_moteur": par_moteur,
        "cout_mensuel_cents": cout_total, "cout": "connu" if cout_total is not None else "inconnu",
        "plafond_mensuel_cents": plafond_mensuel_cents, "source_moteurs": SOURCE_MOTEURS,
        "avertissements": ["Réponse d'API ≠ interface grand public (personnalisation, modèles différents).",
                           "Les tarifs viennent de la déclaration du client : aucun tarif n'est inventé ici.",
                           "Conditions d'utilisation de chaque éditeur pour un panel de visibilité : à lire (R4 "
                           "§10 n°11)."],
    }
    plan["empreinte"] = hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                                       .encode("utf-8")).hexdigest()
    return plan


def executer_panel(plan: Mapping[str, Any], port: PortMoteurIA, fournisseurs: Mapping[str, FournisseurSecret], *,
                   alias_marque: Any, domaine_client: Any, concurrents: Mapping[str, Mapping[str, Any]] | None = None
                   ) -> dict[str, Any]:
    """Pose le panel. `fournisseurs` : {moteur: fournisseur de secret}. `concurrents` : {nom: {alias, domaine}}. Une
    panne
    d'un appel est consignée (`erreur`) et ne compte pas dans l'effectif ; une panne d'authentification arrête ce
    moteur."""
    if plan.get("type") != "PLAN_PANEL_IA":
        raise ErreurGeo("REJ-GEO-PANEL-PLAN", "plan de panel attendu (planifier_panel)")
    alias, domaine = valider_alias(alias_marque), valider_domaine(domaine_client)
    suivis = {}
    for nom, cfg in (concurrents or {}).items():
        if not isinstance(nom, str) or not _NOM.fullmatch(nom) or not isinstance(cfg, Mapping):
            raise ErreurGeo("REJ-GEO-CONCURRENT-INVALIDE", "concurrent : {nom en snake_case: {alias, domaine}}")
        suivis[nom] = (valider_alias(cfg.get("alias")), valider_domaine(cfg.get("domaine")))
    resultats: list[dict[str, Any]] = []
    for moteur in plan["moteurs"]:
        valider_moteur(moteur)
        fournisseur = fournisseurs.get(moteur)
        if fournisseur is None:
            raise ErreurGeo("REJ-GEO-PANEL-SECRET", f"fournisseur de secret manquant pour {moteur}")
        arret: str | None = None
        for prompt in plan["prompts"]:
            for rep in range(1, plan["repetitions"] + 1):
                ligne: dict[str, Any] = {"prompt_id": prompt["id"], "moteur": moteur, "repetition": rep}
                if arret is not None:
                    resultats.append({**ligne, "erreur": arret})
                    continue
                try:
                    with fournisseur() as jeton:
                        reponse = port.interroger(prompt["texte"], moteur, jeton)
                except ErreurMoteur as exc:
                    arret = exc.code if exc.code == "REJ-GEO-MOTEUR-AUTH" else None
                    resultats.append({**ligne, "erreur": exc.code})
                    continue
                except ErreurGeo as exc:
                    resultats.append({**ligne, "erreur": exc.code})
                    arret = exc.code
                    continue
                except Exception:  # noqa: BLE001 — le message d'un transport peut contenir le jeton
                    resultats.append({**ligne, "erreur": "REJ-GEO-MOTEUR-INDISPONIBLE"})
                    continue
                hotes = domaines_cites(reponse.citations)
                texte = reponse.texte if isinstance(reponse.texte, str) else ""
                resultats.append({
                    **ligne, "mentionne": mentionne(texte, alias), "cite": cite(hotes, domaine),
                    "domaines_cites": list(hotes),
                    "empreinte_reponse": hashlib.sha256(texte.encode("utf-8")).hexdigest(),
                    "version_modele": str(reponse.version_modele)[:60], "tokens": int(reponse.tokens),
                    "concurrents": {n: {"mentionne": mentionne(texte, a), "cite": cite(hotes, d)}
                                    for n, (a, d) in suivis.items()},
                })
    return {"type": "RESULTATS_PANEL_IA", "plan_empreinte": plan["empreinte"], "resultats": resultats,
            "texte_des_reponses": "NON CONSERVÉ (donnée non fiable d'un tiers)"}


__all__ = ["ErreurMoteur", "MOTEURS", "PortMoteurIA", "PortMoteurNonBranche", "ReponseMoteur", "cite",
           "domaines_cites", "executer_panel", "mentionne", "planifier_panel", "valider_alias", "valider_domaine",
           "valider_moteur", "valider_prompts"]
