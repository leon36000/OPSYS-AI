"""Bus d'événements : deux livraisons de CONSTATS de même clé de contenu, sous des `evenement_id` différents, qui se
croisent entre la lecture du registre et son ajout. Deux moteurs (SQLite, PostgreSQL 17 réel).

Le défaut (trouvé sur PostgreSQL réel). Les consommateurs d'interconnexion sont écrits « lire le registre, puis ajouter
si la clé de contenu est neuve » (M1 retrait de consentement, M2 créances / conversions / contextes de site / factures
closes, M5 relevés de marketing, M8 `faits_operations`). Sous SQLite, `BEGIN IMMEDIATE` ne laisse qu'UN écrivain : la
seconde livraison lit APRÈS le commit de la première et rend `deja_enregistre`. Sous PostgreSQL (READ COMMITTED), la
seconde lit le registre AVANT le commit de la première (rien), puis `MaillonsDurables.append` recompte les rangs APRÈS
ce commit et prend le rang suivant : le même constat est rangé DEUX fois (aucune contrainte d'unicité ne le voit, les
rangs diffèrent). Le répartiteur ne sérialisait que la paire (événement, consommateur), jamais deux événements
différents pour le même consommateur.

La correction (`repartiteur._livrer_une_paire`) : un verrou consultatif de transaction NOMMÉ par consommateur, pris
avant la réclamation de la paire ; sur SQLite, aucun effet (l'écrivain unique fait déjà ce travail).

Le test est DÉTERMINISTE : la seconde livraison est lancée dans un fil, depuis le crochet qui précède l'ajout de la
première, et elle a le temps de finir sa propre transaction si rien ne l'en empêche.
"""

from __future__ import annotations

import datetime as dt
import threading

import interconnexion_charges as ch
import interconnexion_monde as im
import pytest
from m1_front_office import message_client_m4 as mc_m1
from m2_revenue_crm import faits_interconnexion as fi
from m5_financecore import charges_marketing_recues as cmr
from pg_parite import base_pg, serveur_pg, url_base  # noqa: F401  (fixtures pytest)
from sqlalchemy import select

from opsys import evenements, stockage
from opsys.evenements import repartiteur as rep
from opsys.stockage.maillons import MaillonsDurables
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS

FICTIF = True
M1, M2, M4, M5, M7, M8 = ("m01-front-office", "m02-revenue-crm", "m04-field-ops", "m05-financecore",
                          "m07-marketing", "m08-analytics")
ATTENTE_MAX_S = 2.0  # combien de temps la première livraison laisse la seconde tenter sa chance


@pytest.fixture
def monde(url_base, tmp_path, monkeypatch):  # noqa: F811
    m = im.monter(tmp_path, monkeypatch, (M1, M2, M4, M5, M7, M8), url=url_base)
    yield m
    im.demonter()


def _livrer(monde, evenement_id: str, consommateur: str) -> str | None:
    """Livre UN événement précis à UN consommateur (la paire), comme le répartiteur, en rendant le statut final."""
    with stockage.transaction() as cnx:
        evenement = dict(cnx.execute(select(EVENEMENTS_SORTANTS).where(
            EVENEMENTS_SORTANTS.c.evenement_id == evenement_id)).mappings().one())
    fonction = monde.departements[consommateur].charger_consommateurs()[evenement["type_evenement"]]
    return rep._livrer_une_paire(evenement, consommateur, fonction, dt.datetime(2026, 11, 2, 12, tzinfo=dt.UTC))


