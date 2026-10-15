"""Un candidat ancien ne contourne pas le nouveau backoff du vrai consommateur M8."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from m8_analytics import outils as m8_outils
from m8_analytics import registre
from sqlalchemy import event, insert, select, update

from opsys import evenements, stockage
from opsys.departements import charger_departements
from opsys.evenements import repartiteur
from opsys.stockage.schema import EVENEMENTS_RECUS

FICTIF = True
M8 = "m08-analytics"
CIBLE = "a-wct-retry-fictif"
AUTRE = "z-wct-independant-fictif"
T0 = dt.datetime(2026, 10, 15, 12, tzinfo=dt.UTC)


def _wct(ident):
    return {
        "wct_id": ident, "intervention_id": "intervention-fictive", "lead_id": "lead-fictif",
        "technicien_id": "technicien-fictif", "horodatage_completion": T0.isoformat(),
        "fix_gps_completion": {}, "duree_reelle_minutes": 120, "ecart_signale": False,
        "revue_id": None, "hash_maillon": "a" * 64, "consommateurs_cibles": ["M8"],
        "devis_id": None, "statut": "completed_verified",
    }


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "instance-fictive"))
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'fictif.db'}")
    racine = tmp_path / "departments"
    racine.mkdir()
    (racine / M8).symlink_to(Path(__file__).resolve().parents[1] / "departments" / M8,
                            target_is_directory=True)
    monkeypatch.setenv("OPSYS_DEPARTMENTS", str(racine))
    stockage.migrer()
    for ident in (CIBLE, AUTRE):
        evenements.publier("m4.travaux_termines", "m04-field-ops", _wct(ident), evenement_id=ident)
    yield charger_departements()
    stockage.liberer()


def _recu(ident):
    with stockage.transaction() as cnx:
        return dict(cnx.execute(select(EVENEMENTS_RECUS).where(
            (EVENEMENTS_RECUS.c.evenement_id == ident) & (EVENEMENTS_RECUS.c.consommateur == M8)
        )).mappings().one())


def _registres():
    snapshots = stockage.maillons(M8, "snapshots")
    assert registre.RegistreSnapshots(snapshots).valider_chaine() == (True, "")
    return len(snapshots), len(stockage.maillons(M8, "faits_chantier"))


@pytest.mark.parametrize("decalage", [0, -4], ids=["UTC", "offset-moins-quatre"])
@pytest.mark.parametrize("deja_echoue", [False, True], ids=["premiere-livraison", "reessai-du"])
def test_candidat_ancien_respecte_backoff_commite_par_autre_repartition(
        base, monkeypatch, decalage, deja_echoue):
    """Deux répartitions publiques, vraie écriture M8 annulée par une panne après calcul."""
    mesure_native = m8_outils._mesurer_et_publier
    appels_en_echec = []
    panne = True

    def mesurer_puis_panne(wct_id, faits):
        resultat = mesure_native(wct_id, faits)
        if wct_id == CIBLE and panne:
            # Les vraies écritures M8 sont présentes DANS le point de sauvegarde.
            assert _registres()[0] >= 1 and _registres()[1] >= 1
            appels_en_echec.append(wct_id)
            raise RuntimeError("panne transitoire fictive après écritures M8")
        return resultat

    monkeypatch.setattr(m8_outils, "_mesurer_et_publier", mesurer_puis_panne)
    instant = T0
    tentatives_avant = 0
    if deja_echoue:
        premier = evenements.repartir(base, limite=1, maintenant=instant.isoformat())
        assert premier["echecs"] == 1
        assert _registres() == (0, 0)
        instant += dt.timedelta(seconds=2)
        tentatives_avant = 1
    appels_en_echec.clear()
    livrer_native = repartiteur._livrer_une_paire
    interpose = False
    resultat_b = []

    def b_puis_livraison_a(evenement, consommateur, fonction, maintenant):
        nonlocal interpose
        if evenement["evenement_id"] == CIBLE and not interpose:
            interpose = True
            heure_b = instant.astimezone(dt.timezone(dt.timedelta(hours=decalage)))
            resultat_b.append(evenements.repartir(base, limite=1, maintenant=heure_b.isoformat()))
            assert resultat_b[-1]["echecs"] == 1
            assert _registres() == (0, 0)
        return livrer_native(evenement, consommateur, fonction, maintenant)

    monkeypatch.setattr(repartiteur, "_livrer_une_paire", b_puis_livraison_a)
    resultat_a = evenements.repartir(base, limite=1, maintenant=instant.isoformat())
    assert interpose and len(resultat_b) == 1
    recu = _recu(CIBLE)
    assert len(appels_en_echec) == 1, "A a relivré avant le nouveau backoff commité par B"
    assert resultat_a == {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 1}
    assert recu["statut"] == "echec" and recu["tentatives"] == tentatives_avant + 1
    echeance = instant + dt.timedelta(seconds=2 ** (tentatives_avant + 1))
    assert dt.datetime.fromisoformat(recu["prochaine_tentative"]) == echeance
    assert _registres() == (0, 0)

    # Un autre événement progresse ; le candidat reporté ne le bloque pas.
    autre = evenements.repartir(base, limite=1, maintenant=(instant + dt.timedelta(seconds=1)).isoformat())
    assert autre["traites"] == 1 and _recu(AUTRE)["statut"] == "traite"
    assert _registres() == (1, 1)
    assert _recu(CIBLE) == recu
    panne = False
    legitime = evenements.repartir(base, limite=1, maintenant=echeance.isoformat())
    assert legitime["traites"] == 1 and _recu(CIBLE)["statut"] == "traite"
    assert _recu(CIBLE)["tentatives"] == tentatives_avant + 2
    assert _registres() == (2, 2)
    assert evenements.repartir(base, limite=1, maintenant=echeance.isoformat())["livres"] == 0


def test_recu_echec_sans_echeance_et_zero_tentative_reste_admissible(base):
    """Un reçu initial explicite reste dû : NULL n'est pas un délai implicite."""
    with stockage.transaction() as cnx:
        cnx.execute(insert(EVENEMENTS_RECUS).values(
            evenement_id=CIBLE, consommateur=M8, statut="echec", tentatives=0,
            prochaine_tentative=None, resultat=None, derniere_erreur=None,
        ))
    assert _registres() == (0, 0)
    resultat = evenements.repartir(base, limite=1, maintenant=T0.isoformat())
    assert resultat["traites"] == resultat["livres"] == 1
    recu = _recu(CIBLE)
    assert recu["statut"] == "traite" and recu["tentatives"] == 1
    assert recu["prochaine_tentative"] is None
    assert _registres() == (1, 1)


