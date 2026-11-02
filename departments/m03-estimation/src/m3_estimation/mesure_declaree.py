"""MESURE DÉCLARÉE : la quantité d'une estimation est l'enregistrement d'une personne, plus un nombre libre (M3-C2).

Avant ce module, ``quantite`` était un argument de ``m3_estimer_projet`` et la garde photos/échelle jugeait des
métadonnées déclarées des photos, pas la mesure qui produit la quantité : un drapeau ``dimensions_connues: true``
suffisait à débloquer un prix. Une mesure est maintenant un enregistrement chaîné, append-only :

- ``valeur`` et ``unite`` (l'unité doit être celle de l'ouvrage du barème), ``borne_basse`` et ``borne_haute`` ;
- l'AUTEUR (une personne : propriétaire, administrateur ou vendeur, jamais un modèle), la MÉTHODE (relevé sur place,
  plan,
  photo à l'échelle mesurée à la main, estimation grossière), la CONFIANCE déclarée, la date de la mesure, les PIÈCES
  (références de photos ou de plans) et le lead et le service qu'elle concerne ;
- une révision ne remplace rien : elle ajoute un maillon, l'ancienne révision reste lisible (rejeu d'une estimation).

``evaluer`` juge si la mesure suffit à un prix, avec des seuils DÉCLARÉS dans le barème (jamais ici) : largeur relative
``(borne_haute - borne_basse) / valeur``. Au-delà du seuil « aucun prix », la mesure est insuffisante (refus qui dit
quoi
mesurer de plus). Entre le seuil de revue et ce seuil, l'estimation donne une plage honnête et EXIGE la revue d'une
personne. Une confiance déclarée « faible » exige aussi la revue. Seuil absent alors que les bornes sont larges : on ne
devine pas, on le dit. Les comparaisons se font en ``Decimal`` exact (multiplication, jamais de division arrondie).

Aucune vision n'est requise : une photo n'entre ici que comme PIÈCE d'une mesure faite à la main. Un candidat de vision
n'est jamais une mesure (``vision_gouvernance.py``) ; en faire une mesure déclarée exige qu'une personne la déclare.

Module pur (ADR-0009) : aucun import ``opsys``, aucune horloge, aucun accès réseau.
"""

from __future__ import annotations

import copy
import re
import unicodedata
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from . import verdicts
from .devis_durable import _ajouter
from .registre import _encoder_canonique

__all__ = [
    "MAX_PIECES",
    "REGISTRE",
    "ROLES_AUTEUR",
    "declarer",
    "evaluer",
    "lire",
    "methodes",
    "resoudre",
    "resoudre_sans_lead",
]

REGISTRE = "mesures_declarees"
TYPE_ENTREE = "mesure_declaree"
MAX_MAILLONS = 5000
MAX_PIECES = 20

# Qui peut déclarer une mesure : une PERSONNE. Le vendeur n'est admis que pour les leads dont il est propriétaire
# (l'adaptateur le vérifie à la source M2) ; l'agent, le client et le rôle d'employé n'y sont pas.
ROLES_AUTEUR = frozenset({"nathan_owner", "admin", "seller"})

_METHODES = ("releve_sur_place", "plan", "photo_echelle_mesuree", "estimation_grossiere")
_CONFIANCES = ("faible", "moyenne", "elevee")
_LIBELLES_METHODE = {
    "releve_sur_place": "relevé sur place",
    "plan": "plan",
    "photo_echelle_mesuree": "photo à l'échelle mesurée à la main",
    "estimation_grossiere": "estimation grossière",
}

_IDENTIFIANT = re.compile(r"[A-Za-z0-9_.:@-]{1,200}")
_CODE = re.compile(r"[A-Za-z0-9_.-]{1,64}")
_DECIMAL = re.compile(r"[0-9]{1,9}(?:\.[0-9]{1,6})?")
_DATE = re.compile(
    r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]{1,6})?(?:Z|[+-][0-9]{2}:[0-9]{2})"
)
_SOURCE_ID = re.compile(r"[0-9a-f]{64}")
_CLES_CONTENU = (
    "mesure_id", "lead_id", "service", "grandeur", "valeur", "unite", "borne_basse", "borne_haute", "methode",
    "confiance", "mesure_le", "pieces",
)
_CLES_MAILLON = frozenset(
    {"type_entree", "rang", "precedent", "revision", "auteur", "horodatage", "source_id", *_CLES_CONTENU}
)
_QUATRE_DECIMALES = Decimal("0.0001")


class _Refus(Exception):
    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(f"{code} : {detail}")

    def verdict(self) -> dict:
        return verdicts.construire_verdict(self.code, detail=self.detail)


