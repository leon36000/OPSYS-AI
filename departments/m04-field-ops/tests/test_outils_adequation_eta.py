"""M4.11 et M4.14 sur les VRAIS outils : base SQLite migrée, registre durable, profil `entreprise.yaml`, file
d'approbation, bus.

Chaîne (scénario fictif de Repentigny à Joliette) : interventions avec adresses confirmées, cédule proposée, appliquée
et DATÉE (semaine du 2030-06-03), profil des équipes avec semaine type, puis les outils d'adéquation, de brouillon
d'affectation, de consentement de suivi et de brouillon de message. Les décisions humaines passent par la VRAIE file
d'approbation (N3). Aucun routeur, aucun réseau, aucune donnée réelle (`fictif: true`).
"""

from __future__ import annotations

import contextlib
import copy
import importlib.util
import json
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from m4_field_ops import frontieres
from m4_field_ops import outils_adequation_eta as adaptateur
from m4_field_ops.outils import outils
from sqlalchemy import func, select

from opsys import approbations, contexte, stockage
from opsys import equipes as equipes_entreprise
from opsys.capacites import outils_executables
from opsys.departements import charger_departements
from opsys.evenements import schemas
from opsys.outils import Autonomie, Niveau
from opsys.stockage.schema import APPROBATIONS, EVENEMENTS_SORTANTS

_spec = importlib.util.spec_from_file_location(
    "fixture_adequation_eta", Path(__file__).with_name("test_cedule_tournees_outils.py")
)
aide = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(aide)
instance, par_nom, interventions = aide.instance, aide.par_nom, aide.interventions

FICTIF = True
M4 = "m04-field-ops"
LUNDI = "2030-06-03"
DECIDE_LE = "2030-05-30T14:00:00+00:00"
REFERENCE = "2030-06-02T09:30:00-04:00"
POIDS = {
    "poids": {"capacite": "1", "charge": "1", "distance": "2", "qualite": "0"},
    "distance_reference_km": 100,
    "historique_minimum": 5,
}
REGLAGES_ETA = {
    "incertitude_trajet_pct": 25,
    "largeur_minimale_minutes": 30,
    "granularite_minutes": 15,
    "validite_consentement_jours": 7,
    "conservation_heures": 48,
    "messages_max_par_intervention": 2,
}
NOUVEAUX = {
    "m4_proposer_adequation_equipes",
    "m4_calibrer_poids_adequation",
    "m4_enregistrer_brouillon_affectation",
    "m4_approuver_affectation_engageante",
    "m4_estimer_eta_client",
    "m4_enregistrer_consentement_suivi_client",
    "m4_retirer_consentement_suivi_client",
    "m4_lire_consentement_suivi_client",
    "m4_preparer_message_eta_client",
}


# -- installation ----------------------------------------------------------------------------------------
def _plages(*couples):
    return [{"debut": debut, "fin": fin} for debut, fin in couples]


def _semaine(*jours, **plus):
    jour = _plages(("07:00", "15:00"))
    return {
        "fuseau": "America/Montreal",
        **{j: copy.deepcopy(jour) for j in jours},
        "samedi": [],
        "dimanche": [],
        **plus,
    }


def _ecrire_profil(maison, **retirer):
    liste = []
    for equipe in aide._equipes():
        liste.append(
            {
                **equipe,
                "membres": [
                    f"{equipe['id'].replace('-', '.')}.fictif",
                    f"second.{equipe['id'].replace('-', '.')}.fictif",
                ],
                "semaine_type": _semaine("lundi", "mardi", "mercredi", "jeudi", "vendredi"),
            }
        )
    brut = {
        "liste": liste,
        "feries": {"annees": [2030], "jours": []},
        "services": {
            t: {"duree_min": d, "competences": list(aide.SCENARIO["competences_par_type_travaux"][t])}
            for t, d in aide.SCENARIO["durees_par_type_travaux"].items()
        },
        "cedule": dict(aide.SCENARIO["parametres"]),
    }
    for cle in retirer:
        brut.pop(cle, None)
    (maison / "home" / "entreprise.yaml").write_text(
        yaml.safe_dump({"equipes": equipes_entreprise.normaliser_equipes(brut)}, allow_unicode=True), encoding="utf-8"
    )


@pytest.fixture
def monde(par_nom, instance, interventions):
    """Profil déclaré, cédule appliquée et datée au lundi 2030-06-03 ; horloge d'approbation figée."""
    _ecrire_profil(instance)
    plan = aide._resultat(aide._proposer(par_nom, interventions))["plan_id"]
    aide._resultat(aide._appliquer(par_nom, plan))
    aide._resultat(
        aide._appeler(
            par_nom,
            "m4_confirmer_dates_cedule",
            {"plan_id": plan, "calendrier": {"0": LUNDI}, "revision_attendue": 0},
            aide.ADMIN,
        )
    )
    return interventions


