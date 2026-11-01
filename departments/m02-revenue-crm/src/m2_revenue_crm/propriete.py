"""Profil de propriété (DEFINITION-PRODUIT §7 M2.3) : ce que M2 sait de la PROPRIÉTÉ d'un client, sourcé, versionné,
minimisé.

Un lead (une opportunité) et son client sont liés à une ou plusieurs propriétés : adresse, type de bâtiment, étages,
âge, matériaux, historique de travaux, accès, contraintes, services potentiels, et des RÉFÉRENCES vers des photos et
des mesures (jamais leur contenu). M3 (estimation) et M4 (terrain) en ont besoin ; M2 en est la source.

Règles (Loi 25, AGENTS.md « fail-closed ») :

- **Liste blanche.** Un champ hors de `CHAMPS` est refusé (`REJ-PROP-CHAMP-INCONNU`) : aucun renseignement sur les
  occupants, aucun contact, aucun revenu, aucune pièce d'identité ne peut entrer par ici. Le profil ne porte ni le nom
  ni le contact du client : seulement son `client_id` (une référence).
- **Texte libre borné et filtré.** Les rares textes libres (matériau, nature d'un travail, note d'accès) sont courts
  et passent par le garde-fou de texte partagé : ni lien, ni adresse, ni courriel, ni téléphone, ni prix, ni « code
  d'accès » (`REJ-PROP-TEXTE-REFUSE`). Ce sont des DONNÉES NON FIABLES pour tout lecteur : jamais une consigne.
- **Sourcé.** Chaque valeur porte sa source (`declare_client`, `constate_vendeur`, `document_onboarding`, `courriel`,
  `mesure_liee`), une référence, et l'instant d'observation. Une source « agent » n'existe pas : un agent propose,
  avec la preuve qui le fonde, ou ne propose rien.
- **Versionné, à confirmer.** Chaque écriture est une RÉVISION d'un registre chaîné append-only ; une proposition est
  un BROUILLON tant qu'une personne ne l'a pas confirmée (ou écartée). Rien n'est supprimé ni réécrit.
- **Alimentation.** Saisie par une personne, ingestion d'onboarding (la fiche client validée porte l'adresse) et
  courriel (extraction par motifs fixes, avec l'extrait comme preuve) produisent des BROUILLONS, jamais un profil
  confirmé.

Module PUR : aucune entrée-sortie, aucune horloge (l'instant est fourni), aucun modèle.
"""

from __future__ import annotations

import copy
import re
import unicodedata
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from opsys import garde_fou_texte as gft
from opsys import taxonomie

from . import clients_importes, encodage
from . import horodatage as _horodatage
from .verdicts_commercial import construire_verdict

__all__ = [
    "ACCES",
    "CHAMPS",
    "CONTRAINTES",
    "ELEMENTS",
    "FINALITE",
    "PROFIL_TEXTE",
    "REGISTRE",
    "SOURCES",
    "TYPES_BATIMENT",
    "TYPE_ENTREE",
    "cle_adresse",
    "etat",
    "extraire_depuis_texte",
    "fait_confirme",
    "identifiant_propriete",
    "proposer",
    "decider",
    "proprietes_du_client",
    "valider_champs",
    "valider_source",
    "vue",
]

TYPE_ENTREE = "profil_propriete"
REGISTRE = "profils_propriete"
FINALITE = (
    "Préparer l'estimation et la planification de travaux sur la propriété du client (Loi 25 : renseignements "
    "strictement nécessaires à cette fin, aucun renseignement sur les occupants)."
)
EVENEMENT_CONFIRME = "m2.profil_propriete_confirme"

TYPES_BATIMENT = (
    "unifamiliale",
    "jumelee",
    "en_rangee",
    "duplex",
    "triplex",
    "multilogement",
    "copropriete",
    "commercial",
    "industriel",
    "autre",
)
ELEMENTS = (
    "fondation",
    "structure",
    "murs_exterieurs",
    "couverture",
    "fenetres",
    "portes",
    "chauffage",
    "plomberie",
    "electricite",
    "terrain",
    "autre",
)
ACCES = (
    "libre",
    "cour_arriere",
    "passage_etroit",
    "stationnement_rue",
    "cle_requise",
    "rendez_vous_requis",
    "escalier_exterieur",
    "autre",
)
CONTRAINTES = (
    "patrimoniale",
    "copropriete_syndicat",
    "pente_terrain",
    "ligne_electrique",
    "arbres_proches",
    "animaux",
    "voisinage_proche",
    "delai_saisonnier",
    "amiante_possible",
    "autre",
)
SOURCES = ("declare_client", "constate_vendeur", "document_onboarding", "courriel", "mesure_liee")
SOURCES_MESURE = ("m3", "m4", "manuel")

# Les champs de la liste blanche, et seulement eux (minimisation).
CHAMPS = (
    "adresse",
    "type_batiment",
    "etages",
    "annee_construction",
    "materiaux",
    "historique_travaux",
    "acces",
    "contraintes",
    "photos_liees",
    "mesures_liees",
    "services_potentiels",
)
# Champs qui suffisent à dire qu'un profil est « renseigné » : base de la complétude.
CHAMPS_CLES = ("adresse", "type_batiment", "etages", "annee_construction", "materiaux")

