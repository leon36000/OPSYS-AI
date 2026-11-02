"""Orchestrateur d'estimation avec barème et mesure DÉCLARÉS (M3-C1 et M3-C2) : plage honnête, revue, reçu, rejeu.

Registres EN MÉMOIRE (listes), horloge injectée (``cb.MAINTENANT``), aucun accès au socle. Les outils réels, la base et
les identités sont éprouvés par ``test_outils_bareme.py`` et ``test_bareme_bout_en_bout.py``. Données fictives.
"""

from __future__ import annotations

import json
import sys
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
_SRC = Path(__file__).resolve().parents[1] / "src"  # la source de CE département (la copie jetable des mutations)
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import _commun_bareme as cb  # noqa: E402
from m3_estimation import bareme_registre, contrats, entrees_declarees, estimation, registre  # noqa: E402

SEUILS = {"resolution_minimale": 1000, "eclairage_minimal": 4}


def _contrat():
    return {
        "lead_id": cb.LEAD, "conversation_id": "conv-bareme-001", "type_travaux": cb.SERVICE, "ville": "Quebec",
        "canal": "formulaire_web", "contact": {"nom": "Durand", "telephone": "5145550000"}, "urgence_declaree": False,
    }


def _marqueur():
    return {"readiness_ok": True, "lead_id": cb.LEAD, "hash_tete_registre": "f" * 64,
            "horodatage": "2026-09-28T10:00:00-04:00", "empreinte": "a" * 64}


def _photo(reference=True, largeur=3000):
    return {"photo_id": "p1", "resolution_largeur": largeur, "resolution_hauteur": 2000, "eclairage": 7,
            "angle": "face", "reference_echelle": {"type": "porte", "dimensions_connues": True} if reference else None}


class Monde:
    """Un barème v1 et une mesure déclarés, des registres en mémoire."""

    def __init__(self, **mesure):
        self.bareme, self.mesures, self.estimations = [], [], registre.Registre()
        self.v1 = cb.declarer_ok(self.bareme)
        self.mesure = cb.mesurer_ok(self.mesures, **mesure)

    def declaration(self, *, bareme_ref="v1", mesure_ref="m", maintenant=cb.MAINTENANT):
        bref = cb.ref(self.v1) if bareme_ref == "v1" else bareme_ref
        mref = {"mesure_id": self.mesure["mesure_id"]} if mesure_ref == "m" else mesure_ref
        return entrees_declarees.Declaration(self.bareme, self.mesures, bref, mref, maintenant)

    def estimer(self, *, photos=None, declaration=None, **surcharges):
        parametres = {
            "contrat": _contrat(), "marqueur": _marqueur(), "photos": photos or [_photo()], "seuils": SEUILS,
            "bareme": None, "quantite": None, "plancher_rentable": None, "registre_cible": self.estimations,
            "declaration": declaration or self.declaration(),
        }
        parametres.update(surcharges)
        return estimation.orchestrer_estimation(**parametres)


def _scenario(reponse, nom):
    return next(e for e in reponse["scenarios_prix"]["scenarios"] if e["scenario"] == nom)


def test_l_arrondi_au_cent_est_celui_de_la_moitie_vers_le_haut():
    assert estimation.arrondir_au_cent(0.125) == 0.13   # pile entre 0,12 et 0,13 : HALF_UP, pas « au pair »
    assert estimation.arrondir_au_cent(0.135) == 0.14
    assert estimation.arrondir_au_cent(2.675) == 2.68   # lu depuis sa représentation décimale, pas son codage binaire
    assert estimation.arrondir_au_cent(10.004) == 10.0


def _charge(monde, reponse):
    maillon = next(m for m in monde.estimations.lire() if m["hash_maillon"] == reponse["estimation"]["hash_maillon"])
    return maillon["charge"]


# ------------------------------------------------------------------------------------------------- voie complète
def test_estimation_par_references_rappelle_la_version_et_la_mesure_et_rend_un_recu():
    monde = Monde()
    reponse = monde.estimer()
    assert reponse["etape"] == "complet" and reponse["accepte"] is True
    bloc = reponse["declaration"]
    assert bloc["bareme_ref"] == cb.ref(monde.v1, avec_empreinte=True)
    assert bloc["mesure_ref"] == {
        "mesure_id": "mesure-fictive-1", "revision": 1, "empreinte": monde.mesure["empreinte"]}
    assert (bloc["quantite"], bloc["unite"], bloc["service"]) == ("1200", "pi2", cb.SERVICE)
    assert bloc["statut_prix"] == "retenu" and bloc["revue_humaine_requise"] is False and bloc["motifs_revue"] == []
    assert bloc["plancher_rentable_cad"] == "9000"
    assert reponse["estimation"]["bareme_version"] == "bareme-fictif@v1"
    assert set(reponse["estimation"]) == set(contrats.CHAMPS_ESTIMATION_V1)  # le contrat gelé ne bouge pas


