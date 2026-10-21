"""Capacités d'agent du département M6 Material Control.

Chaque outil enveloppe l'orchestrateur unique `materiel.py` (seul point d'écriture par
type de mouvement — RECEPTION/CONSOMMATION/VARIANCE_INVENTAIRE, DA-M6-11 ; RETOUR/PERTE/
BRIS depuis PLAN T1.1-d2, garde_ecriture_stock de conformite.py). `m6_receptionner_commande`
compose de bout en bout : réception -> écriture du stock -> résolution de prix -> variance
de réception -> signal à M5 -> suggestion de réapprovisionnement, en un seul appel.
`m6_declarer_materiaux_utilises` (PLAN T1.1-d2) fait de même pour la fin de chantier :
formulaire enrichi -> mouvements typés (CONSOMMATION/RETOUR/PERTE/BRIS) -> stock théorique
cohérent, idempotent par wct_id avec conflit nommé si le contenu du WCT diverge. Depuis PLAN T1.4-i,
l'appelant ne fournit plus le WCT, seulement
son `wct_id` : M6 relit la charge `m4.travaux_termines` publiée par M4 (`evenements.charge_publiee`,
le magasin du bus — AGENTS.md : un fait vient de sa source de vérité, jamais de l'appelant) et la
valide comme avant ; un `wct_id` que M4 n'a jamais publié est refusé (`REJ-WCT-INCONNU`).

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

PLAN T2.3-e : `_recevoir_besoins_materiaux` consomme `m3.besoins_materiaux` (les besoins d'une ESTIMATION,
avant le devis) et les range comme prévu PROVISOIRE dans le registre `besoins_prevus` existant, après
une validation propre à M6 (`besoins_materiaux_recus.py`). Un contrat invalide lève : réessais puis
quarantaine. Recevoir n'est jamais acheter — aucun PO, aucune réservation, aucun mouvement de stock.

PLAN T1.5-d : `declarer_materiaux_utilises`, qui sort du stock, évalue ensuite le stock bas de chaque article
touché (`_constater_stock_des_articles`, règle écrite dans `reapprovisionnement.py`, seuil et quantité cible
par article dans `department.yaml/configuration`) : un besoin de commande si le stock est sous le seuil, un
signal « seuil non configuré » si l'article n'a pas de paramètres utilisables — jamais un seuil deviné, jamais
un bon de commande créé seul. `attentes()` rend l'état COURANT de ces constats à la file de l'admin.

PLAN T4.14 (M6.8, M6.9, M6.4) : réservation par chantier, emplacements et « matériel prêt ». Le consommateur de
`m3.devis_accepte` réserve, dans la MÊME transaction que le prévu, ce qui est disponible pour le devis
(`reservations.py`) et publie `m6.materiel_pret` (`pret`, `partiel` ou `a_commander`, avec les lignes manquantes) : M4
le lit. `disponible = en main - réservé` (`stock.deriver_disponibilite`) alimente le réapprovisionnement. Tout ce qui
change l'en main (réception, déclaration des matériaux, transfert hors main, libération) réconcilie les réservations
(`_reconcilier_reservations`) : le réservé ne dépasse jamais l'en main, le stock n'est jamais négatif. Les emplacements
et leurs transferts audités (`emplacements.py`) vivent dans un registre à part : la chaîne de mouvements ne change
pas d'un octet. Aucun bon de commande n'est créé seul : `a_commander` dit ce qui manque, commander reste le geste
d'un humain (`m6_creer_po_brouillon`, puis approbation). Quatre outils : `m6_reserver_materiel`,
`m6_liberer_reservation` (N2), `m6_transferer_stock`, `m6_lire_disponibilite` (T0) ; ils ne fonctionnent que dans la
transaction de l'outil (registres durables).

PLAN T4.15 (M6.16, pont finance vers M5) : `receptionner_commande`, pour un PO PERSISTÉ, publie
`m6.reception_enregistree` dans la MÊME transaction que le stock et la transition du PO
(`evenement_reception.py` construit la charge ; ici, la publication, seule). Une réception qui n'apparie aucune
ligne, ou qui ne se rattache à aucun PO persisté (pas de fournisseur : M5 n'aurait personne à qui devoir), ne
publie rien. Une quantité reçue négative ou non finie, ou un horodatage sans fuseau, est refusé AVANT toute
écriture (`evenement_reception.verifier_reception`) : M5 en tire de l'argent à payer. M6 ne calcule aucun montant
et ne paie rien ; il ne convertit aucune unité (le livre de prix n'en déclare pas : GATE NATHAN).
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select

from opsys import approbations, contexte, evenements, fichiers, stockage
from opsys.evenements.schemas import erreurs_charge
from opsys.outils import Autonomie, Niveau, Outil
from opsys.stockage import codec
from opsys.stockage.maillons import EcritureConcurrente
from opsys.stockage.schema import EVENEMENTS_SORTANTS, REGISTRES

from . import (
    acces,
    besoins_materiaux_recus,
    besoins_prevus,
    bons_commande,
    classement_variance_appareil,
    contexte_materiaux_appareil,
    contrats,
    digest,
    emplacements,
    encodage,
    evenement_reception,
    fournisseurs,
    livre_prix,
    materiel,
    pertes_appareil,
    preuves_pertes_bris,
    preuves_pertes_bris_appareil,
    reapprovisionnement,
    reapprovisionnement_appareil,
    reception,
    reservations,
    stock,
    validation,
    variance_chantier,
    verdicts,
    wct_recus,
)
from . import catalogue as catalogue_module
from . import registre as registre_module

_DEPARTEMENT = "m06-material-control"
_NOM_REGISTRE = "principal"
_NOM_REGISTRE_BESOINS_PREVUS = "besoins_prevus"
_NOM_REGISTRE_WCT_RECUS = "wct_recus"
_NOM_REGISTRE_FOURNISSEURS = "fournisseurs"
_NOM_REGISTRE_LIVRE_PRIX = "livre_prix"
_NOM_REGISTRE_BONS_COMMANDE = "bons_commande"
_NOM_REGISTRE_BESOINS_COMMANDE = "besoins_commande"
_NOM_REGISTRE_RESERVATIONS = "reservations"
_NOM_REGISTRE_EMPLACEMENTS = "emplacements"
_MANIFESTE = Path(__file__).resolve().parents[2] / "department.yaml"
_TYPE_EVENEMENT_WCT = "m4.travaux_termines"

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
_WCT_ID = {
    "type": "string",
    "description": "Identifiant du WCT tel que M4 l'a publié (m4.travaux_termines) ; M6 en relit la charge.",
}
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
# --------------------------------------------------------------------------------------- T2.4/T2.5
_FOURNISSEURS_HISTORIQUE = {
    "type": "array",
    "items": {"type": "object"},
    "description": "À omettre : le registre des fournisseurs est durable et relu par l'outil.",
}
_LIVRE_PRIX_HISTORIQUE = {
    "type": "array",
    "items": {"type": "object"},
    "description": "À omettre : le livre de prix est durable et relu par l'outil.",
}
_BESOINS_PREVUS_HISTORIQUE = {
    "type": "array",
    "items": {"type": "object"},
    "description": "À omettre : le registre des besoins prévus est durable et relu par l'outil.",
}
_BONS_COMMANDE_HISTORIQUE = {
    "type": "array",
    "items": {"type": "object"},
    "description": "À omettre : le registre des PO est durable et relu par l'outil.",
}
_CATEGORIES_VENDUES = {"type": ["array", "null"], "items": {"type": "string"}}


_EMPLACEMENT = {
    "type": "object",
    "description": (
        "Un emplacement de la liste fermée. `reference` (lequel) est requise pour camion, remorque, employe, "
        "chantier et fournisseur, et interdite pour depot, retour, rebut et inconnu."
    ),
    "properties": {
        "type": {"type": "string", "enum": sorted(emplacements.EMPLACEMENTS)},
        "reference": {"type": ["string", "null"]},
    },
    "required": ["type"],
    "additionalProperties": False,
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


# --------------------------------------------------------------------------------------- T2.4/T2.5
# Fournisseurs, livre de prix, PO : trois registres durables DISTINCTS de plus (même patron que
# _besoins_prevus_de_l_appel ci-dessus) — aucun des trois ne porte de mouvement de stock, donc
# aucun ne passe par registre_module.Registre (réservé à RECEPTION/CONSOMMATION/...).
def _fournisseurs_de_l_appel(historique: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if stockage.connexion_courante() is not None:
        return stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_FOURNISSEURS)
    return list(historique or [])


def _livre_prix_de_l_appel(historique: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if stockage.connexion_courante() is not None:
        return stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_LIVRE_PRIX)
    return list(historique or [])


def _bons_commande_de_l_appel(historique: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if stockage.connexion_courante() is not None:
        return stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_BONS_COMMANDE)
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


def _seuil_ecart_prix_reception() -> float | None:
    """Seuil de criticité de l'ÉCART DE PRIX à la réception (M6.7, PLAN T2.5 point 4) : même
    source (`department.yaml/configuration`) et même discipline fail-closed que
    `_seuil_variance_chantier` (même forme de valeur — une fraction positive — donc même
    validateur, `validation.valider_seuil_variance_chantier`, réutilisé tel quel plutôt que
    dupliqué). Absent ou invalide : `None`, jamais un défaut inventé — `receptionner_commande`
    rend alors une liste de signaux vide plutôt que d'évaluer quoi que ce soit."""
    donnees = yaml.safe_load(_MANIFESTE.read_text(encoding="utf-8")) or {}
    configuration = donnees.get("configuration") or {}
    seuil = configuration.get("seuil_ecart_prix_reception_pourcentage")
    ok, _ = validation.valider_seuil_variance_chantier(seuil)
    return seuil if ok else None


def _articles_reapprovisionnement() -> dict[str, Any] | None:
    """Seuil de réapprovisionnement et quantité cible PAR ARTICLE (M6.15, PLAN T1.5-d) : le bloc
    `configuration.reapprovisionnement.articles` de `department.yaml`, même source et même discipline
    fail-closed que `_seuil_variance_chantier`. Aucun défaut n'est fourni : un bloc absent est `{}`, donc
    chaque article touché est signalé « seuil non configuré » (`reapprovisionnement.lire_parametres`).
    `None` dit que le bloc existe mais n'est pas un dictionnaire (illisible) : c'est aussi visible, jamais
    lu comme « rien à configurer ». La validité de chaque article est jugée article par article, à
    l'évaluation : un article mal écrit ne rend pas les autres inutilisables."""
    donnees = yaml.safe_load(_MANIFESTE.read_text(encoding="utf-8")) or {}
    configuration = donnees.get("configuration") or {}
    section = configuration.get("reapprovisionnement")
    if section is None:
        return {}
    if not isinstance(section, dict):
        return None
    articles = section.get("articles")
    if articles is None:
        return {}
    return articles if isinstance(articles, dict) else None


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
    disponible (le prévu, s'il existe et le connaît — sinon la déclaration, si elle existe déjà)
    ; `None` si aucune des deux ne le connaît encore — jamais deviné. Depuis T1.2-d, le prévu
    PEUT exister sans connaître son chantier (`m3.devis_accepte.chantier_id` est nullable : un
    devis peut être accepté avant que M4 planifie) : la déclaration, qui le connaît TOUJOURS
    (`m6_declarer_materiaux_utilises` l'exige), le résout alors — la seule fois où ça compte
    vraiment est celle où `variance_chantier.evaluer` en a besoin pour filtrer les BONS
    mouvements, dans la branche `evaluee` ci-dessous.

    `evenement_id` = `f"m6-variance-{wct_id}-{statut_variance}"` (correctif : plus seulement
    `f"m6-variance-{wct_id}"`) : chaque STATUT distinct d'un WCT n'est publié qu'une fois — une
    réévaluation qui retombe sur le MÊME statut qu'avant (ex. deux appels de suite alors que la
    déclaration manque encore) rejoue la première enveloppe de ce statut, jamais un doublon. La
    déclaration tardive reste durable même si elle précise maintenant le chantier ; une
    réévaluation qui change de statut (ex. la déclaration arrive enfin : declaration_absente ->
    evaluee) publie un événement DISTINCT, que le consommateur de M4 reçoit et traite normalement
    — c'est exactement ce que corrige cette fonction : avant, le même id pour tous les statuts
    faisait taire toute réévaluation après la première publication.

    `evaluee` est TERMINAL pour un WCT : `evaluee` déjà publié -> court-circuit immédiat, aucune
    réévaluation ni nouvelle publication ; seul le rejeu strict de cette enveloppe vérifie encore
    son producteur, quel que soit le déclencheur qui rappelle cette fonction. En
    pratique, les trois déclencheurs sont chacun déjà idempotents en amont (un WCT redélivré, une
    déclaration ou un devis_id déjà enregistrés ne rappellent jamais cette fonction une seconde
    fois pour le même WCT), donc ce court-circuit est une défense EXPLICITE de plus, pas la seule.
    """
    wct_id = wct_recu["wct_id"]
    intervention_id = wct_recu["intervention_id"]
    devis_id = wct_recu.get("devis_id")
    horodatage_completion = wct_recu["horodatage_completion"]

    ident_terminal = f"m6-variance-{wct_id}-evaluee"
    terminal = evenements.charge_publiee("m6.variance_chantier", ident_terminal)
    if terminal is not None:
        # Preserve the terminal fact, while still checking its expected producer through the bus.
        evenements.publier("m6.variance_chantier", _DEPARTEMENT, terminal, evenement_id=ident_terminal)
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
        # T1.2-d : le prévu peut ne pas connaître son chantier (devis accepté avant planification
        # M4) ; la déclaration, elle, le connaît toujours (`m6_declarer_materiaux_utilises`
        # l'exige) -- on la préfère ici, JAMAIS `besoin["chantier_id"]` seul, parce que
        # `variance_chantier.evaluer` s'en sert pour FILTRER les mouvements déclarés
        # (`comparer_depuis_registre` compare par chantier_id ET wct_id) : lui passer None alors
        # que de vrais mouvements existent sous un chantier_id réel ferait tout apparaître comme
        # non déclaré.
        chantier_id = besoin["chantier_id"] or _chantier_id_depuis_declaration()
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
    premiere = evenements.charge_publiee("m6.variance_chantier", ident)
    evenements.publier(
        "m6.variance_chantier", _DEPARTEMENT,
        premiere if premiere is not None else resultat_evenement, evenement_id=ident,
    )
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


# ---------------------------------------------------------------------------------------------- T4.14
# Réservation par chantier (M6.8), emplacements (M6.9), « matériel prêt » (M6.4). Règles pures : `reservations.py`
# et `emplacements.py`. Ici, seulement les entrées-sorties, et seulement DANS la transaction de l'outil : les
# registres durables `reservations` et `emplacements` n'ont pas de mode « historique en mémoire ».
def _hors_transaction() -> dict[str, Any] | None:
    """Le refus quand aucun registre durable n'est joignable (appel direct, hors transaction) : rien n'est réservé,
    déplacé ni lu à moitié. `None` dans une transaction."""
    if stockage.connexion_courante() is not None:
        return None
    return {"accepte": False, "verdict": verdicts.construire_verdict(
        "REJ-M6-TRANSACTION-REQUISE",
        detail=(
            "cet outil lit et écrit les registres durables de M6 : il ne fonctionne que dans la transaction de l'outil"
        ),
    )}


def _acteur_admin_ou_agent() -> tuple[str | None, dict[str, Any] | None]:
    """Qui appelle un outil de T4.14, pour la piste d'audit : la personne dont l'identité d'appareil est CONFIRMÉE en
    base, ou `agent` pour un appel sans identité d'appareil (voie des agents, console), comme partout dans M6. Jamais
    un argument. Un rôle d'appareil autre qu'`admin` est refusé ICI aussi (`REJ-IDENTITE-APPAREIL-INVALIDE`) : le
    socle n'applique pas `roles_appareil` à un outil de lecture (T0) hors du core, et ces quatre outils portent des
    quantités sur tous les chantiers (docs/architecture/ROLES.md)."""
    acteur, verdict = _declarant_appareil()
    if verdict is not None:
        return None, verdict
    if acteur is not None and acteur.role != acces.ROLE_ADMIN:
        return None, verdicts.construire_verdict(
            "REJ-IDENTITE-APPAREIL-INVALIDE", detail="réservation, transfert et disponibilité : réservés à l'admin"
        )
    return (acteur.personne if acteur is not None else "agent"), None


def _disponibilite(materiaux: Any) -> dict[str, dict[str, Decimal]]:
    """Stock théorique, hors main, en main, réservé et disponible de chaque article demandé, lus aux registres
    durables (`stock.deriver_disponibilite`). Dans la transaction seulement."""
    return stock.deriver_disponibilite(
        materiaux,
        stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE),
        emplacements.hors_main_par_article(stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_EMPLACEMENTS)),
        reservations.reserve_par_article(stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_RESERVATIONS)),
    )


def _en_main(materiaux: Any) -> dict[str, Decimal]:
    return {materiau_id: chiffres["en_main"] for materiau_id, chiffres in _disponibilite(materiaux).items()}


def _ecrire_faits_reservation(faits: list[dict[str, Any]]) -> list[str]:
    """Range chaque fait de réservation au registre et publie son `m6.materiel_pret`, dans la transaction courante :
    le fait et son événement réussissent ou échouent ensemble. Rend les `evenement_id` publiés. La CLÔTURE n'en publie
    aucun (le chantier est terminé). LÈVE si le catalogue refuse la charge (`ChargeInvalide`) : un défaut du code,
    jamais une entrée, et mieux vaut annuler que ranger une réservation que M4 ne verra pas."""
    registre = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_RESERVATIONS)
    publies = []
    for fait in faits:
        registre.append(fait)
        if fait["evenement"] == "cloturee":
            continue
        charge = reservations.charge_materiel_pret(fait)
        evenements.publier(
            reservations.TYPE_EVENEMENT_MATERIEL_PRET, _DEPARTEMENT, charge, evenement_id=charge["evenement_id"]
        )
        publies.append(charge["evenement_id"])
    return publies


def _reconcilier_reservations(materiaux: Any, horodatage: Any) -> list[str]:
    """Rétablit `réservé <= en main` pour ces articles après un changement de l'en main (réception, sortie de stock,
    transfert hors main, libération) et complète les réservations auxquelles du stock est devenu disponible
    (`reservations.reconcilier`) ; publie `m6.materiel_pret` de chaque réservation qui change. Rend les identifiants
    publiés. Rien à faire, et rien de lu, quand aucune réservation n'est active : le comportement d'avant tout
    changement. Hors transaction : rien (aucun registre durable où écrire), comme `_reevaluer_si_wct_connu_*`."""
    if stockage.connexion_courante() is None or not isinstance(horodatage, str) or not horodatage.strip():
        return []
    if not reservations.actives(stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_RESERVATIONS)):
        return []
    articles = sorted({materiau_id for materiau_id in materiaux if isinstance(materiau_id, str)})
    faits = reservations.reconcilier(
        articles, _en_main(articles), stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_RESERVATIONS), horodatage
    )
    return _ecrire_faits_reservation(faits)


def _cloturer_et_reconcilier(devis_id: Any, wct_id: str, horodatage: Any, materiaux: Any) -> list[str]:
    """À la déclaration des matériaux d'un chantier : clôture la réservation active de son devis (ce qu'elle
    retenait redevient disponible ; la sortie de stock est déjà au registre de mouvements), puis réconcilie les
    articles touchés — par la déclaration ET par la réservation clôturée — pour les autres chantiers. Dans la
    transaction seulement."""
    if stockage.connexion_courante() is None:
        return []
    registre = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_RESERVATIONS)
    articles = set(materiaux)
    fait = reservations.cloturer(devis_id, wct_id, horodatage, registre)
    if fait is not None:
        articles |= {ligne["materiau_id"] for ligne in fait["lignes"]}
        _ecrire_faits_reservation([fait])
    return _reconcilier_reservations(articles, horodatage)


def _vue_reservation(fait: dict[str, Any]) -> dict[str, Any]:
    """Ce que la réponse d'un outil dit d'une réservation : sa charge `m6.materiel_pret` (statut, lignes, ce qui
    manque), sans l'identifiant d'événement qui n'y a pas de sens."""
    charge = reservations.charge_materiel_pret(fait)
    return {cle: valeur for cle, valeur in charge.items() if cle != "evenement_id"}


