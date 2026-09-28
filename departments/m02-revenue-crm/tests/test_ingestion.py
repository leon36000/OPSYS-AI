import sys
import os
import copy
import inspect
import subprocess
from pathlib import Path
import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
_PKG = _SRC / "m2_revenue_crm"  # répertoire du paquet, pour les scans de sources
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m2_revenue_crm import encodage  # noqa: E402
from m2_revenue_crm import verdicts  # noqa: E402
from m2_revenue_crm import registre  # noqa: E402
from m2_revenue_crm import contrats  # noqa: E402
from m2_revenue_crm import frontieres  # noqa: E402
from m2_revenue_crm import ingestion  # noqa: E402
from m2_revenue_crm import doublons  # noqa: E402

SUPPRIMER = object()


def contrat_valide(**surcharges):
    """Construit un contrat LeadQualifie conforme aux sept champs, neuf à chaque appel.

    Chaque surcharge remplace la valeur du champ homonyme ; la valeur
    sentinelle SUPPRIMER retire le champ du dict ; toute clé inconnue est
    ajoutée telle quelle, ce qui permet de tester la liste blanche stricte.
    Aucune constante partagée n'est mutable : le dict et le contact imbriqué
    sont reconstruits intégralement à chaque appel.
    """
    contrat = {
        "lead_id": "lead-0001",
        "conversation_id": "conv-0001",
        "contact": {
            "nom": "Jeanne Dupont",
            "telephone": "06 12 34 56 78",
            "courriel": "jeanne.dupont@example.test",
        },
        "type_travaux": "renovation_totale",
        "ville": "Lille",
        "urgence_declaree": False,
        "canal": "telephone",
    }
    for cle, valeur in surcharges.items():
        if valeur is SUPPRIMER:
            contrat.pop(cle, None)
        else:
            contrat[cle] = valeur
    return contrat


class TestStructureListeBlanche:
    """Prouve que valider_structure applique la liste blanche stricte des sept champs."""

    def test_contrat_conforme_accepte(self):
        """Prouve qu'un contrat conforme aux sept champs est accepté avec un code vide."""
        ok, code = contrats.valider_structure(contrat_valide())
        assert ok is True, f"contrat conforme refusé à tort: ({ok!r}, {code!r})"
        assert code == "", f"un contrat accepté doit retourner un code vide, obtenu {code!r}"

    @pytest.mark.parametrize(
        "champ",
        ["lead_id", "conversation_id", "contact", "type_travaux", "ville",
         "urgence_declaree", "canal"],
        ids=["lead_id", "conversation_id", "contact", "type_travaux", "ville",
             "urgence_declaree", "canal"],
    )
    def test_champ_obligatoire_manquant_refuse(self, champ):
        """Prouve que l'absence de chacun des sept champs obligatoires est refusée."""
        ok, code = contrats.valider_structure(contrat_valide(**{champ: SUPPRIMER}))
        assert ok is False, f"contrat sans le champ {champ!r} accepté à tort"
        assert verdicts.est_verdict(code), (
            f"code hors catalogue pour champ {champ!r} manquant: {code!r}"
        )

    @pytest.mark.parametrize(
        "champ_inconnu",
        ["prix", "montant", "date_intervention", "source_utm"],
        ids=["prix", "montant", "date_intervention", "source_utm"],
    )
    def test_champ_inconnu_refuse(self, champ_inconnu):
        """Prouve que tout champ hors liste blanche est refusé, y compris le champ inoffensif."""
        ok, code = contrats.valider_structure(
            contrat_valide(**{champ_inconnu: "valeur-quelconque"})
        )
        assert ok is False, f"champ inconnu {champ_inconnu!r} accepté à tort"
        assert verdicts.est_verdict(code), (
            f"code hors catalogue pour champ inconnu {champ_inconnu!r}: {code!r}"
        )

    def test_type_travaux_hors_enum_refuse(self):
        """Prouve qu'un type_travaux hors de l'enum fermé est refusé."""
        ok, code = contrats.valider_structure(contrat_valide(type_travaux="plomberie"))
        assert ok is False, f"type_travaux hors enum accepté à tort: ({ok!r}, {code!r})"
        assert verdicts.est_verdict(code), f"code hors catalogue: {code!r}"

    def test_canal_hors_enum_refuse(self):
        """Prouve qu'un canal hors de l'enum fermé est refusé."""
        ok, code = contrats.valider_structure(contrat_valide(canal="fax"))
        assert ok is False, f"canal hors enum accepté à tort: ({ok!r}, {code!r})"
        assert verdicts.est_verdict(code), f"code hors catalogue: {code!r}"

    @pytest.mark.parametrize(
        "champ",
        ["ville", "lead_id", "conversation_id"],
        ids=["ville_vide", "lead_id_vide", "conversation_id_vide"],
    )
    def test_champ_vide_refuse(self, champ):
        """Prouve qu'une chaîne vide sur un champ requis est refusée, sans normalisation."""
        ok, code = contrats.valider_structure(contrat_valide(**{champ: ""}))
        assert ok is False, f"champ {champ!r} vide accepté à tort"
        assert verdicts.est_verdict(code), (
            f"code hors catalogue pour champ {champ!r} vide: {code!r}"
        )

    def test_contact_sans_aucune_coordonnee_refuse(self):
        """Prouve qu'un contact dont les trois coordonnées sont vides est refusé."""
        contact = {"nom": "", "telephone": "", "courriel": ""}
        ok, code = contrats.valider_structure(contrat_valide(contact=contact))
        assert ok is False, f"contact sans coordonnée accepté à tort: ({ok!r}, {code!r})"
        assert verdicts.est_verdict(code), f"code hors catalogue: {code!r}"

    @pytest.mark.parametrize(
        "cle",
        ["nom", "telephone", "courriel"],
        ids=["nom_seul", "telephone_seul", "courriel_seul"],
    )
    def test_contact_une_seule_coordonnee_accepte(self, cle):
        """Prouve qu'une seule coordonnée non vide parmi les trois suffit à valider contact."""
        contact = {"nom": "", "telephone": "", "courriel": ""}
        contact[cle] = "coordonnee-non-vide"
        ok, code = contrats.valider_structure(contrat_valide(contact=contact))
        assert ok is True, (
            f"contact avec seule coordonnée {cle!r} refusé à tort: ({ok!r}, {code!r})"
        )
        assert code == "", f"un contrat accepté doit retourner un code vide, obtenu {code!r}"

    @pytest.mark.parametrize(
        "valeur",
        [1, "true", None],
        ids=["entier_un", "chaine_true", "none"],
    )
    def test_urgence_declaree_non_booleen_refuse(self, valeur):
        """Prouve que seul le TYPE booléen est accepté : 1 == True en Python mais
        n'est pas un bool, et il en va de même pour "true" et pour None."""
        assert not isinstance(valeur, bool), (
            f"cas de test invalide, la valeur {valeur!r} est déjà un booléen"
        )
        ok, code = contrats.valider_structure(contrat_valide(urgence_declaree=valeur))
        assert ok is False, f"urgence_declaree={valeur!r} acceptée à tort (type non booléen)"
        assert verdicts.est_verdict(code), f"code hors catalogue: {code!r}"

    def test_urgence_declaree_vraie_acceptee(self):
        """Prouve que le booléen True est accepté, le défaut du helper étant False."""
        ok, code = contrats.valider_structure(contrat_valide(urgence_declaree=True))
        assert ok is True, f"urgence_declaree=True refusée à tort: ({ok!r}, {code!r})"
        assert code == "", f"un contrat accepté doit retourner un code vide, obtenu {code!r}"


    @pytest.mark.parametrize(
        "contrat_fautif, code_attendu",
        [
            (lambda: contrat_valide(**{"prix": 500}), "REJ-CONTRAT-INVALIDE"),
            (lambda: contrat_valide(lead_id=SUPPRIMER), "REJ-CHAMP-MANQUANT"),
            (lambda: contrat_valide(ville=""), "REJ-CHAMP-VIDE"),
            (lambda: contrat_valide(type_travaux="renovation"), "REJ-ENUM-INVALIDE"),
            (lambda: contrat_valide(canal="pigeon"), "REJ-ENUM-INVALIDE"),
            (lambda: contrat_valide(urgence_declaree=1), "REJ-CONTRAT-INVALIDE"),
        ],
        ids=[
            "champ_inconnu_prix",
            "champ_absent_lead_id",
            "chaine_vide_ville",
            "enum_invalide_type_travaux",
            "enum_invalide_canal",
            "non_bool_urgence",
        ],
    )
    def test_code_de_rejet_structurel_est_epingle(self, contrat_fautif, code_attendu):
        """Prouve que chaque faute structurelle leve exactement le verdict attendu,
        et surtout pas OK, empechant une mutation muette de REJ-X vers OK."""
        contrat = contrat_fautif()
        ok, code = contrats.valider_structure(contrat)
        assert not ok, f"La structure devrait etre invalide pour la faute {code_attendu}"
        assert code == code_attendu, (
            f"Faute testee : {code_attendu!r}, code obtenu : {code!r}"
        )
        assert code != "OK", (
            f"Le code de rejet {code_attendu!r} ne doit pas etre le code du succes OK."
        )

