"""Lead scoring 2.0 (DEFINITION-PRODUIT §7 M2.4) : un score TRANSPARENT, EXPLICABLE et DÉTERMINISTE qui ORDONNE la file.

Ce que le score est, et n'est pas :

- **Il ordonne, il ne décide pas.** Le score classe les leads ouverts pour que le vendeur commence par le bon. Il
  n'écarte, ne rejette, ne ferme et ne rétrograde AUCUN lead : tout lead ouvert reste dans la file, à son rang, et un
  humain décide de la suite (`decision_humaine_requise` est toujours vrai). Aucune fonction de ce module ne touche à
  un statut.
- **Il est lisible.** Six facteurs (qualité, urgence, conversion, rentabilité, préparation, risque), chacun fait de
  SIGNAUX à points déclarés ; les poids des facteurs sont déclarés ici, dans `MODELE`, versionnés, et rendus avec
  chaque score. Chaque score dit sa contribution par facteur et par signal, ce qui manque, et la version du modèle.
- **Il est déterministe.** Les mêmes faits donnent le même score, au chiffre près (entiers et fractions exactes :
  aucun flottant). L'instant de référence est fourni par l'appelant.
- **Il ne devine pas.** Un signal sans donnée (devis illisibles, seuil non configuré, lead non qualifié) est NON
  ÉVALUÉ, nommé avec ce qui manque, et sort du calcul : le score est normalisé sur ce qui a été évalué et dit sa
  couverture. Aucune valeur par défaut n'est inventée.
- **Il est équitable par construction.** Les faits d'entrée sont une liste fermée de booléens et de compteurs ; aucun
  attribut protégé (âge, genre, origine, langue, état civil, santé…) ni aucun identifiant personnel (nom, adresse,
  code postal, téléphone, courriel) n'est un facteur : `CHAMPS_INTERDITS` les nomme, le validateur les refuse
  (`REJ-SCORE-CHAMP-INTERDIT`) et des tests les vérifient (la liste des signaux ne la recoupe pas ; changer un nom ou
  un téléphone, sans changer leur présence, ne change pas le score).
- **Il n'affirme aucune probabilité.** La calibration (`calibration_scoring.py`) est mesurée sur un jeu FICTIF : elle
  prouve l'outil de mesure, pas la valeur prédictive du score sur de vrais clients. Tant qu'elle n'est pas refaite sur
  des conversions réelles consenties, le score est un RANG, jamais une probabilité (`probabilite_calibree` reste
  absente).

Module PUR : aucune entrée-sortie, aucune horloge, aucun modèle.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Mapping, Sequence
from decimal import ROUND_HALF_EVEN, Decimal
from fractions import Fraction
from typing import Any

from . import encodage
from .verdicts_commercial import construire_verdict

__all__ = [
    "AVERTISSEMENT_RANG",
    "CHAMPS_FAITS",
    "CHAMPS_INTERDITS",
    "FACTEURS",
    "MODELE",
    "MODELE_ID",
    "VERSION",
    "calculer",
    "classer",
    "declaration_modele",
    "resume",
    "empreinte_modele",
    "valider_faits",
]

MODELE_ID = "m2-score-lead"
VERSION = "1.0.0"
AVERTISSEMENT_RANG = (
    "Le score ORDONNE la file de travail ; il n'écarte, ne rejette et ne ferme aucun lead. Un humain décide de la "
    "suite. Ce n'est pas une probabilité : la calibration disponible est mesurée sur un jeu fictif."
)

STATUTS_CLASSES = ("nouveau", "qualifie")  # les statuts ouverts : les seuls qu'on ordonne

# Attributs protégés et identifiants personnels : jamais un facteur, jamais un fait d'entrée (Charte québécoise des
# droits et libertés, art. 10 ; Loi 25 : minimisation). La liste est en minuscules sans accents.
CHAMPS_INTERDITS = frozenset(
    {
        "nom",
        "prenom",
        "nom_famille",
        "nom_client",
        "genre",
        "sexe",
        "identite_de_genre",
        "orientation_sexuelle",
        "age",
        "age_client",
        "date_naissance",
        "annee_naissance",
        "origine",
        "origine_ethnique",
        "ethnie",
        "race",
        "couleur",
        "religion",
        "croyance",
        "langue",
        "langue_parlee",
        "langue_maternelle",
        "handicap",
        "sante",
        "etat_civil",
        "situation_familiale",
        "grossesse",
        "nationalite",
        "citoyennete",
        "statut_immigration",
        "convictions_politiques",
        "casier_judiciaire",
        "revenu",
        "revenu_menage",
        "source_de_revenu",
        "occupation_client",
        "adresse",
        "code_postal",
        "quartier",
        "telephone",
        "courriel",
        "numero_assurance_sociale",
        "nas",
    }
)

# Les faits d'entrée : liste FERMÉE (nom -> type attendu). Aucun texte libre : des booléens, des compteurs, un statut.
CHAMPS_FAITS: Mapping[str, str] = {
    "contact_courriel": "bool",
    "contact_telephone": "bool",
    "contact_nom": "bool",
    "ville": "bool",
    "service": "bool",
    "canal_connu": "bool",
    "source_connue": "bool",
    "completude_propriete_pct": "pct",
    "urgence_declaree": "bool",
    "jours_depuis_ingestion": "jours",
    "statut": "statut",
    "interactions_humaines": "compteur",
    "jours_depuis_activite": "jours",
    "devis_envoye": "bool_ou_none",
    "readiness_proprietaire": "bool_ou_none",
    "readiness_service": "bool_ou_none",
    "readiness_ville": "bool_ou_none",
    "readiness_interaction": "bool_ou_none",
    "profil_propriete_confirme": "bool",
    "photos_liees": "compteur",
    "valeur_declaree_cents": "montant_ou_none",
    "bandes_valeur_cents": "bandes_ou_none",
    "doublon_en_attente": "bool",
    "retrait_consentement": "bool",
    "seuil_dormant_jours": "jours_ou_none",
}
_JOURS_MAX = 36_500
_COMPTEUR_MAX = 100_000
_MONTANT_MAX = 10**12

# --- le modèle : facteurs, poids, signaux (points déclarés). Σ poids = 100 ; Σ max des signaux d'un facteur = 100.
# Chaque signal : (nom, points_max, règle en une phrase). La règle d'évaluation est dans `_evaluer_signal`.
FACTEURS: Mapping[str, Mapping[str, Any]] = {
    "qualite": {
        "poids": 20,
        "libelle": "Qualité du dossier",
        "signaux": (
            ("contact_courriel", 20, "un courriel est fourni"),
            ("contact_telephone", 20, "un téléphone est fourni"),
            ("contact_nom", 10, "un nom est fourni"),
            ("ville", 10, "la ville est fournie"),
            ("service", 15, "le service demandé est fourni"),
            ("canal_connu", 5, "le canal d'arrivée est connu"),
            ("source_connue", 10, "la source ou la campagne est connue"),
            ("completude_propriete_pct", 10, "complétude du profil de propriété, au prorata"),
        ),
    },
    "urgence": {
        "poids": 15,
        "libelle": "Urgence",
        "signaux": (
            ("urgence_declaree", 60, "le client a déclaré une urgence"),
            ("fraicheur", 40, "ingéré depuis au plus 2 jours : 40 ; 7 jours : 25 ; 14 jours : 10 ; plus : 0"),
        ),
    },
    "conversion": {
        "poids": 25,
        "libelle": "Avancement vers la conversion",
        "signaux": (
            ("statut", 35, "qualifié : 35 ; nouveau : 10"),
            ("interactions_humaines", 30, "10 points par interaction humaine, 3 au plus"),
            (
                "activite_recente",
                25,
                "dernière activité humaine depuis au plus 7 jours : 25 ; 14 jours : 15 ; 30 jours : 5",
            ),
            ("devis_envoye", 10, "un devis a été envoyé au client"),
        ),
    },
    "rentabilite": {
        "poids": 15,
        "libelle": "Valeur déclarée",
        "signaux": (
            (
                "valeur_declaree",
                100,
                "la valeur déclarée par le vendeur, placée dans les bandes configurées : 25 / 50 / 75 / 100",
            ),
        ),
    },
    "preparation": {
        "poids": 15,
        "libelle": "Préparation à l'estimation",
        "signaux": (
            ("readiness_proprietaire", 15, "un propriétaire est assigné"),
            ("readiness_service", 15, "le service est valide"),
            ("readiness_ville", 15, "la ville est fournie"),
            ("readiness_interaction", 15, "une interaction humaine suit la qualification"),
            ("profil_propriete_confirme", 25, "un profil de propriété confirmé existe"),
            ("photos_liees", 15, "au moins une photo est liée au profil"),
        ),
    },
    "risque": {
        "poids": 10,
        "libelle": "Risque (plus haut = moins risqué)",
        "signaux": (
            ("pas_de_doublon", 40, "aucun doublon probable en attente d'arbitrage"),
            ("consentement_maintenu", 20, "aucun retrait de consentement (STOP)"),
            ("pas_dormant", 40, "dernière activité dans le seuil de dormance configuré"),
        ),
    },
}
MODELE: Mapping[str, Any] = {"id": MODELE_ID, "version": VERSION, "facteurs": FACTEURS}


def _verifier_modele() -> None:
    """Le modèle se vérifie à son chargement : une erreur de somme est une erreur du code, pas une donnée."""
    if sum(f["poids"] for f in FACTEURS.values()) != 100:
        raise ValueError("modèle de score : la somme des poids doit valoir 100")
    for nom, facteur in FACTEURS.items():
        if sum(points for _, points, _ in facteur["signaux"]) != 100:
            raise ValueError(f"modèle de score : les points du facteur {nom} doivent totaliser 100")
    signaux = {s for f in FACTEURS.values() for s, _, _ in f["signaux"]}
    interdits = {_plier(s) for s in signaux} & CHAMPS_INTERDITS
    if interdits:
        raise ValueError(f"modèle de score : signal(s) interdit(s) {sorted(interdits)}")


def _plier(texte: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texte.lower()) if not unicodedata.combining(c))


_verifier_modele()


def empreinte_modele() -> str:
    """Empreinte du modèle (identifiant, version, facteurs, poids, signaux, points) : elle change si UN poids change."""
    return encodage.encoder_canonique(
        MODELE_ID, VERSION, [[nom, f["poids"], [[s, p] for s, p, _ in f["signaux"]]] for nom, f in FACTEURS.items()]
    )


def declaration_modele() -> dict[str, Any]:
    """Le modèle tel qu'il est publié à l'utilisateur : facteurs, poids déclarés, signaux et leur règle."""
    return {
        "id": MODELE_ID,
        "version": VERSION,
        "empreinte": empreinte_modele(),
        "facteurs": [
            {
                "facteur": nom,
                "libelle": f["libelle"],
                "poids": f["poids"],
                "signaux": [{"signal": s, "points_max": p, "regle": regle} for s, p, regle in f["signaux"]],
            }
            for nom, f in FACTEURS.items()
        ],
        "champs_interdits": sorted(CHAMPS_INTERDITS),
        "faits_d_entree": sorted(CHAMPS_FAITS),
        "avertissement": AVERTISSEMENT_RANG,
    }


# ---------------------------------------------------------------------------------------------- validation
def _refus(code: str, detail: str) -> tuple[None, dict[str, str]]:
    return None, construire_verdict(code, detail=detail)


def _type_valide(genre: str, valeur: Any) -> bool:
    if genre == "bool":
        return type(valeur) is bool
    if genre == "bool_ou_none":
        return valeur is None or type(valeur) is bool
    if genre == "pct":
        return type(valeur) is int and 0 <= valeur <= 100
    if genre == "jours":
        return type(valeur) is int and 0 <= valeur <= _JOURS_MAX
    if genre == "jours_ou_none":
        return valeur is None or (type(valeur) is int and 1 <= valeur <= _JOURS_MAX)
    if genre == "compteur":
        return type(valeur) is int and 0 <= valeur <= _COMPTEUR_MAX
    if genre == "statut":
        return valeur in STATUTS_CLASSES
    if genre == "montant_ou_none":
        return valeur is None or (type(valeur) is int and 0 <= valeur <= _MONTANT_MAX)
    if genre == "bandes_ou_none":
        return valeur is None or (
            isinstance(valeur, (list, tuple))
            and len(valeur) == 3
            and all(type(v) is int and v > 0 for v in valeur)
            and valeur[0] < valeur[1] < valeur[2]
        )
    return False


def valider_faits(faits: Any) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Les faits d'entrée, normalisés, ou un refus : un fait hors liste fermée est refusé, et s'il porte le nom d'un
    attribut protégé ou d'un identifiant personnel, c'est `REJ-SCORE-CHAMP-INTERDIT`."""
    if not isinstance(faits, Mapping):
        return _refus("REJ-SCORE-FAITS-INVALIDES", "faits : objet attendu")
    interdits = sorted(cle for cle in faits if isinstance(cle, str) and _plier(cle) in CHAMPS_INTERDITS)
    if interdits:
        return _refus(
            "REJ-SCORE-CHAMP-INTERDIT",
            (
                f"{interdits} : un attribut protégé ou un identifiant personnel n'entre jamais dans le score "
                "(équité, Loi 25)"
            ),
        )
    inconnus = sorted(str(cle) for cle in faits if cle not in CHAMPS_FAITS)
    manquants = sorted(cle for cle in CHAMPS_FAITS if cle not in faits)
    if inconnus or manquants:
        return _refus("REJ-SCORE-FAITS-INVALIDES", f"faits hors liste fermée {inconnus} ou manquants {manquants}")
    for cle, genre in CHAMPS_FAITS.items():
        if not _type_valide(genre, faits[cle]):
            return _refus("REJ-SCORE-FAITS-INVALIDES", f"{cle} : valeur hors du type {genre}")
    normalises = dict(faits)
    if normalises["bandes_valeur_cents"] is not None:
        normalises["bandes_valeur_cents"] = list(normalises["bandes_valeur_cents"])
    return normalises, None


