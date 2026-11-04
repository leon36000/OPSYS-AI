"""Registre de barème déclaré (M3-C1) : déclaration, révision sans écrasement, en-vigueur, chaînage, refus lisibles.

Module pur, horloge INJECTÉE (``MAINTENANT`` et ses voisins : aucun test ne lit l'heure). Données fictives.
"""

from __future__ import annotations

import sys
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
_SRC = Path(__file__).resolve().parents[1] / "src"  # la source de CE département (la copie jetable des mutations)
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import _commun_bareme as cb  # noqa: E402
from m3_estimation import bareme_registre, verdicts  # noqa: E402
from m3_estimation.registre import _encoder_canonique  # noqa: E402


def _v1_v2(journal):
    v1 = cb.declarer_ok(journal)
    v2 = cb.declarer_ok(
        journal, version_attendue=1, date_effet=cb.JOUR_EFFET_V2, horodatage="2026-11-03T09:00:00+00:00",
        lignes=cb.lignes(cout_unitaire_min="9.00", cout_unitaire_mode="11.00", cout_unitaire_max="15.00"),
    )
    return v1, v2


def _rechainer(journal):
    """L'attaquant sait recalculer les empreintes : les invariants doivent encore refuser."""
    precedent = None
    for rang, m in enumerate(journal):
        m["rang"], m["precedent"] = rang, precedent
        m["source_id"] = _encoder_canonique({k: v for k, v in m.items() if k != "source_id"})
        precedent = m["source_id"]


# ---------------------------------------------------------------------------------------- déclaration et lecture
def test_declarer_puis_lire_rend_la_version_avec_son_empreinte_et_sa_source():
    journal = []
    v1 = cb.declarer_ok(journal)
    assert v1["version"] == 1 and v1["valide"] is True and v1["a_valider"] is False
    assert len(v1["empreinte"]) == 64
    assert v1["auteur"] == cb.PROPRIO
    assert all(ligne["source_ecrite"] for ligne in v1["lignes"])
    lu, verdict = bareme_registre.lire_version(journal, "bareme-fictif", 1)
    assert verdict is None and lu == v1
    derniere, _ = bareme_registre.lire_version(journal, "bareme-fictif")
    assert derniere["version"] == 1
    assert bareme_registre.verifier_chaine(journal) == (True, "")


def test_la_reference_exacte_rappelle_id_version_et_empreinte():
    journal = []
    v1 = cb.declarer_ok(journal)
    assert bareme_registre.reference_de(v1) == {
        "bareme_id": "bareme-fictif", "version": 1, "empreinte": v1["empreinte"],
    }


def test_une_revision_ajoute_une_version_sans_ecraser_la_precedente():
    journal = []
    v1, v2 = _v1_v2(journal)
    assert (v1["version"], v2["version"]) == (1, 2)
    assert len(journal) == 2 and journal[1]["precedent"] == journal[0]["source_id"]
    ancienne, _ = bareme_registre.lire_version(journal, "bareme-fictif", 1)
    assert ancienne == v1  # l'ancienne version est lisible, identique à bit près
    assert ancienne["lignes"][0]["cout_unitaire_max"] == "14.00"
    assert v2["lignes"][0]["cout_unitaire_max"] == "15.00"
    assert v1["empreinte"] != v2["empreinte"]
    assert bareme_registre.verifier_chaine(journal) == (True, "")


def test_rejeu_de_la_meme_declaration_ne_double_pas_le_maillon():
    journal = []
    v1 = cb.declarer_ok(journal)
    resultat, verdict = cb.declarer(journal, version_attendue=0)
    assert verdict is None and resultat["rejoue"] is True and resultat["version"] == v1
    assert len(journal) == 1


def test_revision_sur_une_version_perimee_est_refusee_avec_la_version_courante():
    journal = []
    _v1_v2(journal)
    _, verdict = cb.declarer(journal, version_attendue=1, lignes=cb.lignes(cout_unitaire_max="20.00"),
                             date_effet=cb.JOUR_EFFET_V2)
    assert cb.code(verdict) == "REJ-BAREME-REVISION-PERIMEE"
    assert "version 2" in verdict["detail"] and "relire" in verdict["detail"]
    assert len(journal) == 2


def test_une_revision_ne_peut_pas_prendre_effet_avant_la_version_precedente():
    journal = []
    cb.declarer_ok(journal)
    _, verdict = cb.declarer(journal, version_attendue=1, date_effet="2026-10-01T00:00:00+00:00")
    assert cb.code(verdict) == "REJ-BAREME-INVALIDE" and "date_effet" in verdict["detail"]


