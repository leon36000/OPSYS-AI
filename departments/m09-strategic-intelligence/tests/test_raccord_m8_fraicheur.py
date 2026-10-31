"""Raccord M9 -> M8 : la fenêtre de fraîcheur DÉCLARÉE par le propriétaire (`fraicheur_attendue_s`), comparée (fictif).

Contrat producteur : departments/m08-analytics/docs/FRAICHEUR-ATTENDUE-LECTURES.md. M8 déclare une fenêtre par lecture
(à la racine de la réponse) et sa version ; il ne juge jamais qu'une lecture est périmée. M9 compare l'âge qu'il calcule
lui-même. Règle de M9 : une fenêtre n'est retenue que si c'est un entier (`type(x) is int`) de 1 à 315 360 000 secondes
ET si sa version se recalcule à l'identique ; tout le reste est ignoré (NON_EVALUEE), jamais HORS_FENETRE."""

import pytest
from m9_strategic_intelligence import capture_strategique as cs
from m9_strategic_intelligence import catalogue_producteurs as cat
from m9_strategic_intelligence import dossier_strategique as ds
from m9_strategic_intelligence import encodage
from m9_strategic_intelligence import sessions_conseil as sc

FICTIF = True
JOUR = 86400
REF = "2026-10-21T12:00:00Z"
DERNIER_FAIT = "2026-10-20T12:00:00Z"  # un jour avant la référence : age_s == 86400
VUE = "m8.vue_executive"
MESURES = "m8.mesures_chantier"
OUTILS = {VUE: "m8_lire_vue_executive", MESURES: "m8_lire_mesures_chantier"}


def version(lecture_id, secondes):
    return encodage.empreinte({"lecture": OUTILS[lecture_id], "fraicheur_attendue_s": secondes})


def _vue(dernier_fait=DERNIER_FAIT, **declaration):
    return {
        "ok": True,
        "resultat": {
            "entonnoir": {"sources": [{"source": "m3", "dernier_fait_le": dernier_fait}]},
            "marge_reelle": {"chantiers": []},
            **declaration,
        },
    }


def _mesures(dernier_fait=DERNIER_FAIT, **declaration):
    return {
        "ok": True,
        "resultat": {"trouve": True, "horodatage_completion": dernier_fait, "mesures": [], **declaration},
    }


def declaration(lecture_id, secondes):
    return {"fraicheur_attendue_s": secondes, "version_definition_fraicheur": version(lecture_id, secondes)}


def _capture(lecture_id, page, *, index=0, precedent="", recu=REF):
    arguments = {"aujourd_hui": "2026-10-21"} if lecture_id == VUE else {"wct_id": "WCT-1"}
    return cs.construire(
        cat.obtenir(lecture_id),
        arguments,
        [page],
        recu_a=recu,
        reference="2026-10-21" if lecture_id == VUE else None,
        index=index,
        hash_precedent=precedent,
    )


def _couverture(captures, lecture_id, reference=REF, **kwargs):
    resultat = cs.evaluer_couverture(
        captures, reference=reference, connaissance=reference, attendues=[lecture_id], **kwargs
    )
    return resultat["lectures"][0]


@pytest.mark.parametrize("lecture_id", [VUE, MESURES])
def test_la_lecture_declare_ou_se_trouve_la_fenetre(lecture_id):
    lecture = cat.obtenir(lecture_id)
    assert lecture.fraicheur_attendue == "resultat.fraicheur_attendue_s"
    assert lecture.fraicheur_version == "resultat.version_definition_fraicheur"
    assert cat.obtenir("m5.prevision_tresorerie").fraicheur_attendue is None


@pytest.mark.parametrize(("lecture_id", "fabrique"), [(VUE, _vue), (MESURES, _mesures)])
def test_sans_declaration_du_proprietaire_la_fraicheur_reste_non_evaluee(lecture_id, fabrique):
    entree = _couverture([_capture(lecture_id, fabrique())], lecture_id)
    assert entree["age_s"] == JOUR and entree["fraicheur"] == "NON_EVALUEE"
    assert "fraicheur_attendue_s" not in entree and "fraicheur_declaration_ignoree" not in entree


@pytest.mark.parametrize(("lecture_id", "fabrique"), [(VUE, _vue), (MESURES, _mesures)])
def test_dans_la_fenetre_et_hors_fenetre_selon_l_age_quand_m8_declare(lecture_id, fabrique):
    dans = _couverture([_capture(lecture_id, fabrique(**declaration(lecture_id, 2 * JOUR)))], lecture_id)
    assert dans["fraicheur"] == "DANS_LA_FENETRE" and dans["fraicheur_attendue_s"] == 2 * JOUR
    assert dans["fraicheur_source"] == "PRODUCTEUR"
    hors = _couverture([_capture(lecture_id, fabrique(**declaration(lecture_id, JOUR - 1)))], lecture_id)
    assert hors["fraicheur"] == "HORS_FENETRE" and hors["age_s"] == JOUR
    limite = _couverture([_capture(lecture_id, fabrique(**declaration(lecture_id, JOUR)))], lecture_id)
    assert limite["fraicheur"] == "DANS_LA_FENETRE"  # l'âge égal à la fenêtre est dans la fenêtre


def test_un_fait_posterieur_a_la_reference_n_est_jamais_dans_la_fenetre_ni_hors_fenetre():
    futur = _capture(VUE, _vue(dernier_fait="2026-10-22T12:00:00Z", **declaration(VUE, 5 * JOUR)))
    entree = _couverture([futur], VUE)
    assert entree["statut"] == "FUTURE" and entree["age_s"] < 0 and entree["fraicheur"] == "HORS_FENETRE"