def _invalide(detail: str) -> _Refus:
    return _Refus("REJ-MESURE-INVALIDE", detail)


def _texte(valeur: Any, maximum: int) -> bool:
    return (
        type(valeur) is str
        and 0 < len(valeur) <= maximum
        and valeur == valeur.strip()
        and not any(unicodedata.category(c) in {"Cc", "Cf", "Cs"} for c in valeur)
    )


def _decimal(valeur: Any, champ: str) -> Decimal:
    if type(valeur) is not str or _DECIMAL.fullmatch(valeur) is None:
        raise _invalide(f"{champ} : un texte décimal strictement positif est attendu (ex. \"120.5\"), jamais un nombre")
    lu = Decimal(valeur)
    if lu <= 0:
        raise _invalide(f"{champ} : une valeur strictement positive est attendue")
    return lu


def _instant(valeur: Any, champ: str) -> datetime:
    if type(valeur) is not str or _DATE.fullmatch(valeur) is None:
        raise _invalide(f"{champ} : un horodatage ISO 8601 avec fuseau est attendu")
    try:
        lu = datetime.fromisoformat(valeur)
    except ValueError:
        raise _invalide(f"{champ} : horodatage illisible") from None
    if lu.utcoffset() is None:
        raise _invalide(f"{champ} : le fuseau horaire est obligatoire")
    return lu


def methodes() -> list[str]:
    """Les méthodes de mesure admises (ensemble fermé : une méthode inconnue est refusée, jamais devinée)."""
    return list(_METHODES)


def _valider_auteur(auteur: Any) -> None:
    if (
        type(auteur) is not dict
        or set(auteur) != {"personne", "role"}
        or type(auteur["personne"]) is not str
        or _IDENTIFIANT.fullmatch(auteur["personne"]) is None
        or auteur["role"] not in ROLES_AUTEUR
    ):
        raise _Refus(
            "REJ-MESURE-IDENTITE",
            "une mesure est déclarée par une personne (propriétaire, administrateur ou vendeur du lead), jamais par un "
            "agent : {personne, role} attendu avec role dans " + str(sorted(ROLES_AUTEUR)),
        )


def _valider_contenu(contenu: dict[str, Any]) -> tuple[Decimal, Decimal, Decimal, datetime]:
    for champ in ("mesure_id", "lead_id"):
        if type(contenu[champ]) is not str or _IDENTIFIANT.fullmatch(contenu[champ]) is None:
            raise _invalide(f"{champ} : un identifiant (lettres, chiffres, _ . : @ -) est attendu")
    if type(contenu["service"]) is not str or _CODE.fullmatch(contenu["service"]) is None:
        raise _invalide("service : un code de service est attendu")
    if not _texte(contenu["grandeur"], 80) or not _texte(contenu["unite"], 24):
        raise _invalide(
            "grandeur (ex. « longueur de bordure ») et unite (ex. « pi.lin ») : des textes non vides sont attendus"
        )
    valeur = _decimal(contenu["valeur"], "valeur")
    basse = _decimal(contenu["borne_basse"], "borne_basse")
    haute = _decimal(contenu["borne_haute"], "borne_haute")
    if not basse <= valeur <= haute:
        raise _invalide("les bornes doivent encadrer la valeur : borne_basse <= valeur <= borne_haute")
    if contenu["methode"] not in _METHODES:
        raise _invalide(f"methode : l'une de {list(_METHODES)} est attendue")
    if contenu["confiance"] not in _CONFIANCES:
        raise _invalide(f"confiance : l'une de {list(_CONFIANCES)} est attendue")
    pieces = contenu["pieces"]
    if (
        type(pieces) is not list or len(pieces) > MAX_PIECES or len(set(pieces)) != len(pieces)
        or any(type(p) is not str or _IDENTIFIANT.fullmatch(p) is None for p in pieces)
    ):
        raise _invalide(f"pieces : au plus {MAX_PIECES} références distinctes (photos, plans) sont attendues")
    return valeur, basse, haute, _instant(contenu["mesure_le"], "mesure_le")


def _sceller(maillon: dict[str, Any]) -> str:
    return _encoder_canonique({cle: valeur for cle, valeur in maillon.items() if cle != "source_id"})


