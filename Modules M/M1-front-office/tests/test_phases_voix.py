import sys
from pathlib import Path
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
import phases_voix  # noqa: E402
import verdicts  # noqa: E402
from registre import Registre  # noqa: E402
import pytest
import random
import inspect


def test_ouvrir_conversation_phase0_ouverte():
    """Règle 1 : ouverture crée phase 0 en statut 'ouverte'."""
    registre = Registre()
    conv = phases_voix.ouvrir_conversation("signal-1", "2026-07-26T12:00:00Z", registre)
    assert isinstance(conv, dict)
    assert "phases" in conv
    phase0 = [p for p in conv["phases"] if p["numero"] == 0]
    assert len(phase0) == 1
    assert phase0[0]["statut"] == "ouverte"


def test_transition_lineaire_complete():
    """Règle 2 : transitions 0→1→2→3→4→5 réussissent intégralement."""
    registre = Registre()
    conv = phases_voix.ouvrir_conversation("signal-2", "2026-07-26T12:00:00Z", registre)
    for cible in range(1, 6):
        verdict = phases_voix.transitionner(conv, cible, "2026-07-26T12:01:00Z", registre)
        assert verdict == verdicts.construire_verdict("OK")
    # vérifier que toutes les phases 0..4 sont close_normale et 5 close_normale (conversation terminée)
    phases = conv["phases"]
    for i in range(5):
        p = [p for p in phases if p["numero"] == i]
        assert len(p) == 1
        assert p[0]["statut"] == "close_normale"
    p5 = [p for p in phases if p["numero"] == 5]
    assert len(p5) == 1
    assert p5[0]["statut"] == "close_normale"


def test_saut_interdit():
    """Règle 3 : saut 0→2 lève TransitionInterdite, code REJ-PHASE-SAUTE."""
    registre = Registre()
    conv = phases_voix.ouvrir_conversation("signal-3", "2026-07-26T12:00:00Z", registre)
    with pytest.raises(phases_voix.TransitionInterdite) as excinfo:
        phases_voix.transitionner(conv, 2, "2026-07-26T12:01:00Z", registre)
    assert excinfo.value.verdict["code"] == "REJ-PHASE-SAUTE"


def test_retour_arriere_interdit():
    """Règle 4 : transition 2→1 après avoir atteint la phase 2 est interdite."""
    registre = Registre()
    conv = phases_voix.ouvrir_conversation("signal-4", "2026-07-26T12:00:00Z", registre)
    phases_voix.transitionner(conv, 1, "2026-07-26T12:01:00Z", registre)
    phases_voix.transitionner(conv, 2, "2026-07-26T12:02:00Z", registre)
    with pytest.raises(phases_voix.TransitionInterdite) as excinfo:
        phases_voix.transitionner(conv, 1, "2026-07-26T12:03:00Z", registre)
    assert excinfo.value.verdict["code"] == "REJ-PHASE-SAUTE"


def test_boucle_interdite():
    """Règle 5 : transition 2→2 (boucle) est interdite."""
    registre = Registre()
    conv = phases_voix.ouvrir_conversation("signal-5", "2026-07-26T12:00:00Z", registre)
    phases_voix.transitionner(conv, 1, "2026-07-26T12:01:00Z", registre)
    phases_voix.transitionner(conv, 2, "2026-07-26T12:02:00Z", registre)
    with pytest.raises(phases_voix.TransitionInterdite) as excinfo:
        phases_voix.transitionner(conv, 2, "2026-07-26T12:03:00Z", registre)
    assert excinfo.value.verdict["code"] == "REJ-PHASE-SAUTE"


def test_apres_violation_conversation_figee():
    """Règle 6 : après une violation, la conversation est close_erreur et toute transition ultérieure est refusée."""
    registre = Registre()
    conv = phases_voix.ouvrir_conversation("signal-6", "2026-07-26T12:00:00Z", registre)
    # provoquer violation
    with pytest.raises(phases_voix.TransitionInterdite):
        phases_voix.transitionner(conv, 3, "2026-07-26T12:01:00Z", registre)
    assert conv["statut"] == "close_erreur"
    # même une transition légitime doit lever TransitionInterdite
    with pytest.raises(phases_voix.TransitionInterdite) as excinfo:
        phases_voix.transitionner(conv, 1, "2026-07-26T12:02:00Z", registre)
    assert excinfo.value.verdict["code"] == "REJ-PHASE-SAUTE"


