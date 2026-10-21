"""Monde explicitement fictif : recherche métier par affaire, sans écriture ni accès privé."""

import json

import pytest
from m10_memoire import amont, classification, consolidation, encodage, outils, paquets, registre
from m10_memoire import contexte as references
from sqlalchemy import text

from opsys import contexte, identite, stockage
from opsys.contexte import IdentiteAppelante
from opsys.outils import Autonomie, Niveau, executer_atomique

FICTIF = True
LEAD = "LEAD-RECHERCHE-FICTIF"
DATE = "2026-10-08T09:00:00-04:00"
NOM = "m10_rechercher_affaire_appareil"


def _outil():
    candidats = [o for o in outils.outils() if o.nom == NOM]
    assert candidats, "La lecture canonique DEVICE par affaire manque au catalogue métier"
    return candidats[0]


@pytest.fixture
def monde(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'recherche-fictive.db'}"
    monkeypatch.setenv(stockage.ENV_URL, url)
    stockage.migrer(url)
    monkeypatch.setattr(identite, "hacher_mot_de_passe", lambda _: "fictif-non-authentifiable")
    with stockage.transaction() as cnx:
        for p, role, actif in [
            ("admin.fictif", "admin", True),
            ("employee.fictif", "employee", True),
            ("seller.fictif", "seller", True),
            ("inactif.fictif", "admin", False),
        ]:
            identite.creer_personne(cnx, p, p, "mot-de-passe-fictif", [role], actif=actif)
    e, a = registre.Registre(), registre.Registre()
    monkeypatch.setattr(outils, "_REGISTRE_EVENEMENTS", e)
    monkeypatch.setattr(outils, "_REGISTRE_AFFAIRES", a)
    yield e, a
    stockage.liberer()


def _wct(e, ident="WCT-FICTIF", lead=LEAD, date=DATE, **extra):
    return e.ajouter(
        {
            "type_entree": "evenement_memorise",
            "horodatage": date,
            "wct_id": ident,
            "lead_id": lead,
            "duree_reelle_minutes": 90,
            "ecart_signale": False,
            **extra,
        }
    )


def _fait(a, source, resume="Résumé fictif", jour="2026-10-08", lead=LEAD, **extra):
    return a.ajouter(
        {
            "type_entree": "fait_consolide",
            "horodatage": DATE,
            "affaire_id": lead,
            "jour": jour,
            "cle_consolidation": f"{lead}:{jour}",
            "resume": resume,
            "sources": [
                {
                    "registre": "evenements",
                    "ligne_id": source["ligne_id"],
                    "type_evenement": classification.type_evenement(source),
                    "identifiant": classification.identifiant(source),
                }
            ],
            **extra,
        }
    )


def _appel(lead=LEAD, query="", limite=8, decalage=0, personne="admin.fictif", role="admin", **extra):
    with contexte.appele_par_appareil(IdentiteAppelante(personne, role)):
        return executer_atomique(
            _outil(), {"affaire_id": lead, "requete": query, "limite": limite, "decalage": decalage, **extra}
        )


def _dto(**args):
    r = _appel(**args)
    assert r["ok"] is True and "resultats" in r["resultat"], r
    return r["resultat"]


def _refus(r, suffix):
    assert r["ok"] is True and r["resultat"]["accepte"] is False, r
    assert r["resultat"]["verdict"]["code"] == "REJ-RECHERCHE-AFFAIRE-" + suffix
    assert "CANARY" not in json.dumps(r)


def test_lecture_declaree_t0_n0_admin_schema_ferme(monde):
    o = _outil()
    assert o.autonomie is Autonomie.T0 and o.niveau_effectif is Niveau.N0
    assert o.roles_appareil == frozenset({"admin"})
    assert set(o.parametres["required"]) == {"affaire_id", "requete", "limite", "decalage"}
    assert o.parametres["additionalProperties"] is False


