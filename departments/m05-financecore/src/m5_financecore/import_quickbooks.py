"""Reprise de l'historique QuickBooks Online par ses EXPORTS standard (onboarding comptable de M5, repli « exports »).

Module pur (ADR-0009, même règle que `grand_livre.py` et `reconciliation_bancaire_csv.py`) : aucun import d'`opsys`,
aucune horloge, aucun accès réseau ni appel à une API QuickBooks. Il reçoit les OCTETS des fichiers exportés
(l'adaptateur d'`outils.py` les lit dans un dossier confiné) et rend des structures validées, ou un refus typé
`REJ-QBO-*`.

Quatre rapports QuickBooks Online (QBO) sont compris, en français ou en anglais :
- la LISTE DES COMPTES (« Account List ») : nom complet, type QBO, type de détail, numéro éventuel ;
- la BALANCE DE VÉRIFICATION (« Trial Balance ») à une date : un solde débit OU crédit par compte, et la ligne TOTAL ;
- le JOURNAL (« Journal ») détaillé : chaque transaction (date, type, numéro, nom, mémo) et ses lignes débit/crédit ;
- une seconde balance de vérification, d'OUVERTURE, facultative.

Règles de lecture (tout ce qui n'est pas compris est un refus typé, jamais une supposition) :
- format : CSV (séparateur `,` `;` ou tabulation, choisi parce qu'UN SEUL fait apparaître l'en-tête attendu) ou classeur
  Excel `.xlsx` (première feuille, lu sans dépendance) ; `.xls` binaire, PDF et autres : refusés ;
- encodage : UTF-8 (avec ou sans BOM), UTF-16 avec BOM, sinon Windows-1252 ; l'encodage retenu est dit ;
- montants : point décimal (`1,234.56`) ou virgule décimale (`1 234,56`, espace ou espace insécable de milliers),
  symbole `$` avant ou après, signe `-` ou parenthèses pour un négatif ; au cent près ; une convention par fichier
  (deux conventions mêlées : `REJ-QBO-MONTANT-AMBIGU`) ;
- dates : `AAAA-MM-JJ`, `JJ/MM/AAAA` ou `MM/JJ/AAAA` (déduit des données, sinon `format_dates` explicite), mois en
  toutes lettres dans les titres (« As of December 31, 2025 », « Au 31 décembre 2025 ») ;
- lignes de TITRE (avant l'en-tête, une seule cellule), lignes VIDES, lignes de TOTAL (contrôlées contre la somme
  recalculée) et PIED de rapport (méthode de comptabilité, horodatage) : ignorées EXPLICITEMENT et comptées ; une
  balance « méthode de caisse » est refusée (le journal d'exercice ne la recalcule pas).

Correspondance des comptes QBO -> plan OPSYS (`proposer_correspondance`), déterministe et expliquée, dans cet ordre :
numéro QBO identique à un compte OPSYS de même classe ; nom reconnu (nom OPSYS ou table de synonymes versionnée) ;
type QBO qui n'a qu'un compte naturel (banque, comptes clients, comptes fournisseurs) quand la liste n'a qu'UN compte de
ce type. Sinon le compte reste NON APPARIÉ : jamais un compte « divers » par défaut. La correspondance proposée est un
BROUILLON ; la correspondance VALIDÉE (`valider_correspondance`, avec les choix manuels de l'humain) n'a plus aucun
compte non apparié, respecte les classes (actif, passif, capitaux propres, produits, charges) et est versionnée par
l'adaptateur.

Import (`preparer_import`) : la balance de vérification RECALCULÉE (ouverture éventuelle + journal) doit égaler AU CENT
la balance exportée, compte QBO par compte QBO et au total, sinon `REJ-QBO-BALANCE-ECART` avec le détail des écarts ;
chaque transaction est équilibrée. Deux modes : `detail` (une écriture par transaction QBO, plus une écriture
d'ouverture si une balance d'ouverture est fournie) et `ouverture` (une seule écriture, au solde de la balance de
vérification à la date de reprise). Les écritures rendues sont des PROPOSITIONS de brouillons du grand livre (pièce
`import_quickbooks`, numéro de transaction QBO et empreinte du fichier) ; `comparer_au_grand_livre` dit lesquelles
existent déjà (même contenu : rien à écrire) et lesquelles sont en CONFLIT (même numéro de transaction, autre contenu).
"""

from __future__ import annotations

import calendar
import csv
import hashlib
import io
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from collections.abc import Iterable, Mapping
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from . import encodage, grand_livre, plan_comptable

__all__ = [
    "CODES_QBO",
    "construire_verdict",
    "analyser_liste_comptes",
    "analyser_balance",
    "analyser_journal",
    "empreinte_liste",
    "proposer_correspondance",
    "valider_correspondance",
    "verifier_reprise",
    "preparer_import",
    "comparer_au_grand_livre",
    "empreinte_lot",
]

CODES_QBO = [
    "REJ-QBO-FICHIER-INVALIDE",
    "REJ-QBO-FORMAT-NON-PRIS-EN-CHARGE",
    "REJ-QBO-ENCODAGE",
    "REJ-QBO-CSV-ILLISIBLE",
    "REJ-QBO-ENTETES-INCONNUES",
    "REJ-QBO-SEPARATEUR-AMBIGU",
    "REJ-QBO-LIGNE-INCOMPRISE",
    "REJ-QBO-MONTANT-INVALIDE",
    "REJ-QBO-MONTANT-AMBIGU",
    "REJ-QBO-DATE-INVALIDE",
    "REJ-QBO-DATE-AMBIGUE",
    "REJ-QBO-DATE-INTROUVABLE",
    "REJ-QBO-TOTAL-ABSENT",
    "REJ-QBO-TOTAL-INCOHERENT",
    "REJ-QBO-BALANCE-DESEQUILIBREE",
    "REJ-QBO-METHODE-CAISSE",
    "REJ-QBO-DEVISE-NON-GEREE",
    "REJ-QBO-TYPE-COMPTE-INCONNU",
    "REJ-QBO-COMPTE-DUPLIQUE",
    "REJ-QBO-COMPTE-HORS-LISTE",
    "REJ-QBO-TRANSACTION-SANS-NUMERO",
    "REJ-QBO-TRANSACTION-DUPLIQUEE",
    "REJ-QBO-TRANSACTION-DESEQUILIBREE",
    "REJ-QBO-TRANSACTION-TROP-LONGUE",
    "REJ-QBO-CHAMP-INVALIDE",
    "REJ-QBO-MODE-INVALIDE",
    "REJ-QBO-DATE-REPRISE-DIFFERENTE",
    "REJ-QBO-DATE-HORS-PERIODE",
    "REJ-QBO-EXERCICE-INCONNU",
    "REJ-QBO-EXERCICES-MULTIPLES",
    "REJ-QBO-BNR-INTROUVABLE",
    "REJ-QBO-COMPTES-NON-APPARIES",
    "REJ-QBO-CORRESPONDANCE-INVALIDE",
    "REJ-QBO-CORRESPONDANCE-INTROUVABLE",
    "REJ-QBO-CORRESPONDANCE-PERIMEE",
    "REJ-QBO-BALANCE-ECART",
    "REJ-QBO-ECRITURE-TROP-LONGUE",
    "REJ-QBO-TRANSACTION-CONFLIT",
    "REJ-QBO-IMPORT-INTROUVABLE",
    "REJ-QBO-LOT-PERIME",
]
_CODES = frozenset(CODES_QBO)


class CodeImportQuickbooksInconnu(ValueError):
    pass


def construire_verdict(code: str, detail: str = "", **complements: Any) -> dict[str, Any]:
    """`{code, detail}` (et des compléments bornés : `ligne`, `ecarts`, `comptes`...). Un code hors catalogue lève."""
    if code not in _CODES:
        raise CodeImportQuickbooksInconnu(f"code de refus de l'import QuickBooks inconnu : {code!r}")
    return {"code": code, "detail": detail, **complements}


def _refus(code: str, detail: str, **complements: Any) -> tuple[None, dict[str, Any]]:
    return None, construire_verdict(code, detail, **complements)


OCTETS_MAX = 5 * 1024 * 1024
LIGNES_MAX = 100_000
CELLULE_MAX = 1_000
NOM_COMPTE_MAX = 300
CHAMP_TRANSACTION_MAX = 40
LIGNES_ECRITURE_MAX = 50  # la borne de `grand_livre.normaliser_lignes`
_LISTE_MAX = 10
_CENT = Decimal("0.01")
_ZERO = Decimal("0.00")
_MONTANT_MAX = Decimal("999999999999.99")
_ENTETE_RECHERCHE_MAX = 40
_XLSX_MEMBRES_MAX = 2_000
_XLSX_OCTETS_DECOMPRESSES_MAX = 60 * 1024 * 1024
_COLONNES_MAX = 16_384  # dernière colonne d'un classeur (« XFD ») : au-delà, la rangée serait construite à vide
_EXPOSANT_CELLULE_MAX = 18  # au plus 19 chiffres entiers : bien au-delà de _MONTANT_MAX (12 chiffres)
_PIECE = "import_quickbooks"
TABLE_SYNONYMES_VERSION = "qbo-synonymes-v1"


