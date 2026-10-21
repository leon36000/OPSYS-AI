import inspect

import pytest
from m1_front_office import contrats, qualification

from opsys import taxonomie

# ---------------------------------------------------------------------------
# Zone desservie de test — correctif d'audit : qualification.py ne code plus
# aucune ville en dur, la zone est fournie par l'appelant. Cette liste (les
# 13 villes historiques du module) devient une donnée de TEST explicite,
# passée à chaque appel de qualifier() dans ce fichier.
# ---------------------------------------------------------------------------
ZONE_DESSERVIE_TEST = (
    "Montréal",
    "Québec",
    "Laval",
    "Gatineau",
    "Sherbrooke",
    "Trois-Rivières",
    "Longueuil",
    "Lévis",
    "Saguenay",
    "Terrebonne",
    "Granby",
    "Saint-Jérôme",
    "Shawinigan",
)


# ---------------------------------------------------------------------------
# Fixtures de base
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _services_declares(declarer_services):
    """L'instance de test déclare les quatre services du catalogue de référence (PLAN T0.13) :
    sans profil, la qualification refuse (voir test_sans_profil_...)."""
    declarer_services()


@pytest.fixture
def canal_texte():
    return "texte"


@pytest.fixture
def conv_id():
    return "test-qualif-001"


# ---------------------------------------------------------------------------
# Règle 1 : extraction du service (taxonomie du socle, profil d'entreprise)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("contenu, service_attendu", [
    ("Je souhaite remplacer mes gouttières à Montréal, téléphone 514-555-0142.", "gouttieres"),
    ("Nos descentes pluviales débordent, nous sommes à Laval, téléphone 450-555-1111.", "gouttieres"),
    ("Nous voulons un nouveau revêtement extérieur à Québec, courriel: client@test.ca.", "revetement"),
    ("Du siding à remplacer à Granby, courriel: siding@test.ca.", "revetement"),
    ("Le soffite est abîmé à Lévis, joignable au (450) 555-1234.", "soffite_fascia"),
    ("Le fascia a pourri, nous sommes à Gatineau, email: grenier@toto.com.", "soffite_fascia"),
    ("Nous avons besoin d'une réparation à Sherbrooke, téléphone 8195551212.", "reparation"),
    ("Il faut réparer notre balcon à Longueuil, courriel: lg@test.ca.", "reparation"),
])
def test_extraction_service_positif(contenu, service_attendu, canal_texte, conv_id):
    resultat = qualification.qualifier(contenu, canal_texte, conv_id, ZONE_DESSERVIE_TEST)
    assert "verdict" not in resultat, f"Échec inattendu : {resultat}"
    assert resultat.get("service") == service_attendu, \
        f"Service attendu {service_attendu}, obtenu {resultat.get('service')}"


@pytest.mark.parametrize("contenu", [
    "GOUTTIERES à remplacer à Montréal, téléphone 514-555-0142.",  # majuscules, sans accent
    "Mes Gouttières sont brisées à Montréal, téléphone 514-555-0142.",
    "Les descentes de gouttière sont percées à Montréal, téléphone 514-555-0142.",
])
def test_extraction_service_ignore_casse_accents_et_pluriel(contenu, canal_texte, conv_id):
    resultat = qualification.qualifier(contenu, canal_texte, conv_id, ZONE_DESSERVIE_TEST)
    assert resultat.get("service") == "gouttieres", resultat


def test_extraction_service_negatif_rejet(canal_texte, conv_id):
    """Contenu sans aucun indice d'un service déclaré → REJ-QUALIF-INSUFFISANTE, jamais un repli."""
    resultat = qualification.qualifier(
        "Je veux juste peindre une porte à Montréal, téléphone 514-555-0142.",
        canal_texte, conv_id, ZONE_DESSERVIE_TEST,
    )
    assert "verdict" in resultat, "Un verdict de rejet est attendu"
    assert resultat["verdict"]["code"] == "REJ-QUALIF-INSUFFISANTE"
    assert "aucun service" in resultat["verdict"]["detail"]


