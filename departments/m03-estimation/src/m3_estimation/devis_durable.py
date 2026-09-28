"""Devis durable de M3 (PLAN T2.3-a/b) : quote commerciale multi-lignes, prix calculé, cycle de vie gardé.

Module pur (ADR-0009, même règle que ``registre.py``/``devis.py``) : aucun import ``opsys``, aucune
horloge interne, aucun accès réseau. Tous les montants sont des ``Decimal`` construits depuis du
texte — jamais un float. Le PRIX de chaque ligne est TOUJOURS calculé par le code, jamais fourni,
en DEUX arrondis ``ROUND_HALF_UP`` au cent, dans cet ORDRE PRÉCIS (PLAN T2.3-b) :

    prix_unitaire = arrondi(cout_unitaire x (1 + taux_marge), cent)   # arrondi D'ABORD
    prix_ligne    = arrondi(prix_unitaire x quantite, cent)           # PUIS multiplié, arrondi

``ROUND_HALF_UP`` (jamais le défaut du module ``decimal``, ``ROUND_HALF_EVEN``) — même mode
qu'``outils.arrondir_au_cent``, déjà utilisé ailleurs dans ce département. Cet ordre n'est pas
arbitraire : la facture brouillon de M5 (``facturation.creer_facture_brouillon``) recalcule
chaque ligne en ``montant = quantite x prix_unitaire``, arrondi UNE fois — c'est exactement la
seconde étape ci-dessus, appliquée au ``prix_unitaire`` que M3 a DÉJÀ arrondi et publié. Arrondir
plutôt ``cout_ligne`` puis le multiplier par ``(1 + taux_marge)`` (l'ordre de PLAN T2.3-a, corrigé
ici) donne un résultat qui peut diverger d'un cent de ce que M5 recalculera à partir du seul
``prix_unitaire`` qu'il connaît — constaté sur un cas réel (``cout_unitaire=15.50, quantite=4,
taux_marge=0.25`` : ancien ordre 77.50, nouvel ordre 77.52, et c'est ce dernier chiffre que M5
obtiendra en recalculant 4 x 19.38). ``cout_ligne`` reste indépendant du prix : ``cout_unitaire x
quantite``, arrondi une fois, jamais mêlé au calcul de ``prix_unitaire``/``prix_ligne``.
``taux_marge`` n'est JAMAIS codé en dur ici : c'est un paramètre obligatoire de ``creer_devis``,
fourni par l'appelant (explicitement, ou par une future configuration d'entreprise que l'appelant
aura lue) ; son absence est un rejet fail-closed (``REJ-DEVIS-TAUX-MARGE-MANQUANT``), jamais une
valeur par défaut inventée.

Chaque ligne porte aussi ``reference_ligne`` (``f"{devis_id}-L{index}"``, calculé une fois à la
création, jamais recalculé), un identifiant stable qui permet à M5 de relier chaque ligne de
facture à sa ligne de devis d'origine — même rôle que ``reference_ligne_devis`` côté
``facturation.LigneFacture``.

Ce module est DISTINCT de ``devis.py`` (qui assemble le contrat gelé interne ``EstimationV1`` —
mesure/Monte Carlo, S007) : le « devis » de PLAN T2.3-a est un document commercial multi-lignes
(description, quantité, unité, coût, référence de besoin matériau) lu par M4 (``devis_id`` du WCT)
et M5 (source des lignes de facture). Les deux modules partagent le mot « devis » par cohérence
produit (DEFINITION-PRODUIT.md §5/§6/§7-M3), pas de code.

Registre : comme ``facturation.py`` de M5 (même patron), ce module ne construit ni n'importe de
registre — il reçoit un ``registre_cible`` déjà construit, duck-typé (itérable, ``append``) : une
liste Python en mémoire dans les tests unitaires, ``opsys.stockage.maillons("m03-estimation",
"devis")`` en production (choix de ``outils.py`` seul, via ``registre_devis_production()``).
DÉLIBÉRÉMENT distinct du registre "principal" (``registre.py``/``registre_production()``) : celui-ci
porte les charges d'ESTIMATION Monte Carlo (S008, six clés fixes dont ``niveau_confiance``/
``bareme_version``/``graine_monte_carlo``, hash-chaînées) — un devis commercial n'a aucune de ces
clés et forcer ce contrat pour lui inventerait des valeurs sans rapport (fail-closed interdit
d'inventer). ``opsys.stockage.maillons`` accepte nativement plusieurs collections nommées par
département (M5 fait de même : "principal" pour les mouvements, "factures" pour les factures) —
"devis" est la collection propre à ce module, jamais mélangée à "principal".

Chaque devis vit comme une petite suite d'événements append-only : un maillon ``devis_cree`` puis,
à chaque transition, un maillon ``transition_devis`` — l'état courant d'un devis est la fusion de
ces maillons dans l'ordre (``_etats_courants``), jamais seulement le dernier maillon (un champ posé
à la création, ex. ``lignes``, doit rester visible après une transition).

Idempotence de la création (``creer_devis``) : par ``devis_id``, au sens d'ADR-0009 (cf.
``evenements.publier(evenement_id=...)``) — un second appel avec le MÊME ``devis_id`` et le MÊME
contenu est un no-op qui rend l'état déjà existant, sans écrire de second maillon (rejeu sûr après
une panne réseau) ; un second appel avec le même ``devis_id`` mais un contenu DIFFÉRENT est un rejet
nommé (``REJ-DEVIS-ID-DEJA-UTILISE``) : deux devis distincts n'ont jamais le même identifiant.

Statuts (PLAN T2.3-a) : ``brouillon`` -> ``envoye`` -> ``accepte``. ``refuse``/``expire`` ne sont
PAS ajoutés ici : DEFINITION-PRODUIT.md ne les justifie pas pour CE contrat (M2.8 parle de « raison
de perte » côté pipeline CRM de M2, pas du document M3 lui-même) — à ajouter plus tard avec un
mandat qui les justifie explicitement, jamais par anticipation. ``marquer_devis_accepte`` accepte un
devis ``brouillon`` OU ``envoye`` (pas seulement ``envoye``) : l'ENVOI n'est pas exposé comme outil
avant T1.3 (approbations du socle), donc exiger ``envoye`` rendrait ``m3_marquer_devis_accepte``
inutilisable en pratique aujourd'hui — alors qu'un humain peut constater une acceptation réelle
(signature, courriel, appel) même quand OPSYS n'a pas encore tracé l'envoi formel. Réaccepter un
devis déjà ``accepte`` reste un rejet nommé (``REJ-DEVIS-TRANSITION-ILLEGALE``), comme les
transitions de ``facturation.py`` (M5) : pas de no-op silencieux sur une transition, seule la
CRÉATION est idempotente (PLAN T2.3-a ne demande l'idempotence que pour ``creer_devis``).

Séparation coût/prix (audit M3, docs/departements/M3-audit.md §2.1) : ``projeter_devis(devis,
role="employe")`` retire ``cout_unitaire``, ``cout_ligne``, ``cout_total``, ``taux_marge`` ET
``prix_unitaire``/``prix_ligne``/``prix_total`` — pas seulement le coût et la marge au sens strict.
Motif : si l'employé connaît (ou devine) le coût réel des matériaux/main-d'œuvre qu'il pose, lui
montrer le PRIX suffit à lui laisser déduire la marge par soustraction ; cacher le coût sans cacher
le prix ne protégerait donc rien. La vue "employe" ne garde que ce qui sert le travail terrain :
référence de ligne, description, quantité, unité, référence de besoin matériau, plus l'identité et
le statut du devis. L'événement ``m3.devis_accepte`` (``charge_evenement_devis_accepte``) suit la
même règle par ligne : ``prix_unitaire``/``prix_ligne`` y figurent (M5 en a besoin pour facturer),
mais jamais ``cout_unitaire``/``cout_ligne`` — M6, qui consomme cet événement pour ses besoins
matériaux prévus, planifie des quantités, jamais des montants.
"""

