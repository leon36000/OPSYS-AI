"""Garde de l'interconnexion des départements : chaque événement du catalogue a un consommateur RÉEL ou une
justification
écrite (données), chaque consommateur déclaré a son handler, aucun handler n'est orphelin.

Lit les vrais manifestes, les vraies `consommateurs()` et le vrai catalogue. La logique de l'audit est aussi prouvée
sur des
départements fictifs (un écart de chaque famille doit être vu : un audit qui ne voit rien ne prouve rien).
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from opsys.departements import charger_departements
from opsys.evenements import interconnexion as ic
from opsys.evenements.schemas import types_connus

FICTIF = True
RACINE = Path(__file__).resolve().parents[1]
SCRIPT = RACINE / "scripts" / "docs" / "interconnexion_evenements.py"
PAGE = RACINE / "docs" / "architecture" / "INTERCONNEXION.md"


@pytest.fixture(scope="module")
def analyse():
    return ic.analyser(charger_departements(RACINE / "departments"))


def test_aucun_ecart_bloquant(analyse):
    assert ic.problemes(analyse) == []


def test_chaque_type_du_catalogue_a_un_consommateur_reel_ou_une_justification(analyse):
    justifs = ic.lire_justifications()
    for ligne in analyse["matrice"]:
        assert ligne["consommateurs"] or ligne["type"] in justifs, (
            f"{ligne['type']} : ni consommateur réel ni justification (evenements-sans-consommateur.json)"
        )


def test_aucune_justification_perimee_ni_orpheline(analyse):
    """Une fiche « sans consommateur » pour un type qui en a un, ou pour un type absent du catalogue, ment."""
    justifs = ic.lire_justifications()
    consommes = {ligne["type"] for ligne in analyse["matrice"] if ligne["consommateurs"]}
    assert not set(justifs) & consommes, f"fiches périmées : {sorted(set(justifs) & consommes)}"
    assert set(justifs) <= types_connus()


def test_chaque_consommateur_declare_a_son_handler_et_inversement(analyse):
    assert analyse["declares_sans_handler"] == []
    assert analyse["handlers_sans_declaration"] == []
    assert analyse["modules_illisibles"] == []


def test_les_justifications_sont_des_donnees_bien_formees():
    justifs = ic.lire_justifications()
    assert ic.justifications_invalides(justifs, types_connus()) == []
    for type_evenement, fiche in justifs.items():
        assert fiche["revue_le"] < fiche["a_revoir_avant"], type_evenement


def test_la_matrice_de_la_page_est_a_jour():
    spec = importlib.util.spec_from_file_location("interconnexion_evenements_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules["interconnexion_evenements_script"] = module
    spec.loader.exec_module(module)
    texte = PAGE.read_text(encoding="utf-8")
    assert module.remplacer(texte) == texte, "python scripts/docs/interconnexion_evenements.py --ecrire"


def test_le_script_d_audit_sort_a_zero():
    resultat = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--audit"],
        capture_output=True,
        text=True,
        timeout=120,
        env={"PATH": "/usr/bin:/bin", "HOME": str(RACINE)},
    )
    assert resultat.returncode == 0, resultat.stderr[-500:]
    assert "cohérente" in resultat.stdout


# ------------------------------------------------------------------------------------------------ l'audit voit-il ?
def _handler_factice(charge):
    """Un handler qui n'est pas inerte (il référence `dict`) : l'audit refuse les `lambda charge: charge`."""
    return dict(charge)


def _dep(identifiant, numero, publie=(), consomme=(), fonctions=(), racine=None):
    return SimpleNamespace(
        id=identifiant,
        numero=numero,
        evenements_publie=tuple(publie),
        evenements_consomme=tuple(consomme),
        racine=racine,
        charger_consommateurs=lambda: dict.fromkeys(fonctions, _handler_factice),
    )


@pytest.fixture
def monde_fictif(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "producteur.py").write_text('TYPE = "m1.lead_qualifie"\nAUTRE = "m1.courriel_recu"\n')
    return tmp_path


def test_un_type_sans_consommateur_et_sans_fiche_est_vu(monde_fictif):
    deps = {"m01-x": _dep("m01-x", 1, publie=["m1.lead_qualifie"], racine=monde_fictif)}
    analyse = ic.analyser(deps, {})
    assert "m1.lead_qualifie" in analyse["types_sans_consommateur_non_justifies"]
    assert any("m1.lead_qualifie" in p for p in ic.problemes(analyse))


def test_une_fiche_ecrite_leve_le_type_sans_consommateur(monde_fictif):
    deps = {"m01-x": _dep("m01-x", 1, publie=["m1.lead_qualifie"], racine=monde_fictif)}
    fiche = {"m1.lead_qualifie": {"raison": "x" * 60, "revue_le": "2026-11-01", "a_revoir_avant": "2027-02-01"}}
    analyse = ic.analyser(deps, fiche)
    assert "m1.lead_qualifie" not in analyse["types_sans_consommateur_non_justifies"]


def test_une_fiche_pour_un_type_consomme_est_perimee(monde_fictif):
    deps = {
        "m01-x": _dep("m01-x", 1, publie=["m1.lead_qualifie"], racine=monde_fictif),
        "m02-y": _dep("m02-y", 2, consomme=["m1.lead_qualifie"], fonctions=["m1.lead_qualifie"], racine=monde_fictif),
    }
    fiche = {"m1.lead_qualifie": {"raison": "x" * 60, "revue_le": "2026-11-01", "a_revoir_avant": "2027-02-01"}}
    assert ic.analyser(deps, fiche)["justifications_perimees"] == ["m1.lead_qualifie"]


def test_un_consommateur_declare_sans_handler_est_vu(monde_fictif):
    deps = {
        "m01-x": _dep("m01-x", 1, publie=["m1.lead_qualifie"], racine=monde_fictif),
        "m02-y": _dep("m02-y", 2, consomme=["m1.lead_qualifie"], fonctions=[], racine=monde_fictif),
    }
    analyse = ic.analyser(deps, {})
    assert analyse["declares_sans_handler"] == [{"departement": "m02-y", "type": "m1.lead_qualifie"}]
    assert "m1.lead_qualifie" in analyse["types_sans_consommateur"]  # déclaré n'est pas réel


def test_un_handler_sans_declaration_est_vu(monde_fictif):
    deps = {
        "m01-x": _dep("m01-x", 1, publie=["m1.lead_qualifie"], racine=monde_fictif),
        "m02-y": _dep("m02-y", 2, consomme=[], fonctions=["m1.lead_qualifie"], racine=monde_fictif),
    }
    analyse = ic.analyser(deps, {})
    assert analyse["handlers_sans_declaration"] == [{"departement": "m02-y", "type": "m1.lead_qualifie"}]
    assert "m1.lead_qualifie" in analyse["types_sans_consommateur"]  # le répartiteur ne l'appellerait jamais


def test_un_type_consomme_que_personne_ne_publie_est_vu(monde_fictif):
    deps = {
        "m02-y": _dep("m02-y", 2, consomme=["m1.lead_qualifie"], fonctions=["m1.lead_qualifie"], racine=monde_fictif)
    }
    assert ic.analyser(deps, {})["types_sans_producteur"] == ["m1.lead_qualifie"]


def test_un_producteur_dont_le_code_ne_nomme_pas_le_type_est_vu(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "rien.py").write_text("X = 1\n")
    # Un type que seul le code de son département nomme : le socle ne le cite pas, donc l'absence est bien vue.
    deps = {"m03-x": _dep("m03-x", 3, publie=["m3.mesure_vision_validee"], racine=tmp_path)}
    assert ic.analyser(deps, {})["producteurs_sans_trace"] == [
        {"departement": "m03-x", "type": "m3.mesure_vision_validee"}
    ]


@pytest.mark.parametrize(
    "fiche",
    [
        {"raison": "trop court", "revue_le": "2026-11-01", "a_revoir_avant": "2027-02-01"},
        {"raison": "x" * 60, "revue_le": "pas une date", "a_revoir_avant": "2027-02-01"},
        {"raison": "x" * 60, "revue_le": "2026-11-01", "a_revoir_avant": "2026-10-01"},
        {"raison": "x" * 60, "revue_le": "2026-11-01"},
    ],
)
def test_une_fiche_mal_formee_est_refusee(fiche):
    assert ic.justifications_invalides({"m1.lead_qualifie": fiche}, types_connus()) != []


def test_une_fiche_d_un_type_inconnu_est_refusee():
    fiche = {"raison": "x" * 60, "revue_le": "2026-11-01", "a_revoir_avant": "2027-02-01"}
    assert ic.justifications_invalides({"m99.inconnu": fiche}, types_connus()) != []


def test_le_fichier_de_justifications_refuse_un_schema_inconnu(tmp_path):
    fichier = tmp_path / "j.json"
    fichier.write_text(json.dumps({"schema": "autre", "types": {}}))
    with pytest.raises(ValueError):
        ic.lire_justifications(fichier)


# ------------------------------------------------------------------------------------------------ lectures croisées
@pytest.fixture(scope="module")
def lectures(analyse):
    return ic.auditer_lectures_croisees(charger_departements(RACINE / "departments"))


def test_les_lectures_croisees_declarees_existent_et_aucune_autre_n_existe(lectures):
    assert ic.problemes_lectures(lectures) == []
    assert lectures["ports_introuvables"] == [] and lectures["directes_non_declarees"] == []
    assert lectures["directes_disparues"] == [] and lectures["imports_non_declares"] == []


def test_aucune_lecture_n_elargit_dependances_ni_les_droits_d_appareil(lectures):
    """Le manifeste ne s'élargit pas pour couvrir une lecture : `dependances` ouvre aussi les bases de connaissances."""
    informatives = set(lectures["sans_dependance"])
    assert "m09-strategic-intelligence lit m01-front-office" in informatives  # port à liste blanche, pas `dependances`
    deps = charger_departements(RACINE / "departments")
    assert deps["m01-front-office"].dependances == ()
    assert set(deps["m09-strategic-intelligence"].dependances) == {"m08-analytics", "m10-memoire"}