def test_plusieurs_services_evoques_ne_sont_pas_qualifies(canal_texte, conv_id):
    """Le lead porte UN service : deux services évoqués = ambigu, on demande lequel (fail-closed)."""
    resultat = qualification.qualifier(
        "Nos gouttières et notre soffite sont abîmés à Montréal, téléphone 514-555-0142.",
        canal_texte, conv_id, ZONE_DESSERVIE_TEST,
    )
    assert resultat["verdict"]["code"] == "REJ-QUALIF-INSUFFISANTE"
    assert "gouttieres, soffite_fascia" in resultat["verdict"]["detail"]


def test_service_non_declare_par_l_entreprise_est_ignore(canal_texte, conv_id, declarer_services):
    """Le revêtement existe au catalogue mais cette entreprise ne l'offre pas : pas de lead."""
    declarer_services("gouttieres", "soffite_fascia")
    resultat = qualification.qualifier(
        "Nous voulons un revêtement neuf à Montréal, téléphone 514-555-0142.",
        canal_texte, conv_id, ZONE_DESSERVIE_TEST,
    )
    assert resultat["verdict"]["code"] == "REJ-QUALIF-INSUFFISANTE"


def test_sans_profil_d_entreprise_la_qualification_refuse_et_dit_quoi_configurer(canal_texte, conv_id):
    """Fail-closed : aucun service par défaut n'est inventé pour une entreprise sans profil."""
    taxonomie.fichier_profil().unlink()
    with pytest.raises(ValueError) as exc:
        qualification.qualifier(
            "Gouttières à Montréal, téléphone 514-555-0142.", canal_texte, conv_id, ZONE_DESSERVIE_TEST
        )
    assert "REJ-SERVICE-NON-CONFIGURE" in str(exc.value)
    assert "entreprise.yaml" in str(exc.value)


def test_services_fournis_par_l_appelant_priment_sur_le_profil(canal_texte, conv_id):
    pergola = taxonomie.Service("pose_pergola", "Pose de pergolas", ("pergola",))
    resultat = qualification.qualifier(
        "Une pergola à Montréal, téléphone 514-555-0142.", canal_texte, conv_id, ZONE_DESSERVIE_TEST,
        services=(pergola,),
    )
    assert resultat["service"] == "pose_pergola"


def test_service_propre_d_une_autre_pme_sans_mot_cle_n_est_jamais_devine(canal_texte, conv_id):
    sans_termes = taxonomie.Service("pose_pergola", "Pose de pergolas")
    resultat = qualification.qualifier(
        "Une pergola à Montréal, téléphone 514-555-0142.", canal_texte, conv_id, ZONE_DESSERVIE_TEST,
        services=(sans_termes,),
    )
    assert resultat["verdict"]["code"] == "REJ-QUALIF-INSUFFISANTE"


def test_le_lead_emis_est_un_lead_v2_sans_type_travaux(canal_texte, conv_id):
    lead = qualification.qualifier(
        "Gouttières à Montréal, téléphone 514-555-0142.", canal_texte, conv_id, ZONE_DESSERVIE_TEST
    )
    assert lead["schema_version"] == 2
    assert lead["service"] == "gouttieres"
    assert "type_travaux" not in lead
    assert set(lead) == {
        "schema_version", "lead_id", "service", "ville", "urgence_declaree", "canal",
        "conversation_id", "contact",
    }


def test_provenance_marketing_transmise_telle_quelle_ou_absente(canal_texte, conv_id):
    contenu = "Gouttières à Montréal, téléphone 514-555-0142."
    sans = qualification.qualifier(contenu, canal_texte, conv_id, ZONE_DESSERVIE_TEST)
    assert not {"source", "utm", "campagne"} & set(sans), "jamais de valeur par défaut inventée"
    avec = qualification.qualifier(
        contenu, canal_texte, conv_id, ZONE_DESSERVIE_TEST,
        source="formulaire_site", utm={"utm_source": "google"}, campagne="printemps",
    )
    assert avec["source"] == "formulaire_site"
    assert avec["utm"] == {"utm_source": "google"}
    assert avec["campagne"] == "printemps"
    contrats.valider_lead(avec)


