"""confidentialite.py : ce qu'un paquet de contexte laisse sortir, par couche et par agent (PLAN T3.3-suite-b).

La table de la règle est épinglée en entier : élargir qui reçoit `CLIENT_PRIVATE` exige de modifier
`AGENTS_CLIENT_PRIVE_PAR_COUCHE`, ce fichier et l'ADR-0010 ensemble, donc de le faire exprès en relecture.
Toutes les données sont fictives (`fictif: true`).
"""

import json

import pytest
from m10_memoire import confidentialite, decisions, paquets, registre, signaux, variance, wct

FICTIF = True
HORODATAGE = "2026-09-15T14:00:00-04:00"
HORODATAGE_PAQUET = "2026-09-16T08:00:00-04:00"
PRIVE = "CLIENT_PRIVATE"
SECRET_DU_CLIENT = "Mme Tremblay préfère être jointe après 17 h, au numéro de sa sœur."

COUCHES = ("regles_entreprise", "faits_affaire", "evenements_recents", "signaux_non_resolus")
DEPARTEMENTS = (
    "m01-front-office", "m02-revenue-crm", "m03-estimation", "m04-field-ops", "m05-financecore",
    "m06-material-control", "m07-marketing", "m08-analytics", "m09-strategic-intelligence", "m10-memoire",
)
INTERDITS_A_TOUS = ("SENSITIVE", "FINANCIAL", "SECRET_REF", "LEGAL_LOCKED")


def _wct(wct_id="WCT-1", lead_id="LEAD-1"):
    return {
        "wct_id": wct_id, "intervention_id": f"int-{wct_id}", "lead_id": lead_id, "technicien_id": "TECH-1",
        "horodatage_completion": HORODATAGE, "fix_gps_completion": {"latitude": 46.8, "longitude": -71.2},
        "duree_reelle_minutes": 90, "ecart_signale": False, "revue_id": None, "hash_maillon": "a" * 64,
        "consommateurs_cibles": ["M10"], "devis_id": f"devis-{wct_id}",
    }


def _variance(evenement_id, wct_id="WCT-1", critique=True, **surcharges):
    base = {
        "evenement_id": evenement_id, "wct_id": wct_id, "intervention_id": f"int-{wct_id}", "chantier_id": "CH-1",
        "statut_variance": "evaluee", "signal_critique": critique, "seuil_pourcentage": 0.1,
        "horodatage_completion": HORODATAGE, "lignes": [],
    }
    base.update(surcharges)
    return base


def _fait_consolide(niveau, resume=SECRET_DU_CLIENT, jour="2026-09-15", affaire="LEAD-1"):
    entree = {
        "type_entree": "fait_consolide", "horodatage": HORODATAGE_PAQUET, "affaire_id": affaire, "jour": jour,
        "cle_consolidation": f"{affaire}:{jour}", "resume": resume, "sources": [],
    }
    if niveau is not None:
        entree["confidentialite"] = niveau
    return entree


@pytest.fixture
def registres():
    return registre.Registre(), registre.Registre()


def _paquet(registres, agent, **options):
    evenements, affaires = registres
    return paquets.assembler_paquet_contexte(
        "LEAD-1", HORODATAGE_PAQUET, evenements, affaires, agent=agent, **options
    )


def _couche(paquet, nom):
    return next(c for c in paquet["couches"] if c["nom"] == nom)


# -- la règle, épinglée --------------------------------------------------------------------------------
def test_la_table_de_la_regle_est_epinglee():
    assert {
        "regles_entreprise": frozenset(),
        "faits_affaire": frozenset({"m01-front-office", "m02-revenue-crm"}),
        "evenements_recents": frozenset({"m01-front-office", "m02-revenue-crm"}),
        "signaux_non_resolus": frozenset(),
    } == confidentialite.AGENTS_CLIENT_PRIVE_PAR_COUCHE
    assert confidentialite.REGLE_VERSION == "v1"


def test_les_couches_de_la_table_sont_exactement_celles_du_paquet():
    assert tuple(confidentialite.AGENTS_CLIENT_PRIVE_PAR_COUCHE) == COUCHES
    assert tuple(paquets._COUCHES_ORDRE) == COUCHES


def test_les_sept_niveaux_de_la_definition_sont_connus():
    assert confidentialite.niveaux_connus() == frozenset(
        {"PUBLIC_INTERNAL", "INTERNAL", "SENSITIVE", "FINANCIAL", "CLIENT_PRIVATE", "SECRET_REF", "LEGAL_LOCKED"}
    )


