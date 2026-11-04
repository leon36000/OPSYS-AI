"""Sélection temporelle de l'historique M8 : l'instant réel, pas l'ordre lexical du texte RFC 3339.

Données fictives. Aucune horloge réelle, aucun réseau, aucune écriture Git.

Le défaut reproduit : ``m8_ent_mesures_hist.construit_le`` conserve le décalage RFC 3339 du producteur
(``-04:00`` / ``-05:00``). Trier ce texte avant ``LIMIT`` classe ``01:30-04:00`` (05:30 UTC) avant
``01:15-05:00`` (06:15 UTC) : la ligne la plus récente en temps réel peut être omise. La correction stocke une clé
UTC à longueur fixe, la remplit pour les historiques existants par migration, et refuse une clé absente ou incohérente.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from alembic import command
from m8_analytics import catalogue_mesures, entonnoir, entrepot, entrepot_stockage, jeux_fictifs, tendances
from sqlalchemy import inspect, select, text

from opsys import stockage
from opsys.stockage.schema import M8_ENT_MESURES_HIST

_TABLE = "m8_ent_mesures_hist"
_COLONNE = "construit_le_utc"
_INDEX = "ix_m8_ent_mesures_hist_metrique_utc"
_DERNIER = "2026-11-01T01:15:00-05:00"
_ENTREE = {
    "metric_id": "m8_taux_acceptation_pct",
    "nom": "Taux d'acceptation",
    "unite": "%",
    "proprietaire": "m03-estimation",
    "version_definition": "a" * 64,
    "fraicheur": {"fenetre_s": 86400},
}


@pytest.fixture
def base(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'opsys.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    yield url
    stockage.liberer()


@pytest.fixture(scope="module")
def catalogue():
    return catalogue_mesures.charger()


def _instant_ancien(rang: int) -> str:
    """50 instants de 01:16 à 02:05 en -04:00 (05:16 à 06:05 UTC), tous avant 06:15 UTC."""
    minutes = 16 + rang
    heure = 1 + minutes // 60
    minute = minutes % 60
    return f"2026-11-01T{heure:02d}:{minute:02d}:00-04:00"


def _etat_historique(cnx):
    return [
        tuple(ligne)
        for ligne in cnx.execute(
            select(M8_ENT_MESURES_HIST).order_by(
                M8_ENT_MESURES_HIST.c.construction_id, M8_ENT_MESURES_HIST.c.metric_id
            )
        ).mappings()
    ]


def _base_a(tmp_path, monkeypatch, revision: str) -> str:
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    cfg = stockage._config()
    with stockage.moteur(url).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, revision)
    return url


def _retirer_colonne(cnx) -> None:
    """Simule une base migrée avant 0087 : la colonne dérivée n'existait pas."""
    inspecteur = inspect(cnx)
    colonnes = {colonne["name"] for colonne in inspecteur.get_columns(_TABLE)}
    if _COLONNE not in colonnes:
        return
    index = {entree["name"] for entree in inspecteur.get_indexes(_TABLE)}
    if _INDEX in index:
        cnx.exec_driver_sql(f"DROP INDEX IF EXISTS {_INDEX}")
    cnx.exec_driver_sql(f"ALTER TABLE {_TABLE} DROP COLUMN {_COLONNE}")


def _inserer_historique_brut(cnx, instants: list[str]) -> None:
    constructions = [
        {"cid": f"c{rang:03d}", "instant": instant}
        for rang, instant in enumerate(instants)
    ]
    cnx.execute(
        text(
            "INSERT INTO m8_ent_constructions (construction_id, version_schema, version_catalogue, "
            "empreinte_registres, construit_le, nb_mesures, comptes) VALUES "
            "(:cid, 1, 'v', 'e', :instant, 1, '{}')"
        ),
        constructions,
    )
    lignes = [
        {"cid": f"c{rang:03d}", "instant": instant, "valeur": str(20 + rang)}
        for rang, instant in enumerate(instants)
    ]
    cnx.execute(
        text(
            "INSERT INTO m8_ent_mesures_hist (construction_id, metric_id, construit_le, statut, valeur, "
            "version_definition, dernier_fait_le) VALUES "
            "(:cid, 'm8_leads_recus', :instant, 'calculee', :valeur, 'v', NULL)"
        ),
        lignes,
    )


