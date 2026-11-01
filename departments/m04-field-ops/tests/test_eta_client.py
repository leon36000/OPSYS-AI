"""Fenêtre d'arrivée estimée pour le client (M4.14) : un intervalle, jamais une heure unique ni une promesse. Module
pur.

Chiffres calculés À LA MAIN (secondes entières). Données fictives (`fictif: true`).
"""

from __future__ import annotations

import ast
import copy
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m4_field_ops import eta_client as eta  # noqa: E402
from m4_field_ops import verdicts  # noqa: E402

FICTIF = True
EST = timezone(timedelta(hours=-5))
EDT = timezone(timedelta(hours=-4))
PARAMETRES = {
    "incertitude_trajet_pct": 25,
    "largeur_minimale_minutes": 30,
    "granularite_minutes": 15,
    "validite_consentement_jours": 7,
    "conservation_heures": 48,
    "messages_max_par_intervention": 3,
}


def _t(h, m=0, jour=4, mois=6, tz=EDT):
    return datetime(2030, mois, jour, h, m, tzinfo=tz).isoformat()


def _entrees(**plus):
    base = {
        "intervention_id": "int-1",
        "creneau": {"debut": _t(9), "fin": _t(12)},
        "depart": {
            "instant": _t(8, 0),
            "trajet_secondes": 1800,
            "origine": "fin_intervention_precedente",
            "approximatif": False,
        },
        "retards_declares_minutes": [],
        "horodatage_reference": _t(7, 0),
    }
    base.update(plus)
    return base


def _estimer(entrees=None, parametres=None):
    resultat, verdict = eta.estimer(entrees or _entrees(), parametres or PARAMETRES)
    return resultat, verdict


def test_depart_tot_la_fenetre_part_du_debut_du_creneau_jamais_avant():
    # départ 8 h + 30 min = 8 h 30, mais le créneau du client commence à 9 h : bas = 9 h ; haut = 9 h (le départ +
    # 37,5 min = 8 h 37 < 9 h) -> largeur minimale 30 min : 9 h à 9 h 30
    resultat, verdict = _estimer()
    assert verdict is None
    assert resultat["fenetre"] == {"debut": _t(9), "fin": _t(9, 30), "largeur_minutes": 30}


def test_depart_tardif_borne_basse_physique_borne_haute_avec_incertitude_et_arrondi_vers_l_exterieur():
    # départ 9 h 07 + 40 min = 9 h 47 (bas) ; haut = 9 h 07 + 40 x 1,25 = 50 min -> 9 h 57 ; largeur 10 < 30 -> haut =
    # 9 h 47 + 30 = 10 h 17 arrondi à 15 min : bas 9 h 45 (vers le bas), haut 10 h 30 (vers le haut)
    e = _entrees(depart={"instant": _t(9, 7), "trajet_secondes": 2400, "origine": "depot", "approximatif": False})
    resultat, _ = _estimer(e)
    assert resultat["fenetre"] == {"debut": _t(9, 45), "fin": _t(10, 30), "largeur_minutes": 45}
    assert "trajet_routier_depuis_depot" in resultat["sources"]


def test_les_retards_declares_s_ajoutent_a_la_borne_haute_seulement():
    # sans retard : voir ci-dessus (9 h 45 -> 10 h 30). +20 min de retard : haut 9 h 57 + 20 = 10 h 17, mais largeur
    # mini donne 10 h 17 ; le plus grand des deux = 10 h 17 -> arrondi 10 h 30 pour 20 min ; avec 40 min : 10 h 37 ->
    # 10 h 45
    e = _entrees(
        depart={"instant": _t(9, 7), "trajet_secondes": 2400, "origine": "depot", "approximatif": False},
        retards_declares_minutes=[25, 15],
    )
    resultat, _ = _estimer(e)
    assert resultat["fenetre"]["debut"] == _t(9, 45) and resultat["fenetre"]["fin"] == _t(10, 45)
    assert resultat["retards_declares_minutes"] == 40 and "retards_declares" in resultat["sources"]


def test_sans_depart_la_fenetre_part_du_creneau_seul_et_le_dit():
    resultat, _ = _estimer(_entrees(depart=None))
    assert resultat["sources"] == ["creneau_cedule"]
    assert resultat["fenetre"]["debut"] == _t(9) and resultat["fenetre"]["fin"] == _t(9, 30)


def test_un_trajet_approximatif_est_marque_dans_la_sortie():
    e = _entrees(depart={"instant": _t(8, 0), "trajet_secondes": 3600, "origine": "depot", "approximatif": True})
    resultat, _ = _estimer(e)
    assert resultat["approximatif"] is True and "trajet_approximatif_depuis_depot" in resultat["sources"]
    assert any("mode bridé" in a for a in resultat["avertissements"])


