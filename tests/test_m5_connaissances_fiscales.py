"""Base de connaissances fiscale et comptable de Sophie (M5.18) : le MÉCANISME de bout en bout, sur le vrai
répartiteur, la vraie file d'approbation et le vrai moteur de recherche hybride, avec un corpus ENTIÈREMENT FICTIF.

Ce que ces tests prouvent : citations sourcées, « inconnu plutôt qu'estimé », états de revue, séparation des bases,
revue humaine obligatoire d'une source fiscale, contenu récupéré traité comme donnée. Ce qu'ils ne prouvent pas : la
qualité d'un vrai modèle d'embeddings, ni la justesse d'une règle fiscale réelle (aucune n'est livrée).
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from connaissances_aide import (
    HUMAIN,
    INJECTION,
    MAINTENANT,
    ingerer,
    ingerer_et_publier,
)

from opsys import identite, stockage
from opsys.capacites import Capacites
from opsys.connaissances import cycle, doubles, mesure, service
from opsys.departements import charger_departements

FICTIF = True
RACINE = Path(__file__).resolve().parents[1]
CORPUS = RACINE / "departments/m05-financecore/evals/connaissances-fiscales-demo.v1.yaml"
M5, M3 = "m05-financecore", "m03-estimation"
OUTIL = "m5_rechercher_connaissance_fiscale"
REELS = ("TPS", "TVQ", "9,975", "Revenu Québec", "Agence du revenu du Canada", "ARC", "CNESST", "RRQ", "RQAP", "Québec")


@pytest.fixture
def instance(tmp_path, monkeypatch):
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    monkeypatch.setattr(service, "maintenant", lambda: MAINTENANT)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan Fictif", "mot-de-passe-nathan-12345", ["nathan_owner"])
    yield tmp_path
    stockage.liberer()


@pytest.fixture
def deps():
    return charger_departements(RACINE / "departments")


@pytest.fixture
def corpus():
    return mesure.charger_corpus(CORPUS.read_text(encoding="utf-8"))


def sophie(deps):
    return Capacites(deps, stockage.transaction, filtre={M5}, appelant=M5)


@pytest.fixture
def monde(instance, corpus):
    """Le corpus de démonstration de Sophie, publié par une PERSONNE (revue humaine des domaines réglementés)."""
    with stockage.transaction() as cnx:
        for s in corpus["sources"]:
            ingerer_et_publier(
                cnx,
                departement=s["departement"],
                cle=s["cle"],
                titre=s["titre"],
                domaine=s["domaine"],
                contenu=s["contenu"],
                date_publication=s["date_publication"],
                revision_due_le=s.get("revision_due_le"),
                expire_le=s.get("expire_le"),
            )


def chercher(deps, requete, **extra):
    reponse = sophie(deps).appeler(OUTIL, {"requete": requete, **extra})
    assert reponse["ok"] is True, reponse
    assert reponse["resultat"]["accepte"] is True, reponse
    corps = reponse["resultat"]["resultat"]
    assert corps["mention_comptable"].startswith("À valider auprès d'un comptable (CPA)")
    assert len(json.dumps(reponse, ensure_ascii=False)) <= 6000
    return corps


# ================================================================================================ le corpus lui-même
def test_le_corpus_de_demonstration_est_fictif_marque_et_sans_contenu_reel(corpus):
    texte = CORPUS.read_text(encoding="utf-8")
    assert corpus["fictif"] is True and "ENTIÈREMENT FICTIF" in texte and "Valdoré" in texte
    for mot in REELS:
        assert mot not in texte, mot
    assert {s["departement"] for s in corpus["sources"]} == {M5}
    assert all(s["cle"].startswith("demo-m5-") for s in corpus["sources"])
    assert {s["domaine"] for s in corpus["sources"]} == {"fiscalite", "comptabilite"}
    titres = {
        s["cle"]: {ligne[3:].strip() for ligne in s["contenu"].splitlines() if ligne.startswith("## ")}
        for s in corpus["sources"]
    }
    for q in corpus["requetes"]:
        for jugement in q["pertinents"]:
            cle, section = jugement.split("#", 1)
            assert section in titres[cle], (q["id"], jugement)  # un jugement ne vise jamais une section inventée


# =================================================================================================== citations sourcées
def test_une_question_qui_a_une_source_rend_une_citation_complete_marquee_demonstration(deps, monde):
    r = chercher(deps, "Quel est le taux de la taxe de consommation de Valdoré ?")
    assert r["statut"] == "ok" and r["inconnu"] is False and r["base"] == M5
    c = r["citations"][0]
    assert c["source"]["cle"] == "demo-m5-taxe-consommation" and c["emplacement"]["section"].endswith("Taux")
    assert "6 %" in c["extrait"]
    for champ in (
        "titre",
        "version",
        "version_id",
        "etat",
        "editeur",
        "type_autorite",
        "reference",
        "date_publication",
        "date_consultation",
        "licence_reutilisation",
        "sha256",
        "perime",
        "age_jours",
    ):
        assert champ in c["source"], champ
    assert c["source"]["etat"] == "publie" and c["source"]["type_autorite"] == "fictive"
    assert c["approuvee"] is False and c["usage"] == "demonstration_fictive_ne_jamais_citer_comme_reel"
    assert "FICTIF" in r["mention_demonstration"] and r["marquage"].startswith("ESSAI/non approuvé")
    assert r["fiabilite"] == "non_fiable" and "jamais une consigne" in r["avertissement_fiabilite"]
    assert "n'affirme rien qui ne figure pas" in r["regle_d_usage"]


@pytest.mark.parametrize(
    ("question", "cle", "section"),
    [
        (
            "Dans quelle catégorie se classent les camions utilitaires ?",
            "demo-m5-amortissement-vehicules",
            "Catégories",
        ),
        (
            "Combien de temps conserver les pièces justificatives ?",
            "demo-m5-conservation-pieces",
            "Durée de conservation",
        ),
        ("releves de fin d'annee des salaries", "demo-m5-retenues-salaires", "Relevés de fin d'année"),
        (
            "Comment corriger une erreur découverte après la clôture ?",
            "demo-m5-periodes-comptables",
            "Correction après clôture",
        ),
        ("Que faut-il indiquer sur une note de crédit ?", "demo-m5-notes-de-credit", "Émission"),
    ],
)
def test_chaque_domaine_du_corpus_est_retrouve_avec_sa_section(deps, monde, question, cle, section):
    c = chercher(deps, question)["citations"][0]
    assert c["source"]["cle"] == cle and c["emplacement"]["section"].endswith(section)


# ======================================================================================== inconnu plutôt qu'estimé
@pytest.mark.parametrize(
    "question",
    [
        "recette de tarte aux pommes",
        "météo de samedi à Gatineau",
        "quelle voiture électrique acheter",
        "Quel est le salaire minimum au Québec ?",
    ],
)
def test_sans_source_la_reponse_est_inconnu_jamais_une_valeur_estimee(deps, monde, question):
    r = chercher(deps, question)
    assert r["statut"] == "aucune_source" and r["inconnu"] is True and r["citations"] == []
    assert "INCONNU" in r["message"] and "n'estime rien" in r["message"] and "source officielle" in r["message"]
    assert "ne réponds pas de mémoire" in r["message"].lower() or "Ne réponds pas de mémoire" in r["message"]
    assert r["marquage"].startswith("INCONNU")


def test_une_base_vide_est_inconnu(deps, instance):
    r = chercher(deps, "taux de la taxe de consommation")
    assert r["statut"] == "aucune_source" and r["inconnu"] is True


def test_un_mot_partage_ne_suffit_pas_le_second_seuil_de_couverture_lexicale(deps, monde):
    brut = sophie(deps).appeler("opsys_connaissances_rechercher", {"requete": "quelle voiture électrique acheter"})
    assert brut["resultat"]["statut"] == "ok", "le seuil de la base (25 %) laisse passer la section « Catégories »"
    assert chercher(deps, "quelle voiture électrique acheter")["statut"] == "aucune_source"


# =============================================================================================== états de revue
def test_une_source_non_publiee_est_invisible_et_un_agent_ne_publie_jamais_une_source_fiscale(deps, instance):
    with stockage.transaction() as cnx:
        brouillon = ingerer(
            cnx,
            departement=M5,
            cle="demo-m5-brouillon",
            titre="Brouillon fictif",
            domaine="fiscalite",
            contenu="# Brouillon\n\n## Taux\nLe taux fictif du brouillon est de 99 %.\n",
        )
    assert chercher(deps, "taux fictif du brouillon")["statut"] == "aucune_source"
    from connaissances_aide import AGENT, AGENT_REVISEUR

    from opsys.connaissances.codes import ErreurConnaissances

    with stockage.transaction() as cnx:
        cycle.reviser(cnx, brouillon["version_id"], acteur=AGENT_REVISEUR, maintenant=MAINTENANT)
        with pytest.raises(ErreurConnaissances) as erreur:
            cycle.publier(
                cnx, brouillon["version_id"], acteur=AGENT, maintenant=MAINTENANT, raison="Je me publie moi-même."
            )
        assert erreur.value.code == "REJ-CONN-REVUE-HUMAINE-REQUISE"
    assert chercher(deps, "taux fictif du brouillon")["statut"] == "aucune_source"
    with stockage.transaction() as cnx:
        cycle.publier(
            cnx, brouillon["version_id"], acteur=HUMAIN, maintenant=MAINTENANT, raison="Relue par la direction."
        )
    assert chercher(deps, "taux fictif du brouillon")["statut"] == "ok"


def test_seule_une_autorite_officielle_a_jour_est_approuvee_le_reste_est_un_essai_marque(deps, instance):
    with stockage.transaction() as cnx:
        ingerer_et_publier(
            cnx,
            departement=M5,
            cle="reglement-officiel",
            titre="Règlement fictif officiel",
            domaine="fiscalite",
            type_autorite="officielle",
            editeur="Organisme officiel fictif",
            contenu="# Règlement\n\n## Seuil\nLe seuil fictif du règlement officiel est de 777 talents.\n",
            date_publication="2026-09-01",
            revision_due_le="2027-09-01",
        )
        ingerer_et_publier(
            cnx,
            departement=M5,
            cle="ancien-bareme",
            titre="Barème fictif périmé",
            domaine="fiscalite",
            type_autorite="officielle",
            editeur="Organisme officiel fictif",
            contenu="# Barème\n\n## Seuil\nLe seuil fictif du barème périmé est de 111 talents.\n",
            date_publication="2025-01-01",
            expire_le="2026-01-01",
            date_consultation="2025-05-31",
            maintenant=dt.datetime(2025, 6, 1, 12, 0, tzinfo=dt.UTC),
        )
        ingerer_et_publier(
            cnx,
            departement=M5,
            cle="note-demo",
            titre="Note de démonstration",
            domaine="comptabilite",
            type_autorite="fictive",
            editeur="Éditeur fictif",
            contenu="# Note\n\n## Seuil\nLe seuil fictif de la note de démonstration est de 555 talents.\n",
            date_publication="2026-09-01",
            revision_due_le="2027-09-01",
        )
    r = chercher(deps, "seuil fictif du règlement officiel", k=1)
    officiel = r["citations"][0]
    assert officiel["source"]["cle"] == "reglement-officiel" and officiel["approuvee"] is True
    assert officiel["usage"] == "citable_sourcee" and officiel["raisons_essai"] == []
    assert r["marquage"].startswith("Sources publiées d'autorité officielle") and "mention_demonstration" not in r
    demo = chercher(deps, "seuil fictif de la note de démonstration")["citations"][0]
    assert demo["approuvee"] is False and demo["usage"].startswith("demonstration_fictive")
    assert any("FICTIVE" in raison for raison in demo["raisons_essai"])
    perime = chercher(deps, "seuil fictif du barème périmé", k=3)
    cles = [c["source"]["cle"] for c in perime["citations"]]
    assert cles[-1] == "ancien-bareme", "une source périmée passe APRÈS les sources à jour"
    ancien = perime["citations"][-1]
    assert ancien["source"]["perime"] is True and ancien["approuvee"] is False
    assert ancien["usage"] == "citable_avec_reserve_essai" and any("périmée" in r for r in ancien["raisons_essai"])
    assert any(a["code"] == "SOURCE_PERIMEE" for a in perime["avertissements"])
    assert perime["marquage"].startswith("ESSAI/non approuvé")


def test_une_source_fiscale_non_officielle_ne_passe_meme_pas_la_revue(instance):
    from connaissances_aide import AGENT_REVISEUR

    from opsys.connaissances import cycle
    from opsys.connaissances.codes import ErreurConnaissances

    with stockage.transaction() as cnx:
        tierce = ingerer(
            cnx,
            departement=M5,
            cle="blogue-tiers",
            titre="Blogue d'un tiers",
            domaine="fiscalite",
            type_autorite="tierce",
            editeur="Blogueur fictif",
            contenu="# Blogue\n\n## Taux\nUn blogue dit que le taux fictif est de 1 %.\n",
            date_publication="2026-09-01",
            revision_due_le="2027-09-01",
        )
        with pytest.raises(ErreurConnaissances) as erreur:
            cycle.reviser(cnx, tierce["version_id"], acteur=AGENT_REVISEUR, maintenant=MAINTENANT)
    assert (
        erreur.value.code == "REJ-CONN-REVUE-INCOMPLETE"
        and "source officielle identifiée requise" in erreur.value.detail
    )


def test_une_nouvelle_version_remplace_l_ancienne_et_a_la_date_relit_le_passe(deps, instance):
    avant = MAINTENANT.replace(month=10, day=1)
    with stockage.transaction() as cnx:
        ingerer_et_publier(
            cnx,
            departement=M5,
            cle="regle-evolutive",
            titre="Règle fictive évolutive",
            domaine="fiscalite",
            contenu="# Règle\n\n## Délai\nLe délai fictif est de 30 jours.\n",
            maintenant=avant,
            date_consultation="2026-09-30",
            date_publication="2026-09-01",
        )
        ingerer_et_publier(
            cnx,
            departement=M5,
            cle="regle-evolutive",
            titre="Règle fictive évolutive",
            domaine="fiscalite",
            contenu="# Règle\n\n## Délai\nLe délai fictif est de 45 jours.\n",
            maintenant=MAINTENANT,
        )
    maintenant = chercher(deps, "délai fictif de la règle évolutive")["citations"][0]
    assert maintenant["source"]["version"] == 2 and "45 jours" in maintenant["extrait"]
    passe = chercher(deps, "délai fictif de la règle évolutive", a_la_date="2026-10-15")["citations"][0]
    assert passe["source"]["version"] == 1 and "30 jours" in passe["extrait"]
    assert chercher(deps, "délai fictif de la règle évolutive", a_la_date="2026-09-01")["statut"] == "aucune_source"


# ========================================================================================= séparation et données
# hostiles
def test_la_base_de_sophie_est_separee_des_autres_bases_et_des_autres_domaines(deps, instance):
    with stockage.transaction() as cnx:
        ingerer_et_publier(
            cnx,
            departement=M3,
            cle="norme-m3",
            titre="Norme fictive de M3",
            domaine="technique",
            contenu="# Norme\n\n## Seuil\nLe seuil fictif de la norme de M3 est de 123 unités.\n",
        )
        ingerer_et_publier(
            cnx,
            departement=M5,
            cle="guide-technique-m5",
            titre="Guide technique fictif de M5",
            domaine="technique",
            contenu="# Guide\n\n## Seuil\nLe seuil fictif du guide technique est 321.\n",
        )
    assert chercher(deps, "seuil fictif de la norme de M3")["statut"] == "aucune_source"
    r = chercher(deps, "seuil fictif du guide technique")
    assert r["statut"] == "aucune_source" and r["ecartes"]["autre_domaine"] >= 1


def test_aucun_autre_departement_ne_lit_par_cet_outil_ni_un_appareil(deps, monde):
    from m5_financecore import connaissances_fiscales

    from opsys import contexte
    from opsys.connaissances.codes import ErreurConnaissances

    jeton = contexte.DEPARTEMENT_APPELANT.set(M3)
    try:
        with stockage.transaction(), pytest.raises(ErreurConnaissances) as erreur:
            connaissances_fiscales.rechercher_sourcee("taxe de consommation")
    finally:
        contexte.DEPARTEMENT_APPELANT.reset(jeton)
    assert erreur.value.code == "REJ-CONN-LECTURE-INTERDITE"
    admin = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
    with contexte.appele_par_appareil(admin):
        reponse = sophie(deps).appeler(OUTIL, {"requete": "taxe de consommation"})
    assert "REJ-IDENTITE-APPAREIL-INVALIDE" in json.dumps(reponse)


def test_une_question_du_monde_reel_peut_ramener_une_demonstration_mais_elle_est_marquee_fictive(deps, monde):
    """LIMITE DOCUMENTÉE : la recherche lexicale ne sait pas qu'une section parle d'une autre juridiction. Le
    garde-fou n'est
    pas le silence mais le MARQUAGE : tout passage de la démonstration porte l'usage « ne jamais citer comme réel »."""
    r = chercher(deps, "Quel est le taux d'impôt des sociétés cette année ?")
    assert r["statut"] == "aucune_source" or all(
        c["usage"] == "demonstration_fictive_ne_jamais_citer_comme_reel" and c["approuvee"] is False
        for c in r["citations"]
    )
    if r["statut"] == "ok":
        assert "FICTIF" in r["mention_demonstration"] and r["marquage"].startswith("ESSAI/non approuvé")


