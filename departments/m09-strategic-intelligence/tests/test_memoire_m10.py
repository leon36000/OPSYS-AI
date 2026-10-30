"""M9.20 — mémoire M10 : IDs et versions reliés, correction append-only, aucune mémoire fantôme (fictif)."""

import pytest
from m9_strategic_intelligence import capture_strategique as cs
from m9_strategic_intelligence import catalogue_producteurs as cat
from m9_strategic_intelligence import memoire_m10 as mm

FICTIF = True
CONNAISSANCE = "2026-10-28T13:00:00Z"
SESSION = "a" * 32
RAPPORT = "b" * 64
DOSSIER = "c" * 64
DECISION = f"m9:{SESSION}"


def session(issue="RECOMMANDATION", verdict=True, rapport=RAPPORT):
    return {
        "session_id": SESSION,
        "dossier_id": DOSSIER,
        "cloture": {
            "issue": issue,
            "rapport_id": rapport,
            "gouvernance": {"verdict_id": "d" * 64} if verdict else None,
        },
    }


def statut_capture(valeur, index=0, precedent=cs.HASH_INITIAL, recu="2026-10-27T12:00:00Z", reponse=None):
    page = reponse or {"ok": True, "resultat": {"statut": valeur}}
    return cs.construire(
        cat.obtenir("m10.statut_decision"), {"decision_id": DECISION}, [page], recu_a=recu, reference=None,
        index=index, hash_precedent=precedent,
    )  # fmt: skip


def test_preparation_exacte_avec_ids_versions_et_aucune_ecriture():
    args = mm.preparer(session(), "proposee", "2026-10-27T12:00:00Z", options_ecartees="ne rien faire")
    decision = args["decision"]
    assert decision["decision_id"] == DECISION and decision["statut"] == "proposee"
    assert RAPPORT in decision["raison"] and DOSSIER in decision["raison"] and SESSION in decision["raison"]
    assert "d" * 64 in decision["raison"] and decision["options_ecartees"] == "ne rien faire"
    assert set(args) == {"decision", "horodatage"} and set(decision) == {
        "decision_id",
        "raison",
        "statut",
        "options_ecartees",
    }


def test_correction_meme_identifiant_nouvelle_version_et_motif_obligatoire():
    premiere = mm.preparer(session(), "proposee", "2026-10-27T12:00:00Z")
    nouveau_rapport = "e" * 64
    correction = mm.preparer(
        session(rapport=nouveau_rapport),
        "remplacee",
        "2026-10-28T09:00:00Z",
        motif="nouvelles données M5",
        correction=True,
    )
    assert correction["decision"]["decision_id"] == premiere["decision"]["decision_id"]
    assert (
        nouveau_rapport in correction["decision"]["raison"]
        and "nouvelles données M5" in correction["decision"]["raison"]
    )
    with pytest.raises(ValueError, match="REJ-MEMOIRE-MOTIF"):
        mm.preparer(session(), "annulee", "2026-10-28T09:00:00Z", correction=True)
    with pytest.raises(ValueError, match="REJ-MEMOIRE-STATUT"):
        mm.preparer(session(), "proposee", "2026-10-28T09:00:00Z", motif="x", correction=True)


@pytest.mark.parametrize(
    "kwargs, code",
    [
        ({"statut": "validee"}, "REJ-MEMOIRE-VALIDATION"),
        ({"statut": "inventee"}, "REJ-MEMOIRE-STATUT"),
        ({"statut": "proposee", "horodatage": "2026-10-27T12:00:00"}, "REJ-CAPTURE-TEMPS"),
        ({"statut": "proposee", "options_ecartees": "x" * 401}, "REJ-MEMOIRE-OPTIONS"),
        ({"statut": "proposee", "motif": "x" * 301}, "REJ-MEMOIRE-MOTIF"),
    ],
)
def test_preparations_refusees(kwargs, code):
    kwargs = {"horodatage": "2026-10-27T12:00:00Z", **kwargs}
    with pytest.raises(ValueError, match=code):
        mm.preparer(session(), **kwargs)


