"""FICTIF : vrais imports M1, identités SQL et SQLite fichier ; aucun HTTP/fournisseur."""

from __future__ import annotations

import copy
import datetime as dt
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from threading import Barrier
from uuid import uuid4

import pytest
from m1_front_office import outils
from m1_front_office.registre import Registre
from sqlalchemy import event, text, update

from opsys import contexte, idempotence, identite, stockage, taxonomie
from opsys.outils import Autonomie, Niveau, executer_atomique
from opsys.stockage.schema import REGISTRES

LISTE = "m1_lister_rappels_appareil"
PRISE = "m1_prendre_en_charge_rappel_appareil"
ADMIN = contexte.IdentiteAppelante("admin-rappel-fictif", "admin")
HEURE = "2026-10-09T04:00:00+00:00"
APP = "APP-RAPPEL-FICTIF"


def outil(nom):
    o = next((o for o in outils.outils() if o.nom == nom), None)
    assert o is not None, "nouvelle façade M1 absente"
    return o


@pytest.fixture
def monde(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    home = tmp_path / "home"
    home.mkdir(mode=0o700)
    monkeypatch.setenv("OPSYS_HOME", str(home))
    monkeypatch.setenv(stockage.ENV_URL, f"sqlite:///{tmp_path / 'fictif.db'}")
    stockage.migrer()
    outils.utiliser_stockage_durable()
    taxonomie.enregistrer_zone_desservie(["Laval"])
    taxonomie.enregistrer_services(["gouttieres"])
    monkeypatch.setattr(identite, "hacher_mot_de_passe", lambda _: "FICTIF-non-authentifiable")
    with stockage.transaction() as cnx:
        for p, roles in [
            (ADMIN.personne, ["admin"]),
            ("autre-admin-fictif", ["admin"]),
            ("employe-fictif", ["employee"]),
            ("vendeur-fictif", ["seller"]),
        ]:
            identite.creer_personne(cnx, p, "Personne FICTIVE", "secret-fictif", roles)
    yield tmp_path, monkeypatch
    stockage.liberer()
    outils.utiliser_stockage_durable()


def importer(n=0, **changes):
    args = {
        "source": "Journal FICTIF",
        "evenement_id": f"evt-fictif-{n}",
        "appel_id": f"appel-fictif-{n}",
        "recu_le": "2026-10-08T17:00:00+00:00",
        "telephone": f"+1514555{n:04}",
        "statut": "manque",
        **changes,
    }
    with stockage.transaction():
        r = outils.importer_appel_manuellement(**args)
    assert r["accepte"] and r["tache_rappel"] is not None
    return r["tache_rappel"]["transfert_id"]


def tables():
    with stockage.transaction() as cnx:
        names = (
            cnx.execute(
                text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
            )
            .scalars()
            .all()
        )
        return {n: [dict(r) for r in cnx.execute(text(f'SELECT * FROM "{n}"')).mappings()] for n in names}


@contextmanager
def mutation(meta=None, actor=ADMIN, limite=5400):
    outil(PRISE)  # oracle absence avant tout import du module futur
    from m1_front_office import rappels_appareil as r

    meta = meta or idempotence.Meta(str(uuid4()), APP, HEURE)
    h = contexte.HorodatageAppareil(
        meta.appareil, dt.datetime.fromisoformat(meta.horodatage_appareil), dt.datetime.fromisoformat(HEURE)
    )
    with (
        contexte.appele_par_appareil(actor),
        contexte.receptionne_de(h),
        contexte.sortie_bornee(limite),
        r.contexte_mutation(meta),
    ):
        yield meta


def lister(**args):
    with contexte.appele_par_appareil(ADMIN):
        return executer_atomique(outil(LISTE), {"apres_transfert_id": None, "taille_page": 8, **args})


def prendre(t, snapshot=None, **kwargs):
    if snapshot is None:
        snapshot = next(x for x in lister()["resultat"]["resultat"]["rappels"] if x["transfert_id"] == t)[
            "suivi_rappel"
        ]["snapshot_suivi"]
    with mutation(**kwargs):
        return executer_atomique(outil(PRISE), {"transfert_id": t, "snapshot_attendu": snapshot})


def test_outils_appendes_niveaux_et_console_inchangee():
    noms = [o.nom for o in outils.outils()]
    assert noms[-2:] == [LISTE, PRISE]
    assert outil(LISTE).autonomie is Autonomie.T0 and outil(LISTE).niveau_effectif is Niveau.N0
    assert outil(PRISE).autonomie is Autonomie.T1 and outil(PRISE).niveau_effectif is Niveau.N2
    assert outil(PRISE).portee_contexte is None
    assert outil(LISTE).roles_appareil == outil(PRISE).roles_appareil == frozenset({"admin"})
    assert set(outil(PRISE).parametres["properties"]) == {"transfert_id", "snapshot_attendu"}
    assert not outil(PRISE).parametres["additionalProperties"]
    ancien = outil("m1_consigner_suivi_rappel")
    assert ancien.niveau_effectif is Niveau.N2 and ancien.roles_appareil == frozenset()


def test_liste_reelle_privee_et_49_tables_inchangees(monde):
    t = importer()
    before = tables()
    r = lister()
    assert r["ok"] and r["resultat"]["accepte"], r
    dto = r["resultat"]["resultat"]
    ligne = dto["rappels"][0]
    assert ligne["transfert_id"] == t and ligne["canal"] == "telephone"
    assert ligne["nombre_sources"] == 1 and ligne["derniere_source"]["statut"] == "manque"
    assert ligne["suivi_rappel"]["responsable"] is None and ligne["lead_id"] is None
    assert set(ligne) == {
        "transfert_id",
        "conversation_id",
        "lead_id",
        "canal",
        "ouvert_le",
        "nombre_sources",
        "derniere_source",
        "suivi_rappel",
    }
    assert "+1514" not in json.dumps(r) and "Journal FICTIF" not in json.dumps(r)
    assert before == tables() and len(before) == 49


def test_keyset_current_total_curseur_exclusif_et_defauts(monde):
    ids = sorted(importer(n) for n in range(10))
    a = lister(taille_page=3)["resultat"]["resultat"]
    b = lister(apres_transfert_id=a["page"]["apres_suivant"], taille_page=8)["resultat"]["resultat"]
    assert [x["transfert_id"] for x in a["rappels"]] == ids[:3]
    assert [x["transfert_id"] for x in b["rappels"]] == ids[3:]
    assert a["page"]["total"] == b["page"]["total"] == 10
    assert a["page"]["reste"] == 7 and b["page"]["reste"] == 0
    assert b["page"]["apres_suivant"] is None
    with contexte.appele_par_appareil(ADMIN):
        assert executer_atomique(outil(LISTE), {})["resultat"]["resultat"]["page"]["taille_page"] == 8


@pytest.mark.parametrize(
    "args",
    [
        {"taille_page": True},
        {"taille_page": 0},
        {"taille_page": 9},
        {"apres_transfert_id": "tr-" + "a" * 20 + "\n"},
        {"apres_transfert_id": 0},
    ],
)
def test_pages_invalides_ne_lisent_pas_le_registre(monde, args):
    _, patch = monde
    before = tables()
    calls = []
    patch.setattr(outils, "_lire_registre_suivi_rappel", lambda: calls.append(1))
    with contexte.appele_par_appareil(ADMIN):
        r = outils.lister_rappels_appareil(**args)
    assert not r["accepte"] and calls == [] and before == tables()


@pytest.mark.parametrize(
    "actor",
    [
        None,
        contexte.IdentiteAppelante("inconnu-fictif", "admin"),
        contexte.IdentiteAppelante("employe-fictif", "employee"),
        contexte.IdentiteAppelante("vendeur-fictif", "seller"),
        contexte.IdentiteAppelante("employe-fictif", "admin"),
        contexte.IdentiteAppelante(ADMIN.personne, "admin", source="console"),
    ],
)
def test_garde_admin_appareil_avant_select_metier(monde, actor):
    outil(LISTE)
    from m1_front_office import rappels_appareil as r

    calls = []

    def observer(_c, _cur, sql, _p, _ctx, _many):
        if "registres_maillons" in sql.lower():
            calls.append(sql)

    with stockage.transaction() as cnx, contexte.appele_par_appareil(actor):
        event.listen(cnx, "before_cursor_execute", observer)
        with pytest.raises(r.Refus):
            outils.autoriser_prise_rappel_appareil({"apres_transfert_id": None, "taille_page": 8}, nom=LISTE)
    assert not calls


def test_retrait_role_avant_source_et_hors_transaction(monde):
    outil(LISTE)
    from m1_front_office import rappels_appareil as r

    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, ADMIN.personne, "admin")
    with stockage.transaction(), contexte.appele_par_appareil(ADMIN), pytest.raises(r.Refus):
        outils.autoriser_prise_rappel_appareil({}, nom=LISTE)
    with contexte.appele_par_appareil(ADMIN):
        assert not outils.lister_rappels_appareil()["accepte"]