class TestFrontieresSurLesValeurs:
    """Prouve que l'inspection des frontières porte sur les valeurs, pas seulement les noms."""

    @pytest.mark.parametrize(
        "texte",
        [
            'devis 4500 €',
            '4 500,00 EUR',
            '1200$',
            '1 200 CAD',
            '350 dollars',
            'tarif de 80 euros',
            '85 €/m²',
            '45 €/h',
            'à partir de 900 €',
            'travaux le 12/08',
            'intervention le 2026-08-12',
            'chantier terminé demain',
            'livraison lundi prochain',
            'finis dans 3 jours',
            'devis 4500',
            'tarif 80',
            'prix 1200',
            'budget 15000',
            'livraison lundi.',
            'prix: 9 €',
            'tarif 80 EUR',
            'coût 100 dollars',
            'montant: 2000$',
            'budget total: 15000 euros',
            'intervention le 15/09',
            'travaux prévus le 12/08',
            'chantier demain',
            'facture 3500€',
            'total 500 dollars',
            'livraison prévue pour le 20/09',
        ],
        ids=[
            "devis_4500",
            "4_500_00_eur",
            "1200",
            "1_200_cad",
            "350_dollars",
            "tarif_de_80_euros",
            "85_m2",
            "45_h",
            "a_partir_de_900",
            "travaux_le_12_08",
            "intervention_le_2026_08_12",
            "chantier_termine_demain",
            "livraison_lundi_prochain",
            "finis_dans_3_jours",
            "devis_4500_2",
            "tarif_80",
            "prix_1200",
            "budget_15000",
            "livraison_lundi",
            "prix_9",
            "tarif_80_eur",
            "cout_100_dollars",
            "montant_2000",
            "budget_total_15000_euros",
            "intervention_le_15_09",
            "travaux_prevus_le_12_08",
            "chantier_demain",
            "facture_3500",
            "total_500_dollars",
            "livraison_prevue_pour_le_20_09",
        ],
    )
    def test_motif_interdit_detecte(self, texte):
        """Prouve que chaque valeur du corpus FIGÉ de violations est détectée."""
        saine, raison = frontieres.inspecter_valeur(texte)
        assert saine is False, (
            f"La valeur {texte!r} du corpus figé doit être détectée comme violation "
            f"de frontière, raison obtenue : {raison!r}"
        )
        assert raison, (
            f"La détection de {texte!r} doit être motivée, raison vide obtenue"
        )

    @pytest.mark.parametrize(
        "texte",
        [
            'Saint-Prix',
            'Rue du Mont-de-Piété',
            'Devismes',
            'Prix-lès-Mézières',
            '75011',
            '06 12 34 56 78',
            'appartement 3 pièces',
            'maison des années 1200',
            'nous vous rappelons demain',
            'travaux de rénovation',
            'chantier en cours',
            'intervention prévue',
            'pose de fenêtres',
            'livraison standard',
            'nom: Jean',
            'email: test@example.com',
            'adresse: 123 rue de Lyon',
            'description: peinture intérieure',
            'type de toit: ardoise',
            'question: devis gratuit?',
            'pas de prix',
            'merci',
            'disponible rapidement',
        ],
        ids=[
            "saint_prix",
            "rue_du_mont_de_piete",
            "devismes",
            "prix_les_mezieres",
            "75011",
            "06_12_34_56_78",
            "appartement_3_pieces",
            "maison_des_annees_1200",
            "nous_vous_rappelons_demain",
            "travaux_de_renovation",
            "chantier_en_cours",
            "intervention_prevue",
            "pose_de_fenetres",
            "livraison_standard",
            "nom_jean",
            "email_test_example_com",
            "adresse_123_rue_de_lyon",
            "description_peinture_interieure",
            "type_de_toit_ardoise",
            "question_devis_gratuit",
            "pas_de_prix",
            "merci",
            "disponible_rapidement",
        ],
    )
    def test_valeur_saine_acceptee(self, texte):
        """Prouve qu'aucune valeur légitime du corpus FIGÉ ne produit de faux positif."""
        saine, raison = frontieres.inspecter_valeur(texte)
        assert saine is True, (
            f"La valeur légitime {texte!r} du corpus figé ne doit pas être signalée, "
            f"raison obtenue : {raison!r}"
        )

    def test_prix_dissimule_dans_ville_detecte(self):
        """Prouve qu'un prix caché dans la valeur de ville est détecté au niveau contrat."""
        contrat = contrat_valide(ville="Lille, devis 4500 €")
        sain, raison = frontieres.inspecter_contrat(contrat)
        assert sain is False, (
            f"prix dissimulé dans ville non détecté: {contrat['ville']!r}"
        )
        assert raison, f"une raison non vide est exigée, obtenu {raison!r}"

    def test_prix_dissimule_dans_contact_detecte(self):
        """Prouve qu'un prix caché dans contact['nom'] est détecté malgré l'imbrication."""
        contact = {
            "nom": "Jeanne Dupont, tarif de 80 euros",
            "telephone": "06 12 34 56 78",
            "courriel": "jeanne.dupont@example.test",
        }
        contrat = contrat_valide(contact=contact)
        sain, raison = frontieres.inspecter_contrat(contrat)
        assert sain is False, "prix dissimulé dans contact['nom'] non détecté"
        assert raison, f"une raison non vide est exigée, obtenu {raison!r}"

    def test_contrat_sain_accepte(self):
        """Prouve qu'un contrat conforme dont toutes les valeurs sont saines passe l'inspection."""
        sain, raison = frontieres.inspecter_contrat(contrat_valide())
        assert sain is True, f"contrat sain rejeté à tort: {raison!r}"
        assert raison == "", (
            f"un contrat sain doit avoir une raison vide, obtenu {raison!r}"
        )

    def test_corpus_de_motifs_non_vides(self):
        """Prouve que les corpus publics sont des tuples non vides : un corpus vide
        rendrait tous les tests d'acceptation trivialement verts."""
        assert isinstance(frontieres.MOTIFS_MONETAIRES, tuple), (
            "MOTIFS_MONETAIRES doit être un tuple, obtenu "
            f"{type(frontieres.MOTIFS_MONETAIRES).__name__}"
        )
        assert isinstance(frontieres.MOTIFS_DATE_EXECUTION, tuple), (
            "MOTIFS_DATE_EXECUTION doit être un tuple, obtenu "
            f"{type(frontieres.MOTIFS_DATE_EXECUTION).__name__}"
        )
        assert len(frontieres.MOTIFS_MONETAIRES) > 0, (
            "MOTIFS_MONETAIRES est vide: les tests d'acceptation ne prouveraient rien"
        )
        assert len(frontieres.MOTIFS_DATE_EXECUTION) > 0, (
            "MOTIFS_DATE_EXECUTION est vide: les tests d'acceptation ne prouveraient rien"
        )

    @pytest.mark.parametrize("texte", [
        "travaux de rénovation",
        "chantier en cours",
        "intervention prévue",
        "nous vous rappelons demain",
        "disponible lundi",
        "le 12/08 nous vous rappellerons",
    ], ids=[
        "terme_renovation",
        "terme_chantier",
        "terme_intervention",
        "date_demain",
        "date_lundi",
        "date_12_08",
    ])
    def test_terme_execution_seul_ou_date_seule_sont_acceptes(self, texte):
        """Prouve que seul l’apparition conjointe d’un terme d’exécution et d’une date déclenche la détection."""
        est_saine, _ = frontieres.inspecter_valeur(texte)
        assert est_saine, f"Le texte '{texte}' doit être accepté car un seul élément (terme seul ou date seule) ne constitue pas une co-occurrence interdite"


