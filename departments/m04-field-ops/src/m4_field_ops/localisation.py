"""Localisation des chantiers (PLAN T4.1-a, docs/research/R15-cedule-vrp.md §3 et §4).

Module pur : aucune horloge, aucun aléa, aucun réseau, aucun import ``opsys`` (même garde AST que le
reste de M4, plus une garde propre aux sockets, voir ``tests/test_localisation.py``). Il fait deux
choses que le solveur de tournées (T4.1-c) attend d'un chantier : une COORDONNÉE, et la preuve qu'un
humain l'a confirmée.

1. Proposer. L'adresse est normalisée (accents, ligature œ, ``St-`` pour ``Saint-``, abréviations de
   génériques d'odonymes, point cardinal), puis cherchée par CORRESPONDANCE EXACTE dans un index local
   du Référentiel québécois des adresses (RQA, CC-BY 4.0), un fichier SQLite de l'instance importé
   depuis le CSV mensuel (``importer_rqa``, filtre par MRC optionnel). Une seule correspondance de
   bonne qualité donne une PROPOSITION (microdegrés entiers, qualité, identifiant et version RQA).
   Aucune, plusieurs, une qualité faible (``Géocodée``, ``Incertaine``, ``Site``) ou une adresse non
   certifiée donnent le verdict « coordonnées manquantes : à confirmer » : jamais une position
   inventée, ni le centre de la ville, ni celui d'un code postal. Rien ne quitte le serveur.

2. Confirmer. Une personne confirme (``confirmer``) ; le maillon ``localisation_chantier`` entre au
   registre M4, versionné : le DERNIER maillon gagne (patron ``consentement.py``), l'historique reste
   lisible. Deux choix de conception, et pourquoi :

   - Les coordonnées sont CHIFFRÉES avant d'entrer dans le registre, avec une clé PAR CHANTIER que
     l'appelant fournit (``opsys.cles_chiffrement``, hors registre). Le registre est append-only :
     l'adresse d'un client y serait irrattrapable. Détruire la clé rend la position illisible sans
     toucher un octet de la chaîne (effacement cryptographique, même raisonnement que
     ``retention.py``). Le flux de clé porte un contexte propre : une clé de chantier ne déchiffre
     jamais un fix GPS, et inversement.
   - L'adresse n'entre JAMAIS dans le registre, ni en clair ni en condensat public : seulement
     ``empreinte_adresse``, un HMAC-SHA256 dont la clé est DÉRIVÉE de la clé du chantier. Un sel
     commun à toute l'instance laisserait n'importe qui essayer, contre un condensat, les adresses
     d'un référentiel public ; avec une clé par chantier, l'empreinte se vérifie tant que la clé
     existe (l'adresse a-t-elle changé depuis la confirmation ?) et devient invérifiable, donc
     inexploitable, quand la clé est détruite.

La source d'une coordonnée est ``rqa`` (lue dans l'index par identifiant, JAMAIS d'un argument : un
modèle ne peut pas écrire une coordonnée en la disant issue du RQA) ou ``manuel`` (saisie par
l'humain, marquée comme telle). Aucun prix, aucune distance, aucune date : ce module ne calcule pas.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import json
import os
import re
import sqlite3
import sys
import unicodedata
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from pathlib import Path

from . import encodage
from . import horodatage as horodatage_mod
from . import verdicts as verdicts_mod

TYPE_LOCALISATION = "localisation_chantier"
ACTIONS_LOCALISATION = ("confirmee", "retiree")
SOURCES_LOCALISATION = ("rqa", "manuel")

# Portée des clés de chiffrement dans le coffre du socle (une clé par chantier, jamais par version).
PORTEE_CLES_LOCALISATION = "m04-field-ops/localisation"

# Emplacement de l'index dans le dossier d'état de l'instance : ``<OPSYS_HOME>/rqa/index.sqlite``.
# Le module ne lit pas OPSYS_HOME (c'est l'affaire de l'adaptateur, ``outils.py``).
SOUS_DOSSIER_INDEX = "rqa"
NOM_FICHIER_INDEX = "index.sqlite"
SCHEMA_INDEX = "m04-field-ops/rqa-index/v1"

MAX_CANDIDATS = 10

ATTRIBUTION_RQA = (
    "Contient des données du Référentiel québécois des adresses (RQA), © Gouvernement du Québec, "
    "ministère des Ressources naturelles et des Forêts, licence CC-BY 4.0 "
    "(https://creativecommons.org/licenses/by/4.0/deed.fr). "
    "Données filtrées par MRC et arrondies au microdegré."
)

# Bornes de vraisemblance (microdegrés) : elles ne servent qu'à refuser une inversion latitude et
# longitude ou une saisie hors du Québec, jamais à déduire une position. Sud du Québec vers 45° N,
# nord vers 62,6° N ; ouest vers 79,8° O, est vers 57,1° O.
LATITUDE_MIN_MICRO = 44_500_000
LATITUDE_MAX_MICRO = 63_000_000
LONGITUDE_MIN_MICRO = -80_000_000
LONGITUDE_MAX_MICRO = -57_000_000

PRECISION_MANUELLE = "manuel"
PRECISION_INCONNUE = "inconnue"
# Libellé RQA (normalisé) -> précision stable. Guide d'utilisation du RQA v1.2 (2026-09-01),
# attribut ``qualite_positionnement_geometrique``.
_PRECISION_PAR_QUALITE = {
    "batiment": "batiment",
    "acces propriete": "acces_propriete",
    "front lot": "front_lot",
    "centre lot": "centre_lot",
    "site": "site",
    "geocodee": "geocodee",
    "incertaine": "incertaine",
}
# R15 §3.3 : ces quatre précisions donnent une PROPOSITION ; toutes les autres (et toute valeur
# inconnue) donnent « à confirmer sur place ».
PRECISIONS_PROPOSABLES = frozenset({"batiment", "acces_propriete", "front_lot", "centre_lot"})

RAISON_AUCUNE = "aucune_correspondance"
RAISON_PLUSIEURS = "plusieurs_correspondances"
RAISON_QUALITE = "qualite_insuffisante"
RAISON_NON_CERTIFIEE = "adresse_non_certifiee"

CHAMPS_ADRESSE = (
    "numero_municipal", "suffixe", "unite", "odonyme", "municipalite", "code_municipalite", "code_postal",
)

# Colonnes du CSV du RQA que l'import exige (guide d'utilisation v1.2). Le nom de l'odonyme se lit dans
# ``odonyme_recompose_normal``, ou à défaut dans ses composantes.
COLONNES_RQA_REQUISES = (
    "identifiant_unique_adresse", "numero_municipal", "adresse_formatee",
    "qualite_positionnement_geometrique", "etat", "code_mrc", "nom_mrc", "code_municipalite",
    "nom_municipalite", "longitude", "latitude",
)

_CONTEXTE_FLUX = b"m4-field-ops/localisation/chiffrement/v1:"
_CONTEXTE_EMPREINTE = b"m4-field-ops/localisation/empreinte/v1"

__all__ = [
    "TYPE_LOCALISATION", "ACTIONS_LOCALISATION", "SOURCES_LOCALISATION", "PORTEE_CLES_LOCALISATION",
    "SOUS_DOSSIER_INDEX", "NOM_FICHIER_INDEX", "ATTRIBUTION_RQA", "MAX_CANDIDATS", "CHAMPS_ADRESSE",
    "COLONNES_RQA_REQUISES", "PRECISIONS_PROPOSABLES", "PRECISION_MANUELLE",
    "normaliser_texte", "normaliser_municipalite", "normaliser_odonyme", "analyser_adresse",
    "microdegres", "precision_rqa", "importer_rqa", "IndexRqa", "IndexRqaAbsent", "ouvrir_index",
    "proposer", "nonce_localisation", "chiffrer_coordonnees", "dechiffrer_coordonnees",
    "empreinte_adresse", "confirmer", "confirmation_courante", "position_confirmee", "historique",
    "principal",
]


def _verdict(code, detail):
    return verdicts_mod.construire_verdict(code, detail=detail)


# --------------------------------------------------------------------------------- normalisation
_LIGATURES = str.maketrans({"œ": "oe", "Œ": "oe", "æ": "ae", "Æ": "ae"})
_SAINTS = {"st": "saint", "ste": "sainte", "sts": "saints", "stes": "saintes"}
# Abréviation usuelle -> générique complet (premier mot de l'odonyme seulement).
_GENERIQUES = {
    "boul": "boulevard", "bd": "boulevard", "blvd": "boulevard", "av": "avenue", "ave": "avenue",
    "ch": "chemin", "rte": "route", "mtee": "montee", "mte": "montee", "pl": "place",
    "cir": "cercle", "terr": "terrasse", "imp": "impasse", "aut": "autoroute", "prom": "promenade",
    "rg": "rang", "cres": "croissant",
}
# Point cardinal en dernier mot (une ou deux lettres) -> mots complets, comme dans le RQA.
_CARDINAUX = {
    "n": ("nord",), "s": ("sud",), "e": ("est",), "o": ("ouest",),
    "ne": ("nord", "est"), "no": ("nord", "ouest"), "se": ("sud", "est"), "so": ("sud", "ouest"),
}
_CARDINAUX_EN_DEUX_LETTRES = {
    ("n", "e"): ("nord", "est"), ("n", "o"): ("nord", "ouest"),
    ("s", "e"): ("sud", "est"), ("s", "o"): ("sud", "ouest"),
}
_DESIGNATION_MUNICIPALE = re.compile(
    r"^(?:ville|municipalite|paroisse|village|canton|cite)\s+(?:de\s+la|de\s+l|de|du|des|d)\s+"
)
_DISCRIMINANT = re.compile(r"\([^)]*\)")
_SUFFIXE_VALIDE = re.compile(r"^(?:[A-Z0-9]{1,20}|\d/\d)$")
_UNITE_VALIDE = re.compile(r"^[A-Z0-9/-]{1,20}$")
_CODE_POSTAL_FIN = re.compile(r"\b([A-Za-z]\d[A-Za-z])[\s-]?(\d[A-Za-z]\d)\s*$")
_CODE_POSTAL_VALIDE = re.compile(r"^[A-Z]\d[A-Z]\d[A-Z]\d$")
_DEBUT_ADRESSE = re.compile(
    r"^(?:(?P<unite>[A-Za-z0-9]{1,6})\s*-\s*)?(?P<numero>\d{1,6})"
    r"(?:\s*(?P<suffixe>[A-Za-z]|\d/\d)(?=\s))?\s+(?P<odonyme>\S.*)$"
)
_FINS_SANS_MUNICIPALITE = frozenset({"qc", "canada", "qc canada"})


def normaliser_texte(texte):
    """Minuscules sans accents ni ponctuation, mots séparés par une espace. ``œ`` devient ``oe``
    (le RQA écrit « Beloeil », jamais « Belœil »). Idempotente."""
    decompose = unicodedata.normalize("NFKD", texte.translate(_LIGATURES))
    sans_accents = "".join(c for c in decompose if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", sans_accents.lower()).split())


def normaliser_municipalite(texte):
    """Nom de municipalité normalisé : ``St-Jean`` et ``Saint-Jean`` se rejoignent, la désignation
    (« Ville de », « Paroisse de »...) tombe. Idempotente."""
    jetons = [_SAINTS.get(j, j) for j in normaliser_texte(texte).split()]
    return _DESIGNATION_MUNICIPALE.sub("", " ".join(jetons))


def normaliser_odonyme(texte):
    """Nom de voie normalisé : générique abrégé complété en tête (``boul.`` -> ``boulevard``), ``St``
    complété, point cardinal complété en fin (``N.-E.`` -> ``nord est``). Idempotente."""
    jetons = [_SAINTS.get(j, j) for j in normaliser_texte(texte).split()]
    if jetons:
        jetons[0] = _GENERIQUES.get(jetons[0], jetons[0])
    if len(jetons) >= 3 and tuple(jetons[-2:]) in _CARDINAUX_EN_DEUX_LETTRES:
        jetons = jetons[:-2] + list(_CARDINAUX_EN_DEUX_LETTRES[tuple(jetons[-2:])])
    elif len(jetons) >= 2 and jetons[-1] in _CARDINAUX:
        jetons = jetons[:-1] + list(_CARDINAUX[jetons[-1]])
    return " ".join(jetons)


def _numero(valeur):
    """Numéro municipal entier (``int`` ou chaîne de chiffres), sinon ``None``."""
    if isinstance(valeur, bool):
        return None
    if isinstance(valeur, int):
        return valeur if valeur > 0 else None
    if isinstance(valeur, str) and re.fullmatch(r"\d{1,9}", valeur.strip()):
        nombre = int(valeur.strip())
        return nombre if nombre > 0 else None
    return None


def _suffixe(valeur):
    """Suffixe normalisé (``a`` -> ``A``, ``1 / 3`` -> ``1/3``), ``""`` s'il n'y en a pas, ``None`` s'il
    est mal formé."""
    if not isinstance(valeur, str):
        return None
    compact = re.sub(r"\s+", "", valeur).upper()
    if compact == "":
        return ""
    return compact if _SUFFIXE_VALIDE.match(compact) else None


def _unite(valeur):
    if not isinstance(valeur, str):
        return None
    compact = re.sub(r"\s+", "", valeur).upper()
    if compact == "":
        return ""
    return compact if _UNITE_VALIDE.match(compact) else None


def _analyser_texte_libre(texte):
    """Adresse écrite en une ligne -> champs structurés, ou ``None`` si elle n'a pas la forme stricte
    ``[unité-]numéro [suffixe] odonyme, municipalité [code postal]``. Aucune devinette : une ligne qui
    n'entre pas dans cette forme est refusée, l'appelant fournit alors les champs séparés. « 2-56 » se
    lit unité 2 de l'immeuble 56, comme dans le RQA ; une plage « 56-58 » se lit de la même façon (unité
    56, immeuble 58), donc ne trouve en général rien : à l'appelant de fournir un seul numéro."""
    brut = texte.strip()
    code_postal = ""
    trouve = _CODE_POSTAL_FIN.search(brut)
    if trouve:
        code_postal = (trouve.group(1) + trouve.group(2)).upper()
        brut = brut[:trouve.start()].rstrip(" ,")
    parties = [p.strip() for p in brut.split(",") if p.strip()]
    while len(parties) > 2 and normaliser_texte(parties[-1]) in _FINS_SANS_MUNICIPALITE:
        parties.pop()
    if len(parties) < 2:
        return None
    debut = _DEBUT_ADRESSE.match(" ".join(parties[:-1]))
    if debut is None:
        return None
    champs = {
        "numero_municipal": debut.group("numero"), "odonyme": debut.group("odonyme"),
        "municipalite": parties[-1],
    }
    if debut.group("suffixe"):
        champs["suffixe"] = debut.group("suffixe")
    if debut.group("unite"):
        champs["unite"] = debut.group("unite")
    if code_postal:
        champs["code_postal"] = code_postal
    return champs


