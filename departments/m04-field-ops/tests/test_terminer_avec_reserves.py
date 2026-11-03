"""P4-07 : « terminer avec réserves ». Une fin de chantier dont la preuve est incomplète passe en attente de revue
avec ses
réserves nommées au lieu d'être refusée ; rien n'est publié aux départements avant la revue humaine.

Deux étages, tout fictif (`fictif: true`) : la mécanique PURE (`outbox`, `preuves`, `reserves_completion`, registre en
mémoire)
et les VRAIS outils (`executer_atomique`, base SQLite migrée, vraies approbations N4 du socle, vrai bus). La cascade
complète
vers M5, M6, M2, M7, M8, M10 est prouvée dans `tests/test_m4_duree_multijours_bout_en_bout.py`.
"""

from __future__ import annotations

import ast
import copy
import importlib.util
from pathlib import Path

import pytest
from m4_field_ops import encodage, etats, outbox, preuves, reserves_completion
from m4_field_ops import registre as registre_m4
from m4_field_ops.outils import attentes, consommateurs, outils
from m4_field_ops.reserves_completion import (
    LISTE_CONTROLE_INCOMPLETE,
    MATERIEL_ECARTE_NON_DOCUMENTE,
    PHOTO_EN_ECHEC,
    PHOTOS_APRES_MANQUANTES,
    SIGNATURE_IMPOSSIBLE,
)
from sqlalchemy import select

from opsys import approbations, identite, stockage
from opsys.departements import lire_manifeste
from opsys.outils import Niveau, executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_SORTANTS

FICTIF = True
_RACINE = Path(__file__).resolve().parents[1]


def _charger(nom, fichier):
    spec = importlib.util.spec_from_file_location(nom, Path(__file__).with_name(fichier))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fichiers = _charger("reserves_fichiers_fixture", "test_outils_fichiers.py")
b = _charger("reserves_outbox_fixture", "test_outbox.py")


def _preuves(**remplacements):
    base = {"checklist_complete": True, "photos_apres": ["photo-declaree-fictive"], "notes": "Note fictive.",
            "signature": None}
    base.update(remplacements)
    return base


def _completer(reg, ident, preuves_completion, signature_requise=False, reserves=outbox.NON_FOURNI):
    return outbox.completer_intervention(
        ident, b.H_COMPLETION, reg, ecart_detecte=False, preuves_completion=preuves_completion,
        signature_requise=signature_requise, reserves=reserves)


def _monde():
    return b._intervention_sur_site_avec_pointages()


# =========================================================================================
# 1. Chaque réserve couvre son manque, et seulement lui
# =========================================================================================
CAS_VALIDES = {
    LISTE_CONTROLE_INCOMPLETE: (_preuves(checklist_complete=False), False),
    PHOTOS_APRES_MANQUANTES: (_preuves(photos_apres=[]), False),
    PHOTO_EN_ECHEC: (_preuves(photos_apres=[]), False),
    SIGNATURE_IMPOSSIBLE: (_preuves(signature=None), True),
    MATERIEL_ECARTE_NON_DOCUMENTE: (_preuves(), False),
}


@pytest.mark.parametrize("code", sorted(CAS_VALIDES))
def test_chaque_reserve_permet_de_terminer_et_met_la_fin_de_chantier_en_attente_de_revue(code):
    reg, ident = _monde()
    dossier, signature_requise = CAS_VALIDES[code]
    accuse, verdict = _completer(reg, ident, dossier, signature_requise, [code])
    assert verdict is None, verdict
    assert accuse["statut"] == "completed_pending_review" and accuse["reserves"] == [code]
    assert accuse["reserves_par_categorie"] == {reserves_completion.categorie(code): [code]}
    maillon = reg.lire()[-1]
    assert maillon["reserves_completion"] == {"version_schema": 1, "reserves": [code]}
    assert maillon["wct"]["statut"] == "completed_pending_review"
    assert set(outbox.CHAMPS_WCT) <= set(maillon["wct"]) <= set(outbox.CHAMPS_WCT) | set(outbox.CHAMPS_WCT_OPTIONNELS)
    assert not any("reserve" in cle for cle in maillon["wct"]), "le WCT ne porte aucune réserve : ses clés sont figées"
    assert outbox.verifier_invariants_outbox(reg) == (True, "")
    assert etats.statut_courant(reg, ident) == "completed_pending_review"
    assert outbox.reserves_de_la_completion(reg, ident) == (code,)


