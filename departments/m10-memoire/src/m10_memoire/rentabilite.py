"""Mémorisation d'un événement ``m5.rentabilite_chantier`` au registre Événements (PLAN T1.5-d).

M5 publie, à chaque nouvelle version de son coût réel d'un chantier, ce qu'il en sait : le coût réel (ou ce
qui manque pour le chiffrer), la marge réelle et prévue, l'écart entre les deux — catalogue socle,
``src/opsys/evenements/catalogue/m5.rentabilite_chantier.json`` (schéma fermé, aucun prix unitaire, aucun taux,
aucune donnée de client). M10 en garde la LEÇON : l'écart de marge de l'affaire, à côté du travail terminé
(WCT) et de la variance de matériaux qui l'expliquent, dans le MÊME registre et sous le MÊME ``type_entree``
(``evenement_memorise``) ; ``classification.py`` les distingue à la lecture par un champ propre à chacun.

Deux différences avec la variance, voulues :

- l'entrée est marquée ``FINANCIAL`` (``confidentialite.py``) : une marge ne sort JAMAIS dans un paquet de
  contexte, pour aucun agent (M1 parle au client). Elle se lit au registre, par les outils de M10 et de M5 ;
- la charge n'a pas de contrat M10 séparé : le catalogue socle est la seule source de vérité (comme pour la
  variance), donc aucune re-validation métier ici. La charge est mémorisée TELLE QUELLE : M10 ne recalcule ni
  ne « corrige » jamais un montant de M5, et un coût partiel n'y porte, comme dans l'événement, aucune marge.

Chaque publication de M5 (identifiant distinct par version des entrées) est un NOUVEAU maillon : l'historique de
la rentabilité d'un chantier se lit en entier, le plus grand ``sequence`` étant le dernier état connu.

Module pur (DA-M10-08) : aucun import d'``opsys``.
"""

from __future__ import annotations

from typing import Any

from . import confidentialite

_TYPE_ENTREE_EVENEMENT = "evenement_memorise"


def memoriser_rentabilite(
    rentabilite_recue: dict[str, Any], registre_cible: Any
) -> tuple[dict[str, Any] | None, str | None]:
    """Mémorise la rentabilité reçue au registre donné, au niveau ``FINANCIAL`` ; rend ``(maillon, None)``.

    Patron ``(resultat, verdict)`` conservé pour cohérence avec ``variance.memoriser_variance``, même si ce
    module n'a aujourd'hui aucun chemin de refus (charge déjà validée par le catalogue socle avant livraison).
    Le marquage ``FINANCIAL`` est posé ICI, après la charge : une charge qui porterait déjà ``confidentialite``
    (le catalogue le refuse) ne peut pas l'ouvrir.
    """
    entree = {
        **rentabilite_recue,
        "type_entree": _TYPE_ENTREE_EVENEMENT,
        "horodatage": rentabilite_recue["horodatage_completion"],
        "confidentialite": confidentialite.NIVEAU_FINANCIER,
    }
    ligne_id = registre_cible.ajouter(entree)

    for maillon in registre_cible.lire():
        if maillon["ligne_id"] == ligne_id:
            return maillon, None

    raise RuntimeError("Maillon ajouté introuvable.")
