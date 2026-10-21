"""Déclarations non attestées, registre séparé ; aucun mouvement ni source YAML."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from datetime import date, datetime

from . import calendrier_obligations, registre

# Private dispatch/page order of the closed, caller-specified RPC contract.
# This does not classify an ambiguous expense: unknown amounts/dates remain null.
_CATEGORIES_PREPARATOIRES = ("paies", "das", "dettes")
REGISTRE = "obligations_preparees"
TYPES = {"declarer": "declaration_obligation_preparee", "retirer": "retrait_obligation_preparee"}
CHAMPS_CALENDRIER = frozenset(
    {
        "autorite",
        "periode_debut",
        "periode_fin",
        "echeance_source",
        "source_consultee_le",
        "source_applicable_du",
        "source_applicable_jusqu_au",
        "annee",
        "version",
    }
)
CHAMPS_ARGS = frozenset({"categorie", "operation", "declaration", "revision_attendue", "motif"})
CHAMPS_REFERENCE = frozenset({"registre", "index", "ligne_id", "precedent_ligne_id"})
CHAMPS_ENTREE = frozenset(
    {
        "type_entree",
        "version_schema",
        "categorie",
        "operation",
        "declaration",
        "revision_precedente",
        "motif",
        "auteur",
        "intention",
        "horodatage",
        "horodatage_appareil_declare",
    }
)
DETAILS = {
    "ARGUMENTS-INVALIDES": "arguments fermés invalides de déclaration préparatoire",
    "REGISTRE-INVALIDE": "registre préparatoire absent, contradictoire ou corrompu",
    "SOURCE-TROP-VOLUMINEUSE": "registre préparatoire au-delà de 10000 maillons",
    "REVISION-PERIMEE": "la révision courante de cette catégorie a changé",
    "SORTIE-TROP-VOLUMINEUSE": "enveloppe préparatoire au-delà de la borne courante",
    "IDENTITE-INVALIDE": "admin DEVICE actif et confirmé requis",
    "CONTEXTE-ABSENT": "intention et réception serveur vérifiables requises",
    "REJEU-INCOHERENT": "aucune confirmation propre à cette intention ne peut être établie",
}


class Refus(ValueError):
    def __init__(self, suffixe):
        self.suffixe = suffixe
        super().__init__(DETAILS[suffixe])

    @property
    def verdict(self):
        return {"code": "REJ-M5-OBLIGATIONS-" + self.suffixe, "detail": DETAILS[self.suffixe]}


def ferme(value, keys):
    if type(value) is not dict or set(value) != set(keys):
        raise Refus("ARGUMENTS-INVALIDES")


def texte(v, maximum=None, vide=False):
    return (
        type(v) is str
        and (vide or bool(v.strip()))
        and (maximum is None or len(v) <= maximum)
        and not any(0xD800 <= ord(c) <= 0xDFFF for c in v)
    )


def jour(v):
    if type(v) is not str or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", v) is None:
        raise Refus("ARGUMENTS-INVALIDES")
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise Refus("ARGUMENTS-INVALIDES") from None


def instant(v):
    if not texte(v):
        raise Refus("ARGUMENTS-INVALIDES")
    try:
        if datetime.fromisoformat(v).tzinfo is None:
            raise ValueError()
    except ValueError:
        raise Refus("ARGUMENTS-INVALIDES") from None


def hash_valide(v):
    return type(v) is str and re.fullmatch(r"[0-9a-f]{64}", v) is not None


def valider_reference(v):
    if v is None:
        return
    ferme(v, CHAMPS_REFERENCE)
    if (
        v["registre"] != REGISTRE
        or type(v["index"]) is not int
        or not 0 <= v["index"] <= 9999
        or not hash_valide(v["ligne_id"])
        or (v["precedent_ligne_id"] is not None and not hash_valide(v["precedent_ligne_id"]))
    ):
        raise Refus("ARGUMENTS-INVALIDES")


def valider_mutation(arguments):
    ferme(arguments, CHAMPS_ARGS)
    a = copy.deepcopy(arguments)
    if (
        a["categorie"] not in _CATEGORIES_PREPARATOIRES
        or type(a["categorie"]) is not str
        or type(a["operation"]) is not str
        or a["operation"] not in TYPES
        or not texte(a["motif"], 500, vide=a["operation"] == "declarer")
    ):
        raise Refus("ARGUMENTS-INVALIDES")
    valider_reference(a["revision_attendue"])
    d = a["declaration"]
    if a["operation"] == "retirer":
        if d is not None:
            raise Refus("ARGUMENTS-INVALIDES")
        return a
    ferme(d, {"montant", "source", "au", "echeance", "calendrier"})
    if d["montant"] is not None and (
        type(d["montant"]) is not str or re.fullmatch(r"[0-9]{1,12}(\.[0-9]{1,2})?", d["montant"]) is None
    ):
        raise Refus("ARGUMENTS-INVALIDES")
    if d["source"] is not None and not texte(d["source"], 120):
        raise Refus("ARGUMENTS-INVALIDES")
    for key in ("au", "echeance"):
        if d[key] is not None:
            jour(d[key])
    cal = d["calendrier"]
    if cal is not None:
        ferme(cal, CHAMPS_CALENDRIER)
        for key in CHAMPS_CALENDRIER:
            value = cal[key]
            if value is None:
                continue
            if key == "annee":
                if type(value) is not int or not 1 <= value <= 9999:
                    raise Refus("ARGUMENTS-INVALIDES")
            elif key in {"autorite", "echeance_source", "version"}:
                if not texte(value, 240):
                    raise Refus("ARGUMENTS-INVALIDES")
            else:
                jour(value)
        for debut, fin in (("periode_debut", "periode_fin"), ("source_applicable_du", "source_applicable_jusqu_au")):
            if cal[debut] is not None and cal[fin] is not None and jour(cal[debut]) > jour(cal[fin]):
                raise Refus("ARGUMENTS-INVALIDES")
    return a


def valider_lecture(arguments):
    ferme(arguments, {"aujourd_hui", "decalage", "limite"})
    jour(arguments["aujourd_hui"])
    if (
        type(arguments["decalage"]) is not int
        or not 0 <= arguments["decalage"] <= 10000
        or type(arguments["limite"]) is not int
        or not 1 <= arguments["limite"] <= 8
    ):
        raise Refus("ARGUMENTS-INVALIDES")
    return copy.deepcopy(arguments)


def empreinte(arguments):
    return hashlib.sha256(
        json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def construire_entree(arguments, auteur, intention, horodatage, horodatage_appareil):
    a = valider_mutation(arguments)
    ferme(auteur, {"personne", "role", "source"})
    ferme(intention, {"appareil_id", "intention_uuid", "empreinte_arguments"})
    if (
        not texte(auteur["personne"])
        or auteur["role"] != "admin"
        or auteur["source"] != "appareil"
        or not texte(intention["appareil_id"])
        or not texte(intention["intention_uuid"])
        or not hash_valide(intention["empreinte_arguments"])
    ):
        raise Refus("ARGUMENTS-INVALIDES")
    instant(horodatage)
    instant(horodatage_appareil)
    return {
        "type_entree": TYPES[a["operation"]],
        "version_schema": 1,
        "categorie": a["categorie"],
        "operation": a["operation"],
        "declaration": a["declaration"],
        "revision_precedente": a["revision_attendue"],
        "motif": a["motif"],
        "auteur": copy.deepcopy(auteur),
        "intention": copy.deepcopy(intention),
        "horodatage": horodatage,
        "horodatage_appareil_declare": horodatage_appareil,
    }


def reference(m, index):
    if type(index) is not int or not 0 <= index < 10000:
        raise Refus("SOURCE-TROP-VOLUMINEUSE")
    return {
        "registre": REGISTRE,
        "index": index,
        "ligne_id": m["ligne_id"],
        "precedent_ligne_id": m["precedent_ligne_id"],
    }


def snapshot_courant(maillons):
    snapshot = copy.deepcopy(list(maillons))
    if len(snapshot) > 10000:
        raise Refus("SOURCE-TROP-VOLUMINEUSE")
    current = {}
    pairs = set()
    try:
        for index, m in enumerate(snapshot):
            ferme(m, CHAMPS_ENTREE | {"ligne_id", "precedent_ligne_id"})
            if type(m["version_schema"]) is not int or m["version_schema"] != 1:
                raise Refus("REGISTRE-INVALIDE")
            args = {
                "categorie": m["categorie"],
                "operation": m["operation"],
                "declaration": m["declaration"],
                "revision_attendue": m["revision_precedente"],
                "motif": m["motif"],
            }
            expected = construire_entree(
                args, m["auteur"], m["intention"], m["horodatage"], m["horodatage_appareil_declare"]
            )
            if any(m[k] != expected[k] for k in CHAMPS_ENTREE):
                raise Refus("REGISTRE-INVALIDE")
            verifier_revision(current, args)
            pair = (m["intention"]["appareil_id"], m["intention"]["intention_uuid"])
            if pair in pairs or m["intention"]["empreinte_arguments"] != empreinte(args):
                raise Refus("REGISTRE-INVALIDE")
            pairs.add(pair)
            current[m["categorie"]] = {"maillon": m, "reference": reference(m, index)}
        if not registre.Registre(snapshot).valider_chaine()[0]:
            raise Refus("REGISTRE-INVALIDE")
    except (KeyError, TypeError, ValueError):
        raise Refus("REGISTRE-INVALIDE") from None
    return current


def verifier_revision(current, arguments):
    old = current.get(arguments["categorie"])
    if arguments["revision_attendue"] != (old["reference"] if old else None):
        raise Refus("REVISION-PERIMEE")


def projection(m, ref):
    return {
        "categorie": m["categorie"],
        "etat_declaration": "DECLAREE" if m["operation"] == "declarer" else "RETIREE",
        "declaration": copy.deepcopy(m["declaration"]),
        "reference": copy.deepcopy(ref),
        "revision_precedente": copy.deepcopy(m["revision_precedente"]),
        "auteur": copy.deepcopy(m["auteur"]),
        "intention": copy.deepcopy(m["intention"]),
        "enregistree_le": m["horodatage"],
        "horodatage_appareil_declare": m["horodatage_appareil_declare"],
    }


def lire(maillons, aujourd_hui, decalage, limite):
    a = valider_lecture({"aujourd_hui": aujourd_hui, "decalage": decalage, "limite": limite})
    if decalage > len(_CATEGORIES_PREPARATOIRES):
        raise Refus("ARGUMENTS-INVALIDES")
    current = snapshot_courant(maillons)
    declared = {k: v["maillon"]["declaration"] for k, v in current.items() if v["maillon"]["declaration"] is not None}
    calendars = calendrier_obligations.lire_obligations_documentees(
        aujourd_hui,
        declared,
        {k: v["echeance"] for k, v in declared.items()},
        {k: v["calendrier"] for k, v in declared.items()},
    )
    cal_by = {v["id"]: v for v in calendars["obligations"]}
    rows = []
    for cat in _CATEGORIES_PREPARATOIRES[decalage : decalage + limite]:
        item = current.get(cat)
        row = (
            projection(item["maillon"], item["reference"])
            if item
            else {
                "categorie": cat,
                "etat_declaration": "ABSENTE",
                **{
                    k: None
                    for k in (
                        "declaration",
                        "reference",
                        "revision_precedente",
                        "auteur",
                        "intention",
                        "enregistree_le",
                        "horodatage_appareil_declare",
                    )
                },
            }
        )
        rows.append({**row, "calendrier_preparatoire": cal_by[cat]})
    suivant = decalage + len(rows)
    return {
        "type": "DECLARATIONS_PREPARATOIRES_OBLIGATIONS",
        "version_schema": 1,
        "aujourd_hui": a["aujourd_hui"],
        "source_canonique": "REGISTRE_PREPARATOIRE_DURABLE",
        "registre": REGISTRE,
        "decalage": decalage,
        "limite": limite,
        "total": 3,
        "decalage_suivant": suivant if suivant < 3 else None,
        "obligations": rows,
        "mention": "Analyse préparatoire IA",
        "couverture": {
            "categories": "paies_das_dettes_seulement",
            "echeances": "a_verifier_sans_etat_paiement",
            "montants": "declares_non_attestes",
            "pages": "courantes_non_figees",
            "plafond_lignes": 10000,
            "source": "registre_preparatoire_sans_activation_YAML_cash_CFO",
        },
    }
