"""Tests M3-S001 — validation des entrées de M3-estimation (phase RED).

Le paquet ``m3_estimation`` n'existe pas encore : ces tests doivent ÉCHOUER à
l'import. Ils définissent le contrat que l'implémentation devra tenir :

- contrat LeadQualifie gelé à SEPT clés, ``urgence_declaree`` booléen strict ;
- marqueur de readiness M2 à CINQ clés, readiness constatée, jamais re-déduite ;
- photos fournies séparément par l'appelant (M2 n'en transporte aucune) ;
- neuf clés interdites traquées RÉCURSIVEMENT sur les trois entrées ;
- parcours récursif borné : REJ-PROFONDEUR-EXCESSIVE au-delà de la limite.
"""

import ast
import re
import sys
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Localisation du paquet sous test : insertion du src/ de M3-estimation dans
# sys.path, dérivée de Path(__file__) — JAMAIS depuis le répertoire courant.
# ---------------------------------------------------------------------------
_RACINE_M3 = Path(__file__).resolve().parents[1]
_SRC_M3 = _RACINE_M3 / "src"
if str(_SRC_M3) not in sys.path:
    sys.path.insert(0, str(_SRC_M3))

# Racine du dépôt : <racine>/Modules M/M3-estimation/tests/<ce fichier>.
_RACINE_DEPOT = Path(__file__).resolve().parents[3]

from m3_estimation import contrats
from m3_estimation import validation
from m3_estimation import verdicts

# ---------------------------------------------------------------------------
# Constantes épinglées par les tests — chaînes écrites en clair, jamais calculées
# ---------------------------------------------------------------------------
_EMPREINTE_VALIDE = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
_HASH_TETE_VALIDE = "fedcba9876543210fedcba9876543210fedcba9876543210fedcba9876543210"
# 64 caractères dont un 'g' final : non hexadécimale à longueur conservée.
_EMPREINTE_NON_HEXA_64 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdeg"
# 63 caractères hexadécimaux : longueur fautive isolée.
_EMPREINTE_HEXA_63 = "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcde"

_CLES_INTERDITES_EPINGLEES = [
    "prix",
    "montant",
    "date_execution",
    "engagement",
    "tva",
    "montant_ttc",
    "conditions_paiement",
    "creneau",
    "duree",
]

_TYPES_TRAVAUX_EPINGLES = [
    "renovation_totale",
    "extension",
    "ravalement",
    "isolation_thermique",
    "autre",
]

_CODES_EXERCES_PAR_CE_FICHIER = {
    "REJ-CLE-INTERDITE",
    "REJ-CONTRAT-INVALIDE",
    "REJ-MARQUEUR-INVALIDE",
    "REJ-READINESS-NON-CONSTATEE",
    "REJ-LEAD-ID-DISCORDANT",
    "REJ-PHOTOS-INVALIDES",
    "REJ-PROFONDEUR-EXCESSIVE",
}


# ---------------------------------------------------------------------------
# Fixtures — fonctions d'aide rendant des dictionnaires NEUFS à chaque appel
# ---------------------------------------------------------------------------
def _contrat_valide():
    """Retourne un contrat LeadQualifie valide, dictionnaire neuf à chaque appel."""
    return {
        "lead_id": "lead-0001",
        "conversation_id": "conv-0001",
        "type_travaux": "renovation_totale",
        "ville": "Lyon",
        "canal": "formulaire_web",
        "contact": {"nom": "Durand", "telephone": "0600000000"},
        "urgence_declaree": False,
    }


def _marqueur_valide():
    """Retourne un marqueur de readiness M2 valide, dictionnaire neuf à chaque appel."""
    return {
        "readiness_ok": True,
        "lead_id": "lead-0001",
        "hash_tete_registre": _HASH_TETE_VALIDE,
        "horodatage": "2025-01-15T10:30:00+00:00",
        "empreinte": _EMPREINTE_VALIDE,
    }


