"""C3 : les alertes MÉTIER de M8, une règle déclarative à la fois, puis le cycle de vie d'un épisode.

Pur (aucune base) : le fichier de règles (`definitions/m8-alertes.v1.yaml`) et ses refus ; les seuils de la direction ;
l'évaluation (franchi, dans la cible, non évaluée et pourquoi) sur des mesures fictives lues avec leur fraîcheur et leur
qualité ; l'ouverture d'UNE alerte par épisode ; l'accusé, le report, la résolution ; les bornes ; la charge de
l'événement `m8.alerte_proposee` (extension additive) ; la liste « À voir ». Le scénario de bout en bout (vrai
planificateur, vrai bus, vrais outils) est dans `tests/test_m8_alertes_metier_planifiees.py`.
"""

from __future__ import annotations

import copy
import datetime as dt
import json
import re
from pathlib import Path

import pytest
import yaml
from m8_analytics import (
    alertes_metier,
    catalogue_mesures,
    fraicheur_mesures,
    jeux_fictifs,
    moteur_mesures,
    pastilles,
)

from opsys.evenements import schemas

FICTIF = True
CATALOGUE = catalogue_mesures.charger()
ENTREES = catalogue_mesures.par_identifiant(CATALOGUE)
REGLES = alertes_metier.charger(CATALOGUE)
MANIFESTE = Path(alertes_metier.__file__).resolve().parents[2] / "department.yaml"
FICHIER = Path(alertes_metier.__file__).resolve().parents[2] / "definitions" / "m8-alertes.v1.yaml"
T0 = dt.datetime(2026, 11, 12, 20, 0, tzinfo=dt.UTC)  # 16 h locale : après le dernier fait des données fictives
MAINTENANT = T0.isoformat()
SEUILS_FICTIFS = {
    "tresorerie_sous_seuil": "30000",  # le cash libre fictif (25 000 $) est SOUS ce seuil
    "creances_90_jours": "5000",
    "taux_acceptation": "30",
    "devis_sans_reponse": "10",
    "articles_en_rupture": "2",  # trois articles en rupture (jeu fictif) : franchi
    "pipeline_leads_ouverts": "5",
}


def _mesures(registres=None, maintenant=T0, **options):
    registres = registres or jeux_fictifs.registres_fictifs(jour="2026-11-12", avec_operations=True, **options)
    lues = fraicheur_mesures.lire_mesures_avec_fraicheur(moteur_mesures.lire(registres, CATALOGUE), CATALOGUE,
                                                         maintenant, {})
    return pastilles.ajouter(lues)


def _seuils(**surcharges):
    configuration = {"seuils": {**SEUILS_FICTIFS, **surcharges}}
    return alertes_metier.lire_seuils(configuration, REGLES)


def _verdicts(mesures=None, seuils=None):
    return alertes_metier.evaluer(REGLES, mesures if mesures is not None else _mesures(),
                                  seuils if seuils is not None else _seuils())


def _v(verdicts, regle, metric_id=None):
    trouves = [v for v in verdicts if v["regle"] == regle and (metric_id is None or v["metric_id"] == metric_id)]
    assert len(trouves) == 1, trouves
    return trouves[0]


# ====================================================================================================== les règles
def test_les_regles_du_depot_sont_declaratives_fermees_et_ne_nomment_que_le_catalogue():
    connues = set(ENTREES)
    assert {r["genre"] for r in REGLES["regles"]} == {"seuil", "peremption", "qualite"}
    for r in REGLES["regles"]:
        assert r["action"] in REGLES["actions"] and r["gravite"] in ("attention", "critique")
        for metric_id in [r.get("mesure"), *r.get("mesures", []), *r.get("mesures_liees", [])]:
            assert metric_id is None or metric_id in connues
    seuils = [r for r in REGLES["regles"] if r["genre"] == "seuil"]
    assert len(seuils) == 6 and len({r["reglage"] for r in seuils}) == 6
    assert alertes_metier.reglages_declares(REGLES) == [r["reglage"] for r in seuils]