# ---------------------------------------------------------------------------
# Règle 2 : extraction de la ville
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("contenu, ville_attendue", [
    ("Gouttières à Montréal, téléphone 514-555-0142.", "Montréal"),
    ("Québec, revêtement extérieur, courriel: qc@test.ca.", "Québec"),
    ("Remplacement du soffite à Laval, contactez-moi au 450-555-1234.", "Laval"),
    ("Fascia abîmé à Gatineau, email: gat@toto.example.", "Gatineau"),
    ("Sherbrooke, besoin d'une réparation, téléphone 819-000-1111.", "Sherbrooke"),
    ("Gouttières à Trois-Rivières, urgence, appel 8195551212.", "Trois-Rivières"),
    ("Longueuil, siding à changer, courriel: lg@test.ca.", "Longueuil"),
])
def test_extraction_ville_positif(contenu, ville_attendue, canal_texte, conv_id):
    resultat = qualification.qualifier(contenu, canal_texte, conv_id, ZONE_DESSERVIE_TEST)
    assert "verdict" not in resultat, f"Rejet inattendu : {resultat}"
    assert resultat.get("ville") == ville_attendue, \
        f"Ville attendue {ville_attendue}, obtenu {resultat.get('ville')}"


def test_extraction_ville_absente_rejet(canal_texte, conv_id):
    resultat = qualification.qualifier(
        "Gouttières à remplacer.", canal_texte, conv_id, ZONE_DESSERVIE_TEST
    )
    assert "verdict" in resultat
    assert resultat["verdict"]["code"] == "REJ-QUALIF-INSUFFISANTE"


def test_ville_non_quebecoise_rejet(canal_texte, conv_id):
    """Même si une ville est mentionnée, elle doit être reconnue (québécoise) sinon rejet."""
    resultat = qualification.qualifier(
        "Gouttières à Paris, téléphone 514-555-0142.", canal_texte, conv_id, ZONE_DESSERVIE_TEST
    )
    assert "verdict" in resultat
    assert resultat["verdict"]["code"] == "REJ-QUALIF-INSUFFISANTE"


# ---------------------------------------------------------------------------
# Règle 3 : urgence_declaree (booléen explicite)
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("contenu, urgence_attendue", [
    ("C'est urgent, il faut intervenir rapidement. Gouttières à Montréal, téléphone 514-555-0142.", True),
    ("Fuite active au sous-sol, dégât d'eau, revêtement à Québec, courriel: fuite@domaine.ca.", True),
    ("Au plus vite svp, soffite à Laval, téléphone 450-000-1111.", True),
    ("Dégât d'eau constaté ce matin, fascia à Gatineau, email: eau@test.ca.", True),
])
def test_urgence_declaree_true(contenu, urgence_attendue, canal_texte, conv_id):
    resultat = qualification.qualifier(contenu, canal_texte, conv_id, ZONE_DESSERVIE_TEST)
    assert "verdict" not in resultat
    assert resultat.get("urgence_declaree") == urgence_attendue


def test_urgence_non_declaree_false(canal_texte, conv_id):
    """Sans marqueur d'urgence, la valeur doit être False, jamais inférée du ton."""
    resultat = qualification.qualifier(
        "Gouttières à Montréal. J'aimerais avoir un estimé, téléphone 514-555-0142.",
        canal_texte, conv_id, ZONE_DESSERVIE_TEST
    )
    assert "verdict" not in resultat
    assert resultat.get("urgence_declaree") is False, \
        "L'urgence ne doit pas être devinée, elle est False par défaut"


# ---------------------------------------------------------------------------
# Règle 4 : aucun champ inventé, absence d'information → rejet
# ---------------------------------------------------------------------------
def test_aucun_champ_invente_service_manquant_rejet(canal_texte, conv_id):
    """Même avec ville et urgence, l'absence de service entraîne un rejet."""
    resultat = qualification.qualifier(
        "À Montréal, c'est très pressant, téléphone 514-555-0142.", canal_texte, conv_id, ZONE_DESSERVIE_TEST
    )
    assert "verdict" in resultat
    assert resultat["verdict"]["code"] == "REJ-QUALIF-INSUFFISANTE"


