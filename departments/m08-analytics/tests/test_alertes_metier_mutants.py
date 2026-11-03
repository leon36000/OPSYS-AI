"""Tests tueurs de mutants pour ``alertes_metier.py`` : bornes des règles, du registre et des compteurs.

Données fictives, déterministes. Les bornes sont testées à la valeur exacte et juste au-delà (nombre de règles, de
mesures liées, texte, fenêtre de 24 h, comptes d'états).
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from m8_analytics import alertes_metier, catalogue_mesures

CATALOGUE = catalogue_mesures.charger()
ENTREES = catalogue_mesures.par_identifiant(CATALOGUE)
ACTIONS = {"a": "{mesure} de {departement}"}
MAINTENANT = dt.datetime(2026, 11, 12, 20, 0, tzinfo=dt.UTC).isoformat()
M8 = sorted(ENTREES)


def _regle_peremption(identifiant: str = "ALERTE-TEST-1", mesures: list | None = None, **surcharges) -> dict:
    base = {
        "id": identifiant,
        "genre": "peremption",
        "gravite": "attention",
        "action": "a",
        "libelle": "Une règle de test.",
        "mesures": ["m8_cash_libre_cad"] if mesures is None else mesures,
    }
    base.update(surcharges)
    return base


def _brut(regles: list[dict], actions: dict | None = None) -> dict:
    return {"schema": alertes_metier.SCHEMA, "version": 1, "actions": actions or dict(ACTIONS), "regles": regles}


def _mesure() -> dict:
    return {"metric_id": "m8_x", "nom": "Mesure fictive", "unite": "u", "proprietaire": "m08-test", "source": "test"}


def _verdict(etat: str = "franchi") -> dict:
    return {"regle": "ALERTE-TEST-1", "metric_id": "m8_x", "etat": etat}


def _regles() -> dict:
    return {
        "version": 1,
        "actions": dict(ACTIONS),
        "regles": [
            {
                "id": "ALERTE-TEST-1",
                "genre": "qualite",
                "gravite": "attention",
                "action": "a",
                "libelle": "Une règle de test.",
            }
        ],
    }


def _registre_ouvertures(ages_heures: list[float]) -> list[dict]:
    return [
        {
            "type_entree": alertes_metier.TYPE_OUVERTE,
            "alerte_id": f"ALERTE-VIEUX:m8_v{rang}:1",
            "regle": "ALERTE-VIEUX",
            "metric_id": f"m8_v{rang}",
            "episode": 1,
            "ouverte_le": (dt.datetime.fromisoformat(MAINTENANT) - dt.timedelta(hours=age)).isoformat(),
            "gravite": "attention",
        }
        for rang, age in enumerate(ages_heures)
    ]


# ================================================================ bornes du fichier de règles
def test_le_plafond_de_regles_est_de_soixante_inclus():
    regles = [_regle_peremption(f"ALERTE-RANG-{rang}", [M8[rang]]) for rang in range(59)]
    regles.append(_regle_peremption("ALERTE-PAIRE-1", M8[:2]))
    regles.append({
        "id": "ALERTE-QUALITE-1", "genre": "qualite", "gravite": "attention", "action": "a", "libelle": "Qualité.",
    })
    assert len(alertes_metier.valider(_brut(regles[:60]), CATALOGUE)["regles"]) == 60

    with pytest.raises(alertes_metier.AlertesRefusees, match="1 à 60"):
        alertes_metier.valider(_brut(regles[:61]), CATALOGUE)


def test_une_seule_regle_est_un_fichier_valide():
    assert len(alertes_metier.valider(_brut([_regle_peremption()]), CATALOGUE)["regles"]) == 1


def test_un_texte_de_six_cents_caracteres_est_accepte_au_plafond_et_un_de_plus_refuse():
    assert len(alertes_metier.valider(
        _brut([_regle_peremption(libelle="x" * 600)]), CATALOGUE)["regles"]) == 1
    with pytest.raises(alertes_metier.AlertesRefusees, match="600"):
        alertes_metier.valider(_brut([_regle_peremption(libelle="x" * 601)]), CATALOGUE)


@pytest.mark.parametrize("libelle", [5, "", " "])
def test_un_libelle_non_chaîne_ou_vide_est_refuse(libelle):
    with pytest.raises(alertes_metier.AlertesRefusees, match="texte"):
        alertes_metier.valider(_brut([_regle_peremption(libelle=libelle)]), CATALOGUE)


def test_au_plus_huit_mesures_liees_sont_acceptees_la_neuvieme_est_refusee():
    regle = _regle_peremption(sens="au_dessus", reglage="seuil_test")
    regle["genre"] = "seuil"
    regle["mesure"] = M8[0]
    regle.pop("mesures")
    regle["mesures_liees"] = M8[1:9]
    assert len(alertes_metier.valider(_brut([regle]), CATALOGUE)["regles"]) == 1

    regle["mesures_liees"] = M8[1:10]
    with pytest.raises(alertes_metier.AlertesRefusees, match="au plus 8 mesures"):
        alertes_metier.valider(_brut([regle]), CATALOGUE)


@pytest.mark.parametrize("mesures", [5, []])
def test_une_liste_de_mesures_non_liste_ou_vide_est_refusee(mesures):
    with pytest.raises(alertes_metier.AlertesRefusees, match="liste non vide"):
        alertes_metier.valider(_brut([_regle_peremption(mesures=mesures)]), CATALOGUE)


def test_une_mesure_nommee_deux_fois_est_refusee_comme_doublon():
    with pytest.raises(alertes_metier.AlertesRefusees, match="sans doublon"):
        alertes_metier.valider(_brut([_regle_peremption(mesures=[M8[0], M8[0]])]), CATALOGUE)


def test_une_regle_de_seuil_valide_charge_et_ne_perd_pas_sa_mesure():
    regle = _regle_peremption(sens="au_dessus", reglage="seuil_test")
    regle["genre"] = "seuil"
    regle["mesure"] = M8[0]
    regle.pop("mesures")
    chargee = alertes_metier.valider(_brut([regle]), CATALOGUE)["regles"][0]
    assert chargee["mesure"] == M8[0]


# ================================================================ bornes du registre et des compteurs
def test_trente_ouvertures_dans_les_vingt_quatre_heures_saturent_le_plafond_la_trente_et_unieme_est_bornee():
    registre = _registre_ouvertures([1.0] * 30)
    plan = alertes_metier.planifier(_regles(), [_verdict()], [_mesure()], registre, MAINTENANT)

    assert plan["ouvertures"] == []
    assert plan["bornees"] == 1


def test_une_ouverture_vieille_de_vingt_quatre_heures_et_une_demi_ne_compte_plus_dans_la_fenetre():
    registre = _registre_ouvertures([1.0] * 29 + [24.5])
    plan = alertes_metier.planifier(_regles(), [_verdict()], [_mesure()], registre, MAINTENANT)

    assert len(plan["ouvertures"]) == 1
    assert plan["bornees"] == 0


def test_une_ouverture_vieille_de_pile_vingt_quatre_heures_ne_compte_plus_dans_la_fenetre():
    registre = _registre_ouvertures([1.0] * 29 + [24.0])
    plan = alertes_metier.planifier(_regles(), [_verdict()], [_mesure()], registre, MAINTENANT)

    assert len(plan["ouvertures"]) == 1
    assert plan["bornees"] == 0


def test_un_verdict_sans_ouverture_ni_resolution_est_compte_une_fois():
    plan = alertes_metier.planifier(_regles(), [_verdict("dans_la_cible")], [_mesure()], [], MAINTENANT)

    assert plan["inchangees"] == 1


# ================================================================ épisode, texte et compteurs d'état
def test_le_prochain_episode_ne_regarde_que_le_couple_regle_mesure():
    tous = {
        "a": {"regle": "ALERTE-A", "metric_id": "m8_x", "episode": 5},
        "b": {"regle": "ALERTE-A", "metric_id": "m8_y", "episode": 9},
    }
    assert alertes_metier._prochain_episode(tous, "ALERTE-A", "m8_x") == 6


@pytest.mark.parametrize(
    ("sens", "attendu"),
    [(alertes_metier.nombres.SENS_AU_DESSOUS, "passe sous"), (alertes_metier.nombres.SENS_AU_DESSUS, "dépasse")],
)
def test_le_sens_d_une_regle_de_seuil_est_dit_dans_la_phrase_pas_inverse(sens, attendu):
    regle = {"id": "A", "genre": "seuil", "sens": sens}
    _, pourquoi = alertes_metier._quoi_pourquoi(
        regle, _mesure(), {"valeur": "5", "seuil": Decimal("10")}
    )
    assert attendu in pourquoi


def test_une_regle_de_peremption_dit_perimee_pas_bloquee_par_la_qualite():
    quoi, _ = alertes_metier._quoi_pourquoi({"id": "A", "genre": "peremption"}, _mesure(), {})
    assert "périmée" in quoi and "qualité" not in quoi


def test_l_etat_des_regles_compte_chaque_etat_une_fois_par_verdict():
    regles = {"version": 1, "actions": {}, "regles": [
        {"id": "A", "genre": "peremption", "gravite": "attention", "libelle": "Test."},
    ]}
    verdicts = [
        {"regle": "A", "etat": "franchi", "raison": None},
        {"regle": "A", "etat": "dans_la_cible", "raison": None},
        {"regle": "A", "etat": "non_evaluee", "raison": "mesure_perimee"},
    ]
    ligne = alertes_metier.etat_des_regles(regles, verdicts, {})[0]

    assert ligne["franchies"] == 1
    assert ligne["dans_la_cible"] == 1
    assert ligne["non_evaluees"] == 1
    assert ligne["raisons_non_evaluee"] == ["mesure_perimee"]
