"""Les étapes de l'amont d'une affaire, du lead au devis (PLAN T4.18, DEFINITION-PRODUIT §6, P4).

Avant le chantier, l'affaire tient en quatre faits que le bus publie : le lead qualifié (M1), le client associé
(M2), le devis accepté et le devis resté sans réponse (M3). M10 en garde l'HISTORIQUE, au registre Événements, sous
le MÊME ``type_entree`` (``evenement_memorise``) que le WCT, la variance et la rentabilité.

Ce que M10 garde, et rien d'autre : des identifiants et des faits d'étape, extraits UN PAR UN de la charge (liste
blanche, jamais une copie de la charge). Ne sont donc jamais gardés : le contact du lead (nom, téléphone, courriel),
la ville, l'identifiant de conversation ni celui du signal (empreintes du correspondant), les lignes d'un devis
(descriptions), ni aucun texte du client (Loi 25, P8). Chaque valeur gardée a une FORME FERMÉE (identifiant, code de
service, énuméré, booléen, entier, texte décimal, instant ISO) : ce qui entre au registre ne peut pas porter de
texte libre. Une valeur hors forme est un refus nommé, dont le détail dit le CHAMP, jamais la valeur (elle pourrait
être une donnée personnelle).

Niveaux de confidentialité (``confidentialite.py``), posés ICI, après la charge :
- ``m2.client_associe`` : ``CLIENT_PRIVATE``. ``client_id`` est une empreinte du contact du client : sur un numéro
  de téléphone, elle se retrouve par essais. Seuls M1 et M2 la voient dans un paquet ;
- le prix et le coût d'un devis accepté vont dans un maillon COMPAGNON, ``FINANCIAL`` (patron ``rentabilite.py``) :
  ils ne sortent dans aucun paquet, pour aucun agent. Le maillon de l'étape, lui, ne porte aucun montant, pour que
  « devis accepté » figure à l'historique que voient les agents ;
- les autres étapes : ``INTERNAL``, comme le WCT.

L'instant d'un fait est celui de l'ÉVÉNEMENT (réception du message, association, acceptation, constat), jamais une
horloge de M10 (``conformite.py::HORLOGE_INTERNE`` le détecterait).

Ajouter une étape (comme ``m3.devis_envoye``, T4.7) = ajouter UNE entrée à ``_ETAPES`` (son
extraction, son résumé, son niveau) et son type à ``evenements.consomme`` de ``department.yaml`` : le consommateur,
la classification, le paquet, la consolidation et l'audit lisent cette table.

Module pur (DA-M10-08) : aucun import d'``opsys``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from . import affaire, confidentialite, validation

TYPE_LEAD_QUALIFIE = "m1.lead_qualifie"
TYPE_CLIENT_ASSOCIE = "m2.client_associe"
TYPE_DEVIS_ENVOYE = "m3.devis_envoye"
TYPE_DEVIS_ACCEPTE = "m3.devis_accepte"
TYPE_DEVIS_SANS_REPONSE = "m3.devis_sans_reponse"
SUFFIXE_MONTANTS = ":montants"
TYPE_MONTANTS_DEVIS_ACCEPTE = TYPE_DEVIS_ACCEPTE + SUFFIXE_MONTANTS

_TYPE_ENTREE_EVENEMENT = "evenement_memorise"

REJ_AMONT_TYPE_INCONNU = "REJ-AMONT-TYPE-INCONNU"
REJ_AMONT_CHAMP_MANQUANT = "REJ-AMONT-CHAMP-MANQUANT"
REJ_AMONT_CHAMP_INVALIDE = "REJ-AMONT-CHAMP-INVALIDE"
REJ_AMONT_HORODATAGE_INVALIDE = "REJ-AMONT-HORODATAGE-INVALIDE"

# Formes fermées (même esprit que `faits_candidats.py`) : aucun espace, aucune arobase, aucun « + » ne passe.
# La forme d'une affaire n'est plus écrite ici mais dans `affaire.py`, commune au core et à toutes les entrées de M10 :
# `affaire.FORME_LEAD` pour le lead que M1 publie, `affaire.FORME_AFFAIRE` pour celui de M2 et de M3, qui peut être
# l'opportunité `<lead d'origine>~opp~<wct_id>` que M2 ouvre pour un nouveau chantier d'un client déjà connu.
_IDENTIFIANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CODE_SERVICE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_DECIMAL = re.compile(r"^[0-9]+(\.[0-9]+)?$")
_CANAUX = frozenset({"telephone", "courriel", "formulaire", "texte"})
_STATUTS_SANS_REPONSE = frozenset({"brouillon", "envoye"})


class ChampRefuse(ValueError):
    """Un champ de la charge manque ou sort de sa forme fermée. ``code`` est le verdict, ``detail`` le CHAMP."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(f"{code} : {detail}")
        self.code = code
        self.detail = detail

    def verdict(self) -> dict[str, Any]:
        return validation.construire_verdict(self.code, self.detail)


