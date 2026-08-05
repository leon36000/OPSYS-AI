# audit/tests/test_contrats_rubrique.py
import copy
import unittest

from audit.contrats import valider_constat
from audit.rubrique import calculer_severite


def constat_valide() -> dict:
    return {
        "id": "AUD-A1-001",
        "lot": "A1",
        "classe": "defaut-code",
        "titre": "Le traitement ignore une erreur de retour.",
        "emplacement": ["audit/contrats.py:42"],
        "temoin": "reproduction.py",
        "temoin_rc": 1,
        "temoin_sortie_sha256": "a" * 64,
        "entrees_rubrique": {
            "frontiere_t3": False,
            "gate_couvrant": True,
            "rayon": 0,
            "contrat_gele": "",
        },
        "severite": "mineure",
        "statut": "ouvert",
        "refutation": {
            "cmd": "python reproduction.py",
            "sortie": "AssertionError",
            "conclusion": "Le défaut est reproduit.",
        },
        "assume_ref": None,
    }


def entrees(
    frontiere_t3: bool = False,
    gate_couvrant: bool = True,
    rayon: int = 0,
    contrat_gele: str = "",
) -> dict:
    return {
        "frontiere_t3": frontiere_t3,
        "gate_couvrant": gate_couvrant,
        "rayon": rayon,
        "contrat_gele": contrat_gele,
    }


