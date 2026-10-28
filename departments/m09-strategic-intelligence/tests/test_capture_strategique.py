"""M9.1 — captures : quatre temps distincts, chaîne, arrivée tardive, contradictions, couverture (fictif)."""

import copy

import pytest
from m9_strategic_intelligence import capture_strategique as cs
from m9_strategic_intelligence import catalogue_producteurs as cat

FICTIF = True
LEADS = cat.obtenir("m2.leads")


def _reponse(instants=("2026-10-20T10:00:00-04:00",), suivant=None, **extra):
    page = {"leads": [{"id": f"L{i}", "derniere_activite": h} for i, h in enumerate(instants)], "suivant": suivant}
    return {"ok": True, "resultat": {"accepte": True, "resultat": page | extra}}


def _lecture_avec_chemins():
    """Lecture de catalogue étendue de chemins d'instants, comme la production une fois la forme constatée."""
    return cat.Lecture(
        "m2.leads",
        "m02-revenue-crm",
        "m2_lister_leads",
        LEADS.libres,
        reference="horodatage",
        pagination=cat.Pagination("decalage", "resultat.resultat.suivant", "resultat.resultat.total"),
        instants_metier=("resultat.resultat.leads[*].derniere_activite",),
        revisions=("resultat.resultat.revision",),
    )


def _capture(
    pages, *, index=0, hash_precedent="", recu_a="2026-10-21T12:00:00Z", reference="2026-10-21T12:00:00Z", **kw
):
    lecture = kw.pop("lecture", _lecture_avec_chemins())
    return cs.construire(
        lecture,
        {"horodatage": reference},
        pages,
        recu_a=recu_a,
        reference=reference,
        index=index,
        hash_precedent=hash_precedent,
        **kw,
    )


def _chaine(*captures):
    return [*captures]


def test_les_quatre_temps_sont_distincts_et_les_instants_sans_fuseau_jamais_devines():
    capture = _capture([_reponse(("2026-10-20T10:00:00-04:00", "2026-10-19T08:00:00Z", "2026-10-18T08:00:00"))])
    temps = capture["instants_metier"]
    assert (temps["min"], temps["max"], temps["nombre"], temps["invalides"]) == (
        "2026-10-19T08:00:00Z",
        "2026-10-20T14:00:00Z",
        2,
        1,
    )
    assert capture["recu_a"] == "2026-10-21T12:00:00Z" and capture["reference"] == "2026-10-21T12:00:00Z"
    assert cs.valider_chaine([capture]) == (True, "")


def test_sans_chemin_declare_le_temps_metier_reste_non_declare_et_jamais_la_reception():
    capture = _capture([_reponse()], lecture=cat.obtenir("m6.disponibilite"))
    assert capture["instants_metier"] == {"declares": False, "nombre": 0, "invalides": 0, "min": None, "max": None}
    couverture = cs.evaluer_couverture(
        [capture], reference="2026-10-21T12:00:00Z", connaissance="2026-10-21T12:00:00Z", attendues=["m6.disponibilite"]
    )
    assert couverture["lectures"][0]["statut"] == "TEMPS_METIER_NON_DECLARE" and couverture["complete"] is False


def test_reponse_refusee_ou_en_erreur_est_conservee_comme_manque():
    refusee = {"ok": True, "resultat": {"accepte": False, "verdict": {"code": "REJ-IDENTITE-APPAREIL-INVALIDE"}}}
    erreur = {"ok": False, "erreur": "lecture_non_autorisee"}
    for page, verdict, code in (
        (refusee, "REFUSEE", "REJ-IDENTITE-APPAREIL-INVALIDE"),
        (erreur, "ERREUR", "lecture_non_autorisee"),
    ):
        capture = _capture([page])
        assert (capture["verdict"], capture["code"], capture["complete"]) == (verdict, code, False)
        assert capture["instants_metier"]["nombre"] == 0
        couverture = cs.evaluer_couverture(
            [capture], reference="2026-10-21T12:00:00Z", connaissance="2026-10-21T12:00:00Z", attendues=["m2.leads"]
        )
        assert couverture["lectures"][0]["statut"] == "REFUSEE"


def test_page_suivante_non_lue_rend_la_capture_partielle():
    capture = _capture([_reponse(suivant=20)])
    assert capture["complete"] is False and capture["raison_incomplete"] == "page suivante non lue"
    complete = _capture([_reponse(suivant=20), _reponse(("2026-10-20T11:00:00-04:00",), suivant=None)])
    assert complete["complete"] is True and complete["instants_metier"]["nombre"] == 2


