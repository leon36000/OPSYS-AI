"""Packs sectoriels (`opsys.packs`) : le chargeur strict, l'empreinte, la résolution depuis le profil et le rendu.

Chaque refus du catalogue `REJ-PACK-*` est provoqué ici par une copie jetable des vrais packs (jamais les vrais
fichiers) : on modifie UN octet utile, on scelle ou non l'empreinte, et on exige le code typé et le chemin du champ
fautif. Données FICTIVES.

Ce que ces tests ne prouvent pas : qu'un second secteur tient dans ce schéma (un seul pack réel est livré) ni que les
textes du pack rénovation sont ceux que le premier client validerait (voir docs/architecture/PACKS-SECTORIELS.md).
"""

from __future__ import annotations

import copy
import json
import re
import shutil
from pathlib import Path

import pytest
import yaml

from opsys import cli, packs, taxonomie
from opsys.packs import RefusPack
from opsys.packs import manifeste as mf
from opsys.packs.codes import CODES_PACK

RACINE = Path(__file__).resolve().parents[1]
PACKS = RACINE / "packs"
RENOVATION = "renovation-exterieure-qc"
GENERIQUE = "generique-pme"


@pytest.fixture
def copie(tmp_path):
    """Une copie jetable du dossier `packs/` ; les tests y modifient et scellent à leur gré."""
    cible = tmp_path / "packs-copie"
    shutil.copytree(PACKS, cible)
    return cible


def sceller(dossier: Path) -> None:
    (dossier / "EMPREINTE.sha256").write_text(mf.calculer_empreinte(dossier) + "\n", encoding="utf-8")


def modifier(dossier: Path, fn, *, sceller_apres: bool = True) -> None:
    fichier = dossier / "pack.yaml"
    donnees = yaml.safe_load(fichier.read_text(encoding="utf-8"))
    fn(donnees)
    fichier.write_text(yaml.safe_dump(donnees, allow_unicode=True, sort_keys=False), encoding="utf-8")
    if sceller_apres:
        sceller(dossier)


def refus(dossier: Path, code: str, chemin: str | None = None) -> RefusPack:
    with pytest.raises(RefusPack) as exc:
        packs.charger_dossier(dossier)
    assert exc.value.code == code, str(exc.value)
    if chemin is not None:
        assert exc.value.chemin == chemin, str(exc.value)
    return exc.value


# ==================================================================================================== les vrais packs
def test_les_deux_packs_livres_se_chargent_avec_une_empreinte_valide():
    reno, generique = packs.charger_pack(RENOVATION), packs.charger_pack(GENERIQUE)
    assert reno.sectoriel and not reno.generique and not generique.sectoriel and generique.generique
    assert reno.langue == generique.langue == "fr-CA"
    assert reno.empreinte == mf.calculer_empreinte(PACKS / RENOVATION)
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", reno.empreinte)
    assert packs.ids_installes() == (GENERIQUE, RENOVATION)
    assert packs.verifier_packs() == []


def test_le_pack_generique_est_vide_de_secteur():
    g = packs.charger_pack(GENERIQUE)
    assert (g.services, g.glossaire, g.gabarits, g.baremes, g.exemples, g.termes_sectoriels) == ((),) * 6
    assert dict(g.blocs) == {} and set(g.vocabulaire.values()) == {""}


def test_le_pack_renovation_porte_vocabulaire_services_glossaire_gabarits_baremes_exemples_et_dix_blocs():
    r = packs.charger_pack(RENOVATION)
    assert r.vocabulaire == {"secteur": "rénovation extérieure au Québec",
                             "qualificatif_secteur": "de rénovation extérieure"}
    assert [s.code for s in r.services] == ["gouttieres", "revetement", "soffite_fascia", "reparation"]
    assert {t.terme for t in r.glossaire} >= {"soffite", "fascia", "gouttière"}
    assert {g.id for g in r.gabarits} == {"soumission-sections", "demande-photos"}
    assert all(g.contenu.strip() and g.statut == "exemple" for g in r.gabarits)
    assert len(r.exemples) >= 3 and set(r.blocs) == set(mf.DEPARTEMENTS)


def test_aucun_bareme_du_pack_renovation_ne_porte_de_valeur():
    r = packs.charger_pack(RENOVATION)
    assert r.baremes and all(b.statut == "a_fournir_par_entreprise" and b.valeur is None for b in r.baremes)


def test_les_services_du_pack_renovation_sont_ceux_du_catalogue_herite_de_la_taxonomie():
    """Le catalogue de `opsys.taxonomie` reste codé en dur (dette dite) : le pack en est la copie, épinglée ici."""
    du_pack = [(s.code, s.libelle, s.mots_cles) for s in packs.charger_pack(RENOVATION).services]
    du_socle = [(s.code, s.libelle, s.mots_cles) for s in taxonomie.CATALOGUE_REFERENCE]
    assert du_pack == du_socle