def analyser_adresse(adresse):
    """``(adresse_normalisee, None)`` ou ``(None, verdict)``. ``adresse`` : un objet aux champs de
    ``CHAMPS_ADRESSE`` (``numero_municipal``, ``odonyme`` et ``municipalite`` obligatoires), ou une
    ligne de texte de forme stricte. Rien n'est complété ni deviné.

    L'adresse normalisée porte ``numero`` (entier), ``suffixe``, ``unite``, ``cle_odonyme``,
    ``cle_municipalite``, ``code_municipalite`` et ``code_postal`` (chaînes, vides si absents)."""
    if isinstance(adresse, str):
        champs = _analyser_texte_libre(adresse)
        if champs is None:
            return None, _verdict(
                "REJ-CONTRAT-INVALIDE",
                "adresse illisible : forme attendue « [unité-]numéro [suffixe] odonyme, municipalité "
                "[code postal] », ou fournir les champs séparés (numero_municipal, odonyme, municipalite)",
            )
        adresse = champs
    if not isinstance(adresse, dict):
        return None, _verdict("REJ-CONTRAT-INVALIDE", "adresse : objet ou texte attendu")
    inconnus = sorted(set(adresse) - set(CHAMPS_ADRESSE))
    if inconnus:
        return None, _verdict("REJ-CONTRAT-INVALIDE", f"adresse : champs inconnus {inconnus}")
    for requis in ("numero_municipal", "odonyme", "municipalite"):
        if requis not in adresse:
            return None, _verdict("REJ-CHAMP-MANQUANT", f"adresse.{requis} manquant")
    numero = _numero(adresse["numero_municipal"])
    if numero is None:
        return None, _verdict(
            "REJ-CONTRAT-INVALIDE",
            "adresse.numero_municipal : entier positif attendu (le suffixe va dans adresse.suffixe)",
        )
    for nom in ("odonyme", "municipalite"):
        valeur = adresse[nom]
        if not isinstance(valeur, str):
            return None, _verdict("REJ-CONTRAT-INVALIDE", f"adresse.{nom} : texte attendu")
        if valeur.strip() == "":
            return None, _verdict("REJ-CHAMP-VIDE", f"adresse.{nom} vide")
    suffixe = _suffixe(adresse.get("suffixe", ""))
    if suffixe is None:
        return None, _verdict(
            "REJ-CONTRAT-INVALIDE", "adresse.suffixe : une lettre, un code court ou une fraction (1/3)")
    unite = _unite(adresse.get("unite", ""))
    if unite is None:
        return None, _verdict("REJ-CONTRAT-INVALIDE", "adresse.unite mal formée")
    code_municipalite = adresse.get("code_municipalite", "")
    if not isinstance(code_municipalite, str):
        return None, _verdict("REJ-CONTRAT-INVALIDE", "adresse.code_municipalite : texte attendu")
    code_postal = adresse.get("code_postal", "")
    if not isinstance(code_postal, str):
        return None, _verdict("REJ-CONTRAT-INVALIDE", "adresse.code_postal : texte attendu")
    code_postal = re.sub(r"[\s-]+", "", code_postal).upper()
    if code_postal and not _CODE_POSTAL_VALIDE.match(code_postal):
        return None, _verdict("REJ-CONTRAT-INVALIDE", "adresse.code_postal : forme A1A1A1 attendue")
    cle_odonyme = normaliser_odonyme(adresse["odonyme"])
    cle_municipalite = normaliser_municipalite(adresse["municipalite"])
    if cle_odonyme == "" or cle_municipalite == "":
        return None, _verdict("REJ-CHAMP-VIDE", "adresse.odonyme et adresse.municipalite doivent contenir des lettres")
    return {
        "numero": numero, "suffixe": suffixe, "unite": unite, "cle_odonyme": cle_odonyme,
        "cle_municipalite": cle_municipalite, "code_municipalite": code_municipalite.strip(),
        "code_postal": code_postal,
    }, None