def test_jamais_une_heure_unique_pour_aucune_entree_valide():
    for trajet in (0, 1, 59, 600, 3600, 20000):
        for depart_min in (0, 7, 30, 59):
            for retards in ([], [5], [0], [480]):
                e = _entrees(
                    depart={
                        "instant": _t(8, depart_min),
                        "trajet_secondes": trajet,
                        "origine": "depot",
                        "approximatif": False,
                    },
                    retards_declares_minutes=retards,
                    horodatage_reference=_t(0, 0),
                )
                resultat, verdict = _estimer(e)
                assert verdict is None
                assert resultat["fenetre"]["largeur_minutes"] >= PARAMETRES["largeur_minimale_minutes"]
                debut = datetime.fromisoformat(resultat["fenetre"]["debut"])
                fin = datetime.fromisoformat(resultat["fenetre"]["fin"])
                assert fin > debut and debut.minute % 15 == 0 and fin.minute % 15 == 0


def test_la_borne_basse_ne_depasse_jamais_l_arrivee_physique_la_plus_tot_possible():
    e = _entrees(depart={"instant": _t(9, 10), "trajet_secondes": 2100, "origine": "depot", "approximatif": False})
    resultat, _ = _estimer(e)
    # arrivée physique la plus tôt : 9 h 45 ; la borne basse (arrondie vers le bas) ne la dépasse pas, et l'enferme à
    # 15 min près
    bas = datetime.fromisoformat(resultat["fenetre"]["debut"])
    physique = datetime(2030, 6, 4, 9, 45, tzinfo=EDT)
    assert bas <= physique and physique - bas < timedelta(minutes=15)


def test_une_fenetre_deja_depassee_n_est_jamais_annoncee():
    e = _entrees(horodatage_reference=_t(10, 30))  # la fenêtre calculée finit à 9 h 30
    resultat, verdict = _estimer(e)
    assert resultat is None and verdict["code"] == "REJ-ETA-FENETRE-DEPASSEE"
    juste, _ = _estimer(_entrees(horodatage_reference=_t(9, 29)))
    assert juste is not None  # une minute avant la fin : encore annonçable
    egal, verdict = _estimer(_entrees(horodatage_reference=_t(9, 30)))
    assert egal is None and verdict["code"] == "REJ-ETA-FENETRE-DEPASSEE"


def test_la_sortie_ne_contient_ni_position_ni_point_de_depart_ni_nom_ni_adresse():
    e = _entrees(depart={"instant": _t(8, 0), "trajet_secondes": 900, "origine": "depot", "approximatif": False})
    resultat, _ = _estimer(e)
    texte = str(resultat).lower()
    for interdit in ("latitude", "longitude", "microdeg", "depart", "adresse", "position", "technicien", "nom"):
        assert interdit not in texte.replace("depuis_depot", "").replace("trajet_routier", ""), interdit
    assert resultat["promesse"] is False and not ({"date_ferme", "montant", "prix"} & set(resultat))


def test_aucun_cle_interdite_par_la_frontiere_m4_dans_la_sortie():
    from m4_field_ops import frontieres

    resultat, _ = _estimer()
    assert frontieres.scanner_frontieres(resultat) == []


def test_deterministe_et_n_altere_pas_les_entrees():
    e = _entrees()
    avant = copy.deepcopy(e)
    assert _estimer(e) == _estimer(e) and e == avant
    assert len(_estimer(e)[0]["empreinte"]) == 64


@pytest.mark.parametrize(
    "mutation",
    [
        lambda e: e["creneau"].update(debut=_t(13)),  # fin avant début
        lambda e: e["creneau"].update(debut="2030-06-04T09:00:00"),  # sans fuseau
        lambda e: e["creneau"].update(fin="demain"),
        lambda e: e.update(retards_declares_minutes=[-1]),
        lambda e: e.update(retards_declares_minutes=[481]),
        lambda e: e.update(retards_declares_minutes=[300, 300]),
        lambda e: e.update(retards_declares_minutes=[1.5]),
        lambda e: e.update(retards_declares_minutes=[True]),
        lambda e: e.update(retards_declares_minutes="10"),
        lambda e: e.update(retards_declares_minutes=[1] * 21),
        lambda e: e["depart"].update(trajet_secondes=-1),
        lambda e: e["depart"].update(trajet_secondes=86401),
        lambda e: e["depart"].update(trajet_secondes=1.5),
        lambda e: e["depart"].update(origine="maison"),
        lambda e: e["depart"].update(approximatif="oui"),
        lambda e: e["depart"].update(instant="tard"),
        lambda e: e["depart"].pop("approximatif"),
        lambda e: e["depart"].update(latitude_microdegres=1),
        lambda e: e.update(horodatage_reference="2030-06-04T07:00:00"),
        lambda e: e.update(intervention_id="a b"),
        lambda e: e.update(intrus=1),
        lambda e: e.pop("creneau"),
    ],
)
def test_entrees_malformees_refusees_sans_exception(mutation):
    e = _entrees()
    mutation(e)
    resultat, verdict = _estimer(e)
    assert resultat is None and verdict["code"] == "REJ-ETA-ENTREE-INVALIDE" and verdicts.est_verdict(verdict["code"])


def test_les_entrees_non_objet_sont_refusees():
    for e in (None, "x", [], 3):
        assert eta.estimer(e, PARAMETRES)[1]["code"] == "REJ-ETA-ENTREE-INVALIDE"