# ---------------------------------------------------------------------------------------------------- en vigueur
def test_la_version_1_est_en_vigueur_avant_la_version_2_et_perimee_apres():
    journal = []
    v1, v2 = _v1_v2(journal)
    avant = cb.MAINTENANT  # 2 novembre : la version 2 ne prend effet que le 10
    resolue, verdict = bareme_registre.resoudre(journal, cb.ref(v1), avant)
    assert verdict is None and resolue["version"] == 1
    _, verdict = bareme_registre.resoudre(journal, cb.ref(v2), avant)
    assert cb.code(verdict) == "REJ-BAREME-HORS-VIGUEUR" and "ne prend effet que le" in verdict["detail"]
    # le 12 novembre : la 2 est en vigueur, la 1 est périmée et le message dit laquelle utiliser
    apres = cb.APRES_V2
    _, verdict = bareme_registre.resoudre(journal, cb.ref(v1), apres)
    assert cb.code(verdict) == "REJ-BAREME-PERIME"
    assert "version 2" in verdict["detail"] and "référencer la version 2" in verdict["detail"]
    resolue, verdict = bareme_registre.resoudre(journal, cb.ref(v2), apres)
    assert verdict is None and resolue["version"] == 2


def test_l_instant_exact_de_la_date_d_effet_est_en_vigueur():
    journal = []
    v1, v2 = _v1_v2(journal)
    pile = bareme_registre._instant(v2["date_effet"], "date_effet")
    _, verdict = bareme_registre.resoudre(journal, cb.ref(v2), pile - timedelta(seconds=1))
    assert cb.code(verdict) == "REJ-BAREME-HORS-VIGUEUR"
    resolue, verdict = bareme_registre.resoudre(journal, cb.ref(v2), pile)
    assert verdict is None and resolue["version"] == 2


def test_une_ancienne_version_se_resout_sans_exiger_la_vigueur_pour_le_rejeu():
    journal = []
    v1, _ = _v1_v2(journal)
    resolue, verdict = bareme_registre.resoudre(journal, cb.ref(v1), cb.APRES_V2, exiger_en_vigueur=False)
    assert verdict is None and resolue["empreinte"] == v1["empreinte"]


def test_la_fin_de_validite_declaree_retire_la_vigueur_a_l_instant_exact():
    journal = []
    v1 = cb.declarer_ok(journal, valide_jusqu_au="2026-12-01T00:00:00+00:00")
    fin = bareme_registre._instant("2026-12-01T00:00:00+00:00", "x")
    _, verdict = bareme_registre.resoudre(journal, cb.ref(v1), fin - timedelta(seconds=1))
    assert verdict is None
    _, verdict = bareme_registre.resoudre(journal, cb.ref(v1), fin)
    assert cb.code(verdict) == "REJ-BAREME-HORS-VIGUEUR" and "plus de version en vigueur" in verdict["detail"]


def test_une_valeur_de_depart_a_valider_n_est_pas_utilisable_avant_la_validation():
    journal = []
    v1 = cb.declarer_ok(journal, a_valider=True)
    assert v1["valide"] is False and v1["a_valider"] is True
    _, verdict = bareme_registre.resoudre(journal, cb.ref(v1), cb.MAINTENANT)
    assert cb.code(verdict) == "REJ-BAREME-A-VALIDER" and "m3_valider_bareme" in verdict["detail"]
    resultat, verdict = bareme_registre.valider_version(
        journal, bareme_id="bareme-fictif", version=1, auteur=cb.PROPRIO, horodatage="2026-11-01T10:00:00+00:00")
    assert verdict is None and resultat["rejoue"] is False and resultat["version"]["valide"] is True
    assert resultat["version"]["validee_par"] == cb.PROPRIO
    resolue, verdict = bareme_registre.resoudre(journal, cb.ref(v1), cb.MAINTENANT)
    assert verdict is None and resolue["version"] == 1
    # valider une seconde fois rend la première validation
    deux, verdict = bareme_registre.valider_version(
        journal, bareme_id="bareme-fictif", version=1, auteur=cb.ADMIN, horodatage="2026-11-01T11:00:00+00:00")
    assert verdict is None and deux["rejoue"] is True and deux["version"]["validee_par"] == cb.PROPRIO
    assert len(journal) == 2


