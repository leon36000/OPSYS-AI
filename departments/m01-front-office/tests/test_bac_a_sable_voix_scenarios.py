"""Bac à sable vocal TEXTUEL — scénarios de bout en bout de la POLITIQUE DE DIALOGUE de M1 (M1.19, mode 2).

Ce que ces scénarios prouvent : sur des faux appels écrits d'avance (tours de texte, confiance de transcription
injectée,
horloge simulée), avec les vrais morceaux de M1 (qualification, plaintes, transferts avec résumé, registre, garde-fou,
session
voix du socle) et le profil produit par l'ADOPTION du pack de rénovation, les règles de dialogue tiennent : jamais un
prix,
une date, un engagement, un aveu ni un avis légal ; redemander sur faible confiance ; repli sur échecs répétés, colère,
danger ; messagerie quand personne n'est disponible ; aucun transfert sans résumé.

Ce qu'ils NE prouvent PAS : la voix. Aucun audio, aucun moteur de transcription ni de synthèse, aucune ligne
téléphonique,
aucun fournisseur ; latence, accent et bruit non mesurés. Les matrices M1.2 et M1.19 ne passent pas à FAIT_PROUVE.
Données FICTIVES (numéros en 555, aucun nom).
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from m1_front_office import bac_a_sable_voix as bac
from m1_front_office import garde_fou, politique_dialogue, transferts
from m1_front_office import outils as m1
from m1_front_office.politique_dialogue import SeuilsDialogue

from opsys import evenements, packs, stockage, taxonomie
from opsys.departements import charger_departements

RENOVATION = "renovation-exterieure-qc"
DEBUT = "2026-09-29T09:00:00-04:00"
PARAMETRES = bac.ParametresBac(SeuilsDialogue(Decimal("0.60"), 2), 3, 0.8, "Léa", "Entreprise Fictive")
MOTS_DE_CONSEIL = ("911", "évacu", "éloign", "appelez", "coupez", "ne touchez", "sortez")
MOTS_DE_PROMESSE = ("désolé", "excuse", "garanti", "promet", "rembours", "dédommag", "rappellera", "immédiatement")


def T(t, texte, confiance=0.95, **options):
    return bac.TourAppelant(t, texte, confiance, **options)


def appel(*tours, numero=1, humain=True, consentement="accorde"):
    return bac.AppelScript(f"scenario-{numero}", f"+1514555{numero:04d}", DEBUT, tuple(tours),
                           humain_disponible=humain, consentement_enregistrement=consentement)


@pytest.fixture
def instance(tmp_path, monkeypatch, declarer_services):
    """Une instance fictive : services, zone, pack choisi et ses cinq propositions ADOPTÉES par une personne."""
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    declarer_services()
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    packs.enregistrer_pack(RENOVATION, par="nathan-fictif")
    for element in packs.ELEMENTS:
        packs.adopter_proposition(element, par="nathan-fictif")
    m1.reinitialiser_registre()
    yield
    m1.reinitialiser_registre()
    stockage.liberer()


def _transferts() -> list:
    return transferts.lire(m1._obtenir_registre().lire())


def _registre_en_texte() -> str:
    return json.dumps(list(m1._obtenir_registre().lire()), ensure_ascii=False, default=str)


def _avatar_est_sur(rapport) -> None:
    for texte in rapport.textes_avatar():
        assert garde_fou.verifier_sortie(texte)["code"] == "OK", texte
        assert not any(c.isdigit() for c in texte.replace("911", "")) or "$" not in texte


# ====================================================================== 1. appel de gouttières complet
def test_appel_gouttieres_complet_qualification_par_les_questions_du_pack_et_lead_chez_m2(
        tmp_path, monkeypatch, declarer_services):
    """Le lead est créé sur le registre DURABLE d'une base de test, publié au vrai bus et consommé par le vrai M2."""
    url = f"sqlite:///{tmp_path / 'durable.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    declarer_services()
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    packs.enregistrer_pack(RENOVATION, par="nathan-fictif")
    for element in packs.ELEMENTS:
        packs.adopter_proposition(element, par="nathan-fictif")
    from m2_revenue_crm import outils as m2

    m1.utiliser_stockage_durable()
    m2.utiliser_stockage_durable()
    try:
        parametres = bac.ParametresBac(**{**PARAMETRES.__dict__, "autoriser_registre_durable": True})
        with stockage.transaction():
            rapport = bac.jouer(appel(
                T(5, "Bonjour, j'aimerais faire changer mes gouttières."), T(12, "À Laval."),
                T(18, "C'est au numéro 123 sur la rue des Érables."), T(25, "C'est une maison."),
                T(30, "Elle a deux étages.")), parametres)
        assert rapport.issue == bac.ISSUE_LEAD and rapport.tours_non_joues == 0
        assert rapport.lead["service"] == "gouttieres" and rapport.lead["ville"] == "Laval"
        assert rapport.lead["contact"] == {"telephone": "+15145550001"} and rapport.lead["source"] == bac.SOURCE_LEAD
        # les questions posées viennent du PROFIL adopté, dans l'ordre écrit ; les autres restent à obtenir
        assert rapport.contexte["questions_posees"] == ["adresse", "etages", "type_batiment"]
        assert rapport.contexte["questions_repondues"] == ["adresse", "type_batiment", "etages"]
        assert rapport.contexte["questions_restantes"] == [
            "probleme", "reparation_ou_neuf", "urgence", "delai", "acces_arbres", "couleur"]
        assert "à obtenir : probleme" in rapport.resume
        _avatar_est_sur(rapport)
        assert rapport.transfert is None and rapport.rappel_a_faire is False
        assert rapport.session["etat"] == "fin" and rapport.session["raison_fin"] == "cloture"
        # le lead part par le vrai bus vers le vrai M2
        deps = charger_departements()
        for tour in range(10):
            if evenements.repartir(deps, maintenant=f"2026-09-29T09:{tour + 1:02d}:00-04:00")["livres"] == 0:
                break
        with stockage.transaction():
            ingeres = [m for m in stockage.maillons("m02-revenue-crm", "principal")
                       if m.get("type_entree") == "lead_ingere"]
        assert [m["contrat"] for m in ingeres] == [rapport.lead]
    finally:
        m1.reinitialiser_registre()
        m2.reinitialiser_registre()


