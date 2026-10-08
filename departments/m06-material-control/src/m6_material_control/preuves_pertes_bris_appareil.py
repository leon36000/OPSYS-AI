"""Chaînes et projections pures des preuves déclarées de pertes/bris.

Les accès CAS, identité, horloges et savepoints appartiennent à outils.py. Une photo
vérifiée prouve l'intégrité de ses octets, jamais la scène ou la cause d'un dommage.
"""

from __future__ import annotations

import copy
import json
import math
import re

from . import contrats_sortie, encodage, pertes_appareil, registre

BORNE_SORTIE = 5400
PLAFOND_LIGNES = 10000
_HASH = re.compile(r"[0-9a-f]{64}\Z")
_CHAMPS = frozenset(
    {
        "index",
        "hash_precedent",
        "hash_maillon",
        "wct_id",
        "intervention_id",
        "chantier_id",
        "position_ligne",
        "reference_mouvement",
        "note",
        "photos",
        "auteur",
        "appareil",
        "enregistre_le",
        "horodatage_appareil_declare",
    }
)
_COUVERTURE = {
    "preuves": "declarations_associees_aux_mouvements",
    "photos": "integrite_et_association_sans_authenticite_scene",
    "dates": "reception_serveur_et_heure_appareil_sans_date_du_dommage",
    "plafond_lignes": PLAFOND_LIGNES,
}


class Refus(Exception):
    """Refus contrôlé, sortant du savepoint avant traduction ; aucun détail source."""

    def __init__(self, suffixe):
        self.suffixe = suffixe
        super().__init__(suffixe)


def refuser(suffixe):
    return {
        "accepte": False,
        "verdict": {
            "code": "REJ-M6-PREUVES-" + suffixe,
            "detail": "la demande de preuves ne satisfait pas son contrat ; aucun détail partiel n’est transmis",
        },
    }


def texte(v):
    return pertes_appareil.texte(v)


def reference(reg, m):
    return {"registre": reg, "index": m["index"], "hash_maillon": m["hash_maillon"]}


def _nombre(v):
    return type(v) is int or (type(v) is float and math.isfinite(v))


def nombre_projectable(v):
    """Même frontière JSON du lecteur mobile : entiers finis exacts JS, jamais arrondis."""
    if type(v) is int:
        return abs(v) <= 2**53 - 1
    return type(v) is float and math.isfinite(v) and (not v.is_integer() or abs(v) <= 2**53 - 1)


def _hash(v):
    return type(v) is str and _HASH.fullmatch(v) is not None


def _metadata(v):
    return type(v) is str and bool(v.strip())


