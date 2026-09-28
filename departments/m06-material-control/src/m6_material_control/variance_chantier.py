"""Moteur de variance de CHANTIER : estimé (M3) vs réel déclaré (formulaire de fin de
chantier, M4) — PLAN T1.1-d, points 2 et 3.

DISTINCT de variance.py (M6-audit.md §3.1/§4) : variance.py compare un comptage
physique au stock théorique dérivé du registre — un audit d'inventaire. Ici, on compare
deux structures fournies en entrée par l'appelant : les besoins matériaux estimés
(BesoinEstimeChantier, l'intake M3 -> M6 de M6.4, hors PLAN T1.1-d) et le réel déclaré
au formulaire de fin de chantier (materiel.soumettre_materiaux_utilises). Ce module ne
lit ni n'écrit le registre M6 — module pur, comme variance.py.

Règles dures (DEFINITION-PRODUIT.md §7 M6, « Règles dures », et M6.12 l.515) :
- Le verdict est neutre (AUCUN_ECART/ECART_REEL_SUPERIEUR/ECART_REEL_INFERIEUR/
  NON_UTILISE/NON_PREVU/INDETERMINE, contrats.VERDICT_VARIANCE_CHANTIER).
- `cause_possible` est TOUJOURS None ici. Les 6 valeurs légales
  (contrats.CAUSES_VARIANCE_CHANTIER) ne sont jamais attribuées par ce module : seul un
  humain classe. Un écart non classé donne cause_possible=None et
  classification_requise=True — jamais une classification automatique, jamais le mot ni
  la notion de « vol ».
- Aucun identifiant d'employé n'entre ni ne sort de ce module.
- M6 SIGNALE : SignalVarianceChantierCritique ne modifie jamais le statut d'un chantier
  côté M4 (ça reste la décision de M4, qui consomme le signal — hors PLAN T1.1-d, T1.2).
  Le seuil de criticité est TOUJOURS fourni par l'appelant, jamais codé en dur ici.
"""

from . import contrats_sortie, validation

# Types de ligne (contrats.TYPES_LIGNE_MATERIAUX_UTILISES) qui augmentent la quantité
# réellement sortie pour un matériau. "retour" est le seul type qui la diminue (matériel
# repris, jamais utilisé) — le nom débute par "_" et la valeur est un frozenset() (un
# appel, pas un ast.Set) : conformite.py ne le voit pas comme un énuméré de domaine.
_TYPES_EN_SORTIE_NETTE = frozenset({"prevu", "non_prevu", "achat_terrain", "perte", "bris"})


def _quantite_nette_declaree(materiau_id, lignes_declarees) -> tuple[float, str | None, bool]:
    """Somme les lignes déclarées pour un matériau : sortie nette (prevu/non_prevu/
    achat_terrain/perte/bris) moins les retours. Renvoie aussi l'unité déclarée et si
    elle est ambiguë (plus d'une unité distincte pour le même matériau_id)."""
    total = 0.0
    unites: set[str] = set()

    for ligne in lignes_declarees:
        if ligne["materiau_id"] != materiau_id:
            continue
        unites.add(ligne["unite"])
        if ligne["type_ligne"] in _TYPES_EN_SORTIE_NETTE:
            total += ligne["quantite"]
        elif ligne["type_ligne"] == "retour":
            total -= ligne["quantite"]

    unite = next(iter(unites)) if len(unites) == 1 else None
    unite_ambigue = len(unites) > 1
    return total, unite, unite_ambigue


