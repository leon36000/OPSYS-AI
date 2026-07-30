import copy
import sys
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import m4_field_ops.outbox as outbox_mod
import m4_field_ops.etats as etats_mod
import m4_field_ops.ecarts as ecarts_mod
import m4_field_ops.pointage as pointage_mod
import m4_field_ops.registre as registre_mod
import m4_field_ops.encodage as encodage_mod
import m4_field_ops.cedule as cedule_mod

# ------------------------------------------------------------------ module-level constants / helpers
SEL = "sel-de-test"
VILLE = "Montreal"
REFERENTIEL = {
    cedule_mod.tokeniser_ville(SEL, VILLE): {
        "latitude": 45.5017,
        "longitude": -73.5673,
        "rayon_km": 25.0,
    }
}
GPS_PROCHE = {"latitude": 45.5088, "longitude": -73.5878}
GPS_LOIN = {"latitude": 46.8139, "longitude": -71.2080}
ATTESTATION = {"fictif": True, "appareil_id": "APP-1"}
FENETRE = {"debut": "2025-06-02T07:00:00+00:00", "fin": "2025-06-02T19:00:00+00:00"}

CONTRAT_VALIDE = {
    "lead_id": "L1",
    "conversation_id": "C1",
    "type_travaux": "renovation_totale",
    "ville": VILLE,
    "canal": "telephone",
    "contact": {"nom": "Dupont", "telephone": "0102030405"},
    "urgence_declaree": True,
}

MARQUEUR_VALIDE = {
    "readiness_ok": True,
    "lead_id": "L1",
    "hash_tete_registre": None,
    "horodatage": "2025-06-01T12:00:00+00:00",
    "empreinte": "ab" * 32,
}

H1 = "2025-06-02T08:00:00+00:00"
H_ARRIVEE = "2025-06-02T09:00:00+00:00"
H_DEPART = "2025-06-02T11:30:00+00:00"          # 150 minutes after arrival
H_COMPLETION = "2025-06-02T11:35:00+00:00"
H_ANOMALIE = "2025-06-02T11:40:00+00:00"   # départ incohérent postérieur
H_APRES_ANOMALIE = "2025-06-02T11:45:00+00:00"

def _ajouter_intervention_sur_site(reg, lead_id, horodatage_inscription):
    """Inscrit une intervention DISTINCTE dans un registre existant.

    L'intervention_id est dérivé de (lead_id, horodatage) : réutiliser les deux
    donne le MÊME identifiant, donc la même intervention — piège mesuré, le test
    du consommateur croyait créer deux interventions et n'en créait qu'une.
    """
    contrat = dict(CONTRAT_VALIDE)
    contrat["lead_id"] = lead_id
    marqueur = dict(MARQUEUR_VALIDE)
    marqueur["lead_id"] = lead_id
    acc, ver = etats_mod.inscrire_intervention(contrat, marqueur, reg, horodatage_inscription, SEL)
    assert acc is not None, f"Inscription {lead_id} echouee: {ver}"
    i_id = acc["intervention_id"]
    acc2, ver2 = etats_mod.transitionner(i_id, "en_route", reg, H_ARRIVEE)
    assert acc2 is not None, f"Transition en_route echouee: {ver2}"
    assign = {"intervention_id": i_id, "technicien_id": "T1"}
    for action, horo in (("arrivee", H_ARRIVEE), ("depart", H_DEPART)):
        acc_p, ver_p = pointage_mod.enregistrer_pointage(
            i_id, "T1", action, horo, GPS_PROCHE, ATTESTATION,
            assign, FENETRE, REFERENTIEL, VILLE, SEL, reg
        )
        assert acc_p is not None, f"Pointage {action} echoue: {ver_p}"
    return i_id


