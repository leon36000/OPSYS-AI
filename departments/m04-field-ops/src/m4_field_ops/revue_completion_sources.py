"""Revue N4 liée aux sources : calculs purs, sans SQL, identité ni horloge courante."""

from __future__ import annotations

import copy
import hashlib
import json
import math

from opsys import contrats_variance_m6 as variance_materiaux

from . import encodage, etats, horodatage, outbox, registre

LIRE = "m4_lire_dossier_revue_completion_appareil"
ECRIRE = "m4_resoudre_revue_completion_sources"
DEPARTEMENT = "m04-field-ops"
BORNE_SORTIE = 5400
BORNE_ARGUMENTS = 1500


class Refus(Exception):
    def __init__(self, suffixe):
        self.suffixe = suffixe
        super().__init__(suffixe)


def verdict(suffixe):
    return {
        "code": "REJ-M4-REVUE-" + suffixe,
        "detail": "la revue ne satisfait pas ses sources et sa signature ; aucun détail partiel n'est transmis",
    }


def _ferme(v, keys):
    return type(v) is dict and set(v) == set(keys)


def empreinte_arguments(v):
    return hashlib.sha256(
        json.dumps(v, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def borner_metier(v, borne=5400, mutation=False):
    for flag in (False, True) if mutation else (None,):
        envelope = {"ok": True, "resultat": v, **({"rejoue": flag} if flag is not None else {})}
        if len(json.dumps(envelope, ensure_ascii=False, allow_nan=False)) > min(BORNE_SORTIE, borne):
            raise Refus("SORTIE-TROP-VOLUMINEUSE")


def _source(reg, source, i):
    if not variance_materiaux.texte(i) or type(source) is not dict:
        raise Refus("ARGUMENTS-INVALIDES")
    if not reg.valider_chaine() or not outbox.verifier_invariants_outbox(reg)[0]:
        raise Refus("REGISTRE-INVALIDE")
    rows = reg.lire()
    completions = [m for m in rows if m.get("intervention_id") == i and type(m.get("wct")) is dict]
    if len(completions) != 1:
        raise Refus("WCT-INCONNU")
    completion = completions[0]
    try:
        if type(source["charge"]) is not dict or "intervention_id" not in source["charge"]:
            raise Refus("SOURCE-INVALIDE")
        charge = source["charge"]
        if charge.get("statut_variance") == "evaluee" and (
            type(charge.get("signal_critique")) is not bool
            or type(charge.get("seuil_pourcentage")) not in (int, float)
            or not math.isfinite(charge["seuil_pourcentage"])
        ):
            raise Refus("SOURCE-INVALIDE")
        if source["wct"] != completion["wct"] or source["charge"].get("intervention_id") != i:
            raise Refus("LIAISON-INCOHERENTE")
        variance_materiaux.valider_source(
            source["wct"],
            source["charge"],
            source["principal"],
            source["preuves"],
            source["classements"],
            source.get("nombre_admission", len(rows)),
            source.get("refus", []),
        )
    except variance_materiaux.Refus as exc:
        raise Refus(exc.suffixe) from None
    except (KeyError, TypeError, AttributeError, ValueError):
        raise Refus("SOURCE-INVALIDE") from None
    transitions = [m for m in rows if m.get("intervention_id") == i and m.get("type_entree") == etats.TYPE_TRANSITION]
    return completion, transitions[-1]


def capture_sources(reg, source, i):
    completion, transition = _source(reg, source, i)
    entries = []
    for k, line in enumerate(source["charge"]["lignes"]):
        if line["critique"]:
            sel = variance_materiaux.selection(source, k)
            previous = variance_materiaux.pour_objet(source, sel)
            entries.append(
                {
                    "position_ligne": k,
                    "materiau_id": line["materiau"],
                    "reference": variance_materiaux.reference(previous[-1]) if previous else None,
                }
            )
    return {
        "wct_id": source["wct"]["wct_id"],
        "chantier_id": source["charge"]["chantier_id"],
        "completion_ligne_id": completion["ligne_id"],
        "transition_attendue_ligne_id": transition["ligne_id"],
        "reference_variance": variance_materiaux.selection(source, 0)["reference_variance"]
        if source["charge"]["lignes"]
        else {
            "type": "m6.variance_chantier",
            "evenement_id": source["charge"]["evenement_id"],
            "empreinte_charge": variance_materiaux.empreinte_charge(source["charge"]),
        },
        "classements": entries,
    }


def dossier(reg, source, i, borne=5400):
    capture = capture_sources(reg, source, i)
    completion, transition = _source(reg, source, i)
    charge = source["charge"]
    lines = []
    for entry in capture["classements"]:
        pos = entry["position_ligne"]
        sel = variance_materiaux.selection(source, pos)
        old = variance_materiaux.pour_objet(source, sel)
        lines.append(
            {
                "selection": sel,
                "source_ligne": copy.deepcopy(charge["lignes"][pos]),
                "classement_courant": variance_materiaux.projection(old[-1]) if old else None,
            }
        )
    result = {
        "version_schema": 1,
        "lecture": "courante",
        "intervention_id": i,
        "statut": transition["statut"],
        "wct": {"wct_id": capture["wct_id"], "intervention_id": i, "chantier_id": capture["chantier_id"]},
        "reference_completion": {"ligne_id": completion["ligne_id"], "hash_maillon": completion["wct"]["hash_maillon"]},
        "reference_transition": {"ligne_id": transition["ligne_id"]},
        "source_variance": {
            **variance_materiaux.source_projection(source),
            "signal_critique": charge["signal_critique"],
            "seuil_pourcentage": charge["seuil_pourcentage"],
        },
        "lignes_critiques": lines,
        "sources": capture,
        "couverture": {
            "positions_critiques": [x["position_ligne"] for x in capture["classements"]],
            "positions_sans_classement": [
                x["position_ligne"] for x in capture["classements"] if x["reference"] is None
            ],
        },
        "bornes": {"limite_arguments_caracteres": BORNE_ARGUMENTS, "limite_enveloppe_caracteres": min(5400, borne)},
    }
    borner_metier({"accepte": True, "resultat": result}, borne)
    return result


def _capture_valide(v):
    if not _ferme(
        v,
        {
            "wct_id",
            "chantier_id",
            "completion_ligne_id",
            "transition_attendue_ligne_id",
            "reference_variance",
            "classements",
        },
    ):
        return False
    if not all(variance_materiaux.texte(v[k]) for k in ["wct_id", "chantier_id"]):
        return False
    if not all(variance_materiaux.hash_valide(v[k]) for k in ["completion_ligne_id", "transition_attendue_ligne_id"]):
        return False
    ref = v["reference_variance"]
    if (
        not _ferme(ref, {"type", "evenement_id", "empreinte_charge"})
        or ref["type"] != "m6.variance_chantier"
        or ref["evenement_id"] != f"m6-variance-{v['wct_id']}-evaluee"
        or not variance_materiaux.hash_valide(ref["empreinte_charge"])
    ):
        return False
    entries = v["classements"]
    return (
        type(entries) is list
        and len(entries) <= 10000
        and all(
            _ferme(x, {"position_ligne", "materiau_id", "reference"})
            and variance_materiaux.entier(x["position_ligne"], 9999)
            and variance_materiaux.texte(x["materiau_id"])
            and (
                x["reference"] is None
                or variance_materiaux.reference_valide(x["reference"], variance_materiaux.REGISTRE)
            )
            for x in entries
        )
    )


def valider_arguments(args):
    if (
        not _ferme(args, {"intervention_id", "decision", "horodatage", "motif", "sources"})
        or not variance_materiaux.texte(args["intervention_id"])
        or type(args["decision"]) is not str
        or args["decision"] not in outbox.DECISIONS_REVUE
        or not variance_materiaux.motif_valide(args["motif"])
        or not _capture_valide(args["sources"])
    ):
        raise Refus("ARGUMENTS-INVALIDES")
    try:
        horodatage.valider_horodatage(args["horodatage"])
    except (ValueError, TypeError):
        raise Refus("HORODATAGE-INVALIDE") from None
    if len(json.dumps(args, ensure_ascii=False, allow_nan=False)) > BORNE_ARGUMENTS:
        raise Refus("ARGUMENTS-TROP-VOLUMINEUX")


def valider_proposition(reg, source, args):
    valider_arguments(args)
    current = capture_sources(reg, source, args["intervention_id"])
    if current != args["sources"]:
        raise Refus("SOURCES-PERIMEES")
    if etats.statut_courant(reg, args["intervention_id"]) != "completed_pending_review":
        raise Refus("TRANSITION-ILLEGALE")
    if args["decision"] == "verifiee" and any(x["reference"] is None for x in current["classements"]):
        raise Refus("COUVERTURE-INCOMPLETE")


def _execution(d, args):
    if (
        not _ferme(
            d,
            {
                "demande_approbation_id",
                "empreinte_arguments_proposition",
                "proposant",
                "approuve_par",
                "role_approbateur",
                "horodatage_decision_serveur",
                "association_decision",
            },
        )
        or not variance_materiaux.texte(d["demande_approbation_id"], 32)
        or d["empreinte_arguments_proposition"] != empreinte_arguments(args)
        or not variance_materiaux.texte(d["approuve_par"])
        or d["role_approbateur"] != "nathan_owner"
    ):
        raise Refus("SIGNATURE-INVALIDE")
    p = d["proposant"]
    a = d["association_decision"]
    if (
        not _ferme(p, {"personne", "role", "appareil_id", "intention_uuid"})
        or p["role"] != "admin"
        or not all(type(p[k]) is str and p[k].strip() for k in p)
        or not _ferme(a, {"appareil_id", "intention_uuid", "empreinte_arguments", "horodatage_appareil_declare"})
        or not all(type(a[k]) is str and a[k].strip() for k in a)
        or not variance_materiaux.hash_valide(a["empreinte_arguments"])
    ):
        raise Refus("SIGNATURE-INVALIDE")
    try:
        horodatage.valider_horodatage(a["horodatage_appareil_declare"])
        horodatage.valider_horodatage(d["horodatage_decision_serveur"])
    except (ValueError, TypeError):
        raise Refus("SIGNATURE-INVALIDE") from None


def preuve_maillon(m):
    return {
        "version_schema": 2,
        "demande_approbation_id": m["demande_approbation_id"],
        "association_decision": copy.deepcopy(m["association_decision"]),
        "empreinte_arguments_proposition": m["empreinte_arguments_proposition"],
        "intervention_id": m["intervention_id"],
        "wct_id": m["sources"]["wct_id"],
        "chantier_id": m["sources"]["chantier_id"],
        "statut": m["statut"],
        "decision": m["decision_revue"],
        "ligne_id": m["ligne_id"],
        "tete_chaine": m["ligne_id"],
        "sources": copy.deepcopy(m["sources"]),
        "approuve_par": m["approuve_par"],
        "role_approbateur": m["role_approbateur"],
        "horodatage_decision_serveur": m["horodatage"],
    }


def enveloppe_decision(preuve):
    return {
        "accepte": True,
        "resultat": {
            "demande_id": preuve["demande_approbation_id"],
            "decision": "approuver",
            "statut": "executee",
            "outil": ECRIRE,
            "departement": DEPARTEMENT,
            "niveau": "N4",
            "decide_par": preuve["approuve_par"],
            "role": preuve["role_approbateur"],
            "decide_le": preuve["horodatage_decision_serveur"],
            "preuve_completion": preuve,
            "issue": {"ok": True, "accepte": True},
        },
    }


def resoudre(reg, source, args, execution, borne=5400):
    try:
        valider_proposition(reg, source, args)
        _execution(execution, args)
        if any(m.get("demande_approbation_id") == execution["demande_approbation_id"] for m in reg.lire()):
            raise Refus("DEMANDE-DEJA-EXECUTEE")
        m = {
            "type_entree": etats.TYPE_TRANSITION,
            "version_schema": 2,
            "intervention_id": args["intervention_id"],
            "statut": "completed_verified" if args["decision"] == "verifiee" else "completed_pending_review",
            "statut_precedent": "completed_pending_review",
            "horodatage": execution["horodatage_decision_serveur"],
            "decision_revue": args["decision"],
            "motif_revue": args["motif"].strip(),
            "horodatage_proposition_declare": args["horodatage"],
            "sources": copy.deepcopy(args["sources"]),
            **copy.deepcopy({k: v for k, v in execution.items() if k != "horodatage_decision_serveur"}),
        }
        preview = {**m, "ligne_id": encodage.empreinte(m, reg.tete())}
        proof = preuve_maillon(preview)
        ack = {"accepte": True, "version_schema": 2, "resultat": proof}
        borner_metier(ack, borne, True)
        borner_metier(enveloppe_decision(proof), borne, True)
    except Refus as exc:
        return None, verdict(exc.suffixe)
    try:
        ident = reg.ajouter(m)
        if ident != preview["ligne_id"] or reg.lire()[-1] != {
            **m,
            "ligne_id": ident,
            "precedent_ligne_id": preview.get("precedent_ligne_id", reg.lire()[-2]["ligne_id"]),
        }:
            raise RuntimeError("projection N4 différente après append")
        borner_metier(ack, borne, True)
        return ack, None
    except Exception as exc:
        raise RuntimeError("panne de la revue N4 après append ; annulation requise") from exc


def preuve_resolution_historique(maillons, demande_id, arguments, proposition, demande):
    try:
        reg = registre.Registre(maillons)
        if not reg.valider_chaine():
            raise Refus("REGISTRE-INVALIDE")
        found = [m for m in reg.lire() if m.get("demande_approbation_id") == demande_id]
        if not found:
            if demande["statut"] == "executee":
                raise Refus("REJEU-INCOHERENT")
            return None, None
        if len(found) != 1 or demande["statut"] != "executee":
            raise Refus("REJEU-INCOHERENT")
        m = found[0]
        expected_keys = {
            "type_entree",
            "version_schema",
            "intervention_id",
            "statut",
            "statut_precedent",
            "horodatage",
            "decision_revue",
            "motif_revue",
            "horodatage_proposition_declare",
            "sources",
            "demande_approbation_id",
            "empreinte_arguments_proposition",
            "proposant",
            "approuve_par",
            "role_approbateur",
            "association_decision",
            "ligne_id",
            "precedent_ligne_id",
        }
        expected_status = "completed_verified" if arguments["decision"] == "verifiee" else "completed_pending_review"
        if (
            not _ferme(m, expected_keys)
            or m["statut_precedent"] != "completed_pending_review"
            or m["statut"] != expected_status
        ):
            raise Refus("REJEU-INCOHERENT")
        valider_arguments(arguments)
        if (
            type(m.get("version_schema")) is not int
            or m["version_schema"] != 2
            or m.get("type_entree") != etats.TYPE_TRANSITION
            or m.get("sources") != arguments["sources"]
            or m.get("intervention_id") != arguments["intervention_id"]
            or m.get("decision_revue") != arguments["decision"]
            or m.get("motif_revue") != arguments["motif"].strip()
            or m.get("horodatage_proposition_declare") != arguments["horodatage"]
            or m.get("empreinte_arguments_proposition") != empreinte_arguments(arguments)
            or m.get("approuve_par") != demande["decide_par"]
            or m.get("role_approbateur") != demande["decide_role"]
            or m.get("horodatage") != demande["decide_le"]
            or m.get("proposant") != proposition["proposant"]
        ):
            raise Refus("REJEU-INCOHERENT")
        _execution(
            {
                k: m[k]
                for k in [
                    "demande_approbation_id",
                    "empreinte_arguments_proposition",
                    "proposant",
                    "approuve_par",
                    "role_approbateur",
                    "association_decision",
                ]
            }
            | {"horodatage_decision_serveur": m["horodatage"]},
            arguments,
        )
        return preuve_maillon(m), None
    except Refus as exc:
        return None, verdict("REGISTRE-INVALIDE" if exc.suffixe == "REGISTRE-INVALIDE" else "REJEU-INCOHERENT")
    except (KeyError, TypeError, ValueError):
        return None, verdict("REJEU-INCOHERENT")


def _objet(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


_HASH_SCHEMA = {"type": "string", "pattern": "^[0-9a-f]{64}$", "minLength": 64, "maxLength": 64}
_REF_SCHEMA = _objet(
    {
        "registre": {"const": "classements_variance"},
        "index": {"type": "integer", "minimum": 0, "maximum": 2**53 - 1},
        "hash_maillon": _HASH_SCHEMA,
    }
)
_SOURCES_SCHEMA = _objet(
    {
        "wct_id": {"type": "string"},
        "chantier_id": {"type": "string"},
        "completion_ligne_id": _HASH_SCHEMA,
        "transition_attendue_ligne_id": _HASH_SCHEMA,
        "reference_variance": _objet(
            {
                "type": {"const": "m6.variance_chantier"},
                "evenement_id": {"type": "string"},
                "empreinte_charge": _HASH_SCHEMA,
            }
        ),
        "classements": {
            "type": "array",
            "maxItems": 10000,
            "items": _objet(
                {
                    "position_ligne": {"type": "integer", "minimum": 0, "maximum": 9999},
                    "materiau_id": {"type": "string"},
                    "reference": {"anyOf": [_REF_SCHEMA, {"type": "null"}]},
                }
            ),
        },
    }
)
SCHEMA_ARGUMENTS = _objet(
    {
        "intervention_id": {"type": "string"},
        "decision": {"type": "string", "enum": list(outbox.DECISIONS_REVUE)},
        "horodatage": {"type": "string"},
        "motif": {"type": "string", "minLength": 1, "maxLength": 500},
        "sources": _SOURCES_SCHEMA,
    }
)
