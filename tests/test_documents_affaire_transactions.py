"""Transactions internes SQLite FICTIF, identité injectée ; ni Core/DEVICE ni RPC."""

from __future__ import annotations

import importlib
import json
import threading

import pytest
from m10_memoire import amont, registre
from sqlalchemy import delete, inspect, select, text, update

from opsys import approbations, contexte, idempotence, identite, stockage
from opsys.stockage import codec
from opsys.stockage.schema import APPROBATIONS, JOURNAL, MUTATIONS_APPLIQUEES, REGISTRES

FICTIF = True
AFFAIRE = "LEAD-DOCUMENT-FICTIF"
ACTEUR = contexte.IdentiteAppelante("admin_fictif", "admin", "appareil")
HORA = "2026-10-09T20:00:00.000-04:00"
CORPS = "CANARI_TRANSACTION_FICTIVE_Aé😀\r\nZ"
ARGS = {
    "affaire_id": AFFAIRE,
    "document_ref": None,
    "version_precedente": None,
    "titre": "Note FICTIVE",
    "corps": CORPS,
    "confidentialite": "INTERNAL",
}
META = idempotence.Meta("depot-fictif", "device-fictif", HORA)


def _t():
    return importlib.import_module("opsys.documents_affaire_transactions")


def _tables(cnx):
    return {
        n: sorted(map(tuple, cnx.execute(text('SELECT * FROM "' + n.replace('"', '""') + '"')).all()), key=repr)
        for n in inspect(cnx).get_table_names()
    }


@pytest.fixture
def monde(tmp_path, monkeypatch):
    monkeypatch.setenv("OPSYS_HOME", str(tmp_path / "home-fictif"))
    monkeypatch.setenv("OPSYS_BASE_URL", f"sqlite:///{tmp_path / 'instance-fictive.db'}")
    stockage.migrer()
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, ACTEUR.personne, "Admin FICTIF", "mot-de-passe-FICTIF-1234", ["admin"])
        charge = {
            "lead": {
                "schema_version": 2,
                "lead_id": AFFAIRE,
                "conversation_id": "texte-fictif",
                "contact": {"nom": "FICTIF", "telephone": "+15145550142", "courriel": "fictif@exemple.test"},
                "service": "gouttieres",
                "ville": "Repentigny",
                "urgence_declaree": True,
                "canal": "texte",
                "source": "sms",
                "utm": {},
                "campagne": "fictif",
            },
            "horodatage": "2026-10-09T19:00:00-04:00",
            "signal_id": "signal-fictif",
        }
        produit, refus = amont.memoriser(
            "m1.lead_qualifie", charge, registre.Registre(stockage.maillons("m10-memoire", "evenements"))
        )
        assert refus is None and produit["affaire"]["connue"] is True
    yield
    stockage.liberer()


def _call(cnx, operation="deposer", args=None, meta=META, quota=6000, mode="ombre", actor=ACTEUR):
    with cnx.begin_nested(), contexte.appele_par_appareil(actor):
        return _t().muter_document_m10(
            cnx, operation, ARGS if args is None else args, meta=meta, quota=quota, mode_manifeste=mode
        )


def _first():
    with stockage.transaction() as cnx:
        return _call(cnx)


def test_premier_effet_seulement_quatre_tables_et_ack_sans_corps(monde):
    with stockage.transaction() as cnx:
        avant = _tables(cnx)
        response = _call(cnx)
        assert set(response) == {"ok", "resultat", "rejoue"}
        assert response["ok"] is True and response["rejoue"] is False
        assert response["resultat"]["accepte"] is True
        ack = response["resultat"]["resultat"]
        assert set(ack) == {
            "version_schema",
            "operation",
            "document_ref",
            "reference",
            "version_source",
            "source_sha256",
            "auteur",
            "intention",
            "horodatage_appareil_declare",
            "horodatage",
        }
        assert CORPS not in json.dumps(response) and ack["reference"]["index"] == 0
        apres = _tables(cnx)
        assert {n for n in avant if avant[n] != apres[n]} == {
            "registres_maillons",
            "approbations",
            "journal",
            "mutations_appliquees",
        }
        assert len(apres["approbations"]) == len(apres["journal"]) == len(apres["mutations_appliquees"]) == 1
        print("TABLES_OBSERVEES", len(avant))
        stored = cnx.execute(select(MUTATIONS_APPLIQUEES.c.reponse)).scalar_one()
        assert codec.decoder(stored) == {"ok": True, "resultat": response["resultat"]}
        assert cnx.execute(select(APPROBATIONS.c.arguments)).scalar_one() == json.dumps(ARGS, ensure_ascii=False)


