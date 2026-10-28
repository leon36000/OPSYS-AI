"""M9.2 — graphe d'impacts : arêtes justifiées, règles inconnues, propagation sans quantité (fictif)."""

import pytest
from m9_strategic_intelligence import capture_strategique as cs
from m9_strategic_intelligence import catalogue_producteurs as cat
from m9_strategic_intelligence import graphe_impacts as gi

FICTIF = True
T0 = "2026-10-21T12:00:00Z"


def _lecture(lecture_id):
    return cat.obtenir(lecture_id)


def _capture(lecture_id, reponse, *, index=0, hash_precedent="", recu_a=T0, arguments=None, suite=None):
    pages = suite if suite is not None else [reponse]
    return cs.construire(
        _lecture(lecture_id),
        arguments or {},
        pages,
        recu_a=recu_a,
        reference=None,
        index=index,
        hash_precedent=hash_precedent,
    )


def _ok(**contenu):
    return {"ok": True, "resultat": {"accepte": True, "resultat": contenu}}


# Règles fictives de tests : matériau → chantier (M6→M4), chantier → devis (M4→M3), devis → lead (M3→M2).
R1 = gi.Regle(
    "materiau_chantier",
    "utilise_par",
    "m6.disponibilite",
    "resultat.resultat.liens[*]",
    "materiau",
    "materiau_id",
    "chantier",
    "wct_id",
)
R2 = gi.Regle(
    "chantier_devis",
    "facture_par",
    "m4.interventions",
    "resultat.resultat.interventions[*]",
    "chantier",
    "wct_id",
    "devis",
    "devis_id",
)
R3 = gi.Regle(
    "devis_lead",
    "vendu_a",
    "m3.ecarts",
    "resultat.resultat.devis[*]",
    "devis",
    "devis_id",
    "lead",
    "lead_id",
    sens="vers->de",
)


def _chaine():
    a = _capture(
        "m6.disponibilite",
        _ok(
            liens=[
                {"materiau_id": "BARDEAU-X", "wct_id": "W1"},
                {"materiau_id": "BARDEAU-X", "wct_id": "W2"},
                {"materiau_id": "", "wct_id": "W9"},
                "pas une ligne",
            ]
        ),
    )
    b = _capture(
        "m4.interventions",
        _ok(interventions=[{"wct_id": "W1", "devis_id": "D1"}, {"wct_id": "W2", "devis_id": "D2"}]),
        index=1,
        hash_precedent=a["hash_maillon"],
    )
    c = _capture(
        "m3.ecarts", _ok(devis=[{"devis_id": "D1", "lead_id": "L1"}]), index=2, hash_precedent=b["hash_maillon"]
    )
    return [a, b, c]


def test_aretes_justifiees_par_capture_regle_et_ligne():
    graphe = gi.construire(_chaine(), [R1, R2, R3], connaissance=T0)
    assert {a["relation"] for a in graphe["aretes"]} == {"utilise_par", "facture_par", "vendu_a"}
    arete = next(a for a in graphe["aretes"] if a["regle"] == "materiau_chantier" and a["vers"] == "chantier:W1")
    assert arete["preuve"]["capture_index"] == 0 and arete["preuve"]["ligne"] == 0
    assert arete["preuve"]["capture_hash"] == _chaine()[0]["hash_maillon"]
    # La ligne sans identifiant valide et la ligne qui n'est pas un objet sont écartées, comptées, jamais devinées.
    actif = next(r for r in graphe["regles_actives"] if r["regle"] == "materiau_chantier")
    assert actif["aretes"] == 2 and actif["lignes_ecartees"] == 2
    assert graphe["regles_inconnues"] == []
    assert gi.construire(_chaine(), [R1, R2, R3], connaissance=T0)["graphe_id"] == graphe["graphe_id"]  # reproductible


def test_propagation_rupture_materiau_vers_chantiers_devis_et_lead_sans_quantite():
    graphe = gi.construire(_chaine(), [R1, R2, R3], connaissance=T0)
    resultat = gi.propager(graphe, "materiau", "BARDEAU-X", profondeur_max=4)
    atteints = {(i["objet"]["kind"], i["objet"]["id"]): i["distance"] for i in resultat["impacts"]}
    assert atteints == {("chantier", "W1"): 1, ("chantier", "W2"): 1, ("devis", "D1"): 2, ("devis", "D2"): 2}
    # devis → lead se propage « vers->de » : un changement du lead touche le devis, pas l'inverse.
    assert ("lead", "L1") not in atteints
    assert all(set(i) == {"objet", "distance", "chemin"} for i in resultat["impacts"])  # aucune quantité, aucun montant
    assert resultat["complet"] is True
    lead = gi.propager(graphe, "lead", "L1")
    assert {(i["objet"]["kind"], i["objet"]["id"]) for i in lead["impacts"]} == {("devis", "D1")}


def test_profondeur_et_filtre_de_relations_bornent_la_propagation():
    graphe = gi.construire(_chaine(), [R1, R2, R3], connaissance=T0)
    proche = gi.propager(graphe, "materiau", "BARDEAU-X", profondeur_max=1)
    assert {i["objet"]["kind"] for i in proche["impacts"]} == {"chantier"}
    filtre = gi.propager(graphe, "materiau", "BARDEAU-X", relations=["utilise_par"])
    assert {i["objet"]["kind"] for i in filtre["impacts"]} == {"chantier"}
    with pytest.raises(ValueError, match="REJ-GRAPHE-PROFONDEUR"):
        gi.propager(graphe, "materiau", "BARDEAU-X", profondeur_max=99)


