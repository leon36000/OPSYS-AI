"""Qualification par conversation (PLAN T2.1-b, `docs/departements/M1-canaux.md` §6) : le service dans un message et la
ville dans le suivant se rejoignent, par du code, dans une fenêtre que le profil d'entreprise déclare.

Registre en mémoire (voir `tests/test_canal_conversation.py` pour la base réelle, `Capacites`, le bus et M2). Le profil
de l'instance de test déclare les services du catalogue et la zone ; la fenêtre n'est déclarée que par les tests qui en
ont besoin, parce que son absence est un cas à prouver. Numéros en 555, messages fictifs.
"""

from __future__ import annotations

import datetime as dt
import hashlib

import pytest
from m1_front_office import conversation, garde_fou, qualification
from m1_front_office.outils import _obtenir_registre, recevoir_message_canal, reinitialiser_registre
from m1_front_office.reception import identifiant_de_conversation

from opsys import taxonomie

NUMERO = "+15145550142"
AUTRE_NUMERO = "+15145550143"
CONVERSATION = identifiant_de_conversation("sms", NUMERO)
DEBUT = dt.datetime(2026, 9, 29, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=-4)))


def _a(minutes: float) -> str:
    return (DEBUT + dt.timedelta(minutes=minutes)).isoformat()


@pytest.fixture(autouse=True)
def _instance(declarer_services):
    declarer_services()
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    reinitialiser_registre()
    yield
    reinitialiser_registre()


def _fenetre(minutes: int = 30) -> None:
    taxonomie.enregistrer_fenetre_conversation(minutes)


def _recevoir(texte: str, message_id: str, minutes: float = 0, expediteur: str = NUMERO):
    return recevoir_message_canal(
        canal="sms", expediteur=expediteur, message_id=message_id, recu_le=_a(minutes), texte=texte)


def _lignes(type_entree: str | None = None) -> list[dict]:
    lignes = _obtenir_registre().lire()
    return lignes if type_entree is None else [ligne for ligne in lignes if ligne["type_entree"] == type_entree]


# -- Le cas de la tranche : le service dans un message, la ville dans le suivant ---------------------------------------


def test_le_service_puis_la_ville_dans_deux_messages_donnent_un_seul_lead():
    _fenetre()
    premier = _recevoir("Bonjour, mes gouttières fuient.", "SM-1", 0)
    assert premier["qualifie"] is False and premier["decision"] == "DEMANDER_PRECISIONS"
    assert _lignes("lead_emis") == []

    second = _recevoir("Je suis à Laval.", "SM-2", 4)
    assert second["qualifie"] is True and second["decision"] == "TRANSMETTRE_M2"
    lead = second["lead"]
    assert (lead["service"], lead["ville"], lead["source"], lead["canal"]) == ("gouttieres", "Laval", "sms", "texte")
    assert lead["contact"] == {"telephone": NUMERO} and lead["conversation_id"] == CONVERSATION
    assert second["conversation"]["messages"] == 2
    assert second["conversation"]["signaux"] == ["sms:SM-1", "sms:SM-2"]

    (ligne_lead,) = _lignes("lead_emis")
    assert ligne_lead["signal_id"] == "sms:SM-2" and ligne_lead["signaux_rassembles"] == ["sms:SM-1", "sms:SM-2"]
    assert [ligne["signal_id"] for ligne in _lignes("signal")] == ["sms:SM-1", "sms:SM-2"], "une ligne par message"
    assert _obtenir_registre().valider_chaine() == (True, None)


def test_la_ville_puis_le_service_donnent_aussi_un_lead_et_l_urgence_d_un_message_compte():
    _fenetre()
    _recevoir("Nous sommes à Québec.", "SM-1", 0)
    second = _recevoir("Le soffite est arraché, c'est urgent.", "SM-2", 2)
    assert second["qualifie"] is True
    assert (second["lead"]["service"], second["lead"]["ville"], second["lead"]["urgence_declaree"]) == (
        "soffite_fascia", "Québec", True)


