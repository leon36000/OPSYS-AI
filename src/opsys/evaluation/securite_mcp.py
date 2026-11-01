"""Corpus TRANSVERSE de sécurité MCP : la dérive d'outil et la Rule of Two doivent être refusées, avec le bon code.

Le gabarit par département (`corpus.py`, `executeur.py`) mesure ce qu'un RÉPONDANT fait. Ce corpus-ci mesure ce que la
GARDE du serveur MCP fait, indépendamment de tout modèle : on prend les outils réels (421 de départements + contexte +
runtime), on en altère un (description, schéma, niveau, nom) ou on déclare une exposition à du contenu non fiable, et
on exige le refus attendu (`REJ-MCP-…`) ou, pour un cas témoin, l'autorisation. Comme le reste du gabarit, tout est
déterministe, sans réseau, sans modèle-juge.

Il vit dans un fichier à part (`corpus_transverse/securite-mcp.v1.yaml`) : les corpus des dix départements et leur
empreinte ne sont pas touchés. Format fermé (`opsys.evaluation.securite-mcp/v1`) : champ inconnu, code hors catalogue ou
cas en double = `REJ-EVAL-CORPUS-…`.

La preuve que le corpus mord : `garde_complaisante()` (registre scellé sur les outils DÉJÀ altérés, Rule of Two coupée)
doit échouer sur tous les cas bloquants.
"""

from __future__ import annotations

import copy
import dataclasses
import datetime as dt
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

from ..registre_mcp import registre as reg
from ..registre_mcp import rule_of_two
from ..registre_mcp.garde import REGISTRE_LIVRE, GardeMCP
from ..registre_mcp.registre import DefinitionOutil, RefusMCP
from .corpus import RefusEvaluation, empreinte

SCHEMA_CORPUS_MCP = "opsys.evaluation.securite-mcp/v1"
FICHIER_CORPUS_MCP = Path(__file__).with_name("corpus_transverse") / "securite-mcp.v1.yaml"
MUTATIONS = ("aucune", "description_ajout", "description_homoglyphe", "description_invisible", "schema_propriete",
             "schema_requis_retire", "schema_ouvert", "niveau", "renommer")
GRAVITES = ("bloquante", "majeure", "mineure")
_CHAMPS_CORPUS = {"schema", "version", "fictif", "description", "cas"}
_CHAMPS_CAS = {"id", "gravite", "poids", "source", "outil", "mutation", "valeur", "expositions", "approbation",
               "table_alteree", "attendu"}
_CHAMPS_ATTENDU = {"decision", "code"}
_CHAMPS_APPROBATION = {"niveau", "humain"}
_CHAMPS_TABLE = {"surface", "ajouter"}
_HOMOGLYPHE = {"a": "а", "e": "е", "o": "о", "p": "р", "c": "с"}  # cyrillique


def _refus(code: str, chemin: str, detail: str) -> RefusEvaluation:
    return RefusEvaluation(code, detail, chemin)


