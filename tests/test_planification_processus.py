"""Planification autonome : plusieurs PROCESSUS, et la mort brutale d'un processus (SIGKILL).

- six processus se disputent le même tour : le créneau est réservé par comparaison-échange, un seul travaille ;
- six processus appellent directement le même travail sous bail : un seul le détient à la fois (jeton de fencing) ;
- un processus tué net (SIGKILL) au milieu d'un tour de M8 laisse un travail à moitié fait : un autre processus le
  reprend après l'expiration du bail, termine, ne refait pas ce qui était fait, avec un jeton de fencing plus grand.

Vraie base SQLite partagée (fichier). Aucun réseau. Données fictives."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import planif_qa as pq
import pytest
from sqlalchemy import select

from opsys import stockage
from opsys.connecteurs_planification import bail, journal
from opsys.stockage.schema import PLANIFICATEUR_BAUX

FICTIF = True
RACINE = Path(__file__).resolve().parents[1]
ENTETE = textwrap.dedent(f'''
    import os, sys, time
    from pathlib import Path
    sys.path[:0] = [{str(RACINE / "src")!r}]
    sys.path[:0] = [str(p) for p in sorted(Path({str(RACINE / "departments")!r}).glob("*/src"))]
''')

COURSE = ENTETE + textwrap.dedent('''
    from opsys import service_acteur_systeme as systeme
    from opsys.connecteurs_planification import planificateur

    JOURNAL, DEPART, MODE = sys.argv[1], float(sys.argv[2]), sys.argv[3]


    class Compteur:
        nom = "m8.entrepot"

        def ressources(self, ctx):
            return ["r1"]

        def cle_bail(self, ressource):
            return "essai.course:" + ressource

        def constater(self, ressource, ctx):
            return {}

        def traiter(self, ressource, ctx, b):
            fd = os.open(JOURNAL, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
            os.write(fd, ("travail %d\\n" % os.getpid()).encode())
            os.close(fd)
            time.sleep(1.5)  # le travail dure : les autres processus arrivent pendant ce temps
            return {"traites": 1}


    ports = planificateur.Ports()
    while time.time() < DEPART:
        time.sleep(0.001)
    if MODE == "tour":
        print(planificateur.tour(None, ports=ports, executeurs=[Compteur()])["executeurs"]["m8.entrepot"]["statut"])
    else:  # le créneau est contourné : seul le bail départage
        with systeme.contexte_planificateur() as acteur:
            ctx = planificateur.Contexte(ports, acteur, "processus-%d" % os.getpid(), None, time.time())
            print(planificateur._passer(Compteur(), "actif", ctx)["statut"], ctx.porteur)
''')

SIGKILL = ENTETE + textwrap.dedent('''
    from pathlib import Path
    from opsys.connecteurs_planification import exec_departements, planificateur
    from opsys.departements import lire_manifeste

    original = exec_departements.appeler_outil


    def meurtrier(ctx, nom, arguments, *, autorises):
        resultat = original(ctx, nom, arguments, autorises=autorises)
        if nom == "m8_construire_entrepot":
            os.kill(os.getpid(), 9)  # mort brutale APRÈS la première étape durable, avant la deuxième
        return resultat


    exec_departements.appeler_outil = meurtrier
    deps = {d.id: d for d in [lire_manifeste(Path(sys.argv[1]) / "departments" / "m08-analytics")]}
    planificateur.tour(deps, ports=planificateur.Ports())
''')


@pytest.fixture
def p(tmp_path, monkeypatch):
    mon = pq.monter(tmp_path, monkeypatch, ("m08-analytics",))
    yield mon
    pq.demonter()


def _lancer(script: Path, *args: str, n: int = 1) -> list[subprocess.Popen]:
    return [subprocess.Popen([sys.executable, str(script), *args], env=dict(os.environ), stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True) for _ in range(n)]


def test_six_processus_se_disputent_un_tour_un_seul_travaille(p, tmp_path):
    p.activer("m8.entrepot", intervalle_s=3600)
    script = tmp_path / "course.py"
    script.write_text(COURSE, encoding="utf-8")
    journal_travail = tmp_path / "travail.log"
    enfants = _lancer(script, str(journal_travail), str(time.time() + 6.0), "tour", n=6)
    sorties = [e.communicate(timeout=120) for e in enfants]
    assert [e.returncode for e in enfants] == [0] * 6, [s[1][-800:] for s in sorties]
    statuts = sorted(s[0].strip() for s in sorties)
    assert len(journal_travail.read_text().splitlines()) == 1  # UN seul travail, malgré six processus
    assert statuts.count("ok") == 1 and set(statuts) <= {"ok", "deja_pris", "pas_echu"}


def test_six_processus_appellent_le_meme_travail_sous_bail_un_seul_le_detient(p, tmp_path):
    p.activer("m8.entrepot", intervalle_s=3600)
    script = tmp_path / "course.py"
    script.write_text(COURSE, encoding="utf-8")
    journal_travail = tmp_path / "travail.log"
    enfants = _lancer(script, str(journal_travail), str(time.time() + 6.0), "bail", n=6)
    sorties = [e.communicate(timeout=120) for e in enfants]
    assert [e.returncode for e in enfants] == [0] * 6, [s[1][-800:] for s in sorties]
    assert len(journal_travail.read_text().splitlines()) == 1  # un seul a travaillé pendant que les autres attendaient
    with stockage.transaction() as cnx:
        assert [j["statut"] for j in journal.lire(cnx,
        "m8.entrepot") if j["evenement"] == "bail_refuse"] == ["occupe"] * 5
        jeton = cnx.execute(select(PLANIFICATEUR_BAUX.c.jeton).where(
            PLANIFICATEUR_BAUX.c.ressource == "essai.course:r1")).scalar_one()
    assert jeton == 1  # un seul bail a jamais été pris


def test_un_processus_tue_net_laisse_un_travail_a_moitie_fait_qu_un_autre_reprend_sans_le_refaire(p, tmp_path):
    p.activer("m8.entrepot", intervalle_s=30)
    script = tmp_path / "meurtrier.py"
    script.write_text(SIGKILL, encoding="utf-8")
    enfant = subprocess.Popen([sys.executable, str(script), str(RACINE)], env=dict(os.environ),
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    sortie = enfant.communicate(timeout=120)
    assert enfant.returncode == -signal.SIGKILL, sortie[1][-800:]
    with stockage.transaction() as cnx:
        assert cnx.exec_driver_sql("SELECT COUNT(*) FROM m8_ent_constructions").scalar_one() == 1  # étape 1 durable
        mort = cnx.execute(select(PLANIFICATEUR_BAUX)).mappings().one()
    assert mort["jeton"] == 1 and mort["porteur"] != ""  # le bail du mort n'a jamais été libéré
    # tant que le bail n'a pas expiré, personne d'autre ne touche à cette ressource
    assert bail.acquerir(mort["ressource"], "autre", 60) is None
    resume = p.tour(avance=1000)  # le créneau et le bail du mort sont échus
    r = resume["executeurs"]["m8.entrepot"]
    assert r["statut"] == "ok" and r["etapes"] == 4
    with stockage.transaction() as cnx:
        assert cnx.exec_driver_sql("SELECT COUNT(*) FROM m8_ent_constructions").scalar_one() == 1  # pas refaite
        reprise = cnx.execute(select(PLANIFICATEUR_BAUX.c.jeton, PLANIFICATEUR_BAUX.c.porteur)).one()
    assert reprise[0] == 2 and reprise[1] == ""  # jeton de fencing plus grand, bail libéré par le repreneur

