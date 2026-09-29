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
n'est jamais autonome, quel que soit le mode du département. Lecture et calcul purs
(état, taxes) sont T0. Créer une facture BROUILLON (M5.2, `m5_creer_facture_brouillon`)
est une écriture interne non finale sur un registre dédié — elle n'envoie rien au
client et n'engage aucun argent (le registre des MOUVEMENTS n'est jamais touché) —
donc T1, jamais T3 à ce stade.

PLAN T1.3-c (branchement sur les approbations du socle, ADR-0009 §4/§5) : les DEUX
transitions qui engagent sont maintenant des outils agent, gardés par le socle et
JAMAIS par la forme d'une donnée passée en argument :
- `m5_envoyer_facture` (BROUILLON -> ENVOYEE) est T2/N4 — le même niveau que F4/F5
  dans l'ancienne échelle interne (`NIVEAU_POUR_PALIER`, plus bas). `finance` ou
  `nathan_owner` (`department.yaml/approbations.n4`) décide dans la console/CLI
  OPSYS ; `opsys.capacites.Capacites._distribuer` intercepte tout appel direct en
  `en_attente_approbation` avant que `facturation.envoyer_facture` ne s'exécute.
- `m5_enregistrer_paiement_facture` (ENVOYEE -> PAYEE) est T3/N5 — le même niveau
  que F6/F7 : `nathan_owner` ET l'attestation du professionnel (ADR-0009 §5), jamais
  automatique, jamais vérifiées ici mais par `opsys.approbations.decider` seul. Le
  montant réellement déposé est comparé par le CODE au montant dû
  (`facturation.enregistrer_paiement_facture`) : un paiement partiel ou un écart est
  un verdict nommé, jamais une facture marquée PAYEE sans contrôle.

L'ancien registre interne F0-F7 (`approbation.py`) n'est plus routé par aucun outil
agent : il reste dans le dépôt comme bibliothèque pure, testée, mais vestigiale (voir
le rapport de PLAN T1.3-c) — toute future action F0-F7 de M5 doit obtenir son PROPRE
outil, au N mappé par `NIVEAU_POUR_PALIER`, plutôt que de rejoindre un registre de
gouvernance parallèle au socle.

Registre des FACTURES (M5.2, `facturation.py`) : troisième registre du département, sur
exactement le même patron d'adaptateur que celui des mouvements (`_registre_factures`/
`_etat_factures` ci-dessous, symétriques à `_registre_mouvements`/`_etat_mouvements`) — durable
dès que `_stockage_durable_actif` l'est (même bascule que les mouvements), jamais ouvert au
chargement, relu à chaque appel, `stockage.maillons("m05-financecore", "factures")` en
production. Le registre des MOUVEMENTS reste strictement celui déjà en place : aucune fonction
de ce fichier n'écrit un ENCAISSEMENT à partir d'une facture.

Consommateurs d'événements (ADR-0009 §3, PLAN T1.2-d, suite ; T1.3-c point 4) : `consommateurs()`
abonne `_recevoir_devis_accepte` (`m3.devis_accepte`) et `_recevoir_travaux_termines`
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
tient pas debout. `consommateurs()` abonne en plus `_recevoir_variance_chantier`
(`m6.variance_chantier`, catalogue existant, M6 en est propriétaire) sur `variance_recus.py` :
M5 GARDE le signal (le dernier connu par `wct_id`, jamais un verrou) pour l'afficher à côté
d'une facture BROUILLON dans `attentes()`, sans jamais bloquer son envoi (M6 « signale
seulement »). Ce module reste le seul point du département qui connaît `opsys.evenements`,
comme il est déjà le seul à connaître `opsys.stockage` — `facturation.py` n'importe ni l'un ni
l'autre (DA-M5-04).

PLAN T2.2 (Client 360 de M2) : `consommateurs()` abonne en plus `_recevoir_client_associe`
(`m2.client_associe`, catalogue M2) sur `clients_recus.py` (même patron que les autres registres
« reçus »). `_essayer_facture_brouillon` facture avec le VRAI `client_id` du Client 360 quand il
est connu, sinon reprend le repli historique (`client_id = lead_id`, une donnée réelle, jamais
inventée) — JAMAIS bloquant : `m2.client_associe` est publié à l'ingestion du lead, bien avant
qu'un devis ou une complétion puisse exister pour lui, donc ce repli ne devrait normalement jamais
s'activer en usage réel ; il reste le filet pour un ordre d'arrivée inhabituel. Aucune facture
déjà créée n'est corrigée rétroactivement si `m2.client_associe` arrive après coup (immuabilité
des écritures, même principe que `variance_recus.py` : le signal est gardé pour l'AVENIR, jamais
appliqué au passé).

PLAN T1.4-k2 (identité authentifiée, `acces.py`, docs/architecture/ROLES.md) : pour un appel
d'appareil, `m5_etat_tresorerie` ne croit plus `role` ni `autorise_couts` — la vue vient du rôle de la
personne authentifiée, confirmée en base à chaque appel (`_acteur_appareil`) ; un argument ne peut que
restreindre. `m5_lister_attentes_facturation` exige la même identité confirmée. Sans identité d'appareil
(agent, console), comportement d'avant, sans contrôle de personne (« voie des agents »).

