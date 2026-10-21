import m4_field_ops.contrats as contrats_mod
import pytest


# ------------------------------------------------------------------ fixtures
@pytest.fixture
def contrat_valide():
    return {
        "lead_id": "L01",
        "conversation_id": "C01",
        "type_travaux": "renovation_totale",
        "ville": "Paris",
        "canal": "telephone",
        "contact": {"nom": "Dupont", "telephone": "0102030405"},
        "urgence_declaree": True,
    }

@pytest.fixture
def marqueur_valide(contrat_valide):
    return {
        "readiness_ok": True,
        "lead_id": contrat_valide["lead_id"],
        "hash_tete_registre": "a" * 64,  # 64 hex minuscule
        "horodatage": "2025-06-01T12:00:00+00:00",  # valide
        "empreinte": "b" * 64,
    }

# --- tests valider_structure ---
def test_valider_structure_contrat_non_dict():
    ok, code = contrats_mod.valider_structure([])
    assert ok is False
    assert code == "REJ-CONTRAT-INVALIDE"

def test_valider_structure_champ_obligatoire_manquant(contrat_valide):
    c = contrat_valide.copy()
    del c["lead_id"]
    ok, code = contrats_mod.valider_structure(c)
    assert ok is False
    assert code == "REJ-CHAMP-MANQUANT"

def test_valider_structure_champ_inconnu(contrat_valide):
    c = contrat_valide.copy()
    c["inconnu"] = 1
    ok, code = contrats_mod.valider_structure(c)
    assert ok is False
    assert code == "REJ-CONTRAT-INVALIDE"

def test_valider_structure_lead_id_non_str(contrat_valide):
    c = contrat_valide.copy()
    c["lead_id"] = 123
    ok, code = contrats_mod.valider_structure(c)
    assert ok is False
    assert code == "REJ-CONTRAT-INVALIDE"

def test_valider_structure_lead_id_vide():
    c = {
        "lead_id": "",
        "conversation_id": "C1",
        "type_travaux": "renovation_totale",
        "ville": "Paris",
        "canal": "telephone",
        "contact": {"nom": "X"},
        "urgence_declaree": True,
    }
    ok, code = contrats_mod.valider_structure(c)
    assert ok is False
    assert code == "REJ-CHAMP-VIDE"

def test_valider_structure_conversation_id_vide():
    c = {
        "lead_id": "L1",
        "conversation_id": "",
        "type_travaux": "renovation_totale",
        "ville": "Paris",
        "canal": "telephone",
        "contact": {"nom": "X"},
        "urgence_declaree": True,
    }
    ok, code = contrats_mod.valider_structure(c)
    assert ok is False
    assert code == "REJ-CHAMP-VIDE"

def test_valider_structure_ville_vide():
    c = {
        "lead_id": "L1",
        "conversation_id": "C1",
        "type_travaux": "renovation_totale",
        "ville": "",
        "canal": "telephone",
        "contact": {"nom": "X"},
        "urgence_declaree": True,
    }
    ok, code = contrats_mod.valider_structure(c)
    assert ok is False
    assert code == "REJ-CHAMP-VIDE"

def test_valider_structure_type_travaux_invalide(contrat_valide):
    c = contrat_valide.copy()
    c["type_travaux"] = "demo"
    ok, code = contrats_mod.valider_structure(c)
    assert ok is False
    assert code == "REJ-ENUM-INVALIDE"

def test_valider_structure_canal_invalide(contrat_valide):
    c = contrat_valide.copy()
    c["canal"] = "fax"
    ok, code = contrats_mod.valider_structure(c)
    assert ok is False
    assert code == "REJ-ENUM-INVALIDE"

def test_valider_structure_contact_cle_etrangere(contrat_valide):
    c = contrat_valide.copy()
    c["contact"] = {"nom": "X", "adresse": "123 rue"}  # adresse non autorisée
    ok, code = contrats_mod.valider_structure(c)
    assert ok is False
    assert code == "REJ-CONTRAT-INVALIDE"

