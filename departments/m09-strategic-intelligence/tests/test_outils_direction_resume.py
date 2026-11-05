"""M9 — les synthèses historiques n'affirment pas un total complet si les recommandations sont tronquées."""

from m9_strategic_intelligence.outils_direction import _resume_actions_classement_incertain


def _revue_historique(total_recommandations, visibles):
    return {
        "synthese": {"recommandations_du_conseil": total_recommandations},
        "decisions": [{"issue": "RECOMMANDATION"}],
        "sections_direction": {
            "sections": {"recommandations": {"contenu": {"recommandations": visibles}}}
        },
    }


def test_historique_proposable_est_signale_et_completude_est_explicite():
    recommandation = {"actions": [{"action": "a1", "verdict": "PROPOSABLE"}]}
    assert _resume_actions_classement_incertain(_revue_historique(1, [recommandation])) == (1, True)
    assert _resume_actions_classement_incertain(_revue_historique(13, [recommandation])) == (1, False)


def test_synthese_courante_fournit_le_total_exact_meme_si_la_liste_est_bornee():
    revue = _revue_historique(13, [{"actions": []}])
    revue["synthese"]["actions_a_classement_non_verifie"] = 4
    assert _resume_actions_classement_incertain(revue) == (4, True)
