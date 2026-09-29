"""Taxonomie métier partagée : les services qu'une entreprise offre (PLAN T0.13).

Une seule taxonomie, dans le socle. Les départements (M1 qualifie, M2 structure, M3 estime) ne
gardent aucune copie locale de la liste des services : ils la lisent ici. Un test de dérive
(`tests/test_taxonomie_derive.py`) refuse qu'une copie réapparaisse.

Deux couches :

- Le CATALOGUE DE RÉFÉRENCE (`CATALOGUE_REFERENCE`) : les quatre services réels du premier client,
  Gouttières et Revêtements Synergy (DEFINITION-PRODUIT §1, M1.3, M3.8, M6.1) — gouttières et
  descentes, revêtement extérieur, soffite/fascia, réparation. Codes stables, libellés fr-CA.
  C'est un vocabulaire, pas une déclaration : rien n'est accepté du seul fait d'y figurer.
- Le PROFIL D'ENTREPRISE de l'instance : `$OPSYS_HOME/entreprise.yaml`, clé `services`. C'est lui
  qui déclare ce que CETTE entreprise offre : des codes du catalogue, ou ses propres services
  (`code`, `libelle`, `mots_cles` optionnel) pour une autre PME en SaaS. Même mécanisme que
  `$OPSYS_HOME/paliers.yaml` (`opsys.modeles`) : un fichier de l'instance, lu à la demande,
  écrit avec un nom signé au journal d'audit.

Fail-closed (AGENTS.md) : sans profil, ou avec un profil sans service, AUCUN service n'est
accepté — pas même ceux du catalogue. Aucun service par défaut n'est inventé pour une entreprise
qui ne l'a pas déclaré. Le verdict de refus dit quoi configurer et où.

Le même profil porte aussi la ZONE DESSERVIE (`zone_desservie`, les villes où l'entreprise intervient,
PLAN T2.1) : M1 la lit ici, jamais dans ce qu'un client ou un modèle lui écrit. Sans zone, aucune ville
n'est reconnue et le verdict dit où la déclarer.

Et la FENÊTRE DE CONVERSATION (`fenetre_conversation_minutes`, PLAN T2.1-b) : la durée pendant laquelle M1
rassemble les messages d'un même client pour qualifier une demande écrite en plusieurs messages. Aucune durée
n'est inventée : sans elle, M1 qualifie message par message et le verdict le dit.

Enfin, ce que M1 demande et note pour qualifier un lead (PLAN T4.4) : les QUESTIONS OBLIGATOIRES PAR SERVICE
(`questions_qualification`, écrites par le propriétaire : aucune n'est dans le code) et les POIDS du score de lead
(`poids_score_lead`). Sans questions déclarées, le verdict le dit et M1 n'en invente aucune ; sans poids, il n'y a
pas de score (« poids à configurer »).

Et ce que M1 reconnaît d'une plainte ou d'une urgence de sécurité, et à qui il transfère (PLAN T4.5) : le
VOCABULAIRE des plaintes (`signaux_plainte`, par catégorie, écrit par le propriétaire : aucun mot n'est dans le code) et
la table « type de transfert -> rôle » (`destinataires_transfert`, vide par défaut : le verdict dit « destinataire à
configurer »). Le profil de l'instance les porte, comme le reste, parce que chaque PME a ses mots et ses gens.

Ce module est pur (fichier YAML et journal d'audit seulement) : il ne connaît ni M1, ni M2, ni M3.
Les verdicts sont des dict `{"code", "detail"}` ; chaque département les traduit dans son propre
catalogue de codes et garde le `detail`, qui porte la consigne de configuration.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .etat import dossier_opsys
from .identite import Role

NOM_FICHIER_PROFIL = "entreprise.yaml"
CLE_SERVICES = "services"
CLE_ZONE = "zone_desservie"
CLE_FENETRE_CONVERSATION = "fenetre_conversation_minutes"
CLE_QUESTIONS_QUALIFICATION = "questions_qualification"
CLE_POIDS_SCORE_LEAD = "poids_score_lead"
CLE_SIGNAUX_PLAINTE = "signaux_plainte"
CLE_DESTINATAIRES_TRANSFERT = "destinataires_transfert"

# Codes de verdict émis par ce module (jamais un booléen nu : le détail dit quoi corriger).
VERDICT_SERVICE_NON_CONFIGURE = "REJ-SERVICE-NON-CONFIGURE"
VERDICT_SERVICE_INCONNU = "REJ-SERVICE-INCONNU"
VERDICT_SERVICE_INVALIDE = "REJ-SERVICE-INVALIDE"
VERDICT_PROFIL_INVALIDE = "REJ-PROFIL-INVALIDE"
VERDICT_ZONE_NON_CONFIGUREE = "REJ-ZONE-NON-CONFIGUREE"
VERDICT_FENETRE_NON_CONFIGUREE = "REJ-FENETRE-NON-CONFIGUREE"
VERDICT_QUESTIONS_NON_CONFIGUREES = "REJ-QUESTIONS-NON-CONFIGUREES"
VERDICT_POIDS_SCORE_NON_CONFIGURES = "REJ-POIDS-SCORE-NON-CONFIGURES"
VERDICT_SIGNAUX_PLAINTE_NON_CONFIGURES = "REJ-SIGNAUX-PLAINTE-NON-CONFIGURES"
VERDICT_DESTINATAIRE_NON_CONFIGURE = "REJ-DESTINATAIRE-NON-CONFIGURE"

_FORME_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_LIBELLE_MAX = 120
_MOTS_CLES_MAX = 20
_VILLES_MAX = 300
_VILLE_MAX = 80
# Garde contre une faute de frappe (« 30000 » pour « 30 »), pas une valeur par défaut : sept jours.
FENETRE_CONVERSATION_MAX_MINUTES = 7 * 24 * 60
# Les critères du score de lead sont les règles du code (M1 `score.py`) ; leurs POIDS sont ceux du propriétaire.
CRITERES_SCORE_LEAD = ("urgence", "completude", "zone")
POIDS_SCORE_LEAD_MAX = 1000
_QUESTION_MAX = 300
_QUESTIONS_PAR_SERVICE_MAX = 10
_CARACTERE_DE_CONTROLE = re.compile(r"[\x00-\x1f\x7f]")

# Ce que M1 reconnaît d'un message (PLAN T4.5). Les catégories sont un ensemble FERMÉ : le code sait ce que chacune
# déclenche ; les MOTS de chacune sont ceux du propriétaire. `securite` est une urgence (escaladée tout de suite) ;
# les quatre autres sont des plaintes (la plainte prime : elle n'ouvre jamais de lead).
CATEGORIES_SIGNAL_PLAINTE = ("insatisfaction", "degat", "garantie", "avocat", "securite")
_TERME_SIGNAL_MIN = 3
_TERME_SIGNAL_MAX = 80
_TERMES_PAR_CATEGORIE_MAX = 60
# Types de transfert à un humain (DEFINITION-PRODUIT §7 M1.12) : ensemble fermé, sans accent (codes stables).
TYPES_TRANSFERT = (
    "ventes", "estimation", "admin", "finance", "plainte", "urgence", "technique", "proprietaire",
)
# Qui peut recevoir un transfert : une PERSONNE de l'entreprise. Ni le client, ni l'agent système.
ROLES_DESTINATAIRES_TRANSFERT: tuple[str, ...] = tuple(
    role.value for role in Role if role not in (Role.CLIENT, Role.SYSTEM_AGENT)
)


class ProfilInvalide(ValueError):
    """Le profil d'entreprise est illisible ou ne respecte pas le schéma (le message dit quoi corriger)."""