@pytest.mark.parametrize(
    "actor",
    [
        None,
        contexte.IdentiteAppelante(ACTEUR.personne, "employee", "appareil"),
        contexte.IdentiteAppelante(ACTEUR.personne, "admin", "console"),
    ],
)
def test_autorite_ambiante_rejetee_avant_sources_claim(monde, monkeypatch, actor):
    def interdit(*args):
        raise AssertionError("sources consultées avant admission")

    monkeypatch.setattr(_t(), "copier_registre_m10", interdit)
    with stockage.transaction() as cnx:
        avant = _tables(cnx)
        with pytest.raises(RuntimeError) as exc:
            _call(cnx, actor=actor)
        assert hasattr(exc.value, "code") and CORPS not in str(exc.value)
        assert _tables(cnx) == avant


@pytest.mark.parametrize("quota", [None, True, 0, -1, 1, 39, 40])
def test_quota_inadmissible_ou_minimum_ne_laisse_aucun_claim(monde, quota):
    with stockage.transaction() as cnx:
        avant = _tables(cnx)
        with pytest.raises(RuntimeError):
            _call(cnx, quota=quota)
        assert _tables(cnx) == avant


@pytest.mark.parametrize("mode", ["supervise", "autonome"])
def test_pas_de_writer_hors_ombre(monde, mode):
    with stockage.transaction() as cnx:
        avant = _tables(cnx)
        with pytest.raises(RuntimeError):
            _call(cnx, mode=mode)
        assert _tables(cnx) == avant


def test_rejeu_propre_apres_v2_retrait_et_reopen_sans_cas_ni_effet(monde):
    original = _first()
    ack = original["resultat"]["resultat"]
    with stockage.transaction() as cnx:
        v2 = _call(
            cnx,
            args={
                **ARGS,
                "document_ref": ack["document_ref"],
                "version_precedente": ack["version_source"],
                "corps": "version2 FICTIVE",
            },
            meta=idempotence.Meta("v2", META.appareil, HORA),
        )
        _call(
            cnx,
            "retirer",
            {
                "affaire_id": AFFAIRE,
                "document_ref": ack["document_ref"],
                "activation_attendue": None,
                "code_motif": "RETRAIT_ACCES",
            },
            meta=idempotence.Meta("retrait", META.appareil, HORA),
        )
        assert v2["resultat"]["resultat"]["version_source"]["index"] == 1
    stockage.liberer()
    with stockage.transaction() as cnx:
        avant = _tables(cnx)
        response = _call(cnx)
        assert response == {**original, "rejoue": True} and _tables(cnx) == avant


@pytest.mark.parametrize(
    "forme", [{"ok": True, "resultat": {"accepte": False}}, None, [], {"ok": False}, "JSON_CORROMPU"]
)
def test_cache_corrompu_ne_confirme_pas_un_refus_sans_effet(monde, forme):
    _first()
    with stockage.transaction() as cnx:
        cnx.execute(
            update(MUTATIONS_APPLIQUEES).values(reponse="{" if forme == "JSON_CORROMPU" else codec.encoder(forme))
        )
        avant = _tables(cnx)
        with pytest.raises(RuntimeError) as exc:
            _call(cnx)
        assert exc.value.code.endswith("CONFIRMATION-INCONNUE") and _tables(cnx) == avant


