"""Contradictions de la mémoire de M10 : deux affirmations de sources différentes qui ne peuvent pas être vraies
ensemble. On les RANGE, on marque les mémoires touchées, on PROPOSE selon l'ordre de vérité (`verite.py`, une donnée),
et une contradiction critique attend une personne. Rien n'est supprimé : tout est ajouté à des registres chaînés.

Deux registres append-only (câblés par `contradictions_outils.py`, comme `rapports_routine`) :

- **`affirmations`** (`affirmation_enregistree`, `affirmation_retiree`) : un fait À CLÉ, rangé par domaine
  (`affaires` ou `developpement`, jamais mêlés : ADR-0012). Une affirmation dit `domaine`, `sujet` («
  famille:identifiant »,
  famille fermée par domaine), `attribut`, `valeur` (un jeton, jamais un texte libre), la `classe` de sa source (une
  position de l'ordre de vérité), l'`emetteur` (qui l'affirme) et sa `ref` (d'où elle vient, vérifiable). Une nouvelle
  affirmation du MÊME émetteur et de la MÊME classe sur la même clé la REMPLACE (supersede : l'ancienne reste, marquée
  remplacée) ; ce n'est pas une contradiction. Une affirmation retirée (source disparue) reste aussi dans le registre.
- **`contradictions`** (`contradiction_detectee`, `contradiction_marque`, `contradiction_demande`,
  `contradiction_decidee`) : l'identifiant d'une contradiction est une empreinte de (clé, deux affirmations), donc
  rejouer la détection n'ajoute rien. L'état (`ouverte`, `resolue_auto`, `en_attente_humain`, `decidee`, `caduque`) et
  la marque de chaque mémoire (`retenue`, `dominee`, `contestee`, `valide`) sont REJOUÉS depuis les maillons, jamais
  des champs qu'on positionne.

Règle de résolution (la logique ne connaît aucune classe par son nom) :
1. rangs différents et contradiction NON critique : la classe de plus haute autorité est retenue, l'autre est marquée
   `dominee` (`resolue_auto`) ; la trace d'origine reste lisible ;
2. contradiction critique (une classe critique ou un attribut critique de l'ordre est en jeu) : les deux mémoires sont
   `contestee`, la proposition est consignée, une personne décide (N3) ;
3. même rang : aucune proposition, les deux mémoires sont `contestee`, une personne tranche.

Module pur (DA-M10-08) : aucun import d'``opsys`` ; l'instant est fourni par l'appelant.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from . import humain, verite

TYPE_AFFIRMATION = "affirmation_enregistree"
TYPE_RETRAIT = "affirmation_retiree"
TYPE_DETECTEE = "contradiction_detectee"
TYPE_MARQUE = "contradiction_marque"
TYPE_DEMANDE = "contradiction_demande"
TYPE_DECIDEE = "contradiction_decidee"

MARQUE_RETENUE, MARQUE_DOMINEE, MARQUE_CONTESTEE, MARQUE_VALIDE = "retenue", "dominee", "contestee", "valide"
_PRIORITE_MARQUE = {MARQUE_VALIDE: 0, MARQUE_RETENUE: 1, MARQUE_CONTESTEE: 2, MARQUE_DOMINEE: 3}
FONDEMENT_ORDRE, FONDEMENT_DETECTION, FONDEMENT_DECISION = "ordre_verite", "detection", "decision_humaine"

STATUT_OUVERTE, STATUT_AUTO, STATUT_HUMAIN = "ouverte", "resolue_auto", "en_attente_humain"
STATUT_DECIDEE, STATUT_CADUQUE = "decidee", "caduque"


PLAFOND_ACTIVES = 2000  # affirmations actives par domaine : au-delà, refus (une source qui déborde ne noie pas la file)

REJ_DOMAINE = "REJ-AFFIRMATION-DOMAINE-INCONNU"
REJ_CLASSE_INCONNUE = "REJ-AFFIRMATION-CLASSE-INCONNUE"
REJ_CLASSE_NON_ADMISE = "REJ-AFFIRMATION-CLASSE-NON-ADMISE"
REJ_SUJET = "REJ-AFFIRMATION-SUJET-INVALIDE"
REJ_ATTRIBUT = "REJ-AFFIRMATION-ATTRIBUT-INVALIDE"
REJ_VALEUR = "REJ-AFFIRMATION-VALEUR-INVALIDE"
REJ_DONNEE_PERSONNELLE = "REJ-AFFIRMATION-DONNEE-PERSONNELLE"
REJ_REFERENCE = "REJ-AFFIRMATION-REFERENCE-INVALIDE"
REJ_EMETTEUR = "REJ-AFFIRMATION-EMETTEUR-INVALIDE"
REJ_PLAFOND = "REJ-AFFIRMATION-PLAFOND"
REJ_INCONNUE = "REJ-CONTRADICTION-INCONNUE"
REJ_CADUQUE = "REJ-CONTRADICTION-CADUQUE"
REJ_DEJA_DECIDEE = "REJ-CONTRADICTION-DEJA-DECIDEE"
REJ_DECISION = "REJ-CONTRADICTION-DECISION-INCONNUE"


def types_affirmations() -> tuple[str, ...]:
    """Les types d'entrée du registre des affirmations (des fonctions, pas des constantes publiques : les gardes de
    conformité traitent une tuple en MAJUSCULES comme un énuméré métier)."""
    return (TYPE_AFFIRMATION, TYPE_RETRAIT)


def types_contradictions() -> tuple[str, ...]:
    return (TYPE_DETECTEE, TYPE_MARQUE, TYPE_DEMANDE, TYPE_DECIDEE)


def statuts() -> tuple[str, ...]:
    return (STATUT_OUVERTE, STATUT_AUTO, STATUT_HUMAIN, STATUT_DECIDEE, STATUT_CADUQUE)


def a_traiter() -> tuple[str, ...]:
    """Les états qui attendent quelqu'un : ouverte (égalité de rang) ou en attente d'une personne (critique)."""
    return (STATUT_OUVERTE, STATUT_HUMAIN)


def decisions() -> tuple[str, ...]:
    return ("retenir_a", "retenir_b", "coexistence_valide", "fausse_alerte")


def raisons_retrait() -> tuple[str, ...]:
    return ("absente_de_la_source", "retrait_humain")


_IDENTIFIANT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._~-]{0,99}$")
_ATTRIBUT = re.compile(r"^[a-z][a-z0-9_]{0,59}$")
_VALEUR = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,79}$")
_SUITE_CHIFFRES = re.compile(r"[0-9](?:[ .-]?[0-9]){6,}")  # un numéro (téléphone, carte) caché dans un jeton
# Un identifiant d'affaire peut être un hexadécimal long ou numérique : seul un identifiant ENTIÈREMENT numérique de la
# taille d'un téléphone, ou un numéro séparé, est refusé.
_TELEPHONE_DANS_IDENTIFIANT = re.compile(r"^[0-9]{10,11}$|[0-9]{3}[-. ][0-9]{3}[-. ][0-9]{4}")
_REF_REGISTRE = re.compile(r"^registre:(evenements|affaires):[0-9a-f]{64}$")
_REF_PROJET = re.compile(r"^projet:[A-Za-z0-9._/~+-]{1,200}@[0-9a-f]{64}$")
_EMETTEUR = {
    "agent": re.compile(r"^agent:m(0[1-9]|10)-[a-z][a-z0-9-]{0,40}$"),
    "humain": re.compile(r"^humain:[a-z][a-z0-9_.-]{1,63}$"),
    "ingestion": re.compile(r"^fichier:[A-Za-z0-9._/~+-]{1,200}$"),
}


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"{code}: {detail}")


# ---------------------------------------------------------------------------------------------------------------
# 1. Les affirmations
# ---------------------------------------------------------------------------------------------------------------
def cle_de(affirmation: Mapping[str, Any]) -> str:
    return f"{affirmation['domaine']}|{affirmation['sujet']}|{affirmation['attribut']}"


def valider(champs: Mapping[str, Any], ordre: verite.OrdreVerite, canal: str) -> dict[str, Any]:
    """L'affirmation, sous sa forme fermée ; `ValueError("REJ-AFFIRMATION-…: …")` au premier défaut, sans jamais
    citer la
    valeur reçue (elle pourrait être une donnée personnelle ou un secret)."""
    attendus = {"domaine", "sujet", "attribut", "valeur", "classe", "ref", "emetteur"}
    if not isinstance(champs, Mapping) or set(champs) != attendus:
        raise _refus(REJ_SUJET, f"champs exacts attendus : {sorted(attendus)}")
    domaine = champs["domaine"]
    if domaine not in verite.domaines():
        raise _refus(REJ_DOMAINE, f"domaine parmi {list(verite.domaines())}")
    classe = champs["classe"]
    if not ordre.connait(classe):
        raise _refus(REJ_CLASSE_INCONNUE, "classe de source hors de l'ordre de vérité")
    if canal not in verite.canaux() or not ordre.admet(classe, domaine, canal):
        raise _refus(
            REJ_CLASSE_NON_ADMISE,
            f"la classe {classe!r} ne s'obtient pas par le canal {canal!r} dans le domaine {domaine!r} "
            "(une autorité haute vient d'un fichier du dépôt ingéré ou d'une personne identifiée, jamais d'une "
            "déclaration)",
        )
    sujet = champs["sujet"]
    famille, _, identifiant = sujet.partition(":") if isinstance(sujet, str) else ("", "", "")
    if famille not in ordre.familles_sujet[domaine] or not _IDENTIFIANT.fullmatch(identifiant):
        raise _refus(REJ_SUJET, f"sujet « famille:identifiant », famille parmi {list(ordre.familles_sujet[domaine])}")
    attribut = champs["attribut"]
    if not isinstance(attribut, str) or not _ATTRIBUT.fullmatch(attribut):
        raise _refus(REJ_ATTRIBUT, "attribut en minuscules, chiffres et _ (60 caractères au plus)")
    valeur = champs["valeur"]
    if not isinstance(valeur, str) or not _VALEUR.fullmatch(valeur):
        raise _refus(REJ_VALEUR, "valeur : un jeton (lettres, chiffres, . _ : -), 80 caractères au plus, sans espace")
    if _SUITE_CHIFFRES.search(valeur) or _TELEPHONE_DANS_IDENTIFIANT.search(identifiant):
        raise _refus(
            REJ_DONNEE_PERSONNELLE, "une longue suite de chiffres ressemble à un numéro de téléphone ou de carte"
        )
    ref = champs["ref"]
    modele_ref = _REF_PROJET if canal == "ingestion" else _REF_REGISTRE
    if not isinstance(ref, str) or not modele_ref.fullmatch(ref):
        raise _refus(
            REJ_REFERENCE,
            "ref projet:<chemin>@<sha256> (ingestion)"
            if canal == "ingestion"
            else "ref registre:<evenements|affaires>:<ligne_id> (une affirmation est sourcée)",
        )
    emetteur = champs["emetteur"]
    if not isinstance(emetteur, str) or not _EMETTEUR[canal].fullmatch(emetteur):
        raise _refus(REJ_EMETTEUR, f"émetteur du canal {canal!r} mal formé")
    return {
        "domaine": domaine,
        "sujet": sujet,
        "attribut": attribut,
        "valeur": valeur,
        "classe": classe,
        "ref": ref,
        "emetteur": emetteur,
        "canal": canal,
    }


def affirmations(maillons: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Toutes les affirmations du registre, dans l'ordre, chacune avec `remplacee_par`, `retiree` et `active`, rejoués.
    Un `remplace` qui ne vise pas une affirmation antérieure de la MÊME clé est ignoré (fail-closed)."""
    liste: list[dict[str, Any]] = []
    par_id: dict[str, dict[str, Any]] = {}
    retirees: set[str] = set()
    for maillon in maillons:
        genre = maillon.get("type_entree")
        if genre == TYPE_AFFIRMATION:
            element = dict(maillon)
            element["remplacee_par"] = None
            cible = par_id.get(maillon.get("remplace") or "")
            if cible is not None and cle_de(cible) == cle_de(maillon) and cible["remplacee_par"] is None:
                cible["remplacee_par"] = maillon["ligne_id"]
            liste.append(element)
            par_id[maillon["ligne_id"]] = element
        elif genre == TYPE_RETRAIT:
            retirees.add(maillon.get("affirmation_ligne_id"))
    for element in liste:
        element["retiree"] = element["ligne_id"] in retirees
        element["active"] = element["remplacee_par"] is None and not element["retiree"]
    return liste


