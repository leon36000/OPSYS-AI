"""Le garde-fou de M1 vient du socle, et l'avis légal y est vérifié PARTOUT (PLAN T4.17-c).

Avant : `garde_fou.verifier_sortie` ne portait que prix, date, engagement, aveu ; l'avis légal n'était vérifié que sur
le gabarit de plainte (T4.5). Maintenant : M1 choisit cinq familles du socle (`opsys.garde_fou_texte`) et chaque texte
qui traverse le garde-fou passe l'avis légal : brouillons de qualification, questions du profil, gabarits, résumés de
transfert et outil `m1_verifier_garde_fou`. Les corpus de M1 (`test_garde_fou.py`, inchangé) prouvent que les quatre
familles d'origine rendent les mêmes verdicts ; ici, on prouve la cinquième et ses points d'entrée. Données fictives.
"""

from __future__ import annotations

import pytest
from m1_front_office import conversation, garde_fou, plaintes, transferts, verdicts
from m1_front_office.outils import (
    outils,
    recevoir_message_canal,
    reinitialiser_registre,
    verifier_garde_fou,
)
from m1_front_office.registre import Registre

from opsys import garde_fou_texte, taxonomie
from opsys.outils import Niveau

FICTIF = True
NUMERO = "+15145550142"
HORODATAGE = "2026-09-29T09:15:00-04:00"


@pytest.fixture
def instance(declarer_services):
    declarer_services()
    taxonomie.enregistrer_zone_desservie(["Laval", "Québec"])
    taxonomie.enregistrer_fenetre_conversation(30)
    reinitialiser_registre()
    yield
    reinitialiser_registre()


def _sms(texte, message_id, minutes=0):
    heure = f"2026-09-29T09:{15 + minutes:02d}:00-04:00"
    return recevoir_message_canal(canal="sms", expediteur=NUMERO, message_id=message_id, recu_le=heure, texte=texte)


# -- le profil de M1 : cinq familles du socle, dans l'ordre du catalogue  ---
def test_m1_choisit_cinq_familles_du_socle_et_aucune_de_m7():
    noms = [f.nom for f in garde_fou.PROFIL_REPONSE_CLIENT.familles]
    assert noms == ["prix_montant", "date_execution", "engagement", "aveu", "avis_legal"]
    assert not {"prix_offre", "promesse_de_date", "adresse", "exageration"} & set(noms)


def test_chaque_famille_de_m1_a_son_code_dans_le_catalogue_des_verdicts_de_m1():
    """Une famille ajoutée au profil sans son code au catalogue lèverait au premier refus, en production."""
    for famille in garde_fou.PROFIL_REPONSE_CLIENT.familles:
        assert verdicts.est_verdict(famille.regle), famille.regle
        assert verdicts.construire_verdict(famille.regle, detail="x")["code"] == famille.regle


@pytest.mark.parametrize(("texte", "code"), [
    ("Le montant total est de 12 500 $.", "REJ-INTERDIT-PRIX"),
    ("Les travaux seront terminés demain.", "REJ-INTERDIT-DATE"),
    ("Nous nous engageons à terminer.", "REJ-INTERDIT-ENGAGEMENT"),
    ("C'est notre faute, nous sommes responsables.", "REJ-INTERDIT-AVEU"),
    ("Vous avez le droit de refuser de payer.", "REJ-INTERDIT-AVIS-LEGAL"),
])
def test_chaque_refus_de_m1_nomme_sa_regle_et_dit_quoi_retirer(texte, code):
    verdict = garde_fou.verifier_sortie(texte)
    assert verdict["code"] == code
    assert verdict["detail"] and "retire" in verdict["detail"], "un refus n'est jamais muet : il dit quoi retirer"


def test_un_texte_accepte_rend_un_verdict_ok_sans_detail():
    assert garde_fou.verifier_sortie("Nous avons bien reçu votre message.") == {
        "code": "OK", "statut": "", "detail": ""}


@pytest.mark.parametrize(("texte", "code"), [
    ("Nous nous engageons, c'est notre faute, à 500 $ selon la loi.", "REJ-INTERDIT-PRIX"),
    ("Nous nous engageons, c'est notre faute, selon la loi.", "REJ-INTERDIT-ENGAGEMENT"),
    ("C'est notre faute, selon la loi.", "REJ-INTERDIT-AVEU"),
    ("Votre garantie de cinq ans, selon la loi.", "REJ-INTERDIT-ENGAGEMENT"),  # « garantie » : l'engagement passe avant
])
def test_le_verdict_est_celui_de_la_premiere_regle_dans_l_ordre_fixe_le_droit_vient_en_dernier(texte, code):
    assert garde_fou.verifier_sortie(texte)["code"] == code


@pytest.mark.parametrize("avis", [
    "Vous avez le droit de refuser de payer.", "Selon la loi, vous pouvez annuler le contrat.",
    "Vos droits sont protégés.", "Le vice est illégal.", "C'est une situation juridique complexe.",
    "Vous avez un recours devant le tribunal.", "Une mise en demeure est possible.",
    "La prescription est de trois ans.", "La responsabilité civile de l'entreprise est engagée.",
    "La Loi sur la protection du consommateur s'applique.",
])
def test_un_avis_legal_est_refuse_par_le_garde_fou_lui_meme(avis):
    assert garde_fou.verifier_sortie(f"Bonjour. {avis}")["code"] == "REJ-INTERDIT-AVIS-LEGAL"


