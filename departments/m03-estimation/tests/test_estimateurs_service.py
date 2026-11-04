"""Estimateurs par service (M3.8b) : quantités déclarées, calcul Decimal, reçu, refus qui disent quoi déclarer.

Modules purs, horloge INJECTÉE (``MAINTENANT`` et ses voisins) ; aucune valeur réelle : les coefficients et les
mesures sont FICTIFS et DÉCLARÉS dans le barème ou par une personne.
"""

from __future__ import annotations

import sys
from copy import deepcopy
from decimal import Decimal
from pathlib import Path

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
_SRC = Path(__file__).resolve().parents[1] / "src"  # la source de CE département (la copie jetable des mutations)
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import _commun_bareme as cb  # noqa: E402
import _commun_estimateurs as ce  # noqa: E402
from m3_estimation import bareme_registre, estimateurs_service  # noqa: E402


def _version_estimee():
    """La version déclarée et un journal de MESURES distinct (deux registres séparés, comme en production)."""
    return ce.declarer_ok([]), []


def _estimer(version, service, mesures, *, lead_id=ce.LEAD, maintenant=ce.MAINTENANT):
    return estimateurs_service.estimer(
        version=version, service=service, lead_id=lead_id, mesures=mesures, maintenant=maintenant
    )


def _decimal(texte):
    return Decimal(texte)


# ---------------------------------------------------------------------------------------- calcul par service
def test_gouttieres_somme_les_composantes_avec_conversion_et_chiffre_au_cent():
    version, journal = _version_estimee()
    mesures = ce.mesures_gouttieres(journal)
    resultat, verdict = _estimer(version, ce.GOUTTIERES, mesures)
    assert verdict is None
    quantite = resultat["quantite"]
    assert quantite == {"basse": "152", "retenue": "155", "haute": "158", "unite": "pi.lin"}
    assert resultat["couts"] == {
        "min_cad": "1444.00", "probable_cad": "1705.00", "max_cad": "2054.00",
        "unite_monetaire": "CAD", "arrondi": "ROUND_HALF_UP",
    }
    assert resultat["duree_minutes"] == "310"
    assert resultat["prix_recommande_cad"] == "2216.50"
    assert resultat["statut"] == "retenu" and resultat["motifs_revue"] == []
    recu = resultat["recu"]
    assert recu["formule"] == estimateurs_service.FORMULE
    assert [c["grandeur"] for c in recu["composantes"]] == [
        "longueur_gouttiere", "longueur_descente", "coin"]
    coin = recu["composantes"][2]
    assert coin["coefficient"] == "1" and coin["facteur_conversion"] == "2.5"
    assert coin["contribution"] == "15" and coin["contribution_basse"] == "15"
    assert recu["quantite"]["minimum_declare"] == "20" and recu["quantite"]["minimum_applique"] is False


def test_revetement_soustrait_les_ouvertures_et_l_intervalle_prend_la_borne_opposee():
    version, journal = _version_estimee()
    resultat, verdict = _estimer(version, ce.REVETEMENT, ce.mesures_revetement(journal))
    assert verdict is None
    assert resultat["quantite"] == {"basse": "1045", "retenue": "1100", "haute": "1155", "unite": "pi2"}
    assert resultat["couts"] == {
        "min_cad": "8360.00", "probable_cad": "11000.00", "max_cad": "16170.00",
        "unite_monetaire": "CAD", "arrondi": "ROUND_HALF_UP",
    }
    assert resultat["prix_recommande_cad"] == "14300.00"
    # la mesure de 1200 pi2 a une largeur relative de 0,0833 : au-delà du seuil de revue (0,05), prix permis
    assert resultat["statut"] == "a_revoir"
    assert any("bornes larges" in motif for motif in resultat["motifs_revue"])


def test_la_quantite_minimum_declaree_s_applique_aux_trois_bornes():
    version, journal = _version_estimee()
    mesure = ce.mesurer_ok(journal, mesure_id="mes-reparation", grandeur="heures_reparation", valeur="1",
                           unite="heure", borne_basse="1", borne_haute="1", service=ce.REPARATION)
    resultat, verdict = _estimer(version, ce.REPARATION, [mesure])
    assert verdict is None
    assert resultat["quantite"] == {"basse": "1.5", "retenue": "1.5", "haute": "1.5", "unite": "heure"}
    assert resultat["recu"]["quantite"]["minimum_applique"] is True
    assert resultat["couts"]["probable_cad"] == "112.50"
    assert resultat["duree_minutes"] == "90"  # 1,5 h x 60 min, exactement le minimum déclaré


def test_le_temps_minimum_declare_s_applique_quand_la_duree_calculee_est_plus_courte():
    version, journal = _version_estimee()
    modifiee = deepcopy(version)
    for ligne in modifiee["lignes"]:
        if ligne["service"] == ce.REPARATION:
            ligne["duree_minutes_par_unite"] = "10"
    mesure = ce.mesurer_ok(journal, mesure_id="mes-reparation-2", grandeur="heures_reparation", valeur="1",
                           unite="heure", borne_basse="1", borne_haute="1", service=ce.REPARATION)
    resultat, verdict = _estimer(modifiee, ce.REPARATION, [mesure])
    assert verdict is None
    assert resultat["duree_minutes"] == "90"
    assert resultat["recu"]["duree"]["minimum_applique"] is True


