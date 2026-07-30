import ast
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
    # Ancrage sur le NOM de la section, jamais sur son numéro : une renumérotation
    # rendait cet extracteur vide EN SILENCE, et les contrôles qui en dépendent
    # échouaient alors pour une raison sans rapport avec ce qu'ils vérifient.
    match = re.search(r"^##\s+\d+\.\s+STORIES\s*$", prd_text, re.MULTILINE)
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


def extraire_s00n_depuis_architecture(archi: str,
                                      motif_section: str = r"^##\s+\d+\.\s+CE QUE CHAQUE STORY PROUVE\s*$") -> Set[str]:
    """
    Extrait les identifiants S00N mentionnés dans la section spécifiée de l'architecture.
    Cherche les titres de niveau ### S00N.
    """
    match = re.search(motif_section, archi, re.MULTILINE)
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
    sec = re.search(r"^##\s+\d+\.\s+CE QUE CHAQUE STORY PROUVE\s*$", archi, re.MULTILINE)
    if not sec:
        return ["Section « CE QUE CHAQUE STORY PROUVE » absente de l'architecture."]
    parties = [archi[:sec.start()], archi[sec.end():]]
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


def verifier_cles_du_contrat_gele(prd: str, archi: str) -> List[str]:
    """Contrôle 11 : les clés d'EstimationV1 sont IDENTIQUES dans les deux documents.

    Le gate comparait les valeurs des énumérés entre PRD et architecture, mais
    jamais les CLÉS du pacte gelé lui-même. Deux renommages successifs ont
    traversé ce trou (`verdict_blocage` renommé d'un seul côté, `bareme_version`
    ajouté d'un seul côté) : un contrat gelé qui diverge entre ses deux
    descriptions n'est plus gelé.
    """
    cles_prd = _cles_contrat(prd, r"^## 5\. CONTRAT GELÉ.*$")
    cles_arc = _cles_contrat(archi, r"^#+\s*2\.2\s+Contrat de sortie.*$")
    if not cles_prd or not cles_arc:
        return ["Clés du contrat gelé introuvables d'un côté au moins — "
                "un extracteur qui ne trouve rien rend le contrôle vide."]
    if cles_prd != cles_arc:
        return [f"Clés d'EstimationV1 divergentes : PRD {sorted(cles_prd)} vs "
                f"architecture {sorted(cles_arc)} (écart {sorted(cles_prd ^ cles_arc)})."]
    return []


def _cles_contrat(texte: str, motif_section: str) -> set:
    """Clés de premier niveau du bloc YAML du contrat gelé, ou ensemble vide."""
    m = re.search(motif_section, texte, re.MULTILINE)
    if not m:
        return set()
    bloc = re.search(r"```yaml\s*(.*?)\s*```", texte[m.start():], re.DOTALL)
    if not bloc or not bloc.group(1).lstrip().startswith("EstimationV1:"):
        return set()
    cles = set()
    for ligne in bloc.group(1).splitlines():
        m2 = re.match(r"^  ([a-z_]+):", ligne)
        if m2:
            cles.add(m2.group(1))
    return cles


