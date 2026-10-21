"""Lecture du registre Growth, données déclarées fictives et sans calcul de performance."""

from __future__ import annotations

import copy
import json

import pytest
from m7_marketing import growth, growth_lecture
from sqlalchemy import insert, select, update

from opsys import stockage
from opsys.stockage import codec
from opsys.stockage.schema import REGISTRES

DEPARTEMENT = "m07-marketing"
REGISTRE = "growth"


@pytest.fixture
def base_growth(tmp_path, monkeypatch):
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "opsys-home"))
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'growth.sqlite3'}")
    stockage.liberer()
    stockage.migrer()
    yield
    stockage.liberer()


def _enregistrer(
    observation_id: str,
    debut: str,
    fin: str,
    *,
    source: str = "export analytique fictif",
    preuve: str = "rapport:croissance-fictif",
):
    resultat = growth.enregistrer_observation(
        observation_id,
        "clics",
        12.5,
        "clic",
        debut,
        fin,
        "google",
        "campagne-fictive",
        source,
        preuve,
        0.7,
    )
    assert resultat["statut"] == "enregistre"
    return resultat["observation"]


def _lecture(cnx, *, debut="2026-01-01", fin="2026-01-31", decalage=0, limite=25):
    return growth_lecture.lire(cnx, debut=debut, fin=fin, decalage=decalage, limite=limite)


def _inscrire_brut(cnx, rang: int, texte: str) -> None:
    cnx.execute(insert(REGISTRES).values(
        departement=DEPARTEMENT, registre=REGISTRE, rang=rang, maillon=texte,
    ))


def test_lecture_persiste_paginee_et_ne_modifie_pas_le_registre(base_growth):
    with stockage.transaction() as cnx:
        _enregistrer("obs-a-fictif", "2026-01-01", "2026-01-05", source="https://source.invalid/export")
        _enregistrer("obs-b-fictif", "2026-01-10", "2026-01-11", preuve="file:///preuves/opaque")
        _enregistrer("obs-c-fictif", "2026-01-20", "2026-01-21")
        _enregistrer("obs-partielle-fictive", "2025-12-31", "2026-01-02")
        _enregistrer("obs-hors-fictive", "2026-02-01", "2026-02-03")
        plan = growth.plan_30j("2026-02-01")
        assert plan["statut"] == "plan_genere"
        avant = cnx.execute(
            select(REGISTRES.c.rang, REGISTRES.c.maillon)
            .where(REGISTRES.c.departement == DEPARTEMENT, REGISTRES.c.registre == REGISTRE)
            .order_by(REGISTRES.c.rang)
        ).all()

    stockage.liberer()
    with stockage.transaction() as cnx:
        page1 = _lecture(cnx, limite=2)
    with stockage.transaction() as cnx:
        page2 = _lecture(cnx, decalage=2, limite=2)
        apres = cnx.execute(
            select(REGISTRES.c.rang, REGISTRES.c.maillon)
            .where(REGISTRES.c.departement == DEPARTEMENT, REGISTRES.c.registre == REGISTRE)
            .order_by(REGISTRES.c.rang)
        ).all()

    assert page1["statut"] == "OBSERVATIONS_DECLAREES"
    assert page1["periode"] == {"debut": "2026-01-01", "fin": "2026-01-31"}
    assert page1["total_observations"] == 5
    assert page1["total_periode"] == 3
    assert page1["hors_periode"] == 2
    assert [obs["observation_id"] for obs in page1["observations"]] == ["obs-a-fictif", "obs-b-fictif"]
    assert page1["observations"][0]["source"] == "https://source.invalid/export"
    assert page1["observations"][1]["preuve"] == "file:///preuves/opaque"
    assert page1["observations"][0]["statut_source"] == "DECLAREE_NON_VERIFIEE"
    assert page1["observations"][0]["auteur"] is None
    assert page1["observations"][0]["verification_externe"] is None
    assert page1["observations"][0]["confiance"] == 0.7
    assert page1["suivant"] == 2 and page1["tronque"] is True
    assert [obs["observation_id"] for obs in page2["observations"]] == ["obs-c-fictif"]
    assert page2["suivant"] is None and page2["tronque"] is False
    assert "ROI" in " ".join(page1["limites"])
    assert avant == apres