def _chantier_deja_declare(devis_id: str) -> bool:
    """Vrai si le WCT de ce devis est déjà reçu ET ses matériaux déjà déclarés : le chantier est fait, rien ne se
    réserve plus pour lui. Le cas se présente quand `m3.devis_accepte` arrive APRÈS la déclaration (ordre inversé du
    bus) : sans ce garde, une réservation resterait active à jamais pour un chantier terminé."""
    wct_recu = wct_recus.pour_devis_id(devis_id, stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_WCT_RECUS))
    if wct_recu is None:
        return False
    return any(m.get("wct_id") == wct_recu["wct_id"] for m in stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))


def _reserver_pour_devis(
    devis_id: Any, horodatage: Any, declencheur: str, *, acteur: str | None = None, re_reservation: bool = False
) -> dict[str, Any]:
    """Cœur partagé par le consommateur de `m3.devis_accepte` et l'outil `m6_reserver_materiel` : réserve ce qui est
    disponible pour ce devis à partir de son prévu DÉFINITIF (`besoins_prevus.pour_devis`), range le fait et publie
    `m6.materiel_pret`. Dans la transaction seulement. Jamais de bon de commande : `a_commander` dit ce qui manque.

    Statut rendu (`statut`) : `creee`, `deja_reservee` (aucun double), `deja_traitee` (libérée ou clôturée, et
    `re_reservation` faux), `aucun_besoin_connu` (prévu vide : rien n'est dit, jamais « prêt » par défaut),
    `chantier_deja_declare` ; ou un verdict de refus."""
    if isinstance(devis_id, str) and devis_id and _chantier_deja_declare(devis_id):
        return {"accepte": True, "statut": "chantier_deja_declare"}
    prevu = besoins_prevus.pour_devis(devis_id, stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_BESOINS_PREVUS))
    materiaux = [ligne["materiau_id"] for ligne in prevu["lignes"]] if prevu is not None else []
    registre = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_RESERVATIONS)
    resultat, verdict = reservations.reserver(
        devis_id, prevu, horodatage, declencheur, registre, _en_main(materiaux),
        acteur=acteur, re_reservation=re_reservation,
    )
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    reponse: dict[str, Any] = {"accepte": True, "statut": resultat["statut"]}
    fait = resultat["fait"]
    if fait is not None:
        (reponse["evenement_materiel_pret_id"],) = _ecrire_faits_reservation([fait])
        reponse["reservation"] = _vue_reservation(fait)
    else:
        courant = reservations.etat(devis_id, registre)
        if courant is not None:
            reponse["reservation"] = _vue_reservation(courant)
    return reponse


def _constater_stock_des_articles(
    wct_id: str, horodatage: Any, chantier_id: str, lignes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """PLAN T1.5-d (DEFINITION-PRODUIT.md §6, ligne M6 : « signale le stock bas, crée le besoin de
    commande ») : évalue le stock de chaque article que cette sortie de stock vient de toucher, et range un
    constat dans le registre durable `besoins_commande` quand il y a quelque chose à dire.

    - stock de l'article EN MAIN (tous lieux moins le hors main, mouvements déjà écrits par la transaction en
      cours ; DISPONIBLE, en main - réservé, quand des réservations retiennent du stock : T4.14) sous son
      seuil : constat `besoin_commande` (quantité cible - stock) ;
    - article sans paramètres, ou aux paramètres invalides : constat `seuil_a_configurer`, jamais un seuil
      deviné ;
    - stock suffisant : rien (le silence n'est pas un fait).
    Idempotent par article ET événement déclencheur (`wct_id`) : un article déjà constaté pour ce WCT n'est
    pas réécrit. Rend les constats ÉCRITS par cet appel.

    Ne crée JAMAIS de bon de commande, ne réserve rien, n'écrit aucun mouvement, ne publie aucun événement,
    et ne peut pas faire échouer la déclaration : une configuration mauvaise donne un constat, pas une
    exception. Hors transaction (aucun registre durable où écrire) : rien, comme `_reevaluer_si_wct_connu_*`.
    `horodatage` est celui du WCT (jamais une horloge consultée ici).
    """
    if stockage.connexion_courante() is None:
        return []
    unites: dict[str, Any] = {}
    for ligne in lignes:
        unites.setdefault(ligne["materiau_id"], ligne.get("unite"))
    disponibilite = _disponibilite(unites)
    articles = _articles_reapprovisionnement()
    constats = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_BESOINS_COMMANDE)
    ecrits: list[dict[str, Any]] = []
    for materiau_id in sorted(unites):
        chiffres = disponibilite[materiau_id]
        # T4.14 : c'est le DISPONIBLE qui est comparé au seuil quand des réservations retiennent du stock ; sans
        # réservation (`reserve` nul), exactement le comportement d'avant.
        verdict = reapprovisionnement.evaluer(
            materiau_id, chiffres["en_main"], articles, reserve=chiffres["reserve"] if chiffres["reserve"] else None
        )
        constat = reapprovisionnement.construire_constat(
            verdict, evenement_declencheur=wct_id, horodatage=horodatage, chantier_id=chantier_id,
            unite=unites[materiau_id],
        )
        if constat is None or reapprovisionnement.constat_deja_range(constat, constats):
            continue
        constats.append(constat)
        ecrits.append(constat)
    return ecrits


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
    bons_commande_historique: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """PLAN T2.5 point 4 : `materiel.enregistrer_reception` (DA-M6-11) reste APPELÉ SANS
    MODIFICATION — la réception éphémère (`bon_demande` fourni à l'appel) continue de fonctionner
    exactement comme avant pour un `po_id` qui ne référence aucun PO persisté (compatibilité
    totale, P5 : « toute nouvelle route est additive »). Quand `bon_demande["po_id"]` référence un
    PO persisté (`m6_creer_po_brouillon`), cette fonction s'y RATTACHE en plus : vérifie que
    `bon_demande` correspond exactement aux lignes du PO (REJ-PO-BON-DEMANDE-INCOHERENT — défend
    contre un bon forgé), que le PO est dans un statut qui permet la réception
    (REJ-PO-TRANSITION-ILLEGALE), PUIS écrit la réception (comme avant) et enfin transitionne le
    PO (`partially_received`/`received` selon le verdict déjà calculé — jamais recalculé) et
    signale tout écart de prix au-delà du seuil configuré (M6.7), vers M5 et M8 (signal retourné,
    jamais transmis directement — même politique que `signal_po_a_payer`).

    PLAN T4.15 : pour un PO persisté, dans une transaction, publie en plus `m6.reception_enregistree`
    (`evenement_reception_id` dans la réponse) : c'est ainsi que M5 apprend ce que l'entreprise devra au
    fournisseur pour ce qui vient d'arriver. Quantité reçue négative ou non finie, horodatage sans fuseau :
    refus nommé, avant toute écriture.

    PLAN T4.15-b : (1) les livraisons d'un PO persisté se CUMULENT. Le statut du PO (`received` ou
    `partially_received`) découle du cumul (`reception.evaluer_cumul`, décimal exact), non de la seule dernière
    livraison contre la commande entière : la livraison qui complète un PO partiel le fait passer à `received`.
    `resultat.accuse_reception` (et `verdict_reception` de l'événement) reste le verdict de CETTE livraison ;
    `reception_cumulee` dit le cumul. (2) Une livraison déjà enregistrée (même PO, même horodatage, mêmes
    quantités) est refusée (`REJ-RECEPTION-DEJA-ENREGISTREE`) : additionnée deux fois, une livraison partielle
    ferait passer le PO à `received`. (3) Une quantité négative ou non finie est refusée AVANT toute écriture
    aussi pour une réception éphémère (PO non persisté)."""
    bons_registre = _bons_commande_de_l_appel(bons_commande_historique)
    po_id = bon_demande.get("po_id") if isinstance(bon_demande, dict) else None
    po_existant = bons_commande.lire(bons_registre, po_id) if po_id else None
    livraison = None
    if po_existant is not None:
        if not bons_commande.bon_demande_correspond(po_existant, bon_demande):
            return {"accepte": False, "verdict": {"code": "REJ-PO-BON-DEMANDE-INCOHERENT"}}
        if not bons_commande.peut_recevoir(po_existant["statut"]):
            return {"accepte": False, "verdict": {"code": "REJ-PO-TRANSITION-ILLEGALE"}}
        # T4.15 : la réception d'un PO persisté devient de l'argent à payer chez M5. Ce qui ne peut pas être
        # publié est refusé ICI, avant toute écriture au stock : après, il faudrait défaire ce qui est écrit.
        verdict_publiable = evenement_reception.verifier_reception(reception_po)
        if verdict_publiable is not None:
            return {"accepte": False, "verdict": verdict_publiable}
        # T4.15-b : les livraisons d'un PO se CUMULENT. Une livraison déjà enregistrée (même PO, même horodatage,
        # mêmes quantités) qu'on rejouerait serait additionnée deux fois : refusée, avant toute écriture.
        if isinstance(reception_po, dict):
            livraison = bons_commande.construire_livraison(po_existant, reception_po)
        if livraison is not None and bons_commande.livraison_deja_enregistree(bons_registre, po_id, livraison):
            return {"accepte": False, "verdict": verdicts.construire_verdict(
                "REJ-RECEPTION-DEJA-ENREGISTREE",
                detail=(
                    f"la livraison du PO {po_id!r} horodatée {livraison['horodatage']!r}, aux mêmes quantités, "
                    "est déjà enregistrée : rien n'est réécrit, rien n'est additionné deux fois"
                ),
            )}
    else:
        # T4.15-b : une quantité négative ou non finie n'est pas une réception, PO persisté ou non.
        verdict_quantites = evenement_reception.verifier_quantites(reception_po)
        if verdict_quantites is not None:
            return {"accepte": False, "verdict": verdict_quantites}

    registre_cible = _registre_de_l_appel(registre_historique)
    resultat, code = materiel.enregistrer_reception(
        bon_demande, reception_po, catalogue_materiaux, registre_cible, seuils=seuils_reorder
    )
    if code is not None:
        return {"accepte": False, "verdict": {"code": code}}
    reponse = {"accepte": True, "resultat": resultat, **_etat_registre(registre_cible)}
    # T4.14 : du stock vient d'entrer, PO persisté ou non : les réservations auxquelles il manquait quelque chose
    # se complètent (les plus anciennes d'abord), et `m6.materiel_pret` le dit à M4.
    publies = _reconcilier_reservations(
        [ligne["materiau_id"] for ligne in resultat["accuse_reception"]["lignes"]], reception_po.get("horodatage")
    )
    if publies:
        reponse["evenements_materiel_pret"] = publies

    if po_existant is not None:
        accuse = resultat["accuse_reception"]
        verdict_po, cumul = _verdict_cumule_du_po(po_existant, accuse, livraison, bons_registre)
        po_maj, code_po = bons_commande.enregistrer_reception_po(
            po_id, verdict_po, reception_po["horodatage"], bons_registre, livraison=livraison
        )
        if code_po is not None:
            # peut_recevoir a déjà validé le statut ci-dessus : un refus ici trahirait une
            # incohérence interne, jamais un cas d'usage normal (même discipline que
            # _essayer_facture_brouillon de M5 face à une entrée déjà validée).
            raise RuntimeError(f"enregistrer_reception_po a refusé une transition déjà validée : {code_po}")
        reponse["po"] = po_maj
        reponse["reception_cumulee"] = cumul
        seuil_ecart_prix = _seuil_ecart_prix_reception()
        reponse["seuil_ecart_prix_pourcentage"] = seuil_ecart_prix
        reponse["signaux_ecart_prix"] = (
            bons_commande.detecter_ecarts_prix(po_maj, accuse["lignes"], seuil_ecart_prix)
            if seuil_ecart_prix is not None
            else []
        )
        if stockage.connexion_courante() is None:
            reponse["bons_commande_historique"] = list(bons_registre)
        else:
            reponse["evenement_reception_id"] = _publier_reception(
                po_maj, accuse, reception_po, seuil_ecart_prix, reponse["signaux_ecart_prix"]
            )
    return reponse