@dataclass(frozen=True)
class Service:
    """Un service offert : code stable (contrat inter-départements), libellé fr-CA, et les termes
    qui l'évoquent dans une demande (`mots_cles`, utilisés par la qualification de M1)."""

    code: str
    libelle: str
    mots_cles: tuple[str, ...] = ()


@dataclass(frozen=True)
class QuestionQualification:
    """Une question obligatoire d'un service, écrite par le propriétaire dans le profil (PLAN T4.4).

    `question` : le texte que M1 propose au client (un brouillon, jamais envoyé par M1). `mots_cles` : les termes qui
    montrent que le client y a répondu (mêmes règles que ceux d'un service : mot entier, pluriel admis, accents et
    casse ignorés) ; sans eux, le code ne pourrait jamais reconnaître la réponse. `photos` : la question demande des
    photos ; le texte du client ne la « répond » pas, et M1 ne la propose que si la politique « photos » est validée.
    """

    code: str
    question: str
    mots_cles: tuple[str, ...] = ()
    photos: bool = False


# Les quatre services réels du premier client (DEFINITION-PRODUIT §1 ; M1.3 ; M3.8 ; M6.1).
# Les mots-clés sont des racines au singulier : M1 les compare sans accent ni casse, pluriel admis.
CATALOGUE_REFERENCE: tuple[Service, ...] = (
    Service("gouttieres", "Gouttières et descentes",
            ("gouttière", "descente pluviale", "descente de gouttière")),
    Service("revetement", "Revêtement extérieur", ("revêtement", "siding")),
    Service("soffite_fascia", "Soffite et fascia", ("soffite", "fascia")),
    Service("reparation", "Réparation", ("réparation", "réparer")),
)
_PAR_CODE_CATALOGUE: dict[str, Service] = {s.code: s for s in CATALOGUE_REFERENCE}


def codes_catalogue() -> tuple[str, ...]:
    """Codes du catalogue de référence, dans l'ordre du catalogue."""
    return tuple(s.code for s in CATALOGUE_REFERENCE)


def fichier_profil() -> Path:
    return dossier_opsys() / NOM_FICHIER_PROFIL


def _consigne_configuration(chemin: Path) -> str:
    return (
        f"déclare les services de l'entreprise dans {chemin} (clé '{CLE_SERVICES}') : des codes du "
        f"catalogue de référence ({', '.join(codes_catalogue())}) ou tes propres services "
        "(code, libelle)"
    )


def _valider_code(code: Any, contexte: str) -> str:
    if not isinstance(code, str) or not _FORME_CODE.match(code):
        raise ProfilInvalide(
            f"{contexte} : code de service invalide {code!r} (minuscules, chiffres et _, "
            "commence par une lettre, 64 caractères au plus)"
        )
    return code


def _valider_mots_cles(brut: Any, contexte: str) -> tuple[str, ...]:
    if brut is None:
        return ()
    if not isinstance(brut, (list, tuple)) or len(brut) > _MOTS_CLES_MAX:
        raise ProfilInvalide(f"{contexte} : 'mots_cles' doit être une liste d'au plus {_MOTS_CLES_MAX} termes")
    termes: list[str] = []
    for terme in brut:
        if not isinstance(terme, str) or not terme.strip():
            raise ProfilInvalide(f"{contexte} : chaque mot-clé doit être une chaîne non vide")
        termes.append(terme.strip())
    return tuple(termes)


def _normaliser_entree(entree: Any, position: int) -> Service:
    contexte = f"services[{position}]"
    if isinstance(entree, Service):
        if entree.code in _PAR_CODE_CATALOGUE:
            entree = entree.code
        else:
            entree = {"code": entree.code, "libelle": entree.libelle, "mots_cles": list(entree.mots_cles)}
    if isinstance(entree, str):
        code = _valider_code(entree, contexte)
        if code not in _PAR_CODE_CATALOGUE:
            raise ProfilInvalide(
                f"{contexte} : '{code}' n'est pas dans le catalogue de référence "
                f"({', '.join(codes_catalogue())}) ; pour un service propre, déclare un objet "
                "{code, libelle}"
            )
        return _PAR_CODE_CATALOGUE[code]
    if not isinstance(entree, Mapping):
        raise ProfilInvalide(f"{contexte} : un code du catalogue ou un objet {{code, libelle}} est attendu")
    inconnues = sorted(set(entree) - {"code", "libelle", "mots_cles"})
    if inconnues:
        raise ProfilInvalide(f"{contexte} : clés inconnues {inconnues} (attendu : code, libelle, mots_cles)")
    code = _valider_code(entree.get("code"), contexte)
    if code in _PAR_CODE_CATALOGUE:
        raise ProfilInvalide(
            f"{contexte} : '{code}' est un code du catalogue de référence ; déclare-le par son seul "
            "code (une liste de chaînes), pas comme service propre"
        )
    libelle = entree.get("libelle")
    if not isinstance(libelle, str) or not libelle.strip() or len(libelle) > _LIBELLE_MAX:
        raise ProfilInvalide(
            f"{contexte} : 'libelle' doit être une chaîne non vide d'au plus {_LIBELLE_MAX} caractères"
        )
    return Service(code, libelle.strip(), _valider_mots_cles(entree.get("mots_cles"), contexte))


