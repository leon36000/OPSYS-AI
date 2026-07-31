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
"""

import math
import random

from . import contrats, verdicts

__all__ = ["NOMBRE_TIRAGES", "simuler_intervalle"]


# Nombre de tirages de la simulation. Cette valeur est FIXE et n'est PAS
# configurable par l'appelant : un nombre de tirages variable rendrait
# deux estimations incomparables entre elles, puisque la largeur de
# l'intervalle dépendrait alors d'un réglage et non plus seulement du
# barème et de la graine.
NOMBRE_TIRAGES = 10000


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


def simuler_intervalle(bareme, type_travaux, quantite, graine, niveau):
    """Simule un intervalle de coût déterministe pour un type de travaux.

    Paramètres :
        bareme        dict ``{"version", "unite", "postes"}`` ; ``postes``
                      associe à chaque type de travaux couvert un poste
                      ``{"cout_unitaire_min", "cout_unitaire_max"}``.
        type_travaux  type demandé ; doit appartenir au contrat ET être
                      couvert par le barème.
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
    if type_travaux not in contrats.TYPES_TRAVAUX:
        return None, verdicts.construire_verdict(
            "REJ-CONTRAT-INVALIDE",
            "type_travaux hors contrat : " + repr(type_travaux),
        )
    if type_travaux not in postes:
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
    # Le générateur est instancié LOCALEMENT à chaque appel : c'est ce qui
    # garantit que deux appels identiques rendent des bornes égales BIT À
    # BIT et qu'un appel intercalé avec une autre graine ne contamine pas
    # le suivant. Un générateur au niveau du module casserait cette
    # propriété en silence : son état avancerait à chaque appel et l'ordre
    # des appels fuiterait dans les résultats.
    generateur = random.Random(graine)

    echantillon = []
    for _ in range(NOMBRE_TIRAGES):
        cout_unitaire = generateur.uniform(cout_min, cout_max)
        echantillon.append(cout_unitaire * quantite)
    echantillon.sort()

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
