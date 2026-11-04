"""Routines planifiées de M1 (réception), de bout en bout : une journée de réception FICTIVE (appel manqué, message
sans suivi,
plainte, urgence, rendez-vous) traitée par les VRAIS outils de M1, le VRAI planificateur durable et une horloge
INJECTÉE (aucun
sleep). On prouve que le digest et les alertes sortent aux bons créneaux, une seule fois, que l'ombre ne consigne rien,
que rien
d'externe ne part et que rien de personnel n'entre dans les journaux ni dans les attentes.

Limite dite sans euphémisme : SQLite seulement, horloge injectée, données fictives ; aucun canal réel (SMS, courriel,
téléphone).
"""

from __future__ import annotations

import datetime as dt
import json

import planif_routines_monde as w
import pytest
from sqlalchemy import func, select

from opsys import stockage
from opsys.outils import Niveau
from opsys.stockage.schema import APPROBATIONS, EVENEMENTS_SORTANTS, PLANIFICATEUR_JOURNAL

LUNDI, MARDI = "2026-11-09", "2026-11-10"
CLIENT_A, CLIENT_B, CLIENT_C, CLIENT_D = "+15145550101", "+15145550102", "+15145550103", "+15145550104"
APPEL = "+15145550199"
DIGEST, ECHEANCES, URGENCES = "m1.routine.digest-reception", "m1.routine.rappels-et-suivis", "m1.routine.urgences"


@pytest.fixture
def plan(tmp_path, monkeypatch, declarer_services):
    plan = w.monter(tmp_path, monkeypatch, declarer_services)
    yield plan
    w.demonter()


def _journee_de_reception(plan):
    """Le lundi 9 novembre 2026 (heure de l'Est) : rendez-vous demandé, message sans suite, appel manqué, plainte,
    urgence."""
    reponse = w.sms(
        CLIENT_D,
        "SM-RDV",
        w.local(LUNDI, "13:50"),
        "Bonjour, quand pouvez-vous venir évaluer mes gouttières à Laval ? Merci.",
    )
    rdv_id = w.rendez_vous_retenu("sms:SM-RDV", w.local(LUNDI, "14:00"))
    w.sms(
        CLIENT_A, "SM-SANS-SUITE", w.local(LUNDI, "15:00"), "Mes gouttières fuient."
    )  # ni ville ni suite : sans suivi à 17 h
    rappel = w.appel_manque(APPEL, 1, w.local(LUNDI, "16:00"))
    plainte = w.sms(
        CLIENT_B, "SM-PLAINTE", w.local(LUNDI, "18:00"), "Je suis très déçu de vos travaux, c'est mal fait."
    )
    urgence = w.sms(CLIENT_C, "SM-URGENCE", w.local(LUNDI, "19:00"), "Danger : un fil électrique pend, j'ai peur.")
    return {"rdv": rdv_id, "rappel": rappel, "plainte": plainte, "urgence": urgence, "reponse_rdv": reponse}


def _types_attentes():
    return sorted(a["type"] for a in w.attentes_m1())


def test_la_journee_de_reception_est_celle_que_l_on_croit(plan):
    """Le décor : les cinq situations existent au registre avant toute routine (rien n'est inventé par les routines)."""
    j = _journee_de_reception(plan)
    types = {t["type_transfert"] for t in w.transferts_ouverts().values()}
    assert types == {"ventes", "plainte", "urgence"}, types
    assert j["rappel"] in w.transferts_ouverts()
    assert _types_attentes() == [
        "plainte_escaladee",
        "transfert_humain",
        "urgence_escaladee",
    ]  # rien de plus : routines inactives
    assert w.avis_m1() == []


def _genres():
    return sorted(a["genre"] for a in w.avis_m1() if a["type_entree"] == "avis_reception")


def _statuts(resume):
    return {n.split(".")[-1]: v["statut"] for n, v in resume.items()}


def test_rien_ne_tourne_par_defaut(plan):
    _journee_de_reception(plan)
    resume = w.tour(plan, w.local(MARDI, "08:00"))
    assert set(resume) == set(w.ROUTINES_M1 + w.ROUTINES_M10)
    assert {v["statut"] for v in resume.values()} == {"inactif"}
    assert w.avis_m1() == [] and w.journal() == []