class TestIngestionNominale:
    """Tests des cas nominaux de la fonction ingestion.ingerer."""

    def test_ingestion_valide_produit_accuse_sans_verdict(self):
        """Un contrat correctement formé, horodatage valide => accuse non nul, verdict absent."""
        contrat = contrat_valide()
        registre_neuf = registre.Registre()
        accuse, verdict = ingestion.ingerer(contrat, registre_neuf, "2026-06-15T10:00:00+02:00")
        assert verdict is None, "Un contrat valide ne doit pas produire de verdict"
        assert accuse is not None, "Un contrat valide doit produire un accusé"
        # Les 8 clés exactes (correctif d'audit PRD §2b : doublons_detectes ajoutée,
        # cf. TestDoublonsDetectesAIngestion pour la preuve du comportement).
        cles_attendues = {
            "lead_id", "ligne_id", "statut", "empreinte_contrat",
            "empreinte_maillon", "tete_chaine", "horodatage", "doublons_detectes",
        }
        assert set(accuse.keys()) == cles_attendues, (
            f"Clés de l'accusé non conformes : écart {set(accuse.keys()) ^ cles_attendues}"
        )
        assert accuse["statut"] == "nouveau", "CA-M2-01 : statut initial doit être 'nouveau'"
        assert accuse["lead_id"] == contrat["lead_id"], "Le lead_id ne doit pas être régénéré"
        assert accuse["doublons_detectes"] == [], (
            "aucun autre lead n'existe encore dans un registre neuf : la liste doit être vide"
        )

    def test_registre_augmente_et_maillon_conforme(self):
        """Après ingestion, le registre contient un maillon de type lead_ingere, chaîne valide."""
        contrat = contrat_valide()
        registre_neuf = registre.Registre()
        accuse, _ = ingestion.ingerer(contrat, registre_neuf, "2026-06-15T10:00:00+02:00")
        assert registre_neuf.taille() == 1, "Le registre doit contenir exactement un maillon"
        maillons = list(registre_neuf.lire())
        assert len(maillons) == 1
        maillon = maillons[0]
        assert maillon["type_entree"] == "lead_ingere", "Le maillon doit porter le type lead_ingere"
        assert accuse["tete_chaine"] == registre_neuf.tete(), "L'accusé doit référencer la tête exacte du registre"
        assert registre_neuf.valider_chaine(ancre=accuse["tete_chaine"]), (
            "La chaîne doit être valide avec la tête comme ancre"
        )

    def test_contrat_non_mute(self):
        """L'ingestion ne modifie jamais le contrat d'origine."""
        contrat = contrat_valide()
        contrat_original = copy.deepcopy(contrat)
        registre_neuf = registre.Registre()
        ingestion.ingerer(contrat, registre_neuf, "2026-06-15T10:00:00+02:00")
        assert contrat == contrat_original, "Le contrat d'origine a été muté – interdit"

    def test_enveloppe_stockee_contient_contrat_et_empreinte_recalculable(self):
        """Le registre conserve le contrat gelé et son empreinte, recalculable par l'appelant."""
        contrat = contrat_valide()
        registre_neuf = registre.Registre()
        ingestion.ingerer(contrat, registre_neuf, "2026-06-15T10:00:00+02:00")
        maillon = list(registre_neuf.lire())[0]
        assert maillon["contrat"] == contrat, "Le contrat gelé stocké ne correspond pas à l'original"
        assert maillon["empreinte_contrat"] == encodage.empreinte(contrat), (
            "L'empreinte stockée doit être recalculable via encodage.empreinte"
        )

    def test_deux_ingestions_distinctes_produisent_ligne_id_differents(self):
        """Deux contrats différents produisent des ligne_id distincts et une chaîne de taille 2."""
        registre_neuf = registre.Registre()
        contrat_a = contrat_valide(lead_id="lead-a")
        contrat_b = contrat_valide(lead_id="lead-b")
        acc_a, _ = ingestion.ingerer(contrat_a, registre_neuf, "2026-06-15T10:00:00+02:00")
        acc_b, _ = ingestion.ingerer(contrat_b, registre_neuf, "2026-06-15T11:00:00+02:00")
        assert registre_neuf.taille() == 2
        assert acc_a["ligne_id"] != acc_b["ligne_id"], "Deux ingestions distinctes doivent produire deux ligne_id différents"
        assert registre_neuf.valider_chaine(), "La chaîne de 2 maillons doit rester valide"


    def test_mutation_imbriquee_du_contrat_apres_ingestion_sans_effet(self):
        """Prouve qu'une copie profonde est utilisee a l'ingestion : une mutation
        en profondeur du contrat d'origine n'altere ni le registre ni la chaine,
        et l'empreinte de l'accuse scelle l'etat capture a l'ingestion, pas une
        reference vivante (mutation de deepcopy vers dict non detectee sinon)."""
        contrat = contrat_valide(
            contact={"nom": "Alice", "telephone": "0123456789", "courriel": "a@b.com"}
        )
        registre_cible = registre.Registre()
        accuse, verdict_ing = ingestion.ingerer(
            contrat, registre_cible, horodatage="2026-07-29T12:00:00+00:00"
        )
        assert accuse is not None, "L'ingestion nominale doit produire un accuse"
        assert verdict_ing is None, "Aucun verdict d'erreur attendu"

        capture_maillons = copy.deepcopy(registre_cible.lire())
        capture_contrat_original = copy.deepcopy(contrat)

        # mutation profonde apres ingestion
        contrat["contact"]["nom"] = "Bob"
        contrat["contact"]["telephone"] = "9876543210"

        etat_registre = registre_cible.lire()
        assert etat_registre == capture_maillons, (
            "La mutation imbriquee du contrat d'origine ne doit pas alterer le registre"
        )
        assert registre_cible.valider_chaine() is True, (
            "La chaine doit rester valide apres mutation du contrat d'origine"
        )
        assert accuse["empreinte_contrat"] == encodage.empreinte(capture_contrat_original), (
            "L'empreinte de l'accuse doit correspondre au contrat tel qu'il etait a l'ingestion, "
            "pas a sa version mutee post-lection."
        )