def test_valider_structure_contact_vide(contrat_valide):
    c = contrat_valide.copy()
    c["contact"] = {"nom": "", "telephone": "", "courriel": ""}
    ok, code = contrats_mod.valider_structure(c)
    assert ok is False
    assert code == "REJ-CHAMP-VIDE"

def test_valider_structure_urgence_declaree_int_1(contrat_valide):
    c = contrat_valide.copy()
    c["urgence_declaree"] = 1
    ok, code = contrats_mod.valider_structure(c)
    assert ok is False
    assert code == "REJ-CONTRAT-INVALIDE"

def test_valider_structure_urgence_declaree_str(contrat_valide):
    c = contrat_valide.copy()
    c["urgence_declaree"] = "True"
    ok, code = contrats_mod.valider_structure(c)
    assert ok is False
    assert code == "REJ-CONTRAT-INVALIDE"

def test_valider_structure_valide(contrat_valide):
    ok, code = contrats_mod.valider_structure(contrat_valide)
    assert ok is True
    assert code == ""

# --- tests valider_marqueur_readiness ---
def test_valider_marqueur_non_dict():
    ok, code = contrats_mod.valider_marqueur_readiness([], "L1")
    assert ok is False
    assert code == "REJ-READINESS-NON-FRANCHIE"

def test_valider_marqueur_cle_manquante(marqueur_valide):
    m = marqueur_valide.copy()
    del m["empreinte"]
    ok, code = contrats_mod.valider_marqueur_readiness(m, marqueur_valide["lead_id"])
    assert ok is False
    assert code == "REJ-READINESS-NON-FRANCHIE"

def test_valider_marqueur_cle_etrangere(marqueur_valide):
    m = marqueur_valide.copy()
    m["extra"] = "nope"
    ok, code = contrats_mod.valider_marqueur_readiness(m, marqueur_valide["lead_id"])
    assert ok is False
    assert code == "REJ-READINESS-NON-FRANCHIE"

def test_valider_marqueur_readiness_ok_int_1(marqueur_valide):
    m = marqueur_valide.copy()
    m["readiness_ok"] = 1
    ok, code = contrats_mod.valider_marqueur_readiness(m, marqueur_valide["lead_id"])
    assert ok is False
    assert code == "REJ-READINESS-NON-FRANCHIE"

def test_valider_marqueur_readiness_ok_false(marqueur_valide):
    m = marqueur_valide.copy()
    m["readiness_ok"] = False
    ok, code = contrats_mod.valider_marqueur_readiness(m, marqueur_valide["lead_id"])
    assert ok is False
    assert code == "REJ-READINESS-NON-FRANCHIE"

def test_valider_marqueur_lead_id_different(marqueur_valide):
    ok, code = contrats_mod.valider_marqueur_readiness(marqueur_valide, "OTHER")
    assert ok is False
    assert code == "REJ-READINESS-NON-FRANCHIE"

def test_valider_marqueur_horodatage_sans_fuseau(marqueur_valide):
    m = marqueur_valide.copy()
    m["horodatage"] = "2025-06-01T12:00:00"  # pas de zone
    ok, code = contrats_mod.valider_marqueur_readiness(m, marqueur_valide["lead_id"])
    assert ok is False
    assert code == "REJ-HORODATAGE-INVALIDE"

def test_valider_marqueur_empreinte_63_chars(marqueur_valide):
    m = marqueur_valide.copy()
    m["empreinte"] = "a" * 63
    ok, code = contrats_mod.valider_marqueur_readiness(m, marqueur_valide["lead_id"])
    assert ok is False
    assert code == "REJ-READINESS-NON-FRANCHIE"

def test_valider_marqueur_empreinte_majuscules(marqueur_valide):
    m = marqueur_valide.copy()
    m["empreinte"] = "A" * 64
    ok, code = contrats_mod.valider_marqueur_readiness(m, marqueur_valide["lead_id"])
    assert ok is False
    assert code == "REJ-READINESS-NON-FRANCHIE"

