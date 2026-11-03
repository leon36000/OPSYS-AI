"""M10-06 : la consommation DÉTERMINISTE d'une leçon promue par un département (socle).

Une leçon n'est jamais un texte appliqué par un modèle : le code lit son paramètre, vérifie la cible,
l'échantillon DÉCLARÉ et les sources, puis propose une valeur corrigée qui cite la leçon. Sans leçon
active, avec un échantillon insuffisant ou un minimum non déclaré, aucune correction n'est appliquée et
la réponse dit pourquoi. Fictif.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from opsys.mnemo import consommation

FICTIF = True


def _lecon(**surcharges):
    base = {
        "lecon_id": "lc-fictive-0001",
        "genre": "ecart_materiau",
        "cible": "m06-material-control",
        "cle": "gouttiere-alu-5po-fictif",
        "etat": "complete",
        "propose_le": "2026-10-01T12:00:00+00:00",
        "sources": ["ligne-fictive-1", "ligne-fictive-2"],
        "contenu": {
            "parametre": "1.15",
            "mode": "facteur",
            "chantiers": 6,
            "coherence": "0.8000",
        },
        "decisions": [
            {
                "etape": "complete",
                "par": "nathan",
                "role": "nathan_owner",
                "motif": "Décision fictive de test.",
                "horodatage": "2026-10-02T12:00:00+00:00",
            }
        ],
    }
    base.update(surcharges)
    return base


def _marge(**surcharges):
    lecon = _lecon(
        lecon_id="lc-fictive-marge",
        genre="ecart_marge",
        cible="m05-financecore",
        cle="marge",
        sources=["rentabilite-fictive-1"],
        contenu={"parametre": "-15.00", "mode": "decalage_cad", "chantiers": 6, "coherence": "0.9000"},
    )
    lecon.update(surcharges)
    return lecon


def _appeler(lecons, *, genre="ecart_materiau", cible="m06-material-control", entrees=None, minimum=6):
    return consommation.appliquer_lignes(
        consommateur="m03-estimation" if genre == "ecart_materiau" else "m05-financecore",
        cible=cible,
        genre=genre,
        entrees=entrees
        or [{"cle": "gouttiere-alu-5po-fictif", "base": "20.00"}],
        lecons_actives=lecons,
        minimum_echantillon=minimum,
    )


def test_sans_lecon_active_aucune_correction_et_le_dit():
    r = _appeler([])
    assert r["statut"] == "aucune_lecon_active"
    assert r["application"] == "aucune_correction"
    assert r["corrections"] == []
    assert r["lignes"][0]["valeur"] == "20.00" and r["lignes"][0]["corrigee"] is False
    assert r["lignes"][0]["raison"] == "aucune_lecon_active"


def test_echantillon_sous_le_minimum_declare_ne_corrige_pas_et_nomme_le_minimum():
    r = _appeler([_lecon()], minimum=7)
    assert r["statut"] == "aucune_correction"
    assert r["lignes"][0]["corrigee"] is False and r["lignes"][0]["valeur"] == "20.00"
    ligne = r["lignes"][0]
    assert ligne["raison"] == "echantillon_insuffisant"
    assert ligne["echantillon"] == 6 and ligne["minimum_echantillon"] == 7


def test_le_minimum_est_une_borne_INCLUSE():
    r = _appeler([_lecon()], minimum=6)
    assert r["statut"] == "correction_proposee"
    assert Decimal(r["lignes"][0]["valeur"]) == Decimal("23.00")


def test_le_minimum_non_declare_ne_corrige_rien_et_dit_quoi_declarer():
    r = _appeler([_lecon()], minimum=None)
    assert r["statut"] == "minimum_non_declare"
    assert r["lignes"][0]["corrigee"] is False
    assert "echantillon_minimum" in r["avertissement"]
    assert r["minimum_echantillon"] is None


@pytest.mark.parametrize("minimum", [0, -1, True, 6.0, "6", 1001])
def test_un_minimum_invalide_est_refuse_ferme(minimum):
    r = _appeler([_lecon()], minimum=minimum)
    assert r["statut"] == "minimum_invalide"
    assert r["lignes"][0]["corrigee"] is False
    assert r["lignes"][0]["valeur"] == "20.00"


def test_la_valeur_corrigee_cite_identifiant_sources_date_et_echantillon():
    ligne = _appeler([_lecon()])["lignes"][0]
    assert ligne["corrigee"] is True
    attribution = ligne["attribution"]
    assert attribution["lecon_id"] == "lc-fictive-0001"
    assert attribution["sources"] == ["ligne-fictive-1", "ligne-fictive-2"]
    assert attribution["date"] == "2026-10-01T12:00:00+00:00"
    assert attribution["echantillon"] == 6
    assert attribution["parametre"] == "1.15"
    assert attribution["decision"]["etape"] == "complete"
    assert attribution["decision"]["par"] == "nathan"
    # la correction reste une PROPOSITION : rien n'est appliqué par le calcul
    assert ligne["application"] == "proposee_non_appliquee"
    assert ligne["niveau_humain"] == "N4"


def test_une_lecon_d_un_autre_departement_ne_s_applique_pas():
    r = _appeler([_lecon(cible="m05-financecore")])
    assert r["statut"] == "aucune_lecon_active"
    assert r["lignes"][0]["corrigee"] is False


def test_deux_lecons_applicables_sont_refusees_plutot_que_doublees():
    r = _appeler([_lecon(), _lecon(lecon_id="lc-fictive-0002")])
    assert r["statut"] == "plusieurs_lecons_actives"
    assert r["lignes"][0]["corrigee"] is False
    assert r["lignes"][0]["raison"] == "plusieurs_lecons_actives"


def test_un_parametre_illisible_est_refuse_et_n_est_pas_interprete():
    r = _appeler([_lecon(contenu={"parametre": "quinze pour cent", "mode": "facteur", "chantiers": 6})])
    assert r["statut"] == "lecon_inapplicable"
    assert r["lignes"][0]["corrigee"] is False
    assert r["lignes"][0]["raison"] == "parametre_invalide"


def test_des_sources_absentes_ne_permettent_pas_d_attribuer_la_valeur():
    r = _appeler([_lecon(sources=[])])
    assert r["lignes"][0]["corrigee"] is False
    assert r["lignes"][0]["raison"] == "sources_absentes"


def test_une_date_illisible_ne_berne_pas_l_attribution():
    r = _appeler([_lecon(propose_le="hier")])
    assert r["lignes"][0]["corrigee"] is False
    assert r["lignes"][0]["raison"] == "date_invalide"


def test_une_lecon_non_promue_ne_s_applique_pas_meme_si_elle_est_fournie():
    r = _appeler([_lecon(etat="proposee")])
    assert r["lignes"][0]["corrigee"] is False
    assert r["lignes"][0]["raison"] == "etat_non_actif"


def test_une_lecon_en_canari_fournie_par_le_port_est_acceptee():
    r = _appeler([_lecon(etat="canari")])
    assert r["statut"] == "correction_proposee"
    assert r["lignes"][0]["attribution"]["etat"] == "canari"


def test_la_marge_est_un_decalage_en_dollars_et_non_un_facteur():
    r = _appeler(
        [_marge()],
        genre="ecart_marge",
        cible="m05-financecore",
        entrees=[{"cle": "marge", "base": "120.00"}],
    )
    assert r["statut"] == "correction_proposee"
    assert Decimal(r["lignes"][0]["valeur"]) == Decimal("105.00")
    assert r["lignes"][0]["attribution"]["mode"] == "decalage_cad"


def test_un_facteur_negatif_ou_nul_est_refuse():
    for facteur in ("0", "-1.5"):
        r = _appeler([_lecon(contenu={"parametre": facteur, "mode": "facteur", "chantiers": 6})])
        assert r["lignes"][0]["corrigee"] is False
        assert r["lignes"][0]["raison"] == "parametre_invalide"


def test_la_quantite_de_base_doit_etre_un_decimal_strict_positif():
    for base in ("0", "-2", "vingt", "1e3", 20):
        r = _appeler([_lecon()], entrees=[{"cle": "gouttiere-alu-5po-fictif", "base": base}])
        assert r["lignes"][0]["corrigee"] is False
        assert r["lignes"][0]["raison"] == "base_invalide"


def test_lire_minimum_declare_et_ses_bornes():
    assert consommation.lire_minimum({"echantillon_minimum": 6}) == (6, None)
    assert consommation.lire_minimum({"echantillon_minimum": 1}) == (1, None)
    assert consommation.lire_minimum({"echantillon_minimum": 1000}) == (1000, None)
    assert consommation.lire_minimum({}) == (None, "minimum_non_declare")
    assert consommation.lire_minimum(None) == (None, "minimum_non_declare")
    for invalide in (0, -1, True, 6.0, "6", 1001):
        minimum, raison = consommation.lire_minimum({"echantillon_minimum": invalide})
        assert minimum is None and raison == "minimum_invalide"


def test_les_entrees_doivent_etre_une_sequence():
    r = consommation.appliquer_lignes(
        consommateur="m03-estimation",
        cible="m06-material-control",
        genre="ecart_materiau",
        entrees="mat-a",
        lecons_actives=[],
        minimum_echantillon=6,
    )
    assert r["statut"] == "entree_invalide"
    assert r["lignes"] == []


# -- mutants survivants : cas de forme et bornes ---------------------------------------------------
def test_une_date_non_texte_ou_vide_est_refusee_sans_lever():
    for propose_le in (None, 123, "", "hier"):
        r = _appeler([_lecon(propose_le=propose_le)])
        assert r["lignes"][0]["corrigee"] is False
        assert r["lignes"][0]["raison"] == "date_invalide"


def test_seules_les_decisions_actives_sont_citees():
    lecon = _lecon(decisions=[{"etape": "proposee", "par": "nathan", "horodatage": "2026-10-02T12:00:00+00:00"}])
    ligne = _appeler([lecon])["lignes"][0]
    assert ligne["corrigee"] is True
    assert ligne["attribution"]["decision"] is None


def test_des_sources_en_texte_ou_avec_un_element_vide_sont_refusees():
    for sources in ("ligne-fictive-1", [""], []):
        r = _appeler([_lecon(sources=sources)])
        assert r["lignes"][0]["corrigee"] is False
        assert r["lignes"][0]["raison"] == "sources_absentes"


def test_un_identifiant_non_texte_est_refuse():
    r = _appeler([_lecon(lecon_id=123)])
    assert r["lignes"][0]["raison"] == "identifiant_invalide"


def test_un_contenu_non_mapping_est_refuse():
    r = _appeler([_lecon(contenu="1.15")])
    assert r["lignes"][0]["corrigee"] is False
    assert r["lignes"][0]["raison"] == "mode_invalide"


def test_un_facteur_inferieur_a_un_reste_une_valeur_admissible():
    r = _appeler([_lecon(contenu={"parametre": "0.5", "mode": "facteur", "chantiers": 6})])
    assert r["lignes"][0]["corrigee"] is True
    assert Decimal(r["lignes"][0]["valeur"]) == Decimal("10.00")


def test_l_avertissement_fourni_est_conserve():
    r = consommation.appliquer_lignes(
        consommateur="m03-estimation", cible="m06-material-control", genre="ecart_materiau",
        entrees=[{"cle": "gouttiere-alu-5po-fictif", "base": "20.00"}], lecons_actives=[],
        minimum_echantillon=6, avertissement="Avertissement fictif fourni par l'appelant.",
    )
    assert r["avertissement"] == "Avertissement fictif fourni par l'appelant."


def test_les_bornes_1_et_1000_du_minimum_sont_acceptees():
    for minimum in (1, 1000):
        r = _appeler([_lecon()], minimum=minimum)
        assert r["statut"] != "minimum_invalide"
        assert r["lignes"][0]["minimum_echantillon"] == minimum


def test_une_cle_non_texte_est_refusee():
    r = _appeler([_lecon()], entrees=[{"cle": 123, "base": "20.00"}])
    assert r["lignes"][0]["corrigee"] is False
    assert r["lignes"][0]["raison"] == "cle_invalide"


def test_une_base_none_est_refusee_sans_lever():
    r = _appeler([_lecon()], entrees=[{"cle": "gouttiere-alu-5po-fictif", "base": None}])
    assert r["lignes"][0]["corrigee"] is False
    assert r["lignes"][0]["raison"] == "base_invalide"


def test_lecons_actives_refuse_une_cible_ou_une_cle_non_texte():
    for cible, cle in ((123, "cas"), ("m06-material-control", 123), ("", "cas"), ("m06-material-control", "")):
        with pytest.raises(ValueError):
            consommation.lecons_actives(cible, cle)


def test_le_verificateur_refuse_une_cible_ou_une_cle_differente():
    attribution, raison = consommation._verifier(
        _lecon(), genre="ecart_materiau", cible="m05-financecore", cle="gouttiere-alu-5po-fictif", minimum=6
    )
    assert attribution is None and raison == "cible_invalide"
    attribution, raison = consommation._verifier(
        _lecon(), genre="ecart_materiau", cible="m06-material-control", cle="autre-materiau", minimum=6
    )
    assert attribution is None and raison == "cible_invalide"


def test_une_entree_non_mapping_est_refusee_sans_lever():
    r = _appeler([_lecon()], entrees=["pas un objet"])
    assert r["lignes"][0]["corrigee"] is False
    assert r["lignes"][0]["raison"] == "entree_invalide"


def test_lecons_actives_non_sequence_est_traite_comme_aucune_lecon():
    r = consommation.appliquer_lignes(
        consommateur="m03-estimation", cible="m06-material-control", genre="ecart_materiau",
        entrees=[{"cle": "gouttiere-alu-5po-fictif", "base": "20.00"}], lecons_actives={"x": 1},
        minimum_echantillon=6,
    )
    assert r["statut"] == "aucune_lecon_active"


def test_une_quantite_fractionnaire_positive_est_une_base_valide():
    r = _appeler([_lecon()], entrees=[{"cle": "gouttiere-alu-5po-fictif", "base": "0.5"}])
    assert r["lignes"][0]["corrigee"] is True
    assert Decimal(r["lignes"][0]["valeur"]) == Decimal("0.575")


def test_des_decisions_non_sequence_ne_font_pas_echouer():
    for decisions in (None, 123):
        ligne = _appeler([_lecon(decisions=decisions)])["lignes"][0]
        assert ligne["corrigee"] is True
        assert ligne["attribution"]["decision"] is None


def test_un_minimum_invalide_avec_une_entree_texte_ne_liste_pas_ses_caracteres():
    r = _appeler([], minimum=None, entrees="mat-a")
    assert r["statut"] == "minimum_non_declare"
    assert r["lignes"] == []


def test_une_liste_de_lecons_non_sequence_ou_entier_ne_leve_pas():
    for lecons in ({"x": 1}, 123, None):
        r = consommation.appliquer_lignes(
            consommateur="m03-estimation", cible="m06-material-control", genre="ecart_materiau",
            entrees=[{"cle": "gouttiere-alu-5po-fictif", "base": "20.00"}], lecons_actives=lecons,
            minimum_echantillon=6,
        )
        assert r["statut"] == "aucune_lecon_active"
        assert r["lignes"][0]["corrigee"] is False
