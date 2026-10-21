"""PLAN T0.13 — LeadQualifie v2 côté M3 : `service` validé par la taxonomie du socle.

La v1 (gelée, `type_travaux`) reste acceptée telle quelle. Pour un lead v2, M3 ne garde AUCUNE
copie de la liste des services : il la lit dans le profil d'entreprise de l'instance. Un service
sans profil, non déclaré, ou sans poste au barème est un refus nommé qui dit quoi fournir ; jamais
un repli sur « autre » ni sur un autre poste. Les copies de M3 (clés du contrat v2) sont épinglées
contre la SOURCE de M2 par AST (décision #109 : aucun import inter-modules)."""

import ast
import sys
from pathlib import Path

import pytest

_RACINE_M3 = Path(__file__).resolve().parents[1]
_SRC_M3 = _RACINE_M3 / "src"
if str(_SRC_M3) not in sys.path:
    sys.path.insert(0, str(_SRC_M3))

_SOURCE_M2 = (
    Path(__file__).resolve().parents[3]
    / "departments" / "m02-revenue-crm" / "src" / "m2_revenue_crm" / "contrats.py"
)

from m3_estimation import contrats, estimation, monte_carlo, registre, validation  # noqa: E402
from m3_estimation import outils as outils_m3  # noqa: E402

from opsys import taxonomie  # noqa: E402
from opsys.outils import executer  # noqa: E402


@pytest.fixture(autouse=True)
def _instance_avec_services(declarer_services):
    """L'instance de test déclare les services du catalogue de référence."""
    declarer_services()


def _constante_m2(nom):
    arbre = ast.parse(_SOURCE_M2.read_text(encoding="utf-8"), filename=str(_SOURCE_M2))
    for noeud in arbre.body:
        if isinstance(noeud, ast.Assign) and any(
            isinstance(cible, ast.Name) and cible.id == nom for cible in noeud.targets
        ):
            return ast.literal_eval(noeud.value)
    pytest.fail(f"constante {nom} introuvable dans {_SOURCE_M2} — fail-closed")


def _contrat_v2(**surcharges):
    contrat = {
        "schema_version": 2,
        "lead_id": "lead-v2-001",
        "conversation_id": "conv-v2-001",
        "service": "revetement",
        "ville": "Quebec",
        "canal": "formulaire",
        "contact": {"nom": "Durand", "telephone": "5145550000"},
        "urgence_declaree": False,
    }
    contrat.update(surcharges)
    return contrat


def _marqueur():
    return {
        "readiness_ok": True,
        "lead_id": "lead-v2-001",
        "hash_tete_registre": "f" * 64,
        "horodatage": "2026-09-28T10:00:00-04:00",
        "empreinte": "a" * 64,
    }


PHOTOS = [{
    "photo_id": "p1", "resolution_largeur": 3000, "resolution_hauteur": 2000, "eclairage": 7,
    "angle": "face", "reference_echelle": {"type": "porte", "dimensions_connues": True},
}]
SEUILS = {"resolution_minimale": 1000, "eclairage_minimal": 4}
BAREME = {
    "version": "2026.1", "unite": "pi2",
    "postes": {"revetement": {"cout_unitaire_min": 8.0, "cout_unitaire_max": 14.0,
                              "duree_minutes_par_unite": 2.5}},
}


def _orchestrer(**surcharges):
    parametres = {
        "contrat": _contrat_v2(), "marqueur": _marqueur(), "photos": PHOTOS, "seuils": SEUILS,
        "bareme": BAREME, "quantite": 1200, "plancher_rentable": 9000,
        "registre_cible": registre.Registre(), "graine": 42, "taux_marge": "0.35",
    }
    parametres.update(surcharges)
    return estimation.orchestrer_estimation(**parametres)


# ---------------------------------------------------------------- copies épinglées contre M2
def test_champs_contrat_v2_copie_m2_ne_derive_pas():
    assert list(contrats.CHAMPS_CONTRAT_GELE_V2) == list(_constante_m2("CHAMPS_CONTRAT_GELE_V2"))


def test_version_v2_copie_m2_ne_derive_pas():
    assert _constante_m2("VERSION_CONTRAT_V2") == contrats.VERSION_CONTRAT_V2


def test_m3_ne_garde_aucune_copie_de_la_liste_des_services():
    """Le catalogue vit dans le socle : la garde de dérive de `opsys-metier verifier` (une seule
    implémentation, `taxonomie.copies_locales_du_catalogue`) ne trouve rien dans les sources de M3."""
    assert taxonomie.copies_locales_du_catalogue([_SRC_M3]) == []


