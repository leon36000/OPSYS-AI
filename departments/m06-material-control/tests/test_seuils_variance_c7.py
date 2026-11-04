"""C7 — seuils de variance DÉCLARÉS et ÉDITABLES : seuil global, par catégorie et par matériau, plancher en quantité
et en dollars, édition par l'admin avec audit.

Ce fichier est le ROUGE-AVANT de C7 : avant ce chantier, `seuils_variance.py` n'existe pas, aucun seuil par matériau
n'est appliqué, aucun plancher n'existe, et rien ne garde qui a changé quel seuil (le manifeste seul, sans journal).

Données fictives ; module pur et base SQLite migrée ; aucun service externe.
"""

from __future__ import annotations

import json

import pytest
from m6_material_control import seuils_variance, variance_chantier

from opsys import stockage

FICTIF = True
HORO = "2026-11-03T09:00:00-05:00"
DEPT = "m06-material-control"


def _config(**plus):
    base = {
        "global_pourcentage": "0.30",
        "par_categorie": {},
        "par_materiau": {},
        "categories": {},
        "plancher_quantite": "0",
        "plancher_dollars": "0",
    }
    base.update(plus)
    return base


def _verdict(materiau="MAT-1", ecart=40.0, ecart_pourcentage=0.40, quantite_estimee=100.0):
    return {
        "materiau_id": materiau,
        "unite": "boite",
        "quantite_estimee": quantite_estimee,
        "quantite_reelle": quantite_estimee + ecart,
        "ecart": ecart,
        "ecart_pourcentage": ecart_pourcentage,
        "verdict_variance": "ECART_REEL_SUPERIEUR",
        "cause_possible": None,
        "classification_requise": True,
    }


# ---------------------------------------------------------------------------------------------------------
# 1. Le seuil applicable : matériau > catégorie > global, jamais deviné
# ---------------------------------------------------------------------------------------------------------
def test_le_seuil_du_materiau_prime_sur_celui_de_sa_categorie_et_sur_le_global():
    config = seuils_variance.valider_config(_config(
        par_materiau={"REV-FICTIF": "0.10"},
        par_categorie={"revetement": "0.20"},
        categories={"REV-FICTIF": "revetement", "SOF-FICTIF": "revetement"},
    ))

    assert seuils_variance.seuil_pour("REV-FICTIF", config) == {
        "seuil_pourcentage": 0.10, "origine": "materiau"}
    assert seuils_variance.seuil_pour("SOF-FICTIF", config) == {
        "seuil_pourcentage": 0.20, "origine": "categorie"}
    assert seuils_variance.seuil_pour("VIS-FICTIF", config) == {
        "seuil_pourcentage": 0.30, "origine": "global"}


def test_un_materiau_sans_categorie_declaree_retombe_sur_le_global_jamais_sur_une_autre_categorie():
    config = seuils_variance.valider_config(_config(
        par_categorie={"revetement": "0.20"}, categories={"SOF-FICTIF": "revetement"}))

    assert seuils_variance.seuil_pour("REV-FICTIF", config)["origine"] == "global"


# ---------------------------------------------------------------------------------------------------------
# 2. La criticité : borne incluse, planchers en quantité ET en dollars
# ---------------------------------------------------------------------------------------------------------
def test_le_seuil_est_inclus_et_un_ecart_sous_le_seuil_n_est_pas_critique():
    config = seuils_variance.valider_config(_config(global_pourcentage="0.30"))

    assert seuils_variance.critique(_verdict(ecart=30.0, ecart_pourcentage=0.30), config)["critique"] is True
    assert seuils_variance.critique(_verdict(ecart=29.99, ecart_pourcentage=0.2999), config) == {
        "critique": False, "motif": "sous_seuil", "seuil_pourcentage": 0.30, "origine": "global"}


def test_le_plancher_de_quantite_est_inclus_et_une_petite_quantite_ne_declenche_pas_la_revue_meme_a_40_pourcent():
    config = seuils_variance.valider_config(_config(plancher_quantite="40"))

    assert seuils_variance.critique(_verdict(ecart=40.0), config)["critique"] is True
    assert seuils_variance.critique(_verdict(ecart=39.99, ecart_pourcentage=0.3999), config) == {
        "critique": False, "motif": "sous_plancher_quantite", "seuil_pourcentage": 0.30, "origine": "global"}


def test_le_plancher_en_dollars_est_calcule_en_decimal_au_cent_et_est_inclus():
    config = seuils_variance.valider_config(_config(plancher_dollars="200.00"))

    # 40 boîtes à 5,00 $ = 200,00 $ : borne incluse.
    assert seuils_variance.critique(_verdict(ecart=40.0), config, valeur_unitaire=5.0)["critique"] is True
    # 39 boîtes à 5,00 $ = 195,00 $ : sous le plancher, bien que 39 % > 30 %.
    verdict = seuils_variance.critique(_verdict(ecart=39.0, ecart_pourcentage=0.39), config, valeur_unitaire=5.0)
    assert verdict["critique"] is False and verdict["motif"] == "sous_plancher_dollars"


