"""Contrat public, identité et SQL fictifs ; aucune autorité Gateway revendiquée."""

import importlib.util
import inspect
from pathlib import Path

import pytest
from m8_analytics import outils
from sqlalchemy import MetaData, Table, select, update
from sqlalchemy import inspect as inspect_sql

from opsys import contexte, evenements, identite, stockage
from opsys.departements import charger_departements
from opsys.outils import Autonomie, executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS, REGISTRES

FICTIF = True
NOM = "m8_lire_provenance_m5_appareil"


def test_nouveau_lecteur_admin_append_sans_modifier_la_vue_legacy():
    catalogue = outils.outils()
    noms = [o.nom for o in catalogue]
    assert NOM in noms, "nouvel outil de provenance non déclaré"
    assert noms[-1] == NOM
    o = catalogue[-1]
    assert o.autonomie == Autonomie.T0 and o.niveau_effectif.value == "N0"
    assert o.roles_appareil == frozenset({"admin"}) and o.portee_contexte == "globale"
    assert list(inspect.signature(o.fonction).parameters) == ["perimetre", "wct_id", "decalage", "limite"]
    assert all(p.default is inspect.Parameter.empty for p in inspect.signature(o.fonction).parameters.values())
    assert o.parametres == {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "perimetre": {"type": "string", "enum": ["cash_global", "rentabilite_wct"]},
            "wct_id": {"type": ["string", "null"], "minLength": 1, "maxLength": 256},
            "decalage": {"type": "integer", "minimum": 0, "maximum": 10000},
            "limite": {"type": "integer", "minimum": 1, "maximum": 8},
        },
        "required": ["perimetre", "wct_id", "decalage", "limite"],
    }
    legacy = next(x for x in catalogue if x.nom == "m8_lire_vue_executive")
    assert list(inspect.signature(legacy.fonction).parameters) == ["aujourd_hui"]


# Les charges sont celles des tests bus historiques, validées au catalogue réel ;
# aucun expected DTO n'est reconstruit par le nouveau producteur.

ARGS = {"perimetre": "cash_global", "wct_id": None, "decalage": 0, "limite": 1}
ADMIN = contexte.IdentiteAppelante("admin.provenance.fictif", "admin")


