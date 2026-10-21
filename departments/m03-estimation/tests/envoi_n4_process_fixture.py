"""Processus réels pour la composition « réponse N4 perdue APRÈS COMMIT, puis nouveau processus ».

Module d'aide (pas un module de test) : il est exécuté comme SCRIPT par deux processus OS distincts (rôles `A` et
`B`) et importé par le test pour piloter ces processus, lire la base par une connexion SQLite indépendante
(`mode=ro`) et contrôler la cible A. Données, personnes, leads, barème et montants : FICTIFS.

- `A` migre une base SQLite neuve, crée un devis sourcé par le chemin réel M2 (readiness) -> M3 (estimation) ->
  `m3_creer_devis`, propose l'envoi N4 par `Capacites.appeler` avec un ticket de session M10 émis par
  `liaison_cibles.emettre_ticket`, puis le propriétaire approuve par `approbations_appareil.decider_demande` dans
  un `stockage.transaction` externe. Le `with` sort (COMMIT SQLite fait) AVANT toute perte : seulement ensuite, sur
  ordre du parent, la réponse de décision est perdue par une exception nommée levée HORS transaction.
- `B` est un autre processus sur la MÊME base : il reconstruit manifestes, `Capacites`, registres et consommateurs,
  rejoue la demande d'origine (même ticket, mêmes arguments) et la décision d'origine, livre `m3.devis_envoye` au vrai
  consommateur durable de M2 par `evenements.repartir` (deux fois), puis fait approuver un devis B neuf.

Aucun SQL n'écrit de fait métier dans la base du scénario ; les seules écritures SQL de ce module visent une COPIE
jetable, pour le contrôle négatif de sensibilité (`muter_copie`). Un délai dépassé est une panne de mise en place,
jamais un oracle métier. Aucun serveur, réseau, fournisseur ni envoi réel au client.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import importlib
import json
import os
import queue
import re
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path
from typing import Any
from urllib.parse import quote

FICTIF = True

_TESTS = Path(__file__).resolve().parent
RACINE_M3 = _TESTS.parent
RACINE_DEPARTEMENTS = RACINE_M3.parent
RACINE_DEPOT = RACINE_DEPARTEMENTS.parent

DEP = "m03-estimation"
M2 = "m02-revenue-crm"
NOM = "m3_demander_envoi_devis"
TYPE_ENVOYE = "m3.devis_envoye"
PROPRIETAIRE = "proprio"
_MOT_DE_PASSE = "un-mot-de-passe-suffisamment-long"
_HORODATAGE_DEVIS = "2026-09-29T14:00:00-04:00"
LEAD_A = "lead-postcommit-a-fictif"
LEAD_B = "lead-postcommit-b-fictif"
APPAREIL_A = "tel-fictif-postcommit-a"
APPAREIL_REJEU = "tel-fictif-postcommit-rejeu"
APPAREIL_B = "tel-fictif-postcommit-b"
CONTEXTE_REVUE = {
    "niveau_confiance_hierarchie": "MONO_VUE_BORNES_LARGES",
    "verdict_estimation": "AUCUN_BLOCAGE",
    "alerte_plancher": False,
    "service_complexe": False,
    "client_a_risque": False,
    "distance_km": "80",
    "donnees_fournisseur_completes": True,
}

PREFIXE = "@@ENVOI-N4@@ "
EXIT_REPONSE_PERDUE = 23
EXIT_ARRET = 75
EXIT_EXCEPTION = 70
DELAI_GLOBAL_S = 150.0
DELAI_HORLOGE_S = 3.0


class EchecMiseEnPlace(RuntimeError):
    """Panne de mise en place (processus, délai, prérequis non observé) : jamais un verdict métier."""


class ReponsePerdueApresCommit(ConnectionError):
    """Seam de test : la réponse de décision est perdue APRÈS la sortie réussie de la transaction."""


class ArretDemande(RuntimeError):
    """STOP explicite ou EOF de stdin : le processus possédé s'arrête sans rien écrire de plus."""


class ProvenanceIncoherente(AssertionError):
    """Sources d'un enfant hors des racines déclarées ou d'empreinte différente : jamais un verdict métier."""


# -- identité de processus --------------------------------------------------------------------------------
def ticks_demarrage(pid: int) -> int | None:
    """Instant de démarrage (`/proc/<pid>/stat`, champ 22) ; None si le processus n'existe plus."""
    try:
        texte = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return None
    return int(texte[texte.rindex(")") + 2:].split()[19])


def identite_courante() -> dict[str, int]:
    return {"pid": os.getpid(), "ticks": ticks_demarrage(os.getpid())}


def source_chargee() -> dict[str, Any]:
    """Reçu de l'enfant : racines déclarées depuis CE fichier, puis chaque module M3/socle réellement chargé (chemin
    résolu + SHA-256), après import des vrais `outils` et `devis_durable` — pas le seul `__init__`."""
    for nom in _MODULES_EXIGES:
        importlib.import_module(nom)
    modules = {}
    for nom, module in sorted(sys.modules.items()):
        if nom.partition(".")[0] not in (_PAQUET_M3, _PAQUET_SOCLE):
            continue
        fichier = getattr(module, "__file__", None)
        chemin = Path(fichier).resolve(strict=True) if fichier else None
        modules[nom] = {"path": str(chemin or ""), "sha256": _empreinte(chemin) if chemin else ""}
    return {"version": PROVENANCE_VERSION, "roots": racines_declarees(RACINE_M3 / "src", RACINE_DEPOT / "src"),
            "modules": modules}


# -- provenance : M3 copie stricte, socle partagé déclaré (lexical + résolu), empreintes ---------------------------
PROVENANCE_VERSION = 1
_PAQUET_M3, _PAQUET_SOCLE = "m3_estimation", "opsys"
_MODULES_EXIGES = ("opsys", "m3_estimation", "m3_estimation.outils", "m3_estimation.devis_durable")
_CLES_RACINES = {"m3_declared", "shared_src_declared", "shared_src_resolved"}