@pytest.mark.parametrize(
    "valeur",
    [True, False, 86400.0, "86400", None, 0, -5, 315360001, 10**12, [86400], {"s": 1}],
)
def test_une_fenetre_invalide_est_ignoree_jamais_hors_fenetre(valeur):
    page = _vue(fraicheur_attendue_s=valeur, version_definition_fraicheur=version(VUE, 86400))
    entree = _couverture([_capture(VUE, page)], VUE)
    assert entree["fraicheur"] == "NON_EVALUEE" and "fraicheur_attendue_s" not in entree
    assert entree["age_s"] == JOUR


@pytest.mark.parametrize("secondes", [1, 315360000])
def test_les_bornes_de_la_fenetre_sont_admises(secondes):
    entree = _couverture([_capture(VUE, _vue(**declaration(VUE, secondes)))], VUE)
    assert entree["fraicheur_attendue_s"] == secondes and entree["fraicheur"] in {"DANS_LA_FENETRE", "HORS_FENETRE"}
    assert entree["fraicheur"] == ("DANS_LA_FENETRE" if secondes >= JOUR else "HORS_FENETRE")


@pytest.mark.parametrize(
    "page",
    [
        _vue(fraicheur_attendue_s=86400),  # version absente
        _vue(fraicheur_attendue_s=86400, version_definition_fraicheur="0" * 64),  # version qui ne se recalcule pas
        _vue(fraicheur_attendue_s=86400, version_definition_fraicheur=version(MESURES, 86400)),  # autre lecture
        _vue(fraicheur_attendue_s=86400, version_definition_fraicheur=7),
        _vue(fraicheur_attendue_s=172800, version_definition_fraicheur=version(VUE, 86400)),  # autre fenêtre
        _vue(fraicheur_attendue_refusee={"raison": "entier attendu", "source": "department.yaml"}),
        _vue(version_definition_fraicheur=version(VUE, 86400)),  # version sans fenêtre
    ],
)
def test_une_declaration_incoherente_ou_refusee_par_m8_n_evalue_rien(page):
    entree = _couverture([_capture(VUE, page)], VUE)
    assert entree["fraicheur"] == "NON_EVALUEE" and "fraicheur_attendue_s" not in entree
    assert entree["fraicheur_declaration_ignoree"] is True


def test_une_declaration_dite_ignoree_n_est_pas_une_fenetre():
    page = _vue(**declaration(VUE, 86400), fraicheur_attendue_ignorees=["m8_lire_autre"])
    assert _couverture([_capture(VUE, page)], VUE)["fraicheur"] == "DANS_LA_FENETRE"


def test_la_fenetre_du_proprietaire_ne_vaut_que_pour_sa_lecture_et_la_derniere_capture():
    ancienne = _capture(VUE, _vue(**declaration(VUE, JOUR - 1)), index=0)
    recente = _capture(
        VUE,
        _vue(**declaration(VUE, 3 * JOUR)),
        index=1,
        precedent=ancienne["hash_maillon"],
        recu="2026-10-21T12:00:01Z",
    )
    entree = _couverture([ancienne, recente], VUE, reference="2026-10-21T12:00:02Z")
    assert entree["fraicheur_attendue_s"] == 3 * JOUR and entree["fraicheur"] == "DANS_LA_FENETRE"
    autre = _couverture([ancienne], VUE)
    assert autre["fraicheur"] == "HORS_FENETRE"
    sans_age = cs.evaluer_couverture([], reference=REF, connaissance=REF, attendues=[VUE, MESURES])["lectures"]
    assert all(e["statut"] == "ABSENTE" and "fraicheur" not in e for e in sans_age)


def test_une_attente_explicite_de_l_appelant_l_emporte_et_sa_source_est_dite():
    capture = _capture(VUE, _vue(**declaration(VUE, 3 * JOUR)))
    entree = _couverture([capture], VUE, fraicheur_attendue_s={VUE: 3600})
    assert entree["fraicheur"] == "HORS_FENETRE" and entree["fraicheur_attendue_s"] == 3600
    assert entree["fraicheur_source"] == "APPELANT"


def test_changer_la_fenetre_declaree_n_est_pas_une_contradiction():
    premiere = _capture(VUE, _vue(**declaration(VUE, JOUR)), index=0)
    seconde = _capture(
        VUE,
        _vue(**declaration(VUE, 2 * JOUR)),
        index=1,
        precedent=premiere["hash_maillon"],
        recu="2026-10-21T12:00:01Z",
    )
    assert premiere["reponse_sha256"] != seconde["reponse_sha256"]
    assert cs.contradictions([premiere, seconde]) == []


def test_le_conseil_voit_la_fenetre_et_le_statut_hors_fenetre():
    capture = _capture(VUE, _vue(**declaration(VUE, JOUR - 1)))
    dossier = ds.construire(
        [capture],
        question="La vue exécutive est-elle encore actuelle ?",
        domaines=["strategie"],
        reference=REF,
        connaissance=REF,
        attendues=[VUE],
    )
    ouverture, session_id = sc.ouvrir([], dossier=dossier, importance="courante", budget_tokens=100000, recu_a=REF)
    role = next(iter(ouverture["tours"]))
    entree = sc.entree_tour([ouverture], session_id, role)
    (lecture,) = entree["donnees"]["couverture"]["lectures"]
    assert lecture["fraicheur"] == "HORS_FENETRE" and lecture["fraicheur_attendue_s"] == JOUR - 1
    assert lecture["fraicheur_source"] == "PRODUCTEUR" and lecture["age_s"] == JOUR
    assert "HORS_FENETRE" in entree["consigne"]["age_des_lectures"]
