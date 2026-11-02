"""M1-A — le pack « rénovation extérieure » rend M1 capable de qualifier, une fois ses propositions adoptées.

Trajet prouvé (SQLite réelle, vrai bus, vrai M2, vraies consoles de profil ; aucun réseau, aucun envoi) :

    pack choisi, propositions adoptées par une personne (signées au journal)
      -> SMS d'un client (champs que la plateforme donne à l'agent) -> `Capacites.appeler("m1_recevoir_message_canal")`
      -> qualification : questions du service lues du PROFIL, photos (fermées sans politique validée), score, prochaine
         action ; lead v2 -> bus -> M2 (contrat reçu tel quel)
      -> plainte, menace juridique, danger : transfert à un humain (rôle du profil), jamais un lead

et les MÊMES entrées sans adoption : comportement actuel de M1 (il enregistre, ne pose aucune question de qualification,
ne reconnaît ni plainte ni danger).

Données FICTIVES (numéros en 555, aucun nom). Ce que ces tests ne prouvent pas : que les questions et les mots du
pack soient les bons pour de vrais clients (corpus fictif écrit par l'auteur du pack), ni aucun SMS réel.
"""

from __future__ import annotations

import datetime as dt

import pytest
from m1_front_office import outils as m1
from m1_front_office import plaintes
from sqlalchemy import func, select

from opsys import evenements, packs, stockage, taxonomie
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.stockage.schema import JOURNAL

RENOVATION = "renovation-exterieure-qc"
DEBUT = dt.datetime(2026, 9, 29, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=-4)))
SMS_GOUTTIERES = "Bonjour, mes gouttières débordent à Laval, c'est urgent."
SMS_REPONSES = ("C'est une maison de 2 étages au 123 rue des Érables, il y a des arbres, je veux un remplacement, "
                "la couleur blanc. Le problème : ça déborde.")
CODES_GOUTTIERES = ["adresse", "type_batiment", "etages", "probleme", "reparation_ou_neuf", "urgence", "delai",
                    "acces_arbres", "couleur"]


def _numero(n: int) -> str:
    return f"+1514555{n:04d}"


def _a(minutes: float = 0) -> str:
    return (DEBUT + dt.timedelta(minutes=minutes)).isoformat()


@pytest.fixture
def instance(tmp_path, monkeypatch, declarer_services):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    declarer_services()
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    m1.utiliser_stockage_durable()
    from m2_revenue_crm import outils as m2

    m2.utiliser_stockage_durable()
    yield charger_departements()
    m1.reinitialiser_registre()
    m2.reinitialiser_registre()
    stockage.liberer()


@pytest.fixture
def capacites(instance):
    return Capacites(instance, stockage.transaction, filtre={"m01-front-office"}, memoire=False)


def _adopter(*elements: str) -> None:
    packs.enregistrer_pack(RENOVATION, par="nathan-fictif")
    for element in elements or packs.ELEMENTS:
        packs.adopter_proposition(element, par="nathan-fictif")


def _sms(capacites, numero: int, texte: str, message_id: str, minutes: float = 0) -> dict:
    reponse = capacites.appeler("m1_recevoir_message_canal", {
        "canal": "sms", "expediteur": _numero(numero), "message_id": message_id, "recu_le": _a(minutes),
        "texte": texte})
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _drainer(deps) -> dict:
    total = {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 0}
    for tour in range(10):
        resume = evenements.repartir(deps, maintenant=(DEBUT + dt.timedelta(seconds=90 * tour)).isoformat())
        for cle in total:
            total[cle] += resume[cle]
        if resume["livres"] == 0:
            return total
    raise AssertionError(f"le bus n'a pas atteint la quiescence : {total}")


def _leads_chez_m2() -> list[dict]:
    with stockage.transaction():
        return [m for m in stockage.maillons("m02-revenue-crm", "principal") if m.get("type_entree") == "lead_ingere"]


def _politique_photos(monkeypatch, statut: str) -> None:
    monkeypatch.setattr(m1, "_politique_photos_texte", lambda: f"STATUT_VALIDATION: {statut}\n")


