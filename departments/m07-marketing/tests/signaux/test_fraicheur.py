"""Fraîcheur : l'âge de la dernière LECTURE RÉUSSIE face à la fenêtre déclarée, jamais l'âge d'un fait."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from m7_marketing.signaux import curseurs, fraicheur

MAINTENANT = datetime(2026, 11, 1, 12, 0, tzinfo=UTC)


def etat(flux="jour", lecture=None, jusqu=None, echec=None, source="search_console"):
    return curseurs.EtatIngestion(
        f"{source}|c|{flux}",
        source,
        "c",
        flux,
        derniere_lecture_reussie_le=lecture,
        donnees_jusqu_au=jusqu,
        dernier_echec=tuple(sorted(echec.items())) if echec else None,
    )


def iso(delta_h):
    return (MAINTENANT - timedelta(hours=delta_h)).isoformat().replace("+00:00", "Z")


def test_aucun_etat_ou_aucune_lecture_est_jamais_ingere_jamais_a_jour():
    assert fraicheur.evaluer("search_console", [], MAINTENANT)["statut"] == fraicheur.STATUT_JAMAIS
    r = fraicheur.evaluer("search_console", [etat()], MAINTENANT)
    assert r["statut"] == fraicheur.STATUT_JAMAIS and r["age_h"] is None and r["derniere_lecture_reussie_le"] is None


def test_a_jour_a_la_frontiere_inclusive_puis_perime():
    # search_console : fenêtre de 72 h
    assert (
        fraicheur.evaluer("search_console", [etat(lecture=iso(72), jusqu="2026-10-29")], MAINTENANT)["statut"]
        == "a_jour"
    )
    r = fraicheur.evaluer("search_console", [etat(lecture=iso(72.2), jusqu="2026-10-29")], MAINTENANT)
    assert r["statut"] == "perime" and r["age_h"] == "72.2" and r["donnees_jusqu_au"] == "2026-10-29"


def test_le_flux_le_plus_en_retard_decide():
    r = fraicheur.evaluer("search_console", [etat("jour", iso(1)), etat("requetes", iso(100))], MAINTENANT)
    assert r["statut"] == "perime" and r["age_h"] == "100.0"


def test_un_flux_jamais_lu_empeche_le_a_jour_du_compte():
    r = fraicheur.evaluer("search_console", [etat("jour", iso(1)), etat("pages", None)], MAINTENANT)
    assert r["statut"] == fraicheur.STATUT_JAMAIS


def test_un_echec_recent_apres_la_derniere_lecture_d_une_source_perimee_la_met_en_echec():
    echec = {"code": "REJ-SIGNAUX-AUTH-REFUSEE", "le": iso(2)}
    r = fraicheur.evaluer("search_console", [etat(lecture=iso(100), echec=echec)], MAINTENANT)
    assert r["statut"] == fraicheur.STATUT_ECHEC and r["dernier_echec"]["code"] == "REJ-SIGNAUX-AUTH-REFUSEE"


def test_un_echec_sans_aucune_lecture_reussie_est_en_echec_pas_jamais_ingere():
    r = fraicheur.evaluer("search_console", [etat(echec={"code": "REJ-SIGNAUX-RESEAU", "le": iso(1)})], MAINTENANT)
    assert r["statut"] == fraicheur.STATUT_ECHEC


def test_un_echec_ancien_avant_la_derniere_lecture_est_ignore_et_une_source_a_jour_le_reste():
    ancien = {"code": "REJ-SIGNAUX-RESEAU", "le": iso(50)}
    r = fraicheur.evaluer("search_console", [etat(lecture=iso(10), echec=ancien)], MAINTENANT)
    assert r["statut"] == "a_jour" and r["dernier_echec"] is None
    recent = {"code": "REJ-SIGNAUX-RESEAU", "le": iso(1)}
    r = fraicheur.evaluer("search_console", [etat(lecture=iso(10), echec=recent)], MAINTENANT)
    assert r["statut"] == "a_jour" and r["dernier_echec"]["code"] == "REJ-SIGNAUX-RESEAU"


def test_la_fenetre_la_plus_stricte_s_applique():
    e = [etat(lecture=iso(30))]
    # plus strict : respecté
    assert fraicheur.evaluer("search_console", e, MAINTENANT, fenetre_h=24)["statut"] == "perime"
    # plus lâche : ignoré
    assert fraicheur.evaluer("search_console", e, MAINTENANT, fenetre_h=500)["fenetre_h"] == 72
    assert fraicheur.evaluer("search_console", e, MAINTENANT)["statut"] == "a_jour"


def test_chaque_source_a_sa_fenetre():
    assert fraicheur.evaluer("umami", [etat(lecture=iso(40), source="umami")], MAINTENANT)["statut"] == "perime"  # 36 h
    assert fraicheur.evaluer("pagespeed", [etat(lecture=iso(40), source="pagespeed")], MAINTENANT)["statut"] == "a_jour"
