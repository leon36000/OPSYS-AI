"""Environnement de mutation jetable : ne jamais écrire dans la vraie source du département.

Un processus tué pendant l'écriture d'un mutant ne doit jamais laisser la source réelle du
département dans un état saboté. C'est arrivé le 2026-09-28 dans ``blocage_prix.py`` : le
mutant ``"niveau": niveau_confiance,`` de ``muter_blocage_prix.py`` est resté écrit sur
``src/m3_estimation/blocage_prix.py`` après un arrêt du script, une story sans rapport l'a
ensuite inclus dans son commit (``git blame`` fait foi), et la suite est restée rouge jusqu'à
ce que ce fichier soit ajouté et que le module corrigé restaure le contenu correct. Ce module
ferme cette classe de risque STRUCTURELLEMENT plutôt que par discipline d'écriture-puis-
restauration : aucune fonction ici n'écrit jamais sous ``departments/m03-estimation/src`` ou
``tests`` réels. Chaque appelant obtient une copie complète et jetable, dans un dossier
temporaire créé par ``tempfile.mkdtemp``, sur laquelle porter ses mutations — un ``rmtree``
manqué (processus tué) laisse au pire un dossier orphelin sous le répertoire temporaire du
système, jamais une trace dans le dépôt.

La copie reproduit la profondeur réelle ``departments/m03-estimation/...`` sous un faux
« dossier racine » : plusieurs fichiers du département calculent des chemins à partir de leur
propre ``__file__`` — les fichiers de test remontent à ``.../src`` pour importer
``m3_estimation`` (``Path(__file__).resolve().parent.parent / "src"``), et
``docs/bmad/verif_coherence.py`` comme ``tests/test_validation_entrees.py`` remontent jusqu'à
un présumé dépôt pour lire en lecture seule ``departments/m02-revenue-crm/src/m2_revenue_crm``.
Un simple ``PYTHONPATH`` ne suffit pas à faire gagner la copie pour ``m3_estimation`` : pytest
insère d'abord la vraie source via l'option ``pythonpath`` du ``pyproject.toml`` racine, mais
chaque fichier de test réinsère ensuite, à sa propre collecte, le chemin qu'il recalcule depuis
son ``__file__`` en tête de ``sys.path`` — c'est cette réinsertion tardive qu'il faut gagner, en
plaçant réellement le fichier de test (donc son ``__file__``) dans la copie. Les autres
départements ne sont jamais mutés : ils sont liés par lien symbolique vers le dépôt réel,
jamais copiés, jamais réécrits.

``src/`` (le socle ``opsys``, dont ``opsys.evenements`` et son catalogue JSON) et le
``pyproject.toml`` racine sont liés par lien symbolique en lecture seule, par le MÊME motif que
les départements voisins ci-dessus, jamais copiés : les scripts ``muter_*.py`` invoquent pytest
avec la copie comme chemin de test mais le dépôt réel comme ``cwd`` (``cwd=RACINE``), et pytest
détermine son ``rootdir``/fichier d'options depuis le chemin des arguments, pas depuis ``cwd`` —
sans ce lien, aucun ``pyproject.toml`` n'est trouvé en remontant depuis la copie, ``pythonpath``
ne s'applique jamais, et ``import opsys`` retombe sur l'installation du paquet dans l'environnement
Python (souvent en retard sur le dépôt réel, ex. un type d'événement du catalogue ajouté après la
dernière installation) plutôt que sur les sources réelles du dépôt qu'on prétend mesurer — constaté
le 2026-09-28 (PLAN T2.3-a) : ``opsys.evenements.publier`` levait ``type d'événement inconnu`` sur
un type ajouté au catalogue dans ce commit, uniquement à l'intérieur de la copie de mutation.

``conftest.py`` racine (garde « instance isolée » et fixtures communes, dont ``declarer_services``,
PLAN T0.13) est lié par le même motif : sans lui, ``fixture 'declarer_services' not found`` fait
échouer la copie avant tout sabotage.

``docs/`` racine (ex. les politiques Loi 25, ``docs/compliance/politiques/*.md``) est lié par le
MÊME motif, à partir de PLAN T2.3 : un test de garde (``test_politique_photos.py``) lit un
document de politique hors de ``departments/m03-estimation`` pour constater son statut de
validation réel — sans ce lien, la copie de mutation ne le trouve pas (``is_file()`` faux) et la
suite y est FAUSSEMENT rouge dès AVANT tout sabotage, pour une raison sans rapport avec le module
muté (mesuré : les neuf outils de mutation échouaient tous à ``test_chaque_outil_est_sain_avant_
sabotage`` sans ce lien). Jamais copié, jamais écrit : aucun test M3 n'écrit dans ``docs/``.
"""