def test_une_version_a_valider_n_empeche_pas_la_precedente_validee_d_etre_en_vigueur():
    journal = []
    v1 = cb.declarer_ok(journal)
    cb.declarer_ok(journal, version_attendue=1, a_valider=True, date_effet=cb.JOUR_EFFET_V1)
    resolue, verdict = bareme_registre.resoudre(journal, cb.ref(v1), cb.MAINTENANT)
    assert verdict is None and resolue["version"] == 1


def test_valider_une_version_declaree_valide_ou_inexistante_est_refuse():
    journal = []
    cb.declarer_ok(journal)
    _, verdict = bareme_registre.valider_version(
        journal, bareme_id="bareme-fictif", version=1, auteur=cb.PROPRIO, horodatage="2026-11-01T10:00:00+00:00")
    assert cb.code(verdict) == "REJ-BAREME-INVALIDE" and "rien à valider" in verdict["detail"]
    _, verdict = bareme_registre.valider_version(
        journal, bareme_id="bareme-fictif", version=5, auteur=cb.PROPRIO, horodatage="2026-11-01T10:00:00+00:00")
    assert cb.code(verdict) == "REJ-BAREME-VERSION-INCONNUE"
    _, verdict = bareme_registre.valider_version(
        journal, bareme_id="inconnu", version=1, auteur=cb.PROPRIO, horodatage="2026-11-01T10:00:00+00:00")
    assert cb.code(verdict) == "REJ-BAREME-INTROUVABLE"


# ----------------------------------------------------------------------------------------- références refusées
def test_references_inconnues_disent_quoi_declarer():
    journal = []
    v1 = cb.declarer_ok(journal)
    _, verdict = bareme_registre.resoudre(journal, {"bareme_id": "autre", "version": 1}, cb.MAINTENANT)
    assert cb.code(verdict) == "REJ-BAREME-INTROUVABLE"
    assert "m3_declarer_bareme" in verdict["detail"] and "autre" in verdict["detail"]
    _, verdict = bareme_registre.resoudre(journal, {"bareme_id": "bareme-fictif", "version": 7}, cb.MAINTENANT)
    assert cb.code(verdict) == "REJ-BAREME-VERSION-INCONNUE" and "dernière version déclarée : 1" in verdict["detail"]
    _, verdict = bareme_registre.resoudre(
        journal, {**cb.ref(v1), "empreinte": "0" * 64}, cb.MAINTENANT)
    assert cb.code(verdict) == "REJ-BAREME-EMPREINTE-DIFFERENTE"
    resolue, verdict = bareme_registre.resoudre(journal, cb.ref(v1, avec_empreinte=True), cb.MAINTENANT)
    assert verdict is None and resolue["version"] == 1


@pytest.mark.parametrize("reference", [
    None, {}, "bareme-fictif", {"bareme_id": "bareme-fictif"}, {"version": 1},
    {"bareme_id": "bareme-fictif", "version": "1"}, {"bareme_id": "bareme-fictif", "version": True},
    {"bareme_id": "bareme-fictif", "version": 0}, {"bareme_id": "bareme-fictif", "version": 1, "extra": 1},
    {"bareme_id": 5, "version": 1}, {"bareme_id": "bareme-fictif", "version": 1, "empreinte": "xyz"},
])
def test_reference_mal_formee_est_refusee_avec_la_forme_attendue(reference):
    journal = []
    cb.declarer_ok(journal)
    _, verdict = bareme_registre.resoudre(journal, reference, cb.MAINTENANT)
    assert cb.code(verdict) == "REJ-BAREME-REFERENCE-REQUISE" and "bareme_id" in verdict["detail"]


def test_instant_sans_fuseau_est_refuse():
    journal = []
    v1 = cb.declarer_ok(journal)
    _, verdict = bareme_registre.resoudre(journal, cb.ref(v1), cb.MAINTENANT.replace(tzinfo=None))
    assert cb.code(verdict) == "REJ-BAREME-INVALIDE"