def actives(liste: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(a) for a in liste if a["active"]]


def preparer(
    liste: Sequence[Mapping[str, Any]], valide: Mapping[str, Any], horodatage: str, ordre: verite.OrdreVerite
) -> dict[str, Any]:
    """Ce que l'écriture d'une affirmation validée ajouterait : `{"resultat": "inchangee"|"ajoutee"|"remplace",
    "entree": …|None}`. Même clé, même classe, même émetteur : c'est LA MÊME source qui s'exprime, elle remplace sa
    version précédente (supersede) ; à l'identique (valeur et référence), rien n'est ajouté."""
    ordre.rang(valide["classe"])
    actifs = [a for a in liste if a["active"]]
    cle = cle_de(valide)
    precedente = next(
        (
            a
            for a in actifs
            if cle_de(a) == cle and a["classe"] == valide["classe"] and a["emetteur"] == valide["emetteur"]
        ),
        None,
    )
    if precedente is not None and precedente["valeur"] == valide["valeur"] and precedente["ref"] == valide["ref"]:
        return {"resultat": "inchangee", "entree": None, "ligne_id": precedente["ligne_id"]}
    if precedente is None and sum(1 for a in actifs if a["domaine"] == valide["domaine"]) >= PLAFOND_ACTIVES:
        raise _refus(REJ_PLAFOND, f"{PLAFOND_ACTIVES} affirmations actives par domaine : le plafond est atteint")
    entree = {
        "type_entree": TYPE_AFFIRMATION,
        "horodatage": horodatage,
        **valide,
        "remplace": precedente["ligne_id"] if precedente is not None else None,
    }
    return {"resultat": "remplace" if precedente is not None else "ajoutee", "entree": entree, "ligne_id": None}


