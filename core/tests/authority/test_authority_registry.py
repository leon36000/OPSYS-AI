"""Tests pour core/src/opsys_core/authority (C03-002) — registre d'autorité.

Couvre les 3 cas RED obligatoires de tasks/C03-002.md :
  1. M5 finance, M6 stock, M2 CRM restent propriétaires
  2. Core ne peut pas s'enregistrer comme writer métier
  3. deux writers sur un agrégat sont rejetés

Décisions de conception tranchées par revue d'architecture AVANT code
(subagent `architecte`, Claude Opus 5 natif, 4 questions fermées,
2026-08-11 — voir docstring de registry.py pour le détail sourcé) :
table d'alias explicite (jamais un algorithme de préfixe — "M10-memoire"
.startswith("M1") == True), CORE non résolvable pour ses 6 agrégats
métier (sentinelle status=AMENDMENT_REQUIRED, jamais une supposition),
owner_of() retourne le nom LONG de module, table d'alias vérifiée contre
les deux CSV réels à chaque appel."""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from opsys_core.authority.model import (  # noqa: E402
    PREFIXE_NON_RESOLU,
    AuthorityRecord,
    StatutIncoherentAvecPort,
)
from opsys_core.authority.registry import (  # noqa: E402
    ALIAS_MODULES,
    CHEMIN_CARTE_CHEMINS,
    CHEMIN_CARTE_METIER,
    AgregatConflitProprietaire,
    AgregatInconnu,
    AliasInconnu,
    AuthorityRegistry,
    TableAliasPerimee,
    construire_registre,
)

MODULES_LONGS = {
    "M1": "M1-front-office", "M2": "M2-revenue-crm", "M3": "M3-estimation",
    "M4": "M4-field-ops", "M5": "M5-financecore", "M6": "M6-material-control",
    "M7": "M7-marketing", "M8": "M8-analytics", "M9": "M9-strategic-intelligence",
    "M10": "M10-memoire",
}

AGREGATS_CORE = {"identity", "policy", "approvals", "consent", "event routing", "tool grants"}


# ---------------------------------------------------------------------------
# construire_registre() sur les VRAIES cartes ratifiées.
# ---------------------------------------------------------------------------


def test_sources_par_defaut_existent_reellement():
    assert CHEMIN_CARTE_CHEMINS.is_file(), CHEMIN_CARTE_CHEMINS
    assert CHEMIN_CARTE_METIER.is_file(), CHEMIN_CARTE_METIER


def test_63_records_charges():
    registre = construire_registre()
    assert len(registre) == 63


def test_cas_red_1_m5_finance_m6_stock_m2_crm_restent_proprietaires():
    """Cas RED obligatoire #1 — valeurs concrètes vérifiables une à une,
    pas seulement l'algorithme de jointure."""
    registre = construire_registre()
    assert registre.owner_of("ledger") == "M5-financecore"
    assert registre.owner_of("invoices") == "M5-financecore"
    assert registre.owner_of("payments") == "M5-financecore"
    assert registre.owner_of("materials catalog") == "M6-material-control"
    assert registre.owner_of("stock movements") == "M6-material-control"
    assert registre.owner_of("reservations") == "M6-material-control"
    assert registre.owner_of("clients") == "M2-revenue-crm"
    assert registre.owner_of("leads") == "M2-revenue-crm"
    assert registre.owner_of("pipeline") == "M2-revenue-crm"


def test_owner_of_retourne_toujours_le_nom_long_jamais_le_court():
    registre = construire_registre()
    for record in registre.records():
        assert record.owner in set(MODULES_LONGS.values()) | {"CORE"}, record.owner
        assert record.owner not in MODULES_LONGS, "owner ne doit jamais être un nom court"


def test_owner_of_aggregate_inconnu_leve_agregat_inconnu():
    registre = construire_registre()
    with pytest.raises(AgregatInconnu):
        registre.owner_of("agregat_qui_nexiste_dans_aucune_carte")


def test_record_of_aggregate_inconnu_leve_agregat_inconnu():
    registre = construire_registre()
    with pytest.raises(AgregatInconnu):
        registre.record_of("agregat_qui_nexiste_dans_aucune_carte")


def test_agregats_core_ont_statut_amendment_required_et_ports_non_resolus():
    """CORE : 4 chemins de code réels (auth/authz/config/opsys_core) mais
    AUCUNE correspondance sourcée avec les 6 agrégats métier — sentinelle
    obligatoire, jamais une supposition (revue d'architecture, question 1)."""
    registre = construire_registre()
    for aggregate in AGREGATS_CORE:
        record = registre.record_of(aggregate)
        assert record.owner == "CORE"
        assert record.status == "AMENDMENT_REQUIRED"
        assert record.read_port.startswith(PREFIXE_NON_RESOLU)
        assert record.write_port.startswith(PREFIXE_NON_RESOLU)


