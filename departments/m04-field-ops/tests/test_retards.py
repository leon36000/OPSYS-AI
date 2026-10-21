"""PLAN T4.27-a : `retards.py`, pur, sur un registre EN MÉMOIRE : les reports en cours et les incidents ouverts que M4
enregistre déjà, avec leur âge. Aucune base, aucun réseau, aucune horloge.

Ce que le relevé doit prouver :

  * il ne montre que du réel : les interventions dont le statut COURANT est `reportee` (motif et heure du DERNIER
    report), les demandes de revue SANS résolution (écart métier, anomalie de pointage) ; rien n'est déduit ni inventé ;
  * l'âge se compte en heures pleines depuis la référence donnée par l'appelant (M4 n'a pas d'horloge) ; une référence
    antérieure au fait ne donne pas d'âge (`None`), jamais un nombre négatif ; « bloquée » dès 24 h, comme le digest ;
  * du plus ancien au plus récent, borné par liste ; le reste est compté, jamais perdu en silence ; `bloques` compte
    TOUTES les demandes bloquées, pas seulement celles qui sont affichées ;
  * le retard sur la cédule est `non_mesurable` et dit pourquoi : le relevé n'écrit jamais « aucun retard » ;
  * rien d'écrit, aucun texte libre du terrain ni contact ni coordonnée ; le module est pur ;
  * chaque ligne dit d'où vient son heure (`origine_heure` : `serveur` ou `appelant`, PLAN T4.27-a2) : ici, des faits
    inscrits sans heure d'appareil, donc `appelant` ; l'origine elle-même est prouvée dans `test_origine_heure.py`.

Le scénario par les vrais outils et la porte d'appareil : `test_retards_outil.py`, `test_heure_du_serveur_outils.py` et
`tests/e2e/test_lectures_admin_m4_appareil.py`. Tout est fictif (`fictif: true`).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from m4_field_ops import digest, ecarts, etats, pointage, retards, verdicts
from m4_field_ops.registre import Registre

FICTIF = True
_SRC = Path(retards.__file__).resolve()
SEL = "sel-t4-27-a-fictif"
INSCRIPTION = "2030-01-01T06:00:00+00:00"
REFERENCE = "2030-01-03T09:30:00+00:00"


def _contrat(lead_id):
    return {
        "lead_id": lead_id,
        "conversation_id": f"C-{lead_id}",
        "type_travaux": "renovation_totale",
        "ville": "Montreal",
        "canal": "telephone",
        "contact": {"nom": "Client fictif", "telephone": "0102030405"},
        "urgence_declaree": False,
    }


def _marqueur(lead_id):
    return {
        "readiness_ok": True,
        "lead_id": lead_id,
        "hash_tete_registre": None,
        "horodatage": "2030-01-01T05:00:00+00:00",
        "empreinte": "ab" * 32,
    }


def _inscrire(registre, lead_id):
    accuse, verdict = etats.inscrire_intervention(_contrat(lead_id), _marqueur(lead_id), registre, INSCRIPTION, SEL)
    assert verdict is None, verdict
    return accuse["intervention_id"]


def _reporter(registre, identifiant, motif, horodatage):
    _, verdict = etats.transitionner(identifiant, "reportee", registre, horodatage, motif=motif)
    assert verdict is None, verdict


def _ecart(registre, identifiant, horodatage, perimetre="PERIMETRE-LIBRE-DU-TERRAIN"):
    accuse, verdict = ecarts.creer_demande_ecart(
        identifiant,
        {"duree_minutes": 60, "perimetre": "perimetre prevu", "materiaux": ["MATERIAU-PREVU-FICTIF"]},
        {"duree_minutes": 90, "perimetre": perimetre, "materiaux": ["MATERIAU-DECLARE-FICTIF"]},
        horodatage,
        registre,
    )
    assert verdict is None, verdict
    return accuse["demande_id"]


def _anomalie(registre, identifiant, horodatage, numero=1):
    """Une anomalie de pointage ouverte : le maillon que `pointage.enregistrer_pointage` écrit (voir ce module)."""
    demande_id = f"demande-anomalie-{numero}-fictive"
    registre.ajouter(
        {
            "type_entree": pointage.TYPE_DEMANDE_REVUE,
            "intervention_id": identifiant,
            "horodatage": horodatage,
            "type_demande": pointage.TYPE_REVUE_ANOMALIE,
            "demande_id": demande_id,
            "statut_arbitrage": "en_attente",
        }
    )
    return demande_id


def _resoudre(registre, demande_id, identifiant, horodatage):
    """Une résolution au registre, sans autre effet (le statut de l'intervention ne bouge pas)."""
    registre.ajouter(
        {
            "type_entree": ecarts.TYPE_RESOLUTION,
            "intervention_id": identifiant,
            "horodatage": horodatage,
            "demande_id": demande_id,
            "decision": "validee",
            "statut_arbitrage": "validee",
            "resolution_id": f"resolution-{demande_id}",
        }
    )


def _lire(registre, reference=REFERENCE, limite=None):
    releve, verdict = retards.lire(registre, reference, limite)
    assert verdict is None, verdict
    return releve


def _octets(objet):
    return json.dumps(objet, sort_keys=True, ensure_ascii=False)


# =========================================================================================
# 1. Rien d'enregistré : des listes vides, jamais « aucun retard »
# =========================================================================================
def test_un_registre_vide_donne_des_listes_vides_et_le_retard_sur_la_cedule_reste_non_mesurable():
    releve = _lire(Registre())
    assert releve["type"] == "RETARDS_INCIDENTS" and releve["reference"] == REFERENCE
    assert releve["reports"] == {
        "total": 0,
        "par_motif": {"client_absent": 0, "meteo": 0, "decision_admin": 0},
        "affiches": 0,
        "reste": 0,
        "suite": None,
        "liste": [],
    }
    assert releve["incidents"] == {
        "total": 0,
        "par_type": {"ecart_metier": 0, "anomalie_pointage": 0},
        "bloques": 0,
        "affiches": 0,
        "reste": 0,
        "suite": None,
        "liste": [],
    }
    assert releve["retard_sur_cedule"] == {"statut": "non_mesurable", "manque": retards.MANQUE_RETARD_SUR_CEDULE}
    assert "calendrier" in retards.MANQUE_RETARD_SUR_CEDULE and "sans date civile" in retards.MANQUE_RETARD_SUR_CEDULE


def test_le_relevé_n_ecrit_jamais_aucun_retard_meme_sans_rien_a_montrer():
    texte = json.dumps(_lire(Registre()), ensure_ascii=False).lower()
    assert "aucun retard" not in texte, "un relevé vide ne prétend pas qu'il n'y a pas de retard"
    assert "non_mesurable" in texte


def test_les_cles_du_releve_sont_exactement_celles_du_contrat():
    releve = _lire(Registre())
    assert set(releve) == {
        "type",
        "reference",
        "seuil_blocage_heures",
        "reports",
        "incidents",
        "retard_sur_cedule",
    }
    assert set(releve["reports"]) == {"total", "par_motif", "affiches", "reste", "suite", "liste"}
    assert set(releve["incidents"]) == {"total", "par_type", "bloques", "affiches", "reste", "suite", "liste"}


def test_le_seuil_de_blocage_est_celui_du_digest_pas_un_second():
    assert retards.SEUIL_BLOCAGE_HEURES == digest.SEUIL_BLOCAGE_HEURES == 24
    assert _lire(Registre())["seuil_blocage_heures"] == digest.SEUIL_BLOCAGE_HEURES


# =========================================================================================
# 2. Les reports : les interventions reportées MAINTENANT, motif et heure du dernier report
# =========================================================================================
def test_un_report_montre_l_intervention_le_motif_l_heure_et_l_age_en_heures_pleines():
    registre = Registre()
    identifiant = _inscrire(registre, "L-1")
    _reporter(registre, identifiant, "meteo", "2030-01-01T08:00:00+00:00")
    releve = _lire(registre, "2030-01-03T09:30:00+00:00")  # 49 h 30 plus tard
    assert releve["reports"]["liste"] == [
        {
            "intervention_id": identifiant,
            "motif": "meteo",
            "depuis": "2030-01-01T08:00:00+00:00",
            "origine_heure": "appelant",  # inscrit sans heure d'appareil : l'heure est celle de l'appelant
            "heures_ecoulees": 49,
        }
    ]
    assert releve["reports"]["total"] == 1 and releve["reports"]["par_motif"]["meteo"] == 1


def test_l_age_est_en_heures_pleines_sans_arrondi_vers_le_haut():
    registre = Registre()
    identifiant = _inscrire(registre, "L-1")
    _reporter(registre, identifiant, "client_absent", "2030-01-01T08:00:00+00:00")
    for reference, heures in (
        ("2030-01-01T08:00:00+00:00", 0),
        ("2030-01-01T08:59:59+00:00", 0),
        ("2030-01-01T09:00:00+00:00", 1),
        ("2030-01-02T07:59:59+00:00", 23),
        ("2030-01-02T08:00:00+00:00", 24),
    ):
        assert _lire(registre, reference)["reports"]["liste"][0]["heures_ecoulees"] == heures, reference


def test_seuls_les_reports_en_cours_sont_montres_pas_l_historique():
    registre = Registre()
    encore = _inscrire(registre, "L-encore")
    replanifiee = _inscrire(registre, "L-replanifiee")
    annulee = _inscrire(registre, "L-annulee")
    planifiee = _inscrire(registre, "L-planifiee")
    for identifiant in (encore, replanifiee, annulee):
        _reporter(registre, identifiant, "client_absent", "2030-01-01T08:00:00+00:00")
    assert etats.transitionner(replanifiee, "planifiee", registre, "2030-01-01T09:00:00+00:00")[1] is None
    assert etats.transitionner(annulee, "annulee", registre, "2030-01-01T09:00:00+00:00")[1] is None
    releve = _lire(registre)
    assert [ligne["intervention_id"] for ligne in releve["reports"]["liste"]] == [encore]
    assert releve["reports"]["total"] == 1
    assert planifiee not in json.dumps(releve), "une intervention planifiée n'est ni un report ni un retard"


def test_le_dernier_report_fait_foi_pour_le_motif_et_l_heure():
    registre = Registre()
    identifiant = _inscrire(registre, "L-1")
    _reporter(registre, identifiant, "meteo", "2030-01-01T08:00:00+00:00")
    assert etats.transitionner(identifiant, "planifiee", registre, "2030-01-01T10:00:00+00:00")[1] is None
    _reporter(registre, identifiant, "client_absent", "2030-01-02T07:00:00+00:00")
    releve = _lire(registre, "2030-01-02T09:00:00+00:00")
    (ligne,) = releve["reports"]["liste"]
    assert (ligne["motif"], ligne["depuis"], ligne["heures_ecoulees"]) == (
        "client_absent",
        "2030-01-02T07:00:00+00:00",
        2,
    )
    assert releve["reports"]["par_motif"] == {"client_absent": 1, "meteo": 0, "decision_admin": 0}


def test_les_motifs_sont_ventiles_et_les_reports_vont_du_plus_ancien_au_plus_recent():
    registre = Registre()
    a, b, c, d = (_inscrire(registre, f"L-{numero}") for numero in range(4))
    _reporter(registre, a, "decision_admin", "2030-01-02T08:00:00+00:00")
    _reporter(registre, b, "meteo", "2030-01-01T08:00:00+00:00")
    _reporter(registre, c, "meteo", "2030-01-02T20:00:00+00:00")
    _reporter(registre, d, "client_absent", "2030-01-01T20:00:00+00:00")
    releve = _lire(registre)
    assert [ligne["intervention_id"] for ligne in releve["reports"]["liste"]] == [b, d, a, c]
    assert releve["reports"]["par_motif"] == {"client_absent": 1, "meteo": 2, "decision_admin": 1}
    assert [ligne["heures_ecoulees"] for ligne in releve["reports"]["liste"]] == [49, 37, 25, 13]


def test_a_heure_egale_l_ordre_est_celui_de_l_identifiant():
    registre = Registre()
    ids = [_inscrire(registre, f"L-{numero}") for numero in range(4)]
    for identifiant in ids:
        _reporter(registre, identifiant, "meteo", "2030-01-01T08:00:00+00:00")
    releve = _lire(registre)
    assert [ligne["intervention_id"] for ligne in releve["reports"]["liste"]] == sorted(ids)


def test_l_ordre_compare_des_instants_pas_des_textes_meme_avec_des_fuseaux_differents():
    registre = Registre()
    tot, tard = _inscrire(registre, "L-tot"), _inscrire(registre, "L-tard")
    _reporter(registre, tard, "meteo", "2030-01-01T08:00:00-05:00")  # 13 h 00 UTC
    _reporter(registre, tot, "meteo", "2030-01-01T10:00:00+00:00")  # 10 h 00 UTC, mais « plus grand » en texte
    releve = _lire(registre, "2030-01-01T14:00:00+00:00")
    assert [ligne["intervention_id"] for ligne in releve["reports"]["liste"]] == [tot, tard]
    assert [ligne["heures_ecoulees"] for ligne in releve["reports"]["liste"]] == [4, 1]


# =========================================================================================
# 3. Les incidents : les demandes de revue sans résolution
# =========================================================================================
def test_un_incident_montre_la_demande_l_intervention_le_type_l_heure_et_l_age():
    registre = Registre()
    identifiant = _inscrire(registre, "L-1")
    demande = _ecart(registre, identifiant, "2030-01-02T08:00:00+00:00")
    releve = _lire(registre, "2030-01-02T10:15:00+00:00")
    assert releve["incidents"]["liste"] == [
        {
            "demande_id": demande,
            "intervention_id": identifiant,
            "type_demande": "ecart_metier",
            "depuis": "2030-01-02T08:00:00+00:00",
            "origine_heure": "appelant",
            "heures_ecoulees": 2,
            "bloquee": False,
        }
    ]
    assert releve["incidents"]["total"] == 1 and releve["incidents"]["par_type"] == {
        "ecart_metier": 1,
        "anomalie_pointage": 0,
    }


def test_une_demande_resolue_n_est_plus_un_incident():
    registre = Registre()
    a, b = _inscrire(registre, "L-a"), _inscrire(registre, "L-b")
    resolue = _anomalie(registre, a, "2030-01-01T08:00:00+00:00", 1)
    ouverte = _anomalie(registre, b, "2030-01-01T09:00:00+00:00", 2)
    _resoudre(registre, resolue, a, "2030-01-01T10:00:00+00:00")
    releve = _lire(registre)
    assert [ligne["demande_id"] for ligne in releve["incidents"]["liste"]] == [ouverte]
    assert releve["incidents"]["total"] == 1 and releve["incidents"]["par_type"]["anomalie_pointage"] == 1


def test_bloquee_des_vingt_quatre_heures_pile_comme_le_digest():
    registre = Registre()
    ids = [_inscrire(registre, f"L-{numero}") for numero in range(3)]
    juste_avant = _ecart(registre, ids[0], "2030-01-02T09:30:01+00:00")  # 23 h 59 min 59 s
    pile = _ecart(registre, ids[1], "2030-01-02T09:30:00+00:00")  # 24 h 00
    plus = _ecart(registre, ids[2], "2030-01-01T09:30:00+00:00")  # 48 h
    releve = _lire(registre, "2030-01-03T09:30:00+00:00")
    par_demande = {ligne["demande_id"]: ligne for ligne in releve["incidents"]["liste"]}
    assert (par_demande[juste_avant]["heures_ecoulees"], par_demande[juste_avant]["bloquee"]) == (23, False)
    assert (par_demande[pile]["heures_ecoulees"], par_demande[pile]["bloquee"]) == (24, True)
    assert (par_demande[plus]["heures_ecoulees"], par_demande[plus]["bloquee"]) == (48, True)
    assert releve["incidents"]["bloques"] == 2


def test_le_meme_seuil_que_le_digest_les_memes_demandes_bloquees():
    """Le digest et le relevé disent la même chose des demandes bloquées, pour la même référence."""
    registre = Registre()
    ids = [_inscrire(registre, f"L-{numero}") for numero in range(4)]
    for numero, identifiant in enumerate(ids):
        _ecart(registre, identifiant, f"2030-01-0{1 + numero % 3}T{6 + numero:02d}:00:00+00:00")
    du_digest, verdict = digest.produire_digest(registre, "2030-01-03", REFERENCE)
    assert verdict is None
    bloquees_du_digest = {ligne["demande_id"] for ligne in du_digest["interventions_bloquees_en_revue"]}
    releve = _lire(registre)
    bloquees_du_releve = {ligne["demande_id"] for ligne in releve["incidents"]["liste"] if ligne["bloquee"]}
    assert bloquees_du_releve == bloquees_du_digest and releve["incidents"]["bloques"] == len(bloquees_du_digest)


def test_les_incidents_vont_du_plus_ancien_au_plus_recent_a_heure_egale_par_identifiant_de_demande():
    registre = Registre()
    ids = [_inscrire(registre, f"L-{numero}") for numero in range(3)]
    recente = _anomalie(registre, ids[0], "2030-01-03T08:00:00+00:00", 1)
    ancienne = _anomalie(registre, ids[1], "2030-01-01T08:00:00+00:00", 2)
    egale_b = _anomalie(registre, ids[2], "2030-01-02T08:00:00+00:00", 4)
    egale_a = _anomalie(registre, ids[1], "2030-01-02T08:00:00+00:00", 3)
    releve = _lire(registre)
    assert [ligne["demande_id"] for ligne in releve["incidents"]["liste"]] == [ancienne, egale_a, egale_b, recente]


def test_les_deux_types_d_incident_sont_comptes_separement():
    registre = Registre()
    a, b, c = (_inscrire(registre, f"L-{numero}") for numero in range(3))
    _ecart(registre, a, "2030-01-02T08:00:00+00:00")
    _anomalie(registre, b, "2030-01-02T09:00:00+00:00", 1)
    _anomalie(registre, c, "2030-01-02T10:00:00+00:00", 2)
    releve = _lire(registre)
    assert releve["incidents"]["par_type"] == {"ecart_metier": 1, "anomalie_pointage": 2}
    assert [ligne["type_demande"] for ligne in releve["incidents"]["liste"]] == [
        "ecart_metier",
        "anomalie_pointage",
        "anomalie_pointage",
    ]


# =========================================================================================
# 4. Bornes : le reste est compté, jamais perdu en silence ; `bloques` compte tout
# =========================================================================================
def test_la_limite_de_chaque_liste_est_de_huit_par_defaut():
    assert retards.LIMITE_PAR_LISTE == 8
    registre = Registre()
    for numero in range(11):
        identifiant = _inscrire(registre, f"L-{numero:02d}")
        _reporter(registre, identifiant, "meteo", f"2030-01-01T{numero:02d}:00:00+00:00")
        _anomalie(registre, identifiant, f"2030-01-01T{numero:02d}:30:00+00:00", numero)
    releve = _lire(registre)
    for cle in ("reports", "incidents"):
        assert (releve[cle]["total"], releve[cle]["affiches"], releve[cle]["reste"]) == (11, 8, 3)
        assert len(releve[cle]["liste"]) == 8


def test_ce_qui_ne_tient_pas_est_compte_et_l_outil_qui_le_rend_est_nomme():
    registre = Registre()
    for numero in range(5):
        identifiant = _inscrire(registre, f"L-{numero}")
        _reporter(registre, identifiant, "meteo", f"2030-01-01T0{numero}:00:00+00:00")
        _ecart(registre, identifiant, f"2030-01-01T0{numero}:30:00+00:00")
    releve = _lire(registre, limite=2)
    assert (releve["reports"]["affiches"], releve["reports"]["reste"], releve["reports"]["total"]) == (2, 3, 5)
    assert releve["reports"]["suite"] == (
        "3 de plus, du moins ancien au plus récent : m4_lister_interventions (statut reportee) les rend tous"
    )
    assert (releve["incidents"]["affiches"], releve["incidents"]["reste"]) == (2, 3)
    assert releve["incidents"]["suite"] == (
        "3 de plus, du moins ancien au plus récent : m4_lister_pending_review les rend tous"
    )
    # les plus anciens d'abord : ce qui reste est le plus récent
    assert [ligne["depuis"][11:13] for ligne in releve["reports"]["liste"]] == ["00", "01"]


def test_les_bloques_comptent_toutes_les_demandes_pas_seulement_celles_qui_sont_affichees():
    registre = Registre()
    for numero in range(6):
        identifiant = _inscrire(registre, f"L-{numero}")
        _ecart(registre, identifiant, f"2030-01-01T0{numero}:00:00+00:00")  # toutes bloquées (plus de 24 h)
    releve = _lire(registre, limite=2)
    assert releve["incidents"]["affiches"] == 2 and releve["incidents"]["total"] == 6
    assert releve["incidents"]["bloques"] == 6


def test_une_limite_a_zero_ne_montre_rien_mais_compte_tout():
    registre = Registre()
    identifiant = _inscrire(registre, "L-1")
    _reporter(registre, identifiant, "meteo", "2030-01-01T08:00:00+00:00")
    releve = _lire(registre, limite=0)
    assert releve["reports"]["liste"] == [] and releve["reports"]["total"] == 1 and releve["reports"]["reste"] == 1


def test_le_relevé_le_plus_gros_tient_dans_une_reponse_d_appareil():
    """Huit reports et huit incidents de la taille maximale : le relevé reste sous la borne d'une réponse (5 500)."""
    registre = Registre()
    for numero in range(20):
        identifiant = _inscrire(registre, f"L-{numero:02d}")
        _reporter(registre, identifiant, "decision_admin", f"2030-01-01T10:{numero:02d}:00.123456-04:00")
        _anomalie(registre, identifiant, f"2030-01-01T11:{numero:02d}:00.123456-04:00", numero)
    releve = _lire(registre, "2099-12-31T23:59:59.999999-04:00")
    enveloppe = {"ok": True, "resultat": {"accepte": True, "resultat": releve}}
    assert len(json.dumps(enveloppe, ensure_ascii=False)) < 5500
    assert releve["reports"]["affiches"] == releve["incidents"]["affiches"] == 8


# =========================================================================================
# 5. L'âge : la référence de l'appelant, jamais une horloge
# =========================================================================================
def test_une_reference_anterieure_au_fait_ne_donne_pas_d_age_jamais_un_nombre_negatif():
    registre = Registre()
    identifiant = _inscrire(registre, "L-1")
    _reporter(registre, identifiant, "meteo", "2030-01-02T12:00:00+00:00")
    demande = _ecart(registre, identifiant, "2030-01-02T12:00:00+00:00")
    releve = _lire(registre, "2030-01-02T11:59:59+00:00")  # l'horloge de l'appareil retarde d'une seconde
    assert releve["reports"]["liste"][0]["heures_ecoulees"] is None
    ligne = releve["incidents"]["liste"][0]
    assert ligne["demande_id"] == demande and ligne["heures_ecoulees"] is None and ligne["bloquee"] is False
    assert releve["incidents"]["bloques"] == 0
    egale = _lire(registre, "2030-01-02T12:00:00+00:00")
    assert egale["reports"]["liste"][0]["heures_ecoulees"] == 0


def test_la_reference_et_les_faits_peuvent_avoir_des_fuseaux_differents():
    registre = Registre()
    identifiant = _inscrire(registre, "L-1")
    _reporter(registre, identifiant, "meteo", "2030-01-01T08:00:00-05:00")  # 13 h 00 UTC
    releve = _lire(registre, "2030-01-02T14:00:00+01:00")  # 13 h 00 UTC le lendemain
    assert releve["reports"]["liste"][0]["heures_ecoulees"] == 24


@pytest.mark.parametrize(
    "reference",
    ["", "hier", "2030-01-03", "2030-01-03T09:30:00", "2030-13-03T09:30:00+00:00", None, 20300103, ["2030-01-03"]],
)
def test_une_reference_illisible_est_refusee_sans_rien_deviner(reference):
    registre = Registre()
    _inscrire(registre, "L-1")
    avant = _octets(registre.lire())
    releve, verdict = retards.lire(registre, reference)
    assert releve is None and verdict["code"] == "REJ-HORODATAGE-INVALIDE"
    assert "horodatage_reference" in verdict["detail"] and "fuseau" in verdict["detail"]
    assert _octets(registre.lire()) == avant


# =========================================================================================
# 6. Lecture pure : rien d'écrit, aucun texte libre du terrain, ni contact ni coordonnée
# =========================================================================================
def test_le_relevé_n_ecrit_rien_est_deterministe_et_serialisable():
    registre = Registre()
    identifiant = _inscrire(registre, "L-1")
    _reporter(registre, identifiant, "meteo", "2030-01-01T08:00:00+00:00")
    _ecart(registre, identifiant, "2030-01-01T09:00:00+00:00")
    avant = _octets(registre.lire())
    premier = _lire(registre)
    assert _octets(registre.lire()) == avant and registre.valider_chaine()
    assert _octets(premier) == _octets(_lire(registre))
    assert json.loads(json.dumps(premier)) == premier


def test_aucun_texte_libre_du_terrain_ni_contact_ne_sort_du_relevé():
    registre = Registre()
    identifiant = _inscrire(registre, "L-1")
    _reporter(registre, identifiant, "client_absent", "2030-01-01T08:00:00+00:00")
    _ecart(registre, identifiant, "2030-01-01T09:00:00+00:00", perimetre="PERIMETRE-LIBRE-DU-TERRAIN")
    texte = json.dumps(_lire(registre), ensure_ascii=False)
    for interdit in (
        "PERIMETRE-LIBRE-DU-TERRAIN",
        "perimetre",
        "MATERIAU-DECLARE-FICTIF",
        "MATERIAU-PREVU-FICTIF",
        "materiaux",
        "Client fictif",
        "0102030405",
        "Montreal",
        "latitude",
        "longitude",
        "prix",
        "montant",
        "duree_minutes",
    ):
        assert interdit not in texte, interdit


def test_le_relevé_ne_prend_ni_score_ni_classement_de_technicien():
    """Aucune notion de performance d'un technicien (CA-M4-16 : jamais de notation ni de sanction automatique)."""
    releve = _lire(Registre())
    for cle in ("technicien", "technicien_assigne", "equipe", "score", "performance"):
        assert cle not in json.dumps(releve)


def test_reports_courants_et_incidents_ouverts_lisent_un_registre_ou_un_instantane():
    registre = Registre()
    identifiant = _inscrire(registre, "L-1")
    _reporter(registre, identifiant, "meteo", "2030-01-01T08:00:00+00:00")
    demande = _ecart(registre, identifiant, "2030-01-01T09:00:00+00:00")
    assert retards.reports_courants(registre) == [
        {
            "intervention_id": identifiant,
            "motif": "meteo",
            "depuis": "2030-01-01T08:00:00+00:00",
            "origine_heure": "appelant",
        }
    ]
    assert retards.incidents_ouverts(registre) == [
        {
            "demande_id": demande,
            "intervention_id": identifiant,
            "type_demande": "ecart_metier",
            "depuis": "2030-01-01T09:00:00+00:00",
            "origine_heure": "appelant",
        }
    ]


# =========================================================================================
# 7. Le présentateur
# =========================================================================================
def test_le_presentateur_rend_le_releve_s_il_tient_sinon_refuse_avec_la_consigne():
    releve = _lire(Registre())
    vue, verdict = retards.presenter(releve, lambda r: True)
    assert verdict is None and vue is releve
    vue, verdict = retards.presenter(releve, lambda r: False)
    assert vue is None and verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert "trop grand" in verdict["detail"]
    assert "m4_lister_pending_review" in verdict["detail"] and "reportee" in verdict["detail"]
    assert verdicts.est_verdict(verdict["code"])


# =========================================================================================
# 8. Garde par analyse du code : pur, sans horloge, sans écriture, sans stub
# =========================================================================================
def _arbre():
    return ast.parse(_SRC.read_text(encoding="utf-8"))


def test_le_module_est_pur_sans_opsys_reseau_horloge_alea_ni_ecriture():
    autorises = {"__future__", "datetime"}
    for noeud in ast.walk(_arbre()):
        if isinstance(noeud, ast.Import):
            for alias in noeud.names:
                assert alias.name in autorises, alias.name
        if isinstance(noeud, ast.ImportFrom):
            assert noeud.module in autorises or noeud.level == 1, (noeud.module, noeud.level)
            if noeud.level == 1:
                assert {a.name for a in noeud.names} == {
                    "cedule_tournees",
                    "digest",
                    "ecarts",
                    "etats",
                    "horodatage",
                    "pointage",
                    "verdicts",
                }
        if isinstance(noeud, ast.Attribute):
            assert noeud.attr not in {
                "now",
                "utcnow",
                "today",
                "time",
                "random",
                "urandom",
                "monotonic",
                "ajouter",
                "extend",
                "append_maillon",
            }
        if isinstance(noeud, ast.Name):
            assert noeud.id not in {"random", "time", "socket", "float", "opsys", "os", "sys", "open"}


def test_le_module_ne_lit_aucune_horloge_selon_la_garde_du_digest():
    ok, message = digest.garde_absence_horloge(str(_SRC.parent))
    assert ok, message


def test_le_module_respecte_la_garde_de_conformite_r020_du_digest():
    ok, message = digest.garde_conformite_r020(str(_SRC.parent))
    assert ok, message


def test_aucun_stub_ni_todo_dans_le_module():
    texte = _SRC.read_text(encoding="utf-8")
    assert "TODO" not in texte and "FIXME" not in texte and "NotImplementedError" not in texte
    for noeud in ast.walk(_arbre()):
        if isinstance(noeud, ast.FunctionDef):
            corps = [n for n in noeud.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant))]
            assert corps and not all(isinstance(n, ast.Pass) for n in corps), noeud.name


def test_les_codes_de_verdict_du_module_sont_tous_au_catalogue():
    codes = {
        n.value
        for n in ast.walk(_arbre())
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value.startswith("REJ-")
    }
    assert codes and codes <= verdicts.CODES_M4, codes - verdicts.CODES_M4
