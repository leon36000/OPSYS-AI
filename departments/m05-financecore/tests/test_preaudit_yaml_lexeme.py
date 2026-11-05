from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import m5_financecore.outils as m5_outils
import pytest
import yaml
from m5_financecore import controleur_preaudit, outils_rapports

from opsys.reglages import lecture as reglages_lecture

SEUIL = "seuil_transaction_hors_norme_cad"
DECLARATION = """\
schema: opsys.departement/v1
id: m05-financecore
code: M5
reglages:
  - cle: m5.seuil_transaction_hors_norme_cad
    libelle: Seuil transaction fictif
    chemin: configuration.preaudit.seuil_transaction_hors_norme_cad
    type: decimal
    unite: "$ CAD"
    min: 1
    max: 1000000000
    niveau: N3
    debloque: Seuil fictif de pré-audit.
"""


def _lire(tmp_path, monkeypatch, texte):
    manifeste = tmp_path / "department.yaml"
    manifeste.write_text(texte, encoding="utf-8")
    monkeypatch.setattr(m5_outils, "_MANIFESTE", manifeste)
    return outils_rapports._preaudit_declare()


@pytest.mark.parametrize(
    "seuil_yaml",
    (
        '100.0100000000000005',
        '"100.0100000000000005"',
        "&declared 100.0100000000000005",
    ),
)
def test_lexeme_decimal_est_preserve_et_autres_champs_safe_load_inchanges(tmp_path, monkeypatch, seuil_yaml):
    prefixe = ""
    expression = seuil_yaml
    if seuil_yaml.startswith("&declared"):
        prefixe = "seuil_ancre: " + seuil_yaml + "\n"
        expression = "*declared"
    texte = (
        prefixe
        + "configuration:\n  preaudit:\n"
        + f"    {SEUIL}: {expression}\n"
        + "    jours_fenetre_doublon: 3\n"
    )

    declare = _lire(tmp_path, monkeypatch, texte)
    seuils, problemes = controleur_preaudit.seuils_depuis(declare)

    assert seuils["transaction_hors_norme_cad"] == "100.0100000000000005"
    assert seuils["jours_fenetre_doublon"] == 3
    assert problemes == []
    assert Decimal("100.01") < Decimal(seuils["transaction_hors_norme_cad"])


@pytest.mark.parametrize(
    ("scalaire", "attendu"),
    (("1.0e-999999999", "1.0E-999999999"), (".nan", None), (".inf", None), ("-.inf", None)),
)
def test_float_yaml_extreme_ou_special_reste_exact_ou_est_refuse_nomme(tmp_path, monkeypatch, scalaire, attendu):
    declare = _lire(
        tmp_path,
        monkeypatch,
        f"configuration:\n  preaudit:\n    {SEUIL}: {scalaire}\n",
    )

    seuils, problemes = controleur_preaudit.seuils_depuis(declare)

    assert seuils["transaction_hors_norme_cad"] == attendu
    if attendu is None:
        assert problemes and SEUIL in problemes[0]
    else:
        assert problemes == []


@pytest.mark.parametrize(
    "configuration",
    (
        f"  preaudit:\n    {SEUIL}: 100.01\n    {SEUIL}: 100.0100000000000005\n",
        "  preaudit:\n    <<: *seuils\n    jours_fenetre_doublon: 3\n",
        f"  preaudit:\n    {SEUIL}: 100.01\n  preaudit:\n    {SEUIL}: 100.02\n",
    ),
)
def test_seuil_ambigu_ou_herite_est_refuse_sans_interpreter_une_valeur(tmp_path, monkeypatch, configuration):
    ancre = "seuils: &seuils\n  seuil_transaction_hors_norme_cad: 100.0100000000000005\n" if "<<:" in configuration else ""
    declare = _lire(tmp_path, monkeypatch, ancre + "configuration:\n" + configuration)

    seuils, problemes = controleur_preaudit.seuils_depuis(declare)

    assert seuils["transaction_hors_norme_cad"] is None
    assert problemes and SEUIL in problemes[0]


def test_doublon_d_ancetre_sans_seuil_ne_cree_pas_un_seuil_invalide(tmp_path, monkeypatch):
    texte = "configuration:\n  rapports: {}\nconfiguration:\n  rapports: {}\n"

    declare = _lire(tmp_path, monkeypatch, texte)
    seuils, problemes = controleur_preaudit.seuils_depuis(declare)

    assert seuils["transaction_hors_norme_cad"] is None
    assert problemes == []


@pytest.mark.parametrize(
    "configuration_key",
    ("!!str configuration", "!!null configuration", "!custom configuration"),
)
def test_cle_configuration_explicitement_taggee_ne_change_pas_la_resolution_yaml(
    tmp_path, monkeypatch, configuration_key
):
    texte = f"{configuration_key}:\n  preaudit:\n    {SEUIL}: 100.0100000000000005\n"

    declare = _lire(tmp_path, monkeypatch, texte)
    seuils, problemes = controleur_preaudit.seuils_depuis(declare)

    if configuration_key == "!!str configuration":
        assert seuils["transaction_hors_norme_cad"] == "100.0100000000000005"
        assert problemes == []
    else:
        # A null-tagged key is not the string key "configuration"; an unknown tag makes the manifest unreadable.
        # Neither may make the scalar node look as if it were under the normal path.
        assert seuils["transaction_hors_norme_cad"] is None
        assert bool(problemes) is (configuration_key == "!custom configuration")
        if problemes:
            assert SEUIL in problemes[0]


