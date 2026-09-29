"""PLAN T4.12 : la cédule par tournées lit le PROFIL DES ÉQUIPES et fait sortir les interventions de `a_planifier`.

`cedule_tournees.py` pur, sur un registre EN MÉMOIRE, des positions injectées et un profil injecté (`lire_equipes`) :
aucune base, aucune clé de chiffrement. Le scénario par les vrais outils, le vrai bus et le vrai profil du fichier est
dans `test_equipes_cedule.py`. Tout est fictif (`fictif: true`) : Repentigny à Joliette, coordonnées approximatives
(`fixtures/tournees_repentigny_joliette.json`).

Les volets matériel et météo de la préparation n'ont pas encore de source (T4.14, T4.13) : aucune intervention n'est
« prête » en vrai. Les tests de sortie SIMULENT ces deux volets (`futurs_ok`) pour prouver la plomberie ; le test
« sans les volets futurs » prouve que la porte reste fermée aujourd'hui.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from m4_field_ops import cedule_tournees, encodage, etats, preparation, verdicts
from m4_field_ops.registre import Registre

FICTIF = True
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "tournees_repentigny_joliette.json").read_text("utf-8"))
SITES = {site["id"]: site for site in FIXTURE["sites"]}
HORODATAGE = "2030-01-01T00:00:00+00:00"
PARAMETRES = {"facteur_detour_milliemes": 1300, "vitesse_moyenne_kmh": 50, "marge_par_trajet_secondes": 600,
              "iterations": 300, "cout_non_cedule_m": 500000}
FENETRE = {"jours": [0], "debut_min": 480, "fin_min": 1020}
LEADS = ("ch-01", "ch-02", "ch-10")


@pytest.fixture(autouse=True)
def _services(declarer_services):
    declarer_services()


@pytest.fixture
def futurs_ok(monkeypatch):
    """Simule T4.14 (matériel) et T4.13 (météo) : deux volets vérifiés. Prouve la plomberie, jamais le produit."""
    def ok(_registre, _inscription, _lire_position, _lire_equipes):
        return {"statut": "ok", "manque": None, "detail": "simulé par le test"}

    monkeypatch.setattr(preparation, "_VOLETS", tuple(
        (nom, ok if nom in ("materiel", "meteo") else fonction) for nom, fonction in preparation._VOLETS))


# -- aides --------------------------------------------------------------------------------------------
def _lead(lead_id, service="gouttieres", urgence=False):
    return {
        "schema_version": 2, "lead_id": lead_id, "conversation_id": f"conv-{lead_id}",
        "contact": {"nom": "Client Fictif", "telephone": "418-555-0100"}, "service": service,
        "ville": "Repentigny", "urgence_declaree": urgence, "canal": "texte",
    }


class Positions:
    """`lire_position(registre, lead_id)` fictif : les positions « confirmées » sont un dictionnaire."""

    def __init__(self, sites):
        self.sites = dict(sites)

    def __call__(self, registre, lead_id):
        site = self.sites.get(lead_id)
        if site is None:
            return None, verdicts.construire_verdict(
                "REJ-COORDONNEES-A-CONFIRMER", detail=f"coordonnées manquantes : à confirmer ({lead_id})")
        return {"latitude_microdegres": site["latitude_microdeg"], "longitude_microdegres": site["longitude_microdeg"],
                "version": 1, "ligne_id": "x"}, None


def _monde(leads=LEADS, services=None, urgences=()):
    """Registre en mémoire : une intervention `a_planifier` par lead (lead_id = id du site), positions connues."""
    registre = Registre()
    ids = {}
    for rang, lead in enumerate(leads):
        accuse, verdict = etats.inscrire_depuis_devis(
            registre, f"DEVIS-{lead}", _lead(lead, (services or {}).get(lead, "gouttieres"), lead in urgences),
            "sel-fictif", f"2030-01-01T00:00:{rang:02d}+00:00")
        assert verdict is None, verdict
        ids[lead] = accuse["intervention_id"]
    return registre, ids, Positions({lead: SITES[lead] for lead in leads})


def _depot(identifiant):
    site = SITES[identifiant]
    return {"id": identifiant, "latitude_microdegres": site["latitude_microdeg"],
            "longitude_microdegres": site["longitude_microdeg"]}


def _profil(**surcharges):
    profil = {
        "liste": [
            {"id": identifiant, "membres": [f"membre-{identifiant}.fictif"],
             "competences": ["gouttieres", "revetement"], "depot": _depot(depot),
             "quarts": [{"jour": 0, "debut_min": 480, "fin_min": 1020}]}
            for identifiant, depot in (("eq-a", "depot-repentigny"), ("eq-b", "depot-joliette"))
        ],
        "services": {
            "gouttieres": {"duree_min": 90, "competences": ["gouttieres"]},
            "revetement": {"duree_min": 120, "competences": ["revetement"]},
            "reparation": {"duree_min": 60, "competences": []},
        },
        "cedule": dict(PARAMETRES),
        "fenetre_par_defaut": dict(FENETRE),
    }
    profil.update(surcharges)
    return profil


def _lecteur(profil=None, verdict=None):
    return lambda: (profil, verdict)


def _arguments_equivalents(ids, profil):
    """Ce que le profil dit, écrit à la main comme arguments : la surcharge complète."""
    return {
        "equipes": [{cle: copy.deepcopy(e[cle]) for cle in ("id", "competences", "depot", "quarts")}
                    for e in profil["liste"]],
        "durees_par_service": {s: v["duree_min"] for s, v in profil["services"].items()},
        "competences_par_service": {s: list(v["competences"]) for s, v in profil["services"].items()},
        "chantiers": [{"intervention_id": iid, "fenetre": dict(FENETRE), "creneau_fige": None}
                      for _lead, iid in sorted(ids.items())],
        "parametres": dict(PARAMETRES),
    }


def _proposer(registre, positions, arguments=None, profil=None, verdict_profil=None, intervention_ids=None):
    lecteur = _lecteur(_profil() if profil is None and verdict_profil is None else profil, verdict_profil)
    donnes = {} if arguments is None else dict(arguments)
    if intervention_ids is not None:
        donnes["intervention_ids"] = intervention_ids
    return cedule_tournees.proposer(registre, donnes, positions, HORODATAGE, moteur="dp", lire_equipes=lecteur)


def _appliquer(registre, plan_id, positions, profil=None, verdict_profil=None):
    lecteur = _lecteur(_profil() if profil is None and verdict_profil is None else profil, verdict_profil)
    return cedule_tournees.appliquer(
        registre, plan_id, positions, HORODATAGE, "admin.fictif", lire_equipes=lecteur)


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


def _octets(objet):
    return json.dumps(objet, sort_keys=True, ensure_ascii=False)


# =========================================================================================
# 1. Le profil seul donne les mêmes octets que les arguments équivalents
# =========================================================================================
def test_le_profil_seul_donne_le_meme_plan_que_les_arguments_equivalents(futurs_ok):
    registre_a, ids_a, positions_a = _monde()
    registre_b, ids_b, positions_b = _monde()
    assert ids_a == ids_b
    par_arguments = _reussi(_proposer(registre_a, positions_a, _arguments_equivalents(ids_a, _profil())))
    par_profil = _reussi(_proposer(registre_b, positions_b))  # AUCUN argument

    maillon_a, maillon_b = _maillons(registre_a, "cedule_proposee")[0], _maillons(registre_b, "cedule_proposee")[0]
    assert _octets(maillon_a["sortie"]) == _octets(maillon_b["sortie"]), "le plan : les mêmes octets"
    assert _octets(maillon_a["entree"]) == _octets(maillon_b["entree"])
    assert par_arguments["plan_id"] == par_profil["plan_id"]
    assert par_arguments["empreinte_entree"] == par_profil["empreinte_entree"]
    assert par_arguments["empreinte_sortie"] == par_profil["empreinte_sortie"]
    assert par_profil["totaux"]["chantiers_cedules"] == 3 and par_profil["non_cedulees"] == []
    # la seule différence est tracée : d'où vient chaque valeur
    assert {v for k, v in par_arguments["provenance"].items() if k != "chantiers"} == {"surcharge"}
    assert {v for k, v in par_profil["provenance"].items() if k != "chantiers"} == {"profil"}


def test_la_provenance_dit_profil_pour_chaque_valeur_qu_aucun_argument_ne_donne(futurs_ok):
    registre, ids, positions = _monde()
    proposition = _reussi(_proposer(registre, positions))
    assert proposition["provenance"] == {
        "equipes": "profil", "parametres": "profil", "durees_par_service": "profil",
        "competences_par_service": "profil", "chantiers": {iid: "profil" for iid in sorted(ids.values())},
    }
    maillon = _maillons(registre, "cedule_proposee")[0]
    assert maillon["provenance"] == proposition["provenance"]
    assert maillon["empreinte_profil"] == encodage.empreinte("profil-equipes", _profil())


def test_des_arguments_complets_sont_tous_des_surcharges_et_le_maillon_n_a_pas_d_empreinte_de_profil(futurs_ok):
    registre, ids, positions = _monde()
    proposition = _reussi(_proposer(registre, positions, _arguments_equivalents(ids, _profil())))
    assert set(proposition["provenance"]) == {
        "equipes", "parametres", "durees_par_service", "competences_par_service", "chantiers"}
    assert {v for k, v in proposition["provenance"].items() if k != "chantiers"} == {"surcharge"}
    assert set(proposition["provenance"]["chantiers"].values()) == {"surcharge"}
    assert _maillons(registre, "cedule_proposee")[0]["empreinte_profil"] is None


def test_un_argument_remplace_la_cle_du_profil_et_le_dit(futurs_ok):
    registre, ids, positions = _monde()
    proposition = _reussi(_proposer(registre, positions, {"parametres": {**PARAMETRES, "iterations": 77}}))
    assert proposition["provenance"]["parametres"] == "surcharge"
    assert proposition["provenance"]["equipes"] == "profil"
    maillon = _maillons(registre, "cedule_proposee")[0]
    assert maillon["entree"]["parametres"]["iterations"] == 77, "l'argument gagne sur le profil (500 -> 77)"
    assert maillon["empreinte_profil"] is not None, "d'autres valeurs viennent encore du profil"
    # une surcharge est la clé ENTIÈRE, jamais une fusion : un réglage oublié n'est pas repris du profil
    partiel = {c: v for c, v in PARAMETRES.items() if c != "vitesse_moyenne_kmh"}
    verdict = _refuse(_proposer(registre, positions, {"parametres": partiel}), "REJ-CHAMP-MANQUANT",
                      "parametres.vitesse_moyenne_kmh")
    assert "opsys equipes declarer" in verdict["detail"]


def test_la_surcharge_de_durees_change_le_plan_donc_son_identifiant(futurs_ok):
    registre, ids, positions = _monde()
    profil = _reussi(_proposer(registre, positions))
    surcharge = _reussi(_proposer(registre, positions, {"durees_par_service": {"gouttieres": 200}}))
    assert surcharge["plan_id"] != profil["plan_id"]
    assert surcharge["provenance"]["durees_par_service"] == "surcharge"
    assert surcharge["provenance"]["competences_par_service"] == "profil"


def test_proposer_deux_fois_du_profil_ou_d_arguments_equivalents_n_ecrit_rien_de_plus(futurs_ok):
    registre, ids, positions = _monde()
    premiere = _reussi(_proposer(registre, positions))
    taille = registre.taille()
    encore = _reussi(_proposer(registre, positions))
    assert encore["plan_id"] == premiere["plan_id"] and encore["deja_proposee"] is True
    assert registre.taille() == taille and len(_maillons(registre, "cedule_proposee")) == 1
    equivalente = _reussi(_proposer(registre, positions, _arguments_equivalents(ids, _profil())))
    assert equivalente["plan_id"] == premiere["plan_id"] and equivalente["deja_proposee"] is True
    assert registre.taille() == taille
    assert equivalente["provenance"]["equipes"] == "surcharge", "la provenance est celle de CET appel"
    assert _maillons(registre, "cedule_proposee")[0]["provenance"]["equipes"] == "profil", "celle du plan est gardée"


def test_un_service_du_profil_que_le_lot_n_utilise_pas_ne_gene_pas_la_cedule(futurs_ok):
    """Seules les durées et compétences des services À PLANIFIER passent au solveur : une durée écrite pour un service
    retiré depuis du profil de services (que `opsys verifier` signale) ne bloque pas la cédule des autres."""
    registre, ids, positions = _monde()
    profil = _profil()
    profil["services"]["service_retire"] = {"duree_min": 45, "competences": ["gouttieres"]}
    proposition = _reussi(_proposer(registre, positions, profil=profil))
    assert proposition["totaux"]["chantiers_cedules"] == 3
    assert proposition["provenance"]["durees_par_service"] == "profil"


def test_le_profil_n_est_jamais_modifie_par_la_proposition(futurs_ok):
    registre, _, positions = _monde()
    profil = _profil()
    avant = copy.deepcopy(profil)
    cedule_tournees.proposer(registre, {}, positions, HORODATAGE, moteur="dp", lire_equipes=_lecteur(profil))
    assert profil == avant


def test_les_membres_n_entrent_pas_dans_le_maillon_du_plan(futurs_ok):
    registre, _, positions = _monde()
    _reussi(_proposer(registre, positions))
    texte = json.dumps(_maillons(registre, "cedule_proposee")[0], ensure_ascii=False)
    assert "membre-eq-a" not in texte and "membres" not in texte


# =========================================================================================
# 2. Sans profil : un verdict qui dit quoi déclarer, jamais un repli
# =========================================================================================
VERDICT_ABSENT = {
    "code": "REJ-EQUIPES-NON-CONFIGUREES",
    "detail": "aucun profil des équipes déclaré : `opsys equipes declarer --depuis <fichier> --par <nom>`",
}
VERDICT_INVALIDE = {"code": "REJ-PROFIL-INVALIDE", "detail": "profil d'entreprise invalide : quart mal formé"}


def _monde_v1(leads=LEADS):
    """Interventions `planifiee` de leads v1 (gelés) : elles ne passent pas par la préparation."""
    registre = Registre()
    ids = {}
    for rang, lead in enumerate(leads):
        accuse, verdict = etats.inscrire_intervention(
            {"lead_id": lead, "conversation_id": f"C-{lead}", "type_travaux": "extension", "ville": "Repentigny",
             "canal": "telephone", "contact": {"nom": "Client Fictif"}, "urgence_declaree": False},
            {"readiness_ok": True, "lead_id": lead, "hash_tete_registre": None, "horodatage": HORODATAGE,
             "empreinte": "cd" * 32}, registre, f"2030-01-01T00:00:{rang:02d}+00:00", "sel-fictif")
        assert verdict is None, verdict
        ids[lead] = accuse["intervention_id"]
    return registre, ids, Positions({lead: SITES[lead] for lead in leads})


def test_sans_profil_ni_argument_le_verdict_liste_tout_et_dit_ou_le_declarer():
    registre, ids, positions = _monde_v1()
    avant = registre.taille()
    verdict = _refuse(_proposer(registre, positions, profil=None, verdict_profil=VERDICT_ABSENT), "REJ-CHAMP-MANQUANT")
    for cle in ("equipes manquant", "durees_par_type_travaux manquant", "competences_par_type_travaux manquant",
                "chantiers manquant", "parametres manquant"):
        assert cle in verdict["detail"], verdict
    assert "opsys equipes declarer --depuis" in verdict["detail"]
    assert registre.taille() == avant, "rien n'est écrit"


def test_un_profil_invalide_garde_son_code_jamais_lu_comme_absent():
    registre, _, positions = _monde_v1()
    verdict = _refuse(_proposer(registre, positions, profil=None, verdict_profil=VERDICT_INVALIDE),
                      "REJ-PROFIL-INVALIDE", "quart mal formé")
    assert "equipes manquant" in verdict["detail"]


def test_un_profil_invalide_n_empeche_pas_des_arguments_complets():
    """Des arguments complets ne lisent pas le profil : la surcharge est totale, l'invalidité est sans objet."""
    registre, ids, positions = _monde_v1()
    arguments = {
        "equipes": _arguments_equivalents(ids, _profil())["equipes"],
        "durees_par_type_travaux": {"extension": 150}, "competences_par_type_travaux": {"extension": []},
        "chantiers": [{"intervention_id": iid, "fenetre": dict(FENETRE), "creneau_fige": None} for iid in ids.values()],
        "parametres": dict(PARAMETRES),
    }
    proposition = _reussi(_proposer(registre, positions, arguments, profil=None, verdict_profil=VERDICT_INVALIDE))
    assert {v for k, v in proposition["provenance"].items() if k != "chantiers"} == {"surcharge"}
    assert set(proposition["provenance"]["chantiers"].values()) == {"surcharge"}
    assert _maillons(registre, "cedule_proposee")[0]["empreinte_profil"] is None


