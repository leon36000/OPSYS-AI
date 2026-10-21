"""Monde explicitement fictif : vrai journal de développement et vrais faits métier dans une même instance.

R1 : les namespaces `developpement`, `evenements` et `affaires` sont alimentés par leurs points d'entrée
publics (API de mémoire développement, outils et consommateurs M10), avec le même identifiant textuel des
deux côtés. La base est fermée, copiée et rouverte sous une URL neuve ; l'ancien contexte d'un admin retiré
est refusé avant les lectures M10 via MaillonsDurables instrumentées ; un autre admin courant lit sans mélange.

R2 : l'ajout ORIGINAL du paquet de développement au registre durable est réellement exécuté et observé en SQL,
puis une panne survient ; le rollback ne laisse aucun fait fantôme et préserve les témoins committés. Après
réouverture, la même opération produit un seul effet, son rejeu aucun, un contenu différent un conflit.
"""

from __future__ import annotations

import json
import shutil
import sqlite3

import pytest
from m10_memoire import developpement as memoire_dev
from m10_memoire import outils as m10
from m10_memoire import registre
from sqlalchemy import select, text

from opsys import contexte, identite, stockage
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.maillons import MaillonsDurables
from opsys.stockage.schema import REGISTRES

FICTIF = True
DEPARTEMENT = "m10-memoire"
NAMESPACES = ("developpement", "evenements", "affaires")
ADMIN_A = contexte.IdentiteAppelante("admin-a.fictif", "admin")
ADMIN_B = contexte.IdentiteAppelante("admin-b.fictif", "admin")
COLLISION = "M10-COLLISION-FICTIF"
CANARY_DEV = "CANARY-DEV-R1-FICTIF"
CANARY_METIER = "CANARY-METIER-R1-FICTIF"
WCT_METIER = f"WCT-{CANARY_METIER}"
HORODATAGE = "2026-10-08T13:00:00+00:00"
JOUR = HORODATAGE[:10]
REFUS_APPAREIL = "REJ-IDENTITE-APPAREIL-INVALIDE"


@pytest.fixture
def instance(tmp_path, monkeypatch):
    opsys_home = tmp_path / "opsys-home"
    opsys_home.mkdir()
    base = tmp_path / "opsys.db"
    url = f"sqlite:///{base}"
    monkeypatch.setenv("OPSYS_HOME", str(opsys_home))
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    monkeypatch.setattr(identite, "hacher_mot_de_passe", lambda _: "fictif-non-authentifiable")
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, ADMIN_A.personne, "Admin A fictif", "mot-de-passe-fictif", ["admin", "employee"])
        identite.creer_personne(cnx, ADMIN_B.personne, "Admin B fictif", "mot-de-passe-fictif", ["admin"])
    yield base
    stockage.liberer()


def _outil(nom):
    return next(o for o in m10.outils() if o.nom == nom)


def _registres():
    with stockage.transaction():
        return {nom: list(stockage.maillons(DEPARTEMENT, nom)) for nom in NAMESPACES}


def _tables():
    with stockage.transaction() as cnx:
        noms = cnx.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )).scalars().all()
        return {nom: sorted(
            [dict(ligne) for ligne in cnx.execute(text(f'SELECT * FROM "{nom}"')).mappings()],
            key=lambda ligne: json.dumps(ligne, sort_keys=True, default=str),
        ) for nom in noms}


def _identifiants_dev(maillons_dev):
    ids = set()
    for maillon in maillons_dev:
        paquet = maillon["paquet"]
        ids |= {event["event_id"] for event in paquet["events"]}
        ids |= {relation["relation_id"] for relation in paquet["relations"]}
        ids |= {source["source_ref"] for source in paquet["sources"]}
        ids.add(maillon["ligne_id"])
    return ids


