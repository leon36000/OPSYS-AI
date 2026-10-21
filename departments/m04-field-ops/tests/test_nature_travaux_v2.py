"""PLAN T0.13-b : la nature des travaux d'une intervention suit la version du LeadQualifie dont elle vient.

Un lead v1 (gelé) porte `type_travaux` ; un lead v2 porte `service` (taxonomie du socle) et `schema_version`.
La version est lue dans le lead à l'inscription, jamais devinée, et l'une des deux clés n'est JAMAIS déduite de
l'autre : l'inscription, la liste des interventions, la cédule simple, le WCT et la cédule par tournées
portent la clé de leur version. Registre EN MÉMOIRE, tout est fictif (`fictif: true`).
"""

from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest
from m4_field_ops import cedule, cedule_tournees, encodage, etats, outbox, pointage
from m4_field_ops.registre import Registre

from opsys import taxonomie

FICTIF = True
SEL = "sel-fictif-v2"
VILLE = "Repentigny"
H1 = "2030-01-01T08:00:00+00:00"
H_ARRIVEE = "2030-01-01T09:00:00+00:00"
H_DEPART = "2030-01-01T11:30:00+00:00"
H_COMPLETION = "2030-01-01T11:35:00+00:00"
HORODATAGE = "2030-01-01T00:00:00+00:00"
FENETRE_TRAVAIL = {"debut": "2030-01-01T07:00:00+00:00", "fin": "2030-01-01T19:00:00+00:00"}
GPS = {"latitude": 45.5088, "longitude": -73.5878}
REFERENTIEL = {cedule.tokeniser_ville(SEL, VILLE): {"latitude": 45.5017, "longitude": -73.5673, "rayon_km": 25.0}}
ATTESTATION = {"fictif": True, "appareil_id": "APP-V2"}
FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "tournees_repentigny_joliette.json").read_text("utf-8"))
SITES = {site["id"]: site for site in FIXTURE["sites"]}
PARAMETRES = {"facteur_detour_milliemes": 1300, "vitesse_moyenne_kmh": 50, "marge_par_trajet_secondes": 600,
              "iterations": 300, "cout_non_cedule_m": 500000}
FENETRE = {"jours": [0], "debut_min": 480, "fin_min": 1020}


@pytest.fixture(autouse=True)
def _instance_avec_services(declarer_services):
    """L'instance de test déclare les services du catalogue de référence."""
    declarer_services()


def _contrat_v1(lead_id, type_travaux="extension", urgence=False):
    return {"lead_id": lead_id, "conversation_id": f"C-{lead_id}", "type_travaux": type_travaux,
            "ville": VILLE, "canal": "telephone", "contact": {"nom": "Client Fictif"},
            "urgence_declaree": urgence}


def _contrat_v2(lead_id, service="gouttieres", urgence=False):
    return {"schema_version": 2, "lead_id": lead_id, "conversation_id": f"C-{lead_id}", "service": service,
            "ville": VILLE, "canal": "formulaire", "contact": {"nom": "Client Fictif"},
            "urgence_declaree": urgence}


def _marqueur(lead_id):
    return {"readiness_ok": True, "lead_id": lead_id, "hash_tete_registre": None,
            "horodatage": HORODATAGE, "empreinte": "cd" * 32}


def _inscrire(registre, contrat, instant=0):
    accuse, verdict = etats.inscrire_intervention(
        contrat, _marqueur(contrat["lead_id"]), registre, f"2030-01-01T00:00:{instant:02d}+00:00", SEL)
    assert verdict is None, verdict
    return accuse["intervention_id"]


def _inscription(registre, intervention_id):
    return next(m for m in registre.lire()
                if m["type_entree"] == etats.TYPE_INSCRIPTION and m["intervention_id"] == intervention_id)