@pytest.mark.parametrize(
    "table,champ,valeur",
    [
        (APPROBATIONS, "resultat", '{"ok":true,"accepte":false}'),
        (APPROBATIONS, "arguments", "[]"),
        (JOURNAL, "details", '{"fictif":true}'),
        (JOURNAL, "cible", "autre-fictif"),
    ],
)
def test_propre_trace_raw_incoherente_ferme_confirmation(monde, table, champ, valeur):
    _first()
    with stockage.transaction() as cnx:
        cnx.execute(update(table).values(**{champ: valeur}))
        avant = _tables(cnx)
        with pytest.raises(RuntimeError) as exc:
            _call(cnx)
        assert exc.value.code.endswith("CONFIRMATION-INCONNUE") and _tables(cnx) == avant


def test_claim_perdu_ne_transforme_pas_paire_existante_en_frais(monde):
    _first()
    with stockage.transaction() as cnx:
        cnx.execute(delete(MUTATIONS_APPLIQUEES))
        avant = _tables(cnx)
        with pytest.raises(RuntimeError) as exc:
            _call(cnx)
        assert exc.value.code.endswith("CONFIRMATION-INCONNUE") and _tables(cnx) == avant


@pytest.mark.parametrize(
    "point", ["claim", "document", "APPJ", "liaison", "quota_post", "finalisation", "confirmation_finale"]
)
def test_panne_chaque_frontiere_annule_tout_puis_retry_meme_meta(monde, monkeypatch, point):
    t = _t()
    seen = {"calls": 0}
    if point == "claim":
        objet, name = t, "_reclamer_claim"
    elif point == "document":
        objet, name = t, "_ajouter_document"
    elif point == "APPJ":
        objet, name = t.approbations, "tracer_validation_documentaire_m10"
    elif point == "liaison":
        objet, name = t, "_ajouter_liaison"
    elif point == "quota_post":
        objet, name = t, "_borner_frames"
    elif point == "finalisation":
        objet, name = t.idempotence, "finaliser"
    else:
        objet, name = t, "_confirmer_own"
    original = getattr(objet, name)

    def panne(*args, **kwargs):
        result = original(*args, **kwargs)
        seen["calls"] += 1
        if point != "quota_post" or seen["calls"] == 2:
            raise KeyError(CORPS)
        return result

    monkeypatch.setattr(objet, name, panne)
    with stockage.transaction() as cnx:
        avant = _tables(cnx)
        with pytest.raises(RuntimeError) as exc:
            _call(cnx)
        assert not isinstance(exc.value, (ValueError, TypeError, KeyError)) and CORPS not in str(exc.value)
        assert _tables(cnx) == avant
    monkeypatch.setattr(objet, name, original)
    assert _first()["resultat"]["accepte"] is True


def test_une_revision_perimee_rolls_back_claim_frais(monde):
    first = _first()["resultat"]["resultat"]
    with stockage.transaction() as cnx:
        avant = _tables(cnx)
        bad = {
            **ARGS,
            "document_ref": first["document_ref"],
            "version_precedente": {**first["version_source"], "ligne_id": "0" * 64},
        }
        with pytest.raises(RuntimeError):
            _call(cnx, args=bad, meta=idempotence.Meta("revision-perimee", META.appareil, HORA))
        assert _tables(cnx) == avant


def test_concurrence_fichier_sqlite_deux_connexions_meme_meta(monde):
    barrier = threading.Barrier(2)
    outputs = []
    failures = []

    def worker():
        try:
            barrier.wait(timeout=10)
            with stockage.transaction() as cnx:
                outputs.append(_call(cnx))
        except BaseException as exc:
            failures.append(type(exc).__name__)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert not any(thread.is_alive() for thread in threads) and failures == []
    assert sorted(r["rejoue"] for r in outputs) == [False, True]
    assert outputs[0]["resultat"] == outputs[1]["resultat"]
    with stockage.transaction() as cnx:
        assert len(cnx.execute(select(APPROBATIONS)).all()) == len(cnx.execute(select(JOURNAL)).all()) == 1


