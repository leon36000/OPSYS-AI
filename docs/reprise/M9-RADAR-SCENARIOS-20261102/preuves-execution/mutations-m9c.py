"""Mutations M9-C1/C2 : on casse une garde dans un CLONE, on relance les tests ciblés, on restaure (hash vérifié)."""
import hashlib
import json
import pathlib
import subprocess
import sys
import time

S = pathlib.Path("/tmp/claude-1000/-tmp/67e51219-6449-4d92-98d1-fbc071b4eb81/scratchpad")
W = S / "wt-m9c-mut"
D = W / "departments/m09-strategic-intelligence"
M9 = D / "src/m9_strategic_intelligence"
M4 = W / "departments/m04-field-ops/src/m4_field_ops"
M10 = W / "departments/m10-memoire/src/m10_memoire"
T = "departments/m09-strategic-intelligence/tests/"
UNIT = [T + f for f in ("test_risques_regles.py", "test_reglages_radar.py", "test_escalade_risques.py",
                        "test_scenarios_chiffres.py", "test_risques.py", "test_playbooks.py")]
INTEG = ["tests/test_m9_radar_scenarios_e2e.py", "tests/test_m9_scenarios_chiffres_integre.py"]
PROPRIO = {
    "m04-field-ops": ["departments/m04-field-ops/tests/test_capacite_hypothese.py"],
    "m10-memoire": ["departments/m10-memoire/tests/test_strategique.py"],
    "lecteurs_m9": ["tests/test_lecteurs_m9.py"],
}
R, E, SC = M9 / "risques.py", M9 / "escalade_risques.py", M9 / "scenarios_chiffres.py"
OE = M9 / "outils_escalade.py"
M = [
 # --- mauvaise dimension -------------------------------------------------------------------------------------------
 ("M01 dimension : surcharge de capacité classée cash", R, 'Regle("capacite_surcharge_cedule", "capacite",', 'Regle("capacite_surcharge_cedule", "cash",'),
 ("M02 dimension : afflux de plaintes classé marketing", R, 'Regle("plaintes_afflux", "plaintes",', 'Regle("plaintes_afflux", "marketing",'),
 ("M03 dimension : retard de chantier classé cash", R, 'Regle("chantier_retard_prolonge", "chantiers",', 'Regle("chantier_retard_prolonge", "cash",'),
 ("M04 dimension : dépense marketing classée capacité", R, 'Regle("depense_marketing_plafond", "marketing",', 'Regle("depense_marketing_plafond", "capacite",'),
 ("M05 dimension : déficit de cash libre classé plaintes", R, 'Regle("cash_libre_deficit", "cash",', 'Regle("cash_libre_deficit", "plaintes",'),
 # --- seuil lu au mauvais endroit ----------------------------------------------------------------------------------
 ("M06 seuil : surcharge lit le seuil des plaintes", R, 'seuil = ctx.seuil("capacite_utilisation_seuil_pct")', 'seuil = ctx.seuil("plaintes_seuil_nombre")'),
 ("M07 seuil : règle de surcharge exige le réglage d'un autre domaine", R, '_signal_surcharge,\n          ("capacite_utilisation_seuil_pct",)', '_signal_surcharge,\n          ("depense_marketing_plafond_cad",)'),
 ("M08 seuil : bloc de réglage lu dans la mauvaise section", M9 / "reglages_radar.py", '_BLOC = ("configuration", "radar")', '_BLOC = ("configuration", "autre")'),
 ("M09 seuil : valeur adoptée ignorée (fichier seul)", M9 / "reglages_radar.py", "fusionne = lecture.superposer(donnees, _BLOC, du_fichier)", "fusionne = du_fichier"),
 # --- bornes -------------------------------------------------------------------------------------------------------
 ("M10 borne : plaintes strictement au-dessus", R, "    if declarees < seuil:", "    if declarees <= seuil:"),
 ("M11 borne : capacité strictement au-dessus", R, "if Decimal(planifiees) * 100 < seuil * disponibles:", "if Decimal(planifiees) * 100 <= seuil * disponibles:"),
 ("M12 borne : dépense au plafond comptée", R, "if total is None or total <= plafond:", "if total is None or total < plafond:"),
 ("M13 borne : retard strictement au-dessus", R, "    if Decimal(age) < seuil:", "    if Decimal(age) <= seuil:"),
 ("M14 borne : écart d'estimation strictement au-dessus", R, "or ecart < seuil:", "or ecart <= seuil:"),
 ("M15 borne : cash libre nul compté en déficit", R, "if montant is None or montant >= 0:\n        return None\n    return Signal(\n        \"CRITIQUE\", \"cash_libre\"", "if montant is None or montant > 0:\n        return None\n    return Signal(\n        \"CRITIQUE\", \"cash_libre\""),
 ("M16 borne : plancher de cash libre atteint compté", R, "montant < 0 or montant >= plancher", "montant < 0 or montant > plancher"),
 ("M17 borne : leads au plancher comptés", R, "if haut is None or haut >= plancher or", "if haut is None or haut > plancher or"),
 # --- critique / multiple ------------------------------------------------------------------------------------------
 ("M18 critique : multiple ignoré (plaintes)", R, "critique = ctx.multiple is not None and Decimal(declarees) >= seuil * ctx.multiple", "critique = False"),
 ("M19 critique : comparaison inversée (capacité)", R, "Decimal(planifiees) * 100 >= seuil * ctx.multiple * disponibles", "Decimal(planifiees) * 100 <= seuil * ctx.multiple * disponibles"),
 ("M20 critique : sans multiple déclaré tout est critique (retard)", R, "critique = ctx.multiple is not None and Decimal(age) >= seuil * ctx.multiple", "critique = ctx.multiple is None or Decimal(age) >= seuil * ctx.multiple"),
 ("M21 critique : déficit de cash libre rétrogradé", R, '"CRITIQUE", "cash_libre", ("constat.statut", "constat.cash_libre_cad"),\n        "le cash libre constaté par M5 est négatif', '"ELEVE", "cash_libre", ("constat.statut", "constat.cash_libre_cad"),\n        "le cash libre constaté par M5 est négatif'),
 # --- seuil non déclaré, péremption, levé --------------------------------------------------------------------------
 ("M22 seuil manquant : règle silencieuse (ni évaluée ni dite)", R, 'elif seuil_manquant and not any(n["regle"] == regle.id for n in non_evaluees):\n            non_evaluee(regle, "SEUIL_NON_DECLARE")', 'elif seuil_manquant:\n            pass'),
 ("M23 levé : signal disparu jamais levé", R, "for ancienne in reversed(utilisables[:-1]):", "for ancienne in reversed([]):"),
 ("M24 péremption : âge déclaré ignoré", R, 'perime_apres_jours, origine_peremption = int(declares["donnees_perimees_jours"]), "reglage"', "pass"),
 ("M25 péremption : périmé reste actif", R, '"A_RECONFIRMER" if perime else "ACTIF"', '"ACTIF"'),
 ("M26 lecture partielle utilisée", R, '                and c["complete"]\n', ""),
 ("M27 groupe : argument de référence conservé", R, "return cs.empreinte({cle: valeur for cle, valeur in arguments.items() if cle != lecture.reference})", "return capture[\"arguments_sha256\"]"),
 ("M28 SLA : règle non évaluée comptée comme violation", R, 'if ligne.get("etat") == "non_evaluee" or type(violations)', "if type(violations)"),
 ("M29 SLA : zéro violation signalé", R, "type(violations) is not int or violations <= 0:", "type(violations) is not int or violations < 0:"),
 ("M30 plainte sensible : catégorie sécurité oubliée", R, '_CATEGORIES_SENSIBLES = frozenset({"avocat", "securite"})', '_CATEGORIES_SENSIBLES = frozenset({"avocat"})'),
 # --- escalade -----------------------------------------------------------------------------------------------------
 ("M31 escalade : un risque élevé est escaladé", E, 'r["statut"] == "ACTIF" and r["gravite"] == "CRITIQUE"', 'r["statut"] == "ACTIF" and r["gravite"] in ("CRITIQUE", "ELEVE")'),
 ("M32 escalade : un risque levé est escaladé", E, 'r["statut"] == "ACTIF" and r["gravite"] == "CRITIQUE"', 'r["gravite"] == "CRITIQUE"'),
 ("M33 escalade : avis non dédoublonné", E, 'if any(m["avis_id"] == ids["avis_id"] for m in chaine):\n        return None', "if False:\n        return None"),
 ("M34 escalade : avis marqué externe", E, '"externe": False,\n            "origine_etablie": False,', '"externe": True,\n            "origine_etablie": False,'),
 ("M35 escalade : cause prétendue établie", E, '"origine_etablie": False,', '"origine_etablie": True,'),
 ("M36 escalade : tâche toujours doublée", OE, "tache_id = tache_ouverte(plans_chaine, ids[\"suivi_ref\"])", "tache_id = None"),
 ("M37 escalade : mémoire jamais publiée", OE, "            memoire = publier(maillon)\n", "            memoire = {\"evenement_id\": None, \"nouveau\": False}\n"),
 ("M38 escalade : tâche sans porteur direction", E, '"porteur": "direction (rôle admin)",', '"porteur": "",'),
 ("M39 escalade : genre de mémoire hors catalogue", E, 'GENRE_MEMOIRE = "risque"', 'GENRE_MEMOIRE = "decision"'),
 # --- scénarios ----------------------------------------------------------------------------------------------------
 ("M40 scénario : probabilité de retard complémentée", SC, 'return format((Decimal(pct) / Decimal(100)).normalize(), "f")', 'return format(((Decimal(100) - Decimal(pct)) / Decimal(100)).normalize(), "f")'),
 ("M41 scénario : hausse de coût appliquée en baisse", SC, "(Decimal(1) + signe * Decimal(pct) / Decimal(100))", "(Decimal(1) - signe * Decimal(pct) / Decimal(100))"),
 ("M42 scénario : bornes de baisse non inversées", SC, "    if signe < 0:\n        bas, haut = haut, bas\n", "    if False:\n        bas, haut = haut, bas\n"),
 ("M43 scénario : vérification de M5 présumée identique", SC, '"identique": r.get("identique") is True,\n            "empreinte_recue"', '"identique": True,\n            "empreinte_recue"'),
 ("M44 scénario : chiffré même sans moteur", SC, '"chiffre": impact["statut"] == "CHIFFRE",', '"chiffre": True,'),
 ("M45 scénario : manque effacé quand non chiffré", SC, '"non_chiffre": [] if impact["statut"] == "CHIFFRE" else [{"impact": impact["id"], "manque": impact["manque"]}],', '"non_chiffre": [],'),
 ("M46 scénario : texte d'erreur du propriétaire recopié", SC, 'return valeur if type(valeur) is str and _CODE.fullmatch(valeur) else defaut', 'return valeur if type(valeur) is str else defaut'),
 ("M47 scénario : réponse non ok admise", SC, '    if reponse.get("ok") is not True:\n        return None, _code_sur', '    if False:\n        return None, _code_sur'),
 ("M48 scénario : refus du moteur admis", SC, '    if interne.get("accepte") is False:', '    if False:'),
 ("M49 scénario : M9 recalcule le plus bas du chemin", SC, '"plus_bas_du_chemin": res.get("plus_bas_du_chemin"),', '"plus_bas_du_chemin": str(min(Decimal(str(t["p5"])) for t in trajectoire)),'),
 ("M50 scénario : M4 non calculable présenté chiffré", SC, 'if r["calculable"] is not True:', 'if False:'),
 ("M51 scénario : position du niveau au bas de l'intervalle", SC, "    if n < b:\n        return \"SOUS_L_INTERVALLE\"", "    if n <= b:\n        return \"SOUS_L_INTERVALLE\""),
 # --- port, M4, M10 ------------------------------------------------------------------------------------------------
 ("M52 port : rejeu du reçu M5 retiré de la liste blanche", W / "src/opsys/lecteurs_m9.py", '"m5_simuler_tresorerie_monte_carlo", "m5_comparer_credit_bail_achat", "m5_verifier_recu_calcul"', '"m5_simuler_tresorerie_monte_carlo", "m5_comparer_credit_bail_achat"', "lecteurs_m9"),
 ("M53 port : moteur M4 retiré de la liste blanche", W / "src/opsys/lecteurs_m9.py", '"m04-field-ops": frozenset({"m4_projeter_capacite_hypotheses", "m4_verifier_recu_projection_capacite"})', '"m04-field-ops": frozenset({"m4_verifier_recu_projection_capacite"})', "lecteurs_m9"),
 ("M54 M4 : perte d'absence sans effectif", M4 / "capacite_hypothese.py", 'Decimal(personnes_jours) * Decimal(duree) / Decimal(ligne["effectif_planifie"])', 'Decimal(personnes_jours) * Decimal(duree) / Decimal(1)', "m04-field-ops"),
 ("M55 M4 : surcharge à égalité", M4 / "capacite_hypothese.py", '"statut": "SURCHARGE" if planifiees > projetees else', '"statut": "SURCHARGE" if planifiees >= projetees else', "m04-field-ops"),
 ("M56 M4 : hausse de demande en baisse", M4 / "capacite_hypothese.py", "(Decimal(100) + hausse) / Decimal(100)", "(Decimal(100) - hausse) / Decimal(100)", "m04-field-ops"),
 ("M57 M4 : durée de jour-personne manquante ignorée", M4 / "capacite_hypothese.py", "            if duree is None:\n                manque.append(MANQUE_DUREE)", "            if False:\n                manque.append(MANQUE_DUREE)", "m04-field-ops"),
 ("M58 M10 : genre risque hors des genres admis", M10 / "strategique.py", '_GENRES = frozenset({"decision", "resultat_observe", "lecon", "risque"})', '_GENRES = frozenset({"decision", "resultat_observe", "lecon"})', "m10-memoire"),
 ("M59 M10 : statut quelconque admis pour un risque", M10 / "strategique.py", '"risque": {"signale_par_le_radar"},', '"risque": {"signale_par_le_radar", "validee_par_la_direction"},', "m10-memoire"),
]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def lancer(tests, timeout=1200):
    r = subprocess.run([str(S / "m9c-run.sh"), str(W), *tests, "-x", "-q"], capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout + r.stderr)[-400:]


