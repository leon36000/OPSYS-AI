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

    La confrontation porte aussi sur les TYPES. Tout contrôle de type que M2
    exprime sur une clé du contrat — `type(contrat["CLE"]) is not TYPE` ou
    `isinstance(contrat["CLE"], TYPE)`, lu sur l'arbre ast.parse de sa source et
    jamais par recherche textuelle, qui trouverait le motif dans un commentaire
    ou une docstring — doit correspondre au type déclaré pour cette clé dans le
    bloc YAML `LeadQualifie` de l'architecture. Le type déclaré est le premier
    token après les deux-points de la clé ; un suffixe éventuel (« bool strict »,
    « str non vide ») précise la règle métier sans changer le type de base
    confronté. Seules les clés soumises à un contrôle de type côté M2 sont
    confrontées : une clé sans contrôle chez le producteur est une absence
    d'information, pas une divergence — le gate ne prête à M2 aucune exigence
    qu'il n'exprime pas.

    COUVERTURE RÉELLE, MESURÉE : à ce jour une seule clé du contrat
    (`urgence_declaree`) est soumise côté M2 à un contrôle portant sur une clé
    littérale. Les autres types y sont contrôlés à travers une variable
    intermédiaire (`contact = contrat["contact"]` puis `isinstance(contact, dict)`),
    forme que cet extracteur ne suit pas encore. La confrontation des types porte
    donc sur une clé sur sept, et le message du gate le dit — annoncer une
    couverture plus large que celle qui est tenue est le défaut que ce contrôle
    existe pour empêcher.
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

    # Des noms de clés identiques ne garantissent pas des types identiques : un
    # consommateur qui déclare « bool » là où le producteur impose « str » (ou
    # l'inverse) valide une sémantique d'entrée différente sous des noms alignés,
    # invisible au seul contrôle des clés. Les contrôles de type de M2 sont lus
    # sur l'arbre ast.parse de sa source — jamais par recherche textuelle, qui
    # trouverait le motif dans un commentaire ou une docstring — aux deux formes
    # reconnues : type(contrat["CLE"]) is not TYPE et isinstance(contrat["CLE"], TYPE).
    try:
        arbre_m2 = ast.parse(texte_m2)
    except SyntaxError as exc:
        return [f"Source de M2 non analysable par ast.parse ({exc}) — contrôle non probant."]
    controles_types_m2 = {}
    for noeud in ast.walk(arbre_m2):
        cible = None
        type_impose = None
        if (isinstance(noeud, ast.Compare) and len(noeud.ops) == 1
                and isinstance(noeud.ops[0], ast.IsNot)
                and isinstance(noeud.left, ast.Call)
                and isinstance(noeud.left.func, ast.Name)
                and noeud.left.func.id == "type"
                and len(noeud.left.args) == 1
                and len(noeud.comparators) == 1
                and isinstance(noeud.comparators[0], ast.Name)):
            cible = noeud.left.args[0]
            type_impose = noeud.comparators[0].id
        elif (isinstance(noeud, ast.Call)
                and isinstance(noeud.func, ast.Name)
                and noeud.func.id == "isinstance"
                and len(noeud.args) == 2
                and isinstance(noeud.args[1], ast.Name)):
            cible = noeud.args[0]
            type_impose = noeud.args[1].id
        if cible is None:
            continue
        # Seul un accès contrat["CLE"] à clé littérale qualifie : un contrôle sur
        # la variable contrat elle-même (ex. isinstance(contrat, dict)) ne dit
        # rien sur le type d'une clé et ne doit pas être capté.
        if not (isinstance(cible, ast.Subscript)
                and isinstance(cible.value, ast.Name)
                and cible.value.id == "contrat"):
            continue
        tranche = cible.slice
        if isinstance(tranche, ast.Constant):
            constante = tranche
        else:
            # Python 3.8 enveloppait la tranche dans un nœud Index portant la constante.
            constante = getattr(tranche, "value", None)
        if isinstance(constante, ast.Constant) and isinstance(constante.value, str):
            controles_types_m2[constante.value] = type_impose
    if not controles_types_m2:
        return ["Aucun contrôle de type extrait de la source de M2 (formes attendues : "
                "type(contrat[CLE]) is not TYPE, isinstance(contrat[CLE], TYPE)) — "
                "extracteur vide, contrôle non probant."]

    # Le type déclaré par M3 est le premier token après les deux-points de la clé,
    # à l'indentation du contrat ; un suffixe éventuel (« bool strict », « str non
    # vide ») précise la règle métier sans changer le type de base confronté.
    types_declares_m3 = dict(re.findall(r"^  ([a-z_][a-z0-9_]*):[ \t]*([a-zA-Z_][a-zA-Z0-9_]*)",
                                        corps, re.MULTILINE))
    divergences_types = []
    for cle in sorted(controles_types_m2):
        type_impose_m2 = controles_types_m2[cle]
        type_declare_m3 = types_declares_m3.get(cle)
        if type_declare_m3 is None:
            return [f"La clé « {cle} » est soumise par M2 à un contrôle de type "
                    f"« {type_impose_m2} » mais aucun type n'est extractible de sa ligne "
                    f"dans le bloc LeadQualifie de l'architecture — contrôle non probant."]
        if type_declare_m3 != type_impose_m2:
            divergences_types.append(
                f"Type divergent pour la clé « {cle} » : l'architecture M3 déclare "
                f"« {type_declare_m3} », M2 impose « {type_impose_m2} ».")
    if divergences_types:
        return divergences_types

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


MOTIF_COPIE_DECLAREE = r"Copié mot pour mot du PRD section (\d+(?:\.\d+)?)\."