# ---------------------------------------------------------------- validation d'entrée
def test_lead_v2_valide_est_accepte_et_l_accuse_porte_le_service():
    accuse, verdict = validation.valider_entrees(_contrat_v2(), _marqueur(), PHOTOS)
    assert verdict is None
    assert accuse["service"] == "revetement" and accuse["schema_version"] == 2
    assert "type_travaux" not in accuse


def test_lead_v1_reste_accepte_et_son_accuse_est_inchange():
    contrat_v1 = {
        "lead_id": "lead-v2-001", "conversation_id": "conv-1", "type_travaux": "ravalement",
        "ville": "Quebec", "canal": "formulaire", "contact": {"nom": "Durand"}, "urgence_declaree": False,
    }
    accuse, verdict = validation.valider_entrees(contrat_v1, _marqueur(), PHOTOS)
    assert verdict is None
    assert set(accuse) == {"lead_id", "type_travaux", "ville", "empreinte_marqueur_m2", "nombre_photos"}


def test_lead_v1_reste_accepte_sans_profil_d_entreprise():
    taxonomie.fichier_profil().unlink()
    contrat_v1 = {
        "lead_id": "lead-v2-001", "conversation_id": "conv-1", "type_travaux": "ravalement",
        "ville": "Quebec", "canal": "formulaire", "contact": {"nom": "Durand"}, "urgence_declaree": False,
    }
    assert validation.valider_entrees(contrat_v1, _marqueur(), PHOTOS)[1] is None


def test_cles_optionnelles_acceptees_a_l_identique_en_v2():
    contrat = _contrat_v2(source="google", campagne="printemps", utm={"utm_source": "google"})
    assert validation.valider_entrees(contrat, _marqueur(), PHOTOS)[1] is None
    for cle, valeur in (("source", ""), ("utm", {"utm_x": "a"}), ("campagne", 3)):
        verdict = validation.valider_entrees(_contrat_v2(**{cle: valeur}), _marqueur(), PHOTOS)[1]
        assert verdict["code"] == "REJ-CONTRAT-INVALIDE"


@pytest.mark.parametrize("version", [1, 3, "2", True, 2.0, None])
def test_version_explicite_jamais_devinee(version):
    verdict = validation.valider_entrees(_contrat_v2(schema_version=version), _marqueur(), PHOTOS)[1]
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert "schema_version" in verdict["detail"]


def test_lead_sans_version_qui_porte_service_est_refuse():
    contrat = _contrat_v2()
    del contrat["schema_version"]
    verdict = validation.valider_entrees(contrat, _marqueur(), PHOTOS)[1]
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert "inconnues=['service']" in verdict["detail"] and "manquantes=['type_travaux']" in verdict["detail"]


def test_lead_v2_qui_porte_type_travaux_est_refuse():
    verdict = validation.valider_entrees(_contrat_v2(type_travaux="autre"), _marqueur(), PHOTOS)[1]
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert "inconnues=['type_travaux']" in verdict["detail"]


def test_service_non_declare_est_refuse_avec_la_consigne_de_configuration(declarer_services):
    declarer_services("gouttieres")
    verdict = validation.valider_entrees(_contrat_v2(service="revetement"), _marqueur(), PHOTOS)[1]
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert "REJ-SERVICE-INCONNU" in verdict["detail"] and "entreprise.yaml" in verdict["detail"]


def test_sans_profil_tout_service_est_refuse_et_dit_quoi_configurer():
    taxonomie.fichier_profil().unlink()
    verdict = validation.valider_entrees(_contrat_v2(), _marqueur(), PHOTOS)[1]
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert "REJ-SERVICE-NON-CONFIGURE" in verdict["detail"] and "entreprise.yaml" in verdict["detail"]


@pytest.mark.parametrize("service", ["autre", "renovation_totale", "", None, 3])
def test_aucun_repli_sur_autre_ni_sur_un_ancien_type(service):
    verdict = validation.valider_entrees(_contrat_v2(service=service), _marqueur(), PHOTOS)[1]
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"


def test_services_fournis_par_l_appelant_priment_sur_le_profil():
    pergola = taxonomie.Service("pose_pergola", "Pose de pergolas")
    accuse, verdict = validation.valider_entrees(
        _contrat_v2(service="pose_pergola"), _marqueur(), PHOTOS, services=(pergola,))
    assert verdict is None and accuse["service"] == "pose_pergola"


# ---------------------------------------------------------------- barème par service
def test_estimation_complete_pour_un_lead_v2_avec_le_poste_du_service():
    reponse = _orchestrer()
    assert reponse["accepte"] is True and reponse["etape"] == "complet"
    assert reponse["estimation"]["intervalle_confiance"]["borne_basse"] > 0
    assert reponse["duree_estimee_minutes"] == "3000.0"
    assert reponse["estimation"]["bareme_version"] == "2026.1"


