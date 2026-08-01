"""Tests M3-S008 — registre append-only hash-chaîné des estimations."""

import ast
import inspect
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import contrats, devis, registre, verdicts


def _empreinte_valide():
    """Fabrique une empreinte M2 canonique attendue par EstimationV1."""
    return "a" * 64


def _charge_valide(**surcharges):
    """Fabrique une charge d'estimation déterministe destinée à un maillon."""
    charge = {
        "devis_id": "M3-DEVIS-charge-s008-001",
        "lead_id": "lead-s008-001",
        "empreinte_marqueur_m2": _empreinte_valide(),
        "niveau_confiance": 0.9,
        "bareme_version": "2025.1",
        "graine_monte_carlo": 314159,
    }
    charge.update(surcharges)
    return charge


def _ajouter_valide(journal, charge=None):
    """Ajoute une charge valide et affirme que l'ajout ne produit pas de rejet."""
    maillon, verdict = journal.ajouter(
        _charge_valide() if charge is None else charge
    )
    assert verdict is None
    assert maillon is not None
    return maillon


def _journal_a_trois_maillons():
    """Fabrique une chaîne de trois maillons distincts pour les tests d'intégrité."""
    journal = registre.Registre()
    _ajouter_valide(
        journal,
        _charge_valide(
            devis_id="M3-DEVIS-charge-s008-001",
            lead_id="lead-s008-001",
        ),
    )
    _ajouter_valide(
        journal,
        _charge_valide(
            devis_id="M3-DEVIS-charge-s008-002",
            lead_id="lead-s008-002",
        ),
    )
    _ajouter_valide(
        journal,
        _charge_valide(
            devis_id="M3-DEVIS-charge-s008-003",
            lead_id="lead-s008-003",
        ),
    )
    return journal


def _assert_validation_invalide_au_rang(journal, rang):
    """Affirme qu'un diagnostic d'intégrité désigne exactement le rang fautif."""
    valide, diagnostic = journal.valider_chaine()

    assert valide is False
    assert isinstance(diagnostic, str)
    assert diagnostic

    import re

    correspondance = re.search(r"\brang\b\D*(\d+)", diagnostic)
    if correspondance is None:
        pytest.fail(
            "Le diagnostic d'intégrité ne contient aucun rang numérique : "
            f"{diagnostic!r}"
        )

    rang_diagnostique = int(correspondance.group(1))
    assert rang_diagnostique == rang


def test_premier_maillon_porte_un_predecesseur_initial_explicite_et_stable():
    """Verrouille le prédécesseur conventionnel explicite et stable du premier maillon."""
    premier_journal = registre.Registre()
    second_journal = registre.Registre()

    premier = _ajouter_valide(premier_journal)
    second = _ajouter_valide(second_journal)

    assert isinstance(registre.HASH_PREDECESSEUR_INITIAL, str)
    assert registre.HASH_PREDECESSEUR_INITIAL
    assert premier["hash_precedent"] == registre.HASH_PREDECESSEUR_INITIAL
    assert second["hash_precedent"] == registre.HASH_PREDECESSEUR_INITIAL
    assert premier["hash_precedent"] == second["hash_precedent"]
    assert premier["hash_precedent"] is not None


def test_hash_du_second_maillon_depend_effectivement_du_hash_du_premier():
    """Verrouille la propagation effective d'une modification du premier hash dans le second."""
    journal_a = registre.Registre()
    premier_a = _ajouter_valide(
        journal_a,
        _charge_valide(devis_id="M3-DEVIS-propagation-a"),
    )
    second_a = _ajouter_valide(
        journal_a,
        _charge_valide(devis_id="M3-DEVIS-propagation-b"),
    )

    journal_b = registre.Registre()
    premier_b = _ajouter_valide(
        journal_b,
        _charge_valide(devis_id="M3-DEVIS-propagation-a-modifie"),
    )
    second_b = _ajouter_valide(
        journal_b,
        _charge_valide(devis_id="M3-DEVIS-propagation-b"),
    )

    assert premier_a["hash_maillon"] != premier_b["hash_maillon"]
    assert second_a["hash_precedent"] == premier_a["hash_maillon"]
    assert second_b["hash_precedent"] == premier_b["hash_maillon"]
    assert second_a["hash_maillon"] != second_b["hash_maillon"]