def test_l_arrondi_du_cent_est_half_up_et_non_half_even():
    version, journal = _version_estimee()
    modifiee = deepcopy(version)
    for ligne in modifiee["lignes"]:
        if ligne["service"] == ce.SOFFITE:
            ligne.update({"cout_unitaire_min": "10.005", "cout_unitaire_mode": "10.005",
                          "cout_unitaire_max": "10.005", "duree_minutes_par_unite": None})
            ligne.pop("duree_minutes_par_unite")
    modifiee["parametres"]["estimateurs"][ce.SOFFITE]["composantes"] = [
        ce._composante("longueur_soffite", "pi.lin", "1")]
    mesure = ce.mesurer_ok(journal, mesure_id="mes-soffite", grandeur="longueur_soffite", valeur="1",
                           unite="pi.lin", borne_basse="1", borne_haute="1", service=ce.SOFFITE)
    resultat, verdict = _estimer(modifiee, ce.SOFFITE, [mesure])
    assert verdict is None
    # 1 x 10,005 = 10,005 : ROUND_HALF_UP donne 10,01 (ROUND_HALF_EVEN donnerait 10,00)
    assert resultat["couts"]["probable_cad"] == "10.01"
    assert resultat["couts"]["min_cad"] == "10.01" and resultat["couts"]["max_cad"] == "10.01"
    assert resultat["quantite"]["retenue"] == "1"


def test_un_mode_sans_prix_ni_taux_declare_laisse_probable_et_prix_a_null_avec_ce_qu_il_faut_declarer():
    version, journal = _version_estimee()
    modifiee = deepcopy(version)
    for ligne in modifiee["lignes"]:
        if ligne["service"] == ce.GOUTTIERES:
            ligne.pop("cout_unitaire_mode")
    modifiee["parametres"].pop("taux_marge")
    resultat, verdict = _estimer(modifiee, ce.GOUTTIERES, ce.mesures_gouttieres(journal))
    assert verdict is None
    assert resultat["couts"]["min_cad"] == "1444.00" and resultat["couts"]["max_cad"] == "2054.00"
    assert resultat["couts"]["probable_cad"] is None
    assert resultat["prix_recommande_cad"] is None
    assert any("cout_unitaire_mode" in manque for manque in resultat["elements_manquants"])
    assert any("taux_marge.normal" in manque for manque in resultat["elements_manquants"])


# ---------------------------------------------------------------------------------------- reçu
def test_le_recu_se_verifie_par_recalcul_et_detecte_un_montant_ou_un_coefficient_altere():
    version, journal = _version_estimee()
    resultat, verdict = _estimer(version, ce.GOUTTIERES, ce.mesures_gouttieres(journal))
    assert verdict is None
    recu = resultat["recu"]
    assert estimateurs_service.verifier_recu(recu) == (True, None)

    altere = deepcopy(recu)
    altere["quantite"]["retenue"] = "156"
    intact, verdict = estimateurs_service.verifier_recu(altere)
    assert intact is False and ce.code(verdict) == "REJ-ESTIMATEUR-RECU-ALTERE"

    altere = deepcopy(recu)
    altere["composantes"][2]["coefficient"] = "3"
    intact, verdict = estimateurs_service.verifier_recu(altere)
    assert intact is False and ce.code(verdict) == "REJ-ESTIMATEUR-RECU-ALTERE"
    assert "coin" in verdict["detail"]


def test_le_recu_porte_les_references_exactes_des_mesures_et_du_bareme():
    version, journal = _version_estimee()
    mesures = ce.mesures_gouttieres(journal)
    resultat, _ = _estimer(version, ce.GOUTTIERES, mesures)
    recu = resultat["recu"]
    assert recu["bareme_ref"] == {
        "bareme_id": version["bareme_id"], "version": version["version"], "empreinte": version["empreinte"]}
    for composante, mesure in zip(recu["composantes"], mesures, strict=True):
        assert composante["mesure_id"] == mesure["mesure_id"]
        assert composante["revision"] == mesure["revision"]
        assert composante["empreinte"] == mesure["empreinte"]
    assert recu["lead_id"] == ce.LEAD and recu["service"] == ce.GOUTTIERES
    assert len(recu["empreinte"]) == 64


# ---------------------------------------------------------------------------------------- refus fail-closed
def test_sans_estimateur_declare_le_refus_dit_la_cle_et_la_forme_a_declarer():
    journal = []
    version = cb.declarer_ok(journal)
    resultat, verdict = _estimer(version, "ravalement", [])
    assert resultat is None
    assert ce.code(verdict) == "REJ-ESTIMATEUR-NON-DECLARE"
    detail = verdict["detail"]
    assert "parametres.estimateurs.ravalement" in detail
    for attendu in ("unite_ouvrage", "composantes", "coefficient", "source_ecrite"):
        assert attendu in detail
    assert "fictif" not in detail.replace("bareme-fictif", "") and "10.00" not in detail  # aucun exemple chiffré


def test_mesures_manquantes_sont_listees_ensemble_avec_le_geste_de_declaration():
    version, journal = _version_estimee()
    mesures = ce.mesures_gouttieres(journal)
    partiel = [mesures[0]]  # il manque la descente et le coin
    resultat, verdict = _estimer(version, ce.GOUTTIERES, partiel)
    assert resultat is None
    assert ce.code(verdict) == "REJ-ESTIMATEUR-MESURES-MANQUANTES"
    assert "longueur_descente" in verdict["detail"] and "coin" in verdict["detail"]
    assert "m3_declarer_mesure" in verdict["detail"]


def test_une_mesure_non_prevue_est_refusee_sans_recopier_un_texte_hote():
    version, journal = _version_estimee()
    mesures = ce.mesures_gouttieres(journal)
    hostile = ce.mesurer_ok(journal, mesure_id="mes-hostile", grandeur="<script>alert(1)</script>",
                            valeur="1", unite="pi.lin", borne_basse="1", borne_haute="1", service=ce.GOUTTIERES)
    resultat, verdict = _estimer(version, ce.GOUTTIERES, [*mesures, hostile])
    assert resultat is None
    assert ce.code(verdict) == "REJ-ESTIMATEUR-MESURE-NON-PREVUE"
    assert "<script>" not in verdict["detail"]
    assert "longueur_gouttiere" in verdict["detail"]  # les grandeurs admises sont nommées


