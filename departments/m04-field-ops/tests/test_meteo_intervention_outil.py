"""PLAN T4.27-a : `m4_lire_meteo_intervention`, de bout en bout, sur les VRAIS outils, le VRAI bus, les VRAIS fichiers
`entreprise.yaml` (équipes et météo, déclarés par `opsys-metier equipes declarer` et `opsys-metier meteo declarer`) et
une base SQLite migrée. Aucun réseau (sockets bloqués : un fournisseur est injecté ou aucun n'est ouvert).

`m4_verifier_meteo_creneau` exige le `plan_id` d'un plan PROPOSÉ (`m4_proposer_cedule` écrit un maillon) : l'app du
propriétaire ne pouvait pas lire la météo d'un chantier sans écrire. `m4_lire_meteo_intervention` lit le créneau d'UNE
intervention que le dernier plan APPLIQUÉ lui a donné, sans `plan_id`, et ne fait que lire.

Le trajet : trois devis acceptés (deux ravalements, une réparation « autre »), les adresses confirmées, un plan proposé
par `m4_proposer_cedule`, puis APPLIQUÉ par l'admin (N3) : les trois interventions sont planifiées. Alors :

  * une prévision saisie calme : `ok` ; de vent fort le jour du créneau : `bloquant`, citée (source, auteur, heure
    d'émission) ; sans prévision ni fournisseur ouvert, sans date, avec un fournisseur en panne : `inconnu`, jamais
    `ok` ;
  * le créneau rendu est celui que `m4_verifier_meteo_creneau` rend pour le même plan, la même date et la même
    prévision ;
  * avant l'application du plan, aucune intervention n'a de créneau : `creneaux` vide, `inconnu`, la cause dite ;
  * la lecture n'écrit rien, ne change aucun statut, ne propose ni report ni cédule ; l'employé, le vendeur et une
    identité non confirmée sont refusés dans le code.

Données fictives (`fictif: true`) : personnes, adresses, prévisions et seuils de test, aucune entreprise réelle.
"""

from __future__ import annotations

import contextlib
import copy
import datetime as dt
import json
import socket
from pathlib import Path

import pytest
import yaml
from m4_field_ops import etats
from m4_field_ops import outils as outils_m4
from m4_field_ops import registre as registre_m4
from m4_field_ops.meteo import CODE_FOURNISSEUR_INDISPONIBLE
from m4_field_ops.outils import outils

from opsys import cli, contexte, evenements, identite, jetons, politiques, stockage, taxonomie
from opsys import meteo as meteo_entreprise
from opsys.departements import charger_departements
from opsys.outils import executer_atomique

FICTIF = True
_FIXTURES = Path(__file__).parent / "fixtures"
SCENARIO = json.loads((_FIXTURES / "scenario_cedule_repentigny_joliette.json").read_text(encoding="utf-8"))
EQUIPES = json.loads((_FIXTURES / "equipes_repentigny_joliette.json").read_text(encoding="utf-8"))
M4, M6 = "m04-field-ops", "m06-material-control"
HORODATAGE = "2030-01-01T00:00:00+00:00"
ACCEPTE_LE = "2030-01-01T10:00:00-05:00"
DEBUT_BUS = dt.datetime(2030, 1, 2, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=-5)))
LEADS_DU_TEST = ("L-E2E-01", "L-E2E-02", "L-E2E-10")  # ravalement, autre, ravalement
LEADS = {lead["lead_id"]: lead for lead in SCENARIO["leads"]}
ADMIN = contexte.IdentiteAppelante(personne="admin.fictif", role="admin")
EMPLOYE = contexte.IdentiteAppelante(personne="luc.fictif", role="employee")
VENDEUR = contexte.IdentiteAppelante(personne="vendeur.fictif", role="seller")
INCONNUE = contexte.IdentiteAppelante(personne="fantome.fictif", role="admin")
CALENDRIER = {0: "2026-10-05", 1: "2026-10-06"}
PERSONNES = (
    ("admin.fictif", ["admin"]),
    ("luc.fictif", ["employee"]),
    ("marc.fictif", ["employee"]),
    ("nadia.fictif", ["employee"]),
    ("vendeur.fictif", ["seller"]),
)
CALME = {
    "temperature_c": 12,
    "vent_kmh": 10,
    "rafales_kmh": 20,
    "precipitation_mm_h": 0,
    "probabilite_precipitation_pct": 10,
    "verglas": False,
}
METEO = {
    "fuseau": "America/Toronto",
    "services": {
        "ravalement": {
            "seuils": {
                "vent_kmh": {"validation": 25, "blocage": 40},
                "pluie_mm_h": {"blocage": 3},
                "gel_c": {"blocage": 0},
                "verglas": {"blocage": True},
                "chaleur_c": {"blocage": 35},
            }
        },
        "autre": {"seuils": {"vent_kmh": {"blocage": 60}}, "sans_objet": ["pluie", "gel", "verglas", "chaleur"]},
        "extension": {"sans_objet": list(meteo_entreprise.RISQUES)},
        "isolation_thermique": {"sans_objet": list(meteo_entreprise.RISQUES)},
        "renovation_totale": {"sans_objet": list(meteo_entreprise.RISQUES)},
    },
}