def _photos_valides():
    """Retourne une liste de photos structurellement valide, neuve à chaque appel."""
    return [
        {"id_photo": "ph-0001", "horodatage": "2025-01-15T10:31:00+00:00"},
        {"id_photo": "ph-0002", "horodatage": "2025-01-15T10:32:00+00:00"},
    ]


# ---------------------------------------------------------------------------
# Mutateurs CA-M3-02 — chacun part du valide et n'introduit QU'UNE faute
# ---------------------------------------------------------------------------
def _faute_cle_contrat_manquante(contrat, marqueur, photos):
    del contrat["canal"]
    return contrat, marqueur, photos


def _faute_cle_inconnue_contrat(contrat, marqueur, photos):
    contrat["cle_inconnue"] = "valeur"
    return contrat, marqueur, photos


def _faute_urgence_entier(contrat, marqueur, photos):
    contrat["urgence_declaree"] = 1
    return contrat, marqueur, photos


def _faute_type_travaux_hors_enumere(contrat, marqueur, photos):
    contrat["type_travaux"] = "peinture_interieure"
    return contrat, marqueur, photos


def _faute_ville_vide(contrat, marqueur, photos):
    contrat["ville"] = ""
    return contrat, marqueur, photos


def _faute_marqueur_absent(contrat, marqueur, photos):
    return contrat, None, photos


def _faute_marqueur_quatre_cles(contrat, marqueur, photos):
    del marqueur["horodatage"]
    return contrat, marqueur, photos


def _faute_readiness_chaine_true(contrat, marqueur, photos):
    marqueur["readiness_ok"] = "true"
    return contrat, marqueur, photos


def _faute_readiness_false(contrat, marqueur, photos):
    marqueur["readiness_ok"] = False
    return contrat, marqueur, photos


def _faute_empreinte_non_hexadecimale(contrat, marqueur, photos):
    marqueur["empreinte"] = _EMPREINTE_NON_HEXA_64
    return contrat, marqueur, photos


def _faute_empreinte_longueur_63(contrat, marqueur, photos):
    marqueur["empreinte"] = _EMPREINTE_HEXA_63
    return contrat, marqueur, photos


def _faute_horodatage_sans_fuseau(contrat, marqueur, photos):
    marqueur["horodatage"] = "2025-01-15T10:30:00"
    return contrat, marqueur, photos


def _faute_lead_id_discordant(contrat, marqueur, photos):
    marqueur["lead_id"] = "lead-9999"
    return contrat, marqueur, photos


_CAS_CA_M3_02 = [
    ("cle_contrat_manquante", _faute_cle_contrat_manquante, "REJ-CONTRAT-INVALIDE"),
    ("cle_inconnue_contrat", _faute_cle_inconnue_contrat, "REJ-CONTRAT-INVALIDE"),
    ("urgence_declaree_entier", _faute_urgence_entier, "REJ-CONTRAT-INVALIDE"),
    ("type_travaux_hors_enumere", _faute_type_travaux_hors_enumere, "REJ-CONTRAT-INVALIDE"),
    ("ville_vide", _faute_ville_vide, "REJ-CONTRAT-INVALIDE"),
    ("marqueur_absent", _faute_marqueur_absent, "REJ-MARQUEUR-INVALIDE"),
    ("marqueur_quatre_cles", _faute_marqueur_quatre_cles, "REJ-MARQUEUR-INVALIDE"),
    ("readiness_chaine_true", _faute_readiness_chaine_true, "REJ-READINESS-NON-CONSTATEE"),
    ("readiness_false", _faute_readiness_false, "REJ-READINESS-NON-CONSTATEE"),
    ("empreinte_non_hexadecimale", _faute_empreinte_non_hexadecimale, "REJ-MARQUEUR-INVALIDE"),
    ("empreinte_longueur_63", _faute_empreinte_longueur_63, "REJ-MARQUEUR-INVALIDE"),
    ("horodatage_sans_fuseau", _faute_horodatage_sans_fuseau, "REJ-MARQUEUR-INVALIDE"),
    ("lead_id_discordant", _faute_lead_id_discordant, "REJ-LEAD-ID-DISCORDANT"),
]


