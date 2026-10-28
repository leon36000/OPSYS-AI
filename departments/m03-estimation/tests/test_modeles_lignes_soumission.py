"""Jeux de lignes fictifs; source textuelle, copies, versions et refus sans effets externes."""

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import modeles_lignes_soumission as lignes  # noqa: E402
from m3_estimation import modeles_soumission as textes  # noqa: E402
from m3_estimation.registre import _encoder_canonique  # noqa: E402

FIXTURE = {"fictif": True}
HEURE = "2030-06-03T12:00:00+00:00"
AUTEUR = {"personne": "admin.fictif", "role": "admin"}
LIGNE = {"ligne_id": "gouttiere-fictive", "description": "Pose de gouttières FICTIF",
         "materiau_id": "matériau-fictif", "unite": "pi_lin"}
BASE = {"modele_id": "modele-fictif", "modele_source": "a" * 64, "lignes": [LIGNE], "revision_attendue": 0}


def _mutation(arguments, cle="intention-fictive", appareil="console:admin.fictif"):
    return {"appareil": appareil, "cle": cle, "empreinte_arguments": _encoder_canonique(arguments)}


def _enregistrer(journal, *, cle="intention-fictive", auteur=AUTEUR, heure=HEURE, limite_sortie=65536, **changements):
    arguments = {**deepcopy(BASE), **changements}
    return lignes.enregistrer(journal, **arguments, auteur=auteur, mutation=_mutation(arguments, cle),
                              horodatage=heure, limite_sortie=limite_sortie)


def _versions_textuelles():
    catalogue, sources = [], []
    for revision in range(2):
        arguments = {"modele_id": BASE["modele_id"], "titre": "Titre FICTIF",
                     "description": f"Description fictive version {revision + 1}", "clauses": "",
                     "revision_attendue": revision}
        r = textes.enregistrer(catalogue, **arguments, auteur=AUTEUR,
                               mutation=_mutation(arguments, f"texte-{revision}"), horodatage=HEURE)
        sources.append(r["resultat"]["source_id"])
    return catalogue, sources


def _rechainer(journal):
    precedent = None
    for rang, m in enumerate(journal):
        m["rang"], m["precedent"] = rang, precedent
        m["source_id"] = _encoder_canonique({k: v for k, v in m.items() if k != "source_id"})
        precedent = m["source_id"]


def test_sources_textuelles_distinctes_pas_de_transfert_cas_par_paire():
    catalogue, (source1, source2) = _versions_textuelles()
    avant = deepcopy(catalogue)
    journal = []
    premier = _enregistrer(journal, modele_source=source1)
    with pytest.raises(lignes.Refus, match="INTROUVABLE"):
        lignes.lire(journal, BASE["modele_id"], source2)
    second = _enregistrer(journal, cle="autre-source", modele_source=source2)
    assert premier["resultat"]["revision"] == second["resultat"]["revision"] == 1
    suivant = _enregistrer(journal, cle="revision", modele_source=source1, revision_attendue=1,
                           lignes=[{**LIGNE, "description": "Nouvelle description FICTIF"}])
    assert suivant["resultat"]["revision"] == 2
    assert lignes.lire(journal, BASE["modele_id"], source2)["resultat"]["revision_courante"] == 1
    ancienne = lignes.lire(journal, BASE["modele_id"], source1, 1)["resultat"]
    assert ancienne == {**premier["resultat"], "revision_courante": 2}
    assert catalogue == avant
    with pytest.raises(lignes.Refus, match="INTROUVABLE"):
        lignes.lire(journal, "autre-modele-fictif", source1)


def test_rejeu_ancienne_version_et_contradictions_sans_append():
    journal = []
    premier = _enregistrer(journal)
    _enregistrer(journal, cle="revision", revision_attendue=1, lignes=[{**LIGNE, "unite": "m"}])
    avant = deepcopy(journal)
    assert _enregistrer(journal, heure="2031-01-01T00:00:00Z") == {**premier, "rejoue": True}
    for changements in ({"modele_source": "b" * 64}, {"lignes": [{**LIGNE, "unite": "m"}]},
                         {"modele_id": "autre-fictif"}):
        with pytest.raises(lignes.Refus, match="MUTATION-CONFLIT"):
            _enregistrer(journal, **changements)
    with pytest.raises(lignes.Refus, match="MUTATION-CONFLIT"):
        _enregistrer(journal, auteur={"personne": "autre.admin", "role": "admin"})
    with pytest.raises(lignes.Refus, match="REVISION-PERIMEE"):
        _enregistrer(journal, cle="redacteur-concurrent", revision_attendue=1)
    assert journal == avant


