"""PLAN T4.1-d : `cedule_tournees.py`, pur, sur un registre EN MÉMOIRE et des positions injectées (aucune base,
aucune clé de chiffrement). Tout est fictif (`fictif: true`) : sites de Repentigny à Joliette aux coordonnées
approximatives (`fixtures/tournees_repentigny_joliette.json`), équipes, durées et paramètres inventés.

Les deux gardes de l'application sont éprouvées séparément : l'ÉTAT des interventions (statut, technicien,
version de la localisation) et l'ENTRÉE du solveur (les coordonnées lues aujourd'hui). Le scénario complet, par
les vrais outils et les vraies clés, est dans `test_cedule_tournees_outils.py`.
"""

from __future__ import annotations

import ast
import copy
import json
from pathlib import Path

import pytest
from m4_field_ops import cedule_tournees, encodage, etats, tournees, verdicts
from m4_field_ops.registre import Registre

FICTIF = True
_SRC = Path(cedule_tournees.__file__).resolve()
_RACINE = Path(__file__).resolve().parents[3]
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "tournees_repentigny_joliette.json").read_text("utf-8"))
SITES = {site["id"]: site for site in FIXTURE["sites"]}
HORODATAGE = "2030-01-01T00:00:00+00:00"
MARQUEUR = {"readiness_ok": True, "lead_id": "", "hash_tete_registre": None,
            "horodatage": HORODATAGE, "empreinte": "cd" * 32}
PARAMETRES = {"facteur_detour_milliemes": 1300, "vitesse_moyenne_kmh": 50, "marge_par_trajet_secondes": 600,
              "iterations": 300, "cout_non_cedule_m": 500000}
FENETRE = {"jours": [0], "debut_min": 480, "fin_min": 1020}
DEPOTS = {"depot-repentigny": SITES["depot-repentigny"], "depot-joliette": SITES["depot-joliette"]}


# -- aides --------------------------------------------------------------------------------------------
def _contrat(lead_id, type_travaux="extension", urgence=False):
    return {"lead_id": lead_id, "conversation_id": f"C-{lead_id}", "type_travaux": type_travaux,
            "ville": "Repentigny", "canal": "telephone", "contact": {"nom": "Client Fictif"},
            "urgence_declaree": urgence}


def _inscrire(registre, lead_id, type_travaux="extension", urgence=False, instant=0):
    accuse, verdict = etats.inscrire_intervention(
        _contrat(lead_id, type_travaux, urgence), {**MARQUEUR, "lead_id": lead_id}, registre,
        f"2030-01-01T00:00:{instant:02d}+00:00", "sel-fictif",
    )
    assert verdict is None, verdict
    return accuse["intervention_id"]


class Positions:
    """`lire_position(registre, lead_id)` fictif : les positions « confirmées » sont un dictionnaire."""

    def __init__(self, sites):
        self.sites = dict(sites)
        self.appels = []

    def __call__(self, registre, lead_id):
        self.appels.append(lead_id)
        site = self.sites.get(lead_id)
        if site is None:
            return None, verdicts.construire_verdict(
                "REJ-COORDONNEES-A-CONFIRMER", detail="coordonnées manquantes : à confirmer")
        return {"latitude_microdegres": site["latitude_microdeg"], "longitude_microdegres": site["longitude_microdeg"],
                "version": 1, "ligne_id": "x"}, None


def _monde(leads=("ch-01", "ch-02", "ch-10"), types=None, urgences=()):
    """Registre en mémoire avec une intervention par lead (lead_id = id du site), positions connues."""
    registre = Registre()
    ids = {}
    for rang, lead in enumerate(leads):
        ids[lead] = _inscrire(registre, lead, (types or {}).get(lead, "extension"), lead in urgences, rang)
    return registre, ids, Positions({lead: SITES[lead] for lead in leads})


def _equipes(depot="depot-repentigny", jours=(0,)):
    def equipe(identifiant, depot_id):
        return {
            "id": identifiant, "competences": ["gouttieres", "revetement"],
            "depot": {"id": depot_id, "latitude_microdegres": DEPOTS[depot_id]["latitude_microdeg"],
                      "longitude_microdegres": DEPOTS[depot_id]["longitude_microdeg"]},
            "quarts": [{"jour": jour, "debut_min": 480, "fin_min": 1020} for jour in jours],
        }
    return [equipe("eq-a", depot), equipe("eq-b", "depot-joliette")]


def _arguments(ids, **remplacements):
    arguments = {
        "equipes": _equipes(),
        "durees_par_type_travaux": {"extension": 150, "ravalement": 120},
        "competences_par_type_travaux": {"extension": [], "ravalement": ["revetement"]},
        "chantiers": [{"intervention_id": iid, "fenetre": dict(FENETRE), "creneau_fige": None}
                      for _lead, iid in sorted(ids.items())],
        "parametres": dict(PARAMETRES),
    }
    arguments.update(remplacements)
    return arguments


def _proposer(registre, ids, positions, arguments=None, moteur="dp", **extra):
    arguments = _arguments(ids) if arguments is None else arguments
    return cedule_tournees.proposer(registre, arguments, positions, HORODATAGE, moteur=moteur, **extra)


def _reussi(couple):
    resultat, verdict = couple
    assert verdict is None, verdict
    return resultat


def _refuse(couple, code, morceau=""):
    resultat, verdict = couple
    assert resultat is None and verdict is not None, resultat
    assert verdict["code"] == code, verdict
    assert morceau in verdict["detail"], verdict
    return verdict


def _maillons(registre, type_entree):
    return [m for m in registre.lire() if m["type_entree"] == type_entree]


# =========================================================================================
# 1. L'urgence : une règle écrite, citée, vérifiable
# =========================================================================================
def test_la_regle_d_urgence_est_vrai_un_faux_zero():
    assert cedule_tournees.urgence_depuis_declaration(True) == (1, None)
    assert cedule_tournees.urgence_depuis_declaration(False) == (0, None)
    assert (cedule_tournees.URGENCE_NORMALE, cedule_tournees.URGENCE_DECLAREE) == (0, 1)
    assert 0 <= cedule_tournees.URGENCE_DECLAREE < tournees.BORNE_URGENCE[1]  # les crans 2 et 3 restent libres


