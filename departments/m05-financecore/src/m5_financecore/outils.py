"""Capacités d'agent du département M5 FinanceCore.

Chaque outil enveloppe une fonction métier déterministe existante : aucune n'est
réécrite. Les montants sont TOUJOURS des Decimal construits depuis une
représentation textuelle (jamais un float JSON, qui importerait une imprécision
binaire dans un registre financier).

Le registre (mouvements et approbations, deux chaînes DISTINCTES, PRD §5.4) : sauf si
l'appelant transmet explicitement `mouvements_historique`/`approbations_historique`
(l'historique renvoyé par un appel précédent — simulation en mémoire, rejouée via
`Registre.ajouter`, comportement historique gardé par les tests unitaires de ce
paquet), chaque appel obtient le registre de PRODUCTION. Pour les APPROBATIONS,
celui-ci reste en mémoire pour la durée d'un appel (registre de gouvernance interne,
hors périmètre de ce chantier). Pour les MOUVEMENTS, il est adossé au stockage durable
de l'instance (ADR-0009) dès le chargement du module, relu à chaque appel et jamais
ouvert au chargement ; `reinitialiser_stockage_mouvements()` le rebascule en mémoire
pour les tests unitaires, `utiliser_stockage_durable()` revient au durable.
`registre.py` reste pur (ni `opsys` ni SQLAlchemy) : ce module est l'unique endroit du
département qui connaît `opsys.stockage`.

RÈGLE FINANCE (autonomie) : toute écriture financière (registre des mouvements) et
toute décision d'approbation sont T3 — une action qui engage ou meut de l'argent
n'est jamais autonome, quel que soit le mode du département. Créer une demande
d'approbation (sans la trancher) est une écriture de gouvernance interne, T1.
Lecture et calcul purs (état, taxes) sont T0. Créer une facture BROUILLON (M5.2,
`m5_creer_facture_brouillon`) suit le même raisonnement que créer une demande
d'approbation : c'est une écriture interne non finale sur un registre dédié — elle
n'envoie rien au client et n'engage aucun argent (le registre des MOUVEMENTS n'est
jamais touché) — donc T1, jamais T3 à ce stade. Les transitions qui, elles,
engagent (BROUILLON -> ENVOYEE derrière une approbation F4, ENVOYEE -> PAYEE
derrière un approbateur humain) restent en `facturation.py`, gardées par construction,
sans outil agent exposé ici pour l'instant.

Registre des FACTURES (M5.2, `facturation.py`) : troisième registre du département, sur
exactement le même patron d'adaptateur que celui des mouvements (`_registre_factures`/
`_etat_factures` ci-dessous, symétriques à `_registre_mouvements`/`_etat_mouvements`) — durable
dès que `_stockage_durable_actif` l'est (même bascule que les mouvements), jamais ouvert au
chargement, relu à chaque appel, `stockage.maillons("m05-financecore", "factures")` en
production. Le registre des MOUVEMENTS reste strictement celui déjà en place : aucune fonction
de ce fichier n'écrit un ENCAISSEMENT à partir d'une facture.

Consommateurs d'événements (ADR-0009 §3, PLAN T1.2-d, suite) : `consommateurs()` abonne
`_recevoir_devis_accepte` (`m3.devis_accepte`) et `_recevoir_travaux_termines`
(`m4.travaux_termines`), chacun sur son propre registre durable dédié (`devis_recus.py`,
`wct_recus.py` — DISTINCTS des mouvements et des factures : ni une écriture financière, ni une
facture, seulement ce qui a été REÇU). Les deux délèguent à `_essayer_facture_brouillon`,
fonction UNIQUE (même patron que M6 `_evaluer_et_publier_variance`) qui tente la facture
BROUILLON dès que devis ET complétion sont connus, quel que soit l'ordre d'arrivée. Fail-closed :
devis inconnu, complétion inconnue, `chantier_id` absent du devis ou WCT sans `devis_id` donnent
un statut d'attente nommé, jamais une facture inventée — `lister_attentes_facturation` (T0) les
recalcule EN DIRECT depuis les registres reçus et celui des factures à chaque appel, aucun
troisième registre d'« attentes » à tenir synchronisé à part. Une incohérence interne (ex.
`prix_total` du devis qui ne concorde pas avec la somme recalculée des lignes) LÈVE : le
répartiteur réessaie puis met en quarantaine, jamais une facture fabriquée sur une donnée qui ne
tient pas debout. Ce module reste le seul point du département qui connaît `opsys.evenements`,
comme il est déjà le seul à connaître `opsys.stockage` — `facturation.py` n'importe ni l'un ni
l'autre (DA-M5-04).
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from opsys import stockage
from opsys.outils import Autonomie, Outil, depuis_couple

from . import approbation, devis_recus, etat_financier, facturation, taux_fiscaux, taxes, validation, wct_recus
from . import registre as registre_module

_CHEMIN_TAUX_FISCAUX = Path(__file__).resolve().parents[2] / "contracts" / "taux_fiscaux.v1.yaml"

_DEPARTEMENT = "m05-financecore"
_NOM_REGISTRE_MOUVEMENTS = "principal"
_NOM_REGISTRE_FACTURES = "factures"
_NOM_REGISTRE_DEVIS_RECUS = "devis_recus"
_NOM_REGISTRE_WCT_RECUS = "wct_recus"

# Registre de production des mouvements (ADR-0009) : durable dès le chargement du module. Les tests
# unitaires en mémoire le rebasculent par `reinitialiser_stockage_mouvements()`.
_stockage_durable_actif = True


def utiliser_stockage_durable() -> None:
    """Revient au registre de PRODUCTION des mouvements, adossé au stockage durable de l'instance
    (ADR-0009) : `opsys.stockage.maillons("m05-financecore", "principal")`, dans la base et la
    transaction de l'appel courant (`opsys.outils.executer_atomique`/`Capacites.appeler` en
    ouvre une autour de chaque appel d'outil). C'est l'état au chargement du module."""
    global _stockage_durable_actif
    _stockage_durable_actif = True


