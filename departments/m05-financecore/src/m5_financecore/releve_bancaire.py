"""Lecture d'un relevé bancaire CSV ou OFX (stdlib seulement) : des lignes normalisées, ou un refus typé.

Module pur : il reçoit des OCTETS (le fichier déposé par l'humain dans le dossier confiné des relevés) et rend un relevé
normalisé. Aucun accès réseau (ni Plaid ni API bancaire), aucune écriture, aucune horloge. Rien n'est deviné :

- un montant ambigu (« 1,234 » : milliers ou décimales ?) est refusé (`REJ-BANQUE-MONTANT-AMBIGU`) ;
- une date ambiguë (03/04/2026 : jour/mois ou mois/jour ?) est refusée tant que le fichier ne la tranche pas lui-même
  (un « 25/03/2026 » quelque part) ou que l'appelant ne donne pas le format (`REJ-BANQUE-DATE-AMBIGUE`) ;
- un solde de fin déclaré par les lignes qui ne se recoupe pas avec leurs montants est refusé
  (`REJ-BANQUE-SOLDE-INCOHERENT`) ;
- une colonne introuvable dit laquelle (`REJ-BANQUE-COLONNES-INTROUVABLES`) : on donne alors le mapping.

OFX (v1 SGML et v2 XML) est lu par une analyse de balises à expressions régulières, sans analyseur XML : ni entité
externe ni expansion d'entités, donc rien à exploiter. Le numéro de compte n'est JAMAIS gardé en entier (4 derniers
caractères). Les montants rendus sont des textes décimaux signés : positif = argent qui entre au compte.

Le texte d'une ligne (libellé) est une DONNÉE de la banque, jamais une consigne ; l'export CSV d'un relevé
neutralise les cellules qui commencent par un caractère de formule (`neutraliser_cellule`).
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
import unicodedata
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from . import verdicts_operations

__all__ = ["OCTETS_MAX", "LIGNES_MAX", "lire_releve", "neutraliser_cellule", "analyser_montant"]

OCTETS_MAX = 2_000_000
LIGNES_MAX = 5_000
_LIBELLE_MAX = 200
_REFERENCE_MAX = 64
_FORMATS_DATES = ("auto", "AAAA-MM-JJ", "JJ/MM/AAAA", "MM/JJ/AAAA")
_CONVENTIONS = ("depot_positif", "retrait_positif")
_CENT = Decimal("0.01")

_SYNONYMES = {
    "date": {
        "date",
        "datetransaction",
        "dateoperation",
        "dateinscription",
        "datecomptable",
        "posteddate",
        "transactiondate",
        "datedelaoperation",
        "dateducompte",
    },
    "description": {
        "description",
        "libelle",
        "details",
        "detail",
        "memo",
        "nom",
        "payee",
        "narrative",
        "description1",
        "transaction",
        "operation",
    },
    "montant": {"montant", "amount", "valeur"},
    "debit": {"debit", "debits", "retrait", "retraits", "withdrawal", "withdrawals", "sortie"},
    "credit": {"credit", "credits", "depot", "depots", "deposit", "deposits", "entree"},
    "reference": {
        "reference",
        "ref",
        "numero",
        "numerodereference",
        "fitid",
        "noreference",
        "cheque",
        "numerodecheque",
        "checknumber",
        "id",
    },
    "solde": {"solde", "balance", "soldecourant"},
}
_MAPPING_CLES = frozenset(_SYNONYMES)
_ENTITES = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"', "&apos;": "'"}


def _verdict(code: str, detail: str = "") -> dict[str, str]:
    return verdicts_operations.construire_verdict(code, detail=detail)


def _normaliser_entete(texte: str) -> str:
    decompose = unicodedata.normalize("NFKD", texte.lower())
    sans_accent = "".join(c for c in decompose if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", sans_accent)


def neutraliser_cellule(texte: str) -> str:
    """Une cellule destinée à un tableur : une valeur qui commencerait par `=`, `+`, `-`, `@`, une tabulation ou un
    retour chariot serait lue comme une formule ; on la précède d'une apostrophe (règle OWASP « CSV injection »)."""
    if texte and texte[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + texte
    return texte


def _une_ligne(texte: str, maximum: int) -> str:
    propre = " ".join(texte.split())
    return propre[:maximum]


def analyser_montant(brut: str) -> tuple[Decimal | None, str | None]:
    """`(montant signé, None)`, `(None, None)` pour une cellule vide, ou `(None, raison)` : `ambigu` ou `invalide`."""
    texte = brut.strip().replace(" ", " ").replace(" ", " ")
    if not texte:
        return None, None
    negatif = False
    if texte.startswith("(") and texte.endswith(")"):
        negatif, texte = True, texte[1:-1]
    texte = texte.replace("$", "").replace("CAD", "").replace("cad", "").replace(" ", "")
    if texte.endswith("-"):
        negatif, texte = True, texte[:-1]
    if texte.startswith("-"):
        negatif, texte = True, texte[1:]
    elif texte.startswith("+"):
        texte = texte[1:]
    if not texte or not re.fullmatch(r"[0-9.,]+", texte):
        return None, "invalide"
    if "," in texte and "." in texte:
        # Le dernier séparateur est le décimal, l'autre ne peut être que celui des milliers : des groupes de TROIS
        # chiffres (« 1.234,56 », « 1,234,567.89 »). « 1.23,45 » ou « 12,34,56.78 » ne sont pas des montants.
        dernier = max(texte.rfind(","), texte.rfind("."))
        milliers = "." if texte.rfind(",") > texte.rfind(".") else ","
        entiere = texte[:dernier]
        if not re.fullmatch(rf"[0-9]{{1,3}}(?:{re.escape(milliers)}[0-9]{{3}})+", entiere):
            return None, "ambigu"
        texte = entiere.replace(milliers, "") + "." + texte[dernier + 1 :]
    elif "," in texte:
        morceaux = texte.split(",")
        if len(morceaux) == 2 and 1 <= len(morceaux[1]) <= 2 and morceaux[0] != "":
            texte = morceaux[0] + "." + morceaux[1]
        else:
            return None, "ambigu"
    if texte.count(".") > 1 or not re.fullmatch(r"[0-9]+(\.[0-9]{1,2})?", texte):
        return None, "invalide"
    try:
        valeur = Decimal(texte).quantize(_CENT, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None, "invalide"
    return (-valeur if negatif else valeur), None


# ------------------------------------------------------------------------------------------------------ les dates
def _decouper_date(texte: str) -> tuple[int, int, int, str] | None:
    """`(a, b, c, forme)` : forme « iso » (AAAA, MM, JJ) ou « nombres » (a/b/AAAA, ambigu tant qu'on ne sait pas)."""
    t = texte.strip()
    m = re.fullmatch(r"([0-9]{4})[-/.]([0-9]{1,2})[-/.]([0-9]{1,2})", t)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3)), "iso"
    m = re.fullmatch(r"([0-9]{4})([0-9]{2})([0-9]{2})", t)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3)), "iso"
    m = re.fullmatch(r"([0-9]{1,2})[-/.]([0-9]{1,2})[-/.]([0-9]{4})", t)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3)), "nombres"
    return None


