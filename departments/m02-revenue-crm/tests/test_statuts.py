import sys
import copy
import inspect
from pathlib import Path
import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
_PKG = _SRC / "m2_revenue_crm"  # répertoire du paquet, pour les scans de sources
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m2_revenue_crm import encodage  # noqa: E402
from m2_revenue_crm import verdicts  # noqa: E402
from m2_revenue_crm import registre  # noqa: E402
from m2_revenue_crm import ingestion  # noqa: E402
from m2_revenue_crm import statuts  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers de module
# ---------------------------------------------------------------------------
def contrat_valide(**surcharges):
    """Retourne un nouveau dict conforme aux sept champs d'un contrat LeadQualifie."""
    base = {
        "lead_id": "L1",
        "conversation_id": "C1",
        "contact": {"nom": "Jean", "telephone": "0601020304", "courriel": "jean@mail.com"},
        "type_travaux": "renovation_totale",
        "ville": "Lyon",
        "urgence_declaree": False,
        "canal": "telephone",
    }
    base.update(surcharges)
    return base

def registre_avec_lead(lead_id="L1"):
    """Retourne un registre neuf avec un lead ingéré, assertion de succès."""
    reg = registre.Registre()
    contrat = contrat_valide(lead_id=lead_id)
    accuse, verdict = ingestion.ingerer(contrat, reg, "2026-03-01T10:00:00+01:00")
    assert accuse is not None, f"Ingestion échouée: {verdict}"
    assert verdict is None, f"Ingestion a produit un verdict: {verdict}"
    return reg

def amener_a(registre_cible, lead_id, statut):
    """Amène un lead au statut donné en enchaînant des transitions légales."""
    if statut == "qualifie":
        accuse, verdict = statuts.transitionner(
            lead_id, "qualifie", registre_cible, "2026-03-01T12:00:00+01:00",
            owner="Alice", prochaine_action={"description": "Rappeler", "echeance": "2026-03-10T09:00:00+01:00"}
        )
        assert accuse is not None, f"Transition vers qualifie échouée: {verdict}"
        assert verdict is None
    elif statut == "converti":
        amener_a(registre_cible, lead_id, "qualifie")
        accuse, verdict = statuts.transitionner(
            lead_id, "converti", registre_cible, "2026-03-01T13:00:00+01:00",
            reference_devis_m3="DEVIS-001"
        )
        assert accuse is not None, f"Transition vers converti échouée: {verdict}"
        assert verdict is None
    elif statut == "perdu":
        # On peut arriver à perdu depuis nouveau ou qualifie ; on choisit nouveau pour simplifier
        # On amène le lead à nouveau (il y est déjà après ingestion) ou on part de l'état actuel.
        # Appel direct depuis le statut courant (qui doit être nouveau).
        # Si le lead est déjà dans un autre état, on ne peut pas, donc on passe par nouveau
        # On s'assure qu'il est en nouveau
        # On peut simplement depuis l'état actuel.
        # Pour être sûr, on suppose que le lead est en nouveau.
        accuse, verdict = statuts.transitionner(
            lead_id, "perdu", registre_cible, "2026-03-01T14:00:00+01:00",
            motif="pas interessé"
        )
        assert accuse is not None, f"Transition vers perdu échouée: {verdict}"
        assert verdict is None