# --------------------------------------------------------------------------------------- validation des champs
@pytest.mark.parametrize("changement, extrait", [
    ({"lignes": []}, "lignes"),
    ({"lignes": "x"}, "lignes"),
    ({"bareme_id": "mauvais id"}, "bareme_id"),
    ({"bareme_id": "a@b"}, "bareme_id"),
    ({"bareme_id": "x" * 41}, "bareme_id"),
    ({"date_effet": "2026-11-01"}, "date_effet"),
    ({"date_effet": "2026-11-01T00:00:00"}, "date_effet"),
    ({"valide_jusqu_au": "2026-10-01T00:00:00+00:00"}, "valide_jusqu_au"),
    ({"a_valider": "oui"}, "a_valider"),
    ({"parametres": {"inconnu": 1}}, "parametres"),
    ({"parametres": {"plancher_rentable_cad": 9000}}, "plancher_rentable_cad"),
    ({"parametres": {"plancher_rentable_cad": "-5"}}, "plancher_rentable_cad"),
    ({"parametres": {"taux_marge": {"tres_agressif": "0.1"}}}, "taux_marge"),
    ({"parametres": {"taux_marge": {"normal": "11"}}}, "taux_marge.normal"),
    ({"parametres": {"seuils_revue": {"montant_maximal_cad": "0"}}}, "montant_maximal_cad"),
    ({"parametres": {"seuils_revue": {"confiance_minimale": "INDETERMINE"}}}, "confiance_minimale"),
    ({"parametres": {"mesure": {"largeur_relative_revue": "0.6", "largeur_relative_max_prix": "0.5"}}},
     "seuil de revue"),
    ({"parametres": {"mesure": {"validite_jours": 0}}}, "validite_jours"),
    ({"soumission": {"validite_jours": 400}}, "validite_jours"),
    ({"soumission": {"exclusions": "texte"}}, "exclusions"),
    ({"soumission": {"exclusions": [""]}}, "exclusions"),
    ({"soumission": {"garantie": ["10 ans"]}}, "soumission"),
])
def test_declaration_invalide_est_refusee_avec_le_champ_fautif(changement, extrait):
    journal = []
    _, verdict = cb.declarer(journal, **changement)
    assert cb.code(verdict) == "REJ-BAREME-INVALIDE" and extrait in verdict["detail"], verdict
    assert journal == []


@pytest.mark.parametrize("ouvrage, extrait", [
    ({"cout_unitaire_min": 8.0}, "cout_unitaire_min"),          # un nombre JSON arrondirait en silence
    ({"cout_unitaire_min": "abc"}, "cout_unitaire_min"),
    ({"cout_unitaire_min": "0"}, "cout_unitaire_min"),
    ({"cout_unitaire_min": "15.00"}, "dépasse"),                # min > max
    ({"cout_unitaire_mode": "7.99"}, "cout_unitaire_mode"),     # mode sous le minimum
    ({"cout_unitaire_mode": "14.01"}, "cout_unitaire_mode"),    # mode au-dessus du maximum
    ({"duree_minutes_par_unite": "0"}, "duree_minutes_par_unite"),
    ({"cout_unitaire_max": "1234567890.5"}, "cout_unitaire_max"),
    ({"source_ecrite": ""}, "source_ecrite"),
    ({"source_ecrite": " espace en tête"}, "source_ecrite"),
    ({"unite": ""}, "unite"),
    ({"inconnu": "x"}, "inconnues"),
    ({"genre": "autre"}, "genre"),
])
def test_ligne_d_ouvrage_invalide_est_refusee(ouvrage, extrait):
    journal = []
    _, verdict = cb.declarer(journal, lignes=cb.lignes(**ouvrage))
    assert cb.code(verdict) == "REJ-BAREME-INVALIDE" and extrait in verdict["detail"], verdict


def test_les_bornes_de_mode_et_de_prix_sont_incluses_quand_elles_valent_les_extremes():
    journal = []
    cb.declarer_ok(journal, lignes=cb.lignes(cout_unitaire_mode="8.00"))
    cb.declarer_ok(journal, bareme_id="b2", lignes=cb.lignes(cout_unitaire_mode="14.00"))
    # coût fixe : min == mode == max
    cb.declarer_ok(journal, bareme_id="b3", lignes=cb.lignes(cout_unitaire_min="14.00", cout_unitaire_mode="14.00"))


