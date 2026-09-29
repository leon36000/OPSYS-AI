"""Matériel prêt d'un devis accepté, tel que M6 le dit à M4 (PLAN T4.14-b, M4.6, DEFINITION-PRODUIT §7 M6 « fournit
à M4 : matériel prêt ou à commander »).

Module pur (stdlib ; aucun import ``opsys``, aucune horloge, aucun aléa, aucun réseau ; un test le vérifie par analyse
du code). M4 ne lit JAMAIS le stock de M6 et n'importe rien de M6 : il reçoit ``m6.materiel_pret`` par le bus, en garde
la charge la plus récente par devis, et ce module la lit.

Retenue par ``devis_id``
    M6 publie une charge par CHANGEMENT de la réservation d'un devis (``revision`` 1, 2, 3 ...). L'ordre de livraison
    du bus n'est pas garanti : M4 retient, pour chaque ``devis_id``, la charge de plus grande ``revision``, quel que
    soit l'ordre d'arrivée. Une charge de révision plus petite ou égale à celle déjà retenue n'est pas écrite. Une
    intervention naît d'un devis (``devis_id`` de son inscription) : c'est la clé de lecture. ``chantier_id`` (nul
    quand M3 ne le connaissait pas) n'est ni lu ni gardé : M4 ne devine pas un chantier.

Ce que « prêt » veut dire
    ``pret`` SEULEMENT si M6 dit ``statut == "pret"``, ET que la réservation est active (``reservation_active``), ET
    qu'aucune ligne ne manque (``lignes_manquantes`` vide). Tout le reste est « pas prêt » : ``partiel`` ou
    ``a_commander``, avec les lignes manquantes. Un « pret » que le reste de la charge contredit (réservation
    libérée, ou lignes manquantes) n'est jamais prêt. Aucune charge pour un devis : « non vérifiable » (M6 n'a rien
    vérifié, et M6 ne dit rien d'un prévu vide) ; jamais « prêt » par défaut.

Le module ne porte ni prix, ni coût, ni montant : ce sont des quantités (texte décimal exact, dans l'unité du prévu, que
M6 recopie sans convertir).
"""

from __future__ import annotations

TYPE_MATERIEL_PRET_RECU = "materiel_pret_recu"

ETAT_PRET = "pret"
ETAT_PARTIEL = "partiel"
ETAT_A_COMMANDER = "a_commander"

# Les champs de la charge que M4 garde : ce que la lecture du volet « matériel » utilise, rien de plus. ``lignes`` (le
# détail de chaque matériau) et ``chantier_id`` restent chez M6 ; ``lignes_manquantes`` dit ce qui manque.
CLES_RETENUES = (
    "evenement_id", "devis_id", "revision", "statut", "reservation_active", "declencheur", "lignes_manquantes",
)

__all__ = [
    "TYPE_MATERIEL_PRET_RECU",
    "ETAT_PRET",
    "ETAT_PARTIEL",
    "ETAT_A_COMMANDER",
    "CLES_RETENUES",
    "maillon_de_la_charge",
    "charge_retenue",
    "etat_du_materiel",
    "lignes_manquantes_en_texte",
]


def maillon_de_la_charge(charge):
    """Le maillon de registre qui garde la charge ``m6.materiel_pret`` : ses champs utiles, et l'horodatage du fait que
    M6 a repris tel quel (jamais l'instant de réception : M4 n'a pas d'horloge).

    Lève ``ValueError`` si la révision n'est pas un entier d'au moins 1 (booléen refusé) : la retenue de la plus grande
    révision ne se comparerait pas, et une charge dont l'ordre est inconnu ne s'écrit pas."""
    revision = charge["revision"]
    if type(revision) is not int or revision < 1:
        raise ValueError(f"revision : entier d'au moins 1 attendu, reçu {revision!r}")
    maillon = {"type_entree": TYPE_MATERIEL_PRET_RECU, "horodatage": charge["horodatage"]}
    for cle in CLES_RETENUES:
        maillon[cle] = charge[cle]
    return maillon


def charge_retenue(registre_cible, devis_id):
    """Le maillon de plus grande ``revision`` pour ce devis, ou ``None`` (aucune charge reçue).

    Lu au registre, jamais déduit."""
    if not isinstance(devis_id, str) or devis_id == "":
        return None
    retenue = None
    for maillon in registre_cible.lire():
        if maillon["type_entree"] != TYPE_MATERIEL_PRET_RECU or maillon["devis_id"] != devis_id:
            continue
        if retenue is None or maillon["revision"] > retenue["revision"]:
            retenue = maillon
    return retenue


def etat_du_materiel(charge):
    """``pret``, ``partiel`` ou ``a_commander`` : ce que la charge retenue permet d'affirmer.

    ``pret`` seulement si ``statut`` vaut ``pret`` ET ``reservation_active`` est vrai ET ``lignes_manquantes`` est
    vide. ``partiel`` et ``a_commander`` sont repris de M6 tels quels. Un « pret » contredit par la suite de la charge
    (ou un statut hors énuméré) donne ``a_commander`` quand la réservation n'est pas active, sinon ``partiel`` :
    jamais prêt."""
    statut = charge["statut"]
    active = charge["reservation_active"] is True
    if statut == ETAT_PRET and active and not charge["lignes_manquantes"]:
        return ETAT_PRET
    if statut in (ETAT_PARTIEL, ETAT_A_COMMANDER):
        return statut
    return ETAT_PARTIEL if active else ETAT_A_COMMANDER


def lignes_manquantes_en_texte(lignes_manquantes):
    """Ce qui manque, une phrase courte par ligne : ``matériau : quantité manquante unité sur besoin``."""
    morceaux = []
    for ligne in lignes_manquantes:
        unite = ligne["unite"]
        suffixe = f" {unite}" if isinstance(unite, str) and unite else ""
        morceaux.append(
            f"{ligne['materiau_id']} : {ligne['quantite_manquante']}{suffixe} manquantes sur {ligne['quantite_besoin']}"
        )
    return " ; ".join(morceaux)
