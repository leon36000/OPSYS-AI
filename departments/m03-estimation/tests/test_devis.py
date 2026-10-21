"""Tests de contrat du devis d'estimation M3 (cahier M3-S007)."""

import ast
import hashlib
import re
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
_TESTS = Path(__file__).resolve().parent
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))

from _commun_contrats import cles_du_bloc_yaml  # noqa: E402
from m3_estimation import contrats, devis, verdicts  # noqa: E402

_CLES_ESTIMATION_ATTENDUES = {
    "devis_id",
    "lead_id",
    "empreinte_marqueur_m2",
    "niveau_confiance",
    "verdict_estimation",
    "bareme_version",
    "prix_bloque",
    "intervalle_confiance",
    "alerte_plancher",
    "raison_blocage",
    "graine_monte_carlo",
    "hash_maillon",
}

_CLES_INTERVALLE_ATTENDUES = {
    "borne_basse",
    "borne_haute",
    "niveau",
}

_PRIORITE_VERDICTS = (
    contrats.VERDICT_CONTRAT_ENTREE_INVALIDE,
    contrats.VERDICT_QUALITE_ENTREE_INSUFFISANTE,
    contrats.VERDICT_REFERENCE_ECHELLE_ABSENTE,
    contrats.VERDICT_INDETERMINE,
    contrats.VERDICT_PLANCHER_RENTABILITE_FRANCHI,
    contrats.VERDICT_AUCUN_BLOCAGE,
)


def _empreinte_valide():
    """Fabrique une empreinte M2 canonique, minuscule et longue de 64 caractères."""
    return "a" * 64


def _hash_maillon_valide():
    """Fabrique un hash de maillon opaque non vide fourni par l'appelant."""
    return "maillon-registre-m3-0001"


def _intervalle_valide(**surcharges):
    """Fabrique le sous-objet intervalle complet d'une estimation non bloquée."""
    intervalle = {
        "borne_basse": 100.0,
        "borne_haute": 200.0,
        "niveau": 0.9,
    }
    intervalle.update(surcharges)
    return intervalle


def _donnees_estimation_valides(**surcharges):
    """Fabrique toutes les entrées explicites de l'assembleur sur voie non bloquée."""
    donnees = {
        "lead_id": "lead-s007-001",
        "empreinte_marqueur_m2": _empreinte_valide(),
        "niveau_confiance": 0.9,
        "verdicts_estimation": (contrats.VERDICT_AUCUN_BLOCAGE,),
        "bareme_version": "2025.1",
        "prix_bloque": False,
        "intervalle_confiance": _intervalle_valide(),
        "alerte_plancher": False,
        "raison_blocage": None,
        "graine_monte_carlo": 314159,
        "hash_maillon": _hash_maillon_valide(),
    }
    donnees.update(surcharges)
    return donnees


def _assembler(**surcharges):
    """Assemble une estimation à partir de la fabrique nominale et de surcharges."""
    return devis.assembler_estimation(**_donnees_estimation_valides(**surcharges))


def _encodage_documente(lead_id, empreinte):
    """Reproduit l'encodage gelé du PRD pour vérifier sa forme, pas le code M3."""
    return (
        f"{len(lead_id):04d}"
        + lead_id
        + f"{len(empreinte):04d}"
        + empreinte
    )


def test_champs_de_contrat_sont_les_listes_fermees_attendues():
    """Les deux constantes de contrat exposent exactement les 12 et 3 clés ratifiées."""
    assert set(contrats.CHAMPS_ESTIMATION_V1) == _CLES_ESTIMATION_ATTENDUES
    assert len(contrats.CHAMPS_ESTIMATION_V1) == len(_CLES_ESTIMATION_ATTENDUES)
    assert set(contrats.CHAMPS_INTERVALLE_CONFIANCE) == _CLES_INTERVALLE_ATTENDUES
    assert len(contrats.CHAMPS_INTERVALLE_CONFIANCE) == len(
        _CLES_INTERVALLE_ATTENDUES
    )