def _empreinte(chemin: Path) -> str:
    return hashlib.sha256(chemin.read_bytes()).hexdigest()


def racines_declarees(racine_m3_src: Path, socle_src: Path) -> dict[str, str]:
    """Racines DÉCLARÉES, jamais déduites du module chargé : `src` de M3 doit être un vrai dossier (copie stricte,
    pas un lien) ; le socle garde son chemin logique et sa cible réelle (`resolve(strict=True)`)."""
    racine_m3_src, socle_src = Path(racine_m3_src).absolute(), Path(socle_src).absolute()
    if racine_m3_src.resolve(strict=True) != racine_m3_src:
        raise ProvenanceIncoherente(f"M3_NON_STRICT : {racine_m3_src} passe par un lien")
    return {"m3_declared": str(racine_m3_src), "shared_src_declared": str(socle_src),
            "shared_src_resolved": str(socle_src.resolve(strict=True))}


def _modules_sous(racine: Path, paquet: str) -> dict[str, dict[str, str]]:
    modules = {}
    for fichier in sorted((racine / paquet).rglob("*.py")):
        parties = fichier.relative_to(racine).with_suffix("").parts
        nom = ".".join(parties[:-1] if parties[-1] == "__init__" else parties)
        modules[nom] = {"path": str(fichier.resolve(strict=True)), "sha256": _empreinte(fichier)}
    return modules


def sources_attendues(racine_m3_src: Path, socle_src: Path) -> dict[str, Any]:
    """Attentes du PARENT, capturées depuis les racines déclarées (même schéma que le reçu de l'enfant)."""
    racines = racines_declarees(racine_m3_src, socle_src)
    return {"version": PROVENANCE_VERSION, "roots": racines, "modules": {
        **_modules_sous(Path(racines["shared_src_resolved"]), _PAQUET_SOCLE),
        **_modules_sous(Path(racines["m3_declared"]), _PAQUET_M3)}}


def _chemin_valide(valeur: Any) -> bool:
    return isinstance(valeur, str) and Path(valeur).is_absolute() and ".." not in Path(valeur).parts


def _valider_recu(recu: Any, quoi: str) -> None:
    """Schéma exact (dict version 1 / roots / modules[nom] = {path, sha256}) et confinement aux racines."""
    if not isinstance(recu, dict) or set(recu) != {"version", "roots", "modules"}:
        raise ProvenanceIncoherente(f"SCHEMA : {quoi} n'est pas un dict {{version, roots, modules}} : {recu!r}")
    racines, modules = recu["roots"], recu["modules"]
    if type(recu["version"]) is not int or recu["version"] != PROVENANCE_VERSION:
        raise ProvenanceIncoherente(f"SCHEMA : {quoi}, version {recu['version']!r}")
    if not isinstance(racines, dict) or set(racines) != _CLES_RACINES or not all(map(_chemin_valide, racines.values())):
        raise ProvenanceIncoherente(f"SCHEMA : {quoi}, racines {racines!r}")
    if not isinstance(modules, dict) or not modules:
        raise ProvenanceIncoherente(f"SCHEMA : {quoi}, modules {modules!r}")
    confinement = {_PAQUET_M3: ("M3_HORS_COPIE", racines["m3_declared"]),
                   _PAQUET_SOCLE: ("OPSYS_HORS_SOCLE", racines["shared_src_resolved"])}
    for nom, entree in modules.items():
        if not (isinstance(nom, str) and nom.partition(".")[0] in confinement and isinstance(entree, dict)
                and set(entree) == {"path", "sha256"} and _chemin_valide(entree["path"])
                and isinstance(entree["sha256"], str) and re.fullmatch("[0-9a-f]{64}", entree["sha256"])):
            raise ProvenanceIncoherente(f"SCHEMA : {quoi}, module {nom!r} : {entree!r}")
        code, racine = confinement[nom.partition(".")[0]]
        if not Path(entree["path"]).is_relative_to(racine):
            raise ProvenanceIncoherente(f"{code} : {quoi}, {nom} chargé depuis {entree['path']}, hors de {racine}")


def controler_provenance_sources(sources: Any, attendues: Any) -> None:
    """Lève `ProvenanceIncoherente` si un reçu d'enfant diffère des attentes du parent (schéma, racines, chemin
    résolu ou SHA-256 d'un module chargé, modules exigés absents) ; ne rend rien sinon."""
    _valider_recu(attendues, "attentes du parent")
    if not isinstance(sources, (tuple, list)) or not sources:
        raise ProvenanceIncoherente(f"SCHEMA : reçus d'enfants {sources!r}")
    for rang, recu in enumerate(sources):
        quoi = f"reçu d'enfant n°{rang}"
        _valider_recu(recu, quoi)
        if recu["roots"] != attendues["roots"]:
            raise ProvenanceIncoherente(f"RACINES : {quoi} {recu['roots']} != {attendues['roots']}")
        if absents := [nom for nom in _MODULES_EXIGES if nom not in recu["modules"]]:
            raise ProvenanceIncoherente(f"MODULES_ABSENTS : {quoi} {absents}")
        for nom, entree in recu["modules"].items():
            attendu = attendues["modules"].get(nom)
            if attendu is None or attendu["path"] != entree["path"]:
                raise ProvenanceIncoherente(f"MODULE_NON_ATTENDU : {quoi}, {nom} chargé depuis {entree['path']}")
            if attendu["sha256"] != entree["sha256"]:
                raise ProvenanceIncoherente(f"EMPREINTE_MODIFIEE : {quoi}, {nom} ({entree['path']})")


