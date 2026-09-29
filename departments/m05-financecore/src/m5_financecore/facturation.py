"""Facturation client (M5.2) : facture brouillon, verrous d'envoi/paiement, âge des créances.

Module pur (ADR-0009, même règle que `registre.py`/`approbation.py`) : aucun import `opsys`,
aucune horloge interne, aucun accès réseau. Tous les montants sont des `Decimal` construits
depuis du texte — jamais un float — et TOUS recalculés depuis les lignes : ce module ne fait
JAMAIS confiance à un `montant_avant_taxes` fourni par l'appelant ; s'il en fournit un quand
même (contrôle défensif optionnel), il doit correspondre exactement au total recalculé, sinon
c'est un rejet nommé (REJ-FACTURE-MONTANT-INCOHERENT). `aujourd_hui` (âge des créances) est
fourni par l'appelant : M5 n'a pas d'horloge (DA-M5-06, docs/departements/M5-audit.md).

T1.2 (à venir) sourcera `lignes` depuis le devis APPROUVÉ de M3 plutôt que d'un appelant
arbitraire — ce module ne valide aujourd'hui que la cohérence interne des lignes fournies,
jamais leur véracité face à une soumission M3 réelle. `outils.py` reste le seul point du
département qui saura, à ce moment-là, aller chercher ces lignes ; `facturation.py` continuera
de les recevoir déjà faites, sans jamais importer de module d'un autre département (DA-M5-04).

Piège documenté (docs/departements/M5-audit.md, résumé exécutif) : ce module n'écrit JAMAIS
dans le registre des MOUVEMENTS et ne l'importe même pas. Une facture marquée PAYEE ne produit
PAS d'ENCAISSEMENT ici — l'encaissement réel (un dépôt bancaire constaté) reste un
`m5_enregistrer_mouvement` distinct, déclenché par une preuve de paiement réel, jamais
automatiquement par ce module (voir `test_marquer_facture_payee_n_ecrit_jamais_dans_le_registre_des_mouvements`).

Registre : comme `approbation.py`, ce module ne construit ni n'importe `registre.Registre` — il
reçoit un `registre_cible` déjà construit (duck-typé : `ajouter`/`lire`) et n'a donc pas besoin
de savoir s'il est en mémoire ou durable (`opsys.stockage.maillons(...)`, choix de `outils.py`
seul). Chaque facture vit comme un petit événement : un maillon `facture_creee` puis, à chaque
transition, un maillon `transition_facture` — l'état courant d'une facture est la fusion de ces
maillons dans l'ordre (voir `_etats_courants`), jamais seulement le dernier (un champ posé à une
transition antérieure, ex. `date_envoi`, doit rester visible après une transition ultérieure).

PLAN T1.3-c (branchement sur les approbations du socle) : `envoyer_facture` ne reçoit et ne
vérifie plus AUCUN maillon d'approbation — l'ancienne garde sur la FORME d'un maillon F4 (palier,
statut, approbateur non vide) est retirée, pas seulement affaiblie. La décision d'envoyer une
facture appartient désormais exclusivement au socle (`opsys.approbations.decider`, niveau N4,
ADR-0009 §4/§5) : l'outil agent `m5_envoyer_facture` (`outils.py`) est intercepté par
`opsys.capacites.Capacites._distribuer` AVANT d'atteindre ce module, et n'est exécuté qu'une fois
qu'une personne autorisée (`department.yaml/approbations.n4`) a décidé — jamais par cette fonction
elle-même. L'exécution de `envoyer_facture` est donc déjà la preuve de cette décision ; QUI a
décidé et QUAND restent tracés par le socle (table `approbations` : `decide_par`, `decide_role`,
`decide_le`), jamais dupliqués dans ce registre. `marquer_facture_payee` garde son propre
`approbateur` texte (comportement INCHANGÉ, aucune régression) ; `enregistrer_paiement_facture`,
elle, est gardée par le socle au niveau N5 (`nathan_owner` ET l'attestation du professionnel,
ADR-0009 §5, imposées par `opsys.approbations`, jamais par ce module) et compare en plus le
montant RÉELLEMENT déposé au montant dû, calculé par le code — jamais une écriture PAYEE sur un
paiement partiel ou un écart (voir plus bas).
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from . import taxes, validation

_DEUX_DECIMALES = Decimal("0.01")
# PLAN T1.2-d (arrondi monétaire) : ROUND_HALF_UP explicite partout où ce module arrondit de
# l'argent, jamais le mode par défaut du module `decimal` (ROUND_HALF_EVEN, « arrondi du
# banquier »). Même mode que M3 (`devis_durable.creer_devis`, `outils.arrondir_au_cent`) : un
# montant de ligne doit arrondir comme la ligne de devis dont il provient (T1.2 le sourcera
# directement de M3), sinon la facture envoyée peut différer d'un cent du devis que le client a
# accepté. Contrairement au montant d'une taxe (`taxes.py`), ce choix n'est pas dicté par la loi —
# c'est une cohérence interne au département — d'où le commentaire distinct ici.

_CHAMPS_LIGNE_REQUIS = frozenset(
    {"description", "quantite", "unite", "prix_unitaire", "reference_ligne_devis"}
)

_TRANCHES_CREANCES = ("0-30", "31-60", "61-90", "90+")


@dataclasses.dataclass(frozen=True)
class LigneFacture:
    """Une ligne de facture. `quantite` et `prix_unitaire` sont des `Decimal` déjà validés (texte
    en entrée, jamais un float) ; `montant` (= quantite * prix_unitaire, 2 décimales,
    ROUND_HALF_UP explicite) est calculé une fois par `_valider_ligne` et conservé ici, jamais
    recalculé ailleurs à la volée."""

    description: str
    quantite: Decimal
    unite: str
    prix_unitaire: Decimal
    reference_ligne_devis: str
    montant: Decimal


@dataclasses.dataclass(frozen=True)
class FactureBrouillonV1:
    """Contrat gelé d'une facture. `montant_avant_taxes`, `taxes`, `total_taxes` et
    `montant_apres_taxes` sont TOUJOURS recalculés par `creer_facture_brouillon` depuis
    `lignes` (via `taxes.calculer_taxes`, taux versionnés) — jamais acceptés tels quels d'un
    appelant."""

    facture_id: str
    chantier_id: str
    devis_id: str
    client_id: str
    lignes: tuple[LigneFacture, ...]
    montant_avant_taxes: Decimal
    taxes: tuple[dict[str, Any], ...]
    total_taxes: Decimal
    montant_apres_taxes: Decimal
    statut: str
    horodatage: str


def _est_texte_non_vide(valeur: Any) -> bool:
    return isinstance(valeur, str) and valeur.strip() != ""


def _texte_vers_decimal(valeur: Any, nom_champ: str, code_erreur: str) -> tuple[Decimal | None, dict | None]:
    if not isinstance(valeur, str):
        return None, validation.construire_verdict(
            code_erreur, detail=f"{nom_champ} doit être fourni en texte décimal (jamais un nombre JSON)"
        )
    try:
        decimal_valeur = Decimal(valeur)
    except InvalidOperation:
        return None, validation.construire_verdict(code_erreur, detail=f"{nom_champ} décimal invalide : {valeur!r}")
    if not decimal_valeur.is_finite():
        return None, validation.construire_verdict(code_erreur, detail=f"{nom_champ} doit être fini")
    return decimal_valeur, None


def _valider_ligne(brute: Any, index: int) -> tuple[LigneFacture | None, dict | None]:
    if not isinstance(brute, dict) or set(brute.keys()) != _CHAMPS_LIGNE_REQUIS:
        return None, validation.construire_verdict(
            "REJ-FACTURE-LIGNE-INVALIDE",
            detail=f"ligne {index} : structure invalide (clés attendues {sorted(_CHAMPS_LIGNE_REQUIS)})",
        )
    for champ in ("description", "unite", "reference_ligne_devis"):
        if not _est_texte_non_vide(brute[champ]):
            return None, validation.construire_verdict(
                "REJ-FACTURE-LIGNE-INVALIDE", detail=f"ligne {index} : champ {champ!r} requis, non vide"
            )

    quantite, verdict = _texte_vers_decimal(brute["quantite"], f"ligne {index} quantite", "REJ-FACTURE-LIGNE-INVALIDE")
    if verdict is not None:
        return None, verdict
    if quantite <= 0:
        return None, validation.construire_verdict(
            "REJ-FACTURE-LIGNE-INVALIDE", detail=f"ligne {index} : quantite doit être strictement positive"
        )

    prix_unitaire, verdict = _texte_vers_decimal(
        brute["prix_unitaire"], f"ligne {index} prix_unitaire", "REJ-FACTURE-LIGNE-INVALIDE"
    )
    if verdict is not None:
        return None, verdict

    montant = (quantite * prix_unitaire).quantize(_DEUX_DECIMALES, rounding=ROUND_HALF_UP)
    ligne = LigneFacture(
        description=brute["description"],
        quantite=quantite,
        unite=brute["unite"],
        prix_unitaire=prix_unitaire,
        reference_ligne_devis=brute["reference_ligne_devis"],
        montant=montant,
    )
    return ligne, None


def _champs_facture(facture: FactureBrouillonV1) -> dict[str, Any]:
    """Aplati `facture` en un dict sûr pour le registre : `lignes`/`taxes` en listes de dicts
    (jamais des dataclasses ni des tuples — `encodage.empreinte` ne connaît pas les dataclasses,
    et une liste est ce qu'un `historique` retransmis en JSON redonnera de toute façon, donc
    l'empreinte d'un maillon rejoué depuis JSON doit déjà partir de la même forme)."""
    return {
        "facture_id": facture.facture_id,
        "chantier_id": facture.chantier_id,
        "devis_id": facture.devis_id,
        "client_id": facture.client_id,
        "lignes": [dataclasses.asdict(ligne) for ligne in facture.lignes],
        "montant_avant_taxes": facture.montant_avant_taxes,
        "taxes": list(facture.taxes),
        "total_taxes": facture.total_taxes,
        "montant_apres_taxes": facture.montant_apres_taxes,
        "statut": facture.statut,
        "horodatage": facture.horodatage,
    }


def _ajouter_et_retrouver(entree: dict[str, Any], registre_cible: Any) -> dict[str, Any]:
    ligne_id = registre_cible.ajouter(entree)
    for maillon in registre_cible.lire():
        if maillon["ligne_id"] == ligne_id:
            return maillon
    raise RuntimeError("Maillon ajouté introuvable.")


def _etats_courants(registre_cible: Any) -> dict[str, dict[str, Any]]:
    """État courant de chaque facture connue de `registre_cible` : une fusion, dans l'ordre du
    registre, de son maillon `facture_creee` puis de chacun de ses `transition_facture` — pas
    seulement le dernier maillon, pour qu'un champ posé à une transition antérieure (ex.
    `date_envoi` posé à l'envoi) reste visible après une transition ultérieure (ex. le paiement).
    """
    etats: dict[str, dict[str, Any]] = {}
    for maillon in registre_cible.lire():
        type_entree = maillon.get("type_entree")
        if type_entree == "facture_creee":
            etats[maillon["facture_id"]] = dict(maillon)
        elif type_entree == "transition_facture":
            facture_id = maillon.get("facture_id")
            if facture_id in etats:
                etats[facture_id] = {**etats[facture_id], **maillon}
    return etats


def _etat_facture(registre_cible: Any, facture_id: str) -> dict[str, Any] | None:
    return _etats_courants(registre_cible).get(facture_id)


def facture_active_pour_devis(registre_cible: Any, devis_id: str) -> dict[str, Any] | None:
    """La facture ACTIVE (statut != ANNULEE) pour ce devis_id, ou None si aucune.

    Un devis ne porte jamais plus d'une facture active à la fois — `creer_facture_brouillon` le
    garantit (REJ-FACTURE-DEVIS-DEJA-FACTURE) en appelant CETTE fonction ci-dessous ; exposée
    publiquement (PLAN T1.2-d, suite) pour un appelant qui a seulement besoin de SAVOIR si une
    facture existe déjà pour un devis (ex. `outils.lister_attentes_facturation`), sans
    reconstruire lignes/montant/horodatage pour le découvrir en retentant une création."""
    return next(
        (
            etat
            for etat in _etats_courants(registre_cible).values()
            if etat.get("devis_id") == devis_id and etat.get("statut") != "ANNULEE"
        ),
        None,
    )


def factures_actives_par_devis(registre_cible: Any) -> dict[str, dict[str, Any]]:
    """La facture ACTIVE (statut != ANNULEE) de chaque devis, en UNE relecture du registre : la même règle que
    `facture_active_pour_devis` (la première trouvée), pour un appelant qui lit beaucoup de devis (PLAN T1.5-d) et
    ne doit pas relire (et copier) tout le registre des factures à chaque devis."""
    actives: dict[str, dict[str, Any]] = {}
    for etat in _etats_courants(registre_cible).values():
        devis_id = etat.get("devis_id")
        if devis_id is not None and etat.get("statut") != "ANNULEE" and devis_id not in actives:
            actives[devis_id] = etat
    return actives


def factures_par_statut(registre_cible: Any, statut: str) -> tuple[dict[str, Any], ...]:
    """Toutes les factures actuellement à ce statut (état courant, PLAN T1.3-c), triées par
    `facture_id` pour un ordre stable. Même patron que `facture_active_pour_devis` : fonction
    publique extraite de `_etats_courants`, exposée pour un appelant qui a seulement besoin de
    RETROUVER des factures par statut (ex. `outils.attentes`, les BROUILLON prêtes à envoyer),
    sans dupliquer la logique de fusion des maillons."""
    return tuple(
        sorted(
            (etat for etat in _etats_courants(registre_cible).values() if etat.get("statut") == statut),
            key=lambda etat: etat["facture_id"],
        )
    )


def creer_facture_brouillon(
    facture_id: str,
    chantier_id: str,
    devis_id: str,
    client_id: str,
    lignes: list[dict[str, Any]],
    horodatage: str,
    dictionnaire_taux: dict[str, dict[str, Any]],
    registre_cible: Any,
    montant_avant_taxes_fourni: str | None = None,
) -> tuple[dict[str, Any] | None, dict | None]:
    """Crée une facture BROUILLON sur `registre_cible` (le registre dédié des FACTURES,
    troisième registre du département, jamais celui des mouvements). Idempotent par
    `devis_id` : refuse s'il existe déjà une facture ACTIVE (statut != ANNULEE) pour ce devis."""
    if not _est_texte_non_vide(facture_id):
        return None, validation.construire_verdict(
            "REJ-FACTURE-FACTURE-ID-VIDE", detail="facture_id requis, non vide"
        )
    if not _est_texte_non_vide(chantier_id):
        return None, validation.construire_verdict(
            "REJ-FACTURE-CHANTIER-ID-VIDE", detail="chantier_id requis, non vide"
        )
    if not _est_texte_non_vide(devis_id):
        return None, validation.construire_verdict("REJ-FACTURE-DEVIS-ID-VIDE", detail="devis_id requis, non vide")
    if not _est_texte_non_vide(client_id):
        return None, validation.construire_verdict(
            "REJ-FACTURE-CLIENT-ID-VIDE", detail="client_id requis, non vide"
        )
    if not isinstance(lignes, (list, tuple)) or not lignes:
        return None, validation.construire_verdict("REJ-FACTURE-LIGNES-VIDES", detail="au moins une ligne est requise")

    lignes_validees: list[LigneFacture] = []
    montant_avant_taxes = Decimal("0")
    for index, brute in enumerate(lignes):
        ligne, verdict = _valider_ligne(brute, index)
        if verdict is not None:
            return None, verdict
        lignes_validees.append(ligne)
        montant_avant_taxes += ligne.montant

    if montant_avant_taxes_fourni is not None:
        fourni, verdict = _texte_vers_decimal(
            montant_avant_taxes_fourni, "montant_avant_taxes", "REJ-FACTURE-MONTANT-INCOHERENT"
        )
        if verdict is not None:
            return None, verdict
        if fourni != montant_avant_taxes:
            return None, validation.construire_verdict(
                "REJ-FACTURE-MONTANT-INCOHERENT",
                detail=(
                    f"montant_avant_taxes fourni ({fourni}) diffère du total recalculé "
                    f"depuis les lignes ({montant_avant_taxes})"
                ),
            )

    resultat_taxes, verdict_taxes = taxes.calculer_taxes(montant_avant_taxes, dictionnaire_taux)
    if verdict_taxes is not None:
        return None, verdict_taxes

    existante = facture_active_pour_devis(registre_cible, devis_id)
    if existante is not None:
        return None, validation.construire_verdict(
            "REJ-FACTURE-DEVIS-DEJA-FACTURE",
            detail=(
                f"devis {devis_id!r} déjà facturé par {existante['facture_id']!r} "
                f"(statut {existante['statut']!r})"
            ),
        )

    facture = FactureBrouillonV1(
        facture_id=facture_id,
        chantier_id=chantier_id,
        devis_id=devis_id,
        client_id=client_id,
        lignes=tuple(lignes_validees),
        montant_avant_taxes=montant_avant_taxes,
        taxes=tuple(resultat_taxes["taxes"]),
        total_taxes=resultat_taxes["total_taxes"],
        montant_apres_taxes=resultat_taxes["montant_apres_taxes"],
        statut="BROUILLON",
        horodatage=horodatage,
    )

    entree = {**_champs_facture(facture), "type_entree": "facture_creee"}
    return _ajouter_et_retrouver(entree, registre_cible), None