def _verdict_cumule_du_po(
    po: dict[str, Any], accuse: dict[str, Any], livraison: dict[str, Any] | None, bons_registre: Any
) -> tuple[str, dict[str, Any]]:
    """Le verdict qui décide du statut du PO après cette livraison, et ce qu'il dit de son cumul (PLAN T4.15-b).

    Accusé `INDETERMINE` (rien n'apparie, rien n'est écrit) : ce verdict, sans transition, et `fiable` nul (aucun
    cumul n'est calculé). Sinon, verdict de `reception.evaluer_cumul` sur les livraisons antérieures du PO PLUS
    celle-ci : c'est ce cumul, non la seule livraison, qui atteint `received`. Si une réception antérieure du PO
    n'a pas gardé le détail de sa livraison (avant T4.15-b), le cumul n'est pas fiable : le verdict reste celui de
    CETTE livraison contre la commande entière (le comportement d'avant, jamais un « reçu » deviné), et `fiable` est
    faux."""
    verdict_livraison = accuse["verdict_reception"]
    if livraison is None or not accuse["lignes"]:
        return verdict_livraison, {
            "fiable": None,
            "verdict_reception": verdict_livraison,
            "lignes": [],
            "raison": "aucune ligne ne s'apparie au PO : rien n'est reçu, rien n'est additionné",
        }
    anterieures = bons_commande.livraisons(bons_registre, po["po_id"])
    sans_detail = bons_commande.livraisons_sans_detail(bons_registre, po["po_id"])
    cumul = reception.evaluer_cumul(
        po["lignes"], [ancienne["lignes"] for ancienne in anterieures] + [livraison["lignes"]]
    )
    if cumul is None or sans_detail:
        return verdict_livraison, {
            "fiable": False,
            "verdict_reception": verdict_livraison,
            "lignes": [],
            "raison": (
                f"{sans_detail} réception(s) antérieure(s) sans détail de livraison : le cumul est inconnu, le "
                "verdict reste celui de cette livraison contre la commande entière"
                if sans_detail
                else "quantité illisible : le cumul n'est pas calculable"
            ),
        }
    return cumul["verdict_reception"], {"fiable": True, **cumul}


def _publier_reception(
    po: dict[str, Any],
    accuse_reception: dict[str, Any],
    reception_po: dict[str, Any],
    seuil_ecart_prix: float | None,
    signaux_ecart_prix: list[dict[str, Any]],
) -> str | None:
    """Publie `m6.reception_enregistree` pour la réception qui vient d'être écrite, dans la transaction courante
    (`receptionner_commande`, seul appelant : le stock, la transition du PO et l'événement réussissent ou
    échouent ensemble). Rend l'`evenement_id`, ou `None` quand il n'y a rien à publier (réception sans ligne
    appariée : rien n'est écrit au stock non plus).

    LÈVE si la charge ne peut pas être construite, ou si le catalogue du socle la refuse (`ChargeInvalide`,
    schéma fermé compris) : ce serait un défaut du code, jamais une entrée (`verifier_reception` a déjà refusé
    les entrées avant d'écrire). Mieux vaut annuler la réception entière que la laisser sans son événement, donc
    sans son « à payer attendu » chez M5. L'identifiant est déterministe (`evenement_reception.evenement_id`) :
    publier deux fois la même réception est un no-op du bus."""
    charge, verdict = evenement_reception.construire_charge(
        po, accuse_reception, reception_po, seuil_ecart_prix, signaux_ecart_prix
    )
    if verdict is not None:
        raise RuntimeError(f"m6.reception_enregistree : réception déjà écrite mais non publiable : {verdict}")
    if charge is None:
        return None
    evenements.publier(evenement_reception.TYPE_EVENEMENT, _DEPARTEMENT, charge, evenement_id=charge["evenement_id"])
    return charge["evenement_id"]


def consommer_materiaux(
    wct: dict[str, Any],
    formulaire: dict[str, Any],
    registre_historique: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compatibilité de l'ancien contrat, adossée au WCT canonique M4.

    Le champ ``wct`` reste accepté pour compatibilité, mais n'est plus une source de vérité :
    son ``wct_id`` sert uniquement à relire ``m4.travaux_termines``. L'appel doit donc être
    transactionnel, comme ``m6_declarer_materiaux_utilises``. Une consommation est ensuite
    marquée par ce WCT dans le registre, ce qui rend les appels répétés idempotents même si la
    clé d'idempotence de transport change.
    """
    wct_id = wct.get("wct_id") if isinstance(wct, dict) else None
    wct_canonique = _wct_publie_par_m4(wct_id)
    if wct_canonique is None:
        return {"accepte": False, "verdict": {"code": "REJ-WCT-INCONNU"}}

    ok, code = validation.valider_wct(wct_canonique)
    if ok:
        ok, code = validation.valider_formulaire_consommation(formulaire, wct_canonique)
    if not ok:
        return {"accepte": False, "verdict": {"code": code}}
    if formulaire["intervention_id"] != wct_canonique["intervention_id"]:
        return {
            "accepte": False,
            "verdict": {"code": "REJ-FORMULAIRE-MATERIAUX-INTERVENTION-INCOHERENTE"},
        }

    registre_cible = _registre_de_l_appel(registre_historique)
    resultat, code = materiel.consommer_materiaux(
        wct_canonique, formulaire, registre_cible, wct_id=wct_id
    )
    if code is not None:
        return {"accepte": False, "verdict": {"code": code}}
    # T4.14 : du stock vient de sortir ; le WCT relu de M4 clôture la réservation de son devis.
    _cloturer_et_reconcilier(
        wct_canonique.get("devis_id"), wct_canonique["wct_id"], wct_canonique["horodatage_completion"],
        [ligne["materiau_id"] for ligne in formulaire["lignes_consommees"]],
    )
    return {"accepte": True, "resultat": resultat, **_etat_registre(registre_cible)}


def _wct_publie_par_m4(wct_id: str) -> dict[str, Any] | None:
    """Le `WctRecu` de ce `wct_id`, relu dans le bus, ou `None` si M4 ne l'a jamais publié.

    M4 publie `m4.travaux_termines` avec `evenement_id = wct_id`, dans la même transaction que le
    WCT lui-même (`m4_completer_intervention`) : le magasin du bus est donc la source de vérité du
    WCT, et un appelant (appareil, modèle) ne peut plus en fabriquer un pour rattacher des
    matériaux à un chantier qui n'existe pas. `contrats.CHAMPS_WCT` (le `WctRecu` de M6) ne porte
    pas `statut`, que le catalogue d'événement requiert et dont M6 ne se sert pas : il est retiré
    ici, tout le reste — clés optionnelles comprises — passe tel quel à `validation.valider_wct`.

    Seule la transaction de l'outil consulte le bus, comme le registre durable et la réévaluation
    (`_reevaluer_si_wct_connu_par_wct_id`) : hors transaction (appel direct, tests en mémoire),
    aucune source de vérité n'est joignable, donc rien n'est connu — fail-closed.
    """
    if stockage.connexion_courante() is None or not isinstance(wct_id, str) or not wct_id:
        return None
    charge = evenements.charge_publiee(_TYPE_EVENEMENT_WCT, wct_id)
    if charge is None:
        return None
    return {cle: valeur for cle, valeur in charge.items() if cle != "statut"}


def _declarant_appareil() -> tuple[acces.Acteur | None, dict[str, Any] | None]:
    """Qui appelle : ``(None, None)`` hors appel d'appareil, ``(acteur, None)`` si l'identité du
    jeton est CONFIRMÉE en base, ``(None, verdict)`` sinon (PLAN T1.4-k).

    Même règle que `m4_field_ops.outils._acteur_appareil` (personne active portant encore le rôle du
    jeton, `approbations.signataire_valide`, la fonction de T1.4-h) : `identite_appelante()` ne rend
    que ce que le core a transmis, la personne a pu être désactivée depuis. Hors transaction, rien
    n'est vérifiable : refus fermé. Ne lit JAMAIS les arguments de l'outil."""
    appelante = contexte.identite_appelante()
    if appelante is None:
        return None, None
    cnx = stockage.connexion_courante()
    confirmee = approbations.signataire_valide(cnx, appelante) if cnx is not None else None
    if confirmee is None:
        return None, verdicts.construire_verdict(
            "REJ-IDENTITE-APPAREIL-INVALIDE",
            detail=(
                f"personne {appelante.personne!r} inconnue, inactive, ou ne porte plus le rôle "
                f"{appelante.role!r} porté par le jeton d'appareil (ou identité non vérifiable "
                "hors transaction)"
            ),
        )
    return acces.acteur_de(confirmee.personne, confirmee.role)


def declarer_materiaux_utilises(wct_id: str, formulaire: dict[str, Any]) -> dict[str, Any]:
    """PLAN T1.1-d2 point 2, PLAN T1.4-i pour l'origine du WCT, PLAN T1.4-k pour qui déclare. Réponse
    tête + taille seulement (`_etat_registre`), comme les autres outils d'écriture.

    L'appelant donne le `wct_id` ; M6 lit lui-même la charge `m4.travaux_termines` publiée par M4
    pour cet identifiant (`_wct_publie_par_m4`) et la valide comme avant (`valider_wct`,
    `valider_formulaire_materiaux_utilises`, dont la cohérence `formulaire["wct_id"] == wct_id`).
    `wct_id` inconnu : `REJ-WCT-INCONNU`, avant toute lecture ou écriture du registre.

    Ordre (chaque refus intervient avant toute écriture) : identité d'appareil confirmée en base
    (`REJ-IDENTITE-APPAREIL-INVALIDE`) ; WCT connu ; un `employee` ne déclare que pour SON WCT
    (`REJ-INTERVENTION-NON-ASSIGNEE`, `acces.controler_declarant`) ; structure du formulaire ;
    `intervention_id` du formulaire = celle du WCT (`REJ-FORMULAIRE-MATERIAUX-INTERVENTION-
    INCOHERENTE`) ; `chantier_id` du formulaire = celui que la source impose
    (`REJ-FORMULAIRE-MATERIAUX-CHANTIER-INCOHERENT`, `acces.controler_chantier`). Hors appel d'appareil
    (agent, console) : aucun contrôle de personne, comme avant T1.4-k ; les deux concordances du
    formulaire valent pour tous les appelants.

    Cet outil ne fonctionne que dans la transaction de l'outil (registre durable et bus) : il n'a
    donc plus de mode `registre_historique` en mémoire.

    Correctif (la déclaration arrive presque toujours APRÈS la complétion, R12 §4/§9.7) : si un
    WCT déjà reçu porte ce wct_id, réévalue et republie m6.variance_chantier tout de suite — sans
    attendre une prochaine livraison de m4.travaux_termines qui n'arrivera jamais deux fois."""
    acteur, verdict_acteur = _declarant_appareil()
    if verdict_acteur is not None:
        return {"accepte": False, "verdict": verdict_acteur}
    wct = _wct_publie_par_m4(wct_id)
    if wct is None:
        return {"accepte": False, "verdict": {"code": "REJ-WCT-INCONNU"}}
    verdict_declarant = acces.controler_declarant(wct, acteur)
    if verdict_declarant is not None:
        return {"accepte": False, "verdict": verdict_declarant}
    # Structure puis concordance avec le WCT, AVANT d'écrire : la même validation que refait
    # `soumettre_materiaux_utilises` (idempotente, sans effet), pour que le chantier ne soit confronté
    # qu'à un formulaire dont la forme est déjà garantie.
    ok, code = validation.valider_wct(wct)
    if ok:
        ok, code = validation.valider_formulaire_materiaux_utilises(formulaire, wct)
    if not ok:
        return {"accepte": False, "verdict": {"code": code}}
    besoin = besoins_prevus.pour_devis(wct.get("devis_id"), _besoins_prevus_de_l_appel(None))
    verdict_chantier = acces.controler_chantier(formulaire, wct, besoin, acteur)
    if verdict_chantier is not None:
        return {"accepte": False, "verdict": verdict_chantier}
    # Une quantité déclarée doit garder l'unité du même article dans le besoin canonique.
    # Contrôler TOUT le formulaire avant l'écriture du lot ; aucune conversion n'est inventée.
    if besoin is not None:
        unites_prevues = {ligne["materiau_id"]: ligne["unite"] for ligne in besoin["lignes"]}
        if any(ligne["materiau_id"] in unites_prevues
               and ligne["unite"] != unites_prevues[ligne["materiau_id"]]
               for ligne in formulaire["lignes_materiaux"]):
            return {"accepte": False, "verdict": {"code": "REJ-FORMULAIRE-MATERIAUX-UNITE-INCOHERENTE"}}
    registre_cible = _registre_de_l_appel(None)
    resultat, code = materiel.soumettre_materiaux_utilises(wct, formulaire, registre_cible)
    if code is not None:
        return {"accepte": False, "verdict": {"code": code}}
    _reevaluer_si_wct_connu_par_wct_id(wct_id)
    # T4.14 : les matériaux du chantier sont déclarés. La réservation de son devis est clôturée (ce qu'elle retenait
    # redevient disponible), et celles des autres chantiers se réconcilient avec le stock qui reste : AVANT le
    # constat du stock bas, qui compare le DISPONIBLE au seuil.
    _cloturer_et_reconcilier(
        wct.get("devis_id"), wct_id, wct["horodatage_completion"],
        [ligne["materiau_id"] for ligne in formulaire["lignes_materiaux"]],
    )
    _constater_stock_des_articles(
        wct_id, wct["horodatage_completion"], formulaire["chantier_id"], formulaire["lignes_materiaux"]
    )
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
    _, verdict = _acteur_admin_ou_agent()
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
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
    _, verdict = _acteur_admin_ou_agent()
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
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


# --------------------------------------------------------------------------------------------- T2.5
# Registre des fournisseurs (M6.2, PLAN T2.5 point 2) : identité et coordonnées seulement.
def enregistrer_fournisseur(
    fournisseur_id: str,
    nom: str,
    horodatage: str,
    courriel_commande: str | None = None,
    telephone: str | None = None,
    categories_vendues: list[str] | None = None,
    delai_habituel_jours: int | None = None,
    format_commande_prefere: str | None = None,
    fournisseurs_historique: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    registre_cible = _fournisseurs_de_l_appel(fournisseurs_historique)
    resultat, verdict = fournisseurs.enregistrer_fournisseur(
        fournisseur_id, nom, horodatage, registre_cible,
        courriel_commande=courriel_commande, telephone=telephone, categories_vendues=categories_vendues,
        delai_habituel_jours=delai_habituel_jours, format_commande_prefere=format_commande_prefere,
    )
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    reponse = {"accepte": True, "resultat": resultat}
    if stockage.connexion_courante() is None:
        reponse["fournisseurs_historique"] = list(registre_cible)
    return reponse


def lister_fournisseurs(fournisseurs_historique: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    registre_cible = _fournisseurs_de_l_appel(fournisseurs_historique)
    return {"accepte": True, "resultat": fournisseurs.lister_fournisseurs(registre_cible)}


# --------------------------------------------------------------------------------------------- T2.4
# Livre de prix (M6.3, PLAN T2.4) : prix fournis, versionnés, datés, par fournisseur.
# bons_commande.creer_brouillon (commit T2.5 précédent) LIT déjà ce livre pour résoudre le prix de
# chaque ligne (fail-closed, verdict INDETERMINE si vide) ; cette fonction est l'outil agent dédié
# à sa SAISIE — la surface manquante que ce commit ajoute.
def enregistrer_prix(
    materiau_id: str,
    fournisseur_id: str,
    prix_unitaire: float,
    devise: str,
    date_effet: str,
    source_document: str | None = None,
    livre_prix_historique: list[dict[str, Any]] | None = None,
    unite: str | None = None,
) -> dict[str, Any]:
    registre_cible = _livre_prix_de_l_appel(livre_prix_historique)
    resultat, verdict = livre_prix.enregistrer_prix(
        materiau_id, fournisseur_id, prix_unitaire, devise, date_effet, registre_cible,
        source_document=source_document, unite=unite,
    )
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    reponse = {"accepte": True, "resultat": resultat,
               "marquage_source": livre_prix.marquage_source_document(resultat.get("source_document"))}
    if stockage.connexion_courante() is None:
        reponse["livre_prix_historique"] = list(registre_cible)
    return reponse


# --------------------------------------------------------------------------------------------- T2.5
# Moteur de PO (M6.5, PLAN T2.5 point 1/3), DA-M6-12 révisée (docs/bmad/03-ARCHITECTURE.md).
def _reponse_po(resultat: dict[str, Any], registre_cible: list[dict[str, Any]]) -> dict[str, Any]:
    """Forme commune des outils PO : le PO à jour, plus l'historique du registre des PO hors
    transaction seulement (même convention que `enregistrer_besoins_prevus` — le registre durable
    de production n'a rien à retransporter, `_bons_commande_de_l_appel` en fait déjà autorité)."""
    reponse = {"accepte": True, "po": bons_commande.projeter_provenance_prix(resultat)}
    if stockage.connexion_courante() is None:
        reponse["bons_commande_historique"] = list(registre_cible)
    return reponse


def creer_po_brouillon(
    po_id: str,
    devis_id: str,
    fournisseur_id: str,
    horodatage: str,
    besoins_prevus_historique: list[dict[str, Any]] | None = None,
    registre_historique: list[dict[str, Any]] | None = None,
    livre_prix_historique: list[dict[str, Any]] | None = None,
    fournisseurs_historique: list[dict[str, Any]] | None = None,
    bons_commande_historique: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Crée un PO BROUILLON à partir des besoins prévus (`m6_enregistrer_besoins_prevus`, source
    `m3.devis_accepte`) et du stock déjà disponible pour le chantier — PAR LE CODE
    (`bons_commande.calculer_lignes_a_commander`), jamais deviné : seul l'ÉCART entre l'estimé et
    le disponible atterrit sur le PO. `devis_id` (pas `chantier_id`) est la clé d'entrée : c'est
    la même clé que `besoins_prevus.py` utilise déjà. Un chantier entièrement couvert par le stock
    rend `statut: "aucun_achat_requis"`, PAS un PO vide."""
    besoins_registre = _besoins_prevus_de_l_appel(besoins_prevus_historique)
    besoin = besoins_prevus.pour_devis(devis_id, besoins_registre)
    if besoin is None:
        return {"accepte": False, "verdict": {"code": "REJ-PO-BESOIN-INTROUVABLE"}}
    chantier_id = besoin["chantier_id"]
    if not chantier_id:
        return {"accepte": False, "verdict": {"code": "REJ-PO-CHANTIER-INCONNU"}}

    mouvements_registre = _registre_de_l_appel(registre_historique)
    # T4.14 : quand une réservation ACTIVE existe pour ce devis, ce qu'on commande est ce qui lui MANQUE (besoin -
    # réservé), pas l'écart au stock du chantier : le stock du dépôt mis de côté pour ce devis est déjà couvert, et
    # celui qui est réservé pour un autre ne l'est pas. Sans réservation, l'écart d'avant.
    reservation = (
        reservations.etat(devis_id, stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_RESERVATIONS))
        if stockage.connexion_courante() is not None else None
    )
    depuis_reservation = reservation is not None and reservation["actif"]
    if depuis_reservation:
        lignes = [
            {"materiau_id": ligne["materiau_id"], "quantite_demandee": float(Decimal(ligne["quantite_manquante"]))}
            for ligne in reservations.lignes_manquantes(reservation["lignes"])
        ]
    else:
        lignes = bons_commande.calculer_lignes_a_commander(besoin["lignes"], chantier_id, mouvements_registre)
    if not lignes:
        return {"accepte": True, "po": None, "statut": "aucun_achat_requis"}

    prix_registre = _livre_prix_de_l_appel(livre_prix_historique)
    fournisseurs_registre = _fournisseurs_de_l_appel(fournisseurs_historique)
    bons_registre = _bons_commande_de_l_appel(bons_commande_historique)
    resultat, verdict = bons_commande.creer_brouillon(
        po_id, chantier_id, fournisseur_id, lignes, horodatage, bons_registre, prix_registre, fournisseurs_registre
    )
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    reponse = _reponse_po(resultat, bons_registre)
    if depuis_reservation:
        reponse["quantites_depuis"] = "reservation"
    return reponse


def approuver_po(
    po_id: str, horodatage: str, bons_commande_historique: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    registre_cible = _bons_commande_de_l_appel(bons_commande_historique)
    resultat, verdict = bons_commande.approuver(po_id, horodatage, registre_cible)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return _reponse_po(resultat, registre_cible)


def annuler_po(
    po_id: str, motif: str, horodatage: str, bons_commande_historique: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    registre_cible = _bons_commande_de_l_appel(bons_commande_historique)
    resultat, verdict = bons_commande.annuler(po_id, motif, horodatage, registre_cible)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return _reponse_po(resultat, registre_cible)


def generer_courriel_po(
    po_id: str,
    horodatage: str,
    nom_entreprise: str,
    fournisseurs_historique: list[dict[str, Any]] | None = None,
    bons_commande_historique: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    registre_cible = _bons_commande_de_l_appel(bons_commande_historique)
    fournisseurs_registre = _fournisseurs_de_l_appel(fournisseurs_historique)
    resultat, verdict = bons_commande.generer_courriel(
        po_id, horodatage, registre_cible, fournisseurs_registre, nom_entreprise
    )
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return _reponse_po(resultat, registre_cible)


def marquer_po_envoye(
    po_id: str, horodatage: str, bons_commande_historique: list[dict[str, Any]] | None = None
) -> dict[str, Any]:
    """Verrou d'envoi (N4) : n'exécute qu'après la décision du socle (`opsys.approbations.decider`,
    `department.yaml` bloc `approbations.n4`) — PLAN T2.5 point 3, « l'envoi au fournisseur est
    N4 ». Aucune primitive d'envoi réel ici (voir bons_commande.marquer_envoye)."""
    registre_cible = _bons_commande_de_l_appel(bons_commande_historique)
    resultat, verdict = bons_commande.marquer_envoye(po_id, horodatage, registre_cible)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return _reponse_po(resultat, registre_cible)


# ---------------------------------------------------------------------------------------------- T4.14
def reserver_materiel(devis_id: str, horodatage: str) -> dict[str, Any]:
    """Réserve le matériel d'un devis ACCEPTÉ (M6.8) : ce qui est disponible, jamais plus, sans double réservation ;
    publie `m6.materiel_pret`. Le bus le fait déjà à l'acceptation du devis (`_recevoir_devis_accepte`) ; cet outil
    sert au prévu saisi à la main (`m6_enregistrer_besoins_prevus`) et à RÉSERVER DE NOUVEAU après une libération
    (le bus, lui, ne défait jamais ce qu'un humain a libéré). Un devis dont les matériaux sont déclarés ne se réserve
    plus. Aucun bon de commande."""
    refus = _hors_transaction()
    if refus is not None:
        return refus
    acteur, verdict = _acteur_admin_ou_agent()
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return _reserver_pour_devis(devis_id, horodatage, "reservation_manuelle", acteur=acteur, re_reservation=True)


def liberer_reservation(devis_id: str, motif: str, horodatage: str) -> dict[str, Any]:
    """Libère la réservation ACTIVE d'un devis (annulation du chantier, M6.8, N2) : ce qu'elle retenait redevient
    disponible, les autres réservations auxquelles il manquait quelque chose se complètent (les plus anciennes
    d'abord), et `m6.materiel_pret` dit à M4 que ce devis n'est plus prêt (`a_commander`, `reservation_active` faux).
    Le motif est requis et gardé (M6.14) ; rejouer la libération d'une réservation déjà libérée n'écrit rien."""
    refus = _hors_transaction()
    if refus is not None:
        return refus
    acteur, verdict = _acteur_admin_ou_agent()
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    registre = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_RESERVATIONS)
    resultat, verdict = reservations.liberer(devis_id, motif, acteur, horodatage, registre)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    fait = resultat["fait"]
    if fait is None:
        return {"accepte": True, "statut": resultat["statut"], "reservation": _vue_reservation(
            reservations.etat(devis_id, registre))}
    publies = _ecrire_faits_reservation([fait])
    publies += _reconcilier_reservations([ligne["materiau_id"] for ligne in fait["lignes"]], horodatage)
    return {
        "accepte": True, "statut": resultat["statut"], "reservation": _vue_reservation(fait),
        "liberees": fait["liberees"], "evenements_materiel_pret": publies,
    }


def transferer_stock(
    transfert_id: str, materiau_id: str, quantite: float, de: dict[str, Any], vers: dict[str, Any], motif: str,
    horodatage: str,
) -> dict[str, Any]:
    """Transfère du stock d'un emplacement à un autre (M6.9), AUDITÉ : acteur, motif, horodatage, quantité et l'avant
    et l'après des deux extrémités, dans une chaîne hash-chaînée. Un transfert déplace, il ne crée ni ne détruit :
    aucune quantité par emplacement ne devient négative, et le stock non localisé est à `inconnu`. Idempotent par
    `transfert_id`. Sortir du stock de la main (vers fournisseur, retour ou rebut) ou l'y remettre réconcilie les
    réservations : le réservé ne dépasse jamais l'en main. La chaîne de mouvements de stock ne change pas."""
    refus = _hors_transaction()
    if refus is not None:
        return refus
    acteur, verdict = _acteur_admin_ou_agent()
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    registre = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_EMPLACEMENTS)
    stock_total = (
        stock.deriver_stock_articles([materiau_id], stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))[materiau_id]
        if isinstance(materiau_id, str) and materiau_id.strip() else Decimal(0)
    )
    resultat, verdict = emplacements.construire_transfert(
        transfert_id, materiau_id, quantite, de, vers, acteur, motif, horodatage, stock_total, registre
    )
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    maillon = resultat["maillon"]
    reponse: dict[str, Any] = {
        "accepte": True,
        "statut": "deja_enregistre" if resultat["deja_enregistre"] else "enregistre",
        "transfert": {cle: maillon[cle] for cle in (
            "transfert_id", "materiau_id", "quantite", "de", "vers", "avant", "apres", "hash_maillon")},
    }
    if resultat["deja_enregistre"]:
        return reponse
    registre.append(maillon)
    variation = emplacements.variation_en_main(maillon["de"], maillon["vers"])
    publies = _reconcilier_reservations([materiau_id], horodatage) if variation else []
    reponse["evenements_materiel_pret"] = publies
    reponse["repartition"] = {
        emplacement: stock.texte_canonique(quantite_emplacement)
        for emplacement, quantite_emplacement in emplacements.repartition(materiau_id, stock_total, registre).items()
    }
    return reponse