def test_trois_messages_service_bruit_puis_ville_donnent_un_lead_qui_compte_les_trois_signaux():
    _fenetre()
    _recevoir("Bonjour", "SM-1", 0)
    _recevoir("Les gouttières sont bouchées", "SM-2", 1)
    reponse = _recevoir("À Laval", "SM-3", 2)
    assert reponse["qualifie"] is True and reponse["conversation"]["messages"] == 3
    assert len(_lignes("signal")) == 3 and len(_lignes("lead_emis")) == 1


def test_un_message_qui_manque_de_ville_dit_ce_qui_est_connu_ce_qui_manque_et_propose_un_brouillon_non_envoye():
    _fenetre()
    reponse = _recevoir("Bonjour, mes gouttières fuient.", "SM-1", 0)
    assert reponse["conversation"]["connu"] == {
        "service": "gouttieres", "ville": None, "contact": "canal", "urgence_declaree": False}
    assert reponse["a_demander"] == ["ville"]
    assert reponse["brouillon_reponse"] == "Bonjour, merci de votre message. Dans quelle ville se trouve la propriété?"
    assert reponse["envoye"] is False
    assert reponse["conversation"]["fenetre_minutes"] == 30
    assert reponse["conversation"]["ouverte_le"] == _a(0) and reponse["conversation"]["expire_le"] == _a(30)


@pytest.mark.parametrize(("texte", "manque", "extrait"), [
    ("Bonjour.", ["service", "ville"], "Quel service vous intéresse (Gouttières et descentes, Revêtement extérieur, "
                                        "Soffite et fascia ou Réparation), et dans quelle ville"),
    ("Je suis à Laval.", ["service"], "Quel service vous intéresse ("),
    ("Gouttières et soffite à Laval.", ["service"], "Vous parlez de plusieurs services : Gouttières et descentes, "
                                                    "Soffite et fascia. Par lequel souhaitez-vous commencer?"),
])
def test_le_brouillon_suit_ce_qui_manque_et_passe_le_garde_fou(texte, manque, extrait):
    _fenetre()
    reponse = _recevoir(texte, "SM-1", 0)
    assert reponse["a_demander"] == manque
    assert extrait in reponse["brouillon_reponse"]
    assert garde_fou.verifier_sortie(reponse["brouillon_reponse"])["code"] == "OK"


def test_un_libelle_de_service_qui_glisse_un_prix_dans_le_brouillon_le_fait_retirer_par_le_garde_fou():
    taxonomie.enregistrer_services([{"code": "pose", "libelle": "Pose à 500 $", "mots_cles": ["pose"]}])
    _fenetre()
    reponse = _recevoir("Bonjour.", "SM-1", 0)
    assert reponse["a_demander"] == ["service", "ville"]
    assert reponse["brouillon_reponse"] is None and reponse["sans_brouillon"] == "REJ-INTERDIT-PRIX"


def test_aucun_message_n_est_emis_ni_propose_a_l_envoi_par_la_reception(monkeypatch):
    import m1_front_office.outils as outils_m1

    class BusEspion:
        def emettre(self, canal, message):
            raise AssertionError("la réception ne doit rien envoyer")

    monkeypatch.setattr(outils_m1.adaptateurs, "creer_bus", lambda mode_ombre=True: BusEspion())
    _fenetre()
    reponse = _recevoir("Bonjour.", "SM-1", 0)
    assert reponse["envoye"] is False and reponse["brouillon_reponse"]


# -- Un message rejoué ne compte pas deux fois -------------------------------------------------------------------------


def test_un_message_rejoue_ne_compte_pas_deux_fois_et_ne_cree_pas_de_lead():
    _fenetre()
    _recevoir("Bonjour, mes gouttières fuient.", "SM-1", 0)
    taille = _obtenir_registre().taille()
    rejoue = _recevoir("Bonjour, mes gouttières fuient.", "SM-1", 0)
    assert rejoue["doublon"] is True and rejoue["qualifie"] is False and rejoue["decision"] == "DEMANDER_PRECISIONS"
    assert _obtenir_registre().taille() == taille

    _recevoir("Bonjour, mes gouttières fuient.", "SM-1", 0)
    lead = _recevoir("À Laval.", "SM-2", 3)
    assert lead["qualifie"] is True and lead["conversation"]["messages"] == 2, "SM-1 n'est compté qu'une fois"
    assert len(_lignes("signal")) == 2