from __future__ import annotations

import copy
import dataclasses
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from . import verdicts

__all__ = [
    "STATUTS_DEVIS",
    "LigneDevis",
    "charge_evenement_devis_accepte",
    "creer_devis",
    "lire_devis",
    "marquer_devis_accepte",
    "marquer_devis_envoye",
    "projeter_devis",
]

_DEUX_DECIMALES = Decimal("0.01")

STATUTS_DEVIS = ("brouillon", "envoye", "accepte")
_STATUTS_AVANT_ENVOI = ("brouillon",)
_STATUTS_AVANT_ACCEPTATION = ("brouillon", "envoye")

_CHAMPS_LIGNE_REQUIS = frozenset(
    {"description", "quantite", "unite", "cout_unitaire", "reference_besoin_materiau"}
)
_CLES_CONTENU_DEVIS = ("lead_id", "chantier_id", "taux_marge", "lignes", "cout_total", "prix_total")

_ROLES_CONNUS = ("interne", "employe")
_CLES_LIGNE_EMPLOYE = ("reference_ligne", "description", "quantite", "unite", "reference_besoin_materiau")
_CLES_DEVIS_EMPLOYE = ("devis_id", "lead_id", "chantier_id", "statut", "horodatage")


@dataclasses.dataclass(frozen=True)
class LigneDevis:
    """Une ligne de devis. ``quantite``/``cout_unitaire`` sont des ``Decimal`` déjà validés (texte
    en entrée, jamais un float). ``reference_ligne`` est un identifiant stable calculé une fois
    (``f"{devis_id}-L{index}"``). ``cout_ligne``, ``prix_unitaire`` et ``prix_ligne`` (2 décimales
    chacun) sont calculés une fois par ``_valider_ligne`` — voir la docstring du module pour
    l'ordre précis des deux arrondis de prix — et conservés ici, jamais recalculés à la volée."""

    reference_ligne: str
    description: str
    quantite: Decimal
    unite: str
    cout_unitaire: Decimal
    reference_besoin_materiau: str | None
    cout_ligne: Decimal
    prix_unitaire: Decimal
    prix_ligne: Decimal


