"""Mémoire M10 effective M9.20 : consigner une décision de la Direction IA dans M10, sans mémoire fantôme.

Module pur. M10 est le seul propriétaire de la mémoire ; M9 n'y écrit jamais : il PRÉPARE les arguments exacts de
``m10_journaliser_decision`` (proposés ensuite à la file d'approbation native par ``m9_proposer_action``) et VÉRIFIE
ensuite,
par la lecture ``m10_statut_decision``, que la mémoire dit bien ce que M9 croit y avoir mis.

* L'identifiant M10 de la décision est stable par session (``m9:<session_id>``) ; la VERSION est le ``rapport_id`` du
rapport
  clos, cité dans la raison avec le ``dossier_id`` et le verdict de gouvernance. Une correction est une nouvelle
  journalisation du même identifiant (``remplacee`` ou ``annulee``) qui cite le nouveau rapport et son motif : M10 reste
  append-only, rien n'est réécrit.
* ``validee`` n'est jamais proposé par défaut : la validation est humaine (l'approbation native de la demande) et doit
être
  déclarée explicitement.
* Verdicts de vérification : ``COHERENT`` (M10 porte le statut attendu après une action exécutée et confirmée),
  ``MEMOIRE_FANTOME`` (M9 croit la décision consignée, M10 n'en a aucune trace), ``DIVERGENT`` (M10 porte un autre
  statut),
  ``NON_ENREGISTREE`` (rien n'a été consigné et M10 le confirme), ``NON_ATTRIBUABLE`` (M10 porte la décision sans que M9
  ait
  une action exécutée), ``INCONNU`` (lecture M10 absente, refusée, partielle ou contradictoire).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence

from . import capture_strategique as cs

VERSION = "2026-10-28.1"
OUTIL_M10 = "m10_journaliser_decision"
LECTURE_STATUT = "m10.statut_decision"
STATUTS_M10 = ("proposee", "validee", "remplacee", "annulee", "indetermine")
STATUTS_PREPARABLES = ("proposee", "remplacee", "annulee", "indetermine", "validee")
MAX_RAISON = 1200
_SESSION = re.compile(r"[0-9a-f]{16,64}")
_HEX = re.compile(r"[0-9a-f]{12,64}")


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code} : {detail}")


def identifiant_decision(session_id: str) -> str:
    if type(session_id) is not str or not _SESSION.fullmatch(session_id):
        raise _refus("REJ-MEMOIRE-SESSION", "identifiant de session hexadécimal requis")
    return f"m9:{session_id}"


def preparer(
    session: Mapping,
    statut: str,
    horodatage: str,
    *,
    options_ecartees: str = "",
    motif: str | None = None,
    validation_humaine_declaree: bool = False,
    correction: bool = False,
) -> dict:
    """Arguments exacts de ``m10_journaliser_decision`` pour une session CLOSE (``sessions_conseil.etat``)."""
    if not isinstance(session, Mapping) or session.get("cloture") is None:
        raise _refus("REJ-MEMOIRE-SESSION", "session close requise : aucune décision n'est consignée avant sa clôture")
    if statut not in STATUTS_PREPARABLES:
        raise _refus("REJ-MEMOIRE-STATUT", f"statut parmi {list(STATUTS_PREPARABLES)}")
    if statut == "validee" and not validation_humaine_declaree:
        raise _refus(
            "REJ-MEMOIRE-VALIDATION", "validee exige la validation humaine déclarée (l'approbation est humaine)"
        )
    if cs.instant(horodatage) is None:
        raise _refus("REJ-CAPTURE-TEMPS", "instant avec fuseau explicite requis")
    cloture = session["cloture"]
    if cloture["issue"] == "ABSTENTION" and statut in ("proposee", "validee"):
        raise _refus(
            "REJ-MEMOIRE-STATUT",
            "une abstention du conseil ne se consigne que « indetermine », « remplacee » ou « annulee »",
        )
    if correction and statut in ("proposee", "validee"):
        raise _refus("REJ-MEMOIRE-STATUT", "une correction est « remplacee » ou « annulee »")
    if (correction or statut in ("remplacee", "annulee")) and (type(motif) is not str or not motif.strip()):
        raise _refus("REJ-MEMOIRE-MOTIF", "un motif borné est requis pour une correction")
    if motif is not None and (type(motif) is not str or len(motif) > 300):
        raise _refus("REJ-MEMOIRE-MOTIF", "motif de 300 caractères au plus")
    if type(options_ecartees) is not str or len(options_ecartees) > 400:
        raise _refus("REJ-MEMOIRE-OPTIONS", "options écartées : texte de 400 caractères au plus")
    gouvernance = cloture.get("gouvernance") or {}
    verdict_id = gouvernance.get("verdict_id")
    parties = [
        f"Direction IA (M9) — issue {cloture['issue']}",
        f"session {session['session_id']}",
        f"rapport {cloture['rapport_id']}",
        f"dossier {session['dossier_id']}",
    ]
    if verdict_id:
        parties.append(f"gouvernance {verdict_id}")
    if motif:
        parties.append(f"motif : {motif}")
    raison = " ; ".join(parties)
    if len(raison) > MAX_RAISON:
        raise _refus("REJ-MEMOIRE-RAISON", "raison trop longue")
    return {
        "decision": {
            "decision_id": identifiant_decision(session["session_id"]),
            "raison": raison,
            "statut": statut,
            "options_ecartees": options_ecartees,
        },
        "horodatage": horodatage,
    }


def statut_m10(captures: Sequence[Mapping], decision_id: str, *, connaissance: str) -> dict:
    """Statut de la décision selon la dernière capture complète de ``m10_statut_decision`` (ou pourquoi inconnu)."""
    connues = cs.connues_a(captures, connaissance)
    en_conflit = {(c["lecture_id"], c["arguments_sha256"]) for c in cs.contradictions(connues)}
    lues = [
        c for c in connues if c["lecture_id"] == LECTURE_STATUT and c["arguments"].get("decision_id") == decision_id
    ]
    if not lues:
        return {"lecture": "ABSENTE", "statut": None}
    derniere = lues[-1]
    if derniere["verdict"] != "ACCEPTEE":
        return {"lecture": "REFUSEE", "statut": None, "capture": derniere["index"]}
    if (derniere["lecture_id"], derniere["arguments_sha256"]) in en_conflit:
        return {"lecture": "CONTRADICTOIRE", "statut": None, "capture": derniere["index"]}
    if not derniere["complete"]:
        return {"lecture": "PARTIELLE", "statut": None, "capture": derniere["index"]}
    valeurs = [v for page in derniere["pages"] for v in cs.extraire(page, "resultat.statut")]
    if len(valeurs) != 1:
        return {"lecture": "ILLISIBLE", "statut": None, "capture": derniere["index"]}
    valeur = valeurs[0]
    if valeur is not None and valeur not in STATUTS_M10:
        return {"lecture": "ILLISIBLE", "statut": None, "capture": derniere["index"]}
    return {
        "lecture": "COMPLETE",
        "statut": valeur,
        "capture": derniere["index"],
        "recu_a": derniere["recu_a"],
        "hash": derniere["hash_maillon"],
    }


def verifier(
    captures: Sequence[Mapping],
    decision_id: str,
    *,
    connaissance: str,
    attendu: str | None,
    action_etat: str | None,
) -> dict:
    """Compare ce que M9 croit avoir consigné (``attendu``, état de l'action) à ce que M10 dit."""
    memoire = statut_m10(captures, decision_id, connaissance=connaissance)
    execute = action_etat == "EXECUTEE_CONFIRMEE"
    if memoire["lecture"] != "COMPLETE":
        verdict = "INCONNU"
    elif memoire["statut"] is None:
        verdict = "MEMOIRE_FANTOME" if execute else "NON_ENREGISTREE"
    elif not execute:
        verdict = "NON_ATTRIBUABLE"
    else:
        verdict = "COHERENT" if memoire["statut"] == attendu else "DIVERGENT"
    return {
        "type": "VERIFICATION_MEMOIRE_M10",
        "version": VERSION,
        "decision_id": decision_id,
        "attendu": attendu,
        "action_etat": action_etat,
        "memoire": memoire,
        "verdict": verdict,
        "limites": [
            "M10 est lu, jamais corrigé par M9 : un écart se traite par une nouvelle journalisation approuvée.",
            "Le statut M10 est calculé par relecture de sa chaîne ; sa lecture n'est connue que si capturée complète.",
        ],
    }
