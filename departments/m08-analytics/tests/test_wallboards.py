"""M8.8 — Wallboards : définitions déclaratives validées, évaluées en lecture avec la règle de fraîcheur commune.

Prouve : les deux définitions livrées sont valides et ne nomment que le catalogue fermé ; une définition mal formée est
refusée en entier (clé inconnue, mesure hors catalogue, seuil flottant ou mal ordonné, rythme hors bornes, rôle inconnu,
doublon) ; un wallboard n'affiche JAMAIS une mesure périmée comme à jour (état en toutes lettres, seuil indéterminé,
bannière qui ne dit pas « ok ») ; les seuils se comparent en Decimal aux frontières exactes ; aucune donnée
personnelle ;
le formatage vient du texte exact (pas de flottant).
"""

from __future__ import annotations

import copy
import json

import pytest
import yaml
from m8_analytics import catalogue_mesures, fraicheur_mesures, jeux_fictifs, moteur_mesures, wallboards

FICTIF = True
_CAT = catalogue_mesures.charger()
_MAINTENANT = "2026-10-30T20:00:00-04:00"


def _mesures(maintenant=_MAINTENANT, **registres):
    lues = moteur_mesures.lire(jeux_fictifs.registres_fictifs(**registres), _CAT)
    return fraicheur_mesures.lire_mesures_avec_fraicheur(lues, _CAT, fraicheur_mesures.lire_maintenant(maintenant), {})


def _definition(**surcharges):
    brut = {
        "schema": wallboards.SCHEMA,
        "id": "essai",
        "version": 1,
        "titre": "Essai",
        "roles": ["admin"],
        "rafraichissement": {"intervalle_s": 30, "flux_max": 10},
        "tuiles": [
            {
                "id": "taux",
                "mesure": "m8_taux_acceptation_pct",
                "titre": "Taux",
                "seuils": {"sens": "au_dessous", "attention": "60", "critique": "40"},
            }
        ],
    }
    brut.update(surcharges)
    return brut


def test_les_wallboards_livres_sont_valides_et_ne_nomment_que_le_catalogue():
    definitions = wallboards.charger(_CAT)
    assert set(definitions) == {
        "direction",
        "marketing",
        "finance-operations",
        "acquisition",
        "ventes-clientele",
        "equipes-materiel",
        "collecte",
    }
    connues = {e["metric_id"] for e in _CAT["mesures"]}
    for definition in definitions.values():
        assert {t["mesure"] for t in definition["tuiles"]} <= connues
        assert all(t["seuils"] is None for t in definition["tuiles"])  # aucun seuil inventé à la livraison
        assert definition["rotation"]["actif"] is False and 5 <= definition["intervalle_s"] <= 3600


@pytest.mark.parametrize(
    ("mutation", "fragment"),
    [
        (lambda d: d.update({"inconnue": 1}), "clés inconnues"),
        (lambda d: d.pop("roles"), "manquantes"),
        (lambda d: d.update({"schema": "x"}), "schema"),
        (lambda d: d.update({"id": "Mauvais Id"}), "id :"),
        (lambda d: d.update({"roles": ["employee"]}), "roles"),
        (lambda d: d.update({"roles": []}), "roles"),
        (lambda d: d.update({"rafraichissement": {"intervalle_s": 1, "flux_max": 10}}), "intervalle_s"),
        (lambda d: d.update({"rafraichissement": {"intervalle_s": 30, "flux_max": 0}}), "flux_max"),
        (lambda d: d.update({"rafraichissement": {"intervalle_s": 30, "flux_max": 10, "x": 1}}), "exactement"),
        (lambda d: d.update({"rafraichissement": {"intervalle_s": True, "flux_max": 10}}), "intervalle_s"),
        (lambda d: d.update({"tuiles": []}), "tuiles"),
        (lambda d: d.update({"tuiles": [d["tuiles"][0]] * 2}), "en double"),
        (lambda d: d["tuiles"][0].update({"mesure": "m8_sql_libre"}), "catalogue fermé"),
        (lambda d: d["tuiles"][0].update({"extra": 1}), "chaque tuile"),
        (lambda d: d["tuiles"][0].update({"page": 99}), "page"),
        (
            lambda d: d["tuiles"][0].update({"seuils": {"sens": "au_dessous", "attention": 60, "critique": "40"}}),
            "texte décimal",
        ),
        (
            lambda d: d["tuiles"][0].update({"seuils": {"sens": "au_dessous", "attention": "40", "critique": "60"}}),
            "plus sévère",
        ),
        (
            lambda d: d["tuiles"][0].update({"seuils": {"sens": "au_dessus", "attention": "60", "critique": "40"}}),
            "plus sévère",
        ),
        (lambda d: d["tuiles"][0].update({"seuils": {"sens": "partout", "attention": "1", "critique": "2"}}), "sens"),
        (
            lambda d: d["tuiles"][0].update({"seuils": {"sens": "au_dessus", "attention": "abc", "critique": "2"}}),
            "illisible",
        ),
        (lambda d: d["tuiles"][0].update({"seuils": {"sens": "au_dessus", "attention": "1"}}), "exactement"),
        (lambda d: d.update({"rotation": {"actif": "oui", "intervalle_s": 20}}), "rotation"),
        (lambda d: d.update({"rotation": {"actif": True, "intervalle_s": 1}}), "rotation"),
    ],
)
def test_une_definition_mal_formee_est_refusee(mutation, fragment):
    brut = _definition()
    mutation(brut)
    with pytest.raises(wallboards.WallboardRefuse, match=fragment) as exc:
        wallboards.valider(brut, _CAT)
    assert exc.value.code == wallboards.REJ_WALLBOARD_INVALIDE


