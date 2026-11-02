"""D0, de bout en bout : le JOUR d'un constat de M5 est minuit LOCAL de l'entreprise, donc un constat de 21 h locale est
encore « à jour » jusqu'au lendemain.

Le défaut (base ea631e4bc) : `synthese._jour_en_instant` datait un constat de M5 du DÉBUT du jour de référence en
UTC, avec la fenêtre de 24 h du catalogue, alors que le jour change à minuit LOCAL (UTC-5 en novembre). Même quand
tous les passages du planificateur réussissaient, les mesures datées par jour (cash libre et ses composantes,
factures émises, dépense comptabilisée, créances, plaintes…) et la composante « finance » du score étaient PÉRIMÉES
de 19 h à minuit locales.

Ici : les vrais départements, le vrai bus, le VRAI planificateur à horloge INJECTÉE (aucun sleep), des données
fictives semées par les vrais outils ; M8 lit par ses vrais outils (`Capacites`). Prouvé : à 21 h locale (02 h UTC le
lendemain) toutes les mesures datées par jour sont à jour et la composante finance est déterminée ; leur fenêtre de
24 h court bien depuis minuit LOCAL (si le planificateur tombe en panne, elles périment à minuit local + 24 h, pas
avant, pas après) ; le fuseau est celui du planificateur (une seule source, `opsys.horloge.FUSEAU_ENTREPRISE`) ; la
réponse de l'outil expose l'instant du dernier fait. Limites dites : SQLite seulement, horloge injectée, aucun
service externe.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import planif_m8_monde as pm
import pytest
from m8_analytics import outils as m8_outils
from m8_analytics import synthese

from opsys import horloge
from opsys.connecteurs_planification.planificateur import Ports
from opsys.outils import executer_atomique

FICTIF = True
LOCAL = ZoneInfo(horloge.FUSEAU_ENTREPRISE)
JOUR = 86400
# Les mesures de M8 datées par un JOUR de M5 (ou de M1) : le trésorier (quatre), puis les autres constats.
CASH = (
    "m8_cash_libre_cad",
    "m8_solde_tresorerie_cad",
    "m8_comptes_a_payer_cad",
    "m8_taxes_a_remettre_cad",
)
AUTRES = ("m8_depense_pub_comptabilisee_cad", "m8_factures_emises", "m8_facturation_emise_cad", "m8_plaintes_periode")
BORNES = {"sante": {"bornes": {"m8_cash_libre_cad": {"pire": "0", "cible": "50000"}}}}


@pytest.fixture
def monde_cash(tmp_path, monkeypatch, declarer_services):
    """Le trésorier fictif de M5 (cash libre, solde, comptes à payer, taxes) : le cas de référence calculé à la main."""
    m = pm.monter(tmp_path, monkeypatch, declarer_services)
    m.attendu = pm.semer_m5_tresorerie(m, tmp_path, monkeypatch)
    reel = m8_outils._configuration
    monkeypatch.setattr(m8_outils, "_configuration", lambda: {**reel(), **BORNES})
    yield m
    pm.demonter()


@pytest.fixture
def monde_tout(tmp_path, monkeypatch, declarer_services):
    """Les neuf constats : factures émises, dépense publicitaire comptabilisée, plaintes… (autres données de M5)."""
    m = pm.monter(tmp_path, monkeypatch, declarer_services)
    pm.semer_tout(m, pm.lire_yaml(pm.RACINE / "departments/m01-front-office/fixtures/plaintes/plaintes.v1.yaml"))
    yield m
    pm.demonter()


def _local(monde) -> dt.datetime:
    return dt.datetime.fromtimestamp(monde.horloge(), dt.UTC).astimezone(LOCAL)


def _etats(monde, ids) -> dict[str, tuple[str, str | None, str]]:
    mesures = monde.mesures()
    return {i: (mesures[i]["statut"], mesures[i]["fraicheur"], mesures[i]["dernier_fait_le"]) for i in ids}


def _finance(monde) -> dict:
    par_nom = {o.nom: o for o in monde.bus.departements[pm.M8].charger_outils()}
    reponse = executer_atomique(par_nom["m8_lire_sante_entreprise"], {"maintenant": monde.maintenant()})
    assert reponse["ok"] is True, reponse
    return next(c for c in reponse["resultat"]["composantes"] if c["id"] == "finance")


def _amener_a(monde, heure_locale: float, jour: str = "2026-11-12") -> None:
    """Avance l'horloge SANS passage du planificateur jusqu'à `heure_locale` (heures depuis minuit local de `jour`)."""
    cible = (dt.datetime.fromisoformat(jour).replace(tzinfo=LOCAL) + dt.timedelta(hours=heure_locale)).timestamp()
    assert cible >= monde.horloge()
    monde.horloge.avancer(cible - monde.horloge())


def test_le_fuseau_de_m8_et_celui_du_planificateur_sont_une_seule_valeur():
    """Une seule source : le fuseau où « aujourd'hui » se calcule pour M5 est celui où M8 date le jour d'un constat."""
    assert Ports().fuseau == horloge.FUSEAU_ENTREPRISE == horloge.fuseau_entreprise()
    assert synthese.FUSEAU_DEFAUT == horloge.FUSEAU_ENTREPRISE
    assert m8_outils._declaration_fuseau() == {"type_entree": "fuseau_entreprise", "fuseau": horloge.FUSEAU_ENTREPRISE}


def test_un_constat_de_21_h_locale_est_encore_frais_jusqu_au_lendemain_cash_libre_wallboard_et_score(monde_cash):
    monde = monde_cash
    monde.activer("actif", noms=("m5.constat.cash-libre",))
    assert monde.tour(1)["m5.constat.cash-libre"]["statut"] == "ok"
    monde.propager()
    minuit = dt.datetime(2026, 11, 12, tzinfo=LOCAL)
    avant = _etats(monde, CASH)
    # 00 h 00 min 01 s locale : calculé et à jour ; l'instant du dernier fait est minuit LOCAL du jour du constat
    for metric_id, (statut, fraicheur, dernier) in avant.items():
        assert (statut, fraicheur) == ("calculee", "a_jour"), (metric_id, avant[metric_id])
        assert dt.datetime.fromisoformat(dernier) == minuit, (metric_id, dernier)  # pas minuit UTC (19 h la veille)

    monde.tour(12 * 3600)  # le créneau de 12 h repasse : même donnée, aucun nouveau constat dans la journée
    _amener_a(monde, 21.0)
    assert _local(monde).strftime("%d %H:%M") == "12 21:00"
    assert dt.datetime.fromtimestamp(monde.horloge(), dt.UTC).strftime("%d %H:%M") == "13 02:00"  # le jour UTC a changé
    monde.propager()
    for metric_id, (statut, fraicheur, dernier) in _etats(monde, CASH).items():
        assert (statut, fraicheur) == ("calculee", "a_jour"), (metric_id, fraicheur, dernier)

    # la composante finance du score est DÉTERMINÉE à 21 h locale (elle était indéterminée : cash libre « périmé »)
    finance = _finance(monde)
    assert finance["statut"] == "determine", finance
    (indicateur,) = finance["indicateurs"]
    assert indicateur["fraicheur"] == "a_jour" and indicateur["valeur"] == monde.attendu["cash_libre"]

    # le wallboard dit « à jour » (ni périmée, ni tuile sans fraîcheur) à 21 h locale
    tuiles = monde.tuiles("direction")
    assert tuiles["cash-libre"]["fraicheur"] == "a_jour" and tuiles["cash-libre"]["perimee"] is False


def test_les_factures_emises_la_depense_comptabilisee_et_les_plaintes_beneficient_du_meme_correctif(monde_tout):
    """Les autres mesures datées par jour (factures émises, dépense publicitaire comptabilisée, plaintes de M1) passent
    par la même conversion : à 21 h locale elles sont à jour, et leur instant est un minuit LOCAL."""
    monde = monde_tout
    monde.activer("actif")
    resume = monde.tour(1)
    assert {v["statut"] for v in resume.values()} == {"ok"}, resume
    monde.propager()
    _amener_a(monde, 21.0)
    monde.propager()
    etats = _etats(monde, AUTRES)
    for metric_id, (statut, fraicheur, dernier) in etats.items():
        assert (statut, fraicheur) == ("calculee", "a_jour"), (metric_id, etats[metric_id])
        lu = dt.datetime.fromisoformat(dernier)
        assert lu.astimezone(LOCAL).time() == dt.time(0, 0), (metric_id, dernier)  # un minuit local, jamais 19 h
    # le dernier jour d'émission est celui de la facture F-2 (12 novembre), la plus récente
    assert dt.datetime.fromisoformat(etats["m8_factures_emises"][2]) == dt.datetime(2026, 11, 12, tzinfo=LOCAL)


def test_la_fenetre_de_24_h_court_depuis_minuit_local_si_le_planificateur_tombe_en_panne(monde_cash):
    monde = monde_cash
    """La fenêtre déclarée (24 h) n'a pas changé : elle court depuis minuit LOCAL du jour du constat. Sans nouveau
    passage,
    la mesure est à jour jusqu'à 24 h après ce minuit (00 h 00 le 13, heure locale) et périmée ensuite."""
    monde.activer("actif", noms=("m5.constat.cash-libre",))
    monde.tour(1)
    monde.propager()
    for heures, attendu in ((23.5, "a_jour"), (23.999, "a_jour"), (24.0, "a_jour"), (24.02, "perime"), (30, "perime")):
        _amener_a(monde, heures)
        assert monde.mesures()["m8_cash_libre_cad"]["fraicheur"] == attendu, (heures, _local(monde))


def test_le_changement_d_heure_ne_decale_pas_la_fenetre_le_constat_du_1er_novembre_dure_24_h_de_minuit_local():
    """Le dimanche 1er novembre 2026 le retour à l'heure normale ajoute une heure : minuit local du 1er est en heure
    d'été (04 h UTC). La fenêtre court depuis cet instant (24 h réelles), jamais depuis 05 h UTC."""
    instant = dt.datetime.fromisoformat(synthese.jour_en_instant("2026-11-01", horloge.FUSEAU_ENTREPRISE))
    assert instant == dt.datetime(2026, 11, 1, 4, 0, tzinfo=dt.UTC)
    suivant = dt.datetime.fromisoformat(synthese.jour_en_instant("2026-11-02", horloge.FUSEAU_ENTREPRISE))
    assert suivant - instant == dt.timedelta(hours=25)  # la journée locale du 1er dure 25 h