# ---------------------------------------------------------------------------
# La clé UTC : précision, offsets opposés, refus
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("texte", "attendu"),
    [
        ("2026-11-01T01:30:00-04:00", "2026-11-01T05:30:00.000000000Z"),
        ("2026-11-01T01:15:00-05:00", "2026-11-01T06:15:00.000000000Z"),
        ("2026-11-01T01:30:00.1-04:00", "2026-11-01T05:30:00.100000000Z"),
        ("2026-11-01T01:30:00.09-04:00", "2026-11-01T05:30:00.090000000Z"),
        ("2026-11-01T01:30:00.000000001-04:00", "2026-11-01T05:30:00.000000001Z"),
        ("2026-11-01T01:30:00.123456789-04:00", "2026-11-01T05:30:00.123456789Z"),
        ("2026-11-01T01:30:00Z", "2026-11-01T01:30:00.000000000Z"),
        ("2026-11-01T01:30:00,5-04:00", "2026-11-01T05:30:00.500000000Z"),
        ("2026-11-01 01:30:00.5-04:00", "2026-11-01T05:30:00.500000000Z"),
        ("2026-11-01t01:30:00.5z", "2026-11-01T01:30:00.500000000Z"),
    ],
)
def test_instant_utc_normalise_a_la_nanoseconde(texte, attendu):
    assert entonnoir.instant_utc(texte) == attendu


@pytest.mark.parametrize(
    "texte",
    [
        None,
        "",
        "2026-11-01T01:30:00",  # sans fuseau : jamais deviné
        "2026-02-30T01:30:00Z",  # date invalide
        "2026-11-01T01:30:60Z",  # seconde 60 non représentable
        "2026-11-01T01:30:00.1234567890Z",  # au-delà de la nanoseconde
        "2026-11-01T01:30:00+04:00:30",  # décalage non RFC 3339
        "2026-11-01T01:30:00-04:00:00",  # secondes de décalage à zéro mais hors RFC 3339
        "2026-11-01T01:30:00+00:00:00.000000789",  # fraction parasite dans le décalage
        "2026-11-01T01:30+04:00:00.000000789",  # fraction horaire recherchée par erreur dans l'offset
        "2026-W44-7T01:30:00Z",  # forme semaine ISO, pas date RFC 3339
        "2026-11-01T01:30+00:00",  # secondes absentes
    ],
)
def test_instant_utc_refuse_plutot_que_de_deviner(texte):
    assert entonnoir.instant_utc(texte) is None


def test_la_cle_utc_ordonne_les_offsets_opposes_et_les_fractions():
    textes = [
        "2026-11-01T01:30:00-04:00",  # 05:30 UTC
        "2026-11-01T01:15:00-05:00",  # 06:15 UTC
        "2026-11-01T01:15:00.000000001-05:00",
        "2026-11-01T01:15:00.000000002-05:00",
    ]
    cles = [entonnoir.instant_utc(texte) for texte in textes]
    assert cles == sorted(cles)
    assert len(set(cles)) == len(cles)


def test_le_producteur_ecrit_la_cle_utc_et_refuse_une_precision_non_representable(catalogue):
    resultat = entrepot.construire(
        jeux_fictifs.registres_fictifs(),
        catalogue,
        construit_le="2026-11-01T01:15:00.123456789-05:00",
        rang_precedent=0,
    )
    ligne = resultat["tables"][entrepot.TABLE_HISTORIQUE][0]
    assert ligne["construit_le"] == "2026-11-01T01:15:00.123456789-05:00"
    assert ligne["construit_le_utc"] == "2026-11-01T06:15:00.123456789Z"

    with pytest.raises(ValueError, match="REJ-ENTREPOT-INSTANT-INVALIDE"):
        entrepot.construire(
            jeux_fictifs.registres_fictifs(),
            catalogue,
            construit_le="2026-11-01T01:15:00.1234567890-05:00",
            rang_precedent=0,
        )


@pytest.mark.parametrize(
    "instant",
    [
        "0001-01-01T00:00:00+01:00",
        "9999-12-31T23:59:59-01:00",
    ],
)
def test_le_constructeur_refuse_les_instants_dont_la_normalisation_depasse_datetime(catalogue, instant):
    with pytest.raises(ValueError, match="REJ-ENTREPOT-INSTANT-INVALIDE"):
        entrepot.construire(
            jeux_fictifs.registres_fictifs(), catalogue, construit_le=instant, rang_precedent=0
        )