def entree_retrait(affirmation: Mapping[str, Any], raison: str, horodatage: str) -> dict[str, Any]:
    if raison not in raisons_retrait():
        raise _refus(REJ_VALEUR, f"raison de retrait parmi {list(raisons_retrait())}")
    return {
        "type_entree": TYPE_RETRAIT,
        "horodatage": horodatage,
        "affirmation_ligne_id": affirmation["ligne_id"],
        "emetteur": affirmation["emetteur"],
        "raison": raison,
    }


# ---------------------------------------------------------------------------------------------------------------
# 2. La détection
# ---------------------------------------------------------------------------------------------------------------
def _cote(affirmation: Mapping[str, Any]) -> dict[str, Any]:
    return {k: affirmation[k] for k in ("ligne_id", "classe", "valeur", "ref", "emetteur", "horodatage")}


def identifiant(cle: str, ligne_a: str, ligne_b: str) -> str:
    return hashlib.sha256(f"{cle}|{ligne_a}|{ligne_b}".encode()).hexdigest()[:32]


def _raison(
    proposition: Mapping[str, Any], gauche: Mapping[str, Any], droite: Mapping[str, Any], ordre: verite.OrdreVerite
) -> str:
    if proposition["retenue"] is None:
        return (
            f"Deux sources de même rang (« {gauche['classe']} ») se contredisent : aucune proposition automatique, "
            "une personne doit trancher."
        )
    gagnant, perdant = (gauche, droite) if proposition["retenue"] == "a" else (droite, gauche)
    return (
        f"La source de classe « {gagnant['classe']} » (rang {ordre.rang(gagnant['classe']) + 1}) l'emporte sur "
        f"« {perdant['classe']} » (rang {ordre.rang(perdant['classe']) + 1}) selon l'ordre de vérité {ordre.version}."
    )


