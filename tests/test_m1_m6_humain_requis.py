"""Les décisions de personne de M1, M5 et M6 refusent un agent seul, MÊME dans un mode où un N3 s'exécute sans file
(`autonome`) : la garde est dans l'outil, pas seulement dans le mode du département.

Vrai socle ; données fictives."""

from __future__ import annotations

import json

import cablage_qa as cq
import lea_rosalie_qa as lr
import pytest

from opsys import approbations, stockage

HORO = "2026-11-02T10:00:00-05:00"
SIGNAL = "courriel:" + "0" * 64
OUTILS = [
    ("m1_consigner_correction_tri", {"signal_id": SIGNAL, "classe_corrigee": "plainte", "horodatage": HORO}),
    ("m1_consigner_retour_brouillon", {"brouillon_id": "b1", "issue": "accepte", "horodatage": HORO}),
    (
        "m1_decider_proposition",
        {"proposition_id": "pr-1", "etape": "refusee", "motif": "Refus de la direction", "horodatage": HORO},
    ),
    (
        "m1_attester_moyen_verification",
        {"verification_id": "vi-" + "0" * 16, "moyen": "rappel_numero_dossier", "horodatage": HORO},
    ),
    (
        "m1_decider_verification_identite",
        {
            "verification_id": "vi-" + "0" * 16,
            "decision": "refuser",
            "motif": "Usurpation soupçonnée",
            "horodatage": HORO,
        },
    ),
    ("m1_confirmer_rendez_vous", {"rdv_id": "rdv-" + "0" * 16, "intervention_id": "i1", "horodatage": HORO}),
    (
        "m5_classer_facture_courriel",
        {"facture_courriel_id": "fc-" + "0" * 16, "statut": "ecartee", "motif": "Fausse facture", "horodatage": HORO},
    ),
    (
        "m6_valider_confirmation_courriel",
        {
            "confirmation_id": "cf-" + "0" * 16,
            "decision": "ecarter",
            "motif": "Hameçonnage probable",
            "horodatage": HORO,
        },
    ),
]


@pytest.fixture
def w(tmp_path, monkeypatch):
    monde = lr.monter(tmp_path, monkeypatch)
    with stockage.transaction() as cnx:
        for dep in monde.capacites.departements.values():
            approbations.fixer_mode(cnx, dep.id, "autonome", "nathan")
    yield monde
    cq.demonter()


@pytest.mark.parametrize(("outil", "arguments"), OUTILS, ids=[o for o, _ in OUTILS])
def test_un_agent_seul_ne_prend_pas_une_decision_de_personne_meme_en_autonome(w, outil, arguments):
    r = w.appeler(outil, **arguments)
    assert r.get("statut") != "en_attente_approbation", "autonome : l'outil s'exécute..."
    assert "REJ-HUMAIN-REQUIS" in json.dumps(r), "...et se refuse lui-même"
    assert not (r.get("ok") and r["resultat"].get("accepte") is True)


def test_les_outils_de_decision_de_personne_sont_tous_n3_et_aucun_n_est_ouvert_aux_appareils_sauf_la_confirmation(w):
    par_nom = {o.nom: o for o in w.capacites.lister()}
    for nom, _ in OUTILS:
        assert par_nom[nom].niveau_effectif.value == "N3", nom
        assert (par_nom[nom].roles_appareil == frozenset({"admin"})) == (nom == "m1_confirmer_rendez_vous"), nom
