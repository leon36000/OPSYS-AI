"""M9.16 — plans et OKR : révision, retard, annulation, source changée, suivi n'est pas effet (fictif)."""

import copy

import pytest
from m9_strategic_intelligence import capture_strategique as cs
from m9_strategic_intelligence import catalogue_producteurs as cat
from m9_strategic_intelligence import plans as pl

FICTIF = True
CONNAISSANCE = "2026-10-28T13:00:00Z"
T = "2026-10-20T12:00:00Z"
ADRESSE = "m6.disponibilite#0:p0.resultat.resultat.reservations_actives[0].statut"
FAITS = {ADRESSE: "partiel"}


def disponibilite(statut):
    return {
        "ok": True,
        "resultat": {
            "accepte": True,
            "resultat": {
                "articles": [{"materiau_id": "M1"}],
                "tronque": False,
                "reservations_actives": [
                    {"devis_id": "D1", "chantier_id": "C1", "statut": statut, "lignes_manquantes": []}
                ],
            },
        },
    }


def captures(*statuts):
    chaine, precedent = [], cs.HASH_INITIAL
    for index, statut in enumerate(statuts):
        capture = cs.construire(
            cat.obtenir("m6.disponibilite"),
            {},
            [disponibilite(statut)],
            recu_a=f"2026-10-2{index + 1}T12:00:00Z",
            reference=None,
            index=index,
            hash_precedent=precedent,
        )
        chaine.append(capture)
        precedent = capture["hash_maillon"]
    return chaine


def plan(**extra):
    base = {
        "plan_id": "rupture-gouttieres",
        "objectif": "Combler le manque de gouttières avant la prochaine intervention",
        "porteur": "nathan",
        "echeance": "2026-10-30",
        "resultats_cles": [
            {
                "id": "reservation_prete",
                "libelle": "Toutes les réservations actives sont prêtes",
                "lecture": "m6.disponibilite",
                "chemin": "resultat.resultat.reservations_actives[*].statut",
                "operateur": "==",
                "cible": "pret",
            },
            {"id": "fournisseur_confirme", "libelle": "Le fournisseur confirme le délai", "operateur": "manuel"},
        ],
        "sources": [ADRESSE],
        "decision_ref": "decision-12",
    }
    return {**base, **extra}


def deposer(chaine, **kwargs):
    maillon = pl.enregistrer(
        chaine, kwargs.pop("plan", plan()), FAITS, recu_a=kwargs.pop("recu_a", T), par="admin.fictif", **kwargs
    )
    chaine.append(maillon)
    return maillon


def test_depot_revision_et_annulation_conservent_l_historique():
    chaine = []
    assert deposer(chaine)["version"] == 1
    revise = deposer(
        chaine, plan=plan(echeance="2026-11-15"), recu_a="2026-10-22T12:00:00Z", motif_revision="délai fournisseur"
    )
    assert revise["version"] == 2 and revise["motif_revision"] == "délai fournisseur"
    chaine.append(
        pl.annuler(chaine, "rupture-gouttieres", "chantier reporté", recu_a="2026-10-23T12:00:00Z", par="admin.fictif")
    )
    vue = pl.vue(chaine, captures("partiel"), connaissance=CONNAISSANCE, jour="2026-10-28")["plans"][0]
    assert vue["statut"] == "ANNULE" and vue["versions_total"] == 2 and vue["annulation"]["motif"] == "chantier reporté"
    assert [h["version"] for h in vue["historique"]] == [1, 2] and vue["echeance"] == "2026-11-15"
    with pytest.raises(ValueError, match="REJ-PLAN-ANNULE"):
        deposer(chaine, plan=plan(echeance="2026-12-01"), motif_revision="rouvrir")
    assert pl.valider_chaine(chaine) == (True, "")


@pytest.mark.parametrize(
    "kwargs, code",
    [
        ({"motif_revision": "x"}, "REJ-PLAN-REVISION"),  # premier dépôt avec motif
        ({"plan": plan(echeance="2026-13-40")}, "REJ-PLAN-DATE"),
        ({"plan": plan(resultats_cles=[])}, "REJ-PLAN-RESULTAT"),
        ({"plan": plan(resultats_cles=[{"id": "a", "libelle": "x", "operateur": "=="}])}, "REJ-PLAN-RESULTAT"),
        ({"plan": plan(sources=["m6.disponibilite#9:p0.inconnu"])}, "REJ-PLAN-SOURCE"),
        ({"plan": plan(porteur="")}, "REJ-PLAN-CHAMP"),
        ({"plan": {**plan(), "cout": "5"}}, "REJ-PLAN-CHAMP"),
        ({"recu_a": "2026-10-20T12:00:00"}, "REJ-CAPTURE-TEMPS"),
    ],
)
def test_depots_refuses(kwargs, code):
    with pytest.raises(ValueError, match=code):
        deposer([], **kwargs)


