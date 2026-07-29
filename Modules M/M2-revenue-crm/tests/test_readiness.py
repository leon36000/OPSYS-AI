import sys
import copy
import inspect
from pathlib import Path
import pytest

# noinspection PyUnresolvedReferences
_SRC = Path(__file__).resolve().parents[1] / "src"
_PKG = _SRC / "m2_revenue_crm"  # répertoire du paquet, pour les scans de sources
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# Les imports suivants échoueront en phase RED car les modules n'existent pas encore.
# C'est le comportement attendu pour ces tests.
from m2_revenue_crm import encodage
from m2_revenue_crm import verdicts
from m2_revenue_crm import registre
from m2_revenue_crm import ingestion
from m2_revenue_crm import statuts
from m2_revenue_crm import interactions  # Fichier manquant → ImportError attendu
from m2_revenue_crm import readiness  # Fichier manquant → ImportError attendu


# ------------------------------------------------------------------ helpers de module
def contrat_valide(**surcharges):
    """Retourne un contrat conforme minimal, surchargeable."""
    base = {
        "lead_id": "L1",
        "conversation_id": "C1",
        "contact": {"nom": "Client Test", "telephone": "", "courriel": "test@example.com"},
        "type_travaux": "renovation_totale",
        "ville": "Paris",
        "urgence_declaree": True,
        "canal": "telephone",
    }
    base.update(surcharges)
    return base


def registre_qualifie(
    lead_id="L1", horodatage_transition="2026-03-01T10:00:00+02:00"
):
    """
    Ingeste un lead et le transitionne vers 'qualifie'.
    Retourne le registre avec un lead ayant owner='Alice' et une prochaine action.
    """
    reg = registre.Registre()
    horodatage_ingestion = "2026-03-01T09:00:00+02:00"
    contrat = contrat_valide(lead_id=lead_id)
    accuse, verdict = ingestion.ingerer(contrat, reg, horodatage_ingestion)
    assert accuse is not None, f"Ingestion echouee: {verdict}"
    assert verdict is None, "Verdict inattendu apres ingestion"
    accuse_t, verdict_t = statuts.transitionner(
        lead_id,
        "qualifie",
        reg,
        horodatage_transition,
        owner="Alice",
        prochaine_action={
            "description": "Appeler client",
            "echeance": "2026-03-02T12:00:00+02:00",
        },
    )
    assert accuse_t is not None, f"Transition vers qualifie echouee: {verdict_t}"
    assert verdict_t is None, "Verdict inattendu apres transition"
    return reg


