"""P4-01, P4-02, P4-07 de bout en bout : la durée apprise de M3 arrive à la cédule de M4, un chantier de deux journées
est planifié pour la même équipe (absence respectée), et une fin de chantier à la preuve incomplète attend la revue.

VRAIS outils de M3, M4, M2, M5, M6 (et les consommateurs M7, M8, M10 du bus), vraie base SQLite migrée, vrai bus
(`evenements.repartir`), vraies approbations N4, vrai profil d'équipes (`entreprise.yaml`). Données FICTIVES
(`fictif: true`). Horloge INJECTÉE : chaque appel porte son horodatage, le répartiteur reçoit `maintenant`, la décision
d'approbation est figée. Sont simulés ici, et dits : les volets « matériel » et « météo » de la préparation (leurs
preuves
sont ailleurs) dans le scénario de cédule ; PyVRP (absent de la machine : le repli exact résout).

Les aides de deux autres fichiers de tests (la fabrique de chantiers apprenants de M3 et les étapes de la cascade
« travaux terminés ») sont chargées par chemin : ce sont les mêmes outils réels, pas des doublures.
"""

from __future__ import annotations

import copy
import datetime as dt
import importlib.util
import json
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from m4_field_ops import etats, preparation
from m4_field_ops import registre as registre_m4
from sqlalchemy import select

from opsys import approbations, evenements, identite, stockage, taxonomie
from opsys import equipes as equipes_entreprise
from opsys.departements import charger_departements
from opsys.outils import Niveau, executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS

FICTIF = True
RACINE = Path(__file__).resolve().parents[1]
M4 = "m04-field-ops"
EQUIPES_JSON = json.loads(
    (RACINE / "departments/m04-field-ops/tests/fixtures/equipes_repentigny_joliette.json").read_text(encoding="utf-8"))
SCENARIO = json.loads(
    (RACINE / "departments/m04-field-ops/tests/fixtures/scenario_cedule_repentigny_joliette.json").read_text(
        encoding="utf-8"))


def _charger(nom, chemin):
    specification = importlib.util.spec_from_file_location(nom, RACINE / chemin)
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


appr = _charger("m4d_appr_bout_en_bout", "departments/m03-estimation/tests/test_apprentissage_bout_en_bout.py")
casc = _charger("m4d_cascade_aide", "tests/test_cascade_travaux_termines.py")

PROPRIO = appr.OWNER
LEAD_TOIT = "L-E2E-01"                      # Repentigny (près du dépôt d'eq-a) ; service « renovation_totale »
LEAD_LEGACY = "L-E2E-02"                    # service « autre » : ni profil ni estimation
MOIS = date(2026, 1, 5)
HORLOGE = dt.datetime(2030, 1, 2, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=-5)))
HORODATAGE = "2030-01-01T00:00:00+00:00"
ADMIN = casc  # (les identités de l'appel d'appareil sont celles du dossier de tests du département M4)


# =============================================================================================
# Le monde : base, profil des équipes, politique d'apprentissage, M3 en mode supervisé
# =============================================================================================
def _profil(jours_a=(0, 1, 2, 3), consecutifs=False):
    """Deux équipes de deux membres, des quarts de 720 min (6 h à 18 h) ; une absence = pas de quart ce jour-là."""
    liste = []
    for identifiant, membres, depot, jours in (
        ("eq-a", ["luc.fictif", "marc.fictif"], ("depot-repentigny", 45735000, -73455000), jours_a),
        ("eq-b", ["nadia.fictif", "zoe.fictif"], ("depot-joliette", 46015000, -73445000), (0, 1, 2, 3)),
    ):
        liste.append({
            "id": identifiant, "membres": membres, "competences": [],
            "depot": {"id": depot[0], "latitude_microdegres": depot[1], "longitude_microdegres": depot[2]},
            "quarts": [{"jour": jour, "debut_min": 360, "fin_min": 1080} for jour in jours],
        })
    return equipes_entreprise.normaliser_equipes({
        "liste": liste,
        "services": {
            "renovation_totale": {"duree_min": 180, "competences": []},
            "extension": {"duree_min": 150, "competences": []},
        },
        "cedule": {"facteur_detour_milliemes": 1300, "vitesse_moyenne_kmh": 50, "marge_par_trajet_secondes": 600,
                   "iterations": 500, "cout_non_cedule_m": 500000,
                   "multijours": {"visite_max_minutes": 540, "jours_consecutifs": consecutifs}},
        "fenetre_par_defaut": {"jours": [0, 1, 2, 3], "debut_min": 360, "fin_min": 1080},
    })