def _course(monde, monkeypatch, *, consommateur, registre, premier, second):
    """`premier` et `second` : `(evenement_id, type, producteur, charge)`. La livraison du premier est suspendue juste
    avant son ajout au registre `(consommateur, registre)` ; on lance alors celle du second, qui a ATTENTE_MAX_S pour
    terminer. Rend `(statut_1, statut_2, fil_second_termine_pendant_la_pause)`."""
    for evenement_id, type_evenement, producteur, charge in (premier, second):
        evenements.publier(type_evenement, producteur, charge, evenement_id=evenement_id)
    original = MaillonsDurables.append
    issues: dict[str, object] = {}
    fil: list[threading.Thread] = []
    pause = {"faite": False, "termine": None}

    def second_en_fil() -> None:
        try:
            issues["second"] = _livrer(monde, second[0], consommateur)
        except BaseException as exc:  # noqa: BLE001 — remonté au test
            issues["second"] = exc

    def append(self, maillon, **options):
        if (not pause["faite"] and self.departement == consommateur and self.registre == registre
                and threading.current_thread() is threading.main_thread()):
            pause["faite"] = True
            t = threading.Thread(target=second_en_fil, name="second-constat")
            fil.append(t)
            t.start()
            t.join(ATTENTE_MAX_S)
            pause["termine"] = not t.is_alive()
        return original(self, maillon, **options)

    monkeypatch.setattr(MaillonsDurables, "append", append)
    issues["premier"] = _livrer(monde, premier[0], consommateur)
    for t in fil:
        t.join(60)
        assert not t.is_alive(), "la seconde livraison ne se termine jamais (blocage)"
    assert pause["faite"], "le crochet d'ajout n'a jamais été atteint : le test ne prouve rien"
    for cle in ("premier", "second"):
        assert not isinstance(issues[cle], BaseException), (cle, repr(issues[cle]))
    return issues["premier"], issues["second"], pause["termine"]


def _compter_si(registre, predicat) -> int:
    with stockage.transaction():
        return sum(1 for m in registre if predicat(m))


# -- M2 : créance, facture close --------------------------------------------------------------------------------------
def test_m2_deux_relances_de_meme_cle_qui_se_croisent_sont_rangees_une_seule_fois(monde, monkeypatch):
    charge = ch.creance_relance(relance_id="rel-course", niveau=1)
    s1, s2, _ = _course(monde, monkeypatch, consommateur=M2, registre=fi.REGISTRE_CREANCES,
                        premier=("c1", "m5.creance_relance_preparee", M5, charge),
                        second=("c2", "m5.creance_relance_preparee", M5, dict(charge)))
    assert (s1, s2) == ("traite", "traite")
    assert monde.taille(M2, fi.REGISTRE_CREANCES) == 1, "le même constat est rangé deux fois (course lire-puis-ajouter)"
    assert monde.registre(M2, "constats_contradictoires") == []  # un rejeu identique reste silencieux


def test_m2_deux_relances_de_meme_cle_et_de_contenu_different_ne_donnent_qu_une_contradiction(monde, monkeypatch):
    s1, s2, _ = _course(monde, monkeypatch, consommateur=M2, registre=fi.REGISTRE_CREANCES,
                        premier=("c1", "m5.creance_relance_preparee", M5, ch.creance_relance(relance_id="r", niveau=1)),
                        second=("c2", "m5.creance_relance_preparee", M5, ch.creance_relance(relance_id="r", niveau=3)))
    assert (s1, s2) == ("traite", "traite")
    (creance,) = monde.registre(M2, fi.REGISTRE_CREANCES)
    assert creance["niveau"] == 1  # le PREMIER état reste
    (audit,) = monde.registre(M2, "constats_contradictoires")
    assert audit["champs"] == ["niveau"]


def test_m2_deux_factures_payees_de_meme_cle_qui_se_croisent_levent_la_creance_une_seule_fois(monde, monkeypatch):
    charge = ch.facture_emise(facture_id="F-course", statut="PAYEE")
    _course(monde, monkeypatch, consommateur=M2, registre=fi.REGISTRE_FACTURES_CLOSES,
            premier=("f1", "m5.facture_emise_constatee", M5, charge),
            second=("f2", "m5.facture_emise_constatee", M5, dict(charge)))
    assert monde.taille(M2, fi.REGISTRE_FACTURES_CLOSES) == 1


