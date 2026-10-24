"""Rétention et destruction des fixes GPS (M4-T4.2, POLITIQUE-geolocalisation.md §5).

Module pur (aucun import ``opsys``, aucune horloge, aucun aléa système — même garde que le reste de
M4) : il calcule une échéance et chiffre/déchiffre une position à partir d'une CLÉ que l'appelant
fournit, exactement comme ``cedule.tokeniser_ville`` reçoit son ``sel`` de l'appelant plutôt que
d'en fabriquer un. La génération, le stockage durable et la DESTRUCTION réelle de cette clé
(``opsys.cles_chiffrement``, socle) sont un problème d'infrastructure impure, hors de ce module.

Pourquoi le chiffrement, et pas un autre mécanisme (étude demandée par PLAN T4.2) :
    Le registre M4 (``registre.py``) est un journal hash-chaîné APPEND-ONLY : chaque ``ligne_id``
    incorpore le contenu du maillon ET celui du précédent (``encodage.empreinte``). Modifier ou
    supprimer un maillon déjà écrit — même un seul octet — casse ce chaînage, détecté par
    ``valider_chaine()`` (voir ``test_registre_durable.py::test_alteration_directe_en_base_
    detectee_par_valider_chaine``). Le support durable (``opsys.stockage.MaillonsDurables``)
    ne propose d'ailleurs même pas d'UPDATE ni de DELETE sur un maillon : seul ``append`` existe.
    Trois mécanismes ont été étudiés :
      1. Garder le point HORS chaîne (dans une table à part, sans hash-chaînage) : possible, mais
         alors le maillon chaîné ne prouve plus rien de ce qui a réellement été vérifié au moment
         du pointage (la cohérence GPS, §11 de ``pointage.py``) — l'audit perd sa valeur probante.
      2. Ne porter qu'une EMPREINTE (hash à sens unique) sur le maillon : intègre et vérifiable
         a posteriori (« ce fix correspond bien à celui déclaré »), mais AUCUNE lecture n'est plus
         jamais possible, même pendant la période de rétention valide — incompatible avec le droit
         d'accès de l'employé à ses propres fixes (§7).
      3. CHIFFRER la position avant de l'écrire dans le maillon, avec une clé conservée EN DEHORS
         du registre append-only, dans un support qui autorise une vraie suppression. Choisi ICI :
         le maillon chaîné ne change JAMAIS après écriture (intégrité et empreinte intactes pour
         toujours) ; la position reste lisible tant que la clé existe (droit d'accès, §7) ; une
         purge de rétention (§5) retire la clé du coffre logique sans toucher à la chaîne.
         Le nettoyage des fichiers SQLite courants est ensuite suivi par purge_id après commit ;
         en_attente ne constitue pas une attestation de nettoyage. Sauvegardes, snapshots et
         supports externes exigent leur propre gestion des clés et restent distincts.
    HMAC-SHA256 en mode compteur (bibliothèque standard ``hmac``/``hashlib`` uniquement, même
    parti pris que ``cedule.py`` §4 de l'architecture M4 : « aucune cryptographie exotique ») :
    un flux de clé est dérivé par blocs HMAC(clé, contexte‖nonce‖compteur), puis XORé avec le
    texte clair. Le nonce est DÉTERMINISTE (dérivé de l'identité du pointage, jamais d'un aléa
    ambiant) : CA-M4-07 garantit déjà qu'un même (intervention_id, action, horodatage) n'est
    jamais écrit deux fois pour la même intervention, ce qui suffit à ne jamais réutiliser un
    couple (clé, nonce) pour deux positions distinctes d'un même technicien.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime

from . import encodage
from . import horodatage as horodatage_mod
from . import verdicts as verdicts_mod

TYPE_ACCES = "acces_position_gps"
TYPE_PURGE = "purge_retention_gps"

# Citation littérale (jamais reformulée) : la durée n'est jamais inventée ici, elle vient du
# document cité. Le marqueur [À VÉRIFIER] fait partie de la citation : la politique elle-même
# signale une confirmation juridique en attente (voir rapport de livraison, ambiguïtés).
CITATION_DUREE_RETENTION = (
    "POLITIQUE-geolocalisation.md §5 : « 12 mois après la fin du contrat de travail ou du dernier "
    "punch, selon la plus longue des deux périodes. [À VÉRIFIER — juriste : durée applicable en "
    "droit du travail québécois.] »"
)

_CONTEXTE_FLUX = b"m4-field-ops/geoloc/v1:"

__all__ = [
    "TYPE_ACCES",
    "TYPE_PURGE",
    "CITATION_DUREE_RETENTION",
    "nonce_position",
    "chiffrer_position",
    "dechiffrer_position",
    "ajouter_12_mois",
    "dernier_pointage_technicien",
    "evaluer_eligibilite_purge",
    "construire_maillon_acces",
    "construire_maillon_purge",
]


# --------------------------------------------------------------------------------------- chiffrement
def _flux_cle(cle: bytes, nonce: bytes, longueur: int) -> bytes:
    flux = b""
    compteur = 0
    while len(flux) < longueur:
        flux += hmac.new(cle, _CONTEXTE_FLUX + nonce + compteur.to_bytes(8, "big"), hashlib.sha256).digest()
        compteur += 1
    return flux[:longueur]


def _xor(a: bytes, b: bytes) -> bytes:
    return bytes(x ^ y for x, y in zip(a, b, strict=True))


def nonce_position(intervention_id: str, technicien_id: str, action: str, horodatage_arg: str) -> bytes:
    """Nonce déterministe (16 octets), jamais un aléa ambiant : ce module reste pur. L'unicité par
    (clé technicien) est portée par CA-M4-07 (``pointage.py``), qui refuse déjà un horodatage
    antérieur ou égal au dernier pointage écrit pour une même intervention."""
    return bytes.fromhex(
        encodage.empreinte("nonce-gps-v1", intervention_id, technicien_id, action, horodatage_arg)
    )[:16]


def chiffrer_position(cle: bytes, nonce: bytes, latitude: float, longitude: float) -> str:
    """Chiffre {latitude, longitude} en une chaîne hexadécimale. ``repr()`` (pas ``str()``) pour
    que le texte clair se reconstruise EXACTEMENT (``float(repr(x)) == x`` toujours, Python >= 3.1)."""
    clair = f"{latitude!r}|{longitude!r}".encode()
    return _xor(clair, _flux_cle(cle, nonce, len(clair))).hex()


def dechiffrer_position(cle: bytes, nonce: bytes, chiffre_hex: str) -> tuple[float, float]:
    """Inverse de ``chiffrer_position``. Lève ``ValueError`` si ``cle``/``nonce`` ne correspondent
    pas (texte déchiffré non conforme au format ``latitude|longitude``) — jamais une paire de
    coordonnées silencieusement fausse."""
    chiffre = bytes.fromhex(chiffre_hex)
    clair = _xor(chiffre, _flux_cle(cle, nonce, len(chiffre)))
    try:
        lat_s, lon_s = clair.decode("utf-8").split("|")
        return float(lat_s), float(lon_s)
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("déchiffrement invalide : clé ou nonce incorrects") from exc


# --------------------------------------------------------------------------------------- échéance
def ajouter_12_mois(dt: datetime) -> datetime:
    """+12 mois = +1 an civil, jour pour jour. Seule exception : le 29 février n'a pas
    d'équivalent l'année suivante quand celle-ci n'est pas bissextile -> 28 février (même
    convention que les calendriers de rétention usuels, aucune bibliothèque tierce requise)."""
    try:
        return dt.replace(year=dt.year + 1)
    except ValueError:
        return dt.replace(year=dt.year + 1, day=28)


def dernier_pointage_technicien(registre_cible, technicien_id: str) -> str | None:
    """Horodatage du plus récent maillon ``pointage`` de ce technicien, toutes interventions
    confondues (comparaison par valeur temporelle, pas par ordre d'écriture : CA-M4-07 n'ordonne
    que les pointages d'UNE MÊME intervention, jamais entre deux interventions distinctes)."""
    plus_recent = None
    horodatage_le_plus_recent = None
    for maillon in registre_cible.lire():
        if maillon.get("type_entree") != "pointage" or maillon.get("technicien_id") != technicien_id:
            continue
        try:
            dt = datetime.fromisoformat(maillon["horodatage"])
        except (KeyError, TypeError, ValueError):
            continue
        if plus_recent is None or dt > plus_recent:
            plus_recent = dt
            horodatage_le_plus_recent = maillon["horodatage"]
    return horodatage_le_plus_recent


def evaluer_eligibilite_purge(registre_cible, technicien_id, fin_contrat_travail, horodatage_actuel):
    """(accusé, None) si une purge est permise MAINTENANT pour ``technicien_id``, (None, verdict)
    sinon. N'effectue AUCUNE destruction : cette fonction ne fait QUE calculer l'échéance §5 — la
    destruction elle-même (suppression de la clé, écriture du maillon d'audit) appartient à
    l'adaptateur (``outils.py``), jamais à un module pur.

    Fail-closed (AGENTS.md) : ``fin_contrat_travail`` est une donnée RH que M4 ne connaît pas de
    lui-même (son registre ne porte que des interventions terrain, jamais un dossier employé) —
    son absence produit REJ-RETENTION-DONNEE-MANQUANTE, jamais une purge fondée sur la seule
    hypothèse qu'un employé sans date de fin est « encore là » ou « parti depuis longtemps ».
    """
    if not isinstance(technicien_id, str) or technicien_id == "":
        return None, verdicts_mod.construire_verdict("REJ-CONTRAT-INVALIDE", detail="technicien_id manquant")
    try:
        horodatage_mod.valider_horodatage(horodatage_actuel)
    except ValueError:
        return None, verdicts_mod.construire_verdict(
            "REJ-HORODATAGE-INVALIDE", detail=f"horodatage_actuel invalide : {horodatage_actuel!r}")
    if not isinstance(fin_contrat_travail, str) or fin_contrat_travail == "":
        return None, verdicts_mod.construire_verdict(
            "REJ-RETENTION-DONNEE-MANQUANTE",
            detail=(
                "fin_contrat_travail inconnue : M4 ne peut pas calculer l'échéance sans cette date "
                f"RH, jamais devinée. {CITATION_DUREE_RETENTION}"
            ),
        )
    try:
        horodatage_mod.valider_horodatage(fin_contrat_travail)
    except ValueError:
        return None, verdicts_mod.construire_verdict(
            "REJ-HORODATAGE-INVALIDE", detail=f"fin_contrat_travail invalide : {fin_contrat_travail!r}")

    dt_reference = datetime.fromisoformat(fin_contrat_travail)
    dernier_punch = dernier_pointage_technicien(registre_cible, technicien_id)
    if dernier_punch is not None:
        dt_dernier_punch = datetime.fromisoformat(dernier_punch)
        if dt_dernier_punch > dt_reference:
            dt_reference = dt_dernier_punch
    dt_echeance = ajouter_12_mois(dt_reference)
    dt_maintenant = datetime.fromisoformat(horodatage_actuel)

    if dt_maintenant < dt_echeance:
        return None, verdicts_mod.construire_verdict(
            "REJ-RETENTION-NON-ECHUE",
            detail=(
                f"échéance {dt_echeance.isoformat()}, maintenant {horodatage_actuel}. "
                f"{CITATION_DUREE_RETENTION}"
            ),
        )
    return {
        "technicien_id": technicien_id,
        "fin_contrat_travail": fin_contrat_travail,
        "dernier_punch": dernier_punch,
        "reference_retenue": dt_reference.isoformat(),
        "date_echeance": dt_echeance.isoformat(),
        "horodatage_actuel": horodatage_actuel,
    }, None


# --------------------------------------------------------------------------------------- traçabilité
def construire_maillon_acces(technicien_id, ligne_id_position, accede_par, horodatage_arg, resultat):
    """Maillon d'accès (§6) : QUI a consulté QUEL fix, QUAND, avec QUEL résultat — jamais la
    position elle-même (elle vit chiffrée sur le maillon de pointage, jamais dupliquée ici)."""
    return {
        "type_entree": TYPE_ACCES,
        "technicien_id": technicien_id,
        "ligne_id_position": ligne_id_position,
        "accede_par": accede_par,
        "horodatage": horodatage_arg,
        "resultat": resultat,
    }


def construire_maillon_purge(
    technicien_id, fin_contrat_travail, horodatage_arg, motif, cle_detruite,
    *, purge_id: str | None = None, etat_fichiers: str | None = None,
):
    """Audit historique du retrait logique de la clé et, si fourni, du travail d'effacement.

    ``cle_detruite`` décrit le retrait du coffre logique, jamais les fichiers physiques. L'état
    enregistré est INITIAL ; le suivi courant se lit par ``purge_id`` sans réécrire ce maillon.
    La position elle-même n'apparaît JAMAIS ici, y compris chiffrée.
    """
    maillon = {
        "type_entree": TYPE_PURGE,
        "technicien_id": technicien_id,
        "fin_contrat_travail": fin_contrat_travail,
        "horodatage": horodatage_arg,
        "motif": motif,
        "cle_detruite": cle_detruite,
    }
    if purge_id is not None:
        maillon["purge_id"] = purge_id
    if etat_fichiers is not None:
        maillon["etat_fichiers"] = etat_fichiers
    return maillon