@pytest.fixture(autouse=True)
def _horloge_et_reglages(monkeypatch):
    monkeypatch.setattr(approbations, "_maintenant", lambda: DECIDE_LE)
    monkeypatch.setattr(adaptateur, "_parametres_adequation", lambda: copy.deepcopy(POIDS))
    monkeypatch.setattr(adaptateur, "_parametres_eta", lambda: dict(REGLAGES_ETA))


def _appeler(par_nom, nom, arguments, acteur=None):
    return aide._appeler(par_nom, nom, arguments, acteur)


def _maillons_du_type(type_entree):
    return [m for m in aide._maillons() if m["type_entree"] == type_entree]


def _evenements(type_evenement="m4.message_client_brouillon_pret"):
    with stockage.transaction() as cnx:
        return cnx.execute(
            select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.type_evenement == type_evenement)
        ).all()


def _decider(par_nom, nom, arguments, personne="admin.fictif", approuver=True):
    """Met la demande en file puis la fait décider par une PERSONNE, comme le propriétaire/admin dans l'app."""
    departements = charger_departements()
    with stockage.transaction() as cnx:
        demande = approbations.creer_demande(cnx, M4, nom, arguments, niveau=Niveau.N3)
    with stockage.transaction() as cnx:
        outils_exec = outils_executables(departements, lambda: contextlib.nullcontext(cnx))
        return demande, approbations.decider(cnx, demande, approuver, personne, outils_exec, departements)


def _consentir(par_nom, iid, canal="sms", recueilli_le="2030-05-30T10:00:00-04:00"):
    arguments = {
        "intervention_id": iid,
        "canal": canal,
        "enonce_version": "suivi-fr-CA-v1",
        "preuve": {"fictif": True, "reference": "formulaire-42"},
        "recueilli_le": recueilli_le,
    }
    return _decider(par_nom, "m4_enregistrer_consentement_suivi_client", arguments)


def _iid(monde, lead="L-E2E-01"):
    return monde[lead]


# =========================================================================================== déclaration
def test_les_neuf_outils_sont_declares_sans_aucun_droit_d_appareil_avec_les_bons_niveaux():
    par = {o.nom: o for o in outils()}
    assert set(par) >= NOUVEAUX
    for nom in NOUVEAUX:
        assert par[nom].roles_appareil == frozenset(), nom  # aucun droit élargi
    for nom in (
        "m4_proposer_adequation_equipes",
        "m4_calibrer_poids_adequation",
        "m4_estimer_eta_client",
        "m4_lire_consentement_suivi_client",
    ):
        assert par[nom].autonomie is Autonomie.T0 and par[nom].niveau_effectif is Niveau.N0, nom
    for nom in (
        "m4_enregistrer_brouillon_affectation",
        "m4_retirer_consentement_suivi_client",
        "m4_preparer_message_eta_client",
    ):
        assert par[nom].autonomie is Autonomie.T1 and par[nom].niveau_effectif is Niveau.N2, nom
    for nom in ("m4_approuver_affectation_engageante", "m4_enregistrer_consentement_suivi_client"):
        assert par[nom].autonomie is Autonomie.T1 and par[nom].niveau_effectif is Niveau.N3, nom
    assert not any(par[n].autonomie is Autonomie.T3 for n in NOUVEAUX)


def test_le_manifeste_livre_laisse_poids_et_reglages_vides_a_dessein(monkeypatch):
    monkeypatch.undo()  # retire les réglages de test
    assert adaptateur._parametres_adequation() == {
        "poids": {"capacite": None, "charge": None, "distance": None, "qualite": None},
        "distance_reference_km": None,
        "historique_minimum": None,
    }
    assert adaptateur._parametres_eta() == {k: None for k in REGLAGES_ETA}


# =========================================================================================== M4.11
def test_sans_poids_declares_aucune_equipe_n_est_ordonnee(par_nom, monde, monkeypatch):
    monkeypatch.setattr(
        adaptateur,
        "_parametres_adequation",
        lambda: {
            "poids": {k: None for k in ("capacite", "charge", "distance", "qualite")},
            "distance_reference_km": None,
            "historique_minimum": None,
        },
    )
    avant = aide._etat()
    reponse = _appeler(par_nom, "m4_proposer_adequation_equipes", {"intervention_id": _iid(monde), "date_cible": LUNDI})
    assert aide._code_refus(reponse) == "REJ-ADEQUATION-PARAMETRES-ABSENTS"
    assert aide._etat() == avant