def test_hash_du_registre_est_transportable_tel_quel_par_estimation_v1():
    """Verrouille que le hash produit par le registre est celui porté par EstimationV1."""
    journal = registre.Registre()
    maillon = _ajouter_valide(journal)

    estimation, verdict = devis.assembler_estimation(
        lead_id="lead-s008-estimation",
        empreinte_marqueur_m2=_empreinte_valide(),
        niveau_confiance=0.9,
        verdicts_estimation=(contrats.VERDICT_AUCUN_BLOCAGE,),
        bareme_version="2025.1",
        prix_bloque=False,
        intervalle_confiance={
            "borne_basse": 100.0,
            "borne_haute": 200.0,
            "niveau": 0.9,
        },
        alerte_plancher=False,
        raison_blocage=None,
        graine_monte_carlo=314159,
        hash_maillon=maillon["hash_maillon"],
    )

    assert verdict is None
    assert estimation["hash_maillon"] == maillon["hash_maillon"]


def test_validation_reussit_pour_une_chaine_intacte():
    """Verrouille CA-M3-18 sur une chaîne complète qui n'a subi aucune altération."""
    journal = _journal_a_trois_maillons()

    valide, diagnostic = journal.valider_chaine()

    assert valide is True
    assert diagnostic == ""


def test_validation_echoue_et_nomme_le_rang_si_charge_du_maillon_est_alteree():
    """Verrouille la détection et le diagnostic de l'altération de la charge d'un maillon."""
    journal = _journal_a_trois_maillons()
    journal._maillons[1]["charge"]["lead_id"] = "lead-s008-altere"

    _assert_validation_invalide_au_rang(journal, 1)


def test_validation_echoue_et_nomme_le_rang_si_hash_du_maillon_est_altere():
    """Verrouille la détection et le diagnostic de l'altération du hash d'un maillon."""
    journal = _journal_a_trois_maillons()
    journal._maillons[1]["hash_maillon"] = "hash-maillon-altere"

    _assert_validation_invalide_au_rang(journal, 1)


def test_validation_echoue_et_nomme_le_rang_si_hash_precedent_est_altere():
    """Verrouille la détection et le diagnostic de l'altération du lien précédent."""
    journal = _journal_a_trois_maillons()
    journal._maillons[1]["hash_precedent"] = "hash-precedent-altere"

    _assert_validation_invalide_au_rang(journal, 1)


def test_validation_echoue_si_un_maillon_intermediaire_est_retire():
    """Verrouille qu'une suppression intermédiaire ne peut pas survivre à la validation."""
    journal = _journal_a_trois_maillons()
    del journal._maillons[1]

    _assert_validation_invalide_au_rang(journal, 1)


def test_validation_echoue_si_deux_maillons_sont_permutés():
    """Verrouille qu'une permutation de maillons est détectée par le chaînage."""
    journal = _journal_a_trois_maillons()
    journal._maillons[1], journal._maillons[2] = (
        journal._maillons[2],
        journal._maillons[1],
    )

    _assert_validation_invalide_au_rang(journal, 1)


def test_validation_echoue_si_un_maillon_est_duplique():
    """Verrouille qu'une duplication de maillon ne peut pas former une chaîne valide.

    Le maillon dupliqué est indétectable à sa propre position, car il y reste
    structurellement cohérent avec le maillon qui le précède. L'anomalie devient
    détectable à la position suivante, où le rang stocké cesse de correspondre
    à la position réelle ; le rang attendu est donc 2.
    """
    journal = _journal_a_trois_maillons()
    journal._maillons.insert(1, journal._maillons[1].copy())

    _assert_validation_invalide_au_rang(journal, 2)


