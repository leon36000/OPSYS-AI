"""Changements de site PROPOSÉS : des brouillons de schéma `opsys.site/v1`, jamais une publication.

Une recommandation (`recommandations.py`) débouche, quand elle touche le texte du site, sur une PROPOSITION : une liste
d'opérations (20 au plus) appliquée à une COPIE du schéma de site fourni. Les opérations sont limitées à une liste
blanche : - `remplacer_texte` sur `page.titre`, `page.description`, `service.resume`, `service.description` (une
page ou un service
  existant, une valeur par langue du site, toutes les langues à la fois) ;
- `ajouter_faq` : une nouvelle entrée de FAQ (identifiant neuf, question et réponse dans chaque langue).
Tout autre chemin est refusé (`REJ-GEO-PROPOSITION-OPERATION`) : coordonnées, charte, témoignages, mentions légales,
sources, images et zones ne se modifient pas par ce moyen.

La proposition passe ensuite, SANS RIEN ÉCRIRE, par les contrôles existants du site : le validateur de structure
(`schema_site.valider_schema`), la garde de contenu (`garde_contenu` : promesses chiffrées, prix, exagération, données
personnelles, copie d'un concurrent…) et le contrôle qualité du rendu (`site.service.construire_site`). Un refus de
l'un d'eux est repris avec SON code. Les textes proposés passent aussi par le contrôle de marques de la veille
(`controle_marques`, injecté : noms de concurrents, recopie) ; sans lui, l'avertissement
`controle_marques_non_applique` est rendu, jamais un silence.

Le schéma d'origine n'est JAMAIS modifié. La proposition est consignée (registre append-only à chaîne de hachage
`propositions_site`, état BROUILLON ou RETIREE). La suite est humaine : préparer le paquet
(`m7_preparer_paquet_site`), puis demander la publication (`m7_demander_publication_site`, N3, décision de la
direction).
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from typing import Any

from .. import journal_chaine
from ..site import garde_contenu, schema_site
from ..site import service as site_service
from .robots_ia import ErreurGeo

REGISTRE = ("m07-marketing", "propositions_site")
M_CREEE = "proposition_creee"
M_RETIREE = "proposition_retiree"
OPERATIONS_MAX = 20
OCTETS_OPS_MAX = 60_000
TEXTE_MAX = 2000
CHAMPS_REMPLACABLES = ("page.titre", "page.description", "service.resume", "service.description")
SUITE = ("Brouillon : rien n'est publié. Suite humaine : m7_preparer_paquet_site avec le schéma proposé, puis "
         "m7_demander_publication_site (N3, décision de la direction).")


def _refus(code: str, chemin: str, detail: str) -> dict[str, Any]:
    return {"accepte": False, "refus": [{"code": code, "chemin": chemin, "detail": detail}]}


def empreinte_schema(schema: Mapping[str, Any]) -> str:
    return hashlib.sha256(json.dumps(schema, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
                          .encode("utf-8")).hexdigest()


def _textes(valeur: Any) -> list[str]:
    if isinstance(valeur, str):
        return [valeur]
    if isinstance(valeur, Mapping):
        return [t for v in valeur.values() for t in _textes(v)]
    if isinstance(valeur, Sequence):
        return [t for v in valeur for t in _textes(v)]
    return []


def _valeur_localisee(valeur: Any, langues: Sequence[str], chemin: str, *, liste: bool) -> dict[str, Any] | None:
    """La valeur dans CHAQUE langue du site (ni plus, ni moins) ; None si elle n'est pas conforme."""
    if not isinstance(valeur, Mapping) or set(valeur) != set(langues):
        return None
    sortie: dict[str, Any] = {}
    for lg, v in valeur.items():
        if liste:
            if (not isinstance(v, list) or not 1 <= len(v) <= 6
                    or any(not isinstance(p, str) or not 1 <= len(p.strip()) <= TEXTE_MAX for p in v)):
                return None
            sortie[lg] = [p.strip() for p in v]
        else:
            if not isinstance(v, str) or not 1 <= len(v.strip()) <= TEXTE_MAX:
                return None
            sortie[lg] = v.strip()
    return sortie