# ------------------------------------------------------------------------------------ coordonnées
def microdegres(valeur):
    """Degrés décimaux -> microdegrés ENTIERS, sans passer par un flottant (``"46.555572433870"`` ->
    ``46555572``, arrondi au plus proche, égalité vers le pair). Accepte une chaîne ou un ``int`` ;
    ``ValueError`` pour tout le reste (``float`` compris : sa valeur est déjà approchée)."""
    if isinstance(valeur, bool) or not isinstance(valeur, (str, int)):
        raise ValueError(f"degrés illisibles : {valeur!r}")
    try:
        decimal = Decimal(str(valeur).strip())
    except InvalidOperation:
        raise ValueError(f"degrés illisibles : {valeur!r}") from None
    if not decimal.is_finite():
        raise ValueError(f"degrés illisibles : {valeur!r}")
    return int((decimal * 1_000_000).quantize(Decimal(1), rounding=ROUND_HALF_EVEN))


def _dans_le_quebec(latitude_micro, longitude_micro):
    return (
        LATITUDE_MIN_MICRO <= latitude_micro <= LATITUDE_MAX_MICRO
        and LONGITUDE_MIN_MICRO <= longitude_micro <= LONGITUDE_MAX_MICRO
    )


def precision_rqa(libelle):
    """Précision stable d'un libellé ``qualite_positionnement_geometrique`` ; ``inconnue`` pour toute
    valeur que le guide ne liste pas (fail-closed : elle ne donne jamais une proposition)."""
    if not isinstance(libelle, str):
        return PRECISION_INCONNUE
    return _PRECISION_PAR_QUALITE.get(normaliser_texte(libelle), PRECISION_INCONNUE)


def _est_certifiee(etat):
    return isinstance(etat, str) and normaliser_texte(etat) == "certifiee"