def test_chaque_seuil_attendu_de_la_direction_est_un_reglage_declare_au_manifeste_dans_l_unite_de_sa_mesure():
    """Les seuils ne sont écrits nulle part : ils s'adoptent à la console. Chaque règle `seuil` doit avoir SON
    réglage."""
    manifeste = yaml.safe_load(MANIFESTE.read_text(encoding="utf-8"))
    par_chemin = {r["chemin"]: r for r in manifeste["reglages"]}
    for regle in (r for r in REGLES["regles"] if r["genre"] == "seuil"):
        reglage = par_chemin[f"configuration.alertes.seuils.{regle['reglage']}"]
        assert reglage["type"] == "decimal" and reglage["niveau"] == "N3" and "proposition" not in reglage
        assert reglage["unite"] and reglage["debloque"] and reglage["cle"].startswith("m8.")
        assert "min" in reglage and "max" in reglage
    assert not [c for c in par_chemin if c.startswith("configuration.alertes.seuils.")
                and c.rsplit(".", 1)[1] not in alertes_metier.reglages_declares(REGLES)]
    assert manifeste["configuration"]["alertes"] == {"seuils": {}}, "aucun seuil n'est inventé à la livraison"


def test_le_departement_propriétaire_d_une_alerte_est_celui_de_la_mesure_au_catalogue_jamais_un_autre():
    registres = jeux_fictifs.registres_fictifs(jour="2026-11-12", avec_operations=True)
    mesures = _mesures(registres)
    plan = alertes_metier.planifier(REGLES, _verdicts(mesures), mesures, [], MAINTENANT)
    assert plan["ouvertures"]
    for entree in plan["ouvertures"]:
        assert entree["departement"] == ENTREES[entree["metric_id"]]["proprietaire"]
    par_regle = {e["regle"]: e for e in plan["ouvertures"]}
    assert par_regle["ALERTE-TRESORERIE-SOUS-SEUIL"]["departement"] == "m05-financecore"
    assert par_regle["ALERTE-RUPTURE-MATERIEL"]["departement"] == "m06-material-control"


def _brut():
    return yaml.safe_load(FICHIER.read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    ("mutation", "attendu"),
    [
        (lambda b: b.update(schema="autre"), "schema attendu"),
        (lambda b: b.update(extra=1), "clés inconnues"),
        (lambda b: b.update(version=0), "version"),
        (lambda b: b.update(actions={}), "actions"),
        (lambda b: b["actions"].update(mauvais="Texte avec {cause} inconnue"), "champs de gabarit inconnus"),
        (lambda b: b["actions"].update(mauvais="Texte {"), "gabarit illisible"),
        (lambda b: b["regles"][0].update(action="inexistante"), "gabarit du fichier"),
        (lambda b: b["regles"][0].update(genre="inconnu"), "genre"),
        (lambda b: b["regles"][0].update(gravite="urgence"), "gravite"),
        (lambda b: b["regles"][0].update(sens="gauche"), "sens"),
        (lambda b: b["regles"][0].update(mesure="m8_inconnue"), "hors du catalogue fermé"),
        (lambda b: b["regles"][0].update(reglage="Seuil Bizarre"), "reglage"),
        (lambda b: b["regles"][0].update(id="REGLE-SANS-PREFIXE"), "ALERTE"),
        (lambda b: b["regles"][0].update(extra=1), "clés inconnues"),
        (lambda b: b["regles"][0].pop("sens"), "manquantes"),
        (lambda b: b["regles"][0].update(mesures_liees=["m8_cash_libre_cad"]), "ne reprend pas la mesure surveillée"),
        (lambda b: b["regles"][0].update(mesures_liees=["m8_x"]), "hors du catalogue fermé"),
        (lambda b: b["regles"].append(copy.deepcopy(b["regles"][0])), "défini deux fois"),
        (lambda b: b["regles"].append({**copy.deepcopy(b["regles"][0]), "id": "ALERTE-AUTRE-NOM"}), "en double"),
        (lambda b: b["regles"].append({**copy.deepcopy(b["regles"][0]), "id": "ALERTE-AUTRE-MESURE",
                                       "mesure": "m8_leads_recus"}), "sert déjà une autre règle"),
        (lambda b: b.update(regles=[]), "regles"),
        (lambda b: b["regles"][-1].update(mesures=["m8_leads_recus"]), "clés inconnues"),
    ],
)
def test_un_fichier_de_regles_abusif_est_refuse_en_entier(mutation, attendu):
    brut = _brut()
    mutation(brut)
    with pytest.raises(alertes_metier.AlertesRefusees) as refus:
        alertes_metier.valider(brut, CATALOGUE)
    assert refus.value.code == alertes_metier.REJ_ALERTES_INVALIDES and attendu in str(refus.value)