def test_sans_lecture_du_profil_le_comportement_d_avant_t4_12_est_intact():
    registre, ids, positions = _monde_v1()
    verdict = _refuse(cedule_tournees.proposer(registre, {}, positions, HORODATAGE, moteur="dp"), "REJ-CHAMP-MANQUANT")
    assert "opsys equipes declarer" not in verdict["detail"], "aucun profil n'est en jeu : pas de renvoi au profil"


def test_un_profil_sans_reglages_de_cedule_dit_ce_qui_manque_sans_rien_inventer(futurs_ok):
    registre, ids, positions = _monde()
    sans_reglages = _profil()
    del sans_reglages["cedule"]
    avant = registre.taille()
    verdict = _refuse(_proposer(registre, positions, profil=sans_reglages), "REJ-CHAMP-MANQUANT",
                      "parametres manquant")
    assert "equipes manquant" not in verdict["detail"] and "durees_par_service manquant" not in verdict["detail"]
    assert "opsys equipes declarer" in verdict["detail"]
    assert registre.taille() == avant
    # ni un réglage d'un autre, ni un défaut : l'argument comble le trou, et la provenance le dit
    proposition = _reussi(_proposer(registre, positions, {"parametres": dict(PARAMETRES)}, profil=sans_reglages))
    assert proposition["provenance"]["parametres"] == "surcharge" and proposition["provenance"]["equipes"] == "profil"


