"""Outils d'un département fictif pour tester le socle OPSYS sans dépendre du métier réel."""

from __future__ import annotations

from decimal import Decimal

from opsys import contexte, stockage
from opsys.outils import Autonomie, Outil

JOURNAL: list[dict] = []


def additionner(a: float, b: float) -> dict:
    return {"somme": Decimal(str(a)) + Decimal(str(b))}


def refuser_si_negatif(valeur: int) -> dict:
    if valeur < 0:
        raise ValueError("valeur négative refusée")
    return {"valeur": valeur}


def envoyer_message(destinataire: str, texte: str) -> dict:
    JOURNAL.append({"a": destinataire, "texte": texte})
    return {"envoye": True, "a": destinataire}


def payer(montant: float) -> dict:
    JOURNAL.append({"paiement": montant})
    return {"paye": montant}


def gros_rapport(lignes: int) -> dict:
    return {"lignes": [f"ligne {i} " + "x" * 50 for i in range(lignes)]}


COMPTEUR_PANNE: dict[str, int] = {}


def echouer_puis_reussir(cle: str) -> dict:
    """Panne interne (RuntimeError, jamais un refus métier) au 1er appel pour `cle`, succès ensuite.

    Sert `tests/test_idempotence.py` : une panne interne ne doit jamais être enregistrée par
    l'idempotence (T1.4-b), pour qu'un renvoi réel réexécute — pas qu'il rejoue un échec figé.
    """
    COMPTEUR_PANNE[cle] = COMPTEUR_PANNE.get(cle, 0) + 1
    if COMPTEUR_PANNE[cle] == 1:
        raise RuntimeError("panne interne simulée")
    return {"tentative": COMPTEUR_PANNE[cle]}


def pointer(appareil: str) -> dict:
    """Écriture T1 simple (mode `supervise` : exécute directement, sans approbation).

    Sert `tests/test_idempotence.py` : un side-effect (JOURNAL) simple à compter pour vérifier
    qu'un renvoi ne ré-exécute jamais.
    """
    JOURNAL.append({"pointage": appareil})
    return {"pointe": True, "appareil": appareil}


HORODATAGES_VUS: list[contexte.HorodatageAppareil | None] = []


def voir_horodatage() -> dict:
    """Capture `contexte.horodatage_reception()` pendant l'exécution, pour `test_idempotence.py`."""
    HORODATAGES_VUS.append(contexte.horodatage_reception())
    return {"vu": True}


IDENTITES_VUES: list[contexte.IdentiteAppelante | None] = []


def voir_identite() -> dict:
    """Capture `contexte.identite_appelante()` pendant l'exécution, pour `test_contexte.py`
    (T1.4-c2 : identité `opsys/personne`/`opsys/role` transmise en `_meta` MCP par OPSYS-CORE)."""
    IDENTITES_VUES.append(contexte.identite_appelante())
    return {"vu": True}


_NB = {"type": "number"}
OUTILS = (
    Outil("m9_additionner", "Additionne deux nombres.",
          {"type": "object", "properties": {"a": _NB, "b": _NB}, "required": ["a", "b"],
           "additionalProperties": False}, additionner),
    Outil("m9_refuser_si_negatif", "Refuse une valeur négative.",
          {"type": "object", "properties": {"valeur": {"type": "integer"}}, "required": ["valeur"]},
          refuser_si_negatif),
    Outil("m9_envoyer_message", "Envoie un message à un client.",
          {"type": "object", "properties": {"destinataire": {"type": "string"}, "texte": {"type": "string"}},
           "required": ["destinataire", "texte"]}, envoyer_message, Autonomie.T2),
    Outil("m9_payer", "Paie un fournisseur.",
          {"type": "object", "properties": {"montant": _NB}, "required": ["montant"]}, payer, Autonomie.T3),
    Outil("m9_gros_rapport", "Produit un long rapport.",
          {"type": "object", "properties": {"lignes": {"type": "integer"}}, "required": ["lignes"]},
          gros_rapport),
    Outil("m9_echouer_puis_reussir", "Échoue par panne interne au premier appel pour `cle`.",
          {"type": "object", "properties": {"cle": {"type": "string"}}, "required": ["cle"],
           "additionalProperties": False}, echouer_puis_reussir),
    Outil("m9_pointer", "Pointe une entrée terrain (écriture T1 directe en mode supervisé).",
          {"type": "object", "properties": {"appareil": {"type": "string"}}, "required": ["appareil"],
           "additionalProperties": False}, pointer, Autonomie.T1),
    Outil("m9_voir_horodatage", "Capture les horloges de réception exposées par le contexte.",
          {"type": "object", "properties": {}, "additionalProperties": False}, voir_horodatage,
          Autonomie.T1),
    Outil("m9_voir_identite", "Capture l'identité de jeton d'appareil exposée par le contexte.",
          {"type": "object", "properties": {}, "additionalProperties": False}, voir_identite,
          Autonomie.T0),
)


def _recevoir_demo_complete(charge: dict) -> dict:
    """Consommateur de démo pour `opsys.demo_complete` (bus d'événements, ADR-0009 §3)."""
    stockage.maillons("m09-demo", "evenements_recus").append({"message": charge["message"]})
    return {"recu": True, "message": charge["message"]}


def consommateurs() -> dict:
    """Utilisé par les tests du bus d'événements (`tests/test_evenements.py`) ; `m09-demo` ne
    déclare rien dans `evenements.consomme` par défaut, donc cette fonction n'est jamais appelée
    tant qu'un test ne fournit pas explicitement cette déclaration (`opsys.departements.Departement`
    en mémoire, ou un manifeste temporaire — voir `docs/architecture/DEPARTEMENTS.md`)."""
    return {"opsys.demo_complete": _recevoir_demo_complete}


# Attentes déclarées par ce département de démonstration (ADR-0009 §5, PLAN T1.3-a §6) : même
# mécanisme de découverte que `consommateurs()`. Vide par défaut ; un test peuple cette liste pour
# exercer `approbations.file_proprietaire` (`tests/test_approbations_identite.py`), puis la vide.
ATTENTES_DEMO: list[dict] = []


def attentes() -> list[dict]:
    return list(ATTENTES_DEMO)
