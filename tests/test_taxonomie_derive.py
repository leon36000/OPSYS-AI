"""Garde de dérive de la taxonomie métier (PLAN T0.13).

Trois familles de copies pouvaient diverger en silence ; chacune est maintenant confrontée à sa
source de vérité :

1. la LISTE DES SERVICES : le catalogue vit dans `opsys.taxonomie`, aucune source de département
   ne le recopie (`taxonomie.copies_locales_du_catalogue`, aussi lancée par `opsys verifier`) ;
2. le CONTRAT v2 : le fichier `m1-lead-qualifie.v2.yaml`, M1 (qui l'émet), M2 (qui l'accepte), M3
   (qui le consomme) et M4 (qui inscrit l'intervention) portent les mêmes clés, la même version et
   les mêmes sous-clés `utm` ;
3. l'ÉNUMÉRÉ v1 (contrat gelé) : les copies conservées par M1, M2, M3 et M4 (`contrats.py` et
   `cedule.py`) pour valider les leads v1 sont celles du fichier gelé `m1-lead-qualifie.v1.yaml` ;
   celle de M7 (`chantier_social.py`) en est l'énuméré sans `autre`.

M4 et M7 (PLAN T0.13-b) valident `service` par `opsys.taxonomie`, jamais par une liste locale. Le WCT
`m4.travaux_termines` porte `type_travaux` (lead v1) OU `service` (lead v2), jamais l'un déduit de l'autre :
le catalogue du socle et le contrat de M4 déclarent les deux clés, additives.

Les sources de départements sont lues par AST (décision #109 : aucun import inter-modules, et une
lecture qui n'exécute rien) ; seul le socle est importé.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
import yaml

from opsys import evenements, taxonomie
from opsys.departements import charger_departements

RACINE = Path(__file__).resolve().parents[1]
DEPARTEMENTS = RACINE / "departments"
CONTRATS_M1 = DEPARTEMENTS / "m01-front-office" / "contracts"
SRC_M1 = DEPARTEMENTS / "m01-front-office" / "src" / "m1_front_office"
SRC_M2 = DEPARTEMENTS / "m02-revenue-crm" / "src" / "m2_revenue_crm"
SRC_M3 = DEPARTEMENTS / "m03-estimation" / "src" / "m3_estimation"
SRC_M4 = DEPARTEMENTS / "m04-field-ops" / "src" / "m4_field_ops"
SRC_M7 = DEPARTEMENTS / "m07-marketing" / "src" / "m7_marketing"


def _constante(fichier: Path, nom: str):
    """Valeur littérale de la constante de module `nom` (tuple, ensemble, entier), lue par AST."""
    arbre = ast.parse(fichier.read_text(encoding="utf-8"), filename=str(fichier))
    for noeud in arbre.body:
        if isinstance(noeud, ast.Assign) and any(isinstance(c, ast.Name) and c.id == nom for c in noeud.targets):
            return ast.literal_eval(noeud.value)
    pytest.fail(f"constante {nom} introuvable dans {fichier} — fail-closed")


def _contrat_yaml(nom: str) -> dict:
    return yaml.safe_load((CONTRATS_M1 / nom).read_text(encoding="utf-8"))


def _champs(contrat: dict, requis: bool) -> set[str]:
    return {c["name"] for c in contrat["fields"] if bool(c["required"]) is requis}


def _contrainte(contrat: dict, champ: str) -> str:
    return " ".join(next(c for c in contrat["fields"] if c["name"] == champ)["constraints"])


# ------------------------------------------------------------------------------- 1. la liste
def test_aucun_departement_ne_recopie_le_catalogue_des_services():
    racines = [RACINE / "src" / "opsys", *(d / "src" for d in DEPARTEMENTS.glob("m*") if (d / "src").is_dir())]
    assert taxonomie.copies_locales_du_catalogue(racines) == []


def test_la_garde_detecte_une_copie_locale_sous_toutes_ses_formes(tmp_path):
    (tmp_path / "copie.py").write_text(
        'A = ("gouttieres", "revetement")\n'
        'B = {"soffite_fascia", "reparation", "autre"}\n'
        'C = ["gouttieres", 3, "reparation"]\n'
        'D = {"revetement": 1, "soffite_fascia": 2}\n'
        'SEUL = ("gouttieres",)\n'
        'AUTRES = ("renovation_totale", "extension")\n',
        encoding="utf-8",
    )
    problemes = taxonomie.copies_locales_du_catalogue([tmp_path])
    assert len(problemes) == 4, problemes
    assert all("copie.py" in p and "opsys.taxonomie" in p for p in problemes)
    assert not any(":5" in p or ":6" in p for p in problemes), "un seul code, ou d'autres valeurs : pas une copie"


def test_la_garde_signale_une_source_illisible_au_lieu_de_l_ignorer(tmp_path):
    (tmp_path / "casse.py").write_text("def (:\n", encoding="utf-8")
    problemes = taxonomie.copies_locales_du_catalogue([tmp_path])
    assert len(problemes) == 1 and "non probante" in problemes[0]


def test_le_fichier_du_catalogue_lui_meme_est_exclu():
    assert taxonomie.copies_locales_du_catalogue([Path(taxonomie.__file__).parent]) == []


def test_opsys_verifier_lance_la_garde_de_derive(capsys, monkeypatch):
    from opsys import cli

    monkeypatch.setattr(cli.taxonomie, "copies_locales_du_catalogue", lambda racines: ["copie.py:1 : fictive"])
    code = cli.main(["verifier"])
    assert code == 1
    assert "copie locale" in capsys.readouterr().err


def test_opsys_verifier_refuse_un_profil_d_entreprise_invalide(capsys, opsys_home):
    from opsys import cli

    fichier = taxonomie.fichier_profil()
    fichier.parent.mkdir(parents=True)
    fichier.write_text("services: [service_inexistant]\n", encoding="utf-8")
    assert cli.main(["verifier"]) == 1
    assert "service_inexistant" in capsys.readouterr().err


def test_opsys_verifier_accepte_l_absence_de_profil(capsys, opsys_home):
    from opsys import cli

    assert not taxonomie.fichier_profil().exists()
    assert cli.main(["verifier"]) == 0
    assert "taxonomie sans copie locale" in capsys.readouterr().out
    # et un profil valide
    taxonomie.enregistrer_services(["gouttieres"])
    assert cli.main(["verifier"]) == 0


def test_les_departements_reels_sont_ceux_scannes_par_opsys_verifier():
    deps = charger_departements()
    assert {"m01-front-office", "m02-revenue-crm", "m03-estimation", "m04-field-ops", "m07-marketing"} <= set(deps)
    assert all((d.racine / "src").is_dir() for d in deps.values())


# ------------------------------------------------------------------------------- 2. contrat v2
def test_le_yaml_v2_cite_exactement_le_catalogue_du_socle():
    contraintes = next(c for c in _contrat_yaml("m1-lead-qualifie.v2.yaml")["fields"] if c["name"] == "service")
    citations = [c for c in contraintes["constraints"] if c.startswith("catalogue de référence : ")]
    assert len(citations) == 1, contraintes["constraints"]
    cites = [c.strip() for c in citations[0].split(" : ", 1)[1].split(",")]
    assert cites == list(taxonomie.codes_catalogue())


def test_le_yaml_v2_remplace_type_travaux_par_service_et_porte_la_version():
    v2 = _contrat_yaml("m1-lead-qualifie.v2.yaml")
    assert v2["schema_version"] == 2
    assert "service" in _champs(v2, True) and "type_travaux" not in _champs(v2, True) | _champs(v2, False)
    assert _champs(v2, False) == {"source", "utm", "campagne"}
    v1 = _contrat_yaml("m1-lead-qualifie.v1.yaml")
    assert _champs(v2, True) - {"schema_version", "service"} == _champs(v1, True) - {"type_travaux"}


def test_m1_m2_m3_portent_les_memes_champs_version_et_cles_utm_que_le_yaml_v2():
    v2 = _contrat_yaml("m1-lead-qualifie.v2.yaml")
    obligatoires, optionnels = _champs(v2, True), _champs(v2, False)
    cles_utm = {c.strip() for c in re.findall(r"utm_[a-z]+", _contrainte(v2, "utm"))}

    assert set(_constante(SRC_M1 / "contrats.py", "_CHAMPS_LEAD_V2")) == obligatoires
    assert set(_constante(SRC_M1 / "contrats.py", "_CHAMPS_LEAD_V2_OPTIONNELS")) == optionnels
    assert set(_constante(SRC_M1 / "contrats.py", "_CLES_UTM")) == cles_utm
    assert _constante(SRC_M1 / "contrats.py", "VERSION_LEAD_V2") == v2["schema_version"]

    assert set(_constante(SRC_M2 / "contrats.py", "CHAMPS_CONTRAT_GELE_V2")) == obligatoires
    assert set(_constante(SRC_M2 / "contrats.py", "CHAMPS_CONTRAT_OPTIONNELS")) == optionnels
    assert set(_constante(SRC_M2 / "contrats.py", "CLES_UTM")) == cles_utm
    assert _constante(SRC_M2 / "contrats.py", "VERSION_CONTRAT_V2") == v2["schema_version"]

    assert set(_constante(SRC_M3 / "contrats.py", "CHAMPS_CONTRAT_GELE_V2")) == obligatoires
    assert set(_constante(SRC_M3 / "contrats.py", "CHAMPS_CONTRAT_OPTIONNELS")) == optionnels
    assert set(_constante(SRC_M3 / "contrats.py", "CHAMPS_UTM")) == cles_utm
    assert _constante(SRC_M3 / "contrats.py", "VERSION_CONTRAT_V2") == v2["schema_version"]

    assert set(_constante(SRC_M4 / "contrats.py", "CHAMPS_CONTRAT_GELE_V2")) == obligatoires
    assert set(_constante(SRC_M4 / "contrats.py", "CHAMPS_CONTRAT_OPTIONNELS")) == optionnels
    assert set(_constante(SRC_M4 / "contrats.py", "CLES_UTM")) == cles_utm
    assert _constante(SRC_M4 / "contrats.py", "VERSION_CONTRAT_V2") == v2["schema_version"]


# ------------------------------------------------------------------------------- 3. énuméré v1
def _enum_v1() -> set[str]:
    contrainte = _contrainte(_contrat_yaml("m1-lead-qualifie.v1.yaml"), "type_travaux")
    return {c.strip() for c in contrainte.split(":", 1)[1].split(",")}


@pytest.mark.parametrize("fichier, nom", [
    (SRC_M1 / "contrats.py", "_TYPES_TRAVAUX"),
    (SRC_M2 / "contrats.py", "TYPES_TRAVAUX"),
    (SRC_M3 / "contrats.py", "TYPES_TRAVAUX"),
    (SRC_M4 / "contrats.py", "TYPES_TRAVAUX"),
    (SRC_M4 / "cedule.py", "TYPES_TRAVAUX"),
])
def test_les_copies_de_l_enum_v1_sont_celles_du_contrat_gele(fichier, nom):
    assert set(_constante(fichier, nom)) == _enum_v1()


def test_la_copie_v1_de_m7_est_l_enum_gele_sans_autre():
    """M7 ne compose pas de contenu social pour un chantier « autre » : son énuméré est celui du contrat
    gelé moins `autre`, jamais un type que le contrat v1 ne connaît pas."""
    copie = set(_constante(SRC_M7 / "workflows" / "chantier_social.py", "TYPES_TRAVAUX_V1"))
    assert copie == _enum_v1() - {"autre"}


def test_l_enum_v1_ne_contient_aucun_des_services_du_catalogue():
    """Constat d'origine de T0.13 : la v1 ne peut PAS exprimer les services réels. C'est la raison
    d'être de la v2, pas un défaut à réparer dans la v1 gelée."""
    assert not _enum_v1() & set(taxonomie.codes_catalogue())


