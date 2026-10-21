"""R44b : édition propriétaire via routes réelles, sans modèle ni chargeur simulé."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from m7_marketing import outils as outils_m7
from m7_marketing.usine import service
from sqlalchemy import update

from opsys import contexte, identite, stockage
from opsys.console import application
from opsys.console.securite import Configuration
from opsys.outils import executer_atomique
from opsys.stockage import codec
from opsys.stockage.schema import REGISTRES

PASSWORD = "mot-de-passe-r44-fictif-123456"


@pytest.fixture(autouse=True)
def _base_isolee(monkeypatch):
    monkeypatch.delenv(stockage.ENV_URL, raising=False)


@pytest.fixture
def client(session):
    with session() as cnx:
        identite.creer_personne(cnx, "owner-r44", "Propriétaire fictif", PASSWORD, ["admin", "nathan_owner"])
        identite.creer_personne(cnx, "admin-r44", "Admin fictif", PASSWORD, ["admin"])
        stockage.maillons(*service.REGISTRE_WCT_RECUS).append(
            {
                "wct_id": "wct-r44-fictif",
                "intervention_id": "intervention-r44-fictif",
                "lead_id": "lead-r44-fictif",
                "technicien_id": "tech-r44-fictif",
                "devis_id": "devis-r44-fictif",
                "hash_maillon": "ab" * 32,
                "horodatage_completion": "2026-10-01T15:00:00-04:00",
                "statut": "completed_verified",
                "ville": "Repentigny",
                "type_travaux": "gouttières",
                "photos": [],
                "client_satisfait": True,
                "consentement_marketing": True,
                "consentement_recueilli_par": "tech-r44-fictif",
                "consentement_recueilli_le": "2026-10-01T19:00:00+00:00",
                "consentement_version_texte": "fr-v1",
            }
        )
    app = application.creer_application(
        Configuration("secret-r44-fictif-" + "x" * 64, cookie_securise=False, prefixe="/opsys"), None, session
    )
    with TestClient(app, base_url="https://testserver/opsys") as testclient:
        yield testclient


def _login(client, personne="owner-r44"):
    r = client.post("/connexion", data={"identifiant": personne, "mot_de_passe": PASSWORD}, follow_redirects=False)
    assert r.status_code == 303, r.text
    return client.get("/api/session").json()["csrf"]


def _marque(client, csrf, nom="Marque fictive R44", *, revision_attendue=0, **options):
    return client.post(
        "/api/marketing/marque",
        headers={"x-csrf-token": csrf},
        json={
            "mutation_id": "marque-" + nom,
            "revision_attendue": revision_attendue,
            "profil": {
                "name": nom,
                "tagline": "Travaux avec soin",
                "tone": "professionnel et factuel",
                "colors": ["#123456"],
                "langue": "fr",
                **options,
            },
        },
    )


def _action(client, csrf, action, mutation=None, **arguments):
    return client.post(
        "/api/marketing/calendrier",
        headers={"x-csrf-token": csrf},
        json={"action": action, "mutation_id": mutation or action + str(arguments), **arguments},
    )


def _resultat(r):
    assert r.status_code == 200 and r.json()["ok"], r.text
    v = r.json()["resultat"]
    while isinstance(v, dict) and "resultat" in v:
        v = v["resultat"]
    return v


def _contenus(client):
    contenus, decalage = [], 0
    while True:
        r = client.get("/api/marketing/calendrier", params={"decalage": decalage})
        assert r.status_code == 200, r.text
        valeur = r.json()["resultat"]
        contenus.extend(valeur["contenus"])
        decalage = valeur["pagination"]["suivant"]
        if decalage is None:
            return contenus


def _proposer(client, csrf, mutation="proposer-r44"):
    _resultat(_action(client, csrf, "proposer_contenus", mutation, wct_id="wct-r44-fictif"))
    return _contenus(client)


def _creneau(client, csrf, contenu):
    cid = contenu["contenu_id"]
    _resultat(_action(client, csrf, "decider_contenu", "decision-" + cid, contenu_id=cid, decision="approuver"))
    slot = _resultat(
        _action(
            client,
            csrf,
            "proposer_creneau",
            "slot-" + cid,
            contenu_id=cid,
            planifie_le=(datetime.now(UTC) + timedelta(days=3)).isoformat(),
        )
    )
    _resultat(
        _action(
            client, csrf, "decider_creneau", "decision-slot-" + cid, creneau_id=slot["creneau_id"], decision="approuver"
        )
    )
    return slot


def _registre(nom):
    with stockage.transaction():
        return list(stockage.maillons("m07-marketing", nom))


def _edition(client, contenu):
    r = client.get("/api/marketing/calendrier/textes/" + contenu["contenu_id"])
    return _resultat(r)


def _reviser(client, csrf, contenu, texte, *, mutation="edition-r44b", preuve=None):
    preuve = preuve or _edition(client, contenu)
    return _action(
        client,
        csrf,
        "reviser_texte",
        mutation=mutation,
        contenu_id=contenu["contenu_id"],
        revision_attendue=preuve["revision"],
        empreinte_texte_attendue=preuve["empreinte_texte"],
        snapshot_attendu=preuve["snapshot_sha256"],
        texte=texte,
    )


def test_propose_modifiable_sans_rejet_et_autres_plateformes_intactes(client):
    csrf = _login(client)
    _resultat(_marque(client, csrf))
    anciens = _proposer(client, csrf)
    contenu = next(c for c in _contenus(client) if c["plateforme"] == "facebook")
    historiques = _registre("contenus_chantier")
    r = _resultat(_reviser(client, csrf, contenu, "Un chantier de gouttières terminé avec soin."))
    assert r["modifie"] is True and r["contenu_id"] != contenu["contenu_id"]
    nouvelle = next(c for c in _contenus(client) if c["plateforme"] == "facebook")
    assert nouvelle["revision"] == 2 and nouvelle["approval_status"] == "PROPOSE"
    assert nouvelle["origine_texte"] == "humain"
    assert nouvelle["decision"] is None and nouvelle["exporte"] is False
    assert _registre("contenus_chantier")[:5] == historiques
    assert len(_registre("contenus_chantier")) == 6
    assert len(anciens) == 5


def test_post_edition_forgé_est_un_refus_metier_pas_action_inconnue(client):
    csrf = _login(client)
    _resultat(_marque(client, csrf))
    _proposer(client, csrf)
    contenu = _contenus(client)[0]
    r = _action(
        client,
        csrf,
        "reviser_texte",
        mutation="preuve-forgee-r44b",
        contenu_id=contenu["contenu_id"],
        revision_attendue=1,
        empreinte_texte_attendue="ab" * 32,
        snapshot_attendu="cd" * 32,
        texte="Un projet de gouttières terminé avec soin.",
    )
    assert r.status_code == 409, r.text
    assert len(_registre("contenus_chantier")) == 5


@pytest.mark.parametrize("plateforme", ["facebook", "instagram", "fiche_google", "video_courte", "demande_temoignage"])
def test_chaque_plateforme_revision_humaine_auteur_serveur(client, plateforme):
    csrf = _login(client)
    _resultat(_marque(client, csrf))
    ancien = next(c for c in _proposer(client, csrf) if c["plateforme"] == plateforme)
    autres = {c["plateforme"]: c for c in _contenus(client) if c["plateforme"] != plateforme}
    _resultat(_reviser(client, csrf, ancien, "Un projet de gouttières terminé avec soin."))
    assert {c["plateforme"]: c for c in _contenus(client) if c["plateforme"] != plateforme} == autres
    nouveau = _registre("contenus_chantier")[-1]
    assert nouveau["origine_texte"] == "humain" and nouveau["approval_status"] == "PROPOSE"
    assert nouveau["edition_humaine"]["par"] == "owner-r44"
    assert nouveau["edition_humaine"]["source"] == "console"
    assert nouveau["edition_humaine"]["ancien_contenu_id"] == ancien["contenu_id"]
    assert nouveau["propose_le"] != "2026-10-01T15:00:00-04:00"
    assert nouveau["utm_content"] != _registre("contenus_chantier")[0]["utm_content"]


@pytest.mark.parametrize("etat", ["APPROVED", "REJECTED"])
def test_reprise_historique_sans_heriter_decision_creneau_export(client, etat):
    csrf = _login(client)
    _resultat(_marque(client, csrf))
    ancien = next(c for c in _proposer(client, csrf) if c["plateforme"] == "facebook")
    slot = None
    if etat == "APPROVED":
        slot = _creneau(client, csrf, ancien)
        _resultat(_action(client, csrf, "exporter_creneau", "export-avant-edition", creneau_id=slot["creneau_id"]))
    else:
        _resultat(
            _action(
                client,
                csrf,
                "decider_contenu",
                "rejet-avant-edition",
                contenu_id=ancien["contenu_id"],
                decision="rejeter",
                motif="À reformuler avec soin",
            )
        )
    historiques = {
        n: _registre(n) for n in ["decisions_contenu", "calendrier_contenus", "exports_calendrier", "dossiers_medias"]
    }
    _resultat(_reviser(client, csrf, ancien, "Un projet de gouttières terminé avec soin."))
    nouveau = next(c for c in _contenus(client) if c["plateforme"] == "facebook")
    assert nouveau["approval_status"] == "PROPOSE" and nouveau["decision"] is None and nouveau["exporte"] is False
    assert {n: _registre(n) for n in historiques} == historiques
    if slot:
        refuse = _action(client, csrf, "exporter_creneau", "export-avant-edition", creneau_id=slot["creneau_id"])
        assert refuse.status_code == 409
        assert _registre("exports_calendrier") == historiques["exports_calendrier"]
    media = client.get("/api/marketing/calendrier/medias/" + nouveau["contenu_id"])
    assert media.status_code == 409 and "photos" in media.text  # aucune source photo déclarée dans cette fixture


def test_texte_identique_noop_replay_et_conflit(client):
    csrf = _login(client)
    _resultat(_marque(client, csrf))
    ancien = _proposer(client, csrf)[0]
    preuve = _edition(client, ancien)
    noop = _resultat(_reviser(client, csrf, ancien, ancien["texte"], preuve=preuve, mutation="noop"))
    assert noop["modifie"] is False and len(_registre("contenus_chantier")) == 5
    texte = "Un projet de gouttières terminé avec soin."
    premier = _reviser(client, csrf, ancien, texte, preuve=preuve)
    _resultat(premier)
    avant = _registre("contenus_chantier")
    replay = _reviser(client, csrf, ancien, texte, preuve=preuve)
    assert _resultat(replay) == _resultat(premier) and replay.json()["resultat"]["rejoue"] is True
    conflit = _reviser(client, csrf, ancien, "Une autre formulation de gouttières terminées.", preuve=preuve)
    assert conflit.status_code == 409
    stale = _reviser(client, csrf, ancien, texte, preuve=preuve, mutation="nouvelle-cle-vieille-preuve")
    assert stale.status_code == 409 and _registre("contenus_chantier") == avant


@pytest.mark.parametrize(
    "texte",
    [
        "",
        "  ",
        "Meilleur prix garanti demain",
        "Merci à Mme Tremblay pour sa confiance.",
        "Terminé au 1234 rue des Érables.",
        "Prix 4 500 $",
        "https://fictif.ca/prix",
        "wct-r44-fictif",
        "x" * 2001,
        "\ud800",
    ],
)
def test_textes_invalides_refusent_sans_append(client, texte):
    csrf = _login(client)
    _resultat(_marque(client, csrf))
    ancien = _proposer(client, csrf)[0]
    preuve = _edition(client, ancien)
    before = _registre("contenus_chantier")
    if texte == "\ud800":
        import json

        corps = {
            "action": "reviser_texte",
            "mutation_id": "unicode-invalide",
            "contenu_id": ancien["contenu_id"],
            "revision_attendue": preuve["revision"],
            "empreinte_texte_attendue": preuve["empreinte_texte"],
            "snapshot_attendu": preuve["snapshot_sha256"],
            "texte": texte,
        }
        r = client.post(
            "/api/marketing/calendrier",
            content=json.dumps(corps, ensure_ascii=True),
            headers={"x-csrf-token": csrf, "content-type": "application/json"},
        )
    else:
        r = _reviser(client, csrf, ancien, texte, preuve=preuve)
    assert r.status_code in {400, 409}, r.text
    assert _registre("contenus_chantier") == before


@pytest.mark.parametrize("change", ["marque", "wct"])
def test_cas_source_complete_changee_pas_seulement_hash_declare(client, session, change):
    csrf = _login(client)
    _resultat(_marque(client, csrf))
    ancien = _proposer(client, csrf)[0]
    preuve = _edition(client, ancien)
    if change == "marque":
        _resultat(_marque(client, csrf, "Autre marque fictive", revision_attendue=1))
    else:
        with session() as cnx:
            wct = _registre("wct_recus")[0]
            wct["description_factuelle"] = "Description fictive modifiée, hash déclaré conservé"
            cnx.execute(
                update(REGISTRES)
                .where(REGISTRES.c.departement == "m07-marketing", REGISTRES.c.registre == "wct_recus")
                .values(maillon=codec.encoder(wct))
            )
    before = _registre("contenus_chantier")
    r = _reviser(client, csrf, ancien, "Un projet de gouttières terminé avec soin.", preuve=preuve)
    assert r.status_code == 409 and _registre("contenus_chantier") == before


@pytest.mark.parametrize("retrait", ["role", "consentement"])
def test_permission_et_retrait_vivants_avant_recu_historique(client, session, retrait):
    csrf = _login(client)
    _resultat(_marque(client, csrf))
    ancien = _proposer(client, csrf)[0]
    preuve = _edition(client, ancien)
    texte = "Un projet de gouttières terminé avec soin."
    _resultat(_reviser(client, csrf, ancien, texte, preuve=preuve))
    before = _registre("contenus_chantier")
    if retrait == "role":
        with session() as cnx:
            identite.retirer_role(cnx, "owner-r44", "nathan_owner")
    else:
        outil = next(o for o in outils_m7.outils() if o.nom == "m7_enregistrer_retrait_consentement_marketing")
        with contexte.appele_par_appareil(contexte.IdentiteAppelante("owner-r44", "admin")):
            r = executer_atomique(
                outil, {"wct_id": "wct-r44-fictif", "canal": "courriel", "horodatage": "2026-10-02T15:00:00+00:00"}
            )
            assert r["ok"] and r["resultat"]["accepte"]
    r = _reviser(client, csrf, ancien, texte, preuve=preuve)
    assert r.status_code == (403 if retrait == "role" else 409), r.text
    assert _registre("contenus_chantier") == before


def test_csrf_admin_injection_et_catalogue_prive(client):
    csrf = _login(client)
    _resultat(_marque(client, csrf))
    ancien = _proposer(client, csrf)[0]
    preuve = _edition(client, ancien)
    assert (
        _reviser(client, "incorrect", ancien, "Un projet de gouttières terminé avec soin.", preuve=preuve).status_code
        == 403
    )
    admin = _login(client, "admin-r44")
    assert (
        _reviser(client, admin, ancien, "Un projet de gouttières terminé avec soin.", preuve=preuve).status_code == 403
    )
    assert client.get("/api/marketing/calendrier/textes/" + ancien["contenu_id"]).status_code == 403
    noms = {o.nom for o in outils_m7.outils()}
    assert "m7_reviser_texte_humain" not in noms and "m7_lire_edition_texte_humain" not in noms
    assert len(_registre("contenus_chantier")) == 5


def test_deux_ecrivains_meme_cas_un_append(client):
    from concurrent.futures import ThreadPoolExecutor

    csrf = _login(client)
    _resultat(_marque(client, csrf))
    ancien = _proposer(client, csrf)[0]
    preuve = _edition(client, ancien)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(
            pool.map(
                lambda n: (
                    _reviser(
                        client,
                        csrf,
                        ancien,
                        "Un projet de gouttières terminé avec soin.",
                        preuve=preuve,
                        mutation="ecrivain-" + str(n),
                    ).status_code
                ),
                range(2),
            )
        )
    assert sorted(results) == [200, 409] and len(_registre("contenus_chantier")) == 6


def test_vrai_formulaire_edition_et_html_echappe(client):
    import html

    csrf = _login(client)
    _resultat(_marque(client, csrf))
    ancien = _proposer(client, csrf)[0]
    preuve = _edition(client, ancien)
    page = client.get("/marketing/calendrier")
    assert page.status_code == 200 and 'name="texte"' in page.text and "Modifier le texte" in page.text
    texte = "Un chantier de gouttières terminé avec soin <b>soigné</b>."
    r = client.post(
        "/marketing/calendrier",
        data={
            "action": "reviser_texte",
            "csrf": csrf,
            "mutation_id": "formulaire-r44b",
            "contenu_id": ancien["contenu_id"],
            "revision_attendue": str(preuve["revision"]),
            "empreinte_texte_attendue": preuve["empreinte_texte"],
            "snapshot_attendu": preuve["snapshot_sha256"],
            "texte": texte,
        },
    )
    assert r.status_code == 200, r.text
    assert texte not in r.text and html.escape(texte) in r.text
    assert _registre("contenus_chantier")[-1]["texte"] == texte
    assert "Dernière correction : owner-r44" in r.text


@pytest.mark.parametrize(
    "champ,valeur",
    [("revision_attendue", True), ("snapshot_attendu", "zz" * 32), ("par", "owner-forge"), ("plateforme", "facebook")],
)
def test_contrat_ferme_et_pas_identite_libre(client, champ, valeur):
    csrf = _login(client)
    _resultat(_marque(client, csrf))
    ancien = _proposer(client, csrf)[0]
    preuve = _edition(client, ancien)
    corps = {
        "action": "reviser_texte",
        "mutation_id": "champ-invalide",
        "contenu_id": ancien["contenu_id"],
        "revision_attendue": preuve["revision"],
        "empreinte_texte_attendue": preuve["empreinte_texte"],
        "snapshot_attendu": preuve["snapshot_sha256"],
        "texte": "Un chantier de gouttières terminé avec soin.",
        champ: valeur,
    }
    r = client.post("/api/marketing/calendrier", json=corps, headers={"x-csrf-token": csrf})
    assert r.status_code == 400 and len(_registre("contenus_chantier")) == 5


@pytest.mark.parametrize(
    "charge",
    [
        "{invalid",
        '{"__opsys__":"decimal","v":"invalid"}',
        '{"__opsys__":"bytes","v":null}',
        '{"__opsys__":"dict","v":null}',
        '"x"',
        '"' + "x" * 65536 + '"',
    ],
)
def test_source_codec_et_bornes_refusent_diagnostic_ferme(client, session, charge):
    csrf = _login(client)
    _resultat(_marque(client, csrf))
    ancien = _proposer(client, csrf)[0]
    with session() as cnx:
        cnx.execute(
            update(REGISTRES)
            .where(REGISTRES.c.departement == "m07-marketing", REGISTRES.c.registre == "wct_recus")
            .values(maillon=charge)
        )
    r = client.get("/api/marketing/calendrier/textes/" + ancien["contenu_id"])
    assert r.status_code == 409 and r.json()["ok"] is False
    assert "source" in r.text and len(_registre("contenus_chantier")) == 5


def test_retrait_du_role_entre_validation_et_effet_refuse(client, monkeypatch):
    from m7_marketing.usine import chantier

    csrf = _login(client)
    _resultat(_marque(client, csrf))
    ancien = _proposer(client, csrf)[0]
    preuve = _edition(client, ancien)
    preparer = chantier.preparer

    def retrait_pendant_controle(*args, **kwargs):
        preparation = preparer(*args, **kwargs)
        identite.retirer_role(stockage.connexion_courante(), "owner-r44", "nathan_owner")
        return preparation

    monkeypatch.setattr(chantier, "preparer", retrait_pendant_controle)
    r = _reviser(client, csrf, ancien, "Un chantier de gouttières terminé avec soin.", preuve=preuve)
    assert r.status_code == 409 and len(_registre("contenus_chantier")) == 5


def test_backend_autre_refuse_avant_recu_et_append(client, session, monkeypatch):
    from opsys.console import metier
    from opsys.console.securite import Session
    from opsys.departements import charger_departements
    from opsys.stockage.schema import MUTATIONS_APPLIQUEES

    csrf = _login(client)
    _resultat(_marque(client, csrf))
    ancien = _proposer(client, csrf)[0]
    preuve = _edition(client, ancien)
    with session() as cnx:
        avant = list(cnx.execute(MUTATIONS_APPLIQUEES.select()))
        with monkeypatch.context() as m:
            m.setattr(cnx.engine.dialect, "name", "autre_backend_non_qualifie")
            r = metier.executer(
                cnx,
                charger_departements(),
                Session(
                    "owner-r44", frozenset({"admin", "nathan_owner"}), csrf, int(datetime.now(UTC).timestamp()) + 3600
                ),
                "m7_reviser_texte_humain",
                {},
                mutation_id="backend-refuse",
            )
        assert r["accepte"] is False and r["verdict"]["code"] == "REJ-TEXTE-ECRITURE-NON-QUALIFIEE"
        assert list(cnx.execute(MUTATIONS_APPLIQUEES.select())) == avant
    assert len(_registre("contenus_chantier")) == 5 and preuve["revision"] == 1


def test_revue_media_reelle_non_heritee_et_export_nouveau_requiert_decisions(client, session):
    import base64
    import hashlib
    import struct
    import zlib

    from opsys import fichiers

    def png(pixel):
        def bloc(nom, contenu):
            charge = nom + contenu
            return struct.pack(">I", len(contenu)) + charge + struct.pack(">I", zlib.crc32(charge))

        return (
            b"\x89PNG\r\n\x1a\n"
            + bloc(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + bloc(b"IDAT", zlib.compress(b"\x00" + pixel))
            + bloc(b"IEND", b"")
        )

    source_png = png(b"\x11\x22\x33")
    sha = hashlib.sha256(source_png).hexdigest()
    reference = fichiers.reference_pour(sha)
    with session() as cnx:
        depot = fichiers.deposer_bloc(
            cnx, sha, len(source_png), "image/png", 0, 1, base64.b64encode(source_png).decode("ascii")
        )
        assert depot.accepte and depot.complet
        wct = _registre("wct_recus")[0]
        wct["photos"] = [reference]
        cnx.execute(
            update(REGISTRES)
            .where(REGISTRES.c.departement == "m07-marketing", REGISTRES.c.registre == "wct_recus")
            .values(maillon=codec.encoder(wct))
        )
    csrf = _login(client)
    _resultat(_marque(client, csrf))
    ancien = next(c for c in _proposer(client, csrf) if c["plateforme"] == "facebook")
    slot = _creneau(client, csrf, ancien)
    url = "/api/marketing/calendrier/medias/" + ancien["contenu_id"]
    dossier = _resultat(client.get(url))
    upload = client.post(
        "/api/marketing/calendrier/medias",
        headers={"x-csrf-token": csrf},
        data={
            "mutation_id": "media-depot-r44b",
            "contenu_id": ancien["contenu_id"],
            "source_ref": reference,
            "revision_attendue": str(dossier["revision"]),
            "empreinte_attendue": dossier["empreinte_dossier"],
            "snapshot_attendu": dossier["snapshot_sha256"],
            "attestation_humaine": "Préparation manuelle du média fictif vérifiée.",
        },
        files={"fichier": ("prepare-fictif.png", png(b"\x44\x55\x66"), "image/png")},
    )
    assert upload.status_code == 200, upload.text
    dossier = _resultat(client.get(url))
    _resultat(
        _action(
            client,
            csrf,
            "decider_medias",
            "media-revue-r44b",
            contenu_id=ancien["contenu_id"],
            decision="approuver",
            revision_attendue=dossier["revision"],
            empreinte_attendue=dossier["empreinte_dossier"],
            snapshot_attendu=dossier["snapshot_sha256"],
            attestation_humaine="Visages, plaques et adresse vérifiés manuellement dans ce média fictif.",
        )
    )
    medias_historiques = _registre("dossiers_medias")
    assert _resultat(client.get(url))["statut"] == "APPROUVE"
    _resultat(_reviser(client, csrf, ancien, "Un projet de gouttières terminé avec soin."))
    nouveau = next(c for c in _contenus(client) if c["plateforme"] == "facebook")
    dossier_neuf = _resultat(client.get("/api/marketing/calendrier/medias/" + nouveau["contenu_id"]))
    assert dossier_neuf["revision"] == 0 and dossier_neuf["medias"] == [] and dossier_neuf["statut"] != "APPROUVE"
    assert _registre("dossiers_medias") == medias_historiques
    assert client.get(url).status_code == 409  # ancienne source remplacée, pas nouvelle remise
    assert (
        _action(client, csrf, "remettre_medias", "ancien-media-remise", creneau_id=slot["creneau_id"]).status_code
        == 409
    )
    _resultat(
        _action(
            client,
            csrf,
            "decider_contenu",
            "nouveau-texte-approve",
            contenu_id=nouveau["contenu_id"],
            decision="approuver",
        )
    )
    slot_neuf = _resultat(
        _action(
            client,
            csrf,
            "proposer_creneau",
            "nouveau-slot",
            contenu_id=nouveau["contenu_id"],
            planifie_le=(datetime.now(UTC) + timedelta(days=3)).isoformat(),
        )
    )
    assert (
        _action(
            client, csrf, "exporter_creneau", "export-avant-decision", creneau_id=slot_neuf["creneau_id"]
        ).status_code
        == 409
    )
    _resultat(
        _action(
            client,
            csrf,
            "decider_creneau",
            "nouveau-slot-approve",
            creneau_id=slot_neuf["creneau_id"],
            decision="approuver",
        )
    )
    _resultat(_action(client, csrf, "exporter_creneau", "nouveau-export", creneau_id=slot_neuf["creneau_id"]))
    assert _registre("dossiers_medias") == medias_historiques