def _est_texte_non_vide(valeur: Any) -> bool:
    return isinstance(valeur, str) and valeur.strip() != ""


def _texte_vers_decimal(valeur: Any, nom_champ: str, code_erreur: str) -> tuple[Decimal | None, dict | None]:
    if not isinstance(valeur, str):
        return None, verdicts.construire_verdict(
            code_erreur, detail=f"{nom_champ} doit être fourni en texte décimal (jamais un nombre JSON)"
        )
    try:
        decimal_valeur = Decimal(valeur)
    except InvalidOperation:
        return None, verdicts.construire_verdict(code_erreur, detail=f"{nom_champ} décimal invalide : {valeur!r}")
    if not decimal_valeur.is_finite():
        return None, verdicts.construire_verdict(code_erreur, detail=f"{nom_champ} doit être fini")
    return decimal_valeur, None


def _texte_vers_taux_marge(taux_marge: Any) -> tuple[Decimal | None, dict | None]:
    """``taux_marge`` n'est jamais codé en dur ni déduit : son absence est un rejet fail-closed."""
    if taux_marge is None:
        return None, verdicts.construire_verdict(
            "REJ-DEVIS-TAUX-MARGE-MANQUANT",
            detail="taux_marge requis (entrée explicite ou configuration de l'entreprise), jamais codé en dur",
        )
    taux, verdict = _texte_vers_decimal(taux_marge, "taux_marge", "REJ-DEVIS-TAUX-MARGE-INVALIDE")
    if verdict is not None:
        return None, verdict
    if taux <= Decimal("-1"):
        return None, verdicts.construire_verdict(
            "REJ-DEVIS-TAUX-MARGE-INVALIDE", detail=f"taux_marge doit être strictement supérieur à -1 (donné : {taux})"
        )
    return taux, None