def test_registre_vide_n_est_pas_un_zero_d_activite(base_growth):
    with stockage.transaction() as cnx:
        resultat = _lecture(cnx)

    assert resultat["statut"] == "OBSERVATIONS_DECLAREES"
    assert resultat["observations"] == []
    assert resultat["total_observations"] == 0
    assert resultat["total_periode"] == 0
    assert "pas preuve de zéro activité" in resultat["message"]


@pytest.mark.parametrize(
    ("debut", "fin", "decalage", "limite"),
    [
        ("20260101", "2026-01-31", 0, 25),
        ("2026-W01-1", "2026-01-31", 0, 25),
        ("2026-02-30", "2026-03-01", 0, 25),
        ("2026-01-02", "2026-01-01", 0, 25),
        ("2026-01-01", "2027-01-02", 0, 25),
        ("2026-01-01", "2026-01-31", True, 25),
        ("2026-01-01", "2026-01-31", 1001, 25),
        ("2026-01-01", "2026-01-31", 0, 0),
        ("2026-01-01", "2026-01-31", 0, 101),
        ("2026-01-01", "2026-01-31", 0, True),
    ],
)
def test_parametres_hors_contrat_refuses_avant_lecture(base_growth, debut, fin, decalage, limite):
    with stockage.transaction() as cnx, pytest.raises(growth_lecture.GrowthLectureErreur):
        growth_lecture.lire(cnx, debut=debut, fin=fin, decalage=decalage, limite=limite)


def test_corruption_meme_hors_filtre_refusee_et_aucun_append(base_growth):
    with stockage.transaction() as cnx:
        enregistrement = _enregistrer("obs-corrompue-fictive", "2025-01-01", "2025-01-02")
        rang = cnx.execute(
            select(REGISTRES.c.rang).where(
                REGISTRES.c.departement == DEPARTEMENT,
                REGISTRES.c.registre == REGISTRE,
            )
        ).scalar_one()
        altere = copy.deepcopy(enregistrement)
        altere["source"] = "référence modifiée"
        cnx.execute(
            update(REGISTRES).where(
                REGISTRES.c.departement == DEPARTEMENT,
                REGISTRES.c.registre == REGISTRE,
                REGISTRES.c.rang == rang,
            ).values(maillon=codec.encoder(altere))
        )
        avant = cnx.execute(
            select(REGISTRES.c.rang).where(REGISTRES.c.departement == DEPARTEMENT, REGISTRES.c.registre == REGISTRE)
        ).all()
        with pytest.raises(growth_lecture.GrowthLectureErreur, match="EMPREINTE"):
            _lecture(cnx, debut="2026-01-01", fin="2026-01-31")
        apres = cnx.execute(
            select(REGISTRES.c.rang).where(REGISTRES.c.departement == DEPARTEMENT, REGISTRES.c.registre == REGISTRE)
        ).all()

    assert avant == apres


@pytest.mark.parametrize(
    "changement",
    [
        {"valeur": True},
        {"valeur": float("nan")},
        {"confiance": float("inf")},
        {"unite": []},
        {"periode": {"debut": "2026-02-02", "fin": "2026-01-01"}},
        {"preuve": "  "},
    ],
)
def test_formes_type_et_numeriques_malformes_refuses(base_growth, changement):
    with stockage.transaction() as cnx:
        _enregistrer("obs-invalide-fictive", "2026-01-01", "2026-01-02")
        range_maillon = cnx.execute(
            select(REGISTRES.c.rang, REGISTRES.c.maillon).where(
                REGISTRES.c.departement == DEPARTEMENT,
                REGISTRES.c.registre == REGISTRE,
            )
        ).one()
        original = codec.decoder(range_maillon.maillon)
        original.update(changement)
        brut = json.dumps(original, allow_nan=True, ensure_ascii=False, separators=(",", ":"))
        cnx.execute(update(REGISTRES).where(
            REGISTRES.c.departement == DEPARTEMENT,
            REGISTRES.c.registre == REGISTRE,
            REGISTRES.c.rang == range_maillon.rang,
        ).values(maillon=brut))
        with pytest.raises(growth_lecture.GrowthLectureErreur):
            _lecture(cnx)


