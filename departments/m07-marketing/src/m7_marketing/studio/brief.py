"""Le brief créatif : ce qu'on demande au studio, sous forme de DONNÉES structurées.

Un brief dit : l'objet de la pièce, le gabarit et le format, la marque (instantané du profil de marque existant, posé
par l'outil, jamais par l'agent), les textes libres par langue, les éléments CRITIQUES (téléphone, courriel, adresse,
licence RBQ, NEQ, prix, site) en champs typés avec leur source, les mentions obligatoires (mot pour mot), la nature du
fond (uni, dégradé, ou généré) et la couleur demandée. Les éléments critiques et les mentions ne sont jamais confiés
à un modèle d'image : le gabarit les pose, le contrôle de sortie les relit.

Fail-closed : un champ inconnu, un type faux, une valeur hors liste, une forme de téléphone ou de licence invalide, un
caractère de contrôle ou bidirectionnel (attaque d'homographe sur une donnée critique) est un refus
`{code, chemin, detail}`, jamais une valeur corrigée en silence. Un brief `fictif` n'accepte que des coordonnées
fictives (numéro 555-01XX, courriel d'un domaine réservé).

Contraintes légales (R5 §5.4) : le français doit être nettement prédominant dans l'affichage commercial au Québec. Ce
module n'en juge pas : le gabarit mesure la part du français et le contrôle qualité applique un SEUIL PARAMÉTRABLE,
déclaré comme heuristique (le seuil réglementaire n'est pas établi : à valider par un avocat). Le brief exige au moins
le texte français de chaque rôle ; l'anglais est facultatif.

Module pur : aucune entrée-sortie, aucune horloge.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import re
import unicodedata
from collections.abc import Mapping
from typing import Any

from opsys import garde_fou_texte as socle

from ..usine import controle_texte

SCHEMA = "opsys.studio.brief/v1"
GABARITS = {
    # gabarit -> {format: libellé} ; les dimensions sont dans `gabarits.py` (une seule source).
    "carte_affaires": ("3.5x2",),
    "affiche": ("11x17", "18x24"),
    "banniere_social": ("1200x627", "1080x1350", "1080x1080", "1080x1920", "1280x720"),
    "couverture": ("1640x624",),
}
CANAUX = ("impression", "facebook", "instagram", "linkedin", "gbp", "youtube", "tiktok", "site")
CANAL_PAR_GABARIT = {
    "carte_affaires": ("impression",),
    "affiche": ("impression",),
    "banniere_social": ("facebook", "instagram", "linkedin", "gbp", "youtube", "tiktok", "site"),
    "couverture": ("facebook", "linkedin", "youtube", "site"),
}
ROLES_TEXTE = ("titre", "sous_titre", "appel_action")
LANGUES = ("fr", "en")
TYPES_CRITIQUES = ("telephone", "courriel", "adresse", "licence_rbq", "neq", "prix", "site_web")
MODES_FOND = ("uni", "degrade", "genere")
RENDUS_FOND = ("photographique", "illustration")
PROFILS_COULEUR = ("rvb", "cmjn")
CHAMPS_BRIEF = (
    "schema",
    "fictif",
    "objet",
    "gabarit",
    "format",
    "canal",
    "marque",
    "langues",
    "textes",
    "elements_critiques",
    "mentions_obligatoires",
    "fond",
    "couleur",
    "ppp",
    "logo_actif_id",
)
CHAMPS_MARQUE = ("nom", "couleurs", "langue", "empreinte_profil")
CHAMPS_CRITIQUE = ("type", "valeur", "source")
CHAMPS_CRITIQUE_PRIX = ("type", "valeur", "source", "valide_jusqu_au")
CHAMPS_FOND = ("mode", "sujet", "ambiance", "rendu", "graine")

REJ_CHAMP = "REJ-STUDIO-BRIEF-CHAMP"
REJ_CHAMP_INCONNU = "REJ-STUDIO-BRIEF-CHAMP-INCONNU"
REJ_VALEUR = "REJ-STUDIO-BRIEF-VALEUR"
REJ_CRITIQUE = "REJ-STUDIO-BRIEF-ELEMENT-CRITIQUE"
REJ_TEXTE = "REJ-STUDIO-BRIEF-TEXTE"
REJ_FICTIF = "REJ-STUDIO-BRIEF-FICTIF"
REJ_FOND = "REJ-STUDIO-BRIEF-FOND"
REJ_FRANCAIS = "REJ-STUDIO-BRIEF-FRANCAIS"

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_COULEUR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_ID_ACTIF = re.compile(r"^[a-z][a-z0-9-]{2,60}$")
_TELEPHONE = re.compile(r"^(?:\+1 )?\(?([2-9]\d{2})\)?[ -]([2-9]\d{2})[ -](\d{4})$", re.ASCII)
_COURRIEL = re.compile(r"^[a-z0-9._-]{1,64}@([a-z0-9.-]{3,200})$")
_RBQ = re.compile(r"^\d{4}-\d{4}-\d{2}$", re.ASCII)
_NEQ = re.compile(r"^\d{10}$", re.ASCII)
_PRIX = re.compile(r"^\d{1,3}(?: \d{3})*(?:,\d{2})? \$$", re.ASCII)
_CODE_POSTAL = re.compile(r"[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z] \d[ABCEGHJ-NPRSTV-Z]\d", re.ASCII)
_SITE = re.compile(r"^(?:https://)?([a-z0-9][a-z0-9.-]{2,200}\.[a-z]{2,24})$")
_DOMAINES_RESERVES = (".example", ".test", ".invalid", ".localhost")
# Contrôle, bidirectionnel, largeur nulle : jamais dans un texte affiché (attaque d'homographe / texte inversé).
_INTERDITS = re.compile(r"[\u0000-\u001f\u007f-\u009f​-‏ -‮⁠-⁯﻿]")
# Pas de texte, de logo ni de marque tierce dans l'invite d'un fond (décision r2 n°3 ; R5 §5.4) : heuristique.
MOTS_INTERDITS_FOND = (
    "logo",
    "texte",
    "text ",
    "lettre",
    "letter",
    "slogan",
    "titre",
    "title",
    "caption",
    "legende",
    "filigrane",
    "watermark",
    "signature",
    "numero",
    "telephone",
    "phone",
    "adresse",
    "address",
    "prix",
    "price",
    "marque",
    "brand",
    "mot ",
    "word",
    "ecrit",
    "written",
    "dans le style",
    "a la maniere",
    "in the style",
    "style of",
    "disney",
    "nike",
    "apple",
    "coca",
    "marvel",
    "pixar",
    "ghibli",
)
TEXTE_MAX = 120
OBJET_MAX = 200


def _refus(code: str, chemin: str, detail: str) -> dict[str, str]:
    return {"code": code, "chemin": chemin, "detail": detail}


def _objet_strict(
    donnees: Any, champs: tuple[str, ...], chemin: str, refus: list[dict[str, str]], facultatifs: tuple[str, ...] = ()
) -> bool:
    avant = len(refus)
    if not isinstance(donnees, Mapping):
        refus.append(_refus(REJ_CHAMP, chemin, "objet attendu"))
        return False
    for nom in sorted(set(donnees) - set(champs)):
        refus.append(_refus(REJ_CHAMP_INCONNU, f"{chemin}.{nom}", "champ inconnu"))
    for nom in champs:
        if nom not in donnees and nom not in facultatifs:
            refus.append(_refus(REJ_CHAMP, f"{chemin}.{nom}", "champ requis absent"))
    return len(refus) == avant


def _texte_affichable(
    valeur: Any,
    chemin: str,
    refus: list[dict[str, str]],
    *,
    minimum: int = 1,
    maximum: int = TEXTE_MAX,
    code: str = REJ_TEXTE,
) -> bool:
    if not isinstance(valeur, str) or not minimum <= len(valeur) <= maximum:
        refus.append(_refus(code, chemin, f"texte de {minimum} à {maximum} caractères attendu"))
        return False
    if _INTERDITS.search(valeur):
        refus.append(_refus(code, chemin, "caractère de contrôle, bidirectionnel ou de largeur nulle interdit"))
        return False
    if not unicodedata.is_normalized("NFC", valeur) or valeur != valeur.strip():
        refus.append(_refus(code, chemin, "texte NFC sans espace en bordure attendu"))
        return False
    if "  " in valeur or "  " in valeur:
        refus.append(_refus(code, chemin, "espaces doubles interdits"))
        return False
    return True


def _critique(element: Any, chemin: str, fictif: bool, refus: list[dict[str, str]]) -> None:
    if not isinstance(element, Mapping):
        refus.append(_refus(REJ_CRITIQUE, chemin, "objet attendu"))
        return
    type_ = element.get("type")
    champs = CHAMPS_CRITIQUE_PRIX if type_ == "prix" else CHAMPS_CRITIQUE
    if not _objet_strict(element, champs, chemin, refus):
        return
    if type_ not in TYPES_CRITIQUES:
        refus.append(_refus(REJ_CRITIQUE, f"{chemin}.type", f"un de {list(TYPES_CRITIQUES)} attendu"))
        return
    valeur = element["valeur"]
    if not _texte_affichable(valeur, f"{chemin}.valeur", refus, maximum=160, code=REJ_CRITIQUE):
        return
    if " " in valeur or " " in valeur:
        refus.append(_refus(REJ_CRITIQUE, f"{chemin}.valeur", "espace ordinaire seulement dans une donnée critique"))
        return
    source = element["source"]
    if not isinstance(source, str) or not 3 <= len(source) <= 120 or _INTERDITS.search(source):
        refus.append(_refus(REJ_CRITIQUE, f"{chemin}.source", "source documentaire de 3 à 120 caractères exigée"))
    if type_ == "telephone":
        trouve = _TELEPHONE.fullmatch(valeur)
        if trouve is None:
            refus.append(_refus(REJ_CRITIQUE, f"{chemin}.valeur", "numéro nord-américain « +1 450 555 0142 » attendu"))
        elif fictif and not (trouve.group(2) == "555" and trouve.group(3).startswith("01")):
            refus.append(_refus(REJ_FICTIF, f"{chemin}.valeur", "brief fictif : numéro de la plage fictive 555-01XX"))
    elif type_ == "courriel":
        trouve = _COURRIEL.fullmatch(valeur)
        if trouve is None:
            refus.append(_refus(REJ_CRITIQUE, f"{chemin}.valeur", "courriel en minuscules attendu"))
        elif fictif and not trouve.group(1).endswith(_DOMAINES_RESERVES):
            refus.append(_refus(REJ_FICTIF, f"{chemin}.valeur", "brief fictif : domaine réservé (.example, .test)"))
    elif type_ == "licence_rbq":
        if not _RBQ.fullmatch(valeur):
            refus.append(_refus(REJ_CRITIQUE, f"{chemin}.valeur", "numéro de licence RBQ « 0000-0000-00 » attendu"))
    elif type_ == "neq":
        if not _NEQ.fullmatch(valeur):
            refus.append(_refus(REJ_CRITIQUE, f"{chemin}.valeur", "NEQ de 10 chiffres attendu"))
    elif type_ == "adresse":
        if not _CODE_POSTAL.search(valeur):
            refus.append(_refus(REJ_CRITIQUE, f"{chemin}.valeur", "adresse avec code postal canadien « H7N 1A1 »"))
    elif type_ == "site_web":
        trouve = _SITE.fullmatch(valeur)
        if trouve is None:
            refus.append(_refus(REJ_CRITIQUE, f"{chemin}.valeur", "nom de domaine attendu (sans chemin)"))
        elif fictif and not trouve.group(1).endswith(_DOMAINES_RESERVES):
            refus.append(_refus(REJ_FICTIF, f"{chemin}.valeur", "brief fictif : domaine réservé (.example, .test)"))
    elif type_ == "prix":
        if not _PRIX.fullmatch(valeur):
            refus.append(_refus(REJ_CRITIQUE, f"{chemin}.valeur", "prix « 1 250,00 $ » attendu (espace, virgule)"))
        limite = element.get("valide_jusqu_au")
        try:
            if not isinstance(limite, str) or dt.date.fromisoformat(limite).isoformat() != limite:
                raise ValueError
        except ValueError:
            refus.append(_refus(REJ_CRITIQUE, f"{chemin}.valide_jusqu_au", "date de fin de validité AAAA-MM-JJ exigée"))


def _marque(marque: Any, refus: list[dict[str, str]]) -> None:
    if not _objet_strict(marque, CHAMPS_MARQUE, "$.marque", refus):
        return
    _texte_affichable(marque["nom"], "$.marque.nom", refus, maximum=80, code=REJ_VALEUR)
    couleurs = marque["couleurs"]
    if (
        not isinstance(couleurs, list)
        or not 1 <= len(couleurs) <= 8
        or any(not isinstance(c, str) or not _COULEUR.fullmatch(c) for c in couleurs)
    ):
        refus.append(_refus(REJ_VALEUR, "$.marque.couleurs", "1 à 8 couleurs #RRGGBB attendues"))
    if marque["langue"] != "fr":
        refus.append(_refus(REJ_FRANCAIS, "$.marque.langue", "la langue de la marque est « fr » (affichage au Québec)"))
    if not isinstance(marque["empreinte_profil"], str) or not _SHA256.fullmatch(marque["empreinte_profil"]):
        refus.append(_refus(REJ_VALEUR, "$.marque.empreinte_profil", "empreinte SHA-256 du profil de marque attendue"))


def _fond(fond: Any, refus: list[dict[str, str]]) -> None:
    if not isinstance(fond, Mapping) or fond.get("mode") not in MODES_FOND:
        refus.append(_refus(REJ_FOND, "$.fond.mode", f"un de {list(MODES_FOND)} attendu"))
        return
    if fond["mode"] != "genere":
        if set(fond) != {"mode"}:
            refus.append(_refus(REJ_FOND, "$.fond", "un fond uni ou dégradé n'a aucun autre champ"))
        return
    if not _objet_strict(fond, CHAMPS_FOND, "$.fond", refus, facultatifs=("ambiance", "rendu", "graine")):
        return
    if not _texte_affichable(fond["sujet"], "$.fond.sujet", refus, minimum=5, maximum=160, code=REJ_FOND):
        return
    if "ambiance" in fond and not _texte_affichable(
        fond["ambiance"], "$.fond.ambiance", refus, minimum=3, maximum=100, code=REJ_FOND
    ):
        return
    if fond.get("rendu", "photographique") not in RENDUS_FOND:
        refus.append(_refus(REJ_FOND, "$.fond.rendu", f"un de {list(RENDUS_FOND)} attendu"))
    graine = fond.get("graine")
    if "graine" in fond and (type(graine) is not int or not 0 <= graine < 2**32):
        refus.append(_refus(REJ_FOND, "$.fond.graine", "entier de 0 à 2^32-1 attendu"))
    for cle in ("sujet", "ambiance"):
        brut = " " + socle_plier(fond.get(cle, "")) + " "
        for mot in MOTS_INTERDITS_FOND:
            if mot in brut:
                refus.append(
                    _refus(
                        REJ_FOND,
                        f"$.fond.{cle}",
                        f"« {mot.strip()} » interdit dans la description d'un fond : le texte, le logo et les noms de "
                        "marque sont posés par le gabarit, jamais demandés à un modèle (décision r2 n°3)",
                    )
                )
                break


def socle_plier(texte: str) -> str:
    """Forme de recherche (compatibilité Unicode, sans accents, minuscules, espaces réduits) des mots interdits."""
    normal = unicodedata.normalize("NFKC", texte).replace("’", "'")
    sans_accents = "".join(c for c in unicodedata.normalize("NFD", normal) if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", sans_accents).casefold()


@dataclasses.dataclass(frozen=True)
class Brief:
    donnees: Mapping[str, Any]

    @property
    def fictif(self) -> bool:
        return self.donnees["fictif"]

    @property
    def gabarit(self) -> str:
        return self.donnees["gabarit"]

    @property
    def format(self) -> str:
        return self.donnees["format"]

    @property
    def marque(self) -> Mapping[str, Any]:
        return self.donnees["marque"]

    @property
    def textes(self) -> Mapping[str, Mapping[str, str]]:
        return self.donnees["textes"]

    @property
    def elements_critiques(self) -> list[Mapping[str, Any]]:
        return self.donnees["elements_critiques"]

    @property
    def mentions(self) -> list[str]:
        return self.donnees["mentions_obligatoires"]

    @property
    def fond(self) -> Mapping[str, Any]:
        return self.donnees["fond"]

    @property
    def langues(self) -> list[str]:
        return self.donnees["langues"]

    @property
    def genere(self) -> bool:
        return self.fond["mode"] == "genere"

    def vers_dict(self) -> dict[str, Any]:
        return json.loads(canonique(self.donnees))

    def empreinte(self) -> str:
        return empreinte(self.donnees)

    def empreinte_fond(self) -> str:
        """Ce qui détermine le fond : un fond généré n'est valable que pour cette description et ce format."""
        return hashlib.sha256(
            (
                "opsys-studio-fond/v1\n"
                + canonique(
                    {
                        "fond": self.fond,
                        "gabarit": self.gabarit,
                        "format": self.format,
                        "couleurs": self.marque["couleurs"],
                    }
                )
            ).encode("utf-8")
        ).hexdigest()


