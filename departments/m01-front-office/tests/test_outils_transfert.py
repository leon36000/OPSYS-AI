"""`m1_transferer`, `m1_escalader_plainte`, `m1_lire_transfert`, `m1_clore_transfert` et la file « À voir » (PLAN T4.5).

Ces tests passent par le VRAI point d'entrée des outils (`Capacites.appeler`), le VRAI manifeste de M1 (mode
`ombre`), la file d'approbation réelle (`approbations.decider`), l'identité d'appareil posée comme le fait le
serveur MCP (`contexte.appele_par_appareil`) et une base SQLite migrée. Ils prouvent trois choses :

- transférer ne demande aucune approbation (N2 : une tâche interne, jamais refusée faute d'affaire liée) et n'écrit rien
  au client ;
- clore un transfert est une décision HUMAINE : refusée à un agent seul, même dans un mode où un N3 s'exécute
  sans file ;
- l'attente naît à l'ouverture et disparaît à la clôture : sans l'outil, la file ne se viderait jamais.

Données fictives (numéros en 555, personnes de test, vocabulaire `fictif: true`).
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import json
from pathlib import Path

import pytest
from m1_front_office import outils as outils_m1
from m1_front_office import plaintes, transferts
from sqlalchemy import update

from opsys import approbations, contexte, idempotence, identite, openclaw, stockage, taxonomie
from opsys.capacites import Capacites, outils_executables
from opsys.departements import PolitiqueApprobation, lire_manifeste
from opsys.outils import Niveau, executer_atomique
from opsys.stockage.schema import APPROBATIONS, EVENEMENTS_SORTANTS

M1 = Path(__file__).resolve().parents[1]
NUMERO = "+15145550142"
AUTRE = "+15145550143"
DEBUT = dt.datetime(2031, 1, 15, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=-5)))
ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
EMPLOYE = contexte.IdentiteAppelante(personne="employe.fictif", role="employee")
MOTIF = "Client rappelé, la fenêtre est réparée et il est satisfait."
HORLOGE_APPAREIL_DEREGLEE = "2000-01-01T00:00:00+00:00"
HORODATAGE = "2031-01-15T12:00:00-05:00"


def _a(minutes: float) -> str:
    return (DEBUT + dt.timedelta(minutes=minutes)).isoformat()


@pytest.fixture
def instance(tmp_path, monkeypatch, declarer_services, declarer_plaintes):
    """Base migrée, profil d'entreprise (services, zone, vocabulaire des plaintes), registre durable de M1, trois
    personnes de test : le propriétaire, un admin et un employé."""
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    declarer_services()
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    declarer_plaintes()
    outils_m1.utiliser_stockage_durable()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "nathan", "Nathan Fictif", "mot-de-passe-nathan-12345", ["nathan_owner"])
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "employe.fictif", "Employé Fictif", "mot-de-passe-employe-1234", ["employee"])
    yield
    outils_m1.reinitialiser_registre()
    stockage.liberer()


@pytest.fixture
def dep(instance):
    return lire_manifeste(M1)


@pytest.fixture
def capacites(dep):
    return Capacites({dep.id: dep}, stockage.transaction, memoire=False)


def _lignes(type_entree=None):
    with stockage.transaction():
        lignes = outils_m1._obtenir_registre().lire()
    return lignes if type_entree is None else [ligne for ligne in lignes if ligne["type_entree"] == type_entree]


def _en_attente():
    with stockage.transaction() as cnx:
        return approbations.lister(cnx, "en_attente")


def _sms(capacites, texte, message_id="SM-1", minutes=0.0, expediteur=NUMERO):
    reponse = capacites.appeler("m1_recevoir_message_canal", {
        "canal": "sms", "expediteur": expediteur, "message_id": message_id, "recu_le": _a(minutes), "texte": texte})
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def _transferer(capacites, type_transfert="ventes", expediteur=NUMERO, **plus):
    return capacites.appeler(
        "m1_transferer", {"type_transfert": type_transfert, "canal": "sms", "expediteur": expediteur, **plus})


def _escalader(capacites, raison="autre", expediteur=NUMERO, **plus):
    return capacites.appeler(
        "m1_escalader_plainte", {"raison": raison, "canal": "sms", "expediteur": expediteur, **plus})


def _attentes():
    with stockage.transaction():
        return outils_m1.attentes()


def _ok(reponse):
    """La charge utile d'un outil qui a réussi : aucune mise en attente, `accepte` vrai."""
    assert reponse["ok"] is True and "statut" not in reponse, reponse
    assert reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _args_cloture(transfert_id, motif=MOTIF, horodatage=HORODATAGE):
    return {"transfert_id": transfert_id, "motif": motif, "horodatage": horodatage}


def _meta(cle="mut-1") -> idempotence.Meta:
    return idempotence.Meta(cle=cle, appareil="tel-admin-fictif-1", horodatage_appareil=HORLOGE_APPAREIL_DEREGLEE)


def _appareil(capacites, nom, arguments, identite_appelante, cle="mut-1"):
    with contexte.appele_par_appareil(identite_appelante):
        return capacites.appeler(nom, arguments, _meta(cle))