# ---------------------------------------------------------------------------------------------- évaluation
def _evaluer_signal(facteur: str, signal: str, max_points: int, f: Mapping[str, Any]) -> tuple[int | None, str | None]:
    """`(points, None)` ou `(None, ce qui manque)` : un signal non évalué ne rapporte rien et ne compte pas dans le
    max."""
    if signal in (
        "contact_courriel",
        "contact_telephone",
        "contact_nom",
        "ville",
        "service",
        "canal_connu",
        "source_connue",
        "urgence_declaree",
        "profil_propriete_confirme",
    ):
        return (max_points if f[signal] else 0), None
    if signal == "completude_propriete_pct":
        return (max_points * f["completude_propriete_pct"]) // 100, None
    if signal == "fraicheur":
        jours = f["jours_depuis_ingestion"]
        return (40 if jours <= 2 else 25 if jours <= 7 else 10 if jours <= 14 else 0), None
    if signal == "statut":
        return (35 if f["statut"] == "qualifie" else 10), None
    if signal == "interactions_humaines":
        return 10 * min(f["interactions_humaines"], 3), None
    if signal == "activite_recente":
        jours = f["jours_depuis_activite"]
        return (25 if jours <= 7 else 15 if jours <= 14 else 5 if jours <= 30 else 0), None
    if signal == "devis_envoye":
        if f["devis_envoye"] is None:
            return None, "les devis de M3 ne sont pas lisibles"
        return (max_points if f["devis_envoye"] else 0), None
    if signal == "valeur_declaree":
        if f["bandes_valeur_cents"] is None:
            return None, "bandes de valeur à configurer (configuration.scoring.bandes_valeur_cents)"
        if f["valeur_declaree_cents"] is None:
            return None, "aucune valeur déclarée par le vendeur pour ce lead"
        a, b, c = f["bandes_valeur_cents"]
        valeur = f["valeur_declaree_cents"]
        return (25 if valeur < a else 50 if valeur < b else 75 if valeur < c else 100), None
    if signal in ("readiness_proprietaire", "readiness_service", "readiness_ville", "readiness_interaction"):
        if f[signal] is None:
            return None, "readiness calculée seulement pour un lead qualifié"
        return (max_points if f[signal] else 0), None
    if signal == "photos_liees":
        return (max_points if f["photos_liees"] > 0 else 0), None
    if signal == "pas_de_doublon":
        return (0 if f["doublon_en_attente"] else max_points), None
    if signal == "consentement_maintenu":
        return (0 if f["retrait_consentement"] else max_points), None
    if signal == "pas_dormant":
        if f["seuil_dormant_jours"] is None:
            return None, "seuil de dormance à configurer (configuration.segments.jours_inactivite_dormant)"
        return (max_points if f["jours_depuis_activite"] <= f["seuil_dormant_jours"] else 0), None
    raise ValueError(f"signal {signal!r} du facteur {facteur!r} sans règle d'évaluation")