def test_un_fichier_illisible_est_refuse_nommement(tmp_path):
    (tmp_path / "a.yaml").write_text("regles: [", encoding="utf-8")
    with pytest.raises(alertes_metier.AlertesRefusees) as refus:
        alertes_metier.charger(CATALOGUE, tmp_path / "a.yaml")
    assert refus.value.code == alertes_metier.REJ_ALERTES_ILLISIBLES


# ================================================================================================ les seuils de la
# direction
def test_sans_seuil_declare_chaque_regle_de_seuil_est_non_evaluee_et_le_dit_aucune_alerte():
    mesures = _mesures()
    verdicts = alertes_metier.evaluer(REGLES, mesures, alertes_metier.lire_seuils({}, REGLES))
    for regle in (r for r in REGLES["regles"] if r["genre"] == "seuil"):
        v = _v(verdicts, regle["id"])
        assert (v["etat"], v["raison"]) == ("non_evaluee", "seuil_a_configurer"), regle["id"]
    plan = alertes_metier.planifier(REGLES, verdicts, mesures, [], MAINTENANT)
    assert [e["genre"] for e in plan["ouvertures"]] == [] and plan["resolutions"] == []
    lignes = alertes_metier.etat_des_regles(REGLES, verdicts, alertes_metier.lire_seuils({}, REGLES))
    assert {ligne["seuil"] for ligne in lignes if ligne["genre"] == "seuil"} == {"a_configurer"}


@pytest.mark.parametrize("invalide", [True, False, 1.5, "abc", "", [], {}, "1e999", None])
def test_un_seuil_illisible_est_refuse_et_dit_jamais_corrige(invalide):
    lus = _seuils(tresorerie_sous_seuil=invalide)
    assert "tresorerie_sous_seuil" in lus["invalides"] and "tresorerie_sous_seuil" not in lus["seuils"]
    v = _v(_verdicts(seuils=lus), "ALERTE-TRESORERIE-SOUS-SEUIL")
    assert (v["etat"], v["raison"]) == ("non_evaluee", "seuil_invalide")


def test_un_seuil_entier_ou_texte_decimal_est_lu_une_cle_inconnue_est_dite():
    lus = alertes_metier.lire_seuils({"seuils": {"tresorerie_sous_seuil": 30000, "taux_acceptation": "12.5",
                                                 "tresorie_faute_de_frappe": "5"}}, REGLES)
    assert lus["seuils"]["tresorerie_sous_seuil"] == 30000 and str(lus["seuils"]["taux_acceptation"]) == "12.5"
    assert lus["ignores"] == ["tresorie_faute_de_frappe"] and lus["invalides"] == []
    assert alertes_metier.lire_seuils({"seuils": "n'importe quoi"}, REGLES)["invalides"] == sorted(
        alertes_metier.reglages_declares(REGLES))


# ================================================================================================== l'évaluation
def test_une_mesure_franchie_dit_courant_reference_et_sens():
    verdicts = _verdicts()
    assert _v(verdicts, "ALERTE-TRESORERIE-SOUS-SEUIL")["etat"] == "franchi"  # 25 000 <= 30 000
    assert _v(verdicts, "ALERTE-RUPTURE-MATERIEL")["etat"] == "franchi"  # 3 >= 2
    assert _v(verdicts, "ALERTE-CREANCES-90-JOURS")["etat"] == "dans_la_cible"  # 0 < 5 000
    assert _v(verdicts, "ALERTE-CONVERSION-SOUS-SEUIL")["etat"] == "dans_la_cible"  # 50 > 30
    assert _v(verdicts, "ALERTE-DEVIS-SANS-REPONSE")["etat"] == "dans_la_cible"  # 2 < 10
    assert _v(verdicts, "ALERTE-PIPELINE-BAS")["etat"] == "dans_la_cible"  # 12 > 5