def _approuver(capacites, demande_id, par="nathan"):
    with stockage.transaction() as cnx:
        return approbations.decider(
            cnx, demande_id, True, par, outils_executables(capacites.departements, stockage.transaction),
            capacites.departements)


def _fermer_mode(dep, mode):
    with stockage.transaction() as cnx:
        approbations.fixer_mode(cnx, dep.id, mode, "nathan")


def _cloture_de(transfert_id):
    return [
        ligne for ligne in _lignes("transfert")
        if ligne["evenement"] == "clos" and ligne["transfert_id"] == transfert_id
    ]


# -- Transférer : une tâche interne (N2), un résumé obligatoire, rien d'écrit au client ---


NIVEAU_PAR_TYPE = {
    "ventes": "N3", "estimation": "N3", "admin": "N3", "finance": "N3", "technique": "N3",
    "plainte": "N4", "proprietaire": "N4", "urgence": "N5",
}


@pytest.mark.parametrize("type_transfert", transferts.TYPES)
def test_transferer_chaque_type_ouvre_un_transfert_et_une_attente_sans_aucune_approbation(capacites, type_transfert):
    _sms(capacites, "Bonjour, pouvez-vous me rappeler au sujet de ma demande?")
    reponse = _transferer(capacites, type_transfert)

    assert reponse["ok"] is True and "statut" not in reponse, "N2 : aucune mise en attente d'approbation"
    resultat = _ok(reponse)
    assert resultat["deja_ouvert"] is False and resultat["resume_origine"] == "code"
    assert resultat["transfert"]["type_transfert"] == type_transfert
    assert resultat["transfert"]["niveau"] == NIVEAU_PAR_TYPE[type_transfert]
    assert resultat["transfert"]["destinataire"] is None
    assert resultat["transfert"]["verdict_destinataire"]["code"] == taxonomie.VERDICT_DESTINATAIRE_NON_CONFIGURE
    assert resultat["envoye"] is False, "un transfert n'écrit jamais au client"
    assert _en_attente() == []
    (attente,) = _attentes()
    assert attente["id"] == resultat["transfert"]["transfert_id"]
    assert attente["niveau"] == NIVEAU_PAR_TYPE[type_transfert]
    (ligne,) = _lignes("transfert")
    assert ligne["type_transfert"] == type_transfert and ligne["declenche_par"] == "agent"
    assert ligne["resume"].strip() != "" and ligne["contact"] == {"telephone": NUMERO}
    with stockage.transaction():
        assert outils_m1._obtenir_registre().valider_chaine() == (True, None)


def test_transferer_ne_produit_aucun_message_au_client_ni_aucun_lead_ni_aucun_evenement(capacites, monkeypatch):
    monkeypatch.setattr(outils_m1.adaptateurs, "creer_bus", lambda mode_ombre=True: pytest.fail("aucun envoi"))
    _sms(capacites, "Où en est ma facture?")
    avant = len(_lignes("lead_emis"))
    _transferer(capacites, "finance")
    _escalader(capacites, "insatisfaction", expediteur=NUMERO)
    assert len(_lignes("lead_emis")) == avant
    with stockage.transaction() as cnx:
        publies = cnx.execute(EVENEMENTS_SORTANTS.select()).all()
    assert all(ligne.type_evenement == "m1.lead_qualifie" for ligne in publies), "seul un lead publie au bus"


def test_transferer_reste_automatique_en_supervise_et_en_ombre(capacites, dep):
    _sms(capacites, "Où en est ma facture?")
    for mode, message in (("ombre", "SM-A"), ("supervise", "SM-B")):
        _fermer_mode(dep, mode)
        expediteur = "+15145550190" if mode == "ombre" else "+15145550191"
        _sms(capacites, "Où en est ma facture?", message, expediteur=expediteur)
        reponse = _transferer(capacites, "finance", expediteur=expediteur)
        assert reponse["ok"] is True and "statut" not in reponse
    assert len(_attentes()) == 2 and _en_attente() == []


def test_transferer_une_conversation_inconnue_est_refuse_et_rien_n_est_ecrit(capacites):
    _sms(capacites, "Bonjour", "SM-1", expediteur=AUTRE)
    avant = _lignes()
    reponse = _transferer(capacites, "ventes", expediteur=NUMERO)
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-TRANSFERT-CONVERSATION-INCONNUE"
    assert _lignes() == avant and _attentes() == []


def test_un_type_hors_de_l_ensemble_ferme_est_refuse_par_le_schema(capacites):
    _sms(capacites, "Bonjour")
    reponse = _transferer(capacites, "livraison")
    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides"
    assert _lignes("transfert") == []


def test_l_expediteur_est_valide_comme_pour_un_message_recu(capacites):
    reponse = _transferer(capacites, "ventes", expediteur="514-555-0142")
    assert reponse["ok"] is False and reponse["erreur"] == "refus_metier" and "E.164" in reponse["details"]