class TestDoublonsDetectesAIngestion:
    """Correctif d'audit (PRD §2b, parcours (b)) : à chaque ingestion, M2 doit
    comparer le nouveau lead aux leads déjà présents et SIGNALER un doublon
    probable — avant ce correctif, ingerer() n'appelait jamais doublons.detecter,
    et un doublon évident (même contact, fenêtre de 7 jours) passait inaperçu."""

    def test_contact_identique_dans_la_fenetre_est_detecte(self):
        """Deux leads au contact strictement identique, ingérés à moins de 7
        jours d'écart, doivent être signalés l'un à l'autre à l'ingestion du
        second (le premier n'a personne à détecter avant lui)."""
        reg = registre.Registre()
        contact = {"nom": "Jeanne Dupont", "telephone": "0612345678", "courriel": "jeanne@example.test"}
        contrat_a = contrat_valide(lead_id="dup-a", contact=contact)
        contrat_b = contrat_valide(lead_id="dup-b", contact=contact, ville="Nantes")
        acc_a, verdict_a = ingestion.ingerer(contrat_a, reg, "2026-06-15T08:00:00+00:00")
        assert verdict_a is None, f"Ingestion A échouée : {verdict_a}"
        assert acc_a["doublons_detectes"] == [], "A est le premier lead : rien à détecter avant lui"

        acc_b, verdict_b = ingestion.ingerer(contrat_b, reg, "2026-06-18T08:00:00+00:00")
        assert verdict_b is None, f"Ingestion B échouée : {verdict_b}"
        assert acc_b["doublons_detectes"] == ["dup-a"], (
            f"B doit détecter A comme doublon probable (contact identique, "
            f"3 jours d'écart) : obtenu {acc_b['doublons_detectes']}"
        )

    def test_hors_fenetre_de_7_jours_non_detecte(self):
        """Le même contact, mais ingéré à plus de 7 jours d'écart, n'est pas
        signalé : la fenêtre glissante doit être respectée par la détection à
        l'ingestion, comme par doublons.detecter directement."""
        reg = registre.Registre()
        contact = {"nom": "Paul Martin", "telephone": "0611112222", "courriel": "paul@example.test"}
        ingestion.ingerer(contrat_valide(lead_id="loin-a", contact=contact), reg, "2026-06-01T08:00:00+00:00")
        acc_b, verdict_b = ingestion.ingerer(
            contrat_valide(lead_id="loin-b", contact=contact), reg, "2026-06-20T08:00:00+00:00"
        )
        assert verdict_b is None
        assert acc_b["doublons_detectes"] == [], (
            "hors de la fenêtre de 7 jours calendaires, aucun signalement attendu"
        )

    def test_contacts_distincts_non_detectes(self):
        """Deux leads sans aucune similitude (contact distinct, ville et type de
        travaux différents) ne se signalent jamais l'un l'autre."""
        reg = registre.Registre()
        ingestion.ingerer(
            contrat_valide(lead_id="d1", ville="Lille", type_travaux="extension"), reg, "2026-06-15T08:00:00+00:00"
        )
        acc, verdict = ingestion.ingerer(
            contrat_valide(
                lead_id="d2",
                contact={"nom": "Autre Personne", "telephone": "0699999999", "courriel": "autre@example.test"},
                ville="Marseille",
                type_travaux="ravalement",
            ),
            reg, "2026-06-16T08:00:00+00:00",
        )
        assert verdict is None
        assert acc["doublons_detectes"] == []

    def test_doublons_detectes_coherent_avec_doublons_detecter(self):
        """La liste renvoyée par l'ingestion doit être exactement celle que
        doublons.detecter calculerait indépendamment sur le même registre
        (aucune divergence entre les deux chemins)."""
        reg = registre.Registre()
        contact = {"nom": "Zoé Simon", "telephone": "0600000000", "courriel": "zoe@example.test"}
        ingestion.ingerer(contrat_valide(lead_id="c1", contact=contact), reg, "2026-06-01T08:00:00+00:00")
        ingestion.ingerer(contrat_valide(lead_id="c2", contact=contact), reg, "2026-06-02T08:00:00+00:00")
        acc_c3, verdict = ingestion.ingerer(
            contrat_valide(lead_id="c3", contact=contact), reg, "2026-06-03T08:00:00+00:00"
        )
        assert verdict is None
        assert sorted(acc_c3["doublons_detectes"]) == sorted(doublons.detecter(reg, "c3"))
        assert sorted(acc_c3["doublons_detectes"]) == ["c1", "c2"]

    def test_detection_n_ecrit_aucun_maillon_supplementaire(self):
        """La détection est un READ pur (doublons.detecter) : ingerer() ne doit
        écrire QUE le maillon lead_ingere, jamais de doublon_signale — signaler
        un doublon reste une étape distincte, décidée par l'appelant/outil, pas
        automatique à l'intérieur de ingerer()."""
        reg = registre.Registre()
        contact = {"nom": "Marc Petit", "telephone": "0655554444", "courriel": "marc@example.test"}
        ingestion.ingerer(contrat_valide(lead_id="e1", contact=contact), reg, "2026-06-01T08:00:00+00:00")
        taille_avant = reg.taille()
        acc, verdict = ingestion.ingerer(contrat_valide(lead_id="e2", contact=contact), reg, "2026-06-02T08:00:00+00:00")
        assert verdict is None
        assert acc["doublons_detectes"] == ["e1"]
        assert reg.taille() == taille_avant + 1, (
            "seul le maillon lead_ingere de e2 doit être écrit, pas de doublon_signale automatique"
        )
        types_ecrits = {m.get("type_entree") for m in reg.lire()}
        assert "doublon_signale" not in types_ecrits