def test_un_plancher_en_dollars_sans_valeur_unitaire_est_critique_et_le_dit_jamais_un_prix_invente():
    config = seuils_variance.valider_config(_config(plancher_dollars="200.00"))

    verdict = seuils_variance.critique(_verdict(ecart=40.0), config, valeur_unitaire=None)

    assert verdict["critique"] is True and verdict["motif"] == "plancher_dollars_non_evalue"


def test_un_ratio_non_defini_ne_declenche_jamais_la_criticite_automatique():
    config = seuils_variance.valider_config(_config())

    verdict = seuils_variance.critique(_verdict(ecart=1000.0, ecart_pourcentage=None, quantite_estimee=0.0), config)

    assert verdict["critique"] is False and verdict["motif"] == "ratio_non_defini"


# ---------------------------------------------------------------------------------------------------------
# 3. Validation fail-closed des réglages déclarés
# ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("mauvais", [
    {**_config(), "cle_inconnue": "1"},
    {**_config(), "global_pourcentage": "0"},
    {**_config(), "global_pourcentage": "6"},
    {**_config(), "global_pourcentage": "beaucoup"},
    {**_config(), "global_pourcentage": 0.3},
    {**_config(), "par_categorie": {"revetement": "-0.1"}},
    {**_config(), "plancher_quantite": None},
    {**_config(), "plancher_dollars": "-1"},
    {**_config(), "categories": {"REV-FICTIF": ""}},
    {**_config(), "par_materiau": ["REV-FICTIF"]},
])
def test_une_configuration_incomplete_ou_hors_bornes_est_refusee_nommee(mauvais):
    with pytest.raises(seuils_variance.SeuilsRefuses) as refus:
        seuils_variance.valider_config(mauvais)

    assert refus.value.code.startswith("REJ-SEUILS-")


# ---------------------------------------------------------------------------------------------------------
# 4. Le registre d'audit : qui, quand, avant/après, chaîne ; jamais une réécriture
# ---------------------------------------------------------------------------------------------------------
@pytest.fixture
def registre():
    return []


def _adopter(registre, config=None, *, auteur="admin.fictif", role="admin", motif="Seuils de départ, fictifs",
             version_attendue=0, horodatage=HORO, approbation_id=None):
    return seuils_variance.enregistrer(
        config or _config(), auteur=auteur, role=role, motif=motif, horodatage=horodatage,
        registre_cible=registre, version_attendue=version_attendue, approbation_id=approbation_id)


def test_adopter_ecrit_un_maillon_audite_avec_avant_apres_auteur_role_motif_et_empreinte(registre):
    maillon, code = _adopter(registre, _config(global_pourcentage="0.25"))

    assert code is None and maillon["version"] == 1 and maillon["avant"] is None
    assert maillon["apres"]["global_pourcentage"] == "0.25"
    assert maillon["auteur"] == "admin.fictif" and maillon["role"] == "admin"
    assert maillon["motif"] == "Seuils de départ, fictifs" and maillon["precedent"] is None
    assert len(maillon["empreinte"]) == 64 and seuils_variance.verifier_chaine(registre) is True


def test_une_seconde_adoption_garde_l_ancienne_valeur_en_avant_et_enchaine_l_empreinte(registre):
    premier, _ = _adopter(registre, _config(global_pourcentage="0.25"), version_attendue=0)
    second, code = _adopter(registre, _config(global_pourcentage="0.20"), version_attendue=1)

    assert code is None and second["version"] == 2
    assert second["avant"] == premier["apres"] and second["precedent"] == premier["empreinte"]
    assert seuils_variance.dernier(registre)["apres"]["global_pourcentage"] == "0.2"


def test_rejouer_la_meme_configuration_ne_cree_aucun_maillon_et_ne_change_pas_la_version(registre):
    _adopter(registre, _config(global_pourcentage="0.25"), version_attendue=0)
    avant = list(registre)

    resultat, code = _adopter(registre, _config(global_pourcentage="0.25"), version_attendue=1)

    assert code is None and resultat["deja_en_vigueur"] is True and registre == avant


def test_une_version_perimee_est_refusee_avant_toute_ecriture(registre):
    _adopter(registre, version_attendue=0)

    resultat, code = _adopter(registre, _config(global_pourcentage="0.2"), version_attendue=0)

    assert resultat is None and code == "REJ-SEUILS-VERSION" and len(registre) == 1


@pytest.mark.parametrize("role", ["employee", "seller", "manager", "system_agent"])
def test_seul_un_admin_ou_le_proprietaire_edite_les_seuils(registre, role):
    resultat, code = _adopter(registre, role=role)

    assert resultat is None and code == "REJ-SEUILS-ROLE" and registre == []


def test_un_motif_vide_est_refuse_et_l_edition_reste_tracee_par_un_motif_lisible(registre):
    resultat, code = _adopter(registre, motif="   ")

    assert resultat is None and code == "REJ-SEUILS-MOTIF"