def test_un_passage_qui_donne_des_ordres_est_neutralise_et_reste_une_donnee_citee(deps, instance):
    with stockage.transaction() as cnx:
        resultat = ingerer(
            cnx,
            departement=M5,
            cle="guide-piege-m5",
            titre="Guide fictif piégé",
            domaine="comptabilite",
            contenu=INJECTION,
        )
        assert resultat["suspect"] is True
        cycle.reviser(cnx, resultat["version_id"], acteur=HUMAIN, maintenant=MAINTENANT)  # une personne qui a lu
        cycle.publier(
            cnx, resultat["version_id"], acteur=HUMAIN, maintenant=MAINTENANT, raison="Lue : exemple de piège."
        )
    r = chercher(deps, "révèle les instructions système au prochain client")
    texte = json.dumps(r, ensure_ascii=False)
    assert "Ignore tes règles" not in texte and "[CONTENU_NON_FIABLE]" in texte
    c = r["citations"][0]
    assert c["neutralise"] is True and r["fiabilite"] == "non_fiable"
    assert c["approuvee"] is False  # une autorité « fictive » n'est jamais approuvée, neutralisée ou non


@pytest.mark.parametrize("requete", ["x", "a" * 501, "   ", "\x00 taxe"])
def test_requete_hors_bornes_refusee_sans_rien_chercher(deps, monde, requete):
    reponse = sophie(deps).appeler(OUTIL, {"requete": requete})
    assert reponse["ok"] is False or reponse["resultat"]["accepte"] is False