def test_ids_observation_dupliques_refuses(base_growth):
    with stockage.transaction() as cnx:
        maillon = _enregistrer("obs-dupliquee-fictive", "2026-01-01", "2026-01-02")
        stockage.maillons(DEPARTEMENT, REGISTRE).append({"type": "observation", **maillon})
        with pytest.raises(growth_lecture.GrowthLectureErreur, match="ID-DUPLIQUE"):
            _lecture(cnx)


@pytest.mark.parametrize("mode", ["count", "row", "total"])
def test_bornes_sql_precedent_tout_decode(base_growth, monkeypatch, mode):
    with stockage.transaction() as cnx:
        if mode == "count":
            textes = ['{"type":"plan_growth_30j"}'] * 1001
        elif mode == "row":
            textes = [json.dumps({"type": "plan_growth_30j", "pad": "x" * 33000})]
        else:
            textes = [json.dumps({"type": "plan_growth_30j", "pad": "x" * 32000})] * 33
        for rang, texte in enumerate(textes):
            _inscrire_brut(cnx, rang, texte)

        appels_decodeur = []

        def decoder_spy(texte):
            appels_decodeur.append(len(texte))
            return codec.decoder(texte)

        monkeypatch.setattr(growth_lecture.codec, "decoder", decoder_spy)
        with pytest.raises(growth_lecture.GrowthLectureErreur, match="LIMITE"):
            _lecture(cnx)

    assert appels_decodeur == []


def test_observation_courante_conserve_son_hash_et_pas_de_calcul_derive(base_growth):
    with stockage.transaction() as cnx:
        observation = _enregistrer("obs-hash-fictive", "2026-01-01", "2026-01-31")
        resultat = _lecture(cnx)

    ligne = resultat["observations"][0]
    charge = {cle: observation[cle] for cle in (
        "observation_id", "metrique", "valeur", "unite", "periode", "plateforme", "campagne",
        "source", "preuve", "confiance",
    )}
    assert ligne["empreinte"] == growth._empreinte(charge)
    assert ligne["valeur"] == 12.5
    assert not {"score", "projection", "cout", "conversion", "roi"} & set(ligne)


@pytest.mark.parametrize("brut", [
    '{"__opsys__":"dict","v":null}',
    '{"__opsys__":"bytes","v":null}',
    '{"__opsys__":"decimal","v":"montant-invalide-fictif"}',
])
def test_etiquette_codec_corrompue_produit_un_refus_nomme(base_growth, brut):
    with stockage.transaction() as cnx:
        _inscrire_brut(cnx, 0, brut)
        with pytest.raises(growth_lecture.GrowthLectureErreur, match="GROWTH-MAILLON-INVALIDE"):
            _lecture(cnx)


def test_observation_retypee_plan_hors_periode_refusee(base_growth):
    with stockage.transaction() as cnx:
        observation = _enregistrer("obs-pseudo-plan-fictive", "2025-01-01", "2025-01-02")
        observation["type"] = "plan_growth_30j"
        cnx.execute(update(REGISTRES).where(
            REGISTRES.c.departement == DEPARTEMENT, REGISTRES.c.registre == REGISTRE,
        ).values(maillon=codec.encoder(observation)))
        with pytest.raises(growth_lecture.GrowthLectureErreur, match="GROWTH-PLAN-INVALIDE"):
            _lecture(cnx)


# Compatibilité : ces scénarios complètent les anciens oracles sans les modifier.
def _charge_humaine_fictive():
    return {"observation_id": "humaine-fictive", "metrique": "clics", "valeur": 3.5, "unite": "clic",
            "debut": "2026-01-01", "fin": "2026-01-31", "plateforme": "google", "campagne": "fictive",
            "source": "source manuelle fictive", "preuve": "rapport:fictif", "confiance": 0.7}


def _personne_et_contexte_humain(cnx):
    from contextlib import ExitStack

    from opsys import contexte, identite

    if identite.personne(cnx, "owner_growth_fictif") is None:
        identite.creer_personne(cnx, "owner_growth_fictif", "Owner fictif", "mot-de-passe-fictif-2026",
                               ["nathan_owner"])
    stack = ExitStack()
    stack.enter_context(contexte.appele_par_appareil(
        contexte.IdentiteAppelante("owner_growth_fictif", "nathan_owner", source="console")))
    stack.enter_context(contexte.appeler_en_tant_que(DEPARTEMENT, origine="console"))
    return stack


