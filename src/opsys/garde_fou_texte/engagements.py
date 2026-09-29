"""Familles d'un message à un client : prix, date d'exécution, engagement, aveu (règles de M1, PLAN T2.1 à T4.5).

Ce sont les règles du garde-fou de M1 (`m1_front_office.garde_fou`), déplacées ici SANS changement de sens : le corpus
adversarial de M1 (44 textes) et son corpus légitime (22) donnent les mêmes verdicts. Elles sont plus étroites que
celles d'un texte public (`promesses.py`) : une réponse à un client peut parler de budget ou de gratuité, jamais
donner un montant, une date de chantier, une promesse ferme ni reconnaître un tort.

Ordre d'évaluation, fixé par le catalogue : prix, date, engagement, aveu. Les motifs lisent le texte dont seule
l'apostrophe courbe est remplacée (`Formes.droit`) : la casse et les accents comptent pour les motifs.

Module pur : aucune entrée-sortie, aucune horloge, aucun modèle.
"""

from __future__ import annotations

import re

from ._types import Contexte, Formes

# ----------------------------------------------------------------------
# Séparateur d'espace étendu (normale + insécables) – corrigé pour re.VERBOSE
# ----------------------------------------------------------------------
_SEP = r'[\x20\u00A0\u202F]'   # espace ASCII + fine insécable + espace insécable

# ----------------------------------------------------------------------
# Détection de la famille PRIX
# ----------------------------------------------------------------------
PRIX_MOT_CLE = re.compile(
    r'\b(?:tarif|budget|fourchette|coûtera|coût|prix|coûte)\b',
    re.IGNORECASE
)
MONTANT_MONETAIRE = re.compile(
    rf'''
    (?:{_SEP}*|\b)\d{{1,3}}(?:{_SEP}{{0,1}}\d{{3}})*(?:[.,]\d+)?\s*
    (?:\$|€|(?:CAD|dollars?|euros?)\b)
    |
    \$\s*\d{{1,3}}(?:{_SEP}{{0,1}}\d{{3}})*(?:[.,]\d+)?\b
    |
    \b\d+\s*(?:\$|CAD|€|dollars?|euros?)\s*/\s*(?:h|heure|pied\s+carré|m²)\b
    |
    \b(?:deux\s+mille|mille)\s+(?:dollars?|CAD|\$|€|euros?)\b
    |
    \bfourchette\b.*\b\d{{1,3}}(?:{_SEP}{{0,1}}\d{{3}})*(?:[.,]\d+)?\s*(?:à|et)\s*\d{{1,3}}(?:{_SEP}{{0,1}}\d{{3}})*(?:[.,]\d+)?\b
    ''',
    re.IGNORECASE | re.VERBOSE
)
GRAND_NOMBRE = re.compile(r'\b\d{1,3}(?:\s?\d{3})*\b')


def _detecter_prix(texte: str) -> bool:
    # Recherche directe d'un montant monétaire (amélioré)
    if MONTANT_MONETAIRE.search(texte):
        return True
    # Mot-clé combiné à un grand nombre (tarif/budget/... + nombre)
    return bool(PRIX_MOT_CLE.search(texte) and GRAND_NOMBRE.search(texte))


# ----------------------------------------------------------------------
# Détection de la famille DATE
# ----------------------------------------------------------------------
MOIS = r'(?:janvier|février|mars|avril|mai|juin|juillet|ao[ûu]t|septembre|octobre|novembre|décembre)'
REF_TEMPORELLE = re.compile(
    r'''
    \b\d{4}-\d{2}-\d{2}\b
    |
    \b\d{1,2}/\d{1,2}\b
    |
    \bdemain\b|\baujourd['’']hui\b
    |
    \b(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche)(?:\s+prochain)?\b
    |
    \bla\s+semaine\s+prochaine\b
    |
    \bdans\s+\d+\s+jours?\b
    |
    \bd['’']ici\s+(?:lundi|mardi|mercredi|jeudi|vendredi|samedi|dimanche|\d{1,2}\s+''' + MOIS + r''')\b
    |
    \b(?:début|mi|fin)\s+''' + MOIS + r'''\b
    |
    \b\d{1,2}\s+''' + MOIS + r'''(?:\s+prochain)?\b
    |
    \bau\s+plus\s+tard\b
    ''',
    re.IGNORECASE | re.VERBOSE
)