def _intervention_sur_site_avec_pointages():
    """Cree un registre avec inscription, transitions et deux pointages (arrivee, depart).
    Retourne (registre, intervention_id)."""
    reg = registre_mod.Registre()
    acc, ver = etats_mod.inscrire_intervention(CONTRAT_VALIDE, MARQUEUR_VALIDE, reg, H1, SEL)
    assert acc is not None, f"Inscription échouée: {ver}"
    i_id = acc["intervention_id"]
    acc2, ver2 = etats_mod.transitionner(i_id, "en_route", reg, H_ARRIVEE)
    assert acc2 is not None, f"Transition en_route échouée: {ver2}"

    assign = {"intervention_id": i_id, "technicien_id": "T1"}
    acc_arr, ver_arr = pointage_mod.enregistrer_pointage(
        i_id, "T1", "arrivee", H_ARRIVEE, GPS_PROCHE, ATTESTATION,
        assign, FENETRE, REFERENTIEL, VILLE, SEL, reg
    )
    assert acc_arr is not None, f"Pointage arrivée échoué: {ver_arr}"

    acc_dep, ver_dep = pointage_mod.enregistrer_pointage(
        i_id, "T1", "depart", H_DEPART, GPS_PROCHE, ATTESTATION,
        assign, FENETRE, REFERENTIEL, VILLE, SEL, reg
    )
    assert acc_dep is not None, f"Pointage départ échoué: {ver_dep}"

    return reg, i_id

ASSIGNATION = lambda i_id: {"intervention_id": i_id, "technicien_id": "T1"}

# ======================================================================= Tests

def test_constantes_epinglees():
    assert outbox_mod.CONSOMMATEURS_CIBLES == ("M6", "M5", "M2", "M7", "M8", "M10")
    assert outbox_mod.CHAMPS_WCT == (
        "wct_id", "intervention_id", "lead_id", "technicien_id", "horodatage_completion",
        "fix_gps_completion", "duree_reelle_minutes", "ecart_signale", "revue_id",
        "hash_maillon", "consommateurs_cibles", "devis_id",
    )

# ------------------------------------------------------------------ 1. CA-M4-11 — UN SEUL maillon
def test_completer_un_seul_maillon():
    reg, i_id = _intervention_sur_site_avec_pointages()
    taille_avant = len(reg.lire())
    accuse, verdict = outbox_mod.completer_intervention(i_id, H_COMPLETION, reg)
    assert accuse is not None, f"completer_intervention échec: {verdict}"
    assert len(reg.lire()) == taille_avant + 1

    dernier = reg.lire()[-1]
    assert dernier["type_entree"] == etats_mod.TYPE_TRANSITION
    assert dernier["statut"] == "terminee"
    assert dernier["statut_precedent"] == "sur_site"
    assert outbox_mod.CLE_WCT in dernier

    # Aucun autre maillon terminee sans wct
    for m in reg.lire():
        if m.get("statut") == "terminee":
            assert outbox_mod.CLE_WCT in m

    # Aucun wct hors d'un maillon terminee
    for m in reg.lire():
        if outbox_mod.CLE_WCT in m:
            assert m["statut"] == "terminee"

# ------------------------------------------------------------------ 2. CA-M4-10 — rien avant terminee
def test_lire_outbox_vide_avant_completion():
    reg, i_id = _intervention_sur_site_avec_pointages()
    assert outbox_mod.lire_outbox(reg) == []
    for m in reg.lire():
        assert outbox_mod.CLE_WCT not in m

# ------------------------------------------------------------------ 3. Contrat WCT complet
def test_contrat_wct_complet():
    reg, i_id = _intervention_sur_site_avec_pointages()
    accuse, _ = outbox_mod.completer_intervention(i_id, H_COMPLETION, reg)
    maillon = reg.lire()[-1]
    wct = maillon[outbox_mod.CLE_WCT]

    assert set(wct.keys()) == set(outbox_mod.CHAMPS_WCT)
    assert wct["consommateurs_cibles"] == list(outbox_mod.CONSOMMATEURS_CIBLES)
    assert wct["devis_id"] is None
    assert wct["ecart_signale"] is False
    assert wct["revue_id"] is None
    assert wct["duree_reelle_minutes"] == 150
    assert wct["horodatage_completion"] == H_DEPART
    assert wct["fix_gps_completion"] == {"latitude": 45.5088, "longitude": -73.5878}
    assert wct["lead_id"] == CONTRAT_VALIDE["lead_id"]
    assert wct["technicien_id"] == "T1"