def test_bareme_sans_poste_pour_le_service_bloque_sans_repli():
    bareme = {"version": "2026.1", "unite": "pi2",
              "postes": {"gouttieres": {"cout_unitaire_min": 5.0, "cout_unitaire_max": 9.0}}}
    reponse = _orchestrer(bareme=bareme)
    assert reponse["accepte"] is False and reponse["etape"] == "intervalle"
    assert reponse["verdict"]["code"] == "REJ-CONTRAT-INVALIDE"
    assert reponse["verdict"]["detail"] == "barème du service 'revetement' absent : à fournir"


def test_bareme_ne_couvrant_qu_un_ancien_type_ne_repond_pas_pour_un_service():
    bareme = {"version": "2026.1", "unite": "pi2",
              "postes": {"autre": {"cout_unitaire_min": 5.0, "cout_unitaire_max": 9.0}}}
    reponse = _orchestrer(bareme=bareme)
    assert reponse["accepte"] is False
    assert "absent : à fournir" in reponse["verdict"]["detail"]


def test_le_type_v1_garde_son_message_de_bareme_absent():
    contrat = {"lead_id": "lead-v2-001", "conversation_id": "c", "type_travaux": "extension",
               "ville": "Quebec", "canal": "formulaire", "contact": {"nom": "D"}, "urgence_declaree": False}
    reponse = _orchestrer(contrat=contrat, bareme={"version": "1", "unite": "pi2", "postes": {
        "ravalement": {"cout_unitaire_min": 1.0, "cout_unitaire_max": 2.0}}})
    assert reponse["verdict"]["detail"] == "barème sans poste pour le type demandé : 'extension'"


def test_simuler_intervalle_ne_reconnait_un_service_que_si_l_appelant_l_a_valide():
    intervalle, verdict = monte_carlo.simuler_intervalle(BAREME, "revetement", 10, 1, 0.9)
    assert intervalle is None and verdict["detail"] == "type_travaux hors contrat : 'revetement'"
    intervalle, verdict = monte_carlo.simuler_intervalle(BAREME, "revetement", 10, 1, 0.9, services=("revetement",))
    assert verdict is None and intervalle["borne_basse"] >= 80.0


def test_a_donnees_egales_meme_intervalle_pour_un_service_bit_a_bit():
    a = monte_carlo.simuler_intervalle(BAREME, "revetement", 10, 7, 0.9, services=("revetement",))
    b = monte_carlo.simuler_intervalle(BAREME, "revetement", 10, 7, 0.9, services=("revetement",))
    assert a == b


# ---------------------------------------------------------------- outils d'agent
def _outil(nom):
    return next(o for o in outils_m3.outils() if o.nom == nom)


def test_m3_simuler_intervalle_accepte_un_service_declare():
    reponse = executer(_outil("m3_simuler_intervalle"), {
        "bareme": BAREME, "type_travaux": "revetement", "quantite": 10, "graine": 1})
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True


def test_m3_simuler_intervalle_refuse_un_service_non_declare_avec_la_consigne(declarer_services):
    declarer_services("gouttieres")
    reponse = executer(_outil("m3_simuler_intervalle"), {
        "bareme": BAREME, "type_travaux": "revetement", "quantite": 10, "graine": 1})
    assert reponse["ok"] is True
    resultat = reponse["resultat"]
    assert resultat["accepte"] is False
    assert resultat["verdict"]["code"] == "REJ-CONTRAT-INVALIDE"
    assert "REJ-SERVICE-INCONNU" in resultat["verdict"]["detail"]
    assert "entreprise.yaml" in resultat["verdict"]["detail"]


def test_m3_simuler_intervalle_accepte_toujours_un_type_v1():
    bareme = {
        "version": "1",
        "unite": "pi2",
        "postes": {"ravalement": {"cout_unitaire_min": 1.0, "cout_unitaire_max": 2.0}},
    }
    reponse = executer(_outil("m3_simuler_intervalle"), {
        "bareme": bareme, "type_travaux": "ravalement", "quantite": 10, "graine": 1})
    assert reponse["resultat"]["accepte"] is True


def test_le_schema_de_m3_estimer_projet_decrit_les_deux_versions_du_contrat():
    contrat = _outil("m3_estimer_projet").parametres["properties"]["contrat"]
    assert {"schema_version", "service", "type_travaux"} <= set(contrat["properties"])
    assert not {"type_travaux", "service"} & set(contrat["required"])
