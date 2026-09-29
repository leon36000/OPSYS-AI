"""Plaintes et urgences de sécurité (PLAN T4.5, `docs/departements/M1-canaux.md` §10).

Un client qui se plaint, ou qui signale un danger, n'est pas un lead : c'est une personne qu'il faut mettre devant un
humain. Ce module le reconnaît, PAR DES RÈGLES, sur le texte déjà filtré par la provenance, avant toute qualification :

- **Les mots ne sont pas dans ce code.** Le propriétaire les écrit, par catégorie, dans son profil d'entreprise
  (`signaux_plainte`, lu par `opsys.taxonomie`). Ce module ne connaît que les CATÉGORIES (ensemble fermé) et ce que
  chacune déclenche : `securite` est une urgence, les quatre autres sont des plaintes. Sans vocabulaire, le verdict le
  dit (`REJ-SIGNAUX-PLAINTE-NON-CONFIGURES`) et rien n'est reconnu : jamais un mot par défaut.
- **Mêmes règles de lecture que les mots-clés d'un service** : mot entier, pluriel admis, accents et casse ignorés ; un
  terme de plusieurs mots est une expression. Le code lit des mots, pas le sens : « ma voisine est avocate » sonne comme
  une menace, « bravo pour le travail » n'en sonne pas. Le faux positif coûte une lecture humaine ; le faux négatif est
  couvert par le jugement de l'agent (`m1_escalader_plainte`).
- **La plainte prime.** Un message reconnu n'ouvre jamais de lead ; il ouvre un transfert (`transferts.py`).
- **Une urgence de sécurité est escaladée tout de suite** : jamais un conseil de sécurité, jamais une promesse
  d'intervention. Ce n'est pas M1 qui la traite, c'est une personne.

Le gabarit de réponse est un BROUILLON de ton empathique (`brouillon`) : il ne reconnaît aucun tort, ne promet rien,
ne dit rien du droit. Il passe par `garde_fou.verifier_sortie` (prix, date, engagement, aveu) et par une vérification
de l'avis légal, que le garde-fou ne porte pas. Il n'est JAMAIS envoyé ici : l'envoi est `m1_emettre_notification`
(N4, approbation). Une menace juridique n'a pas de brouillon : la réponse est humaine. Le ton du gabarit est une
PROPOSITION que Nathan valide (GATE).

Module pur : aucune horloge, aucun accès à la base ni au réseau.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from opsys import taxonomie

from . import garde_fou, qualification, verdicts

CATEGORIES = taxonomie.CATEGORIES_SIGNAL_PLAINTE
CATEGORIE_URGENCE = "securite"
CATEGORIE_JURIDIQUE = "avocat"
# Comment une catégorie se dit à une personne (le code de la catégorie reste celui du profil).
LIBELLES = {
    "insatisfaction": "insatisfaction",
    "degat": "dégât",
    "garantie": "garantie",
    "avocat": "menace juridique",
    "securite": "sécurité",
}

TYPE_PLAINTE = "plainte"
TYPE_URGENCE = "urgence"

STATUT_NON_CONFIGURE = "vocabulaire_a_configurer"
STATUT_PROFIL_INVALIDE = "profil_invalide"
STATUT_AUCUN_SIGNAL = "aucun_signal"
STATUT_SIGNAL = "signal"

GABARIT_VERSION = "v1"
STATUT_GABARIT = "proposition"  # Nathan valide le ton (GATE) ; tant qu'il ne l'a pas fait, c'est une proposition

# Ce que le client lit, mot pour mot. Aucune excuse (« désolé » reconnaît un tort), aucune promesse ni délai, aucun
# conseil de sécurité (pas même « appelez le 9-1-1 » : c'est une décision de Nathan), rien sur le droit. Un fait
# seulement : le message a été transmis.
GABARIT_PLAINTE = (
    "Bonjour, merci de nous avoir écrit. Nous comprenons que la situation que vous décrivez vous préoccupe. "
    "Votre message a été transmis à une personne de l'équipe."
)
GABARIT_URGENCE = "Bonjour, merci de votre message. Nous l'avons signalé à une personne de l'équipe."

SANS_BROUILLON_RETRAIT = "retrait_consentement"
SANS_BROUILLON_JURIDIQUE = "sujet_legal_reponse_humaine"
SANS_BROUILLON_AUCUN_TYPE = "type_sans_gabarit"

# Ce qu'un texte destiné au client ne doit jamais dire du droit (« M1 ne doit jamais donner un avis légal »). Le
# garde-fou ne couvre que le prix, la date, l'engagement et l'aveu : cette vérification est ajoutée ici, pour le gabarit
# seulement. Lecture en minuscules, accents conservés (les formes avec et sans accent sont listées).
_AVIS_LEGAL = re.compile(
    r"\b(?:"
    r"vous\s+avez\s+(?:le\s+)?droit|vos\s+droits?|selon\s+la\s+loi|en\s+vertu\s+(?:de|du)|"
    r"l[ée]gal(?:e|es|ement)?|ill[ée]gal(?:e|es|ement)?|juridique(?:s|ment)?|tribunal|tribunaux|poursuite(?:s)?|poursuivre|"
    r"recours|mise\s+en\s+demeure|avocat(?:e|s|es)?|code\s+civil|protection\s+du\s+consommateur|"
    r"responsabilit[ée]\s+(?:civile|l[ée]gale|contractuelle)|contractuel(?:le|s|les|lement)?|prescription"
    r")\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Detection:
    """Ce que les règles reconnaissent dans un message. `categories` : dans l'ordre fermé de `CATEGORIES`. `termes` :
    les termes du vocabulaire (écrits par le propriétaire) qui ont été reconnus, par catégorie."""

    statut: str
    categories: tuple[str, ...]
    termes: Mapping[str, tuple[str, ...]]
    non_configurees: tuple[str, ...]
    verdict: dict[str, str] | None

    @property
    def reconnu(self) -> bool:
        return bool(self.categories)

    @property
    def type_transfert(self) -> str | None:
        """`urgence` dès qu'une urgence de sécurité est reconnue (elle prime sur la plainte), sinon `plainte`, sinon
        `None`."""
        return type_de(self.categories) if self.categories else None

    def bloc(self) -> dict[str, Any]:
        """Le bloc `plainte` de la réponse de l'outil : ce qui a été reconnu, ou pourquoi rien ne peut l'être."""
        bloc: dict[str, Any] = {"statut": self.statut, "categories": list(self.categories)}
        if self.termes:
            bloc["termes"] = {c: list(t) for c, t in self.termes.items()}
        if self.non_configurees and self.statut in (STATUT_SIGNAL, STATUT_AUCUN_SIGNAL):
            bloc["categories_non_configurees"] = list(self.non_configurees)
        if self.verdict is not None:
            bloc["verdict"] = self.verdict
        return bloc


def type_de(categories: Sequence[str]) -> str:
    """Le type de transfert d'une liste de catégories : `urgence` si elle porte `securite`, sinon `plainte`."""
    return TYPE_URGENCE if CATEGORIE_URGENCE in categories else TYPE_PLAINTE


