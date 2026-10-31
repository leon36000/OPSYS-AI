"""D4 et « Matériaux » (DÉCISIONS-ARCHITECTE r1 §2) par la VRAIE porte d'appareil (moteur HTTP MCP, base temporaire).

Une journée d'ÉQUIPE dont les pointages V3 sont déclarés depuis l'app (`m4_declarer_pointage_equipe_appareil`) et
dont les matériaux sont déclarés par un MEMBRE de l'équipe (`m6_declarer_materiaux_utilises`) :

- les membres déclarés (Étienne, Julie) déclarent ; Marc, employé hors de l'équipe, est refusé partout ;
- l'identité vient du jeton d'appareil appairé : aucun champ de personne n'est accepté dans le corps ;
- rejeu d'une même clé d'appareil : même accusé ; même clé, autres arguments : conflit, rien d'écrit ;
- la projection M4 vérifiée identifie l'équipe, la présence individuelle reste inconnue ;
- le coût certifié en aval : avec les pointages déclarés par l'admin sur son appareil (preuve `admin`), le recalcul
  qualifié publie le coût complet. Avec ceux des membres (preuve `membre_equipe`), M5 ne certifie PAS encore
  (son validateur n'admet que `admin`) : le coût reste inconnu, jamais estimé — dépendance nommée dans le rapport.

Tout est fictif (`fictif: true`).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest
from harnais_e2e import iso
from harnais_e2e_chantier import (
    AppEmploye,
    debut_de_journee,
    png_minimal,
    preparer_chantier,
    receptionner_materiel_args,
)
from harnais_equipe_certifiee import (
    _cle,
    affecter_a_l_equipe,
    appel_porte,
    declarer_materiaux_comme_admin,
    declarer_profil,
    profil_equipes,
    recalcul_certifie_qa,
    revue_completion_verifiee,
    service_m4_et_tarif_fictifs,
)
from m4_field_ops import encodage, temps_certifies_v3, visites_ecriture
from m4_field_ops import outils as m4_outils
from m4_field_ops.registre import Registre
from sqlalchemy import select

from opsys import contexte, stockage
from opsys.stockage.schema import JOURNAL

FICTIF = True
SQLITE_SEULEMENT = pytest.mark.parametrize("moteur", ["sqlite"], indirect=True)
EQUIPE = "eq-declaration-appareil-fictive"
OUTIL = "m4_declarer_pointage_equipe_appareil"


def admin_console_contextes(instant):
    """Les contextes de la console admin (même patron que `harnais_equipe_certifiee.journee_equipe_certifiee`)."""
    return (contexte.appele_par_appareil(contexte.IdentiteAppelante("nathan", "admin", source="console")),
            contexte.appeler_en_tant_que("m04-field-ops", origine="console"),
            contexte.receptionne_de(contexte.HorodatageAppareil("console:nathan", instant, instant)))


def _ouvrir_visite(moteur: Any, admin: Any, chantier: Any, suffixe: str) -> str:
    """Cédule datée, visite prévue puis ouverte par l'admin sur la console (gestes déjà existants)."""
    with stockage.transaction():
        principal = Registre(stockage.maillons("m04-field-ops", "principal"))
        (application,) = [m for m in principal.lire() if m.get("type_entree") == "cedule_appliquee"]
    datee = appel_porte(moteur, admin, "m4_confirmer_dates_cedule", {
        "plan_id": application["plan_id"], "calendrier": {"0": chantier.debut.date().isoformat()},
        "revision_attendue": 0}, cle=_cle("date-equipe-appareil", suffixe))
    assert datee.metier["accepte"] is True, datee.corps
    with stockage.transaction():
        principal = Registre(stockage.maillons("m04-field-ops", "principal"))
        date = next(m for m in principal.lire() if m.get("ligne_id") == datee.resultat["ligne_id"])
    ancre = {"intervention_id": chantier.intervention_id, "plan_id": application["plan_id"],
             "source_application_id": date["source_application_id"], "source_ligne_id": date["ligne_id"]}
    instant = moteur.horloge.maintenant
    with stockage.transaction() as cnx:
        c1, c2, c3 = admin_console_contextes(instant)
        with c1, c2, c3:
            args = {"ancre": ancre, "revision_attendue": 0}
            recu = visites_ecriture.enregistrer(cnx, args, {"personne": "nathan", "role": "admin"}, {
                "appareil": "console:nathan", "cle": _cle("visite-equipe-appareil", suffixe),
                "empreinte_arguments": encodage.empreinte(args)}, instant.isoformat(), m4_outils._autoriser_annotation)
            ouvrir = {"operation": "ouvrir", "visite_id": recu["visite_id"],
                      "source_attendue": visites_ecriture.empreinte_sources(cnx)}
            visites_ecriture.executer_evenement(cnx, ouvrir, {"personne": "nathan", "role": "admin"}, {
                "appareil": "console:nathan", "cle": _cle("ouverture-equipe-appareil", suffixe),
                "empreinte_arguments": encodage.empreinte(ouvrir)}, instant.isoformat(),
                m4_outils._autoriser_annotation)
    return recu["visite_id"]


