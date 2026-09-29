"""Capacités d'agent du département M3 Estimation.

Chaque outil enveloppe une fonction métier déterministe existante : aucune n'est réécrite.
`m3_estimer_projet` compose la chaîne complète en un seul appel, ce qui évite à l'agent
cinq allers-retours (économie de tokens) et garantit l'ordre des contrôles. Le prix n'est
jamais calculé quand il doit être bloqué.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select

from opsys import contexte, evenements, identite, jetons, stockage, taxonomie
from opsys.outils import Autonomie, Niveau, Outil, depuis_couple
from opsys.stockage.schema import APPROBATIONS

from . import (
    besoins_materiaux,
    contrats,
    devis_durable,
    devis_relance,
    estimation,
    estime_vs_reel,
    hierarchie_echelle,
    monte_carlo,
    plancher,
    politique_photos,
    qualite_photos,
    registre,
    revue_devis,
    soumission,
    soumission_pdf,
    verdicts,
)

# Chemin du document de politique Loi 25 « photos » (PLAN T2.3, docs/departements/M3-audit.md §5
# point 2), dérivé de __file__ — JAMAIS du répertoire courant (même discipline que les tests M3,
# ex. tests/_commun_contrats.py). parents[4] depuis src/m3_estimation/outils.py atteint la racine
# du dépôt : m3_estimation -> src -> m03-estimation -> departments -> racine.
_CHEMIN_POLITIQUE_PHOTOS = (
    Path(__file__).resolve().parents[4]
    / "docs"
    / "compliance"
    / "politiques"
    / "POLITIQUE-photos-non-contractuelles.md"
)

_PHOTO = {
    "type": "object",
    "properties": {
        "photo_id": {"type": "string"},
        "resolution_largeur": {"type": "integer"},
        "resolution_hauteur": {"type": "integer"},
        "eclairage": {"type": "number", "description": "0 à 10"},
        "angle": {"type": "string"},
        "reference_echelle": {
            "type": ["object", "null"],
            "description": "{type, dimensions_connues} ou null si aucun objet de référence",
        },
    },
    "required": list(contrats.CHAMPS_PHOTO),
}
_SEUILS = {
    "type": "object",
    "properties": {"resolution_minimale": {"type": "integer"}, "eclairage_minimal": {"type": "number"}},
    "required": list(contrats.CHAMPS_SEUILS_QUALITE),
}
_BAREME = {
    "type": "object",
    "description": (
        "{version, unite, postes: {service (lead v2) ou type_travaux (lead v1) : {cout_unitaire_min, "
        "cout_unitaire_max, "
        "duree_minutes_par_unite (optionnel — minutes de main-d'œuvre par unité de quantite ; "
        "absent : aucune durée n'est calculée), materiaux (optionnel — liste de {materiau, sku "
        "(optionnel), quantite_par_unite (texte décimal), unite, facteur_perte (optionnel, texte "
        "décimal 0 <= f < 1)} ; absent : aucun besoin matériau n'est publié)}}}"
    ),
}
# Type de travaux v1 (énuméré gelé) OU code de service v2 (taxonomie du socle, profil d'entreprise) :
# le schéma ne fige pas d'énuméré, la validation métier tranche et dit quoi configurer.
_TYPE_TRAVAUX = {
    "type": "string",
    "description": (
        "type de travaux v1 (" + ", ".join(contrats.TYPES_TRAVAUX) + ") ou code d'un service "
        "déclaré par l'entreprise (lead v2)"
    ),
}
_CONTRAT = {
    "type": "object",
    "description": (
        "LeadQualifie émis par M2, dans la version qu'il déclare. v1 (gelée, sans schema_version) : "
        "sept clés dont type_travaux. v2 (schema_version = 2) : service (code déclaré par le profil "
        "d'entreprise) remplace type_travaux. source/utm/campagne optionnels."
    ),
    "properties": {
        "schema_version": {"type": "integer", "enum": [contrats.VERSION_CONTRAT_V2], "description": "v2 seulement."},
        "lead_id": {"type": "string"},
        "conversation_id": {"type": "string"},
        "type_travaux": {
            "type": "string", "enum": list(contrats.TYPES_TRAVAUX), "description": "v1 seulement (énuméré gelé).",
        },
        "service": {"type": "string", "description": "v2 seulement : code d'un service déclaré."},
        "ville": {"type": "string"},
        "canal": {"type": "string"},
        "contact": {"type": "object"},
        "urgence_declaree": {"type": "boolean"},
        "source": {"type": "string"},
        "campagne": {"type": "string"},
        "utm": {"type": "object"},
    },
    "required": [c for c in contrats.CHAMPS_CONTRAT_GELE if c != "type_travaux"],
    "additionalProperties": False,
}
_MARQUEUR = {
    "type": "object",
    "description": "Marqueur de readiness signé par M2 (contrats.CHAMPS_MARQUEUR), cinq clés gelées.",
    "properties": {
        "readiness_ok": {"type": "boolean"},
        "lead_id": {"type": "string"},
        "hash_tete_registre": {"type": ["string", "null"]},
        "horodatage": {"type": "string"},
        "empreinte": {"type": "string"},
    },
    "required": list(contrats.CHAMPS_MARQUEUR),
    "additionalProperties": False,
}
_LIGNE_DEVIS = {
    "type": "object",
    "properties": {
        "description": {"type": "string"},
        "quantite": {"type": "string", "description": "texte décimal, ex. \"12.5\" (jamais un nombre JSON)"},
        "unite": {"type": "string"},
        "cout_unitaire": {
            "type": "string",
            "description": "texte décimal CAD, coût unitaire — jamais un prix, le prix est calculé",
        },
        "reference_besoin_materiau": {
            "type": ["string", "null"],
            "description": "référence du besoin matériau (M6), ou null si cette ligne n'en a pas",
        },
    },
    "required": ["description", "quantite", "unite", "cout_unitaire", "reference_besoin_materiau"],
    "additionalProperties": False,
}


# -- projection par l'identité AUTHENTIFIÉE du jeton d'appareil (PLAN T1.4-c4) -------------------
#
# `opsys.contexte.identite_appelante()` porte la personne et le rôle d'un appel d'appareil,
# AUTHENTIFIÉS par OPSYS-CORE (jeton d'appareil vérifié, jamais le corps de la requête) ; hors
# appel d'appareil (Hermes, Claude Code, un outil interne), elle vaut None. Chaque rôle de jeton
# d'appareil (`opsys.appareils.ROLES_APPAREIL` : admin/employee/seller, le sous-ensemble mobile de
# `opsys.identite.Role`) est ici associé à une des DEUX vues de projection connues de M3
# (`devis_durable._ROLES_CONNUS` : "interne" = complète, "employe" = sans coût, marge ni prix) :
#
#   - EMPLOYEE -> "employe" : DEFINITION-PRODUIT.md §9.2, ligne 706 — « l'employé ne voit jamais
#     coûts, marges ni finances ».
#   - SELLER (vendeur) -> "interne" : §9.4 (lignes 723-724) — le vendeur voit les « risques et
#     marge » et la « marge estimée de la soumission » de SES leads ; §9.4 (ligne 727) ne lui
#     retire que les finances GLOBALES et les coûts internes AU-DELÀ de sa propre soumission —
#     jamais la marge/le prix de CE devis_id précis, seul niveau que M3 projette ici. Il n'existe
#     aucune troisième vue (« voit le prix mais pas le coût ») dans `devis_durable.py` à ce jour :
#     ajouter cette nuance serait un contrat de projection de plus, hors du périmètre de cette
#     tranche (voir le rapport de livraison).
#   - ADMIN -> "interne" : §9.5 — approuve tout (factures, PO, soumissions risquées), l'appareil du
#     propriétaire est apparié avec role="admin" (opsys.appareils, même module) : mêmes routes
#     qu'un admin, jamais moins.
_VUE_PAR_ROLE_APPAREIL: dict[str, str] = {
    identite.Role.EMPLOYEE.value: "employe",
    identite.Role.SELLER.value: "interne",
    identite.Role.ADMIN.value: "interne",
}


def _vue_projection_effective(role_demande: str | None) -> dict[str, Any]:
    """Résout le rôle de PROJECTION M3 ("interne"/"employe") pour l'appel courant.

    Hors appel d'appareil (`contexte.identite_appelante() is None`) : rend `role_demande` s'il est
    fourni, sinon "interne" — comportement HISTORIQUE inchangé (PLAN T2.3-a), documenté ici plutôt
    que redécidé à chaque appelant.

    Pendant un appel d'appareil (PLAN T1.4-c4) : la vue DÉCOULE du rôle authentifié par
    OPSYS-CORE — REVÉRIFIÉ ici contre `opsys.identite.personne_active` (la personne existe encore,
    est active, ET porte encore ce rôle ; `IdentiteAppelante` ne garantit ni l'un ni l'autre, voir
    sa docstring) : une personne désactivée ou un rôle retiré APRÈS l'émission du jeton ne doit
    jamais continuer de projeter une vue périmée. `role_demande` ne peut alors que RESTREINDRE
    cette vue, jamais l'élargir :
      - absent (None) : vaut la vue authentifiée ;
      - fourni, ÉGAL ou plus étroit ("employe" demandé sous une vue "interne" autorisée) : honoré ;
      - fourni PLUS LARGE que la vue autorisée ("interne" demandé sous une vue "employe") : refus
        NOMMÉ (`REJ-ROLE-ELARGI`) — jamais élargi, jamais rabattu silencieusement sur la vue
        autorisée (un appelant qui se trompe de rôle doit le savoir, pas être corrigé en silence).

    Rend toujours `{"accepte": True, "role": <vue>, "personne": ..., "role_appareil": ...}` ou
    `{"accepte": False, "verdict": <verdict>}` — jamais une exception. `personne` et `role_appareil` sont
    ceux de l'identité CONFIRMÉE (None hors appel d'appareil) : PLAN T1.4-k2, ils servent au filtre par
    propriétaire de lead (`_hors_portee_du_vendeur`), qui ne relit jamais l'identité lui-même."""
    identite_dispositif = contexte.identite_appelante()
    if identite_dispositif is None:
        return {
            "accepte": True, "role": role_demande if role_demande is not None else "interne",
            "personne": None, "role_appareil": None,
        }

    cnx = stockage.connexion_courante()
    personne = identite.personne_active(cnx, identite_dispositif.personne) if cnx is not None else None
    if personne is None or identite_dispositif.role not in personne.roles:
        return {
            "accepte": False,
            "verdict": verdicts.construire_verdict(
                "REJ-IDENTITE-APPAREIL-INVALIDE",
                detail=(
                    f"personne {identite_dispositif.personne!r} inconnue, inactive, ou ne porte "
                    f"plus le rôle {identite_dispositif.role!r} porté par le jeton d'appareil"
                ),
            ),
        }

    vue_autorisee = _VUE_PAR_ROLE_APPAREIL.get(identite_dispositif.role)
    if vue_autorisee is None:
        return {
            "accepte": False,
            "verdict": verdicts.construire_verdict(
                "REJ-IDENTITE-APPAREIL-INVALIDE",
                detail=f"rôle d'appareil {identite_dispositif.role!r} sans vue M3 connue",
            ),
        }
    confirmee = {"personne": personne.identifiant, "role_appareil": identite_dispositif.role}
    if role_demande is None:
        return {"accepte": True, "role": vue_autorisee, **confirmee}
    if vue_autorisee == "interne" or role_demande == vue_autorisee:
        return {"accepte": True, "role": role_demande, **confirmee}
    return {
        "accepte": False,
        "verdict": verdicts.construire_verdict(
            "REJ-ROLE-ELARGI",
            detail=(
                f"role={role_demande!r} demandé, mais l'appareil authentifié (rôle "
                f"{identite_dispositif.role!r}) n'autorise que {vue_autorisee!r} — le paramètre "
                "role ne peut que restreindre, jamais élargir"
            ),
        ),
    }