# ------------------------------------------------------------------ 4. hash_maillon non circulaire et EXACT
def test_hash_maillon_exact():
    reg, i_id = _intervention_sur_site_avec_pointages()
    accuse, _ = outbox_mod.completer_intervention(i_id, H_COMPLETION, reg)
    maillon = reg.lire()[-1]
    wct = maillon[outbox_mod.CLE_WCT]

    # Reconstruire la partie transition SEULE
    partie_transition = {
        k: v for k, v in maillon.items()
        if k not in (outbox_mod.CLE_WCT, "ligne_id", "precedent_ligne_id")
    }
    recalcul = encodage_mod.empreinte(partie_transition)
    assert wct["hash_maillon"] == recalcul

# ------------------------------------------------------------------ 5. wct_id dérivé
def test_wct_id_derive():
    reg, i_id = _intervention_sur_site_avec_pointages()
    accuse, _ = outbox_mod.completer_intervention(i_id, H_COMPLETION, reg)
    wct = reg.lire()[-1][outbox_mod.CLE_WCT]
    attendu = encodage_mod.empreinte("wct", i_id, H_COMPLETION)
    assert wct["wct_id"] == attendu

# ------------------------------------------------------------------ 6. transitionner REFUSE terminee
@pytest.mark.parametrize("statut_depart", ["sur_site", "en_revue"])
def test_transitionner_refuse_terminee(statut_depart):
    reg, i_id = _intervention_sur_site_avec_pointages()
    if statut_depart == "en_revue":
        # Mettre l'intervention en_revue (pointage incohérent)
        # Depuis sur_site, seul un DÉPART incohérent route en revue (une arrivée
        # exigerait en_route) — mesuré.
        accuse, verd = pointage_mod.enregistrer_pointage(
            i_id, "T1", "depart", H_ANOMALIE, GPS_LOIN, ATTESTATION,
            ASSIGNATION(i_id), FENETRE, REFERENTIEL, VILLE, SEL, reg
        )
        assert accuse is not None, f"pointage d'anomalie refusé : {verd}"
        assert etats_mod.statut_courant(reg, i_id) == "en_revue"

    taille_avant = len(reg.lire())
    acc, verdict = etats_mod.transitionner(i_id, "terminee", reg, H_COMPLETION)
    assert acc is None
    assert verdict["code"] == "REJ-TRANSITION-ILLEGALE"
    assert "outbox" in verdict["detail"].lower()
    assert len(reg.lire()) == taille_avant

# ------------------------------------------------------------------ 7. La table reste l'autorité
def test_transitions_autorisees_contenant_terminee():
    assert ("sur_site", "terminee") in etats_mod.TRANSITIONS_AUTORISEES
    assert ("en_revue", "terminee") in etats_mod.TRANSITIONS_AUTORISEES

# ------------------------------------------------------------------ 8. Chemin illégal (completer sans pointages)
def test_completer_illegal_planifiee():
    reg = registre_mod.Registre()
    acc, _ = etats_mod.inscrire_intervention(CONTRAT_VALIDE, MARQUEUR_VALIDE, reg, H1, SEL)
    i_id = acc["intervention_id"]
    taille_avant = len(reg.lire())
    accuse, verdict = outbox_mod.completer_intervention(i_id, H_COMPLETION, reg)
    assert accuse is None
    assert verdict["code"] == "REJ-TRANSITION-ILLEGALE"
    assert len(reg.lire()) == taille_avant