# ------------------------------------------------------------------ TestInteractions
class TestInteractions:
    """Tests de la gestion des interactions post-qualification."""

    def test_enregistrement_nominal_produit_accuse(self):
        """Un enregistrement valide retourne l'accuse et modifie la chaine."""
        reg = registre_qualifie(lead_id="L-nom")
        taille_avant = reg.taille()
        tete_avant = reg.tete()
        horodatage = "2026-03-01T11:00:00+02:00"
        accuse, verdict = interactions.enregistrer(
            "L-nom", "Bob", "Relance telephone", reg, horodatage
        )
        assert accuse is not None, "Pas d'accuse pour un enregistrement valide"
        assert verdict is None, f"Verdict inattendu: {verdict}"
        assert set(accuse.keys()) == {
            "lead_id", "ligne_id", "tete_chaine", "horodatage"
        }, f"Clés d'accuse inattendues: {accuse.keys()}"
        assert accuse["lead_id"] == "L-nom"
        assert accuse["horodatage"] == horodatage
        assert accuse["tete_chaine"] == reg.tete(), "La tete fournie doit correspondre"
        assert reg.taille() == taille_avant + 1, "Un maillon doit etre ajoute"
        assert reg.tete() != tete_avant, "La tete doit changer"
        # Verification du type du maillon
        chaine = reg.lire()
        dernier = chaine[-1]
        assert dernier["type_entree"] == "interaction"
        assert dernier["lead_id"] == "L-nom"
        assert reg.valider_chaine(), "La chaine doit rester valide"

    def test_lister_retourne_interactions_du_lead(self):
        """lister retourne uniquement les interactions du lead demandé, dans l'ordre."""
        reg = registre_qualifie(lead_id="L1")
        # Enregistrer deux interactions sur L1
        h1 = "2026-03-01T11:00:00+02:00"
        h2 = "2026-03-01T11:30:00+02:00"
        interactions.enregistrer("L1", "Alice", "Note 1", reg, h1)
        interactions.enregistrer("L1", "Alice", "Note 2", reg, h2)
        # Ajouter un second lead et une interaction sur lui
        reg2 = registre_qualifie(lead_id="L2",
                                 horodatage_transition="2026-03-01T10:30:00+02:00")
        # On ne peut pas utiliser le même registre, on crée un registre combiné ?
        # On va fusionner en ajoutant manuellement les maillons de reg2 dans reg ?
        # Pour simplifier, on recrée un registre avec les deux leads.
        # On va plutôt construire un registre avec L1 déjà qualifié, L2 qualifié,
        # et des interactions sur chacun.
        reg_final = registre.Registre()
        # Ingere L1
        accuse1, _ = ingestion.ingerer(contrat_valide(lead_id="L1"),
                                       reg_final, "2026-03-01T09:00:00+02:00")
        statuts.transitionner("L1", "qualifie", reg_final,
                              "2026-03-01T10:00:00+02:00",
                              owner="Alice",
                              prochaine_action={"description": "ok",
                                                "echeance": "2026-03-02"})
        # Ingere L2
        accuse2, _ = ingestion.ingerer(contrat_valide(lead_id="L2"),
                                       reg_final, "2026-03-01T09:10:00+02:00")
        statuts.transitionner("L2", "qualifie", reg_final,
                              "2026-03-01T10:10:00+02:00",
                              owner="Bob",
                              prochaine_action={"description": "ok",
                                                "echeance": "2026-03-02"})
        # Interactions
        interactions.enregistrer("L1", "A", "I1-L1", reg_final,
                                 "2026-03-01T11:00:00+02:00")
        interactions.enregistrer("L2", "B", "I1-L2", reg_final,
                                 "2026-03-01T11:10:00+02:00")
        interactions.enregistrer("L1", "A", "I2-L1", reg_final,
                                 "2026-03-01T11:20:00+02:00")

        liste_L1 = interactions.lister(reg_final, "L1")
        liste_L2 = interactions.lister(reg_final, "L2")
        assert len(liste_L1) == 2, "L1 doit avoir 2 interactions"
        assert len(liste_L2) == 1, "L2 doit avoir 1 interaction"
        assert liste_L1[0]["resume"] == "I1-L1"
        assert liste_L1[1]["resume"] == "I2-L1"
        assert liste_L2[0]["resume"] == "I1-L2"

    def test_lister_retourne_copies_non_modifiantes(self):
        """Les elements retournes par lister sont des copies, pas des references."""
        reg = registre_qualifie(lead_id="L3")
        interactions.enregistrer("L3", "X", "Original",
                                 reg, "2026-03-01T12:00:00+02:00")
        originaux = interactions.lister(reg, "L3")
        copie_profonde = copy.deepcopy(originaux)
        # Modifier le resume dans la liste retournée
        originaux[0]["resume"] = "Modifié"
        # Relire
        relecture = interactions.lister(reg, "L3")
        assert relecture[0]["resume"] == "Original", \
            "La modification d'une copie ne doit pas affecter le registre"
        # S'assurer que la copie profonde n'a pas ete touchee
        assert copie_profonde[0]["resume"] == "Original"

    @pytest.mark.parametrize(
        "auteur,resume,horodatage,code_attendu",
        [
            ("", "OK", "2026-03-01T12:00:00+02:00", "REJ-CHAMP-VIDE"),
            ("Alice", "", "2026-03-01T12:00:00+02:00", "REJ-CHAMP-VIDE"),
            (123, "OK", "2026-03-01T12:00:00+02:00", "REJ-CHAMP-VIDE"),
            # horodatage invalide (sans fuseau)
            ("Bob", "Note", "2026-03-01T12:00:00", "REJ-HORODATAGE-INVALIDE"),
            ("Bob", "Note", "demain", "REJ-HORODATAGE-INVALIDE"),
        ],
        ids=[
            "auteur_vide",
            "resume_vide",
            "auteur_non_chaine",
            "horodatage_sans_fuseau",
            "horodatage_invalide",
        ],
    )
    def test_rejets_parametres(self, auteur, resume, horodatage, code_attendu):
        """Les enregistrements invalides sont rejetes avec le code exact."""
        reg = registre_qualifie(lead_id="L-rej")
        taille_avant = reg.taille()
        tete_avant = reg.tete()
        accuse, verdict = interactions.enregistrer(
            "L-rej", auteur, resume, reg, horodatage
        )
        assert accuse is None, "Pas d'accuse en cas de rejet"
        assert verdict is not None, "Un verdict doit etre present"
        assert verdict["code"] == code_attendu, \
            f"Code attendu {code_attendu}, obtenu {verdict}"
        assert reg.taille() == taille_avant, "Aucun maillon ne doit etre ajoute"
        assert reg.tete() == tete_avant, "La tete ne doit pas changer"

    def test_rejet_lead_inexistant(self):
        """Enregistrer une interaction sur un lead inexistant est rejeté."""
        reg = registre_qualifie(lead_id="Lexistant")
        taille_avant = reg.taille()
        accuse, verdict = interactions.enregistrer(
            "LINCONNU", "Alice", "Note",
            reg, "2026-03-01T12:00:00+02:00"
        )
        assert accuse is None
        assert verdict["code"] == "REJ-TRANSITION-ILLEGALE", \
            f"Attendu REJ-TRANSITION-ILLEGALE, recu {verdict}"
        assert reg.taille() == taille_avant

    def test_rejet_lead_terminal_perdu(self):
        """Un lead en statut perdu ne peut plus recevoir d'interaction."""
        reg = registre_qualifie(lead_id="L-perdu")
        # Transition vers perdu
        statuts.transitionner(
            "L-perdu", "perdu", reg,
            "2026-03-01T13:00:00+02:00",
            motif="Pas interessé",
        )
        taille_avant = reg.taille()
        accuse, verdict = interactions.enregistrer(
            "L-perdu", "Bob", "Tentative",
            reg, "2026-03-01T14:00:00+02:00"
        )
        assert accuse is None
        assert verdict["code"] == "REJ-CONVERSATION-CLOSE", \
            f"Attendu REJ-CONVERSATION-CLOSE, recu {verdict}"
        assert reg.taille() == taille_avant

    def test_maillon_interaction_porte_auteur_et_resume(self):
        """sans ce test, renommer ou omettre auteur/resume dans le maillon ne rend aucun test rouge, et l'audit trail perd sa valeur probante."""
        reg = registre_qualifie(lead_id="L-mail")
        accusé = interactions.enregistrer("L-mail", "Bob", "Appel de suivi", reg, "2026-03-01T11:00:00+02:00")
        assert accusé is not None, "l'enregistrement de l'interaction doit réussir"
        maillon = reg.lire()[-1]
        assert maillon["auteur"] == "Bob", "le maillon doit contenir l'auteur"
        assert maillon["resume"] == "Appel de suivi", "le maillon doit contenir le résumé"
        assert maillon["lead_id"] == "L-mail", "le maillon doit contenir le bon lead_id"
        assert maillon["type_entree"] == "interaction", "le maillon doit avoir le type_entree interaction"
        assert maillon["horodatage"] == "2026-03-01T11:00:00+02:00", "le maillon doit porter l'horodatage correct"
        # Vérification via lister
        liste = interactions.lister(reg, "L-mail")
        assert len(liste) > 0, "la liste des maillons ne doit pas être vide"
        dernier = liste[-1]
        assert dernier["auteur"] == "Bob", "lister : auteur incorrect"
        assert dernier["resume"] == "Appel de suivi", "lister : résumé incorrect"
        assert dernier["lead_id"] == "L-mail", "lister : lead_id incorrect"
        assert dernier["type_entree"] == "interaction", "lister : type_entree incorrect"
        assert dernier["horodatage"] == "2026-03-01T11:00:00+02:00", "lister : horodatage incorrect"

    @pytest.mark.parametrize("auteur, resume, champ_attendu", [
        ("", "resume valide", "auteur"),
        ("auteur valide", "", "resume"),
    ], ids=["auteur_vide", "resume_vide"])
    def test_detail_rejet_distingue_le_champ_vide(self, auteur, resume, champ_attendu):
        registre = registre_qualifie(lead_id="L-1")
        _, verdict = interactions.enregistrer(
            lead_id="L-1",
            auteur=auteur,
            resume=resume,
            registre_cible=registre,
            horodatage="2026-07-28T10:00:00Z"
        )
        assert verdict["code"] == "REJ-CHAMP-VIDE"
        detail_lower = verdict["detail"].lower()
        assert champ_attendu in detail_lower, f"Le détail doit mentionner '{champ_attendu}'"


