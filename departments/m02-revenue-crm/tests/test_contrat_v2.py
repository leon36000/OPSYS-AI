"""Contrat LeadQualifie v2 côté M2 (PLAN T0.13) : `service` de la taxonomie du socle, version
explicite. La v1 (gelée, `type_travaux`) reste acceptée telle quelle ; rien n'est deviné."""

import pytest
from m2_revenue_crm import (
    clients,
    contrats,
    doublons,
    encodage,
    ingestion,
    interactions,
    readiness,
    registre,
    statuts,
)
from m2_revenue_crm.outils import (
    ingerer_lead,
    outils,
    reinitialiser_registre,
)

from opsys import taxonomie
from opsys.outils import executer

H_INGESTION = "2026-03-01T09:00:00+02:00"


@pytest.fixture(autouse=True)
def _instance_avec_services(declarer_services):
    """L'instance de test déclare les services du catalogue de référence."""
    declarer_services()


@pytest.fixture(autouse=True)
def _registre_propre():
    reinitialiser_registre()
    yield
    reinitialiser_registre()


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
        assert contrats.valider_structure(contrat_v2()) == (True, "")

    def test_v1_conforme_reste_accepte(self):
        assert contrats.valider_structure(contrat_v1()) == (True, "")

    def test_v1_reste_accepte_sans_aucun_profil_d_entreprise(self):
        taxonomie.fichier_profil().unlink()
        assert contrats.valider_structure(contrat_v1()) == (True, "")

    def test_cles_optionnelles_acceptees_dans_les_deux_versions(self):
        extras = {"source": "google", "campagne": "printemps", "utm": {"utm_source": "google"}}
        assert contrats.valider_structure(contrat_v2(**extras)) == (True, "")
        assert contrats.valider_structure(contrat_v1(**extras)) == (True, "")

    @pytest.mark.parametrize("cle, valeur", [("source", ""), ("campagne", 4), ("utm", {}), ("utm", {"utm_x": "a"})])
    def test_cles_optionnelles_invalides_refusees_en_v2(self, cle, valeur):
        assert contrats.valider_structure(contrat_v2(**{cle: valeur})) == (False, "REJ-CONTRAT-INVALIDE")

    @pytest.mark.parametrize("version", [1, 3, 0, "2", 2.0, True, None])
    def test_version_explicite_jamais_devinee(self, version):
        assert contrats.valider_structure(contrat_v2(schema_version=version)) == (False, "REJ-CONTRAT-INVALIDE")

    def test_lead_sans_version_qui_porte_service_est_refuse_pas_devine_v2(self):
        lead = contrat_v1()
        del lead["type_travaux"]
        lead["service"] = "gouttieres"
        ok, code = contrats.valider_structure(lead)
        assert (ok, code) == (False, "REJ-CHAMP-MANQUANT")  # lu comme un v1 : type_travaux manque

    def test_v1_avec_les_deux_cles_est_refuse(self):
        assert contrats.valider_structure(contrat_v1(service="gouttieres")) == (False, "REJ-CONTRAT-INVALIDE")

    def test_v2_qui_porte_type_travaux_est_refuse(self):
        ok, code, detail = contrats.valider_structure_avec_detail(contrat_v2(type_travaux="autre"))
        assert (ok, code) == (False, "REJ-CONTRAT-INVALIDE")
        assert "type_travaux" in detail

    @pytest.mark.parametrize("champ", list(contrats.CHAMPS_CONTRAT_GELE_V2[1:]))
    def test_champ_obligatoire_manquant_en_v2(self, champ):
        lead = contrat_v2()
        del lead[champ]
        ok, code, detail = contrats.valider_structure_avec_detail(lead)
        assert (ok, code) == (False, "REJ-CHAMP-MANQUANT")
        assert champ in detail

    def test_ordre_des_controles_v2_champs_manquants_avant_inconnus(self):
        lead = contrat_v2(inconnu="x")
        del lead["ville"]
        assert contrats.valider_structure(lead) == (False, "REJ-CHAMP-MANQUANT")

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
        assert contrats.valider_structure(contrat_v2(**{champ: valeur})) == (False, code)

    def test_non_dict_refuse(self):
        assert contrats.valider_structure(["schema_version"]) == (False, "REJ-CONTRAT-INVALIDE")


