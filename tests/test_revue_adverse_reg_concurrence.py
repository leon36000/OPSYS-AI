"""Revue adverse (reg) : courses entre VRAIS processus (pas des fils) sur un fichier SQLite réel.

Chaque processus enfant attend le même instant de départ puis tente la même chose ; le parent compte les gagnants.
Couvre : bail du planificateur (exclusion mutuelle + jeton de fencing croissant, y compris après libération),
réclamation d'idempotence d'appareil (une seule exécution fraîche), publication d'événement à identifiant fourni
(idempotente, conflit typé). Données fictives, aucun réseau.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from sqlalchemy import text

from opsys import stockage
from opsys.connecteurs_planification import bail

FICTIF = True
PROCESSUS = 6


@pytest.fixture
def base(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    stockage.liberer()  # aucune connexion du parent ne survit à l'ouverture des enfants
    yield url
    stockage.liberer()


def _course(code: str, n: int = PROCESSUS) -> list[dict]:
    """Lance `n` processus qui exécutent `code` (variable `i` = numéro du processus ; il imprime un JSON) au même
    instant, et rend leurs résultats."""
    depart = time.time() + 2.5
    programme = textwrap.dedent(f"""
        import json, sys, time
        i = int(sys.argv[1])
        while time.time() < {depart!r}:
            time.sleep(0.001)
        resultat = None
    """) + textwrap.dedent(code) + "\nprint(json.dumps(resultat))\n"
    procs = [subprocess.Popen([sys.executable, "-c", programme, str(i)], stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE, env=os.environ.copy(), text=True) for i in range(n)]
    sorties = []
    for p in procs:
        sortie, erreur = p.communicate(timeout=120)
        assert p.returncode == 0, erreur[-2000:]
        sorties.append(json.loads(sortie.strip().splitlines()[-1]))
    return sorties


# -- bail ----------------------------------------------------------------------------------------------------------
def test_un_seul_processus_obtient_le_bail(base):
    sorties = _course("""
        from opsys.connecteurs_planification import bail
        b = bail.acquerir("r:course", f"proc-{i}", 120)
        resultat = None if b is None else {"porteur": b.porteur, "jeton": b.jeton}
    """)
    gagnants = [s for s in sorties if s is not None]
    assert len(gagnants) == 1 and gagnants[0]["jeton"] == 1
    assert bail.detenu("r:course")["porteur"] == gagnants[0]["porteur"]


def test_course_sur_un_bail_expire_un_seul_repreneur_et_un_jeton_plus_grand(base):
    t = [1_000_000]
    ancien = bail.acquerir("r:reprise", "ancien", 60, horloge=lambda: t[0])
    stockage.liberer()
    # l'horloge réelle des enfants est très postérieure à 1 000 000 : le bail de l'ancien est expiré pour eux
    sorties = _course("""
        from opsys.connecteurs_planification import bail
        b = bail.acquerir("r:reprise", f"proc-{i}", 120)
        resultat = None if b is None else {"porteur": b.porteur, "jeton": b.jeton}
    """)
    gagnants = [s for s in sorties if s is not None]
    assert len(gagnants) == 1 and gagnants[0]["jeton"] > ancien.jeton


def test_le_jeton_de_fencing_ne_recule_jamais_meme_apres_liberation(base):
    """Un bail libéré puis repris doit porter un jeton PLUS GRAND : un ancien porteur muni du jeton précédent ne peut
    jamais passer pour plus récent (avant le correctif, la ligne était supprimée et le jeton repartait à 1)."""
    t = [1_000]
    a = bail.acquerir("r:fencing", "porteur-a", 60, horloge=lambda: t[0])
    bail.liberer(a)
    b = bail.acquerir("r:fencing", "porteur-b", 60, horloge=lambda: t[0])
    assert (a.jeton, b.jeton) == (1, 2)
    bail.liberer(b)
    c = bail.acquerir("r:fencing", "porteur-c", 60, horloge=lambda: t[0])
    assert c.jeton == 3
    t[0] += 61  # expiration : reprise par un autre porteur, jeton encore plus grand
    d = bail.acquerir("r:fencing", "porteur-d", 60, horloge=lambda: t[0])
    assert d.jeton == 4
    assert bail.renouveler(c, 60, horloge=lambda: t[0]) is None  # l'ancien porteur a perdu son bail


def test_un_bail_libere_n_est_plus_detenu_ni_renouvelable_et_se_reprend_aussitot(base):
    t = [1_000]
    a = bail.acquerir("r:libre", "porteur-a", 600, horloge=lambda: t[0])
    bail.liberer(a)
    assert bail.detenu("r:libre", horloge=lambda: t[0]) is None
    assert bail.renouveler(a, 60, horloge=lambda: t[0]) is None
    b = bail.acquerir("r:libre", "porteur-b", 60, horloge=lambda: t[0])  # sans attendre l'expiration de l'ancien
    assert b is not None and b.porteur == "porteur-b"
    bail.liberer(a)  # l'ancien porteur libère « son » bail : sans effet sur celui de b
    assert bail.detenu("r:libre", horloge=lambda: t[0])["porteur"] == "porteur-b"


def test_un_bail_libere_reste_libre_meme_si_l_horloge_recule(base):
    """Le marqueur « libre » ne dépend pas de l'horloge : un saut en arrière (NTP, bascule d'heure) ne ressuscite pas
    un bail rendu."""
    t = [1_000]
    a = bail.acquerir("r:horloge", "porteur-a", 600, horloge=lambda: t[0])
    bail.liberer(a)
    t[0] = 900
    assert bail.detenu("r:horloge", horloge=lambda: t[0]) is None
    b = bail.acquerir("r:horloge", "porteur-b", 60, horloge=lambda: t[0])
    assert b is not None and b.jeton == 2


def test_le_meme_porteur_reprend_son_bail_non_expire_sans_changer_de_jeton(base):
    t = [1_000]
    a = bail.acquerir("r:meme", "porteur-a", 60, horloge=lambda: t[0])
    a2 = bail.acquerir("r:meme", "porteur-a", 60, horloge=lambda: t[0])
    assert a2.jeton == a.jeton == 1


# -- idempotence d'appareil -------------------------------------------------------------------------------------------
def test_une_seule_execution_fraiche_par_cle_d_idempotence_entre_processus(base):
    sorties = _course("""
        import datetime as dt
        from opsys import idempotence, stockage
        from sqlalchemy import text
        meta = idempotence.Meta(cle="cle-unique", appareil="appareil-1",
                                horodatage_appareil="2026-11-01T12:00:00+00:00")
        with stockage.transaction() as cnx:
            r = idempotence.reclamer(cnx, meta, "m1_outil", {"a": 1}, dt.datetime.now(dt.UTC))
            if not r.rejouee:
                cnx.execute(text("INSERT INTO journal(quand, par, action, cible, details) "
                                 "VALUES ('t', 'proc', 'effet', 'cle-unique', '{}')"))
                idempotence.finaliser(cnx, meta, {"ok": True, "n": i})
            resultat = {"rejouee": r.rejouee, "reponse": r.reponse}
    """)
    frais = [s for s in sorties if not s["rejouee"]]
    assert len(frais) == 1
    rejoues = [s["reponse"] for s in sorties if s["rejouee"]]
    assert len(rejoues) == PROCESSUS - 1 and all(r["ok"] is True for r in rejoues)
    with stockage.transaction() as cnx:
        assert cnx.execute(text("SELECT count(*) FROM journal WHERE action = 'effet'")).scalar_one() == 1


def test_une_cle_reutilisee_pour_d_autres_arguments_est_un_conflit_entre_processus(base):
    sorties = _course("""
        import datetime as dt
        from opsys import idempotence, stockage
        meta = idempotence.Meta(cle="cle-partagee", appareil="appareil-1",
                                horodatage_appareil="2026-11-01T12:00:00+00:00")
        try:
            with stockage.transaction() as cnx:
                r = idempotence.reclamer(cnx, meta, "m1_outil", {"a": i % 2}, dt.datetime.now(dt.UTC))
                if not r.rejouee:
                    idempotence.finaliser(cnx, meta, {"ok": True})
            resultat = "fraiche" if not r.rejouee else "rejouee"
        except idempotence.MutationConflit:
            resultat = "conflit"
    """)
    assert sorties.count("fraiche") == 1
    assert set(sorties) <= {"fraiche", "rejouee", "conflit"} and "conflit" in sorties


# -- bus d'événements ----------------------------------------------------------------------------------------------
def test_publier_avec_identifiant_fourni_est_idempotent_entre_processus(base):
    sorties = _course("""
        from opsys.evenements import bus
        resultat = bus.publier("opsys.demo_complete", "m-demo", {"message": "x"}, evenement_id="evt-course")
    """)
    assert sorties == ["evt-course"] * PROCESSUS
    with stockage.transaction() as cnx:
        assert cnx.execute(text("SELECT count(*) FROM evenements_sortants WHERE evenement_id='evt-course'")
                           ).scalar_one() == 1


def test_publier_le_meme_identifiant_avec_une_autre_charge_est_un_conflit_entre_processus(base):
    sorties = _course("""
        from opsys.evenements import bus
        try:
            bus.publier("opsys.demo_complete", "m-demo", {"message": f"charge-{i % 2}"}, evenement_id="evt-conflit")
            resultat = "publie"
        except bus.ConflitPublication:
            resultat = "conflit"
    """)
    assert set(sorties) == {"publie", "conflit"}
    with stockage.transaction() as cnx:
        lignes = cnx.execute(text("SELECT charge FROM evenements_sortants WHERE evenement_id='evt-conflit'")).all()
    assert len(lignes) == 1
    gagnante = json.loads(lignes[0][0])["message"]
    # tout processus qui a publié « sans conflit » portait exactement la charge gagnante
    assert sorties.count("publie") == PROCESSUS // 2 and gagnante in ("charge-0", "charge-1")


def test_chaque_evenement_est_livre_une_seule_fois_quand_plusieurs_processus_repartissent(base):
    """Quatre répartiteurs en même temps sur vingt événements : l'effet du consommateur (un maillon durable) a lieu
    exactement une fois par événement, et chaque reçu est `traite` avec une seule tentative."""
    from opsys.evenements import bus

    messages = [f"message-{n:02d}" for n in range(20)]
    for message in messages:
        bus.publier("opsys.demo_complete", "m-demo", {"message": message})
    stockage.liberer()
    fixtures = str(Path(__file__).parent / "fixtures")
    sorties = _course(f"""
        import dataclasses, sys
        from pathlib import Path
        sys.path.insert(0, {fixtures!r})
        from opsys import evenements
        from opsys.departements import charger_departements
        base = charger_departements(Path({fixtures!r}) / "departements")["m09-demo"]
        dep = dataclasses.replace(base, module_outils="demo_consommateur_ok",
                                  evenements_publie=("opsys.demo_complete",),
                                  evenements_consomme=("opsys.demo_complete",))
        resultat = evenements.repartir({{dep.id: dep}}, limite=50)
    """, n=4)
    assert sum(s["traites"] for s in sorties) == 20
    recus = [m["message"] for m in stockage.maillons("m-demo-evenements-ok", "recus")]
    assert sorted(recus) == messages
    with stockage.transaction() as cnx:
        lignes = cnx.execute(text("SELECT statut, tentatives, count(*) FROM evenements_recus "
                                  "GROUP BY statut, tentatives")).all()
    assert [tuple(ligne) for ligne in lignes] == [("traite", 1, 20)]