def _dep_lecteur(tmp_path, source, dependances=()):
    (tmp_path / "src").mkdir(parents=True, exist_ok=True)
    (tmp_path / "src" / "lecteur.py").write_text(source)
    return SimpleNamespace(
        id="m02-x",
        numero=2,
        racine=tmp_path,
        module_outils="m2_x.outils",
        dependances=tuple(dependances),
        charger_outils=lambda: (),
    )


def _dep_cible(tmp_path_cible):
    (tmp_path_cible / "src").mkdir(parents=True, exist_ok=True)
    return SimpleNamespace(
        id="m03-y",
        numero=3,
        racine=tmp_path_cible,
        module_outils="m3_y.outils",
        dependances=(),
        charger_outils=lambda: (),
    )


def test_une_lecture_directe_non_declaree_est_vue(tmp_path):
    lecteur = _dep_lecteur(tmp_path / "a", 'for m in stockage.maillons("m03-y", "principal"):\n    pass\n')
    cible = _dep_cible(tmp_path / "b")
    audit = ic.auditer_lectures_croisees({"m02-x": lecteur, "m03-y": cible}, [])
    assert ("m02-x", "m03-y") in [tuple(x) for x in audit["directes_non_declarees"]]
    assert ic.problemes_lectures(audit)


@pytest.mark.parametrize(
    "ligne",
    [
        'where(REGISTRES.c.departement == "m03-y")',
        'copies = _copies(cnx, "m03-y", "reg")',
        'dept = "m03-y"',
        '_DEPARTEMENT_PRIX = "m03-y"',
    ],
)
def test_les_autres_formes_de_lecture_directe_sont_vues(tmp_path, ligne):
    lecteur = _dep_lecteur(tmp_path / "a", ligne + "\n")
    audit = ic.auditer_lectures_croisees({"m02-x": lecteur, "m03-y": _dep_cible(tmp_path / "b")}, [])
    assert ("m02-x", "m03-y") in [tuple(x) for x in audit["directes_non_declarees"]], ligne