def test_les_references_donnent_exactement_l_intervalle_de_l_ancien_appel_libre_avec_le_meme_bareme():
    monde = Monde()
    compile_, _ = bareme_registre.compiler(monde.v1, cb.SERVICE)
    graine = estimation.graine_stable(compile_, cb.SERVICE, 1200.0)
    libre = estimation.orchestrer_estimation(
        _contrat(), _marqueur(), [_photo()], SEUILS, compile_, 1200.0, 9000.0, registre.Registre(), graine, "0.30",
        None, {"prudent": "0.40", "normal": "0.30", "agressif": "0.15"}, {})
    declaree = monde.estimer()
    assert declaree["estimation"]["intervalle_confiance"] == libre["estimation"]["intervalle_confiance"]
    assert declaree["estimation"]["graine_monte_carlo"] == graine
    assert declaree["prix_recommande"] == libre["prix_recommande"]
    assert declaree["distribution_cout"] == libre["distribution_cout"]
    assert str(_scenario(declaree, "prudent")["taux_marge"]) == "0.40"
    assert _scenario(declaree, "prudent")["source_taux"] == "bareme"  # la source est le barème, pas department.yaml
    assert [str(e["taux_marge"]) for e in libre["scenarios_prix"]["scenarios"]] == ["0.40", "0.30", "0.15"]


def test_le_plancher_les_taux_et_la_quantite_viennent_des_declarations_et_les_arguments_libres_sont_ignores():
    monde = Monde()
    absurde = {"version": "x", "unite": "pi2",
               "postes": {cb.SERVICE: {"cout_unitaire_min": 1.0, "cout_unitaire_max": 1.0}}}
    sans = monde.estimer()
    avec = Monde().estimer(bareme=absurde, quantite=3.0, plancher_rentable=1.0, taux_marge="9", graine=7,
                           taux_scenarios={"prudent": "5", "normal": "5", "agressif": "5"},
                           taux_scenarios_configures={"prudent": "6", "normal": "6", "agressif": "6"},
                           seuils_revue={"minimum_rentable_cad": "1"})
    for cle in ("estimation", "prix_recommande", "scenarios_prix", "distribution_cout", "declaration"):
        assert avec[cle] == sans[cle], cle


def test_la_trace_de_temps_est_qualifiee_seulement_si_le_bareme_declare_la_semantique():
    monde = Monde()
    non_qualifiee = _charge(monde, monde.estimer())["trace_calibration_temps"]
    assert non_qualifiee["semantique_temps"] == "non_qualifiee"
    assert non_qualifiee["bareme_version"] == "bareme-fictif@v1"
    v2 = cb.declarer_ok(monde.bareme, version_attendue=1, date_effet=cb.JOUR_EFFET_V1,
                        lignes=cb.lignes(semantique_temps="duree_ecoulee_intervention"))
    qualifiee = _charge(monde, monde.estimer(declaration=monde.declaration(bareme_ref=cb.ref(v2))))
    assert qualifiee["trace_calibration_temps"]["semantique_temps"] == "duree_ecoulee_intervention"
    assert qualifiee["trace_calibration_temps"]["bareme_version"] == "bareme-fictif@v2"
    # les empreintes de barème compilé diffèrent d'une version à l'autre : une calibration se réfère donc à une version
    assert qualifiee["trace_calibration_temps"]["empreinte_bareme"] != non_qualifiee["empreinte_bareme"]


def test_la_duree_et_les_besoins_en_materiaux_viennent_du_bareme_declare():
    monde = Monde()
    reponse = monde.estimer()
    assert Decimal(reponse["duree_estimee_minutes"]) == Decimal("3000")  # 1200 pi2 x 2,5 min/pi2
    assert Decimal(reponse["declaration"]["duree_estimee_minutes"]) == Decimal("3000")
    besoins = reponse["besoins_materiaux"]
    assert besoins["bareme_version"] == "bareme-fictif@v1"
    assert Decimal(besoins["lignes"][0]["quantite_estimee"]) == Decimal("1320")  # 1200 x 1,1
    assert besoins["lignes"][0]["facteur_perte"] == "0.10"


