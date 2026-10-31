"""Radar d'occasions M9.13 : des occasions mesurables et leurs conditions, jamais un revenu probable.

Module pur. Une occasion est DÉCLARÉE (par la personne ou comme proposition non validée du conseil) ou tirée d'un SIGNAL
mesuré par un propriétaire (``signaux_mesures`` : devis envoyés sans réponse chez M8). Elle porte ses conditions et ses
alternatives, et ne devient ``DOCUMENTEE`` que si son coût ET la capacité nécessaire sont des faits CITÉS du dossier ;
sinon elle reste ``HYPOTHESE`` avec ce qui manque, nommé. Aucun revenu, gain, marge, probabilité ni date de réalisation
n'est produit ni accepté : une clé de cette nature est refusée. La confiance n'est jamais estimée (``NON_ESTIMEE``) ;
ses limites sont dites (signal absent, coût ou capacité non cités). Une occasion documentée reste une proposition : la
décision et l'engagement sont humains.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence

from . import capture_strategique as cs

VERSION = "2026-10-28.1"
MAX_OCCASIONS = 30
ORIGINES = frozenset({"DECLAREE_PAR_LA_PERSONNE", "PROPOSITION_CONSEIL_NON_VALIDEE", "SIGNAL_MESURE"})
INTERDITS = frozenset(
    {
        "revenu",
        "revenus",
        "gain",
        "gains",
        "marge",
        "chiffre_affaires",
        "probabilite",
        "probabilites",
        "roi",
        "date_realisation",
    }
)
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:\-]{0,63}")
_ADRESSE = re.compile(r"[a-z0-9_.]+#\d+:p\d+\.[A-Za-z0-9_.\[\]]+")
_CHAMPS = frozenset(
    {"id", "libelle", "origine", "conditions", "alternatives", "cout_ref", "capacite_ref", "signaux_refs"}
)
LECTURE_SIGNAL = "m8.vue_executive"
CHEMIN_SIGNAL = "resultat.entonnoir.devis_en_attente.sans_reponse.devis"
_LIMITES = (
    "Occasions déclarées ou signalées par un propriétaire : aucun revenu, gain ni probabilité n'est produit.",
    "DOCUMENTEE = coût et capacité cités ; ce n'est pas une décision, ni une promesse de résultat.",
)


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def _liste_textes(valeur: object, nom: str, maximum: int = 12) -> list[str]:
    if (
        type(valeur) is not list
        or len(valeur) > maximum
        or any(type(x) is not str or not x.strip() or len(x) > 300 for x in valeur)
    ):
        raise _refus("REJ-OCCASION-CHAMP", f"{nom} : liste bornée de textes non vides")
    return list(valeur)


def _ref(valeur: object, faits: Mapping[str, str], nom: str) -> str | None:
    if valeur is None:
        return None
    if type(valeur) is not str or not _ADRESSE.fullmatch(valeur) or valeur not in faits:
        raise _refus("REJ-OCCASION-REF", f"{nom} : adresse absente des faits citables du dossier")
    return valeur


def _occasion(brute: object, faits: Mapping[str, str]) -> dict:
    if not isinstance(brute, Mapping):
        raise _refus("REJ-OCCASION-CHAMP", "occasion objet requise")
    interdits = INTERDITS & {str(cle).lower() for cle in brute}
    if interdits:
        raise _refus("REJ-OCCASION-REVENU", f"clés refusées {sorted(interdits)} : M9 ne produit aucun revenu probable")
    if not {"id", "libelle", "origine"} <= set(brute) <= _CHAMPS:
        raise _refus("REJ-OCCASION-CHAMP", "occasion {id, libelle, origine[, conditions, alternatives, …]} requise")
    if type(brute["id"]) is not str or not _ID.fullmatch(brute["id"]):
        raise _refus("REJ-OCCASION-CHAMP", "identifiant sobre requis")
    if type(brute["libelle"]) is not str or not brute["libelle"].strip() or len(brute["libelle"]) > 300:
        raise _refus("REJ-OCCASION-CHAMP", "libellé borné requis")
    if brute["origine"] not in ORIGINES:
        raise _refus("REJ-OCCASION-CHAMP", f"origine parmi {sorted(ORIGINES)}")
    alternatives = brute.get("alternatives", [])
    _liste_textes(alternatives, "alternatives")
    cout = _ref(brute.get("cout_ref"), faits, "cout_ref")
    capacite = _ref(brute.get("capacite_ref"), faits, "capacite_ref")
    signaux = brute.get("signaux_refs", [])
    if type(signaux) is not list or len(signaux) > 12:
        raise _refus("REJ-OCCASION-CHAMP", "signaux_refs : liste bornée d'adresses")
    signaux = [_ref(s, faits, "signaux_refs") for s in signaux]
    manques = [nom for nom, ref in (("cout", cout), ("capacite", capacite)) if ref is None]
    limites = [f"{nom} non cité(e) : l'occasion reste une hypothèse" for nom in manques]
    if not signaux:
        limites.append("aucun signal mesuré cité")
    return {
        "id": brute["id"],
        "libelle": brute["libelle"],
        "origine": brute["origine"],
        "conditions": _liste_textes(brute.get("conditions", []), "conditions"),
        "alternatives": list(alternatives),
        "statut": "HYPOTHESE" if manques else "DOCUMENTEE",
        "manques": manques,
        "cout": {"ref": cout, "texte": faits[cout]} if cout else None,
        "capacite": {"ref": capacite, "texte": faits[capacite]} if capacite else None,
        "signaux": [{"ref": s, "texte": faits[s]} for s in signaux],
        "mesurable": bool(signaux),
        "confiance": "NON_ESTIMEE",
        "limites_de_confiance": limites,
        "decision": "HUMAINE_REQUISE",
    }


def signaux_mesures(captures: Sequence[Mapping], *, connaissance: str) -> list[dict]:
    """Occasions tirées d'un signal mesuré : devis envoyés sans réponse (M8), depuis la dernière capture complète."""
    connues = cs.connues_a(captures, connaissance)
    en_conflit = {(c["lecture_id"], c["arguments_sha256"]) for c in cs.contradictions(connues)}
    candidates = [
        c
        for c in connues
        if c["lecture_id"] == LECTURE_SIGNAL
        and c["verdict"] == "ACCEPTEE"
        and c["complete"]
        and (c["lecture_id"], c["arguments_sha256"]) not in en_conflit
    ]
    if not candidates:
        return []
    capture = candidates[-1]
    devis = [d for page in capture["pages"] for d in cs.extraire(page, CHEMIN_SIGNAL)]
    liste = [x for groupe in devis for x in (groupe if isinstance(groupe, list) else [groupe])]
    if not liste:
        return []
    adresse = f"{capture['lecture_id']}#{capture['index']}:p0.{CHEMIN_SIGNAL}"
    return [
        {
            "id": "relancer_devis_sans_reponse",
            "libelle": "Relancer les devis envoyés restés sans réponse",
            "origine": "SIGNAL_MESURE",
            "nombre_de_devis": len(liste),
            "devis": [str(x)[:64] for x in liste[:20]],
            "signal": {"capture": capture["index"], "adresse": adresse, "recu_a": capture["recu_a"]},
            "statut": "HYPOTHESE",
            "manques": ["cout", "capacite"],
            "limites_de_confiance": ["coût et capacité de relance non cités ; aucun taux de conversion estimé"],
            "confiance": "NON_ESTIMEE",
            "decision": "HUMAINE_REQUISE",
        }
    ]


def evaluer(
    occasions: Sequence[object], faits: Mapping[str, str], captures: Sequence[Mapping] = (), *, connaissance: str
) -> dict:
    if not isinstance(occasions, Sequence) or isinstance(occasions, str) or len(occasions) > MAX_OCCASIONS:
        raise _refus("REJ-OCCASION-CHAMP", f"au plus {MAX_OCCASIONS} occasions")
    evaluees = [_occasion(o, faits) for o in occasions]
    if len({o["id"] for o in evaluees}) != len(evaluees):
        raise _refus("REJ-OCCASION-CHAMP", "identifiants distincts requis")
    resultat = {
        "type": "RADAR_OCCASIONS",
        "version": VERSION,
        "connaissance": connaissance,
        "occasions": evaluees,
        "signaux_mesures": signaux_mesures(captures, connaissance=connaissance),
        "limites": list(_LIMITES),
    }
    resultat["radar_id"] = hashlib.sha256(
        json.dumps(resultat, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    ).hexdigest()
    return resultat