# Participles passés des verbes d'exécution de chantier
_PART_EXEC = r'''(?:terminé|terminée|terminés|terminées|
    fini|finie|finis|finies|
    achevé|achevée|achevés|achevées|
    livré|livrée|livrés|livrées|
    commencé|commencée|commencés|commencées|
    débuté|débutée|débutés|débutées|
    démarré|démarrée|démarrés|démarrées|
    installé|installée|installés|installées|
    posé|posée|posés|posées|
    réparé|réparée|réparés|réparées|
    coulé|coulée|coulés|coulées|
    effectué|effectuée|effectués|effectuées|
    réalisé|réalisée|réalisés|réalisées|
    rénové|rénovée|rénovés|rénovées|
    isolé|isolée|isolés|isolées|
    remplacé|remplacée|remplacés|remplacées|
    construit|construite|construits|construites|
    monté|montée|montés|montées|
    refait|refaite|refaits|refaites|
    fait|faite|faits|faites|
    prévu|prévue|prévus|prévues|
    coulé|coulée|coulés|coulées|
    posé|posée|posés|posées|
    terminé|terminée|terminés|terminées|
    livré|livrée|livrés|livrées|
    installé|installée|installés|installées|
    programmé|programmée|programmés|programmées|
    planifié|planifiée|planifiés|planifiées|
    prévu|prévue|prévus|prévues|
    fixé|fixée|fixés|fixées|
    cédulé|cédulée|cédulés|cédulées)'''

# Auxiliaire être (formes courantes)
_AUX_ETRE = r'''(?:sera|seront|est|sont|était|étaient|serait|seraient|
    ét[ée]|soit|soient|suis|es|sommes|êtes|serai|seras|
    serons|serez|serons|seront|fut|furent|sois|soyons|soyez)'''

# Verbes d'exécution : toutes formes actives (infinitif, présent, futur, impératif, etc.)
# + passif (auxiliaire être + participe)
# + noms d'action (livraison, pose, début/fin des travaux, etc.)
VERBES_EXECUTION = re.compile(
    r'''
    \b(?:''' + rf'''
    # Formes actives (infinitif, présent, futur…) pour la plupart des verbes du 1er groupe
    termin(?:er|era|eras|erons|erez|eront|é|ée|és|ées|e|es|ons|ez|ent?)\b|
    fin(?:ir|ira|irons|irez|iront|i|ie|is|ies?|is?t?|issons|issez|issent?)\b|
    achev(?:er|era|eras|erons|erez|eront|é|ée|és|ées|e|es|ons|ez|ent?)\b|
    livr(?:er|era|eras|erons|erez|eront|é|ée|és|ées|e|es|ons|ez|ent?)\b|
    commenc(?:er|era|eras|erons|erez|eront|é|ée|és|ées|e|es|ons|ez|ent?)\b|
    début(?:er|era|eras|erons|erez|eront|é|ée|és|ées|e|es|ons|ez|ent?)\b|
    démarr(?:er|era|eras|erons|erez|eront|é|ée|és|ées|e|es|ons|ez|ent?)\b|
    install(?:er|era|eras|erons|erez|eront|é|ée|és|ées|e|es|ons|ez|ent?)\b|
    pos(?:er|era|eras|erons|erez|eront|é|ée|és|ées|e|es|ons|ez|ent?)\b|
    coul(?:er|era|eras|erons|erez|eront|é|ée|és|ées|e|es|ons|ez|ent?)\b|
    répar(?:er|era|eras|erons|erez|eront|é|ée|és|ées|e|es|ons|ez|ent?)\b|
    rénov(?:er|era|eras|erons|erez|eront|é|ée|és|ées|e|es|ons|ez|ent?)\b|
    isol(?:er|era|eras|erons|erez|eront|é|ée|és|ées|e|es|ons|ez|ent?)\b|
    remplac(?:er|era|eras|erons|erez|eront|é|ée|és|ées|e|es|ons|ez|ent?)\b|
    construi(?:re|ra|rons|rez|ront|t|te|ts|tes?|sons|sez|sent?)\b|
    mont(?:er|era|eras|erons|erez|eront|é|ée|és|ées|e|es|ons|ez|ent?)\b|
    effectu(?:er|era|eras|erons|erez|eront|é|ée|és|ées|e|es|ons|ez|ent?)\b|
    réalis(?:er|era|eras|erons|erez|eront|é|ée|és|ées|e|es|ons|ez|ent?)\b|
    # Formes supplémentaires déjà présentes (gardées pour compatibilité)
    fini[rt]?\b|
    refai[rt]e?\b|
    faites?\b|
    auront\s+lieu\b|
    réfection\b|
    rénovation\b|
    # Noms d'action quand ils sont datés
    livraison\b|
    pose\b|
    début\s+(?:des\s+travaux|du\s+chantier)\b|
    fin\s+(?:des\s+travaux|du\s+chantier)\b|
    commencement\b|
    (?:intervention|livraison|visite\ technique|chantier|pose|installation|réfection|rénovation|travaux)'''
    rf'''\b\s+(?:\w+\s+){{0,2}}'''
    rf'''(?:programmé(?:e)?(?:s)?|planifié(?:e)?(?:s)?|prévu(?:e)?(?:s)?|fixé(?:e)?(?:s)?|cédulé(?:e)?(?:s)?)\b |
    installation\b |
    # Passif générique : auxiliaire être + participe passé d'exécution
    {_AUX_ETRE}\s+{_PART_EXEC}\b
    ''' + r'''
    )\b
    ''',
    re.IGNORECASE | re.VERBOSE
)