def test_le_catalogue_des_codes_est_ferme_et_documente():
    assert CODES_PACK == (
        "REJ-PACK-INTROUVABLE", "REJ-PACK-ID-INVALIDE", "REJ-PACK-ILLISIBLE", "REJ-PACK-FICHIER-INVALIDE",
        "REJ-PACK-SCHEMA", "REJ-PACK-CLE-INCONNUE", "REJ-PACK-CHAMP-INVALIDE", "REJ-PACK-DOUBLON",
        "REJ-PACK-TERMES-ABSENTS", "REJ-PACK-GENERIQUE-NON-VIDE", "REJ-PACK-BAREME-INVENTE",
        "REJ-PACK-EMPREINTE-ABSENTE", "REJ-PACK-EMPREINTE", "REJ-PACK-PROFIL-INVALIDE", "REJ-PACK-NON-INSTALLE",
        "REJ-PACK-JETON-INCONNU", "REJ-PACK-DEPARTEMENT-INCONNU",
    )
    with pytest.raises(ValueError, match="hors catalogue"):
        RefusPack("REJ-PACK-INVENTE", "x")
    doc = (RACINE / "docs" / "architecture" / "PACKS-SECTORIELS.md").read_text(encoding="utf-8")
    assert [c for c in CODES_PACK if c not in doc] == []
    # tout code écrit dans le paquet est du catalogue
    sources = "".join(p.read_text(encoding="utf-8") for p in (RACINE / "src" / "opsys" / "packs").glob("*.py"))
    assert set(re.findall(r"REJ-PACK-[A-Z-]+", sources)) <= set(CODES_PACK)


# ==================================================================================================== empreinte
def test_un_mot_change_sans_sceller_est_un_refus_d_empreinte(copie):
    fichier = copie / RENOVATION / "pack.yaml"
    fichier.write_text(fichier.read_text(encoding="utf-8").replace("Réparation", "Réparations", 1), encoding="utf-8")
    refus(copie / RENOVATION, "REJ-PACK-EMPREINTE", "EMPREINTE.sha256")


def test_un_gabarit_change_sans_sceller_est_un_refus_d_empreinte(copie):
    fichier = copie / RENOVATION / "gabarits" / "demande-photos.md"
    fichier.write_text(fichier.read_text(encoding="utf-8") + "\nAjout non revu.\n", encoding="utf-8")
    refus(copie / RENOVATION, "REJ-PACK-EMPREINTE")


def test_une_empreinte_absente_ou_mal_formee_est_refusee(copie):
    (copie / GENERIQUE / "EMPREINTE.sha256").unlink()
    refus(copie / GENERIQUE, "REJ-PACK-EMPREINTE-ABSENTE")
    (copie / GENERIQUE / "EMPREINTE.sha256").write_text("sha256:abc\n", encoding="utf-8")
    refus(copie / GENERIQUE, "REJ-PACK-EMPREINTE")
    (copie / GENERIQUE / "EMPREINTE.sha256").write_text("sha256:" + "0" * 64 + "\n", encoding="utf-8")
    refus(copie / GENERIQUE, "REJ-PACK-EMPREINTE")


def test_l_empreinte_depend_du_nom_et_du_contenu_de_chaque_fichier(copie):
    base = mf.calculer_empreinte(copie / RENOVATION)
    assert base == mf.calculer_empreinte(copie / RENOVATION)  # déterministe
    (copie / RENOVATION / "gabarits" / "demande-photos.md").rename(copie / RENOVATION / "gabarits" / "photos.md")
    assert mf.calculer_empreinte(copie / RENOVATION) != base  # le nom compte


def test_un_pack_scelle_apres_revue_est_accepte(copie):
    modifier(copie / GENERIQUE, lambda d: d.update(version="1.0.1"))
    assert packs.charger_dossier(copie / GENERIQUE).version == "1.0.1"


# ==================================================================================================== schéma fermé
def test_schema_absent_ou_autre_version(copie):
    modifier(copie / GENERIQUE, lambda d: d.update(schema="opsys.pack/v2"))
    refus(copie / GENERIQUE, "REJ-PACK-SCHEMA", "schema")


def test_cle_inconnue_a_la_racine_et_dans_un_bloc(copie):
    modifier(copie / RENOVATION, lambda d: d.update(permissions="tout"))
    refus(copie / RENOVATION, "REJ-PACK-CLE-INCONNUE")
    modifier(copie / RENOVATION, lambda d: (d.pop("permissions"), d["services"][0].update(prix=12)))
    refus(copie / RENOVATION, "REJ-PACK-CLE-INCONNUE", "services[0]")


def test_cle_manquante(copie):
    modifier(copie / RENOVATION, lambda d: d.pop("glossaire"))
    refus(copie / RENOVATION, "REJ-PACK-CHAMP-INVALIDE")