def normaliser_services(entrees: Iterable[Any]) -> tuple[Service, ...]:
    """Valide une déclaration de services (codes du catalogue, objets, ou `Service`) et la rend
    normalisée. Refuse la liste vide et les doublons : une déclaration vide n'est pas un profil."""
    if isinstance(entrees, (str, bytes, Mapping)) or not isinstance(entrees, Iterable):
        raise ProfilInvalide(f"'{CLE_SERVICES}' doit être une liste")
    services = tuple(_normaliser_entree(entree, i) for i, entree in enumerate(entrees))
    if not services:
        raise ProfilInvalide(f"'{CLE_SERVICES}' est vide : déclare au moins un service")
    codes = [s.code for s in services]
    doublons = sorted({code for code in codes if codes.count(code) > 1})
    if doublons:
        raise ProfilInvalide(f"services déclarés en double : {doublons}")
    return services


def lire_services(chemin: Path | None = None) -> tuple[Service, ...]:
    """Services déclarés par le profil de l'instance ; `()` si le fichier ou la clé est absent.

    Lève `ProfilInvalide` si le fichier existe mais ne respecte pas le schéma : un profil cassé
    n'est jamais lu comme un profil vide.
    """
    fichier = chemin or fichier_profil()
    if not fichier.is_file():
        return ()
    try:
        donnees = yaml.safe_load(fichier.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ProfilInvalide(f"{fichier} illisible : {exc}") from exc
    if donnees is None:
        return ()
    if not isinstance(donnees, dict):
        raise ProfilInvalide(f"{fichier} : un objet YAML est attendu à la racine")
    if CLE_SERVICES not in donnees:
        return ()
    try:
        return normaliser_services(donnees[CLE_SERVICES])
    except ProfilInvalide as exc:
        raise ProfilInvalide(f"{fichier} : {exc}") from exc


def _verdict(code: str, detail: str) -> dict[str, str]:
    return {"code": code, "detail": detail}


def charger_services() -> tuple[tuple[Service, ...], dict[str, str] | None]:
    """`(services, None)` si l'instance en déclare au moins un, sinon `((), verdict)` qui dit quoi
    configurer. Ne lève jamais : un profil illisible est un verdict `REJ-PROFIL-INVALIDE`."""
    chemin = fichier_profil()
    try:
        services = lire_services(chemin)
    except ProfilInvalide as exc:
        return (), _verdict(VERDICT_PROFIL_INVALIDE, f"profil d'entreprise invalide : {exc}")
    if not services:
        return (), _verdict(
            VERDICT_SERVICE_NON_CONFIGURE,
            f"aucun service déclaré pour cette entreprise : {_consigne_configuration(chemin)}",
        )
    return services, None


def valider_service(
    code: Any, services: Iterable[Service] | None = None
) -> tuple[Service | None, dict[str, str] | None]:
    """`(service, None)` si `code` est un service déclaré, sinon `(None, verdict)`.

    `services` : la déclaration à confronter (tests, appelant qui l'a déjà lue) ; absente, le profil
    de l'instance est lu. Un code hors déclaration n'est JAMAIS remplacé par une valeur de repli.
    """
    if services is None:
        declares, verdict = charger_services()
        if verdict is not None:
            return None, verdict
    else:
        declares = tuple(services)
        if not declares:
            return None, _verdict(
                VERDICT_SERVICE_NON_CONFIGURE,
                f"aucun service déclaré pour cette entreprise : {_consigne_configuration(fichier_profil())}",
            )
    if not isinstance(code, str) or not code.strip():
        return None, _verdict(VERDICT_SERVICE_INVALIDE, "le service doit être un code non vide")
    for service in declares:
        if service.code == code:
            return service, None
    return None, _verdict(
        VERDICT_SERVICE_INCONNU,
        f"service {code!r} non déclaré pour cette entreprise (services déclarés : "
        f"{', '.join(s.code for s in declares)}) ; pour l'ajouter, modifie {fichier_profil()} "
        f"(clé '{CLE_SERVICES}')",
    )


def enregistrer_services(
    services: Iterable[Any], chemin: Path | None = None, par: str | None = None
) -> Path:
    """Écrit les services validés dans le profil, sans toucher aux autres clés du fichier.

    Signé par `par`, le changement est inscrit au journal d'audit (même patron que les paliers).
    """
    propres = normaliser_services(services)
    fichier = chemin or fichier_profil()
    existant: dict[str, Any] = {}
    if fichier.is_file():
        try:
            lu = yaml.safe_load(fichier.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            raise ProfilInvalide(f"{fichier} illisible : {exc} ; corrige-le ou supprime-le avant de déclarer") from exc
        if isinstance(lu, dict):
            existant = lu
    serialises: list[Any] = []
    for service in propres:
        if service.code in _PAR_CODE_CATALOGUE:
            serialises.append(service.code)
        else:
            objet: dict[str, Any] = {"code": service.code, "libelle": service.libelle}
            if service.mots_cles:
                objet["mots_cles"] = list(service.mots_cles)
            serialises.append(objet)
    existant[CLE_SERVICES] = serialises
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fichier.write_text(yaml.safe_dump(existant, allow_unicode=True, sort_keys=True), encoding="utf-8")
    if par:
        from .etat import journaliser, session

        with session() as cnx:
            journaliser(cnx, par, "entreprise.services", str(fichier), {"services": [s.code for s in propres]})
    return fichier


def normaliser_zone_desservie(villes: Any) -> tuple[str, ...]:
    """Valide une zone desservie : une liste non vide de villes (texte, sans doublon à la casse près).

    Refuse la liste vide : une zone vide n'est pas une zone, c'est l'absence de déclaration.
    """
    if isinstance(villes, (str, bytes, Mapping)) or not isinstance(villes, Iterable):
        raise ProfilInvalide(f"'{CLE_ZONE}' doit être une liste de villes")
    propres: list[str] = []
    for position, ville in enumerate(villes):
        if not isinstance(ville, str) or not ville.strip() or len(ville.strip()) > _VILLE_MAX:
            raise ProfilInvalide(
                f"{CLE_ZONE}[{position}] : une ville est une chaîne non vide d'au plus {_VILLE_MAX} caractères"
            )
        propres.append(ville.strip())
    if not propres:
        raise ProfilInvalide(f"'{CLE_ZONE}' est vide : déclare au moins une ville")
    if len(propres) > _VILLES_MAX:
        raise ProfilInvalide(f"'{CLE_ZONE}' : {_VILLES_MAX} villes au plus")
    formes = [v.casefold() for v in propres]
    doublons = sorted({v for v, forme in zip(propres, formes, strict=True) if formes.count(forme) > 1})
    if doublons:
        raise ProfilInvalide(f"'{CLE_ZONE}' : villes déclarées en double : {doublons}")
    return tuple(propres)


def lire_zone_desservie(chemin: Path | None = None) -> tuple[str, ...]:
    """Villes déclarées par le profil de l'instance ; `()` si le fichier ou la clé est absent.

    Lève `ProfilInvalide` si le fichier existe mais ne respecte pas le schéma (même règle que
    `lire_services` : un profil cassé n'est jamais lu comme un profil vide).
    """
    fichier = chemin or fichier_profil()
    if not fichier.is_file():
        return ()
    try:
        donnees = yaml.safe_load(fichier.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ProfilInvalide(f"{fichier} illisible : {exc}") from exc
    if donnees is None:
        return ()
    if not isinstance(donnees, dict):
        raise ProfilInvalide(f"{fichier} : un objet YAML est attendu à la racine")
    if CLE_ZONE not in donnees:
        return ()
    try:
        return normaliser_zone_desservie(donnees[CLE_ZONE])
    except ProfilInvalide as exc:
        raise ProfilInvalide(f"{fichier} : {exc}") from exc


def charger_zone_desservie() -> tuple[tuple[str, ...], dict[str, str] | None]:
    """`(villes, None)` si l'instance déclare sa zone, sinon `((), verdict)` qui dit où la déclarer.
    Ne lève jamais : un profil illisible est un verdict `REJ-PROFIL-INVALIDE`."""
    chemin = fichier_profil()
    try:
        villes = lire_zone_desservie(chemin)
    except ProfilInvalide as exc:
        return (), _verdict(VERDICT_PROFIL_INVALIDE, f"profil d'entreprise invalide : {exc}")
    if not villes:
        return (), _verdict(
            VERDICT_ZONE_NON_CONFIGUREE,
            f"aucune zone desservie déclarée pour cette entreprise : liste les villes où elle intervient "
            f"dans {chemin} (clé '{CLE_ZONE}') ; aucune ville n'est reconnue tant qu'elle est absente",
        )
    return villes, None


def _ecrire_cle_du_profil(
    cle: str, valeur: Any, chemin: Path | None, par: str | None, action: str, details: dict[str, Any]
) -> Path:
    """Écrit une clé dans le profil sans toucher aux autres ; signée par `par`, elle est inscrite au journal d'audit."""
    fichier = chemin or fichier_profil()
    existant: dict[str, Any] = {}
    if fichier.is_file():
        try:
            lu = yaml.safe_load(fichier.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            raise ProfilInvalide(f"{fichier} illisible : {exc} ; corrige-le ou supprime-le avant de déclarer") from exc
        if isinstance(lu, dict):
            existant = lu
    existant[cle] = valeur
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fichier.write_text(yaml.safe_dump(existant, allow_unicode=True, sort_keys=True), encoding="utf-8")
    if par:
        from .etat import journaliser, session

        with session() as cnx:
            journaliser(cnx, par, action, str(fichier), details)
    return fichier


def enregistrer_zone_desservie(villes: Any, chemin: Path | None = None, par: str | None = None) -> Path:
    """Écrit la zone validée dans le profil, sans toucher aux autres clés du fichier (services compris).

    Signée par `par`, la modification est inscrite au journal d'audit (même patron que les services).
    """
    propres = normaliser_zone_desservie(villes)
    return _ecrire_cle_du_profil(CLE_ZONE, list(propres), chemin, par, "entreprise.zone_desservie",
                                 {"villes": list(propres)})


def normaliser_fenetre_conversation(minutes: Any) -> int:
    """Valide la fenêtre de conversation : un nombre entier de minutes, d'au moins 1 et d'au plus sept jours.

    Refuse le texte, le décimal, le booléen et le zéro : une durée mal écrite n'est jamais arrondie ni devinée.
    """
    if isinstance(minutes, bool) or not isinstance(minutes, int):
        raise ProfilInvalide(f"'{CLE_FENETRE_CONVERSATION}' doit être un nombre entier de minutes (reçu {minutes!r})")
    if not 1 <= minutes <= FENETRE_CONVERSATION_MAX_MINUTES:
        raise ProfilInvalide(
            f"'{CLE_FENETRE_CONVERSATION}' : entre 1 et {FENETRE_CONVERSATION_MAX_MINUTES} minutes (reçu {minutes})"
        )
    return minutes


def lire_fenetre_conversation(chemin: Path | None = None) -> int | None:
    """Minutes déclarées par le profil de l'instance ; `None` si le fichier ou la clé est absent.

    Lève `ProfilInvalide` si la clé existe mais n'est pas une durée valide (même règle que la zone : une valeur
    cassée n'est jamais lue comme absente).
    """
    fichier = chemin or fichier_profil()
    if not fichier.is_file():
        return None
    try:
        donnees = yaml.safe_load(fichier.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ProfilInvalide(f"{fichier} illisible : {exc}") from exc
    if donnees is None:
        return None
    if not isinstance(donnees, dict):
        raise ProfilInvalide(f"{fichier} : un objet YAML est attendu à la racine")
    if CLE_FENETRE_CONVERSATION not in donnees:
        return None
    try:
        return normaliser_fenetre_conversation(donnees[CLE_FENETRE_CONVERSATION])
    except ProfilInvalide as exc:
        raise ProfilInvalide(f"{fichier} : {exc}") from exc


def charger_fenetre_conversation() -> tuple[int | None, dict[str, str] | None]:
    """`(minutes, None)` si l'instance déclare sa fenêtre, sinon `(None, verdict)` qui dit où la déclarer.
    Ne lève jamais : une valeur illisible est un verdict `REJ-PROFIL-INVALIDE`, distinct de l'absence
    (`REJ-FENETRE-NON-CONFIGUREE`), que l'appelant peut tolérer sans jamais confondre les deux."""
    chemin = fichier_profil()
    try:
        minutes = lire_fenetre_conversation(chemin)
    except ProfilInvalide as exc:
        return None, _verdict(VERDICT_PROFIL_INVALIDE, f"profil d'entreprise invalide : {exc}")
    if minutes is None:
        return None, _verdict(
            VERDICT_FENETRE_NON_CONFIGUREE,
            f"aucune fenêtre de conversation déclarée : donne sa durée en minutes dans {chemin} "
            f"(clé '{CLE_FENETRE_CONVERSATION}') ; tant qu'elle est absente, la qualification se fait "
            "message par message (un service dans un message et la ville dans le suivant ne se rejoignent pas)",
        )
    return minutes, None


def enregistrer_fenetre_conversation(minutes: Any, chemin: Path | None = None, par: str | None = None) -> Path:
    """Écrit la fenêtre validée dans le profil, sans toucher aux autres clés (services et zone compris).
    Signée par `par`, elle est inscrite au journal d'audit."""
    propre = normaliser_fenetre_conversation(minutes)
    return _ecrire_cle_du_profil(CLE_FENETRE_CONVERSATION, propre, chemin, par, "entreprise.fenetre_conversation",
                                 {"minutes": propre})


def _valeur_du_profil(cle: str, fichier: Path) -> Any:
    """La valeur brute de `cle` dans le profil, ou `None` si le fichier, sa racine vide ou la clé est absent.

    Lève `ProfilInvalide` si le fichier est illisible ou n'a pas d'objet YAML à la racine : un profil cassé n'est
    jamais lu comme un profil vide.
    """
    if not fichier.is_file():
        return None
    try:
        donnees = yaml.safe_load(fichier.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise ProfilInvalide(f"{fichier} illisible : {exc}") from exc
    if donnees is None:
        return None
    if not isinstance(donnees, dict):
        raise ProfilInvalide(f"{fichier} : un objet YAML est attendu à la racine")
    return donnees.get(cle)


def _normaliser_question(entree: Any, contexte: str) -> QuestionQualification:
    if isinstance(entree, QuestionQualification):
        entree = {"code": entree.code, "question": entree.question, "mots_cles": list(entree.mots_cles),
                  "photos": entree.photos}
    if not isinstance(entree, Mapping):
        raise ProfilInvalide(f"{contexte} : un objet {{code, question, mots_cles}} est attendu")
    inconnues = sorted(set(entree) - {"code", "question", "mots_cles", "photos"})
    if inconnues:
        raise ProfilInvalide(f"{contexte} : clés inconnues {inconnues} (attendu : code, question, mots_cles, photos)")
    code = _valider_code(entree.get("code"), contexte)
    question = entree.get("question")
    if (
        not isinstance(question, str) or not question.strip() or len(question.strip()) > _QUESTION_MAX
        or _CARACTERE_DE_CONTROLE.search(question)
    ):
        raise ProfilInvalide(
            f"{contexte} : 'question' doit être un texte d'une ligne, non vide, d'au plus {_QUESTION_MAX} caractères "
            "(c'est ce que M1 propose au client)"
        )
    photos = entree.get("photos", False)
    if not isinstance(photos, bool):
        raise ProfilInvalide(f"{contexte} : 'photos' doit valoir true ou false")
    mots_cles = _valider_mots_cles(entree.get("mots_cles"), contexte)
    if photos and mots_cles:
        raise ProfilInvalide(
            f"{contexte} : une question de photos ne se reconnaît pas par des mots-clés (le texte du client ne "
            "remplace pas une photo) ; retire 'mots_cles'"
        )
    if not photos and not mots_cles:
        raise ProfilInvalide(
            f"{contexte} : 'mots_cles' requis (les termes qui montrent que le client a répondu) ; sans eux, le code "
            "ne pourrait jamais reconnaître la réponse et la question resterait posée indéfiniment"
        )
    return QuestionQualification(code, question.strip(), mots_cles, photos)


def normaliser_questions_qualification(brut: Any) -> dict[str, tuple[QuestionQualification, ...]]:
    """Valide les questions obligatoires : `{code_du_service: [questions]}`, chaque question `{code, question,
    mots_cles}` (ou `photos: true`). Refuse la déclaration vide, la liste vide, le doublon de code et la question
    dont le code ne pourrait jamais être reconnu : une déclaration vide n'est pas une déclaration."""
    if not isinstance(brut, Mapping):
        raise ProfilInvalide(f"'{CLE_QUESTIONS_QUALIFICATION}' doit être un objet {{code_du_service: [questions]}}")
    if not brut:
        raise ProfilInvalide(f"'{CLE_QUESTIONS_QUALIFICATION}' est vide : déclare au moins une question")
    propres: dict[str, tuple[QuestionQualification, ...]] = {}
    for service, liste in brut.items():
        contexte = f"{CLE_QUESTIONS_QUALIFICATION}[{service!r}]"
        _valider_code(service, contexte)
        if isinstance(liste, (str, bytes, Mapping)) or not isinstance(liste, Iterable):
            raise ProfilInvalide(f"{contexte} : une liste de questions est attendue")
        questions = tuple(_normaliser_question(q, f"{contexte}[{i}]") for i, q in enumerate(liste))
        if not questions:
            raise ProfilInvalide(f"{contexte} est vide : déclare au moins une question, ou retire ce service")
        if len(questions) > _QUESTIONS_PAR_SERVICE_MAX:
            raise ProfilInvalide(f"{contexte} : {_QUESTIONS_PAR_SERVICE_MAX} questions au plus par service")
        codes = [q.code for q in questions]
        doublons = sorted({c for c in codes if codes.count(c) > 1})
        if doublons:
            raise ProfilInvalide(f"{contexte} : questions déclarées en double : {doublons}")
        propres[service] = questions
    return propres


def lire_questions_qualification(chemin: Path | None = None) -> dict[str, tuple[QuestionQualification, ...]]:
    """Questions déclarées par le profil de l'instance ; `{}` si le fichier ou la clé est absent ou vide.

    Lève `ProfilInvalide` si des questions sont écrites mais ne respectent pas le schéma (même règle que la zone :
    une valeur cassée n'est jamais lue comme absente)."""
    fichier = chemin or fichier_profil()
    valeur = _valeur_du_profil(CLE_QUESTIONS_QUALIFICATION, fichier)
    if valeur is None or valeur == {}:
        return {}
    try:
        return normaliser_questions_qualification(valeur)
    except ProfilInvalide as exc:
        raise ProfilInvalide(f"{fichier} : {exc}") from exc


def _verdict_questions_absentes(chemin: Path, service: str | None) -> dict[str, str]:
    pour = "" if service is None else f" pour le service {service!r}"
    return _verdict(
        VERDICT_QUESTIONS_NON_CONFIGUREES,
        f"aucune question de qualification déclarée{pour} : écris, par service, les questions obligatoires dans "
        f"{chemin} (clé '{CLE_QUESTIONS_QUALIFICATION}') ; M1 ne pose que ce que l'entreprise déclare, jamais une "
        "liste par défaut",
    )


def charger_questions_qualification() -> tuple[dict[str, tuple[QuestionQualification, ...]], dict[str, str] | None]:
    """`(questions, None)` si l'instance en déclare, sinon `({}, verdict)` qui dit où les déclarer.
    Ne lève jamais : une valeur illisible est un verdict `REJ-PROFIL-INVALIDE`, distinct de l'absence."""
    chemin = fichier_profil()
    try:
        questions = lire_questions_qualification(chemin)
    except ProfilInvalide as exc:
        return {}, _verdict(VERDICT_PROFIL_INVALIDE, f"profil d'entreprise invalide : {exc}")
    if not questions:
        return {}, _verdict_questions_absentes(chemin, None)
    return questions, None


def charger_questions_du_service(service: str) -> tuple[tuple[QuestionQualification, ...], dict[str, str] | None]:
    """Les questions obligatoires d'UN service : `(questions, None)`, ou `((), verdict)` quand le profil n'en déclare
    aucune pour lui (`REJ-QUESTIONS-NON-CONFIGUREES`, qui nomme le service) ou qu'il est invalide
    (`REJ-PROFIL-INVALIDE`). Aucune question n'est jamais inventée pour un service sans déclaration."""
    questions, verdict = charger_questions_qualification()
    if verdict is not None and verdict["code"] != VERDICT_QUESTIONS_NON_CONFIGUREES:
        return (), verdict
    if service not in questions:
        return (), _verdict_questions_absentes(fichier_profil(), service)
    return questions[service], None


def _serialiser_questions(
    questions: Mapping[str, tuple[QuestionQualification, ...]],
) -> dict[str, list[dict[str, Any]]]:
    serialisees: dict[str, list[dict[str, Any]]] = {}
    for service, liste in questions.items():
        objets = []
        for q in liste:
            objet: dict[str, Any] = {"code": q.code, "question": q.question}
            if q.mots_cles:
                objet["mots_cles"] = list(q.mots_cles)
            if q.photos:
                objet["photos"] = True
            objets.append(objet)
        serialisees[service] = objets
    return serialisees


def enregistrer_questions_qualification(questions: Any, chemin: Path | None = None, par: str | None = None) -> Path:
    """Écrit les questions validées dans le profil, sans toucher aux autres clés (services, zone, fenêtre, poids).
    Signées par `par`, elles sont inscrites au journal d'audit (le nombre de questions par service, pas leur texte)."""
    propres = normaliser_questions_qualification(questions)
    return _ecrire_cle_du_profil(
        CLE_QUESTIONS_QUALIFICATION, _serialiser_questions(propres), chemin, par, "entreprise.questions_qualification",
        {"questions_par_service": {service: len(liste) for service, liste in propres.items()}},
    )


def normaliser_poids_score_lead(brut: Any) -> dict[str, int]:
    """Valide les poids du score de lead : un entier de 0 à `POIDS_SCORE_LEAD_MAX` pour CHAQUE critère, au moins un
    positif. Refuse le critère inconnu, le poids manquant (0 l'écarte, explicitement), le texte, le décimal et le
    booléen : un poids mal écrit n'est jamais arrondi ni deviné."""
    if not isinstance(brut, Mapping):
        raise ProfilInvalide(f"'{CLE_POIDS_SCORE_LEAD}' doit être un objet {{critère: poids}}")
    inconnus = sorted(str(c) for c in set(brut) - set(CRITERES_SCORE_LEAD))
    if inconnus:
        raise ProfilInvalide(
            f"'{CLE_POIDS_SCORE_LEAD}' : critères inconnus {inconnus} (attendu : {', '.join(CRITERES_SCORE_LEAD)})"
        )
    manquants = [c for c in CRITERES_SCORE_LEAD if c not in brut]
    if manquants:
        raise ProfilInvalide(
            f"'{CLE_POIDS_SCORE_LEAD}' : poids manquants {manquants} ; donne un poids entier à chaque critère "
            "(0 pour en écarter un)"
        )
    poids: dict[str, int] = {}
    for critere in CRITERES_SCORE_LEAD:
        valeur = brut[critere]
        if isinstance(valeur, bool) or not isinstance(valeur, int) or not 0 <= valeur <= POIDS_SCORE_LEAD_MAX:
            raise ProfilInvalide(
                f"'{CLE_POIDS_SCORE_LEAD}.{critere}' : un entier de 0 à {POIDS_SCORE_LEAD_MAX} est attendu "
                f"(reçu {valeur!r})"
            )
        poids[critere] = valeur
    if not any(poids.values()):
        raise ProfilInvalide(f"'{CLE_POIDS_SCORE_LEAD}' : au moins un poids doit être positif")
    return poids


def lire_poids_score_lead(chemin: Path | None = None) -> dict[str, int] | None:
    """Poids déclarés par le profil de l'instance ; `None` s'ils sont absents ou vides (« à configurer »).

    Lève `ProfilInvalide` si des poids sont écrits mais invalides : jamais lus comme absents."""
    fichier = chemin or fichier_profil()
    valeur = _valeur_du_profil(CLE_POIDS_SCORE_LEAD, fichier)
    if valeur is None or valeur == {}:
        return None
    try:
        return normaliser_poids_score_lead(valeur)
    except ProfilInvalide as exc:
        raise ProfilInvalide(f"{fichier} : {exc}") from exc


def charger_poids_score_lead() -> tuple[dict[str, int] | None, dict[str, str] | None]:
    """`(poids, None)` si l'instance déclare ses poids, sinon `(None, verdict)` : « poids à configurer », et aucun
    score n'est calculé. Ne lève jamais : des poids invalides sont un verdict `REJ-PROFIL-INVALIDE`."""
    chemin = fichier_profil()
    try:
        poids = lire_poids_score_lead(chemin)
    except ProfilInvalide as exc:
        return None, _verdict(VERDICT_PROFIL_INVALIDE, f"profil d'entreprise invalide : {exc}")
    if poids is None:
        return None, _verdict(
            VERDICT_POIDS_SCORE_NON_CONFIGURES,
            f"poids à configurer : donne un poids entier (de 0 à {POIDS_SCORE_LEAD_MAX}) à chacun des critères "
            f"{', '.join(CRITERES_SCORE_LEAD)} dans {chemin} (clé '{CLE_POIDS_SCORE_LEAD}') ; tant qu'ils sont "
            "absents, aucun score de lead n'est calculé",
        )
    return poids, None


def enregistrer_poids_score_lead(poids: Any, chemin: Path | None = None, par: str | None = None) -> Path:
    """Écrit les poids validés dans le profil, sans toucher aux autres clés. Signés par `par`, ils sont inscrits au
    journal d'audit."""
    propres = normaliser_poids_score_lead(poids)
    return _ecrire_cle_du_profil(CLE_POIDS_SCORE_LEAD, propres, chemin, par, "entreprise.poids_score_lead",
                                 {"poids": propres})


def normaliser_signaux_plainte(brut: Any) -> dict[str, tuple[str, ...]]:
    """Valide le vocabulaire des plaintes : `{catégorie: [termes]}`, catégories de `CATEGORIES_SIGNAL_PLAINTE`.

    Une catégorie déclarée porte au moins un terme ; chaque terme est un texte d'une ligne (de `_TERME_SIGNAL_MIN` à
    `_TERME_SIGNAL_MAX` caractères : un terme trop court reconnaîtrait n'importe quoi), sans doublon dans sa catégorie.
    Une catégorie absente n'est pas une erreur : elle ne reconnaît rien, et M1 le dit. Une déclaration vide n'est pas
    une déclaration. Les termes suivent les mêmes règles de lecture que les mots-clés d'un service (mot entier,
    pluriel admis, accents et casse ignorés ; plusieurs mots : une expression).
    """
    if not isinstance(brut, Mapping):
        raise ProfilInvalide(f"'{CLE_SIGNAUX_PLAINTE}' doit être un objet {{catégorie: [termes]}}")
    if not brut:
        raise ProfilInvalide(f"'{CLE_SIGNAUX_PLAINTE}' est vide : déclare au moins une catégorie de termes")
    inconnues = sorted(str(c) for c in set(brut) - set(CATEGORIES_SIGNAL_PLAINTE))
    if inconnues:
        raise ProfilInvalide(
            f"'{CLE_SIGNAUX_PLAINTE}' : catégories inconnues {inconnues} "
            f"(attendu : {', '.join(CATEGORIES_SIGNAL_PLAINTE)})"
        )
    propres: dict[str, tuple[str, ...]] = {}
    for categorie in CATEGORIES_SIGNAL_PLAINTE:
        if categorie not in brut:
            continue
        contexte = f"{CLE_SIGNAUX_PLAINTE}.{categorie}"
        termes = brut[categorie]
        if isinstance(termes, (str, bytes, Mapping)) or not isinstance(termes, Iterable):
            raise ProfilInvalide(f"{contexte} : une liste de termes est attendue")
        propres_termes: list[str] = []
        for position, terme in enumerate(termes):
            if not isinstance(terme, str) or _CARACTERE_DE_CONTROLE.search(terme):
                raise ProfilInvalide(f"{contexte}[{position}] : un terme d'une ligne (texte) est attendu")
            nettoye = " ".join(terme.split())
            if not _TERME_SIGNAL_MIN <= len(nettoye) <= _TERME_SIGNAL_MAX:
                raise ProfilInvalide(
                    f"{contexte}[{position}] : un terme de {_TERME_SIGNAL_MIN} à {_TERME_SIGNAL_MAX} caractères est "
                    f"attendu (reçu {terme!r}) ; un terme trop court reconnaîtrait des mots sans rapport"
                )
            propres_termes.append(nettoye)
        if not propres_termes:
            raise ProfilInvalide(f"{contexte} est vide : déclare au moins un terme, ou retire cette catégorie")
        if len(propres_termes) > _TERMES_PAR_CATEGORIE_MAX:
            raise ProfilInvalide(f"{contexte} : {_TERMES_PAR_CATEGORIE_MAX} termes au plus par catégorie")
        doublons = sorted({t for t in propres_termes if [x.casefold() for x in propres_termes].count(t.casefold()) > 1})
        if doublons:
            raise ProfilInvalide(f"{contexte} : termes déclarés en double : {doublons}")
        propres[categorie] = tuple(propres_termes)
    return propres


def lire_signaux_plainte(chemin: Path | None = None) -> dict[str, tuple[str, ...]]:
    """Vocabulaire déclaré par le profil de l'instance ; `{}` si le fichier ou la clé est absent ou vide.

    Lève `ProfilInvalide` si un vocabulaire est écrit mais invalide : jamais lu comme absent."""
    fichier = chemin or fichier_profil()
    valeur = _valeur_du_profil(CLE_SIGNAUX_PLAINTE, fichier)
    if valeur is None or valeur == {}:
        return {}
    try:
        return normaliser_signaux_plainte(valeur)
    except ProfilInvalide as exc:
        raise ProfilInvalide(f"{fichier} : {exc}") from exc


def charger_signaux_plainte() -> tuple[dict[str, tuple[str, ...]], dict[str, str] | None]:
    """`(vocabulaire, None)` si l'instance en déclare un, sinon `({}, verdict)` : « vocabulaire à configurer », et M1
    ne reconnaît alors aucune plainte (il le dit, il n'invente aucun mot). Ne lève jamais : un vocabulaire invalide est
    un verdict `REJ-PROFIL-INVALIDE`, distinct de l'absence."""
    chemin = fichier_profil()
    try:
        signaux = lire_signaux_plainte(chemin)
    except ProfilInvalide as exc:
        return {}, _verdict(VERDICT_PROFIL_INVALIDE, f"profil d'entreprise invalide : {exc}")
    if not signaux:
        return {}, _verdict(
            VERDICT_SIGNAUX_PLAINTE_NON_CONFIGURES,
            f"vocabulaire des plaintes à configurer : écris, par catégorie ({', '.join(CATEGORIES_SIGNAL_PLAINTE)}), "
            f"les termes qui signalent une plainte ou une urgence de sécurité dans {chemin} (clé "
            f"'{CLE_SIGNAUX_PLAINTE}') ; tant qu'ils sont absents, M1 ne reconnaît aucune plainte et n'en invente "
            "aucun",
        )
    return signaux, None


def enregistrer_signaux_plainte(signaux: Any, chemin: Path | None = None, par: str | None = None) -> Path:
    """Écrit le vocabulaire validé dans le profil, sans toucher aux autres clés. Signé par `par`, il est inscrit au
    journal d'audit (le nombre de termes par catégorie)."""
    propres = normaliser_signaux_plainte(signaux)
    return _ecrire_cle_du_profil(
        CLE_SIGNAUX_PLAINTE, {categorie: list(termes) for categorie, termes in propres.items()}, chemin, par,
        "entreprise.signaux_plainte", {"termes_par_categorie": {c: len(t) for c, t in propres.items()}},
    )


def normaliser_destinataires_transfert(brut: Any) -> dict[str, str]:
    """Valide la table « type de transfert -> rôle » : les clés sont des `TYPES_TRANSFERT`, les valeurs des rôles de
    `ROLES_DESTINATAIRES_TRANSFERT`. Une table partielle est permise (un type sans rôle reste « à configurer »). Une
    déclaration vide, un type inconnu, un rôle inconnu ou réservé au client ou à l'agent : refusés."""
    if not isinstance(brut, Mapping):
        raise ProfilInvalide(f"'{CLE_DESTINATAIRES_TRANSFERT}' doit être un objet {{type de transfert: rôle}}")
    if not brut:
        raise ProfilInvalide(f"'{CLE_DESTINATAIRES_TRANSFERT}' est vide : déclare au moins un type de transfert")
    inconnus = sorted(str(t) for t in set(brut) - set(TYPES_TRANSFERT))
    if inconnus:
        raise ProfilInvalide(
            f"'{CLE_DESTINATAIRES_TRANSFERT}' : types de transfert inconnus {inconnus} (attendu : "
            f"{', '.join(TYPES_TRANSFERT)})"
        )
    propres: dict[str, str] = {}
    for type_transfert in TYPES_TRANSFERT:
        if type_transfert not in brut:
            continue
        role = brut[type_transfert]
        if not isinstance(role, str) or role not in ROLES_DESTINATAIRES_TRANSFERT:
            raise ProfilInvalide(
                f"'{CLE_DESTINATAIRES_TRANSFERT}.{type_transfert}' : un rôle parmi "
                f"{', '.join(ROLES_DESTINATAIRES_TRANSFERT)} est attendu (reçu {role!r})"
            )
        propres[type_transfert] = role
    return propres


def lire_destinataires_transfert(chemin: Path | None = None) -> dict[str, str]:
    """Table « type -> rôle » déclarée par le profil ; `{}` si absente ou vide (chaque type est alors « à configurer »).

    Lève `ProfilInvalide` si elle est écrite mais invalide : jamais lue comme absente."""
    fichier = chemin or fichier_profil()
    valeur = _valeur_du_profil(CLE_DESTINATAIRES_TRANSFERT, fichier)
    if valeur is None or valeur == {}:
        return {}
    try:
        return normaliser_destinataires_transfert(valeur)
    except ProfilInvalide as exc:
        raise ProfilInvalide(f"{fichier} : {exc}") from exc


def charger_destinataire_du_transfert(type_transfert: str) -> tuple[str | None, dict[str, str] | None]:
    """Le rôle qui reçoit un transfert de ce type : `(rôle, None)`, ou `(None, verdict)` quand le profil n'en déclare
    aucun pour lui (`REJ-DESTINATAIRE-NON-CONFIGURE` : « destinataire à configurer », qui nomme le type) ou qu'il est
    invalide (`REJ-PROFIL-INVALIDE`). Aucun destinataire n'est jamais deviné. Un type qui n'est pas de
    `TYPES_TRANSFERT` est une erreur de l'appelant (`ValueError`)."""
    if type_transfert not in TYPES_TRANSFERT:
        raise ValueError(f"type de transfert inconnu {type_transfert!r} (attendu : {', '.join(TYPES_TRANSFERT)})")
    chemin = fichier_profil()
    try:
        table = lire_destinataires_transfert(chemin)
    except ProfilInvalide as exc:
        return None, _verdict(VERDICT_PROFIL_INVALIDE, f"profil d'entreprise invalide : {exc}")
    if type_transfert not in table:
        return None, _verdict(
            VERDICT_DESTINATAIRE_NON_CONFIGURE,
            f"destinataire à configurer pour le transfert de type {type_transfert!r} : déclare le rôle qui le reçoit "
            f"({', '.join(ROLES_DESTINATAIRES_TRANSFERT)}) dans {chemin} (clé '{CLE_DESTINATAIRES_TRANSFERT}') ; "
            "M1 ne choisit jamais une personne à la place du propriétaire",
        )
    return table[type_transfert], None


def enregistrer_destinataires_transfert(table: Any, chemin: Path | None = None, par: str | None = None) -> Path:
    """Écrit la table validée dans le profil, sans toucher aux autres clés. Signée par `par`, elle est inscrite au
    journal d'audit (qui reçoit quoi : ce sont des rôles, jamais des noms de personnes)."""
    propres = normaliser_destinataires_transfert(table)
    return _ecrire_cle_du_profil(
        CLE_DESTINATAIRES_TRANSFERT, dict(propres), chemin, par, "entreprise.destinataires_transfert",
        {"destinataires": dict(propres)},
    )


def verifier_profil() -> list[str]:
    """`opsys-metier verifier` : un profil présent doit être valide. Un profil absent n'est pas une erreur
    (l'instance n'a simplement encore déclaré aucun service, et tout service est alors refusé)."""
    problemes: list[str] = []
    lectures = (
        lire_services, lire_zone_desservie, lire_fenetre_conversation, lire_questions_qualification,
        lire_poids_score_lead, lire_signaux_plainte, lire_destinataires_transfert,
    )
    for lecture in lectures:
        try:
            lecture()
        except ProfilInvalide as exc:
            if str(exc) not in problemes:  # un fichier illisible échoue à chaque lecture : un seul message
                problemes.append(str(exc))
    try:
        services, questions = lire_services(), lire_questions_qualification()
    except ProfilInvalide:
        return problemes  # déjà signalé ci-dessus
    if services:
        declares = {s.code for s in services}
        for service in sorted(set(questions) - declares):
            problemes.append(
                f"{fichier_profil()} : '{CLE_QUESTIONS_QUALIFICATION}' porte des questions pour '{service}', "
                f"que l'entreprise ne déclare pas (services déclarés : {', '.join(sorted(declares))})"
            )
    return problemes


def copies_locales_du_catalogue(racines: Iterable[Path]) -> list[str]:
    """`opsys-metier verifier` : garde de dérive. Cherche, dans les sources Python sous `racines`, une
    collection littérale (tuple, liste, ensemble, clés d'un dict) qui porte au moins DEUX codes du
    catalogue de référence : c'est une copie locale de la taxonomie, qui dériverait en silence.

    Le fichier de ce module est exclu (il est le catalogue). Les tests ne sont pas scannés : seuls
    les chemins passés le sont (les `src/` des départements et du socle). Une source illisible ou
    non analysable est signalée, jamais ignorée.
    """
    codes = set(codes_catalogue())
    ici = Path(__file__).resolve()
    problemes: list[str] = []
    for racine in racines:
        for fichier in sorted(Path(racine).rglob("*.py")):
            if fichier.resolve() == ici:
                continue
            try:
                arbre = ast.parse(fichier.read_text(encoding="utf-8"), filename=str(fichier))
            except (OSError, UnicodeDecodeError, SyntaxError) as exc:
                problemes.append(f"{fichier} : source non analysable ({exc}), garde de dérive non probante")
                continue
            for noeud in ast.walk(arbre):
                if isinstance(noeud, (ast.Tuple, ast.List, ast.Set)):
                    elements = noeud.elts
                elif isinstance(noeud, ast.Dict):
                    elements = [cle for cle in noeud.keys if cle is not None]
                else:
                    continue
                trouves = {
                    e.value for e in elements if isinstance(e, ast.Constant) and isinstance(e.value, str)
                } & codes
                if len(trouves) >= 2:
                    problemes.append(
                        f"{fichier}:{noeud.lineno} : copie locale du catalogue de services {sorted(trouves)} ; "
                        "lis `opsys.taxonomie` au lieu de recopier la liste"
                    )
    return problemes
