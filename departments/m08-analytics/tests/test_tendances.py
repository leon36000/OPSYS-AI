"""C8 — tendances déterministes sur l'historique RÉEL des constructions de M8.

L'historique de ``m8_ent_mesures_hist`` n'est pas un échantillonnage régulier : chaque ligne vient d'une construction
déclenchée par un changement de source. Les tests ci-dessous fixent donc les règles du chantier :

- variation absolue et relative calculées sur des valeurs stockées, sans division par zéro (ni base négative) ;
- moyenne mobile terminale explicitement définie ;
- XmR et prévision linéaire SEULEMENT si la cadence observée est exactement régulière et le minimum d'observations
  atteint ; sinon ``non_evalue`` avec la raison, jamais une valeur inventée ;
- observations non calculables, illisibles, ambiguës ou de version incompatible comptées et exclues ;
- aucun zéro inventé, aucune saisonnalité, aucun intervalle de confiance, aucune prévision présentée comme un fait ;
- reçu de calcul vérifiable et sortie bornée ;
- scénario E2E sur une vraie base SQLite migrée et les vrais outils M8, sans écriture.

Données fictives (``fictif: true``). Aucune horloge réelle : tous les instants sont injectés.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest
from m8_analytics import catalogue_mesures, copilote, entrepot_stockage, jeux_fictifs, tendances
from m8_analytics import outils as m8_outils
from m8_analytics.registre import RegistreSnapshots
from sqlalchemy import func, select

from opsys import contexte, identite, stockage
from opsys.contexte import IdentiteAppelante
from opsys.outils import executer, executer_atomique
from opsys.secrets_coffre import cle_maitresse
from opsys.stockage.schema import EVENEMENTS_SORTANTS, M8_ENT_CONSTRUCTIONS, M8_ENT_MESURES_HIST

FICTIF = True
VERSION = "a" * 64
AUTRE_VERSION = "b" * 64
METRIQUE = "m8_taux_acceptation_pct"
MAINTENANT = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
ENTREE = {
    "metric_id": METRIQUE,
    "nom": "Taux d'acceptation",
    "unite": "%",
    "proprietaire": "M2",
    "version_definition": VERSION,
    "fraicheur": {"fenetre_s": 86400},
}


def _instant(heures: int) -> str:
    return (datetime(2026, 10, 30, 0, 0, tzinfo=UTC) + timedelta(hours=heures)).isoformat()


def _ligne(
    rang: int,
    valeur: str | None,
    heures: int,
    *,
    version: str = VERSION,
    statut: str = "calculee",
    derniere: str | None = None,
    construction: str | None = None,
) -> dict:
    return {
        "construction_id": construction or f"c{rang:03d}",
        "metric_id": METRIQUE,
        "construit_le": _instant(heures),
        "statut": statut,
        "valeur": valeur,
        "version_definition": version,
        "dernier_fait_le": _instant(heures - 1) if derniere is None else derniere,
    }


def _analyse(lignes, **options):
    maintenant = options.pop("maintenant", MAINTENANT)
    return tendances.analyser(lignes, ENTREE, maintenant, **options)


# ---------------------------------------------------------------------------
# Variation, moyenne mobile, zéro
# ---------------------------------------------------------------------------
def test_variation_absolue_et_relative_et_moyenne_mobile_definie():
    resultat = _analyse([_ligne(1, "10.00", 0), _ligne(2, "12.00", 1), _ligne(3, "15.00", 2)])
    premiere = resultat["variation"]
    assert premiere["absolue"]["statut"] == "calculee"
    assert premiere["absolue"]["valeur"] == "5.00"
    assert premiere["relative_pct"]["statut"] == "calculee"
    assert premiere["relative_pct"]["valeur"] == "50.00"
    assert resultat["couverture"]["hors_fenetre"] == 0
    assert resultat["couverture"]["etendue_s"] == "7200"
    assert premiere["de"]["construit_le"] == _instant(0)
    assert premiere["a"]["construit_le"] == _instant(2)

    derniere = resultat["variation_derniere"]
    assert derniere["absolue"]["valeur"] == "3.00"
    assert derniere["relative_pct"]["valeur"] == "25.00"

    moyenne = resultat["moyenne_mobile"]
    assert moyenne["statut"] == "calculee"
    assert moyenne["fenetre"] == 3 and moyenne["n"] == 3
    assert moyenne["valeur"] == "12.33"  # (10 + 12 + 15) / 3 = 12.333…, arrondi 2 décimales
    assert "dernières observations valides" in moyenne["definition"]


def test_une_base_nulle_ne_divise_jamais_et_n_invente_pas_zero():
    resultat = _analyse([_ligne(1, "0.00", 0), _ligne(2, "5.00", 1)])
    variation = resultat["variation"]
    assert variation["absolue"]["valeur"] == "5.00"  # la variation absolue reste calculable
    assert variation["relative_pct"]["statut"] == "non_calculable"
    assert variation["relative_pct"]["valeur"] is None
    assert variation["relative_pct"]["raison"] == "base_nulle"
    assert resultat["variation_derniere"]["relative_pct"]["raison"] == "base_nulle"


def test_une_base_negative_rend_la_relative_non_calculable_au_lieu_de_tromper():
    resultat = _analyse([_ligne(1, "-10.00", 0), _ligne(2, "-5.00", 1)])
    assert resultat["variation"]["absolue"]["valeur"] == "5.00"
    assert resultat["variation"]["relative_pct"]["statut"] == "non_calculable"
    assert resultat["variation"]["relative_pct"]["raison"] == "base_negative"


def test_moins_de_deux_observations_laisse_la_moyenne_non_evaluee_sans_zero():
    resultat = _analyse([_ligne(1, "10.00", 0)])
    assert resultat["moyenne_mobile"]["statut"] == "non_evaluee"
    assert resultat["moyenne_mobile"]["valeur"] is None
    assert resultat["moyenne_mobile"]["raison"] == "moins_de_2_observations"
    assert resultat["variation"]["absolue"]["statut"] == "non_calculable"
    assert resultat["variation"]["absolue"]["valeur"] is None


# ---------------------------------------------------------------------------
# Filtrage des observations hostiles et incompatibles
# ---------------------------------------------------------------------------
def test_les_observations_non_calculables_invalides_et_incompatibles_sont_comptees_et_exclues():
    lignes = [
        _ligne(1, "10.00", 0),
        _ligne(2, None, 1, statut="non_calculable"),
        _ligne(3, "NaN", 2),
        _ligne(4, "Infinity", 3),
        _ligne(5, "12.00", 4, version=AUTRE_VERSION),
        _ligne(6, "x" * 81, 5),
        _ligne(7, "13.00", 6),
    ]
    resultat = _analyse(lignes)
    exclusions = resultat["exclusions"]
    assert exclusions["non_calculable"] == 1
    assert exclusions["valeur_invalide"] == 3  # NaN, Infinity, texte démesuré
    assert exclusions["version_incompatible"] == 1
    assert [point["valeur"] for point in resultat["serie"]] == ["10.00", "13.00"]
    assert resultat["couverture"]["lues"] == 7
    assert resultat["couverture"]["retenues"] == 2
    assert all(point["valeur"] is not None for point in resultat["serie"])
    assert len(exclusions["exemples"]) <= 5


def test_une_ligne_d_une_autre_mesure_est_exclue_meme_si_sa_valeur_est_valide():
    ligne = _ligne(1, "10.00", 0)
    ligne["metric_id"] = "m8_autre_mesure"
    resultat = _analyse([ligne])
    assert resultat["exclusions"]["metrique_incompatible"] == 1
    assert resultat["serie"] == []


def test_un_identifiant_ou_un_instant_illisible_est_exclu_sans_planter():
    lignes = [
        _ligne(1, "10.00", 0),
        _ligne(2, "11.00", 1, construction="x" * 65),
        _ligne(3, "12.00", 2),
    ]
    lignes[2]["construit_le"] = "2026-10-30T12:00:00"  # sans fuseau : instant illisible
    resultat = _analyse(lignes)
    assert resultat["exclusions"]["construction_invalide"] == 1
    assert resultat["exclusions"]["instant_construction_invalide"] == 1
    assert [point["valeur"] for point in resultat["serie"]] == ["10.00"]


def test_deux_constructions_au_meme_instant_sont_ambigues_et_exclues_ensemble():
    lignes = [_ligne(1, "10.00", 0), _ligne(2, "12.00", 0, construction="c002"), _ligne(3, "14.00", 1)]
    resultat = _analyse(lignes)
    assert resultat["exclusions"]["instant_ambigu"] == 2
    assert [point["valeur"] for point in resultat["serie"]] == ["14.00"]
    assert resultat["couverture"]["cadence"] == "non_evaluee"  # un seul point retenu


def test_un_doublon_de_construction_est_exclu_sans_choisir_une_version():
    lignes = [
        _ligne(1, "10.00", 0, construction="c001"),
        _ligne(2, "11.00", 1, construction="c001"),
        _ligne(3, "12.00", 2, construction="c003"),
    ]
    resultat = _analyse(lignes)
    assert resultat["exclusions"]["doublon"] == 2
    assert [point["valeur"] for point in resultat["serie"]] == ["12.00"]


def test_aucune_observation_utile_ne_produit_aucune_valeur_et_le_dit():
    resultat = _analyse([_ligne(1, None, 0, statut="non_calculable"), _ligne(2, "NaN", 1)])
    assert resultat["serie"] == []
    for cle in ("moyenne_mobile", "prevision"):
        assert resultat[cle]["statut"] in ("non_calculable", "non_evaluee")
    assert resultat["xmr"]["statut"] == "non_evalue"
    for cle in ("variation", "variation_derniere"):
        assert resultat[cle]["absolue"]["statut"] == "non_calculable"
        assert resultat[cle]["relative_pct"]["statut"] == "non_calculable"
    assert resultat["variation"]["absolue"]["valeur"] is None
    assert resultat["moyenne_mobile"]["valeur"] is None
    assert resultat["couverture"]["fraicheur"]["peut_etre_montree_comme_a_jour"] is False
    assert resultat["couverture"]["fraicheur"]["construction_dans_le_futur"] is False
    assert resultat["xmr"]["statut"] == "non_evalue"
    assert resultat["prevision"]["statut"] == "non_evaluee"


# ---------------------------------------------------------------------------
# Précisions : raisons absentes, bases positives, bornes de moyenne, âge 0 et futur
# ---------------------------------------------------------------------------
def test_une_variation_calculable_ne_porte_aucune_raison_et_une_base_positive_reste_valide():
    resultat = _analyse([_ligne(1, "0.50", 0), _ligne(2, "0.75", 1)])
    assert "raison" not in resultat["variation"]["absolue"]
    assert "raison" not in resultat["variation"]["relative_pct"]
    assert resultat["variation"]["relative_pct"]["valeur"] == "50.00"


def test_deux_points_suffisent_a_la_moyenne_mobile_et_un_seul_donne_la_fenetre_zero():
    deux = _analyse([_ligne(1, "10.00", 0), _ligne(2, "15.00", 1)])
    assert deux["moyenne_mobile"]["statut"] == "calculee"
    assert deux["moyenne_mobile"]["valeur"] == "12.50" and deux["moyenne_mobile"]["fenetre"] == 2
    un = _analyse([_ligne(1, "10.00", 0)])
    assert un["moyenne_mobile"]["fenetre"] == 0
    assert un["couverture"]["intervalles"]["n"] == 0


def test_une_construction_a_l_instant_meme_est_acceptee_et_une_construction_apres_est_ecartee_et_comptee():
    maintenant = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
    au_meme_instant = _analyse(
        [_ligne(1, "10.00", 11), _ligne(2, "12.00", 12)], maintenant=maintenant
    )
    assert au_meme_instant["couverture"]["fraicheur"]["age_construction_s"] == 0
    assert au_meme_instant["couverture"]["fraicheur"]["construction_dans_le_futur"] is False
    assert au_meme_instant["couverture"]["futurs_ecartes"] == 0
    apres = _analyse([_ligne(1, "10.00", 11), _ligne(2, "12.00", 13)], maintenant=maintenant)
    assert [point["valeur"] for point in apres["serie"]] == ["10.00"]
    assert apres["couverture"]["futurs_ecartes"] == 1
    assert apres["couverture"]["fraicheur"]["statut"] == "a_jour"
    assert apres["couverture"]["fraicheur"]["construction_dans_le_futur"] is False
    assert apres["couverture"]["fraicheur"]["peut_etre_montree_comme_a_jour"] is True


def test_xmr_avec_deux_points_est_non_evalue_pour_moins_de_huit_et_l_amplitude_part_du_premier_ecart():
    deux = _analyse([_ligne(1, "10.00", 0), _ligne(2, "12.00", 1)])
    assert deux["xmr"]["raison"] == "moins_de_8_observations" and deux["xmr"]["n"] == 2
    valeurs = ["10.00", "20.00", "30.00", "31.00", "32.00", "33.00", "34.00", "35.00"]
    saut = _analyse([_ligne(rang, valeur, rang - 1) for rang, valeur in enumerate(valeurs, start=1)])
    assert saut["xmr"]["amplitude_moyenne"] == "3.57"  # (10+10+1+1+1+1+1) / 7


def test_xmr_sur_une_serie_constante_reste_dans_les_limites_egales():
    constante = _analyse([_ligne(rang, "10.00", rang - 1) for rang in range(1, 9)])
    assert constante["xmr"]["limite_haute"] == "10.00" and constante["xmr"]["limite_basse"] == "10.00"
    assert constante["xmr"]["signal"] == "DANS_LES_LIMITES"


# ---------------------------------------------------------------------------
# Cadence, XmR, prévision
# ---------------------------------------------------------------------------
def test_une_cadence_irreguliere_interdit_xmr_et_prevision_mais_pas_la_variation():
    lignes = [_ligne(1, "10.00", 0), _ligne(2, "12.00", 1), _ligne(3, "15.00", 3)]
    resultat = _analyse(lignes)
    assert resultat["couverture"]["cadence"] == "irreguliere"
    assert resultat["variation"]["absolue"]["valeur"] == "5.00"
    assert resultat["xmr"]["statut"] == "non_evalue"
    assert resultat["xmr"]["raison"] == "cadence_irreguliere"
    assert resultat["prevision"]["statut"] == "non_evaluee"
    assert resultat["prevision"]["raison"] == "cadence_irreguliere"
    assert resultat["prevision"]["valeur_prevue"] is None


def test_xmr_en_decimal_et_prevision_lineaire_sur_une_cadence_exactement_reguliere():
    valeurs = ["10.00", "12.00", "13.00", "17.00", "16.00", "19.00", "21.00", "22.00"]
    lignes = [_ligne(rang, valeur, rang - 1) for rang, valeur in enumerate(valeurs, start=1)]
    resultat = _analyse(lignes, fenetre_moyenne_mobile=3, horizon_prevision=1)
    assert resultat["couverture"]["cadence"] == "reguliere"
    assert resultat["couverture"]["intervalles"]["n"] == 7
    assert resultat["couverture"]["intervalles"]["min_s"] == "3600"
    assert resultat["couverture"]["intervalles"]["max_s"] == "3600"

    xmr = resultat["xmr"]
    assert xmr["statut"] == "evalue"
    assert xmr["n"] == 8
    # moyenne 16,25 ; amplitudes 2,1,4,1,3,2,1 -> amplitude moyenne 2 ; 16,25 ± 2,66×2
    assert xmr["centre"] == "16.25"
    assert xmr["amplitude_moyenne"] == "2.00"
    assert xmr["limite_haute"] == "21.57"
    assert xmr["limite_basse"] == "10.93"
    assert xmr["signal"] == "HORS_LIMITE_SUPERIEURE"
    assert xmr["valeur_observee"] == "22.00"

    prevision = resultat["prevision"]
    assert prevision["statut"] == "evaluee"
    assert prevision["methode"] == "moindres_carres_lineaire"
    # moindres carrés sur x=0..7 : pente 73/42 = 1,738095…, ordonnée 10,166666… ; x=8 -> 24,071428…
    assert prevision["pente"] == "1.74"
    assert prevision["ordonnee"] == "10.17"
    assert prevision["valeur_prevue"] == "24.07"
    assert prevision["bornes_observees"]["min_residu"] == "-1.12"
    assert prevision["bornes_observees"]["max_residu"] == "1.62"
    assert prevision["bornes_observees"]["intervalle"] == ["22.95", "25.69"]
    assert "jamais un fait observé" in prevision["avertissement"]


def test_moins_de_huit_observations_refuse_xmr_et_prevision_avec_la_raison():
    lignes = [_ligne(rang, str(10 + rang), rang - 1) for rang in range(1, 8)]
    resultat = _analyse(lignes)
    assert resultat["couverture"]["cadence"] == "reguliere"
    assert resultat["xmr"]["statut"] == "non_evalue"
    assert resultat["xmr"]["raison"] == "moins_de_8_observations"
    assert resultat["prevision"]["statut"] == "non_evaluee"
    assert resultat["prevision"]["raison"] == "moins_de_8_observations"


def test_aucune_saisonnalite_ni_intervalle_de_confiance_ne_sont_pretendus():
    resultat = _analyse([_ligne(rang, str(10 + rang), rang - 1) for rang in range(1, 9)])
    assert "saisonnalite" not in resultat
    assert "intervalle_confiance" not in resultat
    assert resultat["prevision"]["methode"] != "saisonniere"
    assert resultat["non_livre"]["saisonnalite"]
    assert resultat["non_livre"]["intervalle_confiance"]
    assert resultat["couverture"]["trous"] == "non_evaluable"
    assert "cadence attendue" in resultat["couverture"]["raison_trous"]


# ---------------------------------------------------------------------------
# Fenêtre, reçu, entrées hostiles
# ---------------------------------------------------------------------------
def test_la_fenetre_garde_les_derniers_points_valides_et_compte_les_anciens():
    lignes = [_ligne(rang, str(10 + rang), rang - 1) for rang in range(1, 6)]
    resultat = _analyse(lignes, fenetre_observations=3)
    assert [point["valeur"] for point in resultat["serie"]] == ["13.00", "14.00", "15.00"]
    assert resultat["couverture"]["hors_fenetre"] == 2
    assert resultat["couverture"]["fenetre_pleine"] is True


def test_le_recu_est_verifiable_et_change_avec_la_serie():
    premier = _analyse([_ligne(1, "10.00", 0), _ligne(2, "12.00", 1)])
    assert tendances.verifier_recu(premier["recu"]) is True
    falsifie = dict(premier["recu"])
    falsifie["n_points"] = 99
    assert tendances.verifier_recu(falsifie) is False
    assert tendances.verifier_recu(None) is False
    assert tendances.verifier_recu({"schema": "autre", "empreinte": "x"}) is False
    assert tendances.verifier_recu({"schema": tendances.SCHEMA_RECU, "empreinte": 3}) is False
    assert tendances.verifier_recu(
        {"schema": tendances.SCHEMA_RECU, "empreinte": "x", "objet": object()}
    ) is False
    second = _analyse([_ligne(1, "11.00", 0), _ligne(2, "12.00", 1)])
    assert premier["recu"]["empreinte_serie"] != second["recu"]["empreinte_serie"]
    assert premier["recu"]["empreinte"] != second["recu"]["empreinte"]


@pytest.mark.parametrize(
    "options, code",
    [
        ({"fenetre_observations": 1}, "REJ-TENDANCES-FENETRE-INVALIDE"),
        ({"fenetre_observations": 201}, "REJ-TENDANCES-FENETRE-INVALIDE"),
        ({"fenetre_observations": True}, "REJ-TENDANCES-FENETRE-INVALIDE"),
        ({"fenetre_moyenne_mobile": 1}, "REJ-TENDANCES-MOYENNE-MOBILE-INVALIDE"),
        ({"fenetre_moyenne_mobile": 13}, "REJ-TENDANCES-MOYENNE-MOBILE-INVALIDE"),
        ({"horizon_prevision": 0}, "REJ-TENDANCES-HORIZON-INVALIDE"),
        ({"horizon_prevision": 13}, "REJ-TENDANCES-HORIZON-INVALIDE"),
    ],
)
def test_les_parametres_de_fenetre_sont_bornes(options, code):
    with pytest.raises(ValueError, match=code):
        _analyse([_ligne(1, "10.00", 0)], **options)


def test_la_precision_decimale_est_epinglee():
    assert tendances.PRECISION_DECIMALE == 28


def test_les_bornes_de_fenetre_sont_incluses():
    # Toutes les observations sont PASSÉES : l'instant de lecture est postérieur à la série, pour ne pas
    # confondre la borne de fenêtre avec l'exclusion des constructions futures.
    maintenant = MAINTENANT + timedelta(hours=500)
    lignes = [_ligne(rang, str(rang), rang - 1) for rang in range(1, 201)]
    assert _analyse(lignes, maintenant=maintenant, fenetre_observations=2)["couverture"]["retenues"] == 2
    assert _analyse(lignes, maintenant=maintenant, fenetre_observations=200)["couverture"]["retenues"] == 200
    assert _analyse(lignes[:12], maintenant=maintenant, fenetre_moyenne_mobile=2)["moyenne_mobile"]["fenetre"] == 2
    assert _analyse(lignes[:12], maintenant=maintenant, fenetre_moyenne_mobile=12)["moyenne_mobile"]["fenetre"] == 12
    assert _analyse(lignes, maintenant=maintenant, horizon_prevision=1)["prevision"]["horizon"] == 1
    assert _analyse(lignes, maintenant=maintenant, horizon_prevision=12)["prevision"]["horizon"] == 12


def test_un_historique_de_1000_lignes_est_accepte_et_1001_refuse():
    mille = [_ligne(rang, "10.00", rang) for rang in range(1000)]
    assert _analyse(mille, fenetre_observations=2)["couverture"]["lues"] == 1000
    with pytest.raises(ValueError, match="REJ-TENDANCES-HISTORIQUE-TROP-VOLUMINEUX"):
        _analyse([_ligne(rang, "10.00", rang) for rang in range(1001)])


def test_un_fuseau_qui_ne_donne_pas_de_decalage_est_refuse():
    from datetime import tzinfo

    class SansDecalage(tzinfo):
        def utcoffset(self, dt):
            return None

        def dst(self, dt):
            return None

        def tzname(self, dt):
            return "fictif"

    with pytest.raises(ValueError, match="REJ-TENDANCES-MAINTENANT-INVALIDE"):
        tendances.analyser([], ENTREE, datetime(2026, 10, 30, 12, 0, tzinfo=SansDecalage()))


def test_une_fraicheur_vide_est_refusee():
    entree = {**ENTREE, "fraicheur": {}}
    with pytest.raises(ValueError, match="REJ-TENDANCES-ENTREE-INVALIDE"):
        tendances.analyser([], entree, MAINTENANT)


def test_les_longueurs_limites_et_la_troncature_des_exemples_sont_respectees():
    identifiant_64 = "c" * 64
    accepte = _ligne(1, "0" * 78 + "12", 0, construction=identifiant_64)
    resultat = _analyse([accepte])
    assert [point["valeur"] for point in resultat["serie"]] == ["12.00"]
    court = _ligne(2, "12.00", 1, construction="c")
    assert [point["valeur"] for point in _analyse([court])["serie"]] == ["12.00"]

    trop_long = _ligne(2, "0" * 79 + "12", 1, construction=identifiant_64)
    assert _analyse([trop_long])["exclusions"]["valeur_invalide"] == 1

    exemple = _ligne(3, "10.00", 2, construction=identifiant_64)
    exemple["statut"] = "non_calculable"
    resultat = _analyse([exemple])
    assert resultat["exclusions"]["exemples"][0]["construction_id"] == identifiant_64[:16]


def test_les_valeurs_numeriques_sont_acceptees_et_les_booleens_refuses():
    entier = _ligne(1, None, 0)
    entier["valeur"] = 12
    assert _analyse([entier])["serie"][0]["valeur"] == "12.00"
    booleen = _ligne(2, None, 1)
    booleen["valeur"] = True
    assert _analyse([booleen])["exclusions"]["valeur_invalide"] == 1


def test_un_dernier_fait_illisible_ou_trop_long_est_exclu():
    illisible = _ligne(1, "10.00", 0, derniere="pas un instant")
    assert _analyse([illisible])["exclusions"]["instant_fait_invalide"] == 1
    long_mais_lisible = _ligne(2, "11.00", 1)
    long_mais_lisible["dernier_fait_le"] = "2026-10-30T00:00:00." + "0" * 16 + "+00:00"
    assert _analyse([long_mais_lisible])["exclusions"]["instant_fait_invalide"] == 1


def test_les_exemples_d_exclusion_sont_bornees_et_les_lignes_non_dict_comptees():
    lignes = [None, None, None, None]  # quatre lignes non-dict : trois exemples, pas un de plus
    sans_identifiant = _ligne(1, "10.00", 0)
    sans_identifiant["construction_id"] = ""
    lignes.append(sans_identifiant)
    lignes.append(_ligne(2, "10.00", 1, construction="d001"))
    lignes.append(_ligne(3, "10.00", 2, construction="d001"))
    lignes.append(_ligne(4, "10.00", 3, version=AUTRE_VERSION))
    lignes.append(_ligne(5, "10.00", 4, construction="d005"))
    lignes.append(_ligne(6, "10.00", 4, construction="d006"))
    resultat = _analyse(lignes)
    assert resultat["exclusions"]["construction_invalide"] == 5  # 4 non-dict + l'identifiant vide
    assert len(resultat["exclusions"]["exemples"]) == 3


def test_une_ligne_non_dict_est_comptee_une_seule_fois():
    resultat = _analyse([None])
    assert resultat["exclusions"]["construction_invalide"] == 1


def test_un_groupe_ambigu_ne_remplit_pas_plus_de_trois_exemples():
    lignes = [None]  # un exemple déjà présent
    lignes.extend(_ligne(rang, "10.00", 0, construction=f"a{rang}") for rang in range(4))
    resultat = _analyse(lignes)
    assert resultat["exclusions"]["instant_ambigu"] == 4
    assert len(resultat["exclusions"]["exemples"]) == 3


def test_un_historique_trop_volumineux_est_refuse_avant_tout_calcul():
    with pytest.raises(ValueError, match="REJ-TENDANCES-HISTORIQUE-TROP-VOLUMINEUX"):
        _analyse([_ligne(rang, "10.00", rang) for rang in range(1001)])


@pytest.mark.parametrize("maintenant", [None, "2026-10-30T12:00:00", datetime(2026, 10, 30, 12, 0)])
def test_un_maintenant_sans_fuseau_ou_non_datetime_est_refuse(maintenant):
    with pytest.raises(ValueError, match="REJ-TENDANCES-MAINTENANT-INVALIDE"):
        tendances.analyser([], ENTREE, maintenant)


def test_une_entree_sans_version_de_definition_est_refusee():
    without = {cle: valeur for cle, valeur in ENTREE.items() if cle != "version_definition"}
    with pytest.raises(ValueError, match="REJ-TENDANCES-ENTREE-INVALIDE"):
        tendances.analyser([], without, MAINTENANT)


# ---------------------------------------------------------------------------
# E2E : vraie base SQLite, vrais outils M8
# ---------------------------------------------------------------------------
@pytest.fixture
def base(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    stockage.migrer(url)
    dossier = tmp_path / "cles"
    dossier.mkdir(mode=0o700)
    cle_maitresse.generer_fichier(dossier / "coffre.cle")
    monkeypatch.setenv(cle_maitresse.ENV_FICHIER, str(dossier / "coffre.cle"))
    monkeypatch.delenv(cle_maitresse.ENV_CLE, raising=False)
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin fictif", "mot-de-passe-admin-fictif-1", ["admin"])
    yield
    stockage.liberer()


def _outils(cibles):
    return {outil.nom: outil for outil in m8_outils.outils(
        registre_cible=RegistreSnapshots(), definitions_cible=[], **cibles
    )}


def _cibles(registres):
    return {
        "faits_cible": registres["chantier"],
        "faits_entonnoir_cible": registres["entonnoir"],
        "faits_contenus_cible": registres["contenus"],
        "faits_cash_libre_cible": registres["cash_libre"],
        "historique_sante_cible": [],
        "publications_cible": [],
    }


def _synchroniser(cibles, registres):
    cibles["faits_cible"][:] = registres["chantier"]
    cibles["faits_entonnoir_cible"][:] = registres["entonnoir"]
    cibles["faits_contenus_cible"][:] = registres["contenus"]
    cibles["faits_cash_libre_cible"][:] = registres["cash_libre"]


def _appeler(outils, nom, atomique=True, **arguments):
    return (executer_atomique if atomique else executer)(outils[nom], arguments)


def _tendances_completes(outils, **arguments):
    """Lit toutes les pages et recompose la série : le reçu couvre la série entière, pas une page."""
    reponse = _appeler(outils, "m8_lire_tendances", **arguments)
    assert reponse["ok"] is True, reponse
    resultat = reponse["resultat"]
    assert len(json.dumps(resultat, ensure_ascii=False)) <= m8_outils.BUDGET_SORTIE
    serie = list(resultat["serie"])
    while resultat["prochain_depart"] is not None:
        reponse = _appeler(
            outils, "m8_lire_tendances", depart=resultat["prochain_depart"], **arguments
        )
        assert reponse["ok"] is True, reponse
        resultat = reponse["resultat"]
        assert len(json.dumps(resultat, ensure_ascii=False)) <= m8_outils.BUDGET_SORTIE
        serie.extend(resultat["serie"])
    resultat["serie"] = serie
    return resultat


def _compter(cnx, table):
    return cnx.execute(select(func.count()).select_from(table)).scalar_one()


def test_e2e_tendances_sur_vraie_base_plusieurs_versions_etats_et_aucune_ecriture(base):
    registres = jeux_fictifs.registres_fictifs(cash_libre_cad="20000.00")
    cibles = _cibles(registres)
    outils = _outils(cibles)

    # Huit constructions horaires régulières, valeurs 20 000 → 27 000 : une vraie suite d'états, pas un échantillon.
    for heure, valeur in enumerate(range(20000, 27001, 1000)):
        registres = jeux_fictifs.registres_fictifs(cash_libre_cad=f"{valeur}.00")
        _synchroniser(cibles, registres)
        construit = _appeler(
            outils, "m8_construire_entrepot", maintenant=(MAINTENANT + timedelta(hours=heure)).isoformat()
        )
        assert construit["ok"] is True and construit["resultat"]["statut"] == "construit"

    # Une construction NON CALCULABLE (M5 n'a rien constaté) : elle ne doit jamais devenir un zéro.
    registres = jeux_fictifs.registres_fictifs(cash_libre_cad=None)
    _synchroniser(cibles, registres)
    assert _appeler(outils, "m8_construire_entrepot", maintenant=(MAINTENANT + timedelta(hours=8)).isoformat())[
        "ok"
    ] is True

    # Une construction d'une AUTRE version de définition : incompatible avec le catalogue courant.
    registres = jeux_fictifs.registres_fictifs(cash_libre_cad="29000.00")
    _synchroniser(cibles, registres)
    catalogue = catalogue_mesures.charger()
    version_courante = catalogue_mesures.par_identifiant(catalogue)["m8_cash_libre_cad"]["version_definition"]
    autre = json.loads(json.dumps(catalogue))
    for entree in autre["mesures"]:
        if entree["metric_id"] == "m8_cash_libre_cad":
            entree["version_definition"] = AUTRE_VERSION
    autre["version_catalogue"] = "c" * 64
    with stockage.transaction() as cnx:
        entrepot_stockage.reconstruire(cnx, registres, autre, (MAINTENANT + timedelta(hours=9)).isoformat())

    # Compte AVANT la lecture : elle ne doit rien écrire, ni historique, ni construction, ni événement.
    with stockage.transaction() as cnx:
        avant = (
            _compter(cnx, M8_ENT_CONSTRUCTIONS),
            _compter(cnx, M8_ENT_MESURES_HIST),
            _compter(cnx, EVENEMENTS_SORTANTS),
        )

    resultat = _tendances_completes(
        outils,
        metric_id="m8_cash_libre_cad",
        maintenant=(MAINTENANT + timedelta(hours=10)).isoformat(),
        fenetre_observations=8,
        fenetre_moyenne_mobile=3,
        horizon_prevision=1,
    )
    assert resultat["metric_id"] == "m8_cash_libre_cad"
    assert resultat["unite"] == "CAD"
    assert resultat["version_definition"] == version_courante
    assert resultat["etat_courant"]["valeur"] == "29000.00"
    assert resultat["etat_courant"]["detail"] is None
    assert resultat["etat_courant"]["qualite"] in ("ok", "non_evaluee")
    assert resultat["couverture"]["retenues"] == 8
    assert resultat["couverture"]["cadence"] == "reguliere"
    assert resultat["exclusions"]["non_calculable"] == 1
    assert resultat["exclusions"]["version_incompatible"] == 1
    assert [point["valeur"] for point in resultat["serie"]] == [
        "20000.00",
        "21000.00",
        "22000.00",
        "23000.00",
        "24000.00",
        "25000.00",
        "26000.00",
        "27000.00",
    ]
    assert all("version_definition" not in point for point in resultat["serie"])
    assert resultat["variation"]["absolue"]["valeur"] == "7000.00"
    assert resultat["variation"]["relative_pct"]["valeur"] == "35.00"
    assert resultat["moyenne_mobile"]["valeur"] == "26000.00"
    assert resultat["xmr"]["statut"] == "evalue" and resultat["xmr"]["signal"] == "HORS_LIMITE_SUPERIEURE"
    assert resultat["prevision"]["statut"] == "evaluee" and resultat["prevision"]["valeur_prevue"] == "28000.00"
    assert "jamais un fait observé" in resultat["prevision"]["avertissement"]
    assert tendances.verifier_recu(resultat["recu"]) is True

    with stockage.transaction() as cnx:
        apres = (
            _compter(cnx, M8_ENT_CONSTRUCTIONS),
            _compter(cnx, M8_ENT_MESURES_HIST),
            _compter(cnx, EVENEMENTS_SORTANTS),
        )
    assert apres == avant

    # La mesure COURANTE peut redevenir non calculable : l'état courant le dit, l'historique reste lisible.
    cibles["faits_cash_libre_cible"].clear()
    courant = _appeler(
        outils, "m8_lire_tendances", metric_id="m8_cash_libre_cad",
        maintenant=(MAINTENANT + timedelta(hours=10)).isoformat(), fenetre_observations=8,
    )["resultat"]
    assert courant["etat_courant"]["statut"] == "non_calculable"
    assert courant["etat_courant"]["valeur"] is None and courant["etat_courant"]["detail"]


def test_e2e_la_limite_de_lecture_de_l_historique_est_bornee(base, monkeypatch):
    registres = jeux_fictifs.registres_fictifs()
    outils = _outils(_cibles(registres))
    _appeler(outils, "m8_construire_entrepot", maintenant=MAINTENANT.isoformat())
    vus: list[int] = []

    def espion(cnx, metric_id, limite=200):
        vus.append(limite)
        return []

    monkeypatch.setattr(entrepot_stockage, "lire_historique", espion)
    for fenetre in (2, 30, 200):
        _appeler(
            outils, "m8_lire_tendances", metric_id="m8_cash_libre_cad",
            maintenant=MAINTENANT.isoformat(), fenetre_observations=fenetre,
        )
    assert vus == [50, 150, 1000]


def test_e2e_l_outil_est_ferme_aux_appareils_et_refuse_les_entrees_invalides(base):
    registres = jeux_fictifs.registres_fictifs()
    cibles = _cibles(registres)
    outils = _outils(cibles)
    _appeler(outils, "m8_construire_entrepot", maintenant=MAINTENANT.isoformat())

    with contexte.appele_par_appareil(IdentiteAppelante("admin.fictif", "admin")):
        refus = _appeler(outils, "m8_lire_tendances", metric_id="m8_cash_libre_cad",
                         maintenant=MAINTENANT.isoformat())
    assert refus["ok"] is False and "REJ-IDENTITE-APPAREIL-INVALIDE" in refus["details"]

    hors = _appeler(outils, "m8_lire_tendances", atomique=False, metric_id="m8_cash_libre_cad",
                    maintenant=MAINTENANT.isoformat())
    assert hors["ok"] is False and "REJ-ANALYTIQUE-HORS-TRANSACTION" in hors["details"]

    inconnue = _appeler(outils, "m8_lire_tendances", metric_id="m8_sql_libre", maintenant=MAINTENANT.isoformat())
    assert inconnue["ok"] is False and "REJ-ANALYTIQUE-MESURE-INCONNUE" in inconnue["details"]

    fenetre = _appeler(outils, "m8_lire_tendances", metric_id="m8_cash_libre_cad",
                       maintenant=MAINTENANT.isoformat(), fenetre_observations=201)
    assert fenetre["ok"] is False and "REJ-TENDANCES-FENETRE-INVALIDE" in fenetre["details"]

    mauvaise_heure = _appeler(outils, "m8_lire_tendances", metric_id="m8_cash_libre_cad", maintenant="hier")
    assert mauvaise_heure["ok"] is False and "REJ-FRAICHEUR-MAINTENANT-INVALIDE" in mauvaise_heure["details"]

    mauvais_depart = _appeler(
        outils, "m8_lire_tendances", metric_id="m8_cash_libre_cad",
        maintenant=MAINTENANT.isoformat(), depart=-1,
    )
    assert mauvais_depart["ok"] is False


def test_e2e_la_sortie_est_paginee_sous_la_borne_avec_pres_de_trente_points(base):
    registres = jeux_fictifs.registres_fictifs(cash_libre_cad="20000.00")
    cibles = _cibles(registres)
    outils = _outils(cibles)
    for heure, valeur in enumerate(range(20000, 20200, 5)):  # 40 constructions, valeurs distinctes
        registres = jeux_fictifs.registres_fictifs(cash_libre_cad=f"{valeur}.00")
        _synchroniser(cibles, registres)
        _appeler(outils, "m8_construire_entrepot", maintenant=(MAINTENANT + timedelta(hours=heure)).isoformat())

    premiere = _appeler(
        outils, "m8_lire_tendances", metric_id="m8_cash_libre_cad",
        maintenant=(MAINTENANT + timedelta(hours=60)).isoformat(), fenetre_observations=40
    )
    assert premiere["ok"] is True
    resultat = premiere["resultat"]
    assert len(json.dumps(resultat, ensure_ascii=False)) <= m8_outils.BUDGET_SORTIE
    assert resultat["prochain_depart"] is not None
    assert len(resultat["serie"]) < 40
    assert resultat["couverture"]["retenues"] == 40
    assert tendances.verifier_recu(resultat["recu"]) is True

    seconde = _appeler(
        outils, "m8_lire_tendances", metric_id="m8_cash_libre_cad",
        maintenant=(MAINTENANT + timedelta(hours=60)).isoformat(), fenetre_observations=40,
        depart=resultat["prochain_depart"],
    )
    assert seconde["ok"] is True and seconde["resultat"]["serie"]
    assert seconde["resultat"]["serie"][0]["construction_id"] != resultat["serie"][0]["construction_id"]


# ---------------------------------------------------------------------------
# Futur : une observation postérieure à maintenant ne nourrit pas les calculs
# ---------------------------------------------------------------------------
def test_e2e_une_observation_future_n_entre_pas_dans_les_calculs_et_est_comptee(base):
    """Reproduit le défaut signalé : 10 à 11Z et 12 à 13Z, maintenant 12Z.

    Avant correction, la variation vaut +2 et la moyenne 11, alors que la dernière construction est
    postérieure à l'instant de lecture. Après correction, seule l'observation de 11Z est retenue ; la
    future est comptée distinctement et le reçu porte la série réellement utilisée.
    """
    registres = jeux_fictifs.registres_fictifs(cash_libre_cad="10.00")
    cibles = _cibles(registres)
    outils = _outils(cibles)
    for heures, valeur in ((11, "10.00"), (13, "12.00")):
        registres = jeux_fictifs.registres_fictifs(cash_libre_cad=valeur)
        _synchroniser(cibles, registres)
        construit = _appeler(outils, "m8_construire_entrepot", maintenant=_instant(heures))
        assert construit["ok"] is True and construit["resultat"]["statut"] == "construit"

    resultat = _tendances_completes(
        outils,
        metric_id="m8_cash_libre_cad",
        maintenant=_instant(12),
        fenetre_observations=3,
        fenetre_moyenne_mobile=3,
        horizon_prevision=1,
    )
    print(
        "avant/apres futur:",
        json.dumps(
            {
                "valeurs": [point["valeur"] for point in resultat["serie"]],
                "variation": resultat["variation"]["absolue"],
                "moyenne": resultat["moyenne_mobile"],
                "fraicheur": resultat["couverture"]["fraicheur"],
                "couverture": resultat["couverture"],
            },
            ensure_ascii=False,
            default=str,
        ),
    )
    assert [point["valeur"] for point in resultat["serie"]] == ["10.00"]
    assert resultat["couverture"]["futurs_ecartes"] == 1
    assert resultat["couverture"]["retenues"] == 1
    assert resultat["variation"]["absolue"]["statut"] == "non_calculable"
    assert resultat["moyenne_mobile"]["statut"] == "non_evaluee"
    assert resultat["couverture"]["fraicheur"]["construction_dans_le_futur"] is False
    assert tendances.verifier_recu(resultat["recu"]) is True
    assert resultat["recu"]["n_points"] == 1
    assert resultat["recu"]["futures_ecartees"] == 1


def _ligne_a(construction: str, construit_le: str, valeur: str = "10.00") -> dict:
    """Une ligne dont l'instant RFC 3339 est donné tel quel (offsets, fractions, changement d'heure)."""
    return {**_ligne(1, valeur, 0, construction=construction), "construit_le": construit_le}


def test_deux_instants_passes_distincts_a_la_nanoseconde_ne_sont_pas_ambigus():
    resultat = _analyse(
        [
            _ligne_a("a-dernier", "2026-10-30T12:00:00.000000002Z", "20.00"),
            _ligne_a("z-premier", "2026-10-30T12:00:00.000000001Z", "10.00"),
        ],
        maintenant=datetime(2026, 10, 31, tzinfo=UTC),
        fenetre_observations=2,
    )
    assert resultat["exclusions"]["instant_ambigu"] == 0
    assert [point["valeur"] for point in resultat["serie"]] == ["10.00", "20.00"]
    assert resultat["couverture"]["etendue_s"] == "0.000000001"
    assert resultat["couverture"]["intervalles"] == {
        "n": 1, "min_s": "0.000000001", "max_s": "0.000000001", "tous_egaux": True,
    }


def test_etendue_temporelle_traverse_jour_heure_minute_seconde_et_nanoseconde():
    resultat = _analyse(
        [
            _ligne_a("avant", "2026-10-28T09:08:07.023456789Z", "10.00"),
            _ligne_a("apres", "2026-10-29T14:13:14.123456791Z", "20.00"),
        ],
        maintenant=datetime(2026, 10, 31, tzinfo=UTC),
        fenetre_observations=2,
    )
    assert [point["valeur"] for point in resultat["serie"]] == ["10.00", "20.00"]
    assert resultat["couverture"]["etendue_s"] == "104707.100000002"
    assert resultat["couverture"]["intervalles"]["min_s"] == "104707.100000002"


def test_les_bornes_de_maintenant_sont_strictes_et_la_nanoseconde_est_honoree():
    maintenant = datetime(2026, 10, 30, 12, 0, 0, 0, tzinfo=UTC)
    resultat = _analyse(
        [
            _ligne_a("avant", "2026-10-30T11:59:59.999999999Z", "1.00"),
            _ligne_a("egal", "2026-10-30T12:00:00.000000000Z", "2.00"),
            _ligne_a("ns", "2026-10-30T12:00:00.000000001Z", "3.00"),
            _ligne_a("us", "2026-10-30T12:00:00.000001000Z", "4.00"),
        ],
        maintenant=maintenant,
        fenetre_observations=10,
    )
    assert [point["valeur"] for point in resultat["serie"]] == ["1.00", "2.00"]
    assert resultat["couverture"]["futurs_ecartes"] == 2


def test_les_offsets_opposes_et_le_changement_d_heure_ne_faussent_pas_la_borne_de_maintenant():
    # 2026-11-01 : fin de l'heure d'été au Québec. 01:30-04:00 = 05:30Z (égal) ; 01:15-05:00 = 06:15Z (futur).
    maintenant = datetime(2026, 11, 1, 1, 30, tzinfo=timezone(timedelta(hours=-4)))
    resultat = _analyse(
        [
            _ligne_a("egal-dst", "2026-11-01T01:30:00-04:00", "10.00"),
            _ligne_a("futur-dst", "2026-11-01T01:15:00-05:00", "12.00"),
            _ligne_a("futur-offset", "2026-11-01T07:30:00+01:00", "14.00"),
        ],
        maintenant=maintenant,
        fenetre_observations=10,
    )
    assert [point["valeur"] for point in resultat["serie"]] == ["10.00"]
    assert resultat["couverture"]["futurs_ecartes"] == 2


def test_une_serie_entierement_future_ne_produit_aucune_valeur_et_dit_la_couverture():
    maintenant = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
    resultat = _analyse(
        [
            _ligne_a("f1", "2026-10-30T13:00:00Z", "10.00"),
            _ligne_a("f2", "2026-10-30T14:00:00Z", "12.00"),
        ],
        maintenant=maintenant,
        fenetre_observations=10,
        limite_lecture=2,
    )
    assert resultat["serie"] == []
    assert resultat["couverture"]["futurs_ecartes"] == 2
    assert resultat["couverture"]["lecture_bornee"] is True
    assert resultat["couverture"]["anterieures_non_lues_possibles"] is True
    assert "postérieure" in resultat["couverture"]["fraicheur"]["motif"]
    for cle in ("variation", "variation_derniere"):
        assert resultat[cle]["absolue"]["statut"] == "non_calculable"
        assert resultat[cle]["relative_pct"]["statut"] == "non_calculable"
    assert resultat["moyenne_mobile"]["statut"] == "non_evaluee"
    assert resultat["xmr"]["statut"] == "non_evalue"
    assert resultat["prevision"]["statut"] == "non_evaluee"
    assert resultat["recu"]["n_points"] == 0
    assert resultat["recu"]["futures_ecartees"] == 2
    assert tendances.verifier_recu(resultat["recu"]) is True


def test_la_fenetre_se_remplit_apres_exclusion_des_futurs_et_compte_les_anciens():
    maintenant = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
    resultat = _analyse(
        [
            _ligne_a("p1", "2026-10-30T09:00:00Z", "1.00"),
            _ligne_a("p2", "2026-10-30T10:00:00Z", "2.00"),
            _ligne_a("p3", "2026-10-30T11:00:00Z", "3.00"),
            _ligne_a("f1", "2026-10-30T13:00:00Z", "4.00"),
            _ligne_a("f2", "2026-10-30T14:00:00Z", "5.00"),
        ],
        maintenant=maintenant,
        fenetre_observations=2,
    )
    assert [point["valeur"] for point in resultat["serie"]] == ["2.00", "3.00"]
    assert resultat["couverture"]["futurs_ecartes"] == 2
    assert resultat["couverture"]["hors_fenetre"] == 1
    assert resultat["variation"]["absolue"]["valeur"] == "1.00"
    assert resultat["moyenne_mobile"]["valeur"] == "2.50"
    assert resultat["recu"]["n_points"] == 2


def test_xmr_moyenne_et_prevision_ignorent_la_construction_future():
    valeurs = ["10.00", "12.00", "13.00", "17.00", "16.00", "19.00", "21.00", "22.00"]
    lignes = [_ligne(rang, valeur, rang - 1) for rang, valeur in enumerate(valeurs, start=1)]
    lignes.append(_ligne(9, "999.00", 8))
    resultat = _analyse(
        lignes,
        maintenant=datetime(2026, 10, 30, 7, 30, tzinfo=UTC),
        fenetre_moyenne_mobile=3,
        horizon_prevision=1,
    )
    assert resultat["couverture"]["futurs_ecartes"] == 1
    assert resultat["couverture"]["retenues"] == 8
    assert resultat["moyenne_mobile"]["valeur"] == "20.67"  # (19 + 21 + 22) / 3
    assert resultat["xmr"]["n"] == 8
    assert resultat["xmr"]["centre"] == "16.25"
    assert resultat["prevision"]["valeur_prevue"] == "24.07"


def test_le_recu_porte_le_nombre_de_futurs_ecartes_et_se_falsifie_si_on_le_change():
    maintenant = datetime(2026, 10, 30, 12, 0, tzinfo=UTC)
    resultat = _analyse(
        [
            _ligne_a("p1", "2026-10-30T11:00:00Z", "10.00"),
            _ligne_a("f1", "2026-10-30T13:00:00Z", "12.00"),
        ],
        maintenant=maintenant,
    )
    assert resultat["recu"]["futures_ecartees"] == 1
    assert resultat["recu"]["n_points"] == 1
    falsifie = dict(resultat["recu"])
    falsifie["futures_ecartees"] = 0
    assert tendances.verifier_recu(falsifie) is False


@pytest.mark.parametrize("limite", [0, 1001, True])
def test_une_limite_de_lecture_invalide_est_refusee(limite):
    with pytest.raises(ValueError, match="REJ-TENDANCES-LIMITE-LECTURE-INVALIDE"):
        _analyse([], limite_lecture=limite)


def test_e2e_la_borne_de_lecture_saturee_par_le_futur_est_dite_sans_recuperation(base):
    """51 lignes : 1 passée et 50 futures. La borne de lecture (50) ne rend que les futures ; la réponse ne
    prétend pas récupérer la passée, elle dit que des observations antérieures peuvent ne pas avoir été lues."""
    registres = jeux_fictifs.registres_fictifs(cash_libre_cad="20000.00")
    cibles = _cibles(registres)
    outils = _outils(cibles)
    _synchroniser(cibles, registres)
    assert _appeler(outils, "m8_construire_entrepot", maintenant=_instant(10))["ok"] is True
    debut = datetime(2026, 10, 30, 12, 0, 1, tzinfo=UTC)
    for i in range(50):
        registres = jeux_fictifs.registres_fictifs(cash_libre_cad=f"{20001 + i}.00")
        _synchroniser(cibles, registres)
        construit = _appeler(outils, "m8_construire_entrepot", maintenant=(debut + timedelta(seconds=i)).isoformat())
        assert construit["ok"] is True and construit["resultat"]["statut"] == "construit"

    resultat = _tendances_completes(
        outils,
        metric_id="m8_cash_libre_cad",
        maintenant=_instant(12),
        fenetre_observations=2,
    )
    assert resultat["serie"] == []
    assert resultat["couverture"]["lues"] == 50
    assert resultat["couverture"]["retenues"] == 0
    assert resultat["couverture"]["futurs_ecartes"] == 50
    assert resultat["couverture"]["limite_lecture"] == 50
    assert resultat["couverture"]["lecture_bornee"] is True
    assert resultat["couverture"]["anterieures_non_lues_possibles"] is True
    assert "postérieure" in resultat["couverture"]["fraicheur"]["motif"]
    assert resultat["variation"]["absolue"]["statut"] == "non_calculable"
    assert resultat["moyenne_mobile"]["statut"] == "non_evaluee"
    assert resultat["recu"]["n_points"] == 0
    assert resultat["recu"]["futures_ecartees"] == 50
    assert tendances.verifier_recu(resultat["recu"]) is True



@pytest.mark.parametrize("limite", [1, 1000])
def test_une_limite_de_lecture_aux_bornes_est_acceptee(limite):
    resultat = _analyse(
        [_ligne_a("p1", "2026-10-30T11:00:00Z", "10.00")],
        maintenant=datetime(2026, 10, 30, 12, 0, tzinfo=UTC),
        limite_lecture=limite,
    )
    assert resultat["couverture"]["limite_lecture"] == limite
    assert resultat["couverture"]["lecture_bornee"] is (limite == 1)
    # Aucun futur : la borne atteinte ne permet pas de conclure qu'une observation antérieure manque.
    assert resultat["couverture"]["anterieures_non_lues_possibles"] is False


def test_une_lecture_bornee_sans_futur_ne_declare_pas_d_anterieures_non_lues():
    resultat = _analyse(
        [_ligne_a("p1", "2026-10-30T10:00:00Z", "10.00"), _ligne_a("p2", "2026-10-30T11:00:00Z", "12.00")],
        maintenant=datetime(2026, 10, 30, 12, 0, tzinfo=UTC),
        limite_lecture=2,
    )
    assert resultat["couverture"]["futurs_ecartes"] == 0
    assert resultat["couverture"]["lecture_bornee"] is True
    assert resultat["couverture"]["anterieures_non_lues_possibles"] is False


def test_maintenant_a_la_nanoseconde_est_une_borne_exacte_et_le_recu_la_porte():
    maintenant = datetime(2026, 10, 30, 12, 0, 0, 0, tzinfo=UTC)
    cle = "2026-10-30T12:00:00.000000001Z"
    resultat = _analyse(
        [
            _ligne_a("egal-ns", "2026-10-30T12:00:00.000000001Z", "10.00"),
            _ligne_a("futur-ns", "2026-10-30T12:00:00.000000002Z", "12.00"),
        ],
        maintenant=maintenant,
        maintenant_cle=cle,
        fenetre_observations=10,
    )
    assert [point["valeur"] for point in resultat["serie"]] == ["10.00"]
    assert resultat["couverture"]["futurs_ecartes"] == 1
    assert resultat["recu"]["maintenant_cle"] == cle
    assert tendances.verifier_recu(resultat["recu"]) is True


@pytest.mark.parametrize(
    "instant",
    [
        datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=1))),
        datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone(-timedelta(hours=1))),
    ],
)
def test_maintenant_hors_plage_utc_est_refuse_nommement(instant):
    with pytest.raises(ValueError, match="REJ-TENDANCES-MAINTENANT-INVALIDE"):
        _analyse([], maintenant=instant)


def test_une_cle_de_maintenant_invalide_est_refusee():
    with pytest.raises(ValueError, match="REJ-TENDANCES-MAINTENANT-INVALIDE"):
        _analyse(
            [],
            maintenant=datetime(2026, 10, 30, 12, 0, tzinfo=UTC),
            maintenant_cle="pas une cle",
        )


def test_une_cle_de_maintenant_coherente_a_la_microseconde_est_requise():
    with pytest.raises(ValueError, match="REJ-TENDANCES-MAINTENANT-INVALIDE"):
        _analyse(
            [],
            maintenant=datetime(2026, 10, 30, 12, 0, tzinfo=UTC),
            maintenant_cle="2026-10-30T12:00:01.000000000Z",
        )


def test_e2e_l_outil_public_conserve_deux_constructions_distinctes_a_la_nanoseconde(base):
    registres = jeux_fictifs.registres_fictifs(cash_libre_cad="10.00")
    cibles = _cibles(registres)
    outils = _outils(cibles)
    for instant, valeur in (
        ("2026-10-30T12:00:00.000000002+00:00", "20.00"),
        ("2026-10-30T12:00:00.000000001+00:00", "10.00"),
    ):
        registres = jeux_fictifs.registres_fictifs(cash_libre_cad=valeur)
        _synchroniser(cibles, registres)
        assert _appeler(outils, "m8_construire_entrepot", maintenant=instant)["ok"] is True
    resultat = _tendances_completes(
        outils,
        metric_id="m8_cash_libre_cad",
        maintenant="2026-10-30T12:00:01+00:00",
        fenetre_observations=10,
    )
    assert resultat["exclusions"]["instant_ambigu"] == 0
    assert [point["valeur"] for point in resultat["serie"]] == ["10.00", "20.00"]
    assert resultat["couverture"]["etendue_s"] == "0.000000001"
    assert resultat["couverture"]["intervalles"]["min_s"] == "0.000000001"


@pytest.mark.parametrize(
    "maintenant",
    [
        "0001-01-01T00:00:00+01:00",
        "9999-12-31T23:59:59-01:00",
    ],
)
def test_e2e_l_outil_refuse_nommement_une_borne_hors_plage_utc(base, maintenant):
    registres = jeux_fictifs.registres_fictifs()
    outils = _outils(_cibles(registres))
    resultat = _appeler(outils, "m8_lire_tendances", metric_id="m8_cash_libre_cad", maintenant=maintenant)
    assert resultat["ok"] is False
    assert "REJ-TENDANCES-MAINTENANT-INVALIDE" in resultat["details"]


def test_e2e_l_outil_refuse_maintenant_au_dela_de_la_nanoseconde(base):
    outils = _outils(_cibles(jeux_fictifs.registres_fictifs()))
    resultat = _appeler(
        outils,
        "m8_lire_tendances",
        metric_id="m8_cash_libre_cad",
        maintenant="2026-10-30T12:00:00.1234567891+00:00",
    )
    assert resultat["ok"] is False
    assert "REJ-TENDANCES-MAINTENANT-INVALIDE" in resultat["details"]


def test_copilote_public_exclut_futur_et_isole_une_autre_metrique_non_normalisee(base):
    registres = jeux_fictifs.registres_fictifs(leads=20)
    cibles = _cibles(registres)
    outils = _outils(cibles)
    for heure, valeur in ((11, 20), (11.5, 21), (13, 99)):
        registres = jeux_fictifs.registres_fictifs(leads=valeur)
        _synchroniser(cibles, registres)
        instant = "2026-10-30T11:30:00Z" if heure == 11.5 else f"2026-10-30T{heure:02d}:00:00Z"
        assert _appeler(outils, "m8_construire_entrepot", maintenant=instant)["ok"] is True

    registres = jeux_fictifs.registres_fictifs(leads=21)
    _synchroniser(cibles, registres)
    reponse = _appeler(
        outils, "m8_repondre_question", question="Évolution des leads reçus", maintenant="2026-10-30T12:00:00Z"
    )
    assert reponse["ok"] is True
    assert "99" not in reponse["resultat"]["chiffres"]
    assert "(99)" not in reponse["resultat"]["texte"]
    assert any(valeur in reponse["resultat"]["chiffres"] for valeur in ("21", "21.00"))

    with stockage.transaction() as cnx:
        cnx.execute(
            M8_ENT_MESURES_HIST.update()
            .where(M8_ENT_MESURES_HIST.c.metric_id == "m8_cash_libre_cad")
            .values(construit_le_utc=None)
        )
    reponse = _appeler(
        outils, "m8_repondre_question", question="Combien de leads reçus ?", maintenant="2026-10-30T12:00:00Z"
    )
    assert reponse["ok"] is True


def test_pont_bi_pagine_l_historique_en_ordre_utc_sans_exposer_la_cle(base):
    from m8_analytics import entonnoir

    from opsys.pont_bi import jeux, service

    cibles = _cibles(jeux_fictifs.registres_fictifs(leads=20))
    outils = _outils(cibles)
    for instant, valeur in (
        ("2026-11-01T01:30:00-04:00", 20),
        ("2026-11-01T01:15:00-05:00", 21),
        ("2026-11-01T01:30:00-04:00", 22),
    ):
        _synchroniser(cibles, jeux_fictifs.registres_fictifs(leads=valeur))
        assert _appeler(outils, "m8_construire_entrepot", maintenant=instant)["ok"] is True

    lignes = []
    with stockage.transaction() as cnx:
        depart = 0
        while True:
            _, page, total = service.lire_jeu(
                cnx, jeux.JEUX["mesures_historique"], financier=True, limite=11, depart=depart,
                selection=["construction_id", "metric_id", "construit_le"],
            )
            lignes.extend(page)
            depart += len(page)
            if depart >= total:
                break
            assert page
    assert len(lignes) == total > 11
    assert all("construit_le_utc" not in ligne for ligne in lignes)
    cles = [
        (entonnoir.instant_utc(ligne["construit_le"]), ligne["construction_id"], ligne["metric_id"])
        for ligne in lignes
    ]
    assert cles == sorted(cles)
    assert len(set(cles)) == len(cles)
    assert {cle[0] for cle in cles} == {"2026-11-01T05:30:00.000000000Z", "2026-11-01T06:15:00.000000000Z"}


def test_copilote_exclut_historique_futur_et_definition_perimee():
    ligne = {"nom": "Mesure fictive", "qualite_en_echec": False, "version_definition": VERSION, "a_jour": True}
    historique = [
        {
            "construit_le": "2026-10-30T13:00:00+00:00", "construit_le_utc": "2026-10-30T13:00:00.000000000Z",
            "valeur": "999", "version_definition": VERSION, "statut": "calculee",
        },
        {
            "construit_le": "2026-10-30T11:00:00+00:00", "construit_le_utc": "2026-10-30T11:00:00.000000000Z",
            "valeur": "100", "version_definition": "b" * 64, "statut": "calculee",
        },
        {
            "construit_le": "2026-10-30T10:00:00+00:00", "construit_le_utc": "2026-10-30T10:00:00.000000000Z",
            "valeur": "10", "version_definition": VERSION, "statut": "calculee",
        },
    ]
    texte, chiffres = copilote._phrase_tendance(ligne, historique, "2026-10-30T12:00:00.000000000Z")
    assert "10" in texte and "999" not in texte and "100" not in texte
    assert chiffres == ["10"]


def test_e2e_l_outil_public_utilise_la_borne_a_la_nanoseconde(base):
    registres = jeux_fictifs.registres_fictifs(cash_libre_cad="10.00")
    cibles = _cibles(registres)
    outils = _outils(cibles)
    for instant, valeur in (
        ("2026-10-30T12:00:00.000000001+00:00", "10.00"),
        ("2026-10-30T12:00:00.000000002+00:00", "12.00"),
    ):
        registres = jeux_fictifs.registres_fictifs(cash_libre_cad=valeur)
        _synchroniser(cibles, registres)
        assert _appeler(outils, "m8_construire_entrepot", maintenant=instant)["ok"] is True
    resultat = _tendances_completes(
        outils,
        metric_id="m8_cash_libre_cad",
        maintenant="2026-10-30T12:00:00.000000001+00:00",
        fenetre_observations=10,
    )
    assert [point["valeur"] for point in resultat["serie"]] == ["10.00"]
    assert resultat["couverture"]["futurs_ecartes"] == 1
    assert resultat["recu"]["maintenant_cle"] == "2026-10-30T12:00:00.000000001Z"
    assert resultat["couverture"]["fraicheur"]["age_construction_s"] == 0
    assert resultat["couverture"]["fraicheur"]["construction_dans_le_futur"] is False
    assert tendances.verifier_recu(resultat["recu"]) is True