# ------------------------------------------------------------------------------------ index RQA
_SCHEMA_SQL = """
CREATE TABLE meta (cle TEXT PRIMARY KEY, valeur TEXT NOT NULL);
CREATE TABLE adresses (
    identifiant TEXT PRIMARY KEY,
    numero INTEGER NOT NULL,
    suffixe TEXT NOT NULL,
    unite TEXT NOT NULL,
    cle_odonyme TEXT NOT NULL,
    cle_municipalite TEXT NOT NULL,
    code_municipalite TEXT NOT NULL,
    code_mrc TEXT NOT NULL,
    nom_mrc TEXT NOT NULL,
    code_postal TEXT NOT NULL,
    discriminant TEXT NOT NULL,
    adresse_formatee TEXT NOT NULL,
    qualite TEXT NOT NULL,
    etat TEXT NOT NULL,
    latitude_micro INTEGER NOT NULL,
    longitude_micro INTEGER NOT NULL
);
CREATE INDEX adresses_cle ON adresses (cle_municipalite, cle_odonyme, numero);
"""
_COLONNES_INDEX = (
    "identifiant", "numero", "suffixe", "unite", "cle_odonyme", "cle_municipalite", "code_municipalite",
    "code_mrc", "nom_mrc", "code_postal", "discriminant", "adresse_formatee", "qualite", "etat",
    "latitude_micro", "longitude_micro",
)
_SELECT_INDEX = "SELECT " + ", ".join(_COLONNES_INDEX) + " FROM adresses"


class IndexRqaAbsent(Exception):
    """L'index RQA n'existe pas, est illisible, d'un autre schéma ou vide."""


def _texte(ligne, colonne):
    valeur = ligne.get(colonne)
    return valeur.strip() if isinstance(valeur, str) else ""


def _cle_odonyme_rqa(ligne):
    """Clé de la voie d'une ligne du RQA : ``odonyme_recompose_normal`` privé de son discriminant
    (« Chemin de la Marquise (P.-a.-T.) Sud » -> « chemin de la marquise sud »), sinon les composantes
    générique, particule, spécifique et point cardinal, dans cet ordre."""
    recompose = _texte(ligne, "odonyme_recompose_normal")
    if recompose:
        return normaliser_odonyme(_DISCRIMINANT.sub(" ", recompose))
    composantes = " ".join(
        p for p in (
            _texte(ligne, "generique_odonyme"), _texte(ligne, "particule_odonyme"),
            _texte(ligne, "specifique_odonyme"), _texte(ligne, "point_cardinal_odonyme"),
        ) if p
    )
    return normaliser_odonyme(composantes)


def _convertir_ligne_rqa(ligne):
    """``(valeurs, None)`` pour une ligne importable, ``(None, raison)`` sinon."""
    identifiant = _texte(ligne, "identifiant_unique_adresse")
    if identifiant == "":
        return None, "identifiant_absent"
    numero = _numero(_texte(ligne, "numero_municipal"))
    if numero is None:
        return None, "numero_municipal_absent"
    suffixe = _suffixe(_texte(ligne, "numero_municipal_suffixe"))
    unite = _unite(_texte(ligne, "numero_unite"))
    if suffixe is None or unite is None:
        return None, "suffixe_ou_unite_illisible"
    cle_odonyme = _cle_odonyme_rqa(ligne)
    cle_municipalite = normaliser_municipalite(_texte(ligne, "nom_municipalite"))
    if cle_odonyme == "" or cle_municipalite == "":
        return None, "odonyme_ou_municipalite_absent"
    try:
        latitude = microdegres(_texte(ligne, "latitude"))
        longitude = microdegres(_texte(ligne, "longitude"))
    except ValueError:
        return None, "coordonnees_illisibles"
    if not _dans_le_quebec(latitude, longitude):
        return None, "coordonnees_hors_quebec"
    return (
        identifiant, numero, suffixe, unite, cle_odonyme, cle_municipalite,
        _texte(ligne, "code_municipalite"), _texte(ligne, "code_mrc"), _texte(ligne, "nom_mrc"),
        re.sub(r"[\s-]+", "", _texte(ligne, "code_postal")).upper(), _texte(ligne, "discriminant_odonyme"),
        _texte(ligne, "adresse_formatee"), _texte(ligne, "qualite_positionnement_geometrique"),
        _texte(ligne, "etat"), latitude, longitude,
    ), None


def importer_rqa(chemin_csv, chemin_index, *, version=None, mrc=None):
    """Construit l'index local depuis le CSV du RQA (UTF-8, séparateur virgule, en-têtes du guide
    d'utilisation) et REMPLACE l'index existant, de façon atomique. Rend un rapport de comptes.

    ``version`` : version du référentiel ; par défaut, la valeur unique de ``date_diffusion_version``
    du fichier (sinon ``ValueError`` : elle est exigée, jamais devinée). ``mrc`` : codes ou noms de
    MRC à garder (tout le fichier sinon). Les adresses détruites (``etat`` ``Détruite`` ou ``date_fin``
    renseignée), sans numéro, sans coordonnées lisibles ou hors du Québec sont écartées et comptées.

    Refuse (``ValueError``) sans toucher l'index en place : colonne requise absente, version
    introuvable ou ambiguë, ou aucune adresse importable."""
    chemin_csv = Path(chemin_csv)
    chemin_index = Path(chemin_index)
    filtre = None
    if mrc is not None:
        filtre = {normaliser_texte(str(m)) for m in mrc} - {""}
        if not filtre:
            raise ValueError("mrc : liste vide (omettre le filtre pour importer tout le fichier)")
    chemin_index.parent.mkdir(parents=True, exist_ok=True)
    temporaire = chemin_index.with_name(chemin_index.name + ".import")
    temporaire.unlink(missing_ok=True)

    compteurs = {"lignes_lues": 0, "importees": 0, "ignorees_hors_mrc": 0, "ignorees_detruites": 0,
                 "doublons_identifiant": 0}
    raisons_invalides = {}
    versions = set()
    cnx = sqlite3.connect(temporaire)
    try:
        cnx.executescript(_SCHEMA_SQL)
        with chemin_csv.open(encoding="utf-8-sig", newline="") as fichier:
            lecteur = csv.DictReader(fichier)
            colonnes = set(lecteur.fieldnames or ())
            manquantes = [c for c in COLONNES_RQA_REQUISES if c not in colonnes]
            if not {"odonyme_recompose_normal", "specifique_odonyme"} & colonnes:
                manquantes.append("odonyme_recompose_normal (ou specifique_odonyme)")
            if manquantes:
                raise ValueError(f"CSV du RQA : colonnes absentes {manquantes}")
            insertion = "INSERT OR IGNORE INTO adresses VALUES (" + ", ".join("?" * len(_COLONNES_INDEX)) + ")"
            for ligne in lecteur:
                compteurs["lignes_lues"] += 1
                if filtre is not None and not (
                    {normaliser_texte(_texte(ligne, "code_mrc")), normaliser_texte(_texte(ligne, "nom_mrc"))} & filtre
                ):
                    compteurs["ignorees_hors_mrc"] += 1
                    continue
                if normaliser_texte(_texte(ligne, "etat")) == "detruite" or _texte(ligne, "date_fin"):
                    compteurs["ignorees_detruites"] += 1
                    continue
                valeurs, raison = _convertir_ligne_rqa(ligne)
                if valeurs is None:
                    raisons_invalides[raison] = raisons_invalides.get(raison, 0) + 1
                    continue
                if cnx.execute(insertion, valeurs).rowcount == 0:
                    compteurs["doublons_identifiant"] += 1
                    continue
                compteurs["importees"] += 1
                diffusion = _texte(ligne, "date_diffusion_version")
                if diffusion:
                    versions.add(diffusion)
        if compteurs["importees"] == 0:
            raise ValueError(
                f"aucune adresse importable ({compteurs['lignes_lues']} lignes lues) : "
                "l'index existant est conservé"
            )
        version_retenue = version
        if version_retenue is None:
            if len(versions) != 1:
                raise ValueError(
                    f"version du RQA introuvable ou ambiguë dans le fichier ({sorted(versions)}) : "
                    "la fournir (version=)"
                )
            version_retenue = next(iter(versions))
        if not isinstance(version_retenue, str) or version_retenue.strip() == "":
            raise ValueError("version : texte non vide attendu")
        cnx.executemany("INSERT INTO meta VALUES (?, ?)", [
            ("schema", SCHEMA_INDEX), ("rqa_version", version_retenue.strip()),
            ("nombre_adresses", str(compteurs["importees"])),
            ("mrc", json.dumps(sorted(filtre) if filtre is not None else [])),
        ])
        cnx.commit()
    except BaseException:
        cnx.close()
        temporaire.unlink(missing_ok=True)
        raise
    cnx.close()
    os.replace(temporaire, chemin_index)
    return {
        "version": version_retenue.strip(), **compteurs, "ignorees_invalides": sum(raisons_invalides.values()),
        "raisons_invalides": dict(sorted(raisons_invalides.items())),
        "mrc": sorted(filtre) if filtre is not None else [],
    }