def _ecrire_humaine(cnx, arguments=None):
    _, tete = growth_lecture.lire_prefixe(cnx)
    with _personne_et_contexte_humain(cnx):
        return growth.enregistrer_observation_humaine(
            arguments or _charge_humaine_fictive(), rang_attendu=tete["rang"], empreinte_attendue=tete["empreinte"],
            horodatage="2026-01-31T12:00:00+00:00",
        )


def test_growth_v1_v2_plans_et_auteurs_distincts_sans_recriture(base_growth):
    with stockage.transaction() as cnx:
        ancienne = _enregistrer("ancienne-fictive", "2026-01-01", "2026-01-02")
        ancien_texte = cnx.execute(select(REGISTRES.c.maillon).where(REGISTRES.c.rang == 0)).scalar_one()
        growth.plan_30j("2026-02-01")
        humaine = _ecrire_humaine(cnx)
        avant = cnx.execute(select(REGISTRES.c.maillon).order_by(REGISTRES.c.rang)).scalars().all()
    stockage.liberer()
    with stockage.transaction() as cnx:
        resultat = _lecture(cnx)
        apres = cnx.execute(select(REGISTRES.c.maillon).order_by(REGISTRES.c.rang)).scalars().all()
    assert ancien_texte == apres[0] and avant == apres
    assert resultat["total_observations"] == 2 and resultat["tete"]["rang"] == 3
    assert resultat["observations"][0]["auteur"] is None
    assert resultat["observations"][0]["empreinte"] == ancienne["empreinte"]
    assert resultat["observations"][1]["auteur"] == "owner_growth_fictif"
    assert resultat["observations"][1]["empreinte"] == humaine["observation"]["empreinte"]
    assert all(o["statut_source"] == "DECLAREE_NON_VERIFIEE" and o["verification_externe"] is None
               for o in resultat["observations"])


@pytest.mark.parametrize("changement", [
    {"schema_version": True}, {"schema_version": 3},
    {"provenance": {"mode": "saisie_humaine_console", "auteur": "fictif", "role": [],
                    "horodatage": "2026-01-01T12:00:00+00:00"}},
    {"provenance": {"mode": "saisie_humaine_console", "auteur": "fictif", "role": "admin"}},
    {"provenance": {"mode": "appareil", "auteur": "fictif", "role": "admin",
                    "horodatage": "2026-01-01T12:00:00+00:00"}},
    {"provenance": {"mode": "saisie_humaine_console", "auteur": "fictif", "role": "employee",
                    "horodatage": "2026-01-01T12:00:00+00:00"}},
    {"provenance": {"mode": "saisie_humaine_console", "auteur": "fictif", "role": "admin",
                    "horodatage": "2026-01-01T12:00:00"}},
])
def test_growth_v2_forme_provenance_fermee(base_growth, changement):
    with stockage.transaction() as cnx:
        resultat = _ecrire_humaine(cnx)
        corrompu = {**resultat["observation"], **changement}
        corrompu["empreinte"] = growth._empreinte({k: v for k, v in corrompu.items()
                                                  if k not in {"type", "empreinte"}})
        cnx.execute(update(REGISTRES).values(maillon=codec.encoder(corrompu)))
        with pytest.raises(growth_lecture.GrowthLectureErreur, match="GROWTH-PROVENANCE-INVALIDE"):
            _lecture(cnx)


def test_growth_v2_changement_auteur_sans_rehash_refuse(base_growth):
    with stockage.transaction() as cnx:
        resultat = _ecrire_humaine(cnx)
        corrompu = copy.deepcopy(resultat["observation"])
        corrompu["provenance"]["auteur"] = "autre-fictif"
        cnx.execute(update(REGISTRES).values(maillon=codec.encoder(corrompu)))
        with pytest.raises(growth_lecture.GrowthLectureErreur, match="GROWTH-EMPREINTE-INVALIDE"):
            _lecture(cnx)