_SENTINELLE_HRDT = object()  # sentinelle distincte de toute valeur d’horodatage testable, y compris None

class TestIngestionRejets:
    """Tests des cas de rejet pour ingestion.ingerer, couvrant les quatre familles et l'ordre des contrôles."""

    CAS_REJET = [
        pytest.param(
            {"modif": {"lead_id": None}, "horodatage": _SENTINELLE_HRDT, "pre_ingere": False, "code": None, "description": "structure"},
            id="structure_fault"
        ),
        pytest.param(
            {"modif": {"ville": "Lille, devis 4500 €"}, "horodatage": _SENTINELLE_HRDT, "pre_ingere": False, "code": "REJ-FRONTIERE-VIOLEE", "description": "frontiere"},
            id="frontiere_fault"
        ),
        pytest.param(
            {"modif": {"lead_id": "unicite_dup"}, "horodatage": _SENTINELLE_HRDT, "pre_ingere": True, "code": "REJ-LEAD-DEJA-INGERE", "description": "unicite"},
            id="unicite_fault"
        ),
        pytest.param(
            {"modif": {}, "horodatage": "2026-13-45", "pre_ingere": False, "code": None, "description": "horodatage"},
            id="horodatage_invalide_1"
        ),
        pytest.param(
            {"modif": {}, "horodatage": "", "pre_ingere": False, "code": "REJ-HORODATAGE-INVALIDE", "description": "horodatage"},
            id="horodatage_invalide_2"
        ),
        pytest.param(
            {"modif": {}, "horodatage": None, "pre_ingere": False, "code": "REJ-HORODATAGE-INVALIDE", "description": "horodatage"},
            id="horodatage_invalide_3"
        ),
        pytest.param(
            {"modif": {}, "horodatage": "2026-07-26", "pre_ingere": False, "code": None, "description": "horodatage"},
            id="horodatage_invalide_4"
        ),
        pytest.param(
            {"modif": {"lead_id": "", "ville": "Lille, devis 4500 €"}, "horodatage": _SENTINELLE_HRDT, "pre_ingere": False, "code": None, "description": "structure+frontiere"},
            id="order_structure_frontiere"
        ),
        pytest.param(
            {"modif": {"ville": "Lille, devis 4500 €", "lead_id": "front_dup"}, "horodatage": _SENTINELLE_HRDT, "pre_ingere": True, "code": "REJ-FRONTIERE-VIOLEE", "description": "frontiere+reingestion"},
            id="order_frontiere_reingestion"
        ),
    ]

    @pytest.mark.parametrize("cas", CAS_REJET, ids=[p.id for p in CAS_REJET])
    def test_rejet_commun(self, cas):
        """Chaque situation de rejet respecte CA-M2-02 et l'ordre des contrôles."""
        modif = cas["modif"]
        horodatage_test = cas.get("horodatage", _SENTINELLE_HRDT)
        pre_ingere = cas["pre_ingere"]
        code_attendu = cas["code"]
        description = cas["description"]

        registre_neuf = registre.Registre()

        if pre_ingere:
            lead_id_pre = modif["lead_id"]
            contrat_pre = contrat_valide(lead_id=lead_id_pre)
            accuse_pre, verdict_pre = ingestion.ingerer(
                contrat_pre, registre_neuf, "2026-01-01T12:00:00+02:00"
            )
            assert accuse_pre is not None, f"Échec de l'ingestion préalable pour {description}"
            assert verdict_pre is None

        taille_avant = registre_neuf.taille()

        contrat_test = contrat_valide(**modif)
        if horodatage_test is not _SENTINELLE_HRDT:
            arg_horodatage = horodatage_test
        else:
            arg_horodatage = "2026-06-15T14:30:00+02:00"

        accuse, verdict = ingestion.ingerer(contrat_test, registre_neuf, arg_horodatage)

        # CA-M2-02 : aucun maillon écrit en cas de rejet
        assert accuse is None, f"{description} : accusé inattendu"
        assert verdict is not None, f"{description} : verdict manquant"
        assert verdicts.est_verdict(verdict["code"]), (
            f"{description} : code verdict invalide {verdict.get('code')}"
        )
        assert registre_neuf.taille() == taille_avant, (
            f"{description} : la taille du registre ne doit pas changer (était {taille_avant})"
        )

        if code_attendu is not None:
            assert verdict["code"] == code_attendu, (
                f"{description} : code attendu {code_attendu}, reçu {verdict['code']}"
            )

        if "frontiere" in description and "structure" in description:
            pass  # assertion dédiée plus bas

        if description == "structure+frontiere":
            assert verdict["code"] != "REJ-FRONTIERE-VIOLEE", (
                "Ordre structure+frontiere : le verdict doit être celui de structure, pas frontière"
            )

        if pre_ingere:
            assert registre_neuf.valider_chaine(), (
                f"{description} : la chaîne doit rester valide après le rejet"
            )

    def test_unicite_ignore_les_autres_types_dentree(self):
        """Preuve que le contrôle d'unicité d'ingestion ignore les maillons de type non-lead_ingere.
        Toute mutation qui retire le filtre sur le type rendrait ce test rouge.
        """
        r = registre.Registre()
        horodatage_alarme = "2026-01-01T00:00:00+00:00"
        entree_alerte = {
            "type_entree": "alerte",
            "horodatage": horodatage_alarme,
            "lead_id": "L1",
            "payload": {},
        }
        r.ajouter(entree_alerte)
        taille_avant = r.taille()

        accuse, verdict = ingestion.ingerer(
            contrat_valide(lead_id="L1"), r, "2026-01-01T00:00:05+00:00"
        )

        assert verdict is None, (
            f"Une alerte portant le même lead_id ne doit pas constituer une ré-ingestion. "
            f"Verdict reçu : {verdict}"
        )
        assert accuse is not None, "L'ingestion doit produire un accusé non nul."
        assert r.taille() == taille_avant + 1, (
            f"Le registre doit contenir exactement un maillon supplémentaire. "
            f"Taille avant : {taille_avant}, après : {r.taille()}"
        )
        assert r.valider_chaine() is True, "La chaîne d'audit doit rester intègre après l'ingestion."
        assert accuse["lead_id"] == "L1", (
            f"L'accusé doit conserver le lead_id d'origine. "
            f"Attendu : 'L1', obtenu : {accuse['lead_id']}"
        )