def test_identifiant_different_du_dossier_ou_mal_forme(copie):
    modifier(copie / RENOVATION, lambda d: d.update(id="autre-pack"))
    refus(copie / RENOVATION, "REJ-PACK-ID-INVALIDE", "id")
    modifier(copie / RENOVATION, lambda d: d.update(id=RENOVATION))
    shutil.copytree(copie / RENOVATION, copie / "Mauvais_ID")
    with pytest.raises(RefusPack) as exc:
        packs.charger_dossier(copie / "Mauvais_ID")
    assert exc.value.code == "REJ-PACK-ID-INVALIDE"


@pytest.mark.parametrize("champ,valeur", [
    ("version", "1.0"), ("version", "v1.0.0"), ("langue", "francais"), ("langue", "fr_CA"), ("nom", ""),
    ("nom", "x" * 121), ("sectoriel", "oui"), ("fictif", False), ("description", 12),
])
def test_valeurs_hors_schema(copie, champ, valeur):
    modifier(copie / RENOVATION, lambda d: d.update({champ: valeur}))
    refus(copie / RENOVATION, "REJ-PACK-CHAMP-INVALIDE", champ)


def test_les_accolades_doubles_sont_reservees_au_coeur(copie):
    modifier(copie / RENOVATION, lambda d: d["glossaire"][0].update(definition="Un {{secteur}} injecté."))
    refus(copie / RENOVATION, "REJ-PACK-CHAMP-INVALIDE", "glossaire[0].definition")


def test_caractere_de_controle_et_saut_de_ligne_dans_un_texte_court(copie):
    modifier(copie / RENOVATION, lambda d: d["services"][0].update(libelle="Gouttières\x07"))
    refus(copie / RENOVATION, "REJ-PACK-CHAMP-INVALIDE", "services[0].libelle")
    modifier(copie / RENOVATION, lambda d: d["services"][0].update(libelle="Gouttières\net descentes"))
    refus(copie / RENOVATION, "REJ-PACK-CHAMP-INVALIDE", "services[0].libelle")


def test_doublons(copie):
    modifier(copie / RENOVATION, lambda d: d["services"].append(copy.deepcopy(d["services"][0])))
    refus(copie / RENOVATION, "REJ-PACK-DOUBLON", "services")
    modifier(copie / RENOVATION, lambda d: d["services"].pop())
    modifier(copie / RENOVATION,
             lambda d: d["glossaire"].append({"terme": "SOFFITE", "definition": "Doublon à la casse près."}))
    refus(copie / RENOVATION, "REJ-PACK-DOUBLON", "glossaire")
    modifier(copie / RENOVATION, lambda d: d["glossaire"].pop())
    modifier(copie / RENOVATION, lambda d: d["termes_sectoriels"].append("Fascia"))
    refus(copie / RENOVATION, "REJ-PACK-DOUBLON", "termes_sectoriels")


def test_un_bareme_a_fournir_ne_porte_jamais_de_valeur(copie):
    modifier(copie / RENOVATION, lambda d: d["baremes"][0].update(valeur=125))
    refus(copie / RENOVATION, "REJ-PACK-BAREME-INVENTE", "baremes[0].valeur")


def test_un_bareme_exemple_fictif_exige_un_nombre_fini_positif_et_se_dit_fictif(copie):
    modifier(copie / RENOVATION, lambda d: d["baremes"][0].update(statut="exemple_fictif", valeur=125))
    pack = packs.charger_dossier(copie / RENOVATION)
    assert pack.baremes[0].valeur == "125"
    assert "exemple fictif non contractuel" in packs.bloc_sectoriel(pack, "M3")
    for invalide in (None, "beaucoup", -1, True, float("inf")):
        modifier(copie / RENOVATION, lambda d, v=invalide: d["baremes"][0].update(statut="exemple_fictif", valeur=v))
        refus(copie / RENOVATION, "REJ-PACK-CHAMP-INVALIDE", "baremes[0].valeur")


def test_statut_de_bareme_ou_de_gabarit_inconnu(copie):
    modifier(copie / RENOVATION, lambda d: d["baremes"][0].update(statut="valide"))
    refus(copie / RENOVATION, "REJ-PACK-CHAMP-INVALIDE", "baremes[0].statut")
    modifier(copie / RENOVATION, lambda d: (d["baremes"][0].update(statut="a_fournir_par_entreprise"),
                                            d["gabarits"][0].update(statut="valide")))
    refus(copie / RENOVATION, "REJ-PACK-CHAMP-INVALIDE", "gabarits[0].statut")


def test_un_exemple_est_fictif_et_d_un_departement_connu(copie):
    modifier(copie / RENOVATION, lambda d: d["exemples"][0].update(fictif=False))
    refus(copie / RENOVATION, "REJ-PACK-CHAMP-INVALIDE", "exemples[0].fictif")
    modifier(copie / RENOVATION, lambda d: d["exemples"][0].update(fictif=True, departement="m11"))
    refus(copie / RENOVATION, "REJ-PACK-CHAMP-INVALIDE", "exemples[0].departement")


