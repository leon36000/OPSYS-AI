import re
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple


def lire_fichier(chemin: Path) -> str:
    """Lit un fichier texte en UTF-8 et retourne son contenu."""
    return chemin.read_text(encoding="utf-8")


def extraire_enum_val(texte: str, titre: str) -> List[str]:
    """
    Extrait les valeurs d'un énuméré depuis un tableau Markdown situé sous un titre donné.
    Cherche la ligne contenant le titre (ex: "### 4.1 NiveauConfiance"), puis lit les lignes
    de tableau jusqu'à une ligne vide ou fin de section. Retourne la liste des valeurs des
    premières colonnes encadrées de backticks.
    """
    pattern_titre = re.compile(rf"^###\s+\d+\.\d+\s+{re.escape(titre)}\s*$", re.MULTILINE)
    match = pattern_titre.search(texte)
    if not match:
        return []
    pos = match.end()
    valeurs = []
    lignes = texte[pos:].splitlines()
    dans_tableau = False
    for ligne in lignes:
        ligne = ligne.strip()
        if not ligne:
            if dans_tableau:
                break
            continue
        if ligne.startswith("|"):
            dans_tableau = True
            # Ignorer la ligne de séparation (ex: |---|---|)
            if re.match(r"^\|[\s\-]+\|", ligne):
                continue
            cellules = ligne.split("|")
            if len(cellules) >= 2:
                premiere = cellules[1].strip()
                # Extraire le texte entre backticks
                backtick = re.search(r"`([^`]+)`", premiere)
                if backtick:
                    valeurs.append(backtick.group(1))
        else:
            if dans_tableau:
                break
    return valeurs


def extraire_enum_architecture(texte: str, nom_enum: str) -> List[str]:
    """Extrait les valeurs d'un énuméré tel que l'ARCHITECTURE le déclare.

    Le PRD présente ses énumérés en tableau Markdown ; l'architecture les déclare
    dans le contrat gelé sous la forme `# Enum <Nom> : A | B | C`, la déclaration
    pouvant se poursuivre sur les lignes de commentaire suivantes. Appliquer
    l'extracteur du PRD à l'architecture rendait une liste VIDE, donc une
    divergence apparente sur la totalité des valeurs — un contrôle qui échoue
    pour la mauvaise raison est aussi trompeur qu'un contrôle qui passe pour la
    mauvaise raison (mesuré).
    """
    lignes = texte.splitlines()
    depart = None
    for i, ligne in enumerate(lignes):
        if re.search(rf"#\s*Enum\s+{re.escape(nom_enum)}\s*:", ligne):
            depart = i
            break
    if depart is None:
        return []
    brut = lignes[depart].split(":", 1)[1]
    j = depart + 1
    while j < len(lignes):
        suite = lignes[j].strip()
        if not suite.startswith("#"):
            break
        corps = suite.lstrip("#").strip()
        if not corps or ":" in corps:
            break
        brut += " " + corps
        j += 1
    valeurs = [v.strip() for v in brut.split("|")]
    return [v for v in valeurs if re.fullmatch(r"[A-Z][A-Z0-9_]+", v)]


def verifier_presence(dossier: Path) -> List[str]:
    """Contrôle 1 : les trois fichiers existent et font plus de 1000 caractères."""
    erreurs = []
    for nom in ["01-BRIEF-ANALYSTE.md", "02-PRD-PM.md", "03-ARCHITECTURE.md"]:
        chemin = dossier / nom
        if not chemin.is_file():
            erreurs.append(f"Fichier manquant : {nom}")
        elif chemin.stat().st_size <= 1000:
            erreurs.append(f"Fichier trop court : {nom} (taille <= 1000)")
    return erreurs


def verifier_enumeres(prd: str, archi: str) -> List[str]:
    """Contrôle 2 : les valeurs d'énuméré du PRD et de l'architecture sont identiques."""
    erreurs = []
    for enum_nom in ("NiveauConfiance", "VerdictEstimation"):
        valeurs_prd = extraire_enum_val(prd, enum_nom)
        valeurs_archi = extraire_enum_architecture(archi, enum_nom)
        set_prd = set(valeurs_prd)
        set_archi = set(valeurs_archi)
        if set_prd != set_archi:
            diff = sorted(set_prd.symmetric_difference(set_archi))
            erreurs.append(
                f"Énuméré {enum_nom} : divergence. "
                f"Différence symétrique : {diff}"
            )
    return erreurs