def test_une_lecture_directe_declaree_est_acceptee_et_une_disparue_est_vue(tmp_path):
    lecteur = _dep_lecteur(tmp_path / "a", 'x = stockage.maillons("m03-y", "principal")\n')
    declaree = [{"lecteur": "m02-x", "source": "m03-y", "voie": "registre", "registres": ["principal"], "raison": "t"}]
    audit = ic.auditer_lectures_croisees({"m02-x": lecteur, "m03-y": _dep_cible(tmp_path / "b")}, declaree)
    assert audit["directes_non_declarees"] == [] and audit["sans_dependance"] == ["m02-x lit m03-y"]
    sans_code = _dep_lecteur(tmp_path / "c", "x = 1\n")
    audit = ic.auditer_lectures_croisees({"m02-x": sans_code, "m03-y": _dep_cible(tmp_path / "d")}, declaree)
    assert audit["directes_disparues"] == [("m02-x", "m03-y")]


def test_un_import_du_code_d_un_autre_departement_non_declare_est_vu(tmp_path):
    lecteur = _dep_lecteur(tmp_path / "a", "from m3_y import registre\n")
    audit = ic.auditer_lectures_croisees({"m02-x": lecteur, "m03-y": _dep_cible(tmp_path / "b")}, [])
    assert audit["imports_non_declares"] == [("m02-x", "m03-y")]


def test_un_port_dont_l_outil_n_existe_pas_ou_n_est_pas_une_lecture_est_vu(tmp_path):
    from opsys.outils import Autonomie, Outil

    ecriture = Outil(
        nom="m3_ecrire",
        description="d",
        parametres={"type": "object", "properties": {}},
        fonction=lambda: {},
        autonomie=Autonomie.T1,
    )
    cible = SimpleNamespace(
        id="m03-y",
        numero=3,
        racine=tmp_path / "b",
        module_outils="m3_y.outils",
        dependances=(),
        charger_outils=lambda: (ecriture,),
    )
    (tmp_path / "b" / "src").mkdir(parents=True, exist_ok=True)
    lecteur = _dep_lecteur(tmp_path / "a", "x = 1\n")
    declaree = [{"lecteur": "m02-x", "source": "m03-y", "voie": "port:p", "outils": ["m3_ecrire", "m3_absent"]}]
    audit = ic.auditer_lectures_croisees({"m02-x": lecteur, "m03-y": cible}, declaree)
    assert any("m3_absent introuvable" in p for p in audit["ports_introuvables"])
    assert any("m3_ecrire n'est pas T0/N0" in p for p in audit["ports_introuvables"])