def test_plusieurs_reserves_ensemble_sont_rangees_triees_par_categorie():
    reg, ident = _monde()
    accuse, verdict = _completer(
        reg, ident, _preuves(checklist_complete=False, photos_apres=[], signature=None), True,
        [SIGNATURE_IMPOSSIBLE, PHOTOS_APRES_MANQUANTES, LISTE_CONTROLE_INCOMPLETE, MATERIEL_ECARTE_NON_DOCUMENTE])
    assert verdict is None
    assert accuse["reserves"] == sorted(accuse["reserves"])
    assert list(accuse["reserves_par_categorie"]) == ["liste_controle", "preuve_photo", "signature", "materiel"]


def test_les_reserves_entrent_dans_l_empreinte_du_maillon():
    reg, ident = _monde()
    _completer(reg, ident, _preuves(checklist_complete=False), False, [LISTE_CONTROLE_INCOMPLETE])
    maillon = copy.deepcopy(reg.lire()[-1])
    partie = {k: v for k, v in maillon.items() if k not in ("wct", "ligne_id", "precedent_ligne_id")}
    assert maillon["wct"]["hash_maillon"] == encodage.empreinte(partie)
    assert "reserves_completion" in partie


# =========================================================================================
# 2. Une preuve incomplète SANS réserve est refusée comme avant ; une réserve n'est pas un passe-droit
# =========================================================================================
@pytest.mark.parametrize("dossier, signature_requise, code, morceau", [
    (_preuves(checklist_complete=False), False, "REJ-CHAMP-VIDE", "checklist non terminée"),
    (_preuves(photos_apres=[]), False, "REJ-CHAMP-VIDE", "photos_apres vide"),
    (_preuves(), True, "REJ-CHAMP-MANQUANT", "signature requise mais absente"),
])
def test_sans_reserve_la_preuve_incomplete_est_refusee_comme_avant(dossier, signature_requise, code, morceau):
    ok, verdict = preuves.valider_preuves_completion(dossier, signature_requise)
    assert ok is False and verdict["code"] == code and morceau in verdict["detail"]
    reg, ident = _monde()
    avant = reg.lire()
    accuse, verdict = _completer(reg, ident, dossier, signature_requise)
    assert accuse is None and verdict["code"] == "REJ-CONTRAT-INVALIDE"      # l'outbox ne garde pas le détail
    assert reg.lire() == avant


@pytest.mark.parametrize("dossier, signature_requise, code_reserve", [
    (_preuves(), False, LISTE_CONTROLE_INCOMPLETE),                      # la liste est complète
    (_preuves(), False, PHOTOS_APRES_MANQUANTES),                        # il y a une photo
    (_preuves(signature="signature-fictive"), True, SIGNATURE_IMPOSSIBLE),   # la signature est là
    (_preuves(), False, SIGNATURE_IMPOSSIBLE),                           # aucune signature n'était requise
])
def test_une_reserve_sans_manque_reel_est_refusee(dossier, signature_requise, code_reserve):
    ok, verdict = preuves.valider_preuves_completion(dossier, signature_requise, (code_reserve,))
    assert ok is False and verdict["code"] == "REJ-CONTRAT-INVALIDE" and "passe-droit" in verdict["detail"]
    reg, ident = _monde()
    avant = reg.lire()
    accuse, verdict = _completer(reg, ident, dossier, signature_requise, [code_reserve])
    assert accuse is None and verdict["code"] == "REJ-CONTRAT-INVALIDE"
    assert reg.lire() == avant


@pytest.mark.parametrize("dossier, signature_requise, mauvaise_reserve", [
    (_preuves(checklist_complete=False), False, PHOTOS_APRES_MANQUANTES),   # mauvaise dimension : photo pour la liste
    (_preuves(checklist_complete=False), False, SIGNATURE_IMPOSSIBLE),
    (_preuves(photos_apres=[]), False, LISTE_CONTROLE_INCOMPLETE),          # liste pour des photos manquantes
    (_preuves(photos_apres=[]), False, MATERIEL_ECARTE_NON_DOCUMENTE),      # matériel pour des photos manquantes
    (_preuves(), True, PHOTO_EN_ECHEC),                                     # photo pour la signature
])
def test_une_reserve_de_la_mauvaise_dimension_ne_couvre_pas_le_manque(dossier, signature_requise, mauvaise_reserve):
    reg, ident = _monde()
    avant = reg.lire()
    accuse, verdict = _completer(reg, ident, dossier, signature_requise, [mauvaise_reserve])
    assert accuse is None and verdict is not None
    assert reg.lire() == avant


