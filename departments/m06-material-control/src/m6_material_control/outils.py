"""Capacités d'agent du département M6 Material Control.

Chaque outil enveloppe l'orchestrateur unique `materiel.py` (seul point d'écriture par
type de mouvement — RECEPTION/CONSOMMATION/VARIANCE_INVENTAIRE, DA-M6-11 ; RETOUR/PERTE/
BRIS depuis PLAN T1.1-d2, garde_ecriture_stock de conformite.py). `m6_receptionner_commande`
compose de bout en bout : réception -> écriture du stock -> résolution de prix -> variance
de réception -> signal à M5 -> suggestion de réapprovisionnement, en un seul appel.
`m6_declarer_materiaux_utilises` (PLAN T1.1-d2) fait de même pour la fin de chantier :
formulaire enrichi -> mouvements typés (CONSOMMATION/RETOUR/PERTE/BRIS) -> stock théorique
cohérent, idempotent par wct_id.

Le registre (append-only hash-chaîné) est durable en production (ADR-0009) : à l'intérieur de la
transaction que `Capacites.appeler`/`executer_atomique` ouvre pour chaque appel d'outil (point de
passage unique), chaque fonction ci-dessous lit et écrit le registre durable du département via
`opsys.stockage.maillons` — plus besoin que l'appelant transporte un historique. Hors transaction
(appel direct de ce module, tests unitaires du département, qui ne montent aucune base) :
comportement historique inchangé — l'appelant transmet l'historique renvoyé par le précédent appel
dans `registre_historique` ; ce module le rejoue pour retrouver un registre en mémoire valide et
chaîné avant d'y écrire la suite. `registre.py` reste pur (aucun import `opsys`/SQLAlchemy) : c'est
ici, et seulement ici, que le paquet touche `opsys.stockage`.

Frontière M6 -> M5 (financier) : `signal_po_a_payer.montant_total_estime` reste un
float (contrat gelé M6, PRD §2.8/§5.8) — quiconque le transmet à M5 (qui exige un
Decimal, CA-M5-01) doit le convertir via
`contrats_sortie.montant_decimal_a_la_frontiere` (jamais `Decimal(x)` direct sur un
float).

Autonomie (RÈGLE FINANCE) : M6 ne porte aucune écriture financière — elle SIGNALE
un montant à payer, sans jamais l'exécuter. Ses écritures (stock, inventaire) sont
un registre interne : T1. Lecture et calcul purs : T0.

Événements (ADR-0009 §3, PLAN T1.2-b et son correctif) : `_evaluer_et_publier_variance` est la
fonction UNIQUE qui compare le prévu au réel déclaré et publie `m6.variance_chantier` — partagée
par `_recevoir_travaux_termines` (consommateur de `m4.travaux_termines`) ET par
`declarer_materiaux_utilises`/`enregistrer_besoins_prevus`, qui la rappellent quand leur propre
écriture comble après coup ce qui manquait à un WCT déjà reçu (`wct_recus.py`) — le flux réel
(R12 §4/§9.7) livre presque toujours la déclaration, et parfois le prévu M3 (T1.2-d), APRÈS la
complétion, jamais avant.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

from opsys import evenements, stockage
from opsys.outils import Autonomie, Outil

from . import besoins_prevus, digest, materiel, validation, variance_chantier, wct_recus
from . import catalogue as catalogue_module
from . import registre as registre_module

_DEPARTEMENT = "m06-material-control"
_NOM_REGISTRE = "principal"
_NOM_REGISTRE_BESOINS_PREVUS = "besoins_prevus"
_NOM_REGISTRE_WCT_RECUS = "wct_recus"
_MANIFESTE = Path(__file__).resolve().parents[2] / "department.yaml"

_MAILLON = {"type": "object", "description": "Maillon tel que renvoyé par un appel précédent."}
_REGISTRE_HISTORIQUE = {
    "type": "array",
    "items": _MAILLON,
    "description": (
        "À omettre : le registre M6 est durable et relu par l'outil. Ne sert qu'aux appels directs "
        "hors transaction, qui retransmettent l'historique renvoyé par l'appel précédent."
    ),
}
_LIGNE_DEMANDEE = {
    "type": "object",
    "properties": {"materiau_id": {"type": "string"}, "quantite_demandee": {"type": "number"}},
    "required": ["materiau_id", "quantite_demandee"],
}
_LIGNE_RECUE = {
    "type": "object",
    "properties": {"materiau_id": {"type": "string"}, "quantite_recue": {"type": "number"}},
    "required": ["materiau_id", "quantite_recue"],
}
_BON_DEMANDE = {
    "type": "object",
    "properties": {
        "po_id": {"type": "string"},
        "chantier_id": {"type": "string"},
        "lignes_demandees": {"type": "array", "items": _LIGNE_DEMANDEE},
        "horodatage": {"type": "string"},
    },
    "required": ["po_id", "chantier_id", "lignes_demandees", "horodatage"],
}
_RECEPTION_PO = {
    "type": "object",
    "properties": {
        "po_id": {"type": "string"},
        "chantier_id": {"type": "string"},
        "lignes_recues": {"type": "array", "items": _LIGNE_RECUE},
        "horodatage": {"type": "string"},
    },
    "required": ["po_id", "chantier_id", "lignes_recues", "horodatage"],
}
_CATALOGUE = {
    "type": ["object", "null"],
    "description": "CatalogueMateriaux {version, unite_monetaire, postes} ; null si aucun catalogue.",
}
_SEUILS_REORDER = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "chantier_id": {"type": "string"},
            "materiau_id": {"type": "string"},
            "seuil_quantite": {"type": "number"},
        },
        "required": ["chantier_id", "materiau_id", "seuil_quantite"],
    },
}
_WCT = {"type": "object", "description": "WctRecu — 12 clés exactes émises par M4, reproduites telles quelles."}
_FORMULAIRE_CONSOMMATION = {
    "type": "object",
    "properties": {
        "wct_id": {"type": "string"},
        "intervention_id": {"type": "string"},
        "chantier_id": {"type": "string"},
        "lignes_consommees": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"materiau_id": {"type": "string"}, "quantite": {"type": "number"}},
                "required": ["materiau_id", "quantite"],
            },
        },
    },
    "required": ["wct_id", "intervention_id", "chantier_id", "lignes_consommees"],
}
_COMPTAGE = {
    "type": "object",
    "properties": {
        "chantier_id": {"type": "string"},
        "materiau_id": {"type": "string"},
        "quantite_comptee": {"type": "number"},
        "horodatage": {"type": "string"},
    },
    "required": ["chantier_id", "materiau_id", "quantite_comptee", "horodatage"],
}
_BESOIN_ESTIME_CHANTIER = {
    "type": "object",
    "description": "BesoinEstimeChantier : ce que M3 a estimé pour ce matériau sur ce chantier.",
    "properties": {
        "materiau_id": {"type": "string"},
        "quantite_estimee": {"type": "number"},
        "unite": {"type": "string"},
    },
    "required": ["materiau_id", "quantite_estimee", "unite"],
}
_BESOINS_ESTIMES_CHANTIER = {"type": "array", "items": _BESOIN_ESTIME_CHANTIER}
_LIGNE_DECLAREE_CHANTIER = {
    "type": "object",
    "description": (
        "Ligne du formulaire de fin de chantier enrichi (materiel.soumettre_materiaux_utilises) : "
        "type_ligne parmi prevu/non_prevu/retour/perte/bris/achat_terrain, materiau_id, quantite, "
        "unite ; quantite_estimee en plus si prevu ; photo_fournie et recu_fourni en plus si "
        "achat_terrain (au moins l'un des deux requis)."
    ),
    "properties": {
        "type_ligne": {
            "type": "string",
            "enum": ["prevu", "non_prevu", "retour", "perte", "bris", "achat_terrain"],
        },
        "materiau_id": {"type": "string"},
        "quantite": {"type": "number"},
        "unite": {"type": "string"},
        "quantite_estimee": {"type": "number"},
        "photo_fournie": {"type": "boolean"},
        "recu_fourni": {"type": "boolean"},
    },
    "required": ["type_ligne", "materiau_id", "quantite", "unite"],
}
_LIGNES_DECLAREES_CHANTIER = {"type": "array", "items": _LIGNE_DECLAREE_CHANTIER}
_FORMULAIRE_MATERIAUX_UTILISES = {
    "type": "object",
    "description": "Formulaire de fin de chantier enrichi (M6.10/M6.11), 6 types de ligne.",
    "properties": {
        "wct_id": {"type": "string"},
        "intervention_id": {"type": "string"},
        "chantier_id": {"type": "string"},
        "lignes_materiaux": {"type": "array", "items": _LIGNE_DECLAREE_CHANTIER},
    },
    "required": ["wct_id", "intervention_id", "chantier_id", "lignes_materiaux"],
}


def _rejouer_registre(historique: list[dict[str, Any]] | None) -> registre_module.Registre:
    """Reconstruit le registre M6 en rejouant l'historique fourni par l'appelant
    (mêmes maillons, même ordre -> mêmes hachages : reconstruction fidèle, pas une
    vérification contre une vérité externe que ce paquet ne détient pas).

    PLAN T1.1-d2 : wct_id, quand un maillon en porte un, est repris tel quel — sinon la
    rejoue perdrait l'idempotence (materiel.soumettre_materiaux_utilises) et le ciblage
    par wct_id (variance_chantier.comparer_depuis_registre) dès le deuxième appel hors
    transaction. Absent (tous les maillons antérieurs à PLAN T1.1-d2), rien ne change :
    même reconstruction qu'avant.
    """
    registre_cible = registre_module.Registre()
    historique = historique or []
    if not historique:
        return registre_cible
    mouvements = []
    for maillon in historique:
        mouvement = {
            "type_mouvement": maillon["type_mouvement"],
            "chantier_id": maillon["chantier_id"],
            "materiau_id": maillon["materiau_id"],
            "quantite": maillon["quantite"],
            "cout_unitaire": maillon["cout_unitaire"],
        }
        if "wct_id" in maillon:
            mouvement["wct_id"] = maillon["wct_id"]
        mouvements.append(mouvement)
    _, erreur = registre_cible.ajouter_lot(mouvements)
    if erreur is not None:
        raise ValueError(f"registre_historique incohérent : {erreur}")
    return registre_cible


def _registre_de_l_appel(historique: list[dict[str, Any]] | None) -> registre_module.Registre:
    """Registre à utiliser pour CET appel.

    À l'intérieur de la transaction que `Capacites.appeler`/`executer_atomique` ouvre pour chaque
    appel d'outil (ADR-0009, point de passage unique) : le registre durable du département fait
    autorité — `stockage.maillons(...)`, rien à rejouer, c'est le registre de PRODUCTION, et
    `ajouter`/`ajouter_lot` s'y exécutent dans cette même transaction (tout ou rien). Hors
    transaction (appel direct des fonctions de ce module, tests unitaires du département qui ne
    montent aucune base) : comportement historique inchangé, `_rejouer_registre` reconstruit un
    registre en mémoire depuis `registre_historique`.
    """
    if stockage.connexion_courante() is not None:
        return registre_module.Registre(maillons=stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
    return _rejouer_registre(historique)


def _etat_registre(registre_cible: registre_module.Registre) -> dict[str, Any]:
    """Ce que la réponse dit du registre après l'appel.

    Registre durable (production) : la tête de chaîne et la taille, jamais l'historique complet,
    qui grossit sans limite et coûterait des tokens à chaque appel. Hors transaction : l'historique
    complet, que l'appelant doit retransmettre au prochain appel (contrat historique).
    """
    if stockage.connexion_courante() is not None:
        return {"registre": {"taille": registre_cible.taille(), "hash_tete": registre_cible.hash_tete()}}
    return {"registre_historique": registre_cible.lire()}


# --------------------------------------------------------------------------------------- T1.2-b
# Besoins prévus (« M6 garde le prévu ») : registre durable DISTINCT du registre de mouvements
# de stock ci-dessus (besoins_prevus.py, docstring) — même patron durable/en mémoire que
# `_registre_de_l_appel`, mais sans passer par `registre_module.Registre` (aucune forme de
# mouvement, aucune garde de type_mouvement à respecter).
def _besoins_prevus_de_l_appel(historique: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if stockage.connexion_courante() is not None:
        return stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_BESOINS_PREVUS)
    return list(historique or [])


def _seuil_variance_chantier() -> float | None:
    """Seuil de criticité de la variance de CHANTIER (m6.variance_chantier, PLAN T1.2) : lu
    depuis `department.yaml/configuration` — JAMAIS un nombre codé en dur ici ni dans
    `variance_chantier.py` (AGENTS.md). Choisi à cet endroit précis (le manifeste du
    département, déjà la source de configuration explicite pour `budget`/`modeles`/`kpis` —
    voir `docs/architecture/DEPARTEMENTS.md`) plutôt qu'une constante Python ou un fichier
    séparé : c'est le seul endroit qu'un non-développeur peut déjà éditer pour ce département,
    et `opsys.departements.lire_manifeste` ignore silencieusement les clés top-niveau qu'il ne
    connaît pas — ajouter `configuration:` ne touche donc AUCUN contrat du socle (`src/opsys/`,
    hors périmètre de cette tranche).

    Fail-closed : absente ou invalide (`validation.valider_seuil_variance_chantier`), rend
    `None` — jamais un défaut inventé. Le consommateur d'événement rapporte alors
    `statut_variance="seuil_absent"` plutôt que d'évaluer quoi que ce soit.
    """
    donnees = yaml.safe_load(_MANIFESTE.read_text(encoding="utf-8")) or {}
    configuration = donnees.get("configuration") or {}
    seuil = configuration.get("seuil_variance_chantier_pourcentage")
    ok, _ = validation.valider_seuil_variance_chantier(seuil)
    return seuil if ok else None


# --------------------------------------------------------------------------------- correctif T1.2-b
# WCT reçus (garde le trou du flux réel — voir wct_recus.py) + la fonction UNIQUE d'évaluation et
# de publication de m6.variance_chantier, partagée par les TROIS déclencheurs : le consommateur de
# m4.travaux_termines ci-dessous, et les deux outils qui peuvent combler après coup ce qui manquait
# à un WCT déjà reçu (declarer_materiaux_utilises, enregistrer_besoins_prevus).
def _wct_recus_de_l_appel(historique: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if stockage.connexion_courante() is not None:
        return stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_WCT_RECUS)
    return list(historique or [])


def _texte_decimal(valeur: float | None) -> str | None:
    """Représentation décimale en texte d'une quantité ou d'un écart déjà calculé par
    variance_chantier.evaluer -- jamais un nombre JSON (précision de lecture non garantie d'un
    consommateur à l'autre), même discipline que contrats_sortie.montant_decimal_a_la_frontiere
    (str() sur le float source, jamais un recalcul). None reste None (ecart_pourcentage
    indéfini, jamais une valeur inventée). `+ 0.0` normalise le seul cas où IEEE 754 distingue
    -0.0 de 0.0 (un matériau prévu jamais déclaré : _quantite_reelle_depuis_registre rend
    -0.0) : même valeur mathématique, jamais un signe fabriqué pour un vrai négatif — inchangé
    pour toute valeur non nulle."""
    return None if valeur is None else str(valeur + 0.0)


def _evaluer_et_publier_variance(wct_recu: dict[str, Any]) -> dict[str, Any]:
    """Compare le prévu (m6_enregistrer_besoins_prevus) au réel déclaré pour ce wct_id
    (m6_declarer_materiaux_utilises, T1.1-d2) et publie `m6.variance_chantier`. DÉTERMINISTE
    (DEPARTEMENTS.md), aucune donnée inventée — SEULE fonction qui calcule ce verdict et publie
    l'événement ; les trois déclencheurs (voir docstring du module) l'appellent avec le MÊME
    `wct_recu` (wct_id, intervention_id, devis_id, horodatage_completion — `wct_recus.py`).

    N'écrit jamais le registre de mouvements ni celui des besoins prévus (lecture seule) ;
    appelable SEULEMENT dans la transaction de l'outil (`stockage.connexion_courante() is not
    None`) — les trois appelants le garantissent déjà, chacun pour la même raison que
    `m4_completer_intervention` : publier hors transaction n'aurait aucun sens à écrire.

    Le seuil vient TOUJOURS de `_seuil_variance_chantier()` (department.yaml/configuration),
    jamais d'un nombre codé en dur ici : absent ou invalide, `statut_variance="seuil_absent"`
    AVANT toute tentative de lecture du prévu ou de la déclaration (fail-closed le plus tôt
    possible). Sinon, prévu absent (aucun besoin enregistré pour le devis_id du WCT) donne
    `prevu_absent` ; prévu présent mais aucune déclaration pour ce wct_id donne
    `declaration_absente` ; les deux présents donnent `evaluee`.

    `chantier_id` (minimum requis par le catalogue) est résolu depuis QUELLE QUE SOIT la source
    disponible (le prévu, s'il existe — sinon la déclaration, si elle existe déjà malgré
    l'absence de prévu) ; `None` si aucune des deux ne le connaît encore — jamais deviné.

    `evenement_id` = `f"m6-variance-{wct_id}-{statut_variance}"` (correctif : plus seulement
    `f"m6-variance-{wct_id}"`) : chaque STATUT distinct d'un WCT n'est publié qu'une fois — une
    réévaluation qui retombe sur le MÊME statut qu'avant (ex. deux appels de suite alors que la
    déclaration manque encore) republie le même id, donc un no-op du bus, jamais un doublon ; une
    réévaluation qui change de statut (ex. la déclaration arrive enfin : declaration_absente ->
    evaluee) publie un événement DISTINCT, que le consommateur de M4 reçoit et traite normalement
    — c'est exactement ce que corrige cette fonction : avant, le même id pour tous les statuts
    faisait taire toute réévaluation après la première publication.

    `evaluee` est TERMINAL pour un WCT : `evaluee` déjà publié -> court-circuit immédiat, aucune
    réévaluation ni republication, quel que soit le déclencheur qui rappelle cette fonction. En
    pratique, les trois déclencheurs sont chacun déjà idempotents en amont (un WCT redélivré, une
    déclaration ou un devis_id déjà enregistrés ne rappellent jamais cette fonction une seconde
    fois pour le même WCT), donc ce court-circuit est une défense EXPLICITE de plus, pas la seule.
    """
    wct_id = wct_recu["wct_id"]
    intervention_id = wct_recu["intervention_id"]
    devis_id = wct_recu.get("devis_id")
    horodatage_completion = wct_recu["horodatage_completion"]

    if evenements.deja_publie(f"m6-variance-{wct_id}-evaluee"):
        return {"traite": True, "statut_variance": "evaluee"}

    mouvements = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE)
    besoins = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_BESOINS_PREVUS)

    def _chantier_id_depuis_declaration() -> str | None:
        for mouvement in mouvements:
            if mouvement.get("wct_id") == wct_id:
                return mouvement["chantier_id"]
        return None

    seuil = _seuil_variance_chantier()
    besoin = besoins_prevus.pour_devis(devis_id, besoins) if devis_id else None
    declaration_existe = any(mouvement.get("wct_id") == wct_id for mouvement in mouvements)
    lignes = None  # requis, mais nul tant que statut_variance != "evaluee" (même patron que
    # signal_critique) : le détail par matériau n'existe que quand variance_chantier.evaluer a
    # réellement tourné.

    if seuil is None:
        statut_variance = "seuil_absent"
        signal_critique = None
        chantier_id = besoin["chantier_id"] if besoin is not None else _chantier_id_depuis_declaration()
    elif besoin is None:
        statut_variance = "prevu_absent"
        signal_critique = None
        chantier_id = _chantier_id_depuis_declaration()
    elif not declaration_existe:
        statut_variance = "declaration_absente"
        signal_critique = None
        chantier_id = besoin["chantier_id"]
    else:
        chantier_id = besoin["chantier_id"]
        registre_cible = registre_module.Registre(maillons=mouvements)
        resultat, code = variance_chantier.evaluer(
            chantier_id, besoin["lignes"], seuil_pourcentage=seuil,
            registre=registre_cible, wct_id=wct_id,
        )
        if code is not None:
            # Entrées déjà validées à l'écriture (besoins_prevus.enregistrer,
            # soumettre_materiaux_utilises, _seuil_variance_chantier) : un refus ici trahirait
            # une incohérence interne, jamais un cas d'usage normal — mieux vaut une panne
            # explicite (retraitée par le répartiteur : réessais puis quarantaine, ou propagée
            # tel quel à l'outil appelant si déclenchée hors répartiteur) qu'un statut d'événement
            # fabriqué pour un cas qu'on n'a pas su nommer.
            raise RuntimeError(f"variance_chantier.evaluer a refusé une entrée déjà validée : {code}")
        statut_variance = "evaluee"
        signal = resultat["signal_variance_critique"]
        signal_critique = signal is not None
        # Détail par matériau (M3 T1.2-d en second ordre, M8) : dérivé TEL QUEL des verdicts déjà
        # calculés par variance_chantier.evaluer -- aucun nouveau calcul. "critique" par ligne
        # reprend la MÊME appartenance à materiaux_en_ecart_critique que
        # variance_chantier._construire_signal_si_critique a déjà décidée (le seuil comparé une
        # seule fois, là-bas), jamais une comparaison au seuil refaite ici. Quantités et écart en
        # texte décimal (_texte_decimal) : jamais un nombre JSON, dont la précision de lecture
        # varierait d'un consommateur à l'autre -- même discipline que
        # contrats_sortie.montant_decimal_a_la_frontiere (str() avant toute conversion Decimal).
        materiaux_critiques = set(signal["materiaux_en_ecart_critique"]) if signal is not None else set()
        lignes = [
            {
                "materiau": verdict["materiau_id"],
                "unite": verdict["unite"],
                "quantite_prevue": _texte_decimal(verdict["quantite_estimee"]),
                "quantite_reelle": _texte_decimal(verdict["quantite_reelle"]),
                "ecart_pourcentage": _texte_decimal(verdict["ecart_pourcentage"]),
                "critique": verdict["materiau_id"] in materiaux_critiques,
            }
            for verdict in resultat["verdicts_materiaux"]
        ]

    ident = f"m6-variance-{wct_id}-{statut_variance}"
    resultat_evenement = {
        "evenement_id": ident,
        "wct_id": wct_id,
        "intervention_id": intervention_id,
        "chantier_id": chantier_id,
        "statut_variance": statut_variance,
        "signal_critique": signal_critique,
        "seuil_pourcentage": seuil,
        "horodatage_completion": horodatage_completion,
        "lignes": lignes,
    }
    evenements.publier("m6.variance_chantier", _DEPARTEMENT, resultat_evenement, evenement_id=ident)
    return {"traite": True, "statut_variance": statut_variance}


def _reevaluer_si_wct_connu_par_wct_id(wct_id: str) -> None:
    """Rappelle `_evaluer_et_publier_variance` SEULEMENT si M6 a déjà reçu ce WCT (sinon, rien à
    réévaluer : `_recevoir_travaux_termines`, quand ce WCT sera livré, partira d'un registre où
    cette déclaration existe déjà et calculera `evaluee` directement). Seulement dans la
    transaction de l'outil — jamais hors transaction (tests en mémoire), où rien n'est publié."""
    if stockage.connexion_courante() is None:
        return
    wct_recu = wct_recus.pour_wct_id(wct_id, stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_WCT_RECUS))
    if wct_recu is not None:
        _evaluer_et_publier_variance(wct_recu)


def _reevaluer_si_wct_connu_par_devis_id(devis_id: str) -> None:
    """Symétrique de `_reevaluer_si_wct_connu_par_wct_id`, mais pour le déclencheur
    `m6_enregistrer_besoins_prevus` (le prévu arrive après la complétion, T1.2-d)."""
    if stockage.connexion_courante() is None:
        return
    wct_recu = wct_recus.pour_devis_id(devis_id, stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_WCT_RECUS))
    if wct_recu is not None:
        _evaluer_et_publier_variance(wct_recu)


def enregistrer_besoins_prevus(
    chantier_id: str, devis_id: str, lignes: list[dict[str, Any]],
    registre_historique: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """PLAN T1.2-b, point 2 : garde le prévu (source M3, T2.3-a — fourni directement par
    l'appelant pour l'instant, par événement plus tard). Idempotent par devis_id.

    Correctif (le prévu peut arriver APRÈS la complétion, T1.2-d) : si un WCT déjà reçu porte ce
    devis_id, réévalue et republie m6.variance_chantier tout de suite — sans attendre une
    prochaine livraison de m4.travaux_termines qui n'arrivera jamais deux fois."""
    maillons = _besoins_prevus_de_l_appel(registre_historique)
    enregistrement, code = besoins_prevus.enregistrer(chantier_id, devis_id, lignes, maillons)
    if code is not None:
        return {"accepte": False, "verdict": {"code": code}}
    maillons.append(enregistrement)
    if stockage.connexion_courante() is not None:
        _reevaluer_si_wct_connu_par_devis_id(devis_id)
        return {"accepte": True, "resultat": enregistrement}
    return {"accepte": True, "resultat": enregistrement, "registre_historique": list(maillons)}


def receptionner_commande(
    bon_demande: dict[str, Any],
    reception_po: dict[str, Any],
    catalogue_materiaux: dict[str, Any] | None = None,
    seuils_reorder: list[dict[str, Any]] | None = None,
    registre_historique: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    registre_cible = _registre_de_l_appel(registre_historique)
    resultat, code = materiel.enregistrer_reception(
        bon_demande, reception_po, catalogue_materiaux, registre_cible, seuils=seuils_reorder
    )
    if code is not None:
        return {"accepte": False, "verdict": {"code": code}}
    return {"accepte": True, "resultat": resultat, **_etat_registre(registre_cible)}


def consommer_materiaux(
    wct: dict[str, Any],
    formulaire: dict[str, Any],
    registre_historique: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    registre_cible = _registre_de_l_appel(registre_historique)
    resultat, code = materiel.consommer_materiaux(wct, formulaire, registre_cible)
    if code is not None:
        return {"accepte": False, "verdict": {"code": code}}
    return {"accepte": True, "resultat": resultat, **_etat_registre(registre_cible)}


def declarer_materiaux_utilises(
    wct: dict[str, Any],
    formulaire: dict[str, Any],
    registre_historique: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """PLAN T1.1-d2 point 2. En transaction (production) : registre durable, réponse
    tête + taille seulement (_etat_registre), comme les autres outils d'écriture.

    Correctif (la déclaration arrive presque toujours APRÈS la complétion, R12 §4/§9.7) : si un
    WCT déjà reçu porte ce wct_id, réévalue et republie m6.variance_chantier tout de suite — sans
    attendre une prochaine livraison de m4.travaux_termines qui n'arrivera jamais deux fois."""
    registre_cible = _registre_de_l_appel(registre_historique)
    resultat, code = materiel.soumettre_materiaux_utilises(wct, formulaire, registre_cible)
    if code is not None:
        return {"accepte": False, "verdict": {"code": code}}
    if stockage.connexion_courante() is not None:
        _reevaluer_si_wct_connu_par_wct_id(formulaire["wct_id"])
    return {"accepte": True, "resultat": resultat, **_etat_registre(registre_cible)}


def soumettre_comptage(
    comptage: dict[str, Any], registre_historique: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    registre_cible = _registre_de_l_appel(registre_historique)
    resultat, code = materiel.soumettre_comptage(comptage, registre_cible)
    if code is not None:
        return {"accepte": False, "verdict": {"code": code}}
    return {"accepte": True, "resultat": resultat, **_etat_registre(registre_cible)}


def produire_digest(
    registre_historique: list[dict[str, Any]] | None = None,
    seuils_reorder: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    registre_cible = _registre_de_l_appel(registre_historique)
    return digest.produire_digest_quotidien(registre_cible, seuils_reorder or [])


def resoudre_prix_materiau(
    materiau_id: str,
    catalogue_materiaux: dict[str, Any] | None = None,
    registre_historique: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    registre_cible = _registre_de_l_appel(registre_historique)
    return catalogue_module.resoudre_prix(materiau_id, catalogue_materiaux, registre_cible)


def evaluer_variance_chantier(
    chantier_id: str,
    besoins_estimes: list[dict[str, Any]],
    seuil_pourcentage: float,
    lignes_declarees: list[dict[str, Any]] | None = None,
    wct_id: str | None = None,
    registre_historique: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """PLAN T1.1-d/d2 points 2 et 3. variance_chantier.evaluer n'écrit jamais le registre
    (T0, lecture/calcul pur) mais peut désormais le LIRE (PLAN T1.1-d2 point 3) : le
    registre est donc toujours résolu (comme m6_produire_digest/m6_resoudre_prix_materiau,
    d'autres outils T0 qui lisent sans écrire), et utilisé seulement si `lignes_declarees`
    est omis. `lignes_declarees` explicite reste utilisable tel quel (entrée directe
    gardée, comme demandé)."""
    registre_cible = _registre_de_l_appel(registre_historique)
    resultat, code = variance_chantier.evaluer(
        chantier_id,
        besoins_estimes,
        lignes_declarees,
        seuil_pourcentage,
        registre=registre_cible,
        wct_id=wct_id,
    )
    if code is not None:
        return {"accepte": False, "verdict": {"code": code}}
    return {"accepte": True, "resultat": resultat}


def outils() -> tuple[Outil, ...]:
    return (
        Outil(
            nom="m6_receptionner_commande",
            description=(
                "Réceptionne une commande de bout en bout : résout le prix par ligne (catalogue -> "
                "historique -> indéterminé), écrit le stock reçu, calcule le verdict de réception "
                "(conforme/inférieure/supérieure/mixte), émet un signal à M5 si un montant est dû "
                "(jamais si indéterminé) et des suggestions de réapprovisionnement si un seuil est fourni."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "bon_demande": _BON_DEMANDE,
                    "reception_po": _RECEPTION_PO,
                    "catalogue_materiaux": _CATALOGUE,
                    "seuils_reorder": _SEUILS_REORDER,
                    "registre_historique": _REGISTRE_HISTORIQUE,
                },
                "required": ["bon_demande", "reception_po"],
                "additionalProperties": False,
            },
            fonction=receptionner_commande,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m6_consommer_materiaux",
            description=(
                "Confirme une consommation de matériaux sur une intervention terrain (WCT de M4), "
                "décrémente le stock localisé du chantier. Refuse fail-closed si le stock disponible "
                "est insuffisant. La confirmation ne porte jamais de coût."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "wct": _WCT,
                    "formulaire": _FORMULAIRE_CONSOMMATION,
                    "registre_historique": _REGISTRE_HISTORIQUE,
                },
                "required": ["wct", "formulaire"],
                "additionalProperties": False,
            },
            fonction=consommer_materiaux,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m6_declarer_materiaux_utilises",
            description=(
                "Déclare le formulaire de fin de chantier enrichi (M6.10/M6.11 ; lignes typées "
                "prévu/non prévu/retour/perte/bris/achat terrain — achat terrain refusé fail-closed "
                "sans photo ni reçu) et l'écrit au registre : CONSOMMATION pour prévu/non prévu/achat "
                "terrain, RETOUR pour un retour (réintègre le stock), PERTE/BRIS pour une perte ou un "
                "bris (sortent du stock sans être une consommation de chantier). Même règle de coût "
                "unitaire fail-closed que m6_consommer_materiaux, aucun coût inventé. Idempotente par "
                "wct_id : une seconde déclaration pour le même WCT est refusée nommément, jamais "
                "réécrite. Distincte de m6_consommer_materiaux, qui garde son contrat "
                "{materiau_id, quantite} exact et n'est pas remplacé."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "wct": _WCT,
                    "formulaire": _FORMULAIRE_MATERIAUX_UTILISES,
                    "registre_historique": _REGISTRE_HISTORIQUE,
                },
                "required": ["wct", "formulaire"],
                "additionalProperties": False,
            },
            fonction=declarer_materiaux_utilises,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m6_soumettre_comptage",
            description=(
                "Compare un comptage physique au stock théorique dérivé du registre et enregistre le "
                "constat (AUCUN_ECART/STOCK_INFERIEUR/STOCK_SUPERIEUR/INDETERMINE). Jamais de cause "
                "ni de responsable attribué automatiquement (R-020)."
            ),
            parametres={
                "type": "object",
                "properties": {"comptage": _COMPTAGE, "registre_historique": _REGISTRE_HISTORIQUE},
                "required": ["comptage"],
                "additionalProperties": False,
            },
            fonction=soumettre_comptage,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m6_produire_digest",
            description=(
                "Digest quotidien déterministe : variances d'inventaire du registre et suggestions "
                "de réapprovisionnement recalculées contre les seuils fournis. Lecture seule."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "registre_historique": _REGISTRE_HISTORIQUE,
                    "seuils_reorder": _SEUILS_REORDER,
                },
                "required": [],
                "additionalProperties": False,
            },
            fonction=produire_digest,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m6_resoudre_prix_materiau",
            description=(
                "Résout le coût unitaire d'un matériau : catalogue fourni -> dernier prix du "
                "registre -> indéterminé. Calcul pur, aucune écriture."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "materiau_id": {"type": "string"},
                    "catalogue_materiaux": _CATALOGUE,
                    "registre_historique": _REGISTRE_HISTORIQUE,
                },
                "required": ["materiau_id"],
                "additionalProperties": False,
            },
            fonction=resoudre_prix_materiau,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m6_evaluer_variance_chantier",
            description=(
                "Compare les besoins matériaux estimés (M3, toujours fournis en entrée) au réel "
                "déclaré au formulaire de fin de chantier enrichi (lignes typées prévu/non prévu/"
                "retour/perte/bris/achat terrain) et calcule un verdict neutre par matériau. Le réel "
                "vient soit de lignes_declarees fourni explicitement, soit — si omis — relu "
                "directement au registre pour wct_id (une déclaration précise) ou chantier_id seul "
                "(tout le réel déclaré du chantier), déjà écrit par m6_declarer_materiaux_utilises. Ne "
                "classe jamais la cause : cause_possible reste toujours null (classification humaine "
                "uniquement parmi les 6 causes nommées de la définition produit, jamais « vol ») et "
                "classification_requise indique si un écart attend cette classification. Émet "
                "SignalVarianceChantierCritique quand l'écart d'au moins un matériau atteint ou "
                "dépasse seuil_pourcentage, toujours fourni par l'appelant, jamais codé en dur. M6 "
                "signale seulement : ce signal ne modifie jamais le statut du chantier côté M4. "
                "Lecture et calcul purs, aucune écriture au registre."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "chantier_id": {"type": "string"},
                    "besoins_estimes": _BESOINS_ESTIMES_CHANTIER,
                    "lignes_declarees": {
                        **_LIGNES_DECLAREES_CHANTIER,
                        "description": (
                            "Réel déclaré explicite. À omettre pour lire le réel directement au "
                            "registre (wct_id ou chantier_id seul) plutôt que de le retransporter."
                        ),
                    },
                    "wct_id": {
                        "type": "string",
                        "description": (
                            "Utilisé seulement quand lignes_declarees est omis : cible une seule "
                            "déclaration au registre. Omis avec lignes_declarees : agrège tout le réel "
                            "déclaré du chantier."
                        ),
                    },
                    "seuil_pourcentage": {
                        "type": "number",
                        "description": (
                            "Fraction (0.40 = 40 %). Toujours fourni par l'appelant : aucune valeur "
                            "par défaut n'existe dans le code."
                        ),
                    },
                    "registre_historique": _REGISTRE_HISTORIQUE,
                },
                "required": ["chantier_id", "besoins_estimes", "seuil_pourcentage"],
                "additionalProperties": False,
            },
            fonction=evaluer_variance_chantier,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m6_enregistrer_besoins_prevus",
            description=(
                "Enregistre les besoins matériaux ESTIMÉS d'un chantier (le prévu : matériau, "
                "quantité estimée, unité — source le devis M3, fourni directement pour l'instant, "
                "par événement plus tard). Aucun montant. Idempotent par devis_id : une seconde "
                "tentative pour le même devis_id est refusée nommément, jamais réécrite ni "
                "fusionnée. C'est ce prévu que le consommateur de m4.travaux_termines compare "
                "au réel déclaré (m6_declarer_materiaux_utilises) pour publier m6.variance_chantier."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "chantier_id": {"type": "string"},
                    "devis_id": {"type": "string"},
                    "lignes": _BESOINS_ESTIMES_CHANTIER,
                    "registre_historique": _REGISTRE_HISTORIQUE,
                },
                "required": ["chantier_id", "devis_id", "lignes"],
                "additionalProperties": False,
            },
            fonction=enregistrer_besoins_prevus,
            autonomie=Autonomie.T1,
        ),
    )


# ---------------------------------------------------------------------------------------------
# Consommateurs d'événements (ADR-0009 §3, PLAN T1.2, point 3 ; correctif : le trou du flux réel)
# ---------------------------------------------------------------------------------------------
# Même module que `outils()` (docs/architecture/DEPARTEMENTS.md) : seul cet adaptateur connaît
# `opsys`/`opsys.evenements` ; `variance_chantier.py` (module pur) fait le calcul déterministe.
# Le répartiteur (`opsys.evenements.repartir`) n'appelle cette fonction que dans une transaction
# déjà ouverte : le registre durable fait donc TOUJOURS autorité ici (comme `enregistrer_besoins_prevus`
# en transaction), sans le mode « en mémoire » des tests unitaires hors transaction ci-dessus.
def _recevoir_travaux_termines(charge: dict[str, Any]) -> dict[str, Any]:
    """Consomme `m4.travaux_termines` : garde ce que M6 vient de recevoir de ce WCT (wct_id,
    intervention_id, devis_id, horodatage_completion — `wct_recus.py`, idempotent par wct_id),
    puis délègue tout le calcul et la publication à `_evaluer_et_publier_variance` (fonction
    UNIQUE, partagée avec `m6_declarer_materiaux_utilises` et `m6_enregistrer_besoins_prevus` —
    voir sa docstring pour le détail des statuts, du seuil et de `chantier_id`).

    Dans le flux réel (R12 §4, §9.7), la déclaration des matériaux — et parfois le prévu M3
    (T1.2-d) — arrivent presque toujours APRÈS ce WCT : ce premier appel publiera donc le plus
    souvent `prevu_absent` ou `declaration_absente`. Ce n'est plus terminal : garder ce WCT ici
    permet aux deux autres déclencheurs de le retrouver (par wct_id, par devis_id) quand la
    pièce qui manquait arrive, et de réévaluer par la MÊME fonction — le correctif au trou où,
    avant, rien ne rappelait jamais ce consommateur une seconde fois pour le même WCT.
    """
    wct_recus_registre = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_WCT_RECUS)
    wct_recu = wct_recus.pour_wct_id(charge["wct_id"], wct_recus_registre)
    if wct_recu is None:
        wct_recu = wct_recus.construire(
            charge["wct_id"], charge["intervention_id"], charge.get("devis_id"),
            charge["horodatage_completion"],
        )
        wct_recus_registre.append(wct_recu)
    return _evaluer_et_publier_variance(wct_recu)


def consommateurs() -> dict[str, Callable[[dict], dict]]:
    return {"m4.travaux_termines": _recevoir_travaux_termines}
