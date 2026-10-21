"""Admission déterministe de citations textuelles et d'hypothèses déclarées.

Le dossier est une capture serveur de confiance : ses empreintes ne sont ni une
preuve d'origine, ni une autorisation. Aucun modèle ni conseil n'est exécuté.
"""
import hashlib
import json
import re
from copy import deepcopy

from .diagnostic_temporel import _capturer_dossier
from .validation import valider_snapshot

__all__ = ["auditer_affirmations"]
_HEX = re.compile(r"[0-9a-f]{64}")
_LIMITES = [
    "Comparaison de champs textuels structurés aux seules sources sélectionnées ; aucune vérification sémantique.",
    "Ni authenticité du producteur, vérité, réception, fraîcheur métier ni couverture complète prouvées.",
    "Aucun agent, modèle, conseil, critique sémantique ou contrôle de gouvernance exécuté.",
    "Aucune décision, approbation d'action majeure, recommandation ou action terrain validée ou exécutée.",
]


def _refus(code, detail):
    return ValueError(code + " : " + detail)


def _json_borne(objet, budget):
    if type(budget) is not int or budget <= 0:
        raise _refus("REJ-AUDIT-BORNE", "budget positif entier requis")
    try:
        representation = json.dumps(objet, ensure_ascii=False, allow_nan=False)
        if len(representation) > budget:
            raise _refus("REJ-AUDIT-BORNE", "document complet au-delà du budget, aucune troncature")
        if json.loads(representation) != objet:
            raise _refus("REJ-AUDIT-ARGUMENT", "JSON sans conversion requis")
    except (TypeError, RecursionError, OverflowError) as exc:
        raise _refus("REJ-AUDIT-ARGUMENT", "document JSON fini et représentable requis") from exc
    except ValueError as exc:
        if str(exc).startswith("REJ-AUDIT-"):
            raise
        raise _refus("REJ-AUDIT-ARGUMENT", "document JSON fini et représentable requis") from exc


def _texte(valeur, maximum, *, vide=False):
    return type(valeur) is str and len(valeur) <= maximum and (vide or bool(valeur))


def _valider_affirmations(dossier_attendu, affirmations, *, budget_caracteres):
    _json_borne({"dossier_attendu": dossier_attendu, "affirmations": affirmations}, budget_caracteres)
    if type(dossier_attendu) is not str or not _HEX.fullmatch(dossier_attendu):
        raise _refus("REJ-AUDIT-ARGUMENT", "empreinte de dossier attendue requise")
    if type(affirmations) is not list or not 1 <= len(affirmations) <= 16:
        raise _refus("REJ-AUDIT-ARGUMENT", "1 à 16 affirmations structurées requises")
    ids = set()
    for affirmation in affirmations:
        if type(affirmation) is not dict or not _texte(affirmation.get("id"), 128):
            raise _refus("REJ-AUDIT-AFFIRMATION", "identifiant textuel borné requis")
        if affirmation["id"] in ids:
            raise _refus("REJ-AUDIT-AFFIRMATION", "identifiants distincts requis")
        ids.add(affirmation["id"])
        nature = affirmation.get("nature")
        if nature == "hypothese":
            if set(affirmation) != {"id", "nature", "enonce"} or not _texte(affirmation["enonce"], 1024):
                raise _refus("REJ-AUDIT-AFFIRMATION", "hypothèse déclarée structurée requise")
        elif nature == "observation_source":
            if set(affirmation) != {"id", "nature", "reference", "valeur"}:
                raise _refus("REJ-AUDIT-AFFIRMATION", "citation structurée exacte requise")
            reference = affirmation["reference"]
            if (type(reference) is not dict
                    or set(reference) != {"module_source", "index", "hash_maillon", "cle"}
                    or not _texte(reference["module_source"], 128)
                    or type(reference["index"]) is not int or reference["index"] < 0
                    or type(reference["hash_maillon"]) is not str or not _HEX.fullmatch(reference["hash_maillon"])
                    or not _texte(reference["cle"], 128)
                    or not _texte(affirmation["valeur"], 2048, vide=True)):
                raise _refus("REJ-AUDIT-AFFIRMATION", "référence exacte et valeur textuelle requises")
        else:
            raise _refus("REJ-AUDIT-AFFIRMATION", "nature structurée inconnue")