def test_ack_ferme_maillon_meta_et_heures_serveur(monde):
    t = importer()
    meta = idempotence.Meta(str(uuid4()), APP, "2026-10-08T23:05:01-04:00")
    a = prendre(t, meta=meta)
    assert a["ok"] and a["resultat"]["accepte"], a
    ack = a["resultat"]["resultat"]
    assert set(ack) == {
        "version",
        "transfert_id",
        "action",
        "ligne_id",
        "precedent_ligne_id",
        "index",
        "snapshot_attendu",
        "par",
        "role",
        "voie",
        "appareil",
        "intention_uuid",
        "recu_le_serveur",
        "horodatage_appareil",
        "suivi_rappel",
    }
    assert (
        ack["appareil"] == APP
        and ack["intention_uuid"] == meta.cle
        and ack["horodatage_appareil"] == meta.horodatage_appareil
    )
    assert ack["recu_le_serveur"] == HEURE and ack["par"] == ADMIN.personne and ack["role"] == "admin"
    assert ack["suivi_rappel"]["responsable"] == ADMIN.personne
    with stockage.transaction():
        lignes = outils._obtenir_registre().lire()
        assert lignes[ack["index"]]["ligne_id"] == ack["ligne_id"]
        assert lignes[ack["index"]]["precedent_ligne_id"] == ack["precedent_ligne_id"]
        assert lignes[ack["index"]]["snapshot_attendu"] == ack["snapshot_attendu"]
    assert lister()["resultat"]["resultat"]["rappels"][0]["suivi_rappel"]["responsable"] == ADMIN.personne