_LIMITE_ARTICLES_LUS = 15
_LIMITE_RESERVATIONS_LUES = 10


def lire_disponibilite(materiau_ids: list[str] | None = None) -> dict[str, Any]:
    """Lecture seule (M6.8, M6.9) : pour chaque article, le stock théorique, ce qui est hors main, l'EN MAIN, le
    RÉSERVÉ, le DISPONIBLE (en main - réservé), où il est (par emplacement, `inconnu` = non localisé), et les
    réservations actives qui le touchent avec ce qui leur manque. Sans `materiau_ids`, les articles connus des
    registres, dans l'ordre, par pages de quinze (`tronque`). Quantités en texte décimal ; aucun prix."""
    refus = _hors_transaction()
    if refus is not None:
        return refus
    _, verdict = _acteur_admin_ou_agent()
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    mouvements = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE)
    transferts = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_EMPLACEMENTS)
    faits = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_RESERVATIONS)
    en_cours = reservations.actives(faits)
    if materiau_ids is None:
        connus = {m["materiau_id"] for m in mouvements if isinstance(m.get("materiau_id"), str)}
        connus |= {t["materiau_id"] for t in transferts if t.get("type_entree") == emplacements.TYPE_TRANSFERT}
        connus |= {ligne["materiau_id"] for e in en_cours for ligne in e["lignes"]}
    else:
        connus = {m for m in materiau_ids if isinstance(m, str) and m.strip()}
    choisis = sorted(connus)[:_LIMITE_ARTICLES_LUS]
    chiffres = stock.deriver_disponibilite(
        choisis, mouvements, emplacements.hors_main_par_article(transferts), reservations.reserve_par_article(faits)
    )
    articles = [
        {
            "materiau_id": materiau_id,
            **{cle: stock.texte_canonique(valeur) for cle, valeur in chiffres[materiau_id].items()},
            "par_emplacement": {
                emplacement: stock.texte_canonique(quantite)
                for emplacement, quantite in emplacements.repartition(
                    materiau_id, chiffres[materiau_id]["stock_theorique"], transferts).items()
            },
        }
        for materiau_id in choisis
    ]
    touchees = [
        e for e in en_cours if any(ligne["materiau_id"] in set(choisis) for ligne in e["lignes"])
    ]
    return {"accepte": True, "resultat": {
        "articles": articles,
        "tronque": len(connus) > len(choisis),
        "reservations_actives": [
            {
                "devis_id": e["devis_id"], "chantier_id": e["chantier_id"],
                "statut": reservations.statut_pret(e["lignes"]),
                "lignes_manquantes": reservations.lignes_manquantes(e["lignes"]),
            }
            for e in touchees[:_LIMITE_RESERVATIONS_LUES]
        ],
        "reservations_tronquees": len(touchees) > _LIMITE_RESERVATIONS_LUES,
    }}


def _snapshots_pertes_appareil(wct_id: str | None = None) -> dict[str, Any]:
    """Copie les sources dans la transaction courante ; les rangs viennent du stockage réel."""
    cnx = stockage.connexion_courante()
    lignes = cnx.execute(select(REGISTRES.c.rang, REGISTRES.c.maillon).where(
        REGISTRES.c.departement == _DEPARTEMENT, REGISTRES.c.registre == _NOM_REGISTRE_WCT_RECUS
    ).order_by(REGISTRES.c.rang)).all()
    recus = [{"rang": r.rang, "maillon": codec.decoder(r.maillon)} for r in lignes]
    ids = ([wct_id, *[f"m6-variance-{wct_id}-{statut}" for statut in pertes_appareil.statuts_historique()]]
           if wct_id is not None else [r["maillon"].get("wct_id") for r in recus
                                      if isinstance(r["maillon"], dict)
                                      and isinstance(r["maillon"].get("wct_id"), str)])
    publications = [{"evenement_id": r.evenement_id, "type": r.type_evenement, "producteur": r.producteur,
                     "charge": codec.decoder(r.charge)} for r in cnx.execute(
        select(EVENEMENTS_SORTANTS.c.evenement_id, EVENEMENTS_SORTANTS.c.type_evenement,
               EVENEMENTS_SORTANTS.c.producteur, EVENEMENTS_SORTANTS.c.charge)
        .where(EVENEMENTS_SORTANTS.c.evenement_id.in_(ids))).all()]
    mouvements = _registre_de_l_appel(None).lire() if wct_id is not None else []
    sources = {"recus": recus, "publications": publications, "mouvements": mouvements}
    # La limite de traitement est après toutes les copies ; ce n'est pas une borne allocation.
    if sum(len(rows) for rows in sources.values()) <= pertes_appareil.PLAFOND_LIGNES:
        for publication in publications:
            publication["catalogue_valide"] = not erreurs_charge(publication["type"], publication["charge"])
    return sources


def _lecture_pertes_appareil(
    wct_id: str | None, decalage: int, limite: int, *, detail: bool
) -> dict[str, Any]:
    if contexte.identite_appelante() is None:
        return {"accepte": False, "verdict": verdicts.construire_verdict(
            "REJ-IDENTITE-APPAREIL-INVALIDE", detail="cette lecture exige une personne admin active confirmée en base")}
    _, verdict = _acteur_admin_ou_agent()
    if verdict is not None:
        return {"accepte": False, "verdict": verdicts.construire_verdict(
            "REJ-IDENTITE-APPAREIL-INVALIDE", detail="cette lecture exige une personne admin active confirmée en base")}
    prefixe = "REJ-M6-PERTES-" if detail else "REJ-M6-WCT-"
    if ((detail and not pertes_appareil.texte(wct_id))
            or not pertes_appareil.arguments_valides(decalage, limite, wct_id)):
        return pertes_appareil.refuser(prefixe, "ARGUMENTS-INVALIDES")
    try:
        sources = _snapshots_pertes_appareil(wct_id)
    except Exception:
        return pertes_appareil.refuser(prefixe, "REGISTRE-INVALIDE")
    return (pertes_appareil.lister(sources, decalage, limite) if not detail
            else pertes_appareil.lire(sources, wct_id, decalage, limite))


def lister_wct_pertes_appareil(decalage: int = 0, limite: int = 8) -> dict[str, Any]:
    return _lecture_pertes_appareil(None, decalage, limite, detail=False)


def lire_pertes_alertes_wct_appareil(wct_id: str | None = None, decalage: int = 0, limite: int = 8) -> dict[str, Any]:
    return _lecture_pertes_appareil(wct_id, decalage, limite, detail=True)


def _configuration_reapprovisionnement_appareil() -> dict[str, Any]:
    contenu = _MANIFESTE.read_bytes()
    import hashlib

    empreinte = hashlib.sha256(contenu).hexdigest()
    try:
        document = yaml.safe_load(contenu.decode("utf-8"))
        if document is None:
            document = {}
        configuration = document.get("configuration", {}) if isinstance(document, dict) else None
        if configuration is None and isinstance(document, dict):
            configuration = {}
        section = configuration.get("reapprovisionnement") if isinstance(configuration, dict) else False
        if section is None:
            articles = {}
        elif isinstance(section, dict):
            articles = section.get("articles", {})
            if articles is None:
                articles = {}
            elif not isinstance(articles, dict):
                articles = None
        else:
            articles = None
    except (UnicodeDecodeError, yaml.YAMLError):
        articles = None
    return {"sha256": empreinte, "articles": articles}


