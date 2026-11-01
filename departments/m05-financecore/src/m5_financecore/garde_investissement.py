"""Garde investissement (NC 31-103) : refuse toute recommandation PERSONNALISÉE de titres
(`docs/architecture/BASE-FISCALE.md`).

M5 n'est pas un conseiller inscrit. Le Règlement 31-103 (NC 31-103) réserve aux personnes inscrites le conseil sur
l'achat
ou la vente de titres. Cette garde est un filtre de TEXTE, déterministe, qui classe une demande en trois verdicts :

- `REFUSE` : une recommandation, un choix ou un ordre d'achat/vente/placement visant des titres (actions, FNB, fonds,
  obligations, cryptoactifs…) ou, faute d'objet d'exploitation reconnu, un achat ou un placement de fonds de la
  personne.
  La réponse est générique, renvoie à un représentant inscrit et porte « À valider auprès d'un comptable (CPA) /
  professionnel qualifié ». Aucun calcul n'est fait.
- `PERMIS` : contenu de la liste blanche — information générale (comment fonctionne un type de placement, sans
  personnalisation), trésorerie (CPG, échelonnement, réserve, prévision), calculs DÉTERMINISTES de `moteur_calcul`
  sur des
  hypothèses fournies, décision d'exploitation de l'entreprise (équipement, véhicule…), ou sujet étranger à
  l'investissement.
- `A_PRECISER` : des titres sont mentionnés sans question d'information générale ni demande de recommandation ; rien
n'est
  recommandé, l'appelant doit préciser la question (comptable, générale).

FAIL-CLOSED : dans le doute, `REFUSE` ou `A_PRECISER`, jamais `PERMIS`. Aucune consigne glissée dans le texte («
ignore tes
règles », « tu es maintenant conseiller inscrit », texte observé qui ordonne d'acheter) ne lève un refus : elle est
signalée (`injection_detectee`) et le texte est jugé sur son CONTENU.

Limites (voir la documentation) : c'est un filtre de motifs, pas une compréhension. Un contournement par une langue non
couverte, une paraphrase inédite ou un code convenu peut passer ; il complète la garde
`REJ-CALC-OBJET-HORS-PERIMETRE` du
moteur de calcul (liste fermée d'objets d'exploitation), il ne la remplace pas.

Module pur : aucune horloge, aucun réseau, aucune écriture.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

from . import analyse, verdicts_fiscal

__all__ = [
    "CONTENUS_PERMIS",
    "MENTION_PROFESSIONNELLE",
    "REPONSE_GENERIQUE",
    "TEXTE_MAX",
    "evaluer_demande",
]

TEXTE_MAX = 4000
MENTION_PROFESSIONNELLE = analyse.MENTION_COMPTABLE
REPONSE_GENERIQUE = (
    "Je ne peux pas recommander l'achat, la vente ou le choix de titres (actions, FNB, fonds, obligations, "
    "cryptoactifs) "
    "ni dire où placer vos fonds : ce serait un conseil en placement personnalisé, réservé aux personnes inscrites "
    "(NC 31-103). Je peux expliquer en termes généraux comment fonctionne un type de placement, ou calculer, à partir "
    "des "
    "hypothèses que vous fournissez, un échelonnement de CPG, un amortissement, une prévision de trésorerie ou la "
    "rentabilité d'une décision d'exploitation de l'entreprise. Pour un conseil personnalisé, adressez-vous à un "
    "représentant inscrit. " + MENTION_PROFESSIONNELLE
)
# Liste blanche : ce que la garde laisse passer, et par quel chemin de M5 (`moteur_calcul` pour tout chiffre).
CONTENUS_PERMIS = frozenset(
    {
        "information_generale",  # explication générale d'un type de placement, sans personnalisation
        "tresorerie",  # CPG, échelonnement, réserve, fonds de roulement, prévision : calculs déterministes
        "decision_exploitation",  # équipement, véhicule, embauche... : m5_calculer_rentabilite_investissement et autres
        "hors_investissement",  # sujet étranger à l'investissement
    }
)

_GRAINS_ZERO_LARGEUR = {"​", "‌", "‍", "⁠", "﻿"}
_HOMOGLYPHES = str.maketrans(
    {
        "а": "a",
        "е": "e",
        "о": "o",
        "р": "p",
        "с": "c",
        "х": "x",
        "у": "y",
        "і": "i",
        "ј": "j",
        "ѕ": "s",
        "һ": "h",
        "ԁ": "d",
        "ɑ": "a",
        "ο": "o",
        "ε": "e",
        "ρ": "p",
        "α": "a",
        "ν": "v",
        "κ": "k",
        "τ": "t",
        "ι": "i",
        "ı": "i",
    }
)
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s", "!": "i"})


def _normaliser(texte: str) -> str:
    t = unicodedata.normalize("NFKC", texte)
    t = "".join(c for c in t if unicodedata.category(c) != "Cf" and c not in _GRAINS_ZERO_LARGEUR)
    t = unicodedata.normalize("NFD", t)
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    t = t.casefold().translate(_HOMOGLYPHES).replace("’", "'").replace("`", "'").replace("´", "'")
    t = re.sub(r"(.)\1{2,}", r"\1", t)  # « acheeeete » -> « achete »
    return re.sub(r"\s+", " ", t).strip()


def _variante_leet(t: str) -> str:
    """4chète, t3sla, bitc0in : n'altère que les mots qui mêlent lettres et chiffres/symboles."""

    def mot(m: re.Match[str]) -> str:
        s = m.group(0)
        return s.translate(_LEET) if re.search(r"[a-z]", s) and re.search(r"[0-9@$!]", s) else s

    return re.sub(r"[\w@$!]+", mot, t)