def reinitialiser_stockage_mouvements() -> None:
    """Revient au registre des mouvements EN MÉMOIRE (réservé aux tests) : annule un éventuel
    `utiliser_stockage_durable()`."""
    global _stockage_durable_actif
    _stockage_durable_actif = False


_MAILLON = {"type": "object", "description": "Maillon tel que renvoyé par un appel précédent."}
_HISTORIQUE = {
    "type": "array",
    "items": _MAILLON,
    "description": "Historique renvoyé par le dernier appel connu ; [] ou omis si aucun.",
}
_HISTORIQUE_MOUVEMENTS = {
    "type": "array",
    "items": _MAILLON,
    "description": (
        "Optionnel. Fourni : simulation en mémoire sur cet historique, sans toucher au registre "
        "durable. Omis (cas normal en production) : lit/écrit le registre des mouvements de "
        "l'instance — la continuité entre appels n'a plus besoin d'être transportée par l'appelant."
    ),
}
_MONTANT_TEXTE = {
    "type": "string",
    "description": "Montant décimal en texte, ex. \"125.00\" — jamais un nombre JSON (imprécision binaire).",
}
_TYPE_MOUVEMENT = {"type": "string", "enum": ["ENCAISSEMENT", "DECAISSEMENT", "PROVISION", "AJUSTEMENT", "AUTRE"]}
_CLASSE_RETENTION = {"type": "string", "enum": ["FISCALE_6_ANS", "STANDARD"]}
_PALIER = {"type": "string", "enum": ["F0", "F1", "F2", "F3", "F4", "F5", "F6", "F7"]}
_LIGNE_FACTURE = {
    "type": "object",
    "properties": {
        "description": {"type": "string"},
        "quantite": _MONTANT_TEXTE,
        "unite": {"type": "string"},
        "prix_unitaire": _MONTANT_TEXTE,
        "reference_ligne_devis": {"type": "string"},
    },
    "required": ["description", "quantite", "unite", "prix_unitaire", "reference_ligne_devis"],
    "additionalProperties": False,
}
_HISTORIQUE_FACTURES = {
    "type": "array",
    "items": _MAILLON,
    "description": (
        "Optionnel. Fourni : simulation en mémoire sur cet historique, sans toucher au registre "
        "durable des factures. Omis (cas normal en production) : lit/écrit le registre des "
        "factures de l'instance."
    ),
}


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