@pytest.mark.parametrize("valeur", [1, 0, "oui", "true", 1.0, [True], {}])
def test_une_urgence_qui_n_est_pas_un_booleen_est_refusee(valeur):
    niveau, verdict = cedule_tournees.urgence_depuis_declaration(valeur)
    assert niveau is None and verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert "booléen" in verdict["detail"]


def test_une_source_absente_est_un_verdict_jamais_un_zero_suppose():
    niveau, verdict = cedule_tournees.urgence_depuis_declaration(None)
    assert niveau is None and verdict["code"] == "REJ-CHAMP-MANQUANT"
    assert "urgence_declaree absente" in verdict["detail"]


def test_la_regle_cite_des_sources_qui_disent_bien_cela():
    regle = cedule_tournees.REGLE_URGENCE
    produit = (_RACINE / "docs" / "produit" / "DEFINITION-PRODUIT.md").read_text(encoding="utf-8")
    assert "DEFINITION-PRODUIT M4.7" in regle and "M4.7 Cédule intelligente" in produit
    assert "urgence" in next(ligne for ligne in produit.splitlines() if ligne.startswith("- M4.7"))
    audit = (_RACINE / "docs" / "departements" / "M4-audit.md").read_text(encoding="utf-8")
    assert "audit M4 risque 10" in regle and "`urgence_declaree` est collecté au contrat mais jamais lu" in audit
    contrats = (_SRC.parent / "contrats.py").read_text(encoding="utf-8")
    assert "contrats.py (booléen strict)" in regle and 'type(contrat["urgence_declaree"]) is not bool' in contrats
    recherche = (_RACINE / "docs" / "research" / "R15-cedule-vrp.md").read_text(encoding="utf-8")
    assert "R15 §4" in regle and "urgence" in recherche
    assert "(1 + urgence)" in regle and tournees.BORNE_URGENCE == (0, 3)
    assert "cout_non_cedule_m" in (_SRC.parent / "tournees.py").read_text(encoding="utf-8")


def test_le_solveur_recoit_l_urgence_convertie_et_le_plan_la_rend():
    registre, ids, positions = _monde(urgences=("ch-02",))
    proposition = _reussi(_proposer(registre, ids, positions))
    assert proposition["urgences"] == {ids["ch-01"]: 0, ids["ch-02"]: 1, ids["ch-10"]: 0}
    maillon = _maillons(registre, "cedule_proposee")[0]
    urgences = {c["id"]: c["urgence"] for c in maillon["entree"]["chantiers"]}
    assert urgences == proposition["urgences"]
    assert "cout_non_cedule_m" in proposition["regle_urgence"]


def test_une_urgence_illisible_au_registre_refuse_la_proposition_en_nommant_l_intervention():
    registre, ids, positions = _monde()
    lecture = registre.lire()
    for maillon in lecture:
        if maillon["intervention_id"] == ids["ch-02"]:
            maillon["urgence_declaree"] = None

    class RegistreFausse(Registre):
        def lire(self, depuis=None):
            return lecture

    verdict = _refuse(_proposer(RegistreFausse(lecture), ids, positions), "REJ-CHAMP-MANQUANT", "urgence_declaree")
    assert ids["ch-02"] in verdict["detail"]


# =========================================================================================
# 2. Proposition : ce que M4 lit, ce qu'il garde, ce qu'il rend
# =========================================================================================
def test_la_proposition_lit_les_interventions_planifiees_et_range_un_maillon_sans_rien_assigner():
    registre, ids, positions = _monde()
    proposition = _reussi(_proposer(registre, ids, positions, propose_par="admin.fictif"))
    assert proposition["mode_distance"] == "haversine_detour" and proposition["mode_bride"] is True
    assert proposition["avertissement"] == cedule_tournees.AVERTISSEMENT_MODE_BRIDE
    assert proposition["solveur"] == "dp-exact" and proposition["deja_proposee"] is False
    assert proposition["non_cedulees"] == [] and proposition["totaux"]["chantiers_cedules"] == 3
    maillons = _maillons(registre, "cedule_proposee")
    assert len(maillons) == 1 and maillons[0]["plan_id"] == proposition["plan_id"]
    assert maillons[0]["propose_par"] == "admin.fictif" and maillons[0]["moteur"] == "dp"
    assert maillons[0]["empreinte_sortie"] == maillons[0]["sortie"]["meta"]["empreinte_sortie"]
    assert maillons[0]["empreinte_entree"] == maillons[0]["sortie"]["meta"]["empreinte_entree"]
    assert maillons[0]["empreinte_etat"] == encodage.empreinte(maillons[0]["etat"])
    assert _maillons(registre, "assignation_technicien") == []  # aucune vérité écrite
    assert all(etats.technicien_assigne(registre, iid) is None for iid in ids.values())
    assert registre.valider_chaine()


def test_la_proposition_ne_regarde_que_les_interventions_au_statut_planifiee():
    registre, ids, positions = _monde(("ch-01", "ch-02", "ch-10"))
    _, verdict = etats.transitionner(ids["ch-10"], "annulee", registre, HORODATAGE)
    assert verdict is None
    arguments = _arguments({k: v for k, v in ids.items() if k != "ch-10"})
    proposition = _reussi(_proposer(registre, ids, positions, arguments))
    assert proposition["totaux"]["chantiers_cedules"] == 2
    assert "ch-10" not in positions.appels  # l'annulée n'est même pas localisée


def test_meme_entree_meme_plan_meme_identifiant_et_rien_d_ecrit_de_plus():
    registre, ids, positions = _monde()
    premiere = _reussi(_proposer(registre, ids, positions))
    taille = registre.taille()
    seconde = _reussi(_proposer(registre, ids, positions))
    assert seconde["plan_id"] == premiere["plan_id"] and seconde["deja_proposee"] is True
    assert registre.taille() == taille
    # Un autre paramètre d'entreprise : un autre plan, un autre identifiant.
    autre = _arguments(ids, parametres={**PARAMETRES, "vitesse_moyenne_kmh": 40})
    troisieme = _reussi(_proposer(registre, ids, positions, autre))
    assert troisieme["plan_id"] != premiere["plan_id"] and registre.taille() == taille + 1