def test_un_second_appel_pour_la_meme_conversation_et_le_meme_type_rend_le_transfert_ouvert(capacites):
    _sms(capacites, "Où en est ma facture?")
    premiere = _ok(_transferer(capacites, "finance"))
    seconde = _ok(_transferer(capacites, "finance"))
    assert seconde["deja_ouvert"] is True
    assert seconde["transfert"]["transfert_id"] == premiere["transfert"]["transfert_id"]
    assert len(_lignes("transfert")) == 1
    autre_type = _ok(_transferer(capacites, "ventes"))
    assert autre_type["deja_ouvert"] is False and len(_attentes()) == 2


# -- Le résumé : obligatoire, composé ou contrôlé ---


def test_un_resume_fourni_et_recevable_est_garde_avec_les_faits_du_code(capacites):
    _sms(capacites, "Où en est ma facture?")
    resume = "Le client demande où en est sa facture de la semaine passée et souhaite un retour par texto."
    resultat = _ok(_transferer(capacites, "finance", resume=resume))
    assert resultat["resume_origine"] == "agent"
    (ligne,) = _lignes("transfert")
    assert ligne["resume"] == resume and "Transfert aux finances. Ouvert par : l'agent." in ligne["faits"]


@pytest.mark.parametrize("resume, code", [
    ("", "REJ-TRANSFERT-RESUME-VIDE"),
    ("    ", "REJ-TRANSFERT-RESUME-VIDE"),
    ("Rappeler le client au 514-555-0199.", "REJ-TRANSFERT-RESUME-CONTACT"),
    ("Écrire à marie@exemple.ca pour la suite.", "REJ-TRANSFERT-RESUME-CONTACT"),
    ("Le client veut un prix de 5 000 $.", "REJ-INTERDIT-PRIX"),
    ("On passera réparer demain matin.", "REJ-INTERDIT-DATE"),
    ("Je vous garantis un rappel.", "REJ-INTERDIT-ENGAGEMENT"),
    ("C'est notre faute, nous avons mal fait le travail.", "REJ-INTERDIT-AVEU"),
    ("x " * 700, "REJ-TRANSFERT-RESUME-TROP-LONG"),
])
def test_un_resume_refuse_ne_laisse_rien_au_registre_et_dit_quoi_corriger(capacites, resume, code):
    _sms(capacites, "Où en est ma facture?")
    avant = _lignes()
    for reponse in (_transferer(capacites, "finance", resume=resume), _escalader(capacites, "autre", resume=resume)):
        assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False
        assert reponse["resultat"]["verdict"]["code"] == code
    assert _lignes() == avant and _attentes() == []


def test_un_resume_absent_est_compose_et_jamais_vide(capacites):
    _sms(capacites, "Où en est ma facture?")
    assert _ok(_transferer(capacites, "finance"))["resume_origine"] == "code"
    (ligne,) = _lignes("transfert")
    assert ligne["resume"] == ligne["faits"] and len(ligne["resume"]) > 100


def test_un_transfert_de_l_agent_ferme_aussi_la_prochaine_action_de_la_conversation(capacites):
    """La demande incomplète avait une prochaine action datée (T4.4) : une personne a maintenant la conversation, M1 ne
    la compte plus « à suivre » (sinon le digest la dirait « sans suivi » alors qu'une attente la porte)."""
    taxonomie.enregistrer_fenetre_conversation(30)
    _sms(capacites, "Mes gouttières fuient", "SM-1", 0)
    assert [ligne["statut"] for ligne in _lignes("suivi_conversation")] == ["ouverte"]
    _ok(_transferer(capacites, "ventes"))
    dernieres = _lignes("suivi_conversation")
    assert dernieres[-1]["statut"] == "close" and dernieres[-1]["motif_fermeture"] == "transfert_humain"
    assert dernieres[-1]["prochaine_action"] is None and len(dernieres) == 2
    _ok(_transferer(capacites, "finance"))
    assert len(_lignes("suivi_conversation")) == 2, "déjà close : rien n'est réécrit"


def test_une_fenetre_declaree_mais_invalide_refuse_le_transfert_de_l_agent_sans_rien_ecrire(capacites):
    _sms(capacites, "Où en est ma facture?")
    fichier = taxonomie.fichier_profil()
    fichier.write_text(fichier.read_text(encoding="utf-8") + "fenetre_conversation_minutes: 0\n", encoding="utf-8")
    avant = _lignes()
    reponse = _transferer(capacites, "finance")
    assert reponse["ok"] is False and reponse["erreur"] == "refus_metier"
    assert "REJ-PROFIL-INVALIDE" in reponse["details"]
    assert _lignes() == avant


# -- Escalader une plainte : le jugement de l'agent ---