def _ecrire_metier():
    """Vrais faits métier via le consommateur amont et les outils M10 ; même identifiant que le dev."""
    with stockage.transaction():
        lead = m10.consommateurs()["m1.lead_qualifie"](
            {
                "lead": {"lead_id": COLLISION, "service": "gouttieres", "urgence_declaree": False, "canal": "texte"},
                "horodatage": HORODATAGE,
            }
        )
    assert lead["memorise"] is True and lead["lead_id"] == COLLISION
    wct = executer_atomique(
        _outil("m10_memoriser_wct"),
        {
            "wct_recu": {
                "wct_id": WCT_METIER,
                "intervention_id": "INT-R1-FICTIF",
                "lead_id": COLLISION,
                "technicien_id": "TECH-R1-FICTIF",
                "horodatage_completion": HORODATAGE,
                "fix_gps_completion": {"lat": "45.5", "lon": "-73.6"},
                "duree_reelle_minutes": 90,
                "ecart_signale": False,
                "revue_id": "REV-R1-FICTIF",
                "hash_maillon": "b" * 64,
                "consommateurs_cibles": ["M6", "M5", "M10"],
                "devis_id": "DEV-R1-FICTIF",
            }
        },
    )
    assert wct["ok"] is True and wct["resultat"]["accepte"] is True, wct
    decision = executer_atomique(
        _outil("m10_journaliser_decision"),
        {
            "decision": {
                "decision_id": COLLISION,
                "raison": f"Raison métier fictive {CANARY_METIER}.",
                "statut": "proposee",
                "options_ecartees": "Reporter le chantier fictif",
            },
            "horodatage": HORODATAGE,
        },
    )
    assert decision["ok"] is True and decision["resultat"]["accepte"] is True, decision
    consolidation = executer_atomique(
        _outil("m10_consolider_affaire"), {"affaire_id": COLLISION, "jour": JOUR, "horodatage": HORODATAGE}
    )
    assert consolidation["ok"] is True and consolidation["resultat"]["ecrit"] is True, consolidation


def _postflight(operation_id, *, plan_id, resume, rapport="reports/m10-collision-fictif"):
    return memoire_dev.enregistrer_postflight(
        operation_id,
        module="M10",
        plan_id=plan_id,
        statut="done",
        resume=resume,
        changements=[{"fichier": "departments/m10-memoire/src/m10_memoire/fictif_collision.py"}],
        tests=[{"source": "departments/m10-memoire/tests/test_fictif_collision.py", "resultat": "passed"}],
        rapport_refs=[rapport],
        claim_key="m10-collision-fictive",
        horodatage=HORODATAGE,
    )


def _ecrire_dev(admin):
    """Vrai journal de développement via l'API publique, mêmes identifiants textuels que le métier."""
    with contexte.appele_par_appareil(admin):
        prompt = memoire_dev.enregistrer_prompt(
            COLLISION,
            f"Prompt de développement fictif {CANARY_DEV} : séparer les domaines après restauration.",
            version=1,
            module="M10",
            objectif=f"Plan fictif {CANARY_DEV}",
            source_refs=["departments/m10-memoire/docs/collision-fictive.md"],
            horodatage=HORODATAGE,
        )
        plan = memoire_dev.enregistrer_plan(
            COLLISION,
            version=1,
            module="M10",
            prompt_id=COLLISION,
            prompt_version=1,
            objectif=f"Étapes fictives {CANARY_DEV}",
            etapes=[{"id": "composer", "description": "Composer les deux domaines", "statut": "active"}],
            fichiers=["departments/m10-memoire/src/m10_memoire/fictif_collision.py"],
            horodatage=HORODATAGE,
        )
        decision = memoire_dev.enregistrer_decision(
            COLLISION,
            version=1,
            module="M10",
            contexte_decision=f"Décision de développement fictive {CANARY_DEV}.",
            options=["séparer", "fusionner"],
            raisons=[f"Raison de développement fictive {CANARY_DEV}."],
            consequences=["Aucune fusion des domaines."],
            autorite="Décision de développement fictive",
            source_refs=["departments/m10-memoire/docs/collision-fictive.md"],
            horodatage=HORODATAGE,
        )
        postflight = _postflight(COLLISION, plan_id=COLLISION, resume=f"Postflight fictif {CANARY_DEV}.")
    assert not any(item["replayed"] for item in (prompt, plan, decision, postflight))
    return {"prompt": prompt, "plan": plan, "decision": decision, "postflight": postflight}


def _preflight_dev(admin):
    with contexte.appele_par_appareil(admin):
        return memoire_dev.preflight(
            "M10", f"{COLLISION} {CANARY_DEV} {CANARY_METIER} {WCT_METIER} prompt plan decision", files=[]
        )