ETAGES_MAX = 12
ANNEE_MIN = 1800
LISTE_MAX = {
    "materiaux": 12,
    "historique_travaux": 20,
    "acces": 8,
    "contraintes": 10,
    "photos_liees": 50,
    "mesures_liees": 50,
    "services_potentiels": 10,
}
TEXTE_COURT = 60
TEXTE_NOTE = 160
EXTRAIT_MAX = 160
PROPRIETES_PAR_CLIENT_MAX = 10
REVISIONS_PAR_PROPRIETE_MAX = 200
COURRIEL_TEXTE_MAX = 8000

# Texte libre d'un profil : jamais un lien, une adresse, un contact, un prix (l'adresse a son propre champ).
PROFIL_TEXTE = gft.profil(
    "m2_propriete_texte", (gft.TEXTE_VIDE, gft.LIEN, gft.ADRESSE, gft.COORDONNEES, gft.PRIX_MONTANT)
)
# Un extrait de courriel est une PREUVE : une adresse y est permise (c'est le fait), un lien ou un contact non.
PROFIL_EXTRAIT = gft.profil("m2_propriete_extrait", (gft.TEXTE_VIDE, gft.LIEN, gft.COORDONNEES))
_SECRET_ACCES = re.compile(
    r"(?i)\b(?:code|mot de passe|mdp|nip|pin|cadenas|combinaison|digicode|cle numerique)\b.{0,40}?\d{2,}"
)
_CONTROLE = re.compile(r"[\x00-\x1f\x7f]")
_IDENTIFIANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+/~-]{0,119}$")
_FICHIER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,119}$")


def _refus(code: str, detail: str) -> tuple[None, dict[str, str]]:
    return None, construire_verdict(code, detail=detail)


# ---------------------------------------------------------------------------------------------- identité
def cle_adresse(ligne: str, ville: str, code_postal: str | None = None) -> str:
    """Clé stable de comparaison d'une adresse (sans accents, abréviations unifiées) : deux écritures de la même adresse
    donnent la même clé. Le code postal, s'il est fourni et valide, en fait partie."""
    base = clients_importes.normaliser_adresse(ligne) + "|" + clients_importes.normaliser_adresse(ville)
    postal = clients_importes.normaliser_code_postal(code_postal) if code_postal else None
    return base + ("|" + postal if postal else "")


def identifiant_propriete(client_id: str, adresse: Mapping[str, Any]) -> str:
    """Identifiant stable d'une propriété d'un client : empreinte de (client, adresse normalisée). Même adresse, même
    client : même identifiant, quelle que soit la façon de l'écrire."""
    return encodage.encoder_canonique(
        "m2-propriete-v1", client_id, cle_adresse(adresse["ligne"], adresse["ville"], adresse.get("code_postal"))
    )


# ---------------------------------------------------------------------------------------------- validation
def _texte(valeur: Any, nom: str, maximum: int) -> tuple[str | None, dict[str, str] | None]:
    if not isinstance(valeur, str):
        return _refus("REJ-PROP-VALEUR-INVALIDE", f"{nom} : texte attendu")
    propre = " ".join(unicodedata.normalize("NFKC", valeur).split())
    if not propre or len(propre) > maximum or _CONTROLE.search(valeur) is not None:
        return _refus("REJ-PROP-VALEUR-INVALIDE", f"{nom} : 1 à {maximum} caractères, sans caractère de contrôle")
    if _SECRET_ACCES.search(propre) is not None:
        return _refus("REJ-PROP-TEXTE-REFUSE", f"{nom} : un code d'accès, mot de passe ou cadenas ne se range pas ici")
    violations = gft.controler(propre, PROFIL_TEXTE)
    if violations:
        return _refus("REJ-PROP-TEXTE-REFUSE", f"{nom} : {gft.motif_de_refus(violations)}")
    return propre, None


def _entier(valeur: Any, nom: str, minimum: int, maximum: int) -> tuple[int | None, dict[str, str] | None]:
    if type(valeur) is not int or not minimum <= valeur <= maximum:
        return _refus("REJ-PROP-VALEUR-INVALIDE", f"{nom} : entier de {minimum} à {maximum}")
    return valeur, None


def _enum(valeur: Any, nom: str, permis: tuple[str, ...]) -> tuple[str | None, dict[str, str] | None]:
    if type(valeur) is not str or valeur not in permis:
        return _refus("REJ-PROP-VALEUR-INVALIDE", f"{nom} : l'une de {list(permis)}")
    return valeur, None


def _liste(valeur: Any, nom: str) -> tuple[list[Any] | None, dict[str, str] | None]:
    if not isinstance(valeur, list) or not valeur or len(valeur) > LISTE_MAX[nom]:
        return _refus("REJ-PROP-VALEUR-INVALIDE", f"{nom} : liste de 1 à {LISTE_MAX[nom]} éléments")
    return valeur, None


def _objet(valeur: Any, nom: str, permises: set[str], requises: set[str]) -> tuple[dict | None, dict | None]:
    if not isinstance(valeur, dict) or set(valeur) - permises or requises - set(valeur):
        return _refus(
            "REJ-PROP-VALEUR-INVALIDE", f"{nom} : objet de clés {sorted(permises)} (requises {sorted(requises)})"
        )
    return valeur, None