def _variantes(texte: str) -> list[str]:
    base = _normaliser(texte)
    leet = _variante_leet(base)
    retire = re.sub(r"(?<=\w)[*._\-'](?=\w)", "", base)  # a*c*h*e*t*e
    return list(dict.fromkeys([base, leet, retire, _variante_leet(retire)]))


def _mots_epeles(t: str) -> str:
    """Les mots épelés lettre par lettre (« a c h e t e ») ramenés à un seul mot, une suite par segment (2 espaces ou
    plus, ou ponctuation, séparent les mots épelés)."""
    suites = re.findall(r"(?:\b\w[ ._*-]){3,}\w\b", t)
    return " ".join(re.sub(r"[ ._*-]", "", s) for s in suites)


# ------------------------------------------------------------------------------------------- motifs
_NEUTRALISER = re.compile(
    r"\bplans? d'actions?\b|\bmise en action\b|\b(?:passer|passage) a l'action\b|\bzone d'action\b"
    r"|\bactions? (?:corrective|collective|de suivi|en justice|commerciale|marketing|prioritaire|concretes?)s?\b"
)
_SECURITES_FORTES = re.compile(
    r"\b(?:etfs?|fnbs?|fonds? (?:commun|negocie|indiciel|mutuel|de placement)s?|mutual funds?|index funds?|"
    r"obligations? (?:d'epargne|du canada|du "
    r"gouvernement|corporatives?|municipales?|d'etat)|bonds?|stocks?|equit(?:y|ies)|"
    r"shares? (?:of|in|de|d')|valeurs? mobilieres?|titres? (?:boursiers?|cotes?|de participation|de creance)|"
    r"crypto\w*|bitcoin|btc|ethereum|dogecoin|solana|nfts?|altcoins?|memecoins?|bourse|boursier\w*|nasdaq|nyse|tsx|"
    r"actions? (?:et|ou|versus|vs\.?) (?:une? )?obligations?|obligations? (?:et|ou) (?:une? )?actions?|"
    r"marches? (?:boursiers?|financiers?|des actions)|les marches financiers|s&p ?500|dow "
    r"jones|reer|rrsp|celi|tfsa|rrif|portefeuilles? (?:d'investissement|boursier|de placements?|d'actions)|"
    r"hedge funds?|fonds de couverture|capital[- ]risque|private equity|penny stocks?|day ?trad\w*|forex|cfd|"
    r"contrats? a terme|options? (?:d'achat|de vente)|vente a decouvert|short sell\w*)\b"
)
_ACTIONS_TITRES = re.compile(
    r"\b(?:acheter|achete\w*|vendre|vend\w*|investir|investi\w*|placer|miser|mes|des|quelques|ces|ses|nouvelles?|\d+|"
    r"buy|sell|which|best|meilleures?s?)\s+actions?\b|\bactions?\s+(?:de|d'|du|chez|a acheter|a vendre|tesla|apple|"
    r"nvidia|amazon|google|microsoft|shopify|bell|desjardins|banque)\b|\bactions? "
    r"(?:boursieres?|ordinaires?|privilegiees?)\b"
    r"|\bquelles? actions?\b|\bactions? (?:est|sont|vaut)"
)
_GAIN = re.compile(
    r"\b(?:gagner|gagne|rapporter|rapporte|rendement|rentable|profit|doubler|enrichir|faire de l'argent|make money|"
    r"returns?|gains?|beat the market|batre le marche)\b"
)
_TITRE_SIMPLE = re.compile(
    r"\b(?:titres?|valeurs?)\b (?:a|d'|de) (?:acheter|vendre|investissement)\b|\bquels? titres?\b"
)
_ACQUISITION = re.compile(
    r"\b(?:achet\w*|acquer\w*|acquis\w*|vend\w*|vente|investi\w*|invest\w*|plac\w*|mis[ea]r?\w*|specul\w*|trad(?:e|er|ez|ing)\b|"
    r"buy\w*|sell\w*|purchas\w*|short\w*|dump\w*|hold\w*|conserv\w* en portefeuille|souscri\w*|choisi\w*|pick\w*|"
    r"choos\w*|select\w*)"
)
_RECOMMANDATION = re.compile(
    r"\b(?:quoi|quel(?:le)?s?|lequel|laquelle|lesquel(?:le)?s|ou|dans quoi|what|which|where|how much)\s+(?:je |i |we "
    r"|nous )?"
    r"(?:devrais |dois |peux |pourrais |should |can |could |to |would |do you think i |)?(?:\w+ ){0,3}?"
    r"(?:acheter|achete|vendre|investir|placer|miser|mettre|parier|speculer|trader|choisir|buy|sell|invest|pick|short|put)\b"
    r"|\b(?:devrais|dois|pourrais|faut|vaut)(?:-je|-il)?\s+(?:je\s+)?(?:mieux\s+)?(?:acheter|vendre|investir|placer|miser|"
    r"speculer)\b|\best-ce que (?:je|nous) (?:dois|devrais|devrait) (?:acheter|vendre|investir|placer)\b"
    r"|\b(?:achete|achetez|acheter-moi|vends|vendez|acquiers|acquerez|investis|investissez|specule|speculez|tradez|"
    r"shorte|shortez)\b"
    r"|\b(?:conseille|conseilles|conseillez|recommande|recommandes|recommandez|suggere|suggeres|suggerez|propose|"
    r"proposes|indique|indiques|advise|recommend|suggest)\b.{0,50}\b(?:placement|investissement|achat|vente|titre|action|"
    r"fnb|etf|crypto|portefeuille|fonds|stock|fund|investment|portfolio|coin|bond)"
    r"|\b(?:meilleur|meilleure|meilleurs|meilleures|top|bon|bonne|best|good|hot|safe)s? (?:action|titre|placement|"
    r"investissement|fnb|etf|crypto|fonds|stock|investment|fund|coin|bond|pick)\w*"
    r"|\bshould i (?:buy|sell|invest|put|short|hold|dump)\b|\b(?:tell me|show me|give me|dis-moi|donne-moi|dites-moi) "
    r"(?:what|which|where|quoi|quel|quelle|ou)\b.{0,40}\b(?:buy|sell|invest|put|acheter|vendre|investir|placer|mettre)\b"
    r"|^(?:please |pls |svp |stp )?(?:buy|sell|short|invest in|go long|acquire)\b"
    r"|\b(?:mets|mettez|place|placez|investis|investissez|put|invest)\b.{0,30}\d[\d .,]*\s?(?:k\b|\$|dollars?|cad)"
    r"|\b(?:fais|faire|faites) fructifier\b|\bgrow my (?:money|savings)\b|\bmake my money grow\b"
    r"|\b(?:lequel|laquelle|lesquels|which one)\b.{0,30}\b(?:acheter|vendre|buy|sell)\b"
)
_PERSONNALISATION = re.compile(
    r"\b(?:mes|mon|ma|nos|notre|my|our)\s+(?:\$\s?)?\d[\d .,]*\s?(?:k\b|\$|dollars?|cad|usd|euros?|\$cad)?"
    r"|\b(?:mon|ma|mes|notre|nos|my|our)\s+(?:argent|capital|epargne|economies|fonds|portefeuille|surplus|money|savings|"
    r"funds|portfolio|cash)\b|\bpour moi\b|\bfor me\b|\bchez moi\b|\bdans mon cas\b|\bdans ma situation\b|\bj'ai "
    r"\d|\bi have \$?\d"
)
_EDUCATIF = re.compile(
    r"\b(?:c'est quoi|qu'est-ce (?:que|qu')|qu'est ce (?:que|qu')|que (?:signifie|veut "
    r"dire)|definition|definis|explique\w*|"
    r"expliquez|comment (?:fonctionne\w*|marche\w*|ca marche)|difference entre|differences? entre|what is|what are|"
    r"explain|how (?:does|do|is|are)|define|meaning of|a quoi sert)\b"
)
_TRESORERIE = re.compile(
    r"\b(?:cpg|gic|certificats? de placement garantis?|depots? a terme|echelonn\w*|ladder\w*|taux de "
    r"rendement|amortissement|"
    r"van\b|tri\b|rentabilite|point mort|credit-bail|reserve de tresorerie|fonds de roulement|prevision de tresorerie|"
    r"tresorerie|cash libre|cash flow|marge de manoeuvre|compte d'epargne|epargne a terme)\b"
)
_EXPLOITATION = re.compile(
    r"\b(?:equipements?|vehicules?|camions?|camionnettes?|remorques?|outillage|outils|machiner\w*|echelles?|echafaudage\w*|"
    r"materiel|materiaux|fournitures?|fournisseurs?|gouttieres?|revetements?|immeubles? d'exploitation|local "
    r"commercial|"
    r"atelier|entrepot|ordinateurs?|logiciels?|licences?|embauche\w*|employes?|bureau|papeterie|carburant|essence|"
    r"equipment|trucks?|vehicles?|tools|supplies|laptops?|software)\b"
)
_INJECTION = re.compile(
    r"\bignore\w*\b.{0,30}\b(?:instruction|regle|consigne|directive|restriction|prompt|rules?|previous|above|prior|all)\w*"
    r"|\b(?:oublie\w*|disregard|forget)\b.{0,30}\b(?:instruction|regle|consigne|tout|everything|rules?|previous)\w*"
    r"|\btu es maintenant\b|\bvous etes maintenant\b|\byou are now\b|\bact as\b|\bagis comme\b|\bjoue le "
    r"role\b|\bpretend\b"
    r"|\bfais semblant\b|\bmode (?:developpeur|dev|dan|admin|god|sans filtre|debug|test)\b|\bjailbreak\b|\bdeveloper "
    r"mode\b"
    r"|\bsystem prompt\b|\bprompt systeme\b|\bnouvelle(?:s)? (?:consigne|regle|instruction)s?\b|\bnew instructions?\b"
    r"|\[(?:system|admin|instruction)\]|<\s*/?\s*(?:system|instruction|admin)|\bautorisation (?:speciale|accordee)\b"
    r"|\bconseiller (?:inscrit|agree|licencie)\b|\blicensed advisor\b|\bregistered advisor\b|\btu as (?:le droit|ma "
    r"permission)\b"
    r"|\bje t'autorise\b|\bi authorize you\b|\bdans ce monde fictif\b|\bhypothetiquement\b|\bpour un exercice\b"
    r"|\bsans conseil\b.{0,20}\bjuste\b|\bnc ?31-?103 ne s'applique pas\b"
)
_TICKER_APRES_VERBE = re.compile(
    r"\b(?:buy|sell|short|achete|achetez|vends|vendez|acquiers|acheter|vendre)\s+\$?([A-Z]{1,5})\b(?!\w)"
)
_CASHTAG = re.compile(r"(?<![\w$])\$[A-Z]{1,5}\b")
_SIGLES_PERMIS = frozenset(
    {
        "CPA",
        "TPS",
        "TVQ",
        "TVH",
        "CPG",
        "GIC",
        "PME",
        "RRQ",
        "RQAP",
        "AE",
        "DAS",
        "CNESST",
        "CCQ",
        "FSS",
        "SCIAN",
        "ARC",
        "CAD",
        "USD",
        "NAS",
        "TD",
        "RL",
        "WCT",
        "PO",
        "AP",
        "AR",
        "VAN",
        "TRI",
        "OK",
        "M",
        "DE",
        "LE",
        "LA",
        "UN",
        "UNE",
    }
)
_STEMS_EPELES = (
    "achete",
    "vend",
    "invest",
    "acheter",
    "bitcoin",
    "crypto",
    "action",
    "etf",
    "fnb",
    "bourse",
    "stock",
    "buy",
    "sell",
    "titre",
    "fonds",
)