def _trancher_ordre(dates: list[tuple[int, int, int, str]], format_dates: str) -> tuple[str | None, str | None]:
    """L'ordre des dates « nombres » : `("JJ/MM", None)`, `("MM/JJ", None)`, `(None, None)` s'il n'y en a pas, ou
    `(None, raison)`."""
    nombres = [d for d in dates if d[3] == "nombres"]
    if format_dates == "JJ/MM/AAAA":
        return "JJ/MM", None
    if format_dates == "MM/JJ/AAAA":
        return "MM/JJ", None
    if not nombres:
        return None, None
    jour_en_premier = any(d[0] > 12 for d in nombres)
    jour_en_second = any(d[1] > 12 for d in nombres)
    if jour_en_premier and jour_en_second:
        return None, "des dates contradictoires (jour en premier ET en second)"
    if jour_en_premier:
        return "JJ/MM", None
    if jour_en_second:
        return "MM/JJ", None
    return None, "aucune date du fichier ne tranche (toutes ont un jour et un mois de 12 ou moins)"


def _date_iso(morceaux: tuple[int, int, int, str], ordre: str | None) -> str | None:
    a, b, c, forme = morceaux
    try:
        if forme == "iso":
            return date(a, b, c).isoformat()
        return (date(c, b, a) if ordre == "JJ/MM" else date(c, a, b)).isoformat()
    except ValueError:
        return None


# --------------------------------------------------------------------------------------------------------- le CSV
def _decoder(octets: bytes) -> tuple[str | None, str | None]:
    if b"\x00" in octets:
        return None, "contenu binaire (octet nul) : ce n'est pas un relevé texte"
    try:
        return octets.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        return octets.decode("cp1252", errors="strict") if _cp1252_valide(octets) else None, "cp1252"


