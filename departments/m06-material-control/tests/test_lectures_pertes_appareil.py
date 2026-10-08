"""Fictif : vraies publications/catalogues et références durables, lecteurs sans écriture."""

from __future__ import annotations

import json

import pytest
from m6_material_control import encodage, outils, wct_recus
from m6_material_control.registre import Registre
from sqlalchemy import text

from opsys import contexte, evenements, identite, stockage
from opsys.outils import Autonomie, Niveau, executer_atomique

FICTIF = True
DATE = "2026-10-08T09:00:00-04:00"
WCT = "WCT-PERTES-FICTIF"
CH = "CH-PERTES-FICTIF"
LISTE = "m6_lister_wct_pertes_appareil"
DETAIL = "m6_lire_pertes_alertes_wct_appareil"
STATUTS = ["seuil_absent", "prevu_absent", "declaration_absente", "evaluee"]
ADMIN = contexte.IdentiteAppelante("admin.pertes.fictif", "admin")


@pytest.fixture
def monde(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    db = tmp_path / "pertes-fictives.db"
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{db}")
    stockage.migrer()
    db.chmod(0o600)
    monkeypatch.setattr(identite, "hacher_mot_de_passe", lambda _: "fictif-non-authentifiable")
    with stockage.transaction() as cnx:
        for personne, role in [(ADMIN.personne, "admin"), ("employee.fictif", "employee"), ("seller.fictif", "seller")]:
            identite.creer_personne(cnx, personne, "Personne fictive", "secret-fictif", [role])
    yield
    stockage.liberer()


def _source(
    wct_id=WCT,
    intervention="INT-PERTES-FICTIF",
    devis="DEVIS-PERTES-FICTIF",
    date=DATE,
    recu=True,
    producteur="m04-field-ops",
):
    charge = {
        "wct_id": wct_id,
        "intervention_id": intervention,
        "lead_id": "LEAD-FICTIF",
        "technicien_id": "PERSONNE-CANARY-PRIVEE",
        "horodatage_completion": date,
        "fix_gps_completion": {"latitude": 45.5, "longitude": -73.5},
        "duree_reelle_minutes": 90,
        "ecart_signale": False,
        "revue_id": None,
        "hash_maillon": "a" * 64,
        "consommateurs_cibles": ["M6"],
        "devis_id": devis,
        "statut": "completed_pending_review",
    }
    with stockage.transaction():
        evenements.publier("m4.travaux_termines", producteur, charge, evenement_id=wct_id)
        if recu:
            stockage.maillons("m06-material-control", "wct_recus").append(
                wct_recus.construire(wct_id, intervention, devis, date, encodage.empreinte(charge))
            )
    return charge


def _mouvements(wct_id=WCT, chantier=CH, types=("CONSOMMATION", "PERTE", "BRIS", "RETOUR"), mat="MAT-FICTIF"):
    with stockage.transaction():
        reg = Registre(stockage.maillons("m06-material-control", "principal"))
        result = []
        for type_ in types:
            m, v = reg.ajouter(
                {
                    "type_mouvement": type_,
                    "chantier_id": chantier,
                    "materiau_id": mat,
                    "quantite": 1.25 if type_ == "RETOUR" else -1.25,
                    "cout_unitaire": 777.77,
                    "wct_id": wct_id,
                }
            )
            assert v is None
            result.append(m)
        return result


def _variance(
    statut,
    wct_id=WCT,
    chantier=CH,
    intervention="INT-PERTES-FICTIF",
    date=DATE,
    producteur="m06-material-control",
    **extra,
):
    ident = f"m6-variance-{wct_id}-{statut}"
    charge = {
        "evenement_id": ident,
        "wct_id": wct_id,
        "intervention_id": intervention,
        "chantier_id": chantier,
        "statut_variance": statut,
        "signal_critique": False if statut == "evaluee" else None,
        "seuil_pourcentage": None if statut == "seuil_absent" else 0.30,
        "horodatage_completion": date,
        "lignes": [] if statut == "evaluee" else None,
        **extra,
    }
    with stockage.transaction():
        evenements.publier("m6.variance_chantier", producteur, charge, evenement_id=ident)
    return charge


def _outil(nom):
    found = [o for o in outils.outils() if o.nom == nom]
    assert found, "lecteur DEVICE décidé absent du catalogue"
    return found[0]


def _call(nom=DETAIL, wct_id=WCT, decalage=0, limite=8, ident=ADMIN, **extra):
    args = {"decalage": decalage, "limite": limite, **({"wct_id": wct_id} if nom == DETAIL else {}), **extra}
    with contexte.appele_par_appareil(ident):
        return executer_atomique(_outil(nom), args)


def _dto(nom=DETAIL, **kwargs):
    r = _call(nom=nom, **kwargs)
    assert r["ok"] and "pagination" in r["resultat"], r
    d = r["resultat"]
    assert len(json.dumps(r, ensure_ascii=False)) == d["taille_caracteres"] <= 5400
    assert "CANARY" not in json.dumps(d) and "777.77" not in json.dumps(d)
    return d


def _refus(nom, suffixe, **kwargs):
    r = _call(nom=nom, **kwargs)
    assert r["ok"] and r["resultat"]["accepte"] is False, r
    prefixe = "REJ-M6-WCT-" if nom == LISTE else "REJ-M6-PERTES-"
    assert r["resultat"]["verdict"]["code"] == prefixe + suffixe
    assert "CANARY" not in json.dumps(r)


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


@pytest.mark.parametrize("seuil", [2**53, 1e20])
def test_seuil_entier_hors_domaine_json_mobile_refuse_nominalement(monde, seuil):
    _source()
    _variance("prevu_absent", seuil_pourcentage=seuil)
    avant = _tables()
    _refus(DETAIL, "SOURCE-INVALIDE")
    assert _tables() == avant


@pytest.mark.parametrize("seuil", [1, 2**53 - 1, 0.125])
def test_seuil_fini_entier_sur_ou_fractionnaire_conserve_verbatim(monde, seuil):
    _source()
    _variance("prevu_absent", seuil_pourcentage=seuil)
    avant = _tables()
    assert _dto()["historique_variance"][1]["publication"]["seuil_pourcentage"] == seuil
    assert _tables() == avant


@pytest.mark.parametrize("nom", [LISTE, DETAIL])
def test_declarations_t0_n0_admin_entrees_fermees(monde, nom):
    o = _outil(nom)
    assert o.autonomie is Autonomie.T0 and o.niveau_effectif is Niveau.N0
    assert o.roles_appareil == frozenset({"admin"}) and o.parametres["additionalProperties"] is False
    assert set(o.parametres["required"]) == {"decalage", "limite"} | ({"wct_id"} if nom == DETAIL else set())


def test_liste_reference_recue_rang_durable_sans_hash_invente(monde):
    charge = _source()
    d = _dto(nom=LISTE)
    assert d["wcts"] == [
        {
            "wct_id": WCT,
            "intervention_id": "INT-PERTES-FICTIF",
            "devis_id": "DEVIS-PERTES-FICTIF",
            "horodatage_completion": DATE,
            "reference_recu": {"registre": "wct_recus", "rang": 0, "empreinte_contenu": encodage.empreinte(charge)},
            "reference_bus": {"type": "m4.travaux_termines", "evenement_id": WCT},
        }
    ]
    assert d["couverture"] == {"wcts": "recus_m6_rapproches_m4", "plafond_lignes": 10000}
    assert d["pagination"]["courante"] and d["pagination"]["total"] == 1


def test_detail_sources_signees_nulls_historique_fixe_et_terminal(monde):
    _source()
    mouvements = _mouvements()
    for statut in reversed(STATUTS):
        _variance(statut)
    d = _dto()
    assert d["chantier_id"] == CH and d["declaration_presente"] and d["evaluee_terminal"]
    assert [x["statut"] for x in d["historique_variance"]] == STATUTS
    assert all(x["presente"] and x["publication"]["horodatage_publication"] is None for x in d["historique_variance"])
    assert d["pertes_bris"] == [
        {
            "type_mouvement": m["type_mouvement"],
            "chantier_id": CH,
            "materiau_id": "MAT-FICTIF",
            "quantite_signee": "-1.25",
            "unite": None,
            "horodatage": None,
            "reference": {"registre": "principal", "index": m["index"], "hash_maillon": m["hash_maillon"]},
        }
        for m in mouvements
        if m["type_mouvement"] in ("PERTE", "BRIS")
    ]
    assert d["pagination"]["total"] == 2


def test_declaration_absente_distincte_zero_perte_et_mouvements_legacy_non_lies(monde):
    _source()
    d = _dto()
    assert not d["declaration_presente"] and d["chantier_id"] is None and not d["pertes_bris"]
    assert not d["evaluee_terminal"] and not any(x["presente"] for x in d["historique_variance"])
    _mouvements(types=("CONSOMMATION",))
    d = _dto()
    assert d["declaration_presente"] and not d["pertes_bris"] and d["pagination"]["total"] == 0
    with stockage.transaction():
        reg = Registre(stockage.maillons("m06-material-control", "principal"))
        reg.ajouter(
            {
                "type_mouvement": "PERTE",
                "chantier_id": CH,
                "materiau_id": "MAT-LEGACY",
                "quantite": -9.0,
                "cout_unitaire": None,
            }
        )
    assert not _dto()["pertes_bris"]


def test_wct_publication_absente_et_jamais_recu_nominalement_distincts(monde):
    _refus(DETAIL, "WCT-INCONNU")
    _source(recu=False)
    _refus(DETAIL, "WCT-NON-RECU-M6")
    assert _dto(nom=LISTE)["wcts"] == []


@pytest.mark.parametrize("nom", [LISTE, DETAIL])
def test_ancien_recu_sans_empreinte_ne_certifie_rien(monde, nom):
    _source(recu=False)
    with stockage.transaction():
        stockage.maillons("m06-material-control", "wct_recus").append(
            wct_recus.construire(WCT, "INT-PERTES-FICTIF", "DEVIS-PERTES-FICTIF", DATE)
        )
    _refus(nom, "EMPREINTE-RECUE-ABSENTE")


@pytest.mark.parametrize("nom", [LISTE, DETAIL])
@pytest.mark.parametrize("producteur", ["m01-front-office", "CANARY-FAUX-PRODUCTEUR"])
def test_producteur_m4_forge_refuse_nominalement(monde, nom, producteur):
    _source(producteur=producteur)
    _refus(nom, "SOURCE-INVALIDE")


def test_producteur_m6_et_liaisons_historique_refuses(monde):
    _source()
    _variance("evaluee", producteur="m01-front-office")
    _refus(DETAIL, "SOURCE-INVALIDE")


@pytest.mark.parametrize("extra", [{"intervention": "AUTRE"}, {"date": "2026-10-08T10:00:00-04:00"}])
def test_liaison_wct_variance_incoherente_refuse(monde, extra):
    _source()
    _variance("evaluee", **extra)
    _refus(DETAIL, "LIAISON-INCOHERENTE")


def test_plusieurs_chantiers_ne_sont_pas_fusionnes(monde):
    _source()
    _mouvements(chantier=CH)
    _variance("evaluee", chantier="AUTRE-CHANTIER")
    _refus(DETAIL, "LIAISON-INCOHERENTE")


def test_pages_liste_et_detail_courantes_hors_total(monde):
    for i in range(3):
        _source(wct_id=f"WCT-{i}", date=f"2026-10-0{i + 1}T09:00:00-04:00")
    d = _dto(nom=LISTE, limite=1)
    assert d["pagination"]["suivant"] == 1
    assert _dto(nom=LISTE, decalage=1, limite=1)["wcts"] != d["wcts"]
    assert _dto(nom=LISTE, decalage=10000)["wcts"] == []
    _source()
    _mouvements()
    d = _dto(limite=1)
    assert d["pagination"]["total"] == 2 and d["pagination"]["suivant"] == 1
    assert (
        _dto(decalage=1, limite=1)["pertes_bris"][0]["reference"]["index"] > d["pertes_bris"][0]["reference"]["index"]
    )


@pytest.mark.parametrize("nom", [LISTE, DETAIL])
@pytest.mark.parametrize("args", [{"limite": 0}, {"limite": 9}, {"decalage": -1}, {"decalage": 10001}])
def test_bornes_arguments_refusees(monde, nom, args):
    _refus(nom, "ARGUMENTS-INVALIDES", **args)


@pytest.mark.parametrize("nom", [LISTE, DETAIL])
@pytest.mark.parametrize(
    "ident",
    [
        contexte.IdentiteAppelante("employee.fictif", "employee"),
        contexte.IdentiteAppelante("seller.fictif", "seller"),
        contexte.IdentiteAppelante("employee.fictif", "admin"),
        contexte.IdentiteAppelante("absent.fictif", "admin"),
    ],
)
def test_roles_invalides_avant_snapshots(monde, monkeypatch, nom, ident):
    def interdit(*args, **kwargs):
        raise AssertionError("CANARY-SOURCE-ACCES-AVANT-ROLE")

    monkeypatch.setattr(outils, "_snapshots_pertes_appareil", interdit, raising=False)
    r = _call(nom=nom, ident=ident)
    assert r["ok"] and r["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    assert "CANARY" not in json.dumps(r)


@pytest.mark.parametrize("nom", [LISTE, DETAIL])
def test_admin_revoque_avant_snapshots(monde, monkeypatch, nom):
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, ADMIN.personne, "admin")

    def interdit(*args, **kwargs):
        raise AssertionError("CANARY-SOURCE-ACCES-AVANT-ROLE")

    monkeypatch.setattr(outils, "_snapshots_pertes_appareil", interdit, raising=False)
    r = _call(nom=nom)
    assert r["ok"] and r["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"


def test_lecture_reprise_et_toutes_tables_integrales_sans_artefact(monde):
    _source()
    _mouvements()
    _variance("evaluee")
    before = _tables()
    responses = _call(nom=LISTE), _call()
    assert _tables() == before and before["artefacts"] == []
    stockage.liberer()
    assert (_call(nom=LISTE), _call()) == responses and _tables() == before


@pytest.mark.parametrize("valeur", [float("nan"), float("inf"), True, "CANARY-COUT-TEXTE"])
def test_cout_source_corrompu_meme_chaine_recomposee_refuse(monde, monkeypatch, valeur):
    _source()
    _mouvements(types=("PERTE",))
    original = outils._snapshots_pertes_appareil

    def source_corrompue(*args, **kwargs):
        sources = original(*args, **kwargs)
        raw = sources["mouvements"][0]
        reg = Registre()
        m, v = reg.ajouter(
            {
                **{k: raw[k] for k in ("type_mouvement", "chantier_id", "materiau_id", "quantite", "wct_id")},
                "cout_unitaire": valeur,
            }
        )
        assert v is None and reg.valider_chaine()[0]
        sources["mouvements"] = [m]
        return sources

    monkeypatch.setattr(outils, "_snapshots_pertes_appareil", source_corrompue)
    _refus(DETAIL, "REGISTRE-INVALIDE")


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"wct_id": None},
        {"wct_id": ""},
        {"wct_id": "   "},
        {"wct_id": False},
        {"wct_id": 1},
        {"wct_id": {}},
        {"wct_id": []},
    ],
)
def test_facade_detail_python_invalide_ne_bascule_jamais_en_liste(monde, monkeypatch, kwargs):
    accesses = []

    def interdit(*args, **kw):
        accesses.append(True)
        raise AssertionError("CANARY-SOURCE-NE-DOIT-PAS-ETRE-LUE")

    monkeypatch.setattr(outils, "_snapshots_pertes_appareil", interdit)
    with contexte.appele_par_appareil(ADMIN), stockage.transaction():
        r = outils.lire_pertes_alertes_wct_appareil(**kwargs)
    assert r["accepte"] is False and r["verdict"]["code"] == "REJ-M6-PERTES-ARGUMENTS-INVALIDES"
    assert accesses == []


