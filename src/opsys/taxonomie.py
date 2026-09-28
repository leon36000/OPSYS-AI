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

NOM_FICHIER_PROFIL = "entreprise.yaml"
CLE_SERVICES = "services"

# Codes de verdict émis par ce module (jamais un booléen nu : le détail dit quoi corriger).
VERDICT_SERVICE_NON_CONFIGURE = "REJ-SERVICE-NON-CONFIGURE"
VERDICT_SERVICE_INCONNU = "REJ-SERVICE-INCONNU"
VERDICT_SERVICE_INVALIDE = "REJ-SERVICE-INVALIDE"
VERDICT_PROFIL_INVALIDE = "REJ-PROFIL-INVALIDE"

_FORME_CODE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_LIBELLE_MAX = 120
_MOTS_CLES_MAX = 20


class ProfilInvalide(ValueError):
    """Le profil d'entreprise est illisible ou ne respecte pas le schéma (le message dit quoi corriger)."""


@dataclass(frozen=True)
class Service:
    """Un service offert : code stable (contrat inter-départements), libellé fr-CA, et les termes
    qui l'évoquent dans une demande (`mots_cles`, utilisés par la qualification de M1)."""

    code: str
    libelle: str
    mots_cles: tuple[str, ...] = ()


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


def verifier_profil() -> list[str]:
    """`opsys verifier` : un profil présent doit être valide. Un profil absent n'est pas une erreur
    (l'instance n'a simplement encore déclaré aucun service, et tout service est alors refusé)."""
    try:
        lire_services()
    except ProfilInvalide as exc:
        return [str(exc)]
    return []


def copies_locales_du_catalogue(racines: Iterable[Path]) -> list[str]:
    """`opsys verifier` : garde de dérive. Cherche, dans les sources Python sous `racines`, une
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