def test_deux_uuid_meme_corps_hora_ne_peuvent_partager_une_pk_app(monde):
    from m10_memoire import encodage

    _first()
    other = idempotence.Meta("deuxieme-fictif", META.appareil, HORA)
    with stockage.transaction() as cnx:
        _call(cnx, meta=other)
        rows = (
            cnx.execute(
                select(REGISTRES).where(REGISTRES.c.registre == "documents_affaire_traces").order_by(REGISTRES.c.rang)
            )
            .mappings()
            .all()
        )
        first, second = [codec.decoder(r["maillon"]) for r in rows]
        second["trace"].update(
            {k: first["trace"][k] for k in ("approbation_id", "cree_le_approbation", "decide_le_approbation")}
        )
        cnx.execute(
            update(JOURNAL)
            .where(JOURNAL.c.id == second["trace"]["journal_id"])
            .values(cible=first["trace"]["approbation_id"])
        )
        payload = {k: v for k, v in second.items() if k not in ("ligne_id", "precedent_ligne_id")}
        second["ligne_id"] = encodage.empreinte(payload, second["precedent_ligne_id"])
        cnx.execute(
            update(REGISTRES)
            .where(REGISTRES.c.registre == "documents_affaire_traces", REGISTRES.c.rang == 1)
            .values(maillon=codec.encoder(second))
        )
        avant = _tables(cnx)
        with pytest.raises(RuntimeError) as exc:
            _call(cnx, meta=other)
        assert exc.value.code.endswith("CONFIRMATION-INCONNUE") and _tables(cnx) == avant


def test_json_claim_duplique_physique_ne_peut_devenir_positif(monde):
    original = _first()
    stored = json.dumps({"ok": True, "resultat": original["resultat"]}, ensure_ascii=False)
    duplique = '{"ok":false,' + stored[1:]
    with stockage.transaction() as cnx:
        cnx.execute(update(MUTATIONS_APPLIQUEES).values(reponse=duplique))
        avant = _tables(cnx)
        with pytest.raises(RuntimeError) as exc:
            _call(cnx)
        assert exc.value.code.endswith("CONFIRMATION-INCONNUE") and _tables(cnx) == avant


@pytest.mark.parametrize(
    "champ,valeur",
    [
        ("outil", "autre"),
        ("empreinte_arguments", "0" * 64),
        ("horodatage_appareil", "2026-10-08T20:00:00.000-04:00"),
        ("statut", "en_cours"),
    ],
)
def test_metadata_claim_refusee_avant_codec_et_snapshot(monde, monkeypatch, champ, valeur):
    _first()
    with stockage.transaction() as cnx:
        cnx.execute(update(MUTATIONS_APPLIQUEES).values(**{champ: valeur}))
        avant = _tables(cnx)
        raw_claim = cnx.execute(select(MUTATIONS_APPLIQUEES.c.reponse)).scalar_one()
        touched = []
        original = _t().codec.decoder

        def decode(raw):
            if raw == raw_claim:
                touched.append(raw)
            return original(raw)

        monkeypatch.setattr(_t().codec, "decoder", decode)
        with pytest.raises(RuntimeError) as exc:
            _call(cnx)
        assert exc.value.code.endswith("CONFIRMATION-INCONNUE")
        assert touched == [] and _tables(cnx) == avant


@pytest.mark.parametrize(
    "table,champ,cap",
    [
        (MUTATIONS_APPLIQUEES, "reponse", 8192),
        (APPROBATIONS, "arguments", 16384),
        (APPROBATIONS, "resultat", 512),
        (JOURNAL, "details", 4096),
    ],
)
@pytest.mark.parametrize("delta", [-1, 0, 1])
def test_borne_raw_sql_exacte_independante_quota_rpc(monde, table, champ, cap, delta):
    original = _first()
    with stockage.transaction() as cnx:
        valeur = cnx.execute(select(table.c[champ])).scalar_one()
        padded = valeur + " " * (cap + delta - len(valeur.encode("utf-8")))
        assert len(padded.encode("utf-8")) == cap + delta
        cnx.execute(update(table).values(**{champ: padded}))
        avant = _tables(cnx)
        if delta <= 0:
            assert _call(cnx) == {**original, "rejoue": True}
        else:
            with pytest.raises(RuntimeError) as exc:
                _call(cnx)
            assert exc.value.code.endswith("CONFIRMATION-INCONNUE")
        assert _tables(cnx) == avant