def test_objet_absent_du_graphe_est_inconnu_jamais_aucun_impact():
    graphe = gi.construire(_chaine(), [R1, R2, R3], connaissance=T0)
    with pytest.raises(ValueError, match="REJ-GRAPHE-NOEUD-INCONNU"):
        gi.propager(graphe, "materiau", "INCONNU")


def test_lecture_absente_refusee_ou_partielle_rend_la_regle_inconnue_sans_arete():
    chaine = _chaine()
    sans_m4 = [chaine[0], chaine[2]]
    graphe = gi.construire(sans_m4, [R1, R2, R3], connaissance=T0)
    assert [r["raison"] for r in graphe["regles_inconnues"] if r["regle"] == "chantier_devis"] == ["ABSENTE"]
    resultat = gi.propager(graphe, "materiau", "BARDEAU-X")
    assert {i["objet"]["kind"] for i in resultat["impacts"]} == {"chantier"}
    assert resultat["complet"] is False
    assert [r["regle"] for r in resultat["regles_inconnues_pertinentes"]] == ["chantier_devis"]

    refusee = _capture(
        "m4.interventions",
        {"ok": False, "erreur": "lecture_non_autorisee"},
        index=1,
        hash_precedent=chaine[0]["hash_maillon"],
    )
    graphe = gi.construire([chaine[0], refusee], [R1, R2], connaissance=T0)
    assert [r["raison"] for r in graphe["regles_inconnues"]] == ["REFUSEE"]

    partielle = _capture("m2.leads", _ok(leads=[], suivant=20), arguments={"decalage": 0})
    regle_leads = gi.Regle(
        "leads", "x", "m2.leads", "resultat.resultat.leads[*]", "lead", "lead_id", "client", "client_id"
    )
    graphe = gi.construire([partielle], [regle_leads], connaissance=T0)
    assert graphe["regles_inconnues"][0]["raison"] == "PARTIELLE"


def test_derniere_capture_decide_une_capture_ancienne_ne_remplace_jamais_un_refus():
    chaine = _chaine()
    refus = _capture(
        "m6.disponibilite",
        {"ok": False, "erreur": "x"},
        index=3,
        hash_precedent=chaine[2]["hash_maillon"],
        recu_a="2026-10-22T12:00:00Z",
    )
    graphe = gi.construire([*chaine, refus], [R1], connaissance="2026-10-23T00:00:00Z")
    assert graphe["aretes"] == [] and graphe["regles_inconnues"][0]["raison"] == "REFUSEE"
    # Connu avant le refus : les arêtes existaient.
    avant = gi.construire([*chaine, refus], [R1], connaissance="2026-10-21T13:00:00Z")
    assert len(avant["aretes"]) == 2 and avant["regles_inconnues"] == []


def test_contradiction_rend_la_regle_inconnue():
    base = _ok(liens=[{"materiau_id": "A", "wct_id": "W1"}], revision="r1")
    a = _capture("m6.disponibilite", base)
    autre = _ok(liens=[{"materiau_id": "A", "wct_id": "W2"}], revision="r1")
    b = _capture("m6.disponibilite", autre, index=1, hash_precedent=a["hash_maillon"])
    regle = gi.Regle(
        "m", "r", "m6.disponibilite", "resultat.resultat.liens[*]", "materiau", "materiau_id", "chantier", "wct_id"
    )
    # Sans révision ni instant déclarés dans le catalogue réel, la comparaison est impossible : pas de contradiction
    # affirmée.
    assert gi.construire([a, b], [regle], connaissance=T0)["aretes"]
    lecture = cat.Lecture(
        "m6.disponibilite",
        "m06-material-control",
        "m6_lire_disponibilite",
        frozenset(),
        revisions=("resultat.resultat.revision",),
    )
    ca = cs.construire(lecture, {}, [base], recu_a=T0, reference=None, index=0, hash_precedent="")
    cb = cs.construire(lecture, {}, [autre], recu_a=T0, reference=None, index=1, hash_precedent=ca["hash_maillon"])
    graphe = gi.construire([ca, cb], [regle], connaissance=T0)
    assert graphe["aretes"] == [] and graphe["regles_inconnues"][0]["raison"] == "CONTRADICTOIRE"


def test_arguments_distincts_sont_evalues_separement():
    a = _capture(
        "m6.disponibilite", _ok(liens=[{"materiau_id": "A", "wct_id": "W1"}]), arguments={"materiau_ids": ["A"]}
    )
    b = _capture(
        "m6.disponibilite",
        {"ok": False, "erreur": "x"},
        index=1,
        hash_precedent=a["hash_maillon"],
        arguments={"materiau_ids": ["B"]},
    )
    graphe = gi.construire([a, b], [R1], connaissance=T0)
    assert len(graphe["aretes"]) == 1 and graphe["regles_inconnues"][0]["raison"] == "REFUSEE"


def test_regle_invalide_refusee():
    with pytest.raises(ValueError, match="sens inconnu"):
        gi.Regle("x", "r", "m2.leads", "a", "k", "c", "k2", "c2", sens="partout")
    with pytest.raises(ValueError, match="règle incomplète"):
        gi.Regle("x", "", "m2.leads", "a", "k", "c", "k2", "c2")