def _valider_ligne(
    brute: Any, index: int, taux_marge: Decimal, devis_id: str
) -> tuple[LigneDevis | None, dict | None]:
    if not isinstance(brute, dict) or set(brute.keys()) != _CHAMPS_LIGNE_REQUIS:
        return None, verdicts.construire_verdict(
            "REJ-DEVIS-LIGNE-INVALIDE",
            detail=f"ligne {index} : structure invalide (clés attendues {sorted(_CHAMPS_LIGNE_REQUIS)})",
        )
    for champ in ("description", "unite"):
        if not _est_texte_non_vide(brute[champ]):
            return None, verdicts.construire_verdict(
                "REJ-DEVIS-LIGNE-INVALIDE", detail=f"ligne {index} : champ {champ!r} requis, non vide"
            )

    reference = brute["reference_besoin_materiau"]
    if reference is not None and not _est_texte_non_vide(reference):
        return None, verdicts.construire_verdict(
            "REJ-DEVIS-LIGNE-INVALIDE",
            detail=f"ligne {index} : reference_besoin_materiau doit être une chaîne non vide ou None",
        )

    quantite, verdict = _texte_vers_decimal(brute["quantite"], f"ligne {index} quantite", "REJ-DEVIS-LIGNE-INVALIDE")
    if verdict is not None:
        return None, verdict
    if quantite <= 0:
        return None, verdicts.construire_verdict(
            "REJ-DEVIS-LIGNE-INVALIDE", detail=f"ligne {index} : quantite doit être strictement positive"
        )

    cout_unitaire, verdict = _texte_vers_decimal(
        brute["cout_unitaire"], f"ligne {index} cout_unitaire", "REJ-DEVIS-LIGNE-INVALIDE"
    )
    if verdict is not None:
        return None, verdict
    if cout_unitaire < 0:
        return None, verdicts.construire_verdict(
            "REJ-DEVIS-LIGNE-INVALIDE", detail=f"ligne {index} : cout_unitaire ne peut pas être négatif"
        )

    # Coût et prix (PLAN T2.3-a/b — voir la docstring du module pour la justification complète de
    # l'ordre des arrondis). cout_ligne est indépendant du prix : cout_unitaire x quantite, arrondi
    # une fois. prix_unitaire = cout_unitaire x (1 + taux_marge), arrondi ROUND_HALF_UP au cent
    # D'ABORD (jamais depuis cout_ligne) ; prix_ligne = CE prix_unitaire déjà arrondi x quantite,
    # arrondi une seconde fois — exactement l'ordre que la facture M5 rejouera plus tard depuis le
    # seul prix_unitaire qu'elle connaît (montant = quantite x prix_unitaire, arrondi une fois).
    cout_ligne = (cout_unitaire * quantite).quantize(_DEUX_DECIMALES, rounding=ROUND_HALF_UP)
    prix_unitaire = (cout_unitaire * (Decimal("1") + taux_marge)).quantize(_DEUX_DECIMALES, rounding=ROUND_HALF_UP)
    prix_ligne = (prix_unitaire * quantite).quantize(_DEUX_DECIMALES, rounding=ROUND_HALF_UP)

    ligne = LigneDevis(
        reference_ligne=f"{devis_id}-L{index}",
        description=brute["description"],
        quantite=quantite,
        unite=brute["unite"],
        cout_unitaire=cout_unitaire,
        reference_besoin_materiau=reference,
        cout_ligne=cout_ligne,
        prix_unitaire=prix_unitaire,
        prix_ligne=prix_ligne,
    )
    return ligne, None


def _contenu_equivalent(existant: dict[str, Any], candidat: dict[str, Any]) -> bool:
    return all(existant.get(cle) == candidat.get(cle) for cle in _CLES_CONTENU_DEVIS)


def _ajouter(entree: dict[str, Any], registre_cible: Any) -> dict[str, Any]:
    """Ajoute une copie PROFONDE de ``entree`` au registre et en retourne une seconde, indépendante
    (même précaution que ``registre.py``/M5 : ni le maillon stocké ni le résultat rendu à
    l'appelant ne doivent partager une structure mutable, ex. la liste ``lignes``)."""
    registre_cible.append(copy.deepcopy(entree))
    return copy.deepcopy(entree)