def test_collision_acquisition_reload_propre_sans_plan_frais(monde, monkeypatch):
    """Lectures initiales simulées anciennes, vraie collision SQL PK, pas course SQLite."""
    original = _first()
    t = _t()
    lire = t._claim
    copier = t._copies
    first = True
    anciennes = {t._DOC, t._LIENS}
    preparations = []
    preparer = t.domaine.preparer_depot

    def absence_initiale(cnx, meta):
        nonlocal first
        if first:
            first = False
            return None
        return lire(cnx, meta)

    def copies_initiales_anciennes(cnx, nom):
        if nom in anciennes:
            anciennes.remove(nom)
            return []
        return copier(cnx, nom)

    def preparation(*args):
        preparations.append(True)
        return preparer(*args)

    def aucun_append(*args):
        raise AssertionError("le candidat préparé est abandonné après collision")

    monkeypatch.setattr(t, "_claim", absence_initiale)
    monkeypatch.setattr(t, "_copies", copies_initiales_anciennes)
    monkeypatch.setattr(t.domaine, "preparer_depot", preparation)
    monkeypatch.setattr(t, "_ajouter_document", aucun_append)
    with stockage.transaction() as cnx:
        avant = _tables(cnx)
        assert _call(cnx) == {**original, "rejoue": True}
        assert _tables(cnx) == avant and cnx.in_transaction()
        assert preparations == [True] and anciennes == set()


def test_reclamation_nommee_meme_insert_socle_et_ne_decode_pas(monde, monkeypatch):
    import datetime as dt

    now = dt.datetime(2026, 10, 10, tzinfo=dt.UTC)

    def aucun_decode(*args):
        raise AssertionError("cache décodé durant acquisition")

    monkeypatch.setattr(_t().codec, "decoder", aucun_decode)
    with stockage.transaction() as cnx, cnx.begin_nested():
        assert _t()._reclamer_claim(cnx, META, "m10_deposer_version_document_appareil", ARGS, now).rejouee is False
        row = dict(cnx.execute(select(MUTATIONS_APPLIQUEES)).mappings().one())
        assert row == {
            "appareil": META.appareil,
            "cle_idempotence": META.cle,
            "outil": "m10_deposer_version_document_appareil",
            "empreinte_arguments": idempotence.empreinte_arguments(ARGS),
            "reponse": "null",
            "horodatage_appareil": HORA,
            "recu_le": "2026-10-10T00:00:00+00:00",
            "statut": "en_cours",
        }
        assert _t()._reclamer_claim(cnx, META, row["outil"], ARGS, now).rejouee is True
        assert dict(cnx.execute(select(MUTATIONS_APPLIQUEES)).mappings().one()) == row


@pytest.mark.parametrize("column,cap", [("reponse", 8192), ("appareil", 512), ("outil", 512)])
def test_case_sql_masque_tout_avant_reception_python(monde, column, cap):
    _first()
    with stockage.transaction() as cnx:
        # BLOB valide UTF8 n'est pas TEXT. La sélection ne retourne aucun payload.
        if column == "appareil":
            valeur = META.appareil + " " * (cap + 1 - len(META.appareil))
            cnx.execute(update(MUTATIONS_APPLIQUEES).values(appareil=valeur))
            cible = idempotence.Meta(META.cle, valeur, HORA)
        else:
            cnx.execute(update(MUTATIONS_APPLIQUEES).values(**{column: b"x" * (cap + 1)}))
            cible = META
        row = _t()._claim(cnx, cible)
        assert row["raw_admis"] is False
        assert all(v is None for k, v in row.items() if k != "raw_admis")


@pytest.mark.parametrize("cache", [False, True])
def test_retrait_sql_admin_avant_corpus_et_claim(monde, monkeypatch, cache):
    if cache:
        _first()
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, ACTEUR.personne, "admin")
        avant = _tables(cnx)

        def interdit(*args):
            raise AssertionError("corpus consulté sans rôle SQL")

        monkeypatch.setattr(_t(), "copier_registre_m10", interdit)
        with pytest.raises(RuntimeError) as exc:
            _call(cnx)
        assert exc.value.code.endswith("AUTORITE-INVALIDE") and _tables(cnx) == avant