def verifier_contrats_ont_un_proprietaire(archi: str) -> List[str]:
    """Contrôle 12 : tout contrat gelé déclaré en §2 a un module propriétaire en §1.

    LIMITE DÉCLARÉE (objection de revue scellée) : ce contrôle lit une TABLE de
    documentation, pas du code — au stade du cadrage il n'existe aucun code à
    inspecter, le module étant au statut CADRE. Il prouve donc que la
    responsabilité est ASSIGNÉE, jamais qu'elle est honorée. La preuve
    d'exécution appartient aux tests des stories qui livreront ces modules, et
    c'est là qu'elle sera exigée. Le dire ici évite qu'un lecteur prenne cette
    assignation pour une garantie.

    Un contrat gelé sans fichier chargé de son schéma et de sa validation est une
    promesse que personne ne tient — objection de revue scellée sur `BaremeCouts`,
    élevé au rang de contrat d'entrée sans qu'aucun module ne s'en charge.
    """
    erreurs = []
    declares = set(re.findall(r"^#+\s*2\.\d+\s+Contrat[^`]*`([A-Za-z0-9_]+)`", archi, re.MULTILINE))
    if not declares:
        return ["Aucun contrat gelé détecté en section 2 — extracteur vide, contrôle non probant."]
    sec2 = re.search(r"^##\s+\d+\.\s+SCHÉMAS DE DONNÉES\s*$", archi, re.MULTILINE)
    table = archi[:sec2.start()] if sec2 else ""
    if not table.strip():
        return ["Table des modules introuvable avant la section des contrats — "
                "contrôle non probant."]
    for contrat in sorted(declares):
        if contrat not in table:
            erreurs.append(
                f"Contrat gelé '{contrat}' déclaré en section 2 mais cité par aucun "
                f"module de la table des modules : promesse sans propriétaire."
            )
    return erreurs


