import hashlib
from pathlib import Path

import pytest
import yaml
from m1_front_office import contrats, verdicts

from opsys import taxonomie

_M1 = Path(__file__).resolve().parents[1]

# Sha256 fictifs (à geler plus tard)
SHA256_LEAD_V1 = "30f5acf271cdce065440ca96e103d4d3206b475b11839ba2e75acea255845f36"  # GEL 2026-07-26 (D-015)
SHA256_CHIFFRAGE_V1 = "15494b7ee41a13368a6c0720e1fafcb9cb5d3d302d4b2afe1b28527dd5eb0a23"  # GEL 2026-07-26 (D-015)

def _lead_conforme():
    return {
        "lead_id": "lead-001",
        "conversation_id": "conv-001",
        "contact": {
            "nom": "Jean Tremblay",
            "telephone": "418-555-1234",
            "courriel": "jean@example.com"
        },
        "type_travaux": "renovation_totale",
        "ville": "Québec",
        "urgence_declaree": True,
        "canal": "telephone"
    }

def _chiffrage_conforme():
    base = _lead_conforme()
    base["description_factuelle"] = (
        "Remplacement complet de la toiture en bardeaux d'asphalte, incluant ventilation et solins, "
        "sur une surface d'environ 200 mètres carrés."
    )
    return base

class TestContratsGeles:
    def test_sha256_lead(self):
        chemin = _M1 / "contracts" / "m1-lead-qualifie.v1.yaml"
        contenu = chemin.read_bytes()
        sha256 = hashlib.sha256(contenu).hexdigest()
        assert sha256 == SHA256_LEAD_V1, f"Le contrat lead a changé : {sha256}"

    def test_sha256_chiffrage(self):
        chemin = _M1 / "contracts" / "m1-demande-chiffrage.v1.yaml"
        contenu = chemin.read_bytes()
        sha256 = hashlib.sha256(contenu).hexdigest()
        assert sha256 == SHA256_CHIFFRAGE_V1, f"Le contrat chiffrage a changé : {sha256}"

class TestValiderLead:
    def test_lead_valide(self):
        verdict = contrats.valider_lead(_lead_conforme())
        assert verdict["code"] == "EVT-CONTRAT-VALIDE"

    def test_lead_id_manquant(self):
        lead = _lead_conforme()
        del lead["lead_id"]
        with pytest.raises(ValueError, match="lead_id"):
            contrats.valider_lead(lead)

    def test_contact_entierement_vide(self):
        lead = _lead_conforme()
        lead["contact"] = {"nom": "", "telephone": "", "courriel": ""}
        with pytest.raises(ValueError, match="contact"):
            contrats.valider_lead(lead)

    def test_type_travaux_hors_enum(self):
        lead = _lead_conforme()
        lead["type_travaux"] = "peinture"
        with pytest.raises(ValueError) as exc:
            contrats.valider_lead(lead)
        assert "REJ-ENUM-INVALIDE" in str(exc.value)

    def test_ville_vide(self):
        lead = _lead_conforme()
        lead["ville"] = ""
        with pytest.raises(ValueError, match="ville"):
            contrats.valider_lead(lead)

    def test_canal_hors_enum(self):
        lead = _lead_conforme()
        lead["canal"] = "fax"
        with pytest.raises(ValueError) as exc:
            contrats.valider_lead(lead)
        assert "REJ-ENUM-INVALIDE" in str(exc.value)

class TestValiderChiffrage:
    def test_chiffrage_valide(self):
        verdict = contrats.valider_chiffrage(_chiffrage_conforme())
        assert verdict["code"] == "EVT-CONTRAT-VALIDE"

    def test_description_trop_courte(self):
        chiffrage = _chiffrage_conforme()
        chiffrage["description_factuelle"] = "trop court"
        with pytest.raises(ValueError, match="description"):
            contrats.valider_chiffrage(chiffrage)

    def test_description_trop_longue(self):
        chiffrage = _chiffrage_conforme()
        chiffrage["description_factuelle"] = "A" * 501
        with pytest.raises(ValueError, match="description"):
            contrats.valider_chiffrage(chiffrage)

    def test_description_contient_prix(self):
        chiffrage = _chiffrage_conforme()
        chiffrage["description_factuelle"] = "Réparation toiture pour 5000 $ et remplacement des gouttières."
        with pytest.raises(ValueError, match="prix"):
            contrats.valider_chiffrage(chiffrage)

    def test_description_contient_date(self):
        chiffrage = _chiffrage_conforme()
        chiffrage["description_factuelle"] = "Les travaux débuteront le 12 mars prochain et dureront trois semaines."
        with pytest.raises(ValueError, match="date"):
            contrats.valider_chiffrage(chiffrage)