def verifier_copies_declarees(prd: str, archi: str) -> List[str]:
    """Contrôle 18 : les copies déclarées sont identiques, et toute copie exacte
    se déclare.

    Une promesse de copie non vérifiée diverge en silence : éditer une seule des
    deux faces laisse l'architecture affirmer une fidélité qu'elle n'a plus —
    la classe de défaut de l'issue #166.

    PASSE 1 — les copies qui se DÉCLARENT (motif MOTIF_COPIE_DECLAREE) sont
    confrontées ligne à ligne. Deux GENRES d'artefact sont reconnus : « bloc »
    (bloc de code clôturé ``` … ```) et « table » (suite contiguë d'au moins
    deux lignes commençant par « | »). Pour chaque déclaration, un seul
    artefact est retenu : celui de la zone bornée entre la fin de la
    déclaration et le prochain titre markdown, jamais au-delà — une recherche
    sans borne traversait plusieurs sections et rapportait un artefact étranger
    à la copie déclarée (mesuré sur les déclarations des sections 4.1 et 4.2) —
    et une zone qui contient PLUS D'UN artefact est refusée plutôt que devinée,
    la déclaration ne désignant pas lequel elle couvre. Côté PRD, l'appariement
    exige le MÊME genre et la même première ligne non vide : un artefact
    retrouvé sous un autre genre n'est pas la copie de celui-ci.

    PASSE 2 — toute copie EXACTE doit se déclarer. Retirer une déclaration
    retirait silencieusement la copie du périmètre du contrôle : le gate
    restait vert et plus rien ne suivait le bloc (mutation mesurée). Tout
    artefact de l'architecture IDENTIQUE à un artefact du PRD — même genre,
    lignes égales après rstrip() par ligne, comme la passe 1 — doit donc être
    précédé d'une déclaration dans sa propre section, c'est-à-dire entre la
    fin du dernier titre markdown qui le précède et son début. La règle plus
    large « même première ligne ⇒ doit être déclarée » a été mesurée puis
    rejetée : des tables distinctes partagent une ligne d'en-tête avec un
    artefact du PRD sans en être des copies (deux faux positifs mesurés).

    Toutes les recherches de titres — borne de la zone de la passe 1, dernier
    titre précédant un artefact à la passe 2, titres du PRD lus par
    section_du_prd — se font sur une vue du texte où le contenu de chaque bloc
    clôturé (clôtures comprises) est masqué caractère pour caractère, car un
    « # » en colonne 0 à l'intérieur d'un bloc est du code et non un titre ;
    les contenus comparés viennent toujours du texte d'origine, la vue masquée
    ne servant qu'à localiser, à longueur strictement identique. Le même
    scanner de blocs sert au masquage et à l'extraction des artefacts, pour
    qu'il n'existe qu'une seule définition de ce qu'est un bloc.
    Les déclarations sont cherchées sur cette même vue masquée, exactement
    comme les titres : une phrase « Copié mot pour mot du PRD section N »
    écrite à l'intérieur d'un bloc clôturé y est un exemple ou une citation,
    jamais un engagement — elle ne doit ni ouvrir une confrontation à la
    passe 1 ni tenir lieu de déclaration à la passe 2.

    Le module ne reconnaît qu'un seul séparateur de ligne, « \\n », partagé par
    le scanner de blocs, les expressions régulières et la comparaison de
    contenu — cette dernière passant par la fonction interne lignes_de.

    LIMITE EXACTE : une copie qui a été MODIFIÉE et n'a jamais été déclarée
    reste indétectable — n'étant plus identique à sa source, rien ne la
    distingue d'un artefact indépendant. La passe 1 ne suit que les copies
    déclarées, la passe 2 que les copies exactes ; aucune des deux n'annonce
    une couverture plus large que celle qu'elle tient.
    """

    # Une table : au moins deux lignes contiguës commençant par « | » (après
    # espaces éventuels) ; elle s'arrête à la première ligne qui n'en commence
    # pas par « | ».
    motif_table = re.compile(r"^[ \t]*\|[^\n]*(?:\n[ \t]*\|[^\n]*)+", re.MULTILINE)
    # Un titre markdown peut être indenté de 0 à 3 espaces : ainsi indenté, il
    # borne les zones exactement comme un titre en colonne 0.
    motif_titre = re.compile(r"^ {0,3}#{1,6}\s", re.MULTILINE)

    def lignes_de(texte: str) -> List[str]:
        """Découpe `texte` sur « \\n » SEUL : le scanner de blocs, les
        expressions régulières en re.MULTILINE et la comparaison de contenu
        doivent partager la MÊME notion de ligne, et .splitlines() coupe en
        plus sur « \\r » seul, « \\v » et « \\f », ce qui a produit un faux
        négatif mesuré — une copie exacte rapportée divergente. Sur la chaîne
        vide, "".split("\\n") rend [""] — une ligne vide — là où .splitlines()
        rendrait la liste vide ; les deux côtés d'une comparaison passant par
        cette même fonction, la symétrie est préservée.
        """
        return texte.split("\n")

    def blocs_clotures(texte: str) -> List[Tuple[int, int, int, int]]:
        """Balaye `texte` LIGNE PAR LIGNE et retourne ses blocs de code clôturés.

        Le découpage en lignes se fait sur « \\n » SEUL, DÉLIBÉRÉMENT, pour
        partager la notion de ligne de re.MULTILINE, dont dépendent les
        recherches de titres : splitlines couperait aussi sur « \\r » seul,
        « \\v » et « \\f », et ferait diverger le scanner des expressions
        régulières.

        Chaque bloc est décrit par (debut, fin, debut_contenu, fin_contenu), en
        offsets absolus dans `texte` : debut et fin bornent le bloc CLÔTURES
        COMPRISES, debut_contenu et fin_contenu bornent son contenu seul. Une
        ligne OUVRE un bloc si, après avoir retiré 0 à 3 espaces de tête, elle
        commence par au moins trois accents graves consécutifs — la longueur de
        cette clôture est retenue, et le reste de la ligne est l'étiquette de
        langue. Tant qu'un bloc est ouvert, une ligne le FERME si, après avoir
        retiré 0 à 3 espaces de tête, elle n'est faite que d'accents graves en
        nombre SUPÉRIEUR OU ÉGAL à la clôture ouvrante, suivis d'espaces
        éventuels et de rien d'autre ; toute autre ligne, y compris une clôture
        PLUS COURTE, appartient au contenu — c'est ce qui rend les blocs
        imbriqués corrects : un bloc à trois accents écrit dans un bloc à
        quatre n'en est pas la fermeture. Un bloc jamais fermé s'étend jusqu'à
        la FIN du texte.
        """
        blocs: List[Tuple[int, int, int, int]] = []
        pos = 0
        en_bloc = False
        debut = 0
        debut_contenu = 0
        longueur_ouvrante = 0
        # Découpage sur « \n » SEUL, le séparateur étant réattaché à chaque
        # segment sauf, éventuellement, le dernier : splitlines(keepends=True)
        # couperait aussi sur « \r » seul, « \v » et « \f », et le scanner
        # n'aurait plus la notion de ligne de re.MULTILINE.
        segments = texte.split("\n")
        lignes = [segment + "\n" for segment in segments[:-1]] + segments[-1:]
        for ligne in lignes:
            fin_ligne = pos + len(ligne)
            if ligne.endswith("\r\n"):
                corps = ligne[:-2]
            elif ligne.endswith("\n") or ligne.endswith("\r"):
                corps = ligne[:-1]
            else:
                corps = ligne
            espaces = len(corps) - len(corps.lstrip(" "))
            # Au-delà de 3 espaces de tête, la ligne ne peut ni ouvrir ni
            # fermer un bloc : reste à None la range hors jeu.
            reste = corps[espaces:] if espaces <= 3 else None
            if not en_bloc:
                if reste is not None:
                    m_ouverture = re.match(r"`+", reste)
                    if m_ouverture is not None and len(m_ouverture.group(0)) >= 3:
                        en_bloc = True
                        longueur_ouvrante = len(m_ouverture.group(0))
                        debut = pos
                        debut_contenu = fin_ligne
            elif reste is not None:
                m_fermeture = re.fullmatch(r"(`+) *", reste)
                if (m_fermeture is not None
                        and len(m_fermeture.group(1)) >= longueur_ouvrante):
                    blocs.append((debut, fin_ligne, debut_contenu, pos))
                    en_bloc = False
            pos = fin_ligne
        if en_bloc:
            # Bloc jamais fermé : il s'étend jusqu'à la fin du texte.
            blocs.append((debut, len(texte), debut_contenu, len(texte)))
        return blocs

    def masquer_blocs(texte: str) -> str:
        """Vue de `texte` où chaque bloc de code clôturé est masqué caractère
        pour caractère, clôtures comprises.

        Tout caractère d'un bloc autre que « \\n » est remplacé par exactement UN
        espace — y compris pour un bloc jamais fermé, que `blocs_clotures`
        étend jusqu'à la fin du texte et qui est donc masqué jusque-là. La
        longueur totale et la position des sauts de ligne « \\n » — le seul
        séparateur reconnu par ce module — sont strictement préservées, car les
        offsets mesurés sur cette vue doivent trancher le texte d'origine.
        """
        caracteres = list(texte)
        for debut, fin, _, _ in blocs_clotures(texte):
            for i in range(debut, fin):
                if caracteres[i] != "\n":
                    caracteres[i] = " "
        return "".join(caracteres)

    # Les recherches de titres se font sur ces vues ; les contenus comparés
    # sont toujours tranchés dans les textes d'origine, aux mêmes offsets.
    prd_masque = masquer_blocs(prd)
    archi_masque = masquer_blocs(archi)

    def premiere_ligne_non_vide(texte: str) -> str:
        """Première ligne non vide du texte, sans espaces de fin ('' si vide)."""
        for ligne in lignes_de(texte):
            if ligne.strip():
                return ligne.rstrip()
        return ""

    def tous_artefacts(texte: str) -> List[Tuple[str, str, int, int]]:
        """Liste ordonnée de tous les artefacts de `texte`.

        Chaque élément est un quadruplet (genre, contenu, debut, fin) : genre
        vaut « bloc » (contenu entre les clôtures ```) ou « table » (suite
        contiguë d'au moins deux lignes commençant par « | ») ; contenu est le
        texte de l'artefact ; debut et fin sont les offsets où l'artefact
        commence et finit dans `texte`. Les blocs retenus sont EXACTEMENT ceux
        que `blocs_clotures` retourne — le scanner qui sert aussi au masquage,
        pour qu'il n'existe qu'une seule définition de ce qu'est un bloc — et
        une table située à l'intérieur d'un bloc clôturé est du contenu de
        bloc, pas un artefact. Le parcours est non recouvrant : les artefacts
        sont triés par offset de début, et tout artefact qui commencerait avant
        la fin du précédent retenu est écarté. Cette fonction est l'unique juge
        de ce qu'est un artefact : elle est appliquée à l'architecture comme au
        PRD, pour que les deux côtés parlent de la même chose.
        """
        blocs = blocs_clotures(texte)
        candidats: List[Tuple[int, int, str, str]] = []
        for debut, fin, debut_contenu, fin_contenu in blocs:
            candidats.append((debut, fin, "bloc", texte[debut_contenu:fin_contenu]))
        for m_table in motif_table.finditer(texte):
            if any(d <= m_table.start() < f for d, f, _, _ in blocs):
                # Une table écrite à l'intérieur d'un bloc clôturé est du
                # contenu de bloc, pas un artefact.
                continue
            candidats.append((m_table.start(), m_table.end(), "table", m_table.group(0)))
        candidats.sort(key=lambda c: c[0])
        artefacts: List[Tuple[str, str, int, int]] = []
        pos = 0
        for debut, fin, genre, contenu in candidats:
            if debut < pos:
                continue
            artefacts.append((genre, contenu, debut, fin))
            pos = fin
        return artefacts

    def premier_artefact(texte: str, depart: int = 0):
        """Premier artefact de `texte` à partir de `depart`, ou None.

        Retourne le triplet (genre, contenu, fin) : genre vaut « bloc » ou
        « table » ; contenu est le texte de l'artefact ; fin est l'offset de
        fin de l'artefact, où reprendre la recherche du suivant. Le juge de ce
        qu'est un artefact est UNIQUE : cette fonction se contente de filtrer
        `tous_artefacts`, dont l'offset de fin vient du même scanner qui a
        borné l'artefact — aucune fin n'est recalculée par expression
        régulière, calcul qui retomberait sur la première clôture interne d'un
        bloc imbriqué.
        """
        for genre, contenu, debut, fin in tous_artefacts(texte):
            if debut < depart:
                continue
            return (genre, contenu, fin)
        return None

    def section_du_prd(numero: str):
        """Texte de la section du PRD dont le titre porte exactement ce numéro.

        Le titre est `## N. …` ou `### N.M …`, indenté de 0 à 3 espaces au
        plus ; la section s'étend jusqu'au titre suivant de niveau inférieur ou
        égal. Les titres sont repérés sur la vue masquée du PRD — un « # » en
        colonne 0 dans un bloc clôturé y est du code, pas un titre — et les
        offsets, à longueur préservée, tranchent le PRD d'origine. Retourne
        None si le titre est introuvable — fail-closed, on ne devine pas la
        section source.
        """
        titres = []
        for m in re.finditer(r"^ {0,3}(#{1,6})\s+(.*)$", prd_masque, re.MULTILINE):
            m_num = re.match(r"(\d+(?:\.\d+)?)\.?(?:\s|$)", m.group(2).strip())
            titres.append((m.start(), m.end(), len(m.group(1)),
                           m_num.group(1) if m_num else None))
        cible = None
        for t in titres:
            if t[3] == numero:
                cible = t
                break
        if cible is None:
            return None
        fin = len(prd)
        for t in titres:
            if t[0] > cible[0] and t[2] <= cible[2]:
                fin = t[0]
                break
        return prd[cible[1]:fin]

    erreurs: List[str] = []
    # Les déclarations sont cherchées sur la vue masquée, comme les titres :
    # une phrase « Copié mot pour mot du PRD section N » écrite à l'intérieur
    # d'un bloc clôturé est un exemple ou une citation, pas un engagement —
    # la compter ouvrirait une passe 1 sur un artefact qui n'existe pas (faux
    # positif mesuré). Les offsets étant préservés par construction,
    # declaration.end() tranche le texte d'origine et declaration.group(1)
    # rend le numéro de section exactement comme avant.
    declarations = list(re.finditer(MOTIF_COPIE_DECLAREE, archi_masque))
    if not declarations:
        return ["Aucune déclaration « Copié mot pour mot du PRD section N » trouvée "
                "dans l'architecture — extracteur vide, contrôle non probant : "
                "un contrôle qui ne compare rien passe toujours."]

    # PASSE 1 — les copies déclarées sont confrontées ligne à ligne.
    for declaration in declarations:
        numero = declaration.group(1)
        # a. L'artefact copié est cherché UNIQUEMENT entre la fin de la
        # déclaration et le prochain titre markdown : sans cette borne, la
        # recherche traversait plusieurs sections et rapportait l'artefact
        # d'une section étrangère — comparer le mauvais artefact est pire que
        # ne rien comparer (mesuré). Le titre est cherché sur la vue masquée :
        # un « # » en colonne 0 dans un bloc clôturé est du code, pas un titre.
        m_titre = motif_titre.search(archi_masque, declaration.end())
        fin_zone = m_titre.start() if m_titre else len(archi)
        zone = archi[declaration.end():fin_zone]
        artefacts_zone = tous_artefacts(zone)
        if not artefacts_zone:
            erreurs.append(
                f"Copie déclarée de la section PRD {numero} : aucun artefact "
                f"(bloc clôturé ou table) entre la déclaration et le prochain "
                f"titre — une copie promise sans artefact est invérifiable.")
            continue
        # b. Une zone à plusieurs artefacts est ambiguë, fail-closed plutôt que
        # deviner : la déclaration ne dit pas lequel elle couvre, et les
        # artefacts suivants ne seraient jamais vérifiés.
        if len(artefacts_zone) > 1:
            erreurs.append(
                f"Copie déclarée de la section PRD {numero} : {len(artefacts_zone)} "
                f"artefacts entre la déclaration et le prochain titre, et la "
                f"déclaration ne désigne pas lequel elle couvre — une déclaration "
                f"gouverne l'artefact unique qui la suit ; s'il y en a plusieurs, "
                f"le document doit être découpé, pas deviné.")
            continue
        genre_arc, contenu_arc, _, _ = artefacts_zone[0]
        # c. La section du PRD portant exactement ce numéro.
        section = section_du_prd(numero)
        if section is None:
            erreurs.append(
                f"Copie déclarée de la section PRD {numero} : ce titre est introuvable "
                f"dans le PRD — fail-closed, on ne devine pas la section source.")
            continue
        # d. Le premier artefact DU MÊME GENRE dans la section du PRD dont la
        # première ligne non vide est celle de l'artefact de l'architecture.
        premiere_arc = premiere_ligne_non_vide(contenu_arc)
        contenu_prd = None
        pos = 0
        while True:
            trouve_prd = premier_artefact(section, pos)
            if trouve_prd is None:
                break
            genre_prd, candidat, pos = trouve_prd
            if (genre_prd == genre_arc
                    and premiere_ligne_non_vide(candidat) == premiere_arc):
                contenu_prd = candidat
                break
        if contenu_prd is None:
            erreurs.append(
                f"Copie déclarée de la section PRD {numero} : aucun artefact de "
                f"genre « {genre_arc} » dans cette section ne commence par "
                f"« {premiere_arc[:120]} » — artefact source introuvable, "
                f"contrôle non probant pour cette copie.")
            continue
        # e. Comparaison ligne à ligne ; les espaces de fin ne sont pas du contenu.
        lignes_prd = [l.rstrip() for l in lignes_de(contenu_prd.rstrip("\n"))]
        lignes_arc = [l.rstrip() for l in lignes_de(contenu_arc.rstrip("\n"))]
        divergence = False
        for i, (lp, la) in enumerate(zip(lignes_prd, lignes_arc), start=1):
            if lp != la:
                erreurs.append(
                    f"Copie déclarée de la section PRD {numero} : divergence à la "
                    f"ligne {i} de l'artefact — PRD : « {lp[:120]} » ; architecture : "
                    f"« {la[:120]} ».")
                divergence = True
                break
        if not divergence and len(lignes_prd) != len(lignes_arc):
            erreurs.append(
                f"Copie déclarée de la section PRD {numero} : préfixe commun identique "
                f"mais longueurs différentes — {len(lignes_prd)} lignes côté PRD, "
                f"{len(lignes_arc)} côté architecture.")

    # PASSE 2 — toute copie exacte doit se déclarer.
    # Un artefact de l'architecture identique à un artefact du PRD (même genre,
    # mêmes lignes après rstrip() par ligne) est une copie, qu'elle se déclare
    # ou non : la passe 1 ne la voit que si elle se déclare, et retirer la
    # déclaration la faisait disparaître du contrôle sans rien changer d'autre
    # (mutation mesurée). Elle doit donc porter une déclaration dans sa propre
    # section — entre la fin du dernier titre markdown qui la précède et son
    # début.
    normalises_prd: Dict[str, List[List[str]]] = {}
    for genre_p, contenu_p, _, _ in tous_artefacts(prd):
        normalises_prd.setdefault(genre_p, []).append(
            [l.rstrip() for l in lignes_de(contenu_p.rstrip("\n"))])
    for genre_a, contenu_a, debut_a, _ in tous_artefacts(archi):
        lignes_a = [l.rstrip() for l in lignes_de(contenu_a.rstrip("\n"))]
        if lignes_a not in normalises_prd.get(genre_a, []):
            # Pas une copie exacte : rien à suivre pour cette passe.
            continue
        # Le dernier titre est cherché sur la vue masquée : un « # » en colonne
        # 0 dans un bloc clôturé est du code, pas un titre — sans cela la borne
        # était décalée et une déclaration légitime était manquée.
        titres_avant = list(motif_titre.finditer(archi_masque, 0, debut_a))
        borne = titres_avant[-1].end() if titres_avant else 0
        # La déclaration est cherchée sur la vue masquée, pour la même raison
        # qu'à la passe 1 : citée dans un bloc clôturé entre la borne et
        # l'artefact, elle serait un exemple et non un engagement, et ferait
        # passer pour déclarée une copie qui ne l'est pas. Les offsets sont
        # préservés par construction : la tranche [borne:debut_a] y désigne
        # exactement la même zone que dans le texte d'origine.
        if re.search(MOTIF_COPIE_DECLAREE, archi_masque[borne:debut_a]):
            continue
        premiere_a = premiere_ligne_non_vide(contenu_a)
        erreurs.append(
            f"Copie non déclarée : l'artefact de genre « {genre_a} » dont la "
            f"première ligne est « {premiere_a[:120]} » est identique à un "
            f"artefact du PRD, mais aucune déclaration « Copié mot pour mot du "
            f"PRD section N » n'apparaît entre le dernier titre qui le précède "
            f"et lui — une copie doit se déclarer pour être suivie.")
    return erreurs

