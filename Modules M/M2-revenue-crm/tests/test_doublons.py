import sys
import copy
import inspect
import ast
from pathlib import Path
import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import encodage  # noqa: E402
import verdicts  # noqa: E402
import registre  # noqa: E402
import ingestion  # noqa: E402
import doublons  # noqa: E402


# ------------------------------------------------------------------- helpers
def _contrat_base():
    """Contrat minimal valide pour l'ingestion."""
    return {
        "lead_id": "lead-unique-1",
        "conversation_id": "conv-123",
        "contact": {"nom": "Dupont", "telephone": "0123456789", "courriel": "a@b.com"},
        "type_travaux": "renovation_totale",
        "ville": "Paris",
        "urgence_declaree": True,
        "canal": "telephone",
    }


def ingerer_lead(reg, lead_id, horodatage, **surcharges_contrat):
    """Ingère un lead dans le registre et vérifie le succès.
    Retourne l'accusé reçu."""
    contrat = _contrat_base()
    contrat.update(surcharges_contrat)
    contrat["lead_id"] = lead_id
    accuse, verdict = ingestion.ingerer(contrat, reg, horodatage)
    assert accuse is not None, f"Ingestion échouée pour {lead_id}"
    assert verdict is None, f"Verdict inattendu : {verdict}"
    return accuse


# ------------------------------------------------------------------- tests
class TestDetectionCritere:
    """Critère de rapprochement : contact identique ou (ville + type_travaux)."""

    def test_contact_identique_detecte(self):
        """Deux leads avec le même contact sont détectés comme doublons."""
        reg = registre.Registre()
        h1 = "2026-03-01T10:00:00+00:00"
        h2 = "2026-03-01T11:00:00+00:00"
        ingerer_lead(reg, "L1", h1, contact={"nom": "Jean", "telephone": "06", "courriel": ""})
        ingerer_lead(reg, "L2", h2, contact={"nom": "Jean", "telephone": "06", "courriel": ""})
        resultat = doublons.detecter(reg, "L2")
        assert "L1" in resultat, "Le doublon par contact identique n'a pas été détecté."

    def test_ville_et_travaux_identiques_detecte(self):
        """Même ville et même type de travaux avec contacts différents -> détecté."""
        reg = registre.Registre()
        h = "2026-03-02T09:00:00+00:00"
        ingerer_lead(reg, "LA", h, ville="Lyon", type_travaux="isolation_thermique",
                     contact={"nom": "A", "telephone": "01", "courriel": ""})
        ingerer_lead(reg, "LB", h, ville="Lyon", type_travaux="isolation_thermique",
                     contact={"nom": "B", "telephone": "02", "courriel": ""})
        resultat = doublons.detecter(reg, "LB")
        assert "LA" in resultat, "Le doublon par ville+travaux n'a pas été détecté."

    def test_ville_identique_travaux_different_non_detecte(self):
        """Même ville mais type de travaux différent -> pas de détection."""
        reg = registre.Registre()
        h = "2026-03-03T12:00:00+00:00"
        ingerer_lead(reg, "C1", h, ville="Nice", type_travaux="ravalement",
                     contact={"nom": "X", "telephone": "00", "courriel": ""})
        ingerer_lead(reg, "C2", h, ville="Nice", type_travaux="isolation_thermique",
                     contact={"nom": "Y", "telephone": "99", "courriel": ""})
        resultat = doublons.detecter(reg, "C2")
        assert resultat == [], "La conjonction ville+travaux n'étant pas satisfaite, aucun doublon ne doit être retourné."

    def test_travaux_identique_ville_differente_non_detecte(self):
        """Même type de travaux mais ville différente -> pas de détection."""
        reg = registre.Registre()
        h = "2026-03-04T08:00:00+00:00"
        ingerer_lead(reg, "D1", h, ville="Paris", type_travaux="ravalement",
                     contact={"nom": "P1", "telephone": "1", "courriel": ""})
        ingerer_lead(reg, "D2", h, ville="Marseille", type_travaux="ravalement",
                     contact={"nom": "P2", "telephone": "2", "courriel": ""})
        resultat = doublons.detecter(reg, "D2")
        assert resultat == [], "Villes différentes ne doivent pas déclencher la détection."

    def test_rien_en_commun_non_detecte(self):
        """Contacts, ville et travaux différents -> aucun doublon."""
        reg = registre.Registre()
        h = "2026-03-05T10:00:00+00:00"
        ingerer_lead(reg, "E1", h, contact={"nom": "Alice", "telephone": "10", "courriel": ""},
                     ville="Bordeaux", type_travaux="autre")
        ingerer_lead(reg, "E2", h, contact={"nom": "Bob", "telephone": "20", "courriel": ""},
                     ville="Lille", type_travaux="renovation_totale")
        resultat = doublons.detecter(reg, "E2")
        assert resultat == [], "Aucun critère commun, liste vide attendue."

    def test_ne_retourne_jamais_lead_lui_meme(self):
        """Un seul lead dans le registre : detecter sur lui-même doit renvoyer []."""
        reg = registre.Registre()
        h = "2026-03-01T12:00:00+00:00"
        ingerer_lead(reg, "UNIQUE", h)
        resultat = doublons.detecter(reg, "UNIQUE")
        assert resultat == [], "Un lead ne doit pas être son propre doublon."

    def test_critere_prioritaire_contact_identique(self):
        """Quand les deux critères s'appliquent, le signalement utilise 'contact_identique'."""
        reg = registre.Registre()
        h = "2026-03-06T10:00:00+00:00"
        contact = {"nom": "Meme", "telephone": "123", "courriel": ""}
        ingerer_lead(reg, "F1", h, contact=contact, ville="Nantes", type_travaux="extension")
        ingerer_lead(reg, "F2", h, contact=contact, ville="Nantes", type_travaux="extension")
        signalement, verdict = doublons.signaler(reg, "F1", "F2", h)
        assert signalement is not None
        assert verdict is None
        assert signalement["critere"] == "contact_identique", "Le critère le plus fort doit être retenu."

    def test_detecter_lead_inconnu_retourne_vide(self):
        """Prouve que detecter retourne une liste vide lorsque le lead cible est inexistant dans le reg."""
        reg = registre.Registre()
        horodatage = "2025-01-15T12:00:00+01:00"
        ingerer_lead(reg, "real-lead", horodatage, contact={"nom": "Client", "telephone": "", "courriel": "hello@test.com"})
        result = doublons.detecter(reg, "INCONNU")
        assert result == []