def test_frais_perime_deja_attribue_et_meta_absente_sans_ecriture(monde):
    t = importer()
    snapshot = lister()["resultat"]["resultat"]["rappels"][0]["suivi_rappel"]["snapshot_suivi"]
    before = tables()
    r = prendre(t, "0" * 64)
    assert not r["resultat"]["accepte"] and before == tables()
    assert prendre(t, snapshot)["resultat"]["accepte"]
    before = tables()
    assert not prendre(t, snapshot)["resultat"]["accepte"]
    assert before == tables()
    with contexte.appele_par_appareil(ADMIN):
        assert not executer_atomique(outil(PRISE), {"transfert_id": t, "snapshot_attendu": snapshot})["resultat"][
            "accepte"
        ]
    assert before == tables()


def test_rejeu_propre_apres_tentative_et_cloture_et_restart(monde):
    t = importer()
    args = {
        "transfert_id": t,
        "snapshot_attendu": lister()["resultat"]["resultat"]["rappels"][0]["suivi_rappel"]["snapshot_suivi"],
    }
    meta = idempotence.Meta(str(uuid4()), APP, HEURE)
    ack = prendre(t, args["snapshot_attendu"], meta=meta)
    actor = contexte.IdentiteAppelante(ADMIN.personne, "admin", source="console")
    with stockage.transaction(), contexte.appele_par_appareil(actor):
        follow = outils.consigner_suivi_rappel(
            t,
            "tentative_sans_contact",
            ack["resultat"]["resultat"]["suivi_rappel"]["snapshot_suivi"],
            HEURE,
            "2026-10-10T04:00:00+00:00",
        )
        assert follow["accepte"]
        assert outils.clore_transfert(t, "FICTIF : suivi terminé humainement", HEURE)["accepte"]
    stockage.liberer()
    before = tables()
    with stockage.transaction(), mutation(meta=meta):
        outils.verifier_rejeu_prise_rappel_appareil(args, ack)
    assert before == tables() and lister()["resultat"]["resultat"]["rappels"] == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("appareil", "AUTRE"),
        ("intention_uuid", "0" * 36),
        ("par", "autre-admin-fictif"),
        ("snapshot_attendu", "f" * 64),
        ("index", 0),
        ("ligne_id", "0" * 64),
        ("recu_le_serveur", "2026-10-10T04:00:00+00:00"),
    ],
)
def test_rejeu_ack_altere_refuse_sans_effet(monde, field, value):
    t = importer()
    args = {
        "transfert_id": t,
        "snapshot_attendu": lister()["resultat"]["resultat"]["rappels"][0]["suivi_rappel"]["snapshot_suivi"],
    }
    meta = idempotence.Meta(str(uuid4()), APP, HEURE)
    ack = prendre(t, args["snapshot_attendu"], meta=meta)
    broken = copy.deepcopy(ack)
    broken["resultat"]["resultat"][field] = value
    before = tables()
    from m1_front_office import rappels_appareil as r

    with stockage.transaction(), mutation(meta=meta), pytest.raises(r.Refus):
        outils.verifier_rejeu_prise_rappel_appareil(args, broken)
    assert before == tables()


