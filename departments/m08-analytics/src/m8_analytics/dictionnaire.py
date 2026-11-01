import pathlib
import re

import yaml

from . import contrats

# Garde de devise (docs/research/R9-m7-m8.md §1.3, trou comblé par
# docs/departements/M8-audit.md §2/§5 — T3.4) : une unité MONÉTAIRE doit être
# en CAD — projet 100 % QC/CAD (TPS/TVQ, Loi 25). Une unité est monétaire si
# elle porte, comme mot entier et n'importe où (nu : "CAD", "usd" ; avec un
# dénominateur : "CAD/lead", "USD / lead" ; entre parenthèses : "lead (EUR)"),
# un code devise ISO 4217 (comparaison insensible à la casse contre
# _CODES_ISO_4217 ci-dessous), ou un symbole ou un mot de devise courant
# ("€", "US$", "dollars US", "euros"). Le trou corrigé en T3.4 : une unité
# monétaire NUE ("CAD", "EUR") traversait la garde ; la revue adverse (num) en
# a fermé un second : seuls "CODE" et "CODE/mot" étaient reconnus, jamais
# "USD / lead" ni "€ par lead" (l'unité d'une définition enregistrée à
# l'exécution est un texte libre). Une unité qui ne porte AUCUN code ISO 4217
# (ex. "ratio", "pourcentage", "dict {note: entier}", "min", "km", "h",
# "jours", "nb") n'est pas monétaire et n'est pas contrainte par cette garde.
# Préfixées `_` : allow-lists techniques, pas des énumérés de domaine à
# classer (pas d'échappatoire D-032 — voir conformite.py::_est_enumere_domaine,
# qui de toute façon n'inspecte que les Tuple/List/Set nus, jamais un
# frozenset(...)).
_DEVISES_AUTORISEES = frozenset({"CAD"})
# Un mot entier = trois lettres encadrées de non-lettres.
_MOTIF_JETON_DEVISE = re.compile(r"(?<![A-Za-z])[A-Za-z]{3}(?![A-Za-z])")
_MOTIF_SYMBOLE_DEVISE = re.compile(
    r"[€£¥₹₩₽₺₫₪]|\bUS\s?\$|\$\s?US\b|\bdollars?\s+(?:us|am[ée]ricains?)\b|\beuros?\b", re.IGNORECASE
)

# Codes ISO 4217 (Table A.1 — Current currency & funds code list, tenue par le
# SIX Group pour l'ISO), 178 codes actifs extraits de
# https://en.wikipedia.org/wiki/ISO_4217 le 2026-09-28. Inclut les codes
# spéciaux de la même table (XAU/XAG/XPD/XPT métaux précieux, XDR droits de
# tirage spéciaux, XTS code de test, XXX « aucune devise ») : ce sont des
# codes ISO 4217 valides au même titre que les devises nationales, donc une
# unité qui en porte un nu (ex. "XXX") est traitée identiquement — une seule
# règle, aucun cas particulier cousu à la main. Liste figée en constante
# plutôt qu'une dépendance (ex. `pycountry`) : quelques dizaines de lignes
# stdlib suffisent (AGENTS.md « les briques sont des ingrédients à adapter,
# pas à empiler » ; M8-audit.md §3.3 : « corrigible en quelques lignes dans
# dictionnaire.py sans aucune brique »).
_CODES_ISO_4217 = frozenset({
    "AED", "AFN", "ALL", "AMD", "AOA", "ARS", "AUD", "AWG", "AZN",
    "BAM", "BBD", "BDT", "BHD", "BIF", "BMD", "BND", "BOB", "BOV",
    "BRL", "BSD", "BTN", "BWP", "BYN", "BZD", "CAD", "CDF", "CHE",
    "CHF", "CHW", "CLF", "CLP", "CNY", "COP", "COU", "CRC", "CUP",
    "CVE", "CZK", "DJF", "DKK", "DOP", "DZD", "EGP", "ERN", "ETB",
    "EUR", "FJD", "FKP", "GBP", "GEL", "GHS", "GIP", "GMD", "GNF",
    "GTQ", "GYD", "HKD", "HNL", "HTG", "HUF", "IDR", "ILS", "INR",
    "IQD", "IRR", "ISK", "JMD", "JOD", "JPY", "KES", "KGS", "KHR",
    "KMF", "KPW", "KRW", "KWD", "KYD", "KZT", "LAK", "LBP", "LKR",
    "LRD", "LSL", "LYD", "MAD", "MDL", "MGA", "MKD", "MMK", "MNT",
    "MOP", "MRU", "MUR", "MVR", "MWK", "MXN", "MXV", "MYR", "MZN",
    "NAD", "NGN", "NIO", "NOK", "NPR", "NZD", "OMR", "PAB", "PEN",
    "PGK", "PHP", "PKR", "PLN", "PYG", "QAR", "RON", "RSD", "RUB",
    "RWF", "SAR", "SBD", "SCR", "SDG", "SEK", "SGD", "SHP", "SLE",
    "SOS", "SRD", "SSP", "STN", "SVC", "SYP", "SZL", "THB", "TJS",
    "TMT", "TND", "TOP", "TRY", "TTD", "TWD", "TZS", "UAH", "UGX",
    "USD", "USN", "UYI", "UYU", "UYW", "UZS", "VED", "VES", "VND",
    "VUV", "WST", "XAD", "XAF", "XAG", "XAU", "XBA", "XBB", "XBC",
    "XBD", "XCD", "XCG", "XDR", "XOF", "XPD", "XPF", "XPT", "XSU",
    "XTS", "XUA", "XXX", "YER", "ZAR", "ZMW", "ZWG",
})