# ---------------------------------------------------------------------------
# Le vrai stockage : sélection, limite, égalités, fractions, aucune écriture
# ---------------------------------------------------------------------------
def test_lire_historique_trie_par_instant_reel_et_non_par_texte(base, catalogue):
    """Le point le plus récent (06:15 UTC) n'est pas omis par une limite de 50 lignes."""
    with stockage.transaction() as cnx:
        for rang in range(50):
            entrepot_stockage.reconstruire(
                cnx,
                jeux_fictifs.registres_fictifs(leads=20 + rang),
                catalogue,
                _instant_ancien(rang),
            )
        entrepot_stockage.reconstruire(
            cnx,
            jeux_fictifs.registres_fictifs(leads=70),
            catalogue,
            _DERNIER,
        )

    with stockage.transaction() as cnx:
        historique = entrepot_stockage.lire_historique(cnx, "m8_leads_recus", 50)

    assert len(historique) == 50
    assert historique[0]["valeur"] == "70"
    assert historique[0]["construit_le"] == _DERNIER
    # Le texte brut reste intact : aucune réécriture silencieuse de l'instant d'origine.
    assert historique[0]["construit_le"].endswith("-05:00")


def test_lire_historique_precise_les_fractions_et_n_ecrit_rien(base, catalogue):
    with stockage.transaction() as cnx:
        # 02:14:59.999999999-04:00 = 06:14:59.999999999 UTC, plus PETIT que 06:15:00.000000002 UTC,
        # mais plus GRAND dans l'ordre lexical du texte brut.
        entrepot_stockage.reconstruire(
            cnx,
            jeux_fictifs.registres_fictifs(leads=20),
            catalogue,
            "2026-11-01T02:14:59.999999999-04:00",
        )
        entrepot_stockage.reconstruire(
            cnx,
            jeux_fictifs.registres_fictifs(leads=21),
            catalogue,
            "2026-11-01T01:15:00.000000002-05:00",
        )

    with stockage.transaction() as cnx:
        avant = _etat_historique(cnx)
        historique = entrepot_stockage.lire_historique(cnx, "m8_leads_recus", 1)
        apres = _etat_historique(cnx)

    assert historique[0]["valeur"] == "21"
    assert historique[0]["construit_le_utc"] == "2026-11-01T06:15:00.000000002Z"
    assert avant == apres


def test_a_instant_egal_l_ordre_est_deterministe(base, catalogue):
    with stockage.transaction() as cnx:
        entrepot_stockage.reconstruire(
            cnx, jeux_fictifs.registres_fictifs(leads=20), catalogue, _DERNIER
        )
        entrepot_stockage.reconstruire(
            cnx, jeux_fictifs.registres_fictifs(leads=21), catalogue, _DERNIER
        )
        identifiants = sorted(
            ligne[0]
            for ligne in cnx.execute(
                select(M8_ENT_MESURES_HIST.c.construction_id).where(
                    M8_ENT_MESURES_HIST.c.metric_id == "m8_leads_recus"
                )
            ).all()
        )

    with stockage.transaction() as cnx:
        premier = entrepot_stockage.lire_historique(cnx, "m8_leads_recus", 1)
        second = entrepot_stockage.lire_historique(cnx, "m8_leads_recus", 1)

    assert premier == second
    assert premier[0]["construction_id"] == identifiants[0]


def test_une_cle_absente_fait_refuser_la_lecture(base, catalogue):
    with stockage.transaction() as cnx:
        entrepot_stockage.reconstruire(
            cnx, jeux_fictifs.registres_fictifs(), catalogue, _DERNIER
        )
        cnx.execute(text(f"UPDATE {_TABLE} SET {_COLONNE} = NULL"))

    with (
        pytest.raises(ValueError, match="REJ-ENTREPOT-HISTORIQUE-INSTANT-NON-NORMALISE"),
        stockage.transaction() as cnx,
    ):
        entrepot_stockage.lire_historique(cnx, "m8_leads_recus", 50)


def test_une_cle_absente_sur_une_autre_mesure_ne_bloque_pas_la_mesure_lue(base, catalogue):
    with stockage.transaction() as cnx:
        entrepot_stockage.reconstruire(
            cnx, jeux_fictifs.registres_fictifs(), catalogue, _DERNIER
        )
        cnx.execute(text(f"UPDATE {_TABLE} SET {_COLONNE} = NULL WHERE metric_id <> 'm8_leads_recus'"))

    with stockage.transaction() as cnx:
        historique = entrepot_stockage.lire_historique(cnx, "m8_leads_recus", 50)

    assert historique and historique[0]["metric_id"] == "m8_leads_recus"