def test_un_service_absent_du_profil_rend_l_intervention_non_prete_et_le_dit(futurs_ok):
    registre, ids, positions = _monde(services={"ch-10": "reparation"})
    profil = _profil()
    del profil["services"]["reparation"]
    proposition = _reussi(_proposer(registre, positions, profil=profil))
    assert proposition["totaux"]["chantiers_cedules"] == 2
    (non_prete,) = proposition["non_pretes"]
    assert non_prete["intervention_id"] == ids["ch-10"]
    (a_fournir,) = non_prete["a_fournir"]
    assert a_fournir["volet"] == "equipe" and "'reparation'" in a_fournir["manque"]
    assert "opsys equipes declarer" in a_fournir["manque"]


def test_une_surcharge_incomplete_de_durees_nomme_le_service_oublie_jamais_repris_du_profil(futurs_ok):
    registre, ids, positions = _monde(services={"ch-10": "revetement"})
    verdict = _refuse(_proposer(registre, positions, {"durees_par_service": {"gouttieres": 90}}),
                      "REJ-CHAMP-MANQUANT", "durees_par_service.revetement manquant")
    assert "competences_par_service" not in verdict["detail"]


def test_les_tables_v1_restent_des_arguments_meme_avec_un_profil():
    registre, ids, positions = _monde_v1()
    verdict = _refuse(_proposer(registre, positions), "REJ-CHAMP-MANQUANT")  # profil complet, leads v1
    assert "durees_par_type_travaux manquant" in verdict["detail"]
    assert "competences_par_type_travaux manquant" in verdict["detail"]
    assert "equipes manquant" not in verdict["detail"] and "parametres manquant" not in verdict["detail"]
    # avec ces deux tables, le reste vient du profil (la fenêtre par défaut ne couvre que les a_planifier)
    verdict = _refuse(_proposer(registre, positions, {"durees_par_type_travaux": {"extension": 150},
                                                       "competences_par_type_travaux": {"extension": []}}),
                      "REJ-CHAMP-MANQUANT")
    assert "chantiers manquant" in verdict["detail"] and "fenetre_par_defaut" in verdict["detail"]
    assert "durees_par_type_travaux manquant" not in verdict["detail"] and "equipes manquant" not in verdict["detail"]


