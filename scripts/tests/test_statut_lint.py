import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[1]
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import statut_lint  # noqa: E402

import yaml


# ----------------------------------------------------------------
# helper de construction de faux dépôt
# ----------------------------------------------------------------
def _faux_depot(tmp_path, modules):
    """
    Construit une arborescence minimale sous *tmp_path* à partir de la liste de
    *modules* (chaque dict contient au moins ``nom`` et ``statut_registre``).

    Retourne ``(chemin_registre, racine_modules)``.
    """
    reg_dir = tmp_path / "registries"
    reg_dir.mkdir(parents=True, exist_ok=True)
    registre_path = reg_dir / "modules.yaml"

    modules_root = tmp_path / "Modules M"
    modules_root.mkdir(parents=True, exist_ok=True)

    # Écrire le registre YAML
    registre_data = {
        "modules": [
            {"name": m["nom"], "statut": m["statut_registre"]} for m in modules
        ]
    }
    with open(registre_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(registre_data, f, allow_unicode=True)

    # Construire chaque module
    for m in modules:
        nom = m["nom"]
        mod_dir = modules_root / nom
        mod_dir.mkdir(parents=True, exist_ok=True)

        # README.md
        sr = m.get("statut_readme", m["statut_registre"])
        if sr != "ABSENT":
            readme_path = mod_dir / "README.md"
            lines = [f"# {nom}", ""]
            if sr != "SANS_LIGNE":
                lines.append(f"Statut: {sr} (texte libre).")
            lines.append("")
            readme_path.write_text("\n".join(lines), encoding="utf-8")
        # else : pas de README du tout

        # Dossiers & fichiers source / test / plats
        ms = m.get("modules_source", 0)
        ft = m.get("fichiers_test", 0)
        fp = m.get("fichiers_plats", 0)

        if ms > 0 or ft > 0 or fp > 0 or True:  # toujours créer src/pkg/__init__.py
            pkg_dir = mod_dir / "src" / "pkg"
            pkg_dir.mkdir(parents=True, exist_ok=True)
            (pkg_dir / "__init__.py").write_text("# init\n", encoding="utf-8")
            for i in range(ms):
                (pkg_dir / f"mod_{i}.py").write_text(f"# module {i}\n", encoding="utf-8")

        if ft > 0:
            test_dir = mod_dir / "tests"
            test_dir.mkdir(parents=True, exist_ok=True)
            for i in range(ft):
                (test_dir / f"test_{i}.py").write_text(f"# test {i}\n", encoding="utf-8")

        if fp > 0:
            src_dir = mod_dir / "src"
            src_dir.mkdir(parents=True, exist_ok=True)
            for i in range(fp):
                (src_dir / f"plat_{i}.py").write_text(f"# plat {i}\n", encoding="utf-8")

    return registre_path, modules_root


# ================================================================
# Tests exigés
# ================================================================

def test_conforme(tmp_path):
    modules = [
        {"nom": "m1", "statut_registre": "STUB", "statut_readme": "STUB",
         "modules_source": 0, "fichiers_test": 0},
        {"nom": "m2", "statut_registre": "PARTIAL", "statut_readme": "PARTIAL",
         "modules_source": 2, "fichiers_test": 1},
    ]
    reg, root = _faux_depot(tmp_path, modules)
    anomalies = statut_lint.verifier(reg, root)
    assert anomalies == []


# Test 2
def test_stub_avec_code_et_tests(tmp_path):
    modules = [
        {"nom": "fautif", "statut_registre": "STUB", "statut_readme": "STUB",
         "modules_source": 12, "fichiers_test": 13},
    ]
    reg, root = _faux_depot(tmp_path, modules)
    anomalies = statut_lint.verifier(reg, root)
    assert len(anomalies) == 1
    msg = anomalies[0]
    assert "fautif" in msg
    assert "STUB" in msg
    assert "12" in msg
    assert "13" in msg


# Test 3a : PARTIAL à 0 module
def test_partial_sans_module(tmp_path):
    modules = [
        {"nom": "vide", "statut_registre": "PARTIAL", "statut_readme": "PARTIAL",
         "modules_source": 0, "fichiers_test": 1},
    ]
    reg, root = _faux_depot(tmp_path, modules)
    anomalies = statut_lint.verifier(reg, root)
    assert len(anomalies) == 1
    assert "vide" in anomalies[0]


# Test 3b : PARTIAL avec modules mais sans test
def test_partial_sans_test(tmp_path):
    modules = [
        {"nom": "sans_test", "statut_registre": "PARTIAL", "statut_readme": "PARTIAL",
         "modules_source": 2, "fichiers_test": 0},
    ]
    reg, root = _faux_depot(tmp_path, modules)
    anomalies = statut_lint.verifier(reg, root)
    assert len(anomalies) == 1
    assert "sans_test" in anomalies[0]


# Test 4 : statut inconnu
def test_statut_inconnu(tmp_path):
    modules = [
        {"nom": "bizarre", "statut_registre": "EN_COURS", "statut_readme": "EN_COURS"},
    ]
    reg, root = _faux_depot(tmp_path, modules)
    anomalies = statut_lint.verifier(reg, root)
    assert len(anomalies) == 1
    assert "EN_COURS" in anomalies[0]


# Test 5 : .py à plat sous src/
def test_fichier_plat_sous_src(tmp_path):
    modules = [
        {"nom": "plat", "statut_registre": "PARTIAL", "statut_readme": "PARTIAL",
         "modules_source": 2, "fichiers_test": 2, "fichiers_plats": 1},
    ]
    reg, root = _faux_depot(tmp_path, modules)
    anomalies = statut_lint.verifier(reg, root)
    assert len(anomalies) == 1
    assert "plat" in anomalies[0]


# Test 6 : README désaligné (deux sens)
@pytest.mark.parametrize("reg_statut, readme_statut", [
    ("PARTIAL", "STUB"),
    ("STUB", "PARTIAL"),
])
def test_readme_desaligne(tmp_path, reg_statut, readme_statut):
    modules = [
        # La réalité du disque suit le statut du REGISTRE (source de vérité), pour
        # que SEULE l'anomalie de désalignement du README se déclenche. Un décor
        # fixe échouerait dans un sens ou dans l'autre : avec du code sous un
        # registre STUB, « STUB mais porte du code » s'ajoute ; sans code sous un
        # registre PARTIAL, « PARTIAL sans code » s'ajoute (les deux mesurés).
        {"nom": "desynchro", "statut_registre": reg_statut, "statut_readme": readme_statut,
         "modules_source": 0 if reg_statut == "STUB" else 2,
         "fichiers_test": 0 if reg_statut == "STUB" else 1},
    ]
    reg, root = _faux_depot(tmp_path, modules)
    anomalies = statut_lint.verifier(reg, root)
    assert len(anomalies) == 1
    assert "desynchro" in anomalies[0]


# Test 7a : README absent
def test_readme_absent(tmp_path):
    modules = [
        # code et tests PRÉSENTS : sinon « PARTIAL sans code » s'ajoute et le test
        # n'isole plus l'anomalie visée (mesuré : 2 anomalies au lieu d'1).
        {"nom": "sans_readme", "statut_registre": "PARTIAL", "statut_readme": "ABSENT",
         "modules_source": 2, "fichiers_test": 1},
    ]
    reg, root = _faux_depot(tmp_path, modules)
    anomalies = statut_lint.verifier(reg, root)
    assert len(anomalies) == 1
    assert "sans_readme" in anomalies[0]
    # Épingler le DIAGNOSTIC, pas seulement le compte : « README absent » et
    # « README désaligné » sont deux causes distinctes, et la branche dédiée à
    # l'absence est redondante avec la comparaison (None != statut) tant qu'on ne
    # lit pas le message — sa suppression passait inaperçue (mutation mesurée).
    assert "README" in anomalies[0]
    bas = anomalies[0].lower()
    assert "absent" in bas or "introuvable" in bas, (
        f"le diagnostic doit nommer l'ABSENCE du README, pas un désalignement : {anomalies[0]}"
    )


# Test 7b : README sans ligne Statut
def test_readme_sans_ligne_statut(tmp_path):
    modules = [
        {"nom": "sans_ligne", "statut_registre": "PARTIAL", "statut_readme": "SANS_LIGNE",
         "modules_source": 2, "fichiers_test": 1},
    ]
    reg, root = _faux_depot(tmp_path, modules)
    anomalies = statut_lint.verifier(reg, root)
    assert len(anomalies) == 1
    assert "sans_ligne" in anomalies[0]


# Test 8a : module sur disque absent du registre
def test_module_disque_absent_du_registre(tmp_path):
    # on crée un module normal + un dossier supplémentaire sans entrée registre
    modules = [
        {"nom": "present", "statut_registre": "STUB"},
    ]
    reg, root = _faux_depot(tmp_path, modules)
    # ajout manuel d'un dossier clandestin
    cland = root / "hors_registre"
    cland.mkdir()
    (cland / "src").mkdir()
    (cland / "src" / "pkg").mkdir()
    (cland / "src" / "pkg" / "__init__.py").touch()
    anomalies = statut_lint.verifier(reg, root)
    assert any("hors_registre" in a for a in anomalies)


# Test 8b : entrée registre sans dossier
def test_entree_registre_sans_dossier(tmp_path):
    modules = [
        {"nom": "fantome", "statut_registre": "STUB"},
        {"nom": "normal", "statut_registre": "STUB"},
    ]
    reg, root = _faux_depot(tmp_path, modules)
    # supprimer le dossier du module "fantome"
    import shutil
    shutil.rmtree(root / "fantome")
    anomalies = statut_lint.verifier(reg, root)
    assert any("fantome" in a for a in anomalies)


# Test 9 : mesurer_module sur dossier vide
def test_mesurer_module_dossier_vide(tmp_path):
    vide = tmp_path / "vide"
    vide.mkdir()
    res = statut_lint.mesurer_module(vide)
    assert res == {"paquets": 0, "modules_source": 0, "fichiers_plats": 0, "fichiers_test": 0}


# Test 10 : lire_statut_readme
def test_lire_statut_readme(tmp_path):
    # Cas normal
    d = tmp_path / "avec_statut"
    d.mkdir()
    (d / "README.md").write_text("# Titre\n\nStatut: PARTIAL (texte).\n")
    statut = statut_lint.lire_statut_readme(d)
    assert statut == "PARTIAL"

    # Cas sans ligne Statut
    d2 = tmp_path / "sans_statut"
    d2.mkdir()
    (d2 / "README.md").write_text("# Titre\n\nPas de statut.\n")
    statut2 = statut_lint.lire_statut_readme(d2)
    assert statut2 is None

    # Ligne indentée
    d3 = tmp_path / "indente"
    d3.mkdir()
    (d3 / "README.md").write_text("# Titre\n  Statut: STUB\n")
    statut3 = statut_lint.lire_statut_readme(d3)
    assert statut3 is None


# Test 11 : plusieurs anomalies distinctes
def test_plusieurs_anomalies(tmp_path):
    modules = [
        {"nom": "a_stub_code", "statut_registre": "STUB", "statut_readme": "STUB",
         "modules_source": 1, "fichiers_test": 0},
        {"nom": "b_partial_no_test", "statut_registre": "PARTIAL", "statut_readme": "PARTIAL",
         "modules_source": 2, "fichiers_test": 0},
        {"nom": "c_inconnu", "statut_registre": "INCONNU", "statut_readme": "INCONNU"},
    ]
    reg, root = _faux_depot(tmp_path, modules)
    anomalies = statut_lint.verifier(reg, root)
    assert len(anomalies) == 3
    # Chaque anomalie doit nommer son module
    noms = {"a_stub_code", "b_partial_no_test", "c_inconnu"}
    for a in anomalies:
        found = any(n in a for n in noms)
        assert found, f"L'anomalie '{a}' ne nomme aucun des modules fautifs"


# Test 12 : main() sur le VRAI dépôt (doit être VERT)
def test_main_sur_vrai_depot_vert(monkeypatch, capsys):
    # se placer à la racine du projet (scripts/.. = racine)
    # argv EXPLICITE et vide : les chemins par défaut viennent de l'emplacement du
    # script. main() RETOURNE son code, il ne lève pas SystemExit (seul le bloc
    # __main__ appelle sys.exit).
    code = statut_lint.main([])
    out = capsys.readouterr().out
    assert code == 0, f"le VRAI dépôt doit être conforme : {out}"
    assert "STATUT_LINT: VERT" in out


# Test 13 : main() sur faux dépôt fautif → ROUGE
def test_main_sur_faux_depot_rouge(monkeypatch, capsys, tmp_path):
    modules = [
        {"nom": "coupable", "statut_registre": "STUB", "statut_readme": "STUB",
         "modules_source": 3, "fichiers_test": 0},
    ]
    reg, root = _faux_depot(tmp_path, modules)
    code = statut_lint.main([str(reg), str(root)])
    out = capsys.readouterr().out
    assert code == 1
    assert "STATUT_LINT: ROUGE" in out
    assert "1 anomalie" in out  # ou "1 anomalies" selon la grammaire, on vérifie la présence

@pytest.mark.parametrize("statut_avec_code", ["PILOTE", "PARTIAL", "COMPLET"])
def test_chaque_statut_avec_code_accepte_du_code(tmp_path, statut_avec_code):
    """Les TROIS statuts-avec-code doivent accepter un module qui porte du code.
    PILOTE n'était couvert par aucun test : le déplacer vers les statuts VIDES ne
    cassait rien (mutation mesurée non détectée), alors que cela aurait rendu tout
    module pilote non conforme dès sa première ligne de code."""
    reg, root = _faux_depot(tmp_path, [
        {"nom": "avec_code", "statut_registre": statut_avec_code,
         "statut_readme": statut_avec_code, "modules_source": 2, "fichiers_test": 1},
    ])
    assert statut_lint.verifier(reg, root) == []
    assert statut_avec_code in statut_lint.STATUTS_AVEC_CODE
    assert statut_avec_code not in statut_lint.STATUTS_VIDES


def test_module_sur_disque_absent_du_registre(tmp_path):
    """Bijection : un dossier de module non déclaré au registre est une anomalie."""
    reg, root = _faux_depot(tmp_path, [
        {"nom": "declare", "statut_registre": "STUB", "statut_readme": "STUB"},
    ])
    (root / "M99-clandestin").mkdir()
    anomalies = statut_lint.verifier(reg, root)
    assert len(anomalies) == 1
    assert "M99-clandestin" in anomalies[0]
    assert "registre" in anomalies[0].lower()


def test_entree_de_registre_sans_dossier(tmp_path):
    """Bijection, sens inverse : une entrée de registre sans dossier est une anomalie."""
    reg, root = _faux_depot(tmp_path, [
        {"nom": "declare", "statut_registre": "STUB", "statut_readme": "STUB"},
    ])
    import shutil
    shutil.rmtree(root / "declare")
    anomalies = statut_lint.verifier(reg, root)
    assert anomalies, "une entrée de registre sans dossier doit être signalée"
    assert any("declare" in a for a in anomalies)

def test_statut_cadre_exige_une_sentinelle_sans_code(tmp_path):
    """CADRE encode en règle une pratique prouvée : le cadrage et la sentinelle
    précèdent la première story (leçon M1 puis M4 — une CI branchée après coup
    laisse passer des stories non gardées). Sans ce statut, un module cadré
    devait mentir en STUB ou faire relâcher la règle : un statut manquant force
    le mensonge."""
    reg, root = _faux_depot(tmp_path, [
        {"nom": "cadre_ok", "statut_registre": "CADRE", "statut_readme": "CADRE",
         "modules_source": 0, "fichiers_test": 1},
    ])
    assert statut_lint.verifier(reg, root) == []


def test_statut_cadre_sans_aucun_test_est_refuse(tmp_path):
    """Un CADRE sans sentinelle n'a pas de sens : c'est un STUB qui se prétend cadré."""
    reg, root = _faux_depot(tmp_path, [
        {"nom": "cadre_nu", "statut_registre": "CADRE", "statut_readme": "CADRE",
         "modules_source": 0, "fichiers_test": 0},
    ])
    anomalies = statut_lint.verifier(reg, root)
    assert len(anomalies) == 1
    assert "CADRE" in anomalies[0]
    assert "sentinelle" in anomalies[0].lower() or "test" in anomalies[0].lower()


def test_statut_cadre_portant_du_code_est_refuse(tmp_path):
    """Dès qu'une story livre du code, le registre doit passer à PARTIAL."""
    reg, root = _faux_depot(tmp_path, [
        {"nom": "cadre_code", "statut_registre": "CADRE", "statut_readme": "CADRE",
         "modules_source": 3, "fichiers_test": 2},
    ])
    anomalies = statut_lint.verifier(reg, root)
    assert len(anomalies) == 1
    assert "PARTIAL" in anomalies[0]