def _etats_courants(registre_cible: Any) -> dict[str, dict[str, Any]]:
    """État courant de chaque devis connu de ``registre_cible`` : une fusion, dans l'ordre du
    registre, de son maillon ``devis_cree`` puis de chacun de ses ``transition_devis`` — pas
    seulement le dernier maillon, pour qu'un champ posé à la création (ex. ``lignes``) reste
    visible après une transition ultérieure (ex. l'acceptation)."""
    etats: dict[str, dict[str, Any]] = {}
    for maillon in registre_cible:
        type_entree = maillon.get("type_entree")
        devis_id = maillon.get("devis_id")
        if type_entree == "devis_cree":
            etats[devis_id] = dict(maillon)
        elif type_entree == "transition_devis" and devis_id in etats:
            etats[devis_id] = {**etats[devis_id], **maillon}
    return etats


def _etat_devis(registre_cible: Any, devis_id: str) -> dict[str, Any] | None:
    return _etats_courants(registre_cible).get(devis_id)


def creer_devis(
    devis_id: str,
    lead_id: str,
    chantier_id: str | None,
    lignes: list[dict[str, Any]],
    taux_marge: str | None,
    horodatage: str,
    registre_cible: Any,
    prix_total_fourni: str | None = None,
) -> tuple[dict[str, Any] | None, dict | None]:
    """Crée un devis BROUILLON sur ``registre_cible`` (le registre DÉDIÉ des devis). Idempotente
    par ``devis_id`` (cf. docstring du module) : un contenu identique rend l'existant sans écrire,
    un contenu différent est un rejet nommé."""
    if not _est_texte_non_vide(devis_id):
        return None, verdicts.construire_verdict("REJ-DEVIS-DEVIS-ID-VIDE", detail="devis_id requis, non vide")
    if not _est_texte_non_vide(lead_id):
        return None, verdicts.construire_verdict("REJ-DEVIS-LEAD-ID-VIDE", detail="lead_id requis, non vide")
    if chantier_id is not None and not _est_texte_non_vide(chantier_id):
        return None, verdicts.construire_verdict(
            "REJ-DEVIS-CHANTIER-ID-INVALIDE", detail="chantier_id doit être une chaîne non vide ou None"
        )
    if not _est_texte_non_vide(horodatage):
        return None, verdicts.construire_verdict("REJ-DEVIS-HORODATAGE-VIDE", detail="horodatage requis, non vide")
    if not isinstance(lignes, (list, tuple)) or not lignes:
        return None, verdicts.construire_verdict("REJ-DEVIS-LIGNES-VIDES", detail="au moins une ligne est requise")

    taux, verdict = _texte_vers_taux_marge(taux_marge)
    if verdict is not None:
        return None, verdict

    lignes_validees: list[LigneDevis] = []
    cout_total = Decimal("0")
    prix_total = Decimal("0")
    for index, brute in enumerate(lignes):
        ligne, verdict = _valider_ligne(brute, index, taux, devis_id)
        if verdict is not None:
            return None, verdict
        lignes_validees.append(ligne)
        # Totaux = SOMME des montants de ligne déjà arrondis (jamais un nouvel arrondi de la
        # somme) : la somme de valeurs à exactement 2 décimales reste exacte à 2 décimales.
        cout_total += ligne.cout_ligne
        prix_total += ligne.prix_ligne

    if prix_total_fourni is not None:
        fourni, verdict = _texte_vers_decimal(prix_total_fourni, "prix_total", "REJ-DEVIS-TOTAL-INCOHERENT")
        if verdict is not None:
            return None, verdict
        if fourni != prix_total:
            return None, verdicts.construire_verdict(
                "REJ-DEVIS-TOTAL-INCOHERENT",
                detail=(
                    f"prix_total fourni ({fourni}) diffère du total recalculé depuis les lignes ({prix_total})"
                ),
            )

    candidat = {
        "devis_id": devis_id,
        "lead_id": lead_id,
        "chantier_id": chantier_id,
        "lignes": [dataclasses.asdict(ligne) for ligne in lignes_validees],
        "taux_marge": taux,
        "cout_total": cout_total,
        "prix_total": prix_total,
    }

    existant = _etat_devis(registre_cible, devis_id)
    if existant is not None:
        if _contenu_equivalent(existant, candidat):
            return existant, None
        return None, verdicts.construire_verdict(
            "REJ-DEVIS-ID-DEJA-UTILISE",
            detail=f"devis_id {devis_id!r} déjà créé avec un contenu différent",
        )

    entree = {**candidat, "type_entree": "devis_cree", "statut": "brouillon", "horodatage": horodatage}
    return _ajouter(entree, registre_cible), None