def sans_vocabulaire(verdict: dict[str, str] | None) -> Detection:
    """Le vocabulaire est absent ou invalide : rien n'est reconnu, et la réponse le dit (jamais un mot par défaut)."""
    invalide = verdict is not None and verdict["code"] == taxonomie.VERDICT_PROFIL_INVALIDE
    return Detection(STATUT_PROFIL_INVALIDE if invalide else STATUT_NON_CONFIGURE, (), {}, CATEGORIES, verdict)


def detecter(
    contenu_filtre: str, signaux: Mapping[str, Sequence[str]], verdict_profil: dict[str, str] | None = None
) -> Detection:
    """Les catégories que `contenu_filtre` (le texte DÉJÀ passé par la provenance) évoque, d'après `signaux`.

    `signaux`, `verdict_profil` : le résultat de `taxonomie.charger_signaux_plainte()` (l'appelant lit le profil, ce
    module reste pur). Sans vocabulaire, rien n'est reconnu : le statut dit pourquoi et le verdict où l'écrire. Une
    catégorie sans terme ne reconnaît rien ; elle est nommée (`non_configurees`) pour que le propriétaire sache ce
    qui manque.
    """
    if not signaux:
        return sans_vocabulaire(verdict_profil)
    texte = qualification.sans_accent(qualification.contenu_utile(contenu_filtre))
    categories: list[str] = []
    termes: dict[str, tuple[str, ...]] = {}
    for categorie in CATEGORIES:
        reconnus = []
        for terme in signaux.get(categorie, ()):
            motif = qualification.motif_de_termes((terme,))
            if motif is not None and motif.search(texte):
                reconnus.append(terme)
        if reconnus:
            categories.append(categorie)
            termes[categorie] = tuple(reconnus)
    non_configurees = tuple(c for c in CATEGORIES if c not in signaux)
    return Detection(
        STATUT_SIGNAL if categories else STATUT_AUCUN_SIGNAL, tuple(categories), termes, non_configurees, None
    )