def _charger(journal: Any) -> tuple[list[Any], dict[str, list[dict[str, Any]]], str | None]:
    maillons = list(journal)
    if len(maillons) > MAX_MAILLONS:
        raise _Refus("REJ-MESURE-ALTEREE", f"le registre des mesures dépasse {MAX_MAILLONS} maillons")
    revisions: dict[str, list[dict[str, Any]]] = {}
    precedent: str | None = None
    for rang, maillon in enumerate(maillons):
        try:
            if type(maillon) is not dict or set(maillon) != _CLES_MAILLON or maillon["type_entree"] != TYPE_ENTREE:
                raise _invalide("maillon aux clés inattendues")
            if (
                type(maillon["rang"]) is not int or maillon["rang"] != rang or maillon["precedent"] != precedent
                or type(maillon["source_id"]) is not str or _SOURCE_ID.fullmatch(maillon["source_id"]) is None
                or maillon["source_id"] != _sceller(maillon)
            ):
                raise _invalide("chaînage rompu")
            _valider_auteur(maillon["auteur"])
            horodatage = _instant(maillon["horodatage"], "horodatage")
            *_, mesure_le = _valider_contenu({cle: maillon[cle] for cle in _CLES_CONTENU})
            if mesure_le > horodatage:
                raise _invalide("mesure postérieure à sa déclaration")
            deja = revisions.get(maillon["mesure_id"], [])
            if type(maillon["revision"]) is not int or maillon["revision"] != len(deja) + 1:
                raise _invalide("révision hors séquence")
            if deja and (deja[0]["lead_id"], deja[0]["service"]) != (maillon["lead_id"], maillon["service"]):
                raise _invalide("une révision ne change ni le lead ni le service")
            revisions.setdefault(maillon["mesure_id"], []).append(maillon)
        except (_Refus, KeyError, TypeError, ValueError, InvalidOperation, RecursionError):
            raise _Refus(
                "REJ-MESURE-ALTEREE",
                f"le registre des mesures est altéré ou incohérent au maillon {rang} : ne pas s'en servir "
                "avant vérification",
            ) from None
        precedent = maillon["source_id"]
    return maillons, revisions, precedent


def _public(maillon: dict[str, Any]) -> dict[str, Any]:
    vue = {cle: copy.deepcopy(maillon[cle]) for cle in (*_CLES_CONTENU, "revision", "auteur", "horodatage")}
    vue["empreinte"] = maillon["source_id"]
    return vue


def declarer(
    journal: Any, *, mesure_id: Any, revision_attendue: Any, lead_id: Any, service: Any, grandeur: Any, valeur: Any,
    unite: Any, borne_basse: Any, borne_haute: Any, methode: Any, confiance: Any, mesure_le: Any, pieces: Any,
    auteur: Any, horodatage: Any,
) -> tuple[dict[str, Any] | None, dict | None]:
    """DÉCLARE une mesure (ou une révision) : la seule fonction qui écrit une mesure.

    ``revision_attendue`` : la révision que l'auteur a sous les yeux (0 pour une première mesure) ; une autre écriture
    entre-temps donne ``REJ-MESURE-REVISION-PERIMEE``, le même appel rejoué donne la révision déjà écrite. ``auteur`` et
    ``horodatage`` viennent du serveur. Rend ``({"mesure", "rejoue"}, None)`` ou ``(None, verdict)``."""
    try:
        contenu = {
            "mesure_id": mesure_id, "lead_id": lead_id, "service": service, "grandeur": grandeur, "valeur": valeur,
            "unite": unite, "borne_basse": borne_basse, "borne_haute": borne_haute, "methode": methode,
            "confiance": confiance, "mesure_le": mesure_le, "pieces": pieces,
        }
        *_, instant_mesure = _valider_contenu(contenu)
        _valider_auteur(auteur)
        instant_declaration = _instant(horodatage, "horodatage")
        if instant_mesure > instant_declaration:
            raise _invalide("mesure_le ne peut pas être postérieure au moment où la mesure est déclarée")
        if type(revision_attendue) is not int or isinstance(revision_attendue, bool) or revision_attendue < 0:
            raise _invalide("revision_attendue : un entier, 0 pour une première mesure")
        maillons, revisions, tete = _charger(journal)
        deja = revisions.get(mesure_id, [])
        if revision_attendue != len(deja):
            suivante = deja[revision_attendue] if revision_attendue < len(deja) else None
            if suivante is not None and suivante["auteur"] == auteur \
                    and all(suivante[cle] == contenu[cle] for cle in _CLES_CONTENU):
                return {"mesure": _public(suivante), "rejoue": True}, None
            raise _Refus(
                "REJ-MESURE-REVISION-PERIMEE",
                f"la mesure {mesure_id!r} est à la révision {len(deja)} (la déclaration part de la révision "
                f"{revision_attendue}) : relire la mesure avant de la réviser",
            )
        if deja and (deja[0]["lead_id"], deja[0]["service"]) != (lead_id, service):
            raise _invalide(
                "une révision ne peut changer ni le lead ni le service de la mesure : déclarer une nouvelle mesure"
            )
        if len(maillons) >= MAX_MAILLONS:
            raise _Refus("REJ-MESURE-ALTEREE", f"le registre des mesures est plein ({MAX_MAILLONS} maillons)")
        maillon: dict[str, Any] = {
            "type_entree": TYPE_ENTREE, "rang": len(maillons), "precedent": tete, "revision": len(deja) + 1,
            **contenu, "auteur": copy.deepcopy(auteur), "horodatage": horodatage,
        }
        maillon["source_id"] = _sceller(maillon)
        _ajouter(maillon, journal, len(maillons))
        return {"mesure": _public(maillon), "rejoue": False}, None
    except _Refus as refus:
        return None, refus.verdict()