# ====================================================================== sans adoption : le comportement actuel de M1
def test_sans_adoption_une_demande_de_gouttieres_est_enregistree_mais_rien_n_est_qualifie(capacites, instance):
    packs.enregistrer_pack(RENOVATION, par="nathan-fictif")  # choisir le pack n'active rien
    r = _sms(capacites, 1, SMS_GOUTTIERES, "SMa1")
    assert r["decision"] == "TRANSMETTRE_M2" and r["lead"]["service"] == "gouttieres"  # service + ville + contact
    assert "questions" not in r and "photos" not in r and "score" not in r and "prochaine_action" not in r
    assert r["conversation"]["mode"] == "message_par_message"  # aucune fenêtre déclarée : rien n'est rassemblé
    assert "Quelle est l'adresse" not in str(r)
    assert r["plainte"]["statut"] == "vocabulaire_a_configurer"  # M1 le dit : rien n'est reconnu
    assert _drainer(instance)["echecs"] == 0 and len(_leads_chez_m2()) == 1


def test_meme_avec_une_fenetre_declaree_a_la_main_les_questions_restent_non_configurees_sans_adoption(capacites):
    taxonomie.enregistrer_fenetre_conversation(30)
    packs.enregistrer_pack(RENOVATION, par="nathan-fictif")
    r = _sms(capacites, 13, SMS_GOUTTIERES, "SMb1")
    assert r["questions"]["statut"] == "non_configurees" and r["questions"]["restantes"] == []
    assert r["questions"]["verdict"]["code"] == taxonomie.VERDICT_QUESTIONS_NON_CONFIGUREES
    assert "photos" not in r and "brouillon_reponse" not in r
    assert r["score"]["statut"] != "calcule"  # « poids à configurer »


@pytest.mark.parametrize(("texte", "reconnu_avec_le_pack", "niveau"), [
    ("Ça fait 3 fois que j'appelle, je vais appeler mon avocat.", "ESCALADE_PLAINTE", "N5"),
    ("Il y a de la fumée et un fil électrique qui pend sur mes gouttières à Laval.", "ESCALADE_URGENCE", "N5"),
    ("Après vos travaux, mes gouttières à Laval fuient encore, je suis déçu.", "ESCALADE_PLAINTE", "N4"),
])
def test_sans_adoption_une_plainte_ou_un_danger_n_est_pas_reconnu_avec_l_adoption_il_l_est(
        capacites, instance, texte, reconnu_avec_le_pack, niveau):
    sans = _sms(capacites, 2, texte, "SMsans")
    assert sans["decision"] in ("DEMANDER_PRECISIONS", "TRANSMETTRE_M2"), sans["decision"]  # traité comme une demande
    assert "transfert" not in sans and sans["plainte"]["statut"] == "vocabulaire_a_configurer"
    _adopter("signaux_plainte", "destinataires_transfert")
    avec = _sms(capacites, 3, texte, "SMavec", 1)  # un autre correspondant : sa propre conversation
    assert avec["decision"] == reconnu_avec_le_pack and avec["qualifie"] is False
    assert avec["transfert"]["destinataire"] == "nathan_owner" and avec["transfert"]["niveau"] == niveau
    assert "lead" not in avec  # la plainte prime : jamais un lead


