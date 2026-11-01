"""Calibration MESURÉE du score de lead (M2.4), sur un jeu FICTIF : AUC, Brier, courbe de calibration, par la
bibliothèque standard seulement (aucun numpy, aucun scipy).

CE QUE CE MODULE PROUVE, ET CE QU'IL NE PROUVE PAS. Le jeu est SYNTHÉTIQUE : il est tiré d'une graine par un
générateur déterministe (`random.Random`, entiers seulement), avec une « vraie » propension de conversion écrite à la
main, DIFFÉRENTE du modèle de score (elle ignore la valeur et les photos, elle ajoute du bruit). Les chiffres rendus
mesurent donc la MÉCANIQUE (l'outil de mesure est exact, le calibrateur monotone fonctionne, un score qui ordonne
mieux que le hasard est reconnu), PAS la capacité du score à prédire de vrais clients : aucun client réel n'a servi,
aucun n'en sert. Tant que cette mesure n'est pas refaite sur des conversions réelles consenties (EFVP Loi 25 d'abord),
le score reste un RANG.

Méthode :
- jeu : `n` leads fictifs tirés de la graine ; leurs faits passent par `scoring.calculer` (le même code que la
  production) ;
- partition : rangs pairs = entraînement (calibrateur), rangs impairs = test (toutes les métriques) ;
- AUC : statistique de Mann-Whitney, ex æquo à demi, par rangs triés — fractions exactes ;
- calibrateur : régression isotone (PAV, blocs de moyennes d'au moins 30 leads) ajustée sur l'entraînement, appliquée
  au test ;
- Brier : moyenne de (p − y)², sur le test, contre la référence « taux de base de l'entraînement » (Brier de
  référence) ;
- courbe : le test en 10 tranches de probabilité de largeur 0,1 (brute : score/100 ; calibrée : sortie du calibrateur)
  ; par tranche : effectif, probabilité moyenne, fréquence observée ; ECE = Σ (n_k/n)·|moyenne_k − observé_k|.

Tout est en nombres exacts (entiers et fractions) et rendu en texte décimal : le même appel donne la même sortie,
partout.
"""

from __future__ import annotations

import random
from decimal import ROUND_HALF_EVEN, Decimal
from fractions import Fraction
from typing import Any

from . import scoring
from .verdicts_commercial import construire_verdict

__all__ = [
    "BANDES_FICTIVES",
    "GRAINE_DEFAUT",
    "N_DEFAUT",
    "N_MAX",
    "N_MIN",
    "auc",
    "brier",
    "isotone",
    "jeu_fictif",
    "mesurer",
]

GRAINE_DEFAUT = 20261101
N_DEFAUT = 2000
N_MIN = 200
N_MAX = 20000
BANDES_FICTIVES = (500_000, 1_500_000, 4_000_000)  # cents : bandes de valeur FICTIVES du jeu, pas une configuration
TRANCHES = 10
TAILLE_MIN_BLOC = 30  # effectif minimal d'un palier du calibrateur (voir `isotone`)


def _texte(valeur: Fraction, chiffres: int = 4) -> str:
    decimal = Decimal(valeur.numerator) / Decimal(valeur.denominator)
    return format(decimal.quantize(Decimal(1).scaleb(-chiffres), rounding=ROUND_HALF_EVEN), "f")


def jeu_fictif(graine: int, n: int) -> list[dict[str, Any]]:
    """`n` leads FICTIFS : leurs faits (liste fermée du modèle) et une issue 0/1 tirée d'une propension écrite à la
    main.
    Entiers seulement : la même graine donne le même jeu sur toute machine."""
    rng = random.Random(graine)
    jeu = []
    for _ in range(n):
        qualifie = rng.randrange(100) < 55
        jours_ingestion = rng.randrange(0, 61)
        jours_activite = rng.randrange(0, jours_ingestion + 1)
        interactions = rng.randrange(0, 6)
        courriel = rng.randrange(100) < 85
        telephone = rng.randrange(100) < 80
        urgence = rng.randrange(100) < 20
        devis = (rng.randrange(100) < 30) if qualifie else False
        profil = rng.randrange(100) < 15
        photos = rng.randrange(0, 4) if rng.randrange(100) < 25 else 0
        valeur = None if rng.randrange(100) < 40 else 100_000 * rng.randrange(1, 80)
        completude = 0 if rng.randrange(100) < 50 else rng.randrange(0, 101)
        faits = {
            "contact_courriel": courriel,
            "contact_telephone": telephone,
            "contact_nom": rng.randrange(100) < 95,
            "ville": rng.randrange(100) < 90,
            "service": rng.randrange(100) < 90,
            "canal_connu": rng.randrange(100) < 95,
            "source_connue": rng.randrange(100) < 60,
            "completude_propriete_pct": completude,
            "urgence_declaree": urgence,
            "jours_depuis_ingestion": jours_ingestion,
            "statut": "qualifie" if qualifie else "nouveau",
            "interactions_humaines": interactions,
            "jours_depuis_activite": jours_activite,
            "devis_envoye": devis,
            "readiness_proprietaire": (rng.randrange(100) < 90) if qualifie else None,
            "readiness_service": (rng.randrange(100) < 85) if qualifie else None,
            "readiness_ville": (rng.randrange(100) < 90) if qualifie else None,
            "readiness_interaction": (interactions >= 1) if qualifie else None,
            "profil_propriete_confirme": profil,
            "photos_liees": photos,
            "valeur_declaree_cents": valeur,
            "bandes_valeur_cents": list(BANDES_FICTIVES),
            "doublon_en_attente": rng.randrange(100) < 5,
            "retrait_consentement": rng.randrange(100) < 3,
            "seuil_dormant_jours": 30,
        }
        # Propension « vraie » du jeu fictif, en pour-mille : DIFFÉRENTE du modèle de score à dessein.
        permille = (
            60
            + 140 * (interactions >= 2)
            + 160 * qualifie
            + 120 * urgence
            + 90 * devis
            + 70 * (courriel and telephone)
            + 60 * profil
            - 4 * min(jours_activite, 60)
            + rng.randrange(-120, 121)
        )
        permille = max(10, min(900, permille))
        jeu.append({"faits": faits, "issue": 1 if rng.randrange(1000) < permille else 0})
    return jeu


