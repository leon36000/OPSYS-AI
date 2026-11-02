#!/usr/bin/env python3
"""Batterie de mutations MÉTIER : barème déclaré, mesure déclarée, leur résolution et la voie libre (M3-C1, M3-C2).

Chaque mutation est une erreur de conception PLAUSIBLE (garde désactivée, comparaison inversée, validation retirée,
source remplacée) sur un fichier de ``src/m3_estimation`` ; la suite CIBLÉE (les fichiers de ``CIBLES``, plutôt que les
plus de deux mille tests du département) doit virer au ROUGE, et rouge À CAUSE de la mutation (un nouvel échec par
rapport à la référence verte). Une mutation qui reste verte, qui ne compile pas ou dont l'ancre est introuvable fait
sortir le script non-zéro. Les mutations qui ne mordent pas sont à DÉCLARER dans ``REDONDANCES_DECLAREES`` avec leur
raison ; le script échoue aussi si une redondance déclarée se met à mordre.

Les sources réelles ne sont jamais écrites : ``EnvironnementMutation`` travaille sur une copie jetable du département.

    python3 -B departments/m03-estimation/tests/outils_preuve/batterie_bareme_registre.py <racine du dépôt> [part/total]

``part/total`` (ex. ``2/4``) répartit les mutations entre plusieurs exécutions lancées en parallèle.
"""
import os
import pathlib
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _environnement_mutation import EnvironnementMutation
from lecture_junit import echecs_junit as _echecs_junit

RACINE = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
PART, TOTAL = (1, 1)
if len(sys.argv) > 2:
    PART, TOTAL = (int(x) for x in sys.argv[2].split("/"))

# Cible principale (les mutations touchent aussi mesure_declaree, entrees_declarees, estimation, outils, outils_bareme,
# conditions_soumission et revue_devis : voir MUTATIONS).
SRC = RACINE / "departments/m03-estimation/src/m3_estimation/bareme_registre.py"

CIBLES = (
    "test_bareme_registre.py", "test_mesure_declaree.py", "test_estimation_declaree.py", "test_outils_bareme.py",
    "test_conditions_soumission.py", "test_bareme_bout_en_bout.py", "test_revue_devis.py", "test_estimation.py",
    "test_outils_scenarios.py",
)

