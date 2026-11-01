"""M1.9 : la logique pure des rendez-vous. Capacité de M4 -> fenêtres, conflits, confirmation depuis la cédule."""

from __future__ import annotations

import copy

import pytest
from m1_front_office import rendez_vous as rdv

NOW = "2026-11-02T09:00:00-05:00"  # lundi
S1, S2, S3 = "2026-11-09", "2026-11-16", "2026-11-23"


def _charge(semaine, equipes=(("eq-a", 2400, 600), ("eq-b", 2400, 2300)), calculable=True, manque=None):
    if not calculable:
        return {
            "contrat": "m4.capacite_equipe",
            "version": 1,
            "semaine_debut": semaine,
            "unite": "heures_declarees",
            "calculable": False,
            "manque": manque or ["cedule_non_appliquee"],
            "equipes": [],
        }
    return {
        "contrat": "m4.capacite_equipe",
        "version": 1,
        "semaine_debut": semaine,
        "unite": "heures_declarees",
        "calculable": True,
        "manque": [],
        "sources": {"profil_empreinte": "e" * 64, "registre_tete": "l1"},
        "equipes": [{"equipe_id": i, "minutes_disponibles": d, "minutes_planifiees": p} for i, d, p in equipes],
    }


def _propose(rid="rdv-1", motif="visite_evaluation", duree=60, signal="courriel:s"):
    return {
        "type_entree": rdv.TYPE_PROPOSE,
        "rdv_id": rid,
        "motif": motif,
        "duree_minutes": duree,
        "signal_id": signal,
        "options": [],
    }


def _retenu(rid, semaine, h=NOW, expire="2026-11-04T09:00:00-05:00"):
    return {"type_entree": rdv.TYPE_RETENU, "horodatage": h, "rdv_id": rid, "semaine": semaine, "expire_le": expire}


def test_les_semaines_doivent_etre_des_lundis_futurs_distincts_et_bornes():
    assert rdv.valider_semaines([S1, S2], NOW) == [S1, S2]
    for mauvais, motif in (
        ([], "SEMAINES"),
        (["2026-11-10"], "lundi"),
        (["2026-10-26"], "horizon"),
        (["2027-04-05"], "horizon"),
        ([S1, S1], "double"),
        (["pas-une-date"], "invalide"),
        ([S1, S2, S3, "2026-11-30", "2026-12-07"], "SEMAINES"),
        (None, "SEMAINES"),
    ):
        with pytest.raises(rdv.RefusRdv, match=motif):
            rdv.valider_semaines(mauvais, NOW)
    assert rdv.valider_semaines(["2026-11-02"], NOW) == ["2026-11-02"], "la semaine courante est admise"


def test_les_options_sont_des_minutes_entieres_nettes_du_planifie_de_m4_et_des_retenues_de_m1():
    (o,) = rdv.options({S1: _charge(S1)}, 60, [], NOW)
    assert (
        o["statut"] == "disponible" and o["minutes_libres"] == 1800 + 100 and o["equipes_possibles"] == ["eq-a", "eq-b"]
    )
    assert o["minutes_retenues_m1"] == 0 and o["minutes_nettes"] == 1900
    deja = [_propose("rdv-0", duree=1850), _retenu("rdv-0", S1)]
    (o2,) = rdv.options({S1: _charge(S1)}, 60, deja, NOW)
    assert o2["minutes_retenues_m1"] == 1850 and o2["statut"] == "complet"


