"""Moteur de bons de commande (PO) PERSISTÉS de M6 (M6.5, PLAN T2.5 point 1).

Lève DA-M6-12 (``docs/bmad/03-ARCHITECTURE.md``, « M6 ne persiste PAS les PO ») : DA-M6-12
contredisait DEFINITION-PRODUIT.md §7 M6.5, qui nomme une machine à 12 statuts pour le PO — une
machine à états ne peut pas exister sur un objet reconstruit à chaque appel sans jamais être
gardé. DA-M6-12 est remplacée ci-dessous (raison complète : ``docs/bmad/03-ARCHITECTURE.md``,
section DA-M6-12 révisée).

Un PO vit comme une petite suite d'événements append-only, EXACTEMENT le patron de
``m3_estimation.devis_durable`` (copie-adaptation, #109) : un maillon ``po_cree`` puis, à chaque
transition, un maillon ``transition_po`` — l'état courant d'un PO est la fusion de ces maillons
dans l'ordre (``_etats_courants``), jamais seulement le dernier maillon.

``registre_cible`` (le PO) est duck-typé (itérable, ``append``), comme partout dans ce paquet :
une liste Python en mémoire dans les tests, ``opsys.stockage.maillons("m06-material-control",
"bons_commande")`` en production (choix d'``outils.py`` seul). DISTINCT du registre de mouvements
de stock (``registre.py``, hash-chaîné, ``type_mouvement`` ∈ {RECEPTION, CONSOMMATION, ...}) : un
PO n'est PAS un mouvement de stock, c'est un document à cycle de vie propre — aucun hash-chaînage
ici (même choix que ``devis_durable.py``/``facturation.py``, qui n'en portent pas non plus ; la
protection contre l'altération vit dans la garantie append-only de ``opsys.stockage`` elle-même,
pas dans un hash applicatif supplémentaire).

Module pur (AGENTS.md, ADR-0009) : aucun import ``opsys``/SQLAlchemy, aucune horloge interne
(``horodatage`` toujours fourni par l'appelant, jamais ``datetime.now()``), aucun ``uuid``
(``po_id`` toujours fourni par l'appelant), aucun aléa, aucun réseau — y compris pour
``marquer_envoye`` : AUCUNE primitive d'envoi de courriel n'existe dans ce module (PLAN T2.5
point 3, « aucun envoi réel de courriel ici (M1 plus tard, repli manuel documenté) »).

Prix : chaque ligne résout son prix ATTENDU depuis ``livre_prix.py`` (PLAN T2.4) au moment de la
création — jamais un prix inventé. Une ligne sans prix au livre reste ``INDETERMINE``
(``verdict_prix``) : le PO BROUILLON peut exister ainsi (visible, pas bloquant), mais
``approuver`` refuse fail-closed tant qu'un prix reste indéterminé (PLAN T2.4, « le prix d'un PO
vient du livre de prix en vigueur OU D'UN VERDICT QUI LE DEMANDE » — le verdict doit être résolu
avant l'engagement).

Fournisseur : ``creer_brouillon`` exige un ``fournisseur_id`` qui référence une fiche déjà
enregistrée dans ``fournisseurs.py`` (PLAN T2.5 point 2) — corrige le trou mesuré par l'audit M6
(« ``BonDeCommandeDemande`` n'a aucun champ fournisseur »).

Envoi (N4) : ``marquer_envoye`` ne reçoit AUCUN paramètre d'approbateur — contrairement à
``devis_durable.marquer_devis_accepte`` (frontière humaine T3 explicite dans la fonction), ce
module suit le patron ``m5_financecore.facturation.envoyer_facture`` : la décision d'approuver
appartient EXCLUSIVEMENT au socle (N4, ``opsys.approbations.decider``, ``department.yaml`` de M6,
bloc ``approbations.n4``) — la fonction elle-même ne s'exécute qu'une fois cette décision prise
(``opsys.capacites.Capacites.appeler``/``executer_atomique``, point de passage unique), donc elle
n'a rien de plus à vérifier ici : lui ajouter un paramètre ``approbateur`` dupliquerait une
garantie déjà tenue ailleurs, sans rien renforcer.

Réception : ``enregistrer_reception_po`` NE RECALCULE RIEN — elle reçoit le ``verdict_reception``
déjà calculé par ``reception.py``/``materiel.enregistrer_reception`` (réutilisés SANS
modification, audit M6 §5 Phase 1 tâche 9) et se contente d'y attacher la transition de statut du
PO persisté (reçue partielle ou complète, PLAN T2.5 point 4).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from typing import Any

from . import contrats, fournisseurs, frontieres, livre_prix, stock, verdicts

__all__ = [
    "calculer_lignes_a_commander",
    "construire_bon_demande",
    "creer_brouillon",
    "approuver",
    "annuler",
    "generer_courriel",
    "marquer_envoye",
    "enregistrer_reception_po",
    "peut_recevoir",
    "detecter_ecarts_prix",
    "lire",
    "lister",
    "transition_autorisee",
]

# Statuts depuis lesquels une réception peut s'attacher (PLAN T2.5 point 4) : supplier_confirmed
# n'a encore aucun outil dédié (comme pending_admin_review/email_ready avant approbation, voir
# contrats.TRANSITIONS_PO) — recevoir directement depuis sent_to_supplier est le même raccourci
# documenté que draft -> approved.
_STATUTS_AVANT_RECEPTION = frozenset({"sent_to_supplier", "supplier_confirmed", "partially_received"})
_CLES_CONTENU_PO = ("chantier_id", "fournisseur_id", "lignes", "montant_total_prevu")


def _texte_non_vide(valeur: Any) -> bool:
    return isinstance(valeur, str) and valeur.strip() != ""


def _quantite_positive_finie(valeur: Any) -> bool:
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        return False
    if isinstance(valeur, float) and not math.isfinite(valeur):
        return False
    return valeur > 0


def calculer_lignes_a_commander(
    besoins_estimes: Iterable[Mapping[str, Any]], chantier_id: Any, registre_mouvements: Any
) -> list[dict[str, Any]]:
    """Les lignes à commander (PLAN T2.5 point 3) : pour chaque besoin PRÉVU (``besoins_prevus.py``,
    source ``m3.devis_accepte``), l'écart entre la quantité estimée et le stock déjà disponible
    pour ce chantier (``stock.deriver_stock_theorique``, réutilisé SANS modification). Un matériau
    déjà entièrement couvert par le stock disponible n'apparaît PAS ici — jamais une ligne à
    quantité nulle ou négative. Pure : aucune écriture, aucun ``po_id`` construit ici."""
    lignes: list[dict[str, Any]] = []
    for besoin in besoins_estimes:
        materiau_id = besoin["materiau_id"]
        quantite_estimee = besoin["quantite_estimee"]
        disponible = stock.deriver_stock_theorique(chantier_id, materiau_id, registre_mouvements)
        ecart = quantite_estimee - disponible
        if ecart > 0:
            lignes.append({"materiau_id": materiau_id, "quantite_demandee": ecart})
    return lignes


def _valider_ligne_po(ligne: Any) -> tuple[bool, str | None]:
    if not isinstance(ligne, dict) or set(ligne.keys()) != contrats.CHAMPS_LIGNE_PO:
        return False, "REJ-PO-LIGNE-INVALIDE"
    if not _texte_non_vide(ligne.get("materiau_id")):
        return False, "REJ-PO-LIGNE-INVALIDE"
    if not _quantite_positive_finie(ligne.get("quantite_demandee")):
        return False, "REJ-PO-LIGNE-INVALIDE"
    return True, None


def _etats_courants(registre_cible: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """État courant de chaque PO connu : fusion, dans l'ordre du registre, de son maillon
    ``po_cree`` puis de chacun de ses ``transition_po`` (copie-adaptation de
    ``m3_estimation.devis_durable._etats_courants``, #109)."""
    etats: dict[str, dict[str, Any]] = {}
    for maillon in registre_cible:
        type_entree = maillon.get("type_entree")
        po_id = maillon.get("po_id")
        if type_entree == "po_cree":
            etats[po_id] = dict(maillon)
        elif type_entree == "transition_po" and po_id in etats:
            etats[po_id] = {**etats[po_id], **maillon}
    return etats


def lire(registre_cible: Iterable[Mapping[str, Any]], po_id: Any) -> dict[str, Any] | None:
    if not _texte_non_vide(po_id):
        return None
    return _etats_courants(registre_cible).get(po_id)


def lister(registre_cible: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Tous les PO connus (état courant de chacun), triés par ``po_id`` pour un ordre
    déterministe — aucune horloge, aucun tri par date."""
    return [etat for _, etat in sorted(_etats_courants(registre_cible).items())]


def transition_autorisee(statut_actuel: Any, statut_cible: Any) -> bool:
    """La machine à 12 statuts (DEFINITION-PRODUIT.md §7 M6.5, ``contrats.TRANSITIONS_PO``) :
    vrai si ``statut_cible`` est une transition légale depuis ``statut_actuel``. Fonction pure,
    table figée — aucun statut inconnu n'est jamais autorisé (``frozenset()`` par défaut)."""
    return statut_cible in contrats.TRANSITIONS_PO.get(statut_actuel, frozenset())


def construire_bon_demande(po: Mapping[str, Any]) -> dict[str, Any]:
    """Dérive un ``BonDeCommandeDemande`` (contrat gelé RECEPTION, §2.4 architecture, INCHANGÉ)
    depuis l'état courant d'un PO persisté — pour que ``materiel.enregistrer_reception`` (réutilisé
    sans modification, DA-M6-12 révisée) reçoive exactement la forme qu'il a toujours acceptée.
    ``horodatage`` reprend celui de la CRÉATION du PO (le bon a été fait à ce moment-là ;
    ``ReceptionPO.horodatage``, séparé, porte la date de la réception elle-même)."""
    return {
        "po_id": po["po_id"],
        "chantier_id": po["chantier_id"],
        "lignes_demandees": [
            {"materiau_id": ligne["materiau_id"], "quantite_demandee": ligne["quantite_demandee"]}
            for ligne in po["lignes"]
        ],
        "horodatage": po["horodatage"],
    }


def bon_demande_correspond(po: Mapping[str, Any], bon_demande: Mapping[str, Any]) -> bool:
    """Vrai si ``bon_demande`` (fourni à la réception) correspond exactement au PO persisté :
    même ``chantier_id``, mêmes lignes (matériau + quantité demandée), peu importe l'ordre. Défend
    contre un ``bon_demande`` forgé ou modifié référençant le ``po_id`` d'un vrai PO."""
    if po["chantier_id"] != bon_demande.get("chantier_id"):
        return False
    lignes_po = {(ligne["materiau_id"], ligne["quantite_demandee"]) for ligne in po["lignes"]}
    lignes_bon = {
        (ligne.get("materiau_id"), ligne.get("quantite_demandee"))
        for ligne in bon_demande.get("lignes_demandees", ())
    }
    return lignes_po == lignes_bon


def creer_brouillon(
    po_id: Any,
    chantier_id: Any,
    fournisseur_id: Any,
    lignes_demandees: Any,
    horodatage: Any,
    registre_po: Any,
    registre_prix: Any,
    registre_fournisseurs: Any,
) -> tuple[dict[str, Any] | None, dict | None]:
    """Crée un PO BROUILLON (statut ``draft``, PLAN T2.5 point 3) : matériau + quantité fournis
    par l'appelant (typiquement ``calculer_lignes_a_commander``), prix ATTENDU résolu ligne par
    ligne depuis ``livre_prix.resoudre_prix_po`` (PLAN T2.4, jamais inventé). Idempotent par
    ``po_id`` : un contenu identique (même chantier, même fournisseur, mêmes lignes, MÊME prix
    résolu) rend l'existant sans écrire ; un contenu différent (y compris un prix qui a changé
    entre-temps au livre) est un rejet nommé — deux PO distincts n'ont jamais le même identifiant."""
    if not _texte_non_vide(po_id):
        return None, verdicts.construire_verdict("REJ-PO-ID-VIDE", detail="po_id requis, non vide")
    if not _texte_non_vide(chantier_id):
        return None, verdicts.construire_verdict("REJ-PO-CHANTIER-VIDE", detail="chantier_id requis, non vide")
    if not _texte_non_vide(fournisseur_id):
        return None, verdicts.construire_verdict(
            "REJ-PO-FOURNISSEUR-VIDE", detail="fournisseur_id requis, non vide"
        )
    if not _texte_non_vide(horodatage):
        return None, verdicts.construire_verdict("REJ-PO-HORODATAGE-VIDE", detail="horodatage requis, non vide")
    if not isinstance(lignes_demandees, list) or not lignes_demandees:
        return None, verdicts.construire_verdict(
            "REJ-PO-LIGNES-VIDES", detail="au moins une ligne à commander est requise"
        )

    ok, code = frontieres.verifier_frontieres(
        {"chantier_id": chantier_id, "fournisseur_id": fournisseur_id, "lignes_demandees": lignes_demandees}
    )
    if not ok:
        return None, verdicts.construire_verdict(code)

    materiaux_vus: set[str] = set()
    for ligne in lignes_demandees:
        ok, code = _valider_ligne_po(ligne)
        if not ok:
            return None, verdicts.construire_verdict(code)
        if ligne["materiau_id"] in materiaux_vus:
            return None, verdicts.construire_verdict(
                "REJ-PO-LIGNE-DUPLIQUEE", detail=f"matériau en double : {ligne['materiau_id']!r}"
            )
        materiaux_vus.add(ligne["materiau_id"])

    if fournisseurs.lire_fournisseur(registre_fournisseurs, fournisseur_id) is None:
        return None, verdicts.construire_verdict(
            "REJ-PO-FOURNISSEUR-INCONNU",
            detail=f"fournisseur {fournisseur_id!r} non enregistré (m6_enregistrer_fournisseur d'abord)",
        )

    lignes: list[dict[str, Any]] = []
    montants_lignes: list[float | None] = []
    for ligne in lignes_demandees:
        materiau_id = ligne["materiau_id"]
        quantite_demandee = ligne["quantite_demandee"]
        resolution = livre_prix.resoudre_prix_po(materiau_id, fournisseur_id, registre_prix)
        prix_unitaire_prevu = resolution["prix_unitaire"]
        montant_ligne_prevu = (
            prix_unitaire_prevu * quantite_demandee if prix_unitaire_prevu is not None else None
        )
        montants_lignes.append(montant_ligne_prevu)
        lignes.append(
            {
                "materiau_id": materiau_id,
                "quantite_demandee": quantite_demandee,
                "verdict_prix": resolution["verdict_prix"],
                "prix_unitaire_prevu": prix_unitaire_prevu,
                "devise_prevue": resolution["devise"],
                "montant_ligne_prevu": montant_ligne_prevu,
            }
        )
    # Équivalence stricte null<->INDETERMINE, même patron que AccuseReceptionPO.montant_total_estime
    # (reception.py) : le total n'est jamais « complet » si une seule ligne reste indéterminée —
    # sum() plutôt qu'un accumulateur à littéral initial (jamais un 0.0 codé en dur en contexte
    # monétaire, conformite.py LITTERAL_COUT_INTERDIT).
    montant_total_prevu = (
        sum(montants_lignes) if all(montant is not None for montant in montants_lignes) else None
    )

    candidat = {
        "po_id": po_id,
        "chantier_id": chantier_id,
        "fournisseur_id": fournisseur_id,
        "lignes": lignes,
        "montant_total_prevu": montant_total_prevu,
    }

    existant = lire(registre_po, po_id)
    if existant is not None:
        if all(existant.get(cle) == candidat[cle] for cle in _CLES_CONTENU_PO):
            return existant, None
        return None, verdicts.construire_verdict(
            "REJ-PO-ID-DEJA-UTILISE", detail=f"po_id {po_id!r} déjà créé avec un contenu différent"
        )

    maillon = {**candidat, "type_entree": "po_cree", "statut": "draft", "horodatage": horodatage}
    registre_po.append(dict(maillon))
    return lire(registre_po, po_id), None


def _transitionner(
    registre_po: Any, po_id: Any, statut_cible: str, horodatage: Any, **champs_supplementaires: Any
) -> tuple[dict[str, Any] | None, dict | None]:
    """Écriture PARTAGÉE d'une transition légale (table ``contrats.TRANSITIONS_PO``) — chaque
    fonction publique ci-dessous en garde la RESPONSABILITÉ métier (prédécesseurs autorisés,
    règles propres à la transition) ; celle-ci ne fait que vérifier la table et écrire."""
    if not _texte_non_vide(horodatage):
        return None, verdicts.construire_verdict("REJ-PO-HORODATAGE-VIDE", detail="horodatage requis, non vide")
    etat = lire(registre_po, po_id)
    if etat is None:
        return None, verdicts.construire_verdict("REJ-PO-INTROUVABLE", detail=f"PO inconnu : {po_id!r}")
    if not transition_autorisee(etat["statut"], statut_cible):
        return None, verdicts.construire_verdict(
            "REJ-PO-TRANSITION-ILLEGALE",
            detail=f"PO {po_id!r} au statut {etat['statut']!r}, transition vers {statut_cible!r} refusée",
        )
    maillon = {
        "type_entree": "transition_po",
        "po_id": po_id,
        "statut": statut_cible,
        "horodatage": horodatage,
        **champs_supplementaires,
    }
    registre_po.append(dict(maillon))
    return lire(registre_po, po_id), None


def approuver(po_id: Any, horodatage: Any, registre_po: Any) -> tuple[dict[str, Any] | None, dict | None]:
    """(draft | pending_admin_review) -> approved. Fail-closed PLAN T2.4 : refuse tant qu'au
    moins une ligne porte ``verdict_prix == "INDETERMINE"`` — un PO ne peut pas être approuvé sur
    un prix qui reste à fournir. Aucun paramètre d'approbateur (voir la docstring du module :
    la décision N3/N4 appartient au socle, pas à cette fonction)."""
    etat = lire(registre_po, po_id)
    if etat is None:
        return None, verdicts.construire_verdict("REJ-PO-INTROUVABLE", detail=f"PO inconnu : {po_id!r}")
    lignes_indeterminees = [ligne["materiau_id"] for ligne in etat["lignes"] if ligne["verdict_prix"] == "INDETERMINE"]
    if lignes_indeterminees:
        return None, verdicts.construire_verdict(
            "REJ-PO-PRIX-INDETERMINE",
            detail=f"prix manquant au livre de prix pour : {sorted(lignes_indeterminees)}",
        )
    return _transitionner(registre_po, po_id, "approved", horodatage)


def annuler(po_id: Any, motif: Any, horodatage: Any, registre_po: Any) -> tuple[dict[str, Any] | None, dict | None]:
    """-> cancelled, depuis tout statut non terminal (table ``contrats.TRANSITIONS_PO``).
    ``motif`` humain requis, non vide (piste d'audit, P3 de la définition produit)."""
    if not _texte_non_vide(motif):
        return None, verdicts.construire_verdict("REJ-PO-MOTIF-ANNULATION-VIDE", detail="motif requis, non vide")
    return _transitionner(registre_po, po_id, "cancelled", horodatage, motif_annulation=motif)


def generer_courriel(
    po_id: Any, horodatage: Any, registre_po: Any, registre_fournisseurs: Any, nom_entreprise: Any
) -> tuple[dict[str, Any] | None, dict | None]:
    """approved -> email_ready. Génère le CORPS TEXTE d'un courriel (M6.6 : objet, destinataire,
    liste des matériaux, chantier, numéro de PO) — AUCUNE primitive d'envoi, jamais un réseau
    (voir la docstring du module). Le courriel est PERSISTÉ sur le PO (relecture possible par
    ``lire``), destiné au repli manuel documenté (copier-coller) tant que M1 n'envoie pas
    réellement (PLAN T2.5 point 3)."""
    if not _texte_non_vide(nom_entreprise):
        return None, verdicts.construire_verdict(
            "REJ-PO-NOM-ENTREPRISE-VIDE", detail="nom_entreprise requis, non vide (identifie l'expéditeur)"
        )
    etat = lire(registre_po, po_id)
    if etat is None:
        return None, verdicts.construire_verdict("REJ-PO-INTROUVABLE", detail=f"PO inconnu : {po_id!r}")

    fiche = fournisseurs.lire_fournisseur(registre_fournisseurs, etat["fournisseur_id"])
    destinataire = fiche.get("courriel_commande") if fiche is not None else None
    lignes_texte = "\n".join(
        f"- {ligne['materiau_id']} : {ligne['quantite_demandee']}" for ligne in etat["lignes"]
    )
    corps = (
        f"Bon de commande {po_id}\n"
        f"Chantier : {etat['chantier_id']}\n"
        f"Fournisseur : {etat['fournisseur_id']}\n\n"
        f"Matériaux demandés :\n{lignes_texte}\n\n"
        f"— {nom_entreprise}"
    )
    courriel = {
        "objet": f"Bon de commande {po_id} — {nom_entreprise}",
        "destinataire": destinataire,
        "corps": corps,
        "repli_manuel_requis": destinataire is None,
    }
    return _transitionner(registre_po, po_id, "email_ready", horodatage, courriel=courriel)


def marquer_envoye(po_id: Any, horodatage: Any, registre_po: Any) -> tuple[dict[str, Any] | None, dict | None]:
    """email_ready -> sent_to_supplier. Verrou d'envoi (N4, voir la docstring du module) : AUCUNE
    primitive d'envoi ici — le courriel généré par ``generer_courriel`` reste à transmettre par le
    repli manuel documenté (M1 plus tard)."""
    return _transitionner(registre_po, po_id, "sent_to_supplier", horodatage)


def peut_recevoir(statut_actuel: Any) -> bool:
    """Vrai si un PO dans ``statut_actuel`` peut recevoir une réception maintenant (PLAN T2.5
    point 4) — exposé publiquement pour qu'``outils.py`` refuse une réception AVANT toute écriture
    de stock (jamais après), sans lire la constante privée directement (encapsulation)."""
    return statut_actuel in _STATUTS_AVANT_RECEPTION


def enregistrer_reception_po(
    po_id: Any, verdict_reception: Any, horodatage: Any, registre_po: Any
) -> tuple[dict[str, Any] | None, dict | None]:
    """Attache le verdict DÉJÀ CALCULÉ par ``reception.py``/``materiel.enregistrer_reception``
    (réutilisés sans modification) au PO persisté (PLAN T2.5 point 4) :
    CONFORME/RECEPTION_SUPERIEURE -> ``received`` ; RECEPTION_INFERIEURE/RECEPTION_MIXTE ->
    ``partially_received`` ; INDETERMINE -> aucune transition (rien n'a été écrit au stock non
    plus, DA-M6-12 d'origine, inchangée pour ce cas), rend l'état actuel sans erreur."""
    etat = lire(registre_po, po_id)
    if etat is None:
        return None, verdicts.construire_verdict("REJ-PO-INTROUVABLE", detail=f"PO inconnu : {po_id!r}")
    if etat["statut"] not in _STATUTS_AVANT_RECEPTION:
        return None, verdicts.construire_verdict(
            "REJ-PO-TRANSITION-ILLEGALE",
            detail=(
                f"PO {po_id!r} au statut {etat['statut']!r}, "
                f"{sorted(_STATUTS_AVANT_RECEPTION)} requis avant réception"
            ),
        )
    if verdict_reception not in contrats.VERDICT_RECEPTION:
        return None, verdicts.construire_verdict(
            "REJ-PO-VERDICT-RECEPTION-INCONNU", detail=f"verdict_reception inconnu : {verdict_reception!r}"
        )
    if verdict_reception in ("CONFORME", "RECEPTION_SUPERIEURE"):
        nouveau_statut = "received"
    elif verdict_reception in ("RECEPTION_INFERIEURE", "RECEPTION_MIXTE"):
        nouveau_statut = "partially_received"
    else:  # INDETERMINE : rien écrit au stock, rien à transitionner ici non plus.
        return etat, None
    return _transitionner(registre_po, po_id, nouveau_statut, horodatage, verdict_reception=verdict_reception)


def detecter_ecarts_prix(
    po: Mapping[str, Any], lignes_accuse_reception: Iterable[Mapping[str, Any]], seuil_pourcentage: float
) -> list[dict[str, Any]]:
    """Compare, ligne par ligne, le prix ATTENDU du PO (``prix_unitaire_prevu``, résolu à la
    création depuis ``livre_prix.py``) au prix RÉEL résolu à la réception
    (``AccuseReceptionPO.lignes[].cout_unitaire_resolu``, ``reception.py``, INCHANGÉ) — M6.7 :
    « un prix réel qui s'écarte du prévu au-delà du seuil crée une alerte admin et un signal à M5
    et M8 ». Écart en VALEUR ABSOLUE (une baisse inattendue mérite aussi une vérification, pas
    seulement une hausse). Silencieux (liste vide) quand l'un des deux prix est indéterminé —
    comparer un prix connu à ``None`` fabriquerait un écart. Fonction PURE : ne signale rien
    elle-même, l'appelant (``outils.py``) transmet la liste à M5/M8."""
    prevu_par_materiau = {ligne["materiau_id"]: ligne["prix_unitaire_prevu"] for ligne in po["lignes"]}
    signaux: list[dict[str, Any]] = []
    for ligne in lignes_accuse_reception:
        materiau_id = ligne["materiau_id"]
        prix_prevu = prevu_par_materiau.get(materiau_id)
        prix_reel = ligne.get("cout_unitaire_resolu")
        if prix_prevu is None or prix_reel is None or prix_prevu == 0:
            continue
        ecart_pourcentage = abs(prix_reel - prix_prevu) / prix_prevu
        if ecart_pourcentage >= seuil_pourcentage:
            signaux.append(
                {
                    "po_id": po["po_id"],
                    "chantier_id": po["chantier_id"],
                    "materiau_id": materiau_id,
                    "prix_prevu": prix_prevu,
                    "prix_reel": prix_reel,
                    "ecart_pourcentage": ecart_pourcentage,
                }
            )
    return signaux