def test_le_message_qui_a_qualifie_rejoue_rend_le_meme_lead_sans_seconde_ligne():
    _fenetre()
    _recevoir("Mes gouttières fuient.", "SM-1", 0)
    premier = _recevoir("À Laval.", "SM-2", 3)
    taille = _obtenir_registre().taille()
    rejoue = _recevoir("À Laval.", "SM-2", 3)
    assert rejoue["doublon"] is True and rejoue["decision"] == "TRANSMETTRE_M2"
    assert rejoue["lead"] == premier["lead"] and rejoue["lead_ligne_id"] == premier["lead_ligne_id"]
    assert _obtenir_registre().taille() == taille and len(_lignes("lead_emis")) == 1


# -- Un seul lead par conversation ouverte -----------------------------------------------------------------------------


def test_un_message_apres_le_lead_dans_la_meme_fenetre_s_y_rattache_sans_second_lead():
    _fenetre()
    _recevoir("Mes gouttières fuient.", "SM-1", 0)
    lead = _recevoir("À Laval.", "SM-2", 3)["lead"]

    merci = _recevoir("Merci beaucoup!", "SM-3", 5)
    assert merci["decision"] == "CONVERSATION_DEJA_QUALIFIEE" and merci["nouveau_lead"] is False
    assert merci["lead"] == lead and "brouillon_reponse" not in merci, "rien à demander : le lead est complet"
    assert merci["complement"] == {"urgence_declaree": False, "services_evoques": [], "autre_service_evoque": False}
    assert len(_lignes("lead_emis")) == 1 and len(_lignes("signal")) == 3
    (signal_merci,) = [ligne for ligne in _lignes("signal") if ligne["signal_id"] == "sms:SM-3"]
    assert signal_merci["rattache_au_lead"] == lead["lead_id"]

    # Rejoué, il rend la même décision, sans seconde ligne.
    taille = _obtenir_registre().taille()
    rejoue = _recevoir("Merci beaucoup!", "SM-3", 5)
    assert rejoue["doublon"] is True and rejoue["decision"] == "CONVERSATION_DEJA_QUALIFIEE"
    assert rejoue["lead"] == lead and _obtenir_registre().taille() == taille


def test_ce_que_le_lead_transmis_ne_porte_pas_est_dit_dans_la_reponse_du_complement():
    _fenetre()
    _recevoir("Mes gouttières fuient à Laval.", "SM-1", 0)
    complement = _recevoir("Aussi le soffite, c'est urgent!", "SM-2", 2)
    assert complement["decision"] == "CONVERSATION_DEJA_QUALIFIEE"
    assert complement["complement"] == {
        "urgence_declaree": True, "services_evoques": ["soffite_fascia"], "autre_service_evoque": True}
    assert "dis-le à une personne" in complement["consigne"]
    assert len(_lignes("lead_emis")) == 1


def test_la_conversation_suivante_apres_la_fenetre_peut_donner_un_second_lead_meme_a_texte_identique():
    _fenetre(30)
    premier = _recevoir("Gouttières à Laval.", "SM-1", 0)["lead"]
    dans_la_fenetre = _recevoir("Gouttières à Laval.", "SM-2", 10)
    assert dans_la_fenetre["decision"] == "CONVERSATION_DEJA_QUALIFIEE"

    apres = _recevoir("Gouttières à Laval.", "SM-3", 90)
    assert apres["qualifie"] is True and apres["decision"] == "TRANSMETTRE_M2"
    assert apres["lead"]["lead_id"] != premier["lead_id"], "deux demandes de même texte ne sont pas le même lead"
    assert len(_lignes("lead_emis")) == 2