def envoyer_facture(
    facture_id: str, horodatage: str, registre_cible: Any
) -> tuple[dict[str, Any] | None, dict | None]:
    """Verrou d'envoi : BROUILLON -> ENVOYEE. La décision d'approuver appartient exclusivement au
    socle (N4, `opsys.approbations.decider` — voir le docstring du module) : cette fonction ne
    reçoit et ne vérifie plus aucun maillon d'approbation. `date_envoi` posé ici sert de base à
    `calculer_age_creances`."""
    etat = _etat_facture(registre_cible, facture_id)
    if etat is None:
        return None, validation.construire_verdict(
            "REJ-FACTURE-INTROUVABLE", detail=f"facture inconnue : {facture_id!r}"
        )
    if etat["statut"] != "BROUILLON":
        return None, validation.construire_verdict(
            "REJ-FACTURE-TRANSITION-ILLEGALE",
            detail=f"facture {facture_id!r} au statut {etat['statut']!r}, BROUILLON requis pour l'envoi",
        )

    entree = {
        "type_entree": "transition_facture",
        "facture_id": facture_id,
        "statut": "ENVOYEE",
        "date_envoi": horodatage,
        "horodatage": horodatage,
    }
    return _ajouter_et_retrouver(entree, registre_cible), None


def marquer_facture_payee(
    facture_id: str, approbateur: str, horodatage: str, registre_cible: Any
) -> tuple[dict[str, Any] | None, dict | None]:
    """ENVOYEE -> PAYEE. Frontière humaine T3 : même garde que `approbation.approuver` —
    `approbateur` doit être une chaîne non vide, un humain qui constate un paiement réel sur
    pièces. AUCUN pont bancaire réel et AUCUNE écriture dans le registre des MOUVEMENTS ici :
    marquer une facture payée n'enregistre jamais d'ENCAISSEMENT de lui-même (piège documenté,
    docs/departements/M5-audit.md) — un ENCAISSEMENT réel reste un `m5_enregistrer_mouvement`
    séparé, déclenché par la constatation du dépôt, jamais automatiquement par cette fonction."""
    etat = _etat_facture(registre_cible, facture_id)
    if etat is None:
        return None, validation.construire_verdict(
            "REJ-FACTURE-INTROUVABLE", detail=f"facture inconnue : {facture_id!r}"
        )
    if etat["statut"] != "ENVOYEE":
        return None, validation.construire_verdict(
            "REJ-FACTURE-TRANSITION-ILLEGALE",
            detail=f"facture {facture_id!r} au statut {etat['statut']!r}, ENVOYEE requis avant paiement",
        )
    if not _est_texte_non_vide(approbateur):
        return None, validation.construire_verdict(
            "REJ-FACTURE-APPROBATEUR-ABSENT", detail="approbateur humain requis, non vide"
        )

    entree = {
        "type_entree": "transition_facture",
        "facture_id": facture_id,
        "statut": "PAYEE",
        "date_paiement": horodatage,
        "approbateur": approbateur,
        "horodatage": horodatage,
    }
    return _ajouter_et_retrouver(entree, registre_cible), None


