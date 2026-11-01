"""Le PLAN DE CAMPAGNE PAYANTE : un brouillon que la direction approuve par son empreinte exacte, et que rien n'exécute.

Un plan dit : sur quel canal (Google Ads, Meta), pour quel objectif, avec quel budget (total, plafond quotidien,
durée, début), quel
ciblage GÉOGRAPHIQUE et par mots-clés, quels CRÉATIFS (des visuels déjà composés, contrôlés et APPROUVÉS par une
personne dans le
studio créatif, avec leurs textes français) et quelles règles d'arrêt PRÉPARÉES (`regles.py`). Son EMPREINTE (SHA-256
d'un JSON
canonique, créatifs vérifiés compris) est ce que la direction approuve : le moindre changement après l'approbation
donne une autre
empreinte et plus rien n'est approuvé.

Cycle (registre `plans_medias`, append-only à chaîne de hachage) : BROUILLON -> PRET_POUR_APPROBATION ->
LANCEMENT_APPROUVE_NON_EXECUTE,
ou RETIRE. L'approbation du lancement est un ENGAGEMENT DE DÉPENSE : N4, le propriétaire seulement, décidée par le
code d'outil
(`medias_outils.py`), jamais ici. Même approuvé, RIEN n'est lancé ni dépensé par OPSYS : la direction lance la
campagne dans la
plateforme (ou, pour Meta, passe par le sas social existant avec les publications préparées par
`dossier_de_lancement`). Aucun
connecteur de ce dépôt ne sait écrire chez une plateforme.

Fail-closed : un champ inconnu, un ciblage sur un critère protégé, un créatif non approuvé, un budget au-delà des
plafonds durs du
sas, un plan sans texte français, un texte qui promet un prix, une garantie ou un chiffre non sourcé, un nom de
concurrent dans un
mot-clé ou un texte : refus nommé, jamais une valeur corrigée en silence.

Module pur : aucune entrée-sortie propre (le journal est injecté), aucune horloge (le moment est un argument).
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any

from .. import journal_chaine
from ..sas_social.politique import PolitiqueSas
from ..site.schema_site import RATIO_ANGLAIS_MAX
from ..usine import controle_texte
from . import regles as regles_mod

REGISTRE = ("m07-marketing", "plans_medias")
CANAUX = ("google_ads", "meta")
OBJECTIFS = ("leads", "appels", "trafic_local")
LANGUES = ("fr-CA", "en-CA")
BROUILLON = "BROUILLON"
PRET = "PRET_POUR_APPROBATION"
APPROUVE = "LANCEMENT_APPROUVE_NON_EXECUTE"
RETIRE = "RETIRE"
M_CREE, M_REVISE, M_PRET, M_APPROUVE, M_RETIRE = (
    "plan_cree",
    "plan_revise",
    "plan_pret",
    "plan_lancement_approuve",
    "plan_retire",
)
NIVEAU_LANCEMENT = 4

# Critères sur lesquels une annonce ne cible JAMAIS (motifs de distinction illicites au Québec, catégories sensibles des
# plateformes).
CRITERES_INTERDITS = frozenset(
    {
        "age",
        "age_min",
        "age_max",
        "sexe",
        "genre",
        "religion",
        "origine",
        "origine_ethnique",
        "ethnie",
        "langue_maternelle",
        "orientation",
        "orientation_sexuelle",
        "sante",
        "handicap",
        "etat_civil",
        "grossesse",
        "revenu",
        "convictions",
        "affiliation_politique",
        "casier",
        "citoyennete",
    }
)
_CHAMPS_PLAN = (
    "nom",
    "canal",
    "objectif",
    "budget",
    "ciblage",
    "creatifs",
    "regles",
    "utm_campagne",
    "divulgation_texte_ia",
    "comptes_sas",
)
_CHAMPS_BUDGET = ("montant_total_cents", "plafond_quotidien_cents", "duree_jours", "date_debut")
_CHAMPS_CIBLAGE = ("zones", "rayon_km", "langues", "mots_cles", "mots_cles_negatifs")
_CLE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
_UTM = re.compile(r"^(fenetre|workflow|contenu)-[a-z0-9-]{1,60}-\d{4}$")
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,80}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")

Resolveur = Callable[[str], Mapping[str, Any]]
ControleMarques = Callable[[str], Sequence[str]]


def _refus(code: str, chemin: str, detail: str) -> dict[str, str]:
    return {"code": code, "chemin": chemin, "detail": detail}


def empreinte(plan: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(plan, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    ).hexdigest()


def identifiant(canal: str, cle: str) -> str:
    return "plan-" + hashlib.sha256(f"{canal}\x1f{cle}".encode()).hexdigest()[:16]


def _entier(v: Any, mini: int, maxi: int) -> bool:
    return type(v) is int and mini <= v <= maxi


def _liste_texte(valeur: Any, chemin: str, maxi: int, long_max: int, refus: list, *, minimum: int = 0) -> list[str]:
    if not isinstance(valeur, Sequence) or isinstance(valeur, (str, bytes)) or not minimum <= len(valeur) <= maxi:
        refus.append(_refus("REJ-PLAN-MEDIA-CHAMP", chemin, f"liste de {minimum} à {maxi} textes attendue"))
        return []
    sortie = []
    for i, t in enumerate(valeur):
        if not isinstance(t, str) or not 1 <= len(t.strip()) <= long_max or any(ord(c) < 32 for c in t):
            refus.append(
                _refus("REJ-PLAN-MEDIA-CHAMP", f"{chemin}[{i}]", f"texte de 1 à {long_max} caractères sans contrôle")
            )
        else:
            sortie.append(" ".join(t.split()))
    vus: set[str] = set()
    for i, t in enumerate(sortie):
        if t.casefold() in vus:
            refus.append(
                _refus("REJ-PLAN-MEDIA-CHAMP", f"{chemin}[{i}]", f"doublon : {t!r} (casse et espaces ignorés)")
            )
        vus.add(t.casefold())
    return sortie


def _controler_marques(texte: str, chemin: str, controle: ControleMarques | None, refus: list) -> None:
    if controle is not None:
        for motif in controle(texte):
            refus.append(_refus("REJ-PLAN-MEDIA-MARQUE-CONCURRENT", chemin, motif))


def _budget(brut: Any, politique: PolitiqueSas, aujourd_hui: date, refus: list) -> dict[str, Any] | None:
    if not isinstance(brut, Mapping) or set(brut) != set(_CHAMPS_BUDGET):
        refus.append(_refus("REJ-PLAN-MEDIA-CHAMP", "$.budget", f"champs exacts : {list(_CHAMPS_BUDGET)}"))
        return None
    n = len(refus)
    total, quotidien, duree = brut["montant_total_cents"], brut["plafond_quotidien_cents"], brut["duree_jours"]
    if not (_entier(total, 1, 10**9) and _entier(quotidien, 1, 10**9) and _entier(duree, 1, 90)):
        refus.append(
            _refus(
                "REJ-PLAN-MEDIA-BUDGET", "$.budget", "cents entiers > 0 et durée de 1 à 90 jours (jamais un flottant)"
            )
        )
    try:
        debut = date.fromisoformat(brut["date_debut"]) if isinstance(brut["date_debut"], str) else None
    except ValueError:
        debut = None
    if debut is None:
        refus.append(_refus("REJ-PLAN-MEDIA-BUDGET", "$.budget.date_debut", "date AAAA-MM-JJ attendue"))
    elif debut < aujourd_hui + timedelta(days=1):
        refus.append(
            _refus(
                "REJ-PLAN-MEDIA-DEBUT-PASSE",
                "$.budget.date_debut",
                "le début doit être au moins demain : le temps de la revue et de la décision de la direction",
            )
        )
    elif debut > aujourd_hui + timedelta(days=politique.horizon_max_jours):
        refus.append(
            _refus(
                "REJ-PLAN-MEDIA-DEBUT-LOINTAIN",
                "$.budget.date_debut",
                f"au plus {politique.horizon_max_jours} jours dans l'avenir",
            )
        )
    if len(refus) > n:
        return None
    if quotidien > politique.plafond_budget_quotidien_cents:
        refus.append(
            _refus(
                "REJ-PLAN-MEDIA-PLAFOND",
                "$.budget.plafond_quotidien_cents",
                f"{quotidien} cents par jour, plafond dur de {politique.plafond_budget_quotidien_cents}",
            )
        )
    if total > politique.plafond_budget_total_cents:
        refus.append(
            _refus(
                "REJ-PLAN-MEDIA-PLAFOND",
                "$.budget.montant_total_cents",
                f"{total} cents au total, plafond dur de {politique.plafond_budget_total_cents}",
            )
        )
    if total > quotidien * duree:
        refus.append(
            _refus(
                "REJ-PLAN-MEDIA-PLAFOND",
                "$.budget.montant_total_cents",
                "le montant dépasse le plafond quotidien multiplié par la durée : le budget ne tient pas dans ses "
                "limites",
            )
        )
    return {k: brut[k] for k in _CHAMPS_BUDGET}


def _ciblage(brut: Any, masqueur: Any, controle: ControleMarques | None, refus: list) -> dict[str, Any] | None:
    if not isinstance(brut, Mapping):
        refus.append(_refus("REJ-PLAN-MEDIA-CHAMP", "$.ciblage", "objet attendu"))
        return None
    interdits = sorted(k for k in brut if isinstance(k, str) and k.lower() in CRITERES_INTERDITS)
    if interdits:
        refus.append(
            _refus(
                "REJ-PLAN-MEDIA-CIBLAGE-INTERDIT",
                "$.ciblage",
                f"critère(s) interdit(s) : {interdits} — aucune annonce ne cible sur une caractéristique protégée "
                "ou sensible ; le ciblage est géographique et par mots-clés",
            )
        )
        return None
    inconnus = sorted(set(brut) - set(_CHAMPS_CIBLAGE))
    manquants = sorted({"zones", "langues"} - set(brut))
    if inconnus or manquants:
        refus.append(_refus("REJ-PLAN-MEDIA-CHAMP", "$.ciblage", f"champs inconnus {inconnus}, manquants {manquants}"))
        return None
    n = len(refus)
    zones = _liste_texte(brut["zones"], "$.ciblage.zones", 20, 60, refus, minimum=1)
    mots = _liste_texte(brut.get("mots_cles", []), "$.ciblage.mots_cles", 30, 60, refus)
    negatifs = _liste_texte(brut.get("mots_cles_negatifs", []), "$.ciblage.mots_cles_negatifs", 30, 60, refus)
    langues = brut["langues"]
    if (
        not isinstance(langues, Sequence)
        or isinstance(langues, (str, bytes))
        or "fr-CA" not in langues
        or len(set(langues)) != len(langues)
        or set(langues) - set(LANGUES)
    ):
        refus.append(
            _refus(
                "REJ-PLAN-MEDIA-FRANCAIS",
                "$.ciblage.langues",
                f"fr-CA obligatoire, parmi {list(LANGUES)}, sans doublon",
            )
        )
    rayon = brut.get("rayon_km")
    if rayon is not None and not _entier(rayon, 1, 100):
        refus.append(_refus("REJ-PLAN-MEDIA-CHAMP", "$.ciblage.rayon_km", "entier de 1 à 100 ou absent"))
    for i, mot in enumerate(mots):
        if masqueur.contient_pii(mot):
            refus.append(
                _refus(
                    "REJ-PLAN-MEDIA-PII",
                    f"$.ciblage.mots_cles[{i}]",
                    "un mot-clé ne porte aucun renseignement personnel",
                )
            )
        _controler_marques(mot, f"$.ciblage.mots_cles[{i}]", controle, refus)
    if len(refus) > n:
        return None
    return {
        "zones": zones,
        "rayon_km": rayon,
        "langues": sorted(langues),
        "mots_cles": mots,
        "mots_cles_negatifs": negatifs,
    }


def _creatifs(
    brut: Any, resolveur: Resolveur, politique: PolitiqueSas, controle: ControleMarques | None, refus: list
) -> list[dict[str, Any]] | None:
    if not isinstance(brut, Sequence) or isinstance(brut, (str, bytes)) or not 1 <= len(brut) <= 6:
        refus.append(_refus("REJ-PLAN-MEDIA-CHAMP", "$.creatifs", "1 à 6 créatifs attendus"))
        return None
    n = len(refus)
    sortie = []
    for i, c in enumerate(brut):
        chemin = f"$.creatifs[{i}]"
        if not isinstance(c, Mapping) or set(c) != {"actif_id", "textes"} or not isinstance(c["actif_id"], str):
            refus.append(_refus("REJ-PLAN-MEDIA-CHAMP", chemin, "{actif_id, textes} attendu"))
            continue
        media = resolveur(c["actif_id"])
        if not media.get("accepte"):
            detail = "; ".join(x.get("detail", "") for x in media.get("refus", []))[:300]
            refus.append(
                _refus(
                    "REJ-PLAN-MEDIA-CREATIF-NON-APPROUVE",
                    f"{chemin}.actif_id",
                    f"{c['actif_id']!r} n'est pas un visuel du studio approuvé par une personne : {detail}",
                )
            )
            continue
        if any(x["actif_id"] == c["actif_id"] for x in sortie):
            refus.append(
                _refus(
                    "REJ-PLAN-MEDIA-CHAMP",
                    f"{chemin}.actif_id",
                    "créatif en double : une publication de plus pour le même visuel",
                )
            )
            continue
        textes = _textes(c["textes"], f"{chemin}.textes", politique, controle, refus)
        if textes is None:
            continue
        sortie.append(
            {
                "actif_id": c["actif_id"],
                "empreinte_actif": media["empreinte_actif"],
                "media_sha256": media["media"]["sha256"],
                "textes": textes,
            }
        )
    return None if len(refus) > n else sortie


def _textes(
    brut: Any, chemin: str, politique: PolitiqueSas, controle: ControleMarques | None, refus: list
) -> list[dict[str, str]] | None:
    if not isinstance(brut, Sequence) or isinstance(brut, (str, bytes)) or not 1 <= len(brut) <= 2:
        refus.append(_refus("REJ-PLAN-MEDIA-CHAMP", chemin, "1 ou 2 textes (fr-CA, en-CA) attendus"))
        return None
    n = len(refus)
    sortie, longueurs = [], {}
    for i, t in enumerate(brut):
        c = f"{chemin}[{i}]"
        if (
            not isinstance(t, Mapping)
            or set(t) != {"langue", "titre", "description"}
            or t["langue"] not in LANGUES
            or not isinstance(t["titre"], str)
            or not isinstance(t["description"], str)
        ):
            refus.append(_refus("REJ-PLAN-MEDIA-CHAMP", c, "{langue, titre, description} attendu"))
            continue
        titre, description = " ".join(t["titre"].split()), " ".join(t["description"].split())
        if not 1 <= len(titre) <= 90 or not 1 <= len(description) <= 300:
            refus.append(_refus("REJ-PLAN-MEDIA-CHAMP", c, "titre de 1 à 90 et description de 1 à 300 caractères"))
            continue
        contexte = _contexte_texte(politique, 300)
        for champ_, texte in (("titre", titre), ("description", description)):
            for v in controle_texte.controler_texte(texte, contexte):
                refus.append(_refus(v.regle, f"{c}.{champ_}", v.detail))
            _controler_marques(texte, f"{c}.{champ_}", controle, refus)
        if t["langue"] in longueurs:
            refus.append(_refus("REJ-PLAN-MEDIA-CHAMP", c, "une seule version par langue"))
            continue
        longueurs[t["langue"]] = len(titre) + len(description)
        sortie.append({"langue": t["langue"], "titre": titre, "description": description})
    if "fr-CA" not in longueurs:
        refus.append(
            _refus(
                "REJ-PLAN-MEDIA-FRANCAIS",
                chemin,
                "une version fr-CA est obligatoire : le français d'abord (Charte "
                "de la langue française), jamais une annonce au Québec sans version française",
            )
        )
    elif "en-CA" in longueurs and longueurs["en-CA"] > longueurs["fr-CA"] * RATIO_ANGLAIS_MAX:
        refus.append(
            _refus(
                "REJ-PLAN-MEDIA-FRANCAIS",
                chemin,
                "la version anglaise dit plus que la française : le français doit rester nettement prédominant",
            )
        )
    return None if len(refus) > n else sorted(sortie, key=lambda x: x["langue"])


def _contexte_texte(politique: PolitiqueSas, longueur: int):
    return dataclasses.replace(politique.contexte_texte, longueur_max=longueur)


def normaliser(
    brut: Any,
    *,
    politique: PolitiqueSas,
    maintenant: datetime,
    resolveur: Resolveur,
    masqueur: Any,
    controle_marques: ControleMarques | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    """Le plan canonique (créatifs vérifiés auprès du studio) ou la liste complète des refus. Rien n'est corrigé."""
    if not isinstance(brut, Mapping):
        return None, [_refus("REJ-PLAN-MEDIA-CHAMP", "$", "objet attendu")]
    inconnus, manquants = (
        sorted(set(brut) - set(_CHAMPS_PLAN)),
        sorted(set(_CHAMPS_PLAN) - {"regles", "comptes_sas"} - set(brut)),
    )
    if inconnus or manquants:
        return None, [_refus("REJ-PLAN-MEDIA-CHAMP", "$", f"champs inconnus {inconnus}, manquants {manquants}")]
    refus: list[dict[str, str]] = []
    nom = brut["nom"]
    if (
        not isinstance(nom, str)
        or not 3 <= len(nom.strip()) <= 80
        or any(ord(c) < 32 for c in nom)
        or masqueur.contient_pii(nom)
    ):
        refus.append(
            _refus("REJ-PLAN-MEDIA-CHAMP", "$.nom", "libellé interne de 3 à 80 caractères sans renseignement personnel")
        )
    if brut["canal"] not in CANAUX:
        refus.append(_refus("REJ-PLAN-MEDIA-CHAMP", "$.canal", f"un de {list(CANAUX)} attendu"))
    if brut["objectif"] not in OBJECTIFS:
        refus.append(_refus("REJ-PLAN-MEDIA-CHAMP", "$.objectif", f"un de {list(OBJECTIFS)} attendu"))
    if not isinstance(brut["utm_campagne"], str) or not _UTM.fullmatch(brut["utm_campagne"]):
        refus.append(
            _refus("REJ-PLAN-MEDIA-CHAMP", "$.utm_campagne", "convention UTM gelée : (fenetre|workflow|contenu)-…-AAAA")
        )
    if type(brut["divulgation_texte_ia"]) is not bool:
        refus.append(
            _refus(
                "REJ-PLAN-MEDIA-CHAMP",
                "$.divulgation_texte_ia",
                "booléen : les textes ont-ils été rédigés avec une IA ?",
            )
        )
    budget = _budget(brut["budget"], politique, maintenant.date(), refus)
    ciblage = _ciblage(brut["ciblage"], masqueur, controle_marques, refus)
    creatifs = _creatifs(brut["creatifs"], resolveur, politique, controle_marques, refus)
    comptes = brut.get("comptes_sas", [])
    if (
        isinstance(comptes, Sequence)
        and not isinstance(comptes, (str, bytes))
        and len({(x.get("reseau"), x.get("compte")) for x in comptes if isinstance(x, Mapping)})
        != len([x for x in comptes if isinstance(x, Mapping)])
    ):
        refus.append(_refus("REJ-PLAN-MEDIA-CHAMP", "$.comptes_sas", "compte du sas en double"))
    if (
        not isinstance(comptes, Sequence)
        or isinstance(comptes, (str, bytes))
        or len(comptes) > 4
        or any(
            not isinstance(x, Mapping)
            or set(x) != {"reseau", "compte"}
            or x["reseau"] not in ("facebook", "instagram")
            or not isinstance(x["compte"], str)
            or not _ID.fullmatch(x["compte"])
            for x in comptes
        )
        or (comptes and brut["canal"] != "meta")
    ):
        refus.append(
            _refus(
                "REJ-PLAN-MEDIA-CHAMP",
                "$.comptes_sas",
                "comptes du sas social (facebook, instagram) : canal meta seulement, 4 au plus",
            )
        )
    if refus or budget is None:
        return None, refus
    regles, refus_regles = regles_mod.normaliser_regles(brut.get("regles"), budget)
    if regles is None:
        return None, refus_regles
    plan = {
        "nom": " ".join(brut["nom"].split()),
        "canal": brut["canal"],
        "objectif": brut["objectif"],
        "budget": budget,
        "ciblage": ciblage,
        "creatifs": creatifs,
        "regles": regles,
        "utm_campagne": brut["utm_campagne"],
        "divulgation_texte_ia": brut["divulgation_texte_ia"],
        "comptes_sas": sorted(
            ({"reseau": x["reseau"], "compte": x["compte"]} for x in comptes), key=lambda x: (x["reseau"], x["compte"])
        ),
    }
    return plan, []