def test_deux_mesures_pour_la_meme_grandeur_sont_ambigues_et_refusees():
    version, journal = _version_estimee()
    mesures = ce.mesures_gouttieres(journal)
    doublon = ce.mesurer_ok(journal, mesure_id="mes-gouttiere-bis", grandeur="longueur_gouttiere", valeur="90",
                            unite="pi.lin", borne_basse="90", borne_haute="90", service=ce.GOUTTIERES)
    resultat, verdict = _estimer(version, ce.GOUTTIERES, [*mesures, doublon])
    assert resultat is None
    assert ce.code(verdict) == "REJ-ESTIMATEUR-MESURE-AMBIGUE"
    assert "longueur_gouttiere" in verdict["detail"]


def test_l_unite_d_une_composante_est_celle_declaree_pas_une_conversion_devinee():
    version, journal = _version_estimee()
    mesures = ce.mesures_gouttieres(journal)
    mauvaise = ce.mesurer_ok(journal, mesure_id="mes-coin-pi", grandeur="coin", valeur="6", unite="pi.lin",
                             borne_basse="6", borne_haute="6", service=ce.GOUTTIERES)
    resultat, verdict = _estimer(version, ce.GOUTTIERES, [mesures[0], mesures[1], mauvaise])
    assert resultat is None
    assert ce.code(verdict) == "REJ-MESURE-UNITE"
    assert "unite" in verdict["detail"]


def test_une_mesure_perimee_bloque_le_calcul_avec_la_date_et_la_validite():
    version, journal = _version_estimee()
    vieille = ce.mesurer_ok(journal, mesure_id="mes-vieille", grandeur="longueur_gouttiere", valeur="100",
                            unite="pi.lin", borne_basse="100", borne_haute="100", service=ce.GOUTTIERES,
                            mesure_le="2026-09-01T09:00:00+00:00")
    descente = ce.mesurer_ok(journal, mesure_id="mes-descente-ok", grandeur="longueur_descente", valeur="40",
                             unite="pi.lin", borne_basse="40", borne_haute="40", service=ce.GOUTTIERES)
    coin = ce.mesurer_ok(journal, mesure_id="mes-coin-ok", grandeur="coin", valeur="6", unite="unite",
                         borne_basse="6", borne_haute="6", service=ce.GOUTTIERES)
    resultat, verdict = _estimer(version, ce.GOUTTIERES, [vieille, descente, coin])
    assert resultat is None
    assert ce.code(verdict) == "REJ-MESURE-PERIMEE"
    assert "30 jours" in verdict["detail"]


def test_une_mesure_trop_large_pour_un_prix_est_refusee_avec_le_seuil_declare():
    version, journal = _version_estimee()
    large = ce.mesurer_ok(journal, mesure_id="mes-large", grandeur="longueur_gouttiere", valeur="100",
                          unite="pi.lin", borne_basse="60", borne_haute="140", service=ce.GOUTTIERES)
    descente = ce.mesurer_ok(journal, mesure_id="mes-descente-large", grandeur="longueur_descente", valeur="40",
                             unite="pi.lin", borne_basse="40", borne_haute="40", service=ce.GOUTTIERES)
    coin = ce.mesurer_ok(journal, mesure_id="mes-coin-large", grandeur="coin", valeur="6", unite="unite",
                         borne_basse="6", borne_haute="6", service=ce.GOUTTIERES)
    resultat, verdict = _estimer(version, ce.GOUTTIERES, [large, descente, coin])
    assert resultat is None
    assert ce.code(verdict) == "REJ-MESURE-INSUFFISANTE"
    assert "0.50" in verdict["detail"]


def test_une_quantite_nulle_ou_negative_est_refusee_jamais_arrondie_a_zero():
    version, journal = _version_estimee()
    surface = ce.mesurer_ok(journal, mesure_id="mes-surface-nue", grandeur="surface_brute", valeur="100",
                            unite="pi2", borne_basse="90", borne_haute="110", service=ce.REVETEMENT)
    ouverture = ce.mesurer_ok(journal, mesure_id="mes-ouverture-grande", grandeur="ouverture", valeur="150",
                              unite="pi2", borne_basse="145", borne_haute="155", service=ce.REVETEMENT)
    resultat, verdict = _estimer(version, ce.REVETEMENT, [surface, ouverture])
    assert resultat is None
    assert ce.code(verdict) == "REJ-ESTIMATEUR-QUANTITE-NON-POSITIVE"
    assert "coefficients" in verdict["detail"] and "mesures" in verdict["detail"]


def test_une_borne_basse_de_cout_non_positive_est_refusee_sans_la_ramener_a_zero():
    version, journal = _version_estimee()
    surface = ce.mesurer_ok(journal, mesure_id="mes-surface-limite", grandeur="surface_brute", valeur="100",
                            unite="pi2", borne_basse="90", borne_haute="110", service=ce.REVETEMENT)
    ouverture = ce.mesurer_ok(journal, mesure_id="mes-ouverture-limite", grandeur="ouverture", valeur="99.5",
                              unite="pi2", borne_basse="99.5", borne_haute="99.5", service=ce.REVETEMENT)
    resultat, verdict = _estimer(version, ce.REVETEMENT, [surface, ouverture])
    assert resultat is None
    assert ce.code(verdict) == "REJ-ESTIMATEUR-BORNES-NON-POSITIVES"
    assert "-9.5" in verdict["detail"]


# ---------------------------------------------------------------------------------------- déclaration du barème
def _declarer_avec(parametres=None, lignes=None):
    journal = []
    resultat, verdict = ce.declarer(
        journal, parametres=parametres if parametres is not None else ce.parametres(),
        lignes=lignes if lignes is not None else ce.lignes())
    return (resultat["version"] if resultat is not None else None), verdict


