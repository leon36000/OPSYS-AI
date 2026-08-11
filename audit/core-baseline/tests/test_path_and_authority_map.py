"""C00-004 — Tests RED→GREEN pour la carte des chemins canoniques et des
autorités."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

WORKTREE = Path(__file__).resolve().parents[3]
BASE = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(BASE))
import custody
import path_and_authority_map as pam
from path_and_authority_map import (
    PathMap,
    Authority,
    ConflitCheminRefuse,
    WriterCoreSurModulesRefuse,
    AdaptationSilencieuseRefusee,
    IncoherenceStatutChemin,
    InventaireDeriveRefuse,
    CHEMINS_CORE_EXISTANTS_PEUPLES,
    CHEMIN_CORE_NOUVEAU,
    MODULES_SRC_ROOTS,
    STATUTS_VALIDES,
    resoudre_chemin_canonique,
    construire_carte_chemins,
    construire_carte_autorites,
    produire_sorties_carte,
    _chemin_egal_ou_sous_chemin_de,
)

# ---------------------------------------------------------------------------
# 3 cas RED obligatoires (noms imposés par le Task Spec)
# ---------------------------------------------------------------------------


def test_ratifier_la_carte_des_chemins_et_des_autorit_s_1():
    """RED obligatoire : « bloquer un conflit avec core/src/authz ou
    core/src/config ». Un chemin RÉELLEMENT peuplé ne peut jamais être
    déclaré RESERVED_NEW — vérifié sur authz ET config nommément par le
    Task Spec, plus auth (trouvé par le même inventaire, même motif)."""
    for chemin_peuple in ("core/src/authz", "core/src/config", "core/src/auth"):
        with pytest.raises(ConflitCheminRefuse, match="RESERVED_NEW"):
            PathMap("x", chemin_peuple, "RESERVED_NEW")

    # La carte RÉELLE ne commet jamais cette erreur : authz/config/auth
    # ressortent EXISTING_SHIM_REQUIRED, jamais RESERVED_NEW.
    carte = construire_carte_chemins(WORKTREE)
    par_chemin = {p.actual_path: p for p in carte}
    for chemin_peuple in CHEMINS_CORE_EXISTANTS_PEUPLES:
        assert par_chemin[chemin_peuple].status == "EXISTING_SHIM_REQUIRED"

    # opsys_core : peuplé pour de vrai par C03-001 (PR #498) depuis la
    # ratification initiale de C00-004 — re-ratifié EXISTING_CORE_OWNED par
    # ce chore (jamais RESERVED_NEW une fois peuplé, cf. cas RED ci-dessous).
    assert par_chemin[CHEMIN_CORE_NOUVEAU].status == "EXISTING_CORE_OWNED"


def test_ratifier_la_carte_des_chemins_et_des_autorit_s_2():
    """RED obligatoire : « interdire un writer Core sur les vérités
    M1-M10 ». Aucune Authority(owner=CORE) ne peut porter un write_port
    référençant la racine src d'un module."""
    for nom_module, racine in MODULES_SRC_ROOTS.items():
        with pytest.raises(WriterCoreSurModulesRefuse, match="CORE"):
            Authority(owner="CORE", aggregate=nom_module, read_port=racine, write_port=racine)

    # La carte RÉELLE ne porte AUCUNE ligne CORE dont write_port pointe vers
    # une racine de module — vérifié sur les 10, pas seulement un exemple.
    autorites = construire_carte_autorites()
    racines_modules = set(MODULES_SRC_ROOTS.values())
    lignes_core = [a for a in autorites if a.owner == "CORE"]
    assert len(lignes_core) > 0, "aucune ligne CORE — le test ne prouverait rien"
    for a in lignes_core:
        assert a.write_port not in racines_modules, f"{a.aggregate} : write_port fuit vers un module"


def test_ratifier_la_carte_des_chemins_et_des_autorit_s_3():
    """RED obligatoire : « interdire une adaptation silencieuse de
    chemin ». Un logical_path hors de la liste blanche doit lever, jamais
    résoudre vers un chemin deviné/approximé."""
    for inconnu in ("core.nimporte_quoi", "module.M11-fantome", "", "core.opsys_core "):
        with pytest.raises(AdaptationSilencieuseRefusee):
            resoudre_chemin_canonique(inconnu)


# ---------------------------------------------------------------------------
# PathMap / Authority — gel + gardes à l'instanciation directe
# ---------------------------------------------------------------------------


