"""Copies techniques SQLite fictives, pas preuve DEVICE/claim/writer documentaire."""

from __future__ import annotations

import datetime as dt
import importlib
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, insert, inspect, text, update

from opsys import stockage
from opsys.stockage import codec
from opsys.stockage.schema import REGISTRES

FICTIF = True
NOMS = ("evenements", "affaires", "documents_affaire", "documents_affaire_traces")
DATE = dt.datetime(2026, 10, 9, 12, 0, 0, 123456, tzinfo=dt.UTC)


def _module():
    return importlib.import_module("opsys.documents_affaire_instance")


@pytest.fixture
def base(tmp_path, monkeypatch):
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home-fictif"))
    monkeypatch.setenv("OPSYS_BASE_URL", f"sqlite:///{tmp_path / 'copies-fictives.db'}")
    stockage.migrer()
    yield
    stockage.liberer()


def _tables(cnx):
    return {
        n: sorted(
            map(
                tuple,
                cnx.execute(
                    text(
                        'SELECT * FROM "' + n.replace('"', '""') + '"',
                    )
                ).all(),
            ),
            key=repr,
        )
        for n in inspect(cnx).get_table_names()
    }


def _ajouter(cnx, rang, raw='{"fictif":true}', nom="documents_affaire", departement="m10-memoire"):
    cnx.execute(
        insert(REGISTRES).values(
            departement=departement,
            registre=nom,
            rang=rang,
            maillon=raw,
            cree_le=DATE,
        )
    )


def _raw(taille):
    prefixe, suffixe = '{"fictif":true,"x":"', '"}'
    assert taille >= len(prefixe) + len(suffixe)
    return prefixe + "a" * (taille - len(prefixe) - len(suffixe)) + suffixe


@pytest.mark.parametrize("nom", NOMS)
def test_registre_vide_identifie_namespace_sans_mutation(base, nom):
    with stockage.transaction() as cnx:
        avant = _tables(cnx)
        snap = _module().copier_registre_m10(cnx, nom)
        assert snap.departement == "m10-memoire" and snap.registre == nom
        assert snap.lignes == ()
        assert _tables(cnx) == avant


def test_type_codec_dates_et_namespace_preserves_copies_independantes(base):
    with stockage.transaction() as cnx:
        valeur = {"fictif": True, "quantite": Decimal("1.20"), "tuple": (1, "é"), "items": [1]}
        _ajouter(cnx, 0, codec.encoder(valeur), nom="evenements")
        _ajouter(cnx, 0, nom="affaires")
        _ajouter(cnx, 0, departement="m03-estimation", nom="evenements")
        avant = _tables(cnx)
        snap = _module().copier_registre_m10(cnx, "evenements")
        assert len(snap.lignes) == 1 and snap.lignes[0].rang == 0
        assert snap.lignes[0].cree_le == DATE.replace(tzinfo=None)
        assert snap.lignes[0].maillon == valeur
        assert type(snap.lignes[0].maillon["quantite"]) is Decimal
        assert type(snap.lignes[0].maillon["tuple"]) is tuple
        snap.lignes[0].maillon["items"].append(9)
        assert _module().copier_registre_m10(cnx, "evenements").lignes[0].maillon == valeur
        assert _tables(cnx) == avant


@pytest.mark.parametrize("mode", ["absente", "etrangere", "fermee", "hors_transaction"])
def test_connexion_canonique_requise_avant_select(base, mode):
    m = _module()
    with stockage.transaction() as cnx:
        foreign_engine = create_engine("sqlite://")
        other = foreign_engine.connect()
        if mode == "etrangere":
            other.begin()
        if mode == "fermee":
            other.close()
        if mode == "hors_transaction":
            cnx.commit()
        target = None if mode == "absente" else cnx if mode == "hors_transaction" else other
        emitted = []
        event.listen(cnx.engine, "before_cursor_execute", lambda _a, _b, sql, _c, _d, _e: emitted.append(sql))
        with pytest.raises(m.RefusCopieM10) as erreur:
            m.copier_registre_m10(target, "documents_affaire")
        assert erreur.value.code == "REJ-M10-COPIE-CONNEXION-INVALIDE"
        assert emitted == []
        other.close()
        foreign_engine.dispose()