class TestServiceDeclare:
    def test_service_hors_profil_refuse_avec_la_marche_a_suivre(self, declarer_services):
        declarer_services("revetement")
        ok, code, detail = contrats.valider_structure_avec_detail(contrat_v2(service="gouttieres"))
        assert (ok, code) == (False, "REJ-ENUM-INVALIDE")
        assert "REJ-SERVICE-INCONNU" in detail
        assert "entreprise.yaml" in detail

    def test_sans_profil_tout_service_est_refuse_et_le_detail_dit_quoi_configurer(self):
        taxonomie.fichier_profil().unlink()
        ok, code, detail = contrats.valider_structure_avec_detail(contrat_v2(service="gouttieres"))
        assert (ok, code) == (False, "REJ-ENUM-INVALIDE")
        assert "REJ-SERVICE-NON-CONFIGURE" in detail
        assert "entreprise.yaml" in detail

    @pytest.mark.parametrize("service", ["autre", "renovation_totale", "Gouttieres", "gouttières"])
    def test_aucun_repli_sur_autre_ni_sur_un_ancien_type(self, service):
        assert contrats.valider_structure(contrat_v2(service=service)) == (False, "REJ-ENUM-INVALIDE")

    def test_service_propre_d_une_autre_pme(self, declarer_services):
        declarer_services({"code": "pose_pergola", "libelle": "Pose de pergolas"})
        assert contrats.valider_structure(contrat_v2(service="pose_pergola")) == (True, "")
        assert contrats.valider_structure(contrat_v2(service="gouttieres")) == (False, "REJ-ENUM-INVALIDE")


# ------------------------------------------------------------------ ingestion
class TestIngestion:
    def test_v2_ingere_et_le_contrat_est_conserve_tel_quel(self):
        reg = registre.Registre()
        accuse, verdict = ingestion.ingerer(contrat_v2(), reg, H_INGESTION)
        assert verdict is None and accuse["lead_id"] == "V2-1"
        maillon = reg.lire()[-1]
        assert maillon["contrat"]["service"] == "gouttieres"
        assert maillon["contrat"]["schema_version"] == 2
        assert "type_travaux" not in maillon["contrat"]

    def test_le_refus_porte_le_detail_de_configuration(self, declarer_services):
        declarer_services("revetement")
        accuse, verdict = ingestion.ingerer(contrat_v2(), registre.Registre(), H_INGESTION)
        assert accuse is None
        assert verdict["code"] == "REJ-ENUM-INVALIDE"
        assert "entreprise.yaml" in verdict["detail"]

    def test_un_refus_v1_garde_un_detail_vide(self):
        accuse, verdict = ingestion.ingerer(contrat_v1(type_travaux="peinture"), registre.Registre(), H_INGESTION)
        assert accuse is None
        assert verdict["code"] == "REJ-ENUM-INVALIDE"
        assert verdict["detail"] == ""

    def test_v1_et_v2_coexistent_dans_le_meme_registre(self):
        reg = registre.Registre()
        assert ingestion.ingerer(contrat_v1(), reg, H_INGESTION)[1] is None
        assert ingestion.ingerer(contrat_v2(), reg, H_INGESTION)[1] is None
        assert reg.valider_chaine()

    def test_outil_ingerer_lead_accepte_un_lead_v2_et_refuse_un_service_non_declare(self, declarer_services):
        reponse = ingerer_lead(contrat_v2("O1"), "2026-06-15T10:00:00+00:00")
        assert reponse["accepte"] is True
        declarer_services("revetement")
        refus = ingerer_lead(contrat_v2("O2"), "2026-06-15T10:00:00+00:00")
        assert refus["accepte"] is False
        assert "entreprise.yaml" in refus["verdict"]["detail"]

    def test_le_schema_de_l_outil_decrit_les_deux_versions(self):
        outil = next(o for o in outils() if o.nom == "m2_ingerer_lead")
        contrat = outil.parametres["properties"]["contrat"]
        assert {"schema_version", "service", "type_travaux"} <= set(contrat["properties"])
        assert "type_travaux" not in contrat["required"] and "service" not in contrat["required"]
        reponse = executer(outil, {"contrat": contrat_v2("O3"), "horodatage": "2026-06-15T10:00:00+00:00"})
        assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True


# ------------------------------------------------------------------ doublons
class TestDoublons:
    def _deux_leads(self, a, b):
        reg = registre.Registre()
        for lead in (a, b):
            contact = {"nom": lead["lead_id"]}
            lead["contact"] = contact
            assert ingestion.ingerer(lead, reg, H_INGESTION)[1] is None
        return reg

    def test_meme_ville_et_meme_service_est_un_doublon_probable(self):
        reg = self._deux_leads(contrat_v2("A"), contrat_v2("B"))
        assert doublons.detecter(reg, "B") == ["A"]

    def test_meme_ville_service_different_n_est_pas_un_doublon(self):
        reg = self._deux_leads(contrat_v2("A"), contrat_v2("B", service="revetement"))
        assert doublons.detecter(reg, "B") == []

    def test_un_type_travaux_v1_et_un_service_v2_ne_se_rapprochent_jamais(self, declarer_services):
        declarer_services("gouttieres", {"code": "extension", "libelle": "Extension (service propre)"})
        reg = self._deux_leads(contrat_v1("A", type_travaux="extension"), contrat_v2("B", service="extension"))
        assert doublons.detecter(reg, "B") == []