def detecter(
    liste_actives: Sequence[Mapping[str, Any]], connues: set[str], ordre: verite.OrdreVerite, horodatage: str
) -> list[dict[str, Any]]:
    """Les contradictions NOUVELLES entre affirmations actives : même clé, valeurs différentes. Les deux domaines ne se
    croisent jamais (le domaine fait partie de la clé). Tri stable, déterministe."""
    par_cle: dict[str, list[Mapping[str, Any]]] = {}
    for affirmation in liste_actives:
        par_cle.setdefault(cle_de(affirmation), []).append(affirmation)
    trouvees: list[dict[str, Any]] = []
    for cle in sorted(par_cle):
        groupe = sorted(par_cle[cle], key=lambda a: (ordre.rang(a["classe"]), a["ligne_id"]))
        for i, gauche in enumerate(groupe):
            for droite in groupe[i + 1 :]:
                if gauche["valeur"] == droite["valeur"]:
                    continue
                ident = identifiant(cle, gauche["ligne_id"], droite["ligne_id"])
                if ident in connues:
                    continue
                proposition = verite.resoudre(gauche, droite, gauche["attribut"], ordre)
                proposition["raison"] = _raison(proposition, gauche, droite, ordre)
                if proposition["critique"]:
                    traitement = "humain"
                elif proposition["retenue"] is not None:
                    traitement = "auto"
                else:
                    traitement = "ouverte"
                trouvees.append(
                    {
                        "type_entree": TYPE_DETECTEE,
                        "horodatage": horodatage,
                        "contradiction_id": ident,
                        "domaine": gauche["domaine"],
                        "cle": cle,
                        "attribut": gauche["attribut"],
                        "a": _cote(gauche),
                        "b": _cote(droite),
                        "critique": proposition["critique"],
                        "motifs_criticite": proposition["motifs_criticite"],
                        "proposition": {k: proposition[k] for k in ("retenue", "regle", "raison")},
                        "ordre_version": ordre.version,
                        "ordre_empreinte": ordre.empreinte,
                        "traitement": traitement,
                    }
                )
    return trouvees