def test_derivation_respecte_exactement_encodage_prefixe_et_troncature_du_prd():
    """Le devis_id est le SHA-256 tronqué à 16 hexadécimaux du format gelé."""
    lead_id = "lead-s007-encodage"
    empreinte = _empreinte_valide()
    encodage = _encodage_documente(lead_id, empreinte)
    attendu = "M3-DEVIS-" + hashlib.sha256(
        encodage.encode("utf-8")
    ).hexdigest()[:16]

    obtenu = devis.deriver_devis_id(lead_id, empreinte)

    assert obtenu == attendu
    assert obtenu.startswith("M3-DEVIS-")
    assert len(obtenu) == len("M3-DEVIS-") + 16


def test_encodage_est_injectif_sur_decoupages_enumeres_sans_pretendre_au_devis_id():
    """Les découpages énumérés donnent des encodages distincts ; cela ne prouve pas
    universellement l'injectivité et le devis_id tronqué sur 64 bits peut collisionner.
    """
    couples = (
        ("ab", "c"),
        ("a", "bc"),
        ("abc", "d"),
        ("ab", "cd"),
    )

    encodages = {
        _encodage_documente(lead_id, empreinte)
        for lead_id, empreinte in couples
    }

    assert len(encodages) == len(couples)
    assert _encodage_documente("ab", "c") != _encodage_documente("a", "bc")


def test_garde_de_longueur_empeche_collision_constructible_du_format_a_quatre_chiffres():
    """Un lead de 10000 caractères est refusé : sans cette garde, les deux couples
    construits ci-dessous produiraient le même encodage ambigu à largeur quatre.
    """
    empreinte = "c" * 64
    lead_trop_long = "a" * 999 + "9065" + "b" * 8997
    lead_alternatif = "0" + lead_trop_long[:999]
    empreinte_alternative = lead_trop_long[1003:] + "0064" + empreinte

    assert len(lead_trop_long) == 10000
    assert len(lead_alternatif) == 1000
    assert len(empreinte_alternative) == 9065
    assert _encodage_documente(lead_trop_long, empreinte) == _encodage_documente(
        lead_alternatif, empreinte_alternative
    )
    with pytest.raises(ValueError):
        devis.deriver_devis_id(lead_trop_long, empreinte)


@pytest.mark.parametrize(
    "lead_id",
    (
        "",
        None,
        42,
        "x" * 10000,
    ),
    ids=(
        "vide",
        "none",
        "entier",
        "depasse_9999_caracteres",
    ),
)
def test_derivation_refuse_lead_id_invalide(lead_id):
    """Un lead_id vide, non textuel ou trop long ne peut pas former un encodage sûr."""
    with pytest.raises(ValueError):
        devis.deriver_devis_id(lead_id, _empreinte_valide())


@pytest.mark.parametrize(
    "empreinte",
    (
        "a" * 63,
        "a" * 65,
        "A" * 64,
        "g" * 64,
        "a" * 63 + "-",
    ),
    ids=(
        "longueur_63",
        "longueur_65",
        "majuscules_non_normalisees",
        "caractere_hors_hexadecimal",
        "ponctuation_hors_hexadecimal",
    ),
)
def test_derivation_refuse_empreinte_non_canonique(empreinte):
    """L'empreinte doit être exactement 64 hexadécimaux minuscules, sans normalisation."""
    with pytest.raises(ValueError):
        devis.deriver_devis_id("lead-s007-empreinte", empreinte)


def test_derivation_est_deterministe_a_entrees_identiques():
    """Deux dérivations identiques donnent bit à bit le même identifiant de devis."""
    lead_id = "lead-s007-deterministe"
    empreinte = _empreinte_valide()

    premier = devis.deriver_devis_id(lead_id, empreinte)
    second = devis.deriver_devis_id(lead_id, empreinte)

    assert premier == second


def test_assemblage_rend_exactement_les_douze_cles_du_contrat():
    """Une estimation valide contient les 12 clés de premier niveau, ni plus ni moins."""
    estimation, verdict = _assembler()

    assert verdict is None
    assert estimation is not None
    assert set(estimation) == _CLES_ESTIMATION_ATTENDUES
    assert estimation["devis_id"] == devis.deriver_devis_id(
        _donnees_estimation_valides()["lead_id"],
        _donnees_estimation_valides()["empreinte_marqueur_m2"],
    )