class TestInvariantsIngestion:
    """Tests des invariants architecturaux de ingestion.py et des modules associés."""

    CAS_EXACT_UN = [
        pytest.param({}, "2026-06-15T10:00:00+02:00", id="nominal"),
        pytest.param({"lead_id": None}, "2026-06-15T10:00:00+02:00", id="rejet_structure"),
        pytest.param({"prix": 500}, "2026-06-15T10:00:00+02:00", id="rejet_frontiere"),
        pytest.param({}, "2026-13-45", id="rejet_horodatage"),
    ]

    @pytest.mark.parametrize("surcharge,horodatage", CAS_EXACT_UN, ids=[p.id for p in CAS_EXACT_UN])
    def test_exactement_un_membre_non_nul(self, surcharge, horodatage):
        """ingerer retourne un couple dont exactement un membre est non nul."""
        contrat = contrat_valide(**surcharge)
        registre_neuf = registre.Registre()
        accuse, verdict = ingestion.ingerer(contrat, registre_neuf, horodatage)
        assert (accuse is None) ^ (verdict is None), (
            "Exactement un des deux (accusé, verdict) doit être non nul"
        )

    def test_un_seul_point_ecriture(self):
        """Le fichier ingestion.py n'utilise .ajouter( qu'à un seul endroit."""
        chemin_ingestion = Path(__file__).resolve().parents[1] / "src" / "m2_revenue_crm" / "ingestion.py"
        contenu = chemin_ingestion.read_text(encoding="utf-8")
        assert contenu, "Fichier ingestion.py vide"
        occurrences = contenu.count(".ajouter(")
        assert occurrences == 1, (
            f"Attendu exactement 1 occurrence de .ajouter(, trouvé {occurrences}"
        )

    @pytest.mark.parametrize("nom_fichier", ["contrats.py", "frontieres.py", "ingestion.py"])
    def test_aucun_reseau(self, nom_fichier):
        """Les sources n'importent aucun module réseau (socket, urllib, requests, http)."""
        chemin = Path(__file__).resolve().parents[1] / "src" / "m2_revenue_crm" / nom_fichier
        contenu = chemin.read_text(encoding="utf-8").lower()
        assert contenu, f"Fichier {nom_fichier} vide"
        for motif in ("import socket", "from urllib", "import requests", "import http"):
            assert motif not in contenu, f"import réseau détecté dans {nom_fichier} : {motif}"

    @pytest.mark.parametrize("nom_fichier", ["contrats.py", "frontieres.py", "ingestion.py"])
    def test_aucune_horloge_interne(self, nom_fichier):
        """Les sources n'utilisent pas datetime.now, time.time, date.today ni utcnow."""
        chemin = Path(__file__).resolve().parents[1] / "src" / "m2_revenue_crm" / nom_fichier
        contenu = chemin.read_text(encoding="utf-8").lower()
        assert contenu, f"Fichier {nom_fichier} vide"
        for appel in ("datetime.now", "time.time", "date.today", "utcnow"):
            assert appel not in contenu, f"Appel d'horloge détecté dans {nom_fichier} : {appel}"

    def test_determinisme_inter_processus(self):
        """La même ingestion exécutée dans des processus distincts produit le même ligne_id."""
        src_path = Path(__file__).resolve().parents[1] / "src" / "m2_revenue_crm"
        script = (
            "import sys, os, json\n"
            f"sys.path.insert(0, {str(src_path.parent)!r})\n"
            "from m2_revenue_crm import encodage, registre, contrats, frontieres, ingestion\n"
            "contrat = {\n"
            '    "lead_id": "det-001",\n'
            '    "conversation_id": "conv-001",\n'
            '    "contact": {"nom": "Test"},\n'
            '    "type_travaux": "renovation_totale",\n'
            '    "ville": "Paris",\n'
            '    "urgence_declaree": False,\n'
            '    "canal": "telephone"\n'
            "}\n"
            "r = registre.Registre()\n"
            'accuse, _ = ingestion.ingerer(contrat, r, "2026-06-15T14:30:00+02:00")\n'
            'print(accuse["ligne_id"])\n'
        )

        graines = ("0", "123", "456")
        sorties = []
        for graine in graines:
            env_mod = os.environ.copy()
            env_mod["PYTHONHASHSEED"] = graine
            # ajout du src au PYTHONPATH pour simplifier
            env_mod["PYTHONPATH"] = str(src_path)
            res = subprocess.run(
                [sys.executable, "-c", script],
                capture_output=True,
                text=True,
                env=env_mod,
            )
            sortie = res.stdout.strip()
            sorties.append(sortie)
            assert sortie, f"Sortie vide pour PYTHONHASHSEED={graine}"

        assert len(set(sorties)) == 1, (
            f"Les ligne_id diffèrent entre processus : {sorties}"
        )