# -- propriétaire d'un lead (PLAN T1.4-k2) --------------------------------------------------------
#
# Un vendeur ne lit que les devis des leads dont il est le PROPRIÉTAIRE. Le propriétaire d'un lead est
# une donnée de M2 (`owner` de la qualification) : M3 ne la reçoit jamais de l'appelant et n'en tient
# aucune copie. Elle est relue à la source du bus (`evenements.charge_publiee`, comme M6 relit le WCT de
# M4, T1.4-i) dans le fait `m2.lead_assigne` que M2 publie dans la transaction de la qualification. Aucun
# import de M2 (#109). L'identifiant d'événement est une convention du contrat du catalogue
# (`m2.lead_assigne.json`) ; `tests/test_acces_par_proprietaire.py` du socle la prouve de bout en bout.
_TYPE_EVENEMENT_LEAD_ASSIGNE = "m2.lead_assigne"
_ROLE_VENDEUR = identite.Role.SELLER.value
_ROLES_SOUMISSION = frozenset({_ROLE_VENDEUR, identite.Role.ADMIN.value})


def _proprietaire_du_lead(lead_id: Any) -> str | None:
    """Le propriétaire COURANT du lead tel que M2 l'a publié, ou None : lead sans fait de propriété (jamais
    qualifié, inconnu de M2, ou qualifié avant T1.4-k2 et jamais republié), `lead_id` invalide, ou aucune
    transaction (rien n'est joignable hors d'un appel d'outil : fail-closed, jamais un propriétaire supposé).

    Le fait est versionné par un rang (PLAN T1.4-m, `m2.lead_assigne.json`) : la qualification est le rang 1
    (`m2-lead-assigne-<lead_id>`), chaque réassignation un rang n >= 2 (`m2-lead-reassigne-<n>-<lead_id>`, qui
    porte `rang: n`). Le propriétaire courant est celui du plus grand rang publié : on lit le rang 1, puis les
    rangs 2, 3... jusqu'au premier absent. Un rang 1 absent n'arrête pas la lecture (un lead réassigné avant
    la republication de son fait)."""
    if stockage.connexion_courante() is None or not isinstance(lead_id, str) or not lead_id:
        return None
    proprietaire = None
    charge = evenements.charge_publiee(_TYPE_EVENEMENT_LEAD_ASSIGNE, f"m2-lead-assigne-{lead_id}")
    if charge is not None and charge.get("lead_id") == lead_id:
        proprietaire = charge.get("proprietaire")
    rang = 2
    while True:
        charge = evenements.charge_publiee(_TYPE_EVENEMENT_LEAD_ASSIGNE, f"m2-lead-reassigne-{rang}-{lead_id}")
        if charge is None or charge.get("lead_id") != lead_id or charge.get("rang") != rang:
            return proprietaire
        proprietaire = charge.get("proprietaire")
        rang += 1


def _hors_portee_du_vendeur(vue: dict[str, Any], devis: dict[str, Any]) -> bool:
    """Vrai si l'appelant est un vendeur (appareil authentifié et confirmé) dont ce devis n'est pas celui
    d'un de SES leads. Admin, employé (qui ne voit ni coût, ni marge, ni prix : T2.3-d) et appel sans
    appareil : faux, aucun filtre par propriétaire."""
    if vue.get("role_appareil") != _ROLE_VENDEUR:
        return False
    return _proprietaire_du_lead(devis.get("lead_id")) != vue["personne"]


def _devis_inconnu(devis_id: str) -> dict[str, Any]:
    """Le refus d'un devis absent du registre (même code et même détail que `devis_durable.lire_devis`),
    rendu aussi à un vendeur pour le devis d'un autre : les deux cas sont indiscernables."""
    return verdicts.construire_verdict("REJ-DEVIS-INTROUVABLE", detail=f"devis inconnu : {devis_id!r}")