def test_completer_illegal_en_route():
    reg = registre_mod.Registre()
    acc, _ = etats_mod.inscrire_intervention(CONTRAT_VALIDE, MARQUEUR_VALIDE, reg, H1, SEL)
    i_id = acc["intervention_id"]
    etats_mod.transitionner(i_id, "en_route", reg, H_ARRIVEE)
    taille_avant = len(reg.lire())
    accuse, verdict = outbox_mod.completer_intervention(i_id, H_COMPLETION, reg)
    assert accuse is None
    assert verdict["code"] == "REJ-TRANSITION-ILLEGALE"
    assert len(reg.lire()) == taille_avant

# ------------------------------------------------------------------ 9. Durée fail-closed — registre inchangé
@pytest.mark.parametrize("scenario", [
    "aucun_pointage",
    "arrivee_seule",
    "depart_seul",
])
def test_duree_fail_closed(scenario):
    reg = registre_mod.Registre()
    acc, _ = etats_mod.inscrire_intervention(CONTRAT_VALIDE, MARQUEUR_VALIDE, reg, H1, SEL)
    i_id = acc["intervention_id"]
    etats_mod.transitionner(i_id, "en_route", reg, H_ARRIVEE)
    # Forcer l'état sur_site en écrivant un maillon de transition directement
    # pour que l'intervention soit éligible à la complétion si la durée était valide
    maillon_sur_site = {
        "type_entree": etats_mod.TYPE_TRANSITION,
        "intervention_id": i_id,
        "statut": "sur_site",
        "statut_precedent": "en_route",
        "horodatage": H_ARRIVEE,
    }
    reg.ajouter(maillon_sur_site)

    if scenario == "aucun_pointage":
        pass  # aucun pointage
    elif scenario == "arrivee_seule":
        # Ajouter directement un maillon de pointage arrivée (simule)
        maillon = {
            "type_entree": pointage_mod.TYPE_POINTAGE,
            "intervention_id": i_id,
            "action": "arrivee",
            "technicien_id": "T1",
            "horodatage": H_ARRIVEE,
            "latitude": GPS_PROCHE["latitude"],
            "longitude": GPS_PROCHE["longitude"],
        }
        reg.ajouter(maillon)
    elif scenario == "depart_seul":
        maillon = {
            "type_entree": pointage_mod.TYPE_POINTAGE,
            "intervention_id": i_id,
            "action": "depart",
            "technicien_id": "T1",
            "horodatage": H_DEPART,
            "latitude": GPS_PROCHE["latitude"],
            "longitude": GPS_PROCHE["longitude"],
        }
        reg.ajouter(maillon)
    taille_avant = len(reg.lire())
    accuse, verdict = outbox_mod.completer_intervention(i_id, H_COMPLETION, reg)
    assert accuse is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert "durée" in verdict["detail"].lower()
    assert len(reg.lire()) == taille_avant

# ------------------------------------------------------------------ 10. calculer_duree_reelle directement
def test_calculer_duree_reelle_nominal():
    reg, i_id = _intervention_sur_site_avec_pointages()
    minutes, code = outbox_mod.calculer_duree_reelle(reg, i_id)
    assert code is None
    assert minutes == 150
    assert isinstance(minutes, int)

def test_calculer_duree_reelle_echoue_aucun_pointage():
    reg = registre_mod.Registre()
    acc, _ = etats_mod.inscrire_intervention(CONTRAT_VALIDE, MARQUEUR_VALIDE, reg, H1, SEL)
    i_id = acc["intervention_id"]
    minutes, code = outbox_mod.calculer_duree_reelle(reg, i_id)
    assert minutes is None
    assert code == "REJ-CONTRAT-INVALIDE"