def test_l_ordre_des_equipes_vient_de_la_semaine_type_de_la_cedule_et_de_la_distance_sans_rien_ecrire(par_nom, monde):
    iid = _iid(monde, "L-E2E-10")  # chantier éloigné (Joliette)
    avant = aide._etat()
    ordre = aide._resultat(
        _appeler(par_nom, "m4_proposer_adequation_equipes", {"intervention_id": iid, "date_cible": LUNDI})
    )
    assert aide._etat() == avant  # lecture seule
    assert ordre["decision"] == "humain" and ordre["semaine_capacite"] == {
        "debut": LUNDI,
        "calculable": True,
        "manque": [],
        "portee": "semaine_type",
    }
    assert {x["equipe_id"] for x in ordre["ordre"]} == {"eq-a", "eq-b"}
    assert (
        ordre["criteres_actifs"] == ["capacite", "charge", "distance"]
        and ordre["criteres_ecartes"][0]["critere"] == "qualite"
    )
    detail = {x["equipe_id"]: {c["critere"]: c for c in x["criteres"]} for x in ordre["ordre"]}
    # capacité de la semaine type : lundi..vendredi 07:00-15:00 = 5 x 480 = 2400 min pour chaque équipe
    for equipe in ("eq-a", "eq-b"):
        assert "sur 2400" in detail[equipe]["charge"]["valeur"]
    # le chantier est près de Joliette : l'équipe de Joliette est plus proche, donc mieux placée pour la distance
    assert Decimal(detail["eq-b"]["distance"]["sous_indice"]) > Decimal(detail["eq-a"]["distance"]["sous_indice"])
    texte = json.dumps(ordre, ensure_ascii=False).lower()
    assert "fictif" not in texte and "second" not in texte  # aucun nom de membre
    assert frontieres.scanner_frontieres(ordre) == []


def test_une_equipe_sans_la_competence_requise_est_exclue_pas_ordonnee(par_nom, monde, instance):
    _ecrire_profil(instance)
    profil = yaml.safe_load((instance / "home" / "entreprise.yaml").read_text(encoding="utf-8"))
    profil["equipes"]["liste"][0]["competences"] = ["gouttieres"]  # eq-a perd « revetement »
    (instance / "home" / "entreprise.yaml").write_text(yaml.safe_dump(profil, allow_unicode=True), encoding="utf-8")
    ordre = aide._resultat(
        _appeler(
            par_nom, "m4_proposer_adequation_equipes", {"intervention_id": _iid(monde, "L-E2E-01"), "date_cible": LUNDI}
        )
    )  # ravalement : exige « revetement »
    assert [x["equipe_id"] for x in ordre["ordre"]] == ["eq-b"]
    assert ordre["exclues"] == [
        {"equipe_id": "eq-a", "motifs": ["competence_manquante"], "detail": "compétence(s) manquante(s) : revetement"}
    ]


def test_une_semaine_sans_semaine_type_rend_les_equipes_non_evaluables_jamais_zero(par_nom, monde, instance):
    _ecrire_profil(instance)
    profil = yaml.safe_load((instance / "home" / "entreprise.yaml").read_text(encoding="utf-8"))
    del profil["equipes"]["liste"][0]["semaine_type"]
    (instance / "home" / "entreprise.yaml").write_text(yaml.safe_dump(profil, allow_unicode=True), encoding="utf-8")
    ordre = aide._resultat(
        _appeler(par_nom, "m4_proposer_adequation_equipes", {"intervention_id": _iid(monde), "date_cible": LUNDI})
    )
    assert ordre["ordre"] == [] and len(ordre["non_evaluables"]) == 2  # toute la capacité est « tout ou rien »
    assert ordre["semaine_capacite"]["calculable"] is False and ordre["semaine_capacite"]["manque"]


@pytest.mark.parametrize(
    "arguments",
    [
        {"intervention_id": "int-inconnue", "date_cible": LUNDI},
        {"intervention_id": "x", "date_cible": "2030-02-30"},
        {"intervention_id": "x", "date_cible": "demain"},
        {"intervention_id": "x", "date_cible": ""},
    ],
)
def test_intervention_inconnue_ou_date_invalide_refusee_sans_ecriture(par_nom, monde, arguments):
    avant = aide._etat()
    reponse = _appeler(par_nom, "m4_proposer_adequation_equipes", arguments)
    assert aide._code_refus(reponse) in ("REJ-AFFECTATION-INTROUVABLE", "REJ-ADEQUATION-ENTREE-INVALIDE")
    assert aide._etat() == avant


def test_aucun_champ_protege_ne_peut_etre_glisse_dans_les_arguments_d_un_outil(par_nom, monde):
    for outil, args in (
        ("m4_proposer_adequation_equipes", {"intervention_id": _iid(monde), "date_cible": LUNDI, "age": 40}),
        (
            "m4_proposer_adequation_equipes",
            {"intervention_id": _iid(monde), "date_cible": LUNDI, "equipes": [{"sexe": "x"}]},
        ),
    ):
        reponse = _appeler(par_nom, outil, args)
        assert reponse["ok"] is False, reponse  # le schéma est fermé (additionalProperties faux)