def decouper_segments(texte: str) -> list[str]:
    """
    Sépare le texte en segments indépendants sur la base de la ponctuation forte :
    . ! ? ; et des sauts de ligne.
    Chaque segment résultant est nettoyé des espaces superflus.
    """
    separateur = re.compile(
        r'''
        \s*                     # éventuels espaces avant le séparateur
        (?:
            [.!?;]              # ponctuation forte
            |                   # OU
            \n                  # saut de ligne
        )
        \s*                     # éventuels espaces après
        ''',
        re.VERBOSE
    )
    parties = separateur.split(texte)
    segments = []
    for p in parties:
        p = p.strip()
        if p:
            segments.append(p)
    return segments


def _detecter_date(texte: str) -> bool:
    """
    Vérifie si le texte contient une proposition associant une
    référence temporelle à un verbe d'exécution de chantier.
    Chaque segment est jugé seul : un rappel téléphonique (« je vous rappelle lundi ») n'a pas de verbe
    d'exécution et passe, mais il ne neutralise jamais la phrase voisine qui en a un.
    """
    segments = decouper_segments(texte)
    # Un segment est suspect si REF_TEMPORELLE et VERBES_EXECUTION sont présents ensemble.
    return any(REF_TEMPORELLE.search(seg) and VERBES_EXECUTION.search(seg) for seg in segments)


# ----------------------------------------------------------------------
# Détection ENGAGEMENT (inchangé)
# ----------------------------------------------------------------------
ENGAGEMENT = re.compile(
    r'''
    \b(?:nous\s+nous\s+engageons|je\s+m['’]engage|
    nous\s+nous\s+portons\s+garants?|se\s+porter\s+garant)|
    \bgaranti[ée]?s?\b|\bje\s+vous\s+garantis\b|\bnous\s+garantissons\b|
    \bpromis\b|\bje\s+vous\s+le\s+promets?\b|
    \bc['’]est\s+confirmé\b|confirmé,\s|
    \bvotre\s+place\s+est\s+réservée\b|\bplace\s+réservée\b|
    \bengagement\s+ferme\b|
    \bvous\s+avez\s+(?:notre|ma)\s+parole\b|\bnotre\s+parole\b|
    \bje\s+m['’]engage\b|
    \bnous\s+garantissons\b
    ''',
    re.IGNORECASE | re.VERBOSE
)


def _detecter_engagement(texte: str) -> bool:
    return bool(ENGAGEMENT.search(texte))


# ----------------------------------------------------------------------
# Détection AVEU (inchangé)
# ----------------------------------------------------------------------
AVEU = re.compile(
    r'''
    \bnotre\s+faute\b|
    \bnous\s+sommes\s+responsables?\b|
    \berreur\s+de\s+notre\s+part\b|
    \bon\s+[al]\s+mal\s+fait\b|
    \ba\s+commis\s+une\s+faute\b|
    \bnous\s+assumons\s+la\s+responsabilité\b|
    \bje\s+reconnais\s+que\s+nous\s+avons\s+mal\b|
    \bnous\s+prenons\s+le\s+blâme\b|
    \bc['’]est\s+une\s+erreur\s+de\s+notre\b|
    \ble\s+vice\s+est\s+dû?\s+à\s+notre\b|
    \bde\s+notre\s+fait\b|
    \bentièrement\s+de\s+notre\s+fait\b|
    \bnous\s+reconnaissons\s+que\b.*\berreur\b|
    \bnous\s+sommes\s+responsables\b.*\bdégâts\b|
    \bnous\s+assumons\b.*\bresponsabilité\b
    ''',
    re.IGNORECASE | re.VERBOSE
)


def _detecter_aveu(texte: str) -> bool:
    return bool(AVEU.search(texte))


def prix_montant(formes: Formes, _contexte: Contexte) -> str | None:
    if _detecter_prix(formes.droit):
        return "prix, montant ou fourchette de prix : retire-le"
    return None


def date_execution(formes: Formes, _contexte: Contexte) -> str | None:
    if _detecter_date(formes.droit):
        return "date ou délai d'exécution des travaux : retire-le"
    return None


def engagement(formes: Formes, _contexte: Contexte) -> str | None:
    if _detecter_engagement(formes.droit):
        return "engagement ferme (promesse, garantie, parole donnée) : retire-le"
    return None


def aveu(formes: Formes, _contexte: Contexte) -> str | None:
    if _detecter_aveu(formes.droit):
        return "aveu de faute ou de responsabilité : retire-le"
    return None
