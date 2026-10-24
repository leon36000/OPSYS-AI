"""Contrat public, identité et SQL fictifs ; aucune autorité Gateway revendiquée."""

import importlib.util
import inspect
from contextlib import contextmanager
from pathlib import Path

import pytest
from m8_analytics import outils
from sqlalchemy import MetaData, Table, event, insert, select, update
from sqlalchemy import inspect as inspect_sql

from opsys import contexte, evenements, identite, stockage
from opsys.departements import charger_departements
from opsys.outils import Autonomie, executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import EVENEMENTS_RECUS, EVENEMENTS_SORTANTS, REGISTRES
from opsys.stockage.schema import META as SCHEMA_META

# Schéma courant déclaré : toutes les lignes, y compris la file F4 et Alembic.
TABLES_SQLITE = set(SCHEMA_META.tables) | {"alembic_version"}

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
    # Inventaire courant déclaré, avec la table de version Alembic également observée.
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
        assert _snapshot(cnx) == avant and set(avant) == TABLES_SQLITE
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
        assert _snapshot(cnx) == avant and set(avant) == TABLES_SQLITE
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
        assert _snapshot(cnx) == avant and set(avant) == TABLES_SQLITE
    dto = r["resultat"]["resultat"]
    assert dto["selection"]["publication_courante_id"] == c["evenement_id"]
    assert dto["publications"][0]["rapprochement"]["etat"] == "CORRESPONDANCE_DE_PROJECTION"
    assert dto["publications"][0]["fait"]["reference"]["rang"] == 1


def test_budget_source_refuse_avant_transfert_driver_et_decodage(base, monkeypatch):
    """Régression : un refus tardif après .all()/decoder doit échouer."""
    _publier_cash()
    marqueur = "Q-M8-TRANSFERT-FICTIF"
    raw = codec.encoder({"fictif": True, "type_entree": marqueur})
    with stockage.transaction() as cnx:
        cnx.execute(insert(REGISTRES), [{"departement": "m08-analytics", "registre": "faits_cash_libre",
                                        "rang": i + 1, "maillon": raw} for i in range(10001)])
        avant = _snapshot(cnx)
        decodages = []
        original = codec.decoder

        def decoder(texte):
            if marqueur in texte:
                decodages.append(texte)
            return original(texte)

        monkeypatch.setattr(codec, "decoder", decoder)
        with _transferts_sql(cnx, marqueur) as transferts:
            reponse = _lire()
        assert reponse["resultat"]["verdict"]["code"] == "REJ-M8-PROVENANCE-BUDGET-SOURCE-DEPASSE"
        assert not transferts, f"{len(transferts)} payloads métier transférés avant refus"
        assert not decodages, f"{len(decodages)} décodages métier avant refus"
        assert _snapshot(cnx) == avant and set(avant) == TABLES_SQLITE


def _publication_utf8_bornee(ident, octets):
    # Budget indépendant : somme des cinq textes réellement sélectionnés de cette publication.
    typ, producteur, date = "m5.cash_libre_constate", "m05-financecore", "2026-10-13T00:00:00+00:00"
    enveloppe = sum(len(x.encode("utf-8")) for x in (ident, typ, producteur, date))
    charge = codec.encoder({"fictif": True, "texte": "é" * 30000})
    charge += " " * (octets - enveloppe - len(charge.encode("utf-8")))
    assert len(charge.encode("utf-8")) + enveloppe == octets
    return {"evenement_id": ident, "type_evenement": typ, "producteur": producteur,
            "charge": charge, "cree_le": date}


@pytest.mark.parametrize("octets,accepte", [(65536, True), (65537, False)])
def test_borne_ligne_utf8_multioctet_pas_caracteres(base, monkeypatch, octets, accepte):
    from opsys.evenements.bus import BudgetProvenanceDepasse, copier_cohorte_provenance_m5_m8

    row = _publication_utf8_bornee("Q-ligne-fictive", octets)
    with stockage.transaction() as cnx:
        cnx.execute(insert(EVENEMENTS_SORTANTS).values(**row))
        avant = _snapshot(cnx)
        original, decodages = codec.decoder, []

        def decoder(texte):
            decodages.append(texte)
            return original(texte)

        monkeypatch.setattr(codec, "decoder", decoder)
        if accepte:
            copie, faits = copier_cohorte_provenance_m5_m8(cnx, type_evenement="m5.cash_libre_constate")
            assert copie.publications[0].charge["texte"] == "é" * 30000 and faits.lignes == ()
            assert len(decodages) == 1
        else:
            with _transferts_sql(cnx, '"texte"') as transferts, pytest.raises(BudgetProvenanceDepasse):
                copier_cohorte_provenance_m5_m8(cnx, type_evenement="m5.cash_libre_constate")
            assert not transferts and not decodages
        assert _snapshot(cnx) == avant


