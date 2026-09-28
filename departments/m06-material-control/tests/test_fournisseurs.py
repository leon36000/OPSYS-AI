"""fournisseurs.py — PLAN T2.5 point 2 (M6.2). Module pur : `registre_cible` est une simple liste
Python en mémoire ici.

Les fournisseurs cités (Gentek, Royal Solution de Bâtiment, O.A.M., Kaycan — DEFINITION-PRODUIT.md
§7 M6, ``docs/departements/M6-audit.md`` §2) n'ont AUCUNE coordonnée réelle connue de ce dépôt :
les fixtures ci-dessous portent ``fictif: true`` (AGENTS.md, « Données inventées : les fixtures
portent fictif: true ») pour marquer explicitement que les courriels/téléphones sont des
PLACEHOLDERS de test, jamais des données réelles importées.
"""

from __future__ import annotations

from m6_material_control import fournisseurs

# Fixture explicitement marquée fictive (AGENTS.md) : nom réel du produit, coordonnées inventées
# pour le test seulement.
GENTEK = {
    "fictif": True,
    "fournisseur_id": "gentek",
    "nom": "Gentek",
    "courriel_commande": "commandes@gentek.exemple-fictif.test",
    "telephone": "514-555-0100",
    "categories_vendues": ["gouttieres", "revetement"],
}


def test_enregistrer_nominal_cree_le_fournisseur():
    registre: list[dict] = []
    fiche, verdict = fournisseurs.enregistrer_fournisseur(
        GENTEK["fournisseur_id"], GENTEK["nom"], "2026-01-01T00:00:00Z", registre,
        courriel_commande=GENTEK["courriel_commande"], telephone=GENTEK["telephone"],
        categories_vendues=GENTEK["categories_vendues"],
    )
    assert verdict is None
    assert fiche["fournisseur_id"] == "gentek"
    assert fiche["nom"] == "Gentek"
    assert fiche["courriel_commande"] == GENTEK["courriel_commande"]
    assert fiche["delai_habituel_jours"] is None  # jamais deviné, omis ici
    assert len(registre) == 1
    assert registre[0]["type_entree"] == "fournisseur_cree"


def test_enregistrer_champs_optionnels_omis_restent_none():
    registre: list[dict] = []
    fiche, verdict = fournisseurs.enregistrer_fournisseur("f1", "Fournisseur 1", "2026-01-01T00:00:00Z", registre)
    assert verdict is None
    assert fiche["courriel_commande"] is None
    assert fiche["telephone"] is None
    assert fiche["categories_vendues"] is None
    assert fiche["delai_habituel_jours"] is None
    assert fiche["format_commande_prefere"] is None


def test_enregistrer_id_vide_refuse_nomme():
    fiche, verdict = fournisseurs.enregistrer_fournisseur("", "Nom", "2026-01-01T00:00:00Z", [])
    assert fiche is None
    assert verdict["code"] == "REJ-FOURNISSEUR-ID-VIDE"


def test_enregistrer_nom_vide_refuse_nomme():
    fiche, verdict = fournisseurs.enregistrer_fournisseur("f1", "", "2026-01-01T00:00:00Z", [])
    assert fiche is None
    assert verdict["code"] == "REJ-FOURNISSEUR-NOM-VIDE"


def test_enregistrer_horodatage_vide_refuse_nomme():
    fiche, verdict = fournisseurs.enregistrer_fournisseur("f1", "Nom", "", [])
    assert fiche is None
    assert verdict["code"] == "REJ-FOURNISSEUR-HORODATAGE-VIDE"


def test_enregistrer_delai_negatif_refuse_nomme():
    fiche, verdict = fournisseurs.enregistrer_fournisseur(
        "f1", "Nom", "2026-01-01T00:00:00Z", [], delai_habituel_jours=-3
    )
    assert fiche is None
    assert verdict["code"] == "REJ-FOURNISSEUR-CHAMP-INVALIDE"


def test_enregistrer_categories_vendues_non_liste_refuse_nomme():
    fiche, verdict = fournisseurs.enregistrer_fournisseur(
        "f1", "Nom", "2026-01-01T00:00:00Z", [], categories_vendues="gouttieres"
    )
    assert fiche is None
    assert verdict["code"] == "REJ-FOURNISSEUR-CHAMP-INVALIDE"


def test_enregistrer_clef_interdite_refusee_nommee():
    # Frontière de domaine (DA-M6-03 ensemble #1) : une clé d'un AUTRE domaine glissée dans un
    # champ ne doit jamais traverser silencieusement — ici via fournisseur_id lui-même.
    fiche, verdict = fournisseurs.enregistrer_fournisseur(
        {"virement": "x"}, "Nom", "2026-01-01T00:00:00Z", []
    )
    assert fiche is None
    assert verdict["code"] == "REJ-FRONTIERE-VIOLEE"


def test_enregistrer_replay_identique_est_un_no_op():
    registre: list[dict] = []
    fournisseurs.enregistrer_fournisseur("f1", "Nom", "2026-01-01T00:00:00Z", registre, telephone="514-000-0000")
    fiche2, verdict = fournisseurs.enregistrer_fournisseur(
        "f1", "Nom", "2026-06-01T00:00:00Z", registre, telephone="514-000-0000"
    )
    assert verdict is None
    assert len(registre) == 1, "contenu identique -> aucun maillon supplémentaire"
    assert fiche2["telephone"] == "514-000-0000"


def test_enregistrer_correction_ajoute_un_maillon_de_mise_a_jour():
    registre: list[dict] = []
    fournisseurs.enregistrer_fournisseur("f1", "Nom", "2026-01-01T00:00:00Z", registre, telephone="514-000-0000")
    fiche2, verdict = fournisseurs.enregistrer_fournisseur(
        "f1", "Nom", "2026-06-01T00:00:00Z", registre, telephone="514-111-1111"
    )
    assert verdict is None
    assert len(registre) == 2
    assert registre[1]["type_entree"] == "fournisseur_maj"
    assert fiche2["telephone"] == "514-111-1111"
    assert fiche2["nom"] == "Nom", "un champ non corrigé reste visible (fusion, pas remplacement)"


def test_lire_fournisseur_inconnu_rend_none():
    assert fournisseurs.lire_fournisseur([], "inconnu") is None


def test_lister_fournisseurs_tri_deterministe():
    registre: list[dict] = []
    fournisseurs.enregistrer_fournisseur("royal", "Royal Solution de Bâtiment", "2026-01-01T00:00:00Z", registre)
    fournisseurs.enregistrer_fournisseur("gentek", "Gentek", "2026-01-01T00:00:00Z", registre)
    fournisseurs.enregistrer_fournisseur("oam", "O.A.M.", "2026-01-01T00:00:00Z", registre)
    fournisseurs.enregistrer_fournisseur("kaycan", "Kaycan", "2026-01-01T00:00:00Z", registre)
    liste = fournisseurs.lister_fournisseurs(registre)
    assert [f["fournisseur_id"] for f in liste] == ["gentek", "kaycan", "oam", "royal"]