# (nom, fichier de src/m3_estimation, ancre unique, remplacement)
MUTATIONS = [
    # -- barème : en vigueur, date d'effet, validation, empreinte, chaînage, révision --------------------------------
    ("en vigueur : une version remplacée reste utilisable (périmée jamais refusée)", "bareme_registre.py",
     '    if courante["version"] != numero:', "    if False:"),
    ("date d'effet : l'instant exact n'est plus en vigueur (<= devient <)", "bareme_registre.py",
     '_instant(v["date_effet"], "date_effet") <= maintenant', '_instant(v["date_effet"], "date_effet") < maintenant'),
    ("date d'effet : une version future est utilisable", "bareme_registre.py",
     '    if _instant(version["date_effet"], "date_effet") > maintenant:', "    if False:"),
    ("fin de validité : l'instant exact reste en vigueur (>= devient >)", "bareme_registre.py",
     'if fin is not None and maintenant >= _instant(fin, "valide_jusqu_au"):',
     'if fin is not None and maintenant > _instant(fin, "valide_jusqu_au"):'),
    ("fin de validité : jamais appliquée", "bareme_registre.py",
     'if fin is not None and maintenant >= _instant(fin, "valide_jusqu_au"):', "if False:"),
    ("validation : une valeur de départ « à valider » est utilisable", "bareme_registre.py",
     "        if not _est_valide(version, validations):", "        if False:"),
    ("empreinte : jamais comparée", "bareme_registre.py",
     '        if empreinte is not None and empreinte != version["source_id"]:', "        if False:"),
    ("chaînage : l'empreinte du précédent n'est plus vérifiée", "bareme_registre.py",
     'or maillon["precedent"] != precedent', "or False"),
    ("chaînage : l'empreinte du maillon n'est plus recalculée", "bareme_registre.py",
     'or maillon["source_id"] != _sceller(maillon)', "or False"),
    ("révision : une version périmée peut être révisée (écrasement possible)", "bareme_registre.py",
     "        if version_attendue != len(deja):", "        if False:"),
    ("révision : la date d'effet peut reculer avant la version précédente", "bareme_registre.py",
     '        if deja and effet < _instant(deja[-1]["date_effet"], "date_effet"):', "        if False:"),
    ("auteur : un agent peut signer un barème", "bareme_registre.py",
     'ROLES_AUTEUR = frozenset({"nathan_owner", "admin"})',
     'ROLES_AUTEUR = frozenset({"nathan_owner", "admin", "system_agent"})'),
    ("ligne : coût minimum au-dessus du maximum accepté", "bareme_registre.py",
     "        if minimum > maximum:", "        if False:"),
    ("compilation : le coût maximum du moteur reçoit le minimum", "bareme_registre.py",
     '"cout_unitaire_max": float(Decimal(ouvrage["cout_unitaire_max"])),',
     '"cout_unitaire_max": float(Decimal(ouvrage["cout_unitaire_min"])),'),
    ("lecture : la copie rendue partage les lignes du registre", "bareme_registre.py",
     '    vue = {cle: copy.deepcopy(version[cle]) for cle in (', '    vue = {cle: version[cle] for cle in ('),
    # -- mesure : bornes, seuils stricts, unité, lead, auteur, péremption ---------------------------------------------
    ("mesure : bornes qui n'encadrent plus la valeur acceptées", "mesure_declaree.py",
     "    if not basse <= valeur <= haute:", "    if False:"),
    ("mesure : seuil « aucun prix » devient large (> devient >=)", "mesure_declaree.py",
     "        if largeur > Decimal(seuil_max) * valeur:", "        if largeur >= Decimal(seuil_max) * valeur:"),
    ("mesure : seuil de revue devient large (> devient >=)", "mesure_declaree.py",
     "        elif largeur > Decimal(seuil_revue) * valeur:", "        elif largeur >= Decimal(seuil_revue) * valeur:"),
    ("mesure : la confiance faible n'exige plus la revue", "mesure_declaree.py",
     '    if mesure["confiance"] == "faible":', "    if False:"),
    ("mesure : l'unité du barème n'est plus contrôlée", "mesure_declaree.py",
     '    if mesure["unite"] != unite_attendue:', "    if False:"),
    ("mesure : la mesure d'un autre lead est acceptée", "mesure_declaree.py",
     '    if mesure["lead_id"] != lead_id:', "    if False:"),
    ("mesure : un employé ou un agent peut la déclarer", "mesure_declaree.py",
     'ROLES_AUTEUR = frozenset({"nathan_owner", "admin", "seller"})',
     'ROLES_AUTEUR = frozenset({"nathan_owner", "admin", "seller", "employee", "system_agent"})'),
    ("mesure : validité déclarée allongée d'un jour", "mesure_declaree.py",
     "+ timedelta(days=validite) < maintenant", "+ timedelta(days=validite + 1) < maintenant"),
    ("mesure : bornes larges sans seuil déclaré passent sans refus", "mesure_declaree.py",
     "        if seuil_max is None:", "        if False:"),
    # -- estimation : références, enveloppe, graine, plancher, rejeu --------------------------------------------------
    ("estimation : l'enveloppe prend la quantité basse aux deux bouts", "estimation.py",
     'bareme, service, quantite_haute, graine, niveau, services=services)',
     'bareme, service, quantite_basse, graine, niveau, services=services)'),
    ("estimation : le barème libre l'emporte sur le barème déclaré", "estimation.py",
     '        bareme = declare["bareme"]\n', ""),
    ("estimation : le plancher libre l'emporte sur le plancher déclaré", "estimation.py",
     '        plancher_rentable = declare["plancher_rentable"]\n', ""),
    ("estimation : la graine libre l'emporte sur la graine dérivée", "estimation.py",
     "        graine = None  # la graine se dérive", "        pass  # la graine se dérive"),
    ("estimation : la revue humaine n'est jamais requise (reçu)", "estimation.py",
     '    revue = bool(evaluation["motifs_revue"])', "    revue = False"),
    ("estimation : arrondi au cent « au pair » (ROUND_HALF_UP devient ROUND_HALF_EVEN)", "estimation.py",
     "return float(Decimal(str(valeur)).quantize(_CENT, rounding=ROUND_HALF_UP))",
     'return float(Decimal(str(valeur)).quantize(_CENT, rounding="ROUND_HALF_EVEN"))'),
    ("déclaration : plancher absent non signalé", "entrees_declarees.py",
     '        if "plancher_rentable_cad" not in parametres:', "        if False:"),
    ("rejeu : aucun écart n'est jamais rapporté", "entrees_declarees.py",
     "    ecarts = [\n        cle for cle in (\"borne_basse\", \"borne_haute\", \"niveau\")\n"
     "        if stocke.get(cle) != recalcule[cle]\n    ]",
     "    ecarts = []"),
    ("rejeu : exige la version en vigueur (l'ancienne n'est plus rejouable)", "entrees_declarees.py",
     "journal_bareme, journal_mesures, bloc[\"bareme_ref\"], bloc[\"mesure_ref\"], maintenant, rejeu=True",
     "journal_bareme, journal_mesures, bloc[\"bareme_ref\"], bloc[\"mesure_ref\"], maintenant, "
     "rejeu=False"),
    # -- voie libre fermée aux agents, auteur humain ------------------------------------------------------------
    ("voie libre : ouverte aux appels venus du MCP (agents)", "outils_bareme.py",
     'and not contexte.appel_provient_du_mcp()', ""),
    ("voie libre : n'importe quelle valeur de la variable l'ouvre", "outils_bareme.py",
     "return os.environ.get(ENV_VOIE_LIBRE) == VALEUR_VOIE_LIBRE",
     "return bool(os.environ.get(ENV_VOIE_LIBRE, \"x\"))"),
    ("voie libre : une valeur libre est acceptée avec une référence", "outils.py",
     "    if declaree and libres:", "    if False:"),
    ("voie libre : l'absence de référence n'est plus refusée", "outils.py",
     "        if not outils_bareme.voie_libre_autorisee():\n"
     "            return {\"etape\": \"bareme\"",
     "        if False:\n            return {\"etape\": \"bareme\""),
    ("voie libre : plancher libre accepté avec une référence (aide au calcul)", "outils.py",
     "        if plancher_rentable is not None:\n            return {\"accepte\": False, \"verdict\": "
     "outils_bareme.verdict_voie_libre_refusee(\n                [\"plancher_rentable\"]",
     "        if False:\n            return {\"accepte\": False, \"verdict\": "
     "outils_bareme.verdict_voie_libre_refusee(\n                [\"plancher_rentable\"]"),
    ("auteur : l'identité n'est plus revérifiée en base", "outils_bareme.py",
     "    signataire = approbations.signataire_valide(cnx, appelante) if cnx is not None else None",
     "    signataire = appelante"),
    ("mesure : un vendeur déclare la mesure du lead d'un autre", "outils_bareme.py",
     "    if auteur[\"role\"] == _ROLE_VENDEUR and _proprietaire_du_lead(lead_id) != auteur[\"personne\"]:",
     "    if False:"),
    # -- soumission et revue -------------------------------------------------------------------------------------------
    ("soumission : validité comptée un jour trop tard", "conditions_soumission.py",
     "jusqu_au = jour_devis + timedelta(days=declare[\"validite_jours\"])",
     "jusqu_au = jour_devis + timedelta(days=declare[\"validite_jours\"] + 1)"),
    ("soumission : heures de travail arrondies « au pair » (HALF_UP devient HALF_EVEN)", "conditions_soumission.py",
     "quantize(_UN_DIXIEME, rounding=ROUND_HALF_UP)", 'quantize(_UN_DIXIEME, rounding="ROUND_HALF_EVEN")'),
    ("soumission : le délai promet une date", "conditions_soumission.py",
     '"Aucune date de début ni de fin n\'est promise par la présente soumission ; la planification des "',
     '"La date de début sera le lundi suivant l\'acceptation ; la planification des "'),
    ("revue : les seuils du manifeste écrasent ceux du barème cité", "outils.py",
     "seuils = {**(seuils or {}), **seuils_barème}", "seuils = {**seuils_barème, **(seuils or {})}"),
    ("revue : les seuils du barème cité sont ignorés", "outils.py",
     "    if isinstance(bloc_declare, dict) and (seuils is None or isinstance(seuils, dict)):",
     "    if False:"),
    ("revue : la mesure à bornes larges ne déclenche plus le motif", "revue_devis.py",
     '    if entrees.faits.get("mesure_a_bornes_larges") is True:', "    if False:"),
]