# ---------------------------------------------------------------------------
# Injecteurs CA-M3-22 — une clé interdite, un site d'injection à la fois
# ---------------------------------------------------------------------------
def _injecter_sommet_contrat(cle):
    contrat = _contrat_valide()
    contrat[cle] = "injecte"
    return contrat, _marqueur_valide(), _photos_valides()


def _injecter_sous_objet_contact(cle):
    contrat = _contrat_valide()
    contrat["contact"][cle] = "injecte"
    return contrat, _marqueur_valide(), _photos_valides()


def _injecter_marqueur(cle):
    marqueur = _marqueur_valide()
    marqueur[cle] = "injecte"
    return _contrat_valide(), marqueur, _photos_valides()


def _injecter_objet_photo(cle):
    photos = _photos_valides()
    photos[0][cle] = "injecte"
    return _contrat_valide(), _marqueur_valide(), photos


_SITES_INJECTION = [
    ("sommet_contrat", _injecter_sommet_contrat),
    ("sous_objet_contact", _injecter_sous_objet_contact),
    ("marqueur", _injecter_marqueur),
    ("objet_photo", _injecter_objet_photo),
]


# ---------------------------------------------------------------------------
# Épinglage des constantes exposées par contrats
# ---------------------------------------------------------------------------
def test_champs_contrat_gele_sept_cles_dans_l_ordre():
    """Prouve que CHAMPS_CONTRAT_GELE énumère les sept clés du contrat, dans l'ordre ratifié."""
    assert list(contrats.CHAMPS_CONTRAT_GELE) == [
        "lead_id",
        "conversation_id",
        "type_travaux",
        "ville",
        "canal",
        "contact",
        "urgence_declaree",
    ]


def test_champs_marqueur_cinq_cles():
    """Prouve que CHAMPS_MARQUEUR énumère les cinq clés du marqueur de readiness M2."""
    assert list(contrats.CHAMPS_MARQUEUR) == [
        "readiness_ok",
        "lead_id",
        "hash_tete_registre",
        "horodatage",
        "empreinte",
    ]


def test_types_travaux_valeurs_epinglees():
    """Prouve que TYPES_TRAVAUX contient exactement les cinq valeurs ratifiées, dans l'ordre."""
    assert list(contrats.TYPES_TRAVAUX) == _TYPES_TRAVAUX_EPINGLES


def test_cles_interdites_neuf_epinglees():
    """Prouve que CLES_INTERDITES contient exactement les neuf clés interdites ratifiées."""
    assert len(contrats.CLES_INTERDITES) == 9
    assert set(contrats.CLES_INTERDITES) == set(_CLES_INTERDITES_EPINGLEES)


# ---------------------------------------------------------------------------
# CA-M3-01 — l'acceptation
# ---------------------------------------------------------------------------
def test_ca_m3_01_acceptation_nominale():
    """CA-M3-01 : entrées valides -> (accusé, None), l'accusé portant les cinq champs ratifiés."""
    contrat = _contrat_valide()
    marqueur = _marqueur_valide()
    photos = _photos_valides()
    accuse, verdict = validation.valider_entrees(contrat, marqueur, photos)
    assert verdict is None
    assert isinstance(accuse, dict)
    assert set(accuse.keys()) == {
        "lead_id",
        "type_travaux",
        "ville",
        "empreinte_marqueur_m2",
        "nombre_photos",
    }
    assert accuse["lead_id"] == contrat["lead_id"]
    assert accuse["type_travaux"] == contrat["type_travaux"]
    assert accuse["ville"] == contrat["ville"]
    # L'empreinte de l'accusé est celle du MARQUEUR, jamais recalculée.
    assert accuse["empreinte_marqueur_m2"] == marqueur["empreinte"]
    assert accuse["nombre_photos"] == len(photos)