class TestLeadStructureOptionnel:
    """PLAN T2.2 (lead structuré) : source/utm/campagne sont ACCEPTÉS s'ils sont fournis,
    VALIDÉS comme toute autre donnée, et jamais requis — leur absence n'est jamais une erreur ni
    une valeur par défaut inventée (audit du front office, docs/produit/DEFINITION-PRODUIT.md
    §6/§7)."""

    def test_absents_les_trois_contrat_toujours_accepte(self):
        """Un contrat sans source/utm/campagne (le contrat gelé v1 actuel) reste accepté à
        l'identique : ce sont des ajouts strictement additifs."""
        ok, code = contrats.valider_structure(contrat_valide())
        assert ok is True, f"contrat sans champs optionnels refusé à tort: ({ok!r}, {code!r})"
        assert code == ""

    def test_source_et_campagne_fournis_acceptes(self):
        ok, code = contrats.valider_structure(
            contrat_valide(source="google_ads", campagne="promo-printemps-2026")
        )
        assert ok is True, f"source/campagne valides refusés à tort: ({ok!r}, {code!r})"
        assert code == ""

    def test_utm_complet_fourni_accepte(self):
        utm = {
            "utm_source": "google",
            "utm_medium": "cpc",
            "utm_campaign": "fenetre-promo-printemps-2026",
            "utm_content": "annonce-a",
        }
        ok, code = contrats.valider_structure(contrat_valide(utm=utm))
        assert ok is True, f"utm complet refusé à tort: ({ok!r}, {code!r})"
        assert code == ""

    def test_utm_partiel_fourni_accepte(self):
        """Aucune sous-clé de utm n'est individuellement obligatoire : M2 n'est pas propriétaire
        de la taxonomie UTM (M7 l'est, docs/produit/DEFINITION-PRODUIT.md §8)."""
        ok, code = contrats.valider_structure(contrat_valide(utm={"utm_source": "facebook"}))
        assert ok is True, f"utm partiel refusé à tort: ({ok!r}, {code!r})"
        assert code == ""

    @pytest.mark.parametrize("champ", ["source", "campagne"], ids=["source_vide", "campagne_vide"])
    def test_source_ou_campagne_vide_refuse(self, champ):
        """Une chaîne vide n'est jamais silencieusement traitée comme une absence : le fournisseur
        doit soit donner une vraie valeur, soit omettre la clé (fail-closed, AGENTS.md)."""
        ok, code = contrats.valider_structure(contrat_valide(**{champ: ""}))
        assert ok is False, f"{champ} vide accepté à tort: ({ok!r}, {code!r})"
        assert code == "REJ-CONTRAT-INVALIDE"

    @pytest.mark.parametrize("champ", ["source", "campagne"], ids=["source_type", "campagne_type"])
    def test_source_ou_campagne_type_invalide_refuse(self, champ):
        ok, code = contrats.valider_structure(contrat_valide(**{champ: 42}))
        assert ok is False, f"{champ} de type entier accepté à tort: ({ok!r}, {code!r})"
        assert code == "REJ-CONTRAT-INVALIDE"

    def test_utm_dict_vide_refuse(self):
        ok, code = contrats.valider_structure(contrat_valide(utm={}))
        assert ok is False, f"utm={{}} accepté à tort: ({ok!r}, {code!r})"
        assert code == "REJ-CONTRAT-INVALIDE"

    def test_utm_type_invalide_refuse(self):
        ok, code = contrats.valider_structure(contrat_valide(utm="google"))
        assert ok is False, f"utm de type chaîne accepté à tort: ({ok!r}, {code!r})"
        assert code == "REJ-CONTRAT-INVALIDE"

    def test_utm_cle_inconnue_refusee(self):
        ok, code = contrats.valider_structure(contrat_valide(utm={"utm_source": "google", "utm_id": "abc"}))
        assert ok is False, f"utm avec clé inconnue accepté à tort: ({ok!r}, {code!r})"
        assert code == "REJ-CONTRAT-INVALIDE"

    def test_utm_sous_valeur_vide_refusee(self):
        ok, code = contrats.valider_structure(contrat_valide(utm={"utm_source": ""}))
        assert ok is False, f"utm_source vide accepté à tort: ({ok!r}, {code!r})"
        assert code == "REJ-CONTRAT-INVALIDE"

    def test_champ_manquant_obligatoire_prioritaire_sur_champ_optionnel_invalide(self):
        """L'ORDRE de validation (contrats.py) place les champs obligatoires (étape 2) avant les
        champs optionnels (étape 5) : un contrat qui cumule les deux fautes retourne le code de la
        faute obligatoire, jamais celui du champ optionnel."""
        contrat = contrat_valide(source="", ville=SUPPRIMER)
        ok, code = contrats.valider_structure(contrat)
        assert ok is False
        assert code == "REJ-CHAMP-MANQUANT", (
            f"attendu REJ-CHAMP-MANQUANT (ville absente, étape 2), obtenu {code!r}"
        )

    def test_lead_avec_champs_optionnels_ingere_et_conserve_tel_quel(self):
        """« garde-les » (PLAN T2.2) : ingestion.ingerer copie le contrat en entier — les champs
        optionnels fournis sont donc conservés tels quels dans le maillon lead_ingere, sans
        transformation ni perte."""
        r = registre.Registre()
        contrat = contrat_valide(
            lead_id="LS-1", source="referral", campagne="parrainage-2026",
            utm={"utm_source": "infolettre", "utm_medium": "courriel", "utm_campaign": "printemps-2026"},
        )
        accuse, verdict = ingestion.ingerer(contrat, r, "2026-06-15T10:00:00+00:00")
        assert verdict is None, f"ingestion refusée à tort : {verdict}"
        maillon = r.lire()[-1]
        assert maillon["contrat"]["source"] == "referral"
        assert maillon["contrat"]["campagne"] == "parrainage-2026"
        assert maillon["contrat"]["utm"]["utm_source"] == "infolettre"