@pytest.mark.parametrize("raison, type_attendu, niveau, brouillon", [
    ("insatisfaction", "plainte", "N4", plaintes.GABARIT_PLAINTE),
    ("degat", "plainte", "N4", plaintes.GABARIT_PLAINTE),
    ("garantie", "plainte", "N4", plaintes.GABARIT_PLAINTE),
    ("autre", "plainte", "N4", plaintes.GABARIT_PLAINTE),
    ("avocat", "plainte", "N5", None),
    ("securite", "urgence", "N5", plaintes.GABARIT_URGENCE),
])
def test_escalader_une_plainte_ouvre_le_meme_transfert_que_les_regles_avec_son_brouillon(
    capacites, raison, type_attendu, niveau, brouillon
):
    _sms(capacites, "Bonjour, ça ne va pas du tout avec vos gars.")
    resultat = _ok(_escalader(capacites, raison))
    assert resultat["transfert"]["type_transfert"] == type_attendu and resultat["transfert"]["niveau"] == niveau
    assert resultat["brouillon_reponse"] == brouillon and resultat["envoye"] is False
    if brouillon is None:
        assert resultat["sans_brouillon"] == "sujet_legal_reponse_humaine"
    (ligne,) = _lignes("transfert")
    expected = [] if raison == "autre" else [raison]
    assert ligne["categories"] == expected and ligne["declenche_par"] == "agent"
    assert _attentes()[0]["niveau"] == niveau


def test_l_agent_ne_sous_classe_jamais_un_danger_qu_une_plainte_evoquait(capacites, corpus_plaintes):
    """Le texte rassemblé dit « dangereux » (vocabulaire de sécurité) : même une `insatisfaction` déclarée par l'agent
    devient une urgence. On ne descend jamais d'un niveau par le choix d'un mot. (Le vocabulaire de sécurité est écrit
    APRÈS la réception : les règles n'avaient rien vu, le jugement de l'agent arrive ensuite.)"""
    taxonomie.enregistrer_signaux_plainte({"insatisfaction": ["déçu"]})
    recu = _sms(capacites, "Ma gouttière est dangereuse pour mes enfants.")
    assert recu["decision"] == "DEMANDER_PRECISIONS"
    taxonomie.enregistrer_signaux_plainte(corpus_plaintes["signaux_plainte"])
    resultat = _ok(_escalader(capacites, "insatisfaction"))
    assert resultat["transfert"]["type_transfert"] == "urgence" and resultat["transfert"]["niveau"] == "N5"
    assert resultat["brouillon_reponse"] == plaintes.GABARIT_URGENCE
    (ligne,) = _lignes("transfert")
    assert ligne["categories"] == ["insatisfaction", "securite"]


def test_transferer_un_type_plainte_dont_le_texte_evoque_un_danger_devient_une_urgence(capacites, corpus_plaintes):
    taxonomie.enregistrer_signaux_plainte({"insatisfaction": ["déçu"]})
    _sms(capacites, "Ma gouttière est dangereuse pour mes enfants.")
    taxonomie.enregistrer_signaux_plainte(corpus_plaintes["signaux_plainte"])
    resultat = _ok(_transferer(capacites, "plainte"))
    assert resultat["transfert"]["type_transfert"] == "urgence" and resultat["transfert"]["niveau"] == "N5"


def test_les_plaintes_que_les_regles_ne_voient_pas_sont_escaladees_par_le_jugement_de_l_agent(
    capacites, corpus_plaintes
):
    """La limite des règles (mots, pas sens) est couverte : chaque message que le code laisse passer comme demande peut
    être escaladé par l'agent. 4 sur 4."""
    escaladees = 0
    for i, un in enumerate(corpus_plaintes["limites"]):
        expediteur = f"+1514555{i:04d}"
        recu = _sms(capacites, un["texte"], f"SM-{un['id']}", i, expediteur=expediteur)
        assert recu["decision"] == "DEMANDER_PRECISIONS" and "transfert" not in recu, "les règles ne la voient pas"
        assert _ok(_escalader(capacites, "autre", expediteur=expediteur))["transfert"]["nouveau"] is True
        escaladees += 1
    assert escaladees == len(corpus_plaintes["limites"]) == 4 and len(_attentes()) == 4


def test_les_messages_couverts_par_un_transfert_de_l_agent_ne_se_qualifient_plus(capacites):
    taxonomie.enregistrer_fenetre_conversation(60)
    _sms(capacites, "Mes gouttières fuient à Québec", "SM-1", 0)  # un lead est déjà parti
    _sms(capacites, "Bravo pour le travail, vraiment.", "SM-2", 5)
    transfert = _ok(_escalader(capacites, "autre"))["transfert"]
    suite = _sms(capacites, "Rappelez-moi", "SM-3", 10)
    assert suite["decision"] == "TRANSFERT_EN_COURS" and suite["transfert"]["transfert_id"] == transfert["transfert_id"]
    (ligne,) = _lignes("transfert")
    assert ligne["signaux"] == ["sms:SM-1", "sms:SM-2"] and ligne["horodatage"] == _a(5), "daté du dernier message"
    assert "Lead déjà transmis à M2" in ligne["resume"]


# -- Lire : le contexte complet d'un transfert ---