def verifier_contrat_consomme_existe_vraiment(archi: str) -> List[str]:
    """Contrôle 13 : le contrat consommé est celui que le module PRODUCTEUR émet.

    Le gate ne vérifiait que la cohérence INTERNE des trois documents de M3. Un
    cadrage peut être parfaitement cohérent avec lui-même et décrire une entrée
    qui n'existe pas : c'est arrivé (issue #166). Le `LeadQualifie` décrit portait
    huit clés dont `sha256`, `owner`, `interactions` et `photos` ; le module M2,
    livré et couvert par 533 tests, en émet SEPT, et ne transporte aucune photo.
    Valider le contrat fantôme aurait rejeté tout lead réel, avec des tests au
    vert puisqu'ils auraient fabriqué l'entrée — un chemin inexistant en
    production, propagé aux neuf stories.

    Ce contrôle confronte donc la liste de clés déclarée dans l'architecture de M3
    à la constante `CHAMPS_CONTRAT_GELE` du module M2, lue dans sa SOURCE. Lire
    la source d'un voisin depuis un GATE n'est pas un import inter-modules
    (décision #109) : aucun code de production ne dépend de M2, seule la
    vérification le fait.
    """
    depot = Path(__file__).resolve().parents[4]
    source_m2 = depot / "Modules M" / "M2-revenue-crm" / "src" / "m2_revenue_crm" / "contrats.py"
    if not source_m2.is_file():
        return [f"Source du module producteur introuvable ({source_m2}) — "
                f"contrôle non probant, jamais silencieusement vert."]
    texte_m2 = source_m2.read_text(encoding="utf-8")
    bloc = re.search(r"CHAMPS_CONTRAT_GELE\s*=\s*\((.*?)\)", texte_m2, re.DOTALL)
    if not bloc:
        return ["Constante CHAMPS_CONTRAT_GELE introuvable dans la source de M2 — "
                "extracteur vide, contrôle non probant."]
    cles_m2 = set(re.findall(r'"([a-z_][a-z0-9_]*)"', bloc.group(1)))

    titre = re.search(r"^#### `LeadQualifie`.*$", archi, re.MULTILINE)
    if not titre:
        return ["Section du contrat LeadQualifie introuvable dans l'architecture M3."]
    # Depuis le titre, le PREMIER bloc yaml COMPLET (ouvrant ET fermant) : s'arrêter
    # à la première clôture rencontrée capturerait la fence ouvrante, donc du vide.
    bloc_m3 = re.search(r"```yaml\s*\n(.*?)\n```", archi[titre.end():], re.DOTALL)
    if not bloc_m3:
        return ["Bloc YAML du contrat LeadQualifie introuvable dans l'architecture M3."]
    corps = bloc_m3.group(1)
    if not corps.lstrip().startswith("LeadQualifie:"):
        return [f"Bloc YAML capturé n'est pas LeadQualifie mais « {corps.lstrip().splitlines()[0]} » "
                f"— ancrage erroné, contrôle non probant."]
    # [a-z_][a-z0-9_]* et non [a-z_]+ : le champ fantôme s'appelait « sha256 »,
    # qu'une classe sans chiffres aurait laissé passer (objection de revue).
    cles_m3 = set(re.findall(r"^  ([a-z_][a-z0-9_]*):", corps, re.MULTILINE))

    if not cles_m3:
        return ["Aucune clé extraite du contrat LeadQualifie de M3 — contrôle vide."]
    if cles_m3 != cles_m2:
        return [f"Le contrat LeadQualifie consommé par M3 {sorted(cles_m3)} DIFFÈRE de celui "
                f"que M2 émet réellement {sorted(cles_m2)} — écart {sorted(cles_m3 ^ cles_m2)}. "
                f"Un consommateur qui décrit une entrée que le producteur n'émet pas valide un "
                f"chemin inexistant en production."]

    # Les NOMS de clés identiques ne suffisent pas : un énuméré divergent produirait
    # une sémantique de rejet différente entre voisins, invisible au gate (objection
    # de revue scellée). On confronte donc aussi les valeurs de TYPES_TRAVAUX.
    bloc_types = re.search(r"TYPES_TRAVAUX\s*=\s*\((.*?)\)", texte_m2, re.DOTALL)
    if not bloc_types:
        return ["Constante TYPES_TRAVAUX introuvable dans la source de M2 — "
                "extracteur vide, contrôle non probant."]
    types_m2 = set(re.findall(r'"([a-z_]+)"', bloc_types.group(1)))
    # L'architecture cite les types dans le bloc du barème (postes) et en prose.
    # L'extracteur précédent ne ramassait RIEN : un contrôle qui ne compare rien
    # passe toujours (mesuré). On confronte donc l'ensemble des types M2 à leur
    # présence effective dans le document.
    # Cibler la DÉCLARATION de l'énuméré, pas une présence quelconque : une simple
    # mention en prose satisfaisait le contrôle et masquait le retrait d'une valeur
    # de la liste (mutation mesurée non détectée).
    titre_enum = re.search(r"^#### `type_travaux`.*$", archi, re.MULTILINE)
    if not titre_enum:
        return ["Déclaration de l'énuméré type_travaux introuvable dans l'architecture M3 — "
                "contrôle non probant."]
    # La déclaration de l'énuméré est la PREMIÈRE ligne non vide après le titre
    # qui porte au moins une valeur entre backticks : une fenêtre fixe englobait
    # la prose voisine et y retrouvait une valeur retirée de la liste (mutation
    # mesurée non détectée). La recherche s'arrête au prochain titre markdown.
    ligne_declaration = None
    for ligne in archi[titre_enum.end():].splitlines():
        if re.match(r"^#", ligne):
            break
        if not ligne.strip():
            continue
        if re.search(r"`[a-z_][a-z0-9_]*`", ligne):
            ligne_declaration = ligne
            break
    if ligne_declaration is None:
        return ["Déclaration de l'énuméré type_travaux introuvable — contrôle non probant."]
    types_m3 = set(re.findall(r"`([a-z_][a-z0-9_]*)`", ligne_declaration))
    if not types_m3:
        return ["Aucune valeur extraite de la déclaration type_travaux — extracteur vide."]
    if types_m3 != types_m2:
        return [f"Énuméré type_travaux divergent : M3 déclare {sorted(types_m3)}, "
                f"M2 émet {sorted(types_m2)} — écart {sorted(types_m3 ^ types_m2)}."]
    return []