@pytest.mark.parametrize("nom", [None, [], {}, "principal", "", "Documents_affaire"])
def test_nom_ferme_avant_select(base, nom):
    m = _module()
    with stockage.transaction() as cnx:
        emitted = []
        event.listen(cnx, "before_cursor_execute", lambda _a, _b, sql, _c, _d, _e: emitted.append(sql))
        with pytest.raises(m.RefusCopieM10) as erreur:
            m.copier_registre_m10(cnx, nom)
        assert erreur.value.code == "REJ-M10-COPIE-REGISTRE-INVALIDE"
        assert emitted == []


@pytest.mark.parametrize(
    ("nom", "cap"),
    [("documents_affaire", 16384), ("documents_affaire_traces", 8192), ("evenements", 65536), ("affaires", 65536)],
)
@pytest.mark.parametrize("delta", [-1, 0, 1])
def test_octets_par_ligne_frontiere_reelle_et_codec_apres_cadre(base, monkeypatch, nom, cap, delta):
    m = _module()
    with stockage.transaction() as cnx:
        _ajouter(cnx, 0, _raw(cap + delta), nom=nom)
        avant = _tables(cnx)
        calls = []
        original = codec.decoder
        monkeypatch.setattr(codec, "decoder", lambda value: calls.append(len(value.encode())) or original(value))
        if delta > 0:
            with pytest.raises(m.RefusCopieM10, match="BORNE-DEPASSEE"):
                m.copier_registre_m10(cnx, nom)
            assert calls == []
        else:
            snap = m.copier_registre_m10(cnx, nom)
            assert len(snap.lignes) == 1 and calls == [cap + delta]
        assert _tables(cnx) == avant


@pytest.mark.parametrize(
    "raw",
    [
        "null",
        "[]",
        "1",
        "true",
        '"texte fictif"',
        "{",
        '{"__opsys__":"dict","v":null}',
        '{"__opsys__":"decimal","v":"invalide"}',
        "[" * 2000 + "0" + "]" * 2000,
    ],
)
def test_codec_corrompu_ou_maillon_non_dict_refuse_sans_echo(base, raw):
    m = _module()
    with stockage.transaction() as cnx:
        _ajouter(cnx, 0, raw)
        avant = _tables(cnx)
        with pytest.raises(m.RefusCopieM10) as erreur:
            m.copier_registre_m10(cnx, "documents_affaire")
        assert erreur.value.code == "REJ-M10-COPIE-SOURCE-INVALIDE"
        assert erreur.value.detail == "la copie documentaire ne satisfait pas son contrat"
        assert _tables(cnx) == avant


@pytest.mark.parametrize("mode", ["trou", "blob", "vide", "rang_negatif", "date"])
def test_cadre_invalide_masque_tous_payloads_avant_premier_codec(base, monkeypatch, mode):
    m = _module()
    with stockage.transaction() as cnx:
        _ajouter(cnx, 0)
        if mode == "trou":
            _ajouter(cnx, 2)
        elif mode == "blob":
            _ajouter(cnx, 1, b'{"fictif":true}')
        elif mode == "vide":
            _ajouter(cnx, 1, "")
        elif mode == "rang_negatif":
            _ajouter(cnx, -1)
        else:
            cnx.execute(text("UPDATE registres_maillons SET cree_le='date-fictive-invalide' WHERE rang=0"))
        avant = _tables(cnx)
        monkeypatch.setattr(codec, "decoder", lambda _value: pytest.fail("codec avant cadre complet"))
        with pytest.raises(m.RefusCopieM10):
            m.copier_registre_m10(cnx, "documents_affaire")
        assert _tables(cnx) == avant