class IndexRqa:
    """Index RQA ouvert en LECTURE SEULE. Aucun accès réseau : un fichier SQLite local."""

    def __init__(self, connexion, version, nombre_adresses):
        self._cnx = connexion
        self.version = version
        self.nombre_adresses = nombre_adresses

    @classmethod
    def ouvrir(cls, chemin):
        chemin = Path(chemin)
        if not chemin.is_file():
            raise IndexRqaAbsent(f"index RQA absent ({chemin}) : importer le CSV du RQA")
        connexion = None
        try:
            connexion = sqlite3.connect(f"{chemin.resolve().as_uri()}?mode=ro", uri=True)
            connexion.row_factory = sqlite3.Row
            meta = {ligne["cle"]: ligne["valeur"] for ligne in connexion.execute("SELECT cle, valeur FROM meta")}
            if meta.get("schema") != SCHEMA_INDEX:
                raise IndexRqaAbsent(f"index RQA d'un autre schéma ({meta.get('schema')!r}) : le réimporter")
            nombre = int(meta.get("nombre_adresses", "0"))
            version = meta.get("rqa_version", "")
            if nombre <= 0 or version == "":
                raise IndexRqaAbsent("index RQA vide : importer le CSV du RQA")
        except (sqlite3.Error, ValueError) as exc:
            if connexion is not None:
                connexion.close()
            raise IndexRqaAbsent(f"index RQA illisible ({exc.__class__.__name__}) : le réimporter") from exc
        except IndexRqaAbsent:
            connexion.close()
            raise
        return cls(connexion, version, nombre)

    def fermer(self):
        self._cnx.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.fermer()

    def _lignes(self, condition, parametres):
        requete = f"{_SELECT_INDEX} WHERE {condition} ORDER BY identifiant"
        return [dict(ligne) for ligne in self._cnx.execute(requete, parametres)]

    def chercher(self, adresse):
        """Toutes les adresses RQA qui ont EXACTEMENT ce numéro, ce suffixe, cette unité, cette voie et
        cette municipalité (et ce code de municipalité, s'il est fourni)."""
        condition = "cle_municipalite = ? AND cle_odonyme = ? AND numero = ? AND suffixe = ? AND unite = ?"
        parametres = [adresse["cle_municipalite"], adresse["cle_odonyme"], adresse["numero"],
                      adresse["suffixe"], adresse["unite"]]
        if adresse["code_municipalite"]:
            condition += " AND code_municipalite = ?"
            parametres.append(adresse["code_municipalite"])
        return self._lignes(condition, parametres)

    def chercher_immeuble(self, adresse):
        """Même voie, même municipalité et même numéro, quels que soient suffixe et unité : les
        candidats à montrer quand rien n'est identique (jamais à choisir)."""
        condition = "cle_municipalite = ? AND cle_odonyme = ? AND numero = ?"
        parametres = [adresse["cle_municipalite"], adresse["cle_odonyme"], adresse["numero"]]
        if adresse["code_municipalite"]:
            condition += " AND code_municipalite = ?"
            parametres.append(adresse["code_municipalite"])
        return self._lignes(condition, parametres)

    def lire(self, identifiant):
        lignes = self._lignes("identifiant = ?", [identifiant])
        return lignes[0] if lignes else None


def ouvrir_index(chemin):
    """``(index, None)`` ou ``(None, verdict)`` : l'absence d'index est un verdict qui dit quoi faire,
    jamais une réponse « aucune correspondance » (qui laisserait croire que l'adresse n'existe pas)."""
    try:
        return IndexRqa.ouvrir(chemin), None
    except IndexRqaAbsent as exc:
        return None, _verdict("REJ-INDEX-RQA-ABSENT", str(exc))


# ------------------------------------------------------------------------------------ proposition
def _coordonnees(ligne):
    return {"latitude_microdegres": ligne["latitude_micro"], "longitude_microdegres": ligne["longitude_micro"]}


def _candidat(ligne):
    return {
        "rqa_identifiant": ligne["identifiant"], "adresse_formatee": ligne["adresse_formatee"],
        "qualite_positionnement_geometrique": ligne["qualite"], "etat": ligne["etat"],
        "nom_mrc": ligne["nom_mrc"], "code_municipalite": ligne["code_municipalite"],
        "code_postal": ligne["code_postal"], "coordonnees": _coordonnees(ligne),
    }


def _a_confirmer(index, raison, lignes, detail):
    resultat = {
        "raison": raison, "candidats": [_candidat(ligne) for ligne in lignes[:MAX_CANDIDATS]],
        "nombre_candidats": len(lignes), "rqa_version": index.version, "attribution": ATTRIBUTION_RQA,
    }
    return resultat, _verdict("REJ-COORDONNEES-A-CONFIRMER", f"coordonnées manquantes : à confirmer. {detail}")