def test_changement_mode_sql_interdit_restitution_cached(monde):
    _first()
    with stockage.transaction() as cnx:
        approbations.fixer_mode(cnx, "m10-memoire", "autonome", ACTEUR.personne)
        avant = _tables(cnx)
        with pytest.raises(RuntimeError) as exc:
            _call(cnx)
        assert exc.value.code.endswith("MODE-NON-ADMIS") and _tables(cnx) == avant


@pytest.mark.parametrize("champ", ["cle", "appareil"])
def test_meta_128_points_utf8_et_129_refuse_sans_effet(monde, champ):
    values = {"cle": META.cle, "appareil": META.appareil, "horodatage_appareil": HORA}
    values[champ] = "😀" * 128
    meta = idempotence.Meta(**values)
    with stockage.transaction() as cnx:
        original = _call(cnx, meta=meta, quota=20000)
        assert original["resultat"]["resultat"]["intention"][champ] == values[champ]
        avant = _tables(cnx)
        assert _call(cnx, meta=meta, quota=20000) == {**original, "rejoue": True}
        bad = idempotence.Meta(**{**values, champ: "😀" * 129})
        with pytest.raises(RuntimeError) as exc:
            _call(cnx, meta=bad, quota=20000)
        assert exc.value.code.endswith("FORME-INVALIDE") and _tables(cnx) == avant


def test_quota_exact_les_deux_flags_et_reduction_cached(monde):
    original = _first()
    framefalse = {**original, "rejoue": False}
    frametrue = {**original, "rejoue": True}
    # Oracle stdlib, séparé du sérialiseur de borne du domaine.
    taillefalse = len(json.dumps(framefalse, ensure_ascii=False, allow_nan=False))
    tailletrue = len(json.dumps(frametrue, ensure_ascii=False, allow_nan=False))
    assert taillefalse == tailletrue + 1
    with stockage.transaction() as cnx:
        avant = _tables(cnx)
        assert _call(cnx, quota=taillefalse) == frametrue
        with pytest.raises(RuntimeError) as exc:
            _call(cnx, quota=tailletrue)
        assert exc.value.code.endswith("CONFIRMATION-INCONNUE") and _tables(cnx) == avant
        fresh = idempotence.Meta(META.cle.upper(), META.appareil, HORA)
        with pytest.raises(RuntimeError) as exc:
            _call(cnx, meta=fresh, quota=tailletrue)
        assert exc.value.code.endswith("QUOTA-DEPASSE") and _tables(cnx) == avant


def test_heure_originale_et_corps_immuables_pour_meme_cle(monde):
    _first()
    with stockage.transaction() as cnx:
        avant = _tables(cnx)
        for args, meta in [
            (ARGS, idempotence.Meta(META.cle, META.appareil, "2026-10-09T20:01:00.000-04:00")),
            ({**ARGS, "corps": "autre FICTIF"}, META),
        ]:
            with pytest.raises(RuntimeError) as exc:
                _call(cnx, args=args, meta=meta)
            assert exc.value.code.endswith("CONFIRMATION-INCONNUE") and _tables(cnx) == avant


def test_une_cle_identique_deux_appareils_reste_distincte(monde):
    first = _first()
    other = idempotence.Meta(META.cle, "device-autre-fictif", HORA)
    with stockage.transaction() as cnx:
        second = _call(cnx, meta=other)
        assert second["rejoue"] is False
        assert second["resultat"]["resultat"]["document_ref"] != first["resultat"]["resultat"]["document_ref"]
        avant = _tables(cnx)
        assert _call(cnx, meta=other) == {**second, "rejoue": True} and _tables(cnx) == avant


def test_affaire_absente_ne_cree_pas_claim(monde):
    with stockage.transaction() as cnx:
        avant = _tables(cnx)
        with pytest.raises(RuntimeError) as exc:
            _call(cnx, args={**ARGS, "affaire_id": "LEAD-INCONNU-FICTIF"})
        assert exc.value.code.endswith("AFFAIRE-INCONNUE") and _tables(cnx) == avant


