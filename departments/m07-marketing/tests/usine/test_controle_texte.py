"""Contrôle en code d'un texte public (PLAN T4.17) : chaque règle refuse en se nommant, un texte propre passe.

Module pur, sans base ni réseau. Données fictives : les noms, adresses et montants ci-dessous n'existent pas.
"""

from __future__ import annotations

import time

import pytest
from m7_marketing.usine import controle_texte as ct
from m7_marketing.usine.controle_texte import ContexteControle, controler_texte, motif_de_refus

FICTIF = True

TEXTES_PROPRES = [
    "Chantier terminé à Repentigny : gouttières et descentes.",
    "Notre équipe vient de terminer ce projet. Demandez votre soumission.",
    "Un projet semblable en tête ? Le lien pour demander une soumission est dans notre bio.",
    "Merci d'avoir confié vos travaux à l'équipe. Nous ne publierons rien sans votre accord explicite.",
    "Scène 1 : plan large du résultat final. Scène 2 : détail du travail terminé.",
    "Revêtement extérieur et soffite : un chantier soigné, du début à la fin.",
]

# (règle attendue, texte fautif) : chaque règle a ses propres cas, dont les formes qu'un modèle écrit vraiment.
CAS_REFUSES = [
    (ct.REGLE_TEXTE_VIDE, ""),
    (ct.REGLE_TEXTE_VIDE, "   \n "),
    (ct.REGLE_LIEN, "Voir notre site https://exemple-fictif.ca/soumission"),
    (ct.REGLE_LIEN, "Rendez-vous sur www.exemple-fictif.ca"),
    (ct.REGLE_LIEN, "Tout est sur exemple-fictif.ca pour vous"),
    (ct.REGLE_ADRESSE, "Gouttières installées au 1234 rue des Érables"),
    (ct.REGLE_ADRESSE, "Chantier au 12, boulevard Taschereau"),
    (ct.REGLE_ADRESSE, "Un beau chantier sur la rue Principale"),
    (ct.REGLE_ADRESSE, "Sur le chemin du Lac, tout est terminé"),
    (ct.REGLE_ADRESSE, "Chantier à Repentigny, J5Y 1A1"),
    (ct.REGLE_ADRESSE, "Chantier situé à 45.7500, -73.5000"),
    (ct.REGLE_ADRESSE, "Le chantier du 12 3e avenue est fini"),
    (ct.REGLE_ADRESSE, "Appartement 4 : soffite refait"),
    (ct.REGLE_COORDONNEES, "Écrivez à client.fictif@exemple-fictif.ca"),
    (ct.REGLE_COORDONNEES, "Appelez le 514 555 0199 dès maintenant"),
    (ct.REGLE_COORDONNEES, "Appelez le (450) 555-0100"),
    (ct.REGLE_NOM_CLIENT, "Merci à Mme Tremblay pour sa confiance"),
    (ct.REGLE_NOM_CLIENT, "Un chantier pour Monsieur Gagnon, satisfait du résultat"),
    (ct.REGLE_NOM_CLIENT, "Merci à la famille Bouchard"),
    (ct.REGLE_NOM_CLIENT, "Terminé chez Jean Tremblay hier"),
    (ct.REGLE_NOM_CLIENT, "Client : Tremblay"),
    (ct.REGLE_NOM_CLIENT, "Merci à @tremblay_fictif pour la confiance"),
    (ct.REGLE_PRIX, "Gouttières à partir de 4 500 $"),
    (ct.REGLE_PRIX, "Un chantier à 850$ seulement"),
    (ct.REGLE_PRIX, "Une soumission de 2500 dollars"),
    (ct.REGLE_PRIX, "Soumission gratuite pour tous"),
    (ct.REGLE_PRIX, "Profitez de notre rabais du printemps"),
    (ct.REGLE_PRIX, "Nos prix sont compétitifs"),
    (ct.REGLE_PRIX, "Un tarif honnête"),
    (ct.REGLE_PRIX, "Financement disponible"),
    (ct.REGLE_CHIFFRE, "Nous avons posé 150 pieds de gouttières"),
    (ct.REGLE_CHIFFRE, "Terminé en 4 heures"),
    (ct.REGLE_CHIFFRE, "25 ans d'expérience"),
    (ct.REGLE_CHIFFRE, "Une économie de 30 % sur le chauffage"),
    (ct.REGLE_GARANTIE, "Travail garanti"),
    (ct.REGLE_GARANTIE, "Une garantie à vie sur la main-d'œuvre"),
    (ct.REGLE_GARANTIE, "Satisfait ou remboursé"),
    (ct.REGLE_GARANTIE, "Aucun risque pour vous"),
    (ct.REGLE_DATE, "Terminé le 15 septembre"),
    (ct.REGLE_DATE, "Livraison prévue le 2026-10-05"),
    (ct.REGLE_DATE, "Rendez-vous le 3/10"),
    (ct.REGLE_DATE, "Nous serons là demain"),
    (ct.REGLE_DATE, "On revient la semaine prochaine"),
    (ct.REGLE_DATE, "Terminé d'ici lundi"),
    (ct.REGLE_DATE, "Dans 3 jours, votre toit sera prêt"),
    (ct.REGLE_DATE, "Au plus tard vendredi"),
    (ct.REGLE_DATE, "Chantier fini le samedi"),
    (ct.REGLE_DATE, "Disponible dès lundi"),
    (ct.REGLE_EXAGERATION, "Le meilleur service au Québec"),
    (ct.REGLE_EXAGERATION, "Numéro 1 des gouttières"),
    (ct.REGLE_EXAGERATION, "Des prix imbattables"),
    (ct.REGLE_EXAGERATION, "Un résultat parfait"),
    (ct.REGLE_EXAGERATION, "Client 100 % satisfait"),
    (ct.REGLE_EXAGERATION, "Le leader de la rénovation"),
]