def _projeter_estimation_employe(reponse: dict[str, Any]) -> dict[str, Any]:
    """Retire coût et prix de la réponse de `m3_estimer_projet` pour la vue "employe" —
    DEFINITION-PRODUIT.md §9.2 : « l'employé ne voit jamais coûts, marges ni finances ». Même
    principe que `devis_durable.projeter_devis`, appliqué à un contrat différent (la réponse
    composée de l'orchestrateur, pas un devis) : `intervalle_confiance` (l'intervalle de COÛT,
    EstimationV1, champ gelé) garde sa forme et son `niveau`, seules ses bornes chiffrées sont
    retirées — même convention que la voie `prix_bloque` de `blocage_prix.py` (None, jamais 0).
    `prix_recommande` (marge) est entièrement retiré. Rien d'autre ne change : verdicts, ids,
    signal de relance, durée de main-d'œuvre ne sont ni de l'argent ni un risque de fuite."""
    projection = dict(reponse)
    if isinstance(projection.get("estimation"), dict):
        intervalle = projection["estimation"].get("intervalle_confiance")
        if isinstance(intervalle, dict):
            projection["estimation"] = {
                **projection["estimation"],
                "intervalle_confiance": {**intervalle, "borne_basse": None, "borne_haute": None},
            }
    projection["prix_recommande"] = None
    return projection


def qualifier_photos(photos: list[dict[str, Any]], seuils: dict[str, Any]) -> dict[str, Any]:
    return depuis_couple(qualite_photos.qualifier_photos(photos, seuils))


def classifier_confiance(photos: list[dict[str, Any]], seuils: dict[str, Any]) -> dict[str, Any]:
    # Convention propre à cette fonction : (niveau, motifs) si valide, (None, verdict) sinon.
    niveau, info = hierarchie_echelle.classifier_niveau_confiance(photos, seuils)
    if niveau is None:
        return {"accepte": False, "verdict": info}
    return {"accepte": True, "resultat": {"niveau_confiance": niveau, "motifs": info}}


def simuler_intervalle(
    bareme: dict[str, Any], type_travaux: str, quantite: float, graine: int, niveau: float = 0.9
) -> dict[str, Any]:
    services: tuple[str, ...] = ()
    if isinstance(type_travaux, str) and type_travaux not in contrats.TYPES_TRAVAUX:
        # Ni type v1 ni rien d'autre : c'est un service, qui doit être déclaré par l'entreprise. Le
        # refus porte le verdict du socle (quoi configurer), jamais un repli sur un autre poste.
        service, verdict_service = taxonomie.valider_service(type_travaux)
        if verdict_service is not None:
            return {"accepte": False, "verdict": verdicts.construire_verdict(
                "REJ-CONTRAT-INVALIDE",
                detail=f"service {type_travaux!r} : {verdict_service['code']} : {verdict_service['detail']}",
            )}
        services = (service.code,)
    intervalle, rejet = monte_carlo.simuler_intervalle(
        bareme, type_travaux, quantite, graine, niveau, services=services
    )
    if rejet is not None:
        return depuis_couple((intervalle, rejet))
    intervalle = {
        "borne_basse": estimation.arrondir_au_cent(intervalle["borne_basse"]),
        "borne_haute": estimation.arrondir_au_cent(intervalle["borne_haute"]),
        "niveau": intervalle["niveau"],
    }
    return depuis_couple((intervalle, None))


def confronter_plancher(intervalle: dict[str, Any], plancher_rentable: float) -> dict[str, Any]:
    return depuis_couple(plancher.confronter_au_plancher(intervalle, plancher_rentable))


def estimer_projet(
    contrat: dict[str, Any],
    marqueur: dict[str, Any],
    photos: list[dict[str, Any]],
    seuils: dict[str, Any],
    bareme: dict[str, Any],
    quantite: float,
    plancher_rentable: float,
    graine: int | None = None,
    taux_marge: str | None = None,
) -> dict[str, Any]:
    """Point d'entrée agent (PLAN T2.3) : appelle l'orchestrateur pur
    `estimation.orchestrer_estimation` sur le registre DURABLE de production. Toute la logique
    métier vit dans `estimation.py` (validation, qualité photos, hiérarchie d'échelle, blocage,
    Monte Carlo, plancher, alerte REFERENCE_ECHELLE_ABSENTE, durée main-d'œuvre, prix recommandé,
    signal de relance M2, registre, contrat gelé EstimationV1) ; cette fonction ne fait que choisir
    le support durable — même patron que `creer_devis`/`lire_devis` ci-dessous pour le registre des
    devis.

    Projection par l'identité authentifiée (PLAN T1.4-c4, `_vue_projection_effective`) : résolue
    AVANT tout appel à l'orchestrateur, pour qu'une identité d'appareil périmée n'écrive jamais au
    registre durable (aucun effet de bord avant un refus). Vue "employe" : la réponse retire coût
    et prix (`_projeter_estimation_employe`) — hors appel d'appareil, ou appareil admin/vendeur,
    comportement inchangé (PLAN T2.3-b).

    Besoins matériaux (PLAN T2.3-e) : quand l'estimation produit des quantités (le poste du barème
    porte `materiaux`, prix non bloqué), le contrat `BesoinsMateriauxM3` est publié sur le bus
    (`m3.besoins_materiaux`) DANS la même transaction que l'inscription au registre : les deux
    réussissent ou échouent ensemble. Publié tel quel, sans projection : il ne porte ni coût, ni
    prix, ni marge."""
    vue = _vue_projection_effective(None)
    if not vue["accepte"]:
        return {"etape": "identite_appareil", "accepte": False, "verdict": vue["verdict"]}
    resultat = estimation.orchestrer_estimation(
        contrat, marqueur, photos, seuils, bareme, quantite, plancher_rentable,
        registre_production(), graine, taux_marge,
    )
    if resultat.get("accepte") is True and resultat.get("besoins_materiaux") is not None:
        _publier_besoins_materiaux(resultat["besoins_materiaux"])
    if vue["role"] == "employe" and resultat.get("accepte") is True:
        return _projeter_estimation_employe(resultat)
    return resultat


def _publier_besoins_materiaux(contrat: dict[str, Any]) -> str:
    """Publie `m3.besoins_materiaux` sous un `evenement_id` déterministe (devis + version
    d'estimation) : republier la même version est un no-op du bus, jamais un second événement.
    Lève `ChargeInvalide` si le contrat ne respecte pas le schéma du catalogue — un défaut de
    programmation, que le bus refuse sans rien écrire."""
    return evenements.publier(
        besoins_materiaux.TYPE_EVENEMENT_BESOINS_MATERIAUX,
        "m03-estimation",
        contrat,
        evenement_id=besoins_materiaux.identifiant_evenement(contrat),
    )


def registre_production() -> registre.Registre:
    """Registre M3 adossé au stockage durable de l'instance (ADR-0009).

    `registre.py` reste pur : il ignore que ses maillons viennent d'une liste Python ou de
    `opsys.stockage.MaillonsDurables`. C'est ce point d'entrée — jamais `registre.py` — qui
    choisit le support durable pour un registre de production, dans la transaction courante
    (`opsys.stockage.transaction()`, ouverte par l'appelant ou par `Capacites.appeler`). Les
    tests unitaires du département construisent `registre.Registre()` EN MÉMOIRE, explicitement,
    sans passer par cette fonction.
    """
    return registre.Registre(stockage.maillons("m03-estimation", "principal"))


def registre_devis_production() -> stockage.MaillonsDurables:
    """Registre M3 des DEVIS (PLAN T2.3-a), adossé au stockage durable de l'instance (ADR-0009) :
    `opsys.stockage.maillons("m03-estimation", "devis")`, dans la base et la transaction de
    l'appel courant, relu à chaque appel, jamais mis en cache — même discipline que
    `registre_production` ci-dessus, mais DÉLIBÉRÉMENT une collection distincte ("devis", jamais
    "principal") : le registre "principal" porte les charges d'ESTIMATION Monte Carlo (S008, six
    clés fixes dont `niveau_confiance`/`bareme_version`/`graine_monte_carlo`, hash-chaînées par
    `registre.Registre`), pas les lignes commerciales d'un devis (voir la docstring de
    `devis_durable.py`). `devis_durable.py` reste pur : il ignore que ses maillons viennent d'une
    liste Python (tests unitaires, construite EN MÉMOIRE, explicitement, sans passer par cette
    fonction) ou de `opsys.stockage.MaillonsDurables` (production, ce point d'entrée) — c'est ce
    point d'entrée, jamais `devis_durable.py`, qui choisit le support durable."""
    return stockage.maillons("m03-estimation", "devis")


