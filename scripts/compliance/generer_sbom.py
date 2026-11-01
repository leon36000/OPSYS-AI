#!/usr/bin/env python3
"""SBOM CycloneDX 1.5 reproductible d'OPSYS-AI et contrôle de la politique de licences (stdlib, hors ligne).

Entrées, toutes dans le dépôt : `uv.lock` et `requirements-*.lock.txt` (Python), `core/pnpm-lock.yaml` (OPSYS-CORE),
`mobile/package-lock.json` (application mobile), `docs/compliance/donnees/*.json` (constats de licences, politique,
composants hors gestionnaire, dette `non-verifiees-reconnues.json`). Aucune horloge, aucun réseau : deux exécutions sur
le même dépôt donnent des octets identiques (le numéro de série est un UUID v5 du contenu).

  python scripts/compliance/generer_sbom.py --ecrire        # réécrit docs/compliance/sbom.cdx.json
  python scripts/compliance/generer_sbom.py --verifier       # échoue si le SBOM committé n'est plus celui du dépôt
  python scripts/compliance/generer_sbom.py --rapport        # résumé + violations de politique (code 1 s'il y en a)
  python scripts/compliance/generer_sbom.py --reconnaitre-non-verifiees   # réécrit la dette (revue humaine requise)
"""

# ruff: noqa: E501  (assertions et chaînes de documentation longues, lisibles telles quelles)

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import sys
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _licences as L  # noqa: E402

FICHIER_RECONNUES = L.DONNEES / "non-verifiees-reconnues.json"
TYPES_CYCLONEDX = {"application": "application", "image": "container", "bibliotheque": "library",
                   "paquets-systeme": "library", "polices": "data", "modele-3d": "data", "icones": "data"}
SPDX_NON_VALIDES = re.compile(r"EUPL-1\.1\+|LicenseRef-|(^|[ (])BSD([ )]|$)|(^|[ (])Apache([ )]|$)")