def test_le_digest_et_les_alertes_sortent_aux_bons_creneaux_une_seule_fois(plan):
    w.aller_a(plan, w.local(LUNDI, "06:00"))
    w.activer(plan, w.ROUTINES_M1)
    # Avant l'heure déclarée (7 h, reprise du cron de la planification « digest-front-office ») : rien.
    assert _statuts(w.tour(plan, w.local(LUNDI, "06:00")))["digest-reception"] == "ok"
    assert w.avis_m1() == []
    # 7 h : le digest du lundi (registre vide : des zéros dits, pas inventés) ; 7 h 15 : rien de plus.
    assert w.tour(plan, w.local(LUNDI, "07:00"))[DIGEST]["notices"] == 1
    w.tour(plan, w.local(LUNDI, "07:15"))
    assert _genres() == ["digest"]
    lundi = w.avis_m1()[0]
    assert lundi["jour"] == LUNDI and lundi["jours_couverts"] == ["2026-11-08"]
    assert set(lundi["compteurs"].values()) == {0}

    # La journée se déroule : les routines sondent, rien n'est à signaler tant que les délais ne sont pas échus.
    w.sms(
        CLIENT_D,
        "SM-RDV",
        w.local(LUNDI, "13:50"),
        "Bonjour, quand pouvez-vous venir évaluer mes gouttières à Laval ? Merci.",
    )
    w.rendez_vous_retenu("sms:SM-RDV", w.local(LUNDI, "14:00"))
    w.sms(CLIENT_A, "SM-SANS-SUITE", w.local(LUNDI, "15:00"), "Mes gouttières fuient.")
    w.tour(plan, w.local(LUNDI, "15:00"))
    rappel = w.appel_manque(APPEL, 1, w.local(LUNDI, "16:00"))
    w.tour(plan, w.local(LUNDI, "16:00"))
    assert _genres() == ["digest"]

    # 17 h 05 : la fenêtre de 120 min de la conversation de 15 h est terminée sans suite : UNE alerte « sans suivi ».
    w.tour(plan, w.local(LUNDI, "17:05"))
    assert _genres() == ["digest", "sans_suivi"]
    w.sms(CLIENT_B, "SM-PLAINTE", w.local(LUNDI, "18:00"), "Je suis très déçu de vos travaux, c'est mal fait.")
    w.tour(plan, w.local(LUNDI, "18:00"))
    # La conversation née de l'appel manqué (16 h, fenêtre jusqu'à 18 h) et la plainte ont un transfert OUVERT : elles
    # sont déjà à « À voir » ; aucune alerte « sans suivi » de plus (une seule attente par situation).
    assert _genres() == ["digest", "sans_suivi"]

    # 19 h 02 : une urgence de sécurité. Alerte seulement après un intervalle COMPLET de contrôle (300 s) ouverte :
    # au sondage de 19 h 05 elle a 3 minutes (rien) ; à celui de 19 h 10, 8 minutes (une alerte).
    w.tour(plan, w.local(LUNDI, "19:00"))
    w.sms(CLIENT_C, "SM-URGENCE", w.local(LUNDI, "19:02"), "Danger : un fil électrique pend, j'ai peur.")
    w.tour(plan, w.local(LUNDI, "19:05"))
    assert "urgence_non_prise" not in _genres()
    resume = w.tour(plan, w.local(LUNDI, "19:10"))
    assert resume[URGENCES]["notices"] == 1 and _genres() == ["digest", "sans_suivi", "urgence_non_prise"]
    w.tour(plan, w.local(LUNDI, "19:15"))
    w.tour(plan, w.local(LUNDI, "19:30"))
    assert _genres() == ["digest", "sans_suivi", "urgence_non_prise"]  # une seule fois

    # Une personne prend le rappel et consigne une tentative sans contact, avec une échéance explicite : mardi 8 h.
    w.suivi_rappel_par_admin(rappel, "prise_en_charge", w.local(LUNDI, "19:35"))
    w.suivi_rappel_par_admin(rappel, "tentative_sans_contact", w.local(LUNDI, "19:40"), w.local(MARDI, "08:00"))
    w.tour(plan, w.local(LUNDI, "20:00"))

    # Mardi : pas de digest avant 7 h ; à 7 h, le digest du mardi couvre le lundi ; à 7 h 05, rien de plus.
    w.tour(plan, w.local(MARDI, "06:50"))
    assert _genres().count("digest") == 1
    w.tour(plan, w.local(MARDI, "07:00"))
    w.tour(plan, w.local(MARDI, "07:05"))
    assert _genres().count("digest") == 2
    mardi = [a for a in w.avis_m1() if a.get("genre") == "digest"][-1]
    assert mardi["jour"] == MARDI and mardi["jours_couverts"] == [LUNDI]
    assert mardi["compteurs"] == {
        "a_rappeler": 1,
        "a_rappeler_sans_responsable": 0,
        "rappels_echus": 0,
        "rendez_vous_a_confirmer": 1,
        "rappels_rdv_dus": 0,
        "plaintes_ouvertes": 1,
        "urgences_non_prises": 1,
        "sans_suivi": 1,
    }
    assert (
        "DIGEST - Période de référence : 2026-11-09" in mardi["grille"]
    )  # le digest existant du registre, un bloc par jour

    # 8 h 05 : l'échéance explicite du rappel (8 h) est passée, le dossier est toujours ouvert : UNE alerte « rappel
    # échu ».
    w.tour(plan, w.local(MARDI, "08:05"))
    w.tour(plan, w.local(MARDI, "08:30"))
    assert _genres() == ["digest", "digest", "rappel_echu", "sans_suivi", "urgence_non_prise"]

    # « À voir » : le dernier digest seulement, chaque alerte, et les transferts déjà là ; sans donnée personnelle.
    assert _types_attentes() == [
        "conversation_sans_suivi",
        "digest_reception",
        "plainte_escaladee",
        "rappel_echu",
        "transfert_humain",
        "urgence_escaladee",
        "urgence_non_prise",
    ]
    digest = next(a for a in w.attentes_m1() if a["type"] == "digest_reception")
    assert digest["resume"].startswith("Digest de réception du 2026-11-10 : 1 à rappeler (0 échu(s)), 1 rendez-vous")
    urgence = next(a for a in w.attentes_m1() if a["type"] == "urgence_non_prise")
    assert urgence["niveau"] == "N5" and dt.datetime.fromisoformat(urgence["depuis"]) == w.local(LUNDI, "19:10")