# ================================================================= avec adoption : qualifier une demande
def test_gouttieres_photos_manquantes_les_questions_manquantes_sont_demandees_et_le_lead_part_chez_m2(
        capacites, instance, monkeypatch):
    _politique_photos(monkeypatch, "valide")  # la politique « photos » validée par une personne (essai)
    _adopter()
    r = _sms(capacites, 4, SMS_GOUTTIERES, "SMq1")
    # 1. le lead est complet pour M2 (service, ville, contact du canal, urgence déclarée)
    assert r["decision"] == "TRANSMETTRE_M2"
    lead = r["lead"]
    assert (lead["service"], lead["ville"], lead["urgence_declaree"], lead["contact"]) == (
        "gouttieres", "Laval", True, {"telephone": _numero(4)})
    # 2. les questions du service viennent du PROFIL adopté, dans l'ordre écrit ; « débordent » répond à `probleme`,
    #    « urgent » à `urgence`
    assert r["questions"]["statut"] == "a_poser" and r["questions"]["repondues"] == ["probleme", "urgence"]
    assert [q["code"] for q in r["questions"]["restantes"]] == [
        c for c in CODES_GOUTTIERES if c not in ("probleme", "urgence")]
    # 3. la demande de photos (avant, arrière, côtés) est ouverte et fait partie du brouillon (jamais envoyé)
    assert r["photos"] == {"statut": "ouverte", "questions": ["photos_facades"]}
    assert "photos de l'avant, de l'arrière et des côtés" in r["brouillon_reponse"] and r["envoye"] is False
    # 4. le score est calculé avec les poids adoptés ; la prochaine action est datée par la fenêtre adoptée
    assert r["score"]["statut"] == "calcule" and {c["poids"] for c in r["score"]["criteres"]} == {30, 50, 20}
    assert r["prochaine_action"]["a_faire_avant"] == _a(30)
    # 5. M2 reçoit le lead tel quel, par le vrai bus
    assert _drainer(instance)["echecs"] == 0
    (ingere,) = _leads_chez_m2()
    assert ingere["contrat"] == lead and ingere["contrat"]["service"] == "gouttieres"

    # le client répond à plusieurs questions : elles ne sont plus redemandées, mais aucun second lead n'est créé
    suite = _sms(capacites, 4, SMS_REPONSES, "SMq2", 5)
    assert suite["decision"] == "CONVERSATION_DEJA_QUALIFIEE"
    assert suite["questions"]["repondues"] == [c for c in CODES_GOUTTIERES if c not in ("delai",)]
    assert [q["code"] for q in suite["questions"]["restantes"]] == ["delai"]
    assert suite["score"]["score"] > r["score"]["score"]
    assert _drainer(instance)["livres"] == 0 and len(_leads_chez_m2()) == 1


def test_les_photos_restent_fermees_tant_que_la_politique_n_est_pas_validee_meme_avec_le_pack_adopte(
        capacites, monkeypatch):
    _politique_photos(monkeypatch, "proposition")
    _adopter()
    r = _sms(capacites, 5, SMS_GOUTTIERES, "SMp1")
    assert r["photos"]["statut"] == "fermee" and r["photos"]["verdict"]["code"] == "REJ-PHOTO-POLITIQUE-NON-VALIDEE"
    assert "photos" not in r["brouillon_reponse"] and "photo" not in r["brouillon_reponse"].lower()
    assert "adresse" in r["brouillon_reponse"]  # les questions de texte, elles, sont posées


@pytest.mark.parametrize(("service_texte", "service", "premieres"), [
    ("Je voudrais remplacer mon revêtement en vinyle à Québec.", "revetement",
     ["adresse", "etages", "surface", "infiltration", "delai"]),
    ("Mon soffite est pourri à Laval.", "soffite_fascia", ["longueur", "ventilation", "hauteur", "acces"]),
])
def test_chaque_service_du_pack_a_ses_propres_questions(capacites, monkeypatch, service_texte, service, premieres):
    _politique_photos(monkeypatch, "valide")
    _adopter()
    r = _sms(capacites, 6, service_texte, "SMs1")
    assert r["lead"]["service"] == service and r["questions"]["service"] == service
    restantes = [q["code"] for q in r["questions"]["restantes"]]
    assert all(code in restantes for code in premieres), restantes
    assert r["photos"]["statut"] == "ouverte"


def test_les_questions_d_un_service_ne_sont_pas_posees_pour_un_autre(capacites):
    _adopter("questions_qualification", "fenetre_conversation_minutes")
    r = _sms(capacites, 7, "Je voudrais remplacer mon revêtement à Québec.", "SMs2")
    codes = {q["code"] for q in r["questions"]["restantes"]}
    assert "revetement_actuel" in codes and "couleur" not in codes and "acces_arbres" not in codes


# ====================================================================== avec adoption : plainte, menace, danger
def test_une_menace_juridique_ouvre_un_transfert_n5_au_role_adopte_sans_lead_et_sans_brouillon(
        capacites, instance):
    _adopter()
    r = _sms(capacites, 8, "Ça fait 3 fois que j'appelle, je vais appeler mon avocat.", "SMc1")
    assert r["decision"] == "ESCALADE_PLAINTE" and r["qualifie"] is False and "lead" not in r
    assert r["plainte"]["categories"] == ["avocat"]
    assert r["transfert"]["type_transfert"] == "plainte" and r["transfert"]["niveau"] == "N5"
    assert r["transfert"]["destinataire"] == "nathan_owner" and r["transfert"]["verdict_destinataire"] is None
    assert r["brouillon_reponse"] is None and r["sans_brouillon"] == "sujet_legal_reponse_humaine"
    assert _drainer(instance)["livres"] == 0 and _leads_chez_m2() == []  # rien chez M2 : ce n'est pas un lead