def valider_corpus_mcp(corpus: Any) -> dict[str, Any]:
    if not isinstance(corpus, Mapping) or set(corpus) - _CHAMPS_CORPUS or {"schema", "version", "fictif",
                                                                           "cas"} - set(corpus):
        raise _refus("REJ-EVAL-CORPUS-FORME", "", "corpus MCP : champs schema, version, fictif, cas (et description)")
    if corpus["schema"] != SCHEMA_CORPUS_MCP:
        raise _refus("REJ-EVAL-CORPUS-FORME", "schema", f"attendu {SCHEMA_CORPUS_MCP!r}")
    if corpus["fictif"] is not True:
        raise _refus("REJ-EVAL-CORPUS-FICTIF", "fictif", "un corpus porte fictif: true")
    ids: set[str] = set()
    for i, cas in enumerate(corpus["cas"]):
        chemin = f"cas[{i}]"
        if not isinstance(cas, Mapping) or set(cas) - _CHAMPS_CAS or {"id", "gravite", "poids", "source", "outil",
                                                                      "attendu"} - set(cas):
            raise _refus("REJ-EVAL-CORPUS-CHAMP-INCONNU", chemin, "champs inconnus ou manquants")
        if cas["id"] in ids:
            raise _refus("REJ-EVAL-CORPUS-DOUBLON", chemin, f"cas en double : {cas['id']}")
        ids.add(cas["id"])
        if cas["gravite"] not in GRAVITES or type(cas["poids"]) is not int or not 1 <= cas["poids"] <= 5:
            raise _refus("REJ-EVAL-CORPUS-FORME", chemin, "gravité ou poids invalide")
        if cas.get("mutation", "aucune") not in MUTATIONS:
            raise _refus("REJ-EVAL-CORPUS-FORME", f"{chemin}.mutation", f"attendu parmi {list(MUTATIONS)}")
        attendu = cas["attendu"]
        if (not isinstance(attendu,
                           Mapping) or set(attendu) - _CHAMPS_ATTENDU or attendu.get("decision") not in ("refuser",
                                                                                                         "autoriser")):
            raise _refus("REJ-EVAL-CORPUS-FORME", f"{chemin}.attendu", "decision: refuser | autoriser (et code)")
        refus_attendu = attendu["decision"] == "refuser"
        if refus_attendu != ("code" in attendu) or ("code" in attendu and attendu["code"] not in reg.CODES_MCP):
            raise _refus("REJ-EVAL-CORPUS-FORME", f"{chemin}.attendu.code",
                         "code REJ-MCP-… requis pour un refus, et lui seul")
        for expo in cas.get("expositions", []):
            if not isinstance(expo, str):
                raise _refus("REJ-EVAL-CORPUS-FORME", f"{chemin}.expositions", "liste de textes attendue")
        if "approbation" in cas and (not isinstance(cas["approbation"],
                                                    Mapping) or set(cas["approbation"]) - _CHAMPS_APPROBATION):
            raise _refus("REJ-EVAL-CORPUS-FORME", f"{chemin}.approbation", "niveau et humain seulement")
        if "table_alteree" in cas and (not isinstance(cas["table_alteree"],
                                                      Mapping) or set(cas["table_alteree"]) - _CHAMPS_TABLE):
            raise _refus("REJ-EVAL-CORPUS-FORME", f"{chemin}.table_alteree", "surface et ajouter seulement")
    return copy.deepcopy(dict(corpus))


def charger_corpus_mcp(chemin: Path = FICHIER_CORPUS_MCP) -> dict[str, Any]:
    try:
        donnees = yaml.safe_load(Path(chemin).read_text(encoding="utf-8"))
    except OSError as exc:
        raise RefusEvaluation("REJ-EVAL-CORPUS-ABSENT", f"fichier illisible : {exc.strerror}", str(chemin)) from exc
    except yaml.YAMLError as exc:
        raise RefusEvaluation("REJ-EVAL-CORPUS-FORME", f"YAML invalide : {exc}", str(chemin)) from exc
    return valider_corpus_mcp(donnees)


def _muter(d: DefinitionOutil, mutation: str, valeur: Any) -> DefinitionOutil:
    schema = copy.deepcopy(dict(d.schema_entree))
    if mutation == "description_ajout":
        return dataclasses.replace(d, description=d.description + str(valeur))
    if mutation == "description_homoglyphe":
        for latin, cyrillique in _HOMOGLYPHE.items():
            if latin in d.description:
                return dataclasses.replace(d, description=d.description.replace(latin, cyrillique, 1))
        raise RefusEvaluation("REJ-EVAL-CORPUS-INCOHERENT", d.nom, "aucune lettre à remplacer par un homoglyphe")
    if mutation == "description_invisible":
        return dataclasses.replace(d, description=d.description[:5] + "​" + d.description[5:])
    if mutation == "schema_propriete":
        schema.setdefault("properties", {})[str(valeur)] = {"type": "string"}
        return dataclasses.replace(d, schema_entree=schema)
    if mutation == "schema_requis_retire":
        schema["required"] = [r for r in schema.get("required", []) if r != valeur]
        return dataclasses.replace(d, schema_entree=schema)
    if mutation == "schema_ouvert":
        schema.pop("additionalProperties", None)
        return dataclasses.replace(d, schema_entree=schema)
    if mutation == "niveau":
        return dataclasses.replace(d, niveau=str(valeur))
    if mutation == "renommer":
        return dataclasses.replace(d, nom=str(valeur))
    return d


@dataclasses.dataclass(frozen=True)
class ResultatCas:
    id: str
    gravite: str
    poids: int
    attendu: str
    obtenu: str
    reussi: bool
    detail: str = ""


def _decision(refus: RefusMCP | None) -> str:
    return "autoriser" if refus is None else refus.code


