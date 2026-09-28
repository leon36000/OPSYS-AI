"""Orchestrateur d'estimation de M3 (PLAN T2.3, `docs/departements/M3-audit.md` §0/§4 phase 1).

`m3_estimer_projet` (``outils.py``) n'assemblait que 6 des 15 modules du paquet
(``blocage_prix, contrats, hierarchie_echelle, monte_carlo, plancher, qualite_photos``) : jamais
``validation.py`` (S001), jamais ``devis.py`` (S007, ``devis_id`` + contrat gelé ``EstimationV1``),
jamais ``registre.py`` (S008). Ce module compose les 15 modules dans l'ordre déjà prouvé par leurs
tests unitaires respectifs — AUCUNE nouvelle règle métier, seulement le câblage documenté par
``docs/bmad/03-ARCHITECTURE.md`` §1 (qui nomme déjà ce fichier, absent du dépôt jusqu'ici) :

    validation -> qualite_photos -> hierarchie_echelle -> blocage_prix
      -> [monte_carlo -> plancher -> alerte REFERENCE_ECHELLE_ABSENTE -> durée main-d'œuvre]
      -> devis.deriver_devis_id -> registre_cible.ajouter (hash-chaîné) -> devis.assembler_estimation

Chaque étape qui échoue rend ``{"etape": <nom>, "accepte": False, "verdict": <verdict nommé>}`` —
jamais une exception, jamais une valeur inventée. Une fois la décision de blocage obtenue
STRUCTURELLEMENT (qu'elle bloque le prix ou non), l'orchestrateur produit TOUJOURS une estimation
complète (``accepte: True``) : ``prix_bloque`` est un état métier normal du contrat de sortie, pas
un échec technique — exactement le comportement déjà rendu par l'ancien ``estimer_projet`` ad hoc.

Module pur (ADR-0009, même règle que ``devis_durable.py``/``estime_vs_reel.py``) : aucun import
``opsys``, aucune horloge interne, aucun accès réseau, aucun aléa non ensemencé (Monte Carlo reste
seedé par ``graine``, jamais par une source d'ambiance). ``registre_cible`` est un
``registre.Registre`` DÉJÀ CONSTRUIT, reçu en paramètre (protocole objet, cf. ``registre.py``) :
une instance en mémoire dans les tests unitaires, ``outils.registre_production()`` (durable) en
production — c'est ``outils.py``, seul, qui choisit ce support, jamais ce module.

``niveau_confiance`` — DIVERGENCE MESURÉE, PAS RÉPARÉE ICI (à consigner) : le contrat gelé rendu
par ``devis.assembler_estimation``/le catalogue de ``registre.py`` valide ``niveau_confiance``
comme un NOMBRE fini (``devis._est_nombre_fini``, éprouvé par 100+ tests verts de
``test_devis.py``/``test_registre.py`` avec la fixture ``0.9``), alors que
``docs/bmad/03-ARCHITECTURE.md``/le PRD le documentent comme la chaîne ``NiveauConfiance``
(REFERENCE_ECHELLE|MULTI_VUES|MONO_VUE_BORNES_LARGES|INDETERMINE). Réparer cette divergence
toucherait deux modules mutés indépendamment (``devis.py``, `registre.py`) et leurs fixtures dans
6 fichiers de tests hors du périmètre de cette tranche — un travail de correction délibéré, pas un
effet de bord du câblage. Ce module respecte donc le contrat RÉELLEMENT VALIDÉ par le code
existant : ``niveau_confiance`` porte le NIVEAU STATISTIQUE du Monte Carlo (0.90/0.95/0.99, cf.
``NIVEAUX_STATISTIQUES_PAR_CONFIANCE`` — le nominal ``blocage_prix.NIVEAU_CONFIANCE_NOMINAL`` sur
la voie bloquée, exactement la convention déjà appliquée par ``blocage_prix.decider_blocage`` au
champ ``intervalle_confiance.niveau`` dans la même situation). La classification HIÉRARCHIQUE
(chaîne ``REFERENCE_ECHELLE``/``MULTI_VUES``/``MONO_VUE_BORNES_LARGES``/``INDETERMINE``), tout
aussi utile, est rendue à part par l'orchestrateur sous la clé ``niveau_confiance_hierarchie`` —
jamais mêlée au champ gelé pour ne pas lui faire porter deux sens incompatibles.

Durée de main-d'œuvre (PLAN T2.3, relevé T1.2-f : « M3 n'a aucune durée estimée de main-d'œuvre
(``duree_estimee_minutes``) ») — FORMULE :

    duree_estimee_minutes = quantite × duree_minutes_par_unite

``duree_minutes_par_unite`` est un TAUX FOURNI PAR L'APPELANT, jamais codé en dur (même discipline
que ``taux_marge``/``plancher_rentable`` ailleurs dans ce département) : une clé OPTIONNELLE du
poste du barème (``bareme["postes"][type_travaux]["duree_minutes_par_unite"]``), à la place d'un
nouveau paramètre séparé — cohérent avec ``cout_unitaire_min``/``cout_unitaire_max`` déjà logés au
même niveau. ABSENTE : aucune durée n'est calculée (``duree_estimee_minutes`` reste ``None``, RIEN
n'est écrit au registre) — un barème existant sans cette clé continue de produire une estimation de
PRIX inchangée ; c'est ``estime_vs_reel.py`` (T1.2-d, déjà déployé) qui rapportera fidèlement
``REJ-ECART-ESTIMATION-ORIGINE-ABSENTE`` le jour où quelqu'un comparera estimé et réel pour CE
devis — jamais un chiffre inventé pour combler l'absence. PRÉSENTE mais invalide (non numérique,
non finie, non strictement positive) : un verdict NOMMÉ (``REJ-ECART-DUREE-ESTIMEE-INVALIDE``,
catalogue existant de T1.2-d, même code que la comparaison estimé-vs-réel réutilise pour la même
notion) — un TAUX fourni de travers est signalé, jamais silencieusement ignoré. Calculée
SEULEMENT sur la voie NON bloquée (même quantité que le Monte Carlo réellement exécuté) : une durée
sans prix associé n'aurait pas de socle. Déposée comme clé SUPPLÉMENTAIRE de la charge du registre
"principal" — jamais dans le contrat gelé ``EstimationV1`` (``contrats.CHAMPS_ESTIMATION_V1``,
12 clés, INCHANGÉ) : ``registre.py`` accepte une charge PLUS RICHE que ses six clés requises
(``_CLES_CHARGE_REQUISES.issubset(charge)``, jamais un ensemble fermé), et
``estime_vs_reel._estimation_origine`` la retrouve par ``devis_id`` sans qu'aucun contrat gelé
n'ait à s'ouvrir. Le registre n'accepte que des types JSON canoniques
(``registre._normaliser`` : aucun ``Decimal``) : la valeur est donc déposée en TEXTE décimal,
jamais en ``Decimal`` ni en ``float`` (mêmes arrondis Decimal-depuis-texte que le reste du
département, jamais l'arrondi binaire implicite d'un float).

``REFERENCE_ECHELLE_ABSENTE`` (alerte NON bloquante, `docs/departements/M3-audit.md` §0/§4-3) :
ajoutée aux verdicts CANDIDATS de ``devis.assembler_estimation`` quand ``niveau_confiance``
(hiérarchie) vaut ``MULTI_VUES`` ou ``MONO_VUE_BORNES_LARGES`` ET qu'aucune photo ne porte de
référence d'échelle CERTIFIÉE (``motifs["photos_avec_reference"] == 0`` — le compteur QUALIFIANT
de ``hierarchie_echelle._compter_motifs``, jamais recalculé ici). Jamais sur ``REFERENCE_ECHELLE``
(une référence existe, par construction de la hiérarchie) ni sur la voie bloquée (la qualité
insuffisante ou l'indétermination priment déjà via ``_PRIORITE_VERDICTS`` de ``devis.py`` — l'ajout
au tuple des candidats ne change alors rien puisque ce verdict n'y figure jamais dans ce cas).
L'assembleur choisit seul, par priorité déjà éprouvée (``devis._PRIORITE_VERDICTS``), le verdict le
plus fort parmi les candidats ; ``alerte_plancher``/``prix_bloque`` restent des booléens EXACTS,
indépendants du verdict affiché en tête.

Signal de relance M2 (PLAN T2.3, ``signaux.py``, ``docs/departements/M3-audit.md`` §2.3/§4 point 4
— « le signal ... est écrit et testé mais ... jamais appelé ») : câblé UNIQUEMENT quand
``decision["verdict_estimation"] == QUALITE_ENTREE_INSUFFISANTE`` — jamais sur la voie INDETERMINE
seule, dont ``qualification["elements_manquants"]`` peut être vide (photos structurellement
acceptables, classification hiérarchique quand même indéterminée) : ``signaux.
construire_signal_relance`` refuse fail-closed une liste vide (``REJ-SIGNAL-INVALIDE``), et cette
voie ne le garantit pas. La voie QUALITE_ENTREE_INSUFFISANTE, elle, le garantit TOUJOURS
(``qualite_photos.qualifier_photos`` ne retourne ce verdict que lorsque ``elements_manquants`` est
déjà non vide) : ``lead_id``/``devis_id`` sont eux aussi déjà validés à ce point de l'orchestrateur,
donc cet appel ne peut jamais échouer en pratique — le verdict éventuel reste géré (jamais une
exception qui s'échappe), fidèle au reste du fichier. Rendu sous la clé ``signal_relance_m2``,
``None`` quand aucun signal n'est dû — jamais un effet de bord inventé (l'ORCHESTRATEUR ne publie
rien lui-même ; c'est un futur consommateur de M2, hors périmètre de cette tranche, qui agira sur ce
signal rendu).

Prix recommandé (PLAN T2.3, reste de T2.3-b — « séparer coût et prix ... le mot "prix" de
l'interface désigne en réalité un coût », ``docs/departements/M3-audit.md`` §2.1) : le barème
(``BaremeCouts``) est un barème de COÛT, et ``intervalle_confiance`` (dans ``EstimationV1``, champ
GELÉ, INCHANGÉ) reste donc un intervalle de coût. ``prix_recommande`` est une clé SUPPLÉMENTAIRE de
la réponse de l'orchestrateur — jamais dans ``EstimationV1`` (même choix que
``duree_estimee_minutes`` ci-dessus : un contrat gelé ne se modifie pas en place, P5) — dérivée de
``intervalle_confiance`` par un ``taux_marge`` FOURNI PAR L'APPELANT (jamais codé en dur, même
discipline que ``plancher_rentable``/``bareme``), en réutilisant TELLES QUELLES les fonctions de
prix de ``devis_durable.py`` (``texte_vers_taux_marge``, ``prix_depuis_cout`` — même formule,
même arrondi ``ROUND_HALF_UP`` au cent, jamais dupliquée). Calculé SEULEMENT sur la voie NON
bloquée (un prix sans coût produit n'aurait pas de socle, même raisonnement que la durée de
main-d'œuvre). Trois issues, jamais une quatrième inventée :
  - ``taux_marge`` ABSENT (``None``) : ``prix_recommande`` reste ``None`` — PAS une erreur, le
    coût seul reste exploitable. Le fait est noté dans ``elements_manquants`` (qui vaut alors
    cette seule note, la voie n'étant pas bloquée par les photos) pour que l'appelant sache
    explicitement pourquoi aucun prix n'a été calculé.
  - ``taux_marge`` PRÉSENT mais invalide (texte non décimal, ``<= -1``) : un verdict NOMMÉ
    (``REJ-DEVIS-TAUX-MARGE-INVALIDE``, catalogue déjà existant de ``devis_durable.py`` — jamais
    dupliqué), l'orchestrateur entier rejette (étape ``prix_recommande``) — même discipline que
    ``plancher_rentable``/``duree_minutes_par_unite`` invalides ailleurs dans ce fichier : une
    donnée fournie DE TRAVERS est signalée, jamais silencieusement ignorée.
  - ``taux_marge`` valide : ``prix_recommande = {borne_basse, borne_haute}``, chaque borne dérivée
    de la borne de COÛT correspondante par ``devis_durable.prix_depuis_cout``.
"""

