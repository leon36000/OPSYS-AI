import sys
from pathlib import Path
import inspect
import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import qualification  # noqa: E402 (module inexistant → RED attendu)
import verdicts        # noqa: E402
import contrats        # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures de base
# ---------------------------------------------------------------------------
@pytest.fixture
def canal_texte():
    return "texte"


@pytest.fixture
def conv_id():
    return "test-qualif-001"


# ---------------------------------------------------------------------------
# Règle 1 : extraction de type_travaux
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("contenu, type_attendu", [
    ("Je souhaite une rénovation totale de ma propriété à Montréal, téléphone 514-555-0142.", "renovation_totale"),
    ("Nous voulons une extension pour la maison à Québec, courriel: client@test.ca.", "extension"),
    ("Le ravalement de la façade est prévu à Lévis, joignable au (450) 555-1234.", "ravalement"),
    ("L'isolation thermique est nécessaire dans le grenier à Gatineau, email: grenier@toto.com.", "isolation_thermique"),
    ("Nous avons un projet de type autre à Sherbrooke, téléphone 8195551212.", "autre"),
])
def test_extraction_type_travaux_positif(contenu, type_attendu, canal_texte, conv_id):
    resultat = qualification.qualifier(contenu, canal_texte, conv_id)
    assert "verdict" not in resultat, f"Échec inattendu : {resultat}"
    assert resultat.get("type_travaux") == type_attendu, \
        f"Type travaux attendu {type_attendu}, obtenu {resultat.get('type_travaux')}"


def test_extraction_type_travaux_negatif_rejet(canal_texte, conv_id):
    """Contenu sans aucun indice de type de travaux → REJ-QUALIF-INSUFFISANTE."""
    resultat = qualification.qualifier(
        "Je veux juste réparer une porte.", canal_texte, conv_id
    )
    assert "verdict" in resultat, "Un verdict de rejet est attendu"
    assert resultat["verdict"]["code"] == "REJ-QUALIF-INSUFFISANTE"


# ---------------------------------------------------------------------------
# Règle 2 : extraction de la ville
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("contenu, ville_attendue", [
    ("Extension à Montréal, téléphone 514-555-0142.", "Montréal"),
    ("Québec, rénovation complète, courriel: qc@test.ca.", "Québec"),
    ("Ravalement de façade à Laval, contactez-moi au 450-555-1234.", "Laval"),
    ("Isolation thermique à Gatineau, email: gat@toto.example.", "Gatineau"),
    ("Sherbrooke, besoin d'extension, téléphone 819-000-1111.", "Sherbrooke"),
    ("Extension à Trois-Rivières, urgence, appel 8195551212.", "Trois-Rivières"),
    ("Longueuil, projet autre, courriel: lg@test.ca.", "Longueuil"),
])
def test_extraction_ville_positif(contenu, ville_attendue, canal_texte, conv_id):
    resultat = qualification.qualifier(contenu, canal_texte, conv_id)
    assert "verdict" not in resultat, f"Rejet inattendu : {resultat}"
    assert resultat.get("ville") == ville_attendue, \
        f"Ville attendue {ville_attendue}, obtenu {resultat.get('ville')}"


def test_extraction_ville_absente_rejet(canal_texte, conv_id):
    resultat = qualification.qualifier(
        "Rénovation totale de ma cuisine.", canal_texte, conv_id
    )
    assert "verdict" in resultat
    assert resultat["verdict"]["code"] == "REJ-QUALIF-INSUFFISANTE"


def test_ville_non_quebecoise_rejet(canal_texte, conv_id):
    """Même si une ville est mentionnée, elle doit être reconnue (québécoise) sinon rejet."""
    resultat = qualification.qualifier(
        "Rénovation totale à Paris, téléphone 514-555-0142.", canal_texte, conv_id
    )
    assert "verdict" in resultat
    assert resultat["verdict"]["code"] == "REJ-QUALIF-INSUFFISANTE"


