"""Les outils de mesure : niveaux, schémas stricts, garde d'argent, parcours de bout en bout sur base réelle."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from fabriques_mesure import evenements_de
from m7_marketing import depenses_marketing as dep
from m7_marketing import mesure_outils as mo
from m7_marketing import outils as outils_m7
from m7_marketing.mesure import conversions as conv
from m7_marketing.mesure import experiences

from opsys import contexte, stockage
from opsys.outils import Autonomie, Niveau

NOMS = {
    "m7_normaliser_utm": (Autonomie.T0, None),
    "m7_importer_conversions_hors_ligne": (Autonomie.T1, Niveau.N2),
    "m7_concevoir_test_marketing": (Autonomie.T0, None),
    "m7_enregistrer_plan_test_marketing": (Autonomie.T1, Niveau.N2),
    "m7_analyser_test_marketing": (Autonomie.T0, None),
    "m7_lire_attribution_simple": (Autonomie.T0, None),
    "m7_rejouer_recu_mesure": (Autonomie.T0, None),
}
SRC = Path(mo.__file__).parent
HORO = "2026-11-01T12:00:00+00:00"


def _outil(nom):
    return next(o for o in mo.outils() if o.nom == nom)


def test_sept_outils_aux_niveaux_declares_sans_role_d_appareil_et_schemas_stricts():
    assert {o.nom for o in mo.outils()} == set(NOMS)
    for o in mo.outils():
        autonomie, niveau = NOMS[o.nom]
        assert o.autonomie == autonomie and o.niveau == niveau, o.nom
        assert o.roles_appareil == frozenset(), o.nom
        assert o.parametres["additionalProperties"] is False, o.nom
        assert set(o.parametres["required"]) <= set(o.parametres["properties"])
        assert o.description.strip() and len(o.description) <= 1024


def test_aucun_conflit_de_nom_avec_les_outils_existants():
    existants = [o.nom for o in outils_m7.outils()]
    assert len(existants) == len(set(existants))
    assert not set(NOMS) & set(existants) or set(NOMS) <= set(existants)


def test_aucun_outil_d_ecriture_n_est_t0_et_aucun_ne_depasse_n2():
    for o in mo.outils():
        assert o.niveau in (None, Niveau.N2)
        if o.niveau == Niveau.N2:
            assert o.autonomie == Autonomie.T1


def test_aucun_module_reseau_dans_la_mesure():
    interdits = {
        "socket",
        "http",
        "urllib3",
        "requests",
        "httpx",
        "aiohttp",
        "smtplib",
        "ftplib",
        "subprocess",
        "random",
    }
    for source in [*(SRC / "mesure").glob("*.py"), SRC / "mesure_outils.py"]:
        arbre = ast.parse(source.read_text(encoding="utf-8"))
        for noeud in ast.walk(arbre):
            noms = (
                [a.name for a in noeud.names]
                if isinstance(noeud, ast.Import)
                else [noeud.module]
                if isinstance(noeud, ast.ImportFrom) and noeud.module and not noeud.level
                else []
            )
            assert not {n.split(".")[0] for n in noms} & interdits, (source.name, noms)
            if isinstance(noeud, ast.Name):
                assert noeud.id not in {"eval", "exec", "__import__"}, (source.name, noeud.id)
        assert "urlopen" not in source.read_text(encoding="utf-8")


# ----------------------------------------------------------------------------------------------- outils purs
def test_normaliser_utm_exclusivite_des_entrees():
    assert mo.normaliser_utm()["accepte"] is False
    assert mo.normaliser_utm(urls=["https://x.test/?utm_source=fb"], source="fb")["accepte"] is False
    r = mo.normaliser_utm(source="FB", medium="PPC", campagne="Fenetre Ete 2026")
    assert r["accepte"] and r["verdict"] == "normalisable" and r["parametres"]["utm_source"]["normalise"] == "facebook"
    r = mo.normaliser_utm(
        urls=["https://x.test/?utm_source=google&utm_medium=cpc&utm_campaign=fenetre-a-2026&gclid=SECRET"]
    )
    assert r["couverture"]["conformes"] == 1 and "SECRET" not in repr(r)
    url = "https://x.test/?utm_source=google&utm_medium=cpc&utm_campaign=fenetre-a-2026&utm_alice%40example.test=x"
    r = mo.normaliser_utm(urls=[url])
    assert r["accepte"] and r["urls"][0]["utm_inconnus"] == ["nom masqué"]
    assert "alice@example.test" not in repr(r)
    refus = mo.normaliser_utm(urls=["https://x.test/"] * 501)
    assert refus["accepte"] is False and refus["refus"][0]["code"] == "REJ-MESURE-UTM-ENTREE-INVALIDE"


def test_concevoir_rend_le_recu_et_refuse_un_moteur_d_analyse_ou_inconnu():
    r = mo.concevoir_test_marketing(
        "taille_echantillon_deux_proportions",
        {"p1": "0.10", "effet": {"mode": "absolu", "valeur": "0.02"}},
        {"alpha": "0.05", "puissance": "0.8"},
    )
    assert r["accepte"] and r["resultat"]["n_par_groupe"] == 3841 and r["recu"]["empreinte"]
    assert (
        mo.concevoir_test_marketing("analyse_resultat_test", {}, {})["refus"][0]["code"] == "REJ-MESURE-MOTEUR-INCONNU"
    )
    assert mo.concevoir_test_marketing("x", {}, {})["refus"][0]["code"] == "REJ-MESURE-MOTEUR-INCONNU"
    r = mo.concevoir_test_marketing(
        "puissance_deux_proportions", {"n_par_groupe": 5, "p1": "2", "p2": "0.1"}, {"alpha": "0.05"}
    )
    assert r["accepte"] is False and r["refus"][0]["code"] == "REJ-MESURE-TAUX-INVALIDE"


def test_rejouer_recu_mesure():
    recu = mo.concevoir_test_marketing(
        "puissance_deux_proportions", {"n_par_groupe": 500, "p1": "0.1", "p2": "0.14"}, {"alpha": "0.05"}
    )["recu"]
    assert mo.rejouer_recu_mesure(recu)["identique"] is True
    recu["resultat"]["puissance"] = "0.99"
    assert mo.rejouer_recu_mesure(recu)["refus"][0]["code"] == "REJ-MESURE-RECU-INVALIDE"


# ------------------------------------------------------------------------------------------- bout en bout
def _recu_marche_arret():
    return mo.concevoir_test_marketing(
        "duree_test_marche_arret",
        {
            "historique_hebdo": ["10", "12", "14", "16", "18", "20", "22", "24"],
            "effet_relatif": "0.5",
            "debut": "2027-03-01",
        },
        {"alpha": "0.05", "puissance": "0.8", "graine": 42, "plafond_semaines": 26},
    )["recu"]


def test_plan_puis_analyse_preenregistre_sur_base_reelle(base):
    recu = _recu_marche_arret()
    with stockage.transaction():
        ack = mo.enregistrer_plan_test_marketing(
            "plan-printemps",
            recu,
            "Arrêter la publicité payante deux semaines sur deux réduit les demandes de soumission.",
            "soumissions_signees",
            "2027-03-01",
            "2027-05-23",
            HORO,
        )
        assert ack["accepte"] and ack["tardif"] is False
        deja = mo.enregistrer_plan_test_marketing(
            "plan-printemps",
            recu,
            "Arrêter la publicité payante deux semaines sur deux réduit les demandes de soumission.",
            "soumissions_signees",
            "2027-03-01",
            "2027-05-23",
            HORO,
        )
        assert deja["deja_enregistre"] is True
    with stockage.transaction():
        donnees = {"test": {"k": 40, "n": 500}, "temoin": {"k": 20, "n": 500}}
        r = mo.analyser_test_marketing(donnees, "0.95", "plan-printemps", {"debut": "2027-03-01", "fin": "2027-05-23"})
        assert r["statut"] == "preenregistre"
        exploratoire = mo.analyser_test_marketing(donnees)
        assert exploratoire["statut"] == "exploratoire"
        assert len(stockage.maillons(*experiences.REGISTRE_PLANS)) == 1


def test_plan_enregistre_par_un_horodatage_de_serveur_invalide_est_refuse(base):
    with stockage.transaction():
        r = mo.enregistrer_plan_test_marketing(
            "p1",
            _recu_marche_arret(),
            "Une hypothèse assez longue pour passer.",
            "conversions",
            "2027-03-01",
            "2027-05-23",
            "hier",
        )
    assert r["accepte"] is False and r["refus"][0]["code"] == "REJ-PUBLICATION-HORODATAGE"


def test_import_de_conversions_par_l_outil_ecrit_au_registre_et_au_bus(base):
    lot = [
        {
            "conversion_id": "c-1",
            "lead_id": "lead-1",
            "type": "appel",
            "convertie_le": "2026-10-10",
            "utm_source": "google",
            "utm_medium": "cpc",
            "utm_campaign": "fenetre-ete-2026",
        }
    ]
    with stockage.transaction():
        r = mo.importer_conversions_hors_ligne(lot, HORO)
        assert r["accepte"] and r["ecrites"] == 1
        assert mo.importer_conversions_hors_ligne(lot, HORO)["deja_presentes"] == 1
        assert (
            mo.importer_conversions_hors_ligne([{**lot[0], "nom": "Jean"}], HORO)["refus"][0]["code"]
            == "REJ-MESURE-CONVERSION-CHAMP-INCONNU"
        )
    assert len(evenements_de(conv.TYPE_EVENEMENT)) == 1
    maillon = list(stockage.maillons(*conv.REGISTRE))[0]
    assert maillon["par"] == "agent"


# ------------------------------------------------------------------------------------------- garde d'argent
def _releve(canal, montant, **modif):
    base = {
        "releve_id": f"rel-{canal}-2026-10",
        "revision": 1,
        "canal": canal,
        "campagne_ref": None,
        "libelle_campagne": None,
        "periode_debut": "2026-10-01",
        "periode_fin": "2026-10-31",
        "montant_cad": montant,
        "devise": "CAD",
        "base_taxes": "HORS_TAXES",
        "source": "RELEVE_PLATEFORME",
        "source_ref": f"releve-{canal}",
        "releve_le": "2026-10-31T23:00:00Z",
    }
    base.update(modif)
    return base


def _lire_admin(debut="2026-10-01", fin="2026-10-31", **kw):
    with (
        stockage.transaction(),
        contexte.appele_par_appareil(contexte.IdentiteAppelante("admin.fictif", "admin", "console")),
    ):
        return mo.lire_attribution_simple(debut, fin, **kw)


def test_attribution_de_bout_en_bout_avec_depenses_connues_puis_partielles(base):
    lot = [
        {
            "conversion_id": f"g{i}",
            "lead_id": f"l{i}",
            "type": "vente",
            "convertie_le": "2026-10-12",
            "utm_source": "google",
            "utm_medium": "cpc",
        }
        for i in range(4)
    ] + [{"conversion_id": "s1", "lead_id": "ls1", "type": "appel", "convertie_le": "2026-10-13"}]
    with stockage.transaction():
        mo.importer_conversions_hors_ligne(lot, HORO)
        dep.enregistrer_releve(_releve("google_ads", "800.00"))
        dep.enregistrer_releve(_releve("meta", "300.00"))
    r = _lire_admin()
    assert r["accepte"] and r["total_conversions"] == 5 and r["sans_source"] == {"conversions": 1, "part": "0.2"}
    couts = {c["canal"]: c for c in r["couts_par_conversion"]}
    assert (
        couts["google_ads"]["cout_par_conversion_cad"] == "200.00" and couts["google_ads"]["statut_depense"] == "CONNUE"
    )
    assert couts["meta"]["cout_par_conversion_cad"] is None and couts["meta"]["conversions_payantes"] == 0
    assert r["causalite"] == "non_etablie" and r["depenses"]["statut"] == "CONNUE"
    partiel = _lire_admin(debut="2026-10-01", fin="2026-11-15")
    assert partiel["depenses"]["statut"] == "PARTIELLE"
    g = next(c for c in partiel["couts_par_conversion"] if c["canal"] == "google_ads")
    assert g["cout_par_conversion_cad"] is None and "PARTIELLE" in g["inconnu"]


def test_attribution_sans_aucune_depense_n_invente_aucun_cout(base):
    with stockage.transaction():
        mo.importer_conversions_hors_ligne(
            [
                {
                    "conversion_id": "g1",
                    "lead_id": "l1",
                    "type": "vente",
                    "convertie_le": "2026-10-12",
                    "utm_source": "google",
                    "utm_medium": "cpc",
                }
            ],
            HORO,
        )
    r = _lire_admin()
    assert all(
        c["cout_par_conversion_cad"] is None and c["statut_depense"] == "NON_BRANCHEE"
        for c in r["couts_par_conversion"]
    )
    assert r["depenses"]["statut"] == "NON_BRANCHEE"


def test_garde_d_argent_executee_deux_fois_avec_le_nom_de_l_outil(base, monkeypatch):
    appels = []
    monkeypatch.setattr(outils_m7, "_autoriser_lecture_performance", lambda nom="x": appels.append(nom))
    with stockage.transaction():
        mo.lire_attribution_simple("2026-10-01", "2026-10-31")
    assert appels == ["m7_lire_attribution_simple", "m7_lire_attribution_simple"]


def test_agent_seul_refuse_avant_toute_lecture_du_registre_ou_des_depenses(monkeypatch):
    def ne_pas_lire(*args, **kwargs):
        raise AssertionError("aucune lecture avant l'autorisation")

    appels = []
    monkeypatch.setattr(outils_m7.contexte_appel, "identite_appelante", lambda: None)
    monkeypatch.setattr(
        outils_m7.usine_service,
        "_proprietaire_qui_decide",
        lambda nom: (appels.append(nom), (None, {"code": "REJ-HUMAIN-REQUIS"}))[1],
    )
    monkeypatch.setattr(mo.stockage, "maillons", ne_pas_lire)
    monkeypatch.setattr(mo.depenses_marketing, "lire_depenses", ne_pas_lire)
    monkeypatch.setattr(mo.conv, "courantes", ne_pas_lire)
    with pytest.raises(ValueError, match="REJ-HUMAIN-REQUIS"):
        mo.lire_attribution_simple("2026-10-01", "2026-10-31")
    assert appels == ["m7_lire_attribution_simple"]


def test_employe_refuse_et_periodes_invalides(base):
    from opsys import identite

    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "employe.fictif", "Employé fictif", "mot-de-passe-fictif-123", ["employee"])
    with (
        stockage.transaction(),
        contexte.appele_par_appareil(contexte.IdentiteAppelante("employe.fictif", "employee", "appareil")),
        pytest.raises(ValueError, match="REJ-ROLE-COUTS"),
    ):
        mo.lire_attribution_simple("2026-10-01", "2026-10-31")
    for debut, fin, code in (
        ("2026-10-31", "2026-10-01", "PERIODE_INVERSEE"),
        ("pas-une-date", "2026-10-31", "PERIODE_DATE"),
    ):
        with pytest.raises(ValueError, match=code):
            _lire_admin(debut, fin)
    with pytest.raises(ValueError, match="PERIODE_TROP_LONGUE"):
        _lire_admin("2024-01-01", "2026-10-31")