def test_ca_m3_01_contrat_accepte_est_celui_a_sept_cles():
    """CA-M3-01 : le contrat accepté est celui à SEPT clés, égal à CHAMPS_CONTRAT_GELE."""
    contrat = _contrat_valide()
    assert set(contrat.keys()) == set(contrats.CHAMPS_CONTRAT_GELE)
    assert len(contrats.CHAMPS_CONTRAT_GELE) == 7
    accuse, verdict = validation.valider_entrees(
        contrat, _marqueur_valide(), _photos_valides()
    )
    assert verdict is None
    assert accuse is not None


# ---------------------------------------------------------------------------
# CA-M3-02 — un cas par CLASSE de faute, chacun isolant SA faute
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "nom, mutateur, code_attendu",
    _CAS_CA_M3_02,
    ids=[cas[0] for cas in _CAS_CA_M3_02],
)
def test_ca_m3_02_une_faute_un_code(nom, mutateur, code_attendu):
    """CA-M3-02 : chaque classe de faute isolée produit exactement son code de verdict."""
    contrat, marqueur, photos = mutateur(
        _contrat_valide(), _marqueur_valide(), _photos_valides()
    )
    accuse, verdict = validation.valider_entrees(contrat, marqueur, photos)
    assert accuse is None, f"cas {nom} : un accusé ne devrait pas être produit"
    assert verdict is not None, f"cas {nom} : un verdict est attendu"
    assert verdict["code"] == code_attendu


def test_ca_m3_02_discordance_lead_id_dediee():
    """CA-M3-02 : un marqueur authentique signé pour un lead A ne passe pas avec le contrat d'un lead B."""
    contrat = _contrat_valide()
    marqueur = _marqueur_valide()
    marqueur["lead_id"] = "lead-autre-que-celui-du-contrat"
    accuse, verdict = validation.valider_entrees(contrat, marqueur, _photos_valides())
    assert accuse is None
    assert verdict is not None
    assert verdict["code"] == "REJ-LEAD-ID-DISCORDANT"


# ---------------------------------------------------------------------------
# CA-M3-22 — les clés interdites, RÉCURSIVEMENT et sur les TROIS entrées
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("cle", _CLES_INTERDITES_EPINGLEES)
@pytest.mark.parametrize(
    "nom_site, injecteur",
    _SITES_INJECTION,
    ids=[site[0] for site in _SITES_INJECTION],
)
def test_ca_m3_22_cle_interdite_recursive(cle, nom_site, injecteur):
    """CA-M3-22 : toute clé interdite, à tout niveau de toute entrée, produit REJ-CLE-INTERDITE."""
    contrat, marqueur, photos = injecteur(cle)
    accuse, verdict = validation.valider_entrees(contrat, marqueur, photos)
    assert accuse is None, f"site {nom_site}, clé {cle} : un accusé ne devrait pas être produit"
    assert verdict is not None, f"site {nom_site}, clé {cle} : un verdict est attendu"
    assert verdict["code"] == "REJ-CLE-INTERDITE"


def test_ca_m3_22_distinction_interdite_vs_inconnue():
    """CA-M3-22 : clé INTERDITE -> REJ-CLE-INTERDITE ; clé simplement INCONNUE -> REJ-CONTRAT-INVALIDE."""
    contrat_interdit = _contrat_valide()
    contrat_interdit["prix"] = "15000"
    accuse_interdit, verdict_interdit = validation.valider_entrees(
        contrat_interdit, _marqueur_valide(), _photos_valides()
    )
    assert accuse_interdit is None
    assert verdict_interdit is not None
    assert verdict_interdit["code"] == "REJ-CLE-INTERDITE"

    contrat_inconnu = _contrat_valide()
    contrat_inconnu["cle_tout_a_fait_inconnue"] = "valeur"
    accuse_inconnu, verdict_inconnu = validation.valider_entrees(
        contrat_inconnu, _marqueur_valide(), _photos_valides()
    )
    assert accuse_inconnu is None
    assert verdict_inconnu is not None
    assert verdict_inconnu["code"] == "REJ-CONTRAT-INVALIDE"