def test_un_manque_non_nomme_reste_refuse_meme_quand_un_autre_est_nomme():
    reg, ident = _monde()
    dossier = _preuves(checklist_complete=False, photos_apres=[])
    ok, verdict = preuves.valider_preuves_completion(dossier, False, (LISTE_CONTROLE_INCOMPLETE,))
    assert ok is False and verdict["code"] == "REJ-CHAMP-VIDE" and "photos_apres vide" in verdict["detail"]
    accuse, verdict = _completer(reg, ident, dossier, False, [LISTE_CONTROLE_INCOMPLETE])
    assert accuse is None


@pytest.mark.parametrize("notes", ["", "   ", "\n\t"])
def test_toute_reserve_exige_une_explication(notes):
    dossier = _preuves(checklist_complete=False, notes=notes)
    ok, verdict = preuves.valider_preuves_completion(dossier, False, (LISTE_CONTROLE_INCOMPLETE,))
    assert ok is False and verdict["code"] == "REJ-CHAMP-VIDE" and "notes requises" in verdict["detail"]
    reg, ident = _monde()
    accuse, verdict = _completer(reg, ident, dossier, False, [LISTE_CONTROLE_INCOMPLETE])
    assert accuse is None


@pytest.mark.parametrize("reserves", [
    "liste_controle_incomplete", [1], ["inconnue"], [None], ["Liste_controle_incomplete"],
    [LISTE_CONTROLE_INCOMPLETE, LISTE_CONTROLE_INCOMPLETE], {"a": 1}])
def test_des_reserves_mal_formees_ou_inconnues_sont_refusees(reserves):
    reg, ident = _monde()
    avant = reg.lire()
    accuse, verdict = _completer(reg, ident, _preuves(checklist_complete=False), False, reserves)
    assert accuse is None and verdict["code"] in ("REJ-CONTRAT-INVALIDE", "REJ-ENUM-INVALIDE")
    assert reg.lire() == avant


def test_des_reserves_sans_dossier_de_preuves_sont_refusees():
    reg, ident = _monde()
    accuse, verdict = outbox.completer_intervention(
        ident, b.H_COMPLETION, reg, ecart_detecte=False, reserves=[LISTE_CONTROLE_INCOMPLETE])
    assert accuse is None and "dossier de preuves" in verdict["detail"]


def test_une_liste_de_reserves_vide_ne_change_rien():
    reg, ident = _monde()
    accuse, verdict = _completer(reg, ident, _preuves(), False, [])
    assert verdict is None and "reserves" not in accuse
    assert "reserves_completion" not in reg.lire()[-1]


def test_une_signature_qui_n_est_ni_chaine_ni_null_n_est_jamais_couverte_par_la_reserve():
    reg, ident = _monde()
    accuse, verdict = _completer(reg, ident, _preuves(signature=5), True, [SIGNATURE_IMPOSSIBLE])
    assert accuse is None and verdict["code"] == "REJ-CONTRAT-INVALIDE"


def test_la_categorie_de_chaque_reserve_est_epinglee():
    assert {code: reserves_completion.categorie(code) for code in reserves_completion.CODES} == {
        LISTE_CONTROLE_INCOMPLETE: "liste_controle", PHOTOS_APRES_MANQUANTES: "preuve_photo",
        PHOTO_EN_ECHEC: "preuve_photo", SIGNATURE_IMPOSSIBLE: "signature",
        MATERIEL_ECARTE_NON_DOCUMENTE: "materiel"}
    assert reserves_completion.par_categorie([MATERIEL_ECARTE_NON_DOCUMENTE, PHOTO_EN_ECHEC]) == {
        "preuve_photo": [PHOTO_EN_ECHEC], "materiel": [MATERIEL_ECARTE_NON_DOCUMENTE]}
    assert reserves_completion.cout_provisoire([MATERIEL_ECARTE_NON_DOCUMENTE]) is True
    for code in (LISTE_CONTROLE_INCOMPLETE, PHOTOS_APRES_MANQUANTES, PHOTO_EN_ECHEC, SIGNATURE_IMPOSSIBLE):
        assert reserves_completion.cout_provisoire([code]) is False


# =========================================================================================
# 3. Une fin de chantier avec réserves ne se vérifie jamais d'elle-même
# =========================================================================================
def _avec_reserves(code=LISTE_CONTROLE_INCOMPLETE):
    reg, ident = _monde()
    dossier, signature_requise = CAS_VALIDES[code]
    accuse, verdict = _completer(reg, ident, dossier, signature_requise, [code])
    assert verdict is None
    return reg, ident


def test_la_confirmation_automatique_est_refusee_pour_une_fin_de_chantier_avec_reserves():
    reg, ident = _avec_reserves()
    avant = reg.lire()
    accuse, verdict = outbox.confirmer_verification(
        ident, "2025-06-02T12:00:00+00:00", reg, evenement_id_variance="v-1")
    assert accuse is None and verdict["code"] == "REJ-RESERVES-REVUE-HUMAINE-REQUISE"
    assert reg.lire() == avant and etats.statut_courant(reg, ident) == "completed_pending_review"


