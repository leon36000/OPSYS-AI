"""M2.4 Lead scoring 2.0 : les VRAIS outils (`m2_calculer_score_lead`, `m2_classer_file_leads`,
`m2_lire_modele_scoring`,
`m2_declarer_valeur_pipeline`, `m2_rejouer_recu_commercial`), la vraie base, la vraie identité d'appareil.

Ce qui est prouvé ici :
- le score est déterministe, expliqué (facteurs, poids déclarés, contribution, version) et rejouable par son reçu ;
- il ORDONNE : le classement est une permutation, aucun lead n'est écarté, aucun statut ne change, un humain décide ;
- il ne devine pas : un signal sans donnée est « non évalué » avec ce qui manque ; les bandes de valeur se configurent
  ;
- il est équitable : changer un nom, un téléphone, un courriel ou une ville ne change pas le score ;
- un vendeur ne classe que SES leads ; la valeur déclarée est une décision de personne. Données fictives (`fictif:
  true`).
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from m2_revenue_crm import scoring
from ventes_aide import ADMIN, BANDES, EMPLOYE, H_INGERE, MAINTENANT, VENDEUR_DEUX, VENDEUR_UN, contact, taille

from opsys.outils import Autonomie, Niveau

FICTIF = True


@pytest.fixture
def pipeline(monde):
    """Quatre leads ouverts très différents, un lead perdu, deux vendeurs."""
    m = monde
    m.lead(
        "riche",
        "vendeur.un",
        contact("Cliente Riche", 201),
        urgence=True,
        service_champs={"source": "site", "campagne": "automne"},
    )
    m.interaction("riche", "Premier appel : projet confirmé.", "2026-10-10T09:00:00-04:00")
    m.interaction("riche", "Visite planifiée.", "2026-10-12T09:00:00-04:00")
    m.lead(
        "pauvre",
        "vendeur.un",
        {"nom": "Client Pauvre"},
        ingere="2026-07-01T09:00:00-04:00",
        qualifie="2026-07-01T10:00:00-04:00",
    )
    m.lead("nouveau", None, contact("Client Nouveau", 203), ingere="2026-10-14T09:00:00-04:00")
    m.lead("autre", "vendeur.deux", contact("Client Autre", 204))
    m.lead("perdu", "vendeur.deux", contact("Client Perdu", 205))
    assert (
        m.appeler(
            "m2_transitionner_statut",
            {
                "lead_id": "perdu",
                "statut_cible": "perdu",
                "horodatage": "2026-09-20T09:00:00-04:00",
                "motif": "Budget insuffisant.",
            },
            VENDEUR_DEUX,
        )["resultat"]["accepte"]
        is True
    )
    return m


def _score(m, lead, qui=VENDEUR_UN, **plus):
    return m.appeler("m2_calculer_score_lead", {"lead_id": lead, "horodatage": MAINTENANT, **plus}, qui)


def _file(m, qui=ADMIN, **plus):
    return m.appeler("m2_classer_file_leads", {"horodatage": MAINTENANT, **plus}, qui)


# ---------------------------------------------------------------------------------------- déclaration
def test_niveaux_et_portees_des_outils_de_score(monde):
    par = monde.par_nom
    for nom in (
        "m2_calculer_score_lead",
        "m2_classer_file_leads",
        "m2_lire_modele_scoring",
        "m2_rejouer_recu_commercial",
    ):
        assert (par[nom].autonomie, par[nom].niveau_effectif) == (Autonomie.T0, Niveau.N0), nom
        assert par[nom].roles_appareil == frozenset({"seller", "admin"}), nom
    declarer = par["m2_declarer_valeur_pipeline"]
    assert (declarer.autonomie, declarer.niveau_effectif) == (Autonomie.T1, Niveau.N3)
    assert declarer.roles_appareil == frozenset({"seller", "admin"})
    for outil in par.values():
        if "score" in outil.nom or "file_leads" in outil.nom:
            assert "ecarter" not in json.dumps(outil.parametres), outil.nom
            assert "employee" not in outil.roles_appareil


# ---------------------------------------------------------------------------------------- le score d'un lead
def test_le_score_est_explique_deterministe_et_versionne(pipeline):
    m = pipeline
    premier = m.accepte(_score(m, "riche"))
    second = m.accepte(_score(m, "riche"))
    assert premier == second, "mêmes faits, même score, au chiffre près"
    assert premier["modele"] == {"id": "m2-score-lead", "version": "1.0.0", "empreinte": scoring.empreinte_modele()}
    assert premier["decision_humaine_requise"] is True and "probabilite_calibree" in premier
    assert premier["probabilite_calibree"] is None
    assert [f["facteur"] for f in premier["facteurs"]] == [
        "qualite",
        "urgence",
        "conversion",
        "rentabilite",
        "preparation",
        "risque",
    ]
    assert [f["poids"] for f in premier["facteurs"]] == [20, 15, 25, 15, 15, 10]
    evalues = [f for f in premier["facteurs"] if f["sous_score"] is not None]
    total = sum(Decimal(f["contribution_points"]) for f in evalues)
    assert abs(total - Decimal(premier["score"])) <= Decimal("0.03"), "les contributions somment au score (arrondis)"
    assert taille({"ok": True, "resultat": {"accepte": True, "resultat": premier}}) < 6000


def test_un_signal_sans_donnee_est_non_evalue_et_nomme_ce_qui_manque_la_valeur_se_configure(pipeline):
    m = pipeline
    brut = m.accepte(_score(m, "riche"))
    non_evalue = next(f for f in brut["facteurs"] if f["facteur"] == "rentabilite")
    assert non_evalue["sous_score"] is None
    assert "bandes de valeur à configurer" in non_evalue["signaux"][0]
    assert Decimal(brut["couverture_poids"]) == Decimal("0.85"), "le score dit sa couverture"

    m.configurer(scoring={"bandes_valeur_cents": BANDES})
    sans_valeur = m.accepte(_score(m, "riche"))
    assert (
        "aucune valeur déclarée"
        in next(f for f in sans_valeur["facteurs"] if f["facteur"] == "rentabilite")["signaux"][0]
    )

    declaree = m.accepte(
        m.appeler(
            "m2_declarer_valeur_pipeline",
            {"lead_id": "riche", "montant": "50000.00", "horodatage": MAINTENANT},
            VENDEUR_UN,
        )
    )
    assert (
        declaree["montant"] == "50000.00" and declaree["devise"] == "CAD" and "pas un prix" in declaree["avertissement"]
    )
    complet = m.accepte(_score(m, "riche"))
    rentabilite = next(f for f in complet["facteurs"] if f["facteur"] == "rentabilite")
    assert rentabilite["sous_score"] == "100.00", "50 000 $ est au-delà de la troisième bande (40 000 $)"
    assert Decimal(complet["couverture_poids"]) == Decimal("1.00"), "tout est évalué : la couverture est complète"


def test_des_bandes_de_valeur_invalides_sont_ignorees_jamais_devinees(pipeline):
    m = pipeline
    for bandes in ([5, 5, 6], [1, 2], "cher", [3, 2, 1], [0, 1, 2], [1.5, 2, 3], [True, 2, 3]):
        m.configurer(scoring={"bandes_valeur_cents": bandes})
        rentabilite = next(f for f in m.accepte(_score(m, "riche"))["facteurs"] if f["facteur"] == "rentabilite")
        assert rentabilite["sous_score"] is None, bandes


def test_le_reçu_du_score_se_rejoue_a_l_identique_et_un_reçu_retouche_est_refuse(pipeline):
    m = pipeline
    avec = m.accepte(_score(m, "riche", avec_recu=True))
    recu = avec["recu"]
    assert recu["format"] == "recu-calcul.v1" and recu["moteur"] == "score_lead" and "entrees" in recu
    rejeu = m.accepte(m.appeler("m2_rejouer_recu_commercial", {"recu": recu}, VENDEUR_UN))
    assert rejeu["identique"] is True and rejeu["empreinte_recue"] == rejeu["empreinte_recalculee"]
    # le MÊME reçu est vérifié par le moteur de M5 (même format, mêmes empreintes)
    from opsys import recu_calcul_pont

    assert recu_calcul_pont.verifier(recu) == (True, "")
    # retouché : refusé
    retouche = json.loads(json.dumps(recu))
    retouche["resultat"]["score"] = "99.99"
    assert m.code(m.appeler("m2_rejouer_recu_commercial", {"recu": retouche}, VENDEUR_UN)) == "REJ-PREV-RECU-INVALIDE"
    # entrées retouchées avec empreintes recalculées à la main : le rejeu refait le calcul et constate la différence
    faux = json.loads(json.dumps(recu))
    faux["entrees"]["urgence_declaree"] = not faux["entrees"]["urgence_declaree"]
    assert m.code(m.appeler("m2_rejouer_recu_commercial", {"recu": faux}, VENDEUR_UN)) == "REJ-PREV-RECU-INVALIDE"
    # compact : pas rejouable
    compact = {k: v for k, v in recu.items() if k != "entrees"}
    assert m.code(m.appeler("m2_rejouer_recu_commercial", {"recu": compact}, VENDEUR_UN)) == "REJ-PREV-RECU-INVALIDE"
    # moteur inconnu : refusé
    inconnu = json.loads(json.dumps(recu))
    inconnu["moteur"] = "moteur_invente"
    assert m.code(m.appeler("m2_rejouer_recu_commercial", {"recu": inconnu}, VENDEUR_UN)) == "REJ-PREV-RECU-INVALIDE"


# ---------------------------------------------------------------------------------------- il ordonne, il n'écarte pas
def test_la_file_est_une_permutation_des_leads_ouverts_aucun_n_est_ecarte(pipeline):
    m = pipeline
    avant = m.registre("principal")
    page = m.accepte(_file(m))
    ids = [e["lead_id"] for e in page["file"]]
    assert sorted(ids) == ["autre", "nouveau", "pauvre", "riche"], "les quatre leads ouverts, le perdu est clos"
    assert page["total_ouverts"] == 4 and page["suivant"] is None and page["decision_humaine_requise"] is True
    assert ids[0] == "riche" and ids[-1] in ("pauvre", "nouveau")
    assert [e["rang"] for e in page["file"]] == [1, 2, 3, 4]
    assert m.registre("principal") == avant, "classer ne change aucun statut ni aucune donnée"
    # un lead au score bas reste dans la file, et son score est lisible
    dernier = page["file"][-1]
    assert Decimal(dernier["score"]) < Decimal(page["file"][0]["score"])
    assert "écarte" in page["avertissement"].lower() or "n'écarte" in page["avertissement"]


def test_la_pagination_de_la_file_ne_perd_ni_ne_repete_aucun_lead(pipeline):
    m = pipeline
    vus, decalage = [], 0
    while True:
        page = m.accepte(_file(m, limite=1, decalage=decalage))
        vus += [e["lead_id"] for e in page["file"]]
        if page["suivant"] is None:
            break
        decalage = page["suivant"]
    assert sorted(vus) == ["autre", "nouveau", "pauvre", "riche"] and len(set(vus)) == len(vus)


def test_un_vendeur_ne_classe_que_ses_leads_l_admin_tous_l_employe_aucun(pipeline):
    m = pipeline
    un = m.accepte(_file(m, qui=VENDEUR_UN))
    assert sorted(e["lead_id"] for e in un["file"]) == ["pauvre", "riche"] and un["total_ouverts"] == 2
    deux = m.accepte(_file(m, qui=VENDEUR_DEUX))
    assert [e["lead_id"] for e in deux["file"]] == ["autre"]
    assert m.code(_file(m, qui=EMPLOYE)) == "REJ-IDENTITE-APPAREIL-INVALIDE"
    avant = m.instantane()
    assert m.code(_score(m, "autre", qui=VENDEUR_UN)) == "REJ-LEAD-NON-ASSIGNE"
    assert m.code(_score(m, "inexistant", qui=VENDEUR_UN)) == "REJ-LEAD-NON-ASSIGNE"
    assert m.code(_score(m, "inexistant", qui=ADMIN)) == "REJ-LEAD-INCONNU"
    assert m.instantane() == avant


def test_un_lead_clos_n_a_pas_de_score_c_est_dit_sans_le_juger(pipeline):
    m = pipeline
    assert m.code(_score(m, "perdu", qui=ADMIN)) == "REJ-SCORE-LEAD-CLOS"


@pytest.mark.parametrize(
    "plus", [{"limite": 0}, {"limite": 51}, {"decalage": -1}, {"statut": "perdu"}, {"limite": "5"}]
)
def test_pagination_invalide_refusee(pipeline, plus):
    m = pipeline
    reponse = _file(m, **plus)
    assert reponse["ok"] is False or m.code(reponse) == "REJ-PAGINATION-INVALIDE"


def test_filtre_de_statut_de_la_file(pipeline):
    m = pipeline
    page = m.accepte(_file(m, statut="qualifie"))
    assert {e["statut"] for e in page["file"]} == {"qualifie"} and page["total_ouverts"] == 3
    nouveaux = m.accepte(_file(m, statut="nouveau"))
    assert [e["lead_id"] for e in nouveaux["file"]] == ["nouveau"]


# ---------------------------------------------------------------------------------------- équité
def test_changer_un_nom_un_telephone_un_courriel_ne_change_pas_le_score(monde):
    m = monde
    m.lead(
        "alpha", "vendeur.un", {"nom": "Alexandre Tremblay", "telephone": "418-555-1111", "courriel": "a@example.test"}
    )
    m.lead("beta", "vendeur.un", {"nom": "Fatima El-Khoury", "telephone": "514-555-9999", "courriel": "b@example.test"})
    m.lead("gamma", "vendeur.un", {"nom": "Zhang Wei", "telephone": "819-555-0000", "courriel": "c@example.test"})
    scores = {lead: m.accepte(_score(m, lead))["score"] for lead in ("alpha", "beta", "gamma")}
    assert len(set(scores.values())) == 1, scores
    details = [json.dumps(m.accepte(_score(m, lead))["facteurs"]) for lead in ("alpha", "beta", "gamma")]
    assert len(set(details)) == 1


def test_la_presence_d_un_contact_compte_pas_sa_valeur(monde):
    m = monde
    m.lead("complet", "vendeur.un", contact("Complet", 301))
    m.lead("sans-courriel", "vendeur.un", {"nom": "Sans Courriel", "telephone": "418-555-0302"})
    assert Decimal(m.accepte(_score(m, "complet"))["score"]) > Decimal(m.accepte(_score(m, "sans-courriel"))["score"])


def test_la_ville_n_est_pas_un_facteur_seule_sa_presence_compte(monde):
    m = monde
    m.lead("quebec", "vendeur.un", contact("Client Q", 311))
    m.lead("autre-ville", "vendeur.un", contact("Client V", 312), service_champs={"ville": "Rouyn-Noranda"})
    assert m.accepte(_score(m, "quebec"))["score"] == m.accepte(_score(m, "autre-ville"))["score"]


# ---------------------------------------------------------------------------------------- valeur déclarée
def test_la_valeur_declaree_est_une_decision_de_personne(pipeline):
    m = pipeline
    avant = m.instantane()
    agent = m.appeler("m2_declarer_valeur_pipeline", {"lead_id": "riche", "montant": "5000", "horodatage": MAINTENANT})
    assert m.code(agent) == "REJ-HUMAIN-REQUIS"
    assert m.instantane() == avant
    for montant in ("-5", "0", "1e6", "12,50", "12.505", "abc", "", "1" * 14, " 5", "5 "):
        reponse = m.appeler(
            "m2_declarer_valeur_pipeline",
            {"lead_id": "riche", "montant": montant, "horodatage": MAINTENANT},
            VENDEUR_UN,
        )
        assert m.code(reponse) == "REJ-PREV-VALEUR-INVALIDE", montant
    assert m.instantane() == avant
    autre = m.appeler(
        "m2_declarer_valeur_pipeline", {"lead_id": "autre", "montant": "5000", "horodatage": MAINTENANT}, VENDEUR_UN
    )
    assert m.code(autre) == "REJ-LEAD-NON-ASSIGNE"
    clos = m.appeler(
        "m2_declarer_valeur_pipeline", {"lead_id": "perdu", "montant": "5000", "horodatage": MAINTENANT}, ADMIN
    )
    assert m.code(clos) == "REJ-SCORE-LEAD-CLOS"
    m.accepte(
        m.appeler(
            "m2_declarer_valeur_pipeline", {"lead_id": "riche", "montant": "5000", "horodatage": MAINTENANT}, VENDEUR_UN
        )
    )
    m.accepte(
        m.appeler(
            "m2_declarer_valeur_pipeline",
            {"lead_id": "riche", "montant": "7500.50", "horodatage": MAINTENANT},
            VENDEUR_UN,
        )
    )
    journal = m.registre("valeurs_pipeline")
    assert [x["montant_cents"] for x in journal] == [500000, 750050], "l'historique reste, le dernier fait foi"
    assert journal[0]["declare_par"] == "vendeur.un" and journal[0]["nature"] == "estimation_commerciale_declaree"


# ---------------------------------------------------------------------------------------- modèle et calibration
def test_le_modele_est_publie_avec_ses_poids_ses_champs_interdits_et_sa_calibration_fictive(pipeline):
    m = pipeline
    modele = m.accepte(m.appeler("m2_lire_modele_scoring", {}, VENDEUR_UN))["modele"]
    assert sum(f["poids"] for f in modele["facteurs"]) == 100
    assert {"age", "genre", "origine", "langue", "code_postal", "nom", "telephone"} <= set(modele["champs_interdits"])
    assert not set(modele["champs_interdits"]) & set(modele["faits_d_entree"])
    avec = m.accepte(m.appeler("m2_lire_modele_scoring", {"avec_calibration": True, "n": 600, "graine": 5}, ADMIN))
    calibration = avec["calibration"]
    assert calibration["jeu"]["nature"] == "fictif_synthetique" and calibration["jeu"]["n"] == 600
    assert 0.5 < float(calibration["auc"]) < 1 and 0 < float(calibration["brier"]["calibre"]) < 1
    assert 1 <= len(calibration["courbe_calibration"]) <= 10 and "MÉCANIQUE SEULEMENT" in calibration["valeur_probante"]
    assert taille({"ok": True, "resultat": {"accepte": True, "resultat": avec}}) < 6000
    refait = m.accepte(m.appeler("m2_lire_modele_scoring", {"avec_calibration": True, "n": 600, "graine": 5}, ADMIN))
    assert refait["calibration"]["empreinte_recu"] == calibration["empreinte_recu"], "même graine, même reçu"


def test_sans_stockage_durable_le_score_refuse(monde):
    from m2_revenue_crm import outils

    monde.lead("riche", "vendeur.un", contact("Cliente Riche", 201))
    outils.reinitialiser_registre()
    assert monde.code(_file(monde, qui=None)) == "REJ-PREV-BUS-INDISPONIBLE"


def test_horodatage_invalide_refuse_sans_ecriture(pipeline):
    m = pipeline
    avant = m.instantane()
    for h in ("hier", "2026-10-15T12:00:00", "", "2026-13-45T00:00:00-04:00"):
        reponse = m.appeler("m2_calculer_score_lead", {"lead_id": "riche", "horodatage": h}, VENDEUR_UN)
        assert m.code(reponse) == "REJ-HORODATAGE-INVALIDE", h
    assert m.instantane() == avant
    _ = H_INGERE