def creer_devis(
    devis_id: str,
    lead_id: str,
    chantier_id: str | None,
    lignes: list[dict[str, Any]],
    taux_marge: str,
    horodatage: str,
    prix_total: str | None = None,
) -> dict[str, Any]:
    return depuis_couple(
        devis_durable.creer_devis(
            devis_id,
            lead_id,
            chantier_id,
            lignes,
            taux_marge,
            horodatage,
            registre_devis_production(),
            prix_total_fourni=prix_total,
        )
    )


def lire_devis(devis_id: str, role: str | None = None) -> dict[str, Any]:
    """Lit un devis durable, projeté par la vue AUTHENTIFIÉE (PLAN T1.4-c4,
    `_vue_projection_effective`) plutôt que par le seul choix de l'appelant — voir sa docstring
    pour la table rôle d'appareil -> vue et la règle « role ne peut que restreindre ». La
    résolution de vue précède la lecture du registre : un refus d'identité ne révèle même pas si
    `devis_id` existe.

    PLAN T1.4-k2 : un vendeur ne lit que le devis d'un lead dont il est le propriétaire (M2, relu à la
    source : `_proprietaire_du_lead`). Le devis d'un autre, celui d'un lead sans propriétaire connu et un
    devis inconnu donnent le MÊME refus (`REJ-DEVIS-INTROUVABLE`) : rien ne dit à un vendeur quels devis
    existent. Admin, employé (toujours sans coût, marge ni prix) et agent : aucun filtre."""
    vue = _vue_projection_effective(role)
    if not vue["accepte"]:
        return {"accepte": False, "verdict": vue["verdict"]}
    devis, verdict = devis_durable.lire_devis(registre_devis_production(), devis_id)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    if _hors_portee_du_vendeur(vue, devis):
        return {"accepte": False, "verdict": _devis_inconnu(devis_id)}
    return depuis_couple(devis_durable.projeter_devis(devis, vue["role"]))


def marquer_devis_accepte(devis_id: str, approbateur: str, horodatage: str) -> dict[str, Any]:
    """Marque un devis ACCEPTE et publie `m3.devis_accepte` dans la MÊME transaction (ADR-0009
    §3) — seulement quand la transition réussit réellement (`verdict is None`) : un rejet
    (devis introuvable, transition illégale, approbateur absent) n'écrit et ne publie jamais rien.

    `evenement_id` déterministe (`f"m3-devis-accepte-{devis_id}"`, PLAN T2.3-b, même patron que
    M6 pour `m6.variance_chantier` : `f"m6-variance-{wct_id}"`) : défense en profondeur — un
    rejeu de cet appel (ex. panne réseau entre l'écriture et la réponse au producteur) republie
    donc un no-op (`evenements.publier` sur un `evenement_id` déjà connu), jamais un second
    événement pour la même acceptation.
    """
    devis, verdict = devis_durable.marquer_devis_accepte(
        devis_id, approbateur, horodatage, registre_devis_production()
    )
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    charge = estime_vs_reel.avec_duree_estimee(  # PLAN T1.5-d : durée estimée du devis, si l'estimation la porte
        devis_durable.charge_evenement_devis_accepte(devis),
        devis_id,
        registre_devis_production(),
        registre_production().lire(),
    )
    evenements.publier("m3.devis_accepte", "m03-estimation", charge, evenement_id=f"m3-devis-accepte-{devis_id}")
    return {"accepte": True, "resultat": devis}


def registre_estime_vs_reel_production() -> stockage.MaillonsDurables:
    """Registre M3 dédié à l'estimé-vs-réel (PLAN T1.2-d, en second ordre) : `stockage.maillons(
    "m03-estimation", "estime_vs_reel")`, relu à chaque appel, jamais mis en cache — même
    discipline que `registre_devis_production`/`registre_production` ci-dessus. Distinct de
    `registre_production()` ("principal") : celui-ci reste le registre D'ORIGINE des estimations
    (S008, jamais écrit ici — lu seulement, voir `estime_vs_reel.py`) ; "estime_vs_reel" est la
    collection propre aux RÉSULTATS de comparaison (durée réelle vs estimée, variance matériaux),
    jamais mélangée aux deux autres."""
    return stockage.maillons("m03-estimation", "estime_vs_reel")


# ---------------------------------------------------------------------------------------------
# Consommateurs d'événements (ADR-0009 §3, PLAN T1.2-d) : seul cet adaptateur connaît `opsys` ;
# `estime_vs_reel.py` (module pur) fait le rapprochement et l'enregistrement déterministes. Le
# répartiteur (`opsys.evenements.repartir`) n'appelle ces fonctions que dans une transaction déjà
# ouverte : le registre durable fait donc TOUJOURS autorité ici (comme les outils T1/T3
# ci-dessus), sans le mode « en mémoire » des tests unitaires du module pur.
# ---------------------------------------------------------------------------------------------
def _recevoir_travaux_termines(charge: dict[str, Any]) -> dict[str, Any]:
    """Consomme `m4.travaux_termines` : relie le WCT à son devis puis, si le lien existe déjà, à
    l'estimation d'origine (`estime_vs_reel.enregistrer_travaux_termines`, DÉTERMINISTE). Toujours
    `traite: true` — une comparaison main-d'œuvre incomplète est une lacune nommée dans le
    résultat, jamais un échec de consommation."""
    resultat = estime_vs_reel.enregistrer_travaux_termines(
        charge, registre_devis_production(), registre_production().lire(), registre_estime_vs_reel_production()
    )
    return {"traite": True, "wct_id": resultat["wct_id"]}


def _recevoir_variance_chantier(charge: dict[str, Any]) -> dict[str, Any]:
    """Consomme `m6.variance_chantier` : n'alimente la partie matériaux que si `statut_variance
    == "evaluee"` (`estime_vs_reel.enregistrer_variance_chantier`) ; les autres statuts sont
    reconnus sans écriture. Laisse volontairement remonter `LookupError` si le wct_id est inconnu
    (ordre d'arrivée inversé, jamais un cas normal) : le répartiteur réessaie puis met en
    quarantaine, comme toute panne de consommateur."""
    resultat = estime_vs_reel.enregistrer_variance_chantier(charge, registre_estime_vs_reel_production())
    if resultat is None:
        return {"traite": True, "ignore_statut": charge["statut_variance"]}
    return {"traite": True, "wct_id": resultat["wct_id"]}


def lire_ecarts_estime_reel(
    devis_id: str | None = None, depuis: str | None = None, jusqua: str | None = None
) -> dict[str, Any]:
    return depuis_couple(
        estime_vs_reel.lire_ecarts(registre_estime_vs_reel_production(), devis_id, depuis, jusqua)
    )


def detecter_devis_sans_reponse(horodatage_reference: str, delai_relance_jours: int) -> dict[str, Any]:
    """Parcourt TOUS les devis durables connus (PLAN T2.3, `devis_relance.py`) et publie
    `m3.devis_sans_reponse` (idempotent par `devis_id`) pour chacun resté sans réponse selon la
    règle fournie — `horodatage_reference` et `delai_relance_jours` sont FOURNIS par l'appelant
    (paramètre ou configuration), jamais déduits d'une horloge ni codés en dur. Un devis dont
    l'entrée est malformée est signalé dans `erreurs`, sans bloquer les autres."""
    tous = devis_durable.lister_devis(registre_devis_production())
    relances: list[str] = []
    erreurs: list[dict[str, Any]] = []
    for devis in tous:
        fait, verdict = devis_relance.construire_fait_devis_sans_reponse(
            devis, horodatage_reference, delai_relance_jours
        )
        if verdict is not None:
            erreurs.append({"devis_id": devis.get("devis_id"), "verdict": verdict})
            continue
        if fait is None:
            continue
        evenements.publier(
            "m3.devis_sans_reponse",
            "m03-estimation",
            fait,
            evenement_id=f"m3-devis-sans-reponse-{fait['devis_id']}",
        )
        relances.append(fait["devis_id"])
    return {"devis_verifies": len(tous), "relances_publiees": relances, "erreurs": erreurs}