def test_sans_reserve_la_confirmation_automatique_marche_toujours():
    reg, ident = _monde()
    _completer(reg, ident, _preuves(), False)
    accuse, verdict = outbox.confirmer_verification(
        ident, "2025-06-02T12:00:00+00:00", reg, evenement_id_variance="v-1")
    assert verdict is None and accuse["statut"] == "completed_verified"


def test_la_revue_verifiee_exige_de_nommer_exactement_les_reserves():
    reg, ident = _avec_reserves(PHOTOS_APRES_MANQUANTES)
    avant = reg.lire()
    for fournies in (outbox.NON_FOURNI, [], [LISTE_CONTROLE_INCOMPLETE],
                     [PHOTOS_APRES_MANQUANTES, SIGNATURE_IMPOSSIBLE], "photos_apres_manquantes", ["inconnue"]):
        accuse, verdict = outbox.resoudre_revue_completion(
            ident, "verifiee", "2025-06-02T12:00:00+00:00", reg, motif="Vu.", reserves_acceptees=fournies)
        assert accuse is None and verdict["code"] == "REJ-RESERVES-NON-ACCEPTEES", fournies
        assert reg.lire() == avant
    accuse, verdict = outbox.resoudre_revue_completion(
        ident, "verifiee", "2025-06-02T12:00:00+00:00", reg, motif="Photos reprises par le chef d'équipe.",
        reserves_acceptees=[PHOTOS_APRES_MANQUANTES])
    assert verdict is None and accuse["statut"] == "completed_verified"
    assert accuse["reserves"] == accuse["reserves_acceptees"] == [PHOTOS_APRES_MANQUANTES]
    assert accuse["cout_reel_provisoire"] is False
    assert reg.lire()[-1]["reserves_acceptees"] == [PHOTOS_APRES_MANQUANTES]
    assert outbox.verifier_invariants_outbox(reg) == (True, "")


def test_accepter_des_reserves_de_materiel_dit_que_le_cout_reel_est_provisoire():
    reg, ident = _avec_reserves(MATERIEL_ECARTE_NON_DOCUMENTE)
    accuse, verdict = outbox.resoudre_revue_completion(
        ident, "verifiee", "2025-06-02T12:00:00+00:00", reg, motif="Matériel écarté constaté.",
        reserves_acceptees=[MATERIEL_ECARTE_NON_DOCUMENTE])
    assert verdict is None and accuse["cout_reel_provisoire"] is True


def test_une_correction_nomme_le_probleme_sans_accepter_les_reserves_ni_rouvrir():
    reg, ident = _avec_reserves()
    accuse, verdict = outbox.resoudre_revue_completion(
        ident, "correction", "2025-06-02T12:00:00+00:00", reg, motif="Refaire la liste de contrôle.")
    assert verdict is None and accuse["statut"] == "completed_pending_review"
    assert "reserves_acceptees" not in reg.lire()[-1]
    assert outbox.reserves_de_la_completion(reg, ident) == (LISTE_CONTROLE_INCOMPLETE,)
    accuse, verdict = outbox.confirmer_verification(
        ident, "2025-06-02T12:30:00+00:00", reg, evenement_id_variance="v-1")
    assert verdict["code"] == "REJ-RESERVES-REVUE-HUMAINE-REQUISE"


def test_accepter_des_reserves_qui_n_existent_pas_est_refuse():
    reg, ident = _monde()
    outbox.completer_intervention(ident, b.H_COMPLETION, reg, ecart_detecte=False, verification_en_attente=True,
                                  preuves_completion=_preuves(), signature_requise=False)
    accuse, verdict = outbox.resoudre_revue_completion(
        ident, "verifiee", "2025-06-02T12:00:00+00:00", reg, motif="Vu.", reserves_acceptees=[PHOTO_EN_ECHEC])
    assert accuse is None and verdict["code"] == "REJ-CONTRAT-INVALIDE" and "aucune réserve" in verdict["detail"]
    accuse, verdict = outbox.resoudre_revue_completion(
        ident, "verifiee", "2025-06-02T12:00:00+00:00", reg, motif="Vu.", reserves_acceptees=[])
    assert verdict is None and "reserves_acceptees" not in reg.lire()[-1]


# =========================================================================================
# 4. Les invariants du registre refusent un maillon forgé
# =========================================================================================
def test_un_bloc_de_reserves_absent_est_valide_et_vide():
    assert reserves_completion.codes_du_bloc(None) == ((), True)


