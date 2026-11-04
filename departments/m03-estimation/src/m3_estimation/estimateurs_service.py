"""ESTIMATEURS PAR SERVICE (M3.8b) : la quantité d'un service est composée de mesures DÉCLARÉES.

Le barème déclaré (M3-C1) portait **un** coût unitaire par service ; la mesure déclarée (M3-C2) portait **une**
quantité. Un service réel ne se mesure pas d'un seul nombre : une gouttière se compose d'une longueur de bordure,
de descentes, de coins ; un revêtement se compose d'une surface brute MOINS ses ouvertures ; une réparation a un
minimum facturable et un temps minimum. Ce module ajoute la composition, sans jamais inventer ni formule chiffrée
ni coefficient :

- la STRUCTURE de l'estimateur est déclarée dans ``parametres.estimateurs.<service>`` de la version de barème
  (``bareme_registre._valider_estimateurs``) : unité de l'ouvrage, liste ordonnée de composantes, minimum de
  quantité et temps minimum facultatifs ;
- chaque COMPOSANTE porte sa ``grandeur`` (le code que la mesure d'une personne doit nommer), son unité, un
  ``coefficient`` SIGNÉ (positif : ajout ; négatif : soustraction, par exemple les ouvertures d'un mur), un
  ``facteur_conversion`` obligatoire seulement si son unité diffère de celle de l'ouvrage (aucune conversion
  devinée) et une ``source_ecrite`` obligatoire (document, date, auteur) ;
- les QUANTITÉS sont lues dans les mesures déclarées, jamais dans un argument : une mesure par grandeur, du même
  lead et du même service, jugée par ``mesure_declaree.evaluer`` (unité, péremption, bornes trop larges) avant tout
  calcul.

FORMULE (versionnée par ``FORMULE``) ::

    contribution_i = coefficient_i x facteur_conversion_i x valeur_i
    quantite_retenue = max(Σ contribution_i, quantite_minimum déclaré)
    quantite_basse   = max(Σ min(coefficient_i x conversion_i x borne_basse_i,
                                 coefficient_i x conversion_i x borne_haute_i), quantite_minimum)
    quantite_haute   = max(Σ max(...), quantite_minimum)

Un coefficient négatif inverse les bornes de SA composante : la borne basse du total prend la borne HAUTE de la
soustraction, sinon l'intervalle mentirait. Les montants sont calculés en ``Decimal`` et arrondis au cent
``ROUND_HALF_UP`` (même règle que M5 et ``devis_durable.prix_depuis_cout``) : le coût minimal multiplie la quantité
basse par le coût unitaire minimal, le maximal la quantité haute par le coût maximal ; le coût probable et le prix
recommandé ne sont calculés QUE si le mode et le taux de marge normal sont déclarés, sinon ils restent ``None`` avec
la liste de ce qu'il faut déclarer.

REÇU DE CALCUL : ``recu`` porte la référence exacte du barème, chaque mesure (id, révision, empreinte), chaque
coefficient et sa source, les contributions et les bornes, les coûts unitaires, les arrondis, le résultat et une
empreinte SHA-256. ``verifier_recu`` refait l'arithmétique depuis les entrées enregistrées et vérifie l'empreinte :
il prouve la COHÉRENCE INTERNE du reçu, pas l'authenticité des registres (les empreintes de ceux-ci sont citées,
mais une chaîne entièrement réécrite par qui peut recalculer toutes les empreintes n'est pas détectée ici — même
limite assumée que ``bareme_registre`` et ``registre``).

FAIL-CLOSED : sans estimateur déclaré, sans une des mesures requises, avec une mesure en double ou non prévue, une
quantité nulle/négative, une borne basse de coût non positive, le module rend ``(None, verdict)`` ; le détail nomme
les clés à déclarer ou les grandeurs à mesurer, dans l'ordre de la déclaration. Aucune exception ne s'échappe.

Module pur (ADR-0009) : aucun import ``opsys``, aucune horloge (l'instant est un paramètre), aucun accès réseau.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from . import devis_durable, mesure_declaree, verdicts

__all__ = [
    "FORMULE",
    "MAX_COMPOSANTES",
    "estimateur",
    "estimer",
    "verifier_recu",
]

# Version de la formule ET de la forme du reçu : la changer rend les anciens reçus explicitement d'une autre version.
FORMULE = "m3-estimateur-service/1"
# Même borne que la déclaration du barème (un test la garde) : un estimateur à plus de seize composantes est une
# nomenclature, pas un estimateur de service.
MAX_COMPOSANTES = 16

_CENT = Decimal("0.01")
_CODE = re.compile(r"[A-Za-z0-9_.-]{1,64}")
_SOURCE_ID = re.compile(r"[0-9a-f]{64}")
_DECIMAL = re.compile(r"-?[0-9]{1,9}(?:\.[0-9]{1,6})?")
_CLES_COMPOSANTE = frozenset({"grandeur", "unite", "coefficient", "facteur_conversion", "source_ecrite"})
_CLES_COMPOSANTE_REQUISES = frozenset({"grandeur", "unite", "coefficient", "source_ecrite"})


class _Refus(Exception):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code} : {detail}")

    def verdict(self) -> dict:
        return verdicts.construire_verdict(self.code, detail=self.detail)


def _invalide(detail: str) -> _Refus:
    return _Refus("REJ-ESTIMATEUR-INVALIDE", detail)


def _texte_decimal(valeur: Decimal) -> str:
    """Un décimal exact en texte, sans notation scientifique ni zéro négatif."""
    if valeur == 0:
        return "0"
    return format(valeur.normalize(), "f")


def _montant(valeur: Decimal) -> str:
    return format(valeur.quantize(_CENT, rounding=ROUND_HALF_UP), "f")


def _decimal(texte: Any, champ: str) -> Decimal:
    if type(texte) is not str or _DECIMAL.fullmatch(texte) is None:
        raise _invalide(f"{champ} : un texte décimal est attendu")
    return Decimal(texte)


def _empreinte(recu: dict[str, Any]) -> str:
    contenu = {cle: valeur for cle, valeur in recu.items() if cle != "empreinte"}
    canonique = json.dumps(contenu, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonique.encode("utf-8")).hexdigest()


def _estimateur(version: dict[str, Any], service: str) -> dict[str, Any]:
    parametres = version.get("parametres")
    estimateurs = parametres.get("estimateurs") if isinstance(parametres, dict) else None
    estimateur = estimateurs.get(service) if isinstance(estimateurs, dict) else None
    if not isinstance(estimateur, dict):
        services = sorted(estimateurs) if isinstance(estimateurs, dict) else []
        raise _Refus(
            "REJ-ESTIMATEUR-NON-DECLARE",
            (
                f"la version {version.get('bareme_id')!r} ne déclare pas d'estimateur pour le service {service!r} "
                f"(services avec estimateur : {services}). À faire : le propriétaire déclare "
                f"parametres.estimateurs.{service} = {{unite_ouvrage, composantes: [{{grandeur, unite, coefficient, "
                "facteur_conversion (si l'unité diffère), source_ecrite}}], quantite_minimum?, "
                "temps_minimum_minutes?}. Chaque coefficient vient d'une source écrite ; aucune valeur n'est "
                "devinée ni fournie par le code"
            ),
        )
    if set(estimateur) - {"unite_ouvrage", "composantes", "quantite_minimum", "temps_minimum_minutes"}:
        raise _invalide("estimateur déclaré aux clés inattendues")
    composantes = estimateur.get("composantes")
    if (
        type(composantes) is not list or not 0 < len(composantes) <= MAX_COMPOSANTES
        or type(estimateur.get("unite_ouvrage")) is not str
    ):
        raise _invalide("estimateur déclaré incomplet : unite_ouvrage et composantes (1 à 16) sont requis")
    return estimateur


def estimateur(version: Any, service: Any) -> tuple[dict[str, Any] | None, dict | None]:
    """La déclaration d'estimateur d'un service, ou le refus qui dit la clé et la forme à déclarer.

    Publique pour que l'adaptateur vérifie la DÉCLARATION avant de résoudre les mesures : le refus le plus en amont
    (barème) est dit en premier, comme dans ``m3_estimer_projet``."""
    try:
        if type(version) is not dict or type(version.get("bareme_id")) is not str:
            raise _invalide("version : la version publique d'un barème déclaré est attendue")
        if type(service) is not str or _CODE.fullmatch(service) is None:
            raise _invalide("service : un code de service est attendu")
        return _estimateur(version, service), None
    except _Refus as refus:
        return None, refus.verdict()


def _indexer_mesures(
    mesures: Any, lead_id: str, service: str, grandeurs_admises: list[str],
) -> dict[str, dict[str, Any]]:
    if type(mesures) not in (list, tuple):
        raise _invalide("mesures : une liste de mesures déclarées est attendue")
    par_grandeur: dict[str, dict[str, Any]] = {}
    non_prevues: list[str] = []
    for mesure in mesures:
        if type(mesure) is not dict:
            raise _invalide("mesures : chaque mesure doit être un objet déclaré")
        for cle in ("mesure_id", "lead_id", "service", "grandeur", "valeur", "borne_basse", "borne_haute",
                    "unite", "methode", "confiance", "revision", "empreinte", "mesure_le"):
            if cle not in mesure:
                raise _invalide(f"mesures : une mesure ne porte pas {cle!r} (registre des mesures déclarées attendu)")
        if mesure["lead_id"] != lead_id:
            raise _Refus(
                "REJ-MESURE-AUTRE-LEAD",
                (
                    f"la mesure {mesure['mesure_id']!r} concerne un autre lead que celui de l'estimation : une mesure "
                    "ne se prête pas d'un chantier à l'autre. À faire : déclarer la mesure de CE chantier"
                ),
            )
        if mesure["service"] != service:
            raise _Refus(
                "REJ-MESURE-AUTRE-LEAD",
                (
                    f"la mesure {mesure['mesure_id']!r} porte sur le service {mesure['service']!r}, l'estimation sur "
                    f"{service!r} : déclarer la mesure de ce service"
                ),
            )
        grandeur = mesure["grandeur"]
        if grandeur not in grandeurs_admises:
            non_prevues.append(grandeur if type(grandeur) is str and _CODE.fullmatch(grandeur) else "?")
            continue
        if grandeur in par_grandeur:
            raise _Refus(
                "REJ-ESTIMATEUR-MESURE-AMBIGUE",
                (
                    f"deux mesures déclarent la grandeur {grandeur!r} pour ce service : une seule est admise par "
                    "grandeur (sinon le calcul choisirait en silence). À faire : n'en référencer qu'une, ou réviser "
                    "l'estimateur pour distinguer les grandeurs"
                ),
            )
        par_grandeur[grandeur] = mesure
    if non_prevues:
        nommees = sorted({g for g in non_prevues})
        raise _Refus(
            "REJ-ESTIMATEUR-MESURE-NON-PREVUE",
            (
                f"mesure(s) non prévue(s) par l'estimateur du service {service!r} : {nommees} ; grandeurs admises : "
                f"{sorted(grandeurs_admises)}. Une mesure non consommée n'est jamais ignorée en silence. À faire : "
                "retirer la mesure, ou déclarer sa grandeur dans l'estimateur avec son coefficient et sa source"
            ),
        )
    return par_grandeur


def _composantes(
    estimateur: dict[str, Any], par_grandeur: dict[str, dict[str, Any]], parametres_mesure: dict[str, Any],
    maintenant: datetime,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Évalue chaque mesure et calcule sa contribution ; rend les composantes et les motifs de revue."""
    manquantes = [
        composante["grandeur"] for composante in estimateur["composantes"]
        if composante.get("grandeur") not in par_grandeur
    ]
    if manquantes:
        raise _Refus(
            "REJ-ESTIMATEUR-MESURES-MANQUANTES",
            (
                f"il manque {len(manquantes)} mesure(s) déclarée(s) pour l'estimateur du service : {manquantes}. "
                "À faire : une personne déclare chaque mesure (m3_declarer_mesure : grandeur, valeur, unité, bornes "
                "basse et haute, méthode, confiance, pièces), puis rappeler l'outil avec leurs références"
            ),
        )
    calculees: list[dict[str, Any]] = []
    motifs: list[str] = []
    for composante in estimateur["composantes"]:
        if (
            type(composante) is not dict or not set(composante).issuperset(_CLES_COMPOSANTE_REQUISES)
            or set(composante) - _CLES_COMPOSANTE
        ):
            raise _invalide("une composante déclarée est mal formée (clés inconnues ou manquantes)")
        grandeur = composante["grandeur"]
        mesure = par_grandeur[grandeur]
        conversion_declaree = composante.get("facteur_conversion")
        if composante["unite"] == estimateur["unite_ouvrage"] and conversion_declaree is not None:
            raise _invalide(
                f"composantes[{grandeur}].facteur_conversion : interdit quand l'unité est celle de l'ouvrage"
            )
        if composante["unite"] != estimateur["unite_ouvrage"] and conversion_declaree is None:
            raise _invalide(
                f"composantes[{grandeur}].facteur_conversion : obligatoire quand l'unité diffère de l'ouvrage"
            )
        coefficient = _decimal(composante.get("coefficient"), f"composantes[{grandeur}].coefficient")
        if coefficient == 0:
            raise _invalide(f"composantes[{grandeur}].coefficient : un coefficient nul ne contribue à rien")
        if composante.get("unite") != mesure["unite"]:
            raise _Refus(
                "REJ-MESURE-UNITE",
                (
                    f"la mesure {mesure['mesure_id']!r} est en {mesure['unite']!r}, la composante {grandeur!r} attend "
                    f"{composante.get('unite')!r} : aucune conversion n'est devinée. À faire : déclarer la mesure dans "
                    "l'unité de la composante (ou réviser l'estimateur)"
                ),
            )
        conversion = Decimal("1")
        if "facteur_conversion" in composante:
            conversion = _decimal(composante["facteur_conversion"], f"composantes[{grandeur}].facteur_conversion")
            if conversion <= 0:
                raise _invalide(f"composantes[{grandeur}].facteur_conversion doit être strictement positif")
        evaluation, verdict = mesure_declaree.evaluer(
            mesure, unite_attendue=composante["unite"], parametres_mesure=parametres_mesure,
            maintenant=maintenant,
        )
        if verdict is not None:
            raise _Refus(verdict["code"], verdict["detail"])
        valeur = Decimal(evaluation["quantite"])
        basse = Decimal(evaluation["quantite_basse"])
        haute = Decimal(evaluation["quantite_haute"])
        facteur = coefficient * conversion
        contribution = facteur * valeur
        contribution_basse = min(facteur * basse, facteur * haute)
        contribution_haute = max(facteur * basse, facteur * haute)
        if evaluation["statut"] == "a_revoir":
            motifs.extend(evaluation["motifs_revue"])
        calculees.append({
            "grandeur": grandeur,
            "mesure_id": mesure["mesure_id"],
            "revision": mesure["revision"],
            "empreinte": mesure["empreinte"],
            "unite": mesure["unite"],
            "methode": mesure["methode"],
            "confiance": mesure["confiance"],
            "statut_mesure": evaluation["statut"],
            "valeur": evaluation["quantite"],
            "valeur_basse": evaluation["quantite_basse"],
            "valeur_haute": evaluation["quantite_haute"],
            "coefficient": composante["coefficient"],
            "facteur_conversion": composante.get("facteur_conversion", "1"),
            "contribution": _texte_decimal(contribution),
            "contribution_basse": _texte_decimal(contribution_basse),
            "contribution_haute": _texte_decimal(contribution_haute),
            "source_ecrite": composante.get("source_ecrite"),
            "_contribution": contribution,
            "_contribution_basse": contribution_basse,
            "_contribution_haute": contribution_haute,
        })
    return calculees, motifs