def auc(scores: list[Fraction], issues: list[int]) -> Fraction | None:
    """Aire sous la courbe ROC (Mann-Whitney) : P(score d'un positif > score d'un négatif) + ½ P(égalité). `None` si une
    des deux classes est vide (l'AUC n'est pas définie)."""
    positifs = sum(issues)
    negatifs = len(issues) - positifs
    if positifs == 0 or negatifs == 0:
        return None
    ordre = sorted(range(len(scores)), key=lambda i: scores[i])
    somme_rangs = Fraction(0)  # rangs moyens (1-indexés) des positifs
    i = 0
    while i < len(ordre):
        j = i
        while j + 1 < len(ordre) and scores[ordre[j + 1]] == scores[ordre[i]]:
            j += 1
        rang_moyen = Fraction(i + 1 + j + 1, 2)
        somme_rangs += rang_moyen * sum(issues[ordre[k]] for k in range(i, j + 1))
        i = j + 1
    return (somme_rangs - Fraction(positifs * (positifs + 1), 2)) / (positifs * negatifs)


def brier(probabilites: list[Fraction], issues: list[int]) -> Fraction:
    """Score de Brier : moyenne de (p − y)²."""
    return sum(((p - y) ** 2 for p, y in zip(probabilites, issues, strict=True)), Fraction(0)) / len(issues)


def isotone(
    scores: list[Fraction], issues: list[int], taille_min: int = 1
) -> list[tuple[Fraction, Fraction, Fraction, int]]:
    """Régression isotone (PAV) : blocs `(score_min, score_max, probabilité, effectif)` croissants en score ET en
    probabilité. Les ex æquo de score sont regroupés avant la mise en commun. `taille_min` : un bloc plus petit que ça
    est fondu dans son voisin (la moyenne reste entre les deux : la monotonie est conservée) — sans cela, deux leads
    de queue donnent une « probabilité » de 1,0 qu'aucun effectif ne soutient."""
    groupes: dict[Fraction, list[int]] = {}
    for s, y in zip(scores, issues, strict=True):
        groupes.setdefault(s, []).append(y)
    pile: list[list[Any]] = []
    for s in sorted(groupes):
        pile.append([s, s, sum(groupes[s]), len(groupes[s])])
        while len(pile) >= 2 and Fraction(pile[-2][2], pile[-2][3]) >= Fraction(pile[-1][2], pile[-1][3]):
            haut = pile.pop()
            bas = pile.pop()
            pile.append([bas[0], haut[1], bas[2] + haut[2], bas[3] + haut[3]])
    while len(pile) > 1 and min(b[3] for b in pile) < taille_min:
        i = min(range(len(pile)), key=lambda k: (pile[k][3], k))
        j = i - 1 if i > 0 else 1
        voisin, courant = (pile[j], pile[i]) if j < i else (pile[i], pile[j])
        fusion = [voisin[0], courant[1], voisin[2] + courant[2], voisin[3] + courant[3]]
        pile[min(i, j) : max(i, j) + 1] = [fusion]
    return [(b[0], b[1], Fraction(b[2], b[3]), b[3]) for b in pile]


def _appliquer(blocs: list[tuple[Fraction, Fraction, Fraction, int]], score: Fraction) -> Fraction:
    probabilite = blocs[0][2]
    for bas, _, p, _ in blocs:
        if bas <= score:
            probabilite = p
        else:
            break
    return probabilite