def _cp1252_valide(octets: bytes) -> bool:
    try:
        octets.decode("cp1252")
        return True
    except UnicodeDecodeError:
        return False


def _separateur(texte: str, impose: str | None) -> str:
    if impose is not None:
        return impose
    for ligne in texte.splitlines():
        if ligne.strip():
            sans_guillemets = re.sub(r'"[^"]*"', "", ligne)
            comptes = {s: sans_guillemets.count(s) for s in (";", "\t", ",")}
            meilleur = max(comptes, key=lambda s: (comptes[s], s == ","))
            return meilleur if comptes[meilleur] else ","
    return ","


def _colonnes(entete: list[str], mapping: dict[str, str] | None) -> tuple[dict[str, int] | None, str | None]:
    normalisees = [_normaliser_entete(c) for c in entete]
    trouvees: dict[str, int] = {}
    if mapping is not None:
        for cle, nom in mapping.items():
            voulu = _normaliser_entete(nom)
            if voulu not in normalisees:
                return None, f"colonne « {nom} » du mapping absente de l'en-tête"
            trouvees[cle] = normalisees.index(voulu)
        return trouvees, None
    for cle, synonymes in _SYNONYMES.items():
        for index, nom in enumerate(normalisees):
            if nom in synonymes and index not in trouvees.values():
                trouvees[cle] = index
                break
    return trouvees, None


def _entete_plausible(colonnes: dict[str, int]) -> bool:
    return "date" in colonnes and ("montant" in colonnes or "debit" in colonnes or "credit" in colonnes)


