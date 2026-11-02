"""Adaptateur des outils de BARÈME et de MESURE déclarés (M3-C1 et M3-C2) : seul endroit où ils touchent le socle.

Les modules purs (``bareme_registre``, ``mesure_declaree``, ``entrees_declarees``) ignorent d'où viennent l'auteur,
l'heure et les maillons. Cet adaptateur les leur fournit :

- l'AUTEUR est l'identité d'appareil authentifiée par OPSYS-CORE ou la session de la console, revérifiée en base
  (``approbations.signataire_valide``) : une personne qui existe, est active et porte encore le rôle. Un agent
  (Hermes, Claude Code, un outil interne) n'a aucune identité d'appareil : il peut LIRE, jamais déclarer un barème
  ni une mesure. Un vendeur ne déclare la mesure que d'un lead dont il est propriétaire (M2, relu à la source) ;
- l'HEURE est celle du serveur (``opsys.horloge``), jamais un argument : un agent qui choisirait l'heure choisirait le
  barème en vigueur ;
- les registres sont ``stockage.maillons("m03-estimation", "bareme" | "mesures_declarees")`` (aucune migration) ;
- l'écriture d'une personne est sérialisée (``verrou_ecriture_console``) et rejouée sur une écriture concurrente.

VOIE DE COMPATIBILITÉ (``voie_libre_autorisee``) : les tests et les appels existants passent encore ``bareme``,
``quantite`` et ``plancher_rentable`` en arguments libres. Cette voie n'est ouverte QUE si l'environnement du serveur
pose ``OPSYS_M3_VOIE_LIBRE=essai`` ET que l'appel ne vient pas du transport MCP (celui de tout agent). Ni l'un ni
l'autre ne se décide par les arguments : un agent ne peut ni poser une variable d'environnement du serveur ni
cesser de venir du MCP.
Hors de cette voie, un barème libre est refusé (``REJ-BAREME-LIBRE-REFUSE``), une absence de référence aussi
(``REJ-BAREME-REFERENCE-REQUISE``), dans les deux cas avec ce qu'il faut déclarer. Mêlée à une référence, une valeur
libre
est refusée : elle ne vient jamais « corriger » le barème déclaré.
"""

from __future__ import annotations

import os
from decimal import Decimal
from typing import Any

from opsys import approbations, contexte, horloge, stockage, taxonomie
from opsys.outils import Autonomie, Outil
from opsys.stockage.concurrence import verrou_ecriture_console

from . import (
    bareme_registre,
    conditions_soumission,
    contrats,
    entrees_declarees,
    estimation,
    mesure_declaree,
    registre,
    verdicts,
)

__all__ = [
    "ENV_VOIE_LIBRE",
    "VALEUR_VOIE_LIBRE",
    "arguments_libres_presents",
    "conditions_pour_devis",
    "construire_declaration",
    "outils_bareme",
    "plancher_declare",
    "seuils_revue_declares",
    "simuler_declare",
    "verdict_voie_libre_refusee",
    "voie_libre_autorisee",
]

_DEPARTEMENT = "m03-estimation"
ENV_VOIE_LIBRE = "OPSYS_M3_VOIE_LIBRE"
VALEUR_VOIE_LIBRE = "essai"
_ROLE_VENDEUR = "seller"

_MESSAGE_A_DECLARER = (
    "À faire : 1) le propriétaire déclare le barème de l'entreprise (m3_declarer_bareme : lignes avec source "
    "écrite, plancher rentable, taux de marge), 2) une personne déclare la mesure du chantier (m3_declarer_mesure : "
    "valeur, unité, bornes basse et haute, méthode, confiance, pièces), 3) rappeler m3_estimer_projet avec "
    "bareme_ref {bareme_id, version} et mesure_ref {mesure_id}. Le barème, la quantité, le plancher rentable et les "
    "taux de marge ne se passent plus en arguments libres."
)


def voie_libre_autorisee() -> bool:
    """Vrai seulement pour un serveur d'essai (variable d'environnement) ET un appel qui ne vient pas du MCP."""
    return os.environ.get(ENV_VOIE_LIBRE) == VALEUR_VOIE_LIBRE and not contexte.appel_provient_du_mcp()


def arguments_libres_presents(**arguments: Any) -> list[str]:
    """Les noms des arguments libres (barème, quantité, plancher, taux) effectivement fournis."""
    return sorted(nom for nom, valeur in arguments.items() if valeur is not None)