def _valider_adresse(valeur: Any, annee: int) -> tuple[dict | None, dict | None]:
    brut, verdict = _objet(valeur, "adresse", {"ligne", "ville", "code_postal"}, {"ligne", "ville"})
    if verdict is not None:
        return None, verdict
    ligne, verdict = _texte_adresse(brut["ligne"], "adresse.ligne", 120)
    if verdict is not None:
        return None, verdict
    ville, verdict = _texte_adresse(brut["ville"], "adresse.ville", 80)
    if verdict is not None:
        return None, verdict
    resultat = {"ligne": ligne, "ville": ville}
    if brut.get("code_postal") is not None:
        postal = clients_importes.normaliser_code_postal(str(brut["code_postal"]))
        if postal is None:
            return _refus("REJ-PROP-VALEUR-INVALIDE", "adresse.code_postal : code postal canadien (A1A 1A1)")
        resultat["code_postal"] = postal
    return resultat, None


def _texte_adresse(valeur: Any, nom: str, maximum: int) -> tuple[str | None, dict | None]:
    """Le champ adresse EST une adresse : seuls la longueur, les caractères de contrôle, les liens et les contacts sont
    refusés (la règle `adresse` du garde-fou s'appliquerait à tort)."""
    if not isinstance(valeur, str):
        return _refus("REJ-PROP-VALEUR-INVALIDE", f"{nom} : texte attendu")
    propre = " ".join(unicodedata.normalize("NFKC", valeur).split())
    if not propre or len(propre) > maximum or _CONTROLE.search(valeur) is not None:
        return _refus("REJ-PROP-VALEUR-INVALIDE", f"{nom} : 1 à {maximum} caractères, sans caractère de contrôle")
    violations = gft.controler(propre, gft.profil("m2_propriete_adresse", (gft.LIEN, gft.COORDONNEES)))
    if violations:
        return _refus("REJ-PROP-TEXTE-REFUSE", f"{nom} : {gft.motif_de_refus(violations)}")
    return propre, None


def _valider_materiaux(valeur: Any, annee: int) -> tuple[list | None, dict | None]:
    liste, verdict = _liste(valeur, "materiaux")
    if verdict is not None:
        return None, verdict
    sortie = []
    for i, brut in enumerate(liste):
        objet, verdict = _objet(brut, f"materiaux[{i}]", {"element", "materiau"}, {"element", "materiau"})
        if verdict is not None:
            return None, verdict
        element, verdict = _enum(objet["element"], f"materiaux[{i}].element", ELEMENTS)
        if verdict is not None:
            return None, verdict
        materiau, verdict = _texte(objet["materiau"], f"materiaux[{i}].materiau", TEXTE_COURT)
        if verdict is not None:
            return None, verdict
        sortie.append({"element": element, "materiau": materiau})
    return sortie, None


def _valider_historique(valeur: Any, annee: int) -> tuple[list | None, dict | None]:
    liste, verdict = _liste(valeur, "historique_travaux")
    if verdict is not None:
        return None, verdict
    sortie = []
    for i, brut in enumerate(liste):
        objet, verdict = _objet(brut, f"historique_travaux[{i}]", {"annee", "nature"}, {"annee", "nature"})
        if verdict is not None:
            return None, verdict
        an, verdict = _entier(objet["annee"], f"historique_travaux[{i}].annee", ANNEE_MIN, annee)
        if verdict is not None:
            return None, verdict
        nature, verdict = _texte(objet["nature"], f"historique_travaux[{i}].nature", TEXTE_NOTE)
        if verdict is not None:
            return None, verdict
        sortie.append({"annee": an, "nature": nature})
    return sortie, None


def _valider_codes(valeur: Any, nom: str, permis: tuple[str, ...]) -> tuple[list | None, dict | None]:
    liste, verdict = _liste(valeur, nom)
    if verdict is not None:
        return None, verdict
    sortie = []
    for i, brut in enumerate(liste):
        objet, verdict = _objet(brut, f"{nom}[{i}]", {"code", "note"}, {"code"})
        if verdict is not None:
            return None, verdict
        code, verdict = _enum(objet["code"], f"{nom}[{i}].code", permis)
        if verdict is not None:
            return None, verdict
        element = {"code": code}
        if objet.get("note") is not None:
            note, verdict = _texte(objet["note"], f"{nom}[{i}].note", TEXTE_NOTE)
            if verdict is not None:
                return None, verdict
            element["note"] = note
        sortie.append(element)
    return sortie, None


def _valider_photos(valeur: Any, annee: int) -> tuple[list | None, dict | None]:
    liste, verdict = _liste(valeur, "photos_liees")
    if verdict is not None:
        return None, verdict
    for i, brut in enumerate(liste):
        if type(brut) is not str or _FICHIER.fullmatch(brut) is None:
            return _refus(
                "REJ-PROP-VALEUR-INVALIDE", f"photos_liees[{i}] : identifiant de fichier (référence, jamais le contenu)"
            )
    return sorted(set(liste)), None


def _valider_mesures(valeur: Any, annee: int) -> tuple[list | None, dict | None]:
    liste, verdict = _liste(valeur, "mesures_liees")
    if verdict is not None:
        return None, verdict
    sortie = []
    for i, brut in enumerate(liste):
        objet, verdict = _objet(brut, f"mesures_liees[{i}]", {"source", "reference"}, {"source", "reference"})
        if verdict is not None:
            return None, verdict
        source, verdict = _enum(objet["source"], f"mesures_liees[{i}].source", SOURCES_MESURE)
        if verdict is not None:
            return None, verdict
        if type(objet["reference"]) is not str or _IDENTIFIANT.fullmatch(objet["reference"]) is None:
            return _refus(
                "REJ-PROP-VALEUR-INVALIDE", f"mesures_liees[{i}].reference : identifiant (référence seulement)"
            )
        sortie.append({"source": source, "reference": objet["reference"]})
    return sorted(sortie, key=lambda m: (m["source"], m["reference"])), None