def test_l_identifiant_du_plan_depend_de_l_etat_et_des_deux_empreintes():
    registre, ids, positions = _monde()
    proposition = _reussi(_proposer(registre, ids, positions))
    maillon = _maillons(registre, "cedule_proposee")[0]
    attendu = encodage.empreinte(
        cedule_tournees.VERSION_PROPOSITION, maillon["empreinte_entree"], maillon["empreinte_sortie"],
        maillon["empreinte_etat"])
    assert proposition["plan_id"] == attendu
    etats.assigner_technicien(ids["ch-01"], "eq-b", registre, HORODATAGE)  # l'état change : un autre plan
    autre = _reussi(_proposer(registre, ids, positions))
    assert autre["plan_id"] != proposition["plan_id"] and autre["empreinte_etat"] != proposition["empreinte_etat"]
    assert autre["empreinte_sortie"] == proposition["empreinte_sortie"]  # le solveur ne lit pas l'assignation


def test_le_maillon_garde_l_entree_sans_matrice_donc_sans_coordonnee_de_chantier():
    registre, ids, positions = _monde()
    _reussi(_proposer(registre, ids, positions))
    maillon = _maillons(registre, "cedule_proposee")[0]
    assert set(maillon["entree"]) == {"equipes", "chantiers", "parametres_distance", "parametres"}
    texte = json.dumps(maillon, ensure_ascii=False)
    for lead in ("ch-01", "ch-02", "ch-10"):
        assert str(SITES[lead]["latitude_microdeg"]) not in texte
        assert str(SITES[lead]["longitude_microdeg"]) not in texte
    assert maillon["entree"]["parametres"]["graine"] == cedule_tournees.GRAINE_TECHNIQUE == 0
    assert set(maillon["entree"]["parametres_distance"]) == set(PARAMETRES) - {"iterations", "cout_non_cedule_m"}


def test_la_graine_est_un_reglage_technique_optionnel():
    registre, ids, positions = _monde()
    _reussi(_proposer(registre, ids, positions, _arguments(ids, parametres={**PARAMETRES, "graine": 42})))
    assert _maillons(registre, "cedule_proposee")[0]["entree"]["parametres"]["graine"] == 42


def test_un_chantier_sans_position_lisible_n_entre_pas_dans_la_matrice():
    registre, ids, _ = _monde()
    positions = Positions({lead: SITES[lead] for lead in ("ch-01", "ch-02")})
    proposition = _reussi(_proposer(registre, ids, positions))
    assert [ligne["chantier"] for ligne in proposition["non_cedulees"]] == [ids["ch-10"]]
    assert proposition["non_cedulees"][0]["code"] == "coordonnees_manquantes"
    assert sorted(positions.appels) == ["ch-01", "ch-02", "ch-10"]


def test_un_verdict_de_lecture_l_emporte_sur_une_position_qui_l_accompagnerait():
    """Fail-closed : ``lire_position`` rend ``(position, None)`` ou ``(None, verdict)`` ; si un adaptateur rendait
    les deux, la position n'entrerait pas dans la matrice (le verdict dit « à confirmer »)."""
    registre, ids, _ = _monde()
    base = Positions({lead: SITES[lead] for lead in ("ch-01", "ch-02", "ch-10")})

    def ambigu(registre_lu, lead_id):
        position, _ = base(registre_lu, lead_id)
        verdict = verdicts.construire_verdict("REJ-LOCALISATION-DETRUITE", detail="clé détruite") \
            if lead_id == "ch-10" else None
        return position, verdict

    proposition = _reussi(_proposer(registre, ids, ambigu))
    assert [ligne["chantier"] for ligne in proposition["non_cedulees"]] == [ids["ch-10"]]
    assert proposition["non_cedulees"][0]["code"] == "coordonnees_manquantes"


def test_un_meme_lead_n_est_localise_qu_une_fois():
    registre = Registre()
    ids = {"a": _inscrire(registre, "ch-01", instant=0), "b": _inscrire(registre, "ch-01", instant=1)}
    positions = Positions({"ch-01": SITES["ch-01"]})
    _reussi(_proposer(registre, ids, positions))
    assert positions.appels == ["ch-01"]


def test_les_arguments_ne_sont_pas_modifies_par_la_proposition():
    registre, ids, positions = _monde()
    arguments = _arguments(ids)
    copie = copy.deepcopy(arguments)
    _reussi(_proposer(registre, ids, positions, arguments))
    assert arguments == copie


# =========================================================================================
# 3. « À fournir » : un seul verdict qui dit tout, aucune valeur par défaut
# =========================================================================================
def test_tout_argument_absent_est_dit_en_un_seul_verdict():
    registre, ids, positions = _monde(types={"ch-10": "ravalement"})
    verdict = _refuse(_proposer(registre, ids, positions, {}), "REJ-CHAMP-MANQUANT")
    for cle in ("equipes manquant", "durees_par_type_travaux manquant", "competences_par_type_travaux manquant",
                "chantiers manquant", "parametres manquant"):
        assert cle in verdict["detail"], verdict


def test_durees_competences_fenetres_et_parametres_manquants_sont_tous_listes():
    registre, ids, positions = _monde(types={"ch-10": "ravalement"})
    arguments = _arguments(
        ids, durees_par_type_travaux={"extension": 150}, competences_par_type_travaux={"ravalement": ["revetement"]},
        chantiers=[{"intervention_id": ids["ch-01"], "fenetre": dict(FENETRE), "creneau_fige": None}],
        parametres={"iterations": 300})
    verdict = _refuse(_proposer(registre, ids, positions, arguments), "REJ-CHAMP-MANQUANT")
    detail = verdict["detail"]
    for attendu in ("durees_par_type_travaux.ravalement", "competences_par_type_travaux.extension",
                    f"entrée de l'intervention {ids['ch-02']!r}", f"entrée de l'intervention {ids['ch-10']!r}",
                    "parametres.facteur_detour_milliemes manquant", "entre 1000 et 3000",
                    "parametres.vitesse_moyenne_kmh", "parametres.marge_par_trajet_secondes",
                    "parametres.cout_non_cedule_m"):
        assert attendu in detail, (attendu, detail)
    assert "parametres.iterations" not in detail  # celui-là est fourni


