"""Fictif: admission et quota Cap des rappels DEVICE, indépendants du writer M1."""

import importlib.util
import json
from pathlib import Path

import pytest
from sqlalchemy import update

from opsys import contexte, idempotence, stockage
from opsys.capacites import Capacites
from opsys.departements import charger_departements
from opsys.stockage.schema import META as SCHEMA_META
from opsys.stockage.schema import PERSONNES

# Schéma courant déclaré : toutes les lignes, y compris la file F4 et Alembic.
TABLES_SQLITE = set(SCHEMA_META.tables) | {"alembic_version"}

LECTURE = "m1_lister_rappels_appareil"
MUTATION = "m1_prendre_en_charge_rappel_appareil"
META = idempotence.Meta(
    cle="4c8b1a5b-b8ed-49e8-b1b3-0185ac8ba113",
    appareil="APP-RAPPEL-FICTIF",
    horodatage_appareil="2026-10-08T00:00:00+00:00",
)
fixture_path = Path(__file__).resolve().parents[1] / "departments/m01-front-office/tests/test_rappels_appareil.py"
spec = importlib.util.spec_from_file_location("fixture_cap_rappels_m1", fixture_path)
fx = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fx)
monde = fx.monde


def capacite(quota=5400):
    def interdite():
        raise AssertionError("Cette garde doit précéder toute connexion ou création d'artefact.")

    return Capacites({}, interdite, memoire=False, limite_sortie=quota)


def test_lecture_meta_refuse_avant_connexion_ou_claim():
    response = capacite().appeler(LECTURE, {}, meta=META)
    assert response.get("erreur") == "idempotence_hors_portee_lecture"
    assert response["ok"] is False


@pytest.mark.parametrize("nom", [LECTURE, MUTATION])
@pytest.mark.parametrize("quota", [800, 5400, 9000])
def test_quota_enveloppe_entiere_unicode_sans_artefact(nom, quota):
    cap = capacite(quota)
    response = {"ok": True, "resultat": {"fictif": ""}}

    def enveloppe(value):
        return {**value, "rejoue": False} if nom == MUTATION else value

    target = min(quota, 5400)
    overhead = len(json.dumps(enveloppe(response), ensure_ascii=False))
    response["resultat"]["fictif"] = "😀" * (target - overhead)
    text = json.dumps(enveloppe(response), ensure_ascii=False)
    assert len(text) == target and len(text.encode()) > target
    assert cap._tronquer(response, nom) == response
    too_large = {"ok": True, "resultat": {"fictif": response["resultat"]["fictif"] + "é"}}
    refusal = cap._tronquer(too_large, nom)
    assert refusal["ok"] is False
    assert "apercu" not in refusal and "tronque" not in refusal
    if nom == MUTATION:
        assert refusal["issue"] == "inconnue"
    else:
        assert refusal["erreur"] == "REJ-M1-RAPPEL-SORTIE-TROP-VOLUMINEUSE"


def capacite_reelle(quota=5400):
    return Capacites(charger_departements(), stockage.transaction, memoire=False, limite_sortie=quota)


def appeler(cap, args, meta=META, acteur=fx.ADMIN):
    with contexte.appele_par_appareil(acteur):
        return cap.appeler(MUTATION, args, meta=meta)


def demande(t):
    with contexte.appele_par_appareil(fx.ADMIN):
        response = capacite_reelle().appeler(LECTURE, {"apres_transfert_id": None, "taille_page": 8})
    assert response["ok"] and response["resultat"]["accepte"], response
    row = next(r for r in response["resultat"]["resultat"]["rappels"] if r["transfert_id"] == t)
    return {"transfert_id": t, "snapshot_attendu": row["suivi_rappel"]["snapshot_suivi"]}


def test_cap_sql_reponse_perdue_restart_meme_uuid_own_ack(monde):
    args = demande(fx.importer())
    before = fx.tables()
    first = appeler(capacite_reelle(), args)
    assert first["ok"] and first["resultat"]["accepte"], first
    ack = first["resultat"]["resultat"]
    assert ack["intention_uuid"] == META.cle and ack["appareil"] == META.appareil
    assert ack["par"] == fx.ADMIN.personne and ack["snapshot_attendu"] == args["snapshot_attendu"]
    after = fx.tables()
    assert {n for n in before if before[n] != after[n]} == {"registres_maillons", "mutations_appliquees"}
    assert set(after) == TABLES_SQLITE and not after["artefacts"]
    stockage.liberer()
    replay = appeler(capacite_reelle(), args)
    assert replay == {**first, "rejoue": True}
    assert after == fx.tables()


def test_cap_sql_revocation_avant_rejeu_puis_restoration_exacte(monde):
    args = demande(fx.importer())
    first = appeler(capacite_reelle(), args)
    assert first["ok"] and first["resultat"]["accepte"]
    with stockage.transaction() as cnx:
        cnx.execute(update(PERSONNES).where(PERSONNES.c.identifiant == fx.ADMIN.personne).values(actif=False))
    revoked = fx.tables()
    response = appeler(capacite_reelle(), args)
    assert not response["ok"] and response["issue"] == "inconnue"
    assert revoked == fx.tables()
    with stockage.transaction() as cnx:
        cnx.execute(update(PERSONNES).where(PERSONNES.c.identifiant == fx.ADMIN.personne).values(actif=True))
    restored = fx.tables()
    assert appeler(capacite_reelle(), args) == {**first, "rejoue": True}
    assert restored == fx.tables()