from __future__ import annotations

import hashlib
import json
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from . import (
    blocage_prix,
    contrats,
    devis,
    devis_durable,
    hierarchie_echelle,
    monte_carlo,
    plancher,
    qualite_photos,
    signaux,
    validation,
    verdicts,
)

__all__ = [
    "NIVEAUX_STATISTIQUES_PAR_CONFIANCE",
    "arrondir_au_cent",
    "graine_stable",
    "orchestrer_estimation",
]

# Niveau statistique (couverture du Monte Carlo — PRD §5 : "niveau : float, ex. 0.90 pour 90 %,
# configurable par l'appelant") retenu par rang de FIABILITÉ DE MESURE dans la hiérarchie ratifiée
# (hierarchie_echelle.NIVEAUX_CONFIANCE, ordre épinglé). Politique ÉNONCÉE, pas une mesure —
# REFERENCE_ECHELLE (rang 0, objet de dimensions CERTIFIÉES visible dans le cadre) reprend SANS
# changement le niveau nominal déclaré par l'architecture (blocage_prix.NIVEAU_CONFIANCE_NOMINAL =
# 0.90). Chaque cran de MOINS de fiabilité de mesure élève la couverture statistique demandée :
# MULTI_VUES ("précision moindre") puis MONO_VUE_BORNES_LARGES ("bornes LARGES" dès son nom).
# INDETERMINE n'atteint jamais cette table : le prix y est bloqué en amont par
# blocage_prix.decider_blocage, avant tout calcul d'intervalle. (Reprise telle quelle de l'ancien
# outils.py::estimer_projet — aucune règle nouvelle, seul le fichier hôte change.)
NIVEAUX_STATISTIQUES_PAR_CONFIANCE = {
    hierarchie_echelle.NIVEAUX_CONFIANCE[0]: blocage_prix.NIVEAU_CONFIANCE_NOMINAL,  # REFERENCE_ECHELLE : 0.90
    hierarchie_echelle.NIVEAUX_CONFIANCE[1]: 0.95,  # MULTI_VUES
    hierarchie_echelle.NIVEAUX_CONFIANCE[2]: 0.99,  # MONO_VUE_BORNES_LARGES
}