def test_evenement_reference_exacte_et_lecture_sans_changement(monde):
    e, a = monde
    ligne = _wct(e)
    _wct(e, "WCT-PRIVE", confidentialite="CLIENT_PRIVATE")
    avant = e.lire(), a.lire()
    d = _dto()
    assert set(d) == {
        "affaire_id",
        "requete",
        "mode",
        "corpus",
        "resultats",
        "affaire",
        "pagination",
        "couverture",
        "confidentialite",
        "borne_caracteres",
        "taille_caracteres",
    }
    assert d["resultats"] == [
        {
            "genre": "evenement",
            "affaire_id": LEAD,
            "identifiant": "WCT-FICTIF",
            "horodatage": DATE,
            "source": "m4.travaux_termines",
            "resume": "WCT WCT-FICTIF : durée réelle 90 min",
            "confidentialite": "INTERNAL",
            "reference": {"ligne_id": ligne, "registre": "evenements", "hash_tete": ligne},
        }
    ]
    assert d["pagination"] == {
        "decalage": 0,
        "limite": 8,
        "affichees": 1,
        "total": 1,
        "suivant": None,
        "reste": 0,
        "courante": True,
    }
    assert d["confidentialite"] == {"agent": None, "regle": "v1", "niveaux": ["PUBLIC_INTERNAL", "INTERNAL"]}
    assert d["taille_caracteres"] == len(json.dumps({"ok": True, "resultat": d}, ensure_ascii=False)) <= 5400
    assert avant == (e.lire(), a.lire())
    assert d["affaire"] == {
        "connue": True,
        "origine_recue": False,
        "origine": None,
        "verdict": "AMONT-ORIGINE-NON-RECUE",
    }
    prefixe = registre.Registre(maillons=e.lire()[:1])
    assert references.verifier_reference(d["resultats"][0]["reference"], prefixe)[1] is None


def test_match_ancien_hors_des_cinq_faits_du_paquet(monde):
    e, a = monde
    for i in range(9):
        _wct(e, f"WCT-ANCIEN-{i}", date=f"2026-10-0{1 + i}T09:00:00-04:00")
    paquet = paquets.assembler_paquet_contexte(LEAD, DATE, e, a, agent=None)
    assert not any(f["identifiant"] == "WCT-ANCIEN-0" for c in paquet["couches"] for f in c["faits"])
    assert [r["identifiant"] for r in _dto(query="ancien-0")["resultats"]] == ["WCT-ANCIEN-0"]


def test_latest_consolidation_avant_confidentialite_sans_resurrection(monde):
    e, a = monde
    _wct(e)
    source = e.lire()[0]
    _fait(a, source, "Ancien visible CANARY")
    _fait(a, source, "Dernier privé CANARY", confidentialite="CLIENT_PRIVATE")
    d = _dto(query="CANARY")
    assert d["pagination"]["total"] == 0 and d["resultats"] == []
    assert d["affaire"]["connue"] is True
    _fait(a, source, "Dernier courant autorisé")
    d = _dto(query="m10:consolidation")
    assert len(d["resultats"]) == 1 and d["resultats"][0]["source"] == "m10:consolidation"
    assert d["resultats"][0]["resume"] == "2026-10-08 : Dernier courant autorisé"
    assert d["affaire"]["connue"] is True and not d["affaire"]["origine_recue"]


@pytest.mark.parametrize(
    "niveau", ["CLIENT_PRIVATE", "FINANCIAL", "SENSITIVE", "SECRET_REF", "LEGAL_LOCKED", "inconnu"]
)
def test_confidentialite_avant_compte_page_et_affaire(monde, niveau):
    e, _ = monde
    _wct(e, "WCT-CANARY-PRIVE", confidentialite=niveau)
    d = _dto(query="CANARY", limite=1)
    assert d["resultats"] == [] and d["pagination"]["total"] == 0 and not d["affaire"]["connue"]
    assert set(d["confidentialite"]) == {"agent", "regle", "niveaux"}


@pytest.mark.parametrize("query", ["777.77", "CANARY-VERDICT", "EV-FIN-CANARY"])
def test_financier_non_marque_et_hybride_exclus_par_taxonomie(monde, query):
    e, _ = monde
    _wct(e)
    e.ajouter(
        {
            "type_entree": "evenement_memorise",
            "horodatage": DATE,
            "evenement_id": "EV-FIN-CANARY",
            "wct_id": "WCT-FICTIF",
            "marge_reelle_cad": "777.77",
            "verdict": "CANARY-VERDICT",
            "statut_variance": "CANARY-VERDICT",
        }
    )
    d = _dto(query=query)
    assert d["pagination"]["total"] == 0
    assert all(
        x not in json.dumps({k: v for k, v in d.items() if k != "requete"})
        for x in ["777.77", "CANARY-VERDICT", "EV-FIN-CANARY"]
    )