def proposer(index, adresse):
    """``(proposition, None)`` si UNE adresse RQA correspond exactement et que sa position est de bonne
    qualité ; sinon ``(None, verdict)`` (adresse illisible ou incomplète, index absent), ou
    ``(aide, verdict)`` avec le verdict « coordonnées manquantes : à confirmer » et, dans ``aide``, la
    raison et les candidats à montrer à l'humain. Aucun candidat n'est jamais choisi ici.

    Un code postal fourni sert seulement à départager plusieurs correspondances exactes ; un code
    postal qui contredit l'unique correspondance est signalé en avertissement, jamais corrigé."""
    adresse_norm, verdict = analyser_adresse(adresse)
    if verdict is not None:
        return None, verdict
    if index is None:
        return None, _verdict("REJ-INDEX-RQA-ABSENT", "index RQA non ouvert : importer le CSV du RQA")
    exactes = index.chercher(adresse_norm)
    if len(exactes) > 1 and adresse_norm["code_postal"]:
        memes = [ligne for ligne in exactes if ligne["code_postal"] == adresse_norm["code_postal"]]
        if len(memes) == 1:
            exactes = memes
    if not exactes:
        proches = index.chercher_immeuble(adresse_norm)
        return _a_confirmer(
            index, RAISON_AUCUNE, proches,
            "aucune adresse du RQA ne correspond exactement. Redemander au client le numéro, le suffixe ou "
            "l'unité exacts (les candidats du même immeuble sont listés), ou confirmer manuellement.",
        )
    if len(exactes) > 1:
        return _a_confirmer(
            index, RAISON_PLUSIEURS, exactes,
            f"{len(exactes)} adresses du RQA correspondent : demander le code postal ou la municipalité "
            "exacts, ou confirmer une de ces adresses par son identifiant.",
        )
    ligne = exactes[0]
    if not _est_certifiee(ligne["etat"]):
        return _a_confirmer(
            index, RAISON_NON_CERTIFIEE, exactes,
            f"l'adresse du RQA est « {ligne['etat']} » : à vérifier sur place avant de la confirmer.",
        )
    precision = precision_rqa(ligne["qualite"])
    if precision not in PRECISIONS_PROPOSABLES:
        return _a_confirmer(
            index, RAISON_QUALITE, exactes,
            f"position de qualité « {ligne['qualite']} » : à confirmer sur place avant de la confirmer.",
        )
    avertissements = []
    if adresse_norm["code_postal"] and adresse_norm["code_postal"] != ligne["code_postal"]:
        avertissements.append("le code postal fourni diffère de celui du RQA pour cette adresse")
    return {
        "statut": "proposee", "coordonnees": _coordonnees(ligne),
        "qualite_positionnement_geometrique": ligne["qualite"], "precision": precision,
        "rqa_identifiant": ligne["identifiant"], "rqa_version": index.version,
        "adresse_formatee": ligne["adresse_formatee"], "nom_mrc": ligne["nom_mrc"],
        "avertissements": avertissements, "attribution": ATTRIBUTION_RQA,
        "confirmation_humaine_requise": True,
    }, None


# ------------------------------------------------------------------------ chiffrement et empreinte
def nonce_localisation(chantier_id, version):
    """Nonce déterministe (16 octets) : jamais un aléa ambiant. Chaque maillon d'un chantier a sa
    ``version``, strictement croissante (``confirmer`` la calcule depuis le registre) : un couple
    (clé, nonce) ne sert donc jamais pour deux positions."""
    return bytes.fromhex(encodage.empreinte("nonce-localisation-v1", chantier_id, version))[:16]


def _flux_cle(cle, nonce, longueur):
    flux = b""
    compteur = 0
    while len(flux) < longueur:
        flux += hmac.new(cle, _CONTEXTE_FLUX + nonce + compteur.to_bytes(8, "big"), hashlib.sha256).digest()
        compteur += 1
    return flux[:longueur]


def chiffrer_coordonnees(cle, nonce, latitude_micro, longitude_micro):
    """Chiffre ``latitude|longitude`` (microdegrés entiers) en chaîne hexadécimale (HMAC-SHA256 en mode
    compteur, bibliothèque standard, même parti pris que ``retention.py``)."""
    clair = f"{int(latitude_micro)}|{int(longitude_micro)}".encode()
    return bytes(a ^ b for a, b in zip(clair, _flux_cle(cle, nonce, len(clair)), strict=True)).hex()


def dechiffrer_coordonnees(cle, nonce, chiffre_hex):
    """Inverse de ``chiffrer_coordonnees`` : ``(latitude_micro, longitude_micro)``. ``ValueError`` si la
    clé ou le nonce ne conviennent pas, jamais une paire silencieusement fausse."""
    try:
        chiffre = bytes.fromhex(chiffre_hex)
        clair = bytes(a ^ b for a, b in zip(chiffre, _flux_cle(cle, nonce, len(chiffre)), strict=True))
        texte = clair.decode("utf-8")
    except (TypeError, ValueError):
        raise ValueError("déchiffrement invalide : clé ou nonce incorrects") from None
    if not re.fullmatch(r"-?\d+\|-?\d+", texte):
        raise ValueError("déchiffrement invalide : clé ou nonce incorrects")
    latitude, longitude = texte.split("|")
    return int(latitude), int(longitude)


def empreinte_adresse(cle, adresse_norm):
    """HMAC-SHA256 (hexadécimal) de l'adresse normalisée, sous une clé dérivée de la clé du chantier
    (voir l'en-tête du module). Deux écritures équivalentes de la même adresse (``St-`` et ``Saint-``)
    donnent la même empreinte."""
    cle_hmac = hmac.new(cle, _CONTEXTE_EMPREINTE, hashlib.sha256).digest()
    canonique = encodage.encoder_canonique(
        adresse_norm["numero"], adresse_norm["suffixe"], adresse_norm["unite"],
        adresse_norm["cle_odonyme"], adresse_norm["cle_municipalite"],
    )
    return hmac.new(cle_hmac, canonique.encode("utf-8"), hashlib.sha256).hexdigest()


# --------------------------------------------------------------------------------------- registre
def _maillons_du_chantier(registre_cible, chantier_id):
    return [
        m for m in registre_cible.lire()
        if m.get("type_entree") == TYPE_LOCALISATION and m.get("chantier_id") == chantier_id
    ]


def _resume(maillon):
    """Ce qu'un maillon dit de lui-même, sans le chiffré."""
    return {
        "version": maillon["version"], "action": maillon["action"], "source": maillon["source"],
        "precision": maillon["precision"], "rqa_identifiant": maillon["rqa_identifiant"],
        "rqa_version": maillon["rqa_version"], "confirme_par": maillon["confirme_par"],
        "motif": maillon["motif"], "horodatage": maillon["horodatage"], "ligne_id": maillon["ligne_id"],
    }


def confirmation_courante(registre_cible, chantier_id):
    """Résumé (sans coordonnées) du DERNIER maillon de localisation du chantier, ou ``None``."""
    maillons = _maillons_du_chantier(registre_cible, chantier_id)
    return _resume(maillons[-1]) if maillons else None