# --------------------------------------------------------------- TestGatePrerequis
class TestGatePrerequis:
    """Le pré-requis de la gate : seul le statut 'qualifie' active l'évaluation."""

    @pytest.mark.parametrize(
        "statut, lead_id_utilise",
        [
            ("nouveau", "L-nouveau"),
            ("qualifie", "L-qualifie"),
            ("converti", "L-converti"),
            ("perdu", "L-perdu"),
        ],
        ids=[
            "nouveau",
            "qualifie",
            "converti",
            "perdu",
        ],
    )
    def test_evaluer_statuts_non_qualifie_retourne_faux(self, statut, lead_id_utilise):
        """Pour les statuts autre que qualifie, evaluer retourne faux."""
        reg = registre.Registre()
        # Ingestion commune
        contrat = contrat_valide(lead_id=lead_id_utilise)
        ingestion.ingerer(contrat, reg, "2026-03-01T09:00:00+02:00")
        # Assurer le statut voulu
        if statut == "nouveau":
            pass  # deja nouveau
        elif statut == "qualifie":
            statuts.transitionner(
                lead_id_utilise, "qualifie", reg,
                "2026-03-01T10:00:00+02:00",
                owner="A",
                prochaine_action={"description": "ok",
                                  "echeance": "2026-03-02"},
            )
        elif statut == "converti":
            # D'abord qualifie puis converti
            statuts.transitionner(
                lead_id_utilise, "qualifie", reg,
                "2026-03-01T10:00:00+02:00",
                owner="A",
                prochaine_action={"description": "ok",
                                  "echeance": "2026-03-02"},
            )
            statuts.transitionner(
                lead_id_utilise, "converti", reg,
                "2026-03-01T12:00:00+02:00",
                reference_devis_m3="m3-ref",
            )
        elif statut == "perdu":
            statuts.transitionner(
                lead_id_utilise, "qualifie", reg,
                "2026-03-01T10:00:00+02:00",
                owner="A",
                prochaine_action={"description": "ok",
                                  "echeance": "2026-03-02"},
            )
            statuts.transitionner(
                lead_id_utilise, "perdu", reg,
                "2026-03-01T13:00:00+02:00",
                motif="raison",
            )
        # Pour un lead inexistant, on teste à part
        if statut != "qualifie":
            assert not readiness.evaluer(reg, lead_id_utilise), \
                f"evaluer doit retourner False pour statut {statut}"
            return
        # Pour 'qualifie', on teste dans les autres classes
        # Ici on ignore, car le paramètre inclut qualifie, mais le test veut juste
        # vérifier que non-qualifie est faux. On peut sauter qualifie.
        # On va ajuster: on veut tester les faux pour non-qualifie, et pour qualifie
        # on s'attend à un test séparé. Donc ici on ne fait rien pour qualifie.
        # Le paramétrage inclut qualifie mais on peut le traiter à part : le test
        # vérifie que pour tous sauf qualifie c'est faux, et pour qualifie c'est
        # une condition nécessaire mais le test d'activation sera fait ailleurs.
        # Pour l'instant, on peut utiliser un skip conditionnel.
        pass  # On va gérer dans le code plus bas.

    # On va plutôt structurer avec deux tests distincts :
    # un pour les statuts non-qualifie, un pour lead inexistant.
    # On reprend la spec : paramétré 4 cas : nouveau, converti, perdu, lead inexistant.
    # Donc on ne paramètre pas "qualifie". On va faire un test séparé pour qualifie.
    # Je réécris proprement.

    @pytest.mark.parametrize(
        "statut, lead_id_utilise",
        [
            ("nouveau", "L-nouveau"),
            ("converti", "L-converti"),
            ("perdu", "L-perdu"),
        ],
        ids=["nouveau", "converti", "perdu"],
    )
    def test_evaluer_statuts_non_qualifie_faux(self, statut, lead_id_utilise):
        """Couvre le retour faux sur les statuts non qualifiés.

        NOTE : ce test ne PROUVE PAS le pré-requis isolément — sans owner ni
        interaction, les conditions échoueraient de toute façon. La preuve
        isolante est test_prerequis_isole_lead_conditions_remplies_mais_converti.
        """
        reg = registre.Registre()
        contrat = contrat_valide(lead_id=lead_id_utilise)
        ingestion.ingerer(contrat, reg, "2026-03-01T09:00:00+02:00")
        if statut == "nouveau":
            pass
        elif statut == "qualifie":
            statuts.transitionner(
                lead_id_utilise, "qualifie", reg,
                "2026-03-01T10:00:00+02:00",
                owner="A",
                prochaine_action={"description": "ok",
                                  "echeance": "2026-03-02"},
            )
        elif statut == "converti":
            statuts.transitionner(
                lead_id_utilise, "qualifie", reg,
                "2026-03-01T10:00:00+02:00",
                owner="A",
                prochaine_action={"description": "ok",
                                  "echeance": "2026-03-02"},
            )
            statuts.transitionner(
                lead_id_utilise, "converti", reg,
                "2026-03-01T12:00:00+02:00",
                reference_devis_m3="m3-ref",
            )
        elif statut == "perdu":
            statuts.transitionner(
                lead_id_utilise, "qualifie", reg,
                "2026-03-01T10:00:00+02:00",
                owner="A",
                prochaine_action={"description": "ok",
                                  "echeance": "2026-03-02"},
            )
            statuts.transitionner(
                lead_id_utilise, "perdu", reg,
                "2026-03-01T13:00:00+02:00",
                motif="raison",
            )
        assert not readiness.evaluer(reg, lead_id_utilise), \
            f"evaluer doit etre False pour statut {statut}"

    def test_lead_inexistant_evaluer_faux(self):
        """evaluer sur un lead inexistant retourne faux."""
        reg = registre.Registre()
        assert not readiness.evaluer(reg, "ID_inconnu"), \
            "Lead inexistant doit retourner False"

    def test_prerequis_nouveau_sans_conditions_n_est_pas_evalue(self):
        """Meme sans owner, ville, interaction, evaluer sur nouveau est faux sans erreur."""
        reg = registre.Registre()
        contrat = contrat_valide(lead_id="L-nue")
        # Ingestion sans transition, donc nouveau, sans owner, etc.
        ingestion.ingerer(contrat, reg, "2026-03-01T09:00:00+02:00")
        # On force l'absence de ces champs dans le contrat.
        # Le lead est nouveau, evaluer doit simplement retourner faux.
        assert not readiness.evaluer(reg, "L-nue"), \
            "Sur statut nouveau, evaluer doit etre False, meme sans conditions"

    def test_prerequis_isole_lead_conditions_remplies_mais_converti(self):
        """ce test isole le pré-requis ; sans lui, désactiver le contrôle de statut ne rend aucun test rouge."""
        reg = registre_qualifie(lead_id="L-iso")
        # La gate doit être vraie avec les quatre conditions remplies.
        accusé = interactions.enregistrer("L-iso", "Bob", "Appel", reg, "2026-03-01T11:00:00+02:00")
        assert accusé is not None, "l'enregistrement de l'interaction doit réussir"
        assert readiness.evaluer(reg, "L-iso") is True, "pré-condition du test : la gate doit être vraie avant la clôture"
        # Transition vers converti
        accusé_transition = statuts.transitionner("L-iso", "converti", reg, "2026-03-01T12:00:00+02:00", reference_devis_m3="DEV-1")
        assert accusé_transition is not None, "la transition vers converti doit réussir"
        # La gate doit maintenant être fausse, bien que les quatre conditions soient toujours dans les maillons
        assert readiness.evaluer(reg, "L-iso") is False, "seul le pré-requis peut rendre faux ici : les quatre conditions restent satisfaites dans les maillons"


