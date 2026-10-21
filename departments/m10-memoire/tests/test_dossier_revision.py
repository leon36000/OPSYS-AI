"""Comparaison métier M10 : deux faits exacts, références et refus entiers (fictif)."""
from __future__ import annotations

import datetime as dt
import json
from copy import deepcopy
from decimal import Decimal

import pytest
from m10_memoire import catalogue_references, contexte, decisions, registre, revision

FICTIF = True
DATE = "2026-09-15T14:00:00-04:00"
DATE_2 = "2026-09-16T09:00:00-04:00"


def _lire(cible, ident):
    from m10_memoire.dossier_revision import lire_revision

    return lire_revision(cible, ident)


def _sources(cible, niveau=None, valeur=None, type_a="decision_enregistree"):
    if type_a == "decision_enregistree":
        a, erreur = decisions.enregistrer_decision({
            "decision_id": "DEC-POSE-FICTIVE", "raison": "Deux joints repris après inspection (fictif).",
            "statut": "proposee", "options_ecartees": "Conserver les joints initiaux (fictif).",
        }, cible, DATE, niveau)
        assert erreur is None
    else:
        ident = cible.ajouter({"type_entree": type_a, "horodatage": DATE,
                             "corps": "source développement fictive à retenir"})
        a = next(m for m in cible.lire() if m["ligne_id"] == ident)
    entree = {"type_entree": "evenement_memorise", "horodatage": DATE_2,
              "evenement": "Inspection de gouttières (fictif)",
              "preuves": {"photos": ["photo-fictive-1"], "mesure": 2, "confirme": True, "note": None}}
    if valeur is not None:
        entree["preuves"] = valeur
    ident_b = cible.ajouter(entree)
    b = next(m for m in cible.lire() if m["ligne_id"] == ident_b)
    sig, erreur = revision.signaler_revision(cible, a["ligne_id"], b["ligne_id"], DATE_2)
    assert erreur is None
    return a, b, sig


def test_deux_faits_exacts_projection_catalogue_dates_refs_sans_entetes_prives():
    cible = registre.Registre()
    a, b, sig = _sources(cible)
    arb, erreur = revision.arbitrer_revision(cible, sig["ligne_id"], "distincts_confirmes", DATE_2)
    assert erreur is None
    prive, erreur = decisions.enregistrer_decision({
        "decision_id": "DEC-PRIVEE-FICTIVE", "raison": "Texte privé fictif", "statut": "proposee",
        "options_ecartees": "Texte privé fictif",
    }, cible, DATE_2, "CLIENT_PRIVATE")
    assert erreur is None
    avant = deepcopy(cible.lire())
    dossier, refus = _lire(cible, sig["ligne_id"])
    assert refus is None and set(dossier) == {"revision", "faits"}
    catalogue, erreur = catalogue_references.lister_references(cible)
    assert erreur is None
    assert dossier["revision"] == catalogue["revisions"][0]
    assert dossier["revision"]["reference_statut"]["ligne_id"] == arb["ligne_id"]
    assert dossier["faits"] == [
        {"reference": {"registre": "affaires", "ligne_id": a["ligne_id"], "hash_tete": a["ligne_id"]},
         "type_entree": "decision_enregistree", "horodatage": DATE,
         "champs": {"decision_id": "DEC-POSE-FICTIVE", "raison": "Deux joints repris après inspection (fictif).",
                    "statut": "proposee", "options_ecartees": "Conserver les joints initiaux (fictif)."}},
        {"reference": {"registre": "affaires", "ligne_id": b["ligne_id"], "hash_tete": b["ligne_id"]},
         "type_entree": "evenement_memorise", "horodatage": DATE_2,
         "champs": {"evenement": "Inspection de gouttières (fictif)",
                    "preuves": {"photos": ["photo-fictive-1"], "mesure": 2, "confirme": True, "note": None}}},
    ]
    for fait in dossier["faits"]:
        assert contexte.verifier_reference(fait["reference"], cible) == (True, None)
    assert prive["ligne_id"] not in json.dumps(dossier, ensure_ascii=False)
    assert cible.lire() == avant