def appliquer(schema: Mapping[str, Any], ops: Any, date_revision: Any) -> tuple[dict[str, Any] | None, list[dict[str,
    Any]],
                                                                               dict[str, Any] | None]:
    """(copie modifiée, diff, refus). L'original n'est jamais muté. Aucun contrôle de contenu ici : voir `proposer`."""
    if (not isinstance(ops, Sequence) or isinstance(ops, str) or not 1 <= len(ops) <= OPERATIONS_MAX):
        return None, [], _refus("REJ-GEO-PROPOSITION-OPERATION", "$.operations", f"1 à {OPERATIONS_MAX} opérations")
    try:
        if len(json.dumps(ops, ensure_ascii=False).encode("utf-8")) > OCTETS_OPS_MAX:
            return None, [], _refus("REJ-GEO-PROPOSITION-OPERATION", "$.operations", f"plus de {OCTETS_OPS_MAX} octets")
    except (TypeError, ValueError):
        return None, [], _refus("REJ-GEO-PROPOSITION-OPERATION", "$.operations", "opérations non sérialisables")
    langues = schema.get("langues") or []
    try:
        revision_base = date.fromisoformat(schema["revision"]["date"])
        revision = date.fromisoformat(date_revision) if isinstance(date_revision, str) else None
    except (KeyError, TypeError, ValueError):
        return None, [], _refus("REJ-GEO-PROPOSITION-REVISION", "$.date_revision", "date de révision du schéma "
                                                                                   "illisible")
    if revision is None or revision < revision_base:
        return None, [], _refus("REJ-GEO-PROPOSITION-REVISION", "$.date_revision",
                                "date AAAA-MM-JJ attendue, pas antérieure à la révision du schéma de base")
    nouveau = copy.deepcopy(dict(schema))
    nouveau["revision"] = {**nouveau["revision"], "date": revision.isoformat()}
    diff: list[dict[str, Any]] = []
    for i, op in enumerate(ops):
        chemin_op = f"$.operations[{i}]"
        if not isinstance(op, Mapping) or op.get("op") not in ("remplacer_texte", "ajouter_faq"):
            return None, [], _refus("REJ-GEO-PROPOSITION-OPERATION", chemin_op, "op : remplacer_texte | ajouter_faq")
        if op["op"] == "ajouter_faq":
            if set(op) != {"op", "id", "valeur"} or not isinstance(op["valeur"], Mapping) or \
                    set(op["valeur"]) != {"question", "reponse"}:
                return None, [], _refus("REJ-GEO-PROPOSITION-OPERATION", chemin_op, "ajouter_faq : {op, id, valeur: "
                                        "{question, reponse}}")
            q = _valeur_localisee(op["valeur"]["question"], langues, chemin_op, liste=False)
            r = _valeur_localisee(op["valeur"]["reponse"], langues, chemin_op, liste=False)
            if q is None or r is None or not isinstance(op["id"], str):
                return None, [], _refus("REJ-GEO-PROPOSITION-OPERATION", chemin_op,
                                        f"question et réponse dans chaque langue du site {list(langues)}")
            if any(e.get("id") == op["id"] for e in nouveau.get("faq", [])):
                return None, [], _refus("REJ-GEO-PROPOSITION-CIBLE", chemin_op,
                    f"entrée de FAQ {op['id']!r} existe déjà")
            nouveau.setdefault("faq", []).append({"id": op["id"], "question": q, "reponse": r})
            diff.append({"chemin": f"$.faq[{len(nouveau['faq']) - 1}]", "avant": None,
                         "apres": {"id": op["id"], "question": q, "reponse": r}})
            continue
        if set(op) != {"op", "cible", "id", "valeur"} or op["cible"] not in CHAMPS_REMPLACABLES:
            return None, [], _refus("REJ-GEO-PROPOSITION-OPERATION", chemin_op,
                                    f"remplacer_texte : cible parmi {list(CHAMPS_REMPLACABLES)}, id, valeur")
        genre, champ = op["cible"].split(".")
        collection = "pages" if genre == "page" else "services"
        indice = next((k for k, e in enumerate(nouveau.get(collection, [])) if e.get("id") == op["id"]), None)
        if indice is None:
            return None, [], _refus("REJ-GEO-PROPOSITION-CIBLE", chemin_op, f"{genre} {op['id']!r} inconnu du schéma")
        valeur = _valeur_localisee(op["valeur"], langues, chemin_op, liste=op["cible"] == "service.description")
        if valeur is None:
            return None, [], _refus("REJ-GEO-PROPOSITION-OPERATION", chemin_op,
                                    f"valeur dans chaque langue du site {list(langues)} (texte, ou 1 à 6 paragraphes "
                                    "pour service.description)")
        avant = nouveau[collection][indice].get(champ)
        for lg in langues:
            diff.append({"chemin": f"$.{collection}[{indice}].{champ}.{lg}", "avant": (avant or {}).get(lg),
                         "apres": valeur[lg]})
        nouveau[collection][indice][champ] = valeur
    return nouveau, diff, None


