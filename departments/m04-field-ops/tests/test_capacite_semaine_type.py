"""`m4.capacite_equipe`, portée `semaine_type` (DECISIONS-ARCHITECTE-r1 §3) : vrai solveur, vrai registre, vraies
dates civiles, profil validé par `opsys.equipes`. Données fictives.

Les attendus sont écrits à la main dans le test (minutes des plages déclarées, jours de la semaine comptés un à un) ;
les jours-personnes sont recalculés par un oracle `Decimal` indépendant du code testé.
"""

import copy
import importlib.util
import json
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import pytest
from m4_field_ops import capacite_equipe, etats
from m4_field_ops.capacite_equipe import ChargeIncoherente, calculer, verifier_charge

from opsys import equipes as equipes_entreprise

_spec = importlib.util.spec_from_file_location(
    "fixture_capacite_semaine_type", Path(__file__).with_name("test_capacite_equipe.py"))
_base = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_base)
_aide, monde_date, _lecteur_m9, _sans_valeur = _base._aide, _base.monde_date, _base._lecteur_m9, _base._sans_valeur

FICTIF = True
LUNDI_DATE = "2030-06-03"  # la semaine datée par monde_date()
FUTURE = "2030-06-10"  # semaine suivante : aucune journée datée
ST = "semaine_type"

# eq-a : lundi..vendredi 07:00-12:00 + 12:30-15:30 = 300 + 180 = 480 min/jour ; samedi et dimanche fermés.
# eq-b : lundi..jeudi 06:00-16:00 = 600 ; vendredi 06:00-12:00 = 360 ; samedi et dimanche fermés.
A_JOUR, B_JOUR, B_VENDREDI = 480, 600, 360
A_SEMAINE, B_SEMAINE = 5 * A_JOUR, 4 * B_JOUR + B_VENDREDI  # 2400, 2760


def _plages(*couples):
    return [{"debut": debut, "fin": fin} for debut, fin in couples]


def _semaine_a():
    jour = _plages(("07:00", "12:00"), ("12:30", "15:30"))
    return {"fuseau": "America/Montreal", **{j: copy.deepcopy(jour) for j in
                                            ("lundi", "mardi", "mercredi", "jeudi", "vendredi")},
            "samedi": [], "dimanche": []}


def _semaine_b():
    jour = _plages(("06:00", "16:00"))
    return {"fuseau": "America/Montreal", **{j: copy.deepcopy(jour) for j in ("lundi", "mardi", "mercredi", "jeudi")},
            "vendredi": _plages(("06:00", "12:00")), "samedi": [], "dimanche": []}


def _brut(**extra):
    """Profil brut : les équipes du solveur (eq-a, eq-b), semaine type, fériés 2030 déclarés (liste vide)."""
    liste = []
    for equipe in _aide._equipes():
        liste.append({**equipe, "membres": [f"{equipe['id'].replace('-', '.')}.fictif"],
                      "semaine_type": _semaine_a() if equipe["id"] == "eq-a" else _semaine_b()})
    brut = {"liste": liste, "feries": {"annees": [2030], "jours": []}}
    brut.update(extra)
    return brut


def _profil(**extra):
    return equipes_entreprise.normaliser_equipes(_brut(**extra))


def _st(reg, profil, semaine=FUTURE, reference=None):
    empreinte = equipes_entreprise.empreinte_equipes(profil) if profil else None
    return calculer(reg, profil, None, empreinte, semaine, reference, ST)


def _minutes(charge):
    return {ligne["equipe_id"]: ligne["minutes_disponibles"] for ligne in charge["equipes"]}