def lire(journal: Any, mesure_id: Any, revision: Any = 0) -> tuple[dict[str, Any] | None, dict | None]:
    """Une mesure (0 = la dernière révision)."""
    try:
        _, revisions, _ = _charger(journal)
        if type(mesure_id) is not str or mesure_id not in revisions:
            raise _Refus(
                "REJ-MESURE-INTROUVABLE",
                f"aucune mesure {mesure_id!r} n'est déclarée. À faire : une personne déclare la mesure "
                "(m3_declarer_mesure)",
            )
        liste = revisions[mesure_id]
        if type(revision) is not int or isinstance(revision, bool) or not 0 <= revision <= len(liste):
            raise _Refus(
                "REJ-MESURE-INTROUVABLE",
                f"la mesure {mesure_id!r} n'a pas de révision {revision!r} (dernière révision : {len(liste)})",
            )
        return _public(liste[-1] if revision == 0 else liste[revision - 1]), None
    except _Refus as refus:
        return None, refus.verdict()


def resoudre_sans_lead(journal: Any, reference: Any) -> tuple[dict[str, Any] | None, dict | None]:
    """Résout ``mesure_ref`` ``{mesure_id, revision?, empreinte?}`` en une mesure, sans confronter lead ni service.

    Sans ``revision`` la dernière est prise ; l'estimation rappelle toujours la révision exacte."""
    if reference is None:
        return None, verdicts.construire_verdict(
            "REJ-MESURE-REQUISE",
            detail=(
                "aucune mesure déclarée n'est référencée. À faire : une personne déclare la mesure du chantier "
                "(m3_declarer_mesure : valeur, unité, bornes basse et haute, méthode, confiance, pièces), puis "
                "l'estimation la référence par mesure_ref {mesure_id}"
            ),
        )
    if (
        type(reference) is not dict or "mesure_id" not in reference
        or not set(reference) <= {"mesure_id", "revision", "empreinte"}
        or type(reference.get("empreinte", "0" * 64)) is not str
        or _SOURCE_ID.fullmatch(reference.get("empreinte", "0" * 64)) is None
    ):
        return None, verdicts.construire_verdict(
            "REJ-MESURE-REQUISE", detail="mesure_ref doit être {mesure_id} (et éventuellement revision, empreinte)"
        )
    mesure, verdict = lire(journal, reference["mesure_id"], reference.get("revision", 0))
    if verdict is not None:
        return None, verdict
    if "empreinte" in reference and reference["empreinte"] != mesure["empreinte"]:
        return None, verdicts.construire_verdict(
            "REJ-MESURE-ALTEREE",
            detail="l'empreinte donnée ne correspond pas à cette révision de la mesure : relire la mesure "
            "(m3_lire_mesure)",
        )
    return mesure, None


def resoudre(
    journal: Any, reference: Any, lead_id: Any, service: Any,
) -> tuple[dict[str, Any] | None, dict | None]:
    """Résout ``mesure_ref`` en une mesure DE CE LEAD et de ce service.

    Une mesure d'un autre lead ou service est refusée : une mesure ne se prête pas d'un chantier à l'autre."""
    mesure, verdict = resoudre_sans_lead(journal, reference)
    if verdict is not None:
        return None, verdict
    if mesure["lead_id"] != lead_id:
        return None, verdicts.construire_verdict(
            "REJ-MESURE-AUTRE-LEAD",
            detail=(
                f"la mesure {mesure['mesure_id']!r} concerne un autre lead que celui de l'estimation : une mesure ne "
                "se prête pas d'un chantier à l'autre. À faire : déclarer la mesure de CE chantier"
            ),
        )
    if mesure["service"] != service:
        return None, verdicts.construire_verdict(
            "REJ-MESURE-AUTRE-LEAD",
            detail=(
                f"la mesure {mesure['mesure_id']!r} porte sur le service {mesure['service']!r}, l'estimation sur "
                f"{service!r} : déclarer la mesure de ce service"
            ),
        )
    return mesure, None