def enregistrer_paiement_facture(
    facture_id: str, montant_paye: str, approbateur: str, horodatage: str, registre_cible: Any
) -> tuple[dict[str, Any] | None, dict | None]:
    """Frontière N5 (PLAN T1.3-c) : le socle exige déjà `nathan_owner` ET l'attestation du
    professionnel (ADR-0009 §5, `opsys.approbations.decider`) avant que cette fonction ne
    s'exécute — jamais vérifié ici (voir le docstring du module). Ce que CE module ajoute : le
    montant RÉELLEMENT déposé (`montant_paye`, ex. relevé/référence de dépôt bancaire) est
    comparé par le CODE au montant dû de la facture (`montant_apres_taxes`, déjà calculé et
    JAMAIS refourni par l'appelant) — jamais un montant inventé ni accepté sans contrôle. Un
    paiement partiel (`REJ-FACTURE-PAIEMENT-PARTIEL`) ou tout autre écart, y compris un
    excédent (`REJ-FACTURE-PAIEMENT-ECART`), est un verdict nommé : la facture n'est marquée
    PAYEE que si le montant concorde exactement. Une fois le montant validé, délègue à
    `marquer_facture_payee` (ENVOYEE -> PAYEE, `approbateur` non vide, aucune écriture dans le
    registre des mouvements) : composition, pas réécriture."""
    etat = _etat_facture(registre_cible, facture_id)
    if etat is None:
        return None, validation.construire_verdict(
            "REJ-FACTURE-INTROUVABLE", detail=f"facture inconnue : {facture_id!r}"
        )
    montant_du = etat.get("montant_apres_taxes")
    if not isinstance(montant_du, Decimal):
        # Défense en profondeur (maillon corrompu ou construit à la main sans montant_apres_taxes) :
        # jamais un montant dû inventé pour comparer quand même.
        return None, validation.construire_verdict(
            "REJ-FACTURE-INTROUVABLE", detail=f"facture {facture_id!r} : montant dû illisible"
        )

    montant_paye_decimal, verdict = _texte_vers_decimal(
        montant_paye, "montant_paye", "REJ-FACTURE-PAIEMENT-MONTANT-INVALIDE"
    )
    if verdict is not None:
        return None, verdict
    if montant_paye_decimal <= 0:
        return None, validation.construire_verdict(
            "REJ-FACTURE-PAIEMENT-MONTANT-INVALIDE", detail="montant_paye doit être strictement positif"
        )

    if montant_paye_decimal < montant_du:
        return None, validation.construire_verdict(
            "REJ-FACTURE-PAIEMENT-PARTIEL",
            detail=(
                f"montant payé ({montant_paye_decimal}) < montant dû ({montant_du}) "
                f"pour la facture {facture_id!r} : paiement partiel, jamais marqué PAYEE"
            ),
        )
    if montant_paye_decimal > montant_du:
        return None, validation.construire_verdict(
            "REJ-FACTURE-PAIEMENT-ECART",
            detail=(
                f"montant payé ({montant_paye_decimal}) != montant dû ({montant_du}) "
                f"pour la facture {facture_id!r} : écart, jamais marqué PAYEE sans vérification"
            ),
        )

    return marquer_facture_payee(facture_id, approbateur, horodatage, registre_cible)