class TestsContrats(unittest.TestCase):
    def test_constat_complet_valide_est_accepte(self) -> None:
        accepte, rejet = valider_constat(constat_valide())
        self.assertTrue(accepte, "un constat complet conforme doit être accepté")
        self.assertEqual(rejet, "", "un constat accepté ne doit porter aucun rejet")

    def test_chaque_champ_manquant_est_nomme(self) -> None:
        for champ in constat_valide():
            with self.subTest(champ=champ):
                constat = constat_valide()
                del constat[champ]
                accepte, rejet = valider_constat(constat)
                self.assertFalse(accepte, f"le champ manquant {champ} doit être rejeté")
                self.assertEqual(
                    rejet,
                    f"CONSTAT_CLE_MANQUANTE:{champ}",
                    f"le rejet doit nommer le champ manquant {champ}",
                )

    def test_chaque_champ_de_mauvais_type_est_nomme(self) -> None:
        valeurs_invalides = {
            "id": 1,
            "lot": 1,
            "classe": 1,
            "titre": 1,
            "emplacement": "fichier:1",
            "temoin": 1,
            "temoin_rc": "1",
            "temoin_sortie_sha256": 1,
            "entrees_rubrique": [],
            "severite": 1,
            "statut": 1,
            "refutation": [],
            "assume_ref": 1,
        }
        for champ, valeur in valeurs_invalides.items():
            with self.subTest(champ=champ):
                constat = constat_valide()
                constat[champ] = valeur
                accepte, rejet = valider_constat(constat)
                self.assertFalse(accepte, f"le type faux de {champ} doit être rejeté")
                self.assertIn(
                    champ.upper(),
                    rejet,
                    f"le rejet doit nommer le champ de type faux {champ}",
                )

    def test_chaque_champ_recoit_un_rejet_de_valeur_nomme(self) -> None:
        valeurs_invalides = {
            "id": "AUD-A8-001",
            "lot": "A8",
            "classe": "inconnue",
            "titre": "",
            "emplacement": [],
            "temoin": "",
            "temoin_rc": 0,
            "temoin_sortie_sha256": "z" * 64,
            "severite": "inconnue",
            "statut": "inconnu",
            "assume_ref": 1,
        }
        for champ, valeur in valeurs_invalides.items():
            with self.subTest(champ=champ):
                constat = constat_valide()
                constat[champ] = valeur
                accepte, rejet = valider_constat(constat)
                self.assertFalse(accepte, f"la valeur invalide de {champ} doit être rejetée")
                self.assertIn(
                    champ.upper(),
                    rejet,
                    f"le rejet doit nommer le champ de valeur invalide {champ}",
                )

    def test_entrees_rubrique_invalide_est_nommee(self) -> None:
        constat = constat_valide()
        constat["entrees_rubrique"]["rayon"] = -1
        accepte, rejet = valider_constat(constat)
        self.assertFalse(accepte, "un rayon négatif doit être rejeté")
        self.assertIn(
            "ENTREES_RUBRIQUE_RAYON",
            rejet,
            "le rejet doit nommer le rayon invalide",
        )

    def test_refutation_invalide_est_nommee(self) -> None:
        constat = constat_valide()
        constat["refutation"]["cmd"] = ""
        accepte, rejet = valider_constat(constat)
        self.assertFalse(accepte, "une réfutation vide doit être rejetée")
        self.assertIn(
            "REFUTATION_CMD",
            rejet,
            "le rejet doit nommer la valeur vide de réfutation",
        )

    def test_temoin_vert_est_rejete(self) -> None:
        constat = constat_valide()
        constat["temoin_rc"] = 0
        accepte, rejet = valider_constat(constat)
        self.assertFalse(accepte, "un témoin avec rc nul ne prouve aucun défaut")
        self.assertIn(
            "TEMOIN_RC",
            rejet,
            "le rejet doit identifier le code retour du témoin",
        )

    def test_sha256_de_63_caracteres_est_rejete(self) -> None:
        constat = constat_valide()
        constat["temoin_sortie_sha256"] = "a" * 63
        accepte, rejet = valider_constat(constat)
        self.assertFalse(accepte, "une empreinte de 63 caractères doit être rejetée")
        self.assertIn(
            "TEMOIN_SORTIE_SHA256",
            rejet,
            "le rejet doit identifier l'empreinte trop courte",
        )

    def test_sha256_de_65_caracteres_est_rejete(self) -> None:
        constat = constat_valide()
        constat["temoin_sortie_sha256"] = "a" * 65
        accepte, rejet = valider_constat(constat)
        self.assertFalse(accepte, "une empreinte de 65 caractères doit être rejetée")
        self.assertIn(
            "TEMOIN_SORTIE_SHA256",
            rejet,
            "le rejet doit identifier l'empreinte trop longue",
        )

    def test_sha256_avec_majuscule_est_rejete(self) -> None:
        constat = constat_valide()
        constat["temoin_sortie_sha256"] = "A" + ("a" * 63)
        accepte, rejet = valider_constat(constat)
        self.assertFalse(accepte, "une empreinte avec majuscule doit être rejetée")
        self.assertIn(
            "TEMOIN_SORTIE_SHA256",
            rejet,
            "le rejet doit identifier l'empreinte non minuscule",
        )

    def test_emplacement_vide_est_rejete(self) -> None:
        constat = constat_valide()
        constat["emplacement"] = []
        accepte, rejet = valider_constat(constat)
        self.assertFalse(accepte, "une liste d'emplacements vide doit être rejetée")
        self.assertIn(
            "EMPLACEMENT",
            rejet,
            "le rejet doit identifier l'emplacement absent",
        )

    def test_emplacement_sans_ligne_est_rejete(self) -> None:
        constat = constat_valide()
        constat["emplacement"] = ["fichier"]
        accepte, rejet = valider_constat(constat)
        self.assertFalse(accepte, "un emplacement sans ligne doit être rejeté")
        self.assertIn(
            "EMPLACEMENT_ELEMENT_0",
            rejet,
            "le rejet doit identifier l'élément d'emplacement invalide",
        )

    def test_titre_avec_grave_comme_mot_est_rejete(self) -> None:
        constat = constat_valide()
        constat["titre"] = "Le défaut est grave."
        accepte, rejet = valider_constat(constat)
        self.assertFalse(accepte, "grave comme mot entier doit être rejeté")
        self.assertIn(
            "TITRE_ADJECTIF_GRAVITE_INTERDIT",
            rejet,
            "le rejet doit nommer l'adjectif de gravité interdit",
        )

    def test_titre_avec_aggravation_est_accepte(self) -> None:
        constat = constat_valide()
        constat["titre"] = "L aggravation du délai révèle le défaut."
        accepte, rejet = valider_constat(constat)
        self.assertTrue(
            accepte,
            "aggravation est un autre mot et ne doit pas être confondu avec grave",
        )
        self.assertEqual(rejet, "", "le titre avec aggravation doit rester valide")

    def test_refutation_avec_une_valeur_vide_est_rejetee(self) -> None:
        for champ in ("cmd", "sortie", "conclusion"):
            with self.subTest(champ=champ):
                constat = constat_valide()
                constat["refutation"][champ] = ""
                accepte, rejet = valider_constat(constat)
                self.assertFalse(
                    accepte,
                    f"une valeur de réfutation vide dans {champ} doit être rejetée",
                )
                self.assertIn(
                    f"REFUTATION_{champ.upper()}",
                    rejet,
                    f"le rejet doit nommer la valeur vide {champ}",
                )

    def test_cle_en_trop_est_rejetee(self) -> None:
        constat = constat_valide()
        constat["champ_invente"] = "interdit"
        accepte, rejet = valider_constat(constat)
        self.assertFalse(accepte, "une clé supplémentaire doit être rejetée")
        self.assertEqual(
            rejet,
            "CONSTAT_CLE_EN_TROP:'champ_invente'",
            "le rejet doit nommer la clé supplémentaire",
        )


