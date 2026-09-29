"""Réservation du matériel par chantier et « matériel prêt » (M6.8, M6.4, PLAN T4.14).

DEFINITION-PRODUIT §6 (flux des matériaux) : « M6 valide le catalogue, vérifie le stock, RÉSERVE, ou crée un besoin de
commande » ; §7 M6.8 : « pas de double réservation, libération en cas d'annulation, ajustement si l'estimation
change » ; §7 M6 « fournit à M4 : matériel prêt ou à commander ». Ce module est la règle, écrite une fois.

UNE RÉSERVATION, C'EST UN PRÉVU DÉFINITIF MIS DE CÔTÉ. Elle naît d'un devis ACCEPTÉ (`besoins_prevus.py`, source
`m3.devis_accepte`) : jamais d'une estimation (`estimation_m3`, prévu provisoire, qui n'engage personne). Elle est
clée par `devis_id` — M3 ne connaît pas encore le chantier à l'acceptation (`chantier_id` nul), et un devis = un
chantier (T4.10). Pour chaque ligne du prévu, elle met de côté `min(besoin, disponible)` : jamais plus que ce qui est
disponible, donc jamais deux chantiers sur la même unité.

    disponible = en main - réservé            (en main : `stock.deriver_disponibilite`)

LE STOCK N'EST JAMAIS NÉGATIF. Une réservation ne dépasse jamais l'en main. Quand l'en main change (réception,
sortie de stock, transfert hors main, libération), `reconcilier` rétablit l'invariant `réservé <= en main` : quand
l'en main BAISSE sous le réservé (la réalité a consommé du stock mis de côté), les réservations les plus RÉCENTES
cèdent d'abord ; quand il MONTE (une réception, une libération), les plus ANCIENNES se complètent d'abord. Ordre total
et déterministe (rang de création de la réservation), aucune horloge, aucun aléa.

PRÊT, PARTIEL, À COMMANDER. Le verdict se calcule sur les lignes, jamais autrement :
- `pret` : chaque ligne est réservée en entier ;
- `a_commander` : RIEN n'est réservé (tout est à commander) ;
- `partiel` : une partie est réservée, une autre manque.
Un prévu VIDE (aucune ligne reliée à un besoin matériau) ne réserve rien et ne dit rien : dire « prêt » ferait partir
une équipe sans avoir rien vérifié. Une réservation LIBÉRÉE n'est plus « prête » : elle publie `a_commander`, avec
`reservation_active` faux.

CE QUE CE MODULE NE FAIT JAMAIS : créer un bon de commande. Il dit ce qui manque, par ligne ; commander est un geste
(`m6_creer_po_brouillon`, puis approbation), jamais un effet de bord d'une réservation (DA-M6-13). Aucun import de
`bons_commande` ici, et un test le garde.

UN FAIT PAR CHANGEMENT. Le registre `reservations` est append-only ; chaque fait est un INSTANTANÉ de la réservation
d'un devis (lignes, quantités, statut), numéroté (`revision`) : l'état courant est le dernier instantané, l'historique
reste. L'événement `m6.materiel_pret` en porte la charge (`charge_materiel_pret`) sous l'identifiant
`m6-materiel-pret-<devis_id>-<revision>` : une révision, un identifiant, donc rejouer un fait est un no-op du bus et un
retour à un état déjà vu (prêt, partiel, prêt) n'est jamais confondu avec le premier.

Module pur (AGENTS.md, ADR-0009) : aucun import `opsys`, aucune horloge (l'horodatage est fourni), aucun aléa, aucun
réseau. Les quantités sont des TEXTES décimaux exacts (`Decimal(str(x))`, jamais un flottant). L'unité de chaque ligne
est recopiée du prévu ; M6 ne convertit rien (le stock ne déclare pas d'unité).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any

from . import stock, verdicts

__all__ = [
    "DECLENCHEURS",
    "STATUT_A_COMMANDER",
    "STATUT_PARTIEL",
    "STATUT_PRET",
    "TYPE_EVENEMENT_MATERIEL_PRET",
    "actives",
    "charge_materiel_pret",
    "cloturer",
    "etat",
    "etats",
    "lignes_manquantes",
    "liberer",
    "reconcilier",
    "reserve_par_article",
    "reserver",
    "statut_pret",
]

TYPE_EVENEMENT_MATERIEL_PRET = "m6.materiel_pret"
TYPE_FAIT = "reservation"
STATUT_PRET = "pret"
STATUT_PARTIEL = "partiel"
STATUT_A_COMMANDER = "a_commander"
# Ce qui a déclenché le fait, dit à M4 : la valeur de l'énuméré fermé du schéma du catalogue. Un frozenset : des noms
# d'événements du produit, pas un verdict que ce paquet invente.
DECLENCHEURS = frozenset({"devis_accepte", "reservation_manuelle", "stock_recu", "stock_sorti", "liberation"})
_SOURCE_PROVISOIRE = "estimation_m3"


_texte = stock.texte_canonique


def _quantite(valeur: Any) -> Decimal:
    """Le nombre du prévu (float) ou le texte d'un fait, en décimal exact : jamais `Decimal(float)`."""
    return Decimal(str(valeur))