# -- protocole enfant -----------------------------------------------------------------------------------
def emettre(etape: str, **donnees: Any) -> None:
    sys.stdout.write(PREFIXE + json.dumps({"etape": etape, **donnees}, ensure_ascii=False, default=str) + "\n")
    sys.stdout.flush()


def lire_commande() -> dict[str, Any]:
    ligne = sys.stdin.readline()
    if not ligne:
        raise ArretDemande("EOF de stdin")
    commande = json.loads(ligne)
    if commande.get("commande") == "STOP":
        raise ArretDemande("STOP")
    return commande


def _attendre_commande(nom: str) -> dict[str, Any]:
    commande = lire_commande()
    if commande.get("commande") != nom:
        raise EchecMiseEnPlace(f"commande {commande.get('commande')!r} reçue, {nom!r} attendue")
    return commande


# -- chemin métier réel (exécuté dans les processus enfants) -------------------------------------------------
def _outil(nom: str):
    from m3_estimation import outils as outils_m3

    return next(o for o in outils_m3.outils() if o.nom == nom)


def _creer_proprietaire() -> None:
    from opsys import identite, stockage

    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, PROPRIETAIRE, "Propriétaire (fictif)", _MOT_DE_PASSE, ["admin", "nathan_owner"])


def _lier_session(lead_id: str) -> str:
    """Liaison M10 d'une session d'agent M3 au lead M2 existant (résolveurs exigés par le ticket)."""
    from m2_revenue_crm import registre as registre_m2
    from m2_revenue_crm import statuts
    from m10_memoire import liaison as liaison_m10
    from m10_memoire import registre as registre_m10

    from opsys import stockage

    cle_session = f"agent:{DEP}:tests:{lead_id}"
    with stockage.transaction():
        reg_m2 = registre_m2.Registre(maillons=stockage.maillons(M2, "principal"))
        if statuts.statut_courant(reg_m2, lead_id) is None:
            raise EchecMiseEnPlace(f"lead M2 {lead_id} absent après la readiness")
        reg_m10 = registre_m10.Registre(maillons=stockage.maillons("m10-memoire", "affaires"))
        if liaison_m10.liaison_courante(cle_session, reg_m10) is None:
            _, refus = liaison_m10.lier_session_affaire(
                cle_session, lead_id, PROPRIETAIRE, "admin", "appareil", "liaison M3 de fixture fictive",
                _HORODATAGE_DEVIS, reg_m10,
            )
            if refus is not None:
                raise EchecMiseEnPlace(f"liaison M10 refusée : {refus}")
    return cle_session