def test_trop_de_tuiles_est_refuse():
    tuiles = [{"id": f"t{i}", "mesure": "m8_leads_recus", "titre": "x"} for i in range(17)]
    with pytest.raises(wallboards.WallboardRefuse, match="tuiles"):
        wallboards.valider(_definition(tuiles=tuiles), _CAT)


def test_un_dossier_avec_un_fichier_invalide_refuse_tout_l_ensemble(tmp_path):
    (tmp_path / "bon.v1.yaml").write_text(yaml.safe_dump(_definition(id="bon")), encoding="utf-8")
    (tmp_path / "mauvais.v1.yaml").write_text(yaml.safe_dump(_definition(id="mauvais", roles=["x"])), encoding="utf-8")
    with pytest.raises(wallboards.WallboardRefuse):
        wallboards.charger(_CAT, tmp_path)
    (tmp_path / "mauvais.v1.yaml").write_text(yaml.safe_dump(_definition(id="autre")), encoding="utf-8")
    with pytest.raises(wallboards.WallboardRefuse, match="nom du fichier"):
        wallboards.charger(_CAT, tmp_path)
    vide = tmp_path / "vide"
    vide.mkdir()
    with pytest.raises(wallboards.WallboardRefuse) as exc:
        wallboards.charger(_CAT, vide)
    assert exc.value.code == wallboards.REJ_WALLBOARD_ILLISIBLE


def test_l_empreinte_suit_le_contenu_de_la_definition():
    a = wallboards.valider(_definition(), _CAT)
    assert wallboards.valider(copy.deepcopy(_definition()), _CAT)["empreinte"] == a["empreinte"]
    b = _definition()
    b["tuiles"][0]["seuils"]["critique"] = "35"
    assert wallboards.valider(b, _CAT)["empreinte"] != a["empreinte"]


# ---------------------------------------------------------------------------
# Évaluation : la fraîcheur d'abord
# ---------------------------------------------------------------------------
def test_une_tuile_a_jour_montre_sa_valeur_exacte_et_sa_provenance():
    definition = wallboards.charger(_CAT)["direction"]
    etat = wallboards.evaluer(definition, _mesures(), maintenant=_MAINTENANT)
    tuiles = {t["id"]: t for t in etat["tuiles"]}
    assert tuiles["carnet"]["valeur_affichee"] == "25 000,00 $" and tuiles["carnet"]["a_jour"] is True
    assert tuiles["taux-acceptation"]["valeur_affichee"] == "50,00 %"
    assert tuiles["leads"]["valeur_affichee"] == "20 leads" and tuiles["leads"]["libelle_fraicheur"] == "À jour"
    assert tuiles["leads"]["source"] and tuiles["leads"]["proprietaire"] == "m02-revenue-crm"
    assert etat["donnees_personnelles"] is False and etat["banniere"]["niveau"] == "ok"
    assert tuiles["chantiers"]["fraicheur"] == "non_applicable" and tuiles["chantiers"]["a_jour"] is True


def test_une_mesure_perimee_n_est_jamais_montree_comme_a_jour():
    definition = wallboards.charger(_CAT)["direction"]
    etat = wallboards.evaluer(
        definition, _mesures(maintenant="2026-11-05T09:00:00-04:00"), maintenant="2026-11-05T09:00:00-04:00"
    )
    tuiles = {t["id"]: t for t in etat["tuiles"]}
    for cle in ("leads", "taux-acceptation", "carnet", "cash-libre"):
        assert tuiles[cle]["perimee"] is True and tuiles[cle]["a_jour"] is False
        assert tuiles[cle]["libelle_fraicheur"] == "PÉRIMÉE" and tuiles[cle]["age_affiche"]
    assert etat["banniere"]["niveau"] == "attention" and "ne pas s'y fier" in " ".join(etat["banniere"]["messages"])
    assert set(etat["banniere"]["perimees"]) >= {"leads", "carnet"}