def test_un_champ_null_vaut_absent_sauf_le_creneau_fige_ou_null_dit_aucun():
    registre, ids, positions = _monde()
    chantiers = _arguments(ids)["chantiers"]
    chantiers[0]["fenetre"] = None
    verdict = _refuse(_proposer(registre, ids, positions, _arguments(ids, chantiers=chantiers)),
                      "REJ-CHAMP-MANQUANT", ".fenetre manquant")
    assert "creneau_fige" not in verdict["detail"]
    _reussi(_proposer(registre, ids, positions))  # creneau_fige: null explicite passe


def test_un_creneau_fige_omis_n_est_pas_un_aucun():
    registre, ids, positions = _monde()
    chantiers = [{"intervention_id": iid, "fenetre": dict(FENETRE)} for iid in ids.values()]
    _refuse(_proposer(registre, ids, positions, _arguments(ids, chantiers=chantiers)),
            "REJ-CHAMP-MANQUANT", "creneau_fige manquant")


def test_un_argument_inconnu_ou_de_mauvais_type_est_refuse():
    registre, ids, positions = _monde()
    _refuse(_proposer(registre, ids, positions, {**_arguments(ids), "vehicules": []}),
            "REJ-CONTRAT-INVALIDE", "clés inconnues : vehicules")
    _refuse(_proposer(registre, ids, positions, _arguments(ids, equipes="eq-a")),
            "REJ-CONTRAT-INVALIDE", "equipes : une liste est attendue")
    _refuse(_proposer(registre, ids, positions, _arguments(ids, equipes=[])),
            "REJ-CHAMP-MANQUANT", "equipes manquantes")
    _refuse(_proposer(registre, ids, positions, _arguments(ids, durees_par_type_travaux=[150])),
            "REJ-CONTRAT-INVALIDE", "un objet est attendu")
    _refuse(_proposer(registre, ids, positions, _arguments(ids, durees_par_type_travaux={"extension": "150"})),
            "REJ-CONTRAT-INVALIDE", "durees_par_type_travaux.extension")
    _refuse(_proposer(registre, ids, positions, _arguments(ids, durees_par_type_travaux={"extension": True})),
            "REJ-CONTRAT-INVALIDE", "durees_par_type_travaux.extension")
    _refuse(_proposer(registre, ids, positions, _arguments(ids, competences_par_type_travaux={"extension": "x"})),
            "REJ-CONTRAT-INVALIDE", "competences_par_type_travaux.extension")
    _refuse(_proposer(registre, ids, positions, _arguments(ids, competences_par_type_travaux={"extension": [""]})),
            "REJ-CONTRAT-INVALIDE", "competences_par_type_travaux.extension")
    _refuse(_proposer(registre, ids, positions, _arguments(ids, chantiers={})), "REJ-CONTRAT-INVALIDE",
            "chantiers : une liste est attendue")
    _refuse(_proposer(registre, ids, positions, _arguments(ids, parametres=[])), "REJ-CONTRAT-INVALIDE",
            "parametres : un objet est attendu")
    _refuse(_proposer(registre, ids, positions, _arguments(ids, parametres={**PARAMETRES, "graine_x": 1})),
            "REJ-CONTRAT-INVALIDE", "clés inconnues : graine_x")
    _refuse(cedule_tournees.proposer(registre, [], positions, HORODATAGE), "REJ-CONTRAT-INVALIDE",
            "un objet est attendu")


def test_un_type_de_travaux_inconnu_est_refuse_meme_s_il_n_est_pas_planifie():
    registre, ids, positions = _monde()
    _refuse(_proposer(registre, ids, positions, _arguments(
        ids, durees_par_type_travaux={"extension": 150, "toiture": 60})),
        "REJ-CONTRAT-INVALIDE", "types de travaux inconnus : toiture")


def test_les_equipes_et_leur_depot_sont_controles():
    registre, ids, positions = _monde()
    equipes = _equipes()
    equipes[0]["vehicule"] = "camion"
    _refuse(_proposer(registre, ids, positions, _arguments(ids, equipes=equipes)),
            "REJ-CONTRAT-INVALIDE", "clés inconnues : vehicule")
    equipes = _equipes()
    del equipes[0]["quarts"]
    _refuse(_proposer(registre, ids, positions, _arguments(ids, equipes=equipes)),
            "REJ-CHAMP-MANQUANT", ".quarts manquant")
    equipes = _equipes()
    equipes[1]["depot"] = {
        "id": "depot-joliette", "latitude_microdegres": 46015000.5, "longitude_microdegres": -73445000}
    _refuse(_proposer(registre, ids, positions, _arguments(ids, equipes=equipes)),
            "REJ-CONTRAT-INVALIDE", "latitude_microdegres : entier requis")
    equipes = _equipes()
    equipes[1]["depot"]["id"] = ""
    _refuse(_proposer(registre, ids, positions, _arguments(ids, equipes=equipes)),
            "REJ-CONTRAT-INVALIDE", "depot.id : chaîne non vide requise")
    equipes = _equipes()
    equipes[1]["depot"] = {"id": "depot-joliette", "latitude_microdegres": 46015000}
    _refuse(_proposer(registre, ids, positions, _arguments(ids, equipes=equipes)),
            "REJ-CHAMP-MANQUANT", "longitude_microdegres manquant")
    equipes = _equipes()
    equipes[1]["depot"] = "depot-joliette"
    _refuse(_proposer(registre, ids, positions, _arguments(ids, equipes=equipes)),
            "REJ-CONTRAT-INVALIDE", "un objet est attendu")
    equipes = _equipes()
    equipes[1]["depot"] = {**equipes[0]["depot"], "latitude_microdegres": 45000000}
    _refuse(_proposer(registre, ids, positions, _arguments(ids, equipes=equipes)),
            "REJ-CONTRAT-INVALIDE", "deux positions différentes")
    equipes = _equipes()
    equipes[1]["depot"] = {**equipes[0]["depot"]}  # deux équipes, un même dépôt : permis
    _reussi(_proposer(registre, ids, positions, _arguments(ids, equipes=equipes)))
    _refuse(_proposer(registre, ids, positions, _arguments(ids, equipes=[[]])),
            "REJ-CONTRAT-INVALIDE", "un objet est attendu")