@pytest.mark.parametrize(
    ("regle", "seuil", "attendu"),
    [
        ("ALERTE-TRESORERIE-SOUS-SEUIL", "25000", "franchi"),  # la borne elle-même franchit (au_dessous : <=)
        ("ALERTE-TRESORERIE-SOUS-SEUIL", "24999.99", "dans_la_cible"),
        ("ALERTE-TRESORERIE-SOUS-SEUIL", "25000.01", "franchi"),
        ("ALERTE-RUPTURE-MATERIEL", "3", "franchi"),  # au_dessus : >=
        ("ALERTE-RUPTURE-MATERIEL", "4", "dans_la_cible"),
        ("ALERTE-RUPTURE-MATERIEL", "2.99", "franchi"),
    ],
)
def test_la_frontiere_franchit_et_le_sens_est_respecte(regle, seuil, attendu):
    reglage = next(r["reglage"] for r in REGLES["regles"] if r["id"] == regle)
    assert _v(_verdicts(seuils=_seuils(**{reglage: seuil})), regle)["etat"] == attendu


def test_franchit_est_une_comparaison_dans_le_bon_sens_des_deux_cotes():
    d = alertes_metier.nombres.decimal_lu
    assert alertes_metier.franchit(d("5"), "au_dessus", d("5")) and alertes_metier.franchit(d("6"), "au_dessus", d("5"))
    assert not alertes_metier.franchit(d("4.99"), "au_dessus", d("5"))
    assert alertes_metier.franchit(d("5"), "au_dessous", d("5"))
    assert alertes_metier.franchit(d("4"), "au_dessous", d("5"))
    assert not alertes_metier.franchit(d("5.01"), "au_dessous", d("5"))


def test_une_mesure_perimee_n_alerte_jamais_sur_sa_valeur_ni_ne_resout():
    vieilles = _mesures(maintenant=T0 + dt.timedelta(days=30))
    verdicts = _verdicts(vieilles)
    v = _v(verdicts, "ALERTE-TRESORERIE-SOUS-SEUIL")
    assert (v["etat"], v["raison"]) == ("non_evaluee", "mesure_perimee")
    assert _v(verdicts, "ALERTE-DONNEE-PERIMEE", "m8_cash_libre_cad")["etat"] == "franchi"  # elle, elle alerte


def test_une_mesure_non_calculable_ou_bloquee_par_la_qualite_n_alerte_pas_sur_une_valeur():
    non_calculable = _mesures(cash_libre_cad=None)
    v = _v(_verdicts(non_calculable), "ALERTE-TRESORERIE-SOUS-SEUIL")
    assert (v["etat"], v["raison"]) == ("non_evaluee", "mesure_non_calculable")
    registres = copy.deepcopy(jeux_fictifs.registres_fictifs(jour="2026-11-12", avec_operations=True))
    registres["cash_libre"][0]["en_deficit"] = True  # incohérent : la qualité bloque le cash libre
    bloquees = _mesures(registres)
    v = _v(_verdicts(bloquees), "ALERTE-TRESORERIE-SOUS-SEUIL")
    assert (v["etat"], v["raison"]) == ("non_evaluee", "qualite_en_echec")
    q = _v(_verdicts(bloquees), "ALERTE-QUALITE-ECHEC", "m8_cash_libre_cad")
    assert q["etat"] == "franchi"
    assert _v(_verdicts(bloquees), "ALERTE-QUALITE-ECHEC", "m8_leads_recus")["etat"] == "dans_la_cible"


def test_la_peremption_ne_vise_que_les_mesures_deja_calculees():
    verdicts = _verdicts(_mesures(cash_libre_cad=None))
    v = _v(verdicts, "ALERTE-DONNEE-PERIMEE", "m8_cash_libre_cad")
    assert (v["etat"], v["raison"]) == ("non_evaluee", "mesure_non_calculable")  # jamais calculée : pas « périmée »


# ===================================================================================== le cycle de vie d'un épisode
def _plan(registre, mesures=None, seuils=None, maintenant=MAINTENANT):
    mesures = mesures if mesures is not None else _mesures()
    verdicts = _verdicts(mesures, seuils)
    return alertes_metier.planifier(REGLES, verdicts, mesures, registre, maintenant)


def _ranger(registre, plan):
    registre.extend(plan["ouvertures"])
    registre.extend(plan["resolutions"])


