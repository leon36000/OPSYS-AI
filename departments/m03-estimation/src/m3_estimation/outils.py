"""Capacités d'agent du département M3 Estimation.

Chaque outil enveloppe une fonction métier déterministe existante : aucune n'est réécrite.
`m3_estimer_projet` compose la chaîne complète en un seul appel, ce qui évite à l'agent
cinq allers-retours (économie de tokens) et garantit l'ordre des contrôles. Le prix n'est
jamais calculé quand il doit être bloqué.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from opsys import contexte, evenements, identite, stockage
from opsys.outils import Autonomie, Outil, depuis_couple

from . import (
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
    soumission,
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
        "{version, unite, postes: {type_travaux: {cout_unitaire_min, cout_unitaire_max, "
        "duree_minutes_par_unite (optionnel — minutes de main-d'œuvre par unité de quantite ; "
        "absent : aucune durée n'est calculée)}}}"
    ),
}
_TYPE_TRAVAUX = {"type": "string", "enum": list(contrats.TYPES_TRAVAUX)}
_CONTRAT = {
    "type": "object",
    "description": "LeadQualifie émis par M2 (contrats.CHAMPS_CONTRAT_GELE), sept clés gelées.",
    "properties": {
        "lead_id": {"type": "string"},
        "conversation_id": {"type": "string"},
        "type_travaux": _TYPE_TRAVAUX,
        "ville": {"type": "string"},
        "canal": {"type": "string"},
        "contact": {"type": "object"},
        "urgence_declaree": {"type": "boolean"},
    },
    "required": list(contrats.CHAMPS_CONTRAT_GELE),
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

    Rend toujours `{"accepte": True, "role": <vue>}` ou `{"accepte": False, "verdict": <verdict>}`
    — jamais une exception."""
    identite_dispositif = contexte.identite_appelante()
    if identite_dispositif is None:
        return {"accepte": True, "role": role_demande if role_demande is not None else "interne"}

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
    if role_demande is None:
        return {"accepte": True, "role": vue_autorisee}
    if vue_autorisee == "interne" or role_demande == vue_autorisee:
        return {"accepte": True, "role": role_demande}
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
    intervalle, rejet = monte_carlo.simuler_intervalle(bareme, type_travaux, quantite, graine, niveau)
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
    comportement inchangé (PLAN T2.3-b)."""
    vue = _vue_projection_effective(None)
    if not vue["accepte"]:
        return {"etape": "identite_appareil", "accepte": False, "verdict": vue["verdict"]}
    resultat = estimation.orchestrer_estimation(
        contrat, marqueur, photos, seuils, bareme, quantite, plancher_rentable,
        registre_production(), graine, taux_marge,
    )
    if vue["role"] == "employe" and resultat.get("accepte") is True:
        return _projeter_estimation_employe(resultat)
    return resultat


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
    `devis_id` existe."""
    vue = _vue_projection_effective(role)
    if not vue["accepte"]:
        return {"accepte": False, "verdict": vue["verdict"]}
    devis, verdict = devis_durable.lire_devis(registre_devis_production(), devis_id)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
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
    evenements.publier(
        "m3.devis_accepte",
        "m03-estimation",
        devis_durable.charge_evenement_devis_accepte(devis),
        evenement_id=f"m3-devis-accepte-{devis_id}",
    )
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


def generer_soumission_brouillon(devis_id: str) -> dict[str, Any]:
    """Lit le devis durable par `devis_id` et rend un brouillon HTML lisible pour le client
    (PLAN T2.3, `soumission.py`) — jamais un envoi (SOUL.md, T1.3 : l'envoi reste derrière les
    approbations du socle)."""
    devis, verdict = devis_durable.lire_devis(registre_devis_production(), devis_id)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
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
                "Estime un projet de bout en bout (PLAN T2.3) : compose validation du contrat "
                "LeadQualifie et du marqueur de readiness M2, qualité des photos, hiérarchie "
                "d'échelle, blocage anti-précision-inventée, Monte Carlo, plancher de rentabilité "
                "et assemble le contrat gelé EstimationV1 (devis_id stable), inscrit au registre "
                "durable des estimations. Bloque le prix si les photos ou la référence d'échelle "
                "sont insuffisantes et liste alors les éléments manquants ; émet signal_relance_m2 "
                "(DEMANDE_ENTREES_VISUELLES) dans ce cas. Signale sans bloquer l'absence de "
                "référence d'échelle en confiance MULTI_VUES/MONO_VUE_BORNES_LARGES "
                "(REFERENCE_ECHELLE_ABSENTE). Calcule la durée de main-d'œuvre si le barème porte "
                "duree_minutes_par_unite. Si taux_marge est fourni (texte décimal, ex. \"0.35\" — "
                "jamais codé en dur), calcule aussi prix_recommande depuis le coût ; absent, aucun "
                "prix n'est calculé et elements_manquants le dit. Pendant un appel d'appareil "
                "authentifié en rôle employee, coût et prix sont toujours retirés de la réponse."
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
                "historique)."
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
                "Génère un brouillon de soumission HTML lisible pour le client depuis un devis "
                "durable existant (description, quantités, prix par ligne, prix total — jamais "
                "coût ni marge). Brouillon seulement : aucun envoi, aucune approbation requise "
                "pour le générer (l'envoi reste derrière les approbations du socle, T1.3)."
            ),
            parametres={
                "type": "object",
                "properties": {"devis_id": {"type": "string"}},
                "required": ["devis_id"],
                "additionalProperties": False,
            },
            fonction=generer_soumission_brouillon,
            autonomie=Autonomie.T0,
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