def test_variance_ne_peut_utiliser_un_wct_prive_pour_lier_affaire(monde):
    e, _ = monde
    _wct(e, "WCT-SECRET", confidentialite="CLIENT_PRIVATE")
    e.ajouter(
        {
            "type_entree": "evenement_memorise",
            "horodatage": DATE,
            "evenement_id": "VAR-VISIBLE",
            "wct_id": "WCT-SECRET",
            "statut_variance": "conforme",
        }
    )
    d = _dto()
    assert not d["affaire"]["connue"] and d["pagination"]["total"] == 0
    _wct(e, "WCT-SECRET")
    assert _dto(query="VAR-VISIBLE")["pagination"]["total"] == 1


def test_developpement_et_payload_brut_non_recherches(monde):
    e, a = monde
    e.ajouter(
        {
            "type_entree": "memoire_developpement",
            "horodatage": DATE,
            "lead_id": LEAD,
            "resume": "CANARY-DEV",
            "contenu": {"cache": "CANARY-DEV"},
        }
    )
    a.ajouter({"type_entree": "memoire_developpement", "horodatage": DATE, "resume": "CANARY-DEV"})
    _wct(e, technicien_id="CANARY-CHAMP-BRUT", secret_fictif="CANARY-CHAMP-BRUT")
    assert _dto(query="CANARY")["pagination"]["total"] == 0
    assert "developpement" in _dto()["couverture"]["hors_corpus"]


def test_recherche_unicode_nfc_casefold_litterale_et_resume_couvert(monde):
    e, a = monde
    _wct(e)
    _fait(a, e.lire()[0], "ÉTÉ Straße .*_()'🙂 " + "X" * 220 + "CANARY-HORS-RESUME")
    for q in ["e\u0301te\u0301", "STRASSE", ".*_()'🙂"]:
        d = _dto(query=q)
        assert d["pagination"]["total"] == 1
    assert _dto(query="CANARY-HORS-RESUME")["pagination"]["total"] == 0
    assert _dto(query="e\u0301te\u0301")["requete"] == "été"
    assert _dto(query=".")["pagination"]["total"] == 2  # Les deux sources contiennent un point littéral.
    assert _dto(query=".*X+")["pagination"]["total"] == 0


def test_situation_visible_origine_et_opportunite_exacte(monde):
    e, _ = monde
    r, v = amont.memoriser(
        "m1.lead_qualifie",
        {
            "lead": {"lead_id": LEAD, "service": "gouttieres", "urgence_declaree": False, "canal": "texte"},
            "horodatage": DATE,
        },
        e,
    )
    assert r is not None and v is None
    _wct(e, lead=LEAD + "~opp~WCT-ORIGINE")
    d = _dto()
    assert d["affaire"]["origine"] == "m1.lead_qualifie"
    assert _dto(lead=LEAD + "~opp~WCT-ORIGINE")["pagination"]["total"] == 1
    assert all(r["affaire_id"] == LEAD for r in d["resultats"])


def test_pages_courantes_filtrees_et_offset_hors_total(monde):
    e, _ = monde
    _wct(e, "WCT-1", date="2026-10-08T13:00:00+00:00")
    _wct(e, "WCT-2", date="2026-10-08T09:01:00-04:00")
    _wct(e, "WCT-HIDDEN", date="2026-10-09T09:00:00-04:00", confidentialite="FINANCIAL")
    d = _dto(limite=1)
    assert [r["identifiant"] for r in d["resultats"]] == ["WCT-2"]
    assert d["pagination"]["total"] == 2 and d["pagination"]["suivant"] == 1
    _wct(e, "WCT-3", date="2026-10-08T09:02:00-04:00")
    assert _dto(limite=1, decalage=1)["resultats"][0]["identifiant"] == "WCT-2"
    d = _dto(decalage=10000)
    assert d["resultats"] == [] and d["pagination"] == {
        "decalage": 10000,
        "limite": 8,
        "affichees": 0,
        "total": 3,
        "suivant": None,
        "reste": 0,
        "courante": True,
    }