# Contrôle 19 — motifs partagés entre la fonction de contrôle et le comptage du
# bloc OK de main, comme MOTIF_COPIE_DECLAREE pour le contrôle 18.
MOTIF_TITRE_CONTRAT_BRIEF = r"^##\s+\d+\.\s+CONTRAT D'ENTRÉE\s*$"
MOTIF_CHAMP_BRIEF = r"^[ \t]*-[ \t]+`([a-z_][a-z0-9_]*)`"


def champs_du_contrat_brief(brief: str) -> List[str]:
    """UNIQUE extracteur des champs du « CONTRAT D'ENTRÉE » du brief, utilisé par
    le contrôle 19 comme par son message de succès.

    Retourne la liste ordonnée et sans doublon des noms présentés dans la
    section ; liste vide si la section est introuvable ou ne présente aucun champ.
    """
    titre = re.search(MOTIF_TITRE_CONTRAT_BRIEF, brief, re.MULTILINE)
    if not titre:
        return []
    reste = brief[titre.end():]
    suivant = re.search(r"^#{1,2}\s", reste, re.MULTILINE)
    section = reste[:suivant.start()] if suivant else reste
    return list(dict.fromkeys(re.findall(MOTIF_CHAMP_BRIEF, section, re.MULTILINE)))


def verifier_brief_contrat_reel(brief: str, archi: str) -> List[str]:
    """Contrôle 19 : le contrat d'entrée que décrit le brief est celui que M2 émet.

    Le brief est le premier document que lit qui implémente le module, et rien ne
    le confrontait : la correction de l'issue #166 y a laissé le contrat fantôme.
    LIMITE : seule la section « CONTRAT D'ENTRÉE » est vérifiée, pas les mentions
    du contrat ailleurs dans le brief.
    """
    # Étape 1 — la section, ancrée sur son NOM et jamais sur son numéro ; la
    # présence du titre est testée ici, mais l'extraction des NOMS n'existe que
    # dans champs_du_contrat_brief, l'unique extracteur de cette notion.
    if not re.search(MOTIF_TITRE_CONTRAT_BRIEF, brief, re.MULTILINE):
        return ["Section « CONTRAT D'ENTRÉE » absente du brief — le contrôle du "
                "brief est non probant."]

    # Étape 2 — les champs présentés : puces de la forme `- `<nom>` — …`, le nom
    # étant [a-z_][a-z0-9_]*.
    champs_brief = set(champs_du_contrat_brief(brief))
    if not champs_brief:
        return ["Aucun champ extrait de la section « CONTRAT D'ENTRÉE » du brief — "
                "extracteur vide, le contrôle du brief est non probant : un "
                "contrôle qui ne compare rien passe toujours."]

    # Étape 3 — les clés RÉELLES, lues dans la SOURCE du producteur comme au
    # contrôle 13 ; racine du dépôt dérivée de __file__, jamais du répertoire
    # courant. Tout repli est fail-closed.
    depot = Path(__file__).resolve().parents[4]
    source_m2 = depot / "Modules M" / "M2-revenue-crm" / "src" / "m2_revenue_crm" / "contrats.py"
    if not source_m2.is_file():
        return [f"Source du module producteur introuvable ({source_m2}) — le "
                f"contrôle du brief est non probant, jamais silencieusement vert."]
    try:
        texte_m2 = source_m2.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return [f"Source du module producteur illisible ({source_m2}) : {exc} — "
                f"le contrôle du brief est non probant, jamais silencieusement vert."]
    bloc = re.search(r"CHAMPS_CONTRAT_GELE\s*=\s*\((.*?)\)", texte_m2, re.DOTALL)
    if not bloc:
        return ["Constante CHAMPS_CONTRAT_GELE introuvable dans la source de M2 — "
                "extracteur vide, le contrôle du brief est non probant."]
    cles_m2 = set(re.findall(r'"([a-z_][a-z0-9_]*)"', bloc.group(1)))
    if not cles_m2:
        return ["Aucune clé extraite de CHAMPS_CONTRAT_GELE — extracteur vide, "
                "le contrôle du brief est non probant."]

    # Étapes 4 et 5 — la confrontation est symétrique : un champ inventé trompe
    # autant qu'un champ tu.
    erreurs: List[str] = []
    fantomes = sorted(champs_brief - cles_m2)
    if fantomes:
        erreurs.append(
            f"Champs présentés par le brief comme appartenant au contrat d'entrée "
            f"mais ABSENTS de ce que le producteur émet : {fantomes} — le brief "
            f"décrit un contrat que le producteur n'émet pas.")
    manquantes = sorted(cles_m2 - champs_brief)
    if manquantes:
        erreurs.append(
            f"Clés que le producteur émet mais que le brief ne mentionne pas dans "
            f"sa section « CONTRAT D'ENTRÉE » : {manquantes} — un brief qui ne "
            f"décrit qu'une partie du contrat laisse croire au reste.")
    return erreurs

