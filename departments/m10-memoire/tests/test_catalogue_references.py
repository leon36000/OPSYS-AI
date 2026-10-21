"""Catalogue métier : données fictives, aucune identité ou mémoire de développement."""

import json
from copy import deepcopy

import pytest
from m10_memoire import contexte, decisions, encodage, registre, revision

FICTIF = True
DATE = "2026-10-07T09:00:00-04:00"
DATE_2 = "2026-10-07T10:00:00-04:00"
SECRET = "Texte confidentiel fictif à ne jamais restituer"


def _lister(reg, **args):
    from m10_memoire.catalogue_references import lister_references

    return lister_references(reg, **args)


def _decision(reg, identifiant="Décision 😀 opaque", statut="proposee", niveau=None, date=DATE):
    maillon, erreur = decisions.enregistrer_decision(
        {"decision_id": identifiant, "raison": SECRET, "statut": statut, "options_ecartees": SECRET},
        reg,
        date,
        niveau,
    )
    assert erreur is None
    return maillon


def _revision(reg):
    a, b = _decision(reg, "DEC-A"), _decision(reg, "DEC-B")
    signalee, erreur = revision.signaler_revision(reg, a["ligne_id"], b["ligne_id"], DATE)
    assert erreur is None
    arbitrage, erreur = revision.arbitrer_revision(reg, signalee["ligne_id"], "distincts_confirmes", DATE_2)
    assert erreur is None
    return a, b, signalee, arbitrage


def _enveloppe(resultat):
    return {"ok": True, "resultat": {"accepte": True, "resultat": resultat}}


def test_references_canoniques_dernier_statut_et_dates_sans_texte_libre():
    reg = registre.Registre()
    a, b, sig, arb = _revision(reg)
    actuel = _decision(reg, "DEC-A", "validee", date=DATE_2)
    avant = reg.lire()
    resultat, verdict = _lister(reg)
    assert verdict is None
    assert resultat["affichees"] == 3
    assert {d["decision_id"]: d["statut"] for d in resultat["decisions"]} == {"DEC-A": "validee", "DEC-B": "proposee"}
    assert (
        next(d for d in resultat["decisions"] if d["decision_id"] == "DEC-A")["reference"]["ligne_id"]
        == actuel["ligne_id"]
    )
    r = resultat["revisions"][0]
    assert r == {
        "genre": "revision",
        "revision_ligne_id": sig["ligne_id"],
        "statut": "distincts_confirmes",
        "signalee_le": DATE,
        "statut_le": DATE_2,
        "reference": {"registre": "affaires", "ligne_id": sig["ligne_id"], "hash_tete": sig["ligne_id"]},
        "reference_statut": {"registre": "affaires", "ligne_id": arb["ligne_id"], "hash_tete": arb["ligne_id"]},
        "reference_a": {"registre": "affaires", "ligne_id": a["ligne_id"], "hash_tete": a["ligne_id"]},
        "reference_b": {"registre": "affaires", "ligne_id": b["ligne_id"], "hash_tete": b["ligne_id"]},
    }
    for reference in (r["reference"], r["reference_statut"], r["reference_a"], r["reference_b"]):
        assert contexte.verifier_reference(reference, reg) == (True, None)
    assert SECRET not in json.dumps(resultat, ensure_ascii=False)
    assert reg.lire() == avant
    assert _lister(reg) == (resultat, None)


def test_derniere_version_privee_ne_restitue_pas_ancienne_version_ni_tete_globale():
    reg = registre.Registre()
    visible = _decision(reg, "DEC-VISIBLE")
    _decision(reg, "DEC-MASQUEE")
    prive = _decision(reg, "DEC-MASQUEE", "validee", "CLIENT_PRIVATE", DATE_2)
    resultat, verdict = _lister(reg)
    assert verdict is None
    assert [d["decision_id"] for d in resultat["decisions"]] == ["DEC-VISIBLE"]
    assert resultat["confidentialite"] == {"regle": "v1", "nb_retenus": 1}
    assert prive["ligne_id"] not in json.dumps(resultat)
    assert resultat["decisions"][0]["reference"]["hash_tete"] == visible["ligne_id"]


