"""Comparaison DÉTERMINISTE entre le site du client et les observations de ses concurrents déclarés.

Pour chaque critère mesurable, un tableau : la valeur du client, puis une ligne par page observée d'un concurrent avec
SA valeur,
l'écart exact (concurrent moins client, en entier), la date de l'observation et sa péremption. Quand une donnée
manque, la
valeur est `"inconnu"` et l'écart `null` : jamais un zéro. Une observation dont l'accès a été refusé ou dont la page
est absente
n'a aucune valeur.

Ce que ce module ne fait PAS, volontairement : aucun score global, aucun classement, aucune affirmation causale (« ils
sont
mieux classés parce que… »). Ce sont des observations de sources publiques, non fiables, prises à une date donnée.

Les « faits du client » sont fournis par l'appelant avec les mêmes champs que l'observation (titre, méta-description,
h1, mots,
types de schéma, URL du plan de site, robots d'IA) : le module ne lit aucun site.

Module pur : l'horloge est un argument.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from . import observations
from .registre import ErreurVeille

INCONNU = "inconnu"
MENTION = ("Observations de sources publiques, non fiables, à une date donnée ; ne prouve rien sur les causes. Aucun "
           "score, aucun classement.")
CHAMPS_CLIENT = ("titre", "description_meta", "h1", "nb_mots", "types_schema", "nb_urls_plan_de_site", "robots_ia")


def valider_faits_client(faits: Any) -> dict[str, Any]:
    if not isinstance(faits, Mapping) or set(faits) - set(CHAMPS_CLIENT):
        raise ErreurVeille("REJ-VEILLE-ARGUMENT-INVALIDE", f"faits du client : champs permis {list(CHAMPS_CLIENT)}")
    sortie = dict(faits)
    for champ in ("titre", "description_meta"):
        if sortie.get(champ) is not None and not isinstance(sortie[champ], str):
            raise ErreurVeille("REJ-VEILLE-ARGUMENT-INVALIDE", f"{champ} : texte attendu")
    if sortie.get("h1") is not None and not (isinstance(sortie["h1"], list) and all(isinstance(t,
        str) for t in sortie["h1"])):
        raise ErreurVeille("REJ-VEILLE-ARGUMENT-INVALIDE", "h1 : liste de textes attendue")
    for champ in ("nb_mots", "nb_urls_plan_de_site"):
        v = sortie.get(champ)
        if v is not None and (type(v) is not int or v < 0):
            raise ErreurVeille("REJ-VEILLE-ARGUMENT-INVALIDE", f"{champ} : entier >= 0 attendu")
    if sortie.get("types_schema") is not None and not (
            isinstance(sortie["types_schema"], list) and all(isinstance(t, str) for t in sortie["types_schema"])):
        raise ErreurVeille("REJ-VEILLE-ARGUMENT-INVALIDE", "types_schema : liste de noms attendue")
    robots = sortie.get("robots_ia")
    if robots is not None and (not isinstance(robots, Mapping) or set(robots) - set(observations.BOTS_IA)
                               or not all(type(v) is bool for v in robots.values())):
        raise ErreurVeille("REJ-VEILLE-ARGUMENT-INVALIDE", "robots_ia : {robot connu: booléen}")
    return sortie


def _mesures_client(faits: Mapping[str, Any]) -> dict[str, Any]:
    """Valeurs du site du client : connu seulement si l'appelant a fourni le champ."""
    robots = faits.get("robots_ia")
    return {
        "longueur_titre": len(faits["titre"]) if faits.get("titre") is not None else None,
        "longueur_description": len(faits["description_meta"]) if faits.get("description_meta") is not None else None,
        "nombre_h1": len(faits["h1"]) if faits.get("h1") is not None else None,
        "nombre_types_schema": len(faits["types_schema"]) if faits.get("types_schema") is not None else None,
        "nb_mots": faits.get("nb_mots"),
        "nb_urls_plan_de_site": faits.get("nb_urls_plan_de_site"),
        "robots_ia_autorises": sum(1 for v in robots.values() if v) if isinstance(robots, Mapping) and robots else None,
    }