def test_une_seule_alerte_par_episode_meme_evaluee_dix_fois():
    registre: list[dict] = []
    premier = _plan(registre)
    assert {e["regle"] for e in premier["ouvertures"]} == {"ALERTE-TRESORERIE-SOUS-SEUIL", "ALERTE-RUPTURE-MATERIEL"}
    _ranger(registre, premier)
    for rang in range(10):
        suite = _plan(registre, maintenant=(T0 + dt.timedelta(minutes=5 * (rang + 1))).isoformat())
        assert suite["ouvertures"] == [] and suite["resolutions"] == [], rang
    assert len([e for e in registre if e["type_entree"] == "alerte_ouverte"]) == 2


def test_l_accuse_ne_rouvre_rien_et_sort_l_alerte_de_a_voir_sans_fermer_l_episode():
    registre: list[dict] = []
    _ranger(registre, _plan(registre))
    cible = "ALERTE-TRESORERIE-SOUS-SEUIL:m8_cash_libre_cad:1"
    assert {a["id"] for a in alertes_metier.attentes(registre, MAINTENANT)} >= {cible}
    accusee = alertes_metier.accuser(registre, cible, MAINTENANT, "nathan")
    assert accusee["type_entree"] == "alerte_accusee" and accusee["par"] == "nathan"
    registre.append(accusee)
    assert cible not in {a["id"] for a in alertes_metier.attentes(registre, MAINTENANT)}
    assert alertes_metier.statut_effectif(alertes_metier.episodes(registre)[cible], MAINTENANT) == "accusee"
    assert _plan(registre)["ouvertures"] == []  # le même état ne rouvre pas
    assert alertes_metier.accuser(registre, cible, MAINTENANT, "nathan") is None  # un double accusé n'écrit rien


def test_le_report_cache_jusqu_a_l_instant_choisi_puis_l_alerte_redevient_visible_sans_rien_ecrire():
    registre: list[dict] = []
    _ranger(registre, _plan(registre))
    cible = "ALERTE-TRESORERIE-SOUS-SEUIL:m8_cash_libre_cad:1"
    jusqu_au = (T0 + dt.timedelta(hours=2)).isoformat()
    registre.append(alertes_metier.reporter(registre, cible, MAINTENANT, jusqu_au, "nathan"))
    episode = alertes_metier.episodes(registre)[cible]
    assert alertes_metier.statut_effectif(episode, (T0 + dt.timedelta(hours=1, minutes=59)).isoformat()) == "reportee"
    assert cible not in {a["id"] for a in alertes_metier.attentes(registre, (T0 + dt.timedelta(hours=1)).isoformat())}
    assert alertes_metier.statut_effectif(episode, jusqu_au) == "ouverte"  # la borne est échue
    echu = (T0 + dt.timedelta(hours=3)).isoformat()
    assert cible in {a["id"] for a in alertes_metier.attentes(registre, echu)}
    assert len(registre) == 3  # deux ouvertures et un report : l'échéance n'a rien écrit
    assert _plan(registre, maintenant=echu)["ouvertures"] == []  # toujours le même épisode


def test_un_report_leve_un_accuse_et_un_accuse_leve_un_report():
    registre: list[dict] = []
    _ranger(registre, _plan(registre))
    cible = "ALERTE-TRESORERIE-SOUS-SEUIL:m8_cash_libre_cad:1"
    registre.append(alertes_metier.accuser(registre, cible, MAINTENANT, "nathan"))
    registre.append(alertes_metier.reporter(registre, cible, MAINTENANT, (T0 + dt.timedelta(hours=1)).isoformat(), "n"))
    apres = (T0 + dt.timedelta(hours=2)).isoformat()
    assert alertes_metier.statut_effectif(alertes_metier.episodes(registre)[cible], apres) == "ouverte"
    registre.append(alertes_metier.reporter(registre, cible, apres, (T0 + dt.timedelta(hours=9)).isoformat(), "n"))
    registre.append(alertes_metier.accuser(registre, cible, apres, "nathan"))
    episode = alertes_metier.episodes(registre)[cible]
    assert alertes_metier.statut_effectif(episode, apres) == "accusee" and episode["reporte_jusqu_au"] is None