# ------------------------------------------------------------------------------- 4. M4 et M7 (T0.13-b)
def _appels_a_taxonomie(fichier: Path) -> set[str]:
    """Noms `taxonomie.<fonction>` appelés dans la source (lue par AST, rien n'est exécuté)."""
    arbre = ast.parse(fichier.read_text(encoding="utf-8"), filename=str(fichier))
    return {
        noeud.func.attr for noeud in ast.walk(arbre)
        if isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Attribute)
        and isinstance(noeud.func.value, ast.Name) and noeud.func.value.id == "taxonomie"
    }


@pytest.mark.parametrize("fichier", [
    SRC_M4 / "contrats.py",
    SRC_M4 / "cedule.py",
    SRC_M7 / "workflows" / "chantier_social.py",
])
def test_m4_et_m7_valident_service_par_la_taxonomie_du_socle(fichier):
    assert "valider_service" in _appels_a_taxonomie(fichier), fichier


def test_le_wct_de_m4_declare_type_travaux_et_service_comme_cles_additives_du_catalogue():
    """Règle documentée (docs/architecture/TAXONOMIE.md) : v1 -> `type_travaux`, v2 -> `service`, jamais l'un
    déduit de l'autre. Le catalogue du socle les déclare optionnelles toutes les deux ; le contrat de M4
    porte les mêmes (sauf `ville`, jamais émise : la ville n'est connue de M4 que tokenisée) ; les treize clés
    requises ne bougent pas."""
    schema = evenements.schema("m4.travaux_termines")
    optionnelles_catalogue = set(schema["properties"]) - set(schema["required"])
    assert {"type_travaux", "service"} <= optionnelles_catalogue
    assert set(_constante(SRC_M4 / "outbox.py", "CHAMPS_WCT_OPTIONNELS")) == optionnelles_catalogue - {"ville"}
    assert len(schema["required"]) == 13 and not {"type_travaux", "service"} & set(schema["required"])
    assert set(_constante(SRC_M4 / "outbox.py", "CHAMPS_WCT")) == set(schema["required"])