def test_une_chaine_retouchee_est_detectee_et_le_dernier_maillon_n_est_plus_servi(registre):
    _adopter(registre, version_attendue=0)
    _adopter(registre, _config(global_pourcentage="0.2"), version_attendue=1)

    registre[0]["apres"]["global_pourcentage"] = "0.01"

    assert seuils_variance.verifier_chaine(registre) is False
    assert seuils_variance.config_en_vigueur(registre) is None


# ---------------------------------------------------------------------------------------------------------
# 5. Branchement dans variance_chantier : le seuil par matériau décide, pas le global
# ---------------------------------------------------------------------------------------------------------
def _besoin(materiau_id, quantite=100.0):
    return {"materiau_id": materiau_id, "quantite_estimee": quantite, "unite": "boite"}


def _ligne(materiau_id, quantite):
    return {"type_ligne": "prevu", "materiau_id": materiau_id, "quantite": quantite, "unite": "boite",
            "quantite_estimee": 100.0}


def test_le_seuil_par_materiau_change_la_liste_critique_du_signal():
    config = seuils_variance.valider_config(_config(
        par_materiau={"MAT-B": "0.50"}, global_pourcentage="0.30"))

    resultat, code = variance_chantier.evaluer(
        "CH-FICTIF", [_besoin("MAT-A"), _besoin("MAT-B")],
        [_ligne("MAT-A", 140.0), _ligne("MAT-B", 140.0)], 0.30, seuils=config)

    assert code is None
    signal = resultat["signal_variance_critique"]
    assert signal["materiaux_en_ecart_critique"] == ["MAT-A"], "MAT-B est sous SON seuil de 50 %"


def test_le_plancher_en_quantite_change_la_liste_critique_du_signal():
    config = seuils_variance.valider_config(_config(plancher_quantite="50"))

    resultat, code = variance_chantier.evaluer(
        "CH-FICTIF", [_besoin("MAT-A")], [_ligne("MAT-A", 140.0)], 0.30, seuils=config)

    assert code is None and resultat["signal_variance_critique"] is None, "40 < plancher de 50"


def test_sans_configuration_c7_le_comportement_historique_du_seuil_global_reste_intact():
    resultat, code = variance_chantier.evaluer(
        "CH-FICTIF", [_besoin("MAT-A")], [_ligne("MAT-A", 140.0)], 0.30)

    assert code is None and resultat["signal_variance_critique"]["materiaux_en_ecart_critique"] == ["MAT-A"]


# ---------------------------------------------------------------------------------------------------------
# 6. Le registre durable et le cache du manifeste : la direction édite, M6 relit au prochain appel
# ---------------------------------------------------------------------------------------------------------
@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


def test_le_dernier_seuils_est_relu_au_registre_durable_et_non_depuis_un_cache(base_durable):
    with stockage.transaction():
        registre = stockage.maillons(DEPT, seuils_variance.REGISTRE)
        seuils_variance.enregistrer(
            _config(global_pourcentage="0.25"), auteur="admin.fictif", role="admin", motif="Décision fictive",
            horodatage=HORO, registre_cible=registre, version_attendue=0)

    with stockage.transaction():
        config = seuils_variance.config_en_vigueur(stockage.maillons(DEPT, seuils_variance.REGISTRE))

    assert config is not None and config["global_pourcentage"] == "0.25"
    assert config["mode"] == "adopte"


def test_le_maillon_ne_contient_aucun_secret_ni_texte_de_client(registre):
    maillon, _ = _adopter(registre)

    texte = json.dumps(maillon, ensure_ascii=False)

    assert "mot-de-passe" not in texte and "@" not in texte


# ---------------------------------------------------------------------------------------------------------
# 7. Le VRAI chemin M6 : registre durable -> _evaluer_et_publier_variance -> événement publié
# ---------------------------------------------------------------------------------------------------------
def _wct(wct_id="wct-c7-fictif", devis="DEVIS-C7-fictif"):
    return {
        "wct_id": wct_id, "intervention_id": "int-C7-fictif", "devis_id": devis,
        "horodatage_completion": "2026-11-03T15:00:00-05:00",
    }


def _preparer(wct, lignes_besoins, mouvements, livre=(), chantier="CH-C7-fictif"):
    with stockage.transaction():
        stockage.maillons(DEPT, "besoins_prevus").append(
            {"chantier_id": chantier, "devis_id": wct["devis_id"], "lignes": lignes_besoins})
        for mouvement in mouvements:
            stockage.maillons(DEPT, "principal").append(mouvement)
        for entree in livre:
            stockage.maillons(DEPT, "livre_prix").append(entree)


def _configurer_c7(**plus):
    config = _config(**plus)
    with stockage.transaction():
        seuils_variance.enregistrer(
            config, auteur="admin.fictif", role="admin", motif="Seuils C7 fictifs",
            horodatage=HORO, registre_cible=stockage.maillons(DEPT, seuils_variance.REGISTRE),
            version_attendue=0)