def test_le_retour_dans_la_cible_resout_l_episode_et_un_nouveau_franchissement_ouvre_l_episode_suivant():
    registre: list[dict] = []
    _ranger(registre, _plan(registre))
    une_heure_plus_tard = (T0 + dt.timedelta(hours=1)).isoformat()
    mieux = _plan(registre, seuils=_seuils(tresorerie_sous_seuil="20000"), maintenant=une_heure_plus_tard)
    assert [r["alerte_id"] for r in mieux["resolutions"]] == ["ALERTE-TRESORERIE-SOUS-SEUIL:m8_cash_libre_cad:1"]
    assert mieux["resolutions"][0]["motif"] == "retour_dans_la_cible" and mieux["ouvertures"] == []
    _ranger(registre, mieux)
    episode = alertes_metier.episodes(registre)["ALERTE-TRESORERIE-SOUS-SEUIL:m8_cash_libre_cad:1"]
    assert alertes_metier.statut_effectif(episode, MAINTENANT) == "resolue"
    rechute = _plan(registre, maintenant=(T0 + dt.timedelta(hours=2)).isoformat())
    (nouvelle,) = [e for e in rechute["ouvertures"] if e["regle"] == "ALERTE-TRESORERIE-SOUS-SEUIL"]
    assert nouvelle["alerte_id"].endswith(":2") and nouvelle["episode"] == 2


def test_une_regle_non_evaluee_ne_resout_rien_on_ne_ferme_pas_sur_une_valeur_qu_on_ne_peut_pas_juger():
    registre: list[dict] = []
    _ranger(registre, _plan(registre))
    for mesures, seuils in (
        (_mesures(maintenant=T0 + dt.timedelta(days=30)), None),  # périmée
        (_mesures(cash_libre_cad=None), None),  # non calculable
        (None, alertes_metier.lire_seuils({}, REGLES)),  # seuils retirés
    ):
        plan = _plan(registre, mesures=mesures, seuils=seuils, maintenant=(T0 + dt.timedelta(days=1)).isoformat())
        assert plan["resolutions"] == [] or all("DONNEE-PERIMEE" in r["alerte_id"] for r in plan["resolutions"])
        assert not [r for r in plan["resolutions"] if "TRESORERIE" in r["alerte_id"]]


def test_une_alerte_resolue_ne_s_accuse_ni_ne_se_reporte_et_les_gestes_hostiles_sont_refuses():
    registre: list[dict] = []
    _ranger(registre, _plan(registre))
    cible = "ALERTE-TRESORERIE-SOUS-SEUIL:m8_cash_libre_cad:1"
    _ranger(registre, _plan(registre, seuils=_seuils(tresorerie_sous_seuil="1"), maintenant=MAINTENANT))
    for geste in (lambda: alertes_metier.accuser(registre, cible, MAINTENANT, "n"),
                  lambda: alertes_metier.reporter(registre, cible, MAINTENANT, (T0 + dt.timedelta(days=1)).isoformat(),
                                                  "n")):
        with pytest.raises(alertes_metier.AlertesRefusees) as refus:
            geste()
        assert refus.value.code == alertes_metier.REJ_ALERTE_RESOLUE
    for faux in ("", "n'importe quoi", "ALERTE-X:m8_y:1", "ALERTE-TRESORERIE-SOUS-SEUIL:m8_cash_libre_cad:0",
                 "../../etc:m8_x:1", cible + "\n", None, 12):
        with pytest.raises(alertes_metier.AlertesRefusees) as refus:
            alertes_metier.accuser(registre, faux, MAINTENANT, "n")
        assert refus.value.code == alertes_metier.REJ_ALERTE_IDENTIFIANT, faux
    with pytest.raises(alertes_metier.AlertesRefusees) as refus:
        alertes_metier.accuser(registre, "ALERTE-TRESORERIE-SOUS-SEUIL:m8_cash_libre_cad:7", MAINTENANT, "n")
    assert refus.value.code == alertes_metier.REJ_ALERTE_INCONNUE


@pytest.mark.parametrize(
    "jusqu_au",
    [
        MAINTENANT,  # maintenant même : pas dans le futur
        (T0 - dt.timedelta(hours=1)).isoformat(),
        (T0 + dt.timedelta(days=31)).isoformat(),
        "demain",
        "2026-11-13T10:00:00",  # sans fuseau
        None,
        12345,
    ],
)
def test_un_report_passe_trop_lointain_ou_illisible_est_refuse(jusqu_au):
    registre: list[dict] = []
    _ranger(registre, _plan(registre))
    with pytest.raises(alertes_metier.AlertesRefusees) as refus:
        alertes_metier.reporter(registre, "ALERTE-TRESORERIE-SOUS-SEUIL:m8_cash_libre_cad:1", MAINTENANT, jusqu_au, "n")
    assert refus.value.code == alertes_metier.REJ_ALERTE_REPORT