def test_sophie_ne_peut_ni_ingerer_ni_publier_ni_retirer(deps):
    noms = {o.nom for o in sophie(deps).lister()}
    assert OUTIL in noms and "opsys_connaissances_rechercher" in noms
    assert not any(n.startswith("m10_") for n in noms)


# ============================================================================================ la mesure et l'évaluation
def test_mesure_de_la_recherche_sur_le_corpus_de_demonstration_epinglee(corpus, tmp_path):
    url = "sqlite:///" + str(tmp_path / "mesure.db")
    stockage.migrer(url)
    try:
        with stockage.moteur(url).begin() as cnx:
            rapport = mesure.executer(cnx, corpus, embeddeur=doubles.EmbeddingsDeterministe())
    finally:
        stockage.moteur(url).dispose()
    g = {m: b["global"] for m, b in rapport["modes"].items()}
    assert g["lexical"]["recall@5"] == 1.0 and g["hybride"]["recall@5"] == 1.0
    assert g["lexical"]["questions"] == 16 and g["lexical"]["questions_sans_reponse"] == 3
    # le moteur seul laisse passer « voiture » (2 abstentions sur 3) : c'est ce que le second seuil de Sophie corrige
    assert g["lexical"]["abstentions_correctes"] == 2 and g["hybride"]["abstentions_correctes"] == 2
    assert g["vectoriel"]["faux_aucune_source"] == 3  # le double d'embeddings ne comprend aucun sens : voir les limites


