"""Catalogue de modèles : données fictives, sans stockage ni horloge extérieure."""

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import modeles_soumission as modeles  # noqa: E402
from m3_estimation.registre import _encoder_canonique  # noqa: E402

FIXTURE = {"fictif": True}
AUTEUR = {"personne": "admin.fictif", "role": "admin"}
HEURE = "2030-06-03T12:00:00+00:00"
ARGUMENTS = {"modele_id": "gouttieres-fictif", "titre": "Gouttières FICTIF",
             "description": "Pose fictive de gouttières.\nDescription saisie par le secrétariat.",
             "clauses": "Texte fictif fourni, sans portée juridique.", "revision_attendue": 0}


def _mutation(arguments, cle="intention-fictive", appareil="console:admin.fictif"):
    return {"appareil": appareil, "cle": cle, "empreinte_arguments": _encoder_canonique(arguments)}


def _enregistrer(journal, *, cle="intention-fictive", auteur=None, heure=HEURE, limite_sortie=65536, **changements):
    arguments = {**ARGUMENTS, **changements}
    return modeles.enregistrer(journal, **arguments, auteur=auteur or AUTEUR,
                              mutation=_mutation(arguments, cle), horodatage=heure, limite_sortie=limite_sortie)


def _rechainer(journal):
    """L'attaquant sait recalculer les hashes; les invariants doivent encore refuser."""
    precedent = None
    for rang, m in enumerate(journal):
        m["rang"], m["precedent"] = rang, precedent
        m["source_id"] = _encoder_canonique({k: v for k, v in m.items() if k != "source_id"})
        precedent = m["source_id"]


def test_creer_reviser_ancienne_version_et_copies_independantes():
    journal = []
    premier = _enregistrer(journal)
    original = deepcopy(journal)
    deuxieme = _enregistrer(journal, cle="revision-fictive", revision_attendue=1,
                           description="Deuxième description fictive", clauses="")
    assert premier["rejoue"] is False and premier["resultat"]["revision"] == 1
    assert deuxieme["resultat"]["revision"] == 2 and deuxieme["resultat"]["clauses"] == ""
    assert journal[0] == original[0]
    ancienne = modeles.lire(journal, ARGUMENTS["modele_id"], 1)["resultat"]
    derniere = modeles.lire(journal, ARGUMENTS["modele_id"])["resultat"]
    assert ancienne == {**premier["resultat"], "revision_courante": 2}
    assert derniere == {**deuxieme["resultat"], "revision_courante": 2}
    assert ancienne["source_id"] != derniere["source_id"]
    avant = deepcopy(journal)
    ancienne["auteur"]["personne"] = "autre-fictif"
    premier["resultat"]["auteur"]["role"] = "vendeur"
    meta = modeles.lister(journal)["resultat"]["modeles"][0]
    meta["auteur"]["personne"] = "autre-fictif"
    assert journal == avant
    assert "description" not in meta and "clauses" not in meta


def test_rejeu_original_apres_revision_et_refus_cles_contradictoires():
    journal = []
    premier = _enregistrer(journal)
    _enregistrer(journal, cle="revision-fictive", revision_attendue=1, titre="Version suivante FICTIF")
    avant = deepcopy(journal)
    assert _enregistrer(journal, heure="2031-01-01T00:00:00Z") == {**premier, "rejoue": True}
    with pytest.raises(modeles.Refus, match="MUTATION-CONFLIT"):
        _enregistrer(journal, titre="Texte changé FICTIF")
    with pytest.raises(modeles.Refus, match="MUTATION-CONFLIT"):
        _enregistrer(journal, auteur={"personne": "autre.admin.fictif", "role": "admin"})
    with pytest.raises(modeles.Refus, match="REVISION-PERIMEE"):
        _enregistrer(journal, cle="editeur-concurrent", revision_attendue=1)
    assert journal == avant


def test_cle_scope_appareil_et_cas_creation():
    journal = []
    _enregistrer(journal)
    with pytest.raises(modeles.Refus, match="REVISION-PERIMEE"):
        _enregistrer(journal, cle="autre-intention")
    autre = {**ARGUMENTS, "modele_id": "autre-modele-fictif"}
    r = modeles.enregistrer(journal, **autre, auteur=AUTEUR, mutation=_mutation(autre, appareil="autre-appareil"),
                           horodatage=HEURE)
    assert r["resultat"]["revision"] == 1 and len(journal) == 2