def test_un_appel_complet_pose_les_memes_questions_de_texte_que_le_sms_et_aucune_demande_de_photos(instance):
    rapport = bac.jouer(appel(
        T(5, "Bonjour, des gouttières à Laval."), T(10, "Au 12 rue des Pins."), T(15, "Une maison."),
        T(20, "Deux étages.")), PARAMETRES)
    assert all("photo" not in t.lower() for t in rapport.textes_avatar())  # une voix ne reçoit pas de photo
    assert rapport.contexte["questions_posees"] == ["adresse", "etages", "type_batiment"]


# ====================================================================== 2. appelant en colère
def test_appelant_en_colere_repli_plainte_transfert_avec_contexte_sans_aucune_promesse(instance):
    rapport = bac.jouer(appel(
        T(5, "Bonjour, des gouttières à Laval."),
        T(12, "Je suis très déçu, après vos travaux ça coule encore et personne ne me rappelle.", 0.9),
        T(20, "Allô?"), numero=2), PARAMETRES)
    assert rapport.issue == bac.ISSUE_TRANSFERT and rapport.motif == "plainte" and rapport.tours_non_joues == 1
    assert rapport.lead is None  # la plainte prime : jamais un lead
    t = rapport.transfert
    assert (t["type_transfert"], t["niveau"], t["destinataire"]) == ("plainte", "N4", "nathan_owner")
    assert {"insatisfaction", "degat"} <= set(t["categories"])
    assert t["resume"].strip() and t["contact_present"] is True and t["verdict_destinataire"] is None
    # la personne reçoit le contexte : le résumé du code, l'appel dans le registre, le rapport
    assert "plainte" in rapport.resume and "tâche humaine plainte" in rapport.resume
    (ouvert,) = [e for e in _transferts() if e.ouvert]
    assert ouvert.ouverture["transfert_id"] == t["transfert_id"] and ouvert.ouverture["contact"] == {
        "telephone": "+15145550002"}
    # l'avatar ne dit que le signalement : ni excuse, ni promesse, ni conseil
    derniere = rapport.textes_avatar()[-1]
    assert derniere == politique_dialogue.TEXTES["transfert"]
    for texte in rapport.textes_avatar():
        assert not any(m in texte.lower() for m in (*MOTS_DE_PROMESSE, *MOTS_DE_CONSEIL))
    _avatar_est_sur(rapport)
    assert rapport.session["etat"] == "fin" and rapport.session["raison_fin"] == "plainte"
    assert rapport.evenements_session[-2:] == ["transfert_humain", "terminer"]