def _marque(ident: str, ligne_id: str, marque: str, fondement: str, horodatage: str) -> dict[str, Any]:
    return {
        "type_entree": TYPE_MARQUE,
        "horodatage": horodatage,
        "contradiction_id": ident,
        "affirmation_ligne_id": ligne_id,
        "marque": marque,
        "fondement": fondement,
    }


def entrees_detection(detection: Mapping[str, Any]) -> list[dict[str, Any]]:
    """La détection, puis la marque de chacune des deux mémoires (deux entrées, dans cet ordre)."""
    ident, horodatage = detection["contradiction_id"], detection["horodatage"]
    ligne_a, ligne_b = detection["a"]["ligne_id"], detection["b"]["ligne_id"]
    if detection["traitement"] == "auto":
        retenue = detection["proposition"]["retenue"]
        marques = (MARQUE_RETENUE, MARQUE_DOMINEE) if retenue == "a" else (MARQUE_DOMINEE, MARQUE_RETENUE)
        fondement = FONDEMENT_ORDRE
    else:
        marques, fondement = (MARQUE_CONTESTEE, MARQUE_CONTESTEE), FONDEMENT_DETECTION
    return [
        dict(detection),
        _marque(ident, ligne_a, marques[0], fondement, horodatage),
        _marque(ident, ligne_b, marques[1], fondement, horodatage),
    ]