def test_pages_25_ordre_stable_sans_doublon_et_source_changee():
    journal = []
    for numero in reversed(range(26)):
        _enregistrer(journal, cle=f"intention-{numero}", modele_id=f"modele-fictif-{numero:02}")
    premiere = modeles.lister(journal)["resultat"]
    seconde = modeles.lister(journal, 25, premiere["source_empreinte"])["resultat"]
    assert len(premiere["modeles"]) == 25 and len(seconde["modeles"]) == 1
    assert premiere["total"] == seconde["total"] == 26
    assert premiere["decalage_suivant"] == 25 and seconde["decalage_suivant"] is None
    assert [m["modele_id"] for m in premiere["modeles"] + seconde["modeles"]] == [
        f"modele-fictif-{numero:02}" for numero in range(26)]
    _enregistrer(journal, cle="revision-source", modele_id="modele-fictif-00", revision_attendue=1)
    with pytest.raises(modeles.Refus, match="SOURCE-MODIFIEE"):
        modeles.lister(journal, 25, premiere["source_empreinte"])
    assert modeles.lister(journal)["resultat"]["total"] == 26
    with pytest.raises(modeles.Refus, match="ARGUMENTS"):
        modeles.lister(journal, 50, modeles.lister(journal)["resultat"]["source_empreinte"])


def test_vide_introuvable_et_refus_public():
    vide = modeles.lister([])["resultat"]
    assert vide["modeles"] == [] and vide["total"] == 0 and vide["decalage_suivant"] is None
    assert len(vide["source_empreinte"]) == 64
    with pytest.raises(modeles.Refus, match="INTROUVABLE"):
        modeles.lire([], "inconnu")
    journal = []
    _enregistrer(journal)
    with pytest.raises(modeles.Refus, match="INTROUVABLE"):
        modeles.lire(journal, ARGUMENTS["modele_id"], 2)
    assert modeles.refuser("SOURCE-INVALIDE") == {
        "accepte": False, "verdict": {"code": "REJ-MODELE-SOURCE-INVALIDE"}}


@pytest.mark.parametrize("modification", [
    {"revision": True}, {"revision": 7}, {"revision_attendue": 1}, {"type_entree": "devis_cree"},
    {"titre": "Contradiction de texte FICTIF"}, {"auteur": {"personne": "admin.fictif", "role": "seller"}},
    {"horodatage": "2030-06-03"}, {"clauses": "\ud800"}, {"champ_invente": True},
])
def test_corruption_semantique_refusee_meme_apres_rechainage(modification):
    journal = []
    _enregistrer(journal)
    journal[0].update(modification)
    _rechainer(journal)
    with pytest.raises(modeles.Refus, match="SOURCE-INVALIDE"):
        modeles.lire(journal, ARGUMENTS["modele_id"])
    with pytest.raises(modeles.Refus, match="SOURCE-INVALIDE"):
        modeles.lister(journal)
    avant = deepcopy(journal)
    with pytest.raises(modeles.Refus, match="SOURCE-INVALIDE"):
        _enregistrer(journal, cle="suivante", revision_attendue=1)
    assert journal == avant


def test_hash_altere_revisions_dupliquees_et_mutation_reutilisee():
    journal = []
    _enregistrer(journal)
    _enregistrer(journal, cle="seconde", revision_attendue=1)
    altere = deepcopy(journal)
    altere[0]["titre"] = "Autre titre FICTIF"
    with pytest.raises(modeles.Refus, match="SOURCE-INVALIDE"):
        modeles.lister(altere)
    doublon = [deepcopy(journal[0]), deepcopy(journal[0])]
    _rechainer(doublon)
    with pytest.raises(modeles.Refus, match="SOURCE-INVALIDE"):
        modeles.lister(doublon)
    journal[1]["mutation"]["cle"] = journal[0]["mutation"]["cle"]
    _rechainer(journal)
    with pytest.raises(modeles.Refus, match="SOURCE-INVALIDE"):
        modeles.lister(journal)


@pytest.mark.parametrize("changements", [
    {"modele_id": ""}, {"modele_id": "é"}, {"modele_id": "../modele"}, {"modele_id": "a" * 101},
    {"titre": " "}, {"titre": "a" * 121}, {"titre": "titre\n"}, {"description": ""},
    {"description": "a" * 4001}, {"clauses": "a" * 12001}, {"clauses": "\x00"}, {"clauses": "\u202e"},
    {"description": "\ud800"}, {"revision_attendue": True}, {"revision_attendue": 0.0},
    {"revision_attendue": -1}, {"revision_attendue": 1001}, {"titre": []},
])
def test_arguments_invalides_sans_ecriture(changements):
    journal = []
    with pytest.raises(modeles.Refus, match="ARGUMENTS"):
        _enregistrer(journal, **changements)
    assert journal == []


@pytest.mark.parametrize("modele_id", [".", ".."])
def test_segments_normalises_refuses_en_ecriture_lecture_et_source(modele_id):
    journal = []
    with pytest.raises(modeles.Refus, match="ARGUMENTS"):
        _enregistrer(journal, modele_id=modele_id)
    assert journal == []
    with pytest.raises(modeles.Refus, match="ARGUMENTS"):
        modeles.lire(journal, modele_id)
    _enregistrer(journal)
    journal[0]["modele_id"] = modele_id
    arguments = {cle: journal[0][cle] for cle in ARGUMENTS}
    journal[0]["mutation"] = _mutation(arguments)
    _rechainer(journal)
    with pytest.raises(modeles.Refus, match="SOURCE-INVALIDE"):
        modeles.lister(journal)


