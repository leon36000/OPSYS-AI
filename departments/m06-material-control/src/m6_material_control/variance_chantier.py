"""Moteur de variance de CHANTIER : estimé (M3) vs réel déclaré (formulaire de fin de
chantier, M4) — PLAN T1.1-d, points 2 et 3.

DISTINCT de variance.py (M6-audit.md §3.1/§4) : variance.py compare un comptage
physique au stock théorique dérivé du registre — un audit d'inventaire. Ici, on compare
les besoins matériaux estimés (BesoinEstimeChantier, l'intake M3 -> M6 de M6.4, hors
PLAN T1.1-d, toujours fourni en entrée par l'appelant) au réel déclaré au formulaire de
fin de chantier (materiel.soumettre_materiaux_utilises). Ce module n'écrit JAMAIS le
registre M6 (comme variance.py). Il peut, depuis PLAN T1.1-d2 point 3, le LIRE : le réel
déclaré peut venir soit explicitement (lignes_declarees, `comparer` — module pur, comme
avant), soit relu directement au registre pour un wct_id ou un chantier_id
(`comparer_depuis_registre`, T1.1-d2), au lieu d'être retransporté par l'appelant.

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


def _indetermine(materiau_id, quantite_estimee, quantite_reelle) -> dict:
    # Fail-closed (P2/AGENTS.md) : comparer des quantités d'unités incohérentes (ou
    # inconnues, côté registre — PLAN T1.1-d2) inventerait un écart. On dit ce qui
    # manque (unité cohérente), pas un chiffre.
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


def _verdict_neutre(materiau_id, unite, quantite_estimee, quantite_reelle) -> dict:
    """Verdict neutre pour un matériau dont l'estimé et le réel sont déjà résolus dans
    la MÊME unité (ou dont l'unité est simplement inconnue, PLAN T1.1-d2). Partagé par
    `comparer` (lignes_declarees explicites) et `comparer_depuis_registre` (mouvements
    persistés, qui ne portent pas d'unité)."""
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


def _comparer_materiau(materiau_id, besoin, lignes_declarees) -> dict:
    quantite_estimee = besoin["quantite_estimee"] if besoin else 0.0
    unite_besoin = besoin["unite"] if besoin else None

    quantite_reelle, unite_declaree, unite_ambigue = _quantite_nette_declaree(materiau_id, lignes_declarees)

    unite_incoherente = unite_ambigue or (
        unite_besoin is not None and unite_declaree is not None and unite_besoin != unite_declaree
    )

    if unite_incoherente:
        return _indetermine(materiau_id, quantite_estimee, quantite_reelle)

    return _verdict_neutre(materiau_id, unite_besoin or unite_declaree, quantite_estimee, quantite_reelle)


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


# PLAN T1.1-d2 point 3 : types de mouvement du registre qui composent le « réel déclaré »
# d'un chantier — exactement ceux écrits par materiel.soumettre_materiaux_utilises.
# CONSOMMATION est aussi écrit par l'ancien m6_consommer_materiaux (WCT simple) : cette
# consommation-là compte légitimement dans le réel du chantier au même titre.
_TYPES_MOUVEMENT_REEL_DECLARE = frozenset({"CONSOMMATION", "RETOUR", "PERTE", "BRIS"})


def _quantite_reelle_depuis_registre(chantier_id, materiau_id, wct_id, registre) -> float:
    """Sortie nette (positive = matière sortie) reconstruite depuis les mouvements du
    registre : CONSOMMATION/PERTE/BRIS sont stockés négatifs (materiel.py), RETOUR
    positif — la somme signée négée donne directement la même quantité que
    `_quantite_nette_declaree` calculerait depuis les lignes déclarées d'origine."""
    total_signe = 0.0
    for mouvement in registre.lire():
        if (
            mouvement.get("type_mouvement") in _TYPES_MOUVEMENT_REEL_DECLARE
            and mouvement.get("chantier_id") == chantier_id
            and mouvement.get("materiau_id") == materiau_id
            and (wct_id is None or mouvement.get("wct_id") == wct_id)
        ):
            total_signe += mouvement["quantite"]
    return -total_signe


def comparer_depuis_registre(besoins_estimes, chantier_id, registre, wct_id=None) -> list[dict]:
    """Verdict neutre par matériau (PLAN T1.1-d2 point 3), réel déclaré relu directement
    au registre M6 (persisté par materiel.soumettre_materiaux_utilises) au lieu d'être
    reçu de l'appelant. `wct_id=None` agrège tout le réel déclaré du chantier (toutes
    déclarations confondues) ; un `wct_id` cible une seule déclaration.

    Les nouvelles déclarations conservent leur unité dans le maillon hash-chaîné.
    Une unité absente (historique), mixte ou différente du prévu rend la comparaison
    INDETERMINE : jamais d'unité réelle empruntée au besoin, ni de conversion devinée.
    """
    estimes_par_materiau = {besoin["materiau_id"]: besoin for besoin in besoins_estimes}

    materiaux_declares = {
        mouvement["materiau_id"]
        for mouvement in registre.lire()
        if mouvement.get("type_mouvement") in _TYPES_MOUVEMENT_REEL_DECLARE
        and mouvement.get("chantier_id") == chantier_id
        and (wct_id is None or mouvement.get("wct_id") == wct_id)
    }
    materiaux = sorted(set(estimes_par_materiau) | materiaux_declares)

    verdicts = []
    for materiau_id in materiaux:
        besoin = estimes_par_materiau.get(materiau_id)
        quantite_estimee = besoin["quantite_estimee"] if besoin else 0.0
        unite = besoin["unite"] if besoin else None
        quantite_reelle = _quantite_reelle_depuis_registre(chantier_id, materiau_id, wct_id, registre)
        mouvements = [
            m for m in registre.lire()
            if m.get("type_mouvement") in _TYPES_MOUVEMENT_REEL_DECLARE
            and m.get("chantier_id") == chantier_id and m.get("materiau_id") == materiau_id
            and (wct_id is None or m.get("wct_id") == wct_id)
        ]
        unites = {m.get("unite") for m in mouvements}
        if mouvements and (
            len(unites) != 1 or None in unites
            or any(not isinstance(u, str) or not u.strip() for u in unites)
            or (unite is not None and unites != {unite})
        ):
            verdicts.append(_indetermine(materiau_id, quantite_estimee, quantite_reelle))
        else:
            unite_reelle = next(iter(unites)) if unites else None
            verdicts.append(_verdict_neutre(materiau_id, unite or unite_reelle, quantite_estimee, quantite_reelle))
    return verdicts


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
    lignes_declarees=None,
    seuil_pourcentage=None,
    *,
    registre=None,
    wct_id=None,
) -> tuple[dict | None, str | None]:
    """Orchestrateur PLAN T1.1-d/d2 (points 2 et 3) : valide puis compare. Aucune
    écriture — m6_evaluer_variance_chantier (outils.py) est T0, lecture/calcul pur.

    Deux sources pour le réel déclaré, au choix de l'appelant (PLAN T1.1-d2 point 3) :
    - `lignes_declarees` explicite (appel direct, signature et comportement INCHANGÉS
      depuis PLAN T1.1-d — l'entrée explicite reste disponible, comme demandé) ;
    - `registre` (+ `wct_id` optionnel) : lit le réel déclaré directement au registre M6
      via `comparer_depuis_registre`, sans que l'appelant le retransporte. `lignes_declarees`
      doit alors être omis (None) — les deux sources ne se mélangent jamais dans un même
      appel, pour ne jamais construire un résultat partiellement fourni/partiellement lu.
    """
    if not isinstance(chantier_id, str) or not chantier_id:
        return None, "REJ-VARIANCE-CHANTIER-CHANTIER-MANQUANT"

    ok, code = validation.valider_besoins_estimes_chantier(besoins_estimes)
    if not ok:
        return None, code

    ok, code = validation.valider_seuil_variance_chantier(seuil_pourcentage)
    if not ok:
        return None, code

    if lignes_declarees is not None:
        ok, code = validation.valider_lignes_declarees_chantier(lignes_declarees)
        if not ok:
            return None, code
        verdicts = comparer(besoins_estimes, lignes_declarees)
    elif registre is not None:
        verdicts = comparer_depuis_registre(besoins_estimes, chantier_id, registre, wct_id)
    else:
        return None, "REJ-VARIANCE-CHANTIER-SOURCE-MANQUANTE"

    signal = _construire_signal_si_critique(chantier_id, verdicts, seuil_pourcentage)

    return contrats_sortie.construire_resultat_variance_chantier(verdicts, signal), None


# Référence documentaire : les 6 causes légales (contrats.CAUSES_VARIANCE_CHANTIER) et le
# verdict neutre (contrats.VERDICT_VARIANCE_CHANTIER) vivent dans contrats.py — jamais
# recopiés ici en dur, pour qu'il n'existe qu'une seule source de vérité par valeur.