@pytest.mark.parametrize("lignes,accepte", [(256, True), (257, False)])
def test_borne_cumul_utf8_exact_16mib_sans_decodage_si_depassee(base, monkeypatch, lignes, accepte):
    from opsys.evenements.bus import BudgetProvenanceDepasse, copier_cohorte_provenance_m5_m8

    rows = [_publication_utf8_bornee(f"Q-total-{i:08d}", 65536) for i in range(lignes)]
    with stockage.transaction() as cnx:
        cnx.execute(insert(EVENEMENTS_SORTANTS), rows)
        original, decodages = codec.decoder, []

        def decoder(texte):
            decodages.append(1)
            return original(texte)

        monkeypatch.setattr(codec, "decoder", decoder)
        if accepte:
            copie, _faits = copier_cohorte_provenance_m5_m8(cnx, type_evenement="m5.cash_libre_constate")
            assert len(copie.publications) == 256 and len(decodages) == 256
        else:
            with _transferts_sql(cnx, '"texte"') as transferts, pytest.raises(BudgetProvenanceDepasse):
                copier_cohorte_provenance_m5_m8(cnx, type_evenement="m5.cash_libre_constate")
            assert not transferts and not decodages


def test_borne_10000_cohorte_complete_et_pas_page_financiere_partielle(base):
    from opsys.evenements.bus import copier_cohorte_provenance_m5_m8

    _publier_cash()
    with stockage.transaction() as cnx:
        cnx.execute(insert(REGISTRES), [{"departement": "m08-analytics", "registre": "faits_cash_libre",
                                        "rang": i + 1, "maillon": codec.encoder({"fictif": True})}
                                       for i in range(9997)])
        copie, faits = copier_cohorte_provenance_m5_m8(cnx, type_evenement="m5.cash_libre_constate")
        assert len(copie.publications) == 1 and len(copie.recus) == 1 and len(faits.lignes) == 9998


def test_cohorte_preserve_scope_hash_raw_date_null_sans_erreur_privee(base):
    from opsys.evenements.bus import copier_cohorte_provenance_m5_m8, copier_publications_et_recus
    from opsys.stockage.maillons import copier_maillons_avec_metadonnees

    c = _publier_cash()
    with stockage.transaction() as cnx:
        cnx.execute(update(EVENEMENTS_SORTANTS).values(charge=" " + codec.encoder(c) + " "))
        cnx.execute(update(EVENEMENTS_RECUS).values(resultat=None, derniere_erreur="PRIVATE-FICTIF" * 10000))
        cnx.execute(insert(REGISTRES).values(departement="m03-estimation", registre="faits_cash_libre",
                                           rang=0, maillon="IGNORED-FICTIF" * 10000))
        cnx.execute(insert(EVENEMENTS_RECUS).values(evenement_id=c["evenement_id"], consommateur="m10-memoire",
                                                  statut="traite", tentatives=1, resultat="IGNORED-FICTIF" * 10000))
        ancien_bus = copier_publications_et_recus(cnx, type_evenement="m5.cash_libre_constate",
                                                consommateur="m08-analytics")
        anciens_faits = copier_maillons_avec_metadonnees(cnx, departement="m08-analytics",
                                                       registre="faits_cash_libre")
        avant = _snapshot(cnx)
        nouveau_bus, nouveaux_faits = copier_cohorte_provenance_m5_m8(cnx, type_evenement="m5.cash_libre_constate")
        assert nouveau_bus == ancien_bus and nouveaux_faits == anciens_faits
        assert nouveau_bus.recus[0].resultat is None
        assert _snapshot(cnx) == avant and set(avant) == TABLES_SQLITE