PLAN T1.5-d (coût réel et rentabilité, DEFINITION-PRODUIT §6 « travaux terminés », `cout_reel.py`,
DA-M5-10) : les consommateurs qui apportent une pièce (devis accepté, WCT, variance M6) appellent
`_essayer_cout_reel`, qui calcule le coût réel du chantier et sa rentabilité depuis des pièces LUES À LA SOURCE
(`_etat_chantier`) et les trace dans un cinquième registre durable, DÉRIVÉ (`rentabilite`, une trace par version
des entrées) : ni le grand livre, ni le registre des factures, ni les comptes à recevoir (une vue de ces
factures) ne sont écrits. Le livre de prix de M6 est lu en lecture seule (`_livre_de_prix_m6`) : le seul endroit du
département qui nomme un autre département. `m5_lire_rentabilite_chantier` et `m5_lire_comptes_a_recevoir` (T0,
`admin` seulement, même contrôle d'identité et de droit de voir les coûts que `m5_etat_tresorerie`) les rendent
à l'admin ; aucun montant, prix, taux, durée ni quantité ne se passe en argument.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import yaml

from opsys import approbations, contexte, stockage
from opsys.outils import Autonomie, Niveau, Outil, depuis_couple

from . import (
    acces,
    clients_recus,
    cout_reel,
    devis_recus,
    etat_financier,
    facturation,
    taux_fiscaux,
    taxes,
    validation,
    variance_recus,
    wct_recus,
)
from . import registre as registre_module

_CHEMIN_TAUX_FISCAUX = Path(__file__).resolve().parents[2] / "contracts" / "taux_fiscaux.v1.yaml"

_DEPARTEMENT = "m05-financecore"
_NOM_REGISTRE_MOUVEMENTS = "principal"
_NOM_REGISTRE_FACTURES = "factures"
_NOM_REGISTRE_DEVIS_RECUS = "devis_recus"
_NOM_REGISTRE_WCT_RECUS = "wct_recus"
_NOM_REGISTRE_VARIANCE_RECUE = "variance_recue"
_NOM_REGISTRE_CLIENTS_RECUS = "clients_recus"
_NOM_REGISTRE_RENTABILITE = "rentabilite"
# PLAN T1.5-d : le livre de prix de M6, lu en LECTURE SEULE à la source (le prix de chaque matériau utilisé
# ne vient ni de l'appelant ni d'un événement). Le seul endroit du département qui nomme un autre département
# ; il n'importe aucun de ses modules (DA-M5-04) et ne fait qu'itérer ses maillons, jamais `append`.
_DEPARTEMENT_LIVRE_DE_PRIX = "m06-material-control"
_NOM_REGISTRE_LIVRE_DE_PRIX = "livre_prix"
# `department.yaml/configuration.taux_horaire_main_d_oeuvre` : même source de configuration que M6
# (`seuil_variance_chantier_pourcentage`). ABSENT du manifeste livré : c'est un chiffre de l'entreprise, que
# M5 ne devine pas (le coût réel dit alors « taux horaire à configurer »).
_MANIFESTE = Path(__file__).resolve().parents[2] / "department.yaml"

# Correspondance F -> N (ADR-0009 §4), établie en UN SEUL endroit pour M5 (PLAN T1.3-c point 3) :
# F0-F2 automatique (N0-N2, le choix exact ne change aucun comportement d'approbation, même
# raisonnement que `opsys.outils.niveau_par_defaut`), F3 -> N3, F4/F5 -> N4 (engagement client),
# F6/F7 -> N5 (argent réel, jamais automatique). Les deux paliers F que M5 réalise concrètement
# aujourd'hui — l'envoi d'une facture (F4) et le paiement constaté (F6) — obtiennent chacun leur
# PROPRE outil, posé explicitement au N mappé ici (`niveau=`, plus bas) : il n'existe plus de
# demande F « libre » routée par un registre interne concurrent (voir `approbation.py`, retiré des
# outils exposés à l'agent ; rapport final de PLAN T1.3-c pour ce qui en reste).
NIVEAU_POUR_PALIER: dict[str, Niveau] = {
    "F0": Niveau.N0, "F1": Niveau.N1, "F2": Niveau.N2,
    "F3": Niveau.N3,
    "F4": Niveau.N4, "F5": Niveau.N4,
    "F6": Niveau.N5, "F7": Niveau.N5,
}
NIVEAU_ENVOI_FACTURE = NIVEAU_POUR_PALIER["F4"]  # engagement client (envoi), ADR-0009 §4
NIVEAU_PAIEMENT_FACTURE = NIVEAU_POUR_PALIER["F6"]  # argent réel constaté, ADR-0009 §4

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


# Portée des rôles d'appareil sur les deux outils de lecture financière : la source UNIQUE, reprise
# par `Outil.roles_appareil` (plus bas) et par le contrôle de `_acteur_appareil`. §9.5 (M5, trésorerie et
# factures à approuver) : l'admin seul ; ni l'employé (§9.2) ni le vendeur (§9.4) ne voient les finances.
_ROLES_APPAREIL_FINANCE = frozenset({acces.ROLE_ADMIN})

# Les deux arguments de vue des outils de lecture financière ajoutés en T1.5-d (mêmes règles que ceux de
# `m5_etat_tresorerie`, T1.4-k2 : un argument ne peut que restreindre la vue).
_LIMITE_LECTURE_DEFAUT = 8
_LIMITE_LECTURE_MAX = 12
_ROLE_DE_LECTURE = {
    "type": ["string", "null"],
    "description": (
        "Appel d'appareil : omis, ou égal au rôle authentifié (sinon REJ-IDENTITE-FOURNIE-DIFFERENTE)."
    ),
}
_AUTORISE_COUTS_DE_LECTURE = {
    "type": ["boolean", "null"],
    "description": (
        "Appel d'appareil : omis, il vaut le droit du rôle ; faux restreint (aucun montant) ; vrai sans ce "
        "droit est refusé (REJ-ROLE-ELARGI). Sans appareil (agent, console) : obligatoire et explicite."
    ),
}


def _acteur_appareil() -> tuple[acces.Acteur | None, dict[str, Any] | None]:
    """Qui appelle : ``(None, None)`` hors appel d'appareil, ``(acteur, None)`` si l'identité du jeton
    est CONFIRMÉE en base et dans la portée de l'outil, ``(None, verdict)`` sinon (PLAN T1.4-k2).

    ``contexte.identite_appelante()`` ne rend que ce que le core a transmis en `_meta` : la personne
    a pu être désactivée, ou perdre le rôle, depuis l'émission du jeton (le fragment de
    configuration du core n'est régénéré qu'à la demande). On la revérifie donc à chaque appel avec
    la même fonction que la validation humaine au départ (``approbations.signataire_valide``, T1.4-h :
    personne active portant encore ce rôle), au lieu d'une seconde règle qui pourrait diverger.
    Hors transaction (aucune base jointe), rien n'est vérifiable : refus fermé, jamais une identité
    crue sur parole. Ne lit JAMAIS les arguments de l'outil, n'écrit rien."""
    appelante = contexte.identite_appelante()
    if appelante is None:
        return None, None
    cnx = stockage.connexion_courante()
    confirmee = approbations.signataire_valide(cnx, appelante) if cnx is not None else None
    if confirmee is None:
        return None, validation.construire_verdict(
            "REJ-IDENTITE-APPAREIL-INVALIDE",
            detail=(
                f"personne {appelante.personne!r} inconnue, inactive, ou ne porte plus le rôle "
                f"{appelante.role!r} porté par le jeton d'appareil (ou identité non vérifiable "
                "hors transaction)"
            ),
        )
    return acces.acteur_de(confirmee.personne, confirmee.role, _ROLES_APPAREIL_FINANCE)


def _refus(verdict: dict[str, Any]) -> dict[str, Any]:
    return {"accepte": False, "verdict": verdict}


def etat_tresorerie(
    role: str | None = None,
    autorise_couts: bool | None = None,
    mouvements_historique: list[dict[str, Any]] | None = None,
    taux_utilises: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Composé de bout en bout : obtient le registre des mouvements (§`_registre_mouvements`),
    calcule solde + argent disponible réel, filtre par rôle.

    Pour un appel d'appareil (PLAN T1.4-k2), la vue vient du rôle authentifié et CONFIRMÉ en base
    (`_acteur_appareil`, `acces.resoudre_vue`) : `autorise_couts` est dérivé du rôle, un argument
    ne peut que la restreindre, `role` ne peut pas contredire le jeton. Un refus est un verdict nommé
    (`{"accepte": False, "verdict": ...}`), rendu AVANT de lire le registre ; la réponse d'un accord
    garde sa forme d'avant.

    Sans identité d'appareil (agent, console) : `autorise_couts` reste OBLIGATOIRE et explicite
    (fail-closed, absent = `REJ-AUTORISE-COUTS-REQUIS`) : aucune valeur par défaut n'expose jamais une
    donnée financière."""
    acteur, refus = _acteur_appareil()
    if refus is not None:
        return _refus(refus)
    vue, verdict = acces.resoudre_vue(acteur, role, autorise_couts)
    if verdict is not None:
        return _refus(verdict)
    registre_cible = _registre_mouvements(mouvements_historique)
    return etat_financier.construire_etat_financier(
        registre_cible, taux_utilises or [], role=vue["role"], autorise_couts=vue["autorise_couts"]
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

    # PLAN T2.2 (Client 360 de M2) : client_id RÉEL si M5 a déjà reçu m2.client_associe pour ce
    # lead (clients_recus.py) ; sinon repli sur lead_id, EXACTEMENT le comportement historique
    # d'avant ce correctif — jamais bloquant (voir docstring du module) et jamais une valeur
    # inventée (lead_id est une donnée réelle, portée telle quelle depuis M3/M2).
    client_recu = clients_recus.pour_lead_id(
        devis_recu["lead_id"], stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_CLIENTS_RECUS)
    )
    client_id = client_recu["client_id"] if client_recu is not None else devis_recu["lead_id"]

    resultat, verdict = facturation.creer_facture_brouillon(
        facture_id=f"fac-{devis_id}",
        chantier_id=chantier_id,
        devis_id=devis_id,
        client_id=client_id,
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


def _taux_horaire_configure() -> Any:
    """`department.yaml/configuration.taux_horaire_main_d_oeuvre` tel que l'entreprise l'a écrit, ou `None`.

    Relu à chaque appel (comme M6 pour ses seuils) : Nathan change le taux sans redémarrer. Un manifeste
    illisible ou sans ce champ rend `None` : `cout_reel.valider_taux_horaire` en fait le verdict « taux
    horaire à configurer », jamais un taux par défaut. La valeur brute est rendue (validée plus loin)."""
    try:
        donnees = yaml.safe_load(_MANIFESTE.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    configuration = donnees.get("configuration") if isinstance(donnees, dict) else None
    return configuration.get("taux_horaire_main_d_oeuvre") if isinstance(configuration, dict) else None


def _livre_de_prix_m6() -> tuple[dict[str, Any], ...]:
    """Les entrées du livre de prix de M6, en LECTURE SEULE (copie ; aucun `append`, aucune écriture)."""
    maillons = stockage.maillons(_DEPARTEMENT_LIVRE_DE_PRIX, _NOM_REGISTRE_LIVRE_DE_PRIX)
    return tuple(dict(entree) for entree in maillons if isinstance(entree, Mapping))


def _sources_cout_reel() -> dict[str, Any]:
    """Lit UNE fois chaque source du coût réel (PLAN T1.5-d) : les registres reçus (devis, WCT, variance), la
    facture ACTIVE de chaque devis, le livre de prix de M6, le taux horaire configuré et le dernier état tracé de
    chaque devis. Lire une fois (et non à chaque devis) garde une liste de chantiers linéaire, pas quadratique."""
    traces: dict[str, dict[str, Any]] = {}
    for maillon in stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_RENTABILITE):
        traces[maillon.get("devis_id")] = maillon  # le dernier écrit fait foi
    return {
        "devis": list(stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_DEVIS_RECUS)),
        "wct": list(stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_WCT_RECUS)),
        "variance": list(stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_VARIANCE_RECUE)),
        "factures": facturation.factures_actives_par_devis(_registre_factures(None)),
        "livre": _livre_de_prix_m6(),
        "taux": _taux_horaire_configure(),
        "traces": traces,
    }


def _etat_chantier(devis_id: str, sources: dict[str, Any] | None = None) -> dict[str, Any]:
    """L'état de coût réel et de rentabilité d'un devis, CALCULÉ à l'instant depuis les pièces lues à la
    source (PLAN T1.5-d) : le devis accepté et le WCT reçus du bus, le dernier signal de variance de M6,
    la facture active du devis, le livre de prix de M6 et le taux horaire configuré. N'écrit RIEN.

    Fonction UNIQUE, partagée par la cascade (`_essayer_cout_reel`, qui trace) et par l'outil de lecture (qui
    ne trace pas) : les deux ne peuvent pas diverger. Sans devis reçu ou sans WCT reçu, il n'y a rien à
    calculer : un statut d'attente nommé (mêmes noms que `lister_attentes_facturation`), jamais une valeur."""
    sources = _sources_cout_reel() if sources is None else sources
    devis_recu = devis_recus.pour_devis_id(devis_id, sources["devis"])
    if devis_recu is None:
        return {"statut": "en_attente_devis_accepte", "devis_id": devis_id, "chantier_id": None}
    chantier_devis = devis_recu.get("chantier_id")
    wct_recu = wct_recus.pour_devis_id(devis_id, sources["wct"])
    if wct_recu is None:
        return {
            "statut": "en_attente_travaux_termines", "devis_id": devis_id,
            "chantier_id": chantier_devis or None,
        }
    autres_wct = {m.get("wct_id") for m in sources["wct"]
                  if m.get("devis_id") == devis_id and m.get("wct_id") not in (None, wct_recu["wct_id"])}
    signal = variance_recus.signal_retenu_pour_wct_id(wct_recu["wct_id"], sources["variance"])
    cout = cout_reel.calculer_cout_reel(wct_recu, signal, sources["livre"], sources["taux"], autres_wct)
    chantier_id = chantier_devis or (signal.get("chantier_id") if signal is not None else None) or None
    rentabilite = cout_reel.calculer_rentabilite(
        cout, sources["factures"].get(devis_id), devis_recu, devis_id=devis_id, chantier_id=chantier_id
    )
    return {
        "statut": "calculee", "devis_id": devis_id, "chantier_id": chantier_id, "rentabilite": rentabilite,
        "horodatage": wct_recu["horodatage_completion"],
    }


def _essayer_cout_reel(devis_id: str) -> dict[str, Any]:
    """Étape de la cascade « travaux terminés » (DEFINITION-PRODUIT §6, M5 « calcule le coût réel [...] et la
    rentabilité du chantier ») : calcule l'état de ce devis et le TRACE dans le registre `rentabilite`.

    Appelée par les consommateurs qui apportent une pièce (devis accepté, WCT, variance M6), dans la
    transaction du répartiteur, quel que soit l'ordre d'arrivée : la dernière pièce à arriver produit l'état
    complet. Écrit UNIQUEMENT dans le registre dérivé `rentabilite` (append-only) : ni le grand livre, ni le
    registre des factures, ni les comptes à recevoir (une vue). Idempotente par devis ET version des entrées :
    un rejeu, ou une pièce qui ne change aucune entrée du calcul, n'ajoute aucun maillon ; une entrée qui change
    (prix du livre, taux, facture envoyée...) en ajoute un, l'historique restant intact.

    Ne lève pas sur une pièce mal formée (elle devient un manque du coût, voir `cout_reel.py`) : la création de
    la facture, faite dans la même transaction, ne dépend jamais de ce calcul."""
    sources = _sources_cout_reel()
    etat = _etat_chantier(devis_id, sources)
    if etat["statut"] != "calculee":
        return {"statut": etat["statut"]}
    rentabilite = etat["rentabilite"]
    trace = sources["traces"].get(devis_id)
    if trace is not None and trace.get("version_entrees") == rentabilite["version_entrees"]:
        return {"statut": "deja_tracee"}
    stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_RENTABILITE).append(
        cout_reel.construire_trace(rentabilite, etat["horodatage"])
    )
    return {"statut": "tracee"}