@pytest.mark.parametrize("texte", TEXTES_PROPRES)
def test_un_texte_propre_est_accepte(texte):
    assert controler_texte(texte) == ()


@pytest.mark.parametrize(("regle", "texte"), CAS_REFUSES)
def test_chaque_regle_refuse_son_texte_et_se_nomme(regle, texte):
    violations = controler_texte(texte)
    assert regle in {v.regle for v in violations}, (texte, violations)
    assert all(v.detail for v in violations)  # jamais un refus muet : il dit quoi retirer


def test_toutes_les_regles_sont_couvertes_et_decrites():
    """Une règle sans cas de refus ne serait pas prouvée ; une règle sans libellé ne se lirait pas. La longueur et
    l'identifiant interne dépendent du contexte : leurs cas sont plus bas."""
    dependantes_du_contexte = {ct.REGLE_LONGUEUR, ct.REGLE_IDENTIFIANT_INTERNE}
    assert {regle for regle, _ in CAS_REFUSES} == set(ct.LIBELLES_REGLES) - dependantes_du_contexte
    assert all(libelle for libelle in ct.LIBELLES_REGLES.values())


def test_une_regle_ne_declenche_pas_les_autres_sur_un_cas_simple():
    """Le refus nomme la BONNE règle : « meilleur » n'est ni un prix ni une adresse."""
    assert {v.regle for v in controler_texte("Le meilleur service")} == {ct.REGLE_EXAGERATION}
    assert {v.regle for v in controler_texte("Un tarif honnête")} == {ct.REGLE_PRIX}
    assert {v.regle for v in controler_texte("Terminé demain")} == {ct.REGLE_DATE}
    assert {v.regle for v in controler_texte("Travail garanti")} == {ct.REGLE_GARANTIE}


def test_plusieurs_regles_violees_sont_toutes_nommees_dans_l_ordre():
    violations = controler_texte("Terminé demain au 12 rue Principale, à partir de 500 $, garanti")
    regles = [v.regle for v in violations]
    assert regles == [ct.REGLE_ADRESSE, ct.REGLE_PRIX, ct.REGLE_GARANTIE, ct.REGLE_DATE]
    motif = motif_de_refus(violations)
    for regle in regles:
        assert regle in motif


def test_motif_de_refus_est_vide_sans_violation():
    assert motif_de_refus(()) == ""


def test_un_texte_qui_n_est_pas_une_chaine_est_une_erreur_de_programmation():
    with pytest.raises(TypeError):
        controler_texte(None)  # type: ignore[arg-type]


# -- le contexte : marque, garanties validées, identifiants, longueur ----------------------------------------------
def test_une_garantie_validee_par_l_entreprise_passe_mot_pour_mot():
    validee = "Garantie limitée de la main-d'œuvre, selon le contrat"
    contexte = ContexteControle(garanties_validees=(validee,))
    assert controler_texte(f"Un chantier soigné. {validee}.", contexte) == ()
    # Sans le contexte, la même phrase est refusée : c'est le profil qui la valide, jamais le texte.
    assert ct.REGLE_GARANTIE in {v.regle for v in controler_texte(f"Un chantier soigné. {validee}.")}


def test_une_garantie_validee_ne_couvre_pas_une_autre_garantie():
    contexte = ContexteControle(garanties_validees=("Garantie limitée de la main-d'œuvre",))
    violations = controler_texte("Garantie limitée de la main-d'œuvre, et garantie à vie sur tout", contexte)
    assert ct.REGLE_GARANTIE in {v.regle for v in violations}