def test_calculer_duree_reelle_echoue_arrivee_seule():
    reg = registre_mod.Registre()
    acc, _ = etats_mod.inscrire_intervention(CONTRAT_VALIDE, MARQUEUR_VALIDE, reg, H1, SEL)
    i_id = acc["intervention_id"]
    etats_mod.transitionner(i_id, "sur_site", reg, H_ARRIVEE)  # bypass pour avoir sur_site
    # Ajouter maillon pointage arrivée uniquement
    reg.ajouter({
        "type_entree": pointage_mod.TYPE_POINTAGE, "intervention_id": i_id,
        "action": "arrivee", "horodatage": H_ARRIVEE, "latitude": 0, "longitude": 0,
    })
    minutes, code = outbox_mod.calculer_duree_reelle(reg, i_id)
    assert minutes is None
    assert code == "REJ-CONTRAT-INVALIDE"

def test_calculer_duree_reelle_arrivee_apres_depart():
    reg, i_id = _intervention_sur_site_avec_pointages()
    # Supprimer les pointages existants et en mettre avec depart avant arrivee
    # Pour simplifier, on crée un nouveau registre avec des pointages inversés
    reg2 = registre_mod.Registre()
    acc, _ = etats_mod.inscrire_intervention(CONTRAT_VALIDE, MARQUEUR_VALIDE, reg2, H1, SEL)
    i_id2 = acc["intervention_id"]
    etats_mod.transitionner(i_id2, "sur_site", reg2, H_ARRIVEE)
    reg2.ajouter({
        "type_entree": pointage_mod.TYPE_POINTAGE, "intervention_id": i_id2,
        "action": "depart", "horodatage": H_ARRIVEE, "latitude": 0, "longitude": 0,
    })
    reg2.ajouter({
        "type_entree": pointage_mod.TYPE_POINTAGE, "intervention_id": i_id2,
        "action": "arrivee", "horodatage": H_DEPART, "latitude": 0, "longitude": 0,
    })
    minutes, code = outbox_mod.calculer_duree_reelle(reg2, i_id2)
    assert minutes is None
    assert code == "REJ-HORODATAGE-ANTERIEUR"

# ------------------------------------------------------------------ 11. CA-M4-13 — wct sans données sensibles
def test_wct_sans_donnees_sensibles():
    reg, i_id = _intervention_sur_site_avec_pointages()
    accuse, _ = outbox_mod.completer_intervention(i_id, H_COMPLETION, reg)
    wct = reg.lire()[-1][outbox_mod.CLE_WCT]
    wct_str = str(wct)
    # Pas de ville en clair
    assert VILLE not in wct_str
    for cle in ("adresse", "rue", "code_postal"):
        assert cle not in wct
    # lead_id en clair
    assert wct["lead_id"] == CONTRAT_VALIDE["lead_id"]

# ------------------------------------------------------------------ 12. verifier_invariants_outbox
def test_verifier_invariants_sain():
    reg, i_id = _intervention_sur_site_avec_pointages()
    outbox_mod.completer_intervention(i_id, H_COMPLETION, reg)
    ok, msg = outbox_mod.verifier_invariants_outbox(reg)
    assert ok
    assert msg == ""

@pytest.mark.parametrize("falsification", [
    "retirer_wct",
    "greffer_wct_sur_pointage",
    "alterer_hash",
])
def test_verifier_invariants_falsifies(falsification):
    reg, i_id = _intervention_sur_site_avec_pointages()
    outbox_mod.completer_intervention(i_id, H_COMPLETION, reg)
    chain = reg._chain
    if falsification == "retirer_wct":
        # supprimer la clé wct du dernier maillon (terminee)
        del chain[-1][outbox_mod.CLE_WCT]
    elif falsification == "greffer_wct_sur_pointage":
        # ajouter une clé wct bidon sur un maillon de pointage
        for m in chain:
            if m.get("type_entree") == pointage_mod.TYPE_POINTAGE:
                m[outbox_mod.CLE_WCT] = chain[-1].get(outbox_mod.CLE_WCT, {"faux": True})
                break
    elif falsification == "alterer_hash":
        # modifier le hash_maillon dans le wct
        wct = chain[-1][outbox_mod.CLE_WCT]
        wct["hash_maillon"] = "0000...0000"
    ok, msg = outbox_mod.verifier_invariants_outbox(reg)
    assert not ok
    assert msg != ""

