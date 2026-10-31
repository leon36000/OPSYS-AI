"""Raccord du conseil au runtime natif : séquence attendue et vérificateur de trace (traces SIMULÉES, fictives)."""

import copy

import pytest
from m9_strategic_intelligence import conseil
from m9_strategic_intelligence import raccord_core_conseil as rc

FICTIF = True


def _depot(role="strategie_ventes", reservation_id="res-1", session="s1", **surcharge):
    reservation = {
        "id": reservation_id,
        "profil": rc.agent_id(role),
        "statut": "conciliee",
        "tokens_reels": 900,
        "tokens_plafond": 1500,
    }
    return {
        "acteur": "admin",
        "outil": rc.OUTIL_DEPOT,
        "resultat": "ok",
        "session_id": session,
        "role": role,
        "issue": "ADMIS",
        "reservation": reservation | surcharge,
    }


def _entree(role="strategie_ventes", session="s1"):
    return {"acteur": "admin", "outil": rc.OUTIL_ENTREE, "resultat": "ok", "session_id": session, "role": role}


def _cycle():
    return [
        _entree(),
        {"acteur": "agent", "outil": rc.OUTIL_ENTREE, "resultat": "refus", "code": rc.CODE_REFUS_IDENTITE},
        _depot(),
    ]


def _regles(verdict):
    return {r["regle"]: r["statut"] for r in verdict["regles"]}


def test_un_cycle_entier_sans_ecart_est_complete_et_dit_ce_qu_il_ne_prouve_pas():
    verdict = rc.verifier_trace(_cycle())
    assert verdict["verdict"] == "COMPLETE" and set(_regles(verdict).values()) == {"CONFORME"}
    assert any("origine" in limite for limite in verdict["limites"])


def test_sans_cycle_la_qualification_est_incomplete_pas_conforme():
    verdict = rc.verifier_trace([_entree()])
    assert verdict["verdict"] == "INCOMPLETE" and _regles(verdict)["R5"] == "NON_OBSERVE"
    sans_depot = rc.verifier_trace([{"acteur": "agent", "outil": rc.OUTIL_ENTREE, "resultat": "refus"}])
    assert sans_depot["verdict"] == "INCOMPLETE"


def test_un_agent_qui_reussit_un_outil_admin_est_un_ecart_de_droits():
    trace = _cycle() + [{"acteur": "agent", "outil": rc.OUTIL_ENTREE, "resultat": "ok"}]
    verdict = rc.verifier_trace(trace)
    assert verdict["verdict"] == "ECART" and _regles(verdict)["R1"] == "ECART"


def test_reservation_etrangere_non_conciliee_ou_depassee_est_un_ecart():
    cas = {
        "profil": _depot(profil="m9-autre-role"),
        "statut": _depot(statut="reservee"),
        "reels": _depot(tokens_reels=2000),
        "entier": _depot(tokens_reels=True),
    }
    for nom, depot in cas.items():
        verdict = rc.verifier_trace([_entree(), depot])
        assert verdict["verdict"] == "ECART" and _regles(verdict)["R2"] == "ECART", nom
    sans_reservation = _depot()
    del sans_reservation["reservation"]
    assert _regles(rc.verifier_trace([_entree(), sans_reservation]))["R2"] == "ECART"


def test_une_reservation_ne_sert_qu_a_un_tour_et_deux_depots_au_plus_par_tour():
    partage = [_entree(), _depot(role="strategie_ventes"), _depot(role="liaison_finance", reservation_id="res-1")]
    verdict = rc.verifier_trace(partage)
    assert _regles(verdict)["R3"] == "ECART" and verdict["verdict"] == "ECART"
    rejeu = [_entree(), _depot(), _depot()]  # même tour, même réservation : un rejeu, pas un partage
    assert _regles(rc.verifier_trace(rejeu))["R3"] == "CONFORME"
    trois = [_entree(), _depot(reservation_id="a"), _depot(reservation_id="b"), _depot(reservation_id="c")]
    assert _regles(rc.verifier_trace(trois))["R4"] == "ECART"