@pytest.mark.parametrize(
    "args",
    [
        {"lead": "../CANARY"},
        {"query": "A" * 201},
        {"query": "a\n"},
        {"query": "\ud800"},
        {"limite": 0},
        {"limite": 9},
        {"decalage": -1},
        {"decalage": 10001},
    ],
)
def test_arguments_nominalement_refuses(monde, args):
    _refus(_appel(**args), "ARGUMENTS-INVALIDES")


@pytest.mark.parametrize(
    "extra",
    [{"agent": "m01-front-office"}, {"role": "admin"}, {"personne": "autrui"}, {"budget": 999999}, {"limite": True}],
)
def test_schema_rejette_les_elargissements(monde, extra):
    args = {"affaire_id": LEAD, "requete": "", "limite": 8, "decalage": 0, **extra}
    with contexte.appele_par_appareil(IdentiteAppelante("admin.fictif", "admin")):
        r = executer_atomique(_outil(), args)
    assert not r["ok"] and r["erreur"] == "arguments_invalides"


@pytest.mark.parametrize(
    "personne,role",
    [
        ("employee.fictif", "employee"),
        ("seller.fictif", "seller"),
        ("employee.fictif", "admin"),
        ("inactif.fictif", "admin"),
        ("absent.fictif", "admin"),
    ],
)
def test_roles_invalides_avant_tout_registre(monde, monkeypatch, personne, role):
    class Interdit:
        def lire(self):
            raise AssertionError("registre accédé avant rôle courant")

    monkeypatch.setattr(outils, "_REGISTRE_EVENEMENTS", Interdit())
    monkeypatch.setattr(outils, "_REGISTRE_AFFAIRES", Interdit())
    r = _appel(personne=personne, role=role)
    assert r["ok"] and r["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"


def test_admin_revoque_agent_et_hors_transaction_refuses(monde, monkeypatch):
    class Interdit:
        def lire(self):
            raise AssertionError("registre accédé sans identité courante")

    monkeypatch.setattr(outils, "_REGISTRE_EVENEMENTS", Interdit())
    monkeypatch.setattr(outils, "_REGISTRE_AFFAIRES", Interdit())
    with stockage.transaction() as cnx:
        identite.retirer_role(cnx, "admin.fictif", "admin")
    assert _appel()["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    r = executer_atomique(_outil(), {"affaire_id": LEAD, "requete": "", "limite": 8, "decalage": 0})
    assert r["resultat"]["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"
    with contexte.appele_par_appareil(IdentiteAppelante("admin.fictif", "admin")):
        assert outils.rechercher_affaire_appareil(LEAD)["verdict"]["code"] == "REJ-IDENTITE-APPAREIL-INVALIDE"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda m: m.update(ligne_id="x" * 64),
        lambda m: m.update(horodatage="2026-01-01"),
        lambda m: m.update(type_entree="inconnu"),
    ],
)
def test_corruption_registre_refus_nominal(monde, mutation):
    e, _ = monde
    _wct(e)
    mutation(e._chain[0])
    _refus(_appel(), "REGISTRE-INVALIDE")


@pytest.mark.parametrize(
    "champ,valeur",
    [
        ("wct_id", {"CANARY": "objet"}),
        ("wct_id", "WCT\nCANARY"),
        ("wct_id", "X" * 257),
        ("duree_reelle_minutes", {"CANARY": 1}),
    ],
)
def test_projection_invalide_refuse_sans_raw(monde, champ, valeur):
    e, _ = monde
    _wct(e, **{champ: valeur})
    _refus(_appel(), "PROJECTION-INVALIDE")


def test_borne_sources_apres_deux_copies_unique(monde, monkeypatch):
    class Source:
        def __init__(self, lignes):
            self.lignes, self.copies = lignes, 0

        def lire(self):
            self.copies += 1
            return self.lignes.copy()

    e, a = Source([{}] * 10000), Source([{}])
    monkeypatch.setattr(outils, "_REGISTRE_EVENEMENTS", e)
    monkeypatch.setattr(outils, "_REGISTRE_AFFAIRES", a)
    _refus(_appel(), "BORNE-SOURCES")
    assert e.copies == a.copies == 1


def test_sortie_reduit_page_sans_tronquer_et_sans_artefact(monde):
    e, _ = monde
    for i in range(8):
        _wct(e, f"WCT-{i}" + "X" * 220)
    d = _dto()
    assert 0 < d["pagination"]["affichees"] < 8 and d["pagination"]["total"] == 8
    assert d["pagination"]["suivant"] == d["pagination"]["affichees"]
    assert len(json.dumps({"ok": True, "resultat": d}, ensure_ascii=False)) <= 5400
    assert "tronque" not in d and "apercu" not in d


def test_tables_durables_integrales_et_relecture_identique(monde, monkeypatch):
    e = registre.Registre(maillons=stockage.maillons("m10-memoire", "evenements"))
    a = registre.Registre(maillons=stockage.maillons("m10-memoire", "affaires"))
    monkeypatch.setattr(outils, "_REGISTRE_EVENEMENTS", e)
    monkeypatch.setattr(outils, "_REGISTRE_AFFAIRES", a)
    with stockage.transaction():
        _wct(e)

    def tables():
        with stockage.transaction() as cnx:
            names = (
                cnx.execute(
                    text("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")
                )
                .scalars()
                .all()
            )
            return {n: [dict(x) for x in cnx.execute(text(f'SELECT * FROM "{n}"')).mappings()] for n in names}

    avant = tables()
    premier = _appel()
    stockage.liberer()
    assert _appel() == premier
    assert tables() == avant and avant["artefacts"] == []


@pytest.mark.parametrize("prive", ["CLIENT_PRIVATE", "FINANCIAL"])
def test_consolidation_canonique_entierement_retenue_si_source_privee(monde, prive):
    e, a = monde
    _wct(e)
    assert consolidation.consolider_affaire(LEAD, "2026-10-08", DATE, e, a)["ecrit"]
    assert _dto(query="m10:consolidation")["pagination"]["total"] == 1
    _wct(e, "WCT-RETENU", confidentialite=prive)
    assert consolidation.consolider_affaire(LEAD, "2026-10-08", DATE, e, a)["ecrit"]
    assert _dto(query="m10:consolidation")["pagination"]["total"] == 0


def test_consolidation_canonique_retient_source_m5_non_marquee(monde):
    e, a = monde
    _wct(e)
    e.ajouter(
        {
            "type_entree": "evenement_memorise",
            "horodatage": DATE,
            "evenement_id": "FIN-CANARY",
            "wct_id": "WCT-FICTIF",
            "marge_reelle_cad": "777.77",
        }
    )
    assert consolidation.consolider_affaire(LEAD, "2026-10-08", DATE, e, a)["ecrit"]
    assert _dto(query="rentabilité")["pagination"]["total"] == 0
    assert _dto(query="m10:consolidation")["pagination"]["total"] == 0


@pytest.mark.parametrize(
    "sources",
    [
        [],
        [{"registre": "affaires"}],
        [
            {
                "registre": "evenements",
                "ligne_id": "a" * 64,
                "type_evenement": "m4.travaux_termines",
                "identifiant": "WCT-FICTIF",
            }
        ],
    ],
)
def test_consolidation_source_absente_ou_malformee_refuse_nominalement(monde, sources):
    e, a = monde
    _wct(e)
    _fait(a, e.lire()[0], sources=sources)
    _refus(_appel(), "PROJECTION-INVALIDE")


@pytest.mark.parametrize("champ,valeur", [("identifiant", "CANARY-FAUX"), ("type_evenement", "m6.variance_chantier")])
def test_consolidation_source_desaccord_refuse_nominalement(monde, champ, valeur):
    e, a = monde
    _wct(e)
    source = {
        "registre": "evenements",
        "ligne_id": e.lire()[0]["ligne_id"],
        "type_evenement": "m4.travaux_termines",
        "identifiant": "WCT-FICTIF",
        champ: valeur,
    }
    _fait(a, e.lire()[0], sources=[source])
    _refus(_appel(), "PROJECTION-INVALIDE")


def test_consolidation_source_autre_affaire_refuse_nominalement(monde):
    e, a = monde
    _wct(e, lead="AUTRE-AFFAIRE")
    _fait(a, e.lire()[0])
    _refus(_appel(), "PROJECTION-INVALIDE")


@pytest.mark.parametrize("champ,valeur", [("horodatage", "2026-01-01"), ("type_entree", "CANARY-TYPE")])
def test_metadata_invalide_meme_si_chaine_recalculee(monde, champ, valeur):
    e, _ = monde
    _wct(e)
    m = e._chain[0]
    m[champ] = valeur
    corps = {k: v for k, v in m.items() if k not in ("ligne_id", "precedent_ligne_id")}
    m["ligne_id"] = encodage.empreinte(corps, None)
    assert e.valider_chaine()[0]
    _refus(_appel(), "REGISTRE-INVALIDE")


@pytest.mark.parametrize(
    "horodatage",
    ["20261008T09:00:00-04:00", "2026-W41-4T09:00:00-04:00", "2026-10-08T09:00-04:00", "2026-10-08T09:00:00+00:60"],
)
def test_formes_iso_non_partagees_avec_mobile_refusees_nominalement(monde, horodatage):
    e, _ = monde
    _wct(e, date=horodatage)
    assert e.valider_chaine()[0]
    _refus(_appel(), "REGISTRE-INVALIDE")


@pytest.mark.parametrize(
    "horodatage",
    [
        "2026-10-08 09:00:00-04:00",
        "2026-10-08T09:00:00Z",
        "2026-10-08T09:00:00.123456+00:30",
        "2026-10-08T09:00:00,12-04:00",
    ],
)
def test_formes_iso_partagees_conservent_date_verbatim(monde, horodatage):
    e, _ = monde
    _wct(e, date=horodatage)
    assert _dto()["resultats"][0]["horodatage"] == horodatage


@pytest.mark.parametrize("nom", ["_REGISTRE_EVENEMENTS", "_REGISTRE_AFFAIRES"])
def test_erreur_copie_source_refuse_nominalement_sans_texte_brut(monde, monkeypatch, nom):
    class SourceIllisible:
        def lire(self):
            raise ValueError("CANARY-COPIE-SOURCE-JSON-PRIVEE")

    monkeypatch.setattr(outils, nom, SourceIllisible())
    _refus(_appel(), "REGISTRE-INVALIDE")


def test_meme_capacite_separe_affaires_durables_cite_prefixes_et_ne_ressuscite_pas(monde, monkeypatch):
    """Identité SQL et sources fictives ; vraie recherche publique sur deux chaînes SQLite.

    L'admin peut consulter les deux affaires : le test protège la cible demandée, sans inventer
    une permission de locataire, un accès d'agent ou une recherche dans le domaine développement.
    """
    from opsys.capacites import Capacites
    from opsys.departements import charger_departements

    e = registre.Registre(maillons=stockage.maillons("m10-memoire", "evenements"))
    a = registre.Registre(maillons=stockage.maillons("m10-memoire", "affaires"))
    monkeypatch.setattr(outils, "_REGISTRE_EVENEMENTS", e)
    monkeypatch.setattr(outils, "_REGISTRE_AFFAIRES", a)
    capacites = Capacites(charger_departements(), stockage.transaction, filtre={"m10-memoire"}, memoire=False)
    affaire_a, affaire_b = LEAD + "-A", LEAD + "-B"

    def tables():
        with stockage.transaction() as cnx:
            noms = cnx.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )).scalars().all()
            return {n: [dict(ligne) for ligne in cnx.execute(text(f'SELECT * FROM "{n}"')).mappings()] for n in noms}

    def lire(affaire_id, requete=""):
        avant = tables()
        with contexte.appele_par_appareil(IdentiteAppelante("admin.fictif", "admin")):
            reponse = capacites.appeler(
                NOM, {"affaire_id": affaire_id, "requete": requete, "limite": 8, "decalage": 0},
            )
        assert reponse["ok"] is True and "resultats" in reponse["resultat"], reponse
        assert tables() == avant, "chaque lecture conserve toutes les tables, sans artefact"
        dto = reponse["resultat"]
        assert dto["affaire_id"] == affaire_id
        assert all(r["affaire_id"] == affaire_id for r in dto["resultats"])
        return dto

    def verifier_citations(dto):
        with stockage.transaction():
            snapshots = {"evenements": e.lire(), "affaires": a.lire()}
        for resultat in dto["resultats"]:
            ref = resultat["reference"]
            lignes = snapshots[ref["registre"]]
            position = next(i for i, ligne in enumerate(lignes) if ligne["ligne_id"] == ref["ligne_id"])
            source = lignes[position]
            champ = "lead_id" if ref["registre"] == "evenements" else "affaire_id"
            assert source[champ] == dto["affaire_id"], "une citation valide doit aussi être celle de la bonne affaire"
            assert ref["hash_tete"] == ref["ligne_id"]
            prefixe = registre.Registre(maillons=lignes[:position + 1])
            assert prefixe.valider_chaine()[0] is True
            assert references.verifier_reference(ref, prefixe)[1] is None

    assert lire(affaire_a)["resultats"] == []  # chauffe la même capacité avant l'arrivée des sources
    with stockage.transaction():
        evenement_a = _wct(e, "WCT-CF036-A-FICTIF", lead=affaire_a)
        evenement_b = _wct(e, "WCT-CF036-B-FICTIF", lead=affaire_b)
        conso_a = consolidation.consolider_affaire(affaire_a, "2026-10-08", DATE, e, a)
        conso_b = consolidation.consolider_affaire(affaire_b, "2026-10-08", DATE, e, a)
        assert conso_a["ecrit"] and conso_b["ecrit"]
        anciens_evenements, anciens_faits = e.lire(), a.lire()

    lus_a, lus_b = lire(affaire_a), lire(affaire_b)
    for dto, evenement, fait in ((lus_a, evenement_a, conso_a), (lus_b, evenement_b, conso_b)):
        assert dto["pagination"]["total"] == len(dto["resultats"]) == 2
        assert {(r["reference"]["registre"], r["reference"]["ligne_id"]) for r in dto["resultats"]} == {
            ("evenements", evenement), ("affaires", fait["fait"]["ligne_id"]),
        }
        verifier_citations(dto)
    assert affaire_b not in json.dumps(lus_a, ensure_ascii=False)
    assert affaire_a not in json.dumps(lus_b, ensure_ascii=False)

    ref_b = next(r["reference"] for r in lus_b["resultats"] if r["reference"]["registre"] == "evenements")
    prefixe_b = registre.Registre(maillons=anciens_evenements)
    assert references.verifier_reference({**ref_b, "hash_tete": evenement_a}, prefixe_b)[1] is not None

    with stockage.transaction():
        _wct(e, "WCT-CF036-A-PRIVE-FICTIF", lead=affaire_a, confidentialite="CLIENT_PRIVATE")
        courante_a = consolidation.consolider_affaire(affaire_a, "2026-10-08", DATE, e, a)
        assert courante_a["ecrit"] and courante_a["fait"]["ligne_id"] != conso_a["fait"]["ligne_id"]
        assert e.lire()[:2] == anciens_evenements and a.lire()[:2] == anciens_faits
        assert e.valider_chaine()[0] is True and a.valider_chaine()[0] is True
    retenue = lire(affaire_a, "m10:consolidation")
    assert retenue["resultats"] == [] and retenue["pagination"]["total"] == 0
    assert retenue["affaire"]["connue"] is True
    autorisee_b = lire(affaire_b, "m10:consolidation")
    assert len(autorisee_b["resultats"]) == 1
    assert autorisee_b["resultats"][0]["reference"]["ligne_id"] == conso_b["fait"]["ligne_id"]
    verifier_citations(autorisee_b)

    stockage.liberer()
    assert lire(affaire_a, "m10:consolidation")["resultats"] == []
    apres_reouverture_b = lire(affaire_b)
    assert apres_reouverture_b["resultats"] == lus_b["resultats"]
    verifier_citations(apres_reouverture_b)