def test_copies_independantes_et_aucun_prix_quantite():
    journal, arguments, auteur = [], deepcopy(BASE), deepcopy(AUTEUR)
    mutation = _mutation(arguments)
    r = lignes.enregistrer(journal, **arguments, auteur=auteur, mutation=mutation, horodatage=HEURE)
    avant = deepcopy(journal)
    arguments["lignes"][0]["description"] = "Mutation externe"
    auteur["personne"] = "autre-fictif"
    mutation["cle"] = "autre-fictive"
    r["resultat"]["lignes"][0]["unite"] = "m"
    lu = lignes.lire(journal, BASE["modele_id"], BASE["modele_source"])["resultat"]
    assert lu["lignes"] == [LIGNE]
    assert set(lu["lignes"][0]) == {"ligne_id", "description", "materiau_id", "unite"}
    lu["lignes"].clear()
    assert journal == avant
    assert lignes.Refus is textes.Refus
    assert lignes.refuser("ARGUMENTS") == {"accepte": False, "verdict": {"code": "REJ-MODELE-ARGUMENTS"}}


def test_meme_cle_sur_autre_appareil_ne_rejoue_pas_autre_source():
    journal = []
    _enregistrer(journal)
    arguments = {**deepcopy(BASE), "modele_source": "b" * 64}
    r = lignes.enregistrer(journal, **arguments, auteur=AUTEUR, horodatage=HEURE,
                          mutation=_mutation(arguments, appareil="console:autre-admin-fictif"))
    assert r["rejoue"] is False and r["resultat"]["revision"] == 1
    assert r["resultat"]["modele_source"] == "b" * 64 and len(journal) == 2


@pytest.mark.parametrize("champ", ["quantite", "cout_unitaire", "prix_unitaire", "fournisseur_id"])
def test_aucune_valeur_implicite_ou_champ_additionnel(champ):
    journal = []
    with pytest.raises(lignes.Refus, match="ARGUMENTS"):
        _enregistrer(journal, lignes=[{**LIGNE, champ: "1"}])
    assert journal == []


@pytest.mark.parametrize("jeu", [[], [LIGNE] * 21, [LIGNE, LIGNE], None,
    [{}], [{**LIGNE, "ligne_id": True}], [{**LIGNE, "ligne_id": "."}], [{**LIGNE, "ligne_id": ".."}],
    [{**LIGNE, "description": " "}], [{**LIGNE, "description": "a" * 501}],
    [{**LIGNE, "materiau_id": "a" * 201}], [{**LIGNE, "materiau_id": "\u202e"}],
    [{**LIGNE, "unite": "a" * 41}], [{**LIGNE, "unite": ""}], [{**LIGNE, "unite": "m\n"}],
    [{**LIGNE, "description": "\x00"}], [{**LIGNE, "description": "\ud800"}]])
def test_lignes_invalides_sans_ecriture(jeu):
    journal = []
    with pytest.raises(lignes.Refus, match="ARGUMENTS"):
        _enregistrer(journal, lignes=jeu)
    assert journal == []


def test_tuple_refuse_avant_calcul_empreinte():
    journal = []
    # Une intention valide permet d'atteindre le validateur du domaine : le
    # sérialiseur du harnais refuse lui-même les tuples avant cet appel.
    with pytest.raises(lignes.Refus, match="ARGUMENTS"):
        lignes.enregistrer(journal, **{**BASE, "lignes": (LIGNE,)}, auteur=AUTEUR,
                           mutation=_mutation(BASE), horodatage=HEURE)
    assert journal == []


@pytest.mark.parametrize("changements", [{"modele_id": "."}, {"modele_id": ".."}, {"modele_id": "é"},
    {"modele_source": ""}, {"modele_source": "A" * 64}, {"modele_source": "a" * 63},
    {"modele_source": None}, {"revision_attendue": True}, {"revision_attendue": 1.0},
    {"revision_attendue": -1}, {"revision_attendue": 1001}])
def test_arguments_fermes(changements):
    journal = []
    with pytest.raises(lignes.Refus, match="ARGUMENTS"):
        _enregistrer(journal, **changements)
    assert journal == []


@pytest.mark.parametrize("version", [True, 1.0, "1", -1, 1001])
def test_version_lecture_stricte(version):
    with pytest.raises(lignes.Refus, match="ARGUMENTS"):
        lignes.lire([], BASE["modele_id"], BASE["modele_source"], version)


def test_20_lignes_preserve_ordre_et_bornes_texte():
    jeu = [{**LIGNE, "ligne_id": f"ligne-{i:02}", "description": "é" * 500,
            "materiau_id": "é" * 200, "unite": "u" * 40} for i in range(20)]
    journal = []
    r = _enregistrer(journal, lignes=jeu)
    assert r["resultat"]["lignes"] == jeu
    assert lignes.lire(journal, BASE["modele_id"], BASE["modele_source"])["resultat"]["lignes"] == jeu
    with pytest.raises(lignes.Refus, match="INTROUVABLE"):
        lignes.lire(journal, BASE["modele_id"], BASE["modele_source"], 2)


