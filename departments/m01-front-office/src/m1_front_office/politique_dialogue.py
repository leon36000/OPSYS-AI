"""Politique de dialogue d'un appel de M1 : QUAND continuer, redemander, répondre sûrement, transférer à une personne ou
prendre un message (M1.2, DEFINITION-PRODUIT §7 M1 « Voix : montée en charge sans sauter d'étape »).

CE MODULE NE PROUVE PAS LA VOIX. Il décide à partir d'une transcription déjà écrite et d'une confiance déjà mesurée :
aucun audio, aucun VAD, aucune transcription, aucune synthèse, aucun canal. Il est exercé par le bac à sable textuel
(`bac_a_sable_voix.py`) ; tant qu'aucun moteur vocal réel ne l'appelle, rien d'un vrai appel n'est établi
(`avatars.CANAUX_REALISES` reste `{messagerie}`).

La politique écrite (la définition du produit) tient en deux phrases : « Faible confiance de transcription : redemander.
Deux échecs de compréhension, plainte, sujet légal ou financier, urgence de sécurité : transfert humain immédiat. »
Jusqu'ici
elle n'existait qu'en prose ; ce module en fait des règles pures, ordonnées et testées.

Ordre de préséance (le premier qui s'applique décide ; un échec de compréhension passe APRÈS tout sujet qui exige une
personne, et une confiance faible n'empêche jamais de reconnaître un danger : un faux positif coûte une lecture
humaine) :

1. urgence de sécurité (catégorie `securite` du profil)        -> transfert « urgence », aucun conseil, aucune promesse
2. menace juridique (catégorie `avocat`)                         -> transfert « plainte » (niveau N5, aucun brouillon)
3. plainte (insatisfaction, dégât, garantie)                     -> transfert « plainte »
4. sujet légal (lexique générique ci-dessous)                    -> transfert « propriétaire »
5. sujet financier (lexique générique)                           -> transfert « finance »
6. demande explicite d'une personne                              -> transfert « ventes »
7. échec de compréhension (confiance sous le seuil, silence, ou le répondant n'a pas compris)
                                                                  -> redemander ; au `echecs_max`-ième échec de suite :
                                                                  repli
8. question de prix / de date                                    -> réponse sûre fixe, l'appel continue (jamais un
montant ni une date)
9. sinon                                                         -> le répondant (modèle ou double) parle, GARDE-FOU de
sortie ensuite

Quand aucune personne n'est disponible (`humain_disponible=False`), tout transfert sauf l'urgence de sécurité devient
une
prise de message (« messagerie intelligente » en repli) : la tâche humaine s'ouvre quand même au registre, rien n'est
perdu.

Les MOTS de la plainte et du danger sont ceux du propriétaire (`signaux_plainte` du profil, jamais ici). Le lexique
ci-dessous
(sujets légal et financier, demande d'une personne, questions de prix et de date) est une PROPOSITION du code, écrite à
la main
comme les règles de tri des courriels, générique (aucun métier) et à valider par Nathan ; le seuil de confiance et le
nombre
d'échecs sont des DÉCISIONS de Nathan : `SeuilsDialogue` n'a aucune valeur par défaut. Les échecs comptés sont
CONSÉCUTIFS : un
tour compris remet le compte à zéro (décision à confirmer ; la définition du produit ne dit pas « de suite »).

Module pur : aucune horloge, aucun accès à la base ni au réseau.
"""

from __future__ import annotations

import enum
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from typing import Any

from . import plaintes, qualification

VERSION_POLITIQUE = "v1"
STATUT_POLITIQUE = "proposition"  # Nathan valide les seuils, l'ordre et le lexique (GATE)
PORTEE = (
    "politique de dialogue seulement : aucune voix, aucun audio, aucun canal ; ne fait pas passer M1.2 ni M1.19 "
    "à FAIT_PROUVE"
)


