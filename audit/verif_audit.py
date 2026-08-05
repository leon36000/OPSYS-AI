#!/usr/bin/env python3
"""Gate de clôture de l'audit — une commande, pas une intention.

Ce que la complétude signifie ici, et qu'il faut dire avant de la mesurer : elle ne prouve
PAS qu'il n'existe aucun défaut dans le dépôt. Elle prouve que, pour chaque constat déposé,
un témoin rejouable sort en code non nul, et que chaque zone déclarée propre porte la preuve
qu'un défaut y aurait été vu.

Sept contrôles. Le gate sort en code non nul si un seul échoue.
"""
import hashlib
import json
import pathlib
import subprocess
import sys

RACINE = pathlib.Path(__file__).resolve().parent.parent
AUDIT = RACINE / "audit"
sys.path.insert(0, str(AUDIT))

from contrats import valider_constat  # noqa: E402
from rubrique import calculer_severite  # noqa: E402


def _constats() -> list[tuple[pathlib.Path, dict]]:
    return [
        (c, json.loads(c.read_text(encoding="utf-8")))
        for c in sorted((AUDIT / "constats").glob("AUD-*.json"))
    ]


def check_constats_valides() -> list[str]:
    """Chaque constat passe le contrat gelé — sinon il n'est pas un constat."""
    ecarts = []
    for chemin, constat in _constats():
        valide, rejet = valider_constat(constat)
        if not valide:
            ecarts.append(f"{chemin.name} rejeté par le contrat : {rejet}")
    return ecarts


def check_severites_recalculees() -> list[str]:
    """Aucune sévérité n'est écrite à la main : elle est recalculée et confrontée."""
    ecarts = []
    for chemin, constat in _constats():
        recalculee, _ = calculer_severite(constat["entrees_rubrique"])
        if recalculee != constat.get("severite"):
            ecarts.append(
                f"{chemin.name} : sévérité {constat.get('severite')!r} ≠ "
                f"recalculée {recalculee!r}"
            )
    return ecarts


def check_temoins_rouges() -> list[str]:
    """Un constat dont le témoin ne rougit plus est périmé, pas confirmé."""
    ecarts = []
    for chemin, constat in _constats():
        temoin = RACINE / constat["temoin"]
        if not temoin.exists():
            ecarts.append(f"{chemin.name} : témoin {constat['temoin']} introuvable")
            continue
        resultat = subprocess.run(
            [sys.executable, str(temoin)], cwd=RACINE,
            capture_output=True, text=True, timeout=300,
        )
        if resultat.returncode != constat["temoin_rc"]:
            ecarts.append(
                f"{chemin.name} : témoin rc={resultat.returncode}, "
                f"attendu {constat['temoin_rc']}"
            )
    return ecarts


def check_zones_propres_prouvees() -> list[str]:
    """Une zone sans constat ne vaut que si elle prouve qu'elle aurait vu."""
    ecarts = []
    for mutation in sorted((AUDIT / "temoins").glob("CLEAN-*/mutation.py")):
        resultat = subprocess.run(
            [sys.executable, str(mutation)], cwd=RACINE,
            capture_output=True, text=True, timeout=600,
        )
        if resultat.returncode != 0:
            ecarts.append(
                f"{mutation.parent.name} : la cellule n'est pas prouvée "
                f"(rc={resultat.returncode})"
            )
    return ecarts


def check_sondes_mordent() -> list[str]:
    """La batterie de mutation des sondes doit être complète."""
    batterie = AUDIT / "mutation_audit.py"
    if not batterie.exists():
        return ["audit/mutation_audit.py introuvable"]
    resultat = subprocess.run(
        [sys.executable, str(batterie)], cwd=RACINE,
        capture_output=True, text=True, timeout=900,
    )
    if resultat.returncode != 0:
        return [f"batterie des sondes incomplète (rc={resultat.returncode})"]
    return []


def check_hypotheses_closes() -> list[str]:
    """Chaque hypothèse adverse est convertie ou réfutée — jamais laissée ouverte."""
    chemin = AUDIT / "hypotheses_adverses.json"
    if not chemin.exists():
        return ["audit/hypotheses_adverses.json introuvable"]
    donnees = json.loads(chemin.read_text(encoding="utf-8"))
    ouvertes = [h["id"] for h in donnees.get("hypotheses", []) if h.get("etat") == "OUVERTE"]
    if ouvertes:
        return [f"{len(ouvertes)} hypothèse(s) encore OUVERTE(s) : {', '.join(ouvertes)}"]
    return []