from __future__ import annotations

import pathlib
import shutil
import tempfile


class EnvironnementMutation:
    """Copie jetable du département M3, prête à recevoir des mutants sans toucher au disque réel."""

    def __init__(self, racine: pathlib.Path) -> None:
        self.racine_reelle = pathlib.Path(racine).resolve()
        vrai_departement = self.racine_reelle / "departments" / "m03-estimation"
        if not vrai_departement.is_dir():
            raise FileNotFoundError(f"département introuvable : {vrai_departement}")

        self.dossier = pathlib.Path(tempfile.mkdtemp(prefix="m3_mutation_"))
        departements = self.dossier / "departments"
        departements.mkdir()

        shutil.copytree(
            vrai_departement,
            departements / "m03-estimation",
            ignore=shutil.ignore_patterns("__pycache__"),
        )
        # Départements voisins : liens symboliques en lecture seule vers le dépôt réel, jamais
        # copiés ni écrits — seul m03-estimation est jamais la cible d'une mutation.
        for voisin in (self.racine_reelle / "departments").iterdir():
            if voisin.name == "m03-estimation":
                continue
            (departements / voisin.name).symlink_to(voisin, target_is_directory=voisin.is_dir())

        # Socle opsys (src/) et pyproject.toml racine : même motif, lien symbolique en lecture
        # seule — jamais copiés. Nécessaires pour que pytest retrouve le pyproject.toml racine
        # (donc son option pythonpath) en remontant depuis la copie, et que import opsys voie les
        # sources réelles du dépôt plutôt qu'une installation figée (cf. docstring du module).
        (self.dossier / "src").symlink_to(self.racine_reelle / "src", target_is_directory=True)
        (self.dossier / "pyproject.toml").symlink_to(self.racine_reelle / "pyproject.toml")
        # docs/ racine (PLAN T2.3) : même motif, même lecture seule — voir la docstring du module.
        (self.dossier / "docs").symlink_to(self.racine_reelle / "docs", target_is_directory=True)
        # conftest.py racine (PLAN T0.13) : la garde commune à tous les tests (instance isolée) et
        # ses fixtures partagées, dont `declarer_services` (profil d'entreprise de l'instance de test,
        # requis par les tests de leads v2). Même motif, même lecture seule : sans ce lien, la copie
        # échoue à `fixture 'declarer_services' not found` AVANT tout sabotage.
        (self.dossier / "conftest.py").symlink_to(self.racine_reelle / "conftest.py")

        self.dossier_departement = departements / "m03-estimation"
        self.dossier_source = self.dossier_departement / "src" / "m3_estimation"
        self.dossier_tests = self.dossier_departement / "tests"

    def cible(self, source_reelle: pathlib.Path) -> pathlib.Path:
        """Retourne, dans la copie, l'équivalent d'un fichier réel de ``src/m3_estimation``."""
        return self.dossier_source / pathlib.Path(source_reelle).name

    def purger_caches(self) -> None:
        """Supprime les caches d'octets compilés accumulés dans la copie entre deux mutants."""
        for cache in self.dossier_departement.rglob("__pycache__"):
            shutil.rmtree(cache, ignore_errors=True)

    def nettoyer(self) -> None:
        """Supprime la copie entière ; jamais appelé sur autre chose qu'un dossier temporaire."""
        shutil.rmtree(self.dossier, ignore_errors=True)