def _declarer(profil):
    equipes_entreprise.enregistrer_equipes(profil, par="nathan")


@pytest.fixture
def monde(tmp_path, monkeypatch):
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    url = f"sqlite:///{tmp_path / 'm4-duree-multijours.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    taxonomie.enregistrer_services(EQUIPES_JSON["services_propres"])
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, PROPRIO, "Propriétaire fictif", "mot-de-passe-long-pour-fixture",
                                ["admin", "nathan_owner"])
        identite.creer_personne(cnx, "admin.fictif", "Admin Fictive", "mot-de-passe-admin-12345", ["admin"])
        identite.creer_personne(cnx, "gerant", "Une Gérante", "mot-de-passe-gerante-1234", ["manager"])
        for personne in ("luc.fictif", "marc.fictif", "nadia.fictif", "zoe.fictif"):
            identite.creer_personne(cnx, personne, personne.title(), "mot-de-passe-fictif-1234", ["employee"])
        approbations.fixer_mode(cnx, appr.M3, "supervise", PROPRIO)       # M3 SUPERVISÉ : l'apprentissage s'applique
    _declarer(_profil())
    politique = {**appr.POLITIQUE, "echantillon_minimum": 4, "echantillon_minimum_equipe": 3,
                "derive_fenetre": 4}
    monkeypatch.setattr(approbations, "_maintenant", lambda: "2026-03-16T10:00:00+00:00")
    monkeypatch.setattr(appr.adaptateur, "_politique_brute", lambda: copy.deepcopy(politique))
    yield tmp_path
    stockage.liberer()


@pytest.fixture
def futurs_ok(monkeypatch):
    """Simule le matériel (m6.materiel_pret) et la météo : deux volets de la préparation, prouvés ailleurs."""
    def ok(_registre, _inscription, _lire_position, _lire_equipes, _lire_meteo):
        return {"statut": "ok", "manque": None, "detail": "simulé par le test"}

    monkeypatch.setattr(preparation, "_VOLETS", tuple(
        (nom, ok if nom in ("materiel", "meteo") else fonction) for nom, fonction in preparation._VOLETS))


# =============================================================================================
# Aides communes
# =============================================================================================
def _par_nom(fab):
    return fab.par_nom


def _admin(par_nom, nom, arguments):
    """Un appel d'appareil de l'admin, l'heure du serveur faisant foi (comme l'app mobile)."""
    from opsys import contexte

    admin = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
    recu = dt.datetime(2030, 6, 2, 9, 0, 0, tzinfo=dt.UTC)
    with contexte.appele_par_appareil(admin), contexte.receptionne_de(contexte.HorodatageAppareil(
            appareil="tel-fictif-p4", horodatage_appareil=dt.datetime(2000, 1, 1, tzinfo=dt.UTC), recu_le=recu)):
        return executer_atomique(par_nom[nom], arguments)


