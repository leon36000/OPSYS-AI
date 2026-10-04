"""Les outils de preuve doivent être EXÉCUTABLES là où ils sont livrés.

Une revue scellée a rendu APPROVE 0/3 sur une première version du dossier
``outils_preuve`` : elle embarquait ``muter_plancher.py`` alors que
``plancher.py`` n'existait pas encore sur la branche. Le script plantait sur
``FileNotFoundError``, et les sorties présentées dans le pack avaient été
produites sur une AUTRE branche — donc irreproductibles là où on les montrait.
"""

import ast
import hashlib
import sys
from pathlib import Path

_RACINE = Path(__file__).resolve().parents[1]
_OUTILS = Path(__file__).resolve().parent / "outils_preuve"
_SOURCE = _RACINE / "src" / "m3_estimation"
sys.path.insert(0, str(_RACINE / "src"))


def _outils_de_mutation():
    """Les scripts muter_<module>.py présents, triés — jamais une liste vide."""
    trouves = sorted(_OUTILS.glob("muter_*.py"))
    assert trouves, (
        f"aucun outil de mutation trouvé sous {_OUTILS} — un scanner qui ne "
        f"trouve rien passe toujours, donc ce test refuse de conclure"
    )
    return trouves


def _outils_python():
    """Tous les outils Python livrés, triés — jamais une liste vide."""
    trouves = sorted(_OUTILS.glob("*.py"))
    assert trouves, (
        f"aucun outil Python trouvé sous {_OUTILS} — un scanner qui ne trouve "
        f"rien passe toujours, donc ce test refuse de conclure"
    )
    return trouves


def _noms_cibles(noeud):
    """Retourne récursivement les noms liés par une cible d'affectation."""
    if isinstance(noeud, ast.Name):
        return [noeud.id]
    if isinstance(noeud, (ast.Tuple, ast.List)):
        return [
            nom
            for element in noeud.elts
            for nom in _noms_cibles(element)
        ]
    return []


def _chaines_de_valeur(valeur):
    """Extrait les littéraux chaîne réellement atteignables depuis une valeur."""
    return [
        noeud.value
        for noeud in ast.walk(valeur)
        if isinstance(noeud, ast.Constant) and isinstance(noeud.value, str)
    ]


def _valeur_est_un_chemin_source(valeur):
    """Distingue un chemin source d'un leurre affecté à une majuscule."""
    return (
        any(
            isinstance(noeud, ast.BinOp) and isinstance(noeud.op, ast.Div)
            for noeud in ast.walk(valeur)
        )
        or any("m3_estimation" in chaine for chaine in _chaines_de_valeur(valeur))
    )


def _affectations_chemins_source(arbre):
    """Extrait les littéraux des affectations majuscules de chemins source."""
    affectations = []
    for noeud in ast.walk(arbre):
        if isinstance(noeud, ast.Assign):
            noms = [
                nom
                for cible in noeud.targets
                for nom in _noms_cibles(cible)
                if nom.isupper()
            ]
            valeur = noeud.value
        elif isinstance(noeud, ast.AnnAssign):
            noms = [
                nom
                for nom in _noms_cibles(noeud.target)
                if nom.isupper()
            ]
            valeur = noeud.value
        else:
            continue

        if not noms or valeur is None or not _valeur_est_un_chemin_source(valeur):
            continue

        chaines = _chaines_de_valeur(valeur)
        for nom in noms:
            affectations.append((nom, chaines))
    return affectations


def test_chaque_outil_de_mutation_a_son_module_cible():
    """Un `muter_<module>.py` sans `<module>.py` plante au lieu de mesurer.

    Empêcherait de casser : la livraison d'un outil dont la cible n'existe pas
    encore sur la branche — exactement le défaut trouvé par la revue, où le
    script rendait FileNotFoundError et où les sorties du pack venaient d'une
    autre branche.
    """
    orphelins = []
    for outil in _outils_de_mutation():
        module = outil.stem[len("muter_"):]
        if not (_SOURCE / f"{module}.py").exists():
            orphelins.append(f"{outil.name} cible {module}.py, absent de {_SOURCE}")
    assert not orphelins, (
        "outil(s) de preuve sans cible — un outil ne vit dans le dépôt qu'avec "
        "le module qu'il mesure :\n  " + "\n  ".join(orphelins)
    )