# =========================================================================================
# 1. L'inscription et la liste des interventions
# =========================================================================================
def test_une_inscription_v2_porte_service_et_sa_version_jamais_type_travaux():
    registre = Registre()
    iid = _inscrire(registre, _contrat_v2("L-V2"))
    inscription = _inscription(registre, iid)
    assert inscription["service"] == "gouttieres" and inscription["schema_version"] == 2
    assert "type_travaux" not in inscription
    assert etats.travaux_de(inscription) == ("service", "gouttieres")


def test_une_inscription_v1_reste_octet_pour_octet_celle_d_avant():
    """Le maillon v1 n'apprend ni `service` ni `schema_version` : les registres déjà écrits restent valides."""
    registre = Registre()
    iid = _inscrire(registre, _contrat_v1("L-V1", "ravalement"))
    inscription = _inscription(registre, iid)
    assert set(inscription) - {"ligne_id", "precedent_ligne_id", "hash"} >= {"type_travaux"}
    assert "service" not in inscription and "schema_version" not in inscription
    assert etats.travaux_de(inscription) == ("type_travaux", "ravalement")


def test_un_lead_v2_dont_le_service_n_est_pas_declare_n_est_pas_inscrit(declarer_services):
    declarer_services("revetement")
    registre = Registre()
    accuse, verdict = etats.inscrire_intervention(
        _contrat_v2("L-V2"), _marqueur("L-V2"), registre, H1, SEL)
    assert accuse is None and verdict["code"] == "REJ-ENUM-INVALIDE"
    assert "REJ-SERVICE-INCONNU" in verdict["detail"] and "revetement" in verdict["detail"]
    assert registre.taille() == 0


def test_sans_profil_un_lead_v2_n_est_pas_inscrit_et_le_verdict_dit_quoi_configurer():
    taxonomie.fichier_profil().unlink()
    registre = Registre()
    accuse, verdict = etats.inscrire_intervention(_contrat_v2("L-V2"), _marqueur("L-V2"), registre, H1, SEL)
    assert accuse is None and "REJ-SERVICE-NON-CONFIGURE" in verdict["detail"]
    accuse_v1, verdict_v1 = etats.inscrire_intervention(_contrat_v1("L-V1"), _marqueur("L-V1"), registre, H1, SEL)
    assert verdict_v1 is None and accuse_v1 is not None  # le v1 ne dépend pas du profil


@pytest.mark.parametrize("inscription", [
    {"type_travaux": "extension", "service": "gouttieres"},  # les deux
    {"lead_id": "L"},  # aucune
])
def test_travaux_de_refuse_une_inscription_qui_ne_porte_pas_exactement_une_des_deux_cles(inscription):
    with pytest.raises(ValueError, match="exactement l'une"):
        etats.travaux_de(inscription)


def test_la_liste_des_interventions_rend_la_cle_de_chaque_version():
    registre = Registre()
    id_v1 = _inscrire(registre, _contrat_v1("L-V1", "ravalement"), 0)
    id_v2 = _inscrire(registre, _contrat_v2("L-V2", "revetement"), 1)
    par_id = {i["intervention_id"]: i for i in etats.lister_interventions(registre)}
    assert par_id[id_v1]["type_travaux"] == "ravalement" and "service" not in par_id[id_v1]
    assert par_id[id_v2]["service"] == "revetement" and "type_travaux" not in par_id[id_v2]
    # Le reste de la forme est celui d'avant, pour les deux versions.
    communes = {"intervention_id", "statut", "lead_id", "devis_id", "technicien_assigne", "fenetre_planifiee"}
    for entree in par_id.values():
        assert communes <= set(entree)


# =========================================================================================
# 2. La cédule simple (`cedule.generer_cedule`)
# =========================================================================================
FENETRES = [{"debut": f"2030-01-0{jour}T08:00:00+00:00", "fin": f"2030-01-0{jour}T17:00:00+00:00"}
            for jour in (1, 2, 3)]


def _inter_v1(numero, type_travaux="extension", ville="Laval"):
    return {"intervention_id": f"i-{numero}", "lead_id": f"L{numero}", "type_travaux": type_travaux, "ville": ville}