# Redondance STRUCTURELLE (l'inertie se démontre) : la garde du registre pur (`_valider_auteur` de bareme_registre et de
# mesure_declaree) applique la MÊME liste de rôles que l'adaptateur (`outils_bareme._auteur_humain`, ROLES_AUTEUR), et
# l'adaptateur la lit dans ces mêmes constantes : retirer le contrôle de rôle de l'adaptateur laisse le refus
# `REJ-BAREME-IDENTITE` / `REJ-MESURE-IDENTITE` au registre, avec le même code. Les deux couches sont voulues
# (défense en profondeur) ; seule la seconde est donc observable.
REDONDANCES_DECLAREES = [
    ("auteur : tout rôle de l'appareil authentifié suffit (le registre pur refuse quand même)", "outils_bareme.py",
     "    if signataire is None or signataire.role not in roles:", "    if signataire is None:",
     "bareme_registre._valider_auteur et mesure_declaree._valider_auteur répètent la liste des rôles"),
]


def executer_tests(env):
    descripteur, nom_rapport = tempfile.mkstemp(prefix="muter_bareme_", suffix=".xml")
    os.close(descripteur)
    rapport = pathlib.Path(nom_rapport)
    try:
        resultat = subprocess.run(
            [sys.executable, "-B", "-m", "pytest", *(str(env.dossier_tests / c) for c in CIBLES), "-q", "-x",
             "-p", "no:cacheprovider", "--color=no", f"--junitxml={rapport}"],
            capture_output=True, text=True, cwd=RACINE,
        )
        sortie = resultat.stdout + resultat.stderr
        motif = re.compile(r"^\s*(?:FAILED|ERROR)\s+(.+?)(?:\s+-\s+.*)?\s*$")
        textuels = {m.group(1) for ligne in sortie.splitlines() if (m := motif.match(ligne))}
        return resultat, _echecs_junit(rapport) | textuels, sortie
    finally:
        rapport.unlink(missing_ok=True)