# Niveaux hiérarchiques où l'absence de référence d'échelle est SIGNALÉE (non bloquante) : jamais
# REFERENCE_ECHELLE (une référence existe déjà, par construction), jamais sur la voie bloquée.
_NIVEAUX_SANS_REFERENCE_ALERTABLES = (
    hierarchie_echelle.NIVEAUX_CONFIANCE[1],  # MULTI_VUES
    hierarchie_echelle.NIVEAUX_CONFIANCE[2],  # MONO_VUE_BORNES_LARGES
)

_CENT = Decimal("0.01")


def arrondir_au_cent(valeur: float) -> float:
    """Arrondit un montant CAD au cent le plus proche via Decimal.

    ``Decimal(str(valeur))`` (jamais ``Decimal(valeur)``) : convertir depuis la représentation
    DÉCIMALE du float évite de figer les artefacts de son codage binaire. Le résultat reste un
    float — le contrat gelé EstimationV1 (PRD §5) type ``borne_basse``/``borne_haute`` en
    ``float`` — mais chaque cent est déterminé par un calcul décimal exact, jamais par l'arrondi
    binaire implicite du float. (Reprise inchangée de l'ancien ``outils.py::arrondir_au_cent``.)
    """
    return float(Decimal(str(valeur)).quantize(_CENT, rounding=ROUND_HALF_UP))