def _inter_v2(numero, service="gouttieres", ville="Laval"):
    return {"intervention_id": f"i-{numero}", "lead_id": f"L{numero}", "service": service, "ville": ville}


def test_la_cedule_rend_service_pour_une_intervention_v2_et_type_travaux_pour_une_v1():
    resultat, verdict = cedule.generer_cedule(
        [_inter_v1(1), _inter_v2(2, "revetement")], ["T1", "T2"], FENETRES, SEL)
    assert verdict is None
    par_id = {a["intervention_id"]: a for a in resultat["assignations"]}
    assert par_id["i-1"]["type_travaux"] == "extension" and "service" not in par_id["i-1"]
    assert par_id["i-2"]["service"] == "revetement" and "type_travaux" not in par_id["i-2"]
    assert resultat["non_cedulees"] == []


def test_une_intervention_v2_non_cedulee_garde_sa_cle():
    resultat, verdict = cedule.generer_cedule([_inter_v2(1), _inter_v2(2)], ["T1"], FENETRES[:1], SEL)
    assert verdict is None
    assert [a["service"] for a in resultat["assignations"]] == ["gouttieres"]
    assert [n["service"] for n in resultat["non_cedulees"]] == ["gouttieres"]
    assert all("type_travaux" not in n for n in resultat["non_cedulees"])


def test_la_cedule_d_un_lot_mixte_ne_depend_pas_de_l_ordre_des_interventions():
    lot = [_inter_v1(1, "extension"), _inter_v2(2, "gouttieres"), _inter_v1(3, "ravalement"),
           _inter_v2(4, "revetement", ville="Québec")]
    attendu, verdict = cedule.generer_cedule(lot, ["T1", "T2"], FENETRES, SEL)
    assert verdict is None
    for permutation in itertools.permutations(lot):
        obtenu, verdict = cedule.generer_cedule(list(permutation), ["T1", "T2"], FENETRES, SEL)
        assert verdict is None and obtenu == attendu


def test_deux_interventions_au_meme_code_mais_de_versions_differentes_ont_un_ordre_stable(declarer_services):
    """Un service propre peut porter le code d'un type v1 (`extension`) : la version départage, l'ordre ne
    dépend pas de celui de l'entrée, et aucune des deux n'est prise pour l'autre."""
    declarer_services("gouttieres", {"code": "extension", "libelle": "Extension (service propre)"})
    lot = [_inter_v2(1, "extension"), _inter_v1(1, "extension")]
    lot[1]["intervention_id"] = "i-1-v1"
    attendu, verdict = cedule.generer_cedule(lot, ["T1", "T2"], FENETRES, SEL)
    assert verdict is None
    inverse, _ = cedule.generer_cedule(list(reversed(lot)), ["T1", "T2"], FENETRES, SEL)
    assert inverse == attendu


def test_les_deux_cles_ou_aucune_est_une_forme_refusee():
    both = {**_inter_v1(1), "service": "gouttieres"}
    neither = {"intervention_id": "i-1", "lead_id": "L1", "ville": "Laval"}
    for forme in (both, neither):
        resultat, verdict = cedule.generer_cedule([forme], ["T1"], FENETRES, SEL)
        assert resultat is None and verdict["code"] == "REJ-CONTRAT-INVALIDE"


def test_un_service_non_declare_est_refuse_avec_la_marche_a_suivre(declarer_services):
    declarer_services("revetement")
    resultat, verdict = cedule.generer_cedule([_inter_v2(1, "gouttieres")], ["T1"], FENETRES, SEL)
    assert resultat is None and verdict["code"] == "REJ-ENUM-INVALIDE"
    assert "REJ-SERVICE-INCONNU" in verdict["detail"] and "entreprise.yaml" in verdict["detail"]