# ------------------------------------------------------------------------------------------ plage et revue
def test_une_mesure_a_bornes_larges_donne_une_plage_plus_large_et_exige_la_revue():
    etroite = Monde().estimer()
    monde = Monde(valeur="1200", borne_basse="1020", borne_haute="1380", confiance="moyenne")  # largeur 0,30
    large = monde.estimer()
    assert large["accepte"] is True
    bloc = large["declaration"]
    assert bloc["revue_humaine_requise"] is True and bloc["statut_prix"] == "a_revoir"
    assert "bornes larges" in bloc["motifs_revue"][0]
    assert (bloc["quantite_basse"], bloc["quantite"], bloc["quantite_haute"]) == ("1020", "1200", "1380")
    i_large, i_etroit = large["estimation"]["intervalle_confiance"], etroite["estimation"]["intervalle_confiance"]
    assert i_large["borne_basse"] < i_etroit["borne_basse"] and i_large["borne_haute"] > i_etroit["borne_haute"]
    # la plage est l'enveloppe : borne basse à la quantité basse, borne haute à la quantité haute
    ratio_bas = Decimal(str(i_large["borne_basse"])) / Decimal(str(i_etroit["borne_basse"]))
    ratio_haut = Decimal(str(i_large["borne_haute"])) / Decimal(str(i_etroit["borne_haute"]))
    assert abs(ratio_bas - Decimal("0.85")) < Decimal("0.001") and abs(ratio_haut - Decimal("1.15")) < Decimal("0.001")
    assert large["prix_recommande"]["borne_basse"] < etroite["prix_recommande"]["borne_basse"]
    assert large["prix_recommande"]["borne_haute"] > etroite["prix_recommande"]["borne_haute"]
    assert bloc["intervalle_confiance"] == i_large  # le reçu garde l'enveloppe


def test_mesure_suffisante_et_etroite_est_retenue_sans_revue():
    monde = Monde(valeur="1200", borne_basse="1150", borne_haute="1250", confiance="moyenne")  # largeur 0,083
    bloc = monde.estimer()["declaration"]
    assert bloc["revue_humaine_requise"] is False and bloc["statut_prix"] == "retenu"


def test_confiance_faible_exige_la_revue_meme_avec_une_mesure_ponctuelle():
    bloc = Monde(confiance="faible").estimer()["declaration"]
    assert bloc["revue_humaine_requise"] is True and bloc["motifs_revue"] == ["confiance déclarée faible"]


def test_mesure_trop_large_pour_un_prix_refuse_avant_tout_calcul_et_n_ecrit_rien():
    monde = Monde(valeur="1200", borne_basse="500", borne_haute="1900")
    reponse = monde.estimer()
    assert reponse["accepte"] is False and reponse["etape"] == "mesure"
    assert reponse["verdict"]["code"] == "REJ-MESURE-INSUFFISANTE"
    assert list(monde.estimations.lire()) == []


# --------------------------------------------------------------------------------------------------- refus
def test_sans_bareme_declare_le_refus_dit_quoi_declarer_et_rien_n_est_ecrit():
    monde = Monde()
    reponse = monde.estimer(declaration=entrees_declarees.Declaration(
        [], monde.mesures, {"bareme_id": "bareme-fictif", "version": 1}, {"mesure_id": "mesure-fictive-1"},
        cb.MAINTENANT))
    assert (reponse["etape"], reponse["accepte"]) == ("bareme", False)
    assert reponse["verdict"]["code"] == "REJ-BAREME-INTROUVABLE"
    assert "m3_declarer_bareme" in reponse["verdict"]["detail"]
    assert list(monde.estimations.lire()) == []


def test_une_reference_perimee_est_refusee_et_la_version_courante_acceptee():
    monde = Monde()
    v2 = cb.declarer_ok(monde.bareme, version_attendue=1, date_effet=cb.JOUR_EFFET_V2)
    apres = monde.declaration(maintenant=cb.APRES_V2)
    reponse = monde.estimer(declaration=apres)
    assert reponse["accepte"] is False and reponse["verdict"]["code"] == "REJ-BAREME-PERIME"
    ok = monde.estimer(declaration=monde.declaration(bareme_ref=cb.ref(v2), maintenant=cb.APRES_V2))
    assert ok["accepte"] is True and ok["estimation"]["bareme_version"] == "bareme-fictif@v2"