def test_violation_ecrit_alerte_evt_phase_violation():
    """Règle 7 : une violation déclenche une entrée registre de type 'alerte' avec code EVT-PHASE-VIOLATION."""
    registre = Registre()
    conv = phases_voix.ouvrir_conversation("signal-7", "2026-07-26T12:00:00Z", registre)
    with pytest.raises(phases_voix.TransitionInterdite):
        phases_voix.transitionner(conv, 5, "2026-07-26T12:01:00Z", registre)
    entrees = registre.lire(None)
    alertes = [e for e in entrees if e["type_entree"] == "alerte"]
    assert len(alertes) >= 1
    evt_trouve = any("EVT-PHASE-VIOLATION" in alerte.get("code", "") for alerte in alertes)
    assert evt_trouve, "Alerte EVT-PHASE-VIOLATION absente du registre"


def test_transition_reussie_ecrit_entree_chainee():
    """Règle 8 : chaque transition réussie écrit une entrée transition_phase chaînée ; valider_chaine() vrai."""
    registre = Registre()
    conv = phases_voix.ouvrir_conversation("signal-8", "2026-07-26T12:00:00Z", registre)
    for cible in range(1, 6):
        phases_voix.transitionner(conv, cible, "2026-07-26T12:01:00Z", registre)
    entrees = registre.lire(None)
    trans_phase = [e for e in entrees if e["type_entree"] == "transition_phase"]
    # Il y a l'entrée d'ouverture + les 5 transitions = 6
    assert len(trans_phase) == 6
    # vérifier le chaînage
    for i in range(1, len(trans_phase)):
        assert trans_phase[i]["precedent_ligne_id"] == trans_phase[i-1]["ligne_id"]
    # intégrité globale
    assert registre.valider_chaine()


def test_abandon_depuis_phase_0():
    """Règle 9a : abandon depuis phase 0 ferme la phase 0 en close_abandon et crée la phase 5 close_abandon, sans phases intermédiaires."""
    registre = Registre()
    conv = phases_voix.ouvrir_conversation("signal-9a", "2026-07-26T12:00:00Z", registre)
    verdict = phases_voix.abandonner(conv, "2026-07-26T12:01:00Z", registre)
    assert verdict == verdicts.construire_verdict("OK")
    phases = conv["phases"]
    # doit contenir exactement deux phases : 0 et 5
    numeros = sorted(p["numero"] for p in phases)
    assert numeros == [0, 5]
    p0 = [p for p in phases if p["numero"] == 0][0]
    p5 = [p for p in phases if p["numero"] == 5][0]
    assert p0["statut"] == "close_abandon"
    assert p5["statut"] == "close_abandon"


def test_abandon_depuis_phase_2():
    """Règle 9b : abandon après avoir atteint la phase 2 ferme 2 en close_abandon et saute à 5 close_abandon, sans phases 3,4."""
    registre = Registre()
    conv = phases_voix.ouvrir_conversation("signal-9b", "2026-07-26T12:00:00Z", registre)
    phases_voix.transitionner(conv, 1, "2026-07-26T12:01:00Z", registre)
    phases_voix.transitionner(conv, 2, "2026-07-26T12:02:00Z", registre)
    verdict = phases_voix.abandonner(conv, "2026-07-26T12:03:00Z", registre)
    assert verdict == verdicts.construire_verdict("OK")
    phases = conv["phases"]
    numeros = sorted(p["numero"] for p in phases)
    assert numeros == [0, 1, 2, 5]
    # vérifier statuts
    statuts = {p["numero"]: p["statut"] for p in phases}
    assert statuts[0] == "close_normale"
    assert statuts[1] == "close_normale"
    assert statuts[2] == "close_abandon"
    assert statuts[5] == "close_abandon"


def test_abandon_depuis_phase_4():
    """Règle 9c : abandon après avoir atteint la phase 4 ferme 4 en close_abandon et crée 5 close_abandon."""
    registre = Registre()
    conv = phases_voix.ouvrir_conversation("signal-9c", "2026-07-26T12:00:00Z", registre)
    for cible in range(1, 5):
        phases_voix.transitionner(conv, cible, "2026-07-26T12:01:00Z", registre)
    verdict = phases_voix.abandonner(conv, "2026-07-26T12:02:00Z", registre)
    assert verdict == verdicts.construire_verdict("OK")
    phases = conv["phases"]
    numeros = sorted(p["numero"] for p in phases)
    assert numeros == [0, 1, 2, 3, 4, 5]
    statuts = {p["numero"]: p["statut"] for p in phases}
    for i in range(4):
        assert statuts[i] == "close_normale"
    assert statuts[4] == "close_abandon"
    assert statuts[5] == "close_abandon"


def test_abandon_sur_conversation_close_refuse():
    """Règle 10 : abandon sur une conversation déjà close (abandon ou complétion) est refusé."""
    registre = Registre()
    conv = phases_voix.ouvrir_conversation("signal-10", "2026-07-26T12:00:00Z", registre)
    phases_voix.abandonner(conv, "2026-07-26T12:01:00Z", registre)
    # deuxième abandon doit échouer
    verdict = phases_voix.abandonner(conv, "2026-07-26T12:02:00Z", registre)
    assert verdict["code"] != "OK"