def test_lire_un_transfert_rend_le_resume_le_contact_les_messages_et_le_brouillon(capacites):
    _sms(capacites, "Je suis très déçu du travail, rappelez-moi au 514-555-0199.", "SM-1", 0)
    _sms(capacites, "Toujours rien", "SM-2", 5)
    tid = _attentes()[0]["id"]
    reponse = capacites.appeler("m1_lire_transfert", {"transfert_id": tid})
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True and "tronque" not in reponse
    vue = reponse["resultat"]["resultat"]
    assert vue["statut"] == "ouvert" and vue["type_transfert"] == "plainte" and vue["contact"] == {"telephone": NUMERO}
    assert [m["texte"] for m in vue["messages_couverts"]] == [
        "Je suis très déçu du travail, rappelez-moi au 514-555-0199."]
    assert [m["texte"] for m in vue["messages_suivants"]] == ["Toujours rien"]
    assert vue["brouillon_reponse"] == plaintes.GABARIT_PLAINTE and vue["envoye"] is False
    assert vue["client_retire_des_messages"] is False and vue["resume"] == vue["resume"].strip() != ""


def test_lire_un_transfert_inconnu_dit_qu_il_est_inconnu(capacites):
    reponse = capacites.appeler("m1_lire_transfert", {"transfert_id": "tr-inexistant"})
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-TRANSFERT-INCONNU"


def test_la_lecture_reste_sous_la_troncature_de_capacites_meme_au_plus_gros_transfert(capacites):
    """`Capacites` tronque au-delà de 6 000 caractères : le plus gros transfert possible (résumé au maximum, quatre
    messages couverts et quatre suivis affichés, chacun au maximum de longueur) se lit encore en entier."""
    taxonomie.enregistrer_fenetre_conversation(120)
    long = "Bonjour, je vous écris au sujet de la gouttière du côté nord de la maison. " * 8
    assert len(long) > transferts.EXTRAIT_MAX
    for i in range(6):
        _sms(capacites, long, f"SM-{i}", i)  # aucun mot du vocabulaire : des demandes à préciser
    resume = ("Résumé long : " + "le client répète sa demande. " * 60)[: transferts.RESUME_MAX]
    assert len(resume) == transferts.RESUME_MAX
    tid = _ok(_escalader(capacites, "autre", resume=resume))["transfert"]["transfert_id"]
    for i in range(6):
        _sms(capacites, long, f"SN-{i}", 10 + i)  # rattachés au transfert ouvert
    reponse = capacites.appeler("m1_lire_transfert", {"transfert_id": tid})
    assert reponse["ok"] is True and "tronque" not in reponse
    vue = reponse["resultat"]["resultat"]
    assert len(vue["messages_couverts"]) == 4 and vue["messages_couverts_omis"] == 2
    assert len(vue["messages_suivants"]) == 4 and vue["messages_suivants_omis"] == 2
    assert len(json.dumps(reponse, ensure_ascii=False)) < 6000


# -- Clore : une décision humaine ---


def test_un_agent_qui_propose_la_cloture_attend_une_personne_puis_l_attente_disparait(capacites):
    _sms(capacites, "Je suis très déçu du travail.")
    (attente,) = _attentes()
    tid = attente["id"]

    reponse = capacites.appeler("m1_clore_transfert", _args_cloture(tid))
    assert reponse["ok"] is True and reponse["statut"] == "en_attente_approbation"
    (demande,) = _en_attente()
    assert (demande["outil"], demande["niveau"], demande["departement"]) == (
        "m1_clore_transfert", "N3", "m01-front-office")
    assert _cloture_de(tid) == [] and len(_attentes()) == 1, "rien n'est clos avant la décision"

    _approuver(capacites, reponse["demande_id"])
    (cloture,) = _cloture_de(tid)
    assert (cloture["clos_par"], cloture["role"], cloture["voie"]) == ("nathan", "nathan_owner", "approbation")
    assert cloture["motif"] == MOTIF and cloture["horodatage"] == HORODATAGE
    assert _attentes() == [], "la file se vide : l'outil de clôture est ce qui la vide"
    lu = capacites.appeler("m1_lire_transfert", {"transfert_id": tid})["resultat"]["resultat"]
    assert lu["statut"] == "clos" and lu["cloture"]["par"] == "nathan" and "brouillon_reponse" not in lu
    with stockage.transaction():
        assert outils_m1._obtenir_registre().valider_chaine() == (True, None)


def test_un_employe_ne_peut_pas_approuver_la_cloture(capacites):
    _sms(capacites, "Je suis très déçu du travail.")
    tid = _attentes()[0]["id"]
    reponse = capacites.appeler("m1_clore_transfert", _args_cloture(tid))
    with pytest.raises(ValueError, match="aucun rôle autorisé"):
        _approuver(capacites, reponse["demande_id"], "employe.fictif")
    with pytest.raises(ValueError, match="aucun rôle autorisé"):
        _approuver(capacites, reponse["demande_id"], "admin.fictif")  # la politique de M1 ne déclare que nathan_owner
    assert _cloture_de(tid) == [] and len(_attentes()) == 1