def test_changement_d_heure_les_instants_restent_exacts_a_l_offset_du_creneau():
    # 2030-03-10 : passage à l'heure d'été à 2 h ; un créneau à 9 h (EDT) garde son offset
    e = _entrees(
        creneau={"debut": _t(9, jour=10, mois=3), "fin": _t(12, jour=10, mois=3)},
        depart=None,
        horodatage_reference=_t(7, jour=10, mois=3),
    )
    resultat, _ = _estimer(e)
    assert resultat["fenetre"]["debut"].endswith("-04:00") and resultat["fenetre"]["debut"].startswith(
        "2030-03-10T09:00"
    )


# ------------------------------------------------------------------------------------------ réglages déclarés
def test_les_reglages_valides_sont_rendus_tels_quels():
    reglages, verdict = eta.lire_parametres(dict(PARAMETRES))
    assert verdict is None and reglages == PARAMETRES


@pytest.mark.parametrize(
    "modif",
    [
        {"incertitude_trajet_pct": None},
        {"incertitude_trajet_pct": 201},
        {"incertitude_trajet_pct": -1},
        {"largeur_minimale_minutes": 4},
        {"largeur_minimale_minutes": 241},
        {"granularite_minutes": 7},
        {"granularite_minutes": 120},
        {"validite_consentement_jours": 0},
        {"validite_consentement_jours": 31},
        {"conservation_heures": 0},
        {"conservation_heures": 721},
        {"messages_max_par_intervention": 0},
        {"messages_max_par_intervention": 11},
        {"messages_max_par_intervention": "3"},
        {"intrus": 1},
        {"largeur_minimale_minutes": 10, "granularite_minutes": 15},  # la fenêtre pourrait se réduire à un instant
    ],
)
def test_reglages_absents_ou_invalides_aucune_fenetre(modif):
    brut = {**PARAMETRES, **modif}
    reglages, verdict = eta.lire_parametres(brut)
    assert reglages is None and verdict["code"] == "REJ-ETA-PARAMETRES-ABSENTS"
    assert "incertitude_trajet_pct" in verdict["detail"] or "granularite_minutes" in verdict["detail"]


def test_sans_aucun_reglage_le_verdict_dit_tout_ce_qu_il_faut_declarer():
    for brut in (None, {}, "x"):
        assert eta.lire_parametres(brut)[1]["code"] == "REJ-ETA-PARAMETRES-ABSENTS"


# ------------------------------------------------------------------------------------------ message au client
def test_le_message_est_un_texte_fixe_avec_fenetre_avertissement_et_moyen_de_se_retirer():
    resultat, _ = _estimer(
        _entrees(depart={"instant": _t(9, 7), "trajet_secondes": 2400, "origine": "depot", "approximatif": False})
    )
    texte = eta.composer_message(resultat["fenetre"])
    assert texte == (
        "Bonjour. L'équipe prévoit arriver chez vous le mardi 4 juin entre 9 h 45 et 10 h 30. Cette fenêtre est une "
        "estimation, pas une promesse : nous vous aviserons de tout changement. Pour ne plus recevoir ces avis, "
        "répondez STOP."
    )


@pytest.mark.parametrize(
    ("debut", "fin", "attendu"),
    [
        (
            datetime(2030, 7, 1, 8, 0, tzinfo=EDT),
            datetime(2030, 7, 1, 9, 0, tzinfo=EDT),
            "le lundi 1er juillet entre 8 h et 9 h.",
        ),
        (
            datetime(2030, 12, 25, 13, 15, tzinfo=EST),
            datetime(2030, 12, 25, 14, 0, tzinfo=EST),
            "le mercredi 25 décembre entre 13 h 15 et 14 h.",
        ),
        (
            datetime(2030, 8, 31, 23, 0, tzinfo=EDT),
            datetime(2030, 9, 1, 0, 30, tzinfo=EDT),
            "entre le samedi 31 août à 23 h et le dimanche 1 septembre à 0 h 30.",
        ),
    ],
)
def test_formats_francais_des_dates_et_des_heures(debut, fin, attendu):
    texte = eta.composer_message({"debut": debut.isoformat(), "fin": fin.isoformat()})
    assert attendu in texte


def test_le_message_ne_contient_ni_nom_ni_adresse_ni_lien_ni_prix():
    texte = eta.composer_message({"debut": _t(9), "fin": _t(10)})
    for interdit in ("http", "www", "@", "$", "rue ", "technicien", "lien", "eq-", "int-"):
        assert interdit not in texte.lower(), interdit


def test_pas_d_horloge_pas_de_reseau_pas_d_opsys_dans_les_modules_purs():
    for nom in ("eta_client", "suivi_client"):
        arbre = ast.parse((_SRC / "m4_field_ops" / f"{nom}.py").read_text(encoding="utf-8"))
        importes = {n.names[0].name.split(".")[0] for n in ast.walk(arbre) if isinstance(n, ast.Import)}
        importes |= {
            (n.module or "").split(".")[0] for n in ast.walk(arbre) if isinstance(n, ast.ImportFrom) and n.level == 0
        }
        assert not importes & {"opsys", "random", "time", "socket", "urllib", "http", "secrets", "uuid", "os"}, nom
