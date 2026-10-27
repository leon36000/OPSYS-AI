"""CRM-09 : notes internes sur vrais outils et SQLite. Fixtures exclusivement fictives.

Aucun import d'un autre fichier de tests. Les tests Capacites exigent le raccord central
de Meta et de garde avant cache ; ils sont destinés à la QA intégrée de ROOT.
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from m6_material_control import notes_commande as n
from m6_material_control import outils
from sqlalchemy import delete, select, update

from opsys import contexte, idempotence, identite, stockage
from opsys.capacites import Capacites
from opsys.departements import lire_manifeste
from opsys.outils import Autonomie, Niveau, executer_atomique
from opsys.stockage.schema import APPROBATIONS, JOURNAL, META, MUTATIONS_APPLIQUEES, PERSONNES, REGISTRES

DEP = "m06-material-control"
DATE = "2026-10-27T04:00:00+00:00"
ADMIN = contexte.IdentiteAppelante("admin.notes.fictif", "admin")
EMP = contexte.IdentiteAppelante("employe.notes.fictif", "employee")
SELLER = contexte.IdentiteAppelante("vendeur.notes.fictif", "seller")
OWNER = contexte.IdentiteAppelante("owner.notes.fictif", "nathan_owner", source="console")
ARGUMENTS = {"note_id": "NOTE-FICTIVE", "devis_id": "DEVIS-FICTIF",
             "texte_libre": "FICTIF : vis et scellant à prévoir", "revision_attendue": 0}


def outil(nom):
    return next(o for o in outils.outils() if o.nom == nom)


@pytest.fixture
def monde(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'notes-fictives.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    with stockage.transaction() as cnx:
        for acteur in (ADMIN, EMP, SELLER, OWNER):
            identite.creer_personne(cnx, acteur.personne, "Personne fictive", "mot-de-passe-fictif-12345",
                                   [acteur.role])
    besoin("DEVIS-FICTIF", "CHANTIER-FICTIF")
    yield url
    stockage.liberer()


def besoin(devis_id, chantier_id):
    if chantier_id is None:
        # Le producteur M3 accepte ce cas ; le schéma RPC manuel historique exige str.
        # Utiliser son orchestrateur public réel, sans fabriquer de maillon.
        with stockage.transaction():
            assert outils.enregistrer_besoins_prevus(None, devis_id, [])["accepte"]
        return
    reponse = executer_atomique(outil("m6_enregistrer_besoins_prevus"), {
        "chantier_id": chantier_id, "devis_id": devis_id, "lignes": [],
    })
    assert reponse["ok"] and reponse["resultat"]["accepte"], reponse


def meta(cle="mutation-fictive"):
    return idempotence.Meta(cle, "APP-NOTES-FICTIF", DATE)


def appel(arguments=None, *, cle="mutation-fictive", acteur=ADMIN, limite=n.BORNE_SORTIE):
    with (contexte.appele_par_appareil(acteur), outils.contexte_mutation_note_commande(meta(cle)),
          contexte.sortie_bornee(limite)):
        return executer_atomique(outil(n.ECRIRE), ARGUMENTS if arguments is None else arguments)


def lecture(note_id="NOTE-FICTIVE", revision=None, *, acteur=ADMIN, limite=n.BORNE_SORTIE):
    args = {"note_id": note_id}
    if revision is not None:
        args["revision"] = revision
    with contexte.appele_par_appareil(acteur), contexte.sortie_bornee(limite):
        return executer_atomique(outil(n.LIRE), args)


def resultat(reponse):
    assert reponse["ok"], reponse
    assert reponse["resultat"]["accepte"], reponse
    return reponse["resultat"]


def notes():
    with stockage.transaction():
        return list(stockage.maillons(DEP, n.REGISTRE))


def tables_hors_note():
    with stockage.transaction() as cnx:
        return {
            table.name: [tuple(row) for row in cnx.execute(select(table)).all()]
            for table in META.sorted_tables if table.name not in {
                REGISTRES.name, JOURNAL.name, MUTATIONS_APPLIQUEES.name,
            }
        }, [tuple(row) for row in cnx.execute(select(REGISTRES).where(
            ~((REGISTRES.c.departement == DEP) & (REGISTRES.c.registre == n.REGISTRE))
        )).all()]


def test_contrat_public_ferme_et_scope_non_invente():
    for nom, autonomie, niveau in ((n.ECRIRE, Autonomie.T1, Niveau.N3), (n.LIRE, Autonomie.T0, Niveau.N0)):
        o = outil(nom)
        assert o.roles_appareil == frozenset({"admin"})
        assert o.parametres["additionalProperties"] is False
        assert o.autonomie is autonomie and o.niveau_effectif is niveau
        assert o.portee_contexte is None
    assert set(outil(n.ECRIRE).parametres["properties"]) == set(ARGUMENTS)


def test_texte_long_exact_prevu_vide_reouverture_sans_autres_effets(monde):
    texte = "  FICTIF <script>alert('x')</script>\r\nAchats : vis, scellant, équerres\t\n" * 250
    avant = tables_hors_note()
    res = resultat(appel({**ARGUMENTS, "texte_libre": texte}))
    assert res["note"]["texte_libre"] == texte
    assert res["note"]["statut"] == "note_interne"
    assert res["note"]["chantier_id"] == "CHANTIER-FICTIF"
    assert res["note"]["auteur"] == {"personne": ADMIN.personne, "role": "admin"}
    assert set(res) == {"accepte", "note", "rejoue"}
    stockage.liberer()
    assert resultat(lecture())["note"] == res["note"]
    assert tables_hors_note() == avant
    with stockage.transaction() as cnx:
        audit = cnx.execute(select(JOURNAL).where(JOURNAL.c.action == "m6.note_commande_enregistree")).all()
        assert len(audit) == 1
        assert "alert" not in repr(audit) and "scellant" not in repr(audit)
        assert outils.approuver_po("NOTE-FICTIVE", DATE)["verdict"]["code"] == "REJ-PO-INTROUVABLE"


@pytest.mark.parametrize("changement", [
    {"texte_libre": "x" * 20001}, {"texte_libre": " \t\r\n"}, {"texte_libre": 10},
    {"texte_libre": "FICTIF\x00"}, {"texte_libre": "FICTIF\ud800"},
    {"revision_attendue": True}, {"revision_attendue": -1}, {"note_id": " "},
    {"devis_id": "d" * 201}, {"auteur": ADMIN.personne}, {"statut": "approved"},
])
def test_entrees_invalides_sans_ecriture(monde, changement):
    reponse = appel({**ARGUMENTS, **changement})
    assert not reponse["ok"] or not reponse["resultat"]["accepte"]
    assert notes() == []


def test_borne_20000_acceptee_et_sortie_insuffisante_avant_append(monde):
    args = {**ARGUMENTS, "texte_libre": "é" * 20000}
    refus = appel(args, limite=5400)
    assert refus["resultat"]["verdict"]["code"] == "REJ-NOTE-COMMANDE-SORTIE-TROP-VOLUMINEUSE"
    assert notes() == []
    assert resultat(appel(args))["note"]["texte_libre"] == args["texte_libre"]
    assert lecture(limite=5400)["resultat"]["verdict"]["code"] == "REJ-NOTE-COMMANDE-SORTIE-TROP-VOLUMINEUSE"


@pytest.mark.parametrize("acteur", [None, EMP, SELLER, OWNER,
    contexte.IdentiteAppelante("inconnue.fictive", "admin"),
    contexte.IdentiteAppelante(ADMIN.personne, "admin", source="agent"),
])
def test_autorite_avant_lecture_et_mutation(monde, acteur):
    resultat(appel())
    avant = notes()
    for r in (appel(acteur=acteur), lecture(acteur=acteur)):
        assert r["resultat"] == n.refuser("IDENTITE")
        assert ARGUMENTS["texte_libre"] not in json.dumps(r)
    assert notes() == avant


@pytest.mark.parametrize("retrait", ["role", "inactive"])
def test_revocation_avant_rejeu_metier(monde, retrait):
    resultat(appel())
    with stockage.transaction() as cnx:
        if retrait == "role":
            identite.retirer_role(cnx, ADMIN.personne, "admin")
        else:
            cnx.execute(update(PERSONNES).where(PERSONNES.c.identifiant == ADMIN.personne).values(actif=False))
    assert appel()["resultat"] == n.refuser("IDENTITE")
    assert lecture()["resultat"] == n.refuser("IDENTITE")
    assert len(notes()) == 1


def test_versions_rejeu_original_et_conflit_de_mutation(monde):
    premier = resultat(appel())
    nouveau = {**ARGUMENTS, "texte_libre": "FICTIF : ajouter vis inox", "revision_attendue": 1}
    second = resultat(appel(nouveau, cle="correction-fictive"))
    assert second["note"]["revision"] == 2
    assert resultat(lecture(revision=1))["note"] == premier["note"]
    assert resultat(lecture())["note"] == second["note"]
    replay = resultat(appel())
    assert replay["rejoue"] and replay["note"] == premier["note"]
    assert appel(nouveau)["resultat"] == n.refuser("MUTATION-CONFLIT")
    assert appel(cle="obsolete-fictive")["resultat"] == n.refuser("REVISION-PERIMEE")
    assert len(notes()) == 2


def test_ancrage_absent_inconnu_et_modification_refuses(monde):
    assert appel({**ARGUMENTS, "devis_id": "ABSENT-FICTIF"})["resultat"] == n.refuser("BESOIN-INTROUVABLE")
    besoin("SANS-CHANTIER-FICTIF", None)
    assert appel({**ARGUMENTS, "devis_id": "SANS-CHANTIER-FICTIF"})["resultat"] == n.refuser("CHANTIER-INCONNU")
    resultat(appel())
    besoin("AUTRE-DEVIS-FICTIF", "AUTRE-CHANTIER-FICTIF")
    args = {**ARGUMENTS, "devis_id": "AUTRE-DEVIS-FICTIF", "revision_attendue": 1}
    assert appel(args, cle="autre-ancrage")["resultat"] == n.refuser("ANCRAGE-DIFFERENT")
    assert len(notes()) == 1


def test_sans_contexte_mutation_et_hors_transaction_refuses(monde):
    with contexte.appele_par_appareil(ADMIN):
        assert executer_atomique(outil(n.ECRIRE), ARGUMENTS)["resultat"] == n.refuser("MUTATION-ABSENTE")
        assert outils.enregistrer_note_commande(**ARGUMENTS) == n.refuser("IDENTITE")
    assert notes() == []


def test_deux_corrections_concurrentes_une_seule_revision(monde):
    resultat(appel())
    barrier = Barrier(2)

    def corriger(index):
        barrier.wait(timeout=10)
        return appel({**ARGUMENTS, "texte_libre": f"FICTIF correction {index}", "revision_attendue": 1},
                     cle=f"concurrente-{index}")["resultat"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        reponses = list(pool.map(corriger, (1, 2)))
    assert sum(r["accepte"] for r in reponses) == 1
    assert [r for r in reponses if not r["accepte"]] == [n.refuser("REVISION-PERIMEE")]
    assert [m["revision"] for m in notes()] == [1, 2]


def test_panne_apres_append_annule_note_et_audit(monde, monkeypatch):
    avant = tables_hors_note()

    def panne(*args, **kwargs):
        raise RuntimeError("panne fictive après append")

    monkeypatch.setattr(outils, "journaliser", panne)
    with pytest.raises(RuntimeError, match="panne fictive"):
        appel()
    assert notes() == []
    assert tables_hors_note() == avant


def test_corruption_durable_refusee_sans_texte_partiel(monde):
    resultat(appel())
    with stockage.transaction() as cnx:
        cnx.execute(update(REGISTRES).where(
            (REGISTRES.c.departement == DEP) & (REGISTRES.c.registre == n.REGISTRE)
        ).values(maillon="{}"))
    assert lecture()["resultat"] == n.refuser("REGISTRE-INVALIDE")
    assert appel()["resultat"] == n.refuser("REGISTRE-INVALIDE")


def test_capacites_rejeu_transport_expiration_et_revocation(monde):
    """Exige raccord ROOT : Meta, autorité avant cache et quota réel sans artefact tronqué."""
    dep = lire_manifeste(Path(__file__).resolve().parents[1])
    cap = Capacites({DEP: dep}, stockage.transaction, limite_sortie=n.BORNE_SORTIE)
    with contexte.appele_par_appareil(ADMIN):
        premier = cap.appeler(n.ECRIRE, ARGUMENTS, meta=meta())
        assert resultat(premier)["note"]["revision"] == 1
        replay = cap.appeler(n.ECRIRE, ARGUMENTS, meta=meta())
        assert replay["rejoue"] and resultat(replay)["note"] == resultat(premier)["note"]
        with stockage.transaction() as cnx:
            cnx.execute(delete(MUTATIONS_APPLIQUEES))
        expire = cap.appeler(n.ECRIRE, ARGUMENTS, meta=meta())
        assert resultat(expire)["note"] == resultat(premier)["note"]
        assert len(notes()) == 1
        with stockage.transaction() as cnx:
            identite.retirer_role(cnx, ADMIN.personne, "admin")
        interdit = cap.appeler(n.ECRIRE, ARGUMENTS, meta=meta())
    assert not interdit.get("ok") or not interdit.get("resultat", {}).get("accepte")
    assert ARGUMENTS["texte_libre"] not in json.dumps(interdit)
    assert len(notes()) == 1


def test_capacites_quota_lecture_rejeu_entiers_et_audit_minimise(monde):
    dep = lire_manifeste(Path(__file__).resolve().parents[1])
    petit = Capacites({DEP: dep}, stockage.transaction, limite_sortie=6000)
    grand = Capacites({DEP: dep}, stockage.transaction, limite_sortie=n.BORNE_SORTIE)
    texte = "ACHATS-FICTIFS-PRIVES-NE-PAS-JOURNALISER " + "é" * 19000
    args = {**ARGUMENTS, "texte_libre": texte}
    with contexte.appele_par_appareil(ADMIN):
        refus = petit.appeler(n.ECRIRE, args, meta=meta("quota-faible"))
        assert not refus.get("ok") or not refus.get("resultat", {}).get("accepte")
        assert notes() == []
        fait = grand.appeler(n.ECRIRE, args, meta=meta("quota-grand"))
        assert resultat(fait)["note"]["texte_libre"] == texte
        lu = grand.appeler(n.LIRE, {"note_id": ARGUMENTS["note_id"]})
        assert resultat(lu)["note"] == resultat(fait)["note"]
        petit_rejeu = petit.appeler(n.ECRIRE, args, meta=meta("quota-grand"))
        assert not petit_rejeu.get("ok") or not petit_rejeu.get("resultat", {}).get("accepte")
        petit_lu = petit.appeler(n.LIRE, {"note_id": ARGUMENTS["note_id"]})
        assert not petit_lu.get("ok") or not petit_lu.get("resultat", {}).get("accepte")
        assert "ACHATS-FICTIFS-PRIVES" not in json.dumps([petit_rejeu, petit_lu])
        lecture_mutation = grand.appeler(n.LIRE, {"note_id": ARGUMENTS["note_id"]}, meta=meta("lecture"))
        assert not lecture_mutation.get("ok")
    assert len(notes()) == 1
    with stockage.transaction() as cnx:
        traces = cnx.execute(select(APPROBATIONS).where(APPROBATIONS.c.outil == n.ECRIRE)).all()
        journal = cnx.execute(select(JOURNAL)).all()
        assert "ACHATS-FICTIFS-PRIVES" not in repr(traces) + repr(journal)


def test_capacites_meme_appareil_autre_admin_ne_rejoue_pas_le_texte(monde):
    dep = lire_manifeste(Path(__file__).resolve().parents[1])
    cap = Capacites({DEP: dep}, stockage.transaction, limite_sortie=n.BORNE_SORTIE)
    autre = contexte.IdentiteAppelante("autre.admin.fictif", "admin")
    with stockage.transaction() as cnx:
        identite.creer_personne(cnx, autre.personne, "Autre admin fictif", "mot-de-passe-fictif-12345", ["admin"])
    with contexte.appele_par_appareil(ADMIN):
        resultat(cap.appeler(n.ECRIRE, ARGUMENTS, meta=meta()))
    with contexte.appele_par_appareil(autre):
        r = cap.appeler(n.ECRIRE, ARGUMENTS, meta=meta())
    assert not r.get("ok") or not r.get("resultat", {}).get("accepte")
    assert ARGUMENTS["texte_libre"] not in json.dumps(r)
    assert len(notes()) == 1


@pytest.mark.parametrize("acteur", [None, contexte.IdentiteAppelante(ADMIN.personne, "admin", source="console")])
def test_sans_meta_ne_cree_pas_demande_exposant_note_a_agent(monde, acteur):
    dep = lire_manifeste(Path(__file__).resolve().parents[1])
    cap = Capacites({DEP: dep}, stockage.transaction, appelant=DEP, limite_sortie=n.BORNE_SORTIE)
    marqueur = "FICTIF-PRIVE-SANS-META-NE-PAS-EXPOSER"
    with contexte.appele_par_appareil(acteur):
        refus = cap.appeler(n.ECRIRE, {**ARGUMENTS, "texte_libre": marqueur})
    assert not refus.get("ok") or not refus.get("resultat", {}).get("accepte"), refus
    with stockage.transaction() as cnx:
        assert cnx.execute(select(APPROBATIONS)).all() == []
    demandes = cap.appeler("opsys_demandes_approbation", {})
    assert marqueur not in json.dumps(demandes)
    assert notes() == []