def _derouler(plan):
    """La journée du lundi et la matinée du mardi, de 6 h à 8 h 30 : l'état de référence des tests qui suivent."""
    w.aller_a(plan, w.local(LUNDI, "06:00"))
    w.activer(plan, w.ROUTINES_M1)
    w.tour(plan, w.local(LUNDI, "07:00"))
    w.sms(
        CLIENT_D,
        "SM-RDV",
        w.local(LUNDI, "13:50"),
        "Bonjour, quand pouvez-vous venir évaluer mes gouttières à Laval ? Merci.",
    )
    w.rendez_vous_retenu("sms:SM-RDV", w.local(LUNDI, "14:00"))
    w.sms(CLIENT_A, "SM-SANS-SUITE", w.local(LUNDI, "15:00"), "Mes gouttières fuient.")
    rappel = w.appel_manque(APPEL, 1, w.local(LUNDI, "16:00"))
    w.tour(plan, w.local(LUNDI, "17:05"))
    plainte = w.sms(
        CLIENT_B, "SM-PLAINTE", w.local(LUNDI, "18:00"), "Je suis très déçu de vos travaux, c'est mal fait."
    )
    w.tour(plan, w.local(LUNDI, "19:00"))
    urgence = w.sms(CLIENT_C, "SM-URGENCE", w.local(LUNDI, "19:02"), "Danger : un fil électrique pend, j'ai peur.")
    w.tour(plan, w.local(LUNDI, "19:05"))
    w.tour(plan, w.local(LUNDI, "19:10"))
    w.suivi_rappel_par_admin(rappel, "prise_en_charge", w.local(LUNDI, "19:35"))
    w.suivi_rappel_par_admin(rappel, "tentative_sans_contact", w.local(LUNDI, "19:40"), w.local(MARDI, "08:00"))
    w.tour(plan, w.local(MARDI, "07:00"))
    w.tour(plan, w.local(MARDI, "08:05"))
    transferts = w.transferts_ouverts()
    return {
        "rappel": rappel,
        "plainte": plainte,
        "urgence": urgence,
        "urgence_id": next(t for t, o in transferts.items() if o["type_transfert"] == "urgence"),
    }