class TestFenetreGlissante:
    """Validation de la fenêtre glissante de 7 jours calendaires (bord inclus)."""

    @pytest.mark.parametrize(
        "date1, date2, attendu",
        [
            ("2026-01-01T10:00:00+00:00", "2026-01-08T10:00:00+00:00", True),      # J et J+7 exact
            ("2026-01-01T10:00:00+00:00", "2026-01-09T10:00:00+00:00", False),     # J+8 -> hors
            ("2026-03-01T23:00:00+00:00", "2026-03-08T01:00:00+00:00", True),      # 7 jours calendaires
            ("2026-03-01T01:00:00+00:00", "2026-03-09T01:00:00+00:00", False),     # J+8 calendaire
        ],
        ids=[
            "bord_inclus_J_plus_7",
            "bord_exclus_J_plus_8",
            "calendaires_7_jours_avec_heures",
            "calendaires_8_jours",
        ],
    )
    def test_fenetre_bords(self, date1, date2, attendu):
        """Teste l'inclusion/exclusion aux bords de la fenêtre de 7 jours."""
        reg = registre.Registre()
        ingerer_lead(reg, "A1", date1, contact={"nom": "Test", "telephone": "1", "courriel": ""},
                     ville="TEST", type_travaux="extension")
        ingerer_lead(reg, "A2", date2, contact={"nom": "Test", "telephone": "1", "courriel": ""},
                     ville="TEST", type_travaux="extension")
        resultat = doublons.detecter(reg, "A2")
        if attendu:
            assert "A1" in resultat, f"Le doublon devrait être détecté entre {date1} et {date2}."
        else:
            assert resultat == [], f"Aucun doublon ne doit être détecté entre {date1} et {date2}."

    def test_fenetre_nulle(self):
        """Deux leads ingérés au même instant sont dans la fenêtre (0 jour)."""
        reg = registre.Registre()
        h = "2026-05-05T12:00:00+00:00"
        ingerer_lead(reg, "M1", h, contact={"nom": "X", "telephone": "x", "courriel": ""},
                     ville="X", type_travaux="renovation_totale")
        ingerer_lead(reg, "M2", h, contact={"nom": "X", "telephone": "x", "courriel": ""},
                     ville="X", type_travaux="renovation_totale")
        resultat = doublons.detecter(reg, "M2")
        assert "M1" in resultat, "Même instant doit être considéré comme dans la fenêtre."

    def test_fenetre_normalise_les_fuseaux(self):
        """La fenêtre est calendaire EN UTC. Cas DISCRIMINANT : sans
        normalisation des fuseaux, le verdict serait FAUX.
          h1 = 2026-03-01T01:00+00:00  (UTC 03-01)
          h2 = 2026-03-09T01:00+09:00  (UTC = 2026-03-08T16:00, soit 03-08)
        En heure LOCALE, les dates sont 03-01 et 03-09 -> 8 jours -> HORS.
        En UTC, 03-01 et 03-08 -> 7 jours -> DANS (bord inclus).
        Le comportement CORRECT est : détecté (calcul UTC). Sans normalisation,
        ce test échoue -> il épingle la normalisation des fuseaux.
        """
        reg = registre.Registre()
        contact = {"nom": "Meme", "telephone": "999", "courriel": ""}
        ingerer_lead(reg, "TZ1", "2026-03-01T01:00:00+00:00", contact=contact,
                     ville="Metz", type_travaux="extension")
        ingerer_lead(reg, "TZ2", "2026-03-09T01:00:00+09:00", contact=contact,
                     ville="Metz", type_travaux="extension")
        assert "TZ2" in doublons.detecter(reg, "TZ1"), (
            "7 jours calendaires EN UTC : dans la fenêtre. Sans normalisation des "
            "fuseaux, l'écart local de 8 jours exclurait à tort ce doublon."
        )