# ---------------------------------------------------------------------------
# CA-M3-03 — la readiness est CONSTATÉE, jamais re-déduite
# ---------------------------------------------------------------------------
def test_ca_m3_03_owner_et_interactions_rejetes():
    """CA-M3-03 : ajouter owner ou interactions au contrat le fait REJETER — M3 ne re-juge pas la readiness."""
    for cle in ("owner", "interactions"):
        contrat = _contrat_valide()
        contrat[cle] = "present"
        accuse, verdict = validation.valider_entrees(
            contrat, _marqueur_valide(), _photos_valides()
        )
        assert accuse is None, f"clé {cle} : un accusé ne devrait pas être produit"
        assert verdict is not None, f"clé {cle} : un verdict est attendu"
        assert verdict["code"] == "REJ-CONTRAT-INVALIDE"


def test_ca_m3_03_ancre_docstring_module_validation():
    """CA-M3-03 : la docstring du module validation porte l'ancre 'la readiness est constatée, jamais re-déduite'."""
    source = (_SRC_M3 / "m3_estimation" / "validation.py").read_text(encoding="utf-8")
    assert "la readiness est constatée, jamais re-déduite" in source


def test_ca_m3_03_ancre_catalogue_verdicts():
    """CA-M3-03 : le catalogue de verdicts porte l'ancre 'seul le registre hash-chaîné de M2 fait foi'."""
    source = (_SRC_M3 / "m3_estimation" / "verdicts.py").read_text(encoding="utf-8")
    assert "seul le registre hash-chaîné de M2 fait foi" in source


def test_ca_m3_03_aucun_hachage_dans_validation():
    """CA-M3-03 : le module validation ne contient ni hashlib ni sha256 — M3 ne recalcule jamais l'empreinte."""
    source = (_SRC_M3 / "m3_estimation" / "validation.py").read_text(encoding="utf-8")
    assert "hashlib" not in source
    assert "sha256" not in source


# ---------------------------------------------------------------------------
# Photos structurellement invalides
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    "photos_invalides",
    ["pas-une-liste", ["pas-un-dict"], [None]],
    ids=["photos_chaine", "element_chaine", "element_none"],
)
def test_photos_invalides(photos_invalides):
    """Une entrée photos qui n'est pas une liste de dictionnaires produit REJ-PHOTOS-INVALIDES."""
    accuse, verdict = validation.valider_entrees(
        _contrat_valide(), _marqueur_valide(), photos_invalides
    )
    assert accuse is None
    assert verdict is not None
    assert verdict["code"] == "REJ-PHOTOS-INVALIDES"


# ---------------------------------------------------------------------------
# Bornage du parcours récursif
# ---------------------------------------------------------------------------
def test_profondeur_excessive_bornee():
    """200 niveaux d'imbrication dans contact -> REJ-PROFONDEUR-EXCESSIVE, sans planter ni épuiser la pile."""
    contrat = _contrat_valide()
    profond = {}
    etage = profond
    for _ in range(200):
        etage["descente"] = {}
        etage = etage["descente"]
    contrat["contact"]["detail"] = profond
    accuse, verdict = validation.valider_entrees(
        contrat, _marqueur_valide(), _photos_valides()
    )
    assert accuse is None
    assert verdict is not None
    assert verdict["code"] == "REJ-PROFONDEUR-EXCESSIVE"