# =========================================================================================
# 3. Chantiers : la fenêtre par défaut ne sert qu'à une intervention a_planifier, sans créneau figé
# =========================================================================================
def test_une_intervention_a_planifier_sans_entree_prend_la_fenetre_par_defaut_et_aucun_creneau_fige(futurs_ok):
    registre, ids, positions = _monde()
    _reussi(_proposer(registre, positions))
    chantiers = _maillons(registre, "cedule_proposee")[0]["entree"]["chantiers"]
    assert {c["id"]: c["fenetre"] for c in chantiers} == {iid: FENETRE for iid in ids.values()}
    assert all(c["creneau_fige"] is None for c in chantiers)


def test_l_entree_d_un_chantier_fait_foi_sur_la_fenetre_par_defaut(futurs_ok):
    registre, ids, positions = _monde()
    etroite = {"jours": [0], "debut_min": 600, "fin_min": 900}
    entree = {"intervention_id": ids["ch-02"], "fenetre": etroite, "creneau_fige": None}
    proposition = _reussi(_proposer(registre, positions, {"chantiers": [entree]}))
    chantiers = {c["id"]: c["fenetre"] for c in _maillons(registre, "cedule_proposee")[0]["entree"]["chantiers"]}
    assert chantiers[ids["ch-02"]] == etroite and chantiers[ids["ch-01"]] == FENETRE
    assert proposition["provenance"]["chantiers"] == {
        ids["ch-01"]: "profil", ids["ch-02"]: "surcharge", ids["ch-10"]: "profil"}