def test_sans_mesure_la_quantite_n_est_pas_devinee():
    monde = Monde()
    reponse = monde.estimer(declaration=monde.declaration(mesure_ref=None))
    assert (reponse["etape"], reponse["verdict"]["code"]) == ("mesure", "REJ-MESURE-REQUISE")
    assert list(monde.estimations.lire()) == []


def test_la_mesure_d_un_autre_lead_est_refusee():
    monde = Monde(lead_id="lead-autre-chantier")
    reponse = monde.estimer()
    assert (reponse["etape"], reponse["verdict"]["code"]) == ("mesure", "REJ-MESURE-AUTRE-LEAD")


def test_la_mesure_dans_une_autre_unite_est_refusee():
    reponse = Monde(unite="m2").estimer()
    assert (reponse["etape"], reponse["verdict"]["code"]) == ("mesure", "REJ-MESURE-UNITE")


def test_un_service_non_couvert_par_le_bareme_dit_quoi_declarer():
    monde = Monde()
    contrat = {**_contrat(), "type_travaux": "extension"}
    reponse = monde.estimer(contrat=contrat)
    assert (reponse["etape"], reponse["verdict"]["code"]) == ("bareme", "REJ-BAREME-INCOMPLET")
    assert "extension" in reponse["verdict"]["detail"]


def test_un_bareme_sans_plancher_declare_n_en_invente_pas():
    monde = Monde()
    parametres = deepcopy(cb.PARAMETRES)
    del parametres["plancher_rentable_cad"]
    v2 = cb.declarer_ok(monde.bareme, version_attendue=1, parametres=parametres, date_effet=cb.JOUR_EFFET_V1)
    reponse = monde.estimer(declaration=monde.declaration(bareme_ref=cb.ref(v2)))
    assert (reponse["etape"], reponse["verdict"]["code"]) == ("bareme", "REJ-BAREME-INCOMPLET")
    assert "plancher" in reponse["verdict"]["detail"]


def test_bareme_sans_taux_de_marge_donne_un_cout_sans_prix_et_le_dit():
    monde = Monde()
    parametres = {k: v for k, v in deepcopy(cb.PARAMETRES).items() if k != "taux_marge"}
    v2 = cb.declarer_ok(monde.bareme, version_attendue=1, parametres=parametres, date_effet=cb.JOUR_EFFET_V1)
    reponse = monde.estimer(declaration=monde.declaration(bareme_ref=cb.ref(v2)))
    assert reponse["accepte"] is True and reponse["prix_recommande"] is None
    verdict = _scenario(reponse, "normal")["verdict"]
    assert verdict["code"] == "REJ-SCENARIOS-TAUX-ABSENT" and "parametres.taux_marge.normal" in verdict["detail"]
    assert any("taux_marge" in note for note in reponse["elements_manquants"])


# --------------------------------------------------------------------------------------- plancher rentable
def test_le_plancher_declare_leve_l_alerte_sous_le_plancher_et_pas_a_l_egalite():
    # coût fixe (min = mode = max) : l'intervalle vaut 10,00 $ x 1 200 pi2 = 12 000,00 $ quelle que soit la graine
    fixe = cb.lignes(cout_unitaire_min="10.00", cout_unitaire_mode="10.00", cout_unitaire_max="10.00")
    monde = Monde()
    pile = deepcopy(cb.PARAMETRES)
    pile["plancher_rentable_cad"] = "12000.00"
    v2 = cb.declarer_ok(monde.bareme, version_attendue=1, lignes=fixe, parametres=pile, date_effet=cb.JOUR_EFFET_V1)
    egal = monde.estimer(declaration=monde.declaration(bareme_ref=cb.ref(v2)))
    assert egal["estimation"]["intervalle_confiance"]["borne_basse"] == 12000.0
    assert egal["estimation"]["alerte_plancher"] is False
    au_dessus = deepcopy(cb.PARAMETRES)
    au_dessus["plancher_rentable_cad"] = "12000.01"
    v3 = cb.declarer_ok(monde.bareme, version_attendue=2, lignes=fixe, parametres=au_dessus,
                        date_effet=cb.JOUR_EFFET_V1)
    alerte = monde.estimer(declaration=monde.declaration(bareme_ref=cb.ref(v3)))
    assert alerte["estimation"]["alerte_plancher"] is True
    assert alerte["estimation"]["verdict_estimation"] == contrats.VERDICT_PLANCHER_RENTABILITE_FRANCHI
    assert Monde().estimer()["estimation"]["alerte_plancher"] is False  # plancher 9 000 $ sous la borne basse