def verdict_voie_libre_refusee(libres: list[str], *, avec_reference: bool) -> dict:
    """Le refus d'un appel qui passe des valeurs libres, ou qui ne référence aucun barème, hors de la voie d'essai."""
    if libres and avec_reference:
        return verdicts.construire_verdict(
            "REJ-BAREME-LIBRE-REFUSE",
            detail=(
                f"valeurs libres refusées avec une référence de barème : {libres}. Le barème, la quantité, le plancher "
                "rentable et les taux viennent des déclarations référencées, jamais d'un argument qui les corrigerait. "
                "À faire : retirer ces arguments"
            ),
        )
    if libres:
        return verdicts.construire_verdict(
            "REJ-BAREME-LIBRE-REFUSE",
            detail=f"valeurs libres refusées en exploitation : {libres}. " + _MESSAGE_A_DECLARER,
        )
    return verdicts.construire_verdict(
        "REJ-BAREME-REFERENCE-REQUISE", detail="aucune référence de barème fournie. " + _MESSAGE_A_DECLARER
    )


def journal_bareme() -> Any:
    return stockage.maillons(_DEPARTEMENT, bareme_registre.REGISTRE)


def journal_mesures() -> Any:
    return stockage.maillons(_DEPARTEMENT, mesure_declaree.REGISTRE)


def construire_declaration(bareme_ref: Any, mesure_ref: Any) -> entrees_declarees.Declaration:
    """La déclaration d'une estimation : les deux registres de l'instance et l'heure du serveur."""
    return entrees_declarees.Declaration(
        journal_bareme(), journal_mesures(), bareme_ref, mesure_ref, horloge.maintenant()
    )


def plancher_declare(bareme_ref: Any) -> tuple[float | None, dict | None]:
    """Le plancher rentable déclaré par la version de barème en vigueur que ``bareme_ref`` désigne."""
    version, verdict = bareme_registre.resoudre(journal_bareme(), bareme_ref, horloge.maintenant())
    if verdict is not None:
        return None, verdict
    plancher = version["parametres"].get("plancher_rentable_cad")
    if plancher is None:
        return None, verdicts.construire_verdict(
            "REJ-BAREME-INCOMPLET",
            detail=(
                f"la version {version['version']} du barème {version['bareme_id']!r} ne déclare pas de plancher "
                "rentable (parametres.plancher_rentable_cad) : le propriétaire le déclare dans une révision "
                "(m3_declarer_bareme)"
            ),
        )
    return float(Decimal(plancher)), None


def simuler_declare(bareme_ref: Any, mesure_ref: Any, type_travaux: Any, niveau: float) -> dict[str, Any]:
    """L'enveloppe de coût d'une mesure déclarée avec un barème en vigueur (aucune écriture, graine dérivée)."""
    mesure, verdict = mesure_declaree.resoudre_sans_lead(journal_mesures(), mesure_ref)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    service = type_travaux if type_travaux is not None else mesure["service"]
    declare, verdict = construire_declaration(bareme_ref, mesure_ref).preparer(mesure["lead_id"], service)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    graine = estimation.graine_stable(declare["bareme"], service, declare["quantite"])
    intervalle, verdict = estimation.enveloppe_de_mesure(
        declare["bareme"], service, declare["quantite_basse"], declare["quantite_haute"], graine, niveau
    )
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return {"accepte": True, "resultat": {
        "intervalle": intervalle, "bareme_ref": declare["bareme_ref"], "mesure_ref": declare["mesure_ref"],
        "quantite": declare["evaluation"]["quantite"], "statut_mesure": declare["evaluation"]["statut"],
    }}


# -- identité humaine ----------------------------------------------------------------------------------------------
def _auteur_humain(roles: frozenset[str], code: str) -> tuple[dict[str, str] | None, dict | None]:
    """L'auteur d'une déclaration : une personne authentifiée, active, qui porte encore un des rôles admis."""
    cnx = stockage.connexion_courante()
    appelante = contexte.identite_appelante()
    signataire = approbations.signataire_valide(cnx, appelante) if cnx is not None else None
    if signataire is None or signataire.role not in roles:
        return None, verdicts.construire_verdict(
            code,
            detail=(
                "cette déclaration est faite par une personne (rôles admis : " + ", ".join(sorted(roles)) + ") "
                "authentifiée sur son appareil ou dans la console, jamais par un agent. Rien n'a été écrit"
            ),
        )
    return {"personne": signataire.personne, "role": signataire.role}, None