def _sources_reapprovisionnement_appareil() -> dict[str, Any]:
    configuration = _configuration_reapprovisionnement_appareil()
    cnx = stockage.connexion_courante()
    copies = {}
    for nom in ("besoins_commande", "principal", "reservations", "emplacements", "wct_recus"):
        lignes = cnx.execute(select(REGISTRES.c.rang, REGISTRES.c.maillon).where(
            REGISTRES.c.departement == _DEPARTEMENT, REGISTRES.c.registre == nom
        ).order_by(REGISTRES.c.rang)).all()
        copies[nom] = [{"rang": r.rang, "maillon": codec.decoder(r.maillon)} for r in lignes]
    derniers = {}
    for ligne in copies["besoins_commande"]:
        m = ligne["maillon"]
        if isinstance(m, dict) and isinstance(m.get("materiau_id"), str):
            derniers[m["materiau_id"]] = m.get("evenement_declencheur")
    ids = [id_ for id_ in derniers.values() if isinstance(id_, str)]
    publications = [{"evenement_id": r.evenement_id, "type": r.type_evenement, "producteur": r.producteur,
                     "charge": codec.decoder(r.charge)} for r in cnx.execute(
        select(EVENEMENTS_SORTANTS.c.evenement_id, EVENEMENTS_SORTANTS.c.type_evenement,
               EVENEMENTS_SORTANTS.c.producteur, EVENEMENTS_SORTANTS.c.charge)
        .where(EVENEMENTS_SORTANTS.c.evenement_id.in_(ids)).order_by(EVENEMENTS_SORTANTS.c.evenement_id)).all()]
    if sum(len(v) for v in copies.values()) + len(publications) <= reapprovisionnement_appareil.PLAFOND_LIGNES:
        for p in publications:
            p["catalogue_valide"] = not erreurs_charge(p["type"], p["charge"])
    recus = copies.pop("wct_recus")
    return {"registres": copies, "recus_m6": recus, "publications": publications, "configuration": configuration}


def lire_reapprovisionnement_appareil(decalage: int = 0, limite: int = 8) -> dict[str, Any]:
    if contexte.identite_appelante() is None:
        return {"accepte": False, "verdict": verdicts.construire_verdict(
            "REJ-IDENTITE-APPAREIL-INVALIDE", detail="cette lecture exige une personne admin active confirmée en base")}
    _, verdict = _acteur_admin_ou_agent()
    if verdict is not None:
        return {"accepte": False, "verdict": verdicts.construire_verdict(
            "REJ-IDENTITE-APPAREIL-INVALIDE", detail="cette lecture exige une personne admin active confirmée en base")}
    if not reapprovisionnement_appareil.arguments_valides(decalage, limite):
        return reapprovisionnement_appareil.refuser("ARGUMENTS-INVALIDES")
    try:
        sources = _sources_reapprovisionnement_appareil()
    except OSError:
        return reapprovisionnement_appareil.refuser("CONFIGURATION-ILLISIBLE")
    except Exception:
        return reapprovisionnement_appareil.refuser("REGISTRE-INVALIDE")
    return reapprovisionnement_appareil.lire(sources, decalage, limite)


def _admission_m4_contexte(intervention_id: str, acteur: acces.Acteur) -> dict[str, Any]:
    from m4_field_ops import etats as etats_m4
    from m4_field_ops import outbox as outbox_m4
    from m4_field_ops import registre as registre_m4

    cnx = stockage.connexion_courante()
    rows = cnx.execute(
        select(REGISTRES.c.rang, REGISTRES.c.maillon)
        .where(REGISTRES.c.departement == "m04-field-ops", REGISTRES.c.registre == "principal")
        .order_by(REGISTRES.c.rang)
    ).all()
    copies = [codec.decoder(r.maillon) for r in rows]
    if len(copies) > contexte_materiaux_appareil.PLAFOND_LIGNES:
        raise contexte_materiaux_appareil.Refus("BORNE-SOURCES")
    reg = registre_m4.Registre(copies)
    if not reg.valider_chaine():
        raise contexte_materiaux_appareil.Refus("SOURCE-INVALIDE")
    if acteur.role == "employee" and etats_m4.technicien_assigne(reg, intervention_id) != acteur.personne:
        raise contexte_materiaux_appareil.Refus("INTERVENTION-NON-ASSIGNEE")
    if not outbox_m4.verifier_invariants_outbox(reg)[0]:
        raise contexte_materiaux_appareil.Refus("SOURCE-INVALIDE")
    found = [m["wct"] for m in copies if m.get("intervention_id") == intervention_id and isinstance(m.get("wct"), dict)]
    if len(found) != 1 or etats_m4.statut_courant(reg, intervention_id) not in outbox_m4.STATUTS_COMPLETION:
        raise contexte_materiaux_appareil.Refus("WCT-INCONNU")
    return {"completion": found[0], "admission_lignes": len(copies)}


def _wct_m4_contexte(wct_id: str, admission: dict[str, Any], acteur: acces.Acteur) -> dict[str, Any]:
    cnx = stockage.connexion_courante()
    r = cnx.execute(
        select(
            EVENEMENTS_SORTANTS.c.evenement_id,
            EVENEMENTS_SORTANTS.c.type_evenement,
            EVENEMENTS_SORTANTS.c.producteur,
            EVENEMENTS_SORTANTS.c.charge,
        ).where(EVENEMENTS_SORTANTS.c.evenement_id == wct_id)
    ).one_or_none()
    if r is None:
        raise contexte_materiaux_appareil.Refus("WCT-INCONNU")
    charge = codec.decoder(r.charge)
    if (
        r.type_evenement != "m4.travaux_termines"
        or r.producteur != "m04-field-ops"
        or erreurs_charge(r.type_evenement, charge)
    ):
        raise contexte_materiaux_appareil.Refus("SOURCE-INVALIDE")
    if charge != admission["completion"] or charge["wct_id"] != wct_id:
        raise contexte_materiaux_appareil.Refus("LIAISON-INCOHERENTE")
    if acteur.role == "employee" and charge["technicien_id"] != acteur.personne:
        raise contexte_materiaux_appareil.Refus("INTERVENTION-NON-ASSIGNEE")
    return {
        **admission,
        "wct": {
            "evenement_id": r.evenement_id,
            "type": r.type_evenement,
            "producteur": r.producteur,
            "charge": charge,
            "catalogue_valide": True,
        },
    }


def _sources_m6_contexte(wct_id: str, admission: dict[str, Any]) -> dict[str, Any]:
    cnx = stockage.connexion_courante()
    rows = cnx.execute(
        select(REGISTRES.c.rang, REGISTRES.c.maillon)
        .where(REGISTRES.c.departement == _DEPARTEMENT, REGISTRES.c.registre == "besoins_prevus")
        .order_by(REGISTRES.c.rang)
    ).all()
    prevus = [{"rang": r.rang, "maillon": codec.decoder(r.maillon)} for r in rows]
    records = cnx.execute(
        select(
            EVENEMENTS_SORTANTS.c.evenement_id,
            EVENEMENTS_SORTANTS.c.type_evenement,
            EVENEMENTS_SORTANTS.c.producteur,
            EVENEMENTS_SORTANTS.c.charge,
        ).where(EVENEMENTS_SORTANTS.c.type_evenement.in_(("m3.besoins_materiaux", "m3.devis_accepte")))
    ).all()
    pubs = [
        {
            "evenement_id": r.evenement_id,
            "type": r.type_evenement,
            "producteur": r.producteur,
            "charge": codec.decoder(r.charge),
        }
        for r in records
    ]
    if len(prevus) + len(pubs) + admission["admission_lignes"] + 1 <= contexte_materiaux_appareil.PLAFOND_LIGNES:
        for pub in pubs:
            pub["catalogue_valide"] = not erreurs_charge(pub["type"], pub["charge"])
    return {**admission, "prevus": prevus, "m3": pubs}


def lire_contexte_materiaux_appareil(
    intervention_id: str, wct_id: str, decalage: int = 0, limite: int = 8
) -> dict[str, Any]:
    acteur, verdict = _declarant_appareil()
    if acteur is None or verdict is not None:
        return contexte_materiaux_appareil.refuser("IDENTITE-INVALIDE")
    if not contexte_materiaux_appareil.arguments_valides(intervention_id, wct_id, decalage, limite):
        return contexte_materiaux_appareil.refuser("ARGUMENTS-INVALIDES")
    try:
        admission = _admission_m4_contexte(intervention_id, acteur)
        admission = _wct_m4_contexte(wct_id, admission, acteur)
        sources = _sources_m6_contexte(wct_id, admission)
    except contexte_materiaux_appareil.Refus as exc:
        return contexte_materiaux_appareil.refuser(exc.suffixe)
    except Exception:
        return contexte_materiaux_appareil.refuser("SOURCE-INVALIDE")
    return contexte_materiaux_appareil.lire(sources, intervention_id, wct_id, acteur, decalage, limite)


def autoriser_declaration_preuves(wct_id: str, formulaire: dict[str, Any] | None = None):
    """Garde fraîche nommée, appelée avant claim/rejeu et avant l'exécution."""
    p = preuves_pertes_bris_appareil
    appelante = contexte.identite_appelante()
    acteur, verdict = _declarant_appareil()
    if appelante is None or appelante.source != "appareil" or acteur is None or verdict is not None:
        raise p.Refus("IDENTITE-INVALIDE")
    if not p.texte(wct_id):
        raise p.Refus("ARGUMENTS-INVALIDES")
    try:
        wct = _wct_publie_par_m4(wct_id)
        if wct is None:
            raise p.Refus("WCT-INCONNU")
        ok, code = validation.valider_wct(wct)
        if not ok:
            raise p.Refus("SOURCE-INVALIDE")
        if acces.controler_declarant(wct, acteur) is not None:
            raise p.Refus("INTERVENTION-NON-ASSIGNEE")
        admission = _admission_m4_contexte(wct["intervention_id"], acteur)
        _wct_m4_contexte(wct_id, admission, acteur)
    except (ValueError, TypeError, KeyError):
        raise p.Refus("SOURCE-INVALIDE") from None
    if not all(p.texte(wct[k]) for k in ("wct_id", "intervention_id")):
        raise p.Refus("PROJECTION-INVALIDE")
    besoin, nombre_prevus = _besoin_preuves(wct)
    if formulaire is not None:
        ok, code = validation.valider_formulaire_materiaux_utilises(formulaire, wct)
        if not ok:
            raise p.Refus("FORMULAIRE-INVALIDE")
        if not p.texte(formulaire["chantier_id"]) or any(
            not p.texte(x["materiau_id"]) or not p.texte(x["unite"]) for x in formulaire["lignes_materiaux"]
        ):
            raise p.Refus("PROJECTION-INVALIDE")
        if any(
            not p.nombre_projectable(ligne[k])
            for ligne in formulaire["lignes_materiaux"]
            for k in ("quantite", "quantite_estimee") if k in ligne
        ):
            raise p.Refus("PROJECTION-INVALIDE")
        if acces.controler_chantier(formulaire, wct, besoin, acteur) is not None:
            raise p.Refus("CHANTIER-INCOHERENT")
    nombre_sources = admission["admission_lignes"] + 1 + nombre_prevus
    if nombre_sources > p.PLAFOND_LIGNES:
        raise p.Refus("BORNE-SOURCES")
    return acteur, wct, nombre_sources, besoin


def _besoin_preuves(wct):
    p = preuves_pertes_bris_appareil
    try:
        copies = list(_besoins_prevus_de_l_appel(None))
        if len(copies) > p.PLAFOND_LIGNES:
            raise p.Refus("BORNE-SOURCES")
        if any(type(x) is not dict for x in copies):
            raise p.Refus("SOURCE-INVALIDE")
        besoin = besoins_prevus.pour_devis(wct.get("devis_id"), copies)
        if besoin is not None and besoin.get("chantier_id") is not None and not p.texte(besoin["chantier_id"]):
            raise p.Refus("SOURCE-INVALIDE")
        return besoin, len(copies)
    except (ValueError, TypeError, KeyError):
        raise p.Refus("SOURCE-INVALIDE") from None


def _snapshots_preuves(lignes_autorisation=0):
    p = preuves_pertes_bris_appareil
    try:
        principal = list(stockage.maillons(_DEPARTEMENT, "principal"))
        preuves = list(stockage.maillons(_DEPARTEMENT, "preuves_pertes_bris"))
    except (ValueError, TypeError):
        raise p.Refus("REGISTRE-INVALIDE") from None
    if len(principal) + len(preuves) + lignes_autorisation > p.PLAFOND_LIGNES:
        raise p.Refus("BORNE-SOURCES")
    p.valider_snapshots(principal, preuves)
    return principal, preuves


def _photo_verifiee(reference: str):
    cnx = stockage.connexion_courante()
    blob = fichiers.lire_blob_verifie(cnx, reference)
    if not blob.accepte or blob.octets is None or blob.type_mime not in fichiers.TYPES_MIME_PERMIS:
        raise preuves_pertes_bris_appareil.Refus("PHOTO-INDISPONIBLE")
    return {
        "reference": reference,
        "empreinte_sha256": fichiers.empreinte_depuis_reference(reference),
        "type_mime": blob.type_mime,
        "taille_octets": len(blob.octets),
    }


def _ajouter_preuve(maillon):
    stockage.maillons(_DEPARTEMENT, "preuves_pertes_bris").append(maillon, rang_attendu=maillon["index"])


def _postflight_preuves(reponse):
    preuves_pertes_bris_appareil.verifier_borne(reponse, contexte.limite_sortie() or 5400, mutation=True)


def declarer_materiaux_avec_preuves_appareil(wct_id: str, formulaire: dict[str, Any], preuves_lignes: list):
    p = preuves_pertes_bris_appareil
    try:
        acteur, wct, nombre_sources, _ = autoriser_declaration_preuves(wct_id, formulaire)
        plan, code = preuves_pertes_bris.valider_preuves_lignes(formulaire["lignes_materiaux"], preuves_lignes)
        if code:
            return {"accepte": False, "verdict": {"code": code}}
        horodatage = contexte.horodatage_reception()
        if horodatage is None:
            raise p.Refus("CONTEXTE-MUTATION-ABSENT")
        avant, anciennes = _snapshots_preuves(nombre_sources)
        if any(m.get("wct_id") == wct_id for m in avant):
            raise p.Refus("DECLARATION-DEJA-SOUMISE")
        # Placeholders de SHA de taille fixe : mesure uniquement, jamais exportés comme références.
        liens = [
            {
                "position_ligne": x["position_ligne"],
                "reference_mouvement": {
                    "registre": "principal",
                    "index": len(avant) + x["position_ligne"],
                    "hash_maillon": "0" * 64,
                },
                "reference_preuve": {
                    "registre": "preuves_pertes_bris",
                    "index": len(anciennes) + k,
                    "hash_maillon": "0" * 64,
                },
                "nombre_photos": len(x["photos"]),
            }
            for k, x in enumerate(plan)
        ]
        _postflight_preuves(p.ack(wct, formulaire, liens, len(avant) + len(formulaire["lignes_materiaux"]), "0" * 64))
        verifiees = []
        for x in plan:
            verifiees.append([_photo_verifiee(ref) for ref in x["photos"]])
        cnx = stockage.connexion_courante()
        with cnx.begin_nested():
            resultat = declarer_materiaux_utilises(wct_id, formulaire)
            if not resultat.get("accepte"):
                raise p.Refus("DECLARATION-REFUSEE")
            apres, _ = _snapshots_preuves(nombre_sources)
            ajouts = p.lier_ajouts(avant, apres, formulaire)
            pred = anciennes[-1]["hash_maillon"] if anciennes else ""
            liens = []
            for k, x in enumerate(plan):
                preuve = p.construire_preuve(
                    len(anciennes) + k,
                    pred,
                    wct,
                    formulaire,
                    x,
                    ajouts[x["position_ligne"]],
                    verifiees[k],
                    acteur,
                    horodatage,
                )
                _ajouter_preuve(preuve)
                pred = preuve["hash_maillon"]
                liens.append(
                    {
                        "position_ligne": x["position_ligne"],
                        "reference_mouvement": preuve["reference_mouvement"],
                        "reference_preuve": p.reference("preuves_pertes_bris", preuve),
                        "nombre_photos": len(preuve["photos"]),
                    }
                )
            final, final_preuves = _snapshots_preuves(nombre_sources)
            if final != apres or len(final_preuves) != len(anciennes) + len(plan):
                raise p.Refus("LIAISON-INCOHERENTE")
            reponse = p.ack(wct, formulaire, liens, len(final), final[-1]["hash_maillon"])
            _postflight_preuves(reponse)
        return reponse
    except (p.Refus, contexte_materiaux_appareil.Refus) as exc:
        return p.refuser(exc.suffixe)
    except EcritureConcurrente:
        raise
    except Exception as exc:
        # Ces types sont capturés par executer comme refus métier ; une panne après
        # écriture doit au contraire remonter et annuler aussi la réclamation Cap.
        raise RuntimeError("échec technique de la déclaration atomique avec preuves") from exc