# -- Ce que le SOCLE dit d'une approbation (T4.15-d : M1 ne lit plus la table des approbations) ---
# `approbations.decider` pose la demande qu'il exécute et `approbations.approbateur_en_cours` dit qui l'a approuvée : la
# matrice complète est dans `tests/test_approbateur_en_cours.py`. Ici : ce que M1 en fait, par le VRAI `decider`.


def _approuver_sous_une_politique_elargie(dep, demande_id, par, roles_n3):
    """Le VRAI `decider`, dans un département dont la politique N3 admet `roles_n3` (le manifeste de M1 ne déclare que
    `nathan_owner`) : la file accepte alors ces rôles, et l'outil décide seul lesquels il reconnaît comme humains."""
    elargi = dataclasses.replace(
        dep, politique_approbation=PolitiqueApprobation(roles={Niveau.N3: frozenset(roles_n3)}))
    departements = {elargi.id: elargi}
    with stockage.transaction() as cnx:
        return approbations.decider(
            cnx, demande_id, True, par, outils_executables(departements, stockage.transaction), departements)


def _proposer_une_cloture(capacites):
    _sms(capacites, "Je suis très déçu du travail.")
    tid = _attentes()[0]["id"]
    return tid, capacites.appeler("m1_clore_transfert", _args_cloture(tid))["demande_id"]


def test_une_ligne_en_cours_ecrite_a_la_main_ne_clot_rien_meme_bien_formee(capacites, dep):
    """Ce que M1 acceptait avant T4.15-d (une demande `en_cours` de `m1_clore_transfert`, aux mêmes arguments, du
    propriétaire actif) ne vaut plus rien sans que `decider` soit en train d'exécuter."""
    _sms(capacites, "Je suis très déçu du travail.")
    tid = _attentes()[0]["id"]
    with stockage.transaction() as cnx:
        ident = approbations.creer_demande(cnx, dep.id, "m1_clore_transfert", _args_cloture(tid), niveau=Niveau.N3)
        cnx.execute(update(APPROBATIONS).where(APPROBATIONS.c.id == ident).values(
            statut="en_cours", decide_par="nathan", decide_role="nathan_owner"))
        forgee = outils_m1.clore_transfert(**_args_cloture(tid))

    assert forgee["accepte"] is False and forgee["verdict"]["code"] == "REJ-HUMAIN-REQUIS"
    assert _cloture_de(tid) == [] and len(_attentes()) == 1


def test_l_approbation_d_une_cloture_ne_sert_pas_a_clore_un_autre_transfert(capacites):
    """Le socle ne dit qui a approuvé que PENDANT `decider` : un agent qui appelle l'outil ensuite, pour un AUTRE
    transfert, ne récupère pas cette approbation."""
    _sms(capacites, "Je suis très déçu du travail.", "SM-1", 0, expediteur=NUMERO)
    _sms(capacites, "Je suis très déçu du travail.", "SM-2", 1, expediteur=AUTRE)
    premier, second = sorted(attente["id"] for attente in _attentes())
    demande = capacites.appeler("m1_clore_transfert", _args_cloture(premier))["demande_id"]
    assert _approuver(capacites, demande)["statut"] == "executee"

    outil = next(o for o in capacites.lister() if o.nom == "m1_clore_transfert")
    apres = executer_atomique(outil, _args_cloture(second))

    assert apres["ok"] is True and apres["resultat"]["verdict"]["code"] == "REJ-HUMAIN-REQUIS"
    assert len(_cloture_de(premier)) == 1 and _cloture_de(second) == []


@pytest.mark.parametrize("par, role", [("gestion", "manager"), ("employe.fictif", "employee"),
                                       ("robot", "system_agent")])
def test_un_role_que_la_file_admet_mais_que_l_outil_ne_reconnait_pas_ne_clot_rien(capacites, dep, par, role):
    """Le manifeste peut élargir la politique N3, mais l'outil refuse ces acteurs et la demande échoue."""
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "gestion", "Gestionnaire Fictive", "mot-de-passe-gestion-1234", ["manager"])
        identite.creer_personne(cnx, "robot", "Agent Fictif", "mot-de-passe-robot-123456", ["system_agent"])
    tid, demande = _proposer_une_cloture(capacites)

    decision = _approuver_sous_une_politique_elargie(dep, demande, par, {role, "nathan_owner"})

    assert decision["statut"] == "echec", decision
    assert decision["reponse"]["resultat"]["accepte"] is False
    assert decision["reponse"]["resultat"]["verdict"]["code"] == "REJ-HUMAIN-REQUIS"
    assert _cloture_de(tid) == [] and len(_attentes()) == 1


def test_un_admin_que_la_file_admet_clot_sous_son_role_par_la_voie_approbation(capacites, dep):
    tid, demande = _proposer_une_cloture(capacites)

    decision = _approuver_sous_une_politique_elargie(dep, demande, "admin.fictif", {"admin", "nathan_owner"})

    assert decision["reponse"]["resultat"]["accepte"] is True
    (cloture,) = _cloture_de(tid)
    assert (cloture["clos_par"], cloture["role"], cloture["voie"]) == ("admin.fictif", "admin", "approbation")