def _quantite(valeur: Decimal) -> str:
    return format(valeur, "f")


def evaluer(
    mesure: dict[str, Any], *, unite_attendue: str, parametres_mesure: dict[str, Any], maintenant: datetime,
    controler_peremption: bool = True,
) -> tuple[dict[str, Any] | None, dict | None]:
    """Juge si la mesure suffit à un prix, avec les seuils DÉCLARÉS dans le barème (``parametres_mesure``).

    Rend ``(evaluation, None)`` avec ``quantite``, ``quantite_basse``, ``quantite_haute`` (textes décimaux),
    ``largeur_relative`` (texte, 4 décimales, affichage seulement), ``statut`` (``retenu`` ou ``a_revoir``) et
    ``motifs_revue`` (la liste de ce qui exige la revue d'une personne) ; ou ``(None, verdict)`` : unité différente de
    celle du barème, mesure périmée, bornes trop larges pour un prix, seuil à déclarer."""
    valeur = Decimal(mesure["valeur"])
    basse = Decimal(mesure["borne_basse"])
    haute = Decimal(mesure["borne_haute"])
    if mesure["unite"] != unite_attendue:
        return None, verdicts.construire_verdict(
            "REJ-MESURE-UNITE",
            detail=(
                f"la mesure est en {mesure['unite']!r}, l'ouvrage du barème se compte en {unite_attendue!r} : aucune "
                "conversion n'est devinée. À faire : déclarer la mesure dans l'unité du barème (ou réviser le barème)"
            ),
        )
    validite = parametres_mesure.get("validite_jours")
    if (
        controler_peremption and validite is not None
        and _instant(mesure["mesure_le"], "mesure_le") + timedelta(days=validite) < maintenant
    ):
        return None, verdicts.construire_verdict(
            "REJ-MESURE-PERIMEE",
            detail=(
                f"la mesure date du {mesure['mesure_le']} : plus de {validite} jours (durée de validité déclarée "
                "dans le barème). À faire : refaire ou confirmer la mesure (révision)"
            ),
        )
    largeur = haute - basse
    seuil_revue = parametres_mesure.get("largeur_relative_revue")
    seuil_max = parametres_mesure.get("largeur_relative_max_prix")
    motifs: list[str] = []
    if largeur > 0:
        if seuil_max is None:
            return None, verdicts.construire_verdict(
                "REJ-BAREME-INCOMPLET",
                detail=(
                    "la mesure a des bornes larges et le barème ne déclare pas jusqu'où un prix reste permis "
                    "(parametres.mesure.largeur_relative_max_prix) : on ne le devine pas. À faire : le propriétaire "
                    "déclare ce seuil dans une révision du barème"
                ),
            )
        if largeur > Decimal(seuil_max) * valeur:
            return None, verdicts.construire_verdict(
                "REJ-MESURE-INSUFFISANTE",
                detail=(
                    f"bornes de {_quantite(basse)} à {_quantite(haute)} {mesure['unite']} autour de "
                    f"{_quantite(valeur)} : "
                    f"trop larges pour un prix (seuil déclaré : {seuil_max}). Aucun prix n'est donné plutôt qu'une "
                    "précision inventée. À faire : mesurer plus précisément (relevé sur place, plan coté) et déclarer "
                    "une révision de la mesure"
                ),
            )
        if seuil_revue is None:
            motifs.append("seuil de revue des bornes non déclaré (parametres.mesure.largeur_relative_revue)")
        elif largeur > Decimal(seuil_revue) * valeur:
            motifs.append(f"bornes larges : au-delà du seuil de revue déclaré ({seuil_revue})")
    if mesure["confiance"] == "faible":
        motifs.append("confiance déclarée faible")
    return {
        "quantite": _quantite(valeur),
        "quantite_basse": _quantite(basse),
        "quantite_haute": _quantite(haute),
        "unite": mesure["unite"],
        "largeur_relative": _quantite((largeur / valeur).quantize(_QUATRE_DECIMALES, rounding=ROUND_HALF_UP)),
        "statut": "a_revoir" if motifs else "retenu",
        "motifs_revue": motifs,
        "methode": mesure["methode"],
        "methode_libelle": _LIBELLES_METHODE[mesure["methode"]],
    }, None