def _position(maillon, cle):
    """``(latitude_micro, longitude_micro)`` d'un maillon, ou ``None`` si la clé manque ou ne convient pas."""
    if cle is None or maillon["coordonnees_chiffrees"] is None:
        return None
    try:
        return dechiffrer_coordonnees(
            cle, nonce_localisation(maillon["chantier_id"], maillon["version"]), maillon["coordonnees_chiffrees"])
    except ValueError:
        return None


def historique(registre_cible, chantier_id, cle=None):
    """Tous les maillons du chantier, dans l'ordre d'écriture. Avec la clé du chantier, chaque position
    est déchiffrée ; sans clé (détruite), ``position`` vaut ``None`` mais versions, actions, sources et
    signataires restent lisibles."""
    resultat = []
    for maillon in _maillons_du_chantier(registre_cible, chantier_id):
        entree = _resume(maillon)
        position = _position(maillon, cle)
        entree["position"] = None if position is None else {
            "latitude_microdegres": position[0], "longitude_microdegres": position[1]}
        resultat.append(entree)
    return resultat


def position_confirmee(registre_cible, chantier_id, cle, adresse=None):
    """Lecture pour le solveur (T4.1-c) : ``(position, None)`` si une localisation est confirmée et
    lisible, sinon ``(None, verdict)`` qui dit quoi faire.

    - jamais confirmée, ou retirée : ``REJ-COORDONNEES-A-CONFIRMER`` (« coordonnées manquantes : à
      confirmer ») ;
    - clé détruite (``cle`` est ``None``) : ``REJ-LOCALISATION-DETRUITE`` ;
    - ``adresse`` fournie et différente de celle qui a été confirmée : à confirmer de nouveau.
    Le dernier maillon gagne. Rien n'est jamais inventé : ni centre de ville, ni valeur par défaut."""
    maillons = _maillons_du_chantier(registre_cible, chantier_id)
    if not maillons:
        return None, _verdict(
            "REJ-COORDONNEES-A-CONFIRMER", "coordonnées manquantes : à confirmer. Aucune localisation confirmée.")
    dernier = maillons[-1]
    if dernier["action"] != "confirmee":
        return None, _verdict(
            "REJ-COORDONNEES-A-CONFIRMER",
            f"coordonnées manquantes : à confirmer. Localisation retirée à la version {dernier['version']} "
            f"par {dernier['confirme_par']}.")
    if cle is None:
        return None, _verdict(
            "REJ-LOCALISATION-DETRUITE", "clé de chiffrement détruite : la position n'est plus lisible")
    position = _position(dernier, cle)
    if position is None:
        return None, _verdict(
            "REJ-LOCALISATION-DETRUITE", "la clé du chantier ne déchiffre pas cette position")
    if adresse is not None:
        adresse_norm, verdict = analyser_adresse(adresse)
        if verdict is not None:
            return None, verdict
        if empreinte_adresse(cle, adresse_norm) != dernier["empreinte_adresse"]:
            return None, _verdict(
                "REJ-COORDONNEES-A-CONFIRMER",
                "coordonnées manquantes : à confirmer. L'adresse a changé depuis la confirmation "
                f"(version {dernier['version']}).")
    return {
        "chantier_id": chantier_id, "version": dernier["version"],
        "latitude_microdegres": position[0], "longitude_microdegres": position[1],
        "source": dernier["source"], "precision": dernier["precision"],
        "rqa_identifiant": dernier["rqa_identifiant"], "rqa_version": dernier["rqa_version"],
        "confirme_par": dernier["confirme_par"], "horodatage": dernier["horodatage"],
        "ligne_id": dernier["ligne_id"],
    }, None


def _texte_non_vide(valeur, nom):
    if not isinstance(valeur, str):
        return _verdict("REJ-CONTRAT-INVALIDE", f"{nom} : texte attendu")
    if valeur.strip() == "":
        return _verdict("REJ-CHAMP-VIDE", f"{nom} vide")
    return None


def _entier_strict(valeur):
    return isinstance(valeur, int) and not isinstance(valeur, bool)


def _preparer_confirmation(
    courant, adresse, source, rqa_identifiant, latitude_microdegres, longitude_microdegres, motif, index,
):
    """Valide une confirmation ; ``(elements, None)`` ou ``(None, verdict)``. Aucun effet de bord :
    la clé du chantier n'est demandée qu'après ce point."""
    if adresse is None:
        return None, _verdict("REJ-CHAMP-MANQUANT", "adresse manquante : nécessaire à l'empreinte de la confirmation")
    adresse_norm, verdict = analyser_adresse(adresse)
    if verdict is not None:
        return None, verdict
    if source not in SOURCES_LOCALISATION:
        return None, _verdict("REJ-ENUM-INVALIDE", f"source invalide : {source!r} (attendu {SOURCES_LOCALISATION})")
    if not isinstance(motif, str):
        return None, _verdict("REJ-CONTRAT-INVALIDE", "motif : texte attendu")
    motif_requis = None
    if courant is not None and courant["action"] == "confirmee":
        motif_requis = "remplacer une localisation déjà confirmée"

    if source == "manuel":
        if rqa_identifiant is not None:
            return None, _verdict("REJ-CONTRAT-INVALIDE", "rqa_identifiant n'a pas de sens pour une saisie manuelle")
        if not (_entier_strict(latitude_microdegres) and _entier_strict(longitude_microdegres)):
            return None, _verdict(
                "REJ-CHAMP-MANQUANT", "saisie manuelle : latitude_microdegres et longitude_microdegres (entiers)")
        if not _dans_le_quebec(latitude_microdegres, longitude_microdegres):
            return None, _verdict(
                "REJ-CONTRAT-INVALIDE",
                "coordonnées hors du Québec : latitude et longitude inversées, ou mauvaise unité "
                "(microdegrés : degrés × 1 000 000)")
        elements = {"latitude": latitude_microdegres, "longitude": longitude_microdegres,
                    "precision": PRECISION_MANUELLE, "rqa_identifiant": None, "rqa_version": None}
    else:
        if latitude_microdegres is not None or longitude_microdegres is not None:
            return None, _verdict(
                "REJ-CONTRAT-INVALIDE",
                "source rqa : les coordonnées viennent de l'index par rqa_identifiant, jamais des arguments")
        if rqa_identifiant is None:
            return None, _verdict("REJ-CHAMP-MANQUANT", "source rqa : rqa_identifiant manquant")
        verdict = _texte_non_vide(rqa_identifiant, "rqa_identifiant")
        if verdict is not None:
            return None, verdict
        if index is None:
            return None, _verdict("REJ-INDEX-RQA-ABSENT", "index RQA non ouvert : importer le CSV du RQA")
        ligne = index.lire(rqa_identifiant)
        if ligne is None:
            return None, _verdict("REJ-CONTRAT-INVALIDE", "rqa_identifiant inconnu de l'index RQA")
        if (ligne["numero"], ligne["suffixe"], ligne["unite"], ligne["cle_odonyme"], ligne["cle_municipalite"]) != (
            adresse_norm["numero"], adresse_norm["suffixe"], adresse_norm["unite"],
            adresse_norm["cle_odonyme"], adresse_norm["cle_municipalite"],
        ) or (adresse_norm["code_municipalite"] and ligne["code_municipalite"] != adresse_norm["code_municipalite"]):
            return None, _verdict(
                "REJ-CONTRAT-INVALIDE",
                "l'adresse du RQA ne correspond pas EXACTEMENT à l'adresse fournie : corriger l'adresse "
                "(suffixe, unité) ou confirmer manuellement les coordonnées")
        precision = precision_rqa(ligne["qualite"])
        if not _est_certifiee(ligne["etat"]) or precision not in PRECISIONS_PROPOSABLES:
            motif_requis = (
                f"confirmer une position « {ligne['qualite']} » / adresse « {ligne['etat']} » "
                "(à vérifier sur place : dire comment)")
        elements = {"latitude": ligne["latitude_micro"], "longitude": ligne["longitude_micro"],
                    "precision": precision, "rqa_identifiant": ligne["identifiant"],
                    "rqa_version": index.version}
    if motif_requis is not None and motif.strip() == "":
        return None, _verdict("REJ-CHAMP-VIDE", f"motif obligatoire pour {motif_requis}")
    elements["adresse_norm"] = adresse_norm
    return elements, None


