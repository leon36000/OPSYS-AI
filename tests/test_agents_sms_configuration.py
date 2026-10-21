"""Tests fictifs de la variante canal SMS des profils agents (RED avant changement de source)."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import MetaData, Table, select

from opsys import agents, departements, identite
from opsys.stockage import schema

FICTIF = True
ADMIN, STAFF, MDP = "admin.sms.fictif", "staff.sms.fictif", "mot-de-passe-sms-fictif-1234"
SID_A = "AC" + "0123456789abcdef" * 2
SID_B = "AC" + "fedcba9876543210" * 2
SID_M = "AC" + "0123456789aBcDeF" * 2
TOOL = "m1_recevoir_message_canal"  # HYPOTHESE: présent dans le catalogue M1 réel
PROFILE_TABLES = {"agents_configurables", "agents_configurables_historique", "agents_configurables_commandes"}
PROOF_WINDOWS = []


def _encoder(valeur):
    if isinstance(valeur, (dt.date, dt.datetime)):
        return {"date": valeur.isoformat()}
    if isinstance(valeur, (bytes, memoryview)):
        return {"octets": bytes(valeur).hex()}
    raise TypeError("type SQL non pris en charge dans le census fictif")


def snapshot_sql(cnx):
    noms = cnx.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").scalars()
    resultat = {}
    for nom in noms:
        table = schema.META.tables.get(nom)
        if table is None:
            table = Table(nom, MetaData(), autoload_with=cnx)
        lignes = [json.dumps(dict(row), ensure_ascii=False, sort_keys=True, allow_nan=False, default=_encoder)
                  for row in cnx.execute(select(table)).mappings()]
        resultat[nom] = hashlib.sha256(json.dumps(sorted(lignes), ensure_ascii=False).encode()).hexdigest()
    return resultat


def verifier_fenetre(avant, apres, *, autorises=frozenset()):
    assert set(avant) == set(apres)
    changes = {nom for nom in avant if avant[nom] != apres[nom]}
    PROOF_WINDOWS.append({"test": os.environ.get("PYTEST_CURRENT_TEST", "fictif"),
                          "avant": avant, "apres": apres, "changes": sorted(changes)})
    assert changes == set(autorises)



def canal(compte="cabinet-1", sid=SID_A, **autres):
    return {"type": "canal", "version": 1, "canal": "sms", "compte_id": compte, "account_sid": sid, **autres}


def spec(ident="m01-sms-un", decl=None, **autres):
    return {
        "id": ident, "departement": "m01-front-office", "responsabilite": "Accueil SMS fictif.",
        "palier_modele": "rapide", "outils": [TOOL], "budget_jour": 1000, "budget_mois": 10000,
        "limite_tours": 8, "limite_reessais": 1, "limite_concurrence": 1,
        "declencheurs": [canal()] if decl is None else decl, **autres,
    }


INVALIDES = [
    canal(version=True), canal(version=False), canal(version=0), canal(version=2), canal(version=1.0), canal(extra="x"),
    {k: v for k, v in canal().items() if k != "account_sid"}, canal(type="Canal"), canal(canal="SMS"),
    canal("Cabinet"), canal("cabinet\n"), canal("cabin\u00e9t"), canal("cabinet-\uff11"),
    canal("a" * 65), canal("prototype"), canal("constructor"), canal("__proto__"),
    canal(sid=SID_A.lower()), canal(sid=SID_A[:-1]), canal(sid="AC" + "g" * 32), canal(sid=SID_A + "\n"),
    canal(sid="AC" + "\uff10" * 32), canal(sid=None), canal(sid=True),
]


@pytest.fixture
def deps(session):
    d = departements.charger_departements()
    with session() as cnx:
        identite.creer_personne(cnx, ADMIN, "Admin fictif", MDP, ["admin"])
        identite.creer_personne(cnx, STAFF, "Employé fictif", MDP, ["employee"])
    return d


def etat(session):
    with session() as cnx:
        return snapshot_sql(cnx)


def creer(cnx, deps, s, n):
    return agents.creer(cnx, deps, s, par=ADMIN, mutation_id=f"creer-sms-{n:04d}")


def activer(cnx, deps, ident, rev, n, actif=True):
    return agents.definir_actif(cnx, ident, deps, actif, par=ADMIN, mutation_id=f"actif-sms-{n:04d}",
                                revision_attendue=rev)


def deux(session, deps, sid_b=SID_B):
    with session() as cnx:
        return (creer(cnx, deps, spec("m01-sms-a"), 1),
                creer(cnx, deps, spec("m01-sms-b", [canal(sid=sid_b)]), 2))


def test_variante_valide_creee_inactive_puis_activation_explicite(session, deps):
    avant = etat(session)
    with session() as cnx:
        p = creer(cnx, deps, spec(decl=[canal(sid=SID_M)]), 1)
        assert (p["actif"], p["revision"]) == (False, 1)
        assert p["declencheurs"] == [canal(sid=SID_M)] and type(p["declencheurs"][0]["version"]) is int
        assert agents.lister(cnx) == []
        a = activer(cnx, deps, p["id"], 1, 1)
        assert a["actif"] and a["revision"] == 2 and agents.historique(cnx, p["id"]) == [p, a]
    with session() as cnx:
        assert agents.obtenir(cnx, p["id"]) == a
    verifier_fenetre(avant, etat(session), autorises=PROFILE_TABLES)


@pytest.mark.parametrize("decl", INVALIDES, ids=[str(i) for i in range(len(INVALIDES))])
def test_variantes_invalides_refusees_avant_ecriture(session, deps, decl):
    avant = etat(session)
    with session() as cnx, pytest.raises(ValueError):
        creer(cnx, deps, spec(decl=[decl]), 1)
    verifier_fenetre(avant, etat(session))


@pytest.mark.parametrize("modif", [
    {"departement": "m03-estimation", "outils": []}, {"outils": []}, {"declencheurs": [canal(), {"type": "manuel"}]},
    {"declencheurs": [canal(), canal("cabinet-2")]}, {"declencheurs": [canal(), canal()]},
])
def test_dedication_m1_outil_natif_et_trigger_unique(session, deps, modif):
    avant = etat(session)
    with session() as cnx, pytest.raises(ValueError):
        creer(cnx, deps, spec(**modif), 1)
    verifier_fenetre(avant, etat(session))


def test_modifier_meme_chemin_refuse_ou_accepte_la_variante(session, deps):
    with session() as cnx:
        p = creer(cnx, deps, spec("m01-legacy-deux", [{"type": "manuel"}], outils=[]), 1)
    avant = etat(session)
    with session() as cnx, pytest.raises(ValueError):
        agents.modifier(cnx, p["id"], deps, spec(p["id"], [canal(version=True)]), par=ADMIN,
                        mutation_id="modif-sms-0001", revision_attendue=1)
    verifier_fenetre(avant, etat(session))
    with session() as cnx:
        m = agents.modifier(cnx, p["id"], deps, spec(p["id"]), par=ADMIN, mutation_id="modif-sms-0002",
                            revision_attendue=1)
        assert (m["revision"], m["actif"], m["declencheurs"]) == (2, False, [canal()])


def test_permission_et_retrait_acteur_avant_replay(session, deps):
    avant = etat(session)
    with session() as cnx, pytest.raises(PermissionError):
        agents.creer(cnx, deps, spec(), par=STAFF, mutation_id="creer-staff-0001")
    verifier_fenetre(avant, etat(session))
    with session() as cnx:
        p = creer(cnx, deps, spec(), 1)
        activer(cnx, deps, p["id"], 1, 1)
        identite.retirer_role(cnx, ADMIN, "admin")
    avant = etat(session)
    with session() as cnx:
        for appel in (lambda: activer(cnx, deps, p["id"], 2, 2, False), lambda: activer(cnx, deps, p["id"], 1, 1)):
            with pytest.raises(PermissionError):
                appel()
    verifier_fenetre(avant, etat(session))


@pytest.mark.parametrize("sid_b", [SID_A, SID_B])
def test_unicite_compte_a_l_activation_sans_ecriture_puis_liberation(session, deps, sid_b):
    a, b = deux(session, deps, sid_b)
    with session() as cnx:
        activer(cnx, deps, a["id"], 1, 1)
    avant = etat(session)
    with session() as cnx, pytest.raises(ValueError):
        activer(cnx, deps, b["id"], 1, 2)
    verifier_fenetre(avant, etat(session))
    with session() as cnx:
        activer(cnx, deps, a["id"], 2, 3, False)
        assert activer(cnx, deps, b["id"], 1, 4)["actif"] is True
        agents.supprimer(cnx, b["id"], deps, par=ADMIN, mutation_id="suppr-sms-0001", revision_attendue=2)
        assert activer(cnx, deps, a["id"], 3, 5)["actif"] is True


def test_modification_d_un_actif_vers_un_compte_occupe_refusee(session, deps):
    with session() as cnx:
        a = creer(cnx, deps, spec("m01-sms-a"), 1)
        b = creer(cnx, deps, spec("m01-sms-b", [canal("cabinet-2", SID_B)]), 2)
        activer(cnx, deps, a["id"], 1, 1)
        activer(cnx, deps, b["id"], 1, 2)
    avant = etat(session)
    with session() as cnx, pytest.raises(ValueError):
        agents.modifier(cnx, b["id"], deps, spec(b["id"], [canal(sid=SID_B)]), par=ADMIN,
                        mutation_id="modif-sms-0003", revision_attendue=2)
    verifier_fenetre(avant, etat(session))


def test_cas_et_replay_rendent_l_ancienne_reponse_apres_changement(session, deps):
    a, b = deux(session, deps)
    with session() as cnx:
        a2 = activer(cnx, deps, a["id"], 1, 1)
        avant_cas = snapshot_sql(cnx)
        with pytest.raises(ValueError, match="conflit de révision"):
            activer(cnx, deps, a["id"], 1, 2, False)
        verifier_fenetre(avant_cas, snapshot_sql(cnx))
        activer(cnx, deps, a["id"], 2, 3, False)
        b2 = activer(cnx, deps, b["id"], 1, 4)
    avant = etat(session)
    with session() as cnx:
        assert activer(cnx, deps, a["id"], 1, 1) == a2
        assert activer(cnx, deps, b["id"], 1, 4) == b2
    verifier_fenetre(avant, etat(session))


def test_rollback_apres_historique_commande_puis_reprise_meme_cle(session, deps, monkeypatch):
    avant = etat(session)
    memoriser = agents._memoriser_commande

    def apres_commande(cnx, *args):
        memoriser(cnx, *args)
        verifier_fenetre(avant, snapshot_sql(cnx), autorises=PROFILE_TABLES)
        raise RuntimeError("PANNE-FICTIVE-APRES-COMMANDE")

    with monkeypatch.context() as patch:
        patch.setattr(agents, "_memoriser_commande", apres_commande)
        with pytest.raises(RuntimeError, match="PANNE-FICTIVE"), session() as cnx:
            creer(cnx, deps, spec(), 1)
    verifier_fenetre(avant, etat(session))
    with session() as cnx:
        assert creer(cnx, deps, spec(), 1)["revision"] == 1
    verifier_fenetre(avant, etat(session), autorises=PROFILE_TABLES)


def test_deux_appels_activation_concurrents_une_seule_reussite(session, deps):
    a, b = deux(session, deps)
    avant = etat(session)
    rendez_vous = threading.Barrier(2)
    connexions = []
    verrou = threading.Lock()

    def tentative(ident, numero):
        rendez_vous.wait(timeout=5)  # AVANT BEGIN IMMEDIATE, jamais sous le verrou écrivain.
        try:
            with session() as cnx:
                with verrou:
                    connexions.append(cnx)
                profil = activer(cnx, deps, ident, 1, numero)
            return "accepte", profil["id"]
        except ValueError as erreur:
            assert "compte SMS" in str(erreur)
            return "refuse", ident

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(tentative, a["id"], 1), pool.submit(tentative, b["id"], 2)]
        resultats = [future.result(timeout=15) for future in futures]
    assert len({id(cnx) for cnx in connexions}) == 2
    assert sorted(verdict for verdict, _ in resultats) == ["accepte", "refuse"]
    verifier_fenetre(avant, etat(session), autorises=PROFILE_TABLES)
    with session() as cnx:
        actifs = agents.lister(cnx)
        assert len(actifs) == 1 and actifs[0]["id"] in {a["id"], b["id"]}
        gagne = next(ident for verdict, ident in resultats if verdict == "accepte")
        perd = next(ident for verdict, ident in resultats if verdict == "refuse")
        assert len(agents.historique(cnx, gagne)) == 2
        assert len(agents.historique(cnx, perd)) == 1


@pytest.mark.parametrize("compte", ["a", "a" * 64])
def test_compte_aux_bornes_conserve_verbatim(session, deps, compte):
    avant = etat(session)
    with session() as cnx:
        profil = creer(cnx, deps, spec(decl=[canal(compte)]), 1)
        assert profil["declencheurs"][0]["compte_id"] == compte
    verifier_fenetre(avant, etat(session), autorises=PROFILE_TABLES)


def test_meme_mutation_id_corps_change_refuse_sans_effet(session, deps):
    with session() as cnx:
        p = creer(cnx, deps, spec(), 1)
    avant = etat(session)
    with session() as cnx, pytest.raises(ValueError, match="mutation_id déjà utilisé"):
        creer(cnx, deps, spec(decl=[canal(sid=SID_B)]), 1)
    verifier_fenetre(avant, etat(session))
    with session() as cnx:
        assert creer(cnx, deps, spec(), 1) == p
    verifier_fenetre(avant, etat(session))


def test_lectures_profil_et_historique_sont_pures(session, deps):
    with session() as cnx:
        p = creer(cnx, deps, spec(), 1)
    avant = etat(session)
    with session() as cnx:
        assert agents.obtenir(cnx, p["id"]) == p
        assert agents.lister(cnx, inclure_inactifs=True) == [p]
        assert agents.historique(cnx, p["id"]) == [p]
    verifier_fenetre(avant, etat(session))