def _registre_mouvements(historique: list[dict[str, Any]] | None) -> registre_module.Registre:
    """Registre des MOUVEMENTS pour un appel.

    Un `historique` explicite (même vide, `[]`) est rejoué EN MÉMOIRE via
    `_rejouer_registre` — simulation sans effet sur le stockage durable, le
    comportement gardé par les tests unitaires de ce paquet. `None` (omis) rend le
    registre de PRODUCTION : en mémoire tant que `utiliser_stockage_durable()` n'a
    pas été appelé, adossé au stockage durable de l'instance (ADR-0009) ensuite.
    Jamais de cache ici, à dessein (même principe que `opsys.stockage.maillons`) :
    une instance fraîche à chaque appel relit l'état réel depuis la base, pour ne
    jamais figer un solde devenu périmé entre deux appels d'outil (concurrence,
    autre processus)."""
    if historique is not None:
        return _rejouer_registre(historique)
    if _stockage_durable_actif:
        return registre_module.Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_MOUVEMENTS))
    return registre_module.Registre()


def _etat_mouvements(historique: list[dict[str, Any]] | None, registre_cible: registre_module.Registre) -> dict:
    """Ce que la réponse dit du registre des mouvements. Registre durable : la tête et la taille,
    jamais tout l'historique, qui grossit sans limite et coûterait des tokens à chaque appel.
    Simulation en mémoire : l'historique complet, que l'appelant retransmet au prochain appel."""
    if historique is None and _stockage_durable_actif:
        return {"registre_mouvements": {"taille": registre_cible.taille(), "tete": registre_cible.tete()}}
    return {"mouvements_historique": registre_cible.lire()}


def _registre_factures(historique: list[dict[str, Any]] | None) -> registre_module.Registre:
    """Registre des FACTURES pour un appel — même patron d'adaptateur que `_registre_mouvements`
    (mandat T1.1-e, tâche 2), y compris la bascule `_stockage_durable_actif` déjà en place pour
    les mouvements (un seul interrupteur pour tout le module : `utiliser_stockage_durable()`/
    `reinitialiser_stockage_mouvements()` couvrent donc aussi le registre des factures)."""
    if historique is not None:
        return _rejouer_registre(historique)
    if _stockage_durable_actif:
        return registre_module.Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_FACTURES))
    return registre_module.Registre()


def _etat_factures(historique: list[dict[str, Any]] | None, registre_cible: registre_module.Registre) -> dict:
    """Même règle que `_etat_mouvements` : registre durable -> tête et taille seulement (jamais
    tout l'historique) ; simulation en mémoire -> historique complet à retransmettre."""
    if historique is None and _stockage_durable_actif:
        return {"registre_factures": {"taille": registre_cible.taille(), "tete": registre_cible.tete()}}
    return {"factures_historique": registre_cible.lire()}


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
    """Composé de bout en bout : obtient le registre des mouvements (§`_registre_mouvements`),
    calcule solde + argent disponible réel, filtre par rôle. `autorise_couts` est un argument
    OBLIGATOIRE et explicite (fail-closed) : aucune valeur par défaut n'expose jamais une donnée
    financière."""
    registre_cible = _registre_mouvements(mouvements_historique)
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
    registre_cible = _registre_mouvements(mouvements_historique)
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
    return {"accepte": True, "resultat": maillon, **_etat_mouvements(mouvements_historique, registre_cible)}