def test_lignes_de_materiau_invalides_ou_incoherentes():
    journal = []
    materiau = cb.lignes()[1]
    for changement, extrait in (
        ({"taux_perte": "1"}, "taux_perte"), ({"taux_perte": "10"}, "taux_perte"),
        ({"quantite_par_unite": "0"}, "quantite"),
        ({"quantite_par_unite": 1.1}, "quantite_par_unite"), ({"sku": ""}, "sku"),
    ):
        _, verdict = cb.declarer(journal, lignes=[cb.lignes()[0], {**materiau, **changement}])
        assert cb.code(verdict) == "REJ-BAREME-INVALIDE" and extrait in verdict["detail"], (changement, verdict)
    # matériau sans ouvrage du même service
    _, verdict = cb.declarer(journal, lignes=[cb.lignes()[0], {**materiau, "service": "extension"}])
    assert cb.code(verdict) == "REJ-BAREME-INVALIDE" and "sans ligne d'ouvrage" in verdict["detail"]
    # matériau en double
    _, verdict = cb.declarer(journal, lignes=[*cb.lignes(), cb.lignes()[1]])
    assert cb.code(verdict) == "REJ-BAREME-INVALIDE" and "en double" in verdict["detail"]
    # deux ouvrages pour le même service
    _, verdict = cb.declarer(journal, lignes=[*cb.lignes(), cb.lignes()[0]])
    assert cb.code(verdict) == "REJ-BAREME-INVALIDE" and "déjà une ligne d'ouvrage" in verdict["detail"]
    # taux_perte absent : permis (le besoin sera publié sans perte et le dira)
    sans_perte = {k: v for k, v in materiau.items() if k != "taux_perte"}
    cb.declarer_ok(journal, lignes=[cb.lignes()[0], sans_perte])


@pytest.mark.parametrize("auteur", [
    None, {}, {"personne": "agent.mathis", "role": "system_agent"}, {"personne": "client.x", "role": "client"},
    {"personne": "vendeur.fictif", "role": "seller"}, {"personne": "emp", "role": "employee"},
    {"personne": "", "role": "admin"}, {"personne": "x y", "role": "admin"},
    {"personne": "proprio", "role": "admin", "extra": 1}, "proprio",
])
def test_un_barème_n_est_jamais_declare_par_autre_chose_qu_un_proprietaire_ou_un_admin(auteur):
    journal = []
    _, verdict = bareme_registre.declarer_version(
        journal, bareme_id="bareme-fictif", version_attendue=0, lignes=cb.lignes(), date_effet=cb.JOUR_EFFET_V1,
        auteur=auteur, horodatage="2026-11-01T09:00:00+00:00")
    assert cb.code(verdict) == "REJ-BAREME-IDENTITE" and "jamais par un agent" in verdict["detail"]
    assert journal == []
    _, verdict = bareme_registre.valider_version(
        journal, bareme_id="bareme-fictif", version=1, auteur=auteur, horodatage="2026-11-01T09:00:00+00:00")
    assert cb.code(verdict) == "REJ-BAREME-IDENTITE"


def test_les_deux_roles_admis_peuvent_declarer():
    for auteur in (cb.PROPRIO, cb.ADMIN):
        cb.declarer_ok([], auteur=auteur)


def test_les_entrees_declarees_ne_sont_pas_modifiees_par_l_appel():
    journal = []
    lignes = cb.lignes()
    parametres = deepcopy(cb.PARAMETRES)
    avant = (deepcopy(lignes), deepcopy(parametres))
    cb.declarer_ok(journal, lignes=lignes, parametres=parametres)
    assert (lignes, parametres) == avant
    lu, _ = bareme_registre.lire_version(journal, "bareme-fictif", 1)
    lu["lignes"][0]["cout_unitaire_max"] = "999"
    relu, _ = bareme_registre.lire_version(journal, "bareme-fictif", 1)
    assert relu["lignes"][0]["cout_unitaire_max"] == "14.00"  # la copie rendue est indépendante du registre


# ------------------------------------------------------------------------------------------------- chaînage
def test_alterer_une_ligne_d_un_maillon_suivi_d_un_autre_est_detecte_et_bloque_l_usage():
    journal = []
    v1, v2 = _v1_v2(journal)
    journal[0]["lignes"][0]["cout_unitaire_max"] = "1.00"
    ok, raison = bareme_registre.verifier_chaine(journal)
    assert ok is False and "altéré" in raison
    _, verdict = bareme_registre.resoudre(journal, cb.ref(v2), cb.APRES_V2)
    assert cb.code(verdict) == "REJ-BAREME-ALTERE"
    _, verdict = cb.declarer(journal, version_attendue=2, date_effet=cb.JOUR_EFFET_V2)
    assert cb.code(verdict) == "REJ-BAREME-ALTERE"
    _, verdict = bareme_registre.lire_version(journal, "bareme-fictif", 1)
    assert cb.code(verdict) == "REJ-BAREME-ALTERE"
    _, verdict = bareme_registre.lister(journal)
    assert cb.code(verdict) == "REJ-BAREME-ALTERE"