def test_validee_seulement_avec_validation_humaine_declaree_et_abstention_restreinte():
    args = mm.preparer(session(), "validee", "2026-10-27T12:00:00Z", validation_humaine_declaree=True)
    assert args["decision"]["statut"] == "validee"
    with pytest.raises(ValueError, match="REJ-MEMOIRE-STATUT"):
        mm.preparer(session(issue="ABSTENTION", verdict=False), "proposee", "2026-10-27T12:00:00Z")
    assert mm.preparer(session(issue="ABSTENTION", verdict=False), "indetermine", "2026-10-27T12:00:00Z")
    sans_cloture = {**session(), "cloture": None}
    with pytest.raises(ValueError, match="REJ-MEMOIRE-SESSION"):
        mm.preparer(sans_cloture, "proposee", "2026-10-27T12:00:00Z")
    with pytest.raises(ValueError, match="REJ-MEMOIRE-SESSION"):
        mm.identifiant_decision("pas-hexa")


@pytest.mark.parametrize(
    "valeur, etat, attendu, verdict",
    [
        ("proposee", "EXECUTEE_CONFIRMEE", "proposee", "COHERENT"),
        ("remplacee", "EXECUTEE_CONFIRMEE", "proposee", "DIVERGENT"),
        (None, "EXECUTEE_CONFIRMEE", "proposee", "MEMOIRE_FANTOME"),
        (None, "EN_ATTENTE_APPROBATION", "proposee", "NON_ENREGISTREE"),
        (None, None, "proposee", "NON_ENREGISTREE"),
        ("proposee", "EN_ATTENTE_APPROBATION", "proposee", "NON_ATTRIBUABLE"),
        ("proposee", None, "proposee", "NON_ATTRIBUABLE"),
    ],
)
def test_verdicts_de_verification(valeur, etat, attendu, verdict):
    res = mm.verifier([statut_capture(valeur)], DECISION, connaissance=CONNAISSANCE, attendu=attendu, action_etat=etat)
    assert res["verdict"] == verdict and res["memoire"]["lecture"] == "COMPLETE"


def test_lecture_absente_refusee_ou_illisible_est_inconnue_jamais_fantome():
    for captures in ([], [statut_capture(None, reponse={"ok": False, "erreur": "refus_metier", "details": "x"})]):
        res = mm.verifier(
            captures, DECISION, connaissance=CONNAISSANCE, attendu="proposee", action_etat="EXECUTEE_CONFIRMEE"
        )
        assert res["verdict"] == "INCONNU" and res["memoire"]["lecture"] in ("ABSENTE", "REFUSEE")
    inconnu = statut_capture("statut_invente")
    res = mm.verifier(
        [inconnu], DECISION, connaissance=CONNAISSANCE, attendu="proposee", action_etat="EXECUTEE_CONFIRMEE"
    )
    assert res["verdict"] == "INCONNU" and res["memoire"]["lecture"] == "ILLISIBLE"


def test_derniere_lecture_connue_a_l_instant_gagne_et_correction_visible_apres_coup():
    premiere = statut_capture("proposee", recu="2026-10-27T12:00:00Z")
    seconde = statut_capture("remplacee", index=1, precedent=premiere["hash_maillon"], recu="2026-10-28T10:00:00Z")
    chaine = [premiere, seconde]
    tard = mm.verifier(
        chaine, DECISION, connaissance=CONNAISSANCE, attendu="remplacee", action_etat="EXECUTEE_CONFIRMEE"
    )
    assert tard["verdict"] == "COHERENT"
    tot = mm.verifier(
        chaine, DECISION, connaissance="2026-10-27T18:00:00Z", attendu="proposee", action_etat="EXECUTEE_CONFIRMEE"
    )
    assert tot["verdict"] == "COHERENT" and tot["memoire"]["capture"] == 0
    # une décision d'une autre session n'est jamais confondue
    autre = mm.verifier(chaine, "m9:" + "f" * 32, connaissance=CONNAISSANCE, attendu="proposee", action_etat=None)
    assert autre["memoire"]["lecture"] == "ABSENTE"