def _autoriser_admin_preuves(wct_id):
    p = preuves_pertes_bris_appareil
    ident = contexte.identite_appelante()
    acteur, verdict = _declarant_appareil()
    if ident is None or ident.source != "appareil" or acteur is None or verdict is not None or acteur.role != "admin":
        raise p.Refus("IDENTITE-INVALIDE")
    acteur, wct, nombre_sources, besoin = autoriser_declaration_preuves(wct_id)
    return acteur, wct, nombre_sources, besoin


def _photo_est_disponible(photo):
    try:
        return _photo_verifiee(photo["reference"]) == photo
    except preuves_pertes_bris_appareil.Refus:
        return False


def lire_preuves_pertes_wct_appareil(wct_id: str, decalage: int = 0, limite: int = 8):
    p = preuves_pertes_bris_appareil
    try:
        _, wct, nombre_sources, _ = _autoriser_admin_preuves(wct_id)
        principal, preuves = _snapshots_preuves(nombre_sources)
        dto = p.lire(wct, principal, preuves, decalage, limite, _photo_est_disponible)
        p.verifier_borne(dto, contexte.limite_sortie() or 5400)
        return dto
    except (p.Refus, contexte_materiaux_appareil.Refus) as exc:
        return p.refuser(exc.suffixe)


def _selection_photo(wct_id, preuve, position_photo):
    p = preuves_pertes_bris_appareil
    acteur, wct, nombre_sources, besoin = _autoriser_admin_preuves(wct_id)
    if (
        type(preuve) is not dict
        or set(preuve) != {"index", "hash_maillon"}
        or type(preuve["index"]) is not int
        or preuve["index"] < 0
        or type(preuve["hash_maillon"]) is not str
        or not p._hash(preuve["hash_maillon"])
        or type(position_photo) is not int
        or not 0 <= position_photo < 3
    ):
        raise p.Refus("ARGUMENTS-INVALIDES")
    principal, preuves = _snapshots_preuves(nombre_sources)
    if preuve["index"] >= len(preuves):
        raise p.Refus("PHOTO-INCONNUE")
    choisie = preuves[preuve["index"]]
    if (
        choisie["hash_maillon"] != preuve["hash_maillon"]
        or choisie["wct_id"] != wct_id
        or choisie["intervention_id"] != wct["intervention_id"]
        or position_photo >= len(choisie["photos"])
    ):
        raise p.Refus("LIAISON-INCOHERENTE")
    try:
        attendu = acces.chantier_attendu(wct, besoin, acteur)
    except (ValueError, TypeError, KeyError):
        raise p.Refus("SOURCE-INVALIDE") from None
    if attendu is not None and choisie["chantier_id"] != attendu:
        raise p.Refus("LIAISON-INCOHERENTE")
    return acteur, choisie["photos"][position_photo]


def revalider_autorite_photo(wct_id, preuve, position_photo, *, cnx_factory=stockage.transaction):
    """Nouvelle transaction courte, rôle et liens actuels ; ne lit jamais de pixels/CAS."""
    p = preuves_pertes_bris_appareil
    if stockage.connexion_courante() is not None:
        raise RuntimeError("la revalidation photo exige une transaction fraîche")
    try:
        with cnx_factory() as cnx:
            if stockage.connexion_courante() is not cnx:
                raise RuntimeError("connexion photo non canonique")
            acteur, photo = _selection_photo(wct_id, preuve, position_photo)
            return {
                "accepte": True,
                **photo,
                "autorite": {
                    "personne": acteur.personne,
                    "role": acteur.role,
                    "source": contexte.identite_appelante().source,
                },
            }
    except (p.Refus, contexte_materiaux_appareil.Refus) as exc:
        return p.refuser(exc.suffixe)


def autoriser_et_lire_photo(wct_id, preuve, position_photo, *, cnx_factory=stockage.transaction):
    """Helper privé D : sélection métier fermée et CAS complet revérifié, jamais hash libre."""
    p = preuves_pertes_bris_appareil
    if stockage.connexion_courante() is not None:
        raise RuntimeError("l’admission photo exige une transaction fraîche")
    try:
        with cnx_factory() as cnx:
            if stockage.connexion_courante() is not cnx:
                raise RuntimeError("connexion photo non canonique")
            acteur, photo = _selection_photo(wct_id, preuve, position_photo)
            blob = fichiers.lire_blob_verifie(cnx, photo["reference"])
            if (
                not blob.accepte
                or blob.octets is None
                or blob.type_mime != photo["type_mime"]
                or len(blob.octets) != photo["taille_octets"]
            ):
                raise p.Refus("PHOTO-INDISPONIBLE")
            return {
                "accepte": True,
                **photo,
                "octets": blob.octets,
                "autorite": {
                    "personne": acteur.personne,
                    "role": acteur.role,
                    "source": contexte.identite_appelante().source,
                },
            }
    except (p.Refus, contexte_materiaux_appareil.Refus) as exc:
        return p.refuser(exc.suffixe)



# T4.27-b : annotation humaine révisable; aucune écriture stock/coût/M4/M10.
def _sources_classement_variance(wct_id):
    c = classement_variance_appareil
    try:
        acteur, wct, nombre_sources, besoin = _autoriser_admin_preuves(wct_id)
    except (
        preuves_pertes_bris_appareil.Refus,
        contexte_materiaux_appareil.Refus,
    ) as exc:
        raise c.Refus(exc.suffixe) from None
    cnx = stockage.connexion_courante()
    acces_classement = acces
    from opsys.stockage.schema import EVENEMENTS_SORTANTS

    from . import preuves_pertes_bris_appareil as p

    ident = f"m6-variance-{wct_id}-evaluee"
    row = cnx.execute(
        select(
            EVENEMENTS_SORTANTS.c.type_evenement,
            EVENEMENTS_SORTANTS.c.producteur,
            EVENEMENTS_SORTANTS.c.charge,
        ).where(EVENEMENTS_SORTANTS.c.evenement_id == ident)
    ).one_or_none()
    if row is None:
        raise c.Refus("VARIANCE-NON-FINALISEE")
    try:
        charge = codec.decoder(row.charge)
    except (ValueError, TypeError, KeyError):
        raise c.Refus("SOURCE-INVALIDE") from None
    if (
        row.type_evenement != "m6.variance_chantier"
        or row.producteur != _DEPARTEMENT
        or erreurs_charge("m6.variance_chantier", charge)
    ):
        raise c.Refus("SOURCE-INVALIDE")
    try:
        chantier = acces_classement.chantier_attendu(wct, besoin, acteur)
        if chantier is not None and charge["chantier_id"] != chantier:
            raise c.Refus("LIAISON-INCOHERENTE")
        principal, preuves = _snapshots_preuves(nombre_sources)
    except (p.Refus, contexte_materiaux_appareil.Refus) as exc:
        raise c.Refus(exc.suffixe) from None
    try:
        classes = list(stockage.maillons(_DEPARTEMENT, c.REGISTRE))
        refus = list(stockage.maillons(_DEPARTEMENT, c.REGISTRE_REFUS))
    except (ValueError, TypeError, KeyError):
        raise c.Refus("REGISTRE-INVALIDE") from None
    source = c.valider_source(wct, charge, principal, preuves, classes, nombre_sources, refus)
    return acteur, source


def autoriser_classement_variance_appareil(
    arguments, *, nom="m6_classer_cause_variance_appareil"
):
    """Admission actuelle avant claim/cache; aucune précondition de dernière révision."""
    c = classement_variance_appareil
    if nom not in c.NOMS or type(arguments) is not dict:
        raise c.Refus("ARGUMENTS-INVALIDES")
    ident = contexte.identite_appelante()
    acteur, verdict = _declarant_appareil()
    if (
        ident is None
        or ident.source != "appareil"
        or acteur is None
        or verdict is not None
        or acteur.role != "admin"
    ):
        raise c.Refus("IDENTITE-INVALIDE")
    if nom == c.ECRIRE:
        from .classement_variance_contexte import intention

        intention(arguments)  # Meta requise après identité mais avant toute source métier.
    sel = arguments.get("selection")
    if nom == c.LISTE:
        wct_id = arguments.get("wct_id")
        if not c.texte(wct_id):
            raise c.Refus("ARGUMENTS-INVALIDES")
    else:
        if not c.selection_valide(sel):
            raise c.Refus("ARGUMENTS-INVALIDES")
        wct_id = sel["wct_id"]
    acteur, source = _sources_classement_variance(wct_id)
    if sel is not None:
        c.choisir(source, sel)
    return acteur, source


def _ajouter_classement_variance(maillon):
    stockage.maillons(_DEPARTEMENT, classement_variance_appareil.REGISTRE).append(
        maillon, rang_attendu=maillon["index"]
    )


def _ajouter_refus_classement_variance(maillon):
    c = classement_variance_appareil
    stockage.maillons(_DEPARTEMENT, c.REGISTRE_REFUS).append(maillon, rang_attendu=maillon["index"])


def classer_cause_variance_appareil(
    selection, cause, motif, classement_attendu, references_pieces
):
    from datetime import datetime

    from . import classement_variance_contexte as ctx

    c = classement_variance_appareil
    args = {"selection": selection, "cause": cause, "motif": motif,
            "classement_attendu": classement_attendu, "references_pieces": references_pieces}
    try:
        acteur, source = autoriser_classement_variance_appareil(args)
        intention = ctx.intention(args)
        meta = ctx.meta_courante()
        reception = contexte.horodatage_reception()
        if (reception is None or reception.appareil != meta.appareil
                or reception.horodatage_appareil != datetime.fromisoformat(meta.horodatage_appareil)):
            raise c.Refus("CONTEXTE-MUTATION-ABSENT")
        auteur = {"personne": acteur.personne, "role": acteur.role, "source": "appareil"}
        if any(m.get("version_schema") == 2 and c.paire(m["intention"]) == c.paire(intention)
               for m in [*source["classements"], *source["refus"]]):
            raise c.Refus("REJEU-INCOHERENT")
    except c.Refus as exc:
        return c.refuser(exc.suffixe)
    limite = contexte.limite_sortie() or c.BORNE_SORTIE
    try:
        nouveau = c.construire(source, selection, cause, motif, classement_attendu,
                               references_pieces, auteur, reception, intention=intention)
        c.verifier_borne(c.ack(nouveau), limite, mutation=True)
    except c.Refus as exc:
        if exc.suffixe not in c.REFUS_FRAIS:
            return c.refuser(exc.suffixe)
        nouveau = c.construire_refus(source, selection, exc.suffixe, intention, auteur, reception)
        try:
            c.verifier_borne(c.ack_refus(nouveau), limite, mutation=True)
        except c.Refus as quota:
            raise RuntimeError("preuve de refus atomique hors de sa borne") from quota
        try:
            with stockage.connexion_courante().begin_nested():
                _ajouter_refus_classement_variance(nouveau)
                actuel = list(stockage.maillons(_DEPARTEMENT, c.REGISTRE_REFUS))
                c.valider_refus(actuel)
                c.valider_associations(source["classements"], actuel)
                if actuel[-1] != nouveau:
                    raise c.Refus("REJEU-INCOHERENT")
                response = c.ack_refus(actuel[-1])
                c.verifier_borne(response, limite, mutation=True)
            return response
        except Exception as panne:
            raise RuntimeError("échec technique du refus atomique de classement") from panne
    try:
        with stockage.connexion_courante().begin_nested():
            _ajouter_classement_variance(nouveau)
            actuel = list(stockage.maillons(_DEPARTEMENT, c.REGISTRE))
            c.valider_classements(actuel)
            c.valider_associations(actuel, source["refus"])
            if actuel[-1] != nouveau:
                raise c.Refus("LIAISON-INCOHERENTE")
            response = c.ack(actuel[-1])
            c.verifier_borne(response, limite, mutation=True)
        return response
    except Exception as exc:
        raise RuntimeError("échec technique du classement atomique de variance") from exc


def verifier_rejeu_classement_variance_appareil(arguments, reponse):
    """Preuve propre positive/négative persistée, pas précondition de dernier état."""
    from datetime import datetime

    from . import classement_variance_contexte as ctx

    c = classement_variance_appareil
    acteur, source = autoriser_classement_variance_appareil(arguments)
    intention = ctx.intention(arguments)
    meta = ctx.meta_courante()
    if type(reponse) is not dict or reponse.get("ok") is not True:
        raise c.Refus("REJEU-INCOHERENT")
    ack = reponse.get("resultat")
    if type(ack) is not dict:
        raise c.Refus("REJEU-INCOHERENT")
    if ack.get("accepte") is False:
        keys = {"accepte", "version_schema", "verdict", "intention", "preuve_refus",
                "auteur", "horodatage_appareil_declare"}
        if (not c.ferme(ack, keys) or type(ack["version_schema"]) is not int
                or ack["version_schema"] != 2 or ack["intention"] != intention
                or not c.reference_valide(ack["preuve_refus"], c.REGISTRE_REFUS)):
            raise c.Refus("REJEU-INCOHERENT")
        ref = ack["preuve_refus"]
        if ref["index"] >= len(source["refus"]):
            raise c.Refus("REJEU-INCOHERENT")
        maillon = source["refus"][ref["index"]]
        if c.ack_refus(maillon) != ack or maillon["selection"] != arguments["selection"]:
            raise c.Refus("REJEU-INCOHERENT")
    else:
        v2 = "version_schema" in ack
        keys = {"accepte", "resultat", "registre"} | ({"version_schema"} if v2 else set())
        if (not c.ferme(ack, keys) or ack.get("accepte") is not True
                or (v2 and (type(ack["version_schema"]) is not int or ack["version_schema"] != 2))):
            raise c.Refus("REJEU-INCOHERENT")
        result = ack["resultat"]
        if type(result) is not dict or not c.reference_valide(result.get("reference"), c.REGISTRE):
            raise c.Refus("REJEU-INCOHERENT")
        ref = result["reference"]
        if ref["index"] >= len(source["classements"]):
            raise c.Refus("REJEU-INCOHERENT")
        maillon = source["classements"][ref["index"]]
        if (c.ack(maillon) != ack
                or any(result.get(k) != arguments.get(k)
                       for k in ["selection", "cause", "motif", "references_pieces"])
                or result.get("reference_precedente") != arguments.get("classement_attendu")
                or (v2 and result.get("intention") != intention)
                or result.get("appareil_id") != meta.appareil):
            raise c.Refus("REJEU-INCOHERENT")
    if (maillon["auteur"] != {"personne": acteur.personne, "role": "admin", "source": "appareil"}
            or datetime.fromisoformat(maillon["horodatage_appareil_declare"])
            != datetime.fromisoformat(meta.horodatage_appareil)):
        raise c.Refus("REJEU-INCOHERENT")
    c.verifier_borne(ack, contexte.limite_sortie() or c.BORNE_SORTIE, mutation=True)


def lister_variances_classables_wct_appareil(wct_id, decalage=0, limite=8):
    c = classement_variance_appareil
    try:
        _, source = autoriser_classement_variance_appareil(
            {"wct_id": wct_id}, nom=c.LISTE
        )
        return {
            "accepte": True,
            "resultat": c.lire(
                source,
                decalage,
                limite,
                borne=contexte.limite_sortie() or c.BORNE_SORTIE,
            ),
        }
    except c.Refus as exc:
        return c.refuser(exc.suffixe)


def lire_historique_classement_variance_appareil(selection, decalage=0, limite=8):
    c = classement_variance_appareil
    try:
        _, source = autoriser_classement_variance_appareil(
            {"selection": selection}, nom=c.HISTO
        )
        return {
            "accepte": True,
            "resultat": c.lire(
                source,
                decalage,
                limite,
                selection,
                borne=contexte.limite_sortie() or c.BORNE_SORTIE,
            ),
        }
    except c.Refus as exc:
        return c.refuser(exc.suffixe)