# ------------------------------------------------------------------ 13. garde_ecriture_unique
def test_garde_ecriture_unique_reel():
    ok, msg = outbox_mod.garde_ecriture_unique()
    assert ok
    assert msg == ""

def test_garde_ecriture_unique_violation_ajouter(tmp_path):
    # Créer un faux module avec un appel à ajouter avec dict contenant CLE_WCT
    fake_module = tmp_path / "fake.py"
    # La garde AST inspecte les LITTÉRAUX : un violateur réaliste écrit la clé
    # "wct" en clair. La forme indirecte (outbox.CLE_WCT) lui échapperait,
    # limitation DÉCLARÉE dans sa docstring — le refus au runtime dans
    # transitionner en est la défense en profondeur.
    fake_module.write_text(
        'def violer(registre):\n    registre.ajouter({"wct": {}, "type_entree": "transition_statut"})\n',
        encoding="utf-8",
    )
    # Modifier temporairement le chemin pour qu'il contienne tmp_path ?
    # L'implémentation de garde_ecriture_unique doit scanner le dossier source, pas tmp_path.
    # On va créer un dossier temporaire et y placer des modules, puis appeler la fonction en lui passant le chemin.
    ok, msg = outbox_mod.garde_ecriture_unique(chemin_source=str(tmp_path))
    assert not ok
    assert msg != ""

def test_garde_ecriture_unique_violation_transitionner_terminee(tmp_path):
    fake_module2 = tmp_path / "fake2.py"
    fake_module2.write_text("""
def violer():
    etats.transitionner(x, "terminee", r, h)
""")
    ok, msg = outbox_mod.garde_ecriture_unique(chemin_source=str(tmp_path))
    assert not ok
    assert msg != ""

# ------------------------------------------------------------------ 14. lire_outbox
def test_lire_outbox_un_element():
    reg, i_id = _intervention_sur_site_avec_pointages()
    outbox_mod.completer_intervention(i_id, H_COMPLETION, reg)
    resultat = outbox_mod.lire_outbox(reg)
    assert len(resultat) == 1
    index, wct = resultat[0]
    assert isinstance(index, int)
    assert wct["intervention_id"] == i_id

def test_lire_outbox_depuis_index():
    reg, i_id = _intervention_sur_site_avec_pointages()
    outbox_mod.completer_intervention(i_id, H_COMPLETION, reg)
    # Créer une deuxième intervention complétée pour avoir un index plus loin
    reg2, i_id2 = _intervention_sur_site_avec_pointages()
    # Copier les maillons dans reg (artificiel mais suffisant)
    for m in reg2.lire()[1:]:  # skip le premier (marqueur)
        reg.ajouter(m)
    outbox_mod.completer_intervention(i_id2, H_COMPLETION, reg)

    tout = outbox_mod.lire_outbox(reg)
    assert len(tout) == 2
    # Filtrer avec depuis_index = premier_index_du_deuxième
    premier_index = tout[0][0]
    resultat = outbox_mod.lire_outbox(reg, depuis_index=premier_index)
    assert len(resultat) == 2  # les deux sont >=
    resultat2 = outbox_mod.lire_outbox(reg, depuis_index=premier_index+1)
    assert len(resultat2) == 1

def test_lire_outbox_index_negatif():
    reg, _ = _intervention_sur_site_avec_pointages()
    with pytest.raises(ValueError, match="depuis_index négatif"):
        outbox_mod.lire_outbox(reg, depuis_index=-1)

