"""Fictif : vrai WCT du producteur M4, SQLite et lecture DEVICE sans écriture."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from m4_field_ops import etats, pointage
from m4_field_ops import outils as outils_m4
from m4_field_ops import registre as registre_m4
from m6_material_control import outils
from sqlalchemy import text

from opsys import contexte, fichiers, identite, stockage
from opsys.outils import Autonomie, Niveau, executer_atomique

FICTIF = True
NOM = "m6_lire_contexte_materiaux_appareil"
EMP = contexte.IdentiteAppelante("terrain.fictif", "employee")
ADMIN = contexte.IdentiteAppelante("admin.contexte.fictif", "admin")
CH = "CH-M3-FICTIF"
MAT = "MAT-CONTEXTE-FICTIF"
DEVI = "DEVIS-CONTEXTE-FICTIF"
DATE = "2025-06-02T11:35:00+00:00"
p = Path(__file__).resolve().parents[2] / "m04-field-ops/tests/test_outbox.py"
spec = importlib.util.spec_from_file_location("fixture_m4_contexte", p)
m4fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m4fixture)


@pytest.fixture
def monde(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'fictif.db'}")
    stockage.migrer()
    (tmp_path / "fictif.db").chmod(0o600)
    monkeypatch.setattr(identite, "hacher_mot_de_passe", lambda _: "fictif-non-authentifiable")
    with stockage.transaction() as cnx:
        for p, role in [
            (EMP.personne, "employee"),
            (ADMIN.personne, "admin"),
            ("autre.fictif", "employee"),
            ("vendeur.fictif", "seller"),
        ]:
            identite.creer_personne(cnx, p, "Personne FICTIVE", "secret-fictif", [role])
    yield tmp_path, monkeypatch
    stockage.liberer()


def _seed(devis=None):
    reg = registre_m4.Registre()
    contract = dict(m4fixture.CONTRAT_VALIDE, lead_id="LEAD-CONTEXTE-FICTIF")
    marker = dict(m4fixture.MARQUEUR_VALIDE, lead_id=contract["lead_id"])
    args = {"devis_id": devis} if devis is not None else {}
    a, v = etats.inscrire_intervention(contract, marker, reg, m4fixture.H1, m4fixture.SEL, **args)
    assert a is not None, v
    i = a["intervention_id"]
    ass = {"intervention_id": i, "technicien_id": EMP.personne}
    a, v = etats.transitionner(i, "en_route", reg, m4fixture.H_ARRIVEE, assignation=ass)
    assert a is not None, v
    for action, date in [("arrivee", m4fixture.H_ARRIVEE), ("depart", m4fixture.H_DEPART)]:
        a, v = pointage.enregistrer_pointage(
            i,
            EMP.personne,
            action,
            date,
            m4fixture.GPS_PROCHE,
            m4fixture.ATTESTATION,
            ass,
            m4fixture.FENETRE,
            m4fixture.REFERENTIEL,
            m4fixture.VILLE,
            m4fixture.SEL,
            reg,
        )
        assert a is not None, v
    with stockage.transaction() as cnx:
        stockage.maillons("m04-field-ops", "principal").extend(reg.lire())
        import base64
        import hashlib

        blob = b"\x89PNG\r\n\x1a\nFICTIF-contexte"
        h = hashlib.sha256(blob).hexdigest()
        f = fichiers.deposer_bloc(cnx, h, len(blob), "image/png", 0, 1, base64.b64encode(blob).decode())
        assert f.accepte
    tool = next(o for o in outils_m4.outils() if o.nom == "m4_completer_intervention")
    r = executer_atomique(
        tool,
        {
            "intervention_id": i,
            "horodatage": DATE,
            "preuves_completion": {
                "checklist_complete": True,
                "photos_apres": [fichiers.reference_pour(h)],
                "notes": "Fictif",
                "signature": None,
            },
        },
    )
    assert r["ok"] and r["resultat"]["accepte"], r
    return i, r["resultat"]["resultat"]["wct_id"]


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
                [dict(x) for x in cnx.execute(text(f'SELECT * FROM "{n}"')).mappings()],
                key=lambda x: json.dumps(x, sort_keys=True, default=str),
            )
            for n in names
        }


def _call(i, w, actor=EMP, **args):
    tool = next((o for o in outils.outils() if o.nom == NOM), None)
    assert tool is not None, "nouvelle lecture contexte absente"
    before = _tables()
    with contexte.appele_par_appareil(actor):
        r = executer_atomique(tool, {"intervention_id": i, "wct_id": w, "decalage": 0, "limite": 8, **args})
    assert before == _tables() and len(before) == 49 and before["artefacts"] == []
    return r


def _dto(i, w, **args):
    r = _call(i, w, **args)
    assert r["ok"] and "wct" in r["resultat"], r
    d = r["resultat"]
    assert d["taille_caracteres"] == len(json.dumps(r, ensure_ascii=False)) <= 5400
    return d


def _prevu(chantier=CH, lignes=None):
    tool = next(o for o in outils.outils() if o.nom == "m6_enregistrer_besoins_prevus")
    r = executer_atomique(
        tool,
        {
            "chantier_id": chantier,
            "devis_id": DEVI,
            "lignes": lignes if lignes is not None else [{"materiau_id": MAT, "quantite_estimee": 40, "unite": "pi"}],
        },
    )
    assert r["ok"] and r["resultat"]["accepte"], r


def test_declaration_fermee_device_t0(monde):
    tool = next((o for o in outils.outils() if o.nom == NOM), None)
    assert tool is not None, "nouvelle lecture contexte absente"
    assert (
        tool.autonomie is Autonomie.T0
        and tool.niveau_effectif is Niveau.N0
        and tool.roles_appareil == frozenset({"employee", "admin"})
    )
    assert (
        set(tool.parametres["required"]) == {"intervention_id", "wct_id", "decalage", "limite"}
        and not tool.parametres["additionalProperties"]
    )


def test_wct_reel_sans_devis_prevu_absent_et_repli_employee(monde):
    i, w = _seed()
    d = _dto(i, w)
    assert d["wct"]["wct_id"] == w and d["wct"]["intervention_id"] == i
    assert d["prevu"] == {"statut": "absent", "source": None} and d["chantier"] == {
        "chantier_id": i,
        "origine": "intervention_employee",
    }
    assert not d["lignes"] and d["pagination"]["total"] == 0
    assert d["manques"] == ["devis_absent", "prevu_absent"]


def test_chantier_source_distinct_et_lignes_uniquement_estimees(monde):
    i, w = _seed(DEVI)
    _prevu()
    d = _dto(i, w)
    assert d["chantier"] == {"chantier_id": CH, "origine": "prevu_m6"} and i != CH
    assert d["lignes"] == [
        {
            "position_source": 0,
            "materiau_id": MAT,
            "unite": "pi",
            "quantite_estimee": "40",
            "origine_quantite": "nombre_m6_persiste",
        }
    ]
    assert d["prevu"]["source"]["rang"] == 0 and d["prevu"]["source"]["horodatage"] is None
    assert "quantite_reelle" not in d["lignes"][0] and "prix" not in json.dumps(d)


def _refus(i, w, suffix, **args):
    r = _call(i, w, **args)
    assert r["ok"] and r["resultat"]["accepte"] is False
    assert r["resultat"]["verdict"]["code"] == "REJ-M6-CONTEXTE-" + suffix
    assert "CANARY" not in json.dumps(r)
    return r


@pytest.mark.parametrize(
    "actor",
    [
        None,
        contexte.IdentiteAppelante("vendeur.fictif", "seller"),
        contexte.IdentiteAppelante("inconnu.fictif", "admin"),
        contexte.IdentiteAppelante(EMP.personne, "admin"),
    ],
)
def test_role_identite_avant_toutes_sources(monde, monkeypatch, actor):
    from unittest.mock import Mock

    i, w = _seed()
    ad = Mock(side_effect=RuntimeError("CANARY-auth-source"))
    so = Mock(side_effect=RuntimeError("CANARY-business-source"))
    monkeypatch.setattr(outils, "_admission_m4_contexte", ad)
    monkeypatch.setattr(outils, "_sources_m6_contexte", so)
    _refus(i, w, "IDENTITE-INVALIDE", actor=actor)
    assert not ad.called and not so.called


def test_admin_role_retire_avant_admission_et_sources(monde, monkeypatch):
    from unittest.mock import Mock

    i, w = _seed()
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, ADMIN.personne, "admin")
    ad = Mock()
    so = Mock()
    monkeypatch.setattr(outils, "_admission_m4_contexte", ad)
    monkeypatch.setattr(outils, "_sources_m6_contexte", so)
    _refus(i, w, "IDENTITE-INVALIDE", actor=ADMIN)
    assert not ad.called and not so.called


@pytest.mark.parametrize("i_inconnu", [False, True])
def test_admission_employee_avant_bus_m6(monde, monkeypatch, i_inconnu):
    from unittest.mock import Mock

    i, w = _seed()
    so = Mock()
    monkeypatch.setattr(outils, "_sources_m6_contexte", so)
    _refus(
        "INTERVENTION-INCONNUE-FICTIVE" if i_inconnu else i,
        w,
        "INTERVENTION-NON-ASSIGNEE",
        actor=contexte.IdentiteAppelante("autre.fictif", "employee"),
    )
    assert not so.called


def test_wct_inconnu_avant_lecture_prevu_m6(monde, monkeypatch):
    from unittest.mock import Mock

    i, _ = _seed()
    so = Mock(wraps=outils._sources_m6_contexte)
    monkeypatch.setattr(outils, "_sources_m6_contexte", so)
    _refus(i, "WCT-INCONNU-FICTIF", "WCT-INCONNU")
    assert not so.called


@pytest.mark.parametrize(
    "params",
    [
        {"limite": 9},
        {"decalage": -1},
        {"decalage": True},
        {"wct_id": None},
        {"intervention_id": "\n"},
        {"intervention_id": "X" * 257},
    ],
)
def test_arguments_invalides_avant_sources(monde, monkeypatch, params):
    from unittest.mock import Mock

    i, w = _seed()
    ad = Mock()
    monkeypatch.setattr(outils, "_admission_m4_contexte", ad)
    # Avoid duplicate positional keyword in helper.
    req = {"intervention_id": i, "wct_id": w, "decalage": 0, "limite": 8, **params}
    tool = next(o for o in outils.outils() if o.nom == NOM)
    before = _tables()
    with contexte.appele_par_appareil(EMP):
        r = executer_atomique(tool, req)
    if not r["ok"]:
        assert r["erreur"] == "arguments_invalides"
    else:
        assert r["resultat"]["verdict"]["code"] == "REJ-M6-CONTEXTE-ARGUMENTS-INVALIDES"
    with stockage.transaction(), contexte.appele_par_appareil(EMP):
        direct = outils.lire_contexte_materiaux_appareil(**req)
    assert direct["verdict"]["code"] == "REJ-M6-CONTEXTE-ARGUMENTS-INVALIDES" and not ad.called and _tables() == before


def test_prevu_vide_connu_admin_null_et_employee_repli(monde):
    i, w = _seed(DEVI)
    _devis_accepte(chantier=None, avec_materiau=False)
    d = _dto(i, w)
    assert (
        d["prevu"]["statut"] == "definitif"
        and d["prevu"]["source"] is not None
        and not d["lignes"]
        and "prevu_absent" not in d["manques"]
    )
    assert d["chantier"] == {"chantier_id": i, "origine": "intervention_employee"}
    d = _dto(i, w, actor=ADMIN)
    assert (
        d["chantier"] == {"chantier_id": None, "origine": "absent_admin"} and "chantier_source_absent" in d["manques"]
    )


def test_copies_source_corrompue_et_quota_refusent_sans_raw(monde, monkeypatch):
    i, w = _seed(DEVI)
    _prevu()
    origin = outils._sources_m6_contexte

    def bad(*a):
        d = origin(*a)
        d["prevus"][0]["maillon"]["lignes"][0]["quantite_estimee"] = float("nan")
        return d

    monkeypatch.setattr(outils, "_sources_m6_contexte", bad)
    _refus(i, w, "SOURCE-INVALIDE")

    def too_many(*a):
        d = origin(*a)
        d["prevus"] = [{}] * 10001
        return d

    monkeypatch.setattr(outils, "_sources_m6_contexte", too_many)
    _refus(i, w, "BORNE-SOURCES")


def test_exception_de_copie_est_nominale_sans_message(monde, monkeypatch):
    from unittest.mock import Mock

    i, w = _seed()
    monkeypatch.setattr(outils, "_sources_m6_contexte", Mock(side_effect=RuntimeError("CANARY-copy")))
    _refus(i, w, "SOURCE-INVALIDE")


def test_pages_courantes_ordonnees_et_reprise_exacte(monde):
    i, w = _seed(DEVI)
    _prevu(lignes=[{"materiau_id": f"MAT-FICTIF-{n}", "quantite_estimee": n + 1, "unite": "pi"} for n in range(10)])
    d = _dto(i, w, limite=2)
    assert [x["position_source"] for x in d["lignes"]] == [0, 1] and d["pagination"]["suivant"] == 2
    e = _dto(i, w, decalage=2, limite=2)
    assert [x["position_source"] for x in e["lignes"]] == [2, 3]
    assert _dto(i, w, decalage=10000)["lignes"] == []
    stockage.liberer()
    assert _dto(i, w, limite=2) == d


def _devis_accepte(chantier=CH, avec_materiau=True, quantite="40"):
    from opsys import evenements

    charge = {
        "devis_id": DEVI,
        "lead_id": "LEAD-CONTEXTE-FICTIF",
        "chantier_id": chantier,
        "lignes": [
            {
                "reference_ligne": "LIGNE-FICTIVE",
                "description": "Matériau FICTIF",
                "quantite": quantite,
                "unite": "pi",
                "prix_unitaire": "25.00",
                "prix_ligne": "1000.00",
                "reference_besoin_materiau": MAT if avec_materiau else None,
            }
        ],
        "cout_total": "777.77",
        "prix_total": "1000.00",
        "taux_marge": "0.25",
        "horodatage_acceptation": "2025-06-01T08:00:00+00:00",
    }
    with stockage.transaction():
        evenements.publier("m3.devis_accepte", "m03-estimation", charge, evenement_id="M3-DEVIS-CONTEXTE-FICTIF")
        outils._recevoir_devis_accepte(charge)
    return charge


def test_m3_devis_accepte_reel_recepteur_projection_sans_prix(monde):
    i, w = _seed(DEVI)
    _devis_accepte(quantite="040.00")
    d = _dto(i, w)
    assert d["lignes"][0]["quantite_estimee"] == "040.00" and d["lignes"][0]["origine_quantite"] == "texte_m3_verifie"
    assert (
        d["prevu"]["source"]["reference_m3"] == {"type": "m3.devis_accepte", "evenement_id": "M3-DEVIS-CONTEXTE-FICTIF"}
        and d["prevu"]["source"]["horodatage"] == "2025-06-01T08:00:00+00:00"
    )
    assert "777.77" not in json.dumps(d) and "prix" not in json.dumps(d)


def _estimation_m3(rang=0, quantite="040.00"):
    from opsys import evenements

    charge = {
        "devis_id": DEVI,
        "lead_id": "LEAD-CONTEXTE-FICTIF",
        "estimation_id": str(rang + 1) * 64,
        "rang_registre": rang,
        "bareme_version": "BAREME-FICTIF",
        "niveau_confiance": 0.95,
        "lignes": [{"materiau": "Gouttière FICTIVE", "sku": MAT, "quantite_estimee": quantite, "unite": "pi"}],
        "facteurs_perte_absents": ["Gouttière FICTIVE"],
    }
    with stockage.transaction():
        evenements.publier(
            "m3.besoins_materiaux", "m03-estimation", charge, evenement_id=f"M3-BESOINS-CONTEXTE-FICTIF-{rang}"
        )
        outils._recevoir_besoins_materiaux(charge)
    return charge


def test_provisoire_m3_texte_original_et_meta_date_absente(monde):
    i, w = _seed(DEVI)
    _estimation_m3()
    d = _dto(i, w)
    assert (
        d["prevu"]["statut"] == "provisoire_estimation_m3"
        and d["prevu"]["source"]["estimation_id"] == "1" * 64
        and d["prevu"]["source"]["rang_m3"] == 0
    )
    assert (
        d["prevu"]["source"]["horodatage"] is None
        and d["lignes"][0]["quantite_estimee"] == "040.00"
        and d["lignes"][0]["origine_quantite"] == "texte_m3_verifie"
    )
    assert d["chantier"]["origine"] == "intervention_employee" and d["manques"] == ["horodatage_prevu_absent"]


def test_definitif_prioritaire_et_rang_reel_apres_provisoires(monde):
    i, w = _seed(DEVI)
    _estimation_m3()
    _estimation_m3(1, quantite="41")
    _prevu()
    d = _dto(i, w)
    assert (
        d["prevu"]["statut"] == "definitif"
        and d["prevu"]["source"]["rang"] == 2
        and d["prevu"]["source"]["estimation_id"] is None
    )
    assert d["lignes"][0]["quantite_estimee"] == "40" and d["lignes"][0]["origine_quantite"] == "nombre_m6_persiste"


def test_provisoire_dernier_rang_m3_sans_tri_par_date(monde):
    i, w = _seed(DEVI)
    _estimation_m3()
    _estimation_m3(1, quantite="42")
    d = _dto(i, w)
    assert (
        d["prevu"]["source"]["rang"] == 1
        and d["prevu"]["source"]["rang_m3"] == 1
        and d["lignes"][0]["quantite_estimee"] == "42"
    )


@pytest.mark.parametrize("corruption", ["producer", "hash", "technicien", "intervention"])
def test_wct_altere_refuse_avant_prevu(monde, monkeypatch, corruption):
    from unittest.mock import Mock

    from sqlalchemy import select, update

    from opsys.stockage import codec
    from opsys.stockage.schema import EVENEMENTS_SORTANTS

    i, w = _seed()
    with stockage.transaction() as cnx:
        row = cnx.execute(select(EVENEMENTS_SORTANTS).where(EVENEMENTS_SORTANTS.c.evenement_id == w)).one()
        charge = codec.decoder(row.charge)
        if corruption == "producer":
            cnx.execute(
                update(EVENEMENTS_SORTANTS)
                .where(EVENEMENTS_SORTANTS.c.evenement_id == w)
                .values(producteur="m05-financecore")
            )
        else:
            charge[
                {"hash": "hash_maillon", "technicien": "technicien_id", "intervention": "intervention_id"}[corruption]
            ] = "0" * 64 if corruption == "hash" else "AUTRE-FICTIF"
            cnx.execute(
                update(EVENEMENTS_SORTANTS)
                .where(EVENEMENTS_SORTANTS.c.evenement_id == w)
                .values(charge=codec.encoder(charge))
            )
    so = Mock()
    monkeypatch.setattr(outils, "_sources_m6_contexte", so)
    _refus(i, w, "SOURCE-INVALIDE" if corruption == "producer" else "LIAISON-INCOHERENTE")
    assert not so.called


def test_source_liee_m3_divergente_refuse_pas_fallback(monde, monkeypatch):
    i, w = _seed(DEVI)
    _devis_accepte()
    origin = outils._sources_m6_contexte

    def bad(*a):
        d = origin(*a)
        d["m3"][0]["charge"]["lignes"][0]["quantite"] = "41"
        return d

    monkeypatch.setattr(outils, "_sources_m6_contexte", bad)
    _refus(i, w, "LIAISON-INCOHERENTE")


def test_metadonnees_provisoire_corrompues_refusent_meme_sans_pub(monde, monkeypatch):
    i, w = _seed(DEVI)
    _estimation_m3()
    origin = outils._sources_m6_contexte

    def bad(*a):
        d = origin(*a)
        d["m3"] = []
        d["prevus"][0]["maillon"]["niveau_confiance"] = float("nan")
        return d

    monkeypatch.setattr(outils, "_sources_m6_contexte", bad)
    _refus(i, w, "SOURCE-INVALIDE")


def test_id_et_unite_feff_sont_verbatim(monde):
    i, w = _seed(DEVI)
    _prevu(lignes=[{"materiau_id": "\ufeff", "quantite_estimee": 1, "unite": "\ufeff"}])
    d = _dto(i, w)
    assert d["lignes"][0]["materiau_id"] == "\ufeff" and d["lignes"][0]["unite"] == "\ufeff"


def test_page_reduite_entiere5400_sans_troncature(monde):
    i, w = _seed(DEVI)
    _prevu(lignes=[{"materiau_id": f"{n}" + ("X" * 255), "quantite_estimee": 1, "unite": "U" * 256} for n in range(8)])
    d = _dto(i, w)
    assert (
        0 < d["pagination"]["affichees"] < 8
        and d["pagination"]["total"] == 8
        and d["pagination"]["suivant"] == d["pagination"]["affichees"]
    )
    e = _dto(i, w, decalage=d["pagination"]["suivant"])
    assert e["lignes"][0]["position_source"] == d["pagination"]["suivant"]


def test_premiere_ligne_hors5400_refuse_sans_artefact(monde):
    i, w = _seed(DEVI)
    _prevu(lignes=[{"materiau_id": MAT, "quantite_estimee": 10**4200, "unite": "pi"}])
    _refus(i, w, "SORTIE-TROP-VOLUMINEUSE")


@pytest.mark.parametrize(
    "champ,valeur",
    [
        ("niveau_confiance", True),
        ("niveau_confiance", 1.0),
        ("lead_id", None),
        ("facteurs_perte_absents", []),
        ("chantier_id", "CHANTIER-INVENTE-FICTIF"),
    ],
)
def test_provisoire_metadata_completes_validees_sans_publication(monde, monkeypatch, champ, valeur):
    i, w = _seed(DEVI)
    _estimation_m3()
    origin = outils._sources_m6_contexte

    def bad(*a):
        d = origin(*a)
        d["m3"] = []
        d["prevus"][0]["maillon"][champ] = valeur
        return d

    monkeypatch.setattr(outils, "_sources_m6_contexte", bad)
    _refus(i, w, "SOURCE-INVALIDE")


def test_provisoire_detail_quantite_divergente_sans_publication(monde, monkeypatch):
    i, w = _seed(DEVI)
    _estimation_m3()
    origin = outils._sources_m6_contexte

    def bad(*a):
        d = origin(*a)
        d["m3"] = []
        d["prevus"][0]["maillon"]["detail_lignes"][0]["quantite_estimee"] = "41"
        return d

    monkeypatch.setattr(outils, "_sources_m6_contexte", bad)
    _refus(i, w, "SOURCE-INVALIDE")


@pytest.mark.parametrize("actif", [False])
def test_personne_inactive_avant_admission(monde, monkeypatch, actif):
    from unittest.mock import Mock

    i, w = _seed()
    with stockage.transaction() as cnx:
        identite.activer(cnx, EMP.personne, actif)
    ad = Mock()
    monkeypatch.setattr(outils, "_admission_m4_contexte", ad)
    _refus(i, w, "IDENTITE-INVALIDE")
    assert not ad.called


def test_admission_employee_ne_lit_pas_bus_avant_assignation(monde, monkeypatch):
    from unittest.mock import Mock

    i, w = _seed()
    bus = Mock()
    sources = Mock()
    monkeypatch.setattr(outils, "_wct_m4_contexte", bus)
    monkeypatch.setattr(outils, "_sources_m6_contexte", sources)
    _refus(i, w, "INTERVENTION-NON-ASSIGNEE", actor=contexte.IdentiteAppelante("autre.fictif", "employee"))
    assert not bus.called and not sources.called


@pytest.mark.parametrize("champ", ["agent_id", "auteur", "device_id", "chantier_id", "technicien_id"])
def test_arguments_etrangers_schema_ferme(monde, monkeypatch, champ):
    from unittest.mock import Mock

    i, w = _seed()
    ad = Mock()
    monkeypatch.setattr(outils, "_admission_m4_contexte", ad)
    r = _call(i, w, **{champ: "FORGE-FICTIF"})
    assert r == {"ok": False, "erreur": "arguments_invalides", "details": r["details"]} and not ad.called


def test_borne_lignes_du_prevu10001_refuse(monde, monkeypatch):
    i, w = _seed(DEVI)
    _prevu()
    origin = outils._sources_m6_contexte

    def too_many(*a):
        d = origin(*a)
        d["prevus"][0]["maillon"]["lignes"] = [
            {"materiau_id": str(n), "quantite_estimee": 1, "unite": "pi"} for n in range(10001)
        ]
        return d

    monkeypatch.setattr(outils, "_sources_m6_contexte", too_many)
    _refus(i, w, "BORNE-SOURCES")


def test_borne_copies10000_exacte_admise10001_refuse(monde, monkeypatch):
    i, w = _seed(DEVI)
    _prevu()
    origin = outils._sources_m6_contexte

    def at_bound(*a):
        d = origin(*a)
        n = 10000 - len(d["m3"]) - d["admission_lignes"] - 1
        d["prevus"] += [{"rang": j, "maillon": {"devis_id": "AUTRE-FICTIF"}} for j in range(1, n)]
        return d

    monkeypatch.setattr(outils, "_sources_m6_contexte", at_bound)
    assert _dto(i, w)["pagination"]["total"] == 1

    def over(*a):
        d = at_bound(*a)
        d["prevus"].append({})
        return d

    monkeypatch.setattr(outils, "_sources_m6_contexte", over)
    _refus(i, w, "BORNE-SOURCES")


def test_quantite_texte_grande_pas_limite_json_number(monde):
    i, w = _seed(DEVI)
    _prevu(lignes=[{"materiau_id": MAT, "quantite_estimee": 2**100, "unite": "pi"}])
    d = _dto(i, w)
    assert (
        d["lignes"][0]["quantite_estimee"] == str(2**100) and d["lignes"][0]["origine_quantite"] == "nombre_m6_persiste"
    )


def test_page_courante_remplace_version_sans_snapshot_fige(monde):
    i, w = _seed(DEVI)
    _estimation_m3()
    d = _dto(i, w)
    _estimation_m3(1, "42")
    e = _dto(i, w)
    assert (
        d["lignes"][0]["quantite_estimee"] == "040.00"
        and e["lignes"][0]["quantite_estimee"] == "42"
        and e["prevu"]["source"]["rang"] == 1
    )


@pytest.mark.parametrize(
    "date",
    ["20250601T08:00:00+00:00", "2025-W22-7T08:00:00+00:00", "2025-06-01T08:00+00:00", "2025-02-30T08:00:00+00:00"],
)
def test_date_source_incompatible_refuse_nominalement(monde, monkeypatch, date):
    i, w = _seed(DEVI)
    _devis_accepte()
    origin = outils._sources_m6_contexte

    def bad(*a):
        d = origin(*a)
        d["m3"][0]["charge"]["horodatage_acceptation"] = date
        return d

    monkeypatch.setattr(outils, "_sources_m6_contexte", bad)
    _refus(i, w, "SOURCE-INVALIDE")


def test_rang_sql_m4_corrompu_refuse_avant_bus(monde, monkeypatch):
    from unittest.mock import Mock

    from sqlalchemy import update

    from opsys.stockage.schema import REGISTRES

    i, w = _seed()
    with stockage.transaction() as cnx:
        cnx.execute(
            update(REGISTRES).where(REGISTRES.c.departement == "m04-field-ops", REGISTRES.c.rang == 0).values(rang=100)
        )
    bus = Mock()
    monkeypatch.setattr(outils, "_wct_m4_contexte", bus)
    _refus(i, w, "SOURCE-INVALIDE")
    assert not bus.called
