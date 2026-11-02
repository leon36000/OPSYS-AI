"""Plan de croissance organique dérivé des observations : formats gagnants, créneaux, séries ; sinon ce qui manque."""

from __future__ import annotations

import pytest
from m7_marketing import growth
from m7_marketing.rapport_hebdo import croissance

FICTIF = True


def obs(oid, plateforme, campagne, valeur, metrique="taux_engagement", unite="pct"):
    return {
        "observation_id": oid,
        "metrique": metrique,
        "valeur": valeur,
        "unite": unite,
        "plateforme": plateforme,
        "campagne": campagne,
        "periode": {"debut": "2026-10-01", "fin": "2026-10-07"},
    }


def trois(prefixe, plateforme, campagne, valeurs, **kw):
    return [obs(f"{prefixe}-{i}", plateforme, campagne, v, **kw) for i, v in enumerate(valeurs)]


def test_un_format_gagnant_net_devient_une_action_organique_sourcee():
    donnees = trois("r", "facebook", "format:reel", [6, 7, 8]) + trois("p", "facebook", "format:photo", [3, 4, 2])
    sortie = croissance.analyser(donnees)
    assert sortie["manques"] == []
    (action,) = sortie["actions"]
    assert action["gagnant"] == "reel" and action["dimension"] == "format" and action["ecart_pct"] == 133
    assert "format « reel »" in action["action"] and "7.00 pct contre 3.00 pct" in action["action"]
    assert action["observations_source"] == ["r-0", "r-1", "r-2", "p-0", "p-1", "p-2"]  # gagnant puis suivant
    assert "causalité" in action["hypotheses"][0]
    assert croissance.verifier_legitimite(action["action"])


def test_creneaux_et_series_ont_leur_propre_formulation():
    donnees = (
        trois("a", "instagram", "creneau:mardi-19h", [5, 5, 5])
        + trois("b", "instagram", "creneau:samedi-10h", [2, 2, 2])
        + trois("c", "facebook", "serie:avant-apres", [9, 9, 9], metrique="portee", unite="personnes")
        + trois("d", "facebook", "serie:equipe", [4, 4, 4], metrique="portee", unite="personnes")
    )
    textes = {a["dimension"]: a["action"] for a in croissance.analyser(donnees)["actions"]}
    assert "créneau « mardi-19h »" in textes["creneau"] and "série « avant-apres »" in textes["serie"]


def test_pas_assez_d_observations_par_etiquette_dit_exactement_ce_qui_manque():
    donnees = trois("r", "facebook", "format:reel", [6, 7, 8]) + trois("p", "facebook", "format:photo", [3, 4])[:2]
    sortie = croissance.analyser(donnees)
    assert sortie["actions"] == []
    (manque,) = sortie["manques"]
    assert "« photo » 2/3" in manque and "« reel » 3/3" in manque and "saisir les observations manquantes" in manque


def test_ecart_trop_faible_ne_donne_pas_de_gagnant():
    donnees = trois("r", "facebook", "format:reel", [10, 10, 10]) + trois("p", "facebook", "format:photo", [9, 9, 9])
    sortie = croissance.analyser(donnees)
    assert sortie["actions"] == [] and "pas de gagnant net" in sortie["manques"][0]


def test_des_observations_sans_etiquette_disent_comment_les_etiqueter():
    sortie = croissance.analyser([obs("x", "facebook", "campagne-quelconque", 5)])
    assert sortie["actions"] == [] and "aucune observation étiquetée" in sortie["manques"][0]


def test_pas_d_observation_du_tout_ne_produit_ni_action_ni_faux_manque():
    assert croissance.analyser([]) == {"actions": [], "manques": []}


def test_une_metrique_inconnue_ou_une_valeur_non_finie_ne_classe_rien():
    donnees = trois("r", "facebook", "format:reel", [6, 7, 8], metrique="metrique_maison") + trois(
        "p", "facebook", "format:photo", [3, 4, float("nan")]
    )
    assert croissance.analyser(donnees)["actions"] == []