def _lire(charge: Mapping[str, Any], chemin: tuple[str, ...]) -> Any:
    courant: Any = charge
    for cle in chemin:
        if not isinstance(courant, Mapping) or cle not in courant:
            raise ChampRefuse(REJ_AMONT_CHAMP_MANQUANT, "/".join(chemin))
        courant = courant[cle]
    return courant


def _refus_invalide(chemin: tuple[str, ...]) -> ChampRefuse:
    return ChampRefuse(REJ_AMONT_CHAMP_INVALIDE, "/".join(chemin))


def _forme(charge: Mapping[str, Any], chemin: tuple[str, ...], motif: re.Pattern[str]) -> str:
    valeur = _lire(charge, chemin)
    if not isinstance(valeur, str) or motif.fullmatch(valeur) is None:
        raise _refus_invalide(chemin)
    return valeur


def _forme_ou_none(charge: Mapping[str, Any], chemin: tuple[str, ...], motif: re.Pattern[str]) -> str | None:
    return None if _lire(charge, chemin) is None else _forme(charge, chemin, motif)


def _choix(charge: Mapping[str, Any], chemin: tuple[str, ...], permis: frozenset[str]) -> str:
    valeur = _lire(charge, chemin)
    if not isinstance(valeur, str) or valeur not in permis:
        raise _refus_invalide(chemin)
    return valeur


def _booleen(charge: Mapping[str, Any], chemin: tuple[str, ...]) -> bool:
    valeur = _lire(charge, chemin)
    if not isinstance(valeur, bool):
        raise _refus_invalide(chemin)
    return valeur


def _entier_positif(charge: Mapping[str, Any], chemin: tuple[str, ...]) -> int:
    valeur = _lire(charge, chemin)
    if not isinstance(valeur, int) or isinstance(valeur, bool) or valeur < 1:
        raise _refus_invalide(chemin)
    return valeur


def _instant(charge: Mapping[str, Any], chemin: tuple[str, ...]) -> str:
    """Un instant ISO 8601 AVEC fuseau : le registre le refuserait de toute façon, mais avec un texte qui ne dit pas
    de quel champ il s'agit."""
    valeur = _lire(charge, chemin)
    try:
        instant = datetime.fromisoformat(valeur) if isinstance(valeur, str) else None
    except ValueError:
        instant = None
    if instant is None or instant.tzinfo is None:
        raise ChampRefuse(REJ_AMONT_HORODATAGE_INVALIDE, "/".join(chemin))
    return valeur


# -- extraction : une fonction par type, une clé à la fois ------------------------------------------------------
def _extraire_lead_qualifie(charge: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "lead_id": _forme(charge, ("lead", "lead_id"), affaire.FORME_LEAD),
        "service": _forme(charge, ("lead", "service"), _CODE_SERVICE),
        "canal": _choix(charge, ("lead", "canal"), _CANAUX),
        "urgence_declaree": _booleen(charge, ("lead", "urgence_declaree")),
        "horodatage": _instant(charge, ("horodatage",)),
    }


def _extraire_client_associe(charge: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "lead_id": _forme(charge, ("lead_id",), affaire.FORME_AFFAIRE),
        "client_id": _forme(charge, ("client_id",), _IDENTIFIANT),
        "horodatage": _instant(charge, ("horodatage_association",)),
    }


def _extraire_devis_envoye(charge: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "lead_id": _forme(charge, ("lead_id",), affaire.FORME_AFFAIRE),
        "devis_id": _forme(charge, ("devis_id",), _IDENTIFIANT),
        "chantier_id": _forme_ou_none(charge, ("chantier_id",), _IDENTIFIANT),
        # L'instant de la décision du propriétaire qui approuve l'envoi (écrit par le socle), pas la livraison.
        "horodatage": _instant(charge, ("horodatage_envoi",)),
    }


def _extraire_devis_accepte(charge: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "lead_id": _forme(charge, ("lead_id",), affaire.FORME_AFFAIRE),
        "devis_id": _forme(charge, ("devis_id",), _IDENTIFIANT),
        "chantier_id": _forme_ou_none(charge, ("chantier_id",), _IDENTIFIANT),
        "horodatage": _instant(charge, ("horodatage_acceptation",)),
    }