def test_les_entrees_du_solveur_hors_bornes_sont_refusees_par_lui():
    registre, ids, positions = _monde()
    _refuse(_proposer(registre, ids, positions, _arguments(ids, durees_par_type_travaux={"extension": 0})),
            "REJ-CONTRAT-INVALIDE", "duree_min")
    _refuse(_proposer(registre, ids, positions, _arguments(ids, parametres={**PARAMETRES, "iterations": 0})),
            "REJ-CONTRAT-INVALIDE", "iterations")
    trop_court = {**PARAMETRES, "facteur_detour_milliemes": 900}
    _refuse(_proposer(registre, ids, positions, _arguments(ids, parametres=trop_court)),
            "REJ-CONTRAT-INVALIDE", "facteur_detour_milliemes")


def test_les_interventions_a_planifier_sont_controlees():
    registre, ids, positions = _monde()
    _refuse(_proposer(registre, ids, positions, _arguments(ids, intervention_ids=[])),
            "REJ-CONTRAT-INVALIDE", "intervention_ids")
    _refuse(_proposer(registre, ids, positions, _arguments(ids, intervention_ids="x")),
            "REJ-CONTRAT-INVALIDE", "intervention_ids")
    _refuse(_proposer(registre, ids, positions, _arguments(ids, intervention_ids=[ids["ch-01"], ids["ch-01"]])),
            "REJ-CONTRAT-INVALIDE", "en double")
    verdict = _refuse(_proposer(registre, ids, positions, _arguments(ids, intervention_ids=["zzz", ids["ch-01"]])),
                      "REJ-CEDULE-INTERVENTION-NON-PLANIFIABLE", "'zzz'")
    assert ids["ch-01"] not in verdict["detail"]
    _, verdict_annulation = etats.transitionner(ids["ch-01"], "annulee", registre, HORODATAGE)
    assert verdict_annulation is None
    _refuse(_proposer(registre, ids, positions, _arguments(ids, intervention_ids=[ids["ch-01"]])),
            "REJ-CEDULE-INTERVENTION-NON-PLANIFIABLE", "plus au statut planifiee")
    _refuse(_proposer(Registre(), ids, positions), "REJ-CEDULE-RIEN-A-PLANIFIER", "rien à céduler")


def test_une_entree_de_chantier_en_double_ou_inconnue_est_refusee():
    registre, ids, positions = _monde()
    chantiers = _arguments(ids)["chantiers"]
    _refuse(_proposer(registre, ids, positions, _arguments(ids, chantiers=chantiers + [chantiers[0]])),
            "REJ-CONTRAT-INVALIDE", "intervention en double")
    _refuse(_proposer(registre, ids, positions, _arguments(ids, chantiers=[*chantiers, {
        "intervention_id": "z", "fenetre": dict(FENETRE), "creneau_fige": None}])),
        "REJ-CONTRAT-INVALIDE", "intervention inconnue")
    _refuse(_proposer(registre, ids, positions, _arguments(ids, chantiers=[*chantiers, 5])),
            "REJ-CONTRAT-INVALIDE", "un objet est attendu")
    sans_id = [{"fenetre": dict(FENETRE), "creneau_fige": None}, *chantiers]
    _refuse(_proposer(registre, ids, positions, _arguments(ids, chantiers=sans_id)),
            "REJ-CHAMP-MANQUANT", "intervention_id manquant")
    faux_id = [{"intervention_id": 7, "fenetre": dict(FENETRE), "creneau_fige": None}, *chantiers]
    _refuse(_proposer(registre, ids, positions, _arguments(ids, chantiers=faux_id)),
            "REJ-CONTRAT-INVALIDE", "intervention_id : chaîne non vide requise")


def test_l_horodatage_et_le_signataire_sont_valides_avant_toute_ecriture():
    registre, ids, positions = _monde()
    taille = registre.taille()
    _refuse(cedule_tournees.proposer(registre, _arguments(ids), positions, "hier"), "REJ-HORODATAGE-INVALIDE")
    _refuse(cedule_tournees.proposer(registre, _arguments(ids), positions, "2030-01-01T00:00:00"),
            "REJ-HORODATAGE-INVALIDE")
    _refuse(cedule_tournees.proposer(registre, _arguments(ids), positions, HORODATAGE, propose_par=""),
            "REJ-CONTRAT-INVALIDE", "propose_par")
    _refuse(cedule_tournees.proposer(registre, _arguments(ids), positions, HORODATAGE, propose_par=3),
            "REJ-CONTRAT-INVALIDE", "propose_par")
    assert registre.taille() == taille


def test_un_moteur_inconnu_ou_un_solveur_absent_est_le_verdict_du_solveur():
    registre, ids, positions = _monde()
    _refuse(_proposer(registre, ids, positions, moteur="hasard"), "REJ-ENUM-INVALIDE")
    taille = registre.taille()
    grand = ("ch-01", "ch-02", "ch-03", "ch-04", "ch-05", "ch-06", "ch-07", "ch-08", "ch-09", "ch-10", "ch-11",
             "ch-12", "ch-13")
    registre_grand, ids_grand, positions_grand = _monde(grand)
    _refuse(_proposer(registre_grand, ids_grand, positions_grand, moteur="dp"), "REJ-TOURNEES-DP-TROP-GRAND")
    assert _maillons(registre_grand, "cedule_proposee") == [] and registre.taille() == taille


# =========================================================================================
# 4. Application : les deux gardes, l'idempotence, l'écriture
# =========================================================================================
def _proposee(**kwargs):
    registre, ids, positions = _monde(**kwargs)
    return registre, ids, positions, _reussi(_proposer(registre, ids, positions))