# -- M8 : faits_operations
# ----------------------------------------------------------------------------------------------
def test_m8_deux_constats_de_facture_de_meme_cle_qui_se_croisent_sont_ranges_une_seule_fois(monde, monkeypatch):
    charge = ch.facture_emise(facture_id="F-m8", statut="ENVOYEE")
    s1, s2, _ = _course(monde, monkeypatch, consommateur=M8, registre="faits_operations",
                        premier=("m8a", "m5.facture_emise_constatee", M5, charge),
                        second=("m8b", "m5.facture_emise_constatee", M5, dict(charge)))
    assert (s1, s2) == ("traite", "traite")
    assert monde.taille(M8, "faits_operations") == 1
    assert monde.registre(M8, "constats_contradictoires") == []


def test_m8_deux_constats_de_facture_de_contenu_different_ne_donnent_qu_une_contradiction(monde, monkeypatch):
    _course(monde, monkeypatch, consommateur=M8, registre="faits_operations",
            premier=("m8a", "m5.facture_emise_constatee", M5, ch.facture_emise(facture_id="F-m8", avant="1000.00")),
            second=("m8b", "m5.facture_emise_constatee", M5, ch.facture_emise(facture_id="F-m8", avant="1.00")))
    assert monde.taille(M8, "faits_operations") == 1
    (audit,) = monde.registre(M8, "constats_contradictoires")
    assert "montant_avant_taxes_cad" in audit["champs"]


# -- M5 : relevés de marketing
# -------------------------------------------------------------------------------------------
def test_m5_deux_releves_de_meme_cle_qui_se_croisent_ne_proposent_qu_un_brouillon(monde, monkeypatch):
    charge = ch.depense_marketing(releve_id="g-course", montant="125.40")
    _course(monde, monkeypatch, consommateur=M5, registre=cmr.REGISTRE,
            premier=("d1", "m7.depenses_marketing_constatees", M7, charge),
            second=("d2", "m7.depenses_marketing_constatees", M7, dict(charge)))
    assert _compter_si(__import__("opsys").stockage.maillons(M5, cmr.REGISTRE),
                       lambda m: m.get("cle") == cmr.cle(charge)) == 1


# -- M1 : retrait du consentement de suivi
# ----------------------------------------------------------------------------------
def test_m1_deux_retraits_de_meme_cle_qui_se_croisent_ne_sont_ranges_qu_une_fois(monde, monkeypatch):
    charge = ch.consentement_suivi_retire(intervention_id="interv-course")
    _course(monde, monkeypatch, consommateur=M1, registre=mc_m1.REGISTRE,
            premier=("t1", "m4.consentement_suivi_retire", M4, charge),
            second=("t2", "m4.consentement_suivi_retire", M4, dict(charge)))
    assert _compter_si(stockage.maillons(M1, mc_m1.REGISTRE),
                       lambda m: m.get("type_entree") == mc_m1.TYPE_RETRAIT) == 1


def test_les_recus_des_deux_livraisons_sont_traites_et_uniques(monde, monkeypatch):
    charge = ch.creance_relance(relance_id="rel-recus")
    _course(monde, monkeypatch, consommateur=M2, registre=fi.REGISTRE_CREANCES,
            premier=("c1", "m5.creance_relance_preparee", M5, charge),
            second=("c2", "m5.creance_relance_preparee", M5, dict(charge)))
    with stockage.transaction() as cnx:
        recus = cnx.execute(select(EVENEMENTS_RECUS.c.evenement_id, EVENEMENTS_RECUS.c.consommateur,
                                   EVENEMENTS_RECUS.c.statut, EVENEMENTS_RECUS.c.tentatives)
                            .where(EVENEMENTS_RECUS.c.consommateur == M2)).all()
    assert sorted((r.evenement_id, r.statut, r.tentatives) for r in recus) == [("c1", "traite", 1), ("c2", "traite", 1)]