@pytest.mark.parametrize(("source", "origine"), [("appareil", "console"), ("console", DEPARTEMENT)])
def test_growth_port_humain_refuse_contexte_non_console(base_growth, source, origine):
    from opsys import contexte

    with stockage.transaction() as cnx:
        with _personne_et_contexte_humain(cnx):
            _, tete = growth_lecture.lire_prefixe(cnx)
        with (contexte.appele_par_appareil(contexte.IdentiteAppelante("owner_growth_fictif", "nathan_owner",
                                                                   source=source)),
              contexte.appeler_en_tant_que(DEPARTEMENT, origine=origine), pytest.raises(PermissionError)):
            growth.enregistrer_observation_humaine(
                _charge_humaine_fictive(), rang_attendu=tete["rang"], empreinte_attendue=tete["empreinte"],
                horodatage="2026-01-31T12:00:00+00:00",
            )
        assert cnx.execute(select(REGISTRES)).all() == []


def test_growth_schema_outil_agent_ne_peut_pas_declarer_phase_humaine(base_growth):
    from m7_marketing import outils

    from opsys.outils import valider_arguments

    outils_actuels = outils.outils()
    assert not any(o.nom == "m7_enregistrer_observation_humaine" for o in outils_actuels)
    outil = next(o for o in outils_actuels if o.nom == "m7_enregistrer_observation_growth")
    assert outil.parametres["additionalProperties"] is False
    for champ in ("auteur", "horodatage", "provenance", "schema_version", "phase_humaine"):
        assert champ not in outil.parametres["properties"]
        assert valider_arguments(outil.parametres, {**_charge_humaine_fictive(), champ: "forge"})
    with stockage.transaction() as cnx:
        resultat = outils.enregistrer_observation_growth(**_charge_humaine_fictive())
        assert "schema_version" not in resultat["observation"]
        assert _lecture(cnx)["observations"][0]["auteur"] is None


def test_growth_quota_sql_refuse_avant_decoder(base_growth, monkeypatch):
    plan = codec.encoder({"type": "plan_growth_30j", "horizon_debut": "2026-01-01",
                          "recommandations": [], "donnees_manquantes": [], "limites": []})
    with stockage.transaction() as cnx:
        cnx.execute(insert(REGISTRES), [{"departement": DEPARTEMENT, "registre": REGISTRE,
                                       "rang": rang, "maillon": plan} for rang in range(1001)])
        appels = []

        def decoder_interdit(texte):
            appels.append(texte)
            raise AssertionError("les budgets SQL doivent précéder le décodage")

        monkeypatch.setattr(growth_lecture.codec, "decoder", decoder_interdit)
        with pytest.raises(growth_lecture.GrowthLectureErreur, match="GROWTH-LIMITE-NOMBRE"):
            _ecrire_humaine(cnx)
        assert appels == []


def test_growth_quota_total_caracteres_refuse_nouvel_append(base_growth):
    # Plans historiques de forme valide; aucune sémantique de leurs textes n'est revendiquée.
    with stockage.transaction() as cnx:
        restant = growth_lecture.LIMITE_CARACTERES - 10
        rang = 0
        while restant > 0:
            plan = {"type": "plan_growth_30j", "horizon_debut": "2026-01-01", "recommandations": [],
                    "donnees_manquantes": [], "limites": [""]}
            base = len(codec.encoder(plan))
            taille = min(growth_lecture.LIMITE_PAR_MAILLON, restant)
            if taille < base:
                break
            plan["limites"] = ["x" * (taille - base)]
            texte = codec.encoder(plan)
            _inscrire_brut(cnx, rang, texte)
            restant -= len(texte)
            rang += 1
        avant = cnx.execute(select(REGISTRES.c.maillon).order_by(REGISTRES.c.rang)).scalars().all()
        with pytest.raises(growth_lecture.GrowthLectureErreur, match="GROWTH-LIMITE-REGISTRE"):
            _ecrire_humaine(cnx)
        apres = cnx.execute(select(REGISTRES.c.maillon).order_by(REGISTRES.c.rang)).scalars().all()
        assert apres == avant


def test_growth_tete_refuse_prefixe_sql_non_contigu(base_growth):
    with stockage.transaction() as cnx:
        plan = codec.encoder({"type": "plan_growth_30j", "horizon_debut": "2026-01-01",
                              "recommandations": [], "donnees_manquantes": [], "limites": []})
        _inscrire_brut(cnx, 4, plan)
        with pytest.raises(growth_lecture.GrowthLectureErreur, match="GROWTH-RANGS-INVALIDES"):
            growth_lecture.lire_prefixe(cnx)