def test_une_retenue_expiree_ou_annulee_ou_confirmee_ne_compte_plus():
    base = [_propose("rdv-0", duree=1850), _retenu("rdv-0", S1)]
    apres_expiration = "2026-11-05T09:00:00-05:00"
    assert rdv.minutes_retenues(base, S1, apres_expiration) == 0
    annulee = [*base, {"type_entree": rdv.TYPE_ANNULE, "rdv_id": "rdv-0", "motif": "client"}]
    assert rdv.minutes_retenues(annulee, S1, NOW) == 0
    confirmee = [
        *base,
        {
            "type_entree": rdv.TYPE_CONFIRME,
            "rdv_id": "rdv-0",
            "debut": "2026-11-10T09:00:00-05:00",
            "fin": "2026-11-10T11:00:00-05:00",
            "intervention_id": "i1",
        },
    ]
    assert rdv.minutes_retenues(confirmee, S1, NOW) == 0, "déjà dans la cédule de M4 : jamais compté deux fois"
    assert rdv.minutes_retenues(base, S1, NOW, sauf="rdv-0") == 0, "on ne se fait pas conflit à soi-même"


def test_une_semaine_non_calculable_dit_ce_qui_manque_jamais_zero():
    (o,) = rdv.options({S1: _charge(S1, calculable=False, manque=["profil_equipes_non_declare"])}, 60, [], NOW)
    assert o["statut"] == "non_calculable" and o["manque"] == ["profil_equipes_non_declare"]
    assert o["minutes_libres"] is None and o["equipes_possibles"] == []


def test_aucune_equipe_ne_peut_prendre_la_duree_meme_si_la_somme_suffit():
    charge = _charge(S1, equipes=(("eq-a", 600, 560), ("eq-b", 600, 560)))  # 40 + 40 min libres : aucune équipe n'a 60
    (o,) = rdv.options({S1: charge}, 60, [], NOW)
    assert o["minutes_libres"] == 80 and o["equipes_possibles"] == [] and o["statut"] == "complet"


@pytest.mark.parametrize(
    "modif,motif",
    [
        (lambda c: c.update(contrat="autre"), "CAPACITE"),
        (lambda c: c.update(version=2), "CAPACITE"),
        (lambda c: c.update(semaine_debut="2026-11-16"), "semaine demandée"),
        (lambda c: c.update(unite="jours_personnes"), "unité"),
        (lambda c: c["equipes"][0].update(minutes_disponibles=-1), "minutes_disponibles"),
        (lambda c: c["equipes"][0].update(minutes_planifiees="5"), "minutes_planifiees"),
        (lambda c: c["equipes"][0].update(equipe_id=""), "equipe_id"),
        (lambda c: c.update(equipes=[]), "sans équipe"),
        (lambda c: c.update(calculable="oui"), "sans équipe|manque"),
    ],
)
def test_une_capacite_qui_viole_le_contrat_est_refusee_avant_tout_calcul(modif, motif):
    c = copy.deepcopy(_charge(S1))
    modif(c)
    with pytest.raises(rdv.RefusRdv, match=motif):
        rdv.options({S1: c}, 60, [], NOW)


def test_non_calculable_sans_manque_nomme_est_refuse():
    c = _charge(S1, calculable=False)
    c["manque"] = []
    with pytest.raises(rdv.RefusRdv, match="nommer"):
        rdv.verifier_capacite(c, S1)


def _cedule(**modif):
    ligne = {
        "intervention_id": "i1",
        "lead_id": "L1",
        "plan_id": "p1",
        "equipe_id": "eq-a",
        "debut": "2026-11-10T09:00:00-05:00",
        "fin": "2026-11-10T11:00:00-05:00",
        "statut": "planifiee",
        "validite": "date_confirmee",
        "revision": 1,
        "source_ligne_id": "l9",
        **modif,
    }
    return {"debut_semaine": S1, "interventions": [ligne]}


def test_le_creneau_vient_de_la_cedule_de_m4_et_jamais_de_l_appelant():
    c = rdv.creneau_depuis_cedule(_cedule(), "i1", S1, 60)
    assert (c["debut"], c["fin"], c["equipe_id"], c["plan_id"]) == (
        "2026-11-10T09:00:00-05:00",
        "2026-11-10T11:00:00-05:00",
        "eq-a",
        "p1",
    )


