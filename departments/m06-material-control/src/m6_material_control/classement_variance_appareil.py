"""Classement humain de variance, projections et chaîne pures; aucune écriture stock."""

from __future__ import annotations

import copy
import json
import unicodedata

from . import contrats, encodage, pertes_appareil
from . import preuves_pertes_bris_appareil as preuves

BORNE_SORTIE = 5400
PLAFOND_LIGNES = 10000
REGISTRE = "classements_variance"
LISTE = "m6_lister_variances_classables_wct_appareil"
ECRIRE = "m6_classer_cause_variance_appareil"
HISTO = "m6_lire_historique_classement_variance_appareil"
NOMS = frozenset({LISTE, ECRIRE, HISTO})
COUVERTURE = {
    "eligibilite": "critique_publiee_ou_perte_bris_liee",
    "autres_ecarts": "hors_perimetre",
    "preuves": "association_sans_inference_de_cause_ni_authenticite_scene",
    "dates": "reception_serveur_sans_date_du_dommage",
    "plafond_sources": PLAFOND_LIGNES,
}


class Refus(Exception):
    """Refus contrôlé, traduit uniquement hors du savepoint d'écriture."""

    def __init__(self, suffixe):
        self.suffixe = suffixe
        super().__init__(suffixe)


def refuser(suffixe):
    return {
        "accepte": False,
        "verdict": {
            "code": "REJ-M6-CLASSEMENT-" + suffixe,
            "detail": "le classement ne satisfait pas son contrat ; aucun détail partiel n’est transmis",
        },
    }


def texte(v, maximum=256):
    return (
        type(v) is str
        and bool(v.strip())
        and len(v) <= maximum
        and not any(unicodedata.category(c) in {"Cc", "Cs"} for c in v)
    )


def ferme(v, keys):
    return type(v) is dict and set(v) == set(keys)


def entier(v, maximum=10000):
    return type(v) is int and 0 <= v <= maximum


def reference(m):
    return {"registre": REGISTRE, "index": m["index"], "hash_maillon": m["hash_maillon"]}


def reference_valide(v, registre):
    return (
        ferme(v, {"registre", "index", "hash_maillon"})
        and v["registre"] == registre
        and entier(v["index"], 2**53 - 1)
        and preuves._hash(v["hash_maillon"])
    )


def selection_valide(s):
    if not ferme(s, {"wct_id", "reference_variance", "position_ligne", "materiau_id"}):
        return False
    r = s["reference_variance"]
    return (
        texte(s["wct_id"])
        and texte(s["materiau_id"])
        and entier(s["position_ligne"], 9999)
        and ferme(r, {"type", "evenement_id", "empreinte_charge"})
        and r["type"] == "m6.variance_chantier"
        and texte(r["evenement_id"], 300)
        and r["evenement_id"] == f"m6-variance-{s['wct_id']}-evaluee"
        and preuves._hash(r["empreinte_charge"])
    )


def page_valide(decalage, limite):
    return entier(decalage) and type(limite) is int and 1 <= limite <= 8


def objet(s):
    return encodage.empreinte(s)


def valider_classements(maillons):
    pred = ""
    derniers = {}
    for index, m in enumerate(maillons):
        keys = {
            "index",
            "hash_precedent",
            "hash_maillon",
            "selection",
            "cause",
            "motif",
            "reference_precedente",
            "auteur",
            "appareil_id",
            "classe_le",
            "horodatage_appareil_declare",
            "references_pieces",
        }
        if (
            not ferme(m, keys)
            or type(m["index"]) is not int
            or m["index"] != index
            or m["hash_precedent"] != pred
            or not preuves._hash(m["hash_maillon"])
            or not selection_valide(m["selection"])
            or type(m["cause"]) is not str
            or m["cause"] not in contrats.CAUSES_VARIANCE_CHANTIER
            or not motif_valide(m["motif"])
            or not ferme(m["auteur"], {"personne", "role", "source"})
            or not texte(m["auteur"]["personne"])
            or m["auteur"]["role"] != "admin"
            or m["auteur"]["source"] != "appareil"
            or not texte(m["appareil_id"])
            or not pieces_forme_valide(m["references_pieces"])
        ):
            raise Refus("REGISTRE-INVALIDE")
        try:
            pertes_appareil._instant(m["classe_le"])
            pertes_appareil._instant(m["horodatage_appareil_declare"])
            attendu = derniers.get(objet(m["selection"]))
            if (
                m["reference_precedente"] != attendu
                or encodage.empreinte({k: v for k, v in m.items() if k != "hash_maillon"}) != m["hash_maillon"]
            ):
                raise Refus("REGISTRE-INVALIDE")
        except (KeyError, TypeError, ValueError, pertes_appareil.Refus):
            raise Refus("REGISTRE-INVALIDE") from None
        derniers[objet(m["selection"])] = reference(m)
        pred = m["hash_maillon"]


