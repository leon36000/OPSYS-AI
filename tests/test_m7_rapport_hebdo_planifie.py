"""Rapport marketing hebdomadaire planifié (M7-RAPPORT-HEBDO) : inactif par défaut, ombre d'abord, un rapport par
semaine,
panne de M8 sans demi-rapport, aucun envoi externe. Vrai planificateur, vrais outils de M8, horloge INJECTÉE, SQLite.

Données fictives. Limites dites : aucun service externe, PostgreSQL non exercé.
"""

from __future__ import annotations

import datetime as dt

import planif_qa as pq
import pytest
from sqlalchemy import select

from opsys import stockage
from opsys.connecteurs_planification import etat, exec_m7_rapport, inventaire, planificateur
from opsys.connecteurs_planification.planificateur import RefusExecuteur
from opsys.stockage.schema import EVENEMENTS_SORTANTS

FICTIF = True
NOM = "m7.rapport-hebdo"
M7, M8 = "m07-marketing", "m08-analytics"
# Lundi 9 novembre 2026, 09 h 00 à Toronto : la dernière semaine complète est du 2 au 8 novembre.
LUNDI_9 = dt.datetime(2026, 11, 9, 14, 0, tzinfo=dt.UTC).timestamp()
JOUR = 86400


@pytest.fixture
def plan(tmp_path, monkeypatch, declarer_services):
    declarer_services()
    p = pq.monter(tmp_path, monkeypatch, (M7, M8))
    p.horloge.t = LUNDI_9
    yield p
    pq.demonter()


def rapports():
    with stockage.transaction():
        return [m for m in stockage.maillons(M7, "rapports_hebdomadaires") if m.get("type") == "rapport_hebdo"]


def taches():
    with stockage.transaction():
        return list(stockage.maillons(M7, "taches_marketing"))


def types_publies():
    with stockage.transaction() as cnx:
        return sorted({t for (t,) in cnx.execute(select(EVENEMENTS_SORTANTS.c.type_evenement).distinct())})


def journal_executeur():
    from opsys.stockage.schema import PLANIFICATEUR_JOURNAL as J

    with stockage.transaction() as cnx:
        return [dict(r) for r in cnx.execute(select(J).where(J.c.executeur == NOM).order_by(J.c.id)).mappings()]


def test_la_definition_est_n2_quotidienne_inactive_et_inventoriee():
    d = etat.definition(NOM)
    assert d is not None and d.niveau == "N2" and d.intervalle_defaut_s == 86400 and not d.irreversible
    assert d.transport is None and d.plafond_appels_jour is None and d.famille == "departements"
    assert NOM in etat.noms()
    tour = inventaire.par_identifiant()["m7.rapport_hebdomadaire"]
    assert tour.executeur == NOM and tour.decision == "brancher_maintenant" and not tour.n3_ou_plus
    assert any(e.nom == NOM for e in planificateur.executeurs_par_defaut())


def test_les_outils_lus_sont_la_liste_fermee_de_deux_lectures_de_m8_en_n0():
    e = exec_m7_rapport.RapportHebdoM7()
    assert e.outils == ("m8_lire_mesures", "m8_lire_mesures_contenus")
    from m8_analytics import outils as m8

    catalogue = {o.nom: o for o in m8.outils()}
    for nom in e.outils:
        assert catalogue[nom].niveau_effectif.value == "N0" and not catalogue[nom].frontiere_humaine


def test_par_defaut_rien_ne_tourne_et_rien_n_est_ecrit(plan):
    resume = plan.tour()
    assert (
        resume["executeurs"][NOM] == {"statut": "inactif"}
        or resume["executeurs"].get(NOM, {}).get("statut") == "inactif"
    )
    assert rapports() == [] and taches() == [] and journal_executeur() == []


def test_en_ombre_il_dit_ce_qu_il_ferait_sans_lire_m8_ni_ecrire_ni_publier(plan, monkeypatch):
    def interdit(*a, **k):
        raise AssertionError("l'ombre ne doit appeler aucun outil")

    monkeypatch.setattr(exec_m7_rapport, "appeler_outil", interdit)
    plan.activer(NOM, "ombre", intervalle_s=JOUR)
    resume = plan.tour()
    assert resume["executeurs"][NOM]["aurait"] == 1 or resume["executeurs"][NOM].get("mode") == "ombre"
    assert rapports() == [] and taches() == [] and types_publies() == []
    evenements = [(j["evenement"], j["mode"], j["details"]) for j in journal_executeur()]
    assert any(e[0] == "aurait" and e[1] == "ombre" for e in evenements)


def test_actif_ecrit_un_rapport_pour_la_derniere_semaine_complete_puis_plus_rien_la_meme_semaine(plan, monkeypatch):
    plan.activer(NOM, "actif", intervalle_s=JOUR)
    plan.tour(avance=1)
    (r,) = rapports()
    assert r["semaine"] == "2026-11-02" and r["rapport"]["semaine"] == {"debut": "2026-11-02", "fin": "2026-11-08"}
    assert (
        r["rapport"]["sources"]["m8_mesures"] == "disponible" and r["rapport"]["sources"]["m8_contenus"] == "disponible"
    )
    # Les sept jours suivants : même semaine de rapport, aucun nouvel appel à M8, aucun doublon.
    appels = []
    original = exec_m7_rapport.appeler_outil
    monkeypatch.setattr(exec_m7_rapport, "appeler_outil", lambda *a, **k: appels.append(a[1]) or original(*a, **k))
    for _ in range(6):
        plan.tour(avance=JOUR)
    assert len(rapports()) == 1 and appels == []
    ignores = [j for j in journal_executeur() if j["evenement"] == "ressource"]
    assert len(ignores) >= 6