def test_le_minimum_rentable_du_bareme_alimente_l_alerte_rouge_des_scenarios():
    monde = Monde()
    parametres = deepcopy(cb.PARAMETRES)
    parametres["seuils_revue"] = {"minimum_rentable_cad": "999999"}
    v2 = cb.declarer_ok(monde.bareme, version_attendue=1, parametres=parametres, date_effet=cb.JOUR_EFFET_V1)
    reponse = monde.estimer(declaration=monde.declaration(bareme_ref=cb.ref(v2)))
    assert _scenario(reponse, "normal")["alerte_rouge"] is True
    assert reponse["scenarios_prix"]["alerte_rouge"] is True


# ------------------------------------------------------------------------------------------ photos et registre
def test_photos_insuffisantes_bloquent_le_prix_meme_avec_barème_et_mesure_declares():
    monde = Monde()
    reponse = monde.estimer(photos=[_photo(reference=False, largeur=200)])
    assert reponse["accepte"] is True and reponse["estimation"]["prix_bloque"] is True
    assert reponse["estimation"]["intervalle_confiance"]["borne_basse"] is None
    assert reponse["declaration"]["statut_prix"] == "bloque" and reponse["declaration"]["intervalle_confiance"] is None
    assert reponse["prix_recommande"] is None and reponse["signal_relance_m2"] is not None


def test_la_charge_au_registre_garde_le_recu_et_les_faits_de_revue_v2():
    monde = Monde(valeur="1200", borne_basse="1020", borne_haute="1380")
    reponse = monde.estimer()
    charge = _charge(monde, reponse)
    assert charge["declaration"] == reponse["declaration"]
    assert charge["faits_revue"]["version"] == "m3.faits-revue/v2"
    assert charge["faits_revue"]["mesure_a_bornes_larges"] is True
    assert monde.estimations.valider_chaine()[0] is True


def test_ni_la_charge_ni_le_recu_ne_portent_de_donnee_personnelle():
    monde = Monde()
    reponse = monde.estimer()
    texte = json.dumps([_charge(monde, reponse), reponse["declaration"]], ensure_ascii=False, default=str)
    for interdit in ("Durand", "5145550000", cb.ADMIN["personne"], cb.PROPRIO["personne"], "Feuille de prix"):
        assert interdit not in texte, interdit