def test_sans_profil_la_cedule_v2_dit_quoi_configurer_et_la_v1_n_en_depend_pas():
    taxonomie.fichier_profil().unlink()
    resultat, verdict = cedule.generer_cedule([_inter_v2(1)], ["T1"], FENETRES, SEL)
    assert resultat is None and "REJ-SERVICE-NON-CONFIGURE" in verdict["detail"]
    resultat_v1, verdict_v1 = cedule.generer_cedule([_inter_v1(1)], ["T1"], FENETRES, SEL)
    assert verdict_v1 is None and len(resultat_v1["assignations"]) == 1


@pytest.mark.parametrize("valeur, code", [("", "REJ-CHAMP-VIDE"), (3, "REJ-CONTRAT-INVALIDE"),
                                            ("extension", "REJ-ENUM-INVALIDE")])
def test_un_service_vide_mal_type_ou_qui_est_un_type_v1_est_refuse(valeur, code):
    resultat, verdict = cedule.generer_cedule([_inter_v2(1, valeur)], ["T1"], FENETRES, SEL)
    assert resultat is None and verdict["code"] == code


def test_un_type_v1_inconnu_reste_refuse_comme_avant():
    resultat, verdict = cedule.generer_cedule([_inter_v1(1, "gouttieres")], ["T1"], FENETRES, SEL)
    assert resultat is None and verdict["code"] == "REJ-ENUM-INVALIDE"  # `gouttieres` n'est pas un type v1


# =========================================================================================
# 3. Le WCT (`outbox.completer_intervention`) : type_travaux (v1) OU service (v2)
# =========================================================================================
def _sur_site(contrat):
    """Registre en mémoire : intervention inscrite, en route, arrivée et départ pointés."""
    registre = Registre()
    iid = _inscrire(registre, contrat)
    assignation = {"intervention_id": iid, "technicien_id": "T1"}
    _, verdict = etats.transitionner(iid, "en_route", registre, H_ARRIVEE, assignation=assignation)
    assert verdict is None, verdict
    for action, horodatage in (("arrivee", H_ARRIVEE), ("depart", H_DEPART)):
        accuse, verdict = pointage.enregistrer_pointage(
            iid, "T1", action, horodatage, GPS, ATTESTATION, assignation, FENETRE_TRAVAIL, REFERENTIEL,
            VILLE, SEL, registre)
        assert verdict is None, verdict
    return registre, iid


def test_le_wct_d_un_lead_v2_porte_service_et_jamais_type_travaux():
    registre, iid = _sur_site(_contrat_v2("L-WCT2", "soffite_fascia"))
    accuse, verdict = outbox.completer_intervention(
        iid, H_COMPLETION, registre, ecart_detecte=False, verification_en_attente=True)
    assert verdict is None, verdict
    wct = registre.lire()[-1][outbox.CLE_WCT]
    assert wct["service"] == "soffite_fascia" and "type_travaux" not in wct
    assert set(wct) == set(outbox.CHAMPS_WCT) | {"service"}
    assert outbox.verifier_invariants_outbox(registre) == (True, "")


def test_le_wct_d_un_lead_v1_porte_type_travaux_et_jamais_service():
    registre, iid = _sur_site(_contrat_v1("L-WCT1", "ravalement"))
    accuse, verdict = outbox.completer_intervention(
        iid, H_COMPLETION, registre, ecart_detecte=False, verification_en_attente=True)
    assert verdict is None, verdict
    wct = registre.lire()[-1][outbox.CLE_WCT]
    assert wct["type_travaux"] == "ravalement" and "service" not in wct
    assert set(wct) == set(outbox.CHAMPS_WCT) | {"type_travaux"}


def test_le_contrat_du_wct_declare_service_comme_champ_optionnel():
    assert "service" in outbox.CHAMPS_WCT_OPTIONNELS and "type_travaux" in outbox.CHAMPS_WCT_OPTIONNELS
    assert "service" not in outbox.CHAMPS_WCT  # additif : les treize clés requises ne bougent pas