def test_la_colere_a_faible_confiance_est_quand_meme_un_transfert_pas_une_demande_de_repeter(instance):
    """Mauvaise dimension à éviter : une transcription peu sûre ne range pas la colère parmi les simples échecs."""
    rapport = bac.jouer(appel(T(5, "Je suis très déçu", 0.2), numero=3), PARAMETRES)
    assert rapport.decisions[0]["action"] == "transferer" and rapport.decisions[0]["motif"] == "plainte"
    assert rapport.echecs_comprehension == 0 and rapport.transfert["type_transfert"] == "plainte"


def test_une_menace_juridique_est_un_transfert_n5_sans_brouillon_et_sans_avis(instance):
    rapport = bac.jouer(appel(T(5, "Mon avocat va vous envoyer une mise en demeure.", 0.85), numero=4), PARAMETRES)
    assert rapport.motif == "menace_juridique"
    assert rapport.transfert["niveau"] == "N5" and rapport.transfert["categories"] == ["avocat"]
    assert rapport.textes_avatar()[-1] == politique_dialogue.TEXTES["transfert"]
    _avatar_est_sur(rapport)


def test_sans_consentement_la_tache_de_plainte_s_ouvre_quand_meme_mais_sans_la_parole_de_l_appelant(instance):
    rapport = bac.jouer(appel(T(5, "Je suis très déçu de votre zèbre-rose-77."), numero=5, consentement=None),
                        PARAMETRES)
    assert rapport.transfert["type_transfert"] == "plainte" and rapport.transfert["resume"].strip()
    assert "zèbre-rose-77" not in _registre_en_texte()
    assert rapport.transfert["categories"] == ["insatisfaction"]


def test_sans_personne_disponible_la_plainte_devient_un_message_a_laisser_et_la_tache_s_ouvre(instance):
    rapport = bac.jouer(appel(
        T(5, "Je suis très déçu de vos travaux.", 0.9),
        T(15, "Rappelez-moi s'il vous plaît, c'est à propos de mes gouttières à Laval.", 0.9),
        numero=6, humain=False), PARAMETRES)
    assert rapport.issue == bac.ISSUE_MESSAGERIE and rapport.motif == "plainte"
    assert rapport.textes_avatar()[-1] == politique_dialogue.TEXTES["messagerie"]
    assert [p.nature for p in rapport.paroles if p.qui == "appelant"] == ["comprise", "message_laisse"]
    assert rapport.transfert["type_transfert"] == "plainte" and rapport.lead is None  # la plainte prime