def verifier_marqueur_consomme_existe_vraiment(archi: str) -> List[str]:
    """Contrôle 13 bis : le marqueur de readiness consommé est celui que M2 émet.

    L'interface M2 → M3 a deux moitiés : le contrat `LeadQualifie`, confronté
    par le contrôle 13, et le marqueur de readiness qui autorise le passage à
    l'estimation. Ce second contrat consommé doit être confronté à la source du
    producteur avec la même rigueur : une architecture peut décrire un marqueur
    cohérent avec elle-même que M2 n'émettra jamais, et un tel marqueur fantôme
    validerait un chemin inexistant en production — le défaut exact de l'issue
    #166, déplacé sur l'autre moitié de l'interface.

    Ce contrôle lit l'ensemble `cles_attendues` dans la SOURCE de
    `readiness.py` de M2 et le compare aux clés du bloc `MarqueurReadiness:`
    déclaré dans l'architecture de M3. Lire la source d'un voisin depuis un
    GATE n'est pas un import inter-modules (décision #109) : aucun code de
    production ne dépend de M2, seule la vérification le fait. Tout repli est
    fail-closed : source absente ou illisible, extracteur vide, bloc absent ou
    ensembles divergents produisent une erreur explicite, jamais un vert par
    vacuité.
    """
    depot = Path(__file__).resolve().parents[4]
    source_m2 = depot / "Modules M" / "M2-revenue-crm" / "src" / "m2_revenue_crm" / "readiness.py"
    if not source_m2.is_file():
        return [f"Source du module producteur introuvable ({source_m2}) — "
                f"contrôle non probant, jamais silencieusement vert."]
    try:
        texte_m2 = source_m2.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"Source du module producteur illisible ({source_m2}) : {exc} — "
                f"contrôle non probant, jamais silencieusement vert."]
    bloc = re.search(r"cles_attendues\s*=\s*\{([^}]*)\}", texte_m2)
    if not bloc:
        return ["Ensemble cles_attendues introuvable dans la source readiness de M2 — "
                "extracteur vide, contrôle non probant."]
    cles_m2 = set(re.findall(r'"([a-z_][a-z0-9_]*)"', bloc.group(1)))
    if not cles_m2:
        return ["Aucune clé extraite de cles_attendues — contrôle non probant."]

    titre = re.search(r"^#### Marqueur de readiness\b.*$", archi, re.MULTILINE)
    if not titre:
        return ["Section « Marqueur de readiness » introuvable dans l'architecture M3."]
    # Depuis le titre, le PREMIER bloc yaml COMPLET (ouvrant ET fermant), comme
    # pour le contrat LeadQualifie : s'arrêter à la première clôture rencontrée
    # capturerait la fence ouvrante, donc du vide.
    bloc_m3 = re.search(r"```yaml\s*\n(.*?)\n```", archi[titre.end():], re.DOTALL)
    if not bloc_m3:
        return ["Bloc YAML du marqueur MarqueurReadiness introuvable dans l'architecture M3."]
    corps = bloc_m3.group(1).lstrip()
    if not corps.startswith("MarqueurReadiness:"):
        tete = corps.splitlines()[0] if corps else "<bloc vide>"
        return [f"Bloc YAML capturé n'est pas MarqueurReadiness mais « {tete} » "
                f"— ancrage erroné, contrôle non probant."]
    cles_m3 = set(re.findall(r"^  ([a-z_][a-z0-9_]*):", corps, re.MULTILINE))
    if not cles_m3:
        return ["Aucune clé extraite du marqueur MarqueurReadiness de M3 — contrôle vide."]
    if cles_m3 != cles_m2:
        return [f"Le marqueur de readiness consommé par M3 {sorted(cles_m3)} DIFFÈRE de "
                f"celui que M2 émet réellement {sorted(cles_m2)} — attendues par M3 mais "
                f"jamais émises : {sorted(cles_m3 - cles_m2)} ; émises par M2 mais non "
                f"déclarées par M3 : {sorted(cles_m2 - cles_m3)}. Le producteur et le "
                f"consommateur ne parlent pas du même marqueur."]
    return []