def _essayer_cout_reel_pour_wct(wct_id: str) -> dict[str, Any]:
    """Comme `_essayer_cout_reel`, depuis un `wct_id` (le signal de variance ne connaît que lui) : le WCT
    reçu donne le `devis_id`. WCT inconnu ou sans devis : un statut d'attente nommé, rien n'est tracé."""
    wct_recu = wct_recus.pour_wct_id(wct_id, stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_WCT_RECUS))
    if wct_recu is None:
        return {"statut": "en_attente_travaux_termines"}
    if wct_recu["devis_id"] is None:
        return {"statut": "wct_sans_devis_id"}
    return _essayer_cout_reel(wct_recu["devis_id"])


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
                cout_total=charge.get("cout_total"),
                taux_marge=charge.get("taux_marge"),
            )
        )
    resultat = _essayer_facture_brouillon(devis_id)
    return {**resultat, "cout_reel": _essayer_cout_reel(devis_id)["statut"]}


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
            duree_reelle_minutes=charge.get("duree_reelle_minutes"),
        )
        registre.append(wct_recu)
    if wct_recu["devis_id"] is None:
        return {"traite": True, "wct_id": wct_id, "statut": "wct_sans_devis_id"}
    resultat = _essayer_facture_brouillon(wct_recu["devis_id"])
    return {**resultat, "cout_reel": _essayer_cout_reel(wct_recu["devis_id"])["statut"]}


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