def _valider_services(valeur: Any, annee: int) -> tuple[list | None, dict | None]:
    liste, verdict = _liste(valeur, "services_potentiels")
    if verdict is not None:
        return None, verdict
    codes = []
    for i, brut in enumerate(liste):
        service, verdict_service = taxonomie.valider_service(brut)
        if verdict_service is not None:
            return _refus("REJ-PROP-VALEUR-INVALIDE", f"services_potentiels[{i}] : {verdict_service['detail']}")
        codes.append(service.code)
    return sorted(set(codes)), None


def valider_champs(champs: Any, horodatage: str) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """`(champs normalisés, None)` ou `(None, verdict)` : liste blanche, valeurs bornées, textes filtrés. Un champ à
    `None` est refusé (on n'efface pas par ce chemin : une nouvelle révision remplace la valeur)."""
    try:
        _horodatage.valider_horodatage(horodatage)
        annee = datetime.fromisoformat(horodatage).year
    except ValueError:
        return _refus("REJ-PROP-ARGUMENT-INVALIDE", "horodatage : ISO-8601 avec fuseau attendu")
    if not isinstance(champs, dict) or not champs:
        return _refus("REJ-PROP-ARGUMENT-INVALIDE", "champs : objet non vide attendu")
    inconnus = sorted(set(champs) - set(CHAMPS))
    if inconnus:
        return _refus(
            "REJ-PROP-CHAMP-INCONNU",
            (
                f"champ(s) {inconnus} hors de la liste blanche {list(CHAMPS)} : le profil de propriété ne porte aucun "
                "renseignement sur les occupants ni aucun contact (minimisation, Loi 25)"
            ),
        )
    sortie: dict[str, Any] = {}
    for nom in CHAMPS:
        if nom not in champs:
            continue
        valeur = champs[nom]
        if nom == "adresse":
            resultat, verdict = _valider_adresse(valeur, annee)
        elif nom == "type_batiment":
            resultat, verdict = _enum(valeur, nom, TYPES_BATIMENT)
        elif nom == "etages":
            resultat, verdict = _entier(valeur, nom, 1, ETAGES_MAX)
        elif nom == "annee_construction":
            resultat, verdict = _entier(valeur, nom, ANNEE_MIN, annee)
        elif nom == "materiaux":
            resultat, verdict = _valider_materiaux(valeur, annee)
        elif nom == "historique_travaux":
            resultat, verdict = _valider_historique(valeur, annee)
        elif nom == "acces":
            resultat, verdict = _valider_codes(valeur, nom, ACCES)
        elif nom == "contraintes":
            resultat, verdict = _valider_codes(valeur, nom, CONTRAINTES)
        elif nom == "photos_liees":
            resultat, verdict = _valider_photos(valeur, annee)
        elif nom == "mesures_liees":
            resultat, verdict = _valider_mesures(valeur, annee)
        else:
            resultat, verdict = _valider_services(valeur, annee)
        if verdict is not None:
            return None, verdict
        sortie[nom] = resultat
    return sortie, None


def valider_source(source: Any, *, extrait_permis: bool = True) -> tuple[dict[str, str] | None, dict[str, str] | None]:
    """La source d'un fait : `{type, reference}` (+ `extrait` pour un courriel). Sans source, aucun fait."""
    if (
        not isinstance(source, dict)
        or set(source) - {"type", "reference", "extrait"}
        or not {"type", "reference"} <= set(source)
    ):
        return _refus("REJ-PROP-SOURCE-INVALIDE", "source : {type, reference} (+ extrait pour un courriel) exigés")
    if source["type"] not in SOURCES:
        return _refus("REJ-PROP-SOURCE-INVALIDE", f"source.type : l'une de {list(SOURCES)}")
    if type(source["reference"]) is not str or _IDENTIFIANT.fullmatch(source["reference"]) is None:
        return _refus(
            "REJ-PROP-SOURCE-INVALIDE", "source.reference : identifiant de 1 à 120 caractères (message, lot, visite)"
        )
    sortie = {"type": source["type"], "reference": source["reference"]}
    if source.get("extrait") is not None:
        if not extrait_permis or source["type"] != "courriel":
            return _refus("REJ-PROP-SOURCE-INVALIDE", "source.extrait : réservé à un fait tiré d'un courriel")
        extrait = source["extrait"]
        if (
            type(extrait) is not str
            or not extrait.strip()
            or len(extrait) > EXTRAIT_MAX
            or _CONTROLE.search(extrait) is not None
        ):
            return _refus("REJ-PROP-SOURCE-INVALIDE", f"source.extrait : 1 à {EXTRAIT_MAX} caractères")
        violations = gft.controler(extrait, PROFIL_EXTRAIT)
        if violations:
            return _refus("REJ-PROP-TEXTE-REFUSE", f"source.extrait : {gft.motif_de_refus(violations)}")
        sortie["extrait"] = " ".join(extrait.split())
    return sortie, None


# ---------------------------------------------------------------------------------------------- registre
def _maillons(registre_cible: Any, propriete_id: str) -> list[dict[str, Any]]:
    return [
        m
        for m in registre_cible.lire()
        if m.get("type_entree") == TYPE_ENTREE and m.get("propriete_id") == propriete_id
    ]


