from pathlib import Path
import sys

import pytest


RACINE_MODULE = Path(__file__).resolve().parents[1]
DOSSIER_GATE = RACINE_MODULE / "docs" / "bmad"
if str(DOSSIER_GATE) not in sys.path:
    sys.path.insert(0, str(DOSSIER_GATE))

from verif_coherence import verifier_contrat_consomme_existe_vraiment


def _architecture(champs):
    lignes = ["#### `LeadQualifie`", "", "```yaml", "LeadQualifie:"]
    lignes.extend(f"  {nom}: {type_decl}  # type" for nom, type_decl in champs.items())
    lignes.extend([
        "```",
        "",
        "#### `type_travaux`",
        "",
        "`autre`",
    ])
    return "\n".join(lignes)


def _source_m2(champs, corps):
    champs_python = ", ".join(f'"{champ}"' for champ in champs)
    return "\n".join([
        f"CHAMPS_CONTRAT_GELE = ({champs_python},)",
        'TYPES_TRAVAUX = ("autre",)',
        "",
        "def valider(contrat):",
        *[f"    {ligne}" if ligne else "" for ligne in corps.splitlines()],
        "",
    ])


def _ecrire_source(tmp_path, contenu):
    chemin = tmp_path / "contrats.py"
    chemin.write_text(contenu, encoding="utf-8")
    return chemin


def test_variable_intermediaire_simple_est_confrontee(tmp_path):
    source = _source_m2(
        ("contact",),
        'nom = contrat["contact"]\nif not isinstance(nom, dict):\n    return False',
    )
    chemin = _ecrire_source(tmp_path, source)

    assert verifier_contrat_consomme_existe_vraiment(
        _architecture({"contact": "dict"}), chemin
    ) == []

    erreurs = verifier_contrat_consomme_existe_vraiment(
        _architecture({"contact": "str"}), chemin
    )
    assert any("clé « contact »" in erreur for erreur in erreurs)
    assert any("M2 impose « dict »" in erreur for erreur in erreurs)


def test_reaffectation_depuis_deux_cles_ne_produit_aucune_conclusion(tmp_path):
    source = _source_m2(
        ("a", "b"),
        'nom = contrat["a"]\nnom = contrat["b"]\nif not isinstance(nom, dict):\n    return False',
    )
    chemin = _ecrire_source(tmp_path, source)

    erreurs = verifier_contrat_consomme_existe_vraiment(
        _architecture({"a": "str", "b": "int"}), chemin
    )

    assert len(erreurs) == 1
    assert "Aucun contrôle de type extrait" in erreurs[0]
    assert "Type divergent" not in erreurs[0]


def test_types_incompatibles_sur_meme_cle_sont_explicitement_refuses(tmp_path):
    source = _source_m2(
        ("contact",),
        '\n'.join([
            'nom = contrat["contact"]',
            'if not isinstance(contrat["contact"], str):',
            '    return False',
            'if not isinstance(nom, int):',
            '    return False',
        ]),
    )
    chemin = _ecrire_source(tmp_path, source)

    erreurs = verifier_contrat_consomme_existe_vraiment(
        _architecture({"contact": "str"}), chemin
    )

    assert len(erreurs) == 1
    assert "clé « contact »" in erreurs[0]
    assert "int" in erreurs[0]
    assert "str" in erreurs[0]
    assert "incompatibles" in erreurs[0]


def test_acces_par_cle_de_boucle_variable_reste_ignore(tmp_path):
    source = _source_m2(
        ("ville",),
        '\n'.join([
            'for champ in ("ville",):',
            '    valeur = contrat[champ]',
            '    if not isinstance(valeur, str):',
            '        return False',
        ]),
    )
    chemin = _ecrire_source(tmp_path, source)

    erreurs = verifier_contrat_consomme_existe_vraiment(
        _architecture({"ville": "int"}), chemin
    )

    assert len(erreurs) == 1
    assert "Aucun contrôle de type extrait" in erreurs[0]
    assert "ville" not in erreurs[0]


