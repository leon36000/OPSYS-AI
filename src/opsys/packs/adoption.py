"""Adopter une proposition d'un pack : le geste signé qui fait entrer un élément dans le profil d'entreprise.

Un pack PROPOSE (`propositions_profil` de son manifeste, tout `a_valider`) ; il n'écrit jamais dans le profil et choisir
un pack n'active rien : les départements ne lisent que `entreprise.yaml` (`opsys.taxonomie`). Ce module est l'unique
chemin d'une proposition vers ce fichier, un ÉLÉMENT à la fois (questions de qualification, vocabulaire des plaintes,
destinataires de transfert, fenêtre de conversation, poids du score), par une personne qui signe (journal d'audit).

Règles, toutes fail-closed :

- le pack doit être celui que le profil a choisi (`pack:`), installé, valide et non altéré (empreinte) ;
- l'élément est de la liste fermée `ELEMENTS` et le pack le propose ;
- ce que le propriétaire a déjà déclaré prime : une valeur différente en place n'est JAMAIS écrasée
  (`REJ-PACK-ADOPTION-ECRASE`) ; il la change lui-même par les fonctions `enregistrer_*` de `opsys.taxonomie` ;
- une valeur identique en place est une adoption déjà faite : rien n'est écrit ni journalisé (idempotence) ;
- une valeur illisible en place n'est jamais lue comme absente (`REJ-PACK-PROFIL-INVALIDE`) ;
- l'écriture passe par les `enregistrer_*` du profil (mêmes validations que pour une saisie à la main) ; le statut
  `a_valider` du pack n'entre pas dans le profil.

L'adoption est un geste de ligne de commande (`opsys-metier pack adopter`), comme le choix du pack : ce n'est PAS une
approbation N3 de la console. Elle ne valide ni la justesse des mots ni des chiffres proposés, et ne lève aucune autre
garde (par exemple la politique « photos », qui reste fermée tant qu'elle n'est pas validée).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .. import taxonomie
from .codes import RefusPack
from .manifeste import ELEMENTS_PROPOSES, Pack
from .resolution import charger_pack, pack_declare

ELEMENTS = ELEMENTS_PROPOSES

ETAT_NON_ADOPTEE = "non_adoptee"
ETAT_ADOPTEE = "adoptee"
ETAT_DIFFERENTE = "differente"

# élément -> (lecture du profil, écriture du profil, vide quand absent)
_PROFIL = {
    taxonomie.CLE_QUESTIONS_QUALIFICATION: (taxonomie.lire_questions_qualification,
                                            taxonomie.enregistrer_questions_qualification),
    taxonomie.CLE_SIGNAUX_PLAINTE: (taxonomie.lire_signaux_plainte, taxonomie.enregistrer_signaux_plainte),
    taxonomie.CLE_DESTINATAIRES_TRANSFERT: (taxonomie.lire_destinataires_transfert,
                                            taxonomie.enregistrer_destinataires_transfert),
    taxonomie.CLE_FENETRE_CONVERSATION: (taxonomie.lire_fenetre_conversation,
                                         taxonomie.enregistrer_fenetre_conversation),
    taxonomie.CLE_POIDS_SCORE_LEAD: (taxonomie.lire_poids_score_lead, taxonomie.enregistrer_poids_score_lead),
}


def _compte(valeur: Any) -> dict[str, Any]:
    """Des comptes pour le journal d'audit : jamais les mots, les questions ni les rôles eux-mêmes."""
    if isinstance(valeur, dict):
        return {"entrees": len(valeur)}
    return {"entrees": 1}


def _pack_adoptable(pack_id: str | None, profil: Path | None, racine: Path | None) -> Pack:
    declare = pack_declare(profil)
    if declare is None or (pack_id is not None and pack_id != declare):
        raise RefusPack(
            "REJ-PACK-ADOPTION-PACK-INACTIF",
            f"le profil a choisi le pack {declare!r}" + (f", pas {pack_id!r}" if pack_id else "")
            + " : choisis-le d'abord (`opsys-metier pack choisir <id> --par NOM`), puis adopte ses propositions",
            "pack")
    return charger_pack(declare, racine)


