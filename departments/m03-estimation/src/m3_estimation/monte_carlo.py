"""Monte Carlo déterministe à graine fournie (cahier M3-S005).

La graine ET le barème viennent de l'appelant : ce module ne possède aucun
modèle de coût propre et n'en invente aucun. Sans barème utilisable —
barème malformé, type de travaux non couvert, bornes incohérentes —
l'estimation est BLOQUÉE par un verdict de rejet plutôt qu'inventée : une
simulation sans modèle sous-jacent produirait des bornes arbitraires,
c'est-à-dire exactement la précision inventée que M3 doit empêcher.

Le déterminisme est bit-à-bit : le générateur pseudo-aléatoire est
``random.Random(graine)``, instancié LOCALEMENT à chaque appel, et le
nombre de tirages est une constante fixe. Deux appels identiques rendent
donc des bornes EXACTEMENT égales, quel que soit l'ordre des appels.

PLAN T4.11 (M3.12, DEFINITION-PRODUIT « P50, P80 ») — deux ajouts, qui ne
changent rien à ce que ce module rendait avant :

- ``simuler_quantiles`` lit d'autres rangs du MÊME échantillon que
  ``simuler_intervalle`` : même générateur local, même graine, même loi, même
  tri, même convention de rang que la borne haute de l'intervalle
  (``ceil(p x (n - 1))``). Ce n'est pas une seconde simulation qui pourrait
  dériver de la première : les deux fonctions appellent ``_echantillon_trie``.
- un poste du barème qui porte ``cout_unitaire_mode`` est tiré en PERT (loi
  bêta d'un mode fourni) ; sans mode, le tirage reste UNIFORME, bit à bit comme
  avant. Le mode est une donnée du barème, jamais inventée : fourni de travers
  (hors des bornes, non numérique), il est refusé, jamais ignoré.
"""

import math
import random

from . import contrats, verdicts

__all__ = ["NOMBRE_TIRAGES", "POIDS_DU_MODE_PERT", "lire_poste", "simuler_intervalle", "simuler_quantiles"]


# Nombre de tirages de la simulation. Cette valeur est FIXE et n'est PAS
# configurable par l'appelant : un nombre de tirages variable rendrait
# deux estimations incomparables entre elles, puisque la largeur de
# l'intervalle dépendrait alors d'un réglage et non plus seulement du
# barème et de la graine.
NOMBRE_TIRAGES = 10000

# Poids du mode dans la loi PERT : moyenne = (min + 4 x mode + max) / 6, et
# les deux paramètres de la bêta valent 1 + 4 x (distance au mode) / étendue.
# 4 est la définition de la loi PERT, pas un réglage : un autre poids
# donnerait une autre loi que celle que le barème annonce en parlant de PERT.
POIDS_DU_MODE_PERT = 4.0


def _est_nombre_fini(valeur):
    """Vrai pour un int ou un float FINI qui n'est PAS un booléen.

    ``isinstance(True, int)`` est vrai en Python : sans exclusion
    explicite, un booléen passerait pour un nombre partout où un nombre
    est attendu. Un float infini ou NaN n'est pas un coût ni une
    quantité défendable : il est refusé ici, une seule fois.
    """
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float)):
        return False
    if isinstance(valeur, int):
        return True
    return math.isfinite(valeur)


def _echantillon_trie(parametres, quantite, graine):
    """L'échantillon trié des coûts, tiré UNE seule fois pour toute la simulation.

    ``simuler_intervalle`` et ``simuler_quantiles`` l'appellent toutes les deux : ce sont les MÊMES tirages, par
    construction, jamais deux boucles qui pourraient dériver l'une de l'autre. Loi UNIFORME sans mode (comme avant,
    bit à bit), loi PERT avec le mode du poste.
    """
    cout_min = parametres["cout_min"]
    cout_max = parametres["cout_max"]
    mode = parametres["mode"]

    # Les deux paramètres de la bêta PERT. Un coût fixe (étendue nulle) n'a pas de forme à donner : (1, 1), et le
    # tirage vaut alors exactement cout_min.
    etendue = cout_max - cout_min
    if mode is None or etendue == 0:
        alpha = beta = 1.0
    else:
        alpha = 1.0 + POIDS_DU_MODE_PERT * (mode - cout_min) / etendue
        beta = 1.0 + POIDS_DU_MODE_PERT * (cout_max - mode) / etendue

    # Le générateur est instancié LOCALEMENT à chaque appel : c'est ce qui
    # garantit que deux appels identiques rendent des résultats égaux BIT À
    # BIT et qu'un appel intercalé avec une autre graine ne contamine pas
    # le suivant. Un générateur au niveau du module casserait cette
    # propriété en silence : son état avancerait à chaque appel et l'ordre
    # des appels fuiterait dans les résultats.
    generateur = random.Random(graine)

    echantillon = []
    for _ in range(NOMBRE_TIRAGES):
        if mode is None:
            cout_unitaire = generateur.uniform(cout_min, cout_max)
        else:
            cout_unitaire = cout_min + etendue * generateur.betavariate(alpha, beta)
        echantillon.append(cout_unitaire * quantite)
    echantillon.sort()
    return echantillon