def test_aucune_troncature_budget_et_pages_bornes():
    with pytest.raises(ValueError, match="REJ-CAPTURE-BORNE"):
        _capture([_reponse(("2026-10-20T10:00:00Z",) * 200)], max_octets=500)
    with pytest.raises(ValueError, match="REJ-CAPTURE-PAGES"):
        _capture([_reponse()] * (cs.MAX_PAGES + 1))
    with pytest.raises(ValueError, match="REJ-CAPTURE-JSON"):
        _capture([{"ok": True, "resultat": float("nan")}])


def test_chaine_et_monotonie_de_la_reception():
    a = _capture([_reponse()])
    b = _capture(
        [_reponse()],
        index=1,
        hash_precedent=a["hash_maillon"],
        recu_a="2026-10-21T13:00:00Z",
        dernier_recu_a=a["recu_a"],
    )
    assert cs.valider_chaine([a, b]) == (True, "")
    with pytest.raises(ValueError, match="REJ-CAPTURE-TEMPS"):
        _capture(
            [_reponse()],
            index=1,
            hash_precedent=a["hash_maillon"],
            recu_a="2026-10-21T11:00:00Z",
            dernier_recu_a=a["recu_a"],
        )
    altere = copy.deepcopy(b)
    altere["pages"][0]["resultat"]["resultat"]["leads"][0]["id"] = "FAUX"
    assert cs.valider_chaine([a, altere])[0] is False
    assert cs.valider_chaine([b])[0] is False  # un rang 1 sans rang 0
    regressif = copy.deepcopy(b)
    regressif["recu_a"] = "2026-10-21T11:00:00Z"
    regressif["hash_maillon"] = cs._hash_maillon(regressif)
    ok, raison = cs.valider_chaine([a, regressif])
    assert ok is False and "régressif" in raison


def test_arrivee_tardive_ne_reecrit_pas_ce_qui_etait_connu():
    a = _capture([_reponse(("2026-10-20T10:00:00Z",))])
    b = _capture(
        [_reponse(("2026-10-20T10:00:00Z", "2026-10-21T09:00:00Z"))],
        index=1,
        hash_precedent=a["hash_maillon"],
        recu_a="2026-10-22T08:00:00Z",
        reference="2026-10-22T08:00:00Z",
    )
    chaine = _chaine(a, b)
    avant = cs.evaluer_couverture(
        chaine, reference="2026-10-21T20:00:00Z", connaissance="2026-10-21T20:00:00Z", attendues=["m2.leads"]
    )
    apres = cs.evaluer_couverture(
        chaine, reference="2026-10-21T20:00:00Z", connaissance="2026-10-22T09:00:00Z", attendues=["m2.leads"]
    )
    assert (
        avant["lectures"][0]["dernier_index"] == 0
        and avant["lectures"][0]["instants_metier"]["max"] == "2026-10-20T10:00:00Z"
    )
    assert (
        apres["lectures"][0]["dernier_index"] == 1
        and apres["lectures"][0]["instants_metier"]["max"] == "2026-10-21T09:00:00Z"
    )
    assert [c["index"] for c in cs.connues_a(chaine, "2026-10-21T20:00:00Z")] == [0]
    assert (
        cs.evaluer_couverture(
            chaine, reference="2026-10-21T20:00:00Z", connaissance="2026-10-20T00:00:00Z", attendues=["m2.leads"]
        )["lectures"][0]["statut"]
        == "ABSENTE"
    )


def test_observation_future_et_age_signe_sans_sla():
    futur = _capture([_reponse(("2026-11-01T10:00:00Z",))])
    couverture = cs.evaluer_couverture(
        [futur], reference="2026-10-21T12:00:00Z", connaissance="2026-10-21T12:00:00Z", attendues=["m2.leads"]
    )
    assert couverture["lectures"][0]["statut"] == "FUTURE" and couverture["lectures"][0]["age_s"] < 0
    ancienne = _capture([_reponse(("2026-01-01T10:00:00Z",))])
    sans_attente = cs.evaluer_couverture(
        [ancienne], reference="2026-10-21T12:00:00Z", connaissance="2026-10-21T12:00:00Z", attendues=["m2.leads"]
    )["lectures"][0]
    assert (
        sans_attente["statut"] == "PRESENTE" and sans_attente["fraicheur"] == "NON_EVALUEE"
    )  # un âge n'est pas un SLA
    avec = cs.evaluer_couverture(
        [ancienne],
        reference="2026-10-21T12:00:00Z",
        connaissance="2026-10-21T12:00:00Z",
        attendues=["m2.leads"],
        fraicheur_attendue_s={"m2.leads": 86400},
    )["lectures"][0]
    assert avec["fraicheur"] == "HORS_FENETRE"