def motif_valide(v):
    return (
        type(v) is str
        and bool(v.strip())
        and len(v) <= 500
        and not any(
            unicodedata.category(c) == "Cs" or (unicodedata.category(c) == "Cc" and c not in "\t\r\n") for c in v
        )
    )


def pieces_forme_valide(pieces):
    if type(pieces) is not list or len(pieces) > 8:
        return False
    seen = set()
    for p in pieces:
        if not ferme(p, {"reference_mouvement", "reference_preuve", "positions_photos"}):
            return False
        if not reference_valide(p["reference_mouvement"], "principal"):
            return False
        idx = p["reference_mouvement"]["index"]
        if idx in seen:
            return False
        seen.add(idx)
        rp, positions = p["reference_preuve"], p["positions_photos"]
        if rp is not None and not reference_valide(rp, "preuves_pertes_bris"):
            return False
        if type(positions) is not list or len(positions) > 3 or not all(entier(i, 2) for i in positions):
            return False
        if len(set(positions)) != len(positions) or (rp is None and positions):
            return False
    return True


def valider_source(wct, charge, principal, preuve_lignes, classements, nombre_admission):
    if type(charge) is not dict or charge.get("statut_variance") != "evaluee":
        raise Refus("VARIANCE-NON-FINALISEE")
    lignes = charge.get("lignes")
    if type(lignes) is not list:
        raise Refus("SOURCE-INVALIDE")
    if nombre_admission + 1 + len(lignes) + len(principal) + len(preuve_lignes) + len(classements) > PLAFOND_LIGNES:
        raise Refus("BORNE-SOURCES")
    if (
        charge.get("wct_id") != wct["wct_id"]
        or charge.get("intervention_id") != wct["intervention_id"]
        or not texte(charge.get("chantier_id"))
        or charge.get("evenement_id") != f"m6-variance-{wct['wct_id']}-evaluee"
    ):
        raise Refus("LIAISON-INCOHERENTE")
    for ligne in lignes:
        if (
            not ferme(
                ligne, {"materiau", "unite", "quantite_prevue", "quantite_reelle", "ecart_pourcentage", "critique"}
            )
            or not texte(ligne["materiau"])
            or (ligne["unite"] is not None and not texte(ligne["unite"]))
            or any(
                ligne[k] is not None and type(ligne[k]) is not str
                for k in ["quantite_prevue", "quantite_reelle", "ecart_pourcentage"]
            )
            or type(ligne["critique"]) is not bool
        ):
            raise Refus("PROJECTION-INVALIDE")
    if len({ligne["materiau"] for ligne in lignes}) != len(lignes):
        raise Refus("SOURCE-INVALIDE")
    try:
        preuves.valider_snapshots(principal, preuve_lignes)
    except preuves.Refus as exc:
        raise Refus(exc.suffixe) from None
    valider_classements(classements)
    return {"wct": wct, "charge": charge, "principal": principal, "preuves": preuve_lignes, "classements": classements}


def selection(source, position):
    c = source["charge"]
    return {
        "wct_id": c["wct_id"],
        "reference_variance": {
            "type": "m6.variance_chantier",
            "evenement_id": c["evenement_id"],
            "empreinte_charge": encodage.empreinte(c),
        },
        "position_ligne": position,
        "materiau_id": c["lignes"][position]["materiau"],
    }


def pieces_disponibles(source, sel):
    result = []
    for m in source["principal"]:
        if (
            m.get("wct_id") == sel["wct_id"]
            and m["materiau_id"] == sel["materiau_id"]
            and m["chantier_id"] == source["charge"]["chantier_id"]
            and m["type_mouvement"] in {"PERTE", "BRIS"}
        ):
            linked = [p for p in source["preuves"] if p["reference_mouvement"] == preuves.reference("principal", m)]
            if len(linked) > 1:
                raise Refus("LIAISON-INCOHERENTE")
            pr = linked[0] if linked else None
            result.append(
                {
                    "reference_mouvement": preuves.reference("principal", m),
                    "reference_preuve": preuves.reference("preuves_pertes_bris", pr) if pr else None,
                    "positions_photos": list(range(len(pr["photos"]))) if pr else [],
                }
            )
    return result


def choisir(source, sel, *, eligible=False):
    if not selection_valide(sel):
        raise Refus("ARGUMENTS-INVALIDES")
    pos = sel["position_ligne"]
    if pos >= len(source["charge"]["lignes"]) or sel != selection(source, pos):
        raise Refus("SOURCE-PERIMEE")
    if eligible and not (source["charge"]["lignes"][pos]["critique"] or pieces_disponibles(source, sel)):
        raise Refus("LIGNE-HORS-PERIMETRE")