def test_deuxieme_instance_ou_redemarrage_n_ecrit_rien_de_plus(plan):
    _derouler(plan)
    avant, attentes = w.avis_m1(), w.attentes_m1()
    nombre_journal = len(w.journal())
    # La réservation du créneau est perdue (autre processus, redémarrage) : chaque routine est de nouveau due, à la
    # même heure.
    w.rembobiner(plan, w.ROUTINES_M1)
    resume = w.tour(plan, w.local(MARDI, "08:05"))
    assert {n: v.get("notices", 0) for n, v in resume.items() if n in w.ROUTINES_M1} == {n: 0 for n in w.ROUTINES_M1}
    assert w.avis_m1() == avant and w.attentes_m1() == attentes
    # Le journal n'a pas grossi d'un passage « à vide » non plus : ni digest refait, ni lot recalculé.
    assert len(w.journal()) == nombre_journal
    # Un second passage au même instant est refusé par la réservation de créneau elle-même.
    assert {v["statut"] for n, v in w.tour(plan).items() if n in w.ROUTINES_M1} == {"pas_echu"}


def test_pas_de_rattrapage_en_rafale_apres_un_arret_de_plusieurs_jours(plan):
    _derouler(plan)
    digests = [a for a in w.avis_m1() if a.get("genre") == "digest"]
    assert [d["jour"] for d in digests] == [LUNDI, MARDI]
    # Le serveur est arrêté du mardi 8 h au vendredi midi : UN digest (celui du vendredi), jamais ceux du mercredi et
    # du jeudi.
    resume = w.tour(plan, w.local("2026-11-13", "12:00"))
    assert resume[DIGEST]["notices"] == 1
    w.tour(plan, w.local("2026-11-13", "12:15"))
    digests = [a for a in w.avis_m1() if a.get("genre") == "digest"]
    assert [d["jour"] for d in digests] == [LUNDI, MARDI, "2026-11-13"]
    # Chaque jour entre dans un digest et un seul : celui du vendredi couvre mardi, mercredi et jeudi (la veille et
    # depuis le
    # digest précédent), borné à une semaine.
    assert digests[-1]["jours_couverts"] == ["2026-11-10", "2026-11-11", "2026-11-12"]
    # Le samedi et le dimanche ne sont pas des jours prévus (cron « 1-5 ») : rien.
    w.tour(plan, w.local("2026-11-14", "09:00"))
    w.tour(plan, w.local("2026-11-15", "09:00"))
    assert len([a for a in w.avis_m1() if a.get("genre") == "digest"]) == 3
    # Le lundi suivant couvre vendredi, samedi et dimanche.
    w.tour(plan, w.local("2026-11-16", "07:00"))
    dernier = [a for a in w.avis_m1() if a.get("genre") == "digest"][-1]
    assert dernier["jours_couverts"] == ["2026-11-13", "2026-11-14", "2026-11-15"]


def test_l_alerte_disparait_quand_une_personne_agit_jamais_par_peremption(plan):
    ids = _derouler(plan)
    avant = _types_attentes()
    assert avant.count("urgence_non_prise") == 1 and avant.count("rappel_echu") == 1
    assert avant.count("conversation_sans_suivi") == 1
    # La personne clôt l'urgence : l'alerte ET le transfert sortent de « À voir ».
    w.clore_transfert(ids["urgence_id"], w.local(MARDI, "09:00"))
    apres = _types_attentes()
    assert "urgence_non_prise" not in apres and "urgence_escaladee" not in apres
    # Une nouvelle tentative (nouvelle échéance) remplace l'ancienne situation : l'alerte « rappel échu » sort.
    w.suivi_rappel_par_admin(ids["rappel"], "tentative_sans_contact", w.local(MARDI, "09:10"), w.local(MARDI, "15:00"))
    assert "rappel_echu" not in _types_attentes()
    # Le client A réécrit après la fin de sa fenêtre : sa nouvelle conversation (qui n'est pas encore échue) remplace
    # l'ancienne ;
    # l'alerte de CE client sort.
    w.sms(CLIENT_A, "SM-REPONSE", w.local(MARDI, "09:20"), "Je suis à Laval.")
    assert _types_attentes().count("conversation_sans_suivi") == 0
    # Autre voie : une personne reprend une conversation échue (transfert) : l'alerte sort aussi.
    w.sms(CLIENT_D, "SM-D2", w.local(MARDI, "09:30"), "Je cherche toujours.")
    w.tour(plan, w.local(MARDI, "12:00"))
    # (la nouvelle conversation de A, sans service, est échue à son tour à 11 h 20 ; celle de D à 11 h 30)
    assert _types_attentes().count("conversation_sans_suivi") == 2
    w.transferer_a_une_personne("ventes", CLIENT_D)
    assert _types_attentes().count("conversation_sans_suivi") == 1
    w.transferer_a_une_personne("ventes", CLIENT_A)
    assert _types_attentes().count("conversation_sans_suivi") == 0
    # Les avis, eux, restent au registre (append-only) : l'historique est complet.
    assert (
        sorted(a["genre"] for a in w.avis_m1() if a["type_entree"] == "avis_reception").count("urgence_non_prise") == 1
    )
    # Un temps très long ne fait rien disparaître à lui seul.
    w.tour(plan, w.local("2026-12-20", "12:00"))
    assert _types_attentes().count("conversation_sans_suivi") == 0
    assert "digest_reception" in _types_attentes()