# ---------------------------------------------------------------------------
# Le catalogue est FERMÉ
# ---------------------------------------------------------------------------
def test_catalogue_ferme_refus_code_inconnu():
    """construire_verdict REFUSE tout code hors catalogue en levant une exception."""
    with pytest.raises(verdicts.CodeVerdictInconnu):
        verdicts.construire_verdict("REJ-CODE-QUI-N-EXISTE-PAS")


def test_codes_exerces_appartiennent_au_catalogue():
    """Tous les codes exercés par ce fichier appartiennent à CODES_M3_LIST."""
    assert _CODES_EXERCES_PAR_CE_FICHIER <= set(verdicts.CODES_M3_LIST)


# ---------------------------------------------------------------------------
# L'énuméré épinglé ne dérive pas — comparaison au source de M2 (fail-closed)
# ---------------------------------------------------------------------------
def test_contact_portant_les_trois_cles_de_m2_est_accepte():
    """Un contact portant les TROIS clés émises par M2 (nom, telephone, courriel) est accepté."""
    contrat = _contrat_valide()
    contrat["contact"] = {
        "nom": "Durand",
        "telephone": "0600000000",
        "courriel": "durand@example.com",
    }
    accuse, verdict = validation.valider_entrees(
        contrat, _marqueur_valide(), _photos_valides()
    )
    assert verdict is None, (
        "une liste blanche de contact dérivée des fixtures de test au lieu de la "
        "source du producteur M2 rejette un lead parfaitement légitime portant "
        "'courriel' — verdict inattendu : "
        f"{verdict}"
    )
    assert accuse is not None, (
        "une liste blanche de contact dérivée des fixtures de test au lieu de la "
        "source du producteur M2 rejette un lead parfaitement légitime portant "
        "'courriel' — aucun accusé produit"
    )


def test_ca_m3_02_lead_id_discordant_est_un_rejet_nomme():
    """CA-M3-02 : 'lead_id' du marqueur différent de celui du contrat -> REJ-LEAD-ID-DISCORDANT.

    Cette garde empêche qu'un marqueur AUTHENTIQUE signé pour un lead A soit
    présenté avec le contrat d'un lead B — une traçabilité transportée sans
    jamais être liée au lead qu'elle qualifie réellement.
    """
    contrat = _contrat_valide()
    marqueur = _marqueur_valide()
    marqueur["lead_id"] = "lead-9999"
    accuse, verdict = validation.valider_entrees(
        contrat, marqueur, _photos_valides()
    )
    assert accuse is None
    assert verdict is not None
    assert verdict["code"] == "REJ-LEAD-ID-DISCORDANT"




def _lire_chaines_litterales(valeur, chemin, nom_constante):
    """Lit les chaînes littérales d'un nœud tuple/liste/ensemble AST, fail-closed.

    Tout élément qui n'est pas un ``ast.Constant`` de type ``str`` fait
    ÉCHOUER le test en nommant la constante — on ne devine jamais ce que
    l'élément « voudrait dire ». Un conteneur vide fait également échouer :
    une constante vidée chez M2 ne doit pas passer en silence.
    """
    if not isinstance(valeur, (ast.Tuple, ast.List, ast.Set)):
        pytest.fail(
            f"constante {nom_constante} de {chemin} : valeur de type "
            f"{type(valeur).__name__}, tuple/liste/ensemble attendu — "
            f"on ne devine pas"
        )
    chaines = []
    for element in valeur.elts:
        if not (
            isinstance(element, ast.Constant)
            and isinstance(element.value, str)
        ):
            pytest.fail(
                f"constante {nom_constante} de {chemin} : élément "
                f"{ast.dump(element)} qui n'est pas une chaîne littérale — "
                f"on ne devine pas"
            )
        chaines.append(element.value)
    if not chaines:
        pytest.fail(
            f"constante {nom_constante} de {chemin} vide — fail-closed"
        )
    return chaines