@pytest.mark.parametrize("decalage,source", [(True, ""), (0.0, ""), (1, ""), (-25, ""),
    (1025, "a" * 64), (25, ""), (0, "g" * 64), (0, "a" * 65), (0, None)])
def test_pagination_invalide(decalage, source):
    with pytest.raises(modeles.Refus, match="ARGUMENTS"):
        modeles.lister([], decalage, source)


@pytest.mark.parametrize("version", [True, 0.0, -1, 1001, "1"])
def test_version_stricte(version):
    with pytest.raises(modeles.Refus, match="ARGUMENTS"):
        modeles.lire([], "modele-fictif", version)


@pytest.mark.parametrize("auteur", [{}, {"personne": "admin.fictif", "role": "seller"},
    {"personne": "admin.fictif", "role": "admin", "extra": True}, {"personne": True, "role": "admin"}])
def test_identite_invalide(auteur):
    journal = []
    with pytest.raises(modeles.Refus, match="IDENTITE"):
        modeles.enregistrer(journal, **ARGUMENTS, auteur=auteur, mutation=_mutation(ARGUMENTS), horodatage=HEURE)
    assert journal == []


@pytest.mark.parametrize("heure", [None, "", "2030-06-03", "2030-06-03T12:00:00", "2030-02-30T00:00:00Z"])
def test_heure_serveur_explicitement_fournie(heure):
    journal = []
    with pytest.raises(modeles.Refus, match="HORODATAGE-INVALIDE"):
        _enregistrer(journal, heure=heure)
    assert journal == []


def test_mutation_fausse_et_controles_texte_multiligne():
    journal = []
    mutation = _mutation(ARGUMENTS)
    mutation["empreinte_arguments"] = "0" * 64
    with pytest.raises(modeles.Refus, match="ARGUMENTS"):
        modeles.enregistrer(journal, **ARGUMENTS, auteur=AUTEUR, mutation=mutation, horodatage=HEURE)
    assert journal == []
    texte = "Texte fictif\tavec CR\rLF\n<script>littéral</script> {{aucune_execution}}"
    assert _enregistrer(journal, description=texte, clauses=texte)["resultat"]["description"] == texte


@pytest.mark.parametrize("quota", [True, 0, -1, 0.5, 10])
def test_quota_avant_append_et_rejeu(quota):
    journal = []
    with pytest.raises(modeles.Refus, match="SORTIE-TROP-VOLUMINEUSE"):
        _enregistrer(journal, limite_sortie=quota)
    assert journal == []
    _enregistrer(journal)
    avant = deepcopy(journal)
    with pytest.raises(modeles.Refus, match="SORTIE-TROP-VOLUMINEUSE"):
        _enregistrer(journal, limite_sortie=quota)
    with pytest.raises(modeles.Refus, match="SORTIE-TROP-VOLUMINEUSE"):
        modeles.lire(journal, ARGUMENTS["modele_id"], limite_sortie=quota)
    with pytest.raises(modeles.Refus, match="SORTIE-TROP-VOLUMINEUSE"):
        modeles.lister(journal, limite_sortie=quota)
    assert journal == avant


def test_quota_compte_enveloppe_complete_et_utf8():
    journal = []
    arguments = {"description": "é" * 4000, "clauses": "é" * 12000}
    reponse = _enregistrer(journal, **arguments)
    taille = len(json.dumps({"ok": True, "resultat": reponse, "rejoue": False}, ensure_ascii=False).encode("utf-8"))
    essai = []
    with pytest.raises(modeles.Refus, match="SORTIE-TROP-VOLUMINEUSE"):
        _enregistrer(essai, limite_sortie=taille - 1, **arguments)
    assert essai == []
    assert _enregistrer(essai, limite_sortie=taille, **arguments) == reponse


def test_borne_source_avant_lecture_et_derniere_place_rejeu_permis():
    class TropGrand:
        def __len__(self):
            return 1001

        def __iter__(self):
            raise AssertionError("Le plafond doit précéder la lecture")

    with pytest.raises(modeles.Refus, match="SOURCES-TROP-VOLUMINEUSES"):
        modeles.lister(TropGrand())
    journal = []
    premier = _enregistrer(journal)
    # Générer des maillons valides sans 1000 relectures cumulatives du même journal.
    for revision in range(2, 1001):
        m = deepcopy(journal[0])
        m["revision"], m["revision_attendue"] = revision, revision - 1
        arguments = {cle: m[cle] for cle in ARGUMENTS}
        m["mutation"] = _mutation(arguments, f"intention-{revision}")
        journal.append(m)
    _rechainer(journal)
    assert modeles.lire(journal, ARGUMENTS["modele_id"])["resultat"]["revision"] == 1000
    assert _enregistrer(journal) == {**premier, "rejoue": True}
    with pytest.raises(modeles.Refus, match="SOURCES-TROP-VOLUMINEUSES"):
        _enregistrer(journal, cle="depassement", revision_attendue=1000)
    assert len(journal) == 1000