def test_cap_sql_quota_cache_retient_confirmation_puis_exacte(monde):
    args = demande(fx.importer())
    first = appeler(capacite_reelle(), args)
    assert first["ok"] and first["resultat"]["accepte"]
    after = fx.tables()
    response = appeler(capacite_reelle(800), args)
    assert not response["ok"] and response["issue"] == "inconnue"
    assert "apercu" not in response and after == fx.tables()
    assert appeler(capacite_reelle(), args) == {**first, "rejoue": True}
    assert after == fx.tables()


def test_refus_metier_frais_perdu_rejoue_le_meme_refus_certain(monde):
    args = demande(fx.importer())
    args["snapshot_attendu"] = "0" * 64
    before = fx.tables()
    first = appeler(capacite_reelle(), args)
    assert first["ok"] and first["resultat"]["accepte"] is False, first
    assert first["resultat"]["verdict"]["code"] == "REJ-M1-RAPPEL-SNAPSHOT-PERIME"
    after = fx.tables()
    assert {n for n in before if before[n] != after[n]} == {"mutations_appliquees"}
    stockage.liberer()
    assert appeler(capacite_reelle(), args) == {**first, "rejoue": True}
    assert after == fx.tables()


@pytest.mark.parametrize("suffixe", [
    "TRANSFERT-CLOS", "SNAPSHOT-PERIME", "DEJA-ATTRIBUE", "SORTIE-TROP-VOLUMINEUSE",
])
def test_cache_succes_remplace_par_refus_certain_reste_inconnu(monde, suffixe):
    from m1_front_office import rappels_appareil

    from opsys.stockage import codec
    from opsys.stockage.schema import MUTATIONS_APPLIQUEES

    args = demande(fx.importer())
    first = appeler(capacite_reelle(), args)
    assert first["ok"] and first["resultat"]["accepte"] is True
    negative = {"ok": True, "resultat": rappels_appareil.refus(rappels_appareil.Refus(suffixe))}
    with stockage.transaction() as cnx:
        cnx.execute(update(MUTATIONS_APPLIQUEES).where(
            MUTATIONS_APPLIQUEES.c.cle_idempotence == META.cle,
            MUTATIONS_APPLIQUEES.c.appareil == META.appareil,
        ).values(reponse=codec.encoder(negative)))
    corrupt = fx.tables()
    stockage.liberer()
    response = appeler(capacite_reelle(), args)
    assert response["ok"] is False and response["issue"] == "inconnue", response
    assert response["erreur"] == "REJ-M1-RAPPEL-REJEU-INCOHERENT"
    assert corrupt == fx.tables()


@pytest.mark.parametrize("acteur", [
    contexte.IdentiteAppelante("employe-fictif", "employee"),
    contexte.IdentiteAppelante("vendeur-fictif", "seller"),
    contexte.IdentiteAppelante("admin-rappel-fictif", "inconnu"),
    contexte.IdentiteAppelante("admin-rappel-fictif", "admin", source="console"),
])
def test_role_non_admis_avant_source_metier_et_claim(monde, acteur):
    _, patch = monde
    from m1_front_office import outils

    args = demande(fx.importer())
    reads, claims = [], []
    patch.setattr(outils, "_lire_registre_suivi_rappel", lambda: reads.append(True))
    patch.setattr(idempotence, "reclamer", lambda *a: claims.append(a))
    before = fx.tables()
    response = appeler(capacite_reelle(), args, acteur=acteur)
    assert not response["ok"] and response["issue"] == "inconnue"
    assert not reads and not claims and before == fx.tables()


def test_payload_autre_meme_uuid_conflit_sans_mutation(monde):
    args = demande(fx.importer())
    first = appeler(capacite_reelle(), args)
    assert first["ok"] and first["resultat"]["accepte"]
    after = fx.tables()
    response = appeler(capacite_reelle(), {**args, "snapshot_attendu": "0" * 64})
    assert not response["ok"] and response["erreur"] == "mutation_conflit"
    assert after == fx.tables()


@pytest.mark.parametrize("erreur", [ValueError, KeyError, RuntimeError])
def test_panne_apres_append_annule_aussi_claim_puis_meme_uuid(monde, erreur):
    _, patch = monde
    from m1_front_office import outils

    args = demande(fx.importer())
    original = outils._appliquer_suivi_rappel

    def panne(*a, **kw):
        original(*a, **kw)
        raise erreur("Panne FICTIVE après l'append réel.")

    before = fx.tables()
    patch.setattr(outils, "_appliquer_suivi_rappel", panne)
    with pytest.raises(RuntimeError):
        appeler(capacite_reelle(), args)
    assert before == fx.tables()
    patch.setattr(outils, "_appliquer_suivi_rappel", original)
    response = appeler(capacite_reelle(), args)
    assert response["ok"] and response["resultat"]["accepte"]
    after = fx.tables()
    assert appeler(capacite_reelle(), args) == {**response, "rejoue": True}
    assert after == fx.tables()
