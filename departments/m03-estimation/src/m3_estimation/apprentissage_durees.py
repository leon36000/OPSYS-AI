"""Apprentissage des durées SUR SITE de M3 : estimateur robuste, gouvernance par règle, performance d'équipe agrégée.

CE QUE C'EST. La boucle fermée « le terrain corrige l'estimation » : les temps certifiés par l'app mobile (WCT de M4,
durée écoulée sur site moins pauses, SANS déplacement) deviennent des observations normalisées ; par type de travaux
(service + unité de quantité), un taux appris en minutes par unité est estimé de façon robuste ; il devient une
CANDIDATE versionnée, qui ne s'applique que si une règle déclarée le permet (voir « Gouvernance »). Ce module est PUR :
stdlib seulement, aucun import ``opsys``, aucune horloge (``maintenant_utc`` est injecté), aucun aléa non ensemencé
(le bootstrap est ensemencé par le contenu), aucun réseau, aucun registre. Le journal append-only vit dans
``apprentissage_journal.py`` et l'adaptateur (lecture des registres, mode, approbations) dans
``outils_apprentissage_durees.py``.

CE QUE C'EST PAS.
* Le déplacement n'entre JAMAIS ici. Une observation dont la sémantique n'est pas exactement
  ``duree_ecoulee_intervention`` (temps écoulé sur site, pauses et déplacement exclus), dont l'unité n'est pas la
  minute ou qui déclare inclure du déplacement est EXCLUE et comptée. Le déplacement reste calculé à part (distances,
  M4) et n'est jamais ajouté ni retranché au taux appris.
* Ni prix, ni coût, ni marge : seule la durée de main-d'œuvre sur site change. Le prix et l'envoi au client restent
  décidés par les humains comme avant.
* Aucune note de personne. Les agrégats d'équipe portent sur un COUPLE (équipe, type de travaux) pour une équipe
  déclarée d'au moins deux membres (le filtre est appliqué par M4, qui détient le profil) ; une personne seule ou une
  observation sans équipe attribuable n'entre dans aucun agrégat.

ESTIMATEUR. Par observation, le taux observé est ``durée réelle / quantité`` (minutes par unité) : il ne dépend ni de
l'estimation d'origine ni d'une calibration déjà appliquée, donc l'apprentissage ne peut pas se mordre la queue.
Cohorte = (type de service, unité de quantité). Étapes : (1) exclusion des observations non certifiées, mal formées,
futures ou en conflit de rejeu ; (2) exclusion des aberrantes (écart à la médiane > k x échelle robuste, l'échelle
étant ``max(1,4826 x MAD, plancher relatif x médiane)`` pour ne pas rejeter tout écart quand les données sont
identiques) ; (3) médiane PONDÉRÉE par l'âge (poids ``2^(-âge/demi-vie)``) ; (4) intervalle par bootstrap de cette
médiane, ensemencé par le contenu (même entrée, même sortie) ; (5) détection de dérive : la médiane des ``fenetre``
derniers chantiers contre celle des précédents ET contre le taux en vigueur ; si dérive, le taux est ré-estimé sur la
seule fenêtre récente (le régime change, l'ancien historique ne dilue pas le nouveau) et la candidate retient
``regime_depuis_utc``.

GOUVERNANCE (décision d'architecte ; seuils et bornes sont des DONNÉES déclarées dans
``department.yaml/configuration/apprentissage_durees``, jamais des constantes de formule). Sans politique complète,
aucune candidate n'est évaluée : le verdict dit quoi déclarer (fail-closed). Décision d'une candidate :

* ``insuffisante`` : moins de ``echantillon_minimum`` chantiers retenus ;
* ``stable`` : le taux en vigueur (appliqué, sinon barème) est dans l'intervalle, ou l'écart est sous
  ``variation_minimale_pct`` : rien à changer ;
* ``refusee_hors_bornes`` : le facteur (taux appris / taux du barème) sort de [``facteur_min``, ``facteur_max``] ;
  même un humain ne l'approuve pas par ce chemin (une telle valeur dit surtout qu'une donnée est fausse) ;
* ``approbation_requise`` : dérive détectée, ou variation supérieure au palier ``variation_auto_max_pct`` : attend une
  personne (N3) ;
* ``auto_applicable`` : tout le reste, c.-à-d. petit ajustement dans les bornes, échantillon suffisant, intervalle qui
  EXCLUT le taux en vigueur, aucune dérive. Il ne s'applique, hors mode ombre, qu'au brouillon d'estimation.

Les nombres sont des ``Decimal`` (contexte local de 40 chiffres) et sortent en texte. Aucune valeur d'affaires n'est
inventée ici : les seuils viennent de la politique, les observations des registres.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections import defaultdict
from datetime import UTC, datetime
from decimal import (
    ROUND_HALF_EVEN,
    Context,
    Decimal,
    DecimalException,
    DivisionByZero,
    FloatOperation,
    InvalidOperation,
    Overflow,
    localcontext,
)
from typing import Any

__all__ = [
    "CHAMPS_POLITIQUE",
    "SEMANTIQUE_SUR_SITE",
    "VERSION_POLITIQUE",
    "calculer_cohorte",
    "controler_application",
    "decisions",
    "empreinte",
    "instant_utc",
    "lire_politique",
    "performance_equipes",
    "preparer_observations",
    "saison_de",
]

VERSION_POLITIQUE = "m3-apprentissage-durees/1"
SEMANTIQUE_SUR_SITE = "duree_ecoulee_intervention"
STATUT_CERTIFIE = "completed_verified"
# Décisions d'une candidate : une classification de CE module (jamais une mesure indéterminée), donc privée et
# exposée par ``decisions()`` - ``conformite.py`` réserve l'échappatoire INDETERMINE aux énumérés publics de domaine.
_DECISIONS = (
    "insuffisante", "stable", "refusee_hors_bornes", "approbation_requise", "auto_applicable",
)
COMPLEXITE_INCONNUE = "inconnue"
CHAMPS_POLITIQUE = (
    "version", "echantillon_minimum", "echantillon_minimum_equipe", "demi_vie_jours", "aberrantes_k",
    "echelle_minimale_relative", "niveau_confiance", "replications", "variation_minimale_pct",
    "variation_auto_max_pct", "facteur_min", "facteur_max", "derive_fenetre", "derive_seuil_pct", "complexites",
)

_CONTEXTE = Context(prec=40, rounding=ROUND_HALF_EVEN, Emin=-999, Emax=999)
for _signal in _CONTEXTE.traps:
    _CONTEXTE.traps[_signal] = _signal in {InvalidOperation, DivisionByZero, Overflow, FloatOperation}

_QUANTUM = Decimal("0.0001")
_DEUX = Decimal(2)
_CENT = Decimal(100)
_MAD_VERS_SIGMA = Decimal("1.4826")
_MAX_LIGNES = 2000
_MAX_BOOTSTRAP_LIGNES = 400
_DECIMAL_TEXTE = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?\Z")
_CODE = re.compile(r"[a-z][a-z0-9_]{1,29}\Z")
_TEXTE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}\Z")
_SAISONS = {12: "hiver", 1: "hiver", 2: "hiver", 3: "printemps", 4: "printemps", 5: "printemps",
            6: "ete", 7: "ete", 8: "ete", 9: "automne", 10: "automne", 11: "automne"}


def decisions() -> tuple[str, ...]:
    return _DECISIONS


def empreinte(valeur: Any) -> str:
    """SHA-256 du JSON canonique (clés triées, ASCII) : l'identité de tout ce que ce module produit."""
    return hashlib.sha256(
        json.dumps(valeur, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("utf-8")
    ).hexdigest()


def saison_de(instant: datetime) -> str:
    """Saison de calendrier du mois (hiver, printemps, ete, automne) : une étiquette descriptive, pas une météo."""
    return _SAISONS[instant.month]


def _txt(valeur: Decimal) -> str:
    return format(valeur.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN), "f")


