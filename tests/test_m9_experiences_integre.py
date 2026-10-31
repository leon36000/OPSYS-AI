"""M9.18 — expériences/ROI par le vrai dispatcher, mesures M8 et coût M5 réels : pas de ROI sans coût (fictif)."""

from __future__ import annotations

import json

import m2_revenue_crm.outils as m2_outils
from sqlalchemy import select

from opsys import stockage
from opsys.stockage.schema import META

pytest_plugins: list[str] = []
G = __import__("importlib").import_module  # chargé paresseusement ci-dessous
FICTIF = True


def _g():
    import importlib.util
    import sys
    from pathlib import Path

    chemin = Path(__file__).with_name("test_m9_graphe_reel.py")
    spec = importlib.util.spec_from_file_location("test_m9_graphe_reel", chemin)
    module = importlib.util.module_from_spec(spec)
    sys.modules["test_m9_graphe_reel"] = module
    spec.loader.exec_module(module)
    return module


G = _g()
B = G.B
REF = "2026-10-28T13:00:00Z"


def appel(cap, nom, arguments, identite_appelante=B.ADMIN):
    if identite_appelante is None:
        return cap.appeler(nom, arguments)
    with B.contexte.appele_par_appareil(identite_appelante):
        return cap.appeler(nom, arguments)


def ok(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]


def refuse(reponse, code=None):
    echec = reponse["ok"] is False or reponse["resultat"].get("accepte") is False
    return echec and (code is None or code in json.dumps(reponse))


def _fait(faits, lecture, suffixe):
    (adresse,) = [a for a in faits if a.startswith(f"{lecture}#") and a.endswith(suffixe)]
    return adresse