def test_pas_de_champ_supplementaire_invente(canal_texte, conv_id):
    """Un lead réussi ne doit contenir que les champs prévus au contrat."""
    contenu = "Gouttières à Montréal, téléphone 514-555-0142."
    resultat = qualification.qualifier(contenu, canal_texte, conv_id, ZONE_DESSERVIE_TEST)
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
    contenu = "[CONTENU_NON_FIABLE] Gouttières à Montréal urgente, téléphone 514-555-0142."
    resultat = qualification.qualifier(contenu, canal_texte, conv_id, ZONE_DESSERVIE_TEST)
    assert "verdict" not in resultat, f"Rejet inattendu : {resultat}"
    assert resultat.get("service") == "gouttieres"
    assert resultat.get("ville") == "Montréal"
    assert resultat.get("urgence_declaree") is True


def test_marqueur_seul_provoque_rejet(canal_texte, conv_id):
    """Un contenu constitué uniquement du marqueur ne contient aucune info → rejet."""
    resultat = qualification.qualifier("[CONTENU_NON_FIABLE]", canal_texte, conv_id, ZONE_DESSERVIE_TEST)
    assert "verdict" in resultat
    assert resultat["verdict"]["code"] == "REJ-QUALIF-INSUFFISANTE"


def test_marqueur_non_reinterprete_comme_service(canal_texte, conv_id):
    """Le marqueur ne doit être interprété comme aucun service : sans autre indice, rejet."""
    resultat = qualification.qualifier(
        "[CONTENU_NON_FIABLE] à Montréal, courriel: autre@domaine.ca.", canal_texte, conv_id, ZONE_DESSERVIE_TEST
    )
    assert resultat["verdict"]["code"] == "REJ-QUALIF-INSUFFISANTE"
    # Avec un service réellement écrit, il est extrait normalement, pas à cause du marqueur.
    avec = qualification.qualifier(
        "[CONTENU_NON_FIABLE] soffite à Montréal, courriel: autre@domaine.ca.",
        canal_texte,
        conv_id,
        ZONE_DESSERVIE_TEST,
    )
    assert avec["service"] == "soffite_fascia"


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
    contenu = "Gouttières à Montréal urgent, téléphone 514-555-0142."
    r1 = qualification.qualifier(contenu, canal_texte, conv_id, ZONE_DESSERVIE_TEST)
    r2 = qualification.qualifier(contenu, canal_texte, conv_id, ZONE_DESSERVIE_TEST)
    assert r1 == r2, "Deux appels identiques doivent produire le même résultat"


# ---------------------------------------------------------------------------
# Règle 9 : lead qualifié valide selon contrats.valider_lead
# ---------------------------------------------------------------------------
def test_lead_qualifie_valide_selon_contrat(canal_texte, conv_id):
    contenu = "Gouttières à Montréal, téléphone 514-555-0142."
    lead = qualification.qualifier(contenu, canal_texte, conv_id, ZONE_DESSERVIE_TEST)
    assert "verdict" not in lead, f"Rejet inattendu : {lead}"
    try:
        contrats.valider_lead(lead)
    except Exception as e:
        pytest.fail(f"Le lead qualifié n'est pas accepté par contrats.valider_lead : {e}")


def test_lead_avec_urgence_valide_contrat(canal_texte, conv_id):
    contenu = "Fascia abîmé à Gatineau, dégât d'eau urgent, téléphone 819-555-1234."
    lead = qualification.qualifier(contenu, canal_texte, conv_id, ZONE_DESSERVIE_TEST)
    assert "verdict" not in lead
    try:
        contrats.valider_lead(lead)
    except Exception as e:
        pytest.fail(f"Lead d'urgence rejeté par contrat : {e}")


