"""Détecteurs de renseignements personnels québécois et canadiens, par motifs et validations (module pur, sans E/S).

Chaque détecteur rend des `Detection` (catégorie, position, valeur normalisée). Rien ici ne choisit le remplacement ni
ne
stocke la valeur : voir `pii.py`.

Ce que ces détecteurs savent faire (déterministe, mesuré sur `corpus_pii`) : NAS (9 chiffres, somme de Luhn), cartes de
paiement (Luhn + préfixe d'émetteur), téléphones nord-américains (plan NANP), courriels, codes postaux canadiens,
adresses
civiques à numéro et type de voie, numéro d'assurance maladie (format RAMQ plausible), NEQ et numéros d'entreprise (avec
contexte), jetons et clés (préfixes connus, paires clé=valeur, entropie), civilité + nom.

Ce qu'ils NE savent PAS faire (voir « Limites » de docs/architecture/OBSERVABILITE-MCP.md) : un nom propre sans
civilité,
une adresse décrite en mots (« la maison bleue au coin de l'église »), un numéro écrit en lettres, un courriel obscurci
(« jean arobase … »), un identifiant interne sans forme reconnaissable, une valeur coupée sur deux lignes. Une approche
par
motifs ne comprend pas le sens : Presidio (NER) ou une revue humaine reste le complément (port `MasqueurPII`).

Aucun motif n'a de retour arrière catastrophique : quantificateurs bornés ou possessifs (testé sur des suites hostiles).
"""

from __future__ import annotations

import dataclasses
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Callable, Iterable

CATEGORIES: tuple[str, ...] = (
    "secret", "courriel", "carte", "nas", "ramq", "neq", "numero_entreprise", "telephone", "adresse", "code_postal",
    "nom",
)
# Priorité de résolution d'un chevauchement (plus petit = plus fort) : une structure délimitée (secret, courriel)
# l'emporte
# sur un nombre validé, qui l'emporte sur un motif plus lâche.
PRIORITE = {cat: rang for rang, cat in enumerate(CATEGORIES)}
ETIQUETTES = {
    "secret": "SECRET", "courriel": "COURRIEL", "carte": "CARTE", "nas": "NAS", "ramq": "RAMQ", "neq": "NEQ",
    "numero_entreprise": "NE", "telephone": "TEL", "adresse": "ADRESSE", "code_postal": "CP", "nom": "NOM",
}
TAILLE_MAX_TEXTE = 200_000
_SEP = r"[ \u00a0\u202f]"  # espace, espace insécable (typographie française), espace fine insécable


@dataclasses.dataclass(frozen=True)
class Detection:
    categorie: str
    debut: int
    fin: int
    normalisee: str = dataclasses.field(repr=False)  # jamais affichée : c'est la valeur (normalisée) qu'on protège


def plier(texte: str) -> str:
    """Minuscules sans accents : sert aux mots de contexte (« tél », « numéro d'assurance sociale »)."""
    decompose = unicodedata.normalize("NFKD", texte.casefold())
    return "".join(c for c in decompose if not unicodedata.combining(c))


def luhn_valide(chiffres: str) -> bool:
    if not chiffres.isdigit() or len(chiffres) < 2:
        return False
    somme = 0
    for rang, c in enumerate(reversed(chiffres)):
        n = int(c)
        if rang % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        somme += n
    return somme % 10 == 0


def _chiffres(valeur: str) -> str:
    return "".join(c for c in valeur if c.isdigit())


def _avant(texte: str, debut: int, n: int = 48) -> str:
    return plier(texte[max(0, debut - n):debut])


def _apres_monetaire(texte: str, fin: int) -> bool:
    suite = texte[fin:fin + 8].lstrip(" \u00a0\u202f")
    return bool(re.match(r"(?:\$|€|cad\b|usd\b|dollars?\b)", suite, re.IGNORECASE))


# -- NAS -------------------------------------------------------------------------------------------------------------
_NAS = re.compile(r"(?<![\d.,-])(?<!\d[ \u00a0\u202f])(\d{3})([ \u00a0\u202f.-]?)(\d{3})\2(\d{3})(?!\d|[.,]\d)")
_CTX_NAS = re.compile(r"\bnas\b|n\.?a\.?s\b|assurance sociale|social insurance|\bsin\b|securite sociale")