def check_rapport_genere() -> list[str]:
    """Le rapport doit être régénérable à l'identique : sinon il a été édité à la main."""
    rapport = AUDIT / "RAPPORT.md"
    if not rapport.exists():
        return ["audit/RAPPORT.md introuvable"]
    avant = rapport.read_text(encoding="utf-8")
    resultat = subprocess.run(
        [sys.executable, str(AUDIT / "rapport.py")], cwd=RACINE,
        capture_output=True, text=True, timeout=600,
    )
    if resultat.returncode != 0:
        return [f"le générateur de rapport échoue (rc={resultat.returncode})"]
    if rapport.read_text(encoding="utf-8") != avant:
        return ["RAPPORT.md diffère de sa régénération — il a été édité à la main"]
    return []


def check_rapport_fidele() -> list[str]:
    """Le rapport est régénérable — mais dit-il ce que les constats disent ?

    Un relecteur a relevé que « généré, non édité » ne prouve que la reproductibilité :
    un générateur qui omettrait un constat, ou en altérerait le titre, produirait un
    rapport parfaitement régénérable et pourtant infidèle. On confronte donc le contenu
    du rapport aux constats, un par un.
    """
    rapport = AUDIT / "RAPPORT.md"
    if not rapport.exists():
        return ["audit/RAPPORT.md introuvable"]
    texte = rapport.read_text(encoding="utf-8")
    ecarts = []
    for chemin, constat in _constats():
        if constat["id"] not in texte:
            ecarts.append(f"{constat['id']} absent du rapport")
            continue
        if constat["titre"] not in texte:
            ecarts.append(f"{constat['id']} : titre absent ou altéré dans le rapport")
        if constat["severite"] not in texte.split(constat["id"], 1)[1][:400]:
            ecarts.append(f"{constat['id']} : sévérité absente au voisinage de son entrée")
    return ecarts


def check_temoins_mordent() -> list[str]:
    """Un témoin qui sort au bon code sans rien exercer serait tautologique.

    Objection d'un relecteur : « rien n'empêche un témoin de faire exit 1 avant tout
    test ». On exige donc qu'il PRODUISE une sortie substantielle et qu'il NOMME le
    constat qu'il porte — un script muet qui rend le bon code ne prouve rien.
    """
    ecarts = []
    for chemin, constat in _constats():
        temoin = RACINE / constat["temoin"]
        if not temoin.exists():
            continue
        resultat = subprocess.run(
            [sys.executable, str(temoin)], cwd=RACINE,
            capture_output=True, text=True, timeout=300,
        )
        sortie = resultat.stdout + resultat.stderr
        if len(sortie.strip()) < 200:
            ecarts.append(
                f"{constat['id']} : témoin quasi muet ({len(sortie.strip())} caractères) "
                "— il rend le bon code sans montrer ce qu'il mesure"
            )
        if constat["id"] not in sortie:
            ecarts.append(f"{constat['id']} : le témoin ne nomme pas le constat qu'il porte")
    return ecarts


