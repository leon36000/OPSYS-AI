"""M2-C1 : le plan de réparation (module pur `reparation.py`). Des actions PROPOSÉES, jamais exécutées.

Prouvé : chaque règle SLA et chaque contrôle d'intégrité a son action ; une action qui passe par un outil de niveau N3
est
sensible et le dit (le niveau est RELU des outils réels, jamais recopié) ; un niveau inconnu est traité comme sensible ;
aucune action n'a `execute: True` ; l'urgence ordonne le plan (plainte, lead chaud, lead sans propriétaire, …) ; la
sortie
est déterministe ; la prochaine meilleure action existante accompagne un lead. Données fictives (`fictif: true`).
"""

from __future__ import annotations

import copy
import json
import random

import pytest
from m2_revenue_crm import integrite, outils, reparation, sla

FICTIF = True
NIVEAUX_REELS = {o.nom: o.niveau_effectif.value for o in outils.outils()}


def violation(regle, lead_id="lead-1", **plus):
    return {
        "regle": regle,
        "lead_id": lead_id,
        "statut": "qualifie",
        "proprietaire": "vendeur.un",
        "depuis": "2026-11-01T12:00:00+00:00",
        "ecoule_heures": 5,
        "seuil": None,
        "raison": f"raison de {regle}",
        "donnee": {},
        **plus,
    }


def anomalie(controle, lead_id="lead-1", client_id=None, **donnee):
    return {
        "controle": controle,
        "nature": f"nature-{controle}",
        "lead_id": lead_id,
        "client_id": client_id,
        "donnee": donnee,
    }


def plan(violations=(), anomalies=(), niveaux=NIVEAUX_REELS, suggestions=None):
    return reparation.planifier(violations, anomalies, niveaux=niveaux, suggestions=suggestions)


def test_chaque_regle_sla_et_chaque_controle_ont_une_action():
    assert set(reparation.ACTIONS) == set(sla.ORDRE_REGLES) | set(integrite.CONTROLES)


@pytest.mark.parametrize("regle", sla.ORDRE_REGLES)
def test_une_violation_donne_une_entree_avec_au_moins_une_action_proposee(regle):
    (entree,) = plan([violation(regle)])
    assert entree["cible"] == {"type": "lead", "id": "lead-1"} and entree["actions"]
    assert entree["problemes"] == [{"source": "sla", "code": regle, "raison": f"raison de {regle}"}]
    assert all(a["execute"] is False for a in entree["actions"])


@pytest.mark.parametrize("controle", integrite.CONTROLES)
def test_une_anomalie_d_integrite_donne_une_action_de_revue_jamais_une_correction_automatique(controle):
    (entree,) = plan(anomalies=[anomalie(controle)])
    assert entree["problemes"][0]["source"] == "integrite" and entree["actions"]
    assert all(a["execute"] is False for a in entree["actions"])


def test_les_niveaux_sont_ceux_des_outils_reels_et_toute_action_n3_demande_une_approbation():
    assert reparation.OUTILS_CITES and set(reparation.OUTILS_CITES) <= set(NIVEAUX_REELS), "outils cités existants"
    tout = plan([violation(r) for r in sla.ORDRE_REGLES], [anomalie(c) for c in integrite.CONTROLES])
    vues = 0
    for entree in tout:
        for action in entree["actions"]:
            if action["outil"] is None:
                assert action["niveau"] is None and action["approbation_requise"] is False and action["note"]
                continue
            vues += 1
            assert action["niveau"] == NIVEAUX_REELS[action["outil"]]
            assert action["approbation_requise"] is (action["niveau"] in ("N3", "N4", "N5"))
    assert vues >= 6


def test_une_lecture_n0_ne_demande_pas_d_approbation_une_ecriture_n3_oui():
    (retard,) = plan([violation("tache_en_retard")])
    assert [(a["outil"], a["niveau"], a["approbation_requise"]) for a in retard["actions"]] == [
        ("m2_suggerer_prochaine_action", "N0", False)
    ]
    (sans_proprio,) = plan([violation("lead_sans_proprietaire")])
    assert sans_proprio["actions"][0]["outil"] == "m2_transitionner_statut"
    assert sans_proprio["actions"][0]["approbation_requise"] is True


def test_un_niveau_inconnu_est_traite_comme_sensible_jamais_comme_libre():
    (entree,) = plan([violation("lead_sans_proprietaire")], niveaux={})
    assert entree["actions"][0]["niveau"] is None and entree["actions"][0]["approbation_requise"] is True