def _courbe(probabilites: list[Fraction], issues: list[int]) -> tuple[list[dict[str, Any]], Fraction]:
    tranches: list[list[tuple[Fraction, int]]] = [[] for _ in range(TRANCHES)]
    for p, y in zip(probabilites, issues, strict=True):
        indice = min(TRANCHES - 1, int(p * TRANCHES))
        tranches[indice].append((p, y))
    courbe = []
    ece = Fraction(0)
    for k, contenu in enumerate(tranches):
        entree: dict[str, Any] = {"tranche": f"{k / TRANCHES:.1f}-{(k + 1) / TRANCHES:.1f}", "effectif": len(contenu)}
        if contenu:
            moyenne = sum((p for p, _ in contenu), Fraction(0)) / len(contenu)
            observe = Fraction(sum(y for _, y in contenu), len(contenu))
            entree.update(probabilite_moyenne=_texte(moyenne), frequence_observee=_texte(observe))
            ece += Fraction(len(contenu), len(probabilites)) * abs(moyenne - observe)
        else:
            entree.update(probabilite_moyenne=None, frequence_observee=None)
        courbe.append(entree)
    return courbe, ece


def mesurer(graine: Any = GRAINE_DEFAUT, n: Any = N_DEFAUT) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Le rapport de calibration du modèle courant sur le jeu fictif de `graine` : `(rapport, None)` ou un refus."""
    if type(graine) is not int or not 0 <= graine <= 2**63 - 1 or type(n) is not int or not N_MIN <= n <= N_MAX:
        return None, construire_verdict(
            "REJ-PREV-PARAMETRE-INVALIDE", detail=f"graine entière ≥ 0 et n entre {N_MIN} et {N_MAX} exigés"
        )
    jeu = jeu_fictif(graine, n)
    scores, issues = [], []
    for ligne in jeu:
        resultat, verdict = scoring.calculer(ligne["faits"])
        if verdict is not None:
            return None, verdict
        scores.append(resultat["_score_exact"] / 100)
        issues.append(ligne["issue"])
    entrainement = [(s, y) for i, (s, y) in enumerate(zip(scores, issues, strict=True)) if i % 2 == 0]
    test = [(s, y) for i, (s, y) in enumerate(zip(scores, issues, strict=True)) if i % 2 == 1]
    s_train, y_train = [s for s, _ in entrainement], [y for _, y in entrainement]
    s_test, y_test = [s for s, _ in test], [y for _, y in test]
    blocs = isotone(s_train, y_train, TAILLE_MIN_BLOC)
    calibrees = [_appliquer(blocs, s) for s in s_test]
    taux_base = Fraction(sum(y_train), len(y_train))
    aire = auc(s_test, y_test)
    brier_calibre = brier(calibrees, y_test)
    brier_brut = brier(s_test, y_test)
    brier_reference = brier([taux_base] * len(y_test), y_test)
    courbe_brute, ece_brute = _courbe(s_test, y_test)
    courbe_calibree, ece_calibree = _courbe(calibrees, y_test)
    rapport = {
        "jeu": {
            "nature": "fictif_synthetique",
            "graine": graine,
            "n": n,
            "effectif_entrainement": len(s_train),
            "effectif_test": len(s_test),
            "taux_de_conversion_test": _texte(Fraction(sum(y_test), len(y_test))),
            "taux_de_base_entrainement": _texte(taux_base),
        },
        "modele": {"id": scoring.MODELE_ID, "version": scoring.VERSION, "empreinte": scoring.empreinte_modele()},
        "auc": _texte(aire) if aire is not None else None,
        "brier": {
            "calibre": _texte(brier_calibre),
            "score_brut_sur_100": _texte(brier_brut),
            "reference_taux_de_base": _texte(brier_reference),
            "gain_sur_reference": _texte(1 - brier_calibre / brier_reference) if brier_reference else None,
        },
        "ece": {"brute": _texte(ece_brute), "calibree": _texte(ece_calibree)},
        "courbe_calibration": {"calibree": courbe_calibree, "brute": courbe_brute},
        "calibrateur": {
            "methode": "regression_isotone_pav",
            "taille_min_bloc": TAILLE_MIN_BLOC,
            "blocs": len(blocs),
            "probabilite_min": _texte(blocs[0][2]),
            "probabilite_max": _texte(blocs[-1][2]),
        },
        "valeur_probante": (
            "MÉCANIQUE SEULEMENT : le jeu est synthétique et sa propension de conversion est écrite à la main. Ces "
            "mesures prouvent l'outil de mesure et le calibrateur, pas la capacité du score à prédire de vrais "
            "clients. "
            "Aucune probabilité n'est affirmée pour un vrai lead."
        ),
    }
    return rapport, None
