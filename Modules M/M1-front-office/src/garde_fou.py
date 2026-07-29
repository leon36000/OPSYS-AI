import re
import unicodedata
import verdicts
from registre import Registre

__all__ = ["verifier_sortie"]



# ----------------------------------------------------------------------
# Normalisation
# ----------------------------------------------------------------------
def _normaliser(texte: str) -> str:
    """Remplace toutes les apostrophes courbes par l'apostrophe droite."""
    return texte.replace('\u2019', "'")


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
    r'''
    (?:{sep}*|\b)\d{{1,3}}(?:{sep}{{0,1}}\d{{3}})*(?:[.,]\d+)?\s*
    (?:\$|€|(?:CAD|dollars?|euros?)\b)
    |
    \$\s*\d{{1,3}}(?:{sep}{{0,1}}\d{{3}})*(?:[.,]\d+)?\b
    |
    \b\d+\s*(?:\$|CAD|€|dollars?|euros?)\s*/\s*(?:h|heure|pied\s+carré|m²)\b
    |
    \b(?:deux\s+mille|mille)\s+(?:dollars?|CAD|\$|€|euros?)\b
    |
    \bfourchette\b.*\b\d{{1,3}}(?:{sep}{{0,1}}\d{{3}})*(?:[.,]\d+)?\s*(?:à|et)\s*\d{{1,3}}(?:{sep}{{0,1}}\d{{3}})*(?:[.,]\d+)?\b
    '''.format(sep=_SEP),
    re.IGNORECASE | re.VERBOSE
)
GRAND_NOMBRE = re.compile(r'\b\d{1,3}(?:\s?\d{3})*\b')


def _detecter_prix(texte: str) -> bool:
    # Recherche directe d'un montant monétaire (amélioré)
    if MONTANT_MONETAIRE.search(texte):
        return True
    # Mot-clé combiné à un grand nombre (tarif/budget/... + nombre)
    if PRIX_MOT_CLE.search(texte) and GRAND_NOMBRE.search(texte):
        return True
    return False


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
    \b(?:''' + r'''
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
    (?:intervention|livraison|visite\ technique|chantier|pose|installation|réfection|rénovation|travaux)\b\s+(?:\w+\s+){{0,2}}(?:programmé(?:e)?(?:s)?|planifié(?:e)?(?:s)?|prévu(?:e)?(?:s)?|fixé(?:e)?(?:s)?|cédulé(?:e)?(?:s)?)\b |
    installation\b |
    # Passif générique : auxiliaire être + participe passé d'exécution
    {aux}\s+{part}\b
    '''.format(aux=_AUX_ETRE, part=_PART_EXEC) + r'''
    )\b
    ''',
    re.IGNORECASE | re.VERBOSE
)

# Verbes de contact (liste blanche) – inchangés
VERBES_CONTACT = re.compile(
    r'''
    \b(?:rappel[ée]r?(?:a|ont)?|recontact[ée]r?(?:a|ont)?|
    reviendr[aez]|joindr[ée]|téléphon[ée]r?(?:a|ont)?|
    écri[rt]|enverr[oa]|transmettr[ae]|fixer\s+(?:une\s+)?date|
    confirmer\s+(?:la\s+)?prise\s+de\s+rendez-vous)\b
    ''',
    re.IGNORECASE | re.VERBOSE
)


def _decouper_segments(texte: str) -> list[str]:
    """
    Sépare le texte en segments indépendants sur la base de :
    - ponctuation forte : . ! ? ;
    - ponctuation faible : , :
    - conjonctions / mots-outils : et, puis, mais, pour, afin, que
    Chaque segment résultant est nettoyé des espaces superflus.
    """
    # Pattern de séparation : les ponctuations et les mots de liaison entourés d'espaces
    # Le tiret a été retiré de la classe de ponctuation pour ne pas découper
    # les dates au format ISO (AAAA-MM-JJ), qui contiennent des tirets internes.
    separateur = re.compile(
        r'''
        \s*                     # éventuels espaces avant le séparateur
        (?:
            [.!?;,:]            # ponctuation
          |                     # OU
            \b(?:et|puis|mais|pour|afin|que)\b   # conjonctions/mots-outils
        )
        \s*                     # éventuels espaces après
        ''',
        re.IGNORECASE | re.VERBOSE
    )
    parties = separateur.split(texte)
    # Nettoyer chaque partie et ne garder que les segments non vides
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
    La présence d'un verbe de contact dans un segment ne neutralise
    que ce segment, sauf si un verbe d'exécution est également présent.
    """
    segments = _decouper_segments(texte)
    for seg in segments:
        # Un segment est suspect si REF_TEMPORELLE et VERBES_EXECUTION sont présents,
        # indépendamment de VERBES_CONTACT (l'exécution l'emporte).
        if REF_TEMPORELLE.search(seg) and VERBES_EXECUTION.search(seg):
            return True
    return False


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


# ----------------------------------------------------------------------
# Point d'entrée (inchangé)
# ----------------------------------------------------------------------
def verifier_sortie(texte: str, registre=None, horodatage: str | None = None) -> dict:
    if not isinstance(texte, str):
        raise TypeError("Le texte doit être une chaîne de caractères")
    if texte == "":
        return verdicts.construire_verdict("OK")

    texte_norm = _normaliser(texte)

    # Ordre d'évaluation fixe et documenté : PRIX → DATE → ENGAGEMENT → AVEU
    if _detecter_prix(texte_norm):
        code = "REJ-INTERDIT-PRIX"
    elif _detecter_date(texte_norm):
        code = "REJ-INTERDIT-DATE"
    elif _detecter_engagement(texte_norm):
        code = "REJ-INTERDIT-ENGAGEMENT"
    elif _detecter_aveu(texte_norm):
        code = "REJ-INTERDIT-AVEU"
    else:
        code = "OK"

    verdict = verdicts.construire_verdict(code)

    # Journalisation dans le registre si violation et registre fourni
    if code != "OK" and registre is not None:
        if horodatage is None:
            raise ValueError("Un horodatage doit être fourni lorsque le registre est utilisé")
        entree = {
            "type_entree": "alerte",
            "horodatage": horodatage,
            "payload": {"code_verdict": code}
        }
        registre.ajouter(entree)

    return verdict
