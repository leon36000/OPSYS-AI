"""Retrait du consentement, état d'un contenu, décision humaine (PLAN T4.17) : les trois modules purs qui décident.

Aucune base : les registres sont des listes de maillons, comme `stockage.maillons` les rend.
"""

from __future__ import annotations

import pytest
from m7_marketing.usine import decision, registre, retrait, verdicts

FICTIF = True
HORODATAGE = "2026-09-29T10:00:00-04:00"


def _proposition(contenu_id="c-1", wct_id="wct-1", lead_id="lead-1", plateforme="facebook", revision=1, **plus):
    return {
        "contenu_id": contenu_id, "wct_id": wct_id, "lead_id": lead_id, "plateforme": plateforme,
        "revision": revision, "texte": f"texte {contenu_id}", "empreinte_texte": f"empreinte-{contenu_id}", **plus,
    }


# -- retrait ---------------------------------------------------------------------------------------------------------
def test_un_retrait_valide_ne_porte_aucun_texte_libre():
    maillon, verdict = retrait.construire_retrait("wct-1", "lead-1", "telephone", "nathan", "appareil", HORODATAGE)
    assert verdict is None
    assert set(maillon) == {"retrait_id", "wct_id", "lead_id", "canal", "enregistre_par", "source", "horodatage"}
    assert (maillon["wct_id"], maillon["lead_id"], maillon["canal"]) == ("wct-1", "lead-1", "telephone")


def test_le_retrait_est_deterministe_par_chantier():
    a, _ = retrait.construire_retrait("wct-1", None, "sms", "agent", "agent", HORODATAGE)
    b, _ = retrait.construire_retrait("wct-1", "lead-9", "courriel", "nathan", "appareil", "2026-10-01T09:00:00-04:00")
    c, _ = retrait.construire_retrait("wct-2", None, "sms", "agent", "agent", HORODATAGE)
    assert a["retrait_id"] == b["retrait_id"] != c["retrait_id"]


@pytest.mark.parametrize(("wct_id", "canal", "horodatage"), [
    ("", "telephone", HORODATAGE),
    (None, "telephone", HORODATAGE),
    ("wct-1", "pigeon", HORODATAGE),
    ("wct-1", "telephone", "hier"),
    ("wct-1", "telephone", "2026-09-29T10:00:00"),  # sans fuseau
])
def test_un_retrait_mal_forme_est_refuse_avec_un_verdict(wct_id, canal, horodatage):
    maillon, verdict = retrait.construire_retrait(wct_id, None, canal, "agent", "agent", horodatage)
    assert maillon is None
    assert verdict["code"] in {verdicts.REJ_RETRAIT_INVALIDE, verdicts.REJ_HORODATAGE_INVALIDE}
    assert verdict["detail"]


def test_le_retrait_vaut_pour_le_chantier_et_pour_le_meme_lead():
    retraits = [{"wct_id": "wct-1", "lead_id": "lead-1", "retrait_id": "r-1"}]
    assert retrait.retrait_applicable("wct-1", None, retraits)["retrait_id"] == "r-1"
    assert retrait.retrait_applicable("wct-2", "lead-1", retraits)["retrait_id"] == "r-1"  # autre chantier, même lead
    assert retrait.retrait_applicable("wct-2", "lead-2", retraits) is None
    assert retrait.retrait_applicable("wct-2", None, retraits) is None
    assert retrait.retrait_applicable(None, None, retraits) is None


def test_un_retrait_sans_lead_connu_ne_bloque_pas_tous_les_leads_inconnus():
    retraits = [{"wct_id": "wct-1", "lead_id": None, "retrait_id": "r-1"}]
    assert retrait.retrait_applicable("wct-2", None, retraits) is None


# -- registre ------------------------------------------------------------------------------------------------------
def test_derniere_revision_par_chantier_et_plateforme_la_plus_recente_en_dernier():
    propositions = [
        _proposition("a1", plateforme="facebook"), _proposition("b1", plateforme="instagram"),
        _proposition("a2", plateforme="facebook", revision=2),
    ]
    assert [p["contenu_id"] for p in registre.dernieres_revisions(propositions)] == ["b1", "a2"]
    assert registre.dernieres_revisions(propositions, "autre-wct") == []
    assert registre.est_derniere_revision(propositions[2], propositions)
    assert not registre.est_derniere_revision(propositions[0], propositions)