def graine_stable(bareme: dict[str, Any], type_travaux: str, quantite: float) -> int:
    """Graine reproductible dérivée des entrées : même demande, même intervalle. (Reprise
    inchangée de l'ancien ``outils.py::graine_stable``.)"""
    empreinte = json.dumps([bareme.get("version"), type_travaux, quantite], sort_keys=True)
    return int(hashlib.sha256(empreinte.encode("utf-8")).hexdigest()[:8], 16)


def _duree_estimee_minutes_texte(
    quantite: Any, bareme: dict[str, Any], type_travaux: str
) -> tuple[str | None, dict | None]:
    """``duree_estimee_minutes = quantite x duree_minutes_par_unite`` (Decimal, texte) — voir la
    docstring du module pour le choix de dépôt (charge du registre, jamais EstimationV1) et pour
    la distinction ABSENTE (silencieux, ``(None, None)``) contre INVALIDE (verdict nommé)."""
    poste = bareme.get("postes", {}).get(type_travaux) if isinstance(bareme, dict) else None
    if not isinstance(poste, dict) or "duree_minutes_par_unite" not in poste:
        return None, None  # non fournie : aucune durée calculée, jamais une durée inventée

    brute = poste["duree_minutes_par_unite"]
    if isinstance(brute, bool) or not isinstance(brute, (int, float, Decimal)):
        return None, verdicts.construire_verdict(
            "REJ-ECART-DUREE-ESTIMEE-INVALIDE",
            detail=f"duree_minutes_par_unite doit être numérique (reçu {type(brute).__name__})",
        )
    try:
        taux_decimal = brute if isinstance(brute, Decimal) else Decimal(str(brute))
        quantite_decimale = Decimal(str(quantite))
    except InvalidOperation:
        return None, verdicts.construire_verdict(
            "REJ-ECART-DUREE-ESTIMEE-INVALIDE",
            detail="duree_minutes_par_unite ou quantite non convertible en Decimal",
        )
    if not taux_decimal.is_finite() or taux_decimal <= 0:
        return None, verdicts.construire_verdict(
            "REJ-ECART-DUREE-ESTIMEE-INVALIDE",
            detail=f"duree_minutes_par_unite doit être strictement positive et finie (reçu {brute!r})",
        )
    return str(quantite_decimale * taux_decimal), None


