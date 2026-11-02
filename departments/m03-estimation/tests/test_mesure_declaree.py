"""Mesure déclarée (M3-C2) : enregistrement d'une personne avec bornes, révision, suffisance et revue. Horloge injectée.

Module pur. Données fictives. Les seuils de largeur relative sont ceux d'un barème DÉCLARÉ (jamais dans le code testé).
"""

from __future__ import annotations

import sys
from copy import deepcopy
from datetime import timedelta
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
_SRC = Path(__file__).resolve().parents[1] / "src"  # la source de CE département (la copie jetable des mutations)
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import _commun_bareme as cb  # noqa: E402
from m3_estimation import mesure_declaree, verdicts  # noqa: E402
from m3_estimation.registre import _encoder_canonique  # noqa: E402

PARAMS = {"largeur_relative_revue": "0.15", "largeur_relative_max_prix": "0.50", "validite_jours": 30}


def _evaluer(mesure, **surcharges):
    arguments = {"unite_attendue": "pi2", "parametres_mesure": PARAMS, "maintenant": cb.MAINTENANT}
    arguments.update(surcharges)
    return mesure_declaree.evaluer(mesure, **arguments)


def _rechainer(journal):
    precedent = None
    for rang, m in enumerate(journal):
        m["rang"], m["precedent"] = rang, precedent
        m["source_id"] = _encoder_canonique({k: v for k, v in m.items() if k != "source_id"})
        precedent = m["source_id"]


# ----------------------------------------------------------------------------------------- déclaration, lecture
def test_declarer_une_mesure_garde_auteur_methode_bornes_pieces_et_confiance():
    journal = []
    m = cb.mesurer_ok(journal, valeur="120.5", borne_basse="118", borne_haute="125", methode="plan",
                      confiance="moyenne")
    assert (m["valeur"], m["borne_basse"], m["borne_haute"]) == ("120.5", "118", "125")
    assert m["auteur"] == cb.ADMIN and m["methode"] == "plan" and m["confiance"] == "moyenne"
    assert m["pieces"] == ["photo-fictive-1", "croquis-fictif-1"] and m["revision"] == 1
    assert m["lead_id"] == cb.LEAD and m["service"] == cb.SERVICE and len(m["empreinte"]) == 64
    lue, verdict = mesure_declaree.lire(journal, "mesure-fictive-1")
    assert verdict is None and lue == m


def test_une_revision_ajoute_sans_ecraser_et_l_ancienne_reste_lisible():
    journal = []
    r1 = cb.mesurer_ok(journal, valeur="1200", borne_basse="1000", borne_haute="1400", methode="estimation_grossiere")
    r2 = cb.mesurer_ok(journal, revision_attendue=1, valeur="1180", borne_basse="1175", borne_haute="1185",
                       horodatage="2026-11-02T11:00:00+00:00")
    assert (r1["revision"], r2["revision"]) == (1, 2) and len(journal) == 2
    ancienne, _ = mesure_declaree.lire(journal, "mesure-fictive-1", 1)
    assert ancienne == r1
    derniere, _ = mesure_declaree.lire(journal, "mesure-fictive-1")
    assert derniere == r2
    assert journal[1]["precedent"] == journal[0]["source_id"]


def test_rejeu_et_revision_perimee():
    journal = []
    r1 = cb.mesurer_ok(journal)
    resultat, verdict = cb.mesurer(journal)
    assert verdict is None and resultat["rejoue"] is True and resultat["mesure"] == r1 and len(journal) == 1
    cb.mesurer_ok(journal, revision_attendue=1, valeur="1250", borne_basse="1250", borne_haute="1250")
    _, verdict = cb.mesurer(journal, revision_attendue=1, valeur="1300", borne_basse="1300", borne_haute="1300")
    assert cb.code(verdict) == "REJ-MESURE-REVISION-PERIMEE" and "révision 2" in verdict["detail"]