class TestSignalementSansFusion:
    """Signalement d'un doublon sans jamais fusionner les leads (CA-M2-07)."""

    def test_signalement_nominal(self):
        """Un signalement valide retourne le SignalementDoublon et écrit un maillon."""
        reg = registre.Registre()
        h = "2026-04-01T10:00:00+00:00"
        ingerer_lead(reg, "S1", h)
        ingerer_lead(reg, "S2", h)
        taille_avant = reg.taille()
        signalement, verdict = doublons.signaler(reg, "S1", "S2", h)
        assert signalement is not None
        assert verdict is None
        assert reg.taille() == taille_avant + 1, "Un maillon doublon_signale a dû être ajouté."
        assert signalement["lead_id_a"] == "S1"
        assert signalement["lead_id_b"] == "S2"
        assert signalement["arbitrage"] == "en_attente"
        assert signalement["critere"] == "contact_identique"

    def test_signalement_contient_cles_exactes(self):
        """Le SignalementDoublon contient les 6 clés obligatoires."""
        reg = registre.Registre()
        h = "2026-04-02T10:00:00+00:00"
        # contacts DIFFÉRENTS mais même ville+travaux : le critère déterminé est
        # ville_et_travaux (contact_identique ne s'applique pas).
        ingerer_lead(reg, "S3", h, contact={"nom": "Un", "telephone": "111", "courriel": ""},
                     ville="Reims", type_travaux="extension")
        ingerer_lead(reg, "S4", h, contact={"nom": "Deux", "telephone": "222", "courriel": ""},
                     ville="Reims", type_travaux="extension")
        signalement, _ = doublons.signaler(reg, "S3", "S4", h)
        cles_attendues = {"signalement_id", "lead_id_a", "lead_id_b", "critere", "horodatage", "arbitrage"}
        assert set(signalement.keys()) == cles_attendues, "Le dict doit contenir exactement les 6 clés."
        assert signalement["arbitrage"] == "en_attente"
        assert signalement["critere"] == "ville_et_travaux", (
            "contacts différents, même ville+travaux : le critère déterminé est ville_et_travaux"
        )

    def test_signalement_id_independant_ordre(self):
        """Le signalement_id est le même quel que soit l'ordre des lead_ids."""
        reg1 = registre.Registre()
        reg2 = registre.Registre()
        h = "2026-04-03T10:00:00+00:00"
        for reg in (reg1, reg2):
            ingerer_lead(reg, "X1", h)
            ingerer_lead(reg, "X2", h)
        sig1, _ = doublons.signaler(reg1, "X1", "X2", h)
        sig2, _ = doublons.signaler(reg2, "X2", "X1", h)
        assert sig1["signalement_id"] == sig2["signalement_id"], "L'identifiant doit être indépendant de l'ordre."

    def test_les_deux_leads_restent_distincts(self):
        """Après signalement, les deux leads sont encore présents individuellement."""
        reg = registre.Registre()
        h = "2026-04-04T10:00:00+00:00"
        ingerer_lead(reg, "T1", h)
        ingerer_lead(reg, "T2", h)
        doublons.signaler(reg, "T1", "T2", h)
        maillons = reg.lire()
        leads = [m for m in maillons if m.get("type_entree") == "lead_ingere"]
        ids_leads = {m["lead_id"] for m in leads}
        assert ids_leads == {"T1", "T2"}, "Les deux leads doivent toujours exister après signalement."

    @pytest.mark.parametrize(
        "lead_a, lead_b, horodatage, code_attendu",
        [
            ("INEX", "S2", "2026-01-01T00:00:00+00:00", "REJ-TRANSITION-ILLEGALE"),
            ("S1", "INEX", "2026-01-01T00:00:00+00:00", "REJ-TRANSITION-ILLEGALE"),
            ("S1", "S2", "mauvais_format", "REJ-HORODATAGE-INVALIDE"),
            ("S1", "S1", "2026-01-01T00:00:00+00:00", "REJ-TRANSITION-ILLEGALE"),
        ],
        ids=[
            "lead_a_inexistant",
            "lead_b_inexistant",
            "horodatage_invalide",
            "meme_lead",
        ],
    )
    def test_rejets_parametres(self, lead_a, lead_b, horodatage, code_attendu):
        """Les erreurs de paramètres produisent le verdict exact et aucune écriture."""
        reg = registre.Registre()
        h = "2026-04-05T10:00:00+00:00"
        ingerer_lead(reg, "S1", h)
        ingerer_lead(reg, "S2", h)
        taille_avant = reg.taille()
        signalement, verdict = doublons.signaler(reg, lead_a, lead_b, horodatage)
        assert signalement is None
        assert verdict is not None
        assert verdict["code"] == code_attendu, f"Attendu {code_attendu}, reçu {verdict}"
        assert reg.taille() == taille_avant, "Aucun maillon ne doit avoir été ajouté."

    def test_lister_signalements_copie(self):
        """lister_signalements retourne les signalements existants (copies)."""
        reg = registre.Registre()
        h = "2026-04-06T10:00:00+00:00"
        ingerer_lead(reg, "L1", h)
        ingerer_lead(reg, "L2", h)
        sig, _ = doublons.signaler(reg, "L1", "L2", h)
        liste = doublons.lister_signalements(reg)
        assert len(liste) == 1
        copie = liste[0]
        assert copie is not sig, "Doit retourner des copies."
        assert copie == sig

    def test_contact_identique_prime_sur_ville_travaux(self):
        """Prouve que le signalement dérive le critère contact_identique même lorsque ville_et_travaux serait faux."""
        reg = registre.Registre()
        horodatage = "2025-01-15T10:30:00+01:00"
        lead1_id = "lead-1"
        lead2_id = "lead-2"
        ingerer_lead(reg, lead1_id, horodatage, contact={"nom": "Client", "telephone": "", "courriel": "a@b.com"}, type_travaux="isolation_thermique", ville="Paris")
        ingerer_lead(reg, lead2_id, horodatage, contact={"nom": "Client", "telephone": "", "courriel": "a@b.com"}, type_travaux="ravalement", ville="Lyon")
        taille_avant = reg.taille()
        signalement, verdict = doublons.signaler(reg, lead1_id, lead2_id, horodatage)
        assert verdict is None
        assert signalement["critere"] == "contact_identique", (
            "contact identique prime : le critère dérivé doit être contact_identique "
            "même si ville et travaux diffèrent"
        )
        assert reg.taille() == taille_avant + 1, "un signalement réussi écrit un maillon"

    def test_signaler_deux_leads_non_similaires_rejete(self):
        """Prouve que signaler rejette deux leads sans similarité avec le verdict REJ-TRANSITION-ILLEGALE sans modifier le reg."""
        reg = registre.Registre()
        horodatage = "2025-01-15T11:00:00+01:00"
        lead1_id = "lead-a"
        lead2_id = "lead-b"
        ingerer_lead(reg, lead1_id, horodatage, contact={"nom": "Client", "telephone": "", "courriel": "x@y.com"}, type_travaux="renovation_totale", ville="Bordeaux")
        ingerer_lead(reg, lead2_id, horodatage, contact={"nom": "Client", "telephone": "", "courriel": "z@w.com"}, type_travaux="autre", ville="Marseille")
        taille_avant = reg.taille()
        signalement, verdict = doublons.signaler(reg, lead1_id, lead2_id, horodatage)
        assert signalement is None
        assert verdict["code"] == "REJ-TRANSITION-ILLEGALE"
        assert reg.taille() == taille_avant