def _lectures_metier(admin):
    with contexte.appele_par_appareil(admin):
        return {
            "canary_metier": executer_atomique(
                _outil("m10_rechercher_affaire_appareil"),
                {"affaire_id": COLLISION, "requete": CANARY_METIER, "limite": 8, "decalage": 0},
            ),
            "canary_dev": executer_atomique(
                _outil("m10_rechercher_affaire_appareil"),
                {"affaire_id": COLLISION, "requete": CANARY_DEV, "limite": 8, "decalage": 0},
            ),
            "tout": executer_atomique(
                _outil("m10_rechercher_affaire_appareil"),
                {"affaire_id": COLLISION, "requete": "", "limite": 8, "decalage": 0},
            ),
            "paquet": executer_atomique(
                _outil("m10_lire_paquet_affaire_appareil"), {"affaire_id": COLLISION, "horodatage": HORODATAGE}
            ),
            "statut": executer_atomique(_outil("m10_statut_decision"), {"decision_id": COLLISION}),
        }


def _assert_preflight_dev_separe(paquet, ids_dev, ids_metier):
    assert paquet["status"] == "available", paquet
    attendus = {("prompt", COLLISION), ("plan", COLLISION), ("decision", COLLISION), ("postflight", COLLISION)}
    assert {(item["kind"], item["entity_id"]) for item in paquet["must_know"]} == attendus
    assert {item["event_id"] for item in paquet["must_know"]} <= ids_dev
    sortie = json.dumps({k: v for k, v in paquet.items() if k != "task"}, ensure_ascii=False)
    assert CANARY_DEV in sortie
    assert CANARY_METIER not in sortie and WCT_METIER not in sortie
    assert not any(ligne_id in sortie for ligne_id in ids_metier)


def _assert_lectures_metier_separees(lectures, ids_dev):
    canary = lectures["canary_metier"]
    assert canary["ok"] is True and "resultats" in canary["resultat"], canary
    assert WCT_METIER in {r["identifiant"] for r in canary["resultat"]["resultats"]}
    assert lectures["canary_dev"]["ok"] is True
    assert lectures["canary_dev"]["resultat"]["pagination"]["total"] == 0
    assert lectures["tout"]["resultat"]["pagination"]["total"] >= 2
    assert {r["affaire_id"] for r in lectures["tout"]["resultat"]["resultats"]} == {COLLISION}
    assert lectures["paquet"]["ok"] is True and lectures["paquet"]["resultat"]["affaire"]["connue"] is True
    assert lectures["statut"] == {"ok": True, "resultat": {"statut": "proposee"}}
    for nom, reponse in lectures.items():
        sortie = json.dumps(
            {k: v for k, v in reponse["resultat"].items() if k != "requete"}, ensure_ascii=False
        )
        assert CANARY_DEV not in sortie, nom
        assert not any(identifiant in sortie for identifiant in ids_dev), nom


def _assert_registres_separes(registres):
    assert all(m["type_entree"] == "memoire_developpement" for m in registres["developpement"])
    texte_dev = json.dumps(registres["developpement"], ensure_ascii=False)
    texte_metier = json.dumps([registres["evenements"], registres["affaires"]], ensure_ascii=False)
    assert CANARY_DEV in texte_dev and CANARY_METIER not in texte_dev and WCT_METIER not in texte_dev
    assert CANARY_METIER in texte_metier and CANARY_DEV not in texte_metier
    assert not any(m["type_entree"] == "memoire_developpement" for m in registres["evenements"])
    assert not any(m["type_entree"] == "memoire_developpement" for m in registres["affaires"])
    for nom in NAMESPACES:
        assert registre.Registre(maillons=registres[nom]).valider_chaine() == (True, ""), nom


def _compter_lectures_registres(monkeypatch):
    lectures = []
    for nom in ("__iter__", "__len__", "__getitem__"):
        original = getattr(MaillonsDurables, nom)

        def compteur(self, *args, _original=original, _nom=nom):
            if self.departement == DEPARTEMENT:
                lectures.append((self.registre, _nom))
            return _original(self, *args)

        monkeypatch.setattr(MaillonsDurables, nom, compteur)
    return lectures