def test_l_ombre_dit_ce_qu_elle_ferait_sans_rien_consigner(plan):
    w.aller_a(plan, w.local(LUNDI, "06:00"))
    w.activer(plan, w.ROUTINES_M1, mode="ombre")
    w.sms(CLIENT_A, "SM-SANS-SUITE", w.local(LUNDI, "15:00"), "Mes gouttières fuient.")
    w.sms(CLIENT_C, "SM-URGENCE", w.local(LUNDI, "19:00"), "Danger : un fil électrique pend, j'ai peur.")
    avant_registres = (w.lignes_m1(), w.avis_m1())
    for heure in ("07:00", "19:06", "19:20", "21:00"):
        resume = w.tour(plan, w.local(LUNDI, heure))
        assert {v["statut"] for n, v in resume.items() if n in w.ROUTINES_M1} <= {"ombre", "pas_echu"}
    # Rien n'est consigné, aucune attente nouvelle, aucun KPI : l'ombre n'appelle que la lecture (et le calcul à blanc).
    assert (w.lignes_m1(), w.avis_m1()) == avant_registres and w.avis_m1() == []
    assert _types_attentes() == ["urgence_escaladee"]
    lignes = [ligne for ligne in w.journal() if ligne["executeur"] in w.ROUTINES_M1]
    aurait = {
        (ligne["executeur"], ligne["ressource"]): ligne["details"] for ligne in lignes if ligne["evenement"] == "aurait"
    }
    assert all(ligne["mode"] == "ombre" for ligne in lignes) and not [
        x for x in lignes if x["evenement"] == "ressource"
    ]
    assert aurait[(DIGEST, LUNDI)] == {"aurait": 1}
    assert any(ex == URGENCES and d == {"aurait": 1} for (ex, _), d in aurait.items())
    assert any(ex == ECHEANCES and d == {"aurait": 1} for (ex, _), d in aurait.items())  # la conversation sans suivi
    # Une seule ligne « aurait » par créneau et par lot : les sondages suivants ne répètent pas le constat.
    assert len(aurait) == len([ligne for ligne in lignes if ligne["evenement"] == "aurait"])
    # Passer à l'actif le même jour fonctionne : un « aurait » d'ombre n'empêche jamais le passage actif.
    w.activer(plan, w.ROUTINES_M1, mode="actif")
    resume = w.tour(plan, w.local(LUNDI, "21:05"))
    assert resume[DIGEST]["notices"] == 1 and resume[URGENCES]["notices"] == 1 and resume[ECHEANCES]["notices"] == 1