def devise_non_autorisee(unite):
    """Code devise ISO 4217 non autorisé trouvé dans une unité monétaire, sinon None.

    Détecte une unité monétaire NUE (ex. "CAD", "usd") aussi bien que préfixée d'un
    dénominateur (ex. "CAD/lead") : dans les deux formes, le code candidat (l'unité entière, ou
    ce qui précède le "/") est comparé insensiblement à la casse contre _CODES_ISO_4217. Une
    unité qui ne correspond à aucun code ISO 4217 n'est simplement pas une devise — retour
    None, jamais un refus par défaut (la garde fail-closed s'applique au VERDICT de rejet côté
    appelant, pas à cette détection : une unité hors du référentiel ISO n'est pas une devise).
    Fonction publique : partagée par compiler_dictionnaire ci-dessous et par
    registre_metriques.py (« unité validée par le dictionnaire »), seule source de vérité de
    cette règle dans M8.
    """
    for jeton in _MOTIF_JETON_DEVISE.findall(unite):
        devise = jeton.upper()
        if devise in _CODES_ISO_4217 and devise not in _DEVISES_AUTORISEES:
            return devise
    symbole = _MOTIF_SYMBOLE_DEVISE.search(unite)
    if symbole is not None:
        return symbole.group(0)
    return None


def _compiler_fichier(chemin, dictionnaire, erreurs):
    """Compile UN fichier `metrics/*.yaml` dans `dictionnaire` ; ses refus vont dans `erreurs`."""
    try:
        contenu = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        erreurs.append(f"Erreur de parsing YAML : {chemin}")
        return

    if not isinstance(contenu, dict):
        erreurs.append(f"Contenu YAML invalide : {chemin}")
        return

    module = contenu.get("module")
    if (
        contenu.get("schema_version") != 1
        or not isinstance(module, str)
        or not module
        or not isinstance(contenu.get("metrics"), list)
    ):
        erreurs.append(f"Schéma invalide : {chemin}")
        return

    ids_vus = set()
    for index, metrique in enumerate(contenu["metrics"]):
        identifiant = (
            metrique.get("id")
            if isinstance(metrique, dict) and "id" in metrique
            else index
        )

        if (
            not isinstance(metrique, dict)
            or set(metrique.keys()) != contrats.CHAMPS_DEFINITION_METRIQUE
            or any(
                not isinstance(metrique[cle], str) or not metrique[cle]
                for cle in contrats.CHAMPS_DEFINITION_METRIQUE
            )
        ):
            erreurs.append(f"Métrique invalide {identifiant} : {chemin}")
            continue

        metric_id = metrique["id"]
        if metric_id in ids_vus:
            erreurs.append(f"ID de métrique dupliqué {metric_id} : {chemin}")
            continue

        devise_refusee = devise_non_autorisee(metrique["unite"])
        if devise_refusee is not None:
            erreurs.append(
                f"REJ-DEVISE-NON-AUTORISEE {devise_refusee!r} (unité {metrique['unite']!r}) "
                f"pour métrique monétaire {metric_id} : {chemin}"
            )
            continue

        ids_vus.add(metric_id)
        dictionnaire.setdefault(module, {})[metric_id] = {
            cle: metrique[cle] for cle in contrats.CHAMPS_DEFINITION_METRIQUE
        }


def compiler_fichier(chemin):
    """Compile un seul fichier `metrics/*.yaml` (T1.5-d : M8 charge SON dictionnaire sans relire
    celui des autres départements). Même contrôles, même garde de devise que
    `compiler_dictionnaire`, dont c'est le corps : `(dictionnaire, erreurs)`."""
    dictionnaire = {}
    erreurs = []
    _compiler_fichier(pathlib.Path(chemin), dictionnaire, erreurs)
    return dictionnaire, erreurs


def compiler_dictionnaire(racine_modules):
    dictionnaire = {}
    erreurs = []

    for chemin in sorted(pathlib.Path(racine_modules).glob("*/metrics/*.yaml")):
        _compiler_fichier(chemin, dictionnaire, erreurs)

    return dictionnaire, erreurs