def _lire_csv(
    texte: str, mapping: dict[str, str] | None, separateur: str | None, format_dates: str, convention: str
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    delimiteur = _separateur(texte, separateur)
    lecteur = csv.reader(io.StringIO(texte), delimiter=delimiteur)
    try:
        lignes = [r for r in lecteur if any(c.strip() for c in r)]
    except csv.Error as exc:
        return None, _verdict("REJ-BANQUE-FICHIER-INVALIDE", f"CSV illisible : {exc}")
    colonnes: dict[str, int] = {}
    debut = None
    for index, rangee in enumerate(lignes[:12]):
        candidates, refus = _colonnes(rangee, mapping)
        if refus is not None:
            return None, _verdict("REJ-BANQUE-COLONNES-INTROUVABLES", refus)
        if candidates and _entete_plausible(candidates):
            colonnes, debut = candidates, index
            break
    if debut is None:
        return None, _verdict(
            "REJ-BANQUE-COLONNES-INTROUVABLES",
            "aucune colonne de date et de montant (ou débit/crédit) reconnue dans les 12 premières lignes : donner le "
            "mapping {date, montant | debit+credit, description, reference, solde} (noms de colonnes du fichier)",
        )
    corps = lignes[debut + 1 :]
    if not corps:
        return None, _verdict("REJ-BANQUE-FICHIER-INVALIDE", "aucune ligne de transaction sous l'en-tête")
    if len(corps) > LIGNES_MAX:
        return None, _verdict("REJ-BANQUE-FICHIER-INVALIDE", f"{len(corps)} lignes : au plus {LIGNES_MAX}")

    def cellule(rangee: list[str], cle: str) -> str:
        index = colonnes.get(cle)
        return rangee[index].strip() if index is not None and index < len(rangee) else ""

    morceaux = []
    for numero, rangee in enumerate(corps, start=debut + 2):
        decoupe = _decouper_date(cellule(rangee, "date"))
        if decoupe is None:
            return None, _verdict("REJ-BANQUE-LIGNE-INVALIDE", f"ligne {numero} : date illisible")
        morceaux.append(decoupe)
    ordre, raison = _trancher_ordre(morceaux, format_dates)
    if raison is not None and any(d[3] == "nombres" for d in morceaux):
        return None, _verdict("REJ-BANQUE-DATE-AMBIGUE", f"{raison} : donner format_dates (JJ/MM/AAAA ou MM/JJ/AAAA)")
    resultat: list[dict[str, Any]] = []
    for position, (rangee, decoupe) in enumerate(zip(corps, morceaux, strict=True)):
        numero = debut + 2 + position
        jour = _date_iso(decoupe, ordre)
        if jour is None:
            return None, _verdict("REJ-BANQUE-LIGNE-INVALIDE", f"ligne {numero} : date inexistante")
        montant, refus = _montant_de_la_ligne(rangee, colonnes, cellule, convention, numero)
        if refus is not None:
            return None, refus
        solde = None
        if "solde" in colonnes and cellule(rangee, "solde"):
            solde, raison_solde = analyser_montant(cellule(rangee, "solde"))
            if raison_solde == "ambigu":
                return None, _verdict("REJ-BANQUE-MONTANT-AMBIGU", f"ligne {numero} : solde ambigu")
            if raison_solde is not None:
                return None, _verdict("REJ-BANQUE-LIGNE-INVALIDE", f"ligne {numero} : solde illisible")
        resultat.append(
            {
                "ligne": numero,
                "date": jour,
                "montant": format(montant, "f"),
                "description": _une_ligne(cellule(rangee, "description"), _LIBELLE_MAX),
                "reference": _une_ligne(cellule(rangee, "reference"), _REFERENCE_MAX),
                "solde": None if solde is None else format(solde, "f"),
            }
        )
    avertissements = [
        f"séparateur {delimiteur!r} ; convention de signe : {convention}"
        if "montant" in colonnes
        else f"séparateur {delimiteur!r} ; colonnes débit et crédit"
    ]
    return {"lignes": resultat, "avertissements": avertissements, "compte_masque": None, "solde_declare": None}, None


def _montant_de_la_ligne(
    rangee: list[str], colonnes: dict[str, int], cellule: Any, convention: str, numero: int
) -> tuple[Decimal | None, dict[str, str] | None]:
    if "montant" in colonnes:
        montant, raison = analyser_montant(cellule(rangee, "montant"))
        if raison == "ambigu":
            return None, _verdict("REJ-BANQUE-MONTANT-AMBIGU", f"ligne {numero} : montant ambigu")
        if raison is not None or montant is None:
            return None, _verdict("REJ-BANQUE-LIGNE-INVALIDE", f"ligne {numero} : montant illisible ou vide")
        return (-montant if convention == "retrait_positif" else montant), None
    debit, raison_d = analyser_montant(cellule(rangee, "debit")) if "debit" in colonnes else (None, None)
    credit, raison_c = analyser_montant(cellule(rangee, "credit")) if "credit" in colonnes else (None, None)
    for raison in (raison_d, raison_c):
        if raison == "ambigu":
            return None, _verdict("REJ-BANQUE-MONTANT-AMBIGU", f"ligne {numero} : montant ambigu")
        if raison is not None:
            return None, _verdict("REJ-BANQUE-LIGNE-INVALIDE", f"ligne {numero} : montant illisible")
    if (debit is not None and debit != 0) and (credit is not None and credit != 0):
        return None, _verdict("REJ-BANQUE-LIGNE-INVALIDE", f"ligne {numero} : débit ET crédit renseignés")
    if debit is None and credit is None:
        return None, _verdict("REJ-BANQUE-LIGNE-INVALIDE", f"ligne {numero} : ni débit ni crédit")
    if debit is not None and debit != 0:
        return -abs(debit), None
    return abs(credit or Decimal("0.00")), None


# --------------------------------------------------------------------------------------------------------- l'OFX
def _entites(valeur: str) -> str:
    for source, cible in _ENTITES.items():
        valeur = valeur.replace(source, cible)
    return valeur.strip()


def _lire_ofx(octets: bytes) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    try:
        texte = octets.decode("utf-8")
    except UnicodeDecodeError:
        texte = octets.decode("cp1252", errors="replace")
    if "<OFX>" not in texte.upper():
        return None, _verdict("REJ-BANQUE-FORMAT-INCONNU", "balise <OFX> introuvable")
    transactions: list[dict[str, str]] = []
    courante: dict[str, str] | None = None
    comptes: set[str] = set()
    devise = None
    solde: dict[str, str] = {}
    dans_solde = False
    for ouverture_fermeture, balise, valeur in re.findall(r"<(/?)([A-Za-z0-9.]+)>([^<\r\n]*)", texte):
        nom = balise.upper()
        if nom == "STMTTRN":
            if ouverture_fermeture == "/":
                if courante is not None:
                    transactions.append(courante)
                courante = None
            else:
                courante = {}
            continue
        if nom == "LEDGERBAL":
            dans_solde = ouverture_fermeture != "/"
            continue
        if ouverture_fermeture == "/" or not valeur.strip():
            continue
        v = _entites(valeur)
        if courante is not None:
            courante[nom] = v
        elif dans_solde and nom in ("BALAMT", "DTASOF"):
            solde[nom] = v
        elif nom == "ACCTID":
            comptes.add(v)
        elif nom == "CURDEF" and devise is None:
            devise = v.upper()
    if devise is not None and devise != "CAD":
        return None, _verdict("REJ-BANQUE-DEVISE-INVALIDE", f"devise {devise!r} : CAD seulement")
    if len(comptes) > 1:
        return None, _verdict("REJ-BANQUE-FICHIER-INVALIDE", "plusieurs comptes dans le même fichier OFX")
    if not transactions:
        return None, _verdict("REJ-BANQUE-FICHIER-INVALIDE", "aucune transaction <STMTTRN>")
    if len(transactions) > LIGNES_MAX:
        return None, _verdict("REJ-BANQUE-FICHIER-INVALIDE", f"{len(transactions)} transactions : au plus {LIGNES_MAX}")
    lignes: list[dict[str, Any]] = []
    vus: set[str] = set()
    for numero, t in enumerate(transactions, start=1):
        fitid = t.get("FITID", "")
        if not fitid:
            return None, _verdict("REJ-BANQUE-LIGNE-INVALIDE", f"transaction {numero} : FITID absent")
        if fitid in vus:
            return None, _verdict("REJ-BANQUE-DOUBLON-REFERENCE", f"FITID {fitid!r} présent deux fois")
        vus.add(fitid)
        brut_date = t.get("DTPOSTED", "")[:8]
        decoupe = _decouper_date(brut_date)
        jour = _date_iso(decoupe, None) if decoupe is not None else None
        if jour is None:
            return None, _verdict("REJ-BANQUE-LIGNE-INVALIDE", f"transaction {numero} : DTPOSTED illisible")
        montant, raison = analyser_montant(t.get("TRNAMT", ""))
        if raison == "ambigu":
            return None, _verdict("REJ-BANQUE-MONTANT-AMBIGU", f"transaction {numero} : TRNAMT ambigu")
        if raison is not None or montant is None:
            return None, _verdict("REJ-BANQUE-LIGNE-INVALIDE", f"transaction {numero} : TRNAMT illisible")
        libelle = " ".join(x for x in (t.get("NAME", ""), t.get("MEMO", "")) if x)
        lignes.append(
            {
                "ligne": numero,
                "date": jour,
                "montant": format(montant, "f"),
                "description": _une_ligne(libelle, _LIBELLE_MAX),
                "reference": _une_ligne(fitid, _REFERENCE_MAX),
                "solde": None,
            }
        )
    declare = None
    if "BALAMT" in solde:
        montant, raison = analyser_montant(solde["BALAMT"])
        if raison is not None or montant is None:
            return None, _verdict("REJ-BANQUE-SOLDE-INCOHERENT", "LEDGERBAL/BALAMT illisible")
        asof = _decouper_date(solde.get("DTASOF", "")[:8])
        declare = {
            "montant": format(montant, "f"),
            "date": _date_iso(asof, None) if asof is not None else None,
            "source": "ofx_ledgerbal",
        }
    masque = None
    if comptes:
        compte = next(iter(comptes))
        masque = "****" + compte[-4:]
    return {
        "lignes": lignes,
        "avertissements": ["OFX : la date est celle de DTPOSTED (fuseau ignoré)"],
        "compte_masque": masque,
        "solde_declare": declare,
    }, None


# --------------------------------------------------------------------------------------------------- l'entrée
def _controler_solde(lignes: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    """Le solde de fin d'après la colonne « solde » si TOUTES les lignes en ont un ET qu'il se recoupe avec les
    montants (ordre croissant ou décroissant dans le fichier) ; `(None, raison)` si le recoupement échoue."""
    if len(lignes) < 1 or any(ligne["solde"] is None for ligne in lignes):
        return None, None
    montants = [Decimal(ligne["montant"]) for ligne in lignes]
    soldes = [Decimal(ligne["solde"]) for ligne in lignes]
    croissant = all(soldes[i] == soldes[i - 1] + montants[i] for i in range(1, len(lignes)))
    decroissant = all(soldes[i - 1] == soldes[i] + montants[i - 1] for i in range(1, len(lignes)))
    if len(lignes) == 1:
        return format(soldes[0], "f"), None
    if croissant:
        return format(soldes[-1], "f"), None
    if decroissant:
        return format(soldes[0], "f"), None
    return None, "la colonne solde ne se recoupe pas avec les montants (ni en ordre croissant ni décroissant)"


def lire_releve(
    octets: bytes,
    *,
    nom: str,
    mapping: dict[str, str] | None = None,
    separateur: str | None = None,
    format_dates: str = "auto",
    convention_signe: str = "depot_positif",
    solde_fin_declare: str | None = None,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Le relevé normalisé `{format, sha256, nom, devise, compte_masque, lignes, date_debut, date_fin, solde_fin,
    solde_fin_source, solde_fin_date, avertissements}`, ou le refus nommé. `solde_fin_declare` (texte décimal) est le
    solde de fin lu SUR LE RELEVÉ PAPIER par l'humain ; il prime sur celui du fichier mais doit le recouper s'il
    existe."""
    if not isinstance(octets, (bytes, bytearray)) or not octets:
        return None, _verdict("REJ-BANQUE-FICHIER-INVALIDE", "fichier vide")
    if len(octets) > OCTETS_MAX:
        return None, _verdict("REJ-BANQUE-FICHIER-INVALIDE", f"fichier de plus de {OCTETS_MAX} octets")
    if format_dates not in _FORMATS_DATES:
        return None, _verdict("REJ-BANQUE-DATE-AMBIGUE", f"format_dates parmi {', '.join(_FORMATS_DATES)}")
    if convention_signe not in _CONVENTIONS:
        return None, _verdict("REJ-BANQUE-LIGNE-INVALIDE", f"convention_signe parmi {', '.join(_CONVENTIONS)}")
    if mapping is not None and (
        not isinstance(mapping, dict)
        or not set(mapping) <= _MAPPING_CLES
        or not all(isinstance(v, str) and v.strip() for v in mapping.values())
    ):
        return None, _verdict("REJ-BANQUE-COLONNES-INTROUVABLES", f"mapping : clés parmi {sorted(_MAPPING_CLES)}")
    if separateur is not None and separateur not in (",", ";", "\t"):
        return None, _verdict("REJ-BANQUE-FICHIER-INVALIDE", "séparateur parmi , ; et tabulation")
    sha = hashlib.sha256(bytes(octets)).hexdigest()
    debut = bytes(octets[:2000]).decode("latin-1", errors="replace").upper()
    if "OFXHEADER" in debut or "<OFX>" in debut:
        format_trouve = "ofx"
        lu, refus = _lire_ofx(bytes(octets))
    else:
        format_trouve = "csv"
        texte, encodage_trouve = _decoder(bytes(octets))
        if texte is None:
            return None, _verdict("REJ-BANQUE-FICHIER-INVALIDE", "encodage illisible (ni UTF-8 ni cp1252)")
        lu, refus = _lire_csv(texte, mapping, separateur, format_dates, convention_signe)
        if lu is not None:
            lu["avertissements"].append(f"encodage {encodage_trouve}")
    if refus is not None:
        return None, refus
    lignes = lu["lignes"]
    solde_fin, solde_source, solde_date = None, None, None
    solde_colonne, incoherence = _controler_solde(lignes)
    if incoherence is not None:
        return None, _verdict("REJ-BANQUE-SOLDE-INCOHERENT", incoherence)
    if solde_colonne is not None:
        solde_fin, solde_source = solde_colonne, "colonne_solde"
    elif lu["solde_declare"] is not None:
        solde_fin, solde_source = lu["solde_declare"]["montant"], lu["solde_declare"]["source"]
        solde_date = lu["solde_declare"]["date"]
    if solde_fin_declare is not None:
        declare, raison = analyser_montant(solde_fin_declare) if isinstance(solde_fin_declare, str) else (None, "x")
        if raison is not None or declare is None:
            return None, _verdict("REJ-BANQUE-SOLDE-INCOHERENT", "solde_fin_declare : texte décimal attendu")
        if solde_fin is not None and Decimal(solde_fin) != declare:
            return None, _verdict(
                "REJ-BANQUE-SOLDE-INCOHERENT",
                f"solde de fin déclaré {format(declare, 'f')} ≠ celui du fichier {solde_fin}",
            )
        solde_fin, solde_source = format(declare, "f"), "declare_par_un_humain"
    dates = sorted(ligne["date"] for ligne in lignes)
    return {
        "format": format_trouve,
        "sha256": sha,
        "nom": nom,
        "devise": "CAD",
        "compte_masque": lu["compte_masque"],
        "lignes": lignes,
        "date_debut": dates[0],
        "date_fin": dates[-1],
        "solde_fin": solde_fin,
        "solde_fin_source": solde_source,
        "solde_fin_date": solde_date,
        "avertissements": lu["avertissements"],
    }, None