@pytest.mark.parametrize("couche", COUCHES)
@pytest.mark.parametrize("agent", (*DEPARTEMENTS, None))
def test_niveaux_admis_par_couche_et_par_agent(couche, agent):
    autorise = agent in confidentialite.AGENTS_CLIENT_PRIVE_PAR_COUCHE[couche]

    admis = confidentialite.niveaux_admis(couche, agent)

    assert admis == ({"PUBLIC_INTERNAL", "INTERNAL", PRIVE} if autorise else {"PUBLIC_INTERNAL", "INTERNAL"})
    for interdit in INTERDITS_A_TOUS:
        assert interdit not in admis


def test_une_couche_inconnue_n_admet_jamais_client_private():
    assert confidentialite.niveaux_admis("couche_inventee", "m01-front-office") == {"PUBLIC_INTERNAL", "INTERNAL"}


def test_le_niveau_effectif_d_un_maillon():
    assert confidentialite.niveau_de({}) == "INTERNAL"
    for niveau in confidentialite.niveaux_connus():
        assert confidentialite.niveau_de({"confidentialite": niveau}) == niveau
    # un marquage inconnu ne devient jamais plus ouvert que ce que le maillon dit
    for inconnu in ("SECRET", "internal", "", 3, ["CLIENT_PRIVATE"]):
        assert confidentialite.niveau_de({"confidentialite": inconnu}) == "LEGAL_LOCKED"


# -- le filtre, sur de vrais paquets -------------------------------------------------------------------
@pytest.mark.parametrize("agent", ["m01-front-office", "m02-revenue-crm"])
def test_m1_et_m2_recoivent_le_fait_prive_de_l_affaire(registres, agent):
    _, affaires = registres
    affaires.ajouter(_fait_consolide(PRIVE))

    paquet = _paquet(registres, agent)

    [fait] = _couche(paquet, "faits_affaire")["faits"]
    assert SECRET_DU_CLIENT in fait["resume"] and fait["confidentialite"] == PRIVE
    assert paquet["confidentialite"]["nb_retenus"] == 0


AUTRES_AGENTS = [d for d in DEPARTEMENTS if d not in ("m01-front-office", "m02-revenue-crm")] + [None]


@pytest.mark.parametrize("agent", AUTRES_AGENTS)
def test_les_autres_agents_ne_recoivent_ni_le_contenu_ni_l_identifiant_du_fait_prive(registres, agent):
    _, affaires = registres
    affaires.ajouter(_fait_consolide(PRIVE))
    identifiant = affaires.lire()[0]["ligne_id"]

    paquet = _paquet(registres, agent)

    texte = json.dumps(paquet, ensure_ascii=False)
    assert "Tremblay" not in texte and SECRET_DU_CLIENT not in texte and identifiant not in texte
    couche = _couche(paquet, "faits_affaire")
    assert couche["vide"] is True and couche["nb_total"] == 0 and couche["tronque"] is False
    assert paquet["confidentialite"]["nb_retenus"] == 1  # dit qu'il y a une vue partielle, rien de plus


@pytest.mark.parametrize("niveau", INTERDITS_A_TOUS)
@pytest.mark.parametrize("agent", ["m01-front-office", "m02-revenue-crm", "m05-financecore", "m10-memoire", None])
def test_les_niveaux_fermes_ne_sortent_jamais_dans_un_paquet(registres, niveau, agent):
    _, affaires = registres
    affaires.ajouter(_fait_consolide(niveau))
    decisions.enregistrer_decision(
        {"decision_id": "DEC-1", "raison": SECRET_DU_CLIENT, "statut": "validee", "options_ecartees": ""},
        affaires, HORODATAGE, niveau,
    )

    paquet = _paquet(registres, agent)

    assert SECRET_DU_CLIENT not in json.dumps(paquet, ensure_ascii=False)
    assert paquet["confidentialite"]["nb_retenus"] == 2


def test_un_marquage_inconnu_est_traite_comme_le_plus_ferme(registres):
    _, affaires = registres
    affaires.ajouter({**_fait_consolide(None), "confidentialite": "TRES_SECRET"})

    paquet = _paquet(registres, "m01-front-office")

    assert SECRET_DU_CLIENT not in json.dumps(paquet, ensure_ascii=False)
    assert paquet["confidentialite"]["nb_retenus"] == 1


def test_une_regle_de_l_entreprise_marquee_privee_ne_sort_pour_personne(registres):
    _, affaires = registres
    decisions.enregistrer_decision(
        {"decision_id": "DEC-1", "raison": SECRET_DU_CLIENT, "statut": "validee", "options_ecartees": ""},
        affaires, HORODATAGE, PRIVE,
    )

    for agent in ("m01-front-office", "m02-revenue-crm", None):
        paquet = _paquet(registres, agent)
        assert _couche(paquet, "regles_entreprise")["vide"] is True
        assert paquet["confidentialite"]["nb_retenus"] == 1