@pytest.mark.parametrize("bloc", [
    {"version_schema": 1, "reserves": [LISTE_CONTROLE_INCOMPLETE], "en_trop": 1},
    {"version_schema": 2, "reserves": [LISTE_CONTROLE_INCOMPLETE]},
    {"version_schema": True, "reserves": [LISTE_CONTROLE_INCOMPLETE]},
    ["version_schema", "reserves"],
    {"version_schema": 1, "reserves": (LISTE_CONTROLE_INCOMPLETE,)},
    {"version_schema": 1, "reserves": [SIGNATURE_IMPOSSIBLE, MATERIEL_ECARTE_NON_DOCUMENTE]},
])
def test_un_bloc_de_reserves_mal_forme_est_refuse_sans_etre_presume_valide(bloc):
    assert reserves_completion.codes_du_bloc(bloc) == ((), False)


def _forger(reg, modification):
    maillons = copy.deepcopy(reg.lire())
    modification(maillons)
    return registre_m4.Registre(maillons)


def test_les_invariants_refusent_un_bloc_de_reserves_invalide_meme_rehache():
    reg, _ = _avec_reserves()

    def retirer_la_reserve(maillons):
        del maillons[-1]["reserves_completion"]
    assert outbox.verifier_invariants_outbox(_forger(reg, retirer_la_reserve))[0] is False   # preuve incomplète + hash

    for bloc in ({"version_schema": 2, "reserves": [LISTE_CONTROLE_INCOMPLETE]}, {"version_schema": 1, "reserves": []},
                 {"version_schema": 1, "reserves": ["inconnue"]}, {"version_schema": 1, "reserves": [], "x": 1},
                 {"version_schema": True, "reserves": [LISTE_CONTROLE_INCOMPLETE]}, "texte", None):
        def forger(maillons, bloc=bloc):
            maillons[-1]["reserves_completion"] = bloc
        assert outbox.verifier_invariants_outbox(_forger(reg, forger))[0] is False, bloc


def test_les_invariants_refusent_une_verification_automatique_d_une_fin_de_chantier_avec_reserves():
    reg, ident = _avec_reserves()
    maillons = copy.deepcopy(reg.lire())
    maillons.append({
        "type_entree": etats.TYPE_TRANSITION, "intervention_id": ident, "statut": "completed_verified",
        "statut_precedent": "completed_pending_review", "horodatage": "2025-06-02T12:00:00+00:00",
        "evenement_id_variance": "v-forge", "source_horodatage": "repartiteur"})
    ok, message = outbox.verifier_invariants_outbox(registre_m4.Registre(maillons))
    assert ok is False and "sans revue humaine" in message


def test_les_invariants_refusent_une_revue_qui_n_accepte_pas_nommement_les_reserves():
    reg, ident = _avec_reserves()
    outbox.resoudre_revue_completion(ident, "verifiee", "2025-06-02T12:00:00+00:00", reg, motif="Vu.",
                                     reserves_acceptees=[LISTE_CONTROLE_INCOMPLETE])

    def vider(maillons):
        del maillons[-1]["reserves_acceptees"]
    assert outbox.verifier_invariants_outbox(_forger(reg, vider)) [0] is False

    def autre(maillons):
        maillons[-1]["reserves_acceptees"] = [PHOTO_EN_ECHEC]
    assert outbox.verifier_invariants_outbox(_forger(reg, autre))[0] is False


def test_les_invariants_refusent_des_reserves_hors_d_une_premiere_completion_en_revue():
    reg, ident = _monde()
    _completer(reg, ident, _preuves(), False)

    def greffer(maillons):
        maillons[-1]["reserves_completion"] = {"version_schema": 1, "reserves": [MATERIEL_ECARTE_NON_DOCUMENTE]}
    assert outbox.verifier_invariants_outbox(_forger(reg, greffer))[0] is False


def test_les_invariants_refusent_des_reserves_acceptees_pour_une_fin_de_chantier_sans_reserve():
    reg, ident = _monde()
    outbox.completer_intervention(ident, b.H_COMPLETION, reg, ecart_detecte=False, verification_en_attente=True,
                                  preuves_completion=_preuves(), signature_requise=False)
    outbox.resoudre_revue_completion(ident, "verifiee", "2025-06-02T12:00:00+00:00", reg, motif="Vu.")
    assert outbox.verifier_invariants_outbox(reg) == (True, "")

    def greffer(maillons):
        maillons[-1]["reserves_acceptees"] = [PHOTO_EN_ECHEC]
    assert outbox.verifier_invariants_outbox(_forger(reg, greffer))[0] is False