def _invalide(parametres=None, lignes=None):
    resultat, verdict = _declarer_avec(parametres=parametres, lignes=lignes)
    assert resultat is None
    assert ce.code(verdict) == "REJ-BAREME-INVALIDE"
    return verdict["detail"]


def test_un_estimateur_valide_est_publie_avec_ses_composantes_et_ses_sources():
    version, verdict = _declarer_avec()
    assert verdict is None
    estimateur = version["parametres"]["estimateurs"][ce.GOUTTIERES]
    assert estimateur["unite_ouvrage"] == "pi.lin"
    assert all(composante["source_ecrite"] for composante in estimateur["composantes"])
    assert version["parametres"]["estimateurs"][ce.REVETEMENT]["composantes"][1]["coefficient"] == "-1"


def test_un_estimateur_sans_ligne_d_ouvrage_pour_son_service_est_refuse():
    detail = _invalide(lignes=[ligne for ligne in ce.lignes() if ligne["service"] != ce.SOFFITE])
    assert ce.SOFFITE in detail and "ouvrage" in detail


def test_l_unite_de_l_estimateur_doit_etre_celle_de_la_ligne_d_ouvrage():
    parametres = ce.parametres()
    estimateur = parametres["estimateurs"][ce.GOUTTIERES]
    estimateur["unite_ouvrage"] = "pi2"
    for composante in estimateur["composantes"]:
        composante["unite"] = "pi2"
        composante.pop("facteur_conversion", None)
    detail = _invalide(parametres=parametres)
    assert "unite_ouvrage" in detail and ce.GOUTTIERES in detail


def test_une_composante_d_une_autre_unite_exige_un_facteur_de_conversion():
    parametres = ce.parametres()
    parametres["estimateurs"][ce.GOUTTIERES]["composantes"][2].pop("facteur_conversion")
    detail = _invalide(parametres=parametres)
    assert "facteur_conversion" in detail and "coin" in detail


def test_un_facteur_de_conversion_avec_la_meme_unite_est_refuse_comme_une_ambiguite():
    parametres = ce.parametres()
    parametres["estimateurs"][ce.GOUTTIERES]["composantes"][0]["facteur_conversion"] = "2"
    detail = _invalide(parametres=parametres)
    assert "facteur_conversion" in detail


def test_un_coefficient_nul_ou_non_decimal_est_refuse():
    parametres = ce.parametres()
    parametres["estimateurs"][ce.GOUTTIERES]["composantes"][0]["coefficient"] = "0"
    detail = _invalide(parametres=parametres)
    assert "coefficient" in detail

    parametres = ce.parametres()
    parametres["estimateurs"][ce.GOUTTIERES]["composantes"][0]["coefficient"] = "1,5"
    detail = _invalide(parametres=parametres)
    assert "coefficient" in detail


def test_une_grandeur_en_double_dans_le_meme_estimateur_est_refusee():
    parametres = ce.parametres()
    parametres["estimateurs"][ce.GOUTTIERES]["composantes"].append(
        ce._composante("longueur_gouttiere", "pi.lin", "1"))
    detail = _invalide(parametres=parametres)
    assert "longueur_gouttiere" in detail


def test_une_cle_inconnue_dans_une_composante_est_refusee():
    parametres = ce.parametres()
    parametres["estimateurs"][ce.GOUTTIERES]["composantes"][0]["prix_unitaire"] = "12"
    detail = _invalide(parametres=parametres)
    assert "prix_unitaire" in detail


def test_une_composante_sans_source_ecrite_est_refusee():
    parametres = ce.parametres()
    parametres["estimateurs"][ce.GOUTTIERES]["composantes"][0].pop("source_ecrite")
    detail = _invalide(parametres=parametres)
    assert "source_ecrite" in detail


def test_quantite_minimum_et_temps_minimum_doivent_etre_strictement_positifs():
    parametres = ce.parametres()
    parametres["estimateurs"][ce.GOUTTIERES]["quantite_minimum"] = "0"
    assert "quantite_minimum" in _invalide(parametres=parametres)

    parametres = ce.parametres()
    parametres["estimateurs"][ce.GOUTTIERES]["temps_minimum_minutes"] = "-5"
    assert "temps_minimum_minutes" in _invalide(parametres=parametres)


def test_un_estimateur_ne_change_pas_le_bareme_compile_du_moteur():
    version, _ = _declarer_avec()
    compile, verdict = bareme_registre.compiler(version, ce.GOUTTIERES)
    assert verdict is None
    assert compile["unite"] == "pi.lin"
    assert compile["version"] == f"{version['bareme_id']}@v{version['version']}"
    assert compile["postes"][ce.GOUTTIERES]["cout_unitaire_min"] == 9.5


def test_les_mesures_doivent_appartenir_au_meme_lead_que_l_estimation():
    version, journal = _version_estimee()
    mesures = ce.mesures_gouttieres(journal, lead_id=ce.LEAD)
    resultat, verdict = _estimer(version, ce.GOUTTIERES, mesures, lead_id="lead-autre")
    assert resultat is None
    assert ce.code(verdict) == "REJ-MESURE-AUTRE-LEAD"
    assert "autre lead" in verdict["detail"]


def test_une_mesure_d_un_autre_service_est_refusee():
    version, journal = _version_estimee()
    mesures = ce.mesures_gouttieres(journal)
    etrangere = ce.mesurer_ok(journal, mesure_id="mes-etrangere", grandeur="surface_brute", valeur="10",
                              unite="pi2", borne_basse="10", borne_haute="10", service=ce.REVETEMENT)
    resultat, verdict = _estimer(version, ce.GOUTTIERES, [*mesures, etrangere])
    assert resultat is None
    assert ce.code(verdict) == "REJ-MESURE-AUTRE-LEAD"
    assert ce.REVETEMENT in verdict["detail"]