class Action(enum.StrEnum):
    CONTINUER = "continuer"          # le répondant parle (sous garde-fou)
    REPONSE_SURE = "reponse_sure"    # texte fixe de la politique (prix, date) ; l'appel continue
    REDEMANDER = "redemander"        # confiance faible, silence ou incompréhension : première ou deuxième chance
    TRANSFERER = "transferer"        # une personne prend le relais (tâche au registre + remise en direct)
    MESSAGERIE = "messagerie"        # personne de disponible : l'appelant laisse un message, la tâche s'ouvre


class Motif(enum.StrEnum):
    URGENCE_SECURITE = "urgence_securite"
    MENACE_JURIDIQUE = "menace_juridique"
    PLAINTE = "plainte"
    SUJET_LEGAL = "sujet_legal"
    SUJET_FINANCIER = "sujet_financier"
    DEMANDE_HUMAIN = "demande_humain"
    ECHECS_REPETES = "echecs_repetes"
    FAIBLE_CONFIANCE = "faible_confiance"
    SILENCE = "silence"
    INCOMPREHENSION = "incomprehension"
    QUESTION_PRIX = "question_prix"
    QUESTION_DATE = "question_date"
    ORDINAIRE = "ordinaire"


# Ce que dit l'avatar quand la politique décide : des TEXTES FIXES, jamais d'un modèle. Chacun passe le garde-fou des
# interdits (test) : aucun montant, aucune date, aucun engagement, aucun aveu, aucun avis, aucun conseil de sécurité.
TEXTES: Mapping[str, str] = {
    "redemander": "Je n'ai pas bien saisi. Pouvez-vous répéter, s'il vous plaît?",
    "silence": "Êtes-vous toujours là? Je n'ai rien entendu.",
    "prix": ("Je ne peux pas donner de prix au téléphone. L'équipe prépare une estimation à partir des détails de "
             "votre demande."),
    "date": "Je ne peux pas confirmer de date. Je note votre demande pour que l'équipe vous en parle.",
    "transfert": "Je transmets votre appel à une personne de l'équipe.",
    "urgence": "Je signale votre appel à une personne de l'équipe.",
    "messagerie": ("Je ne peux pas vous passer une personne maintenant. Vous pouvez laisser votre nom, votre numéro et "
                   "la raison de votre appel."),
    "cloture": "Merci de votre appel.",
    "sur_repli": "Je préfère noter votre demande pour qu'une personne de l'équipe vous réponde.",
}

# Lexique générique PROPOSÉ (mot entier, pluriel admis, accents et casse ignorés ; plusieurs mots : une expression).
LEXIQUE_V1: Mapping[str, tuple[str, ...]] = {
    "legal": ("contrat", "légal", "légale", "légalement", "juridique", "mes droits", "loi", "assurance", "assurances",
              "responsabilité", "licence"),
    "financier": ("facture", "paiement", "remboursement", "rembourser", "carte de crédit", "virement", "chèque",
                  "financement", "acompte", "solde", "crédit"),
    "humain": ("parler à quelqu'un", "parler à une personne", "parler à un humain", "parler à une vraie personne",
               "parler à un responsable", "parler au responsable", "parler au patron", "parler à la direction",
               "parler à un représentant", "parler à un agent", "passez-moi quelqu'un", "une vraie personne",
               "un humain", "transférez-moi"),
    "prix": ("combien", "prix", "coût", "coûte", "coûter", "tarif", "tarifs", "budget", "à quel prix"),
    "date": ("quand venez-vous", "quand pouvez-vous", "quand est-ce que", "à quelle date", "quelle date",
             "êtes-vous disponible", "pouvez-vous venir"),
}

TYPE_URGENCE = plaintes.TYPE_URGENCE
TYPE_PLAINTE = plaintes.TYPE_PLAINTE
TYPE_PROPRIETAIRE = "proprietaire"
TYPE_FINANCE = "finance"
TYPE_VENTES = "ventes"