def valider_pieces(source, sel, pieces):
    if not pieces_forme_valide(pieces):
        raise Refus("PIECES-INVALIDES")
    disponibles = pieces_disponibles(source, sel)
    for p in pieces:
        choices = [x for x in disponibles if x["reference_mouvement"] == p["reference_mouvement"]]
        if len(choices) != 1 or p["reference_preuve"] != choices[0]["reference_preuve"]:
            raise Refus("LIAISON-INCOHERENTE")
        if any(i not in choices[0]["positions_photos"] for i in p["positions_photos"]):
            raise Refus("LIAISON-INCOHERENTE")


def projection(m):
    return {
        "reference": reference(m),
        **copy.deepcopy({k: v for k, v in m.items() if k not in {"index", "hash_precedent", "hash_maillon"}}),
    }


def pour_objet(source, sel):
    return [m for m in source["classements"] if m["selection"] == sel]


def construire(source, sel, cause, motif, attendu, pieces, auteur, reception):
    choisir(source, sel, eligible=True)
    if type(cause) is not str or cause not in contrats.CAUSES_VARIANCE_CHANTIER or not motif_valide(motif):
        raise Refus("ARGUMENTS-INVALIDES")
    if attendu is not None and not reference_valide(attendu, REGISTRE):
        raise Refus("ARGUMENTS-INVALIDES")
    valider_pieces(source, sel, pieces)
    old = pour_objet(source, sel)
    previous = reference(old[-1]) if old else None
    if attendu != previous:
        raise Refus("REVISION-PERIMEE")
    m = {
        "index": len(source["classements"]),
        "hash_precedent": source["classements"][-1]["hash_maillon"] if source["classements"] else "",
        "selection": copy.deepcopy(sel),
        "cause": cause,
        "motif": motif,
        "reference_precedente": previous,
        "auteur": auteur,
        "appareil_id": reception.appareil,
        "classe_le": reception.recu_le.isoformat(),
        "horodatage_appareil_declare": reception.horodatage_appareil.isoformat(),
        "references_pieces": copy.deepcopy(pieces),
    }
    m["hash_maillon"] = encodage.empreinte(m)
    return m


def ack(m):
    return {
        "accepte": True,
        "resultat": projection(m),
        "registre": {"taille": m["index"] + 1, "hash_tete": m["hash_maillon"]},
    }


def verifier_borne(dto, limite=5400, *, mutation=False):
    envelope = {"ok": True, "resultat": dto, **({"rejoue": False} if mutation else {})}
    if len(json.dumps(envelope, ensure_ascii=False)) > min(BORNE_SORTIE, limite):
        raise Refus("SORTIE-TROP-VOLUMINEUSE")


def source_projection(source):
    c = source["charge"]
    return {
        "type": "m6.variance_chantier",
        "evenement_id": c["evenement_id"],
        "empreinte_charge": encodage.empreinte(c),
        "statut_variance": c["statut_variance"],
        "horodatage_completion": c["horodatage_completion"],
    }


def pagination(decalage, limite, total, affichees):
    return {
        "decalage": decalage,
        "limite": limite,
        "total": total,
        "affichees": affichees,
        "reste": max(0, total - decalage - affichees),
        "decalage_suivant": decalage + affichees if decalage + affichees < total else None,
        "borne_atteinte": affichees < min(limite, max(0, total - decalage)),
    }


def lire(source, decalage, limite, sel=None, borne=5400):
    if not page_valide(decalage, limite):
        raise Refus("ARGUMENTS-INVALIDES")
    if sel is None:
        values = []
        for i, ligne in enumerate(source["charge"]["lignes"]):
            s = selection(source, i)
            pieces = pieces_disponibles(source, s)
            if ligne["critique"] or pieces:
                old = pour_objet(source, s)
                values.append(
                    {
                        "selection": s,
                        "source_ligne": copy.deepcopy(ligne),
                        "pieces_disponibles_a_selectionner": pieces,
                        "classement_courant": projection(old[-1]) if old else None,
                    }
                )
        key = "lignes"
        dto = {
            "wct": {k: source["wct"][k] for k in ["wct_id", "intervention_id"]}
            | {"chantier_id": source["charge"]["chantier_id"]}
        }
    else:
        choisir(source, sel)
        values = [projection(m) for m in pour_objet(source, sel)]
        key = "historique"
        dto = {"selection": copy.deepcopy(sel)}
    if decalage > len(values):
        raise Refus("PAGINATION-HORS-BORNE")
    dto.update(
        {
            "source_variance": source_projection(source),
            key: [],
            "pagination": pagination(decalage, limite, len(values), 0),
            "couverture": COUVERTURE.copy(),
        }
    )
    verifier_borne(dto, borne)
    for v in values[decalage : decalage + limite]:
        candidate = {
            **dto,
            key: [*dto[key], v],
            "pagination": pagination(decalage, limite, len(values), len(dto[key]) + 1),
        }
        try:
            verifier_borne(candidate, borne)
        except Refus:
            if not dto[key]:
                raise
            break
        dto = candidate
    return dto