def test_une_selection_namespace_sans_fallback_ou_write_et_sans_cache(base):
    with stockage.transaction() as cnx:
        _ajouter(cnx, 0)
        statements = []
        event.listen(cnx, "before_cursor_execute", lambda _a, _b, sql, _c, _d, _e: statements.append(sql))
        a = _module().copier_registre_m10(cnx, "documents_affaire")
        assert len(a.lignes) == 1
        assert len([s for s in statements if s.lstrip().upper().startswith("SELECT")]) == 1
        assert all(s.lstrip().upper().startswith(("SELECT", "PRAGMA")) for s in statements)
        _ajouter(cnx, 1)
        b = _module().copier_registre_m10(cnx, "documents_affaire")
        assert len(b.lignes) == 2 and len(a.lignes) == 1


@pytest.mark.parametrize(
    ("nom", "n"),
    [("documents_affaire", 512), ("documents_affaire_traces", 512), ("evenements", 10000), ("affaires", 10000)],
)
def test_sentinel_rang_plafond_plus_un_refuse_avant_codec(base, monkeypatch, nom, n):
    with stockage.transaction() as cnx:
        cnx.execute(
            insert(REGISTRES),
            [
                {
                    "departement": "m10-memoire",
                    "registre": nom,
                    "rang": i,
                    "maillon": '{"fictif":true}',
                    "cree_le": DATE,
                }
                for i in range(n + 1)
            ],
        )
        avant = _tables(cnx)
        monkeypatch.setattr(codec, "decoder", lambda _value: pytest.fail("codec sentinel"))
        with pytest.raises(_module().RefusCopieM10, match="BORNE-DEPASSEE"):
            _module().copier_registre_m10(cnx, nom)
        assert _tables(cnx) == avant


@pytest.mark.parametrize(
    ("nom", "cap", "total"),
    [
        ("documents_affaire", 16384, 8203264),
        ("documents_affaire_traces", 8192, 2120704),
        ("evenements", 65536, 16777216),
        ("affaires", 65536, 16777216),
    ],
)
def test_cumul_exact_puis_plus_un_refuse_toute_copie(base, monkeypatch, nom, cap, total):
    with stockage.transaction() as cnx:
        q, r = divmod(total, cap)
        raws = [_raw(cap)] * q + ([_raw(r)] if r else [])
        cnx.execute(
            insert(REGISTRES),
            [
                {"departement": "m10-memoire", "registre": nom, "rang": i, "maillon": raw, "cree_le": DATE}
                for i, raw in enumerate(raws)
            ],
        )
        m = _module()
        before = _tables(cnx)
        assert len(m.copier_registre_m10(cnx, nom).lignes) == len(raws)
        assert _tables(cnx) == before
        if r:
            cnx.execute(
                update(REGISTRES).where(REGISTRES.c.registre == nom, REGISTRES.c.rang == q).values(maillon=_raw(r + 1))
            )
        else:
            _ajouter(cnx, q, nom=nom)
        before = _tables(cnx)
        monkeypatch.setattr(codec, "decoder", lambda _value: pytest.fail("codec cumul dépassé"))
        with pytest.raises(m.RefusCopieM10, match="BORNE-DEPASSEE"):
            m.copier_registre_m10(cnx, nom)
        assert _tables(cnx) == before


