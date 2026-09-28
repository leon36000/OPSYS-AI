"""Contrôle d'accès de la vue financière (PLAN T1.4-k2, docs/architecture/ROLES.md).

Module pur (même patron que ``acces.py`` de M4 : aucun import ``opsys``, aucune horloge, aucun
aléa). Il décide, il ne lit jamais l'identité : c'est ``outils.py`` (l'adaptateur, seul) qui la lit
dans ``opsys.contexte.identite_appelante()``, la fait confirmer par la base, et la passe ici sous
forme d'``Acteur``. Ce module ne reçoit donc jamais une identité que le modèle ou l'appareil a
écrite dans les arguments d'un outil.

POURQUOI. ``m5_etat_tresorerie`` prenait ``role`` et ``autorise_couts`` dans ses arguments : c'était
l'appelant qui choisissait ce qu'il avait le droit de voir. Pour un appel d'appareil, la vue vient
maintenant du rôle de la personne authentifiée.

TROIS CAS, jamais un quatrième :
  - ``acteur is None`` : appel sans jeton d'appareil (agent, console, outil interne). Comportement
    d'avant T1.4-k2, sans aucun contrôle de personne : ``role`` est une étiquette de l'appelant,
    ``autorise_couts`` reste OBLIGATOIRE et explicite (fail-closed : jamais une valeur par défaut qui
    exposerait un montant). Le secret partagé de la passerelle garde l'accès complet
    (docs/architecture/ROLES.md, « Voie des agents »).
  - appel d'appareil, rôle avec droit de voir les coûts (``admin``) : ``autorise_couts`` est DÉRIVÉ du
    rôle (table ci-dessous), jamais cru sur parole.
  - appel d'appareil, rôle sans portée sur l'outil : refus, avant de lire quoi que ce soit.

RÈGLE ÉCRITE (rôle -> droit de voir solde, argent disponible et taux). Fermée par défaut : un rôle
absent de la table ne voit pas les coûts.
  - ``admin`` : oui. DEFINITION-PRODUIT §9.5 (« M5 : trésorerie et cash libre réel ») et §7 M5
    « Mobile » (« Admin : ... trésorerie »).
  - ``employee`` : non. §9.2 (« l'employé ne voit jamais coûts, marges ni finances »).
  - ``seller`` : non. §9.4 (« Ne voit pas : finances globales, coûts internes au-delà de sa
    soumission ») ; le solde et l'argent disponible sont des finances globales.
Ni ``client`` (§9.6, lien tokenisé) ni ``nathan_owner`` ne portent de jeton d'appareil : sans entrée.

CE QUE LES ARGUMENTS PEUVENT FAIRE, pour un appel d'appareil (même règle que ``m3_lire_devis``, M3
T2.3-c : un argument ne peut que RESTREINDRE la vue, jamais l'élargir, et un refus est nommé, jamais
une correction silencieuse) :
  - ``autorise_couts`` absent (ou nul) : vaut le droit du rôle ;
  - ``autorise_couts=false`` : honoré, la vue est plus étroite que le droit (aperçu sans montants) ;
  - ``autorise_couts=true`` sans le droit : ``REJ-ROLE-ELARGI``, rien n'est lu ;
  - ``role`` absent (ou nul) ou égal au rôle authentifié : la réponse porte le rôle authentifié ;
  - ``role`` différent : ``REJ-IDENTITE-FOURNIE-DIFFERENTE``. Dans M5, ``role`` n'est pas un réglage de
    vue (c'est ``autorise_couts``) mais l'étiquette que la réponse porte et que son empreinte
    ``etat_id`` scelle : la seule étiquette fidèle est celle du jeton, et une autre n'a aucun sens
    à restreindre. Refusée, jamais remplacée en silence.
"""

from __future__ import annotations

import dataclasses

from . import validation

ROLE_ADMIN = "admin"
ROLE_EMPLOYE = "employee"
ROLE_VENDEUR = "seller"

__all__ = [
    "ROLE_ADMIN",
    "ROLE_EMPLOYE",
    "ROLE_VENDEUR",
    "Acteur",
    "acteur_de",
    "droit_couts",
    "resoudre_vue",
]

# La règle écrite ci-dessus, en code. Privée et fermée par défaut (`droit_couts` : absent = non).
_VOIT_LES_COUTS = {
    ROLE_ADMIN: True,
    ROLE_EMPLOYE: False,
    ROLE_VENDEUR: False,
}


@dataclasses.dataclass(frozen=True)
class Acteur:
    """Personne et rôle d'un jeton d'appareil, DÉJÀ confirmés par la base (voir ``outils.py``)."""

    personne: str
    role: str


def acteur_de(personne, role, roles_permis):
    """``(Acteur, None)`` si ``role`` est dans ``roles_permis``, sinon ``(None, verdict)``.

    ``roles_permis`` est la portée déclarée de l'outil (``Outil.roles_appareil``, la source unique
    que le core applique déjà en amont) : la repasser ici est une défense en profondeur, car le
    socle n'applique pas cette portée aux outils T0 hors du core. Un rôle hors portée n'obtient ni
    la vue sans montants ni un message qui décrit ce que l'outil aurait rendu."""
    if role not in roles_permis:
        return None, validation.construire_verdict(
            "REJ-IDENTITE-APPAREIL-INVALIDE",
            detail=f"rôle d'appareil {role!r} sans portée sur cet outil financier",
        )
    return Acteur(personne=personne, role=role), None


def droit_couts(role):
    """Vrai si ce rôle voit solde, argent disponible et taux (règle écrite en tête de module).

    Un rôle inconnu ne voit rien. Ne prend que le rôle, jamais un argument de l'appelant."""
    return _VOIT_LES_COUTS.get(role, False) is True


def _refus(code, detail):
    return None, validation.construire_verdict(code, detail=detail)


def resoudre_vue(acteur, role, autorise_couts):
    """``({"role", "autorise_couts"}, None)`` : la vue à construire, ou ``(None, verdict)`` : un refus.

    ``autorise_couts`` fourni doit être un booléen (jamais interprété par sa « vérité » : la chaîne
    ``"false"`` est vraie en Python) ou nul. Le verdict ne porte jamais un montant. Aucune lecture du
    registre ici : l'appelant ne lit qu'après un accord."""
    if autorise_couts is not None and not isinstance(autorise_couts, bool):
        return _refus(
            "REJ-AUTORISE-COUTS-REQUIS",
            "autorise_couts doit être un booléen (vrai ou faux), ou absent pour un appel d'appareil",
        )
    if acteur is None:
        if autorise_couts is None:
            return _refus(
                "REJ-AUTORISE-COUTS-REQUIS",
                "autorise_couts est obligatoire et explicite hors appel d'appareil : "
                "vrai pour voir solde, argent disponible et taux, faux pour un état sans montant",
            )
        return {"role": role, "autorise_couts": autorise_couts}, None

    if role is not None and role != acteur.role:
        return _refus(
            "REJ-IDENTITE-FOURNIE-DIFFERENTE",
            "role ne correspond pas au rôle authentifié : la réponse porte celui du jeton d'appareil, "
            "jamais une étiquette choisie par l'appelant",
        )
    droit = droit_couts(acteur.role)
    if autorise_couts is True and not droit:
        return _refus(
            "REJ-ROLE-ELARGI",
            f"autorise_couts=true demandé, mais le rôle authentifié {acteur.role!r} ne voit pas les "
            "coûts : autorise_couts ne peut que restreindre la vue, jamais l'élargir",
        )
    effectif = droit if autorise_couts is None else autorise_couts
    return {"role": acteur.role, "autorise_couts": effectif}, None