def _mouvement_c7(materiau, quantite, wct_id="wct-c7-fictif"):
    return {"type_mouvement": "CONSOMMATION", "chantier_id": "CH-C7-fictif", "materiau_id": materiau,
            "quantite": -quantite, "wct_id": wct_id, "unite": "boite", "cout_unitaire": None}


def _charge_variance(wct_id="wct-c7-fictif", statut="evaluee"):
    from opsys import evenements

    return evenements.charge_publiee("m6.variance_chantier", f"m6-variance-{wct_id}-{statut}")


def test_le_vrai_chemin_lit_le_seuil_par_materiau_au_registre_et_publie_le_bon_critique(base_durable):
    from m6_material_control import outils as outils_mod

    wct = _wct()
    _preparer(
        wct,
        [{"materiau_id": "MAT-A", "quantite_estimee": 100.0, "unite": "boite"},
         {"materiau_id": "MAT-B", "quantite_estimee": 100.0, "unite": "boite"}],
        [_mouvement_c7("MAT-A", 140.0), _mouvement_c7("MAT-B", 140.0)],
    )
    _configurer_c7(par_materiau={"MAT-B": "0.50"}, global_pourcentage="0.30", plancher_quantite="0",
                   plancher_dollars="0")

    with stockage.transaction():
        outils_mod._evaluer_et_publier_variance(wct)

    charge = _charge_variance()
    assert charge["statut_variance"] == "evaluee" and charge["signal_critique"] is True
    assert {ligne["materiau"]: ligne["critique"] for ligne in charge["lignes"]} == {
        "MAT-A": True, "MAT-B": False}
    assert charge["seuil_pourcentage"] == 0.30


def test_le_vrai_chemin_applique_le_plancher_en_dollars_avec_le_prix_declare_au_livre(base_durable):
    from m6_material_control import outils as outils_mod

    wct = _wct()
    _preparer(
        wct,
        [{"materiau_id": "MAT-A", "quantite_estimee": 100.0, "unite": "boite"},
         {"materiau_id": "MAT-B", "quantite_estimee": 100.0, "unite": "boite"}],
        [_mouvement_c7("MAT-A", 140.0), _mouvement_c7("MAT-B", 139.0)],
        livre=[
            {"materiau_id": "MAT-A", "fournisseur_id": "f-c7", "prix_unitaire": 5.0, "devise": "CAD",
             "date_effet": "2026-10-01", "unite": "boite", "source_document": None},
            {"materiau_id": "MAT-B", "fournisseur_id": "f-c7", "prix_unitaire": 5.0, "devise": "CAD",
             "date_effet": "2026-10-01", "unite": "boite", "source_document": None},
        ],
    )
    _configurer_c7(global_pourcentage="0.30", plancher_quantite="0", plancher_dollars="200.00")

    with stockage.transaction():
        outils_mod._evaluer_et_publier_variance(wct)

    charge = _charge_variance()
    assert {ligne["materiau"]: ligne["critique"] for ligne in charge["lignes"]} == {
        "MAT-A": True, "MAT-B": False}, "A = 40 x 5 = 200 (inclus), B = 39 x 5 = 195 (exclu)"


def test_un_registre_retouche_ne_sert_aucun_seuil_et_le_chantier_sort_seuil_absent(base_durable):
    from m6_material_control import outils as outils_mod

    wct = _wct()
    _preparer(wct, [{"materiau_id": "MAT-A", "quantite_estimee": 100.0, "unite": "boite"}],
              [_mouvement_c7("MAT-A", 140.0)])
    _configurer_c7(global_pourcentage="0.30", plancher_quantite="0", plancher_dollars="0")
    with stockage.transaction():
        registre = stockage.maillons(DEPT, seuils_variance.REGISTRE)
        premier = registre[0]
        faux = {**premier, "version": 2, "precedent": premier["empreinte"], "avant": premier["apres"],
                "empreinte": "0" * 64}
        faux["apres"] = {**premier["apres"], "global_pourcentage": "0.01"}
        registre.append(faux)

    with stockage.transaction():
        outils_mod._evaluer_et_publier_variance(wct)
        attentes = [a for a in outils_mod.attentes() if a["type"] == "seuils_variance_a_configurer"]

    assert _charge_variance(statut="seuil_absent")["statut_variance"] == "seuil_absent"
    assert len(attentes) == 1 and "reconfigurer" in attentes[0]["resume"].lower()