def test_agregats_non_core_ont_statut_resolved_et_ports_reels():
    registre = construire_registre()
    for record in registre.records():
        if record.owner == "CORE":
            continue
        assert record.status == "RESOLVED", record
        assert not record.read_port.startswith(PREFIXE_NON_RESOLU)
        assert not record.write_port.startswith(PREFIXE_NON_RESOLU)
        assert record.read_port.startswith("Modules M/"), record.read_port


def test_port_resolu_correspond_au_module_reel():
    registre = construire_registre()
    record = registre.record_of("ledger")
    assert record.read_port == "Modules M/M5-financecore/src"
    assert record.write_port == "Modules M/M5-financecore/src"


def test_construction_deterministe_octet_pour_octet():
    a = construire_registre()
    b = construire_registre()
    assert [tuple(r.__dict__.items()) for r in a.records()] == [tuple(r.__dict__.items()) for r in b.records()]


def test_tous_les_agregats_core_couverts_par_ancres():
    """Les 6 agrégats CORE réels du CSV source correspondent exactement à
    la constante AGREGATS_CORE de ce fichier de test (pas de dérive
    silencieuse entre le test et la donnée réelle)."""
    registre = construire_registre()
    aggregats_reels_core = {r.aggregate for r in registre.records() if r.owner == "CORE"}
    assert aggregats_reels_core == AGREGATS_CORE


# ---------------------------------------------------------------------------
# Cas RED sur données SYNTHÉTIQUES — isolent chaque garde.
# ---------------------------------------------------------------------------


def _ecrire_carte_chemins(tmp_path: Path, lignes: list[tuple[str, str, str, str]]) -> Path:
    chemin = tmp_path / "chemins.csv"
    with chemin.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["owner", "aggregate", "read_port", "write_port"])
        writer.writerows(lignes)
    return chemin


def _ecrire_carte_metier(tmp_path: Path, lignes: list[tuple[str, str]]) -> Path:
    chemin = tmp_path / "metier.csv"
    with chemin.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["aggregate", "owner", "source_row", "source_sha256"])
        for aggregate, owner in lignes:
            writer.writerow([aggregate, owner, "1", "0" * 64])
    return chemin


def test_cas_red_3_deux_owners_differents_sur_meme_aggregate_refuse(tmp_path):
    chemins = _ecrire_carte_chemins(tmp_path, [
        ("X-module", "X-module", "Modules M/X-module/src", "Modules M/X-module/src"),
        ("Y-module", "Y-module", "Modules M/Y-module/src", "Modules M/Y-module/src"),
    ])
    metier = _ecrire_carte_metier(tmp_path, [("agregat_partage", "X"), ("agregat_partage", "Y")])
    alias = {"X": "X-module", "Y": "Y-module"}
    with pytest.raises(AgregatConflitProprietaire):
        construire_registre(chemin_carte_chemins=chemins, chemin_carte_metier=metier, alias=alias)


def test_cas_red_2_core_ne_peut_pas_usurper_un_agregat_metier(tmp_path):
    """Cas RED obligatoire #2 — CORE tentant de revendiquer un agrégat
    déjà attribué à un module M1-M10 EST une instance du conflit à deux
    propriétaires (même mécanisme que le cas RED #3, cf. docstring
    AgregatConflitProprietaire)."""
    chemins = _ecrire_carte_chemins(tmp_path, [
        ("X-module", "X-module", "Modules M/X-module/src", "Modules M/X-module/src"),
    ])
    metier = _ecrire_carte_metier(tmp_path, [("ledger_synthetique", "X"), ("ledger_synthetique", "CORE")])
    alias = {"X": "X-module", "CORE": "CORE"}
    with pytest.raises(AgregatConflitProprietaire):
        construire_registre(chemin_carte_chemins=chemins, chemin_carte_metier=metier, alias=alias)


def test_meme_owner_repete_le_meme_aggregat_nest_pas_un_conflit(tmp_path):
    chemins = _ecrire_carte_chemins(tmp_path, [
        ("X-module", "X-module", "Modules M/X-module/src", "Modules M/X-module/src"),
    ])
    metier = _ecrire_carte_metier(tmp_path, [("a", "X"), ("a", "X")])
    alias = {"X": "X-module"}
    registre = construire_registre(chemin_carte_chemins=chemins, chemin_carte_metier=metier, alias=alias)
    assert len(registre) == 2
    assert registre.owner_of("a") == "X-module"