def _ok(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _refus(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]


def _publier_lead_v2(lead_id):
    lead = next(item for item in SCENARIO["leads"] if item["lead_id"] == lead_id)
    evenements.publier(
        "m1.lead_qualifie", "m01-front-office",
        {"lead": {"schema_version": 2, "lead_id": lead_id, "conversation_id": f"sms-{lead_id}",
                  "contact": {"nom": "Client Fictif", "telephone": "+15145550142"}, "service": appr.TYPE_A,
                  "ville": lead["secteur"], "urgence_declaree": False, "canal": "texte", "source": "sms"},
         "horodatage": HORODATAGE, "signal_id": f"sms:{lead_id}"},
        evenement_id=f"m1-lead-qualifie-{lead_id}")


def _livrer_a_m4(deps, tours=3):
    total = {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0}
    for tour in range(tours):
        resume = evenements.repartir({M4: deps[M4]}, maintenant=(HORLOGE + timedelta(seconds=100 * tour)).isoformat())
        for cle in total:
            total[cle] += resume[cle]
    assert total["echecs"] == 0 and total["quarantaines"] == 0, total
    return total


def _confirmer_position(par_nom, lead_id):
    lead = next(item for item in SCENARIO["leads"] if item["lead_id"] == lead_id)
    _ok(_admin(par_nom, "m4_confirmer_localisation", {
        "chantier_id": lead_id, "action": "confirmee", "horodatage": HORODATAGE, "confirme_par": "admin.fictif",
        "adresse": {"numero_municipal": "10", "odonyme": "rue Fictive", "municipalite": lead["secteur"]},
        "source": "manuel", "motif": "", "latitude_microdegres": lead["latitude_microdegres"],
        "longitude_microdegres": lead["longitude_microdegres"]}))


def _registre_m4():
    return registre_m4.Registre(stockage.maillons(M4, "principal"))


def _devis_accepte_appris(fab, lead_id):
    """Une estimation M3 (la durée apprise y est appliquée), son devis, puis l'acceptation par un humain (T3) :
    publie `m3.devis_accepte`. Rend ``(estimation, devis_id)``."""
    with stockage.transaction():
        estimation = appr.estimer(fab, appr.TYPE_A, lead=lead_id)
    devis_id = estimation["estimation"]["devis_id"]
    source = estimation["estimation"]["hash_maillon"]
    fab._appel("m3_creer_devis", {
        "devis_id": devis_id, "estimation_source_hash": source, "lead_id": lead_id,
        "chantier_id": f"CHANTIER-{lead_id}",
        "lignes": [{"description": "Toiture complète (fictif)", "quantite": "28", "unite": "pi_lin",
                    "cout_unitaire": "12.00", "reference_besoin_materiau": None}],
        "taux_marge": "0.20", "horodatage": "2026-03-01T13:00:00Z"})
    fab._appel("m3_marquer_devis_accepte", {
        "devis_id": devis_id, "approbateur": "approbateur-fictif", "horodatage": "2026-03-01T14:00:00Z"})
    return estimation, devis_id


def _apprendre(fab):
    """Six chantiers terminés et vérifiés (~16 h sur site pour 28 pi_lin, barème 14 h) puis le calcul de M3 :
    la version apprise est appliquée automatiquement (mode supervisé)."""
    bruit = (0.99, 1.01, 1.0, 0.98, 1.02, 1.0)
    for position, facteur in enumerate(bruit):
        fab.creer(equipe="eq-nord", reel_minutes=round(960 * facteur), jour=MOIS + timedelta(days=position),
                  deplacement_minutes=20 + 7 * position)
    fab.livrer()
    resultat = appr.calculer(fab)
    cohorte = appr.cohorte(resultat, appr.TYPE_A)
    assert cohorte["active"] is True and cohorte["rapport"]["decision"] == "auto_applicable"
    return cohorte


# =============================================================================================
# 1. Devis appris de 16 h -> deux journées de la même équipe, absence respectée ; durée absente -> refus
# =============================================================================================
def test_devis_appris_de_16_h_deux_journees_de_la_meme_equipe_absence_respectee(monde, futurs_ok):
    fab = appr.Chantiers()
    cohorte = _apprendre(fab)
    version = cohorte["version_id"]
    deps = charger_departements()
    par_nom = _par_nom(fab)

    # -- M3 (supervisé) : l'estimation de ce devis porte la durée APPRISE, avec sa trace ------------------------
    estimation, devis_id = _devis_accepte_appris(fab, LEAD_TOIT)
    bloc = estimation["apprentissage_duree"]
    assert bloc["statut"] == "applique" and bloc["mode_activation"] == "auto" and bloc["version_id"] == version
    minutes_m3 = Decimal(estimation["duree_estimee_minutes"])
    assert 930 < minutes_m3 < 1010                                     # ~16 h, et non les 14 h (840) du barème
    attendu = int(minutes_m3.to_integral_value(rounding="ROUND_CEILING"))

    # -- le bus : le devis accepté porte la durée ET dit qu'une version apprise l'a corrigée -------------------
    with stockage.transaction() as cnx:
        charge = codec.decoder(cnx.execute(select(EVENEMENTS_SORTANTS.c.charge).where(
            EVENEMENTS_SORTANTS.c.type_evenement == "m3.devis_accepte",
            EVENEMENTS_SORTANTS.c.evenement_id == f"m3-devis-accepte-{devis_id}")).scalar_one())
    assert Decimal(charge["duree_estimee_minutes"]) == minutes_m3
    assert charge["semantique_temps"] == "duree_ecoulee_intervention"
    origine = charge["duree_origine"]
    assert origine["origine"] == "calibration" and origine["calibration_version_id"] == version
    assert Decimal(charge["duree_origine"]["taux_minutes_par_unite_source"]) == appr.TAUX_A

    # -- M4 reçoit le devis : l'intervention naît `a_planifier` et RETIENT la durée (jamais recalculée) ---------
    _publier_lead_v2(LEAD_TOIT)
    _livrer_a_m4(deps)
    with stockage.transaction():
        iid = next(ligne["intervention_id"]
                   for ligne in etats.lister_interventions(_registre_m4(), statut="a_planifier")
                   if ligne["lead_id"] == LEAD_TOIT)
        inscription = next(m for m in _registre_m4().lire()
                           if m["type_entree"] == "intervention_inscrite" and m["intervention_id"] == iid)
    assert inscription["duree_m3"]["statut"] == "retenue" and inscription["duree_m3"]["origine"] == "calibration"
    assert Decimal(inscription["duree_m3"]["minutes"]) == minutes_m3
    _confirmer_position(par_nom, LEAD_TOIT)

    # -- la préparation dit la durée, ses deux visites et la correction apprise -------------------------------
    verdict = _ok(_admin(par_nom, "m4_verifier_preparation", {"intervention_id": iid}))
    assert verdict["pret"] is True
    assert "corrigée par une version apprise appliquée" in verdict["volets"]["equipe"]["detail"]
    assert "2 visites" in verdict["volets"]["equipe"]["detail"]

    # -- variante 0 : tout le monde est là, journées non consécutives exigées -> eq-a (près du chantier), jours 0 et 1 -
    p0 = _ok(_admin(par_nom, "m4_proposer_cedule", {"horodatage": HORODATAGE, "intervention_ids": [iid]}))
    v0 = _visites(p0["plan"], iid)
    assert [v[1] for v in v0] == [0, 1] and {v[0] for v in v0} == {"eq-a"}

    # -- l'absence d'eq-a le jour 1 (aucun quart ce jour-là) change le plan : jamais une visite chez eq-a le jour 1 -
    _declarer(_profil(jours_a=(0, 2)))
    p1 = _ok(_admin(par_nom, "m4_proposer_cedule", {"horodatage": HORODATAGE, "intervention_ids": [iid]}))
    assert p1["plan_id"] != p0["plan_id"]
    v1 = _visites(p1["plan"], iid)
    assert {v[0] for v in v1} == {"eq-a"} and [v[1] for v in v1] == [0, 2]        # la MÊME équipe, 1 jour d'écart
    assert not any(r["equipe"] == "eq-a" and r["jour"] == 1 for r in p1["plan"])
    assert [v[3] - v[2] for v in v1] == [attendu // 2 + attendu % 2, attendu // 2]  # somme exacte, jamais arrondie
    duree = p1["durees"][iid]
    assert duree["minutes"] == attendu and duree["source"] == "estimation_m3" and duree["repli"] is False
    assert duree["origine_m3"] == "calibration" and duree["calibration_version_id"] == version
    assert sum(duree["visites"]) == attendu and len(duree["visites"]) == 2
    assert duree["ecart_profil_min"] == attendu - 180                           # le service du profil dit 180 min

    # -- journées consécutives exigées (surcharge) : eq-a (jours 0 et 2) ne l'est plus -> eq-b, en entier -----------
    p2 = _ok(_admin(par_nom, "m4_proposer_cedule", {
        "horodatage": HORODATAGE, "intervention_ids": [iid],
        "multijours": {"visite_max_minutes": 540, "jours_consecutifs": True}}))
    v2 = _visites(p2["plan"], iid)
    assert {v[0] for v in v2} == {"eq-b"} and [v[1] for v in v2] == [0, 1]
    assert p2["provenance"]["multijours"] == "surcharge"

    # -- rien n'est encore assigné ni promis : une proposition est un brouillon -----------------------------------
    assert etats_courant(iid) == "a_planifier"
    evenements_client = _evenements_de_types("m4.message_client_brouillon_pret", "m1.brouillon_courriel_pret")
    assert evenements_client == []

    # -- application (N3, par une personne) : UNE assignation, UN passage à planifiee, deux visites ----------------
    application = _ok(_admin(par_nom, "m4_appliquer_cedule", {
        "plan_id": p1["plan_id"], "horodatage": HORODATAGE, "confirme_par": "admin.fictif"}))
    assignation = next(a for a in application["assignations"] if a["intervention_id"] == iid)
    assert assignation["technicien_id"] == "eq-a" and assignation["visites"] == 2
    assert etats_courant(iid) == "planifiee"
    with stockage.transaction():
        maillons = _registre_m4().lire()
    assert len([m for m in maillons if m["type_entree"] == "assignation_technicien" and m["intervention_id"] == iid
                and m["technicien_id"] == "eq-a"]) == 1
    assert len([m for m in maillons if m["type_entree"] == "transition_statut" and m["intervention_id"] == iid
                and m["statut"] == "planifiee"]) == 1

    # -- les dates civiles restent une décision : l'admin date les deux journées, jour par jour ------------------
    confirmation = _ok(_admin(par_nom, "m4_confirmer_dates_cedule", {
        "plan_id": p1["plan_id"], "calendrier": {"0": "2030-06-03", "2": "2030-06-05"}, "revision_attendue": 0}))
    assert confirmation["calendrier"] == {"0": "2030-06-03", "2": "2030-06-05"}
    semaine = _ok(_admin(par_nom, "m4_lire_cedule_semaine", {"debut_semaine": "2030-06-03"}))
    lignes = [ligne for ligne in semaine["interventions"] if ligne["intervention_id"] == iid]
    assert [ligne["debut"][:10] for ligne in lignes] == ["2030-06-03", "2030-06-05"]
    assert {ligne["validite"] for ligne in lignes} == {"date_confirmee"}
    assert {ligne["equipe_id"] for ligne in lignes} == {"eq-a"}
    # sans promettre de date au client : aucun message préparé, aucun brouillon M1
    assert _evenements_de_types("m4.message_client_brouillon_pret", "m1.brouillon_courriel_pret") == []


def etats_courant(intervention_id):
    with stockage.transaction():
        return etats.statut_courant(_registre_m4(), intervention_id)


def _evenements_de_types(*types):
    with stockage.transaction() as cnx:
        return cnx.execute(select(EVENEMENTS_SORTANTS.c.evenement_id).where(
            EVENEMENTS_SORTANTS.c.type_evenement.in_(types))).all()


def _visites(plan, intervention_id):
    return sorted(((r["equipe"], r["jour"], v["debut_min"], v["fin_min"]) for r in plan for v in r["visites"]
                   if v["chantier"] == intervention_id), key=lambda t:
                   t[1])


def test_duree_absente_refus_lisible_et_estimation_non_retenue_repli_dit(monde, futurs_ok):
    """Sans estimation M3 retenue ni durée déclarée : « durée à déclarer » (jamais une durée inventée) ; avec la
    durée du service seulement : un repli explicite, dit avec sa raison."""
    fab = appr.Chantiers()
    deps = charger_departements()
    par_nom = _par_nom(fab)
    # (a) un devis accepté SANS durée (barème sans durée de M3) : repli sur la durée du service, dit
    _publier_lead_v2("L-E2E-03")
    evenements.publier("m3.devis_accepte", "m03-estimation", {
        "devis_id": "DEVIS-SANS-DUREE", "lead_id": "L-E2E-03", "chantier_id": None,
        "lignes": [{"reference_ligne": "DEVIS-SANS-DUREE-L0", "description": "Travaux (fictif)", "quantite": "1",
                    "unite": "forfait", "prix_unitaire": "100.00", "prix_ligne": "100.00",
                    "reference_besoin_materiau": None}],
        "cout_total": "80.00", "prix_total": "100.00", "taux_marge": "0.25",
        "horodatage_acceptation": "2030-01-01T10:00:00-05:00"},
        evenement_id="m3-devis-accepte-DEVIS-SANS-DUREE")
    _livrer_a_m4(deps)
    with stockage.transaction():
        iid = next(ligne["intervention_id"]
                   for ligne in etats.lister_interventions(_registre_m4(), statut="a_planifier")
                   if ligne["lead_id"] == "L-E2E-03")
    _confirmer_position(par_nom, "L-E2E-03")
    proposition = _ok(_admin(par_nom, "m4_proposer_cedule", {"horodatage": HORODATAGE, "intervention_ids": [iid]}))
    bloc = proposition["durees"][iid]
    assert bloc["source"] == "profil_service" and bloc["repli"] is True and bloc["minutes"] == 180
    assert "ne porte aucune durée" in bloc["raison_repli"] and "REPLI" in bloc["libelle"]

    # (b) ni estimation ni durée de service (service « autre » absent du profil) : refus lisible, rien n'est rangé
    plan = executer_atomique(par_nom["m4_planifier_intervention"], {
        "contrat": {"lead_id": LEAD_LEGACY, "conversation_id": "C-LEG", "type_travaux": "autre", "ville": "Le Gardeur",
                    "canal": "telephone", "contact": {"nom": "Client Fictif"}, "urgence_declaree": False},
        "marqueur": {"readiness_ok": True, "lead_id": LEAD_LEGACY, "hash_tete_registre": None,
                     "horodatage": HORODATAGE, "empreinte": "ab" * 32},
        "horodatage": HORODATAGE, "sel": "sel-fictif", "techniciens_disponibles": ["eq-a"],
        "fenetres_disponibles": [{"debut": "2030-01-07T08:00:00-05:00", "fin": "2030-01-07T17:00:00-05:00"}]})
    legacy = plan["resultat"]["intervention_id"]
    avant = len([m for m in _registre_m4_lire() if m["type_entree"] == "cedule_proposee"])
    refus = _refus(_admin(par_nom, "m4_proposer_cedule", {"horodatage": HORODATAGE, "intervention_ids": [legacy]}))
    assert refus["code"] == "REJ-CHAMP-MANQUANT" and "durée à déclarer" in refus["detail"]
    assert legacy in refus["detail"] and "jamais une durée par défaut" in refus["detail"]
    assert len([m for m in _registre_m4_lire() if m["type_entree"] == "cedule_proposee"]) == avant


def _registre_m4_lire():
    with stockage.transaction():
        return _registre_m4().lire()


# =============================================================================================
# 2. Fin de chantier à la preuve incomplète : attente de revue, rien de facturé ; revue approuvée -> cascade complète
# =============================================================================================
base_durable = casc.base_durable
RESERVES = ["liste_controle_incomplete", "photos_apres_manquantes", "materiel_ecarte_non_documente"]
CONSOMMATEURS = ("m02-revenue-crm", "m03-estimation", "m05-financecore", "m06-material-control", "m07-marketing",
                 "m08-analytics", "m10-memoire")


def _m5_attentes(m5):
    reponse = executer_atomique(m5["m5_lister_attentes_facturation"], {})
    assert reponse["ok"] is True, reponse
    return reponse["resultat"]


def test_preuve_incomplete_attente_de_revue_rien_facture_puis_revue_approuvee_cascade_complete(base_durable):
    deps = charger_departements()
    m2, m3, m4, m5, m6 = (casc._outils(deps, d) for d in (
        "m02-revenue-crm", "m03-estimation", "m04-field-ops", "m05-financecore", "m06-material-control"))
    base = dt.datetime(2026, 9, 15, 7, 0, 0, tzinfo=casc.DT_TZ)
    lead_id, devis_id, chantier_id = "LEAD-RES-1-fictif", "DEVIS-RES-1-fictif", "CH-RES-1-fictif"
    marqueur = casc._m2_amener_pret_pour_readiness(m2, lead_id, base)
    casc._m3_creer_devis(m3, devis_id, lead_id, chantier_id, base)
    casc._m2_transitionner(m2, lead_id, "converti", base, 300, reference_devis_m3=devis_id)
    casc._m3_accepter_devis(m3, devis_id, base)
    casc._m2_transitionner(m2, lead_id, "cedule", base, 660)
    intervention_id = casc._m4_planifier_router_pointer(m4, casc._contrat(lead_id), marqueur, devis_id, base)
    casc._m2_transitionner(m2, lead_id, "chantier", base, 840)
    casc._m6_receptionner(m6, chantier_id, casc.MATERIAU_ID, 200.0, f"PO-{devis_id}", base)

    # -- fin de chantier AVEC RÉSERVES : liste de contrôle non terminée, aucune photo, matériel écarté non documenté ---
    avant_drainage = casc._drainer(deps, base + dt.timedelta(hours=2))
    assert avant_drainage["echecs"] == 0
    reponse = executer_atomique(m4["m4_completer_intervention"], {
        "intervention_id": intervention_id, "horodatage": casc._iso(base, 11400),
        "preuves_completion": {"checklist_complete": False, "photos_apres": [], "signature": None,
                               "notes": "Pluie en fin de journée : liste inachevée, aucune photo, chutes jetées "
                                        "au conteneur sans photo (fictif)."},
        "reserves": RESERVES})
    accuse = _ok(reponse)
    wct_id = accuse["wct_id"]
    assert accuse["statut"] == "completed_pending_review" and accuse["reserves"] == sorted(RESERVES)
    assert accuse["cascade"]["etat"] == "differee_jusqu_a_la_revue" and accuse["cascade"]["evenement_publie"] is False
    assert list(accuse["reserves_par_categorie"]) == ["liste_controle", "preuve_photo", "materiel"]

    # -- le bus tourne : RIEN n'est parti vers aucun département -----------------------------------------------------
    total = casc._drainer(deps, base + dt.timedelta(hours=4))
    assert total["echecs"] == 0 and total["quarantaines"] == 0 and total["livres"] == 0, total
    assert _evenements_de_types("m4.travaux_termines") == []
    for consommateur in CONSOMMATEURS:
        assert casc._recu(wct_id, consommateur) is None, consommateur
    assert casc._facture_active(devis_id) is None                              # rien de facturé, pas même un brouillon
    assert not [m for m in stockage.maillons("m05-financecore", "wct_recus") if m.get("wct_id") == wct_id]
    assert not [m for m in stockage.maillons("m06-material-control", "wct_recus") if m.get("wct_id") == wct_id]
    assert not [m for m in stockage.maillons("m10-memoire", "evenements") if m.get("wct_id") == wct_id]
    assert not [m for m in stockage.maillons("m08-analytics", "snapshots")
                if m.get("module_source") == "m04-field-ops" and m["valeurs"].get("m4_wct_id") == wct_id]
    from m2_revenue_crm import statuts as m2_statuts
    assert m2_statuts.statut_courant(casc._m2_registre(), lead_id) == "chantier"        # pas « facture »
    assert list(stockage.maillons("m07-marketing", "demandes_avis")) == []
    attentes = _m5_attentes(m5)
    # M5 attend toujours les travaux
    assert devis_id in json.dumps(attentes, ensure_ascii=False)
    # M6 ne connaît pas ce WCT : le formulaire de matériaux n'est pas ouvert avant la revue
    refus_m6 = executer_atomique(m6["m6_declarer_materiaux_utilises"], {
        "wct_id": wct_id, "formulaire": {
            "wct_id": wct_id, "intervention_id": intervention_id, "chantier_id": chantier_id,
            "lignes_materiaux": [{"type_ligne": "prevu", "materiau_id": casc.MATERIAU_ID, "quantite": 40.0,
                                  "unite": "pi", "quantite_estimee": 40.0}]}})
    assert refus_m6["resultat"]["accepte"] is False
    statut = executer_atomique(m4["m4_statut_intervention"], {"intervention_id": intervention_id})
    assert statut["resultat"]["statut"] == "completed_pending_review"

    # -- la file du propriétaire : réserves nommées, cascade différée ------------------------------------------------
    with stockage.transaction() as cnx:
        file = approbations.file_proprietaire(cnx, {M4: deps[M4]})
    [item] = [i for i in file if i["id"] == intervention_id]
    assert "AVEC RÉSERVES" in item["resume"] and "rien n'est parti" in item["resume"]

    # -- une revue qui ne nomme pas toutes les réserves n'exécute rien ----------------------------------------------
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "gerant", "Une Gérante", "mot-de-passe-gerante-1234", ["manager"])
        mauvaise = approbations.creer_demande(cnx, M4, "m4_resoudre_revue_completion", {
            "intervention_id": intervention_id, "decision": "verifiee", "horodatage": casc._iso(base, 12000),
            "motif": "Vu sur place.", "reserves_acceptees": ["liste_controle_incomplete"]}, niveau=Niveau.N4)
        refusee = approbations.decider(cnx, mauvaise, True, "gerant", m4, {M4: deps[M4]})
    assert refusee["reponse"]["resultat"]["verdict"]["code"] == "REJ-RESERVES-NON-ACCEPTEES"
    assert _evenements_de_types("m4.travaux_termines") == []

    # -- revue HUMAINE approuvée, réserves nommées exactement : la cascade part, complète -----------------------------
    with stockage.transaction() as cnx:
        demande = approbations.creer_demande(cnx, M4, "m4_resoudre_revue_completion", {
            "intervention_id": intervention_id, "decision": "verifiee", "horodatage": casc._iso(base, 12000),
            "motif": "Chantier vu par la gérante : reprises photographiées, chutes comptées.",
            "reserves_acceptees": sorted(RESERVES)}, niveau=Niveau.N4)
        decision = approbations.decider(cnx, demande, True, "gerant", m4, {M4: deps[M4]}, motif="Revue faite.")
    assert decision["statut"] == "executee", decision
    revue = decision["reponse"]["resultat"]["resultat"]
    assert revue["statut"] == "completed_verified" and revue["wct_id"] == wct_id
    assert revue["cascade"]["etat"] == "declenchee_apres_revue" and revue["cascade"]["evenement_publie"] is True
    assert revue["cascade"]["cout_reel"] == "provisoire" and "matériel" in revue["cascade"]["note"]
    assert revue["reserves"] == revue["reserves_acceptees"] == sorted(RESERVES)

    # le WCT publié est celui de la complétion, intact (13 clés requises, aucune réserve dedans)
    charge = casc._charge_publiee("m4.travaux_termines", wct_id)
    assert charge["intervention_id"] == intervention_id and charge["statut"] == "completed_pending_review"
    assert not any("reserve" in cle for cle in charge)

    casc._m6_declarer(m6, wct_id, chantier_id, casc.MATERIAU_ID, 40.0)
    total = casc._drainer(deps, base + dt.timedelta(hours=6))
    assert total["echecs"] == 0 and total["quarantaines"] == 0, total
    for consommateur in CONSOMMATEURS:
        recu = casc._recu(wct_id, consommateur)
        assert recu is not None and recu["statut"] == "traite", (consommateur, recu)
    facture = casc._facture_active(devis_id)
    # un brouillon, que valide une personne
    assert facture is not None and facture["statut"] == "BROUILLON"
    assert facture["montant_apres_taxes"] == Decimal("689.85")
    assert m2_statuts.statut_courant(casc._m2_registre(), lead_id) == "facture"
    assert [m for m in stockage.maillons("m10-memoire", "evenements") if m.get("wct_id") == wct_id]
    assert [m for m in stockage.maillons("m06-material-control", "wct_recus") if m.get("wct_id") == wct_id]
    variance = casc._charge_publiee("m6.variance_chantier", f"m6-variance-{wct_id}-evaluee")
    assert variance["statut_variance"] == "evaluee" and variance["signal_critique"] is False
    statut = executer_atomique(m4["m4_statut_intervention"], {"intervention_id": intervention_id})
    assert statut["resultat"]["statut"] == "completed_verified"
    with stockage.transaction():
        reg = _registre_m4()
        from m4_field_ops import outbox
        assert outbox.verifier_invariants_outbox(reg) == (True, "")
        assert reg.valider_chaine()
