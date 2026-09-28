"""Capacités d'agent du département M5 FinanceCore.

Chaque outil enveloppe une fonction métier déterministe existante : aucune n'est
réécrite. Les montants sont TOUJOURS des Decimal construits depuis une
représentation textuelle (jamais un float JSON, qui importerait une imprécision
binaire dans un registre financier).

Le registre (mouvements et approbations, deux chaînes DISTINCTES, PRD §5.4) est en
mémoire pour la durée d'un appel : ce paquet ne possède aucune persistance (hors
périmètre, couche MCP/dashboard). L'appelant transmet l'historique renvoyé par le
précédent appel dans `mouvements_historique`/`approbations_historique` ; ce module
le rejoue via `Registre.ajouter` pour retrouver un registre valide et chaîné avant
d'y écrire la suite.

RÈGLE FINANCE (autonomie) : toute écriture financière (registre des mouvements) et
toute décision d'approbation sont T3 — une action qui engage ou meut de l'argent
n'est jamais autonome, quel que soit le mode du département. Créer une demande
d'approbation (sans la trancher) est une écriture de gouvernance interne, T1.
Lecture et calcul purs (état, taxes) sont T0.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from opsys.outils import Autonomie, Outil, depuis_couple

from . import approbation, etat_financier, registre as registre_module, taux_fiscaux, taxes, validation

_CHEMIN_TAUX_FISCAUX = Path(__file__).resolve().parents[2] / "contracts" / "taux_fiscaux.v1.yaml"

_MAILLON = {"type": "object", "description": "Maillon tel que renvoyé par un appel précédent."}
_HISTORIQUE = {
    "type": "array",
    "items": _MAILLON,
    "description": "Historique renvoyé par le dernier appel connu ; [] ou omis si aucun.",
}
_MONTANT_TEXTE = {
    "type": "string",
    "description": "Montant décimal en texte, ex. \"125.00\" — jamais un nombre JSON (imprécision binaire).",
}
_TYPE_MOUVEMENT = {"type": "string", "enum": ["ENCAISSEMENT", "DECAISSEMENT", "PROVISION", "AJUSTEMENT", "AUTRE"]}
_CLASSE_RETENTION = {"type": "string", "enum": ["FISCALE_6_ANS", "STANDARD"]}
_PALIER = {"type": "string", "enum": ["F0", "F1", "F2", "F3", "F4", "F5", "F6", "F7"]}


def _rejouer_registre(historique: list[dict[str, Any]] | None) -> registre_module.Registre:
    """Reconstruit un registre M5 en rejouant l'historique fourni par l'appelant.

    Fonctionne indifféremment pour la chaîne des mouvements ou celle des
    approbations : `Registre.ajouter` distingue déjà les `type_entree`. Rejouer
    déterministe (mêmes entrées, même ordre -> mêmes hachages) : ce n'est pas une
    vérification contre une vérité externe, seulement une reconstruction fidèle.

    Frontière JSON : `opsys.outils.executer` sérialise un Decimal en texte pour la
    réponse (`vers_json`). Quand l'appelant renvoie cet historique tel quel à un
    appel suivant, `montant` y arrive donc en texte — il est reconstruit en
    Decimal ici (jamais un float intermédiaire) avant d'être rejoué.
    """
    registre_cible = registre_module.Registre()
    for entree in historique or ():
        brut = {cle: valeur for cle, valeur in entree.items() if cle not in ("ligne_id", "precedent_ligne_id")}
        if brut.get("type_entree") == "mouvement_enregistre" and isinstance(brut.get("montant"), str):
            brut["montant"] = _vers_montant_decimal(brut["montant"])
        registre_cible.ajouter(brut)
    return registre_cible


def _vers_montant_decimal(montant_texte: str) -> Decimal:
    if not isinstance(montant_texte, str):
        raise ValueError("montant doit être fourni en texte décimal (jamais un nombre JSON)")
    try:
        return Decimal(montant_texte)
    except InvalidOperation as exc:
        raise ValueError(f"montant décimal invalide : {montant_texte!r}") from exc


def etat_tresorerie(
    role: str | None,
    autorise_couts: bool,
    mouvements_historique: list[dict[str, Any]] | None = None,
    taux_utilises: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Composé de bout en bout : rejoue le registre, calcule solde + argent disponible
    réel, filtre par rôle. `autorise_couts` est un argument OBLIGATOIRE et explicite
    (fail-closed) : aucune valeur par défaut n'expose jamais une donnée financière."""
    registre_cible = _rejouer_registre(mouvements_historique)
    return etat_financier.construire_etat_financier(
        registre_cible, taux_utilises or [], role=role, autorise_couts=autorise_couts
    )


def calculer_taxes_tps_tvq(montant_avant_taxes: str) -> dict[str, Any]:
    dictionnaire, erreurs = taux_fiscaux.charger_taux_fiscaux(_CHEMIN_TAUX_FISCAUX)
    if erreurs:
        return {"accepte": False, "verdict": {"code": "REJ-TAUX-FICHIER-INVALIDE", "detail": "; ".join(erreurs)}}
    resultat, verdict = taxes.calculer_taxes(_vers_montant_decimal(montant_avant_taxes), dictionnaire)
    return depuis_couple((resultat, verdict))