# -- installation -----------------------------------------------------------------------------------
@pytest.fixture
def instance(tmp_path, monkeypatch):
    (tmp_path / "home").mkdir()
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    taxonomie.enregistrer_services(EQUIPES["services_propres"])
    with stockage.transaction() as cnx:
        for identifiant, roles in PERSONNES:
            identite.creer_personne(cnx, identifiant, identifiant.title(), "mot-de-passe-fictif-1234", roles)
    yield tmp_path
    stockage.liberer()


@pytest.fixture(autouse=True)
def _sans_reseau(sockets_bloques):
    """Ce module n'ouvre jamais un socket : un fournisseur en panne est INJECTÉ, jamais une vraie connexion coupée."""


@pytest.fixture
def par_nom(instance):
    return {o.nom: o for o in outils()}


def _appeler(par_nom, nom, arguments, identite_appelante=ADMIN):
    """Un appel d'appareil sous `identite_appelante` ; `None` : un appel d'agent, sans identité d'appareil."""
    with contexte.appele_par_appareil(identite_appelante) if identite_appelante else contextlib.nullcontext():
        return executer_atomique(par_nom[nom], arguments)


def _resultat(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    return reponse["resultat"]["resultat"]


def _code_refus(reponse):
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, reponse
    return reponse["resultat"]["verdict"]["code"]


def _maillons():
    with stockage.transaction():
        return registre_m4.Registre(stockage.maillons(M4, "principal")).lire()


def _octets(objet) -> str:
    return json.dumps(objet, sort_keys=True, ensure_ascii=False)


def _declarer(dossier: Path, commande: str, profil: dict) -> None:
    fichier = dossier / f"{commande}-declare.yaml"
    fichier.write_text(yaml.safe_dump(profil, allow_unicode=True), encoding="utf-8")
    assert cli.main([commande, "declarer", "--depuis", str(fichier), "--par", "nathan"]) == 0


def _profil_equipes_deux_jours() -> dict:
    profil = copy.deepcopy(EQUIPES["profil"])
    for equipe in profil["liste"]:
        equipe["quarts"] = [{"jour": jour, "debut_min": 480, "fin_min": 1020} for jour in (0, 1)]
    profil["fenetre_par_defaut"]["jours"] = [0, 1]
    return profil


def _charge_pret(devis_id):
    ligne = {
        "materiau_id": "gouttiere-fictive",
        "unite": "pi",
        "quantite_besoin": "10",
        "quantite_reservee": "10",
        "quantite_manquante": "0",
    }
    return {
        "evenement_id": f"m6-materiel-pret-{devis_id}-1",
        "devis_id": devis_id,
        "chantier_id": None,
        "revision": 1,
        "statut": "pret",
        "reservation_active": True,
        "declencheur": "devis_accepte",
        "horodatage": "2030-01-01T12:00:00-05:00",
        "lignes": [ligne],
        "lignes_manquantes": [],
    }


def _naitre(leads=LEADS_DU_TEST) -> dict[str, str]:
    """Un devis accepté et sa charge de matériel prêt par lead : ``{lead_id: intervention_id}``."""
    for lead_id in leads:
        lead = LEADS[lead_id]
        evenements.publier(
            "m1.lead_qualifie",
            "m01-front-office",
            {
                "lead": {
                    "schema_version": 2,
                    "lead_id": lead_id,
                    "conversation_id": f"sms-{lead_id}",
                    "contact": {"nom": "Client Fictif", "telephone": "+15145550142"},
                    "service": lead["type_travaux"],
                    "ville": lead["secteur"],
                    "urgence_declaree": False,
                    "canal": "texte",
                    "source": "sms",
                },
                "horodatage": HORODATAGE,
                "signal_id": f"sms:{lead_id}",
            },
            evenement_id=f"m1-lead-qualifie-{lead_id}",
        )
        devis_id = f"DEVIS-{lead_id}"
        evenements.publier(
            "m3.devis_accepte",
            "m03-estimation",
            {
                "devis_id": devis_id,
                "lead_id": lead_id,
                "chantier_id": None,
                "lignes": [
                    {
                        "reference_ligne": f"{devis_id}-L0",
                        "description": "Travaux (fictif)",
                        "quantite": "1",
                        "unite": "forfait",
                        "prix_unitaire": "100.00",
                        "prix_ligne": "100.00",
                        "reference_besoin_materiau": None,
                    }
                ],
                "cout_total": "80.00",
                "prix_total": "100.00",
                "taux_marge": "0.25",
                "horodatage_acceptation": ACCEPTE_LE,
            },
            evenement_id=f"m3-devis-accepte-{devis_id}",
        )
        evenements.publier(
            "m6.materiel_pret", M6, _charge_pret(devis_id), evenement_id=_charge_pret(devis_id)["evenement_id"]
        )
    deps = {M4: charger_departements()[M4]}
    total = {"livres": 0, "echecs": 0, "quarantaines": 0}
    for tour in range(4):
        resume = evenements.repartir(deps, maintenant=(DEBUT_BUS + dt.timedelta(seconds=100 * tour)).isoformat())
        for cle in total:
            total[cle] += resume[cle]
    assert total["echecs"] == 0 and total["quarantaines"] == 0 and total["livres"] == 2 * len(leads), total
    with stockage.transaction():
        liste = etats.lister_interventions(
            registre_m4.Registre(stockage.maillons(M4, "principal")), statut="a_planifier"
        )
    par_lead = {ligne["lead_id"]: ligne["intervention_id"] for ligne in liste}
    assert sorted(par_lead) == sorted(leads)
    return par_lead


def _confirmer_les_positions(par_nom, leads=LEADS_DU_TEST) -> None:
    for lead_id in leads:
        lead = LEADS[lead_id]
        _resultat(
            _appeler(
                par_nom,
                "m4_confirmer_localisation",
                {
                    "chantier_id": lead_id,
                    "action": "confirmee",
                    "horodatage": HORODATAGE,
                    "confirme_par": "admin.fictif",
                    "adresse": {"numero_municipal": "10", "odonyme": "rue Fictive", "municipalite": lead["secteur"]},
                    "source": "manuel",
                    "motif": "",
                    "latitude_microdegres": lead["latitude_microdegres"],
                    "longitude_microdegres": lead["longitude_microdegres"],
                },
            )
        )


@pytest.fixture
def monde_propose(instance, par_nom):
    """Profils déclarés, trois interventions prêtes, adresses confirmées, un plan PROPOSÉ (jamais appliqué)."""
    _declarer(instance, "equipes", _profil_equipes_deux_jours())
    _declarer(instance, "meteo", METEO)
    interventions = _naitre()
    _confirmer_les_positions(par_nom)
    proposition = _resultat(_appeler(par_nom, "m4_proposer_cedule", {"horodatage": HORODATAGE}))
    assert proposition["non_cedulees"] == [] and proposition["non_pretes"] == []
    visites = {
        v["chantier"]: (r["jour"], v["debut_min"], v["fin_min"]) for r in proposition["plan"] for v in r["visites"]
    }
    assert sorted(visites) == sorted(interventions.values())
    return {"interventions": interventions, "plan_id": proposition["plan_id"], "visites": visites}


@pytest.fixture
def monde(par_nom, monde_propose):
    """Le même plan, APPLIQUÉ par l'admin (N3, sous son nom) : les trois interventions sont planifiées."""
    application = _resultat(
        _appeler(
            par_nom,
            "m4_appliquer_cedule",
            {"plan_id": monde_propose["plan_id"], "horodatage": HORODATAGE, "confirme_par": "admin.fictif"},
        )
    )
    assert {a["intervention_id"] for a in application["assignations"]} == set(monde_propose["interventions"].values())
    return monde_propose


# -- prévisions saisies -----------------------------------------------------------------------------
def _saisie(auteur="admin.fictif", dates_vent_fort=(), vent=55):
    points = []
    for date in CALENDRIER.values():
        for heure in range(6, 21):
            point = {**CALME, "heure": f"{date}T{heure:02d}:00"}
            if date in dates_vent_fort:
                point["vent_kmh"] = vent
            points.append(point)
    return {
        "saisi_par": auteur,
        "source": "Bulletin fictif du 4 octobre, 18 h",
        "emise_le": "2026-10-04T18:00:00-04:00",
        "points": points,
    }


def _lire(par_nom, intervention_id, date=None, saisie=None, identite_appelante=ADMIN):
    arguments = {"intervention_id": intervention_id}
    if date is not None:
        arguments["date"] = date
    if saisie is not None:
        arguments["previsions_saisies"] = saisie
    return _appeler(par_nom, "m4_lire_meteo_intervention", arguments, identite_appelante)


def _date_de(monde, intervention_id):
    return CALENDRIER[monde["visites"][intervention_id][0]]


# =========================================================================================
# 1. L'outil : T0, réservé à l'admin, décrit
# =========================================================================================
def test_l_outil_est_de_lecture_t0_reserve_a_l_admin_et_sa_description_tient_dans_la_limite(par_nom):
    outil = par_nom["m4_lire_meteo_intervention"]
    assert outil.autonomie.name == "T0" and outil.roles_appareil == frozenset({"admin"})
    assert not politiques.approbation_requise_niveau(outil.niveau_effectif, "ombre")
    assert len(outil.description) <= 1024
    assert outil.parametres["required"] == ["intervention_id"]
    assert set(outil.parametres["properties"]) == {"intervention_id", "date", "previsions_saisies"}
    assert outil.parametres["additionalProperties"] is False
    assert "plan_id" in outil.description and "APPLIQUÉ" in outil.description and "JAMAIS ok" in outil.description
    assert "Réservé à l'admin" in outil.description and "N'écrit rien" in outil.description


def test_l_outil_est_le_dernier_de_la_liste_et_ne_remplace_pas_celui_du_plan(par_nom):
    noms = list(par_nom)
    assert "m4_verifier_meteo_creneau" in noms and noms.index("m4_lire_meteo_intervention") > noms.index(
        "m4_verifier_meteo_creneau"
    )
    assert par_nom["m4_verifier_meteo_creneau"].parametres["required"] == ["plan_id", "calendrier"]


# =========================================================================================
# 2. Une intervention planifiée : son créneau se juge sans plan_id
# =========================================================================================
def test_une_prevision_calme_rend_le_creneau_ok_et_cite_l_auteur_la_source_et_l_heure(par_nom, monde):
    premier = monde["interventions"]["L-E2E-01"]
    date = _date_de(monde, premier)
    resultat = _resultat(_lire(par_nom, premier, date, _saisie()))
    assert resultat["statut"] == "ok" and resultat["cause"] is None and resultat["statut_intervention"] == "planifiee"
    assert resultat["plan_id"] == monde["plan_id"] and resultat["intervention_id"] == premier
    (creneau,) = resultat["creneaux"]
    assert creneau["statut"] == "ok" and creneau["date"] == date and creneau["service"] == "ravalement"
    jour, debut, fin = monde["visites"][premier]
    assert (creneau["jour"], creneau["debut_min"], creneau["fin_min"]) == (jour, debut, fin)
    citation = creneau["prevision"]
    assert citation["source"] == "saisie_manuelle" and citation["saisi_par"] == "admin.fictif"
    assert citation["reference"] == "Bulletin fictif du 4 octobre, 18 h"
    assert citation["emise_le"] == "2026-10-04T18:00:00-04:00", "l'heure de la prévision, jamais l'horloge de M4"
    assert resultat["attributions"] == []


def test_un_vent_fort_le_jour_du_creneau_bloque_le_ravalement_et_cite_les_valeurs_jugees(par_nom, monde):
    premier = monde["interventions"]["L-E2E-01"]
    date = _date_de(monde, premier)
    reponse = _lire(par_nom, premier, date, _saisie(dates_vent_fort=[date]))
    resultat = _resultat(reponse)
    assert resultat["statut"] == "bloquant"
    (creneau,) = resultat["creneaux"]
    assert creneau["statut"] == "bloquant" and creneau["date"] == date
    assert [r["detail"] for r in creneau["regles"] if r["statut"] == "bloquant"] == [
        "vent_kmh : 55 km/h à 08:00, blocage >= 40"
    ], "le créneau garde le détail de ses règles"
    assert all(set(r) == {"risque", "statut", "detail"} for r in creneau["regles"])
    assert set(creneau["prevision"]) == {"source", "emise_le", "heure_type", "saisi_par", "reference"}
    assert "points" not in json.dumps(creneau)
    assert len(json.dumps(reponse, ensure_ascii=False)) < jetons.LIMITE_SORTIE_DEFAUT


def test_le_meme_vent_ne_bloque_pas_la_reparation_dont_le_seuil_est_a_soixante(par_nom, monde):
    reparation = monde["interventions"]["L-E2E-02"]
    date = _date_de(monde, reparation)
    resultat = _resultat(_lire(par_nom, reparation, date, _saisie(dates_vent_fort=[date])))
    assert resultat["statut"] == "ok" and resultat["creneaux"][0]["service"] == "autre"


def test_un_vent_au_niveau_validation_demande_une_validation(par_nom, monde):
    premier = monde["interventions"]["L-E2E-01"]
    date = _date_de(monde, premier)
    resultat = _resultat(_lire(par_nom, premier, date, _saisie(dates_vent_fort=[date], vent=30)))
    assert resultat["statut"] == "validation_requise"


def _du_plan(par_nom, monde, saisie):
    """`m4_verifier_meteo_creneau` pour le plan, avec la même prévision : `{intervention_id: créneau}` et la vue."""
    vue = _resultat(
        _appeler(
            par_nom,
            "m4_verifier_meteo_creneau",
            {
                "plan_id": monde["plan_id"],
                "calendrier": {str(jour): date for jour, date in CALENDRIER.items()},
                "previsions_saisies": saisie,
            },
        )
    )
    return {c["intervention_id"]: c for c in vue["creneaux"]}, vue


def test_le_creneau_est_celui_du_plan_octet_pour_octet_sous_une_prevision_calme(par_nom, monde):
    """La MÊME évaluation : pour chaque intervention, le créneau est identique à celui de `m4_verifier_meteo_creneau`
    pour le même plan, la même date et la même prévision."""
    saisie = _saisie()
    par_intervention, vue = _du_plan(par_nom, monde, saisie)
    assert "detail_reduit" not in vue and len(par_intervention) == 3
    for identifiant in monde["interventions"].values():
        resultat = _resultat(_lire(par_nom, identifiant, _date_de(monde, identifiant), saisie))
        assert _octets(resultat["creneaux"][0]) == _octets(par_intervention[identifiant])
        assert resultat["statut"] == "ok"


def test_sous_un_vent_fort_le_verdict_et_les_regles_qui_bloquent_sont_celles_du_plan(par_nom, monde):
    jour_venteux = min(jour for jour, _, _ in monde["visites"].values())
    saisie = _saisie(dates_vent_fort=[CALENDRIER[jour_venteux]])
    par_intervention, vue = _du_plan(par_nom, monde, saisie)
    statuts = set()
    for identifiant in monde["interventions"].values():
        resultat = _resultat(_lire(par_nom, identifiant, _date_de(monde, identifiant), saisie))
        creneau = resultat["creneaux"][0]
        du_plan = par_intervention[identifiant]
        assert creneau["statut"] == du_plan["statut"] and resultat["statut"] == du_plan["statut"]
        assert creneau["prevision"] == du_plan["prevision"]
        if "regles" in du_plan:
            # une vue de plan très résumée (`ok_resume`) ne garde que les règles qui ne sont pas « ok »
            regles = [r for r in creneau["regles"] if r["statut"] != "ok"] if "ok_resume" in vue else creneau["regles"]
            assert regles == du_plan["regles"]
        statuts.add(resultat["statut"])
    assert statuts == {"bloquant", "ok"}


# =========================================================================================
# 3. inconnu n'est JAMAIS ok
# =========================================================================================
def test_sans_prevision_ni_fournisseur_ouvert_le_creneau_est_inconnu_jamais_ok_et_sans_reseau(par_nom, monde):
    premier = monde["interventions"]["L-E2E-01"]
    resultat = _resultat(_lire(par_nom, premier, _date_de(monde, premier)))
    assert resultat["statut"] == "inconnu"
    (creneau,) = resultat["creneaux"]
    assert creneau["statut"] == "inconnu" and creneau["regles"] == [] and creneau["prevision"] is None
    assert creneau["cause"]["code"] == "REJ-METEO-FOURNISSEUR-FERME"
    assert "aucun fournisseur météo n'est ouvert" in creneau["cause"]["detail"]


def test_sans_date_le_creneau_est_inconnu_la_date_n_est_jamais_devinee(par_nom, monde):
    premier = monde["interventions"]["L-E2E-01"]
    resultat = _resultat(_lire(par_nom, premier, None, _saisie()))
    assert resultat["statut"] == "inconnu" and resultat["plan_id"] == monde["plan_id"]
    (creneau,) = resultat["creneaux"]
    assert creneau["date"] is None and creneau["prevision"] is None
    assert "pas de date" in creneau["cause"]["detail"]


def test_un_service_sans_regle_reste_inconnu_meme_avec_une_prevision_calme(instance, par_nom, monde):
    partiel = copy.deepcopy(METEO)
    del partiel["services"]["autre"]
    _declarer(instance, "meteo", partiel)
    reparation = monde["interventions"]["L-E2E-02"]
    resultat = _resultat(_lire(par_nom, reparation, _date_de(monde, reparation), _saisie()))
    (creneau,) = resultat["creneaux"]
    assert resultat["statut"] == "inconnu" and "seuil à configurer" in creneau["cause"]["detail"]
    assert "'autre'" in creneau["cause"]["detail"]


def test_sans_profil_meteo_declare_le_creneau_est_inconnu_avec_le_verdict_du_profil(instance, par_nom, monde):
    fichier = instance / "home" / "entreprise.yaml"
    profil = yaml.safe_load(fichier.read_text(encoding="utf-8"))
    del profil["meteo"]
    fichier.write_text(yaml.safe_dump(profil, allow_unicode=True), encoding="utf-8")
    premier = monde["interventions"]["L-E2E-01"]
    resultat = _resultat(_lire(par_nom, premier, _date_de(monde, premier), _saisie()))
    assert resultat["statut"] == "inconnu"
    assert resultat["creneaux"][0]["cause"]["code"] == "REJ-METEO-NON-CONFIGUREE"
    assert "opsys-metier meteo declarer" in resultat["creneaux"][0]["cause"]["detail"]


class FournisseurEnPanne:
    """Un fournisseur du port qui répond toujours « indisponible » : ni réseau ni horloge."""

    def descripteur(self):
        return {"fournisseur": "panne_fictive"}

    def previsions(self, lieu, date_debut, date_fin):
        return None, {
            "code": CODE_FOURNISSEUR_INDISPONIBLE,
            "detail": "fournisseur fictif indisponible (panne simulée)",
        }


def test_un_fournisseur_en_panne_rend_inconnu_avec_la_cause_jamais_ok(instance, monde):
    en_panne = {o.nom: o for o in outils(fournisseur_meteo=FournisseurEnPanne())}
    premier = monde["interventions"]["L-E2E-01"]
    resultat = _resultat(_lire(en_panne, premier, _date_de(monde, premier)))
    assert resultat["statut"] == "inconnu"
    assert resultat["creneaux"][0]["cause"]["code"] == CODE_FOURNISSEUR_INDISPONIBLE


def test_la_saisie_a_la_main_l_emporte_sur_un_fournisseur_en_panne(instance, monde):
    en_panne = {o.nom: o for o in outils(fournisseur_meteo=FournisseurEnPanne())}
    premier = monde["interventions"]["L-E2E-01"]
    resultat = _resultat(_lire(en_panne, premier, _date_de(monde, premier), _saisie()))
    assert resultat["statut"] == "ok" and resultat["creneaux"][0]["prevision"]["source"] == "saisie_manuelle"


def test_un_fournisseur_ouvert_par_le_profil_dont_le_reseau_est_coupe_rend_inconnu_jamais_ok(
    instance, par_nom, monde, monkeypatch
):
    profil = copy.deepcopy(METEO)
    profil["fournisseur"] = "msc_geomet"
    _declarer(instance, "meteo", profil)

    def coupure(*_args, **_kwargs):
        raise OSError("réseau coupé (simulé par le test)")

    monkeypatch.setattr(socket, "create_connection", coupure)
    premier = monde["interventions"]["L-E2E-01"]
    resultat = _resultat(_lire(par_nom, premier, _date_de(monde, premier)))
    assert resultat["statut"] == "inconnu"
    assert CODE_FOURNISSEUR_INDISPONIBLE in json.dumps(resultat["creneaux"], ensure_ascii=False)


# =========================================================================================
# 4. Sans créneau : l'intervention n'est placée par aucun plan appliqué
# =========================================================================================
def test_avant_l_application_du_plan_aucune_intervention_n_a_de_creneau(par_nom, monde_propose):
    """Le plan est seulement PROPOSÉ : rien n'est assigné, la météo n'a aucun créneau à juger."""
    for identifiant in monde_propose["interventions"].values():
        resultat = _resultat(_lire(par_nom, identifiant, "2026-10-05", _saisie()))
        assert resultat["statut_intervention"] == "a_planifier" and resultat["creneaux"] == []
        assert resultat["statut"] == "inconnu" and resultat["plan_id"] is None
        assert resultat["cause"]["code"] == "REJ-CHAMP-MANQUANT" and "a_planifier" in resultat["cause"]["detail"]


def test_une_intervention_reportee_a_quitte_son_creneau(par_nom, monde):
    premier = monde["interventions"]["L-E2E-01"]
    reponse = _appeler(
        par_nom,
        "m4_signaler_report",
        {"intervention_id": premier, "motif": "meteo", "horodatage": HORODATAGE},
    )
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is True, reponse
    resultat = _resultat(_lire(par_nom, premier, _date_de(monde, premier), _saisie()))
    assert resultat["statut_intervention"] == "reportee" and resultat["creneaux"] == []
    assert resultat["statut"] == "inconnu" and "reportee" in resultat["cause"]["detail"]
    # les deux autres gardent leur créneau
    autre = monde["interventions"]["L-E2E-10"]
    assert _resultat(_lire(par_nom, autre, _date_de(monde, autre), _saisie()))["creneaux"]


def test_une_intervention_inconnue_ou_terminee_est_refusee(par_nom, monde):
    assert _code_refus(_lire(par_nom, "intervention-fantome", "2026-10-05")) == "REJ-TRANSITION-ILLEGALE"
    premier = monde["interventions"]["L-E2E-01"]
    annulation = _appeler(
        par_nom, "m4_annuler_intervention", {"intervention_id": premier, "horodatage": HORODATAGE}, None
    )
    assert annulation["ok"] is True and annulation["resultat"]["accepte"] is True
    reponse = _lire(par_nom, premier, "2026-10-05")
    assert _code_refus(reponse) == "REJ-TRANSITION-ILLEGALE"
    assert "météo sans objet" in reponse["resultat"]["verdict"]["detail"]


@pytest.mark.parametrize("date", ["2026-02-30", "5 octobre", "", "2026-13-01"])
def test_une_date_qui_n_existe_pas_est_refusee_et_n_ecrit_rien(par_nom, monde, date):
    premier = monde["interventions"]["L-E2E-01"]
    avant = _octets(_maillons())
    assert _code_refus(_appeler(par_nom, "m4_lire_meteo_intervention", {"intervention_id": premier, "date": date})) == (
        "REJ-CONTRAT-INVALIDE"
    )
    assert _octets(_maillons()) == avant


def test_le_socle_refuse_un_mauvais_type_et_toute_cle_inconnue(par_nom, monde):
    premier = monde["interventions"]["L-E2E-01"]
    for arguments in (
        {"intervention_id": premier, "date": 20261005},
        {"intervention_id": 12},
        {"date": "2026-10-05"},
        {"intervention_id": premier, "plan_id": monde["plan_id"]},
        {"intervention_id": premier, "calendrier": {"0": "2026-10-05"}},
        {"intervention_id": premier, "jours": [0]},
        {"intervention_id": premier, "personne": "admin.fictif"},
    ):
        reponse = _appeler(par_nom, "m4_lire_meteo_intervention", arguments)
        assert reponse["ok"] is False and reponse["erreur"] == "arguments_invalides", arguments


# =========================================================================================
# 5. Lecture pure : rien n'est écrit, aucun statut ne change, ni report ni cédule
# =========================================================================================
def test_l_outil_n_ecrit_rien_deux_appels_donnent_le_meme_resultat(par_nom, monde):
    premier = monde["interventions"]["L-E2E-01"]
    date = _date_de(monde, premier)
    saisie = _saisie(dates_vent_fort=[date])
    avant = _octets(_maillons())
    un = _resultat(_lire(par_nom, premier, date, saisie))
    assert _octets(_maillons()) == avant, "le registre n'a pas bougé d'un octet"
    deux = _resultat(_lire(par_nom, premier, date, saisie))
    assert _octets(un) == _octets(deux) and _octets(_maillons()) == avant
    types = [m["type_entree"] for m in _maillons()]
    assert types.count("cedule_proposee") == 1 and types.count("cedule_appliquee") == 1
    statuts = {etats.statut_courant(registre_m4.Registre(_maillons()), i) for i in monde["interventions"].values()}
    assert statuts == {"planifiee"}, "un vent qui bloque ne change aucun statut : le report est un geste de l'admin"


def test_la_reponse_ne_propose_ni_report_ni_cedule_et_ne_porte_ni_coordonnee_ni_prix_ni_contact(par_nom, monde):
    premier = monde["interventions"]["L-E2E-01"]
    date = _date_de(monde, premier)
    resultat = _resultat(_lire(par_nom, premier, date, _saisie(dates_vent_fort=[date])))
    assert set(resultat) == {
        "intervention_id",
        "statut_intervention",
        "statut",
        "plan_id",
        "creneaux",
        "cause",
        "attributions",
    }
    texte = json.dumps(resultat, ensure_ascii=False)
    for interdit in (
        "latitude",
        "longitude",
        "microdegres",
        "Client Fictif",
        "5145550142",
        "prix",
        "montant",
        "45735000",
        "-73455000",
        "rue Fictive",
        "reports_proposes",
        "cedule_relancee",
    ):
        assert interdit not in texte, interdit


# =========================================================================================
# 6. Refus : identité, rôle, saisie
# =========================================================================================
def test_l_employe_n_a_pas_de_portee_sur_la_meteo_d_un_chantier(par_nom, monde):
    premier = monde["interventions"]["L-E2E-01"]
    avant = _octets(_maillons())
    reponse = _lire(par_nom, premier, _date_de(monde, premier), _saisie(auteur="luc.fictif"), EMPLOYE)
    assert _code_refus(reponse) == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert _octets(_maillons()) == avant


def test_le_vendeur_n_a_pas_de_portee_sur_la_meteo_d_un_chantier(par_nom, monde):
    premier = monde["interventions"]["L-E2E-01"]
    assert _code_refus(_lire(par_nom, premier, _date_de(monde, premier), None, VENDEUR)) == (
        "REJ-IDENTITE-APPAREIL-INVALIDE"
    )


def test_une_identite_non_confirmee_est_refusee(par_nom, monde):
    premier = monde["interventions"]["L-E2E-01"]
    assert _code_refus(_lire(par_nom, premier, _date_de(monde, premier), None, INCONNUE)) == (
        "REJ-IDENTITE-APPAREIL-INVALIDE"
    )


def test_un_agent_sans_identite_d_appareil_peut_lire(par_nom, monde):
    premier = monde["interventions"]["L-E2E-01"]
    resultat = _resultat(_lire(par_nom, premier, _date_de(monde, premier), _saisie(auteur="assistant"), None))
    assert resultat["statut"] == "ok"


def test_le_nom_de_la_saisie_doit_etre_celui_de_la_personne_authentifiee(par_nom, monde):
    premier = monde["interventions"]["L-E2E-01"]
    reponse = _lire(par_nom, premier, _date_de(monde, premier), _saisie(auteur="marc.fictif"))
    assert _code_refus(reponse) == "REJ-IDENTITE-FOURNIE-DIFFERENTE"


@pytest.mark.parametrize(
    "saisie",
    [
        {"saisi_par": "admin.fictif", "source": "x", "emise_le": "2026-10-04T18:00:00-04:00", "points": "beau"},
        {"saisi_par": "admin.fictif", "source": "", "emise_le": "2026-10-04T18:00:00-04:00", "points": []},
        {"saisi_par": "admin.fictif", "source": "x", "emise_le": "hier soir", "points": []},
        {"saisi_par": "admin.fictif", "source": "x", "emise_le": "2026-10-04T18:00:00-04:00"},
    ],
)
def test_une_saisie_mal_formee_est_refusee_et_n_ecrit_rien(par_nom, monde, saisie):
    premier = monde["interventions"]["L-E2E-01"]
    avant = _octets(_maillons())
    assert _code_refus(_lire(par_nom, premier, _date_de(monde, premier), saisie)) == "REJ-CONTRAT-INVALIDE"
    assert _octets(_maillons()) == avant


# =========================================================================================
# 7. La réponse tient dans une réponse d'appareil
# =========================================================================================
def test_la_limite_de_la_reponse_est_celle_de_l_appareil_moins_une_marge():
    assert outils_m4._LIMITE_REPONSE_METEO == jetons.LIMITE_SORTIE_DEFAUT - 500


def test_une_reponse_qui_ne_tient_pas_est_refusee_jamais_tronquee(par_nom, monde, monkeypatch):
    premier = monde["interventions"]["L-E2E-01"]
    date = _date_de(monde, premier)
    saisie = _saisie(dates_vent_fort=[date])
    complete = _lire(par_nom, premier, date, saisie)
    assert len(json.dumps(complete, ensure_ascii=False)) < 3000
    monkeypatch.setattr(outils_m4, "_LIMITE_REPONSE_METEO", 300)
    refus = _lire(par_nom, premier, date, saisie)
    assert _code_refus(refus) == "REJ-CONTRAT-INVALIDE" and "trop grande" in refus["resultat"]["verdict"]["detail"]
    assert len(json.dumps(refus, ensure_ascii=False)) < 1000


# =========================================================================================
# 8. Le volet météo de la préparation et l'outil du plan ne changent pas
# =========================================================================================
def test_le_volet_meteo_de_la_preparation_et_l_outil_du_plan_sont_inchanges(par_nom, monde_propose):
    for identifiant in monde_propose["interventions"].values():
        verdict = _resultat(_appeler(par_nom, "m4_verifier_preparation", {"intervention_id": identifiant}))
        assert verdict["volets"]["meteo"]["statut"] == "ok"
    du_plan = _resultat(
        _appeler(
            par_nom,
            "m4_verifier_meteo_creneau",
            {"plan_id": monde_propose["plan_id"], "calendrier": {str(j): d for j, d in CALENDRIER.items()}},
        )
    )
    assert du_plan["plan_id"] == monde_propose["plan_id"] and len(du_plan["creneaux"]) == 3