def test_horodatage_invalide_refuse():
    """Règle 11 : un horodatage invalide est refusé à l'ouverture, transition et abandon."""
    registre = Registre()
    # horodatage invalide
    res = phases_voix.ouvrir_conversation("signal-11", "2026-13-45", registre)
    assert res["code"] != "OK"
    # test avec une transition sur une conversation initialisée normalement
    conv = phases_voix.ouvrir_conversation("signal-11b", "2026-07-26T12:00:00Z", registre)
    res = phases_voix.transitionner(conv, 1, "pas une date", registre)
    assert res["code"] != "OK"
    res = phases_voix.abandonner(conv, "mauvais", registre)
    assert res["code"] != "OK"


def test_pas_d_horloge_interne():
    """Règle 11 (suite) : le module n'utilise jamais datetime.now ni time.time."""
    source = inspect.getsource(phases_voix)
    assert "datetime.now" not in source
    assert "time.time" not in source


def test_pas_de_reseau():
    """Règle 12 : aucune I/O réseau intempestive dans le module."""
    source = inspect.getsource(phases_voix)
    for interdite in ("urllib", "socket", "http.client"):
        assert interdite not in source, f"Trouvé {interdite} dans phases_voix"


def test_mille_sequences_aleatoires_zero_phase_sautee():
    """Règle 13 : 1000 séquences aléatoires avec graine fixe, aucun saut de phase, violations > 0."""
    rng = random.Random(20260726)
    violations_detectees = 0
    for _ in range(1000):
        registre = Registre()
        conv = phases_voix.ouvrir_conversation("rand", "2026-07-26T12:00:00Z", registre)
        current_phase = 0
        figee = False
        while not figee:
            cible = rng.randint(0, 5)
            try:
                verdict = phases_voix.transitionner(conv, cible, "2026-07-26T12:01:00Z", registre)
                # si pas d'exception, la transition doit être légitime (cible == current_phase+1)
                assert cible == current_phase + 1, "Transition illégale acceptée sans exception"
                assert verdict == verdicts.construire_verdict("OK")
                current_phase = cible
                if current_phase == 5:
                    # progression terminée, conversation close_normale
                    break
            except phases_voix.TransitionInterdite as exc:
                violations_detectees += 1
                assert cible != current_phase + 1, "Transition légitime a levé TransitionInterdite"
                assert exc.verdict["code"] == "REJ-PHASE-SAUTE"
                figee = True
            # si figée, plus aucune transition n'est autorisée
            if conv["statut"] == "close_erreur":
                figee = True
        # après la séquence, vérifier qu'aucune phase non parcourue n'existe
        phases = conv["phases"]
        numeros = sorted(p["numero"] for p in phases)
        # la liste doit être consécutive de 0 à max(numero)
        assert numeros == list(range(len(numeros))), f"Phases non contiguës : {numeros}"
        # vérifier les statuts : sauf la dernière, toutes doivent être "close_normale"
        if not figee:
            # séquence normale terminée à 5
            assert numeros == [0, 1, 2, 3, 4, 5]
            statuts = {p["numero"]: p["statut"] for p in phases}
            for i in range(5):
                assert statuts[i] == "close_normale"
            assert statuts[5] == "close_normale"  # conversation close_normale
        else:
            # violation : la dernière phase est close_erreur, les précédentes close_normale
            statuts = {p["numero"]: p["statut"] for p in phases}
            for i in range(len(numeros)-1):
                assert statuts[i] == "close_normale"
            dernier = numeros[-1]
            assert statuts[dernier] == "close_erreur"
    assert violations_detectees > 0, "Aucune violation détectée, le test ne prouve rien"