def test_pagination_commune_pages_courantes_et_budget_enveloppe_complete():
    reg = registre.Registre()
    for i in range(14):
        _decision(reg, f"DEC-{i}-" + "é" * 248)
    avant = reg.lire()
    premier, erreur = _lister(reg)
    assert erreur is None
    assert 0 < premier["affichees"] <= 8
    assert len(json.dumps(_enveloppe(premier), ensure_ascii=False)) == premier["taille_caracteres"] <= 5400
    suivants, erreur = _lister(reg, decalage=premier["suivant"])
    assert erreur is None
    assert not {x["decision_id"] for x in premier["decisions"]} & {x["decision_id"] for x in suivants["decisions"]}
    assert reg.lire() == avant
    _decision(reg, "DEC-NOUVELLE")
    courante, erreur = _lister(reg)
    assert erreur is None
    assert courante["decisions"][0]["decision_id"] == "DEC-NOUVELLE"


@pytest.mark.parametrize("niveau", ["CLIENT_PRIVATE", "FINANCIAL", "SENSITIVE", "SECRET_REF", "LEGAL_LOCKED", "SECRET"])
@pytest.mark.parametrize("piece", ["signalement", "a", "b", "arbitrage"])
def test_confidentialite_sur_chaque_piece_retient_toute_revision(niveau, piece):
    reg = registre.Registre()

    def entree(genre, **champs):
        return reg.ajouter({"type_entree": genre, "horodatage": DATE, **champs})

    a = entree("evenement_memorise", valeur=SECRET, **({"confidentialite": niveau} if piece == "a" else {}))
    b = entree("evenement_memorise", valeur=SECRET, **({"confidentialite": niveau} if piece == "b" else {}))
    sig = entree(
        "revision_signalee",
        ligne_id_a=a,
        ligne_id_b=b,
        revision_ligne_id=None,
        statut="en_attente",
        **({"confidentialite": niveau} if piece == "signalement" else {}),
    )
    entree(
        "revision_signalee",
        ligne_id_a=None,
        ligne_id_b=None,
        revision_ligne_id=sig,
        statut="distincts_confirmes",
        **({"confidentialite": niveau} if piece == "arbitrage" else {}),
    )
    resultat, refus = _lister(reg)
    assert refus is None
    assert resultat["decisions"] == resultat["revisions"] == []
    assert resultat["confidentialite"]["nb_retenus"] == 1
    assert SECRET not in json.dumps(resultat)
    for ligne in reg.lire():
        assert ligne["ligne_id"] not in json.dumps(resultat)


@pytest.mark.parametrize("niveau", [None, "INTERNAL", "PUBLIC_INTERNAL"])
def test_vues_de_base_seules_admises_et_id_unicode_preserve(niveau):
    reg = registre.Registre()
    _decision(reg, niveau=niveau)
    resultat, refus = _lister(reg)
    assert refus is None
    assert resultat["decisions"][0]["decision_id"] == "Décision 😀 opaque"
    assert resultat["confidentialite"]["nb_retenus"] == 0


@pytest.mark.parametrize("identifiant", [None, "", " ", "id\nsecret", "id\x00secret", "x" * 257, 42])
def test_identifiant_invalide_refus_global_sans_valeur_brute(identifiant):
    reg = registre.Registre()
    _decision(reg, identifiant)
    resultat, refus = _lister(reg)
    assert resultat is None
    assert refus["code"] == "REJ-CATALOGUE-DECISION-INVALIDE"
    assert SECRET not in json.dumps(refus)


