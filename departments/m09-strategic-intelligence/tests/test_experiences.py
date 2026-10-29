"""M9.18 — expériences et ROI : pas de ROI sur données manquantes, association ≠ causalité, source corrigée (fictif)."""

import pytest
from m9_strategic_intelligence import capture_strategique as cs
from m9_strategic_intelligence import catalogue_producteurs as cat
from m9_strategic_intelligence import experiences as ex

FICTIF = True
CONNAISSANCE = "2026-10-28T13:00:00Z"
T = "2026-10-20T12:00:00Z"
EXPOSE = "m8.mesures_chantier#0:p0.resultat.valeur_expose"
REFERENCE = "m8.mesures_chantier#0:p0.resultat.valeur_reference"
COUT = "m7.performance_campagnes#1:p0.resultat.resultat.cout_total"
EFFECTIF = "m7.performance_campagnes#1:p0.resultat.resultat.leads"
FAITS = {EXPOSE: "1200.00", REFERENCE: "1000.00", COUT: "100.00", EFFECTIF: "10"}


def captures(expose="1200.00", reference="1000.00", cout="100.00", avec_cout=True, avec_effectif=True):
    pages = [
        ("m8.mesures_chantier", {"ok": True, "resultat": {"valeur_expose": expose, "valeur_reference": reference}}),
    ]
    if avec_cout:
        contenu = {"cout_total": cout}
        if avec_effectif:
            contenu["leads"] = "10"
        pages.append(("m7.performance_campagnes", {"ok": True, "resultat": {"accepte": True, "resultat": contenu}}))
    chaine, precedent = [], cs.HASH_INITIAL
    for index, (lecture, page) in enumerate(pages):
        capture = cs.construire(
            cat.obtenir(lecture), {}, [page], recu_a=f"2026-10-2{index + 1}T12:00:00Z", reference=None, index=index,
            hash_precedent=precedent,
        )  # fmt: skip
        chaine.append(capture)
        precedent = capture["hash_maillon"]
    return chaine


def experience(design="AVANT_APRES", **extra):
    base = {
        "experience_id": "gouttiere-alt",
        "hypothese": "Le matériau alternatif améliore la marge réelle",
        "design": design,
        "exposition": "chantiers avec le matériau alternatif",
        "reference": "chantiers de référence",
        "mesures": [
            {"id": "expose", "role": "expose", "ref": EXPOSE, "unite": "CAD"},
            {"id": "reference", "role": "reference", "ref": REFERENCE, "unite": "CAD"},
            {"id": "cout", "role": "cout", "ref": COUT, "unite": "CAD"},
            {"id": "effectif", "role": "effectif", "ref": EFFECTIF, "unite": "leads"},
        ],
        "contre_exemples": ["chantier C-4 : marge plus basse malgré le matériau alternatif"],
    }
    return {**base, **extra}


def definir(chaine, **kwargs):
    maillon = ex.definir(chaine, kwargs.pop("exp", experience()), FAITS, recu_a=T, par="admin.fictif", **kwargs)
    chaine.append(maillon)
    return maillon


def evaluation(exp=None, capt=None):
    chaine = []
    maillon = definir(chaine, exp=exp or experience())
    return ex.evaluer(maillon["definition"], capt if capt is not None else captures(), connaissance=CONNAISSANCE)


def test_gain_roi_et_association_avec_lacunes_dites():
    res = evaluation()
    assert res["gain_mesure"] == "200.00" and res["roi"] == "1.0000" and res["statut_roi"] == "CALCULE"
    assert res["inference"] == "ASSOCIATION_SEULEMENT" and "DESIGN_NON_ALEATOIRE" in res["lacunes"]
    assert res["incertitude"] == "NON_CHIFFREE" and res["contre_exemples"]["total"] == 1 and res["manques"] == []
    assert "EFFECTIF_INCONNU" not in res["lacunes"]


def test_aucun_roi_sur_donnees_manquantes_cout_absent_ou_non_lu():
    sans_cout = evaluation(capt=captures(avec_cout=False))
    assert sans_cout["statut_roi"] == "ROI_NON_CALCULABLE" and sans_cout["roi"] is None
    assert sans_cout["gain_mesure"] == "200.00", "le gain mesuré reste dit : il vient de M8"
    assert any("LECTURE_INDISPONIBLE" in m for m in sans_cout["manques"]) and "EFFECTIF_INCONNU" in sans_cout["lacunes"]
    nul = evaluation(capt=captures(cout=None))  # cout_par_lead None côté producteur : donnée insuffisante
    assert nul["statut_roi"] == "ROI_NON_CALCULABLE" and any("VALEUR_ABSENTE" in m for m in nul["manques"])
    zero = evaluation(capt=captures(cout="0.00"))
    assert zero["roi"] is None and any("indéfini" in m for m in zero["manques"])
    texte = evaluation(capt=captures(cout="beaucoup"))
    assert texte["roi"] is None and any("non numérique" in m for m in texte["manques"])


