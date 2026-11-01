"""Fraîcheur des mesures du catalogue (M8.5/M8.8) : la règle partagée par wallboards, santé, copilote et pont BI.

Prouve : A_JOUR / PERIME / INCONNU / MANQUANT / NON_APPLICABLE selon l'âge du dernier fait face à la fenêtre ; la PLUS
STRICTE des fenêtres (propriétaire, appelant) l'emporte ; une fenêtre invalide est refusée ou dite, jamais corrigée ;
`maintenant` illisible est un refus ; un fait daté dans le futur n'est jamais « à jour » ; une mesure périmée,
inconnue ou
manquante ne peut pas être montrée comme à jour. Frontières exactes (≤ fenêtre) testées.
"""

from __future__ import annotations

import pytest
from m8_analytics import catalogue_mesures, jeux_fictifs, moteur_mesures
from m8_analytics import fraicheur_mesures as fm

FICTIF = True
_CAT = catalogue_mesures.charger()
_ENTREES = catalogue_mesures.par_identifiant(_CAT)
_MESURES = {m["metric_id"]: m for m in moteur_mesures.lire(jeux_fictifs.registres_fictifs(jour="2026-10-30"))}
_DERNIER_LEADS = _MESURES["m8_leads_recus"]["dernier_fait_le"]  # 2026-10-30T08:20:00-04:00


def _statut(metric_id, maintenant, **kw):
    fenetre = fm.fenetre_effective(_ENTREES[metric_id], kw.get("fenetres", {}), kw.get("max_s"))
    return fm.evaluer(_MESURES[metric_id], fm.lire_maintenant(maintenant), fenetre)


def test_a_jour_dans_la_fenetre_et_perime_au_dela_avec_frontiere_exacte():
    assert _statut("m8_leads_recus", "2026-10-30T12:00:00-04:00")["statut"] == fm.STATUT_A_JOUR
    pile = "2026-10-31T08:20:00-04:00"  # exactement 86400 s après le dernier fait
    assert _statut("m8_leads_recus", pile)["statut"] == fm.STATUT_A_JOUR
    apres = _statut("m8_leads_recus", "2026-10-31T08:20:01-04:00")
    assert apres["statut"] == fm.STATUT_PERIME and apres["peut_etre_montree_comme_a_jour"] is False
    assert apres["age_s"] == 86401 and "au-delà" in apres["motif"]


def test_la_plus_stricte_des_fenetres_l_emporte():
    maintenant = "2026-10-30T12:20:00-04:00"  # 4 h après le dernier fait de leads
    assert _statut("m8_leads_recus", maintenant)["statut"] == fm.STATUT_A_JOUR
    assert _statut("m8_leads_recus", maintenant, max_s=3600)["statut"] == fm.STATUT_PERIME  # l'appelant resserre
    assert _statut("m8_leads_recus", maintenant, fenetres={"m8_leads_recus": 3600})["statut"] == fm.STATUT_PERIME
    # un appelant plus indulgent que le producteur ne gagne jamais
    large = _statut("m8_leads_recus", "2026-11-02T08:20:00-04:00", max_s=10**7)
    assert large["statut"] == fm.STATUT_PERIME and large["origine_fenetre"] == fm.ORIGINE_CATALOGUE
    resserre = fm.fenetre_effective(_ENTREES["m8_leads_recus"], {"m8_leads_recus": 7200}, 3600)
    assert resserre == {"secondes": 3600, "origine": fm.ORIGINE_APPELANT}
    assert (
        fm.fenetre_effective(_ENTREES["m8_leads_recus"], {"m8_leads_recus": 3600}, 7200)["origine"]
        == fm.ORIGINE_CONFIGURATION
    )


def test_une_mesure_terminale_est_non_applicable_sauf_si_l_appelant_resserre():
    tard = "2027-05-01T00:00:00-04:00"
    terminale = _statut("m8_chantiers_termines", tard)
    assert terminale["statut"] == fm.STATUT_NON_APPLICABLE and terminale["peut_etre_montree_comme_a_jour"] is True
    assert terminale["fenetre_s"] is None
    stricte = _statut("m8_chantiers_termines", tard, max_s=3600)
    assert stricte["statut"] == fm.STATUT_PERIME and stricte["origine_fenetre"] == fm.ORIGINE_APPELANT
    configuree = _statut("m8_chantiers_termines", tard, fenetres={"m8_chantiers_termines": 86400})
    assert configuree["statut"] == fm.STATUT_PERIME and configuree["origine_fenetre"] == fm.ORIGINE_CONFIGURATION