# -- registre
# ------------------------------------------------------------------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class EtatPlan:
    plan_id: str
    etat: str
    revision: int
    plan: Mapping[str, Any]
    empreinte: str
    cle_idempotence: str
    decision: Mapping[str, Any] | None = None


def charger(journal: Sequence[Any]) -> tuple[dict[str, EtatPlan], dict[str, Any] | None]:
    problemes = journal_chaine.verifier(journal)
    if problemes:
        return {}, {"accepte": False, "refus": [_refus("REJ-PLAN-MEDIA-JOURNAL-ALTERE", "$", "; ".join(problemes[:3]))]}
    etats: dict[str, EtatPlan] = {}
    for m in journal:
        t, pid = m["type"], m["plan_id"]
        if t == M_CREE:
            etats[pid] = EtatPlan(pid, BROUILLON, 1, m["plan"], m["empreinte"], m["cle_idempotence"])
        elif t == M_REVISE:
            c = etats[pid]
            etats[pid] = dataclasses.replace(
                c, etat=BROUILLON, revision=c.revision + 1, plan=m["plan"], empreinte=m["empreinte"], decision=None
            )
        elif t == M_PRET:
            etats[pid] = dataclasses.replace(etats[pid], etat=PRET)
        elif t == M_APPROUVE:
            etats[pid] = dataclasses.replace(etats[pid], etat=APPROUVE, decision=m["decision"])
        elif t == M_RETIRE:
            etats[pid] = dataclasses.replace(etats[pid], etat=RETIRE)
    return etats, None