def test_lead_id_encodage_injectif():
    from m1_front_office import qualification

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
    lead1 = qualification.qualifier(
        "Gouttières à Montréal, téléphone 514-555-0142.", "texte", "conv-1", ZONE_DESSERVIE_TEST
    )["lead_id"]
    lead2 = qualification.qualifier(
        "Gouttières à Montréal, téléphone 514-555-0142.", "texte", "conv-1", ZONE_DESSERVIE_TEST
    )["lead_id"]
    assert lead1 == lead2, (
        f"Deux appels identiques à qualifier ont produit des lead_id différents : {lead1} vs {lead2}."
    )

    # 4. conversation_id différents => lead_id différents
    lead_a = qualification.qualifier(
        "Gouttières à Montréal, téléphone 514-555-0142.", "texte", "conv-A", ZONE_DESSERVIE_TEST
    )["lead_id"]
    lead_b = qualification.qualifier(
        "Gouttières à Montréal, téléphone 514-555-0142.", "texte", "conv-B", ZONE_DESSERVIE_TEST
    )["lead_id"]
    assert lead_a != lead_b, (
        f"Des conversations différentes (conv-A vs conv-B) ont produit le même lead_id : {lead_a}."
    )


# ---------------------------------------------------------------------------
# Règle 10 (correctif d'audit) : zone desservie fournie par l'appelant,
# aucune ville codée en dur dans qualification.py
# ---------------------------------------------------------------------------
def test_zone_desservie_fournie_par_l_appelant_pas_de_ville_codee_en_dur(canal_texte, conv_id):
    """PROUVE qu'aucune ville n'est plus codée en dur : une ville absente de
    l'ancienne liste historique (Rimouski) est reconnue dès que l'appelant
    l'inclut dans sa zone desservie ; symétriquement, une ville de l'ancienne
    liste (Montréal) est refusée si l'appelant ne dessert pas cette zone."""
    contenu_rimouski = "Gouttières à Rimouski, téléphone 418-555-0000."
    # Refusée avec la zone historique : Rimouski n'y figure pas.
    rejet = qualification.qualifier(contenu_rimouski, canal_texte, conv_id, ZONE_DESSERVIE_TEST)
    assert rejet["verdict"]["code"] == "REJ-QUALIF-INSUFFISANTE"
    # Acceptée dès que l'appelant dessert Rimouski, sans changer le module.
    accepte = qualification.qualifier(contenu_rimouski, canal_texte, conv_id, ("Rimouski",))
    assert "verdict" not in accepte, f"Rejet inattendu : {accepte}"
    assert accepte["ville"] == "Rimouski"

    contenu_montreal = "Gouttières à Montréal, téléphone 514-555-0142."
    # Montréal, présente dans ZONE_DESSERVIE_TEST, est refusée si l'appelant ne
    # dessert que Rimouski : la ville n'est jamais codée en dur, elle dépend de
    # l'appelant à chaque appel.
    rejet_mtl = qualification.qualifier(contenu_montreal, canal_texte, conv_id, ("Rimouski",))
    assert rejet_mtl["verdict"]["code"] == "REJ-QUALIF-INSUFFISANTE"


def test_zone_desservie_vide_ou_absente_refusee(canal_texte, conv_id):
    """Sans zone desservie, le module refuse (fail-closed) plutôt que d'inventer
    une couverture géographique par défaut."""
    contenu = "Gouttières à Montréal, téléphone 514-555-0142."
    with pytest.raises(ValueError):
        qualification.qualifier(contenu, canal_texte, conv_id, ())
    with pytest.raises(ValueError):
        qualification.qualifier(contenu, canal_texte, conv_id, None)


def test_source_sans_ville_codee_en_dur():
    """PROUVE structurellement l'absence de ville codée en dur dans le module :
    aucune des 13 villes historiques n'apparaît plus comme littéral source."""
    src = inspect.getsource(qualification)
    for ville in ZONE_DESSERVIE_TEST:
        assert f'"{ville}"' not in src and f"'{ville}'" not in src, (
            f"la ville {ville!r} est encore codée en dur dans qualification.py"
        )