# ---------------------------------------------------------------------------
# TestTableDesTransitions
# ---------------------------------------------------------------------------
class TestTableDesTransitions:
    """Vérifie la table des transitions autorisées et son usage nominal."""

    def test_transitions_autorisees_exactes(self):
        """TRANSITIONS_AUTORISEES contient exactement les quatre couples de la table."""
        attendus = {("nouveau", "qualifie"), ("qualifie", "converti"), ("qualifie", "perdu"), ("nouveau", "perdu")}
        obtenus = set(statuts.TRANSITIONS_AUTORISEES)
        assert obtenus == attendus, f"Écart: manquants {attendus - obtenus}, en trop {obtenus - attendus}"
        assert len(statuts.TRANSITIONS_AUTORISEES) > 0

    def test_statuts_enum(self):
        """STATUTS et STATUTS_TERMINAUX ont les bonnes valeurs."""
        assert set(statuts.STATUTS) == {"nouveau", "qualifie", "converti", "perdu"}, "STATUTS incorrect"
        assert set(statuts.STATUTS_TERMINAUX) == {"converti", "perdu"}, "STATUTS_TERMINAUX incorrect"

    @pytest.mark.parametrize("depart,cible,setup_kwargs", [
        ("nouveau", "qualifie", {"owner": "Alice", "prochaine_action": {"description": "Appel", "echeance": "2026-03-10T10:00:00+02:00"}}),
        ("qualifie", "converti", {"reference_devis_m3": "D123"}),
        ("qualifie", "perdu", {"motif": "Non prioritaire"}),
        ("nouveau", "perdu", {"motif": "Annulé"}),
    ], ids=["nouveau-vers-qualifie", "qualifie-vers-converti", "qualifie-vers-perdu", "nouveau-vers-perdu"])
    def test_transitions_legales_reussissent(self, depart, cible, setup_kwargs):
        """Les quatre transitions autorisées fonctionnent avec conditions remplies."""
        reg = registre_avec_lead("L1")
        if depart == "qualifie":
            amener_a(reg, "L1", "qualifie")
        elif depart == "converti":
            amener_a(reg, "L1", "converti")
        elif depart == "perdu":
            amener_a(reg, "L1", "perdu")
        # Pour depart == nouveau, le lead est déjà nouveau
        accuse, verdict = statuts.transitionner("L1", cible, reg, "2026-03-01T15:00:00+02:00", **setup_kwargs)
        assert accuse is not None, f"Accusé absent"
        assert verdict is None, f"Verdict inattendu: {verdict}"


# ---------------------------------------------------------------------------
# TestTransitionsIllegales
# ---------------------------------------------------------------------------
class TestTransitionsIllegales:
    """Vérifie que les transitions non autorisées sont rejetées (CA-M2-06)."""

    # Liste en dur des couples (depuis, vers) non autorisés, hors départs terminaux
    couples_illegaux_non_terminaux = [
        ("nouveau", "converti"),
        ("qualifie", "nouveau"),
    ]

    @pytest.mark.parametrize("depart,cible", couples_illegaux_non_terminaux,
                             ids=["nouveau-vers-converti", "qualifie-vers-nouveau"])
    def test_transition_illegale_rejetee(self, depart, cible):
        """Un chemin hors table depuis un état non terminal retourne REJ-TRANSITION-ILLEGALE."""
        reg = registre_avec_lead("L1")
        if depart == "qualifie":
            amener_a(reg, "L1", "qualifie")
        taille_avant = reg.taille()
        accuse, verdict = statuts.transitionner("L1", cible, reg, "2026-03-01T16:00:00+02:00")
        assert accuse is None, "Accusé inattendu"
        assert verdicts.est_verdict(verdict["code"])
        assert verdict["code"] == "REJ-TRANSITION-ILLEGALE", f"Code verdict: {verdict['code']}"
        assert reg.taille() == taille_avant, "Le registre a été modifié"

    @pytest.mark.parametrize("cible", ["en_cours", "", None],
                             ids=["hors_enum", "chaine_vide", "None"])
    def test_statut_hors_enum_rejete(self, cible):
        """Cible hors énumération -> REJ-ENUM-INVALIDE."""
        reg = registre_avec_lead("L1")
        taille_avant = reg.taille()
        accuse, verdict = statuts.transitionner("L1", cible, reg, "2026-03-01T17:00:00+02:00")
        assert accuse is None
        assert verdicts.est_verdict(verdict["code"])
        assert verdict["code"] == "REJ-ENUM-INVALIDE", f"Code: {verdict['code']}"
        assert reg.taille() == taille_avant

    def test_lead_inexistant(self):
        """Transition sur un lead_id inconnu -> REJ-TRANSITION-ILLEGALE."""
        reg = registre_avec_lead("L1")
        taille_avant = reg.taille()
        accuse, verdict = statuts.transitionner("INCONNU", "qualifie", reg, "2026-03-01T18:00:00+02:00")
        assert accuse is None
        assert verdicts.est_verdict(verdict["code"])
        assert verdict["code"] == "REJ-TRANSITION-ILLEGALE"
        assert reg.taille() == taille_avant

    @pytest.mark.parametrize("horodatage_invalide", ["2026-13-45", "", None, "2026-03-01T12:00:00"], ids=["horodatage_invalide_13_45", "chaine_vide", "None", "sans_fuseau"])
    def test_horodatage_de_transition_invalide_rejete(self, horodatage_invalide):
        """Ce test épingle l'étape 1 de l'ordre figé des contrôles ; sans lui,
        désactiver la validation d'horodatage ne rend aucun test rouge."""
        reg = registre_avec_lead("LH")
        taille_initiale = reg.taille()
        accuse, verdict = statuts.transitionner(
            "LH",
            "qualifie",
            reg,
            horodatage_invalide,
            owner="Alice",
            prochaine_action={"description": "Suivi", "echeance": "2026-03-10T09:00:00+02:00"}
        )
        assert accuse is None, "Aucun accusé attendu pour un horodatage invalide"
        assert verdict["code"] == "REJ-HORODATAGE-INVALIDE", f"Code attendu: REJ-HORODATAGE-INVALIDE, obtenu: {verdict['code']}"
        assert reg.taille() == taille_initiale, "Aucun maillon ne doit être ajouté"
        assert reg.valider_chaine() is True, "La chaîne doit rester valide"