def test_la_calibration_passe_par_l_outil_sur_des_cas_fictifs_seulement(par_nom, monde):
    def equipe(identifiant, distance):
        return {
            "equipe_id": identifiant,
            "competences": ["c1"],
            "membres_declares": 2,
            "distance_m": distance,
            "capacite": {"minutes_disponibles": 2400, "minutes_planifiees": 600},
        }

    cas = [
        {
            "fictif": True,
            "choix_humain": "eq-a",
            "entrees": {
                "intervention": {
                    "intervention_id": f"i{k}",
                    "service": "service_a",
                    "date": LUNDI,
                    "duree_min": 120,
                    "competences_requises": ["c1"],
                },
                "equipes": [equipe("eq-a", 1000), equipe("eq-b", 40000)],
            },
        }
        for k in range(3)
    ]
    arguments = {"cas": cas, "pas": 4, "distance_reference_km": 50, "historique_minimum": 5}
    rapport = aide._resultat(_appeler(par_nom, "m4_calibrer_poids_adequation", arguments))
    assert rapport["fictif"] is True and rapport["accord"]["reussis"] == 3
    cas[0]["fictif"] = False
    reponse = _appeler(par_nom, "m4_calibrer_poids_adequation", {**arguments, "cas": cas})
    assert aide._code_refus(reponse) == "REJ-ADEQUATION-DONNEES-REELLES-REFUSEES"


# =========================================================================================== brouillon d'affectation
def _arg_brouillon(iid, equipe, **plus):
    base = {
        "intervention_id": iid,
        "equipe_id": equipe,
        "source": "adequation",
        "ordre_empreinte": "a" * 64,
        "engagement_client": False,
        "horodatage": "2030-06-01T10:00:00-04:00",
    }
    base.update(plus)
    return base


def test_le_brouillon_d_affectation_est_interne_n_assigne_personne_et_ne_change_pas_l_assignation(par_nom, monde):
    iid = _iid(monde)
    assigne_avant = aide._technicien(iid)
    reponse = _appeler(par_nom, "m4_enregistrer_brouillon_affectation", _arg_brouillon(iid, "eq-b"))
    resultat = aide._resultat(reponse)
    assert (
        resultat["statut"] == "brouillon" and resultat["affecte"] is False and "m4_appliquer_cedule" in resultat["note"]
    )
    [maillon] = _maillons_du_type("affectation_brouillon")
    assert (
        maillon["equipe_id"] == "eq-b" and maillon["engagement_client"] is False and maillon["intervention_id"] == iid
    )
    assert aide._technicien(iid) == assigne_avant, "aucune assignation n'a été exécutée"


def test_un_brouillon_qui_engage_le_client_est_refuse_ici_et_renvoye_vers_l_approbation(par_nom, monde):
    avant = aide._etat()
    reponse = _appeler(
        par_nom, "m4_enregistrer_brouillon_affectation", _arg_brouillon(_iid(monde), "eq-b", engagement_client=True)
    )
    assert aide._code_refus(reponse) == "REJ-AFFECTATION-ENGAGEMENT-CLIENT"
    assert "m4_approuver_affectation_engageante" in aide._detail_refus(reponse)
    assert aide._etat() == avant


@pytest.mark.parametrize(
    ("modif", "code"),
    [
        ({"equipe_id": "eq-inconnue"}, "REJ-AFFECTATION-INVALIDE"),
        ({"ordre_empreinte": "court"}, "REJ-AFFECTATION-INVALIDE"),
        ({"horodatage": "hier"}, "REJ-AFFECTATION-INVALIDE"),
        ({"intervention_id": "int-inconnue"}, "REJ-AFFECTATION-INTROUVABLE"),
    ],
)
def test_brouillon_mal_forme_ou_equipe_inadmissible_refuse_sans_ecriture(par_nom, monde, modif, code):
    avant = aide._etat()
    reponse = _appeler(par_nom, "m4_enregistrer_brouillon_affectation", _arg_brouillon(_iid(monde), "eq-b", **modif))
    assert aide._code_refus(reponse) == code
    assert aide._etat() == avant


def test_une_source_de_brouillon_hors_liste_est_refusee_par_le_schema_de_l_outil(par_nom, monde):
    reponse = _appeler(
        par_nom, "m4_enregistrer_brouillon_affectation", _arg_brouillon(_iid(monde), "eq-b", source="devinette")
    )
    assert reponse["ok"] is False and _maillons_du_type("affectation_brouillon") == []


def test_l_approbation_d_une_affectation_engageante_exige_une_personne_et_un_brouillon(par_nom, monde):
    iid = _iid(monde)
    arguments = {"intervention_id": iid, "equipe_id": "eq-b"}
    direct = _appeler(par_nom, "m4_approuver_affectation_engageante", arguments)
    assert aide._code_refus(direct) == "REJ-AFFECTATION-SANS-APPROBATION"
    assert _maillons_du_type("affectation_approuvee") == []

    # approuvée par une personne MAIS sans brouillon pour cette équipe : refusée
    _, decision = _decider(par_nom, "m4_approuver_affectation_engageante", arguments)
    assert not _maillons_du_type("affectation_approuvee")

    aide._resultat(_appeler(par_nom, "m4_enregistrer_brouillon_affectation", _arg_brouillon(iid, "eq-b")))
    _decider(par_nom, "m4_approuver_affectation_engageante", arguments)
    [maillon] = _maillons_du_type("affectation_approuvee")
    assert (
        maillon["approuve_par"] == "admin.fictif"
        and maillon["engagement_client"] is True
        and maillon["horodatage"] == DECIDE_LE
    )
    assert maillon["approbation_ref"]

    # une seule approbation par intervention
    _decider(par_nom, "m4_approuver_affectation_engageante", {"intervention_id": iid, "equipe_id": "eq-a"})
    assert len(_maillons_du_type("affectation_approuvee")) == 1


