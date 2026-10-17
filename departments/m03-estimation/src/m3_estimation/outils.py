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
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml
from sqlalchemy import select

from opsys import contexte, evenements, identite, jetons, readiness_m2, stockage, taxonomie
from opsys.approbations import approbateur_en_cours
from opsys.outils import Autonomie, Niveau, Outil, depuis_couple
from opsys.stockage import codec
from opsys.stockage.schema import APPROBATIONS

from . import (
    besoins_materiaux,
    calibration_raccord,
    calibration_versions,
    contrats,
    couverture_apprentissage,
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
    scenarios,
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
    "properties": {
        "semantique_temps": {
            "type": "string",
            "description": (
                "Optionnel. Seule la valeur exacte duree_ecoulee_intervention qualifie les minutes comme "
                "temps écoulé sur site par unité, pauses et déplacement exclus; absent ou toute autre valeur "
                "reste non qualifiée."
            ),
        },
    },
    "description": (
        "{version, unite, postes: {service (lead v2) ou type_travaux (lead v1) : {cout_unitaire_min, "
        "cout_unitaire_max, "
        "cout_unitaire_mode (optionnel — coût unitaire le plus probable, entre min et max : tirage PERT ; "
        "absent : tirage uniforme), "
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
    signal de relance, durée de main-d'œuvre ne sont ni de l'argent ni un risque de fuite. Depuis T4.11 :
    `distribution_cout` (P50, P80), `facteurs_dominants` (amplitudes en dollars) et `scenarios_prix` (coûts, prix,
    taux de marge) sont retirés aussi."""
    projection = dict(reponse)
    if isinstance(projection.get("estimation"), dict):
        intervalle = projection["estimation"].get("intervalle_confiance")
        if isinstance(intervalle, dict):
            projection["estimation"] = {
                **projection["estimation"],
                "intervalle_confiance": {**intervalle, "borne_basse": None, "borne_haute": None},
            }
    projection["prix_recommande"] = None
    # PLAN T4.11 : P50 et P80 sont des coûts, les scénarios des prix et des marges : rien n'en reste pour l'employé.
    for cle in scenarios.CHAMPS_SOEURS_ESTIMATION:
        projection[cle] = None
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
    taux_marge_scenarios: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Point d'entrée agent (PLAN T2.3) : appelle l'orchestrateur pur
    `estimation.orchestrer_estimation` sur le registre DURABLE de production. Toute la logique
    métier vit dans `estimation.py` (validation, qualité photos, hiérarchie d'échelle, blocage,
    Monte Carlo, plancher, alerte REFERENCE_ECHELLE_ABSENTE, durée main-d'œuvre, prix recommandé,
    signal de relance M2, registre, contrat gelé EstimationV1) ; cette fonction ne fait que choisir
    le support durable — même patron que `creer_devis`/`lire_devis` ci-dessous pour le registre des
    devis. À la frontière durable, M2 est relu par son vérificateur canonique : un
    marqueur périmé ou falsifié est refusé avant calcul et effet, sous une garde conservée
    jusqu’à la fin de la transaction. Le validateur pur reste structurel.

    Projection par l'identité authentifiée (PLAN T1.4-c4, `_vue_projection_effective`) : résolue
    AVANT tout appel à l'orchestrateur, pour qu'une identité d'appareil périmée n'écrive jamais au
    registre durable (aucun effet de bord avant un refus). Vue "employe" : la réponse retire coût
    et prix (`_projeter_estimation_employe`) — hors appel d'appareil, ou appareil admin/vendeur,
    comportement inchangé (PLAN T2.3-b).

    Besoins matériaux (PLAN T2.3-e) : quand l'estimation produit des quantités (le poste du barème
    porte `materiaux`, prix non bloqué), le contrat `BesoinsMateriauxM3` est publié sur le bus
    (`m3.besoins_materiaux`) DANS la même transaction que l'inscription au registre : les deux
    réussissent ou échouent ensemble. Publié tel quel, sans projection : il ne porte ni coût, ni
    prix, ni marge.

    P50, P80, facteurs dominants et scénarios de prix (PLAN T4.11, `scenarios.py`) : clés sœurs de la réponse, sur la
    voie non bloquée seulement. Les taux de marge des trois scénarios viennent de `taux_marge_scenarios` (l'appel
    d'abord, scénario par scénario) puis de `department.yaml/configuration/scenarios_prix/taux_marge` ; le minimum
    rentable est celui de `configuration/revue_devis` (T4.7). Les deux sont lus ICI, jamais par le module pur : vides à
    dessein, ils rendent un verdict qui dit quoi déclarer, jamais un prix. Rien de tout cela n'entre au registre."""
    vue = _vue_projection_effective(None)
    if not vue["accepte"]:
        return {"etape": "identite_appareil", "accepte": False, "verdict": vue["verdict"]}
    with stockage.transaction() as cnx:
        if not readiness_m2.verifier_preparation_estimation(cnx, contrat, marqueur):
            return {
                "etape": "readiness_m2", "accepte": False,
                "verdict": verdicts.construire_verdict(
                    "REJ-READINESS-NON-CONSTATEE",
                    detail="Réévaluer la préparation commerciale actuelle du lead dans M2.",
                ),
            }
        # Une attente du verrou M2 n'entretient pas une identité révoquée en vie.
        vue = _vue_projection_effective(None)
        if not vue["accepte"]:
            return {"etape": "identite_appareil", "accepte": False, "verdict": vue["verdict"]}
        calibration_candidate, erreur_calibration = _calibration_active_pour_demande(
            contrat, bareme, quantite,
        )
        if erreur_calibration is not None:
            return {"etape": "calibration_active", "accepte": False,
                    "raisons": [erreur_calibration], "candidate_active": False}
        resultat = _rejouer_sur_ecriture_concurrente(lambda: estimation.orchestrer_estimation(
            contrat, marqueur, photos, seuils, bareme, quantite, plancher_rentable,
            registre_production(), graine, taux_marge,
            taux_marge_scenarios, _taux_scenarios_configures(), _seuils_revue(), calibration_candidate,
        ))
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


# Sous PostgreSQL (READ COMMITTED), l'écriture d'un autre appel entre la lecture et l'ajout d'un registre pur
# (`devis_durable`, `registre`) lève `EcritureConcurrente` (précondition de rang du socle) au lieu d'écrire sur un
# état périmé. Le rang étant global au registre, un AUTRE devis ou une autre estimation peut en être la cause :
# l'opération est rejouée sur une lecture fraîche, qui reprend la même décision si son objet n'a pas changé, ou
# rend le refus nommé du nouvel état sinon. Une décision du propriétaire n'est donc pas perdue pour une écriture
# sans rapport. Au-delà de trois essais, l'exception remonte et la transaction est annulée (fail-closed).
_ESSAIS_ECRITURE_CONCURRENTE = 3


def _rejouer_sur_ecriture_concurrente(operation: Callable[[], Any]) -> Any:
    for _ in range(_ESSAIS_ECRITURE_CONCURRENTE - 1):
        try:
            return operation()
        except stockage.EcritureConcurrente:
            continue
    return operation()


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


def _source_estimation_exacte(hash_source: str | None, devis_id: str, lead_id: str) -> dict[str, Any] | None:
    """Résout un hash source seulement dans la chaîne M3 validée et pour les deux mêmes identifiants.

    L'appelant est dans la transaction atomique du métier. Une chaîne altérée, un hash absent/inconnu,
    ou un devis/lead différent ne produit aucune source exploitable.
    """
    if (
        not isinstance(hash_source, str)
        or len(hash_source) != 64
        or any(caractere not in "0123456789abcdef" for caractere in hash_source)
    ):
        return None
    journal = registre_production()
    try:
        valide, _ = journal.valider_chaine()
        if not valide:
            return None
        matches = [
            maillon for maillon in journal.lire()
            if isinstance(maillon, dict) and maillon.get("hash_maillon") == hash_source
        ]
    except (AttributeError, KeyError, TypeError, ValueError, RecursionError):
        return None
    if len(matches) != 1:
        return None
    charge = matches[0].get("charge")
    if not isinstance(charge, dict) or charge.get("devis_id") != devis_id or charge.get("lead_id") != lead_id:
        return None
    return charge


def creer_devis(
    devis_id: str,
    lead_id: str,
    chantier_id: str | None,
    lignes: list[dict[str, Any]],
    taux_marge: str,
    horodatage: str,
    prix_total: str | None = None,
    estimation_source_hash: str | None = None,
) -> dict[str, Any]:
    if (
        estimation_source_hash is not None
        and _source_estimation_exacte(estimation_source_hash, devis_id, lead_id) is None
    ):
        return {
            "accepte": False,
            "verdict": verdicts.construire_verdict(
                "REJ-CONTRAT-INVALIDE",
                detail="estimation_source_hash ne référence pas une charge M3 validée pour ce devis et ce lead",
            ),
        }
    return depuis_couple(_rejouer_sur_ecriture_concurrente(lambda: devis_durable.creer_devis(
        devis_id,
        lead_id,
        chantier_id,
        lignes,
        taux_marge,
        horodatage,
        registre_devis_production(),
        prix_total_fourni=prix_total,
        estimation_source_hash=estimation_source_hash,
    )))


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



def _curseur_devis_vendeur(personne: str, devis_id: str) -> str:
    """Encode un repère de pagination lié à une personne; ce jeton ne confère aucun droit."""
    charge = json.dumps(
        {"version": 1, "personne": personne, "devis_id": devis_id},
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return base64.urlsafe_b64encode(charge).decode("ascii").rstrip("=")


def _lire_curseur_devis_vendeur(curseur: Any) -> dict[str, str] | None:
    """Décode uniquement la forme canonique émise par _curseur_devis_vendeur."""
    if not isinstance(curseur, str) or not 1 <= len(curseur) <= 2048:
        return None
    if re.fullmatch(r"[A-Za-z0-9_-]+", curseur) is None:
        return None
    try:
        charge = base64.b64decode(
            curseur + "=" * (-len(curseur) % 4), altchars=b"-_", validate=True
        )
        objet = json.loads(charge.decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if (
        not isinstance(objet, dict)
        or set(objet) != {"version", "personne", "devis_id"}
        or type(objet.get("version")) is not int
        or objet["version"] != 1
        or not isinstance(objet.get("personne"), str)
        or not objet["personne"]
        or not isinstance(objet.get("devis_id"), str)
        or not objet["devis_id"]
        or _curseur_devis_vendeur(objet["personne"], objet["devis_id"]) != curseur
    ):
        return None
    return {"personne": objet["personne"], "devis_id": objet["devis_id"]}


def lister_devis_vendeur(limite: int = 20, curseur: str | None = None) -> dict[str, Any]:
    """Liste une page des devis du vendeur d'appareil authentifié, tous statuts courants confondus.

    La propriété est relue depuis M2 pour chaque devis dans la transaction courante. Le curseur est
    un repère de tri seulement : personne et appartenance sont revalidées à chaque appel.
    """
    appareil = contexte.identite_appelante()
    if appareil is None or appareil.role != _ROLE_VENDEUR:
        return {
            "accepte": False,
            "verdict": verdicts.construire_verdict(
                "REJ-IDENTITE-APPAREIL-INVALIDE",
                detail="un vendeur humain authentifié est requis",
            ),
        }
    vue = _vue_projection_effective(None)
    if not vue["accepte"]:
        return {"accepte": False, "verdict": vue["verdict"]}
    if vue["role_appareil"] != _ROLE_VENDEUR:
        return {
            "accepte": False,
            "verdict": verdicts.construire_verdict(
                "REJ-IDENTITE-APPAREIL-INVALIDE",
                detail="un vendeur humain authentifié est requis",
            ),
        }
    if type(limite) is not int or not 1 <= limite <= 50:
        return {
            "accepte": False,
            "verdict": verdicts.construire_verdict(
                "REJ-CONTRAT-INVALIDE", detail="limite doit être un entier entre 1 et 50"
            ),
        }

    repere = None
    if curseur is not None:
        repere = _lire_curseur_devis_vendeur(curseur)
        if repere is None or repere["personne"] != vue["personne"]:
            return {
                "accepte": False,
                "verdict": verdicts.construire_verdict(
                    "REJ-CONTRAT-INVALIDE", detail="curseur invalide"
                ),
            }

    devis_vendeur = [
        devis for devis in devis_durable.lister_devis(registre_devis_production())
        if _proprietaire_du_lead(devis.get("lead_id")) == vue["personne"]
    ]
    if repere is not None:
        identifiants = {devis.get("devis_id") for devis in devis_vendeur}
        if repere["devis_id"] not in identifiants:
            return {
                "accepte": False,
                "verdict": verdicts.construire_verdict(
                    "REJ-CONTRAT-INVALIDE", detail="curseur invalide"
                ),
            }
        devis_vendeur = [devis for devis in devis_vendeur if devis["devis_id"] > repere["devis_id"]]

    page = devis_vendeur[:limite]
    projection = []
    for devis in page:
        projete, rejet = devis_durable.projeter_devis(devis, "interne")
        if rejet is not None:
            return {"accepte": False, "verdict": rejet}
        projection.append(projete)
    suivant = (
        _curseur_devis_vendeur(vue["personne"], page[-1]["devis_id"])
        if len(devis_vendeur) > limite
        else None
    )
    return depuis_couple(({"devis": projection, "curseur_suivant": suivant}, None))


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
    devis, verdict = _rejouer_sur_ecriture_concurrente(lambda: devis_durable.marquer_devis_accepte(
        devis_id, approbateur, horodatage, registre_devis_production()
    ))
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    charge = devis_durable.charge_evenement_devis_accepte(devis)
    source = _source_estimation_exacte(devis.get("estimation_source_hash"), devis_id, devis.get("lead_id"))
    if source is not None:
        # La référence est l'unique autorité. Le helper exige la sémantique exacte avant de publier la mesure.
        charge = estime_vs_reel.avec_duree_estimee(
            charge, devis_id, registre_devis_production(), registre_production().lire()
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


def registre_calibration_versions_production() -> stockage.MaillonsDurables:
    """Journal append-only CAS des candidates et décisions de calibration."""
    return stockage.maillons("m03-estimation", "calibration_versions")


def _prefixe_recu_wct(maillons: Any) -> dict[str, Any] | None:
    """Empreinte bornée du préfixe M3 append-only des reçus WCT et rangs d'admission courants."""
    if not isinstance(maillons, list) or len(maillons) > 20_000:
        return None
    entries: list[dict[str, Any]] = []
    rangs: dict[str, int] = {}
    for rang_registre, maillon in enumerate(maillons):
        if not isinstance(maillon, dict) or maillon.get("type_entree") != "wct_recu":
            continue
        champs = {"type_entree", "wct_id", "devis_id", "lead_id", "intervention_id",
                  "horodatage_completion", "main_doeuvre", "materiaux", "horodatage"}
        if (set(maillon) != champs or not isinstance(maillon.get("wct_id"), str)
                or not maillon["wct_id"] or maillon["wct_id"] in rangs
                or not isinstance(maillon.get("main_doeuvre"), dict)
                or not isinstance(maillon.get("horodatage_completion"), str)
                or maillon.get("horodatage") != maillon.get("horodatage_completion")):
            return None
        rangs[maillon["wct_id"]] = len(entries)
        encoded = codec.encoder(maillon)
        entries.append({"rang_registre": rang_registre, "maillon": encoded})
    contenu = {"version": "m03-wct-prefix/1", "entrees": entries}
    canonique = json.dumps(contenu, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    if len(entries) > 2_000 or len(canonique.encode("utf-8")) > 4_000_000:
        return None
    return {
        "count": len(entries), "sha256": hashlib.sha256(canonique.encode("utf-8")).hexdigest(),
        "wct_id_hashes": sorted(
            calibration_versions.empreinte_identifiant_wct(wct_id) for wct_id in rangs
        ),
        "rangs": rangs, "entrees": entries,
    }


def _politique_calibration() -> dict[str, Any] | None:
    configuration = _configuration_du_manifeste()
    politique = configuration.get("calibration_temps") if isinstance(configuration, dict) else None
    return politique if isinstance(politique, dict) else None


def proposer_calibration_temps(coupure_utc: str, coupure_evaluation_utc: str) -> dict[str, Any]:
    """Fige candidates exclusivement depuis le train du rapport; ne consomme aucun holdout futur."""
    rapport = evaluer_calibration_cohortes(coupure_utc, _inclure_observations=True, _train_only=True)
    rapport.pop("observations_qualifiees", None)
    rapport.pop("_observations_qualifiees", None)
    # Les observations brutes ne sont jamais incluses dans le reçu d'outil; le registre conserve
    # seulement les empreintes et bornes de provenance du rapport source.
    if rapport.get("statut") != "candidate":
        rapport["candidate_active"] = False
        return rapport
    prefixe = _prefixe_recu_wct(list(registre_estime_vs_reel_production()))
    if prefixe is None:
        return {"statut": "refuse", "raisons": ["prefixe_wct_m3_invalide_ou_hors_limite"],
                "candidate_active": False}
    rapport["source_wct_prefix"] = {
        "count": prefixe["count"], "sha256": prefixe["sha256"],
        "wct_id_hashes": prefixe["wct_id_hashes"],
    }
    rapport["holdout_cutoff_utc"] = coupure_evaluation_utc
    sans_hash = {key: value for key, value in rapport.items() if key != "rapport_sha256"}
    rapport["rapport_sha256"] = hashlib.sha256(
        json.dumps(sans_hash, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    ).hexdigest()
    politique = _politique_calibration()
    if politique is None:
        return {"statut": "refuse", "raisons": ["politique_calibration_absente"], "candidate_active": False}
    journal = registre_calibration_versions_production()
    prefixe_immediat = _prefixe_recu_wct(list(registre_estime_vs_reel_production()))
    if (prefixe_immediat is None or prefixe_immediat["count"] != prefixe["count"]
            or prefixe_immediat["sha256"] != prefixe["sha256"]):
        return {"statut": "refuse", "raisons": ["prefixe_wct_m3_concurrent"], "candidate_active": False}
    resultat = calibration_versions.proposer_candidate(journal, rapport, politique=politique)
    resultat["rapport_sha256"] = rapport.get("rapport_sha256")
    resultat["holdout_initial_non_utilise"] = True
    resultat["candidate_active"] = False
    if isinstance(resultat.get("candidates"), list):
        resultat["candidates"] = [
            {
                "candidate_id": item["candidate_id"],
                "type_service": item["scope"]["type_service"],
                "unite_quantite": item["scope"]["unite_quantite"],
                "bareme_version": item["scope"]["bareme_version"],
                "quantite_exacte": item["scope"]["quantite_exacte"],
                "taux_minutes_par_unite_reference": item["scope"]["taux_minutes_par_unite_reference"],
                "taux_minutes_par_unite_candidat": item["taux_minutes_par_unite_candidat"],
                "source_horizon_utc": item["source_horizon_utc"],
                "holdout_cutoff_utc": item["holdout_cutoff_utc"],
                "politique_version": item["politique"]["version"],
                "politique_sha256": item["politique_sha256"],
                "candidate_active": False,
            }
            for item in resultat["candidates"]
        ]
    return resultat


def evaluer_candidate_calibration(candidate_id: str) -> dict[str, Any]:
    """Compare baseline et candidate sur une nouvelle fenêtre explicitement coupée, après le protocole figé."""
    try:
        candidate = calibration_versions.lire_candidate(registre_calibration_versions_production(), candidate_id)
    except ValueError:
        return {"statut": "refuse", "raisons": ["journal_calibration_invalide"], "candidate_active": False}
    if candidate is None:
        return {"statut": "refuse", "raisons": ["candidate_introuvable"], "candidate_active": False}
    prefixe_actuel = _prefixe_recu_wct(list(registre_estime_vs_reel_production()))
    prefixe_attendu = candidate.get("source_wct_prefix")
    if (prefixe_actuel is None or not isinstance(prefixe_attendu, dict)
            or type(prefixe_attendu.get("count")) is not int
            or prefixe_attendu["count"] > prefixe_actuel["count"]):
        return {"statut": "refuse", "raisons": ["prefixe_wct_m3_indisponible"], "candidate_active": False}
    prefixe_serialise = {
        "version": "m03-wct-prefix/1",
        "entrees": prefixe_actuel["entrees"][:prefixe_attendu["count"]],
    }
    digest_prefixe = hashlib.sha256(json.dumps(
        prefixe_serialise, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
    ).encode("utf-8")).hexdigest()
    hashes_ids_prefixe = sorted(
        calibration_versions.empreinte_identifiant_wct(wct_id)
        for wct_id, rang in prefixe_actuel["rangs"].items() if rang < prefixe_attendu["count"]
    )
    if (digest_prefixe != prefixe_attendu.get("sha256")
            or hashes_ids_prefixe != prefixe_attendu.get("wct_id_hashes")):
        return {"statut": "refuse", "raisons": ["prefixe_wct_m3_modifie"], "candidate_active": False}
    rapport = evaluer_calibration_cohortes(candidate["holdout_cutoff_utc"], _inclure_observations=True)
    observations = rapport.pop("observations_qualifiees", [])
    if rapport.get("statut") == "refuse":
        return {"statut": "refuse", "raisons": rapport.get("raisons", ["source_m4_refusee"]),
                "candidate_active": False}
    try:
        horizon_text = candidate["source_horizon_utc"]
        horizon = datetime.fromisoformat(
            horizon_text[:-1] + "+00:00" if horizon_text.endswith("Z") else horizon_text
        ).astimezone(UTC)
    except (AttributeError, KeyError, TypeError, ValueError):
        return {"statut": "refuse", "raisons": ["horizon_source_invalide"], "candidate_active": False}
    provenance = rapport.get("provenance_observations", [])
    holdout_wct_ids = {
        item.get("wct_id") for item in provenance
        if isinstance(item, dict) and item.get("partition") == "holdout"
    }
    # Dénominateur conservateur : les WCT du holdout observés et les WCT identifiables refusés
    # ou exclus restent comptés. Le corpus M4 n'est pas déclaré exhaustif.
    known_holdout_ids = set(holdout_wct_ids)
    for entry in rapport.get("exclusions", []) + rapport.get("refus_projection_m4", []):
        if isinstance(entry, dict) and isinstance(entry.get("wct_id"), str):
            known_holdout_ids.add(entry["wct_id"])
    futur = []
    for observation in observations:
        if observation.get("wct_id") not in holdout_wct_ids:
            continue
        try:
            debut_text = observation["horodatage_debut"]
            debut = datetime.fromisoformat(
                debut_text[:-1] + "+00:00" if debut_text.endswith("Z") else debut_text
            )
            if debut.tzinfo is None or debut.utcoffset() != timedelta(0):
                continue
            debut = debut.astimezone(UTC)
        except (AttributeError, KeyError, TypeError, ValueError):
            continue
        if debut <= horizon:
            continue
        rang_admission = prefixe_actuel["rangs"].get(observation.get("wct_id"))
        if rang_admission is None or rang_admission < prefixe_attendu["count"]:
            continue
        futur.append({
            **observation,
            "duree_estimee_minutes": format(observation["duree_estimee_minutes"], "f"),
            "quantite": format(observation["quantite"], "f"),
            "taux_minutes_par_unite": format(observation["taux_minutes_par_unite"], "f"),
            "taux_minutes_par_unite_source": format(observation["taux_minutes_par_unite_source"], "f"),
        })
    ids_admis_apres_sceau = {
        wct_id for wct_id, rang in prefixe_actuel["rangs"].items()
        if rang >= prefixe_attendu["count"]
    }
    return calibration_versions.evaluer_candidate(
        registre_calibration_versions_production(), candidate_id, futur,
        couverture_denominateur=len(known_holdout_ids | ids_admis_apres_sceau),
    )


def activer_candidate_calibration(candidate_id: str, active_version_attendue: str | None = None) -> dict[str, Any]:
    signataire = approbateur_en_cours(
        stockage.connexion_courante(), "m3_activer_candidate_calibration", "m03-estimation",
        roles=frozenset({"nathan_owner"}),
    )
    if signataire is None:
        return {"accepte": False, "raisons": ["approbateur_nathan_owner_requis"], "candidate_active": False}
    return calibration_versions.activer_candidate(
        registre_calibration_versions_production(), candidate_id,
        active_version_attendue=active_version_attendue,
        approbateur={"personne": signataire.personne, "role": signataire.role},
    )


def rollback_candidate_calibration(candidate_id: str) -> dict[str, Any]:
    signataire = approbateur_en_cours(
        stockage.connexion_courante(), "m3_rollback_candidate_calibration", "m03-estimation",
        roles=frozenset({"nathan_owner"}),
    )
    if signataire is None:
        return {"accepte": False, "raisons": ["approbateur_nathan_owner_requis"], "candidate_active": False}
    return calibration_versions.revoquer_candidate(
        registre_calibration_versions_production(), active_version_attendue=candidate_id,
        approbateur={"personne": signataire.personne, "role": signataire.role},
    )


def _calibration_active_pour_demande(
    contrat: dict[str, Any], bareme: dict[str, Any], quantite: float,
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(contrat, dict) or not isinstance(bareme, dict):
        return None, None
    service = contrat.get("service", contrat.get("type_travaux"))
    if not isinstance(service, str):
        return None, None
    try:
        baseline, taux, verdict = estimation._duree_estimee_minutes_texte(quantite, bareme, service)
    except (AttributeError, TypeError, ValueError):
        return None, None
    if verdict is not None or baseline is None or taux is None:
        return None, None
    try:
        journal = registre_calibration_versions_production()
        valide, _ = calibration_versions.valider_journal(list(journal))
        if not valide:
            return None, "journal_calibration_invalide"
        active = calibration_versions.version_active(
            list(journal), service, bareme.get("unite"), bareme.get("version"),
            estimation.trace_calibration_temps.empreinte_bareme(bareme),
            format(Decimal(str(quantite)), "f"), format(taux, "f"), None,
        )
        profondeur = 0
        while active is not None and profondeur < 16:
            suivant = calibration_versions.version_active(
                list(journal), service, bareme.get("unite"), bareme.get("version"),
                estimation.trace_calibration_temps.empreinte_bareme(bareme),
                format(Decimal(str(quantite)), "f"), active["taux_minutes_par_unite_candidat"],
                active["candidate_id"],
            )
            if suivant is None:
                return active, None
            if suivant["candidate_id"] == active["candidate_id"]:
                return None, "cycle_calibration"
            active = suivant
            profondeur += 1
        if profondeur >= 16:
            return None, "profondeur_calibration_depassee"
        return active, None
    except (ArithmeticError, KeyError, TypeError, ValueError, RecursionError):
        return None, "journal_calibration_invalide"


# ---------------------------------------------------------------------------------------------
# Consommateurs d'événements (ADR-0009 §3, PLAN T1.2-d) : seul cet adaptateur connaît `opsys` ;
# `estime_vs_reel.py` (module pur) fait le rapprochement et l'enregistrement déterministes. Le
# répartiteur (`opsys.evenements.repartir`) n'appelle ces fonctions que dans une transaction déjà
# ouverte : le registre durable fait donc TOUJOURS autorité ici (comme les outils T1/T3
# ci-dessus), sans le mode « en mémoire » des tests unitaires du module pur.
# ---------------------------------------------------------------------------------------------
def _recevoir_travaux_termines(charge: dict[str, Any]) -> dict[str, Any]:
    """Consomme le WCT; une mesure n'est comparable qu'avec le hash explicite du devis et une
    chaîne M3 valide. Une chaîne cassée rend la mesure indisponible, sans bloquer la réception du WCT."""
    journal = registre_production()
    try:
        valide, _ = journal.valider_chaine()
        maillons_estimations = journal.lire() if valide else []
    except (AttributeError, KeyError, TypeError, ValueError, RecursionError):
        maillons_estimations = []
    resultat = estime_vs_reel.enregistrer_travaux_termines(
        charge, registre_devis_production(), maillons_estimations, registre_estime_vs_reel_production()
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


def auditer_couverture_apprentissage() -> dict[str, Any]:
    """Diagnostic des publications M4 reçues par M3, réservé à l'admin appareil."""
    def autorise() -> bool:
        appareil = contexte.identite_appelante()
        cnx = stockage.connexion_courante()
        if cnx is None or appareil is None or appareil.source != "appareil" or appareil.role != "admin":
            return False
        personne = identite.personne_active(cnx, appareil.personne)
        return personne is not None and "admin" in personne.roles

    return couverture_apprentissage.auditer(lire_prefixe=_prefixe_recu_wct, autorise=autorise)


def lire_apprentissage_chantier(wct_id: str, coupure_utc: str) -> dict[str, Any]:
    """Lecture M3 bornée d'un chantier, sans promotion, mutation ni inférence causale.

    Les sources aval sont lues par leurs outils T0 existants, sous l'identité admin de l'appel
    d'appareil. Le rapport de raccord M3 reste l'autorité de la jointure estimation/devis/WCT.
    """
    appareil = contexte.identite_appelante()
    cnx = stockage.connexion_courante()
    personne = identite.personne_active(cnx, appareil.personne) if cnx is not None and appareil else None
    if (
        appareil is None or getattr(appareil, "source", None) != "appareil" or appareil.role != "admin"
        or personne is None or "admin" not in personne.roles
    ):
        return {"statut": "refuse", "raison": "identite_admin_authentifiee_requise"}
    if not isinstance(wct_id, str) or not wct_id or len(wct_id) > 128:
        return {"statut": "refuse", "raison": "wct_id_invalide"}
    try:
        horodatage = datetime.fromisoformat(coupure_utc.replace("Z", "+00:00"))
    except (AttributeError, TypeError, ValueError):
        return {"statut": "refuse", "raison": "coupure_utc_invalide"}
    if horodatage.tzinfo is None or horodatage.utcoffset() != timedelta(0):
        return {"statut": "refuse", "raison": "coupure_utc_invalide"}

    try:
        from opsys.capacites import Capacites
        from opsys.departements import charger_departements

        departements = charger_departements()
        cibles = {nom: departements[nom] for nom in (
            "m03-estimation", "m04-field-ops", "m05-financecore", "m08-analytics",
        )}
        capacites = Capacites(
            cibles, stockage.transaction, appelant="m03-estimation", limite_sortie=6_000, memoire=False,
        )
        projection = capacites.appeler("m4_lire_faits_calibration_m3", {"wct_ids": [wct_id]})
        if not projection.get("ok") or not isinstance(projection.get("resultat"), dict):
            return {"statut": "exclu", "wct_id": wct_id, "exclusions": ["projection_m4_indisponible"], "cause": None}
        projection_m4 = projection["resultat"]
        observations_m4 = projection_m4.get("observations", [])
        exactes_m4 = [
            o for o in observations_m4
            if isinstance(o, dict) and isinstance(o.get("wct"), dict) and o["wct"].get("wct_id") == wct_id
        ]
        if len(exactes_m4) != 1:
            refus = [
                str(m.get("motif", "fait_m4_refuse")) for m in projection_m4.get("refus", [])
                if isinstance(m, dict) and m.get("wct_id") in (None, wct_id)
            ]
            raison = "wct_m4_absent" if not exactes_m4 else "wct_m4_ambigu"
            return {"statut": "exclu", "wct_id": wct_id,
                    "exclusions": sorted(set(refus + [raison])), "cause": None}
        projections = {"observations": observations_m4, "refus": projection_m4.get("refus", [])}
        journal_estimations = registre_production()
        journal_devis = registre_devis_production()
        maillons_estimations = journal_estimations.lire()
        if not isinstance(maillons_estimations, list):
            return {"statut": "refuse", "wct_id": wct_id, "raison": "registre_estimations_illisible"}
        if len(maillons_estimations) > 20_000:
            return {"statut": "refuse", "wct_id": wct_id, "raison": "limite_registre_estimations_depassee"}
        if len(journal_devis) > 10_000:
            return {"statut": "refuse", "wct_id": wct_id, "raison": "limite_registre_devis_depassee"}
        rapport_m3 = calibration_raccord.construire_rapport(
            coupure_utc=coupure_utc,
            registre_estimations=journal_estimations,
            registre_devis=journal_devis,
            projections_m4=projections,
            _inclure_observations=True,
        )
        observations_m3 = [
            o for o in rapport_m3.get("_observations_qualifiees", [])
            if isinstance(o, dict) and o.get("wct_id") == wct_id
        ]
        if len(observations_m3) != 1:
            compteurs = rapport_m3.get("refus_jointure_m3", {})
            exclusions = [f"jointure_m3:{code}" for code, nombre in compteurs.items() if nombre]
            if not exclusions:
                exclusions = ["jointure_m3_absente_ou_ambigu"]
            return {"statut": "exclu", "wct_id": wct_id,
                    "exclusions": sorted(exclusions), "cause": None}
        observation = observations_m3[0]
        preuve = observation.get("preuve", {})
        provenance_m3 = [
            p for p in rapport_m3.get("provenance_observations", [])
            if isinstance(p, dict) and p.get("wct_id") == wct_id
        ]
        if len(provenance_m3) != 1:
            exclusions_calibration = [
                f"calibration:{raison}"
                for ligne in rapport_m3.get("exclusions", [])
                if isinstance(ligne, dict) and ligne.get("wct_id") == wct_id
                for raison in ligne.get("raisons", [])
            ]
            if not exclusions_calibration:
                exclusions_calibration = ["observation_non_admise_par_calibration_cohortes"]
            return {"statut": "exclu", "wct_id": wct_id,
                    "exclusions": sorted(exclusions_calibration), "cause": None}
        admission = provenance_m3[0]
        if (
            admission.get("m3_source_hash") != preuve.get("m3_source_hash")
            or admission.get("m4_wct_hash") != preuve.get("m4_wct_hash")
            or admission.get("partition") not in {"train", "holdout"}
        ):
            return {"statut": "exclu", "wct_id": wct_id,
                    "exclusions": ["provenance_calibration_absente_ou_divergente"], "cause": None}
        devis_id = observation.get("devis_id")
        if not isinstance(devis_id, str) or not devis_id:
            return {"statut": "exclu", "wct_id": wct_id,
                    "exclusions": ["devis_id_absent_de_la_jointure_m3"], "cause": None}

        resultat_m5 = capacites.appeler(
            "m5_lire_rentabilite_chantier", {"devis_id": devis_id, "limite": 1},
        )
        if not resultat_m5.get("ok") or not isinstance(resultat_m5.get("resultat"), dict):
            return {"statut": "exclu", "wct_id": wct_id, "devis_id": devis_id,
                    "exclusions": ["lecture_m5_indisponible"], "cause": None}
        resultat_m5 = resultat_m5["resultat"].get("resultat", {})
        chantiers_m5 = resultat_m5.get("chantiers", [])
        chantiers_exactes = [c for c in chantiers_m5 if isinstance(c, dict) and c.get("devis_id") == devis_id]
        if (
            resultat_m5.get("nombre") != 1 or resultat_m5.get("affichees") != 1
            or resultat_m5.get("reste") != 0 or len(chantiers_exactes) != 1
        ):
            return {"statut": "exclu", "wct_id": wct_id, "devis_id": devis_id,
                    "exclusions": ["rentabilite_m5_absente_ou_ambiguite_devis"], "cause": None}
        chantier_m5 = chantiers_exactes[0]
        def _detail_rentabilite(ligne: dict[str, Any]) -> dict[str, Any]:
            # Le filtre devis_id demande la vue DETAIL M5 : cout_reel.complet et
            # marge_reelle. Les clés de l'événement M5 ne sont pas celles de cet outil.
            detail = ligne.get("rentabilite")
            detail = detail if isinstance(detail, dict) else {}
            cout = detail.get("cout_reel")
            cout = cout if isinstance(cout, dict) else {}
            return {
                "verdict": detail.get("verdict"),
                "prix_definitif": detail.get("prix_definitif"),
                "cout_reel_complet": cout.get("complet"),
                "marge_reelle_cad": detail.get("marge_reelle"),
            }

        rentabilite = _detail_rentabilite(chantier_m5)
        trace_m5 = chantier_m5.get("trace")
        trace_m5 = trace_m5 if isinstance(trace_m5, dict) else {}
        version_m5 = trace_m5.get("version_entrees")

        resultat_m8 = capacites.appeler("m8_lire_mesures_chantier", {"wct_id": wct_id})
        if not resultat_m8.get("ok") or not isinstance(resultat_m8.get("resultat"), dict):
            return {"statut": "exclu", "wct_id": wct_id, "devis_id": devis_id,
                    "exclusions": ["lecture_m8_indisponible"], "cause": None}
        resultat_m5_apres = capacites.appeler(
            "m5_lire_rentabilite_chantier", {"devis_id": devis_id, "limite": 1},
        )
        if not resultat_m5_apres.get("ok") or not isinstance(resultat_m5_apres.get("resultat"), dict):
            return {"statut": "refuse", "wct_id": wct_id,
                    "raison": "relecture_m5_indisponible_pendant_controle_de_coherence"}
        resultat_m5_apres = resultat_m5_apres["resultat"].get("resultat", {})
        chantiers_m5_apres = resultat_m5_apres.get("chantiers", [])
        chantiers_m5_apres = [c for c in chantiers_m5_apres if isinstance(c, dict) and c.get("devis_id") == devis_id]
        if (
            resultat_m5_apres.get("nombre") != 1 or resultat_m5_apres.get("affichees") != 1
            or resultat_m5_apres.get("reste") != 0 or len(chantiers_m5_apres) != 1
        ):
            return {"statut": "refuse", "wct_id": wct_id,
                    "raison": "rentabilite_m5_ambigue_pendant_controle_de_coherence"}
        m5_apres = chantiers_m5_apres[0]
        trace_m5_apres = m5_apres.get("trace")
        trace_m5_apres = trace_m5_apres if isinstance(trace_m5_apres, dict) else {}
        if (
            not isinstance(m5_apres.get("rentabilite"), dict)
            or trace_m5_apres.get("version_entrees") != version_m5
            or trace_m5_apres.get("a_jour") != trace_m5.get("a_jour")
            or _detail_rentabilite(m5_apres) != rentabilite
        ):
            return {"statut": "refuse", "wct_id": wct_id,
                    "raison": "version_ou_trace_m5_changee_pendant_lecture"}
        resultat_m8_apres = capacites.appeler("m8_lire_mesures_chantier", {"wct_id": wct_id})
        if not resultat_m8_apres.get("ok") or not isinstance(resultat_m8_apres.get("resultat"), dict):
            return {"statut": "refuse", "wct_id": wct_id,
                    "raison": "relecture_m8_indisponible_pendant_controle_de_coherence"}
        mesures_m8 = resultat_m8["resultat"].get("mesures", [])
        def _metrics(lignes: Any, metric_id: str) -> list[dict[str, Any]]:
            return [m for m in lignes if isinstance(m, dict) and m.get("metric_id") == metric_id]

        marges_m8 = _metrics(mesures_m8, "m8_marge_reelle_cad")
        variances_m8 = _metrics(mesures_m8, "m8_ecart_materiaux_max_pct")
        if len(marges_m8) > 1 or len(variances_m8) > 1:
            return {"statut": "refuse", "wct_id": wct_id,
                    "raison": "metrique_m8_dupliquee"}
        marge_m8 = marges_m8[0] if marges_m8 else {}
        entrees_m8 = marge_m8.get("entrees", {})
        mesures_m8_apres = resultat_m8_apres["resultat"].get("mesures", [])
        marges_m8_apres = _metrics(mesures_m8_apres, "m8_marge_reelle_cad")
        variances_m8_apres = _metrics(mesures_m8_apres, "m8_ecart_materiaux_max_pct")
        if len(variances_m8_apres) > 1:
            return {"statut": "refuse", "wct_id": wct_id,
                    "raison": "metrique_variance_m8_dupliquee_pendant_controle_de_coherence"}
        if len(marges_m8_apres) > 1:
            return {"statut": "refuse", "wct_id": wct_id,
                    "raison": "metrique_m8_dupliquee_pendant_controle_de_coherence"}
        marge_m8_apres = marges_m8_apres[0] if marges_m8_apres else {}
        if (
            marge_m8_apres.get("statut") != marge_m8.get("statut")
            or marge_m8_apres.get("valeur") != marge_m8.get("valeur")
            or marge_m8_apres.get("entrees", {}).get("version_entrees") != entrees_m8.get("version_entrees")
        ):
            return {"statut": "refuse", "wct_id": wct_id,
                    "raison": "version_ou_mesure_m8_changee_pendant_lecture"}
        variance_m8_apres = variances_m8_apres[0] if variances_m8_apres else {}
        variance_m8_changee = (
            any(variance_m8_apres.get(cle) != variances_m8[0].get(cle) for cle in (
                "statut", "valeur", "unite", "entrees", "version_definition",
            )) if variances_m8 else bool(variances_m8_apres)
        )
        if variance_m8_changee:
            return {"statut": "refuse", "wct_id": wct_id,
                    "raison": "variance_m8_changee_pendant_lecture"}
        projection_finale = capacites.appeler("m4_lire_faits_calibration_m3", {"wct_ids": [wct_id]})
        if not projection_finale.get("ok") or not isinstance(projection_finale.get("resultat"), dict):
            return {"statut": "refuse", "wct_id": wct_id,
                    "raison": "relecture_m4_indisponible_pendant_controle_de_coherence"}
        observations_finales_m4 = [
            o for o in projection_finale["resultat"].get("observations", [])
            if isinstance(o, dict) and isinstance(o.get("wct"), dict) and o["wct"].get("wct_id") == wct_id
        ]
        if len(observations_finales_m4) != 1 or (
            observations_finales_m4[0].get("wct_hash") != exactes_m4[0].get("wct_hash")
            or observations_finales_m4[0].get("horodatage_completion") != exactes_m4[0].get("horodatage_completion")
        ):
            return {"statut": "refuse", "wct_id": wct_id,
                    "raison": "preuve_wct_m4_changee_pendant_lecture"}
        estimations_finales = registre_production()
        devis_finaux = registre_devis_production()
        maillons_estimations_finaux = estimations_finales.lire()
        if not isinstance(maillons_estimations_finaux, list):
            return {"statut": "refuse", "wct_id": wct_id,
                    "raison": "registre_estimations_illisible_pendant_lecture"}
        if len(maillons_estimations_finaux) > 20_000 or len(devis_finaux) > 10_000:
            return {"statut": "refuse", "wct_id": wct_id,
                    "raison": "limite_registre_m3_depassee_pendant_lecture"}
        rapport_m3_final = calibration_raccord.construire_rapport(
            coupure_utc=coupure_utc, registre_estimations=estimations_finales, registre_devis=devis_finaux,
            projections_m4={"observations": projection_finale["resultat"].get("observations", []),
                            "refus": projection_finale["resultat"].get("refus", [])},
            _inclure_observations=True,
        )
        observations_finales_m3 = [
            o for o in rapport_m3_final.get("_observations_qualifiees", [])
            if isinstance(o, dict) and o.get("wct_id") == wct_id
        ]
        if len(observations_finales_m3) != 1 or (
            observations_finales_m3[0].get("preuve", {}).get("m3_source_hash")
            != preuve.get("m3_source_hash")
            or observations_finales_m3[0].get("preuve", {}).get("m4_wct_hash")
            != preuve.get("m4_wct_hash")
            or observations_finales_m3[0].get("duree_estimee_minutes") != observation.get("duree_estimee_minutes")
            or observations_finales_m3[0].get("duree_reelle_minutes") != observation.get("duree_reelle_minutes")
        ):
            return {"statut": "refuse", "wct_id": wct_id,
                    "raison": "jointure_m3_changee_pendant_lecture"}
        admissions_finales = [
            p for p in rapport_m3_final.get("provenance_observations", [])
            if isinstance(p, dict) and p.get("wct_id") == wct_id
        ]
        if len(admissions_finales) != 1 or any(
            admissions_finales[0].get(cle) != admission.get(cle)
            for cle in ("m3_source_hash", "m4_wct_hash", "partition")
        ):
            return {"statut": "refuse", "wct_id": wct_id,
                    "raison": "admission_calibration_changee_pendant_lecture"}
        exclusions_marge = []
        if "prix_definitif" not in rentabilite:
            exclusions_marge.append("finalite_facture_inconnue")
        elif rentabilite.get("prix_definitif") is not True:
            exclusions_marge.append("facture_brouillon_ou_prix_non_definitif")
        if rentabilite.get("cout_reel_complet") is not True:
            exclusions_marge.append("cout_reel_incomplet_ou_inconnu")
        if rentabilite.get("verdict") != "CALCULEE":
            exclusions_marge.append("verdict_m5_non_calculee")
        version_m8 = entrees_m8.get("version_entrees")
        if not isinstance(version_m5, str) or not version_m5:
            exclusions_marge.append("version_entrees_m5_absente")
        if not isinstance(version_m8, str) or not version_m8:
            exclusions_marge.append("version_entrees_m8_absente")
        elif version_m8 != version_m5:
            exclusions_marge.append("version_entrees_m8_divergente_de_m5")
        if trace_m5.get("a_jour") is not True:
            exclusions_marge.append("trace_m5_non_a_jour")
        if marge_m8.get("statut") != "calculee" or marge_m8.get("valeur") != rentabilite.get("marge_reelle_cad"):
            exclusions_marge.append("mesure_marge_m8_absente_ou_divergente")

        variance_m8 = variances_m8[0] if variances_m8 else {}
        variance = {
            "statut": variance_m8.get("statut", "non_calculable"),
            "valeur": variance_m8.get("valeur"),
            "unite": variance_m8.get("unite"),
            "source": "M6 via faits reçus par M8",
            "cause": None,
        }
        exclusions_variance = []
        if variance["statut"] != "calculee":
            exclusions_variance.append("variance_m6_absente_ou_non_evaluee")
        unite_materiau = variance_m8.get("entrees", {}).get("unite")
        if not isinstance(unite_materiau, str) or not unite_materiau.strip():
            exclusions_variance.append("unite_materiau_absente_ou_inconnue")
        if variance["unite"] != "pourcentage":
            exclusions_variance.append("unite_variance_absente_ou_inconnue")
        variance["unite_materiau"] = unite_materiau if not exclusions_variance else None
        if exclusions_variance:
            variance.update({"statut": "exclue", "valeur": None, "exclusions": exclusions_variance})

        def _json_metier(valeur: Any) -> Any:
            if isinstance(valeur, Decimal):
                return format(valeur, "f")
            if valeur is None or type(valeur) in (str, int, bool):
                return valeur
            return None

        sortie = {
            "statut": "observee",
            "coupure_utc": coupure_utc,
            "sources": {
                "wct_id": wct_id, "devis_id": devis_id,
                "estimation_hash": preuve.get("m3_source_hash"),
                "wct_hash": preuve.get("m4_wct_hash"),
                "version_calibration": observation.get("calibration_version_id"),
                "partition_calibration": admission["partition"],
                "horodatage_completion_utc": observation.get("horodatage_completion"),
            },
            "temps": {
                "estime_minutes": _json_metier(observation.get("duree_estimee_minutes")),
                "ecoule_reel_minutes": _json_metier(observation.get("duree_reelle_minutes")),
                "semantique": observation.get("preuve", {}).get("semantique_reel"),
                "unite": observation.get("preuve", {}).get("unite_duree_reelle"),
                "paie_heures_personnes": "non mesurees par ces sources",
                "trace_m3": {k: _json_metier(observation.get(k)) for k in (
                    "type_service", "quantite", "unite_quantite", "taux_minutes_par_unite", "bareme_version",
                )},
            },
            "variance_materiaux": variance,
            "rentabilite": {
                "statut": "exclue" if exclusions_marge else "qualifiee",
                "montant_marge_reelle_cad": None if exclusions_marge else rentabilite.get("marge_reelle_cad"),
                "prix_definitif": rentabilite.get("prix_definitif"),
                "cout_reel_complet": rentabilite.get("cout_reel_complet"),
                "verdict_m5": rentabilite.get("verdict"),
                "version_entrees_m5": version_m5,
                "version_entrees_m8": version_m8,
                "trace_m5_a_jour": trace_m5.get("a_jour"),
                "exclusions": sorted(set(exclusions_marge)),
            },
            "cause": None,
            "lecture_intermodules": "sources relues séquentiellement; aucun snapshot transactionnel commun garanti",
        }
        # Revalider l'identité active juste avant la réponse; les T0 du dispatcher ne suffisent pas.
        personne_finale = identite.personne_active(stockage.connexion_courante(), appareil.personne)
        if personne_finale is None or "admin" not in personne_finale.roles:
            return {"statut": "refuse", "raison": "identite_admin_revoquee_pendant_lecture"}
        enveloppe = {"ok": True, "resultat": sortie}
        if len(json.dumps(enveloppe, ensure_ascii=False)) > 6_000:
            return {"statut": "refuse", "wct_id": wct_id, "raison": "rapport_trop_volumineux"}
        return sortie
    except (AttributeError, ImportError, KeyError, TypeError, ValueError, RecursionError):
        return {"statut": "exclu", "wct_id": wct_id,
                "exclusions": ["source_ou_projection_illisible"], "cause": None}


def evaluer_calibration_cohortes(
    coupure_utc: str, *, _inclure_observations: bool = False, _train_only: bool = False,
) -> dict[str, Any]:
    """Rapport de calibration candidat, formé depuis M4 et les registres M3 relus en serveur."""
    appareil = contexte.identite_appelante()
    origine = contexte.departement_origine_appelante()
    if appareil is not None and appareil.role != "admin":
        return {"statut": "refuse", "raisons": ["role_appareil_non_autorise"], "candidate_active": False}
    if origine != "m03-estimation" and appareil is None:
        return {"statut": "refuse", "raisons": ["departement_appelant_non_autorise"], "candidate_active": False}
    try:
        from opsys.capacites import Capacites
        from opsys.departements import charger_departements

        departements = charger_departements()
        cibles = {nom: departements[nom] for nom in ("m03-estimation", "m04-field-ops")}
        capacites = Capacites(
            cibles, stockage.transaction, appelant="m03-estimation", limite_sortie=200_000, memoire=False,
        )
        registre_rapport = registre_estime_vs_reel_production()
        if len(registre_rapport) > 2000:
            return {"statut": "refuse", "raisons": ["limite_wct_m3_depassee"], "candidate_active": False}
        maillons_wct = list(registre_rapport)
        wct_ids = sorted({
            maillon["wct_id"] for maillon in maillons_wct
            if isinstance(maillon, dict) and maillon.get("type_entree") == "wct_recu"
            and isinstance(maillon.get("wct_id"), str)
        })
        if len(wct_ids) > 2000:
            return {"statut": "refuse", "raisons": ["limite_wct_m3_depassee"], "candidate_active": False}
        projections_m4: list[dict[str, Any]] = []
        for debut in range(0, len(wct_ids), 200):
            resultat = capacites.appeler(
                "m4_lire_faits_calibration_m3", {"wct_ids": wct_ids[debut:debut + 200]},
            )
            if not resultat.get("ok") or not isinstance(resultat.get("resultat"), dict):
                return {
                    "statut": "refuse", "raisons": ["projection_m4_refusee_ou_indisponible"],
                    "candidate_active": False,
                }
            projections_m4.append(resultat["resultat"])
        projections = {
            "observations": [
                observation for projection in projections_m4 for observation in projection.get("observations", [])
            ],
            "refus": [refus for projection in projections_m4 for refus in projection.get("refus", [])],
        }
    except (ImportError, KeyError, TypeError, ValueError, RecursionError):
        return {"statut": "refuse", "raisons": ["projection_m4_indisponible"], "candidate_active": False}
    journal_estimations = registre_production()
    journal_devis = registre_devis_production()
    if len(stockage.maillons("m03-estimation", "principal")) > 20000:
        return {"statut": "refuse", "raisons": ["limite_registre_estimations_depassee"], "candidate_active": False}
    if len(journal_devis) > 10000:
        return {"statut": "refuse", "raisons": ["limite_registre_devis_depassee"], "candidate_active": False}
    rapport = calibration_raccord.construire_rapport(
        coupure_utc=coupure_utc,
        registre_estimations=journal_estimations,
        registre_devis=journal_devis,
        projections_m4=projections,
        _inclure_observations=_inclure_observations,
        _train_only=_train_only,
    )
    if rapport.get("statut") in {"candidate", "insuffisant"}:
        observation_rows = rapport.get("_observations_qualifiees", [])
        if _train_only:
            train_ids = {
                row.get("wct_id") for row in rapport.get("provenance_observations", [])
                if isinstance(row, dict) and row.get("partition") == "train"
            }
            observation_rows = [row for row in observation_rows if row.get("wct_id") in train_ids]
        horizons = [row["horodatage_completion"] for row in observation_rows if isinstance(row, dict)]
        if horizons:
            rapport["source_horizon_utc"] = max(horizons)
        if _inclure_observations:
            rapport["observations_qualifiees"] = observation_rows
        else:
            rapport.pop("_observations_qualifiees", None)
        public = {
            key: value for key, value in rapport.items()
            if key not in {"observations_qualifiees", "_observations_qualifiees"}
        }
        public.pop("rapport_sha256", None)
        rapport["rapport_sha256"] = hashlib.sha256(
            json.dumps(public, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
        ).hexdigest()
        rapport.pop("_observations_qualifiees", None)
    return rapport


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
_OUTIL_ACCEPTATION_DEVIS = "m3_marquer_devis_accepte"
_TYPE_ATTENTE_REVUE_ACCEPTATION = "revue_acceptation_devis"
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


def _configuration_du_manifeste() -> Any:
    """`configuration` de `department.yaml`, telle quelle : un objet, `None` (absente ou d'une autre forme), ou
    `_CONFIGURATION_ILLISIBLE` (manifeste illisible). Une `configuration` qui n'est pas un objet vaut `None` : le
    marqueur (un texte) ne se confond jamais avec une valeur du fichier. Lue à chaque appel, jamais mise en cache :
    le propriétaire peut l'éditer, et les tests la remplacent par un manifeste jetable (`_MANIFESTE`)."""
    try:
        donnees = yaml.safe_load(_MANIFESTE.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return _CONFIGURATION_ILLISIBLE
    configuration = donnees.get("configuration") if isinstance(donnees, dict) else None
    return configuration if isinstance(configuration, dict) else None


def _seuils_revue() -> Any:
    """`configuration.revue_devis` de `department.yaml`, tel quel (`None` s'il est absent) : les seuils de la
    revue, JAMAIS un nombre codé en dur ici ni dans `revue_devis.py`. Même source et même discipline que M6
    (`_seuil_variance_chantier`) : `revue_devis` juge chaque seuil vide ou invalide « seuil à configurer » ou
    « seuil invalide », jamais une valeur par défaut. Un manifeste illisible rend `_CONFIGURATION_ILLISIBLE`
    (que `revue_devis` refuse de lire comme des seuils) : la revue le dit, elle ne tombe pas."""
    configuration = _configuration_du_manifeste()
    if configuration is None or configuration == _CONFIGURATION_ILLISIBLE:
        return configuration
    return configuration.get("revue_devis")


def _taux_scenarios_configures() -> Any:
    """`configuration.scenarios_prix.taux_marge` de `department.yaml`, tel quel (`None` s'il est absent) : les taux de
    marge des trois scénarios (PLAN T4.11), JAMAIS un taux codé en dur ici ni dans `scenarios.py`. VIDES à dessein : un
    taux vide est un taux à déclarer (verdict `REJ-SCENARIOS-TAUX-ABSENT`), jamais une marge inventée. Un manifeste
    illisible rend `_CONFIGURATION_ILLISIBLE` (que `scenarios` refuse de lire comme des taux, scénario par scénario)."""
    configuration = _configuration_du_manifeste()
    if configuration is None or configuration == _CONFIGURATION_ILLISIBLE:
        return configuration
    scenarios_prix = configuration.get("scenarios_prix")
    return scenarios_prix.get("taux_marge") if isinstance(scenarios_prix, dict) else None


def _decision_approuvee_en_cours(cnx: Any, arguments: dict[str, Any]) -> tuple[str, str, str] | None:
    """`(personne, rôle, instant)` de la décision qui fait exécuter CET appel, sinon `None`. Lecture seule.

    `approbations.decider` réserve la demande (`en_attente` -> `en_cours`, avec `decide_par`, `decide_role` et
    `decide_le`), pose son identifiant autour de l'outil (`contexte.executer_demande_approuvee`) puis l'exécute
    avec les arguments EXACTS enregistrés, dans la même transaction. Cet appel EST donc l'exécution d'une décision
    si et seulement si le socle la reconnaît (`approbateur_en_cours`, PLAN T4.15-e : CETTE demande, `en_cours`, de
    cet outil et de ce département, approuvée par `nathan_owner` toujours actif et portant ce rôle) ET qu'elle porte
    exactement ces arguments. Une autre ligne `en_cours`, même aux mêmes arguments, n'est pas cette décision : seul
    le pointeur posé par `decider` désigne la demande exécutée. `decide_le` est celui de cette demande, l'horloge du
    socle au moment de la décision : M3 ne lit jamais l'heure."""
    if cnx is None:
        return None
    signataire = approbateur_en_cours(cnx, _OUTIL_ENVOI_DEVIS, _DEPARTEMENT, roles=_ROLES_APPROBATEURS_ENVOI)
    if signataire is None:
        return None
    ligne = cnx.execute(
        select(APPROBATIONS.c.arguments, APPROBATIONS.c.decide_le).where(
            APPROBATIONS.c.id == contexte.demande_approuvee_en_cours(),
        )
    ).one_or_none()
    if ligne is None or not ligne.decide_le or json.loads(ligne.arguments) != arguments:
        return None
    return signataire.personne, signataire.role, ligne.decide_le


_CHAMPS_FAITS_REVUE = ("verdict_estimation", "niveau_confiance_hierarchie", "alerte_plancher")


def _evaluer_revue_source(devis: dict[str, Any], contexte_revue: Any, seuils: Any) -> tuple[Any, Any]:
    """Une source liée prime sur les déclarations; une source inconnue ne devient jamais un fait."""
    source_hash = devis.get("estimation_source_hash")
    if source_hash is None:
        # Devis manuel: les faits restent ceux du contexte déclaré, sans preuve canonique inventée.
        return revue_devis.evaluer_revue(devis, contexte_revue, seuils)
    charge = _source_estimation_exacte(source_hash, devis["devis_id"], devis["lead_id"])
    if charge is None:
        return None, verdicts.construire_verdict(
            "REJ-REVUE-DEVIS-INVALIDE", detail="source d'estimation liée absente, altérée ou hors identité"
        )
    faits = charge.get("faits_revue")
    valide = (
        isinstance(faits, dict)
        and set(faits) == {"version", "prix_bloque", *_CHAMPS_FAITS_REVUE}
        and faits.get("version") == "m3.faits-revue/v1"
        and type(faits.get("prix_bloque")) is bool
        and type(faits.get("alerte_plancher")) is bool
        and faits.get("verdict_estimation") in contrats.VERDICTS_ESTIMATION
        and faits.get("niveau_confiance_hierarchie") in hierarchie_echelle.NIVEAUX_CONFIANCE
    )
    if contexte_revue is not None and not isinstance(contexte_revue, dict):
        return revue_devis.evaluer_revue(devis, contexte_revue, seuils)
    contexte_effectif = dict(contexte_revue or {})
    for cle in _CHAMPS_FAITS_REVUE:
        contexte_effectif.pop(cle, None)
    if valide:
        contexte_effectif.update({cle: faits[cle] for cle in _CHAMPS_FAITS_REVUE})
    revue, verdict = revue_devis.evaluer_revue(devis, contexte_effectif, seuils)
    if verdict is not None:
        return None, verdict
    revue["source_estimation"] = {
        "hash_maillon": source_hash, "devis_id": devis["devis_id"], "lead_id": devis["lead_id"],
        "statut": "faits_canoniques" if valide else "non_evaluable",
        "raison": None if valide else "historique_sans_faits" if "faits_revue" not in charge else "faits_invalides",
    }
    if valide:
        for motif in revue["motifs"]:
            if motif["donnee"]["nom"] in _CHAMPS_FAITS_REVUE:
                motif["donnee"]["source"] = "estimation_canonique"
    else:
        # Anciennes charges, valeur None ou snapshot mal formé: jamais le contexte en repli.
        revue["non_evaluables"].insert(0, {
            "code": ("SOURCE_ESTIMATION_HISTORIQUE_SANS_FAITS" if "faits_revue" not in charge
                     else "SOURCE_ESTIMATION_FAITS_NON_EVALUABLES"),
            "manque": ["faits de revue canoniques absents ou invalides"],
            "a_faire": ["faire qualifier la source; ne pas déduire ses faits du barème"],
        })
        revue["aucun_motif"] = False
    return revue, None


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
        revue, verdict = _evaluer_revue_source(devis, contexte_revue, _seuils_revue())
        if verdict is not None:
            return {"accepte": False, "verdict": verdict}
    # Le contenu d'un devis ne change jamais après sa création : seul son statut peut avoir bougé entre la revue et
    # l'écriture, et `marquer_devis_envoye` le relit à chaque essai (refus nommé s'il n'est plus `brouillon`).
    envoye, verdict = _rejouer_sur_ecriture_concurrente(lambda: devis_durable.marquer_devis_envoye(
        devis_id, decide_le, registre_devis, approuve_par=approuve_par, approuve_role=approuve_role,
        revue=revue_devis.synthese(revue) if revue is not None else None,
    ))
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


def _resume_demande_envoi(arguments: Any, registre_devis: Any, seuils: Any, *, acceptation: bool = False) -> str:
    """Le texte d'UNE demande d'envoi (ou d'acceptation) en attente, tel que le propriétaire le lit : la revue du
    devis tel qu'il est AUJOURD'HUI (`revue_devis.resume_attente`), ou, quand elle ne peut pas se faire, pourquoi.
    Jamais un silence : une demande qu'on ne sait pas lire reste visible, avec la raison.

    `acceptation` : la demande N5 de `m3_marquer_devis_accepte`. Un devis peut être accepté depuis `brouillon`,
    sans être passé par la revue d'envoi : le propriétaire lit alors la même revue (sans `contexte_revue`, que cette
    demande ne porte pas ; la source canonique liée prime comme à l'envoi) avant sa décision (§7 M3.11)."""
    limite = revue_devis.LIMITE_RESUME
    action, demande = ("Acceptation", "demandée") if acceptation else ("Envoi", "demandé")
    devis_id = arguments.get("devis_id") if isinstance(arguments, dict) else None
    if not isinstance(devis_id, str) or not devis_id.strip():
        return revue_devis.abreger(f"Demande d'{action.lower()} illisible : aucun devis_id. À refuser.", limite)
    devis, verdict = devis_durable.lire_devis(registre_devis, devis_id)
    if verdict is not None:
        return revue_devis.abreger(
            f"{action} du devis {devis_id} {demande}, mais ce devis est introuvable. À refuser.", limite
        )
    if devis["statut"] not in (("brouillon", "envoye") if acceptation else ("brouillon",)):
        return revue_devis.abreger(
            f"{action} du devis {devis_id} {demande}, mais il est déjà {devis['statut']} : rien à approuver.", limite
        )
    revue, verdict = _evaluer_revue_source(devis, None if acceptation else arguments.get("contexte_revue"), seuils)
    if verdict is not None:
        return revue_devis.abreger(
            f"{action} du devis {devis_id} : revue impossible ({verdict['code']} : {verdict['detail']}). "
            "À refuser ou à redemander.", limite,
        )
    resume = revue_devis.resume_attente(revue, limite, action)
    if revue.get("source_estimation", {}).get("statut") == "non_evaluable":
        raison = revue["source_estimation"]["raison"]
        message = ("source historique sans faits de revue" if raison == "historique_sans_faits"
                   else "faits de revue source invalides ou non disponibles")
        return revue_devis.abreger(message + " : " + resume, limite)
    return resume


def attentes() -> list[dict[str, Any]]:
    """L'attente de la file du propriétaire (ADR-0009 §5, PLAN T4.7) : une entrée par demande d'envoi de devis
    en attente, dont le résumé PORTE LES MOTIFS de la revue (alerte rouge d'abord, critères non évaluables
    comptés). Le vendeur crée la demande (le socle la met en file, l'outil ne s'exécute pas) ; cette fonction la
    lit et refait la revue sur le devis d'aujourd'hui, avec les faits que la demande a enregistrés et les
    seuils de `department.yaml`. L'entrée disparaît quand la demande est décidée. Lecture seule : ne crée
    rien, ne décide de rien. Hors transaction (aucune connexion), rien n'est lisible : liste vide.

    Ce n'est PAS la demande d'approbation (celle du socle, décidable) : c'est ce qui la rend lisible. Son `id`
    est celui de la demande, pour les retrouver l'une à côté de l'autre.

    De même, une entrée `revue_acceptation_devis` (N5) par demande d'acceptation en attente : l'acceptation est
    permise depuis `brouillon`, donc sans revue d'envoi, et le prix y devient un engagement ; le propriétaire lit
    la même revue avant de décider (§7 M3.11 : jamais sous le minimum rentable sans alerte rouge)."""
    cnx = stockage.connexion_courante()
    if cnx is None:
        return []
    demandes = cnx.execute(
        select(APPROBATIONS.c.id, APPROBATIONS.c.outil, APPROBATIONS.c.arguments, APPROBATIONS.c.cree_le).where(
            APPROBATIONS.c.statut == "en_attente",
            APPROBATIONS.c.outil.in_((_OUTIL_ENVOI_DEVIS, _OUTIL_ACCEPTATION_DEVIS)),
            APPROBATIONS.c.departement == _DEPARTEMENT,
        ).order_by(APPROBATIONS.c.cree_le, APPROBATIONS.c.id)
    ).all()
    if not demandes:
        return []
    registre_devis = registre_devis_production()
    seuils = _seuils_revue()
    attentes_revue: list[dict[str, Any]] = []
    for demande_id, outil, brut, cree_le in demandes:
        try:
            arguments: Any = json.loads(brut)
        except ValueError:
            arguments = None
        acceptation = outil == _OUTIL_ACCEPTATION_DEVIS
        attentes_revue.append({
            "type": _TYPE_ATTENTE_REVUE_ACCEPTATION if acceptation else _TYPE_ATTENTE_REVUE_ENVOI,
            "id": demande_id,
            "resume": _resume_demande_envoi(arguments, registre_devis, seuils, acceptation=acceptation),
            "niveau": (Niveau.N5 if acceptation else Niveau.N4).value,
            "depuis": cree_le,
            "action_proposee": (
                "approuver ou refuser l'acceptation à la console, avec l'attestation du professionnel (N5)"
                if acceptation
                else "approuver ou refuser l'envoi (le propriétaire décide)"
            ),
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
                "Estime un projet de bout en bout : valide le contrat LeadQualifie et le marqueur M2, la qualité des "
                "photos, la hiérarchie d'échelle, puis Monte Carlo et plancher de rentabilité ; assemble EstimationV1 "
                "(gelé), inscrit au registre durable. Photos ou échelle insuffisantes : prix bloqué, "
                "elements_manquants et signal_relance_m2. Sans bloquer : REFERENCE_ECHELLE_ABSENTE. Durée de "
                "main-d'œuvre si le barème porte duree_minutes_par_unite ; prix_recommande si taux_marge est fourni "
                "(jamais codé en dur). Voie non bloquée, clés sœurs d'EstimationV1 : distribution_cout (P50 et P80 "
                "du coût ; PERT si cout_unitaire_mode, sinon uniforme), facteurs_dominants, "
                "scenarios_prix (prudent, normal, agressif : coût x (1 + taux), taux de taux_marge_scenarios ou "
                "de department.yaml ; sans taux : aucun prix, un verdict dit où le déclarer ; sous le minimum "
                "rentable, alerte rouge). Si le poste porte materiaux : besoins_materiaux, "
                "publiés à M6 (facteur_perte absent : signalé, jamais inventé). Rôle employee : coût et prix retirés."
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
                    "taux_marge_scenarios": {
                        "type": ["object", "null"],
                        "description": (
                            "taux de marge des scénarios, texte décimal (ex. \"0.35\"), jamais codé en dur ; un "
                            "scénario absent ou null prend celui de department.yaml, sinon n'a aucun prix"
                        ),
                        "properties": {
                            "prudent": {"type": ["string", "null"]},
                            "normal": {"type": ["string", "null"]},
                            "agressif": {"type": ["string", "null"]},
                        },
                        "additionalProperties": False,
                    },
                },
                "required": ["contrat", "marqueur", "photos", "seuils", "bareme", "quantite", "plancher_rentable"],
                "additionalProperties": False,
            },
            fonction=estimer_projet,
            autonomie=Autonomie.T1,
            # Le core compare le contrat validé avec l'affaire M10 avant l'effet métier.
            portee_contexte="affaire",
            cible_contexte=("contrat", "lead_id"),
            identite_contexte="lead",
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
                    "estimation_source_hash": {
                        "type": "string",
                        "pattern": "^[0-9a-f]{64}$",
                        "description": (
                            "Optionnel : hash_maillon exact de l'estimation M3 retourné par "
                            "m3_estimer_projet.estimation.hash_maillon; le code valide la chaîne et les IDs."
                        ),
                    },
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
            nom="m3_lister_devis",
            description=(
                "Liste de façon paginée les devis des leads actuellement assignés au vendeur humain "
                "authentifié. Inclut tous les statuts courants. La propriété est relue depuis M2; "
                "aucun identifiant de propriétaire n'est accepté. Ne rend que les devis de la page, "
                "sans total global."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "limite": {"type": "integer", "minimum": 1, "maximum": 50, "default": 20},
                    "curseur": {"type": ["string", "null"]},
                },
                "additionalProperties": False,
            },
            fonction=lister_devis_vendeur,
            autonomie=Autonomie.T0,
            roles_appareil=frozenset({_ROLE_VENDEUR}),
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
            nom="m3_evaluer_calibration_cohortes",
            description=(
                "Évalue une cohorte candidate inactive depuis les faits publiés M4 et les liens exacts M3. "
                "Exige une coupure ISO-8601 UTC explicite, rejette ou compte les preuves insuffisantes, exclut "
                "les chantiers traversant la frontière, et ne modifie aucun prix ni barème. Une durée réelle est "
                "du temps écoulé sur site moins pauses, sans déplacement ni heures-personnes."
            ),
            parametres={
                "type": "object",
                "properties": {"coupure_utc": {"type": "string", "format": "date-time", "maxLength": 40}},
                "required": ["coupure_utc"],
                "additionalProperties": False,
            },
            fonction=evaluer_calibration_cohortes,
            autonomie=Autonomie.T0,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m3_auditer_couverture_apprentissage",
            description=(
                "Diagnostic admin appareil actif, sans paramètres : compare les identités des publications "
                "M4 présentes dans le bus aux reçus M3. Compteurs et exemples bornés, aucun payload ni GPS. "
                "Ne vérifie ni le contenu des WCT, ni toutes les complétions terrain, ni la qualité "
                "des mesures; aucun reçu, rejeu, barème ou prix modifié. SQLite uniquement."
            ),
            parametres={"type": "object", "properties": {}, "additionalProperties": False},
            fonction=auditer_couverture_apprentissage, autonomie=Autonomie.T0,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m3_lire_apprentissage_chantier",
            description=(
                "Lecture bornée d'un seul chantier pour rapprocher la trace M3, le temps écoulé M4, "
                "la variance M6 via M8 et la rentabilité M5. Exige une coupure UTC explicite et une "
                "identité admin confirmée; aucun barème, montant ou registre n'est modifié. Le temps "
                "écoulé n'est pas une paie ni des heures-personnes; une association n'établit jamais "
                "une cause. Les faits absents, ambigus, périmés ou d'unité inconnue sont exclus et nommés."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "wct_id": {"type": "string", "minLength": 1, "maxLength": 128},
                    "coupure_utc": {"type": "string", "format": "date-time", "maxLength": 40},
                },
                "required": ["wct_id", "coupure_utc"],
                "additionalProperties": False,
            },
            fonction=lire_apprentissage_chantier,
            autonomie=Autonomie.T0,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m3_proposer_calibration_temps",
            description=(
                "Préenregistre au journal append-only une candidate de durée calculée exclusivement sur le train "
                "d'une cohorte M3/M4, ainsi que la coupure UTC de son futur holdout. Le holdout du rapport initial "
                "est marqué comme déjà vu et ne sert pas à son évaluation ultérieure. Candidate inactive; aucun prix, "
                "coût ou facteur photo n'est modifié."
            ),
            parametres={
                "type": "object", "properties": {
                    "coupure_utc": {"type": "string", "format": "date-time", "maxLength": 40},
                    "coupure_evaluation_utc": {"type": "string", "format": "date-time", "maxLength": 40},
                }, "required": ["coupure_utc", "coupure_evaluation_utc"], "additionalProperties": False,
            },
            fonction=proposer_calibration_temps,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m3_evaluer_candidate_calibration",
            description=(
                "Évalue une candidate préenregistrée sur sa coupure holdout UTC scellée avant collecte, après son "
                "horizon source. Baseline et candidate sont comparées selon la politique déjà scellée; données "
                "insuffisantes ou réutilisées refusent l'admission. La candidate reste inactive."
            ),
            parametres={
                "type": "object", "properties": {
                    "candidate_id": {"type": "string", "minLength": 64, "maxLength": 64},
                }, "required": ["candidate_id"], "additionalProperties": False,
            },
            fonction=evaluer_candidate_calibration,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m3_activer_candidate_calibration",
            description=(
                "Demande la promotion future d'une candidate évaluée comme acceptable. Décision N4 du seul "
                "propriétaire authentifié; l'appel demande une approbation, il n'active pas la candidate. "
                "Les estimations et devis historiques restent inchangés."
            ),
            parametres={
                "type": "object", "properties": {
                    "candidate_id": {"type": "string", "minLength": 64, "maxLength": 64},
                    "active_version_attendue": {"type": ["string", "null"], "maxLength": 64},
                }, "required": ["candidate_id", "active_version_attendue"], "additionalProperties": False,
            },
            fonction=activer_candidate_calibration,
            autonomie=Autonomie.T2,
            niveau=Niveau.N4,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m3_rollback_candidate_calibration",
            description=(
                "Demande le retrait d'une candidate actuellement active. Décision N4 du seul propriétaire; "
                "le journal reste append-only et les estimations historiques ne sont pas réécrites."
            ),
            parametres={
                "type": "object", "properties": {
                    "candidate_id": {"type": "string", "minLength": 64, "maxLength": 64},
                }, "required": ["candidate_id"], "additionalProperties": False,
            },
            fonction=rollback_candidate_calibration,
            autonomie=Autonomie.T2,
            niveau=Niveau.N4,
            roles_appareil=frozenset({"admin"}),
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
                "tirés du devis, de sa source canonique liée, de contexte_revue et des seuils de department.yaml) "
                "avant de "
                "décider. Seul nathan_owner approuve. Approuvée, le devis passe à envoye (une seule fois, un rejeu "
                "ne fait rien) et m3.devis_envoye est publié, sans coût ni marge. La livraison au client n'est pas "
                "ici (M1). Les faits de revue d’une estimation liée sont relus dans son maillon exact, à la file et "
                "à la décision ; contexte_revue ne les remplace pas. Une source historique sans ces faits "
                "est non évaluable ; une source liée absente ou altérée est refusée. Sans source liée, "
                "contexte_revue reste déclaratif. Un fait absent est non évaluable, jamais deviné. "
                "Ne présente jamais le devis comme "
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