def _appliquer(registre, plan_id, positions, par="admin.fictif", instant="2030-01-02T00:00:00+00:00", **extra):
    return cedule_tournees.appliquer(registre, plan_id, positions, instant, par, **extra)


def test_appliquer_assigne_chaque_technicien_et_ecrit_un_marqueur():
    registre, ids, positions, proposition = _proposee()
    application = _reussi(_appliquer(registre, proposition["plan_id"], positions))
    visites = {v["chantier"]: r["equipe"] for r in proposition["plan"] for v in r["visites"]}
    assert len(visites) == 3
    for chantier, equipe in visites.items():
        assert etats.technicien_assigne(registre, chantier) == equipe
    assert {(a["intervention_id"], a["technicien_id"]) for a in application["assignations"]} == set(visites.items())
    assert {a["effet"] for a in application["assignations"]} == {"assignee"}
    assert application["deja_appliquee"] is False and application["appliquee_par"] == "admin.fictif"
    assert application["mode_bride"] is True and "mode bridé" in application["avertissement"]
    marqueurs = _maillons(registre, "cedule_appliquee")
    assert len(marqueurs) == 1 and marqueurs[0]["plan_id"] == proposition["plan_id"]
    assert marqueurs[0]["empreinte_entree"] == proposition["empreinte_entree"]
    assert marqueurs[0]["empreinte_sortie"] == proposition["empreinte_sortie"]
    assert all(etats.statut_courant(registre, iid) == "planifiee" for iid in ids.values())
    assert registre.valider_chaine()


def test_appliquer_deux_fois_ne_reecrit_rien_et_rend_le_meme_resultat():
    registre, ids, positions, proposition = _proposee()
    premiere = _reussi(_appliquer(registre, proposition["plan_id"], positions))
    taille = registre.taille()
    seconde = _reussi(_appliquer(registre, proposition["plan_id"], positions, par="marie.fictif",
                                 instant="2030-01-03T00:00:00+00:00"))
    assert seconde["deja_appliquee"] is True and registre.taille() == taille
    assert seconde["assignations"] == premiere["assignations"]
    assert seconde["appliquee_par"] == "admin.fictif" and seconde["horodatage"] == premiere["horodatage"]


def test_un_technicien_deja_le_bon_n_est_pas_reassigne():
    registre, ids, positions, proposition = _proposee()
    visites = {v["chantier"]: r["equipe"] for r in proposition["plan"] for v in r["visites"]}
    premier = sorted(visites)[0]
    etats.assigner_technicien(premier, visites[premier], registre, HORODATAGE)
    # L'assignation n'entre pas dans l'entrée du solveur, mais dans l'ÉTAT : il faut donc reproposer.
    _refuse(_appliquer(registre, proposition["plan_id"], positions), "REJ-CEDULE-ENTREE-CHANGEE", "technicien_assigne")
    nouvelle = _reussi(_proposer(registre, ids, positions))
    avant = len(_maillons(registre, "assignation_technicien"))
    application = _reussi(_appliquer(registre, nouvelle["plan_id"], positions))
    effets = {a["intervention_id"]: a["effet"] for a in application["assignations"]}
    assert effets[premier] == "deja_assignee"
    assert sorted(effets.values()).count("assignee") == 2
    assert len(_maillons(registre, "assignation_technicien")) == avant + 2


@pytest.mark.parametrize("changement", ["statut", "assignation", "urgence", "type"])
def test_un_changement_d_etat_refuse_l_application_sans_rien_ecrire(changement):
    registre, ids, positions, proposition = _proposee()
    cible = ids["ch-02"]
    if changement == "statut":
        assert etats.transitionner(cible, "annulee", registre, HORODATAGE)[1] is None
    elif changement == "assignation":
        assert etats.assigner_technicien(cible, "eq-b", registre, HORODATAGE)[1] is None
    else:
        # Le registre est append-only : on falsifie ici une COPIE de lecture pour prouver que la garde regarde
        # l'urgence et le type, pas seulement le statut.
        lecture = registre.lire()
        for maillon in lecture:
            if maillon["type_entree"] == "intervention_inscrite" and maillon["intervention_id"] == cible:
                if changement == "urgence":
                    maillon["urgence_declaree"] = not maillon["urgence_declaree"]
                else:
                    maillon["type_travaux"] = "ravalement"

        class RegistreFalsifie(Registre):
            def lire(self, depuis=None):
                return copy.deepcopy(lecture)

        registre = RegistreFalsifie(lecture)
    taille = registre.taille()
    verdict = _refuse(_appliquer(registre, proposition["plan_id"], positions), "REJ-CEDULE-ENTREE-CHANGEE",
                      "proposer de nouveau")
    assert cible in verdict["detail"]
    champ = {"statut": "statut", "assignation": "technicien_assigne", "urgence": "urgence_declaree",
             "type": "type_travaux"}[changement]
    assert f"{champ} :" in verdict["detail"]
    for inchange in ("lead_id", "localisation"):
        assert f"{inchange} :" not in verdict["detail"]  # le détail ne nomme que ce qui a bougé
    assert registre.taille() == taille and _maillons(registre, "cedule_appliquee") == []


def test_une_coordonnee_lue_aujourd_hui_differente_refuse_meme_si_l_etat_est_le_meme():
    """Seconde garde : la version de la localisation est la même (rien au registre), mais la lecture rend une
    autre position (ici, une clé qui déchiffre autrement) : l'entrée du solveur n'est plus la même."""
    registre, ids, positions, proposition = _proposee()
    positions.sites["ch-02"] = {**SITES["ch-02"], "latitude_microdeg": SITES["ch-02"]["latitude_microdeg"] + 90000}
    taille = registre.taille()
    _refuse(_appliquer(registre, proposition["plan_id"], positions), "REJ-CEDULE-ENTREE-CHANGEE",
            "coordonnées confirmées")
    assert registre.taille() == taille


def test_une_position_devenue_illisible_refuse_aussi():
    registre, ids, positions, proposition = _proposee()
    del positions.sites["ch-10"]  # retirée, ou clé détruite : plus de coordonnées
    _refuse(_appliquer(registre, proposition["plan_id"], positions), "REJ-CEDULE-ENTREE-CHANGEE",
            "coordonnées confirmées")