def test_requete_cohorte_dialectes_byte_count_et_union_datetime_null():
    from sqlalchemy.dialects import postgresql, sqlite

    from opsys.evenements.bus import _requete_cohorte_m5_m8

    for nom, dialecte, fonction in [("sqlite", sqlite.dialect(), "BLOB"),
                                    ("postgresql", postgresql.dialect(), "octet_length")]:
        sql = str(_requete_cohorte_m5_m8("m5.cash_libre_constate", nom).compile(
            dialect=dialecte, compile_kwargs={"literal_binds": True}))
        assert fonction in sql and "10001" in sql and "CASE WHEN" in sql and "UNION ALL" in sql
        assert "derniere_erreur" not in sql
        # Compilation seule : ne constitue pas une exécution PostgreSQL native.


class CurseurObserve:
    def __init__(self, curseur, marqueur, transferts):
        self.curseur = curseur
        self.marqueur = marqueur
        self.transferts = transferts

    def __getattr__(self, nom):
        return getattr(self.curseur, nom)

    def _observer(self, lignes):
        for ligne in lignes:
            if any(isinstance(x, str) and self.marqueur in x for x in ligne):
                self.transferts.append(ligne)
        return lignes

    def fetchall(self):
        return self._observer(self.curseur.fetchall())

    def fetchmany(self, *args):
        return self._observer(self.curseur.fetchmany(*args))

    def fetchone(self):
        ligne = self.curseur.fetchone()
        if ligne is not None:
            self._observer([ligne])
        return ligne


@contextmanager
def _transferts_sql(cnx, marqueur):
    transferts = []

    def observer(_cnx, curseur, _sql, _params, contexte_sql, _many):
        contexte_sql.cursor = CurseurObserve(curseur, marqueur, transferts)

    event.listen(cnx, "after_cursor_execute", observer)
    try:
        yield transferts
    finally:
        event.remove(cnx, "after_cursor_execute", observer)


@pytest.mark.parametrize("table,colonne,code", [
    (EVENEMENTS_RECUS, "tentatives", "SOURCE-INVALIDE"),
    (REGISTRES, "rang", "REGISTRE-INVALIDE"),
])
def test_metadonnees_sql_integer_corrompues_refusent_avant_transfert_et_decoder(
    base, monkeypatch, table, colonne, code,
):
    _publier_cash()
    marqueur = "Q-M8-METADONNEE-FICTIF"
    with stockage.transaction() as cnx:
        # SQLite accepte réellement TEXT dans ces INTEGER non STRICT ; aucun lecteur simulé.
        cnx.execute(update(table).values({colonne: marqueur + "x" * 100000}))
        avant = _snapshot(cnx)
        decodages, original = [], codec.decoder

        def decoder(texte):
            decodages.append(texte)
            return original(texte)

        monkeypatch.setattr(codec, "decoder", decoder)
        with _transferts_sql(cnx, marqueur) as transferts:
            reponse = _lire()
        assert not transferts, "métadonnée métier TEXT transférée depuis une colonne INTEGER"
        assert not decodages
        assert reponse["resultat"]["verdict"]["code"] == "REJ-M8-PROVENANCE-" + code
        assert _snapshot(cnx) == avant and set(avant) == TABLES_SQLITE


def test_date_sql_malformee_refuse_secure_sans_faux_code_registre(base, monkeypatch):
    _publier_cash()
    with stockage.transaction() as cnx:
        cnx.exec_driver_sql(
            "UPDATE registres_maillons SET cree_le = ? WHERE departement = ? AND registre = ?",
            ("Q-M8-DATE-MALFORMEE-FICTIVE", "m08-analytics", "faits_cash_libre"),
        )
        noms = inspect_sql(cnx).get_table_names()

        def brut():
            return {nom: tuple(cnx.exec_driver_sql('SELECT * FROM "' + nom.replace('"', '""') + '"'))
                    for nom in noms}

        avant = brut()
        decodages, original = [], codec.decoder

        def decoder(texte):
            decodages.append(texte)
            return original(texte)

        monkeypatch.setattr(codec, "decoder", decoder)
        reponse = _lire()
        assert reponse["resultat"]["verdict"]["code"] == "REJ-M8-PROVENANCE-SOURCE-INVALIDE"
        # Le processeur DateTime SQLAlchemy refuse avant les decoders métier ; payload déjà borné.
        # On ne prétend pas préserver REGISTRE-INVALIDE pour ce format SQL malformé.
        assert not decodages and "Q-M8-DATE" not in str(reponse)
        assert brut() == avant and set(noms) == TABLES_SQLITE