def test_contradiction_conservee_meme_revision_meme_instant_reponse_differente():
    a = _capture([_reponse(("2026-10-20T10:00:00Z",), revision="r1")])
    b = _capture(
        [_reponse(("2026-10-20T10:00:00Z",), revision="r1", autre="x")],
        index=1,
        hash_precedent=a["hash_maillon"],
        recu_a="2026-10-21T13:00:00Z",
    )
    conflits = cs.contradictions([a, b])
    assert len(conflits) == 1 and (conflits[0]["index_a"], conflits[0]["index_b"]) == (0, 1)
    assert conflits[0]["hash_a"] == a["hash_maillon"] and conflits[0]["hash_b"] == b["hash_maillon"]
    couverture = cs.evaluer_couverture(
        [a, b], reference="2026-10-21T20:00:00Z", connaissance="2026-10-21T20:00:00Z", attendues=["m2.leads"]
    )
    assert couverture["lectures"][0]["statut"] == "CONTRADICTOIRE" and couverture["complete"] is False


def test_correction_de_source_nouvelle_revision_n_est_pas_une_contradiction():
    a = _capture([_reponse(("2026-10-20T10:00:00Z",), revision="r1")])
    b = _capture(
        [_reponse(("2026-10-20T10:00:00Z",), revision="r2", autre="x")],
        index=1,
        hash_precedent=a["hash_maillon"],
        recu_a="2026-10-21T13:00:00Z",
    )
    assert cs.contradictions([a, b]) == []


def test_lecture_inconnue_et_arguments_non_autorises_refuses():
    with pytest.raises(ValueError, match="REJ-CAPTURE-LECTURE"):
        cat.obtenir("m2.tout_le_registre")
    with pytest.raises(ValueError, match="REJ-CAPTURE-ARGUMENTS"):
        cat.arguments_admis(LEADS, {"horodatage": "2026-10-21T12:00:00Z", "role": "admin"})
    assert cat.arguments_admis(LEADS, {"horodatage": "2026-10-21T12:00:00Z"}) == {"horodatage": "2026-10-21T12:00:00Z"}


def test_catalogue_n_expose_aucun_calculateur_a_donnees_fournies():
    interdits = {
        "mouvements_historique",
        "taux_utilises",
        "besoins_estimes",
        "lignes_declarees",
        "registre_historique",
        "previsions_saisies",
    }
    for lecture in cat.LECTURES:
        assert not lecture.libres & interdits, lecture.id
    assert len({lecture.id for lecture in cat.LECTURES}) == len(cat.LECTURES)


def test_instants_de_reception_ou_reference_invalides_refuses():
    with pytest.raises(ValueError, match="REJ-CAPTURE-TEMPS"):
        _capture([_reponse()], recu_a="2026-10-21T12:00:00")
    with pytest.raises(ValueError, match="REJ-CAPTURE-TEMPS"):
        _capture([_reponse()], reference="demain")


def test_troncature_declaree_par_le_producteur_rend_la_capture_partielle():
    cedule = cat.obtenir("m4.cedule_semaine")
    tronquee = {"ok": True, "resultat": {"accepte": True, "resultat": {"interventions": [], "tronque": True}}}
    entiere = {"ok": True, "resultat": {"accepte": True, "resultat": {"interventions": [], "tronque": False}}}
    args = {"debut_semaine": "2026-11-02"}
    a = cs.construire(cedule, args, [tronquee], recu_a=REF_RECU, reference=None, index=0, hash_precedent="")
    b = cs.construire(cedule, args, [entiere], recu_a=REF_RECU, reference=None, index=0, hash_precedent="")
    assert a["complete"] is False and "tronquée" in a["raison_incomplete"] and b["complete"] is True
    retards = cat.obtenir("m4.retards_incidents")
    avec_reste = {
        "ok": True,
        "resultat": {
            "accepte": True,
            "resultat": {"reports": {"liste": [], "reste": 3}, "incidents": {"liste": [], "reste": 0}},
        },
    }
    sans_reste = {
        "ok": True,
        "resultat": {
            "accepte": True,
            "resultat": {"reports": {"liste": [], "reste": 0}, "incidents": {"liste": [], "reste": 0}},
        },
    }
    for reponse, attendu in ((avec_reste, False), (sans_reste, True)):
        capture = cs.construire(retards, {}, [reponse], recu_a=REF_RECU, reference=None, index=0, hash_precedent="")
        assert capture["complete"] is attendu


REF_RECU = "2026-10-21T12:00:00Z"