def _nas(texte: str) -> Iterable[Detection]:
    for m in _NAS.finditer(texte):
        chiffres = _chiffres(m.group(0))
        if not luhn_valide(chiffres) or _apres_monetaire(texte, m.end()):
            continue
        if texte[max(0, m.start() - 1):m.start()] == "$":
            continue
        if not m.group(2) and not _CTX_NAS.search(_avant(texte, m.start())):
            continue  # 9 chiffres collés : trop courant (identifiants) sans le mot « NAS » devant
        yield Detection("nas", m.start(), m.end(), chiffres)


# -- cartes de paiement ----------------------------------------------------------------------------------------------
_CARTE = re.compile(r"(?<![\d])(?:\d[ \u00a0\u202f-]?){12,18}\d(?!\d)")
_PREFIXES_CARTE = re.compile(
    r"^(?:4|3[47]|5[1-5]|2(?:2[2-9][1-9]|2[3-9]\d|[3-6]\d\d|7[01]\d|720)|6011|65|64[4-9]|35(?:2[89]|[3-8]\d)|"
    r"30[0-5]|36|38|62)"
)


def _carte(texte: str) -> Iterable[Detection]:
    for m in _CARTE.finditer(texte):
        chiffres = _chiffres(m.group(0))
        if (13 <= len(chiffres) <= 19 and luhn_valide(chiffres) and _PREFIXES_CARTE.match(chiffres)
                and not _apres_monetaire(texte, m.end())):
            yield Detection("carte", m.start(), m.end(), chiffres)


# -- téléphones (plan nord-américain) --------------------------------------------------------------------------------
_TEL = re.compile(
    rf"(?<![\w@])(?P<ind>\+?1[ \u00a0\u202f.-]?)?(?:\((?P<a1>[2-9]\d{{2}})\)|(?P<a2>[2-9]\d{{2}}))"
    rf"[ \u00a0\u202f.-]?(?P<e>[2-9]\d{{2}})[ \u00a0\u202f.-]?(?P<n>\d{{4}})(?!\d)"
    rf"(?:{_SEP}?(?:poste|p\.|ext\.?|x){_SEP}?\d{{1,6}})?",
    re.IGNORECASE,
)
_CTX_TEL = re.compile(
    r"\btel\b|telephone|cellulaire|\bcell\b|mobile|phone|\bfax\b|telecopieur|texto|\bsms\b|rejoindre|joindre|"
    r"appeler|rappeler|numero"
)


def _tel(texte: str) -> Iterable[Detection]:
    for m in _TEL.finditer(texte):
        indicatif = m.group("a1") or m.group("a2")
        echange = m.group("e")
        if indicatif[1:] == "11" or echange[1:] == "11":  # N11 (211, 911…) : jamais un abonné
            continue
        brut = m.group(0)
        sans_poste = re.split(r"(?i)[ \u00a0\u202f]*(?:poste|p\.|ext|x)", brut)[0]
        formate = bool(re.search(r"[ \u00a0\u202f().+-]", sans_poste))
        if not formate and not m.group("ind") and not _CTX_TEL.search(_avant(texte, m.start(), 18)):
            continue  # 10 chiffres collés, sans indicatif ni mot de contexte : identifiant probable
        yield Detection("telephone", m.start(), m.end(), indicatif + echange + m.group("n"))


# -- courriels -------------------------------------------------------------------------------------------------------
# Partie locale lue d'un seul départ, sans retour arrière : temps linéaire même sur une longue suite sans « @ ».
_COURRIEL = re.compile(r"(?<![A-Za-z0-9._%+-])[A-Za-z0-9._%+-]++@(?:[A-Za-z0-9-]++\.)++[A-Za-z]{2,24}(?![A-Za-z0-9-])")


def _courriel(texte: str) -> Iterable[Detection]:
    for m in _COURRIEL.finditer(texte):
        yield Detection("courriel", m.start(), m.end(), m.group(0).lower())