def verifier_ca_cites_existent(prd: str) -> List[str]:
    """Contrôle 14 : tout critère cité par une story existe dans la table des CA.

    Retirer le DERNIER critère de la table laisse une séquence 01..N parfaitement
    valide, et les stories continuent de le citer : la story promet alors un
    critère qui n'existe plus (mutation mesurée non détectée par les contrôles
    de séquence et de propriétaire).
    """
    # Ancrage sur le NOM des sections, pas sur leur numéro : une renumérotation
    # cassait l'extraction et le contrôle échouait pour une raison sans rapport
    # avec ce qu'il vérifie (objection de revue scellée).
    debut = re.search(r"^##\s+\d+\.\s+CRITÈRES D'ACCEPTATION\s*$", prd, re.MULTILINE)
    fin = re.search(r"^##\s+\d+\.\s+STORIES\s*$", prd, re.MULTILINE)
    if not debut or not fin or fin.start() <= debut.end():
        return ["Sections « CRITÈRES D'ACCEPTATION » et « STORIES » introuvables ou dans un "
                "ordre inattendu — contrôle non probant."]
    table = prd[debut.end():fin.start()]
    if not table.strip():
        return ["Table des critères vide — contrôle non probant."]
    definis = set(re.findall(r"\| (CA-M3-\d{2}) \|", table))
    if not definis:
        return ["Aucun critère extrait de la table — extracteur vide, contrôle non probant."]
    cites = set(re.findall(r"CA-M3-\d{2}", prd[fin.end():]))
    fantomes = cites - definis
    if fantomes:
        return [f"Critères cités par une story mais ABSENTS de la table : {sorted(fantomes)} — "
                f"une story ne peut pas porter un critère qui n'existe pas."]
    return []