def main():
    if not SRC.is_file():
        print(f"ABANDON : cible introuvable : {SRC}")
        return 1
    if not MUTATIONS:
        print("ABANDON : MUTATIONS est vide.")
        return 1
    mutations = [m for i, m in enumerate(MUTATIONS) if i % TOTAL == PART - 1]
    env = EnvironnementMutation(RACINE)
    echecs, mordues = [], 0
    originaux = {}
    try:
        env.purger_caches()
        reference, echecs_ref, sortie_ref = executer_tests(env)
        if reference.returncode != 0:
            print("REFERENCE ROUGE : muter une suite non verte ne prouve rien.\n" + sortie_ref[-3000:])
            return 1
        for nom, fichier, avant, apres in mutations:
            cible = env.dossier_source / fichier
            originaux.setdefault(fichier, cible.read_text(encoding="utf-8"))
            original = originaux[fichier]
            if original.count(avant) != 1:
                echecs.append(f"{nom} : ancre x{original.count(avant)}")
                print(f"{nom:<84} -> ANCRE INTROUVABLE/AMBIGUE")
                continue
            mutant = original.replace(avant, apres, 1)
            try:
                compile(mutant, str(cible), "exec")
            except SyntaxError as erreur:
                echecs.append(f"{nom} : ne compile pas ({erreur.msg})")
                print(f"{nom:<84} -> NE COMPILE PAS")
                continue
            cible.write_text(mutant, encoding="utf-8")
            env.purger_caches()
            try:
                resultat, echecs_mutant, sortie = executer_tests(env)
            finally:
                cible.write_text(original, encoding="utf-8")
            nouveaux = echecs_mutant - echecs_ref
            if resultat.returncode == 0:
                echecs.append(f"{nom} : reste VERTE")
                etat = "VERTE (NON DETECTEE)"
            elif not nouveaux:
                echecs.append(f"{nom} : rouge NON ATTRIBUABLE")
                etat = "ROUGE (NON ATTRIBUABLE)"
            else:
                mordues += 1
                etat = "ROUGE : " + sorted(nouveaux)[0].split("::")[-1][:60]
            print(f"{nom:<84} -> {etat}", flush=True)
        for nom, fichier, avant, apres, raison in REDONDANCES_DECLAREES:
            cible = env.dossier_source / fichier
            original = originaux.setdefault(fichier, cible.read_text(encoding="utf-8"))
            cible.write_text(original.replace(avant, apres, 1), encoding="utf-8")
            try:
                resultat, _, _ = executer_tests(env)
            finally:
                cible.write_text(original, encoding="utf-8")
            if resultat.returncode != 0:
                echecs.append(f"[redondance] {nom} : MORD alors qu'elle est déclarée inerte")
            print(f"[déclarée] {nom} -> {'MORD (hypothèse tombée)' if resultat.returncode else 'inerte'} : {raison}")
        restaure = all(
            (env.dossier_source / f).read_text(encoding="utf-8") == t for f, t in originaux.items()
        )
    finally:
        env.nettoyer()
    print(f"\n{mordues}/{len(mutations)} mordent (part {PART}/{TOTAL}) | "
          f"copie jetable restaurée à l'identique : {restaure}")
    return 1 if (echecs or not restaure) else 0


sys.exit(main())
