"""Le briefing du matin à 23 et à 200 décisions, PAR `Capacites` (PLAN T1.5-d) : la vraie troncature.

Constat de l'E2E : au-delà d'environ 22 décisions en attente, `m9_produire_briefing_matin` dépassait
les 6 000 caractères de `Capacites._tronquer` et l'app recevait un aperçu coupé au milieu. Ici, de
vraies demandes d'approbation dans une base migrée, les vrais manifestes, le vrai `Capacites` : la
réponse n'est jamais tronquée, elle dit « N autres éléments non affichés » et la suite se lit page
après page par `m9_lire_suite_briefing`, sans rien perdre ni répéter.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest
from m9_strategic_intelligence import briefing_matin
from sqlalchemy import update

from opsys import approbations, jetons, stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.outils import Niveau
from opsys.stockage.schema import APPROBATIONS

_RACINE_DEPARTEMENTS = Path(__file__).resolve().parents[2]
_MAINTENANT = "2026-09-28T07:00:00-04:00"


@pytest.fixture
def base_durable(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


@pytest.fixture
def capacites(base_durable):
    departements = charger_departements(_RACINE_DEPARTEMENTS)
    return Capacites(departements, stockage.transaction, filtre={"m09-strategic-intelligence"}, memoire=False)


def _en_attente(n: int) -> list[str]:
    """`n` demandes N4 en attente, créées à une minute d'écart : la première est sans équivoque la plus
    ancienne (le socle date à la seconde, deux demandes du même instant se départageraient au hasard)."""
    depart = dt.datetime(2026, 9, 1, 8, 0, tzinfo=dt.UTC)
    identifiants = []
    with stockage.transaction() as cnx:
        for numero in range(n):
            ident = approbations.creer_demande(
                cnx, "m06-material-control", "m6_creer_bon_commande", {"fournisseur": f"fictif-{numero}"},
                niveau=Niveau.N4, motif="réapprovisionnement fictif",
            )
            cnx.execute(update(APPROBATIONS).where(APPROBATIONS.c.id == ident).values(
                cree_le=(depart + dt.timedelta(minutes=numero)).isoformat()))
            identifiants.append(ident)
    return identifiants


def _taille_socle(reponse: dict) -> int:
    """Ce que `Capacites._tronquer` mesure : `json.dumps(reponse, ensure_ascii=False)`."""
    return len(json.dumps(reponse, ensure_ascii=False))


def _lire_la_suite(capacites, section: str, depart: int) -> list[dict]:
    lus = []
    pages = 0
    while depart is not None:
        reponse = capacites.appeler("m9_lire_suite_briefing", {
            "maintenant": _MAINTENANT, "section": section, "depart": depart,
        })
        assert reponse["ok"] is True, reponse
        assert "tronque" not in reponse and _taille_socle(reponse) <= jetons.LIMITE_SORTIE_DEFAUT
        page = reponse["resultat"]
        assert page["affiches"] == len(page["items"]) > 0
        lus.extend(page["items"])
        depart = page["prochain_depart"]
        pages += 1
        assert pages < 100
    return lus


def test_avant_la_borne_le_briefing_de_23_decisions_depassait_la_limite_du_socle(base_durable):
    """La preuve de la régression : le même briefing, non borné, dépasse 6 000 caractères à 23 décisions."""
    _en_attente(23)
    with stockage.transaction() as cnx:
        decisions = approbations.file_proprietaire(cnx, charger_departements(_RACINE_DEPARTEMENTS), limite=1000)
    sans_borne = briefing_matin.assembler_briefing_matin(_MAINTENANT, decisions, [], [])

    assert len(sans_borne["sections"]["decisions_en_attente"]["items"]) == 23
    assert _taille_socle({"ok": True, "resultat": sans_borne}) > jetons.LIMITE_SORTIE_DEFAUT


@pytest.mark.parametrize("total", [23, 200])
def test_le_briefing_de_23_ou_200_decisions_n_est_jamais_tronque_par_capacites(capacites, total):
    identifiants = _en_attente(total)

    reponse = capacites.appeler("m9_produire_briefing_matin", {"maintenant": _MAINTENANT})

    assert reponse["ok"] is True, reponse
    assert "tronque" not in reponse and "apercu" not in reponse  # pas l'aperçu coupé de `_tronquer`
    assert _taille_socle(reponse) <= jetons.LIMITE_SORTIE_DEFAUT
    briefing = reponse["resultat"]
    affichees = len(briefing["sections"]["decisions_en_attente"]["items"])
    assert 0 < affichees < total
    affichage = briefing["affichage"]
    assert affichage["n_non_affiches"] == total - affichees
    assert affichage["message"].startswith(f"{total - affichees} autres éléments non affichés")
    assert affichage["taille_caracteres"] <= affichage["borne_caracteres"] < jetons.LIMITE_SORTIE_DEFAUT
    [lire] = affichage["lire_la_suite"]
    assert lire["section"] == "decisions_en_attente" and lire["arguments"]["depart"] == affichees

    suite = _lire_la_suite(capacites, "decisions_en_attente", affichees)

    lus = [d["id"] for d in briefing["sections"]["decisions_en_attente"]["items"]] + [d["id"] for d in suite]
    assert lus == identifiants  # les `total`, ni perdues ni répétées, de la plus ancienne à la plus récente


def test_la_plus_ancienne_decision_est_la_premiere_meme_au_dela_de_cent_en_attente(capacites):
    """`file_proprietaire` borne à 100 demandes, les PLUS RÉCENTES, si on ne lui dit rien : les plus
    anciennes — les plus urgentes — disparaîtraient. M9 lui demande toute la file."""
    identifiants = _en_attente(120)

    briefing = capacites.appeler("m9_produire_briefing_matin", {"maintenant": _MAINTENANT})["resultat"]

    premiere = briefing["sections"]["decisions_en_attente"]["items"][0]
    assert premiere["id"] == identifiants[0]
    assert briefing["affichage"]["n_non_affiches"] + len(briefing["sections"]["decisions_en_attente"]["items"]) == 120


def test_sans_decision_ni_alerte_le_briefing_reste_complet_et_honnete(capacites):
    briefing = capacites.appeler("m9_produire_briefing_matin", {"maintenant": _MAINTENANT})["resultat"]

    assert briefing["affichage"]["complet"] is True and briefing["affichage"]["message"] is None
    assert briefing["sections"]["decisions_en_attente"] == {"items": [], "vide": True}
    assert {m["section"] for m in briefing["sections"]["manques_pour_conclure"]["items"]} == {
        "decisions_en_attente", "alertes_m8", "faits_veille",
    }


def test_lire_la_suite_au_dela_de_la_fin_est_un_refus_metier_pas_une_panne(capacites):
    _en_attente(3)
    reponse = capacites.appeler("m9_lire_suite_briefing", {
        "maintenant": _MAINTENANT, "section": "decisions_en_attente", "depart": 99,
    })
    assert reponse["ok"] is False and reponse["erreur"] == "refus_metier"
    assert "au-delà de la fin" in reponse["details"]