def verifier_ancres_de_docstring(prd: str, archi: str, racine_module: Path) -> List[str]:
    """Contrôle 15 : les promesses de docstring du PRD sont ancrées, puis tenues
    à l'emplacement promis.

    Vérifie trois choses : (1) l'architecture déclare une section ANCRES DE
    DOCSTRING avec une table non vide à TROIS colonnes — critère, ancre exacte
    promise, emplacement — où chaque ligne de critère porte l'un des deux seuls
    emplacements admis, « docstring de module » ou « catalogue de verdicts » ;
    (2) cette table est synchronisée avec le PRD — tout critère dont la ligne de
    table mentionne une docstring y figure sur au moins une ligne, et aucune
    ligne n'existe pour un critère qui ne promet rien ; (3) dès que le paquet
    source existe, chaque ancre est tenue À L'EMPLACEMENT DÉCLARÉ : pour
    « docstring de module », dans une docstring de module lue par
    ast.get_docstring sur l'arbre ast.parse du fichier — une docstring de classe
    ou de fonction ne tient pas une promesse qui vise le module ; pour
    « catalogue de verdicts », dans le source d'un .py du paquet dont le nom
    contient « verdict », et l'absence même d'un tel fichier est une erreur.

    Un même critère peut figurer sur DEUX lignes, une par emplacement : la table
    est une liste de triplets (critère, ancre, emplacement) et chaque ligne est
    vérifiée séparément — une promesse qui engage à la fois la docstring du
    module et le catalogue de verdicts n'est tenue que si les deux moitiés sont
    écrites.

    Quand le paquet ne contient aucun module Python, le module est au statut
    CADRE : l'exigence d'écriture dans le code n'est donc pas encore applicable, et le contrôle retourne conforme sur cette
    étape — seules les erreurs de déclaration et de synchronisation (étapes 1
    et 2) sont alors rapportées.

    Ce sont précisément les étapes 1 et 2 qui empêchent un vert-par-vacuité :
    sans table d'ancres déclarée, non vide et synchronisée avec le PRD, le
    contrôle échoue avant même de regarder le code. Sa suppression ou son vidage
    serait donc détecté immédiatement, et la promesse faite au cadrage ne peut
    pas se perdre silencieusement entre le cadrage et l'implémentation.
    """

    def normaliser(texte: str) -> str:
        """Réduit espaces multiples et retours à la ligne à une seule espace."""
        return re.sub(r"\s+", " ", texte).strip()

    EMPLACEMENTS_ADMIS = ("docstring de module", "catalogue de verdicts")

    erreurs: List[str] = []

    # Étape 1 — la table d'ancres doit exister, être non vide, et chaque ligne
    # de critère doit porter une ancre exacte et un emplacement admis.
    titre = re.search(r"^###\s+ANCRES DE DOCSTRING\s*$", archi, re.MULTILINE)
    if not titre:
        return ["Section ANCRES DE DOCSTRING absente de l'architecture — "
                "contrôle non probant."]
    triplets: List[tuple] = []
    for ligne in archi[titre.end():].splitlines():
        if re.match(r"^#{1,6}\s", ligne):
            break
        if not ligne.lstrip().startswith("|"):
            continue
        cellules = [c.strip() for c in ligne.strip().strip("|").split("|")]
        m_critere = re.search(r"CA-M3-\d{2}", cellules[0])
        if not m_critere:
            # Ligne d'en-tête ou de séparation : elle ne porte aucun critère,
            # il n'y a rien à y vérifier.
            continue
        critere = m_critere.group(0)
        m_ancre = re.search(r"`([^`]+)`", cellules[1]) if len(cellules) > 1 else None
        if not m_ancre:
            erreurs.append(f"Ligne de {critere} sans ancre entre backticks — une "
                           f"promesse déclarée sans ancre exacte est invérifiable.")
            continue
        if len(cellules) < 3 or not cellules[2]:
            erreurs.append(f"Ligne de {critere} sans emplacement déclaré — la table "
                           f"exige trois colonnes : critère, ancre, emplacement.")
            continue
        emplacement = cellules[2].strip("`").strip()
        if emplacement not in EMPLACEMENTS_ADMIS:
            erreurs.append(f"Emplacement « {emplacement} » lu pour {critere} — seules "
                           f"les valeurs {list(EMPLACEMENTS_ADMIS)} sont admises.")
            continue
        triplets.append((critere, m_ancre.group(1), emplacement))
    if not triplets:
        return erreurs + ["Aucune ancre extraite — extracteur vide, contrôle non probant."]

    # Étape 2 — aucune promesse ne doit échapper à la table, et réciproquement.
    prometteurs: Set[str] = set()
    for ligne in prd.splitlines():
        if not ligne.lstrip().startswith("|"):
            continue
        if "docstring" not in ligne.lower():
            continue
        for m in re.finditer(r"CA-M3-\d{2}", ligne):
            prometteurs.add(m.group(0))
    declares: Set[str] = {t[0] for t in triplets}
    manquants = sorted(prometteurs - declares)
    if manquants:
        erreurs.append(f"Critères promettant une docstring mais sans ancre déclarée : "
                       f"{manquants} — une promesse sans ancre est invérifiable.")
    orphelines = sorted(declares - prometteurs)
    if orphelines:
        erreurs.append(f"Ancre déclarée pour {orphelines} qui ne promet aucune docstring — "
                       f"table désynchronisée.")

    # Étape 3 — exigence conditionnelle au paquet source (statut CADRE : src absent).
    # Le paquet existe quand il contient au moins un module Python : un dossier src
    # réduit à un .gitkeep est l'état CADRE, pas un paquet vide à contrôler (mesuré :
    # le contrôle échouait sur l'ancre « absente » d'un paquet qui n'existe pas).
    src = racine_module / "src"
    fichiers = sorted(src.rglob("*.py")) if src.is_dir() else []
    if not fichiers:
        return erreurs
    docs_modules: List[str] = []
    sources_lues: Dict[Path, str] = {}
    for chemin in fichiers:
        try:
            source = chemin.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            erreurs.append(f"Fichier illisible : {chemin} ({exc}) — aucun .py du paquet "
                           f"source ne peut être ignoré silencieusement.")
            continue
        sources_lues[chemin] = source
        try:
            arbre = ast.parse(source, filename=str(chemin))
        except SyntaxError as exc:
            erreurs.append(f"Fichier non parsable : {chemin} ({exc}) — aucun .py du paquet "
                           f"source ne peut être ignoré silencieusement.")
            continue
        doc_module = ast.get_docstring(arbre)
        if doc_module:
            docs_modules.append(doc_module)
    docs_modules_plates = [normaliser(d) for d in docs_modules]
    # L'ancre « catalogue de verdicts » se lit dans le source du fichier verdict :
    # un catalogue de verdicts est une structure de données, pas une docstring,
    # et ast.get_docstring n'y lirait rien.
    fichiers_verdict = [c for c in fichiers if "verdict" in c.name]
    sources_verdict = [normaliser(sources_lues[c]) for c in fichiers_verdict
                       if c in sources_lues]
    requiert_catalogue = sorted({t[0] for t in triplets
                                 if t[2] == "catalogue de verdicts"})
    if requiert_catalogue and not fichiers_verdict:
        erreurs.append(f"Aucun .py dont le nom contient « verdict » dans le paquet, "
                       f"alors que {requiert_catalogue} y promettent une ancre — "
                       f"l'emplacement déclaré n'existe pas.")
    for critere, ancre_brute, emplacement in sorted(triplets):
        ancre_plate = normaliser(ancre_brute)
        if emplacement == "docstring de module":
            if not any(ancre_plate in d for d in docs_modules_plates):
                erreurs.append(f"Ancre de {critere} absente de toute docstring de module "
                               f"du paquet : \"{ancre_brute}\" — la limite promise au "
                               f"cadrage n'est pas écrite dans la docstring du module.")
        elif fichiers_verdict and not any(ancre_plate in s for s in sources_verdict):
            erreurs.append(f"Ancre de {critere} absente du catalogue de verdicts "
                           f"{[c.name for c in fichiers_verdict]} : \"{ancre_brute}\" — "
                           f"la limite promise au cadrage n'est pas écrite à côté du "
                           f"verdict.")
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
    # Garde d'extractibilité : decouper_stories retourne un dict VIDE quand la section
    # est introuvable, et les contrôles qui en dépendent échouent alors en accusant les
    # critères (« CA-M3-08 n'est cité dans aucune story ») au lieu de nommer la cause.
    # Un diagnostic qui désigne la mauvaise pièce coûte plus qu'une absence de contrôle.
    if not stories:
        msg = ("Aucune story extraite du PRD — la section « STORIES » est introuvable ou vide. "
               "Les contrôles de couverture qui suivent seraient non probants.")
        erreurs.append(msg)
        print(f"ECHEC : {msg}")
    else:
        print("OK : La section des stories est extractible.")

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

    errs = verifier_cles_du_contrat_gele(prd, archi)
    if errs:
        erreurs.extend(errs)
        for e in errs:
            print(f"ECHEC : {e}")
    else:
        print("OK : Les clés du contrat gelé sont identiques dans les deux documents.")

    errs = verifier_contrats_ont_un_proprietaire(archi)
    if errs:
        erreurs.extend(errs)
        for e in errs:
            print(f"ECHEC : {e}")
    else:
        print("OK : Chaque contrat gelé a un module propriétaire déclaré.")

    errs = verifier_contrat_consomme_existe_vraiment(archi)
    if errs:
        erreurs.extend(errs)
        for e in errs:
            print(f"ECHEC : {e}")
    else:
        print("OK : Le contrat LeadQualifie consommé correspond à celui que le module "
              "producteur émet.")

    errs = verifier_marqueur_consomme_existe_vraiment(archi)
    if errs:
        erreurs.extend(errs)
        for e in errs:
            print(f"ECHEC : {e}")
    else:
        print("OK : Le marqueur de readiness consommé correspond à celui que le module "
              "producteur émet.")

    errs = verifier_ca_cites_existent(prd)
    if errs:
        erreurs.extend(errs)
        for e in errs:
            print(f"ECHEC : {e}")
    else:
        print("OK : Tout critère cité par une story existe dans la table.")

    errs = verifier_ancres_de_docstring(prd, archi, dossier.parent.parent)
    if errs:
        erreurs.extend(errs)
        for e in errs:
            print(f"ECHEC : {e}")
    else:
        print("OK : Les ancres de docstring sont déclarées, synchronisées avec le "
              "PRD, et tenues dès que le paquet source existe.")

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