def _etat(tous: Mapping[str, EtatPlan], plan_id: Any) -> EtatPlan | dict[str, Any]:
    courant = tous.get(plan_id) if isinstance(plan_id, str) else None
    if courant is None:
        return {
            "accepte": False,
            "refus": [_refus("REJ-PLAN-MEDIA-INCONNU", "$.plan_id", f"plan inconnu : {plan_id!r}")],
        }
    return courant


def composer(
    journal: Any,
    brut: Any,
    cle_idempotence: Any,
    par: str,
    horodatage: str,
    *,
    politique: PolitiqueSas,
    maintenant: datetime,
    resolveur: Resolveur,
    masqueur: Any,
    controle_marques: ControleMarques | None = None,
    plan_id: str | None = None,
) -> dict[str, Any]:
    """Crée un brouillon, ou en révise un (`plan_id`). Même clé et même contenu : le même plan (`deja_cree`)."""
    tous, refus_journal = charger(journal)
    if refus_journal is not None:
        return refus_journal
    if not isinstance(cle_idempotence, str) or not _CLE.fullmatch(cle_idempotence):
        return {
            "accepte": False,
            "refus": [_refus("REJ-PLAN-MEDIA-CLE", "$.cle_idempotence", "16 à 64 caractères [A-Za-z0-9_-]")],
        }
    plan, refus = normaliser(
        brut,
        politique=politique,
        maintenant=maintenant,
        resolveur=resolveur,
        masqueur=masqueur,
        controle_marques=controle_marques,
    )
    if plan is None:
        return {"accepte": False, "refus": refus}
    marque = empreinte(plan)
    if plan_id is not None:
        courant = _etat(tous, plan_id)
        if isinstance(courant, dict):
            return courant
        if courant.etat in (APPROUVE, RETIRE):
            return {
                "accepte": False,
                "refus": [
                    _refus(
                        "REJ-PLAN-MEDIA-ETAT",
                        "$.plan_id",
                        f"plan {courant.etat} : on n'en révise pas : en créer un autre",
                    )
                ],
            }
        if courant.plan["canal"] != plan["canal"]:
            return {
                "accepte": False,
                "refus": [_refus("REJ-PLAN-MEDIA-IDENTITE", "$.canal", "le canal d'un plan ne change pas")],
            }
        if courant.empreinte == marque:
            return {
                "accepte": True,
                "plan_id": plan_id,
                "etat": courant.etat,
                "empreinte": marque,
                "revision": courant.revision,
                "deja_cree": True,
            }
        journal_chaine.ajouter(
            journal,
            M_REVISE,
            {"plan_id": plan_id, "plan": plan, "empreinte": marque, "par": par, "etat_avant": courant.etat},
            horodatage,
        )
        return {
            "accepte": True,
            "plan_id": plan_id,
            "etat": BROUILLON,
            "empreinte": marque,
            "revision": courant.revision + 1,
            "deja_cree": False,
        }
    pid = identifiant(plan["canal"], cle_idempotence)
    existant = tous.get(pid)
    if existant is not None:
        if existant.empreinte != marque:
            return {
                "accepte": False,
                "refus": [
                    _refus(
                        "REJ-PLAN-MEDIA-CLE-CONFLIT",
                        "$.cle_idempotence",
                        "cette clé désigne déjà un plan au contenu différent : une clé, un plan "
                        f"({pid}) ; pour le modifier, le réviser par son identifiant",
                    )
                ],
            }
        return {
            "accepte": True,
            "plan_id": pid,
            "etat": existant.etat,
            "empreinte": marque,
            "revision": existant.revision,
            "deja_cree": True,
        }
    journal_chaine.ajouter(
        journal,
        M_CREE,
        {"plan_id": pid, "plan": plan, "empreinte": marque, "cle_idempotence": cle_idempotence, "par": par},
        horodatage,
    )
    return {"accepte": True, "plan_id": pid, "etat": BROUILLON, "empreinte": marque, "revision": 1, "deja_cree": False}