def test_un_libelle_piege_dans_la_campagne_n_entre_jamais_dans_une_action():
    piege = "format:acheter des abonnes"  # libellé 'sûr' mais contenant une tactique interdite
    donnees = trois("r", "facebook", piege, [9, 9, 9]) + trois("p", "facebook", "format:photo", [3, 3, 3])
    sortie = croissance.analyser(donnees)
    assert all(croissance.verifier_legitimite(a["action"]) for a in sortie["actions"])
    assert sortie["actions"] == [] and any("garde de légitimité" in m for m in sortie["manques"])
    assert croissance.etiquette("format:<script>alert(1)</script>") is None
    assert croissance.etiquette("format:" + "x" * 41) is None
    assert croissance.etiquette("reel") is None


@pytest.mark.parametrize(
    "texte",
    [
        "Acheter des abonnés pour grandir",
        "Faux likes sur les publications",
        "Organiser un pod d'engagement",
        "Envoyer un DM massif aux entreprises",
        "Utiliser un bot pour commenter",
        "faire du SPAM ciblé",
        "Contourner les limites de l'API",
        "ACHAT D'ABONNÉS rapide",
    ],
)
def test_la_garde_de_legitimite_refuse_les_tactiques_interdites(texte):
    assert croissance.verifier_legitimite(texte) is False


def test_la_garde_de_legitimite_laisse_passer_les_actions_organiques():
    assert croissance.verifier_legitimite("Publier de préférence le mardi, répondre aux commentaires, demander un avis")
    assert croissance.verifier_legitimite("Le robot de cuisine de la photo")  # « bot » seulement comme mot entier


def test_deux_etiquettes_ex_aequo_a_zero_ne_donnent_pas_de_gagnant():
    donnees = trois("r", "facebook", "format:reel", [0, 0, 0]) + trois("p", "facebook", "format:photo", [0, 0, 0])
    assert croissance.analyser(donnees)["actions"] == []


def test_etiquette_gagnante_a_zero_contre_zero_et_positif_est_net():
    donnees = trois("r", "facebook", "format:reel", [4, 4, 4]) + trois("p", "facebook", "format:photo", [0, 0, 0])
    (action,) = croissance.analyser(donnees)["actions"]
    assert action["gagnant"] == "reel" and action["ecart_pct"] is None


def test_le_resultat_ne_depend_pas_de_l_ordre_des_observations():
    donnees = trois("r", "facebook", "format:reel", [6, 7, 8]) + trois("p", "facebook", "format:photo", [3, 4, 2])
    a = croissance.analyser(donnees)
    donnees.reverse()
    assert croissance.analyser(donnees) == a


# -- le plan à 30 jours (growth.plan_30j) n'est plus « poursuivre la mesure » ----------------------------------------
@pytest.fixture
def base_growth(tmp_path, monkeypatch):
    from opsys import stockage

    url = f"sqlite:///{tmp_path / 'g.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home"))
    stockage.migrer(url)
    yield
    stockage.liberer()


def enregistrer(o):
    return growth.enregistrer_observation(
        o["observation_id"],
        o["metrique"],
        o["valeur"],
        o["unite"],
        o["periode"]["debut"],
        o["periode"]["fin"],
        o["plateforme"],
        o["campagne"],
        "export manuel fictif",
        "preuve-fictive",
        0.8,
    )


def test_le_plan_30_jours_derive_ses_actions_des_donnees_ou_dit_ce_qui_manque(base_growth):
    from opsys import stockage

    with stockage.transaction():
        vide = growth.plan_30j("2026-11-01")
    assert vide["recommandations"] == [] and vide["donnees_manquantes"] == ["observations sourcées de performance"]
    with stockage.transaction():
        enregistrer(obs("solo", "facebook", "campagne-x", 5))
        un = growth.plan_30j("2026-11-01")
    assert "poursuivre la mesure" not in str(un)
    assert un["recommandations"][0]["action"].startswith("aucune action organique dérivée")
    assert un["donnees_manquantes"] and "aucune observation étiquetée" in un["donnees_manquantes"][0]
    with stockage.transaction():
        for o in trois("r", "facebook", "format:reel", [6, 7, 8]) + trois("p", "facebook", "format:photo", [3, 4, 2]):
            enregistrer(o)
        riche = growth.plan_30j("2026-11-01")
    actions = [r for r in riche["recommandations"] if r["action"].startswith("Sur facebook")]
    assert len(actions) == 1 and "organique" in actions[0]["action"] and actions[0]["donnees_manquantes"] == []
    assert "poursuivre la mesure" not in str(riche)
    assert set(riche) == {"statut", "type", "horizon_debut", "recommandations", "donnees_manquantes", "limites"}