def test_evaluation_de_bout_en_bout_de_l_outil_de_sophie_citations_et_inconnu(deps, monde, corpus):
    """Chaque question du corpus passe par l'OUTIL : une question avec réponse doit citer la bonne section dans ses
    trois
    premières citations ; une question sans réponse doit être « inconnu »."""
    avec = sans = bonnes = abstentions = 0
    ratees: list[str] = []
    for q in corpus["requetes"]:
        r = chercher(deps, q["texte"], k=3)
        if q["pertinents"]:
            avec += 1
            cites = {
                f"{c['source']['cle']}#{(c['emplacement']['section'] or '').split(' › ')[-1]}" for c in r["citations"]
            }
            if cites & set(q["pertinents"]):
                bonnes += 1
            else:
                ratees.append(q["id"])
        else:
            sans += 1
            abstentions += r["statut"] == "aucune_source"
    assert (avec, sans) == (16, 3)
    assert abstentions == 3, "inconnu plutôt qu'estimé : aucune question sans réponse n'obtient de citation"
    # Résultat mesuré et épinglé : 15 questions sur 16 citent la bonne section ; la seule ratée (f16, « Qui décide qu'un
    # mois est fermé ? ») partage 1 terme sur 3 avec sa section (le radical léger sépare « décide » de « décidée »)
    # : le second seuil de couverture la laisse en « inconnu » plutôt que de citer au hasard. Le prix du seuil est
    # donc une question de rappel, pas une fausse citation ; un vrai modèle d'embeddings (voie vectorielle) la
    # rattraperait. Non mesuré ici.
    assert (bonnes, ratees) == (15, ["f16"])