# Rapprochement par fragment et non par égalité : le critère parle en langue
# naturelle (« le seuil »), l'interface nomme une clé (`seuils_qualite`).
GRANDEURS_FOURNIES = (
    ("seuil", "seuil"),
    ("barème", "bareme"),
    ("graine", "graine"),
    ("plancher", "plancher"),
)


def verifier_grandeurs_fournies_declarees(prd: str, archi: str) -> List[str]:
    """Contrôle 20 : toute grandeur que les critères exigent comme fournie est
    déclarée dans l'interface d'entrée, sous un nom portant le fragment
    correspondant — un critère qui exige ce que l'interface ne déclare pas
    est improuvable (DA-M3-09). LIMITE : seules les grandeurs de la table
    GRANDEURS_FOURNIES sont confrontées ; une grandeur d'un autre nom n'est
    pas suivie. LIMITE : le rapprochement entre le mot employé par un
    critère et le nom d'une entrée déclarée est purement LEXICAL, par
    fragment — il établit qu'une grandeur est déclarée, jamais qu'elle est
    la bonne : une entrée au nom voisin mais sémantiquement étranger
    (« seuil_acceptation » face au « seuil » de qualité photo) satisferait
    le contrôle."""

    def plier(texte: str) -> str:
        """Minuscules sans accents : la comparaison est insensible à la casse
        et aux accents — le « barème » des critères doit rejoindre « bareme »."""
        return texte.lower().translate(str.maketrans({
            "à": "a", "â": "a", "ä": "a", "á": "a",
            "é": "e", "è": "e", "ê": "e", "ë": "e",
            "î": "i", "ï": "i",
            "ô": "o", "ö": "o",
            "ù": "u", "û": "u", "ü": "u",
            "ç": "c", "œ": "oe", "æ": "ae",
        }))

    # Étape 1 — la section des critères du PRD, ancrée sur son NOM, jamais
    # sur son numéro.
    debut_ca = re.search(r"^##\s+(?:\d+\.\s+)?CRITÈRES D'ACCEPTATION\s*$",
                         prd, re.MULTILINE)
    if not debut_ca:
        return ["Section « CRITÈRES D'ACCEPTATION » introuvable dans le PRD — "
                "contrôle non probant."]
    reste_prd = prd[debut_ca.end():]
    fin_ca = re.search(r"^##\s", reste_prd, re.MULTILINE)
    section_ca = reste_prd[:fin_ca.start()] if fin_ca else reste_prd

    # Étape 2 — la section de l'interface d'entrée de l'architecture, ancrée
    # sur son NOM, jamais sur son numéro.
    titre_interface = re.search(
        r"^(#{1,6})\s+(?:\d+(?:\.\d+)*\.?\s+)?Interface d['’]entrée\b[^\n]*$",
        archi, re.MULTILINE)
    if not titre_interface:
        return ["Section « Interface d'entrée » introuvable dans l'architecture — "
                "contrôle non probant."]
    niveau = len(titre_interface.group(1))
    reste_archi = archi[titre_interface.end():]
    titre_suivant = re.search(rf"^#{{1,{niveau}}}\s", reste_archi, re.MULTILINE)
    section_interface = (reste_archi[:titre_suivant.start()]
                         if titre_suivant else reste_archi)

    # Étape 3 — les entrées déclarées : puces de la forme
    # `- `<nom>: <type>` — …`, le nom étant [a-z_][a-z0-9_]*.
    entrees = re.findall(r"^[ \t]*-[ \t]+`([a-z_][a-z0-9_]*):[^`]*`",
                         section_interface, re.MULTILINE)
    if not entrees:
        return ["Aucune entrée extraite de la section « Interface d'entrée » — "
                "extracteur vide, contrôle non probant : un contrôle qui ne "
                "compare rien passe toujours."]

    # Étape 4 — chaque grandeur employée par les critères doit être fournie.
    erreurs: List[str] = []
    criteres_plies = plier(section_ca)
    for mot, fragment in GRANDEURS_FOURNIES:
        if plier(mot) not in criteres_plies:
            continue
        if any(fragment in nom for nom in entrees):
            continue
        erreurs.append(
            f"Grandeur « {mot} » employée par les critères d'acceptation mais "
            f"aucune entrée déclarée ne porte le fragment « {fragment} » — "
            f"entrées déclarées : {sorted(set(entrees))}. Un critère qui exige "
            f"ce que l'interface ne déclare pas est improuvable (DA-M3-09).")
    return erreurs