def revalider(
    courant: EtatPlan,
    *,
    politique: PolitiqueSas,
    maintenant: datetime,
    resolveur: Resolveur,
    masqueur: Any,
    controle_marques: ControleMarques | None = None,
) -> list[dict[str, str]]:
    """Refait TOUS les contrôles sur le plan enregistré, au moment de la soumission ou de la décision : un visuel
    révoqué ou
    modifié depuis, une date devenue passée, un concurrent déclaré depuis : refus. L'empreinte des créatifs doit
    être la même."""
    brut = {
        **courant.plan,
        "creatifs": [{"actif_id": c["actif_id"], "textes": c["textes"]} for c in courant.plan["creatifs"]],
        "regles": [
            {
                k: v
                for k, v in x.items()
                if k
                in ("type", "seuil_cents", "conversions_min", "fenetre_jours", "ratio_pct", "minimum_cents", "action")
            }
            for x in courant.plan["regles"]
            if not x["obligatoire"]
        ],
    }
    plan, refus = normaliser(
        brut,
        politique=politique,
        maintenant=maintenant,
        resolveur=resolveur,
        masqueur=masqueur,
        controle_marques=controle_marques,
    )
    if plan is None:
        return refus
    if empreinte(plan) != courant.empreinte:
        return [
            _refus(
                "REJ-PLAN-MEDIA-CREATIF-CHANGE",
                "$.creatifs",
                "un visuel du studio a changé depuis la rédaction du plan : le réviser pour figer l'état actuel",
            )
        ]
    return []