@dataclass(frozen=True)
class SeuilsDialogue:
    """Les deux décisions de Nathan, SANS valeur par défaut : la confiance minimale d'une transcription (fraction de 0
    à 1,
    exclue 0) et le nombre d'échecs de compréhension consécutifs qui déclenche le repli (la définition du produit dit
    « deux »)."""

    confiance_minimale: Decimal
    echecs_max: int

    def __post_init__(self) -> None:
        confiance = _decimal(self.confiance_minimale)
        if confiance is None or not Decimal(0) < confiance <= Decimal(1):
            raise ValueError("confiance_minimale : une fraction de 0 (exclu) à 1 est attendue")
        if isinstance(self.echecs_max, bool) or not isinstance(self.echecs_max, int) or not 1 <= self.echecs_max <= 10:
            raise ValueError("echecs_max : un entier de 1 à 10 est attendu")
        object.__setattr__(self, "confiance_minimale", confiance)


def _decimal(valeur: Any) -> Decimal | None:
    """Une confiance valide en `Decimal`, sinon `None` (booléen, texte, NaN, infini, hors de 0 à 1 : aucune)."""
    if isinstance(valeur, bool) or not isinstance(valeur, (int, float, Decimal)):
        return None
    if isinstance(valeur, float) and not math.isfinite(valeur):
        return None
    try:
        decimal = Decimal(str(valeur))
    except InvalidOperation:
        return None
    return decimal if decimal.is_finite() and Decimal(0) <= decimal <= Decimal(1) else None


@dataclass(frozen=True)
class EtatDialogue:
    """Ce que la politique retient d'un tour à l'autre : le nombre d'échecs de compréhension CONSÉCUTIFS."""

    echecs: int = 0


@dataclass(frozen=True)
class Decision:
    action: Action
    motif: Motif
    etat: EtatDialogue
    type_transfert: str | None = None   # pour TRANSFERER et MESSAGERIE : le type de la tâche humaine (ensemble fermé)
    categories: tuple[str, ...] = ()    # catégories du profil reconnues (plainte, urgence)
    texte: str | None = None            # le texte fixe à dire, ou None quand c'est le répondant qui parle

    @property
    def ouvre_une_tache(self) -> bool:
        return self.type_transfert is not None


def confiance_suffisante(confiance: Any, seuils: SeuilsDialogue) -> bool:
    """Vrai si la confiance est valide et au moins égale au seuil (absente ou invalide : faible)."""
    mesuree = _decimal(confiance)
    return mesuree is not None and mesuree >= seuils.confiance_minimale


def sujets(texte: str | None) -> frozenset[str]:
    """Les sujets génériques que le texte évoque (`legal`, `financier`, `humain`, `prix`, `date`), par le lexique."""
    if not isinstance(texte, str) or not texte.strip():
        return frozenset()
    lu = qualification.sans_accent(qualification.contenu_utile(texte))
    trouves = set()
    for sujet, termes in LEXIQUE_V1.items():
        motif = qualification.motif_de_termes(termes)
        if motif is not None and motif.search(lu):
            trouves.add(sujet)
    return frozenset(trouves)


def _transfert(motif: Motif, etat: EtatDialogue, type_transfert: str, humain_disponible: bool,
               categories: tuple[str, ...] = ()) -> Decision:
    if motif is Motif.URGENCE_SECURITE:
        # Un danger n'attend jamais un message : la tâche s'ouvre, l'avatar ne dit qu'un signalement.
        return Decision(Action.TRANSFERER, motif, etat, type_transfert, categories, TEXTES["urgence"])
    if humain_disponible:
        return Decision(Action.TRANSFERER, motif, etat, type_transfert, categories, TEXTES["transfert"])
    return Decision(Action.MESSAGERIE, motif, etat, type_transfert, categories, TEXTES["messagerie"])