def test_une_revision_ne_change_ni_le_lead_ni_le_service():
    journal = []
    cb.mesurer_ok(journal)
    _, verdict = cb.mesurer(journal, revision_attendue=1, lead_id="lead-autre")
    assert cb.code(verdict) == "REJ-MESURE-INVALIDE" and "nouvelle mesure" in verdict["detail"]
    assert len(journal) == 1


@pytest.mark.parametrize("changement, extrait", [
    ({"valeur": 1200}, "valeur"),                                   # nombre JSON : refusé
    ({"valeur": "0"}, "valeur"),
    ({"valeur": "-5"}, "valeur"),
    ({"valeur": "1e3"}, "valeur"),
    ({"valeur": "abc"}, "valeur"),
    ({"borne_basse": "1300"}, "encadrer"),                          # valeur sous la borne basse
    ({"borne_haute": "1100"}, "encadrer"),                          # valeur au-dessus de la borne haute
    ({"methode": "devinette"}, "methode"),
    ({"confiance": "totale"}, "confiance"),
    ({"unite": ""}, "unite"),
    ({"grandeur": ""}, "grandeur"),
    ({"pieces": "photo"}, "pieces"),
    ({"pieces": ["a", "a"]}, "pieces"),
    ({"pieces": ["p" + str(i) for i in range(21)]}, "pieces"),
    ({"pieces": ["https://exemple.test/photo.jpg"]}, "pieces"),       # une pièce est une référence, pas une URL
    ({"mesure_le": "2026-11-02"}, "mesure_le"),
    ({"mesure_le": "2026-11-02T09:00:00"}, "mesure_le"),
    ({"mesure_id": "mauvais id"}, "mesure_id"),
    ({"lead_id": ""}, "lead_id"),
    ({"service": "x y"}, "service"),
])
def test_mesure_invalide_est_refusee_avec_le_champ_fautif(changement, extrait):
    journal = []
    _, verdict = cb.mesurer(journal, **changement)
    assert cb.code(verdict) == "REJ-MESURE-INVALIDE" and extrait in verdict["detail"], verdict
    assert journal == []


def test_bornes_egales_a_la_valeur_sont_admises_et_la_mesure_ne_peut_pas_etre_dans_le_futur():
    journal = []
    cb.mesurer_ok(journal, valeur="100", borne_basse="100", borne_haute="100")
    _, verdict = cb.mesurer(journal, mesure_id="m2", mesure_le="2026-11-02T10:00:01+00:00",
                            horodatage="2026-11-02T10:00:00+00:00")
    assert cb.code(verdict) == "REJ-MESURE-INVALIDE" and "postérieure" in verdict["detail"]
    cb.mesurer_ok(journal, mesure_id="m3", mesure_le="2026-11-02T10:00:00+00:00",
                  horodatage="2026-11-02T10:00:00+00:00")


@pytest.mark.parametrize("auteur", [
    None, {}, {"personne": "agent.mathis", "role": "system_agent"}, {"personne": "c", "role": "client"},
    {"personne": "emp", "role": "employee"}, {"personne": "", "role": "admin"}, "admin.fictif",
    {"personne": "admin.fictif", "role": "admin", "extra": 1},
])
def test_une_mesure_n_est_jamais_declaree_par_un_agent_ni_un_modele(auteur):
    journal = []
    _, verdict = cb.mesurer(journal, auteur=auteur)
    assert cb.code(verdict) == "REJ-MESURE-IDENTITE" and "jamais par un agent" in verdict["detail"]
    assert journal == []


def test_proprietaire_admin_et_vendeur_peuvent_declarer():
    for auteur, numero in ((cb.PROPRIO, 1), (cb.ADMIN, 2), (cb.VENDEUR, 3)):
        cb.mesurer_ok([], auteur=auteur, mesure_id=f"m{numero}")


def test_lecture_d_une_mesure_inconnue_dit_quoi_faire():
    journal = []
    cb.mesurer_ok(journal)
    _, verdict = mesure_declaree.lire(journal, "inconnue")
    assert cb.code(verdict) == "REJ-MESURE-INTROUVABLE" and "m3_declarer_mesure" in verdict["detail"]
    _, verdict = mesure_declaree.lire(journal, "mesure-fictive-1", 4)
    assert cb.code(verdict) == "REJ-MESURE-INTROUVABLE" and "dernière révision : 1" in verdict["detail"]