def enregistrer_mouvement(
    montant: str,
    type_mouvement: str,
    horodatage: str,
    classe_retention: str,
    source: str,
    mouvements_historique: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    registre_cible = _rejouer_registre(mouvements_historique)
    mouvement = {
        "montant": _vers_montant_decimal(montant),
        "type_mouvement": type_mouvement,
        "horodatage": horodatage,
        "classe_retention": classe_retention,
        "source": source,
    }
    try:
        maillon = registre_module.enregistrer_mouvement(mouvement, registre_cible)
    except validation.MouvementInvalide as exc:
        return {"accepte": False, "verdict": exc.verdict}
    return {"accepte": True, "resultat": maillon, "mouvements_historique": registre_cible.lire()}


def creer_demande_approbation(
    demande_id: str,
    palier: str,
    action: str,
    horodatage: str,
    approbations_historique: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    registre_cible = _rejouer_registre(approbations_historique)
    maillon, verdict = approbation.creer_demande(demande_id, palier, action, registre_cible, horodatage)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return {"accepte": True, "resultat": maillon, "approbations_historique": registre_cible.lire()}


def decider_approbation(
    demande_id: str,
    decision: str,
    approbateur: str,
    horodatage: str,
    preuve: str | None = None,
    approbations_historique: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    registre_cible = _rejouer_registre(approbations_historique)
    if decision == "APPROUVE":
        maillon, verdict = approbation.approuver(demande_id, approbateur, registre_cible, horodatage, preuve=preuve)
    elif decision == "REFUSE":
        maillon, verdict = approbation.refuser(demande_id, approbateur, registre_cible, horodatage)
    else:
        return {
            "accepte": False,
            "verdict": {"code": "REJ-DECISION-INVALIDE", "detail": f"decision inconnue : {decision!r}"},
        }
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return {"accepte": True, "resultat": maillon, "approbations_historique": registre_cible.lire()}


def outils() -> tuple[Outil, ...]:
    return (
        Outil(
            nom="m5_etat_tresorerie",
            description=(
                "État financier de bout en bout : solde et argent disponible réel (solde moins "
                "provisions), filtrés par rôle. autorise_couts doit être explicitement vrai pour "
                "voir un montant ; sinon l'état ne porte ni solde, ni argent disponible, ni taux."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "role": {"type": ["string", "null"]},
                    "autorise_couts": {"type": "boolean"},
                    "mouvements_historique": _HISTORIQUE,
                    "taux_utilises": {"type": "array", "items": {"type": "object"}},
                },
                "required": ["role", "autorise_couts"],
                "additionalProperties": False,
            },
            fonction=etat_tresorerie,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m5_calculer_taxes_tps_tvq",
            description=(
                "Calcule TPS + TVQ en Decimal sur un montant avant taxes, à partir des taux "
                "versionnés en vigueur (contracts/taux_fiscaux.v1.yaml). Bloque si un taux est absent."
            ),
            parametres={
                "type": "object",
                "properties": {"montant_avant_taxes": _MONTANT_TEXTE},
                "required": ["montant_avant_taxes"],
                "additionalProperties": False,
            },
            fonction=calculer_taxes_tps_tvq,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m5_enregistrer_mouvement",
            description=(
                "Enregistre un mouvement financier au registre append-only (écriture financière : "
                "T3, jamais autonome). Le signe du montant doit être cohérent avec le type "
                "(DECAISSEMENT négatif, ENCAISSEMENT/PROVISION positifs) ou le mouvement est refusé."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "montant": _MONTANT_TEXTE,
                    "type_mouvement": _TYPE_MOUVEMENT,
                    "horodatage": {"type": "string", "description": "ISO 8601 avec fuseau"},
                    "classe_retention": _CLASSE_RETENTION,
                    "source": {"type": "string"},
                    "mouvements_historique": _HISTORIQUE,
                },
                "required": ["montant", "type_mouvement", "horodatage", "classe_retention", "source"],
                "additionalProperties": False,
            },
            fonction=enregistrer_mouvement,
            autonomie=Autonomie.T3,
        ),
        Outil(
            nom="m5_creer_demande_approbation",
            description=(
                "Crée une demande d'approbation à un palier F0-F7 (statut EN_ATTENTE). Registre "
                "interne dédié, distinct de celui des mouvements — ne décide rien par elle-même."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "demande_id": {"type": "string"},
                    "palier": _PALIER,
                    "action": {"type": "string"},
                    "horodatage": {"type": "string"},
                    "approbations_historique": _HISTORIQUE,
                },
                "required": ["demande_id", "palier", "action", "horodatage"],
                "additionalProperties": False,
            },
            fonction=creer_demande_approbation,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m5_decider_approbation",
            description=(
                "Enregistre la décision (APPROUVE/REFUSE) d'un humain sur une demande existante. "
                "F6/F7 exigent en plus une preuve structurée JSON {methode, horodatage, "
                "identifiant_approbateur} — une chaîne libre est refusée. Action T3, jamais autonome."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "demande_id": {"type": "string"},
                    "decision": {"type": "string", "enum": ["APPROUVE", "REFUSE"]},
                    "approbateur": {"type": "string"},
                    "horodatage": {"type": "string"},
                    "preuve": {
                        "type": ["string", "null"],
                        "description": (
                            "Requise (JSON {methode, horodatage, identifiant_approbateur}) pour "
                            "APPROUVE aux paliers F6/F7 ; ignorée sinon."
                        ),
                    },
                    "approbations_historique": _HISTORIQUE,
                },
                "required": ["demande_id", "decision", "approbateur", "horodatage"],
                "additionalProperties": False,
            },
            fonction=decider_approbation,
            autonomie=Autonomie.T3,
        ),
    )