# ---------------------------------------------------------------------------
# TestConditionsManquantes
# ---------------------------------------------------------------------------
class TestConditionsManquantes:
    """Vérifie les rejets spécifiques pour conditions manquantes (CA-M2-03/04/05)."""

    @pytest.mark.parametrize("depart,cible,kwargs,code_attendu", [
        ("nouveau", "qualifie", {"prochaine_action": {"description": "Rappel", "echeance": "2026-03-10T10:00:00+02:00"}}, "REJ-OWNER-ABSENT"),
        ("nouveau", "qualifie", {"owner": "Bob"}, "REJ-ACTION-ABSENTE"),
        ("nouveau", "qualifie", {"owner": "Bob", "prochaine_action": {"description": "", "echeance": "2026-03-10T10:00:00+02:00"}}, "REJ-ACTION-ABSENTE"),
        ("nouveau", "qualifie", {"owner": "Bob", "prochaine_action": {"description": "Suivi"}}, "REJ-ACTION-ABSENTE"),
        ("nouveau", "qualifie", {"owner": "Bob", "prochaine_action": {"description": "Suivi", "echeance": "2026-03-10T10:00:00"}}, "REJ-ACTION-ABSENTE"),
        ("qualifie", "converti", {}, "REJ-DEVIS-ABSENT"),
        ("qualifie", "converti", {"reference_devis_m3": ""}, "REJ-DEVIS-ABSENT"),
        ("qualifie", "converti", {"reference_devis_m3": "   "}, "REJ-DEVIS-ABSENT"),
        ("qualifie", "perdu", {}, "REJ-MOTIF-ABSENT"),
        ("nouveau", "perdu", {"motif": ""}, "REJ-MOTIF-ABSENT"),
    ], ids=[
        "nouveau-vers-qualifie-sans-owner",
        "nouveau-vers-qualifie-sans-prochaine-action",
        "prochaine-action-description-vide",
        "prochaine-action-sans-echeance",
        "prochaine-action-echeance-sans-fuseau",
        "qualifie-vers-converti-sans-devis",
        "qualifie-vers-converti-devis-vide",
        "qualifie-vers-converti-devis-blanc",
        "qualifie-vers-perdu-sans-motif",
        "nouveau-vers-perdu-motif-vide",
    ])
    def test_condition_manquante(self, depart, cible, kwargs, code_attendu):
        """Chaque condition manquante sur un chemin autorisé donne son verdict spécifique."""
        reg = registre_avec_lead("L2")
        if depart == "qualifie":
            amener_a(reg, "L2", "qualifie")
        taille_avant = reg.taille()
        accuse, verdict = statuts.transitionner("L2", cible, reg, "2026-03-01T19:00:00+02:00", **kwargs)
        assert accuse is None, "Accusé inattendu"
        assert verdicts.est_verdict(verdict["code"])
        assert verdict["code"] == code_attendu, f"Attendu {code_attendu}, obtenu {verdict['code']}"
        assert reg.taille() == taille_avant

    @pytest.mark.parametrize("devis", ["?!x-1", "   devis   ", "0"],
                             ids=["non_alpha", "espaces", "chiffre_zero"])
    def test_reference_devis_opaque_acceptee(self, devis):
        """Une chaîne quelconque non vide est acceptée comme reference_devis_m3 (CA-M2-04)."""
        reg = registre_avec_lead("L3")
        amener_a(reg, "L3", "qualifie")
        accuse, verdict = statuts.transitionner("L3", "converti", reg, "2026-03-01T20:00:00+02:00",
                                                reference_devis_m3=devis)
        assert accuse is not None, f"Transition refusée: {verdict}"
        assert verdict is None