def test_la_limite_par_defaut_reste_bornee_a_200(base):
    """La borne par défaut du contrat de lecture est 200, même quand l'historique en contient davantage."""
    instants = [
        (datetime(2026, 11, 1, tzinfo=UTC) + timedelta(minutes=rang)).isoformat()
        for rang in range(201)
    ]
    with stockage.transaction() as cnx:
        cnx.execute(
            text(
                "INSERT INTO m8_ent_constructions (construction_id, version_schema, version_catalogue, "
                "empreinte_registres, construit_le, nb_mesures, comptes) VALUES "
                "(:cid, 1, 'v', 'e', :instant, 1, '{}')"
            ),
            [{"cid": f"c{rang:03d}", "instant": instant} for rang, instant in enumerate(instants)],
        )
        cnx.execute(
            text(
                "INSERT INTO m8_ent_mesures_hist (construction_id, metric_id, construit_le, construit_le_utc, "
                "statut, valeur, version_definition, dernier_fait_le) VALUES "
                "(:cid, 'm8_leads_recus', :instant, :utc, 'calculee', :valeur, 'v', NULL)"
            ),
            [
                {
                    "cid": f"c{rang:03d}",
                    "instant": instant,
                    "utc": entonnoir.instant_utc(instant),
                    "valeur": str(rang),
                }
                for rang, instant in enumerate(instants)
            ],
        )
        historique = entrepot_stockage.lire_historique(cnx, "m8_leads_recus")

    assert len(historique) == 200
    assert historique[0]["valeur"] == "200"


def test_la_borne_haute_de_lecture_1000_est_acceptee(base):
    with stockage.transaction() as cnx:
        assert entrepot_stockage.lire_historique(cnx, "m8_leads_recus", 1000) == []


# ---------------------------------------------------------------------------
# Les historiques DÉJÀ stockés : migration 0087, sans réécrire le texte d'origine
# ---------------------------------------------------------------------------
def test_la_migration_remplit_les_historiques_deja_stockes_sans_reecrire_le_texte(tmp_path, monkeypatch):
    url = _base_a(tmp_path, monkeypatch, "0086")
    instants = [_instant_ancien(rang) for rang in range(50)] + [_DERNIER]
    with stockage.moteur(url).begin() as cnx:
        _retirer_colonne(cnx)
        _inserer_historique_brut(cnx, instants)

    cfg = stockage._config()
    with stockage.moteur(url).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "head")

    with stockage.transaction() as cnx:
        lignes = cnx.execute(
            text(f"SELECT construction_id, construit_le, {_COLONNE} FROM {_TABLE} ORDER BY construction_id")
        ).mappings().all()
        historique = entrepot_stockage.lire_historique(cnx, "m8_leads_recus", 50)

    assert [ligne["construit_le"] for ligne in lignes] == instants
    assert all(ligne[_COLONNE] == entonnoir.instant_utc(ligne["construit_le"]) for ligne in lignes)
    assert historique[0]["valeur"] == "70"
    assert historique[0]["construit_le"] == _DERNIER


@pytest.mark.parametrize(
    "instant",
    [
        "pas un instant",
        "2026-11-01T01:15:00.1234567890-05:00",  # au-delà de la nanoseconde
        "2026-11-01T01:15:00+04:00:30",  # décalage non RFC 3339
        "2026-11-01T01:15:00",  # sans fuseau
        "0001-01-01T00:00:00+01:00",  # instant hors plage UTC de datetime
        "9999-12-31T23:59:59-01:00",  # instant hors plage UTC de datetime
    ],
)
def test_la_migration_refuse_un_instant_non_representable_sans_toucher_aux_donnees(tmp_path, monkeypatch, instant):
    url = _base_a(tmp_path, monkeypatch, "0086")
    with stockage.moteur(url).begin() as cnx:
        _retirer_colonne(cnx)
        _inserer_historique_brut(cnx, [instant])

    cfg = stockage._config()
    with (
        pytest.raises(RuntimeError, match="migration 0087 refusée"),
        stockage.moteur(url).begin() as cnx,
    ):
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "head")

    assert stockage.revision_courante(url) == "0086"
    with stockage.moteur(url).begin() as cnx:
        colonnes = {colonne["name"] for colonne in inspect(cnx).get_columns(_TABLE)}
        ligne = cnx.execute(text(f"SELECT construit_le FROM {_TABLE}")).one()
    assert _COLONNE not in colonnes
    assert tuple(ligne) == (instant,)


def test_la_migration_remplit_une_cle_nulle_quand_la_colonne_existe_deja(tmp_path, monkeypatch):
    """Une colonne déjà créée mais laissée nulle (montage interrompu) est remplie sans écraser une clé cohérente."""
    url = _base_a(tmp_path, monkeypatch, "0086")
    with stockage.moteur(url).begin() as cnx:
        _inserer_historique_brut(cnx, [_DERNIER])
        cnx.execute(text(f"UPDATE {_TABLE} SET {_COLONNE} = NULL"))

    cfg = stockage._config()
    with stockage.moteur(url).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "head")

    with stockage.transaction() as cnx:
        cle = cnx.execute(text(f"SELECT {_COLONNE} FROM {_TABLE}")).scalar_one()
    assert cle == entonnoir.instant_utc(_DERNIER)


