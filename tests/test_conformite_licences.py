"""Conformité des licences : SBOM reproductible, politique appliquée, dette visible, cohérence avec les notices.

Les tests lisent les VRAIS verrous et fichiers de données du dépôt (aucun réseau). Les cas négatifs travaillent sur des
copies en mémoire : ils prouvent que le contrôle échoue quand une dépendance de production arrive sans licence connue, avec
une licence interdite, ou quand une consigne (décision, écart, dette) est périmée. Voir `docs/compliance/INVENTAIRE-LICENCES.md`.
"""

# ruff: noqa: E501  (assertions et chaînes de documentation longues, lisibles telles quelles)

from __future__ import annotations

import copy
import importlib.util
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
DOSSIER = RACINE / "scripts" / "compliance"


def _charger(nom: str):
    sys.path.insert(0, str(DOSSIER))
    spec = importlib.util.spec_from_file_location(nom, DOSSIER / f"{nom}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    spec.loader.exec_module(module)
    return module


L = _charger("_licences")
G = _charger("generer_sbom")


@pytest.fixture(scope="module")
def donnees():
    constats, politique, hors, reconnues = G.charger_tout()
    composants = G.inventaire(constats)
    return constats, politique, hors, reconnues, composants


def _evaluer(donnees, composants=None, politique=None, hors=None, reconnues=None):
    constats, pol, h, rec, comp = donnees
    return G.evaluer(copy.deepcopy(comp if composants is None else composants), h if hors is None else hors,
                     pol if politique is None else politique, rec if reconnues is None else reconnues)


def _composant(eco="pypi", nom="nouveau-paquet", spdx=None, portee="production", version="1.0.0"):
    return {"ecosysteme": eco, "nom": nom, "version": version, "portee": portee, "groupes": ["test"], "spdx": spdx,
            "niveau": "metadonnees_locales" if spdx else "non_verifiee", "source": "test", "brut": None, "raison": None}


# ------------------------------------------------------------------------------------------------ état du dépôt
def test_le_depot_respecte_sa_politique_de_licences(donnees):
    rapport = _evaluer(donnees)
    assert rapport["violations"] == []
    assert rapport["consignes_perimees"] == []


def test_l_ecart_libsignal_est_consigne_et_visible(donnees):
    rapport = _evaluer(donnees)
    assert rapport["ecarts_ouverts"] == ["npm-core:libsignal"]
    ecart = next(e for e in donnees[1]["ecarts_ouverts"] if e["composant"] == "npm-core:libsignal")
    assert ecart["licence"] == "GPL-3.0" and ecart["statut"] == "ecart_ouvert_decision_requise"
    assert "extensions/whatsapp" in ecart["chaine"]


def test_aucun_composant_de_production_n_est_sous_copyleft_fort_ou_usage_restreint_hors_ecart(donnees):
    comp = copy.deepcopy(donnees[4])
    rapport = G.evaluer(comp, donnees[2], donnees[1], donnees[3])
    fautifs = [f"{c['ecosysteme']}:{c['nom']}" for c in comp
               if c["portee"] != "developpement" and c["classe"] in ("copyleft_fort", "usage_restreint")]
    assert fautifs == rapport["ecarts_ouverts"] == ["npm-core:libsignal"]


# ------------------------------------------------------------------------------------------------------ SBOM
def test_le_sbom_commite_est_celui_du_depot(donnees):
    constats, _, hors, _, composants = donnees
    attendu = G.serialiser(G.construire_sbom(composants, hors, constats))
    assert (RACINE / "docs/compliance/sbom.cdx.json").read_text(encoding="utf-8") == attendu, \
        "SBOM périmé : python scripts/compliance/generer_sbom.py --ecrire"


def test_le_sbom_est_reproductible_dans_un_autre_processus(tmp_path):
    chemin = RACINE / "docs/compliance/sbom.cdx.json"
    env = {**os.environ, "PYTHONHASHSEED": "12345", "HOME": str(tmp_path), "TMPDIR": str(tmp_path)}
    sortie = subprocess.run([sys.executable, str(DOSSIER / "generer_sbom.py"), "--verifier"], cwd=tmp_path, env=env,
                            capture_output=True, text=True, timeout=120)
    assert sortie.returncode == 0, sortie.stderr
    assert "à jour" in sortie.stdout
    assert chemin.read_text(encoding="utf-8")  # non vide


def test_le_sbom_est_un_cyclonedx_valide_dans_sa_forme():
    sbom = json.loads((RACINE / "docs/compliance/sbom.cdx.json").read_text(encoding="utf-8"))
    assert sbom["bomFormat"] == "CycloneDX" and sbom["specVersion"] == "1.5" and sbom["version"] == 1
    assert uuid.UUID(sbom["serialNumber"].removeprefix("urn:uuid:")).version == 5
    refs = [c["bom-ref"] for c in sbom["components"]]
    assert len(refs) == len(set(refs)) and refs == sorted(refs)
    assert all(c["scope"] in ("required", "optional", "excluded") for c in sbom["components"])
    assert "timestamp" not in sbom["metadata"]  # reproductible : aucune horloge
    texte = json.dumps(sbom)
    assert not re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", texte), "horodatage dans le SBOM"
    types = {c["type"] for c in sbom["components"]}
    assert {"library", "container", "application"} <= types
    sans_licence = [c for c in sbom["components"] if "licenses" not in c]
    assert sans_licence and all(
        any(p["name"] == "opsys:verification" and p["value"] == "non_verifiee" for p in c["properties"]) for c in sans_licence), \
        "un composant sans licence doit se dire non_verifiee, jamais passer pour sain"


def test_le_sbom_inventorie_les_verrous_reels(donnees):
    sbom = json.loads((RACINE / "docs/compliance/sbom.cdx.json").read_text(encoding="utf-8"))
    refs = {c["bom-ref"] for c in sbom["components"]}
    assert "pypi|pkg:pypi/sqlalchemy@2.1.1" in refs and "pypi|pkg:pypi/psycopg@3.2.3" in refs
    assert "npm-core|pkg:npm/libsignal@6.0.0" in refs
    lock = (RACINE / "requirements-runtime.lock.txt").read_text(encoding="utf-8")
    for nom, version in re.findall(r"^([A-Za-z0-9_.-]+)==([^\s;\\]+)", lock, re.M):
        assert "pypi|" + L.purl("pypi", L.normaliser_nom_pypi(nom), version) in refs, nom
    for h in json.loads((RACINE / "docs/compliance/donnees/composants-hors-gestionnaire.json").read_text(encoding="utf-8"))["composants"]:
        assert f"opsys:hors-gestionnaire/{h['id']}" in refs


def test_les_comptes_du_sbom_sont_ceux_de_l_inventaire_documente(donnees):
    sbom = json.loads((RACINE / "docs/compliance/sbom.cdx.json").read_text(encoding="utf-8"))
    doc = (RACINE / "docs/compliance/INVENTAIRE-LICENCES.md").read_text(encoding="utf-8")
    n_gestionnaires = sum(1 for c in sbom["components"] if not c["bom-ref"].startswith("opsys:hors-gestionnaire/"))
    n_hors = len(sbom["components"]) - n_gestionnaires
    assert f"**{n_gestionnaires:,}**".replace(",", " ") in doc and f"**{n_hors}** composants hors gestionnaire" in doc
    lignes = {}
    for ecosysteme, portee, n in re.findall(r"^\| ([^|]+) \| ([^|]+) \| (\d+) \| \d+ \|$", doc, re.M):
        lignes[(ecosysteme.strip(), portee.strip())] = int(n)
    reels: dict[tuple[str, str], int] = {}
    for c in donnees[4]:
        reels[(c["ecosysteme"], c["portee"])] = reels.get((c["ecosysteme"], c["portee"]), 0) + 1
    assert sum(v for k, v in lignes.items() if not k[0].startswith("Hors")) == sum(reels.values())
    assert lignes[("OPSYS-CORE (`npm-core`)", "production (fermeture de `core/pnpm-lock.yaml`)")] == reels[("npm-core", "production")]
    assert lignes[("Mobile (`npm-mobile`)", "développement")] == reels[("npm-mobile", "developpement")]
    assert lignes[("Python (`pypi`)", "production (`requirements-runtime.lock.txt`)")] == reels[("pypi", "production")]


# ----------------------------------------------------------------------- cas négatifs : licences interdites ou inconnues
@pytest.mark.parametrize("licence,motif", [
    ("AGPL-3.0-only", "LICENCE-INTERDITE"), ("GPL-3.0-or-later", "LICENCE-INTERDITE"), ("GPL-2.0-only", "LICENCE-INTERDITE"),
    ("SSPL-1.0", "LICENCE-INTERDITE"), ("BUSL-1.1", "LICENCE-INTERDITE"), ("Elastic-2.0", "LICENCE-INTERDITE"),
    ("CC-BY-NC-4.0", "LICENCE-INTERDITE"), ("PolyForm-Noncommercial-1.0.0", "LICENCE-INTERDITE"),
    ("Acme-Non-Commercial-1.0", "LICENCE-INTERDITE"), ("Commons-Clause", "LICENCE-INTERDITE"),
    ("LGPL-2.1-only", "DECISION-MANQUANTE"), ("MPL-2.0", "DECISION-MANQUANTE"),
    ("Licence-Maison-X", "LICENCE-NON-CLASSEE"),
])
def test_une_dependance_de_production_sous_licence_interdite_ou_non_decidee_fait_echouer(donnees, licence, motif):
    comp = list(donnees[4]) + [_composant(spdx=licence)]
    rapport = _evaluer(donnees, composants=comp)
    assert any(v.startswith(motif) and "nouveau-paquet" in v for v in rapport["violations"]), rapport["violations"]


@pytest.mark.parametrize("eco", ["pypi", "npm-core", "npm-mobile"])
def test_une_dependance_de_production_sans_licence_connue_fait_echouer(donnees, eco):
    comp = list(donnees[4]) + [_composant(eco=eco, spdx=None)]
    rapport = _evaluer(donnees, composants=comp)
    assert any(v.startswith("LICENCE-INCONNUE") and "nouveau-paquet" in v for v in rapport["violations"])


def test_une_dependance_optionnelle_est_controlee_comme_la_production(donnees):
    comp = list(donnees[4]) + [_composant(spdx="AGPL-3.0-only", portee="production-optionnel")]
    assert any("LICENCE-INTERDITE" in v for v in _evaluer(donnees, composants=comp)["violations"])


def test_une_dependance_de_developpement_fautive_est_surveillee_sans_faire_echouer(donnees):
    comp = list(donnees[4]) + [_composant(spdx="GPL-3.0-only", portee="developpement")]
    rapport = _evaluer(donnees, composants=comp)
    assert rapport["violations"] == [] and any("nouveau-paquet" in s for s in rapport["surveillance_dev"])


def test_une_licence_inconnue_connue_de_la_dette_ne_fait_pas_echouer_mais_la_dette_perimee_echoue(donnees):
    c = _composant(spdx=None)
    reconnues = copy.deepcopy(donnees[3])
    reconnues["pypi"] = list(reconnues["pypi"]) + ["nouveau-paquet==1.0.0"]
    ok = _evaluer(donnees, composants=list(donnees[4]) + [c], reconnues=reconnues)
    assert ok["violations"] == [] and ok["consignes_perimees"] == []
    perimee = _evaluer(donnees, reconnues=reconnues)  # le composant n'existe plus : la consigne reste, donc périmée
    assert any("dette reconnue périmée" in p and "nouveau-paquet" in p for p in perimee["consignes_perimees"])
    # la licence est enfin relevée : la ligne de dette devient périmée elle aussi
    releve = _evaluer(donnees, composants=list(donnees[4]) + [_composant(spdx="MIT")], reconnues=reconnues)
    assert any("dette reconnue périmée" in p for p in releve["consignes_perimees"])


def test_un_ecart_ouvert_corrige_ou_retire_est_signale_comme_perime(donnees):
    comp = [c for c in donnees[4] if c["nom"] != "libsignal"]
    rapport = _evaluer(donnees, composants=comp)
    assert any("libsignal" in p for p in rapport["consignes_perimees"])


def test_un_changement_de_licence_ne_passe_pas_sous_une_decision_obsolete(donnees):
    comp = [dict(c, spdx="LGPL-2.1-only") if c["nom"] == "psycopg" and c["ecosysteme"] == "pypi" else c for c in donnees[4]]
    assert any(v.startswith("DECISION-OBSOLETE pypi:psycopg") for v in _evaluer(donnees, composants=comp)["violations"])


def test_une_decision_sans_composant_correspondant_est_perimee(donnees):
    pol = copy.deepcopy(donnees[1])
    pol["decisions_copyleft_faible"].append({"composant": "pypi:fantome", "licence": "MPL-2.0", "statut": "x", "decision": "y", "date": "z"})
    assert any("pypi:fantome" in p for p in _evaluer(donnees, politique=pol)["consignes_perimees"])


def test_un_composant_hors_gestionnaire_copyleft_exige_son_isolement(donnees):
    hors = copy.deepcopy(donnees[2])
    plugin = next(h for h in hors["composants"] if h["id"] == "wordpress-opsys-connect")
    assert plugin["spdx"] == "GPL-2.0-or-later" and plugin["isole"] is True
    assert _evaluer(donnees, hors=hors)["violations"] == []
    plugin["isole"] = False
    assert any("wordpress-opsys-connect" in v and "LICENCE-INTERDITE" in v for v in _evaluer(donnees, hors=hors)["violations"])
    plugin["isole"] = True
    del plugin["isolation"]
    assert any("wordpress-opsys-connect" in v for v in _evaluer(donnees, hors=hors)["violations"])


def test_un_composant_hors_gestionnaire_sans_licence_exige_une_raison(donnees):
    hors = copy.deepcopy(donnees[2])
    image = next(h for h in hors["composants"] if h["id"] == "image-python")
    del image["raison"]
    assert any("image-python" in v for v in _evaluer(donnees, hors=hors)["violations"])


# ----------------------------------------------------------------------------------- expressions SPDX et classement
@pytest.mark.parametrize("expression,classe", [
    ("MIT", "permissive"), ("(MIT OR GPL-3.0-or-later)", "permissive"), ("MIT AND MPL-2.0", "copyleft_faible"),
    ("Apache-2.0 OR BSD-3-Clause", "permissive"), ("MIT AND GPL-3.0", "copyleft_fort"), ("(MIT AND (ISC OR AGPL-3.0-only))", "permissive"),
    ("LGPL-3.0-only", "copyleft_faible"), ("GPL-3.0", "copyleft_fort"), ("Apache-2.0 WITH LLVM-exception", "permissive"),
    ("(GPL-2.0-only OR CC-BY-NC-4.0)", "usage_restreint"), ("MIT AND", "inconnue"), ("(MIT", "inconnue"), ("", "inconnue"),
    ("MIT OR", "inconnue"), ("Inconnu-1.0", "inconnue"),
])
def test_evaluation_des_expressions_spdx(donnees, expression, classe):
    assert L.evaluer_expression(donnees[1], expression)[0] == classe


def test_lgpl_n_est_pas_prise_pour_gpl(donnees):
    assert L.classer_identifiant(donnees[1], "LGPL-3.0-or-later") == "copyleft_faible"
    assert L.classer_identifiant(donnees[1], "AGPL-3.0-only") == "copyleft_fort"
    assert L.classer_identifiant(donnees[1], "Sleepy-NC-Licence") == "usage_restreint"


def test_les_metadonnees_pypi_ne_devinent_pas_la_variante_bsd():
    assert L.spdx_depuis_metadonnees_pypi(None, None, ["BSD License"])[0] is None
    assert L.spdx_depuis_metadonnees_pypi(None, None, ["MIT License"])[0] == "MIT"
    assert L.spdx_depuis_metadonnees_pypi("Apache-2.0 OR BSD-3-Clause", None, [])[0] == "Apache-2.0 OR BSD-3-Clause"
    assert L.spdx_depuis_metadonnees_pypi(None, "BSD license (see license.txt for details), Copyright", ["BSD License"])[0] is None
    assert L.spdx_depuis_package_json("SEE LICENSE IN LICENSE.txt")[0] is None
    assert L.spdx_depuis_package_json({"type": "ISC"})[0] == "ISC"
    assert L.spdx_depuis_package_json(None, [{"type": "MIT"}, {"type": "Apache-2.0"}])[0] == "(MIT OR Apache-2.0)"


# ------------------------------------------------------------------------- verrous : le parseur lit bien la réalité
def test_la_fermeture_de_production_du_core_est_coherente():
    prod, tous = L.lire_pnpm_lock(RACINE / "core/pnpm-lock.yaml")
    assert prod <= tous and len(tous) > len(prod) > 800
    noms = {n for n, _ in prod}
    assert {"baileys", "libsignal", "zod"} <= noms
    assert "vitest" not in noms and any(n == "vitest" for n, _ in tous)


def test_les_verrous_python_sont_lus():
    runtime = L.lire_exigences(RACINE / "requirements-runtime.lock.txt")
    assert ("sqlalchemy", "2.1.1") in runtime and ("psycopg", "3.2.3") in runtime
    assert ("pytest", "9.1.1") not in runtime and ("pytest", "9.1.1") in L.lire_uv_lock(RACINE / "uv.lock")


# -------------------------------------------------------------------- cohérence avec les notices et la documentation
def test_chaque_notice_tierce_du_core_est_dans_les_composants_hors_gestionnaire(donnees):
    notices = (RACINE / "core/THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    titres = re.findall(r"^## (.+)$", notices, re.M)
    assert titres == ["Pi / pi-mono", "GitHub Octicons", "Three.js"]  # 3 notices, pas « 239 » : voir INVENTAIRE-LICENCES.md
    ids = {h["id"]: h for h in donnees[2]["composants"]}
    assert ids["notice-pi-mono"]["spdx"] == "MIT" and ids["notice-octicons"]["spdx"] == "MIT" and ids["three-js"]["spdx"] == "MIT"
    assert "License: MIT" in notices and "Three.js is MIT-licensed" in notices
    assert not (RACINE / "docs/LICENCES.md").exists()
    assert "n'existe" in (RACINE / "docs/compliance/INVENTAIRE-LICENCES.md").read_text(encoding="utf-8")


def test_les_sources_citees_dans_les_donnees_existent_dans_le_depot(donnees):
    fichiers = set()
    for h in donnees[2]["composants"]:
        fichiers.update(re.findall(r"\b((?:core|integrations|mobile|docs|deploy|departments|src)/[A-Za-z0-9_./@+-]+\.(?:md|json|txt|php|py|yml|ttf)|LICENSE)\b",
                                   h["source"]))
    assert fichiers
    manquants = sorted(f for f in fichiers if not (RACINE / f).exists())
    assert manquants == []
    assert (RACINE / "docs/research/INGREDIENTS.md").exists()


def test_les_licences_de_la_documentation_du_depot_concordent_avec_les_donnees(donnees):
    lignes = (RACINE / "docs/research/INGREDIENTS.md").read_text(encoding="utf-8").splitlines()
    assert "NumPy BSD-3-Clause" in lignes[234] and "Tokenizers Apache-2.0" in lignes[234] and "ONNX Runtime MIT" in lignes[234]
    assert lignes[357].startswith("| **PyVRP** | MIT")
    for nom, ligne in (("numpy", 235), ("onnxruntime", 235), ("tokenizers", 235), ("pyvrp", 358)):
        assert nom in donnees[0]["declarations_documentation"]["pypi"]
        assert f"l.{ligne}" in donnees[0]["declarations_documentation"]["pypi"][nom]["source"]


def test_le_plugin_wordpress_declare_bien_sa_licence_et_reste_isole():
    en_tete = (RACINE / "integrations/wordpress/opsys-connect/opsys-connect.php").read_text(encoding="utf-8")[:1200]
    assert "License:           GPL-2.0-or-later" in en_tete
    assert "GNU GENERAL PUBLIC LICENSE" in (RACINE / "integrations/wordpress/opsys-connect/LICENSE").read_text(encoding="utf-8")[:200]
    for chemin in list((RACINE / "src").rglob("*.py")) + list((RACINE / "departments").glob("*/src/**/*.py")):
        texte = chemin.read_text(encoding="utf-8", errors="replace")
        assert "import opsys_connect" not in texte and "from opsys_connect" not in texte, chemin


def test_la_licence_du_depot_reste_une_contradiction_consignee():
    assert "Apache License" in (RACINE / "LICENSE").read_text(encoding="utf-8")[:100]
    assert "Licence propriétaire" in (RACINE / "docs/decisions/ADR-0003-RATIFICATION.md").read_text(encoding="utf-8")
    assert "se\ncontredisent" in (RACINE / "README.md").read_text(encoding="utf-8")
    hors = json.loads((RACINE / "docs/compliance/donnees/composants-hors-gestionnaire.json").read_text(encoding="utf-8"))
    assert "ADR-0003" in next(h for h in hors["composants"] if h["id"] == "opsys-ai")["ecart"]


def test_toute_dependance_python_declaree_est_dans_le_sbom():
    import tomllib
    pyproject = tomllib.loads((RACINE / "pyproject.toml").read_text(encoding="utf-8"))
    declarees = {re.split(r"[<>=\[;! ]", d)[0].lower() for d in pyproject["project"]["dependencies"]}
    for extra in pyproject["project"]["optional-dependencies"].values():
        declarees |= {re.split(r"[<>=\[;! ]", d)[0].lower() for d in extra}
    sbom = json.loads((RACINE / "docs/compliance/sbom.cdx.json").read_text(encoding="utf-8"))
    noms = {c["name"] for c in sbom["components"] if c.get("purl", "").startswith("pkg:pypi/")}
    assert sorted(d for d in declarees if L.normaliser_nom_pypi(d) not in noms) == []