def creer_facture_brouillon(
    facture_id: str,
    chantier_id: str,
    devis_id: str,
    client_id: str,
    lignes: list[dict[str, Any]],
    horodatage: str,
    montant_avant_taxes: str | None = None,
    factures_historique: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    dictionnaire_taux, erreurs = taux_fiscaux.charger_taux_fiscaux(_CHEMIN_TAUX_FISCAUX)
    if erreurs:
        return {"accepte": False, "verdict": {"code": "REJ-TAUX-FICHIER-INVALIDE", "detail": "; ".join(erreurs)}}
    registre_cible = _registre_factures(factures_historique)
    resultat, verdict = facturation.creer_facture_brouillon(
        facture_id=facture_id,
        chantier_id=chantier_id,
        devis_id=devis_id,
        client_id=client_id,
        lignes=lignes,
        horodatage=horodatage,
        dictionnaire_taux=dictionnaire_taux,
        registre_cible=registre_cible,
        montant_avant_taxes_fourni=montant_avant_taxes,
    )
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return {"accepte": True, "resultat": resultat, **_etat_factures(factures_historique, registre_cible)}


def _essayer_facture_brouillon(devis_id: str) -> dict[str, Any]:
    """Fonction UNIQUE qui tente de créer la facture BROUILLON pour ce devis_id (PLAN T1.2-d,
    suite). Les deux consommateurs ci-dessous l'appellent avec le MÊME devis_id dès qu'ils
    viennent de garder leur propre pièce (`devis_recus.py`/`wct_recus.py`), quel que soit l'ordre
    d'arrivée entre `m3.devis_accepte` et `m4.travaux_termines` — jamais de calcul différent selon
    qui a déclenché l'appel (même patron que M6 `_evaluer_et_publier_variance`, PLAN T1.2-b).
    Appelable SEULEMENT dans la transaction du répartiteur (`stockage.maillons` y fait autorité).

    Fail-closed, jamais une facture inventée : devis inconnu, complétion inconnue, ou
    `chantier_id` absent du devis (nul ou vide) rendent un statut d'attente nommé (`en_attente_*`)
    — états normaux du flux réel (R12 §4/§9.7), jamais une panne. `lister_attentes_facturation`
    recalcule ces mêmes statuts EN DIRECT pour l'outil T0, sans rien stocker de plus ici.

    Idempotent : une facture déjà active pour ce devis_id (`facturation.facture_active_pour_devis`)
    court-circuite AVANT toute tentative de création — couvre la redélivrance de l'un ou l'autre
    événement, la double publication du même devis, et le second appel de cette fonction quand les
    deux pièces sont déjà connues (chaque consommateur rappelle systématiquement cette fonction).

    Incohérence interne (ex. taux fiscal illisible, ou `prix_total` du devis qui ne concorde pas
    avec la somme recalculée des lignes) : LÈVE. `creer_facture_brouillon` a déjà validé la forme
    de chaque ligne et le total à la source (M3, `devis_durable.py`) ; un refus ici trahirait une
    incohérence entre départements, jamais un cas d'usage normal — mieux vaut une panne explicite
    (réessais puis quarantaine par le répartiteur) qu'une facture fabriquée ou un statut inventé
    pour un cas qu'on n'a pas su nommer.
    """
    devis_recu = devis_recus.pour_devis_id(devis_id, stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_DEVIS_RECUS))
    if devis_recu is None:
        return {"traite": True, "devis_id": devis_id, "statut": "en_attente_devis_accepte"}

    wct_recu = wct_recus.pour_devis_id(devis_id, stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_WCT_RECUS))
    if wct_recu is None:
        return {"traite": True, "devis_id": devis_id, "statut": "en_attente_travaux_termines"}

    chantier_id = devis_recu.get("chantier_id")
    if not isinstance(chantier_id, str) or not chantier_id.strip():
        return {"traite": True, "devis_id": devis_id, "statut": "en_attente_chantier_id"}

    registre_cible = _registre_factures(None)
    if facturation.facture_active_pour_devis(registre_cible, devis_id) is not None:
        return {"traite": True, "devis_id": devis_id, "statut": "facture_deja_existante"}

    dictionnaire_taux, erreurs = taux_fiscaux.charger_taux_fiscaux(_CHEMIN_TAUX_FISCAUX)
    if erreurs:
        raise RuntimeError(f"taux fiscaux illisibles ({_CHEMIN_TAUX_FISCAUX}) : {'; '.join(erreurs)}")

    lignes = [
        {
            "description": ligne["description"],
            "quantite": ligne["quantite"],
            "unite": ligne["unite"],
            "prix_unitaire": ligne["prix_unitaire"],
            "reference_ligne_devis": ligne["reference_ligne"],
        }
        for ligne in devis_recu["lignes"]
    ]

    resultat, verdict = facturation.creer_facture_brouillon(
        facture_id=f"fac-{devis_id}",
        chantier_id=chantier_id,
        devis_id=devis_id,
        # T2.2 (Client 360) pas encore construit : lead_id fait office de client_id le temps que
        # ce département existe — documenté ici, à réconcilier par T2.2, jamais un identifiant
        # fabriqué en attendant (le lead_id, lui, est réel : porté tel quel depuis M3/M2).
        client_id=devis_recu["lead_id"],
        lignes=lignes,
        horodatage=wct_recu["horodatage_completion"],
        dictionnaire_taux=dictionnaire_taux,
        registre_cible=registre_cible,
        montant_avant_taxes_fourni=devis_recu["prix_total"],
    )
    if verdict is not None:
        if verdict["code"] == "REJ-FACTURE-DEVIS-DEJA-FACTURE":
            return {"traite": True, "devis_id": devis_id, "statut": "facture_deja_existante"}
        raise RuntimeError(f"creer_facture_brouillon a refusé une entrée déjà validée par M3 : {verdict}")

    return {
        "traite": True,
        "devis_id": devis_id,
        "statut": "facture_creee",
        "facture_id": resultat["facture_id"],
    }