def test_sources_revendiquees_corrompues_chaine_reempreintee_non_filtrees(monde):
    t = importer()
    importer(1)
    with stockage.transaction() as cnx:
        lignes = outils._obtenir_registre().lire()
        source = next(
            x
            for x in lignes
            if x.get("type_entree") == "appel_importe" and x["reponse"]["tache_rappel"]["transfert_id"] == t
        )
        source["reponse"]["appel_id"] = "AUTRE-FICTIF"
        reg = Registre()
        for ligne in lignes:
            reg.ajouter({k: v for k, v in ligne.items() if k not in {"ligne_id", "precedent_ligne_id"}})
        for idx, ligne in enumerate(reg.lire()):
            cnx.execute(
                update(REGISTRES)
                .where(
                    REGISTRES.c.departement == "m01-front-office",
                    REGISTRES.c.registre == "principal",
                    REGISTRES.c.rang == idx,
                )
                .values(maillon=stockage.codec.encoder(ligne))
            )
    before = tables()
    r = lister()
    assert not r["resultat"]["accepte"]
    assert before == tables()


def test_prevu_ordinary_transfert_sans_source_exclu_et_voicemail_canonique_admis(monde):
    t = importer(statut="voicemail")
    with stockage.transaction():
        reg = outils._obtenir_registre()
        reg.ajouter(
            {
                "type_entree": "transfert",
                "evenement": "ouvert",
                "transfert_id": "tr-" + "f" * 20,
                "type_transfert": "ventes",
                "horodatage": HEURE,
            }
        )
    assert [ligne["transfert_id"] for ligne in lister()["resultat"]["resultat"]["rappels"]] == [t]