def test_le_report_de_trente_jours_pile_est_accepte():
    registre: list[dict] = []
    _ranger(registre, _plan(registre))
    entree = alertes_metier.reporter(registre, "ALERTE-TRESORERIE-SOUS-SEUIL:m8_cash_libre_cad:1", MAINTENANT,
                                     (T0 + dt.timedelta(days=30)).isoformat(), "n")
    assert entree["type_entree"] == "alerte_reportee"


def test_l_inondation_est_bornee_par_vingt_quatre_heures_le_surplus_est_compte_et_reviendra():
    registres = jeux_fictifs.registres_fictifs(jour="2026-11-12", avec_operations=True)
    registres["cash_libre"][0]["en_deficit"] = True  # qualité : quatre mesures bloquées + les mesures liées
    mesures = _mesures(registres)
    verdicts = _verdicts(mesures)
    franchies = sum(1 for v in verdicts if v["etat"] == "franchi")
    assert franchies >= 5
    borne = alertes_metier.OUVERTURES_PAR_JOUR_MAX
    registre = [{"type_entree": "alerte_ouverte", "alerte_id": f"ALERTE-X-Y:m8_a_{i}:1", "regle": "ALERTE-X-Y",
                 "metric_id": f"m8_a_{i}", "episode": 1, "ouverte_le": (T0 - dt.timedelta(hours=1)).isoformat(),
                 "gravite": "attention", "accusee_le": None} for i in range(borne - 2)]
    plan = alertes_metier.planifier(REGLES, verdicts, mesures, registre, MAINTENANT)
    assert len(plan["ouvertures"]) == 2 and plan["bornees"] == franchies - 2
    # vingt-cinq heures plus tard, les anciennes ouvertures ne comptent plus : le surplus passe
    plus_tard = alertes_metier.planifier(REGLES, verdicts, mesures, registre, (T0 + dt.timedelta(hours=25)).isoformat())
    assert len(plus_tard["ouvertures"]) == franchies and plus_tard["bornees"] == 0


def test_le_resultat_est_deterministe_et_l_evenement_id_ne_depend_que_de_l_episode():
    a = _plan([])
    b = _plan([])
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)
    for entree in a["ouvertures"]:
        assert entree["evenement_id"] == f"m8-alerte-{entree['metric_id']}-{entree['type_alerte']}-{MAINTENANT}"


# ==================================================================== l'alerte : contenu, événement, « À voir »
def _ouvertures():
    return {e["regle"]: e for e in _plan([])["ouvertures"]}


def test_une_alerte_porte_courant_reference_action_departement_et_mesures_liees_jamais_une_cause():
    entree = _ouvertures()["ALERTE-TRESORERIE-SOUS-SEUIL"]
    assert entree["courant"] == "25000.00" and entree["seuil"] == "30000.00" and entree["sens"] == "au_dessous"
    assert "25 000,00" in entree["pourquoi"] and "30 000,00" in entree["pourquoi"]
    assert entree["action_id"] == "examiner_tresorerie" and "m05-financecore" in entree["action"]
    assert "CPA" in entree["action"] and "M8 n'exécute aucune action" in entree["action"]
    assert entree["departement"] == "m05-financecore" and entree["gravite"] == "critique"
    assert set(entree["mesures_liees"]) == {"m8_solde_tresorerie_cad", "m8_comptes_a_payer_cad",
                                            "m8_taxes_a_remettre_cad", "m8_creances_ouvertes_cad"}
    vue = alertes_metier.vue_episode(alertes_metier.episodes([entree])[entree["alerte_id"]], MAINTENANT)

    def cles(objet):
        if isinstance(objet, dict):
            for cle, valeur in objet.items():
                yield cle
                yield from cles(valeur)
        elif isinstance(objet, list):
            for element in objet:
                yield from cles(element)

    interdites = {"cause", "causes", "responsable", "raison_signalee"}
    assert not (set(cles(vue)) | set(cles(entree))) & interdites
    assert vue["departement_proprietaire"] == "m05-financecore" and vue["statut"] == "ouverte"
    assert vue["courant"] == {"valeur": "25000.00", "unite": "CAD"}