def lister_attentes_facturation_appareil() -> dict[str, Any]:
    """L'outil `m5_lister_attentes_facturation` : la même liste, précédée de l'identité (PLAN
    T1.4-k2). Un appel d'appareil doit venir d'une personne confirmée en base dans la portée de l'outil
    (admin) : une personne désactivée, ou qui a perdu le rôle depuis l'appairage, ne lit plus rien.
    Sans identité d'appareil (agent, console) : la liste, comme avant. `attentes()` (file du
    propriétaire) et les tests appellent `lister_attentes_facturation` directement, sans ce contrôle."""
    _acteur, refus = _acteur_appareil()
    if refus is not None:
        return _refus(refus)
    return lister_attentes_facturation()


def _recevoir_variance_chantier(charge: dict[str, Any]) -> dict[str, Any]:
    """Consomme `m6.variance_chantier` (PLAN T1.3-c point 4, catalogue existant, M6 en est
    propriétaire) : garde le DERNIER signal connu par wct_id (`variance_recus.py`) — jamais un
    verrou sur la facture (M6 « signale seulement »). `attentes()` l'affiche à côté d'une facture
    BROUILLON quand il est critique, sans jamais bloquer son envoi."""
    registre = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_VARIANCE_RECUE)
    registre.append(
        variance_recus.construire(
            wct_id=charge["wct_id"],
            chantier_id=charge["chantier_id"],
            statut_variance=charge["statut_variance"],
            signal_critique=charge["signal_critique"],
            horodatage_completion=charge["horodatage_completion"],
            lignes=charge.get("lignes"),
        )
    )
    return {
        "traite": True,
        "wct_id": charge["wct_id"],
        "statut_variance": charge["statut_variance"],
        "cout_reel": _essayer_cout_reel_pour_wct(charge["wct_id"])["statut"],
    }