@pytest.mark.parametrize("delta", [0, 1])
def test_nonbmp_est_borne_en_octets_pas_caracteres(base, monkeypatch, delta):
    with stockage.transaction() as cnx:
        prefixe, suffixe = '{"fictif":true,"x":"', '"}'
        n = 8192 + delta - len(prefixe) - len(suffixe)
        raw = prefixe + "😀" * (n // 4) + "a" * (n % 4) + suffixe
        assert len(raw) < 8192 and len(raw.encode()) == 8192 + delta
        _ajouter(cnx, 0, raw, nom="documents_affaire_traces")
        if delta:
            monkeypatch.setattr(codec, "decoder", lambda _value: pytest.fail("codec nonBMP excessif"))
            with pytest.raises(_module().RefusCopieM10, match="BORNE-DEPASSEE"):
                _module().copier_registre_m10(cnx, "documents_affaire_traces")
        else:
            assert len(_module().copier_registre_m10(cnx, "documents_affaire_traces").lignes) == 1


@pytest.mark.parametrize("n", [511, 512])
def test_nombre_lignes_exact_511_512_admis(base, n):
    with stockage.transaction() as cnx:
        cnx.execute(
            insert(REGISTRES),
            [
                {
                    "departement": "m10-memoire",
                    "registre": "documents_affaire",
                    "rang": i,
                    "maillon": '{"fictif":true}',
                    "cree_le": DATE,
                }
                for i in range(n)
            ],
        )
        avant = _tables(cnx)
        snap = _module().copier_registre_m10(cnx, "documents_affaire")
        assert len(snap.lignes) == n and snap.lignes[-1].rang == n - 1
        assert _tables(cnx) == avant


def test_nom_str_subclass_ne_declenche_pas_de_hash(base):
    class NomHostile(str):
        def __hash__(self):
            raise AssertionError("hash caller arbitraire")

    with stockage.transaction() as cnx, pytest.raises(_module().RefusCopieM10, match="REGISTRE-INVALIDE"):
        _module().copier_registre_m10(cnx, NomHostile("documents_affaire"))


def test_sqlite_utf16_refuse_avant_registres_et_codec(tmp_path, monkeypatch):
    import sqlite3

    chemin = tmp_path / "utf16-fictif.db"
    with sqlite3.connect(chemin) as sqlite:
        sqlite.execute("PRAGMA encoding='UTF-16'")
        sqlite.execute("CREATE TABLE fictif_initialisation (id INTEGER)")
    monkeypatch.setenv("OPSYS_BASE_URL", f"sqlite:///{chemin}")
    stockage.migrer()
    with stockage.transaction() as cnx:
        emitted = []
        event.listen(cnx, "before_cursor_execute", lambda _a, _b, sql, _c, _d, _e: emitted.append(sql))
        monkeypatch.setattr(codec, "decoder", lambda _value: pytest.fail("codec UTF16"))
        with pytest.raises(_module().RefusCopieM10, match="ENCODAGE-INVALIDE"):
            _module().copier_registre_m10(cnx, "documents_affaire")
        assert emitted == ["PRAGMA encoding"]


def test_lecture_fichier_survit_reouverture_engine_sans_cache(base):
    with stockage.transaction() as cnx:
        _ajouter(cnx, 0)
        snapshot = _module().copier_registre_m10(cnx, "documents_affaire")
    snapshot.lignes[0].maillon["fictif"] = False
    stockage.liberer()
    with stockage.transaction() as cnx:
        autre = _module().copier_registre_m10(cnx, "documents_affaire")
        assert autre.lignes[0].maillon == {"fictif": True}
        assert autre.lignes[0].cree_le == DATE.replace(tzinfo=None)


@pytest.mark.parametrize(
    "raw",
    ['{"fictif":true,"x":NaN}', '{"fictif":true,"x":{"__opsys__":"decimal","v":"NaN"}}', '{"fictif":true,"\\ud800":1}'],
)
def test_decodage_non_reencodable_utf8_ou_nonfini_refuse(base, raw):
    with stockage.transaction() as cnx:
        _ajouter(cnx, 0, raw)
        avant = _tables(cnx)
        with pytest.raises(_module().RefusCopieM10, match="SOURCE-INVALIDE"):
            _module().copier_registre_m10(cnx, "documents_affaire")
        assert _tables(cnx) == avant