def test_une_entree_mal_formee_est_refusee_nommee_sans_exception():
    version, journal = _version_estimee()
    resultat, verdict = estimateurs_service.estimer(
        version=version, service=ce.GOUTTIERES, lead_id=ce.LEAD, mesures="pas une liste",
        maintenant=ce.MAINTENANT)
    assert resultat is None
    assert ce.code(verdict) == "REJ-ESTIMATEUR-INVALIDE"


# ---------------------------------------------------------------------------------------- entrées hostiles et bornes
def _version_avec(estimateur_soffite=None, *, sans_duree=False, sans_mode=False, sans_taux=False,
                  minimum=None, duree=None):
    version, journal = _version_estimee()
    modifiee = deepcopy(version)
    if sans_duree:
        for ligne in modifiee["lignes"]:
            ligne.pop("duree_minutes_par_unite", None)
    if sans_mode:
        for ligne in modifiee["lignes"]:
            ligne.pop("cout_unitaire_mode", None)
    if sans_taux:
        modifiee["parametres"].pop("taux_marge", None)
    if minimum is not None:
        modifiee["parametres"]["estimateurs"][ce.GOUTTIERES]["quantite_minimum"] = minimum
    if duree is not None:
        for ligne in modifiee["lignes"]:
            if ligne["service"] == ce.GOUTTIERES:
                ligne["duree_minutes_par_unite"] = duree
    if estimateur_soffite is not None:
        modifiee["parametres"]["estimateurs"][ce.SOFFITE] = estimateur_soffite
    return modifiee, journal


def test_estimateur_refuse_une_version_ou_un_service_mal_forme_sans_exception():
    version, _ = _version_estimee()
    for candidate in (None, [], "version", {"bareme_id": 5}):
        declaration, verdict = estimateurs_service.estimateur(candidate, ce.GOUTTIERES)
        assert declaration is None and ce.code(verdict) == "REJ-ESTIMATEUR-INVALIDE"
    for service in (None, 3, "avec espace", ""):
        declaration, verdict = estimateurs_service.estimateur(version, service)
        assert declaration is None and ce.code(verdict) == "REJ-ESTIMATEUR-INVALIDE"
    declaration, verdict = estimateurs_service.estimateur(version, ce.GOUTTIERES)
    assert verdict is None and declaration["unite_ouvrage"] == "pi.lin"


def test_estimer_refuse_les_entrees_mal_formees_par_des_verdicts_nommes():
    version, journal = _version_estimee()
    mesures = ce.mesures_gouttieres(journal)
    for maintenant in ("maintenant", ce.MAINTENANT.replace(tzinfo=None)):
        resultat, verdict = estimateurs_service.estimer(
            version=version, service=ce.GOUTTIERES, lead_id=ce.LEAD, mesures=mesures, maintenant=maintenant)
        assert resultat is None and ce.code(verdict) == "REJ-ESTIMATEUR-INVALIDE"
    for lead in ("", None, 3):
        resultat, verdict = estimateurs_service.estimer(
            version=version, service=ce.GOUTTIERES, lead_id=lead, mesures=mesures, maintenant=ce.MAINTENANT)
        assert resultat is None and ce.code(verdict) == "REJ-ESTIMATEUR-INVALIDE"


def test_la_borne_des_seize_composantes_est_incluse_et_dix_sept_refusees():
    seize = {"unite_ouvrage": "pi.lin", "composantes": [
        ce._composante(f"g{i}", "pi.lin", "1") for i in range(16)]}
    version, _ = _version_avec(seize)
    declaration, verdict = estimateurs_service.estimateur(version, ce.SOFFITE)
    assert verdict is None and len(declaration["composantes"]) == 16
    dix_sept = {"unite_ouvrage": "pi.lin", "composantes": [
        ce._composante(f"g{i}", "pi.lin", "1") for i in range(17)]}
    version, _ = _version_avec(dix_sept)
    declaration, verdict = estimateurs_service.estimateur(version, ce.SOFFITE)
    assert declaration is None and ce.code(verdict) == "REJ-ESTIMATEUR-INVALIDE"


def test_estimateur_refuse_une_liste_vide_ou_un_type_de_composantes_invalide():
    for composantes in ([], "trois", {"a": 1}):
        version, _ = _version_avec({"unite_ouvrage": "pi.lin", "composantes": composantes})
        declaration, verdict = estimateurs_service.estimateur(version, ce.SOFFITE)
        assert declaration is None and ce.code(verdict) == "REJ-ESTIMATEUR-INVALIDE"


def test_une_grandeur_non_prevue_mais_bien_codee_est_nommee_dans_le_refus():
    version, journal = _version_estimee()
    mesures = ce.mesures_gouttieres(journal)
    typo = ce.mesurer_ok(journal, mesure_id="mes-typo", grandeur="longueur_toit", valeur="1", unite="pi.lin",
                         borne_basse="1", borne_haute="1", service=ce.GOUTTIERES)
    resultat, verdict = _estimer(version, ce.GOUTTIERES, [*mesures, typo])
    assert resultat is None and ce.code(verdict) == "REJ-ESTIMATEUR-MESURE-NON-PREVUE"
    assert "longueur_toit" in verdict["detail"]