def test_assemblage_conserve_cles_nullables_et_cles_intervalle_meme_a_none():
    """Les champs nullables restent présents : None ne signifie jamais clé omise."""
    estimation, verdict = _assembler(
        prix_bloque=True,
        bareme_version=None,
        intervalle_confiance=_intervalle_valide(
            borne_basse=None,
            borne_haute=None,
        ),
        raison_blocage="Informations visuelles insuffisantes pour chiffrer.",
        verdicts_estimation=(contrats.VERDICT_QUALITE_ENTREE_INSUFFISANTE,),
    )

    assert verdict is None
    assert set(estimation) == _CLES_ESTIMATION_ATTENDUES
    assert "bareme_version" in estimation
    assert estimation["bareme_version"] is None
    assert "raison_blocage" in estimation
    assert estimation["raison_blocage"] is not None
    assert set(estimation["intervalle_confiance"]) == _CLES_INTERVALLE_ATTENDUES
    assert estimation["intervalle_confiance"]["borne_basse"] is None
    assert estimation["intervalle_confiance"]["borne_haute"] is None


@pytest.mark.parametrize(
    "cle_inconnue",
    (
        "note_interne",
        "montant_previsionnel",
        "horodatage_estimation",
    ),
)
def test_assemblage_refuse_toute_cle_hors_liste_blanche(cle_inconnue):
    """Toute clé hors contrat, même financière ou temporelle au nom anodin, est rejetée."""
    estimation, verdict = _assembler(**{cle_inconnue: "valeur-non-contractuelle"})

    assert estimation is None
    assert verdict["code"] in verdicts.CODES_M3_LIST


@pytest.mark.parametrize(
    "hash_maillon",
    (
        "",
        None,
        42,
    ),
    ids=(
        "vide",
        "none",
        "entier",
    ),
)
def test_assemblage_refuse_hash_maillon_vide_ou_non_chaine(hash_maillon):
    """Le hash de maillon est fourni par l'appelant et doit être une chaîne non vide."""
    estimation, verdict = _assembler(hash_maillon=hash_maillon)

    assert estimation is None
    assert verdict["code"] in verdicts.CODES_M3_LIST


def test_prix_bloque_impose_bornes_nulles_et_raison_non_vide():
    """Le blocage interdit toute fuite de prix et exige une raison explicitement fournie."""
    estimation, verdict = _assembler(
        prix_bloque=True,
        bareme_version=None,
        intervalle_confiance=_intervalle_valide(
            borne_basse=None,
            borne_haute=None,
        ),
        raison_blocage="La qualification ne permet pas de produire un prix.",
        verdicts_estimation=(contrats.VERDICT_QUALITE_ENTREE_INSUFFISANTE,),
    )

    assert verdict is None
    assert estimation["prix_bloque"] is True
    assert estimation["intervalle_confiance"]["borne_basse"] is None
    assert estimation["intervalle_confiance"]["borne_haute"] is None
    assert estimation["raison_blocage"]


@pytest.mark.parametrize(
    "surcharges",
    (
        {
            "prix_bloque": True,
            "bareme_version": None,
            "intervalle_confiance": _intervalle_valide(),
            "raison_blocage": "Prix pourtant présent.",
            "verdicts_estimation": (
                contrats.VERDICT_QUALITE_ENTREE_INSUFFISANTE,
            ),
        },
        {
            "prix_bloque": True,
            "bareme_version": None,
            "intervalle_confiance": _intervalle_valide(
                borne_basse=None,
                borne_haute=None,
            ),
            "raison_blocage": "",
            "verdicts_estimation": (
                contrats.VERDICT_QUALITE_ENTREE_INSUFFISANTE,
            ),
        },
    ),
    ids=(
        "bloque_mais_bornes_numeriques",
        "bloque_sans_raison",
    ),
)
def test_les_contraintes_du_prix_bloque_sont_rejetees_dans_le_sens_inverse(
    surcharges,
):
    """Aucune estimation bloquée incohérente ne peut conserver un prix ou perdre sa raison."""
    estimation, verdict = _assembler(**surcharges)

    assert estimation is None
    assert verdict["code"] in verdicts.CODES_M3_LIST