def proposer(schema: Mapping[str, Any], actifs: Mapping[str, bytes], ops: Any, date_revision: Any, journal: Any, *,
             par: str, horodatage: str, recommandation_id: str | None = None,
             controle_marques: Callable[[str], Mapping[str, Any]] | None = None) -> dict[str, Any]:
    """Crée (ou retrouve) la proposition. Rien n'est écrit ailleurs qu'au registre `propositions_site`."""
    if recommandation_id is not None and (not isinstance(recommandation_id,
        str) or not 1 <= len(recommandation_id) <= 80):
        return _refus("REJ-GEO-PROPOSITION-OPERATION", "$.recommandation_id", "identifiant de recommandation de 1 à 80")
    problemes = journal_chaine.verifier(journal)
    if problemes:
        return _refus("REJ-GEO-PROPOSITION-JOURNAL", "$", "; ".join(problemes[:3]))
    refus_base = schema_site.valider_schema(schema)
    if refus_base:
        return {"accepte": False, "refus": refus_base}
    nouveau, diff, refus = appliquer(schema, ops, date_revision)
    if refus is not None:
        return refus
    assert nouveau is not None
    refus_structure = schema_site.valider_schema(nouveau)
    if refus_structure:
        return {"accepte": False, "refus": refus_structure}
    refus_contenu = garde_contenu.controler_contenu(nouveau)
    if refus_contenu:
        return {"accepte": False, "refus": refus_contenu}
    avertissements: list[str] = []
    if controle_marques is None:
        avertissements.append("controle_marques_non_applique")
    else:
        textes = sorted({t for d in diff for t in _textes(d["apres"])})
        refus_marques = []
        mentions: list[str] = []
        for texte in textes:
            verdict = controle_marques(texte)
            refus_marques += list(verdict.get("refus", []))
            mentions += list(verdict.get("mentions", []))
        if refus_marques:
            return {"accepte": False, "refus": refus_marques}
        avertissements += sorted(set(mentions))
    construit = site_service.construire_site(nouveau, actifs)
    if not construit["accepte"]:
        return {"accepte": False, "refus": construit["refus"]}
    qa = construit["qa"]
    if not qa["conforme"]:
        echecs = [c["code"] for c in qa["controles"] if not c["ok"]]
        return _refus("REJ-GEO-PROPOSITION-QA", "$", f"contrôle qualité du rendu non conforme : {echecs}")
    ops_canon = json.loads(json.dumps(ops, ensure_ascii=False))
    empreinte_base, empreinte_resultat = empreinte_schema(schema), empreinte_schema(nouveau)
    identifiant = "prop-" + hashlib.sha256(json.dumps([schema["site_id"], empreinte_base, date_revision, ops_canon],
                                                      sort_keys=True,
                                                          ensure_ascii=False).encode("utf-8")).hexdigest()[:16]
    existantes = etats(journal)
    deja = identifiant in existantes
    if deja and existantes[identifiant]["etat"] == "RETIREE":
        return _refus("REJ-GEO-PROPOSITION-ETAT", "$", "cette proposition a été retirée : en faire une autre")
    if not deja:
        journal_chaine.ajouter(journal, M_CREEE, {
            "proposition_id": identifiant, "site_id": schema["site_id"], "recommandation_id": recommandation_id,
            "empreinte_base": empreinte_base, "empreinte_resultat": empreinte_resultat, "date_revision": date_revision,
            "operations": ops_canon, "par": par}, horodatage)
    return {"accepte": True, "proposition_id": identifiant, "etat": "BROUILLON", "deja_propose": deja,
            "site_id": schema["site_id"], "recommandation_id": recommandation_id, "empreinte_base": empreinte_base,
            "empreinte_resultat": empreinte_resultat, "diff": diff, "schema_propose": nouveau, "qa_conforme": True,
            "avertissements": avertissements, "suite": SUITE}