# ---------------------------------------------------------------------------
# TestEtatsTerminaux
# ---------------------------------------------------------------------------
class TestEtatsTerminaux:
    """Vérifie que les états terminaux bloquent toute nouvelle transition."""

    @pytest.mark.parametrize("cible", ["nouveau", "qualifie", "converti", "perdu"],
                             ids=["vers-nouveau", "vers-qualifie", "vers-converti", "vers-perdu"])
    def test_depuis_converti_toute_cible_close(self, cible):
        """Depuis converti, toute transition donne REJ-CONVERSATION-CLOSE."""
        reg = registre_avec_lead("L4")
        amener_a(reg, "L4", "converti")
        taille_avant = reg.taille()
        accuse, verdict = statuts.transitionner("L4", cible, reg, "2026-03-01T21:00:00+02:00")
        assert accuse is None
        assert verdict["code"] == "REJ-CONVERSATION-CLOSE", f"Code: {verdict['code']}"
        assert reg.taille() == taille_avant

    @pytest.mark.parametrize("cible", ["nouveau", "qualifie", "converti", "perdu"],
                             ids=["vers-nouveau", "vers-qualifie", "vers-converti", "vers-perdu"])
    def test_depuis_perdu_toute_cible_close(self, cible):
        """Depuis perdu, toute transition donne REJ-CONVERSATION-CLOSE."""
        reg = registre_avec_lead("L5")
        amener_a(reg, "L5", "perdu")
        taille_avant = reg.taille()
        accuse, verdict = statuts.transitionner("L5", cible, reg, "2026-03-01T22:00:00+02:00")
        assert accuse is None
        assert verdict["code"] == "REJ-CONVERSATION-CLOSE", f"Code: {verdict['code']}"
        assert reg.taille() == taille_avant

    def test_ordre_controle_terminal_avant_table(self):
        """Depuis converti vers qualifie (terminal + chemin absent), le verdict est CONVERSATION-CLOSE."""
        reg = registre_avec_lead("L6")
        amener_a(reg, "L6", "converti")
        taille_avant = reg.taille()
        accuse, verdict = statuts.transitionner("L6", "qualifie", reg, "2026-03-01T23:00:00+02:00")
        assert accuse is None
        assert verdict["code"] == "REJ-CONVERSATION-CLOSE", f"Code: {verdict['code']}"
        assert reg.taille() == taille_avant