def test_deux_clients_n_ont_jamais_la_meme_conversation():
    _fenetre()
    _recevoir("Mes gouttières fuient.", "SM-1", 0, expediteur=NUMERO)
    autre = _recevoir("À Laval.", "SM-2", 1, expediteur=AUTRE_NUMERO)
    assert autre["qualifie"] is False and autre["a_demander"] == ["service"], "la ville de l'un ne complète pas l'autre"
    assert _lignes("lead_emis") == []


# -- La fenêtre est bornée ---------------------------------------------------------------------------------------------


def test_une_fenetre_expiree_ne_rassemble_plus_et_le_dit():
    _fenetre(30)
    _recevoir("Mes gouttières fuient.", "SM-1", 0)
    tard = _recevoir("À Laval.", "SM-2", 90)
    assert tard["qualifie"] is False and tard["a_demander"] == ["service"]
    assert tard["conversation"]["hors_fenetre"] == 1, "le message d'avant reste au registre, hors de cette conversation"
    assert tard["conversation"]["messages"] == 1 and tard["conversation"]["ouverte_le"] == _a(90)
    assert _lignes("lead_emis") == [] and len(_lignes("signal")) == 2, "rien n'est perdu, rien n'est qualifié"


def test_la_borne_de_la_fenetre_est_incluse_et_une_minute_de_plus_ferme_la_conversation():
    _fenetre(30)
    _recevoir("Mes gouttières fuient.", "SM-1", 0)
    assert _recevoir("À Laval.", "SM-2", 30)["qualifie"] is True

    reinitialiser_registre()
    _recevoir("Mes gouttières fuient.", "SM-1", 0)
    assert _recevoir("À Laval.", "SM-2", 31)["qualifie"] is False


def test_la_fenetre_se_lit_dans_le_profil_a_chaque_message_et_une_autre_duree_change_le_regroupement():
    _fenetre(10)
    _recevoir("Mes gouttières fuient.", "SM-1", 0)
    assert _recevoir("À Laval.", "SM-2", 20)["qualifie"] is False
    _fenetre(60)
    reinitialiser_registre()
    _recevoir("Mes gouttières fuient.", "SM-1", 0)
    assert _recevoir("À Laval.", "SM-2", 20)["qualifie"] is True


def test_l_heure_de_reception_fait_foi_meme_quand_un_message_arrive_hors_d_ordre():
    _fenetre(30)
    _recevoir("À Laval.", "SM-2", 20)  # livré le premier, envoyé après
    reponse = _recevoir("Mes gouttières fuient.", "SM-1", 5)
    assert reponse["qualifie"] is True and reponse["conversation"]["messages"] == 2


# -- Sans fenêtre déclarée : le comportement d'avant, et le verdict le dit ---------------------------------------------


def test_sans_fenetre_declaree_la_qualification_reste_message_par_message_et_le_verdict_le_dit():
    premier = _recevoir("Mes gouttières fuient.", "SM-1", 0)
    second = _recevoir("À Laval.", "SM-2", 1)
    assert premier["qualifie"] is False and second["qualifie"] is False, "le service et la ville ne se rejoignent pas"
    assert _lignes("lead_emis") == []
    for reponse in (premier, second):
        assert reponse["conversation"]["mode"] == "message_par_message"
        verdict = reponse["conversation"]["verdict"]
        assert verdict["code"] == "REJ-FENETRE-NON-CONFIGUREE"
        assert "fenetre_conversation_minutes" in verdict["detail"]
        assert str(taxonomie.fichier_profil()) in verdict["detail"]
        assert "brouillon_reponse" not in reponse and "a_demander" not in reponse


def test_sans_fenetre_un_message_complet_se_qualifie_seul_comme_avant_et_porte_le_verdict():
    reponse = _recevoir("Mes gouttières fuient à Laval.", "SM-1", 0)
    assert reponse["decision"] == "TRANSMETTRE_M2" and reponse["conversation"]["mode"] == "message_par_message"
    (ligne_lead,) = _lignes("lead_emis")
    assert "signaux_rassembles" not in ligne_lead
    assert "rattache_au_lead" not in _lignes("signal")[0]


