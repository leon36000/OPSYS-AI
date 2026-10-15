"""Inbox durable de réputation pour les avis importés manuellement.

Les avis et transitions sont append-only dans les registres M7 existants. Aucun
connecteur de plateforme n'est appelé ici : la source explicite est une référence
que l'opérateur a lue et saisie. Les avis conflictuels et les plaintes restent privés.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import date
from typing import Any
from urllib.parse import urlsplit

from opsys import stockage

from ..brand import profil_client
from . import classifier, response_builder

_DEPARTEMENT = "m07-marketing"
_AVIS = (_DEPARTEMENT, "reputation_avis")
_DECISIONS = (_DEPARTEMENT, "reputation_decisions")
_EXPORTS = (_DEPARTEMENT, "reputation_exports")
_PLATEFORMES = frozenset({"google_business_profile", "facebook", "autre"})
_ROLES_LECTURE = frozenset({"nathan_owner", "admin", "employee"})
_CATEGORIES_PRIVEES = frozenset({"litige", "urgence"})


def _service():
    # Import local pour ne pas créer de cycle avec le manifeste d'outils.
    from ..usine import service

    return service


def _lire(registre: tuple[str, str]) -> list[dict[str, Any]]:
    return list(stockage.maillons(*registre))


def _empreinte(valeur: dict[str, Any]) -> str:
    canonique = json.dumps(valeur, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonique.encode("utf-8")).hexdigest()


def _refus(code: str, detail: str) -> dict[str, Any]:
    return {"accepte": False, "verdict": {"code": code, "detail": detail}}


def _identite_appelante() -> tuple[str, str] | None:
    identite = _service()._appelant_confirme()
    if identite is None:
        return None
    return identite.personne, identite.role


def _avis_par_id(avis_id: str) -> dict[str, Any] | None:
    return next((avis for avis in _lire(_AVIS) if avis["avis_id"] == avis_id), None)


def _decision_par_id(avis_id: str) -> dict[str, Any] | None:
    return next((d for d in _lire(_DECISIONS) if d["avis_id"] == avis_id), None)


def _export_par_id(avis_id: str) -> dict[str, Any] | None:
    return next((e for e in _lire(_EXPORTS) if e["avis_id"] == avis_id), None)


def avis_pour_metriques() -> list[dict[str, Any]]:
    """Projection minimale de la source durable, sans URL ni provenance personnelle."""
    return [
        {"id": a["avis_id"], "date": a["date_avis"], "note": a["note"], "texte": a["texte"]}
        for a in _lire(_AVIS)
    ]


def _statut(avis: dict[str, Any]) -> str:
    export = _export_par_id(avis["avis_id"])
    if export:
        return "EXPORTE_MANUEL"
    decision = _decision_par_id(avis["avis_id"])
    if decision:
        return decision["decision"]
    return "PROPOSE"


def importer_avis_manuel(
    plateforme: str,
    avis_source_id: str,
    date_avis: str,
    note: int,
    texte: str,
    source_url: str,
) -> dict[str, Any]:
    """Importe une transcription explicite; l'auteur vient du jeton appareil vérifié."""
    identite = _identite_appelante()
    if identite is None or identite[1] not in _ROLES_LECTURE:
        return _refus("REJ-IDENTITE-REQUIS", "un appareil actif admin ou employee doit authentifier cet import manuel")
    personne, _role = identite
    if plateforme not in _PLATEFORMES:
        return _refus("REJ-AVIS-INVALIDE", f"plateforme attendue : {', '.join(sorted(_PLATEFORMES))}")
    if not isinstance(avis_source_id, str) or not avis_source_id.strip() or len(avis_source_id) > 200:
        return _refus("REJ-AVIS-INVALIDE", "avis_source_id obligatoire (200 caractères au plus)")
    try:
        date.fromisoformat(date_avis)
    except (TypeError, ValueError):
        return _refus("REJ-AVIS-INVALIDE", "date_avis doit être une date ISO 8601 (AAAA-MM-JJ)")
    if type(note) is not int or not 1 <= note <= 5:
        return _refus("REJ-AVIS-INVALIDE", "note doit être un entier de 1 à 5")
    if not isinstance(texte, str) or not texte.strip() or len(texte) > 5000:
        return _refus("REJ-AVIS-INVALIDE", "texte obligatoire (5 000 caractères au plus)")
    if not isinstance(source_url, str) or not source_url.strip() or len(source_url) > 2000:
        return _refus(
            "REJ-AVIS-INVALIDE",
            "source_url est la référence explicite de l'avis consulté (2 000 caractères au plus)",
        )
    try:
        reference = urlsplit(source_url.strip())
    except ValueError:
        reference = None
    if (reference is None or reference.scheme != "https" or not reference.hostname
            or reference.username is not None or reference.password is not None):
        return _refus("REJ-AVIS-INVALIDE", "source_url doit être une référence HTTPS sans identifiants intégrés")

    source = {
        "plateforme": plateforme,
        "avis_source_id": avis_source_id.strip(),
        "date_avis": date_avis,
        "note": note,
        "texte": texte.strip(),
        "source_url": source_url.strip(),
        "mode_import": "manuel",
    }
    empreinte_source = _empreinte(source)
    avis_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"m7-avis:{plateforme}:{avis_source_id.strip()}"))
    avis_lus = _lire(_AVIS)
    deja = next((avis for avis in avis_lus if avis["avis_id"] == avis_id), None)
    if deja is not None:
        if deja["empreinte_source"] != empreinte_source:
            return _refus(
                "CONFLIT-AVIS-SOURCE",
                "cet identifiant de plateforme existe avec un contenu ou une source différente",
            )
        return {"accepte": True, "resultat": {
            "avis_id": avis_id, "statut": _statut(deja), "deja_importe": True,
            "categorie": deja["categorie"], "visibilite": deja["visibilite"],
        }}

    profil, motif = profil_client.charger_profil_client()
    if profil is None:
        return _refus("REJ-PROFIL-MARQUE", str(motif))
    categorie = classifier.classifier_avis({"id": avis_id, "note": note, "texte": source["texte"]})
    brouillon = response_builder.construire_reponse(
        {"id": avis_id}, categorie, profil, niveau_validation=1,
    )
    maillon = {
        "avis_id": avis_id,
        **source,
        "importe_par": personne,
        "importe_par_role": identite[1],
        "empreinte_source": empreinte_source,
        "categorie": categorie,
        "visibilite": "privee" if categorie in _CATEGORIES_PRIVEES else "normale",
        "revision": 1,
        "reponse_id": brouillon["id"],
        "reponse_texte": brouillon["texte"],
        "reponse_empreinte": _empreinte({"texte": brouillon["texte"], "revision": 1}),
        "approval_status": "PROPOSE",
    }
    # La déduplication et l'append portent sur le même préfixe observé.
    stockage.maillons(*_AVIS).append(maillon, rang_attendu=len(avis_lus))
    return {"accepte": True, "resultat": {
        "avis_id": avis_id, "statut": "PROPOSE", "deja_importe": False,
        "categorie": categorie, "visibilite": maillon["visibilite"],
        "reponse_texte": None if maillon["visibilite"] == "privee" and identite[1] != "admin"
        else maillon["reponse_texte"],
    }}