def test_prix_non_bloque_impose_bornes_numeriques_et_raison_nulle():
    """Un prix produit porte deux bornes numériques et aucune raison de blocage."""
    estimation, verdict = _assembler()

    assert verdict is None
    assert estimation["prix_bloque"] is False
    assert isinstance(estimation["intervalle_confiance"]["borne_basse"], float)
    assert isinstance(estimation["intervalle_confiance"]["borne_haute"], float)
    assert estimation["raison_blocage"] is None


@pytest.mark.parametrize(
    "surcharges",
    (
        {
            "prix_bloque": False,
            "intervalle_confiance": _intervalle_valide(
                borne_basse=None,
                borne_haute=None,
            ),
        },
        {
            "prix_bloque": False,
            "raison_blocage": "Raison incompatible avec un prix produit.",
        },
    ),
    ids=(
        "non_bloque_mais_bornes_nulles",
        "non_bloque_mais_raison_presente",
    ),
)
def test_les_contraintes_du_prix_non_bloque_sont_rejetees_dans_le_sens_inverse(
    surcharges,
):
    """Aucune estimation non bloquée ne peut masquer ses bornes ou déclarer un blocage."""
    estimation, verdict = _assembler(**surcharges)

    assert estimation is None
    assert verdict["code"] in verdicts.CODES_M3_LIST


def test_bareme_version_none_si_et_seulement_si_prix_bloque():
    """La version de barème est absente exactement sur la voie où aucun prix n'est produit."""
    estimation_bloquee, verdict_bloque = _assembler(
        prix_bloque=True,
        bareme_version=None,
        intervalle_confiance=_intervalle_valide(
            borne_basse=None,
            borne_haute=None,
        ),
        raison_blocage="Le chiffrage est bloqué en amont.",
        verdicts_estimation=(contrats.VERDICT_QUALITE_ENTREE_INSUFFISANTE,),
    )
    estimation_non_bloquee, verdict_non_bloque = _assembler()

    assert verdict_bloque is None
    assert estimation_bloquee["bareme_version"] is None
    assert estimation_bloquee["prix_bloque"] is True
    assert verdict_non_bloque is None
    assert estimation_non_bloquee["bareme_version"] is not None
    assert estimation_non_bloquee["prix_bloque"] is False


@pytest.mark.parametrize(
    "surcharges",
    (
        {
            "prix_bloque": True,
            "bareme_version": "2025.1",
            "intervalle_confiance": _intervalle_valide(
                borne_basse=None,
                borne_haute=None,
            ),
            "raison_blocage": "Version de barème incompatible avec blocage.",
            "verdicts_estimation": (
                contrats.VERDICT_QUALITE_ENTREE_INSUFFISANTE,
            ),
        },
        {
            "prix_bloque": False,
            "bareme_version": None,
        },
    ),
    ids=(
        "bloque_mais_version_presente",
        "non_bloque_mais_version_absente",
    ),
)
def test_equivalence_bareme_et_blocage_est_verifiee_dans_les_deux_sens(
    surcharges,
):
    """Les deux contre-sens de l'équivalence bareme_version/prix_bloque sont refusés."""
    estimation, verdict = _assembler(**surcharges)

    assert estimation is None
    assert verdict["code"] in verdicts.CODES_M3_LIST


@pytest.mark.parametrize(
    "rang_fort, rang_faible",
    tuple(
        (rang_fort, rang_faible)
        for rang_fort in range(len(_PRIORITE_VERDICTS))
        for rang_faible in range(rang_fort + 1, len(_PRIORITE_VERDICTS))
    ),
)
def test_priorite_des_verdicts_est_verifiee_dans_les_deux_ordres(
    rang_fort,
    rang_faible,
):
    """Chaque paire de verdicts tranche vers la cause la plus forte, quel que soit son ordre."""
    verdict_fort = _PRIORITE_VERDICTS[rang_fort]
    verdict_faible = _PRIORITE_VERDICTS[rang_faible]

    estimation_faible_fort, rejet_faible_fort = _assembler(
        verdicts_estimation=(verdict_faible, verdict_fort),
    )
    estimation_fort_faible, rejet_fort_faible = _assembler(
        verdicts_estimation=(verdict_fort, verdict_faible),
    )

    assert rejet_faible_fort is None
    assert rejet_fort_faible is None
    assert estimation_faible_fort["verdict_estimation"] == verdict_fort
    assert estimation_fort_faible["verdict_estimation"] == verdict_fort