# ---------------------------------------------------------------------------------------------------------
# 8. Bornes exactes, types hostiles et chaîne d'audit (mutants survivants)
# ---------------------------------------------------------------------------------------------------------
def test_les_bornes_de_longueur_sont_exactes_et_un_texte_vide_est_refuse(registre):
    assert _adopter(registre, auteur="a" * 200, motif="m" * 500)[1] is None
    registre.clear()

    for champ, valeur, code in (
        ("auteur", "", "REJ-SEUILS-AUTEUR"),
        ("auteur", "a" * 201, "REJ-SEUILS-AUTEUR"),
        ("motif", "", "REJ-SEUILS-MOTIF"),
        ("motif", "m" * 501, "REJ-SEUILS-MOTIF"),
        ("approbation_id", "p" * 201, "REJ-SEUILS-APPROBATION"),
        ("approbation_id", 123, "REJ-SEUILS-APPROBATION"),
    ):
        resultat, code_lu = _adopter(registre, **{champ: valeur})
        assert resultat is None and code_lu == code, (champ, code_lu)
        assert registre == []


def test_une_cle_de_materiau_de_200_caracteres_est_acceptee_et_201_refusee():
    for longueur, accepte in ((200, True), (201, False)):
        config = _config(par_materiau={"M" * longueur: "0.2"})
        if accepte:
            assert seuils_variance.valider_config(config)["par_materiau"]
        else:
            with pytest.raises(seuils_variance.SeuilsRefuses):
                seuils_variance.valider_config(config)
    for longueur, accepte in ((200, True), (201, False)):
        for config in (
            _config(categories={"REV-FICTIF": "C" * longueur}),
            _config(categories={"M" * longueur: "revetement"}),
        ):
            if accepte:
                assert seuils_variance.valider_config(config)["categories"]
            else:
                with pytest.raises(seuils_variance.SeuilsRefuses):
                    seuils_variance.valider_config(config)


def test_les_bornes_de_pourcentage_et_de_plancher_sont_incluses_et_un_texte_trop_long_est_refuse():
    assert seuils_variance.valider_config(_config(global_pourcentage="5"))["global_pourcentage"] == "5"
    assert seuils_variance.valider_config(_config(global_pourcentage="0.01"))["global_pourcentage"] == "0.01"
    for mauvais in ("5.0001", "0.009"):
        with pytest.raises(seuils_variance.SeuilsRefuses):
            seuils_variance.valider_config(_config(global_pourcentage=mauvais))
    # 41 caractères mais une valeur parfaitement lisible : la borne de longueur refuse, pas le décimal.
    with pytest.raises(seuils_variance.SeuilsRefuses):
        seuils_variance.valider_config(_config(plancher_quantite="0" * 40 + "1"))
    assert seuils_variance.valider_config(_config(plancher_quantite="0" * 39 + "1"))["plancher_quantite"] == "1"


def test_un_identifiant_de_materiau_non_texte_retombe_sur_le_global():
    config = seuils_variance.valider_config(_config(par_materiau={"MAT-1": "0.1"}))

    assert seuils_variance.seuil_pour(None, config)["origine"] == "global"
    assert seuils_variance.seuil_pour(123, config)["origine"] == "global"


def test_un_plancher_en_dollars_a_zero_est_declare_et_n_est_pas_non_evalue():
    config = seuils_variance.valider_config(_config(plancher_dollars="0"))

    verdict = seuils_variance.critique(_verdict(ecart=40.0), config, valeur_unitaire=None)

    assert verdict["critique"] is True and verdict["motif"] == "au_dessus_du_seuil"
    assert "valeur_ecart" not in verdict


def test_une_valeur_unitaire_positive_inferieure_a_un_dollar_reste_utilisable():
    config = seuils_variance.valider_config(_config(plancher_dollars="20"))

    verdict = seuils_variance.critique(_verdict(ecart=40.0), config, valeur_unitaire=0.5)

    assert verdict["critique"] is True and verdict["motif"] == "au_dessus_des_seuils"


@pytest.mark.parametrize("valeur", [float("nan"), float("inf"), 0.0, -1.0])
def test_une_valeur_unitaire_impossible_ne_calcule_aucun_montant(valeur):
    config = seuils_variance.valider_config(_config(plancher_dollars="200"))

    verdict = seuils_variance.critique(_verdict(ecart=40.0), config, valeur_unitaire=valeur)

    assert verdict["critique"] is True and verdict["motif"] == "plancher_dollars_non_evalue"


def test_un_plancher_en_dollars_d_un_dollar_est_actif_et_non_evalue_sans_valeur():
    config = seuils_variance.valider_config(_config(plancher_dollars="1"))

    verdict = seuils_variance.critique(_verdict(ecart=40.0), config, valeur_unitaire=None)

    assert verdict["critique"] is True and verdict["motif"] == "plancher_dollars_non_evalue"


def test_le_mode_herite_reste_critique_au_dessus_du_seuil_global():
    config = seuils_variance.config_heritee(0.30)

    verdict = seuils_variance.critique(_verdict(ecart=40.0), config)

    assert verdict == {"critique": True, "motif": "au_dessus_du_seuil", "seuil_pourcentage": 0.3,
                       "origine": "global"}


def test_un_verdict_sans_ecart_utilise_zero_pour_les_planchers():
    config = seuils_variance.valider_config(_config(plancher_quantite="1", plancher_dollars="0"))
    verdict = {"materiau_id": "MAT-1", "ecart_pourcentage": 0.40}

    resultat = seuils_variance.critique(verdict, config)

    assert resultat["critique"] is False and resultat["motif"] == "sous_plancher_quantite"