def test_sans_fenetre_par_defaut_le_verdict_nomme_chaque_intervention(futurs_ok):
    registre, ids, positions = _monde()
    profil = _profil()
    del profil["fenetre_par_defaut"]
    verdict = _refuse(_proposer(registre, positions, profil=profil), "REJ-CHAMP-MANQUANT", "chantiers manquant")
    assert "fenetre_par_defaut" in verdict["detail"] and "aucun créneau figé" in verdict["detail"]
    # une entrée pour chacune comble le trou, jamais une fenêtre inventée
    chantiers = [{"intervention_id": iid, "fenetre": dict(FENETRE), "creneau_fige": None} for iid in ids.values()]
    assert _reussi(_proposer(registre, positions, {"chantiers": chantiers}, profil=profil))["totaux"][
        "chantiers_cedules"] == 3
    # une seule entrée : les autres sont nommées
    verdict = _refuse(_proposer(registre, positions, {"chantiers": chantiers[:1]}, profil=profil),
                      "REJ-CHAMP-MANQUANT", "entrée de l'intervention")
    assert ids["ch-02"] in verdict["detail"] or ids["ch-10"] in verdict["detail"]


def test_une_intervention_planifiee_exige_toujours_son_entree_et_son_creneau_fige():
    """Une intervention planifiée à la main a pu se voir promettre un créneau : le profil ne le suppose jamais nul."""
    registre, ids, positions = _monde_v1()
    arguments = {"durees_par_type_travaux": {"extension": 150}, "competences_par_type_travaux": {"extension": []}}
    verdict = _refuse(_proposer(registre, positions, arguments), "REJ-CHAMP-MANQUANT", "chantiers manquant")
    assert "creneau_fige" in verdict["detail"]
    une_entree = [{"intervention_id": ids["ch-01"], "fenetre": dict(FENETRE), "creneau_fige": None}]
    verdict = _refuse(_proposer(registre, positions, {**arguments, "chantiers": une_entree}), "REJ-CHAMP-MANQUANT",
                      "chantiers : entrée de l'intervention")
    assert ids["ch-02"] in verdict["detail"] and ids["ch-10"] in verdict["detail"] and ids["ch-01"] not in verdict[
        "detail"]


# =========================================================================================
# 4. Sortie de a_planifier : la cédule ne prend que ce qui est PRÊT
# =========================================================================================
def test_sans_les_volets_futurs_la_porte_reste_fermee_et_dit_ce_qui_manque():
    registre, ids, positions = _monde()
    avant = registre.taille()
    verdict = _refuse(_proposer(registre, positions), "REJ-CEDULE-RIEN-A-PLANIFIER", "a_planifier non prêtes")
    for iid in ids.values():
        assert iid in verdict["detail"]
    for morceau in ("materiel", "meteo", "m4_verifier_preparation"):
        assert morceau in verdict["detail"], morceau
    assert verdict["detail"].count("materiel : ") == 1, "ce que l'entreprise doit fournir n'est dit qu'une fois"
    demande = _refuse(_proposer(registre, positions, intervention_ids=[ids["ch-01"]]),
                      "REJ-CEDULE-PREPARATION-NON-PRETE", ids["ch-01"])
    assert "m4_verifier_preparation" in demande["detail"]
    assert registre.taille() == avant