def test_lecture_unique_snapshot_et_zero_mutation():
    reg = registre.Registre()
    _decision(reg)

    class Source:
        lectures = 0

        def lire(self):
            self.lectures += 1
            assert self.lectures == 1
            return reg.lire()

    source = Source()
    avant = deepcopy(reg.lire())
    assert _lister(source)[1] is None
    assert source.lectures == 1
    assert reg.lire() == avant


def test_chaine_alteree_ou_illisible_refus_sans_identifiant_prive():
    reg = registre.Registre()
    _decision(reg)
    for lignes in [
        None,
        [None],
        [{"type_entree": "secret", "ligne_id": SECRET}],
        [{**reg.lire()[0], "raison": "altération"}],
    ]:

        class Source:
            def lire(self, copie=lignes):
                return copie

        resultat, refus = _lister(Source())
        assert resultat is None
        assert refus["code"] in {"REJ-CATALOGUE-CHAINE-INVALIDE", "REJ-CATALOGUE-MAILLON-ILLISIBLE"}
        assert SECRET not in json.dumps(refus)


@pytest.mark.parametrize(
    "champs,code",
    [
        ({"ligne_id_a": None, "ligne_id_b": None, "revision_ligne_id": "a" * 64}, "REJ-CATALOGUE-ARBITRAGE-ORPHELIN"),
        (
            {"ligne_id_a": "a" * 64, "ligne_id_b": "b" * 64, "revision_ligne_id": None},
            "REJ-CATALOGUE-REFERENCES-INVALIDES",
        ),
        ({"ligne_id_a": None, "ligne_id_b": None, "revision_ligne_id": None}, "REJ-CATALOGUE-ARBITRAGE-ORPHELIN"),
    ],
)
def test_revision_illisible_ou_orpheline_refus_global(champs, code):
    reg = registre.Registre()
    reg.ajouter({"type_entree": "revision_signalee", "horodatage": DATE, "statut": "en_attente", **champs})
    assert _lister(reg)[1]["code"] == code


def test_references_identiques_refusees_et_preflight_non_arbitrable_reconnu():
    reg = registre.Registre()
    a = _decision(reg)
    reg.ajouter(
        {
            "type_entree": "revision_signalee",
            "horodatage": DATE,
            "statut": "en_attente",
            "code_verdict": "REJ-CONTEXTE-STRUCTURE-INVALIDE",
        }
    )
    resultat, refus = _lister(reg)
    assert refus is None
    assert resultat["revisions"] == []
    assert resultat["affichees"] == 1
    reg.ajouter(
        {
            "type_entree": "revision_signalee",
            "horodatage": DATE,
            "statut": "en_attente",
            "ligne_id_a": a["ligne_id"],
            "ligne_id_b": a["ligne_id"],
            "revision_ligne_id": None,
        }
    )
    assert _lister(reg)[1]["code"] == "REJ-CATALOGUE-REFERENCES-INVALIDES"


@pytest.mark.parametrize("limite,decalage", [(True, 0), (0, 0), (9, 0), (8, True), (8, -1), (8, "0")])
def test_pagination_invalide_refuse_avant_lecture(limite, decalage):
    class Source:
        def lire(self):
            raise AssertionError("la lecture ne doit pas commencer")

    assert _lister(Source(), limite=limite, decalage=decalage)[1]["code"] == "REJ-CATALOGUE-PAGINATION-INVALIDE"


def test_huit_revisions_reduites_par_budget_pages_sans_perte_et_fin_explicitement_vide():
    reg = registre.Registre()
    for i in range(10):
        a = reg.ajouter({"type_entree": "evenement_memorise", "horodatage": DATE, "numero": f"{i}-a"})
        b = reg.ajouter({"type_entree": "evenement_memorise", "horodatage": DATE, "numero": f"{i}-b"})
        revision.signaler_revision(reg, a, b, DATE)
    vus, offset = [], 0
    while True:
        resultat, refus = _lister(reg, decalage=offset)
        assert refus is None
        assert resultat["taille_caracteres"] == len(json.dumps(_enveloppe(resultat), ensure_ascii=False)) <= 5400
        assert 0 < resultat["affichees"] < 8
        for r in resultat["revisions"]:
            assert r["statut"] == "en_attente"
            assert r["reference_statut"] == r["reference"]
        vus.extend(r["revision_ligne_id"] for r in resultat["revisions"])
        if resultat["suivant"] is None:
            break
        assert resultat["suivant"] > offset
        offset = resultat["suivant"]
    assert len(set(vus)) == len(vus) == 10
    fin, refus = _lister(reg, decalage=100)
    assert refus is None
    assert fin["decisions"] == fin["revisions"] == []
    assert fin["suivant"] is None
    assert fin["reste"] == 0


