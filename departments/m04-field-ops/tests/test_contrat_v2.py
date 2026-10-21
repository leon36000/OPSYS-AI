"""Contrat LeadQualifie v2 côté M4 (PLAN T0.13-b) : `service` de la taxonomie du socle, version explicite.

La v1 (gelée, `type_travaux`) reste acceptée telle quelle ; rien n'est deviné. Même comportement que M2
(`departments/m02-revenue-crm/tests/test_contrat_v2.py`) : mêmes codes de refus, même ordre des contrôles.
Fixtures fictives.
"""

import m4_field_ops.contrats as contrats_mod
import pytest

from opsys import taxonomie

MARQUEUR = {
    "readiness_ok": True, "lead_id": "V2-1", "hash_tete_registre": "a" * 64,
    "horodatage": "2026-09-28T12:00:00+00:00", "empreinte": "b" * 64,
}


@pytest.fixture(autouse=True)
def _instance_avec_services(declarer_services):
    """L'instance de test déclare les services du catalogue de référence."""
    declarer_services()


def contrat_v2(lead_id="V2-1", **surcharges):
    base = {
        "schema_version": 2,
        "lead_id": lead_id,
        "conversation_id": f"conv-{lead_id}",
        "contact": {"nom": "Client Test", "courriel": f"{lead_id}@example.test"},
        "service": "gouttieres",
        "ville": "Québec",
        "urgence_declaree": False,
        "canal": "formulaire",
    }
    base.update(surcharges)
    return base


def contrat_v1(lead_id="V1-1", **surcharges):
    base = {
        "lead_id": lead_id,
        "conversation_id": f"conv-{lead_id}",
        "contact": {"nom": "Client Test", "courriel": f"{lead_id}@example.test"},
        "type_travaux": "renovation_totale",
        "ville": "Québec",
        "urgence_declaree": False,
        "canal": "telephone",
    }
    base.update(surcharges)
    return base


# ------------------------------------------------------------------ structure et version
class TestValidationStructure:
    def test_v2_conforme_accepte(self):
        assert contrats_mod.valider_structure(contrat_v2()) == (True, "")

    def test_v1_conforme_reste_accepte(self):
        assert contrats_mod.valider_structure(contrat_v1()) == (True, "")

    def test_v1_reste_accepte_sans_aucun_profil_d_entreprise(self):
        taxonomie.fichier_profil().unlink()
        assert contrats_mod.valider_structure(contrat_v1()) == (True, "")

    def test_cles_optionnelles_acceptees_dans_les_deux_versions(self):
        extras = {"source": "google", "campagne": "printemps", "utm": {"utm_source": "google"}}
        assert contrats_mod.valider_structure(contrat_v2(**extras)) == (True, "")
        assert contrats_mod.valider_structure(contrat_v1(**extras)) == (True, "")

    @pytest.mark.parametrize("cle, valeur", [("source", ""), ("campagne", 4), ("utm", {}), ("utm", {"utm_x": "a"})])
    def test_cles_optionnelles_invalides_refusees_en_v2(self, cle, valeur):
        assert contrats_mod.valider_structure(contrat_v2(**{cle: valeur})) == (False, "REJ-CONTRAT-INVALIDE")

    @pytest.mark.parametrize("version", [1, 3, 0, "2", 2.0, True, None])
    def test_version_explicite_jamais_devinee(self, version):
        assert contrats_mod.valider_structure(contrat_v2(schema_version=version)) == (False, "REJ-CONTRAT-INVALIDE")

    def test_lead_sans_version_qui_porte_service_est_refuse_pas_devine_v2(self):
        lead = contrat_v1()
        del lead["type_travaux"]
        lead["service"] = "gouttieres"
        assert contrats_mod.valider_structure(lead) == (False, "REJ-CHAMP-MANQUANT")  # lu v1 : type_travaux manque

    def test_v1_avec_les_deux_cles_est_refuse(self):
        assert contrats_mod.valider_structure(contrat_v1(service="gouttieres")) == (False, "REJ-CONTRAT-INVALIDE")

    def test_v2_qui_porte_type_travaux_est_refuse(self):
        ok, code, detail = contrats_mod.valider_structure_avec_detail(contrat_v2(type_travaux="autre"))
        assert (ok, code) == (False, "REJ-CONTRAT-INVALIDE")
        assert "type_travaux" in detail

    @pytest.mark.parametrize("champ", list(contrats_mod.CHAMPS_CONTRAT_GELE_V2[1:]))
    def test_champ_obligatoire_manquant_en_v2(self, champ):
        lead = contrat_v2()
        del lead[champ]
        ok, code, detail = contrats_mod.valider_structure_avec_detail(lead)
        assert (ok, code) == (False, "REJ-CHAMP-MANQUANT")
        assert champ in detail

    def test_ordre_des_controles_v2_champs_manquants_avant_inconnus(self):
        lead = contrat_v2(inconnu="x")
        del lead["ville"]
        assert contrats_mod.valider_structure(lead) == (False, "REJ-CHAMP-MANQUANT")

    def test_champ_inconnu_refuse_en_v2(self):
        assert contrats_mod.valider_structure(contrat_v2(inconnu="x")) == (False, "REJ-CONTRAT-INVALIDE")

    @pytest.mark.parametrize("champ, valeur, code", [
        ("ville", "", "REJ-CHAMP-VIDE"),
        ("lead_id", 3, "REJ-CONTRAT-INVALIDE"),
        ("service", "", "REJ-CHAMP-VIDE"),
        ("service", 3, "REJ-CONTRAT-INVALIDE"),
        ("canal", "fax", "REJ-ENUM-INVALIDE"),
        ("contact", {"nom": ""}, "REJ-CHAMP-VIDE"),
        ("contact", {"fax": "x"}, "REJ-CONTRAT-INVALIDE"),
        ("urgence_declaree", 1, "REJ-CONTRAT-INVALIDE"),
    ])
    def test_memes_controles_de_valeur_qu_en_v1(self, champ, valeur, code):
        assert contrats_mod.valider_structure(contrat_v2(**{champ: valeur})) == (False, code)

    def test_non_dict_refuse(self):
        assert contrats_mod.valider_structure(["schema_version"]) == (False, "REJ-CONTRAT-INVALIDE")

    def test_les_copies_de_champs_v2_sont_les_huit_du_contrat(self):
        assert contrats_mod.VERSION_CONTRAT_V2 == 2
        assert set(contrats_mod.CHAMPS_CONTRAT_GELE_V2) == {
            "schema_version", "lead_id", "conversation_id", "service", "ville", "canal", "contact",
            "urgence_declaree"}


