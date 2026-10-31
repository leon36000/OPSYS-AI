import datetime as dt
import importlib
from decimal import Decimal

import pytest
from opsys import stockage
from opsys.stockage import codec
from opsys.stockage.maillons import copier_maillons_avec_metadonnees
from opsys.stockage.schema import REGISTRES
from sqlalchemy import create_engine, insert, text

moteur = importlib.import_module("opsys.stockage.moteur")


@pytest.fixture
def cnx():
    engine = create_engine("sqlite://")
    REGISTRES.create(engine)
    with engine.connect() as c, c.begin():
        token = moteur._CONNEXION.set(c)
        try:
            yield c
        finally:
            moteur._CONNEXION.reset(token)
    engine.dispose()


def lire(c, **kw):
    return stockage.copier_maillons_stricts(
        c,
        departement="m05-financecore",
        registre="wct_recus",
        max_lignes=kw.get("max_lignes", 10),
        max_octets_ligne=kw.get("max_octets_ligne", 1024),
        max_octets_total=kw.get("max_octets_total", 4096),
    )


def ajouter(c, rang, raw):
    c.execute(insert(REGISTRES).values(departement="m05-financecore", registre="wct_recus", rang=rang, maillon=raw))


def test_doublon_brut_est_refuse_sans_changer_lecture_historique(cnx):
    ajouter(cnx, 0, '{"wct_id":"original","wct_id":"faux"}')
    assert (
        copier_maillons_avec_metadonnees(cnx, departement="m05-financecore", registre="wct_recus")
        .lignes[0]
        .maillon["wct_id"]
        == "faux"
    )
    with pytest.raises(ValueError):
        lire(cnx)


@pytest.mark.parametrize(
    "raw",
    [
        '{"a":{"v":1,"v":2}}',
        '{"a":1,"\\u0061":2}',
        "[NaN]",
        "[Infinity]",
        "[1e999]",
        '{"__opsys__":"decimal","v":"NaN"}',
        '{"a":',
        "[" * 66 + "0" + "]" * 66,
    ],
)
def test_json_non_fini_ambigu_ou_trop_profond_refuse(cnx, raw):
    ajouter(cnx, 0, raw)
    with pytest.raises(ValueError):
        lire(cnx)


def test_codec_compatibilite_et_copie_independante(cnx):
    valeur = {
        "d": Decimal("12.30"),
        "date": dt.date(2026, 10, 30),
        "datetime": dt.datetime(2026, 10, 30, 12, 4, tzinfo=dt.UTC),
        "tuple": (True, 1, 1.25),
        "bytes": b"abc",
        "__opsys__": "metier",
    }
    ajouter(cnx, 0, codec.encoder(valeur))
    ancien = copier_maillons_avec_metadonnees(cnx, departement="m05-financecore", registre="wct_recus")
    copie = lire(cnx)
    assert copie == ancien
    assert type(copie.lignes[0].rang) is int
    assert type(copie.lignes[0].maillon["tuple"][0]) is bool
    assert type(copie.lignes[0].maillon["tuple"][1]) is int
    assert type(copie.lignes[0].maillon["d"]) is Decimal
    copie.lignes[0].maillon["d"] = Decimal("99")
    assert lire(cnx).lignes[0].maillon == valeur


def test_limites_lignes_octets_et_absence_de_mutation(cnx):
    ajouter(cnx, 0, '"éé"')
    ajouter(cnx, 1, '"abcd"')
    avant = cnx.execute(text("SELECT rang,maillon FROM registres_maillons ORDER BY rang")).all()
    for kw in (
        {"max_lignes": 1},
        {"max_octets_ligne": 5},
        {"max_octets_ligne": 6, "max_octets_total": 11},
        {"max_lignes": True},
        {"max_octets_ligne": 1025, "max_octets_total": 1024},
    ):
        with pytest.raises(ValueError):
            lire(cnx, **kw)
    assert len(lire(cnx, max_octets_ligne=6, max_octets_total=12).lignes) == 2
    assert cnx.execute(text("SELECT rang,maillon FROM registres_maillons ORDER BY rang")).all() == avant


@pytest.mark.parametrize("rang", [-1, 1, 0.5])
def test_rang_non_contigu_ou_non_entier_refuse(cnx, rang):
    ajouter(cnx, rang, "{}")
    with pytest.raises(ValueError):
        lire(cnx)


def test_connexion_non_courante_ou_transaction_absente_refuse(cnx):
    ajouter(cnx, 0, "{}")
    token = moteur._CONNEXION.set(None)
    try:
        with pytest.raises(ValueError):
            lire(cnx)
    finally:
        moteur._CONNEXION.reset(token)
    cnx.exec_driver_sql("COMMIT")
    with pytest.raises(ValueError):
        lire(cnx)


def test_vraie_transaction_core_vide_puis_deux_registres():
    engine = moteur.moteur("sqlite://")
    REGISTRES.create(engine)
    try:
        with stockage.transaction("sqlite://") as c:
            assert lire(c).lignes == ()
            ajouter(c, 0, codec.encoder({"wct_id": "fictif"}))
            c.execute(
                insert(REGISTRES).values(
                    departement="m05-financecore",
                    registre="devis_recus",
                    rang=0,
                    maillon=codec.encoder({"devis_id": "d-fictif"}),
                )
            )
            assert lire(c).lignes[0].maillon["wct_id"] == "fictif"
            devis = stockage.copier_maillons_stricts(
                c,
                departement="m05-financecore",
                registre="devis_recus",
                max_lignes=10,
                max_octets_ligne=1024,
                max_octets_total=4096,
            )
            assert devis.lignes[0].maillon["devis_id"] == "d-fictif"
    finally:
        moteur.liberer()


def test_blob_sql_refuse(cnx):
    cnx.execute(
        text(
            "INSERT INTO registres_maillons (departement, registre, rang, maillon) "
            "VALUES ('m05-financecore', 'wct_recus', 0, x'7b7d')"
        )
    )
    with pytest.raises(ValueError):
        lire(cnx)