def _valider_demande(question, modules_attendus, dossier_attendu, affirmations, *, budget_caracteres):
    """Admission des arguments clients avant tout accès aux sources natives."""
    _json_borne({"question": question, "modules_attendus": modules_attendus,
                 "dossier_attendu": dossier_attendu, "affirmations": affirmations}, budget_caracteres)
    if not _texte(question, 2048) or not question.strip():
        raise _refus("REJ-AUDIT-ARGUMENT", "question textuelle bornée requise")
    if (type(modules_attendus) is not list or not 1 <= len(modules_attendus) <= 16
            or not all(_texte(m, 128) and m.strip() for m in modules_attendus)
            or len(set(modules_attendus)) != len(modules_attendus)):
        raise _refus("REJ-AUDIT-ARGUMENT", "1 à 16 modules distincts requis")
    _valider_affirmations(dossier_attendu, affirmations, budget_caracteres=budget_caracteres)


def auditer_affirmations(dossier_de_confiance, dossier_attendu, affirmations, *, budget_caracteres):
    """Tout le lot est admis ou refusé ; la seule source est cette capture serveur."""
    _json_borne({"dossier_de_confiance": dossier_de_confiance, "dossier_attendu": dossier_attendu,
                 "affirmations": affirmations}, budget_caracteres)
    _valider_affirmations(dossier_attendu, affirmations, budget_caracteres=budget_caracteres)
    dossier = _capturer_dossier(dossier_de_confiance)
    if dossier["dossier_id"] != dossier_attendu:
        raise _refus("REJ-AUDIT-DOSSIER-PERIME", "la capture sélectionnée a changé ; préparer un nouveau dossier")
    affirmations = deepcopy(affirmations)
    preuves = {}
    try:
        for source in [*dossier["preuves"], *dossier["faits_selectionnes"].values()]:
            projection = {cle: source[cle] for cle in ("module_source", "horodatage", "valeurs")}
            valide, _ = valider_snapshot(projection)
            if (valide is not True or type(source["index"]) is not int or source["index"] < 0
                    or type(source["hash_maillon"]) is not str or not _HEX.fullmatch(source["hash_maillon"])):
                raise _refus("REJ-AUDIT-SOURCE", "source textuelle complète requise")
        preuves = {preuve["index"]: preuve for preuve in dossier["preuves"]}
        contradictoires = {
            preuves[contradiction[champ]]["module_source"]
            for contradiction in dossier["contradictions"] for champ in ("ligne_id_a", "ligne_id_b")
        }
    except (KeyError, TypeError) as exc:
        raise _refus("REJ-AUDIT-SOURCE", "preuves de source incohérentes") from exc
    admises = []
    for affirmation in affirmations:
        if affirmation["nature"] == "hypothese":
            statut = "HYPOTHESE_DECLAREE"
        else:
            reference = affirmation["reference"]
            module = reference["module_source"]
            fait = dossier["faits_selectionnes"].get(module)
            if fait is None:
                raise _refus("REJ-AUDIT-SOURCE", "module sans source sélectionnée")
            if module in contradictoires:
                raise _refus("REJ-AUDIT-SOURCE-CONTRADICTOIRE", "source contradictoire, aucune variante arbitrée")
            preuve = preuves.get(reference["index"])
            if (reference["index"] != fait["index"] or reference["hash_maillon"] != fait["hash_maillon"]
                    or preuve is None
                    or json.dumps(preuve, sort_keys=True, ensure_ascii=False, allow_nan=False)
                    != json.dumps(fait, sort_keys=True, ensure_ascii=False, allow_nan=False)
                    or reference["cle"] not in fait["valeurs"]
                    or type(fait["valeurs"][reference["cle"]]) is not str
                    or affirmation["valeur"] != fait["valeurs"][reference["cle"]]):
                raise _refus("REJ-AUDIT-SOURCE", "citation sans correspondance textuelle exacte")
            statut = "SOURCE_CONCORDANTE"
        admises.append({**affirmation, "statut": statut})
    audit = {"type": "AUDIT_AFFIRMATIONS_CONSEIL", "dossier_id": dossier["dossier_id"],
             "etat_id": dossier["etat_id"], "affirmations": admises, "admissible_a_la_revue": True,
             "validation_metier": "NON_PROUVEE", "actualite_metier": "NON_EVALUEE",
             "decision_validee": False, "conseil_execute": False, "modele_execute": False,
             "limites": list(_LIMITES)}
    audit["audit_id"] = hashlib.sha256(json.dumps(
        audit, sort_keys=True, ensure_ascii=False, allow_nan=False,
    ).encode("utf-8")).hexdigest()
    resultat = {"dossier": dossier, "audit": audit}
    _json_borne(resultat, budget_caracteres)
    return resultat