def _tranche_pour_age(age_jours: int) -> str:
    if age_jours <= 30:
        return "0-30"
    if age_jours <= 60:
        return "31-60"
    if age_jours <= 90:
        return "61-90"
    return "90+"


def calculer_age_creances(registre_factures: Any, aujourd_hui: str) -> tuple[dict[str, Any] | None, dict | None]:
    """Âge des comptes à recevoir : regroupe par tranche (0-30, 31-60, 61-90, 90+) les factures
    actuellement ENVOYEE — les seules encore « à recevoir » : une BROUILLON n'a pas été envoyée,
    une PAYEE ou une ANNULEE ne sont plus dues — depuis leur `date_envoi` jusqu'à `aujourd_hui`.
    `aujourd_hui` (date ISO 8601, ex. "2026-09-28") est fourni par l'appelant : M5 n'a pas
    d'horloge (DA-M5-06). Une facture ENVOYEE sans `date_envoi` utilisable (absente, illisible,
    ou postérieure à `aujourd_hui`) est EXCLUE avec un verdict nommé, jamais classée par défaut.
    """
    try:
        date_du_jour = date.fromisoformat(aujourd_hui)
    except (TypeError, ValueError):
        return None, validation.construire_verdict(
            "REJ-CREANCES-AUJOURDHUI-INVALIDE",
            detail=f"aujourd_hui doit être une date ISO 8601 (AAAA-MM-JJ) : {aujourd_hui!r}",
        )

    tranches: dict[str, list[dict[str, Any]]] = {tranche: [] for tranche in _TRANCHES_CREANCES}
    total_par_tranche: dict[str, Decimal] = {tranche: Decimal("0") for tranche in _TRANCHES_CREANCES}
    exclues: list[dict[str, Any]] = []

    for etat in _etats_courants(registre_factures).values():
        if etat.get("statut") != "ENVOYEE":
            continue
        facture_id = etat["facture_id"]
        date_envoi_texte = etat.get("date_envoi")
        if not _est_texte_non_vide(date_envoi_texte):
            exclues.append(
                {
                    "facture_id": facture_id,
                    "verdict": validation.construire_verdict(
                        "REJ-CREANCES-DATE-ENVOI-ABSENTE",
                        detail=f"facture {facture_id!r} envoyée sans date_envoi utilisable",
                    ),
                }
            )
            continue
        try:
            date_envoi = datetime.fromisoformat(date_envoi_texte).date()
        except ValueError:
            exclues.append(
                {
                    "facture_id": facture_id,
                    "verdict": validation.construire_verdict(
                        "REJ-CREANCES-DATE-ENVOI-INVALIDE",
                        detail=f"facture {facture_id!r} : date_envoi non ISO 8601 : {date_envoi_texte!r}",
                    ),
                }
            )
            continue

        age_jours = (date_du_jour - date_envoi).days
        if age_jours < 0:
            exclues.append(
                {
                    "facture_id": facture_id,
                    "verdict": validation.construire_verdict(
                        "REJ-CREANCES-DATE-ENVOI-INVALIDE",
                        detail=(
                            f"facture {facture_id!r} : date_envoi ({date_envoi.isoformat()}) "
                            f"postérieure à aujourd_hui ({date_du_jour.isoformat()})"
                        ),
                    ),
                }
            )
            continue

        tranche = _tranche_pour_age(age_jours)
        montant_du = etat.get("montant_apres_taxes", Decimal("0"))
        tranches[tranche].append(
            {
                "facture_id": facture_id,
                "client_id": etat.get("client_id"),
                "montant_apres_taxes": montant_du,
                "date_envoi": date_envoi.isoformat(),
                "age_jours": age_jours,
            }
        )
        total_par_tranche[tranche] += montant_du

    return {
        "aujourd_hui": date_du_jour.isoformat(),
        "tranches": tranches,
        "total_par_tranche": total_par_tranche,
        "exclues": exclues,
    }, None