def _creer_devis_source(lead_id: str) -> tuple[str, str]:
    """Readiness M2 réelle -> estimation M3 (photos valides : prix non bloqué) -> devis sourcé immuable."""
    from m2_preparation_estimation import marqueur_m2

    from opsys.outils import executer_atomique

    estimation = executer_atomique(_outil("m3_estimer_projet"), {
        "contrat": {"lead_id": lead_id, "conversation_id": f"conv-{lead_id}",
                    "type_travaux": "ravalement", "ville": "Quebec", "canal": "formulaire_web",
                    "contact": {"nom": "Client fictif", "telephone": "555-0101"},
                    "urgence_declaree": False},
        "marqueur": marqueur_m2(lead_id),
        "photos": [{"photo_id": "p-fictif", "resolution_largeur": 3000, "resolution_hauteur": 2000,
                    "eclairage": 7, "angle": "face",
                    "reference_echelle": {"type": "porte", "dimensions_connues": True}}],
        "seuils": {"resolution_minimale": 1000, "eclairage_minimal": 4},
        "bareme": {"version": "prix-fictifs-v1", "unite": "pi2",
                   "postes": {"ravalement": {"cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0}}},
        "quantite": 1, "plancher_rentable": 1, "graine": 42,
    })
    if not (estimation.get("ok") and estimation["resultat"].get("accepte")):
        raise EchecMiseEnPlace(f"estimation refusée : {estimation}")
    est = estimation["resultat"]["estimation"]
    if est["prix_bloque"] is not False:
        raise EchecMiseEnPlace("prix bloqué : hors de la composition visée")
    cree = executer_atomique(_outil("m3_creer_devis"), {
        "devis_id": est["devis_id"], "lead_id": lead_id, "chantier_id": None,
        "lignes": [{"description": "Forfait fictif manuel", "quantite": "1", "unite": "forfait",
                    "cout_unitaire": "4000.00", "reference_besoin_materiau": None}],
        "taux_marge": "0.35", "horodatage": _HORODATAGE_DEVIS, "estimation_source_hash": est["hash_maillon"],
    })
    if not (cree.get("ok") and cree["resultat"].get("accepte")):
        raise EchecMiseEnPlace(f"création du devis refusée : {cree}")
    return est["devis_id"], est["hash_maillon"]


def _etat_devis(devis_id: str) -> dict[str, Any]:
    from m3_estimation import outils as outils_m3

    from opsys import stockage

    with stockage.transaction():
        etat, verdict = outils_m3.devis_durable.lire_devis(outils_m3.registre_devis_production(), devis_id)
    if verdict is not None:
        raise EchecMiseEnPlace(f"devis {devis_id} illisible : {verdict}")
    return etat


def _resume_devis(etat: dict[str, Any]) -> dict[str, Any]:
    return {cle: (None if etat.get(cle) is None else str(etat[cle])) for cle in (
        "devis_id", "lead_id", "statut", "horodatage", "prix_total", "estimation_source_hash",
        "envoi_approuve_par", "envoi_approuve_role")}


def _demander(capacites, devis_id: str, lead_id: str) -> tuple[dict[str, Any], str, dict[str, Any]]:
    """Demande N4 d'une session d'agent liée, avec un ticket privé sur les arguments finaux."""
    from opsys import liaison_cibles, stockage

    arguments = {"devis_id": devis_id, "contexte_revue": dict(CONTEXTE_REVUE)}
    cle_session = _lier_session(lead_id)
    with stockage.transaction() as cnx:
        ticket = liaison_cibles.emettre_ticket(
            cnx, departement=DEP, agent_id=DEP, cle_session=cle_session, affaire_id=lead_id,
            origine_affaire="session", outil=NOM, arguments=arguments,
        )["ticket"]
    reponse = capacites.appeler(NOM, arguments, ticket_cible=liaison_cibles.TicketMeta(ticket))
    if reponse.get("statut") != "en_attente_approbation":
        raise EchecMiseEnPlace(f"demande N4 non mise en file : {reponse}")
    return arguments, ticket, reponse


def _decider(departements, demande_id: str, appareil: str):
    """Le helper `_decider_app` existant : décision d'app dans un `stockage.transaction` externe."""
    from opsys import approbations_appareil, contexte, stockage

    proprio = contexte.IdentiteAppelante(personne=PROPRIETAIRE, role="admin")
    with stockage.transaction() as cnx:
        return approbations_appareil.decider_demande(
            cnx, departements, proprio, demande_id, "approuver", "", appareil=appareil)


def _transporter_reponse(resultat: Any) -> None:
    """Seam de perte : la réponse de décision ne parvient jamais au client (elle n'est jamais sérialisée)."""
    del resultat
    raise ReponsePerdueApresCommit("réponse de décision perdue après COMMIT (seam de test fictif)")


def _role_a() -> int:
    from opsys import stockage
    from opsys.capacites import Capacites
    from opsys.departements import lire_manifeste

    emettre("demarre", source=source_chargee(), **identite_courante())
    stockage.migrer()
    _creer_proprietaire()
    departements = {DEP: lire_manifeste(RACINE_M3)}
    capacites = Capacites(departements, stockage.transaction, appelant=DEP, memoire=False)
    devis_id, source_hash = _creer_devis_source(LEAD_A)
    avant = _resume_devis(_etat_devis(devis_id))
    arguments, ticket, demande = _demander(capacites, devis_id, LEAD_A)
    # La réponse de DEMANDE parvient au client (identité de rejeu) ; celle de la DÉCISION sera perdue.
    emettre("demande", demande=demande, ticket=ticket, arguments=arguments, devis_id=devis_id,
            lead_id=LEAD_A, source_hash=source_hash, devis_avant=avant)
    resultat = _decider(departements, demande["demande_id"], APPAREIL_A)
    # Le `with` de `_decider` est sorti sans exception : COMMIT fait, plus aucune transaction ouverte.
    if stockage.connexion_courante() is not None:
        raise EchecMiseEnPlace("transaction encore ouverte après la décision")
    emettre("transaction_sortie", connexion_ouverte=False, **identite_courante())
    _attendre_commande("PERDRE_REPONSE")
    _transporter_reponse(resultat)
    raise EchecMiseEnPlace("la perte de réponse attendue n'a pas eu lieu")


def _attendre_horloge_canonique_apres(t0_iso: str) -> str:
    """Attente BORNÉE : l'horloge canonique des approbations (lue, jamais remplacée) dépasse strictement T0."""
    from opsys import approbations

    t0 = dt.datetime.fromisoformat(t0_iso)
    fin = time.monotonic() + DELAI_HORLOGE_S
    while True:
        maintenant = approbations._maintenant()
        if dt.datetime.fromisoformat(maintenant) > t0:
            return maintenant
        if time.monotonic() >= fin:
            raise EchecMiseEnPlace("horloge canonique pas strictement après T0 dans le délai borné")
        time.sleep(0.05)


def _role_b() -> int:
    from m2_revenue_crm import clients
    from m2_revenue_crm import outils as outils_m2

    from opsys import evenements, identite, liaison_cibles, stockage
    from opsys.capacites import Capacites
    from opsys.departements import charger_departements, lire_manifeste

    emettre("demarre", source=source_chargee(), **identite_courante())
    contexte_a = _attendre_commande("CONTEXTE")
    departements = {DEP: lire_manifeste(RACINE_M3)}
    tous = charger_departements(RACINE_DEPARTEMENTS)
    capacites = Capacites(departements, stockage.transaction, appelant=DEP, memoire=False)
    outils_m2.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        personne = identite.personne_active(cnx, PROPRIETAIRE)
    emettre("reconstruit", proprietaire_actif=personne is not None,
            roles=sorted(personne.roles) if personne is not None else [])

    t_rejeu = _attendre_horloge_canonique_apres(contexte_a["t0"])
    rejeu = capacites.appeler(
        NOM, contexte_a["arguments"], ticket_cible=liaison_cibles.TicketMeta(contexte_a["ticket"]))
    resultat, verdict = _decider(departements, contexte_a["demande_id"], APPAREIL_REJEU)
    emettre("rejeux", t_rejeu=t_rejeu, rejeu=rejeu, redecision={"resultat": resultat, "verdict": verdict},
            devis_a=_resume_devis(_etat_devis(contexte_a["devis_id"])))

    _attendre_commande("REPARTIR")
    premiere = evenements.repartir({M2: tous[M2]})
    seconde = evenements.repartir({M2: tous[M2]})
    with stockage.transaction():
        client_a = clients.client_de_lead(outils_m2._obtenir_registre(), contexte_a["lead_id"])
    emettre("repartitions", premiere=premiere, seconde=seconde, client_a=client_a)

    _attendre_commande("DEVIS_B")
    devis_b, source_b = _creer_devis_source(LEAD_B)
    arguments_b, ticket_b, demande_b = _demander(capacites, devis_b, LEAD_B)
    resultat_b, verdict_b = _decider(departements, demande_b["demande_id"], APPAREIL_B)
    troisieme = evenements.repartir({M2: tous[M2]})
    with stockage.transaction():
        client_b = clients.client_de_lead(outils_m2._obtenir_registre(), LEAD_B)
    emettre("devis_b", devis_id=devis_b, source_hash=source_b, arguments=arguments_b, demande=demande_b,
            ticket_distinct=ticket_b != contexte_a["ticket"], resultat=resultat_b, verdict=verdict_b,
            devis_b=_resume_devis(_etat_devis(devis_b)), troisieme=troisieme, client_b=client_b)

    _attendre_commande("FIN")
    emettre("fin", **identite_courante())
    return 0


def main(argv: list[str]) -> int:
    role = argv[1] if len(argv) > 1 else ""
    try:
        if role == "A":
            return _role_a()
        if role == "B":
            return _role_b()
        raise EchecMiseEnPlace(f"rôle inconnu {role!r}")
    except ReponsePerdueApresCommit as exc:
        from opsys import stockage

        emettre("reponse_perdue", type=type(exc).__name__, connexion_ouverte=stockage.connexion_courante() is not None)
        return EXIT_REPONSE_PERDUE
    except ArretDemande as exc:
        emettre("arret", raison=str(exc))
        return EXIT_ARRET
    except BaseException as exc:  # noqa: BLE001 — toute exception enfant est rendue au parent, qui la réasserte
        emettre("exception", type=type(exc).__name__, message=str(exc), trace=traceback.format_exc())
        return EXIT_EXCEPTION


# -- côté parent : processus possédés -------------------------------------------------------------------------
def environnement_enfant(dossier: Path, chemin_db: Path, role: str) -> dict[str, str]:
    from opsys import stockage

    maison = dossier / f"opsys-home-{role}"
    maison.mkdir(exist_ok=True)
    chemins = [str(RACINE_DEPOT / "src"), *(str(p) for p in sorted(RACINE_DEPARTEMENTS.glob("*/src"))),
               str(RACINE_DEPOT / "tests" / "fixtures")]
    if os.environ.get("PYTHONPATH"):
        chemins.append(os.environ["PYTHONPATH"])
    return {**os.environ, stockage.ENV_URL: f"sqlite:///{chemin_db}", "OPSYS_HOME": str(maison),
            "OPSYS_EVENEMENTS_REPARTITEUR": "0", "OPSYS_DEPARTMENTS": str(RACINE_DEPARTEMENTS),
            "PYTHONPATH": os.pathsep.join(chemins), "PYTHONDONTWRITEBYTECODE": "1"}


class ProcessusPossede:
    """Un processus enfant lancé ici, et lui seul : stdin pour les ordres, stdout lu jusqu'à EOF."""

    def __init__(self, role: str, dossier: Path, chemin_db: Path, echeance: float) -> None:
        self.role = role
        self.echeance = echeance
        self.messages: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self.stderr: list[str] = []
        self.eof = threading.Event()
        self.popen = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), role], cwd=str(dossier),
            env=environnement_enfant(dossier, chemin_db, role), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1,
        )
        self.ticks = ticks_demarrage(self.popen.pid)
        self._lecteurs = [threading.Thread(target=self._lire_stdout, daemon=True),
                          threading.Thread(target=self._lire_stderr, daemon=True)]
        for lecteur in self._lecteurs:
            lecteur.start()

    def _lire_stdout(self) -> None:
        try:
            for ligne in self.popen.stdout:
                if ligne.startswith(PREFIXE):
                    self.messages.put(json.loads(ligne[len(PREFIXE):]))
        finally:
            self.eof.set()
            self.messages.put(None)

    def _lire_stderr(self) -> None:
        for ligne in self.popen.stderr:
            if len(self.stderr) < 400:
                self.stderr.append(ligne)

    def attendre(self, etape: str) -> dict[str, Any]:
        while True:
            reste = self.echeance - time.monotonic()
            if reste <= 0:
                raise EchecMiseEnPlace(f"{self.role} : délai global dépassé avant {etape!r} (jamais un oracle métier)")
            try:
                message = self.messages.get(timeout=min(reste, 1.0))
            except queue.Empty:
                continue
            if message is None:
                raise EchecMiseEnPlace(f"{self.role} : EOF avant {etape!r}, rc={self.popen.poll()} ; "
                                       f"stderr={''.join(self.stderr)[-3000:]}")
            if message["etape"] == "exception":
                raise AssertionError(
                    f"exception dans le processus {self.role} : {message['type']}: {message['message']}\n"
                    f"{message['trace']}")
            if message["etape"] != etape:
                raise EchecMiseEnPlace(f"{self.role} : étape {message['etape']!r} reçue, {etape!r} attendue")
            return message

    def ordonner(self, commande: str, **donnees: Any) -> None:
        self.popen.stdin.write(json.dumps({"commande": commande, **donnees}, ensure_ascii=False) + "\n")
        self.popen.stdin.flush()

    def joindre(self) -> int:
        """Attend la fin propre du processus possédé et l'EOF de sa sortie ; rend son code."""
        try:
            rc = self.popen.wait(timeout=max(1.0, min(30.0, self.echeance - time.monotonic())))
        except subprocess.TimeoutExpired as exc:
            raise EchecMiseEnPlace(f"{self.role} : pas de sortie dans le délai (jamais un oracle métier)") from exc
        for lecteur in self._lecteurs:
            lecteur.join(timeout=5)
        if not self.eof.is_set():
            raise EchecMiseEnPlace(f"{self.role} : EOF de stdout non établi")
        return rc

    def liberer(self) -> None:
        """Toujours appelé (finally) : STOP, puis EOF de stdin, puis kill borné — de CE processus seulement."""
        if self.popen.poll() is None:
            with contextlib.suppress(OSError):
                self.ordonner("STOP")
                self.popen.stdin.close()
            try:
                self.popen.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.popen.kill()
                self.popen.wait(timeout=5)
        for lecteur in self._lecteurs:
            lecteur.join(timeout=5)
        for flux in (self.popen.stdin, self.popen.stdout, self.popen.stderr):
            if flux is not None and not flux.closed:
                with contextlib.suppress(OSError):
                    flux.close()


