import sys, hashlib
from pathlib import Path
import pytest
import yaml

_M1 = Path(__file__).resolve().parents[1]
_SRC = _M1 / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
import registre, contrats, verdicts, horodatage  # noqa: E402

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
    base["description_factuelle"] = "Remplacement complet de la toiture en bardeaux d'asphalte, incluant ventilation et solins, sur une surface d'environ 200 mètres carrés."
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