def _recevoir_devis_accepte(charge: dict[str, Any]) -> dict[str, Any]:
    """Consomme `m3.devis_accepte` : garde ce que M5 a reçu de ce devis (`devis_recus.py`,
    idempotent par devis_id), puis délègue toute la décision de facturer à
    `_essayer_facture_brouillon`, fonction UNIQUE partagée avec `_recevoir_travaux_termines`."""
    devis_id = charge["devis_id"]
    registre = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_DEVIS_RECUS)
    if devis_recus.pour_devis_id(devis_id, registre) is None:
        registre.append(
            devis_recus.construire(
                devis_id=devis_id,
                lead_id=charge["lead_id"],
                chantier_id=charge["chantier_id"],
                lignes=charge["lignes"],
                prix_total=charge["prix_total"],
                horodatage_acceptation=charge["horodatage_acceptation"],
            )
        )
    return _essayer_facture_brouillon(devis_id)


def _recevoir_travaux_termines(charge: dict[str, Any]) -> dict[str, Any]:
    """Consomme `m4.travaux_termines` : garde ce que M5 a reçu de ce WCT (`wct_recus.py`,
    idempotent par wct_id — y compris quand `devis_id` est nul, pour que
    `lister_attentes_facturation` puisse le signaler), puis délègue à
    `_essayer_facture_brouillon` SEULEMENT si `devis_id` est connu : une intervention inscrite
    sans devis n'a rien à joindre, jamais deviné (fail-closed, PLAN T1.2-d)."""
    wct_id = charge["wct_id"]
    registre = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_WCT_RECUS)
    wct_recu = wct_recus.pour_wct_id(wct_id, registre)
    if wct_recu is None:
        wct_recu = wct_recus.construire(
            wct_id=wct_id,
            intervention_id=charge["intervention_id"],
            devis_id=charge.get("devis_id"),
            horodatage_completion=charge["horodatage_completion"],
        )
        registre.append(wct_recu)
    if wct_recu["devis_id"] is None:
        return {"traite": True, "wct_id": wct_id, "statut": "wct_sans_devis_id"}
    return _essayer_facture_brouillon(wct_recu["devis_id"])