class TestArbitrage:
    """Arbitrage de doublons (distincts_confirmes uniquement pour v1)."""

    def test_arbitrage_distincts_confirmes(self):
        """Un arbitrage valide retourne un accusé et enregistre la décision."""
        reg = registre.Registre()
        h = "2026-04-07T10:00:00+00:00"
        ingerer_lead(reg, "A1", h)
        ingerer_lead(reg, "A2", h)
        signalement, _ = doublons.signaler(reg, "A1", "A2", h)
        sid = signalement["signalement_id"]
        accuse, verdict = doublons.arbitrer(reg, sid, "distincts_confirmes", h)
        assert accuse is not None
        assert verdict is None
        assert reg.valider_chaine() is True

    @pytest.mark.parametrize(
        "decision, code_attendu",
        [
            ("fusionne", "REJ-ENUM-INVALIDE"),
            ("en_attente", "REJ-ENUM-INVALIDE"),
            ("n_importe_quoi", "REJ-ENUM-INVALIDE"),
        ],
        ids=["fusionne", "en_attente_interdit", "aleatoire"],
    )
    def test_arbitrage_decision_hors_enum(self, decision, code_attendu):
        """Toute décision non valide pour v1 produit REJ-ENUM-INVALIDE."""
        reg = registre.Registre()
        h = "2026-04-08T10:00:00+00:00"
        ingerer_lead(reg, "B1", h)
        ingerer_lead(reg, "B2", h)
        signalement, _ = doublons.signaler(reg, "B1", "B2", h)
        sid = signalement["signalement_id"]
        taille_avant = reg.taille()
        accuse, verdict = doublons.arbitrer(reg, sid, decision, h)
        assert accuse is None
        assert verdict is not None
        assert verdict["code"] == code_attendu
        assert reg.taille() == taille_avant, "Aucune écriture en cas de rejet."

    def test_etat_fusionne_interdit(self):
        """Aucune valeur d'arbitrage ne doit contenir 'fusionne'."""
        assert "fusionne" not in doublons.ARBITRAGES, "'fusionne' ne doit pas exister dans ARBITRAGES."