def test_lecture_retourne_une_copie_sans_reference_vivante_sur_le_registre():
    """Verrouille qu'une mutation de lecture ne modifie jamais l'état append-only interne."""
    journal = registre.Registre()
    maillon = _ajouter_valide(journal)
    lecture = journal.lire()

    lecture[0]["charge"]["lead_id"] = "lead-s008-mutation-externe"
    lecture[0]["hash_maillon"] = "hash-externe-altere"

    lecture_apres_mutation = journal.lire()
    valide, diagnostic = journal.valider_chaine()

    assert lecture_apres_mutation[0]["charge"]["lead_id"] == maillon["charge"]["lead_id"]
    assert lecture_apres_mutation[0]["hash_maillon"] == maillon["hash_maillon"]
    assert valide is True
    assert diagnostic == ""


def test_surface_publique_ne_propose_aucune_mutation_ou_suppression_de_maillon():
    """Verrouille que la surface publique n'expose ni modification ni suppression de maillon."""
    termes_interdits = (
        "modifier",
        "modifie",
        "mise_a_jour",
        "mettre_a_jour",
        "supprimer",
        "effacer",
        "retirer",
        "remplacer",
    )

    fonctions_module = {
        nom
        for nom, objet in inspect.getmembers(registre, inspect.isfunction)
        if not nom.startswith("_") and objet.__module__ == registre.__name__
    }
    methodes_registre = {
        nom
        for nom, objet in inspect.getmembers(registre.Registre, inspect.isfunction)
        if not nom.startswith("_")
    }
    surface_publique = fonctions_module | methodes_registre

    assert "ajouter" in methodes_registre
    assert "lire" in methodes_registre
    assert "valider_chaine" in methodes_registre
    assert all(
        terme not in nom.lower()
        for nom in surface_publique
        for terme in termes_interdits
    )


def test_ajout_deterministe_a_charge_et_predecesseur_identiques():
    """Verrouille que les mêmes conditions d'ajout produisent exactement le même hash."""
    charge = _charge_valide(devis_id="M3-DEVIS-determinisme")

    journal_a = registre.Registre()
    journal_b = registre.Registre()
    maillon_a = _ajouter_valide(journal_a, charge)
    maillon_b = _ajouter_valide(journal_b, charge)

    assert maillon_a["hash_precedent"] == maillon_b["hash_precedent"]
    assert maillon_a["hash_maillon"] == maillon_b["hash_maillon"]


def test_encodage_canonique_ignore_ordre_insertion_des_cles_de_charge():
    """Verrouille que deux dictionnaires égaux d'ordres d'insertion distincts ont le même hash."""
    charge_a = {
        "devis_id": "M3-DEVIS-canonique",
        "lead_id": "lead-s008-canonique",
        "empreinte_marqueur_m2": _empreinte_valide(),
        "niveau_confiance": 0.9,
        "bareme_version": "2025.1",
        "graine_monte_carlo": 314159,
    }
    charge_b = {}
    for cle in (
        "graine_monte_carlo",
        "bareme_version",
        "niveau_confiance",
        "empreinte_marqueur_m2",
        "lead_id",
        "devis_id",
    ):
        charge_b[cle] = charge_a[cle]

    journal_a = registre.Registre()
    journal_b = registre.Registre()
    maillon_a = _ajouter_valide(journal_a, charge_a)
    maillon_b = _ajouter_valide(journal_b, charge_b)

    assert charge_a == charge_b
    assert list(charge_a) != list(charge_b)
    assert maillon_a["hash_maillon"] == maillon_b["hash_maillon"]