def _extraire_montants_devis_accepte(charge: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "lead_id": _forme(charge, ("lead_id",), affaire.FORME_AFFAIRE),
        "devis_id": _forme(charge, ("devis_id",), _IDENTIFIANT),
        "prix_total": _forme(charge, ("prix_total",), _DECIMAL),
        "cout_total": _forme(charge, ("cout_total",), _DECIMAL),
        "taux_marge": _forme(charge, ("taux_marge",), _DECIMAL),
        "horodatage": _instant(charge, ("horodatage_acceptation",)),
    }


def _extraire_devis_sans_reponse(charge: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "lead_id": _forme(charge, ("lead_id",), affaire.FORME_AFFAIRE),
        "devis_id": _forme(charge, ("devis_id",), _IDENTIFIANT),
        "chantier_id": _forme_ou_none(charge, ("chantier_id",), _IDENTIFIANT),
        "statut": _choix(charge, ("statut",), _STATUTS_SANS_REPONSE),
        "depuis": _instant(charge, ("horodatage_devis",)),
        "delai_relance_jours": _entier_positif(charge, ("delai_relance_jours",)),
        # L'instant du fait : le constat, fourni par l'appelant de M3 (« maintenant » du contrôle).
        "horodatage": _instant(charge, ("horodatage_reference",)),
    }


# -- résumés : courts, sans montant, sans texte libre ---------------------------------------------------------------
def _resume_lead_qualifie(maillon: Mapping[str, Any]) -> str:
    urgence = "déclarée" if maillon.get("urgence_declaree") else "non déclarée"
    return f"Lead qualifié : service {maillon.get('service')}, canal {maillon.get('canal')}, urgence {urgence}"


def _resume_client_associe(maillon: Mapping[str, Any]) -> str:
    return f"Client associé au lead : {maillon.get('client_id')}"


def _resume_devis_envoye(maillon: Mapping[str, Any]) -> str:
    resume = f"Devis {maillon.get('devis_id')} approuvé pour envoi"
    if maillon.get("chantier_id"):
        resume += f", chantier {maillon['chantier_id']}"
    return resume


def _resume_devis_accepte(maillon: Mapping[str, Any]) -> str:
    resume = f"Devis {maillon.get('devis_id')} accepté"
    if maillon.get("chantier_id"):
        resume += f", chantier {maillon['chantier_id']}"
    return resume


def _resume_montants_devis_accepte(maillon: Mapping[str, Any]) -> str:
    # Jamais un montant : l'entrée est FINANCIAL et ne sort dans aucun paquet ; ce résumé n'en porte pas non plus,
    # pour qu'un marquage perdu ne puisse pas devenir une fuite.
    return f"Montants du devis {maillon.get('devis_id')} (niveau financier)"


def _resume_devis_sans_reponse(maillon: Mapping[str, Any]) -> str:
    return (
        f"Devis {maillon.get('devis_id')} ({maillon.get('statut')}) sans réponse depuis {maillon.get('depuis')}, "
        f"délai de relance {maillon.get('delai_relance_jours')} j"
    )


@dataclass(frozen=True)
class Etape:
    """Un type d'événement de l'amont : d'où il vient, ce qu'on en garde, comment on le lit."""

    type_evenement: str
    producteur: str  # seul émetteur déclaré au catalogue socle
    cle: str  # clé du maillon qui porte l'identifiant PUBLIC du fait (lead_id, devis_id)
    libelle: str  # consolidation nocturne : « 2 devis accepté(s) »
    niveau: str
    extraire: Callable[[Mapping[str, Any]], dict[str, Any]]
    resumer: Callable[[Mapping[str, Any]], str]
    # Compagnon FINANCIAL : ce que la charge porte de prix et de coût, en maillon à part.
    montants: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None
    resumer_montants: Callable[[Mapping[str, Any]], str] | None = None
    # Genres d'affaire (`affaire.GENRE_*`) que cette étape OUVRE : elle en est l'origine, celle dont M10 dit qu'il ne
    # l'a pas reçue (`AMONT-ORIGINE-NON-RECUE`). Vide : l'étape suit l'ouverture d'une affaire, elle ne l'ouvre pas.
    ouvre: tuple[str, ...] = ()