def test_un_ecart_sans_valeur_unitaire_avec_plancher_dollars_reste_non_evalue():
    config = seuils_variance.valider_config(_config(plancher_quantite="0", plancher_dollars="200"))
    verdict = {"materiau_id": "MAT-1", "ecart_pourcentage": 0.40}

    resultat = seuils_variance.critique(verdict, config, valeur_unitaire=None)

    assert resultat["critique"] is True and resultat["motif"] == "plancher_dollars_non_evalue"


def test_un_ecart_absent_est_zero_pour_le_plancher_en_dollars():
    config = seuils_variance.valider_config(_config(plancher_quantite="0", plancher_dollars="5"))
    verdict = {"materiau_id": "MAT-1", "ecart_pourcentage": 0.40}

    assert seuils_variance.critique(verdict, config, valeur_unitaire=5.0)["motif"] == "sous_plancher_dollars"


def test_la_chaine_refuse_un_maillon_non_dict_un_type_inconnu_une_cle_manquante(registre):
    _adopter(registre)
    valide = registre[0]

    assert seuils_variance.verifier_chaine([42]) is False
    assert seuils_variance.verifier_chaine([{**valide, "type_entree": "autre"}]) is False
    for cle in tuple(valide):
        sans = {k: v for k, v in valide.items() if k != cle}
        assert seuils_variance.verifier_chaine([sans]) is False, cle


def test_la_chaine_refuse_une_version_un_precedent_ou_un_avant_retouches(registre):
    _adopter(registre)
    _adopter(registre, _config(global_pourcentage="0.2"), version_attendue=1)
    premier, second = registre[0], registre[1]

    faux_version = {**premier, "version": 2}
    faux_precedent = {**second, "precedent": "0" * 64}
    faux_avant = {**second, "avant": {"mode": "adopte"}}
    faux_empreinte = {**second, "empreinte": "0" * 64}
    # Chaque champ est isolé : l'empreinte est RECALCULÉE après la retouche, sinon le seul contrôle d'empreinte
    # masquerait le contrôle de version / de lien au précédent / de l'« avant ».
    from m6_material_control.seuils_variance import _empreinte

    isoles = []
    for faux in (faux_version, faux_precedent, faux_avant):
        faux = {k: v for k, v in faux.items() if k != "empreinte"}
        faux["empreinte"] = _empreinte(faux)
        isoles.append(faux)
    for faux in (*isoles, faux_empreinte):
        assert seuils_variance.verifier_chaine([premier, faux]) is False, faux
    assert seuils_variance.verifier_chaine([premier, second]) is True


def test_le_dernier_maillon_ignore_les_entrees_qui_ne_sont_pas_des_maillons_de_seuils(registre):
    _adopter(registre)
    valide = registre[0]

    assert seuils_variance.dernier([42, {"type_entree": "autre"}, valide]) == valide
    assert seuils_variance.dernier([42, {"type_entree": "autre"}]) is None


def test_la_version_attendue_a_un_defaut_de_zero_et_refuse_les_types_et_bornes_invalides(registre):
    maillon, code = seuils_variance.enregistrer(
        _config(), auteur="admin.fictif", role="admin", motif="Sans version explicite",
        horodatage=HORO, registre_cible=registre)
    assert code is None and maillon["version"] == 1
    registre.clear()

    for mauvais in (True, "0", -1, 10**9 + 1):
        resultat, code = seuils_variance.enregistrer(
            _config(), auteur="admin.fictif", role="admin", motif="Version invalide", horodatage=HORO,
            registre_cible=registre, version_attendue=mauvais)
        assert resultat is None and code == "REJ-SEUILS-VERSION", mauvais
        assert registre == []


def test_un_horodatage_naif_vide_trop_long_ou_d_un_autre_type_est_refuse(registre):
    for mauvais in ("", None, 42, "2026-11-03T09:00:00", "hier", "2026-11-03T09:00:00." + "0" * 25 + "+00:00"):
        resultat, code = seuils_variance.enregistrer(
            _config(), auteur="admin.fictif", role="admin", motif="Horodatage invalide", horodatage=mauvais,
            registre_cible=registre)
        assert resultat is None and code == "REJ-SEUILS-HORODATAGE", mauvais
        assert registre == []


def test_un_horodatage_valide_de_50_caracteres_exactement_est_accepte(registre):
    horodatage = "2026-11-03T09:00:00." + "0" * 24 + "+00:00"
    assert len(horodatage) == 50

    maillon, code = seuils_variance.enregistrer(
        _config(), auteur="admin.fictif", role="admin", motif="Borne de longueur d'horodatage",
        horodatage=horodatage, registre_cible=registre)

    assert code is None and maillon["horodatage"] == horodatage


