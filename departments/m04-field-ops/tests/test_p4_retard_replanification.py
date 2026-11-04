"""P4-04 / P4-05 (tests ROUGES d'abord) : retard mesurable sur la cédule datée, et replanification outillée.

P4-04 : `retard_sur_cedule` se calcule à partir du créneau daté (`cedule_datee`) et du statut courant :
une intervention `planifiee` ou `en_route` dont la fin du créneau est dépassée à `horodatage_reference`
(dans la tolérance DÉCLARÉE par la direction) est « en retard » ; une tolérance absente rend la règle
« non évaluée » (fail-closed, jamais 0 ni « tout va bien »).
P4-05 : une intervention `reportee` se replanifie dans le cycle (retour à `planifiee` puis nouvelle
proposition/application), avec plan de secours et historique des reports.
Données fictives.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from m4_field_ops import calendrier_civil, cedule_tournees, etats, replanification, retards

_spec = importlib.util.spec_from_file_location(
    "aide_cedule_p4", Path(__file__).with_name("test_cedule_tournees.py"))
_aide = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_aide)
_monde, _proposer, _reussi = _aide._monde, _aide._proposer, _aide._reussi


def _monde_date():
    reg, ids, positions = _monde()
    plan = _reussi(_proposer(reg, ids, positions))["plan_id"]
    _reussi(cedule_tournees.appliquer(reg, plan, positions, "2030-01-01T00:00:00+00:00", "admin.fictif"))
    calendrier_civil.confirmer(reg, plan, {"0": "2030-06-03"}, 0, "admin.fictif", "2030-01-01T00:00:00+00:00")
    return reg, ids, plan


def test_retard_mesurable_depuis_creneau_date_depasse():
    reg, ids, _plan = _monde_date()
    iid = next(iter(ids.values()))
    releve, verdict = retards.lire(reg, "2030-06-03T18:00:00-04:00", tolerance_minutes=30)
    assert verdict is None
    lignes = [r for r in releve["retards_cedule"]["lignes"] if r["intervention_id"] == iid]
    assert lignes and lignes[0]["statut_retard"] == "en_retard"


def test_le_retard_compte_les_minutes_exactes_au_dela_de_la_tolerance():
    reg, ids, _plan = _monde_date()
    releve, verdict = retards.lire(reg, "2030-06-03T18:00:00-04:00", tolerance_minutes=30)
    assert verdict is None
    bloc = releve["retards_cedule"]
    # Fins datées : 10:42, 10:44, 13:27 (−04:00) ; 18:00 − fin − 30 min.
    assert bloc["statut"] == "evalue" and bloc["tolerance_minutes"] == 30
    assert bloc["total"] == 3 and bloc["en_retard"] == 3 and bloc["sans_date"] == 0
    assert [r["minutes_retard"] for r in bloc["lignes"]] == [408, 406, 243]
    assert [r["statut_retard"] for r in bloc["lignes"]] == ["en_retard"] * 3
    # Le plus en retard d'abord, puis par début puis par identifiant.
    assert [r["minutes_retard"] for r in bloc["lignes"]] == sorted(
        [r["minutes_retard"] for r in bloc["lignes"]], reverse=True)


def test_a_la_limite_exacte_de_la_tolerance_c_est_a_l_heure():
    reg, ids, _plan = _monde_date()
    releve, verdict = retards.lire(reg, "2030-06-03T13:57:00-04:00", tolerance_minutes=30)
    assert verdict is None
    lignes = releve["retards_cedule"]["lignes"]
    # À 13:57 : fin 13:27 + 30 min pile → à l'heure (jamais négatif) ; les deux créneaux du matin dépassés.
    par_fin = {r["fin"]: r for r in lignes}
    assert par_fin["2030-06-03T13:27:00-04:00"]["statut_retard"] == "a_l_heure"
    assert par_fin["2030-06-03T13:27:00-04:00"]["minutes_retard"] is None
    assert releve["retards_cedule"]["en_retard"] == 2


def test_une_minute_apres_la_tolerance_c_est_une_minute_de_retard():
    reg, ids, _plan = _monde_date()
    releve, verdict = retards.lire(reg, "2030-06-03T13:58:00-04:00", tolerance_minutes=30)
    assert verdict is None
    ligne = next(r for r in releve["retards_cedule"]["lignes"]
                 if r["fin"] == "2030-06-03T13:27:00-04:00")
    assert (ligne["statut_retard"], ligne["minutes_retard"]) == ("en_retard", 1)
    # Un dépassement de moins d'une minute pleine reste « à l'heure » (jamais 0 minute de retard).
    releve, verdict = retards.lire(reg, "2030-06-03T13:57:30-04:00", tolerance_minutes=30)
    assert verdict is None
    ligne = next(r for r in releve["retards_cedule"]["lignes"]
                 if r["fin"] == "2030-06-03T13:27:00-04:00")
    assert (ligne["statut_retard"], ligne["minutes_retard"]) == ("a_l_heure", None)


def test_une_tolerance_non_entiere_ou_negative_est_refusee():
    reg, _ids, _plan = _monde_date()
    for mauvaise in ("30", 30.5, -1, True):
        releve, verdict = retards.lire(reg, "2030-06-03T18:00:00-04:00", tolerance_minutes=mauvaise)
        assert releve is None and verdict["code"] == "REJ-RETARD-TOLERANCE-A-DECLARER", mauvaise
    # Zéro est une tolérance valide : tout dépassement compte.
    releve, verdict = retards.lire(reg, "2030-06-03T11:13:00-04:00", tolerance_minutes=0)
    assert verdict is None and releve["retards_cedule"]["en_retard"] == 2


def test_une_reference_illisible_est_refusee_avant_la_tolerance():
    reg, _ids, _plan = _monde_date()
    releve, verdict = retards.lire(reg, "pas-une-heure", tolerance_minutes=30)
    assert releve is None and verdict["code"] == "REJ-HORODATAGE-INVALIDE"


def test_une_reportee_d_un_plan_date_n_est_pas_mesurable_mais_comptee():
    reg, ids, _plan = _monde_date()
    iid = next(iter(ids.values()))
    _reussi(etats.transitionner(iid, "reportee", reg, "2030-06-03T09:00:00-04:00", motif="meteo"))
    releve, verdict = retards.lire(reg, "2030-06-03T18:00:00-04:00", tolerance_minutes=30)
    assert verdict is None
    bloc = releve["retards_cedule"]
    assert all(r["intervention_id"] != iid for r in bloc["lignes"])
    assert bloc["sans_date"] == 1 and bloc["en_retard"] == 2
    # Une reportee à validité confirmée mais statut non mesurable reste exclue : les deux conditions
    # du filtre comptent séparément (ni statut mesurable, ni validité confirmée → sans date).
    assert bloc["total"] == 2


def test_une_planifiee_a_date_reconfirmee_n_est_pas_mesurable():
    # Reportée puis revenue planifiée : le statut est mesurable mais la date est à reconfirmer —
    # une seule des deux conditions du filtre est vraie : le « ou » exclut (sans date), le « et »
    # mutant l'inclurait à tort.
    reg, ids, _plan = _monde_date()
    iid = next(iter(ids.values()))
    _reussi(etats.transitionner(iid, "reportee", reg, "2030-06-03T09:00:00-04:00", motif="meteo"))
    _reussi(etats.transitionner(iid, "planifiee", reg, "2030-06-03T10:00:00-04:00"))
    releve, verdict = retards.lire(reg, "2030-06-03T18:00:00-04:00", tolerance_minutes=30)
    assert verdict is None
    bloc = releve["retards_cedule"]
    assert all(r["intervention_id"] != iid for r in bloc["lignes"])
    assert bloc["sans_date"] == 1 and bloc["total"] == 2 and bloc["en_retard"] == 2
    assert bloc["reste"] == 0


def test_les_fins_illisibles_ou_sans_fuseau_sont_sans_date_jamais_devinees(monkeypatch):
    import m4_field_ops.calendrier_civil as _civil

    reg, _ids, _plan = _monde_date()
    bonnes = [
        {"intervention_id": "bonne", "lead_id": "l", "plan_id": "p", "equipe_id": "eq-a",
         "debut": "2030-06-03T08:00:00-04:00", "fin": "2030-06-03T10:00:00-04:00",
         "statut": "planifiee", "validite": "date_confirmee", "confirme_le": "2030-01-01T00:00:00+00:00"},
        {"intervention_id": "illisible", "lead_id": "l", "plan_id": "p", "equipe_id": "eq-a",
         "debut": "2030-06-03T08:00:00-04:00", "fin": "pas-une-date",
         "statut": "planifiee", "validite": "date_confirmee", "confirme_le": "2030-01-01T00:00:00+00:00"},
        {"intervention_id": "naive", "lead_id": "l", "plan_id": "p", "equipe_id": "eq-a",
         "debut": "2030-06-03T08:00:00", "fin": "2030-06-03T10:00:00",
         "statut": "planifiee", "validite": "date_confirmee", "confirme_le": "2030-01-01T00:00:00+00:00"},
    ]
    monkeypatch.setattr(_civil, "_projection", lambda _index: (list(bonnes), []))
    bloc, verdict = retards.retards_cedule(reg, "2030-06-03T18:00:00-04:00", 30)
    assert verdict is None
    # Seule la fin lisible avec fuseau est mesurée (8 h de dépassement → 480 − 30 = 450) ;
    # l'illisible et la naïve sont « sans date », jamais devinées.
    assert bloc["total"] == 1 and bloc["sans_date"] == 2
    assert bloc["lignes"][0]["intervention_id"] == "bonne"
    assert bloc["lignes"][0]["minutes_retard"] == 450


def test_le_tri_place_les_plus_en_retard_d_abord_et_les_a_l_heure_en_dernier():
    reg, _ids, _plan = _monde_date()
    releve, verdict = retards.lire(reg, "2030-06-03T13:57:00-04:00", tolerance_minutes=30)
    assert verdict is None
    minutes = [r["minutes_retard"] for r in releve["retards_cedule"]["lignes"]]
    # 165 et 163 minutes de retard d'abord (ordre décroissant), puis l'à-l'heure (None) en dernier.
    assert minutes == [165, 163, None]
    assert [r["statut_retard"] for r in releve["retards_cedule"]["lignes"]] == [
        "en_retard", "en_retard", "a_l_heure"]


def test_sans_report_ni_incident_les_ventilations_sont_a_zero():
    reg, _ids, _plan = _monde_date()
    releve, verdict = retards.lire(reg, "2030-06-03T18:00:00-04:00", tolerance_minutes=30)
    assert verdict is None
    assert releve["reports"]["total"] == 0 and releve["reports"]["reste"] == 0
    assert releve["reports"]["par_motif"] == {"client_absent": 0, "meteo": 0, "decision_admin": 0}
    assert releve["incidents"]["total"] == 0 and releve["incidents"]["reste"] == 0
    assert releve["incidents"]["par_type"] == {"ecart_metier": 0, "anomalie_pointage": 0}
    assert releve["retards_cedule"]["reste"] == 0


def test_le_reste_des_lignes_de_retard_est_compte_jamais_perdu(monkeypatch):
    import m4_field_ops.retards as module_retards

    reg, _ids, _plan = _monde_date()
    # Troncature à une ligne : une affichée, deux comptées dans `reste`.
    monkeypatch.setattr(module_retards, "LIMITE_PAR_LISTE", 1)
    releve, verdict = retards.lire(reg, "2030-06-03T18:00:00-04:00", tolerance_minutes=30)
    assert verdict is None
    assert len(releve["retards_cedule"]["lignes"]) == 1
    assert releve["retards_cedule"]["reste"] == 2


def test_les_seuils_et_les_comptes_des_listes_sont_justes():
    reg, _ids, _plan = _monde_date()
    assert retards.LIMITE_PAR_LISTE == 8
    assert retards.SEUIL_BLOCAGE_HEURES == 24
    releve, verdict = retards.lire(reg, "2030-06-03T18:00:00-04:00", tolerance_minutes=30)
    assert verdict is None
    # 3 lignes datées, aucune paginée (total = affichées, reste nul, aucune suite).
    assert releve["retards_cedule"]["total"] == 3
    assert releve["retards_cedule"]["reste"] == 0
    # Un relevé qui ne tient pas est refusé avec la consigne, jamais tronqué en silence.
    rien, verdict = retards.presenter(releve, lambda _releve: False)
    assert rien is None and verdict["code"] == "REJ-CONTRAT-INVALIDE"
    garde, verdict = retards.presenter(releve, lambda _releve: True)
    assert verdict is None and garde is releve


def test_le_releve_dit_son_type_et_ses_origines_d_heure():
    reg, ids, _plan = _monde_date()
    releve, verdict = retards.lire(reg, "2030-06-03T18:00:00-04:00", tolerance_minutes=30)
    assert verdict is None
    assert releve["type"] == retards.TYPE_RELEVE
    assert releve["seuil_blocage_heures"] == 24
    assert releve["reference"] == "2030-06-03T18:00:00-04:00"
    for ligne in releve["retards_cedule"]["lignes"]:
        assert ligne["tolerance_minutes"] == 30
        assert set(ligne) == {"intervention_id", "lead_id", "plan_id", "equipe_id", "debut", "fin",
                              "statut", "statut_retard", "minutes_retard", "tolerance_minutes",
                              "confirme_le"}
    # Les lignes gardent la trace du plan appliqué puis daté (même plan, même confirmation).
    assert {r["plan_id"] for r in releve["retards_cedule"]["lignes"]} == {_plan}
    assert {r["confirme_le"] for r in releve["retards_cedule"]["lignes"]} == {"2030-01-01T00:00:00+00:00"}
    assert len(ids) == 3


def test_une_fin_future_reste_a_l_heure_avec_la_tolerance_zero():
    reg, _ids, _plan = _monde_date()
    releve, verdict = retards.lire(reg, "2030-06-03T08:00:00-04:00", tolerance_minutes=0)
    assert verdict is None
    # À 08:00 aucune fin n'est dépassée : tout est à l'heure, zéro en retard, zéro minute partout.
    assert releve["retards_cedule"]["en_retard"] == 0 and releve["retards_cedule"]["total"] == 3
    assert [r["minutes_retard"] for r in releve["retards_cedule"]["lignes"]] == [None] * 3
    assert {r["statut_retard"] for r in releve["retards_cedule"]["lignes"]} == {"a_l_heure"}


def test_l_attente_tolerance_dit_quoi_declarer_tant_que_c_est_vide():
    attente = retards.attente_tolerance_retard(None)
    assert attente["type"] == "tolerance_retard_a_configurer" and attente["niveau"] == "N2"
    assert "tolerance_minutes" in attente["resume"] and "N3" in attente["action_proposee"]
    assert set(attente) == {"type", "id", "resume", "niveau", "depuis", "action_proposee"}
    assert attente["id"] == "tolerance_retard_a_configurer" and attente["depuis"] == ""
    for mauvaise in (None, "30", 30.5, -1, True, 30.0):
        assert retards.attente_tolerance_retard(mauvaise) is not None, mauvaise
    for bonne in (0, 1, 30, 480):
        assert retards.attente_tolerance_retard(bonne) is None, bonne
    # Le `depuis` fourni est recopié tel quel (la file le laisse vide : aucune horloge lue).
    assert retards.attente_tolerance_retard(None, "2030-01-01")["depuis"] == "2030-01-01"


def test_les_reports_courants_ne_retiennent_que_le_dernier_report_des_reportees():
    from m4_field_ops import etats as _etats

    reg, ids, _positions = _monde()
    iids = list(ids.values())
    _reussi(_etats.transitionner(iids[0], "reportee", reg, "2030-06-03T09:00:00-04:00", motif="meteo"))
    _reussi(_etats.transitionner(iids[1], "reportee", reg, "2030-06-03T09:05:00-04:00", motif="meteo"))
    _reussi(_etats.transitionner(iids[1], "planifiee", reg, "2030-06-03T10:00:00-04:00"))
    instantane = cedule_tournees.instantane_du_registre(reg)
    courants = {(r["intervention_id"], r["motif"], r["depuis"]) for r in retards.reports_courants(instantane)}
    assert courants == {(iids[0], "meteo", "2030-06-03T09:00:00-04:00")}
    # Chaque ligne dit d'où vient son heure.
    assert {r["origine_heure"] for r in retards.reports_courants(instantane)} == {"appelant"}
    # Une reportée sortie du cycle (annulée) ne compte plus comme un report en cours.
    _reussi(_etats.transitionner(iids[0], "annulee", reg, "2030-06-03T11:00:00-04:00"))
    assert retards.reports_courants(cedule_tournees.instantane_du_registre(reg)) == []


def test_les_incidents_ouverts_disent_l_origine_de_l_heure_demande_par_demande():
    from m4_field_ops import ecarts as _ecarts
    from m4_field_ops import pointage as _pointage
    from m4_field_ops.registre import Registre as _Registre

    reg = _Registre()
    demande_ecart = {"type_entree": _pointage.TYPE_DEMANDE_REVUE, "demande_id": "d1",
                     "intervention_id": "i1", "type_demande": "ecart_metier",
                     "horodatage": "2030-06-01T08:00:00-04:00"}
    demande_anomalie = {"type_entree": _pointage.TYPE_DEMANDE_REVUE, "demande_id": "d2",
                        "intervention_id": "i2", "type_demande": _pointage.TYPE_REVUE_ANOMALIE,
                        "horodatage": "2030-06-01T09:00:00-04:00", "pointage_ligne_id": "p9",
                        "horodatage_appareil": "2030-06-01T09:01:00-04:00"}
    # Un écart signé par l'appareil (heure de réception serveur) : c'est SON signe qui compte,
    # pas celui d'un pointage (les écarts ne prennent jamais l'heure d'un pointage).
    demande_ecart_signee = {"type_entree": _pointage.TYPE_DEMANDE_REVUE, "demande_id": "d4",
                            "intervention_id": "i4", "type_demande": "ecart_metier",
                            "horodatage": "2030-06-01T13:00:00-04:00",
                            "horodatage_appareil": "2030-06-01T13:02:00-04:00"}
    anomalie_resolue = {"type_entree": _pointage.TYPE_DEMANDE_REVUE, "demande_id": "d3",
                        "intervention_id": "i3", "type_demande": _pointage.TYPE_REVUE_ANOMALIE,
                        "horodatage": "2030-06-01T10:00:00-04:00", "pointage_ligne_id": None}
    anomalie_resolue["pointage_ligne_id"] = None
    id_pointage = reg.ajouter({"type_entree": _pointage.TYPE_POINTAGE,
                               "horodatage": "2030-06-01T10:00:00-04:00",
                               "horodatage_appareil": "2030-06-01T10:02:00-04:00"})
    anomalie_resolue["pointage_ligne_id"] = id_pointage
    id_pointage_2 = reg.ajouter({"type_entree": _pointage.TYPE_POINTAGE,
                                 "horodatage": "2030-06-01T09:00:00-04:00",
                                 "horodatage_appareil": "2030-06-01T09:05:00-04:00"})
    demande_anomalie["pointage_ligne_id"] = id_pointage_2
    resolution = {"type_entree": _ecarts.TYPE_RESOLUTION, "demande_id": "d3",
                    "horodatage": "2030-06-01T12:00:00-04:00"}
    for maillon in (demande_ecart, demande_anomalie, anomalie_resolue, resolution, demande_ecart_signee):
        reg.ajouter(dict(maillon))
    ouverts = {d["demande_id"]: d for d in retards.incidents_ouverts(reg)}
    assert set(ouverts) == {"d1", "d2", "d4"}
    # L'écart porte son propre signe (ici l'heure de l'appelant) ; l'anomalie prend celle de son pointage.
    assert ouverts["d1"]["origine_heure"] == "appelant"
    assert ouverts["d2"]["origine_heure"] == "serveur"
    # L'écart signé par l'appareil dit « serveur » même si un pointage signé existe : son signe est le sien.
    assert ouverts["d4"]["origine_heure"] == "serveur"
    assert ouverts["d1"]["depuis"] == "2030-06-01T08:00:00-04:00"
    # Une anomalie dont le pointage est introuvable reste « appelant », jamais « serveur » sans preuve.
    reg2 = _Registre()
    reg2.ajouter({"type_entree": _pointage.TYPE_DEMANDE_REVUE, "demande_id": "d9",
                  "intervention_id": "i9", "type_demande": _pointage.TYPE_REVUE_ANOMALIE,
                  "horodatage": "2030-06-01T11:00:00-04:00", "pointage_ligne_id": "absent"})
    assert retards.incidents_ouverts(reg2)[0]["origine_heure"] == "appelant"


def test_sans_tolerance_le_verdict_dit_quoi_declarer():
    reg, _ids, _plan = _monde_date()
    releve, verdict = retards.lire(reg, "2030-06-03T18:00:00-04:00", tolerance_minutes=None)
    assert releve is None and verdict["code"] == "REJ-RETARD-TOLERANCE-A-DECLARER"
    assert "tolerance_minutes" in verdict["detail"]


def test_sans_tolerance_le_releve_reste_lisible_non_evalue():
    reg, _ids, _plan = _monde_date()
    releve, verdict = retards.lire(reg, "2030-06-03T18:00:00-04:00")
    assert verdict is None
    assert releve["retards_cedule"]["statut"] == "non_evalue"
    assert releve["retards_cedule"]["manque"]


def test_intervention_en_route_a_l_heure_n_est_pas_en_retard():
    reg, ids, _plan = _monde_date()
    iid = next(iter(ids.values()))
    _reussi(etats.transitionner(iid, "en_route", reg, "2030-06-03T08:00:00-04:00",
                                assignation={"intervention_id": iid, "technicien_id": "eq-a"}))
    releve, verdict = retards.lire(reg, "2030-06-03T09:00:00-04:00", tolerance_minutes=30)
    assert verdict is None
    lignes = [r for r in releve["retards_cedule"]["lignes"] if r["intervention_id"] == iid]
    assert lignes and lignes[0]["statut_retard"] == "a_l_heure"


def test_replanifier_une_reportee_la_remet_en_planifiee():
    reg, ids, _plan = _monde_date()
    iid = next(iter(ids.values()))
    _reussi(etats.transitionner(iid, "reportee", reg, "2030-06-03T09:00:00-04:00", motif="meteo"))
    accuse, verdict = etats.transitionner(iid, "planifiee", reg, "2030-06-03T10:00:00-04:00")
    assert verdict is None and accuse["statut"] == "planifiee"
    assert etats.statut_courant(reg, iid) == "planifiee"
    # Une intervention inconnue est refusée (jamais devinée), avec le secours « attendre ».
    _reg_vide, _ids_vide, pos_vide = _monde()
    dossier, verdict = replanification.verifier(_reg_vide, "introuvable", pos_vide, None, None)
    assert dossier is None and verdict["code"] == "REJ-REPLANIFICATION-REFUS"
    assert "inconnue" in verdict["detail"]
    # Une préparation non prête refuse aussi, statut recopié, secours fourni.
    dossier, verdict = replanification.verifier(reg, iid, pos_vide, None, None)
    assert dossier is None and verdict["code"] == "REJ-REPLANIFICATION-NON-PRETE"
    assert verdict["statut"] in replanification.STATUTS_REPLANIFIABLES


def _lectures_monde():
    reg, ids, positions = _monde()
    return reg, ids, positions, positions, lambda: (None, None)


def test_verifier_dit_la_prochaine_etape_d_une_reportee_prete():
    reg, ids, _positions, lire_position, lire_equipes = _lectures_monde()
    iid = next(iter(ids.values()))
    _reussi(etats.transitionner(iid, "reportee", reg, "2030-06-03T09:00:00-04:00", motif="meteo"))
    dossier, verdict = replanification.verifier(reg, iid, lire_position, lire_equipes, None)
    # Ici la préparation n'est pas « prête » (volet équipe sans profil d'entreprise) : le refus est
    # fail-closed et nomme ce qui manque, avec un plan de secours qui garde le report.
    assert dossier is None and verdict["code"] == "REJ-REPLANIFICATION-NON-PRETE"
    assert "m4_verifier_preparation" in verdict["detail"]
    secours = replanification.plan_de_secours({"statut": "reportee", "historique": [{"motif": "meteo"}],
                                               "preparation": {"a_fournir": []}}, verdict["detail"])
    assert secours["secours"] == "attendre" and "meteo" in secours["conseil"]


def test_verifier_refuse_un_statut_non_replanifiable_avec_secours():
    reg, ids, positions, lire_position, lire_equipes = _lectures_monde()
    iid = next(iter(ids.values()))
    _reussi(etats.transitionner(iid, "en_route", reg, "2030-06-03T08:00:00-04:00",
                                assignation={"intervention_id": iid, "technicien_id": "eq-a"}))
    dossier, verdict = replanification.verifier(reg, iid, lire_position, lire_equipes, None)
    assert dossier is None and verdict["code"] == "REJ-REPLANIFICATION-REFUS"
    secours = replanification.plan_de_secours("en_route", verdict["detail"])
    assert secours["secours"] == "attendre" and secours["statut"] == "en_route"


def test_historique_reports_retient_motifs_heures_et_origine():
    reg, ids, _plan = _monde_date()
    iid = next(iter(ids.values()))
    _reussi(etats.transitionner(iid, "reportee", reg, "2030-06-03T09:00:00-04:00", motif="meteo"))
    _reussi(etats.transitionner(iid, "planifiee", reg, "2030-06-03T10:00:00-04:00"))
    passe = replanification.historique_reports(reg, iid)
    assert passe == [{"motif": "meteo", "horodatage": "2030-06-03T09:00:00-04:00",
                      "origine_heure": "appelant"}]


def test_verifier_prete_donne_la_bonne_prochaine_etape(monkeypatch):
    import m4_field_ops.preparation as preparation_module

    reg, ids, _positions, lire_position, lire_equipes = _lectures_monde()
    iids = list(ids.values())
    _reussi(etats.transitionner(iids[0], "reportee", reg, "2030-06-03T09:00:00-04:00", motif="meteo"))
    prete = {"pret": True, "a_fournir": [], "statut": "pret"}
    monkeypatch.setattr(preparation_module, "evaluer",
                        lambda *a, **k: (dict(prete), None))
    dossier_reportee, verdict_reportee = replanification.verifier(
        reg, iids[0], lire_position, lire_equipes, None)
    assert verdict_reportee is None
    assert dossier_reportee["prochaine_etape"] == "repasser_planifiee"
    assert dossier_reportee["intervention_id"] == iids[0]
    dossier_planifiee, verdict_planifiee = replanification.verifier(
        reg, iids[1], lire_position, lire_equipes, None)
    assert verdict_planifiee is None
    assert dossier_planifiee["prochaine_etape"] == "reproposer_cedule"
    assert dossier_planifiee["preparation"]["pret"] is True
    # Sans l'historique ni la préparation, le secours reste générique mais nommé.
    secours = replanification.plan_de_secours({}, "")
    assert secours["secours"] == "attendre" and secours["reports_passes"] == 0
    assert secours["statut"] == "?" and secours["a_fournir"] == []
    # Une raison vide ne ponctue pas le conseil.
    assert not replanification.plan_de_secours(dossier_planifiee, "")["conseil"].endswith(" : ")
    # Une intervention inconnue n'a aucun historique (liste vide, jamais une erreur).
    assert replanification.historique_reports(reg, "introuvable") == []
    # Un second report se fait depuis planifiee (reportée → planifiée → reportée).
    _reussi(etats.transitionner(iids[0], "planifiee", reg, "2030-06-03T10:00:00-04:00"))
    _reussi(etats.transitionner(iids[0], "reportee", reg, "2030-06-03T10:30:00-04:00", motif="client_absent"))
    assert [e["motif"] for e in replanification.historique_reports(reg, iids[0])] == ["meteo", "client_absent"]


def test_le_dossier_d_une_planifiee_prete_dit_reproposer_la_cedule():
    dossier = {"statut": "planifiee", "historique": [], "preparation": {"a_fournir": []}}
    assert replanification.plan_de_secours(dossier, "")["statut"] == "planifiee"
    assert "planification" in replanification.plan_de_secours(dossier, "")["conseil"]
    # Une planifiee sans dossier vérifié prend la même branche « garder la planification ».
    assert "planification" in replanification.plan_de_secours("planifiee", "")["conseil"]
    # Une reportee sans historique prend la branche « garder l'état courant ».
    assert "état courant" in replanification.plan_de_secours("reportee", "")["conseil"]
    # L'historique (dernier motif) l'emporte sur le statut seul.
    assert "meteo" in replanification.plan_de_secours(
        {"statut": "reportee", "historique": [{"motif": "meteo"}], "preparation": {"a_fournir": []}},
        "")["conseil"]
    # La raison est recopiée dans le conseil, l'étape reste « attendre ».
    assert replanification.plan_de_secours(
        dossier, "créneau perdu")["conseil"].endswith(" : créneau perdu")


def test_le_module_replanification_est_pur():
    import ast

    src = Path(__file__).with_name("..").resolve() / "src" / "m4_field_ops" / "replanification.py"
    arbre = ast.parse((src).read_text(encoding="utf-8"))
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Import):
            for alias in noeud.names:
                assert alias.name in {"__future__", "typing"}, alias.name
        if isinstance(noeud, ast.ImportFrom):
            if noeud.level == 0 and noeud.module in {"__future__", "typing"}:
                continue
            assert noeud.level == 1 and {a.name for a in noeud.names} <= {
                "etats", "horodatage", "preparation", "verdicts"}, noeud.module
        if isinstance(noeud, ast.Attribute):
            assert noeud.attr not in {"ajouter", "append_maillon", "now", "utcnow", "today", "random"}