def verifier_renvois_internes_valides(prd: str, archi: str) -> List[str]:
    """Contrôle 21 : chaque renvoi interne mesuré vise une section existante dans
    le même document.

    Le contrôle extrait les sections réellement définies par leurs titres de
    niveau 2 ou 3, puis confronte les renvois internes de la forme « décrit en
    N » et « voir N » à cet ensemble. Les blocs de code clôturés sont masqués
    avant toute recherche : un renvoi écrit dans un exemple ou une citation n'est
    pas un engagement documentaire.

    Les renvois inter-documents sont exclus. Ils nomment toujours leur source
    (« du PRD section », « proposé par l'analyste », « brief analyste »), à la
    différence des renvois internes qui ne portent que leur numéro ; une lecture
    de proximité suffit donc pour les distinguer dans les formulations mesurées.

    LIMITE EXACTE : le contrôle vérifie seulement que la section citée existe
    dans le document qui la cite. Il ne vérifie ni que son contenu correspond à
    la promesse du renvoi, ni les renvois inter-documents ; ces responsabilités
    appartiennent aux contrôles spécialisés correspondants.

    CINQ LIMITES SUPPLÉMENTAIRES, mesurées comme ABSENTES du corpus actuel
    (objections de revue scellée — vérifié par mesure directe avant d'écrire
    cette note, pas supposé) mais qui resteraient de vrais angles morts si le
    corpus évoluait :
    - les motifs reconnus sont « décrit en » et « voir » ; une autre
      formulation de renvoi interne (« cf. », « section N » sans qualificatif
      de source) échapperait au contrôle. Aucune de ces formes n'a été
      trouvée dans le corpus mesuré.
    - les marques d'exclusion inter-documents sont des chaînes fixes ; une
      formulation non mesurée échapperait à l'exclusion (fausse alerte) ou à
      la détection (silence). Toutes les occurrences réelles de « section N »
      qualifiée mesurées dans le corpus sont couvertes par les trois marques.
    - un titre de section n'est reconnu qu'à deux niveaux (« N.N ») ; une
      sous-sous-section (« N.N.N ») ne serait pas distinguée de son préfixe.
      Le corpus ne contient aucun titre à trois niveaux.
    - seuls les blocs ```yaml échappent au masquage ; un autre langage de
      bloc portant un jour un renvoi engagé (ou un bloc yaml portant un
      titre markdown qui ressemblerait à une section) resterait un angle
      mort. Aucun bloc du corpus ne présente ce cas.
    - les motifs de renvoi sont sensibles à la casse (« décrit en », « voir »,
      minuscules) ; une variante en capitale (« Voir », « DÉCRIT EN »)
      échapperait à la détection. Aucune variante de casse n'a été trouvée
      dans le corpus mesuré.
    Ce contrôle ne prétend donc pas une robustesse à un corpus qu'il n'a pas
    vu ; il tient ce qu'il a mesuré, comme le reste de ce fichier.
    """

    def masquer_blocs(texte: str) -> str:
        """Masque les blocs clôturés par accents graves, SAUF les blocs ``yaml``.

        `blocs_clotures` est locale à `verifier_copies_declarees` et ne peut pas
        être réutilisée sans modifier cette autre fonction, ce qui est interdit
        ici. Ce scanner minimal reproduit donc sa règle pertinente : ouverture
        et fermeture par au moins trois accents graves, avec une fermeture d'une
        longueur au moins égale à celle de l'ouverture.

        EXCEPTION MESURÉE : un bloc ```yaml décrit un contrat gelé — son contenu
        est normatif, pas une citation d'exemple. Le seul renvoi interne engagé
        qui vit dans un bloc clôturé du corpus réel est « voir 2.5 », À
        L'INTÉRIEUR du bloc YAML du contrat LeadQualifie ; masquer tous les
        blocs génériquement le rendait invisible et ROUVRAIT exactement le trou
        que ce contrôle existe pour fermer. Les autres langages (``text`` dans
        les citations d'exemple mesurées) restent masqués : eux ne portent
        jamais de renvoi engagé dans ce corpus.
        """
        caracteres = list(texte)
        position = 0
        ouvert = False
        masquer_ce_bloc = False
        debut_bloc = 0
        longueur_ouverture = 0
        segments = texte.split("\n")
        lignes = [segment + "\n" for segment in segments[:-1]] + segments[-1:]

        for ligne in lignes:
            fin_ligne = position + len(ligne)
            if ligne.endswith("\r\n"):
                corps = ligne[:-2]
            elif ligne.endswith("\n") or ligne.endswith("\r"):
                corps = ligne[:-1]
            else:
                corps = ligne
            indentation = len(corps) - len(corps.lstrip(" "))
            reste = corps[indentation:] if indentation <= 3 else None

            if not ouvert:
                if reste is not None:
                    ouverture = re.match(r"`+", reste)
                    if ouverture is not None and len(ouverture.group(0)) >= 3:
                        ouvert = True
                        debut_bloc = position
                        longueur_ouverture = len(ouverture.group(0))
                        langage = reste[len(ouverture.group(0)):].strip().lower()
                        masquer_ce_bloc = langage != "yaml"
            elif reste is not None:
                fermeture = re.fullmatch(r"(`+) *", reste)
                if (fermeture is not None
                        and len(fermeture.group(1)) >= longueur_ouverture):
                    if masquer_ce_bloc:
                        for indice in range(debut_bloc, fin_ligne):
                            if caracteres[indice] != "\n":
                                caracteres[indice] = " "
                    ouvert = False

            position = fin_ligne

        if ouvert and masquer_ce_bloc:
            for indice in range(debut_bloc, len(caracteres)):
                if caracteres[indice] != "\n":
                    caracteres[indice] = " "

        return "".join(caracteres)

    erreurs: List[str] = []
    motifs_renvoi = (
        re.compile(r"décrit en (\d+(?:\.\d+)?)"),
        re.compile(r"voir (\d+(?:\.\d+)?)"),
    )
    marques_interdocuments = (
        "du prd section",
        "proposé par l'analyste",
        "brief analyste",
    )

    for etiquette, texte in (("PRD", prd), ("ARCHITECTURE", archi)):
        texte_masque = masquer_blocs(texte)
        sections = set(re.findall(
            r"^#{2,3}\s+(\d+(?:\.\d+)?)",
            texte_masque,
            re.MULTILINE,
        ))

        for motif in motifs_renvoi:
            for correspondance in motif.finditer(texte_masque):
                numero = correspondance.group(1)

                # Le bug historique « décrit en 2.3 bis » doit être refusé :
                # le motif mesuré capture le numéro, puis cette lecture locale
                # conserve le suffixe textuel qui rend le renvoi inexistant.
                suffixe_bis = re.match(
                    r"[ \t]+bis\b",
                    texte_masque[correspondance.end(1):],
                    re.IGNORECASE,
                )
                if suffixe_bis is not None:
                    numero += suffixe_bis.group(0)

                # BUG CORRIGÉ (revue scellée, objection Qwen3.8-Max fondée) : le
                # contexte de proximité était lu sur `texte` (original) alors que
                # la recherche du motif se fait sur `texte_masque`. Un renvoi
                # capturé HORS bloc, juste après une marque d'exclusion SITUÉE
                # DANS un bloc clôturé masqué, était donc ignoré à tort — le
                # masquage annoncé « avant toute recherche » ne s'appliquait pas
                # réellement à cette lecture. Vérifié : sans cette correction,
                # `voir 99.9` après un bloc ```text contenant seulement
                # « du PRD section » restait invisible (messages == []).
                # `texte` et `texte_masque` ont la MÊME longueur et les MÊMES
                # offsets par construction du masquage : lire le contexte sur
                # `texte_masque` ne change rien pour un contexte hors bloc, et
                # ferme l'angle mort pour un contexte partiellement en bloc.
                debut_contexte = max(0, correspondance.start(1) - 40)
                contexte = texte_masque[debut_contexte:correspondance.start(1)].lower()
                # Un renvoi inter-document nomme explicitement sa source ;
                # contrairement à un renvoi interne, sa proximité est donc
                # suffisante pour l'exclure sans deviner une cible locale.
                if any(marque in contexte for marque in marques_interdocuments):
                    continue

                if numero not in sections:
                    erreurs.append(
                        f"{etiquette} : renvoi interne vers la section {numero} "
                        f"alors qu'aucune section de ce numéro n'existe dans ce document."
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
        brief = lire_fichier(dossier / "01-BRIEF-ANALYSTE.md")
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
              "producteur émet — clés, énuméré type_travaux, et les types que M2 "
              "impose par un contrôle sur une clé littérale du contrat.")

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

    errs = verifier_copies_declarees(prd, archi)
    if errs:
        erreurs.extend(errs)
        for e in errs:
            print(f"ECHEC : {e}")
    else:
        nb_copies = len(re.findall(MOTIF_COPIE_DECLAREE, archi))
        print(f"OK : Les {nb_copies} copie(s) déclarée(s) « Copié mot pour mot du PRD » "
              f"sont identiques aux blocs du PRD, ligne à ligne.")

    errs = verifier_brief_contrat_reel(brief, archi)
    if errs:
        erreurs.extend(errs)
        for e in errs:
            print(f"ECHEC : {e}")
    else:
        nb_champs = len(champs_du_contrat_brief(brief))
        print(f"OK : Les {nb_champs} champs du contrat d'entrée décrits par le brief "
              f"sont exactement les clés que le module producteur émet.")

    errs = verifier_grandeurs_fournies_declarees(prd, archi)
    if errs:
        erreurs.extend(errs)
        for e in errs:
            print(f"ECHEC : {e}")
    else:
        print(f"OK : Les {len(GRANDEURS_FOURNIES)} grandeurs de GRANDEURS_FOURNIES "
              f"ont été confrontées — chacune, dès qu'un critère l'emploie, est "
              f"déclarée dans l'interface d'entrée.")

    errs = verifier_renvois_internes_valides(prd, archi)
    if errs:
        erreurs.extend(errs)
        for e in errs:
            print(f"ECHEC : {e}")
    else:
        print("OK : Chaque renvoi interne mesuré vise une section existante dans son document.")

    n = len(erreurs)
    if n == 0:
        print("VERDICT : TOUT VERT")
        return 0
    else:
        print(f"VERDICT : {n} CONTROLE(S) EN ECHEC")
        return 1


if __name__ == "__main__":
    sys.exit(main())