def test_un_materiau_rattache_a_une_categorie_sans_seuil_retombe_sur_le_global():
    config = seuils_variance.valider_config(_config(
        par_categorie={"gouttieres": "0.20"}, categories={"REV-FICTIF": "revetement"}))

    assert seuils_variance.seuil_pour("REV-FICTIF", config) == {
        "seuil_pourcentage": 0.30, "origine": "global"}


def test_l_empreinte_du_maillon_d_audit_est_figee_pour_une_decision_donnée(registre):
    """Une empreinte figée protège la canonicalisation de l'audit : changer l'encodage (ASCII échappé, ordre des clés,
    séparateurs) change l'empreinte et casserait la vérification d'une chaîne existante."""
    maillon, code = seuils_variance.enregistrer(
        _config(global_pourcentage="0.30", par_categorie={"revêtement": "0.20"}),
        auteur="admin.fictif", role="admin", motif="Décision fictive — accents éàç",
        horodatage="2026-11-03T09:00:00-05:00", registre_cible=registre)

    assert code is None
    assert maillon["empreinte"] == "ce5cdf016052f7a6692624de86c3bf9db4c67aa120685fcb0889f88e85d623e9"


def test_les_valeurs_unitaires_ne_prennent_que_les_mouvements_du_chantier_et_du_wct(base_durable):
    from m6_material_control import outils as outils_mod

    wct = _wct()
    mouvements = [
        _mouvement_c7("MAT-A", 10.0),
        {**_mouvement_c7("MAT-AUTRE-CHANTIER", 10.0), "chantier_id": "CH-AUTRE"},
        {**_mouvement_c7("MAT-AUTRE-WCT", 10.0), "wct_id": "wct-autre"},
        {**_mouvement_c7("MAT-INT", 10.0), "materiau_id": 123},
    ]
    _preparer(wct, [{"materiau_id": "MAT-A", "quantite_estimee": 10.0, "unite": "boite"}], mouvements)

    with stockage.transaction():
        valeurs = outils_mod._valeurs_unitaires_variance(
            "CH-C7-fictif", [{"materiau_id": "MAT-A", "unite": "boite"}], mouvements,
            wct["horodatage_completion"], "wct-c7-fictif")

    assert set(valeurs) == {"MAT-A"}


def test_un_seuil_absent_garde_le_chantier_du_besoin_pour_l_evenement(base_durable, monkeypatch, tmp_path):
    from m6_material_control import outils as outils_mod

    manifeste = tmp_path / "department-m6-sans-seuil.yaml"
    manifeste.write_text("schema: opsys.departement/v1\nconfiguration: {}\n", encoding="utf-8")
    monkeypatch.setattr(outils_mod, "_MANIFESTE", manifeste)
    wct = _wct()
    _preparer(wct, [{"materiau_id": "MAT-A", "quantite_estimee": 10.0, "unite": "boite"}],
              [{**_mouvement_c7("MAT-A", 10.0), "chantier_id": "CH-DECLARATION"}], chantier="CH-BESOIN")

    with stockage.transaction():
        outils_mod._evaluer_et_publier_variance(wct)

    charge = _charge_variance(statut="seuil_absent")
    assert charge["chantier_id"] == "CH-BESOIN"


def test_un_prevu_sans_chantier_reprend_le_chantier_de_la_declaration(base_durable):
    from m6_material_control import outils as outils_mod

    wct = _wct()
    _preparer(wct, [{"materiau_id": "MAT-A", "quantite_estimee": 10.0, "unite": "boite"}],
              [{**_mouvement_c7("MAT-A", 10.0), "chantier_id": "CH-DECLARATION"}], chantier=None)
    _configurer_c7(global_pourcentage="0.30", plancher_quantite="0", plancher_dollars="0")

    with stockage.transaction():
        outils_mod._evaluer_et_publier_variance(wct)

    charge = _charge_variance()
    assert charge["statut_variance"] == "evaluee" and charge["chantier_id"] == "CH-DECLARATION"


def test_aucune_attente_de_seuils_sans_registre_et_une_seule_avec_un_registre_illisible(base_durable):
    from m6_material_control import outils as outils_mod

    with stockage.transaction():
        assert [a for a in outils_mod.attentes() if a["type"] == "seuils_variance_a_configurer"] == []
        stockage.maillons(DEPT, seuils_variance.REGISTRE).append(42)
        attentes = [a for a in outils_mod.attentes() if a["type"] == "seuils_variance_a_configurer"]

    assert len(attentes) == 1 and attentes[0]["depuis"] == ""


def test_la_file_des_achats_terrain_ignore_les_non_maillons_et_les_non_attentes(base_durable):
    from m6_material_control import outils as outils_mod

    with stockage.transaction():
        registre = stockage.maillons(DEPT, outils_mod._NOM_REGISTRE_ACHATS_TERRAIN)
        registre.append(42)
        registre.append({"en_attente": False, "recu": "recu-faux-fictif", "statut": "en_attente_approbation"})
        registre.append({"en_attente": True, "recu": "recu-vrai-fictif", "statut": "en_attente_approbation",
                         "motif": "Dépassement fictif"})
        attentes = [a for a in outils_mod.attentes() if a["type"] == "achat_terrain_a_approuver"]

    assert [a["id"] for a in attentes] == ["achat_terrain:recu-vrai-fictif"]