class TestVerdictsStables:
    def test_codes_verdicts_dans_verdicts_py(self):
        # On ne peut pas tester exhaustivement ici, mais on vérifie que les identifiants utilisés
        # dans les exceptions sont bien présents dans verdicts.py
        codes_attendu = ["REJ-ENUM-INVALIDE", "REJ-CHAMP-MANQUANT", "REJ-CHAMP-VIDE"]
        for code in codes_attendu:
            assert hasattr(verdicts, code), f"Code {code} absent de verdicts"
        # Vérifier qu'aucun verdict ne contient 'score'
        for attr_name in dir(verdicts):
            if attr_name.startswith("REJ") or attr_name.startswith("EVT"):
                assert "score" not in attr_name.lower()


def test_valider_lead_retourne_verdict_evt_contrat_valide():
    lead = _lead_conforme()
    verdict = contrats.valider_lead(lead)
    assert verdict["code"] == "EVT-CONTRAT-VALIDE"
    assert verdict["statut"] == ""
    assert "detail" in verdict

def test_valider_chiffrage_retourne_verdict_evt_contrat_valide():
    demande = _chiffrage_conforme()
    verdict = contrats.valider_chiffrage(demande)
    assert verdict["code"] == "EVT-CONTRAT-VALIDE"
    assert verdict["statut"] == ""
    assert "detail" in verdict


class TestHashContrat:
    """hash_contrat doit lire les fichiers réels sous departments/m01-front-office/contracts/,
    pas sous src/contracts/ (bug d'audit : _CONTRACTS_DIR pointait un niveau trop haut)."""

    def test_hash_contrat_lead_trouve_le_fichier_reel(self):
        sha256 = contrats.hash_contrat("m1-lead-qualifie.v1.yaml")
        assert sha256 == SHA256_LEAD_V1

    def test_hash_contrat_chiffrage_trouve_le_fichier_reel(self):
        sha256 = contrats.hash_contrat("m1-demande-chiffrage.v1.yaml")
        assert sha256 == SHA256_CHIFFRAGE_V1

    def test_hash_contrat_fichier_inconnu_leve_filenotfounderror(self):
        with pytest.raises(FileNotFoundError):
            contrats.hash_contrat("m1-inexistant.v1.yaml")

    def test_hash_contrat_repertoire_contracts_est_celui_du_module(self):
        """PROUVE que hash_contrat lit sous departments/m01-front-office/contracts/,
        pas sous src/contracts/ (qui n'existe pas)."""
        assert not (_M1 / "src" / "contracts").exists(), (
            "src/contracts ne doit pas exister : c'est le mauvais chemin, celui du bug"
        )
        assert (_M1 / "contracts" / "m1-lead-qualifie.v1.yaml").is_file()


# ---------------------------------------------------------------------------
# Contrat LeadQualifie v2 (PLAN T0.13) : `service` de la taxonomie du socle, version explicite
# ---------------------------------------------------------------------------
SHA256_LEAD_V2 = "a606aa9445c8604dc740ca91a5cac3a220a0262dc7ef73555c51315c77c11a4d"  # GEL T0.13


def _lead_v2_conforme():
    return {
        "schema_version": 2,
        "lead_id": "lead-002",
        "conversation_id": "conv-002",
        "contact": {"nom": "Jeanne Gagnon", "telephone": "418-555-9876"},
        "service": "gouttieres",
        "ville": "Québec",
        "urgence_declaree": False,
        "canal": "formulaire",
    }


@pytest.fixture
def services_declares(declarer_services):
    declarer_services()


class TestContratV2Gele:
    def test_sha256_lead_v2(self):
        empreinte = hashlib.sha256((_M1 / "contracts" / "m1-lead-qualifie.v2.yaml").read_bytes()).hexdigest()
        assert empreinte == SHA256_LEAD_V2

    def test_hash_contrat_v2_est_distinct_de_la_v1_et_la_v1_reste_intacte(self):
        assert contrats.hash_contrat("m1-lead-qualifie.v2.yaml") == SHA256_LEAD_V2
        assert contrats.hash_contrat("m1-lead-qualifie.v1.yaml") == SHA256_LEAD_V1
        assert SHA256_LEAD_V1 != SHA256_LEAD_V2

    def test_les_champs_du_yaml_v2_sont_ceux_que_le_validateur_exige(self):
        contrat = yaml.safe_load((_M1 / "contracts" / "m1-lead-qualifie.v2.yaml").read_text(encoding="utf-8"))
        assert contrat["schema_version"] == contrats.VERSION_LEAD_V2
        obligatoires = {c["name"] for c in contrat["fields"] if c["required"]}
        optionnels = {c["name"] for c in contrat["fields"] if not c["required"]}
        assert obligatoires == set(contrats._CHAMPS_LEAD_V2)
        assert optionnels == set(contrats._CHAMPS_LEAD_V2_OPTIONNELS)
        assert "type_travaux" not in obligatoires | optionnels
        utm = next(c for c in contrat["fields"] if c["name"] == "utm")
        assert all(cle in " ".join(utm["constraints"]) for cle in contrats._CLES_UTM)