def _recevoir_client_associe(charge: dict[str, Any]) -> dict[str, Any]:
    """Consomme `m2.client_associe` (PLAN T2.2, catalogue M2) : garde le lien lead_id -> client_id
    (`clients_recus.py`, idempotent par lead_id), pour que `_essayer_facture_brouillon` facture le
    VRAI client_id du Client 360 M2 dès qu'il est connu. N'essaie PAS de facturer ici : ce type
    d'événement arrive à l'ingestion du lead, bien avant qu'un devis_id soit même connaissable
    (voir docstring du module) — rien à tenter tant qu'aucun devis n'existe pour ce lead."""
    lead_id = charge["lead_id"]
    registre = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_CLIENTS_RECUS)
    if clients_recus.pour_lead_id(lead_id, registre) is None:
        registre.append(
            clients_recus.construire(
                lead_id=lead_id,
                client_id=charge["client_id"],
                horodatage_association=charge["horodatage_association"],
            )
        )
    return {"traite": True, "lead_id": lead_id, "client_id": charge["client_id"]}


def consommateurs() -> dict[str, Callable[[dict], dict]]:
    return {
        "m2.client_associe": _recevoir_client_associe,
        "m3.devis_accepte": _recevoir_devis_accepte,
        "m4.travaux_termines": _recevoir_travaux_termines,
        "m6.variance_chantier": _recevoir_variance_chantier,
    }