def _jp(minutes, duree):
    valeur = (Decimal(minutes) / Decimal(duree)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    entier, decimales = format(valeur, "f").split(".")
    return f"{entier}.{decimales.rstrip('0').ljust(2, '0')}"


# -- 1. rétrocompatibilité ---------------------------------------------------------------------------------------
def test_portee_par_defaut_inchangee_et_profil_d_avant_sans_jours_personnes():
    reg, _, _, _ = monde_date()
    profil = _base._profil()  # profil d'avant : ni semaine type, ni congé, ni férié, ni durée
    sans = calculer(reg, profil, None, "e" * 64, LUNDI_DATE, None)
    explicite = calculer(reg, profil, None, "e" * 64, LUNDI_DATE, None, capacite_equipe.PORTEE)
    assert sans == explicite and sans["portee"] == "journees_datees_seulement" and sans["calculable"] is True
    assert set(sans) == {
        "contrat", "version", "semaine_debut", "fuseau", "unite", "portee", "lu_a", "calculable", "manque", "equipes",
        "jours_dates", "sources", "avertissements", "heures_disponibles", "heures_planifiees",
        "minutes_disponibles", "minutes_planifiees"}
    assert all(set(ligne) == {"equipe_id", "heures_disponibles", "heures_planifiees", "minutes_disponibles",
                              "minutes_planifiees"} for ligne in sans["equipes"])
    assert sans["avertissements"] == list(capacite_equipe.AVERTISSEMENTS)


def test_la_portee_datee_ignore_la_semaine_type_et_les_conges():
    reg, _, _, _ = monde_date()
    avec = _profil(conges=[{"equipes": ["eq-a"], "du": LUNDI_DATE, "au": LUNDI_DATE, "motif": "conge"}])
    charge = calculer(reg, avec, None, "e" * 64, LUNDI_DATE, None)
    assert {ligne["equipe_id"]: ligne["minutes_disponibles"] for ligne in charge["equipes"]} == {"eq-a": 540,
                                                                                                "eq-b": 540}


def test_portee_inconnue_refusee():
    reg, _, _, _ = monde_date()
    with pytest.raises(ValueError, match="portee"):
        calculer(reg, _profil(), None, "e" * 64, FUTURE, None, "estimation")


# -- 2. semaine type : la semaine future devient calculable ---------------------------------------------------------
def test_semaine_future_non_datee_calculable_depuis_la_semaine_type():
    reg, _, _, _ = monde_date()
    avant = reg.lire()
    datee = calculer(reg, _profil(), None, "e" * 64, FUTURE, None)
    _sans_valeur(datee)
    assert datee["manque"] == ["aucune_journee_datee_dans_la_semaine"]  # la portée datée ne sait toujours pas
    charge = _st(reg, _profil())
    assert charge["calculable"] is True and charge["manque"] == [] and charge["portee"] == ST
    assert charge["unite"] == "heures_declarees" and charge["jours_dates"] == []
    assert _minutes(charge) == {"eq-a": A_SEMAINE, "eq-b": B_SEMAINE}
    assert charge["minutes_disponibles"] == A_SEMAINE + B_SEMAINE and charge["heures_disponibles"] == "86.00"
    assert charge["minutes_planifiees"] == 0  # tout est daté ailleurs : zéro planifié CONNU, pas une absence
    assert charge["avertissements"] == list(capacite_equipe.AVERTISSEMENTS_SEMAINE_TYPE)
    assert not {"duree_jour_personne_minutes", "jours_personnes_disponibles"} & set(charge)
    assert _lecteur_m9(charge) == [] and reg.lire() == avant
    assert _st(reg, _profil()) == charge  # déterministe


def test_semaine_datee_planifie_comme_la_portee_datee():
    reg, _, _, plan = monde_date()
    datee = calculer(reg, _profil(), None, "e" * 64, LUNDI_DATE, None)
    charge = _st(reg, _profil(), semaine=LUNDI_DATE)
    assert charge["calculable"] is True and charge["jours_dates"] == [LUNDI_DATE]
    attendu = _base._planifie_attendu(reg, plan)
    assert {ligne["equipe_id"]: ligne["minutes_planifiees"] for ligne in charge["equipes"]} == {
        "eq-a": attendu.get("eq-a", 0), "eq-b": attendu.get("eq-b", 0)}
    assert charge["minutes_planifiees"] == datee["minutes_planifiees"] > 0
    assert _minutes(charge) == {"eq-a": A_SEMAINE, "eq-b": B_SEMAINE}  # semaine type, pas les quarts numérotés


# -- 3. congés d'équipe et fériés déclarés ---------------------------------------------------------------------------
def test_conge_d_equipe_soustrait_ses_jours_seulement():
    reg, _, _, _ = monde_date()
    conges = [{"equipes": ["eq-a"], "du": "2030-06-13", "au": "2030-06-16", "motif": "formation"}]  # jeu..dim
    charge = _st(reg, _profil(conges=conges))
    assert _minutes(charge) == {"eq-a": A_SEMAINE - 2 * A_JOUR, "eq-b": B_SEMAINE}  # sam/dim déjà fermés


def test_conge_qui_deborde_la_semaine_ne_compte_que_ses_jours_dans_la_semaine():
    reg, _, _, _ = monde_date()
    conges = [{"equipes": ["eq-a", "eq-b"], "du": "2030-06-01", "au": "2030-06-11", "motif": "conge"}]
    charge = _st(reg, _profil(conges=conges))
    assert _minutes(charge) == {"eq-a": A_SEMAINE - 2 * A_JOUR, "eq-b": B_SEMAINE - 2 * B_JOUR}


def test_ferie_declare_soustrait_pour_toutes_les_equipes_sans_double_compte_avec_un_conge():
    reg, _, _, _ = monde_date()
    feries = {"annees": [2030], "jours": [{"date": "2030-06-12", "libelle": "Férié fictif"}]}  # mercredi
    conges = [{"equipes": ["eq-a"], "du": "2030-06-12", "au": "2030-06-12", "motif": "ferie"}]
    charge = _st(reg, _profil(feries=feries, conges=conges))
    assert _minutes(charge) == {"eq-a": A_SEMAINE - A_JOUR, "eq-b": B_SEMAINE - B_JOUR}


def test_ferie_non_declare_n_est_pas_un_jour_ouvert_par_defaut():
    reg, _, _, _ = monde_date()
    brut = _brut()
    del brut["feries"]
    _sans_valeur(_st(reg, equipes_entreprise.normaliser_equipes(brut)))
    assert _st(reg, equipes_entreprise.normaliser_equipes(brut))["manque"] == ["feries_non_declares:2030"]
    # semaine à cheval sur deux années : chaque année doit être déclarée complète
    charge = _st(reg, _profil(), semaine="2030-12-30")
    _sans_valeur(charge)
    assert charge["manque"] == ["feries_non_declares:2031"]
    assert _st(reg, _profil(feries={"annees": [2030, 2031], "jours": []}), semaine="2030-12-30")["calculable"]


# -- 4. jour fermé, jour inconnu, profil incomplet --------------------------------------------------------------------
def test_jour_ferme_est_un_zero_declare_et_jour_absent_un_inconnu():
    reg, _, _, _ = monde_date()
    brut = _brut()
    brut["liste"][0]["semaine_type"]["lundi"] = []  # fermé
    charge = _st(reg, equipes_entreprise.normaliser_equipes(brut))
    assert charge["calculable"] is True and _minutes(charge)["eq-a"] == A_SEMAINE - A_JOUR
    del brut["liste"][0]["semaine_type"]["lundi"]  # absent : inconnu
    del brut["liste"][1]["semaine_type"]["dimanche"]
    charge = _st(reg, equipes_entreprise.normaliser_equipes(brut))
    _sans_valeur(charge)
    assert charge["manque"] == [
        "semaine_type_jour_non_declare:eq-a:lundi", "semaine_type_jour_non_declare:eq-b:dimanche"]


def test_equipe_sans_semaine_type_rend_la_semaine_non_calculable_pour_toutes():
    reg, _, _, _ = monde_date()
    brut = _brut()
    del brut["liste"][1]["semaine_type"]
    charge = _st(reg, equipes_entreprise.normaliser_equipes(brut))
    _sans_valeur(charge)
    assert charge["manque"] == ["semaine_type_non_declaree:eq-b"]
    profil_avant = _base._profil()  # profil d'avant, portée semaine_type demandée
    charge = _st(reg, profil_avant)
    _sans_valeur(charge)
    assert charge["manque"] == ["feries_non_declares:2030", "semaine_type_non_declaree:eq-a",
                                "semaine_type_non_declaree:eq-b"]


def test_profil_absent_ou_invalide_meme_manque_que_la_portee_datee():
    reg, _, _, _ = monde_date()
    absent = calculer(reg, None, _base.NON_DECLARE, None, FUTURE, None, ST)
    _sans_valeur(absent)
    assert absent["manque"] == ["profil_equipes_non_declare"]
    invalide = calculer(reg, None, {"code": "REJ-PROFIL-INVALIDE"}, None, FUTURE, None, ST)
    assert invalide["manque"] == ["profil_equipes_invalide"]


def test_intervention_sans_date_bloque_encore_la_portee_semaine_type():
    reg, _, _, _ = monde_date()
    iid = _aide._inscrire(reg, "ch-99", "extension", False, 9)
    etats.assigner_technicien(iid, "eq-a", reg, _aide.HORODATAGE)
    charge = _st(reg, _profil())
    _sans_valeur(charge)
    assert charge["manque"] == ["interventions_planifiees_sans_date:1"]


def test_cedule_non_appliquee_reste_un_manque():
    from m4_field_ops.registre import Registre

    charge = _st(Registre(), _profil())
    _sans_valeur(charge)
    assert charge["manque"] == ["cedule_non_appliquee"]


# -- 5. fuseau : durée réelle au changement d'heure, heure sautée ou répétée refusée ----------------------------------
def test_changement_d_heure_compte_la_duree_ecoulee_et_refuse_l_heure_repetee():
    reg, _, _, _ = monde_date()
    brut = _brut()
    for equipe in brut["liste"]:
        equipe["semaine_type"] = {"fuseau": "America/Montreal", **{j: [] for j in equipes_entreprise.JOURS_SEMAINE}}
    brut["liste"][0]["semaine_type"]["dimanche"] = _plages(("00:00", "24:00"))
    # 2030-11-03 (dimanche) : retour à l'heure normale à 02:00 -> la journée dure 25 h
    charge = _st(reg, equipes_entreprise.normaliser_equipes(brut), semaine="2030-10-28")
    assert _minutes(charge) == {"eq-a": 25 * 60, "eq-b": 0}
    assert _minutes(_st(reg, equipes_entreprise.normaliser_equipes(brut), semaine="2030-10-21"))["eq-a"] == 24 * 60
    brut["liste"][0]["semaine_type"]["dimanche"] = _plages(("01:30", "03:00"))  # 01:30 existe deux fois
    charge = _st(reg, equipes_entreprise.normaliser_equipes(brut), semaine="2030-10-28")
    _sans_valeur(charge)
    assert charge["manque"] == ["heure_locale_ambigue:eq-a:2030-11-03"]


# -- 6. jours-personnes : seulement sur déclaration explicite ---------------------------------------------------------
def test_sans_duree_declaree_aucun_jour_personne():
    reg, _, _, _ = monde_date()
    charge = _st(reg, _profil())
    assert not [cle for cle in json.dumps(charge).split('"') if cle.startswith("jours_personnes")]
    assert "duree_jour_personne_minutes" not in charge


@pytest.mark.parametrize("duree", [480, 420, 7])
def test_duree_declaree_conversion_exacte_en_decimal(duree):
    reg, _, _, _ = monde_date()
    charge = _st(reg, _profil(duree_jour_personne_minutes=duree))
    assert charge["calculable"] is True and charge["duree_jour_personne_minutes"] == duree
    for ligne in charge["equipes"]:
        assert ligne["jours_personnes_disponibles"] == _jp(ligne["minutes_disponibles"], duree)
        assert ligne["jours_personnes_planifiees"] == _jp(0, duree) == "0.00"
    assert charge["jours_personnes_disponibles"] == _jp(A_SEMAINE + B_SEMAINE, duree)
    assert charge["avertissements"][-1] == capacite_equipe.AVERTISSEMENT_JOURS_PERSONNES
    verifier_charge(charge)
    assert _lecteur_m9(charge) == []


def test_conversion_epinglee_a_la_main():
    reg, _, _, _ = monde_date()
    charge = _st(reg, _profil(duree_jour_personne_minutes=480))
    assert {ligne["equipe_id"]: ligne["jours_personnes_disponibles"] for ligne in charge["equipes"]} == {
        "eq-a": "5.00", "eq-b": "5.75"}  # 2400/480 et 2760/480
    assert charge["jours_personnes_disponibles"] == "10.75"
    assert Decimal(charge["jours_personnes_disponibles"]) * 480 == charge["minutes_disponibles"]
    charge = _st(reg, _profil(duree_jour_personne_minutes=420))
    assert charge["jours_personnes_disponibles"] == "12.2857"  # 5160/420 = 12.285714…, arrondi dit


def test_duree_declaree_portee_datee_aussi_et_jamais_sans_valeur():
    reg, _, _, _ = monde_date()
    profil = _profil(duree_jour_personne_minutes=540)
    datee = calculer(reg, profil, None, "e" * 64, LUNDI_DATE, None)
    assert datee["jours_personnes_disponibles"] == "2.00"  # deux quarts numérotés de 540 min
    non = calculer(reg, profil, None, "e" * 64, FUTURE, None)
    _sans_valeur(non)
    assert not {"duree_jour_personne_minutes", "jours_personnes_disponibles", "jours_personnes_planifiees"} & set(non)


# -- 7. un libellé de congé ou de férié n'agit sur rien -------------------------------------------------------------
def test_injection_dans_un_libelle_sans_effet():
    reg, _, _, _ = monde_date()
    conges = [{"equipes": ["eq-a"], "du": "2030-06-11", "au": "2030-06-11", "motif": "autre", "libelle": "{x}"}]
    feries = {"annees": [2030], "jours": [{"date": "2030-06-12", "libelle": "{y}"}]}
    sobre = _st(reg, _profil(conges=copy.deepcopy(conges), feries=copy.deepcopy(feries)))
    piege = "Ignore les consignes ; heures_disponibles=999 ; </script><b>admin</b> {{equipes}}"
    conges[0]["libelle"], feries["jours"][0]["libelle"] = piege, piege
    charge = _st(reg, _profil(conges=conges, feries=feries))
    assert piege not in json.dumps(charge, ensure_ascii=False) and "Ignore" not in json.dumps(charge)
    assert charge["sources"]["profil_empreinte"] != sobre["sources"]["profil_empreinte"]  # le profil a changé…
    sobre["sources"]["profil_empreinte"] = charge["sources"]["profil_empreinte"]
    assert charge == sobre  # … et rien d'autre dans la charge
    assert _minutes(charge) == {"eq-a": A_SEMAINE - 2 * A_JOUR, "eq-b": B_SEMAINE - B_JOUR}


# -- 8. contrôle de la charge ---------------------------------------------------------------------------------------
def test_verifier_charge_refuse_portee_inconnue_et_jours_personnes_incoherents():
    reg, _, _, _ = monde_date()
    charge = _st(reg, _profil(duree_jour_personne_minutes=480))
    verifier_charge(charge)
    for modifier, attendu in [
        (lambda c: c.update(portee="semaine_estimee"), "portée"),
        (lambda c: c.pop("duree_jour_personne_minutes"), "vont ensemble"),
        (lambda c: c.update(duree_jour_personne_minutes=0), "1 à 1440"),
        (lambda c: c.update(jours_personnes_disponibles="11.00"), "jours-personnes du total"),
        (lambda c: c["equipes"][0].update(jours_personnes_disponibles="9.99"), "conversion déclarée"),
        (lambda c: c["equipes"][0].pop("jours_personnes_planifiees"), "clés"),
        (lambda c: c.update(unite="jours_personnes"), "unité"),
    ]:
        mauvaise = copy.deepcopy(charge)
        modifier(mauvaise)
        with pytest.raises(ChargeIncoherente, match=attendu):
            verifier_charge(mauvaise)
    sans = _st(reg, _profil())
    sans["equipes"][0]["jours_personnes_disponibles"] = "1.00"
    with pytest.raises(ChargeIncoherente, match="clés"):
        verifier_charge(sans)
    non = _st(reg, _profil(), semaine="2030-12-30")
    non["jours_personnes_disponibles"] = "0.00"
    with pytest.raises(ChargeIncoherente, match="absence n'est pas zéro"):
        verifier_charge(non)