_REFERENCE_CLASSEMENT = {
    "type": "object",
    "properties": {
        "registre": {"type": "string", "enum": ["classements_variance"]},
        "index": {"type": "integer", "minimum": 0},
        "hash_maillon": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    },
    "required": ["registre", "index", "hash_maillon"],
    "additionalProperties": False,
}
_SELECTION_VARIANCE = {
    "type": "object",
    "properties": {
        "wct_id": {"type": "string", "minLength": 1, "maxLength": 256},
        "reference_variance": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["m6.variance_chantier"]},
                "evenement_id": {"type": "string", "maxLength": 300},
                "empreinte_charge": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
            },
            "required": ["type", "evenement_id", "empreinte_charge"],
            "additionalProperties": False,
        },
        "position_ligne": {"type": "integer", "minimum": 0, "maximum": 9999},
        "materiau_id": {"type": "string", "minLength": 1, "maxLength": 256},
    },
    "required": ["wct_id", "reference_variance", "position_ligne", "materiau_id"],
    "additionalProperties": False,
}
_REFERENCE_PIECE = {
    **_REFERENCE_CLASSEMENT,
    "properties": {
        **_REFERENCE_CLASSEMENT["properties"],
        "registre": {"type": "string", "enum": ["principal"]},
    },
}
_REFERENCE_PREUVE_CLASSEMENT = {
    **_REFERENCE_CLASSEMENT,
    "type": ["object", "null"],
    "properties": {
        **_REFERENCE_CLASSEMENT["properties"],
        "registre": {"type": "string", "enum": ["preuves_pertes_bris"]},
    },
}
_PAGE_CLASSEMENT = {
    "decalage": {"type": "integer", "minimum": 0, "maximum": 10000},
    "limite": {"type": "integer", "minimum": 1, "maximum": 8},
}