# ------------------------------------------------------------------------------------- lecture des faits
def etats(maillons: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """L'état courant de chaque réservation connue : le dernier instantané de chaque `devis_id`, plus son `rang` :
    la position au registre du fait qui l'a CRÉÉE (ordre total, stable, sans horloge). Une réservation refaite après une
    libération est une nouvelle demande : elle prend un nouveau rang, donc passe après celles qui ont été faites entre
    temps."""
    courants: dict[str, dict[str, Any]] = {}
    for position, maillon in enumerate(maillons):
        if maillon.get("type_entree") != TYPE_FAIT:
            continue
        devis_id = maillon["devis_id"]
        rang = position if maillon["evenement"] == "creee" or devis_id not in courants else courants[devis_id]["rang"]
        courants[devis_id] = {**maillon, "rang": rang}
    return courants


def etat(devis_id: Any, maillons: Iterable[Mapping[str, Any]]) -> dict[str, Any] | None:
    """L'état courant de la réservation de ce devis, ou `None` s'il n'en a jamais eu."""
    if not isinstance(devis_id, str) or not devis_id:
        return None
    return etats(maillons).get(devis_id)


def actives(maillons: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Les réservations actives, de la plus ancienne à la plus récente (rang de création)."""
    return sorted((e for e in etats(maillons).values() if e["actif"]), key=lambda e: e["rang"])


def reserve_par_article(maillons: Iterable[Mapping[str, Any]]) -> dict[str, Decimal]:
    """Ce qui est réservé, par article, toutes réservations ACTIVES confondues. Un article sans réservation est
    absent (rien de réservé)."""
    reserve: dict[str, Decimal] = {}
    for reservation in actives(maillons):
        for ligne in reservation["lignes"]:
            quantite = _quantite(ligne["quantite_reservee"])
            if quantite > 0:
                reserve[ligne["materiau_id"]] = reserve.get(ligne["materiau_id"], Decimal(0)) + quantite
    return reserve


def statut_pret(lignes: Iterable[Mapping[str, Any]]) -> str:
    """`pret`, `partiel` ou `a_commander` (voir la docstring du module), calculé sur les lignes d'un instantané.

    Suppose au moins une ligne : un prévu vide ne se réserve pas (`reserver`)."""
    lignes = list(lignes)
    besoins = [(_quantite(ligne["quantite_besoin"]), _quantite(ligne["quantite_reservee"])) for ligne in lignes]
    if all(reservee >= besoin for besoin, reservee in besoins):
        return STATUT_PRET
    if all(reservee <= 0 for _, reservee in besoins):
        return STATUT_A_COMMANDER
    return STATUT_PARTIEL


def _manquante(ligne: Mapping[str, Any]) -> Decimal:
    return max(_quantite(ligne["quantite_besoin"]) - _quantite(ligne["quantite_reservee"]), Decimal(0))


def lignes_manquantes(lignes: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Les lignes dont il manque quelque chose, avec ce qui manque (texte décimal), dans l'ordre du prévu."""
    return [
        {
            "materiau_id": ligne["materiau_id"],
            "unite": ligne.get("unite"),
            "quantite_besoin": ligne["quantite_besoin"],
            "quantite_reservee": ligne["quantite_reservee"],
            "quantite_manquante": _texte(_manquante(ligne)),
        }
        for ligne in lignes
        if _manquante(ligne) > 0
    ]


# ------------------------------------------------------------------------------------------ écriture
def _fait(
    devis_id: str, chantier_id: str | None, revision: int, evenement: str, actif: bool, declencheur: str,
    horodatage: str, acteur: str | None, motif: str | None, lignes: list[dict[str, Any]], **supplement: Any,
) -> dict[str, Any]:
    return {
        "type_entree": TYPE_FAIT,
        "devis_id": devis_id,
        "chantier_id": chantier_id,
        "revision": revision,
        "evenement": evenement,
        "actif": actif,
        "declencheur": declencheur,
        "horodatage": horodatage,
        "acteur": acteur,
        "motif": motif,
        "lignes": lignes,
        **supplement,
    }


def _ligne_texte(materiau_id: str, unite: Any, besoin: Decimal, reservee: Decimal) -> dict[str, Any]:
    return {
        "materiau_id": materiau_id, "unite": unite,
        "quantite_besoin": _texte(besoin), "quantite_reservee": _texte(reservee),
    }


def reserver(
    devis_id: Any,
    prevu: Mapping[str, Any] | None,
    horodatage: Any,
    declencheur: str,
    maillons: Iterable[Mapping[str, Any]],
    en_main: Mapping[str, Decimal],
    *,
    acteur: str | None = None,
    re_reservation: bool = False,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """`({"statut", "fait"}, None)` ou `(None, verdict)`. Sans écriture : l'appelant ajoute `fait` (quand il n'est
    pas `None`), seul point où `opsys.stockage` est touché.

    `prevu` : le prévu du devis (`besoins_prevus.pour_devis`) ; `en_main` : l'en main de CHAQUE article du prévu
    (`stock.deriver_disponibilite`) — un article absent de `en_main` est un défaut de l'appelant (`KeyError`),
    jamais un zéro silencieux qui ne réserverait rien. Statuts rendus :
    - `creee` : la réservation est faite (`fait` : instantané, révision 1 ou suivante) ;
    - `deja_reservee` : une réservation ACTIVE existe pour ce devis : aucun double, rien n'est écrit ;
    - `deja_traitee` : une réservation existe mais n'est plus active (libérée, ou clôturée à la déclaration des
      matériaux) et `re_reservation` est faux : le bus ne défait jamais ce qu'un humain a libéré ;
    - `aucun_besoin_connu` : le prévu est vide, rien à réserver, rien à dire.
    Refus nommés : `REJ-RESERVATION-DEVIS-VIDE`, `REJ-RESERVATION-PREVU-ABSENT`, `REJ-RESERVATION-PREVU-PROVISOIRE`
    (une estimation ne réserve pas), `REJ-RESERVATION-CLOTUREE` (les matériaux du chantier sont déclarés : rien
    ne se réserve plus, même en `re_reservation`), `REJ-RESERVATION-DECLENCHEUR-INCONNU`,
    `REJ-RESERVATION-HORODATAGE-VIDE`.
    """
    if not isinstance(devis_id, str) or not devis_id:
        return None, verdicts.construire_verdict("REJ-RESERVATION-DEVIS-VIDE", detail="devis_id requis, non vide")
    if not isinstance(horodatage, str) or not horodatage.strip():
        return None, verdicts.construire_verdict("REJ-RESERVATION-HORODATAGE-VIDE", detail="horodatage requis")
    if declencheur not in DECLENCHEURS:
        return None, verdicts.construire_verdict(
            "REJ-RESERVATION-DECLENCHEUR-INCONNU",
            detail=f"déclencheur hors de la liste fermée : {sorted(DECLENCHEURS)}",
        )
    if prevu is None:
        return None, verdicts.construire_verdict(
            "REJ-RESERVATION-PREVU-ABSENT",
            detail=f"aucun besoin matériaux enregistré pour le devis {devis_id!r} (m3.devis_accepte n'est pas reçu)",
        )
    if prevu.get("source") == _SOURCE_PROVISOIRE:
        return None, verdicts.construire_verdict(
            "REJ-RESERVATION-PREVU-PROVISOIRE",
            detail=f"le prévu du devis {devis_id!r} est une estimation : seul un devis accepté réserve",
        )
    maillons = list(maillons)
    existant = etat(devis_id, maillons)
    if existant is not None:
        if existant["actif"]:
            return {"statut": "deja_reservee", "fait": None}, None
        if existant["evenement"] == "cloturee":
            return None, verdicts.construire_verdict(
                "REJ-RESERVATION-CLOTUREE",
                detail=f"les matériaux du devis {devis_id!r} sont déclarés : plus rien ne se réserve pour lui",
            )
        if not re_reservation:
            return {"statut": "deja_traitee", "fait": None}, None
    if not prevu["lignes"]:
        return {"statut": "aucun_besoin_connu", "fait": None}, None

    reserve = reserve_par_article(maillons)
    lignes = []
    for ligne in prevu["lignes"]:
        materiau_id = ligne["materiau_id"]
        besoin = _quantite(ligne["quantite_estimee"])
        disponible = en_main[materiau_id] - reserve.get(materiau_id, Decimal(0))
        reservee = min(besoin, max(disponible, Decimal(0)))
        lignes.append(_ligne_texte(materiau_id, ligne.get("unite"), besoin, reservee))
    revision = existant["revision"] + 1 if existant is not None else 1
    fait = _fait(
        devis_id, prevu.get("chantier_id"), revision, "creee", True, declencheur, horodatage, acteur, None, lignes
    )
    return {"statut": "creee", "fait": fait}, None


def liberer(
    devis_id: Any, motif: Any, acteur: str | None, horodatage: Any, maillons: Iterable[Mapping[str, Any]]
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """`({"statut", "fait"}, None)` ou `(None, verdict)` : libère la réservation ACTIVE d'un devis (annulation du
    chantier, M6.8). Les quantités réservées retournent au disponible ; l'instantané garde ce qui a été libéré
    (`liberees`), l'historique garde le reste.

    Statuts : `liberee` (`fait` à ajouter) ; `deja_liberee` (rejeu : la réservation n'est plus active, rien à
    écrire). Refus : `REJ-RESERVATION-INTROUVABLE` (aucune réservation pour ce devis), `REJ-RESERVATION-MOTIF-VIDE`
    (chaque libération garde sa raison, M6.14), `REJ-RESERVATION-HORODATAGE-VIDE`."""
    if not isinstance(motif, str) or not motif.strip():
        return None, verdicts.construire_verdict(
            "REJ-RESERVATION-MOTIF-VIDE", detail="motif requis, non vide (chaque libération garde sa raison)"
        )
    if not isinstance(horodatage, str) or not horodatage.strip():
        return None, verdicts.construire_verdict("REJ-RESERVATION-HORODATAGE-VIDE", detail="horodatage requis")
    courant = etat(devis_id, maillons)
    if courant is None:
        return None, verdicts.construire_verdict(
            "REJ-RESERVATION-INTROUVABLE", detail=f"aucune réservation pour le devis {devis_id!r}"
        )
    if not courant["actif"]:
        return {"statut": "deja_liberee", "fait": None}, None
    liberees = [
        {"materiau_id": ligne["materiau_id"], "quantite": ligne["quantite_reservee"]}
        for ligne in courant["lignes"] if _quantite(ligne["quantite_reservee"]) > 0
    ]
    lignes = [_ligne_texte(ligne["materiau_id"], ligne.get("unite"), _quantite(ligne["quantite_besoin"]), Decimal(0))
              for ligne in courant["lignes"]]
    fait = _fait(
        devis_id, courant["chantier_id"], courant["revision"] + 1, "liberee", False, "liberation", horodatage, acteur,
        motif.strip(), lignes, liberees=liberees,
    )
    return {"statut": "liberee", "fait": fait}, None


def cloturer(
    devis_id: Any, wct_id: str, horodatage: str, maillons: Iterable[Mapping[str, Any]]
) -> dict[str, Any] | None:
    """Le fait de CLÔTURE de la réservation active de ce devis, ou `None` s'il n'y en a pas. À la déclaration des
    matériaux utilisés d'un chantier (`wct_id`), ce qui était mis de côté est consommé ou rendu : la réservation
    n'a plus de raison d'être, et ce qu'elle retenait redevient disponible (la sortie de stock, elle, est déjà au
    registre de mouvements). Aucun événement `m6.materiel_pret` n'en naît : le chantier est terminé."""
    courant = etat(devis_id, maillons)
    if courant is None or not courant["actif"]:
        return None
    lignes = [_ligne_texte(ligne["materiau_id"], ligne.get("unite"), _quantite(ligne["quantite_besoin"]), Decimal(0))
              for ligne in courant["lignes"]]
    return _fait(
        devis_id, courant["chantier_id"], courant["revision"] + 1, "cloturee", False, "stock_sorti", horodatage, None,
        "materiaux_declares", lignes, wct_id=wct_id,
    )


def reconcilier(
    materiaux: Iterable[str],
    en_main: Mapping[str, Decimal],
    maillons: Iterable[Mapping[str, Any]],
    horodatage: str,
) -> list[dict[str, Any]]:
    """Les faits `ajustee` qui rétablissent `réservé <= en main` et complètent ce qui manque, pour ces articles.
    Sans écriture : l'appelant ajoute chaque fait et publie son `m6.materiel_pret`.

    Par article : si le réservé dépasse l'en main (jamais négatif : un en main négatif se compte comme zéro), les
    réservations les plus RÉCENTES cèdent d'abord, ligne par ligne, jusqu'à l'en main ; s'il reste de l'en main non
    réservé, les réservations les plus ANCIENNES dont il manque quelque chose se complètent d'abord, jusqu'à leur
    besoin. Un seul fait par devis, quel que soit le nombre d'articles qui le touchent ; aucun fait pour un devis
    qui ne change pas.

    `declencheur` du fait : `stock_sorti` si la réservation a CÉDÉ du stock sur au moins une ligne (une sortie, une
    perte ou un transfert hors main a diminué l'en main), `stock_recu` si elle n'a fait que se compléter (une
    réception, ou du stock libéré, l'a augmenté). Le sens du changement, jamais ce qui l'a causé : M4 n'a besoin
    que de savoir si le matériel se rapproche du prêt ou s'en éloigne.

    `en_main` doit porter CHAQUE article de `materiaux` : un article absent est un défaut de l'appelant
    (`KeyError`), jamais un zéro silencieux qui effacerait les réservations."""
    en_cours = actives(maillons)
    reservees: dict[str, dict[str, Decimal]] = {
        e["devis_id"]: {ligne["materiau_id"]: _quantite(ligne["quantite_reservee"]) for ligne in e["lignes"]}
        for e in en_cours
    }
    besoins: dict[str, dict[str, Decimal]] = {
        e["devis_id"]: {ligne["materiau_id"]: _quantite(ligne["quantite_besoin"]) for ligne in e["lignes"]}
        for e in en_cours
    }
    changes: set[str] = set()
    cedes: set[str] = set()
    for materiau_id in sorted(set(materiaux)):
        plafond = max(en_main[materiau_id], Decimal(0))
        total = sum((reservees[e["devis_id"]].get(materiau_id, Decimal(0)) for e in en_cours), Decimal(0))
        if total > plafond:
            exces = total - plafond
            for reservation in reversed(en_cours):
                if exces <= 0:
                    break
                actuelle = reservees[reservation["devis_id"]].get(materiau_id, Decimal(0))
                retire = min(actuelle, exces)
                if retire > 0:
                    reservees[reservation["devis_id"]][materiau_id] = actuelle - retire
                    exces -= retire
                    changes.add(reservation["devis_id"])
                    cedes.add(reservation["devis_id"])
        elif total < plafond:
            libre = plafond - total
            for reservation in en_cours:
                if libre <= 0:
                    break
                devis = reservation["devis_id"]
                if materiau_id not in besoins[devis]:
                    continue
                manque = besoins[devis][materiau_id] - reservees[devis].get(materiau_id, Decimal(0))
                ajout = min(manque, libre)
                if ajout > 0:
                    reservees[devis][materiau_id] = reservees[devis].get(materiau_id, Decimal(0)) + ajout
                    libre -= ajout
                    changes.add(devis)
    faits = []
    for reservation in en_cours:
        devis = reservation["devis_id"]
        if devis not in changes:
            continue
        lignes = [
            _ligne_texte(ligne["materiau_id"], ligne.get("unite"), besoins[devis][ligne["materiau_id"]],
                         reservees[devis][ligne["materiau_id"]])
            for ligne in reservation["lignes"]
        ]
        faits.append(_fait(
            devis, reservation["chantier_id"], reservation["revision"] + 1, "ajustee", True,
            "stock_sorti" if devis in cedes else "stock_recu", horodatage, None, None, lignes,
        ))
    return faits


# -------------------------------------------------------------------------- l'événement m6.materiel_pret
def charge_materiel_pret(fait: Mapping[str, Any]) -> dict[str, Any]:
    """La charge de `m6.materiel_pret` pour un instantané de réservation (catalogue du socle, schéma fermé, toutes
    propriétés requises) : le statut calculé sur les lignes, toutes les lignes, et les lignes manquantes.

    `evenement_id` = `m6-materiel-pret-<devis_id>-<revision>` : déterministe, unique par changement. M4 lit la
    charge de plus grande `revision` d'un `devis_id` : `pret` avec `reservation_active` vrai est le SEUL état qui dit
    que le matériel est prêt. Aucun montant, aucun prix, aucune date de chantier."""
    lignes = [
        {
            "materiau_id": ligne["materiau_id"],
            "unite": ligne.get("unite"),
            "quantite_besoin": ligne["quantite_besoin"],
            "quantite_reservee": ligne["quantite_reservee"],
            "quantite_manquante": _texte(_manquante(ligne)),
        }
        for ligne in fait["lignes"]
    ]
    return {
        "evenement_id": f"m6-materiel-pret-{fait['devis_id']}-{fait['revision']}",
        "devis_id": fait["devis_id"],
        "chantier_id": fait["chantier_id"],
        "revision": fait["revision"],
        "statut": statut_pret(fait["lignes"]),
        "reservation_active": fait["actif"],
        "declencheur": fait["declencheur"],
        "horodatage": fait["horodatage"],
        "lignes": lignes,
        "lignes_manquantes": lignes_manquantes(fait["lignes"]),
    }