def _decimal(valeur: Any) -> Decimal | None:
    """Décimal fini et strictement positif depuis un Decimal ou un texte décimal strict ; ``None`` sinon (jamais un
    flottant, jamais un booléen)."""
    if isinstance(valeur, (bool, float)):
        return None
    if isinstance(valeur, str):
        if len(valeur) > 40 or _DECIMAL_TEXTE.fullmatch(valeur) is None:
            return None
        valeur = Decimal(valeur)
    if not isinstance(valeur, Decimal) or not valeur.is_finite() or valeur <= 0:
        return None
    return valeur


def _entier(valeur: Any, minimum: int, maximum: int) -> int | None:
    return valeur if type(valeur) is int and minimum <= valeur <= maximum else None


# --------------------------------------------------------------------------------------------------- politique
def lire_politique(brut: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """``(politique, None)`` ou ``(None, verdict)``. Tout champ est DÉCLARÉ par l'entreprise : un champ absent, nul
    ou hors des limites structurelles rend un verdict qui nomme ce qu'il faut déclarer, jamais une valeur par défaut.
    Les limites ci-dessous bornent la FORME (un taux de palier de 0 % ou de 500 % est une faute de frappe), elles ne
    choisissent aucune valeur."""
    a_declarer = (
        "déclarer department.yaml/configuration/apprentissage_durees : " + ", ".join(CHAMPS_POLITIQUE)
        + " (aucune valeur par défaut)"
    )

    def refus(detail: str) -> tuple[None, dict[str, Any]]:
        return None, {"code": "REJ-APPRENTISSAGE-POLITIQUE-ABSENTE", "detail": f"{detail} ; {a_declarer}"}

    if not isinstance(brut, dict) or set(brut) != set(CHAMPS_POLITIQUE):
        manquants = sorted(set(CHAMPS_POLITIQUE) - set(brut)) if isinstance(brut, dict) else list(CHAMPS_POLITIQUE)
        return refus("politique absente ou incomplète" + (f" (manque : {', '.join(manquants)})" if manquants else ""))
    if brut["version"] != VERSION_POLITIQUE:
        return refus(f"version attendue {VERSION_POLITIQUE}")
    entiers = {
        "echantillon_minimum": (3, 1000), "echantillon_minimum_equipe": (3, 1000), "demi_vie_jours": (7, 3650),
        "replications": (200, 5000), "derive_fenetre": (3, 1000),
    }
    politique: dict[str, Any] = {"version": VERSION_POLITIQUE}
    for champ, (bas, haut) in entiers.items():
        valeur = _entier(brut[champ], bas, haut)
        if valeur is None:
            return refus(f"{champ} : entier de {bas} à {haut}")
        politique[champ] = valeur
    decimaux = {
        "aberrantes_k": (Decimal("2"), Decimal("10")), "echelle_minimale_relative": (Decimal("0.001"), Decimal("1")),
        "niveau_confiance": (Decimal("0.5"), Decimal("0.999")), "variation_minimale_pct": (Decimal("0.01"), _CENT),
        "variation_auto_max_pct": (Decimal("0.1"), _CENT), "facteur_min": (Decimal("0.01"), Decimal("1")),
        "facteur_max": (Decimal("1"), Decimal("100")), "derive_seuil_pct": (Decimal("1"), Decimal("1000")),
    }
    for champ, (bas, haut) in decimaux.items():
        valeur = _decimal(brut[champ])
        if valeur is None or not bas <= valeur <= haut:
            return refus(f"{champ} : texte décimal de {bas} à {haut}")
        politique[champ] = valeur
    complexites = brut["complexites"]
    if (
        not isinstance(complexites, list) or not 1 <= len(complexites) <= 8
        or any(not isinstance(c, str) or _CODE.fullmatch(c) is None for c in complexites)
        or len(set(complexites)) != len(complexites) or COMPLEXITE_INCONNUE in complexites
    ):
        return refus(f"complexites : 1 à 8 codes distincts (minuscules), « {COMPLEXITE_INCONNUE} » est réservé")
    politique["complexites"] = list(complexites)
    if politique["derive_fenetre"] < politique["echantillon_minimum"]:
        return refus("derive_fenetre doit être au moins echantillon_minimum (la fenêtre récente fait l'échantillon)")
    if politique["variation_minimale_pct"] >= politique["variation_auto_max_pct"]:
        return refus("variation_minimale_pct doit être inférieure à variation_auto_max_pct")
    politique["empreinte"] = empreinte(politique_canonique(politique))
    return politique, None


def politique_canonique(politique: dict[str, Any]) -> dict[str, Any]:
    """La politique sous forme de texte, sans son empreinte : ce qui est haché et inscrit au journal."""
    return {
        cle: (format(valeur, "f") if isinstance(valeur, Decimal) else valeur)
        for cle, valeur in politique.items() if cle != "empreinte"
    }


# ------------------------------------------------------------------------------------------- observations
def _instant(valeur: Any) -> datetime | None:
    if not isinstance(valeur, str) or len(valeur) > 40:
        return None
    try:
        instant = datetime.fromisoformat(valeur[:-1] + "+00:00" if valeur.endswith("Z") else valeur)
    except ValueError:
        return None
    if instant.tzinfo is None or instant.utcoffset().total_seconds() != 0:  # type: ignore[union-attr]
        return None
    return instant.astimezone(UTC)


instant_utc = _instant


def _iso(instant: datetime) -> str:
    return instant.isoformat().replace("+00:00", "Z")


def _ligne(brute: Any, maintenant: datetime, politique: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """Normalise une observation ou rend la RAISON de son exclusion (une seule, la première, dans un ordre fixe)."""
    if not isinstance(brute, dict):
        return None, "forme_invalide"
    preuve = brute.get("preuve")
    if brute.get("statut") != STATUT_CERTIFIE:
        return None, "non_certifiee"
    if (
        not isinstance(preuve, dict) or preuve.get("liaison_exacte") is not True
        or preuve.get("chaine_m3_valide") is not True
    ):
        return None, "non_certifiee"
    if preuve.get("semantique_reel") != SEMANTIQUE_SUR_SITE or brute.get("inclut_deplacement") is True:
        return None, "semantique_non_sur_site"
    if preuve.get("unite_duree_reelle") != "minute":
        return None, "unite_non_minute"
    if any(
        not isinstance(brute.get(cle), str) or _TEXTE_ID.fullmatch(brute[cle]) is None
        for cle in ("wct_id", "chantier_id", "type_service", "unite_quantite")
    ):
        return None, "identite_invalide"
    reel, quantite = brute.get("duree_reelle_minutes"), _decimal(brute.get("quantite"))
    if type(reel) is not int or not 0 < reel <= 1_000_000 or quantite is None:
        return None, "mesure_invalide"
    debut, fin = _instant(brute.get("horodatage_debut")), _instant(brute.get("horodatage_completion"))
    if debut is None or fin is None or fin < debut:
        return None, "chronologie_invalide"
    if fin > maintenant:
        return None, "dans_le_futur"
    equipe, complexite = brute.get("equipe_ref"), brute.get("complexite")
    if equipe is not None and (not isinstance(equipe, str) or _TEXTE_ID.fullmatch(equipe) is None):
        return None, "equipe_invalide"
    if complexite is not None and complexite not in politique["complexites"]:
        return None, "complexite_hors_echelle"
    ecart = maintenant - fin
    age_jours = Decimal(ecart.days * 86400 + ecart.seconds) / Decimal(86400)
    poids = _DEUX ** (-(age_jours / Decimal(politique["demi_vie_jours"])))
    return {
        "wct_id": brute["wct_id"], "chantier_id": brute["chantier_id"], "type_service": brute["type_service"],
        "unite_quantite": brute["unite_quantite"], "quantite": quantite, "reel": Decimal(reel),
        "taux": (Decimal(reel) / quantite).quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN),
        "debut": debut, "fin": fin, "age_jours": age_jours, "poids": poids,
        "equipe_ref": equipe, "complexite": complexite if complexite is not None else COMPLEXITE_INCONNUE,
        "saison": saison_de(debut),
    }, None


def _canonique_ligne(ligne: dict[str, Any]) -> str:
    return json.dumps(
        {cle: (format(v, "f") if isinstance(v, Decimal) else _iso(v) if isinstance(v, datetime) else v)
         for cle, v in ligne.items() if cle not in ("poids", "age_jours")},
        sort_keys=True, separators=(",", ":"),
    )


def preparer_observations(brutes: Any, *, maintenant_utc: str, politique: dict[str, Any]) -> dict[str, Any]:
    """Observations normalisées + exclusions comptées par raison. Un même ``wct_id`` en contenu identique compte une
    fois (``rejeux``) ; en contenu divergent, TOUTES ses versions sont exclues (``conflit_rejeu``) : aucune n'est
    présumée la bonne. Rien n'est lu hors des arguments."""
    maintenant = _instant(maintenant_utc)
    if maintenant is None or not isinstance(brutes, (list, tuple)) or len(brutes) > _MAX_LIGNES:
        return {"statut": "refuse", "raisons": ["entree_invalide_ou_hors_limite"], "lignes": [], "exclusions": {}}
    exclusions: dict[str, int] = defaultdict(int)
    vues: dict[str, str | None] = {}
    par_wct: dict[str, dict[str, Any]] = {}
    rejeux = 0
    conflits: set[str] = set()
    with localcontext(_CONTEXTE):
        for brute in brutes:
            ligne, raison = _ligne(brute, maintenant, politique)
            identite = brute.get("wct_id") if isinstance(brute, dict) and isinstance(brute.get("wct_id"), str) else None
            if ligne is None:
                exclusions[raison or "forme_invalide"] += 1
                if identite is not None and identite in vues:
                    conflits.add(identite)
                elif identite is not None:
                    vues[identite] = None
                continue
            canon = _canonique_ligne(ligne)
            if ligne["wct_id"] in vues:
                if vues[ligne["wct_id"]] == canon:
                    rejeux += 1
                else:
                    conflits.add(ligne["wct_id"])
                continue
            vues[ligne["wct_id"]] = canon
            par_wct[ligne["wct_id"]] = ligne
    for identite in sorted(conflits):
        if par_wct.pop(identite, None) is not None:
            exclusions["conflit_rejeu"] += 1
    return {
        "statut": "ok", "lignes": sorted(par_wct.values(), key=lambda x: (x["fin"], x["wct_id"])),
        "exclusions": dict(sorted(exclusions.items())), "rejeux": rejeux,
    }


# -------------------------------------------------------------------------------------------- estimateur
def _mediane(valeurs: list[Decimal]) -> Decimal:
    tries = sorted(valeurs)
    milieu = len(tries) // 2
    return tries[milieu] if len(tries) % 2 else (tries[milieu - 1] + tries[milieu]) / _DEUX


def _mediane_ponderee(paires: list[tuple[Decimal, Decimal]]) -> Decimal:
    """Médiane pondérée : première valeur dont le poids cumulé atteint la moitié ; à égalité exacte, le milieu avec la
    suivante. Ordre total (valeur puis poids) : déterministe."""
    tries = sorted(paires)
    total = sum((p for _, p in tries), Decimal(0))
    cumul = Decimal(0)
    for index, (valeur, poids) in enumerate(tries):
        cumul += poids
        if cumul * _DEUX > total:
            return valeur
        if cumul * _DEUX == total and index + 1 < len(tries):
            return (valeur + tries[index + 1][0]) / _DEUX
    return tries[-1][0]


def _seed(*morceaux: str) -> int:
    return int(hashlib.sha256("\x1f".join(morceaux).encode("utf-8")).hexdigest()[:16], 16)


def _intervalle(
    paires: list[tuple[Decimal, Decimal]], politique: dict[str, Any], graine: int,
) -> tuple[Decimal, Decimal]:
    """Intervalle bootstrap (percentiles) de la médiane pondérée : ``replications`` rééchantillons uniformes avec
    remise, poids d'âge conservés, générateur ensemencé par le contenu."""
    if len(paires) > _MAX_BOOTSTRAP_LIGNES:
        paires = paires[-_MAX_BOOTSTRAP_LIGNES:]
    generateur = random.Random(graine)
    n = len(paires)
    medianes = []
    for _ in range(politique["replications"]):
        medianes.append(_mediane_ponderee([paires[generateur.randrange(n)] for _ in range(n)]))
    medianes.sort()
    alpha = (Decimal(1) - politique["niveau_confiance"]) / _DEUX
    total = len(medianes)
    bas = int((alpha * total).to_integral_value(rounding="ROUND_FLOOR"))
    haut = int(((Decimal(1) - alpha) * total).to_integral_value(rounding="ROUND_CEILING")) - 1
    return medianes[max(0, min(bas, total - 1))], medianes[max(0, min(haut, total - 1))]


def _sans_aberrantes(lignes: list[dict[str, Any]], politique: dict[str, Any]) -> tuple[list[dict[str, Any]], int]:
    mediane = _mediane([ligne["taux"] for ligne in lignes])
    mad = _mediane([abs(ligne["taux"] - mediane) for ligne in lignes])
    echelle = max(_MAD_VERS_SIGMA * mad, politique["echelle_minimale_relative"] * mediane)
    retenues = [ligne for ligne in lignes if abs(ligne["taux"] - mediane) <= politique["aberrantes_k"] * echelle]
    return retenues, len(lignes) - len(retenues)


def _chantiers(lignes: list[dict[str, Any]]) -> list[str]:
    """Chantiers distincts, du plus ancien au plus récent (par leur dernière complétion)."""
    derniere: dict[str, datetime] = {}
    for ligne in lignes:
        derniere[ligne["chantier_id"]] = max(derniere.get(ligne["chantier_id"], ligne["fin"]), ligne["fin"])
    return [c for c, _ in sorted(derniere.items(), key=lambda kv: (kv[1], kv[0]))]


def _pct(a: Decimal, b: Decimal) -> Decimal:
    return abs(a / b - 1) * _CENT


def calculer_cohorte(
    lignes: list[dict[str, Any]], *, type_service: str, unite_quantite: str, taux_baseline: Any,
    taux_courant: Any = None, regime_depuis_utc: str | None = None, politique: dict[str, Any],
) -> dict[str, Any]:
    """Candidate d'une cohorte (type de service, unité) : voir la docstring du module. ``taux_baseline`` est le taux
    du barème en minutes par unité ; ``taux_courant`` celui déjà APPLIQUÉ (version active) ou ``None``. Rend toujours
    un dictionnaire avec une ``decision`` de ``decisions()`` et des ``raisons`` : jamais d'exception pour un manque."""
    with localcontext(_CONTEXTE):
        try:
            return _calculer_cohorte(
                lignes, type_service, unite_quantite, taux_baseline, taux_courant, regime_depuis_utc, politique,
            )
        except DecimalException:
            return _rapport_vide(type_service, unite_quantite, taux_baseline, taux_courant, ["arithmetique_invalide"])


def _rapport_vide(
    type_service: str, unite_quantite: str, baseline: Any, courant: Any, raisons: list[str], **plus: Any,
) -> dict[str, Any]:
    return {
        "cohorte": {"type_service": type_service, "unite_quantite": unite_quantite},
        "taux_baseline": str(baseline), "taux_courant": None if courant is None else str(courant),
        "decision": "insuffisante", "raisons": raisons, **plus,
    }


def _calculer_cohorte(
    lignes: list[dict[str, Any]], type_service: str, unite_quantite: str, baseline_brut: Any, courant_brut: Any,
    regime_depuis_utc: str | None, politique: dict[str, Any],
) -> dict[str, Any]:
    baseline = _decimal(baseline_brut)
    courant = None if courant_brut is None else _decimal(courant_brut)
    if baseline is None or (courant_brut is not None and courant is None):
        return _rapport_vide(type_service, unite_quantite, baseline_brut, courant_brut, ["taux_reference_invalide"])
    regime = _instant(regime_depuis_utc) if regime_depuis_utc is not None else None
    cohorte = [x for x in lignes if x["type_service"] == type_service and x["unite_quantite"] == unite_quantite]
    exclues: dict[str, int] = {}
    if regime is not None:
        avant = [x for x in cohorte if x["fin"] < regime]
        if avant:
            exclues["avant_changement_de_regime"] = len(avant)
        cohorte = [x for x in cohorte if x["fin"] >= regime]
    base = _rapport_vide(type_service, unite_quantite, _txt(baseline), None if courant is None else _txt(courant), [])
    if not cohorte:
        return {**base, "raisons": ["aucune_observation"], "n_observations": 0, "n_chantiers": 0, "exclues": exclues}
    # La dérive est jugée AVANT l'exclusion des aberrantes : un vrai changement de régime (plusieurs chantiers de suite)
    # ne doit pas être pris pour des aberrations par rapport à l'ancien historique. Les médianes y résistent aux
    # chantiers isolés.
    ordre_brut = _chantiers(cohorte)
    reference = courant if courant is not None else baseline
    fenetre = politique["derive_fenetre"]
    derive = {"detectee": False, "fenetre": fenetre, "evaluable": len(ordre_brut) >= 2 * fenetre}
    source = cohorte
    regime_nouveau: str | None = None
    if derive["evaluable"]:
        recents = set(ordre_brut[-fenetre:])
        recentes = [x for x in cohorte if x["chantier_id"] in recents]
        anterieures = [x for x in cohorte if x["chantier_id"] not in recents]
        med_recente = _mediane([x["taux"] for x in recentes])
        med_anterieure = _mediane([x["taux"] for x in anterieures])
        ecart_regime = _pct(med_recente, med_anterieure)
        ecart_reference = _pct(med_recente, reference)
        derive.update({
            "mediane_recente": _txt(med_recente), "mediane_anterieure": _txt(med_anterieure),
            "ecart_pct": _txt(ecart_regime), "ecart_reference_pct": _txt(ecart_reference),
            "seuil_pct": _txt(politique["derive_seuil_pct"]),
        })
        if ecart_regime > politique["derive_seuil_pct"] and ecart_reference > politique["derive_seuil_pct"]:
            derive["detectee"] = True
            source = recentes
            regime_nouveau = _iso(min(x["debut"] for x in recentes))
    estimees, nb_aberrantes = _sans_aberrantes(source, politique)
    if nb_aberrantes:
        exclues["aberrante"] = nb_aberrantes
    ordre = _chantiers(estimees)
    base.update({"n_observations": len(estimees), "n_chantiers": len(ordre), "exclues": exclues, "derive": derive})
    saisons = defaultdict(list)
    for ligne in estimees:
        saisons[ligne["saison"]].append(ligne["taux"])
    base["saisons"] = {s: {"n": len(v), "taux_median": _txt(_mediane(v))} for s, v in sorted(saisons.items())}
    if len(ordre) < politique["echantillon_minimum"]:
        return {**base, "raisons": ["echantillon_insuffisant_apres_derive" if derive["detectee"]
                                    else "echantillon_insuffisant"]}

    paires = [(x["taux"], x["poids"]) for x in estimees]
    appris = _mediane_ponderee(paires)
    graine = _seed(type_service, unite_quantite, politique["empreinte"], str(len(estimees)),
                   empreinte(sorted((x["wct_id"], format(x["taux"], "f")) for x in estimees)))
    bas, haut = _intervalle(paires, politique, graine)
    facteur = appris / baseline
    base.update({
        "taux_appris": _txt(appris), "facteur": _txt(facteur), "regime_depuis_utc": regime_nouveau,
        "intervalle": {"bas": _txt(bas), "haut": _txt(haut), "niveau": format(politique["niveau_confiance"], "f")},
        "observations_sha256": empreinte(sorted(x["wct_id"] for x in estimees)),
        "n_chantiers_estimation": len(ordre),
    })
    raisons: list[str] = []
    if not politique["facteur_min"] <= facteur <= politique["facteur_max"]:
        return {**base, "decision": "refusee_hors_bornes", "raisons": ["facteur_hors_bornes_absolues"]}
    variation = _pct(appris, reference)
    base["variation_pct"] = _txt(variation)
    if bas <= reference <= haut or variation < politique["variation_minimale_pct"]:
        return {**base, "decision": "stable", "raisons": ["taux_en_vigueur_dans_l_intervalle"]}
    if derive["detectee"]:
        raisons.append("derive_detectee")
    if variation > politique["variation_auto_max_pct"]:
        raisons.append("variation_superieure_au_palier")
    return {**base, "decision": "approbation_requise" if raisons else "auto_applicable",
            "raisons": raisons or ["petit_ajustement_dans_les_bornes"]}


def controler_application(
    version: dict[str, Any], *, type_service: str, unite_quantite: str, taux_baseline: Any,
) -> str | None:
    """``None`` si la version active PEUT s'appliquer à cette demande, sinon la raison (rien n'est appliqué). Le taux du
    barème de la demande doit être EXACTEMENT celui contre lequel la version a été décidée : un barème modifié depuis
    invalide la version jusqu'au prochain calcul."""
    cohorte = version.get("cohorte")
    if not isinstance(cohorte, dict) or cohorte.get("type_service") != type_service \
            or cohorte.get("unite_quantite") != unite_quantite:
        return "cohorte_differente"
    reference = _decimal(taux_baseline)
    attendu = _decimal(version.get("taux_baseline"))
    applique = _decimal(version.get("taux_applique"))
    if reference is None or attendu is None or applique is None:
        return "taux_invalide"
    if reference != attendu:
        return "bareme_modifie_depuis_la_version"
    return None


# --------------------------------------------------------------------------------------------- équipes
def performance_equipes(lignes: list[dict[str, Any]], *, politique: dict[str, Any]) -> dict[str, Any]:
    """Indice de rapidité par COUPLE (équipe, type de travaux), normalisé par la difficulté.

    Pour chaque strate (type de service, complexité déclarée ou « inconnue »), la référence est la médiane des taux
    observés de la strate (aberrantes exclues). Une strate n'est COMPARABLE que si au moins deux équipes distinctes y
    ont travaillé et que le nombre de chantiers atteint ``echantillon_minimum_equipe`` : sinon ses observations ne
    comptent pas (``sans_comparaison``) - c'est ce qui empêche une équipe toujours affectée aux chantiers faciles de
    ressortir « meilleure » en travaillant seule dans sa strate. L'indice d'une équipe = médiane pondérée (âge) de
    ``taux / référence de la strate`` sur ses chantiers comparables : 0,93 veut dire 7 % plus rapide que l'habitude de
    l'entreprise pour ce type, à difficulté déclarée comparable. Évaluable si assez de chantiers comparables ; sinon
    « non évaluable » (jamais zéro ni 1). Intervalle : bootstrap comme pour les cohortes. Une observation sans
    ``equipe_ref`` n'entre dans aucun agrégat."""
    with localcontext(_CONTEXTE):
        try:
            return _performance_equipes(lignes, politique)
        except DecimalException:
            return {"statut": "refuse", "raisons": ["arithmetique_invalide"], "equipes": []}


def _performance_equipes(lignes: list[dict[str, Any]], politique: dict[str, Any]) -> dict[str, Any]:
    minimum = politique["echantillon_minimum_equipe"]
    attribuees = [x for x in lignes if x["equipe_ref"] is not None]
    sans_equipe = len(lignes) - len(attribuees)
    strates: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for ligne in attribuees:
        strates[(ligne["type_service"], ligne["unite_quantite"], ligne["complexite"])].append(ligne)
    references: dict[tuple[str, str, str], Decimal] = {}
    resume_strates = []
    for cle, membres in sorted(strates.items()):
        retenues, _ = _sans_aberrantes(membres, politique)
        equipes = {x["equipe_ref"] for x in retenues}
        chantiers = len({x["chantier_id"] for x in retenues})
        comparable = len(equipes) >= 2 and chantiers >= minimum
        resume_strates.append({
            "type_service": cle[0], "complexite": cle[2], "equipes": len(equipes), "chantiers": chantiers,
            "comparable": comparable,
        })
        if comparable:
            references[cle] = _mediane([x["taux"] for x in retenues])
    agreges: dict[tuple[str, str], list[tuple[dict[str, Any], Decimal]]] = defaultdict(list)
    non_comparables: dict[tuple[str, str], int] = defaultdict(int)
    for cle, membres in strates.items():
        retenues, _ = _sans_aberrantes(membres, politique)
        for ligne in retenues:
            groupe = (ligne["equipe_ref"], ligne["type_service"])
            if cle in references:
                agreges[groupe].append((ligne, ligne["taux"] / references[cle]))
            else:
                non_comparables[groupe] += 1
    sortie = []
    for groupe in sorted(set(agreges) | set(non_comparables)):
        comparables = agreges.get(groupe, [])
        chantiers = len({ligne["chantier_id"] for ligne, _ in comparables})
        ligne_sortie: dict[str, Any] = {
            "equipe_ref": groupe[0], "type_service": groupe[1], "chantiers": chantiers,
            "observations_sans_comparaison": non_comparables.get(groupe, 0), "evaluable": False,
        }
        if chantiers < minimum:
            ligne_sortie["motif"] = "echantillon_comparable_insuffisant" if comparables or non_comparables.get(groupe) \
                else "aucune_observation"
            sortie.append(ligne_sortie)
            continue
        paires = [(rapport, ligne["poids"]) for ligne, rapport in comparables]
        indice = _mediane_ponderee(paires)
        sceau = empreinte(sorted(ligne["wct_id"] for ligne, _ in comparables))
        bas, haut = _intervalle(paires, politique, _seed("equipe", groupe[0], groupe[1], politique["empreinte"], sceau))
        ligne_sortie.update({
            "evaluable": True, "indice_median": _txt(indice), "borne_basse": _txt(bas), "borne_haute": _txt(haut),
            "niveau": format(politique["niveau_confiance"], "f"),
            "lecture": (
                f"{chantiers} chantiers de ce type à {_txt(indice)} de la durée habituelle de l'entreprise "
                f"(intervalle {_txt(bas)} à {_txt(haut)}), à difficulté déclarée comparable"
            ),
        })
        sortie.append(ligne_sortie)
    return {
        "statut": "ok", "equipes": sortie, "strates": resume_strates, "observations_sans_equipe": sans_equipe,
        "limite": (
            "Agrégat d'équipe par type de travaux : jamais une note de personne ; la référence est la médiane de "
            "l'entreprise par strate (type, complexité déclarée), pas l'estimation d'origine."
        ),
    }