def _version_opsys() -> str:
    texte = (L.RACINE / "src" / "opsys" / "__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__\s*=\s*"([^"]+)"', texte).group(1)


def _lire_json(chemin: Path) -> Any:
    return json.loads(chemin.read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------------------ résolution des licences
def resoudre(constats: dict[str, Any], ecosysteme: str, nom: str, version: str) -> dict[str, Any]:
    """Licence d'un composant d'après (dans l'ordre) : normalisation manuelle, relevé local, déclaration du dépôt."""
    cle = f"{nom}=={version}" if ecosysteme == "pypi" else f"{nom}@{version}"
    manuelle = constats.get("normalisations_manuelles", {}).get(ecosysteme, {}).get(cle)
    releve = constats.get(ecosysteme, {}).get(cle)
    if manuelle and releve:
        return {"spdx": manuelle["spdx"], "niveau": "metadonnees_locales", "source": constats["sources"][releve["source"]],
                "brut": releve["brut"], "raison": manuelle["justification"]}
    if releve and releve.get("spdx"):
        return {"spdx": releve["spdx"], "niveau": "metadonnees_locales", "source": constats["sources"][releve["source"]],
                "brut": releve["brut"], "raison": None}
    declaration = constats.get("declarations_documentation", {}).get(ecosysteme, {}).get(nom)
    if declaration:
        return {"spdx": declaration["spdx"], "niveau": declaration["niveau"], "source": declaration["source"],
                "brut": None, "raison": None}
    raison = releve.get("raison") if releve else "aucune métadonnée de ce paquet n'existe sur la machine du relevé"
    return {"spdx": None, "niveau": "non_verifiee", "source": None, "brut": releve.get("brut") if releve else None,
            "raison": raison}


# ------------------------------------------------------------------------------------------------ inventaire
def inventaire(constats: dict[str, Any]) -> list[dict[str, Any]]:
    racine = L.RACINE
    composants: dict[tuple[str, str, str], dict[str, Any]] = {}

    def ajouter(eco: str, nom: str, version: str, portee: str, groupes: list[str], licence: dict[str, Any]) -> None:
        cle = (eco, nom, version)
        existant = composants.get(cle)
        if existant:  # même composant vu par plusieurs verrous : la portée la plus exposée gagne
            ordre = {"production": 0, "production-optionnel": 1, "developpement": 2}
            if ordre[portee] < ordre[existant["portee"]]:
                existant["portee"] = portee
            existant["groupes"] = sorted(set(existant["groupes"]) | set(groupes))
            return
        composants[cle] = {"ecosysteme": eco, "nom": nom, "version": version, "portee": portee,
                           "groupes": sorted(groupes), **licence}

    # Python
    runtime = L.lire_exigences(racine / "requirements-runtime.lock.txt")
    embeddings = L.lire_exigences(racine / "requirements-embeddings-local.lock.txt")
    pdf = L.lire_exigences(racine / "requirements-ingestion-pdf.lock.txt")
    tous_uv = L.lire_uv_lock(racine / "uv.lock")
    for (nom, version) in sorted(set(runtime) | set(embeddings) | set(pdf) | tous_uv):
        if (nom, version) in runtime:
            portee, groupes = "production", ["requirements-runtime.lock.txt"]
        elif (nom, version) in embeddings or (nom, version) in pdf:
            portee = "production-optionnel"
            groupes = (["extra embeddings-local"] if (nom, version) in embeddings else []) + (
                ["extra ingestion-pdf"] if (nom, version) in pdf else [])
        else:
            portee, groupes = "developpement", ["uv.lock (extra dev ou groupe build)"]
        ajouter("pypi", nom, version, portee, groupes, resoudre(constats, "pypi", nom, version))
    # OPSYS-CORE
    prod, tous = L.lire_pnpm_lock(racine / "core" / "pnpm-lock.yaml")
    for (nom, version) in sorted(tous):
        portee = "production" if (nom, version) in prod else "developpement"
        ajouter("npm-core", nom, version, portee, ["core/pnpm-lock.yaml"], resoudre(constats, "npm-core", nom, version))
    # mobile : la licence vient du verrou lui-même
    for p in L.lire_package_lock(racine / "mobile" / "package-lock.json"):
        if p["lien"] or not p["version"]:
            continue
        spdx, brut = L.spdx_depuis_package_json(p["licence_brute"])
        licence = {"spdx": spdx, "niveau": "verrou" if spdx else "non_verifiee",
                   "source": "mobile/package-lock.json (champ license)" if spdx else None,
                   "brut": brut, "raison": None if spdx else "champ license absent du verrou"}
        ajouter("npm-mobile", p["nom"], p["version"], "developpement" if p["dev"] else "production",
                ["mobile/package-lock.json"], licence)
    return sorted(composants.values(), key=lambda c: (c["ecosysteme"], c["nom"], c["version"]))


def cle_dette(c: dict[str, Any]) -> str:
    return f"{c['nom']}=={c['version']}" if c["ecosysteme"] == "pypi" else f"{c['nom']}@{c['version']}"


# ---------------------------------------------------------------------------------------------------- politique
def evaluer(composants: list[dict[str, Any]], hors: dict[str, Any], politique: dict[str, Any],
            reconnues: dict[str, list[str]]) -> dict[str, Any]:
    """Violations (échec), écarts ouverts consignés, dettes et incohérences de consignes (périmées)."""
    violations: list[str] = []
    ecarts_vus: set[str] = set()
    decisions_vues: set[str] = set()
    dette_vue: dict[str, set[str]] = {e: set() for e in ("pypi", "npm-core", "npm-mobile")}
    decisions = {d["composant"]: d for d in politique["decisions_copyleft_faible"]}  # clé : motif fnmatch « eco:nom »
    ecarts = {d["composant"]: d for d in politique["ecarts_ouverts"]}
    surveillance_dev: list[str] = []
    stats: Counter = Counter()

    for c in composants:
        id_c = f"{c['ecosysteme']}:{c['nom']}"
        classe, detail = L.evaluer_expression(politique, c["spdx"])
        c["classe"] = classe
        stats[(c["ecosysteme"], c["portee"], c["niveau"])] += 1
        if c["portee"] == "developpement":
            if classe in ("copyleft_fort", "usage_restreint"):
                surveillance_dev.append(f"{id_c}@{c['version']} : {c['spdx']}")
            continue
        if c["spdx"] is None:
            if cle_dette(c) in reconnues.get(c["ecosysteme"], []):
                dette_vue[c["ecosysteme"]].add(cle_dette(c))
            else:
                violations.append(f"LICENCE-INCONNUE {id_c}@{c['version']} ({c['portee']}) : aucune source ne porte sa licence ; "
                                  "relever la licence ou la consigner dans non-verifiees-reconnues.json")
            continue
        if classe == "inconnue":
            violations.append(f"LICENCE-NON-CLASSEE {id_c}@{c['version']} : {detail} absent de la politique")
        elif classe == "copyleft_faible":
            d = next((x for motif, x in decisions.items() if fnmatch.fnmatchcase(id_c, motif)), None)
            if d is None:
                violations.append(f"DECISION-MANQUANTE {id_c}@{c['version']} : {c['spdx']} (copyleft faible) sans décision consignée")
            elif d["licence"] != c["spdx"]:
                violations.append(f"DECISION-OBSOLETE {id_c} : décision pour « {d['licence']} », composant sous « {c['spdx']} »")
            else:
                decisions_vues.add(d["composant"])
        elif classe in ("copyleft_fort", "usage_restreint"):
            e = ecarts.get(id_c)
            if e is not None and e["licence"] == c["spdx"]:
                ecarts_vus.add(id_c)
            else:
                violations.append(f"LICENCE-INTERDITE {id_c}@{c['version']} : {c['spdx']} ({classe}) dans le code distribué")

    for h in hors["composants"]:
        classe, detail = L.evaluer_expression(politique, h["spdx"])
        if h["portee"] == "developpement":
            continue
        if h["spdx"] is None:
            if not h.get("raison"):
                violations.append(f"HORS-GESTIONNAIRE {h['id']} : licence absente sans raison")
        elif classe in ("copyleft_fort", "usage_restreint") and not (h.get("isole") and h.get("isolation")):
            violations.append(f"LICENCE-INTERDITE hors-gestionnaire {h['id']} : {h['spdx']} sans isolement documenté")
        elif classe == "inconnue":
            violations.append(f"LICENCE-NON-CLASSEE hors-gestionnaire {h['id']} : {h['spdx']}")
        if h["niveau"] not in ("fichier_depot", "documentation_depot", "non_verifiee"):
            violations.append(f"HORS-GESTIONNAIRE {h['id']} : niveau « {h['niveau']} » inconnu")

    perimees = []
    for id_c in decisions:
        if id_c not in decisions_vues:
            perimees.append(f"décision sans composant de production correspondant : {id_c}")
    for id_c in ecarts:
        if id_c not in ecarts_vus:
            perimees.append(f"écart ouvert sans composant correspondant (corrigé ou retiré ?) : {id_c}")
    for eco, cles in reconnues.items():
        if eco in ("schema", "date", "note"):
            continue
        for cle in cles:
            if cle not in dette_vue.get(eco, set()):
                perimees.append(f"dette reconnue périmée : {eco}:{cle}")
    return {"violations": violations, "ecarts_ouverts": sorted(ecarts_vus), "decisions": sorted(decisions_vues),
            "dette": {e: sorted(v) for e, v in dette_vue.items()}, "consignes_perimees": perimees,
            "surveillance_dev": sorted(surveillance_dev), "stats": stats}


# ---------------------------------------------------------------------------------------------------------- SBOM
def _licences_cdx(spdx: str | None) -> list[dict[str, Any]] | None:
    if not spdx:
        return None
    if SPDX_NON_VALIDES.search(spdx):
        return [{"license": {"name": spdx}}]
    return [{"expression": spdx}]


def construire_sbom(composants: list[dict[str, Any]], hors: dict[str, Any], constats: dict[str, Any]) -> dict[str, Any]:
    items = []
    for c in composants:
        item: dict[str, Any] = {
            "type": "library", "bom-ref": f"{c['ecosysteme']}|{L.purl(c['ecosysteme'], c['nom'], c['version'])}",  # un même paquet npm peut être dans le core ET le mobile
            "name": c["nom"],
            "version": c["version"], "purl": L.purl(c["ecosysteme"], c["nom"], c["version"]),
            "scope": {"production": "required", "production-optionnel": "optional", "developpement": "excluded"}[c["portee"]],
        }
        lic = _licences_cdx(c["spdx"])
        if lic:
            item["licenses"] = lic
        props = [("opsys:ecosysteme", c["ecosysteme"]), ("opsys:portee", c["portee"]),
                 ("opsys:verification", c["niveau"]), ("opsys:groupes", "; ".join(c["groupes"]))]
        if c["source"]:
            props.append(("opsys:source-licence", c["source"]))
        if c.get("raison"):
            props.append(("opsys:note-licence", c["raison"]))
        item["properties"] = [{"name": n, "value": v} for n, v in props]
        items.append(item)
    for h in hors["composants"]:
        item = {"type": TYPES_CYCLONEDX[h["type"]], "bom-ref": f"opsys:hors-gestionnaire/{h['id']}", "name": h["nom"],
                "version": h["version"],
                "scope": {"production": "required", "production-optionnel": "optional", "developpement": "excluded"}[h["portee"]]}
        lic = _licences_cdx(h["spdx"])
        if lic:
            item["licenses"] = lic
        props = [("opsys:ecosysteme", "hors-gestionnaire"), ("opsys:portee", h["portee"]),
                 ("opsys:verification", h["niveau"]), ("opsys:source-licence", h["source"])]
        if h.get("raison"):
            props.append(("opsys:note-licence", h["raison"]))
        if h.get("note"):
            props.append(("opsys:remarque", h["note"]))
        item["properties"] = [{"name": n, "value": v} for n, v in props]
        items.append(item)
    items.sort(key=lambda i: i["bom-ref"])
    corps = json.dumps(items, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    empreinte = hashlib.sha256(corps.encode("utf-8")).hexdigest()
    compte = Counter(i["scope"] for i in items)
    return {
        "bomFormat": "CycloneDX", "specVersion": "1.5",
        "serialNumber": "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL, "opsys-ai-sbom/" + empreinte)),
        "version": 1,
        "metadata": {
            "component": {"type": "application", "bom-ref": "opsys-ai", "name": "opsys-ai", "version": _version_opsys()},
            "properties": [
                {"name": "opsys:generateur", "value": "scripts/compliance/generer_sbom.py (stdlib, sans horloge ni réseau)"},
                {"name": "opsys:date-releve-licences", "value": constats["date_releve"]},
                {"name": "opsys:composants-requis", "value": str(compte["required"])},
                {"name": "opsys:composants-optionnels", "value": str(compte["optional"])},
                {"name": "opsys:composants-exclus-developpement", "value": str(compte["excluded"])},
                {"name": "opsys:avertissement", "value": "Les licences portent leur niveau de vérification (opsys:verification) : "
                 "aucune n'a été revérifiée à la source ; non_verifiee = aucune source locale. Pas un avis juridique."},
            ],
        },
        "components": items,
    }


def serialiser(sbom: dict[str, Any]) -> str:
    return json.dumps(sbom, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


def charger_tout() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    constats = _lire_json(L.FICHIER_CONSTATS)
    politique = L.charger_politique()
    hors = _lire_json(L.FICHIER_HORS_GESTIONNAIRE)
    reconnues = _lire_json(FICHIER_RECONNUES) if FICHIER_RECONNUES.exists() else {}
    return constats, politique, hors, reconnues


def main(argv: list[str] | None = None) -> int:
    a = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = a.add_mutually_exclusive_group(required=True)
    g.add_argument("--ecrire", action="store_true")
    g.add_argument("--verifier", action="store_true")
    g.add_argument("--rapport", action="store_true")
    g.add_argument("--reconnaitre-non-verifiees", action="store_true")
    args = a.parse_args(argv)
    constats, politique, hors, reconnues = charger_tout()
    composants = inventaire(constats)

    if args.reconnaitre_non_verifiees:
        dette: dict[str, Any] = {"schema": "opsys.conformite.non-verifiees/v1", "date": constats["date_releve"],
                                 "note": "DETTE VISIBLE : composants de production (ou optionnels) dont aucune source locale ne porte la licence. "
                                         "Chaque ligne est une licence NON VERIFIEE, pas une licence acceptable. Un composant NOUVEAU absent de "
                                         "cette liste fait échouer tests/test_conformite_licences.py."}
        for eco in ("pypi", "npm-core", "npm-mobile"):
            dette[eco] = sorted(cle_dette(c) for c in composants
                                if c["ecosysteme"] == eco and c["portee"] != "developpement" and c["spdx"] is None)
        FICHIER_RECONNUES.write_text(json.dumps(dette, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print({e: len(dette[e]) for e in ("pypi", "npm-core", "npm-mobile")})
        return 0

    sbom = serialiser(construire_sbom(composants, hors, constats))
    if args.ecrire:
        L.FICHIER_SBOM.write_text(sbom, encoding="utf-8")
        print(f"SBOM écrit : {len(composants)} composants de gestionnaires + {len(hors['composants'])} hors gestionnaire")
        return 0
    if args.verifier:
        actuel = L.FICHIER_SBOM.read_text(encoding="utf-8") if L.FICHIER_SBOM.exists() else ""
        if actuel != sbom:
            print("SBOM périmé : relancer `python scripts/compliance/generer_sbom.py --ecrire`", file=sys.stderr)
            return 1
        print("SBOM à jour")
        return 0
    rapport = evaluer(composants, hors, politique, reconnues)
    for (eco, portee, niveau), n in sorted(rapport["stats"].items()):
        print(f"{eco:11} {portee:21} {niveau:21} {n}")
    for v in rapport["violations"]:
        print("VIOLATION", v)
    for e in rapport["ecarts_ouverts"]:
        print("ECART OUVERT", e)
    for p in rapport["consignes_perimees"]:
        print("PERIMEE", p)
    return 1 if rapport["violations"] or rapport["consignes_perimees"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