def valider_snapshots(principal, preuves):
    if type(principal) is not list or type(preuves) is not list:
        raise Refus("REGISTRE-INVALIDE")
    if len(principal) + len(preuves) > PLAFOND_LIGNES:
        raise Refus("BORNE-SOURCES")
    champs = {
        "index",
        "type_mouvement",
        "chantier_id",
        "materiau_id",
        "quantite",
        "cout_unitaire",
        "hash_precedent",
        "hash_maillon",
    }
    try:
        for i, m in enumerate(principal):
            if (
                type(m) is not dict
                or not champs <= set(m) <= champs | {"wct_id"}
                or type(m["index"]) is not int
                or m["index"] != i
                or not _metadata(m["chantier_id"])
                or not _metadata(m["materiau_id"])
                or ("wct_id" in m and not _metadata(m["wct_id"]))
                or not _nombre(m["quantite"])
                or not _hash(m["hash_maillon"])
                or (m["cout_unitaire"] is not None and not _nombre(m["cout_unitaire"]))
                or m["type_mouvement"] not in registre.TYPES_MOUVEMENT_VALIDES
            ):
                raise Refus("REGISTRE-INVALIDE")
            if (m["type_mouvement"] in {"PERTE", "BRIS", "CONSOMMATION"} and m["quantite"] >= 0) or (
                m["type_mouvement"] in {"RECEPTION", "RETOUR"} and m["quantite"] <= 0
            ):
                raise Refus("REGISTRE-INVALIDE")
        if not registre.Registre(principal).valider_chaine()[0]:
            raise Refus("REGISTRE-INVALIDE")
        pred = ""
        seen = set()
        for i, p in enumerate(preuves):
            if (
                type(p) is not dict
                or set(p) != _CHAMPS
                or type(p["index"]) is not int
                or p["index"] != i
                or p["hash_precedent"] != pred
                or not _hash(p["hash_maillon"])
                or encodage.empreinte({k: v for k, v in p.items() if k != "hash_maillon"}) != p["hash_maillon"]
                or any(not texte(p[k]) for k in ("wct_id", "intervention_id", "chantier_id"))
                or type(p["position_ligne"]) is not int
                or not 0 <= p["position_ligne"] < 24
                or type(p["auteur"]) is not dict
                or set(p["auteur"]) != {"personne", "role"}
                or not _metadata(p["auteur"]["personne"])
                or p["auteur"]["role"] not in {"employee", "admin"}
                or not _metadata(p["appareil"])
            ):
                raise Refus("REGISTRE-INVALIDE")
            pertes_appareil._instant(p["enregistre_le"])
            pertes_appareil._instant(p["horodatage_appareil_declare"])
            ref = p["reference_mouvement"]
            if (
                type(ref) is not dict
                or set(ref) != {"registre", "index", "hash_maillon"}
                or ref["registre"] != "principal"
                or type(ref["index"]) is not int
                or not 0 <= ref["index"] < len(principal)
                or ref["index"] in seen
            ):
                raise Refus("LIAISON-INCOHERENTE")
            m = principal[ref["index"]]
            if (
                ref != reference("principal", m)
                or m["type_mouvement"] not in {"PERTE", "BRIS"}
                or m.get("wct_id") != p["wct_id"]
                or m["chantier_id"] != p["chantier_id"]
            ):
                raise Refus("LIAISON-INCOHERENTE")
            from . import preuves_pertes_bris as plan_pur

            pseudo = [{"type_ligne": "non_prevu"}] * (p["position_ligne"] + 1)
            pseudo[p["position_ligne"]] = {"type_ligne": "perte"}
            photos = p["photos"]
            if type(photos) is not list:
                raise Refus("REGISTRE-INVALIDE")
            _, code = plan_pur.valider_preuves_lignes(
                pseudo,
                [
                    {
                        "position_ligne": p["position_ligne"],
                        "note": p["note"],
                        "photos": [x["reference"] for x in photos],
                    }
                ],
            )
            if code:
                raise Refus("REGISTRE-INVALIDE")
            for photo in photos:
                if (
                    type(photo) is not dict
                    or set(photo) != {"reference", "empreinte_sha256", "type_mime", "taille_octets"}
                    or not _hash(photo["empreinte_sha256"])
                    or photo["reference"] != "fichier:sha256:" + photo["empreinte_sha256"]
                    or photo["type_mime"] not in {"image/png", "image/jpeg"}
                    or type(photo["taille_octets"]) is not int
                    or not 1 <= photo["taille_octets"] <= 10 * 1024 * 1024
                ):
                    raise Refus("REGISTRE-INVALIDE")
            seen.add(ref["index"])
            pred = p["hash_maillon"]
    except (KeyError, TypeError, ValueError, pertes_appareil.Refus):
        raise Refus("REGISTRE-INVALIDE") from None


def lier_ajouts(avant, apres, formulaire):
    lignes = formulaire["lignes_materiaux"]
    if len(apres) != len(avant) + len(lignes) or apres[: len(avant)] != avant:
        raise Refus("LIAISON-INCOHERENTE")
    for pos, ligne in enumerate(lignes):
        m = apres[len(avant) + pos]
        typ = {
            "prevu": "CONSOMMATION",
            "non_prevu": "CONSOMMATION",
            "retour": "RETOUR",
            "perte": "PERTE",
            "bris": "BRIS",
        }[ligne["type_ligne"]]
        q = ligne["quantite"] if typ == "RETOUR" else -ligne["quantite"]
        if (
            m["index"] != len(avant) + pos
            or m["wct_id"] != formulaire["wct_id"]
            or m["chantier_id"] != formulaire["chantier_id"]
            or m["materiau_id"] != ligne["materiau_id"]
            or m["type_mouvement"] != typ
            or m["quantite"] != q
        ):
            raise Refus("LIAISON-INCOHERENTE")
    return apres[len(avant) :]