def _constante_m2(chemin_relatif, nom_constante):
    """Extrait une constante de module du source M2 par AST, jamais par regex.

    Une capture textuelle (regex non ancrée, puis findall sur tout ce qui est
    entre guillemets) avale AUSSI les chaînes écrites dans les commentaires et
    docstrings à l'intérieur de la parenthèse : mesuré, une clé fantôme
    (« fantome », venue d'un commentaire ``# ex: "fantome"``) est entrée dans
    la comparaison. Le parseur AST ne produit de nœuds que pour la syntaxe
    réelle — un commentaire n'en produit aucun — donc seules les chaînes
    effectivement affectées sont lues.
    """
    chemin = _RACINE_DEPOT / chemin_relatif
    if not chemin.is_file():
        pytest.fail(
            f"extraction AST fail-closed : fichier M2 introuvable "
            f"{chemin} (constante {nom_constante})"
        )
    source = chemin.read_text(encoding="utf-8")
    try:
        arbre = ast.parse(source, filename=str(chemin))
    except (SyntaxError, ValueError) as erreur:
        pytest.fail(
            f"extraction AST fail-closed : {chemin} non parsable "
            f"(constante {nom_constante}) : {erreur}"
        )
    for noeud in arbre.body:
        if not isinstance(noeud, ast.Assign):
            continue
        if not any(
            isinstance(cible, ast.Name) and cible.id == nom_constante
            for cible in noeud.targets
        ):
            continue
        return _lire_chaines_litterales(noeud.value, chemin, nom_constante)
    pytest.fail(
        f"constante {nom_constante} introuvable au niveau module de "
        f"{chemin} — fail-closed, jamais de passage silencieux"
    )


def _cles_attendues_m2(chemin_relatif):
    """Extrait la variable LOCALE ``cles_attendues`` du readiness de M2, par AST.

    Les clés du marqueur ne sont pas une constante de module chez M2 :
    ``_constante_m2``, qui ne lit que le corps de module, ne les trouverait
    pas. Ce lecteur parcourt donc TOUS les nœuds ``ast.Assign`` du fichier
    (``ast.walk``) et retient le premier dont une cible s'appelle
    ``cles_attendues``. Fail-closed si la variable est introuvable.
    """
    chemin = _RACINE_DEPOT / chemin_relatif
    if not chemin.is_file():
        pytest.fail(
            f"extraction AST fail-closed : fichier M2 introuvable "
            f"{chemin} (variable cles_attendues)"
        )
    source = chemin.read_text(encoding="utf-8")
    try:
        arbre = ast.parse(source, filename=str(chemin))
    except (SyntaxError, ValueError) as erreur:
        pytest.fail(
            f"extraction AST fail-closed : {chemin} non parsable "
            f"(variable cles_attendues) : {erreur}"
        )
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.Assign):
            continue
        if not any(
            isinstance(cible, ast.Name) and cible.id == "cles_attendues"
            for cible in noeud.targets
        ):
            continue
        return _lire_chaines_litterales(noeud.value, chemin, "cles_attendues")
    pytest.fail(
        f"variable cles_attendues introuvable dans {chemin} — "
        f"fail-closed, jamais de passage silencieux"
    )


def test_types_travaux_copie_m2_ne_derive_pas():
    """TYPES_TRAVAUX de M3 est une copie exacte de celui de M2, extraite du source M2 par AST.

    L'extraction par AST — et non par regex non ancrée suivie d'un findall —
    garantit qu'aucun commentaire ni docstring à l'intérieur de la parenthèse
    n'injecte de clé fantôme dans la comparaison (défaut mesuré sur la
    version regex). La comparaison porte sur des LISTES ORDONNÉES : le
    commentaire de provenance annonce « dans l'ordre du producteur », et une
    comparaison d'ensembles ne le vérifierait pas — si l'ordre diverge, ce
    test le dit.
    """
    valeurs_m2 = _constante_m2(
        "Modules M/M2-revenue-crm/src/m2_revenue_crm/contrats.py",
        "TYPES_TRAVAUX",
    )
    assert list(contrats.TYPES_TRAVAUX) == valeurs_m2