# ------------------------------------------------------------------------------------------------ référence
def test_resoudre_refuse_une_mesure_d_un_autre_lead_ou_d_un_autre_service():
    journal = []
    cb.mesurer_ok(journal)
    ref = {"mesure_id": "mesure-fictive-1"}
    ok, verdict = mesure_declaree.resoudre(journal, ref, cb.LEAD, cb.SERVICE)
    assert verdict is None and ok["lead_id"] == cb.LEAD
    _, verdict = mesure_declaree.resoudre(journal, ref, "lead-autre", cb.SERVICE)
    assert cb.code(verdict) == "REJ-MESURE-AUTRE-LEAD" and "CE chantier" in verdict["detail"]
    _, verdict = mesure_declaree.resoudre(journal, ref, cb.LEAD, "extension")
    assert cb.code(verdict) == "REJ-MESURE-AUTRE-LEAD" and "service" in verdict["detail"]


def test_resoudre_sans_reference_dit_quoi_declarer_et_verifie_l_empreinte():
    journal = []
    m = cb.mesurer_ok(journal)
    _, verdict = mesure_declaree.resoudre(journal, None, cb.LEAD, cb.SERVICE)
    assert cb.code(verdict) == "REJ-MESURE-REQUISE" and "m3_declarer_mesure" in verdict["detail"]
    for mauvaise in ({}, {"mesure_id": "mesure-fictive-1", "extra": 1}, "mesure-fictive-1",
                     {"mesure_id": "mesure-fictive-1", "empreinte": "xyz"}):
        _, verdict = mesure_declaree.resoudre(journal, mauvaise, cb.LEAD, cb.SERVICE)
        assert cb.code(verdict) == "REJ-MESURE-REQUISE"
    _, verdict = mesure_declaree.resoudre(
        journal, {"mesure_id": "mesure-fictive-1", "empreinte": "0" * 64}, cb.LEAD, cb.SERVICE)
    assert cb.code(verdict) == "REJ-MESURE-ALTEREE"
    ok, verdict = mesure_declaree.resoudre(
        journal, {"mesure_id": "mesure-fictive-1", "revision": 1, "empreinte": m["empreinte"]}, cb.LEAD, cb.SERVICE)
    assert verdict is None and ok == m


def test_resoudre_sans_revision_prend_la_derniere_et_avec_revision_la_demandee():
    journal = []
    cb.mesurer_ok(journal, valeur="100", borne_basse="100", borne_haute="100")
    cb.mesurer_ok(journal, revision_attendue=1, valeur="110", borne_basse="110", borne_haute="110")
    derniere, _ = mesure_declaree.resoudre(journal, {"mesure_id": "mesure-fictive-1"}, cb.LEAD, cb.SERVICE)
    premiere, _ = mesure_declaree.resoudre(
        journal, {"mesure_id": "mesure-fictive-1", "revision": 1}, cb.LEAD, cb.SERVICE)
    assert (derniere["valeur"], premiere["valeur"]) == ("110", "100")


# ----------------------------------------------------------------------------------------------- suffisance
def test_mesure_ponctuelle_est_retenue_sans_revue_meme_sans_seuil_declare():
    m = cb.mesurer_ok([], valeur="1200", borne_basse="1200", borne_haute="1200")
    evaluation, verdict = _evaluer(m, parametres_mesure={})
    assert verdict is None
    assert evaluation["statut"] == "retenu" and evaluation["motifs_revue"] == []
    assert evaluation["quantite"] == evaluation["quantite_basse"] == evaluation["quantite_haute"] == "1200"
    assert evaluation["largeur_relative"] == "0.0000"