cible = sys.argv[1:]
resultats = []
for entree in M:
    nom, fichier, ancien, nouveau = entree[:4]
    proprio = entree[4] if len(entree) > 4 else None
    if cible and not any(nom.startswith(c) for c in cible):
        continue
    sauve = fichier.read_text()
    h0 = sha(fichier)
    if sauve.count(ancien) != 1:
        resultats.append((nom, "MOTIF-INTROUVABLE", sauve.count(ancien)))
        print(resultats[-1], flush=True)
        continue
    fichier.write_text(sauve.replace(ancien, nouveau))
    try:
        t0 = time.time()
        etapes = [("unit", UNIT), ("integ", INTEG)] + ([("proprio", PROPRIO[proprio])] if proprio else [])
        etat = "SURVIT"
        for etiquette, tests in etapes:
            code, sortie = lancer(tests)
            if code != 0:
                etat = f"TUE({etiquette})"
                break
        resultats.append((nom, etat, round(time.time() - t0, 1)))
    finally:
        fichier.write_text(sauve)
        assert sha(fichier) == h0, f"restauration non conforme : {fichier}"
    print(resultats[-1], flush=True)
json.dump(resultats, open(S / ("mutations-m9c-resultats-partiel-%d.json" % int(time.time()) if cible else "mutations-m9c-resultats.json"), "w"), ensure_ascii=False, indent=1)
