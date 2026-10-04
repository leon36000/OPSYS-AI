"""Contrats du chemin privé d'admission des procédures, sur PostgreSQL réel."""

from __future__ import annotations

import hashlib
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest
from memoire.doubles import postgres_ephemere, raison_sans_docker, vider

import opsys.memoire.ingestion_procedures as ingestion
from opsys.memoire.ingestion_procedures import (
    CHUNKS_MAX,
    OCTETS_MAX,
    extraire,
)
from opsys.memoire.store import MemoireEntreprise, MemoireIndisponible

RAISON_SANS_DOCKER = raison_sans_docker()
avec_postgres = pytest.mark.skipif(RAISON_SANS_DOCKER is not None, reason=str(RAISON_SANS_DOCKER))


@pytest.fixture(scope="module")
def url_pg():
    if RAISON_SANS_DOCKER is not None:
        pytest.skip(RAISON_SANS_DOCKER)
    with postgres_ephemere(stockage_en_memoire=True) as url:
        yield url


def _sql(url: str, query: str, *params):
    import psycopg

    with psycopg.connect(url) as cnx:
        curseur = cnx.execute(query, params)
        return curseur.fetchall() if curseur.description else []


def _vider(url: str) -> None:
    """Réinitialisation isolée de scénario, y compris les tombstones opaques."""
    vider(url)
    _sql(url, "DELETE FROM memoire.procedure_admission_oubliees")


def _seed_procedures(url: str, nombre: int, octets: int) -> list[str]:
    import psycopg

    raw = b"x" * octets
    identifiants = [str(uuid.uuid5(uuid.NAMESPACE_URL, f"r26-seed-{nombre}-{octets}-{i}"))
                    for i in range(nombre)]
    with psycopg.connect(url) as cnx:
        for numero, ident in enumerate(identifiants):
            cnx.execute("INSERT INTO memoire.procedure_series(document_uuid,titre) VALUES (%s::uuid,'seed')",
                        (ident,))
            sha = "a" * 64
            uri = f"opsys-document://{ident}/{sha}"
            (document_id,) = cnx.execute("INSERT INTO memoire.documents(source,titre) VALUES (%s,'seed')"
                                         " RETURNING id", (uri,)).fetchone()
            cnx.execute("INSERT INTO memoire.procedure_versions(document_uuid,version_no,sha256,cle_admission,"
                        "document_id,corps,auteur,etat,extracteur)"
                        " VALUES (%s::uuid,1,%s,%s,%s,%s,'admin:seed','RECU','procedures-1')",
                        (ident, sha, f"seed-admission-r26-{numero:03d}", document_id, raw))
    return identifiants


def test_extraction_utf8_preserve_crlf_et_nfc_verifiable():
    raw = "# Règle\r\n\r\nCafe\u0301 et toiture.\r\n".encode("utf-8")
    chunks = extraire(raw)

    assert len(chunks) == 1
    chunk = chunks[0]
    assert chunk.texte == "Café et toiture."
    assert raw[chunk.debut_octets:chunk.fin_octets].decode("utf-8") == "Cafe\u0301 et toiture."
    assert (chunk.ligne_debut, chunk.ligne_fin) == (3, 3)
    assert chunk.section == ("Règle",)


def test_extraction_titres_markdown_niveaux_sautes_reconstruit_la_pile():
    raw = ("# Racine\n\n## Niveau 2\n\n#### Profond\n\nTexte profond.\n\n"
           "### Frère\n\nTexte frère.\n\n# Nouvelle racine\n\n## Enfant\n\nTexte enfant.\n\n"
           "### Feuille\n\nTexte feuille.\n\n## Retour\n\nTexte retour.\n").encode()
    chunks = extraire(raw)

    assert [chunk.section for chunk in chunks] == [
        ("Racine", "Niveau 2", "Profond"),
        ("Racine", "Niveau 2", "Frère"),
        ("Nouvelle racine", "Enfant"),
        ("Nouvelle racine", "Enfant", "Feuille"),
        ("Nouvelle racine", "Retour"),
    ]


@avec_postgres
def test_indexation_valide_fragment_normalise_avec_saut_de_ligne_en_fin(url_pg):
    memoire = MemoireEntreprise(url_pg)
    memoire.migrer()
    _vider(url_pg)
    service = memoire.procedures()
    raw = b"mot\n" * 3001
    admission = service.admettre(raw, "Paragraphes", auteur="admin:normalisation",
                                 cle_admission="nonce-lf-r26-0001")
    chunks = extraire(raw)
    assert len(chunks) > 1 and chunks[0].texte.endswith("\n")

    service.indexer(admission.document_id, admission.sha256)
    service.activer(admission.document_id, admission.sha256, attendu_sha256=None, auteur="admin:normalisation")
    resultats = memoire.rechercher("mot", None, 5, {"portee": "procedures"}).resultats
    assert resultats
    assert resultats[0].citations_verifiees