def _ligne_ouvrage(version: dict[str, Any], service: str) -> dict[str, Any]:
    lignes = version.get("lignes")
    if type(lignes) is not list:
        raise _invalide("version de barème sans lignes")
    ligne = next(
        (candidate for candidate in lignes
         if isinstance(candidate, dict) and candidate.get("service") == service
         and candidate.get("genre") == "ouvrage"),
        None,
    )
    if ligne is None:
        raise _Refus(
            "REJ-BAREME-INCOMPLET",
            (
                f"aucune ligne d'ouvrage pour le service {service!r} dans cette version de barème : sans coût "
                "unitaire, aucune estimation n'est chiffrée. À faire : le propriétaire déclare la ligne d'ouvrage "
                "(m3_declarer_bareme)"
            ),
        )
    return ligne


def _prix(probable: str | None, normal: Any) -> tuple[str | None, list[str]]:
    manquants: list[str] = []
    if normal is None:
        manquants.append(
            "taux_marge.normal non déclaré : le prix recommandé n'est pas calculé (le propriétaire le déclare dans "
            "parametres.taux_marge.normal)"
        )
    if probable is None or normal is None:
        return None, manquants
    taux = _decimal(normal, "parametres.taux_marge.normal")
    return _montant(devis_durable.prix_depuis_cout(Decimal(probable), taux)), manquants