def test_rien_d_externe_ne_part_et_rien_n_est_approuve(plan, monkeypatch):
    from m1_front_office import outils as m1

    appels = []
    monkeypatch.setattr(m1, "emettre_notification", lambda *a, **k: appels.append((a, k)))
    assert plan.ports.service_courriel is None and plan.ports.recepteur_m1 is None  # aucun transport branché
    with stockage.transaction() as cnx:
        avant = {t: cnx.execute(select(func.count()).select_from(t)).scalar_one() for t in (APPROBATIONS,)}
    types_avant = None
    _derouler(plan)
    with stockage.transaction() as cnx:
        publies = {r[0] for r in cnx.execute(select(EVENEMENTS_SORTANTS.c.type_evenement))}
        apres = {t: cnx.execute(select(func.count()).select_from(t)).scalar_one() for t in (APPROBATIONS,)}
    assert appels == [] and apres == avant == {APPROBATIONS: 0}  # aucune demande d'approbation, aucune notification
    # le lead de la réception et, pour un transfert ou une plainte ouverts, les événements minimaux de M1-E
    # (identifiants et catégorie seulement) ; aucun courriel, brouillon ni envoi
    assert publies <= {"m1.lead_qualifie", "m1.plainte_ouverte", "m1.transfert_ouvert"}, publies
    assert types_avant is None
    # Un tour de routines seules ne publie AUCUN événement.
    w.rembobiner(plan, w.ROUTINES_M1)
    with stockage.transaction() as cnx:
        compte = cnx.execute(select(func.count()).select_from(EVENEMENTS_SORTANTS)).scalar_one()
    w.tour(plan, w.local(MARDI, "09:00"))
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(EVENEMENTS_SORTANTS)).scalar_one() == compte


def test_rien_de_personnel_dans_les_journaux_les_avis_et_les_attentes(plan):
    _derouler(plan)
    with stockage.transaction() as cnx:
        journal_brut = json.dumps(
            [dict(r) for r in cnx.execute(select(PLANIFICATEUR_JOURNAL)).mappings()], ensure_ascii=False
        )
    surfaces = {
        "journal": journal_brut,
        "avis": json.dumps(w.avis_m1(), ensure_ascii=False),
        "attentes": json.dumps([a for a in w.attentes_m1()], ensure_ascii=False),
    }
    for nom, texte in surfaces.items():
        for personnel in w.PERSONNEL:
            assert personnel not in texte, (nom, personnel)
    # Ce que les avis portent : des comptes, des empreintes de conversation et de transfert, une grille de comptes.
    alerte = next(a for a in w.avis_m1() if a.get("genre") == "urgence_non_prise")
    assert alerte["ref"].startswith("tr-") and set(alerte) <= {
        "type_entree",
        "horodatage",
        "genre",
        "cle",
        "ref",
        "ligne_id",
        "precedent_ligne_id",
    }


def test_la_panne_d_une_routine_n_arrete_pas_les_autres_et_la_reprise_ne_double_rien(plan, monkeypatch):
    from m1_front_office import reception_interne_outils as ri

    original = ri.consigner_a_voir_reception

    def en_panne(groupe, maintenant, jour=None, delai_controle_s=None):
        if groupe == "digest":
            raise RuntimeError("panne simulée du digest")
        return original(groupe, maintenant, jour, delai_controle_s)

    monkeypatch.setattr(ri, "consigner_a_voir_reception", en_panne)
    w.aller_a(plan, w.local(LUNDI, "06:00"))
    w.activer(plan, w.ROUTINES_M1)
    w.sms(CLIENT_C, "SM-URGENCE", w.local(LUNDI, "06:30"), "Danger : un fil électrique pend, j'ai peur.")
    resume = w.tour(plan, w.local(LUNDI, "07:00"))
    assert resume[DIGEST]["statut"] == "erreur" and resume[DIGEST]["erreurs"] == 1
    assert (
        resume[URGENCES]["statut"] == "ok" and resume[URGENCES]["notices"] == 1
    )  # l'urgence est alertée malgré la panne
    assert resume["m1.routine.kpis-reception"]["statut"] == "ok"
    assert [a["genre"] for a in w.avis_m1() if a["type_entree"] == "avis_reception"] == ["urgence_non_prise"]
    # Le créneau n'est pas marqué fait : au sondage suivant, une fois la panne passée, le digest sort — une seule fois.
    monkeypatch.setattr(ri, "consigner_a_voir_reception", original)
    w.tour(plan, w.local(LUNDI, "07:15"))
    w.tour(plan, w.local(LUNDI, "07:30"))
    assert sorted(a["genre"] for a in w.avis_m1() if a["type_entree"] == "avis_reception") == [
        "digest",
        "urgence_non_prise",
    ]