def test_une_conversion_nulle_ou_negative_est_refusee_et_une_conversion_de_un_est_acceptee():
    for conversion in ("0", "-1"):
        version, journal = _version_estimee()
        modifiee = deepcopy(version)
        modifiee["parametres"]["estimateurs"][ce.GOUTTIERES]["composantes"][2]["facteur_conversion"] = conversion
        mesures = ce.mesures_gouttieres(journal)
        resultat, verdict = _estimer(modifiee, ce.GOUTTIERES, mesures)
        assert resultat is None and ce.code(verdict) == "REJ-ESTIMATEUR-INVALIDE"
    version, journal = _version_estimee()
    modifiee = deepcopy(version)
    modifiee["parametres"]["estimateurs"][ce.GOUTTIERES]["composantes"][2]["facteur_conversion"] = "1"
    resultat, verdict = _estimer(modifiee, ce.GOUTTIERES, ce.mesures_gouttieres(journal))
    assert verdict is None and resultat["quantite"]["retenue"] == "146"  # 100 + 40 + 6 x 1


def test_un_minimum_nul_ou_negatif_est_refuse_et_un_minimum_de_un_est_accepte():
    for minimum in ("0", "-1"):
        version, journal = _version_avec(minimum=minimum)
        resultat, verdict = _estimer(version, ce.GOUTTIERES, ce.mesures_gouttieres(journal))
        assert resultat is None and ce.code(verdict) == "REJ-ESTIMATEUR-INVALIDE"
    version, journal = _version_avec(minimum="1")
    resultat, verdict = _estimer(version, ce.GOUTTIERES, ce.mesures_gouttieres(journal))
    assert verdict is None and resultat["recu"]["quantite"]["minimum_declare"] == "1"
    assert estimateurs_service.verifier_recu(resultat["recu"]) == (True, None)


def test_le_drapeau_de_minimum_est_faux_quand_aucun_minimum_n_est_declare_ou_quand_il_est_atteint():
    version, journal = _version_estimee()
    resultat, verdict = _estimer(version, ce.SOFFITE, [
        ce.mesurer_ok(journal, mesure_id="s1", grandeur="longueur_soffite", valeur="10", unite="pi.lin",
                      borne_basse="10", borne_haute="10", service=ce.SOFFITE),
        ce.mesurer_ok(journal, mesure_id="s2", grandeur="longueur_fascia", valeur="10", unite="pi.lin",
                      borne_basse="10", borne_haute="10", service=ce.SOFFITE)])
    assert verdict is None and resultat["recu"]["quantite"]["minimum_applique"] is False
    assert resultat["recu"]["duree"]["minimum_applique"] is False
    assert estimateurs_service.verifier_recu(resultat["recu"]) == (True, None)

    version, journal = _version_avec(minimum="155")
    resultat, verdict = _estimer(version, ce.GOUTTIERES, ce.mesures_gouttieres(journal))
    assert verdict is None and resultat["quantite"]["retenue"] == "155"
    assert resultat["recu"]["quantite"]["minimum_applique"] is False  # égalité : pas « appliqué »
    assert estimateurs_service.verifier_recu(resultat["recu"]) == (True, None)


def test_une_borne_basse_exactement_nulle_est_refusee_sans_etre_arrondie():
    version, journal = _version_estimee()
    surface = ce.mesurer_ok(journal, mesure_id="surface-zero", grandeur="surface_brute", valeur="100",
                            unite="pi2", borne_basse="99", borne_haute="101", service=ce.REVETEMENT)
    ouverture = ce.mesurer_ok(journal, mesure_id="ouverture-zero", grandeur="ouverture", valeur="99",
                              unite="pi2", borne_basse="99", borne_haute="99", service=ce.REVETEMENT)
    resultat, verdict = _estimer(version, ce.REVETEMENT, [surface, ouverture])
    assert resultat is None and ce.code(verdict) == "REJ-ESTIMATEUR-BORNES-NON-POSITIVES"
    assert "0" in verdict["detail"]


def test_la_duree_egale_au_minimum_n_est_pas_dite_appliquee_et_le_recu_se_verifie():
    version, journal = _version_estimee()
    mesure = ce.mesurer_ok(journal, mesure_id="rep-egal", grandeur="heures_reparation", valeur="1",
                           unite="heure", borne_basse="1", borne_haute="1", service=ce.REPARATION)
    resultat, verdict = _estimer(version, ce.REPARATION, [mesure])
    assert verdict is None and resultat["duree_minutes"] == "90"
    assert resultat["recu"]["duree"]["minimum_applique"] is False
    assert estimateurs_service.verifier_recu(resultat["recu"]) == (True, None)


def test_un_recu_sans_prix_ni_duree_se_verifie_sans_exiger_ces_valeurs():
    version, journal = _version_avec(sans_duree=True, sans_mode=True, sans_taux=True)
    resultat, verdict = _estimer(version, ce.SOFFITE, [
        ce.mesurer_ok(journal, mesure_id="sans-prix-1", grandeur="longueur_soffite", valeur="10", unite="pi.lin",
                      borne_basse="10", borne_haute="10", service=ce.SOFFITE),
        ce.mesurer_ok(journal, mesure_id="sans-prix-2", grandeur="longueur_fascia", valeur="10", unite="pi.lin",
                      borne_basse="10", borne_haute="10", service=ce.SOFFITE)])
    assert verdict is None and resultat["prix_recommande_cad"] is None and resultat["duree_minutes"] is None
    assert estimateurs_service.verifier_recu(resultat["recu"]) == (True, None)


def test_l_empreinte_du_recu_est_canonique_et_stable_quel_que_soit_l_ordre_des_cles():
    import hashlib
    import json

    a = {"service": "gouttières", "b": 2, "a": 1}
    b = {"a": 1, "b": 2, "service": "gouttières"}
    assert estimateurs_service._empreinte(a) == estimateurs_service._empreinte(b)
    attendu = hashlib.sha256(json.dumps(a, sort_keys=True, ensure_ascii=False,
                                        separators=(",", ":")).encode("utf-8")).hexdigest()
    assert estimateurs_service._empreinte(a) == attendu