# -- codes postaux canadiens -----------------------------------------------------------------------------------------
_LETTRE_1 = "ABCEGHJ-NPRSTVXY"
_LETTRE_N = "ABCEGHJ-NPRSTV-Z"
_CP = re.compile(
    rf"(?<![A-Za-z0-9])([{_LETTRE_1}])(\d)([{_LETTRE_N}])([ \u00a0\u202f-]?)(\d)([{_LETTRE_N}])(\d)(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def _code_postal(texte: str) -> Iterable[Detection]:
    for m in _CP.finditer(texte):
        brut = m.group(0)
        if not m.group(4) and brut != brut.upper():
            continue  # collé et en minuscules : ressemble à un identifiant hexadécimal
        yield Detection("code_postal", m.start(), m.end(), re.sub(r"[ \u00a0\u202f-]", "", brut).upper())


# -- adresses civiques -----------------------------------------------------------------------------------------------
_VOIE = (
    r"(?:rue|av\.?|avenue|boul\.?|boulevard|bd|ch\.?|chemin|rang|route|rte|mont[ée]e|place|impasse|croissant|all[ée]e|"
    r"c[ôo]te|terrasse|promenade|cercle|ruelle|carr[ée])"
)
_PARTICULES = r"(?:de la|de l['’]|du|des|de|d['’]|la|le|les|aux?)"
_MOT = r"[A-Za-zÀ-ÖØ-öø-ÿ0-9][A-Za-zÀ-ÖØ-öø-ÿ0-9'’.-]{0,30}"
_MOT_MAJ = r"[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’.-]{0,30}"
_ADRESSE = re.compile(
    rf"(?<![\w-])\d{{1,5}}[A-Z]?(?:-\d{{1,5}})?(?:{_SEP}*,{_SEP}*|{_SEP}+)(?:\d{{1,3}}(?:e|re|ère|eme|ème|ieme){_SEP}+)?"
    rf"(?i:{_VOIE})(?![A-Za-zÀ-ÿ]){_SEP}+(?:(?i:{_PARTICULES}){_SEP}*)?{_MOT}"
    rf"(?:{_SEP}+(?:(?i:{_PARTICULES}){_SEP}*)?{_MOT_MAJ}){{0,3}}"
    rf"(?:{_SEP}*,?{_SEP}*(?i:app(?:artement)?|apt|bureau|suite|unit[ée]|local)\.?{_SEP}*#?{_SEP}*\d{{1,5}}[A-Za-z]?)?"
)


_ADRESSE_EN = re.compile(
    rf"(?<![\w-])\d{{1,5}}[A-Z]?{_SEP}+(?:[A-Z][a-z'’-]{{1,20}}{_SEP}+){{1,3}}"
    r"(?:Street|St\.?|Avenue|Ave\.?|Road|Rd\.?|Boulevard|Blvd\.?|Drive|Dr\.?|Lane|Ln\.?|Crescent|Court|Way)(?![A-Za-z])"
)


def _adresse(texte: str) -> Iterable[Detection]:
    for m in _ADRESSE_EN.finditer(texte):
        yield Detection("adresse", m.start(), m.end(), re.sub(r"[ \u00a0\u202f]+", " ", plier(m.group(0))))
    for m in _ADRESSE.finditer(texte):
        fin = m.end()
        while fin > m.start() and texte[fin - 1] in ".,-'’":
            fin -= 1  # ponctuation finale de la phrase
        yield Detection("adresse", m.start(), fin, re.sub(r"[ \u00a0\u202f]+", " ", plier(texte[m.start():fin])))


# -- assurance maladie (RAMQ) ----------------------------------------------------------------------------------------
# Format : 4 lettres (3 du nom de famille, 1 du prénom), puis AAMMJJNN ; le mois porte +50 pour une femme.
_RAMQ = re.compile(
    r"(?<![A-Za-z0-9])([A-Z]{4})([ \u00a0\u202f-]?)(\d{2})(\d{2})\2(\d{2})(\d{2})(?![A-Za-z0-9])"
)
_RAMQ_SEP = re.compile(r"(?<![A-Za-z0-9])([A-Z]{4})[ \u00a0\u202f-](\d{4})[ \u00a0\u202f-](\d{4})(?![A-Za-z0-9])")


def _ramq(texte: str) -> Iterable[Detection]:
    vus: set[int] = set()
    for motif in (_RAMQ, _RAMQ_SEP):
        for m in motif.finditer(texte):
            valeur = re.sub(r"[ \u00a0\u202f-]", "", m.group(0))
            mois, jour = int(valeur[6:8]), int(valeur[8:10])
            if not (1 <= mois <= 12 or 51 <= mois <= 62) or not 1 <= jour <= 31:
                continue
            if m.start() in vus:
                continue
            vus.add(m.start())
            yield Detection("ramq", m.start(), m.end(), valeur)


# -- NEQ et numéros d'entreprise -------------------------------------------------------------------------------------
_NEQ = re.compile(r"(?<![\d])(?:11|22|33|88)\d{2}[ \u00a0\u202f]?\d{4}[ \u00a0\u202f]?\d{2}(?!\d)")
_CTX_NEQ = re.compile(
    r"\bneq\b|numero d'entreprise du quebec|registraire des entreprises|registre des entreprises|\breq\b"
)
_BN_PROGRAMME = re.compile(rf"(?<![\d])\d{{9}}{_SEP}?(?:R[TPCMRZDE])\s?\d{{4}}(?![\d])", re.IGNORECASE)
_TVQ = re.compile(rf"(?<![\d])\d{{10}}{_SEP}?TQ{_SEP}?\d{{4}}(?![\d])", re.IGNORECASE)
_BN9 = re.compile(r"(?<![\d.,-])\d{9}(?![\d]|[.,]\d)")
_CTX_BN = re.compile(
    r"numero d'entreprise|n[°o] d'entreprise|\bbn\b|business number|\btps\b|\bgst\b|\bhst\b|\btvh\b|\bne\b"
)


def _entreprise(texte: str) -> Iterable[Detection]:
    for m in _NEQ.finditer(texte):
        if _CTX_NEQ.search(_avant(texte, m.start())):
            yield Detection("neq", m.start(), m.end(), _chiffres(m.group(0)))
    for motif in (_BN_PROGRAMME, _TVQ):
        for m in motif.finditer(texte):
            yield Detection("numero_entreprise", m.start(), m.end(), re.sub(r"[ \u00a0\u202f]", "", m.group(0)).upper())
    for m in _BN9.finditer(texte):
        if _CTX_BN.search(_avant(texte, m.start(), 40)) and not _CTX_NAS.search(_avant(texte, m.start(), 40)):
            yield Detection("numero_entreprise", m.start(), m.end(), m.group(0))


# -- secrets : clés, jetons, mots de passe ---------------------------------------------------------------------------
_PEM = re.compile(r"-----BEGIN [A-Z ]{0,40}PRIVATE KEY-----(?:[\s\S]*?-----END [A-Z ]{0,40}PRIVATE KEY-----|[\s\S]*\Z)")
_PREFIXES_SECRETS = re.compile(
    r"(?<![A-Za-z0-9_-])(?:"
    r"sk-ant-[A-Za-z0-9_-]{16,}|sk-[A-Za-z0-9_-]{16,}|[sr]k_(?:live|test)_[A-Za-z0-9]{16,}|pk_live_[A-Za-z0-9]{16,}|"
    r"gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{30,}|glpat-[A-Za-z0-9_-]{16,}|"
    r"xox[abprs]-[A-Za-z0-9-]{10,}|(?:AKIA|ASIA)[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|ya29\.[0-9A-Za-z_.-]{20,}|"
    r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}|opsys-jeton:v1:[A-Za-z0-9_-]{16,}|"
    r"hf_[A-Za-z0-9]{30,}|npm_[A-Za-z0-9]{30,}|SG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,})"
)
_BEARER = re.compile(r"(?i:\b(?:bearer|basic))[ \t]+([A-Za-z0-9._~+/=-]{8,})")
_CLE_VALEUR = re.compile(
    r"(?i:\b(?:api[_-]?key|apikey|secret|client[_-]?secret|(?:access|refresh|auth|id)[_-]?token|token|password|passwd|pwd|"
    r"mot[ _]de[ _]passe|cl[ée][ _]api|authorization|private[_-]?key))[\"']?[ \t]*[:=][ \t]*[\"']?([^\s\"',;]{6,})"
)
_USERINFO = re.compile(r"(?<=://)[^/\s:@]{1,64}:([^@\s/]{3,128})(?=@)")
_CANDIDAT_ENTROPIE = re.compile(r"(?<![A-Za-z0-9_+=-])[A-Za-z0-9_+-]{24,}={0,2}(?![A-Za-z0-9_+=-])")
_HEX = re.compile(r"^[0-9a-fA-F]+$")
SEUIL_ENTROPIE = 4.0