def _texte(valeur: Fraction, chiffres: int = 2) -> str:
    """Une fraction exacte en texte décimal (arrondi pair), jamais un flottant."""
    decimal = Decimal(valeur.numerator) / Decimal(valeur.denominator)
    return format(decimal.quantize(Decimal(1).scaleb(-chiffres), rounding=ROUND_HALF_EVEN), "f")


def calculer(faits: Any) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Le score d'un lead ouvert et son explication complète : `(resultat, None)` ou `(None, verdict)`.

    `resultat` : `score` (texte, 0 à 100, 2 décimales), `couverture_poids` (part des poids évalués), `facteurs`
    (poids, sous-score, contribution en points au score, signaux avec leurs points), `facteurs_non_evalues` /
    `signaux_non_evalues` (avec ce qui manque), `modele` (id, version, empreinte), `decision_humaine_requise: true`,
    `avertissement`. Aucun champ `ecarter`, `rejeter` ni `probabilite` n'existe."""
    normalises, verdict = valider_faits(faits)
    if verdict is not None:
        return None, verdict
    f = normalises
    facteurs = []
    non_evalues_facteurs = []
    non_evalues_signaux = []
    numerateur = Fraction(0)
    denominateur = 0
    for nom, facteur in FACTEURS.items():
        points_obtenus = 0
        points_possibles = 0
        signaux = []
        for signal, max_points, _regle in facteur["signaux"]:
            points, manque = _evaluer_signal(nom, signal, max_points, f)
            if points is None:
                non_evalues_signaux.append({"facteur": nom, "signal": signal, "manque": manque})
                signaux.append({"signal": signal, "points": None, "points_max": max_points})
                continue
            points_obtenus += points
            points_possibles += max_points
            signaux.append({"signal": signal, "points": points, "points_max": max_points})
        if points_possibles == 0:
            manques = sorted({x["manque"] for x in non_evalues_signaux if x["facteur"] == nom})
            non_evalues_facteurs.append({"facteur": nom, "poids": facteur["poids"], "manque": "; ".join(manques)})
            facteurs.append(
                {"facteur": nom, "poids": facteur["poids"], "evalue": False, "sous_score": None, "signaux": signaux}
            )
            continue
        sous_score = Fraction(100 * points_obtenus, points_possibles)
        numerateur += facteur["poids"] * sous_score
        denominateur += facteur["poids"]
        facteurs.append(
            {
                "facteur": nom,
                "poids": facteur["poids"],
                "evalue": True,
                "sous_score": _texte(sous_score),
                "signaux": signaux,
                "_sous": sous_score,
            }
        )
    if denominateur == 0:
        return _refus("REJ-SCORE-FAITS-INVALIDES", "aucun facteur évaluable : rien à ordonner")
    score = numerateur / denominateur
    for facteur in facteurs:
        if facteur["evalue"]:
            facteur["contribution_points"] = _texte(facteur["poids"] * facteur.pop("_sous") / denominateur)
    return {
        "modele": {"id": MODELE_ID, "version": VERSION, "empreinte": empreinte_modele()},
        "score": _texte(score),
        "_score_exact": score,
        "couverture_poids": _texte(Fraction(denominateur, 100)),
        "facteurs": facteurs,
        "facteurs_non_evalues": non_evalues_facteurs,
        "signaux_non_evalues": non_evalues_signaux,
        "decision_humaine_requise": True,
        "avertissement": AVERTISSEMENT_RANG,
    }, None