def lister_attentes_facturation() -> dict[str, Any]:
    """Outil T0 compact : liste les devis/WCT en attente d'une facture BROUILLON (T1.3 s'en
    servira pour la file d'approbation du propriétaire). Recalculée EN DIRECT depuis les
    registres reçus (`devis_recus.py`, `wct_recus.py`) et celui des factures à CHAQUE appel — le
    même état que `_essayer_facture_brouillon` recalculerait pour chaque devis_id, sans effet de
    bord ni troisième registre d'« attentes » à tenir synchronisé à part."""
    devis_recus_registre = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_DEVIS_RECUS)
    wct_recus_registre = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_WCT_RECUS)
    factures_registre = _registre_factures(None)

    devis_ids_connus = {maillon["devis_id"] for maillon in devis_recus_registre}
    devis_ids_connus |= {
        maillon["devis_id"] for maillon in wct_recus_registre if maillon.get("devis_id") is not None
    }

    attentes_devis: list[dict[str, Any]] = []
    for devis_id in sorted(devis_ids_connus):
        if facturation.facture_active_pour_devis(factures_registre, devis_id) is not None:
            continue
        devis_recu = devis_recus.pour_devis_id(devis_id, devis_recus_registre)
        if devis_recu is None:
            attentes_devis.append({"devis_id": devis_id, "statut": "en_attente_devis_accepte"})
            continue
        wct_recu = wct_recus.pour_devis_id(devis_id, wct_recus_registre)
        if wct_recu is None:
            attentes_devis.append({"devis_id": devis_id, "statut": "en_attente_travaux_termines"})
            continue
        chantier_id = devis_recu.get("chantier_id")
        if not isinstance(chantier_id, str) or not chantier_id.strip():
            attentes_devis.append({"devis_id": devis_id, "statut": "en_attente_chantier_id"})

    attentes_wct_sans_devis_id = [
        {"wct_id": maillon["wct_id"], "intervention_id": maillon["intervention_id"], "statut": "wct_sans_devis_id"}
        for maillon in wct_recus_registre
        if maillon.get("devis_id") is None
    ]

    return {"attentes_devis": attentes_devis, "attentes_wct_sans_devis_id": attentes_wct_sans_devis_id}


def consommateurs() -> dict[str, Callable[[dict], dict]]:
    return {
        "m3.devis_accepte": _recevoir_devis_accepte,
        "m4.travaux_termines": _recevoir_travaux_termines,
    }


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
                    "mouvements_historique": _HISTORIQUE_MOUVEMENTS,
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
                    "mouvements_historique": _HISTORIQUE_MOUVEMENTS,
                },
                "required": ["montant", "type_mouvement", "horodatage", "classe_retention", "source"],
                "additionalProperties": False,
            },
            fonction=enregistrer_mouvement,
            autonomie=Autonomie.T3,
        ),
        Outil(
            nom="m5_creer_facture_brouillon",
            description=(
                "Crée une facture BROUILLON (M5.2) sur le registre dédié des factures, distinct "
                "du registre des mouvements. Recalcule tous les totaux et les taxes TPS/TVQ "
                "depuis les lignes — ne fait jamais confiance à un montant_avant_taxes fourni "
                "(rejet s'il diffère). Idempotente par devis_id : refuse un second brouillon "
                "actif pour le même devis. Écriture interne non finale (T1) : n'envoie rien au "
                "client, n'encaisse rien, ne touche jamais le registre des mouvements."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "facture_id": {"type": "string"},
                    "chantier_id": {"type": "string"},
                    "devis_id": {"type": "string"},
                    "client_id": {"type": "string"},
                    "lignes": {"type": "array", "items": _LIGNE_FACTURE, "minItems": 1},
                    "horodatage": {"type": "string", "description": "ISO 8601 avec fuseau"},
                    "montant_avant_taxes": {
                        "type": ["string", "null"],
                        "description": (
                            "Optionnel : contrôle défensif. Si fourni, doit correspondre "
                            "exactement au total recalculé depuis les lignes, sinon rejet."
                        ),
                    },
                    "factures_historique": _HISTORIQUE_FACTURES,
                },
                "required": ["facture_id", "chantier_id", "devis_id", "client_id", "lignes", "horodatage"],
                "additionalProperties": False,
            },
            fonction=creer_facture_brouillon,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m5_lister_attentes_facturation",
            description=(
                "Liste compacte (PLAN T1.2-d, suite) des devis acceptés (m3.devis_accepte) et "
                "des interventions terminées (m4.travaux_termines) qui n'ont PAS encore produit "
                "de facture BROUILLON, avec le statut nommé qui dit quoi demander : "
                "en_attente_devis_accepte, en_attente_travaux_termines, en_attente_chantier_id, "
                "ou wct_sans_devis_id (intervention inscrite sans devis, jamais reliée seule). "
                "Lecture pure recalculée à chaque appel, aucune écriture. T1.3 s'en servira pour "
                "la file d'approbation du propriétaire."
            ),
            parametres={"type": "object", "properties": {}, "additionalProperties": False},
            fonction=lister_attentes_facturation,
            autonomie=Autonomie.T0,
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