def test_une_alteration_qui_garde_des_valeurs_valides_est_detectee_par_l_empreinte_seule():
    journal = []
    _v1_v2(journal)
    journal[0]["lignes"][0]["cout_unitaire_max"] = "15.00"  # encore valide (8,00 <= 15,00) : seule l'empreinte parle
    ok, raison = bareme_registre.verifier_chaine(journal)
    assert ok is False and "maillon 0" in raison


def test_reecrire_un_maillon_en_recalculant_seulement_sa_propre_empreinte_rompt_le_lien_du_suivant():
    journal = []
    _v1_v2(journal)
    journal[0]["lignes"][0]["cout_unitaire_max"] = "15.00"
    journal[0]["source_id"] = _encoder_canonique({k: v for k, v in journal[0].items() if k != "source_id"})
    ok, raison = bareme_registre.verifier_chaine(journal)
    assert ok is False and "maillon 1" in raison  # le maillon 1 cite encore l'ancienne empreinte du maillon 0


def test_retirer_ou_permuter_des_maillons_rompt_la_chaine():
    journal = []
    _v1_v2(journal)
    cb.declarer_ok(journal, bareme_id="b2")
    permute = [journal[1], journal[0], journal[2]]
    assert bareme_registre.verifier_chaine(permute)[0] is False
    assert bareme_registre.verifier_chaine([journal[0], journal[2]])[0] is False
    assert bareme_registre.verifier_chaine(journal[1:])[0] is False


def test_recalculer_les_empreintes_ne_masque_pas_un_invariant_viole():
    journal = []
    _v1_v2(journal)
    journal[1]["version"] = 5  # numéro hors séquence, empreintes recalculées
    _rechainer(journal)
    assert bareme_registre.verifier_chaine(journal)[0] is False
    journal = []
    _v1_v2(journal)
    journal[1]["auteur"] = {"personne": "agent", "role": "system_agent"}  # auteur non humain
    _rechainer(journal)
    assert bareme_registre.verifier_chaine(journal)[0] is False
    journal = []
    _v1_v2(journal)
    journal[1]["date_effet"] = "2026-10-01T00:00:00+00:00"  # effet antérieur à la version précédente
    _rechainer(journal)
    assert bareme_registre.verifier_chaine(journal)[0] is False
    journal = []
    cb.declarer_ok(journal)
    journal[0]["lignes"][0]["cout_unitaire_min"] = 8.0  # nombre JSON au lieu du texte
    _rechainer(journal)
    assert bareme_registre.verifier_chaine(journal)[0] is False


def test_un_maillon_aux_cles_inattendues_ou_un_type_inconnu_est_refuse():
    journal = []
    cb.declarer_ok(journal)
    journal[0]["extra"] = 1
    _rechainer(journal)
    assert bareme_registre.verifier_chaine(journal)[0] is False
    assert bareme_registre.verifier_chaine(["pas un dict"])[0] is False
    assert bareme_registre.verifier_chaine([{"type_entree": "autre"}])[0] is False


def test_la_limite_de_maillons_est_refusee_sans_ecrire(monkeypatch):
    journal = []
    cb.declarer_ok(journal)
    monkeypatch.setattr(bareme_registre, "MAX_MAILLONS", 1)
    _, verdict = cb.declarer(journal, version_attendue=1, date_effet=cb.JOUR_EFFET_V2)
    assert cb.code(verdict) == "REJ-BAREME-ALTERE" and "plein" in verdict["detail"]
    assert len(journal) == 1


# ------------------------------------------------------------------------------------------------------ lister
def test_lister_montre_les_versions_et_celle_en_vigueur_a_l_instant_donne():
    journal = []
    _v1_v2(journal)
    cb.declarer_ok(journal, bareme_id="autre-bareme")
    avant, _ = bareme_registre.lister(journal, cb.MAINTENANT)
    apres, _ = bareme_registre.lister(journal, cb.APRES_V2)
    assert [b["bareme_id"] for b in avant] == ["autre-bareme", "bareme-fictif"]
    assert {b["bareme_id"]: b["version_en_vigueur"] for b in avant} == {"autre-bareme": 1, "bareme-fictif": 1}
    assert {b["bareme_id"]: b["version_en_vigueur"] for b in apres} == {"autre-bareme": 1, "bareme-fictif": 2}
    sans_instant, _ = bareme_registre.lister(journal)
    assert all(b["version_en_vigueur"] is None for b in sans_instant)
    assert all("lignes" not in version for b in avant for version in b["versions"])