@pytest.mark.parametrize("mode", ["supervise", "autonome"])
def test_un_agent_ne_clot_jamais_seul_meme_dans_un_mode_ou_un_n3_s_execute_sans_file(capacites, dep, mode):
    """Un N3 s'exécute sans file en `supervise` et en `autonome` : l'outil refuse lui-même tout appel qui n'est pas une
    décision humaine."""
    _sms(capacites, "Je suis très déçu du travail.")
    tid = _attentes()[0]["id"]
    _fermer_mode(dep, mode)
    reponse = capacites.appeler("m1_clore_transfert", _args_cloture(tid))
    assert reponse["ok"] is True and "statut" not in reponse
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-HUMAIN-REQUIS"
    assert _cloture_de(tid) == [] and len(_attentes()) == 1


def test_l_admin_authentifie_clot_depuis_son_appareil_sans_file_et_avec_sa_trace(capacites):
    _sms(capacites, "Je suis très déçu du travail.")
    tid = _attentes()[0]["id"]
    reponse = _appareil(
        capacites, "m1_clore_transfert", _args_cloture(tid, horodatage=HORLOGE_APPAREIL_DEREGLEE), ADMIN)

    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True and "statut" not in reponse
    (cloture,) = _cloture_de(tid)
    assert (cloture["clos_par"], cloture["role"], cloture["voie"]) == ("admin.fictif", "admin", "appareil")
    # L'heure de RÉCEPTION du serveur fait foi, jamais celle, déréglée, de l'appareil ni l'argument.
    assert cloture["horodatage"] != HORLOGE_APPAREIL_DEREGLEE
    assert abs((dt.datetime.now(dt.UTC) - dt.datetime.fromisoformat(cloture["horodatage"])).total_seconds()) < 120
    with stockage.transaction() as cnx:
        (trace,) = approbations.lister(cnx, "executee")
    assert (trace["decide_par"], trace["decide_role"], trace["outil"]) == (
        "admin.fictif", "admin", "m1_clore_transfert")
    assert _attentes() == []


def test_l_appareil_qui_renvoie_la_meme_cle_rejoue_la_reponse_sans_seconde_cloture(capacites):
    _sms(capacites, "Je suis très déçu du travail.")
    tid = _attentes()[0]["id"]
    premiere = _appareil(capacites, "m1_clore_transfert", _args_cloture(tid), ADMIN, "mut-7")
    seconde = _appareil(capacites, "m1_clore_transfert", _args_cloture(tid), ADMIN, "mut-7")
    assert premiere["rejoue"] is False and seconde["rejoue"] is True
    assert len(_cloture_de(tid)) == 1


def test_un_employe_ne_peut_pas_clore_un_transfert_depuis_son_appareil(capacites):
    """`Capacites` juge la portée quand une approbation serait requise (la clôture, N3) ; pour la lecture (N0), c'est la
    porte d'appareil du core qui la refuse, d'après `roles.json` (voir `test_seuls_la_lecture_et_la_cloture...` et
    l'E2E `tests/e2e/test_plainte_urgence_appareil.py`, où l'employé reçoit 403)."""
    _sms(capacites, "Je suis très déçu du travail.")
    tid = _attentes()[0]["id"]
    reponse = _appareil(capacites, "m1_clore_transfert", _args_cloture(tid), EMPLOYE, "mut-employe")
    assert reponse["ok"] is False and reponse["erreur"] == "hors_portee_role"
    assert _cloture_de(tid) == []


@pytest.mark.parametrize("perte", ["role_retire", "personne_desactivee", "personne_inconnue"])
def test_une_identite_d_appareil_que_la_base_ne_confirme_plus_ne_clot_rien(capacites, dep, perte):
    _sms(capacites, "Je suis très déçu du travail.")
    tid = _attentes()[0]["id"]
    identite_appelante = ADMIN
    with stockage.transaction() as cnx:
        if perte == "role_retire":
            identite.ajouter_role(cnx, "admin.fictif", "employee")
            identite.retirer_role(cnx, "admin.fictif", "admin")
        elif perte == "personne_desactivee":
            identite.activer(cnx, "admin.fictif", False)
        else:
            identite_appelante = contexte.IdentiteAppelante(personne="fantome.fictif", role="admin")

    en_ombre = _appareil(capacites, "m1_clore_transfert", _args_cloture(tid), identite_appelante, "mut-1")
    assert en_ombre["ok"] is True and en_ombre["statut"] == "en_attente_approbation", "la file, rien n'est exécuté"
    assert _cloture_de(tid) == []

    _fermer_mode(dep, "supervise")
    sans_file = _appareil(capacites, "m1_clore_transfert", _args_cloture(tid), identite_appelante, "mut-2")
    assert sans_file["resultat"]["verdict"]["code"] == "REJ-HUMAIN-IDENTITE-INVALIDE"
    assert _cloture_de(tid) == []