# ====================================================================== 3. faible confiance répétée
def test_faible_confiance_repetee_redemande_puis_repli_vers_une_personne_sans_lead_invente(instance):
    rapport = bac.jouer(appel(
        T(5, "gouttières laval", 0.31), T(12, "zzz mes gouttières ksss", 0.44), T(20, "Allô?"), numero=7), PARAMETRES)
    assert [d["action"] for d in rapport.decisions] == ["redemander", "transferer"]
    assert [d["motif"] for d in rapport.decisions] == ["faible_confiance", "echecs_repetes"]
    assert [p.nature for p in rapport.paroles if p.qui == "appelant"] == ["faible_confiance", "faible_confiance"]
    assert rapport.textes_avatar()[-2:] == [politique_dialogue.TEXTES["redemander"],
                                            politique_dialogue.TEXTES["transfert"]]
    assert rapport.lead is None  # un texte peu sûr n'ouvre jamais de lead
    assert rapport.transfert["type_transfert"] == "ventes" and rapport.transfert["destinataire"] == "seller"
    assert "gouttières laval" not in _registre_en_texte() and "zzz" not in _registre_en_texte()
    assert rapport.tours_non_joues == 1 and rapport.echecs_comprehension == 2


def test_un_sujet_financier_a_faible_confiance_ouvre_la_tache_mais_le_texte_peu_sur_ne_fait_pas_de_lead(instance):
    rapport = bac.jouer(appel(T(5, "ma facture gouttières Laval", 0.3), numero=25), PARAMETRES)
    assert rapport.transfert["type_transfert"] == "finance" and rapport.lead is None
    assert "ma facture" not in _registre_en_texte()
    sur = bac.jouer(appel(T(5, "ma facture gouttières Laval", 0.9), numero=26), PARAMETRES)
    assert sur.transfert["type_transfert"] == "finance" and sur.lead is not None  # texte sûr : lead ET tâche


def test_un_echec_isole_ne_declenche_pas_le_repli_et_le_compte_repart_a_zero(instance):
    rapport = bac.jouer(appel(
        T(5, "gouttières", 0.3), T(12, "Bonjour, des gouttières à Laval."), T(20, "flou", 0.2),
        T(26, "Au 12 rue des Pins."), numero=8), PARAMETRES)
    assert [d["action"] for d in rapport.decisions] == ["redemander", "continuer", "redemander", "continuer"]
    assert rapport.issue == bac.ISSUE_LEAD and rapport.transfert is None


def test_faible_confiance_repetee_sans_personne_messagerie_intelligente_en_repli(instance):
    """La messagerie en repli reprend le chemin de la messagerie vocale : le message laissé est qualifié par les mêmes
    règles (ici service, ville et numéro de l'appelant font un lead), et une tâche humaine s'ouvre quand même."""
    rapport = bac.jouer(appel(
        T(5, "flou", 0.2), T(10, "flou encore", 0.3),
        T(20, "Bonjour, c'est pour mes gouttières à Laval, rappelez-moi.", 0.2),
        numero=9, humain=False), PARAMETRES)
    assert rapport.issue == bac.ISSUE_MESSAGERIE and rapport.motif == "echecs_repetes"
    assert rapport.textes_avatar()[-1] == politique_dialogue.TEXTES["messagerie"]
    assert rapport.lead is not None and rapport.lead["service"] == "gouttieres"
    assert rapport.transfert["type_transfert"] == "ventes"


def test_messagerie_sans_message_laisse_la_demande_n_est_pas_perdue(instance):
    rapport = bac.jouer(appel(T(5, "flou", 0.2), T(10, None), numero=10, humain=False), PARAMETRES)
    assert rapport.issue == bac.ISSUE_MESSAGERIE
    assert rapport.lead is None and rapport.transfert["type_transfert"] == "ventes"
    assert rapport.transfert["resume"].strip()


def test_le_silence_compte_comme_un_echec_de_comprehension(instance):
    rapport = bac.jouer(appel(T(5, None), T(12, None), numero=11), PARAMETRES)
    assert [d["motif"] for d in rapport.decisions] == ["silence", "echecs_repetes"]
    assert rapport.textes_avatar()[1] == politique_dialogue.TEXTES["silence"]
    assert rapport.transfert["type_transfert"] == "ventes"