@pytest.mark.parametrize("modifications", [
    {"revision": True}, {"revision": 9}, {"revision_attendue": 1}, {"type_entree": "modele_soumission"},
    {"modele_source": "b" * 64}, {"auteur": {"personne": "admin.fictif", "role": "seller"}},
    {"lignes": [{**LIGNE, "quantite": "1"}]}, {"lignes": [LIGNE, LIGNE]}, {"champ_invente": "fictif"},
])
def test_semantique_refuse_corruption_rechainee(modifications):
    journal = []
    _enregistrer(journal)
    journal[0].update(modifications)
    _rechainer(journal)
    with pytest.raises(lignes.Refus, match="SOURCE-INVALIDE"):
        lignes.lire(journal, BASE["modele_id"], BASE["modele_source"])
    avant = deepcopy(journal)
    with pytest.raises(lignes.Refus, match="SOURCE-INVALIDE"):
        _enregistrer(journal, cle="suivante", revision_attendue=1)
    assert journal == avant


def test_hash_altere_collision_mutation_et_transfert_rechaine():
    journal = []
    _enregistrer(journal)
    _enregistrer(journal, cle="revision", revision_attendue=1)
    alt = deepcopy(journal)
    alt[0]["lignes"][0]["description"] = "Altération fictive"
    with pytest.raises(lignes.Refus, match="SOURCE-INVALIDE"):
        lignes.lire(alt, BASE["modele_id"], BASE["modele_source"])
    collision = deepcopy(journal)
    collision[1]["mutation"]["cle"] = collision[0]["mutation"]["cle"]
    _rechainer(collision)
    with pytest.raises(lignes.Refus, match="SOURCE-INVALIDE"):
        lignes.lire(collision, BASE["modele_id"], BASE["modele_source"])
    journal[1]["modele_source"] = "b" * 64
    journal[1]["mutation"] = _mutation({cle: journal[1][cle] for cle in BASE}, "revision")
    _rechainer(journal)
    with pytest.raises(lignes.Refus, match="SOURCE-INVALIDE"):
        lignes.lire(journal, BASE["modele_id"], "b" * 64)


def test_identite_mutation_et_heure_revalidees_avant_rejeu():
    journal = []
    _enregistrer(journal)
    avant = deepcopy(journal)
    with pytest.raises(lignes.Refus, match="IDENTITE"):
        _enregistrer(journal, auteur={"personne": "admin.fictif", "role": "seller"})
    with pytest.raises(lignes.Refus, match="HORODATAGE-INVALIDE"):
        _enregistrer(journal, heure="2030-06-03")
    mutation = _mutation(BASE)
    mutation["empreinte_arguments"] = "0" * 64
    with pytest.raises(lignes.Refus, match="ARGUMENTS"):
        lignes.enregistrer(journal, **BASE, auteur=AUTEUR, mutation=mutation, horodatage=HEURE)
    assert journal == avant


@pytest.mark.parametrize("quota", [True, 0, -1, 1.0, 10])
def test_quota_avant_append_et_rejeu(quota):
    journal = []
    with pytest.raises(lignes.Refus, match="SORTIE-TROP-VOLUMINEUSE"):
        _enregistrer(journal, limite_sortie=quota)
    assert journal == []
    _enregistrer(journal)
    avant = deepcopy(journal)
    with pytest.raises(lignes.Refus, match="SORTIE-TROP-VOLUMINEUSE"):
        _enregistrer(journal, limite_sortie=quota)
    with pytest.raises(lignes.Refus, match="SORTIE-TROP-VOLUMINEUSE"):
        lignes.lire(journal, BASE["modele_id"], BASE["modele_source"], limite_sortie=quota)
    assert journal == avant


def test_enveloppe_utf8_comptee_et_limite_sources_avant_lecture():
    journal = []
    r = _enregistrer(journal, lignes=[{**LIGNE, "description": "é" * 500}])
    taille = len(json.dumps({"ok": True, "resultat": r, "rejoue": False}, ensure_ascii=False).encode("utf-8"))
    essai = []
    with pytest.raises(lignes.Refus, match="SORTIE-TROP-VOLUMINEUSE"):
        _enregistrer(essai, lignes=[{**LIGNE, "description": "é" * 500}], limite_sortie=taille - 1)
    assert essai == []
    assert _enregistrer(essai, lignes=[{**LIGNE, "description": "é" * 500}], limite_sortie=taille) == r

    class TropGrand:
        def __len__(self):
            return 1001

        def __iter__(self):
            raise AssertionError("Le plafond doit précéder la lecture")

    with pytest.raises(lignes.Refus, match="SOURCES-TROP-VOLUMINEUSES"):
        lignes.lire(TropGrand(), BASE["modele_id"], BASE["modele_source"])


def test_derniere_place_et_rejeu_a_saturation():
    journal = []
    premier = _enregistrer(journal)
    for revision in range(2, 1001):
        m = deepcopy(journal[0])
        m["revision"], m["revision_attendue"] = revision, revision - 1
        m["mutation"] = _mutation({cle: m[cle] for cle in BASE}, f"intention-{revision}")
        journal.append(m)
    _rechainer(journal)
    assert lignes.lire(journal, BASE["modele_id"], BASE["modele_source"])["resultat"]["revision"] == 1000
    assert _enregistrer(journal) == {**premier, "rejoue": True}
    with pytest.raises(lignes.Refus, match="SOURCES-TROP-VOLUMINEUSES"):
        _enregistrer(journal, cle="depassement", revision_attendue=1000)
    assert len(journal) == 1000
