"""Recommandation GOUVERNÉE d'Athéna : une proposition structurée dont chaque chiffre a une source, jamais une décision.

Module pur, sans horloge ni import d'``opsys``. Une recommandation (écrite par le conseil d'agents ou une personne) est
contrôlée AVANT d'être montrée à la direction ; elle est admise en bloc ou refusée avec un code ``REJ-RECO-…`` :

* M9 ne DÉCIDE jamais : le statut est ``PROPOSITION_NON_DECIDEE``, ``decision_prise_par_m9`` est faux, la direction
  valide ; un texte qui prétend une décision, un paiement, une signature ou un envoi fait est refusé ;
* M9 ne CALCULE jamais de tête : chaque chiffre vient (a) d'un fait cité d'une capture (adresse + valeur en texte
  exact), (b) d'un reçu du moteur de calcul de M5 dont les empreintes sont intactes et dont la valeur se lit à son
  chemin, ou (c) d'une hypothèse déclarée PAR LA DIRECTION. Tout autre chiffre — y compris dans un texte libre — est
  refusé ;
* le statut de certitude d'un fait cité est rejoué : un essai, un périmé ou une prévision déclaré « établi » est refusé
;
* M9 refuse l'INCONNU plutôt que d'estimer : une donnée manquante BLOQUANTE interdit de recommander une option (la
  recommandation s'abstient et dit pourquoi) ;
* tout avis comptable, fiscal, juridique ou d'investissement — déclaré OU impliqué par les sources citées (M5, santé de
  l'entreprise) — porte la mention « À valider auprès d'un comptable (CPA) / professionnel qualifié » et exige la
  validation d'un professionnel en plus de la direction.

Le contrôle ne dit rien de la VÉRITÉ : il garantit la forme, l'ancrage et l'honnêteté des statuts.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence

from . import certitude as ct
from . import conseil

SCHEMA = "opsys.m9.recommandation/v1"
STATUT = "PROPOSITION_NON_DECIDEE"
MENTION = ct.MENTION_CPA
DOMAINES_PROFESSIONNELS = frozenset({"comptable", "fiscal", "juridique", "financement", "investissement"})
VALIDATIONS = frozenset({"direction", "comptable_cpa", "juriste"})
_CHAMPS = frozenset(
    {
        "schema", "question", "domaines", "hypotheses", "options", "chiffres", "risques", "donnees_manquantes",
        "recommandation", "statut", "decision_prise_par_m9", "validation_requise", "mention_professionnelle",
    }
)  # fmt: skip
_IMPLIQUE_PAR_LECTURE = {"m5.": "comptable", "m8.synthese_direction": "comptable"}
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:\-]{0,63}")
_HEX = re.compile(r"[0-9a-f]{64}")
_ADRESSE = re.compile(r"[a-z0-9_.]+#\d+:p\d+\.[A-Za-z0-9_.\[\]]+")
_CHEMIN = re.compile(r"[A-Za-z0-9_]+(\[\d+\])?(\.[A-Za-z0-9_]+(\[\d+\])?)*")
# Un nombre dans un texte libre : groupes de milliers (espaces) ou entier nu, décimales facultatives. Plus strict que
# ``conseil.chiffres_libres`` (qui ne vise que montants, pourcentages et décimaux) : dans une recommandation, AUCUN
# nombre
# n'est libre. Les identifiants (c1, o2) sont écartés par la frontière de mot.
_NOMBRE_LIBRE = re.compile(r"(?<![\w.,])(?:\d{1,3}(?:[ \u00a0\u202f]\d{3})+|\d+)(?:[.,]\d+)?(?![\w])")
_DATE_ISO = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
_DECISION_PRETENDUE = re.compile(
    r"\b(j'ai|nous avons|c'est)\s+(décidé|décidée|approuvé|approuvée|autorisé|autorisée|signé|signée|payé|payée|"
    r"envoyé|envoyée|commandé|commandée|embauché)|décision (est )?prise|\bapprouvé par athéna\b",
    re.IGNORECASE,
)
MAX_TEXTE = 1200
MAX_ELEMENTS = 24


def _refus(code: str, detail: str) -> ValueError:
    return ValueError(f"REJ-RECO-{code} : {detail}")


def _texte(valeur: object, maximum: int = MAX_TEXTE) -> bool:
    return type(valeur) is str and bool(valeur.strip()) and len(valeur) <= maximum


def _liste(valeur: object, nom: str, minimum: int = 0) -> list:
    if type(valeur) is not list or not minimum <= len(valeur) <= MAX_ELEMENTS:
        raise _refus("FORME", f"{nom} : liste de {minimum} à {MAX_ELEMENTS} éléments")
    return valeur


# type: ignore[assignment]
def _element(brut: object, nom: str, champs: set[str], facultatifs: set[str] = frozenset()) -> Mapping:
    if not isinstance(brut, Mapping) or not champs <= set(brut) <= champs | set(facultatifs):
        raise _refus("FORME", f"{nom} : champs {sorted(champs)} requis (et {sorted(facultatifs)} permis)")
    if type(brut["id"]) is not str or not _ID.fullmatch(brut["id"]):
        raise _refus("FORME", f"{nom} : identifiant sobre requis")
    return brut


def domaines_impliques(chiffres: Sequence[Mapping]) -> set[str]:
    """Domaines professionnels IMPLIQUÉS par les sources citées, même si la recommandation ne les déclare pas."""
    impliques: set[str] = set()
    for chiffre in chiffres:
        source = chiffre.get("source", {})
        if source.get("genre") == "recu_m5":
            impliques.add("financement")
        elif source.get("genre") == "fait":
            lecture = str(source.get("adresse", "")).split("#", 1)[0]
            for prefixe, domaine in _IMPLIQUE_PAR_LECTURE.items():
                if lecture.startswith(prefixe):
                    impliques.add(domaine)
    return impliques


def _valeur_au_chemin(document: object, chemin: str) -> object:
    courant = document
    for morceau in chemin.split("."):
        rang = None
        trouve = re.fullmatch(r"([A-Za-z0-9_]+)(?:\[(\d+)\])?", morceau)
        if trouve is None:
            return None
        cle, rang = trouve.group(1), trouve.group(2)
        if not isinstance(courant, Mapping) or cle not in courant:
            return None
        courant = courant[cle]
        if rang is not None:
            if not isinstance(courant, list) or int(rang) >= len(courant):
                return None
            courant = courant[int(rang)]
    return courant


def nombres_libres(texte: str, valeurs_citees: Sequence[str]) -> list[str]:
    """Nombres d'un texte libre qui ne sont la valeur d'AUCUN chiffre cité ou hypothèse de la direction. Les dates ISO
    se
    comparent en texte exact aux valeurs citées ; tout le reste se compare en valeur décimale."""
    autorises: set = set()
    for valeur in valeurs_citees:
        autorises.update(conseil._nombre(m.group(0)) for m in _NOMBRE_LIBRE.finditer(valeur))
        autorises.add(conseil._nombre(valeur))
    dates = {d for valeur in valeurs_citees for d in _DATE_ISO.findall(valeur)}
    libres = [d for d in _DATE_ISO.findall(texte) if d not in dates]
    sans_dates = _DATE_ISO.sub(" ", texte)
    libres += [
        m.group(0).strip() for m in _NOMBRE_LIBRE.finditer(sans_dates) if conseil._nombre(m.group(0)) not in autorises
    ]
    return list(dict.fromkeys(libres))


def identifiant(reco: Mapping) -> str:
    return hashlib.sha256(json.dumps(reco, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def controler(
    reco: object,
    *,
    faits: Mapping[str, str],
    certitudes: Mapping[str, str],
    recus: Mapping[str, Mapping] | None = None,
    verifier_recu: Callable[[Mapping], tuple[bool, str]] | None = None,
) -> dict:
    """Admet ou refuse une recommandation. ``faits`` : adresse → texte exact des faits citables du dossier ;
    ``certitudes`` : adresse → statut (``certitude.certitude_des_faits``) ; ``recus`` : empreinte → reçu M5 fourni ;
    ``verifier_recu`` : le pont du socle (intégrité des empreintes). Lève ``ValueError('REJ-RECO-…')``."""
    if not isinstance(reco, Mapping) or set(reco) != _CHAMPS:
        raise _refus("FORME", f"champs exacts requis : {sorted(_CHAMPS)}")
    try:
        json.dumps(reco, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise _refus("FORME", "JSON fini requis") from exc
    if reco["schema"] != SCHEMA:
        raise _refus("FORME", f"schéma {SCHEMA} requis")
    if reco["statut"] != STATUT or reco["decision_prise_par_m9"] is not False:
        raise _refus("DECISION", "M9 ne décide jamais : statut PROPOSITION_NON_DECIDEE et decision_prise_par_m9 faux")
    if not _texte(reco["question"], 500):
        raise _refus("FORME", "question : texte de 500 caractères au plus")
    domaines = reco["domaines"]
    if type(domaines) is not list or not 1 <= len(domaines) <= 12 or len(set(map(str, domaines))) != len(domaines):
        raise _refus("FORME", "domaines : 1 à 12 domaines distincts")
    if not set(domaines) <= (conseil.DOMAINES | DOMAINES_PROFESSIONNELS):
        raise _refus("FORME", "domaines : vocabulaire fermé du conseil")

    # --- hypothèses : une valeur n'y entre que si la DIRECTION la déclare
    hypotheses: dict[str, Mapping] = {}
    for brute in _liste(reco["hypotheses"], "hypotheses"):
        h = _element(brute, "hypothese", {"id", "enonce", "source"}, {"valeur", "unite", "declaree_par"})
        if h["id"] in hypotheses or not _texte(h["enonce"]) or h["source"] not in ("direction", "modele"):
            raise _refus("FORME", "hypothese : identifiant distinct, énoncé et source (direction ou modele)")
        if "valeur" in h and (
            h["source"] != "direction" or type(h["valeur"]) is not str or not _texte(h.get("declaree_par"), 120)
        ):
            raise _refus("HYPOTHESE", "une valeur d'hypothèse est déclarée PAR LA DIRECTION (nom) en texte exact")
        hypotheses[h["id"]] = h

    # --- chiffres : source obligatoire et vérifiée
    chiffres: dict[str, Mapping] = {}
    recus_verifies: list[str] = []
    valeurs_citees: list[str] = [h["valeur"] for h in hypotheses.values() if "valeur" in h]
    for brut in _liste(reco["chiffres"], "chiffres"):
        c = _element(brut, "chiffre", {"id", "libelle", "valeur", "unite", "source", "certitude"})
        if c["id"] in chiffres or not _texte(c["libelle"], 200) or type(c["valeur"]) is not str or not c["valeur"]:
            raise _refus("FORME", "chiffre : identifiant distinct, libellé et valeur en texte exact")
        if not _texte(c["unite"], 32) or c["certitude"] not in ct.STATUTS:
            raise _refus("FORME", "chiffre : unité et statut de certitude du vocabulaire fermé")
        source = c["source"]
        genre = source.get("genre") if isinstance(source, Mapping) else None
        if genre == "fait":
            if set(source) != {"genre", "adresse"} or not _ADRESSE.fullmatch(str(source["adresse"])):
                raise _refus("CHIFFRE-SANS-SOURCE", f"{c['id']} : adresse de fait {{genre, adresse}} requise")
            adresse = source["adresse"]
            if adresse not in faits:
                raise _refus(
                    "CHIFFRE-FAIT-INCONNU", f"{c['id']} : aucun fait citable à cette adresse (ni nul, ni inventé)"
                )
            if faits[adresse] != c["valeur"]:
                raise _refus("CHIFFRE-VALEUR", f"{c['id']} : la valeur ne correspond pas mot pour mot au fait cité")
            reel = certitudes.get(adresse, ct.INDETERMINE)
            if c["certitude"] != reel:
                raise _refus(
                    "STATUT-FAUX",
                    f"{c['id']} : le fait cité est {reel} ; il ne peut pas être présenté comme {c['certitude']}",
                )
        elif genre == "recu_m5":
            if set(source) != {"genre", "empreinte", "chemin"} or not _HEX.fullmatch(str(source["empreinte"])):
                raise _refus("CHIFFRE-SANS-SOURCE", f"{c['id']} : reçu M5 {{genre, empreinte, chemin}} requis")
            if not _CHEMIN.fullmatch(str(source["chemin"])):
                raise _refus("CHIFFRE-SANS-SOURCE", f"{c['id']} : chemin de résultat illisible")
            recu = (recus or {}).get(source["empreinte"])
            if recu is None:
                raise _refus("CHIFFRE-RECU", f"{c['id']} : reçu de calcul absent (le moteur de M5 le produit)")
            if verifier_recu is None:
                raise _refus("CHIFFRE-RECU", "vérificateur de reçu non fourni : aucun reçu n'est admis")
            ok, raison = verifier_recu(recu)
            if not ok or recu.get("empreinte") != source["empreinte"]:
                raise _refus("CHIFFRE-RECU", f"{c['id']} : reçu invalide ou retouché ({raison[:120]})")
            lu = _valeur_au_chemin(recu.get("resultat"), source["chemin"])
            if type(lu) is not str or lu != c["valeur"]:
                raise _refus("CHIFFRE-VALEUR", f"{c['id']} : la valeur n'est pas celle du résultat du reçu à ce chemin")
            if c["certitude"] not in (ct.ETABLI, ct.ESSAI):
                raise _refus("STATUT-FAUX", f"{c['id']} : un résultat de reçu est ETABLI ou ESSAI_NON_APPROUVE")
            recus_verifies.append(source["empreinte"])
        elif genre == "hypothese":
            if (
                set(source) != {"genre", "ref"}
                or source["ref"] not in hypotheses
                or "valeur" not in hypotheses[source["ref"]]
            ):
                raise _refus(
                    "CHIFFRE-SANS-SOURCE", f"{c['id']} : hypothèse déclarée par la direction, avec valeur, requise"
                )
            if hypotheses[source["ref"]]["valeur"] != c["valeur"] or c["certitude"] != ct.ESSAI:
                raise _refus("STATUT-FAUX", f"{c['id']} : une hypothèse reprend sa valeur et reste ESSAI_NON_APPROUVE")
        else:
            raise _refus(
                "CHIFFRE-SANS-SOURCE", f"{c['id']} : aucune source (fait, recu_m5 ou hypothèse de la direction)"
            )
        chiffres[c["id"]] = c
        valeurs_citees.append(c["valeur"])
        if c["unite"] not in ("", "%"):
            valeurs_citees.append(f"{c['valeur']} {c['unite']}")

    # --- risques et données manquantes
    risques: dict[str, Mapping] = {}
    for brut in _liste(reco["risques"], "risques"):
        r = _element(brut, "risque", {"id", "enonce", "refs"})
        refs = r["refs"]
        if r["id"] in risques or not _texte(r["enonce"]) or type(refs) is not list or not 1 <= len(refs) <= 16:
            raise _refus("RISQUE-SANS-SOURCE", "risque : identifiant distinct, énoncé et au moins une référence")
        for ref in refs:
            if not (ref in chiffres or ref in hypotheses or ref in faits):
                raise _refus("RISQUE-SANS-SOURCE", f"{r['id']} : référence inconnue (chiffre, hypothèse ou fait cité)")
        risques[r["id"]] = r
    manquantes: dict[str, Mapping] = {}
    for brute in _liste(reco["donnees_manquantes"], "donnees_manquantes"):
        m = _element(brute, "donnee_manquante", {"id", "enonce", "proprietaire", "bloquante"})
        if (
            m["id"] in manquantes
            or not _texte(m["enonce"])
            or not _texte(m["proprietaire"], 64)
            or type(m["bloquante"]) is not bool
        ):
            raise _refus("FORME", "donnée manquante : identifiant distinct, énoncé, propriétaire, bloquante (booléen)")
        manquantes[m["id"]] = m

    # --- options et recommandation
    options: dict[str, Mapping] = {}
    for brute in _liste(reco["options"], "options", minimum=2):
        o = _element(brute, "option", {"id", "titre", "description", "chiffres", "risques"})
        if o["id"] in options or not _texte(o["titre"], 200) or not _texte(o["description"]):
            raise _refus("FORME", "option : identifiant distinct, titre et description")
        if not all(x in chiffres for x in o["chiffres"]) or not all(x in risques for x in o["risques"]):
            raise _refus("FORME", f"{o['id']} : chiffres et risques doivent exister")
        options[o["id"]] = o
    rec = reco["recommandation"]
    if (
        not isinstance(rec, Mapping)
        or set(rec) != {"option_id", "texte", "abstention_raison"}
        or not _texte(rec["texte"])
    ):
        raise _refus("FORME", "recommandation : {option_id, texte, abstention_raison}")
    if rec["option_id"] is None:
        if not _texte(rec["abstention_raison"], 600):
            raise _refus("ABSTENTION", "une abstention dit sa raison")
    else:
        if rec["option_id"] not in options or rec["abstention_raison"] is not None:
            raise _refus("FORME", "option recommandée inconnue, ou abstention_raison avec une option")
        bloquantes = sorted(i for i, m in manquantes.items() if m["bloquante"])
        if bloquantes:
            raise _refus(
                "RECOMMANDE-SUR-INCONNU",
                f"donnée(s) bloquante(s) manquante(s) {bloquantes} : s'abstenir plutôt qu'estimer",
            )

    # --- aucun chiffre libre, aucune décision prétendue
    textes = [h["enonce"] for h in hypotheses.values()] + [o["description"] for o in options.values()]
    textes += [r["enonce"] for r in risques.values()] + [m["enonce"] for m in manquantes.values()]
    textes += [rec["texte"]] + ([rec["abstention_raison"]] if rec["abstention_raison"] else [])
    textes += [o["titre"] for o in options.values()]
    for texte in textes:
        if _DECISION_PRETENDUE.search(texte):
            raise _refus("DECISION", "un texte prétend une décision ou un acte fait : M9 propose, la direction décide")
    conseil.exiger_chiffres_sources(textes, valeurs_citees)
    for texte in textes:
        libres = nombres_libres(texte, valeurs_citees)
        if libres:
            raise ValueError(
                f"{conseil.CODE_CHIFFRE_LIBRE} : {libres[:3]} n'est la valeur d'aucun chiffre cité ni d'aucune "
                "hypothèse de la direction ; citer la source plutôt que produire un nombre"
            )

    # --- professionnel qualifié et validations
    implicites = domaines_impliques(list(chiffres.values()))
    professionnels = (set(domaines) & DOMAINES_PROFESSIONNELS) | implicites
    validations = reco["validation_requise"]
    if type(validations) is not list or not set(validations) <= VALIDATIONS or "direction" not in validations:
        raise _refus(
            "VALIDATION", "validation_requise : la direction toujours, parmi direction, comptable_cpa, juriste"
        )
    if professionnels:
        if reco["mention_professionnelle"] != MENTION:
            raise _refus("MENTION", f"mention exacte requise pour {sorted(professionnels)} : « {MENTION} »")
        if professionnels - {"juridique"} and "comptable_cpa" not in validations:
            raise _refus(
                "VALIDATION", "un avis comptable, fiscal, de financement ou d'investissement exige comptable_cpa"
            )
        if "juridique" in professionnels and "juriste" not in validations:
            raise _refus("VALIDATION", "un avis juridique exige juriste")
    elif reco["mention_professionnelle"] not in (None, MENTION):
        raise _refus("MENTION", "mention professionnelle inconnue")
    return {
        "valide": True,
        "recommandation_id": identifiant(reco),
        "decision_prise_par_m9": False,
        "domaines_professionnels": sorted(professionnels),
        "domaines_impliques_par_les_sources": sorted(implicites),
        "chiffres": len(chiffres),
        "recus_verifies": sorted(set(recus_verifies)),
        "abstention": rec["option_id"] is None,
        "limites": [
            "Forme, ancrage et statuts contrôlés ; ni la vérité des sources ni la valeur du jugement ne le sont.",
            "Un reçu de calcul est contrôlé pour l'intégrité de ses empreintes ; son rejeu appartient à "
            "m5_verifier_recu_calcul.",
            MENTION,
        ],
    }