def test_archive_valide_n_accepte_une_preuve_incomplete_qu_avec_sa_reserve():
    archive, verdict = preuves.preparer_archive(_preuves(checklist_complete=False), False, (LISTE_CONTROLE_INCOMPLETE,))
    assert verdict is None
    assert preuves.archive_valide(archive, (LISTE_CONTROLE_INCOMPLETE,)) is True
    assert preuves.archive_valide(archive) is False
    assert preuves.archive_valide(archive, (PHOTO_EN_ECHEC,)) is False


# =========================================================================================
# 5. Les VRAIS outils : rien n'est publié avant la revue, puis la cascade part (même WCT, même identifiant)
# =========================================================================================
def _dep():
    return lire_manifeste(_RACINE)


def _evenements_wct():
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS.c.evenement_id, EVENEMENTS_SORTANTS.c.charge).where(
            EVENEMENTS_SORTANTS.c.type_evenement == "m4.travaux_termines")).all()
    return [(ligne.evenement_id, codec.decoder(ligne.charge)) for ligne in lignes]


def _completer_outil(par_nom, ident, dossier, signature_requise=False, reserves=None):
    arguments = {"intervention_id": ident, "horodatage": "2025-06-02T11:35:00+00:00", "preuves_completion": dossier,
                 "signature_requise": signature_requise}
    if reserves is not None:
        arguments["reserves"] = reserves
    return executer_atomique(par_nom["m4_completer_intervention"], arguments)


def test_le_vrai_outil_enregistre_la_fin_en_attente_de_revue_et_ne_publie_rien(base_durable, deposer_photo_test):
    par_nom = {o.nom: o for o in outils()}
    ident = fichiers._mener_a_sur_site(par_nom, "L-RESERVES-OUTIL")
    reponse = _completer_outil(par_nom, ident, _preuves(checklist_complete=False, photos_apres=[]), False,
                               [LISTE_CONTROLE_INCOMPLETE, PHOTOS_APRES_MANQUANTES])
    assert reponse["ok"] and reponse["resultat"]["accepte"] is True, reponse
    accuse = reponse["resultat"]["resultat"]
    assert accuse["statut"] == "completed_pending_review"
    assert accuse["reserves"] == [LISTE_CONTROLE_INCOMPLETE, PHOTOS_APRES_MANQUANTES]
    assert accuse["cascade"]["etat"] == "differee_jusqu_a_la_revue" and accuse["cascade"]["evenement_publie"] is False
    assert accuse["cascade"]["departements_non_notifies"] == list(outbox.CONSOMMATEURS_CIBLES)
    assert _evenements_wct() == []                                     # RIEN n'est parti
    statut = executer_atomique(par_nom["m4_statut_intervention"], {"intervention_id": ident})
    assert statut["resultat"]["statut"] == "completed_pending_review"
    with stockage.transaction():
        reg = registre_m4.Registre(stockage.maillons("m04-field-ops", "principal"))
        assert outbox.verifier_invariants_outbox(reg) == (True, "")
        assert outbox.reserves_de_la_completion(reg, ident) == (LISTE_CONTROLE_INCOMPLETE, PHOTOS_APRES_MANQUANTES)


def test_le_vrai_outil_garde_son_comportement_sans_reserve_et_publie(base_durable, deposer_photo_test):
    par_nom = {o.nom: o for o in outils()}
    ident = fichiers._mener_a_sur_site(par_nom, "L-SANS-RESERVE")
    reponse = _completer_outil(par_nom, ident, _preuves(photos_apres=[deposer_photo_test(par_nom)]))
    assert reponse["resultat"]["accepte"] is True and "cascade" not in reponse["resultat"]["resultat"]
    assert len(_evenements_wct()) == 1


def test_une_preuve_incomplete_sans_reserve_est_refusee_par_le_vrai_outil_comme_avant(base_durable):
    par_nom = {o.nom: o for o in outils()}
    ident = fichiers._mener_a_sur_site(par_nom, "L-SANS-RESERVE-REFUS")
    reponse = _completer_outil(par_nom, ident, _preuves(checklist_complete=False, photos_apres=[]))
    assert reponse["resultat"]["accepte"] is False and reponse["resultat"]["verdict"]["code"] == "REJ-CHAMP-VIDE"
    assert _evenements_wct() == []