def _horodatage() -> str:
    return horloge.maintenant().isoformat(timespec="seconds")


def _rejouer_si_concurrent(operation: Any) -> Any:
    for _ in range(2):
        try:
            return operation()
        except stockage.EcritureConcurrente:
            continue
    return operation()


def _journaliser(cnx: Any, auteur: dict[str, str], action: str, cible: str, details: dict[str, Any]) -> None:
    from opsys.etat import journaliser

    journaliser(cnx, auteur["personne"], action, cible, details)


# -- barème --------------------------------------------------------------------------------------------------------
def _services_declares(lignes: Any) -> dict | None:
    """Chaque service nommé par une ligne est un type de travaux v1 ou un service déclaré par l'entreprise."""
    if not isinstance(lignes, list):
        return None
    for ligne in lignes:
        service = ligne.get("service") if isinstance(ligne, dict) else None
        if isinstance(service, str) and service not in contrats.TYPES_TRAVAUX:
            _, verdict = taxonomie.valider_service(service)
            if verdict is not None:
                return verdicts.construire_verdict(
                    "REJ-BAREME-INVALIDE",
                    detail=f"ligne de service {service!r} : {verdict['code']} : {verdict['detail']}",
                )
    return None


def _resume_version(version: dict[str, Any], rejoue: bool | None = None) -> dict[str, Any]:
    resume = {
        "bareme_ref": bareme_registre.reference_de(version),
        "date_effet": version["date_effet"],
        "valide_jusqu_au": version["valide_jusqu_au"],
        "a_valider": version["a_valider"],
        "valide": version["valide"],
        "nombre_lignes": len(version["lignes"]),
        "services": sorted({ligne["service"] for ligne in version["lignes"] if ligne["genre"] == "ouvrage"}),
        "plancher_rentable_declare": "plancher_rentable_cad" in version["parametres"],
        "declaree_par": version["auteur"]["personne"],
        "declaree_le": version["horodatage"],
    }
    if rejoue is not None:
        resume["rejoue"] = rejoue
    return resume


def declarer_bareme(
    bareme_id: str, version_attendue: int, lignes: list[dict[str, Any]], date_effet: str,
    valide_jusqu_au: str | None = None, a_valider: bool = False, parametres: dict[str, Any] | None = None,
    soumission: dict[str, Any] | None = None,
) -> dict[str, Any]:
    auteur, verdict = _auteur_humain(bareme_registre.ROLES_AUTEUR, "REJ-BAREME-IDENTITE")
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    verdict = _services_declares(lignes)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    cnx = stockage.connexion_courante()
    verrou_ecriture_console(cnx)

    def ecrire() -> dict[str, Any]:
        with cnx.begin_nested():
            resultat, refus = bareme_registre.declarer_version(
                journal_bareme(), bareme_id=bareme_id, version_attendue=version_attendue, lignes=lignes,
                parametres=parametres, soumission=soumission, date_effet=date_effet,
                valide_jusqu_au=valide_jusqu_au, a_valider=a_valider, auteur=auteur, horodatage=_horodatage(),
            )
            if refus is not None:
                return {"accepte": False, "verdict": refus}
            version = resultat["version"]
            if not resultat["rejoue"]:
                _journaliser(cnx, auteur, "m3.bareme_declare", version["empreinte"],
                             {"bareme_id": bareme_id, "version": version["version"]})
            return {"accepte": True, "resultat": _resume_version(version, resultat["rejoue"])}

    return _rejouer_si_concurrent(ecrire)


def valider_bareme(bareme_id: str, version: int) -> dict[str, Any]:
    auteur, verdict = _auteur_humain(bareme_registre.ROLES_AUTEUR, "REJ-BAREME-IDENTITE")
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    cnx = stockage.connexion_courante()
    verrou_ecriture_console(cnx)

    def ecrire() -> dict[str, Any]:
        with cnx.begin_nested():
            resultat, refus = bareme_registre.valider_version(
                journal_bareme(), bareme_id=bareme_id, version=version, auteur=auteur, horodatage=_horodatage(),
            )
            if refus is not None:
                return {"accepte": False, "verdict": refus}
            valide = resultat["version"]
            if not resultat["rejoue"]:
                _journaliser(cnx, auteur, "m3.bareme_valide", valide["empreinte"],
                             {"bareme_id": bareme_id, "version": version})
            return {"accepte": True, "resultat": _resume_version(valide, resultat["rejoue"])}

    return _rejouer_si_concurrent(ecrire)