def test_path_map_est_gelee():
    p = PathMap("core.opsys_core", CHEMIN_CORE_NOUVEAU, "EXISTING_CORE_OWNED")
    with pytest.raises(AttributeError):
        p.status = "AMENDMENT_REQUIRED"


def test_path_map_refuse_status_hors_liste_blanche():
    with pytest.raises(ValueError, match="hors liste blanche"):
        PathMap("x", "y", "STATUT_INVENTE")


def test_path_map_refuse_champ_vide():
    with pytest.raises(ValueError):
        PathMap("", "y", "RESERVED_NEW")


def test_path_map_refuse_existing_shim_required_sur_chemin_non_peuple():
    """IncoherenceStatutChemin : un chemin déclaré EXISTING_SHIM_REQUIRED
    mais absent de l'inventaire des services Core peuplés est une
    déclaration fausse — refusée nommément."""
    with pytest.raises(IncoherenceStatutChemin, match="EXISTING_SHIM_REQUIRED"):
        PathMap("core.invente", "core/src/n_existe_pas", "EXISTING_SHIM_REQUIRED")


def test_path_map_refuse_existing_module_owned_sur_racine_inconnue():
    with pytest.raises(IncoherenceStatutChemin, match="EXISTING_MODULE_OWNED"):
        PathMap("module.invente", "Modules M/M11-fantome/src", "EXISTING_MODULE_OWNED")


def test_path_map_refuse_opsys_core_declare_reserved_new_maintenant_peuple():
    """Cas RED 1, extension (chore post C03-001, PR #498) : depuis que
    core/src/opsys_core est réellement peuplé, le redéclarer RESERVED_NEW
    est le MÊME mensonge que pour core/src/authz ou core/src/config —
    refusé par la même garde, élargie à ce chemin. Élargir un REFUS est
    sûr (cf. docstring de `_chemin_egal_ou_sous_chemin_de`, portée
    volontairement limitée aux gardes de refus, jamais aux gardes de
    cohérence)."""
    with pytest.raises(ConflitCheminRefuse, match="RESERVED_NEW"):
        PathMap("x", CHEMIN_CORE_NOUVEAU, "RESERVED_NEW")


def test_path_map_refuse_existing_core_owned_sur_chemin_different():
    """IncoherenceStatutChemin, symétrique de EXISTING_SHIM_REQUIRED/
    EXISTING_MODULE_OWNED : EXISTING_CORE_OWNED ne peut être déclaré que
    sur CHEMIN_CORE_NOUVEAU exactement — égalité STRICTE (jamais la
    comparaison souple de sous-chemin, réservée aux gardes de refus)."""
    with pytest.raises(IncoherenceStatutChemin, match="EXISTING_CORE_OWNED"):
        PathMap("core.invente", "core/src/pas_opsys_core", "EXISTING_CORE_OWNED")


@pytest.mark.parametrize("variante", [
    "core/src/opsys_core/kernel.py", "core/src/opsys_core/", "core/src/opsys_core/status",
])
def test_path_map_refuse_existing_core_owned_meme_sur_un_sous_chemin(variante):
    """Piège nommé en revue d'architecture (chore de re-ratification) : la
    garde de COHÉRENCE EXISTING_CORE_OWNED doit rester une égalité STRICTE.
    Si elle utilisait la comparaison souple _chemin_egal_ou_sous_chemin_de
    (réservée aux gardes de REFUS), un sous-chemin de CHEMIN_CORE_NOUVEAU
    passerait à tort — alors que les gardes EXISTING_SHIM_REQUIRED/
    EXISTING_MODULE_OWNED existantes le refusent déjà par construction
    (comparaison `in` sur un ensemble, jamais un préfixe)."""
    with pytest.raises(IncoherenceStatutChemin, match="EXISTING_CORE_OWNED"):
        PathMap("core.invente", variante, "EXISTING_CORE_OWNED")


def test_path_map_accepte_amendment_required():
    """AMENDMENT_REQUIRED est un statut légitime — pas soumis aux mêmes
    contraintes qu'EXISTING_*/RESERVED_NEW (aucun chemin réel n'est promis)."""
    p = PathMap("core.futur", "UNRESOLVED — motif documenté", "AMENDMENT_REQUIRED")
    assert p.status == "AMENDMENT_REQUIRED"