def test_connexion_sans_savepoint_et_etrangere_avant_corpus(monde, monkeypatch):
    def interdit(*args):
        raise AssertionError("corpus hors transaction canonique")

    monkeypatch.setattr(_t(), "copier_registre_m10", interdit)
    with stockage.transaction() as cnx, contexte.appele_par_appareil(ACTEUR):
        avant = _tables(cnx)
        with pytest.raises(RuntimeError) as exc:
            _t().muter_document_m10(cnx, "deposer", ARGS, meta=META, quota=6000, mode_manifeste="ombre")
        assert exc.value.code.endswith("CONNEXION-INVALIDE") and _tables(cnx) == avant
        from sqlalchemy import create_engine

        engine = create_engine("sqlite:///:memory:")
        with engine.connect() as autre, autre.begin(), autre.begin_nested():
            with pytest.raises(RuntimeError) as exc:
                _t().muter_document_m10(autre, "deposer", ARGS, meta=META, quota=6000, mode_manifeste="ombre")
            assert exc.value.code.endswith("CONNEXION-INVALIDE")


def test_activation_et_replay_propre_apres_retrait(monde):
    depot = _first()["resultat"]["resultat"]
    activation = {
        "affaire_id": AFFAIRE,
        "document_ref": depot["document_ref"],
        "version_source": depot["version_source"],
        "activation_attendue": None,
    }
    meta = idempotence.Meta("activation-fictive", META.appareil, HORA)
    with stockage.transaction() as cnx:
        active = _call(cnx, "activer", activation, meta=meta)
        _call(
            cnx,
            "retirer",
            {
                "affaire_id": AFFAIRE,
                "document_ref": depot["document_ref"],
                "activation_attendue": active["resultat"]["resultat"]["reference"],
                "code_motif": "RETRAIT_ACCES",
            },
            meta=idempotence.Meta("retire-active", META.appareil, HORA),
        )
        avant = _tables(cnx)
        assert _call(cnx, "activer", activation, meta=meta) == {**active, "rejoue": True} and _tables(cnx) == avant


@pytest.mark.parametrize(
    "args",
    [None, list(ARGS.items()), {**ARGS, "corps": float("nan")}, {**ARGS, "titre": "\ud800"}, {**ARGS, "role": "admin"}],
)
def test_commande_inadmissible_non_normalisee_avant_claim(monde, args):
    with stockage.transaction() as cnx:
        avant = _tables(cnx)
        with cnx.begin_nested(), contexte.appele_par_appareil(ACTEUR), pytest.raises(RuntimeError) as exc:
            _t().muter_document_m10(cnx, "deposer", args, meta=META, quota=6000, mode_manifeste="ombre")
        assert exc.value.code.endswith("FORME-INVALIDE") and _tables(cnx) == avant


@pytest.mark.parametrize(
    "texte",
    ['{"ok":NaN}', '{"ok":Infinity}', '{"ok":-Infinity}', '{"ok":true,"resultat":{"accepte":false,"accepte":true}}'],
)
def test_json_claim_non_fini_ou_duplique_refuse_avant_codec(monde, monkeypatch, texte):
    _first()
    with stockage.transaction() as cnx:
        cnx.execute(update(MUTATIONS_APPLIQUEES).values(reponse=texte))
        avant = _tables(cnx)
        seen = []
        decode = _t().codec.decoder

        def observer(raw):
            if raw == texte:
                seen.append(raw)
            return decode(raw)

        monkeypatch.setattr(_t().codec, "decoder", observer)
        with pytest.raises(RuntimeError) as exc:
            _call(cnx)
        assert exc.value.code.endswith("CONFIRMATION-INCONNUE") and seen == [] and _tables(cnx) == avant