def lire_bareme(bareme_id: str, version: int = 0, service: str | None = None) -> dict[str, Any]:
    publique, verdict = bareme_registre.lire_version(journal_bareme(), bareme_id, version)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    if service is not None:
        publique = {**publique, "lignes": [ligne for ligne in publique["lignes"] if ligne["service"] == service]}
    return {"accepte": True, "resultat": publique}


def lister_baremes() -> dict[str, Any]:
    baremes, verdict = bareme_registre.lister(journal_bareme(), horloge.maintenant())
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return {"accepte": True, "resultat": {"baremes": baremes}}


# -- mesure --------------------------------------------------------------------------------------------------------
def _proprietaire_du_lead(lead_id: Any) -> str | None:
    from . import outils  # import tardif : outils importe ce module pour déclarer les outils

    return outils._proprietaire_du_lead(lead_id)


def declarer_mesure(
    mesure_id: str, revision_attendue: int, lead_id: str, service: str, grandeur: str, valeur: str, unite: str,
    borne_basse: str, borne_haute: str, methode: str, confiance: str, mesure_le: str, pieces: list[str],
) -> dict[str, Any]:
    auteur, verdict = _auteur_humain(mesure_declaree.ROLES_AUTEUR, "REJ-MESURE-IDENTITE")
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    if auteur["role"] == _ROLE_VENDEUR and _proprietaire_du_lead(lead_id) != auteur["personne"]:
        return {"accepte": False, "verdict": verdicts.construire_verdict(
            "REJ-MESURE-IDENTITE",
            detail="un vendeur ne déclare la mesure que d'un lead dont il est propriétaire. Rien n'a été écrit",
        )}
    cnx = stockage.connexion_courante()
    verrou_ecriture_console(cnx)

    def ecrire() -> dict[str, Any]:
        with cnx.begin_nested():
            resultat, refus = mesure_declaree.declarer(
                journal_mesures(), mesure_id=mesure_id, revision_attendue=revision_attendue, lead_id=lead_id,
                service=service, grandeur=grandeur, valeur=valeur, unite=unite, borne_basse=borne_basse,
                borne_haute=borne_haute, methode=methode, confiance=confiance, mesure_le=mesure_le, pieces=pieces,
                auteur=auteur, horodatage=_horodatage(),
            )
            if refus is not None:
                return {"accepte": False, "verdict": refus}
            mesure = resultat["mesure"]
            if not resultat["rejoue"]:
                _journaliser(cnx, auteur, "m3.mesure_declaree", mesure["empreinte"],
                             {"mesure_id": mesure_id, "revision": mesure["revision"], "lead_id": lead_id})
            return {"accepte": True, "resultat": {**mesure, "rejoue": resultat["rejoue"]}}

    return _rejouer_si_concurrent(ecrire)


def lire_mesure(mesure_id: str, revision: int = 0) -> dict[str, Any]:
    mesure, verdict = mesure_declaree.lire(journal_mesures(), mesure_id, revision)
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return {"accepte": True, "resultat": mesure}


# -- conditions de soumission ---------------------------------------------------------------------------------------
def conditions_pour_devis(
    devis: dict[str, Any], charge: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, dict | None]:
    """Les sections déclarées (exclusions, hypothèses, délai, validité) d'un devis à estimation source déclarée.

    ``charge`` : la charge de l'estimation source au registre (``None`` : devis sans source, rien à composer). La
    version de barème et la révision de mesure sont celles que l'estimation CITE, même remplacées depuis."""
    bloc = charge.get("declaration") if isinstance(charge, dict) else None
    if bloc is None:
        return None, None
    version, verdict = bareme_registre.resoudre(
        journal_bareme(), bloc["bareme_ref"], horloge.maintenant(), exiger_en_vigueur=False
    )
    if verdict is not None:
        return None, verdict
    mesure, verdict = mesure_declaree.resoudre_sans_lead(journal_mesures(), bloc["mesure_ref"])
    if verdict is not None:
        return None, verdict
    return conditions_soumission.composer(
        version_bareme=version, mesure=mesure, duree_estimee_minutes=bloc.get("duree_estimee_minutes"),
        horodatage_devis=devis["horodatage"],
    )