def verifier_echappatoire(prd: str) -> List[str]:
    """Contrôle 3 : chaque énuméré contient une valeur avec 'INDETERMINE'."""
    erreurs = []
    for enum_nom in ("NiveauConfiance", "VerdictEstimation"):
        valeurs = extraire_enum_val(prd, enum_nom)
        if not any("INDETERMINE" in v for v in valeurs):
            erreurs.append(
                f"Énuméré {enum_nom} sans échappatoire INDETERMINE "
                "(D-032 : un énuméré sans issue force la fabrication)"
            )
    return erreurs


def verifier_ca_sequence(prd: str) -> List[str]:
    """Contrôle 4 : les identifiants CA-M3-NN forment une séquence continue, 18 à 22 éléments."""
    erreurs = []
    ids = re.findall(r"CA-M3-(\d{2})", prd)
    numeros = sorted(set(int(num) for num in ids))
    if not numeros:
        erreurs.append("Aucun identifiant CA-M3 trouvé dans le PRD.")
        return erreurs
    if numeros[0] != 1 or len(numeros) != max(numeros):
        erreurs.append(
            f"CA-M3 non continus : trouvé {len(numeros)} identifiants, "
            f"de {numeros[0]} à {max(numeros)}, séquence : {numeros}"
        )
    if not (18 <= len(numeros) <= 22):
        erreurs.append(
            f"Nombre de CA hors bornes : {len(numeros)} (attendu entre 18 et 22)"
        )
    return erreurs


def decouper_stories(prd_text: str) -> Dict[str, str]:
    """
    Retourne un dict {story_id: contenu} pour toutes les sous-sections de la section
    ## 7. STORIES du PRD. Les story_id sont extraits des titres ### S00N.
    """
    # Trouver la section STORIES
    match = re.search(r"^## 7\. STORIES\s*$", prd_text, re.MULTILINE)
    if not match:
        return {}
    section = prd_text[match.start():]
    # Découper par les titres ### S00N
    parties = re.split(r"^(###\s+(S\d{3})\b.*)$", section, flags=re.MULTILINE)
    # parties alterne : texte avant premier titre, titre, contenu, titre, contenu...
    result = {}
    for i in range(1, len(parties), 3):
        titre = parties[i]
        ident = parties[i+1]
        contenu = parties[i+2] if (i+2) < len(parties) else ""
        result[ident] = (titre + contenu)
    return result


def verifier_proprietaire_unique(stories: Dict[str, str], prd: str) -> List[str]:
    """Contrôle 5 : chaque CA-M3 est cité dans exactement une story."""
    erreurs = []
    # Récupérer tous les CA depuis l'ensemble du PRD (pour avoir la liste exhaustive)
    tous_ca = set(re.findall(r"CA-M3-\d{2}", prd))
    ca_occurrences = {ca: [] for ca in tous_ca}

    # Parcourir chaque story
    for story_id, contenu in stories.items():
        ca_dans_story = set(re.findall(r"CA-M3-\d{2}", contenu))
        for ca in ca_dans_story:
            if ca not in ca_occurrences:
                ca_occurrences[ca] = []
            ca_occurrences[ca].append(story_id)

    for ca, owners in ca_occurrences.items():
        if len(owners) == 0:
            erreurs.append(f"{ca} n'est cité dans aucune story.")
        elif len(owners) > 1:
            erreurs.append(f"{ca} cité dans plusieurs stories : {', '.join(sorted(owners))}")
    return erreurs


def extraire_s00n_depuis_architecture(archi: str, section_titre: str = "## 5. CE QUE CHAQUE STORY PROUVE") -> Set[str]:
    """
    Extrait les identifiants S00N mentionnés dans la section spécifiée de l'architecture.
    Cherche les titres de niveau ### S00N.
    """
    match = re.search(re.escape(section_titre), archi)
    if not match:
        return set()
    contenu = archi[match.start():]
    # L'architecture cite les stories en GRAS dans un tableau (| **S001** — ... |),
    # pas en titre de section : chercher « ### S00N » rendait un ensemble VIDE.
    ids = set(re.findall(r"\*\*(S\d{3})\*\*", contenu))
    ids |= set(re.findall(r"^###\s+(S\d{3})\b", contenu, re.MULTILINE))
    return ids