def test_un_wct_qui_porte_les_deux_cles_est_refuse_par_les_invariants():
    registre, iid = _sur_site(_contrat_v1("L-WCT-DEUX", "ravalement"))
    outbox.completer_intervention(iid, H_COMPLETION, registre, ecart_detecte=False)
    registre._chain[-1][outbox.CLE_WCT]["service"] = "gouttieres"
    ok, message = outbox.verifier_invariants_outbox(registre)
    assert ok is False and "type_travaux ET service" in message


def test_une_cle_etrangere_reste_refusee_par_les_invariants():
    registre, iid = _sur_site(_contrat_v2("L-WCT-ETRANGER"))
    outbox.completer_intervention(iid, H_COMPLETION, registre, ecart_detecte=False)
    registre._chain[-1][outbox.CLE_WCT]["categorie"] = "x"
    ok, message = outbox.verifier_invariants_outbox(registre)
    assert ok is False and "clés incorrectes" in message


# =========================================================================================
# 4. La cédule par tournées (`cedule_tournees`) : durées et compétences par type (v1) et par service (v2)
# =========================================================================================
class Positions:
    """`lire_position(registre, lead_id)` fictif : les positions « confirmées » sont un dictionnaire."""

    def __init__(self, sites):
        self.sites = dict(sites)

    def __call__(self, registre, lead_id):
        site = self.sites[lead_id]
        return {"latitude_microdegres": site["latitude_microdeg"], "longitude_microdegres": site["longitude_microdeg"],
                "version": 1, "ligne_id": "x"}, None


def _equipes():
    def equipe(identifiant, depot_id):
        depot = SITES[depot_id]
        return {"id": identifiant, "competences": ["gouttieres", "revetement"],
                "depot": {"id": depot_id, "latitude_microdegres": depot["latitude_microdeg"],
                          "longitude_microdegres": depot["longitude_microdeg"]},
                "quarts": [{"jour": 0, "debut_min": 480, "fin_min": 1020}]}
    return [equipe("eq-a", "depot-repentigny"), equipe("eq-b", "depot-joliette")]


def _monde(contrats):
    """Registre avec une intervention par contrat (lead_id = id du site), et ses positions."""
    registre = Registre()
    ids = {contrat["lead_id"]: _inscrire(registre, contrat, rang) for rang, contrat in enumerate(contrats)}
    return registre, ids, Positions({lead: SITES[lead] for lead in ids})


def _arguments(ids, **remplacements):
    arguments = {
        "equipes": _equipes(),
        "chantiers": [{"intervention_id": iid, "fenetre": dict(FENETRE), "creneau_fige": None}
                      for _lead, iid in sorted(ids.items())],
        "parametres": dict(PARAMETRES),
    }
    arguments.update(remplacements)
    return arguments


def _tables_v1(**remplacements):
    return {"durees_par_type_travaux": {"extension": 150, "ravalement": 120},
            "competences_par_type_travaux": {"extension": [], "ravalement": ["revetement"]}, **remplacements}


def _tables_v2(**remplacements):
    return {"durees_par_service": {"gouttieres": 90, "revetement": 180},
            "competences_par_service": {"gouttieres": [], "revetement": ["revetement"]}, **remplacements}


def _proposer(registre, positions, arguments, **extra):
    return cedule_tournees.proposer(registre, arguments, positions, HORODATAGE, moteur="dp", **extra)


def _reussi(couple):
    resultat, verdict = couple
    assert verdict is None, verdict
    return resultat


def _refuse(couple, code, *morceaux):
    resultat, verdict = couple
    assert resultat is None and verdict is not None, resultat
    assert verdict["code"] == code, verdict
    for morceau in morceaux:
        assert morceau in verdict["detail"], verdict
    return verdict


def _chantiers_du_plan(registre):
    maillon = next(m for m in registre.lire() if m["type_entree"] == cedule_tournees.TYPE_PROPOSEE)
    return {c["id"]: c for c in maillon["entree"]["chantiers"]}, maillon