def test_sans_declaration_la_charge_reste_celle_d_avant():
    registre_libre = registre.Registre()
    libre = estimation.orchestrer_estimation(
        _contrat(), _marqueur(), [_photo()], SEUILS,
        {"version": "2026.1", "unite": "pi2",
         "postes": {cb.SERVICE: {"cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0}}},
        1200, 9000, registre_libre, 42)
    charge = next(iter(registre_libre.lire()))["charge"]
    assert "declaration" not in charge and "declaration" not in libre
    assert charge["faits_revue"]["version"] == "m3.faits-revue/v1"
    assert "mesure_a_bornes_larges" not in charge["faits_revue"]


# ------------------------------------------------------------------------------------------------- le rejeu
def test_le_rejeu_refait_le_calcul_et_confirme_l_intervalle_garde():
    monde = Monde(valeur="1200", borne_basse="1020", borne_haute="1380")
    charge = _charge(monde, monde.estimer())
    rapport, verdict = entrees_declarees.rejouer(charge, monde.bareme, monde.mesures, cb.MAINTENANT)
    assert verdict is None and rapport["identique"] is True and rapport["ecarts"] == []
    assert rapport["recalcule"] == rapport["stocke"]
    assert rapport["bareme_toujours_en_vigueur"] is True


def test_apres_la_version_2_et_une_revision_de_mesure_l_ancienne_estimation_se_rejoue_avec_la_version_1():
    monde = Monde(valeur="1200", borne_basse="1020", borne_haute="1380")
    reponse = monde.estimer()
    charge = _charge(monde, reponse)
    cb.declarer_ok(monde.bareme, version_attendue=1, date_effet=cb.JOUR_EFFET_V2,
                   lignes=cb.lignes(cout_unitaire_min="20.00", cout_unitaire_mode="22.00", cout_unitaire_max="30.00"))
    cb.mesurer_ok(monde.mesures, revision_attendue=1, valeur="2000", borne_basse="2000", borne_haute="2000",
                  horodatage="2026-11-03T10:00:00+00:00")
    rapport, verdict = entrees_declarees.rejouer(charge, monde.bareme, monde.mesures, cb.APRES_V2)
    assert verdict is None and rapport["identique"] is True
    assert rapport["bareme_ref"]["version"] == 1 and rapport["mesure_ref"]["revision"] == 1
    assert rapport["bareme_toujours_en_vigueur"] is False  # la version 1 est périmée aujourd'hui, le rejeu reste exact
    # et une nouvelle estimation avec la version 1 est refusée
    refus = monde.estimer(declaration=monde.declaration(maintenant=cb.APRES_V2))
    assert refus["verdict"]["code"] == "REJ-BAREME-PERIME"


def test_un_ecart_entre_l_intervalle_garde_et_le_recalcul_est_dit():
    monde = Monde()
    charge = _charge(monde, monde.estimer())
    falsifiee = deepcopy(charge)
    falsifiee["declaration"]["intervalle_confiance"]["borne_haute"] += 1.0
    rapport, verdict = entrees_declarees.rejouer(falsifiee, monde.bareme, monde.mesures, cb.MAINTENANT)
    assert verdict is None and rapport["identique"] is False and rapport["ecarts"] == ["borne_haute"]
    falsifiee = deepcopy(charge)
    falsifiee["declaration"]["quantite"] = "1"
    rapport, _ = entrees_declarees.rejouer(falsifiee, monde.bareme, monde.mesures, cb.MAINTENANT)
    assert "quantite" in rapport["ecarts"]


def test_un_barème_altere_empeche_le_rejeu():
    monde = Monde()
    charge = _charge(monde, monde.estimer())
    monde.bareme[0]["lignes"][0]["cout_unitaire_max"] = "1.00"
    _, verdict = entrees_declarees.rejouer(charge, monde.bareme, monde.mesures, cb.MAINTENANT)
    assert verdict["code"] == "REJ-BAREME-ALTERE"


def test_rien_a_rejouer_pour_un_prix_bloque_ou_une_estimation_sans_declaration():
    monde = Monde()
    bloquee = _charge(monde, monde.estimer(photos=[_photo(reference=False, largeur=200)]))
    _, verdict = entrees_declarees.rejouer(bloquee, monde.bareme, monde.mesures, cb.MAINTENANT)
    assert verdict["code"] == "REJ-REJEU-IMPOSSIBLE" and "bloqué" in verdict["detail"]
    for charge in ({"devis_id": "x"}, None, {"declaration": {"version": "autre"}}):
        _, verdict = entrees_declarees.rejouer(charge, monde.bareme, monde.mesures, cb.MAINTENANT)
        assert verdict["code"] == "REJ-REJEU-IMPOSSIBLE"


def test_deux_calculs_avec_les_memes_references_donnent_les_memes_octets():
    a, b = Monde(), Monde()
    ra, rb = a.estimer(), b.estimer()
    assert ra["estimation"]["hash_maillon"] == rb["estimation"]["hash_maillon"]
    assert ra["declaration"] == rb["declaration"]


@pytest.mark.parametrize("quantite_basse, quantite_haute", [("1200", "1200"), ("1199", "1201")])
def test_l_enveloppe_contient_toujours_l_intervalle_a_la_valeur_retenue(quantite_basse, quantite_haute):
    compile_, _ = bareme_registre.compiler(cb.declarer_ok([]), cb.SERVICE)
    nominal, _ = estimation.enveloppe_de_mesure(compile_, cb.SERVICE, 1200.0, 1200.0, 42, 0.9)
    enveloppe, _ = estimation.enveloppe_de_mesure(
        compile_, cb.SERVICE, float(quantite_basse), float(quantite_haute), 42, 0.9)
    assert enveloppe["borne_basse"] <= nominal["borne_basse"] and enveloppe["borne_haute"] >= nominal["borne_haute"]
    assert enveloppe["niveau"] == nominal["niveau"] == 0.9