def seuils_revue_declares(bloc: dict[str, Any]) -> tuple[dict[str, Any] | None, dict | None]:
    """Les seuils de revue d'un devis (``parametres.seuils_revue``) du barème que l'estimation source CITE.

    Version exacte (même remplacée depuis) : la revue d'un devis juge selon le barème avec lequel il a été chiffré."""
    version, verdict = bareme_registre.resoudre(
        journal_bareme(), bloc["bareme_ref"], horloge.maintenant(), exiger_en_vigueur=False
    )
    if verdict is not None:
        return None, verdict
    return dict(version["parametres"].get("seuils_revue", {})), None


# -- rejeu ---------------------------------------------------------------------------------------------------------
def rejouer_estimation(estimation_id: str) -> dict[str, Any]:
    """Refait le calcul d'une estimation déclarée (``hash_maillon`` rendu par ``m3_estimer_projet``) depuis la
    version de barème et la révision de mesure qu'elle cite, et confronte le résultat à l'intervalle gardé."""
    journal = registre.Registre(stockage.maillons(_DEPARTEMENT, "principal"))
    valide, raison = journal.valider_chaine()
    if not valide:
        return {"accepte": False, "verdict": verdicts.construire_verdict(
            "REJ-REJEU-IMPOSSIBLE", detail=f"le registre des estimations est altéré ({raison}) : rejeu refusé")}
    charge = next(
        (m["charge"] for m in journal.lire() if isinstance(m, dict) and m.get("hash_maillon") == estimation_id), None
    )
    if charge is None:
        return {"accepte": False, "verdict": verdicts.construire_verdict(
            "REJ-REJEU-IMPOSSIBLE", detail=f"aucune estimation {estimation_id!r} au registre")}
    rapport, verdict = entrees_declarees.rejouer(charge, journal_bareme(), journal_mesures(), horloge.maintenant())
    if verdict is not None:
        return {"accepte": False, "verdict": verdict}
    return {"accepte": True, "resultat": {"estimation_id": estimation_id, **rapport}}


