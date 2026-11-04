"""Attribution campagne → lead observable, non causale (données fictives)."""

import hashlib
import json

import pytest
from m9_strategic_intelligence import capture_strategique as cs
from m9_strategic_intelligence import catalogue_producteurs as cat
from m9_strategic_intelligence import graphe_impacts as gi
from m9_strategic_intelligence import relations_catalogue as rc

FICTIF = True
CONNAISSANCE = "2026-10-21T12:00:00Z"


def _id_campagne(source, campagne):
    tuple_json = json.dumps((source, campagne), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "sha256-" + hashlib.sha256(tuple_json).hexdigest()


def _capture(reponse):
    return cs.construire(
        cat.obtenir("m7.performance_campagnes"),
        {"debut": "2026-10-01", "fin": "2026-10-31"},
        [reponse],
        recu_a=CONNAISSANCE,
        reference=None,
        index=0,
        hash_precedent="",
    )


def _capture_pages(pages):
    return cs.construire(
        cat.obtenir("m7.performance_campagnes"),
        {"debut": "2026-10-01", "fin": "2026-10-31"},
        pages,
        recu_a=CONNAISSANCE,
        reference=None,
        index=0,
        hash_precedent="",
    )


def test_capture_m7_relations_d_attribution_sont_composites_filtrees_et_incompletes():
    regle = next(r for r in rc.REGLES if r.id == "m7_campagne_lead_utm")
    capture = _capture(
        {
            "ok": True,
            "resultat": {
                "couverture": "PARTIELLE",
                "campagnes": [
                    {
                        "source": "google",
                        "campagne": "automne|promo",
                        "source_refs": [
                            {"type": "m2.client_associe", "reference": "lead-fictif-a"},
                            {"type": "m3.devis_accepte", "reference": "devis-fictif-exclu"},
                        ],
                    },
                    {
                        "source": "facebook",
                        "campagne": "automne|promo",
                        "source_refs": [
                            {"type": "m2.client_associe", "reference": "lead-fictif-b"},
                        ],
                    },
                ],
            },
        }
    )

    graphe = gi.construire([capture], [regle], connaissance=CONNAISSANCE)
    campagnes = [n["id"] for n in graphe["noeuds"] if n["kind"] == "campagne"]
    assert len(campagnes) == 2 and campagnes[0] != campagnes[1]
    assert all("automne|promo" not in ident for ident in campagnes)
    assert {a["relation"] for a in graphe["aretes"]} == {"attribue_selon_utm"}
    ident_google = _id_campagne("google", "automne|promo")
    ident_facebook = _id_campagne("facebook", "automne|promo")
    assert {(a["de"], a["vers"]) for a in graphe["aretes"]} == {
        (f"campagne:{ident_google}", "lead:lead-fictif-a"),
        (f"campagne:{ident_facebook}", "lead:lead-fictif-b"),
    }
    assert all(a["preuve"]["capture_hash"] == capture["hash_maillon"] for a in graphe["aretes"])
    assert all(a["preuve"]["sous_chemin"] == "source_refs[*]" for a in graphe["aretes"])
    assert {r["raison"] for r in graphe["regles_inconnues"] if r["regle"] == regle.id} == {"COUVERTURE_PARTIELLE"}
    assert gi.propager(graphe, "campagne", campagnes[0])["complet"] is False
    assert gi.construire([capture], [regle], connaissance=CONNAISSANCE)["graphe_id"] == graphe["graphe_id"]


def test_cle_composite_ne_confond_pas_separateurs_ni_ne_tronque_les_valeurs():
    regle = next(r for r in rc.REGLES if r.id == "m7_campagne_lead_utm")
    capture = _capture(
        {
            "ok": True,
            "resultat": {
                "couverture": "PARTIELLE",
                "campagnes": [
                    {
                        "source": "a|b",
                        "campagne": "c",
                        "source_refs": [{"type": "m2.client_associe", "reference": "lead-1"}],
                    },
                    {
                        "source": "a",
                        "campagne": "b|c",
                        "source_refs": [{"type": "m2.client_associe", "reference": "lead-2"}],
                    },
                ],
            },
        }
    )
    graphe = gi.construire([capture], [regle], connaissance=CONNAISSANCE)
    identifiants = {n["id"] for n in graphe["noeuds"] if n["kind"] == "campagne"}
    assert len(identifiants) == 2
    assert all(len(identifiant) <= 128 for identifiant in identifiants)
    assert {(a["de"].split(":", 1)[1], a["vers"]) for a in graphe["aretes"]} == {
        (_id_campagne("a|b", "c"), "lead:lead-1"),
        (_id_campagne("a", "b|c"), "lead:lead-2"),
    }


def test_unicode_utm_longue_et_reference_invalide_ne_sont_pas_silencieuses():
    regle = next(r for r in rc.REGLES if r.id == "m7_campagne_lead_utm")
    source, campagne = "é" * 600, "été|automne" * 40
    capture = _capture(
        {
            "ok": True,
            "resultat": {
                "couverture": "PARTIELLE",
                "campagnes": [
                    {
                        "source": source,
                        "campagne": campagne,
                        "source_refs": [
                            {"type": "m2.client_associe", "reference": ["mal-formé"]},
                            {"type": "m2.client_associe", "reference": "lead-long-fictif"},
                        ],
                    }
                ],
            },
        }
    )
    graphe = gi.construire([capture], [regle], connaissance=CONNAISSANCE)
    assert len(graphe["aretes"]) == 1
    assert graphe["aretes"][0]["vers"] == "lead:lead-long-fictif"
    inconnues = {(r["raison"], r["regle"]) for r in graphe["regles_inconnues"]}
    assert ("COUVERTURE_PARTIELLE", regle.id) in inconnues
    assert ("IDENTIFIANT_LIEN_INVALIDE", regle.id) in inconnues
    assert all(source not in n["id"] and campagne not in n["id"] for n in graphe["noeuds"])


def test_collision_d_empreinte_de_tuples_distincts_est_refusee(monkeypatch):
    regle = next(r for r in rc.REGLES if r.id == "m7_campagne_lead_utm")
    capture = _capture(
        {
            "ok": True,
            "resultat": {
                "couverture": "PARTIELLE",
                "campagnes": [
                    {
                        "source": "google",
                        "campagne": "a",
                        "source_refs": [{"type": "m2.client_associe", "reference": "lead-a"}],
                    },
                    {
                        "source": "facebook",
                        "campagne": "a",
                        "source_refs": [{"type": "m2.client_associe", "reference": "lead-b"}],
                    },
                ],
            },
        }
    )

    class EmpreinteCollision:
        def hexdigest(self):
            return "0" * 64

    monkeypatch.setattr(gi.hashlib, "sha256", lambda _valeur: EmpreinteCollision())
    with pytest.raises(ValueError, match="REJ-GRAPHE-CLE_COMPOSITE_COLLISION"):
        gi.construire([capture], [regle], connaissance=CONNAISSANCE)


def test_surrogate_invalide_est_refuse_sans_exception_fuite():
    assert gi._identifiant_champ(("^source", "^campagne"), {}, {"source": "\ud800", "campagne": "x"}) == (
        None,
        None,
    )


def test_couverture_doit_etre_complete_sur_chaque_page():
    regle = next(r for r in rc.REGLES if r.id == "m7_campagne_lead_utm")
    pages = [
        {"ok": True, "resultat": {"couverture": "COMPLETE", "campagnes": []}},
        {
            "ok": True,
            "resultat": {
                "campagnes": [
                    {
                        "source": "google",
                        "campagne": "campagne-fictive",
                        "source_refs": [{"type": "m2.client_associe", "reference": "lead-page-2"}],
                    }
                ]
            },
        },
    ]
    capture = _capture_pages(pages)
    graphe = gi.construire([capture], [regle], connaissance=CONNAISSANCE)

    assert len(graphe["aretes"]) == 1
    assert any(
        inconnu["regle"] == regle.id and inconnu["raison"] == "COUVERTURE_NON_DECLAREE"
        for inconnu in graphe["regles_inconnues"]
    )
    assert gi.propager(graphe, "campagne", graphe["aretes"][0]["de"].split(":", 1)[1])["complet"] is False


@pytest.mark.parametrize(
    "ligne",
    [
        None,
        {"source": "google", "campagne": "campagne-fictive"},
        {"source": "google", "campagne": "campagne-fictive", "source_refs": None},
        {
            "source": "google",
            "campagne": "campagne-fictive",
            "source_refs": [
                {"reference": "lead-malforme"},
            ],
        },
    ],
)
def test_ligne_ou_source_refs_malformes_rendent_la_regle_inconnue(ligne):
    regle = next(r for r in rc.REGLES if r.id == "m7_campagne_lead_utm")
    capture = _capture(
        {
            "ok": True,
            "resultat": {
                "couverture": "COMPLETE",
                "campagnes": [ligne],
            },
        }
    )
    graphe = gi.construire([capture], [regle], connaissance=CONNAISSANCE)

    assert graphe["aretes"] == []
    assert any(
        inconnu["regle"] == regle.id and inconnu["raison"] == "IDENTIFIANT_LIEN_INVALIDE"
        for inconnu in graphe["regles_inconnues"]
    )


def test_source_refs_vide_est_liste_valide_sans_lien_invalide():
    regle = next(r for r in rc.REGLES if r.id == "m7_campagne_lead_utm")
    capture = _capture(
        {
            "ok": True,
            "resultat": {
                "couverture": "COMPLETE",
                "campagnes": [
                    {"source": "google", "campagne": "sans-lead", "source_refs": []},
                ],
            },
        }
    )
    graphe = gi.construire([capture], [regle], connaissance=CONNAISSANCE)

    assert graphe["aretes"] == []
    assert not any(
        inconnu["regle"] == regle.id and inconnu["raison"] == "IDENTIFIANT_LIEN_INVALIDE"
        for inconnu in graphe["regles_inconnues"]
    )


@pytest.mark.parametrize(
    ("resultat", "raison"),
    [
        ({"couverture": "INCONNUE", "campagnes": []}, "COUVERTURE_INCONNUE"),
        ({"campagnes": []}, "COUVERTURE_NON_DECLAREE"),
    ],
)
def test_couverture_inconnue_ou_absente_est_signalee(resultat, raison):
    regle = next(r for r in rc.REGLES if r.id == "m7_campagne_lead_utm")
    capture = _capture({"ok": True, "resultat": resultat})
    graphe = gi.construire([capture], [regle], connaissance=CONNAISSANCE)

    assert any(inconnu["regle"] == regle.id and inconnu["raison"] == raison for inconnu in graphe["regles_inconnues"])


@pytest.mark.parametrize("campagnes", [None, "pas-une-liste", ...])
def test_liste_campagnes_absente_ou_mal_typee_ne_vaut_pas_liste_vide(campagnes):
    regle = next(r for r in rc.REGLES if r.id == "m7_campagne_lead_utm")
    resultat = {"couverture": "COMPLETE"}
    if campagnes is not ...:
        resultat["campagnes"] = campagnes
    capture = _capture({"ok": True, "resultat": resultat})
    graphe = gi.construire([capture], [regle], connaissance=CONNAISSANCE)

    assert not graphe["aretes"]
    assert any(
        inconnu["regle"] == regle.id and inconnu["raison"] == "IDENTIFIANT_LIEN_INVALIDE"
        for inconnu in graphe["regles_inconnues"]
    )


def test_liste_campagnes_vide_est_valide():
    regle = next(r for r in rc.REGLES if r.id == "m7_campagne_lead_utm")
    capture = _capture({"ok": True, "resultat": {"couverture": "COMPLETE", "campagnes": []}})
    graphe = gi.construire([capture], [regle], connaissance=CONNAISSANCE)

    assert not graphe["aretes"]
    assert not any(inconnu["regle"] == regle.id for inconnu in graphe["regles_inconnues"])


def test_cle_campagnes_omise_est_inconnue():
    regle = next(r for r in rc.REGLES if r.id == "m7_campagne_lead_utm")
    capture = _capture({"ok": True, "resultat": {"couverture": "COMPLETE"}})
    graphe = gi.construire([capture], [regle], connaissance=CONNAISSANCE)

    assert not graphe["aretes"]
    assert any(
        inconnu["regle"] == regle.id and inconnu["raison"] == "IDENTIFIANT_LIEN_INVALIDE"
        for inconnu in graphe["regles_inconnues"]
    )


def test_trois_types_source_refs_emis_par_m7_sont_reconnus_et_seul_m2_cree_un_lien():
    regle = next(r for r in rc.REGLES if r.id == "m7_campagne_lead_utm")
    capture = _capture(
        {
            "ok": True,
            "resultat": {
                "couverture": "COMPLETE",
                "campagnes": [
                    {
                        "source": "google",
                        "campagne": "multi-sources",
                        "source_refs": [
                            {"type": "m2.client_associe", "reference": "lead-fictif"},
                            {"type": "m3.devis_accepte", "reference": "devis-fictif"},
                            {"type": "m5.rentabilite_chantier", "reference": "event-fictif"},
                        ],
                    }
                ],
            },
        }
    )
    graphe = gi.construire([capture], [regle], connaissance=CONNAISSANCE)

    assert [(a["relation"], a["vers"]) for a in graphe["aretes"]] == [
        ("attribue_selon_utm", "lead:lead-fictif"),
    ]
    assert not any(
        inconnu["regle"] == regle.id and inconnu["raison"] == "IDENTIFIANT_LIEN_INVALIDE"
        for inconnu in graphe["regles_inconnues"]
    )


def test_type_source_ref_inconnu_marque_la_couverture_inconnue_sans_lien():
    regle = next(r for r in rc.REGLES if r.id == "m7_campagne_lead_utm")
    capture = _capture(
        {
            "ok": True,
            "resultat": {
                "couverture": "COMPLETE",
                "campagnes": [
                    {
                        "source": "google",
                        "campagne": "type-futur",
                        "source_refs": [
                            {"type": "m2.client_associe", "reference": "lead-fictif"},
                            {"type": "m99.type_futur", "reference": "opaque-fictif"},
                        ],
                    }
                ],
            },
        }
    )
    graphe = gi.construire([capture], [regle], connaissance=CONNAISSANCE)

    assert [a["vers"] for a in graphe["aretes"]] == ["lead:lead-fictif"]
    assert any(
        inconnu["regle"] == regle.id and inconnu["raison"] == "TYPE_LIEN_INCONNU"
        for inconnu in graphe["regles_inconnues"]
    )


def test_couverture_absente_sur_premiere_page_est_inconnue():
    regle = next(r for r in rc.REGLES if r.id == "m7_campagne_lead_utm")
    capture = _capture_pages(
        [
            {"ok": True, "resultat": {"campagnes": []}},
            {
                "ok": True,
                "resultat": {
                    "couverture": "COMPLETE",
                    "campagnes": [
                        {
                            "source": "google",
                            "campagne": "fictive-page-2",
                            "source_refs": [{"type": "m2.client_associe", "reference": "lead-page-2"}],
                        }
                    ],
                },
            },
        ]
    )
    graphe = gi.construire([capture], [regle], connaissance=CONNAISSANCE)

    assert len(graphe["aretes"]) == 1
    assert gi.propager(graphe, "campagne", graphe["aretes"][0]["de"].split(":", 1)[1])["complet"] is False
    assert any(
        inconnu["regle"] == regle.id and inconnu["raison"] == "COUVERTURE_NON_DECLAREE"
        for inconnu in graphe["regles_inconnues"]
    )


def test_couverture_absente_sur_derniere_page_est_inconnue():
    regle = next(r for r in rc.REGLES if r.id == "m7_campagne_lead_utm")
    capture = _capture_pages(
        [
            {"ok": True, "resultat": {"couverture": "COMPLETE", "campagnes": []}},
            {"ok": True, "resultat": {"campagnes": []}},
        ]
    )
    graphe = gi.construire([capture], [regle], connaissance=CONNAISSANCE)

    assert any(
        inconnu["regle"] == regle.id and inconnu["raison"] == "COUVERTURE_NON_DECLAREE"
        for inconnu in graphe["regles_inconnues"]
    )


@pytest.mark.parametrize("refs", [None, "pas-une-liste"])
def test_source_refs_non_liste_est_inconnu(refs):
    regle = next(r for r in rc.REGLES if r.id == "m7_campagne_lead_utm")
    capture = _capture(
        {
            "ok": True,
            "resultat": {
                "couverture": "COMPLETE",
                "campagnes": [
                    {"source": "google", "campagne": "source-malformee", "source_refs": refs},
                ],
            },
        }
    )
    graphe = gi.construire([capture], [regle], connaissance=CONNAISSANCE)

    assert any(
        inconnu["regle"] == regle.id and inconnu["raison"] == "IDENTIFIANT_LIEN_INVALIDE"
        for inconnu in graphe["regles_inconnues"]
    )


def test_capture_sans_page_rejetee_et_chaine_invalide():
    response = {"ok": True, "resultat": {
        "couverture": "COMPLETE",
        "campagnes": [{"source": "google", "campagne": "fictif",
                       "source_refs": [{"type": "m2.client_associe", "reference": "lead-fictif"}]}],
    }}
    capture = _capture(response)
    capture["pages"] = []
    capture["reponse_sha256"] = cs.empreinte([])
    capture["hash_maillon"] = cs._hash_maillon(capture)
    with pytest.raises(ValueError, match="REJ-CAPTURE-PAGES"):
        cs.valider_capture(capture)
    assert cs.valider_chaine([capture])[0] is False
    with pytest.raises(ValueError, match="REJ-CAPTURE-PAGES"):
        cs.construire(
            cat.obtenir("m7.performance_campagnes"),
            {"debut": "2026-10-01", "fin": "2026-10-31"}, [],
            recu_a=CONNAISSANCE, reference=None, index=0, hash_precedent=cs.HASH_INITIAL,
        )


@pytest.mark.parametrize("pages", [[], ["p"] * (cs.MAX_PAGES + 1)])
def test_valider_capture_refuse_nombre_pages_hors_bornes(pages):
    capture = _capture({"ok": True, "resultat": {"couverture": "COMPLETE"}})
    capture["pages"] = pages
    capture["reponse_sha256"] = cs.empreinte(pages)
    capture["hash_maillon"] = cs._hash_maillon(capture)
    with pytest.raises(ValueError, match="REJ-CAPTURE-PAGES"):
        cs.valider_capture(capture)


def test_constructeur_compte_octets_utf8_et_preserve_budget_personnalise():
    response = {"ok": True, "resultat": {"texte": "é" * 500_000}}
    args = {"debut": "2026-10-01", "fin": "2026-10-31"}
    with pytest.raises(ValueError, match="REJ-CAPTURE-BORNE"):
        cs.construire(
            cat.obtenir("m7.performance_campagnes"), args, [response],
            recu_a=CONNAISSANCE, reference=None, index=0, hash_precedent=cs.HASH_INITIAL,
        )
    capture = cs.construire(
        cat.obtenir("m7.performance_campagnes"), args, [response],
        recu_a=CONNAISSANCE, reference=None, index=0, hash_precedent=cs.HASH_INITIAL,
        max_octets=2_000_000,
    )
    assert len(cs.canonique(capture["pages"]).encode("utf-8")) > cs.MAX_OCTETS_DEFAUT
    cs.valider_capture(capture)
    assert cs.valider_chaine([capture]) == (True, "")