def test_une_ecriture_d_une_coordonnee_sous_le_meme_lead_change_la_reference_de_l_etat():
    registre, ids, positions, proposition = _proposee()
    registre.ajouter({
        "type_entree": "localisation_chantier", "chantier_id": "ch-01", "version": 1, "action": "confirmee",
        "source": "manuel", "precision": "manuel", "rqa_identifiant": None, "rqa_version": None,
        "confirme_par": "admin.fictif", "motif": "", "horodatage": HORODATAGE, "coordonnees_chiffrees": None,
        "empreinte_adresse": "0" * 64,
    })
    verdict = _refuse(_appliquer(registre, proposition["plan_id"], positions), "REJ-CEDULE-ENTREE-CHANGEE",
                      "localisation")
    assert ids["ch-01"] in verdict["detail"]


def test_un_plan_inconnu_ou_des_arguments_vides_sont_des_verdicts():
    registre, ids, positions, proposition = _proposee()
    _refuse(_appliquer(registre, "inconnu", positions), "REJ-CEDULE-PLAN-INTROUVABLE", "'inconnu'")
    _refuse(_appliquer(registre, "", positions), "REJ-CHAMP-VIDE", "plan_id")
    _refuse(_appliquer(registre, None, positions), "REJ-CHAMP-VIDE", "plan_id")
    _refuse(_appliquer(registre, proposition["plan_id"], positions, par=""), "REJ-CHAMP-VIDE", "appliquee_par")
    _refuse(_appliquer(registre, proposition["plan_id"], positions, par=None), "REJ-CHAMP-VIDE", "appliquee_par")
    _refuse(_appliquer(registre, proposition["plan_id"], positions, instant="demain"), "REJ-HORODATAGE-INVALIDE")
    assert _maillons(registre, "cedule_appliquee") == []


def test_un_plan_ne_s_applique_que_s_il_a_ete_propose():
    """Le marqueur d'application d'un autre plan n'ouvre rien : la proposition est requise, par identifiant."""
    registre, ids, positions, proposition = _proposee()
    registre.ajouter({
        "type_entree": "cedule_appliquee", "horodatage": HORODATAGE, "plan_id": "fantome", "appliquee_par": "x",
        "empreinte_entree": "0" * 64, "empreinte_sortie": "0" * 64, "assignations": [], "non_cedulees": [],
    })
    _refuse(_appliquer(registre, "fantome", positions), "REJ-CEDULE-PLAN-INTROUVABLE")


def _forger(registre, proposition, modifier, identifiant):
    """Range à côté un maillon de plan modifié par ``modifier(maillon)`` (le registre est append-only), sous un
    autre plan_id : le maillon d'origine n'est pas touché."""
    maillon = copy.deepcopy(next(
        m for m in registre.lire()
        if m["type_entree"] == "cedule_proposee" and m["plan_id"] == proposition["plan_id"]))
    for cle in ("ligne_id", "precedent_ligne_id"):
        maillon.pop(cle)
    modifier(maillon)
    maillon["plan_id"] = identifiant
    registre.ajouter(maillon)
    return identifiant


def _resceller(maillon):
    sortie = maillon["sortie"]
    sortie["meta"].pop("empreinte_sortie")
    sortie["meta"]["empreinte_sortie"] = encodage.empreinte(sortie)
    maillon["empreinte_sortie"] = sortie["meta"]["empreinte_sortie"]


def test_un_plan_qui_echoue_a_verifier_plan_n_est_jamais_applique():
    registre, ids, positions, proposition = _proposee()

    def deplacer_hors_du_quart(maillon):
        visite = maillon["sortie"]["plan"][0]["visites"][0]
        visite["debut_min"] += 600
        visite["fin_min"] += 600
        _resceller(maillon)

    plan = _forger(registre, proposition, deplacer_hors_du_quart, "forge-hors-quart")
    taille = registre.taille()
    verdict = _refuse(_appliquer(registre, plan, positions), "REJ-TOURNEES-PLAN-INVALIDE")
    assert "quart" in verdict["detail"] or "fenêtre" in verdict["detail"]
    assert registre.taille() == taille


def test_un_plan_dont_un_creneau_fige_a_ete_deplace_est_refuse():
    """Un créneau confirmé au client n'est jamais déplacé : même si le maillon a été forgé, `verifier_plan`
    revoit le créneau figé de l'entrée stockée."""
    registre, ids, positions = _monde()
    figes = {ids["ch-01"]: {"equipe": "eq-a", "jour": 0, "debut_min": 600}}
    chantiers = [{"intervention_id": iid, "fenetre": dict(FENETRE), "creneau_fige": figes.get(iid)}
                 for iid in sorted(ids.values())]
    proposition = _reussi(_proposer(registre, ids, positions, _arguments(ids, chantiers=chantiers)))
    visites = {v["chantier"]: v["debut_min"] for r in proposition["plan"] for v in r["visites"]}
    assert visites[ids["ch-01"]] == 600

    def deplacer_le_fige(maillon):
        for route in maillon["sortie"]["plan"]:
            for visite in route["visites"]:
                if visite["chantier"] == ids["ch-01"]:
                    visite["debut_min"] += 30
                    visite["arrivee_min"] += 30
                    visite["fin_min"] += 30
        _resceller(maillon)

    plan = _forger(registre, proposition, deplacer_le_fige, "forge-fige")
    verdict = _refuse(_appliquer(registre, plan, positions), "REJ-TOURNEES-PLAN-INVALIDE")
    assert "créneau figé non respecté" in verdict["detail"]
    _reussi(_appliquer(registre, proposition["plan_id"], positions))  # le vrai plan, lui, s'applique
    assert etats.technicien_assigne(registre, ids["ch-01"]) == "eq-a"


def test_un_maillon_dont_l_empreinte_de_sortie_ment_est_refuse():
    registre, ids, positions, proposition = _proposee()
    plan = _forger(registre, proposition, lambda m: m.update(empreinte_sortie="0" * 64), "forge-empreinte")
    _refuse(_appliquer(registre, plan, positions), "REJ-TOURNEES-PLAN-INVALIDE", "empreinte de sortie")