def test_chaque_outil_de_mutation_declare_sa_cible_dans_son_code():
    """Exige une cible dans une affectation majuscule réellement liée à un chemin.

    Le nom du script ne suffit pas, mais une chaîne libre, une docstring ou une
    affectation à un nom minuscule ne suffit pas davantage. Deux formes correctes
    coexistent : un chemin complet construit dans une seule affectation, ou un
    dossier déclaré puis des noms de fichiers affectés simultanément dans un tuple.
    L'extracteur examine donc chaque nom majuscule de ces tuples et les littéraux
    atteignables dans leur valeur, y compris au sein d'opérateurs ``/`` imbriqués.
    Il refuse néanmoins un leurre tel que ``LEURRE = "foo.py"`` : l'affectation
    doit faire intervenir ``/`` ou contenir explicitement ``m3_estimation``.
    """
    discordances = []
    for outil in _outils_de_mutation():
        attendu = outil.stem[len("muter_"):]
        arbre = ast.parse(outil.read_text(encoding="utf-8"))
        affectations = _affectations_chemins_source(arbre)
        vise = any(
            chaine == f"{attendu}.py" or chaine.endswith(f"/{attendu}.py")
            for _, chaines in affectations
            for chaine in chaines
        )
        if not vise:
            examinees = [
                f"{nom}={chaines!r}"
                for nom, chaines in affectations
            ]
            discordances.append(
                f"{outil.name} : affectations examinées "
                f"{'; '.join(examinees) if examinees else '<aucune>'}"
            )
    assert not discordances, (
        "le nom du script ne correspond pas au module qu'il mesure :\n  "
        + "\n  ".join(discordances)
    )


def _racine_nom(expression):
    """Nom de la racine d'une chaîne d'attributs/appels (ex. ``SRC.parent`` -> ``"SRC"``)."""
    while isinstance(expression, (ast.Attribute, ast.Subscript)):
        expression = expression.value
    if isinstance(expression, ast.Call):
        return _racine_nom(expression.func)
    if isinstance(expression, ast.Name):
        return expression.id
    return None


def test_aucun_outil_de_preuve_n_ecrit_jamais_dans_la_vraie_source():
    """Preuve STRUCTURELLE (PLAN T0.12) : aucun outil n'écrit jamais ``SRC``/``TESTS`` eux-mêmes.

    C'est cette propriété qui rend un ``kill -9`` en cours de mutation sans danger pour
    ``departments/m03-estimation/src`` : le code ne contient tout simplement plus aucun appel
    qui y écrit, donc plus aucune fenêtre temporelle où l'écrire serait possible — contrairement
    à l'ancien schéma « écrire le mutant dans la vraie source, la restaurer dans un ``finally`` ».
    C'est arrivé le 2026-09-28 dans ``blocage_prix.py`` : ``muter_blocage_prix.py`` écrivait
    ``SRC.write_text(mutant)`` puis restaurait dans un ``finally`` — un processus tué entre les
    deux a laissé le mutant en place, jusqu'à son commit accidentel par une story sans rapport
    (``899bbad``, cf. ``git blame`` sur la ligne corrigée de ``blocage_prix.py``). Chaque outil
    reçoit désormais sa propre copie jetable (``_environnement_mutation.EnvironnementMutation``)
    et n'écrit plus que dans celle-ci ; ce test échouerait si un ``SRC.write_text(...)`` ou
    ``TESTS.write_text(...)`` réapparaissait dans un outil, sous quelque forme que ce soit
    (``SRC.write_text(...)``, ``SRC.parent.write_text(...)``, etc.).
    """
    racines_interdites = {"SRC", "TESTS"}
    fautifs = []
    for outil in _outils_python():
        arbre = ast.parse(outil.read_text(encoding="utf-8"))
        for noeud in ast.walk(arbre):
            if (
                isinstance(noeud, ast.Call)
                and isinstance(noeud.func, ast.Attribute)
                and noeud.func.attr == "write_text"
            ):
                racine = _racine_nom(noeud.func.value)
                if racine in racines_interdites:
                    fautifs.append(f"{outil.name}:{noeud.lineno} écrit {racine}.write_text(...)")

    assert not fautifs, (
        "outil(s) de preuve écrivant directement dans la vraie source/tests du dépôt :\n  "
        + "\n  ".join(fautifs)
    )


