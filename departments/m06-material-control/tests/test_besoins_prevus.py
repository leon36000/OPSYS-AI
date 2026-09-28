"""besoins_prevus.py — PLAN T1.2-b (M6), « M6 garde le prévu ». Module pur : aucune base,
`maillons_existants` est une simple liste Python en mémoire ici."""

from __future__ import annotations

from m6_material_control import besoins_prevus


def _ligne(materiau_id="MAT-1", quantite_estimee=10.0, unite="boite"):
    return {"materiau_id": materiau_id, "quantite_estimee": quantite_estimee, "unite": unite}


def test_enregistrer_nominal_construit_le_maillon_sans_ecrire():
    maillons: list[dict] = []
    maillon, code = besoins_prevus.enregistrer("C1", "DEVIS-1", [_ligne()], maillons)
    assert code is None
    assert maillon == {"chantier_id": "C1", "devis_id": "DEVIS-1", "lignes": [_ligne()]}
    assert maillons == [], "enregistrer() ne mute jamais maillons_existants"


def test_enregistrer_chantier_id_manquant_refuse_nomme():
    maillon, code = besoins_prevus.enregistrer("", "DEVIS-1", [_ligne()], [])
    assert maillon is None
    assert code == "REJ-BESOINS-PREVUS-CHANTIER-MANQUANT"


def test_enregistrer_devis_id_manquant_refuse_nomme():
    maillon, code = besoins_prevus.enregistrer("C1", None, [_ligne()], [])
    assert maillon is None
    assert code == "REJ-BESOINS-PREVUS-DEVIS-MANQUANT"


def test_enregistrer_lignes_vides_refuse_nomme():
    maillon, code = besoins_prevus.enregistrer("C1", "DEVIS-1", [], [])
    assert maillon is None
    assert code == "REJ-BESOINS-PREVUS-LIGNES-VIDES"


def test_enregistrer_ligne_invalide_reutilise_le_verdict_de_validation():
    maillon, code = besoins_prevus.enregistrer(
        "C1", "DEVIS-1", [{"materiau_id": "MAT-1", "quantite_estimee": -1.0, "unite": "boite"}], [],
    )
    assert maillon is None
    assert code == "REJ-LIGNE-MATERIAUX-QUANTITE-INVALIDE"


def test_enregistrer_idempotent_par_devis_id_refuse_nomme_sans_fusion():
    maillons = [{"chantier_id": "C1", "devis_id": "DEVIS-1", "lignes": [_ligne(quantite_estimee=10.0)]}]
    maillon, code = besoins_prevus.enregistrer(
        "C1", "DEVIS-1", [_ligne(quantite_estimee=999.0)], maillons,
    )
    assert maillon is None
    assert code == "REJ-BESOINS-PREVUS-DEJA-ENREGISTRES"
    # jamais fusionné ni réécrit : le premier maillon reste identique
    assert maillons[0]["lignes"][0]["quantite_estimee"] == 10.0


def test_enregistrer_meme_chantier_devis_id_distincts_tous_deux_acceptes():
    maillons: list[dict] = []
    m1, code1 = besoins_prevus.enregistrer("C1", "DEVIS-1", [_ligne()], maillons)
    maillons.append(m1)
    m2, code2 = besoins_prevus.enregistrer("C1", "DEVIS-2", [_ligne(materiau_id="MAT-2")], maillons)
    assert code1 is None and code2 is None
    assert m1["devis_id"] != m2["devis_id"]


def test_pour_devis_trouve_le_maillon_enregistre():
    maillons = [
        {"chantier_id": "C1", "devis_id": "DEVIS-1", "lignes": [_ligne()]},
        {"chantier_id": "C2", "devis_id": "DEVIS-2", "lignes": [_ligne(materiau_id="MAT-2")]},
    ]
    trouve = besoins_prevus.pour_devis("DEVIS-2", maillons)
    assert trouve is not None
    assert trouve["chantier_id"] == "C2"


def test_pour_devis_absent_rend_none():
    assert besoins_prevus.pour_devis("DEVIS-INCONNU", []) is None
    assert besoins_prevus.pour_devis(None, [{"devis_id": "DEVIS-1"}]) is None