def etats(journal: Any) -> dict[str, dict[str, Any]]:
    resultat: dict[str, dict[str, Any]] = {}
    for m in journal:
        if m["type"] == M_CREEE:
            resultat[m["proposition_id"]] = {
                "proposition_id": m["proposition_id"], "etat": "BROUILLON", "site_id": m["site_id"],
                "recommandation_id": m["recommandation_id"], "empreinte_base": m["empreinte_base"],
                "empreinte_resultat": m["empreinte_resultat"], "date_revision": m["date_revision"],
                "operations": m["operations"], "par": m["par"], "cree_le": m["horodatage"]}
        elif m["type"] == M_RETIREE:
            resultat[m["proposition_id"]]["etat"] = "RETIREE"
            resultat[m["proposition_id"]]["retiree_pour"] = m["motif"]
    return resultat


def retirer(journal: Any, proposition_id: str, par: str, motif: str, horodatage: str) -> dict[str, Any]:
    courant = etats(journal).get(proposition_id)
    if courant is None:
        return _refus("REJ-GEO-PROPOSITION-INCONNUE", "$.proposition_id", "proposition inconnue")
    if courant["etat"] == "RETIREE":
        return {"accepte": True, "proposition_id": proposition_id, "deja_retiree": True}
    journal_chaine.ajouter(journal, M_RETIREE, {"proposition_id": proposition_id, "par": par, "motif": motif[:300]},
                           horodatage)
    return {"accepte": True, "proposition_id": proposition_id, "deja_retiree": False}


def lire(journal: Any, proposition_id: str | None = None, etat: str | None = None, limite: int = 20) -> dict[str, Any]:
    problemes = journal_chaine.verifier(journal)
    if problemes:
        return _refus("REJ-GEO-PROPOSITION-JOURNAL", "$", "; ".join(problemes[:3]))
    if type(limite) is not int or not 1 <= limite <= 50:
        raise ErreurGeo("REJ-GEO-ARGUMENT", "limite : entier de 1 à 50")
    tous = etats(journal)
    if proposition_id is not None:
        if proposition_id not in tous:
            return _refus("REJ-GEO-PROPOSITION-INCONNUE", "$.proposition_id", "proposition inconnue")
        return {"accepte": True, "proposition": tous[proposition_id]}
    choisies = [p for p in tous.values() if etat is None or p["etat"] == etat]
    return {"accepte": True, "total": len(choisies),
            "propositions": [{k: p[k] for k in ("proposition_id", "etat", "site_id", "recommandation_id",
                                                "empreinte_resultat", "cree_le")} for p in choisies[-limite:]],
            "integrite": {"journal_intact": True}}


__all__ = ["CHAMPS_REMPLACABLES", "OPERATIONS_MAX", "REGISTRE", "SUITE", "appliquer", "empreinte_schema", "etats",
    "lire",
           "proposer", "retirer"]