# -- témoin indépendant en lecture seule ---------------------------------------------------------------------
_TABLES = {
    "registres_maillons": ("SELECT departement, registre, rang, maillon, cree_le FROM registres_maillons "
                           "ORDER BY departement, registre, rang", ("departement", "registre", "rang")),
    "approbations": ("SELECT * FROM approbations ORDER BY id", ("id",)),
    "evenements_sortants": ("SELECT * FROM evenements_sortants ORDER BY evenement_id", ("evenement_id",)),
    "evenements_recus": ("SELECT * FROM evenements_recus ORDER BY evenement_id, consommateur",
                         ("evenement_id", "consommateur")),
    "liaisons_tickets": ("SELECT * FROM liaisons_tickets ORDER BY ticket_hash", ("ticket_hash",)),
    "journal": ("SELECT * FROM journal ORDER BY id", ("id",)),
}
_TABLES_PREFIXE = ("registres_maillons", "approbations", "evenements_sortants", "liaisons_tickets", "journal")


def temoin_lecture_seule(chemin_db: Path) -> dict[str, list[dict[str, Any]]]:
    """Connexion SQLite neuve et indépendante (URI `mode=ro`), un seul instantané de lecture pour toutes les tables."""
    cnx = sqlite3.connect(f"file:{quote(str(chemin_db))}?mode=ro", uri=True, timeout=5, isolation_level=None)
    try:
        cnx.row_factory = sqlite3.Row
        cnx.execute("BEGIN")
        etat = {nom: [dict(ligne) for ligne in cnx.execute(requete)] for nom, (requete, _) in _TABLES.items()}
        cnx.execute("COMMIT")
    finally:
        cnx.close()
    return etat