@pytest.mark.parametrize(
    "champs",
    [
        {"statut": None},
        {"statut": []},
        {"horodatage": None},
        {"horodatage": DATE.replace("-04:00", "")},
        {"type_entree": None},
    ],
)
def test_date_null_et_statut_illisible_refus_explicites(champs):
    reg = registre.Registre()
    reg.ajouter(
        {"type_entree": "decision_enregistree", "horodatage": DATE, "decision_id": "DEC-1", "statut": "proposee"}
    )
    lignes = reg.lire()
    lignes[0].update(champs)
    corps = {k: v for k, v in lignes[0].items() if k not in {"ligne_id", "precedent_ligne_id"}}
    lignes[0]["ligne_id"] = encodage.empreinte(corps, None)
    resultat, refus = _lister(registre.Registre(lignes))
    assert resultat is None
    assert refus is not None
    assert SECRET not in json.dumps(refus)


def test_forme_fermee_vide_et_sorties_sans_alias_du_registre():
    reg = registre.Registre()
    resultat, refus = _lister(reg)
    assert refus is None
    assert set(resultat) == {
        "decisions",
        "revisions",
        "decalage",
        "suivant",
        "reste",
        "total",
        "affichees",
        "limite",
        "borne_caracteres",
        "taille_caracteres",
        "confidentialite",
    }
    assert resultat["total"] == resultat["affichees"] == 0
    assert resultat["suivant"] is None
    _decision(reg)
    avant = reg.lire()
    resultat, refus = _lister(reg)
    assert refus is None
    assert set(resultat["decisions"][0]) == {"genre", "decision_id", "statut", "horodatage", "reference"}
    resultat["decisions"][0]["reference"]["ligne_id"] = "modifié côté appelant"
    assert reg.lire() == avant


def test_dernier_maillon_fait_foi_meme_si_son_horodatage_est_anterieur():
    reg = registre.Registre()
    _decision(reg, statut="proposee", date=DATE_2)
    dernier = _decision(reg, statut="annulee", date=DATE)
    resultat, refus = _lister(reg)
    assert refus is None
    d = resultat["decisions"][0]
    assert d["statut"] == "annulee"
    assert d["horodatage"] == DATE
    assert d["reference"]["ligne_id"] == dernier["ligne_id"]


def test_un_arbitrage_ne_peut_pas_cibler_un_autre_arbitrage():
    reg = registre.Registre()
    _, _, _, arbitre = _revision(reg)
    reg.ajouter(
        {
            "type_entree": "revision_signalee",
            "horodatage": DATE_2,
            "statut": "obsolete_marquee",
            "ligne_id_a": None,
            "ligne_id_b": None,
            "revision_ligne_id": arbitre["ligne_id"],
        }
    )
    resultat, refus = _lister(reg)
    assert resultat is None
    assert refus["code"] == "REJ-CATALOGUE-ARBITRAGE-ORPHELIN"


def test_identifiant_unicode_opaque_avec_jointure_emoji_preserve_sans_reinterpretation():
    reg = registre.Registre()
    identifiant = "Décision 👨‍👩‍👧‍👦 opaque"
    _decision(reg, identifiant)
    resultat, refus = _lister(reg)
    assert refus is None
    assert resultat["decisions"][0]["decision_id"] == identifiant