def lister_inbox_reputation(
    categorie: str | None = None, statut: str | None = None, limite: int = 20,
) -> dict[str, Any]:
    """Liste les avis durables; l'employé voit les métadonnées des plaintes, jamais leur contenu."""
    identite = _identite_appelante()
    if identite is None or identite[1] not in _ROLES_LECTURE:
        return _refus("REJ-IDENTITE-REQUIS", "un appareil actif admin ou employee est requis pour consulter l'inbox")
    if type(limite) is not int or not 1 <= limite <= 100:
        return _refus("REJ-FILTRE-INBOX", "limite doit être comprise entre 1 et 100")
    items = sorted(_lire(_AVIS), key=lambda a: (a["date_avis"], a["avis_id"]), reverse=True)
    resultats = []
    for avis in items:
        etat = _statut(avis)
        if categorie and avis["categorie"] != categorie:
            continue
        if statut and etat != statut:
            continue
        prive = avis["visibilite"] == "privee" and identite[1] not in {"nathan_owner", "admin"}
        if prive:
            continue
        resultats.append({
            "avis_id": avis["avis_id"], "plateforme": avis["plateforme"], "date_avis": avis["date_avis"],
            "note": avis["note"], "categorie": avis["categorie"], "statut": etat,
            "visibilite": avis["visibilite"], "source_url": avis["source_url"],
            "texte": avis["texte"], "reponse_texte": avis["reponse_texte"],
        })
        if len(resultats) >= limite:
            break
    return {"accepte": True, "resultat": {"avis": resultats, "limite": limite}}