def test_un_outil_de_niveau_n3_n_est_jamais_appele(plan, monkeypatch):
    import dataclasses

    from m1_front_office import reception_interne_outils as ri

    origine = ri.outils_reception_interne

    def promu():
        return tuple(
            dataclasses.replace(o, niveau=Niveau.N3) if o.nom == "m1_consigner_a_voir_reception" else o
            for o in origine()
        )

    monkeypatch.setattr(ri, "outils_reception_interne", promu)
    w.aller_a(plan, w.local(LUNDI, "06:00"))
    w.activer(plan, w.ROUTINES_M1)
    w.sms(CLIENT_C, "SM-URGENCE", w.local(LUNDI, "06:30"), "Danger : un fil électrique pend, j'ai peur.")
    resume = w.tour(plan, w.local(LUNDI, "07:00"))
    for nom in (DIGEST, URGENCES, ECHEANCES):
        assert resume[nom]["statut"] == "refus" and resume[nom]["code"] == "REJ-PLAN-NIVEAU-INTERDIT", (
            nom,
            resume[nom],
        )
    assert [a for a in w.avis_m1() if a["type_entree"] == "avis_reception"] == []  # le niveau est relu AVANT tout appel


def test_les_kpi_de_reception_sont_calcules_et_consultables(plan):
    _derouler(plan)
    resume = w.tour(plan, w.local("2026-11-11", "06:30"))
    assert resume["m1.routine.kpis-reception"]["statut"] == "ok"
    kpis = [x for x in w.avis_m1() if x["type_entree"] == "kpis_reception"]
    assert [k["jour"] for k in kpis][-1] == MARDI  # la veille du mercredi
    dernier = kpis[-1]
    assert set(dernier["kpis"]) == {"taux_signaux_qualifies_pct", "taux_interdits_bloques_pct"}  # ceux du manifeste
    # Le lundi : 5 signaux reçus (rendez-vous, message sans suite, appel manqué, plainte, urgence), 1 lead qualifié.
    lundi = next(k for k in kpis if k["jour"] == LUNDI)
    assert lundi["kpis"]["taux_signaux_qualifies_pct"] == {
        "calculable": True,
        "valeur_pct": 20.0,
        "numerateur": 1,
        "denominateur": 5,
    }
    # Ce que le registre ne permet pas de mesurer est DIT, jamais zéro ni cent.
    interdits = lundi["kpis"]["taux_interdits_bloques_pct"]
    assert interdits["calculable"] is False and "valeur_pct" not in interdits and "consigne" in interdits["manque"]
    # Un jour sans aucun signal : taux non calculable (pas 0 %).
    dimanche = next(k for k in kpis if k["jour"] == "2026-11-08")
    assert dimanche["kpis"]["taux_signaux_qualifies_pct"]["calculable"] is False
    # Consultable par l'outil de lecture.
    from m1_front_office import outils as m1

    with stockage.transaction():
        lecture = m1.outils() and next(o for o in m1.outils() if o.nom == "m1_lire_attentes_reception").fonction(
            w.local(MARDI, "09:00").isoformat()
        )
    assert lecture["resultat"]["derniers_kpis"]["jour"] == MARDI


def test_deux_instances_simultanees_ne_se_partagent_qu_un_creneau(plan):
    """Deux instances (ici deux fils, deux porteurs) font un tour au MÊME instant, chaque routine étant de nouveau due :
    la réservation du créneau (comparaison-échange) n'en laisse passer qu'une par routine, et rien ne double."""
    import threading

    from opsys.connecteurs_planification import planificateur

    _derouler(plan)
    avant = (w.avis_m1(), w.attentes_m1())
    w.rembobiner(plan, w.ROUTINES_M1)
    barriere = threading.Barrier(2)
    resumes: list[dict] = []

    def un_tour(porteur):
        barriere.wait()
        resumes.append(planificateur.tour(plan.departements, ports=plan.ports, porteur=porteur)["executeurs"])

    fils = [threading.Thread(target=un_tour, args=(f"instance-{i}",)) for i in range(2)]
    for f in fils:
        f.start()
    for f in fils:
        f.join(timeout=60)
    assert len(resumes) == 2
    for nom in w.ROUTINES_M1:
        statuts = sorted(r[nom]["statut"] for r in resumes)
        assert statuts.count("ok") + statuts.count("deja_pris") + statuts.count("pas_echu") == 2, (nom, statuts)
        assert statuts.count("ok") <= 1, (nom, statuts)  # au plus un des deux a travaillé ce créneau
    assert (w.avis_m1(), w.attentes_m1()) == avant