def test_un_pack_sectoriel_sans_termes_ou_sans_un_des_dix_blocs_est_refuse(copie):
    modifier(copie / RENOVATION, lambda d: d.update(termes_sectoriels=[]))
    refus(copie / RENOVATION, "REJ-PACK-TERMES-ABSENTS")
    modifier(copie / RENOVATION, lambda d: (d.update(termes_sectoriels=["soffite"]), d["blocs"].pop("m07")))
    refus(copie / RENOVATION, "REJ-PACK-CHAMP-INVALIDE", "blocs")
    modifier(copie / RENOVATION, lambda d: d["blocs"].update(m07={"ligne": "x", "inclure": ["services"]},
                                                              m11={"ligne": "x", "inclure": []}))
    refus(copie / RENOVATION, "REJ-PACK-CLE-INCONNUE", "blocs")
    modifier(copie / RENOVATION, lambda d: (d["blocs"].pop("m11"), d["blocs"]["m07"].update(inclure=["secrets"])))
    refus(copie / RENOVATION, "REJ-PACK-CHAMP-INVALIDE", "blocs.m07.inclure[0]")


@pytest.mark.parametrize("contamination", [
    lambda d: d["services"].append({"code": "x_service", "libelle": "Un service"}),
    lambda d: d["glossaire"].append({"terme": "t", "definition": "d"}),
    lambda d: d["vocabulaire"].update(secteur="plomberie"),
    lambda d: d["termes_sectoriels"].append("plomberie"),
    lambda d: d["blocs"].update(m01={"ligne": "x", "inclure": []}),
    lambda d: d["exemples"].append({"id": "e1", "departement": "m01", "demande": "x", "fictif": True}),
    lambda d: d["baremes"].append({"id": "b1", "libelle": "x", "unite": "u", "statut": "a_fournir_par_entreprise",
                                   "valeur": None, "ou_fournir": "ailleurs"}),
])
def test_un_pack_generique_contamine_est_refuse(copie, contamination):
    modifier(copie / GENERIQUE, contamination)
    refus(copie / GENERIQUE, "REJ-PACK-GENERIQUE-NON-VIDE")


def test_un_pack_generique_contamine_par_un_gabarit_est_refuse(copie):
    (copie / GENERIQUE / "gabarits").mkdir()
    (copie / GENERIQUE / "gabarits" / "g.md").write_text("Un gabarit.\n", encoding="utf-8")
    modifier(copie / GENERIQUE, lambda d: d["gabarits"].append(
        {"id": "g", "document": "d", "fichier": "gabarits/g.md", "statut": "exemple"}))
    refus(copie / GENERIQUE, "REJ-PACK-GENERIQUE-NON-VIDE")


# ==================================================================================================== YAML et fichiers
def _sceller_texte(dossier: Path, texte: str) -> None:
    (dossier / "pack.yaml").write_text(texte, encoding="utf-8")
    sceller(dossier)


def test_yaml_cle_en_double_alias_racine_non_objet_et_illisible(copie):
    base = (copie / GENERIQUE / "pack.yaml").read_text(encoding="utf-8")
    _sceller_texte(copie / GENERIQUE, base + "id: generique-pme\n")
    refus(copie / GENERIQUE, "REJ-PACK-ILLISIBLE")
    _sceller_texte(copie / GENERIQUE, base.replace("langue: fr-CA", "langue: &l fr-CA\nautre: *l"))
    assert "alias" in refus(copie / GENERIQUE, "REJ-PACK-ILLISIBLE").detail
    _sceller_texte(copie / GENERIQUE, "- une\n- liste\n")
    refus(copie / GENERIQUE, "REJ-PACK-ILLISIBLE")
    _sceller_texte(copie / GENERIQUE, "id: [pas fermé\n")
    refus(copie / GENERIQUE, "REJ-PACK-ILLISIBLE")
    (copie / GENERIQUE / "pack.yaml").write_bytes(b"\xff\xfe\x00bad")
    sceller(copie / GENERIQUE)
    refus(copie / GENERIQUE, "REJ-PACK-ILLISIBLE")


def test_un_manifeste_trop_gros_est_refuse_avant_d_etre_analyse(copie):
    _sceller_texte(copie / GENERIQUE, "x: " + "a" * (mf.TAILLE_MANIFESTE_MAX + 1) + "\n")
    assert "octets" in refus(copie / GENERIQUE, "REJ-PACK-ILLISIBLE").detail


def test_un_dossier_ou_un_manifeste_absent_est_introuvable(tmp_path):
    (tmp_path / "vide").mkdir()
    with pytest.raises(RefusPack) as exc:
        packs.charger_dossier(tmp_path / "vide")
    assert exc.value.code == "REJ-PACK-INTROUVABLE"