def test_le_seuil_de_revue_est_strict_au_dessus_de_la_largeur_relative_declaree():
    # largeur 0,15 exactement : (1275 - 1125) / 1000 = 0,15 -> pas de revue
    pile = cb.mesurer_ok([], valeur="1000", borne_basse="925", borne_haute="1075")
    evaluation, verdict = _evaluer(pile)
    assert verdict is None and evaluation["statut"] == "retenu" and evaluation["largeur_relative"] == "0.1500"
    juste_au_dessus = cb.mesurer_ok([], valeur="1000", borne_basse="925", borne_haute="1075.001")
    evaluation, verdict = _evaluer(juste_au_dessus)
    assert verdict is None and evaluation["statut"] == "a_revoir"
    assert "bornes larges" in evaluation["motifs_revue"][0] and "0.15" in evaluation["motifs_revue"][0]


def test_au_dela_du_seuil_aucun_prix_la_mesure_est_insuffisante_et_dit_quoi_faire():
    pile = cb.mesurer_ok([], valeur="1000", borne_basse="750", borne_haute="1250")  # largeur 0,50 exactement
    evaluation, verdict = _evaluer(pile)
    assert verdict is None and evaluation["statut"] == "a_revoir"
    trop_large = cb.mesurer_ok([], valeur="1000", borne_basse="750", borne_haute="1250.001")
    _, verdict = _evaluer(trop_large)
    assert cb.code(verdict) == "REJ-MESURE-INSUFFISANTE"
    assert "Aucun prix" in verdict["detail"] and "mesurer plus précisément" in verdict["detail"]
    assert "1250.001" in verdict["detail"] and "0.50" in verdict["detail"]


def test_bornes_larges_sans_seuil_declare_ne_sont_pas_devinees():
    m = cb.mesurer_ok([], valeur="1000", borne_basse="900", borne_haute="1100")
    _, verdict = _evaluer(m, parametres_mesure={})
    assert cb.code(verdict) == "REJ-BAREME-INCOMPLET" and "largeur_relative_max_prix" in verdict["detail"]
    evaluation, verdict = _evaluer(m, parametres_mesure={"largeur_relative_max_prix": "0.50"})
    assert verdict is None and evaluation["statut"] == "a_revoir"
    assert "largeur_relative_revue" in evaluation["motifs_revue"][0]  # seuil de revue absent : revue par prudence


def test_une_confiance_faible_exige_la_revue_meme_avec_des_bornes_etroites():
    m = cb.mesurer_ok([], confiance="faible")
    evaluation, verdict = _evaluer(m)
    assert verdict is None and evaluation["statut"] == "a_revoir"
    assert evaluation["motifs_revue"] == ["confiance déclarée faible"]
    moyenne = cb.mesurer_ok([], confiance="moyenne")
    assert _evaluer(moyenne)[0]["statut"] == "retenu"


def test_les_deux_motifs_se_cumulent():
    m = cb.mesurer_ok([], valeur="1000", borne_basse="850", borne_haute="1150", confiance="faible")
    evaluation, _ = _evaluer(m)
    assert len(evaluation["motifs_revue"]) == 2


def test_unite_differente_du_bareme_est_refusee_sans_conversion_devinee():
    m = cb.mesurer_ok([], unite="m2")
    _, verdict = _evaluer(m)
    assert cb.code(verdict) == "REJ-MESURE-UNITE"
    assert "'m2'" in verdict["detail"] and "'pi2'" in verdict["detail"] and "aucune conversion" in verdict["detail"]


def test_mesure_perimee_apres_la_validite_declaree_a_la_seconde_pres():
    m = cb.mesurer_ok([], mesure_le="2026-10-03T12:00:00+00:00", horodatage="2026-10-03T12:00:00+00:00")
    limite = mesure_declaree._instant(m["mesure_le"], "x") + timedelta(days=30)
    evaluation, verdict = _evaluer(m, maintenant=limite)
    assert verdict is None
    _, verdict = _evaluer(m, maintenant=limite + timedelta(seconds=1))
    assert cb.code(verdict) == "REJ-MESURE-PERIMEE" and "30 jours" in verdict["detail"]
    # le rejeu ne contrôle pas la péremption : la mesure d'alors reste celle d'alors
    evaluation, verdict = _evaluer(m, maintenant=limite + timedelta(days=400), controler_peremption=False)
    assert verdict is None and evaluation["statut"] == "retenu"
    # sans validité déclarée : jamais périmée
    assert _evaluer(m, parametres_mesure={}, maintenant=limite + timedelta(days=400))[1] is None