def _fermer_visite(moteur: Any, visite_id: str, suffixe: str) -> None:
    instant = moteur.horloge.maintenant
    with stockage.transaction() as cnx:
        c1, c2, c3 = admin_console_contextes(instant)
        with c1, c2, c3:
            fermer = {"operation": "fermer", "visite_id": visite_id,
                      "source_attendue": visites_ecriture.empreinte_sources(cnx)}
            visites_ecriture.executer_evenement(cnx, fermer, {"personne": "nathan", "role": "admin"}, {
                "appareil": "console:nathan", "cle": _cle("fermeture-equipe-appareil", suffixe),
                "empreinte_arguments": encodage.empreinte(fermer)}, instant.isoformat(),
                m4_outils._autoriser_annotation)


def _valider_revue_gps(moteur: Any, admin: Any, pointage_id: str, cle: str) -> None:
    """Un pointage d'équipe n'a pas de GPS : il part en revue, l'admin la résout (comme la console)."""
    with stockage.transaction():
        principal = Registre(stockage.maillons("m04-field-ops", "principal"))
        (demande,) = [m for m in principal.lire() if m.get("type_entree") == "demande_revue"
                      and m.get("pointage_ligne_id") == pointage_id]
    reponse = appel_porte(moteur, admin, "m4_resoudre_demande", {
        "demande_id": demande["demande_id"], "decision": "validee", "horodatage": iso(moteur.horloge.maintenant),
        "motif": "Contrôle fictif."}, cle=cle)
    assert reponse.metier["accepte"] is True, reponse.corps


def _declarer(porte: Any, moteur: Any, chantier: Any, action: str, cle: str, *, visite_id: str | None = None,
              equipe_id: str = EQUIPE, heure_appareil_s: int = -420) -> Any:
    reponse = porte.appeler(OUTIL, {
        "intervention_id": chantier.intervention_id, "visite_id": visite_id, "equipe_id": equipe_id,
        "action": action, "mutation_id": cle}, cle=cle, horodatage_appareil=iso(moteur.horloge.maintenant,
                                                                               heure_appareil_s))
    assert reponse.statut == 200 and not reponse.mesure.tronque, reponse.corps
    return reponse


def _sans_reclamations(etat):
    return {k: v for k, v in etat.items() if k != "mutations"}