def test_authority_est_gelee_et_gardee():
    a = Authority("M1-front-office", "M1-front-office", "x", "x")
    with pytest.raises(AttributeError):
        a.owner = "CORE"
    with pytest.raises(ValueError):
        Authority("", "x", "y", "z")


@pytest.mark.parametrize("variante", ["core/src/authz/", "core/src/authz/sous_dossier", "core/src/config/", "core/src/config/x/y"])
def test_path_map_ferme_le_conflit_meme_avec_slash_final_ou_sous_dossier(variante):
    """Gemini-3.1-Pro, mineure, C00-004 tour 1 (mesurée fondée, 4
    contournements reproduits) : une comparaison de chaîne exacte laissait
    passer un slash final ou un sous-dossier direct d'un chemin Core
    peuplé. Fermé par comparaison de composants (PurePosixPath.parts)."""
    with pytest.raises(ConflitCheminRefuse):
        PathMap("x", variante, "RESERVED_NEW")


@pytest.mark.parametrize("variante", [
    "Modules M/M1-front-office/src/", "Modules M/M1-front-office/src/sous_dossier",
    "Modules M/M7-marketing/src/utm",
])
def test_authority_ferme_le_writer_core_meme_avec_slash_final_ou_sous_dossier(variante):
    with pytest.raises(WriterCoreSurModulesRefuse):
        Authority("CORE", "x", "y", variante)


@pytest.mark.parametrize("variante", [
    "core/src/authz/../config",           # exemple DeepSeek-V4-Pro (ne se reproduisait pas seul, mais couvert)
    "core/src/unprotected/../authz",      # exemple Gemini-3.1-Pro (reproduit)
    "core/src/../src/authz",              # exemple Qwen3.7-Max (reproduit)
])
def test_path_map_ferme_le_conflit_meme_avec_point_point_non_normalise(variante):
    """DeepSeek-V4-Pro + Gemini-3.1-Pro + Qwen3.7-Max, MAJEURE CONVERGENTE,
    C00-004 tour 2 (mesurée fondée sur 2 des 3 exemples fournis) :
    PurePosixPath.parts ne normalise pas lexicalement '..' — un chemin
    candidat qui résout (lexicalement) vers un chemin peuplé pouvait
    contourner ConflitCheminRefuse. Fermé par os.path.normpath AVANT le
    découpage en composants."""
    with pytest.raises(ConflitCheminRefuse):
        PathMap("x", variante, "RESERVED_NEW")


def test_chemin_normalise_est_independant_de_la_plateforme(monkeypatch):
    """DeepSeek-V4-Pro + Gemini-3.1-Pro + Qwen3.7-Max, CRITIQUE+MAJEURE
    CONVERGENTE 3/3, C00-004 tour 3 (mesurée fondée) : la version tour 3
    utilisait `os.path.normpath`, un ALIAS dépendant de l'OS hôte (`ntpath`
    sous Windows, séparateur `\\`) — incompatible avec `PurePosixPath` qui
    ne découpe que sur `/`. Preuve DIRECTE de robustesse : on simule
    `os.path = ntpath` (ce qui serait réellement vrai sous Windows) et on
    vérifie que la garde continue de fonctionner — preuve que la fonction
    n'utilise JAMAIS `os.path`, seulement `posixpath` explicitement importé,
    donc son comportement est identique sur toute plateforme.

    Piège mesuré en écrivant CE test : un candidat qui se RÉSOUT (via '..')
    exactement au même texte que la référence (ex. `'core/src/unprotected/../authz'`
    vs `'core/src/authz'`) matche encore PAR COÏNCIDENCE même sous la
    normalisation buguée — les deux chaînes finissent mangled en un SEUL
    composant IDENTIQUE, donc la comparaison réussit sans que le correctif
    soit sollicité. Ce test ne discrimine PAS le bug (mesuré : passe même
    avec `os.path.normpath` réintroduit). Le cas qui discrimine RÉELLEMENT
    est un candidat avec un COMPOSANT SUPPLÉMENTAIRE après la référence (un
    vrai sous-dossier, ex. `'core/src/authz/sous_dossier'`) : sous `ntpath`,
    candidat et référence ne collapsent PAS vers la même chaîne (le
    sous-dossier reste un suffixe distinct), donc `parts_candidat[:1]` (un
    seul composant mangled) ne peut jamais égaler `parts_reference` (un
    composant mangled DIFFÉRENT) — reproduit et vérifié avant d'écrire
    l'assertion ci-dessous."""
    import ntpath
    monkeypatch.setattr(pam.os, "path", ntpath)
    assert pam._chemin_egal_ou_sous_chemin_de("core/src/authz/sous_dossier", "core/src/authz") is True
    assert pam._chemin_egal_ou_sous_chemin_de(
        "Modules M/M1-front-office/src/x", "Modules M/M1-front-office/src"
    ) is True
    assert pam._chemin_egal_ou_sous_chemin_de("core/src/authzz", "core/src/authz") is False
    # Bout en bout : la garde PathMap elle-même reste efficace sous la simulation.
    with pytest.raises(ConflitCheminRefuse):
        PathMap("x", "core/src/authz/sous_dossier", "RESERVED_NEW")