def entropie(valeur: str) -> float:
    """Entropie de Shannon (bits par caractère) de la distribution observée des caractères."""
    if not valeur:
        return 0.0
    n = len(valeur)
    return -sum(c / n * math.log2(c / n) for c in Counter(valeur).values())


def _ressemble_a_un_secret(candidat: str) -> bool:
    if _HEX.match(candidat):
        return False  # empreintes sha256/sha1/md5 et identifiants hexadécimaux : des identifiants, pas des secrets
    classes = (any(c.islower() for c in candidat), any(c.isupper() for c in candidat),
               any(c.isdigit() for c in candidat))
    return sum(classes) >= 2 and any(c.isdigit() for c in candidat) and entropie(candidat) >= SEUIL_ENTROPIE


def _secret(texte: str) -> Iterable[Detection]:
    for m in _PEM.finditer(texte):
        yield Detection("secret", m.start(), m.end(), m.group(0))
    for m in _PREFIXES_SECRETS.finditer(texte):
        yield Detection("secret", m.start(), m.end(), m.group(0))
    for motif in (_BEARER, _CLE_VALEUR, _USERINFO):
        for m in motif.finditer(texte):
            yield Detection("secret", m.start(1), m.end(1), m.group(1))
    for m in _CANDIDAT_ENTROPIE.finditer(texte):
        if _ressemble_a_un_secret(m.group(0)):
            yield Detection("secret", m.start(), m.end(), m.group(0))


