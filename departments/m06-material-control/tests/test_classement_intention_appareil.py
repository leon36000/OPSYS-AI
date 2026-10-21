"""FICTIF : vraies publications, maillons et SQLite; pas Cap/Gateway/mobile."""

from __future__ import annotations

import copy
import datetime as dt
import importlib
import importlib.util
from contextlib import nullcontext
from pathlib import Path

import pytest
from m6_material_control import classement_variance_appareil as c
from m6_material_control import outils

from opsys import contexte, idempotence, stockage
from opsys.outils import executer_atomique

spec = importlib.util.spec_from_file_location(
    "fixture_intention_classement", Path(__file__).with_name("test_classement_variance_appareil.py")
)
fx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fx)
monde = fx.monde
META = idempotence.Meta("4612b2de-a1c4-4a68-a044-e0ab685025ad", "APP-CLASSEMENT-FICTIF", fx.DATE)


def contexte_meta(meta=META):
    name = "m6_material_control.classement_variance_contexte"
    if importlib.util.find_spec(name) is None:
        return nullcontext()  # Préimage8099 : atteindre le vrai comportement avant v2.
    return importlib.import_module(name).contexte_mutation(meta)


def executer(args, meta=META, limite=5400):
    reception = contexte.HorodatageAppareil(
        meta.appareil, dt.datetime.fromisoformat(meta.horodatage_appareil), dt.datetime.fromisoformat(fx.DATE)
    )
    with (
        contexte_meta(meta),
        contexte.appele_par_appareil(fx.ADMIN),
        contexte.receptionne_de(reception),
        contexte.sortie_bornee(limite),
    ):
        return executer_atomique(fx.outil(fx.ECRIRE), args)


def replay(args, response, meta=META):
    with contexte_meta(meta), contexte.appele_par_appareil(fx.ADMIN), stockage.transaction():
        outils.verifier_rejeu_classement_variance_appareil(args, response)


def test_succes_v2_scelle_exacte_intention_hash_et_49tables(monde):
    args = fx.demande(fx.preparer())
    before = fx.fx.fx._tables()
    first = executer(args)
    assert first["resultat"]["version_schema"] == 2
    result = first["resultat"]["resultat"]
    assert result["intention"] == {
        "appareil_id": META.appareil,
        "intention_uuid": META.cle,
        "empreinte_arguments": idempotence.empreinte_arguments(args),
    }
    with stockage.transaction():
        lines = list(stockage.maillons("m06-material-control", c.REGISTRE))
    assert lines[-1]["intention"] == result["intention"]
    c.valider_classements(lines)
    after = fx.fx.fx._tables()
    assert len(after) == 49
    assert {n for n in before if before[n] != after[n]} == {"registres_maillons"}
    replay(args, first)
    assert after == fx.fx.fx._tables()


def test_vrai_refus_v2_scelle_preuve_auteur_heure_et_replay(monde):
    args = fx.demande(fx.preparer())
    executer(args)
    second = idempotence.Meta("4612b2de-a1c4-4a68-a044-e0ab685025ae", META.appareil, META.horodatage_appareil)
    before = fx.fx.fx._tables()
    refused = executer(args, second)
    r = refused["resultat"]
    assert r["version_schema"] == 2 and r["accepte"] is False
    assert r["verdict"]["code"] == "REJ-M6-CLASSEMENT-REVISION-PERIMEE"
    assert r["auteur"] == {"personne": fx.ADMIN.personne, "role": "admin", "source": "appareil"}
    assert dt.datetime.fromisoformat(r["horodatage_appareil_declare"]) == dt.datetime.fromisoformat(
        second.horodatage_appareil
    )
    with stockage.transaction():
        proof = list(stockage.maillons("m06-material-control", c.REGISTRE_REFUS))
    assert len(proof) == 1 and proof[0]["intention"] == r["intention"]
    assert proof[0]["hash_maillon"] == r["preuve_refus"]["hash_maillon"]
    after = fx.fx.fx._tables()
    assert len(after) == 49 and {n for n in before if before[n] != after[n]} == {"registres_maillons"}
    stockage.liberer()
    replay(args, refused, second)
    assert after == fx.fx.fx._tables()


def test_succes_cache_remplace_en_refus_est_inconnu(monde):
    args = fx.demande(fx.preparer())
    success = executer(args)
    tampered = {"ok": True, "resultat": c.refuser("REVISION-PERIMEE")}
    before = fx.fx.fx._tables()
    with pytest.raises(c.Refus, match="REJEU-INCOHERENT"):
        replay(args, tampered)
    assert before == fx.fx.fx._tables()
    replay(args, success)


def test_legacy_refus_sans_preuve_ne_certifie_pas_absence_effet(monde):
    args = fx.demande(fx.preparer())
    before = fx.fx.fx._tables()
    with pytest.raises(c.Refus, match="REJEU-INCOHERENT"):
        replay(args, {"ok": True, "resultat": c.refuser("REVISION-PERIMEE")})
    assert before == fx.fx.fx._tables()


def test_refus_apres_append_devient_panne_rollback_et_meme_uuid_retry(monde):
    args = fx.demande(fx.preparer())
    _, patch = monde
    original = outils._ajouter_classement_variance

    def failure(m):
        original(m)
        raise c.Refus("REGISTRE-INVALIDE")

    patch.setattr(outils, "_ajouter_classement_variance", failure)
    before = fx.fx.fx._tables()
    with pytest.raises(RuntimeError, match="atomique"):
        executer(args)
    assert before == fx.fx.fx._tables()
    patch.setattr(outils, "_ajouter_classement_variance", original)
    assert executer(args)["resultat"]["accepte"] is True