def check_perimetre_scelle() -> list[str]:
    """Le verdict est-il ancré à un état du dépôt, ou flotterait-il sur n'importe lequel ?

    Objection unanime des trois relecteurs de clôture : « rejouer le pipeline sur un dépôt
    modifié donnerait le même verdict vert ». Elle est fondée — le manifeste gelé existait
    mais rien ne le confrontait à la réalité.

    Le contrôle confronte chaque empreinte du manifeste au fichier correspondant. Il sert
    deux choses à la fois :
      - il ancre le verdict à un état précis, si bien que « TOUT VERT » cesse d'être vrai
        sur n'importe quel arbre ;
      - il PROUVE que l'audit n'a rien modifié du produit — CA-AUD-09 — au lieu de le
        déclarer.

    Un fichier disparu est signalé comme tel, jamais ignoré : c'est le mode de défaillance
    exact que le constat AUD-A1-001 reproche à l'instrument audité.
    """
    manifeste = AUDIT / "MANIFESTE.sha256"
    if not manifeste.exists():
        return ["audit/MANIFESTE.sha256 introuvable — le périmètre n'est pas gelé"]

    ecarts, verifies = [], 0
    for ligne in manifeste.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if not ligne:
            continue
        empreinte, _, relatif = ligne.partition("  ")
        if not relatif:
            ecarts.append(f"ligne de manifeste illisible : {ligne[:60]}")
            continue
        chemin = RACINE / relatif
        if not chemin.exists():
            ecarts.append(f"{relatif} : présent au manifeste, ABSENT du disque")
            continue
        reelle = hashlib.sha256(chemin.read_bytes()).hexdigest()
        if reelle != empreinte:
            ecarts.append(f"{relatif} : empreinte {reelle[:12]}… ≠ manifeste {empreinte[:12]}…")
        verifies += 1

    if not verifies:
        return ["le manifeste ne contient aucune entrée vérifiable"]

    # Le sens inverse, réclamé par un relecteur : itérer sur le manifeste ne voit que
    # les fichiers DISPARUS ou ALTÉRÉS. Un arbre modifié par AJOUT seul produirait
    # encore un verdict vert. On parcourt donc aussi le disque.
    #
    # Les ajouts de l'audit lui-même sont attendus — c'est son travail. CA-AUD-09 nomme
    # les chemins où il a le droit d'écrire ; tout ajout HORS de ces chemins est un écart,
    # et signifierait que l'audit a touché au produit.
    CHEMINS_AUTORISES = ("audit/", "reviews/", "registries/", "stories/REM-")
    connus = set()
    for ligne in manifeste.read_text(encoding="utf-8").splitlines():
        _, _, relatif = ligne.strip().partition("  ")
        if relatif:
            connus.add(relatif)

    sortie = subprocess.run(
        ["git", "ls-files", "-z"], cwd=RACINE, capture_output=True, text=True, check=True
    ).stdout
    for relatif in (c for c in sortie.split("\0") if c):
        if relatif in connus:
            continue
        if any(relatif.startswith(prefixe) for prefixe in CHEMINS_AUTORISES):
            continue
        ecarts.append(
            f"{relatif} : AJOUTÉ au dépôt hors du périmètre gelé et hors des chemins "
            "que CA-AUD-09 autorise à l'audit"
        )

    if not ecarts:
        print(f"     ({verifies} fichiers du périmètre gelé confrontés à leur empreinte,")
        print("      et aucun ajout hors des chemins autorisés)")
    return ecarts


CONTROLES = [
    ("Le périmètre gelé est intact — le verdict est ancré", check_perimetre_scelle),
    ("Chaque constat passe le contrat gelé", check_constats_valides),
    ("Aucune sévérité écrite à la main", check_severites_recalculees),
    ("Chaque témoin rejoué sort au code attendu", check_temoins_rouges),
    ("Chaque zone déclarée propre est prouvée mordante", check_zones_propres_prouvees),
    ("La batterie des sondes est complète", check_sondes_mordent),
    ("Aucune hypothèse adverse laissée ouverte", check_hypotheses_closes),
    ("RAPPORT.md est généré, non édité", check_rapport_genere),
    ("RAPPORT.md est FIDÈLE aux constats", check_rapport_fidele),
    ("Chaque témoin montre ce qu'il mesure", check_temoins_mordent),
]


def main() -> int:
    total = 0
    for libelle, controle in CONTROLES:
        ecarts = controle()
        if ecarts:
            total += len(ecarts)
            for ecart in ecarts:
                print(f"ÉCART ({libelle}): {ecart}")
        else:
            print(f"OK: {libelle}")
    print()
    if total:
        print(f"VERDICT : {total} ÉCART(S) — l'audit ne peut pas être clos")
        return 1
    print("VERDICT : TOUT VERT — l'audit est clos")
    print()
    print("Ce que ce verdict signifie : pour chaque constat déposé, un témoin rejouable")
    print("sort au code attendu, et chaque zone déclarée propre porte la preuve qu'un")
    print("défaut y aurait été vu. Ce qu'il ne signifie PAS : qu'il n'existe aucun autre")
    print("défaut dans le dépôt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