def decider_reponse_avis(avis_id: str, decision: str, horodatage: str, motif: str = "") -> dict[str, Any]:
    """Le service public réutilise la preuve propriétaire vivante de l'usine de contenu M7."""
    service = _service()
    acteur, refus = service._proprietaire_qui_decide("m7_decider_reponse_avis")
    if acteur is None:
        return {"accepte": False, "verdict": refus or {"code": "REJ-HUMAIN-REQUIS", "detail": "propriétaire requis"}}
    avis = _avis_par_id(avis_id)
    if avis is None:
        return _refus("REJ-AVIS-INCONNU", "avis absent de l'inbox durable")
    if not service.retrait.horodatage_valide(horodatage):
        return _refus("REJ-HORODATAGE-INVALIDE", "horodatage ISO 8601 avec fuseau requis")
    if _decision_par_id(avis_id):
        return _refus("REJ-AVIS-DEJA-TRANCHE", "une décision humaine existe déjà pour cette révision")
    if decision not in {"approuver", "rejeter"}:
        return _refus("REJ-DECISION-INVALIDE", "decision attendue : approuver ou rejeter")
    if decision == "rejeter" and not motif.strip():
        return _refus("REJ-MOTIF-REQUIS", "le rejet doit expliquer la correction attendue")
    if decision == "approuver" and avis["visibilite"] == "privee":
        # La plainte reste un dossier de traitement privé, jamais un candidat à une réponse publique.
        statut = "APPROUVE_PRIVE"
    else:
        statut = "APPROUVE" if decision == "approuver" else "REJETE"
    decision_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"m7-avis-decision:{avis_id}"))
    maillon = {
        "decision_id": decision_id, "avis_id": avis_id, "revision": avis["revision"],
        "decision": statut, "empreinte_source": avis["empreinte_source"],
        "empreinte_reponse": avis["reponse_empreinte"], "par": acteur["par"], "role": acteur["role"],
        "source": acteur["source"], "motif": motif.strip(),
        "horodatage": service._horodatage_faisant_foi(horodatage),
    }
    stockage.maillons(*_DECISIONS).append(maillon)
    return {"accepte": True, "resultat": {"avis_id": avis_id, "statut": statut, "par": acteur["par"]}}


def exporter_reponse_avis_manuel(avis_id: str) -> dict[str, Any]:
    """Retourne un paquet stable pour copie manuelle; ne contacte ni plateforme ni client."""
    service = _service()
    acteur, refus = service._proprietaire_qui_decide("m7_exporter_reponse_avis_manuel")
    if acteur is None:
        return {"accepte": False, "verdict": refus or {"code": "REJ-HUMAIN-REQUIS", "detail": "propriétaire requis"}}
    exporte_par = acteur["par"]
    avis = _avis_par_id(avis_id)
    if avis is None:
        return _refus("REJ-AVIS-INCONNU", "avis absent de l'inbox durable")
    if avis["visibilite"] == "privee":
        return _refus(
            "REJ-AVIS-PRIVE",
            "les plaintes/urgences restent en traitement privé et ne sont jamais exportées publiquement",
        )
    decision = _decision_par_id(avis_id)
    if decision is None or decision["decision"] != "APPROUVE":
        return _refus("REJ-AVIS-NON-APPROUVE", "une approbation humaine du propriétaire est requise")
    if (decision["empreinte_source"] != avis["empreinte_source"]
            or decision["empreinte_reponse"] != avis["reponse_empreinte"]
            or decision["revision"] != avis["revision"]):
        return _refus("REJ-AVIS-MODIFIE", "la source ou la réponse ne correspond plus à la révision approuvée")
    existant = _export_par_id(avis_id)
    if existant is None:
        existant = {
            "export_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"m7-avis-export:{avis_id}")),
            "avis_id": avis_id, "revision": avis["revision"], "empreinte_source": avis["empreinte_source"],
            "empreinte_reponse": avis["reponse_empreinte"], "exporte_par": exporte_par,
            "mode": "copie_manuelle", "reponse_texte": avis["reponse_texte"],
        }
        stockage.maillons(*_EXPORTS).append(existant)
        deja = False
    else:
        deja = True
    return {"accepte": True, "resultat": {
        **existant, "deja_exporte": deja,
        "instruction": "copier manuellement dans la source après vérification; aucune publication n'a été faite",
    }}