@pytest.mark.parametrize(
    "cedule,intervention,code",
    [
        ({"debut_semaine": S1, "interventions": []}, "i1", "CEDULE-ABSENTE"),
        (_cedule(), "autre", "CEDULE-ABSENTE"),
        (_cedule(validite="a_reconfirmer"), "i1", "A-RECONFIRMER"),
        (_cedule(statut="reportee"), "i1", "A-RECONFIRMER"),
        (_cedule(statut="a_planifier"), "i1", "A-RECONFIRMER"),
        ({**_cedule(), "debut_semaine": "2026-11-16"}, "i1", "CEDULE:"),
        ({}, "i1", "CEDULE:"),
    ],
)
def test_sans_creneau_date_et_valide_rien_n_est_confirme(cedule, intervention, code):
    with pytest.raises(rdv.RefusRdv, match=code):
        rdv.creneau_depuis_cedule(cedule, intervention, S1, 60)


def test_un_creneau_plus_court_que_la_duree_demandee_est_refuse():
    with pytest.raises(rdv.RefusRdv, match="DUREE"):
        rdv.creneau_depuis_cedule(_cedule(), "i1", S1, 180)


def test_cycle_de_vie_et_expirations():
    lignes = [_propose()]
    assert rdv.etats(lignes, NOW)["rdv-1"]["etat"] == "proposee"
    lignes.append(_retenu("rdv-1", S1))
    assert rdv.etats(lignes, NOW)["rdv-1"]["etat"] == "retenue"
    assert rdv.etats(lignes, "2026-11-05T09:00:00-05:00")["rdv-1"]["etat"] == "expiree"
    lignes.append(
        {
            "type_entree": rdv.TYPE_CONFIRME,
            "rdv_id": "rdv-1",
            "debut": "2026-11-10T09:00:00-05:00",
            "fin": "2026-11-10T11:00:00-05:00",
            "intervention_id": "i1",
        }
    )
    assert rdv.etats(lignes, NOW)["rdv-1"]["etat"] == "confirmee"
    assert rdv.etats(lignes, "2026-11-11T09:00:00-05:00")["rdv-1"]["etat"] == "passee"


def test_on_ne_confirme_pas_ce_qui_n_a_pas_ete_retenu():
    lignes = [_propose(), {"type_entree": rdv.TYPE_CONFIRME, "rdv_id": "rdv-1", "debut": "x", "fin": "y"}]
    assert rdv.etats(lignes, NOW)["rdv-1"]["etat"] == "proposee"


def test_les_echeances_de_rappel_sont_calculees_par_le_code_et_seulement_a_venir():
    assert rdv.echeances_rappel("2026-11-10T09:00:00-05:00", NOW) == [
        "2026-11-08T09:00:00-05:00",
        "2026-11-09T09:00:00-05:00",
        "2026-11-10T07:00:00-05:00",
    ]
    assert rdv.echeances_rappel("2026-11-02T10:00:00-05:00", NOW) == [], "tout est déjà passé"
    assert rdv.echeances_rappel("2026-11-10T09:00:00-05:00", NOW, (120, 120)) == ["2026-11-10T07:00:00-05:00"]
    for mauvais in (0, 4, 10_000_000, "5", True):
        with pytest.raises(rdv.RefusRdv, match="DECALAGE"):
            rdv.echeances_rappel("2026-11-10T09:00:00-05:00", NOW, (mauvais,))


def test_textes_de_date_en_francais_et_identifiant_stable():
    assert rdv.texte_date("2026-11-10T09:00:00-05:00") == "mardi 10 novembre 2026"
    assert rdv.texte_heure("2026-11-10T09:05:00-05:00") == "9 h 05"
    assert rdv.identifiant_rdv("k") == rdv.identifiant_rdv("k") != rdv.identifiant_rdv("k2")


def test_un_instant_sans_fuseau_est_refuse():
    with pytest.raises(rdv.RefusRdv, match="HORODATAGE"):
        rdv.etats([_propose()], "2026-11-02T09:00:00")