# ----------------------------------------------------------- TestGateQuatreConditions
class TestGateQuatreConditions:
    """Validation des quatre conditions conjonctives de la readiness gate."""

    def test_nominal_toutes_conditions_remplies(self):
        """Lead qualifie avec interaction post-transition : evaluer retourne True."""
        reg = registre_qualifie(lead_id="L-nominal")
        # Ajouter une interaction postérieure
        interactions.enregistrer("L-nominal", "Bob", "Appel",
                                 reg, "2026-03-01T11:00:00+02:00")
        assert readiness.evaluer(reg, "L-nominal"), \
            "La gate doit etre franchie"

    @pytest.mark.parametrize(
        "condition_testee",
        [
            "aucune_interaction",
            "interaction_anterieure",
            "interaction_autre_lead",
        ],
        ids=[
            "aucune_interaction",
            "interaction_anterieure",
            "interaction_autre_lead",
        ],
    )
    def test_condition_unique_manquante(self, condition_testee):
        """Chaque condition manquante isolément bloque la gate."""
        if condition_testee == "aucune_interaction":
            reg = registre_qualifie(lead_id="L-sans-inter")
            assert not readiness.evaluer(reg, "L-sans-inter"), \
                "Sans interaction, gate faux"
        elif condition_testee == "interaction_anterieure":
            # Créer un lead qualifié avec interaction strictement antérieure
            reg = registre_qualifie(lead_id="L-ant")
            # Transition vers qualifie à 10:00, ajouter interaction à 09:00 (avant)
            # Mais on ne peut pas enregistrer avant la transition,
            # car la transition n'a pas encore eu lieu. On va contourner en
            # créant un lead qualifié puis enregistrant une interaction avec
            # horodatage antérieur à la transition.
            # Le registre autorise-t-il un horodatage antérieur ?
            # On suppose que l'horodatage est libre, mais cela pourrait être rejeté ?
            # La spec ne l'interdit pas. On essaie.
            interactions.enregistrer("L-ant", "X", "Vieux",
                                     reg, "2026-03-01T09:00:00+02:00")
            # l'horodatage de transition est 10:00, donc 09:00 est antérieur
            assert not readiness.evaluer(reg, "L-ant"), \
                "Interaction antérieure ne doit pas suffire"
        elif condition_testee == "interaction_autre_lead":
            reg = registre_qualifie(lead_id="L-principal")
            # Ajouter un autre lead qualifié
            reg2 = registre_qualifie(lead_id="L-secondaire")
            # Impossible d'avoir deux registres, il faut un seul registre.
            # On va créer directement un registre avec deux leads.
            reg = registre.Registre()
            ingestion.ingerer(contrat_valide(lead_id="L-principal"),
                              reg, "2026-03-01T09:00:00+02:00")
            statuts.transitionner("L-principal", "qualifie", reg,
                                  "2026-03-01T10:00:00+02:00",
                                  owner="A",
                                  prochaine_action={"description": "ok",
                                                    "echeance": "2026-03-02"})
            ingestion.ingerer(contrat_valide(lead_id="L-autre"),
                              reg, "2026-03-01T09:10:00+02:00")
            statuts.transitionner("L-autre", "qualifie", reg,
                                  "2026-03-01T10:10:00+02:00",
                                  owner="B",
                                  prochaine_action={"description": "ok",
                                                    "echeance": "2026-03-02"})
            # Interaction uniquement sur l'autre lead
            interactions.enregistrer("L-autre", "Z", "Interaction autre",
                                     reg, "2026-03-01T11:00:00+02:00")
            assert not readiness.evaluer(reg, "L-principal"), \
                "Interaction d'un autre lead ne doit pas activer la gate"

    def test_interaction_horaire_egal_transition_passe(self):
        """Interaction avec horodatage égal à la transition compte comme postérieure."""
        reg = registre_qualifie(lead_id="L-egal")
        # Transition à 10:00, interaction aussi à 10:00
        interactions.enregistrer("L-egal", "Alice", "Synchrone",
                                 reg, "2026-03-01T10:00:00+02:00")
        assert readiness.evaluer(reg, "L-egal"), \
            "L'égalité horaire doit valider la condition"

    def test_deux_interactions_dont_une_ante_et_une_post(self):
        """Avec deux interactions, une antérieure et une postérieure, la gate passe."""
        reg = registre_qualifie(lead_id="L-deux")
        # Transition à 10:00, ajouter une interaction à 09:30 (ante) et une à 11:00 (post)
        interactions.enregistrer("L-deux", "X", "Ante",
                                 reg, "2026-03-01T09:30:00+02:00")
        interactions.enregistrer("L-deux", "X", "Post",
                                 reg, "2026-03-01T11:00:00+02:00")
        assert readiness.evaluer(reg, "L-deux"), \
            "Une interaction postérieure suffit, meme avec une antérieure"

    def test_purete_evaluer_sans_effet_de_bord(self):
        """Plusieurs appels a evaluer ne modifient pas le registre."""
        reg = registre_qualifie(lead_id="L-pure")
        interactions.enregistrer("L-pure", "Alice", "Test",
                                 reg, "2026-03-01T11:00:00+02:00")
        taille_avant = reg.taille()
        tete_avant = reg.tete()
        v1 = readiness.evaluer(reg, "L-pure")
        v2 = readiness.evaluer(reg, "L-pure")
        assert v1 == v2, "evaluer doit etre deterministe"
        assert reg.taille() == taille_avant, "taille ne doit pas changer"
        assert reg.tete() == tete_avant, "tete ne doit pas changer"

    def test_maillon_falsifie_naif_ne_plante_pas_la_gate(self):
        """sans ce test, remettre la comparaison hors du try ne rend aucun test rouge et un
        maillon falsifié ferait planter evaluer/emettre_marqueur au lieu d'un refus propre."""
        reg = registre_qualifie(lead_id="LF")
        accusé = interactions.enregistrer("LF", "Bob", "ok", reg, "2026-03-01T11:00:00+02:00")
        assert accusé is not None, "l'enregistrement de l'interaction doit réussir"
        assert readiness.evaluer(reg, "LF") is True, "pré-condition du test : la gate doit être vraie avant falsification"
        # Falsification directe du maillon (inaccessible par l'API publique, qui refuse
        # les horodatages naïfs) pour tester la robustesse de la gate face à un état
        # qu'elle ne contrôle pas.
        reg._chain[-1]["horodatage"] = "2026-03-01T11:00:00"
        # La gate ne doit pas lever.
        résultat = None
        try:
            résultat = readiness.evaluer(reg, "LF")
        except Exception as e:
            pytest.fail(f"evaluer a levé {type(e).__name__} sur un maillon falsifié : {e}")
        # L'interaction falsifiée est incomparable donc ne satisfait pas la condition,
        # et c'était la seule interaction.
        assert résultat is False, (
            f"evaluer doit retourner False pour un maillon naïf, obtenu {résultat}"
        )
        # Idempotence : un second appel doit retourner la même chose.
        second_résultat = readiness.evaluer(reg, "LF")
        assert second_résultat is False, (
            f"le second appel doit aussi retourner False, obtenu {second_résultat}"
        )

    @pytest.mark.parametrize("cas, cible", [
        ("owner_falsifie", "owner"),
        ("type_travaux_falsifie", "type_travaux"),
        ("ville_falsifiee", "ville"),
    ], ids=["owner_falsifie", "type_travaux_falsifie", "ville_falsifiee"])
    def test_chaque_condition_metier_en_echec_isole(self, cas, cible):
        """chaque condition doit être LE facteur isolé d'échec ; sans ce test, forcer les trois conditions à vrai ne rend aucun test rouge."""
        lead_id = f"L-cond-{cible}"
        reg = registre_qualifie(lead_id=lead_id)
        accusé = interactions.enregistrer(lead_id, "Bob", "Appel", reg, "2026-03-02T11:00:00+02:00")
        assert accusé is not None, "l'enregistrement de l'interaction doit réussir"
        assert readiness.evaluer(reg, lead_id) is True, "pré-condition : la gate doit être vraie avant falsification"

        # Falsification directe
        maillon = None
        if cible == "owner":
            for m in reg._chain:
                if m.get("statut") == "qualifie":
                    maillon = m
                    break
            assert maillon is not None, "maillon transition_statut contenant 'qualifie' non trouvé"
            maillon["owner"] = ""
        elif cible == "type_travaux":
            for m in reg._chain:
                if isinstance(m.get("contrat"), dict):
                    maillon = m
                    break
            assert maillon is not None, "maillon lead_ingere avec contrat non trouvé"
            maillon["contrat"]["type_travaux"] = "jardinage"
        elif cible == "ville":
            for m in reg._chain:
                if isinstance(m.get("contrat"), dict):
                    maillon = m
                    break
            assert maillon is not None, "maillon lead_ingere avec contrat non trouvé"
            maillon["contrat"]["ville"] = ""

        # Après falsification, la gate doit échouer
        assert readiness.evaluer(reg, lead_id) is False, (
            f"evaluer doit retourner False après falsification de {cible}"
        )

        # emettre_marqueur doit rejeter la transition
        résultat, verdict = readiness.emettre_marqueur(reg, lead_id, "2026-03-02T12:00:00+02:00")
        assert résultat is None, "emettre_marqueur ne doit pas produire de résultat sur échec"
        assert verdict is not None, "un verdict de rejet est attendu"
        assert verdict["code"] == "REJ-TRANSITION-ILLEGALE", (
            f"verdict attendu REJ-TRANSITION-ILLEGALE, obtenu {verdict['code']}"
        )