@pytest.mark.parametrize("fichier", ["../hors.md", "/etc/passwd.md", "gabarits/../../x.md", "Gabarits/Majuscule.md",
                                     "gabarits/absent.md", "gabarits/sans-extension"])
def test_un_gabarit_qui_sort_du_pack_ou_n_existe_pas_est_refuse(copie, fichier):
    modifier(copie / RENOVATION, lambda d: d["gabarits"][0].update(fichier=fichier))
    refus(copie / RENOVATION, "REJ-PACK-FICHIER-INVALIDE", "gabarits[0].fichier")


def test_un_gabarit_lien_symbolique_ou_non_utf8_ou_trop_gros_est_refuse(copie):
    cible = copie / RENOVATION / "gabarits" / "demande-photos.md"
    secret = copie / "secret.md"
    secret.write_text("hors du pack\n", encoding="utf-8")
    cible.unlink()
    cible.symlink_to(secret)
    refus(copie / RENOVATION, "REJ-PACK-FICHIER-INVALIDE", "gabarits[1].fichier")  # refusé avant même l'empreinte
    with pytest.raises(RefusPack) as scellement:
        sceller(copie / RENOVATION)  # et l'outil de scellement refuse aussi un lien symbolique
    assert scellement.value.code == "REJ-PACK-FICHIER-INVALIDE"
    cible.unlink()
    cible.write_bytes(b"\xff\xfe")
    sceller(copie / RENOVATION)
    refus(copie / RENOVATION, "REJ-PACK-FICHIER-INVALIDE", "gabarits[1].fichier")
    cible.write_text("x" * (mf.TAILLE_GABARIT_MAX + 1), encoding="utf-8")
    sceller(copie / RENOVATION)
    refus(copie / RENOVATION, "REJ-PACK-FICHIER-INVALIDE", "gabarits[1].fichier")


def test_un_fichier_non_declare_ou_cache_dans_le_pack_est_refuse_meme_scelle(copie):
    (copie / RENOVATION / "gabarits" / "clandestin.md").write_text("Du contenu hors revue.\n", encoding="utf-8")
    sceller(copie / RENOVATION)
    assert refus(copie / RENOVATION, "REJ-PACK-FICHIER-INVALIDE", "gabarits/clandestin.md")
    (copie / RENOVATION / "gabarits" / "clandestin.md").unlink()
    (copie / RENOVATION / ".cache").write_text("x", encoding="utf-8")
    with pytest.raises(RefusPack) as scellement:
        sceller(copie / RENOVATION)  # même l'outil de scellement refuse un fichier caché
    assert scellement.value.code == "REJ-PACK-FICHIER-INVALIDE"


def test_deux_gabarits_ne_partagent_ni_identifiant_ni_fichier(copie):
    modifier(copie / RENOVATION, lambda d: d["gabarits"][1].update(id="soumission-sections"))
    refus(copie / RENOVATION, "REJ-PACK-DOUBLON", "gabarits")
    modifier(copie / RENOVATION,
             lambda d: d["gabarits"][1].update(id="demande-photos", fichier=d["gabarits"][0]["fichier"]))
    refus(copie / RENOVATION, "REJ-PACK-DOUBLON", "gabarits")


# ==================================================================================================== résolution
def test_sans_profil_le_pack_actif_est_le_generique():
    assert packs.pack_declare() is None
    assert packs.pack_actif().id == GENERIQUE


def _profil(contenu) -> Path:
    fichier = taxonomie.fichier_profil()
    fichier.parent.mkdir(parents=True, exist_ok=True)
    texte = contenu if isinstance(contenu, str) else yaml.safe_dump(contenu, allow_unicode=True)
    fichier.write_text(texte, encoding="utf-8")
    return fichier


def test_le_profil_choisit_le_pack_et_ses_autres_cles_sont_ignorees():
    _profil({"pack": RENOVATION, "services": ["gouttieres"]})
    assert packs.pack_declare() == RENOVATION
    assert packs.pack_actif().id == RENOVATION


def test_un_pack_nomme_mais_inconnu_n_est_jamais_remplace_par_le_generique():
    _profil({"pack": "plomberie-qc"})
    with pytest.raises(RefusPack) as exc:
        packs.pack_actif()
    assert exc.value.code == "REJ-PACK-NON-INSTALLE" and "plomberie-qc" in exc.value.detail


@pytest.mark.parametrize("contenu", [{"pack": 12}, {"pack": ""}, {"pack": ["a"]}, {"pack": "  "}, "pack: [x\n",
                                     "- pack\n"])
def test_un_profil_illisible_ou_une_cle_pack_mal_formee_est_refuse(contenu):
    _profil(contenu)
    with pytest.raises(RefusPack) as exc:
        packs.pack_actif()
    assert exc.value.code == "REJ-PACK-PROFIL-INVALIDE"