def _comparer_materiau(materiau_id, besoin, lignes_declarees) -> dict:
    quantite_estimee = besoin["quantite_estimee"] if besoin else 0.0
    unite_besoin = besoin["unite"] if besoin else None

    quantite_reelle, unite_declaree, unite_ambigue = _quantite_nette_declaree(materiau_id, lignes_declarees)

    unite_incoherente = unite_ambigue or (
        unite_besoin is not None and unite_declaree is not None and unite_besoin != unite_declaree
    )

    if unite_incoherente:
        # Fail-closed (P2/AGENTS.md) : comparer des quantités d'unités différentes
        # inventerait un écart. On dit ce qui manque (unité cohérente), pas un chiffre.
        return {
            "materiau_id": materiau_id,
            "unite": None,
            "quantite_estimee": quantite_estimee,
            "quantite_reelle": quantite_reelle,
            "ecart": None,
            "ecart_pourcentage": None,
            "verdict_variance": "INDETERMINE",
            "cause_possible": None,
            "classification_requise": True,
        }

    unite = unite_besoin or unite_declaree
    ecart = quantite_reelle - quantite_estimee

    if quantite_estimee == 0 and quantite_reelle > 0:
        verdict_variance = "NON_PREVU"
    elif quantite_estimee > 0 and quantite_reelle == 0:
        verdict_variance = "NON_UTILISE"
    elif ecart == 0:
        verdict_variance = "AUCUN_ECART"
    elif ecart > 0:
        verdict_variance = "ECART_REEL_SUPERIEUR"
    else:
        verdict_variance = "ECART_REEL_INFERIEUR"

    # Ratio non défini quand rien n'était estimé (division par zéro) : None, jamais une
    # valeur fabriquée (0 ou infini) — cohérent avec le reste du paquet (DA-M6-09).
    ecart_pourcentage = abs(ecart) / quantite_estimee if quantite_estimee > 0 else None

    return {
        "materiau_id": materiau_id,
        "unite": unite,
        "quantite_estimee": quantite_estimee,
        "quantite_reelle": quantite_reelle,
        "ecart": ecart,
        "ecart_pourcentage": ecart_pourcentage,
        "verdict_variance": verdict_variance,
        "cause_possible": None,
        "classification_requise": verdict_variance != "AUCUN_ECART",
    }


def comparer(besoins_estimes, lignes_declarees) -> list[dict]:
    """Verdict neutre par matériau (PLAN T1.1-d point 2). Suppose une entrée déjà
    validée (validation.valider_besoins_estimes_chantier / valider_lignes_declarees_chantier) —
    module pur, comme variance.py."""
    estimes_par_materiau = {besoin["materiau_id"]: besoin for besoin in besoins_estimes}
    materiaux = sorted(
        {besoin["materiau_id"] for besoin in besoins_estimes}
        | {ligne["materiau_id"] for ligne in lignes_declarees}
    )

    return [
        _comparer_materiau(materiau_id, estimes_par_materiau.get(materiau_id), lignes_declarees)
        for materiau_id in materiaux
    ]


def _construire_signal_si_critique(chantier_id, verdicts, seuil_pourcentage) -> dict | None:
    """SignalVarianceChantierCritique (PLAN T1.1-d point 3) : émis seulement quand au
    moins un matériau atteint ou dépasse `seuil_pourcentage` (toujours fourni par
    l'appelant). Un ecart_pourcentage=None (NON_PREVU/INDETERMINE, ratio non défini) ne
    déclenche jamais automatiquement le signal : seul le seuil décide, rien d'autre codé
    en dur. M6 signale seulement ; ce signal ne touche jamais un statut de chantier M4."""
    en_ecart_critique = [
        verdict
        for verdict in verdicts
        if verdict["ecart_pourcentage"] is not None and verdict["ecart_pourcentage"] >= seuil_pourcentage
    ]

    if not en_ecart_critique:
        return None

    return {
        "chantier_id": chantier_id,
        "seuil_pourcentage": seuil_pourcentage,
        "ecart_maximal_pourcentage": max(verdict["ecart_pourcentage"] for verdict in en_ecart_critique),
        "materiaux_en_ecart_critique": sorted(verdict["materiau_id"] for verdict in en_ecart_critique),
        "verdicts_materiaux": verdicts,
    }


def evaluer(
    chantier_id,
    besoins_estimes,
    lignes_declarees,
    seuil_pourcentage,
) -> tuple[dict | None, str | None]:
    """Orchestrateur PLAN T1.1-d (points 2 et 3) : valide puis compare. Aucune écriture —
    m6_evaluer_variance_chantier (outils.py) est T0, lecture/calcul pur."""
    if not isinstance(chantier_id, str) or not chantier_id:
        return None, "REJ-VARIANCE-CHANTIER-CHANTIER-MANQUANT"

    ok, code = validation.valider_besoins_estimes_chantier(besoins_estimes)
    if not ok:
        return None, code

    ok, code = validation.valider_lignes_declarees_chantier(lignes_declarees)
    if not ok:
        return None, code

    ok, code = validation.valider_seuil_variance_chantier(seuil_pourcentage)
    if not ok:
        return None, code

    verdicts = comparer(besoins_estimes, lignes_declarees)
    signal = _construire_signal_si_critique(chantier_id, verdicts, seuil_pourcentage)

    return contrats_sortie.construire_resultat_variance_chantier(verdicts, signal), None


# Référence documentaire : les 6 causes légales (contrats.CAUSES_VARIANCE_CHANTIER) et le
# verdict neutre (contrats.VERDICT_VARIANCE_CHANTIER) vivent dans contrats.py — jamais
# recopiés ici en dur, pour qu'il n'existe qu'une seule source de vérité par valeur.