# Ordre de l'entonnoir : c'est celui de la consolidation. Une étape absente d'ici n'est pas consommée.
# `m3.devis_envoye` (T4.7) : l'envoi approuvé par le propriétaire, entre le client associé et l'acceptation.
# Deux étapes OUVRENT une affaire (PLAN T4.18-b) : M1 qualifie un lead ; M2 ouvre l'opportunité d'un client qui revient
# et publie alors son client associé. Le client associé d'un LEAD n'ouvre rien : M2 ingère un lead que M1 a ouvert, ou
# que quelqu'un a saisi hors de M1, et M10 ne peut pas le savoir (il dit l'origine non reçue).
_ETAPES = (
    Etape(
        TYPE_LEAD_QUALIFIE, "m01-front-office", "lead_id", "lead(s) qualifié(s)",
        confidentialite.NIVEAU_INTERNE, _extraire_lead_qualifie, _resume_lead_qualifie,
        ouvre=(affaire.GENRE_LEAD,),
    ),
    Etape(
        TYPE_CLIENT_ASSOCIE, "m02-revenue-crm", "lead_id", "client(s) associé(s)",
        confidentialite.NIVEAU_CLIENT_PRIVE, _extraire_client_associe, _resume_client_associe,
        ouvre=(affaire.GENRE_OPPORTUNITE,),
    ),
    Etape(
        TYPE_DEVIS_ENVOYE, "m03-estimation", "devis_id", "devis envoyé(s)",
        confidentialite.NIVEAU_INTERNE, _extraire_devis_envoye, _resume_devis_envoye,
    ),
    Etape(
        TYPE_DEVIS_ACCEPTE, "m03-estimation", "devis_id", "devis accepté(s)",
        confidentialite.NIVEAU_INTERNE, _extraire_devis_accepte, _resume_devis_accepte,
        _extraire_montants_devis_accepte, _resume_montants_devis_accepte,
    ),
    Etape(
        TYPE_DEVIS_SANS_REPONSE, "m03-estimation", "devis_id", "devis sans réponse",
        confidentialite.NIVEAU_INTERNE, _extraire_devis_sans_reponse, _resume_devis_sans_reponse,
    ),
)


def etapes_de_l_amont() -> tuple[Etape, ...]:
    return _ETAPES


def etape(type_evenement: Any) -> Etape | None:
    """L'étape d'un type d'événement du bus, ou ``None`` (type non consommé par cette table)."""
    return next((e for e in _ETAPES if e.type_evenement == type_evenement), None)


def origine_de(genre_de_l_affaire: str | None) -> str | None:
    """Le type du bus de l'étape qui OUVRE une affaire de ce genre (``affaire.genre``), ou ``None`` (genre inconnu :
    rien n'est deviné). Le lead qualifié de M1 ouvre un lead ; le client associé de M2 ouvre une opportunité."""
    return next((e.type_evenement for e in _ETAPES if genre_de_l_affaire in e.ouvre), None)


def types_consommes() -> tuple[str, ...]:
    """Les types du bus que M10 consomme pour l'amont, dans l'ordre de l'entonnoir."""
    return tuple(e.type_evenement for e in _ETAPES)


def type_montants(type_evenement: str) -> str:
    return type_evenement + SUFFIXE_MONTANTS


def _etape_du_maillon(maillon: Any) -> tuple[Etape, bool] | None:
    """``(étape, est_le_compagnon_financier)`` d'un maillon de l'amont, ou ``None``."""
    if not isinstance(maillon, Mapping) or maillon.get("type_entree") != _TYPE_ENTREE_EVENEMENT:
        return None
    type_maillon = maillon.get("type_evenement")
    for candidate in _ETAPES:
        if type_maillon == candidate.type_evenement:
            return candidate, False
        if candidate.montants is not None and type_maillon == type_montants(candidate.type_evenement):
            return candidate, True
    return None


def type_du_maillon(maillon: Any) -> str | None:
    """Le type d'un maillon de l'amont (celui du bus, ou celui de son compagnon financier), sinon ``None``."""
    trouve = _etape_du_maillon(maillon)
    if trouve is None:
        return None
    candidate, compagnon = trouve
    return type_montants(candidate.type_evenement) if compagnon else candidate.type_evenement


def cle_du_maillon(maillon: Any) -> str | None:
    """La clé publique du fait (``lead_id`` ou ``devis_id``), telle que le maillon la porte."""
    trouve = _etape_du_maillon(maillon)
    return None if trouve is None else maillon.get(trouve[0].cle)


def resume(maillon: Any) -> str | None:
    """Le résumé de paquet d'un maillon de l'amont, ou ``None`` s'il n'en est pas un."""
    trouve = _etape_du_maillon(maillon)
    if trouve is None:
        return None
    candidate, compagnon = trouve
    if compagnon:
        return candidate.resumer_montants(maillon) if candidate.resumer_montants is not None else None
    return candidate.resumer(maillon)