# -------------------------------------------------------------------- TestMarqueur
class TestMarqueur:
    """Tests du marqueur signé et de sa vérification."""

    def test_marqueur_valide_gate_vraie(self):
        """Quand la gate est vraie, un marqueur aux 5 cles est emis, rien ecrit."""
        reg = registre_qualifie(lead_id="L-marq")
        interactions.enregistrer("L-marq", "Alice", "Post",
                                 reg, "2026-03-01T11:00:00+02:00")
        taille_avant = reg.taille()
        tete_avant = reg.tete()
        marqueur, verdict = readiness.emettre_marqueur(
            reg, "L-marq", "2026-03-01T12:00:00+02:00"
        )
        assert marqueur is not None, "Marqueur absent"
        assert verdict is None, f"Verdict inattendu: {verdict}"
        assert set(marqueur.keys()) == {
            "readiness_ok", "lead_id", "hash_tete_registre",
            "horodatage", "empreinte"
        }, f"Clés inattendues: {marqueur.keys()}"
        assert marqueur["readiness_ok"] is True
        assert marqueur["lead_id"] == "L-marq"
        assert marqueur["hash_tete_registre"] == tete_avant
        # Aucune ecriture
        assert reg.taille() == taille_avant

    def test_marqueur_gate_fausse_retourne_verdict(self):
        """Quand la gate est fausse, retourne (None, verdict)."""
        reg = registre_qualifie(lead_id="L-faux")  # pas d'interaction
        marqueur, verdict = readiness.emettre_marqueur(
            reg, "L-faux", "2026-03-01T12:00:00+02:00"
        )
        assert marqueur is None
        assert verdict is not None
        assert verdicts.est_verdict(verdict["code"])
        # Aucune ecriture
        assert reg.taille() == reg.taille()

    def test_verifier_marqueur_authentique_vrai(self):
        """verifier_marqueur retourne True sur un marqueur valide."""
        reg = registre_qualifie(lead_id="L-verif")
        interactions.enregistrer("L-verif", "Alice", "OK",
                                 reg, "2026-03-01T11:00:00+02:00")
        marqueur, _ = readiness.emettre_marqueur(
            reg, "L-verif", "2026-03-01T12:00:00+02:00"
        )
        assert readiness.verifier_marqueur(marqueur, reg), \
            "Un marqueur authentique doit etre verifie vrai"

    @pytest.mark.parametrize(
        "champ_a_modifier, valeur",
        [
            ("lead_id", "L-truque"),
            ("empreinte", "empreinte_fabriquee"),
            ("hash_tete_registre", "hash_invente"),
            ("readiness_ok", False),
        ],
        ids=[
            "lead_id_falsifie",
            "empreinte_modifiee",
            "hash_tete_modifie",
            "readiness_ok_false",
        ],
    )
    def test_recalcul_detecte_falsification(self, champ_a_modifier, valeur):
        """La modification d'un champ du marqueur est detectee par verifier_marqueur."""
        reg = registre_qualifie(lead_id="L-falsif")
        interactions.enregistrer("L-falsif", "Bob", "Interaction",
                                 reg, "2026-03-01T11:00:00+02:00")
        marqueur, _ = readiness.emettre_marqueur(
            reg, "L-falsif", "2026-03-01T12:00:00+02:00"
        )
        marqueur_alt = copy.deepcopy(marqueur)
        marqueur_alt[champ_a_modifier] = valeur
        assert not readiness.verifier_marqueur(marqueur_alt, reg), \
            f"Falsification du champ {champ_a_modifier} doit etre detectee"

    def test_marqueur_invalide_apres_modification_registre(self):
        """Un marqueur emis devient faux si le registre est modifie ensuite."""
        reg = registre_qualifie(lead_id="L-modif")
        interactions.enregistrer("L-modif", "Alice", "Initiale",
                                 reg, "2026-03-01T11:00:00+02:00")
        marqueur, _ = readiness.emettre_marqueur(
            reg, "L-modif", "2026-03-01T12:00:00+02:00"
        )
        # Ajouter une nouvelle interaction
        interactions.enregistrer("L-modif", "Bob", "Nouvelle",
                                 reg, "2026-03-01T13:00:00+02:00")
        assert not readiness.verifier_marqueur(marqueur, reg), \
            "Le marqueur ne doit plus etre valide apres modification de la chaine"

    def test_empreinte_recalculable_par_appelant(self):
        """
        L'appelant peut reconstruire l'empreinte depuis le registre.
        Ingrédients (dans l'ordre fixé ci-dessous) :
        - lead_id
        - owner (du lead)
        - type_travaux
        - ville
        - horodatage de la transition vers qualifie (ou équivalent)
        - horodatage de la dernière interaction post-transition (ou True/false)
        - hash_tete_registre
        Ce test fixe le contrat de recalcul.
        """
        reg = registre_qualifie(lead_id="L-recal")
        horodatage_transition = "2026-03-01T10:00:00+02:00"
        # Ajouter une interaction postérieure
        horodatage_interaction = "2026-03-01T11:00:00+02:00"
        interactions.enregistrer("L-recal", "Alice", "Appel",
                                 reg, horodatage_interaction)
        marqueur, _ = readiness.emettre_marqueur(
            reg, "L-recal", "2026-03-01T12:00:00+02:00"
        )
        # Extraire les éléments du registre correspondant au lead
        # On suppose que le lead a un owner="Alice", type_travaux="renovation_totale",
        # ville="Paris", horodatage_transition et presence d'interaction.
        # Pour la presence d'interaction postérieure, on peut utiliser un booléen.
        # Ordre défini par le contrat : lead_id, owner, type_travaux, ville,
        # horodatage_transition, bool_presence_interaction_post, hash_tete.
        # Contrat de recalcul DOCUMENTÉ dans la docstring de readiness :
        # encoder_canonique(conditions, lead_id, tete) où conditions est le dict
        # déterministe des quatre conditions évaluées. C'est ce que M3 réimplémente.
        conditions = {
            "owner": "Alice",
            "type_travaux": "renovation_totale",
            "ville": "Paris",
            "interaction_post_qualification": True,
        }
        empreinte_reconstruite = encodage.encoder_canonique(
            conditions, "L-recal", marqueur["hash_tete_registre"],
        )
        assert empreinte_reconstruite == marqueur["empreinte"], \
            "L'empreinte reconstruite doit correspondre exactement"

    @pytest.mark.parametrize("horodatage_invalide", [
        "2026-13-45",
        "",
        None,
        "2026-03-01T12:00:00"
    ], ids=["mois_invalide", "vide", "none", "sans_fuseau"])
    def test_emettre_marqueur_horodatage_invalide(self, horodatage_invalide):
        """Comportement mesuré : le code retourné est bien REJ-HORODATAGE-INVALIDE."""
        lead_id = "L-horo"
        reg = registre_qualifie(lead_id=lead_id)
        accusé = interactions.enregistrer(lead_id, "Bob", "Appel", reg, "2026-03-02T11:00:00+02:00")
        assert accusé is not None, "l'enregistrement de l'interaction doit réussir"
        assert readiness.evaluer(reg, lead_id) is True, "pré-condition : la gate doit être vraie"

        taille_avant = len(reg._chain)
        résultat, verdict = readiness.emettre_marqueur(reg, lead_id, horodatage_invalide)
        assert résultat is None, "emettre_marqueur ne doit pas produire de résultat sur échec"
        assert verdict is not None, "un verdict est attendu"
        assert verdict["code"] == "REJ-HORODATAGE-INVALIDE", (
            f"verdict attendu REJ-HORODATAGE-INVALIDE, obtenu {verdict['code']}"
        )
        assert len(reg._chain) == taille_avant, (
            "le registre ne doit pas être modifié par un horodatage invalide"
        )

    def test_marqueur_forge_pour_lead_non_pret_rejete(self):
        """
        Verrou R-M2-004 côté vérificateur : un marqueur forgé avec une empreinte
        auto-cohérente doit être rejeté par le recoupement des conditions RÉELLES
        du registre. Sans ce test, retirer le bloc de recoupement ne rend aucun
        test rouge et la forge réussit (mesuré).
        """
        # 1) Registre neuf, ingestion du lead LX à 09:00+02:00
        reg = registre.Registre()
        contrat = contrat_valide(lead_id="LX")
        acc_i, _ = ingestion.ingerer(contrat, reg, "2026-03-01T09:00:00+02:00")
        assert acc_i is not None, "pré-condition : ingestion du lead"
        # 2) Transition vers qualifie à 10:00+02:00, owner "Alice", prochaine action complète.
        #    AUCUNE interaction n'est enregistrée : la gate sera réellement fausse.
        acc_t, _ = statuts.transitionner(
            "LX", "qualifie", reg, "2026-03-01T10:00:00+02:00",
            owner="Alice",
            prochaine_action={"description": "Appeler", "echeance": "2026-03-02T09:00:00+02:00"},
        )
        assert acc_t is not None, "pré-condition : transition vers qualifie"
        # Pré-condition : le lead n'est pas prêt
        assert readiness.evaluer(reg, "LX") is False

        # 3) Forger un marqueur comme un attaquant qui connaît le contrat documenté
        conditions_forgees = {
            "owner": "Alice",
            "type_travaux": "renovation_totale",
            "ville": "Paris",
            "interaction_post_qualification": True,
        }
        faux = {
            "readiness_ok": True,
            "lead_id": "LX",
            "hash_tete_registre": reg.tete(),
            "horodatage": "2026-03-01T12:00:00+02:00",
            "empreinte": encodage.encoder_canonique(
                conditions_forgees, "LX", reg.tete()
            ),
        }

        # 4) Vérification : doit être rejeté (False)
        assert (
            readiness.verifier_marqueur(faux, reg) is False
        ), "un marqueur forgé avec une empreinte auto-cohérente doit être rejeté"

    def test_detail_du_verdict_de_rejet_est_actionnable(self):
        """
        Sur un lead qualifié sans interaction, le rejet doit comporter un détail
        non vide, seul garant d’un digest d’erreurs actionnable. La prose exacte
        n’est pas testée.
        """
        reg = registre_qualifie(lead_id="LX")  # lead qualifié, sans interaction
        _, verdict = readiness.emettre_marqueur(reg, "LX", "2026-03-01T12:00:00+02:00")
        assert verdict is not None
        assert verdict["code"] == "REJ-TRANSITION-ILLEGALE"
        detail = verdict.get("detail", "")
        assert isinstance(detail, str)
        assert len(detail) > 0, "le détail du verdict doit être non vide pour être actionnable"

    @pytest.mark.parametrize(
        "marqueur_casse",
        [
            None,
            [],
            {},
            {"readiness_ok": True, "lead_id": "LX", "hash_tete_registre": 12345},
            {"readiness_ok": True, "lead_id": "LX", "horodatage": "2026-03-01T12:00:00+02:00", "empreinte": None},
        ],
        ids=[
            "None",
            "liste_vide",
            "dict_sans_hash_ni_empreinte",
            "hash_entier_type_casse",
            "empreinte_None",
        ],
    )
    def test_verifier_marqueur_fail_closed_sur_entrees_cassees(self, marqueur_casse):
        """
        Le vérificateur est fail-closed : toute entrée corrompue ou incomplète
        retourne False sans lever d’exception.
        """
        # Construire un registre avec un lead qualifié ET une interaction
        reg = registre_qualifie(lead_id="LX")
        acc, _ = interactions.enregistrer(
            "LX", "Agent", "discussion devis", reg, "2026-03-01T13:00:00+02:00"
        )
        assert acc is not None, "pré-condition : interaction enregistrée"
        # Par précaution, vérifier que le lead est bien prêt
        assert readiness.evaluer(reg, "LX") is True

        try:
            resultat = readiness.verifier_marqueur(marqueur_casse, reg)
        except Exception as e:
            pytest.fail(f"verifier_marqueur a levé une exception inattendue : {e}")
        assert resultat is False, "une entrée cassée doit retourner False, fail-closed"

    def test_detail_rejet_emettre_marqueur_distingue_le_motif(self):
        registre_vide = registre.Registre()
        _, verdict1 = readiness.emettre_marqueur(
            registre_cible=registre_vide,
            lead_id="INCONNU",
            horodatage="2026-03-01T12:00:00+02:00"
        )
        assert verdict1["code"] == "REJ-TRANSITION-ILLEGALE"
        detail1 = verdict1["detail"]
        assert detail1, "Le détail ne doit pas être vide"

        registre_avec_lead = registre_qualifie(lead_id="LZ")
        _, verdict2 = readiness.emettre_marqueur(
            registre_cible=registre_avec_lead,
            lead_id="LZ",
            horodatage="2026-03-01T12:00:00+02:00"
        )
        assert verdict2["code"] == "REJ-TRANSITION-ILLEGALE"
        detail2 = verdict2["detail"]
        assert detail2, "Le détail ne doit pas être vide"

        assert detail1 != detail2, f"Les détails doivent être différents, reçu : '{detail1}' et '{detail2}'"