def construire_preuve(index, pred, wct, formulaire, plan, mouvement, photos, acteur, horodatage):
    p = {
        "index": index,
        "hash_precedent": pred,
        "wct_id": wct["wct_id"],
        "intervention_id": wct["intervention_id"],
        "chantier_id": formulaire["chantier_id"],
        "position_ligne": plan["position_ligne"],
        "reference_mouvement": reference("principal", mouvement),
        "note": plan["note"],
        "photos": photos,
        "auteur": {"personne": acteur.personne, "role": acteur.role},
        "appareil": horodatage.appareil,
        "enregistre_le": horodatage.recu_le.isoformat(),
        "horodatage_appareil_declare": horodatage.horodatage_appareil.isoformat(),
    }
    p["hash_maillon"] = encodage.empreinte(p)
    return p


def ack(wct, formulaire, liens, taille, tete):
    confirmation = contrats_sortie.construire_confirmation_materiaux_utilises(
        wct["intervention_id"], formulaire["chantier_id"], formulaire["lignes_materiaux"]
    )
    return {
        "accepte": True,
        "resultat": {"wct_id": wct["wct_id"], **confirmation, "preuves": liens},
        "registre": {"taille": taille, "hash_tete": tete},
    }


def verifier_borne(ack_, limite=5400, mutation=False):
    envelope = {"ok": True, "resultat": ack_}
    if mutation:
        envelope["rejoue"] = False
    if len(json.dumps(envelope, ensure_ascii=False, allow_nan=False)) > min(BORNE_SORTIE, limite):
        raise Refus("SORTIE-TROP-VOLUMINEUSE")


def lire(wct, principal, preuves, decalage, limite, verifier_photo):
    valider_snapshots(principal, preuves)
    if (
        type(decalage) is not int
        or not 0 <= decalage <= PLAFOND_LIGNES
        or type(limite) is not int
        or not 1 <= limite <= 8
    ):
        raise Refus("ARGUMENTS-INVALIDES")
    by_index = {p["reference_mouvement"]["index"]: p for p in preuves}
    mouvements = [m for m in principal if m.get("wct_id") == wct["wct_id"] and m["type_mouvement"] in {"PERTE", "BRIS"}]
    items = []
    for m in mouvements[decalage : decalage + limite]:
        if not texte(m["materiau_id"]) or not texte(m["chantier_id"]):
            raise Refus("PROJECTION-INVALIDE")
        p = by_index.get(m["index"])
        vue = {
            "etat": "absente",
            "reference": None,
            "position_ligne": None,
            "note": None,
            "enregistre_le": None,
            "horodatage_appareil_declare": None,
            "photos": [],
        }
        if p is not None:
            if p["intervention_id"] != wct["intervention_id"]:
                raise Refus("LIAISON-INCOHERENTE")
            photos = [
                {"position_photo": k, **photo, "etat_actuel": "disponible" if verifier_photo(photo) else "indisponible"}
                for k, photo in enumerate(p["photos"])
            ]
            vue = {
                "etat": "photos_declarees" if photos else "note_seule",
                "reference": reference("preuves_pertes_bris", p),
                "position_ligne": p["position_ligne"],
                "note": p["note"],
                "enregistre_le": p["enregistre_le"],
                "horodatage_appareil_declare": p["horodatage_appareil_declare"],
                "photos": photos,
            }
        items.append(
            {
                "reference_mouvement": reference("principal", m),
                "materiau_id": m["materiau_id"],
                "type_mouvement": m["type_mouvement"],
                "quantite": pertes_appareil._quantite_signee(m["quantite"]),
                "unite": None,
                "preuve": vue,
            }
        )
    return {
        "wct_id": wct["wct_id"],
        "intervention_id": wct["intervention_id"],
        "decalage": decalage,
        "limite": limite,
        "total": len(mouvements),
        "decalage_suivant": decalage + len(items) if items and decalage + len(items) < len(mouvements) else None,
        "pertes_bris": items,
        "couverture": copy.deepcopy(_COUVERTURE),
    }