def test_une_mesure_non_calculable_est_manquante_jamais_a_jour():
    resultat = _statut("m8_clics_par_contenu", "2026-10-30T12:00:00-04:00")
    assert resultat["statut"] == fm.STATUT_MANQUANT and resultat["peut_etre_montree_comme_a_jour"] is False


def test_un_fait_dans_le_futur_ou_sans_instant_lisible_est_inconnu():
    futur = _statut("m8_leads_recus", "2026-10-29T00:00:00-04:00")
    assert futur["statut"] == fm.STATUT_INCONNU and futur["age_s"] is None
    mesure = {**_MESURES["m8_leads_recus"], "dernier_fait_le": None}
    fenetre = fm.fenetre_effective(_ENTREES["m8_leads_recus"], {})
    sans = fm.evaluer(mesure, fm.lire_maintenant("2026-10-30T12:00:00-04:00"), fenetre)
    assert sans["statut"] == fm.STATUT_INCONNU and sans["peut_etre_montree_comme_a_jour"] is False
    illisible = fm.evaluer(
        {**mesure, "dernier_fait_le": "hier soir"}, fm.lire_maintenant("2026-10-30T12:00:00Z"), fenetre
    )
    assert illisible["statut"] == fm.STATUT_INCONNU


@pytest.mark.parametrize("brut", [None, "", "2026-10-30T12:00:00", "demain", 12, "2026-13-45T00:00:00Z"])
def test_maintenant_illisible_ou_sans_fuseau_est_un_refus(brut):
    with pytest.raises(ValueError, match="REJ-FRAICHEUR-MAINTENANT-INVALIDE"):
        fm.lire_maintenant(brut)


@pytest.mark.parametrize("brut", [0, -5, True, 1.5, "60", 3650 * 86400 + 1])
def test_une_fenetre_d_appelant_invalide_est_refusee(brut):
    with pytest.raises(ValueError, match="REJ-FRAICHEUR-FENETRE-APPELANT-INVALIDE"):
        fm.lire_fenetre_appelant(brut)
    assert fm.lire_fenetre_appelant(None) is None and fm.lire_fenetre_appelant(60) == 60


def test_la_configuration_du_proprietaire_refuse_et_dit_sans_corriger():
    lue = fm.lire_configuration(
        {"m8_leads_recus": 3600, "m8_devis_envoyes": 0, "m8_clics_par_contenu": "vite", "faute_de_frappe": 5}, _CAT
    )
    assert lue["fenetres"] == {"m8_leads_recus": 3600}
    assert {r["metric_id"] for r in lue["refusees"]} == {"m8_devis_envoyes", "m8_clics_par_contenu"}
    assert lue["ignorees"] == ["faute_de_frappe"]
    assert fm.lire_configuration(None, _CAT) == {"fenetres": {}, "refusees": [], "ignorees": []}
    assert fm.lire_configuration([1], _CAT)["refusees"][0]["metric_id"] == "*"


def test_lire_mesures_avec_fraicheur_enrichit_chaque_mesure_et_ne_change_pas_la_valeur():
    maintenant = fm.lire_maintenant("2026-11-05T12:00:00-04:00")
    enrichies = fm.lire_mesures_avec_fraicheur(list(_MESURES.values()), _CAT, maintenant, {})
    assert [e["metric_id"] for e in enrichies] == list(_MESURES)
    assert all(e["valeur"] == _MESURES[e["metric_id"]]["valeur"] for e in enrichies)
    assert {e["fraicheur"]["statut"] for e in enrichies} == {
        fm.STATUT_PERIME,
        fm.STATUT_MANQUANT,
        fm.STATUT_NON_APPLICABLE,
    }
    assert not [
        e
        for e in enrichies
        if e["fraicheur"]["statut"] == fm.STATUT_PERIME and e["fraicheur"]["peut_etre_montree_comme_a_jour"]
    ]


@pytest.mark.parametrize(
    ("secondes", "texte"),
    [
        (45, "45 s"),
        (125, "2 min 05 s"),
        (7500, "2 h 05 min"),
        (90000, "1 j 1 h"),
        (-3, "0 s"),
    ],
)
def test_les_durees_sont_lisibles_en_francais(secondes, texte):
    assert fm.formater_duree(secondes) == texte