def test_la_migration_accepte_z_et_la_nanoseconde(tmp_path, monkeypatch):
    url = _base_a(tmp_path, monkeypatch, "0086")
    instants = [
        "2026-11-01T00:00:00Z",
        "2026-11-01T01:00:00.123456789-05:00",
    ]
    with stockage.moteur(url).begin() as cnx:
        _retirer_colonne(cnx)
        _inserer_historique_brut(cnx, instants)

    cfg = stockage._config()
    with stockage.moteur(url).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "head")

    with stockage.transaction() as cnx:
        cles = [
            ligne[0]
            for ligne in cnx.execute(
                text(f"SELECT {_COLONNE} FROM {_TABLE} ORDER BY construction_id")
            ).all()
        ]
    assert cles == [entonnoir.instant_utc(instant) for instant in instants]
    assert cles[1] == "2026-11-01T06:00:00.123456789Z"


@pytest.mark.parametrize(
    ("cle", "refus"),
    [
        ("2026-11-01T06:15:00.000000000Z", False),
        ("2026-11-01T05:30:00.000000001Z", True),
    ],
)
def test_la_migration_accepte_une_cle_coherente_et_refuse_une_cle_incoherente(
    tmp_path, monkeypatch, cle, refus
):
    url = _base_a(tmp_path, monkeypatch, "0086")
    with stockage.moteur(url).begin() as cnx:
        _inserer_historique_brut(cnx, [_DERNIER])
        cnx.execute(text(f"UPDATE {_TABLE} SET {_COLONNE} = :cle"), {"cle": cle})

    cfg = stockage._config()
    if refus:
        with (
            pytest.raises(RuntimeError, match="migration 0087 refusée"),
            stockage.moteur(url).begin() as cnx,
        ):
            cfg.attributes["connection"] = cnx
            command.upgrade(cfg, "head")
        assert stockage.revision_courante(url) == "0086"
        return

    with stockage.moteur(url).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "head")
    with stockage.transaction() as cnx:
        assert cnx.execute(text(f"SELECT {_COLONNE} FROM {_TABLE}")).scalar_one() == cle


def test_la_migration_est_reversible_sans_perdre_le_texte(tmp_path, monkeypatch):
    url = _base_a(tmp_path, monkeypatch, "0086")
    with stockage.moteur(url).begin() as cnx:
        _retirer_colonne(cnx)
        _inserer_historique_brut(cnx, [_DERNIER])

    cfg = stockage._config()
    with stockage.moteur(url).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "head")
    with stockage.moteur(url).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.downgrade(cfg, "0086")

    with stockage.moteur(url).begin() as cnx:
        colonnes = {colonne["name"] for colonne in inspect(cnx).get_columns(_TABLE)}
        texte = cnx.execute(text(f"SELECT construit_le FROM {_TABLE}")).scalar_one()
    assert _COLONNE not in colonnes
    assert texte == _DERNIER

    with stockage.moteur(url).begin() as cnx:
        cfg.attributes["connection"] = cnx
        command.upgrade(cfg, "head")
    with stockage.transaction() as cnx:
        cle = cnx.execute(text(f"SELECT {_COLONNE} FROM {_TABLE}")).scalar_one()
    assert cle == entonnoir.instant_utc(_DERNIER)


# ---------------------------------------------------------------------------
# Le contrat de tendances reste fail-closed sur la précision et la clé
# ---------------------------------------------------------------------------
def test_tendances_exclut_une_fraction_non_representable_ou_une_cle_incoherente():
    ligne = {
        "construction_id": "c001",
        "metric_id": _ENTREE["metric_id"],
        "construit_le": "2026-11-01T01:30:00.1234567890-04:00",
        "statut": "calculee",
        "valeur": "10.00",
        "version_definition": _ENTREE["version_definition"],
        "dernier_fait_le": None,
    }
    resultat = tendances.analyser([ligne], _ENTREE, datetime(2026, 11, 1, 12, 0, tzinfo=UTC))
    assert resultat["exclusions"]["instant_construction_invalide"] == 1
    assert resultat["serie"] == []

    ligne["construit_le"] = "2026-11-01T01:30:00-04:00"
    ligne["construit_le_utc"] = "2026-11-01T05:30:00.000000001Z"
    resultat = tendances.analyser([ligne], _ENTREE, datetime(2026, 11, 1, 12, 0, tzinfo=UTC))
    assert resultat["exclusions"]["instant_construction_invalide"] == 1
    assert resultat["serie"] == []