def outils() -> tuple[Outil, ...]:
    return (
        Outil(
            nom="m6_receptionner_commande",
            description=(
                "Réceptionne une commande de bout en bout : résout le prix par ligne (catalogue -> historique -> "
                "indéterminé), écrit le stock reçu, donne le verdict de la livraison, un signal à M5 si un montant "
                "est dû et des suggestions de réapprovisionnement si un seuil est fourni. Si bon_demande.po_id "
                "référence un PO persisté (m6_creer_po_brouillon) : bon_demande doit correspondre au PO, les "
                "livraisons se CUMULENT (la livraison qui complète un PO partiel le passe à received), un écart de "
                "prix au-delà du seuil est signalé, et m6.reception_enregistree (ce qui est arrivé cette fois-là, "
                "aucun montant) est publié dans la même transaction. Refuse, avant d'écrire : quantité négative ou "
                "non finie (aussi hors PO), horodatage sans fuseau, livraison déjà enregistrée."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "bon_demande": _BON_DEMANDE,
                    "reception_po": _RECEPTION_PO,
                    "catalogue_materiaux": _CATALOGUE,
                    "seuils_reorder": _SEUILS_REORDER,
                    "registre_historique": _REGISTRE_HISTORIQUE,
                    "bons_commande_historique": _BONS_COMMANDE_HISTORIQUE,
                },
                "required": ["bon_demande", "reception_po"],
                "additionalProperties": False,
            },
            fonction=receptionner_commande,
            autonomie=Autonomie.T1,
            # §9.5 M6 (réception rapide). Pas `employee` : la réponse porte des prix (§9.3 « aucun coût »).
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m6_consommer_materiaux",
            description=(
                "Ancien contrat conservé pour compatibilité ({wct, formulaire}), désormais lié au WCT "
                "publié par M4 : le champ wct sélectionne son wct_id mais sa charge est relue dans "
                "l'événement canonique. Exige une transaction durable, refuse un WCT inconnu ou une "
                "intervention divergente sans écriture, et refuse un second débit du même WCT même "
                "si la clé de transport change. Décrémente le stock du chantier. La confirmation ne "
                "porte jamais de coût. Pour le formulaire de fin de chantier enrichi, utiliser "
                "m6_declarer_materiaux_utilises."
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
                "réécrite. On ne fournit que le wct_id (celui de l'accusé de m4_completer_intervention) : "
                "M6 lit lui-même le WCT publié par M4 pour cet identifiant, et refuse un wct_id que M4 "
                "n'a jamais publié (REJ-WCT-INCONNU) sans rien écrire. Distincte de "
                "m6_consommer_materiaux, qui garde son contrat {materiau_id, quantite} exact et n'est "
                "pas remplacé."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "wct_id": _WCT_ID,
                    "formulaire": _FORMULAIRE_MATERIAUX_UTILISES,
                },
                "required": ["wct_id", "formulaire"],
                "additionalProperties": False,
            },
            fonction=declarer_materiaux_utilises,
            autonomie=Autonomie.T1,
            # §9.3 et §9.7 (formulaire des matériaux utilisés, sans coût affiché). M6 relit le WCT (T1.4-i).
            roles_appareil=frozenset({"employee", "admin"}),
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
            # §9 (inventaire) : comptage physique, constat de stock.
            roles_appareil=frozenset({"admin"}),
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
            # §9.5 M6 (stock critique, rapport de pertes et bris).
            roles_appareil=frozenset({"admin"}),
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
            # §9.5 M6 (écarts de chantier, validation d'usage).
            roles_appareil=frozenset({"admin"}),
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
        # ----------------------------------------------------------------------------- T2.5 point 2
        Outil(
            nom="m6_enregistrer_fournisseur",
            description=(
                "Crée ou corrige la fiche d'un fournisseur (M6.2) : identité et coordonnées "
                "SEULEMENT (nom, courriel de commande, téléphone, catégories vendues, délai "
                "habituel, format de commande préféré) — jamais un prix (livre_prix.py, séparé). "
                "Champs optionnels omis restent inconnus, jamais devinés. Idempotent : rejouer la "
                "même fiche est un no-op ; des coordonnées différentes pour le même fournisseur_id "
                "sont une correction (fiche vivante), jamais un rejet."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "fournisseur_id": {"type": "string"},
                    "nom": {"type": "string"},
                    "horodatage": {"type": "string"},
                    "courriel_commande": {"type": ["string", "null"]},
                    "telephone": {"type": ["string", "null"]},
                    "categories_vendues": _CATEGORIES_VENDUES,
                    "delai_habituel_jours": {"type": ["integer", "null"]},
                    "format_commande_prefere": {"type": ["string", "null"]},
                    "fournisseurs_historique": _FOURNISSEURS_HISTORIQUE,
                },
                "required": ["fournisseur_id", "nom", "horodatage"],
                "additionalProperties": False,
            },
            fonction=enregistrer_fournisseur,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m6_lister_fournisseurs",
            description="Liste les fournisseurs connus (état courant de chacun). Lecture seule.",
            parametres={
                "type": "object",
                "properties": {"fournisseurs_historique": _FOURNISSEURS_HISTORIQUE},
                "required": [],
                "additionalProperties": False,
            },
            fonction=lister_fournisseurs,
            autonomie=Autonomie.T0,
        ),
        # ----------------------------------------------------------------------------------- T2.4
        Outil(
            nom="m6_enregistrer_prix",
            description=(
                "Ajoute une entrée au livre de prix (M6.3) : prix FOURNI (jamais calculé), pour un "
                "matériau et un fournisseur donnés, daté (date_effet). Append-only et versionné : "
                "n'écrase jamais une entrée antérieure, chaque hausse ou correction est une "
                "nouvelle entrée. source_document (facture ou PO d'origine) optionnel : sans référence, "
                "marquage_source=FALLBACK_PRICE_BOOK; une référence est SOURCE_DECLAREE, jamais authentifiée ici. "
                "unite du tarif optionnelle, fournie explicitement : aucune unité inférée si elle est absente."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "materiau_id": {"type": "string"},
                    "fournisseur_id": {"type": "string"},
                    "prix_unitaire": {"type": "number"},
                    "devise": {"type": "string"},
                    "date_effet": {"type": "string"},
                    "source_document": {"type": ["string", "null"]},
                    "unite": {"type": ["string", "null"]},
                    "livre_prix_historique": _LIVRE_PRIX_HISTORIQUE,
                },
                "required": ["materiau_id", "fournisseur_id", "prix_unitaire", "devise", "date_effet"],
                "additionalProperties": False,
            },
            fonction=enregistrer_prix,
            autonomie=Autonomie.T1,
        ),
        # ----------------------------------------------------------------------------- T2.5 point 3
        Outil(
            nom="m6_creer_po_brouillon",
            description=(
                "Crée un PO au statut BROUILLON (M6.5) à partir des besoins matériaux prévus pour "
                "un devis (m6_enregistrer_besoins_prevus, source m3.devis_accepte) et du stock déjà "
                "disponible pour le chantier : seul l'écart est commandé, calculé par le code, "
                "jamais deviné. Résout le prix attendu de chaque ligne depuis le livre de prix "
                "(PRIX_LIVRE ou INDETERMINE — jamais inventé), avec provenance capturée séparément "
                "des lignes économiques; un PO ancien sans capture est ESTIMATED/NON_CAPTURE. "
                "Refuse fail-closed si le fournisseur "
                "n'est pas enregistré (m6_enregistrer_fournisseur d'abord). Rend "
                "statut=\"aucun_achat_requis\" (po=null) si le stock couvre déjà tout le besoin."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "po_id": {"type": "string"},
                    "devis_id": {"type": "string"},
                    "fournisseur_id": {"type": "string"},
                    "horodatage": {"type": "string"},
                    "besoins_prevus_historique": _BESOINS_PREVUS_HISTORIQUE,
                    "registre_historique": _REGISTRE_HISTORIQUE,
                    "livre_prix_historique": _LIVRE_PRIX_HISTORIQUE,
                    "fournisseurs_historique": _FOURNISSEURS_HISTORIQUE,
                    "bons_commande_historique": _BONS_COMMANDE_HISTORIQUE,
                },
                "required": ["po_id", "devis_id", "fournisseur_id", "horodatage"],
                "additionalProperties": False,
            },
            fonction=creer_po_brouillon,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m6_approuver_po",
            description=(
                "Approuve un PO (draft ou pending_admin_review -> approved). Refuse fail-closed "
                "(REJ-PO-PRIX-INDETERMINE) si au moins une ligne n'a pas de prix résolu au livre de "
                "prix : un PO ne peut pas être approuvé sur un prix encore à fournir."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "po_id": {"type": "string"},
                    "horodatage": {"type": "string"},
                    "bons_commande_historique": _BONS_COMMANDE_HISTORIQUE,
                },
                "required": ["po_id", "horodatage"],
                "additionalProperties": False,
            },
            fonction=approuver_po,
            autonomie=Autonomie.T1,
            # §9.2 et §9.5 (le propriétaire approuve les bons de commande).
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m6_annuler_po",
            description="Annule un PO (-> cancelled), depuis tout statut non terminal. motif humain requis.",
            parametres={
                "type": "object",
                "properties": {
                    "po_id": {"type": "string"},
                    "motif": {"type": "string"},
                    "horodatage": {"type": "string"},
                    "bons_commande_historique": _BONS_COMMANDE_HISTORIQUE,
                },
                "required": ["po_id", "motif", "horodatage"],
                "additionalProperties": False,
            },
            fonction=annuler_po,
            autonomie=Autonomie.T1,
            # §9.5 M6 (PO à approuver : le refus est une annulation avec motif).
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m6_generer_courriel_po",
            description=(
                "Génère le corps texte du courriel de commande (M6.6 : objet, destinataire, liste "
                "des matériaux, chantier, numéro de PO) pour un PO approved -> email_ready. AUCUN "
                "envoi réel : le courriel est retourné et persisté sur le PO pour un repli manuel "
                "(copier-coller) tant que M1 n'envoie pas réellement. repli_manuel_requis=true si "
                "le fournisseur n'a pas de courriel de commande enregistré."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "po_id": {"type": "string"},
                    "horodatage": {"type": "string"},
                    "nom_entreprise": {"type": "string"},
                    "fournisseurs_historique": _FOURNISSEURS_HISTORIQUE,
                    "bons_commande_historique": _BONS_COMMANDE_HISTORIQUE,
                },
                "required": ["po_id", "horodatage", "nom_entreprise"],
                "additionalProperties": False,
            },
            fonction=generer_courriel_po,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m6_marquer_po_envoye",
            description=(
                "Verrou d'envoi au fournisseur (email_ready -> sent_to_supplier) : ENGAGEMENT "
                "EXTERNE, N4 — passe par la file d'approbation du socle (department.yaml, bloc "
                "approbations.n4). N'exécute qu'après décision signée ; aucune primitive d'envoi de "
                "courriel réelle n'existe ici (repli manuel documenté, M1 plus tard)."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "po_id": {"type": "string"},
                    "horodatage": {"type": "string"},
                    "bons_commande_historique": _BONS_COMMANDE_HISTORIQUE,
                },
                "required": ["po_id", "horodatage"],
                "additionalProperties": False,
            },
            fonction=marquer_po_envoye,
            autonomie=Autonomie.T2,
        ),
        # ----------------------------------------------------------------------------------- T4.14
        Outil(
            nom="m6_reserver_materiel",
            description=(
                "Réserve le matériel d'un devis ACCEPTÉ depuis son prévu définitif (M6.8) : met de côté "
                "min(besoin, disponible) par ligne, jamais plus que le disponible (en main - réservé), sans double "
                "réservation ; un prévu vide ne réserve rien. Rend pret, partiel ou a_commander avec les lignes "
                "manquantes et publie m6.materiel_pret (M4 le lit). Ne crée aucun bon de commande. Le bus le fait "
                "déjà à l'acceptation du devis ; cet outil sert au prévu saisi à la main ou à re-réserver après une "
                "libération."
            ),
            parametres={
                "type": "object",
                "properties": {"devis_id": {"type": "string"}, "horodatage": {"type": "string"}},
                "required": ["devis_id", "horodatage"],
                "additionalProperties": False,
            },
            fonction=reserver_materiel,
            autonomie=Autonomie.T1,
            # N2 : une réservation est une tâche interne (rien de dépensé, rien d'envoyé, réversible par libération).
            niveau=Niveau.N2,
            # §9.5 M6 (chantiers sans matériel prêt) : l'admin réserve ou relance depuis son téléphone.
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m6_liberer_reservation",
            description=(
                "Libère la réservation active d'un devis (annulation du chantier, M6.8) : le stock retenu redevient "
                "disponible, les autres réservations auxquelles il manquait quelque chose se complètent, et "
                "m6.materiel_pret dit à M4 que ce devis n'est plus prêt. Motif requis et gardé. Rejouer une "
                "libération n'écrit rien. Ne supprime aucun historique."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "devis_id": {"type": "string"}, "motif": {"type": "string"}, "horodatage": {"type": "string"},
                },
                "required": ["devis_id", "motif", "horodatage"],
                "additionalProperties": False,
            },
            fonction=liberer_reservation,
            autonomie=Autonomie.T1,
            # N2 (DEFINITION-PRODUIT §5) : libérer ne dépense, n'envoie ni ne supprime rien ; elle remet du stock au
            # disponible, et la trace reste. L'annulation d'un PO, elle, engage (m6_annuler_po).
            niveau=Niveau.N2,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m6_transferer_stock",
            description=(
                "Transfère du stock entre emplacements (M6.9 : depot, camion, remorque, chantier, employe, "
                "fournisseur, retour, rebut, inconnu ; reference requise pour camion, remorque, employe, chantier, "
                "fournisseur). AUDITÉ : acteur, motif requis, horodatage, quantité, avant et après des deux "
                "extrémités, chaîne hash-chaînée. Un transfert déplace, il ne crée ni ne détruit : aucune quantité "
                "par emplacement ne devient négative ; le stock non localisé est à inconnu. Idempotent par "
                "transfert_id. Sortir du stock de la main (fournisseur, retour, rebut) réconcilie les réservations. "
                "La chaîne de mouvements de stock ne change pas."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "transfert_id": {"type": "string"},
                    "materiau_id": {"type": "string"},
                    "quantite": {"type": "number"},
                    "de": _EMPLACEMENT,
                    "vers": _EMPLACEMENT,
                    "motif": {"type": "string"},
                    "horodatage": {"type": "string"},
                },
                "required": ["transfert_id", "materiau_id", "quantite", "de", "vers", "motif", "horodatage"],
                "additionalProperties": False,
            },
            fonction=transferer_stock,
            autonomie=Autonomie.T1,
            # §9.5 M6 (stock critique, réception rapide) : l'admin déplace le stock. Pas `employee` : un transfert
            # vers le rebut ou le fournisseur retire du stock de ce qu'on peut réserver, et le stock non localisé
            # d'aujourd'hui est tout entier à `inconnu`.
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m6_lire_disponibilite",
            description=(
                "Lit, par article (quinze au plus), le stock théorique, le hors main, l'en main, le réservé, le "
                "disponible (en main - réservé) et sa répartition par emplacement (inconnu = non localisé), avec les "
                "réservations actives qui le touchent et ce qui leur manque. Sans materiau_ids : les articles connus. "
                "Lecture seule, quantités en texte décimal, aucun prix."
            ),
            parametres={
                "type": "object",
                "properties": {"materiau_ids": {"type": ["array", "null"], "items": {"type": "string"}}},
                "required": [],
                "additionalProperties": False,
            },
            fonction=lire_disponibilite,
            autonomie=Autonomie.T0,
            # §7 M6 tableau de bord : « stock réservé et disponible », « chantiers sans matériel prêt ».
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m6_lister_wct_pertes_appareil",
            description=("WCT réellement reçus M6 et rapprochés des publications M4, par page courante. "
                         "Références durables natives ; identité DEVICE admin active obligatoire, aucune écriture."),
            parametres={"type": "object", "properties": {
                "decalage": {"type": "integer", "minimum": 0, "maximum": 10000},
                "limite": {"type": "integer", "minimum": 1, "maximum": 8}},
                "required": ["decalage", "limite"], "additionalProperties": False},
            fonction=lister_wct_pertes_appareil, autonomie=Autonomie.T0, roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m6_lire_pertes_alertes_wct_appareil",
            description=("PERTE/BRIS déclarés pour un WCT exact, sources signées et historique fixe des quatre "
                         "statuts de variance publiés. Date/unité des pertes inconnues ; aucune cause attribuée, "
                         "aucun stock courant/réapprovisionnement/coût ; admin DEVICE active, aucune écriture."),
            parametres={"type": "object", "properties": {
                "wct_id": {"type": "string", "maxLength": 256},
                "decalage": {"type": "integer", "minimum": 0, "maximum": 10000},
                "limite": {"type": "integer", "minimum": 1, "maximum": 8}},
                "required": ["wct_id", "decalage", "limite"], "additionalProperties": False},
            fonction=lire_pertes_alertes_wct_appareil, autonomie=Autonomie.T0, roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m6_lire_reapprovisionnement_appareil",
            description=("État courant des articles déjà constatés M6, paramètres de réapprovisionnement et "
                         "références du dernier constat. Stock théorique/disponible, unité non confirmée ; "
                         "DEVICE admin active, page courante, aucune commande ni écriture."),
            parametres={"type": "object", "properties": {
                "decalage": {"type": "integer", "minimum": 0, "maximum": 10000},
                "limite": {"type": "integer", "minimum": 1, "maximum": 8}},
                "required": ["decalage", "limite"], "additionalProperties": False},
            fonction=lire_reapprovisionnement_appareil, autonomie=Autonomie.T0, roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m6_lire_contexte_materiaux_appareil",
            description=("Lit le contexte et le prévu réel du WCT choisi, sans coût ni quantité réellement utilisée, "
                         "après admission de la personne."),
            parametres={
                "type": "object",
                "properties": {
                    "intervention_id": {"type": "string", "minLength": 1, "maxLength": 256},
                    "wct_id": {"type": "string", "minLength": 1, "maxLength": 256},
                    "decalage": {"type": "integer", "minimum": 0, "maximum": 10000},
                    "limite": {"type": "integer", "minimum": 1, "maximum": 8},
                },
                "required": ["intervention_id", "wct_id", "decalage", "limite"],
                "additionalProperties": False,
            },
            fonction=lire_contexte_materiaux_appareil,
            autonomie=Autonomie.T0,
            roles_appareil=frozenset({"employee", "admin"}),
        ),
        Outil(
            nom="m6_declarer_materiaux_avec_preuves_appareil",
            description=("Déclaration DEVICE atomique avec notes de pertes/bris et références CAS vérifiées ; "
                         "aucun achat terrain."),
            parametres={
                "type": "object",
                "properties": {
                    "wct_id": {"type": "string", "minLength": 1, "maxLength": 256},
                    "formulaire": {**_FORMULAIRE_MATERIAUX_UTILISES, "additionalProperties": False,
                    "properties": {**_FORMULAIRE_MATERIAUX_UTILISES["properties"],
                        "lignes_materiaux": {"type": "array", "minItems": 1, "maxItems": 24,
                            "items": _LIGNE_DECLAREE_CHANTIER}}},
                    "preuves_lignes": {
                        "type": "array",
                        "maxItems": 8,
                        "items": {
                            "type": "object",
                            "properties": {
                                "position_ligne": {"type": "integer", "minimum": 0, "maximum": 23},
                                "note": {"type": "string", "minLength": 1, "maxLength": 500},
                                "photos": {"type": "array", "maxItems": 3, "items": {"type": "string"}},
                            },
                            "required": ["position_ligne", "note", "photos"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["wct_id", "formulaire", "preuves_lignes"],
                "additionalProperties": False,
            },
            fonction=declarer_materiaux_avec_preuves_appareil,
            autonomie=Autonomie.T1,
            niveau=Niveau.N3,
            roles_appareil=frozenset({"employee", "admin"}),
        ),
        Outil(
            nom="m6_lire_preuves_pertes_wct_appareil",
            description=("Lecture admin des notes/photo associées aux vrais mouvements PERTE/BRIS ; "
                         "pages courantes sans coûts."),
            parametres={
                "type": "object",
                "properties": {
                    "wct_id": {"type": "string", "minLength": 1, "maxLength": 256},
                    "decalage": {"type": "integer", "minimum": 0, "maximum": 10000},
                    "limite": {"type": "integer", "minimum": 1, "maximum": 8},
                },
                "required": ["wct_id", "decalage", "limite"],
                "additionalProperties": False,
            },
            fonction=lire_preuves_pertes_wct_appareil,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m6_lister_variances_classables_wct_appareil",
            description=("Lecture admin DEVICE des seules lignes terminales critiques ou liées à PERTE/BRIS, "
                         "sans inférence de cause."),
            parametres={
                "type": "object",
                "properties": {
                    "wct_id": {"type": "string", "maxLength": 256},
                    **_PAGE_CLASSEMENT,
                },
                "required": ["wct_id", "decalage", "limite"],
                "additionalProperties": False,
            },
            fonction=lister_variances_classables_wct_appareil,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m6_classer_cause_variance_appareil",
            description=("Annotation interne admin DEVICE, six causes humaines explicites et révision append-only; "
                         "aucun effet stock/coût/M4/M10."),
            parametres={
                "type": "object",
                "properties": {
                    "selection": _SELECTION_VARIANCE,
                    "cause": {
                        "type": "string",
                        "enum": sorted(contrats.CAUSES_VARIANCE_CHANTIER),
                    },
                    "motif": {"type": "string", "minLength": 1, "maxLength": 500},
                    "classement_attendu": {
                        **_REFERENCE_CLASSEMENT,
                        "type": ["object", "null"],
                    },
                    "references_pieces": {
                        "type": "array",
                        "maxItems": 8,
                        "items": {
                            "type": "object",
                            "properties": {
                                "reference_mouvement": _REFERENCE_PIECE,
                                "reference_preuve": _REFERENCE_PREUVE_CLASSEMENT,
                                "positions_photos": {
                                    "type": "array",
                                    "maxItems": 3,
                                    "items": {
                                        "type": "integer",
                                        "minimum": 0,
                                        "maximum": 2,
                                    },
                                },
                            },
                            "required": [
                                "reference_mouvement",
                                "reference_preuve",
                                "positions_photos",
                            ],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": [
                    "selection",
                    "cause",
                    "motif",
                    "classement_attendu",
                    "references_pieces",
                ],
                "additionalProperties": False,
            },
            fonction=classer_cause_variance_appareil,
            autonomie=Autonomie.T1,
            niveau=Niveau.N3,
            roles_appareil=frozenset({"admin"}),
            portee_contexte="affaire",
            cible_contexte=("selection", "wct_id"),
            identite_contexte="wct",
        ),
        Outil(
            nom="m6_lire_historique_classement_variance_appareil",
            description=("Historique admin DEVICE des révisions humaines de cette sélection exacte; "
                         "lectures sans effet."),
            parametres={
                "type": "object",
                "properties": {"selection": _SELECTION_VARIANCE, **_PAGE_CLASSEMENT},
                "required": ["selection", "decalage", "limite"],
                "additionalProperties": False,
            },
            fonction=lire_historique_classement_variance_appareil,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
            roles_appareil=frozenset({"admin"}),
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
    intervention_id, devis_id, horodatage_completion et empreinte du contenu complet —
    `wct_recus.py`). Une répétition du même wct_id et du même contenu est idempotente ; un contenu
    différent retourne `CONFLIT-WCT-CONTENU` et ne touche ni projection ni événement. Puis délègue
    tout le calcul et la publication à `_evaluer_et_publier_variance` (fonction
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
    empreinte_contenu = encodage.empreinte(charge)
    if wct_recu is not None:
        if wct_recu.get("empreinte_contenu") != empreinte_contenu:
            return {
                "statut_variance": "conflit",
                "wct_id": charge["wct_id"],
                "code": "CONFLIT-WCT-CONTENU",
            }
        return _evaluer_et_publier_variance(wct_recu)

    wct_recu = wct_recus.construire(
        charge["wct_id"], charge["intervention_id"], charge.get("devis_id"),
        charge["horodatage_completion"], empreinte_contenu,
    )
    wct_recus_registre.append(wct_recu)
    return _evaluer_et_publier_variance(wct_recu)


def _recevoir_devis_accepte(charge: dict[str, Any]) -> dict[str, Any]:
    """Consomme `m3.devis_accepte` (T1.2-d, « le prévu vient du devis accepté par le bus, plus
    d'un appel manuel ») : les lignes dont `reference_besoin_materiau` n'est PAS nul deviennent
    le prévu — materiau_id = cette référence, quantité et unité portées telles quelles, JAMAIS un
    montant (`prix_unitaire`/`prix_ligne` existent sur la ligne mais M6 planifie des quantités de
    matériaux, pas des prix — même séparation coût/prix que le catalogue documente déjà pour
    `cout_total`/`prix_total`). `quantite` du catalogue est un texte décimal (frontière M3,
    comme `m6.variance_chantier` l'est en sortie) : converti en `float` ICI, à l'entrée, pour
    rejoindre `validation.valider_besoins_estimes_chantier`/`variance_chantier.evaluer`, qui
    n'acceptent qu'un nombre — esprit inverse de `_texte_decimal`.

    Passe par LA MÊME LOGIQUE que l'outil manuel `m6_enregistrer_besoins_prevus` : cette fonction
    EST `enregistrer_besoins_prevus`, appelée avec les lignes dérivées du devis plutôt que
    fournies par un appelant humain — idempotent par devis_id, et le prévu tardif (un WCT déjà
    reçu pour ce devis_id) y est réévalué exactement de la même façon, aucune logique dupliquée.

    `chantier_id` du devis PEUT être `None` (M3 accepte un devis avant que M4 planifie le
    chantier) : jamais deviné ici — `besoins_prevus.enregistrer` l'accepte tel quel (T1.2-d) et
    `_evaluer_et_publier_variance` le résout plus tard depuis la déclaration au besoin.

    Un devis accepté SANS AUCUNE ligne reliée à un besoin matériau (`reference_besoin_materiau`
    nul partout) donne `lignes == []` : un PRÉVU VIDE CONNU (besoins_prevus.py), pas une absence
    — le chantier reste évaluable normalement (tout matériau déclaré devient NON_PREVU,
    `variance_chantier.evaluer`), jamais bloqué en revue faute de prévu.
    """
    lignes = [
        {
            "materiau_id": ligne["reference_besoin_materiau"],
            "quantite_estimee": float(ligne["quantite"]),
            "unite": ligne["unite"],
        }
        for ligne in charge["lignes"]
        if ligne.get("reference_besoin_materiau") is not None
    ]
    reponse = enregistrer_besoins_prevus(charge["chantier_id"], charge["devis_id"], lignes)
    # T4.14 : le prévu est le devis ACCEPTÉ : M6 réserve ce qui est disponible et dit à M4 si le matériel est prêt,
    # partiel ou à commander (`m6.materiel_pret`), dans la MÊME transaction. Même quand le prévu était déjà rangé
    # (par l'outil manuel, ou un rejeu) : la réservation est idempotente par devis, et jamais refaite après une
    # libération. Un prévu vide ne réserve rien et ne dit rien. Jamais de bon de commande.
    if stockage.connexion_courante() is not None:
        reponse["reservation"] = _reserver_pour_devis(
            charge["devis_id"], charge["horodatage_acceptation"], "devis_accepte"
        )
    return reponse


def _recevoir_besoins_materiaux(charge: dict[str, Any]) -> dict[str, Any]:
    """Consomme `m3.besoins_materiaux` (PLAN T2.3-e) : les besoins d'une ESTIMATION, avant le devis.

    Validation du récepteur, indépendante de celle de M3 (`besoins_materiaux_recus.valider`, en plus
    du schéma du catalogue) : un contrat invalide LÈVE `ValueError` — le répartiteur réessaie puis le
    met en QUARANTAINE, visible d'un humain (`opsys-metier evenements etat`), sans qu'aucune écriture n'ait
    eu lieu. Un rejet retourné comme résultat serait « traité » : la faute passerait pour un succès.

    Un contrat valide est rangé dans le registre des besoins prévus EXISTANT (`besoins_prevus.py`,
    source `estimation_m3` : prévu provisoire du devis, jamais un second registre) — celui que
    `m6_declarer_materiaux_utilises` et l'évaluation de variance lisent déjà, et que le prévu définitif
    du devis accepté (`_recevoir_devis_accepte`) remplace sans jamais être refusé par lui. Idempotent
    par (`devis_id`, `estimation_id`) ; une version d'estimation périmée arrivée en retard est
    ignorée (`besoins_prevus.enregistrer_estimation`).

    Ne crée JAMAIS de bon de commande, ne réserve rien, ne touche à aucun stock : recevoir un besoin
    n'est pas acheter. Un PO reste un brouillon calculé à la demande (`m6_creer_po_brouillon`), soumis à
    approbation (T2.5) — et il exige un `chantier_id`, que le prévu provisoire n'a pas.

    Dans la transaction du répartiteur seulement : le registre durable fait autorité (comme
    `_recevoir_travaux_termines`), jamais l'historique en mémoire d'un appel direct — une écriture
    perdue en silence serait pire qu'une panne."""
    ok, code = besoins_materiaux_recus.valider(charge)
    if not ok:
        raise ValueError(f"m3.besoins_materiaux refusé ({code}) : contrat invalide, aucune écriture")
    maillons = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_BESOINS_PREVUS)
    maillon, statut = besoins_prevus.enregistrer_estimation(charge, maillons)
    resultat: dict[str, Any] = {
        "traite": True,
        "statut": statut,
        "devis_id": charge["devis_id"],
        "estimation_id": charge["estimation_id"],
    }
    if maillon is None:
        return resultat
    maillons.append(maillon)
    courant = besoins_prevus.pour_devis(charge["devis_id"], maillons)
    definitif_existe = courant is not None and courant.get("estimation_id") != charge["estimation_id"]
    resultat["lignes_enregistrees"] = len(maillon["lignes"])
    resultat["lignes_sans_sku"] = [
        ligne["materiau"] for ligne in maillon["detail_lignes"] if "sku" not in ligne
    ]
    resultat["facteurs_perte_absents"] = list(maillon["facteurs_perte_absents"])
    resultat["prevu_definitif_existant"] = definitif_existe
    if not definitif_existe:
        # Cette version EST maintenant le prévu du devis : si son WCT est déjà reçu, il se
        # réévalue — même règle que pour un prévu manuel ou un devis accepté tardif (T1.2-d).
        _reevaluer_si_wct_connu_par_devis_id(charge["devis_id"])
    return resultat


def consommateurs() -> dict[str, Callable[[dict], dict]]:
    return {
        "m4.travaux_termines": _recevoir_travaux_termines,
        "m3.devis_accepte": _recevoir_devis_accepte,
        "m3.besoins_materiaux": _recevoir_besoins_materiaux,
    }


# ---------------------------------------------------------------------------------------------
# Attentes de l'admin (ADR-0009 §5, PLAN T1.5-d)
# ---------------------------------------------------------------------------------------------
# Même mécanisme de découverte que `consommateurs()` (`opsys.departements.Departement.charger_attentes`) :
# fonction module-level, sans argument, appelée par `approbations.file_proprietaire` et par
# `m9_lister_demandes_approbation` (section « À voir » de l'app admin) DANS une transaction déjà ouverte.
def attentes() -> list[dict[str, Any]]:
    """Le stock bas et les seuils à configurer, tels qu'ils sont AUJOURD'HUI (`reapprovisionnement.attentes`) :
    une attente `besoin_commande` par article constaté dont le stock est encore sous le seuil, et une seule
    attente `seuil_a_configurer` pour les articles sans paramètres utilisables. Lecture seule : ne crée ni
    bon de commande, ni mouvement, ni constat. Sans constat au registre, aucune attente."""
    return reapprovisionnement.attentes(
        stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_BESOINS_COMMANDE),
        stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE),
        _articles_reapprovisionnement(),
        reserves=reservations.reserve_par_article(stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_RESERVATIONS)),
        hors_main=emplacements.hors_main_par_article(stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_EMPLACEMENTS)),
    )
