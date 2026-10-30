"""M9.4 — conseil : douze rôles, sélection sous budget, admission des sorties de modèle, gouvernance (fictif)."""

import pytest
from m9_strategic_intelligence import catalogue_producteurs as cat
from m9_strategic_intelligence import conseil

FICTIF = True
SOURCES = {"m6.disponibilite#0:stock": "12", "m5.comptes_a_payer#1:total": "8400.00"}


def test_douze_responsabilites_distinctes_et_lectures_du_catalogue():
    assert len(conseil.ROLES) == 12 and len({r.id for r in conseil.ROLES}) == 12
    attendus = {"conseiller_pdg", "operations", "liaison_finance", "croissance_marketing", "strategie_ventes",
                "rentabilite_estimation", "contraintes_inventaire", "experience_client", "responsable_risques",
                "auditeur_donnees", "planificateur_execution", "critique_decisions"}  # fmt: skip
    assert {r.id for r in conseil.ROLES} == attendus
    for role in conseil.ROLES:
        assert all(lecture in cat.PAR_ID for lecture in role.lectures), role.id
        assert role.domaines <= conseil.DOMAINES and role.enveloppe_tokens > 0


def test_selection_ne_consulte_que_les_specialistes_utiles():
    selection = conseil.selectionner(["stock", "cash"], importance="courante", budget_tokens=100_000)
    assert [e["role"] for e in selection["appeles"]] == ["liaison_finance", "contraintes_inventaire"]
    non = {e["role"]: e["raison"] for e in selection["non_appeles"]}
    assert non["critique_decisions"] == "décision non majeure"
    assert non["croissance_marketing"] == "domaine non concerné"
    assert len(selection["appeles"]) + len(non) == 11  # tous sauf l'auditeur, qui est une étape de code
    assert selection["tokens_reserves"] + selection["tokens_restants"] == 100_000


def test_decision_majeure_ajoute_le_critique_et_le_budget_borne_les_appels():
    majeure = conseil.selectionner(["cash", "risque"], importance="majeure", budget_tokens=100_000)
    assert [e["role"] for e in majeure["appeles"]][-1] == "critique_decisions"
    serre = conseil.selectionner(["cash", "risque", "stock"], importance="majeure", budget_tokens=5000)
    assert [e["role"] for e in serre["appeles"]] == ["liaison_finance"]
    assert {e["role"] for e in serre["non_appeles"]} >= {"responsable_risques", "critique_decisions"}
    assert conseil.selectionner(["cash"], importance="courante", budget_tokens=0)["appeles"] == []


def test_selection_deterministe_et_arguments_invalides_refuses():
    a = conseil.selectionner(["marketing", "leads", "pipeline"], importance="courante", budget_tokens=20000)
    assert a == conseil.selectionner(["marketing", "leads", "pipeline"], importance="courante", budget_tokens=20000)
    for domaines in ([], ["inconnu"], ["cash", "cash"], "cash"):
        with pytest.raises(ValueError, match="REJ-CONSEIL-DOMAINES"):
            conseil.selectionner(domaines, importance="courante", budget_tokens=1)
    with pytest.raises(ValueError, match="REJ-CONSEIL-IMPORTANCE"):
        conseil.selectionner(["cash"], importance="critique", budget_tokens=1)
    with pytest.raises(ValueError, match="REJ-CONSEIL-BUDGET"):
        conseil.selectionner(["cash"], importance="courante", budget_tokens=-1)


def _sortie(**surcharge):
    base = {
        "affirmations": [
            {"id": "A1", "nature": "observation_source", "reference": "m6.disponibilite#0:stock", "valeur": "12"},
            {"id": "H1", "nature": "hypothese", "enonce": "le fournisseur livre sous 10 jours"},
            {"id": "I1", "nature": "inference", "enonce": "rupture avant la livraison", "premisses": ["A1", "H1"]},
        ],
        "demandes": [{"outil": "m5_payer_facture", "arguments": {"montant": "8400.00"}}],
    }
    return base | surcharge


def test_proposition_admise_citation_exacte_inference_non_validee_et_demande_ecartee():
    admise = conseil.admettre_proposition(_sortie(), sources=SOURCES)
    statuts = {a["id"]: a["statut"] for a in admise["affirmations"]}
    assert statuts == {"A1": "SOURCE_CONCORDANTE", "H1": "HYPOTHESE_DECLAREE", "I1": "INFERENCE_NON_VALIDEE"}
    assert admise["demandes_ecartees"] == 1 and admise["validation_semantique"] == "NON_PROUVEE"
    assert "tool" not in str(admise) and "m5_payer_facture" not in str(admise)  # la demande n'est jamais conservée