# ------------------------------------------------------------------ client 360
class TestClient360:
    def test_la_vue_porte_le_service_d_un_lead_v2_et_le_type_d_un_lead_v1(self):
        reg = registre.Registre()
        v2 = contrat_v2("A", contact={"nom": "Dupont", "telephone": "418-555-1111"})
        v1 = contrat_v1("B", contact={"nom": "Dupont", "telephone": "418-555-1111"})
        for lead in (v1, v2):
            assert ingestion.ingerer(lead, reg, H_INGESTION)[1] is None
            assert clients.lier_lead(reg, lead["lead_id"], lead, H_INGESTION)[1] is None
        client_id = clients.identifiant_client(v2)
        vue = clients.vue_360(reg, client_id)
        par_lead = {o["lead_id"]: o for o in vue["opportunites"]}
        assert par_lead["A"]["service"] == "gouttieres" and par_lead["A"]["type_travaux"] is None
        assert par_lead["B"]["type_travaux"] == "renovation_totale" and par_lead["B"]["service"] is None


# ------------------------------------------------------------------ readiness
def _qualifier_avec_interaction(reg, lead, horodatage_transition="2026-03-01T10:00:00+02:00"):
    assert ingestion.ingerer(lead, reg, H_INGESTION)[1] is None
    accuse, verdict = statuts.transitionner(
        lead["lead_id"], "qualifie", reg, horodatage_transition, owner="Alice",
        prochaine_action={"description": "Appeler", "echeance": "2026-03-02T12:00:00+02:00"},
    )
    assert verdict is None, verdict
    assert interactions.enregistrer(lead["lead_id"], "Alice", "Appel", reg, "2026-03-01T11:00:00+02:00")[1] is None


class TestReadiness:
    def test_lead_v2_pret_pour_m3_et_marqueur_signe_sur_la_cle_service(self):
        reg = registre.Registre()
        _qualifier_avec_interaction(reg, contrat_v2("R1"))
        assert readiness.evaluer(reg, "R1") is True
        marqueur, verdict = readiness.emettre_marqueur(reg, "R1", "2026-03-01T12:00:00+02:00")
        assert verdict is None
        attendu = encodage.encoder_canonique(
            {"owner": "Alice", "service": "gouttieres", "ville": "Québec",
             "interaction_post_qualification": True},
            "R1", reg.tete(),
        )
        assert marqueur["empreinte"] == attendu
        assert readiness.verifier_marqueur(marqueur, reg) is True

    def test_lead_v1_garde_exactement_les_memes_conditions_signees(self):
        """Octets inchangés pour la v1 : M3 recalcule la même empreinte qu'avant T0.13."""
        reg = registre.Registre()
        _qualifier_avec_interaction(reg, contrat_v1("R2"))
        marqueur, verdict = readiness.emettre_marqueur(reg, "R2", "2026-03-01T12:00:00+02:00")
        assert verdict is None
        attendu = encodage.encoder_canonique(
            {"owner": "Alice", "type_travaux": "renovation_totale", "ville": "Québec",
             "interaction_post_qualification": True},
            "R2", reg.tete(),
        )
        assert marqueur["empreinte"] == attendu

    def test_la_cle_signee_suit_la_version_donc_les_empreintes_v1_et_v2_different(self):
        reg1, reg2 = registre.Registre(), registre.Registre()
        _qualifier_avec_interaction(reg1, contrat_v1("R3", ville="Québec"))
        _qualifier_avec_interaction(reg2, contrat_v2("R3", ville="Québec"))
        m1, _ = readiness.emettre_marqueur(reg1, "R3", "2026-03-01T12:00:00+02:00")
        m2, _ = readiness.emettre_marqueur(reg2, "R3", "2026-03-01T12:00:00+02:00")
        assert m1["empreinte"] != m2["empreinte"]

    def test_service_retire_du_profil_apres_l_ingestion_rend_le_lead_non_pret(self, declarer_services):
        reg = registre.Registre()
        _qualifier_avec_interaction(reg, contrat_v2("R4"))
        marqueur, verdict = readiness.emettre_marqueur(reg, "R4", "2026-03-01T12:00:00+02:00")
        assert verdict is None
        declarer_services("revetement")  # gouttieres n'est plus offert
        assert readiness.evaluer(reg, "R4") is False
        assert readiness.verifier_marqueur(marqueur, reg) is False
        _, verdict = readiness.emettre_marqueur(reg, "R4", "2026-03-01T12:00:00+02:00")
        assert verdict["code"] == "REJ-TRANSITION-ILLEGALE"
        assert "service invalide 'gouttieres'" in verdict["detail"]

    def test_profil_absent_rend_le_lead_non_pret_fail_closed(self):
        reg = registre.Registre()
        _qualifier_avec_interaction(reg, contrat_v2("R5"))
        taxonomie.fichier_profil().unlink()
        assert readiness.evaluer(reg, "R5") is False

    def test_une_seule_copie_de_l_enum_v1_dans_m2(self):
        assert readiness.TYPES_TRAVAUX is contrats.TYPES_TRAVAUX