def verifier_stories_couvertes(stories_prd: Dict[str, str], archi: str) -> List[str]:
    """Contrôle 6 : les S00N du PRD et de l'architecture sont identiques."""
    erreurs = []
    prd_ids = set(stories_prd.keys())
    archi_ids = extraire_s00n_depuis_architecture(archi)
    if prd_ids != archi_ids:
        manque_prd = archi_ids - prd_ids
        manque_archi = prd_ids - archi_ids
        msg = "Divergence de couverture des stories : "
        if manque_prd:
            msg += f"dans l'architecture mais pas dans le PRD : {sorted(manque_prd)}. "
        if manque_archi:
            msg += f"dans le PRD mais pas dans l'architecture : {sorted(manque_archi)}. "
        erreurs.append(msg.strip())
    return erreurs


# Frontières RATIFIÉES : les dates appartiennent à M4, la finance à M5.
# Liste ÉLARGIE après revue scellée : la version initiale laissait passer
# montant, creneau, duree et engagement — le contrôle affichait « OK » sur un
# contrat qui violait la frontière.
MOTS_INTERDITS = {
    "date", "echeance", "creneau", "duree", "planning", "calendrier",
    "montant", "facture", "paiement", "tva", "acompte", "encaissement",
    "solde", "engagement", "remise", "escompte",
}


def extraire_cles_yaml(bloc_yaml: str) -> Set[str]:
    """
    Extrait tous les noms de clés d'un bloc YAML (commentaires ignorés).
    Retourne un ensemble de noms simples (sans préfixe d'indentation).
    """
    cles = set()
    for ligne in bloc_yaml.splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#"):
            continue
        if ":" in ligne:
            cle = ligne.split(":")[0].strip()
            if cle and re.match(r"^[\w_]+$", cle):
                cles.add(cle)
    return cles


def verifier_contrat_sans_date_finance(prd: str, archi: str = "") -> List[str]:
    """Contrôle 7 : aucun champ interdit dans le contrat gelé, des DEUX côtés.

    Le contrat est décrit dans le PRD ET dans l'architecture : ne contrôler que
    le PRD laissait passer un champ interdit ajouté du seul côté architecture
    (objection de revue scellée). Seuls les NOMS DE CHAMPS des blocs YAML sont
    inspectés — le mot « date » apparaît légitimement en prose.
    """
    erreurs = []
    erreurs.extend(_champs_interdits_du_bloc(prd, r"^## 5\. CONTRAT GELÉ.*$", "PRD"))
    if archi:
        # Ancrage sur le TITRE DE SECTION du contrat de SORTIE. Un ancrage large
        # (« toute ligne citant EstimationV1 ») attrapait une ligne de tableau
        # bien plus haut, et le premier bloc YAML qui suivait était celui du
        # contrat d'ENTRÉE : le contrôle validait le mauvais bloc et passait au
        # vert quel que soit le contenu réel (mutation mesurée non détectée).
        erreurs.extend(_champs_interdits_du_bloc(
            archi, r"^#+\s*2\.2\s+Contrat de sortie.*$", "ARCHITECTURE"))
    return erreurs


def _champs_interdits_du_bloc(texte: str, motif_section: str, etiquette: str) -> List[str]:
    """Extrait les clés du premier bloc YAML sous la section et les confronte aux interdits."""
    erreurs = []
    match_section = re.search(motif_section, texte, re.MULTILINE)
    if not match_section:
        erreurs.append(f"Section du contrat gelé absente ({etiquette}).")
        return erreurs
    section = texte[match_section.start():]
    # Extraire le bloc de code yaml
    bloc_match = re.search(r"```yaml\s*(.*?)\s*```", section, re.DOTALL)
    if not bloc_match:
        erreurs.append(f"Bloc YAML du contrat gelé introuvable ({etiquette}) — "
                       f"un extracteur qui ne trouve rien rend le contrôle vide.")
        return erreurs
    bloc = bloc_match.group(1)
    # Un extracteur doit prouver qu'il a attrapé le BON bloc : sans ce contrôle,
    # pointer par erreur sur un autre contrat rendait le gate vert à tort.
    if not bloc.lstrip().startswith("EstimationV1:"):
        premiere = bloc.lstrip().splitlines()[0] if bloc.strip() else "(vide)"
        erreurs.append(
            f"Bloc YAML capturé ({etiquette}) n'est PAS le contrat EstimationV1 "
            f"mais « {premiere} » — ancrage erroné, contrôle non probant."
        )
        return erreurs
    cles = extraire_cles_yaml(bloc)
    fautives = []
    for cle in cles:
        for mot in MOTS_INTERDITS:
            if mot in cle.lower():
                fautives.append(cle)
                break
    if fautives:
        erreurs.append(
            f"Champ(s) interdit(s) dans le contrat gelé ({etiquette}) : {', '.join(sorted(fautives))}. "
            f"Fragments exclus : {sorted(MOTS_INTERDITS)}"
        )
    return erreurs