def test_le_refus_est_journalise_au_registre_avec_le_code_de_l_avis_legal():
    registre = Registre()
    garde_fou.verifier_sortie("Vos droits sont protégés.", registre=registre, horodatage=HORODATAGE)
    (alerte,) = registre.lire()
    assert alerte["type_entree"] == "alerte" and alerte["payload"] == {"code_verdict": "REJ-INTERDIT-AVIS-LEGAL"}
    garde_fou.verifier_sortie("Merci de votre message.", registre=registre, horodatage=HORODATAGE)
    assert len(registre.lire()) == 1, "un texte accepté n'écrit rien"
    with pytest.raises(ValueError, match="horodatage"):
        garde_fou.verifier_sortie("Vos droits sont protégés.", registre=Registre())


def test_le_garde_fou_de_m1_est_le_profil_du_socle_pas_une_copie():
    for texte in ("Vos droits sont protégés.", "Les travaux seront terminés demain.", "Merci de votre message."):
        violation = garde_fou_texte.premiere_violation(texte, garde_fou.PROFIL_REPONSE_CLIENT)
        assert garde_fou.verifier_sortie(texte)["code"] == ("OK" if violation is None else violation.regle)


# -- l'avis légal vaut PARTOUT où M1 passe un texte  ---
def test_l_outil_du_garde_fou_refuse_l_avis_legal_et_le_dit_dans_sa_description():
    assert verifier_garde_fou("Vous avez le droit de refuser de payer.")["code"] == "REJ-INTERDIT-AVIS-LEGAL"
    outil = next(o for o in outils() if o.nom == "m1_verifier_garde_fou")
    assert "avis légal" in outil.description and outil.niveau_effectif is not Niveau.N5


def test_le_gabarit_de_plainte_passe_par_le_meme_garde_fou_sans_verification_locale(monkeypatch):
    assert not hasattr(plaintes, "verifier_brouillon") and not hasattr(plaintes, "_AVIS_LEGAL")
    monkeypatch.setattr(plaintes, "GABARIT_PLAINTE", "Bonjour. Vos droits sont protégés.")
    resultat = plaintes.brouillon("plainte", (), retire=False)
    assert resultat["brouillon_reponse"] is None and resultat["sans_brouillon"] == "REJ-INTERDIT-AVIS-LEGAL"


def test_un_libelle_de_service_qui_parle_de_droit_est_retire_du_brouillon_de_qualification(instance):
    taxonomie.enregistrer_services([{"code": "conseil", "libelle": "Conseil juridique", "mots_cles": ["conseil"]}])
    reponse = _sms("Bonjour.", "SM-1")
    assert reponse["a_demander"] == ["service", "ville"]
    assert reponse["brouillon_reponse"] is None and reponse["sans_brouillon"] == "REJ-INTERDIT-AVIS-LEGAL"


def test_une_question_du_profil_qui_parle_de_droit_est_retiree_et_nommee_les_autres_partent(instance):
    taxonomie.enregistrer_questions_qualification({"gouttieres": [
        {"code": "droits", "question": "Connaissez-vous vos droits?", "mots_cles": ["zzz"]},
        {"code": "longueur", "question": "Quelle longueur?", "mots_cles": ["pied"]},
    ]})
    _sms("Mes gouttières fuient.", "SM-1")
    reponse = _sms("À Laval.", "SM-2", 3)
    assert reponse["questions_refusees"] == [{"code": "droits", "verdict": "REJ-INTERDIT-AVIS-LEGAL"}]
    assert "droits" not in reponse["brouillon_reponse"] and reponse["brouillon_reponse"].endswith("Quelle longueur?")
    assert reponse["envoye"] is False
    assert garde_fou.verifier_sortie(reponse["brouillon_reponse"])["code"] == "OK"


def test_les_questions_du_module_pur_passent_aussi_par_la_meme_famille():
    from opsys.taxonomie import QuestionQualification

    droit = QuestionQualification("droits", "Connaissez-vous vos droits?", ("zzz",), False)
    retenues, refusees = conversation._passer_le_garde_fou([droit])
    assert retenues == [] and refusees == [{"code": "droits", "verdict": "REJ-INTERDIT-AVIS-LEGAL"}]


# -- le résumé de transfert : conséquence documentée  ---
def test_un_resume_de_l_agent_qui_parle_de_droit_est_refuse_le_resume_du_code_reste_possible():
    """Conséquence de « l'avis légal partout » : un résumé fourni par l'agent est un texte de M1 comme un autre. Il ne
    peut pas NOMMER un avocat ou un tribunal ; le refus dit de retirer le terme, ou d'omettre `resume` : le code
    compose alors le résumé (catégories et termes reconnus, sans texte du client), sans passer par le garde-fou, et
    la menace juridique reste lisible dans « À voir » (N5)."""
    resume, sain, verdict = transferts.controler_resume("Le client menace de consulter son avocat.")
    assert resume is None and sain is True and verdict["code"] == "REJ-INTERDIT-AVIS-LEGAL"
    assert "avocat" in verdict["detail"]
    texte = "Le client demande un retour au sujet de l'eau dans le salon."
    ordinaire, _, verdict = transferts.controler_resume(texte)
    assert verdict is None and ordinaire == texte


def test_une_menace_juridique_reconnue_par_les_regles_ouvre_bien_son_transfert_avec_un_resume_du_code(
    instance, declarer_plaintes,
):
    declarer_plaintes()
    reponse = _sms("Si personne ne me répond, je vais consulter mon avocat.", "SM-1")
    assert reponse["decision"] == "ESCALADE_PLAINTE" and reponse["transfert"]["niveau"] == "N5"
    assert reponse["brouillon_reponse"] is None and reponse["sans_brouillon"] == "sujet_legal_reponse_humaine"