def _hashes_source_capture(preuve):
    prefixe = "department:m03-estimation/src/"
    avant = {
        entree.chemin.removeprefix(prefixe): entree.sha256
        for entree in preuve.avant.entrees
        if entree.chemin.startswith(prefixe) and entree.chemin.endswith(".py")
    }
    apres = {
        entree.chemin.removeprefix(prefixe): entree.sha256
        for entree in preuve.apres.entrees
        if entree.chemin.startswith(prefixe) and entree.chemin.endswith(".py")
    }
    actuel = {
        str(Path("m3_estimation") / chemin.relative_to(_SOURCE)): hashlib.sha256(
            chemin.read_bytes()
        ).hexdigest()
        for chemin in sorted(_SOURCE.rglob("*.py"))
    }
    return avant, apres, actuel


def test_capture_source_se_reconcilie_avec_les_fichiers_reels(campagne_gardes):
    """Contrôle léger du chemin relatif entre les reçus et la source M3 réelle."""
    preuve = campagne_gardes.sans_garde_preuve().preuve
    avant, apres, actuel = _hashes_source_capture(preuve)
    assert preuve.nettoyage_prouve
    assert avant, "la capture réelle ne contient aucun fichier Python source M3"
    assert avant == apres == actuel, (
        "les captures autour du subprocess ou la source actuelle divergent"
    )


def test_empreinte_source_reelle_identique_dans_la_preuve_nominale(campagne_gardes):
    """Vérifie les captures d'une batterie réelle, pas des hashes autour d'un accès cache."""
    outil = _OUTILS / "muter_registre.py"
    assert outil.exists(), f"outil de référence absent : {outil}"
    acces = campagne_gardes.nominal(outil)
    preuve = acces.preuve
    acces_reutilise = campagne_gardes.nominal(outil)
    assert acces_reutilise.processus_lance_ici is False
    assert acces_reutilise.preuve is preuve
    assert preuve.retour == 0, (
        f"la batterie de référence n'est pas saine:\n{preuve.stdout}\n{preuve.stderr}"
    )
    avant, apres, actuel = _hashes_source_capture(preuve)
    assert preuve.nettoyage_prouve, "la batterie réelle n'a pas de captures égales"
    assert avant, "la capture réelle ne contient aucun fichier Python source M3"
    assert avant == apres == actuel, (
        "les captures autour du subprocess ou la source actuelle divergent"
    )


def test_les_outils_transverses_sont_presents_et_documentes():
    """Chaque outil livré explique sa portée et ses limites dans une docstring.

    Un dossier vide est refusé explicitement : l'absence d'outil ne constitue pas
    une preuve. La vérification couvre indifféremment les mutateurs, l'énumérateur,
    le bilan et tout autre script Python ajouté au dossier de preuve.
    """
    insuffisants = []
    for chemin in _outils_python():
        doc = ast.get_docstring(ast.parse(chemin.read_text(encoding="utf-8")))
        if not doc or len(doc) <= 200:
            insuffisants.append(chemin.name)

    assert not insuffisants, (
        "outil(s) sans docstring substantiel expliquant leur portée : "
        + ", ".join(insuffisants)
    )