class TestAntiFusionArchitecturale:
    """Garantie qu'aucune fonction de fusion n'existe dans le module (CA-M2-07)."""

    @staticmethod
    def _noms_fonctions_source(fichier_py):
        """Extrait tous les noms « appelables » introduits dans un fichier via AST.

        Couvre TOUS les vecteurs d'introduction d'une fonction, pas seulement les
        def de module (le scan naïf manquait lambdas assignées et alias d'import) :
        - def et async def (FunctionDef, AsyncFunctionDef), y compris méthodes ;
        - lambda assignée à une variable (le nom de la cible d'assignation) ;
        - import ... as nom (le nom local de l'alias).
        """
        with open(fichier_py, "r", encoding="utf-8") as f:
            arbre = ast.parse(f.read())
        noms = []
        for node in ast.walk(arbre):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                noms.append(node.name.lower())
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Lambda):
                for cible in node.targets:
                    if isinstance(cible, ast.Name):
                        noms.append(cible.id.lower())
            elif isinstance(node, (ast.Import, ast.ImportFrom)):
                for alias in node.names:
                    nom_local = alias.asname or alias.name
                    noms.append(nom_local.lower())
        return noms

    def test_aucune_fonction_fusion_dans_src(self):
        """Scan des fichiers src/*.py : aucun nom de fonction contenant 'fusionn', 'merge' ou 'fusion'."""
        fichiers = list(_SRC.glob("*.py"))
        assert len(fichiers) > 0, "Aucun fichier source trouvé dans le module."
        noms_suspects = []
        for fp in fichiers:
            for nom in self._noms_fonctions_source(fp):
                if "fusionn" in nom or "merge" in nom or "fusion" in nom:
                    noms_suspects.append(f"{fp.name} -> {nom}")
        assert not noms_suspects, f"Fonctions de fusion trouvées : {noms_suspects}"

    def test_aucun_attribut_public_fusion(self):
        """Vérifie que le module doublons n'expose aucun attribut public contenant fusion ou merge."""
        publics = [n for n in dir(doublons) if not n.startswith("_")]
        interdits = [n for n in publics if "fusion" in n.lower() or "merge" in n.lower()]
        assert not interdits, f"Attributs publics suspects : {interdits}"