def test_unites_divergentes_et_devise_non_cad_refusent_le_roi():
    heures = experience(
        mesures=[
            {"id": "expose", "role": "expose", "ref": EXPOSE, "unite": "heures"},
            {"id": "reference", "role": "reference", "ref": REFERENCE, "unite": "CAD"},
            {"id": "cout", "role": "cout", "ref": COUT, "unite": "CAD"},
        ]
    )
    res = evaluation(exp=heures)
    assert res["gain_mesure"] is None and res["roi"] is None and any("UNITE_DIVERGENTE" in m for m in res["manques"])
    usd = experience(
        mesures=[
            {"id": "expose", "role": "expose", "ref": EXPOSE, "unite": "CAD"},
            {"id": "reference", "role": "reference", "ref": REFERENCE, "unite": "CAD"},
            {"id": "cout", "role": "cout", "ref": COUT, "unite": "USD"},
        ]
    )
    res = evaluation(exp=usd)
    assert res["roi"] is None and any("≠ CAD" in m for m in res["manques"])


def test_design_aleatoire_plausible_sans_preuve_et_sans_reference_aucun_gain():
    assert evaluation(exp=experience("ALEATOIRE"))["inference"] == "CAUSALITE_PLAUSIBLE_SI_ALEATOIRE_DECLARE"
    assert "DESIGN_NON_ALEATOIRE" not in evaluation(exp=experience("ALEATOIRE"))["lacunes"]
    sans = evaluation(exp=experience("SANS_REFERENCE"))
    assert sans["gain_mesure"] is None and sans["roi"] is None and any("SANS_REFERENCE" in m for m in sans["manques"])


def test_gain_negatif_est_un_contre_exemple_de_plus():
    res = evaluation(capt=captures(expose="900.00"))
    assert res["gain_mesure"] == "-100.00" and res["contre_exemples"]["total"] == 2 and res["roi"] == "-2.0000"


def test_source_corrigee_produit_un_nouveau_resultat_sans_effacer_l_ancien():
    chaine = []
    maillon = definir(chaine)
    premiere = ex.evaluer(maillon["definition"], captures(), connaissance=CONNAISSANCE)
    r1 = ex.enregistrer_resultat(chaine, "gouttiere-alt", premiere, recu_a="2026-10-22T12:00:00Z", par="a")
    chaine.append(r1)
    assert ex.enregistrer_resultat(chaine, "gouttiere-alt", premiere, recu_a="2026-10-23T12:00:00Z", par="a") is None
    corrigees = captures(expose="1300.00")
    deuxieme = ex.evaluer(maillon["definition"], corrigees, connaissance=CONNAISSANCE)
    assert "SOURCE_CORRIGEE_DEPUIS_LE_DEPOT" in deuxieme["lacunes"] and deuxieme["gain_mesure"] == "300.00"
    r2 = ex.enregistrer_resultat(chaine, "gouttiere-alt", deuxieme, recu_a="2026-10-24T12:00:00Z", par="a")
    chaine.append(r2)
    historique = ex.vue(chaine, corrigees, connaissance=CONNAISSANCE)["experiences"][0]["historique_resultats"]
    assert [h["gain_mesure"] for h in historique] == ["200.00", "300.00"] and ex.valider_chaine(chaine) == (True, "")
    # connaissance antérieure à la correction : seul le premier résultat est connu
    avant = ex.vue(chaine, corrigees, connaissance="2026-10-23T00:00:00Z")["experiences"][0]["historique_resultats"]
    assert [h["gain_mesure"] for h in avant] == ["200.00"]


@pytest.mark.parametrize(
    "exp, code",
    [
        ({"design": "MAGIE"}, "REJ-EXPERIENCE-CHAMP"),
        ({"mesures": []}, "REJ-EXPERIENCE-MESURE"),
        ({"mesures": [{"id": "a", "role": "gain", "ref": EXPOSE, "unite": "CAD"}]}, "REJ-EXPERIENCE-MESURE"),
        (
            {"mesures": [{"id": "a", "role": "expose", "ref": "m8.mesures_chantier#9:p0.inconnu", "unite": "CAD"}]},
            "REJ-EXPERIENCE-SOURCE",
        ),
        ({"mesures": [{"id": "a", "role": "expose", "ref": EXPOSE, "unite": ""}]}, "REJ-EXPERIENCE-MESURE"),
        ({"mesures": [{"id": "a", "role": "expose", "ref": EXPOSE, "unite": "CAD"}] * 2}, "REJ-EXPERIENCE-MESURE"),
        ({"contre_exemples": "aucun"}, "REJ-EXPERIENCE-CHAMP"),
        ({"experience_id": "Majuscule"}, "REJ-EXPERIENCE-CHAMP"),
        ({"roi": "3"}, "REJ-EXPERIENCE-CHAMP"),
    ],
)
def test_definitions_refusees(exp, code):
    with pytest.raises(ValueError, match=code):
        ex.definir([], experience(**exp), FAITS, recu_a=T, par="a")


def test_revision_exige_motif_et_changement():
    chaine = []
    definir(chaine)
    with pytest.raises(ValueError, match="REJ-EXPERIENCE-REVISION"):
        ex.definir(chaine, experience(), FAITS, recu_a=T, par="a", motif_revision="rien")
    with pytest.raises(ValueError, match="REJ-EXPERIENCE-REVISION"):
        ex.definir(chaine, experience("GROUPE_TEMOIN"), FAITS, recu_a=T, par="a")
    deux = ex.definir(
        chaine, experience("GROUPE_TEMOIN"), FAITS, recu_a=T, par="a", motif_revision="groupe témoin ajouté"
    )
    assert deux["version"] == 2
    with pytest.raises(ValueError, match="REJ-EXPERIENCE-INCONNUE"):
        ex.enregistrer_resultat(chaine, "absente", {"entrees_hash": "x"}, recu_a=T, par="a")