def test_trace_mal_formee_est_refusee_jamais_jugee():
    for mauvaise in (None, [], "texte", [3], [{"acteur": "robot", "outil": "x", "resultat": "ok"}],
                     [{"acteur": "admin", "outil": "x", "resultat": "peut-etre"}]):  # fmt: skip
        with pytest.raises(ValueError, match="REJ-TRACE-FORME"):
            rc.verifier_trace(mauvaise)


def test_le_verificateur_ne_modifie_pas_la_trace_et_la_sequence_est_ordonnee():
    trace = _cycle()
    avant = copy.deepcopy(trace)
    rc.verifier_trace(trace)
    assert trace == avant
    assert [e["etape"] for e in rc.SEQUENCE] == list(range(1, len(rc.SEQUENCE) + 1))
    assert rc.agent_id("strategie_ventes") == "m9-strategie-ventes" and all(rc.agent_id(r) for r in conseil.PAR_ID)
    with pytest.raises(ValueError, match="REJ-TOUR-INCONNU"):
        rc.agent_id("inconnu")


def test_r5_exige_entree_puis_depot_admis_de_meme_session_et_meme_role():
    """Défaut trouvé en relecture : une entrée et un dépôt sans lien donnaient COMPLETE."""
    sans_lien = [_depot(session="s2"), _entree(role="liaison_finance", session="s1")]
    assert rc.verifier_trace(sans_lien)["verdict"] == "INCOMPLETE"
    autre_role = [_entree(role="liaison_finance"), _depot(role="strategie_ventes")]
    assert rc.verifier_trace(autre_role)["verdict"] == "INCOMPLETE"
    entree_apres = [_depot(), _entree()]
    assert rc.verifier_trace(entree_apres)["verdict"] == "INCOMPLETE"
    refuse = _depot()
    refuse["issue"] = "REFUSE"  # l'outil répond accepte même quand l'admission refuse la sortie
    assert rc.verifier_trace([_entree(), refuse])["verdict"] == "INCOMPLETE"
    sans_issue = _depot()
    del sans_issue["issue"]
    assert rc.verifier_trace([_entree(), sans_issue])["verdict"] == "ECART"


def test_r1_tout_succes_d_agent_sur_un_outil_m9_est_un_ecart():
    for outil in ("m9_ouvrir_conseil", "m9_cloturer_conseil", "m9_salle_de_guerre"):
        trace = _cycle() + [{"acteur": "agent", "outil": outil, "resultat": "ok"}]
        verdict = rc.verifier_trace(trace)
        assert verdict["verdict"] == "ECART" and _regles(verdict)["R1"] == "ECART", outil
    autre = _cycle() + [{"acteur": "agent", "outil": "outil_hors_m9", "resultat": "ok"}]
    assert _regles(rc.verifier_trace(autre))["R1"] == "CONFORME"


def test_r2_forme_complete_de_la_reservation_et_du_depot_jamais_une_exception_non_nommee():
    sans_id = _depot()
    del sans_id["reservation"]["id"]
    negatif = _depot(tokens_reels=-10)
    sans_session = _depot()
    del sans_session["session_id"]
    role_non_hachable = _depot()
    role_non_hachable["role"] = []
    plafond_nul = _depot(tokens_plafond=0)
    for nom, depot in {"id": sans_id, "negatif": negatif, "session": sans_session, "role": role_non_hachable,
                       "plafond": plafond_nul}.items():  # fmt: skip
        verdict = rc.verifier_trace([_entree(), depot])
        assert verdict["verdict"] == "ECART" and _regles(verdict)["R2"] == "ECART", nom


def test_une_trace_fidele_a_la_sequence_avec_l_acteur_runtime_est_acceptee():
    reconciliation = {"acteur": "runtime", "outil": rc.OUTIL_RECONCILIATION, "resultat": "ok"}
    trace = [_entree(), reconciliation, _depot()]
    assert rc.verifier_trace(trace)["verdict"] == "COMPLETE"
    assert {e["acteur"] for e in rc.SEQUENCE} <= rc.ACTEURS