def test_authority_ferme_le_writer_core_meme_avec_point_point_non_normalise():
    with pytest.raises(WriterCoreSurModulesRefuse):
        Authority("CORE", "x", "y", "Modules M/M1-front-office/unprotected/../src")


def test_chemin_egal_ou_sous_chemin_de_normalise_point_point_sans_faux_positif():
    """Preuve directe sur le helper (pas seulement via PathMap/Authority) :
    la normalisation ferme les 3 exemples de revue ET ne casse pas le test
    anti-faux-positif existant (authzz reste distinct d'authz après
    normalisation, '..' n'introduit aucune collision inattendue)."""
    assert _chemin_egal_ou_sous_chemin_de("core/src/unprotected/../authz", "core/src/authz") is True
    assert _chemin_egal_ou_sous_chemin_de("core/src/../src/authz", "core/src/authz") is True
    assert _chemin_egal_ou_sous_chemin_de("core/src/authzz", "core/src/authz") is False
    assert _chemin_egal_ou_sous_chemin_de("core/src/../src/authzz", "core/src/authz") is False


def test_chemin_egal_ou_sous_chemin_de_ne_matche_pas_un_nom_voisin():
    """Faux positif à éviter à tout prix : un nom de dossier VOISIN
    partageant un préfixe de CHAÎNE (pas de composant) ne doit jamais
    matcher — sinon la fonction serait pire que l'ancienne comparaison
    (elle bloquerait des chemins parfaitement légitimes)."""
    assert _chemin_egal_ou_sous_chemin_de("core/src/authzz", "core/src/authz") is False
    assert _chemin_egal_ou_sous_chemin_de("core/src/authz-backup", "core/src/authz") is False
    # La carte réelle ne doit donc PAS refuser un nom voisin légitime.
    p = PathMap("x", "core/src/authzz", "RESERVED_NEW")
    assert p.status == "RESERVED_NEW"


def test_chemin_egal_ou_sous_chemin_de_cas_nominaux():
    assert _chemin_egal_ou_sous_chemin_de("core/src/authz", "core/src/authz") is True
    assert _chemin_egal_ou_sous_chemin_de("core/src/authz/x", "core/src/authz") is True
    assert _chemin_egal_ou_sous_chemin_de("core/src", "core/src/authz") is False


def test_authority_core_sur_ses_propres_chemins_est_autorise():
    """Le Core PEUT écrire dans SES PROPRES chemins (authz/config/auth/
    opsys_core) — seule l'écriture sur un chemin de MODULE est interdite."""
    a = Authority(owner="CORE", aggregate="authz", read_port="core/src/authz", write_port="core/src/authz")
    assert a.write_port == "core/src/authz"


# ---------------------------------------------------------------------------
# resoudre_chemin_canonique / construire_carte_chemins
# ---------------------------------------------------------------------------


def test_resoudre_chemin_canonique_couvre_les_3_familles():
    assert resoudre_chemin_canonique("core.opsys_core").status == "EXISTING_CORE_OWNED"
    assert resoudre_chemin_canonique("core.authz").status == "EXISTING_SHIM_REQUIRED"
    assert resoudre_chemin_canonique("module.M2-revenue-crm").status == "EXISTING_MODULE_OWNED"
    assert resoudre_chemin_canonique("core.policy_kernel").status == "AMENDMENT_REQUIRED"