# -- civilité + nom --------------------------------------------------------------------------------------------------
_NOM_MAJ = r"[A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÖØ-öø-ÿ'’-]{1,30}"
_NOM = re.compile(
    rf"(?<![\w])(?:M\.|Mme|Mlle|Mmes|MM\.|Me|Dr|Dre|Monsieur|Madame|Mademoiselle|Ma[iî]tre|Docteure?|Pr|Prof\.?)"
    rf"[ \t\u00a0]+{_NOM_MAJ}(?:[ \t\u00a0]+(?:(?:de|du|des|d['’]|la|le)[ \t\u00a0]*)?{_NOM_MAJ}){{0,2}}"
)


def _nom(texte: str) -> Iterable[Detection]:
    for m in _NOM.finditer(texte):
        yield Detection("nom", m.start(), m.end(), re.sub(r"\s+", " ", plier(m.group(0))))


def detecteur_lexique(noms: Iterable[str]) -> Callable[[str], Iterable[Detection]]:
    """Détecteur de noms exacts fournis par l'appelant (clients, employés connus du CRM) : la parade aux noms sans
    civilité."""
    valides = sorted({n.strip() for n in noms if isinstance(n, str) and len(n.strip()) >= 3}, key=len, reverse=True)
    if len(valides) > 5000:
        raise ValueError("lexique de noms : 5000 entrées au plus")
    if not valides:
        return lambda _texte: ()
    motif = re.compile(r"(?<![\w])(?:" + "|".join(re.escape(n) for n in valides) + r")(?![\w])", re.IGNORECASE)

    def trouver(texte: str) -> Iterable[Detection]:
        for m in motif.finditer(texte):
            yield Detection("nom", m.start(), m.end(), re.sub(r"\s+", " ", plier(m.group(0))))

    return trouver


DETECTEURS: tuple[Callable[[str], Iterable[Detection]], ...] = (
    _secret, _courriel, _carte, _nas, _ramq, _entreprise, _tel, _adresse, _code_postal, _nom,
)


def resoudre(detections: Iterable[Detection]) -> list[Detection]:
    """Retire les chevauchements : la catégorie la plus prioritaire, puis la plus longue, puis la plus à gauche
    gagne."""
    ordre = sorted(detections, key=lambda d: (PRIORITE[d.categorie], -(d.fin - d.debut), d.debut))
    retenues: list[Detection] = []
    for d in ordre:
        if d.fin <= d.debut:
            continue
        if all(d.fin <= r.debut or d.debut >= r.fin for r in retenues):
            retenues.append(d)
    return sorted(retenues, key=lambda d: d.debut)