def test_source_exactement_1mib_et_100_positions_est_inclusive():
    base = b"x\n\n" * 100
    raw = base + b" " * (OCTETS_MAX - len(base))
    chunks = extraire(raw)
    assert len(raw) == OCTETS_MAX and len(chunks) == CHUNKS_MAX
    assert all(raw[c.debut_octets:c.fin_octets] == b"x" for c in chunks)


def test_extraction_refuse_bytes_invalides_et_bornes(monkeypatch):
    with pytest.raises(ValueError, match="UTF-8"):
        extraire(b"\xff")
    with pytest.raises(ValueError, match="1 MiB"):
        extraire(b"x" * (OCTETS_MAX + 1))

    # Les blocs de taille bornée donnent au plus 100 positions documentaires.
    monkeypatch.setattr(ingestion, "TAILLE_CHUNK_MAX", 10)
    with pytest.raises(ValueError, match="100 chunks"):
        extraire(("mot " * 260).encode("utf-8"))
    assert CHUNKS_MAX == 100


def test_beaucoup_de_petits_paragraphes_s_arretent_avant_101_calculs_lourds(monkeypatch):
    appels = 0
    reel = ingestion._octets_jusqua

    def compter(texte, caractere):
        nonlocal appels
        appels += 1
        return reel(texte, caractere)

    monkeypatch.setattr(ingestion, "_octets_jusqua", compter)
    raw = (("x\n\n" * (OCTETS_MAX // 3)) + "x").encode("utf-8")
    with pytest.raises(ValueError, match="100 chunks"):
        extraire(raw)
    assert appels == CHUNKS_MAX


@avec_postgres
def test_admission_rejeu_versions_cas_occurrences_et_oubli(url_pg):
    memoire = MemoireEntreprise(url_pg)
    memoire.migrer()
    _vider(url_pg)
    service = memoire.procedures()
    raw = (b"# Proc\n\nVerifier la toiture.\n" * 4)

    admis = service.admettre(raw, "Guide", auteur="admin:test", cle_admission="nonce-admission-r26-0001",
                             )
    document_id = admis.document_id
    rejoue = service.admettre(raw, "Guide", auteur="admin:test", cle_admission="nonce-admission-r26-0001",
                              document_id=document_id)
    assert rejoue.version_id == admis.version_id
    assert rejoue.sha256 == hashlib.sha256(raw).hexdigest()
    assert service.lire_etat(document_id).etat == "RECU"
    assert memoire.rechercher("toiture", None, 5, {"portee": "procedures"}).resultats == ()
    uri = f"opsys-document://{document_id}/{admis.sha256}"
    for departement, portee in (("m03-estimation", "procedures"), ("m04-field-ops", "procedures"),
                                ("m03-estimation", "estimations")):
        with pytest.raises(ValueError, match="source réservée"):
            memoire.ajouter("Verifier la toiture.", {"departement": departement, "portee": portee,
                "source": uri, "sensibilite": "interne"})

    indexe = service.indexer(document_id, admis.sha256)
    assert indexe.etat == "INDEXE"
    assert service.lire_etat(document_id).courante is None
    service.activer(document_id, admis.sha256, attendu_sha256=None, auteur="admin:test")
    import psycopg

    faux_source = f"opsys-document://{uuid.uuid4()}/{'f' * 64}"
    with psycopg.connect(url_pg) as cnx:
        (faux_doc,) = cnx.execute("INSERT INTO memoire.documents(source,titre) VALUES (%s,'forge') RETURNING id",
                                  (faux_source,)).fetchone()
        cnx.execute("INSERT INTO memoire.fragments(document_id,texte,empreinte,departement,portee,sensibilite)"
                    " VALUES (%s,'Verifier la toiture forge.','faux-empreinte','m03-estimation',"
                    "'procedures','interne')",
                    (faux_doc,))
    recherche = memoire.rechercher("toiture", None, 5, {"portee": "procedures"})
    (resultat,) = recherche.resultats
    assert resultat.citations_verifiees
    citation = resultat.citations_verifiees[0]
    assert citation.sha256 == admis.sha256
    assert citation.nombre_occurrences == 4
    assert len(citation.positions) == 3
    version_pk, = _sql(url_pg, "SELECT id FROM memoire.procedure_versions WHERE sha256=%s", admis.sha256)[0]
    occurrences = _sql(url_pg, "SELECT debut_octets,fin_octets FROM memoire.procedure_occurrences"
                       " WHERE version_id=%s ORDER BY debut_octets", version_pk)
    assert len(occurrences) == 4
    dernier_debut = occurrences[-1][0]
    _sql(url_pg, "UPDATE memoire.procedure_occurrences SET debut_octets=0"
        " WHERE version_id=%s AND debut_octets=%s", version_pk, dernier_debut)
    with pytest.raises(ValueError, match="offset"):
        memoire.rechercher("toiture", None, 5, {"portee": "procedures"})
    _sql(url_pg, "UPDATE memoire.procedure_occurrences SET debut_octets=%s"
        " WHERE version_id=%s AND debut_octets=0", dernier_debut, version_pk)
    premier_fin = occurrences[0][1]
    _sql(url_pg, "UPDATE memoire.procedure_occurrences SET fin_octets=%s"
        " WHERE version_id=%s AND debut_octets=%s", len(raw) + 100, version_pk, occurrences[0][0])
    with pytest.raises(ValueError, match="octets source"):
        memoire.rechercher("toiture", None, 5, {"portee": "procedures"})
    _sql(url_pg, "UPDATE memoire.procedure_occurrences SET fin_octets=%s"
        " WHERE version_id=%s AND debut_octets=%s", premier_fin, version_pk, occurrences[0][0])
    _sql(url_pg, "UPDATE memoire.procedure_occurrences SET ligne_debut=ligne_debut+1,ligne_fin=ligne_fin+1"
        " WHERE version_id=%s AND debut_octets=%s", version_pk, occurrences[0][0])
    with pytest.raises(ValueError, match="lignes ou section"):
        memoire.rechercher("toiture", None, 5, {"portee": "procedures"})
    _sql(url_pg, "UPDATE memoire.procedure_occurrences SET ligne_debut=ligne_debut-1,ligne_fin=ligne_fin-1"
        " WHERE version_id=%s AND debut_octets=%s", version_pk, occurrences[0][0])
    original_section, = _sql(url_pg, "SELECT section FROM memoire.procedure_occurrences"
                             " WHERE version_id=%s AND debut_octets=%s", version_pk, occurrences[0][0])[0]
    _sql(url_pg, "UPDATE memoire.procedure_occurrences SET section=ARRAY['falsifie']"
        " WHERE version_id=%s AND debut_octets=%s", version_pk, occurrences[0][0])
    with pytest.raises(ValueError, match="lignes ou section"):
        memoire.rechercher("toiture", None, 5, {"portee": "procedures"})
    _sql(url_pg, "UPDATE memoire.procedure_occurrences SET section=%s"
        " WHERE version_id=%s AND debut_octets=%s", original_section, version_pk, occurrences[0][0])
    original_body, = _sql(url_pg, "SELECT corps FROM memoire.procedure_versions WHERE id=%s", version_pk)[0]
    _sql(url_pg, "UPDATE memoire.procedure_versions SET corps=corps || convert_to('alteration','UTF8')"
        " WHERE id=%s", version_pk)
    with pytest.raises(ValueError, match="intégrité de la source"):
        memoire.rechercher("toiture", None, 5, {"portee": "procedures"})
    _sql(url_pg, "UPDATE memoire.procedure_versions SET corps=%s WHERE id=%s", original_body, version_pk)
    position_test = occurrences[0][0]
    fragment_origine, = _sql(url_pg, "SELECT fragment_id FROM memoire.procedure_occurrences"
                             " WHERE version_id=%s AND debut_octets=%s", version_pk, position_test)[0]
    fragment_etranger = memoire.ajouter("Verifier la toiture.", {
        "departement": "m03-estimation", "portee": "procedures", "source": "fictif:fragment-étranger",
        "sensibilite": "interne"})
    _sql(url_pg, "UPDATE memoire.procedure_occurrences SET fragment_id=%s"
        " WHERE version_id=%s AND debut_octets=%s", fragment_etranger, version_pk, position_test)
    with pytest.raises(ValueError, match="provenance|lien"):
        memoire.rechercher("toiture", None, 5, {"portee": "procedures"})
    _sql(url_pg, "UPDATE memoire.procedure_occurrences SET fragment_id=%s"
        " WHERE version_id=%s AND debut_octets=%s", fragment_origine, version_pk, position_test)
    assert memoire.oublier({"source": "fictif:fragment-étranger"}, demandeur="admin:test",
                           motif="fixture forge") == 1

    seconde = service.admettre(raw + b"Appliquer au besoin.\n", "Guide", auteur="admin:test",
                               cle_admission="nonce-admission-r26-0002", document_id=document_id)
    service.indexer(document_id, seconde.sha256)
    assert service.lire_etat(document_id).courante == admis.sha256
    service.activer(document_id, seconde.sha256, attendu_sha256=admis.sha256, auteur="admin:test")
    assert service.lire_etat(document_id).courante == seconde.sha256
    service.activer(document_id, admis.sha256, attendu_sha256=seconde.sha256, auteur="admin:rollback")
    assert service.lire_etat(document_id).courante == admis.sha256
    assert service.lister_versions(document_id)[0].active is True
    assert service.lister_versions(document_id)[1].active is False
    activations = _sql(url_pg, "SELECT version_precedente,version_cible,auteur FROM memoire.procedure_activations"
                       " WHERE document_uuid=%s::uuid ORDER BY id", document_id)
    assert activations == [(None, admis.sha256, "admin:test"),
                           (admis.sha256, seconde.sha256, "admin:test"),
                           (seconde.sha256, admis.sha256, "admin:rollback")]
    page = service.lister_series()
    assert page.total == 1 and page.series[0]["nombre_versions"] == 2

    uri_v1 = f"opsys-document://{document_id}/{admis.sha256}"
    assert memoire.oublier({"source": uri_v1}, demandeur="admin:test", motif="retrait version courante") == 1
    assert service.lire_etat(document_id).courante is None
    assert [v.sha256 for v in service.lister_versions(document_id)] == [seconde.sha256]
    assert memoire.rechercher("toiture", None, 5, {"portee": "procedures"}).resultats == ()
    assert service.oublier(document_id, demandeur="admin:test", motif="retrait série") >= 1
    assert service.lire_etat(document_id, absent_ok=True) is None
    assert _sql(url_pg, "SELECT count(*) FROM memoire.documents WHERE source LIKE %s",
                f"opsys-document://{document_id}/%")[0][0] == 0
    assert _sql(url_pg, "SELECT count(*) FROM memoire.procedure_activations WHERE document_uuid=%s::uuid",
                document_id)[0][0] == 0


@avec_postgres
def test_cle_admission_rejoue_uuid_serveur_et_oubli_source_nettoie_recu_sans_fragment(url_pg):
    memoire = MemoireEntreprise(url_pg)
    memoire.migrer()
    _vider(url_pg)
    service = memoire.procedures()
    raw = b"# Admission\n\nDocument pas encore indexe.\n"
    invalid = b"x\n\n" * 101
    with pytest.raises(ValueError, match="100 chunks"):
        service.admettre(invalid, "Ne doit pas persister", auteur="admin:stable",
                         cle_admission="nonce-invalid-r26-0001")
    assert _sql(url_pg, "SELECT count(*) FROM memoire.procedure_series")[0][0] == 0
    premier = service.admettre(raw, "À réviser", auteur="admin:stable", cle_admission="nonce-http-r26-0001")
    rejoue = service.admettre(raw, "À réviser", auteur="admin:stable", cle_admission="nonce-http-r26-0001")
    assert rejoue == premier
    with pytest.raises(ValueError, match="conflit"):
        service.admettre(raw + b"autre", "À réviser", auteur="admin:stable",
                         cle_admission="nonce-http-r26-0001")
    assert service.lire_etat(premier.document_id).etat == "RECU"
    assert memoire.etat()["fragments"] == 0
    assert service.oublier(premier.document_id, demandeur="admin:stable", motif="annulation") == 0
    assert service.lire_etat(premier.document_id, absent_ok=True) is None
    with pytest.raises(ValueError, match="clé d'admission oubliée"):
        service.admettre(raw, "À réviser", auteur="admin:stable", cle_admission="nonce-http-r26-0001")
    assert _sql(url_pg, "SELECT cle_admission FROM memoire.procedure_admission_oubliees") == [
        ("nonce-http-r26-0001",)
    ]

    second = service.admettre(raw, "À réviser", auteur="admin:stable", cle_admission="nonce-http-r26-0002")
    assert second.document_id != premier.document_id
    uri = f"opsys-document://{second.document_id}/{second.sha256}"
    assert memoire.oublier({"source": uri}, demandeur="admin:stable", motif="annulation source") == 0
    assert service.lire_etat(second.document_id, absent_ok=True) is None
    assert _sql(url_pg, "SELECT count(*) FROM memoire.documents WHERE source=%s", uri)[0][0] == 0
    assert _sql(url_pg, "SELECT count(*) FROM memoire.procedure_versions WHERE document_uuid=%s::uuid",
                second.document_id)[0][0] == 0

    third = service.admettre(raw, "À réviser", auteur="admin:stable", cle_admission="nonce-http-r26-0003")
    (document_pk,) = _sql(url_pg, "SELECT document_id FROM memoire.procedure_versions WHERE id=%s",
                          third.version_id)[0]
    assert memoire.oublier({"document_id": document_pk}, demandeur="admin:stable",
                           motif="annulation id") == 0
    assert service.lire_etat(third.document_id, absent_ok=True) is None
    assert _sql(url_pg, "SELECT count(*) FROM memoire.documents WHERE id=%s", document_pk)[0][0] == 0


@avec_postgres
def test_oubli_recu_respecte_filtres_composes_et_tombstone(url_pg):
    memoire = MemoireEntreprise(url_pg)
    memoire.migrer()
    _vider(url_pg)
    service = memoire.procedures()
    raw = "# À conserver\n\nAdmission RECU sans fragment.\n".encode()

    par_source = service.admettre(raw, "Source", auteur="admin:forget-filter",
                                  cle_admission="nonce-forget-filter-r26-01")
    source = f"opsys-document://{par_source.document_id}/{par_source.sha256}"
    assert memoire.oublier({"source": source, "portee": "clients"}, demandeur="admin:forget-filter",
                           motif="filtre trop restrictif") == 0
    assert service.lire_etat(par_source.document_id).etat == "RECU"
    assert memoire.oublier({"source": source, "sujet": "client:C-0042"},
                           demandeur="admin:forget-filter", motif="sujet absent") == 0
    assert memoire.oublier({"source": source, "attributs": {"scope": "absent"}},
                           demandeur="admin:forget-filter", motif="attributs absents") == 0
    assert service.lire_etat(par_source.document_id).etat == "RECU"
    assert memoire.oublier({"source": source, "portee": "procedures"}, demandeur="admin:forget-filter",
                           motif="source procédure") == 0
    assert service.lire_etat(par_source.document_id, absent_ok=True) is None
    with pytest.raises(ValueError, match="clé d'admission oubliée"):
        service.admettre(raw, "Source", auteur="admin:forget-filter",
                         cle_admission="nonce-forget-filter-r26-01")

    par_document = service.admettre(raw, "Document", auteur="admin:forget-filter",
                                    cle_admission="nonce-forget-filter-r26-02")
    (document_pk,) = _sql(url_pg, "SELECT document_id FROM memoire.procedure_versions WHERE id=%s",
                          par_document.version_id)[0]
    assert memoire.oublier({"document_id": document_pk, "departement": "m04-field-ops"},
                           demandeur="admin:forget-filter", motif="département non correspondant") == 0
    assert service.lire_etat(par_document.document_id).etat == "RECU"
    assert memoire.oublier({"document_id": document_pk, "departement": "m03-estimation"},
                           demandeur="admin:forget-filter", motif="document procédures") == 0
    assert service.lire_etat(par_document.document_id, absent_ok=True) is None
    with pytest.raises(ValueError, match="clé d'admission oubliée"):
        service.admettre(raw, "Document", auteur="admin:forget-filter",
                         cle_admission="nonce-forget-filter-r26-02")


@avec_postgres
def test_concurrence_rejeu_et_activation_cas_ne_cree_qu_une_version_courante(url_pg):
    memoire = MemoireEntreprise(url_pg)
    memoire.migrer()
    _vider(url_pg)
    service = memoire.procedures()
    raw_a = b"# Regle\n\nInspecter la toiture annuelle.\n"
    raw_b = "# Regle\n\nInspecter la toiture après tempête.\n".encode()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futur = [pool.submit(service.admettre, raw_a, "Plan", auteur="admin:concurrent",
                             cle_admission="nonce-concurrent-r26-001") for _ in range(2)]
        admissions = [f.result() for f in futur]
    assert admissions[0] == admissions[1]
    a = admissions[0]
    b = service.admettre(raw_b, "Plan", auteur="admin:concurrent", cle_admission="nonce-concurrent-r26-002",
                         document_id=a.document_id)
    service.indexer(a.document_id, a.sha256)
    service.indexer(b.document_id, b.sha256)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(service.activer, a.document_id, digest, attendu_sha256=None,
                               auteur="admin:concurrent") for digest in (a.sha256, b.sha256)]
    resultats = [f.exception() for f in futures]
    assert sum(erreur is None for erreur in resultats) == 1
    assert sum(isinstance(erreur, ValueError) for erreur in resultats) == 1
    courante = service.lire_etat(a.document_id).courante
    avant = _sql(url_pg, "SELECT count(*) FROM memoire.procedure_activations WHERE document_uuid=%s::uuid",
                 a.document_id)[0][0]
    with pytest.raises(ValueError, match="CAS"):
        service.activer(a.document_id, a.sha256 if courante != a.sha256 else b.sha256,
                        attendu_sha256=None, auteur="admin:stale")
    apres = _sql(url_pg, "SELECT count(*) FROM memoire.procedure_activations WHERE document_uuid=%s::uuid",
                 a.document_id)[0][0]
    assert courante in {a.sha256, b.sha256} and avant == apres == 1


@avec_postgres
def test_echec_apres_premier_fragment_rollback_index_complet_et_reprise(url_pg):
    import psycopg

    memoire = MemoireEntreprise(url_pg)
    memoire.migrer()
    _vider(url_pg)
    service = memoire.procedures()
    raw = b"# Reprise\n\nPremiere instruction distincte.\n\nDeuxieme instruction distincte.\n"
    admission = service.admettre(raw, "Reprise", auteur="admin:rollback", cle_admission="nonce-rollback-r26-1")
    (document_pk,) = _sql(url_pg, "SELECT document_id FROM memoire.procedure_versions WHERE id=%s",
                          admission.version_id)[0]
    with psycopg.connect(url_pg, autocommit=True) as cnx:
        cnx.execute("""CREATE FUNCTION memoire.test_r26_fail_after_one() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF NEW.portee='procedures' AND EXISTS
                (SELECT 1 FROM memoire.fragments WHERE document_id=NEW.document_id) THEN
                RAISE EXCEPTION 'injected second fragment failure';
              END IF;
              RETURN NEW;
            END $$""")
        cnx.execute("CREATE TRIGGER test_r26_fail_after_one BEFORE INSERT ON memoire.fragments"
                    " FOR EACH ROW EXECUTE FUNCTION memoire.test_r26_fail_after_one()")
    try:
        with pytest.raises(psycopg.errors.RaiseException, match="injected second fragment failure"):
            service.indexer(admission.document_id, admission.sha256)
        assert service.lire_etat(admission.document_id).etat == "RECU"
        assert _sql(url_pg, "SELECT count(*) FROM memoire.fragments WHERE document_id=%s", document_pk)[0][0] == 0
        assert _sql(url_pg, "SELECT count(*) FROM memoire.procedure_occurrences WHERE version_id=%s",
                    admission.version_id)[0][0] == 0
    finally:
        with psycopg.connect(url_pg, autocommit=True) as cnx:
            cnx.execute("DROP TRIGGER IF EXISTS test_r26_fail_after_one ON memoire.fragments")
            cnx.execute("DROP FUNCTION IF EXISTS memoire.test_r26_fail_after_one()")
    assert service.indexer(admission.document_id, admission.sha256).etat == "INDEXE"


@avec_postgres
def test_verrou_documentaire_occupe_refuse_en_deux_secondes_sans_mutation(url_pg):
    import psycopg

    memoire = MemoireEntreprise(url_pg)
    memoire.migrer()
    _vider(url_pg)
    service = memoire.procedures()
    raw = b"# Attente\n\nNe pas indexer sous verrou.\n"
    admission = service.admettre(raw, "Attente", auteur="admin:lock", cle_admission="nonce-lock-r26-0001")
    with psycopg.connect(url_pg) as cnx:
        cnx.execute("SELECT pg_advisory_xact_lock(hashtext(%s))",
                    ("opsys.memoire.procedure." + admission.document_id,))
        with pytest.raises(MemoireIndisponible, match="STOCKAGE_OCCUPE"):
            service.indexer(admission.document_id, admission.sha256)
    assert service.lire_etat(admission.document_id).etat == "RECU"
    (docs,) = _sql(url_pg, "SELECT document_id FROM memoire.procedure_versions WHERE id=%s", admission.version_id)[0]
    assert _sql(url_pg, "SELECT count(*) FROM memoire.fragments WHERE document_id=%s", docs)[0][0] == 0


@avec_postgres
def test_quota_64mib_sous_courses_reel_pg_ne_depasse_pas_et_rollback(url_pg):
    memoire = MemoireEntreprise(url_pg)
    memoire.migrer()
    _vider(url_pg)
    identifiants = _seed_procedures(url_pg, 63, OCTETS_MAX)
    service = memoire.procedures()
    brut_y, brut_z = b"y" * OCTETS_MAX, b"z" * OCTETS_MAX
    with ThreadPoolExecutor(max_workers=2) as pool:
        futur = [pool.submit(service.admettre, brut, "Concurrent", auteur="admin:quota",
                             cle_admission=f"nonce-quota-r26-{numero:02d}", document_id=identifiants[0])
                 for numero, brut in enumerate((brut_y, brut_z), 1)]
    resultats = []
    erreurs = []
    for future in futur:
        try:
            resultats.append(future.result())
        except ValueError as exc:
            erreurs.append(exc)
    assert len(resultats) == len(erreurs) == 1
    assert "quota global de 64 MiB" in str(erreurs[0])
    (octets,) = _sql(url_pg, "SELECT sum(octet_length(corps)) FROM memoire.procedure_versions")[0]
    (versions,) = _sql(url_pg, "SELECT count(*) FROM memoire.procedure_versions")[0]
    assert octets == 64 * 1024 * 1024 and versions == 64
    with pytest.raises(ValueError, match="quota global de 64 MiB"):
        service.admettre(b"extra", "Trop", auteur="admin:quota", cle_admission="nonce-quota-r26-extra",
                         document_id=identifiants[0])
    assert _sql(url_pg, "SELECT sum(octet_length(corps)),count(*) FROM memoire.procedure_versions")[0] == (
        64 * 1024 * 1024, 64)


@avec_postgres
def test_quota_64_series_sous_course_et_8_versions_strictes(url_pg):
    memoire = MemoireEntreprise(url_pg)
    memoire.migrer()
    _vider(url_pg)
    _seed_procedures(url_pg, 63, 1)
    service = memoire.procedures()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(service.admettre, b"x", "Série", auteur="admin:quota",
                               cle_admission=f"nonce-series-r26-{numero:02d}") for numero in (1, 2)]
    resultats, erreurs = [], []
    for future in futures:
        try:
            resultats.append(future.result())
        except ValueError as exc:
            erreurs.append(exc)
    assert len(resultats) == len(erreurs) == 1
    assert "64 séries" in str(erreurs[0])
    assert _sql(url_pg, "SELECT count(*) FROM memoire.procedure_series")[0][0] == 64

    _vider(url_pg)
    admission = service.admettre(b"Version 1.\n", "Versions", auteur="admin:versions",
                                 cle_admission="nonce-version-r26-001")
    for numero in range(2, 9):
        service.admettre(f"Version {numero}.\n".encode(), "Versions", auteur="admin:versions",
                         cle_admission=f"nonce-version-r26-{numero:03d}", document_id=admission.document_id)
    with pytest.raises(ValueError, match="8 versions"):
        service.admettre(b"Version 9.\n", "Versions", auteur="admin:versions",
                         cle_admission="nonce-version-r26-009", document_id=admission.document_id)
    assert len(service.lister_versions(admission.document_id)) == 8


@avec_postgres
def test_purge_du_courant_n_active_pas_l_historique_et_garde_son_audit(url_pg):
    memoire = MemoireEntreprise(url_pg)
    memoire.migrer()
    _vider(url_pg)
    service = memoire.procedures()
    v1 = service.admettre(b"# Historique\n\nRegle historique inactive.\n", "Plan",
                          auteur="admin:purge", cle_admission="nonce-purge-r26-001")
    service.indexer(v1.document_id, v1.sha256)
    service.activer(v1.document_id, v1.sha256, attendu_sha256=None, auteur="admin:purge")
    v2 = service.admettre("# Actuelle\n\nRegle actuelle expirée.\n".encode(), "Plan",
                          auteur="admin:purge", cle_admission="nonce-purge-r26-002",
                          document_id=v1.document_id)
    service.indexer(v2.document_id, v2.sha256)
    service.activer(v2.document_id, v2.sha256, attendu_sha256=v1.sha256, auteur="admin:purge")
    (document_pk,) = _sql(url_pg, "SELECT document_id FROM memoire.procedure_versions WHERE sha256=%s", v2.sha256)[0]
    _sql(url_pg, "UPDATE memoire.fragments SET cree_le=now()-interval '2 days',"
        "expire_le=now()-interval '1 day' WHERE document_id=%s", document_pk)

    assert memoire.purger_expires() == 1
    etat = service.lire_etat(v1.document_id)
    assert etat.courante is None
    assert [version.sha256 for version in service.lister_versions(v1.document_id)] == [v1.sha256]
    assert memoire.rechercher("actuelle historique", None, 5, {"portee": "procedures"}).resultats == ()
    assert _sql(url_pg, "SELECT count(*) FROM memoire.documents WHERE id=%s", document_pk)[0][0] == 0
    assert _sql(url_pg, "SELECT version_precedente,version_cible FROM memoire.procedure_activations"
                " WHERE document_uuid=%s::uuid ORDER BY id", v1.document_id)[0] == (None, v1.sha256)
    assert _sql(url_pg, "SELECT version_precedente,version_cible FROM memoire.procedure_activations"
                " WHERE document_uuid=%s::uuid ORDER BY id", v1.document_id)[1] == (v1.sha256, v2.sha256)


@avec_postgres
def test_echec_oubli_apres_cascade_rollback_series_source_index_et_journal(url_pg):
    import psycopg

    memoire = MemoireEntreprise(url_pg)
    memoire.migrer()
    _vider(url_pg)
    service = memoire.procedures()
    admission = service.admettre(b"# Oubli\n\nTexte qui doit rester entier.\n", "Oubli",
                                 auteur="admin:rollback", cle_admission="nonce-forget-r26-01")
    service.indexer(admission.document_id, admission.sha256)
    service.activer(admission.document_id, admission.sha256, attendu_sha256=None, auteur="admin:rollback")
    avant = {
        "series": _sql(url_pg, "SELECT count(*) FROM memoire.procedure_series")[0][0],
        "versions": _sql(url_pg, "SELECT count(*) FROM memoire.procedure_versions")[0][0],
        "fragments": _sql(url_pg, "SELECT count(*) FROM memoire.fragments")[0][0],
        "occurrences": _sql(url_pg, "SELECT count(*) FROM memoire.procedure_occurrences")[0][0],
        "activations": _sql(url_pg, "SELECT count(*) FROM memoire.procedure_activations")[0][0],
        "admission_tombstones": _sql(url_pg, "SELECT count(*) FROM memoire.procedure_admission_oubliees")[0][0],
        "journal": _sql(url_pg, "SELECT count(*) FROM memoire.journal_effacements")[0][0],
    }
    with psycopg.connect(url_pg, autocommit=True) as cnx:
        cnx.execute("""CREATE FUNCTION memoire.test_r26_fail_forget() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF OLD.source LIKE 'opsys-document://%' THEN
                RAISE EXCEPTION 'injected forget failure';
              END IF;
              RETURN OLD;
            END $$""")
        cnx.execute("CREATE TRIGGER test_r26_fail_forget BEFORE DELETE ON memoire.documents"
                    " FOR EACH ROW EXECUTE FUNCTION memoire.test_r26_fail_forget()")
    try:
        with pytest.raises(psycopg.errors.RaiseException, match="injected forget failure"):
            service.oublier(admission.document_id, demandeur="admin:rollback", motif="test rollback")
    finally:
        with psycopg.connect(url_pg, autocommit=True) as cnx:
            cnx.execute("DROP TRIGGER IF EXISTS test_r26_fail_forget ON memoire.documents")
            cnx.execute("DROP FUNCTION IF EXISTS memoire.test_r26_fail_forget()")
    apres = {
        "series": _sql(url_pg, "SELECT count(*) FROM memoire.procedure_series")[0][0],
        "versions": _sql(url_pg, "SELECT count(*) FROM memoire.procedure_versions")[0][0],
        "fragments": _sql(url_pg, "SELECT count(*) FROM memoire.fragments")[0][0],
        "occurrences": _sql(url_pg, "SELECT count(*) FROM memoire.procedure_occurrences")[0][0],
        "activations": _sql(url_pg, "SELECT count(*) FROM memoire.procedure_activations")[0][0],
        "admission_tombstones": _sql(url_pg, "SELECT count(*) FROM memoire.procedure_admission_oubliees")[0][0],
        "journal": _sql(url_pg, "SELECT count(*) FROM memoire.journal_effacements")[0][0],
    }
    assert apres == avant
    assert service.lire_etat(admission.document_id).courante == admission.sha256