def test_la_semaine_suivante_est_un_nouveau_rapport(plan):
    plan.activer(NOM, "actif", intervalle_s=JOUR)
    plan.tour(avance=1)
    plan.horloge.avancer(7 * JOUR)
    plan.tour(avance=1)
    assert [r["semaine"] for r in rapports()] == ["2026-11-02", "2026-11-09"]


@pytest.mark.parametrize(
    ("instant", "semaine"),
    [
        (dt.datetime(2026, 11, 9, 5, 30, tzinfo=dt.UTC), "2026-11-02"),  # lundi 00 h 30 locale
        (
            dt.datetime(2026, 11, 9, 4, 30, tzinfo=dt.UTC),
            "2026-10-26",
        ),  # dimanche 23 h 30 locale : la semaine n'est pas finie
        (dt.datetime(2026, 11, 15, 14, 0, tzinfo=dt.UTC), "2026-11-02"),  # dimanche : encore la semaine d'avant
        (dt.datetime(2026, 11, 16, 5, 1, tzinfo=dt.UTC), "2026-11-09"),
    ],
)
def test_la_semaine_suit_la_date_locale_de_l_entreprise_pas_l_heure_utc(plan, instant, semaine):
    plan.horloge.t = instant.timestamp()
    plan.activer(NOM, "actif", intervalle_s=JOUR)
    plan.tour(avance=1)
    assert [r["semaine"] for r in rapports()] == [semaine]


def test_si_m8_ne_repond_pas_rien_n_est_ecrit_et_la_reprise_ecrit_une_fois(plan, monkeypatch):
    plan.activer(NOM, "actif", intervalle_s=JOUR)
    original = exec_m7_rapport.appeler_outil

    def panne(ctx, nom, arguments, *, autorises):
        raise RefusExecuteur("REJ-PLAN-OUTIL-REFUSE")

    monkeypatch.setattr(exec_m7_rapport, "appeler_outil", panne)
    resume = plan.tour(avance=1)
    assert resume["executeurs"][NOM].get("code") == "REJ-PLAN-OUTIL-REFUSE" or "erreur" in str(
        resume["executeurs"][NOM]
    )
    assert (
        rapports() == [] and taches() == [] and types_publies() == []
    )  # pas de rapport dégradé qui verrouille la semaine
    dernier = [j for j in journal_executeur() if j["evenement"] == "passage"][-1]
    assert dernier["statut"] in ("erreur", "refus")
    monkeypatch.setattr(exec_m7_rapport, "appeler_outil", original)
    plan.tour(avance=JOUR)
    plan.tour(avance=JOUR)
    assert len(rapports()) == 1


def test_sans_m8_ou_sans_m7_l_executeur_le_dit_et_ne_fait_rien(tmp_path, monkeypatch, declarer_services):
    declarer_services()
    p = pq.monter(tmp_path, monkeypatch, (M7,))
    try:
        p.horloge.t = LUNDI_9
        p.activer(NOM, "actif", intervalle_s=JOUR)
        p.tour(avance=1)
        assert rapports() == []
        assert any(j["code"] == "REJ-PLAN-DEPARTEMENT-ABSENT" for j in journal_executeur())
    finally:
        pq.demonter()


def test_aucun_envoi_externe_le_seul_type_publie_est_l_apprentissage_et_aucun_outil_n3_n_est_appele(plan, monkeypatch):
    appeles = []
    original = exec_m7_rapport.appeler_outil
    monkeypatch.setattr(
        exec_m7_rapport, "appeler_outil", lambda ctx, nom, *a, **k: appeles.append(nom) or original(ctx, nom, *a, **k)
    )
    plan.activer(NOM, "actif", intervalle_s=JOUR)
    plan.tour(avance=1)
    assert set(appeles) <= {"m8_lire_mesures", "m8_lire_mesures_contenus"}
    assert set(types_publies()) <= {"m7.apprentissage_marketing_constate"}


def test_un_outil_hors_liste_ou_de_niveau_n3_est_refuse_par_la_garde_commune(plan):
    from opsys.connecteurs_planification.exec_departements import appeler_outil
    from opsys.connecteurs_planification.planificateur import Contexte, NiveauInterdit

    ctx = Contexte(plan.ports, None, "essai", plan.departements, plan.horloge())
    with pytest.raises(NiveauInterdit):
        appeler_outil(ctx, "m7_decider_contenu", {}, autorises=frozenset({"m8_lire_mesures"}))
    with pytest.raises(NiveauInterdit):
        appeler_outil(ctx, "m7_decider_contenu", {}, autorises=frozenset({"m7_decider_contenu"}))