# ---------------------------------------------------------------------------
# TestMaillonEtAccuse
# ---------------------------------------------------------------------------
class TestMaillonEtAccuse:
    """Vérifie la structure du maillon écrit et de l'accusé."""

    def test_un_seul_maillon_par_transition(self):
        """Une transition réussie ajoute exactement un maillon."""
        reg = registre_avec_lead("L7")
        taille_avant = reg.taille()
        accuse, _ = statuts.transitionner("L7", "qualifie", reg, "2026-03-01T12:00:00+02:00",
                                          owner="Alice", prochaine_action={"description": "Contacter", "echeance": "2026-03-05T10:00:00+02:00"})
        assert accuse is not None
        assert reg.taille() == taille_avant + 1

    def test_maillon_champs_type_lead_horodatage(self):
        """Le maillon porte type_entree='transition_statut', lead_id et horodatage."""
        reg = registre_avec_lead("L8")
        accuse, _ = statuts.transitionner("L8", "qualifie", reg, "2026-03-01T12:00:00+02:00",
                                          owner="Alice", prochaine_action={"description": "Suivi", "echeance": "2026-03-10T09:00:00+02:00"})
        maillon = reg.lire()[-1]  # le dernier maillon (depuis= attend un ligne_id, pas un indice)
        assert maillon["type_entree"] == "transition_statut"
        assert maillon["lead_id"] == "L8"
        assert maillon["horodatage"] == "2026-03-01T12:00:00+02:00"

    def test_accuse_sept_cles(self):
        """L'accusé contient exactement les sept clés attendues."""
        reg = registre_avec_lead("L9")
        accuse, _ = statuts.transitionner("L9", "qualifie", reg, "2026-03-01T12:00:00+02:00",
                                          owner="Alice", prochaine_action={"description": "Appeler", "echeance": "2026-03-08T10:00:00+02:00"})
        attendues = {"lead_id", "ligne_id", "statut", "statut_precedent", "empreinte_maillon", "tete_chaine", "horodatage"}
        assert set(accuse.keys()) == attendues, f"Clés accusé: {set(accuse.keys())}"

    def test_accuse_valeurs_statuts(self):
        """L'accusé porte le bon statut cible et statut_precedent."""
        reg = registre_avec_lead("L10")
        accuse, _ = statuts.transitionner("L10", "qualifie", reg, "2026-03-01T12:00:00+02:00",
                                          owner="Alice", prochaine_action={"description": "Relance", "echeance": "2026-03-15T10:00:00+02:00"})
        assert accuse["statut"] == "qualifie"
        assert accuse["statut_precedent"] == "nouveau"

    def test_accuse_tete_chaine_correspond(self):
        """accuse['tete_chaine'] égale la tête du registre après transition."""
        reg = registre_avec_lead("L11")
        accuse, _ = statuts.transitionner("L11", "qualifie", reg, "2026-03-01T12:00:00+02:00",
                                          owner="Alice", prochaine_action={"description": "Check", "echeance": "2026-03-20T10:00:00+02:00"})
        assert accuse["tete_chaine"] == reg.tete()

    def test_chaine_valide_apres_transition(self):
        """La chaîne reste valide après transition."""
        reg = registre_avec_lead("L12")
        accuse, _ = statuts.transitionner("L12", "qualifie", reg, "2026-03-01T12:00:00+02:00",
                                          owner="Alice", prochaine_action={"description": "Valider", "echeance": "2026-03-18T10:00:00+02:00"})
        assert reg.valider_chaine(ancre=accuse["tete_chaine"]) is True

    def test_statut_courant_avant_apres(self):
        """statut_courant reflète le bon état avant et après transition."""
        reg = registre_avec_lead("L13")
        assert statuts.statut_courant(reg, "L13") == "nouveau"
        accuse, _ = statuts.transitionner("L13", "qualifie", reg, "2026-03-01T12:00:00+02:00",
                                          owner="Alice", prochaine_action={"description": "Suivi", "echeance": "2026-03-12T10:00:00+02:00"})
        assert statuts.statut_courant(reg, "L13") == "qualifie"

    def test_deux_transitions_legales_successives(self):
        """Deux transitions successives maintiennent la chaîne valide et la taille cohérente."""
        reg = registre_avec_lead("L14")
        taille_apres_ingestion = reg.taille()
        accuse1, _ = statuts.transitionner("L14", "qualifie", reg, "2026-03-01T13:00:00+02:00",
                                           owner="Alice", prochaine_action={"description": "Contacter", "echeance": "2026-03-10T10:00:00+02:00"})
        assert reg.taille() == taille_apres_ingestion + 1
        accuse2, _ = statuts.transitionner("L14", "converti", reg, "2026-03-01T14:00:00+02:00",
                                           reference_devis_m3="D-OK")
        assert reg.taille() == taille_apres_ingestion + 2
        assert reg.valider_chaine(ancre=accuse2["tete_chaine"]) is True

    @pytest.mark.parametrize(
        "statut_depart, statut_cible, kwargs_transition, cle_metier, valeur_attendue",
        [
            (
                "nouveau",
                "qualifie",
                {"owner": "Alice", "prochaine_action": {"description": "Suivi", "echeance": "2026-03-10T09:00:00+02:00"}},
                "prochaine_action",
                {"description": "Suivi", "echeance": "2026-03-10T09:00:00+02:00"},
            ),
            (
                "qualifie",
                "converti",
                {"reference_devis_m3": "DEV-42"},
                "reference_devis_m3",
                "DEV-42",
            ),
            (
                "qualifie",
                "perdu",
                {"motif": "budget refuse"},
                "motif",
                "budget refuse",
            ),
            (
                "nouveau",
                "perdu",
                {"motif": "sans reponse"},
                "motif",
                "sans reponse",
            ),
        ],
        ids=[
            "nouveau->qualifie",
            "qualifie->converti",
            "qualifie->perdu",
            "nouveau->perdu",
        ],
    )
    def test_maillon_porte_les_donnees_metier_de_la_transition(
        self,
        statut_depart,
        statut_cible,
        kwargs_transition,
        cle_metier,
        valeur_attendue,
    ):
        """Sans ce test, supprimer l'inscription des données métier dans le maillon ne rend
        aucun test rouge, et l'audit trail perd sa valeur probante."""
        lead_id = "lead-test-001"
        reg = registre_avec_lead(lead_id)
        horodatage = "2026-03-01T10:00:00+02:00"
        amener_a(reg, lead_id, statut_depart)

        if cle_metier == "prochaine_action":
            prochaine_action_passee = copy.deepcopy(kwargs_transition["prochaine_action"])
            kwargs_transition_mod = copy.deepcopy(kwargs_transition)
            kwargs_transition_mod["prochaine_action"] = prochaine_action_passee
        else:
            kwargs_transition_mod = kwargs_transition

        accuse, verdict = statuts.transitionner(
            lead_id,
            statut_cible,
            reg,
            horodatage,
            **kwargs_transition_mod,
        )
        assert verdict is None, (
            f"Transition {statut_depart}->{statut_cible}: verdict inattendu {verdict!r}"
        )
        assert accuse is not None, (
            f"Transition {statut_depart}->{statut_cible}: accusé manquant"
        )

        maillon = reg.lire()[-1]

        assert maillon["statut_precedent"] == statut_depart, (
            f"Transition {statut_depart}->{statut_cible}: statut_precedent incorrect"
        )
        assert cle_metier in maillon, (
            f"Transition {statut_depart}->{statut_cible}: clé métier '{cle_metier}' absente du maillon"
        )
        assert maillon[cle_metier] == valeur_attendue, (
            f"Transition {statut_depart}->{statut_cible}: valeur métier incorrecte pour '{cle_metier}'"
        )

        if cle_metier == "prochaine_action":
            prochaine_action_passee["description"] = "MODIFIE"
            maillon_apres_mutation = reg.lire()[-1]
            assert maillon_apres_mutation["prochaine_action"] == valeur_attendue, (
                "La mutation de l'argument prochaine_action après transition a modifié le maillon (leçon deepcopy non respectée)"
            )