def test_une_chaine_retouchee_avec_un_nan_est_invalide_sans_exception():
    # Trouvé à l'intégration par le survivant `allow_nan=False -> True` : un maillon retouché portant NaN faisait
    # lever ValueError à `verifier_chaine` au lieu de la déclarer invalide.
    from m6_material_control import seuils_variance as sv

    maillon = {
        "type_entree": sv.TYPE_ENTREE, "version": 1, "apres": {"x": float("nan")}, "avant": None, "auteur": "a",
        "role": "admin", "motif": "m", "horodatage": "2026-11-03T10:00:00-05:00", "approbation_id": "x",
        "precedent": None, "empreinte": "0" * 64,
    }
    assert sv.verifier_chaine([maillon]) is False
    assert sv._empreinte({"x": 1}) == sv._empreinte({"x": 1})
    with __import__("pytest").raises(ValueError):
        sv._empreinte({"x": float("nan")})


@pytest.mark.parametrize("ratio", ["beaucoup", float("nan"), float("inf"), [0.40], {"ratio": 0.40}, True])
def test_un_ratio_illisible_rend_un_verdict_non_defini_sans_lever(ratio):
    """`critique` est publique : un ratio hostile ne doit jamais faire remonter une exception de `decimal`."""
    resultat = seuils_variance.critique(_verdict(ecart_pourcentage=ratio), seuils_variance.valider_config(_config()))

    assert resultat["critique"] is False and resultat["motif"] == "ratio_non_defini"


def test_un_ecart_negatif_est_juge_en_valeur_absolue_dans_les_deux_modes():
    config = seuils_variance.valider_config(_config())
    herite = seuils_variance.config_heritee(0.30)

    assert seuils_variance.critique(_verdict(ecart=-40.0, ecart_pourcentage=-0.40), config)["critique"] is True
    assert seuils_variance.critique(_verdict(ecart=-29.0, ecart_pourcentage=-0.29), config)["critique"] is False
    assert seuils_variance.critique(_verdict(ecart=-40.0, ecart_pourcentage=-0.40), herite)["critique"] is True


def _retoucher_la_chaine_en_base(valeur="0.01"):
    """Une retouche RÉELLE en base : `registre[0][...] = ...` ne modifierait que la copie décodée (A7)."""
    from sqlalchemy import select, update

    from opsys.stockage import codec as codec_stockage
    from opsys.stockage.schema import REGISTRES

    with stockage.transaction() as cnx:
        brut = cnx.execute(select(REGISTRES.c.maillon).where(
            (REGISTRES.c.departement == DEPT)
            & (REGISTRES.c.registre == seuils_variance.REGISTRE))).scalar_one()
        faux = codec_stockage.decoder(brut)
        faux["apres"]["global_pourcentage"] = valeur
        cnx.execute(update(REGISTRES).where(
            (REGISTRES.c.departement == DEPT)
            & (REGISTRES.c.registre == seuils_variance.REGISTRE)).values(
                maillon=codec_stockage.encoder(faux)))


def test_une_chaine_retouchee_ne_se_repare_pas_meme_avec_la_bonne_version(base_durable):
    """Une chaîne retouchée n'est réparable NI par l'outil NI par l'écran : l'écran le dit et l'admin base agit."""
    from m6_material_control import outils as outils_mod

    with stockage.transaction():
        registre = stockage.maillons(DEPT, seuils_variance.REGISTRE)
        maillon, code = seuils_variance.enregistrer(
            _config(), auteur="admin.fictif", role="admin", motif="Premiers seuils", horodatage=HORO,
            registre_cible=registre, version_attendue=0)
        assert code is None and maillon is not None
    _retoucher_la_chaine_en_base()

    for version in (0, 1):
        with stockage.transaction():
            resultat, code = seuils_variance.enregistrer(
                _config(global_pourcentage="0.25"), auteur="admin.fictif", role="admin",
                motif="Réparation après retouche", horodatage=HORO,
                registre_cible=stockage.maillons(DEPT, seuils_variance.REGISTRE), version_attendue=version)
        assert (resultat, code) == (None, "REJ-SEUILS-CHAINE")

    with stockage.transaction():
        registre = list(stockage.maillons(DEPT, seuils_variance.REGISTRE))
        attentes = [a for a in outils_mod.attentes() if a["type"] == "seuils_variance_a_configurer"]

    assert seuils_variance.verifier_chaine(registre) is False
    assert seuils_variance.config_en_vigueur(registre) is None
    assert len(attentes) == 1
    resume = attentes[0]["resume"].lower()
    assert "reconfigurer" in resume and "n'est pas possible" in resume
    assert "administrateur de base" in resume and "hors outil" in resume