def test_un_seuil_n_est_jamais_evalue_sur_une_valeur_perimee():
    brut = _definition()
    definition = wallboards.valider(brut, _CAT)
    frais = wallboards.evaluer(definition, _mesures(acceptes=2, chantiers=2), maintenant=_MAINTENANT)
    assert frais["tuiles"][0]["valeur"] == "16.67" and frais["tuiles"][0]["etat_seuil"] == "critique"
    assert frais["banniere"]["niveau"] == "critique"
    vieux = wallboards.evaluer(
        definition,
        _mesures(maintenant="2026-12-01T00:00:00-04:00", acceptes=2, chantiers=2),
        maintenant="2026-12-01T00:00:00-04:00",
    )
    assert vieux["tuiles"][0]["etat_seuil"] == "indetermine" and vieux["tuiles"][0]["perimee"] is True
    assert vieux["banniere"]["niveau"] == "attention"  # jamais « critique » fondé sur du périmé, jamais « ok »


@pytest.mark.parametrize(("acceptes", "attendu"), [(6, "normal"), (5, "attention"), (4, "attention"), (3, "critique")])
def test_les_seuils_se_comparent_aux_frontieres_exactes(acceptes, attendu):
    # envoyés 12 : acceptés 6 -> 50 % ; 5 -> 41.67 % ; 4 -> 33.33 % ; 3 -> 25 %. Seuils (au_dessous) : 41.67 et 30.
    brut = _definition()
    brut["tuiles"][0]["seuils"] = {"sens": "au_dessous", "attention": "41.67", "critique": "30"}
    definition = wallboards.valider(brut, _CAT)
    etat = wallboards.evaluer(
        definition, _mesures(acceptes=acceptes, chantiers=min(4, acceptes)), maintenant=_MAINTENANT
    )
    assert etat["tuiles"][0]["etat_seuil"] == attendu


def test_la_frontiere_egale_au_seuil_declenche_et_le_sens_au_dessus_aussi():
    brut = _definition(
        tuiles=[
            {
                "id": "att",
                "mesure": "m8_devis_sans_reponse",
                "titre": "Attente",
                "seuils": {"sens": "au_dessus", "attention": "2", "critique": "5"},
            }
        ]
    )
    definition = wallboards.valider(brut, _CAT)
    for sans_reponse, attendu in ((1, "normal"), (2, "attention"), (4, "attention"), (5, "critique")):
        etat = wallboards.evaluer(definition, _mesures(sans_reponse=sans_reponse), maintenant=_MAINTENANT)
        assert etat["tuiles"][0]["etat_seuil"] == attendu, sans_reponse


def test_une_tuile_sans_seuil_n_a_ni_couleur_ni_alerte():
    definition = wallboards.charger(_CAT)["direction"]
    etat = wallboards.evaluer(definition, _mesures(), maintenant=_MAINTENANT)
    assert {t["etat_seuil"] for t in etat["tuiles"]} == {"sans_seuil"}
    assert all(t["libelle_seuil"] == "sans seuil" for t in etat["tuiles"])


def test_une_mesure_non_calculable_n_est_jamais_un_zero_affiche():
    definition = wallboards.charger(_CAT)["marketing"]
    etat = wallboards.evaluer(definition, _mesures(), maintenant=_MAINTENANT)
    tuiles = {t["id"]: t for t in etat["tuiles"]}
    assert tuiles["impressions"]["valeur_affichee"] == "non calculable" and tuiles["impressions"]["valeur"] is None
    assert tuiles["clics"]["a_jour"] is False and tuiles["clics"]["libelle_fraicheur"] == "Non calculable"
    assert "non calculable" in " ".join(etat["banniere"]["messages"]) and etat["banniere"]["niveau"] == "attention"


def test_aucune_donnee_personnelle_dans_le_rendu():
    definition = wallboards.charger(_CAT)["direction"]
    etat = wallboards.evaluer(definition, _mesures(), maintenant=_MAINTENANT)
    rendu = json.dumps(etat, ensure_ascii=False)
    for interdit in ("tech-fictif", "technicien", "client_id", "@", "utm-fictif"):
        assert interdit not in rendu


@pytest.mark.parametrize(
    ("valeur", "unite", "attendu"),
    [
        ("1234567.5", "CAD", "1 234 567,5 $"),
        ("-1500.00", "CAD", "-1 500,00 $"),
        ("12.50", "pourcentage", "12,50 %"),
        ("0", "leads", "0 leads"),
        ("999", "devis", "999 devis"),
        ("1000", "devis", "1 000 devis"),
        (None, "CAD", "non calculable"),
    ],
)
def test_le_formatage_vient_du_texte_exact(valeur, unite, attendu):
    assert wallboards.formater_valeur(valeur, unite) == attendu.replace(" ", " ")


def test_le_role_est_relu_et_ferme_par_defaut():
    definition = wallboards.charger(_CAT)["direction"]
    assert wallboards.role_permis(definition, {"admin"}) and wallboards.role_permis(definition, ["admin"])
    assert not wallboards.role_permis(definition, {"employee"}) and not wallboards.role_permis(definition, set())
    assert not wallboards.role_permis(definition, None) and not wallboards.role_permis(definition, 12)