def _prix_recommande_depuis_intervalle(
    intervalle_confiance: dict[str, Any], taux_marge: str | None
) -> tuple[dict[str, float] | None, dict | None]:
    """Dérive ``prix_recommande`` (``{borne_basse, borne_haute}``) depuis l'intervalle de COÛT
    Monte Carlo et un ``taux_marge`` FOURNI — voir la docstring du module pour la justification
    complète. Réutilise ``devis_durable.texte_vers_taux_marge``/``prix_depuis_cout`` telles
    quelles, jamais une seconde copie de la formule de prix.

    ``taux_marge is None`` : ``(None, None)`` — absent n'est PAS une erreur ici (à la différence de
    ``creer_devis``, où le taux est obligatoire) : l'appelant (ci-dessous) note le fait dans
    ``elements_manquants``, jamais un rejet. ``taux_marge`` invalide : ``(None, verdict)``, un rejet
    NOMMÉ qui fait échouer l'orchestrateur entier — même discipline que ``plancher_rentable``/
    ``duree_minutes_par_unite``."""
    if taux_marge is None:
        return None, None
    taux, verdict = devis_durable.texte_vers_taux_marge(taux_marge)
    if verdict is not None:
        return None, verdict
    borne_basse_cout = Decimal(str(intervalle_confiance["borne_basse"]))
    borne_haute_cout = Decimal(str(intervalle_confiance["borne_haute"]))
    return {
        "borne_basse": float(devis_durable.prix_depuis_cout(borne_basse_cout, taux)),
        "borne_haute": float(devis_durable.prix_depuis_cout(borne_haute_cout, taux)),
    }, None