def verifier_ca_par_story_coherents(prd: str, archi: str) -> List[str]:
    """Contrôle 9 : pour CHAQUE story, les CA cités par l'architecture sont ceux du PRD.

    Le gate vérifiait que les mêmes stories existent des deux côtés, mais pas que
    chacune y porte les MÊMES critères : après l'ajout de CA-M3-21 au PRD, la
    ligne S005 de l'architecture n'en citait que deux sur trois et rien ne le
    voyait (objection de revue scellée). Deux documents peuvent s'accorder sur la
    LISTE des stories tout en divergeant sur ce que chacune prouve.
    """
    erreurs = []
    stories_prd = decouper_stories(prd)
    parties = archi.split("## 5. CE QUE CHAQUE STORY PROUVE")
    if len(parties) < 2:
        return ["Section '## 5. CE QUE CHAQUE STORY PROUVE' absente de l'architecture."]
    vues = 0
    for ligne in parties[1].splitlines():
        m = re.search(r"\*\*(S\d{3})\*\*", ligne)
        if not m:
            continue
        story = m.group(1)
        ca_prd = set(re.findall(r"CA-M3-\d{2}", stories_prd.get(story, "")))
        if not ca_prd:
            continue
        vues += 1
        ca_archi = set(re.findall(r"CA-M3-\d{2}", ligne))
        if ca_archi != ca_prd:
            erreurs.append(
                f"Story {story} : critères divergents — PRD {sorted(ca_prd)} vs "
                f"architecture {sorted(ca_archi)} (écart {sorted(ca_prd ^ ca_archi)})."
            )
    if vues == 0:
        erreurs.append(
            "Aucune story confrontée : l'extracteur n'a rien trouvé, le contrôle "
            "serait vide — un contrôle qui ne compare rien passe toujours."
        )
    return erreurs


def verifier_numerotation_des_sections(prd: str, archi: str) -> List[str]:
    """Contrôle 10 : aucune sous-section dupliquée, aucune hors de sa section mère.

    Trois dérapages successifs de numérotation pendant les rounds de revue — un
    contrat rangé sous la mauvaise section, puis une collision créée par mon
    propre renumérotage — ont montré qu'un humain relit mal une table des
    matières. Une machine, non : les renvois « décrit en 2.3 » deviennent
    ambigus dès qu'il existe deux 2.3, et le lecteur suit le mauvais.
    """
    erreurs = []
    for etiquette, texte in (("PRD", prd), ("ARCHITECTURE", archi)):
        numeros = re.findall(r"^###\s+(\d+)\.(\d+)", texte, re.MULTILINE)
        vus = {}
        for majeur, mineur in numeros:
            cle = f"{majeur}.{mineur}"
            vus[cle] = vus.get(cle, 0) + 1
        for cle, n in sorted(vus.items()):
            if n > 1:
                erreurs.append(
                    f"{etiquette} : sous-section {cle} définie {n} fois — tout renvoi "
                    f"« voir {cle} » devient ambigu."
                )
        # chaque sous-section doit tomber sous SA section mère
        mere = None
        for ligne in texte.splitlines():
            m2 = re.match(r"^##\s+(\d+)\.", ligne)
            if m2:
                mere = m2.group(1)
                continue
            m3 = re.match(r"^###\s+(\d+)\.(\d+)", ligne)
            if m3 and mere is not None and m3.group(1) != mere:
                erreurs.append(
                    f"{etiquette} : sous-section {m3.group(1)}.{m3.group(2)} placée sous "
                    f"la section {mere} — rangement incohérent."
                )
    return erreurs


def verifier_anti_derive(prd: str) -> List[str]:
    """Contrôle 8 : les DEUX déclarations exigées sont présentes, distinctement.

    L'ancrage initial sur le seul fragment « HORS PÉRIMÈTRE » était satisfait par
    le titre de la section des ajouts du PM : supprimer la section du périmètre
    GATED laissait le contrôle vert (objection de revue scellée). Un contrôle
    satisfait par autre chose que ce qu'il prétend vérifier ne prouve rien.
    """
    erreurs = []
    if "HORS PÉRIMÈTRE" not in prd.upper():
        erreurs.append(
            "Aucune section déclarant les ajouts hors du périmètre de l'analyste : "
            "une extension non déclarée est une dérive."
        )
    if not re.search(r"GATED", prd):
        erreurs.append(
            "Aucune mention du périmètre GATED : ce qui est repoussé hors du mode "
            "ombre doit être nommé, sinon il sera tenté en v1."
        )
    if not re.search(r"(?im)^#+\s*3\.2\b.*GATED", prd):
        erreurs.append(
            "La section dédiée au périmètre GATED (3.2) est absente : la seule "
            "mention du mot dans une phrase ne suffit pas à délimiter le périmètre."
        )
    return erreurs