def test_un_danger_est_escalade_tout_de_suite_sans_conseil_ni_promesse(capacites, instance):
    _adopter()
    r = _sms(capacites, 9, "Il y a de la fumée et un fil électrique qui pend de ma gouttière à Laval.", "SMd1")
    assert r["decision"] == "ESCALADE_URGENCE" and "lead" not in r
    assert r["transfert"]["type_transfert"] == "urgence" and r["transfert"]["niveau"] == "N5"
    assert r["transfert"]["destinataire"] == "nathan_owner"
    assert "conseil" in r["consigne"].lower() and "AUCUNE intervention" in r["consigne"]
    assert _drainer(instance)["livres"] == 0 and _leads_chez_m2() == []


def test_une_plainte_de_degat_va_au_proprietaire_avec_un_brouillon_empathique_jamais_envoye(capacites):
    _adopter()
    r = _sms(capacites, 10, "Après vos travaux, vos employés ont brisé ma clôture, je suis très déçu.", "SMc2")
    assert r["decision"] == "ESCALADE_PLAINTE" and r["transfert"]["niveau"] == "N4"
    assert set(r["plainte"]["categories"]) == {"insatisfaction", "degat"}
    assert r["envoye"] is False and "transmis à une personne" in r["brouillon_reponse"]


def test_sans_destinataire_adopte_le_transfert_s_ouvre_quand_meme_et_dit_destinataire_a_configurer(capacites):
    _adopter("signaux_plainte")
    r = _sms(capacites, 11, "Je vais vous envoyer une mise en demeure.", "SMc3")
    assert r["decision"] == "ESCALADE_PLAINTE" and r["transfert"]["destinataire"] is None
    assert r["transfert"]["verdict_destinataire"]["code"] == taxonomie.VERDICT_DESTINATAIRE_NON_CONFIGURE


def test_une_adoption_partielle_n_active_que_ce_qui_a_ete_adopte(capacites):
    _adopter("questions_qualification", "fenetre_conversation_minutes")
    r = _sms(capacites, 12, SMS_GOUTTIERES, "SMx1")
    assert r["questions"]["statut"] == "a_poser" and r["score"]["statut"] != "calcule"  # questions oui, poids non
    assert r["plainte"]["statut"] == "vocabulaire_a_configurer"


def test_les_questions_adoptees_sans_fenetre_adoptee_ne_sont_pas_posees_limite_de_m1(capacites):
    """Constat : M1 ne pose les questions du service qu'avec une fenêtre de conversation (elle rassemble les messages).
    Adopter les questions seules n'a donc aucun effet visible : la documentation du pack le dit."""
    _adopter("questions_qualification")
    r = _sms(capacites, 14, SMS_GOUTTIERES, "SMx2")
    assert "questions" not in r and r["conversation"]["mode"] == "message_par_message"


def test_l_adoption_est_au_journal_et_le_profil_final_est_valide(instance, session):
    _adopter()
    with stockage.transaction() as cnx:
        n = cnx.execute(select(func.count()).select_from(JOURNAL)
                        .where(JOURNAL.c.action == "entreprise.adoption_proposition")).scalar_one()
    assert n == 5 and taxonomie.verifier_profil() == []