def soumettre(journal: Any, plan_id: str, par: str, horodatage: str, **controles: Any) -> dict[str, Any]:
    tous, refus_journal = charger(journal)
    if refus_journal is not None:
        return refus_journal
    courant = _etat(tous, plan_id)
    if isinstance(courant, dict):
        return courant
    if courant.etat == PRET:
        return {"accepte": True, "plan_id": plan_id, "etat": PRET, "empreinte": courant.empreinte, "deja_soumis": True}
    if courant.etat != BROUILLON:
        return {
            "accepte": False,
            "refus": [_refus("REJ-PLAN-MEDIA-ETAT", "$.plan_id", f"plan {courant.etat} : seul un brouillon se soumet")],
        }
    refus = revalider(courant, **controles)
    if refus:
        return {"accepte": False, "refus": refus}
    journal_chaine.ajouter(
        journal, M_PRET, {"plan_id": plan_id, "empreinte": courant.empreinte, "par": par}, horodatage
    )
    return {"accepte": True, "plan_id": plan_id, "etat": PRET, "empreinte": courant.empreinte, "deja_soumis": False}


def approuver_lancement(
    journal: Any, plan_id: str, empreinte_voulue: Any, decision: Mapping[str, str], horodatage: str, **controles: Any
) -> dict[str, Any]:
    """L'ENGAGEMENT DE DÉPENSE (N4) : consigne la décision de la direction sur l'empreinte EXACTE. N'exécute rien."""
    tous, refus_journal = charger(journal)
    if refus_journal is not None:
        return refus_journal
    courant = _etat(tous, plan_id)
    if isinstance(courant, dict):
        return courant
    if courant.etat == APPROUVE:
        if courant.empreinte == empreinte_voulue:
            return {
                "accepte": True,
                "plan_id": plan_id,
                "etat": APPROUVE,
                "deja_approuve": True,
                "empreinte": courant.empreinte,
            }
        return {
            "accepte": False,
            "refus": [
                _refus("REJ-PLAN-MEDIA-EMPREINTE", "$.empreinte", "empreinte différente de celle du plan approuvé")
            ],
        }
    if courant.etat != PRET:
        return {
            "accepte": False,
            "refus": [
                _refus(
                    "REJ-PLAN-MEDIA-ETAT",
                    "$.plan_id",
                    f"plan {courant.etat} : seul un plan soumis (prêt pour approbation) se décide",
                )
            ],
        }
    if (
        not isinstance(empreinte_voulue, str)
        or not _SHA.fullmatch(empreinte_voulue)
        or empreinte_voulue != courant.empreinte
    ):
        return {
            "accepte": False,
            "refus": [
                _refus(
                    "REJ-PLAN-MEDIA-EMPREINTE",
                    "$.empreinte",
                    "l'empreinte approuvée doit être celle du plan actuel (une révision change l'empreinte)",
                )
            ],
        }
    refus = revalider(courant, **controles)
    if refus:
        return {"accepte": False, "refus": refus}
    journal_chaine.ajouter(
        journal,
        M_APPROUVE,
        {
            "plan_id": plan_id,
            "empreinte": courant.empreinte,
            "decision": dict(decision),
            "niveau": NIVEAU_LANCEMENT,
            "creatifs_verifies": [
                {"actif_id": c["actif_id"], "empreinte_actif": c["empreinte_actif"]} for c in courant.plan["creatifs"]
            ],
        },
        horodatage,
    )
    return {
        "accepte": True,
        "plan_id": plan_id,
        "etat": APPROUVE,
        "empreinte": courant.empreinte,
        "deja_approuve": False,
    }