def entree_demande(contradiction_id: str, demande_id: str, horodatage: str) -> dict[str, Any]:
    return {
        "type_entree": TYPE_DEMANDE,
        "horodatage": horodatage,
        "contradiction_id": contradiction_id,
        "demande_id": demande_id,
    }


# ---------------------------------------------------------------------------------------------------------------
# 3. L'état, rejoué
# ---------------------------------------------------------------------------------------------------------------
def etats(
    maillons: Iterable[Mapping[str, Any]], liste_actives: Iterable[Mapping[str, Any]]
) -> dict[str, dict[str, Any]]:
    """`{contradiction_id: état}` rejoué : statut, marque de chaque mémoire, décision, demande d'approbation. Une
    contradiction dont l'une des deux affirmations n'est plus active est `caduque` (la question ne se pose plus ; la
    trace reste)."""
    actifs = {a["ligne_id"] for a in liste_actives}
    sortie: dict[str, dict[str, Any]] = {}
    for maillon in maillons:
        genre, ident = maillon.get("type_entree"), maillon.get("contradiction_id")
        if genre == TYPE_DETECTEE and ident not in sortie:
            sortie[ident] = {**maillon, "marques": {}, "decision": None, "demande_id": None}
        elif ident in sortie and genre == TYPE_MARQUE:
            sortie[ident]["marques"][maillon["affirmation_ligne_id"]] = maillon["marque"]
        elif ident in sortie and genre == TYPE_DEMANDE and sortie[ident]["demande_id"] is None:
            sortie[ident]["demande_id"] = maillon["demande_id"]
        elif ident in sortie and genre == TYPE_DECIDEE and sortie[ident]["decision"] is None:
            sortie[ident]["decision"] = {k: maillon[k] for k in ("decision", "motif", "par", "role", "horodatage")}
    for etat in sortie.values():
        if etat["a"]["ligne_id"] not in actifs or etat["b"]["ligne_id"] not in actifs:
            etat["statut"] = STATUT_CADUQUE
        elif etat["decision"] is not None:
            etat["statut"] = STATUT_DECIDEE
        else:
            etat["statut"] = {"auto": STATUT_AUTO, "humain": STATUT_HUMAIN}.get(etat["traitement"], STATUT_OUVERTE)
    return sortie


def marques_effectives(etat_par_id: Mapping[str, Mapping[str, Any]]) -> dict[str, str]:
    """La marque de chaque mémoire (ligne_id d'affirmation) : la plus sévère parmi les contradictions encore vivantes
    (`dominee` > `contestee` > `retenue` > `valide`). Une mémoire absente de ce dictionnaire n'est contestée par
    rien."""
    resultat: dict[str, str] = {}
    for etat in etat_par_id.values():
        if etat["statut"] == STATUT_CADUQUE:
            continue
        for ligne_id, marque in etat["marques"].items():
            if _PRIORITE_MARQUE[marque] >= _PRIORITE_MARQUE[resultat.get(ligne_id, MARQUE_VALIDE)]:
                resultat[ligne_id] = marque
    return resultat


def compter(etat_par_id: Mapping[str, Mapping[str, Any]]) -> dict[str, int]:
    compte = dict.fromkeys(statuts(), 0)
    for etat in etat_par_id.values():
        compte[etat["statut"]] += 1
    return compte