def test_doublons_sous_alias_et_sources_de_merge_ne_sont_pas_resolus_en_une_valeur(tmp_path, monkeypatch):
    cas = (
        "preaudit_template: &preaudit\n"
        f"  {SEUIL}: 100.01\n"
        f"  {SEUIL}: 100.0100000000000005\n"
        "configuration:\n  preaudit: *preaudit\n",
        "premier: &premier\n"
        f"  {SEUIL}: 100.01\n"
        "second: &second\n"
        f"  {SEUIL}: 100.02\n"
        "configuration:\n  preaudit:\n    <<: [*premier, *second]\n",
    )
    for texte in cas:
        declare = _lire(tmp_path, monkeypatch, texte)
        seuils, problemes = controleur_preaudit.seuils_depuis(declare)
        assert seuils["transaction_hors_norme_cad"] is None
        assert problemes and SEUIL in problemes[0]


def test_seuil_direct_explicite_gagne_sur_merge_et_lexeme_reste_exact(tmp_path, monkeypatch):
    texte = (
        "defauts: &defauts\n"
        f"  {SEUIL}: 100.01\n"
        "configuration:\n  preaudit:\n"
        "    <<: *defauts\n"
        f"    {SEUIL}: 100.0100000000000005\n"
    )

    declare = _lire(tmp_path, monkeypatch, texte)
    seuils, problemes = controleur_preaudit.seuils_depuis(declare)

    assert seuils["transaction_hors_norme_cad"] == "100.0100000000000005"
    assert problemes == []


@pytest.mark.parametrize(
    ("scalaire", "attendu", "refuse"),
    (("1_000.01", "1000.01", False), ("1:20.0", None, True), ("0x10", "16.00", False), ("012", "10.00", False)),
)
def test_syntaxes_numeriques_yaml_exotiques_sont_exactes_ou_refusees(
    tmp_path, monkeypatch, scalaire, attendu, refuse
):
    declare = _lire(tmp_path, monkeypatch, f"configuration:\n  preaudit:\n    {SEUIL}: {scalaire}\n")

    seuils, problemes = controleur_preaudit.seuils_depuis(declare)

    assert seuils["transaction_hors_norme_cad"] == attendu
    assert bool(problemes) is refuse
    if refuse:
        assert SEUIL in problemes[0]


@pytest.mark.parametrize(
    "configuration",
    (
        f"  preaudit:\n    {SEUIL}: 100.01\n    {SEUIL}: 100.0100000000000005\n",
        "  preaudit:\n    <<: *seuils\n",
        f"  preaudit:\n    {SEUIL}: .nan\n",
        f"  preaudit:\n    {SEUIL}: 100.0100000000000005\n",
    ),
)
def test_adoption_n3_exacte_ecrase_toute_valeur_fichier_ambigue(tmp_path, monkeypatch, configuration):
    ancre = "seuils: &seuils\n  seuil_transaction_hors_norme_cad: 100.0100000000000005\n" if "<<:" in configuration else ""
    texte = DECLARATION + ancre + "configuration:\n" + configuration
    monkeypatch.setattr(
        reglages_lecture,
        "adoptees",
        lambda: SimpleNamespace(valeurs={"m5.seuil_transaction_hors_norme_cad": "101.0075"}),
    )

    declare = _lire(tmp_path, monkeypatch, texte)

    assert declare[SEUIL] == "101.0075"
    seuils, problemes = controleur_preaudit.seuils_depuis(declare)
    assert seuils["transaction_hors_norme_cad"] == "101.0075"
    assert problemes == []


def test_doublon_d_un_autre_champ_ne_change_pas_le_seuil_ni_le_champ_charge(tmp_path, monkeypatch):
    texte = (
        "configuration:\n  preaudit:\n"
        f"    {SEUIL}: 100.0100000000000005\n"
        "    jours_fenetre_doublon: 2\n"
        "    jours_fenetre_doublon: 4\n"
    )

    declare = _lire(tmp_path, monkeypatch, texte)
    seuils, problemes = controleur_preaudit.seuils_depuis(declare)

    assert seuils["transaction_hors_norme_cad"] == "100.0100000000000005"
    assert seuils["jours_fenetre_doublon"] == 4
    assert problemes == []


def test_yaml_float_lexeme_est_semantiquement_decimal_et_pas_float_arrondi(tmp_path, monkeypatch):
    texte = f"configuration:\n  preaudit:\n    {SEUIL}: 100.0100000000000005\n"
    parsed = yaml.safe_load(texte)
    assert parsed["configuration"]["preaudit"][SEUIL] == 100.01

    declare = _lire(tmp_path, monkeypatch, texte)
    seuils, problemes = controleur_preaudit.seuils_depuis(declare)

    assert problemes == []
    assert Decimal("100.01") < Decimal(seuils["transaction_hors_norme_cad"])