def test_construire_carte_chemins_couvre_les_10_modules_et_3_services():
    carte = construire_carte_chemins(WORKTREE)
    logical_paths = {p.logical_path for p in carte}
    for nom_module in MODULES_SRC_ROOTS:
        assert f"module.{nom_module}" in logical_paths
    for service in ("auth", "authz", "config"):
        assert f"core.{service}" in logical_paths
    assert "core.opsys_core" in logical_paths
    # 3 services transversaux CA07-0002 : AMENDMENT_REQUIRED, jamais un
    # chemin inventé.
    amendements = [p for p in carte if p.status == "AMENDMENT_REQUIRED"]
    assert len(amendements) == 3
    for p in amendements:
        assert p.actual_path.startswith("UNRESOLVED")


def test_construire_carte_chemins_refuse_si_inventaire_derive(tmp_path, monkeypatch):
    """InventaireDeriveRefuse : si le disque ne confirme plus l'inventaire
    codé en dur (ici : aucun des 3 services Core n'existe dans un worktree
    vide), la carte est refusée plutôt que publiée sur une hypothèse
    fausse."""
    faux_worktree = tmp_path / "worktree_vide"
    faux_worktree.mkdir()
    with pytest.raises(InventaireDeriveRefuse):
        construire_carte_chemins(faux_worktree)


def test_construire_carte_chemins_refuse_si_opsys_core_absent(tmp_path):
    """Chore de re-ratification (post C03-001, PR #498) : depuis que
    core/src/opsys_core est EXISTING_CORE_OWNED (peuplé pour de vrai, plus
    RESERVED_NEW), il rejoint le même régime que les 3 services legacy —
    un worktree où il est ABSENT (nouveau Core jamais construit, dépendance
    amont non satisfaite) est refusé, jamais publié sur une hypothèse
    fausse. Inverse l'ancien test de ce nom (qui vérifiait l'ancien régime
    RESERVED_NEW, devenu obsolète — cf. test_path_map_refuse_opsys_core_
    declare_reserved_new_maintenant_peuple pour la garde qui a repris cette
    préoccupation à la couche PathMap)."""
    faux_worktree = tmp_path / "worktree_sans_opsys_core"
    for rel in CHEMINS_CORE_EXISTANTS_PEUPLES:
        d = faux_worktree / rel
        d.mkdir(parents=True)
        (d / "reel.py").write_text("# fichier réel\n", encoding="utf-8")
    for racine in MODULES_SRC_ROOTS.values():
        (faux_worktree / racine).mkdir(parents=True)
    # opsys_core délibérément PAS créé — worktree par ailleurs complet
    # (3 services + 10 modules) pour que la garde échoue pour la BONNE
    # raison, jamais parce qu'une boucle antérieure a levé en premier.
    with pytest.raises(InventaireDeriveRefuse, match="opsys_core"):
        construire_carte_chemins(faux_worktree)


def test_construire_carte_chemins_refuse_si_opsys_core_vide_de_fichier_reel(tmp_path):
    """Même garde, second cas (les deux branches de la condition composée
    `not chemin.is_dir() or not fichiers_reels`) : le dossier existe (ex.
    suivi par un seul .gitkeep, comme les racines de modules avant leur
    première story) mais ne contient aucun fichier réel — toujours une
    dépendance amont non satisfaite, jamais un « le dossier existe donc
    c'est bon »."""
    faux_worktree = tmp_path / "worktree_opsys_core_vide"
    for rel in CHEMINS_CORE_EXISTANTS_PEUPLES:
        d = faux_worktree / rel
        d.mkdir(parents=True)
        (d / "reel.py").write_text("# fichier réel\n", encoding="utf-8")
    for racine in MODULES_SRC_ROOTS.values():
        (faux_worktree / racine).mkdir(parents=True)
    d = faux_worktree / CHEMIN_CORE_NOUVEAU
    d.mkdir(parents=True)
    (d / ".gitkeep").write_text("", encoding="utf-8")
    with pytest.raises(InventaireDeriveRefuse, match="opsys_core"):
        construire_carte_chemins(faux_worktree)


# ---------------------------------------------------------------------------
# construire_carte_autorites
# ---------------------------------------------------------------------------


def test_construire_carte_autorites_10_modules_plus_4_core():
    autorites = construire_carte_autorites()
    assert len(autorites) == 14
    owners_modules = {a.owner for a in autorites if a.owner != "CORE"}
    assert owners_modules == set(MODULES_SRC_ROOTS)
    agregats_core = {a.aggregate for a in autorites if a.owner == "CORE"}
    assert agregats_core == {"auth", "authz", "config", "opsys_core"}


