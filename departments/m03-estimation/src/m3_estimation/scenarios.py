"""Incertitude et scénarios de prix de M3 (PLAN T4.11, DEFINITION-PRODUIT §7 M3.11 et M3.12).

« Prix et marge : minimum rentable, plages, scénarios prudent/normal/agressif. Jamais sous le minimum rentable sans
alerte rouge et validation de Nathan. » « Incertitude par Monte Carlo (P50, P80, facteurs dominants). » Ce module
ajoute à l'estimation ce que l'intervalle seul ne dit pas, en trois clés SŒURS d'``EstimationV1`` (le contrat gelé v1
ne change ni de clé ni de sens, P5) : ``distribution_cout``, ``facteurs_dominants`` et ``scenarios_prix``. Module pur
(ADR-0009, même règle que ``revue_devis.py``) : aucun import ``opsys``, aucune horloge, aucun accès réseau, aucun
fichier. Les taux et les seuils lui sont PASSÉS ; c'est ``outils.py``, seul, qui lit ``department.yaml``.

P50 et P80 du COÛT. Ils viennent de ``monte_carlo.simuler_quantiles`` : les MÊMES graine et tirages que l'intervalle
d'``EstimationV1`` (même générateur local, même loi, même tri, même convention de rang que la borne haute de
l'intervalle). Une seule simulation, deux lectures : P80 est la borne haute de l'intervalle à 60 %. Mêmes entrées,
mêmes montants, bit à bit. Un montant est un ``Decimal`` arrondi au cent, ``ROUND_HALF_UP``, comme le reste de M3.

Loi de chaque poste, dite poste par poste (``distribution_cout.postes``). PERT si le barème fournit
``cout_unitaire_mode`` pour le poste ; sinon UNIFORME entre ses bornes. Jamais un mode déduit. L'intervalle de
l'estimation suit la même loi (le tirage est celui de ``monte_carlo``) : P50, P80 et intervalle ne se contredisent pas.

Facteurs dominants (``facteurs_dominants``), par sensibilité, calcul EXACT et déterministe. Le coût d'un ouvrage est
la somme, sur les postes, de ``quantité x coût unitaire`` ; le coût unitaire d'un poste varie dans ses bornes, selon la
loi du poste. Les postes sont supposés INDÉPENDANTS (le barème ne déclare aucune corrélation) : la variance du coût
est la somme des variances des postes, chacune ``(quantité x étendue)² x k`` avec ``k = 1/12`` pour la loi uniforme et
``k = a x b / ((a + b)² x (a + b + 1))`` pour la bêta PERT (``a`` et ``b`` : ses deux paramètres, voir
``monte_carlo.POIDS_DU_MODE_PERT``). La part de variance d'un poste est sa variance sur le total : c'est l'indice de
sensibilité du premier ordre, exact pour une somme de postes indépendants, sans bruit de tirage. Le classement est par
part décroissante, puis par nom de poste (à égalité) ; aucun seuil de « dominance » n'est inventé, le rang et la part
sont des faits. Limite : une estimation d'aujourd'hui porte UN poste (le service demandé) ; le classement ne devient
informatif qu'avec plusieurs postes dans un même ouvrage, et la fonction le sait déjà faire.

Scénarios de prix (``scenarios_prix``) : prudent, normal, agressif. Le prix d'un scénario est
``coût de base x (1 + taux de marge)`` (``devis_durable.prix_depuis_cout``, LA formule de prix du paquet), arrondi au
cent. Le taux est FOURNI, jamais inventé : par l'appelant (``taux_marge_scenarios``) ou par la configuration
(``department.yaml``, ``configuration.scenarios_prix.taux_marge``), l'appel d'abord, scénario par scénario ; un taux
``null`` est un taux absent. Sans taux : aucun prix, et un verdict ``REJ-SCENARIOS-TAUX-ABSENT`` qui dit où le déclarer.
Un taux fourni de travers (non décimal, négatif, ``NaN``) donne ``REJ-SCENARIOS-TAUX-INVALIDE`` et aucun prix, et ne
retombe jamais sur l'autre source. Un taux négatif n'est pas un scénario : vendre sous le coût est une décision du
propriétaire, pas une proposition du système. Le coût de base est une POLITIQUE énoncée, pas une mesure : le prudent
se prend sur P80 (le prix tient si le coût dérape), le normal et l'agressif sur P50 ; seul le taux les distingue. La
sortie annonce la base de chaque scénario (``base_cout``). À décider par Nathan (PLAN T4.11, GATE) : les taux, et
cette base.

Chaque scénario est confronté au minimum rentable par le mécanisme de motifs de la revue de T4.7 (``revue_devis``),
appelé tel quel sur un devis fictif au prix et au taux du scénario : sous le minimum, alerte rouge et le motif
``PRIX_SOUS_MINIMUM_RENTABLE`` que la revue N4 montrera à l'envoi du devis réel (mêmes code, gravité, donnée et
seuil). Le minimum est ``configuration.revue_devis.minimum_rentable_cad`` de ``department.yaml``, VIDE à dessein : vide
ou invalide, la confrontation est « non évaluable » (``alerte_rouge`` vaut ``None``, jamais ``False``) et dit quoi
déclarer, une seule fois pour les trois scénarios. Comparaison stricte : un prix exactement au minimum ne déclenche
rien. Le montant maximal et la marge minimale de la revue se jugent sur le devis réel, à l'envoi (T4.7), pas ici.

Ce module ne persiste rien : la simulation est déterministe (barème, quantité, graine) et les taux sont rejoués à
chaque appel. Il ne publie aucun événement et n'envoie rien : un scénario est une proposition, jamais un engagement
(N4).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from . import devis_durable, monte_carlo, revue_devis, verdicts

__all__ = [
    "CHAMPS_DISTRIBUTION_COUT",
    "CHAMPS_FACTEUR_DOMINANT",
    "CHAMPS_LOI_DU_POSTE",
    "CHAMPS_SCENARIO",
    "CHAMPS_SCENARIOS_PRIX",
    "CHAMPS_SOEURS_ESTIMATION",
    "distribution_du_cout",
    "evaluer",
    "facteurs_dominants",
    "scenarios_de_prix",
]

# Les trois clés sœurs d'``EstimationV1`` que ce module produit (la réponse de l'orchestrateur les porte à côté de
# ``estimation``, jamais dedans). Fermé : la clé d'une réponse qui n'y figure pas n'est pas de ce module.
CHAMPS_SOEURS_ESTIMATION = ("distribution_cout", "facteurs_dominants", "scenarios_prix")

# Les clés de chaque objet rendu, dans l'ordre. Fermées : aucune clé en plus, aucune en moins.
CHAMPS_DISTRIBUTION_COUT = ("tirages", "graine", "p50", "p80", "postes")
CHAMPS_LOI_DU_POSTE = ("poste", "loi", "mode", "raison")
CHAMPS_FACTEUR_DOMINANT = ("rang", "poste", "amplitude", "part_variance")
CHAMPS_SCENARIOS_PRIX = ("scenarios", "alerte_rouge", "non_evaluables")
CHAMPS_SCENARIO = (
    "scenario", "base_cout", "cout", "taux_marge", "source_taux", "prix", "alerte_rouge", "motifs", "verdict",
)

_CENT = Decimal("0.01")
_QUATRE_DECIMALES = Decimal("0.0001")

# P50 et P80 : les deux probabilités que lit le module (une constante par nom, pas une liste : un énuméré de domaine
# est une liste qui porte une échappatoire, et ces deux nombres n'en sont pas un).
_PROBABILITE_P50 = 0.5
_PROBABILITE_P80 = 0.8

# Les trois scénarios, dans l'ordre où ils sont rendus, et la base de coût de chacun (politique énoncée, voir la
# docstring du module). Des étiquettes fixes d'un tableau, pas une classification d'une mesure incertaine : aucun
# scénario « indéterminé » n'existe, un scénario sans taux est une absence déclarée.
_BASE_DE_COUT = {"prudent": "P80", "normal": "P50", "agressif": "P50"}

_LOI_UNIFORME = "uniforme"
_LOI_PERT = "PERT"
_SOURCE_APPEL = "appel"
_SOURCE_CONFIGURATION = "configuration"
_ARGUMENT_TAUX = "taux_marge_scenarios"
_CLE_TAUX_CONFIGURATION = "configuration.scenarios_prix.taux_marge"


def _montant(valeur: Any) -> Decimal:
    """Un montant au cent, ``ROUND_HALF_UP`` (jamais l'arrondi bancaire). Un flottant passe par sa représentation
    DÉCIMALE (``str(0.1)`` donne ``0.1``), jamais par son codage binaire : même règle que ``arrondir_au_cent``."""
    return Decimal(str(valeur)).quantize(_CENT, rounding=ROUND_HALF_UP)


def _est_quantite(valeur: Any) -> bool:
    """Un nombre fini strictement positif, jamais un booléen (``isinstance(True, int)`` est vrai)."""
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        return False
    return Decimal(str(valeur)).is_finite() and valeur > 0


def _refus(detail: str) -> dict[str, str]:
    return verdicts.construire_verdict("REJ-CONTRAT-INVALIDE", detail)


# ---------------------------------------------------------------------------------------- P50 et P80 du coût
def _loi_du_poste(poste: str, parametres: dict[str, Any]) -> dict[str, Any]:
    """La loi retenue pour UN poste, et pourquoi : PERT s'il a un mode dans le barème, sinon uniforme."""
    mode = parametres["mode"]
    if mode is None:
        return {
            "poste": poste, "loi": _LOI_UNIFORME, "mode": None,
            "raison": "aucun cout_unitaire_mode dans le barème : tirage uniforme entre les bornes du poste",
        }
    return {
        "poste": poste, "loi": _LOI_PERT, "mode": _montant(mode),
        "raison": "cout_unitaire_mode fourni par le barème : tirage PERT",
    }


def distribution_du_cout(
    bareme: Any, type_travaux: Any, quantite: Any, graine: Any, services: tuple[str, ...] = ()
) -> tuple[dict[str, Any] | None, dict | None]:
    """P50 et P80 du coût de l'ouvrage, sur les MÊMES graine et tirages que l'intervalle de l'estimation.

    Rend ``(distribution, None)`` ou ``(None, verdict)`` : ``distribution`` porte ``CHAMPS_DISTRIBUTION_COUT``
    (``tirages``, ``graine``, ``p50`` et ``p80`` en ``Decimal`` au cent, ``postes`` : la loi de chaque poste). Les
    refus sont ceux du Monte Carlo (barème, poste, quantité, graine, mode fournis de travers), dans le même ordre."""
    parametres, verdict = monte_carlo.lire_poste(bareme, type_travaux, services)
    if verdict is not None:
        return None, verdict
    valeurs, verdict = monte_carlo.simuler_quantiles(
        bareme, type_travaux, quantite, graine, (_PROBABILITE_P50, _PROBABILITE_P80), services=services
    )
    if verdict is not None:
        return None, verdict
    p50, p80 = valeurs
    return {
        "tirages": monte_carlo.NOMBRE_TIRAGES,
        "graine": graine,
        "p50": _montant(p50),
        "p80": _montant(p80),
        "postes": [_loi_du_poste(type_travaux, parametres)],
    }, None


# -------------------------------------------------------------------------------------- facteurs dominants
def _coefficient_de_variance(parametres: dict[str, Any]) -> Decimal:
    """``k`` tel que variance du coût d'un poste = ``(quantité x étendue)² x k`` : ``1/12`` pour l'uniforme,
    ``a x b / ((a + b)² x (a + b + 1))`` pour la bêta PERT (``a`` et ``b`` valent ``1 + poids x distance au mode /
    étendue``, donc ``a + b = 2 + poids``). Un coût fixe (étendue nulle) ne varie pas : ``0``."""
    mode = parametres["mode"]
    if mode is None:
        return Decimal(1) / Decimal(12)
    cout_min = Decimal(str(parametres["cout_min"]))
    cout_max = Decimal(str(parametres["cout_max"]))
    etendue = cout_max - cout_min
    if etendue == 0:
        return Decimal(0)
    poids = Decimal(str(monte_carlo.POIDS_DU_MODE_PERT))
    forme_a = 1 + poids * (Decimal(str(mode)) - cout_min) / etendue
    forme_b = 1 + poids * (cout_max - Decimal(str(mode))) / etendue
    somme = forme_a + forme_b
    return forme_a * forme_b / (somme * somme * (somme + 1))


def facteurs_dominants(
    bareme: Any, quantites: Any, services: tuple[str, ...] = ()
) -> tuple[list[dict[str, Any]] | None, dict | None]:
    """Quels postes du barème font le plus varier le coût : leur part de variance, exacte, classée.

    ``quantites`` : ``{poste: quantité}`` (un poste par entrée, quantité finie strictement positive). Rend
    ``(facteurs, None)`` ou ``(None, verdict)`` : ``facteurs`` est la liste de ``CHAMPS_FACTEUR_DOMINANT`` (``rang``
    à partir de 1, ``poste``, ``amplitude`` : ``quantité x (borne haute - borne basse)`` en ``Decimal`` au cent,
    ``part_variance`` : part de la variance totale, ``Decimal`` à quatre décimales), du plus au moins dominant. Quand
    aucun poste ne varie (coûts fixes), la variance totale est nulle : ``part_variance`` vaut ``None``, jamais une
    part inventée. Les parts, arrondies une à une, somment à un à l'arrondi près."""
    if not isinstance(quantites, dict) or not quantites:
        return None, _refus("quantités des postes : dictionnaire non vide {poste: quantité} exigé")

    lignes = []
    for poste in sorted(quantites, key=str):
        quantite = quantites[poste]
        if not _est_quantite(quantite):
            return None, _refus(f"quantité du poste {poste!r} : nombre fini strictement positif exigé")
        parametres, verdict = monte_carlo.lire_poste(bareme, poste, services)
        if verdict is not None:
            return None, verdict
        etendue = Decimal(str(parametres["cout_max"])) - Decimal(str(parametres["cout_min"]))
        amplitude = Decimal(str(quantite)) * etendue
        lignes.append((poste, amplitude, amplitude * amplitude * _coefficient_de_variance(parametres)))

    total = sum((variance for _, _, variance in lignes), Decimal(0))
    classement = sorted(lignes, key=lambda ligne: (-ligne[2], str(ligne[0])))
    facteurs = []
    for rang, (poste, amplitude, variance) in enumerate(classement, start=1):
        part = None if total == 0 else (variance / total).quantize(_QUATRE_DECIMALES, rounding=ROUND_HALF_UP)
        facteurs.append({"rang": rang, "poste": poste, "amplitude": _montant(amplitude), "part_variance": part})
    return facteurs, None


# ------------------------------------------------------------------------------------ scénarios de prix
def _probleme_de_declarations(nom: str, declarations: Any) -> str | None:
    """Le problème d'une déclaration de taux qui n'est ni ``None`` ni un objet aux clés de scénarios connus."""
    if declarations is None:
        return None
    if not isinstance(declarations, dict):
        return f"{nom} : objet {{prudent, normal, agressif}} exigé (ou null)"
    inconnues = sorted((cle for cle in declarations if cle not in _BASE_DE_COUT), key=str)
    if inconnues:
        return f"{nom} : scénario(s) inconnu(s) {inconnues} (attendus : {list(_BASE_DE_COUT)})"
    return None


def _lire_taux(brut: Any, tolere_un_nombre: bool) -> tuple[Decimal | None, str | None]:
    """``(taux, None)`` ou ``(None, problème)``. Un taux d'appel est un TEXTE décimal (jamais un nombre JSON, comme
    ``taux_marge``) ; un taux de configuration peut être un nombre YAML (``0.35``), lu tel qu'écrit. Même validation
    que ``taux_marge`` (``devis_durable.texte_vers_taux_marge``), plus : jamais négatif."""
    if tolere_un_nombre and isinstance(brut, (int, float)) and not isinstance(brut, bool):
        brut = str(brut)
    taux, verdict = devis_durable.texte_vers_taux_marge(brut)
    if verdict is not None:
        return None, verdict["detail"]
    if taux < 0:
        return None, (
            f"taux de marge négatif ({taux}) : vendre sous le coût n'est pas un scénario, "
            "c'est une décision du propriétaire"
        )
    return taux, None


def _declarer(nom: str, brut: Any, source: str) -> tuple[Decimal | None, dict | None]:
    """``(taux, None)`` ou ``(None, verdict)`` pour UN taux déclaré par ``source``."""
    taux, probleme = _lire_taux(brut, tolere_un_nombre=source == _SOURCE_CONFIGURATION)
    if probleme is not None:
        return None, verdicts.construire_verdict(
            "REJ-SCENARIOS-TAUX-INVALIDE", f"scénario « {nom} » ({source}) : {probleme}"
        )
    return taux, None


def _resoudre_taux(
    nom: str, taux_appel: dict | None, taux_configures: dict | None, probleme_configuration: str | None
) -> tuple[Decimal | None, str | None, dict | None]:
    """``(taux, source, None)`` ou ``(None, None, verdict)``. L'appel d'abord, puis la configuration, scénario par
    scénario ; ``null`` vaut absent. Un taux fourni de travers n'est JAMAIS remplacé par celui de l'autre source, et une
    configuration inutilisable (pas un objet, scénario inconnu) ne donne aucun taux, jamais un taux deviné : elle est
    dite, scénario par scénario, sans empêcher l'estimation ni les scénarios que l'appel a déclarés."""
    brut = None if taux_appel is None else taux_appel.get(nom)
    if brut is not None:
        taux, verdict = _declarer(nom, brut, _SOURCE_APPEL)
        return taux, (_SOURCE_APPEL if verdict is None else None), verdict
    if probleme_configuration is not None:
        return None, None, verdicts.construire_verdict(
            "REJ-SCENARIOS-TAUX-INVALIDE", f"scénario « {nom} » ({_SOURCE_CONFIGURATION}) : {probleme_configuration}"
        )
    brut = None if taux_configures is None else taux_configures.get(nom)
    if brut is not None:
        taux, verdict = _declarer(nom, brut, _SOURCE_CONFIGURATION)
        return taux, (_SOURCE_CONFIGURATION if verdict is None else None), verdict
    return None, None, verdicts.construire_verdict(
        "REJ-SCENARIOS-TAUX-ABSENT",
        f"taux de marge non déclaré : {_ARGUMENT_TAUX}.{nom} ou department.yaml {_CLE_TAUX_CONFIGURATION}.{nom}",
    )


def _confronter_au_minimum_rentable(
    devis_id: Any, prix: Decimal, taux: Decimal, seuils_revue: Any
) -> tuple[list[dict[str, Any]] | None, list[dict[str, Any]] | None, dict | None]:
    """``(motifs, non_evaluables, None)`` ou ``(None, None, verdict)`` : la revue de T4.7 sur un devis fictif au prix et
    au taux du scénario, réduite au seul critère du minimum rentable. Les autres critères (confiance, distance, montant
    maximal, marge minimale...) se jugent sur le devis réel, à l'envoi."""
    revue, verdict = revue_devis.evaluer_revue(
        {"devis_id": devis_id, "prix_total": prix, "taux_marge": taux}, None, seuils_revue
    )
    if verdict is not None:
        return None, None, verdict
    code = revue_devis.PRIX_SOUS_MINIMUM_RENTABLE
    motifs = [motif for motif in revue["motifs"] if motif["code"] == code]
    manques = [manque for manque in revue["non_evaluables"] if manque["code"] == code]
    return motifs, manques, None


def scenarios_de_prix(
    distribution: dict[str, Any], devis_id: Any, taux_appel: Any, taux_configures: Any, seuils_revue: Any
) -> tuple[dict[str, Any] | None, dict | None]:
    """Les trois scénarios de prix (prudent, normal, agressif), confrontés au minimum rentable.

    ``distribution`` : ``distribution_du_cout`` (``p50`` et ``p80`` en ``Decimal``). ``taux_appel`` et
    ``taux_configures`` : ``None`` ou ``{scénario: taux}`` (voir la docstring du module). ``seuils_revue`` :
    ``configuration.revue_devis`` de ``department.yaml``, tel que lu (``None`` s'il est absent). ``devis_id`` : celui de
    l'estimation, pour la revue.

    Rend ``(section, None)`` ou ``(None, verdict)`` (``taux_appel`` mal formé : refusé en bloc ; une ``taux_configures``
    mal formée, elle, est dite scénario par scénario et n'empêche rien d'autre). ``section`` porte
    ``CHAMPS_SCENARIOS_PRIX`` : ``scenarios`` (trois entrées de ``CHAMPS_SCENARIO``, dans l'ordre prudent, normal,
    agressif), ``alerte_rouge`` (vrai dès qu'un scénario chiffré est sous le minimum ; faux si tous les scénarios
    chiffrés ont été jugés et aucun ne l'est ; ``None`` sinon) et ``non_evaluables`` (ce qui empêche de juger, dit
    une fois).
    Dans une entrée : ``prix``, ``taux_marge`` et ``source_taux`` valent ``None`` sans taux valide, avec un ``verdict``
    qui dit quoi déclarer ; ``alerte_rouge`` vaut ``None`` quand le minimum ne peut pas être jugé."""
    probleme = _probleme_de_declarations(_ARGUMENT_TAUX, taux_appel)
    if probleme is not None:
        return None, _refus(probleme)
    probleme_configuration = _probleme_de_declarations(_CLE_TAUX_CONFIGURATION, taux_configures)

    entrees = []
    non_evaluables: list[dict[str, Any]] = []
    for nom, base in _BASE_DE_COUT.items():
        cout = distribution["p80"] if base == "P80" else distribution["p50"]
        entree: dict[str, Any] = {
            "scenario": nom, "base_cout": base, "cout": cout, "taux_marge": None, "source_taux": None,
            "prix": None, "alerte_rouge": None, "motifs": [], "verdict": None,
        }
        entrees.append(entree)
        taux, source, verdict = _resoudre_taux(nom, taux_appel, taux_configures, probleme_configuration)
        if verdict is not None:
            entree["verdict"] = verdict
            continue
        entree["taux_marge"] = taux
        entree["source_taux"] = source
        entree["prix"] = devis_durable.prix_depuis_cout(cout, taux)
        motifs, manques, verdict = _confronter_au_minimum_rentable(devis_id, entree["prix"], taux, seuils_revue)
        if verdict is not None:
            return None, verdict
        entree["motifs"] = motifs
        entree["alerte_rouge"] = None if manques else bool(motifs)
        non_evaluables.extend(manque for manque in manques if manque not in non_evaluables)

    jugees = [entree["alerte_rouge"] for entree in entrees if entree["prix"] is not None]
    if any(alerte is True for alerte in jugees):
        alerte_rouge: bool | None = True
    elif jugees and all(alerte is False for alerte in jugees):
        alerte_rouge = False
    else:
        alerte_rouge = None
    return {"scenarios": entrees, "alerte_rouge": alerte_rouge, "non_evaluables": non_evaluables}, None


# --------------------------------------------------------------------------------------------- l'ensemble
def evaluer(
    bareme: Any, type_travaux: Any, quantite: Any, graine: Any, devis_id: Any, taux_appel: Any = None,
    taux_configures: Any = None, seuils_revue: Any = None, services: tuple[str, ...] = (),
) -> tuple[dict[str, Any] | None, dict | None]:
    """Les trois clés sœurs d'``EstimationV1`` : ``distribution_cout``, ``facteurs_dominants`` et ``scenarios_prix``.

    Rend ``({clé sœur: valeur}, None)`` ou ``(None, verdict)`` ; les clés sont exactement ``CHAMPS_SOEURS_ESTIMATION``.
    Le poste demandé est l'unique poste de l'estimation : il porte toute la variance (voir la docstring du module)."""
    distribution, verdict = distribution_du_cout(bareme, type_travaux, quantite, graine, services)
    if verdict is not None:
        return None, verdict
    facteurs, verdict = facteurs_dominants(bareme, {type_travaux: quantite}, services)
    if verdict is not None:
        return None, verdict
    section, verdict = scenarios_de_prix(distribution, devis_id, taux_appel, taux_configures, seuils_revue)
    if verdict is not None:
        return None, verdict
    return {"distribution_cout": distribution, "facteurs_dominants": facteurs, "scenarios_prix": section}, None