def envoyer_facture(
    facture_id: str,
    horodatage: str,
    factures_historique: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Outil N4 (PLAN T1.3-c) : n'est JAMAIS exécuté hors d'une décision approuvée du socle
    (`opsys.approbations.decider`, `department.yaml/approbations.n4`) — voir
    `facturation.envoyer_facture` et le docstring de ce module (RÈGLE FINANCE)."""
    registre_cible = _registre_factures(factures_historique)
    resultat, verdict = facturation.envoyer_facture(facture_id, horodatage, registre_cible)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return {"accepte": True, "resultat": resultat, **_etat_factures(factures_historique, registre_cible)}


def enregistrer_paiement_facture(
    facture_id: str,
    montant_paye: str,
    approbateur: str,
    horodatage: str,
    factures_historique: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Outil N5 (PLAN T1.3-c) : le socle exige `nathan_owner` ET l'attestation du professionnel
    (ADR-0009 §5) avant exécution — jamais vérifiées ici. Voir
    `facturation.enregistrer_paiement_facture` pour la comparaison de montant, calculée par le
    code, jamais fournie sans contrôle (paiement partiel ou écart -> verdict nommé)."""
    registre_cible = _registre_factures(factures_historique)
    resultat, verdict = facturation.enregistrer_paiement_facture(
        facture_id, montant_paye, approbateur, horodatage, registre_cible
    )
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return {"accepte": True, "resultat": resultat, **_etat_factures(factures_historique, registre_cible)}


def _factures_brouillon() -> tuple[dict[str, Any], ...]:
    return facturation.factures_par_statut(_registre_factures(None), "BROUILLON")


def _depuis_attente_devis(devis_id: str, statut: str, devis_registre: Any, wct_registre: Any) -> str:
    """Date de début d'attente d'un item `attentes_devis` (PLAN T1.3-c point 4) : celle de la
    pièce déjà connue (le WCT quand c'est le devis accepté qui manque encore, sinon le devis)."""
    if statut == "en_attente_devis_accepte":
        return wct_recus.pour_devis_id(devis_id, wct_registre)["horodatage_completion"]
    return devis_recus.pour_devis_id(devis_id, devis_registre)["horodatage_acceptation"]


def _variance_critique_pour_facture(
    facture: dict[str, Any], wct_registre: Any, variance_registre: Any
) -> dict[str, Any] | None:
    """Le signal de variance CRITIQUE de M6 (PLAN T1.3-c point 4) à afficher à côté de cette
    facture BROUILLON, ou None si M5 n'en a reçu aucun pour son WCT, ou si le dernier connu n'est
    pas évalué critique — jamais un blocage de l'envoi, seulement une information pour le
    propriétaire (`m5_envoyer_facture` reste disponible que ce signal existe ou non)."""
    wct_recu = wct_recus.pour_devis_id(facture["devis_id"], wct_registre)
    if wct_recu is None:
        return None
    signal = variance_recus.pour_wct_id(wct_recu["wct_id"], variance_registre)
    if signal is None or signal["statut_variance"] != "evaluee" or not signal["signal_critique"]:
        return None
    return {
        "type": "chantier_a_reviser",
        "id": f"variance-{signal['wct_id']}",
        "resume": (
            f"Écart matériaux critique sur le chantier {signal['chantier_id']} "
            f"(wct {signal['wct_id']}) — facture {facture['facture_id']} prête à envoyer quand même"
        ),
        "niveau": "N4",
        "depuis": signal["horodatage_completion"],
        "action_proposee": "réviser",
    }


def attentes() -> list[dict[str, Any]]:
    """File du propriétaire (ADR-0009 §5, PLAN T1.3-c point 4) :
    1. les attentes de facturation déjà calculées par `lister_attentes_facturation` (devis/WCT à
       qui il manque encore une pièce), reformées à la forme commune
       (`opsys.approbations.CHAMPS_ATTENTE`) ;
    2. chaque facture BROUILLON prête à envoyer, au même niveau que `m5_envoyer_facture` (N4) ;
    3. à côté d'une facture BROUILLON, le signal de variance de chantier CRITIQUE reçu de M6
       (`m6.variance_chantier`, gardé par wct_id — `variance_recus.py`) s'il existe : jamais un
       blocage de l'envoi, seulement une information (point 4 du mandat, relevé par le test de
       bout en bout `tests/test_attentes.py`).
    """
    brut = lister_attentes_facturation()
    devis_registre = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_DEVIS_RECUS)
    wct_registre = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_WCT_RECUS)
    variance_registre = stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE_VARIANCE_RECUE)

    items: list[dict[str, Any]] = []
    for attente in brut["attentes_devis"]:
        items.append({
            "type": f"facturation_{attente['statut']}",
            "id": attente["devis_id"],
            "resume": f"Devis {attente['devis_id']} : {attente['statut']}",
            "niveau": "N3",
            "depuis": _depuis_attente_devis(attente["devis_id"], attente["statut"], devis_registre, wct_registre),
            "action_proposee": "compléter",
        })
    for attente in brut["attentes_wct_sans_devis_id"]:
        wct_recu = wct_recus.pour_wct_id(attente["wct_id"], wct_registre)
        items.append({
            "type": "wct_sans_devis_id",
            "id": attente["wct_id"],
            "resume": f"Intervention {attente['intervention_id']} sans devis relié (wct {attente['wct_id']})",
            "niveau": "N3",
            "depuis": wct_recu["horodatage_completion"],
            "action_proposee": "relier un devis",
        })

    for facture in _factures_brouillon():
        items.append({
            "type": "facture_brouillon",
            "id": facture["facture_id"],
            "resume": f"Facture {facture['facture_id']} prête à envoyer ({facture['montant_apres_taxes']} $)",
            "niveau": "N4",
            "depuis": facture["horodatage"],
            "action_proposee": "envoyer",
        })
        variance = _variance_critique_pour_facture(facture, wct_registre, variance_registre)
        if variance is not None:
            items.append(variance)

    return items


def _vue_chantier(etat: dict[str, Any], sources: dict[str, Any], autorise_couts: bool, detail: bool) -> dict[str, Any]:
    """Ce que l'outil de lecture rend pour un devis : un statut d'attente (aucun montant), ou l'état calculé.

    Sans droit de voir les coûts (`autorise_couts` faux) : identifiants, verdict et codes de manque
    seulement (`cout_reel.masquer_montants`). Avec le droit : le détail (lignes de matériaux, sources de prix,
    hypothèses) pour un chantier précis, une ligne (`cout_reel.resumer`) pour une liste. `trace.a_jour` dit si le
    dernier état tracé par la cascade correspond aux pièces d'AUJOURD'HUI (faux : un prix, le taux ou la
    facture ont changé depuis ; le calcul rendu est, lui, toujours celui d'aujourd'hui)."""
    if etat["statut"] != "calculee":
        return {"devis_id": etat["devis_id"], "chantier_id": etat["chantier_id"], "statut": etat["statut"]}
    rentabilite = etat["rentabilite"]
    trace = sources["traces"].get(etat["devis_id"])
    if not autorise_couts:
        contenu = cout_reel.masquer_montants(rentabilite)
    elif detail:
        contenu = {cle: valeur for cle, valeur in rentabilite.items() if cle != "version_entrees"}
    else:
        contenu = cout_reel.resumer(rentabilite)
    trace_vue = {"a_jour": trace is not None and trace.get("version_entrees") == rentabilite["version_entrees"]}
    if detail:  # l'empreinte de 64 caractères n'a d'intérêt que pour un chantier précis
        trace_vue = {"version_entrees": rentabilite["version_entrees"], **trace_vue}
    return {
        "devis_id": etat["devis_id"],
        "chantier_id": etat["chantier_id"],
        "statut": "calculee",
        "rentabilite": contenu,
        "trace": trace_vue,
    }