def lire_devis(registre_cible: Any, devis_id: str) -> tuple[dict[str, Any] | None, dict | None]:
    """Lit l'état courant (fusion de tous ses maillons) d'un devis par ``devis_id``."""
    if not _est_texte_non_vide(devis_id):
        return None, verdicts.construire_verdict("REJ-DEVIS-DEVIS-ID-VIDE", detail="devis_id requis, non vide")
    etat = _etat_devis(registre_cible, devis_id)
    if etat is None:
        return None, verdicts.construire_verdict("REJ-DEVIS-INTROUVABLE", detail=f"devis inconnu : {devis_id!r}")
    return etat, None


def marquer_devis_envoye(
    devis_id: str, horodatage: str, registre_cible: Any
) -> tuple[dict[str, Any] | None, dict | None]:
    """brouillon -> envoye. Pas d'outil agent exposé pour cette transition à ce stade (SOUL.md,
    PLAN T2.3-a) : l'ENVOI réel au client est une action externe qui ira derrière les approbations
    du socle en T1.3. Fonction gardée ici pour que la machine à états soit complète et testable
    dès maintenant, comme ``facturation.envoyer_facture``/``marquer_facture_payee`` chez M5."""
    if not _est_texte_non_vide(horodatage):
        return None, verdicts.construire_verdict("REJ-DEVIS-HORODATAGE-VIDE", detail="horodatage requis, non vide")
    etat = _etat_devis(registre_cible, devis_id)
    if etat is None:
        return None, verdicts.construire_verdict("REJ-DEVIS-INTROUVABLE", detail=f"devis inconnu : {devis_id!r}")
    if etat["statut"] not in _STATUTS_AVANT_ENVOI:
        return None, verdicts.construire_verdict(
            "REJ-DEVIS-TRANSITION-ILLEGALE",
            detail=f"devis {devis_id!r} au statut {etat['statut']!r}, {_STATUTS_AVANT_ENVOI} requis avant l'envoi",
        )
    entree = {"type_entree": "transition_devis", "devis_id": devis_id, "statut": "envoye", "horodatage": horodatage}
    _ajouter(entree, registre_cible)
    # Rend l'état COURANT (fusion de tous les maillons, cf. _etats_courants), jamais le seul
    # maillon de transition qui vient d'être écrit : les champs posés à la création (lignes,
    # totaux, taux_marge, lead_id, chantier_id) doivent rester visibles après la transition.
    return _etat_devis(registre_cible, devis_id), None


def marquer_devis_accepte(
    devis_id: str, approbateur: str, horodatage: str, registre_cible: Any
) -> tuple[dict[str, Any] | None, dict | None]:
    """(brouillon | envoye) -> accepte. Frontière humaine T3 (AGENTS.md : « engagements externes :
    humain seul ») : ``approbateur`` doit être une chaîne non vide, un humain qui CONSTATE
    l'acceptation réelle du client (signature, courriel, appel) — jamais déduite. Réaccepter un
    devis déjà ``accepte`` est un rejet nommé, pas un no-op (cf. docstring du module)."""
    if not _est_texte_non_vide(horodatage):
        return None, verdicts.construire_verdict("REJ-DEVIS-HORODATAGE-VIDE", detail="horodatage requis, non vide")
    if not _est_texte_non_vide(approbateur):
        return None, verdicts.construire_verdict(
            "REJ-DEVIS-APPROBATEUR-ABSENT",
            detail="approbateur humain requis, non vide : un humain doit constater l'acceptation du client",
        )
    etat = _etat_devis(registre_cible, devis_id)
    if etat is None:
        return None, verdicts.construire_verdict("REJ-DEVIS-INTROUVABLE", detail=f"devis inconnu : {devis_id!r}")
    if etat["statut"] not in _STATUTS_AVANT_ACCEPTATION:
        return None, verdicts.construire_verdict(
            "REJ-DEVIS-TRANSITION-ILLEGALE",
            detail=(
                f"devis {devis_id!r} au statut {etat['statut']!r}, "
                f"{_STATUTS_AVANT_ACCEPTATION} requis avant acceptation"
            ),
        )
    entree = {
        "type_entree": "transition_devis",
        "devis_id": devis_id,
        "statut": "accepte",
        "approbateur": approbateur,
        "horodatage": horodatage,
    }
    _ajouter(entree, registre_cible)
    # Rend l'état COURANT, pas le seul maillon de transition : outils.py a besoin de lignes/
    # lead_id/chantier_id/cout_total/prix_total/taux_marge pour construire la charge de
    # l'événement m3.devis_accepte (charge_evenement_devis_accepte), qu'un maillon de transition
    # seul ne porte pas.
    return _etat_devis(registre_cible, devis_id), None