@pytest.mark.parametrize("changement", ["echeance", "tentatives"])
def test_claim_ancien_ne_remplace_pas_metadata_changee_apres_select(base, changement):
    """Interposition SQL réelle, pas simulation d'un autre répartiteur concurrent."""
    with stockage.transaction() as cnx:
        cnx.execute(insert(EVENEMENTS_RECUS).values(
            evenement_id=CIBLE, consommateur=M8, statut="echec", tentatives=0,
            prochaine_tentative=None, resultat=None, derniere_erreur=None,
        ))
    moteur = stockage.moteur()
    interpose = []
    future = T0 + dt.timedelta(seconds=2)
    nouveaux = ({"prochaine_tentative": future.isoformat()} if changement == "echeance"
                else {"tentatives": 1})

    def changer_avant_claim(cnx, curseur, instruction, parametres, contexte_sql, executemany):
        compilation = getattr(contexte_sql, "compiled", None)
        commande = getattr(compilation, "statement", None)
        if (interpose or not getattr(commande, "is_update", False)
                or getattr(commande, "table", None) is not EVENEMENTS_RECUS):
            return
        interpose.append(changement)  # garde avant le vrai UPDATE imbriqué
        cnx.execute(update(EVENEMENTS_RECUS).where(
            (EVENEMENTS_RECUS.c.evenement_id == CIBLE) & (EVENEMENTS_RECUS.c.consommateur == M8)
        ).values(**nouveaux))

    event.listen(moteur, "before_cursor_execute", changer_avant_claim)
    try:
        resultat = evenements.repartir(base, limite=1, maintenant=T0.isoformat())
    finally:
        event.remove(moteur, "before_cursor_execute", changer_avant_claim)
    assert interpose == [changement]
    assert resultat == {"livres": 0, "traites": 0, "echecs": 0, "quarantaines": 0, "ignores": 1}
    recu = _recu(CIBLE)
    assert recu["statut"] == "echec"
    assert recu["tentatives"] == (0 if changement == "echeance" else 1)
    assert recu["prochaine_tentative"] == (future.isoformat() if changement == "echeance" else None)
    assert _registres() == (0, 0)

    # L'état frais reste livrable après retrait de l'interposition, à sa vraie échéance.
    controle = evenements.repartir(base, limite=1, maintenant=future.isoformat())
    assert controle["traites"] == controle["livres"] == 1
    assert _recu(CIBLE)["tentatives"] == (1 if changement == "echeance" else 2)
    assert _registres() == (1, 1)
