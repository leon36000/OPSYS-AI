"""M9.13 — radar d'occasions : hypothèse sans coût ni capacité cités, aucun revenu inventé (fictif)."""

import pytest
from m9_strategic_intelligence import capture_strategique as cs
from m9_strategic_intelligence import catalogue_producteurs as cat
from m9_strategic_intelligence import occasions as oc

FICTIF = True
CONNAISSANCE = "2026-10-28T13:00:00Z"
FAITS = {
    "m8.vue_executive#0:p0.resultat.cout_relance": "300",
    "m4.cedule_semaine#1:p0.resultat.resultat.capacite": "6",
    "m8.vue_executive#0:p0.resultat.signal": "3",
}
COUT, CAPACITE, SIGNAL = (
    "m8.vue_executive#0:p0.resultat.cout_relance",
    "m4.cedule_semaine#1:p0.resultat.resultat.capacite",
    "m8.vue_executive#0:p0.resultat.signal",
)


def occasion(id_="o1", **extra):
    return {"id": id_, "libelle": f"Occasion fictive {id_}", "origine": "DECLAREE_PAR_LA_PERSONNE", **extra}


def test_sans_cout_ni_capacite_cites_l_occasion_reste_une_hypothese_et_dit_ce_qui_manque():
    res = oc.evaluer(
        [occasion(conditions=["un technicien libre"], alternatives=["ne rien faire"])], FAITS, connaissance=CONNAISSANCE
    )
    o = res["occasions"][0]
    assert o["statut"] == "HYPOTHESE" and o["manques"] == ["cout", "capacite"]
    assert o["confiance"] == "NON_ESTIMEE" and o["decision"] == "HUMAINE_REQUISE" and o["mesurable"] is False
    assert "aucun signal mesuré cité" in o["limites_de_confiance"]
    assert o["conditions"] == ["un technicien libre"] and o["alternatives"] == ["ne rien faire"]
    assert "revenu" not in str(res["occasions"]).lower()


def test_cout_et_capacite_cites_donnent_une_occasion_documentee_toujours_decidee_par_un_humain():
    o = oc.evaluer(
        [occasion(cout_ref=COUT, capacite_ref=CAPACITE, signaux_refs=[SIGNAL])], FAITS, connaissance=CONNAISSANCE
    )["occasions"][0]
    assert o["statut"] == "DOCUMENTEE" and o["manques"] == [] and o["mesurable"] is True
    assert o["cout"] == {"ref": COUT, "texte": "300"} and o["capacite"]["texte"] == "6"
    assert o["signaux"] == [{"ref": SIGNAL, "texte": "3"}] and o["decision"] == "HUMAINE_REQUISE"
    seul = oc.evaluer([occasion(cout_ref=COUT)], FAITS, connaissance=CONNAISSANCE)["occasions"][0]
    assert seul["statut"] == "HYPOTHESE" and seul["manques"] == ["capacite"]


@pytest.mark.parametrize(
    "cle", ["revenu", "gain", "marge", "probabilite", "chiffre_affaires", "ROI", "date_realisation"]
)
def test_aucune_cle_de_revenu_probable_n_est_acceptee(cle):
    with pytest.raises(ValueError, match="REJ-OCCASION-REVENU"):
        oc.evaluer([occasion(**{cle: "5000"})], FAITS, connaissance=CONNAISSANCE)


@pytest.mark.parametrize(
    "extra, code",
    [
        ({"cout_ref": "m8.vue_executive#0:p0.resultat.inconnu"}, "REJ-OCCASION-REF"),
        ({"capacite_ref": "n'importe quoi"}, "REJ-OCCASION-REF"),
        ({"signaux_refs": ["m8.vue_executive#9:p0.x"]}, "REJ-OCCASION-REF"),
        ({"origine": "MODELE"}, "REJ-OCCASION-CHAMP"),
        ({"conditions": "oui"}, "REJ-OCCASION-CHAMP"),
        ({"champ_inconnu": 1}, "REJ-OCCASION-CHAMP"),
        ({"id": "a b"}, "REJ-OCCASION-CHAMP"),
    ],
)
def test_references_inconnues_et_champs_invalides_refuses(extra, code):
    with pytest.raises(ValueError, match=code):
        oc.evaluer([{**occasion(), **extra}], FAITS, connaissance=CONNAISSANCE)


def test_doublon_et_borne():
    with pytest.raises(ValueError, match="REJ-OCCASION-CHAMP"):
        oc.evaluer([occasion("x"), occasion("x")], FAITS, connaissance=CONNAISSANCE)
    with pytest.raises(ValueError, match="REJ-OCCASION-CHAMP"):
        oc.evaluer([occasion(f"o{i}") for i in range(oc.MAX_OCCASIONS + 1)], FAITS, connaissance=CONNAISSANCE)


def _capture_m8(devis, index=0, complet=True):
    page = {"ok": True, "resultat": {"entonnoir": {"devis_en_attente": {"sans_reponse": {"devis": devis, "reste": 0}}}}}
    return cs.construire(
        cat.obtenir("m8.vue_executive"),
        {"aujourd_hui": "2026-10-27"},
        [page],
        recu_a="2026-10-27T12:00:00Z",
        reference="2026-10-27",
        index=index,
        hash_precedent=cs.HASH_INITIAL,
    )


def test_signal_mesure_devis_sans_reponse_est_une_hypothese_sans_taux_de_conversion():
    res = oc.evaluer([], {}, [_capture_m8(["D1", "D2"])], connaissance=CONNAISSANCE)
    (signal,) = res["signaux_mesures"]
    assert signal["nombre_de_devis"] == 2 and signal["devis"] == ["D1", "D2"] and signal["statut"] == "HYPOTHESE"
    assert signal["signal"]["adresse"].startswith("m8.vue_executive#0:p0.resultat.entonnoir")
    assert signal["manques"] == ["cout", "capacite"] and signal["confiance"] == "NON_ESTIMEE"
    assert "conversion" in signal["limites_de_confiance"][0] and "revenu" not in str(signal).lower()
    assert oc.evaluer([], {}, [_capture_m8([])], connaissance=CONNAISSANCE)["signaux_mesures"] == []
    # connaissance antérieure à la réception : le signal n'était pas connu
    assert oc.evaluer([], {}, [_capture_m8(["D1"])], connaissance="2026-10-27T11:00:00Z")["signaux_mesures"] == []


def test_identifiant_lie_au_contenu_et_deterministe():
    a = oc.evaluer([occasion()], FAITS, connaissance=CONNAISSANCE)
    b = oc.evaluer([occasion()], dict(reversed(list(FAITS.items()))), connaissance=CONNAISSANCE)
    assert a["radar_id"] == b["radar_id"] and len(a["radar_id"]) == 64
    assert oc.evaluer([occasion("o2")], FAITS, connaissance=CONNAISSANCE)["radar_id"] != a["radar_id"]