@pytest.mark.parametrize("identifiant", ["../etc", "Renovation", "a/b", "", "x" * 65, "-debut", "pack_souligne", ".."])
def test_un_identifiant_de_pack_hostile_est_refuse_avant_toute_lecture(identifiant):
    with pytest.raises(RefusPack) as exc:
        packs.charger_pack(identifiant)
    assert exc.value.code == "REJ-PACK-ID-INVALIDE"


def test_un_dossier_de_pack_qui_est_un_lien_hors_de_la_racine_est_refuse(copie, tmp_path):
    (copie / "evil").symlink_to(copie / RENOVATION, target_is_directory=True)
    with pytest.raises(RefusPack) as exc:
        packs.charger_pack("evil", copie)
    assert exc.value.code in ("REJ-PACK-INTROUVABLE", "REJ-PACK-ID-INVALIDE")


def test_enregistrer_un_pack_ecrit_la_cle_sans_toucher_aux_autres():
    fichier = _profil({"services": ["gouttieres"], "zone_desservie": ["Laval"]})
    assert packs.enregistrer_pack(RENOVATION) == fichier
    contenu = yaml.safe_load(fichier.read_text(encoding="utf-8"))
    assert contenu == {"services": ["gouttieres"], "zone_desservie": ["Laval"], "pack": RENOVATION}
    assert packs.pack_actif().id == RENOVATION


def test_enregistrer_un_pack_inconnu_ou_casse_n_ecrit_rien(copie, monkeypatch):
    assert not taxonomie.fichier_profil().exists()
    with pytest.raises(RefusPack) as exc:
        packs.enregistrer_pack("inconnu")
    assert exc.value.code == "REJ-PACK-NON-INSTALLE" and not taxonomie.fichier_profil().exists()
    (copie / RENOVATION / "pack.yaml").write_text("x: 1\n", encoding="utf-8")  # empreinte cassée
    monkeypatch.setenv("OPSYS_PACKS", str(copie))
    with pytest.raises(RefusPack):
        packs.enregistrer_pack(RENOVATION)
    assert not taxonomie.fichier_profil().exists()


def test_enregistrer_un_pack_signe_au_journal_d_audit(session):
    from sqlalchemy import select

    from opsys.stockage.schema import JOURNAL

    packs.enregistrer_pack(RENOVATION, par="admin-fictif")
    with session() as cnx:
        lignes = cnx.execute(select(JOURNAL.c.action, JOURNAL.c.par, JOURNAL.c.details)
                             .where(JOURNAL.c.action == "entreprise.pack")).all()
    assert len(lignes) == 1 and lignes[0].par == "admin-fictif"
    details = json.loads(lignes[0].details)
    assert details["pack"] == RENOVATION and details["empreinte"] == packs.charger_pack(RENOVATION).empreinte


def test_enregistrer_un_pack_dans_un_profil_illisible_est_un_refus_typé():
    _profil("services: [x\n")
    with pytest.raises(RefusPack) as exc:
        packs.enregistrer_pack(RENOVATION)
    assert exc.value.code == "REJ-PACK-PROFIL-INVALIDE"


def test_verifier_packs_nomme_un_pack_altere_un_defaut_absent_et_un_profil_casse(copie, monkeypatch):
    monkeypatch.setenv("OPSYS_PACKS", str(copie))
    assert packs.verifier_packs() == []
    fichier = copie / RENOVATION / "pack.yaml"
    fichier.write_text(fichier.read_text(encoding="utf-8") + "\n# modifié\n", encoding="utf-8")
    problemes = packs.verifier_packs()
    assert len(problemes) == 1 and "REJ-PACK-EMPREINTE" in problemes[0]
    shutil.rmtree(copie / GENERIQUE)
    assert any("pack par défaut" in p for p in packs.verifier_packs())
    _profil({"pack": "inconnu"})
    assert any("REJ-PACK-NON-INSTALLE" in p for p in packs.verifier_packs())
    assert packs.verifier_packs(racine=copie / "absent") == [f"dossier des packs introuvable : {copie / 'absent'}"]


def test_la_racine_des_packs_se_remplace_par_l_environnement(copie, monkeypatch):
    assert packs.racine_packs() == PACKS
    monkeypatch.setenv("OPSYS_PACKS", str(copie))
    assert packs.racine_packs() == copie
    assert packs.pack_actif().dossier == copie / GENERIQUE


def test_les_termes_installes_sont_l_union_des_packs():
    assert set(packs.termes_sectoriels_installes()) == set(packs.charger_pack(RENOVATION).termes_sectoriels)


