"""Vocabulaire, validation et empreinte du manifeste d'une entrée voix/visage.

Une entrée relie un identifiant LOGIQUE d'avatar (`voix.lea.defaut`) à un runtime du registre de fournisseurs
(`opsys.fournisseurs`) : la licence du code, la licence des poids, les seuils de revenu, les territoires et le droit de
service à des tiers vivent dans la définition du FOURNISSEUR et sont jugés par son moteur de politique
(`fournisseurs.politique.evaluer`) ; ils ne sont pas recopiés ici. Le MANIFESTE figé de l'entrée n'en garde que ce qui
identifie le moteur (modèle, point d'accès, licence) : son empreinte SHA-256 lie le consentement de départ et la
qualification exécutée au moteur réellement configuré.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from .. import avatars
from ..fournisseurs.modele import USAGES_COMMERCIAUX, Fournisseur
from .codes import AvatarRefus

GENRE_VOIX = "voix"
GENRE_VISAGE = "visage"
GENRES = (GENRE_VOIX, GENRE_VISAGE)
# Capacité du registre de fournisseurs qui sert chaque genre (`fournisseurs.modele.CAPACITES`).
CAPACITE_DU_GENRE = {GENRE_VOIX: "tts", GENRE_VISAGE: "avatar"}
CAPACITE_ECOUTE = "stt"

ETAT_PREVU = "prevu"
ETAT_CONFIGURE = "configure"
ETAT_QUALIFIE = "qualifie"
ETATS_ENTREE = (ETAT_PREVU, ETAT_CONFIGURE, ETAT_QUALIFIE)

ORIGINE_GENERIQUE = "generique"
ORIGINE_CLONEE = "clonee"
ORIGINE_RESSEMBLANCE = "ressemblance"
ORIGINES = {GENRE_VOIX: (ORIGINE_GENERIQUE, ORIGINE_CLONEE), GENRE_VISAGE: (ORIGINE_GENERIQUE, ORIGINE_RESSEMBLANCE)}

# Langue exigée d'une voix pour le marché du produit (Québec) ; les autres langues sont inscriptibles, jamais
# déclarées disponibles pour un client québécois.
LANGUE_EXIGEE = "fr-CA"
LANGUES = ("fr-CA", "fr-FR", "en-CA", "en-US")

PORTEE_CLONAGE = "clonage"
PORTEE_SYNTHESE = "synthese"
PORTEE_RENDU_VISAGE = "rendu_visage"
PORTEES = (PORTEE_CLONAGE, PORTEE_SYNTHESE, PORTEE_RENDU_VISAGE)
# Ce qu'un consentement doit couvrir pour que l'origine soit permise.
PORTEES_REQUISES = {
    (GENRE_VOIX, ORIGINE_CLONEE): frozenset({PORTEE_CLONAGE, PORTEE_SYNTHESE}),
    (GENRE_VISAGE, ORIGINE_RESSEMBLANCE): frozenset({PORTEE_RENDU_VISAGE}),
}
FORME_ECRITE = "ecrit"

# Une banque de caractéristiques biométriques se déclare à la CAI au plus tard 60 jours avant sa mise en service
# (R1 §4, source secondaire [S] ; à valider par une avocate ou un avocat avant production).
DELAI_BIOMETRIE_JOURS = 60

SCHEMA_MANIFESTE = "opsys.avatars.entree/v1"

_LOCUTEUR = re.compile(r"^[a-z0-9][a-z0-9._-]{2,63}$")
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_ACCENT = re.compile(r"^[a-zé][a-zé _-]{1,39}$")
_CONSENTEMENT_ID = re.compile(r"^[0-9a-f]{32}$")


def refus_declaration(detail: str) -> AvatarRefus:
    return AvatarRefus("REJ-AVATAR-DECLARATION-INVALIDE", detail, 422)


def genre_de(identifiant: Any) -> str:
    """`voix` ou `visage` d'après le préfixe ; la forme complète est celle des manifestes (`avatars`)."""
    if not isinstance(identifiant, str) or "." not in identifiant:
        raise AvatarRefus("REJ-AVATAR-IDENTIFIANT-INVALIDE",
                          "identifiant logique attendu : voix.<nom>.<variante> ou visage.<nom>.<variante>", 422)
    genre = identifiant.split(".", 1)[0]
    if genre not in GENRES:
        raise AvatarRefus("REJ-AVATAR-IDENTIFIANT-INVALIDE", "l'identifiant commence par « voix. » ou « visage. »", 422)
    try:
        avatars.valider_identifiant(genre, identifiant, "entrée")
    except avatars.AvatarInvalide as exc:
        raise AvatarRefus("REJ-AVATAR-IDENTIFIANT-INVALIDE", str(exc), 422) from None
    return genre


def valider_langue(valeur: Any) -> str:
    if valeur not in LANGUES:
        raise refus_declaration(f"langue parmi {', '.join(LANGUES)}")
    return valeur