def projeter_devis(devis: dict[str, Any] | None, role: str) -> tuple[dict[str, Any] | None, dict | None]:
    """Projection par rôle (audit M3 §2.1/§2.6, séparation coût/prix). ``role="interne"`` (défaut
    des appelants internes) rend la vue complète ; ``role="employe"`` retire coût, marge ET prix
    (cf. docstring du module — cacher un seul des deux ne protège pas la marge)."""
    if role not in _ROLES_CONNUS:
        return None, verdicts.construire_verdict(
            "REJ-DEVIS-ROLE-INCONNU", detail=f"role inconnu : {role!r}, attendu {_ROLES_CONNUS}"
        )
    if devis is None:
        return None, verdicts.construire_verdict("REJ-DEVIS-INTROUVABLE", detail="aucun devis à projeter")
    if role == "interne":
        return dict(devis), None

    lignes_redigees = [
        {cle: ligne.get(cle) for cle in _CLES_LIGNE_EMPLOYE} for ligne in devis.get("lignes", ())
    ]
    projection = {cle: devis.get(cle) for cle in _CLES_DEVIS_EMPLOYE}
    projection["lignes"] = lignes_redigees
    return projection, None


def charge_evenement_devis_accepte(devis: dict[str, Any]) -> dict[str, Any]:
    """Construit la charge de l'événement ``m3.devis_accepte`` (catalogue
    ``opsys.evenements.catalogue/m3.devis_accepte.json``) depuis l'état courant d'un devis déjà
    ACCEPTE. Ne publie rien elle-même — module pur : c'est ``outils.py``, seul, qui appelle
    ``opsys.evenements.publier`` après une acceptation réussie, dans la même transaction. Tous les
    montants sont convertis en texte décimal (jamais un float JSON).

    PLAN T2.3-b : porte ce qu'il faut pour que M5 facture sans rien recalculer différemment —
    ``reference_ligne``/``prix_unitaire``/``prix_ligne`` par ligne (jamais ``cout_unitaire``/
    ``cout_ligne`` : séparation coût/prix, audit M3 §2.1), et ``horodatage_acceptation`` (celui
    fourni à ``marquer_devis_accepte``, déjà le ``horodatage`` du dernier maillon fusionné — voir
    ``_etats_courants`` — donc TOUJOURS celui de l'acceptation, jamais celui d'une création ou
    d'un envoi antérieurs)."""
    return {
        "devis_id": devis["devis_id"],
        "lead_id": devis["lead_id"],
        "chantier_id": devis["chantier_id"],
        "lignes": [
            {
                "reference_ligne": ligne["reference_ligne"],
                "description": ligne["description"],
                "quantite": str(ligne["quantite"]),
                "unite": ligne["unite"],
                "prix_unitaire": str(ligne["prix_unitaire"]),
                "prix_ligne": str(ligne["prix_ligne"]),
                "reference_besoin_materiau": ligne["reference_besoin_materiau"],
            }
            for ligne in devis["lignes"]
        ],
        "cout_total": str(devis["cout_total"]),
        "prix_total": str(devis["prix_total"]),
        "taux_marge": str(devis["taux_marge"]),
        "horodatage_acceptation": devis["horodatage"],
    }