def test_l_urgence_ordonne_le_plan_plainte_chaud_proprietaire_action_soumission_retard_photos():
    ordre = [
        "plainte_non_escaladee",
        "lead_chaud_non_contacte",
        "lead_sans_proprietaire",
        "prochaine_action_obligatoire",
        "soumission_non_relancee",
        "tache_en_retard",
        "photos_non_recues",
    ]
    melange = [violation(r, lead_id=f"lead-{r}") for r in ordre]
    random.Random(7).shuffle(melange)
    assert [e["cible"]["id"] for e in plan(melange)] == [f"lead-{r}" for r in ordre]


def test_un_lead_aux_problemes_multiples_est_une_entree_unique_a_la_priorite_la_plus_forte_sans_action_en_double():
    entrees = plan(
        [
            violation("lead_sans_proprietaire"),
            violation("prochaine_action_obligatoire"),
            violation("plainte_non_escaladee"),
        ],
        [anomalie("pipeline_incoherent"), anomalie("pipeline_incoherent")],
    )
    (entree,) = entrees
    assert entree["priorite"] == 1
    ids = [a["action_id"] for a in entree["actions"]]
    assert ids == sorted(set(ids), key=ids.index), "pas d'action en double"
    assert {a["action_id"] for a in entree["actions"]} >= {
        "escalader_plainte",
        "assigner_proprietaire",
        "fixer_prochaine_action",
        "revue_administrateur",
    }
    assert ids[0] == "escalader_plainte", "l'action de la priorité la plus forte vient d'abord"
    assert len(entree["problemes"]) == 5


def test_la_cible_est_le_lead_sinon_le_client_sinon_le_devis():
    entrees = plan(
        anomalies=[
            anomalie("client_sans_contact", lead_id=None, client_id="client-9"),
            anomalie("soumission_orpheline", lead_id=None, devis_id="devis-7"),
            anomalie("activite_sans_lead", lead_id="fantome"),
        ]
    )
    assert sorted((e["cible"]["type"], e["cible"]["id"]) for e in entrees) == [
        ("client", "client-9"),
        ("devis", "devis-7"),
        ("lead", "fantome"),
    ]


def test_la_prochaine_meilleure_action_existante_accompagne_le_lead():
    suggestion = {
        "regle": "assigner_owner",
        "suggestion": "Assigner un représentant et qualifier ce lead.",
        "motif": "Aucun propriétaire assigné",
    }
    (avec,) = plan([violation("lead_sans_proprietaire")], suggestions={"lead-1": suggestion})
    assert avec["prochaine_action_suggeree"] == suggestion
    (sans,) = plan([violation("lead_sans_proprietaire")])
    assert sans["prochaine_action_suggeree"] is None


def test_le_plan_ne_depend_pas_de_l_ordre_des_entrees_ne_les_modifie_pas_et_est_repetable():
    violations = [violation(r, lead_id=f"l{i}") for i, r in enumerate(sla.ORDRE_REGLES)]
    anomalies = [anomalie(c, lead_id=f"a{i}") for i, c in enumerate(integrite.CONTROLES)]
    avant = copy.deepcopy((violations, anomalies))
    reference = plan(violations, anomalies)
    assert (violations, anomalies) == avant
    for graine in range(6):
        v, a = list(violations), list(anomalies)
        random.Random(graine).shuffle(v)
        random.Random(graine).shuffle(a)
        assert plan(v, a) == reference


def test_le_plan_ne_porte_aucune_donnee_personnelle_ni_aucun_texte_libre():
    texte = json.dumps(
        plan([violation(r) for r in sla.ORDRE_REGLES], [anomalie(c) for c in integrite.CONTROLES]), ensure_ascii=False
    )
    for personnel in ("@", "example.test", "418-555", "telephone"):
        assert personnel not in texte


def test_aucune_action_ne_promet_un_envoi_un_prix_une_date_ou_une_fusion():
    for code, (_, libelle, outil, _) in reparation.ACTIONS.items():
        assert outil not in ("m2_envoyer", "m2_fusionner_clients"), code
        minuscule = libelle.lower()
        assert "fusionne automatiquement" not in minuscule and "supprim" not in minuscule
        assert "prix" not in minuscule and "remise" not in minuscule


def test_le_module_est_pur():
    from pathlib import Path

    source = Path(reparation.__file__).read_text(encoding="utf-8")
    assert "import opsys" not in source and "from opsys" not in source and "datetime" not in source