def echec_de_comprehension(
    etat: EtatDialogue, seuils: SeuilsDialogue, humain_disponible: bool, motif: Motif
) -> Decision:
    """Un échec de plus (confiance faible, silence, ou répondant qui n'a pas compris) : redemander, ou repli au
    `echecs_max`-ième échec consécutif."""
    echecs = etat.echecs + 1
    suivant = EtatDialogue(echecs)
    if echecs >= seuils.echecs_max:
        return _transfert(Motif.ECHECS_REPETES, suivant, TYPE_VENTES, humain_disponible)
    texte = TEXTES["silence" if motif is Motif.SILENCE else "redemander"]
    return Decision(Action.REDEMANDER, motif, suivant, texte=texte)


def decider(
    texte: str | None,
    confiance: Any,
    etat: EtatDialogue,
    *,
    seuils: SeuilsDialogue,
    signaux_profil: Mapping[str, Sequence[str]],
    verdict_profil: dict[str, str] | None = None,
    humain_disponible: bool,
) -> Decision:
    """La décision pour UN tour de l'appelant.

    `texte` : la transcription (`None` ou vide : silence). `confiance` : celle du moteur de transcription, de 0 à 1 ;
    absente
    ou invalide, elle est traitée comme FAIBLE (fail-closed). `signaux_profil`, `verdict_profil` : le résultat de
    `taxonomie.charger_signaux_plainte()` (l'appelant lit le profil, ce module reste pur) ; sans vocabulaire, plainte et
    danger ne sont pas reconnus (le verdict le dit côté appelant), mais les autres règles s'appliquent.
    """
    if not isinstance(texte, str) or not texte.strip():
        return echec_de_comprehension(etat, seuils, humain_disponible, Motif.SILENCE)

    # 1-3. Le profil du propriétaire : un danger ou une plainte, MÊME si la transcription est peu sûre.
    detection = plaintes.detecter(texte, signaux_profil, verdict_profil)
    if plaintes.CATEGORIE_URGENCE in detection.categories:
        return _transfert(Motif.URGENCE_SECURITE, etat, TYPE_URGENCE, humain_disponible, detection.categories)
    if plaintes.CATEGORIE_JURIDIQUE in detection.categories:
        return _transfert(Motif.MENACE_JURIDIQUE, etat, TYPE_PLAINTE, humain_disponible, detection.categories)
    if detection.reconnu:
        return _transfert(Motif.PLAINTE, etat, TYPE_PLAINTE, humain_disponible, detection.categories)

    # 4-6. Les sujets qui exigent une personne.
    evoques = sujets(texte)
    if "legal" in evoques:
        return _transfert(Motif.SUJET_LEGAL, etat, TYPE_PROPRIETAIRE, humain_disponible)
    if "financier" in evoques:
        return _transfert(Motif.SUJET_FINANCIER, etat, TYPE_FINANCE, humain_disponible)
    if "humain" in evoques:
        return _transfert(Motif.DEMANDE_HUMAIN, etat, TYPE_VENTES, humain_disponible)

    # 7. La compréhension : une confiance absente ou sous le seuil est un échec, jamais un texte à croire.
    if not confiance_suffisante(confiance, seuils):
        return echec_de_comprehension(etat, seuils, humain_disponible, Motif.FAIBLE_CONFIANCE)

    # Tour compris : le compte des échecs consécutifs repart de zéro.
    compris = replace(etat, echecs=0)

    # 8. Prix et date : une réponse sûre fixe ; l'appel continue.
    if "prix" in evoques:
        return Decision(Action.REPONSE_SURE, Motif.QUESTION_PRIX, compris, texte=TEXTES["prix"])
    if "date" in evoques:
        return Decision(Action.REPONSE_SURE, Motif.QUESTION_DATE, compris, texte=TEXTES["date"])

    # 9. Le répondant parle.
    return Decision(Action.CONTINUER, Motif.ORDINAIRE, compris)