def proprietes_du_client(registre_cible: Any, client_id: str) -> list[str]:
    """Les `propriete_id` d'un client, dans l'ordre de première apparition."""
    vus: list[str] = []
    for m in registre_cible.lire():
        if m.get("type_entree") == TYPE_ENTREE and m.get("client_id") == client_id and m["propriete_id"] not in vus:
            vus.append(m["propriete_id"])
    return vus


def etat(registre_cible: Any, propriete_id: str) -> dict[str, Any]:
    """L'état d'une propriété : `confirme` (dernier snapshot confirmé), `brouillon` (dernière proposition non décidée),
    `revision` (nombre de propositions), `historique` (maillons, sans les snapshots)."""
    propositions: dict[int, dict[str, Any]] = {}
    decisions: dict[int, dict[str, Any]] = {}
    for m in _maillons(registre_cible, propriete_id):
        if m["evenement"] == "proposition":
            propositions[m["revision"]] = m
        else:
            decisions[m["revision"]] = m
    confirme = None
    for revision in sorted(decisions):
        if decisions[revision]["evenement"] == "confirmation":
            confirme = propositions[revision]
    brouillon = None
    if propositions:
        derniere = max(propositions)
        if derniere not in decisions:
            brouillon = propositions[derniere]
    return {
        "propriete_id": propriete_id,
        "confirme": copy.deepcopy(confirme),
        "brouillon": copy.deepcopy(brouillon),
        "revision": max(propositions) if propositions else 0,
        "decisions": [copy.deepcopy(decisions[r]) for r in sorted(decisions)],
    }


def _base(etat_courant: Mapping[str, Any]) -> dict[str, Any]:
    source = etat_courant["brouillon"] or etat_courant["confirme"]
    return copy.deepcopy(source["champs"]) if source else {}


