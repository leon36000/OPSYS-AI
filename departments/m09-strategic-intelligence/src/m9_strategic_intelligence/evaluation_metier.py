"""Évaluation métier M9.23 : un corpus de cas d'affaires fictifs rejoué dans les VRAIS chemins M9, hors ligne.

Module pur : aucune horloge d'affaires, aucun réseau, aucun appel de modèle. Le corpus
(``evals/corpus-metier-v1.json``, schéma ``corpus-metier-v1.schema.json``) porte, par cas, une ENTRÉE (réponses de
producteurs simulées au format du catalogue), des SORTIES FIGÉES de « modèle » et des ATTENTES écrites à la main
depuis les exigences du cahier (``DEFINITION-PRODUIT`` §M9, « Règles dures ») et depuis des oracles métier
déterministes calculés à la main — jamais depuis la sortie du code testé.

Ce que ce harnais est, et n'est pas :

* les sorties figées sont des **doubles de protocole** : elles décrivent ce qu'un modèle pourrait rendre (y compris
  des sorties fautives, pour sonder les garde-fous). Le verdict obtenu ici porte sur la couche déterministe de M9 et
  JAMAIS sur un modèle réel : la qualification par modèle réel et l'exécution Core native restent des verdicts
  séparés, ouverts ;
* les réponses de producteurs sont des CONTRATS SIMULÉS (forme du catalogue ``catalogue_producteurs``) ou, dans le
  corpus v2, des pages CAPTURÉES sur les vrais producteurs raccordés (``contrats_reels``) : aucun producteur n'est
  interrogé ici. Le corpus nomme ceux qui sont simulés, ceux qui sont réels et ceux qui n'existent pas encore ;
* les cas sont répartis en deux partitions : ``ajustement`` (sur laquelle on analyse, on corrige) et
  ``verification`` (tenue à part : jamais utilisée pour décider d'un changement de code ;
  ``fuites_entre_partitions`` le contrôle) ;
* les coûts et latences de modèle sont ``UNKNOWN`` (aucun modèle appelé) ; seule la latence du harnais est mesurée ;
* un taux élevé sur un petit effectif n'établit ni « zéro hallucination » ni une confiance générale : l'intervalle
  de Wilson est rendu, et les cas rouges sont listés avec l'attendu et l'observé, jamais moyennés.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal, InvalidOperation

from . import capture_strategique as cs
from . import catalogue_producteurs as cat
from . import conseil, dossier_direction, occasions, previsions, priorisation, registre, sessions_conseil
from . import dossier_strategique as ds
from .audit_affirmations import auditer_affirmations
from .evaluation import wilson

VERSION = "2026-10-31.1"
FAMILLES = (
    "rapport_direction",
    "budget_marketing",
    "tresorerie_serree",
    "leads_hors_capacite",
    "nouvelle_ville",
    "reputation",
)
PARTITIONS = ("ajustement", "verification")
PERTURBATIONS = ("nominal", "absence", "tardive", "contradiction", "perimee", "unite_date", "homonyme", "injection")
CHEMINS = ("conseil", "direction", "previsions", "priorisation", "occasions")
STATUT_INCONNU = "UNKNOWN"
BIAIS_CONNUS = (
    "corpus fictif rédigé par un seul auteur (agent), en français : aucune diversité d'auteurs ni de formulations",
    "effectifs faibles par famille et par partition : les intervalles de Wilson sont larges",
    "sorties de modèle FIGÉES rédigées à la main : elles sondent les garde-fous, elles ne mesurent aucun modèle réel",
    "réponses de producteurs simulées au format du catalogue : aucune réponse réelle de M1–M8 n'est rejouée ici",
    "les attentes suivent les exigences écrites du cahier ; une exigence absente du cahier n'est pas testée",
    "la justesse sémantique d'une inférence (par ex. « équipes » pour « matériaux ») n'est pas détectable par le code",
)
LIMITES = (
    "Verdict de DOUBLES DE PROTOCOLE sur la couche déterministe de M9 : aucune qualification d'un modèle réel.",
    "Qualité du conseil, justesse des inférences et utilité des décisions NON ÉTABLIES : "
    "revue métier humaine indépendante requise.",
    "Exécution Core native (budget natif, réservations, agents) non exercée : verdict séparé, ouvert.",
    "Corpus v1 : producteurs M4 (capacité d'équipe), M7 (dépenses) et M1 (plaintes structurées) simulés. Corpus v2 : "
    "pages capturées sur les VRAIS producteurs M1, M4, M7, M8 raccordés pour les cas qui les nomment ; le reste reste "
    "simulé.",
)
_MONTANT = re.compile(
    r"(?<![\w.,])(?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)(?:[.,]\d{1,2})?\s?(?:\$|CAD|%|dollars?|k\$)"
    r"|(?<![\w.,])\d+[.,]\d{2}(?![\w])"
)
_DATE_ISO = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_NOMBRE = re.compile(r"\d+(?:[.,]\d+)?")


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def _code(exc: ValueError) -> str:
    message = str(exc)
    return message.split(" :", 1)[0] if message.startswith("REJ-") else "ERREUR-NON-NOMMEE"


# ----------------------------------------------------------------------------------------------------------------
# Corpus : validation sémantique (le schéma JSON est contrôlé par les tests)
# ----------------------------------------------------------------------------------------------------------------
def valider_corpus_metier(corpus: object) -> list[dict]:
    """Contrôle sémantique du corpus ; rend la liste des cas. Lève ``REJ-EVALMETIER-CORPUS``."""
    if not isinstance(corpus, Mapping) or corpus.get("fictif") is not True or not isinstance(corpus.get("cas"), list):
        raise _refus("REJ-EVALMETIER-CORPUS", "corpus {fictif: true, cas[]} requis")
    for cle in ("version", "contrats_simules", "producteurs_absents", "double_protocole"):
        if cle not in corpus:
            raise _refus("REJ-EVALMETIER-CORPUS", f"clé « {cle} » requise (contrats simulés et doubles nommés)")
    ids: set[str] = set()
    for cas in corpus["cas"]:
        identifiant = cas.get("id") if isinstance(cas, Mapping) else cas
        requis = {"id", "famille", "partition", "perturbations", "chemin", "scenario", "regle", "entree", "attentes"}
        if (
            not isinstance(cas, Mapping)
            or not requis <= set(cas)
            or cas["famille"] not in FAMILLES
            or cas["partition"] not in PARTITIONS
            or cas["chemin"] not in CHEMINS
            or not isinstance(cas["perturbations"], list)
            or not cas["perturbations"]
            or not set(cas["perturbations"]) <= set(PERTURBATIONS)
            or cas["id"] in ids
            or not isinstance(cas["entree"], Mapping)
            or not isinstance(cas["attentes"], Mapping)
            or not str(cas["scenario"]).strip()
            or not str(cas["regle"]).strip()
        ):
            raise _refus("REJ-EVALMETIER-CORPUS", f"cas invalide {identifiant!r}")
        ids.add(cas["id"])
    return list(corpus["cas"])


def empreinte_partition(corpus: Mapping, partition: str) -> str:
    """Sceau d'une partition : empreinte des cas triés par identifiant (détecte toute retouche après gel)."""
    cas = sorted((c for c in corpus["cas"] if c["partition"] == partition), key=lambda c: c["id"])
    return hashlib.sha256(json.dumps(cas, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def _signature_entree(cas: Mapping) -> str:
    return hashlib.sha256(
        json.dumps([cas["chemin"], cas["entree"]], sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()


def fuites_entre_partitions(corpus: Mapping) -> list[str]:
    """Fuites possibles de l'ajustement vers la vérification (liste vide = aucune détectée).

    Contrôlé : identifiants disjoints, entrées jamais identiques d'une partition à l'autre, et aucune sortie figée
    (``double_protocole``) identique. Le harnais, lui, n'a aucune branche par identifiant de cas : voir les tests."""
    cas = valider_corpus_metier(corpus)
    fuites = []
    par_partition = {p: [c for c in cas if c["partition"] == p] for p in PARTITIONS}
    ids_a = {c["id"] for c in par_partition["ajustement"]}
    ids_v = {c["id"] for c in par_partition["verification"]}
    fuites += [f"identifiant commun {i}" for i in sorted(ids_a & ids_v)]
    signatures_a = {_signature_entree(c): c["id"] for c in par_partition["ajustement"]}
    for c in par_partition["verification"]:
        autre = signatures_a.get(_signature_entree(c))
        if autre is not None:
            fuites.append(f"entrée identique entre {autre} et {c['id']}")
    doubles_a = {
        json.dumps(c.get("double_protocole"), sort_keys=True): c["id"]
        for c in par_partition["ajustement"]
        if c.get("double_protocole")
    }
    for c in par_partition["verification"]:
        if c.get("double_protocole"):
            autre = doubles_a.get(json.dumps(c["double_protocole"], sort_keys=True))
            if autre is not None:
                fuites.append(f"sortie figée identique entre {autre} et {c['id']}")
    return fuites


# --------------------------------------------------------------------------------------------------------------------
# Comparaison attendu / observé : l'attendu est un sous-ensemble de l'observé (dict), les listes sont exactes.
# --------------------------------------------------------------------------------------------------------------------
def _ecarts_sous_ensemble(attendu: object, observe: object, chemin: str = "") -> list[str]:
    if isinstance(attendu, Mapping):
        if not isinstance(observe, Mapping):
            return [f"{chemin or '.'} : attendu un objet, observé {observe!r}"]
        ecarts: list[str] = []
        for cle, valeur in attendu.items():
            if cle not in observe:
                ecarts.append(f"{chemin}.{cle} : attendu {valeur!r}, clé absente de l'observé")
            else:
                ecarts += _ecarts_sous_ensemble(valeur, observe[cle], f"{chemin}.{cle}")
        return ecarts
    if isinstance(attendu, list):
        if not isinstance(observe, list) or len(observe) != len(attendu):
            return [f"{chemin} : attendu {attendu!r}, observé {observe!r}"]
        ecarts = []
        for rang, (a, o) in enumerate(zip(attendu, observe, strict=True)):
            ecarts += _ecarts_sous_ensemble(a, o, f"{chemin}[{rang}]")
        return ecarts
    return [] if attendu == observe else [f"{chemin} : attendu {attendu!r}, observé {observe!r}"]


# --------------------------------------------------------------------------------------------------------------------
# Captures et dossier : les vrais constructeurs M9 sur des réponses de producteurs simulées
# --------------------------------------------------------------------------------------------------------------------
def _captures(specs: Sequence[Mapping]) -> tuple[list[dict], list[dict]]:
    """(chaîne de captures, refus de capture). Une capture refusée n'entre pas dans la chaîne : un manque se prouve."""
    chaine: list[dict] = []
    refus: list[dict] = []
    precedent, dernier = cs.HASH_INITIAL, None
    for position, spec in enumerate(specs):
        try:
            capture = cs.construire(
                cat.obtenir(spec["lecture"]),
                spec.get("arguments", {}),
                spec["pages"],
                recu_a=spec["recu_a"],
                reference=spec.get("reference"),
                index=len(chaine),
                hash_precedent=precedent,
                dernier_recu_a=dernier,
            )
        except ValueError as exc:
            refus.append({"position": position, "lecture": spec["lecture"], "code": _code(exc)})
            continue
        chaine.append(capture)
        precedent, dernier = capture["hash_maillon"], capture["recu_a"]
    return chaine, refus


def _projection_dossier(dossier: Mapping, refus_captures: Sequence[Mapping]) -> dict:
    return {
        "statuts": {e["lecture_id"]: e["statut"] for e in dossier["couverture"]["lectures"]},
        "fraicheurs": {e["lecture_id"]: e["fraicheur"] for e in dossier["couverture"]["lectures"] if "fraicheur" in e},
        "manques": sorted(m["lecture_id"] for m in dossier["manques"]),
        "contradictions": len(dossier["contradictions"]),
        "lectures_avec_faits": sorted({a.split("#", 1)[0] for a in dossier["faits"]}),
        "faits": dossier["faits"],
        "nb_faits": len(dossier["faits"]),
        "faits_non_retenus": dossier["faits_non_retenus"],
        "captures_refusees": [{"lecture": r["lecture"], "code": r["code"]} for r in refus_captures],
    }


def _normaliser_nombre(texte: str) -> Decimal | None:
    brut = re.sub(r"[^\d.,]", "", texte).replace(",", ".")
    try:
        return Decimal(brut)
    except InvalidOperation:
        return None


def _nombres_cites(valeurs: Sequence[str]) -> tuple[set[Decimal], set[str]]:
    nombres: set[Decimal] = set()
    dates: set[str] = set()
    for valeur in valeurs:
        complet = _normaliser_nombre(valeur)
        if complet is not None:
            nombres.add(complet)
        for brut in _NOMBRE.findall(valeur):
            n = _normaliser_nombre(brut)
            if n is not None:
                nombres.add(n)
        dates |= set(_DATE_ISO.findall(valeur))
    return nombres, dates


def montants_libres(texte: str, valeurs_citees: Sequence[str]) -> list[str]:
    """Oracle indépendant : montants, pourcentages, décimaux ou dates ISO d'un texte libre qui ne figurent dans AUCUNE
    observation citée par la même sortie (le modèle explique ; le code calcule)."""
    nombres, dates = _nombres_cites(valeurs_citees)
    trouves = []
    for correspondance in _MONTANT.finditer(texte):
        n = _normaliser_nombre(correspondance.group(0))
        if n is None or n not in nombres:
            trouves.append(correspondance.group(0).strip())
    trouves += [d for d in _DATE_ISO.findall(texte) if d not in dates]
    return trouves


def _textes_libres(proposition: Mapping) -> list[tuple[str, list[str]]]:
    """(texte libre, valeurs citées par la même sortie) : hypothèses, inférences, décision, descriptions d'action."""
    citees = [a["valeur"] for a in proposition["affirmations"] if a["nature"] == "observation_source"]
    textes = [a["enonce"] for a in proposition["affirmations"] if a["nature"] in ("hypothese", "inference")]
    recommandation = proposition.get("recommandation")
    if recommandation:
        textes.append(recommandation["decision"])
        textes += [a.get("description", "") for a in recommandation["actions"]]
    return [(t, citees) for t in textes]


# --------------------------------------------------------------------------------------------------------------------
# Chemin « conseil » : captures → dossier → session → dépôts figés → clôture gouvernée
# --------------------------------------------------------------------------------------------------------------------
def _sorties_du_role(double: Mapping, role: str) -> list:
    valeur = double.get(role)
    if valeur is None:
        return []
    return valeur if isinstance(valeur, list) else [valeur]


def _executer_conseil(cas: Mapping) -> dict:
    entree = cas["entree"]
    double = cas.get("double_protocole", {})
    chaine, refus_captures = _captures(entree["captures"])
    dossier = ds.construire(
        chaine,
        question=entree["question"],
        domaines=entree["domaines"],
        reference=entree["reference"],
        connaissance=entree["connaissance"],
        attendues=entree["attendues"],
    )
    observe: dict = {"dossier": _projection_dossier(dossier, refus_captures), "invariants_violes": []}
    horodatage = entree["ouverture_a"]
    try:
        ouverture, session_id = sessions_conseil.ouvrir(
            [],
            dossier=dossier,
            importance=entree["importance"],
            budget_tokens=entree["budget_tokens"],
            recu_a=horodatage,
        )
    except ValueError as exc:
        observe["ouverture"] = {"issue": "REFUSEE", "code": _code(exc)}
        observe["selection"] = sorted(
            a["role"]
            for a in conseil.selectionner(
                dossier["domaines"], importance=entree["importance"], budget_tokens=entree["budget_tokens"]
            )["appeles"]
        )
        return observe
    evenements = [ouverture]
    observe["ouverture"] = {"issue": "OUVERTE"}
    observe["selection"] = sorted(ouverture["tours"])
    premier = next(iter(ouverture["tours"]))
    donnees = sessions_conseil.entree_tour(evenements, session_id, premier)["donnees"]
    observe["entree_conseil"] = {
        "cles": sorted(donnees),
        "ages_exposes": '"age_s"' in json.dumps(donnees, ensure_ascii=False),
    }
    compte = 0

    def ajouter(evenement: dict | None) -> None:
        if evenement is not None:
            evenements.append(evenement)

    ordre = [r for r in ouverture["tours"] if r != "critique_decisions"] + (
        ["critique_decisions"] if "critique_decisions" in ouverture["tours"] else []
    )
    textes_admis: list[tuple[str, list[str]]] = []
    for role in ordre:
        sorties = _sorties_du_role(double, role)
        if not sorties:
            ajouter(
                sessions_conseil.abandonner(
                    evenements, session_id, role, "aucune sortie figée fournie pour ce rôle", recu_a=horodatage
                )
            )
            continue
        for sortie in sorties:
            compte += 1
            try:
                ajouter(
                    sessions_conseil.deposer(
                        evenements,
                        session_id,
                        role,
                        copy.deepcopy(sortie),
                        reservation_id=f"double-{cas['id']}-{compte}",
                        tokens_reels=0,
                        recu_a=horodatage,
                    )
                )
            except ValueError as exc:
                observe.setdefault("erreurs_contexte", []).append({"role": role, "code": _code(exc)})
                break
    projection = sessions_conseil.etat(evenements, session_id)
    observe["tours"] = {}
    for tour in projection["tours"]:
        depots = [e for e in evenements if e["type"] == "TOUR" and e["role"] == tour["role"]]
        observe["tours"][tour["role"]] = {
            "statut": tour["statut"],
            "depots": [
                {
                    "issue": e["issue"],
                    "code": e["code"],
                    "demandes_ecartees": (e["proposition"] or {}).get("demandes_ecartees"),
                    "statuts": {a["id"]: a["statut"] for a in (e["proposition"] or {}).get("affirmations", [])},
                }
                for e in depots
            ],
        }
        for e in depots:
            if e["proposition"]:
                textes_admis += _textes_libres(e["proposition"])
                for a in e["proposition"]["affirmations"]:
                    if a["nature"] == "observation_source" and dossier["faits"].get(a["reference"]) != a["valeur"]:
                        observe["invariants_violes"].append(
                            f"I1 citation admise sans correspondance exacte ({a['id']})"
                        )
    try:
        cloture = sessions_conseil.cloturer(evenements, session_id, recu_a=horodatage)
    except ValueError as exc:
        observe["cloture"] = {"issue": "ERREUR", "code": _code(exc)}
        return observe
    gouvernance = cloture["gouvernance"]
    rapport = cloture["rapport"]
    observe["cloture"] = {
        "issue": cloture["issue"],
        "autorite_d_effet": cloture["autorite_d_effet"],
        "actions": {a["action"]: a["verdict"] for a in (gouvernance or {}).get("actions", [])},
        "mandataires": {a["action"]: a["mandataire"] for a in (gouvernance or {}).get("actions", [])},
        "decision_majeure": (gouvernance or {}).get("decision_majeure"),
        "sections": {
            cle: rapport["sections"][cle]["statut"]
            for cle in ("decision_recommandee", "donnees_manquantes", "contradictions", "hypotheses", "diagnostic")
        },
    }
    if cloture["autorite_d_effet"] is not False:
        observe["invariants_violes"].append("I3 autorité d'effet non nulle")
    if any(a["effet_autorise"] for a in (gouvernance or {}).get("actions", [])):
        observe["invariants_violes"].append("I3 effet autorisé par la gouvernance")
    if cloture["issue"] == "ABSTENTION" and rapport["sections"]["decision_recommandee"]["statut"] == "RENSEIGNEE":
        observe["invariants_violes"].append("I5 décision renseignée malgré l'abstention")
    for texte, citees in textes_admis:
        libres = montants_libres(texte, citees)
        if libres:
            observe["invariants_violes"].append(f"I6 montant ou date libres sans source dans un texte admis : {libres}")
    return observe


# --------------------------------------------------------------------------------------------------------------------
# Chemin « direction » : registre de snapshots → dossier de direction → audit des affirmations
# --------------------------------------------------------------------------------------------------------------------
class _Copie:
    def __init__(self, lignes: list[dict]) -> None:
        self._lignes = lignes

    def lire(self) -> list[dict]:
        return copy.deepcopy(self._lignes)


def _executer_direction(cas: Mapping) -> dict:
    entree = cas["entree"]
    reg = registre.RegistreSnapshots()
    maillons = []
    for snapshot in entree["snapshots"]:
        maillon, _ = reg.ajouter(copy.deepcopy(snapshot))
        maillons.append(maillon)
    budget = entree.get("budget_caracteres", 20000)
    observe: dict = {"invariants_violes": []}
    dossier = dossier_direction.construire_dossier(
        _Copie(reg.lire()), entree["question"], entree["modules_attendus"], budget_caracteres=budget
    )
    observe["dossier"] = {
        "modules_manquants": dossier["modules_manquants"],
        "contradictions": len(dossier["contradictions"]),
        "selection": {m: f["horodatage"] for m, f in sorted(dossier["faits_selectionnes"].items())},
        "selection_index": {m: f["index"] for m, f in sorted(dossier["faits_selectionnes"].items())},
    }
    affirmations = []
    for brute in entree["affirmations"]:
        a = copy.deepcopy(brute)
        if a["nature"] == "observation_source":
            cible = maillons[a.pop("snapshot")]
            a["reference"] = {
                "module_source": cible["module_source"],
                "index": cible["index"],
                "hash_maillon": cible["hash_maillon"],
                "cle": a.pop("cle"),
            }
            for cle, valeur in a.pop("reference_forcee", {}).items():
                a["reference"][cle] = valeur
        affirmations.append(a)
    try:
        resultat = auditer_affirmations(dossier, dossier["dossier_id"], affirmations, budget_caracteres=budget)
    except ValueError as exc:
        observe["audit"] = {"issue": "REFUSE", "code": _code(exc)}
        return observe
    audit = resultat["audit"]
    observe["audit"] = {
        "issue": "ADMIS",
        "statuts": {a["id"]: a["statut"] for a in audit["affirmations"]},
        "validation_metier": audit["validation_metier"],
        "actualite_metier": audit["actualite_metier"],
        "decision_validee": audit["decision_validee"],
        "conseil_execute": audit["conseil_execute"],
        "modele_execute": audit["modele_execute"],
    }
    if audit["decision_validee"] is not False or audit["validation_metier"] != "NON_PROUVEE":
        observe["invariants_violes"].append("I3 l'audit prétend valider une décision ou la vérité métier")
    return observe


# --------------------------------------------------------------------------------------------------------------------
# Chemins « previsions », « priorisation », « occasions » : lecture de calculs de propriétaires, jamais de calcul de M9
# --------------------------------------------------------------------------------------------------------------------
def _executer_previsions(cas: Mapping) -> dict:
    entree = cas["entree"]
    chaine, refus_captures = _captures(entree["captures"])
    resultat = previsions.consolider(
        chaine, connaissance=entree["connaissance"], perime_apres_jours=entree.get("perime_apres_jours")
    )
    observe: dict = {"invariants_violes": [], "captures_refusees": [r["code"] for r in refus_captures], "domaines": {}}
    for d in resultat["domaines"]:
        projection = {"statut": d["statut"], "proprietaire": d["proprietaire"]}
        if "courante" in d:
            version = next(v for v in d["versions"] if v["capture"] == d["courante"])
            projection["courante"] = d["courante"]
            projection["valeurs"] = version["valeurs"]
            projection["age_jours"] = version["age_jours"]
            projection["incertitude_chiffree"] = d["incertitude"]["chiffree"]
        projection["statuts_versions"] = [v["statut"] for v in d["versions"]]
        observe["domaines"][d["domaine"]] = projection
        if d["statut"] in ("AUCUNE_PREVISION_PRODUITE", "ABSENTE") and ("valeurs" in d or "courante" in d):
            observe["invariants_violes"].append(f"I2 valeur produite pour le domaine sans prévision {d['domaine']}")
    return observe


def _executer_priorisation(cas: Mapping) -> dict:
    entree = cas["entree"]
    chaine, refus_captures = _captures(entree.get("captures", []))
    dossier = ds.construire(
        chaine,
        question="Quelles priorités tenir avec la capacité connue ?",
        domaines=["capacite", "leads"],
        reference=entree["reference"],
        connaissance=entree["connaissance"],
        attendues=entree["attendues"],
    )
    adresse = entree.get("capacite_fait")
    capacite = dossier["faits"].get(adresse) if adresse is not None else entree.get("capacite_declaree")
    source = adresse if adresse is not None and capacite is not None else None
    observe: dict = {"invariants_violes": [], "captures_refusees": [r["code"] for r in refus_captures]}
    observe["capacite_utilisee"] = capacite
    try:
        resultat = priorisation.allouer(entree["candidats"], capacite=capacite, source_capacite=source)
    except ValueError as exc:
        observe["allocation"] = {"statut": "REFUSE", "code": _code(exc)}
        return observe
    allocation = resultat["allocation"]
    observe["allocation"] = {"statut": allocation["statut"]}
    observe["classement"] = [c["id"] for c in resultat["classement"]]
    observe["scores"] = {c["id"]: c["score"] for c in resultat["classement"]}
    observe["retenus"] = [r["id"] for r in resultat["retenus"]]
    observe["statuts_retenus"] = {r["id"]: r["statut"] for r in resultat["retenus"]}
    observe["non_retenus"] = {n["id"]: n["raison"] for n in resultat["non_retenus"]}
    observe["conflits"] = [c["entre"] for c in resultat["conflits"]]
    if allocation["statut"] == "PROPOSEE":
        observe["allocation"] |= {"utilisee": allocation["utilisee"], "restante": allocation["restante"]}
        observe["alternatives"] = [(a["retirer"], a["ajouter"]) for a in resultat["alternatives"]]
    if capacite is None and resultat["retenus"]:
        observe["invariants_violes"].append("I2 allocation proposée sans capacité citée")
    return observe


def _executer_occasions(cas: Mapping) -> dict:
    entree = cas["entree"]
    chaine, refus_captures = _captures(entree.get("captures", []))
    dossier = ds.construire(
        chaine,
        question="Quelles occasions documenter ?",
        domaines=["strategie"],
        reference=entree["reference"],
        connaissance=entree["connaissance"],
        attendues=entree["attendues"],
    )
    observe: dict = {"invariants_violes": [], "captures_refusees": [r["code"] for r in refus_captures]}
    try:
        resultat = occasions.evaluer(entree["occasions"], dossier["faits"], chaine, connaissance=entree["connaissance"])
    except ValueError as exc:
        observe["radar"] = {"issue": "REFUSE", "code": _code(exc)}
        return observe
    observe["radar"] = {"issue": "EVALUE"}
    observe["occasions"] = {
        o["id"]: {
            "statut": o["statut"],
            "manques": o["manques"],
            "confiance": o["confiance"],
            "decision": o["decision"],
            "cout": (o["cout"] or {}).get("texte"),
            "capacite": (o["capacite"] or {}).get("texte"),
        }
        for o in resultat["occasions"]
    }
    observe["signaux_mesures"] = [s["id"] for s in resultat["signaux_mesures"]]
    return observe


EXECUTEURS = {
    "conseil": _executer_conseil,
    "direction": _executer_direction,
    "previsions": _executer_previsions,
    "priorisation": _executer_priorisation,
    "occasions": _executer_occasions,
}


def executer_cas(cas: Mapping) -> dict:
    """Résultat observé d'un cas dans le chemin M9 qu'il déclare. Aucune branche par identifiant de cas."""
    return EXECUTEURS[cas["chemin"]](cas)


def evaluer_cas(cas: Mapping) -> dict:
    observe = executer_cas(cas)
    attentes = dict(cas["attentes"])
    attentes.setdefault("invariants_violes", [])
    ecarts = _ecarts_sous_ensemble(attentes, observe)
    return {
        "id": cas["id"],
        "famille": cas["famille"],
        "partition": cas["partition"],
        "ecarts": ecarts,
        "observe": observe,
    }


# --------------------------------------------------------------------------------------------------------------------
# Mesures : effectifs, cas rouges, abstention, intervalles de Wilson, limites
# --------------------------------------------------------------------------------------------------------------------
def _bloc(resultats: Sequence[Mapping]) -> dict:
    n = len(resultats)
    ok = sum(1 for r in resultats if not r["ecarts"])
    bas, haut = wilson(ok, n)
    return {
        "effectif": n,
        "reussites": ok,
        "taux": f"{(ok / n) if n else 0:.4f}",
        "wilson95": [bas, haut],
        "rouges": [{"id": r["id"], "ecarts": r["ecarts"]} for r in resultats if r["ecarts"]],
    }


def _proportion(k: int, n: int) -> dict:
    bas, haut = wilson(k, n)
    return {"k": k, "n": n, "taux": f"{(k / n) if n else 0:.4f}", "wilson95": [bas, haut]}


def _mesures_conseil(cas_liste: Sequence[Mapping], resultats: Sequence[Mapping]) -> dict:
    """Refus et abstentions des sessions de conseil : attendus (écrits à la main) contre observés, par famille."""
    familles: dict[str, dict] = {}
    for cas, res in zip(cas_liste, resultats, strict=True):
        if cas["chemin"] != "conseil":
            continue
        bloc = familles.setdefault(
            cas["famille"],
            {"sessions": 0, "abstentions_attendues": 0, "abstentions_observees": 0, "depots": 0, "refus": 0},
        )
        bloc["sessions"] += 1
        bloc["abstentions_attendues"] += (
            cas["attentes"].get("cloture", {}).get("issue") == "ABSTENTION"
            or cas["attentes"].get("ouverture", {}).get("issue") == "REFUSEE"
        )
        bloc["abstentions_observees"] += (
            res["observe"].get("cloture", {}).get("issue") == "ABSTENTION"
            or res["observe"].get("ouverture", {}).get("issue") == "REFUSEE"
        )
        for tour in res["observe"].get("tours", {}).values():
            for depot in tour["depots"]:
                bloc["depots"] += 1
                bloc["refus"] += depot["issue"] == "REFUSE"

    def somme(cle: str) -> int:
        return sum(b[cle] for b in familles.values())

    return {
        "sessions": somme("sessions"),
        "abstention_attendue": _proportion(somme("abstentions_attendues"), somme("sessions")),
        "abstention_observee": _proportion(somme("abstentions_observees"), somme("sessions")),
        "depots_refuses": _proportion(somme("refus"), somme("depots")),
        "par_famille": {
            f: {
                "sessions": b["sessions"],
                "abstentions_attendues": b["abstentions_attendues"],
                "abstentions_observees": b["abstentions_observees"],
                "depots_figes": b["depots"],
                "depots_refuses": b["refus"],
            }
            for f, b in sorted(familles.items())
        },
        "note": "un dépôt refusé est souvent le comportement ATTENDU : des sorties fautives sont injectées pour sonder",
    }


def evaluer(corpus: Mapping, *, partition: str | None = None, horloge: Callable[[], float] | None = None) -> dict:
    """Rejoue les cas (d'une partition ou de toutes) et rend effectifs, cas rouges, abstentions, limites.

    ``horloge`` : chronomètre injecté par l'appelant (module pur : aucune horloge interne, ADR-0009) ; sans lui, la
    latence du harnais est UNKNOWN."""
    cas_liste = valider_corpus_metier(corpus)
    fuites = fuites_entre_partitions(corpus)
    if partition is not None:
        if partition not in PARTITIONS:
            raise _refus("REJ-EVALMETIER-PARTITION", "ajustement ou verification")
        cas_liste = [c for c in cas_liste if c["partition"] == partition]
    depart = horloge() if horloge else None
    resultats = [evaluer_cas(c) for c in cas_liste]
    duree = (horloge() - depart) if horloge and depart is not None else None
    par_famille = {
        f: {
            p: _bloc([r for r in resultats if r["famille"] == f and r["partition"] == p])
            for p in PARTITIONS
            if partition in (None, p)
        }
        for f in FAMILLES
    }
    par_partition = {
        p: _bloc([r for r in resultats if r["partition"] == p]) for p in PARTITIONS if partition in (None, p)
    }
    par_perturbation = {
        t: _bloc([r for c, r in zip(cas_liste, resultats, strict=True) if t in c["perturbations"]])
        for t in PERTURBATIONS
    }
    rapport = {
        "type": "EVALUATION_METIER_M9",
        "version": VERSION,
        "corpus": corpus.get("version"),
        "corpus_sha256": hashlib.sha256(
            json.dumps(corpus, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
        ).hexdigest(),
        "sceaux_partitions": {p: empreinte_partition(corpus, p) for p in PARTITIONS},
        "partition_evaluee": partition or "toutes",
        "portee": "couche déterministe M9 (captures, dossier, session de conseil, audit, gouvernance, prévisions, "
        "priorisation, occasions) sur des producteurs simulés et des sorties de modèle FIGÉES",
        "modele_reel": False,
        "verdicts_separes": {
            "double_de_protocole_deterministe": "MESURE_ICI",
            "qualite_metier_conseil": "NON_ETABLIE",
            "qualification_modele_reel": "OUVERTE",
            "execution_core_native": "OUVERTE",
        },
        "fuites_entre_partitions": fuites,
        "effectifs": {
            "cas": len(cas_liste),
            "par_famille_partition": {f: {p: par_famille[f][p]["effectif"] for p in par_famille[f]} for f in FAMILLES},
        },
        "par_famille": par_famille,
        "par_partition": par_partition,
        "par_perturbation": par_perturbation,
        "global": _bloc(resultats),
        "conseil": _mesures_conseil(cas_liste, resultats),
        "cas_rouges": [
            {"id": r["id"], "famille": r["famille"], "partition": r["partition"], "ecarts": r["ecarts"]}
            for r in resultats
            if r["ecarts"]
        ],
        "mesures_modele": {
            "latence": STATUT_INCONNU,
            "tokens": STATUT_INCONNU,
            "cout": STATUT_INCONNU,
            "raison": "aucun modèle appelé : sorties figées",
        },
        "latence_harnais_secondes": round(duree, 6) if duree is not None else STATUT_INCONNU,
        "biais_connus": list(BIAIS_CONNUS),
        "limites": list(LIMITES),
    }
    return rapport