@pytest.mark.parametrize("piece", ["a", "b", "signalement", "arbitrage"])
@pytest.mark.parametrize("niveau", [
    "CLIENT_PRIVATE", "FINANCIAL", "SENSITIVE", "SECRET_REF", "LEGAL_LOCKED", "INCONNU",
])
def test_une_piece_retenue_refuse_tout_dossier_sans_fuite(piece, niveau):
    cible = registre.Registre()
    a, b, sig = _sources(cible)
    # Reconstruit une chaîne valide avec le marquage placé sur la pièce choisie, avant son hash.
    entree_a = {k: v for k, v in a.items() if k not in {"ligne_id", "precedent_ligne_id"}}
    entree_b = {k: v for k, v in b.items() if k not in {"ligne_id", "precedent_ligne_id"}}
    if piece == "a":
        entree_a["confidentialite"] = niveau
    if piece == "b":
        entree_b["confidentialite"] = niveau
    cible = registre.Registre()
    ida, idb = cible.ajouter(entree_a), cible.ajouter(entree_b)
    sig = {"type_entree": "revision_signalee", "horodatage": DATE_2, "ligne_id_a": ida, "ligne_id_b": idb,
           "revision_ligne_id": None, "statut": "en_attente"}
    if piece == "signalement":
        sig["confidentialite"] = niveau
    ident = cible.ajouter(sig)
    if piece == "arbitrage":
        cible.ajouter({"type_entree": "revision_signalee", "horodatage": DATE_2, "ligne_id_a": None,
                      "ligne_id_b": None, "revision_ligne_id": ident, "statut": "distincts_confirmes",
                      "confidentialite": niveau})
    avant = cible.lire()
    dossier, refus = _lire(cible, ident)
    assert dossier is None and refus["code"] == "REJ-DOSSIER-REVISION-RETENU"
    assert "joints" not in json.dumps(refus) and all(m["ligne_id"] not in json.dumps(refus) for m in avant)
    assert cible.lire() == avant


@pytest.mark.parametrize("ident", ["inconnu", "", None, 3])
def test_revision_absente_est_un_refus_nominal(ident):
    dossier, refus = _lire(registre.Registre(), ident)
    assert dossier is None and refus["code"] == "REJ-DOSSIER-REVISION-INCONNUE"


def test_un_arbitrage_ou_trace_ne_devient_pas_signalement():
    cible = registre.Registre()
    _, _, sig = _sources(cible)
    arb, _ = revision.arbitrer_revision(cible, sig["ligne_id"], "distincts_confirmes", DATE_2)
    assert _lire(cible, arb["ligne_id"])[1]["code"] == "REJ-DOSSIER-REVISION-INCONNUE"


@pytest.mark.parametrize("type_a", [
    "memoire_developpement", "revision_signalee", "session_affaire_liee", "signal_traite",
])
def test_source_non_factuelle_ou_developpement_ne_sort_pas(type_a):
    cible = registre.Registre()
    if type_a == "revision_signalee":
        _, _, premiere = _sources(cible)
        autre = cible.ajouter({"type_entree": "evenement_memorise", "horodatage": DATE, "evenement": "Autre fictif"})
        sig, _ = revision.signaler_revision(cible, premiere["ligne_id"], autre, DATE_2)
    else:
        _, _, sig = _sources(cible, type_a=type_a)
    dossier, refus = _lire(cible, sig["ligne_id"])
    assert dossier is None and refus["code"] == "REJ-DOSSIER-REVISION-TYPE-FAIT-INTERDIT"
    assert "développement" not in json.dumps(refus)


@pytest.mark.parametrize("valeur", [Decimal("2.0"), {1, 2}, (1, 2), b"fictif", dt.date(2026, 9, 15),
                                    float("nan"), float("inf"), {1: "clé non JSON"}])
def test_types_non_json_refuses_sans_coercition(valeur):
    cible = registre.Registre()
    _, _, sig = _sources(cible, valeur=valeur)
    dossier, refus = _lire(cible, sig["ligne_id"])
    assert dossier is None and refus["code"] == "REJ-DOSSIER-REVISION-JSON-INVALIDE"


def test_profondeur_bornee_et_taille_refusent_dossier_entier():
    for valeur, code in [("texte fictif " * 1000, "REJ-DOSSIER-REVISION-BUDGET-DEPASSE"),
                         ([[[[[[[[[["trop profond"]]]]]]]]]], "REJ-DOSSIER-REVISION-JSON-INVALIDE")]:
        cible = registre.Registre()
        _, _, sig = _sources(cible, valeur=valeur)
        avant = cible.lire()
        dossier, refus = _lire(cible, sig["ligne_id"])
        assert dossier is None and refus["code"] == code
        assert cible.lire() == avant


def test_un_seul_snapshot_et_chaine_corrompue_refusee():
    cible = registre.Registre()
    _, _, sig = _sources(cible)

    class Source:
        lectures = 0

        def lire(self):
            self.lectures += 1
            assert self.lectures == 1
            return cible.lire()

    source = Source()
    assert _lire(source, sig["ligne_id"])[1] is None
    assert source.lectures == 1
    lignes = cible.lire()
    lignes[0]["raison"] = "altération fictive"
    dossier, refus = _lire(registre.Registre(maillons=lignes), sig["ligne_id"])
    assert dossier is None and refus["code"] == "REJ-DOSSIER-REVISION-REGISTRE-INVALIDE"