# ==================================================================================================== rendu
def test_un_jeton_se_resout_par_le_vocabulaire_et_son_espace_disparait_avec_lui_si_le_pack_est_vide():
    reno, generique = packs.charger_pack(RENOVATION), packs.charger_pack(GENERIQUE)
    texte = "Tu es l'adjoint d'une entreprise {{qualificatif_secteur}} au Québec ({{secteur}})."
    assert packs.rendre_jetons(texte, reno) == (
        "Tu es l'adjoint d'une entreprise de rénovation extérieure au Québec (rénovation extérieure au Québec).")
    assert packs.rendre_jetons(texte, generique) == "Tu es l'adjoint d'une entreprise au Québec ()."
    assert packs.rendre_jetons("Sans jeton.\n", reno) == "Sans jeton.\n"


@pytest.mark.parametrize("texte", ["{{inconnu}}", "{{ qualificatif_secteur }}", "{{qualificatif_secteur}", "a {{}} b",
                                   "}} perdu", "{{secteur}}{{"])
def test_un_jeton_inconnu_ou_mal_forme_est_refuse_jamais_laisse_dans_un_prompt(texte):
    with pytest.raises(RefusPack) as exc:
        packs.rendre_jetons(texte, packs.charger_pack(RENOVATION))
    assert exc.value.code == "REJ-PACK-JETON-INCONNU"


@pytest.mark.parametrize("code,cle", [("M1", "m01"), ("m7", "m07"), ("M10", "m10")])
def test_cle_de_departement(code, cle):
    assert packs.rendu.cle_departement(code) == cle


@pytest.mark.parametrize("code", ["M0", "M11", "m-1", "", "M1x", "00"])
def test_un_departement_hors_m1_m10_est_refuse(code):
    with pytest.raises(RefusPack) as exc:
        packs.bloc_sectoriel(packs.charger_pack(RENOVATION), code)
    assert exc.value.code == "REJ-PACK-DEPARTEMENT-INCONNU"


def test_le_bloc_sectoriel_porte_l_identite_du_pack_et_ses_sections():
    reno = packs.charger_pack(RENOVATION)
    for code in ("M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9", "M10"):
        bloc = packs.bloc_sectoriel(reno, code)
        cle = packs.rendu.cle_departement(code)
        assert f"pack `{RENOVATION}` v{reno.version}" in bloc and reno.empreinte[:19] in bloc
        assert reno.blocs[cle].ligne in bloc
        assert ("Services de référence :" in bloc) == ("services" in reno.blocs[cle].inclure)
    m3 = packs.bloc_sectoriel(reno, "M3")
    assert "à fournir par l'entreprise" in m3 and "aucune valeur n'est supposée" in m3


def test_le_bloc_du_pack_generique_ne_suppose_aucun_secteur_et_est_le_meme_pour_chaque_departement():
    g = packs.charger_pack(GENERIQUE)
    blocs = {packs.bloc_sectoriel(g, f"M{n}") for n in range(1, 11)}
    assert len(blocs) == 1
    (bloc,) = blocs
    assert "Aucun secteur d'activité n'est déclaré" in bloc and g.empreinte[:19] in bloc
    assert packs.termes_trouves(bloc, packs.termes_sectoriels_installes()) == []


def test_copier_un_skill_rend_les_jetons_et_laisse_les_autres_fichiers_intacts(tmp_path):
    source = tmp_path / "skill"
    (source / "ressources").mkdir(parents=True)
    (source / "SKILL.md").write_text(
        "---\nname: s\ndescription: Estimer un projet {{qualificatif_secteur}} ici.\n---\n", encoding="utf-8")
    (source / "ressources" / "note.md").write_text("Sans jeton.\n", encoding="utf-8")
    (source / "ressources" / "donnees.bin").write_bytes(b"\x00\x01{{secteur}}")
    reno, generique = packs.charger_pack(RENOVATION), packs.charger_pack(GENERIQUE)
    packs.copier_skill(source, tmp_path / "reno", reno)
    packs.copier_skill(source, tmp_path / "gen", generique)
    assert "projet de rénovation extérieure ici" in (tmp_path / "reno" / "SKILL.md").read_text(encoding="utf-8")
    assert "projet ici" in (tmp_path / "gen" / "SKILL.md").read_text(encoding="utf-8")
    binaire = tmp_path / "gen" / "ressources" / "donnees.bin"
    assert binaire.read_bytes() == b"\x00\x01{{secteur}}"  # binaire non touché
    (source / "SKILL.md").write_text("{{jeton_inconnu}}", encoding="utf-8")
    with pytest.raises(RefusPack):
        packs.copier_skill(source, tmp_path / "x", reno)


# ==================================================================================================== termes
def test_la_recherche_de_termes_ignore_accents_et_casse_et_traite_le_souligne_comme_separateur():
    termes = ["rénovation", "descente pluviale", "Synergy"]
    assert packs.termes_trouves("La RENOVATION_TOTALE et la Descente-Pluviale de SYNERGY.", termes) == termes
    assert packs.termes_trouves("Une innovation", termes) == []  # début de mot : pas « rénovation »
    assert packs.termes_trouves("antirénovation", ["rénovation"]) == []
    assert [n for n, _, _ in packs.lignes_avec_termes("a\nsoffite ici\nb\n", ["soffite"])] == [2]