def test_statut_propose_puis_decision_puis_retrait_qui_l_emporte_sur_tout():
    proposition = _proposition()
    approbation = {"contenu_id": "c-1", "decision": registre.STATUT_APPROUVE, "par": "nathan", "role": "nathan_owner",
                   "source": "appareil", "motif": "", "horodatage": HORODATAGE}
    assert registre.statut(proposition, [], []) == registre.STATUT_PROPOSE
    assert registre.statut(proposition, [approbation], []) == registre.STATUT_APPROUVE
    assert registre.statut(proposition, [{**approbation, "decision": registre.STATUT_REJETE}], []) == "REJECTED"
    retraits = [{"wct_id": "wct-1", "lead_id": None}]
    assert registre.statut(proposition, [], retraits) == registre.STATUT_RETIRE
    assert registre.statut(proposition, [approbation], retraits) == registre.STATUT_RETIRE  # même approuvé


def test_la_vue_dit_la_decision_et_l_export():
    proposition = _proposition()
    approbation = {"contenu_id": "c-1", "decision": registre.STATUT_APPROUVE, "par": "nathan", "role": "nathan_owner",
                   "source": "appareil", "motif": "ok", "horodatage": HORODATAGE}
    vue = registre.vue(proposition, [approbation], [{"contenu_id": "c-1"}], [])
    assert vue["approval_status"] == registre.STATUT_APPROUVE and vue["exporte"] is True
    assert vue["decision"]["par"] == "nathan" and vue["decision"]["motif"] == "ok"
    non_decide = registre.vue(proposition, [], [], [])
    assert non_decide["decision"] is None and non_decide["exporte"] is False


def test_recherches_par_identifiant():
    propositions = [_proposition("a"), _proposition("b")]
    assert registre.proposition_par_id(propositions, "b")["contenu_id"] == "b"
    assert registre.proposition_par_id(propositions, "z") is None
    assert registre.decision_de("a", []) is None and registre.export_de("a", []) is None


# -- décision humaine ------------------------------------------------------------------------------------------------
def test_une_approbation_porte_l_empreinte_du_texte_decide():
    maillon, verdict = decision.construire_decision(
        _proposition(), "approuver", "nathan", "nathan_owner", "appareil", "", HORODATAGE,
    )
    assert verdict is None
    assert maillon["decision"] == registre.STATUT_APPROUVE and maillon["empreinte_texte"] == "empreinte-c-1"
    assert (maillon["par"], maillon["role"], maillon["source"]) == ("nathan", "nathan_owner", "appareil")


def test_un_rejet_exige_un_motif_qui_dit_pourquoi():
    maillon, verdict = decision.construire_decision(
        _proposition(), "rejeter", "nathan", "nathan_owner", "appareil", "ok", HORODATAGE,
    )
    assert maillon is None and verdict["code"] == verdicts.REJ_MOTIF_REQUIS
    maillon, verdict = decision.construire_decision(
        _proposition(), "rejeter", "nathan", "nathan_owner", "appareil", "trop vague, à refaire", HORODATAGE,
    )
    assert verdict is None and maillon["decision"] == registre.STATUT_REJETE
    assert maillon["motif"] == "trop vague, à refaire"


@pytest.mark.parametrize(("par", "role", "source"), [
    ("", "nathan_owner", "appareil"),
    ("Nathan Fictif", "nathan_owner", "appareil"),  # pas la forme d'un identifiant de personne
    ("nathan", "admin", "appareil"),  # le propriétaire seulement
    ("nathan", "nathan_owner", "agent"),  # deux voies seulement
    (None, "nathan_owner", "approbation"),
])
def test_sans_proprietaire_identifie_aucune_decision(par, role, source):
    maillon, verdict = decision.construire_decision(_proposition(), "approuver", par, role, source, "", HORODATAGE)
    assert maillon is None and verdict["code"] == verdicts.REJ_HUMAIN_ACTEUR_INVALIDE


def test_decision_inconnue_horodatage_et_motif_trop_long_sont_refuses():
    args = ("nathan", "nathan_owner", "appareil")
    _, verdict = decision.construire_decision(_proposition(), "publier", *args, "", HORODATAGE)
    assert verdict["code"] == verdicts.REJ_DECISION_INVALIDE
    _, verdict = decision.construire_decision(_proposition(), "approuver", *args, "", "demain")
    assert verdict["code"] == verdicts.REJ_HORODATAGE_INVALIDE
    _, verdict = decision.construire_decision(_proposition(), "approuver", *args, "x" * 501, HORODATAGE)
    assert verdict["code"] == verdicts.REJ_MOTIF_REQUIS


def test_la_decision_est_deterministe_par_contenu():
    args = ("nathan", "nathan_owner", "appareil", "", HORODATAGE)
    a, _ = decision.construire_decision(_proposition("c-1"), "approuver", *args)
    b, _ = decision.construire_decision(_proposition("c-1"), "approuver", *args)
    c, _ = decision.construire_decision(_proposition("c-2"), "approuver", *args)
    assert a["decision_id"] == b["decision_id"] != c["decision_id"]