def test_revision_exige_un_motif_et_un_changement():
    chaine = []
    deposer(chaine)
    with pytest.raises(ValueError, match="REJ-PLAN-REVISION"):
        deposer(chaine, recu_a="2026-10-21T12:00:00Z", motif_revision="rien ne change")
    with pytest.raises(ValueError, match="REJ-PLAN-REVISION"):
        deposer(chaine, plan=plan(echeance="2026-11-01"), recu_a="2026-10-21T12:00:00Z")


def test_resultat_mesure_retard_et_suivi_n_est_pas_un_effet():
    chaine = []
    deposer(chaine)
    chaine.append(
        pl.noter_suivi(
            chaine, "rupture-gouttieres", "reservation_prete", "commande passée", recu_a="2026-10-24T12:00:00Z", par="a"
        )
    )
    chaine.append(
        pl.noter_suivi(
            chaine, "rupture-gouttieres", "fournisseur_confirme", "appel fait", recu_a="2026-10-24T13:00:00Z", par="a"
        )
    )
    en_retard = pl.vue(chaine, captures("partiel"), connaissance=CONNAISSANCE, jour="2026-10-31")["plans"][0]
    assert en_retard["statut"] == "EN_RETARD"
    mesure = {r["id"]: r for r in en_retard["resultats_cles"]}
    assert (
        mesure["reservation_prete"]["mesure"]["statut"] == "NON_SATISFAIT"
        and mesure["reservation_prete"]["suivis_declares"] == 1
    )
    assert mesure["fournisseur_confirme"]["mesure"]["statut"] == "A_JUGER_PAR_LA_PERSONNE"
    dans_les_temps = pl.vue(chaine, captures("partiel"), connaissance=CONNAISSANCE, jour="2026-10-28")["plans"][0]
    assert dans_les_temps["statut"] == "EN_COURS"
    # Même mesuré atteint, un résultat « manuel » garde le plan non atteint : la personne le juge hors de M9.
    pret = pl.vue(chaine, captures("partiel", "pret"), connaissance=CONNAISSANCE, jour="2026-10-28")["plans"][0]
    assert {r["id"]: r["mesure"]["statut"] for r in pret["resultats_cles"]}["reservation_prete"] == "SATISFAIT"
    assert pret["statut"] == "EN_COURS"


def test_plan_entierement_mesurable_est_atteint_seulement_sur_mesure():
    chaine = []
    seul = plan(resultats_cles=[plan()["resultats_cles"][0]], plan_id="p-mesure")
    deposer(chaine, plan=seul)
    assert (
        pl.vue(chaine, captures("partiel"), connaissance=CONNAISSANCE, jour="2026-10-28")["plans"][0]["statut"]
        == "EN_COURS"
    )
    assert (
        pl.vue(chaine, captures("pret"), connaissance=CONNAISSANCE, jour="2026-10-28")["plans"][0]["statut"]
        == "ATTEINT_MESURE"
    )
    assert (
        pl.vue(chaine, [], connaissance=CONNAISSANCE, jour="2026-10-28")["plans"][0]["resultats_cles"][0]["mesure"][
            "statut"
        ]
        == "INCONNU"
    )


def test_source_changee_signalee_sans_modifier_le_plan_et_connaissance_anterieure():
    chaine = []
    deposer(chaine)
    capt = captures("partiel", "pret")
    vue = pl.vue(chaine, capt, connaissance=CONNAISSANCE, jour="2026-10-28")["plans"][0]
    assert vue["sources_changees"] == [
        {"source": ADRESSE, "avant": "partiel", "maintenant": "pret", "capture": 1, "raison": "valeur différente"}
    ]
    assert vue["version"] == 1, "le plan n'a pas été réécrit"
    avant = pl.vue(chaine, capt, connaissance="2026-10-21T18:00:00Z", jour="2026-10-28")["plans"][0]
    assert avant["sources_changees"] == [], "la seconde capture n'était pas encore connue"
    assert (
        pl.vue(chaine, [], connaissance=CONNAISSANCE, jour="2026-10-28")["plans"][0]["sources_changees"][0]["raison"]
        == "lecture non disponible"
    )


def test_chaine_falsifiee_detectee_et_suivi_hors_perimetre_refuse():
    chaine = []
    deposer(chaine)
    falsifiee = copy.deepcopy(chaine)
    falsifiee[0]["plan"]["objectif"] = "autre"
    assert pl.valider_chaine(falsifiee)[0] is False
    with pytest.raises(ValueError, match="REJ-PLAN-RESULTAT"):
        pl.noter_suivi(chaine, "rupture-gouttieres", "inconnu", "x", recu_a=T, par="a")
    with pytest.raises(ValueError, match="REJ-PLAN-INCONNU"):
        pl.noter_suivi(chaine, "absent", "reservation_prete", "x", recu_a=T, par="a")
    with pytest.raises(ValueError, match="REJ-PLAN-INCONNU"):
        pl.annuler(chaine, "absent", "x", recu_a=T, par="a")
