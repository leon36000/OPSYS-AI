"""Pagination de la liste des interventions (PLAN T4.27-a, §9.5 M4 « dispatch du jour »).

Module pur (stdlib et ``verdicts`` ; aucun import ``opsys``, aucune horloge, aucun aléa, aucun réseau ; un test le
vérifie par analyse du code). ``m4_lister_interventions`` rendait la liste ENTIÈRE : au-delà d'une vingtaine
d'interventions, le socle (``Capacites``) coupait la réponse à 6 000 caractères et l'app lisait un aperçu, pas une
liste. Ce module la coupe lui-même, proprement : une page qui tient toujours dans la borne, et de quoi lire la suivante.

Une clé SŒUR, jamais un changement de sens (le contrat v1 de la liste est gelé) : sans ``curseur`` ni ``taille_page``,
l'outil rend la liste comme avant, octet pour octet. Avec l'un des deux, il rend une PAGE : ``{interventions, page}``.
``interventions`` porte les mêmes lignes que la liste v1 (aucune clé ajoutée, retirée ni renommée) ; ``page`` dit où
l'on en est.

ORDRE, stable et total : ``intervention_id`` croissant (identifiant unique, empreinte SHA-256 en hexadécimal
minuscule). Le curseur est l'identifiant de la DERNIÈRE intervention de la page : la page suivante rend celles dont
l'identifiant est strictement plus grand. Ce curseur ne dépend d'aucun rang : une intervention qui naît entre deux pages
ne fait ni sauter ni répéter une intervention déjà lue (elle s'insère dans l'ordre : trop petite, elle est avant le
curseur et se lit à la relecture depuis le début ; sinon, elle vient dans une page suivante). ``total`` et ``reste`` se
calculent à chaque appel : si ``total`` change d'une page à l'autre, l'appelant relit depuis le début.

BORNE : la page est la plus grande qui tient (mesurée par le code, jamais estimée) sous ``tient``, sans dépasser
``taille_page`` quand elle est donnée. Au moins une intervention par page, sinon la lecture ne progresserait jamais : si
même une seule ne tient pas, refus nommé, jamais une page vide ni une réponse coupée. ``borne_atteinte`` dit qu'elle a
été raccourcie par la borne et non par ``taille_page`` ni par la fin de la liste.

Ce module reçoit la liste DÉJÀ filtrée par le statut demandé et par ce que l'appelant a le droit de voir
(``acces.interventions_visibles``) : ``total``, ``reste`` et ``curseur_suivant`` ne comptent donc jamais une
intervention qu'un employé n'a pas le droit de voir (un curseur arbitraire ne révèle rien : il ne sert que de borne
inférieure).
"""

from __future__ import annotations

import re

from . import verdicts

ORDRE = "intervention_id croissant"
TAILLE_PAGE_MAX = 50
FORME_CURSEUR = r"^[0-9a-f]{64}$"
_CURSEUR = re.compile(FORME_CURSEUR)

__all__ = [
    "FORME_CURSEUR",
    "ORDRE",
    "TAILLE_PAGE_MAX",
    "paginer",
    "verifier_arguments",
]


def _verdict(detail):
    return verdicts.construire_verdict("REJ-CONTRAT-INVALIDE", detail=detail)


def verifier_arguments(curseur, taille_page):
    """``None`` si ``curseur`` et ``taille_page`` sont admis, sinon un verdict qui dit quoi corriger.

    ``curseur`` : ``None`` (première page) ou l'identifiant d'une intervention (64 caractères hexadécimaux minuscules),
    celui que ``curseur_suivant`` a rendu. ``taille_page`` : ``None`` (la plus grande page qui tient) ou un entier de 1
    à ``TAILLE_PAGE_MAX``. Un booléen n'est jamais un entier ; rien n'est corrigé, borné ni deviné en silence."""
    if curseur is not None and (not isinstance(curseur, str) or _CURSEUR.fullmatch(curseur) is None):
        return _verdict(
            "curseur : l'identifiant d'intervention rendu par curseur_suivant est attendu (64 caractères hexadécimaux "
            "minuscules) ; null ou absent pour la première page"
        )
    if taille_page is not None and (
        isinstance(taille_page, bool) or not isinstance(taille_page, int) or not 1 <= taille_page <= TAILLE_PAGE_MAX
    ):
        return _verdict(
            f"taille_page : un entier de 1 à {TAILLE_PAGE_MAX} est attendu (reçu {taille_page!r}) ; null ou absent "
            "pour la plus grande page qui tient dans une réponse"
        )
    return None


def paginer(interventions, curseur, taille_page, tient):
    """``(page, None)`` ou ``(None, verdict)`` : une page de la liste, dans l'ordre de ``ORDRE``.

    ``interventions`` : les lignes de ``etats.lister_interventions``, déjà filtrées (statut demandé, droit de voir).
    ``curseur``, ``taille_page`` : voir ``verifier_arguments``. ``tient(page)`` : prédicat que l'appelant fournit et qui
    mesure la place que la réponse prend (le code mesure, jamais une estimation).

    La page rendue est ``{"interventions": [...], "page": {...}}`` ; ``page`` porte ``ordre``, ``curseur`` et
    ``taille_demandee`` (ce qui a été demandé, tel quel), ``taille`` (lignes de cette page), ``total`` (toutes les
    interventions de la liste, avant le curseur), ``reste`` (celles qui viennent APRÈS cette page),
    ``curseur_suivant`` (à redonner tel quel pour la page suivante ; ``None`` quand il ne reste rien) et
    ``borne_atteinte``. Un curseur au-delà de la dernière intervention rend une page vide, qui le dit (``reste`` 0,
    ``curseur_suivant`` nul), jamais une erreur ni une intervention inventée."""
    verdict = verifier_arguments(curseur, taille_page)
    if verdict is not None:
        return None, verdict
    ordonnees = sorted(interventions, key=lambda ligne: ligne["intervention_id"])
    suivantes = ordonnees if curseur is None else [ligne for ligne in ordonnees if ligne["intervention_id"] > curseur]
    plafond = len(suivantes) if taille_page is None else min(taille_page, len(suivantes))

    def page(nombre):
        reste = len(suivantes) - nombre
        return {
            "interventions": [dict(ligne) for ligne in suivantes[:nombre]],
            "page": {
                "ordre": ORDRE,
                "curseur": curseur,
                "taille_demandee": taille_page,
                "taille": nombre,
                "total": len(ordonnees),
                "reste": reste,
                "curseur_suivant": suivantes[nombre - 1]["intervention_id"] if reste and nombre else None,
                "borne_atteinte": nombre < plafond,
            },
        }

    nombre = 0
    while nombre < plafond and tient(page(nombre + 1)):
        nombre += 1
    if plafond and nombre == 0:
        return None, _verdict(
            f"l'intervention {suivantes[0]['intervention_id']} dépasse à elle seule la borne d'une réponse : "
            "impossible de la lire par page"
        )
    return page(nombre), None