def test_un_appelant_ne_peut_pas_se_faire_passer_pour_l_approbateur_par_ses_arguments(par_nom, monde):
    iid = _iid(monde)
    aide._resultat(_appeler(par_nom, "m4_enregistrer_brouillon_affectation", _arg_brouillon(iid, "eq-b")))
    reponse = _appeler(
        par_nom,
        "m4_approuver_affectation_engageante",
        {"intervention_id": iid, "equipe_id": "eq-b", "approuve_par": "proprio"},
    )
    assert reponse["ok"] is False  # schéma fermé : aucun champ d'identité
    assert _maillons_du_type("affectation_approuvee") == []


# =========================================================================================== M4.14
def test_sans_reglages_declares_aucune_fenetre_n_est_estimee(par_nom, monde, monkeypatch):
    monkeypatch.setattr(adaptateur, "_parametres_eta", lambda: {k: None for k in REGLAGES_ETA})
    reponse = _appeler(
        par_nom,
        "m4_estimer_eta_client",
        {
            "intervention_id": _iid(monde),
            "horodatage_reference": REFERENCE,
            "retards_declares_minutes": [],
            "depart": None,
        },
    )
    assert aide._code_refus(reponse) == "REJ-ETA-PARAMETRES-ABSENTS"


def _eta(par_nom, iid, depart=None, retards=(), reference=REFERENCE):
    return _appeler(
        par_nom,
        "m4_estimer_eta_client",
        {
            "intervention_id": iid,
            "horodatage_reference": reference,
            "retards_declares_minutes": list(retards),
            "depart": depart,
        },
    )


def _creneau(iid):
    from m4_field_ops import calendrier_civil

    with stockage.transaction():
        lignes, _ = calendrier_civil._projection(calendrier_civil._index(aide._registre()))
    return next(x for x in lignes if x["intervention_id"] == iid)


def test_la_fenetre_vient_du_creneau_date_de_la_cedule_sans_depart_connu(par_nom, monde):
    iid = _iid(monde)
    creneau = _creneau(iid)
    eta = aide._resultat(_eta(par_nom, iid))
    assert eta["sources"] == ["creneau_cedule"] and eta["promesse"] is False
    assert eta["fenetre"]["debut"] <= creneau["debut"] < eta["fenetre"]["fin"]
    assert eta["fenetre"]["largeur_minutes"] >= 30 and frontieres.scanner_frontieres(eta) == []


def test_avec_un_depart_le_trajet_vient_du_port_en_mode_bride_et_les_coordonnees_ne_sortent_pas(par_nom, monde):
    iid = _iid(monde, "L-E2E-10")  # Joliette
    creneau = _creneau(iid)
    depart_instant = creneau["debut"][:11] + "05:00:00-04:00"  # très tôt : le trajet pèse sur la borne basse
    depart = {
        "instant": depart_instant,
        "origine": "depot",
        "latitude_microdegres": 45735000,
        "longitude_microdegres": -73455000,
    }
    avant = aide._etat()
    eta = aide._resultat(_eta(par_nom, iid, depart=depart))
    assert aide._etat() == avant, "l'estimation n'écrit rien"
    assert eta["approximatif"] is True and "trajet_approximatif_depuis_depot" in eta["sources"]
    texte = json.dumps(eta)
    assert "45735000" not in texte and "73455000" not in texte and "latitude" not in texte


def test_les_retards_declares_elargissent_la_borne_haute(par_nom, monde):
    iid = _iid(monde)
    sans = aide._resultat(_eta(par_nom, iid))["fenetre"]
    avec = aide._resultat(_eta(par_nom, iid, retards=[60]))["fenetre"]
    assert avec["debut"] == sans["debut"] and avec["fin"] > sans["fin"]


def test_une_intervention_sans_creneau_date_ou_une_fenetre_depassee_ne_rend_rien(par_nom, monde):
    assert aide._code_refus(_eta(par_nom, "int-sans-creneau")) == "REJ-ETA-CRENEAU-INCONNU"
    assert (
        aide._code_refus(_eta(par_nom, _iid(monde), reference="2030-06-03T20:00:00-04:00"))
        == "REJ-ETA-FENETRE-DEPASSEE"
    )