def _mesures_observation(obs: Mapping[str, Any]) -> dict[str, Any]:
    """Valeurs d'une page observée. Une page HTML LUE sans titre vaut un titre de longueur 0 (c'est un fait) ; un texte
    écarté pour injection, un accès refusé ou une saisie sans le champ restent INCONNUS."""
    inconnues = {c: None for c in CRITERES}
    if obs["acces"] != "ok":
        return inconnues
    robots = obs.get("robots_ia")
    mesures = dict(inconnues)
    mesures["nb_urls_plan_de_site"] = obs["nb_urls_plan_de_site"]
    mesures["robots_ia_autorises"] = sum(1 for v in robots.values() if v) if isinstance(robots, Mapping) and robots \
        else None
    page_lue = obs["mode"] == "collecte_publique" and obs["nb_mots"] is not None and not obs["injection_detectee"]
    if page_lue:
        mesures.update({
            "longueur_titre": len(obs["titre"] or ""), "longueur_description": len(obs["description_meta"] or ""),
            "nombre_h1": len(obs["h1"]), "nombre_types_schema": len(obs["types_schema"]), "nb_mots": obs["nb_mots"]})
    elif obs["mode"] == "saisie_humaine":
        mesures.update({
            "longueur_titre": len(obs["titre"]) if obs["titre"] is not None else None,
            "longueur_description": len(obs["description_meta"]) if obs["description_meta"] is not None else None,
            "nombre_h1": len(obs["h1"]) if obs["h1"] else None,
            "nombre_types_schema": len(obs["types_schema"]) if obs["types_schema"] else None,
            "nb_mots": obs["nb_mots"]})
    return mesures


CRITERES = ("longueur_titre", "longueur_description", "nombre_h1", "nombre_types_schema", "nb_mots",
            "nb_urls_plan_de_site", "robots_ia_autorises")


def comparer(faits_client: Mapping[str, Any] | None, observations_par_url: Iterable[Mapping[str, Any]],
             maintenant: datetime) -> dict[str, Any]:
    """Le tableau comparatif. `observations_par_url` : la dernière observation de chaque (concurrent, URL)."""
    client = valider_faits_client(faits_client) if faits_client is not None else {}
    valeurs_client = _mesures_client(client)
    lignes = sorted(observations_par_url, key=lambda o: (o["concurrent_id"], o["url"]))
    mesures_par_obs = {(o['concurrent_id'], o['url']): _mesures_observation(o) for o in lignes}
    tableau = []
    for critere in CRITERES:
        v_client = valeurs_client[critere]
        rangees = []
        for obs in lignes:
            valeur = mesures_par_obs[(obs['concurrent_id'], obs['url'])][critere]
            rangees.append({
                "concurrent_id": obs["concurrent_id"], "url": obs["url"],
                "valeur": INCONNU if valeur is None else valeur,
                "ecart_vs_client": None if valeur is None or v_client is None else valeur - v_client,
                "observe_le": obs["collecte_le"], "perimee": observations.est_perimee(obs, maintenant),
                "acces": obs["acces"], "mode": obs["mode"],
            })
        tableau.append({"critere": critere, "client": INCONNU if v_client is None else v_client,
            "concurrents": rangees})
    types_client = set(client.get("types_schema") or [])

    def types_comparables(o: Mapping[str, Any]) -> bool:
        return (faits_client is not None and client.get("types_schema") is not None
                and mesures_par_obs[(o["concurrent_id"], o["url"])]["nombre_types_schema"] is not None)

    schema = [{
        "concurrent_id": o["concurrent_id"], "url": o["url"],
        "types_absents_chez_le_client": sorted(set(o["types_schema"]) - types_client)
        if types_comparables(o) else INCONNU,
        "types_absents_chez_le_concurrent": sorted(types_client - set(o["types_schema"]))
        if types_comparables(o) else INCONNU,
    } for o in lignes]
    bots = {}
    for obs in lignes:
        robots = obs.get("robots_ia")
        bots[f"{obs['concurrent_id']}|{obs['url']}"] = (
            INCONNU if not isinstance(robots, Mapping) else sorted(b for b, ok in robots.items() if not ok))
    return {"type": "COMPARAISON_CONCURRENTIELLE", "criteres": tableau, "schema": schema,
            "robots_ia_bloques_par_page": bots, "observations": len(lignes),
            "client_fourni": faits_client is not None, "mention": MENTION, "fiabilite_sources": "non_fiable"}


__all__ = ["CHAMPS_CLIENT", "CRITERES", "INCONNU", "MENTION", "comparer", "valider_faits_client"]