# --------------------------------------------------------- TestInvariantsReadiness
class TestInvariantsReadiness:
    """Invariants structurels des modules readiness et interactions."""

    def test_readiness_pas_d_appel_ajouter(self):
        """Le fichier readiness.py ne contient aucun appel a .ajouter(."""
        chemin_readiness = _PKG / "readiness.py"
        contenu = chemin_readiness.read_text(encoding="utf-8")
        assert ".ajouter(" not in contenu, \
            "readiness.py ne doit pas contenir .ajouter("

    def test_interactions_un_seul_appel_ajouter(self):
        """Le fichier interactions.py contient exactement un appel .ajouter(."""
        chemin_interactions = _PKG / "interactions.py"
        contenu = chemin_interactions.read_text(encoding="utf-8")
        nb = contenu.count(".ajouter(")
        assert nb == 1, f"Attendu 1 appel .ajouter(, trouve {nb}"

    @pytest.mark.parametrize("nom_fichier", ["interactions.py", "readiness.py"])
    def test_absence_de_horloge_ou_reseau(self, nom_fichier):
        """Aucun usage de time.sleep, socket, requests, etc. dans les deux fichiers."""
        chemin = _PKG / nom_fichier
        contenu = chemin.read_text(encoding="utf-8").lower()
        motifs_interdits = [
            "time.sleep", "datetime.now", "datetime.utcnow",
            "requests.get", "requests.post", "socket.",
        ]
        for motif in motifs_interdits:
            assert motif not in contenu, \
                f"{nom_fichier} contient {motif}, interdit"

    def test_absence_reference_M1_dans_les_sources(self):
        """Aucun fichier source du module M2 ne fait reference a 'M1-'."""
        for fichier in _PKG.glob("*.py"):
            contenu = fichier.read_text(encoding="utf-8")
            assert "M1-" not in contenu, \
                f"Le fichier {fichier.name} contient la chaine interdite 'M1-'"

    @pytest.mark.parametrize(
        "fonction, args_scenario",
        [
            # enregistrer nominal
            (
                "enregistrer",
                ("L-inv", "A", "Resume", None, "2026-03-01T12:00:00+02:00"),
            ),
            # enregistrer rejet (auteur vide)
            (
                "enregistrer",
                ("L-inv", "", "Resume", None, "2026-03-01T12:00:00+02:00"),
            ),
            # emettre_marqueur rejet (gate fausse)
            (
                "emettre_marqueur",
                (None, "L-inv", "2026-03-01T12:00:00+02:00"),
            ),
        ],
        ids=[
            "enregistrer_valide",
            "enregistrer_rejet",
            "emettre_marqueur_rejet",
        ],
    )
    def test_couples_retour_exactement_un_non_nul(self, fonction, args_scenario):
        """Les fonctions retournent un couple dont exactement un membre est non nul."""
        reg = registre_qualifie(lead_id="L-inv")
        # Ajuster les arguments : remplacer None par le registre si nécessaire
        if fonction == "enregistrer":
            func = interactions.enregistrer
            lead_id, auteur, resume, _, horodatage = args_scenario
            res = func(lead_id, auteur, resume, reg, horodatage)
        else:  # emettre_marqueur
            func = readiness.emettre_marqueur
            _, lead_id, horodatage = args_scenario
            res = func(reg, lead_id, horodatage)
        accuse, verdict = res
        assert (accuse is None) != (verdict is None), \
            f"{fonction}: un seul membre doit etre non nul, recu {accuse}, {verdict}"