class TestAbandonRegistre:

    def test_abandon_ecrit_entree_registre_chainee(self):
        """Après 2 transitions, un abandon écrit exactement 1 entrée transition_phase
        avec motif=abandon, chaînée correctement, et valider_chaine() est vraie."""
        registre = Registre()
        conv = phases_voix.ouvrir_conversation("signal-ab", "2026-07-26T12:00:00Z", registre)
        phases_voix.transitionner(conv, 1, "2026-07-26T12:01:00Z", registre)
        phases_voix.transitionner(conv, 2, "2026-07-26T12:02:00Z", registre)

        # Mémoriser la taille actuelle du registre (entrées de transition précédentes + ouverture)
        nb_avant = len(registre.lire(None))

        verdict = phases_voix.abandonner(conv, "2026-07-26T12:03:00Z", registre)
        assert verdict == verdicts.construire_verdict("OK")

        entrees = registre.lire(None)
        nb_apres = len(entrees)
        assert nb_apres == nb_avant + 1

        derniere_entree = entrees[-1]
        assert derniere_entree["type_entree"] == "transition_phase"
        assert derniere_entree["payload"]["motif"] == "abandon"
        assert derniere_entree["payload"]["phase_source"] == 2
        assert derniere_entree["payload"]["phase_cible"] == 5
        assert derniere_entree["payload"]["conversation_id"] == conv["conversation_id"]

        # Vérification du chaînage
        avant_derniere = entrees[-2]
        assert derniere_entree["precedent_ligne_id"] == avant_derniere["ligne_id"]

        # L'intégrité globale doit être conservée
        assert registre.valider_chaine()

    def test_abandon_refuse_n_ecrit_rien(self):
        """Un second abandon sur une conversation déjà close n'écrit rien."""
        registre = Registre()
        conv = phases_voix.ouvrir_conversation("signal-ab2", "2026-07-26T12:00:00Z", registre)
        # Premier abandon (réussi)
        phases_voix.abandonner(conv, "2026-07-26T12:01:00Z", registre)

        nb_avant = len(registre.lire(None))

        # Second abandon (doit être refusé)
        verdict = phases_voix.abandonner(conv, "2026-07-26T12:02:00Z", registre)
        assert verdict["code"] != "OK"

        nb_apres = len(registre.lire(None))
        assert nb_apres == nb_avant, "Le registre ne doit pas contenir de nouvelle entrée après un abandon refusé"


# ---- Nouveaux tests ajoutés (correctifs R3 M1-S002) ----

def test_abandon_apres_completion_refuse():
    """Après une complétion (0→5), abandonner est refusé, rien n'est modifié."""
    registre = Registre()
    conv = phases_voix.ouvrir_conversation("signal-comp", "2026-07-26T12:00:00Z", registre)
    # Complétion complète
    for cible in range(1, 6):
        phases_voix.transitionner(conv, cible, "2026-07-26T12:01:00Z", registre)

    nb_phases_avant = len(conv["phases"])
    nb_registre_avant = len(registre.lire(None))
    numeros_avant = [p["numero"] for p in conv["phases"]]

    verdict = phases_voix.abandonner(conv, "2026-07-26T12:02:00Z", registre)
    assert verdict["code"] == "REJ-CONVERSATION-CLOSE"

    # Aucune phase ajoutée
    assert len(conv["phases"]) == nb_phases_avant
    # Aucun doublon dans les numéros de phase
    numeros_apres = [p["numero"] for p in conv["phases"]]
    assert len(numeros_apres) == len(set(numeros_apres))
    # Registre inchangé
    assert len(registre.lire(None)) == nb_registre_avant


def test_completion_ferme_la_conversation():
    """Après transition vers 5, la conversation est close_normale et la phase 5 aussi."""
    registre = Registre()
    conv = phases_voix.ouvrir_conversation("signal-fin", "2026-07-26T12:00:00Z", registre)
    for cible in range(1, 6):
        phases_voix.transitionner(conv, cible, "2026-07-26T12:01:00Z", registre)

    assert conv["statut"] == "close_normale"
    phases_5 = [p for p in conv["phases"] if p["numero"] == 5]
    assert len(phases_5) == 1
    assert phases_5[0]["statut"] == "close_normale"


def test_aucun_doublon_de_phase():
    """Séquence complète puis tentatives d'abandon/transition : aucun doublon de phase."""
    registre = Registre()
    conv = phases_voix.ouvrir_conversation("signal-uniq", "2026-07-26T12:00:00Z", registre)
    for cible in range(1, 6):
        phases_voix.transitionner(conv, cible, "2026-07-26T12:01:00Z", registre)

    # Tentative d'abandon après clôture
    phases_voix.abandonner(conv, "2026-07-26T12:02:00Z", registre)

    # Tentative de transition supplémentaire (doit lever une exception ou être bloquée)
    try:
        phases_voix.transitionner(conv, 6, "2026-07-26T12:03:00Z", registre)
    except phases_voix.TransitionInterdite:
        pass

    numeros = [p["numero"] for p in conv["phases"]]
    assert len(numeros) == len(set(numeros)), f"Doublons détectés : {numeros}"


def test_ouverture_ecrit_entree_registre():
    """ouvrir_conversation écrit une entrée registre avec motif ouverture, valider_chaine() vraie."""
    registre = Registre()
    conv = phases_voix.ouvrir_conversation("signal-ouv", "2026-07-26T12:00:00Z", registre)

    entrees = registre.lire(None)
    assert len(entrees) == 1
    entree = entrees[0]
    assert entree["type_entree"] == "transition_phase"
    assert entree["payload"]["motif"] == "ouverture"
    assert entree["payload"]["phase_source"] is None
    assert entree["payload"]["phase_cible"] == 0
    assert entree["payload"]["conversation_id"] == conv["conversation_id"]

    assert conv["dernier_ligne_id"] is not None
    assert registre.valider_chaine()
