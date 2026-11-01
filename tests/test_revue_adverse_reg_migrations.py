"""Revue adverse (reg) : les migrations ne perdent ni déclencheur, ni index, ni contrainte, ni donnée.

Une reconstruction de table (`batch_alter_table`, copie-supprime-renomme) fait disparaître les déclencheurs et les
index de la table d'origine ; la technique `PRAGMA writable_schema` (0040, 0044, 0049) échoue-t-elle en silence si le
motif est introuvable ou si SQLite est en mode DEFENSIVE ? Ces tests rejouent les migrations de la 0001 à la tête, puis
un aller-retour complet AVEC DONNÉES. Aucun réseau, données fictives."""

from __future__ import annotations

import re
import sqlite3

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import event

from opsys import stockage
from opsys.stockage import moteur as moteur_de

FICTIF = True


def _aller(url: str, cible: str, sens: str = "up") -> None:
    config = stockage._config()
    with moteur_de(url).begin() as cnx:
        config.attributes["connection"] = cnx
        (command.upgrade if sens == "up" else command.downgrade)(config, cible)


def _base(tmp_path, nom: str = "opsys.db") -> tuple[str, str]:
    chemin = tmp_path / nom
    return f"sqlite:///{chemin}", str(chemin)


def _objets(chemin: str) -> dict[tuple[str, str], str]:
    cnx = sqlite3.connect(chemin)
    try:
        lignes = cnx.execute("SELECT type, name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
    finally:
        cnx.close()
    return {(t, n): re.sub(r"\s+", " ", sql or "").strip() for t, n, sql in lignes
            if not n.startswith("connaissances_fts")}


def _table_en_ensemble(sql: str) -> frozenset[str]:
    """Une table = l'ENSEMBLE de ses colonnes et contraintes (l'ordre des contraintes varie à la reconstruction)."""
    corps = sql[sql.index("(") + 1: sql.rindex(")")]
    morceaux, profondeur, courant = [], 0, ""
    for caractere in corps:
        profondeur += caractere == "("
        profondeur -= caractere == ")"
        if caractere == "," and profondeur == 0:
            morceaux.append(courant.strip())
            courant = ""
        else:
            courant += caractere
    morceaux.append(courant.strip())
    return frozenset(morceaux)


def _comparable(objets: dict) -> dict:
    return {cle: (_table_en_ensemble(sql) if cle[0] == "table" else sql) for cle, sql in objets.items()}


def test_une_seule_tete_alembic():
    scripts = ScriptDirectory.from_config(stockage._config())
    assert len(scripts.get_heads()) == 1


def test_aucune_migration_ne_perd_un_declencheur_ni_un_index(tmp_path):
    """Montée pas à pas de la 0001 à la tête : l'ensemble des déclencheurs et des index ne fait que croître, et le
    texte d'un déclencheur existant ne change jamais (une migration qui le recréerait autrement doit être explicite)."""
    url, chemin = _base(tmp_path)
    scripts = ScriptDirectory.from_config(stockage._config())
    revisions = [r.revision for r in scripts.walk_revisions()][::-1]
    precedent: dict[tuple[str, str], str] = {}
    for revision in revisions:
        _aller(url, revision)
        courant = {k: v for k, v in _objets(chemin).items() if k[0] in ("trigger", "index")}
        perdus = sorted(k for k in precedent if k not in courant)
        modifies = sorted(k for k in precedent if k in courant and k[0] == "trigger" and courant[k] != precedent[k])
        assert not perdus, f"migration {revision} : objets perdus {perdus}"
        assert not modifies, f"migration {revision} : déclencheurs modifiés en silence {modifies}"
        precedent = courant
    assert sum(1 for k in precedent if k[0] == "trigger") >= 50


def test_aller_retour_complet_avec_donnees_ne_change_ni_schema_ni_donnees(tmp_path):
    url, chemin = _base(tmp_path)
    _aller(url, "head")
    reference = _comparable(_objets(chemin))
    cnx = sqlite3.connect(chemin, isolation_level=None)
    cnx.execute("INSERT INTO registres_maillons(departement, registre, rang, maillon) VALUES ('d', 'r', 0, '{}')")
    cnx.execute("INSERT INTO journal(quand, par, action, cible, details) VALUES ('t', 'p', 'a', 'c', '{}')")
    cnx.execute("INSERT INTO usage_tokens(jour, departement, modele, appels, tokens_entree, tokens_sortie, "
                "tokens_cache_lus) VALUES ('2026-01-01', 'd', 'm', 9223372036854775807, 1, 2, 3)")
    cnx.execute("INSERT INTO evenements_sortants(evenement_id, type_evenement, producteur, charge, cree_le) "
                "VALUES ('e1', 't', 'p', '{}', 't')")
    cnx.close()
    _aller(url, "0035", "down")
    _aller(url, "head")
    assert _comparable(_objets(chemin)) == reference
    cnx = sqlite3.connect(chemin)
    try:
        assert cnx.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
        assert cnx.execute("PRAGMA foreign_key_check").fetchall() == []
        assert cnx.execute("SELECT appels FROM usage_tokens").fetchone() == (9223372036854775807,)
        assert [cnx.execute(f"SELECT count(*) FROM {t}").fetchone()[0]
                for t in ("registres_maillons", "journal", "evenements_sortants")] == [1, 1, 1]
    finally:
        cnx.close()


def test_writable_schema_en_mode_defensive_echoue_bruyamment_et_laisse_la_base_intacte(tmp_path):
    """SQLITE_DBCONFIG_DEFENSIVE interdit d'écrire `sqlite_master` : la migration par `writable_schema` doit LEVER (la
    transaction est annulée), jamais « réussir » sans avoir changé la contrainte."""
    url, chemin = _base(tmp_path)
    _aller(url, "0039")
    avant = _objets(chemin)
    stockage.liberer(url)
    moteur = moteur_de(url)
    event.listen(moteur, "connect", lambda dbapi, _enr: dbapi.setconfig(sqlite3.SQLITE_DBCONFIG_DEFENSIVE, True))
    try:
        with pytest.raises(Exception, match="sqlite_master|readonly|may not be modified"):
            _aller(url, "head")
    finally:
        stockage.liberer(url)
    assert _objets(chemin) == avant
    cnx = sqlite3.connect(chemin)
    try:
        assert cnx.execute("SELECT version_num FROM alembic_version").fetchall() == [("0039",)]
    finally:
        cnx.close()


@pytest.mark.parametrize("module,table", [
    ("0044_planificateur_connecteurs", "ingestion_brouillons"),
    ("0049_capacite_vision", "fournisseurs_configurations"),
])
def test_writable_schema_motif_introuvable_leve_au_lieu_de_passer_en_silence(tmp_path, module, table):
    """Si la CHECK attendue n'est plus dans la table (schéma déjà divergent), la migration refuse."""
    url, chemin = _base(tmp_path)
    precedent = {"0044_planificateur_connecteurs": "0041", "0049_capacite_vision": "0046"}[module]
    _aller(url, precedent)
    cnx = sqlite3.connect(chemin, isolation_level=None)
    cnx.execute("PRAGMA writable_schema = ON")
    motif = "genre IN" if table == "ingestion_brouillons" else "capacite IN"
    # même contrainte, autre mise en forme : SQL valide, mais le motif de la migration ne la retrouve plus
    cnx.execute("UPDATE sqlite_master SET sql = replace(sql, ?, ?) WHERE name = ?",
                (motif, motif.replace(" IN", "  IN"), table))
    cnx.execute(f"PRAGMA schema_version = {cnx.execute('PRAGMA schema_version').fetchone()[0] + 1}")
    cnx.execute("PRAGMA writable_schema = OFF")
    cnx.close()
    with pytest.raises(RuntimeError, match="introuvable"):
        _aller(url, module.split("_")[0])
    stockage.liberer(url)


def test_la_migration_writable_schema_est_visible_d_une_autre_connexion_ouverte(tmp_path):
    """Une connexion déjà ouverte (cache de schéma) accepte la nouvelle valeur après la migration, et la refusait
    avant : le `schema_version` est bien incrémenté."""
    url, chemin = _base(tmp_path)
    _aller(url, "0046")
    lecteur = sqlite3.connect(chemin, isolation_level=None)
    insertion = ("INSERT INTO fournisseurs_configurations(identifiant, capacite, definition, actif, revision, "
                 "modifie_le, modifie_par) VALUES (?, 'vision', '{}', 0, 1, 't', 'u')")
    with pytest.raises(sqlite3.IntegrityError):  # met aussi le schéma en cache : 'vision' n'existe pas encore
        lecteur.execute(insertion, ("avant",))
    _aller(url, "0049")
    lecteur.execute(insertion, ("apres",))  # même connexion, jamais fermée : le nouveau schéma est relu
    assert lecteur.execute("SELECT identifiant FROM fournisseurs_configurations").fetchall() == [("apres",)]
    lecteur.close()


def test_les_descentes_0049_et_0044_restaurent_les_contraintes_elargies(tmp_path):
    """La rétrogradation remet les listes fermées d'avant (et les remonte ensuite) : rien ne reste élargi en silence."""
    url, chemin = _base(tmp_path)
    _aller(url, "head")
    ddl = "SELECT sql FROM sqlite_master WHERE name = ?"
    cnx = sqlite3.connect(chemin)
    try:
        assert "'vision'" in cnx.execute(ddl, ("fournisseurs_configurations",)).fetchone()[0]
        assert "'courriel_contact'" in cnx.execute(ddl, ("ingestion_brouillons",)).fetchone()[0]
    finally:
        cnx.close()
    _aller(url, "0046", "down")
    _aller(url, "0041", "down")
    cnx = sqlite3.connect(chemin)
    try:
        assert "'vision'" not in cnx.execute(ddl, ("fournisseurs_configurations",)).fetchone()[0]
        assert "'courriel_contact'" not in cnx.execute(ddl, ("ingestion_brouillons",)).fetchone()[0]
        assert cnx.execute("PRAGMA integrity_check").fetchall() == [("ok",)]
    finally:
        cnx.close()
    _aller(url, "head")
    cnx = sqlite3.connect(chemin)
    try:
        assert "'vision'" in cnx.execute(ddl, ("fournisseurs_configurations",)).fetchone()[0]
    finally:
        cnx.close()