_FORMATS_SOUMISSION = ("html", "pdf")
_HORS_NOM_DE_FICHIER = re.compile(r"[^A-Za-z0-9._-]")


def _soumission_pdf(devis: dict[str, Any], devis_id: str) -> dict[str, Any]:
    """Le brouillon en PDF, remis en base64 avec de quoi le vérifier (taille, SHA-256).

    Un outil ne peut pas transmettre plus de `jetons.LIMITE_SORTIE_DEFAUT` caractères : au-delà,
    `Capacites._tronquer` le remplacerait par un aperçu, et un PDF tronqué est un fichier corrompu
    présenté comme un fichier. La même mesure que `_tronquer` est donc faite ICI, et un PDF trop gros
    est un verdict nommé, jamais un contenu coupé. Aucun envoi : ce sont des octets rendus à l'appelant."""
    octets, verdict = soumission_pdf.generer_brouillon_pdf(devis)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    resultat = {
        "format": "pdf",
        "type_mime": soumission_pdf.TYPE_MIME,
        "nom_fichier": "soumission-brouillon-" + _HORS_NOM_DE_FICHIER.sub("_", devis_id) + ".pdf",
        "taille_octets": len(octets),
        "empreinte_sha256": hashlib.sha256(octets).hexdigest(),
        "contenu_base64": base64.b64encode(octets).decode("ascii"),
    }
    enveloppe = {"ok": True, "resultat": {"accepte": True, "resultat": resultat}}
    caracteres = len(json.dumps(enveloppe, ensure_ascii=False))
    if caracteres > jetons.LIMITE_SORTIE_DEFAUT:
        return {"accepte": False, "verdict": verdicts.construire_verdict(
            "REJ-SOUMISSION-PDF-TROP-VOLUMINEUX",
            detail=(
                f"le PDF pèse {len(octets)} octets ({caracteres} caractères transmis) : un outil ne rend "
                f"pas plus de {jetons.LIMITE_SORTIE_DEFAUT} caractères, il serait tronqué donc corrompu ; "
                "réduire le nombre de lignes du devis (le dépôt de fichiers du socle ne prend pas encore le PDF)"
            ),
        )}
    return {"accepte": True, "resultat": resultat}


def generer_soumission_brouillon(devis_id: str, format: str = "html") -> dict[str, Any]:
    """Lit le devis durable par `devis_id` et rend un brouillon lisible pour le client, en HTML (défaut)
    ou en PDF (PLAN T2.3, `soumission.py`, `soumission_pdf.py`) — jamais un envoi (SOUL.md, T1.3 :
    l'envoi reste derrière les approbations du socle).

    PLAN T1.4-k2 : pendant un appel d'appareil, l'identité est confirmée en base, le rôle doit être dans la
    portée de l'outil (vendeur ou admin : le brouillon porte les prix, jamais montrés à l'employé) et un
    vendeur n'obtient que le brouillon d'un lead dont il est le propriétaire (même refus que `lire_devis`
    pour le devis d'un autre et pour un devis inconnu). Agent : comme avant. Les deux formats passent par
    ces mêmes gardes : le PDF n'ouvre aucune porte de plus."""
    if format not in _FORMATS_SOUMISSION:
        raise ValueError(f"format inconnu : {format!r} (attendu : {', '.join(_FORMATS_SOUMISSION)})")
    vue = _vue_projection_effective(None)
    if not vue["accepte"]:
        return {"accepte": False, "verdict": vue["verdict"]}
    if vue["role_appareil"] is not None and vue["role_appareil"] not in _ROLES_SOUMISSION:
        return {"accepte": False, "verdict": verdicts.construire_verdict(
            "REJ-IDENTITE-APPAREIL-INVALIDE",
            detail=f"rôle d'appareil {vue['role_appareil']!r} sans portée sur le brouillon de soumission",
        )}
    devis, verdict = devis_durable.lire_devis(registre_devis_production(), devis_id)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    if _hors_portee_du_vendeur(vue, devis):
        return {"accepte": False, "verdict": _devis_inconnu(devis_id)}
    if format == "pdf":
        return _soumission_pdf(devis, devis_id)
    return depuis_couple(soumission.generer_brouillon_html(devis))


def _politique_photos_texte() -> str:
    """Lit le texte réel de la politique Loi 25 « photos » sur disque — seul point du paquet à
    toucher le système de fichiers pour cette garde (`politique_photos.py` reste pur). Un fichier
    absent ou illisible rend une chaîne vide : `politique_photos.lire_statut_validation` la
    traite comme un statut ABSENT, donc un refus fail-closed, jamais une exception qui masquerait
    la vraie cause à l'agent appelant."""
    try:
        return _CHEMIN_POLITIQUE_PHOTOS.read_text(encoding="utf-8")
    except OSError:
        return ""


def verifier_politique_photos() -> dict[str, Any]:
    """Constate si la politique Loi 25 « photos » est marquée VALIDÉE (PLAN T2.3,
    `politique_photos.py`) — lecture pure, aucun effet de bord. Tout futur code qui collecterait
    un octet d'image réel doit appeler ce même contrôle (ou `politique_photos.
    verifier_collecte_photo_autorisee` directement) avant d'agir."""
    texte = _politique_photos_texte()
    verdict = politique_photos.verifier_collecte_photo_autorisee(texte)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return {"accepte": True, "resultat": {"statut_validation": politique_photos.lire_statut_validation(texte)}}


# ---------------------------------------------------------------------------------------------
# Revue et envoi du devis (PLAN T4.7, DEFINITION-PRODUIT §7 M3.14) : `m3_demander_envoi_devis`.
#
# L'outil est N4 : le socle (`Capacites._distribuer`) ne l'exécute JAMAIS sur l'appel d'un agent ni d'un
# vendeur ; il met une demande dans la file du propriétaire (`approbations.creer_demande`, niveau N4 figé).
# Seule une décision (`approbations.decider`) l'exécute, avec les arguments EXACTS enregistrés. Qui peut
# décider : `department.yaml/approbations.n4` (nathan_owner seul) ; l'app d'approbation exige en plus que la
# PERSONNE authentifiée porte `nathan_owner` (`approbations_appareil`, un `admin` qui ne l'est pas voit la
# file en lecture seule). Aucune livraison au client : le statut `envoye` dit « approuvé pour envoi », la
# livraison est à M1 (PLAN T2.1-c).
# ---------------------------------------------------------------------------------------------
_DEPARTEMENT = "m03-estimation"
_OUTIL_ENVOI_DEVIS = "m3_demander_envoi_devis"
_TYPE_EVENEMENT_DEVIS_ENVOYE = "m3.devis_envoye"
_TYPE_ATTENTE_REVUE_ENVOI = "revue_envoi_devis"
# Rôles dont une décision peut faire exécuter l'envoi : la même liste que `department.yaml/approbations.n4`
# (un test les confronte). Relue à l'exécution, en défense en profondeur : un mode `autonome` ne met pas un
# N4 en file, l'outil s'exécuterait alors sans humain ; il refuse donc de lui-même (voir ci-dessous).
_ROLES_APPROBATEURS_ENVOI = frozenset({identite.Role.NATHAN_OWNER.value})
_MANIFESTE = Path(__file__).resolve().parents[2] / "department.yaml"
_CONFIGURATION_ILLISIBLE = "illisible"

_CONTEXTE_REVUE = {
    "type": ["object", "null"],
    "description": (
        "Faits que M3 ne détient pas, à recopier tels quels de la réponse de m3_estimer_projet "
        "(niveau_confiance_hierarchie, estimation.verdict_estimation, estimation.alerte_plancher) ou à donner "
        "s'ils sont connus. Chaque clé est facultative ; un fait absent est listé « non évaluable » dans la "
        "revue, jamais deviné. null : aucun fait fourni."
    ),
    "properties": {
        "niveau_confiance_hierarchie": {"type": "string", "enum": list(hierarchie_echelle.NIVEAUX_CONFIANCE)},
        "verdict_estimation": {"type": "string", "enum": list(contrats.VERDICTS_ESTIMATION)},
        "alerte_plancher": {"type": "boolean"},
        "service_complexe": {"type": "boolean"},
        "client_a_risque": {"type": "boolean"},
        "distance_km": {"type": ["string", "number"], "description": "kilomètres, texte décimal ou nombre"},
        "donnees_fournisseur_completes": {"type": "boolean"},
    },
    "additionalProperties": False,
}