def test_lire_outbox_copie_profonde():
    reg, i_id = _intervention_sur_site_avec_pointages()
    outbox_mod.completer_intervention(i_id, H_COMPLETION, reg)
    resultat = outbox_mod.lire_outbox(reg)
    wct_original = reg.lire()[-1][outbox_mod.CLE_WCT]
    wct_resultat = resultat[0][1]
    # Modifier la copie ne doit pas altérer le registre
    wct_resultat["intervention_id"] = "bidon"
    assert reg.lire()[-1][outbox_mod.CLE_WCT]["intervention_id"] == i_id

# ------------------------------------------------------------------ 15. Consommateur idempotent (CA-M4-11 preuve 3)
def test_consommateur_idempotent():
    reg, i_id1 = _intervention_sur_site_avec_pointages()
    outbox_mod.completer_intervention(i_id1, H_COMPLETION, reg)

    # Deuxième intervention, RÉELLEMENT distincte (autre lead_id)
    i_id2 = _ajouter_intervention_sur_site(reg, "L2", H1)
    acc2, ver2 = outbox_mod.completer_intervention(i_id2, H_COMPLETION, reg)
    assert acc2 is not None, f"complétion 2 refusée : {ver2}"

    cons = outbox_mod.ConsommateurReference()
    nb1 = cons.consommer(reg)
    assert nb1 == 2
    assert len(cons.effets) == 2

    nb2 = cons.consommer(reg)
    assert nb2 == 0
    assert len(cons.effets) == 2

    nb3 = cons.consommer(reg, depuis_index=0)  # resoumission totale
    assert nb3 == 0
    assert len(cons.effets) == 2

    assert cons.wct_vus == {e["wct_id"] for e in cons.effets}

    # Troisième intervention, consommation incrémentale
    i_id3 = _ajouter_intervention_sur_site(reg, "L3", H1)
    acc3, ver3 = outbox_mod.completer_intervention(i_id3, H_COMPLETION, reg)
    assert acc3 is not None, f"complétion 3 refusée : {ver3}"

    nb4 = cons.consommer(reg)
    assert nb4 == 1
    assert len(cons.effets) == 3

# ------------------------------------------------------------------ 16. Écart validé -> complétion avec WCT
def test_ecart_valide_produit_wct():
    reg, i_id = _intervention_sur_site_avec_pointages()
    # Créer une demande d'écart (pointage incohérent)
    acc_anomalie, verd_anomalie = pointage_mod.enregistrer_pointage(
        i_id, "T1", "depart", H_ANOMALIE, GPS_LOIN, ATTESTATION,
        ASSIGNATION(i_id), FENETRE, REFERENTIEL, VILLE, SEL, reg
    )
    assert acc_anomalie is not None, f"pointage d'anomalie refusé : {verd_anomalie}"
    # Trouver la demande créée
    demande = None
    for m in reg.lire():
        if m.get("type_entree") == pointage_mod.TYPE_DEMANDE_REVUE:
            demande = m
            break
    assert demande is not None
    demande_id = demande["demande_id"]

    # Résoudre validee -> doit créer la transition terminee (avec wct)
    acc, ver = ecarts_mod.resoudre_demande(demande_id, "validee", H_COMPLETION, reg)
    assert acc is not None, f"resoudre_demande échec: {ver}"
    # Le composite n'est PAS le dernier maillon : l'entrée de résolution est
    # écrite après lui. On le localise par sa clé wct.
    composites = [m for m in reg.lire() if outbox_mod.CLE_WCT in m]
    assert len(composites) == 1
    dernier = composites[0]
    assert dernier["type_entree"] == etats_mod.TYPE_TRANSITION
    assert dernier["statut"] == "terminee"
    wct = dernier[outbox_mod.CLE_WCT]
    assert wct["ecart_signale"] is True
    assert wct["revue_id"] == demande_id
    ok, _ = outbox_mod.verifier_invariants_outbox(reg)
    assert ok