def _journee(moteur, equipe, declarants, membre_materiaux, monkeypatch, tmp_path, suffixe):
    """La journée : `declarants` = (porte d'arrivée, porte de départ). Rend (chantier, wct_id, visite_id, marc)."""
    for personne in ("julie", "marc"):
        moteur.creer_personne(personne, f"{personne.capitalize()} (fictif)", ["employee"], monkeypatch)
    portes = {"julie": moteur.appairer("julie", "employee"), "marc": moteur.appairer("marc", "employee"),
              "etienne": equipe["employe"], "nathan": equipe["admin"]}
    admin = equipe["admin"]
    chantier = preparer_chantier(moteur.departements, suffixe=suffixe, technicien="etienne",
                                 debut=debut_de_journee(16))
    moteur.horloge.maintenant = chantier.debut
    moteur.drainer_bus(moteur.horloge.maintenant)
    reception = admin.appeler("m6_receptionner_commande", receptionner_materiel_args(chantier),
                              cle=f"mut-reception-{suffixe}", horodatage_appareil=iso(chantier.debut))
    assert reception.metier["accepte"] is True, reception.metier
    declarer_profil(tmp_path, "equipes", profil_equipes(EQUIPE, ["etienne", "julie"], {
        "gouttieres": {"duree_min": 90, "competences": ["gouttieres"]}}))
    affecter_a_l_equipe(moteur, admin, chantier, EQUIPE, suffixe=suffixe, arguments_cedule={
        "durees_par_type_travaux": {"renovation_totale": 90},
        "competences_par_type_travaux": {"renovation_totale": []},
        "chantiers": [{"intervention_id": chantier.intervention_id, "creneau_fige": None,
                       "fenetre": {"jours": [0], "debut_min": 480, "fin_min": 1020}}]})
    service_m4_et_tarif_fictifs(chantier, EQUIPE, suffixe=suffixe)
    app = AppEmploye(moteur, portes["etienne"], chantier, derive_appareil_s=0)
    visite_id = _ouvrir_visite(moteur, admin, chantier, suffixe)
    app.attendre(minutes=1)
    assert app.donner_consentement_gps().metier["accepte"] is True
    app.attendre(minutes=29)
    route = appel_porte(moteur, admin, "m4_demarrer_route", {
        "intervention_id": chantier.intervention_id, "technicien_id": EQUIPE,
        "horodatage": iso(moteur.horloge.maintenant)}, cle=_cle("route-equipe-appareil", suffixe))
    assert route.metier["accepte"] is True, route.corps
    app.attendre(minutes=30)

    # Marc n'est pas membre : refusé, rien d'écrit (seule la réclamation de sa clé d'appareil est gardée, pour qu'un
    # renvoi rende le même refus) ; un champ de personne dans le corps est refusé par le schéma.
    avant = _sans_reclamations(moteur.empreinte_etat())
    refus = _declarer(portes["marc"], moteur, chantier, "arrivee", f"marc-arrivee-{suffixe}")
    assert refus.metier["accepte"] is False and refus.metier["verdict"]["code"] == "REJ-EQUIPE-NON-MEMBRE"
    corps = portes["julie"].appeler(OUTIL, {
        "intervention_id": chantier.intervention_id, "visite_id": None, "equipe_id": EQUIPE, "action": "arrivee",
        "mutation_id": f"corps-{suffixe}", "personne": "julie"}, cle=f"corps-{suffixe}",
        horodatage_appareil=iso(moteur.horloge.maintenant))
    assert corps.statut != 200 or corps.corps.get("result", {}).get("ok") is False, corps.corps
    autre = _declarer(portes["julie"], moteur, chantier, "arrivee", f"autre-equipe-{suffixe}",
                      equipe_id="eq-inexistante-fictive")
    assert autre.metier["accepte"] is False
    assert _sans_reclamations(moteur.empreinte_etat()) == avant

    arrivee_porte, depart_porte = (portes[n] for n in declarants)
    arrivee = _declarer(arrivee_porte, moteur, chantier, "arrivee", f"arrivee-{suffixe}")
    assert arrivee.metier["accepte"] is True, arrivee.corps
    assert arrivee.resultat["visite_id"] == visite_id and arrivee.resultat["presence_individuelle"] == "inconnue"
    # L'heure du serveur fait foi (l'appareil, en retard de 7 minutes, est gardé à côté).
    assert dt.datetime.fromisoformat(arrivee.resultat["horodatage"]) == moteur.horloge.maintenant
    assert dt.datetime.fromisoformat(arrivee.resultat["horodatage_appareil"]) == (
        moteur.horloge.maintenant - dt.timedelta(minutes=7))
    # Renvoi de la même clé : même accusé, rien d'écrit ; même clé, autre action : conflit.
    etat = moteur.empreinte_etat()
    rejeu = _declarer(arrivee_porte, moteur, chantier, "arrivee", f"arrivee-{suffixe}")
    assert rejeu.enveloppe["rejoue"] is True and rejeu.resultat["preuve_id"] == arrivee.resultat["preuve_id"]
    conflit = _declarer(arrivee_porte, moteur, chantier, "depart", f"arrivee-{suffixe}")
    assert conflit.ok is False or conflit.enveloppe.get("ok") is False, conflit.corps
    assert moteur.empreinte_etat() == etat
    _valider_revue_gps(moteur, admin, arrivee.resultat["pointage_id"], _cle("revue-arrivee-appareil", suffixe))
    app.attendre(hours=2, minutes=55)
    photo = app.deposer_fichier(png_minimal(largeur=4))
    signature = app.deposer_fichier(png_minimal(largeur=2))
    app.attendre(minutes=5)
    depart = _declarer(depart_porte, moteur, chantier, "depart", f"depart-{suffixe}", visite_id=visite_id)
    assert depart.metier["accepte"] is True, depart.corps
    _valider_revue_gps(moteur, admin, depart.resultat["pointage_id"], _cle("revue-depart-appareil", suffixe))
    _fermer_visite(moteur, visite_id, suffixe)
    app.attendre(minutes=5)
    completion = app.terminer(photo, signature)
    wct_id = completion.resultat["wct_id"]
    moteur.drainer_bus(moteur.horloge.maintenant)
    app.attendre(minutes=5)

    # Matériaux : Marc (hors équipe) refusé ; le membre déclare depuis son téléphone, audit nominatif.
    formulaire = {"wct_id": wct_id, "formulaire": {
        "wct_id": wct_id, "intervention_id": chantier.intervention_id, "chantier_id": chantier.chantier_id,
        "lignes_materiaux": [{"type_ligne": "prevu", "materiau_id": "gouttiere-alu-5po-fictif", "quantite": 40.0,
                              "unite": "pi", "quantite_estimee": 40.0}]}}
    refus_marc = portes["marc"].appeler("m6_declarer_materiaux_utilises", formulaire, cle=f"mat-marc-{suffixe}",
                                        horodatage_appareil=iso(moteur.horloge.maintenant))
    assert refus_marc.metier["accepte"] is False
    assert refus_marc.metier["verdict"]["code"] == "REJ-INTERVENTION-NON-ASSIGNEE"
    if membre_materiaux is None:
        declaration = declarer_materiaux_comme_admin(moteur, admin, chantier, wct_id, 40.0, suffixe=suffixe)
    else:
        declaration = portes[membre_materiaux].appeler(
            "m6_declarer_materiaux_utilises", formulaire, cle=f"mat-{membre_materiaux}-{suffixe}",
            horodatage_appareil=iso(moteur.horloge.maintenant))
    assert declaration.metier["accepte"] is True, declaration.corps
    moteur.drainer_bus(moteur.horloge.maintenant)
    if app.statut().resultat["statut"] == "completed_pending_review":
        revue_completion_verifiee(moteur, admin, app, chantier, wct_id, suffixe=suffixe)
        moteur.drainer_bus(moteur.horloge.maintenant)
    return chantier, wct_id, visite_id