# ---------------------------------------------------------------------------
# TestInvariantsStatuts
# ---------------------------------------------------------------------------
class TestInvariantsStatuts:
    """Invariants du module statuts."""

    @pytest.mark.parametrize("depart,cible,setup_kwargs,rejet_attendu", [
        ("nouveau", "qualifie", {"owner": "Alice", "prochaine_action": {"description": "Ok", "echeance": "2026-03-12T10:00:00+02:00"}}, False),
        ("nouveau", "qualifie", {}, True),
        ("nouveau", "en_cours", {}, True),
        ("converti", "qualifie", {}, True),  # après amener_a, pour test couple exact/non nul
    ], ids=["nominal", "rejet-condition", "rejet-enum", "rejet-terminal"])
    def test_retour_exactement_un_non_nul(self, depart, cible, setup_kwargs, rejet_attendu):
        """transitionner retourne toujours un couple dont exactement un membre est non nul."""
        reg = registre_avec_lead("L15")
        if depart == "qualifie":
            amener_a(reg, "L15", "qualifie")
        elif depart == "converti":
            amener_a(reg, "L15", "converti")
        elif depart == "perdu":
            amener_a(reg, "L15", "perdu")
        accuse, verdict = statuts.transitionner("L15", cible, reg, "2026-03-01T15:00:00+02:00", **setup_kwargs)
        non_nuls = sum(x is not None for x in (accuse, verdict))
        assert non_nuls == 1, f"Non nuls: {non_nuls}"

    def test_un_seul_point_ecriture(self):
        """Le fichier statuts.py contient exactement une occurrence de .ajouter(."""
        fichier = _PKG / "statuts.py"
        assert fichier.exists(), "Fichier statuts.py introuvable"
        texte = fichier.read_text(encoding="utf-8")
        assert texte.strip(), "Fichier vide"
        occurences = texte.count(".ajouter(")
        assert occurences == 1, f".ajouter( trouvé {occurences} fois"

    def test_aucun_import_reseau(self):
        """Aucun import réseau dans statuts.py."""
        fichier = _PKG / "statuts.py"
        texte = fichier.read_text(encoding="utf-8")
        for interdit in ["socket", "urllib", "requests", "http"]:
            assert interdit not in texte, f"Import interdit trouvé: {interdit}"

    def test_aucune_horloge_interne(self):
        """Aucune horloge interne dans statuts.py."""
        fichier = _PKG / "statuts.py"
        texte = fichier.read_text(encoding="utf-8")
        for appel in ["datetime.now", "time.time", "date.today", "utcnow"]:
            assert appel not in texte, f"Appel horloge: {appel}"

    def test_arguments_non_mutes(self):
        """Les arguments passés ne sont pas mutés par la fonction."""
        reg = registre_avec_lead("L16")
        prochaine = {"description": "Suivi", "echeance": "2026-03-20T10:00:00+02:00"}
        prochaine_avant = copy.deepcopy(prochaine)
        statuts.transitionner("L16", "qualifie", reg, "2026-03-01T16:00:00+02:00",
                              owner="Alice", prochaine_action=prochaine)
        assert prochaine == prochaine_avant, "prochaine_action muté"