def maillons(etat: dict[str, Any], departement: str, registre: str) -> list[Any]:
    from opsys.stockage import codec

    return [codec.decoder(ligne["maillon"]) for ligne in etat["registres_maillons"]
            if (ligne["departement"], ligne["registre"]) == (departement, registre)]


def charge(ligne: dict[str, Any]) -> Any:
    from opsys.stockage import codec

    return codec.decoder(ligne["charge"])


def oracle_avant_perte(etat: dict[str, Any], a: dict[str, Any]) -> dict[str, Any]:
    """Prérequis « commis avant la perte » vu par le témoin indépendant ; sinon panne de mise en place."""
    demande_id, devis_id = a["demande"]["demande_id"], a["devis_id"]
    approbations_a = [r for r in etat["approbations"] if r["id"] == demande_id]
    lignes_a = [m for m in maillons(etat, DEP, "devis") if m.get("devis_id") == devis_id]
    envoyes = [m for m in lignes_a if m.get("statut") == "envoye"]
    sorties = [r for r in etat["evenements_sortants"] if r["evenement_id"] == f"m3-devis-envoye-{devis_id}"]
    tickets = [r for r in etat["liaisons_tickets"] if r["demande_id"] == demande_id]
    if not (len(approbations_a) == 1 and approbations_a[0]["statut"] == "executee"
            and approbations_a[0]["decide_le"] and len(envoyes) == 1 and len(sorties) == 1 and len(tickets) == 1):
        raise EchecMiseEnPlace(f"COMMIT avant la perte non observé par le témoin indépendant : {approbations_a}")
    return {
        "t0": approbations_a[0]["decide_le"], "demande_id": demande_id, "devis_id": devis_id,
        "lead_id": a["lead_id"], "arguments": a["arguments"], "source_hash": a["source_hash"],
        "approbation": approbations_a[0], "lignes_devis_a": lignes_a, "outbox_a": sorties[0],
        "ticket_a": tickets[0], "evenement_a": f"m3-devis-envoye-{devis_id}", "prefixe": etat, "client_id": None,
    }


def _cle(nom: str, ligne: dict[str, Any]) -> tuple:
    return tuple(ligne[colonne] for colonne in _TABLES[nom][1])


