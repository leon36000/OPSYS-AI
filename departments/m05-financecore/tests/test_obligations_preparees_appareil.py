"""Contrat DEVICE nouveau, preuves SQL fictives sans Cap/Gateway."""

import contextlib
import copy
import datetime as dt
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from m5_financecore import obligations_preparees as ob
from m5_financecore import outils
from sqlalchemy import inspect

from opsys import contexte, idempotence, identite, intentions_obligations_m5, stockage

FICTIF = True


def test_deux_outils_declares_admin_globaux():
    by = {o.nom: o for o in outils.outils()}
    for name in ("m5_lire_obligations_preparees_appareil", "m5_enregistrer_obligation_preparee_appareil"):
        assert name in by
        assert by[name].roles_appareil == frozenset({"admin"})
        assert by[name].portee_contexte == "globale"


def args(**changes):
    result = {
        "categorie": "paies",
        "operation": "declarer",
        "revision_attendue": None,
        "motif": "FICTIF",
        "declaration": {
            "montant": "0.00",
            "source": "déclaration FICTIVE",
            "au": "2026-10-09",
            "echeance": None,
            "calendrier": None,
        },
    }
    result.update(changes)
    return result


HORA = "2026-10-09T12:00:00+00:00"
ACTEUR = contexte.IdentiteAppelante("admin.fictif", "admin")


@pytest.fixture
def sql(tmp_path, monkeypatch):
    path = tmp_path / "obligations-fictives.db"
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{path}")
    stockage.migrer()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, "admin.fictif", "Admin fictif", "mot-de-passe-fictif123", ["admin"])
    yield
    stockage.liberer()
    for f in tmp_path.glob("obligations-fictives.db*"):
        f.unlink()


def tables(cnx):
    return {
        n: list(cnx.exec_driver_sql('SELECT * FROM "' + n + '"').fetchall()) for n in inspect(cnx).get_table_names()
    }


@contextlib.contextmanager
def appel(arguments, cle="uuid-fictif-1", acteur=ACTEUR, quota=5400, appareil="device-fictif"):
    meta = idempotence.Meta(cle, appareil, HORA)
    rec = contexte.HorodatageAppareil(appareil, dt.datetime.fromisoformat(HORA), dt.datetime.fromisoformat(HORA))
    with (
        contexte.appele_par_appareil(acteur),
        contexte.receptionne_de(rec),
        contexte.sortie_bornee(quota),
        intentions_obligations_m5.contexte_intention(meta, arguments),
    ):
        yield meta


def mutation(a):
    return outils.enregistrer_obligation_preparee_appareil(**a)


def test_sql_lecture_retrait_rejeu_historique(sql):
    a = args()
    with stockage.transaction() as cnx, appel(a):
        ack = mutation(a)
        assert ack["accepte"] is True
        assert "calendrier_preparatoire" not in ack["resultat"]
        initial = tables(cnx)
        dto = outils.lire_obligations_preparees_appareil("2026-10-09", 0, 1)
        assert dto["resultat"]["obligations"][0]["declaration"]["montant"] == "0.00"
        assert tables(cnx) == initial
    b = args(operation="retirer", declaration=None, revision_attendue=ack["resultat"]["reference"])
    with stockage.transaction(), appel(b, "uuid-fictif-2"):
        assert mutation(b)["accepte"] is True
    stockage.liberer()
    with stockage.transaction() as cnx, appel(a):
        initial = tables(cnx)
        outils.verifier_rejeu_obligation_preparee_appareil(a, {"ok": True, "resultat": ack})
        assert tables(cnx) == initial


@pytest.mark.parametrize("field,value", [("version_schema", True), ("registre", "principal")])
def test_cache_ack_types_fermes(sql, field, value):
    a = args()
    with stockage.transaction() as cnx, appel(a):
        ack = mutation(a)
        bad = copy.deepcopy(ack)
        bad[field] = value
        before = tables(cnx)
        with pytest.raises(ob.Refus):
            outils.verifier_rejeu_obligation_preparee_appareil(a, {"ok": True, "resultat": bad})
        assert tables(cnx) == before


@pytest.mark.parametrize(
    "acteur",
    [
        None,
        contexte.IdentiteAppelante("admin.fictif", "employee"),
        contexte.IdentiteAppelante("admin.fictif", "seller"),
        contexte.IdentiteAppelante("absent", "admin"),
        contexte.IdentiteAppelante("admin.fictif", "admin", source="console"),
    ],
)
def test_autorite_avant_lecture_metier(sql, monkeypatch, acteur):
    def interdit():
        pytest.fail("registre métier ne doit pas être lu")

    monkeypatch.setattr(outils, "_snapshot_obligations_preparees", interdit)
    with stockage.transaction() as cnx, appel(args(), acteur=acteur):
        before = tables(cnx)
        result = mutation(args())
        assert result["accepte"] is False
        assert tables(cnx) == before


def test_retrait_role_quota_refus_et_panne_rollback(sql, monkeypatch):
    a = args()
    with stockage.transaction() as cnx, appel(a, quota=800):
        before = tables(cnx)
        assert mutation(a)["accepte"] is False
        assert tables(cnx) == before
    with stockage.transaction() as cnx:
        before = tables(cnx)
    real = ob.snapshot_courant

    def panne(snapshot):
        if snapshot:
            raise TypeError("panne fictive postappend")
        return real(snapshot)

    with monkeypatch.context() as m:
        m.setattr(ob, "snapshot_courant", panne)
        with pytest.raises(RuntimeError), stockage.transaction(), appel(a):
            mutation(a)
    with stockage.transaction() as cnx, appel(a):
        assert tables(cnx) == before
        ack = mutation(a)
        assert ack["accepte"] is True
        identite.retirer_role(cnx, "admin.fictif", "admin")
        before = tables(cnx)
        with pytest.raises(ob.Refus):
            outils.verifier_rejeu_obligation_preparee_appareil(a, {"ok": True, "resultat": ack})
        assert tables(cnx) == before


def test_concurrence_deux_uuid_meme_revision_sql(sql):
    barrier = Barrier(2)

    def worker(n):
        a = args()
        barrier.wait(timeout=10)
        with stockage.transaction(), appel(a, f"uuid-concurrent-{n}"):
            return mutation(a)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, [1, 2]))
    assert sum(r["accepte"] is True for r in results) == 1
    with stockage.transaction():
        assert len(outils._snapshot_obligations_preparees()) == 1


def test_lecture_arguments_deep_avant_source(sql, monkeypatch):
    def interdit():
        pytest.fail("arguments invalides : aucune source métier lue")

    monkeypatch.setattr(outils, "_snapshot_obligations_preparees", interdit)
    with stockage.transaction(), appel(args()):
        response = outils.lire_obligations_preparees_appareil("2026-02-30", 0, 8)
        assert response["accepte"] is False
        assert response["verdict"]["code"].endswith("ARGUMENTS-INVALIDES")