def test_la_charge_de_l_evenement_respecte_le_schema_etendu_et_le_catalogue():
    for entree in _plan([])["ouvertures"]:
        charge = alertes_metier.charge_evenement(entree)
        assert schemas.erreurs_charge("m8.alerte_proposee", charge) == [], (entree["regle"],
                                                                           schemas.erreurs_charge("m8.alerte_proposee",
                                                                                                 charge))
        assert charge["a_qui"] == entree["departement"] and charge["action_proposee"] == entree["action"]
        assert charge["horodatage_reference"] == MAINTENANT and charge["type_alerte"].startswith("METIER-")
    et_une_charge_forgee_ne_passe_pas = alertes_metier.charge_evenement(_plan([])["ouvertures"][0])
    et_une_charge_forgee_ne_passe_pas["type_alerte"] = "METIER-INVENTE"
    assert schemas.erreurs_charge("m8.alerte_proposee", et_une_charge_forgee_ne_passe_pas)
    forgee = alertes_metier.charge_evenement(_plan([])["ouvertures"][0])
    forgee["preuve"]["cause"] = "mauvais fournisseur"
    assert schemas.erreurs_charge("m8.alerte_proposee", forgee)


def test_a_voir_ne_liste_que_les_alertes_ouvertes_avec_un_niveau_par_gravite_et_aucun_montant():
    registre: list[dict] = []
    _ranger(registre, _plan(registre))
    items = alertes_metier.attentes(registre, MAINTENANT)
    par_id = {i["id"]: i for i in items}
    assert par_id["ALERTE-TRESORERIE-SOUS-SEUIL:m8_cash_libre_cad:1"]["niveau"] == "N3"
    assert par_id["ALERTE-RUPTURE-MATERIEL:m8_articles_en_rupture:1"]["niveau"] == "N2"
    for item in items:
        assert set(item) == {"type", "id", "resume", "niveau", "depuis", "action_proposee"}
        assert item["type"] == "alerte_metier" and item["depuis"] == MAINTENANT and "$" not in item["resume"]
        sans_code = re.sub(r"m[0-9]{2}-[a-z-]+", "", item["resume"])  # le code du département est le seul nombre permis
        assert not re.search(r"\d", sans_code), "le résumé ne porte aucun montant ni aucun compte"
    rupture = "ALERTE-RUPTURE-MATERIEL:m8_articles_en_rupture:1"
    registre.append(alertes_metier.accuser(registre, rupture, MAINTENANT, "n"))
    assert rupture not in {i["id"] for i in alertes_metier.attentes(registre, MAINTENANT)}


def test_un_episode_inconnu_au_registre_est_ignore_jamais_invente():
    registre = [{"type_entree": "alerte_accusee", "alerte_id": "ALERTE-FANTOME:m8_x:1", "accusee_le": MAINTENANT,
                 "par": "n"}]
    assert alertes_metier.episodes(registre) == {} and alertes_metier.attentes(registre, MAINTENANT) == []


def test_l_etat_des_regles_dit_le_seuil_declare_invalide_ou_a_configurer():
    seuils = _seuils(tresorerie_sous_seuil="x")
    seuils["seuils"].pop("devis_sans_reponse")
    etat = alertes_metier.etat_des_regles(REGLES, _verdicts(seuils=seuils), seuils)
    lignes = {ligne["regle"]: ligne for ligne in etat}
    assert lignes["ALERTE-TRESORERIE-SOUS-SEUIL"]["seuil"] == "invalide"
    assert lignes["ALERTE-DEVIS-SANS-REPONSE"]["seuil"] == "a_configurer"
    assert lignes["ALERTE-RUPTURE-MATERIEL"]["seuil"] == "declare"
    assert lignes["ALERTE-RUPTURE-MATERIEL"]["franchies"] == 1
    assert lignes["ALERTE-RUPTURE-MATERIEL"]["reglage"] == "configuration.alertes.seuils.articles_en_rupture"
    assert "seuil" not in lignes["ALERTE-QUALITE-ECHEC"]