def controler_cible_a(etat: dict[str, Any], oracle: dict[str, Any], *, livre: bool) -> list[str]:
    """Anomalies de la cible A dans `etat`, comparé à l'oracle FIXÉ avant la perte (T0, lead, source, préfixe).

    Ne se fie à aucune chaîne ni empreinte recalculable : chaque fait est compté et comparé à la valeur capturée.
    Les ajouts légitimes (devis B, ses tickets, son audit, reçus du répartiteur) ne sont pas des anomalies."""
    anomalies: set[str] = set()
    t0, devis_id, lead_id = oracle["t0"], oracle["devis_id"], oracle["lead_id"]
    approbations_a = [r for r in etat["approbations"] if r["id"] == oracle["demande_id"]]
    if approbations_a != [oracle["approbation"]]:
        anomalies.add("A_APPROBATION_MODIFIEE")
    if any(r["decide_le"] != t0 for r in approbations_a):
        anomalies.add("A_DATE_T0")
    if any(r["id"] != oracle["demande_id"] and r["outil"] == NOM and json.loads(r["arguments"]) == oracle["arguments"]
           for r in etat["approbations"]):
        anomalies.add("A_DEMANDE_DOUBLE")
    lignes_a = [m for m in maillons(etat, DEP, "devis") if m.get("devis_id") == devis_id]
    envoyes = [m for m in lignes_a if m.get("statut") == "envoye"]
    if len(envoyes) != 1:
        anomalies.add("A_TRANSITION_ENVOYE_DOUBLE" if envoyes else "A_TRANSITION_ENVOYE_ABSENTE")
    if any(m.get("horodatage") != t0 for m in envoyes):
        anomalies.add("A_DATE_T0")
    if any(m.get("lead_id", lead_id) != lead_id for m in lignes_a):
        anomalies.add("A_LEAD")
    if any("estimation_source_hash" in m and m["estimation_source_hash"] != oracle["source_hash"] for m in lignes_a):
        anomalies.add("A_SOURCE")
    if lignes_a != oracle["lignes_devis_a"]:
        anomalies.add("A_DEVIS_MODIFIE")
    sorties = [r for r in etat["evenements_sortants"]
               if r["type_evenement"] == TYPE_ENVOYE and charge(r).get("devis_id") == devis_id]
    if len(sorties) != 1:
        anomalies.add("A_OUTBOX_DOUBLE" if sorties else "A_OUTBOX_ABSENTE")
    if sorties != [oracle["outbox_a"]]:
        anomalies.add("A_OUTBOX_MODIFIEE")
    for ligne in sorties:
        if charge(ligne).get("horodatage_envoi") != t0:
            anomalies.add("A_DATE_T0")
        if charge(ligne).get("lead_id") != lead_id:
            anomalies.add("A_LEAD")
    if [r for r in etat["liaisons_tickets"] if r["demande_id"] == oracle["demande_id"]] != [oracle["ticket_a"]]:
        anomalies.add("A_TICKET_MODIFIE")
    for nom in _TABLES_PREFIXE:
        actuelles = {_cle(nom, ligne): ligne for ligne in etat[nom]}
        if any(actuelles.get(_cle(nom, ligne)) != ligne for ligne in oracle["prefixe"][nom]):
            anomalies.add("PREFIXE_MODIFIE")
    faits = [m for m in maillons(etat, M2, "devis_envoyes_recus") if m.get("devis_id") == devis_id]
    recus = [r for r in etat["evenements_recus"] if r["evenement_id"] == oracle["evenement_a"]]
    if livre:
        if len(faits) != 1:
            anomalies.add("M2_FAIT_DOUBLE" if faits else "M2_FAIT_ABSENT")
        for fait in faits:
            if fait.get("horodatage_envoi") != t0:
                anomalies.add("A_DATE_T0")
            if fait.get("lead_id") != lead_id:
                anomalies.add("A_LEAD")
            if fait.get("client_id") != oracle["client_id"] or "ignore" in fait:
                anomalies.add("M2_FAIT_CLIENT_OU_IGNORE")
        if [(r["consommateur"], r["statut"], r["tentatives"]) for r in recus] != [(M2, "traite", 1)]:
            anomalies.add("M2_RECU_A")
    elif faits or recus:
        anomalies.add("M2_PREMATURE")
    if any(r["statut"] == "quarantaine" for r in etat["evenements_recus"]):
        anomalies.add("QUARANTAINE")
    return sorted(anomalies)


def dates_internes_a(etat: dict[str, Any], oracle: dict[str, Any]) -> set[str]:
    """Dates de A lues aux quatre endroits (décision, transition, outbox, fait M2) : cohérence interne seule."""
    devis_id = oracle["devis_id"]
    dates = {r["decide_le"] for r in etat["approbations"] if r["id"] == oracle["demande_id"]}
    dates |= {m["horodatage"] for m in maillons(etat, DEP, "devis")
              if m.get("devis_id") == devis_id and m.get("statut") == "envoye"}
    dates |= {charge(r)["horodatage_envoi"] for r in etat["evenements_sortants"]
              if r["evenement_id"] == oracle["evenement_a"]}
    dates |= {m["horodatage_envoi"] for m in maillons(etat, M2, "devis_envoyes_recus") if m.get("devis_id") == devis_id}
    return dates


# -- contrôle négatif : copie jetable seulement ------------------------------------------------------------------
def copie_jetable(source: Path, cible: Path) -> Path:
    lecture = sqlite3.connect(f"file:{quote(str(source))}?mode=ro", uri=True)
    ecriture = sqlite3.connect(str(cible))
    try:
        lecture.backup(ecriture)
    finally:
        lecture.close()
        ecriture.close()
    return cible