def test_indetermine_est_transmis_par_la_constante_de_contrat():
    """INDETERMINE est sélectionné via sa constante et non par un littéral recopié."""
    estimation, verdict = _assembler(
        verdicts_estimation=(contrats.VERDICT_INDETERMINE,),
    )

    assert verdict is None
    assert estimation["verdict_estimation"] == contrats.VERDICT_INDETERMINE


def test_contrat_estimation_est_aligne_sur_bloc_architecture_a_toutes_profondeurs():
    """Les 15 clés extraites du bloc architecture égalent l'union des contrats top-level et intervalle."""
    cles_document = cles_du_bloc_yaml(
        re.compile(r"^#{1,6}\s+.*\bEstimationV1\b.*$", re.MULTILINE),
        3,
    )
    cles_contrat = set(contrats.CHAMPS_ESTIMATION_V1) | set(
        contrats.CHAMPS_INTERVALLE_CONFIANCE
    )

    assert cles_document == cles_contrat
    assert len(cles_document) == 15


def test_liste_blanche_ferme_le_cas_horodatage_non_detectable_lexicalement():
    """horodatage_estimation ne contient pas « date », mais la liste blanche le refuse quand même."""
    champ_date_anodin = "horodatage_estimation"
    estimation, verdict = _assembler(**{champ_date_anodin: "2025-01-01T00:00:00Z"})

    assert "date" not in champ_date_anodin
    assert champ_date_anodin not in contrats.CHAMPS_ESTIMATION_V1
    assert estimation is None
    assert verdict["code"] in verdicts.CODES_M3_LIST


def test_devis_nimporte_ni_horloge_alea_ni_reseau():
    """Le seul fichier devis.py n'importe ni date système, ni aléa, ni bibliothèque réseau."""
    modules_interdits = {
        "datetime",
        "time",
        "random",
        "socket",
        "urllib",
        "requests",
    }
    source = Path(devis.__file__).read_text(encoding="utf-8")
    arbre = ast.parse(source)

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


def test_assembler_estimation_verrouille_statiquement_cles_litterales():
    """Verrouille les clés du littéral EstimationV1, statiquement car leur ensemble est fixé à l'analyse."""
    import ast
    import pathlib

    from m3_estimation import contrats

    source = (
        pathlib.Path(__file__).resolve().parents[1]
        / "src"
        / "m3_estimation"
        / "devis.py"
    )
    arbre = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    assembleurs = [
        noeud
        for noeud in arbre.body
        if isinstance(noeud, ast.FunctionDef)
        and noeud.name == "assembler_estimation"
    ]
    assert len(assembleurs) == 1, (
        "extracteur statique nommé : assembler_estimation introuvable ou ambigu"
    )

    affectations = [
        noeud
        for noeud in ast.walk(assembleurs[0])
        if isinstance(noeud, ast.Assign)
        and len(noeud.targets) == 1
        and isinstance(noeud.targets[0], ast.Name)
        and noeud.targets[0].id == "estimation"
        and isinstance(noeud.value, ast.Dict)
    ]
    assert len(affectations) == 1, (
        "extracteur statique nommé : affectation du dictionnaire estimation introuvable ou ambiguë"
    )

    cles = []
    for cle in affectations[0].value.keys:
        assert isinstance(cle, ast.Constant), (
            "extracteur statique nommé : clé du dictionnaire estimation non constante"
        )
        assert isinstance(cle.value, str), (
            "extracteur statique nommé : clé du dictionnaire estimation non textuelle"
        )
        cles.append(cle.value)

    assert set(cles) == set(contrats.CHAMPS_ESTIMATION_V1), (
        "clés littérales de estimation incompatibles avec CHAMPS_ESTIMATION_V1"
    )