def test_borne_entire_list_et_frais_rollback_postappend(monde):
    t = importer()
    before = tables()
    with contexte.appele_par_appareil(ADMIN), contexte.sortie_bornee(100):
        assert not executer_atomique(outil(LISTE), {})["resultat"]["accepte"]
    assert before == tables()
    r = prendre(t, limite=100)
    assert not r["resultat"]["accepte"]
    assert before == tables()
    _, patch = monde
    original = outils._appliquer_suivi_rappel

    def panne(*a, **kw):
        original(*a, **kw)
        raise TypeError("FICTIF panne après append")

    patch.setattr(outils, "_appliquer_suivi_rappel", panne)
    with pytest.raises(RuntimeError):
        prendre(t)
    assert before == tables()


def test_sqlite_deux_prises_concurrentes_une_seule(monde):
    t = importer()
    snap = lister()["resultat"]["resultat"]["rappels"][0]["suivi_rappel"]["snapshot_suivi"]
    barrier = Barrier(2)

    def job():
        barrier.wait(timeout=5)
        return prendre(t, snap)["resultat"]["accepte"]

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: job(), range(2)))
    assert sorted(results) == [False, True]
    with stockage.transaction():
        assert (
            len([ligne for ligne in outils._obtenir_registre().lire() if ligne.get("evenement") == "prise_en_charge"])
            == 1
        )


@pytest.mark.parametrize("champ", ["version_bool", "compteur_bool"])
def test_ack_rejeu_types_json_exacts_pas_egalite_python_bool_int(monde, champ):
    t = importer()
    args = {
        "transfert_id": t,
        "snapshot_attendu": lister()["resultat"]["resultat"]["rappels"][0]["suivi_rappel"]["snapshot_suivi"],
    }
    meta = idempotence.Meta(str(uuid4()), APP, HEURE)
    ack = prendre(t, args["snapshot_attendu"], meta=meta)
    if champ == "version_bool":
        ack["resultat"]["resultat"]["version"] = True
    else:
        ack["resultat"]["resultat"]["suivi_rappel"]["tentatives_sans_contact"] = False
    from m1_front_office import rappels_appareil as r

    with stockage.transaction(), mutation(meta=meta), pytest.raises(r.Refus):
        outils.verifier_rejeu_prise_rappel_appareil(args, ack)


def test_quota_source_sql_avant_decodeur_sur_toutes_les_tables(monde):
    from sqlalchemy import insert

    outil(LISTE)
    _, patch = monde
    with stockage.transaction() as cnx:
        cnx.execute(
            insert(REGISTRES),
            [
                {
                    "departement": "m01-front-office",
                    "registre": "principal",
                    "rang": n,
                    "maillon": "JSON FICTIF volontairement non décodable",
                }
                for n in range(10001)
            ],
        )
    reads = []
    patch.setattr(Registre, "lire", lambda _self: reads.append(1))
    before = tables()
    reply = lister()
    assert not reply["resultat"]["accepte"] and reads == [] and before == tables()


@pytest.mark.parametrize("kind", ["ValueError", "KeyError", "quota"])
def test_pannes_post_append_refusent_techniquement_et_rollback_entier(monde, kind):
    t = importer()
    before = tables()
    _, patch = monde
    original = outils._appliquer_suivi_rappel

    def panne(*args, **kwargs):
        result = original(*args, **kwargs)
        if kind == "ValueError":
            raise ValueError("FICTIF projection cassée")
        if kind == "KeyError":
            raise KeyError("FICTIF ACK cassé")
        contexte._LIMITE_SORTIE.set(100)
        return result

    # Le quota passe à 100 après l'effet pour exercer le postflight, pas le préflight.
    patch.setattr(outils, "_appliquer_suivi_rappel", panne)
    with pytest.raises(RuntimeError):
        prendre(t)
    assert before == tables()