def test_sans_fenetre_le_lead_id_est_celui_d_avant_octet_pour_octet():
    """Le matériau du `lead_id` n'a pas changé : les leads déjà émis gardent leur identité."""
    texte = "Mes gouttières fuient à Laval."
    reponse = _recevoir(texte, "SM-1", 0)
    ancien_materiau = f"{len(CONVERSATION)}:{CONVERSATION}|{len(texte)}:{texte}"
    assert reponse["lead"]["lead_id"] == hashlib.sha256(ancien_materiau.encode("utf-8")).hexdigest()


def test_l_identite_du_lead_de_conversation_distingue_deux_demandes_de_meme_texte():
    services, _ = taxonomie.charger_services()
    zone = ["Laval"]
    sans = qualification.qualifier("Gouttières à Laval.", "texte", CONVERSATION, zone, services=services,
                                   contact_canal={"telephone": NUMERO})
    avec_a = qualification.qualifier("Gouttières à Laval.", "texte", CONVERSATION, zone, services=services,
                                     contact_canal={"telephone": NUMERO}, identite_lead="sms:SM-1")
    avec_b = qualification.qualifier("Gouttières à Laval.", "texte", CONVERSATION, zone, services=services,
                                     contact_canal={"telephone": NUMERO}, identite_lead="sms:SM-2")
    assert len({sans["lead_id"], avec_a["lead_id"], avec_b["lead_id"]}) == 3


def test_le_diagnostic_dit_ce_qui_est_connu_avec_les_memes_regles_que_la_qualification():
    services, _ = taxonomie.charger_services()
    zone = ["Laval", "Québec"]
    assert qualification.diagnostiquer("Gouttières à Laval, urgent.", zone, services) == {
        "services_evoques": ["gouttieres"], "service": "gouttieres", "ville": "Laval", "contact": None,
        "urgence_declaree": True}
    assert qualification.diagnostiquer("Gouttières et soffite.", zone, services) == {
        "services_evoques": ["gouttieres", "soffite_fascia"], "service": None, "ville": None, "contact": None,
        "urgence_declaree": False}
    assert qualification.diagnostiquer("Bonjour à Rimouski.", zone, services)["ville"] is None
    with pytest.raises(ValueError, match="zone_desservie requise"):
        qualification.diagnostiquer("Gouttières", [], services)


@pytest.mark.parametrize("valeur", ["0", "-5", "30.5", "'30'", "true", "10081", "[30]"])
def test_une_fenetre_declaree_mais_invalide_est_refusee_avant_toute_ecriture_jamais_lue_comme_absente(valeur):
    fichier = taxonomie.fichier_profil()
    fichier.write_text(fichier.read_text(encoding="utf-8") + f"fenetre_conversation_minutes: {valeur}\n",
                       encoding="utf-8")
    with pytest.raises(ValueError, match="REJ-PROFIL-INVALIDE") as exc:
        _recevoir("Mes gouttières fuient à Laval.", "SM-1", 0)
    assert "fenetre_conversation_minutes" in str(exc.value)
    assert _lignes() == []


# -- Un retrait ferme la conversation ----------------------------------------------------------------------------------


def test_stop_au_milieu_d_une_conversation_ferme_la_conversation_et_rien_n_est_jamais_qualifie():
    _fenetre()
    _recevoir("Mes gouttières fuient.", "SM-1", 0)
    stop = _recevoir("STOP", "SM-STOP", 2)
    assert stop["decision"] == "RETRAIT_CONSENTEMENT" and stop["qualifie"] is False
    assert stop["conversation"] == {
        "mode": "fenetre", "fenetre_minutes": 30, "fermee_par_retrait": True, "messages_non_qualifies": 1}

    apres = _recevoir("À Laval.", "SM-2", 4)
    assert apres["qualifie"] is False, "ce qui a été écrit avant STOP ne se joint pas à ce qui suit"
    assert apres["conversation"]["messages"] == 1 and apres["a_demander"] == ["service"]
    assert apres["brouillon_reponse"] is None and apres["sans_brouillon"] == "retrait_consentement"
    assert _lignes("lead_emis") == []
    assert [a["marqueur"] for a in _lignes("alerte")] == ["retrait_consentement"]