@pytest.mark.parametrize("value", [None, 7, False, 3.5, []])
def test_maillon_malforme_refuse_ferme_pas_exception_brute(value):
    with pytest.raises(c.Refus, match="REGISTRE-INVALIDE"):
        c.valider_classements([value])


def test_deux_uuid_meme_corps_heure_et_preuve_etrangere(monde):
    args = fx.demande(fx.preparer())
    first = executer(args)
    other = idempotence.Meta("4612b2de-a1c4-4a68-a044-e0ab685025af", META.appareil, META.horodatage_appareil)
    negative = executer(args, other)
    assert negative["resultat"]["accepte"] is False
    assert first["resultat"]["resultat"]["intention"]["intention_uuid"] == META.cle
    assert negative["resultat"]["intention"]["intention_uuid"] == other.cle
    before = fx.fx.fx._tables()
    replay(args, negative, other)
    with pytest.raises(c.Refus, match="REJEU-INCOHERENT"):
        replay(args, negative, META)
    replay(args, first)
    assert before == fx.fx.fx._tables()


def test_deux_appareils_meme_uuid_ne_sont_pas_meme_intention(monde):
    args = fx.demande(fx.preparer())
    first = executer(args)
    other = idempotence.Meta(META.cle, "APP-AUTRE-FICTIF", META.horodatage_appareil)
    negative = executer(args, other)
    before = fx.fx.fx._tables()
    replay(args, negative, other)
    replay(args, first)
    with pytest.raises(c.Refus, match="REJEU-INCOHERENT"):
        replay(args, negative)
    assert before == fx.fx.fx._tables()


@pytest.mark.parametrize("kind", [TypeError, KeyError, c.Refus])
def test_panne_apres_append_preuve_refus_annule_tout_et_retry(monde, kind):
    args = fx.demande(fx.preparer())
    executer(args)
    other = idempotence.Meta("4612b2de-a1c4-4a68-a044-e0ab685025af", META.appareil, META.horodatage_appareil)
    _, patch = monde
    original = outils._ajouter_refus_classement_variance

    def failure(m):
        original(m)
        raise kind("SORTIE-TROP-VOLUMINEUSE")

    patch.setattr(outils, "_ajouter_refus_classement_variance", failure)
    before = fx.fx.fx._tables()
    with pytest.raises(RuntimeError, match="atomique"):
        executer(args, other)
    assert before == fx.fx.fx._tables()
    patch.setattr(outils, "_ajouter_refus_classement_variance", original)
    assert executer(args, other)["resultat"]["accepte"] is False


def test_meta_scope_reset_et_absence_avant_source(monde):
    from m6_material_control import classement_variance_contexte as ctx

    args = fx.demande(fx.preparer())
    with contexte_meta():
        assert ctx.intention(args)["intention_uuid"] == META.cle
    with pytest.raises(c.Refus, match="CONTEXTE-MUTATION-ABSENT"):
        ctx.intention(args)
    _, patch = monde

    def prohibited(*_):
        raise AssertionError("aucune source métier sans Meta")

    patch.setattr(outils, "_sources_classement_variance", prohibited)
    with (contexte.appele_par_appareil(fx.ADMIN), stockage.transaction(),
          pytest.raises(c.Refus, match="CONTEXTE-MUTATION-ABSENT")):
        outils.autoriser_classement_variance_appareil(args)


@pytest.mark.parametrize("hour", ["2026-10-08T17:00:00", "FICTIF-invalide", None])
def test_meta_hora_invalide_refuse_avant_source(hour):
    from m6_material_control import classement_variance_contexte as ctx

    meta = idempotence.Meta(META.cle, META.appareil, hour)
    with contexte_meta(meta), pytest.raises(c.Refus, match="CONTEXTE-MUTATION-ABSENT"):
        ctx.intention({})


@pytest.mark.parametrize("suffix", sorted(c.REFUS_FRAIS))
def test_six_refus_frais_atteignables_ont_preuve_scellee(monde, suffix):
    if suffix == "LIGNE-HORS-PERIMETRE":
        world = fx.fx.preparer(1)
        world["formulaire"]["lignes_materiaux"] = [
            {
                "type_ligne": "prevu",
                "materiau_id": fx.fx.fx.MAT,
                "quantite": 40,
                "quantite_estimee": 40,
                "unite": "pi",
            }
        ]
        world["preuves_lignes"] = []
        assert fx.fx.executer(world)["resultat"]["accepte"]
        args = fx.demande(world)
    else:
        args = fx.demande(fx.preparer())
    if suffix == "ARGUMENTS-INVALIDES":
        args["motif"] = " \t"
    elif suffix == "REVISION-PERIMEE":
        args["classement_attendu"] = {"registre": c.REGISTRE, "index": 0, "hash_maillon": "0" * 64}
    elif suffix in {"PIECES-INVALIDES", "LIAISON-INCOHERENTE"}:
        with contexte_meta(), contexte.appele_par_appareil(fx.ADMIN), stockage.transaction():
            _, source = outils.autoriser_classement_variance_appareil(args)
            piece = c.pieces_disponibles(source, args["selection"])[0]
        args["references_pieces"] = [piece, copy.deepcopy(piece)] if suffix == "PIECES-INVALIDES" else [piece]
        if suffix == "LIAISON-INCOHERENTE":
            piece["reference_mouvement"]["hash_maillon"] = "0" * 64
    before = fx.fx.fx._tables()
    r = executer(args, limite=800 if suffix == "SORTIE-TROP-VOLUMINEUSE" else 5400)
    assert r["resultat"]["verdict"]["code"] == "REJ-M6-CLASSEMENT-" + suffix
    assert r["resultat"]["version_schema"] == 2
    after = fx.fx.fx._tables()
    assert {n for n in before if before[n] != after[n]} == {"registres_maillons"}
    replay(args, r)
    assert after == fx.fx.fx._tables()
