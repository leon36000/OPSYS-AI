"""Contrôle d'accès de la déclaration des matériaux utilisés (PLAN T1.4-k, docs/architecture/ROLES.md).

Module pur (aucun import ``opsys``, aucune horloge) : il décide, il ne lit jamais l'identité. C'est
``outils.py`` (l'adaptateur, seul) qui lit ``opsys.contexte.identite_appelante()``, la fait confirmer
par la base et la passe ici sous forme d'``Acteur`` — jamais une identité que l'appareil ou le
modèle a écrite dans les arguments.

QUI A LE DROIT DE DÉCLARER. Le WCT relu à la source (T1.4-i, ``m4.travaux_termines``) porte le
``technicien_id`` du dernier pointage de départ : c'est la personne qui a réellement travaillé sur
cette intervention. Pour un appel d'appareil, l'identifiant de technicien EST celui de la personne
OPSYS (voir ``m4_field_ops.acces`` : un seul lien, tenu côté M4). Un ``employee`` ne déclare donc que
pour un WCT dont ce technicien est lui ; l'``admin`` déclare pour tous (il reprend un dossier) ; sans
identité d'appareil (agent, console) le comportement est inchangé, documenté dans ROLES.md.

CHANTIER. Le WCT ne porte aucun ``chantier_id`` (il vient de M4, où un chantier EST une intervention) :
celui du formulaire ne peut donc être confronté qu'à ce que M6 tient de la source, par le devis du
WCT (``devis_id`` -> besoins prévus, écrits à partir de ``m3.devis_accepte``). S'il y est connu, le
formulaire doit le porter (tous les appelants). S'il n'y est pas connu (aucun devis, aucun prévu,
prévu sans chantier), on ne devine rien pour un agent ou un admin, qui connaissent légitimement le
chantier d'un bon de commande ; mais un ``employee`` n'a aucune autre source que son intervention (c'est
aussi ce que l'app envoie) : son ``chantier_id`` doit être l'``intervention_id`` du WCT. Ce qui
détermine où le stock sort ne vient ainsi jamais de la seule affirmation de l'appareil d'un employé.
"""

from __future__ import annotations

import dataclasses

from . import verdicts

ROLE_EMPLOYE = "employee"
ROLE_ADMIN = "admin"

__all__ = [
    "ROLE_EMPLOYE",
    "ROLE_ADMIN",
    "Acteur",
    "acteur_de",
    "controler_declarant",
    "chantier_attendu",
    "controler_chantier",
]


@dataclasses.dataclass(frozen=True)
class Acteur:
    """Personne et rôle d'un jeton d'appareil, DÉJÀ confirmés par la base (voir ``outils.py``)."""

    personne: str
    role: str


def acteur_de(personne: str, role: str) -> tuple[Acteur | None, dict | None]:
    """``(Acteur, None)`` pour un rôle de terrain (``employee``, ``admin``), sinon ``(None, verdict)``.

    Fail-closed : la déclaration n'est ouverte qu'à ces deux rôles (``Outil.roles_appareil``) ; un
    autre rôle qui arriverait jusqu'ici n'a aucune portée sur elle, on ne lui en invente pas une."""
    if role not in (ROLE_EMPLOYE, ROLE_ADMIN):
        return None, verdicts.construire_verdict(
            "REJ-IDENTITE-APPAREIL-INVALIDE",
            detail=f"rôle d'appareil {role!r} sans portée sur la déclaration des matériaux utilisés",
        )
    return Acteur(personne=personne, role=role), None


def _accede_a_tout(acteur: Acteur | None) -> bool:
    return acteur is None or acteur.role == ROLE_ADMIN


def controler_declarant(wct: dict, acteur: Acteur | None) -> dict | None:
    """``None`` si l'acteur peut déclarer pour ce WCT, sinon un verdict.

    ``employee`` : le ``technicien_id`` du WCT doit être SA personne. Un WCT d'un autre technicien, ou
    sans technicien, donne le même refus (``REJ-INTERVENTION-NON-ASSIGNEE``) : rien sur les autres
    n'est révélé."""
    if _accede_a_tout(acteur):
        return None
    if wct.get("technicien_id") != acteur.personne:
        return verdicts.construire_verdict(
            "REJ-INTERVENTION-NON-ASSIGNEE",
            detail="ce chantier n'est pas assigné à la personne authentifiée",
        )
    return None


def chantier_attendu(wct: dict, besoin: dict | None, acteur: Acteur | None) -> str | None:
    """Le ``chantier_id`` que le formulaire doit porter, ou ``None`` si la source n'en impose aucun.

    1. Le prévu du devis du WCT (``besoin``, ou ``None`` si aucun) le connaît : c'est lui.
    2. Sinon, pour un ``employee`` seulement : l'``intervention_id`` du WCT (un chantier de M4 EST une
       intervention).
    3. Sinon ``None`` : agent ou admin, la source ne dit rien, rien n'est deviné (fail-closed n'est pas
       « refuser tout » ici : le prévu peut légitimement manquer, ``prevu_absent``)."""
    if besoin is not None and besoin.get("chantier_id") is not None:
        return besoin["chantier_id"]
    if acteur is not None and acteur.role == ROLE_EMPLOYE:
        return wct["intervention_id"]
    return None


def controler_chantier(formulaire: dict, wct: dict, besoin: dict | None, acteur: Acteur | None) -> dict | None:
    """``None`` si le ``chantier_id`` du formulaire concorde avec la source, sinon un verdict
    ``REJ-FORMULAIRE-MATERIAUX-CHANTIER-INCOHERENT``. Suppose le formulaire déjà validé
    structurellement (``validation.valider_formulaire_materiaux_utilises``)."""
    attendu = chantier_attendu(wct, besoin, acteur)
    if attendu is None or formulaire["chantier_id"] == attendu:
        return None
    return verdicts.construire_verdict(
        "REJ-FORMULAIRE-MATERIAUX-CHANTIER-INCOHERENT",
        detail=(
            "chantier_id du formulaire ne concorde pas avec le chantier de ce WCT, tel que M6 le "
            "tient de la source (prévu du devis, sinon l'intervention)"
        ),
    )
