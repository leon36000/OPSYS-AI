"""Questions obligatoires par service et poids du score de lead (PLAN T4.4) : écrits par le propriétaire dans le
profil d'entreprise, jamais dans le code. Absents, le verdict le dit ; jamais une liste ni un poids par défaut.

Les questions et les poids de ces tests sont fictifs (`fictif: true` dans la fixture de M1 dont ils sont tirés)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from opsys import etat, stockage, taxonomie
from opsys.taxonomie import ProfilInvalide, QuestionQualification

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "departments" / "m01-front-office" / "fixtures" / "qualification" / "profil-fictif.v1.yaml"
)


@pytest.fixture
def profil_fictif() -> dict:
    donnees = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
    assert donnees["fictif"] is True
    return donnees


def _ecrire_profil(contenu: str) -> None:
    fichier = taxonomie.fichier_profil()
    fichier.parent.mkdir(parents=True, exist_ok=True)
    fichier.write_text(contenu, encoding="utf-8")


# -- Questions : jamais dans le code, jamais inventées -----------------------------------------------------------------


def test_sans_profil_aucune_question_n_est_inventee_et_le_verdict_dit_ou_les_declarer(opsys_home):
    questions, verdict = taxonomie.charger_questions_qualification()
    assert questions == {}
    assert verdict["code"] == taxonomie.VERDICT_QUESTIONS_NON_CONFIGUREES
    assert str(taxonomie.fichier_profil()) in verdict["detail"]
    assert "questions_qualification" in verdict["detail"] and "jamais une liste par défaut" in verdict["detail"]
    assert taxonomie.lire_questions_qualification() == {}


@pytest.mark.parametrize("contenu", ["questions_qualification:\n", "questions_qualification: {}\n"])
def test_des_questions_vides_valent_des_questions_absentes(opsys_home, contenu):
    _ecrire_profil(contenu)
    assert taxonomie.charger_questions_qualification()[1]["code"] == taxonomie.VERDICT_QUESTIONS_NON_CONFIGUREES
    assert taxonomie.verifier_profil() == []


def test_un_profil_de_services_sans_questions_n_en_a_pas(opsys_home, declarer_services):
    declarer_services("gouttieres")
    taxonomie.enregistrer_zone_desservie(["Laval"])
    assert taxonomie.charger_questions_qualification()[0] == {}


def test_les_questions_declarees_se_relisent_a_l_identique_et_le_reste_du_profil_demeure(
    opsys_home, declarer_services, profil_fictif
):
    declarer_services("gouttieres", "revetement")
    taxonomie.enregistrer_zone_desservie(["Laval"])
    taxonomie.enregistrer_fenetre_conversation(30)
    fichier = taxonomie.enregistrer_questions_qualification(profil_fictif["questions_qualification"])
    assert fichier == taxonomie.fichier_profil()

    questions, verdict = taxonomie.charger_questions_qualification()
    assert verdict is None
    assert set(questions) == {"gouttieres", "revetement", "soffite_fascia", "reparation"}
    assert questions["gouttieres"][0] == QuestionQualification(
        "longueur", "Quelle est la longueur approximative de gouttières à remplacer, en pieds ou en mètres?",
        ("pied", "mètre", "pouce"), False)
    assert [q.code for q in questions["gouttieres"]] == ["longueur", "etages", "photo_facade"], "ordre écrit"
    assert questions["gouttieres"][2].photos is True and questions["gouttieres"][2].mots_cles == ()

    # Déclarer autre chose ensuite n'efface pas les questions, et elles n'effacent rien.
    taxonomie.enregistrer_services(["gouttieres"])
    taxonomie.enregistrer_zone_desservie(["Québec"])
    taxonomie.enregistrer_fenetre_conversation(60)
    assert taxonomie.charger_questions_qualification()[0] == questions
    assert [s.code for s in taxonomie.lire_services()] == ["gouttieres"]
    assert taxonomie.lire_zone_desservie() == ("Québec",)
    assert taxonomie.lire_fenetre_conversation() == 60


def test_les_questions_d_un_service_et_le_verdict_du_service_sans_question(opsys_home, profil_fictif):
    gouttieres = profil_fictif["questions_qualification"]["gouttieres"]
    taxonomie.enregistrer_questions_qualification({"gouttieres": gouttieres})
    questions, verdict = taxonomie.charger_questions_du_service("gouttieres")
    assert verdict is None and [q.code for q in questions] == ["longueur", "etages", "photo_facade"]

    aucune, verdict = taxonomie.charger_questions_du_service("revetement")
    assert aucune == ()
    assert verdict["code"] == taxonomie.VERDICT_QUESTIONS_NON_CONFIGUREES
    assert "'revetement'" in verdict["detail"] and str(taxonomie.fichier_profil()) in verdict["detail"]


def test_le_verdict_du_service_sans_profil_dit_aussi_le_service(opsys_home):
    aucune, verdict = taxonomie.charger_questions_du_service("gouttieres")
    assert aucune == () and verdict["code"] == taxonomie.VERDICT_QUESTIONS_NON_CONFIGUREES
    assert "'gouttieres'" in verdict["detail"]


@pytest.mark.parametrize("contenu, motif", [
    ("questions_qualification: [a]\n", "objet"),
    ("questions_qualification: {gouttieres: []}\n", "vide"),
    ("questions_qualification: {gouttieres: longueur}\n", "liste de questions"),
    ("questions_qualification: {Gouttières: [{code: a, question: 'Q?', mots_cles: [x]}]}\n", "service invalide"),
    ("questions_qualification: {gouttieres: [texte]}\n", "un objet"),
    ("questions_qualification: {gouttieres: [{code: a, question: 'Q?', mots_cles: [x], prix: 1}]}\n", "clés inconnues"),
    ("questions_qualification: {gouttieres: [{code: A, question: 'Q?', mots_cles: [x]}]}\n", "service invalide"),
    ("questions_qualification: {gouttieres: [{code: a, mots_cles: [x]}]}\n", "'question'"),
    ("questions_qualification: {gouttieres: [{code: a, question: '  ', mots_cles: [x]}]}\n", "'question'"),
    ("questions_qualification: {gouttieres: [{code: a, question: \"Q?\\nR?\", mots_cles: [x]}]}\n", "une ligne"),
    ("questions_qualification: {gouttieres: [{code: a, question: 'Q?'}]}\n", "'mots_cles' requis"),
    ("questions_qualification: {gouttieres: [{code: a, question: 'Q?', mots_cles: []}]}\n", "'mots_cles' requis"),
    ("questions_qualification: {gouttieres: [{code: a, question: 'Q?', mots_cles: ['']}]}\n", "chaîne non vide"),
    ("questions_qualification: {gouttieres: [{code: a, question: 'Q?', mots_cles: [x], photos: oui}]}\n", "'photos'"),
    ("questions_qualification: {gouttieres: [{code: a, question: 'Q?', mots_cles: [x], photos: true}]}\n",
     "ne se reconnaît pas"),
    ("questions_qualification: {gouttieres: [{code: a, question: 'Q?', mots_cles: [x]}, "
     "{code: a, question: 'R?', mots_cles: [y]}]}\n", "en double"),
    ("questions_qualification: {gouttieres: [{code: a, question: 'Q?', mots_cles: [x]\n", "illisible"),
])
def test_des_questions_mal_formees_sont_refusees_avec_la_raison_jamais_lues_comme_absentes(
    opsys_home, contenu, motif
):
    _ecrire_profil(contenu)
    with pytest.raises(ProfilInvalide, match=motif):
        taxonomie.lire_questions_qualification()
    questions, verdict = taxonomie.charger_questions_qualification()
    assert questions == {}
    assert verdict["code"] == taxonomie.VERDICT_PROFIL_INVALIDE, "distinct de l'absence"
    assert taxonomie.charger_questions_du_service("gouttieres")[1]["code"] == taxonomie.VERDICT_PROFIL_INVALIDE
    assert taxonomie.verifier_profil() != []


def test_trop_de_questions_pour_un_service_est_refuse(opsys_home):
    onze = [{"code": f"q{i}", "question": "Q?", "mots_cles": ["x"]} for i in range(11)]
    with pytest.raises(ProfilInvalide, match="10 questions au plus"):
        taxonomie.normaliser_questions_qualification({"gouttieres": onze})
    assert len(taxonomie.normaliser_questions_qualification({"gouttieres": onze[:10]})["gouttieres"]) == 10


def test_une_question_trop_longue_est_refusee(opsys_home):
    with pytest.raises(ProfilInvalide, match="300 caractères"):
        taxonomie.normaliser_questions_qualification(
            {"gouttieres": [{"code": "a", "question": "x" * 301, "mots_cles": ["x"]}]})


def test_enregistrer_des_questions_invalides_ne_touche_pas_au_profil(opsys_home, declarer_services):
    declarer_services("gouttieres")
    avant = taxonomie.fichier_profil().read_text(encoding="utf-8")
    for invalide in ({}, [], {"gouttieres": []}, {"gouttieres": [{"code": "a", "question": "Q?"}]}, None):
        with pytest.raises(ProfilInvalide):
            taxonomie.enregistrer_questions_qualification(invalide)
    assert taxonomie.fichier_profil().read_text(encoding="utf-8") == avant


def test_enregistrer_les_questions_signe_au_journal_sans_recopier_leur_texte(opsys_home, profil_fictif):
    stockage.migrer()
    taxonomie.enregistrer_questions_qualification(profil_fictif["questions_qualification"], par="nathan")
    with etat.session() as cnx:
        journal = etat.lire_journal(cnx)
    assert journal[0]["par"] == "nathan" and journal[0]["action"] == "entreprise.questions_qualification"
    assert journal[0]["details"] == {
        "questions_par_service": {"gouttieres": 3, "revetement": 2, "soffite_fascia": 1, "reparation": 2}}


def test_verifier_signale_des_questions_pour_un_service_que_l_entreprise_ne_declare_pas(opsys_home, declarer_services):
    declarer_services("gouttieres")
    taxonomie.enregistrer_questions_qualification({
        "gouttieres": [{"code": "a", "question": "Q?", "mots_cles": ["x"]}],
        "revetement": [{"code": "b", "question": "R?", "mots_cles": ["y"]}],
    })
    (probleme,) = taxonomie.verifier_profil()
    assert "'revetement'" in probleme and "gouttieres" in probleme


# -- Poids du score : « à configurer », jamais un poids par défaut -----------------------------------------------------


def test_sans_profil_aucun_poids_n_est_invente_et_le_verdict_dit_a_configurer(opsys_home):
    poids, verdict = taxonomie.charger_poids_score_lead()
    assert poids is None
    assert verdict["code"] == taxonomie.VERDICT_POIDS_SCORE_NON_CONFIGURES
    assert verdict["detail"].startswith("poids à configurer")
    assert str(taxonomie.fichier_profil()) in verdict["detail"] and "aucun score" in verdict["detail"]
    for critere in taxonomie.CRITERES_SCORE_LEAD:
        assert critere in verdict["detail"]
    assert taxonomie.lire_poids_score_lead() is None


@pytest.mark.parametrize("contenu", ["poids_score_lead:\n", "poids_score_lead: {}\n"])
def test_des_poids_vides_valent_des_poids_a_configurer(opsys_home, contenu):
    _ecrire_profil(contenu)
    assert taxonomie.charger_poids_score_lead()[1]["code"] == taxonomie.VERDICT_POIDS_SCORE_NON_CONFIGURES
    assert taxonomie.verifier_profil() == []


def test_les_poids_declares_se_relisent_a_l_identique_et_le_reste_du_profil_demeure(
    opsys_home, declarer_services, profil_fictif
):
    declarer_services("gouttieres")
    taxonomie.enregistrer_zone_desservie(["Laval"])
    taxonomie.enregistrer_poids_score_lead(profil_fictif["poids_score_lead"])
    assert taxonomie.charger_poids_score_lead() == ({"urgence": 30, "completude": 50, "zone": 20}, None)
    taxonomie.enregistrer_services(["reparation"])
    taxonomie.enregistrer_zone_desservie(["Québec"])
    assert taxonomie.lire_poids_score_lead() == {"urgence": 30, "completude": 50, "zone": 20}
    assert yaml.safe_load(taxonomie.fichier_profil().read_text(encoding="utf-8"))["poids_score_lead"] == {
        "completude": 50, "urgence": 30, "zone": 20}


def test_un_poids_zero_ecarte_un_critere_explicitement(opsys_home):
    taxonomie.enregistrer_poids_score_lead({"urgence": 0, "completude": 1, "zone": 0})
    assert taxonomie.lire_poids_score_lead() == {"urgence": 0, "completude": 1, "zone": 0}


@pytest.mark.parametrize("contenu, motif", [
    ("poids_score_lead: [1, 2, 3]\n", "objet"),
    ("poids_score_lead: {urgence: 1, completude: 1}\n", "poids manquants"),
    ("poids_score_lead: {urgence: 1, completude: 1, zone: 1, prix: 3}\n", "critères inconnus"),
    ("poids_score_lead: {urgence: '30', completude: 50, zone: 20}\n", "entier"),
    ("poids_score_lead: {urgence: 30.5, completude: 50, zone: 20}\n", "entier"),
    ("poids_score_lead: {urgence: true, completude: 50, zone: 20}\n", "entier"),
    ("poids_score_lead: {urgence: -1, completude: 50, zone: 20}\n", "entier"),
    ("poids_score_lead: {urgence: 1001, completude: 50, zone: 20}\n", "entier"),
    ("poids_score_lead: {urgence: 30, completude: ~, zone: 20}\n", "entier"),
    ("poids_score_lead: {urgence: 0, completude: 0, zone: 0}\n", "au moins un poids"),
    ("poids_score_lead: {urgence: 30\n", "illisible"),
])
def test_des_poids_mal_formes_sont_refuses_avec_la_raison_jamais_lus_comme_a_configurer(opsys_home, contenu, motif):
    _ecrire_profil(contenu)
    with pytest.raises(ProfilInvalide, match=motif):
        taxonomie.lire_poids_score_lead()
    poids, verdict = taxonomie.charger_poids_score_lead()
    assert poids is None
    assert verdict["code"] == taxonomie.VERDICT_PROFIL_INVALIDE, "distinct de « à configurer »"
    assert taxonomie.verifier_profil() != []


def test_enregistrer_des_poids_invalides_ne_touche_pas_au_profil(opsys_home, declarer_services):
    declarer_services("gouttieres")
    avant = taxonomie.fichier_profil().read_text(encoding="utf-8")
    for invalide in ({}, {"urgence": 1}, {"urgence": 0, "completude": 0, "zone": 0}, {"urgence": 1.5, "completude": 1,
                                                                                    "zone": 1}, None):
        with pytest.raises(ProfilInvalide):
            taxonomie.enregistrer_poids_score_lead(invalide)
    assert taxonomie.fichier_profil().read_text(encoding="utf-8") == avant


def test_enregistrer_les_poids_signe_au_journal_d_audit(opsys_home):
    stockage.migrer()
    taxonomie.enregistrer_poids_score_lead({"urgence": 30, "completude": 50, "zone": 20}, par="nathan")
    with etat.session() as cnx:
        journal = etat.lire_journal(cnx)
    assert journal[0]["par"] == "nathan" and journal[0]["action"] == "entreprise.poids_score_lead"
    assert journal[0]["details"] == {"poids": {"urgence": 30, "completude": 50, "zone": 20}}


def test_un_fichier_illisible_n_est_signale_qu_une_fois_meme_avec_les_nouvelles_cles(opsys_home):
    _ecrire_profil("questions_qualification: {gouttieres: [\n")
    assert len(taxonomie.verifier_profil()) == 1