def test_un_nom_fourni_dans_les_arguments_n_est_pas_une_identite(capacites):
    _sms(capacites, "Je suis très déçu du travail.")
    tid = _attentes()[0]["id"]
    reponse = _appareil(capacites, "m1_clore_transfert", {**_args_cloture(tid), "par": "nathan"}, ADMIN)
    assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides"
    assert _cloture_de(tid) == []


@pytest.mark.parametrize("motif, code", [
    ("court", "REJ-HUMAIN-MOTIF-INVALIDE"),
    ("x" * 501, "REJ-HUMAIN-MOTIF-INVALIDE"),
])
def test_une_cloture_sans_motif_recevable_est_refusee_et_l_attente_reste(capacites, motif, code):
    _sms(capacites, "Je suis très déçu du travail.")
    tid = _attentes()[0]["id"]
    reponse = _appareil(capacites, "m1_clore_transfert", _args_cloture(tid, motif=motif), ADMIN)
    assert reponse["resultat"]["accepte"] is False and reponse["resultat"]["verdict"]["code"] == code
    assert _cloture_de(tid) == [] and len(_attentes()) == 1


def test_clore_deux_fois_ou_un_transfert_inconnu_est_refuse_avec_un_verdict(capacites):
    _sms(capacites, "Je suis très déçu du travail.")
    tid = _attentes()[0]["id"]
    assert _appareil(capacites, "m1_clore_transfert", _args_cloture(tid), ADMIN, "mut-1")["resultat"]["accepte"] is True
    encore = _appareil(capacites, "m1_clore_transfert", _args_cloture(tid), ADMIN, "mut-2")
    assert encore["resultat"]["verdict"]["code"] == "REJ-TRANSFERT-DEJA-CLOS"
    inconnu = _appareil(capacites, "m1_clore_transfert", _args_cloture("tr-inexistant"), ADMIN, "mut-3")
    assert inconnu["resultat"]["verdict"]["code"] == "REJ-TRANSFERT-INCONNU"
    assert len(_cloture_de(tid)) == 1


# -- La file du propriétaire : « À voir » ---


def test_les_attentes_de_m1_sont_lues_par_la_file_du_proprietaire_dans_l_ordre_niveau_puis_anciennete(capacites, dep):
    _sms(capacites, "Je suis très déçu du travail.", "SM-1", 0, expediteur=NUMERO)  # plainte, N4, la plus ancienne
    _sms(capacites, "Où en est ma facture?", "SM-2", 1, expediteur=AUTRE)
    _transferer(capacites, "finance", expediteur=AUTRE)  # N3
    _sms(capacites, "Il y a de la fumée qui sort du soffite.", "SM-3", 2, expediteur="+15145550144")  # urgence, N5

    with stockage.transaction() as cnx:
        file = approbations.file_proprietaire(cnx, {dep.id: dep})
        attentes, illisibles = approbations.attentes_departements(cnx, {dep.id: dep})
    assert illisibles == []
    assert [a["type"] for a in attentes] == ["urgence_escaladee", "plainte_escaladee", "transfert_humain"]
    assert [a["niveau"] for a in attentes] == ["N5", "N4", "N3"]
    assert all(a["departement"] == "m01-front-office" for a in attentes)
    assert {a["id"] for a in file} == {a["id"] for a in attentes}
    assert all(set(a) >= set(approbations.CHAMPS_ATTENTE) for a in attentes)


def test_attentes_se_charge_comme_le_verifie_opsys_verifier(dep):
    fonction = dep.charger_attentes()
    assert callable(fonction)


def test_sans_transfert_au_registre_aucune_attente(capacites):
    _sms(capacites, "Mes gouttières fuient à Laval")
    assert _attentes() == []


# -- Qui appelle quoi : la portée des appareils ---


def test_seuls_la_lecture_la_cloture_et_import_sont_ouverts_a_l_admin(dep):
    portees = openclaw.roles_outils({dep.id: dep})
    m1_admin = {nom for nom in portees["admin"] if nom.startswith("m1_")}
    assert m1_admin == {"m1_lire_transfert", "m1_clore_transfert", "m1_produire_digest",
                        "m1_importer_appel_manuellement"}
    for role in ("employee", "seller"):
        assert not any(nom.startswith("m1_") for nom in portees.get(role, ())), role
    par_nom = {o.nom: o for o in dep.charger_outils()}
    for nom in ("m1_transferer", "m1_escalader_plainte", "m1_recevoir_message_canal"):
        assert par_nom[nom].roles_appareil == frozenset(), f"{nom} : réservé à l'agent, fermé à tous les appareils"


def test_les_outils_de_transfert_n_ecrivent_jamais_un_message_au_client(dep):
    """Le seul outil de M1 qui écrit à un client reste `m1_emettre_notification` (N4)."""
    par_nom = {o.nom: o for o in dep.charger_outils()}
    assert par_nom["m1_emettre_notification"].niveau_effectif.value == "N4"
    for nom in ("m1_transferer", "m1_escalader_plainte", "m1_lire_transfert", "m1_clore_transfert"):
        description = par_nom[nom].description.lower()
        assert "envoie" not in description and "emet" not in description, nom