# ---------------------------------------------------------------------------
# Règle 3 : urgence_declaree (booléen explicite)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("contenu, urgence_attendue", [
    ("C'est urgent, il faut intervenir rapidement. Rénovation totale à Montréal, téléphone 514-555-0142.", True),
    ("Fuite active au sous-sol, dégât d'eau, extension à Québec, courriel: fuite@domaine.ca.", True),
    ("Au plus vite svp, ravalement à Laval, téléphone 450-000-1111.", True),
    ("Dégât d'eau constaté ce matin, isolation thermique à Gatineau, email: eau@test.ca.", True),
])
def test_urgence_declaree_true(contenu, urgence_attendue, canal_texte, conv_id):
    resultat = qualification.qualifier(contenu, canal_texte, conv_id)
    assert "verdict" not in resultat
    assert resultat.get("urgence_declaree") == urgence_attendue


def test_urgence_non_declaree_false(canal_texte, conv_id):
    """Sans marqueur d'urgence, la valeur doit être False, jamais inférée du ton."""
    resultat = qualification.qualifier(
        "Rénovation totale à Montréal. J'aimerais avoir un estimé, téléphone 514-555-0142.", canal_texte, conv_id
    )
    assert "verdict" not in resultat
    assert resultat.get("urgence_declaree") is False, \
        "L'urgence ne doit pas être devinée, elle est False par défaut"


# ---------------------------------------------------------------------------
# Règle 4 : aucun champ inventé, absence d'information → rejet
# ---------------------------------------------------------------------------
def test_aucun_champ_invente_type_manquant_rejet(canal_texte, conv_id):
    """Même avec ville et urgence, l'absence de type de travaux entraîne un rejet."""
    resultat = qualification.qualifier(
        "À Montréal, c'est très pressant, téléphone 514-555-0142.", canal_texte, conv_id
    )
    assert "verdict" in resultat
    assert resultat["verdict"]["code"] == "REJ-QUALIF-INSUFFISANTE"


def test_pas_de_champ_supplementaire_invente(canal_texte, conv_id):
    """Un lead réussi ne doit contenir que les champs prévus au contrat."""
    contenu = "Rénovation totale à Montréal, téléphone 514-555-0142."
    resultat = qualification.qualifier(contenu, canal_texte, conv_id)
    assert "verdict" not in resultat
    # Récupération de l'ensemble des clés autorisées par le contrat
    # (on s'appuie sur contrats.valider_lead pour garantir la conformité)
    try:
        contrats.valider_lead(resultat)
    except Exception as e:
        pytest.fail(f"Lead inattendu rejeté par le contrat : {e}")
    # Exemple de clé interdite : "prix_estime"
    assert "prix_estime" not in resultat, \
        "Aucun champ inventé ne doit apparaître (ex: prix_estime)"


# ---------------------------------------------------------------------------
# Règle 5 : opère sur le contenu filtré, ignore [CONTENU_NON_FIABLE]
# ---------------------------------------------------------------------------
def test_contenu_filtre_avec_marqueur_ignore(canal_texte, conv_id):
    """Le marqueur de neutralisation est ignoré ; les informations légitimes sont extraites."""
    contenu = "[CONTENU_NON_FIABLE] Rénovation totale à Montréal urgente, téléphone 514-555-0142."
    resultat = qualification.qualifier(contenu, canal_texte, conv_id)
    assert "verdict" not in resultat, f"Rejet inattendu : {resultat}"
    assert resultat.get("type_travaux") == "renovation_totale"
    assert resultat.get("ville") == "Montréal"
    assert resultat.get("urgence_declaree") is True


def test_marqueur_seul_provoque_rejet(canal_texte, conv_id):
    """Un contenu constitué uniquement du marqueur ne contient aucune info → rejet."""
    resultat = qualification.qualifier("[CONTENU_NON_FIABLE]", canal_texte, conv_id)
    assert "verdict" in resultat
    assert resultat["verdict"]["code"] == "REJ-QUALIF-INSUFFISANTE"


def test_marqueur_non_reinterprete_comme_type(canal_texte, conv_id):
    """Le marqueur ne doit pas être interprété comme un type de travaux 'autre'."""
    resultat = qualification.qualifier(
        "[CONTENU_NON_FIABLE] autre à Montréal, courriel: autre@domaine.ca.", canal_texte, conv_id
    )
    # Doit extraire "autre" normalement, pas à cause du marqueur
    assert "verdict" not in resultat
    assert resultat["type_travaux"] == "autre", \
        "Le type doit provenir du mot 'autre' présent, pas du marqueur"