def test_wct256_reference_variance_canonique_au_dela256_reste_legale(monde):
    wct_id = "WCT-" + "X" * 252
    _source(wct_id=wct_id)
    _mouvements(wct_id=wct_id, types=("CONSOMMATION",))
    pub = _variance("evaluee", wct_id=wct_id)
    assert 256 < len(pub["evenement_id"]) <= 300
    d = _dto(wct_id=wct_id)
    assert (
        d["evaluee_terminal"]
        and d["historique_variance"][3]["publication"]["reference_bus"]["evenement_id"] == pub["evenement_id"]
    )


def test_evaluee_sans_mouvement_de_declaration_est_incoherente(monde):
    _source()
    _variance("evaluee")
    _refus(DETAIL, "LIAISON-INCOHERENTE")


@pytest.mark.parametrize("type_", ["RECEPTION", "VARIANCE_INVENTAIRE"])
def test_type_non_declaration_portant_wct_ne_peut_attester_declaration(monde, type_):
    _source()
    with stockage.transaction():
        reg = Registre(stockage.maillons("m06-material-control", "principal"))
        reg.ajouter(
            {
                "type_mouvement": type_,
                "chantier_id": CH,
                "materiau_id": "MAT-FICTIF",
                "quantite": 2.0,
                "cout_unitaire": None,
                "wct_id": WCT,
            }
        )
    _refus(DETAIL, "LIAISON-INCOHERENTE")