def lire_poste(bareme, type_travaux, services=()):
    """Lit et valide le poste du barème d'un type de travaux ou d'un service.

    Rend ``(parametres, None)`` où ``parametres`` porte EXACTEMENT ``cout_min``, ``cout_max`` et ``mode`` (``None``
    quand le barème ne fournit pas de ``cout_unitaire_mode`` : jamais une valeur par défaut) ; ou ``(None, verdict)``
    avec un code du catalogue fermé M3. C'est la validation que ``simuler_intervalle`` et ``simuler_quantiles``
    partagent et que les autres modules appellent pour lire un poste sans la récrire (``scenarios.py``). Même barème,
    mêmes ``services`` : mêmes refus, dans le même ordre. Aucune exception ne s'échappe.
    """
    # --- 1. Structure du barème ----------------------------------------
    # Empêche : un barème absent, non dictionnaire ou amputé de l'une de
    # ses trois clés d'être lu par accident plus bas — un KeyError ou un
    # TypeError échappé à l'appelant serait un plantage, pas un rejet
    # NOMMÉ. Un ``postes`` vide ne couvre par construction aucun type.
    if not isinstance(bareme, dict):
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE", "barème absent ou non dictionnaire"
        )
    if any(cle not in bareme for cle in ("version", "unite", "postes")):
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            "barème incomplet : clés version, unite et postes exigées",
        )
    postes = bareme["postes"]
    if not isinstance(postes, dict) or not postes:
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            "postes absent, non dictionnaire ou vide",
        )

    # --- 2. Couverture du type de travaux (CA-M3-21) -------------------
    # Empêche : l'extrapolation depuis un autre poste ou des bornes par
    # défaut. Un type_travaux absent du barème rend l'estimation
    # IMPOSSIBLE : on rejette, on n'invente jamais un modèle de coût.
    est_service = type_travaux not in contrats.TYPES_TRAVAUX
    if est_service and type_travaux not in services:
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            "type_travaux hors contrat : " + repr(type_travaux),
        )
    if type_travaux not in postes:
        if est_service:
            return None, verdicts.construire_verdict(
                "REJ-CONTRAT-INVALIDE",
                "barème du service " + repr(type_travaux) + " absent : à fournir",
            )
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            "barème sans poste pour le type demandé : "
            + repr(type_travaux),
        )

    # --- 3. Bornes du poste --------------------------------------------
    # Empêche : un poste sans clés de coût, à valeurs non numériques ou
    # non finies, ou dont min > max, de produire un intervalle inversé ou
    # arbitraire. Le cas min == max (coût fixe) est LÉGITIME : il n'est
    # pas rejeté et produit un intervalle dégéné valide.
    poste = postes[type_travaux]
    if not isinstance(poste, dict):
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            "poste non dictionnaire pour : " + repr(type_travaux),
        )
    if "cout_unitaire_min" not in poste or "cout_unitaire_max" not in poste:
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            "poste sans cout_unitaire_min ou cout_unitaire_max",
        )
    cout_min = poste["cout_unitaire_min"]
    cout_max = poste["cout_unitaire_max"]
    if not _est_nombre_fini(cout_min) or not _est_nombre_fini(cout_max):
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            "bornes de coût non numériques, booléennes ou non finies",
        )
    if cout_min > cout_max:
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            "bornes incohérentes : cout_unitaire_min > cout_unitaire_max",
        )

    # --- 3 bis. Mode du poste (optionnel) -------------------------------
    # Empêche : un mode fourni de travers d'être ignoré en silence — le
    # tirage retomberait sur l'uniforme alors que le barème croit parler de
    # PERT — ou de produire une bêta de paramètres négatifs, donc un tirage
    # hors des bornes du barème, c'est-à-dire un coût inventé. Le mode est
    # OPTIONNEL : absent, le poste reste tiré en uniforme ; PRÉSENT, il doit
    # être valide (même discipline que duree_minutes_par_unite ailleurs dans
    # ce paquet). Un null explicite est un mode fourni de travers.
    mode = None
    if "cout_unitaire_mode" in poste:
        mode = poste["cout_unitaire_mode"]
        if not _est_nombre_fini(mode):
            return None, verdicts.construire_verdict(
                "REJ-CONTRAT-INVALIDE",
                "cout_unitaire_mode non numérique, booléen ou non fini",
            )
        if not cout_min <= mode <= cout_max:
            return None, verdicts.construire_verdict(
                "REJ-CONTRAT-INVALIDE",
                "cout_unitaire_mode hors des bornes : cout_unitaire_min <= mode <= cout_unitaire_max exigé",
            )
    return {"cout_min": cout_min, "cout_max": cout_max, "mode": mode}, None