def test_sans_profil_le_verdict_des_a_planifier_dit_quoi_declarer_une_seule_fois():
    registre, ids, positions = _monde()
    verdict = _refuse(_proposer(registre, positions, profil=None, verdict_profil=VERDICT_ABSENT),
                      "REJ-CEDULE-RIEN-A-PLANIFIER", "à fournir : equipe : aucun profil des équipes déclaré")
    assert verdict["detail"].count("opsys equipes declarer --depuis") == 1
    assert all(iid in verdict["detail"] for iid in ids.values())


def test_la_cedule_prend_les_a_planifier_pretes_et_rend_les_autres_avec_ce_qui_leur_manque(futurs_ok):
    registre, ids, _ = _monde()
    positions = Positions({lead: SITES[lead] for lead in ("ch-01", "ch-02")})  # ch-10 : adresse jamais confirmée
    proposition = _reussi(_proposer(registre, positions))
    assert proposition["totaux"]["chantiers_cedules"] == 2
    assert [ligne["intervention_id"] for ligne in proposition["non_pretes"]] == [ids["ch-10"]]
    ligne = proposition["non_pretes"][0]
    assert ligne["statut_preparation"] == "bloque" and [f["volet"] for f in ligne["a_fournir"]] == ["adresse"]
    assert set(_maillons(registre, "cedule_proposee")[0]["entree"]["chantiers"][k]["id"] for k in (0, 1)) == {
        ids["ch-01"], ids["ch-02"]}


def test_une_intervention_demandee_qui_n_est_pas_prete_refuse_toute_la_proposition(futurs_ok):
    registre, ids, _ = _monde()
    positions = Positions({lead: SITES[lead] for lead in ("ch-01", "ch-02")})
    avant = registre.taille()
    _refuse(_proposer(registre, positions, intervention_ids=[ids["ch-01"], ids["ch-10"]]),
            "REJ-CEDULE-PREPARATION-NON-PRETE", ids["ch-10"])
    assert registre.taille() == avant
    proposition = _reussi(_proposer(registre, positions, intervention_ids=[ids["ch-01"], ids["ch-02"]]))
    assert proposition["non_pretes"] == [] and proposition["totaux"]["chantiers_cedules"] == 2


def test_l_etat_d_une_a_planifier_porte_l_empreinte_de_sa_preparation_et_pas_celui_d_une_planifiee(futurs_ok):
    registre, ids, positions = _monde()
    _reussi(_proposer(registre, positions))
    etat = _maillons(registre, "cedule_proposee")[0]["etat"]
    assert {ligne["statut"] for ligne in etat} == {"a_planifier"}
    for ligne in etat:
        verdict, _ = preparation.evaluer(registre, ligne["intervention_id"], positions, _lecteur(_profil()))
        assert ligne["preparation"] == verdict["empreinte"]
    # une planifiee n'a pas cette clé : les plans d'avant T4.12 gardent leurs octets
    registre_v1, ids_v1, positions_v1 = _monde_v1()
    arguments = {
        "durees_par_type_travaux": {"extension": 150}, "competences_par_type_travaux": {"extension": []},
        "chantiers": [{"intervention_id": iid, "fenetre": dict(FENETRE), "creneau_fige": None}
                      for iid in ids_v1.values()],
    }
    _reussi(_proposer(registre_v1, positions_v1, arguments))
    assert all("preparation" not in ligne for ligne in _maillons(registre_v1, "cedule_proposee")[0]["etat"])


def test_planifiees_et_a_planifier_pretes_entrent_dans_le_meme_plan(futurs_ok):
    registre, ids, positions = _monde(("ch-01", "ch-02"))
    accuse, verdict = etats.inscrire_intervention(
        {"lead_id": "ch-10", "conversation_id": "C-ch-10", "type_travaux": "extension", "ville": "Joliette",
         "canal": "telephone", "contact": {"nom": "Client Fictif"}, "urgence_declaree": False},
        {"readiness_ok": True, "lead_id": "ch-10", "hash_tete_registre": None, "horodatage": HORODATAGE,
         "empreinte": "cd" * 32}, registre, "2030-01-01T00:00:09+00:00", "sel-fictif")
    assert verdict is None
    positions = Positions({lead: SITES[lead] for lead in ("ch-01", "ch-02", "ch-10")})
    arguments = {
        "durees_par_type_travaux": {"extension": 150}, "competences_par_type_travaux": {"extension": []},
        "chantiers": [{"intervention_id": accuse["intervention_id"], "fenetre": dict(FENETRE), "creneau_fige": None}],
    }
    proposition = _reussi(_proposer(registre, positions, arguments))
    assert proposition["totaux"]["chantiers_cedules"] == 3
    assert proposition["provenance"]["durees_par_type_travaux"] == "surcharge"
    plan = _reussi(_appliquer(registre, proposition["plan_id"], positions))
    sorties = {a["intervention_id"]: a["transition"] for a in plan["assignations"]}
    assert sorties[accuse["intervention_id"]] is None
    assert [t for i, t in sorties.items() if i != accuse["intervention_id"]] == ["a_planifier->planifiee"] * 2