def estimer(
    *, version: Any, service: Any, lead_id: Any, mesures: Any, maintenant: Any,
) -> tuple[dict[str, Any] | None, dict | None]:
    """Compose et chiffre l'estimation d'UN service à partir du barème déclaré et des mesures déclarées.

    Rend ``(resultat, None)`` : quantités basse/retenue/haute dans l'unité de l'ouvrage, coûts min/probable/max au
    cent, durée facultative, prix recommandé facultatif, statut de revue, éléments manquants et ``recu``.
    Rend ``(None, verdict)`` : toute entrée absente, périmée, mal formée ou toute quantité non positive."""
    try:
        if type(version) is not dict or type(version.get("bareme_id")) is not str:
            raise _invalide("version : la version publique d'un barème déclaré est attendue")
        if type(service) is not str or _CODE.fullmatch(service) is None:
            raise _invalide("service : un code de service est attendu")
        if type(lead_id) is not str or not lead_id:
            raise _invalide("lead_id : un identifiant de lead est attendu")
        if not isinstance(maintenant, datetime) or maintenant.tzinfo is None:
            raise _invalide("maintenant : un instant avec fuseau horaire est attendu")
        estimateur = _estimateur(version, service)
        parametres = version["parametres"]
        grandes_admises = [composante["grandeur"] for composante in estimateur["composantes"]]
        par_grandeur = _indexer_mesures(mesures, lead_id, service, grandes_admises)
        composantes, motifs = _composantes(
            estimateur, par_grandeur, parametres.get("mesure", {}), maintenant,
        )
        if not composantes:
            raise _invalide("aucune composante calculable")
        brut_basse = sum((c["_contribution_basse"] for c in composantes), Decimal("0"))
        brut_retenue = sum((c["_contribution"] for c in composantes), Decimal("0"))
        brut_haute = sum((c["_contribution_haute"] for c in composantes), Decimal("0"))
        # Une soustraction peut être plus grande que les ajouts : la quantité nulle ou négative est refusée, JAMAIS
        # ramenée à zéro (ce serait inventer un chantier).
        if brut_retenue <= 0:
            raise _Refus(
                "REJ-ESTIMATEUR-QUANTITE-NON-POSITIVE",
                (
                    f"la quantité composée vaut {_texte_decimal(brut_retenue)} {estimateur['unite_ouvrage']!r} : "
                    "nulle ou négative. À faire : vérifier les mesures et les coefficients déclarés (une soustraction "
                    "plus grande que les ajouts ne donne pas un chantier)"
                ),
            )
        minimum = estimateur.get("quantite_minimum")
        minimum_declare = None
        if minimum is not None:
            minimum_declare = _decimal(minimum, "quantite_minimum")
            if minimum_declare <= 0:
                raise _invalide("quantite_minimum doit être strictement positive")
        quantite_basse, quantite_retenue, quantite_haute = brut_basse, brut_retenue, brut_haute
        minimum_applique = False
        if minimum_declare is not None:
            minimum_applique = min(quantite_basse, quantite_retenue, quantite_haute) < minimum_declare
            quantite_basse = max(quantite_basse, minimum_declare)
            quantite_retenue = max(quantite_retenue, minimum_declare)
            quantite_haute = max(quantite_haute, minimum_declare)
        if quantite_basse <= 0:
            raise _Refus(
                "REJ-ESTIMATEUR-BORNES-NON-POSITIVES",
                (
                    f"la borne basse de la quantité vaut {_texte_decimal(quantite_basse)} "
                    f"{estimateur['unite_ouvrage']!r} : non positive, le coût minimal serait négatif. Aucun zéro "
                    "n'est inventé. À faire : resserrer les mesures des composantes soustraites (bornes plus "
                    "précises) ou réviser les coefficients déclarés"
                ),
            )
        ligne = _ligne_ouvrage(version, service)
        if ligne.get("unite") != estimateur["unite_ouvrage"]:
            raise _invalide(
                "l'unité de l'estimateur diffère de l'unité de la ligne d'ouvrage : aucun coût ne serait juste"
            )
        cout_min = Decimal(ligne["cout_unitaire_min"])
        cout_max = Decimal(ligne["cout_unitaire_max"])
        mode = ligne.get("cout_unitaire_mode")
        manquants: list[str] = []
        cout_probable = None
        if mode is not None:
            cout_probable = Decimal(mode)
        else:
            manquants.append(
                "cout_unitaire_mode non déclaré : le coût le plus probable n'est pas calculé (min et max restent "
                "disponibles ; le propriétaire déclare le mode dans la ligne d'ouvrage)"
            )
        couts = {
            "min_cad": _montant(quantite_basse * cout_min),
            "probable_cad": _montant(quantite_retenue * cout_probable) if cout_probable is not None else None,
            "max_cad": _montant(quantite_haute * cout_max),
            "unite_monetaire": "CAD",
            "arrondi": "ROUND_HALF_UP",
        }
        taux = parametres.get("taux_marge")
        normal = taux.get("normal") if isinstance(taux, dict) else None
        prix, prix_manquants = _prix(couts["probable_cad"], normal)
        manquants.extend(prix_manquants)
        duree_minutes = None
        duree_minimum_applique = False
        taux_minutes = ligne.get("duree_minutes_par_unite")
        if taux_minutes is not None:
            duree = quantite_retenue * Decimal(taux_minutes)
            temps_minimum = estimateur.get("temps_minimum_minutes")
            if temps_minimum is not None:
                minimum_temps = _decimal(temps_minimum, "temps_minimum_minutes")
                duree_minimum_applique = duree < minimum_temps
                duree = max(duree, minimum_temps)
            duree_minutes = _texte_decimal(duree)
        else:
            manquants.append(
                "duree_minutes_par_unite non déclarée : la durée de main-d'œuvre n'est pas calculée (le propriétaire "
                "la déclare dans la ligne d'ouvrage)"
            )
        recu: dict[str, Any] = {
            "formule": FORMULE,
            "service": service,
            "lead_id": lead_id,
            "bareme_ref": {
                "bareme_id": version["bareme_id"],
                "version": version.get("version"),
                "empreinte": version.get("empreinte"),
            },
            "unite_ouvrage": estimateur["unite_ouvrage"],
            "couts_unitaires": {
                "min": ligne["cout_unitaire_min"], "mode": mode, "max": ligne["cout_unitaire_max"],
            },
            "taux_marge_normal": normal,
            "composantes": [
                {cle: valeur for cle, valeur in composante.items() if not cle.startswith("_")}
                for composante in composantes
            ],
            "quantite": {
                "basse": _texte_decimal(quantite_basse), "retenue": _texte_decimal(quantite_retenue),
                "haute": _texte_decimal(quantite_haute), "unite": estimateur["unite_ouvrage"],
                "minimum_declare": minimum, "minimum_applique": minimum_applique,
            },
            "couts": couts,
            "duree": {
                "minutes": duree_minutes, "taux_minutes_par_unite": taux_minutes,
                "minimum_declare": estimateur.get("temps_minimum_minutes"),
                "minimum_applique": duree_minimum_applique,
            },
            "prix_recommande_cad": prix,
            "statut": "a_revoir" if motifs else "retenu",
            "motifs_revue": list(dict.fromkeys(motifs)),
            "elements_manquants": manquants,
        }
        recu["empreinte"] = _empreinte(recu)
        resultat = {
            "service": service,
            "lead_id": lead_id,
            "bareme_ref": copy.deepcopy(recu["bareme_ref"]),
            "unite_ouvrage": recu["unite_ouvrage"],
            "quantite": {cle: recu["quantite"][cle] for cle in ("basse", "retenue", "haute", "unite")},
            "couts": copy.deepcopy(recu["couts"]),
            "duree_minutes": recu["duree"]["minutes"],
            "prix_recommande_cad": recu["prix_recommande_cad"],
            "statut": recu["statut"],
            "motifs_revue": list(recu["motifs_revue"]),
            "elements_manquants": list(recu["elements_manquants"]),
            "recu": recu,
        }
        return resultat, None
    except _Refus as refus:
        return None, refus.verdict()
    except (KeyError, TypeError, ValueError, InvalidOperation, ArithmeticError):
        return None, verdicts.construire_verdict(
            "REJ-ESTIMATEUR-INVALIDE",
            detail=(
                "les entrées déclarées ne permettent pas un calcul exact : une valeur est absente, mal formée ou "
                "hors de la capacité de calcul (magnitude trop grande). À faire : vérifier les valeurs fournies, "
                "réduire leur magnitude ou découper l'estimation"
            ),
        )