# -------------------------------------------------------------------------------------------------- compilation
def test_compiler_donne_le_bareme_du_moteur_avec_la_version_du_bareme_declare():
    journal = []
    v1 = cb.declarer_ok(journal)
    bareme, verdict = bareme_registre.compiler(v1, cb.SERVICE)
    assert verdict is None
    assert bareme["version"] == "bareme-fictif@v1" and bareme["unite"] == "pi2"
    poste = bareme["postes"][cb.SERVICE]
    assert (poste["cout_unitaire_min"], poste["cout_unitaire_mode"], poste["cout_unitaire_max"]) == (8.0, 10.0, 14.0)
    assert poste["duree_minutes_par_unite"] == Decimal("2.5")
    assert poste["materiaux"] == [
        {"materiau": "Revêtement fictif", "quantite_par_unite": "1.1", "unite": "pi2", "facteur_perte": "0.10"}]


def test_la_semantique_du_temps_est_declaree_ou_absente_jamais_devinee():
    from m3_estimation import trace_calibration_temps

    assert bareme_registre.SEMANTIQUE_TEMPS_QUALIFIEE == trace_calibration_temps._SEMANTIQUE_TEMPS_QUALIFIEE
    journal = []
    sans = cb.declarer_ok(journal)
    assert "semantique_temps" not in bareme_registre.compiler(sans, cb.SERVICE)[0]
    avec = cb.declarer_ok(journal, version_attendue=1, lignes=cb.lignes(semantique_temps="duree_ecoulee_intervention"))
    assert bareme_registre.compiler(avec, cb.SERVICE)[0]["semantique_temps"] == "duree_ecoulee_intervention"
    _, verdict = cb.declarer(journal, version_attendue=2, lignes=cb.lignes(semantique_temps="temps_facture"))
    assert cb.code(verdict) == "REJ-BAREME-INVALIDE" and "semantique_temps" in verdict["detail"]


def test_compiler_un_service_non_couvert_dit_quoi_declarer():
    journal = []
    v1 = cb.declarer_ok(journal)
    _, verdict = bareme_registre.compiler(v1, "extension")
    assert cb.code(verdict) == "REJ-BAREME-INCOMPLET"
    assert "extension" in verdict["detail"] and "ravalement" in verdict["detail"] and "révision" in verdict["detail"]


def test_la_version_compilee_change_avec_la_revision():
    journal = []
    v1, v2 = _v1_v2(journal)
    b1, _ = bareme_registre.compiler(v1, cb.SERVICE)
    b2, _ = bareme_registre.compiler(v2, cb.SERVICE)
    assert b1["version"] != b2["version"] and b1["postes"] != b2["postes"]


def test_tous_les_codes_de_refus_du_barème_sont_au_catalogue_ferme():
    for code_ in ("REJ-BAREME-REFERENCE-REQUISE", "REJ-BAREME-LIBRE-REFUSE", "REJ-BAREME-INTROUVABLE",
                  "REJ-BAREME-VERSION-INCONNUE", "REJ-BAREME-EMPREINTE-DIFFERENTE", "REJ-BAREME-A-VALIDER",
                  "REJ-BAREME-HORS-VIGUEUR", "REJ-BAREME-PERIME", "REJ-BAREME-INCOMPLET", "REJ-BAREME-INVALIDE",
                  "REJ-BAREME-REVISION-PERIMEE", "REJ-BAREME-IDENTITE", "REJ-BAREME-ALTERE"):
        assert verdicts.est_verdict(code_), code_


@pytest.mark.parametrize("jours, accepte", [(0, False), (1, True), (3650, True), (3651, False)])
def test_la_validite_d_une_mesure_est_bornee_a_un_jour_et_3650_jours(jours, accepte):
    parametres = deepcopy(cb.PARAMETRES)
    parametres["mesure"] = {"validite_jours": jours}
    resultat, verdict = cb.declarer([], parametres=parametres)
    assert (verdict is None) is accepte
    if not accepte:
        assert cb.code(verdict) == "REJ-BAREME-INVALIDE" and "validite_jours" in verdict["detail"]