# =========================================================================================
# 5. Application : la transition, la porte d'empreinte, tout refus sans écriture
# =========================================================================================
def _proposition_prete(futurs_ok_fixture=None):
    registre, ids, positions = _monde()
    return registre, ids, positions, _reussi(_proposer(registre, positions))


def test_appliquer_fait_sortir_de_a_planifier_puis_assigne_chaque_equipe(futurs_ok):
    registre, ids, positions, proposition = _proposition_prete()
    avant = {iid: preparation.evaluer(registre, iid, positions, _lecteur(_profil()))[0] for iid in ids.values()}
    application = _reussi(_appliquer(registre, proposition["plan_id"], positions))

    routes = {v["chantier"]: r["equipe"] for r in proposition["plan"] for v in r["visites"]}
    assert application["deja_appliquee"] is False and application["appliquee_par"] == "admin.fictif"
    assert sorted(a["intervention_id"] for a in application["assignations"]) == sorted(ids.values())
    for ligne in application["assignations"]:
        assert ligne["transition"] == "a_planifier->planifiee" and ligne["effet"] == "assignee"
        assert ligne["technicien_id"] == routes[ligne["intervention_id"]]
    for iid in ids.values():
        assert etats.statut_courant(registre, iid) == "planifiee"
        assert etats.technicien_assigne(registre, iid) == routes[iid]
    transitions = [m for m in _maillons(registre, "transition_statut") if m["statut"] == "planifiee"]
    assert len(transitions) == 3 and {m["statut_precedent"] for m in transitions} == {"a_planifier"}
    for maillon in transitions:  # la porte d'empreinte de T4.10 : l'empreinte du verdict « prêt » y est consignée
        assert maillon["empreinte_preparation"] == avant[maillon["intervention_id"]]["empreinte"]
        assert "volets" not in maillon
    assert registre.valider_chaine()


def test_appliquer_deux_fois_n_ecrit_rien_de_plus(futurs_ok):
    registre, _, positions, proposition = _proposition_prete()
    premiere = _reussi(_appliquer(registre, proposition["plan_id"], positions))
    taille = registre.taille()
    seconde = _reussi(_appliquer(registre, proposition["plan_id"], positions))
    assert seconde["deja_appliquee"] is True and registre.taille() == taille
    assert seconde["assignations"] == premiere["assignations"]


def test_un_plan_applique_ne_peut_etre_reapplique_apres_un_autre_qui_a_deja_pris_les_interventions(futurs_ok):
    registre, ids, positions = _monde()
    premier = _reussi(_proposer(registre, positions))
    autre = _reussi(_proposer(registre, positions, {"parametres": {**PARAMETRES, "iterations": 301}}))
    _reussi(_appliquer(registre, premier["plan_id"], positions))
    taille = registre.taille()
    verdict = _refuse(_appliquer(registre, autre["plan_id"], positions), "REJ-CEDULE-ENTREE-CHANGEE")
    assert "a_planifier" in verdict["detail"] and "planifiee" in verdict["detail"]
    assert registre.taille() == taille


def test_une_preparation_devenue_non_prete_refuse_l_application_sans_rien_ecrire(futurs_ok):
    registre, ids, positions, proposition = _proposition_prete()
    taille = registre.taille()
    sans_ch10 = Positions({lead: SITES[lead] for lead in ("ch-01", "ch-02")})  # l'adresse de ch-10 est retirée
    verdict = _refuse(_appliquer(registre, proposition["plan_id"], sans_ch10), "REJ-CEDULE-PREPARATION-NON-PRETE",
                      ids["ch-10"])
    assert "adresse" in verdict["detail"]
    assert registre.taille() == taille
    assert {etats.statut_courant(registre, iid) for iid in ids.values()} == {"a_planifier"}


def test_un_profil_qui_a_change_depuis_la_proposition_refuse_l_application(futurs_ok):
    registre, ids, positions, proposition = _proposition_prete()
    taille = registre.taille()
    change = _profil()
    change["cedule"]["iterations"] = 301  # un réglage : la préparation ne bouge pas, mais le plan a lu l'ancien profil
    verdict = _refuse(_appliquer(registre, proposition["plan_id"], positions, profil=change),
                      "REJ-CEDULE-ENTREE-CHANGEE", "le profil des équipes a changé")
    assert "proposer de nouveau" in verdict["detail"]
    assert registre.taille() == taille


def test_un_profil_devenu_illisible_refuse_l_application(futurs_ok):
    registre, _, positions, proposition = _proposition_prete()
    taille = registre.taille()
    # la préparation ne peut plus être prête sans profil : refus par la préparation, jamais une application sans lui
    _refuse(_appliquer(registre, proposition["plan_id"], positions, profil=None, verdict_profil=VERDICT_INVALIDE),
            "REJ-CEDULE-PREPARATION-NON-PRETE", "equipe")
    assert registre.taille() == taille