def test_r1_domaines_restaures_separes_et_ancien_admin_refuse_avant_lecture(instance, monkeypatch):
    _ecrire_metier()
    dev = _ecrire_dev(ADMIN_A)
    avant = _registres()
    ids_dev = _identifiants_dev(avant["developpement"])
    ids_metier = {m["ligne_id"] for nom in ("evenements", "affaires") for m in avant[nom]}
    assert len(avant["developpement"]) == 4 and len(avant["evenements"]) == 2 and len(avant["affaires"]) == 2
    _assert_registres_separes(avant)
    preflight_origine = _preflight_dev(ADMIN_A)
    lectures_origine = _lectures_metier(ADMIN_A)
    _assert_preflight_dev_separe(preflight_origine, ids_dev, ids_metier)
    _assert_lectures_metier_separees(lectures_origine, ids_dev)

    # Restauration : base fermée, copie du fichier SQLite seul, URL neuve, original écarté, poignées neuves.
    stockage.liberer()
    assert not instance.with_name(instance.name + "-wal").exists()
    restauree = instance.with_name("opsys-restauree.db")
    shutil.copy2(instance, restauree)
    instance.rename(instance.with_name("opsys-original-ecarte.db"))
    url_restauree = f"sqlite:///{restauree}"
    monkeypatch.setenv(stockage.ENV_URL, url_restauree)
    stockage.migrer(url_restauree)
    assert stockage.url_base() == url_restauree
    assert _registres() == avant
    _assert_registres_separes(_registres())

    # A encore admin dans l'instance restaurée : mêmes sources exactes, rejeu même clé sans nouveau maillon.
    preflight_restaure = _preflight_dev(ADMIN_A)
    assert preflight_restaure["must_know"] == preflight_origine["must_know"]
    assert preflight_restaure["links"] == preflight_origine["links"]
    _assert_preflight_dev_separe(preflight_restaure, ids_dev, ids_metier)
    assert _lectures_metier(ADMIN_A) == lectures_origine
    with contexte.appele_par_appareil(ADMIN_A):
        rejeu = _postflight(COLLISION, plan_id=COLLISION, resume=f"Postflight fictif {CANARY_DEV}.")
    assert rejeu["replayed"] is True and rejeu["event_id"] == dev["postflight"]["event_id"]
    assert _registres() == avant

    # Retrait réel du rôle admin de A dans la base restaurée ; A reste une personne active.
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, ADMIN_A.personne, "admin")
    with stockage.transaction() as cnx:
        personne_a = identite.personne_active(cnx, ADMIN_A.personne)
    assert personne_a is not None and set(personne_a.roles) == {"employee"}
    tables_avant_refus = _tables()

    lectures = _compter_lectures_registres(monkeypatch)
    with contexte.appele_par_appareil(ADMIN_A):
        with pytest.raises(memoire_dev.AccesDeveloppementRefuse):
            memoire_dev.preflight("M10", f"{COLLISION} {CANARY_DEV}", files=[])
        with pytest.raises(memoire_dev.AccesDeveloppementRefuse):
            _postflight(COLLISION, plan_id=COLLISION, resume=f"Postflight fictif {CANARY_DEV}.")
    refus_metier = _lectures_metier(ADMIN_A)
    assert lectures == []
    for nom, reponse in refus_metier.items():
        assert reponse["ok"] is True and reponse["resultat"]["accepte"] is False, nom
        assert reponse["resultat"]["verdict"]["code"] == REFUS_APPAREIL, nom
        sortie = json.dumps(reponse, ensure_ascii=False)
        assert CANARY_DEV not in sortie and CANARY_METIER not in sortie and WCT_METIER not in sortie, nom
    assert _tables() == tables_avant_refus

    # B, admin courant de l'instance restaurée : lecture positive et séparée des deux domaines. Le même
    # compteur voit ses lectures réelles : le zéro de A ne vient pas d'un compteur hors chemin.
    preflight_b = _preflight_dev(ADMIN_B)
    assert ("developpement", "__iter__") in lectures
    assert preflight_b["must_know"] == preflight_origine["must_know"]
    _assert_preflight_dev_separe(preflight_b, ids_dev, ids_metier)
    lectures.clear()
    lectures_b = _lectures_metier(ADMIN_B)
    assert {("evenements", "__iter__"), ("affaires", "__iter__")} <= set(lectures)
    assert "developpement" not in {nom for nom, _ in lectures}
    _assert_lectures_metier_separees(lectures_b, ids_dev)
    # Témoins positifs des deux autres méthodes instrumentées, sans lecture SQL directe prétendue couverte.
    with stockage.transaction():
        support = stockage.maillons(DEPARTEMENT, "developpement")
        assert len(support) == len(avant["developpement"])
        assert support[0] == avant["developpement"][0]
    assert {("developpement", "__len__"), ("developpement", "__getitem__")} <= set(lectures)
    assert _tables() == tables_avant_refus
    assert _registres() == avant