def _preparer(bareme, type_travaux, quantite, graine, services):
    """Étapes 1 à 5 des deux simulations : le poste, la quantité, la graine (le niveau, propre à l'intervalle, suit)."""
    parametres, verdict = lire_poste(bareme, type_travaux, services)
    if verdict is not None:
        return None, verdict

    # --- 4. Quantité ----------------------------------------------------
    # Empêche : zéro écrasant l'intervalle à 0, un négatif l'inversant, un
    # booléen passant pour un entier (isinstance(True, int) est vrai), ou
    # une valeur non finie rendant des bornes infinies présentées comme
    # un chiffrage.
    if not _est_nombre_fini(quantite) or quantite <= 0:
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            "quantite invalide : nombre fini strictement positif exigé",
        )

    # --- 5. Graine -------------------------------------------------------
    # Empêche : une graine flottante, qui rendrait la reproductibilité
    # bit-à-bit dépendante de la représentation interne du flottant, et un
    # booléen, qui EST un entier pour isinstance et seederait en silence
    # avec 0 ou 1.
    if isinstance(graine, bool) or not isinstance(graine, int):
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            "graine invalide : entier non booléen exigé",
        )

    return parametres, None


def simuler_intervalle(bareme, type_travaux, quantite, graine, niveau, services=()):
    """Simule un intervalle de coût déterministe pour un type de travaux ou un service.

    Paramètres :
        bareme        dict ``{"version", "unite", "postes"}`` ; ``postes``
                      associe à chaque type de travaux couvert un poste
                      ``{"cout_unitaire_min", "cout_unitaire_max"}`` et, en
                      option, ``cout_unitaire_mode`` (tirage PERT ; absent,
                      tirage uniforme).
        type_travaux  type demandé ; doit appartenir au contrat ET être
                      couvert par le barème. Un type de travaux v1 est reconnu
                      par l'énuméré gelé ; un SERVICE (lead v2, PLAN T0.13) l'est
                      seulement s'il figure dans ``services`` : l'appelant (qui a
                      validé le lead contre la taxonomie du socle) les fournit, ce
                      module ne lit aucun profil et reste pur et déterministe.
        services      codes de service déjà validés par l'appelant (défaut : aucun).
        quantite      nombre strictement positif (booléens refusés).
        graine        entier (booléens refusés) seedant le générateur.
        niveau        flottant strictement entre 0 et 1, bornes exclues.

    Retour :
        ``(intervalle, None)`` où ``intervalle`` porte EXACTEMENT les trois
        clés ``borne_basse`` (float), ``borne_haute`` (float) et ``niveau``
        (float, EXACTEMENT celui fourni) ; ou ``(None, verdict)`` avec un
        code du catalogue fermé M3 si une entrée est invalide. Aucune
        exception ne s'échappe : le contrat est fail-closed.
    """
    parametres, verdict = _preparer(bareme, type_travaux, quantite, graine, services)
    if verdict is not None:
        return None, verdict

    # --- 6. Niveau -------------------------------------------------------
    # Empêche : un niveau à 0 ou 1, qui produirait un intervalle dégénéré
    # présenté comme un taux de confiance, un niveau hors de ]0, 1[, qui
    # n'a aucun sens statistique, et un booléen, refusé explicitement.
    if (
        isinstance(niveau, bool)
        or not isinstance(niveau, float)
        or not 0.0 < niveau < 1.0
    ):
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            "niveau invalide : flottant strictement entre 0 et 1 exigé",
        )

    # --- Simulation ------------------------------------------------------
    # L'échantillon est celui que ``simuler_quantiles`` lit aussi (voir
    # ``_echantillon_trie`` : générateur local, graine fournie, tri).
    echantillon = _echantillon_trie(parametres, quantite, graine)
    cout_min = parametres["cout_min"]
    cout_max = parametres["cout_max"]

    # Intervalle symétrique : les queues basse et haute laissent chacune
    # (1 - niveau) / 2 de l'échantillon à l'extérieur.
    alpha = (1.0 - niveau) / 2.0
    indice_max = NOMBRE_TIRAGES - 1
    indice_bas = min(max(int(alpha * indice_max), 0), indice_max)
    indice_haut = min(
        max(math.ceil((1.0 - alpha) * indice_max), 0), indice_max
    )
    borne_basse = echantillon[indice_bas]
    borne_haute = echantillon[indice_haut]

    # Contrainte NON NÉGOCIABLE : les bornes rendues restent DANS les
    # bornes du barème. Un tirage qui en sortirait INVENTERAIT un coût que
    # le barème ne couvre pas — de la précision inventée chiffrée. Chaque
    # tirage étant par construction dans [min, max] * quantite, ce bornage
    # ne corrige que d'éventuels dépassements d'un chiffre binaire liés à
    # l'arrondi des flottants ; il ne déplace jamais l'intervalle.
    plancher = cout_min * quantite
    plafond = cout_max * quantite
    if borne_basse < plancher:
        borne_basse = plancher
    if borne_haute > plafond:
        borne_haute = plafond

    intervalle = {
        "borne_basse": float(borne_basse),
        "borne_haute": float(borne_haute),
        # Le niveau rendu est EXACTEMENT celui fourni : arrondi, plafonné
        # ou recalculé, il étiquetterait l'intervalle avec un taux qui
        # n'est pas celui demandé — de la précision inventée.
        "niveau": float(niveau),
    }
    return intervalle, None


