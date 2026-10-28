"""Fictif : constats du vrai writer M6, publications M4 cataloguées, lecture SQL entière."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
import yaml
from m6_material_control import outils, reservations
from sqlalchemy import text

from opsys import contexte, identite, stockage
from opsys.outils import Autonomie, Niveau, executer_atomique
from opsys.stockage.schema import META as SCHEMA_META

# Schéma courant déclaré : toutes les lignes, y compris la file F4 et Alembic.
TABLES_SQLITE = set(SCHEMA_META.tables) | {"alembic_version"}

FICTIF = True
NOM = "m6_lire_reapprovisionnement_appareil"
ADMIN = contexte.IdentiteAppelante("admin.reappro.fictif", "admin")
MAT = "MAT-REAPPRO-FICTIF"
CH = "CH-REAPPRO-FICTIF"
WCT = "WCT-REAPPRO-FICTIF"
DATE = "2026-09-15T12:00:00+00:00"
_spec = importlib.util.spec_from_file_location(
    "stock_bas_fixture_reappro", Path(__file__).with_name("test_stock_bas_cascade.py")
)
source = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(source)


@pytest.fixture
def monde(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'fictif.db'}")
    stockage.migrer()
    (tmp_path / "fictif.db").chmod(0o600)
    monkeypatch.setattr(identite, "hacher_mot_de_passe", lambda _: "fictif-non-authentifiable")
    with stockage.transaction() as cnx:
        for p, role in [(ADMIN.personne, "admin"), ("employee.fictif", "employee"), ("seller.fictif", "seller")]:
            identite.creer_personne(cnx, p, "Personne fictive", "secret-fictif", [role])
    _config(tmp_path, monkeypatch)
    yield tmp_path, monkeypatch
    stockage.liberer()


def _config(path, mp, articles=None, raw=None):
    p = path / "configuration-fictive.yaml"
    config = {
        "configuration": {
            "reapprovisionnement": {
                "articles": articles
                if articles is not None
                else {MAT: {"seuil_reapprovisionnement": 150, "quantite_cible": 300}}
            }
        }
    }
    p.write_text(raw if raw is not None else yaml.safe_dump(config), encoding="utf-8")
    p.chmod(0o600)
    mp.setattr(outils, "_MANIFESTE", p)
    return p


def _writer(
    wct=WCT,
    mat=MAT,
    stock_initial=200,
    consommation=56,
    unite="pi",
    date=DATE,
    intervention="int-fictif",
    devis="DEVIS-STOCK-fictif",
):
    catalogue = {o.nom: o for o in outils.outils()}
    source._receptionner(catalogue, mat, stock_initial, "PO-FICTIF-" + wct, CH)
    source._publier_wct(wct, intervention, devis_id=devis, horodatage_completion=date)
    r = source._declarer(
        catalogue,
        wct,
        [source._ligne("prevu", mat, consommation, unite)],
        intervention_id=intervention,
        chantier_id=CH,
        publier=False,
    )
    assert r["accepte"] is True


def _tables():
    with stockage.transaction() as cnx:
        names = (
            cnx.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
            )
            .scalars()
            .all()
        )
        return {
            n: sorted(
                [dict(r) for r in cnx.execute(text(f'SELECT * FROM "{n}"')).mappings()],
                key=lambda r: json.dumps(r, sort_keys=True, default=str),
            )
            for n in names
        }


def _outil():
    found = [o for o in outils.outils() if o.nom == NOM]
    assert found, "nouvelle façade DEVICE réapprovisionnement absente"
    return found[0]


def _call(ident=ADMIN, **args):
    with contexte.appele_par_appareil(ident):
        return executer_atomique(_outil(), {"decalage": 0, "limite": 8, **args})


def _dto(**args):
    before = _tables()
    r = _call(**args)
    assert r["ok"] and "articles" in r["resultat"], r
    d = r["resultat"]
    assert d["taille_caracteres"] == len(json.dumps(r, ensure_ascii=False)) <= 5400
    assert before == _tables() and before["artefacts"] == [] and set(before) == TABLES_SQLITE
    return d


def test_declaration_entrees_fermees_t0_device_admin(monde):
    o = _outil()
    assert o.autonomie is Autonomie.T0 and o.niveau_effectif is Niveau.N0
    assert o.roles_appareil == frozenset({"admin"})
    assert o.parametres["additionalProperties"] is False and set(o.parametres["required"]) == {"decalage", "limite"}


def test_corpus_vide_source_quatre_registres_et_configuration(monde):
    d = _dto()
    assert d["articles"] == [] and d["pagination"]["total"] == 0
    assert [r["registre"] for r in d["sources_registres"]] == [
        "besoins_commande",
        "principal",
        "reservations",
        "emplacements",
    ]


def test_vrai_writer_derniers_constats_sans_recu_m6_legitime(monde):
    _writer()
    a = _dto()["articles"][0]
    assert a["statut"] == "stock_bas" and a["chiffres"] == {
        "stock_theorique": "144",
        "hors_main": "0",
        "en_main": "144",
        "reserve": "0",
        "disponible": "144",
    }
    assert (a["seuil_reapprovisionnement"], a["quantite_cible"], a["quantite_a_commander"]) == ("150", "300", "156")
    assert a["unite"] is None and a["unite_dernier_constat"] == "pi"
    assert a["dernier_constat"]["reference"]["rang"] == 0
    assert a["dernier_constat"]["reference_bus"] == {"type": "m4.travaux_termines", "evenement_id": WCT}
    assert a["dernier_constat"]["horodatage"] == DATE


def test_reception_egalite_seuil_et_stock_suffisant_courant(monde):
    _writer()
    source._receptionner({o.nom: o for o in outils.outils()}, MAT, 6, "PO-RETOUR-FICTIF", CH)
    a = _dto()["articles"][0]
    assert a["statut"] == "stock_suffisant" and a["chiffres"]["stock_theorique"] == "150"
    assert a["seuil_reapprovisionnement"] == "150" and a["quantite_cible"] == "300"
    assert a["quantite_a_commander"] is None and a["dernier_constat"]["horodatage"] == DATE


@pytest.mark.parametrize(
    "raw,etat,code",
    [
        ("configuration: {}", "seuil_absent", None),
        ("configuration: false", "configuration_invalide", "REJ-REAPPRO-CONFIGURATION-ILLISIBLE"),
        ("configuration: [", "configuration_invalide", "REJ-REAPPRO-CONFIGURATION-ILLISIBLE"),
        (
            "configuration:\n  reapprovisionnement:\n    articles:\n"
            "      MAT-REAPPRO-FICTIF:\n        seuil_reapprovisionnement: false\n"
            "        quantite_cible: 300",
            "configuration_invalide",
            "REJ-REAPPRO-SEUIL-INVALIDE",
        ),
    ],
)
def test_configuration_courante_absence_vs_invalide_visible(monde, raw, etat, code):
    _writer()
    _config(*monde, raw=raw)
    a = _dto()["articles"][0]
    assert a["statut"] == etat and a["code_configuration"] == code
    assert a["seuil_reapprovisionnement"] is a["quantite_cible"] is a["quantite_a_commander"] is None


def test_stock_en_main_negatif_proposition_nulle_meme_config_absente(monde):
    _writer(consommation=250)
    a = _dto()["articles"][0]
    assert a["stock_negatif"] and a["chiffres"]["en_main"] == "-50" and a["quantite_a_commander"] is None
    _config(*monde, raw="configuration: {}")
    assert _dto()["articles"][0]["stock_negatif"]


def test_reservation_change_disponible_sans_nouveau_constat(monde):
    _writer()
    with stockage.transaction():
        result, refus = reservations.reserver(
            "DEV-AUTRE-FICTIF",
            {
                "chantier_id": "CH-AUTRE-FICTIF",
                "source": "devis_accepte",
                "lignes": [{"materiau_id": MAT, "unite": "pi", "quantite_estimee": 50}],
            },
            DATE,
            "devis_accepte",
            [],
            {MAT: __import__("decimal").Decimal(144)},
        )
        assert refus is None
        stockage.maillons("m06-material-control", "reservations").append(result["fait"])
    a = _dto()["articles"][0]
    assert a["chiffres"]["reserve"] == "50" and a["chiffres"]["disponible"] == "94"
    assert a["quantite_a_commander"] == "206" and a["dernier_constat"]["reference"]["rang"] == 0


def test_ancien_recu_sans_empreinte_hors_corpus_ne_bloque_pas_le_constat_lie(monde):
    _writer()
    with stockage.transaction():
        stockage.maillons("m06-material-control", "wct_recus").append(
            {
                "wct_id": "WCT-ETRANGER-FICTIF",
                "intervention_id": "INT-ETRANGER-FICTIF",
                "devis_id": None,
                "horodatage_completion": DATE,
            }
        )
    d = _dto()
    assert d["articles"][0]["dernier_constat"]["evenement_declencheur"] == WCT
    assert d["source_publications"]["recus_m6"]["lignes"] == 1


@pytest.mark.parametrize(
    "ident",
    [
        contexte.IdentiteAppelante("employee.fictif", "employee"),
        contexte.IdentiteAppelante("seller.fictif", "seller"),
        None,
    ],
)
def test_identite_non_admin_ou_interne_refuse_avant_sources(monde, ident):
    _writer()
    r = _call(ident=ident)
    assert r["ok"] and r["resultat"]["accepte"] is False
    assert r["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"


def _refus(suffixe, **args):
    avant = _tables()
    r = _call(**args)
    assert r["ok"] and r["resultat"]["accepte"] is False, r
    assert r["resultat"]["verdict"]["code"] == "REJ-M6-REAPPRO-" + suffixe
    assert "CANARY" not in json.dumps(r) and avant == _tables()


def test_recu_lie_rang_nonzero_apres_etranger_ancienne_forme(monde):
    _writer()
    with stockage.transaction():
        stockage.maillons("m06-material-control", "wct_recus").append(
            {
                "wct_id": "WCT-ETRANGER-FICTIF",
                "intervention_id": "INT-ETRANGER-FICTIF",
                "devis_id": None,
                "horodatage_completion": DATE,
            }
        )
        outils._recevoir_travaux_termines(source._wct_charge(WCT, "int-fictif"))
    d = _dto()
    assert d["source_publications"]["recus_m6"]["lignes"] == 2
    assert d["articles"][0]["dernier_constat"]["reference_bus"]["evenement_id"] == WCT


def test_recu_lie_existant_sans_empreinte_refuse_sans_ancien_fallback(monde):
    _writer()
    with stockage.transaction():
        stockage.maillons("m06-material-control", "wct_recus").append(
            {
                "wct_id": WCT,
                "intervention_id": "int-fictif",
                "devis_id": "DEVIS-STOCK-fictif",
                "horodatage_completion": DATE,
            }
        )
    _refus("SOURCE-INVALIDE")


@pytest.mark.parametrize("dec,lim", [(-1, 8), (10001, 8), (0, 0), (0, 9), (0, True)])
def test_arguments_stricts_hors_borne_avant_sources(monde, monkeypatch, dec, lim):
    from unittest.mock import Mock

    spy = Mock(side_effect=AssertionError("lecture source avant garde"))
    monkeypatch.setattr(outils, "_sources_reapprovisionnement_appareil", spy)
    with contexte.appele_par_appareil(ADMIN), stockage.transaction():
        r = outils.lire_reapprovisionnement_appareil(dec, lim)
    assert r["verdict"]["code"] == "REJ-M6-REAPPRO-ARGUMENTS-INVALIDES"
    spy.assert_not_called()


def test_admin_revoque_avant_configuration_et_sql(monde, monkeypatch):
    from unittest.mock import Mock

    _writer()
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, ADMIN.personne, "admin")
    spies = [Mock(side_effect=AssertionError("CANARY-source")) for _ in range(2)]
    monkeypatch.setattr(outils, "_sources_reapprovisionnement_appareil", spies[0])
    monkeypatch.setattr(outils, "_configuration_reapprovisionnement_appareil", spies[1])
    r = _call()
    assert r["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    for spy in spies:
        spy.assert_not_called()


def test_dernier_par_rang_pas_date_et_article_jamais_constate_hors_corpus(monde):
    _writer()
    _writer(wct="WCT-SECOND-FICTIF", consommation=200, date="2026-09-01T12:00:00+00:00", unite="m")
    source._receptionner(
        {o.nom: o for o in outils.outils()}, "MAT-JAMAIS-CONSTATE-FICTIF", 10, "PO-ETRANGER-FICTIF", CH
    )
    a = _dto()["articles"][0]
    assert a["dernier_constat"]["reference"]["rang"] == 1
    assert a["dernier_constat"]["horodatage"] == "2026-09-01T12:00:00+00:00"
    assert a["unite"] is None and a["unite_dernier_constat"] == "m"
    assert a["chiffres"]["stock_theorique"] == "144"


def test_arrondi_decimal_evite_cancellation_des_grands_entiers(monde):
    from m6_material_control.registre import Registre

    _writer()
    with stockage.transaction():
        reg = Registre(stockage.maillons("m06-material-control", "principal"))
        for type_, q in [("RECEPTION", 10**500), ("CONSOMMATION", -(10**500)), ("RECEPTION", 1)]:
            _, refus = reg.ajouter(
                {"type_mouvement": type_, "chantier_id": CH, "materiau_id": MAT, "quantite": q, "cout_unitaire": None}
            )
            assert refus is None
    a = _dto()["articles"][0]
    assert a["chiffres"]["stock_theorique"] == "145" and a["quantite_a_commander"] == "155"


def test_seuil_entier_au_dela_js_safe_reste_texte_exact(monde):
    _writer()
    _config(*monde, articles={MAT: {"seuil_reapprovisionnement": 2**53, "quantite_cible": 2**53 + 1}})
    a = _dto()["articles"][0]
    assert a["seuil_reapprovisionnement"] == "9007199254740992"
    assert a["quantite_cible"] == "9007199254740993" and a["quantite_a_commander"] == "9007199254740849"


@pytest.mark.parametrize("quantity", [True, float("nan"), float("inf"), "-2"])
def test_quantite_source_corrompue_hash_recompose_refuse_nominal(monde, monkeypatch, quantity):
    from m6_material_control.registre import Registre

    _writer()
    origin = outils._sources_reapprovisionnement_appareil

    def corrupted():
        d = origin()
        reg = Registre()
        for r in d["registres"]["principal"]:
            m = r["maillon"]
            reg.ajouter({**m, "quantite": quantity})
        d["registres"]["principal"] = [{"rang": n, "maillon": m} for n, m in enumerate(reg.lire())]
        return d

    monkeypatch.setattr(outils, "_sources_reapprovisionnement_appareil", corrupted)
    _refus("REGISTRE-INVALIDE")


@pytest.mark.parametrize(
    "mutation,suffix",
    [
        ("rank", "REGISTRE-INVALIDE"),
        ("constatid", "REGISTRE-INVALIDE"),
        ("date", "SOURCE-INVALIDE"),
        ("producer", "SOURCE-INVALIDE"),
        ("missingpub", "LIAISON-INCOHERENTE"),
        ("chantier", "LIAISON-INCOHERENTE"),
        ("sources10001", "BORNE-SOURCES"),
    ],
)
def test_sources_corrompues_borne_et_liaisons_refusees(monde, monkeypatch, mutation, suffix):
    _writer()
    origin = outils._sources_reapprovisionnement_appareil

    def corrupted():
        d = origin()
        c = d["registres"]["besoins_commande"][0]
        if mutation == "rank":
            c["rang"] = 5
        elif mutation == "constatid":
            c["maillon"]["constat_id"] = "CANARY-invalid"
        elif mutation == "date":
            c["maillon"]["horodatage"] = "20260915T12:00:00+00:00"
        elif mutation == "producer":
            d["publications"][0]["producteur"] = "m05-financecore"
        elif mutation == "missingpub":
            d["publications"] = []
        elif mutation == "chantier":
            c["maillon"]["chantier_id"] = "CH-ETRANGER-FICTIF"
        else:
            d["registres"]["besoins_commande"] = [{}] * 10001
        return d

    monkeypatch.setattr(outils, "_sources_reapprovisionnement_appareil", corrupted)
    _refus(suffix)


def test_exception_source_et_fichier_absent_sans_raw(monde, monkeypatch):
    from unittest.mock import Mock

    _writer()
    origin = outils._sources_reapprovisionnement_appareil
    monkeypatch.setattr(outils, "_sources_reapprovisionnement_appareil", Mock(side_effect=RuntimeError("CANARY-raw")))
    _refus("REGISTRE-INVALIDE")
    monkeypatch.setattr(outils, "_sources_reapprovisionnement_appareil", origin)
    outils._MANIFESTE.unlink()
    _refus("CONFIGURATION-ILLISIBLE")


def test_reprise_exacte_toutes_tables_integrales(monde):
    _writer()
    before = _dto()
    stockage.liberer()
    assert _dto() == before


def test_pages_courantes_volume_et_remplacement(monde):
    for n in range(8):
        _writer(wct=f"WCT-PAGE-FICTIF-{n}", mat=f"MAT-PAGE-FICTIF-{n}")
    first = _dto()
    p = first["pagination"]
    assert 0 < p["affichees"] < 8 and p["total"] == 8 and p["suivant"] == p["affichees"]
    second = _dto(decalage=p["suivant"])
    assert first["articles"][0]["dernier_constat"]["reference"]["rang"] == 7
    assert second["articles"][0]["dernier_constat"]["reference"]["rang"] == 7 - p["suivant"]
    assert _dto(decalage=10000)["articles"] == []
    _writer(wct="WCT-PAGE-NEUF-FICTIF", mat="MAT-PAGE-NEUF-FICTIF")
    assert _dto(limite=1)["articles"][0]["materiau_id"] == "MAT-PAGE-NEUF-FICTIF"


def test_emplacement_hors_main_modifie_calcul_courant_sans_nouveau_constat(monde):
    _writer()
    o = next(o for o in outils.outils() if o.nom == "m6_transferer_stock")
    r = executer_atomique(
        o,
        {
            "transfert_id": "TRANSFERT-FICTIF",
            "materiau_id": MAT,
            "quantite": 30,
            "de": {"type": "inconnu"},
            "vers": {"type": "fournisseur", "reference": "FOURNISSEUR-FICTIF"},
            "motif": "Déplacement fictif",
            "horodatage": DATE,
        },
    )
    assert r["ok"] and r["resultat"]["accepte"]
    a = _dto()["articles"][0]
    assert a["chiffres"] == {
        "stock_theorique": "144",
        "hors_main": "30",
        "en_main": "114",
        "reserve": "0",
        "disponible": "114",
    }
    assert a["quantite_a_commander"] == "186" and a["dernier_constat"]["reference"]["rang"] == 0
    assert "FOURNISSEUR-FICTIF" not in json.dumps(a)


def test_grands_textes_decimaux_hors_enveloppe_refusent_sans_artefact(monde):
    from m6_material_control.registre import Registre

    _writer()
    with stockage.transaction():
        Registre(stockage.maillons("m06-material-control", "principal")).ajouter(
            {
                "type_mouvement": "RECEPTION",
                "chantier_id": CH,
                "materiau_id": MAT,
                "quantite": 10**1000,
                "cout_unitaire": None,
            }
        )
    _config(*monde, articles={MAT: {"seuil_reapprovisionnement": 10**1001, "quantite_cible": 10**1002}})
    _refus("SORTIE-TROP-VOLUMINEUSE")
    assert _tables()["artefacts"] == []


def test_identifiants_256_et_unicode_feff_verbatim(monde):
    ident = "WCT-" + "X" * 252
    _writer(wct=ident, mat="\ufeff")
    a = _dto()["articles"][0]
    assert a["materiau_id"] == "\ufeff" and a["dernier_constat"]["reference_bus"]["evenement_id"] == ident


@pytest.mark.parametrize("valeur", ["NaN", "Infinity", "-1", False])
def test_quantite_reservation_corrompue_refuse_sans_partiel(monde, monkeypatch, valeur):
    _writer()
    original = outils._sources_reapprovisionnement_appareil

    def corrupted():
        d = original()
        r, refus = reservations.reserver(
            "DEV-FICTIF",
            {"chantier_id": CH, "lignes": [{"materiau_id": MAT, "unite": "pi", "quantite_estimee": 10}]},
            DATE,
            "devis_accepte",
            [],
            {MAT: __import__("decimal").Decimal(144)},
        )
        assert refus is None
        r["fait"]["lignes"][0]["quantite_reservee"] = valeur
        d["registres"]["reservations"] = [{"rang": 0, "maillon": r["fait"]}]
        return d

    monkeypatch.setattr(outils, "_sources_reapprovisionnement_appareil", corrupted)
    _refus("REGISTRE-INVALIDE")


def test_metadata_transfert_non_projetees_restent_au_schema_writer_legacy(monde):
    _writer()
    o = next(o for o in outils.outils() if o.nom == "m6_transferer_stock")
    r = executer_atomique(
        o,
        {
            "transfert_id": "TRANSFERT-LEGACY-FICTIF",
            "materiau_id": MAT,
            "quantite": 30,
            "de": {"type": "inconnu"},
            "vers": {"type": "fournisseur", "reference": "FOURNISSEUR-FICTIF"},
            "motif": "Note humaine fictive\n" + "X" * 2001,
            "horodatage": "date-legacy-fictive",
        },
    )
    assert r["ok"] and r["resultat"]["accepte"]
    a = _dto()["articles"][0]
    assert a["chiffres"]["hors_main"] == "30"
    assert a["dernier_constat"]["horodatage"] == DATE


@pytest.mark.parametrize("transfer_id", ["TRANSFERT-FICTIF-NORMAL", "T" * 257, "TRANSFERT-FICTIF\nSUITE"])
def test_identifiant_transfert_non_projete_suit_schema_writer(monde, transfer_id):
    _writer()
    o = next(o for o in outils.outils() if o.nom == "m6_transferer_stock")
    r = executer_atomique(
        o,
        {
            "transfert_id": transfer_id,
            "materiau_id": MAT,
            "quantite": 30,
            "de": {"type": "inconnu"},
            "vers": {"type": "fournisseur", "reference": "FOURNISSEUR-FICTIF"},
            "motif": "Déplacement fictif",
            "horodatage": DATE,
        },
    )
    assert r["ok"] and r["resultat"]["accepte"]
    d = _dto()
    assert d["articles"][0]["chiffres"]["hors_main"] == "30"
    assert "transfert_id" not in json.dumps(d) and transfer_id not in json.dumps(d)


@pytest.mark.parametrize("metadata", ["M" * 257, "METADATA-FICTIVE\nSUITE"])
def test_liaisons_recu_devis_intervention_non_projetees_suivent_writer(monde, metadata):
    from opsys import evenements

    _writer(intervention=metadata, devis=metadata)
    with stockage.transaction():
        charge = evenements.charge_publiee("m4.travaux_termines", WCT)
        assert charge["intervention_id"] == charge["devis_id"] == metadata
        outils._recevoir_travaux_termines(charge)
    d = _dto()
    assert d["articles"][0]["dernier_constat"]["reference_bus"]["evenement_id"] == WCT
    assert metadata not in json.dumps(d)


@pytest.mark.parametrize("metadata", ["M" * 257, "METADATA-FICTIVE\nSUITE"])
def test_ids_reservation_non_projetes_suivent_vrais_outils_et_cloture(monde, metadata):
    _writer()
    tools = {o.nom: o for o in outils.outils()}
    r = executer_atomique(
        tools["m6_enregistrer_besoins_prevus"],
        {
            "chantier_id": metadata,
            "devis_id": metadata,
            "lignes": [{"materiau_id": MAT, "unite": metadata, "quantite_estimee": 20}],
        },
    )
    assert r["ok"] and r["resultat"]["accepte"]
    r = executer_atomique(tools["m6_reserver_materiel"], {"devis_id": metadata, "horodatage": DATE})
    assert r["ok"] and r["resultat"]["accepte"]
    d = _dto()
    assert d["articles"][0]["chiffres"]["reserve"] == "20" and metadata not in json.dumps(d)
    with stockage.transaction():
        reg = stockage.maillons("m06-material-control", "reservations")
        fact = reservations.cloturer(metadata, metadata, DATE, reg)
        assert fact is not None
        reg.append(fact)
    d = _dto()
    assert d["articles"][0]["chiffres"]["reserve"] == "0" and metadata not in json.dumps(d)


def test_wct_id_public_superieur_256_ne_devient_pas_metadonnee_tolerante(monde):
    _writer(wct="W" * 257)
    _refus("REGISTRE-INVALIDE")