def test_construire_carte_autorites_chaque_module_est_seul_maitre_de_soi():
    autorites = construire_carte_autorites()
    par_module = {a.owner: a for a in autorites if a.owner != "CORE"}
    for nom_module, racine in MODULES_SRC_ROOTS.items():
        a = par_module[nom_module]
        assert a.read_port == racine
        assert a.write_port == racine


# ---------------------------------------------------------------------------
# Confinement — refus de symlink (mêmes primitives que C00-001/002/003)
# ---------------------------------------------------------------------------


def test_produire_sorties_refuse_sortie_dir_symlinke(tmp_path):
    faux_worktree = tmp_path / "faux_worktree"
    for rel in CHEMINS_CORE_EXISTANTS_PEUPLES:
        d = faux_worktree / rel
        d.mkdir(parents=True)
        (d / "reel.py").write_text("# reel\n", encoding="utf-8")
    for racine in MODULES_SRC_ROOTS.values():
        (faux_worktree / racine).mkdir(parents=True)
    # opsys_core doit lui aussi être peuplé ici (EXISTING_CORE_OWNED) —
    # sinon construire_carte_chemins (appelé par produire_sorties_carte
    # AVANT toute écriture) lève InventaireDeriveRefuse et ce test cesse
    # d'exercer la garde anti-symlink qu'il vise réellement.
    d = faux_worktree / CHEMIN_CORE_NOUVEAU
    d.mkdir(parents=True)
    (d / "reel.py").write_text("# reel\n", encoding="utf-8")
    ailleurs = tmp_path / "ailleurs"
    ailleurs.mkdir()
    lien = faux_worktree / "sortie"
    lien.symlink_to(ailleurs)
    with pytest.raises(custody.EcritureViaSymlinkRefusee):
        produire_sorties_carte(faux_worktree, lien)


# ---------------------------------------------------------------------------
# Sorties réelles — comptes, en-têtes, round-trip, déterminisme
# ---------------------------------------------------------------------------


class TestProductionSorties:
    """Écrit RÉELLEMENT les 2 sorties dans le répertoire du worktree —
    même motif anti-auto-référence que C00-001/002/003."""

    @pytest.fixture(autouse=True)
    def _produire(self):
        sortie_dir = Path(__file__).resolve().parent.parent
        self.chemins, self.autorites = produire_sorties_carte(WORKTREE, sortie_dir)
        self.sortie_dir = sortie_dir
        yield

    def test_canonical_path_map_json_bien_forme(self):
        obj = json.loads((self.sortie_dir / "CANONICAL-PATH-MAP.json").read_text(encoding="utf-8"))
        assert isinstance(obj, list)
        assert len(obj) == len(self.chemins)
        for ligne in obj:
            assert set(ligne.keys()) == {"logical_path", "actual_path", "status"}
            assert ligne["status"] in STATUTS_VALIDES

    def test_authority_map_csv_14_lignes_bon_entete(self):
        with open(self.sortie_dir / "AUTHORITY-MAP.csv", encoding="utf-8", newline="") as f:
            lecteur = csv.DictReader(f)
            assert lecteur.fieldnames == ["owner", "aggregate", "read_port", "write_port"]
            lignes = list(lecteur)
        assert len(lignes) == 14
        assert not any(l["owner"] == "CORE" and l["write_port"] in MODULES_SRC_ROOTS.values() for l in lignes)

    def test_sorties_sont_deterministes_octet_pour_octet(self):
        # `sortie_dir` doit rester CONFINÉ sous WORKTREE (custody l'exige
        # pour l'écriture) — impossible d'utiliser un tmp_path hors du
        # worktree ici, contrairement à C00-002/003 où racine et sortie_dir
        # pouvaient tous deux être un tmp_path arbitraire (aucune vérité
        # d'inventaire à recouper). Nettoyé dans un `finally` pour ne
        # laisser aucun résidu non suivi dans le worktree réel.
        autre_dir = WORKTREE / "audit" / "core-baseline" / "_tmp_test_determinisme"
        autre_dir.mkdir(exist_ok=True)
        try:
            produire_sorties_carte(WORKTREE, autre_dir)
            for nom in ("CANONICAL-PATH-MAP.json", "AUTHORITY-MAP.csv"):
                assert (self.sortie_dir / nom).read_bytes() == (autre_dir / nom).read_bytes()
        finally:
            import shutil
            shutil.rmtree(autre_dir, ignore_errors=True)