def _main_d_oeuvre_tracee():
    """La main-d'oeuvre de la dernière trace de rentabilité de M5 (après le recalcul qualifié)."""
    with stockage.transaction():
        derniere = list(stockage.maillons("m05-financecore", "rentabilite"))[-1]
    cout = derniere["rentabilite"]["cout_reel"]
    return cout["main_d_oeuvre"], cout["manque"]


def _projection(chantier, wct_id):
    with (stockage.transaction() as cnx,
          contexte.appele_par_appareil(contexte.IdentiteAppelante("nathan", "admin", source="console")),
          contexte.appeler_en_tant_que("m04-field-ops", origine="console")):
        return temps_certifies_v3.projeter(cnx, chantier.intervention_id, wct_id)["projection"]


@SQLITE_SEULEMENT
def test_admin_sur_son_appareil_et_materiaux_d_un_membre_donnent_le_cout_certifie(
        moteur, equipe, monkeypatch, tmp_path):
    chantier, wct_id, _ = _journee(moteur, equipe, ("nathan", "nathan"), "julie", monkeypatch, tmp_path, "eqadm")
    (visite,) = _projection(chantier, wct_id)["visites"]
    assert visite["equipe_pointee"]["statut"] == "identifiee"
    assert {p["auteur"]["role"] for p in visite["equipe_pointee"]["preuves"]} == {"admin"}
    assert visite["presence_individuelle"] == {"statut": "inconnue"}
    with stockage.transaction() as cnx:
        audits = cnx.execute(select(JOURNAL.c.par, JOURNAL.c.cible).where(
            JOURNAL.c.action == "m6.materiaux_declares_membre_equipe")).all()
    assert [tuple(a) for a in audits] == [("julie", wct_id)]
    recalcul_certifie_qa(chantier, wct_id, suffixe="eqadm")
    main_d_oeuvre, _ = _main_d_oeuvre_tracee()
    # 180 minutes d'équipe (arrivée 08 h, départ 11 h) au tarif d'équipe fictif de 50,00 $ l'heure.
    assert main_d_oeuvre["statut"] == "complet" and main_d_oeuvre["minutes"] == 180
    assert str(main_d_oeuvre["cout"]) == "150.00", main_d_oeuvre


@SQLITE_SEULEMENT
def test_pointages_des_membres_sur_l_appareil_identifient_l_equipe_et_m5_reste_ferme(
        moteur, equipe, monkeypatch, tmp_path):
    chantier, wct_id, _ = _journee(moteur, equipe, ("etienne", "julie"), "etienne", monkeypatch, tmp_path, "eqmbr")
    (visite,) = _projection(chantier, wct_id)["visites"]
    assert visite["equipe_pointee"]["statut"] == "identifiee"
    assert visite["equipe_pointee"]["identifiant"] == EQUIPE
    assert [p["auteur"] for p in visite["equipe_pointee"]["preuves"]] == [
        {"personne": "etienne", "role": "membre_equipe"}, {"personne": "julie", "role": "membre_equipe"}]
    assert visite["presence_individuelle"] == {"statut": "inconnue"}
    # Dépendance M5 : son validateur de projection n'admet encore que des preuves `admin`. Le recalcul qualifié trace
    # donc la main-d'oeuvre « non disponible, preuve de pointage invalide » : aucun coût certifié, jamais une
    # estimation, tant que M5 n'accepte pas `membre_equipe` (`validation_projection_visites`, une ligne).
    recalcul_certifie_qa(chantier, wct_id, suffixe="eqmbr")
    main_d_oeuvre, manques = _main_d_oeuvre_tracee()
    assert main_d_oeuvre["cout"] is None and main_d_oeuvre["statut"] == "non_disponible"
    assert {"code": "REJ-COUT-TEMPS-POINTE-ABSENT", "detail": "preuve de pointage invalide"} in manques