def orchestrer_estimation(
    contrat: dict[str, Any],
    marqueur: dict[str, Any],
    photos: list[dict[str, Any]],
    seuils: dict[str, Any],
    bareme: dict[str, Any],
    quantite: float,
    plancher_rentable: float,
    registre_cible: Any,
    graine: int | None = None,
    taux_marge: str | None = None,
) -> dict[str, Any]:
    """Compose la chaîne complète d'estimation M3 — voir la docstring du module pour l'ordre et
    les décisions de conception. Chaque étape qui échoue rend un verdict NOMMÉ qui dit quoi
    demander ; jamais une exception, jamais une valeur inventée."""
    accuse, verdict = validation.valider_entrees(contrat, marqueur, photos)
    if verdict is not None:
        return {"etape": "validation", "accepte": False, "verdict": verdict}

    lead_id = accuse["lead_id"]
    # Lead v2 : `service` (taxonomie du socle, validé par `valider_entrees`) ; lead v1 : `type_travaux`.
    # Dans les deux cas c'est la clé du poste du barème : une clé absente du barème BLOQUE l'estimation
    # (« barème du service X absent : à fournir »), jamais un repli sur un autre poste.
    est_lead_v2 = "service" in accuse
    type_travaux = accuse["service"] if est_lead_v2 else accuse["type_travaux"]
    empreinte_marqueur_m2 = accuse["empreinte_marqueur_m2"]

    qualification, verdict = qualite_photos.qualifier_photos(photos, seuils)
    if verdict is not None:
        return {"etape": "qualite_photos", "accepte": False, "verdict": verdict}
    elements_manquants = qualification["elements_manquants"]

    niveau_hierarchie, motifs = hierarchie_echelle.classifier_niveau_confiance(photos, seuils)
    if niveau_hierarchie is None:
        return {"etape": "niveau_confiance", "accepte": False, "verdict": motifs}

    decision, verdict = blocage_prix.decider_blocage(niveau_hierarchie, qualification)
    if verdict is not None:
        return {"etape": "blocage", "accepte": False, "verdict": verdict}

    try:
        devis_id = devis.deriver_devis_id(lead_id, empreinte_marqueur_m2)
    except ValueError as exc:
        return {
            "etape": "devis_id",
            "accepte": False,
            "verdict": verdicts.construire_verdict("REJ-CONTRAT-INVALIDE", detail=str(exc)),
        }

    prix_bloque = decision["prix_bloque"]
    verdicts_candidats = [decision["verdict_estimation"]]
    intervalle_confiance = decision["intervalle_confiance"]
    raison_blocage = decision["raison_blocage"]
    bareme_version: str | None = None
    alerte_plancher = False
    duree_estimee_minutes: str | None = None
    prix_recommande: dict[str, float] | None = None
    elements_manquants_prix: list[str] = []
    signal_relance_m2: dict[str, Any] | None = None
    niveau_confiance_numerique = NIVEAUX_STATISTIQUES_PAR_CONFIANCE.get(
        niveau_hierarchie, blocage_prix.NIVEAU_CONFIANCE_NOMINAL
    )
    graine_effective = graine if graine is not None else graine_stable(bareme, type_travaux, quantite)

    # Signal de relance M2 (voir la docstring du module) : UNIQUEMENT sur la qualité photo
    # insuffisante, jamais sur INDETERMINE seul (elements_manquants y serait parfois vide).
    if decision["verdict_estimation"] == contrats.VERDICT_QUALITE_ENTREE_INSUFFISANTE:
        signal_relance_m2, verdict_signal = signaux.construire_signal_relance(
            lead_id, devis_id, elements_manquants
        )
        if verdict_signal is not None:
            return {"etape": "signal_relance", "accepte": False, "verdict": verdict_signal}

    if not prix_bloque:
        niveau_statistique = NIVEAUX_STATISTIQUES_PAR_CONFIANCE[niveau_hierarchie]
        intervalle, verdict = monte_carlo.simuler_intervalle(
            bareme, type_travaux, quantite, graine_effective, niveau_statistique,
            services=(type_travaux,) if est_lead_v2 else (),
        )
        if verdict is not None:
            return {"etape": "intervalle", "accepte": False, "verdict": verdict}
        intervalle_confiance = {
            "borne_basse": arrondir_au_cent(intervalle["borne_basse"]),
            "borne_haute": arrondir_au_cent(intervalle["borne_haute"]),
            "niveau": intervalle["niveau"],
        }
        bareme_version = bareme.get("version") if isinstance(bareme, dict) else None

        constat, verdict = plancher.confronter_au_plancher(intervalle_confiance, plancher_rentable)
        if verdict is not None:
            return {"etape": "plancher", "accepte": False, "verdict": verdict}
        alerte_plancher = constat["alerte_plancher"]
        verdicts_candidats.append(constat["verdict_estimation"])

        if (
            niveau_hierarchie in _NIVEAUX_SANS_REFERENCE_ALERTABLES
            and motifs["photos_avec_reference"] == 0
        ):
            verdicts_candidats.append(contrats.VERDICT_REFERENCE_ECHELLE_ABSENTE)

        duree_estimee_minutes, verdict = _duree_estimee_minutes_texte(quantite, bareme, type_travaux)
        if verdict is not None:
            return {"etape": "duree_main_doeuvre", "accepte": False, "verdict": verdict}

        prix_recommande, verdict = _prix_recommande_depuis_intervalle(intervalle_confiance, taux_marge)
        if verdict is not None:
            return {"etape": "prix_recommande", "accepte": False, "verdict": verdict}
        if prix_recommande is None:
            # taux_marge ABSENT (pas invalide : ce cas a déjà rejeté ci-dessus) : pas une erreur,
            # mais l'appelant doit savoir explicitement pourquoi aucun prix n'a été calculé.
            elements_manquants_prix.append(
                "taux_marge non fourni : aucun prix recommandé calculé (coût seulement disponible)"
            )

    charge: dict[str, Any] = {
        "devis_id": devis_id,
        "lead_id": lead_id,
        "empreinte_marqueur_m2": empreinte_marqueur_m2,
        "niveau_confiance": niveau_confiance_numerique,
        "bareme_version": bareme_version,
        "graine_monte_carlo": graine_effective,
    }
    if duree_estimee_minutes is not None:
        charge["duree_estimee_minutes"] = duree_estimee_minutes

    maillon, verdict = registre_cible.ajouter(charge)
    if verdict is not None:
        return {"etape": "registre", "accepte": False, "verdict": verdict}

    estimation, verdict = devis.assembler_estimation(
        lead_id=lead_id,
        empreinte_marqueur_m2=empreinte_marqueur_m2,
        niveau_confiance=niveau_confiance_numerique,
        verdicts_estimation=tuple(verdicts_candidats),
        bareme_version=bareme_version,
        prix_bloque=prix_bloque,
        intervalle_confiance=intervalle_confiance,
        alerte_plancher=alerte_plancher,
        raison_blocage=raison_blocage,
        graine_monte_carlo=graine_effective,
        hash_maillon=maillon["hash_maillon"],
    )
    if verdict is not None:
        return {"etape": "assemblage", "accepte": False, "verdict": verdict}

    return {
        "etape": "complet",
        "accepte": True,
        "estimation": estimation,
        "niveau_confiance_hierarchie": niveau_hierarchie,
        "motifs_confiance": motifs,
        "duree_estimee_minutes": duree_estimee_minutes,
        # SOUL.md : « quand le prix est bloqué, tu expliques simplement au client ce qui manque »
        # — liste EXPLICITE (jamais seulement la phrase composée de raison_blocage) sur la voie
        # bloquée (reprise directe de qualite_photos.qualifier_photos, jamais recalculée ici) ;
        # sur la voie NON bloquée, ne porte que la note taux_marge absent le cas échéant (jamais
        # les deux à la fois : les deux causes de blocage/incomplétude sont mutuellement
        # exclusives par construction — voir _prix_recommande_depuis_intervalle ci-dessus).
        "elements_manquants": elements_manquants if prix_bloque else elements_manquants_prix,
        # Séparation coût/prix (PLAN T2.3, reste de T2.3-b) : dérivé de intervalle_confiance par
        # taux_marge, jamais dans EstimationV1 (champ gelé, inchangé). None sur la voie bloquée ou
        # quand taux_marge est absent — voir la docstring du module.
        "prix_recommande": prix_recommande,
        # Signal de relance M2 (signaux.py, DEMANDE_ENTREES_VISUELLES) : None sauf sur la qualité
        # photo insuffisante — voir la docstring du module pour la justification du câblage exact.
        "signal_relance_m2": signal_relance_m2,
    }