def evaluer_cas(cas: Mapping[str, Any], definitions: Mapping[str, DefinitionOutil], garde: GardeMCP) -> ResultatCas:
    attendu = cas["attendu"]
    voulu = attendu.get("code", "autoriser")
    d = definitions.get(cas["outil"])
    if d is None:
        raise RefusEvaluation("REJ-EVAL-CORPUS-OUTIL", f"cas[{cas['id']}]",
                              f"outil inconnu du catalogue réel : {cas['outil']}")
    d = _muter(d, cas.get("mutation", "aucune"), cas.get("valeur"))
    original = dict(rule_of_two.SANS_APPROBATION)
    try:
        if "table_alteree" in cas:  # la table est fautive : la règle des trois propriétés doit tenir quand même
            t = cas["table_alteree"]
            rule_of_two.SANS_APPROBATION = {**original, t["surface"]: original[t["surface"]] | frozenset(t["ajouter"])}  # type: ignore[misc]
        try:
            expositions = rule_of_two.parser_expositions(list(cas.get("expositions", [])) or None)
        except RefusMCP as refus:
            obtenu, detail = refus.code, refus.detail
        else:
            a = cas.get("approbation")
            preuve = (rule_of_two.ApprobationPreuve(a["niveau"], "personne-fictive", "demande-fictive",
                                                    a.get("humain", True)) if a else None)
            refus = garde.controler(d, expositions=expositions, approbation=preuve)
            obtenu, detail = _decision(refus), (refus.detail if refus else "")
    finally:
        rule_of_two.SANS_APPROBATION = original  # type: ignore[misc]
    return ResultatCas(cas["id"], cas["gravite"], cas["poids"], voulu, obtenu, obtenu == voulu, detail)


def evaluer(corpus: Mapping[str, Any], definitions: Sequence[DefinitionOutil],
            garde: GardeMCP | None = None) -> dict[str, Any]:
    """Exécute le corpus sur les outils réels. Rapport JSON (score pondéré, échecs nommés, bloquants échoués)."""
    garde = garde or GardeMCP(reg.charger(REGISTRE_LIVRE), surfaces=frozenset({"departement", "contexte", "runtime"}),
                         silencieux=True)
    par_nom = {d.nom: d for d in definitions}
    resultats = [evaluer_cas(cas, par_nom, garde) for cas in corpus["cas"]]
    poids_total = sum(r.poids for r in resultats)
    poids_reussi = sum(r.poids for r in resultats if r.reussi)
    echecs = [r for r in resultats if not r.reussi]
    return {
        "schema": "opsys.evaluation.securite-mcp.rapport/v1", "version_corpus": corpus["version"],
        "empreinte_corpus": empreinte(corpus), "cas": len(resultats), "reussis": len(resultats) - len(echecs),
        "score": float(poids_reussi) / poids_total if poids_total else None,
        "bloquants_echoues": [r.id for r in echecs if r.gravite == "bloquante"],
        "echecs": [dataclasses.asdict(r) for r in echecs],
        "qualifie": not any(r.gravite == "bloquante" for r in echecs) and bool(resultats),
        "garde": {"revision_registre": garde.registre.revision, "rule_of_two": garde.rule_of_two_active},
    }


def garde_complaisante(definitions_alterees: Sequence[DefinitionOutil]) -> GardeMCP:
    """Garde fautive pour prouver que le corpus mord : registre scellé sur les définitions déjà altérées ET Rule of Two
    coupée. Tout cas bloquant doit échouer avec elle."""
    scelle = reg.sceller(definitions_alterees, None, par="doublure-de-test", maintenant=dt.datetime.now(dt.UTC),
                        inspecter=False)
    return GardeMCP(scelle, surfaces=frozenset({"departement", "contexte", "runtime"}), rule_of_two_active=False,
                    silencieux=True)


def rapport_markdown(rapport: Mapping[str, Any]) -> str:
    lignes = [f"# Sécurité MCP — {rapport['reussis']}/{rapport['cas']} cas",
              f"Score pondéré : {rapport['score']:.4f} · registre révision {rapport['garde']['revision_registre']} · "
              f"{'QUALIFIÉ' if rapport['qualifie'] else 'NON QUALIFIÉ'}"]
    for e in rapport["echecs"]:
        lignes.append(f"- ÉCHEC {e['id']} ({e['gravite']}) : attendu {e['attendu']}, obtenu {e['obtenu']}")
    return "\n".join(lignes) + "\n"


def lancer_depuis_cli(chemin_corpus: Path | None = None) -> tuple[dict[str, Any], str]:
    from .. import etat
    from ..departements import charger_departements
    from ..registre_mcp.inventaire import inventaire

    corpus = charger_corpus_mcp(chemin_corpus or FICHIER_CORPUS_MCP)
    rapport = evaluer(corpus, inventaire(charger_departements(), etat.session))
    return rapport, rapport_markdown(rapport)


def serialiser(rapport: Mapping[str, Any]) -> str:
    return json.dumps(rapport, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