def muter_copie(copie: Path, oracle: dict[str, Any], mutation: str) -> None:
    """Mutation de FIXTURE sur une copie jetable (jamais la base du scénario, jamais un défaut produit).

    `doublon_transition` / `doublon_fait_m2` ajoutent en fin de registre (préfixe intact) ; `date_recalculee` et
    `lead_recalcule` réécrivent les quatre champs vérifiés (décision, transition, outbox, fait M2).
    Les témoins et préfixes restent fixés avant la perte ; le registre principal d'estimations n'est pas muté ici."""
    from opsys.stockage import codec

    devis_id = oracle["devis_id"]
    faux_t = (dt.datetime.fromisoformat(oracle["t0"]) + dt.timedelta(hours=1)).isoformat()
    cnx = sqlite3.connect(str(copie), isolation_level=None)
    try:
        cnx.execute("BEGIN")
        lignes = cnx.execute("SELECT departement, registre, rang, maillon FROM registres_maillons "
                             "WHERE departement IN (?, ?) ORDER BY rang", (DEP, M2)).fetchall()

        def reecrire(departement, registre, rang, maillon):
            cnx.execute("UPDATE registres_maillons SET maillon = ? WHERE departement = ? AND registre = ? AND rang = ?",
                        (codec.encoder(maillon), departement, registre, rang))

        def ajouter(departement, registre, maillon):
            rang = cnx.execute("SELECT COALESCE(MAX(rang) + 1, 0) FROM registres_maillons WHERE departement = ? "
                               "AND registre = ?", (departement, registre)).fetchone()[0]
            cnx.execute("INSERT INTO registres_maillons (departement, registre, rang, maillon) VALUES (?, ?, ?, ?)",
                        (departement, registre, rang, codec.encoder(maillon)))

        cibles = [(d, r, rang, codec.decoder(texte)) for d, r, rang, texte in lignes
                  if (d, r) in {(DEP, "devis"), (M2, "devis_envoyes_recus")}
                  and codec.decoder(texte).get("devis_id") == devis_id]
        transition = next(m for _, r, _, m in cibles if r == "devis" and m.get("statut") == "envoye")
        fait = next(m for _, r, _, m in cibles if r == "devis_envoyes_recus")
        sortie = codec.decoder(cnx.execute("SELECT charge FROM evenements_sortants WHERE evenement_id = ?",
                                           (oracle["evenement_a"],)).fetchone()[0])
        if mutation == "doublon_transition":
            ajouter(DEP, "devis", transition)
        elif mutation == "doublon_fait_m2":
            ajouter(M2, "devis_envoyes_recus", fait)
        elif mutation in {"date_recalculee", "lead_recalcule"}:
            date = mutation == "date_recalculee"
            champ, valeur = ("horodatage", faux_t) if date else ("lead_id", "lead-autre-fictif")
            for departement, registre, rang, maillon in cibles:
                cle = {"devis": champ, "devis_envoyes_recus": "horodatage_envoi" if champ == "horodatage" else champ}
                if registre == "devis" and champ == "horodatage" and maillon.get("statut") != "envoye":
                    continue
                if registre == "devis" and champ == "lead_id" and "lead_id" not in maillon:
                    continue
                reecrire(departement, registre, rang, {**maillon, cle[registre]: valeur})
            sortie[{"horodatage": "horodatage_envoi", "lead_id": "lead_id"}[champ]] = valeur
            cnx.execute("UPDATE evenements_sortants SET charge = ? WHERE evenement_id = ?",
                        (codec.encoder(sortie), oracle["evenement_a"]))
            if champ == "horodatage":
                cnx.execute("UPDATE approbations SET decide_le = ? WHERE id = ?", (valeur, oracle["demande_id"]))
        else:
            raise ValueError(f"mutation inconnue {mutation!r}")
        cnx.execute("COMMIT")
    finally:
        cnx.close()


# -- scénario piloté par le parent ----------------------------------------------------------------------------
def executer_scenario(dossier: Path) -> dict[str, Any]:
    """Pilote A puis B ; rend les observations brutes (les oracles métier sont dans le test)."""
    chemin_db = dossier / "opsys-postcommit-fictif.db"
    echeance = time.monotonic() + DELAI_GLOBAL_S
    obs: dict[str, Any] = {"chemin_db": chemin_db, "uri_temoin": "mode=ro"}
    # La copie attendue est celle du test qui pilote : ce module doit être à côté de lui, pas un M3 d'origine.
    pilote = Path(sys._getframe(1).f_code.co_filename).resolve()
    if pilote.parent != _TESTS:
        raise ProvenanceIncoherente(f"M3_HORS_COPIE : aide {_TESTS} hors du dossier du test pilote {pilote}")
    # Attentes de provenance capturées AVANT A/B depuis les racines déclarées, revérifiées après B.
    obs["sources_attendues"] = sources_attendues(RACINE_M3 / "src", RACINE_DEPOT / "src")
    possedes: list[ProcessusPossede] = []
    try:
        a = ProcessusPossede("A", dossier, chemin_db, echeance)
        possedes.append(a)
        obs["a_demarre"] = a.attendre("demarre")
        obs["a_ticks_parent"] = a.ticks
        obs["a_demande"] = a.attendre("demande")
        obs["a_sortie"] = a.attendre("transaction_sortie")
        obs["a_ticks_avant_perte"] = ticks_demarrage(a.popen.pid)
        etat_avant = temoin_lecture_seule(chemin_db)
        oracle = oracle_avant_perte(etat_avant, obs["a_demande"])
        obs["etat_avant"] = etat_avant
        a.ordonner("PERDRE_REPONSE")
        obs["a_perte"] = a.attendre("reponse_perdue")
        obs["a_rc"] = a.joindre()
        obs["a_ticks_apres_fin"] = ticks_demarrage(a.popen.pid)
        obs["etat_apres_a"] = temoin_lecture_seule(chemin_db)

        b = ProcessusPossede("B", dossier, chemin_db, echeance)
        possedes.append(b)
        obs["b_demarre"] = b.attendre("demarre")
        obs["b_ticks_parent"] = b.ticks
        b.ordonner("CONTEXTE", t0=oracle["t0"], demande_id=oracle["demande_id"], ticket=obs["a_demande"]["ticket"],
                   arguments=oracle["arguments"], devis_id=oracle["devis_id"], lead_id=oracle["lead_id"])
        obs["b_reconstruit"] = b.attendre("reconstruit")
        obs["b_rejeux"] = b.attendre("rejeux")
        obs["etat_apres_rejeux"] = temoin_lecture_seule(chemin_db)
        b.ordonner("REPARTIR")
        obs["b_repartitions"] = b.attendre("repartitions")
        obs["etat_apres_repartitions"] = temoin_lecture_seule(chemin_db)
        b.ordonner("DEVIS_B")
        obs["b_devis_b"] = b.attendre("devis_b")
        obs["etat_b_vivant"] = temoin_lecture_seule(chemin_db)
        b.ordonner("FIN")
        obs["b_fin"] = b.attendre("fin")
        obs["b_rc"] = b.joindre()
        if sources_attendues(RACINE_M3 / "src", RACINE_DEPOT / "src") != obs["sources_attendues"]:
            raise ProvenanceIncoherente("EMPREINTE_MODIFIEE : sources M3/socle changées entre capture et fin de B")
        obs["etat_rouvert"] = temoin_lecture_seule(chemin_db)
        obs["oracle"] = oracle
        return obs
    finally:
        for possede in reversed(possedes):
            possede.liberer()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