def test_verifier_recu_nomme_le_champ_altere_et_refuse_les_structures_incompletes():
    version, journal = _version_estimee()
    resultat, _ = _estimer(version, ce.GOUTTIERES, ce.mesures_gouttieres(journal))
    recu = resultat["recu"]

    sans_empreinte = deepcopy(recu)
    sans_empreinte["empreinte"] = 123
    intact, verdict = estimateurs_service.verifier_recu(sans_empreinte)
    assert intact is False and "empreinte du reçu absente" in verdict["detail"]

    sans_composante = deepcopy(recu)
    sans_composante["composantes"] = []
    sans_composante["empreinte"] = estimateurs_service._empreinte(sans_composante)
    intact, verdict = estimateurs_service.verifier_recu(sans_composante)
    assert intact is False and "aucune composante" in verdict["detail"]

    basse = deepcopy(recu)
    basse["quantite"]["basse"] = "151"
    basse["empreinte"] = estimateurs_service._empreinte(basse)
    intact, verdict = estimateurs_service.verifier_recu(basse)
    assert intact is False and "quantité" in verdict["detail"]

    sans_taux = deepcopy(recu)
    sans_taux["taux_marge_normal"] = None
    sans_taux["empreinte"] = estimateurs_service._empreinte(sans_taux)
    intact, verdict = estimateurs_service.verifier_recu(sans_taux)
    assert intact is False and "un prix est enregistré" in verdict["detail"]


def test_une_valeur_decimale_mal_formee_dans_la_declaration_est_dite_avant_tout_calcul():
    version, journal = _version_estimee()
    modifiee = deepcopy(version)
    modifiee["parametres"]["estimateurs"][ce.GOUTTIERES]["composantes"][0]["coefficient"] = "1,5"
    resultat, verdict = _estimer(modifiee, ce.GOUTTIERES, ce.mesures_gouttieres(journal))
    assert resultat is None and ce.code(verdict) == "REJ-ESTIMATEUR-INVALIDE"
    assert "un texte décimal" in verdict["detail"]


def test_un_seul_manque_entre_mode_et_taux_ne_fait_pas_echouer_le_calcul():
    version, journal = _version_estimee()
    sans_mode = deepcopy(version)
    for ligne in sans_mode["lignes"]:
        if ligne["service"] == ce.GOUTTIERES:
            ligne.pop("cout_unitaire_mode")
    resultat, verdict = _estimer(sans_mode, ce.GOUTTIERES, ce.mesures_gouttieres(journal))
    assert verdict is None and resultat["couts"]["probable_cad"] is None
    assert resultat["prix_recommande_cad"] is None and resultat["couts"]["min_cad"] == "1444.00"

    sans_taux = deepcopy(version)
    sans_taux["parametres"].pop("taux_marge")
    resultat, verdict = _estimer(sans_taux, ce.GOUTTIERES, ce.mesures_gouttieres(journal))
    assert verdict is None and resultat["couts"]["probable_cad"] == "1705.00"
    assert resultat["prix_recommande_cad"] is None


def test_estimer_refuse_une_version_non_dictionnaire_et_un_service_non_texte():
    version, journal = _version_estimee()
    mesures = ce.mesures_gouttieres(journal)
    for candidate in (None, {"bareme_id": 5}):
        resultat, verdict = estimateurs_service.estimer(
            version=candidate, service=ce.GOUTTIERES, lead_id=ce.LEAD, mesures=mesures,
            maintenant=ce.MAINTENANT)
        assert resultat is None and ce.code(verdict) == "REJ-ESTIMATEUR-INVALIDE"
    resultat, verdict = estimateurs_service.estimer(
        version=version, service=3, lead_id=ce.LEAD, mesures=mesures, maintenant=ce.MAINTENANT)
    assert resultat is None and ce.code(verdict) == "REJ-ESTIMATEUR-INVALIDE"
    assert "service" in verdict["detail"]


def test_une_quantite_exactement_nulle_est_refusee_avant_la_borne_de_cout():
    version, journal = _version_estimee()
    surface = ce.mesurer_ok(journal, mesure_id="surface-nulle", grandeur="surface_brute", valeur="100",
                            unite="pi2", borne_basse="100", borne_haute="100", service=ce.REVETEMENT)
    ouverture = ce.mesurer_ok(journal, mesure_id="ouverture-nulle", grandeur="ouverture", valeur="100",
                              unite="pi2", borne_basse="100", borne_haute="100", service=ce.REVETEMENT)
    resultat, verdict = _estimer(version, ce.REVETEMENT, [surface, ouverture])
    assert resultat is None and ce.code(verdict) == "REJ-ESTIMATEUR-QUANTITE-NON-POSITIVE"


def test_le_recu_verifie_une_soustraction_ponderee_et_refuse_un_minimum_nul():
    version, journal = _version_estimee()
    modifiee = deepcopy(version)
    modifiee["parametres"]["estimateurs"][ce.REVETEMENT]["composantes"][1]["coefficient"] = "-2"
    resultat, verdict = _estimer(modifiee, ce.REVETEMENT, ce.mesures_revetement(journal))
    assert verdict is None
    assert estimateurs_service.verifier_recu(resultat["recu"]) == (True, None)

    minimum_nul = deepcopy(resultat["recu"])
    minimum_nul["quantite"]["minimum_declare"] = "0"
    minimum_nul["empreinte"] = estimateurs_service._empreinte(minimum_nul)
    intact, verdict = estimateurs_service.verifier_recu(minimum_nul)
    assert intact is False and "strictement positif" in verdict["detail"]


def test_le_recu_nomme_une_borne_haute_alteree():
    version, journal = _version_estimee()
    resultat, _ = _estimer(version, ce.GOUTTIERES, ce.mesures_gouttieres(journal))
    haute = deepcopy(resultat["recu"])
    haute["quantite"]["haute"] = "157"
    haute["empreinte"] = estimateurs_service._empreinte(haute)
    intact, verdict = estimateurs_service.verifier_recu(haute)
    assert intact is False and "quantité" in verdict["detail"]