# ------------------------------------------------------------------ service déclaré (taxonomie du socle)
class TestServiceDeclare:
    def test_service_hors_profil_refuse_avec_la_marche_a_suivre(self, declarer_services):
        declarer_services("revetement")
        ok, code, detail = contrats_mod.valider_structure_avec_detail(contrat_v2(service="gouttieres"))
        assert (ok, code) == (False, "REJ-ENUM-INVALIDE")
        assert "REJ-SERVICE-INCONNU" in detail and "revetement" in detail and "entreprise.yaml" in detail

    def test_sans_profil_aucun_service_n_est_accepte_et_le_detail_dit_quoi_configurer(self):
        taxonomie.fichier_profil().unlink()
        ok, code, detail = contrats_mod.valider_structure_avec_detail(contrat_v2())
        assert (ok, code) == (False, "REJ-ENUM-INVALIDE")
        assert "REJ-SERVICE-NON-CONFIGURE" in detail and "entreprise.yaml" in detail

    def test_profil_invalide_refuse_sans_repli(self):
        taxonomie.fichier_profil().write_text("services: [service_inexistant]\n", encoding="utf-8")
        ok, code, detail = contrats_mod.valider_structure_avec_detail(contrat_v2())
        assert (ok, code) == (False, "REJ-ENUM-INVALIDE")
        assert "REJ-PROFIL-INVALIDE" in detail

    def test_un_service_propre_de_l_entreprise_est_accepte(self, declarer_services):
        declarer_services("gouttieres", {"code": "pose_pergola", "libelle": "Pose de pergolas"})
        assert contrats_mod.valider_structure(contrat_v2(service="pose_pergola")) == (True, "")

    def test_un_type_v1_n_est_pas_un_service_v2(self):
        """`extension` est un type v1 : sous la v2, ce n'est pas un service déclaré."""
        assert contrats_mod.valider_structure(contrat_v2(service="extension")) == (False, "REJ-ENUM-INVALIDE")

    def test_un_service_du_catalogue_n_est_pas_un_type_v1(self):
        assert contrats_mod.valider_structure(contrat_v1(type_travaux="gouttieres")) == (False, "REJ-ENUM-INVALIDE")


# ------------------------------------------------------------------ valider_entree : frontière, structure, marqueur
class TestValiderEntree:
    def test_v2_avec_marqueur_valide_est_accepte(self):
        assert contrats_mod.valider_entree(contrat_v2(), MARQUEUR) == (True, None)

    def test_le_verdict_de_refus_porte_le_detail_de_la_taxonomie(self, declarer_services):
        declarer_services("revetement")
        ok, verdict = contrats_mod.valider_entree(contrat_v2(service="gouttieres"), MARQUEUR)
        assert ok is False and verdict["code"] == "REJ-ENUM-INVALIDE"
        assert "REJ-SERVICE-INCONNU" in verdict["detail"]

    def test_le_verdict_v1_garde_son_detail_vide(self):
        ok, verdict = contrats_mod.valider_entree(contrat_v1(type_travaux="demolition"), MARQUEUR)
        assert (ok, verdict["code"], verdict["detail"]) == (False, "REJ-ENUM-INVALIDE", "")

    def test_la_frontiere_passe_avant_la_structure_en_v2_aussi(self):
        ok, verdict = contrats_mod.valider_entree(contrat_v2(prix=100), MARQUEUR)
        assert ok is False and verdict["code"] == "REJ-FRONTIERE-VIOLEE"

    def test_marqueur_d_un_autre_lead_refuse_en_v2(self):
        ok, verdict = contrats_mod.valider_entree(contrat_v2(lead_id="V2-AUTRE"), MARQUEUR)
        assert ok is False and verdict["code"] == "REJ-READINESS-NON-FRANCHIE"