def test_un_lot_v2_se_propose_avec_les_tables_par_service_et_sans_celles_par_type():
    registre, ids, positions = _monde([_contrat_v2("ch-01"), _contrat_v2("ch-02", "revetement")])
    proposition = _reussi(_proposer(registre, positions, _arguments(ids, **_tables_v2())))
    assert proposition["totaux"]["chantiers_cedules"] == 2 and proposition["non_cedulees"] == []
    chantiers, maillon = _chantiers_du_plan(registre)
    assert (chantiers[ids["ch-01"]]["duree_min"], chantiers[ids["ch-01"]]["competences_requises"]) == (90, [])
    assert (chantiers[ids["ch-02"]]["duree_min"], chantiers[ids["ch-02"]]["competences_requises"]) == (
        180, ["revetement"])
    # L'état gardé pour la garde d'application porte `service`, jamais `type_travaux`.
    assert all("service" in etat and "type_travaux" not in etat for etat in maillon["etat"])
    assert {etat["service"] for etat in maillon["etat"]} == {"gouttieres", "revetement"}


def test_un_lot_v2_s_applique_et_assigne_les_techniciens():
    registre, ids, positions = _monde([_contrat_v2("ch-01"), _contrat_v2("ch-02", "revetement")])
    proposition = _reussi(_proposer(registre, positions, _arguments(ids, **_tables_v2())))
    application = _reussi(cedule_tournees.appliquer(
        registre, proposition["plan_id"], positions, HORODATAGE, "admin.fictif"))
    assert application["deja_appliquee"] is False
    assert {a["intervention_id"] for a in application["assignations"]} == set(ids.values())
    assert all(etats.technicien_assigne(registre, iid) is not None for iid in ids.values())


def test_un_lot_v2_sans_les_tables_par_service_dit_quoi_fournir_sans_exiger_celles_par_type():
    registre, ids, positions = _monde([_contrat_v2("ch-01")])
    verdict = _refuse(_proposer(registre, positions, _arguments(ids)), "REJ-CHAMP-MANQUANT",
                      "durees_par_service manquant", "competences_par_service manquant")
    assert "durees_par_type_travaux" not in verdict["detail"]
    assert "competences_par_type_travaux" not in verdict["detail"]
    assert registre.taille() == 1  # rien n'a été rangé (l'inscription seule)


def test_un_lot_v1_n_exige_pas_les_tables_par_service_et_dit_toujours_celles_par_type():
    registre, ids, positions = _monde([_contrat_v1("ch-01")])
    _reussi(_proposer(registre, positions, _arguments(ids, **_tables_v1())))
    verdict = _refuse(_proposer(registre, positions, _arguments(ids)), "REJ-CHAMP-MANQUANT",
                      "durees_par_type_travaux manquant", "competences_par_type_travaux manquant")
    assert "par_service" not in verdict["detail"]


def test_un_service_absent_de_la_table_est_rapporte_par_son_nom():
    registre, ids, positions = _monde([_contrat_v2("ch-01"), _contrat_v2("ch-02", "revetement")])
    tables = _tables_v2(durees_par_service={"gouttieres": 90})
    _refuse(_proposer(registre, positions, _arguments(ids, **tables)), "REJ-CHAMP-MANQUANT",
            "durees_par_service.revetement manquant")


def test_une_cle_qui_n_est_pas_un_service_declare_est_rapportee():
    registre, ids, positions = _monde([_contrat_v2("ch-01")])
    tables = _tables_v2(durees_par_service={"gouttieres": 90, "pergola": 60})
    _refuse(_proposer(registre, positions, _arguments(ids, **tables)), "REJ-CONTRAT-INVALIDE",
            "durees_par_service : services inconnus : pergola", "déclarés : gouttieres")