def lire_rentabilite_chantier(
    chantier_id: str | None = None,
    devis_id: str | None = None,
    limite: int | None = None,
    role: str | None = None,
    autorise_couts: bool | None = None,
) -> dict[str, Any]:
    """Outil T0 (PLAN T1.5-d) : le coût réel et la rentabilité des chantiers, pour l'admin.

    Même contrôle d'accès que `m5_etat_tresorerie` (PLAN T1.4-k2) : pour un appel d'appareil, l'identité
    confirmée en base (`admin` seulement) ; la vue vient du rôle authentifié, un argument ne peut que la
    restreindre ; refus AVANT toute lecture, sans écriture. Sans appareil, `autorise_couts` reste obligatoire.

    Aucun montant, prix, taux, durée ni quantité ne se passe en argument : tout est lu à la source
    (`_etat_chantier`). `chantier_id` et `devis_id` ne servent qu'à CHOISIR quels chantiers lire ; un filtre
    sans résultat est `REJ-RENTABILITE-CHANTIER-INCONNU`. Les devis sont pris du plus récemment reçu au plus
    ancien, au plus `limite` (8 par défaut, 12 au plus : la réponse d'un outil est tronquée au-delà de 6 000
    caractères) ; `nombre` est le total qui correspond, `reste` ce qui n'est pas affiché."""
    acteur, refus = _acteur_appareil()
    if refus is not None:
        return _refus(refus)
    vue, verdict = acces.resoudre_vue(acteur, role, autorise_couts)
    if verdict is not None:
        return _refus(verdict)

    plafond = _LIMITE_LECTURE_DEFAUT if limite is None else limite
    if isinstance(plafond, bool) or not isinstance(plafond, int) or not 1 <= plafond <= _LIMITE_LECTURE_MAX:
        return _refus(validation.construire_verdict(
            "REJ-RENTABILITE-LIMITE-INVALIDE",
            detail=f"limite doit être un entier de 1 à {_LIMITE_LECTURE_MAX}",
        ))
    sources = _sources_cout_reel()
    filtre = devis_id is not None or chantier_id is not None
    recus = list(dict.fromkeys(  # ordre de réception, sans doublon
        m["devis_id"] for m in sources["devis"] if isinstance(m.get("devis_id"), str)))
    etats = []
    for candidat in reversed(recus):  # le plus récemment reçu d'abord
        if devis_id is not None and candidat != devis_id:
            continue
        etat = _etat_chantier(candidat, sources)
        if chantier_id is not None and etat["chantier_id"] != chantier_id:
            continue
        etats.append(etat)
    if filtre and not etats:
        return _refus(validation.construire_verdict(
            "REJ-RENTABILITE-CHANTIER-INCONNU",
            detail="aucun devis accepté reçu ne correspond à ce devis_id / chantier_id",
        ))
    affiches = etats[:plafond]
    return {"accepte": True, "resultat": {
        "role": vue["role"], "nombre": len(etats), "affichees": len(affiches), "reste": len(etats) - len(affiches),
        "chantiers": [_vue_chantier(e, sources, vue["autorise_couts"], detail=filtre) for e in affiches],
    }}


def lire_comptes_a_recevoir(
    aujourd_hui: str | None = None,
    role: str | None = None,
    autorise_couts: bool | None = None,
) -> dict[str, Any]:
    """Outil T0 (PLAN T1.5-d) : les comptes à recevoir, c'est-à-dire les factures ENVOYEE (et seulement
    elles), avec leur âge quand la date du jour est fournie. Même contrôle d'accès que
    `lire_rentabilite_chantier` (admin authentifié ; sans droit de voir les coûts : le nombre seulement).
    Ne lit que le registre des factures, n'écrit rien."""
    acteur, refus = _acteur_appareil()
    if refus is not None:
        return _refus(refus)
    vue, verdict = acces.resoudre_vue(acteur, role, autorise_couts)
    if verdict is not None:
        return _refus(verdict)
    resultat, verdict = facturation.comptes_a_recevoir(_registre_factures(None), aujourd_hui)
    if verdict is not None:
        return _refus(verdict)
    if not vue["autorise_couts"]:
        return {"accepte": True, "resultat": {
            "role": vue["role"], "nombre": resultat["nombre"], "montants_masques": True}}
    return {"accepte": True, "resultat": {"role": vue["role"], **resultat}}