def test_les_bornes_de_longueur_et_de_type_des_champs_declares_sont_refusees_a_la_declaration():
    # grandeur non textuelle : refus nommé, jamais une exception qui s'échappe
    parametres = ce.parametres()
    parametres["estimateurs"][ce.GOUTTIERES]["composantes"][0]["grandeur"] = 5
    assert "grandeur" in _invalide(parametres=parametres)

    # unité de composante de 25 caractères (la borne est 24, incluse)
    parametres = ce.parametres()
    parametres["estimateurs"][ce.GOUTTIERES]["composantes"][0]["unite"] = "u" * 25
    assert "unite" in _invalide(parametres=parametres)

    # source écrite de 301 caractères (la borne est 300, incluse)
    parametres = ce.parametres()
    parametres["estimateurs"][ce.GOUTTIERES]["composantes"][0]["source_ecrite"] = "s" * 301
    assert "source_ecrite" in _invalide(parametres=parametres)

    # conversion zéro : strictement positive exigée
    parametres = ce.parametres()
    parametres["estimateurs"][ce.GOUTTIERES]["composantes"][2]["facteur_conversion"] = "0"
    assert "facteur_conversion" in _invalide(parametres=parametres)

    # estimateurs non dictionnaire : refus nommé, jamais une exception
    assert "estimateurs" in _invalide(parametres={"estimateurs": []})

    # clé de service non textuelle : refus nommé
    parametres = ce.parametres()
    parametres["estimateurs"] = {5: parametres["estimateurs"][ce.GOUTTIERES]}
    assert "service" in _invalide(parametres=parametres)

    # composantes non liste et liste vide : refus nommés
    for composantes in ("abc", []):
        parametres = ce.parametres()
        parametres["estimateurs"][ce.GOUTTIERES]["composantes"] = composantes
        assert "composantes" in _invalide(parametres=parametres)

    # unité de l'ouvrage de 25 caractères : refus par le schéma (la borne est 24), pas par la confrontation
    parametres = ce.parametres()
    parametres["estimateurs"][ce.GOUTTIERES]["unite_ouvrage"] = "u" * 25
    detail = _invalide(parametres=parametres)
    assert "unite_ouvrage" in detail and "24" in detail


def test_les_bornes_de_nombre_de_services_et_de_composantes_sont_incluses():
    def monde(nombre_services, nombre_composantes=1):
        lignes, estimateurs = [], {}
        for i in range(nombre_services):
            service = f"s{i}"
            lignes.append(ce._ligne(service, "pi.lin"))
            estimateurs[service] = {"unite_ouvrage": "pi.lin", "composantes": [
                ce._composante(f"g{j}", "pi.lin", "1") for j in range(nombre_composantes)]}
        return {"estimateurs": estimateurs}, lignes

    parametres, lignes = monde(20)
    version, verdict = _declarer_avec(parametres=parametres, lignes=lignes)
    assert verdict is None and len(version["parametres"]["estimateurs"]) == 20

    parametres, lignes = monde(21)
    assert "20" in _invalide(parametres=parametres, lignes=lignes)

    parametres, lignes = monde(1, 16)
    version, verdict = _declarer_avec(parametres=parametres, lignes=lignes)
    assert verdict is None and len(next(iter(version["parametres"]["estimateurs"].values()))["composantes"]) == 16


def test_un_estimateur_en_memoire_mal_forme_est_refuse_avant_de_chiffrer():
    version, journal = _version_estimee()
    mesures = ce.mesures_gouttieres(journal)
    # clé inconnue dans une composante
    modifiee = deepcopy(version)
    modifiee["parametres"]["estimateurs"][ce.GOUTTIERES]["composantes"][0]["prix"] = "1"
    resultat, verdict = _estimer(modifiee, ce.GOUTTIERES, mesures)
    assert resultat is None and ce.code(verdict) == "REJ-ESTIMATEUR-INVALIDE"
    # clé requise absente
    modifiee = deepcopy(version)
    modifiee["parametres"]["estimateurs"][ce.GOUTTIERES]["composantes"][0].pop("unite")
    resultat, verdict = _estimer(modifiee, ce.GOUTTIERES, mesures)
    assert resultat is None and ce.code(verdict) == "REJ-ESTIMATEUR-INVALIDE"
    assert "une composante déclarée est mal formée" in verdict["detail"]
    # conversion implicite entre deux unités différentes
    modifiee = deepcopy(version)
    modifiee["parametres"]["estimateurs"][ce.GOUTTIERES]["composantes"][2].pop("facteur_conversion")
    resultat, verdict = _estimer(modifiee, ce.GOUTTIERES, mesures)
    assert resultat is None and ce.code(verdict) == "REJ-ESTIMATEUR-INVALIDE"
    # conversion interdite quand l'unité est la même
    modifiee = deepcopy(version)
    modifiee["parametres"]["estimateurs"][ce.GOUTTIERES]["composantes"][0]["facteur_conversion"] = "1"
    resultat, verdict = _estimer(modifiee, ce.GOUTTIERES, mesures)
    assert resultat is None and ce.code(verdict) == "REJ-ESTIMATEUR-INVALIDE"
    # unité de l'estimateur différente de celle de la ligne d'ouvrage (mesures et composantes inchangées)
    modifiee = deepcopy(version)
    for ligne in modifiee["lignes"]:
        if ligne["service"] == ce.GOUTTIERES:
            ligne["unite"] = "pi2"
    resultat, verdict = _estimer(modifiee, ce.GOUTTIERES, mesures)
    assert resultat is None and ce.code(verdict) == "REJ-ESTIMATEUR-INVALIDE"