def test_un_type_v1_donne_pour_un_lot_v2_est_rapporte_au_lieu_d_etre_pris_pour_un_service():
    """Un agent qui range `gouttieres` sous `durees_par_type_travaux` n'est pas compris de travers."""
    registre, ids, positions = _monde([_contrat_v2("ch-01")])
    tables = _tables_v2(durees_par_type_travaux={"gouttieres": 90})
    _refuse(_proposer(registre, positions, _arguments(ids, **tables)), "REJ-CONTRAT-INVALIDE",
            "durees_par_type_travaux : types de travaux inconnus : gouttieres")


def test_sans_profil_les_tables_par_service_dit_quoi_configurer(declarer_services):
    registre, ids, positions = _monde([_contrat_v2("ch-01")])
    taxonomie.fichier_profil().unlink()
    _refuse(_proposer(registre, positions, _arguments(ids, **_tables_v2())), "REJ-CONTRAT-INVALIDE",
            "REJ-SERVICE-NON-CONFIGURE")


def test_un_lot_mixte_exige_les_deux_jeux_de_tables_et_chaque_intervention_lit_les_siennes(declarer_services):
    """`extension` est à la fois un type v1 et un service propre déclaré : chaque intervention lit la table de
    SA version, aucune n'est prise pour l'autre."""
    declarer_services("gouttieres", {"code": "extension", "libelle": "Extension (service propre)"})
    registre, ids, positions = _monde([_contrat_v1("ch-01", "extension"), _contrat_v2("ch-02", "extension")])
    arguments = _arguments(ids, **_tables_v1(), durees_par_service={"extension": 60},
                           competences_par_service={"extension": ["gouttieres"]})
    _reussi(_proposer(registre, positions, arguments))
    chantiers, maillon = _chantiers_du_plan(registre)
    assert (chantiers[ids["ch-01"]]["duree_min"], chantiers[ids["ch-01"]]["competences_requises"]) == (150, [])
    assert (chantiers[ids["ch-02"]]["duree_min"], chantiers[ids["ch-02"]]["competences_requises"]) == (
        60, ["gouttieres"])
    etat_par_id = {e["intervention_id"]: e for e in maillon["etat"]}
    assert etat_par_id[ids["ch-01"]]["type_travaux"] == "extension" and "service" not in etat_par_id[ids["ch-01"]]
    assert etat_par_id[ids["ch-02"]]["service"] == "extension" and "type_travaux" not in etat_par_id[ids["ch-02"]]

    seulement_v1 = _arguments(ids, **_tables_v1())
    _refuse(_proposer(registre, positions, seulement_v1), "REJ-CHAMP-MANQUANT",
            "durees_par_service manquant", "competences_par_service manquant")


def test_l_identifiant_d_un_plan_v1_ne_change_pas_apres_t013b():
    """`etat` d'une intervention v1 garde exactement ses clés : les plans déjà proposés restent appliquables."""
    registre, ids, positions = _monde([_contrat_v1("ch-01")])
    _reussi(_proposer(registre, positions, _arguments(ids, **_tables_v1())))
    _, maillon = _chantiers_du_plan(registre)
    assert set(maillon["etat"][0]) == {
        "intervention_id", "lead_id", "type_travaux", "urgence_declaree", "statut", "technicien_assigne",
        "localisation"}
    assert maillon["empreinte_etat"] == encodage.empreinte(maillon["etat"])


def test_appliquer_refuse_un_plan_v2_dont_le_service_a_change_de_nature():
    """La garde d'application compare `service` : un état qui n'est plus celui de la proposition est refusé."""
    registre, ids, positions = _monde([_contrat_v2("ch-01")])
    proposition = _reussi(_proposer(registre, positions, _arguments(ids, **_tables_v2())))
    etats.assigner_technicien(ids["ch-01"], "eq-b", registre, HORODATAGE)  # l'état bouge
    _refuse(cedule_tournees.appliquer(registre, proposition["plan_id"], positions, HORODATAGE, "admin.fictif"),
            "REJ-CEDULE-ENTREE-CHANGEE", "technicien_assigne")