class TestInvariantsDoublons:
    """Invariants sur les fonctions du module doublons."""

    def test_detecter_est_pure(self):
        """detecter ne modifie pas le registre et n'utilise pas .ajouter()."""
        reg = registre.Registre()
        h = "2026-04-09T10:00:00+00:00"
        ingerer_lead(reg, "I1", h)
        taille_avant = reg.taille()
        tete_avant = reg.tete()
        _ = doublons.detecter(reg, "I1")
        assert reg.taille() == taille_avant
        assert reg.tete() == tete_avant
        source = inspect.getsource(doublons.detecter)
        assert ".ajouter(" not in source, "detecter ne doit contenir aucun appel à .ajouter()."

    def test_signaler_contient_un_ajouter(self):
        """La fonction signaler contient exactement un appel à .ajouter()."""
        source = inspect.getsource(doublons.signaler)
        count = source.count(".ajouter(")
        assert count == 1, f"signaler devrait contenir 1 .ajouter(, trouvé {count}."

    def test_aucune_horloge_interne_dans_doublons(self):
        """Aucun appel à datetime.now, time.time, date.today ou utcnow dans doublons.py."""
        source_fichier = Path(inspect.getfile(doublons)).read_text(encoding="utf-8")
        mots_interdits = ["datetime.now", "time.time", "date.today", "utcnow"]
        for mot in mots_interdits:
            assert mot not in source_fichier, f"Appel interdit à l'horloge : {mot}"

    @pytest.mark.parametrize(
        "fonction, args",
        [
            ("signaler", None),
            ("arbitrer", None),
        ],
        ids=["signaler_retour_couple", "arbitrer_retour_couple"],
    )
    def test_retour_couple_exactement_un_non_nul(self, fonction, args):
        """Les fonctions signaler/arbitrer retournent toujours un couple dont exactement un membre est non nul."""
        reg = registre.Registre()
        h = "2026-04-10T10:00:00+00:00"
        ingerer_lead(reg, "P1", h)
        ingerer_lead(reg, "P2", h)
        if fonction == "signaler":
            signalement, verdict = doublons.signaler(reg, "P1", "P2", h)
            assert (signalement is None) ^ (verdict is None), "Un seul doit être non nul."
            # cas rejet
            _, ver = doublons.signaler(reg, "P1", "P1", h)
            assert ver is not None
            assert (None is ver) is False
        else:  # arbitrer
            sig, _ = doublons.signaler(reg, "P1", "P2", h)
            accuse, verdict = doublons.arbitrer(reg, sig["signalement_id"], "distincts_confirmes", h)
            assert (accuse is None) ^ (verdict is None)
            _, ver2 = doublons.arbitrer(reg, sig["signalement_id"], "inexistant", h)
            assert ver2 is not None
            assert (None is ver2) is False