def test_owner_court_absent_de_la_table_alias_leve_alias_inconnu(tmp_path):
    chemins = _ecrire_carte_chemins(tmp_path, [
        ("X-module", "X-module", "Modules M/X-module/src", "Modules M/X-module/src"),
    ])
    metier = _ecrire_carte_metier(tmp_path, [("a", "Z_INCONNU")])
    alias = {"X": "X-module"}
    with pytest.raises(AliasInconnu):
        construire_registre(chemin_carte_chemins=chemins, chemin_carte_metier=metier, alias=alias)


def test_alias_pointe_vers_owner_long_absent_des_chemins_leve_table_perimee(tmp_path):
    """3 entrées d'alias pour 2 owners réels (cardinalités DIFFÉRENTES,
    délibérément) — sinon cette garde et la garde symétrique
    (`owner_long_reel_non_couvert_par_alias`) se chevauchent
    mécaniquement dès que `len(alias) == len(owners_longs_reels)` : par
    le principe des tiroirs, une valeur d'alias qui ne matche aucun owner
    réel implique alors NÉCESSAIREMENT qu'un owner réel n'est couvert par
    aucune valeur — la suppression de L'UNE des deux gardes devient
    indétectable par un test à cardinalités égales (mesuré : mutation-proof
    tour 1, la garde symétrique masquait la disparition de celle-ci)."""
    chemins = _ecrire_carte_chemins(tmp_path, [
        ("X-module", "X-module", "Modules M/X-module/src", "Modules M/X-module/src"),
        ("Y-module", "Y-module", "Modules M/Y-module/src", "Modules M/Y-module/src"),
    ])
    metier = _ecrire_carte_metier(tmp_path, [("a", "X"), ("b", "Y")])
    # X et Y (les 2 owners RÉELS) restent bien couverts chacun par une
    # entrée valide — seule "Z" pointe dans le vide.
    alias = {"X": "X-module", "Y": "Y-module", "Z": "Z-module-fantome"}
    with pytest.raises(TableAliasPerimee):
        construire_registre(chemin_carte_chemins=chemins, chemin_carte_metier=metier, alias=alias)


def test_owner_long_reel_non_couvert_par_alias_leve_table_perimee(tmp_path):
    chemins = _ecrire_carte_chemins(tmp_path, [
        ("X-module", "X-module", "Modules M/X-module/src", "Modules M/X-module/src"),
        ("NOUVEAU-module", "NOUVEAU-module", "Modules M/NOUVEAU-module/src", "Modules M/NOUVEAU-module/src"),
    ])
    metier = _ecrire_carte_metier(tmp_path, [("a", "X")])
    # La table d'alias ne connaît PAS "NOUVEAU-module", pourtant présent
    # dans la carte des chemins (nouveau module jamais répercuté).
    alias = {"X": "X-module"}
    with pytest.raises(TableAliasPerimee):
        construire_registre(chemin_carte_chemins=chemins, chemin_carte_metier=metier, alias=alias)


def test_alias_core_vers_autre_chose_que_core_leve_table_perimee(tmp_path):
    """Revue scellée (2026-08-11, Kimi-K3, mineure) : sans garde
    symétrique, un alias injecté {"CORE": "M5-financecore", ...}
    passerait _verifier_table_alias silencieusement (CORE était
    entièrement exempté), résolvant les 6 agrégats métier CORE sur les
    ports RÉELS de M5 au lieu de la sentinelle documentée comme
    obligatoire. CORE doit toujours pointer vers CORE (identique dans
    les deux cartes par construction)."""
    chemins = _ecrire_carte_chemins(tmp_path, [
        ("M5-financecore", "M5-financecore", "Modules M/M5-financecore/src", "Modules M/M5-financecore/src"),
    ])
    metier = _ecrire_carte_metier(tmp_path, [("ledger", "M5"), ("identity", "CORE")])
    # Alias corrompu : CORE pointe vers M5-financecore au lieu de CORE.
    alias = {"M5": "M5-financecore", "CORE": "M5-financecore"}
    with pytest.raises(TableAliasPerimee):
        construire_registre(chemin_carte_chemins=chemins, chemin_carte_metier=metier, alias=alias)