class TestsRubrique(unittest.TestCase):
    def test_sortie_indetermine_pour_entree_absente(self) -> None:
        severite, explication = calculer_severite({})
        self.assertEqual(
            severite,
            "indetermine",
            "une entrée absente doit empêcher toute estimation de sévérité",
        )
        self.assertEqual(
            explication,
            "entree_absente:frontiere_t3",
            "la raison doit nommer la première entrée absente",
        )

    def test_sortie_mineure(self) -> None:
        severite, explication = calculer_severite(entrees())
        self.assertEqual(
            severite,
            "mineure",
            "sans critère aggravant la sévérité doit être mineure",
        )
        self.assertEqual(
            explication,
            "regle_mineure:aucun_critere_aggravant",
            "l'explication doit nommer la règle mineure",
        )

    def test_critique_par_frontiere_t3(self) -> None:
        severite, explication = calculer_severite(entrees(frontiere_t3=True))
        self.assertEqual(
            severite,
            "critique",
            "une frontière T3 doit suffire à produire critique",
        )
        self.assertEqual(
            explication,
            "regle_critique:frontiere_t3",
            "l'explication doit nommer la disjonction frontière T3",
        )

    def test_critique_par_contrat_gele_et_rayon_deux(self) -> None:
        severite, explication = calculer_severite(
            entrees(rayon=2, contrat_gele="D-999")
        )
        self.assertEqual(
            severite,
            "critique",
            "un contrat gelé avec rayon deux doit produire critique",
        )
        self.assertEqual(
            explication,
            "regle_critique:contrat_gele_rayon_ge_2",
            "l'explication doit nommer la disjonction contrat gelé",
        )

    def test_critique_par_gate_non_couvrant_et_rayon_trois(self) -> None:
        severite, explication = calculer_severite(
            entrees(gate_couvrant=False, rayon=3)
        )
        self.assertEqual(
            severite,
            "critique",
            "un gate non couvrant avec rayon trois doit produire critique",
        )
        self.assertEqual(
            explication,
            "regle_critique:gate_non_couvrant_rayon_ge_3",
            "l'explication doit nommer la disjonction gate non couvrant",
        )

    def test_majeure_par_contrat_gele(self) -> None:
        severite, explication = calculer_severite(
            entrees(rayon=1, contrat_gele="D-999")
        )
        self.assertEqual(
            severite,
            "majeure",
            "un contrat gelé sous le seuil critique doit produire majeure",
        )
        self.assertEqual(
            explication,
            "regle_majeure:contrat_gele",
            "l'explication doit nommer la règle majeure par contrat",
        )

    def test_majeure_par_gate_non_couvrant(self) -> None:
        severite, explication = calculer_severite(
            entrees(gate_couvrant=False, rayon=1)
        )
        self.assertEqual(
            severite,
            "majeure",
            "un gate non couvrant avec rayon un doit produire majeure",
        )
        self.assertEqual(
            explication,
            "regle_majeure:gate_non_couvrant_rayon_ge_1",
            "l'explication doit nommer la règle majeure par gate",
        )

    def test_contrat_gele_d_999_est_resolvable_en_forme(self) -> None:
        severite, explication = calculer_severite(
            entrees(rayon=1, contrat_gele="D-999")
        )
        self.assertEqual(
            severite,
            "majeure",
            "D-999 doit être traité comme identifiant résolvable en forme",
        )
        self.assertNotEqual(
            explication,
            "contrat_gele_non_resolvable",
            "D-999 ne doit pas être traité comme contrat non résolvable",
        )

    def test_contrat_gele_bidule_est_indetermine(self) -> None:
        severite, explication = calculer_severite(
            entrees(rayon=1, contrat_gele="bidule")
        )
        self.assertEqual(
            severite,
            "indetermine",
            "un contrat gelé non résolvable ne doit jamais être deviné",
        )
        self.assertEqual(
            explication,
            "contrat_gele_non_resolvable",
            "la raison doit nommer le contrat non résolvable",
        )

    def test_seuil_contrat_gele_rayon_un_est_majeur(self) -> None:
        severite, _ = calculer_severite(entrees(rayon=1, contrat_gele="R-001"))
        self.assertEqual(
            severite,
            "majeure",
            "rayon un avec contrat gelé doit rester sous le seuil critique",
        )

    def test_seuil_contrat_gele_rayon_deux_est_critique(self) -> None:
        severite, _ = calculer_severite(entrees(rayon=2, contrat_gele="R-001"))
        self.assertEqual(
            severite,
            "critique",
            "rayon deux avec contrat gelé doit atteindre le seuil critique",
        )

    def test_seuil_gate_non_couvrant_rayon_deux_est_majeur(self) -> None:
        severite, _ = calculer_severite(
            entrees(gate_couvrant=False, rayon=2)
        )
        self.assertEqual(
            severite,
            "majeure",
            "rayon deux sans gate couvrant doit rester sous le seuil critique",
        )

    def test_seuil_gate_non_couvrant_rayon_trois_est_critique(self) -> None:
        severite, _ = calculer_severite(
            entrees(gate_couvrant=False, rayon=3)
        )
        self.assertEqual(
            severite,
            "critique",
            "rayon trois sans gate couvrant doit atteindre le seuil critique",
        )

    def test_type_invalide_ne_leve_pas_et_reste_indetermine(self) -> None:
        severite, explication = calculer_severite(
            entrees(frontiere_t3="oui")
        )
        self.assertEqual(
            severite,
            "indetermine",
            "un type invalide doit retourner indetermine sans exception",
        )
        self.assertEqual(
            explication,
            "type_invalide:frontiere_t3",
            "la raison doit distinguer le type invalide",
        )


if __name__ == "__main__":
    unittest.main()