def valider_accent(valeur: Any) -> str | None:
    if valeur is None:
        return None
    if not isinstance(valeur, str) or not _ACCENT.fullmatch(valeur):
        raise refus_declaration("accent : texte court en minuscules (ex. quebecois), ou absent")
    return valeur


def valider_origine(genre: str, valeur: Any) -> str:
    if valeur not in ORIGINES[genre]:
        raise refus_declaration(f"origine d'un(e) {genre} parmi {', '.join(ORIGINES[genre])}")
    return valeur


def valider_usage_actif(genre: str, valeur: Any) -> str | None:
    """Licence d'usage commercial de l'ACTIF visuel (modèle 3D, gabarit) : propre au visage."""
    if genre == GENRE_VOIX:
        if valeur is not None:
            raise refus_declaration("actif_usage_commercial ne s'applique qu'à un visage")
        return None
    if valeur not in USAGES_COMMERCIAUX:
        raise refus_declaration(f"actif_usage_commercial d'un visage parmi {', '.join(USAGES_COMMERCIAUX)}")
    return valeur


def valider_date(valeur: Any, champ: str) -> str:
    if not isinstance(valeur, str) or len(valeur) != 10:
        raise refus_declaration(f"{champ} : date AAAA-MM-JJ attendue")
    try:
        dt.date.fromisoformat(valeur)
    except ValueError:
        raise refus_declaration(f"{champ} : date AAAA-MM-JJ attendue") from None
    return valeur


def valider_locuteur(valeur: Any) -> str:
    if not isinstance(valeur, str) or not _LOCUTEUR.fullmatch(valeur):
        raise refus_declaration(
            "locuteur_ref : référence pseudonyme (minuscules, chiffres, . _ -, 3 à 64 caractères), jamais un nom")
    return valeur


def valider_document(reference: Any, empreinte: Any) -> tuple[str, str]:
    if not isinstance(reference, str) or not reference.strip() or len(reference) > 200 or not reference.isprintable():
        raise refus_declaration("document_ref : référence du contrat signé (texte imprimable, 200 caractères au plus)")
    if not isinstance(empreinte, str) or not _SHA256.fullmatch(empreinte):
        raise refus_declaration("document_sha256 : empreinte SHA-256 hexadécimale (64 caractères) du document signé")
    return reference.strip(), empreinte


def valider_portee(valeur: Any) -> tuple[str, ...]:
    if isinstance(valeur, (str, bytes)) or not isinstance(valeur, (list, tuple, set, frozenset)) or not valeur:
        raise refus_declaration(f"portee : liste non vide parmi {', '.join(PORTEES)}")
    if any(p not in PORTEES for p in valeur):
        raise refus_declaration(f"portee : valeurs permises {', '.join(PORTEES)}")
    return tuple(sorted(set(valeur)))


def valider_consentement_id(valeur: Any) -> str:
    if not isinstance(valeur, str) or not _CONSENTEMENT_ID.fullmatch(valeur):
        raise AvatarRefus("REJ-AVATAR-CONSENTEMENT-INCONNU", "identifiant de consentement invalide", 404)
    return valeur


def _canonique(donnees: Mapping[str, Any]) -> str:
    return json.dumps(donnees, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def description_runtime(fournisseur: Fournisseur) -> dict[str, Any]:
    """Ce qui IDENTIFIE le moteur : modèle, mode, point d'accès, licence (code, poids, seuils, territoires, service à
    des tiers) et références contractuelles. Les indicateurs revus en direct (profil du client, mention affichée,
    EFVP, activation) n'y sont pas : le moteur de politique les juge à chaque lecture. Aucun secret, aucune quota."""
    return {
        "identifiant": fournisseur.identifiant, "capacite": fournisseur.capacite, "mode": fournisseur.mode,
        "modele": fournisseur.modele, "point_acces": fournisseur.point_acces,
        "residence_donnees": fournisseur.residence_donnees, "contrat_ref": fournisseur.contrat_ref,
        "licence": fournisseur.licence.vers_json(),
    }


def empreinte_runtime(fournisseur: Fournisseur) -> str:
    return hashlib.sha256(_canonique(description_runtime(fournisseur)).encode("utf-8")).hexdigest()


def manifeste(*, identifiant: str, genre: str, langue: str, accent: str | None, origine: str,
              actif_usage_commercial: str | None, empreinte_vocale_tiers: bool,
              fournisseur: Fournisseur | None) -> dict[str, Any]:
    return {
        "schema": SCHEMA_MANIFESTE, "identifiant": identifiant, "genre": genre, "langue": langue, "accent": accent,
        "origine": origine, "actif_usage_commercial": actif_usage_commercial,
        "empreinte_vocale_tiers": bool(empreinte_vocale_tiers),
        "runtime": None if fournisseur is None else description_runtime(fournisseur),
        "empreinte_runtime": None if fournisseur is None else empreinte_runtime(fournisseur),
    }


def empreinte_manifeste(contenu: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonique(contenu).encode("utf-8")).hexdigest()