def test_un_evenement_prive_sort_vers_m2_pas_vers_m4(registres):
    evenements, _ = registres
    wct.memoriser_wct(_wct(), evenements)
    variance.memoriser_variance(_variance("EVT-PRIVE", critique=False, confidentialite=PRIVE), evenements)

    vu_par_m2 = _couche(_paquet(registres, "m02-revenue-crm"), "evenements_recents")
    vu_par_m4 = _paquet(registres, "m04-field-ops")

    assert {f["identifiant"] for f in vu_par_m2["faits"]} == {"WCT-1", "EVT-PRIVE"}
    assert {f["identifiant"] for f in _couche(vu_par_m4, "evenements_recents")["faits"]} == {"WCT-1"}
    assert vu_par_m4["confidentialite"]["nb_retenus"] == 1


def test_un_signal_prive_ne_sort_pour_personne_mais_reste_compte_pour_la_garde(registres):
    """La couche des signaux ne porte jamais de donnée du client. Le décompte, lui, compte TOUT signal :
    la garde du core ne doit jamais croire « aucun signal ouvert » parce qu'un signal a été retenu."""
    evenements, _ = registres
    wct.memoriser_wct(_wct(), evenements)
    variance.memoriser_variance(_variance("EVT-1", confidentialite=PRIVE), evenements)

    paquet = _paquet(registres, "m01-front-office")

    assert _couche(paquet, "signaux_non_resolus")["vide"] is True
    assert paquet["signaux"]["nb_ouverts"] == 1
    assert paquet["confidentialite"]["nb_retenus"] >= 1


def test_un_element_retenu_ne_prend_pas_la_place_d_un_autre_et_n_est_pas_un_omis(registres):
    _, affaires = registres
    affaires.ajouter(_fait_consolide(PRIVE, jour="2026-09-15", resume="jour privé"))
    affaires.ajouter(_fait_consolide(None, jour="2026-09-14", resume="jour interne"))

    paquet = _paquet(registres, "m03-estimation", n_faits_max_par_couche=1)

    couche = _couche(paquet, "faits_affaire")
    assert [f["resume"] for f in couche["faits"]] == ["2026-09-14 : jour interne"]
    assert couche["nb_total"] == 1 and couche["nb_omis"] == 0 and couche["tronque"] is False
    assert paquet["confidentialite"]["nb_retenus"] == 1


def test_sans_marquage_tout_reste_visible_pour_tous_comme_avant(registres):
    _, affaires = registres
    affaires.ajouter(_fait_consolide(None, resume="fait interne"))

    for agent in (*DEPARTEMENTS, None):
        paquet = _paquet(registres, agent)
        assert [f["confidentialite"] for f in _couche(paquet, "faits_affaire")["faits"]] == ["INTERNAL"]
        assert paquet["confidentialite"]["nb_retenus"] == 0


# -- le marquage d'une décision ------------------------------------------------------------------------
def test_une_decision_marquee_garde_son_niveau_dans_le_maillon(registres):
    _, affaires = registres

    maillon, code = decisions.enregistrer_decision(
        {"decision_id": "DEC-1", "raison": "raison suffisante", "statut": "validee", "options_ecartees": ""},
        affaires, HORODATAGE, PRIVE,
    )

    assert code is None and maillon["confidentialite"] == PRIVE


def test_une_decision_non_marquee_s_ecrit_exactement_comme_avant(registres):
    _, affaires = registres

    maillon, _ = decisions.enregistrer_decision(
        {"decision_id": "DEC-1", "raison": "raison suffisante", "statut": "validee", "options_ecartees": ""},
        affaires, HORODATAGE,
    )

    assert "confidentialite" not in maillon
    assert confidentialite.niveau_de(maillon) == "INTERNAL"


@pytest.mark.parametrize("niveau", ["SECRET", "client_private", "", 3])
def test_un_niveau_inconnu_refuse_la_decision_et_n_ecrit_rien(registres, niveau):
    _, affaires = registres

    maillon, code = decisions.enregistrer_decision(
        {"decision_id": "DEC-1", "raison": "raison suffisante", "statut": "validee", "options_ecartees": ""},
        affaires, HORODATAGE, niveau,
    )

    assert maillon is None and code == confidentialite.REJ_CONFIDENTIALITE_NIVEAU_INCONNU
    assert affaires.lire() == []


def test_le_filtre_ne_change_pas_le_decompte_des_signaux_visibles(registres):
    evenements, affaires = registres
    wct.memoriser_wct(_wct(), evenements)
    variance.memoriser_variance(_variance("EVT-1"), evenements)

    paquet = _paquet(registres, "m03-estimation")

    attendus = signaux.signaux_de_laffaire("LEAD-1", evenements.lire(), affaires.lire())
    assert paquet["signaux"] == signaux.decompte(attendus)
    assert paquet["confidentialite"] == {"agent": "m03-estimation", "regle": "v1", "nb_retenus": 0}