# ============================================================================================== normalisation
def _normaliser(texte: str) -> str:
    """Forme de comparaison d'un libellé : sans accents, minuscules, ponctuation en espaces (`#` et `№` -> numero)."""
    brut = texte.replace("#", " numero ").replace("№", " numero ")
    replie = unicodedata.normalize("NFKD", brut)
    replie = "".join(c for c in replie if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", " ", replie).strip()


def _une_ligne(texte: str) -> str:
    return re.sub(r"\s+", " ", texte).strip()


def _texte(valeur: Decimal) -> str:
    return str(valeur.quantize(_CENT, rounding=ROUND_HALF_UP))


# ============================================================================================== montants
_POINT = re.compile(r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?")
_VIRGULE = re.compile(r"(?:\d{1,3}(?:[ \u00a0\u202f.]\d{3})+|\d+)(?:,\d{1,2})?")
_BLANCS = " \t\u00a0\u202f"


def _montant(texte: str) -> tuple[Decimal | None, str | None, str | None]:
    """`(montant signé au cent | None si la cellule est vide, convention 'point'|'virgule'|None si neutre, erreur)`.
    Une chaîne n'a jamais deux lectures : un groupe de milliers a exactement trois chiffres, une partie décimale au plus
    deux ; `123` (sans séparateur) est neutre."""
    t = texte.strip(_BLANCS)
    if not t:
        return None, None, None
    negatif = False
    if t.startswith("(") and t.endswith(")"):
        negatif, t = True, t[1:-1].strip(_BLANCS)
    if t.startswith("-"):
        if negatif:
            return None, None, "double signe négatif"
        negatif, t = True, t[1:].strip(_BLANCS)
    if t.startswith("$"):
        t = t[1:].strip(_BLANCS)
    elif t.endswith("$"):
        t = t[:-1].strip(_BLANCS)
    if t.startswith("-") and not negatif:
        negatif, t = True, t[1:].strip(_BLANCS)
    if not t or "$" in t:
        return None, None, "montant illisible"
    point, virgule = _POINT.fullmatch(t), _VIRGULE.fullmatch(t)
    try:
        if point and virgule:
            convention, valeur = None, Decimal(t)
        elif point:
            convention, valeur = "point", Decimal(t.replace(",", ""))
        elif virgule:
            convention, valeur = "virgule", Decimal(re.sub(r"[ \u00a0\u202f.]", "", t).replace(",", "."))
        else:
            return None, None, "montant illisible (séparateurs, décimales au-delà du cent ou texte)"
    except InvalidOperation:
        return None, None, "montant illisible"
    if valeur > _MONTANT_MAX:
        return None, None, "montant hors domaine"
    valeur = valeur.quantize(_CENT, rounding=ROUND_HALF_UP)  # exact : deux décimales au plus
    return (-valeur if negatif else valeur), convention, None


# ============================================================================================== dates
_MOIS = {
    "january": 1, "jan": 1, "janvier": 1, "janv": 1,
    "february": 2, "feb": 2, "fevrier": 2, "fevr": 2, "fev": 2,
    "march": 3, "mar": 3, "mars": 3,
    "april": 4, "apr": 4, "avril": 4, "avr": 4,
    "may": 5, "mai": 5,
    "june": 6, "jun": 6, "juin": 6,
    "july": 7, "jul": 7, "juillet": 7, "juil": 7,
    "august": 8, "aug": 8, "aout": 8,
    "september": 9, "sep": 9, "sept": 9, "septembre": 9,
    "october": 10, "oct": 10, "octobre": 10,
    "november": 11, "nov": 11, "novembre": 11,
    "december": 12, "dec": 12, "decembre": 12,
}
_DATE_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_DATE_BARRE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
_FORMATS_DATES = ("auto", "AAAA-MM-JJ", "JJ/MM/AAAA", "MM/JJ/AAAA")
_EPOQUE_EXCEL = date(1899, 12, 30)


def _jour(annee: int, mois: int, jour: int) -> date | None:
    try:
        return date(annee, mois, jour)
    except ValueError:
        return None


def _convention_dates(textes: Iterable[str], format_dates: str) -> tuple[str | None, dict[str, Any] | None]:
    """La convention des dates `JJ/MM/AAAA` ou `MM/JJ/AAAA` d'un fichier : explicite, ou déduite des données (un jour
    au-delà de 12). Les deux observées, ou aucune preuve alors qu'une date est ambiguë : refus."""
    if format_dates != "auto":
        return format_dates, None
    vues: set[str] = set()
    ambigue = False
    for texte in textes:
        correspondance = _DATE_BARRE.fullmatch(texte)
        if correspondance is None:
            continue
        premier, second = int(correspondance.group(1)), int(correspondance.group(2))
        if premier > 12:
            vues.add("JJ/MM/AAAA")
        elif second > 12:
            vues.add("MM/JJ/AAAA")
        elif premier != second:
            ambigue = True
    if len(vues) > 1:
        return None, construire_verdict("REJ-QBO-DATE-AMBIGUE", "dates JJ/MM et MM/JJ mêlées dans le même fichier")
    if vues:
        return vues.pop(), None
    if ambigue:
        return None, construire_verdict(
            "REJ-QBO-DATE-AMBIGUE", "dates JJ/MM/AAAA ou MM/JJ/AAAA indécidables (aucun jour au-delà de 12) : "
            "préciser format_dates")
    return "AAAA-MM-JJ", None


def _date_cellule(texte: str, convention: str | None, source_xlsx: bool) -> date | None:
    t = texte.strip()
    correspondance = _DATE_ISO.fullmatch(t)
    if correspondance:
        return _jour(int(correspondance.group(1)), int(correspondance.group(2)), int(correspondance.group(3)))
    correspondance = _DATE_BARRE.fullmatch(t)
    if correspondance:
        a, b, annee = (int(g) for g in correspondance.groups())
        if convention == "MM/JJ/AAAA":
            return _jour(annee, a, b)
        if convention == "JJ/MM/AAAA" or a == b:
            return _jour(annee, b, a)
        return None
    if source_xlsx and re.fullmatch(r"\d{4,6}", t):  # numéro de série Excel d'une cellule date (système 1900)
        return _EPOQUE_EXCEL + timedelta(days=int(t))
    return None


def _dates_en_lettres(texte: str) -> list[date]:
    """Les dates écrites en toutes lettres (EN « December 31, 2025 », FR « 31 décembre 2025 », « 1er janvier ») ou
    ISO dans une ligne de titre, dans l'ordre."""
    t = _normaliser(texte)
    trouvees: list[tuple[int, date]] = []
    for m in re.finditer(r"\b([a-z]+) (\d{1,2}) (\d{4})\b", t):
        mois, jour = _MOIS.get(m.group(1)), int(m.group(2))
        valeur = _jour(int(m.group(3)), mois, jour) if mois else None
        if valeur:
            trouvees.append((m.start(), valeur))
    for m in re.finditer(r"\b(\d{1,2})(?: ?er)? ([a-z]+) (\d{4})\b", t):
        mois = _MOIS.get(m.group(2))
        valeur = _jour(int(m.group(3)), mois, int(m.group(1))) if mois else None
        if valeur:
            trouvees.append((m.start(), valeur))
    for m in re.finditer(r"\b(\d{4}) (\d{2}) (\d{2})\b", t):
        valeur = _jour(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if valeur:
            trouvees.append((m.start(), valeur))
    return [valeur for _position, valeur in sorted(trouvees)]


# ============================================================================================== lecture tabulaire
def _decoder(contenu: bytes) -> tuple[str | None, str | None]:
    if contenu.startswith(b"\xef\xbb\xbf"):
        essais = [("utf-8-sig", "UTF-8 (BOM)")]
    elif contenu.startswith((b"\xff\xfe", b"\xfe\xff")):
        essais = [("utf-16", "UTF-16 (BOM)")]
    else:
        essais = [("utf-8", "UTF-8"), ("cp1252", "Windows-1252")]
    for codec, nom in essais:
        try:
            return contenu.decode(codec, errors="strict"), nom
        except UnicodeDecodeError:
            continue
    return None, None


_NS_FEUILLE = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_NS_REL_DOC = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_NS_REL_PAQUET = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _xml(archive: zipfile.ZipFile, nom: str) -> ET.Element:
    octets = archive.read(nom)
    if b"<!DOCTYPE" in octets or b"<!ENTITY" in octets:
        raise ValueError("XML avec déclaration de type refusé")
    return ET.fromstring(octets)


def _colonne_excel(reference: str) -> int:
    lettres = re.match(r"[A-Z]+", reference or "")
    if lettres is None:
        raise ValueError("référence de cellule invalide")
    index = 0
    for lettre in lettres.group(0):
        index = index * 26 + (ord(lettre) - 64)
        if index > _COLONNES_MAX:
            raise ValueError("colonne hors des limites d'un classeur")
    return index - 1


def _nombre_excel(valeur: str) -> str:
    """Le texte d'un nombre de classeur, sans passer par un flottant : au cent s'il n'en diffère que d'un artefact de
    représentation binaire (moins d'un millionième), sinon tel quel (et la lecture du montant le refusera)."""
    try:
        nombre = Decimal(valeur)
    except InvalidOperation:
        return valeur
    if not nombre.is_finite():
        return valeur
    if nombre.adjusted() > _EXPOSANT_CELLULE_MAX:
        # Ni un montant ni un numéro de série de date : rendu tel quel, la lecture du montant le refusera. Sans cette
        # borne, `int(1E+99999999)` calcule pendant des minutes et `quantize` de plus de 28 chiffres lève.
        return valeur
    if nombre == nombre.to_integral_value():
        return str(int(nombre))
    arrondi = nombre.quantize(_CENT, rounding=ROUND_HALF_UP)
    if abs(arrondi - nombre) < Decimal("0.000001"):
        return str(arrondi)
    return str(nombre)


def _lire_xlsx(contenu: bytes) -> tuple[list[list[str]] | None, dict[str, Any] | None]:
    """Les lignes (texte) de la PREMIÈRE feuille d'un classeur `.xlsx`, avec la bibliothèque standard seulement."""
    try:
        archive = zipfile.ZipFile(io.BytesIO(contenu))
        membres = archive.infolist()
        if len(membres) > _XLSX_MEMBRES_MAX or sum(m.file_size for m in membres) > _XLSX_OCTETS_DECOMPRESSES_MAX:
            return _refus("REJ-QBO-FICHIER-INVALIDE", "classeur trop volumineux une fois décompressé")
        noms = {m.filename for m in membres}
        classeur = _xml(archive, "xl/workbook.xml")
        feuille = classeur.find(f"{_NS_FEUILLE}sheets/{_NS_FEUILLE}sheet")
        if feuille is None:
            return _refus("REJ-QBO-FORMAT-NON-PRIS-EN-CHARGE", "classeur sans feuille")
        relation = feuille.get(f"{_NS_REL_DOC}id")
        cible = None
        for rel in _xml(archive, "xl/_rels/workbook.xml.rels").iter(f"{_NS_REL_PAQUET}Relationship"):
            if rel.get("Id") == relation:
                cible = rel.get("Target", "")
        if not cible:
            return _refus("REJ-QBO-FORMAT-NON-PRIS-EN-CHARGE", "feuille du classeur introuvable")
        chemin = cible.lstrip("/") if cible.startswith("/") else "xl/" + cible
        partages: list[str] = []
        if "xl/sharedStrings.xml" in noms:
            for element in _xml(archive, "xl/sharedStrings.xml").iter(f"{_NS_FEUILLE}si"):
                partages.append("".join(t.text or "" for t in element.iter(f"{_NS_FEUILLE}t")))
        lignes: list[list[str]] = []
        for rangee in _xml(archive, chemin).iter(f"{_NS_FEUILLE}row"):
            numero = int(rangee.get("r", len(lignes) + 1))
            if numero < len(lignes) + 1 or numero > LIGNES_MAX:
                return _refus("REJ-QBO-FORMAT-NON-PRIS-EN-CHARGE",
                              "rangées du classeur hors d'ordre ou trop nombreuses")
            while len(lignes) < numero - 1:
                lignes.append([])
            cellules: dict[int, str] = {}
            for cellule in rangee.iter(f"{_NS_FEUILLE}c"):
                genre = cellule.get("t", "n")
                v = cellule.find(f"{_NS_FEUILLE}v")
                if genre == "s":
                    texte = partages[int(v.text)] if v is not None and v.text is not None else ""
                elif genre == "inlineStr":
                    texte = "".join(t.text or "" for t in cellule.iter(f"{_NS_FEUILLE}t"))
                elif genre == "str":
                    texte = v.text or "" if v is not None else ""
                elif genre == "n":
                    texte = _nombre_excel(v.text) if v is not None and v.text else ""
                else:
                    return _refus("REJ-QBO-FORMAT-NON-PRIS-EN-CHARGE",
                                  f"cellule de type {genre!r} (erreur ou booléen) dans le classeur")
                cellules[_colonne_excel(cellule.get("r", ""))] = texte
            largeur = max(cellules) + 1 if cellules else 0
            lignes.append([cellules.get(index, "") for index in range(largeur)])
        return lignes, None
    except (zipfile.BadZipFile, KeyError, ValueError, IndexError, ET.ParseError, RuntimeError):
        return _refus("REJ-QBO-FORMAT-NON-PRIS-EN-CHARGE", "classeur .xlsx illisible")


def _sources(contenu: Any) -> tuple[list[tuple[str | None, list[list[str]]]] | None, dict[str, Any], dict | None]:
    """Les lectures candidates d'un fichier : `[(séparateur, lignes)]` (un seul candidat pour un classeur), la
    description de la lecture (format, encodage), ou le refus."""
    if not isinstance(contenu, bytes) or not contenu:
        return None, {}, construire_verdict("REJ-QBO-FICHIER-INVALIDE", "fichier vide ou absent")
    if len(contenu) > OCTETS_MAX:
        return None, {}, construire_verdict("REJ-QBO-FICHIER-INVALIDE", "fichier de plus de 5 Mio")
    lecture: dict[str, Any] = {"sha256": hashlib.sha256(contenu).hexdigest(), "octets": len(contenu)}
    if contenu.startswith(b"PK\x03\x04"):
        lignes, refus = _lire_xlsx(contenu)
        if refus is not None:
            return None, lecture, refus
        return [(None, lignes)], {**lecture, "format": "xlsx", "encodage": None}, None
    if contenu.startswith(b"\xd0\xcf\x11\xe0") or contenu.startswith(b"%PDF"):
        return None, lecture, construire_verdict(
            "REJ-QBO-FORMAT-NON-PRIS-EN-CHARGE", "classeur .xls binaire ou PDF : exporter en CSV ou en .xlsx")
    texte, encodage_nom = _decoder(contenu)
    if texte is None:
        return None, lecture, construire_verdict("REJ-QBO-ENCODAGE", "ni UTF-8, ni UTF-16 avec BOM, ni Windows-1252")
    if "\x00" in texte:
        return None, lecture, construire_verdict("REJ-QBO-ENCODAGE", "caractère nul dans le texte")
    candidats = []
    for separateur in (",", ";", "\t"):
        try:
            lignes = list(csv.reader(io.StringIO(texte, newline=""), delimiter=separateur, strict=True))
        except csv.Error:
            continue
        if len(lignes) > LIGNES_MAX:
            return None, lecture, construire_verdict("REJ-QBO-FICHIER-INVALIDE", f"plus de {LIGNES_MAX} lignes")
        candidats.append((separateur, lignes))
    if not candidats:
        return None, lecture, construire_verdict("REJ-QBO-CSV-ILLISIBLE", "CSV mal formé (guillemets)")
    return candidats, {**lecture, "format": "csv", "encodage": encodage_nom}, None


# ============================================================================================== en-têtes
_COLONNES = {
    "liste_comptes": {
        "nom": {"account", "compte", "nom", "nom du compte", "account name", "full name", "nom complet",
                "account full name", "nom complet du compte"},
        "type": {"type", "account type", "type de compte"},
        "detail": {"detail type", "type de detail", "type detaille", "type de details"},
        "numero": {"account numero", "account number", "numero de compte", "n de compte", "no de compte", "numero",
                   "compte numero", "account no"},
        "devise": {"currency", "devise"},
    },
    "balance": {
        "compte": {"account", "compte", "nom du compte", "account name"},
        "debit": {"debit"},
        "credit": {"credit"},
        "devise": {"currency", "devise"},
    },
    "journal": {
        "date": {"date", "transaction date", "date de transaction", "date de la transaction"},
        "type": {"transaction type", "type de transaction", "type"},
        "num": {"num", "no", "n", "numero", "ref no", "no de reference", "n de reference", "numero de reference",
                "numero de transaction", "n de transaction"},
        "nom": {"name", "nom"},
        "memo": {"memo description", "memo", "description"},
        "compte": {"account", "compte", "account full name", "nom complet du compte", "full name"},
        "debit": {"debit"},
        "credit": {"credit"},
        "devise": {"currency", "devise"},
    },
}
_REQUIS = {
    "liste_comptes": ("nom", "type"),
    "balance": ("compte", "debit", "credit"),
    "journal": ("date", "type", "num", "compte", "debit", "credit"),
}
_NOMS_RAPPORTS = {"liste_comptes": "liste des comptes (Account List)",
                  "balance": "balance de vérification (Trial Balance)", "journal": "journal (Journal)"}


def _entete(ligne: list[str], genre: str) -> tuple[dict[str, int], list[str]] | None:
    """Les colonnes reconnues d'une ligne d'en-tête (`{rôle: index}`) et les en-têtes ignorés, si la ligne porte tous
    les rôles requis, chacun une fois. Balance : le compte peut être la colonne sans en-tête avant le débit."""
    roles: dict[str, int] = {}
    ignorees: list[str] = []
    for index, cellule in enumerate(ligne):
        normal = _normaliser(cellule)
        trouves = [role for role, synonymes in _COLONNES[genre].items() if normal in synonymes]
        if not trouves:
            if normal:
                ignorees.append(cellule.strip())
            continue
        if trouves[0] in roles:
            return None
        roles[trouves[0]] = index
    if genre == "balance" and "compte" not in roles and "debit" in roles:
        vides = [i for i, c in enumerate(ligne) if not c.strip() and i < roles["debit"]]
        if vides:
            roles["compte"] = vides[0]
    if not all(role in roles for role in _REQUIS[genre]):
        return None
    return roles, ignorees


def _tableau(contenu: Any, genre: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Le tableau d'un rapport : lecture retenue (séparateur unique qui fait apparaître l'en-tête), index de l'en-tête,
    colonnes, lignes de titre, corps (lignes numérotées à partir de 1) et pied ; refus sinon."""
    candidats, lecture, refus = _sources(contenu)
    if refus is not None:
        return None, refus
    retenus = []
    for separateur, lignes in candidats:
        for index, ligne in enumerate(lignes[:_ENTETE_RECHERCHE_MAX]):
            entete = _entete(ligne, genre)
            if entete is not None:
                retenus.append((separateur, lignes, index, entete))
                break
    if not retenus:
        attendus = ", ".join(_REQUIS[genre])
        return _refus("REJ-QBO-ENTETES-INCONNUES",
                      f"en-tête de {_NOMS_RAPPORTS[genre]} introuvable (colonnes requises : {attendus})")
    if len(retenus) > 1:
        return _refus("REJ-QBO-SEPARATEUR-AMBIGU", "plusieurs séparateurs font apparaître l'en-tête")
    separateur, lignes, index_entete, (colonnes, ignorees) = retenus[0]
    titres = []
    for numero, ligne in enumerate(lignes[:index_entete], start=1):
        remplies = [c.strip() for c in ligne if c.strip()]
        if len(remplies) > 1:
            return _refus("REJ-QBO-LIGNE-INCOMPRISE", "ligne de titre à plusieurs cellules avant l'en-tête",
                          ligne=numero)
        if remplies:
            titres.append(remplies[0][:CELLULE_MAX])
    largeur = len(lignes[index_entete])
    corps: list[tuple[int, list[str]]] = []
    for numero, ligne in enumerate(lignes[index_entete + 1:], start=index_entete + 2):
        if any(len(c) > CELLULE_MAX for c in ligne):
            return _refus("REJ-QBO-LIGNE-INCOMPRISE", "cellule trop longue", ligne=numero)
        if len(ligne) > largeur and any(c.strip() for c in ligne[largeur:]):
            return _refus("REJ-QBO-LIGNE-INCOMPRISE", "plus de cellules que de colonnes d'en-tête", ligne=numero)
        corps.append((numero, [c.strip() for c in ligne[:largeur]] + [""] * max(0, largeur - len(ligne))))
    # Le pied : la plus longue suite finale de lignes vides ou d'une seule cellule (méthode, horodatage).
    pied: list[str] = []
    vides_du_pied = 0
    while corps:
        remplies = [c for c in corps[-1][1] if c]
        if len(remplies) > 1:
            break
        if remplies:
            pied.insert(0, remplies[0])
        else:
            vides_du_pied += 1
        corps.pop()
    textes = titres + pied
    methode = "non_indiquee"
    for texte in textes:
        normal = _normaliser(texte)
        if "cash basis" in normal or "methode de caisse" in normal or "comptabilite de caisse" in normal:
            return _refus("REJ-QBO-METHODE-CAISSE",
                          "rapport en méthode de caisse : exporter en comptabilité d'exercice (Accrual Basis)")
        if "accrual basis" in normal or "comptabilite d exercice" in normal:
            methode = "exercice"
    return {
        "lecture": {**lecture, "separateur": {",": "virgule", ";": "point-virgule", "\t": "tabulation"}.get(
            separateur) if separateur else None, "ligne_entete": index_entete + 1,
            "colonnes_ignorees": ignorees[:_LISTE_MAX], "lignes_titre": titres[:5], "methode": methode,
            "lignes_ignorees": {"titre": len(titres), "pied": len(pied), "vides": vides_du_pied, "totaux": 0}},
        "colonnes": colonnes, "titres": titres, "corps": corps, "xlsx": lecture.get("format") == "xlsx",
    }, None


def _cellule(ligne: list[str], colonnes: Mapping[str, int], role: str) -> str:
    index = colonnes.get(role)
    return ligne[index] if index is not None and index < len(ligne) else ""


class _Montants:
    """Lit les montants d'un fichier et vérifie qu'il n'emploie qu'UNE convention décimale."""

    def __init__(self) -> None:
        self.conventions: set[str] = set()

    def lire(self, texte: str, numero: int) -> tuple[Decimal | None, dict[str, Any] | None]:
        valeur, convention, erreur = _montant(texte)
        if erreur is not None:
            return None, construire_verdict("REJ-QBO-MONTANT-INVALIDE", erreur, ligne=numero)
        if convention is not None:
            self.conventions.add(convention)
            if len(self.conventions) > 1:
                return None, construire_verdict(
                    "REJ-QBO-MONTANT-AMBIGU", "point décimal et virgule décimale mêlés dans le même fichier",
                    ligne=numero)
        return valeur, None

    @property
    def convention(self) -> str:
        return next(iter(self.conventions), "neutre")


def _devise_cad(ligne: list[str], colonnes: Mapping[str, int], numero: int) -> dict[str, Any] | None:
    devise = _cellule(ligne, colonnes, "devise")
    if devise and devise.upper() not in ("CAD", "$ CA", "CA$"):
        return construire_verdict("REJ-QBO-DEVISE-NON-GEREE", f"devise {devise!r} : seul le CAD est géré",
                                  ligne=numero)
    return None


def _debit_credit(
    ligne: list[str], colonnes: Mapping[str, int], numero: int, montants: _Montants
) -> tuple[tuple[Decimal | None, Decimal | None] | None, dict[str, Any] | None]:
    debit, refus = montants.lire(_cellule(ligne, colonnes, "debit"), numero)
    if refus is not None:
        return None, refus
    credit, refus = montants.lire(_cellule(ligne, colonnes, "credit"), numero)
    if refus is not None:
        return None, refus
    return (debit, credit), None


def _est_total(texte: str) -> bool:
    normal = _normaliser(texte)
    return normal == "total" or normal.startswith("total ")


# ============================================================================================== la liste des comptes
_TYPES_QBO = {
    "bank": ("actif", {"bank", "banque"}),
    "accounts_receivable": ("actif", {"accounts receivable a r", "accounts receivable", "comptes clients",
                                      "comptes clients c c", "comptes debiteurs"}),
    "other_current_assets": ("actif", {"other current assets", "other current asset", "autres actifs a court terme",
                                       "autres actifs courants", "actifs a court terme"}),
    "fixed_assets": ("actif", {"fixed assets", "fixed asset", "immobilisations", "immobilisations corporelles"}),
    "other_assets": ("actif", {"other assets", "other asset", "autres actifs"}),
    "accounts_payable": ("passif", {"accounts payable a p", "accounts payable", "comptes fournisseurs",
                                    "comptes fournisseurs c f", "comptes crediteurs"}),
    "credit_card": ("passif", {"credit card", "carte de credit"}),
    "other_current_liabilities": ("passif", {"other current liabilities", "other current liability",
                                             "autres passifs a court terme", "passifs a court terme",
                                             "autres passifs courants"}),
    "long_term_liabilities": ("passif", {"long term liabilities", "long term liability", "passifs a long terme",
                                         "passif a long terme"}),
    "equity": ("capitaux_propres", {"equity", "capitaux propres", "avoir des proprietaires"}),
    "income": ("produits", {"income", "revenus", "revenu", "produits"}),
    "other_income": ("produits", {"other income", "autres revenus", "autres produits"}),
    "cost_of_goods_sold": ("charges", {"cost of goods sold", "cout des marchandises vendues", "cout des ventes"}),
    "expenses": ("charges", {"expenses", "expense", "depenses", "charges"}),
    "other_expense": ("charges", {"other expense", "other expenses", "autres depenses", "autres charges"}),
}
_TYPE_PAR_LIBELLE = {libelle: cle for cle, (_classe, libelles) in _TYPES_QBO.items() for libelle in libelles}
_DETAILS_BNR = {"retained earnings", "benefices non repartis"}


def analyser_liste_comptes(contenu: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """La liste des comptes QBO : `{rapport, lecture, comptes: [{nom, type_qbo, type_cle, classe, detail, numero}]}`
    triée par nom, ou un refus (type QBO inconnu, compte ou numéro répété, devise autre que CAD, ligne incomprise)."""
    tableau, refus = _tableau(contenu, "liste_comptes")
    if refus is not None:
        return None, refus
    colonnes = tableau["colonnes"]
    comptes: dict[str, dict[str, Any]] = {}
    numeros: set[str] = set()
    inconnus: list[str] = []
    vides = 0
    for numero_ligne, ligne in tableau["corps"]:
        if not any(ligne):
            vides += 1
            continue
        nom, type_brut = _une_ligne(_cellule(ligne, colonnes, "nom")), _cellule(ligne, colonnes, "type")
        if not nom or not type_brut:
            return _refus("REJ-QBO-LIGNE-INCOMPRISE", "compte sans nom ou sans type", ligne=numero_ligne)
        if len(nom) > NOM_COMPTE_MAX:
            return _refus("REJ-QBO-CHAMP-INVALIDE", "nom de compte trop long", ligne=numero_ligne)
        refus = _devise_cad(ligne, colonnes, numero_ligne)
        if refus is not None:
            return None, refus
        type_cle = _TYPE_PAR_LIBELLE.get(_normaliser(type_brut))
        if type_cle is None:
            inconnus.append(f"{nom} ({type_brut})")
            continue
        if nom in comptes:
            return _refus("REJ-QBO-COMPTE-DUPLIQUE", f"compte {nom!r} listé deux fois", ligne=numero_ligne)
        numero = _cellule(ligne, colonnes, "numero") or None
        if numero is not None:
            if numero in numeros:
                return _refus("REJ-QBO-COMPTE-DUPLIQUE", f"numéro {numero!r} porté par deux comptes",
                              ligne=numero_ligne)
            numeros.add(numero)
        comptes[nom] = {"nom": nom, "type_qbo": type_brut, "type_cle": type_cle, "classe": _TYPES_QBO[type_cle][0],
                        "detail": _cellule(ligne, colonnes, "detail") or None, "numero": numero}
    if inconnus:
        return _refus("REJ-QBO-TYPE-COMPTE-INCONNU", f"{len(inconnus)} compte(s) de type QBO non reconnu",
                      comptes=inconnus[:_LISTE_MAX])
    if not comptes:
        return _refus("REJ-QBO-LIGNE-INCOMPRISE", "liste des comptes vide")
    lecture = tableau["lecture"]
    lecture["lignes_ignorees"]["vides"] += vides
    return {"rapport": "liste_comptes", "lecture": lecture,
            "comptes": [comptes[nom] for nom in sorted(comptes)]}, None


def empreinte_liste(liste: Mapping[str, Any]) -> str:
    """L'empreinte de l'ENSEMBLE des comptes (nom, type) : un nouvel export de la même liste (soldes ou horodatage
    différents) garde la même ; un compte ajouté, retiré ou retypé la change."""
    return encodage.empreinte("m5.qbo.liste_comptes.v1", sorted((c["nom"], c["type_cle"]) for c in liste["comptes"]))


def _index_comptes(liste: Mapping[str, Any]) -> dict[str, str]:
    index: dict[str, str] = {}
    for compte in liste["comptes"]:
        index[compte["nom"]] = compte["nom"]
        if compte["numero"]:
            index.setdefault(f"{compte['numero']} {compte['nom']}", compte["nom"])
    return index


def _resoudre(noms: Iterable[str], liste: Mapping[str, Any]) -> tuple[dict[str, str] | None, dict | None]:
    """`{nom tel qu'écrit dans le rapport: nom de la liste}` ; des comptes absents de la liste : un refus qui les
    nomme."""
    index = _index_comptes(liste)
    resolus, absents = {}, []
    for nom in noms:
        if nom in index:
            resolus[nom] = index[nom]
        else:
            absents.append(nom)
    if absents:
        return _refus("REJ-QBO-COMPTE-HORS-LISTE", f"{len(absents)} compte(s) absents de la liste des comptes",
                      comptes=sorted(absents)[:_LISTE_MAX])
    return resolus, None


# ====================================================================================== la balance de vérification
def analyser_balance(contenu: Any, format_dates: str = "auto") -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Une balance de vérification QBO : `{rapport, date, lecture, lignes: [{compte, debit, credit, ligne}],
    soldes: {compte: débit moins crédit}, total_debits, total_credits}`. La date vient du titre (« As of ... »,
    « Au ... »). La ligne TOTAL est exigée et contrôlée contre la somme des colonnes ; débits = crédits."""
    if format_dates not in _FORMATS_DATES:
        return _refus("REJ-QBO-CHAMP-INVALIDE", f"format_dates parmi {list(_FORMATS_DATES)}")
    tableau, refus = _tableau(contenu, "balance")
    if refus is not None:
        return None, refus
    colonnes = tableau["colonnes"]
    dates = [d for titre in tableau["titres"] for d in _dates_en_lettres(titre)]
    if not dates:
        for titre in tableau["titres"]:
            for morceau in re.findall(r"\d{1,2}/\d{1,2}/\d{4}", titre):
                convention, refus = _convention_dates([morceau], format_dates)
                if refus is not None:
                    return None, refus
                trouvee = _date_cellule(morceau, convention, False)
                if trouvee:
                    dates.append(trouvee)
    if not dates:
        return _refus("REJ-QBO-DATE-INTROUVABLE", "date de la balance introuvable dans le titre (« As of … » / "
                      "« Au … »)")
    date_balance = dates[-1]
    montants = _Montants()
    lignes: list[dict[str, Any]] = []
    soldes: dict[str, Decimal] = {}
    total = None
    vides = 0
    debits = credits = _ZERO
    for numero_ligne, ligne in tableau["corps"]:
        if not any(ligne):
            vides += 1
            continue
        if total is not None:
            return _refus("REJ-QBO-LIGNE-INCOMPRISE", "ligne après la ligne TOTAL", ligne=numero_ligne)
        refus = _devise_cad(ligne, colonnes, numero_ligne)
        if refus is not None:
            return None, refus
        libelle = _une_ligne(_cellule(ligne, colonnes, "compte"))
        couple, refus = _debit_credit(ligne, colonnes, numero_ligne, montants)
        if refus is not None:
            return None, refus
        debit, credit = couple
        if _est_total(libelle):
            if debit is None or credit is None:
                return _refus("REJ-QBO-TOTAL-INCOHERENT", "ligne TOTAL sans débit ou sans crédit",
                              ligne=numero_ligne)
            total = (debit, credit, numero_ligne)
            continue
        if not libelle:
            return _refus("REJ-QBO-LIGNE-INCOMPRISE", "montants sans compte", ligne=numero_ligne)
        if len(libelle) > NOM_COMPTE_MAX:
            return _refus("REJ-QBO-CHAMP-INVALIDE", "nom de compte trop long", ligne=numero_ligne)
        if debit and credit:
            return _refus("REJ-QBO-MONTANT-INVALIDE", "débit ET crédit sur le même compte", ligne=numero_ligne)
        if libelle in soldes:
            return _refus("REJ-QBO-COMPTE-DUPLIQUE", f"compte {libelle!r} deux fois dans la balance",
                          ligne=numero_ligne)
        debit, credit = debit or _ZERO, credit or _ZERO
        debits, credits = debits + debit, credits + credit
        soldes[libelle] = debit - credit
        lignes.append({"compte": libelle, "debit": debit, "credit": credit, "ligne": numero_ligne})
    if total is None:
        return _refus("REJ-QBO-TOTAL-ABSENT", "la ligne TOTAL de la balance est exigée (contrôle de lecture)")
    if (total[0], total[1]) != (debits, credits):
        return _refus("REJ-QBO-TOTAL-INCOHERENT",
                      f"TOTAL écrit {_texte(total[0])} / {_texte(total[1])} ≠ somme des lignes {_texte(debits)} / "
                      f"{_texte(credits)}", ligne=total[2])
    if debits != credits:
        return _refus("REJ-QBO-BALANCE-DESEQUILIBREE",
                      f"débits {_texte(debits)} ≠ crédits {_texte(credits)}")
    lecture = tableau["lecture"]
    lecture["lignes_ignorees"].update(vides=lecture["lignes_ignorees"]["vides"] + vides, totaux=1)
    lecture["convention_montants"] = montants.convention
    return {"rapport": "balance_verification", "date": date_balance.isoformat(), "lecture": lecture,
            "lignes": lignes, "soldes": soldes, "total_debits": debits, "total_credits": credits}, None


# ============================================================================================== le journal
def analyser_journal(contenu: Any, format_dates: str = "auto") -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Le journal QBO : `{rapport, periode, lecture, transactions: [{cle, type, num, date, nom, memo, lignes:
    [{compte, montant signé}], ligne}], total_debits, total_credits}`. Une transaction commence à la ligne qui porte sa
    date ; ses lignes suivent ; une ligne de montants sans compte est son total (contrôlé) ; la ligne TOTAL finale est
    contrôlée contre la somme de toutes les lignes. Chaque transaction a un numéro, unique avec son type, et est
    équilibrée ; une ligne à zéro est ignorée (comptée), une transaction toute à zéro aussi."""
    if format_dates not in _FORMATS_DATES:
        return _refus("REJ-QBO-CHAMP-INVALIDE", f"format_dates parmi {list(_FORMATS_DATES)}")
    tableau, refus = _tableau(contenu, "journal")
    if refus is not None:
        return None, refus
    colonnes = tableau["colonnes"]
    convention, refus = _convention_dates(
        (_cellule(ligne, colonnes, "date") for _n, ligne in tableau["corps"]), format_dates)
    if refus is not None:
        return None, refus
    montants = _Montants()
    transactions: list[dict[str, Any]] = []
    courante: dict[str, Any] | None = None
    total_final = None
    vides = lignes_nulles = sous_totaux = 0
    debits = credits = _ZERO
    autres = [i for role, i in colonnes.items() if role not in ("debit", "credit")]
    for numero_ligne, ligne in tableau["corps"]:
        if not any(ligne):
            vides += 1
            courante = None
            continue
        if total_final is not None:
            return _refus("REJ-QBO-LIGNE-INCOMPRISE", "ligne après la ligne TOTAL", ligne=numero_ligne)
        refus = _devise_cad(ligne, colonnes, numero_ligne)
        if refus is not None:
            return None, refus
        couple, refus = _debit_credit(ligne, colonnes, numero_ligne, montants)
        if refus is not None:
            return None, refus
        debit, credit = couple
        texte_date, compte = _cellule(ligne, colonnes, "date"), _une_ligne(_cellule(ligne, colonnes, "compte"))
        montants_index = (colonnes["debit"], colonnes["credit"])
        libelles = [ligne[i] for i in range(len(ligne)) if i not in montants_index and ligne[i]]
        if not compte and any(_est_total(t) for t in libelles):
            if debit is None or credit is None:
                return _refus("REJ-QBO-TOTAL-INCOHERENT", "ligne TOTAL sans débit ou sans crédit",
                              ligne=numero_ligne)
            total_final = (debit, credit, numero_ligne)
            continue
        if not texte_date and not compte:
            if courante is not None and debit is not None and credit is not None and not [
                    ligne[i] for i in autres if ligne[i]]:
                sommes = (sum((m for m in courante["_debits"]), _ZERO), sum((m for m in courante["_credits"]), _ZERO))
                if (debit, credit) != sommes:
                    return _refus("REJ-QBO-TOTAL-INCOHERENT", f"total de la transaction {courante['num']!r} écrit "
                                  f"{_texte(debit)} / {_texte(credit)} ≠ {_texte(sommes[0])} / {_texte(sommes[1])}",
                                  ligne=numero_ligne)
                sous_totaux += 1
                courante = None
                continue
            return _refus("REJ-QBO-LIGNE-INCOMPRISE", "ligne sans date, sans compte et qui n'est pas un total",
                          ligne=numero_ligne)
        if texte_date:
            jour = _date_cellule(texte_date, convention, tableau["xlsx"])
            if jour is None:
                return _refus("REJ-QBO-DATE-INVALIDE", f"date {texte_date!r} illisible", ligne=numero_ligne)
            type_txn = _une_ligne(_cellule(ligne, colonnes, "type"))
            num = _une_ligne(_cellule(ligne, colonnes, "num"))
            if len(type_txn) > CHAMP_TRANSACTION_MAX or len(num) > CHAMP_TRANSACTION_MAX or not type_txn:
                return _refus("REJ-QBO-CHAMP-INVALIDE",
                              f"type de transaction absent, ou type ou numéro de plus de {CHAMP_TRANSACTION_MAX} "
                              "caractères", ligne=numero_ligne)
            courante = {"type": type_txn, "num": num, "date": jour.isoformat(),
                        "nom": _une_ligne(_cellule(ligne, colonnes, "nom")),
                        "memo": _une_ligne(_cellule(ligne, colonnes, "memo")),
                        "lignes": [], "ligne": numero_ligne, "_debits": [], "_credits": []}
            transactions.append(courante)
        elif courante is None:
            return _refus("REJ-QBO-LIGNE-INCOMPRISE", "ligne de compte hors de toute transaction",
                          ligne=numero_ligne)
        if compte:
            if len(compte) > NOM_COMPTE_MAX:
                return _refus("REJ-QBO-CHAMP-INVALIDE", "nom de compte trop long", ligne=numero_ligne)
            if debit and credit:
                return _refus("REJ-QBO-MONTANT-INVALIDE", "débit ET crédit sur la même ligne", ligne=numero_ligne)
            courante["_debits"].append(debit or _ZERO)
            courante["_credits"].append(credit or _ZERO)
            montant = (debit or _ZERO) - (credit or _ZERO)
            if montant == 0:
                lignes_nulles += 1
                continue
            debits += max(montant, _ZERO)
            credits += max(-montant, _ZERO)
            courante["lignes"].append({"compte": compte, "montant": montant})
        elif debit is not None or credit is not None:
            return _refus("REJ-QBO-LIGNE-INCOMPRISE", "montants sans compte sur la ligne d'une transaction",
                          ligne=numero_ligne)
    if total_final is not None:
        ecrits = (total_final[0], total_final[1])
        bruts = (sum((m for t in transactions for m in t["_debits"]), _ZERO),
                 sum((m for t in transactions for m in t["_credits"]), _ZERO))
        if ecrits != bruts:
            return _refus("REJ-QBO-TOTAL-INCOHERENT", f"TOTAL écrit {_texte(ecrits[0])} / {_texte(ecrits[1])} ≠ "
                          f"somme des lignes {_texte(bruts[0])} / {_texte(bruts[1])}", ligne=total_final[2])
    retenues, refus = _controler_transactions(transactions)
    if refus is not None:
        return None, refus
    periode = None
    for titre in tableau["titres"]:
        dates = _dates_en_lettres(titre)
        if len(dates) >= 2:
            periode = {"debut": dates[0].isoformat(), "fin": dates[-1].isoformat()}
    lecture = tableau["lecture"]
    ignorees = lecture["lignes_ignorees"]
    ignorees.update(vides=ignorees["vides"] + vides, totaux=sous_totaux + (1 if total_final else 0),
                    lignes_nulles=lignes_nulles, transactions_nulles=len(transactions) - len(retenues))
    lecture["convention_montants"] = montants.convention
    lecture["convention_dates"] = convention
    return {"rapport": "journal", "periode": periode, "lecture": lecture, "transactions": retenues,
            "total_debits": debits, "total_credits": credits}, None


def _controler_transactions(transactions: list[dict[str, Any]]) -> tuple[list[dict] | None, dict | None]:
    sans_numero, desequilibrees, longues = [], [], []
    vues: dict[str, int] = {}
    doublons = []
    retenues = []
    for transaction in transactions:
        propre = {cle: valeur for cle, valeur in transaction.items() if not cle.startswith("_")}
        if not propre["lignes"]:
            continue
        if not propre["num"]:
            sans_numero.append(f"ligne {propre['ligne']} ({propre['type']}, {propre['date']})")
            continue
        cle = f"{propre['type']}#{propre['num']}"
        if cle in vues:
            doublons.append(f"{cle} (lignes {vues[cle]} et {propre['ligne']})")
            continue
        vues[cle] = propre["ligne"]
        somme = sum((ligne["montant"] for ligne in propre["lignes"]), _ZERO)
        if somme != 0:
            desequilibrees.append(f"{cle} (écart {_texte(somme)})")
        if len(propre["lignes"]) > LIGNES_ECRITURE_MAX:
            longues.append(f"{cle} ({len(propre['lignes'])} lignes)")
        retenues.append({**propre, "cle": cle})
    if sans_numero:
        return _refus("REJ-QBO-TRANSACTION-SANS-NUMERO",
                      f"{len(sans_numero)} transaction(s) sans numéro (colonne Num / N°) : la clé d'idempotence est "
                      "le type et le numéro QBO ; utiliser le mode ouverture ou numéroter dans QuickBooks",
                      transactions=sans_numero[:_LISTE_MAX])
    if doublons:
        return _refus("REJ-QBO-TRANSACTION-DUPLIQUEE", f"{len(doublons)} type et numéro de transaction répétés",
                      transactions=doublons[:_LISTE_MAX])
    if desequilibrees:
        return _refus("REJ-QBO-TRANSACTION-DESEQUILIBREE", f"{len(desequilibrees)} transaction(s) où débits ≠ "
                      "crédits", transactions=desequilibrees[:_LISTE_MAX])
    if longues:
        return _refus("REJ-QBO-TRANSACTION-TROP-LONGUE",
                      f"{len(longues)} transaction(s) de plus de {LIGNES_ECRITURE_MAX} lignes (borne du grand livre)",
                      transactions=longues[:_LISTE_MAX])
    return retenues, None


# ============================================================================================== la correspondance
# Table de synonymes (version TABLE_SYNONYMES_VERSION) : nom QBO normalisé -> compte du plan par défaut. N'apparie que
# si le compte existe, est actif et de la même classe dans le plan EFFECTIF ; sinon le compte reste non apparié.
_SYNONYMES = {
    "chequing": "1010", "checking": "1010", "compte cheques": "1010", "compte bancaire": "1010",
    "petty cash": "1020", "petite caisse": "1020",
    "accounts receivable a r": "1100", "accounts receivable": "1100", "comptes clients": "1100",
    "inventory": "1200", "inventory asset": "1200", "stocks": "1200", "inventaire": "1200",
    "prepaid expenses": "1300", "frais payes d avance": "1300", "charges payees d avance": "1300",
    "equipment": "1500", "equipement": "1500", "vehicles": "1510", "vehicules": "1510", "materiel roulant": "1510",
    "accounts payable a p": "2100", "accounts payable": "2100", "comptes fournisseurs": "2100",
    "gst hst payable": "2300", "gst payable": "2300", "tps tvh a payer": "2300", "tps a payer": "2300",
    "qst payable": "2310", "tvq a payer": "2310",
    "share capital": "3100", "capital actions": "3100", "capital social": "3100",
    "retained earnings": "3200", "benefices non repartis": "3200",
    "dividends": "3300", "dividendes": "3300",
    "sales": "4100", "ventes": "4100", "services": "4100", "revenus de services": "4100",
    "other income": "4900", "autres revenus": "4900",
    "materials": "5100", "materiaux": "5100", "subcontractors": "5200", "sous traitance": "5200",
    "wages": "5300", "salaires": "5300", "salaires et traitements": "5300",
    "fuel": "5400", "carburant": "5400", "tools": "5500", "outils": "5500",
    "rent": "5600", "rent or lease": "5600", "loyer": "5600", "insurance": "5700", "assurances": "5700",
    "bank charges": "5800", "frais bancaires": "5800", "interest expense": "5800",
    "legal and professional fees": "5900", "honoraires professionnels": "5900",
    "advertising": "5950", "publicite": "5950",
}
_TYPE_VERS_ROLE = {"bank": "banque", "accounts_receivable": "comptes_clients",
                   "accounts_payable": "comptes_fournisseurs"}


def _cible_valide(plan: Mapping[str, Any], numero: str, classe: str) -> bool:
    fiche = plan["comptes"].get(numero)
    return fiche is not None and fiche["actif"] and fiche["type"] == classe


def proposer_correspondance(liste: Mapping[str, Any], plan: Mapping[str, Any]) -> dict[str, Any]:
    """La correspondance PROPOSÉE (brouillon), compte QBO par compte QBO, avec la méthode et l'explication :
    numéro, puis nom (nom OPSYS ou synonyme), puis type QBO à compte naturel unique. Déterministe : mêmes listes et même
    plan, même proposition. Un compte que rien n'apparie est rendu NON APPARIÉ, avec la raison."""
    par_type: dict[str, int] = {}
    for compte in liste["comptes"]:
        par_type[compte["type_cle"]] = par_type.get(compte["type_cle"], 0) + 1
    noms_opsys = {_normaliser(fiche["nom"]): numero for numero, fiche in plan["comptes"].items()}
    lignes = []
    for compte in liste["comptes"]:
        classe = compte["classe"]
        cible = methode = explication = None
        numero = compte["numero"]
        if numero and _cible_valide(plan, numero, classe):
            cible, methode = numero, "numero"
            explication = f"numéro QBO {numero} = compte OPSYS {numero} (classe {classe})"
        if cible is None:
            noms = [_normaliser(compte["nom"]), _normaliser(compte["nom"].split(":")[-1])]
            for nom in noms:
                candidat = noms_opsys.get(nom)
                if candidat and _cible_valide(plan, candidat, classe):
                    cible, methode = candidat, "nom"
                    explication = f"nom QBO « {compte['nom']} » = nom du compte OPSYS {candidat}"
                    break
                candidat = _SYNONYMES.get(nom)
                if candidat and _cible_valide(plan, candidat, classe):
                    cible, methode = candidat, "nom"
                    explication = (f"nom QBO « {compte['nom']} » reconnu par la table {TABLE_SYNONYMES_VERSION} "
                                   f"-> compte OPSYS {candidat}")
                    break
        if cible is None:
            role = _TYPE_VERS_ROLE.get(compte["type_cle"])
            candidat = plan["roles"].get(role) if role else None
            if candidat and par_type[compte["type_cle"]] == 1 and _cible_valide(plan, candidat, classe):
                cible, methode = candidat, "type"
                explication = (f"seul compte QBO de type « {compte['type_qbo']} » -> compte OPSYS {candidat} "
                               f"(rôle {role})")
        if cible is None:
            raison = "aucun numéro, nom ou type QBO ne désigne un compte OPSYS actif de la même classe"
            if _TYPE_VERS_ROLE.get(compte["type_cle"]) and par_type[compte["type_cle"]] > 1:
                raison = f"{par_type[compte['type_cle']]} comptes QBO de type « {compte['type_qbo']} » : choisir"
            explication = f"NON APPARIÉ : {raison} (choix manuel requis)"
        lignes.append({"compte_qbo": compte["nom"], "type_qbo": compte["type_qbo"], "classe": classe,
                       "compte_opsys": cible, "nom_opsys": plan["comptes"][cible]["nom"] if cible else None,
                       "methode": methode, "explication": explication})
    non_apparies = [ligne["compte_qbo"] for ligne in lignes if ligne["compte_opsys"] is None]
    return {"statut": "BROUILLON", "empreinte_liste": empreinte_liste(liste),
            "plan_comptable_version": plan["version_effective"], "table_synonymes": TABLE_SYNONYMES_VERSION,
            "correspondances": lignes, "non_apparies": non_apparies}


def valider_correspondance(
    liste: Mapping[str, Any], plan: Mapping[str, Any], manuelles: Any
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """La correspondance à VALIDER : la proposition, où chaque choix manuel (`[{compte_qbo, compte_opsys}]`) remplace
    la ligne proposée. Refus : choix manuel mal formé, répété, pour un compte QBO inconnu, vers un compte OPSYS inconnu,
    inactif ou d'une autre classe ; et tout compte encore non apparié (`REJ-QBO-COMPTES-NON-APPARIES`, la liste)."""
    if not isinstance(manuelles, list):
        return _refus("REJ-QBO-CORRESPONDANCE-INVALIDE", "correspondances_manuelles : une liste")
    proposition = proposer_correspondance(liste, plan)
    par_nom = {ligne["compte_qbo"]: dict(ligne) for ligne in proposition["correspondances"]}
    vus: set[str] = set()
    for choix in manuelles:
        if (not isinstance(choix, Mapping) or set(choix) != {"compte_qbo", "compte_opsys"}
                or not all(isinstance(v, str) for v in choix.values())):
            return _refus("REJ-QBO-CORRESPONDANCE-INVALIDE", "chaque choix : exactement compte_qbo, compte_opsys")
        nom, numero = choix["compte_qbo"], choix["compte_opsys"]
        if nom in vus:
            return _refus("REJ-QBO-CORRESPONDANCE-INVALIDE", f"compte QBO {nom!r} choisi deux fois")
        vus.add(nom)
        ligne = par_nom.get(nom)
        if ligne is None:
            return _refus("REJ-QBO-CORRESPONDANCE-INVALIDE", f"compte QBO {nom!r} absent de la liste des comptes")
        refus = plan_comptable.compte_utilisable(plan, numero)
        if refus is not None:
            return _refus("REJ-QBO-CORRESPONDANCE-INVALIDE", f"{nom!r} -> {numero!r} : {refus['detail']}")
        if plan["comptes"][numero]["type"] != ligne["classe"]:
            return _refus("REJ-QBO-CORRESPONDANCE-INVALIDE",
                          f"{nom!r} est un compte de {ligne['classe']} ; {numero} est un compte de "
                          f"{plan['comptes'][numero]['type']}")
        ligne.update(compte_opsys=numero, nom_opsys=plan["comptes"][numero]["nom"], methode="manuel",
                     explication=f"choix manuel -> compte OPSYS {numero}")
    lignes = [par_nom[nom] for nom in sorted(par_nom)]
    non_apparies = [ligne["compte_qbo"] for ligne in lignes if ligne["compte_opsys"] is None]
    if non_apparies:
        return _refus("REJ-QBO-COMPTES-NON-APPARIES",
                      f"{len(non_apparies)} compte(s) QBO sans compte OPSYS : un choix manuel par compte (jamais un "
                      "compte « divers » par défaut)", comptes=non_apparies[:20],
                      comptes_reste=max(0, len(non_apparies) - 20))
    table = {ligne["compte_qbo"]: ligne["compte_opsys"] for ligne in lignes}
    return {"empreinte_liste": proposition["empreinte_liste"], "plan_comptable_version": plan["version_effective"],
            "table_synonymes": TABLE_SYNONYMES_VERSION, "correspondances": lignes, "table": table,
            "empreinte_correspondance": encodage.empreinte("m5.qbo.correspondance.v1", table)}, None


# ============================================================================================== l'import
_MODES = ("detail", "ouverture")


def _fin_de_mois(annee: int, mois: int) -> date:
    return date(annee, mois, calendar.monthrange(annee, mois)[1])


def _debut_exercice(jour: date, mois_fin: int) -> date:
    """Le premier jour de l'exercice qui contient `jour` (exercice clos le dernier jour du mois `mois_fin`)."""
    fin = _fin_de_mois(jour.year, mois_fin)
    if jour <= fin:
        return _fin_de_mois(jour.year - 1, mois_fin) + timedelta(days=1)
    return fin + timedelta(days=1)


def _mois_fin(mois_fin_exercice: Any) -> int | None:
    if isinstance(mois_fin_exercice, bool) or not isinstance(mois_fin_exercice, int):
        return None
    return mois_fin_exercice if 1 <= mois_fin_exercice <= 12 else None


def _soldes_resolus(balance: Mapping[str, Any], liste: Mapping[str, Any]) -> tuple[dict | None, dict | None]:
    resolus, refus = _resoudre(balance["soldes"], liste)
    if refus is not None:
        return None, refus
    soldes: dict[str, Decimal] = {}
    for nom, solde in balance["soldes"].items():
        cible = resolus[nom]
        if cible in soldes:
            return _refus("REJ-QBO-COMPTE-DUPLIQUE", f"compte {cible!r} deux fois dans la balance (nom et numéro)")
        soldes[cible] = solde
    return soldes, None


def _reporter_resultats(
    soldes: dict[str, Decimal], liste: Mapping[str, Any]
) -> tuple[dict[str, Decimal] | None, dict[str, Any] | None]:
    """Les soldes d'ouverture d'un NOUVEL exercice : le résultat (produits et charges) de l'exercice clos reporté aux
    bénéfices non répartis (le compte QBO de type de détail « Retained Earnings » / « Bénéfices non répartis »)."""
    fiches = {c["nom"]: c for c in liste["comptes"]}
    bnr = [c["nom"] for c in liste["comptes"] if c["classe"] == "capitaux_propres" and (
        _normaliser(c["detail"] or "") in _DETAILS_BNR or _normaliser(c["nom"]) in _DETAILS_BNR)]
    if len(bnr) != 1:
        return _refus("REJ-QBO-BNR-INTROUVABLE", f"{len(bnr)} compte(s) de bénéfices non répartis dans la liste : "
                      "exactement un est requis pour reporter le résultat de l'exercice clos")
    reportes = dict(soldes)
    resultat = _ZERO
    for nom, solde in soldes.items():
        if fiches[nom]["classe"] in ("produits", "charges"):
            resultat += solde
            reportes[nom] = _ZERO
    reportes[bnr[0]] = reportes.get(bnr[0], _ZERO) + resultat
    return reportes, None


def _lignes_agregees(soldes: Mapping[str, Decimal], table: Mapping[str, str]) -> list[dict[str, Any]]:
    par_compte: dict[str, Decimal] = {}
    for nom, solde in soldes.items():
        par_compte[table[nom]] = par_compte.get(table[nom], _ZERO) + solde
    return [{"compte": numero, "debit": _texte(solde) if solde > 0 else None,
             "credit": _texte(-solde) if solde < 0 else None}
            for numero, solde in sorted(par_compte.items()) if solde != 0]


def _ecarts(attendus: Mapping[str, Decimal], recalcules: Mapping[str, Decimal]) -> list[dict[str, str]]:
    ecarts = []
    for nom in sorted(set(attendus) | set(recalcules)):
        attendu, recalcule = attendus.get(nom, _ZERO), recalcules.get(nom, _ZERO)
        if attendu != recalcule:
            ecarts.append({"compte_qbo": nom, "balance_qbo": _texte(attendu), "recalcule": _texte(recalcule),
                           "ecart": _texte(recalcule - attendu)})
    return ecarts


def _cote(soldes: Iterable[Decimal]) -> tuple[Decimal, Decimal]:
    valeurs = list(soldes)
    return (sum((s for s in valeurs if s > 0), _ZERO), sum((-s for s in valeurs if s < 0), _ZERO))


def verifier_reprise(
    *,
    liste: Mapping[str, Any],
    cloture: Mapping[str, Any],
    journal: Mapping[str, Any] | None,
    ouverture: Mapping[str, Any] | None,
    mois_fin_exercice: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """La vérification de la reprise, compte QBO par compte QBO (sans correspondance) : la balance RECALCULÉE (soldes
    d'ouverture, résultat reporté aux bénéfices non répartis si l'ouverture clôt un exercice, plus chaque transaction
    du journal) doit égaler AU CENT la balance de clôture exportée, compte par compte et au total. Sans journal, la
    vérification est INTERNE seulement (la ligne TOTAL de la balance, débits = crédits). Rend aussi ce que
    `preparer_import` utilise : soldes de clôture et d'ouverture résolus, transactions résolues."""
    if ouverture is not None and journal is None:
        return _refus("REJ-QBO-MODE-INVALIDE", "une balance d'ouverture ne sert qu'avec le journal de la période qui "
                      "la suit (sinon : mode ouverture sur la seule balance de clôture)")
    fin = date.fromisoformat(cloture["date"])
    mois = _mois_fin(mois_fin_exercice)
    if mois_fin_exercice is not None and mois is None:
        return _refus("REJ-QBO-EXERCICE-INCONNU", "configuration.fiscal.mois_fin_exercice : entier de 1 à 12")
    soldes_cloture, refus = _soldes_resolus(cloture, liste)
    if refus is not None:
        return None, refus
    classes = {c["nom"]: c["classe"] for c in liste["comptes"]}
    base: dict[str, Decimal] = {}
    date_ouverture = None
    report = False
    if ouverture is not None:
        date_ouverture = date.fromisoformat(ouverture["date"])
        if date_ouverture >= fin:
            return _refus("REJ-QBO-DATE-HORS-PERIODE", f"balance d'ouverture au {date_ouverture} pas avant la "
                          f"balance de clôture au {fin}")
        base, refus = _soldes_resolus(ouverture, liste)
        if refus is not None:
            return None, refus
        resultat_non_nul = any(s != 0 for nom, s in base.items() if classes[nom] in ("produits", "charges"))
        if resultat_non_nul:
            if mois is None:
                return _refus("REJ-QBO-EXERCICE-INCONNU",
                              "la balance d'ouverture a des produits ou charges : déclarer "
                              "configuration.fiscal.mois_fin_exercice pour savoir si elle clôt un exercice")
            if date_ouverture == _fin_de_mois(date_ouverture.year, mois):
                base, refus = _reporter_resultats(base, liste)
                if refus is not None:
                    return None, refus
                report = True
    recalcules = dict(base)
    transactions: list[dict[str, Any]] = []
    if journal is not None:
        noms = {ligne["compte"] for t in journal["transactions"] for ligne in t["lignes"]}
        resolus, refus = _resoudre(sorted(noms), liste)
        if refus is not None:
            return None, refus
        debut_fy = _debut_exercice(fin, mois) if mois is not None else None
        hors = []
        for transaction in journal["transactions"]:
            jour = date.fromisoformat(transaction["date"])
            if jour > fin or (date_ouverture is not None and jour <= date_ouverture):
                hors.append(f"{transaction['cle']} ({transaction['date']})")
            elif debut_fy is not None and jour < debut_fy:
                return _refus("REJ-QBO-EXERCICES-MULTIPLES",
                              f"{transaction['cle']} ({transaction['date']}) précède l'exercice ouvert le {debut_fy} : "
                              "les résultats d'un exercice clos ne se recalculent pas depuis le journal ; fournir la "
                              "balance d'ouverture à la fin de l'exercice précédent et le journal de l'exercice "
                              "courant")
            lignes = [{**ligne, "compte": resolus[ligne["compte"]]} for ligne in transaction["lignes"]]
            for ligne in lignes:
                recalcules[ligne["compte"]] = recalcules.get(ligne["compte"], _ZERO) + ligne["montant"]
            transactions.append({**transaction, "lignes": lignes})
        if hors:
            bornes = f"après le {date_ouverture} et " if date_ouverture else ""
            return _refus("REJ-QBO-DATE-HORS-PERIODE", f"{len(hors)} transaction(s) hors de la période ({bornes}au "
                          f"plus tard le {fin})", transactions=hors[:_LISTE_MAX])
        ecarts = _ecarts(soldes_cloture, recalcules)
        if ecarts:
            return _refus("REJ-QBO-BALANCE-ECART",
                          f"{len(ecarts)} compte(s) où la balance recalculée ≠ la balance QBO au {fin} : rien n'est "
                          "importé", ecarts=ecarts[:20], ecarts_reste=max(0, len(ecarts) - 20))
        total_recalcule = _cote(recalcules.values())
        if total_recalcule != (cloture["total_debits"], cloture["total_credits"]):
            return _refus("REJ-QBO-BALANCE-ECART", "totaux recalculés ≠ totaux de la balance QBO")
        type_verification = "ouverture_et_journal" if ouverture is not None else "journal"
    else:
        total_recalcule = None
        type_verification = "interne"
    return {
        "verification": {
            "type": type_verification, "au": fin.isoformat(), "egale_au_cent": total_recalcule is not None,
            "comptes_compares": len(set(soldes_cloture) | set(recalcules)) if total_recalcule is not None else 0,
            "total_debits_balance_qbo": _texte(cloture["total_debits"]),
            "total_credits_balance_qbo": _texte(cloture["total_credits"]),
            "total_debits_recalcule": _texte(total_recalcule[0]) if total_recalcule else None,
            "total_credits_recalcule": _texte(total_recalcule[1]) if total_recalcule else None,
            "report_resultats_bnr": report,
            "transactions": len(transactions),
        },
        "soldes_cloture": soldes_cloture, "soldes_ouverture": base, "transactions": transactions,
        "date_ouverture": date_ouverture, "report": report,
    }, None


def preparer_import(
    *,
    liste: Mapping[str, Any],
    cloture: Mapping[str, Any],
    journal: Mapping[str, Any] | None,
    ouverture: Mapping[str, Any] | None,
    correspondance: Mapping[str, Any],
    plan: Mapping[str, Any],
    mode: Any,
    date_reprise: Any,
    mois_fin_exercice: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Vérifie (`verifier_reprise`) et prépare l'import : `({propositions, verification, attendu_opsys,
    date_ouverture}, None)` ou le refus. `correspondance` est la correspondance VALIDÉE (`table`, `empreinte_liste`).
    Les propositions sont des brouillons du grand livre (forme de `grand_livre.proposer_ecritures_lot`), aucune n'est
    écrite ici. `attendu_opsys` : le solde (débiteur positif) de chaque compte OPSYS à la date de reprise, que le grand
    livre doit montrer une fois les brouillons validés."""
    if mode not in _MODES:
        return _refus("REJ-QBO-MODE-INVALIDE", f"mode parmi {list(_MODES)}")
    if date_reprise != cloture["date"]:
        return _refus("REJ-QBO-DATE-REPRISE-DIFFERENTE",
                      f"date de reprise {date_reprise!r} ≠ date de la balance de vérification {cloture['date']}")
    if mode == "detail" and journal is None:
        return _refus("REJ-QBO-MODE-INVALIDE", "le mode detail exige le journal exporté")
    if correspondance.get("empreinte_liste") != empreinte_liste(liste):
        return _refus("REJ-QBO-CORRESPONDANCE-PERIMEE", "la liste des comptes a changé depuis la correspondance "
                      "validée (compte ajouté, retiré ou retypé) : la revalider")
    table = correspondance["table"]
    for nom, numero in table.items():
        refus = plan_comptable.compte_utilisable(plan, numero)
        if refus is not None:
            return _refus("REJ-QBO-CORRESPONDANCE-PERIMEE", f"{nom!r} -> {numero} : {refus['detail']}")
    verifie, refus = verifier_reprise(liste=liste, cloture=cloture, journal=journal, ouverture=ouverture,
                                      mois_fin_exercice=mois_fin_exercice)
    if refus is not None:
        return None, refus
    soldes_cloture = verifie["soldes_cloture"]
    propositions: list[dict[str, Any]] = []
    if mode == "ouverture":
        lignes = _lignes_agregees(soldes_cloture, table)
        refus = _refus_longueur(lignes)
        if refus is not None:
            return None, refus
        if lignes:
            propositions.append(_proposition_ouverture(date.fromisoformat(cloture["date"]), lignes,
                                                       cloture["lecture"]["sha256"][:12], False))
    else:
        if ouverture is not None:
            lignes = _lignes_agregees(verifie["soldes_ouverture"], table)
            refus = _refus_longueur(lignes)
            if refus is not None:
                return None, refus
            if lignes:
                propositions.append(_proposition_ouverture(verifie["date_ouverture"], lignes,
                                                           ouverture["lecture"]["sha256"][:12], verifie["report"]))
        sha_journal = journal["lecture"]["sha256"][:12]
        for transaction in sorted(verifie["transactions"], key=lambda t: (t["date"], t["ligne"])):
            propositions.append(_proposition_transaction(transaction, table, sha_journal))
    attendu: dict[str, Decimal] = {}
    for nom, solde in soldes_cloture.items():
        attendu[table[nom]] = attendu.get(table[nom], _ZERO) + solde
    return {
        "propositions": propositions,
        "verification": verifie["verification"],
        "date_ouverture": verifie["date_ouverture"].isoformat() if verifie["date_ouverture"] else None,
        "attendu_opsys": {numero: solde for numero, solde in sorted(attendu.items()) if solde != 0},
    }, None


def _refus_longueur(lignes: list[dict[str, Any]]) -> dict[str, Any] | None:
    if len(lignes) > LIGNES_ECRITURE_MAX:
        return construire_verdict("REJ-QBO-ECRITURE-TROP-LONGUE",
                                  f"écriture d'ouverture de {len(lignes)} comptes OPSYS : le grand livre en accepte "
                                  f"{LIGNES_ECRITURE_MAX} ; regrouper des comptes dans la correspondance")
    return None


def _proposition_ouverture(jour: date, lignes: list[dict[str, Any]], sha: str, report: bool) -> dict[str, Any]:
    libelle = f"Soldes d'ouverture QuickBooks au {jour.isoformat()} (balance de vérification)"
    if report:
        libelle += " ; résultat de l'exercice clos reporté aux bénéfices non répartis"
    return {"cle_piece": f"{_PIECE}:ouverture:{jour.isoformat()}",
            "piece": {"type": _PIECE, "reference": f"qbo:ouverture:{jour.isoformat()}@{sha}"},
            "nature": "import_quickbooks_ouverture", "date_effet": jour.isoformat(), "libelle": libelle,
            "lignes_brutes": lignes}


def _proposition_transaction(transaction: Mapping[str, Any], table: Mapping[str, str], sha: str) -> dict[str, Any]:
    morceaux = [f"QuickBooks {transaction['type']} n° {transaction['num']}"]
    morceaux += [texte for texte in (transaction["nom"], transaction["memo"]) if texte]
    lignes = [{"compte": table[ligne["compte"]],
               "debit": _texte(ligne["montant"]) if ligne["montant"] > 0 else None,
               "credit": _texte(-ligne["montant"]) if ligne["montant"] < 0 else None}
              for ligne in transaction["lignes"]]
    return {"cle_piece": f"{_PIECE}:transaction:{transaction['cle']}",
            "piece": {"type": _PIECE, "reference": f"qbo:{transaction['cle']}@{sha}"},
            "nature": "import_quickbooks_transaction", "date_effet": transaction["date"],
            "libelle": _une_ligne(" — ".join(morceaux))[:200], "lignes_brutes": lignes}


def comparer_au_grand_livre(
    propositions: list[Mapping[str, Any]], etat: Mapping[str, Any], plan: Mapping[str, Any]
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Idempotence de l'import : pour chaque proposition, l'écriture déjà au grand livre sous la même clé (même type et
    numéro de transaction QBO, ou même date d'ouverture). Même date, même libellé et mêmes lignes : DÉJÀ IMPORTÉE (la
    référence du fichier peut différer : un nouvel export identique ne crée rien) ; autre contenu : CONFLIT
    (`REJ-QBO-TRANSACTION-CONFLIT`, la liste ; rien n'est importé). Rend `{nouvelles, deja: [ecriture_id]}`."""
    nouvelles, deja, conflits = [], [], []
    for proposition in propositions:
        existante = etat["ecritures"].get(grand_livre.identifiant_ecriture(proposition["cle_piece"]))
        if existante is None:
            nouvelles.append(proposition)
            continue
        lignes, refus = grand_livre.normaliser_lignes(proposition["lignes_brutes"], plan)
        identique = (refus is None and existante["date_effet"] == proposition["date_effet"]
                     and existante["libelle"] == proposition["libelle"]
                     and existante["nature"] == proposition["nature"]
                     and [(ligne["compte"], ligne["debit"], ligne["credit"]) for ligne in existante["lignes"]]
                     == [(ligne["compte"], ligne["debit"], ligne["credit"]) for ligne in lignes])
        if identique:
            deja.append(existante["ecriture_id"])
        else:
            conflits.append(f"{proposition['cle_piece'].split(':', 2)[-1]} (écriture {existante['ecriture_id']}, "
                            f"{existante['statut']})")
    if conflits:
        return _refus("REJ-QBO-TRANSACTION-CONFLIT",
                      f"{len(conflits)} transaction(s) déjà importée(s) sous le même numéro avec un autre contenu : "
                      "contre-passer l'écriture concernée (si définitive) ou corriger l'export ; rien n'est importé",
                      transactions=conflits[:_LISTE_MAX])
    return {"nouvelles": nouvelles, "deja": deja}, None


def empreinte_lot(etat: Mapping[str, Any], ecriture_ids: Iterable[str]) -> tuple[list[str], str]:
    """Les BROUILLONS encore en attente parmi `ecriture_ids` (dans l'ordre donné) et l'empreinte du lot : identifiant
    et empreinte de contenu de chacun. Une écriture validée ou contre-passée entre-temps change l'empreinte."""
    brouillons = [ident for ident in ecriture_ids
                  if ident in etat["ecritures"] and etat["ecritures"][ident]["statut"] == "BROUILLON"]
    empreinte = encodage.empreinte("m5.qbo.lot.v1", [(ident, etat["ecritures"][ident]["empreinte_contenu"])
                                                     for ident in brouillons])
    return brouillons, empreinte