def _lire_profil(element: str, profil: Path | None) -> Any:
    try:
        return _PROFIL[element][0](profil)
    except taxonomie.ProfilInvalide as exc:
        raise RefusPack("REJ-PACK-PROFIL-INVALIDE", f"valeur en place illisible pour {element!r} : {exc}",
                        "entreprise.yaml") from exc


def _propositions(pack: Pack, element: str) -> Any:
    if element not in ELEMENTS:
        raise RefusPack("REJ-PACK-ADOPTION-ELEMENT-INCONNU",
                        f"élément {element!r} inconnu (éléments adoptables : {', '.join(ELEMENTS)})", "element")
    p = pack.propositions_profil
    if p is None or element not in p.elements:
        raise RefusPack("REJ-PACK-ADOPTION-ELEMENT-INCONNU",
                        f"le pack {pack.id!r} ne propose pas {element!r}", "element")
    return p.elements[element]


def _etat(propose: Any, en_place: Any) -> str:
    if en_place in ({}, None):
        return ETAT_NON_ADOPTEE
    return ETAT_ADOPTEE if en_place == propose else ETAT_DIFFERENTE


def etat_des_propositions(pack_id: str | None = None, *, profil: Path | None = None,
                          racine: Path | None = None) -> list[dict[str, Any]]:
    """Pour chaque élément proposé par le pack du profil : `non_adoptee` (rien en place), `adoptee` (identique à la
    proposition) ou `differente` (le propriétaire a déclaré autre chose). Lecture seule."""
    pack = _pack_adoptable(pack_id, profil, racine)
    if pack.propositions_profil is None:
        return []
    return [
        {"element": e, "statut_pack": "a_valider", **_compte(valeur),
         "etat": _etat(valeur, _lire_profil(e, profil))}
        for e, valeur in pack.propositions_profil.elements.items()
    ]


def adopter_proposition(element: str, *, par: str | None, pack_id: str | None = None, profil: Path | None = None,
                        racine: Path | None = None) -> dict[str, Any]:
    """Écrit dans le profil l'élément proposé par le pack choisi, signé par `par` au journal d'audit.

    Rend `{element, pack, version, empreinte, ecrit, fichier}` ; `ecrit` vaut `False` quand le profil portait déjà
    exactement cette valeur (rien n'est alors écrit ni journalisé)."""
    if not isinstance(par, str) or not par.strip():
        raise RefusPack("REJ-PACK-ADOPTION-SANS-SIGNATURE",
                        "adopter une proposition est un geste signé : dis qui l'adopte (`--par NOM`)", "par")
    pack = _pack_adoptable(pack_id, profil, racine)
    propose = _propositions(pack, element)
    en_place = _lire_profil(element, profil)
    fichier = profil or taxonomie.fichier_profil()
    resultat = {"element": element, "pack": pack.id, "version": pack.version, "empreinte": pack.empreinte,
                "fichier": str(fichier)}
    etat = _etat(propose, en_place)
    if etat == ETAT_ADOPTEE:
        return {**resultat, "ecrit": False}
    if etat == ETAT_DIFFERENTE:
        raise RefusPack("REJ-PACK-ADOPTION-ECRASE",
                        f"le profil déclare déjà {element!r} ({en_place!r}) : la valeur du propriétaire n'est jamais "
                        "écrasée ; modifie-la toi-même avec les fonctions `enregistrer_*` de opsys.taxonomie",
                        "entreprise.yaml")
    _PROFIL[element][1](propose, profil)  # mêmes validations qu'une saisie à la main ; sans signature propre
    from ..etat import journaliser, session  # importé ici : le journal n'est utile qu'à l'écriture

    with session() as cnx:
        journaliser(cnx, par.strip(), "entreprise.adoption_proposition", str(fichier),
                    {"element": element, "pack": pack.id, "version": pack.version, "empreinte": pack.empreinte,
                     **_compte(propose)})
    return {**resultat, "ecrit": True}