def test_acces_direct_urgence_declaree_continue_d_etre_confronte(tmp_path):
    source = _source_m2(
        ("urgence_declaree",),
        'if type(contrat["urgence_declaree"]) is not bool:\n    return False',
    )
    chemin = _ecrire_source(tmp_path, source)

    assert verifier_contrat_consomme_existe_vraiment(
        _architecture({"urgence_declaree": "bool"}), chemin
    ) == []

    erreurs = verifier_contrat_consomme_existe_vraiment(
        _architecture({"urgence_declaree": "str"}), chemin
    )
    assert len(erreurs) == 1
    assert "clé « urgence_declaree »" in erreurs[0]
    assert "M2 impose « bool »" in erreurs[0]


def _architecture_avec_optionnelles(gelees, optionnelles):
    lignes = ["#### `LeadQualifie`", "", "```yaml", "LeadQualifie:"]
    lignes.extend(f"  {nom}: {type_decl}  # gelée" for nom, type_decl in gelees.items())
    lignes.extend(
        f"  {nom}: {type_decl}  # OPTIONNEL (PLAN T2.2)" for nom, type_decl in optionnelles.items()
    )
    lignes.extend(["```", "", "#### `type_travaux`", "", "`autre`"])
    return "\n".join(lignes)


def _source_m2_avec_optionnelles(gelees, optionnelles, corps):
    source = _source_m2(gelees, corps)
    optionnels_python = ", ".join(f'"{champ}"' for champ in optionnelles)
    return f"CHAMPS_CONTRAT_OPTIONNELS = ({optionnels_python},)\n" + source


_CORPS_UTM = 'utm = contrat["utm"]\nif not isinstance(utm, dict):\n    return False'


def test_cles_optionnelles_declarees_des_deux_cotes_sont_confrontees(tmp_path):
    chemin = _ecrire_source(
        tmp_path, _source_m2_avec_optionnelles(("contact",), ("utm",), _CORPS_UTM))

    assert verifier_contrat_consomme_existe_vraiment(
        _architecture_avec_optionnelles({"contact": "dict"}, {"utm": "dict"}), chemin
    ) == []

    erreurs = verifier_contrat_consomme_existe_vraiment(
        _architecture_avec_optionnelles({"contact": "dict"}, {"utm": "str"}), chemin)
    assert any("clé « utm »" in erreur and "M2 impose « dict »" in erreur for erreur in erreurs)


def test_cle_optionnelle_de_m2_absente_de_l_architecture_est_signalee(tmp_path):
    chemin = _ecrire_source(
        tmp_path, _source_m2_avec_optionnelles(("contact",), ("utm",), _CORPS_UTM))

    erreurs = verifier_contrat_consomme_existe_vraiment(
        _architecture_avec_optionnelles({"contact": "dict"}, {}), chemin)
    assert erreurs and "OPTIONNELLES" in erreurs[0] and "'utm'" in erreurs[0]


def test_cle_optionnelle_non_marquee_est_confondue_avec_une_cle_gelee(tmp_path):
    chemin = _ecrire_source(
        tmp_path, _source_m2_avec_optionnelles(("contact",), ("utm",), _CORPS_UTM))

    erreurs = verifier_contrat_consomme_existe_vraiment(
        _architecture({"contact": "dict", "utm": "dict"}), chemin)
    assert erreurs and "DIFFÈRE" in erreurs[0] and "'utm'" in erreurs[0]


def test_cle_marquee_optionnelle_inconnue_du_producteur_est_signalee(tmp_path):
    chemin = _ecrire_source(tmp_path, _source_m2(
        ("contact",), 'nom = contrat["contact"]\nif not isinstance(nom, dict):\n    return False'))

    erreurs = verifier_contrat_consomme_existe_vraiment(
        _architecture_avec_optionnelles({"contact": "dict"}, {"source": "str"}), chemin)
    assert erreurs and "OPTIONNELLES" in erreurs[0] and "'source'" in erreurs[0]