# ====================================================================== 4. question de prix
def test_question_de_prix_reponse_sure_aucun_montant_et_l_appel_continue_jusqu_au_lead(instance):
    rapport = bac.jouer(appel(
        T(5, "Bonjour, ça coûte combien pour changer mes gouttières à Laval?"),
        T(15, "Au 12 rue des Pins."), T(22, "Une maison."), T(28, "Deux étages."), numero=12), PARAMETRES)
    assert rapport.decisions[0]["motif"] == "question_prix" and rapport.decisions[0]["action"] == "reponse_sure"
    assert rapport.textes_avatar()[1] == politique_dialogue.TEXTES["prix"]
    for texte in rapport.textes_avatar():
        assert "$" not in texte and "dollar" not in texte.lower()
    assert rapport.violations_garde_fou == []
    assert rapport.issue == bac.ISSUE_LEAD  # le service et la ville de la question comptent pour le lead
    _avatar_est_sur(rapport)


def test_un_repondant_qui_laisse_echapper_un_prix_apres_la_question_est_neutralise(instance):
    class Bavard:
        def __init__(self):
            self.n = 0

        def repondre(self, contexte):
            self.n += 1
            textes = ["Dans quelle ville? Ça coûte environ 4 500 $ en général.",
                      "Je vous garantis un début des travaux lundi le 5 octobre."]
            return bac.Reponse(textes[self.n - 1] if self.n <= 2 else "Merci.", fin=self.n > 2)

    rapport = bac.jouer(appel(T(5, "Bonjour, des gouttières."), T(12, "À Laval."), T(20, "Oui."), numero=13),
                        PARAMETRES, Bavard())
    assert len(rapport.violations_garde_fou) == 2
    assert {v["code"] for v in rapport.violations_garde_fou} <= {
        "REJ-INTERDIT-PRIX", "REJ-INTERDIT-DATE", "REJ-INTERDIT-ENGAGEMENT"}
    texte = " ".join(rapport.textes_avatar())
    assert "4 500" not in texte and "lundi" not in texte and "garantis" not in texte
    _avatar_est_sur(rapport)


def test_question_de_date_reponse_sure_aucune_date(instance):
    rapport = bac.jouer(appel(T(5, "Quand venez-vous faire la visite pour mes gouttières à Laval?"), numero=14),
                        PARAMETRES)
    assert rapport.decisions[0]["motif"] == "question_date"
    assert rapport.textes_avatar()[1] == politique_dialogue.TEXTES["date"]
    _avatar_est_sur(rapport)


# ====================================================================== 5. urgence de sécurité
def test_urgence_securite_escalade_immediate_sans_conseil_ni_promesse(instance):
    rapport = bac.jouer(appel(
        T(5, "Il y a de la fumée qui sort du mur et un fil électrique qui pend près de ma gouttière!", 0.82),
        T(9, "Allô? Vous êtes là?"), numero=15), PARAMETRES)
    assert rapport.issue == bac.ISSUE_TRANSFERT and rapport.motif == "urgence_securite"
    assert rapport.decisions == [{"t": 5, "action": "transferer", "motif": "urgence_securite",
                                  "type_transfert": "urgence", "categories": ["securite"], "echecs": 0}]
    assert rapport.tours_non_joues == 1  # l'avatar se tait : rien de plus n'est joué
    t = rapport.transfert
    assert (t["type_transfert"], t["niveau"], t["destinataire"]) == ("urgence", "N5", "nathan_owner")
    assert rapport.lead is None
    assert rapport.textes_avatar()[-1] == politique_dialogue.TEXTES["urgence"]
    for texte in rapport.textes_avatar():
        assert not any(m in texte.lower() for m in (*MOTS_DE_CONSEIL, *MOTS_DE_PROMESSE))
    _avatar_est_sur(rapport)
    assert rapport.session["raison_fin"] == "urgence_securite"


def test_urgence_a_faible_confiance_est_quand_meme_une_escalade_immediate(instance):
    rapport = bac.jouer(appel(T(5, "fumée... fil électrique", 0.1), numero=16), PARAMETRES)
    assert rapport.decisions[0]["motif"] == "urgence_securite" and rapport.echecs_comprehension == 0
    assert rapport.transfert["type_transfert"] == "urgence"