def verifier_recu(recu: Any) -> tuple[bool, dict | None]:
    """Refait l'arithmétique du reçu depuis ses entrées enregistrées et vérifie son empreinte.

    Ne relit PAS les registres : c'est une vérification de cohérence interne, pas d'authenticité de la source. Un
    écart est nommé (composante ou champ) ; aucune correction silencieuse n'est faite."""
    def _refus(detail: str) -> tuple[bool, dict]:
        return False, verdicts.construire_verdict("REJ-ESTIMATEUR-RECU-ALTERE", detail=detail)

    try:
        if type(recu) is not dict:
            return _refus("le reçu n'est pas un objet")
        for cle in ("formule", "service", "lead_id", "bareme_ref", "unite_ouvrage", "couts_unitaires",
                    "composantes", "quantite", "couts", "duree", "prix_recommande_cad", "statut",
                    "motifs_revue", "elements_manquants", "empreinte"):
            if cle not in recu:
                return _refus(f"le reçu ne porte pas {cle!r}")
        if recu["formule"] != FORMULE:
            return _refus(f"formule {recu['formule']!r} inconnue ; ce vérificateur ne lit que {FORMULE!r}")
        if type(recu["empreinte"]) is not str or _SOURCE_ID.fullmatch(recu["empreinte"]) is None:
            return _refus("empreinte du reçu absente ou mal formée")
        composantes = recu["composantes"]
        if type(composantes) is not list or not composantes:
            return _refus("le reçu ne porte aucune composante")
        brut_basse = Decimal("0")
        brut_retenue = Decimal("0")
        brut_haute = Decimal("0")
        for index, composante in enumerate(composantes):
            try:
                facteur = _decimal(composante["coefficient"], "coefficient") * _decimal(
                    composante.get("facteur_conversion", "1"), "facteur_conversion")
                valeur = _decimal(composante["valeur"], "valeur")
                basse = _decimal(composante["valeur_basse"], "valeur_basse")
                haute = _decimal(composante["valeur_haute"], "valeur_haute")
                contribution = facteur * valeur
                contribution_basse = min(facteur * basse, facteur * haute)
                contribution_haute = max(facteur * basse, facteur * haute)
            except (_Refus, KeyError, TypeError, InvalidOperation):
                return _refus(f"composantes[{index}] : une valeur du reçu est absente ou mal formée")
            if _texte_decimal(contribution) != composante.get("contribution"):
                return _refus(
                    f"composantes[{index}] ({composante.get('grandeur')}) : la contribution enregistrée diffère du "
                    "produit coefficient x conversion x valeur"
                )
            if _texte_decimal(contribution_basse) != composante.get("contribution_basse"):
                return _refus(f"composantes[{index}] ({composante.get('grandeur')}) : borne basse incohérente")
            if _texte_decimal(contribution_haute) != composante.get("contribution_haute"):
                return _refus(f"composantes[{index}] ({composante.get('grandeur')}) : borne haute incohérente")
            brut_basse += contribution_basse
            brut_retenue += contribution
            brut_haute += contribution_haute
        quantite = recu["quantite"]
        minimum = quantite.get("minimum_declare")
        if minimum is not None:
            minimum_declare = _decimal(minimum, "minimum_declare")
            if minimum_declare <= 0:
                return _refus("quantite.minimum_declare doit être strictement positif")
            minimum_applique = min(brut_basse, brut_retenue, brut_haute) < minimum_declare
            brut_basse = max(brut_basse, minimum_declare)
            brut_retenue = max(brut_retenue, minimum_declare)
            brut_haute = max(brut_haute, minimum_declare)
        else:
            minimum_applique = False
        if (quantite.get("basse") != _texte_decimal(brut_basse)
                or quantite.get("retenue") != _texte_decimal(brut_retenue)
                or quantite.get("haute") != _texte_decimal(brut_haute)):
            return _refus("la quantité du reçu diffère de la somme recalculée des composantes")
        if quantite.get("minimum_applique") is not minimum_applique:
            return _refus("le drapeau minimum_applique du reçu est incohérent")
        couts = recu["couts"]
        unitaires = recu["couts_unitaires"]
        attendus = {
            "min_cad": _montant(brut_basse * Decimal(unitaires["min"])),
            "max_cad": _montant(brut_haute * Decimal(unitaires["max"])),
            "probable_cad": (
                _montant(brut_retenue * Decimal(unitaires["mode"])) if unitaires.get("mode") is not None else None
            ),
        }
        for cle, attendu in attendus.items():
            if couts.get(cle) != attendu:
                return _refus(f"couts.{cle} diffère du recalcul ({attendu!r} attendu)")
        prix = recu["prix_recommande_cad"]
        if prix is not None:
            normal = recu.get("taux_marge_normal")
            if normal is None or attendus["probable_cad"] is None:
                return _refus("un prix est enregistré sans coût probable ni taux de marge normal")
            recalcule = _montant(devis_durable.prix_depuis_cout(Decimal(attendus["probable_cad"]), Decimal(normal)))
            if prix != recalcule:
                return _refus("prix_recommande_cad diffère du recalcul coût probable x (1 + taux normal)")
        duree = recu["duree"]
        taux_minutes = duree.get("taux_minutes_par_unite")
        if taux_minutes is None:
            if duree.get("minutes") is not None:
                return _refus("une durée est enregistrée sans taux de minutes déclaré")
        else:
            attendue = brut_retenue * Decimal(taux_minutes)
            if duree.get("minimum_declare") is not None:
                minimum_temps = _decimal(duree["minimum_declare"], "temps_minimum_minutes")
                if (attendue < minimum_temps) is not duree.get("minimum_applique"):
                    return _refus("le drapeau minimum_applique de la durée est incohérent")
                attendue = max(attendue, minimum_temps)
            if duree.get("minutes") != _texte_decimal(attendue):
                return _refus("la durée du reçu diffère du recalcul quantité x minutes par unité")
        if _empreinte(recu) != recu["empreinte"]:
            return _refus("l'empreinte du reçu ne correspond pas à son contenu (un champ a été modifié)")
        return True, None
    except (AttributeError, KeyError, TypeError, ValueError, InvalidOperation, ArithmeticError):
        return _refus("le reçu est mal formé : une valeur absente ou non décimale empêche le recalcul")