def _reponse(
    verdict: str,
    code: str | None,
    motifs: list[str],
    contenu: str | None,
    injection: bool,
    restrictions: list[str] | None = None,
) -> dict[str, Any]:
    sortie: dict[str, Any] = {
        "schema": "m5-garde-investissement/1",
        "verdict": verdict,
        "code": code,
        "motifs": motifs,
        "injection_detectee": injection,
        "norme": "NC 31-103",
        "mention_professionnelle": MENTION_PROFESSIONNELLE,
        "contenu_permis": contenu,
    }
    if verdict == "REFUSE":
        sortie["reponse"] = REPONSE_GENERIQUE
    elif verdict == "A_PRECISER":
        sortie["reponse"] = (
            "Je ne fais aucune recommandation sur des titres. Précisez si vous voulez une explication générale ou un "
            "traitement comptable, ou un calcul sur des hypothèses que vous fournissez. " + MENTION_PROFESSIONNELLE
        )
    else:
        sortie["reponse"] = (
            "Contenu permis (information générale ou calcul déterministe) : aucune recommandation de "
            "titres. " + MENTION_PROFESSIONNELLE
        )
    if restrictions:
        sortie["restrictions"] = restrictions
    return sortie


def evaluer_demande(texte: Any, origine: str = "utilisateur") -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Classe une demande. `origine` : `utilisateur` ou `donnee_observee` (un courriel, un document, une page :
    jamais une
    source de consignes). Rend `(verdict, None)` ou `(None, refus typé)` si le texte est inutilisable."""
    if not isinstance(texte, str) or not texte.strip() or len(texte) > TEXTE_MAX:
        return None, verdicts_fiscal.construire_verdict(
            "REJ-INVEST-TEXTE-INVALIDE", f"texte non vide de {TEXTE_MAX} caractères au plus exigé"
        )
    if origine not in {"utilisateur", "donnee_observee"}:
        return None, verdicts_fiscal.construire_verdict(
            "REJ-INVEST-TEXTE-INVALIDE", "origine : utilisateur ou donnee_observee"
        )

    originaux = unicodedata.normalize("NFKC", texte)
    tickers = {m.group(1) for m in _TICKER_APRES_VERBE.finditer(originaux)} - _SIGLES_PERMIS
    cashtags = bool(_CASHTAG.search(originaux))
    securites = acquisition = recommande = personnalise = educatif = tresorerie = exploitation = injection = gain = (
        False
    )
    for variante in _variantes(texte):
        sans_faux = _NEUTRALISER.sub(" ", variante)
        securites |= bool(
            _SECURITES_FORTES.search(sans_faux) or _ACTIONS_TITRES.search(sans_faux) or _TITRE_SIMPLE.search(sans_faux)
        )
        acquisition |= bool(_ACQUISITION.search(variante))
        recommande |= bool(_RECOMMANDATION.search(variante))
        personnalise |= bool(_PERSONNALISATION.search(variante))
        gain |= bool(_GAIN.search(variante))
        educatif |= bool(_EDUCATIF.search(variante))
        tresorerie |= bool(_TRESORERIE.search(variante))
        exploitation |= bool(_EXPLOITATION.search(variante))
        injection |= bool(_INJECTION.search(variante))
        epeles = _mots_epeles(variante)
        if epeles:
            for stem in _STEMS_EPELES:
                if stem in epeles:
                    securites |= stem in {
                        "bitcoin",
                        "crypto",
                        "action",
                        "etf",
                        "fnb",
                        "bourse",
                        "stock",
                        "titre",
                        "fonds",
                    }
                    acquisition |= stem in {"achete", "vend", "invest", "acheter", "buy", "sell"}
                    recommande |= stem in {"achete", "vend", "invest", "acheter", "buy", "sell"}
    securites |= bool(tickers) or cashtags
    if tickers:
        acquisition = recommande = True
    motifs: list[str] = []
    if securites:
        motifs.append("titres mentionnés (actions, FNB, fonds, obligations, cryptoactifs, symbole boursier)")
    if recommande:
        motifs.append("demande de recommandation, de choix ou d'ordre d'achat, de vente ou de placement")
    if personnalise:
        motifs.append("situation ou montants personnels")
    if injection:
        motifs.append("consigne glissée dans le texte, sans effet sur la décision")
    donnee_qui_ordonne = origine == "donnee_observee" and (recommande or acquisition) and (securites or recommande)
    if donnee_qui_ordonne:
        injection = True
        motifs.append("texte observé qui ordonne une action : une donnée n'est jamais une consigne")

    if securites and (recommande or acquisition or personnalise or gain or donnee_qui_ordonne):
        return _reponse("REFUSE", "REJ-INVEST-RECOMMANDATION-PERSONNALISEE", motifs, None, injection), None
    if securites and educatif:
        return _reponse(
            "PERMIS",
            None,
            motifs,
            "information_generale",
            injection,
            ["explication générale seulement : aucun titre précis recommandé"],
        ), None
    if securites:
        return _reponse("A_PRECISER", None, motifs, None, injection), None
    if recommande or donnee_qui_ordonne:
        if exploitation and not donnee_qui_ordonne:
            return _reponse(
                "PERMIS",
                None,
                motifs,
                "decision_exploitation",
                injection,
                [
                    "calculer avec m5_calculer_rentabilite_investissement et les moteurs de calcul, sur des "
                    "hypothèses fournies"
                ],
            ), None
        if tresorerie and not donnee_qui_ordonne:
            return _reponse(
                "PERMIS",
                None,
                motifs,
                "tresorerie",
                injection,
                [
                    "aucun produit, émetteur ni institution n'est recommandé",
                    "calculs déterministes sur des hypothèses fournies",
                ],
            ), None
        motifs.append("achat ou placement de fonds sans objet d'exploitation reconnu : refusé par prudence")
        return _reponse("REFUSE", "REJ-INVEST-RECOMMANDATION-PERSONNALISEE", motifs, None, injection), None
    if exploitation:
        return _reponse("PERMIS", None, motifs, "decision_exploitation", injection), None
    if tresorerie:
        return _reponse(
            "PERMIS", None, motifs, "tresorerie", injection, ["aucun produit, émetteur ni institution n'est recommandé"]
        ), None
    if educatif and acquisition:
        return _reponse("PERMIS", None, motifs, "information_generale", injection), None
    return _reponse("PERMIS", None, motifs, "hors_investissement", injection), None