def _seuils_revue() -> Any:
    """`configuration.revue_devis` de `department.yaml`, tel quel (`None` s'il est absent) : les seuils de la
    revue, JAMAIS un nombre codé en dur ici ni dans `revue_devis.py`. Même source et même discipline que M6
    (`_seuil_variance_chantier`) : `revue_devis` juge chaque seuil vide ou invalide « seuil à configurer » ou
    « seuil invalide », jamais une valeur par défaut. Un manifeste illisible rend `_CONFIGURATION_ILLISIBLE`
    (que `revue_devis` refuse de lire comme des seuils) : la revue le dit, elle ne tombe pas."""
    try:
        donnees = yaml.safe_load(_MANIFESTE.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return _CONFIGURATION_ILLISIBLE
    configuration = donnees.get("configuration") if isinstance(donnees, dict) else None
    return configuration.get("revue_devis") if isinstance(configuration, dict) else None


def _decision_approuvee_en_cours(cnx: Any, arguments: dict[str, Any]) -> tuple[str, str, str] | None:
    """`(personne, rôle, instant)` de la décision qui fait exécuter CET appel, sinon `None`. Lecture seule.

    `approbations.decider` réserve la demande (`en_attente` -> `en_cours`, avec `decide_par`, `decide_role` et
    `decide_le`) puis exécute l'outil avec les arguments EXACTS enregistrés, dans la même transaction. Cet
    appel EST donc l'exécution d'une décision si et seulement si une demande `en_cours` de cet outil, de ce
    département, porte exactement ces arguments et un approbateur de rôle autorisé (`nathan_owner`) toujours
    actif. Un agent ne peut pas fabriquer une telle ligne : il ne peut que créer une demande `en_attente`.
    Le socle n'expose pas l'approbateur à l'outil : cette lecture de sa table en tient lieu (même patron que
    M5 et M10). `decide_le` est l'horloge du socle au moment de la décision : M3 ne lit jamais l'heure."""
    if cnx is None:
        return None
    lignes = cnx.execute(
        select(APPROBATIONS.c.arguments, APPROBATIONS.c.decide_par, APPROBATIONS.c.decide_role,
               APPROBATIONS.c.decide_le).where(
            APPROBATIONS.c.statut == "en_cours",
            APPROBATIONS.c.outil == _OUTIL_ENVOI_DEVIS,
            APPROBATIONS.c.departement == _DEPARTEMENT,
        )
    ).all()
    for enregistres, decide_par, decide_role, decide_le in lignes:
        if not decide_par or not decide_le or decide_role not in _ROLES_APPROBATEURS_ENVOI:
            continue
        if json.loads(enregistres) != arguments:
            continue
        personne = identite.personne_active(cnx, decide_par)
        if personne is not None and decide_role in personne.roles:
            return decide_par, decide_role, decide_le
    return None


def demander_envoi_devis(devis_id: str, contexte_revue: dict[str, Any] | None) -> dict[str, Any]:
    """L'outil `m3_demander_envoi_devis` (T2, N4) — ce corps s'exécute APRÈS la décision du propriétaire.

    1. Il refuse de s'exécuter hors d'une décision approuvée (`REJ-ENVOI-SANS-APPROBATION`) : un mode
       `autonome`, un appel en ligne de commande ou une transaction absente n'envoient jamais un devis.
    2. Un devis déjà `envoye` est un rejeu : rien n'est écrit, rien n'est republié, la réponse le dit
       (`deja_envoye`). Un devis `accepte` est refusé par la machine à états (transition illégale).
    3. La revue est refaite sur le devis TEL QU'IL EST À LA DÉCISION (`revue_devis.evaluer_revue`), pas sur ce
       qu'il était à la demande ; sa synthèse (alerte et codes, jamais les valeurs) est gardée au maillon de
       transition avec l'approbateur. Une alerte rouge n'EMPÊCHE PAS l'envoi : c'est le propriétaire qui la
       lit et qui décide (§7 M3.11).
    4. Le devis passe `envoye` à l'instant de la décision et `m3.devis_envoye` est publié dans la MÊME
       transaction, sous un identifiant déterministe : les deux réussissent ou échouent ensemble.

    Les deux paramètres sont requis : la demande approuvée rejoue les arguments EXACTS enregistrés, et
    `_decision_approuvee_en_cours` les compare tels quels."""
    decision = _decision_approuvee_en_cours(
        stockage.connexion_courante(), {"devis_id": devis_id, "contexte_revue": contexte_revue}
    )
    if decision is None:
        return {"accepte": False, "verdict": verdicts.construire_verdict(
            "REJ-ENVOI-SANS-APPROBATION",
            detail=(
                "l'envoi d'un devis est un engagement (N4) : il ne s'exécute que sur la décision du propriétaire "
                "dans la file d'approbation OPSYS. Ne le présente pas comme envoyé."
            ),
        )}
    approuve_par, approuve_role, decide_le = decision
    registre_devis = registre_devis_production()
    devis, verdict = devis_durable.lire_devis(registre_devis, devis_id)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    if devis["statut"] == "envoye":
        return {"accepte": True, "resultat": {
            "devis_id": devis_id, "statut": "envoye", "horodatage_envoi": devis["horodatage"], "deja_envoye": True,
        }}
    revue: dict[str, Any] | None = None
    if devis["statut"] == "brouillon":
        revue, verdict = revue_devis.evaluer_revue(devis, contexte_revue, _seuils_revue())
        if verdict is not None:
            return {"accepte": False, "verdict": verdict}
    envoye, verdict = devis_durable.marquer_devis_envoye(
        devis_id, decide_le, registre_devis, approuve_par=approuve_par, approuve_role=approuve_role,
        revue=revue_devis.synthese(revue) if revue is not None else None,
    )
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    evenements.publier(
        _TYPE_EVENEMENT_DEVIS_ENVOYE, _DEPARTEMENT, devis_durable.charge_evenement_devis_envoye(envoye),
        evenement_id=f"m3-devis-envoye-{devis_id}",
    )
    return {"accepte": True, "resultat": {
        "devis_id": devis_id, "statut": "envoye", "horodatage_envoi": decide_le, "deja_envoye": False,
        "revue": revue,
    }}


def _resume_demande_envoi(arguments: Any, registre_devis: Any, seuils: Any) -> str:
    """Le texte d'UNE demande d'envoi en attente, tel que le propriétaire le lit : la revue du devis tel
    qu'il est AUJOURD'HUI (`revue_devis.resume_attente`), ou, quand elle ne peut pas se faire, pourquoi.
    Jamais un silence : une demande qu'on ne sait pas lire reste visible, avec la raison."""
    limite = revue_devis.LIMITE_RESUME
    devis_id = arguments.get("devis_id") if isinstance(arguments, dict) else None
    if not isinstance(devis_id, str) or not devis_id.strip():
        return revue_devis.abreger("Demande d'envoi illisible : aucun devis_id. À refuser.", limite)
    devis, verdict = devis_durable.lire_devis(registre_devis, devis_id)
    if verdict is not None:
        return revue_devis.abreger(
            f"Envoi du devis {devis_id} demandé, mais ce devis est introuvable. À refuser.", limite
        )
    if devis["statut"] != "brouillon":
        return revue_devis.abreger(
            f"Envoi du devis {devis_id} demandé, mais il est déjà {devis['statut']} : rien à approuver.", limite
        )
    revue, verdict = revue_devis.evaluer_revue(devis, arguments.get("contexte_revue"), seuils)
    if verdict is not None:
        return revue_devis.abreger(
            f"Envoi du devis {devis_id} : revue impossible ({verdict['code']} : {verdict['detail']}). "
            "À refuser ou à redemander.", limite,
        )
    return revue_devis.resume_attente(revue, limite)


def attentes() -> list[dict[str, Any]]:
    """L'attente de la file du propriétaire (ADR-0009 §5, PLAN T4.7) : une entrée par demande d'envoi de devis
    en attente, dont le résumé PORTE LES MOTIFS de la revue (alerte rouge d'abord, critères non évaluables
    comptés). Le vendeur crée la demande (le socle la met en file, l'outil ne s'exécute pas) ; cette fonction la
    lit et refait la revue sur le devis d'aujourd'hui, avec les faits que la demande a enregistrés et les
    seuils de `department.yaml`. L'entrée disparaît quand la demande est décidée. Lecture seule : ne crée
    rien, ne décide de rien. Hors transaction (aucune connexion), rien n'est lisible : liste vide.

    Ce n'est PAS la demande d'approbation (celle du socle, décidable) : c'est ce qui la rend lisible. Son `id`
    est celui de la demande, pour les retrouver l'une à côté de l'autre."""
    cnx = stockage.connexion_courante()
    if cnx is None:
        return []
    demandes = cnx.execute(
        select(APPROBATIONS.c.id, APPROBATIONS.c.arguments, APPROBATIONS.c.cree_le).where(
            APPROBATIONS.c.statut == "en_attente",
            APPROBATIONS.c.outil == _OUTIL_ENVOI_DEVIS,
            APPROBATIONS.c.departement == _DEPARTEMENT,
        ).order_by(APPROBATIONS.c.cree_le, APPROBATIONS.c.id)
    ).all()
    if not demandes:
        return []
    registre_devis = registre_devis_production()
    seuils = _seuils_revue()
    attentes_revue: list[dict[str, Any]] = []
    for demande_id, brut, cree_le in demandes:
        try:
            arguments: Any = json.loads(brut)
        except ValueError:
            arguments = None
        attentes_revue.append({
            "type": _TYPE_ATTENTE_REVUE_ENVOI,
            "id": demande_id,
            "resume": _resume_demande_envoi(arguments, registre_devis, seuils),
            "niveau": Niveau.N4.value,
            "depuis": cree_le,
            "action_proposee": "approuver ou refuser l'envoi (le propriétaire décide)",
        })
    return attentes_revue


def consommateurs() -> dict[str, Callable[[dict[str, Any]], dict[str, Any]]]:
    return {
        "m4.travaux_termines": _recevoir_travaux_termines,
        "m6.variance_chantier": _recevoir_variance_chantier,
    }


def outils() -> tuple[Outil, ...]:
    """Capacités exposées aux agents (fonction : les constantes publiques du paquet sont des énumérés)."""
    return (
        Outil(
            nom="m3_estimer_projet",
            description=(
                "Estime un projet de bout en bout (PLAN T2.3) : valide le contrat LeadQualifie et le "
                "marqueur de readiness M2, qualité des photos, hiérarchie d'échelle, blocage "
                "anti-précision-inventée, Monte Carlo, plancher de rentabilité ; assemble le contrat "
                "gelé EstimationV1, inscrit au registre durable. Bloque le prix si "
                "photos ou référence d'échelle insuffisantes, liste ce qui manque et émet "
                "signal_relance_m2. Signale sans bloquer REFERENCE_ECHELLE_ABSENTE. Calcule la durée de "
                "main-d'œuvre si le barème porte duree_minutes_par_unite, et prix_recommande depuis le "
                "coût si taux_marge est fourni (jamais codé en dur ; absent, elements_manquants le "
                "dit). Si le poste du barème porte materiaux et que le prix n'est pas bloqué, calcule "
                "les besoins matériaux (quantités nettes en texte décimal, sans prix ni coût), les rend "
                "sous besoins_materiaux et les publie à M6 (m3.besoins_materiaux) ; un facteur_perte "
                "absent reste absent et est signalé, jamais inventé. Rôle employee (appareil "
                "authentifié) : coût et prix toujours retirés."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "contrat": _CONTRAT,
                    "marqueur": _MARQUEUR,
                    "photos": {"type": "array", "items": _PHOTO},
                    "seuils": _SEUILS,
                    "bareme": _BAREME,
                    "quantite": {"type": "number"},
                    "plancher_rentable": {"type": "number"},
                    "graine": {"type": "integer"},
                    "taux_marge": {
                        "type": ["string", "null"],
                        "description": (
                            "texte décimal, ex. \"0.35\" pour 35 % — jamais codé en dur ; absent "
                            "ou null : aucun prix_recommande calculé (coût seulement)"
                        ),
                    },
                },
                "required": ["contrat", "marqueur", "photos", "seuils", "bareme", "quantite", "plancher_rentable"],
                "additionalProperties": False,
            },
            fonction=estimer_projet,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m3_qualifier_photos",
            description="Vérifie la qualité des photos (résolution, éclairage) et liste ce qui manque.",
            parametres={
                "type": "object",
                "properties": {"photos": {"type": "array", "items": _PHOTO}, "seuils": _SEUILS},
                "required": ["photos", "seuils"],
                "additionalProperties": False,
            },
            fonction=qualifier_photos,
            # §9.4 « demander des photos au client » : fonction pure, ne lit aucune donnée interne.
            roles_appareil=frozenset({"seller", "admin"}),
        ),
        Outil(
            nom="m3_classifier_confiance",
            description="Classe le niveau de confiance des mesures (référence d'échelle, multi-vues, mono-vue).",
            parametres={
                "type": "object",
                "properties": {"photos": {"type": "array", "items": _PHOTO}, "seuils": _SEUILS},
                "required": ["photos", "seuils"],
                "additionalProperties": False,
            },
            fonction=classifier_confiance,
        ),
        Outil(
            nom="m3_simuler_intervalle",
            description="Intervalle de coût Monte Carlo reproductible pour un type de travaux et une quantité.",
            parametres={
                "type": "object",
                "properties": {
                    "bareme": _BAREME,
                    "type_travaux": _TYPE_TRAVAUX,
                    "quantite": {"type": "number"},
                    "graine": {"type": "integer"},
                    "niveau": {"type": "number", "description": "entre 0 et 1 exclus, défaut 0,9"},
                },
                "required": ["bareme", "type_travaux", "quantite", "graine"],
                "additionalProperties": False,
            },
            fonction=simuler_intervalle,
        ),
        Outil(
            nom="m3_confronter_plancher",
            description="Compare la borne basse d'un intervalle au plancher de rentabilité fourni.",
            parametres={
                "type": "object",
                "properties": {
                    "intervalle": {"type": "object"},
                    "plancher_rentable": {"type": "number"},
                },
                "required": ["intervalle", "plancher_rentable"],
                "additionalProperties": False,
            },
            fonction=confronter_plancher,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m3_creer_devis",
            description=(
                "Crée un devis BROUILLON (PLAN T2.3-a) sur le registre dédié des devis, distinct du "
                "registre d'estimations. Le prix de chaque ligne est TOUJOURS calculé par le code, "
                "jamais fourni : prix_unitaire = cout_unitaire x (1 + taux_marge) arrondi au cent, "
                "puis prix_ligne = prix_unitaire x quantite, arrondi une seconde fois — même ordre "
                "que la facture M5 recalculera. Les totaux sont recalculés depuis les lignes ; un "
                "prix_total fourni qui diffère est rejeté. "
                "Idempotente par devis_id : un second appel identique est un no-op, un contenu "
                "différent est rejeté. Écriture interne non finale (T1) : n'envoie rien au client."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "devis_id": {"type": "string"},
                    "lead_id": {"type": "string", "description": "lien avec le lead M2"},
                    "chantier_id": {"type": ["string", "null"], "description": "chantier M4, si déjà connu"},
                    "lignes": {"type": "array", "items": _LIGNE_DEVIS, "minItems": 1},
                    "taux_marge": {
                        "type": "string",
                        "description": "texte décimal, ex. \"0.35\" pour 35 % — jamais codé en dur",
                    },
                    "horodatage": {"type": "string"},
                    "prix_total": {
                        "type": ["string", "null"],
                        "description": (
                            "Optionnel : contrôle défensif, doit correspondre exactement au total "
                            "recalculé depuis les lignes, sinon rejet."
                        ),
                    },
                },
                "required": ["devis_id", "lead_id", "chantier_id", "lignes", "taux_marge", "horodatage"],
                "additionalProperties": False,
            },
            fonction=creer_devis,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m3_lire_devis",
            description=(
                "Lit l'état courant d'un devis par devis_id (registre durable, relu à chaque appel, "
                "jamais mis en cache). role=\"employe\" retire coût, marge ET prix (séparation "
                "coût/prix, audit M3) ; role=\"interne\" rend la vue complète. Pendant un appel "
                "d'appareil authentifié (PLAN T1.4-c4), la vue vient du rôle authentifié — employee "
                "-> employe, admin/seller -> interne — et role ne peut que RESTREINDRE cette vue, "
                "jamais l'élargir (une demande plus large est un refus nommé). Hors appel "
                "d'appareil, role choisit librement la vue (défaut : interne, comportement "
                "historique). Un vendeur authentifié ne lit que les devis des leads dont il est le "
                "propriétaire (M2) ; le devis d'un autre et un devis inconnu donnent le même refus."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "devis_id": {"type": "string"},
                    "role": {"type": "string", "enum": ["interne", "employe"]},
                },
                "required": ["devis_id"],
                "additionalProperties": False,
            },
            fonction=lire_devis,
            autonomie=Autonomie.T0,
            # §9.4 (vendeur : « voir risques et marge », M5 « marge estimée de la soumission »,
            # « ne voit pas les coûts internes au-delà de sa soumission »). Jamais `employee` :
            # `role` est choisi par l'appelant, rien ne l'empêche de demander la vue interne.
            roles_appareil=frozenset({"seller", "admin"}),
        ),
        Outil(
            nom="m3_marquer_devis_accepte",
            description=(
                "Marque un devis (brouillon ou envoyé) ACCEPTE et publie m3.devis_accepte dans la "
                "même transaction. T3 (frontière humaine, AGENTS.md) : l'acceptation du client est "
                "un engagement externe — approbateur doit être un humain qui CONSTATE l'acceptation "
                "réelle (signature, courriel, appel), jamais déduite. L'ENVOI du devis au client "
                "n'est pas un outil exposé (action externe, ira derrière les approbations du socle "
                "en T1.3) : marquer_devis_accepte accepte donc aussi depuis brouillon."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "devis_id": {"type": "string"},
                    "approbateur": {"type": "string", "description": "humain qui constate l'acceptation"},
                    "horodatage": {"type": "string"},
                },
                "required": ["devis_id", "approbateur", "horodatage"],
                "additionalProperties": False,
            },
            fonction=marquer_devis_accepte,
            autonomie=Autonomie.T3,
        ),
        Outil(
            nom="m3_lire_ecarts_estime_reel",
            description=(
                "Rend les écarts estimé-vs-réel (PLAN T1.2-d) pour un devis_id ou sur une période "
                "[depuis, jusqua[ (horodatage_completion, ISO-8601 avec fuseau) — au moins un des "
                "deux requis. Par WCT : main_doeuvre (durée réelle vs estimée, écart relatif, ou un "
                "verdict nommé si la durée estimée est introuvable) et materiaux (lignes de "
                "variance M6 telles quelles, absentes tant qu'aucune variance evaluee n'est reçue). "
                "Lecture pure (T0), aucun barème ajusté."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "devis_id": {"type": ["string", "null"]},
                    "depuis": {"type": ["string", "null"], "description": "borne incluse, ISO-8601 avec fuseau"},
                    "jusqua": {"type": ["string", "null"], "description": "borne exclue, ISO-8601 avec fuseau"},
                },
                "required": [],
                "additionalProperties": False,
            },
            fonction=lire_ecarts_estime_reel,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m3_detecter_devis_sans_reponse",
            description=(
                "Parcourt tous les devis durables et publie m3.devis_sans_reponse (idempotent "
                "par devis_id) pour chaque devis resté au statut brouillon ou envoye (jamais "
                "accepte) depuis au moins delai_relance_jours jours par rapport à "
                "horodatage_reference — les deux sont fournis par l'appelant, jamais déduits "
                "d'une horloge ni codés en dur (audit M3, signal de relance vers M2)."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "horodatage_reference": {
                        "type": "string",
                        "description": "instant de référence du constat, ISO-8601 avec fuseau",
                    },
                    "delai_relance_jours": {"type": "integer", "minimum": 1},
                },
                "required": ["horodatage_reference", "delai_relance_jours"],
                "additionalProperties": False,
            },
            fonction=detecter_devis_sans_reponse,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m3_generer_soumission_brouillon",
            description=(
                "Génère un brouillon de soumission lisible pour le client depuis un devis durable "
                "existant (description, quantités, prix par ligne, prix total — jamais coût ni marge), "
                "marqué BROUILLON. format=html (défaut) : texte HTML. format=pdf : fichier PDF rendu en "
                "base64 (contenu_base64, avec taille_octets et empreinte_sha256 pour le vérifier) ; sans "
                "la brique PDF (extra soumission) ou si le PDF dépasse la sortie d'un outil, un verdict "
                "dit quoi faire, jamais un faux PDF. Brouillon seulement : aucun envoi, aucune approbation "
                "requise pour le générer (l'envoi reste derrière les approbations du socle, T1.3). Un "
                "vendeur authentifié n'obtient que le brouillon d'un devis dont le lead lui appartient (M2)."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "devis_id": {"type": "string"},
                    "format": {"type": "string", "enum": list(_FORMATS_SOUMISSION)},
                },
                "required": ["devis_id"],
                "additionalProperties": False,
            },
            fonction=generer_soumission_brouillon,
            autonomie=Autonomie.T0,
            # §9.4 (vendeur : soumissions de ses leads, T1.4-k2 : filtre par propriétaire) ; ne porte jamais
            # coût ni marge.
            roles_appareil=frozenset({"seller", "admin"}),
        ),
        Outil(
            nom=_OUTIL_ENVOI_DEVIS,
            description=(
                "Demande l'ENVOI d'un devis brouillon au client (M3.14) : engagement, N4. Cet appel n'envoie rien "
                "et ne change rien : il met une demande dans la file du propriétaire, qui y lit la revue (motifs "
                "tirés du devis, de contexte_revue et des seuils de department.yaml, jamais inventés) avant de "
                "décider. Seul nathan_owner approuve. Approuvée, le devis passe à envoye (une seule fois, un rejeu "
                "ne fait rien) et m3.devis_envoye est publié, sans coût ni marge. La livraison au client n'est pas "
                "ici (M1). Recopie dans contexte_revue les faits de la réponse de m3_estimer_projet "
                "(niveau_confiance_hierarchie, estimation.verdict_estimation, estimation.alerte_plancher) ; un "
                "fait absent est listé « non évaluable », jamais deviné. Ne présente jamais le devis comme "
                "envoyé : il attend une décision."
            ),
            parametres={
                "type": "object",
                "properties": {"devis_id": {"type": "string"}, "contexte_revue": _CONTEXTE_REVUE},
                "required": ["devis_id", "contexte_revue"],
                "additionalProperties": False,
            },
            fonction=demander_envoi_devis,
            autonomie=Autonomie.T2,
            niveau=Niveau.N4,
            # §9.4 (vendeur : « soumissions » de ses leads) et §9.5 (admin : « approuve tout »). Le vendeur
            # DEMANDE ; il ne décide jamais (N4 : nathan_owner). Le socle ne peut pas filtrer par propriétaire
            # de lead à la demande (l'outil ne s'exécute qu'à la décision, sans l'identité de l'appareil) :
            # le propriétaire lit le devis et la revue avant d'approuver.
            roles_appareil=frozenset({"seller", "admin"}),
        ),
        Outil(
            nom="m3_verifier_politique_photos",
            description=(
                "Constate si la politique Loi 25 « photos non contractuelles » "
                "(docs/compliance/politiques/POLITIQUE-photos-non-contractuelles.md) est marquée "
                "VALIDÉE. Lecture seule ; refuse fail-closed (statut absent ou 'proposition') "
                "tant que Nathan ou un juriste ne l'a pas validée."
            ),
            parametres={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
            fonction=verifier_politique_photos,
            autonomie=Autonomie.T0,
        ),
    )