def test_un_plan_sur_des_arguments_complets_ne_depend_pas_de_l_empreinte_du_profil_mais_de_l_admissibilite(futurs_ok):
    """Des arguments complets, donc aucune valeur lue du profil : un changement du profil ne périme pas le plan. Le
    profil reste juge de l'admissibilité de l'équipe qui reçoit une intervention qui sort de a_planifier."""
    registre, ids, positions = _monde()
    proposition = _reussi(_proposer(registre, positions, _arguments_equivalents(ids, _profil())))
    change = _profil()
    change["cedule"]["iterations"] = 301
    _reussi(_appliquer(registre, proposition["plan_id"], positions, profil=change))


def test_une_equipe_hors_profil_ne_recoit_pas_une_intervention_qui_sort_de_a_planifier(futurs_ok):
    registre, ids, positions = _monde()
    arguments = _arguments_equivalents(ids, _profil())
    arguments["equipes"] = [{
        "id": "eq-x", "competences": ["gouttieres", "revetement"], "depot": _depot("depot-joliette"),
        "quarts": [{"jour": 0, "debut_min": 480, "fin_min": 1020}],
    }]
    proposition = _reussi(_proposer(registre, positions, arguments))
    assert {r["equipe"] for r in proposition["plan"]} == {"eq-x"}
    taille = registre.taille()
    verdict = _refuse(_appliquer(registre, proposition["plan_id"], positions), "REJ-TOURNEES-PLAN-INVALIDE", "eq-x")
    assert "admissibles : eq-a, eq-b" in verdict["detail"]
    assert registre.taille() == taille
    assert {etats.statut_courant(registre, iid) for iid in ids.values()} == {"a_planifier"}


def test_une_equipe_du_profil_qui_a_perdu_sa_competence_n_est_plus_admissible(futurs_ok):
    """Plan proposé avec des équipes en surcharge, dont une équipe du profil dont la compétence a disparu du profil."""
    registre, ids, positions = _monde()
    arguments = _arguments_equivalents(ids, _profil())
    profil = _profil()
    for equipe in profil["liste"]:
        equipe["competences"] = ["revetement"]  # plus personne ne détient « gouttieres »
    proposition = _reussi(_proposer(registre, positions, arguments))
    taille = registre.taille()
    # la préparation, calculée sur le nouveau profil, n'est plus prête (aucune équipe admissible)
    verdict = _refuse(_appliquer(registre, proposition["plan_id"], positions, profil=profil),
                      "REJ-CEDULE-PREPARATION-NON-PRETE", "equipe")
    assert registre.taille() == taille and verdict["code"] == "REJ-CEDULE-PREPARATION-NON-PRETE"


def test_une_non_cedulee_reste_a_planifier_et_les_autres_sortent(futurs_ok):
    """`ch-01` (gouttières) dure 530 minutes : admissible (le quart en fait 540), mais aller et retour dépassent le
    quart. Le solveur la laisse de côté : elle ne change pas de statut, jamais un `planifiee` sans équipe."""
    registre, ids, positions = _monde(services={"ch-02": "revetement", "ch-10": "revetement"})
    profil = _profil()
    profil["services"]["gouttieres"]["duree_min"] = 530
    proposition = _reussi(_proposer(registre, positions, profil=profil))
    assert [ligne["chantier"] for ligne in proposition["non_cedulees"]] == [ids["ch-01"]]
    application = _reussi(_appliquer(registre, proposition["plan_id"], positions, profil=profil))
    assert sorted(a["intervention_id"] for a in application["assignations"]) == sorted(
        [ids["ch-02"], ids["ch-10"]])
    assert etats.statut_courant(registre, ids["ch-01"]) == "a_planifier"
    assert etats.technicien_assigne(registre, ids["ch-01"]) is None
    assert etats.statut_courant(registre, ids["ch-02"]) == etats.statut_courant(registre, ids["ch-10"]) == "planifiee"


def test_un_refus_n_ecrit_rien_meme_si_une_seule_intervention_est_en_cause(futurs_ok):
    registre, ids, positions, proposition = _proposition_prete()
    avant = json.dumps(registre.lire(), sort_keys=True)
    sans_ch02 = Positions({lead: SITES[lead] for lead in ("ch-01", "ch-10")})
    _refuse(_appliquer(registre, proposition["plan_id"], sans_ch02), "REJ-CEDULE-PREPARATION-NON-PRETE", ids["ch-02"])
    assert json.dumps(registre.lire(), sort_keys=True) == avant


def test_un_verdict_de_preparation_truque_ne_passe_pas_la_porte_meme_par_la_cedule(futurs_ok, monkeypatch):
    """La porte d'empreinte de T4.10 reste en place : `etats.transitionner` recalcule l'empreinte du verdict. Un
    volet qui mentirait après coup (verdict modifié entre le calcul et la transition) est refusé, la cédule lève."""
    registre, ids, positions, proposition = _proposition_prete()
    vraie = preparation.evaluer

    def truquee(*args, **kwargs):
        verdict, refus = vraie(*args, **kwargs)
        if verdict is not None:
            verdict["volets"]["meteo"]["detail"] = "modifié après le calcul de l'empreinte"
        return verdict, refus

    monkeypatch.setattr(preparation, "evaluer", truquee)
    with pytest.raises(RuntimeError, match="sortie de a_planifier refusée"):
        _appliquer(registre, proposition["plan_id"], positions)