def test_concurrence_revision_unique_deux_uuid_sur_sqlite_fichier(monde):
    premier = _first()["resultat"]["resultat"]
    correction = {
        **ARGS,
        "document_ref": premier["document_ref"],
        "version_precedente": premier["version_source"],
        "corps": "correction FICTIVE",
    }
    barriere = threading.Barrier(2)
    reponses = []
    refus = []
    bugs = []

    def writer(cle):
        try:
            barriere.wait(timeout=10)
            with stockage.transaction() as cnx:
                reponses.append(_call(cnx, args=correction, meta=idempotence.Meta(cle, META.appareil, HORA)))
        except _t().ErreurTransactionDocumentaire as exc:
            refus.append(exc.code)
        except BaseException as exc:
            bugs.append(type(exc).__name__)

    threads = [threading.Thread(target=writer, args=(cle,)) for cle in ("correction-A", "correction-B")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=15)
    assert not any(t.is_alive() for t in threads) and not bugs
    assert len(reponses) == 1 and reponses[0]["rejoue"] is False
    assert refus == ["REJ-M10-TRANSACTION-PRECONDITION-REFUSEE"]
    with stockage.transaction() as cnx:
        assert len(cnx.execute(select(APPROBATIONS)).all()) == len(cnx.execute(select(JOURNAL)).all()) == 2
        assert len(cnx.execute(select(MUTATIONS_APPLIQUEES)).all()) == 2
        assert (
            len(
                cnx.execute(
                    select(REGISTRES).where(REGISTRES.c.registre.in_(["documents_affaire", "documents_affaire_traces"]))
                ).all()
            )
            == 4
        )


def test_autorite_sql_revoquee_apres_append_annule_effect_et_retry(monde, monkeypatch):
    t = _t()
    original = t._ajouter_document

    def retirer(cnx, candidat, rang):
        original(cnx, candidat, rang)
        identite.retirer_role(cnx, ACTEUR.personne, "admin")

    monkeypatch.setattr(t, "_ajouter_document", retirer)
    with stockage.transaction() as cnx:
        avant = _tables(cnx)
        with pytest.raises(RuntimeError) as exc:
            _call(cnx)
        assert exc.value.code.endswith("AUTORITE-INVALIDE") and _tables(cnx) == avant
    monkeypatch.setattr(t, "_ajouter_document", original)
    assert _first()["rejoue"] is False


@pytest.mark.parametrize("budget", ["minimum40", "frame_false_moins1"])
def test_preflight_quota_aucune_tentative_insert_claim(monde, budget):
    from sqlalchemy import event

    original = _first()
    taille = len(json.dumps({**original, "rejoue": False}, ensure_ascii=False, allow_nan=False))
    quota = 40 if budget == "minimum40" else taille - 1
    meta = idempotence.Meta(META.cle.upper(), META.appareil, HORA)
    with stockage.transaction() as cnx:
        avant = _tables(cnx)
        claims = []

        def observer(_cnx, _cursor, statement, _params, _context, _many):
            if statement.lstrip().upper().startswith("INSERT INTO MUTATIONS_APPLIQUEES"):
                claims.append(True)

        event.listen(cnx.engine, "before_cursor_execute", observer)
        try:
            with pytest.raises(RuntimeError) as exc:
                _call(cnx, meta=meta, quota=quota)
        finally:
            event.remove(cnx.engine, "before_cursor_execute", observer)
        assert exc.value.code.endswith("QUOTA-DEPASSE") and _tables(cnx) == avant
        assert claims == [], "un quota refusé ne tente pas même un claim rollbacké"


@pytest.mark.parametrize("motif", ["motif parasite FICTIF", "   "])
def test_app_motif_demande_non_vide_ne_confirme_pas_own(monde, motif):
    _first()
    with stockage.transaction() as cnx:
        cnx.execute(update(APPROBATIONS).values(motif_demande=motif))
        avant = _tables(cnx)
        with pytest.raises(RuntimeError) as exc:
            _call(cnx)
        assert exc.value.code.endswith("CONFIRMATION-INCONNUE") and _tables(cnx) == avant


def test_app_motif_demande_raw_513_masque_avant_json_arguments(monde, monkeypatch):
    _first()
    with stockage.transaction() as cnx:
        arguments = cnx.execute(select(APPROBATIONS.c.arguments)).scalar_one()
        cnx.execute(update(APPROBATIONS).values(motif_demande="x" * 513))
        avant = _tables(cnx)
        seen = []
        decoder = _t()._json

        def observer(raw):
            if raw == arguments:
                seen.append(True)
            return decoder(raw)

        monkeypatch.setattr(_t(), "_json", observer)
        with pytest.raises(RuntimeError) as exc:
            _call(cnx)
        assert exc.value.code.endswith("CONFIRMATION-INCONNUE") and seen == [] and _tables(cnx) == avant