OPERATION_A = "M10-R2-OPERATION-A-FICTIVE"
PLAN_R2 = "M10-R2-PLAN-FICTIF"


class PanneApresAjoutDurable(RuntimeError):
    """Panne fictive levée après l'ajout original du paquet de développement."""


def _postflight_r2(operation_id, resume="Postflight R2 fictif : résultat observé."):
    return memoire_dev.enregistrer_postflight(
        operation_id,
        module="M10",
        plan_id=PLAN_R2,
        statut="done",
        resume=resume,
        changements=[{"fichier": "departments/m10-memoire/src/m10_memoire/fictif_r2.py"}],
        tests=[{"source": "departments/m10-memoire/tests/test_fictif_r2.py", "resultat": "passed"}],
        rapport_refs=["reports/m10-r2-fictif"],
        claim_key="m10-r2-fictif",
        horodatage=HORODATAGE,
    )


def _lignes_sql_dev(chemin):
    cnx = sqlite3.connect(chemin)
    try:
        return cnx.execute(
            f"SELECT rang, maillon FROM {REGISTRES.name} WHERE departement=? AND registre=? ORDER BY rang",
            (DEPARTEMENT, "developpement"),
        ).fetchall()
    finally:
        cnx.close()


def test_r2_ajout_original_puis_panne_rollback_et_reprise_un_seul_effet(instance):
    _ecrire_metier()
    with contexte.appele_par_appareil(ADMIN_B):
        memoire_dev.enregistrer_prompt(
            PLAN_R2, "Prompt R2 fictif.", version=1, module="M10", objectif="R2 fictif", horodatage=HORODATAGE
        )
        plan = memoire_dev.enregistrer_plan(
            PLAN_R2,
            version=1,
            module="M10",
            prompt_id=PLAN_R2,
            prompt_version=1,
            objectif="Plan R2 fictif",
            etapes=[{"id": "panne", "description": "Panne après ajout", "statut": "active"}],
            fichiers=["departments/m10-memoire/src/m10_memoire/fictif_r2.py"],
            horodatage=HORODATAGE,
        )
        anterieur = _postflight_r2("M10-R2-POSTFLIGHT-ANTERIEUR", resume="Postflight antérieur R2 fictif.")
    avant = _registres()
    tete_dev_avant = registre.Registre(maillons=avant["developpement"]).tete()
    assert len(avant["developpement"]) == 3 and not anterieur["replayed"]
    lignes_sql_avant = _lignes_sql_dev(instance)

    original = registre.Registre.ajouter
    atteintes = []

    def ajouter_puis_panne(self, entree):
        resultat = original(self, entree)
        if getattr(self._chain, "registre", None) == "developpement" and any(
            event["entity_id"] == f"postflight:{OPERATION_A}" for event in entree["paquet"]["events"]
        ):
            cnx = stockage.connexion_courante()
            lignes = cnx.execute(
                select(REGISTRES.c.rang, REGISTRES.c.maillon)
                .where((REGISTRES.c.departement == DEPARTEMENT) & (REGISTRES.c.registre == "developpement"))
                .order_by(REGISTRES.c.rang)
            ).all()
            ecrit = codec.decoder(lignes[-1].maillon)
            atteintes.append({"rang": lignes[-1].rang, "total": len(lignes), "maillon": ecrit})
            raise PanneApresAjoutDurable("panne fictive après ajout durable")
        return resultat

    registre.Registre.ajouter = ajouter_puis_panne
    try:
        with contexte.appele_par_appareil(ADMIN_B), pytest.raises(PanneApresAjoutDurable):
            _postflight_r2(OPERATION_A)
    finally:
        registre.Registre.ajouter = original
    assert registre.Registre.ajouter is original

    # L'ajout original a bien écrit le maillon dans la transaction avant la panne.
    assert len(atteintes) == 1
    atteinte = atteintes[0]
    assert atteinte["rang"] == len(avant["developpement"]) and atteinte["total"] == len(avant["developpement"]) + 1
    assert atteinte["maillon"]["precedent_ligne_id"] == tete_dev_avant
    evenements_ecrits = atteinte["maillon"]["paquet"]["events"]
    assert [event["entity_id"] for event in evenements_ecrits] == [f"postflight:{OPERATION_A}"]
    event_id_panne = evenements_ecrits[0]["event_id"]

    # Rollback : connexion SQLite indépendante, SELECT seuls, puis API native après libération.
    stockage.liberer()
    assert _lignes_sql_dev(instance) == lignes_sql_avant
    assert OPERATION_A not in json.dumps([codec.decoder(m) for _, m in lignes_sql_avant], ensure_ascii=False)
    assert _registres() == avant
    with contexte.appele_par_appareil(ADMIN_B):
        paquet = memoire_dev.preflight("M10", f"{OPERATION_A} {PLAN_R2}", files=[])
    assert OPERATION_A not in json.dumps({k: v for k, v in paquet.items() if k != "task"}, ensure_ascii=False)

    # Réouverture de la même base : un seul paquet durable cohérent pour l'opération reprise.
    stockage.liberer()
    with contexte.appele_par_appareil(ADMIN_B):
        reprise = _postflight_r2(OPERATION_A)
    assert reprise["replayed"] is False and reprise["event_id"] == event_id_panne
    apres_reprise = _registres()
    assert apres_reprise["evenements"] == avant["evenements"] and apres_reprise["affaires"] == avant["affaires"]
    assert apres_reprise["developpement"][:-1] == avant["developpement"]
    assert len(apres_reprise["developpement"]) == len(avant["developpement"]) + 1
    nouveau = apres_reprise["developpement"][-1]
    assert nouveau["precedent_ligne_id"] == tete_dev_avant
    assert [event["event_id"] for event in nouveau["paquet"]["events"]] == [reprise["event_id"]]
    assert nouveau["paquet"]["sources"] == []
    assert {(r["from_event"], r["to_ref"], r["relation_type"]) for r in nouveau["paquet"]["relations"]} == {
        (reprise["event_id"], plan["event_id"], "plan_for"),
        (reprise["event_id"], "file:departments/m10-memoire/src/m10_memoire/fictif_r2.py", "changes"),
        (reprise["event_id"], "departments/m10-memoire/tests/test_fictif_r2.py", "tests"),
        (reprise["event_id"], "reports/m10-r2-fictif", "report"),
    }
    assert registre.Registre(maillons=apres_reprise["developpement"]).valider_chaine() == (True, "")

    # Rejeu exact : même identité, aucun maillon ; contenu différent même id : conflit sans effet.
    stockage.liberer()
    with contexte.appele_par_appareil(ADMIN_B):
        rejeu = _postflight_r2(OPERATION_A)
        assert rejeu["replayed"] is True and rejeu["event_id"] == reprise["event_id"]
        with pytest.raises(memoire_dev.ConflitIdempotence):
            _postflight_r2(OPERATION_A, resume="Autre résultat fictif sous la même opération.")
    assert _registres() == apres_reprise

    # Après reprise, les lectures restent séparées dans les deux sens.
    with contexte.appele_par_appareil(ADMIN_B):
        paquet = memoire_dev.preflight("M10", f"{OPERATION_A} {CANARY_METIER} {WCT_METIER}", files=[])
        recherche = executer_atomique(
            _outil("m10_rechercher_affaire_appareil"),
            {"affaire_id": COLLISION, "requete": "", "limite": 8, "decalage": 0},
        )
    assert {item["entity_id"] for item in paquet["must_know"] if item["kind"] == "postflight"} >= {OPERATION_A}
    sortie_dev = json.dumps({k: v for k, v in paquet.items() if k != "task"}, ensure_ascii=False)
    assert CANARY_METIER not in sortie_dev and WCT_METIER not in sortie_dev
    sortie_metier = json.dumps(recherche, ensure_ascii=False)
    assert recherche["resultat"]["pagination"]["total"] >= 2
    assert OPERATION_A not in sortie_metier and reprise["event_id"] not in sortie_metier