def test_experience_sur_marges_reelles_m8_sans_cout_puis_avec_cout_m5(tmp_path, monkeypatch):
    try:
        G._monter_scenario(tmp_path, monkeypatch)
        cap = B.capacites(G.M2, G.M3, G.M4, G.M5, G.M6, G.M8)
        faits, depart = {}, 0
        while depart is not None:
            page = ok(
                appel(
                    cap,
                    "m9_apercu_dossier_strategique",
                    {"question": "Expérience", "domaines": ["strategie"], "reference": REF, "depart": depart},
                )
            )
            faits.update(page["faits"])
            depart = page["prochain_depart"]
        # Chiffres RÉELS du propriétaire M5 (rentabilité du chantier) : marge réelle contre marge prévue.
        reelle = _fait(faits, "m5.rentabilite_chantier", ".rentabilite.marge_reelle")
        prevue = _fait(faits, "m5.rentabilite_chantier", ".rentabilite.marge_prevue")
        assert (faits[reelle], faits[prevue]) == ("114.00", "120.00")
        definition = {
            "experience_id": "materiau-alternatif",
            "hypothese": "La marge réelle dépasse la marge prévue avec le matériau alternatif",
            "design": "AVANT_APRES",
            "mesures": [
                {"id": "reelle", "role": "expose", "ref": reelle, "unite": "CAD"},
                {"id": "prevue", "role": "reference", "ref": prevue, "unite": "CAD"},
            ],
            "contre_exemples": [],
            "plafond_budget_cad": "0",
            "duree_jours": 30,
            "limite_risque": "aucune dépense : mesure de chantiers déjà réalisés",
            "porteur": "admin.fictif",
            "plan_retour": "aucune action à défaire : lecture seule des chiffres du propriétaire",
        }
        ok(
            appel(
                cap,
                "m9_definir_experience",
                {"experience": definition, "reference": REF, "horodatage": "2026-10-28T13:00:00Z"},
            )
        )
        sans_cout = ok(
            appel(
                cap,
                "m9_evaluer_experience",
                {"experience_id": "materiau-alternatif", "horodatage": "2026-10-28T13:05:00Z"},
            )
        )
        evaluation = sans_cout["experience"]["evaluation"]
        assert evaluation["budget"]["statut"] == "INCONNU" and evaluation["cadre"]["plafond_budget_cad"] == "0"
        assert evaluation["gain_mesure"] == "-6.00" and evaluation["statut_roi"] == "ROI_NON_CALCULABLE"
        assert evaluation["inference"] == "ASSOCIATION_SEULEMENT" and evaluation["contre_exemples"]["total"] == 1
        assert any("cout" in m for m in evaluation["manques"]) and sans_cout["resultat_ajoute"] is True
        encore = ok(
            appel(
                cap,
                "m9_evaluer_experience",
                {"experience_id": "materiau-alternatif", "horodatage": "2026-10-28T13:06:00Z"},
            )
        )
        assert encore["resultat_ajoute"] is False, "mêmes entrées : aucun doublon"
        # Un coût RÉEL (M5) cité : le ROI se calcule en Decimal, jamais autrement.
        # (Mécanisme : le coût cité est celui que M5 publie pour le chantier ; son sens d'« coût de l'expérience » est
        # l'affirmation de la personne qui l'a cité.)
        cout = [_fait(faits, "m5.rentabilite_chantier", ".rentabilite.cout_total")]
        if cout:
            revise = {
                **definition,
                "plafond_budget_cad": "400.00",
                "mesures": [*definition["mesures"], {"id": "cout", "role": "cout", "ref": cout[0], "unite": "CAD"}],
            }
            ok(
                appel(
                    cap,
                    "m9_definir_experience",
                    {
                        "experience": revise,
                        "reference": REF,
                        "horodatage": "2026-10-28T13:10:00Z",
                        "motif_revision": "coût M5 ajouté",
                    },
                )
            )
            avec = ok(
                appel(
                    cap,
                    "m9_evaluer_experience",
                    {"experience_id": "materiau-alternatif", "horodatage": "2026-10-28T13:11:00Z"},
                )
            )
            assert avec["experience"]["evaluation"]["statut_roi"] == "CALCULE"
            assert avec["experience"]["evaluation"]["roi"] == "-1.0123"  # (-6.00 - 486.00) / 486.00, en Decimal
            budget = avec["experience"]["evaluation"]["budget"]
            assert budget == {"statut": "DEPASSE", "plafond_budget_cad": "400.00", "cout_mesure_cad": "486.00"}
            assert "PLAFOND_BUDGET_DEPASSE" in avec["experience"]["evaluation"]["lacunes"]
            assert avec["experience"]["version"] == 2 and avec["experience"]["versions_total"] == 2
        lues = ok(appel(cap, "m9_lire_experiences", {"connaissance": "2026-10-28T14:00:00Z"}))
        assert lues["experiences"][0]["historique_resultats"], "l'historique des résultats est conservé"
        # source inventée, identité non admin, voie d'agent
        inventee = {
            **definition,
            "experience_id": "x",
            "mesures": [{"id": "a", "role": "expose", "ref": "m8.mesures_chantier#99:p0.nulle", "unite": "CAD"}],
        }
        assert refuse(
            appel(
                cap,
                "m9_definir_experience",
                {"experience": inventee, "reference": REF, "horodatage": "2026-10-28T13:00:00Z"},
            ),
            "REJ-EXPERIENCE-SOURCE",
        )
        vendeur = B.IdentiteAppelante("vendeur.fictif", "employee", source="appareil")
        for identite_appelante in (vendeur, None):
            assert refuse(appel(cap, "m9_lire_experiences", {"connaissance": REF}, identite_appelante))
            assert refuse(
                appel(
                    cap,
                    "m9_evaluer_experience",
                    {"experience_id": "materiau-alternatif", "horodatage": REF},
                    identite_appelante,
                )
            )
        with stockage.transaction() as cnx:
            table = META.tables["registres_maillons"]
            ligne = cnx.execute(select(table).where(table.c.registre == "experiences")).first()
            cnx.execute(
                table.update()
                .where((table.c.registre == "experiences") & (table.c.rang == ligne.rang))
                .values(maillon=ligne.maillon.replace("matériau alternatif", "matériau pirate"))
            )
        assert refuse(appel(cap, "m9_lire_experiences", {"connaissance": REF}), "REJ-EXPERIENCE-CHAINE-INVALIDE")
    finally:
        m2_outils.reinitialiser_registre()