def a_demander(etat_par_id: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Les contradictions critiques qui ont une proposition et pas encore de demande d'approbation, tri stable."""
    return sorted(
        (
            dict(e)
            for e in etat_par_id.values()
            if e["statut"] == STATUT_HUMAIN and e["demande_id"] is None and e["proposition"]["retenue"] is not None
        ),
        key=lambda e: e["contradiction_id"],
    )


def sans_proposition(etat_par_id: Mapping[str, Mapping[str, Any]]) -> int:
    return sum(1 for e in etat_par_id.values() if e["statut"] == STATUT_HUMAIN and e["proposition"]["retenue"] is None)


def arguments_de_demande(etat: Mapping[str, Any]) -> dict[str, str]:
    """Les arguments EXACTS que la personne approuve : la proposition de l'ordre de vérité, rien d'autre."""
    return {
        "contradiction_id": etat["contradiction_id"],
        "decision": "retenir_a" if etat["proposition"]["retenue"] == "a" else "retenir_b",
        "motif": "Proposition de l'ordre de vérité (source de plus haute autorité retenue), à valider par une "
        "personne.",
    }


def preparer_decision(
    etat_par_id: Mapping[str, Mapping[str, Any]],
    contradiction_id: str,
    decision: str,
    motif: str,
    acteur: Mapping[str, str],
    horodatage: str,
) -> list[dict[str, Any]]:
    """Les entrées d'une décision HUMAINE (décision, puis la marque des deux mémoires). `ValueError("REJ-…: …")` ou
    verdict d'acteur invalide : rien n'est ajouté."""
    etat = etat_par_id.get(contradiction_id)
    if etat is None:
        raise _refus(REJ_INCONNUE, "contradiction introuvable")
    if decision not in decisions():
        raise _refus(REJ_DECISION, f"décision parmi {list(decisions())}")
    verdict = humain.verifier_ecriture(acteur.get("par"), acteur.get("role"), acteur.get("source"), motif, horodatage)
    if verdict is not None:
        raise _refus(verdict["code"], verdict["detail"])
    if etat["statut"] == STATUT_CADUQUE:
        raise _refus(REJ_CADUQUE, "une des deux affirmations n'est plus active : la question ne se pose plus")
    if etat["statut"] == STATUT_DECIDEE:
        raise _refus(REJ_DEJA_DECIDEE, "une personne a déjà décidé de cette contradiction (la décision est définitive)")
    ligne_a, ligne_b = etat["a"]["ligne_id"], etat["b"]["ligne_id"]
    marques = {
        "retenir_a": (MARQUE_RETENUE, MARQUE_DOMINEE),
        "retenir_b": (MARQUE_DOMINEE, MARQUE_RETENUE),
    }.get(decision, (MARQUE_VALIDE, MARQUE_VALIDE))
    return [
        {
            "type_entree": TYPE_DECIDEE,
            "horodatage": horodatage,
            "contradiction_id": contradiction_id,
            "decision": decision,
            "motif": motif.strip(),
            "par": acteur["par"],
            "role": acteur["role"],
            "source_decision": acteur["source"],
        },
        _marque(contradiction_id, ligne_a, marques[0], FONDEMENT_DECISION, horodatage),
        _marque(contradiction_id, ligne_b, marques[1], FONDEMENT_DECISION, horodatage),
    ]


def vue(etat: Mapping[str, Any]) -> dict[str, Any]:
    """Une contradiction pour la lecture : les deux côtés, la proposition, l'état, les marques. Aucune donnée
    personnelle ne s'y trouve (jetons, empreintes, classes)."""
    return {
        "contradiction_id": etat["contradiction_id"],
        "domaine": etat["domaine"],
        "cle": etat["cle"],
        "statut": etat["statut"],
        "critique": etat["critique"],
        "motifs_criticite": list(etat["motifs_criticite"]),
        "a": dict(etat["a"]),
        "b": dict(etat["b"]),
        "proposition": dict(etat["proposition"]),
        "marques": dict(etat["marques"]),
        "decision": etat["decision"],
        "demande_id": etat["demande_id"],
        "ordre_version": etat["ordre_version"],
        "detectee_le": etat["horodatage"],
    }