# ---------------------------------------------------------------------------
# Règle 6 : zéro score, zéro LLM
# ---------------------------------------------------------------------------
def test_source_sans_score_ni_llm():
    src = inspect.getsource(qualification)
    interdits = ["score", "openai", "litellm", "requests", "confidence"]
    for mot in interdits:
        assert mot not in src, f"Chaîne interdite trouvée dans qualification : {mot}"


# ---------------------------------------------------------------------------
# Règle 7 : zéro réseau, zéro horloge
# ---------------------------------------------------------------------------
def test_source_sans_reseau_ni_horloge():
    src = inspect.getsource(qualification)
    interdits = ["urllib", "socket", "http.client", "datetime.now", "time.time"]
    for mot in interdits:
        assert mot not in src, f"Chaîne interdite trouvée dans qualification : {mot}"


# ---------------------------------------------------------------------------
# Règle 8 : déterminisme
# ---------------------------------------------------------------------------
def test_determinisme(canal_texte, conv_id):
    contenu = "Rénovation totale à Montréal urgent, téléphone 514-555-0142."
    r1 = qualification.qualifier(contenu, canal_texte, conv_id)
    r2 = qualification.qualifier(contenu, canal_texte, conv_id)
    assert r1 == r2, "Deux appels identiques doivent produire le même résultat"


# ---------------------------------------------------------------------------
# Règle 9 : lead qualifié valide selon contrats.valider_lead
# ---------------------------------------------------------------------------
def test_lead_qualifie_valide_selon_contrat(canal_texte, conv_id):
    contenu = "Rénovation totale à Montréal, téléphone 514-555-0142."
    lead = qualification.qualifier(contenu, canal_texte, conv_id)
    assert "verdict" not in lead, f"Rejet inattendu : {lead}"
    try:
        contrats.valider_lead(lead)
    except Exception as e:
        pytest.fail(f"Le lead qualifié n'est pas accepté par contrats.valider_lead : {e}")


def test_lead_avec_urgence_valide_contrat(canal_texte, conv_id):
    contenu = "Isolation thermique à Gatineau, dégât d'eau urgent, téléphone 819-555-1234."
    lead = qualification.qualifier(contenu, canal_texte, conv_id)
    assert "verdict" not in lead
    try:
        contrats.valider_lead(lead)
    except Exception as e:
        pytest.fail(f"Lead d'urgence rejeté par contrat : {e}")


def test_lead_id_encodage_injectif():
    import qualification

    # 1. Injectivité – concaténation naïve identique
    assert qualification._materiau_lead_id("AB", "X") != qualification._materiau_lead_id("A", "BX"), (
        "Les couples ('AB','X') et ('A','BX') ont produit le même matériau, "
        "l'encodage n'est pas injectif."
    )

    # 2. Cas de l'historique
    assert qualification._materiau_lead_id("A", " BC") != qualification._materiau_lead_id("A ", "BC"), (
        "Les couples ('A',' BC') et ('A ','BC') ont produit le même matériau, "
        "l'encodage n'est pas injectif."
    )

    # 3. Déterminisme du lead_id via qualifier
    lead1 = qualification.qualifier("Extension à Montréal, téléphone 514-555-0142.", "texte", "conv-1")["lead_id"]
    lead2 = qualification.qualifier("Extension à Montréal, téléphone 514-555-0142.", "texte", "conv-1")["lead_id"]
    assert lead1 == lead2, (
        f"Deux appels identiques à qualifier ont produit des lead_id différents : {lead1} vs {lead2}."
    )

    # 4. conversation_id différents => lead_id différents
    lead_a = qualification.qualifier("Extension à Montréal, téléphone 514-555-0142.", "texte", "conv-A")["lead_id"]
    lead_b = qualification.qualifier("Extension à Montréal, téléphone 514-555-0142.", "texte", "conv-B")["lead_id"]
    assert lead_a != lead_b, (
        f"Des conversations différentes (conv-A vs conv-B) ont produit le même lead_id : {lead_a}."
    )
