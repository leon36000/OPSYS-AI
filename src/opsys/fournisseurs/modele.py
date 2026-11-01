"""Modèle du registre de fournisseurs (DECISIONS-ARCHITECTE r1 §6, FEUILLE-DE-ROUTE r2 B.2).

Un fournisseur est une capacité technique (LLM, OCR, TTS…) servie en local ou par API. Chaque
déclaration porte un bloc licence complet : c'est lui que le moteur de politique
(`opsys.fournisseurs.politique`) confronte au profil du client avant toute activation.

Règles de forme (fail-closed) :
- aucune valeur de secret : seulement une référence `coffre:<nom>` vers `opsys.secrets_coffre` ;
- un montant est une chaîne décimale (jamais un flottant) avec sa devise et son unité ;
- un champ de licence inconnu se déclare `inconnu`/`incertain`, jamais une valeur supposée.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

CAPACITES: tuple[str, ...] = (
    "llm", "embeddings", "reranker", "ocr", "stt", "tts", "avatar", "image", "video", "recherche_web", "courriel",
)
MODES = ("local", "api")
STATUTS_CATALOGUE = ("adopte", "repli", "conditionnel", "ecarte", "declare")
QUALIFICATIONS = ("a_mesurer", "qualifie")
USAGES_COMMERCIAUX = ("autorise", "interdit", "sous_seuil", "sur_contrat", "inconnu")
SERVICES_TIERS = ("autorise", "interdit", "incertain")
VERIFICATIONS = ("verifiee", "a_lire")
INTEGRATIONS = ("bibliotheque", "service_separe", "api", "appareil")
TERRITOIRES = ("CA", "US", "UE", "UK", "KR", "CN", "AUTRE")
RESIDENCES = ("local", "QC", "CA", "US", "UE", "inconnue")
DEVISES = ("USD", "CAD", "EUR")
PREFIXE_SECRET = "coffre:"

_IDENTIFIANT = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")
_NOM_SECRET = re.compile(r"^[a-z0-9][a-z0-9._-]{2,79}$")
_UNITE = re.compile(r"^[a-z_]{2,32}$")
_URL = re.compile(r"^(https?://[^\s\"'<>]{3,500}|module:[a-z_][a-z0-9_.]{0,120}|binaire:[a-z0-9_.-]{1,64}|appareil:[a-z0-9_.-]{1,64})$")
_COPYLEFT = re.compile(r"\b(A?GPL|AGPL)(-\d(\.\d)?)?", re.IGNORECASE)
_TEXTE_MAX = 600


class DeclarationInvalide(ValueError):
    """Déclaration de fournisseur refusée avant toute écriture ; le message ne contient aucune valeur secrète."""


def _texte(valeur: Any, champ: str, *, requis: bool = True, maximum: int = _TEXTE_MAX) -> str | None:
    if valeur is None or valeur == "":
        if requis:
            raise DeclarationInvalide(f"{champ} requis")
        return None
    if not isinstance(valeur, str) or len(valeur) > maximum or not valeur.isprintable():
        raise DeclarationInvalide(f"{champ} invalide (texte imprimable de {maximum} caractères maximum)")
    return valeur.strip()


def _choix(valeur: Any, champ: str, permis: tuple[str, ...]) -> str:
    if valeur not in permis:
        raise DeclarationInvalide(f"{champ} invalide : {', '.join(permis)}")
    return valeur


@dataclasses.dataclass(frozen=True)
class Licence:
    """Bloc licence d'un fournisseur. `code` : licence du logiciel ; `poids` : licence des poids (None si sans
    poids, ex. API ou bibliothèque sans modèle). `usage_commercial` : `sous_seuil` exige `seuil_revenu_usd` ;
    `sur_contrat` exige une référence de contrat à l'activation. `verification` : `a_lire` tant qu'un humain n'a
    pas lu le texte intégral (fail-closed : refus d'activation)."""

    code: str | None
    poids: str | None
    usage_commercial: str
    seuil_revenu_usd: int | None = None
    territoires_exclus: tuple[str, ...] = ()
    service_tiers: str = "incertain"
    mention_obligatoire: str | None = None
    integration: str = "bibliotheque"
    verification: str = "verifiee"
    source: str = ""
    note: str | None = None

    def __post_init__(self) -> None:
        _texte(self.code, "licence.code", requis=False, maximum=160)
        _texte(self.poids, "licence.poids", requis=False, maximum=240)
        if self.code is None and self.poids is None:
            raise DeclarationInvalide("licence : au moins la licence du code ou celle des poids est requise")
        _choix(self.usage_commercial, "licence.usage_commercial", USAGES_COMMERCIAUX)
        if self.seuil_revenu_usd is not None and (
            type(self.seuil_revenu_usd) is not int or self.seuil_revenu_usd <= 0
        ):
            raise DeclarationInvalide("licence.seuil_revenu_usd doit être un entier positif (USD)")
        if self.usage_commercial == "sous_seuil" and self.seuil_revenu_usd is None:
            raise DeclarationInvalide("licence : usage « sous_seuil » sans seuil_revenu_usd")
        if not isinstance(self.territoires_exclus, tuple) or any(
            t not in TERRITOIRES for t in self.territoires_exclus
        ) or len(set(self.territoires_exclus)) != len(self.territoires_exclus):
            raise DeclarationInvalide(f"licence.territoires_exclus invalide : {', '.join(TERRITOIRES)}")
        _choix(self.service_tiers, "licence.service_tiers", SERVICES_TIERS)
        _texte(self.mention_obligatoire, "licence.mention_obligatoire", requis=False, maximum=200)
        _choix(self.integration, "licence.integration", INTEGRATIONS)
        _choix(self.verification, "licence.verification", VERIFICATIONS)
        _texte(self.source, "licence.source", maximum=300)
        _texte(self.note, "licence.note", requis=False)

    @property
    def copyleft(self) -> bool:
        """Licence GPL/AGPL (code ou poids) : intégrable seulement en service séparé (DECISIONS r1 §7)."""
        return any(_COPYLEFT.search(x or "") and "LGPL" not in (x or "").upper() for x in (self.code, self.poids))

    def vers_json(self) -> dict[str, Any]:
        donnees = dataclasses.asdict(self)
        donnees["territoires_exclus"] = list(self.territoires_exclus)
        return donnees

    @classmethod
    def depuis_json(cls, donnees: Mapping[str, Any]) -> Licence:
        if not isinstance(donnees, Mapping) or set(donnees) - {f.name for f in dataclasses.fields(cls)}:
            raise DeclarationInvalide("licence : champs absents ou inconnus")
        valeurs = dict(donnees)
        valeurs["territoires_exclus"] = tuple(valeurs.get("territoires_exclus") or ())
        try:
            return cls(**valeurs)
        except TypeError as exc:
            raise DeclarationInvalide("licence : champs absents ou inconnus") from exc


@dataclasses.dataclass(frozen=True)
class Cout:
    """Coût unitaire DÉCLARÉ (source : recherche ou contrat), jamais estimé par un modèle."""

    unite: str
    montant: str
    devise: str
    source: str

    def __post_init__(self) -> None:
        if not isinstance(self.unite, str) or not _UNITE.fullmatch(self.unite):
            raise DeclarationInvalide("cout.unite invalide (ex. page, appel, image, million_caracteres)")
        try:
            montant = Decimal(self.montant) if isinstance(self.montant, str) else None
        except InvalidOperation:
            montant = None
        if montant is None or not montant.is_finite() or montant < 0 or len(self.montant) > 24:
            raise DeclarationInvalide("cout.montant doit être une chaîne décimale positive ou nulle")
        _choix(self.devise, "cout.devise", DEVISES)
        _texte(self.source, "cout.source", maximum=200)


@dataclasses.dataclass(frozen=True)
class Quotas:
    """Quotas déclarés ; `None` = non déclaré (affiché tel quel, jamais remplacé par une valeur supposée)."""

    requetes_par_minute: int | None = None
    unites_par_mois: int | None = None

    def __post_init__(self) -> None:
        for nom in ("requetes_par_minute", "unites_par_mois"):
            valeur = getattr(self, nom)
            if valeur is not None and (type(valeur) is not int or not 0 < valeur <= 10**12):
                raise DeclarationInvalide(f"quotas.{nom} doit être un entier positif")


@dataclasses.dataclass(frozen=True)
class Fournisseur:
    identifiant: str
    capacite: str
    mode: str
    modele: str
    licence: Licence
    point_acces: str | None = None
    reference_secret: str | None = None
    quotas: Quotas = Quotas()
    cout_unitaire: Cout | None = None
    statut_catalogue: str = "declare"
    qualification: str = "a_mesurer"
    raison_ecart: str | None = None
    residence_donnees: str = "local"
    efvp_ref: str | None = None
    contrat_ref: str | None = None
    mention_confirmee: bool = False
    licence_lue_par: str | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.identifiant, str) or not _IDENTIFIANT.fullmatch(self.identifiant):
            raise DeclarationInvalide("identifiant invalide (minuscules, chiffres, . _ -, 3 à 80 caractères)")
        _choix(self.capacite, "capacite", CAPACITES)
        _choix(self.mode, "mode", MODES)
        _texte(self.modele, "modele", maximum=200)
        if not isinstance(self.licence, Licence):
            raise DeclarationInvalide("licence requise")
        if self.point_acces is not None:
            if not isinstance(self.point_acces, str) or not _URL.fullmatch(self.point_acces):
                raise DeclarationInvalide(
                    "point_acces invalide : https://…, http://127.0.0.1…, module:…, binaire:… ou appareil:…"
                )
            if self.mode == "api" and not self.point_acces.startswith("https://"):
                raise DeclarationInvalide("point_acces d'un fournisseur API : https:// obligatoire")
            if self.point_acces.startswith("http://") and not _boucle_locale(self.point_acces):
                raise DeclarationInvalide("http:// en clair seulement vers 127.0.0.1, ::1 ou localhost")
            if self.point_acces.startswith("http") and "@" in self.point_acces.split("/", 3)[2]:
                raise DeclarationInvalide("point_acces : identifiants dans l'URL interdits (utiliser le coffre)")
        if self.reference_secret is not None and (
            not isinstance(self.reference_secret, str) or not self.reference_secret.startswith(PREFIXE_SECRET)
            or not _NOM_SECRET.fullmatch(self.reference_secret[len(PREFIXE_SECRET):])
        ):
            raise DeclarationInvalide("reference_secret : forme coffre:<nom> attendue (jamais une valeur)")
        if not isinstance(self.quotas, Quotas):
            raise DeclarationInvalide("quotas invalides")
        if self.cout_unitaire is not None and not isinstance(self.cout_unitaire, Cout):
            raise DeclarationInvalide("cout_unitaire invalide")
        _choix(self.statut_catalogue, "statut_catalogue", STATUTS_CATALOGUE)
        _choix(self.qualification, "qualification", QUALIFICATIONS)
        if self.statut_catalogue == "ecarte" and not self.raison_ecart:
            raise DeclarationInvalide("un fournisseur écarté cite sa raison")
        _texte(self.raison_ecart, "raison_ecart", requis=False)
        _choix(self.residence_donnees, "residence_donnees", RESIDENCES)
        for champ in ("efvp_ref", "contrat_ref", "licence_lue_par", "note"):
            _texte(getattr(self, champ), champ, requis=False, maximum=200 if champ != "note" else _TEXTE_MAX)
        if type(self.mention_confirmee) is not bool:
            raise DeclarationInvalide("mention_confirmee doit être booléen")

    @property
    def nom_secret(self) -> str | None:
        return self.reference_secret[len(PREFIXE_SECRET):] if self.reference_secret else None

    def vers_json(self) -> dict[str, Any]:
        donnees = dataclasses.asdict(self)
        donnees["licence"] = self.licence.vers_json()
        return donnees

    def canonique(self) -> str:
        return json.dumps(self.vers_json(), ensure_ascii=False, sort_keys=True, separators=(",", ":"))

    @classmethod
    def depuis_json(cls, donnees: Mapping[str, Any]) -> Fournisseur:
        if not isinstance(donnees, Mapping) or set(donnees) - {f.name for f in dataclasses.fields(cls)}:
            raise DeclarationInvalide("fournisseur : champs absents ou inconnus")
        valeurs = dict(donnees)
        valeurs["licence"] = Licence.depuis_json(valeurs.get("licence") or {})
        quotas = valeurs.get("quotas") or {}
        cout = valeurs.get("cout_unitaire")
        try:
            valeurs["quotas"] = Quotas(**quotas) if isinstance(quotas, Mapping) else quotas
            valeurs["cout_unitaire"] = Cout(**cout) if isinstance(cout, Mapping) else cout
            return cls(**valeurs)
        except TypeError as exc:
            raise DeclarationInvalide("fournisseur : champs absents ou inconnus") from exc


def _boucle_locale(url: str) -> bool:
    hote = url.split("/", 3)[2].rsplit("@", 1)[-1]
    hote = hote[1:].split("]", 1)[0] if hote.startswith("[") else hote.split(":", 1)[0]
    return hote in {"127.0.0.1", "::1", "localhost"}