def test_maillon_reserve_explicitement_la_place_vide_du_cout_reel():
    """Verrouille la présence explicite et vide de l'emplacement coût réel réservé à M5/M6."""
    journal = registre.Registre()
    maillon = _ajouter_valide(journal)

    assert "cout_reel" in maillon
    assert maillon["cout_reel"] is None


def test_registre_nimporte_ni_horloge_alea_ni_reseau():
    """Verrouille que registre.py ne consulte ni horloge, ni aléa, ni réseau."""
    modules_interdits = {
        "datetime",
        "time",
        "random",
        "socket",
        "urllib",
    }
    source = Path(registre.__file__).read_text(encoding="utf-8")
    arbre = ast.parse(source, filename=registre.__file__)

    imports_interdits = []
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            imports_interdits.extend(
                alias.name
                for alias in noeud.names
                if alias.name.split(".")[0] in modules_interdits
            )
        elif isinstance(noeud, ast.ImportFrom):
            module = noeud.module or ""
            if module.split(".")[0] in modules_interdits:
                imports_interdits.append(module)

    assert imports_interdits == []


def test_entree_non_dictionnaire_est_refusee_par_verdict_sans_exception():
    """Verrouille le refus fail-closed d'une entrée non dictionnaire hostile."""
    journal = registre.Registre()
    try:
        maillon, verdict = journal.ajouter(None)
    except (AttributeError, KeyError, TypeError, ValueError) as erreur:
        pytest.fail(
            "ajouter a laissé échapper "
            f"{type(erreur).__name__} pour une entrée non dictionnaire"
        )

    assert maillon is None
    assert isinstance(verdict, dict)
    assert verdicts.est_verdict(verdict["code"])


def test_entree_vide_est_refusee_par_verdict_sans_exception():
    """Verrouille le refus fail-closed d'une charge vide dépourvue de contrat exploitable."""
    journal = registre.Registre()
    try:
        maillon, verdict = journal.ajouter({})
    except (AttributeError, KeyError, TypeError, ValueError) as erreur:
        pytest.fail(
            "ajouter a laissé échapper "
            f"{type(erreur).__name__} pour une charge vide"
        )

    assert maillon is None
    assert isinstance(verdict, dict)
    assert verdicts.est_verdict(verdict["code"])


def test_entree_avec_valeur_non_canonique_est_refusee_par_verdict_sans_exception():
    """Verrouille le refus fail-closed d'une charge contenant une valeur non canonique hostile."""
    journal = registre.Registre()
    charge_hostile = _charge_valide()
    charge_hostile["niveau_confiance"] = object()

    try:
        maillon, verdict = journal.ajouter(charge_hostile)
    except (AttributeError, KeyError, TypeError, ValueError) as erreur:
        pytest.fail(
            "ajouter a laissé échapper "
            f"{type(erreur).__name__} pour une valeur non canonique"
        )

    assert maillon is None
    assert isinstance(verdict, dict)
    assert verdicts.est_verdict(verdict["code"])


def test_predecesseur_initial_conventionnel_est_epingle_a_sa_valeur_zero_sha256():
    """Verrouille la valeur conventionnelle exacte et son portage par le premier maillon."""
    journal = registre.Registre()

    maillon = _ajouter_valide(journal)

    assert registre.HASH_PREDECESSEUR_INITIAL == "0" * 64
    assert maillon["hash_precedent"] == "0" * 64


def test_ajout_copie_defensivement_la_charge_de_lappelant():
    """Verrouille qu'une mutation ultérieure de la charge appelante ne corrompt pas le journal."""
    journal = registre.Registre()
    charge = _charge_valide()
    maillon = _ajouter_valide(journal, charge)

    charge["lead_id"] = "lead-s008-mutation-apres-ajout"

    lecture = journal.lire()
    valide, diagnostic = journal.valider_chaine()

    assert maillon["charge"]["lead_id"] == "lead-s008-001"
    assert lecture[0]["charge"]["lead_id"] == "lead-s008-001"
    assert valide is True
    assert diagnostic == ""