def comptes_a_recevoir(
    registre_factures: Any, aujourd_hui: str | None = None
) -> tuple[dict[str, Any] | None, dict | None]:
    """Les comptes à recevoir (PLAN T1.5-d, DEFINITION-PRODUIT §6 « travaux terminés ») : les factures
    actuellement ENVOYEE, et seulement elles.

    Il n'y a AUCUNE écriture à faire pour « mettre à jour » les comptes à recevoir : ils sont une VUE de
    l'état courant du registre des factures, donc toujours à jour. Une BROUILLON n'a pas été envoyée
    (l'envoi est la décision humaine N4 du socle, `m5_envoyer_facture`) et n'est pas due ; une PAYEE
    ou une ANNULEE ne l'est plus. C'est la même règle que `calculer_age_creances`, dont on réutilise
    l'âge quand la date du jour est fournie.

    `aujourd_hui` est optionnel : M5 n'a pas d'horloge (DA-M5-06) et ne devine jamais la date. Absent,
    on rend la liste et le total sans âge (`age` est `None`, `age_non_calcule` le dit) ; invalide, c'est
    le verdict de `calculer_age_creances`, sans rien rendre. Un montant dû illisible n'entre JAMAIS au
    total (`REJ-CREANCES-MONTANT-ILLISIBLE` dans `illisibles`, `total_complet` faux)."""
    age = None
    if aujourd_hui is not None:
        age, verdict = calculer_age_creances(registre_factures, aujourd_hui)
        if verdict is not None:
            return None, verdict

    factures: list[dict[str, Any]] = []
    illisibles: list[dict[str, Any]] = []
    total = Decimal("0")
    for etat in sorted(_etats_courants(registre_factures).values(), key=lambda e: e["facture_id"]):
        if etat.get("statut") != "ENVOYEE":
            continue
        montant_du = etat.get("montant_apres_taxes")
        if not isinstance(montant_du, Decimal) or not montant_du.is_finite():
            illisibles.append(
                {
                    "facture_id": etat["facture_id"],
                    "verdict": validation.construire_verdict(
                        "REJ-CREANCES-MONTANT-ILLISIBLE",
                        detail=f"facture {etat['facture_id']!r} envoyée dont le montant dû est illisible",
                    ),
                }
            )
            continue
        total += montant_du
        factures.append(
            {
                "facture_id": etat["facture_id"],
                "chantier_id": etat.get("chantier_id"),
                "devis_id": etat.get("devis_id"),
                "client_id": etat.get("client_id"),
                "montant_apres_taxes": montant_du,
                "date_envoi": etat.get("date_envoi"),
            }
        )

    return {
        "factures": factures,
        "nombre": len(factures),
        "total_a_recevoir": total,
        "total_complet": not illisibles,
        "illisibles": illisibles,
        "age": age,
        "age_non_calcule": "aujourd_hui absent : la date du jour n'est jamais devinée" if age is None else None,
    }, None