def retirer(journal: Any, plan_id: str, par: str, motif: str, horodatage: str) -> dict[str, Any]:
    tous, refus_journal = charger(journal)
    if refus_journal is not None:
        return refus_journal
    courant = _etat(tous, plan_id)
    if isinstance(courant, dict):
        return courant
    if courant.etat == RETIRE:
        return {"accepte": True, "plan_id": plan_id, "etat": RETIRE, "deja_retire": True}
    journal_chaine.ajouter(
        journal,
        M_RETIRE,
        {"plan_id": plan_id, "par": par, "motif": motif[:300], "etat_avant": courant.etat},
        horodatage,
    )
    return {
        "accepte": True,
        "plan_id": plan_id,
        "etat": RETIRE,
        "deja_retire": False,
        "avertissement": "retirer le plan ne rappelle pas une campagne déjà lancée par la direction dans la plateforme"
        if courant.etat == APPROUVE
        else None,
    }


def lire(journal: Any, plan_id: str | None = None, etat: str | None = None, limite: int = 20) -> dict[str, Any]:
    tous, refus_journal = charger(journal)
    if refus_journal is not None:
        return refus_journal
    if plan_id is not None:
        courant = _etat(tous, plan_id)
        if isinstance(courant, dict):
            return courant
        return {"accepte": True, "plan": _vue(courant, detail=True)}
    choisis = [p for p in tous.values() if etat is None or p.etat == etat]
    return {
        "accepte": True,
        "total": len(choisis),
        "plans": [_vue(p) for p in choisis[:limite]],
        "reste": max(0, len(choisis) - limite),
    }