# ==================================================================================================== CLI
def _cli(capsys, *args):
    code = cli.main(["pack", *args])
    sortie = capsys.readouterr()
    return code, sortie.out, sortie.err


def test_cli_lister_valider_afficher(capsys):
    code, sortie, _ = _cli(capsys, "lister")
    etat = json.loads(sortie)
    assert code == 0 and etat["installes"] == [GENERIQUE, RENOVATION] and etat["effectif"]["id"] == GENERIQUE
    code, sortie, _ = _cli(capsys, "valider")
    assert code == 0 and f"OK : {RENOVATION}" in sortie and f"OK : {GENERIQUE}" in sortie
    code, sortie, _ = _cli(capsys, "valider", "--pack", RENOVATION)
    assert code == 0 and "4 service(s)" in sortie
    code, sortie, _ = _cli(capsys, "afficher", RENOVATION, "--departement", "M6")
    assert code == 0 and packs.bloc_sectoriel(packs.charger_pack(RENOVATION), "M6") in sortie


def test_cli_refus_typés_en_json_sur_la_sortie_d_erreur(capsys):
    code, _, erreur = _cli(capsys, "afficher", "inconnu", "--departement", "M1")
    assert code == 2 and json.loads(erreur)["code"] == "REJ-PACK-NON-INSTALLE"
    code, _, erreur = _cli(capsys, "afficher", RENOVATION, "--departement", "M42")
    assert code == 2 and json.loads(erreur)["code"] == "REJ-PACK-DEPARTEMENT-INCONNU"
    code, _, erreur = _cli(capsys, "empreinte", "../packs")
    assert code == 2 and json.loads(erreur)["code"] == "REJ-PACK-ID-INVALIDE"


def test_cli_empreinte_ecrire_regenere_apres_revue_et_refuse_un_pack_invalide(capsys, copie, monkeypatch):
    monkeypatch.setenv("OPSYS_PACKS", str(copie))
    fichier = copie / GENERIQUE / "pack.yaml"
    texte = fichier.read_text(encoding="utf-8")
    fichier.write_text(texte.replace("version: 1.0.0", "version: 1.0.1"), encoding="utf-8")
    assert _cli(capsys, "valider", "--pack", GENERIQUE)[0] == 2  # modifié sans revue : refus
    code, sortie, _ = _cli(capsys, "empreinte", GENERIQUE)
    assert code == 0 and sortie.strip() == mf.calculer_empreinte(copie / GENERIQUE)
    code, sortie, _ = _cli(capsys, "empreinte", GENERIQUE, "--ecrire")
    assert code == 0 and (copie / GENERIQUE / "EMPREINTE.sha256").read_text(encoding="utf-8").strip() in sortie
    assert _cli(capsys, "valider", "--pack", GENERIQUE)[0] == 0
    fichier.write_text(fichier.read_text(encoding="utf-8").replace("schema: opsys.pack/v1", "schema: autre"),
                       encoding="utf-8")
    code, _, erreur = _cli(capsys, "empreinte", GENERIQUE, "--ecrire")
    assert code == 2 and json.loads(erreur)["code"] == "REJ-PACK-SCHEMA"  # jamais sceller un pack invalide


def test_cli_choisir_ecrit_le_profil_et_verifier_voit_le_pack_actif(capsys, session):
    code, sortie, _ = _cli(capsys, "choisir", RENOVATION, "--par", "admin-fictif")
    assert code == 0 and sortie.strip() == str(taxonomie.fichier_profil())
    assert packs.pack_actif().id == RENOVATION
    assert json.loads(_cli(capsys, "lister")[1])["declare_dans_le_profil"] == RENOVATION
    taxonomie.enregistrer_services(taxonomie.codes_catalogue())  # le profil garde ses autres clés
    assert packs.pack_declare() == RENOVATION
    assert cli.main(["verifier"]) == 0
    assert f"(actif : {RENOVATION})" in capsys.readouterr().out
    code, _, erreur = _cli(capsys, "choisir", "inconnu", "--par", "admin-fictif")
    assert code == 2 and json.loads(erreur)["code"] == "REJ-PACK-NON-INSTALLE"


def test_opsys_metier_verifier_refuse_un_pack_altere(capsys, copie, monkeypatch):
    monkeypatch.setenv("OPSYS_PACKS", str(copie))
    fichier = copie / RENOVATION / "pack.yaml"
    fichier.write_text(fichier.read_text(encoding="utf-8").replace("Réparation", "Réparations", 1), encoding="utf-8")
    assert cli.main(["verifier"]) == 1
    erreur = capsys.readouterr().err
    assert "packs sectoriels invalides" in erreur and "REJ-PACK-EMPREINTE" in erreur