def confirmer(
    registre_cible, chantier_id, action, horodatage_arg, confirme_par, *, adresse=None, source=None,
    rqa_identifiant=None, latitude_microdegres=None, longitude_microdegres=None, motif="",
    index=None, fournir_cle=None,
):
    """Écrit le maillon ``localisation_chantier`` suivant. ``(accusé, None)`` ou ``(None, verdict)``.
    RIEN n'est écrit en cas de refus : toutes les vérifications précèdent la demande de clé et
    l'écriture.

    ``confirmee`` : ``adresse`` et ``source`` obligatoires. ``rqa`` : ``rqa_identifiant`` d'une adresse
    de l'index qui correspond EXACTEMENT à ``adresse`` (les coordonnées viennent de l'index) ;
    ``manuel`` : ``latitude_microdegres`` et ``longitude_microdegres`` saisis par l'humain. Un ``motif``
    est obligatoire pour remplacer une confirmation, et pour confirmer une position de qualité faible
    ou une adresse non certifiée (« à confirmer sur place »).
    ``retiree`` : retire la confirmation courante (motif obligatoire) ; le chantier redevient « à
    confirmer ».

    ``fournir_cle`` : appelable sans argument qui rend la clé de chiffrement du chantier (création si
    besoin) ; il n'est appelé qu'une fois la confirmation validée. L'accusé ne porte ni coordonnées ni
    adresse."""
    for nom, valeur in (("chantier_id", chantier_id), ("confirme_par", confirme_par)):
        verdict = _texte_non_vide(valeur, nom)
        if verdict is not None:
            return None, verdict
    try:
        horodatage_mod.valider_horodatage(horodatage_arg)
    except ValueError:
        return None, _verdict("REJ-HORODATAGE-INVALIDE", f"horodatage invalide : {horodatage_arg!r}")
    if action not in ACTIONS_LOCALISATION:
        return None, _verdict("REJ-ENUM-INVALIDE", f"action invalide : {action!r} (attendu {ACTIONS_LOCALISATION})")

    maillons = _maillons_du_chantier(registre_cible, chantier_id)
    courant = maillons[-1] if maillons else None
    version = (courant["version"] if courant else 0) + 1
    maillon = {
        "type_entree": TYPE_LOCALISATION, "chantier_id": chantier_id, "version": version, "action": action,
        "coordonnees_chiffrees": None, "empreinte_adresse": None, "source": None, "rqa_identifiant": None,
        "rqa_version": None, "precision": None, "confirme_par": confirme_par,
        "motif": motif if isinstance(motif, str) else "", "horodatage": horodatage_arg,
    }

    if action == "retiree":
        if not isinstance(motif, str) or motif.strip() == "":
            return None, _verdict("REJ-CHAMP-VIDE", "motif obligatoire pour retirer une localisation confirmée")
        if any(v is not None for v in (adresse, source, rqa_identifiant, latitude_microdegres, longitude_microdegres)):
            return None, _verdict(
                "REJ-CONTRAT-INVALIDE",
                "retirer une localisation ne prend ni adresse, ni source, ni coordonnées")
        if courant is None or courant["action"] != "confirmee":
            return None, _verdict("REJ-CONTRAT-INVALIDE", "aucune localisation confirmée à retirer")
    else:
        elements, verdict = _preparer_confirmation(
            courant, adresse, source, rqa_identifiant, latitude_microdegres, longitude_microdegres, motif, index)
        if verdict is not None:
            return None, verdict
        if fournir_cle is None:
            return None, _verdict("REJ-CONTRAT-INVALIDE", "aucune clé de chiffrement disponible : confirmation refusée")
        cle = fournir_cle()
        maillon.update({
            "coordonnees_chiffrees": chiffrer_coordonnees(
                cle, nonce_localisation(chantier_id, version), elements["latitude"], elements["longitude"]),
            "empreinte_adresse": empreinte_adresse(cle, elements["adresse_norm"]),
            "source": source, "rqa_identifiant": elements["rqa_identifiant"],
            "rqa_version": elements["rqa_version"], "precision": elements["precision"],
        })

    ligne_id = registre_cible.ajouter(maillon)
    return {
        "chantier_id": chantier_id, "version": version, "action": action, "source": maillon["source"],
        "precision": maillon["precision"], "confirme_par": confirme_par, "horodatage": horodatage_arg,
        "ligne_id": ligne_id, "tete_chaine": registre_cible.tete(),
    }, None


# ------------------------------------------------------------------------------------------- CLI
def principal(argv=None):
    """``python -m m4_field_ops.localisation importer --csv RQA.csv --index INDEX [--version V]
    [--mrc CODE_OU_NOM ...]`` : construit l'index local. Rend 0, ou 1 avec la raison sur ``stderr``."""
    analyseur = argparse.ArgumentParser(prog="m4_field_ops.localisation")
    sous = analyseur.add_subparsers(dest="commande", required=True)
    imp = sous.add_parser("importer", help="importer le CSV du RQA dans l'index local")
    imp.add_argument("--csv", required=True)
    imp.add_argument(
        "--index", required=True,
        help=f"fichier SQLite, en général <OPSYS_HOME>/{SOUS_DOSSIER_INDEX}/{NOM_FICHIER_INDEX}",
    )
    imp.add_argument("--version")
    imp.add_argument("--mrc", nargs="+")
    arguments = analyseur.parse_args(argv)
    try:
        rapport = importer_rqa(arguments.csv, arguments.index, version=arguments.version, mrc=arguments.mrc)
    except (OSError, ValueError, csv.Error) as exc:
        print(f"import refusé : {exc}", file=sys.stderr)
        return 1
    print(json.dumps(rapport, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(principal())
