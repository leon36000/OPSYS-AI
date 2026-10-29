"""M9.17 — orchestrateur : états, rejeu, constats issus de l'état natif, chaîne (fictif)."""

import copy

import pytest
from m9_strategic_intelligence import orchestrateur as oc

FICTIF = True
SHA = "a" * 64
T = "2026-10-27T12:00:00Z"
SOURCE = "m2.leads#0:p0.resultat.resultat.leads[0].lead_id"


def proposer(chaine, sha=SHA, demande="0123456789ab", **extra):
    base = dict(
        departement="m02-revenue-crm",
        outil="m2_reassigner_lead",
        arguments_sha256=sha,
        demande_id=demande,
        niveau="N3",
        sources=[SOURCE],
        motif="charge",
        recu_a=T,
        propose_par="admin.fictif",
    )
    maillon = oc.proposition(chaine, **{**base, **extra})
    chaine.append(maillon)
    return maillon


def natif(statut="en_attente", succes=None, sha=SHA, outil="m2_reassigner_lead", trouvee=True):
    return {
        "ok": True,
        "trouvee": trouvee,
        "statut": statut,
        "outil": outil,
        "arguments_sha256": sha,
        "succes_declare": succes,
        "decide_par": "nathan.fictif",
        "resultat_sha256": "b" * 64,
    }


def reconcilier(chaine, action_id, lecture, recu=T):
    maillon = oc.reconciliation(chaine, action_id, lecture, recu_a=recu)
    if maillon is not None:
        chaine.append(maillon)
    return maillon


def test_cycle_complet_et_rejeu_selon_l_etat():
    chaine = []
    action = proposer(chaine)["action_id"]
    assert oc.etat(chaine)[action]["etat"] == "EN_ATTENTE_APPROBATION"
    with pytest.raises(ValueError, match="REJ-ACTION-REJEU"):
        proposer(chaine, demande="ffffffffffff")
    assert reconcilier(chaine, action, natif("en_attente")) is None, (
        "constat identique à l'état initial : rien à écrire"
    )
    assert reconcilier(chaine, action, natif("refusee"))["constat"] == "REFUSEE"
    second = proposer(chaine, demande="111111111111")
    assert second["tentative"] == 2 and second["action_id"] == action
    assert reconcilier(chaine, action, natif("executee", succes=True))["constat"] == "EXECUTEE_CONFIRMEE"
    assert reconcilier(chaine, action, natif("executee", succes=True)) is None
    with pytest.raises(ValueError, match="REJ-ACTION-REJEU"):
        proposer(chaine, demande="222222222222")
    assert oc.valider_chaine(chaine) == (True, "")
    assert oc.vue(chaine)["par_etat"] == {"EXECUTEE_CONFIRMEE": 1}


@pytest.mark.parametrize(
    "lecture, attendu",
    [
        (None, "INCONNU"),
        ({"ok": True, "trouvee": False}, "INCONNU"),
        ({"ok": False}, "INCONNU"),
        (natif("en_cours"), "INCONNU"),
        (natif("executee", succes=None), "INCONNU"),
        (natif("executee", succes=False), "INCONNU"),
        (natif("echec"), "ECHEC"),
        (natif("refusee"), "REFUSEE"),
        (natif("autre"), "INCONNU"),
        (natif("executee", succes=True, sha="c" * 64), "INCONNU"),
        (natif("executee", succes=True, outil="m2_preparer_relance"), "INCONNU"),
    ],
)
def test_constats_issus_de_l_etat_natif(lecture, attendu):
    chaine = []
    action = proposer(chaine)["action_id"]
    reconcilier(chaine, action, lecture)
    assert oc.etat(chaine)[action]["etat"] == attendu


def test_inconnu_bloque_le_rejeu_jusqu_a_un_constat_definitif():
    chaine = []
    action = proposer(chaine)["action_id"]
    reconcilier(chaine, action, None)
    with pytest.raises(ValueError, match="REJ-ACTION-REJEU.*ne jamais rejouer"):
        proposer(chaine, demande="333333333333")
    reconcilier(chaine, action, natif("refusee"))
    assert proposer(chaine, demande="333333333333")["tentative"] == 2


@pytest.mark.parametrize(
    "extra, code",
    [
        ({"outil": "m2_ingerer_lead"}, "REJ-ACTION-NON-AUTORISEE"),
        ({"departement": "m05-financecore"}, "REJ-ACTION-NON-AUTORISEE"),
        ({"arguments_sha256": "zz"}, "REJ-ACTION-ARGUMENTS"),
        ({"demande_id": "pas-une-demande"}, "REJ-ACTION-DEMANDE"),
        ({"sources": []}, "REJ-ACTION-SOURCES"),
        ({"sources": ["libre"]}, "REJ-ACTION-SOURCES"),
        ({"sources": [SOURCE] * 13}, "REJ-ACTION-SOURCES"),
        ({"motif": ""}, "REJ-ACTION-MOTIF"),
        ({"recu_a": "2026-10-27T12:00:00"}, "REJ-CAPTURE-TEMPS"),
    ],
)
def test_propositions_refusees(extra, code):
    chaine = []
    with pytest.raises(ValueError, match=code):
        proposer(chaine, **extra)
    assert chaine == []


def test_sources_admises_references_de_playbook_priorisation_et_faits():
    chaine = []
    proposer(chaine, sources=[SOURCE, "playbook:" + "a" * 64, "priorisation:" + "b" * 32, "radar:" + "c" * 12])
    with pytest.raises(ValueError, match="REJ-ACTION-INCONNUE"):
        oc.reconciliation(chaine, "inconnue", None, recu_a=T)


def test_chaine_falsifiee_detectee():
    chaine = []
    proposer(chaine)
    falsifiee = copy.deepcopy(chaine)
    falsifiee[0]["motif"] = "autre"
    assert oc.valider_chaine(falsifiee)[0] is False