@pytest.mark.parametrize(
    "depart",
    [
        {
            "instant": "2030-06-03T05:00:00-04:00",
            "origine": "maison",
            "latitude_microdegres": 1,
            "longitude_microdegres": 1,
        },
        {"instant": "2030-06-03T05:00:00-04:00", "origine": "depot"},
        {
            "instant": "2030-06-03T05:00:00-04:00",
            "origine": "depot",
            "latitude_microdegres": 0,
            "longitude_microdegres": 0,
        },
        {
            "instant": "2030-06-03T05:00:00-04:00",
            "origine": "depot",
            "latitude_microdegres": "45",
            "longitude_microdegres": -73455000,
        },
    ],
)
def test_depart_mal_forme_refuse_sans_ecriture(par_nom, monde, depart):
    avant = aide._etat()
    reponse = _eta(par_nom, _iid(monde), depart=depart)
    assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"].startswith("REJ-ETA-")
    assert aide._etat() == avant


def test_le_consentement_de_suivi_est_inscrit_par_une_personne_via_la_file_jamais_par_un_agent(par_nom, monde):
    iid = _iid(monde)
    arguments = {
        "intervention_id": iid,
        "canal": "sms",
        "enonce_version": "suivi-fr-CA-v1",
        "preuve": {"fictif": True, "reference": "formulaire-42"},
        "recueilli_le": "2030-05-30T10:00:00-04:00",
    }
    direct = _appeler(par_nom, "m4_enregistrer_consentement_suivi_client", arguments)
    assert aide._code_refus(direct) == "REJ-SUIVI-SANS-APPROBATION"
    assert _maillons_du_type("consentement_suivi_client") == []

    _consentir(par_nom, iid)
    [maillon] = _maillons_du_type("consentement_suivi_client")
    assert maillon["recueilli_par"] == "admin.fictif" and maillon["lead_id"] == "L-E2E-01"
    assert maillon["horodatage"] == DECIDE_LE and maillon["valide_jusqu_au"] == "2030-06-06T14:00:00+00:00"
    assert "telephone" not in json.dumps(maillon) and "latitude" not in json.dumps(maillon)
    etat = aide._resultat(
        _appeler(
            par_nom,
            "m4_lire_consentement_suivi_client",
            {"intervention_id": iid, "canal": "sms", "horodatage_reference": "2030-06-01T09:00:00-04:00"},
        )
    )
    assert etat["etat"] == "actif" and etat["valide_jusqu_au"] == "2030-06-06T14:00:00+00:00"
    expire = aide._resultat(
        _appeler(
            par_nom,
            "m4_lire_consentement_suivi_client",
            {"intervention_id": iid, "canal": "sms", "horodatage_reference": "2030-06-06T14:00:00+00:00"},
        )
    )
    assert expire["etat"] == "expire"


def test_un_consentement_recueilli_apres_son_enregistrement_est_refuse(par_nom, monde):
    iid = _iid(monde)
    _consentir(par_nom, iid, recueilli_le="2031-01-01T10:00:00-05:00")  # après l'approbation figée (2030-05-30)
    assert _maillons_du_type("consentement_suivi_client") == []


def _arguments_message(iid, canal="sms", reference=REFERENCE, retards=()):
    return {
        "intervention_id": iid,
        "canal": canal,
        "horodatage_reference": reference,
        "retards_declares_minutes": list(retards),
        "depart": None,
    }


def test_sans_consentement_aucun_message_n_est_prepare_ni_publie(par_nom, monde):
    avant = aide._etat()
    reponse = _appeler(par_nom, "m4_preparer_message_eta_client", _arguments_message(_iid(monde)))
    assert aide._code_refus(reponse) == "REJ-ETA-CONSENTEMENT-ABSENT"
    assert aide._etat() == avant and _evenements() == []


def test_avec_consentement_le_brouillon_est_prepare_publie_a_m1_et_n_envoie_rien(par_nom, monde):
    iid = _iid(monde)
    _consentir(par_nom, iid)
    reponse = aide._resultat(_appeler(par_nom, "m4_preparer_message_eta_client", _arguments_message(iid)))
    assert (
        reponse["statut"] == "brouillon"
        and reponse["envoi"] == "n3_requis_via_m1"
        and reponse["evenement_publie"] is True
    )
    assert reponse["deja_prepare"] is False and reponse["message"].startswith(
        "Bonjour. L'équipe prévoit arriver chez vous le lundi 3 juin"
    )
    assert "STOP" in reponse["message"] and "pas une promesse" in reponse["message"]
    [ligne] = _evenements()
    charge = json.loads(ligne.charge)
    assert schemas.erreurs_charge("m4.message_client_brouillon_pret", charge) == []
    assert (charge["lead_id"], charge["canal"], charge["statut"], charge["envoi"]) == (
        "L-E2E-01",
        "sms",
        "brouillon",
        "n3_requis_via_m1",
    )
    assert charge["texte"] == reponse["message"] and charge["fenetre_debut"] == reponse["fenetre"]["debut"]
    texte_evenement = ligne.charge
    for interdit in ("latitude", "microdeg", "Client Fictif", "technicien", "eq-a", "eq-b", "adresse", "10 rue"):
        assert interdit not in texte_evenement, interdit
    [enreg] = _maillons_du_type("eta_client_preparee")
    # empreinte du texte seulement
    assert enreg["conserve_jusqu_au"] and "message" not in enreg and "texte" not in enreg
    assert set(enreg) <= {
        "type_entree",
        "horodatage",
        "intervention_id",
        "canal",
        "fenetre_debut",
        "fenetre_fin",
        "message_empreinte",
        "consentement_ligne_id",
        "conserve_jusqu_au",
        "ligne_id",
        "precedent_ligne_id",
    }