def canonique(donnees: Any) -> str:
    return json.dumps(donnees, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def empreinte(donnees: Any) -> str:
    return hashlib.sha256(("opsys-studio-brief/v1\n" + canonique(donnees)).encode("utf-8")).hexdigest()


def depuis_dict(donnees: Any) -> tuple[Brief | None, list[dict[str, str]]]:
    """(brief, refus). Un seul des deux est utile : jamais de brief partiel."""
    refus: list[dict[str, str]] = []
    if not _objet_strict(donnees, CHAMPS_BRIEF, "$", refus, facultatifs=("ppp", "logo_actif_id")):
        return None, refus
    if donnees["schema"] != SCHEMA:
        refus.append(_refus(REJ_VALEUR, "$.schema", f"version attendue {SCHEMA!r}"))
    if type(donnees["fictif"]) is not bool:
        refus.append(_refus(REJ_VALEUR, "$.fictif", "booléen attendu"))
    fictif = donnees["fictif"] is True
    _texte_affichable(donnees["objet"], "$.objet", refus, minimum=5, maximum=OBJET_MAX, code=REJ_VALEUR)
    gabarit, format_ = donnees["gabarit"], donnees["format"]
    if gabarit not in GABARITS:
        refus.append(_refus(REJ_VALEUR, "$.gabarit", f"un de {list(GABARITS)} attendu"))
    elif format_ not in GABARITS[gabarit]:
        refus.append(_refus(REJ_VALEUR, "$.format", f"un de {list(GABARITS[gabarit])} attendu pour {gabarit}"))
    if gabarit in CANAL_PAR_GABARIT and donnees["canal"] not in CANAL_PAR_GABARIT[gabarit]:
        refus.append(_refus(REJ_VALEUR, "$.canal", f"canal de {gabarit} : {list(CANAL_PAR_GABARIT[gabarit])}"))
    _marque(donnees["marque"], refus)
    langues = donnees["langues"]
    if not isinstance(langues, list) or langues not in (["fr"], ["fr", "en"]):
        refus.append(
            _refus(REJ_FRANCAIS, "$.langues", '["fr"] ou ["fr", "en"] : le français vient toujours en premier')
        )
        langues = ["fr"]
    textes = donnees["textes"]
    if not isinstance(textes, Mapping) or "titre" not in textes or set(textes) - set(ROLES_TEXTE):
        refus.append(_refus(REJ_TEXTE, "$.textes", f"rôles parmi {list(ROLES_TEXTE)}, « titre » obligatoire"))
    else:
        contexte = socle.Contexte(
            noms_de_marque=(donnees["marque"].get("nom", "") if isinstance(donnees["marque"], Mapping) else "",),
            longueur_max=TEXTE_MAX,
        )
        for role in sorted(textes):
            par_langue = textes[role]
            chemin = f"$.textes.{role}"
            if not isinstance(par_langue, Mapping) or "fr" not in par_langue or set(par_langue) - set(LANGUES):
                refus.append(_refus(REJ_FRANCAIS, chemin, "texte français obligatoire ; langues permises : fr, en"))
                continue
            for langue in sorted(par_langue):
                if langue not in langues:
                    refus.append(_refus(REJ_FRANCAIS, f"{chemin}.{langue}", "langue absente de $.langues"))
                    continue
                if not _texte_affichable(par_langue[langue], f"{chemin}.{langue}", refus):
                    continue
                if langue == "fr":
                    for violation in controle_texte.controler_texte(par_langue[langue], contexte):
                        refus.append(_refus(violation.regle, f"{chemin}.{langue}", violation.detail))
    critiques = donnees["elements_critiques"]
    if not isinstance(critiques, list) or len(critiques) > 12:
        refus.append(_refus(REJ_CRITIQUE, "$.elements_critiques", "liste de 12 éléments au plus"))
    else:
        for rang, element in enumerate(critiques):
            _critique(element, f"$.elements_critiques[{rang}]", fictif, refus)
        valeurs = [e.get("valeur") for e in critiques if isinstance(e, Mapping)]
        if len(set(map(str, valeurs))) != len(valeurs):
            refus.append(_refus(REJ_CRITIQUE, "$.elements_critiques", "valeur en double"))
    mentions = donnees["mentions_obligatoires"]
    if not isinstance(mentions, list) or len(mentions) > 6:
        refus.append(_refus(REJ_TEXTE, "$.mentions_obligatoires", "liste de 6 mentions au plus"))
    else:
        for rang, mention in enumerate(mentions):
            _texte_affichable(mention, f"$.mentions_obligatoires[{rang}]", refus, minimum=3, maximum=200)
        if len(set(map(str, mentions))) != len(mentions):
            refus.append(_refus(REJ_TEXTE, "$.mentions_obligatoires", "mention en double"))
    _fond(donnees["fond"], refus)
    if donnees["couleur"] not in PROFILS_COULEUR:
        refus.append(_refus(REJ_VALEUR, "$.couleur", f"un de {list(PROFILS_COULEUR)} attendu"))
    if "ppp" in donnees and (type(donnees["ppp"]) is not int or not 72 <= donnees["ppp"] <= 600):
        refus.append(_refus(REJ_VALEUR, "$.ppp", "entier de 72 à 600 attendu"))
    if "logo_actif_id" in donnees and (
        not isinstance(donnees["logo_actif_id"], str) or not _ID_ACTIF.fullmatch(donnees["logo_actif_id"])
    ):
        refus.append(_refus(REJ_VALEUR, "$.logo_actif_id", "identifiant d'actif de logo attendu"))
    if refus:
        return None, refus
    return Brief(json.loads(canonique(donnees))), []