def test_horodatage_meta_mismatch_et_contexte_reinitialise(monde):
    from m1_front_office import rappels_appareil as r

    t = importer()
    args = {
        "transfert_id": t,
        "snapshot_attendu": lister()["resultat"]["resultat"]["rappels"][0]["suivi_rappel"]["snapshot_suivi"],
    }
    meta = idempotence.Meta(str(uuid4()), APP, HEURE)
    before = tables()
    wrong = contexte.HorodatageAppareil(
        "AUTRE-APP-FICTIF", dt.datetime.fromisoformat(HEURE), dt.datetime.fromisoformat(HEURE)
    )
    with (
        stockage.transaction(),
        contexte.appele_par_appareil(ADMIN),
        r.contexte_mutation(meta),
        contexte.receptionne_de(wrong),
    ):
        assert not outils.prendre_en_charge_rappel_appareil(**args)["accepte"]
    with stockage.transaction(), contexte.appele_par_appareil(ADMIN):
        assert not outils.prendre_en_charge_rappel_appareil(**args)["accepte"]
    assert before == tables()


@pytest.mark.parametrize("raison", ["SNAPSHOT-PERIME", "TRANSFERT-CLOS", "DEJA-ATTRIBUE", "SORTIE-TROP-VOLUMINEUSE"])
def test_refus_frais_certain_rejoue_entier_sans_maillon_ni_condition_fraiche(monde, raison):
    from m1_front_office import rappels_appareil as r

    t = importer()
    snap = lister()["resultat"]["resultat"]["rappels"][0]["suivi_rappel"]["snapshot_suivi"]
    if raison == "DEJA-ATTRIBUE":
        assert prendre(t, snap)["resultat"]["accepte"]
        snap = lister()["resultat"]["resultat"]["rappels"][0]["suivi_rappel"]["snapshot_suivi"]
    if raison == "TRANSFERT-CLOS":
        with stockage.transaction(), contexte.appele_par_appareil(ADMIN):
            assert outils.clore_transfert(t, "FICTIF clôture humaine avant demande", HEURE)["accepte"]
    if raison == "SNAPSHOT-PERIME":
        snap = "0" * 64
    meta = idempotence.Meta(str(uuid4()), APP, HEURE)
    args = {"transfert_id": t, "snapshot_attendu": snap}
    quota = 700 if raison == "SORTIE-TROP-VOLUMINEUSE" else 5400
    reply = prendre(t, snap, meta=meta, limite=quota)
    assert reply["resultat"]["verdict"]["code"] == "REJ-M1-RAPPEL-" + raison, reply
    before = tables()
    stockage.liberer()
    with stockage.transaction(), mutation(meta=meta):
        outils.verifier_rejeu_prise_rappel_appareil(args, reply)
    assert before == tables()
    with stockage.transaction(), mutation(meta=meta, limite=100), pytest.raises(r.Refus) as err:
        outils.verifier_rejeu_prise_rappel_appareil(args, reply)
    assert err.value.suffixe == "SORTIE-TROP-VOLUMINEUSE" and before == tables()


@pytest.mark.parametrize("change", ["detail", "extra", "bool", "source", "identite", "meta", "outer"])
def test_cache_negatif_faux_ou_tampered_ne_devient_pas_refus_certain(monde, change):
    from m1_front_office import rappels_appareil as r

    t = importer()
    meta = idempotence.Meta(str(uuid4()), APP, HEURE)
    args = {"transfert_id": t, "snapshot_attendu": "0" * 64}
    reply = prendre(t, args["snapshot_attendu"], meta=meta)
    if change == "detail":
        reply["resultat"]["verdict"]["detail"] = "FICTIF texte modifié"
    elif change == "extra":
        reply["resultat"]["secret"] = "FICTIF interdit"
    elif change == "bool":
        reply["resultat"]["accepte"] = 0
    elif change == "source":
        reply["resultat"] = r.refus(r.Refus("SOURCE-INVALIDE"))
    elif change == "identite":
        reply["resultat"] = r.refus(r.Refus("IDENTITE-INVALIDE"))
    elif change == "meta":
        reply["resultat"] = r.refus(r.Refus("HORODATAGE-REQUIS"))
    else:
        reply["ok"] = False
    before = tables()
    with stockage.transaction(), mutation(meta=meta), pytest.raises(r.Refus) as err:
        outils.verifier_rejeu_prise_rappel_appareil(args, reply)
    assert err.value.suffixe == "REJEU-INCOHERENT" and before == tables()