def test_core_sans_ligne_dans_les_chemins_recoit_la_sentinelle_meme_synthetique(tmp_path):
    """CORE est la SEULE exemption de `_verifier_table_alias` (owner_court
    == "CORE" jamais vérifié contre les owners réels des chemins, cf.
    registry.py) — un owner NON-CORE dans la même situation lève
    TableAliasPerimee à la place (cas RED voisin, testé séparément
    ci-dessous) : cette exemption n'est pas un mécanisme générique, elle
    est câblée nommément sur "CORE" et doit être exercée isolément."""
    chemins = _ecrire_carte_chemins(tmp_path, [])
    metier = _ecrire_carte_metier(tmp_path, [("a", "CORE")])
    alias = {"CORE": "CORE"}
    registre = construire_registre(chemin_carte_chemins=chemins, chemin_carte_metier=metier, alias=alias)
    record = registre.record_of("a")
    assert record.status == "AMENDMENT_REQUIRED"
    assert record.read_port.startswith(PREFIXE_NON_RESOLU)


def test_owner_non_core_sans_ligne_dans_les_chemins_leve_table_perimee_pas_sentinelle(tmp_path):
    """Symétrique du test précédent : un owner NON-CORE référencé par
    l'alias mais absent de la carte des chemins n'est PAS traité comme
    "à résoudre plus tard" — c'est un signe de désynchronisation de la
    table, refusé nommément plutôt que masqué par une sentinelle."""
    chemins = _ecrire_carte_chemins(tmp_path, [])
    metier = _ecrire_carte_metier(tmp_path, [("a", "X")])
    alias = {"X": "X-module"}
    with pytest.raises(TableAliasPerimee):
        construire_registre(chemin_carte_chemins=chemins, chemin_carte_metier=metier, alias=alias)


# ---------------------------------------------------------------------------
# AuthorityRecord (model.py) — garde de cohérence status/port, indépendante
# du chargement CSV.
# ---------------------------------------------------------------------------


def test_record_resolved_avec_port_non_resolu_leve_statut_incoherent():
    with pytest.raises(StatutIncoherentAvecPort):
        AuthorityRecord(aggregate="a", owner="M1-front-office", read_port=f"{PREFIXE_NON_RESOLU} — x", write_port="Modules M/M1-front-office/src", status="RESOLVED")


def test_record_amendment_required_sans_port_non_resolu_leve_statut_incoherent():
    with pytest.raises(StatutIncoherentAvecPort):
        AuthorityRecord(aggregate="a", owner="CORE", read_port="Modules M/reel/src", write_port="Modules M/reel/src", status="AMENDMENT_REQUIRED")


def test_record_amendment_required_avec_UN_SEUL_port_non_resolu_leve_statut_incoherent():
    """Revue scellée (2026-08-11, Kimi-K3, MAJEURE, confirmée par
    reproduction directe avant correction) : un `or` (au lieu d'un `and`)
    laissait passer un record MIXTE (un port sentinelle, l'autre réel)
    sous status=AMENDMENT_REQUIRED — exposant un write_port RÉEL comme si
    le champ status documentait sa non-résolution. Les DEUX cas mixtes
    (read seul, write seul) doivent lever, pas seulement le cas où
    AUCUN port n'est résolu."""
    with pytest.raises(StatutIncoherentAvecPort):
        AuthorityRecord(
            aggregate="x", owner="CORE",
            read_port=f"{PREFIXE_NON_RESOLU} — y",
            write_port="Modules M/M5-financecore/src",
            status="AMENDMENT_REQUIRED",
        )
    with pytest.raises(StatutIncoherentAvecPort):
        AuthorityRecord(
            aggregate="x", owner="CORE",
            read_port="Modules M/M5-financecore/src",
            write_port=f"{PREFIXE_NON_RESOLU} — y",
            status="AMENDMENT_REQUIRED",
        )


def test_record_champ_texte_vide_refuse():
    with pytest.raises(ValueError):
        AuthorityRecord(aggregate="", owner="M1-front-office", read_port="Modules M/M1-front-office/src", write_port="Modules M/M1-front-office/src")


def test_record_status_hors_liste_blanche_refuse():
    with pytest.raises(ValueError):
        AuthorityRecord(aggregate="a", owner="M1-front-office", read_port="Modules M/M1-front-office/src", write_port="Modules M/M1-front-office/src", status="AUTRE")


def test_alias_modules_couvre_exactement_les_10_modules_plus_core():
    assert set(ALIAS_MODULES) == {"CORE"} | set(MODULES_LONGS)
    assert set(ALIAS_MODULES.values()) == {"CORE"} | set(MODULES_LONGS.values())