def proposer(
    registre_cible: Any,
    *,
    client_id: str,
    lead_id: str,
    propriete_id: str | None,
    champs: Any,
    sources: Mapping[str, Mapping[str, str]] | Mapping[str, Any],
    origine: str,
    par: str,
    revision_attendue: int | None,
    horodatage: str,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Ajoute une RÉVISION en brouillon. `sources` : une source par champ proposé (ou la clé `"*"` pour tous). Le
    brouillon courant (ou, à défaut, le profil confirmé) sert de base : seuls les champs fournis changent. Création
    (`propriete_id` absent) : l'adresse est exigée, l'identifiant en dérive. `revision_attendue` : la révision lue (0
    pour une création) ; une autre est périmée.

    Rend `({"propriete_id", "revision", "champs_modifies", "entree"}, None)` après avoir écrit un maillon, ou `(None,
    verdict)` sans rien écrire."""
    normalises, verdict = valider_champs(champs, horodatage)
    if verdict is not None:
        return None, verdict
    if not isinstance(origine, str) or not origine or not isinstance(par, str) or not par:
        return _refus("REJ-PROP-ARGUMENT-INVALIDE", "origine et auteur de la proposition exigés")
    fournies: dict[str, dict[str, str]] = {}
    for nom in normalises:
        brute = sources.get(nom, sources.get("*")) if isinstance(sources, Mapping) else None
        propre, verdict = valider_source(brute)
        if verdict is not None:
            return None, verdict
        fournies[nom] = propre
    if propriete_id is None:
        if "adresse" not in normalises:
            return _refus("REJ-PROP-ADRESSE-REQUISE", "créer une propriété exige une adresse (ligne et ville)")
        propriete_id = identifiant_propriete(client_id, normalises["adresse"])
        existantes = proprietes_du_client(registre_cible, client_id)
        if propriete_id not in existantes and len(existantes) >= PROPRIETES_PAR_CLIENT_MAX:
            return _refus("REJ-PROP-QUOTA", f"{PROPRIETES_PAR_CLIENT_MAX} propriétés au plus par client")
    else:
        if propriete_id not in proprietes_du_client(registre_cible, client_id):
            return _refus("REJ-PROP-INCONNUE", "propriété inconnue pour ce client")
        if "adresse" in normalises and identifiant_propriete(client_id, normalises["adresse"]) != propriete_id:
            return _refus(
                "REJ-PROP-VALEUR-INVALIDE",
                "adresse : une autre adresse est une autre propriété (omettre propriete_id pour la créer)",
            )
    courant = etat(registre_cible, propriete_id)
    if revision_attendue != courant["revision"]:
        return _refus(
            "REJ-PROP-REVISION-PERIMEE",
            (f"révision attendue {revision_attendue!r}, courante {courant['revision']} : relire avant de proposer"),
        )
    if courant["revision"] >= REVISIONS_PAR_PROPRIETE_MAX:
        return _refus("REJ-PROP-QUOTA", f"{REVISIONS_PAR_PROPRIETE_MAX} révisions au plus par propriété")
    base = _base(courant)
    snapshot = copy.deepcopy(base)
    modifies = []
    for nom, valeur in normalises.items():
        if base.get(nom, {}).get("valeur") != valeur:
            modifies.append(nom)
        snapshot[nom] = {"valeur": valeur, "source": fournies[nom], "observe_le": horodatage}
    if not modifies:
        return _refus("REJ-PROP-VALEUR-INVALIDE", "aucun changement : ces valeurs sont déjà au brouillon ou au profil")
    entree = {
        "type_entree": TYPE_ENTREE,
        "evenement": "proposition",
        "propriete_id": propriete_id,
        "client_id": client_id,
        "lead_id": lead_id,
        "revision": courant["revision"] + 1,
        "champs": snapshot,
        "champs_modifies": sorted(modifies),
        "origine": origine,
        "par": par,
        "finalite": FINALITE,
        "horodatage": horodatage,
    }
    registre_cible.ajouter(entree)
    return {
        "propriete_id": propriete_id,
        "revision": entree["revision"],
        "champs_modifies": sorted(modifies),
        "entree": registre_cible.lire()[-1],
    }, None


def decider(
    registre_cible: Any,
    *,
    propriete_id: str,
    client_id: str,
    revision_attendue: Any,
    decision: Any,
    motif: Any,
    par: str,
    role: str,
    voie: str,
    horodatage: str,
) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Une PERSONNE confirme ou écarte le brouillon courant. Écarter exige un motif. Rend l'entrée écrite."""
    try:
        _horodatage.valider_horodatage(horodatage)
    except ValueError:
        return _refus("REJ-PROP-ARGUMENT-INVALIDE", "horodatage : ISO-8601 avec fuseau attendu")
    if decision not in ("confirmer", "ecarter"):
        return _refus("REJ-PROP-ARGUMENT-INVALIDE", "decision : confirmer ou ecarter")
    if propriete_id not in proprietes_du_client(registre_cible, client_id):
        return _refus("REJ-PROP-INCONNUE", "propriété inconnue pour ce client")
    courant = etat(registre_cible, propriete_id)
    if courant["brouillon"] is None:
        derniere = courant["decisions"][-1]["revision"] if courant["decisions"] else None
        if derniere is not None and revision_attendue == derniere:
            return _refus("REJ-PROP-DEJA-DECIDEE", f"la révision {derniere} a déjà été décidée")
        return _refus("REJ-PROP-AUCUNE-PROPOSITION", "aucun brouillon à confirmer ou à écarter")
    if revision_attendue != courant["brouillon"]["revision"]:
        return _refus(
            "REJ-PROP-REVISION-PERIMEE",
            (f"révision attendue {revision_attendue!r}, brouillon courant {courant['brouillon']['revision']}"),
        )
    if decision == "ecarter":
        if not isinstance(motif, str) or not motif.strip() or len(motif) > 300 or not motif.isprintable():
            return _refus("REJ-PROP-ARGUMENT-INVALIDE", "écarter exige un motif (300 caractères imprimables)")
    elif motif is not None:
        return _refus("REJ-PROP-ARGUMENT-INVALIDE", "motif : réservé à un écartement")
    entree = {
        "type_entree": TYPE_ENTREE,
        "evenement": "confirmation" if decision == "confirmer" else "ecartement",
        "propriete_id": propriete_id,
        "client_id": client_id,
        "lead_id": courant["brouillon"]["lead_id"],
        "revision": courant["brouillon"]["revision"],
        "decide_par": par,
        "role": role,
        "voie": voie,
        "motif": motif.strip() if isinstance(motif, str) else None,
        "horodatage": horodatage,
    }
    registre_cible.ajouter(entree)
    return {
        "propriete_id": propriete_id,
        "revision": entree["revision"],
        "decision": decision,
        "entree": registre_cible.lire()[-1],
        "snapshot": courant["brouillon"]["champs"],
    }, None


# ---------------------------------------------------------------------------------------------- lecture
def _age(champs: Mapping[str, Any], maintenant: str) -> int | None:
    annee = champs.get("annee_construction", {}).get("valeur")
    if type(annee) is not int:
        return None
    return max(0, datetime.fromisoformat(maintenant).year - annee)


def completude(champs: Mapping[str, Any]) -> dict[str, Any]:
    """La part des champs clés renseignés, et ceux qui manquent : jamais une valeur devinée pour combler."""
    manquants = [nom for nom in CHAMPS_CLES if nom not in champs]
    return {"pourcentage": (100 * (len(CHAMPS_CLES) - len(manquants))) // len(CHAMPS_CLES), "manquants": manquants}


def vue(etat_courant: Mapping[str, Any], maintenant: str, *, historique: bool = False) -> dict[str, Any]:
    """La vue lisible d'une propriété : le profil confirmé, le brouillon en attente (avec ce qu'il change), l'âge et la
    complétude. Les textes libres sont des DONNÉES NON FIABLES (marqué) ; aucun contact ni nom n'y figure."""

    def corps(maillon: Mapping[str, Any] | None) -> dict[str, Any] | None:
        if maillon is None:
            return None
        champs = maillon["champs"]
        return {
            "revision": maillon["revision"],
            "propose_le": maillon["horodatage"],
            "origine": maillon.get("origine"),
            "champs": {
                nom: {
                    "valeur": champs[nom]["valeur"],
                    "source": champs[nom]["source"],
                    "observe_le": champs[nom]["observe_le"],
                }
                for nom in CHAMPS
                if nom in champs
            },
            "age_batiment_annees": _age(champs, maintenant),
            "completude": completude(champs),
        }

    brouillon = corps(etat_courant["brouillon"])
    if brouillon is not None:
        brouillon["champs_modifies"] = list(etat_courant["brouillon"].get("champs_modifies", []))
    sortie = {
        "propriete_id": etat_courant["propriete_id"],
        "profil_confirme": corps(etat_courant["confirme"]),
        "brouillon_a_confirmer": brouillon,
        "revision": etat_courant["revision"],
        "finalite": FINALITE,
        "fiabilite_textes_libres": "donnee_non_fiable",
    }
    if historique:
        sortie["decisions"] = [
            {k: d.get(k) for k in ("evenement", "revision", "decide_par", "role", "voie", "motif", "horodatage")}
            for d in etat_courant["decisions"]
        ]
    return sortie


def fait_confirme(
    client_id: str, propriete_id: str, revision: int, snapshot: Mapping[str, Any], horodatage: str
) -> tuple[str, dict[str, Any]]:
    """`(evenement_id, charge)` de `m2.profil_propriete_confirme` : un fait MINIMISÉ pour M3, M4 et M10 (références et
    attributs du bâtiment ; jamais l'adresse précise, le code postal, les notes, les photos ni les mesures)."""
    fait_id = encodage.encoder_canonique("m2-propriete-confirmee-v1", propriete_id, revision)

    def valeur(nom: str) -> Any:
        return snapshot.get(nom, {}).get("valeur")

    charge: dict[str, Any] = {
        "fait_id": fait_id,
        "client_id": client_id,
        "propriete_id": propriete_id,
        "revision": revision,
        "ville": valeur("adresse")["ville"] if valeur("adresse") else None,
        "type_batiment": valeur("type_batiment"),
        "etages": valeur("etages"),
        "annee_construction": valeur("annee_construction"),
        "nb_photos_liees": len(valeur("photos_liees") or []),
        "nb_mesures_liees": len(valeur("mesures_liees") or []),
        "horodatage": horodatage,
    }
    return "m2-propriete-" + fait_id, {cle: v for cle, v in charge.items() if v is not None}


# ---------------------------------------------------------------------------------------------- courriel
_NOMBRES = {"un": 1, "une": 1, "deux": 2, "trois": 3, "quatre": 4, "cinq": 5}
_TYPES_MOTS = (
    (re.compile(r"\bjumel[ée]e?s?\b", re.I), "jumelee"),
    (re.compile(r"\bduplex\b", re.I), "duplex"),
    (re.compile(r"\btriplex\b", re.I), "triplex"),
    (re.compile(r"\bunifamiliale?s?\b", re.I), "unifamiliale"),
    (re.compile(r"\b(?:maison|unit[ée])\s+en\s+rang[ée]e\b", re.I), "en_rangee"),
    (re.compile(r"\b(?:condo|copropri[ée]t[ée])\b", re.I), "copropriete"),
    (re.compile(r"\bmultilogements?\b", re.I), "multilogement"),
    (re.compile(r"\b(?:commerce|local commercial|b[âa]timent commercial)\b", re.I), "commercial"),
)
_ELEMENTS_MOTS = (
    (re.compile(r"\bmurs?(?:\s+ext[ée]rieurs?)?\b", re.I), "murs_exterieurs"),
    (re.compile(r"\bfen[êe]tres?\b", re.I), "fenetres"),
    (re.compile(r"\bportes?\b", re.I), "portes"),
    (re.compile(r"\bfondations?\b", re.I), "fondation"),
    (re.compile(r"\bcouverture\b", re.I), "couverture"),
)
_MATERIAUX = (
    "brique",
    "bois",
    "aluminium",
    "pierre",
    "béton",
    "acier",
    "stucco",
    "fibrociment",
    "asphalte",
    "cèdre",
    "composite",
    "verre",
)
_RE_ETAGES_CHIFFRE = re.compile(r"\b(\d{1,2})\s+[ée]tages?\b", re.I)
_RE_ETAGES_MOT = re.compile(r"\b(un|une|deux|trois|quatre|cinq)\s+[ée]tages?\b", re.I)
_RE_PLAIN_PIED = re.compile(r"\bplain-pied\b", re.I)
_RE_ANNEE = re.compile(r"\b(?:construit[e]?|b[âa]ti[e]?)\s+(?:en|vers)\s+((?:18|19|20)\d{2})\b", re.I)
_RE_TRAVAUX = re.compile(
    r"\b((?:remplac|refait|refaite|install|r[ée]par)\w*\s+[^.\n,;]{3,60}?)\s+en\s+((?:19|20)\d{2})\b", re.I
)
_RE_ADRESSE = re.compile(
    r"\b(\d{1,5}[a-zA-Z]?,?\s+(?:rue|avenue|av\.|boulevard|boul\.|chemin|rang|route|place|impasse|mont[ée]e)\s+"
    r"[^,\n]{2,50}?)\s*,\s*([A-ZÀ-ÖØ-Þ][A-Za-zÀ-ÿ' -]{1,40}?)(?:\s*,|\s+(?=[A-Z]\d[A-Z])|[.\n]|$)"
)


def _extrait(texte: str, debut: int, fin: int) -> str | None:
    """La phrase qui fonde un fait : le passage avec un peu de contexte, sinon le passage seul, sinon rien (un contact
    ou
    un lien voisin ne doit jamais entrer dans le profil)."""
    for a, b in ((max(0, debut - 20), min(len(texte), fin + 20)), (debut, fin)):
        candidat = " ".join(texte[a:b].split())[:EXTRAIT_MAX]
        if candidat and not gft.controler(candidat, PROFIL_EXTRAIT):
            return candidat
    return None


def _noter(extraits: dict[str, str], nom: str, extrait: str | None) -> None:
    if extrait is not None:
        extraits.setdefault(nom, extrait)


def extraire_depuis_texte(texte: Any, horodatage: str) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
    """Les faits de propriété qu'un courriel dit en toutes lettres, par MOTIFS FIXES (jamais un modèle) : `({champs,
    extraits}, None)` ou `(None, REJ-PROP-EXTRACTION-VIDE)`. `extraits[nom]` est la phrase du courriel qui fonde la
    valeur (la preuve). Le texte du courriel est une donnée non fiable : seules des valeurs typées de la liste blanche
    en sortent, validées comme toute saisie ; une consigne glissée dans le texte n'a aucun effet.

    Ce que cette extraction NE fait pas : deviner une adresse partielle, un étage d'après une photo, une année d'après
    un style. Ce qui n'est pas écrit n'est pas proposé."""
    if not isinstance(texte, str) or not texte.strip() or len(texte) > COURRIEL_TEXTE_MAX:
        return _refus("REJ-PROP-ARGUMENT-INVALIDE", f"texte : 1 à {COURRIEL_TEXTE_MAX} caractères")
    propre = unicodedata.normalize("NFKC", texte)
    champs: dict[str, Any] = {}
    extraits: dict[str, str] = {}
    try:
        annee_max = datetime.fromisoformat(horodatage).year
    except ValueError:
        return _refus("REJ-PROP-ARGUMENT-INVALIDE", "horodatage : ISO-8601 avec fuseau attendu")
    m = _RE_ADRESSE.search(propre)
    if m:
        adresse = {"ligne": " ".join(m.group(1).split()), "ville": " ".join(m.group(2).split())}
        postal = re.search(
            r"\b([ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z])\s?(\d[ABCEGHJ-NPRSTV-Z]\d)\b", propre[m.end() : m.end() + 30]
        )
        if postal:
            adresse["code_postal"] = postal.group(1) + " " + postal.group(2)
        champs["adresse"] = adresse
        _noter(extraits, "adresse", _extrait(propre, m.start(), m.end()))
    for motif, code in _TYPES_MOTS:
        m = motif.search(propre)
        if m:
            champs["type_batiment"] = code
            _noter(extraits, "type_batiment", _extrait(propre, m.start(), m.end()))
            break
    m = _RE_ETAGES_CHIFFRE.search(propre)
    if m and 1 <= int(m.group(1)) <= ETAGES_MAX:
        champs["etages"] = int(m.group(1))
        _noter(extraits, "etages", _extrait(propre, m.start(), m.end()))
    else:
        m = _RE_ETAGES_MOT.search(propre)
        if m:
            champs["etages"] = _NOMBRES[m.group(1).lower()]
            _noter(extraits, "etages", _extrait(propre, m.start(), m.end()))
        else:
            m = _RE_PLAIN_PIED.search(propre)
            if m:
                champs["etages"] = 1
                _noter(extraits, "etages", _extrait(propre, m.start(), m.end()))
    m = _RE_ANNEE.search(propre)
    if m and ANNEE_MIN <= int(m.group(1)) <= annee_max:
        champs["annee_construction"] = int(m.group(1))
        _noter(extraits, "annee_construction", _extrait(propre, m.start(), m.end()))
    materiaux = []
    for motif_element, element in _ELEMENTS_MOTS:
        for me in motif_element.finditer(propre):
            fenetre = propre[me.end() : me.end() + 40]
            mat = re.match(r"\s+(?:en|de|d')\s*(?:" + "|".join(_MATERIAUX) + r")\b", fenetre, re.I)
            if mat:
                nom_mat = re.search("|".join(_MATERIAUX), mat.group(0), re.I).group(0).lower()
                materiaux.append({"element": element, "materiau": nom_mat})
                _noter(extraits, "materiaux", _extrait(propre, me.start(), me.end() + mat.end()))
                break
    if materiaux:
        champs["materiaux"] = [dict(t) for t in {tuple(sorted(x.items())) for x in materiaux}]
        champs["materiaux"].sort(key=lambda x: (x["element"], x["materiau"]))
    travaux = []
    for mt in _RE_TRAVAUX.finditer(propre):
        an = int(mt.group(2))
        if ANNEE_MIN <= an <= annee_max and len(travaux) < LISTE_MAX["historique_travaux"]:
            travaux.append({"annee": an, "nature": " ".join(mt.group(1).split())[:TEXTE_NOTE]})
            _noter(extraits, "historique_travaux", _extrait(propre, mt.start(), mt.end()))
    if travaux:
        champs["historique_travaux"] = travaux
    if not champs:
        return _refus("REJ-PROP-EXTRACTION-VIDE", "aucun fait de propriété reconnu dans ce texte (rien n'est deviné)")
    valides, verdict = valider_champs(champs, horodatage)
    if verdict is not None:
        # Un fait extrait que la validation refuse (texte filtré, valeur hors bornes) est retiré un à un : le reste
        # peut rester. Un refus total reste « extraction vide ».
        retenus = {}
        for nom, valeur in champs.items():
            propre_valeur, verdict_champ = valider_champs({nom: valeur}, horodatage)
            if verdict_champ is None:
                retenus.update(propre_valeur)
        if not retenus:
            return _refus("REJ-PROP-EXTRACTION-VIDE", "les faits reconnus ont été refusés par la validation")
        valides = retenus
    return {"champs": valides, "extraits": {nom: extraits[nom] for nom in valides if nom in extraits}}, None