def _avis_legal(texte: str) -> bool:
    return _AVIS_LEGAL.search(texte) is not None


def verifier_brouillon(texte: str) -> dict[str, str]:
    """Le verdict d'un texte destiné au client : le garde-fou des interdits (prix, date, engagement, aveu), puis l'avis
    légal, que le garde-fou ne porte pas (`REJ-INTERDIT-AVIS-LEGAL`). `OK` seulement si les deux laissent passer."""
    verdict = garde_fou.verifier_sortie(texte)
    if verdict["code"] != "OK":
        return verdict
    if _avis_legal(texte):
        return verdicts.construire_verdict(
            "REJ-INTERDIT-AVIS-LEGAL", detail="le texte parle de droit : M1 ne donne jamais d'avis légal"
        )
    return verdict


def brouillon(type_transfert: str, categories: Sequence[str], retire: bool) -> dict[str, Any]:
    """Le brouillon de réponse d'une plainte ou d'une urgence : `{brouillon_reponse, envoye: False, gabarit, ...}`.

    `brouillon_reponse` vaut `None` (et `sans_brouillon` dit pourquoi) quand :
    - le client s'est retiré des messages (STOP) : rien ne lui est proposé ;
    - une menace juridique est reconnue : la réponse est humaine, jamais un gabarit ;
    - le type n'a pas de gabarit (seules la plainte et l'urgence en ont un) ;
    - le garde-fou, ou la vérification de l'avis légal, refuse le gabarit (un texte modifié ne doit pas glisser un
      prix, une date, une promesse, un aveu ou un avis légal) : le code du verdict est alors la raison.

    `envoye` vaut TOUJOURS `False` : le brouillon ne part que par `m1_emettre_notification` (N4), après l'approbation
    d'une personne. Le gabarit est une proposition dont Nathan valide le ton.
    """
    resultat: dict[str, Any] = {
        "brouillon_reponse": None,
        "envoye": False,
        "gabarit": {"version": GABARIT_VERSION, "statut_validation": STATUT_GABARIT},
    }
    gabarit = {TYPE_PLAINTE: GABARIT_PLAINTE, TYPE_URGENCE: GABARIT_URGENCE}.get(type_transfert)
    if retire:
        resultat["sans_brouillon"] = SANS_BROUILLON_RETRAIT
    elif CATEGORIE_JURIDIQUE in categories:
        resultat["sans_brouillon"] = SANS_BROUILLON_JURIDIQUE
    elif gabarit is None:
        resultat["sans_brouillon"] = SANS_BROUILLON_AUCUN_TYPE
    else:
        verdict = verifier_brouillon(gabarit)
        if verdict["code"] == "OK":
            resultat["brouillon_reponse"] = gabarit
        else:
            resultat["sans_brouillon"] = verdict["code"]
    return resultat