def test_le_nom_de_marque_ne_fait_pas_une_promesse():
    """Un nom commercial peut contenir « Garantie » ou « Meilleur » ; le texte n'en fait pas une promesse."""
    contexte = ContexteControle(noms_de_marque=("Toitures Garantie Meilleur Prix Inc.",))
    assert controler_texte("L'équipe de Toitures Garantie Meilleur Prix Inc. a terminé ce projet.", contexte) == ()
    assert controler_texte("L'équipe de Toitures Garantie Meilleur Prix Inc. a terminé ce projet.") != ()


def test_le_masque_de_marque_ne_cache_que_la_marque():
    contexte = ContexteControle(noms_de_marque=("Toitures Garantie Inc.",))
    violations = controler_texte("Toitures Garantie Inc. : travail garanti", contexte)
    assert {v.regle for v in violations} == {ct.REGLE_GARANTIE}


def test_un_nom_de_marque_precede_de_chez_n_est_pas_un_nom_de_client():
    contexte = ContexteControle(noms_de_marque=("Gouttières Synergy",))
    assert controler_texte("Chantier terminé chez Gouttières Synergy", contexte) == ()


def test_un_nom_fourni_comme_confidentiel_est_refuse():
    contexte = ContexteControle(noms_clients=("Tremblay",))
    violations = controler_texte("Un chantier pour tremblay, satisfait", contexte)
    assert ct.REGLE_NOM_CLIENT in {v.regle for v in violations}
    assert controler_texte("Un chantier de tremblayette", contexte) == ()  # mot entier seulement


def test_un_identifiant_interne_est_refuse():
    contexte = ContexteControle(identifiants=("lead-4711", "wct-9f8e7d6c"))
    assert ct.REGLE_IDENTIFIANT_INTERNE in {v.regle for v in controler_texte("Dossier LEAD-4711 terminé", contexte)}
    assert ct.REGLE_IDENTIFIANT_INTERNE in {v.regle for v in controler_texte("Ref wct-9f8e7d6c", contexte)}
    assert controler_texte("Dossier terminé", contexte) == ()


def test_un_identifiant_trop_court_n_est_jamais_cherche():
    """« et » comme identifiant refuserait tout texte français : sous quatre caractères, on ne cherche pas."""
    contexte = ContexteControle(identifiants=("et", "de"), noms_clients=("un",))
    assert controler_texte("Gouttières et descentes, un travail de qualité", contexte) == ()


def test_la_longueur_maximale_de_la_plateforme_est_controlee():
    contexte = ContexteControle(longueur_max=20)
    violations = controler_texte("x" * 21, contexte)
    assert [v.regle for v in violations] == [ct.REGLE_LONGUEUR]
    assert controler_texte("x" * 20, contexte) == ()
    assert controler_texte("x" * 500) == ()  # sans plafond, pas de contrôle de longueur


def test_le_controle_ne_depend_ni_des_accents_ni_des_espaces_insecables():
    """Un montant écrit avec une espace insécable, ou « gratuité » sans accent, ne passe pas plus qu'un autre."""
    assert ct.REGLE_PRIX in {v.regle for v in controler_texte("À partir de 4 500 $")}
    assert ct.REGLE_GARANTIE in {v.regle for v in controler_texte("TRAVAIL GARANTI")}
    assert ct.REGLE_DATE in {v.regle for v in controler_texte("Terminé DEMAIN")}


def test_le_contrat_est_deterministe():
    texte = "Terminé demain au 12 rue Principale, à partir de 500 $"
    assert controler_texte(texte) == controler_texte(texte)


def test_un_texte_demesure_est_refuse_sans_etre_lu_par_les_motifs():
    texte = "1 2 3 4 " * 2000
    violations = controler_texte(texte)
    assert [v.regle for v in violations] == [ct.REGLE_LONGUEUR]
    assert str(ct.TEXTE_MAX_CONTROLE) in violations[0].detail


@pytest.mark.parametrize("texte", ["1" * 4900, "1 " * 2450, "a" * 4900, "@" * 4900, "chez " + "Ab " * 1600])
def test_le_controle_reste_rapide_sur_des_textes_pathologiques_sous_le_plafond(texte):
    debut = time.perf_counter()
    controler_texte(texte)
    assert time.perf_counter() - debut < 0.5  # linéaire : la version quadratique prenait plus d'une seconde


def test_les_montants_sont_toujours_reconnus_apres_le_durcissement_des_motifs():
    montants = (
        "4 500 $", "500$", "12,50 $", "5.000 dollars", "Total : 1 234,56 CAD", "x 1 1 1 $", "2500 piastres", "18 €",
        "$500 seulement", "Un total de $ 4 500", "€20 l'heure",  # le symbole devant le nombre
    )
    for texte in montants:
        assert ct.REGLE_PRIX in {v.regle for v in controler_texte(texte)}, texte
    assert controler_texte("Scène 1 : plan large. Scène 2 : détail.") == ()