def test_valider_marqueur_empreinte_non_str(marqueur_valide):
    m = marqueur_valide.copy()
    m["empreinte"] = 123
    ok, code = contrats_mod.valider_marqueur_readiness(m, marqueur_valide["lead_id"])
    assert ok is False
    assert code == "REJ-READINESS-NON-FRANCHIE"

def test_valider_marqueur_hash_tete_registre_entier(marqueur_valide):
    m = marqueur_valide.copy()
    m["hash_tete_registre"] = 42
    ok, code = contrats_mod.valider_marqueur_readiness(m, marqueur_valide["lead_id"])
    assert ok is False
    assert code == "REJ-READINESS-NON-FRANCHIE"

def test_valider_marqueur_hash_tete_none_valide(marqueur_valide):
    m = marqueur_valide.copy()
    m["hash_tete_registre"] = None
    ok, code = contrats_mod.valider_marqueur_readiness(m, marqueur_valide["lead_id"])
    assert ok is True
    assert code == ""

def test_valider_marqueur_valide(marqueur_valide):
    ok, code = contrats_mod.valider_marqueur_readiness(marqueur_valide, marqueur_valide["lead_id"])
    assert ok is True
    assert code == ""

# --- tests valider_entree ---
def test_valider_entree_valide(contrat_valide, marqueur_valide):
    ok, verdict = contrats_mod.valider_entree(contrat_valide, marqueur_valide)
    assert ok is True
    assert verdict is None

def test_valider_entree_frontiere_prix(contrat_valide, marqueur_valide):
    c = contrat_valide.copy()
    c["prix"] = 100  # champ interdit
    ok, verdict = contrats_mod.valider_entree(c, marqueur_valide)
    assert ok is False
    assert verdict["code"] == "REJ-FRONTIERE-VIOLEE"
    assert "prix" in verdict["detail"]

def test_valider_entree_frontiere_priority_over_structure(marqueur_valide):
    # Contrat avec champ interdit ET manque lead_id -> priorité frontière
    c = {"prix": 10, "conversation_id": "C1", "type_travaux": "renovation_totale",
         "ville": "X", "canal": "telephone", "contact": {"nom": "X"}, "urgence_declaree": True}
    ok, verdict = contrats_mod.valider_entree(c, marqueur_valide)
    assert ok is False
    assert verdict["code"] == "REJ-FRONTIERE-VIOLEE"

def test_valider_entree_structure_error_before_marqueur(contrat_valide, marqueur_valide):
    c = contrat_valide.copy()
    c["type_travaux"] = "inconnu"  # faute structurale
    ok, verdict = contrats_mod.valider_entree(c, marqueur_valide)
    assert ok is False
    assert verdict["code"] == "REJ-ENUM-INVALIDE"

def test_valider_entree_marqueur_invalide_apres_structure_valide(contrat_valide):
    m = {
        "readiness_ok": False,
        "lead_id": contrat_valide["lead_id"],
        "hash_tete_registre": None,
        "horodatage": "2025-06-01T12:00:00+00:00",
        "empreinte": "c" * 64,
    }
    ok, verdict = contrats_mod.valider_entree(contrat_valide, m)
    assert ok is False
    assert verdict["code"] == "REJ-READINESS-NON-FRANCHIE"

def test_valider_entree_frontiere_imbriquee_contact(contrat_valide, marqueur_valide):
    # contact contient une clé interdite ("engagement")
    c = contrat_valide.copy()
    c["contact"] = {"nom": "X", "engagement": "oui"}
    ok, verdict = contrats_mod.valider_entree(c, marqueur_valide)
    assert ok is False
    assert verdict["code"] == "REJ-FRONTIERE-VIOLEE"
    assert "contact.engagement" in verdict["detail"]