def test_stop_apres_le_lead_ne_laisse_aucun_message_sans_lead():
    _fenetre()
    _recevoir("Mes gouttières fuient à Laval.", "SM-1", 0)
    stop = _recevoir("Arrêt", "SM-STOP", 2)
    assert stop["conversation"]["messages_non_qualifies"] == 0
    assert len(_lignes("lead_emis")) == 1


def test_une_demande_complete_apres_un_retrait_reste_qualifiee_mais_sans_brouillon():
    _fenetre()
    _recevoir("STOP", "SM-STOP", 0)
    reponse = _recevoir("Bonjour, gouttières à Laval, pouvez-vous me rappeler?", "SM-2", 5)
    assert reponse["decision"] == "TRANSMETTRE_M2", "STOP retire le consentement aux messages, pas le droit d'écrire"


def test_un_stop_rejoue_ne_ferme_pas_deux_fois_ni_n_ajoute_de_ligne():
    _fenetre()
    _recevoir("Mes gouttières fuient.", "SM-1", 0)
    _recevoir("STOP", "SM-STOP", 2)
    taille = _obtenir_registre().taille()
    rejoue = _recevoir("STOP", "SM-STOP", 2)
    assert rejoue["doublon"] is True and rejoue["decision"] == "RETRAIT_CONSENTEMENT"
    assert _obtenir_registre().taille() == taille


# -- Le module pur : la conversation ouverte se relit du registre ----------------------------------------------------


def _signal(signal_id: str, minutes: float, texte: str = "x", conv: str = "c1") -> dict:
    return {"type_entree": "signal", "conversation_id": conv, "signal_id": signal_id, "horodatage": _a(minutes),
            "contenu_filtre": texte}


def test_lire_ignore_les_autres_conversations_et_rend_l_etat_avant_le_message_courant():
    lignes = [
        _signal("a", 0, "gouttières", "c1"), _signal("z", 1, "Laval", "c2"), _signal("b", 5, "encore", "c1"),
    ]
    etat = conversation.lire(lignes, "c1", _a(6), 30)
    assert [m["signal_id"] for m in etat.messages] == ["a", "b"]
    assert etat.lead is None and etat.retire is False and etat.hors_fenetre == 0
    assert etat.ouverture == _a(0)
    assert conversation.contenu_rassemble(etat, "à Laval") == "gouttières\nencore\nà Laval"
    assert conversation.signaux_rassembles(etat, "c") == ["a", "b", "c"]


def test_lire_ferme_par_la_fenetre_ou_le_retrait_et_compte_ce_qui_reste_sans_lead():
    lignes = [_signal("a", 0), _signal("b", 10), _signal("c", 100)]
    etat = conversation.lire(lignes, "c1", _a(105), 30)
    assert [m["signal_id"] for m in etat.messages] == ["c"] and etat.ouverture == _a(100)

    expire = conversation.lire(lignes, "c1", _a(200), 30)
    assert expire.messages == () and expire.hors_fenetre == 1 and expire.ouverture is None

    retire = conversation.lire(
        [*lignes, {"type_entree": "alerte", "marqueur": "retrait_consentement", "conversation_id": "c1"}],
        "c1", _a(101), 30)
    assert retire.messages == () and retire.retire is True and retire.hors_fenetre == 0


def test_lire_une_conversation_deja_qualifiee_ne_compte_pas_hors_fenetre():
    lignes = [_signal("a", 0), {"type_entree": "lead_emis", "conversation_id": "c1", "signal_id": "a",
                                "lead": {"lead_id": "L"}}]
    dans = conversation.lire(lignes, "c1", _a(10), 30)
    assert dans.lead is not None and dans.lead["lead"]["lead_id"] == "L"
    apres = conversation.lire(lignes, "c1", _a(500), 30)
    assert apres.lead is None and apres.hors_fenetre == 0 and apres.messages == ()