def outils() -> tuple[Outil, ...]:
    return (
        Outil(
            nom="m5_etat_tresorerie",
            description=(
                "État financier de bout en bout : solde et argent disponible réel (solde moins "
                "provisions), filtrés par rôle. Sans montant (ni solde, ni argent disponible, ni taux) "
                "sauf autorisation. Pendant un appel d'appareil authentifié (PLAN T1.4-k2), la vue "
                "vient du rôle authentifié — admin : montants ; les autres n'ont pas accès — et "
                "autorise_couts ne peut que la RESTREINDRE (faux), jamais l'élargir (refus nommé "
                "REJ-ROLE-ELARGI) ; role, s'il est fourni, doit être celui du jeton. Hors appel "
                "d'appareil (agent), autorise_couts est obligatoire et explicite : vrai pour voir un "
                "montant, faux pour l'état sans montant."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "role": {
                        "type": ["string", "null"],
                        "description": (
                            "Étiquette du rôle portée par la réponse. Appel d'appareil : omis, ou égal au "
                            "rôle authentifié ; un autre est refusé (REJ-IDENTITE-FOURNIE-DIFFERENTE)."
                        ),
                    },
                    "autorise_couts": {
                        "type": ["boolean", "null"],
                        "description": (
                            "Vrai pour voir solde, argent disponible et taux. Appel d'appareil : omis, il "
                            "vaut le droit du rôle authentifié ; faux restreint la vue ; vrai sans ce "
                            "droit est refusé (REJ-ROLE-ELARGI). Sans appareil (agent, console) : "
                            "obligatoire et explicite (REJ-AUTORISE-COUTS-REQUIS)."
                        ),
                    },
                    "mouvements_historique": _HISTORIQUE_MOUVEMENTS,
                    "taux_utilises": {"type": "array", "items": {"type": "object"}},
                },
                "additionalProperties": False,
            },
            fonction=etat_tresorerie,
            autonomie=Autonomie.T0,
            # §9.5 M5 (trésorerie et cash libre réel) : l'admin seul. Pour un appel d'appareil, la vue vient
            # du rôle authentifié et confirmé en base (T1.4-k2, acces.py), pas de `role` ni d'`autorise_couts`.
            roles_appareil=_ROLES_APPAREIL_FINANCE,
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
            fonction=lister_attentes_facturation_appareil,
            autonomie=Autonomie.T0,
            # §9.5 M5 (factures à préparer et à approuver). Identité confirmée en base (T1.4-k2).
            roles_appareil=_ROLES_APPAREIL_FINANCE,
        ),
        Outil(
            nom="m5_lire_rentabilite_chantier",
            description=(
                "Coût réel et rentabilité des chantiers (PLAN T1.5-d), pour l'admin : matériaux réellement "
                "utilisés (variance M6) x prix du livre de prix M6, main-d'oeuvre pointée (WCT) x taux horaire "
                "configuré ; prix facturé avant taxes moins coût réel ; marge réelle contre marge prévue du "
                "devis. Tout est lu à la source, rien ne se passe en argument. Un coût partiel est dit partiel, "
                "avec la liste `manque` (prix non disponible, taux à configurer, temps absent...) : jamais un "
                "chiffre inventé. Avec devis_id ou chantier_id : le détail ; sans : une ligne par devis "
                "(limite, 8 récents). Lecture pure, aucune écriture comptable. Même règle d'accès que "
                "m5_etat_tresorerie : admin "
                "seulement ; autorise_couts ne peut que restreindre (sans droit : aucun montant)."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "chantier_id": {"type": ["string", "null"], "description": "Filtre : lire ce chantier."},
                    "devis_id": {"type": ["string", "null"], "description": "Filtre : lire ce devis."},
                    "limite": {
                        "type": ["integer", "null"], "minimum": 1, "maximum": _LIMITE_LECTURE_MAX,
                        "description": (
                            f"Nombre de devis rendus, du plus récent au plus ancien (défaut {_LIMITE_LECTURE_DEFAUT}, "
                            f"au plus {_LIMITE_LECTURE_MAX}) ; `reste` dit ce qui n'est pas affiché."
                        ),
                    },
                    "role": _ROLE_DE_LECTURE,
                    "autorise_couts": _AUTORISE_COUTS_DE_LECTURE,
                },
                "additionalProperties": False,
            },
            fonction=lire_rentabilite_chantier,
            autonomie=Autonomie.T0,
            roles_appareil=_ROLES_APPAREIL_FINANCE,
        ),
        Outil(
            nom="m5_lire_comptes_a_recevoir",
            description=(
                "Comptes à recevoir (PLAN T1.5-d), pour l'admin : les factures ENVOYEE, et seulement elles (une "
                "BROUILLON n'est pas due, une PAYEE ou ANNULEE non plus), avec le total et, si aujourd_hui "
                "(AAAA-MM-JJ) est fourni, l'âge par tranche (0-30, 31-60, 61-90, 90+). Sans aujourd_hui : pas "
                "d'âge, la date du jour n'est jamais devinée. Vue de l'état des factures : rien à mettre à "
                "jour, aucune écriture. Même règle d'accès que m5_etat_tresorerie : admin seulement ; "
                "autorise_couts ne peut que restreindre (sans droit : le nombre de factures seulement)."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "aujourd_hui": {
                        "type": ["string", "null"],
                        "description": "Date du jour ISO 8601 (AAAA-MM-JJ), pour l'âge des créances. Optionnelle.",
                    },
                    "role": _ROLE_DE_LECTURE,
                    "autorise_couts": _AUTORISE_COUTS_DE_LECTURE,
                },
                "additionalProperties": False,
            },
            fonction=lire_comptes_a_recevoir,
            autonomie=Autonomie.T0,
            roles_appareil=_ROLES_APPAREIL_FINANCE,
        ),
        Outil(
            nom="m5_envoyer_facture",
            description=(
                "Transitionne une facture BROUILLON vers ENVOYEE (engagement client). N'est "
                "JAMAIS exécuté directement par l'agent : la file d'approbation du socle "
                "intercepte l'appel (N4) et ne l'exécute qu'après la décision signée d'une "
                "personne autorisée (department.yaml/approbations.n4 : finance ou nathan_owner). "
                "Aucun envoi réel de courriel ici (M1, plus tard) : seulement le statut et sa "
                "trace."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "facture_id": {"type": "string"},
                    "horodatage": {"type": "string", "description": "ISO 8601 avec fuseau"},
                    "factures_historique": _HISTORIQUE_FACTURES,
                },
                "required": ["facture_id", "horodatage"],
                "additionalProperties": False,
            },
            fonction=envoyer_facture,
            autonomie=Autonomie.T2,
            niveau=NIVEAU_ENVOI_FACTURE,
        ),
        Outil(
            nom="m5_enregistrer_paiement_facture",
            description=(
                "Transitionne une facture ENVOYEE vers PAYEE (argent réel). N'est JAMAIS exécuté "
                "directement : le socle exige nathan_owner ET l'attestation du professionnel "
                "(ex. référence de dépôt bancaire, N5, jamais automatique). montant_paye — ce qui "
                "a RÉELLEMENT été déposé — est comparé par le code au montant dû de la facture ; "
                "un paiement partiel ou tout autre écart est un verdict nommé, jamais accepté "
                "sans contrôle. N'écrit jamais dans le registre des mouvements (voir "
                "m5_enregistrer_mouvement, un ENCAISSEMENT réel reste un appel séparé)."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "facture_id": {"type": "string"},
                    "montant_paye": _MONTANT_TEXTE,
                    "approbateur": {"type": "string"},
                    "horodatage": {"type": "string", "description": "ISO 8601 avec fuseau"},
                    "factures_historique": _HISTORIQUE_FACTURES,
                },
                "required": ["facture_id", "montant_paye", "approbateur", "horodatage"],
                "additionalProperties": False,
            },
            fonction=enregistrer_paiement_facture,
            autonomie=Autonomie.T3,
            niveau=NIVEAU_PAIEMENT_FACTURE,
        ),
    )
