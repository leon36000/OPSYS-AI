"""Bus d'événements en VRAIS PROCESSUS (SQLite et PostgreSQL 17 réel) : publication concurrente et livraison
concurrente.

- N processus publient le MÊME `evenement_id` : une seule ligne ; l'enveloppe identique est absorbée, l'enveloppe
  différente lève `ConflitPublication` chez les perdants (la première reste) ;
- N processus livrent en même temps un arriéré de constats de M2 et de M8 dont plusieurs `evenement_id` portent la même
  clé de contenu : chaque clé est rangée UNE fois, chaque reçu est `traite` une fois, aucune quarantaine, et une
  contradiction (même clé, contenu différent) est rangée une seule fois, premier état conservé.
Données fictives, aucun réseau.
"""

from __future__ import annotations

import interconnexion_charges as ch
import interconnexion_monde as im
import pytest
from m2_revenue_crm import faits_interconnexion as fi
from pg_concurrence import lancer
from pg_constats import propager, publier_enveloppe
from pg_parite import base_pg, serveur_pg, url_base  # noqa: F401  (fixtures pytest)
from sqlalchemy import func, select

from opsys import stockage
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS

FICTIF = True
N = 4
M2, M3, M5, M8 = "m02-revenue-crm", "m03-estimation", "m05-financecore", "m08-analytics"
T0 = 1_793_600_000.0  # un instant fixe (novembre 2026) : le répartiteur reçoit « maintenant » en paramètre


@pytest.fixture
def monde(url_base, tmp_path, monkeypatch):  # noqa: F811
    m = im.monter(tmp_path, monkeypatch, (M2, M3, M5, M8), url=url_base)
    yield m
    im.demonter()


def _sans_panne(issues) -> None:
    assert [i for i in issues if i[0] == "PANNE"] == [], issues


def test_n_processus_publient_la_meme_enveloppe_une_seule_ligne_et_aucun_conflit(monde):
    charge = ch.creance_relance(relance_id="rel-pub")
    issues = lancer(publier_enveloppe, [("pub-1", "m5.creance_relance_preparee", M5, charge)] * N, delai_s=300)
    _sans_panne(issues)
    assert issues == [("publie",)] * N
    with stockage.transaction() as cnx:
        assert cnx.execute(select(func.count()).select_from(EVENEMENTS_SORTANTS).where(
            EVENEMENTS_SORTANTS.c.evenement_id == "pub-1")).scalar_one() == 1


def test_n_processus_publient_deux_enveloppes_differentes_sous_le_meme_id_un_gagnant_et_des_conflits_dits(monde):
    a = ch.creance_relance(relance_id="rel-pub", niveau=1)
    b = ch.creance_relance(relance_id="rel-pub", niveau=3)
    issues = lancer(publier_enveloppe, [("pub-2", "m5.creance_relance_preparee", M5, c) for c in (a, b, a, b)],
                    delai_s=300)
    _sans_panne(issues)
    gagnants = [i for i in issues if i[0] == "publie"]
    conflits = [i for i in issues if i[0] == "conflit"]
    # la charge gagnante est publiée par tous ceux qui portent la même ; l'autre variante, par personne
    assert len(gagnants) == 2 and len(conflits) == 2 and all("charge" in c[1] for c in conflits), issues
    with stockage.transaction() as cnx:
        lignes = cnx.execute(select(EVENEMENTS_SORTANTS.c.charge).where(
            EVENEMENTS_SORTANTS.c.evenement_id == "pub-2")).all()
    assert len(lignes) == 1 and codec.decoder(lignes[0][0])["niveau"] in (1, 3)


def _arriere(monde_, n_cles: int = 4, par_cle: int = 3) -> None:
    """`n_cles` clés de contenu x `par_cle` identifiants d'événement chacune, pour M2 (créances) ET M8 (factures)."""
    from opsys import evenements

    for k in range(n_cles):
        for j in range(par_cle):
            evenements.publier("m5.creance_relance_preparee", M5, ch.creance_relance(relance_id=f"rel-{k}", niveau=1),
                               evenement_id=f"cr-{k}-{j}")
            evenements.publier("m5.facture_emise_constatee", M5, ch.facture_emise(facture_id=f"F-{k}", statut="PAYEE"),
                               evenement_id=f"fa-{k}-{j}")


def test_n_processus_livrent_un_arriere_de_constats_chaque_cle_est_rangee_une_fois(monde):
    _arriere(monde)
    issues = lancer(propager, [(T0, (M2, M8))] * N, delai_s=600)
    _sans_panne(issues)
    assert all(i[1]["echecs"] == 0 and i[1]["quarantaines"] == 0 for i in issues), issues
    reste = monde.repartir()
    assert reste["echecs"] == 0 and reste["quarantaines"] == 0
    assert monde.taille(M2, fi.REGISTRE_CREANCES) == 4
    assert monde.taille(M2, fi.REGISTRE_FACTURES_CLOSES) == 4
    assert monde.taille(M8, "faits_operations") == 4  # M8 ne reçoit que les 4 factures : une fois chacune
    assert monde.registre(M2, "constats_contradictoires") == [] and monde.registre(M8, "constats_contradictoires") == []
    with stockage.transaction() as cnx:
        recus = cnx.execute(select(EVENEMENTS_RECUS.c.statut, func.count()).group_by(EVENEMENTS_RECUS.c.statut)).all()
        doubles = cnx.execute(select(func.count()).select_from(
            select(EVENEMENTS_RECUS.c.evenement_id, EVENEMENTS_RECUS.c.consommateur)
            .group_by(EVENEMENTS_RECUS.c.evenement_id, EVENEMENTS_RECUS.c.consommateur)
            .having(func.count() > 1).subquery())).scalar_one()
    assert dict(recus) == {"traite": 36} and doubles == 0  # M2 : 12 relances + 12 factures ; M8 : 12 factures


def test_n_processus_livrent_des_constats_contradictoires_une_seule_contradiction_par_contenu(monde):
    from opsys import evenements

    evenements.publier("m5.creance_relance_preparee", M5, ch.creance_relance(relance_id="r", niveau=1),
                       evenement_id="k-0")
    for j in range(1, 7):  # six rejeux d'un contenu DIFFÉRENT (deux contenus distincts, trois fois chacun)
        evenements.publier("m5.creance_relance_preparee", M5, ch.creance_relance(relance_id="r", niveau=2 + j % 2),
                           evenement_id=f"k-{j}")
    # le premier est rangé seul avant la course : « le premier état reste » ne dépend pas de l'ordre des processus
    monde.repartir(passes=1, limite=1, departements=(M2,))
    issues = lancer(propager, [(T0, (M2,))] * N, delai_s=600)
    _sans_panne(issues)
    monde.repartir(departements=(M2,))
    (creance,) = monde.registre(M2, fi.REGISTRE_CREANCES)
    assert creance["niveau"] == 1
    audit = monde.registre(M2, "constats_contradictoires")
    assert len(audit) == 2 and sorted({a["empreinte_nouveau"] for a in audit}) == sorted(
        a["empreinte_nouveau"] for a in audit)  # une ligne par contenu contradictoire distinct, pas par rejeu
    assert monde.quarantaines() == []