def test_une_reference_de_photo_inventee_reste_refusee_meme_avec_une_reserve(base_durable):
    """Le refus d'une preuve FAUSSE est maintenu : photo_en_echec nomme un échec, pas une référence qui ne mène nulle
    part."""
    par_nom = {o.nom: o for o in outils()}
    ident = fichiers._mener_a_sur_site(par_nom, "L-RESERVE-FAUSSE-REFERENCE")
    avant = executer_atomique(par_nom["m4_statut_intervention"], {"intervention_id": ident})
    for reference in ("une-chaine-inventee.jpg", f"fichier:sha256:{'cd' * 32}"):
        reponse = _completer_outil(par_nom, ident, _preuves(photos_apres=[reference]), False, [PHOTO_EN_ECHEC])
        assert reponse["resultat"]["accepte"] is False
        assert reponse["resultat"]["verdict"]["code"] == "REJ-PREUVE-FICHIER-INTROUVABLE"
    assert executer_atomique(par_nom["m4_statut_intervention"], {"intervention_id": ident}) == avant
    assert _evenements_wct() == []


def test_une_signature_inventee_reste_refusee_meme_avec_une_autre_reserve(base_durable, deposer_photo_test):
    par_nom = {o.nom: o for o in outils()}
    ident = fichiers._mener_a_sur_site(par_nom, "L-RESERVE-FAUSSE-SIGNATURE")
    reponse = _completer_outil(
        par_nom, ident, _preuves(checklist_complete=False, photos_apres=[deposer_photo_test(par_nom)],
                                 signature="signature-inventee"), True, [LISTE_CONTROLE_INCOMPLETE])
    assert reponse["resultat"]["accepte"] is False
    assert reponse["resultat"]["verdict"]["code"] == "REJ-PREUVE-FICHIER-INTROUVABLE"


def test_la_file_du_proprietaire_montre_les_reserves_et_le_geste(base_durable):
    par_nom = {o.nom: o for o in outils()}
    ident = fichiers._mener_a_sur_site(par_nom, "L-RESERVES-FILE")
    _completer_outil(par_nom, ident, _preuves(photos_apres=[]), False, [PHOTO_EN_ECHEC, MATERIEL_ECARTE_NON_DOCUMENTE])
    with stockage.transaction() as cnx:
        file = approbations.file_proprietaire(cnx, {"m04-field-ops": _dep()})
    [item] = [i for i in file if i["id"] == ident]
    assert item["niveau"] == "N4" and item["type"] == "completion_en_revue"
    assert "AVEC RÉSERVES" in item["resume"] and "preuve_photo" in item["resume"] and "materiel" in item["resume"]
    assert "rien n'est parti" in item["resume"] and "coût réel provisoire" in item["resume"]
    assert "reserves_acceptees" in item["action_proposee"] and "cascade" in item["action_proposee"]
    assert attentes()  # l'adaptateur nu fonctionne aussi


def test_la_revue_humaine_publie_le_wct_gardé_et_dit_que_le_cout_est_provisoire(base_durable):
    par_nom = {o.nom: o for o in outils()}
    dep = _dep()
    ident = fichiers._mener_a_sur_site(par_nom, "L-RESERVES-REVUE")
    _completer_outil(par_nom, ident, _preuves(photos_apres=[]), False, [PHOTO_EN_ECHEC, MATERIEL_ECARTE_NON_DOCUMENTE])
    assert _evenements_wct() == []
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "gerant", "Une Gérante", "mot-de-passe-gerante-1234", ["manager"])
        arguments = {"intervention_id": ident, "decision": "verifiee", "horodatage": "2025-06-02T12:00:00+00:00",
                     "motif": "Photos reprises, matériel constaté.",
                     "reserves_acceptees": [MATERIEL_ECARTE_NON_DOCUMENTE, PHOTO_EN_ECHEC]}
        demande = approbations.creer_demande(cnx, "m04-field-ops", "m4_resoudre_revue_completion", arguments,
                                             niveau=Niveau.N4)
        decision = approbations.decider(cnx, demande, True, "gerant", par_nom, {"m04-field-ops": dep},
                                        motif="Revue faite.")
    assert decision["statut"] == "executee", decision
    resultat = decision["reponse"]["resultat"]["resultat"]
    assert resultat["statut"] == "completed_verified"
    assert resultat["cascade"]["etat"] == "declenchee_apres_revue" and resultat["cascade"]["evenement_publie"] is True
    assert resultat["cascade"]["cout_reel"] == "provisoire" and "matériel" in resultat["cascade"]["note"]
    publies = _evenements_wct()
    assert [identifiant for identifiant, _ in publies] == [resultat["wct_id"]]
    assert publies[0][1]["intervention_id"] == ident and set(outbox.CHAMPS_WCT) <= set(publies[0][1])
    assert "reserves_completion" not in publies[0][1] and "reserves" not in publies[0][1]