@pytest.mark.parametrize(
    ("modification", "code"),
    [
        (lambda s: s["affirmations"][0].update(valeur="13"), "REJ-CONSEIL-CITATION"),
        (lambda s: s["affirmations"][0].update(reference="m9:inventee"), "REJ-CONSEIL-CITATION"),
        (lambda s: s["affirmations"][2].update(premisses=["A1", "INCONNUE"]), "REJ-CONSEIL-INFERENCE"),
        (lambda s: s["affirmations"][2].update(premisses=["I1"]), "REJ-CONSEIL-INFERENCE"),
        (lambda s: s["affirmations"][2].update(premisses=[]), "REJ-CONSEIL-INFERENCE"),
        (lambda s: s["affirmations"][1].update(extra="x"), "REJ-CONSEIL-AFFIRMATION"),
        (lambda s: s["affirmations"][1].update(nature="certitude"), "REJ-CONSEIL-AFFIRMATION"),
        (lambda s: s["affirmations"][1].update(id="A1"), "REJ-CONSEIL-AFFIRMATION"),
    ],
)
def test_un_defaut_refuse_toute_la_sortie(modification, code):
    sortie = _sortie()
    modification(sortie)
    with pytest.raises(ValueError, match=code):
        conseil.admettre_proposition(sortie, sources=SOURCES)


def test_inference_avant_ses_premisses_ou_inference_sur_inference_refusee():
    sortie = _sortie()
    sortie["affirmations"].reverse()
    with pytest.raises(ValueError, match="REJ-CONSEIL-INFERENCE"):
        conseil.admettre_proposition(sortie, sources=SOURCES)
    chaine = _sortie()
    chaine["affirmations"].append({"id": "I2", "nature": "inference", "enonce": "donc retard", "premisses": ["I1"]})
    with pytest.raises(ValueError, match="REJ-CONSEIL-INFERENCE"):
        conseil.admettre_proposition(chaine, sources=SOURCES)


@pytest.mark.parametrize("sortie", [None, [], {"affirmations": []}, {"demandes": []}, {"affirmations": [1]},
                                    {"affirmations": [{"id": "x"}], "autre": 1}])  # fmt: skip
def test_sortie_malformee_refusee(sortie):
    with pytest.raises(ValueError, match="REJ-CONSEIL-(SORTIE|AFFIRMATION)"):
        conseil.admettre_proposition(sortie, sources=SOURCES)


def test_gouvernance_aucune_action_sensible_sans_validation_et_aucun_effet_autorise():
    verdict = conseil.gouverner({
        "decision": "Embaucher un couvreur",
        "actions": [
            {"id": "a1", "type": "embauche", "description": "ouvrir un poste"},
            {"id": "a2", "type": "depense_reelle", "description": "acheter un camion"},
            {"id": "a3", "type": "suivi_interne", "description": "suivre la mesure"},
            {"id": "a4", "type": "virement", "description": "?"},
        ],
    })  # fmt: skip
    par_id = {v["action"]: v for v in verdict["actions"]}
    assert par_id["a1"]["verdict"] == par_id["a2"]["verdict"] == "VALIDATION_HUMAINE_REQUISE"
    assert par_id["a3"]["verdict"] == "PROPOSABLE" and par_id["a4"]["verdict"] == "REFUSEE_TYPE_INCONNU"
    assert all(v["effet_autorise"] is False for v in verdict["actions"]) and verdict["autorite_d_effet"] is False
    assert verdict["decision_majeure"] is True
    with pytest.raises(ValueError, match="REJ-GOUVERNANCE-ENTREE"):
        conseil.gouverner({"decision": "x", "actions": [{"id": "a", "type": "suivi_interne"}] * 2})


def test_profil_agent_est_une_declaration_manuelle_sans_grant():
    spec = conseil.profil_agent(
        "liaison_finance", outils=["m9_lire_etat_consolide"], budget_jour=10000, budget_mois=100000
    )
    assert spec["declencheurs"] == [{"type": "manuel"}] and spec["departement"] == "m09-strategic-intelligence"
    assert spec["id"] == "m9-liaison-finance" and spec["limite_tours"] == 3