def _vue(p: EtatPlan, detail: bool = False) -> dict[str, Any]:
    base = {
        "plan_id": p.plan_id,
        "etat": p.etat,
        "revision": p.revision,
        "empreinte": p.empreinte,
        "nom": p.plan["nom"],
        "canal": p.plan["canal"],
        "budget": p.plan["budget"],
    }
    if detail:
        base |= {
            "plan": p.plan,
            "decision": p.decision,
            "executee_par_opsys": False,
            "statut_lancement": "AUCUNE_DEPENSE_PAR_OPSYS : la direction lance la campagne dans la plateforme",
        }
    return base


def dossier_de_lancement(courant: EtatPlan, medias_sas: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Ce que la direction fait À LA MAIN pour lancer le plan approuvé : étapes, plafonds à saisir dans la
    plateforme, et, pour
    Meta, les publications d'annonce PAYANTE préparées pour le sas social (`m7_composer_publication_sociale`, puis N4
    `m7_demander_annonce_payante`). Rien n'est soumis ni exécuté ici."""
    plan = courant.plan
    b = plan["budget"]
    etapes = [
        f"Dans la plateforme ({plan['canal']}), créer la campagne « {plan['nom']} » "
        f"avec l'objectif « {plan['objectif']} ».",
        f"Régler le budget quotidien à {b['plafond_quotidien_cents'] / 100:.2f} $ CAD au maximum "
        f"et la durée à {b['duree_jours']} "
        f"jours à partir du {b['date_debut']} ; le total ne dépasse pas {b['montant_total_cents'] / 100:.2f} $ CAD.",
        "Cibler les zones et mots-clés du plan, en français ; ne rien ajouter au ciblage (aucun critère protégé).",
        f"Utiliser le paramètre de campagne UTM « {plan['utm_campagne']} » sur les liens (convention gelée).",
        "Après le lancement, consigner la référence de campagne de la plateforme pour que M7 évalue les règles d'arrêt "
        "(m7_evaluer_regles_media).",
    ]
    publications = []
    for compte in plan["comptes_sas"]:
        for creatif in plan["creatifs"]:
            media = medias_sas.get(creatif["actif_id"])
            texte_fr = next(t for t in creatif["textes"] if t["langue"] == "fr-CA")
            if media is None:
                continue
            publications.append(
                {
                    "reseau": compte["reseau"],
                    "compte": compte["compte"],
                    "texte": texte_fr["description"],
                    "titre": None,
                    "medias": [media],
                    "planifie_le": f"{b['date_debut']}T13:00:00Z",
                    "divulgation": {
                        "texte_ia": plan["divulgation_texte_ia"],
                        "media_synthetique_realiste": bool(media.get("realiste")),
                        "contenu_commercial": True,
                    },
                    "type_publication": "annonce_payante",
                    "budget": {
                        "montant_cents": b["montant_total_cents"],
                        "plafond_quotidien_cents": b["plafond_quotidien_cents"],
                        "duree_jours": b["duree_jours"],
                    },
                    "options": {},
                }
            )
    return {
        "plan_id": courant.plan_id,
        "empreinte": courant.empreinte,
        "etapes_manuelles": etapes,
        "regles_preparees": [{k: v for k, v in x.items() if k not in ("statut",)} for x in plan["regles"]],
        "publications_sas_preparees": publications,
        "avertissement": "Rien n'a été lancé, soumis ni dépensé par OPSYS. Les règles d'arrêt sont des propositions de "
        "pause évaluées sur des chiffres lus ; elles ne s'exécutent pas.",
    }


__all__ = [
    "APPROUVE",
    "BROUILLON",
    "CANAUX",
    "CRITERES_INTERDITS",
    "EtatPlan",
    "NIVEAU_LANCEMENT",
    "OBJECTIFS",
    "PRET",
    "REGISTRE",
    "RETIRE",
    "approuver_lancement",
    "charger",
    "composer",
    "dossier_de_lancement",
    "empreinte",
    "identifiant",
    "lire",
    "normaliser",
    "retirer",
    "revalider",
    "soumettre",
]