# ------------------------------------------------------------------ 17. Écart rejeté -> annulation SANS WCT
def test_ecart_rejete_pas_de_wct():
    reg, i_id = _intervention_sur_site_avec_pointages()
    # Créer une demande d'écart
    acc_anomalie, verd_anomalie = pointage_mod.enregistrer_pointage(
        i_id, "T1", "depart", H_ANOMALIE, GPS_LOIN, ATTESTATION,
        ASSIGNATION(i_id), FENETRE, REFERENTIEL, VILLE, SEL, reg
    )
    assert acc_anomalie is not None, f"pointage d'anomalie refusé : {verd_anomalie}"
    demande = next(m for m in reg.lire() if m.get("type_entree") == pointage_mod.TYPE_DEMANDE_REVUE)
    demande_id = demande["demande_id"]

    acc, _ = ecarts_mod.resoudre_demande(demande_id, "rejetee", H_COMPLETION, reg)
    assert acc is not None
    assert etats_mod.statut_courant(reg, i_id) == "annulee"
    assert outbox_mod.lire_outbox(reg) == []
    for m in reg.lire():
        assert outbox_mod.CLE_WCT not in m

# ------------------------------------------------------------------ 18. revue_id inconnu
def test_completer_revue_id_inconnu():
    reg, i_id = _intervention_sur_site_avec_pointages()
    taille_avant = len(reg.lire())
    accuse, verdict = outbox_mod.completer_intervention(i_id, H_COMPLETION, reg, revue_id="inconnu")
    assert accuse is None
    assert verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert "revue" in verdict["detail"].lower()
    assert len(reg.lire()) == taille_avant

# ------------------------------------------------------------------ 19. Chaîne intacte après parcours complet
def test_chaine_intacte_apres_completion():
    reg, i_id = _intervention_sur_site_avec_pointages()
    outbox_mod.completer_intervention(i_id, H_COMPLETION, reg)
    assert reg.valider_chaine() is True
    reg.assert_chaine()  # ne doit pas lever

def test_duree_du_premier_arrivee_au_dernier_depart():
    """DISCRIMINANT de la règle de durée : deux départs, dont un incohérent qui a
    ouvert une revue. La durée doit courir jusqu'au DERNIER départ — prendre le
    premier donnerait 150 minutes au lieu de 160 (mutation mesurée non détectée
    tant qu'un seul départ existait).

    Ce cas n'est pas théorique : c'est exactement ce que produit le chemin de
    revue, et c'est pourquoi la règle « exactement une paire » a été écartée —
    elle rendait toute intervention arbitrée impossible à compléter.
    """
    reg, i_id = _intervention_sur_site_avec_pointages()   # arrivée 09:00, départ 11:30
    acc_anom, verd_anom = pointage_mod.enregistrer_pointage(
        i_id, "T1", "depart", H_ANOMALIE, GPS_LOIN, ATTESTATION,
        ASSIGNATION(i_id), FENETRE, REFERENTIEL, VILLE, SEL, reg,
    )
    assert acc_anom is not None, f"second départ refusé : {verd_anom}"
    assert etats_mod.statut_courant(reg, i_id) == "en_revue"

    duree, code = outbox_mod.calculer_duree_reelle(reg, i_id)
    assert code is None, f"durée refusée à tort : {code}"
    # 09:00 -> 11:40 = 160 minutes (et non 150, qui serait le PREMIER départ)
    assert duree == 160, f"attendu 160 (premier arrivée -> dernier départ), obtenu {duree}"

    # et la complétion qui en découle porte bien cette durée
    acc, verd = outbox_mod.completer_intervention(i_id, H_APRES_ANOMALIE, reg)
    assert acc is not None, f"complétion refusée : {verd}"
    assert acc["duree_reelle_minutes"] == 160