def test_preparer_deux_fois_la_meme_fenetre_ne_republie_rien(par_nom, monde):
    iid = _iid(monde)
    _consentir(par_nom, iid)
    premier = aide._resultat(_appeler(par_nom, "m4_preparer_message_eta_client", _arguments_message(iid)))
    second = aide._resultat(_appeler(par_nom, "m4_preparer_message_eta_client", _arguments_message(iid)))
    assert second["deja_prepare"] is True and second["message"] == premier["message"]
    assert len(_evenements()) == 1 and len(_maillons_du_type("eta_client_preparee")) == 1


def test_le_plafond_de_messages_par_chantier_empeche_de_harceler_le_client(par_nom, monde):
    iid = _iid(monde)
    _consentir(par_nom, iid)
    for retards in ([], [45]):  # deux fenêtres différentes : le plafond déclaré est de 2
        aide._resultat(_appeler(par_nom, "m4_preparer_message_eta_client", _arguments_message(iid, retards=retards)))
    reponse = _appeler(par_nom, "m4_preparer_message_eta_client", _arguments_message(iid, retards=[120]))
    assert aide._code_refus(reponse) == "REJ-ETA-QUOTA-MESSAGES"
    assert len(_evenements()) == 2 and len(_maillons_du_type("eta_client_preparee")) == 2


def test_un_retrait_est_immediat_et_bloque_tout_nouveau_message(par_nom, monde):
    iid = _iid(monde)
    _consentir(par_nom, iid)
    aide._resultat(_appeler(par_nom, "m4_preparer_message_eta_client", _arguments_message(iid)))
    retrait = aide._resultat(
        _appeler(
            par_nom,
            "m4_retirer_consentement_suivi_client",
            {
                "intervention_id": iid,
                "canal": "sms",
                "source": "client_stop",
                "horodatage": "2030-06-01T08:00:00-04:00",
            },
        )
    )
    assert retrait["etat"] == "retire"
    reponse = _appeler(par_nom, "m4_preparer_message_eta_client", _arguments_message(iid, retards=[30]))
    assert aide._code_refus(reponse) == "REJ-ETA-CONSENTEMENT-RETIRE"
    assert len(_evenements()) == 1
    # le canal courriel n'a jamais été consenti : il reste absent, pas retiré
    assert (
        aide._code_refus(_appeler(par_nom, "m4_preparer_message_eta_client", _arguments_message(iid, canal="courriel")))
        == "REJ-ETA-CONSENTEMENT-ABSENT"
    )


def test_un_consentement_expire_ne_permet_plus_aucun_message(par_nom, monde):
    iid = _iid(monde)
    _consentir(par_nom, iid)
    reponse = _appeler(
        par_nom, "m4_preparer_message_eta_client", _arguments_message(iid, reference="2030-06-06T15:00:00+00:00")
    )
    assert aide._code_refus(reponse) == "REJ-ETA-CONSENTEMENT-EXPIRE"
    assert _evenements() == []


def test_un_retrait_pose_avant_tout_consentement_bloque_quand_meme(par_nom, monde):
    iid = _iid(monde)
    aide._resultat(
        _appeler(
            par_nom,
            "m4_retirer_consentement_suivi_client",
            {
                "intervention_id": iid,
                "canal": "sms",
                "source": "client_stop",
                "horodatage": "2030-06-01T08:00:00-04:00",
            },
        )
    )
    _consentir(par_nom, iid, recueilli_le="2030-05-29T10:00:00-04:00")  # recueilli AVANT le retrait : ne le lève pas
    reponse = _appeler(par_nom, "m4_preparer_message_eta_client", _arguments_message(iid))
    assert aide._code_refus(reponse) == "REJ-ETA-CONSENTEMENT-RETIRE"


def test_le_consentement_d_un_chantier_ne_sert_pas_a_un_autre(par_nom, monde):
    _consentir(par_nom, _iid(monde, "L-E2E-01"))
    reponse = _appeler(par_nom, "m4_preparer_message_eta_client", _arguments_message(_iid(monde, "L-E2E-02")))
    assert aide._code_refus(reponse) == "REJ-ETA-CONSENTEMENT-ABSENT"