def sans_exact(resultat: Mapping[str, Any]) -> dict[str, Any]:
    """Le résultat sans la valeur exacte interne (`_score_exact`, une fraction) : la forme qui traverse un outil."""
    return {cle: valeur for cle, valeur in resultat.items() if cle != "_score_exact"}


def resume(resultat: Mapping[str, Any]) -> dict[str, Any]:
    """Le résumé d'un score pour une file ou un contexte : score, deux facteurs dominants, couverture, non évalués."""
    return {
        "score": resultat["score"],
        "facteurs_dominants": sorted(
            (
                {"facteur": f["facteur"], "contribution_points": f["contribution_points"]}
                for f in resultat["facteurs"]
                if f["evalue"]
            ),
            key=lambda x: (-Decimal(x["contribution_points"]), x["facteur"]),
        )[:2],
        "couverture_poids": resultat["couverture_poids"],
        "non_evalue": [x["facteur"] for x in resultat["facteurs_non_evalues"]],
    }


def classer(scores: Sequence[tuple[str, Mapping[str, Any], str]]) -> list[dict[str, Any]]:
    """Ordonne des leads déjà notés : `(lead_id, résultat de calculer, clé d'ingestion)` -> liste ordonnée. Ordre :
    score
    exact décroissant, puis ingestion croissante (le plus ancien d'abord ; la clé doit se comparer comme du texte, par
    exemple un instant UTC ISO-8601), puis `lead_id`. C'est une PERMUTATION : aucun lead n'est retiré ni écarté, et le
    nombre de sortie est celui d'entrée."""
    ordonnes = sorted(scores, key=lambda t: (-t[1]["_score_exact"], t[2], t[0]))
    return [{"rang": i + 1, "lead_id": lead_id, **resume(r)} for i, (lead_id, r, _) in enumerate(ordonnes)]