class TestValiderLeadV2:
    def test_lead_v2_valide(self, services_declares):
        verdict = contrats.valider_lead(_lead_v2_conforme())
        assert verdict["code"] == "EVT-CONTRAT-VALIDE"

    def test_lead_v1_reste_accepte_tel_quel(self, services_declares):
        assert contrats.valider_lead(_lead_conforme())["code"] == "EVT-CONTRAT-VALIDE"

    def test_v1_reste_accepte_meme_sans_profil_d_entreprise(self):
        """Un lead v1 n'a pas de service : il ne dépend d'aucune configuration."""
        assert contrats.valider_lead(_lead_conforme())["code"] == "EVT-CONTRAT-VALIDE"

    def test_service_non_declare_refuse_avec_la_marche_a_suivre(self, declarer_services):
        declarer_services("revetement")
        with pytest.raises(ValueError) as exc:
            contrats.valider_lead(_lead_v2_conforme())
        assert "REJ-ENUM-INVALIDE" in str(exc.value)
        assert "entreprise.yaml" in str(exc.value)

    def test_sans_profil_tout_service_est_refuse_et_dit_quoi_configurer(self):
        with pytest.raises(ValueError) as exc:
            contrats.valider_lead(_lead_v2_conforme())
        assert "REJ-SERVICE-NON-CONFIGURE" in str(exc.value)

    def test_pas_de_repli_sur_autre(self, services_declares):
        lead = _lead_v2_conforme()
        lead["service"] = "autre"
        with pytest.raises(ValueError, match="REJ-ENUM-INVALIDE"):
            contrats.valider_lead(lead)

    @pytest.mark.parametrize("version", [1, 3, "2", True, 2.0, None])
    def test_version_explicite_jamais_devinee(self, services_declares, version):
        lead = _lead_v2_conforme()
        lead["schema_version"] = version
        with pytest.raises(ValueError, match="schema_version"):
            contrats.valider_lead(lead)

    def test_lead_v1_qui_porte_service_est_refuse_pas_devine_v2(self, services_declares):
        lead = _lead_conforme()
        del lead["type_travaux"]
        lead["service"] = "gouttieres"
        with pytest.raises(ValueError, match="type_travaux"):
            contrats.valider_lead(lead)

    def test_lead_v2_qui_porte_type_travaux_est_refuse(self, services_declares):
        lead = _lead_v2_conforme()
        lead["type_travaux"] = "renovation_totale"
        with pytest.raises(ValueError, match="champ inconnu en v2"):
            contrats.valider_lead(lead)

    @pytest.mark.parametrize("champ", ["lead_id", "conversation_id", "contact", "service", "ville",
                                       "urgence_declaree", "canal"])
    def test_champ_obligatoire_manquant(self, services_declares, champ):
        lead = _lead_v2_conforme()
        del lead[champ]
        with pytest.raises(ValueError, match=champ):
            contrats.valider_lead(lead)

    def test_memes_controles_communs_qu_en_v1(self, services_declares):
        for champ, valeur, motif in (("canal", "fax", "REJ-ENUM-INVALIDE"), ("ville", "", "ville"),
                                     ("contact", {"nom": ""}, "contact"), ("urgence_declaree", "oui", "urgence")):
            lead = _lead_v2_conforme()
            lead[champ] = valeur
            with pytest.raises(ValueError, match=motif):
                contrats.valider_lead(lead)

    def test_cles_optionnelles_acceptees_et_validees_si_presentes(self, services_declares):
        lead = _lead_v2_conforme()
        lead.update(source="formulaire_site", campagne="printemps", utm={"utm_source": "google"})
        assert contrats.valider_lead(lead)["code"] == "EVT-CONTRAT-VALIDE"
        for cle, valeur in (("source", ""), ("campagne", 3), ("utm", {}), ("utm", {"utm_x": "a"}),
                            ("utm", {"utm_source": ""})):
            mauvais = _lead_v2_conforme()
            mauvais[cle] = valeur
            with pytest.raises(ValueError, match="REJ-CONTRAT-INVALIDE"):
                contrats.valider_lead(mauvais)

    def test_services_fournis_par_l_appelant(self):
        pergola = taxonomie.Service("pose_pergola", "Pose de pergolas")
        lead = _lead_v2_conforme()
        lead["service"] = "pose_pergola"
        assert contrats.valider_lead(lead, services=(pergola,))["code"] == "EVT-CONTRAT-VALIDE"

    def test_la_demande_de_chiffrage_v1_reste_validee_contre_le_lead_v1(self, services_declares):
        v2 = _lead_v2_conforme()
        v2["description_factuelle"] = _chiffrage_conforme()["description_factuelle"]
        with pytest.raises(ValueError, match="type_travaux"):
            contrats.valider_chiffrage(v2)
        assert contrats.valider_chiffrage(_chiffrage_conforme())["code"] == "EVT-CONTRAT-VALIDE"