def simuler_quantiles(bareme, type_travaux, quantite, graine, probabilites, services=()):
    """Quantiles du coût sur les MÊMES tirages que ``simuler_intervalle`` (PLAN T4.11, P50 et P80).

    Paramètres : ceux de ``simuler_intervalle`` sauf ``probabilites`` (à la place de ``niveau``) : liste ou tuple
    NON VIDE de flottants strictement entre 0 et 1, bornes exclues, booléens et entiers refusés — par exemple
    ``(0.5, 0.8)`` pour P50 et P80.

    Retour : ``(valeurs, None)`` où ``valeurs`` est un tuple de floats, dans l'ordre des probabilités demandées ; ou
    ``(None, verdict)`` avec un code du catalogue fermé M3. Aucune exception ne s'échappe.

    Le rang lu est ``ceil(p x (n - 1))``, celui de la borne haute de l'intervalle : le quantile de probabilité
    ``1 - (1 - niveau) / 2`` égale donc EXACTEMENT la borne haute de l'intervalle de ce niveau (P80 est la borne haute
    de l'intervalle à 60 %). Les valeurs restent dans les bornes du barème, comme celles de l'intervalle.
    """
    parametres, verdict = _preparer(bareme, type_travaux, quantite, graine, services)
    if verdict is not None:
        return None, verdict

    # --- Probabilités ----------------------------------------------------
    # Empêche : une liste vide (aucune réponse, présentée comme un succès), une probabilité à 0 ou à 1 (le minimum
    # ou le maximum du barème présenté comme un quantile), hors de ]0, 1[, NaN, booléenne ou entière (même règle
    # que le niveau de l'intervalle : ni un booléen ni un entier n'est un flottant), et un scalaire ou un texte
    # pris pour une liste de probabilités.
    if (
        not isinstance(probabilites, (list, tuple))
        or not probabilites
        or any(not isinstance(p, float) or not 0.0 < p < 1.0 for p in probabilites)
    ):
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            "probabilites invalides : liste non vide de flottants strictement entre 0 et 1 exigée",
        )

    echantillon = _echantillon_trie(parametres, quantite, graine)
    indice_max = NOMBRE_TIRAGES - 1
    plancher = parametres["cout_min"] * quantite
    plafond = parametres["cout_max"] * quantite
    valeurs = []
    for probabilite in probabilites:
        indice = min(max(math.ceil(probabilite * indice_max), 0), indice_max)
        # Même bornage au barème que l'intervalle : un quantile hors des bornes inventerait un coût.
        valeurs.append(float(min(max(echantillon[indice], plancher), plafond)))
    return tuple(valeurs), None