# ================================================================= le vocabulaire proposé, sur un corpus fictif
COMPLAINTES = [
    ("Je suis très déçu du travail de vos gens.", "insatisfaction"),
    ("On est vraiment mécontents, c'est inacceptable.", "insatisfaction"),
    ("Ça fait trois semaines et personne ne me rappelle.", "insatisfaction"),
    ("Votre service est lamentable, j'en ai assez.", "insatisfaction"),
    ("Le travail est bâclé, je suis en colère.", "insatisfaction"),
    ("Je vais laisser un mauvais avis partout.", "insatisfaction"),
    ("C'est une arnaque!", "insatisfaction"),
    ("Je veux faire une plainte officielle.", "insatisfaction"),
    ("Après vos travaux, mon entrée est pleine de dégâts.", "degat"),
    ("Vos employés ont brisé ma clôture.", "degat"),
    ("Vous avez endommagé mon revêtement en installant la gouttière.", "degat"),
    ("Après votre passage, il y a de l'eau partout dans le sous-sol.", "degat"),
    ("La gouttière est mal installée, elle est encore sous garantie.", "garantie"),
    ("Je fais une réclamation, le travail est défectueux.", "garantie"),
    ("C'est une malfaçon évidente.", "garantie"),
    ("Mon avocat va vous contacter.", "avocat"),
    ("Vous allez recevoir une mise en demeure.", "avocat"),
    ("Je vais vous poursuivre devant les petites créances.", "avocat"),
    ("J'appelle la Régie du bâtiment demain.", "avocat"),
    ("Je vais porter plainte à la protection du consommateur.", "avocat"),
    ("Il y a de la fumée qui sort du mur près de la gouttière.", "securite"),
    ("Un fil électrique pend de la façade, c'est dangereux!", "securite"),
    ("Ça sent le gaz près de l'échafaudage.", "securite"),
    ("Mon fils est blessé, un morceau est tombé.", "securite"),
    ("Le balcon s'effondre.", "securite"),
    ("Appelez une ambulance, quelqu'un est tombé de l'échelle.", "securite"),
]
ORDINAIRES = [
    SMS_GOUTTIERES,
    "Avez-vous une garantie sur les gouttières?",
    "Ma gouttière est brisée depuis la tempête, pouvez-vous la réparer?",
    "Je voudrais une soumission pour du revêtement en vinyle à Québec.",
    "Merci beaucoup, le travail est super, je suis très content.",
    "La cour arrière est accessible par la clôture de gauche.",
    "Vous venez quand pour évaluer mon soffite?",
    "Un arbre a abîmé ma gouttière pendant l'orage, quel est votre délai?",
    "Je voudrais une réparation de fascia, ce n'est pas urgent.",
    "Pouvez-vous m'envoyer des photos de vos réalisations?",
    "Est-ce que vous faites aussi le déneigement du toit?",
    "Mon voisin m'a recommandé votre entreprise.",
    "J'aimerais un rendez-vous la semaine prochaine pour mes gouttières.",
    "Combien de temps dure l'installation d'un revêtement?",
    "Je reçois ma soumission demain, merci.",
]
# Limites du code (il lit des mots, pas le sens), documentées : ironie, formulation indirecte, anglais absent du
# vocabulaire. Elles ne sont pas reconnues ; le jugement de l'agent (`m1_escalader_plainte`) couvre ce que les
# règles ratent.
NON_RECONNUES_CONNUES = [
    "Je commence à perdre patience avec vous.",
    "Bravo, encore un travail parfait... vraiment, bravo.",
    "This is unacceptable, I want my money back.",
]
FAUX_POSITIF_CONNU = "Ma voisine est avocate et elle a adoré vos gouttières."


@pytest.fixture(scope="module")
def signaux():
    return packs.charger_pack(RENOVATION).propositions_profil.elements["signaux_plainte"]


def test_toutes_les_plaintes_et_tous_les_dangers_du_corpus_fictif_sont_reconnus_dans_la_bonne_categorie(signaux):
    ratees = []
    for texte, categorie in COMPLAINTES:
        d = plaintes.detecter(texte, signaux)
        if categorie not in d.categories:
            ratees.append((categorie, d.categories, texte))
    assert ratees == [], ratees
    assert len(COMPLAINTES) == 26


def test_aucune_demande_ordinaire_du_corpus_fictif_n_est_escaladee_a_tort(signaux):
    faux = [(t, plaintes.detecter(t, signaux).categories) for t in ORDINAIRES if plaintes.detecter(t, signaux).reconnu]
    assert faux == [] and len(ORDINAIRES) == 15


def test_les_limites_connues_du_vocabulaire_sont_dites_et_stables(signaux):
    for texte in NON_RECONNUES_CONNUES:
        assert plaintes.detecter(texte, signaux).reconnu is False, texte
    assert plaintes.detecter(FAUX_POSITIF_CONNU, signaux).categories == ("avocat",)  # coûte une lecture humaine


def test_une_garantie_demandee_par_un_prospect_n_est_pas_une_plainte_mais_sous_garantie_en_est_une(signaux):
    assert plaintes.detecter("Quelle garantie offrez-vous?", signaux).reconnu is False
    assert plaintes.detecter("Ma gouttière est sous garantie, venez la refaire.", signaux).categories == ("garantie",)