def test_refus_certain_ne_contourne_pas_retrait_autorite_avant_rejeu(monde):
    from m1_front_office import rappels_appareil as r

    t = importer()
    args = {"transfert_id": t, "snapshot_attendu": "0" * 64}
    meta = idempotence.Meta(str(uuid4()), APP, HEURE)
    reply = prendre(t, args["snapshot_attendu"], meta=meta)
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, ADMIN.personne, "admin")
    before = tables()
    with stockage.transaction(), mutation(meta=meta), pytest.raises(r.Refus) as err:
        outils.verifier_rejeu_prise_rappel_appareil(args, reply)
    assert err.value.suffixe == "IDENTITE-INVALIDE" and before == tables()


@pytest.mark.parametrize("code", ["TRANSFERT-CLOS", "SNAPSHOT-PERIME", "DEJA-ATTRIBUE", "SORTIE-TROP-VOLUMINEUSE"])
def test_succes_cache_substitue_en_refus_canonique_reste_inconnu(monde, code):
    from m1_front_office import rappels_appareil as r

    t = importer()
    args = {
        "transfert_id": t,
        "snapshot_attendu": lister()["resultat"]["resultat"]["rappels"][0]["suivi_rappel"]["snapshot_suivi"],
    }
    meta = idempotence.Meta(str(uuid4()), APP, HEURE)
    ack = prendre(t, args["snapshot_attendu"], meta=meta)
    assert ack["resultat"]["accepte"] is True
    substituted = {"ok": True, "resultat": r.refus(r.Refus(code))}
    before = tables()
    with stockage.transaction(), mutation(meta=meta), pytest.raises(r.Refus) as err:
        outils.verifier_rejeu_prise_rappel_appareil(args, substituted)
    assert err.value.suffixe == "REJEU-INCOHERENT" and before == tables()


def test_vrai_refus_autre_appareil_uuid_identique_n_est_pas_le_succes_etranger(monde):
    t = importer()
    snapshot = lister()["resultat"]["resultat"]["rappels"][0]["suivi_rappel"]["snapshot_suivi"]
    key = str(uuid4())
    first = idempotence.Meta(key, APP, HEURE)
    assert prendre(t, snapshot, meta=first)["resultat"]["accepte"]
    second = idempotence.Meta(key, "AUTRE-APPAREIL-FICTIF", HEURE)
    args = {"transfert_id": t, "snapshot_attendu": "0" * 64}
    refusal = prendre(t, args["snapshot_attendu"], meta=second)
    assert refusal["resultat"]["verdict"]["code"] == "REJ-M1-RAPPEL-SNAPSHOT-PERIME"
    before = tables()
    with stockage.transaction(), mutation(meta=second):
        outils.verifier_rejeu_prise_rappel_appareil(args, refusal)
    assert before == tables()


def test_prise_console_legacy_sans_paire_device_ne_bloque_pas_vrai_refus(monde):
    t = importer()
    snapshot = lister()["resultat"]["resultat"]["rappels"][0]["suivi_rappel"]["snapshot_suivi"]
    with (
        stockage.transaction(),
        contexte.appele_par_appareil(contexte.IdentiteAppelante(ADMIN.personne, "admin", source="console")),
    ):
        legacy = outils.consigner_suivi_rappel(t, "prise_en_charge", snapshot, HEURE)
        assert legacy["accepte"]
        ligne = outils._obtenir_registre().lire()[-1]
        assert ligne["voie"] == "console" and "appareil" not in ligne and "intention_uuid" not in ligne
    args = {"transfert_id": t, "snapshot_attendu": "0" * 64}
    meta = idempotence.Meta(str(uuid4()), APP, HEURE)
    refusal = prendre(t, args["snapshot_attendu"], meta=meta)
    before = tables()
    with stockage.transaction(), mutation(meta=meta):
        outils.verifier_rejeu_prise_rappel_appareil(args, refusal)
    assert before == tables()