# -- déclaration des outils ----------------------------------------------------------------------------------------
def _schema(proprietes: dict[str, Any], requis: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": proprietes, "required": requis, "additionalProperties": False}


_TEXTE_DECIMAL = {"type": "string", "pattern": r"^[0-9]{1,9}(\.[0-9]{1,6})?$"}
_INSTANT = {"type": "string", "description": "ISO 8601 avec fuseau, ex. 2026-11-02T00:00:00-05:00"}
_LIGNE_BAREME = {
    "type": "object",
    "description": (
        "Une ligne du barème. genre ouvrage : cout_unitaire_min, cout_unitaire_max, cout_unitaire_mode (facultatif), "
        "duree_minutes_par_unite (facultatif), textes décimaux ; semantique_temps (facultatif) : seule la valeur "
        "duree_ecoulee_intervention. genre materiau : quantite_par_unite, taux_perte "
        "(facultatif, 0.10 pour 10 %), sku (facultatif). Toujours : service, element, unite, source_ecrite."
    ),
    "properties": {
        "service": {"type": "string"}, "genre": {"type": "string", "enum": ["ouvrage", "materiau"]},
        "element": {"type": "string"}, "unite": {"type": "string"}, "source_ecrite": {"type": "string"},
        "cout_unitaire_min": _TEXTE_DECIMAL, "cout_unitaire_max": _TEXTE_DECIMAL, "cout_unitaire_mode": _TEXTE_DECIMAL,
        "duree_minutes_par_unite": _TEXTE_DECIMAL, "quantite_par_unite": _TEXTE_DECIMAL,
        "semantique_temps": {"type": "string", "enum": ["duree_ecoulee_intervention"]},
        "taux_perte": _TEXTE_DECIMAL, "sku": {"type": "string"},
    },
    "required": ["service", "genre", "element", "unite", "source_ecrite"],
    "additionalProperties": False,
}


def outils_bareme() -> tuple[Outil, ...]:
    ident = {"type": "string", "minLength": 1, "maxLength": 200}
    entier = {"type": "integer", "minimum": 0}
    return (
        Outil(
            nom="m3_declarer_bareme",
            description=(
                "Déclare une version du barème de l'entreprise (lignes avec source écrite, plancher rentable, taux "
                "de marge, seuils, textes de soumission). Réservé à une PERSONNE authentifiée (propriétaire ou admin) "
                ": un agent est refusé, rien n'est inventé. Révision = nouvelle version, l'ancienne reste lisible. "
                "a_valider=true : valeur de départ tirée d'une source écrite, inutilisable avant m3_valider_bareme."
            ),
            parametres=_schema({
                "bareme_id": ident, "version_attendue": entier, "lignes": {"type": "array", "items": _LIGNE_BAREME},
                "date_effet": _INSTANT, "valide_jusqu_au": {"type": ["string", "null"]},
                "a_valider": {"type": "boolean"}, "parametres": {"type": ["object", "null"]},
                "soumission": {"type": ["object", "null"]},
            }, ["bareme_id", "version_attendue", "lignes", "date_effet"]),
            fonction=declarer_bareme,
            autonomie=Autonomie.T1,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m3_valider_bareme",
            description=(
                "Le propriétaire (ou un admin) valide une version de barème déclarée « à valider ». Sans cette "
                "validation la version n'est pas utilisable par une estimation. Refusé à un agent."
            ),
            parametres=_schema({"bareme_id": ident, "version": {"type": "integer", "minimum": 1}},
                               ["bareme_id", "version"]),
            fonction=valider_bareme,
            autonomie=Autonomie.T1,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m3_lire_bareme",
            description=(
                "Lit une version de barème (0 = la dernière) avec son empreinte, son état de validation et ses "
                "lignes ; service limite les lignes à un service. Lecture seule."
            ),
            parametres=_schema({"bareme_id": ident, "version": entier, "service": {"type": ["string", "null"]}},
                               ["bareme_id"]),
            fonction=lire_bareme,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m3_lister_baremes",
            description=(
                "Liste les barèmes déclarés, leurs versions et celle en vigueur maintenant : c'est la source du "
                "bareme_ref à passer à m3_estimer_projet. Lecture seule."
            ),
            parametres=_schema({}, []),
            fonction=lister_baremes,
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m3_declarer_mesure",
            description=(
                "Déclare la mesure d'un chantier : valeur, unité (celle du barème), bornes basse et haute, méthode, "
                "confiance, pièces (références de photos ou de plans). Réservé à une PERSONNE (propriétaire, admin, ou "
                "vendeur propriétaire du lead) : un agent est refusé. Révision = nouvelle révision, l'ancienne reste "
                "lisible. Aucune vision requise."
            ),
            parametres=_schema({
                "mesure_id": ident, "revision_attendue": entier, "lead_id": ident, "service": ident,
                "grandeur": {"type": "string", "maxLength": 80}, "valeur": _TEXTE_DECIMAL, "unite": {"type": "string"},
                "borne_basse": _TEXTE_DECIMAL, "borne_haute": _TEXTE_DECIMAL,
                "methode": {"type": "string", "enum": mesure_declaree.methodes()},
                "confiance": {"type": "string", "enum": ["faible", "moyenne", "elevee"]},
                "mesure_le": _INSTANT,
                "pieces": {"type": "array", "items": ident, "maxItems": mesure_declaree.MAX_PIECES},
            }, ["mesure_id", "revision_attendue", "lead_id", "service", "grandeur", "valeur", "unite", "borne_basse",
                "borne_haute", "methode", "confiance", "mesure_le", "pieces"]),
            fonction=declarer_mesure,
            autonomie=Autonomie.T1,
            roles_appareil=frozenset({"seller", "admin"}),
        ),
        Outil(
            nom="m3_lire_mesure",
            description="Lit une mesure déclarée (0 = la dernière révision) avec son auteur, sa méthode et ses bornes.",
            parametres=_schema({"mesure_id": ident, "revision": entier}, ["mesure_id"]),
            fonction=lire_mesure,
            roles_appareil=frozenset({"seller", "admin"}),
        ),
        Outil(
            nom="m3_rejouer_estimation",
            description=(
                "Rejoue le calcul d'une estimation déclarée (estimation_id = hash_maillon rendu par m3_estimer_projet) "
                "avec la version de barème et la révision de mesure qu'elle cite, même si une révision les a "
                "remplacées, et confronte le résultat à l'intervalle gardé. Lecture seule."
            ),
            parametres=_schema({"estimation_id": {"type": "string", "pattern": "^[0-9a-f]{64}$"}}, ["estimation_id"]),
            fonction=rejouer_estimation,
        ),
    )