def test_une_correction_laisse_la_cascade_en_attente_et_ne_publie_rien(base_durable):
    par_nom = {o.nom: o for o in outils()}
    dep = _dep()
    ident = fichiers._mener_a_sur_site(par_nom, "L-RESERVES-CORRECTION")
    _completer_outil(par_nom, ident, _preuves(photos_apres=[]), False, [PHOTOS_APRES_MANQUANTES])
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "gerant", "Une Gérante", "mot-de-passe-gerante-1234", ["manager"])
        demande = approbations.creer_demande(
            cnx, "m04-field-ops", "m4_resoudre_revue_completion",
            {"intervention_id": ident, "decision": "correction", "horodatage": "2025-06-02T12:00:00+00:00",
             "motif": "Reprendre les photos."}, niveau=Niveau.N4)
        decision = approbations.decider(cnx, demande, True, "gerant", par_nom, {"m04-field-ops": dep})
    resultat = decision["reponse"]["resultat"]["resultat"]
    assert resultat["statut"] == "completed_pending_review" and "cascade" not in resultat
    assert _evenements_wct() == []
    statut = executer_atomique(par_nom["m4_statut_intervention"], {"intervention_id": ident})
    assert statut["resultat"]["statut"] == "completed_pending_review"


def test_une_revue_qui_ne_nomme_pas_les_reserves_n_execute_rien_et_ne_publie_rien(base_durable):
    par_nom = {o.nom: o for o in outils()}
    dep = _dep()
    ident = fichiers._mener_a_sur_site(par_nom, "L-RESERVES-REVUE-REFUSEE")
    _completer_outil(par_nom, ident, _preuves(photos_apres=[]), False, [PHOTOS_APRES_MANQUANTES])
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "gerant", "Une Gérante", "mot-de-passe-gerante-1234", ["manager"])
        demande = approbations.creer_demande(
            cnx, "m04-field-ops", "m4_resoudre_revue_completion",
            {"intervention_id": ident, "decision": "verifiee", "horodatage": "2025-06-02T12:00:00+00:00",
             "motif": "Vu."}, niveau=Niveau.N4)
        decision = approbations.decider(cnx, demande, True, "gerant", par_nom, {"m04-field-ops": dep})
    assert decision["reponse"]["resultat"]["accepte"] is False
    assert decision["reponse"]["resultat"]["verdict"]["code"] == "REJ-RESERVES-NON-ACCEPTEES"
    assert _evenements_wct() == []
    statut = executer_atomique(par_nom["m4_statut_intervention"], {"intervention_id": ident})
    assert statut["resultat"]["statut"] == "completed_pending_review"


def test_un_signal_m6_sans_ecart_ne_verifie_pas_une_fin_de_chantier_avec_reserves(base_durable):
    par_nom = {o.nom: o for o in outils()}
    ident = fichiers._mener_a_sur_site(par_nom, "L-RESERVES-SIGNAL-M6")
    _completer_outil(par_nom, ident, _preuves(photos_apres=[]), False, [PHOTO_EN_ECHEC])
    with stockage.transaction():
        resultat = consommateurs()["m6.variance_chantier"]({
            "evenement_id": "m6-variance-fictive", "wct_id": "wct-fictif", "intervention_id": ident,
            "chantier_id": "C-TEST", "statut_variance": "evaluee", "signal_critique": False, "seuil_pourcentage": 0.3,
            "horodatage_completion": "2025-06-02T11:30:00+00:00"})
    assert resultat["verifie"] is False and resultat["raison"] == "reserves_en_attente_de_revue_humaine"
    statut = executer_atomique(par_nom["m4_statut_intervention"], {"intervention_id": ident})
    assert statut["resultat"]["statut"] == "completed_pending_review"
    with stockage.transaction():
        reg = registre_m4.Registre(stockage.maillons("m04-field-ops", "principal"))
        assert outbox.dernier_signal_variance(reg, ident)["statut_variance"] == "evaluee"   # tracé pour la file


def test_les_schemas_des_outils_declarent_les_codes_fermes():
    par_nom = {o.nom: o for o in outils()}
    for nom, cle in (("m4_completer_intervention", "reserves"), ("m4_resoudre_revue_completion", "reserves_acceptees")):
        propriete = par_nom[nom].parametres["properties"][cle]
        assert propriete["items"]["enum"] == list(reserves_completion.CODES) and propriete["uniqueItems"] is True
    assert par_nom["m4_resoudre_revue_completion"].niveau_effectif is Niveau.N4


def test_le_module_est_pur():
    source = (_RACINE / "src" / "m4_field_ops" / "reserves_completion.py").read_text(encoding="utf-8")
    for noeud in ast.walk(ast.parse(source)):
        assert not (isinstance(noeud, ast.Import) and any(a.name not in ("__future__",) for a in noeud.names))
        assert not (isinstance(noeud, ast.Constant) and isinstance(noeud.value, float))