def test_urgence_sans_personne_disponible_n_attend_pas_un_message(instance):
    rapport = bac.jouer(appel(T(5, "Il y a un incendie!", 0.7), numero=17, humain=False), PARAMETRES)
    assert rapport.issue == bac.ISSUE_TRANSFERT and rapport.motif == "urgence_securite"
    assert rapport.textes_avatar()[-1] == politique_dialogue.TEXTES["urgence"]
    assert rapport.transfert["niveau"] == "N5"


def test_urgence_qui_interrompt_la_divulgation_est_signalee_apres_la_divulgation_refaite(instance):
    rapport = bac.jouer(appel(T(1, "Du danger! Un fil électrique!", 0.9, interrompt=True), numero=18), PARAMETRES)
    assert [p.nature for p in rapport.paroles if p.qui == "avatar"] == ["divulgation", "divulgation", "politique"]
    assert rapport.motif == "urgence_securite" and rapport.transfert["niveau"] == "N5"


# ====================================================================== autres sujets qui exigent une personne
@pytest.mark.parametrize(("texte", "motif", "type_transfert"), [
    ("J'ai une question sur ma facture.", "sujet_financier", "finance"),
    ("Je voudrais relire mon contrat, c'est légal?", "sujet_legal", "proprietaire"),
    ("Je veux parler à une personne, s'il vous plaît.", "demande_humain", "ventes"),
])
def test_sujets_legal_financier_ou_demande_d_une_personne_transfert_du_bon_type(
        instance, texte, motif, type_transfert):
    rapport = bac.jouer(appel(T(5, texte, 0.9), numero=20), PARAMETRES)
    assert rapport.issue == bac.ISSUE_TRANSFERT and rapport.motif == motif
    assert rapport.transfert["type_transfert"] == type_transfert and rapport.transfert["resume"].strip()
    _avatar_est_sur(rapport)


# ====================================================================== sans adoption du pack : la limite, dite
def test_sans_vocabulaire_adopte_ni_colere_ni_danger_ne_sont_reconnus_precondition_de_tout_appel_reel(
        tmp_path, monkeypatch, declarer_services):
    """Le profil n'a pas adopté le pack : comme pour un message écrit, M1 ne devine aucun mot. Le même appel en colère,
    ou avec un danger, est traité comme une demande ordinaire. Avant tout appel réel, le vocabulaire doit être
    adopté."""
    url = f"sqlite:///{tmp_path / 'sans.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    declarer_services()
    taxonomie.enregistrer_zone_desservie(["Laval"])
    m1.reinitialiser_registre()
    try:
        colere = bac.jouer(appel(T(5, "Je suis très déçu, après vos travaux ça coule.", 0.9), numero=21), PARAMETRES)
        danger = bac.jouer(appel(T(5, "Il y a de la fumée et un fil électrique!", 0.9), numero=22), PARAMETRES)
        assert colere.decisions[0]["action"] == danger.decisions[0]["action"] == "continuer"
        assert colere.transfert is None or colere.transfert["type_transfert"] == "ventes"
        assert danger.transfert is None or danger.transfert["type_transfert"] == "ventes"
        # ce qui tient sans vocabulaire : une demande de personne, un échec répété, le garde-fou
        humain = bac.jouer(appel(T(5, "Je veux parler à une personne", 0.9), numero=23), PARAMETRES)
        assert humain.motif == "demande_humain"
    finally:
        m1.reinitialiser_registre()
        stockage.liberer()


def test_un_appel_ne_cree_jamais_de_demande_d_envoi_ni_de_message_au_client(instance):
    rapport = bac.jouer(appel(T(5, "Je suis très déçu", 0.9), numero=24), PARAMETRES)
    lignes = list(m1._obtenir_registre().lire())
    assert not any("approbation" in json.dumps(ligne) or ligne.get("type_entree") == "notification"
                   for ligne in lignes)
    assert rapport.session["actions"] == []