def test_un_maillon_dont_l_empreinte_d_entree_ment_est_refuse_comme_entree_changee():
    registre, ids, positions, proposition = _proposee()
    plan = _forger(registre, proposition, lambda m: m.update(empreinte_entree="0" * 64), "forge-entree")
    _refuse(_appliquer(registre, plan, positions), "REJ-CEDULE-ENTREE-CHANGEE", "solveur")


def test_un_plan_sans_visite_ne_s_applique_pas():
    registre, ids, _ = _monde()
    positions = Positions({})  # aucune position confirmée : tout est non cédulé
    proposition = _reussi(_proposer(registre, ids, positions))
    assert proposition["plan"] == [] and len(proposition["non_cedulees"]) == 3
    _refuse(_appliquer(registre, proposition["plan_id"], positions), "REJ-CEDULE-RIEN-A-PLANIFIER", "aucun chantier")
    assert _maillons(registre, "cedule_appliquee") == []


def test_une_assignation_refusee_apres_les_controles_leve_pour_annuler_l_appel_atomique(monkeypatch):
    registre, ids, positions, proposition = _proposee()
    monkeypatch.setattr(
        etats, "assigner_technicien",
        lambda *args, **kwargs: (None, verdicts.construire_verdict("REJ-TRANSITION-ILLEGALE")))
    with pytest.raises(RuntimeError, match="REJ-TRANSITION-ILLEGALE"):
        _appliquer(registre, proposition["plan_id"], positions)


def test_une_non_cedulee_garde_son_assignation_anterieure_et_le_dit():
    registre, ids, _ = _monde()
    etats.assigner_technicien(ids["ch-10"], "eq-b", registre, HORODATAGE)
    positions = Positions({lead: SITES[lead] for lead in ("ch-01", "ch-02")})
    proposition = _reussi(_proposer(registre, ids, positions))
    application = _reussi(_appliquer(registre, proposition["plan_id"], positions))
    assert [(n["chantier"], n["assignation_conservee"]) for n in application["non_cedulees"]] == [
        (ids["ch-10"], "eq-b")]
    assert etats.technicien_assigne(registre, ids["ch-10"]) == "eq-b"
    assert application["non_cedulees"][0]["code"] == "coordonnees_manquantes"


# =========================================================================================
# 5. Garde par analyse du code : pur, sans horloge, sans aléa, sans flottant, sans réseau
# =========================================================================================
def _arbre():
    return ast.parse(_SRC.read_text(encoding="utf-8"))


def test_le_module_est_pur_sans_horloge_ni_alea_ni_opsys():
    autorises = {"__future__", "copy"}
    for noeud in ast.walk(_arbre()):
        if isinstance(noeud, ast.Import):
            for alias in noeud.names:
                assert alias.name in autorises, alias.name
        if isinstance(noeud, ast.ImportFrom):
            assert noeud.module in autorises or noeud.level == 1, (noeud.module, noeud.level)
            if noeud.level == 1:
                assert {a.name for a in noeud.names} <= {
                    "admissibilite", "cedule", "distances", "encodage", "etats", "horodatage", "localisation",
                    "preparation", "tournees", "verdicts"}


def test_le_module_n_a_aucun_flottant_ni_division_ni_appel_d_horloge():
    for noeud in ast.walk(_arbre()):
        assert not (isinstance(noeud, ast.Constant) and isinstance(noeud.value, float))
        assert not (isinstance(noeud, ast.BinOp) and isinstance(noeud.op, ast.Div))
        if isinstance(noeud, ast.Attribute):
            assert noeud.attr not in {"now", "utcnow", "today", "time", "random", "urandom", "monotonic"}
        if isinstance(noeud, ast.Name):
            assert noeud.id not in {"random", "time", "datetime", "float", "socket"}


def test_aucun_stub_ni_todo_dans_le_module():
    texte = _SRC.read_text(encoding="utf-8")
    assert "TODO" not in texte and "FIXME" not in texte and "NotImplementedError" not in texte
    for noeud in ast.walk(_arbre()):
        if isinstance(noeud, ast.FunctionDef):
            corps = [n for n in noeud.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
            assert corps, noeud.name
            assert not all(isinstance(n, ast.Pass) for n in corps), noeud.name


def test_les_verdicts_du_module_sont_tous_au_catalogue():
    codes = {
        noeud.value for noeud in ast.walk(_arbre())
        if isinstance(noeud, ast.Constant) and isinstance(noeud.value, str) and noeud.value.startswith("REJ-")
    }
    assert codes and codes <= verdicts.CODES_M4, codes - verdicts.CODES_M4


# =========================================================================================
# 6. Déploiement : l'image installe le solveur que le code attend
# =========================================================================================
def test_l_image_installe_l_extra_tournees_a_la_version_que_le_code_epingle():
    import re
    import tomllib

    dockerfile = (_RACINE / "deploy" / "Dockerfile").read_text(encoding="utf-8")
    assert "--require-hashes" in dockerfile
    assert '-r "$opsys_lock"' in dockerfile
    assert '0) opsys_lock=/opt/opsys/requirements-runtime.lock.txt ;;' in dockerfile
    assert '1) opsys_lock=/opt/opsys/requirements-ingestion-pdf.lock.txt ;;' in dockerfile
    assert "--no-deps" in dockerfile and "--no-build-isolation -e /opt/opsys" in dockerfile

    verrou = (_RACINE / "requirements-runtime.lock.txt").read_text(encoding="utf-8")
    assert re.search(rf"(?m)^pyvrp=={re.escape(tournees.VERSION_PYVRP)}\s", verrou)
    assert re.search(r"(?m)^reportlab==4\.5\.1\s", verrou)

    projet = tomllib.loads((_RACINE / "pyproject.toml").read_text(encoding="utf-8"))
    assert projet["project"]["optional-dependencies"]["tournees"] == [f"pyvrp=={tournees.VERSION_PYVRP}"]
    assert projet["project"]["optional-dependencies"]["soumission"] == ["reportlab==4.5.1"]