def test_l_evaluation_ne_modifie_pas_la_mesure_et_rend_des_textes_decimaux():
    m = cb.mesurer_ok([], valeur="1200.5", borne_basse="1190", borne_haute="1215.25")
    avant = deepcopy(m)
    evaluation, _ = _evaluer(m)
    assert m == avant
    assert all(isinstance(evaluation[c], str) for c in ("quantite", "quantite_basse", "quantite_haute"))
    assert evaluation["methode_libelle"] == "relevé sur place"


# ---------------------------------------------------------------------------------------------------- chaîne
def test_alterer_une_mesure_est_detecte_et_bloque_la_lecture():
    journal = []
    cb.mesurer_ok(journal)
    cb.mesurer_ok(journal, revision_attendue=1, valeur="1300", borne_basse="1300", borne_haute="1300")
    journal[0]["valeur"] = "1"
    _, verdict = mesure_declaree.lire(journal, "mesure-fictive-1")
    assert cb.code(verdict) == "REJ-MESURE-ALTEREE"
    _, verdict = cb.mesurer(journal, revision_attendue=2)
    assert cb.code(verdict) == "REJ-MESURE-ALTEREE"


def test_alteration_valide_ou_reecriture_partielle_d_une_mesure_est_detectee():
    journal = []
    cb.mesurer_ok(journal)
    cb.mesurer_ok(journal, revision_attendue=1, valeur="1300", borne_basse="1300", borne_haute="1300")
    journal[0]["pieces"] = ["autre-photo"]  # contenu encore valide : seule l'empreinte parle
    assert cb.code(mesure_declaree.lire(journal, "mesure-fictive-1")[1]) == "REJ-MESURE-ALTEREE"
    journal[0]["source_id"] = _encoder_canonique({k: v for k, v in journal[0].items() if k != "source_id"})
    verdict = mesure_declaree.lire(journal, "mesure-fictive-1")[1]  # le maillon 1 cite l'ancienne empreinte
    assert cb.code(verdict) == "REJ-MESURE-ALTEREE" and "maillon 1" in verdict["detail"]


def test_recalculer_les_empreintes_ne_masque_pas_un_invariant_viole():
    journal = []
    cb.mesurer_ok(journal)
    journal[0]["auteur"] = {"personne": "agent", "role": "system_agent"}
    _rechainer(journal)
    assert cb.code(mesure_declaree.lire(journal, "mesure-fictive-1")[1]) == "REJ-MESURE-ALTEREE"
    journal = []
    cb.mesurer_ok(journal)
    journal[0]["borne_haute"] = "1"  # bornes qui n'encadrent plus la valeur
    _rechainer(journal)
    assert cb.code(mesure_declaree.lire(journal, "mesure-fictive-1")[1]) == "REJ-MESURE-ALTEREE"
    journal = []
    cb.mesurer_ok(journal)
    journal[0]["revision"] = 3
    _rechainer(journal)
    assert cb.code(mesure_declaree.lire(journal, "mesure-fictive-1")[1]) == "REJ-MESURE-ALTEREE"


def test_les_codes_de_refus_de_la_mesure_sont_au_catalogue_ferme():
    for code_ in ("REJ-MESURE-REQUISE", "REJ-MESURE-INTROUVABLE", "REJ-MESURE-AUTRE-LEAD", "REJ-MESURE-UNITE",
                  "REJ-MESURE-INVALIDE", "REJ-MESURE-INSUFFISANTE", "REJ-MESURE-PERIMEE", "REJ-MESURE-IDENTITE",
                  "REJ-MESURE-REVISION-PERIMEE", "REJ-MESURE-ALTEREE", "REJ-REJEU-IMPOSSIBLE"):
        assert verdicts.est_verdict(code_), code_