def main(dossier_str: str = None) -> int:
    if dossier_str is None:
        dossier = Path(__file__).resolve().parent
    else:
        dossier = Path(dossier_str).resolve()
    if not dossier.is_dir():
        print(f"ECHEC : le dossier {dossier} n'existe pas.")
        return 1

    erreurs = []
    # Chargement des fichiers
    try:
        prd = lire_fichier(dossier / "02-PRD-PM.md")
        archi = lire_fichier(dossier / "03-ARCHITECTURE.md")
        # La présence de l'analyste est contrôlée plus bas
        _ = lire_fichier(dossier / "01-BRIEF-ANALYSTE.md")
    except FileNotFoundError as e:
        print(f"ECHEC : fichier manquant — {e}")
        return 1

    # Contrôle 1 : présence
    errs = verifier_presence(dossier)
    if errs:
        erreurs.extend(errs)
        for e in errs:
            print(f"ECHEC : {e}")
        # On peut continuer partiellement mais mieux vaut s'arrêter si fichier absent
        if any("manquant" in e for e in errs):
            print("VERDICT : ECHEC — fichiers manquants.")
            return 1
    else:
        print("OK : Les trois fichiers sont présents et de taille suffisante.")

    # Contrôle 2 : énumérés identiques
    errs = verifier_enumeres(prd, archi)
    if errs:
        erreurs.extend(errs)
        for e in errs:
            print(f"ECHEC : {e}")
    else:
        print("OK : Les valeurs des énumérés PRD/Architecture sont identiques.")

    # Contrôle 3 : échappatoire D-032
    errs = verifier_echappatoire(prd)
    if errs:
        erreurs.extend(errs)
        for e in errs:
            print(f"ECHEC : {e}")
    else:
        print("OK : Chaque énuméré possède une échappatoire INDETERMINE (D-032).")

    # Contrôle 4 : séquence CA-M3
    errs = verifier_ca_sequence(prd)
    if errs:
        erreurs.extend(errs)
        for e in errs:
            print(f"ECHEC : {e}")
    else:
        print("OK : La séquence CA-M3 est continue, sans trou ni doublon, nombre dans [18,22].")

    # Contrôle 5 : propriétaire unique
    stories = decouper_stories(prd)
    errs = verifier_proprietaire_unique(stories, prd)
    if errs:
        erreurs.extend(errs)
        for e in errs:
            print(f"ECHEC : {e}")
    else:
        print("OK : Chaque critère d'acceptation est porté par exactement une story.")

    # Contrôle 6 : stories couvertes (architecture vs PRD)
    errs = verifier_stories_couvertes(stories, archi)
    if errs:
        erreurs.extend(errs)
        for e in errs:
            print(f"ECHEC : {e}")
    else:
        print("OK : Les stories du PRD et de l'architecture sont exactement les mêmes.")

    # Contrôle 7 : contrat sans date ni finance
    errs = verifier_contrat_sans_date_finance(prd, archi)
    if errs:
        erreurs.extend(errs)
        for e in errs:
            print(f"ECHEC : {e}")
    else:
        print("OK : Aucun champ interdit (date/finance) dans le contrat gelé.")

    # Contrôle 8 : anti-dérive
    errs = verifier_ca_par_story_coherents(prd, archi)
    if errs:
        erreurs.extend(errs)
        for e in errs:
            print(f"ECHEC : {e}")
    else:
        print("OK : Chaque story porte les mêmes critères dans le PRD et l'architecture.")

    errs = verifier_numerotation_des_sections(prd, archi)
    if errs:
        erreurs.extend(errs)
        for e in errs:
            print(f"ECHEC : {e}")
    else:
        print("OK : Numérotation des sous-sections cohérente et sans doublon.")

    errs = verifier_anti_derive(prd)
    if errs:
        erreurs.extend(errs)
        for e in errs:
            print(f"ECHEC : {e}")
    else:
        print("OK : Section 'HORS PÉRIMÈTRE' présente (anti-dérive déclarée).")

    n = len(erreurs)
    if n == 0:
        print("VERDICT : TOUT VERT")
        return 0
    else:
        print(f"VERDICT : {n} CONTROLE(S) EN ECHEC")
        return 1


if __name__ == "__main__":
    sys.exit(main())