def test_champs_contact_copie_m2_ne_derive_pas():
    """CHAMPS_CONTACT de M3 est une copie exacte de CLES_CONTACT de M2, extraite du source M2 par AST.

    Cette liste blanche se dérive du PRODUCTEUR, jamais des fixtures : sans ce
    test, une troncature de CHAMPS_CONTACT reste invisible parce que les
    fixtures ne fournissent qu'un sous-ensemble des clés réellement émises.
    L'extraction par AST exclut les chaînes des commentaires et docstrings —
    mesuré, une clé fantôme y est entrée par une capture textuelle. La
    comparaison est ORDONNÉE : le commentaire de provenance annonce « dans
    l'ordre du producteur », une comparaison d'ensembles ne le vérifierait
    pas, et si l'ordre diverge ce test le dit.
    """
    valeurs_m2 = _constante_m2(
        "Modules M/M2-revenue-crm/src/m2_revenue_crm/contrats.py",
        "CLES_CONTACT",
    )
    assert list(contrats.CHAMPS_CONTACT) == valeurs_m2


def test_champs_contrat_gele_copie_m2_ne_derive_pas():
    """CHAMPS_CONTRAT_GELE de M3 est une copie exacte de celle de M2, extraite du source M2 par AST.

    Comparaison en LISTES ORDONNÉES, comme pour TYPES_TRAVAUX et CLES_CONTACT.
    Note au relecteur : CLES_INTERDITES n'a VOLONTAIREMENT pas de test de
    non-dérive de ce genre — elle n'a aucune contrepartie chez M2, c'est une
    frontière PROPRE à M3 ratifiée par CA-M3-22 ; il ne faut pas chercher un
    test qui ne doit pas exister.
    """
    valeurs_m2 = _constante_m2(
        "Modules M/M2-revenue-crm/src/m2_revenue_crm/contrats.py",
        "CHAMPS_CONTRAT_GELE",
    )
    assert list(contrats.CHAMPS_CONTRAT_GELE) == valeurs_m2


def test_champs_marqueur_copie_m2_ne_derive_pas():
    """CHAMPS_MARQUEUR de M3 reflète ``cles_attendues`` du readiness de M2, extrait par AST.

    Les clés du marqueur ne sont PAS une constante de module chez M2 : c'est
    une variable LOCALE de ``readiness.py``, que ``_constante_m2`` (corps de
    module uniquement) ne trouverait pas — d'où l'extraction dédiée qui
    parcourt TOUS les nœuds ``ast.Assign`` du fichier. La source est un
    ``set`` : l'ordre n'y a pas de sens, la comparaison se fait donc en
    ENSEMBLES, à la différence des autres constantes confrontées en listes
    ordonnées — et cette docstring le dit.
    """
    cles_m2 = _cles_attendues_m2(
        "Modules M/M2-revenue-crm/src/m2_revenue_crm/readiness.py"
    )
    assert set(contrats.CHAMPS_MARQUEUR) == set(cles_m2)


def test_une_entree_legitime_maximale_reste_sous_les_bornes():
    """Verrouille les bornes défensives PROFONDEUR_MAX et NOEUDS_MAX par le BAS.

    Sans ce test, PROFONDEUR_MAX pourrait être resserré sous le besoin réel
    et rejeter des lots parfaitement légitimes, sans que rien ne le dise
    avant la production.
    """
    photos = [
        {
            "resolution": "4032x3024",
            "angle": "face",
            "eclairage": "naturel",
            "reference_echelle": {
                "objet": "porte_interieure",
                "dimension_cm": 203,
            },
        }
        for _ in range(20)
    ]
    accuse, verdict = validation.valider_entrees(
        _contrat_valide(), _marqueur_valide(), photos
    )
    assert verdict is None
    assert accuse is not None
    assert accuse["nombre_photos"] == 20