@pytest.mark.parametrize("nom", [LISTE, DETAIL])
def test_erreur_copie_source_nominale_sans_raw(monde, monkeypatch, nom):
    def illisible(*args, **kwargs):
        raise ValueError("CANARY-LECTURE-PRIVEE-JSON")

    monkeypatch.setattr(outils, "_snapshots_pertes_appareil", illisible)
    _refus(nom, "REGISTRE-INVALIDE")


@pytest.mark.parametrize("nom", [LISTE, DETAIL])
def test_borne10000_sources_apres_copies(monde, monkeypatch, nom):
    monkeypatch.setattr(
        outils,
        "_snapshots_pertes_appareil",
        lambda *a, **k: {"recus": [{}] * 10000, "publications": [{}], "mouvements": []},
    )
    _refus(nom, "BORNE-SOURCES")


def test_corruption_chaine_et_rang_recu_refusee_sans_projection(monde):
    _source()
    _mouvements()
    with stockage.transaction() as cnx:
        cnx.execute(
            text(
                "UPDATE registres_maillons SET rang=5 "
                "WHERE departement='m06-material-control' AND registre='wct_recus'"
            )
        )
    _refus(LISTE, "REGISTRE-INVALIDE")


@pytest.mark.parametrize(
    "mutation",
    [
        lambda s: s["mouvements"][0].update(hash_maillon="0" * 64),
        lambda s: s["recus"][0]["maillon"].update(empreinte_contenu="0" * 64),
        lambda s: s["publications"][0].update(catalogue_valide=False),
    ],
)
def test_sources_corrompues_ferment_nominalement(monde, monkeypatch, mutation):
    _source()
    _mouvements()
    original = outils._snapshots_pertes_appareil

    def corrompu(*args, **kwargs):
        s = original(*args, **kwargs)
        mutation(s)
        return s

    monkeypatch.setattr(outils, "_snapshots_pertes_appareil", corrompu)
    r = _call()
    assert r["ok"] and r["resultat"]["accepte"] is False and "CANARY" not in json.dumps(r)


def test_source_date_iso_compacte_refusee_et_bom_id_verbatim(monde):
    _source(wct_id="\ufeff")
    assert _dto(nom=LISTE)["wcts"][0]["wct_id"] == "\ufeff"
    assert _dto(wct_id="\ufeff")["wct"]["wct_id"] == "\ufeff"
    _source(wct_id="WCT-COMPACT-FICTIF", date="20261008T09:00:00-04:00")
    _refus(LISTE, "SOURCE-INVALIDE")


def test_sortie_bornee_reduit_page_aucun_detail_tronque(monde):
    _source()
    for i in range(8):
        _mouvements(types=("PERTE",), mat=f"MAT-{i}-" + "X" * 240)
    for statut in STATUTS:
        _variance(statut)
    d = _dto()
    assert 0 < d["pagination"]["affichees"] < 8 and d["pagination"]["total"] == 8
    assert len(d["historique_variance"]) == 4 and all(x["presente"] for x in d["historique_variance"])
    assert all(len(m["materiau_id"]) > 240 for m in d["pertes_bris"])
    assert "tronque" not in d and "apercu" not in d