@pytest.mark.parametrize(
    "modif", [{"canal": "pigeon"}, {"horodatage_reference": "demain"}, {"intervention_id": "int-inconnue"}]
)
def test_arguments_invalides_du_message_refuses_sans_ecriture(par_nom, monde, modif):
    iid = _iid(monde)
    _consentir(par_nom, iid)
    avant = aide._etat()
    reponse = _appeler(par_nom, "m4_preparer_message_eta_client", {**_arguments_message(iid), **modif})
    assert reponse["ok"] is False or reponse["resultat"]["accepte"] is False
    assert aide._etat() == avant


def test_le_texte_du_message_passe_le_garde_fou_du_socle_et_un_texte_pollue_serait_refuse():
    from m4_field_ops import eta_client

    from opsys.garde_fou_texte import controler

    fenetre = {"debut": "2030-06-03T09:00:00-04:00", "fin": "2030-06-03T10:00:00-04:00"}
    assert controler(eta_client.composer_message(fenetre), adaptateur.PROFIL_TEXTE_CLIENT) == ()
    sale = (
        eta_client.composer_message(fenetre) + " Appelez le 514-555-0100 ou écrivez à x@exemple.test, 10 rue Fictive."
    )
    assert controler(sale, adaptateur.PROFIL_TEXTE_CLIENT) != ()


def test_aucun_appel_reseau_n_est_possible_pendant_ces_outils(par_nom, monde, monkeypatch):
    import socket

    def interdit(*a, **k):
        raise AssertionError("appel réseau interdit")

    monkeypatch.setattr(socket.socket, "connect", interdit)
    iid = _iid(monde)
    _consentir(par_nom, iid)
    aide._resultat(_appeler(par_nom, "m4_preparer_message_eta_client", _arguments_message(iid)))
    aide._resultat(_appeler(par_nom, "m4_proposer_adequation_equipes", {"intervention_id": iid, "date_cible": LUNDI}))


def test_les_nouveaux_types_de_maillon_gardent_la_chaine_valide(par_nom, monde):
    iid = _iid(monde)
    _consentir(par_nom, iid)
    aide._resultat(_appeler(par_nom, "m4_preparer_message_eta_client", _arguments_message(iid)))
    aide._resultat(_appeler(par_nom, "m4_enregistrer_brouillon_affectation", _arg_brouillon(iid, "eq-b")))
    with stockage.transaction():
        assert aide._registre().valider_chaine() is True
    with stockage.transaction() as cnx:
        assert (
            cnx.execute(
                select(func.count())
                .select_from(EVENEMENTS_SORTANTS)
                .where(EVENEMENTS_SORTANTS.c.type_evenement == "m4.message_client_brouillon_pret")
            ).scalar_one()
            == 1
        )


def _demande_en_cours(nom, arguments):
    """Une demande N3 réservée par une personne (comme `approbations.decider` le fait avant d'exécuter l'outil)."""
    with stockage.transaction() as cnx:
        demande = approbations.creer_demande(cnx, M4, nom, arguments, niveau=Niveau.N3)
        cnx.execute(
            APPROBATIONS.update()
            .where(APPROBATIONS.c.id == demande)
            .values(statut="en_cours", decide_par="admin.fictif", decide_role="admin", decide_le=DECIDE_LE)
        )
    return demande


def test_une_approbation_ne_sert_qu_a_ses_arguments_exacts_consentement_et_affectation(par_nom, monde):
    iid, autre = _iid(monde), _iid(monde, "L-E2E-02")
    aide._resultat(_appeler(par_nom, "m4_enregistrer_brouillon_affectation", _arg_brouillon(iid, "eq-b")))
    arguments = {
        "intervention_id": iid,
        "canal": "sms",
        "enonce_version": "suivi-fr-CA-v1",
        "preuve": {"fictif": True, "reference": "formulaire-42"},
        "recueilli_le": "2030-05-30T10:00:00-04:00",
    }
    demande = _demande_en_cours("m4_enregistrer_consentement_suivi_client", arguments)
    for detourne in ({**arguments, "intervention_id": autre}, {**arguments, "canal": "courriel"}):
        with stockage.transaction(), contexte.executer_demande_approuvee(demande):
            reponse = adaptateur_outil("m4_enregistrer_consentement_suivi_client")(**detourne)
        assert reponse["accepte"] is False and reponse["verdict"]["code"] == "REJ-SUIVI-SANS-APPROBATION"
    assert _maillons_du_type("consentement_suivi_client") == []
    approuvee = {"intervention_id": iid, "equipe_id": "eq-b"}
    demande = _demande_en_cours("m4_approuver_affectation_engageante", approuvee)
    with stockage.transaction(), contexte.executer_demande_approuvee(demande):
        reponse = adaptateur_outil("m4_approuver_affectation_engageante")(intervention_id=iid, equipe_id="eq-a")
    assert reponse["verdict"]["code"] == "REJ-AFFECTATION-SANS-APPROBATION"
    assert _maillons_du_type("affectation_approuvee") == []


def adaptateur_outil(nom):
    return next(o for o in outils() if o.nom == nom).fonction