def _fixture_historique(nom):
    path = Path(__file__).with_name(nom)
    spec = importlib.util.spec_from_file_location("fixture_provenance_" + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _snapshot(cnx):
    # META contient48tables ; alembic_version donne la49e réelle, également observée.
    names = inspect_sql(cnx).get_table_names()
    metadata = MetaData()
    return {
        name: tuple(tuple(row) for row in cnx.execute(select(Table(name, metadata, autoload_with=cnx))))
        for name in sorted(names)
    }


@pytest.fixture
def base(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'provenance-fictive.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home-fictif"))
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        identite.creer_personne(
            cnx, ADMIN.personne, "Admin fictif provenance", "mot-de-passe-fictif-long-provenance", ["admin"]
        )
    try:
        yield url
    finally:
        stockage.liberer()


def _lire(args=None, acteur=ADMIN, budget=5400):
    o = next(o for o in outils.outils() if o.nom == NOM)
    with contexte.appele_par_appareil(acteur), contexte.sortie_bornee(budget):
        return executer_atomique(o, ARGS if args is None else args)


def _publier_cash(livrer=True):
    c = _fixture_historique("test_evenements_cash_libre.py")._charge_valide()
    with stockage.transaction():
        evenements.publier("m5.cash_libre_constate", "m05-financecore", c, evenement_id=c["evenement_id"])
    if livrer:
        deps = charger_departements(Path(__file__).resolve().parents[2])
        resultat = evenements.repartir({"m08-analytics": deps["m08-analytics"]}, maintenant="2026-09-29T18:00:00+00:00")
        assert resultat["echecs"] == 0 and resultat["quarantaines"] == 0
    return c


def test_vrai_bus_sql_cash_id_receipt_et_fait_aucune_table_modifiee(base):
    c = _publier_cash()
    with stockage.transaction() as cnx:
        avant = _snapshot(cnx)
        reponse = _lire()
        assert _snapshot(cnx) == avant and len(avant) == 49
    assert set(reponse) == {"ok", "resultat"} and reponse["ok"] is True
    couple = reponse["resultat"]
    assert set(couple) == {"accepte", "resultat"} and couple["accepte"] is True
    dto = couple["resultat"]
    row = dto["publications"][0]
    assert row["publication"]["reference"]["evenement_id"] == c["evenement_id"]
    assert row["rapprochement"]["etat"] == "RECEPTION_LIEE_ID_EXACT"
    assert row["fait"]["reference"]["rang"] == 0
    assert row["fait"]["enregistrement_SQL"]["fuseau"] == "non_persiste"
    assert row["recu_bus"]["horodatage_reception"] is None
    assert dto["sources"][0]["lignes"] == dto["sources"][1]["lignes"] == dto["sources"][2]["lignes"] == 1
    assert "27861.98" not in str(dto) and "derniere_erreur" not in str(dto)


def test_publication_non_livree_ne_fabrique_pas_reception(base):
    _publier_cash(livrer=False)
    row = _lire()["resultat"]["resultat"]["publications"][0]
    assert row["fait"] is None and row["recu_bus"]["statut"] == "ABSENT"
    assert row["rapprochement"]["etat"] == "FAIT_ABSENT"


@pytest.mark.parametrize(
    "acteur",
    [
        None,
        contexte.IdentiteAppelante(ADMIN.personne, "employee"),
        contexte.IdentiteAppelante(ADMIN.personne, "admin", source="console"),
    ],
)
def test_identite_absente_ou_non_admin_refuse_avant_copies(base, monkeypatch, acteur):
    def interdit(*a, **kw):
        raise AssertionError("copie métier avant admission")

    monkeypatch.setattr(outils, "_copier_diagnostic_provenance_m5", interdit)
    with stockage.transaction() as cnx:
        avant = _snapshot(cnx)
        r = _lire(acteur=acteur)
        assert _snapshot(cnx) == avant
    assert r["resultat"]["accepte"] is False
    assert r["resultat"]["verdict"]["code"] == "REJ-M8-PROVENANCE-IDENTITE-INVALIDE"


def test_role_sql_retire_refuse_avant_metier_et_reactivation_relit(base, monkeypatch):
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, ADMIN.personne, "admin")
    with monkeypatch.context() as m:
        m.setattr(outils, "_copier_diagnostic_provenance_m5", lambda *a: pytest.fail("copie sans rôle SQL"))
        assert _lire()["resultat"]["verdict"]["code"] == "REJ-M8-PROVENANCE-IDENTITE-INVALIDE"
    with stockage.transaction() as cnx:
        identite.ajouter_role(cnx, ADMIN.personne, "admin")
    assert _lire()["resultat"]["resultat"]["publications"] == []


@pytest.mark.parametrize(
    "table,colonne,valeur",
    [
        (EVENEMENTS_SORTANTS, "charge", "{invalide"),
        (EVENEMENTS_RECUS, "resultat", "{invalide"),
        (REGISTRES, "maillon", "{invalide"),
    ],
)
def test_codec_corrompu_devient_refus_constant_sans_mutation(base, table, colonne, valeur):
    _publier_cash()
    with stockage.transaction() as cnx:
        cnx.execute(update(table).values({colonne: valeur}))
        avant = _snapshot(cnx)
        r = _lire()
        assert _snapshot(cnx) == avant
    assert r["ok"] is True and r["resultat"]["accepte"] is False
    assert r["resultat"]["verdict"]["code"] in {
        "REJ-M8-PROVENANCE-SOURCE-INVALIDE",
        "REJ-M8-PROVENANCE-REGISTRE-INVALIDE",
    }
    assert "{invalide" not in str(r)


def test_quota_enveloppe_faible_refuse_sans_tronquer_ni_ecrire(base):
    _publier_cash()
    with stockage.transaction() as cnx:
        avant = _snapshot(cnx)
        r = _lire(budget=1000)
        assert _snapshot(cnx) == avant
    assert r["resultat"]["verdict"]["code"] == "REJ-M8-PROVENANCE-SORTIE-TROP-VOLUMINEUSE"


def test_catalogue_source_revalide_avant_projection(base):
    _publier_cash()
    with stockage.transaction() as cnx:
        row = cnx.execute(select(EVENEMENTS_SORTANTS)).mappings().one()
        c = codec.decoder(row["charge"])
        c["devise"] = "USD"
        cnx.execute(update(EVENEMENTS_SORTANTS).values(charge=codec.encoder(c)))
    r = _lire()
    assert r["resultat"]["verdict"]["code"] == "REJ-M8-PROVENANCE-SOURCE-INVALIDE"


def test_vrai_bus_rentabilite_projection_pas_id_et_multidevis(base):
    fixture = _fixture_historique("test_evenements_rentabilite_chantier.py")
    charges = [
        fixture._m5(verdict="PARTIELLE"),
        fixture._m5(
            sequence=2, verdict="PARTIELLE", devis_id="devis-fictif-autre", evenement_id="rent-autre-devis-fictif"
        ),
    ]
    with stockage.transaction():
        for c in charges:
            evenements.publier("m5.rentabilite_chantier", "m05-financecore", c, evenement_id=c["evenement_id"])
    deps = charger_departements(Path(__file__).resolve().parents[2])
    assert (
        evenements.repartir({"m08-analytics": deps["m08-analytics"]}, maintenant="2026-09-29T18:00:00+00:00")["echecs"]
        == 0
    )
    with stockage.transaction() as cnx:
        avant = _snapshot(cnx)
        r = _lire({"perimetre": "rentabilite_wct", "wct_id": "wct-m8-1", "decalage": 0, "limite": 1})
        assert _snapshot(cnx) == avant
    dto = r["resultat"]["resultat"]
    assert dto["selection"] == {"publication_courante_id": None, "fact_courant_reference": None, "ambiguite": True}
    row = dto["publications"][0]
    assert row["rapprochement"]["etat"] == "CORRESPONDANCE_DE_PROJECTION"
    assert "ID_NON_PERSISTE_DANS_FAIT" in row["rapprochement"]["codes"]
    assert row["fait"]["evenement_id_persiste"] is None
    assert row["publication"]["devis_id"] == "devis-fictif-autre"


def test_rangs_sql_non_contigus_et_date_sans_fuseau_restant_exacts(base):
    _publier_cash()
    with stockage.transaction() as cnx:
        cnx.execute(update(REGISTRES).where(REGISTRES.c.departement == "m08-analytics").values(rang=42))
    row = _lire()["resultat"]["resultat"]["publications"][0]
    assert row["fait"]["reference"]["rang"] == 42
    assert row["fait"]["enregistrement_SQL"]["fuseau"] == "non_persiste"
    assert "+00:00" not in row["fait"]["enregistrement_SQL"]["valeur"]


def test_relecture_apres_restart_et_offset_fin_sans_cache(base):
    _publier_cash()
    premiere = _lire()
    stockage.liberer()
    assert _lire() == premiere
    fin = _lire({**ARGS, "decalage": 10000})["resultat"]["resultat"]
    assert fin["publications"] == [] and fin["affichage"]["decalage"] == 10000
    assert fin["affichage"]["total_publications"] == 1


@pytest.mark.parametrize("champ,valeur", [("en_deficit", 0), ("pieces", 1.0)])
def test_fait_sql_meme_valeur_python_type_json_distinct_diagnostic_divergent(base, champ, valeur):
    _publier_cash()
    with stockage.transaction() as cnx:
        row = cnx.execute(select(REGISTRES).where(REGISTRES.c.departement == "m08-analytics")).mappings().one()
        m = codec.decoder(row["maillon"])
        if champ == "en_deficit":
            m[champ] = valeur
        else:
            # Fixture canonique solde.pieces=3 : mêmevaleur numeric, type différent.
            assert m["solde"]["fraicheur"]["pieces"] == 3
            m["solde"]["fraicheur"]["pieces"] = 3.0
        cnx.execute(
            update(REGISTRES).where(REGISTRES.c.departement == "m08-analytics").values(maillon=codec.encoder(m))
        )
        avant = _snapshot(cnx)
        r = _lire()
        assert _snapshot(cnx) == avant and len(avant) == 49
    assert r["resultat"]["resultat"]["publications"][0]["rapprochement"]["etat"] == "FAITS_DIVERGENTS"


def test_vrai_bus_legacy_puis_nouveau_fait_fort_ne_bloquent_pas_courant(base):
    c = _fixture_historique("test_evenements_rentabilite_chantier.py")._m5(sequence=3, verdict="PARTIELLE")
    # Maillon historique fictif, validement représenté par la projection existante ; aucune publication inventée.
    from m8_analytics import mesures_chantier

    legacy = mesures_chantier.fait_rentabilite(c)
    for k in ("devis_id", "sequence", "version_entrees", "prix_definitif", "cout_reel_complet"):
        legacy.pop(k)
    with stockage.transaction():
        stockage.maillons("m08-analytics", "faits_chantier").append(legacy)
        evenements.publier("m5.rentabilite_chantier", "m05-financecore", c, evenement_id=c["evenement_id"])
    deps = charger_departements(Path(__file__).resolve().parents[2])
    assert (
        evenements.repartir({"m08-analytics": deps["m08-analytics"]}, maintenant="2026-09-29T18:00:00+00:00")["echecs"]
        == 0
    )
    with stockage.transaction() as cnx:
        avant = _snapshot(cnx)
        r = _lire({"perimetre": "rentabilite_wct", "wct_id": c["wct_id"], "decalage": 0, "limite": 1})
        assert _snapshot(cnx) == avant and len(avant) == 49
    dto = r["resultat"]["resultat"]
    assert dto["selection"]["publication_courante_id"] == c["evenement_id"]
    assert dto["publications"][0]["rapprochement"]["etat"] == "CORRESPONDANCE_DE_PROJECTION"
    assert dto["publications"][0]["fait"]["reference"]["rang"] == 1
