"""Apprentissage continu gouverné : des LEÇONS candidates, mesurées hors ligne, promues par une personne, retirables.

Le cycle, sans raccourci :

    événements et registres de M10 ──(code déterministe)──► leçon PROPOSÉE ──► ÉVALUATION hors ligne
        ──► décision HUMAINE (N3) : canari (1 à 50 %) ──► promotion complète │ retour arrière │ refus

- **D'où viennent les leçons.** Jamais d'un modèle : du code les tire de ce que M10 a déjà mémorisé. Cinq genres :
  `ecart_materiau` (la quantité réellement utilisée s'écarte du prévu, M6 `variance_chantier`), `ecart_marge` (la
  marge réelle s'écarte de la marge prévue, M5 `rentabilite_chantier`), `refus_recurrent` (un outil est refusé avec le
  même code dans plusieurs affaires, faits candidats du POSTFLIGHT) et `rejets_soi` (la direction rejette de façon
  répétée les propositions automatiques d'une dimension du modèle de soi : une correction humaine) et
  `apprentissage_marketing` (M7-MEMOIRE : un contenu gagnant ou faible, un signal d'objection ou des avis défavorables
  reviennent sur des semaines distinctes, d'après les observations minimales que M7 annonce ; aucun texte de client).
- **Le texte est un gabarit du code, sans chiffre ni identifiant** (`texte_agent`) : les paramètres (facteur, décalage)
  sont des données structurées calculées en `Decimal`, jamais recopiées de tête dans une réponse.
- **Évaluation hors ligne, en deux parties.** (1) LA MESURE, pour un écart chiffré : le paramètre est ajusté sur les
  chantiers d'ENTRAÎNEMENT et mesuré sur des chantiers distincts, tenus à l'écart (partage par hachage de l'identifiant
  du chantier) : erreur avant, erreur après, pire dégradation d'un chantier. Pour un écart de matériau, seules les
  observations de la MÊME unité exacte sont comparées ; une leçon historique sans unité n'est pas évaluable et le dit
  (`unite_absente`). (2) LA GARDE DU GABARIT, pour toutes : le
  texte de la leçon est ajouté aux réponses de référence du corpus du gabarit commun du département visé, et le rapport
  est comparé à celui sans la leçon (aucune régression, aucun cas bloquant échoué de plus). La garde monte une instance
  fictive : elle ne peut pas tourner dans un appel d'outil (transaction ouverte) ; c'est l'opérateur qui la lance
  (`opsys-metier mnemo garde-lecon`). Une leçon sans mesure possible le dit (`amelioration_mesurable: false`).
- **Promotion.** `opsys.mnemo.promotion` (généralisation de la boucle de M1) : un canari à la fois, puis promotion, ou
  retour arrière ; la décision est HUMAINE, motivée, et exige une évaluation favorable faite sur le corpus de garde
  COURANT.
- **Aucune leçon ne s'applique seule.** Promouvoir une leçon la rend LISIBLE (`appliquer_a`, avec le tirage du canari) ;
  c'est un département qui la lit et l'applique, par ses propres règles.
- **Surveillance.** Après promotion, `surveiller` rejoue la leçon sur les chantiers terminés depuis : si elle dégrade,
  il le dit et conseille le retour arrière, que seule une personne décide.

Le journal est un registre append-only chaîné (celui de M10) ; l'état est toujours rejoué depuis lui. Module pur.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation
from typing import Any

from . import codes, promotion
from .codes import ErreurMnemo

TYPE_PROPOSEE = "lecon_proposee"
TYPE_EVALUATION = "lecon_evaluation"
TYPE_DECISION = "lecon_decision"
VERROU_REGISTRE = "m10-registre-lecons"

GENRES = ("ecart_materiau", "ecart_marge", "refus_recurrent", "rejets_soi", "apprentissage_marketing")
GENRES_CHIFFRES = ("ecart_materiau", "ecart_marge")
CHANTIERS_MIN = 6
ENTRAINEMENT_MIN = 4
TEST_MIN = 2
COHERENCE_MIN = Decimal("0.70")
ECART_MIN_RELATIF = Decimal("0.05")
AMELIORATION_MIN = Decimal("0.10")  # l'erreur mesurée doit baisser d'au moins 10 % de sa valeur d'avant
DEGRADATION_MAX = Decimal("0.50")  # un chantier ne perd pas plus de la moitié de l'erreur moyenne d'avant
AFFAIRES_MIN = 3
REJETS_MIN = 3
MOTIF_MIN, MOTIF_MAX = 10, 500
_QUANTUM = Decimal("0.0001")
_PERSONNE = re.compile(r"^[a-z][a-z0-9_.-]{1,63}$")
_AGENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9:._-]{1,63}$")
_DEPARTEMENT = re.compile(r"^m(0[1-9]|10)-[a-z][a-z0-9-]*$")
_ROLES = frozenset({"admin", "nathan_owner"})
_VOIES = frozenset({"appareil", "approbation", "cli"})
_CLE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:~-]{0,127}$")
_DECIMAL = re.compile(r"^-?[0-9]+(\.[0-9]+)?$")
TEXTES = {
    "ecart_materiau": (
        "Pour un matériau dont la quantité réellement utilisée s'écarte de façon répétée de la quantité "
        "prévue, ne reprends pas la quantité prévue telle quelle : applique le facteur d'ajustement "
        "sourcé que la leçon fournit, calculé par le code."
    ),
    "ecart_marge": (
        "La marge réelle des chantiers terminés s'écarte de façon répétée de la marge prévue : tiens compte "
        "du décalage sourcé que la leçon fournit, calculé par le code, et dis-le quand tu cites une marge "
        "prévue. À valider auprès d'un comptable (CPA) / professionnel qualifié."
    ),
    "refus_recurrent": (
        "Un outil de ce département est refusé de façon répétée avec le même code dans des affaires "
        "distinctes : avant de l'appeler, vérifie la condition que ce code nomme au lieu de réessayer."
    ),
    "rejets_soi": (
        "La direction rejette de façon répétée les propositions automatiques de cette dimension du modèle de "
        "soi : n'en propose pas sans une source solide, et laisse la question ouverte si elle l'est."
    ),
}


@dataclasses.dataclass(frozen=True)
class Ecart:
    """Une observation prévu / réel d'un chantier terminé, tirée d'un fait mémorisé (jamais saisie)."""

    chantier: str
    groupe: str
    prevu: Decimal
    reel: Decimal
    ligne_id: str
    quand: str
    unite: str | None = None


# -- observations tirées des registres de M10
# --------------------------------------------------------------------------------
def _dec(valeur: Any) -> Decimal | None:
    if not isinstance(valeur, str) or not _DECIMAL.fullmatch(valeur):
        return None
    try:
        return Decimal(valeur)
    except InvalidOperation:
        return None


def _unite_lecon(lecon: Mapping[str, Any]) -> str | None:
    """L'unité EXACTE déclarée par une leçon, ou `None` : aucune conversion, aucun synonyme, aucun défaut."""
    contenu = lecon.get("contenu")
    if not isinstance(contenu, Mapping):
        return None
    unite = contenu.get("unite")
    return unite if isinstance(unite, str) and unite.strip() else None


def ecarts_materiaux(maillons: Iterable[Mapping[str, Any]]) -> list[Ecart]:
    """Un écart prévu / réel par (chantier, matériau) : la dernière variance ÉVALUÉE de chaque `wct_id`. Une quantité
    prévue nulle ou une ligne sans unité cohérente n'est pas une observation."""
    derniere: dict[str, Mapping[str, Any]] = {}
    for m in maillons:
        if "statut_variance" in m and m.get("statut_variance") == "evaluee" and isinstance(m.get("lignes"), list):
            derniere[m["wct_id"]] = m
    sortie = []
    for wct_id, m in derniere.items():
        for ligne in m["lignes"]:
            prevu, reel = _dec(ligne.get("quantite_prevue")), _dec(ligne.get("quantite_reelle"))
            unite = ligne.get("unite")
            if (
                not isinstance(unite, str)
                or not unite.strip()
                or prevu is None
                or reel is None
                or prevu <= 0
                or reel < 0
            ):
                continue
            sortie.append(
                Ecart(wct_id, str(ligne["materiau"]), prevu, reel, m["ligne_id"], m["horodatage"], unite)
            )
    return sortie


def ecarts_marge(maillons: Iterable[Mapping[str, Any]]) -> list[Ecart]:
    """Un écart de marge par chantier : le plus grand `sequence` de chaque `wct_id`, si les DEUX marges sont
    chiffrées."""
    derniere: dict[str, Mapping[str, Any]] = {}
    for m in maillons:
        if "marge_reelle_cad" in m and "marge_prevue_cad" in m:
            courant = derniere.get(m["wct_id"])
            if courant is None or m["sequence"] >= courant["sequence"]:
                derniere[m["wct_id"]] = m
    sortie = []
    for wct_id, m in derniere.items():
        prevu, reel = _dec(m["marge_prevue_cad"]), _dec(m["marge_reelle_cad"])
        if prevu is not None and reel is not None:
            sortie.append(Ecart(wct_id, "marge", prevu, reel, m["ligne_id"], m["horodatage"]))
    return sortie


# -- ajustement et mesure
# ------------------------------------------------------------------------------------------------------
def cote(chantier: str) -> str:
    """`test` pour un tiers des chantiers (hachage de l'identifiant), `entrainement` pour les autres : stable et sans
    tirage au sort, donc rejouable ; un chantier n'est jamais à la fois dans les deux."""
    return (
        "test"
        if int(hashlib.sha256(("lecon-partage|" + chantier).encode()).hexdigest()[:8], 16) % 3 == 0
        else "entrainement"
    )


def _mediane(valeurs: Sequence[Decimal]) -> Decimal:
    tri = sorted(valeurs)
    n = len(tri)
    return tri[n // 2] if n % 2 else (tri[n // 2 - 1] + tri[n // 2]) / 2


def _q(valeur: Decimal) -> str:
    return str(valeur.quantize(_QUANTUM, rounding=ROUND_HALF_EVEN))


def _erreur(genre: str, e: Ecart, parametre: Decimal) -> Decimal | None:
    if genre == "ecart_materiau":
        return None if e.reel == 0 else abs(e.reel - e.prevu * parametre) / e.reel
    return abs(e.reel - (e.prevu + parametre))


NEUTRE = {"ecart_materiau": Decimal("1"), "ecart_marge": Decimal("0")}


def ajuster(genre: str, ecarts: Sequence[Ecart]) -> dict[str, Any] | None:
    """Ajuste le paramètre sur les chantiers d'ENTRAÎNEMENT. `None` : pas de leçon (support insuffisant, signe
    incohérent
    ou écart négligeable). Le résultat dit aussi pourquoi."""
    distincts = {e.chantier for e in ecarts}
    entrainement = [e for e in ecarts if cote(e.chantier) == "entrainement"]
    test = [e for e in ecarts if cote(e.chantier) == "test"]
    if (
        len(distincts) < CHANTIERS_MIN
        or len({e.chantier for e in entrainement}) < ENTRAINEMENT_MIN
        or len({e.chantier for e in test}) < TEST_MIN
    ):
        return {"lecon": False, "raison": "support_insuffisant", "chantiers": len(distincts)}
    if genre == "ecart_materiau":
        valeurs = [e.reel / e.prevu for e in entrainement]
        parametre, neutre = _mediane(valeurs), Decimal("1")
        cote_du_parametre = [v > neutre for v in valeurs] if parametre > neutre else [v < neutre for v in valeurs]
        negligeable = abs(parametre - neutre) < ECART_MIN_RELATIF
    else:
        valeurs = [e.reel - e.prevu for e in entrainement]
        parametre = _mediane(valeurs)
        cote_du_parametre = [v > 0 for v in valeurs] if parametre > 0 else [v < 0 for v in valeurs]
        echelle = _mediane([abs(e.prevu) for e in entrainement])
        negligeable = parametre == 0 or (echelle > 0 and abs(parametre) / echelle < ECART_MIN_RELATIF)
    if negligeable:
        return {"lecon": False, "raison": "ecart_negligeable"}
    coherence = Decimal(sum(cote_du_parametre)) / Decimal(len(valeurs))
    if coherence < COHERENCE_MIN:
        return {"lecon": False, "raison": "signe_incoherent", "coherence": _q(coherence)}
    return {
        "lecon": True,
        "parametre": _q(parametre),
        "coherence": _q(coherence),
        "chantiers": len(distincts),
        "entrainement": len({e.chantier for e in entrainement}),
        "test": len({e.chantier for e in test}),
    }


def mesurer(genre: str, parametre: str, ecarts: Sequence[Ecart]) -> dict[str, Any]:
    """Erreur moyenne sur les chantiers TENUS À L'ÉCART, sans puis avec la leçon : améliorée, régressée, inchangée."""
    p, neutre = Decimal(parametre), NEUTRE[genre]
    avant, apres, pires = [], [], []
    for e in ecarts:
        if cote(e.chantier) != "test":
            continue
        a, b = _erreur(genre, e, neutre), _erreur(genre, e, p)
        if a is None or b is None:
            continue
        avant.append(a)
        apres.append(b)
        pires.append(b - a)
    if len(avant) < TEST_MIN:
        return {"mesurable": False, "raison": "chantiers_de_test_insuffisants"}
    moy_avant, moy_apres = sum(avant) / len(avant), sum(apres) / len(apres)
    pire = max(pires)
    ameliore = moy_apres <= moy_avant * (1 - AMELIORATION_MIN) and pire <= moy_avant * DEGRADATION_MAX
    return {
        "mesurable": True,
        "chantiers_test": len(avant),
        "erreur_avant": _q(moy_avant),
        "erreur_apres": _q(moy_apres),
        "pire_degradation": _q(pire),
        "ameliore": ameliore,
        "regression": moy_apres > moy_avant or pire > moy_avant * DEGRADATION_MAX,
        "unite": "fraction du réel" if genre == "ecart_materiau" else "CAD",
    }


# -- état rejoué
# -------------------------------------------------------------------------------------------------------------------
@dataclasses.dataclass
class EtatLecons:
    lecons: dict[str, dict[str, Any]]
    evaluations: dict[str, dict[str, dict[str, Any]]]  # leçon -> {"mesure": dernière mesure, "gabarit": dernière garde}
    promotion: promotion.EtatPromotion
    decisions: dict[str, list[dict[str, Any]]]


def etat(registre: Any) -> EtatLecons:
    maillons = [m for m in registre.lire() if m.get("type_entree") in (TYPE_PROPOSEE, TYPE_EVALUATION, TYPE_DECISION)]
    lecons: dict[str, dict[str, Any]] = {}
    evaluations: dict[str, dict[str, dict[str, Any]]] = {}
    decisions: dict[str, list[dict[str, Any]]] = {}
    for m in maillons:
        if m["type_entree"] == TYPE_PROPOSEE:
            lecons.setdefault(m["lecon_id"], dict(m))
        elif m["lecon_id"] not in lecons:
            raise ErreurMnemo(codes.LECON_INCONNUE, "le journal juge une leçon qui n'existe pas")
        elif m["type_entree"] == TYPE_EVALUATION:
            evaluations.setdefault(m["lecon_id"], {})[m["partie"]] = dict(m)
        else:
            decisions.setdefault(m["lecon_id"], []).append(dict(m))
    rejoue = promotion.rejouer(
        maillons, type_proposition=TYPE_PROPOSEE, type_decision=TYPE_DECISION, cle_id="lecon_id", ordre_strict=False
    )
    return EtatLecons(lecons, evaluations, rejoue, decisions)


def lecon_id(genre: str, cible: str, cle: str, identite: Mapping[str, Any]) -> str:
    """Identité d'une leçon : ce qu'elle DIT (le paramètre, l'unité pour un matériau, l'outil et le code, la dimension),
    pas combien de chantiers l'appuient : de nouvelles observations qui redonnent le même paramètre et la même unité ne
    font pas une nouvelle leçon. La clé `materiau` reste inchangée ; l'unité est ajoutée à l'identité, pas à la clé."""
    canon = json.dumps([genre, cible, cle, identite], sort_keys=True, ensure_ascii=False)
    return "lc-" + hashlib.sha256(canon.encode("utf-8")).hexdigest()[:20]


def _instant(h: object) -> dt.datetime:
    try:
        i = dt.datetime.fromisoformat(h) if isinstance(h, str) else None
    except ValueError:
        i = None
    if i is None or i.tzinfo is None:
        raise ErreurMnemo(codes.HORODATAGE_INVALIDE, "horodatage ISO 8601 avec fuseau requis")
    return i


def _exiger_humain(acteur: Any, motif: Any, horodatage: Any) -> tuple[Any, str]:
    par, role, voie = (getattr(acteur, "par", None), getattr(acteur, "role", None), getattr(acteur, "source", None))
    if not (isinstance(par, str) and _PERSONNE.fullmatch(par) and role in _ROLES and voie in _VOIES):
        raise ErreurMnemo(
            codes.HUMAIN_REQUIS,
            "cette décision est humaine : une personne identifiée (admin ou "
            "propriétaire) par appareil, approbation ou CLI",
        )
    if not isinstance(motif, str) or not MOTIF_MIN <= len(motif.strip()) <= MOTIF_MAX:
        raise ErreurMnemo(codes.MOTIF_REQUIS, f"le motif est obligatoire : {MOTIF_MIN} à {MOTIF_MAX} caractères")
    _instant(horodatage)
    return acteur, motif.strip()


# -- extraction (écrit des propositions, jamais plus)
# ----------------------------------------------------------------------------
TEXTES_MARKETING = {
    "contenu_gagnant": (
        "Des contenus de ce canal ont amené des leads de façon répétée, sur des semaines distinctes : avant de "
        "proposer "
        "un nouveau contenu pour ce canal, relis les contenus gagnants cités par la leçon et garde ce qui les "
        "rend mesurables (lien de suivi, appel clair à demander une soumission) au lieu d'en inventer une autre forme."
    ),
    "contenu_faible": (
        "Des contenus de ce canal restent sans lead longtemps après leur export, de façon répétée : avant de "
        "proposer un "
        "nouveau contenu pour ce canal, vérifie le lien de suivi et l'appel à l'action, et dis que la cause est une "
        "hypothèse, pas un fait."
    ),
    "objection_frequente": (
        "Les avis signalent de façon répétée la même friction : n'y réponds jamais par une promesse, un prix ou un "
        "délai ; "
        "prépare la réponse avec le propriétaire, qui la valide avant toute publication."
    ),
    "avis_constate": (
        "Les avis récents penchent défavorablement de façon répétée : ne sollicite pas seulement les clients "
        "satisfaits "
        "et prépare les réponses pour validation humaine, sans jamais publier seule."
    ),
}


def _meme_cohorte(autre: Mapping[str, Any], genre: str, contenu: Mapping[str, Any]) -> bool:
    """Deux leçons d'écart de matériau ne se doublent que dans la MÊME unité ; les autres genres n'en ont pas."""
    if genre != "ecart_materiau":
        return True
    autre_contenu = autre.get("contenu")
    autre_unite = autre_contenu.get("unite") if isinstance(autre_contenu, Mapping) else None
    return autre_unite == contenu.get("unite")


def _proposer(
    registre: Any,
    st: EtatLecons,
    *,
    genre: str,
    cible: str,
    cle: str,
    contenu: dict[str, Any],
    identite: dict[str, Any],
    sources: list[str],
    par: str,
    horodatage: str,
    libelle: str,
    texte: str | None = None,
) -> tuple[str, str]:
    texte = texte if texte is not None else TEXTES[genre]
    if re.search(r"\d", texte):
        raise ErreurMnemo(codes.ENTREE_INVALIDE, "le texte destiné à l'agent ne porte aucun chiffre")
    ident = lecon_id(genre, cible, cle, identite)
    if ident in st.lecons:
        return "deja_connue", ident
    for autre_id, autre in st.lecons.items():
        if (
            autre["genre"] == genre
            and autre["cible"] == cible
            and autre["cle"] == cle
            and _meme_cohorte(autre, genre, contenu)
            and st.promotion.etats.get(autre_id) in ("proposee", "canari")
        ):
            return "en_cours", ident  # une décision attend déjà pour cette cohorte : on ne la double pas
    registre.ajouter(
        {
            "type_entree": TYPE_PROPOSEE,
            "horodatage": horodatage,
            "lecon_id": ident,
            "genre": genre,
            "cible": cible,
            "cle": cle,
            "contenu": contenu,
            "libelle": libelle,
            "texte_agent": texte,
            "sources": sources[:5],
            "propose_par": par,
        }
    )
    st.lecons[ident] = {"genre": genre, "cible": cible, "cle": cle, "contenu": contenu}
    st.promotion = promotion.rejouer(
        [m for m in registre.lire() if m.get("type_entree") in (TYPE_PROPOSEE, TYPE_DECISION)],
        type_proposition=TYPE_PROPOSEE,
        type_decision=TYPE_DECISION,
        cle_id="lecon_id",
    )
    return "proposee", ident


def extraire(
    registre: Any,
    *,
    ecarts_mat: Sequence[Ecart],
    ecarts_mar: Sequence[Ecart],
    refus: Sequence[Mapping[str, Any]],
    rejets: Sequence[Mapping[str, Any]],
    par: str,
    horodatage: str,
    marketing: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Tire les leçons candidates des observations et les écrit PROPOSÉES. Rien n'est évalué, rien n'est décidé."""
    if not isinstance(par, str) or not _AGENT.fullmatch(par):
        raise ErreurMnemo(codes.ENTREE_INVALIDE, "par : identifiant de l'auteur")
    _instant(horodatage)
    st = etat(registre)
    bilan: dict[str, Any] = {"proposees": [], "deja_connues": 0, "en_cours": 0, "sans_lecon": []}

    def note(resultat: tuple[str, str]) -> None:
        statut, ident = resultat
        if statut == "proposee":
            bilan["proposees"].append(ident)
        elif statut == "deja_connue":
            bilan["deja_connues"] += 1
        else:
            bilan["en_cours"] += 1

    for genre, cible, ecarts in (
        ("ecart_materiau", "m06-material-control", ecarts_mat),
        ("ecart_marge", "m05-financecore", ecarts_mar),
    ):
        groupes: dict[tuple[str, str | None], list[Ecart]] = {}
        for e in ecarts:
            # Valider avant de grouper ou trier : l'API Python accepte aussi des écarts construits directement.
            # Conserver toute unité valide telle quelle : `" pi "` reste distincte de `"pi"`.
            unite = e.unite if genre == "ecart_materiau" and isinstance(e.unite, str) and e.unite.strip() else None
            cohorte = (e.groupe, unite)
            groupes.setdefault(cohorte, []).append(e)
        for groupe, unite in sorted(groupes, key=lambda c: (c[0], c[1] or "")):
            if genre == "ecart_materiau" and not unite:
                bilan["sans_lecon"].append({"genre": genre, "cle": groupe, "raison": "unite_absente"})
                continue
            serie = groupes[(groupe, unite)]
            ajuste = ajuster(genre, serie)
            if ajuste is None or not ajuste["lecon"]:
                bilan["sans_lecon"].append(
                    {"genre": genre, "cle": groupe, "raison": ajuste["raison"] if ajuste else "?"}
                )
                continue
            if not _CLE.fullmatch(groupe):
                bilan["sans_lecon"].append({"genre": genre, "cle": "?", "raison": "cle_invalide"})
                continue
            contenu = {
                "parametre": ajuste["parametre"],
                "mode": "facteur" if genre == "ecart_materiau" else "decalage_cad",
                "chantiers": ajuste["chantiers"],
                "coherence": ajuste["coherence"],
                "empreinte_observations": hashlib.sha256(
                    json.dumps(
                        sorted([e.chantier, str(e.prevu), str(e.reel), e.unite or ""] for e in serie)
                    ).encode()
                ).hexdigest(),
            }
            identite = {"parametre": ajuste["parametre"]}
            if genre == "ecart_materiau":
                contenu["unite"] = unite
                identite["unite"] = unite
            sources = sorted({e.ligne_id for e in serie})
            note(
                _proposer(
                    registre,
                    st,
                    genre=genre,
                    cible=cible,
                    cle=groupe,
                    contenu=contenu,
                    identite=identite,
                    sources=sources,
                    par=par,
                    horodatage=horodatage,
                    libelle=f"{genre} « {groupe} » : paramètre {ajuste['parametre']}, {ajuste['chantiers']} chantiers",
                )
            )
    for r in refus:
        if r.get("affaires_distinctes", 0) >= AFFAIRES_MIN and _DEPARTEMENT.fullmatch(str(r.get("departement"))):
            contenu = {
                "outil": r["outil"],
                "code": r["code"],
                "affaires_distinctes": r["affaires_distinctes"],
                "observations": r["observations"],
            }
            cle = f"{r['outil']}|{r['code']}"
            note(
                _proposer(
                    registre,
                    st,
                    genre="refus_recurrent",
                    cible=r["departement"],
                    cle=cle,
                    contenu=contenu,
                    identite={"outil": r["outil"], "code": r["code"]},
                    sources=list(r.get("lignes", ())),
                    par=par,
                    horodatage=horodatage,
                    libelle=f"refus récurrent de {r['outil']} ({r['code']}) dans {r['affaires_distinctes']} affaires",
                )
            )
    for r in rejets:
        if r.get("rejets", 0) >= REJETS_MIN:
            contenu = {"dimension": r["dimension"], "rejets": r["rejets"], "cles_distinctes": r["cles_distinctes"]}
            note(
                _proposer(
                    registre,
                    st,
                    genre="rejets_soi",
                    cible="m10-memoire",
                    cle=r["dimension"],
                    contenu=contenu,
                    identite={"dimension": r["dimension"]},
                    sources=list(r.get("lignes", ())),
                    par=par,
                    horodatage=horodatage,
                    libelle=f"{r['rejets']} propositions rejetées par la direction pour la dimension {r['dimension']}",
                )
            )
    for g in marketing:
        genre_obs = g.get("genre_observation")
        if genre_obs not in TEXTES_MARKETING or g.get("semaines_distinctes", 0) < AFFAIRES_MIN:
            continue
        categorie = g.get("categorie")
        cle = ":".join(x for x in (genre_obs, str(g["canal"]), categorie) if x)
        if not _CLE.fullmatch(cle):
            bilan["sans_lecon"].append({"genre": "apprentissage_marketing", "cle": "?", "raison": "cle_invalide"})
            continue
        contenu = {
            "genre_observation": genre_obs, "canal": g["canal"], "categorie": categorie,
            "semaines_distinctes": g["semaines_distinctes"], "observations": g["observations"],
            "leads": g["leads"], "occurrences": g["occurrences"], "cles_mesure": list(g.get("cles_mesure", ())),
        }
        note(
            _proposer(
                registre,
                st,
                genre="apprentissage_marketing",
                cible="m07-marketing",
                cle=cle,
                contenu=contenu,
                identite={"genre_observation": genre_obs, "canal": g["canal"], "categorie": categorie},
                sources=list(g.get("lignes", ())),
                par=par,
                horodatage=horodatage,
                libelle=f"marketing : {genre_obs} sur {g['canal']}, {g['semaines_distinctes']} semaines distinctes",
                texte=TEXTES_MARKETING[genre_obs],
            )
        )
    return bilan


# -- évaluation hors ligne
# ----------------------------------------------------------------------------------------------------------
GardeGabarit = Callable[[str, str], dict[str, Any]]  # (département visé, texte de la leçon) -> comparaison au gabarit


def evaluer_mesure(
    registre: Any,
    ident: str,
    *,
    ecarts_mat: Sequence[Ecart],
    ecarts_mar: Sequence[Ecart],
    horodatage: str,
    par: str = "systeme",
) -> dict[str, Any]:
    """PREMIÈRE partie : la mesure sur les chantiers tenus à l'écart (genres chiffrés). Écrit le résultat. Pour un genre
    sans mesure chiffrée possible, écrit qu'il n'y en a pas (`amelioration_mesurable: false`) : ce n'est pas un échec,
    c'est une limite dite."""
    _instant(horodatage)
    st = etat(registre)
    lecon = st.lecons.get(ident)
    if lecon is None:
        raise ErreurMnemo(codes.LECON_INCONNUE, "leçon introuvable")
    genre = lecon["genre"]
    if genre in GENRES_CHIFFRES:
        if genre == "ecart_materiau":
            unite = _unite_lecon(lecon)
            if unite is None:
                mesure = {"mesurable": False, "raison": "unite_absente"}
            else:
                serie = [
                    e for e in ecarts_mat if e.groupe == lecon["cle"] and e.unite == unite
                ]
                mesure = mesurer(genre, lecon["contenu"]["parametre"], serie)
        else:
            serie = [e for e in ecarts_mar if e.groupe == lecon["cle"]]
            mesure = mesurer(genre, lecon["contenu"]["parametre"], serie)
    else:
        mesure = {"mesurable": False, "raison": "aucune mesure chiffrée possible hors ligne pour ce genre"}
    registre.ajouter(
        {
            "type_entree": TYPE_EVALUATION,
            "partie": "mesure",
            "horodatage": horodatage,
            "lecon_id": ident,
            "mesure": mesure,
            "amelioration_mesurable": bool(mesure["mesurable"]),
            "par": par,
        }
    )
    return {
        "lecon_id": ident,
        "partie": "mesure",
        "mesure": mesure,
        "amelioration_mesurable": bool(mesure["mesurable"]),
    }


def enregistrer_garde(
    registre: Any,
    ident: str,
    verdict: Mapping[str, Any],
    *,
    empreinte_garde: str,
    horodatage: str,
    par: str = "systeme",
) -> dict[str, Any]:
    """SECONDE partie : le verdict de la garde du gabarit commun (calculé hors transaction par `garde_gabarit`)."""
    _instant(horodatage)
    if ident not in etat(registre).lecons:
        raise ErreurMnemo(codes.LECON_INCONNUE, "leçon introuvable")
    registre.ajouter(
        {
            "type_entree": TYPE_EVALUATION,
            "partie": "gabarit",
            "horodatage": horodatage,
            "lecon_id": ident,
            "garde_gabarit": dict(verdict),
            "empreinte_garde": empreinte_garde,
            "par": par,
        }
    )
    return {
        "lecon_id": ident,
        "partie": "gabarit",
        "regressions": len(verdict.get("regressions", ())),
        "bloquants_nouveaux": list(verdict.get("bloquants_nouveaux", ())),
    }


def verdict_evaluation(st: EtatLecons, ident: str, empreinte_garde: str) -> dict[str, Any]:
    """Les deux parties réunies : `promouvable` et les raisons NOMMÉES de ce qui manque ou échoue."""
    genre = st.lecons[ident]["genre"]
    parties = st.evaluations.get(ident, {})
    raisons: list[str] = []
    mesure, garde = parties.get("mesure"), parties.get("gabarit")
    if genre == "ecart_materiau" and _unite_lecon(st.lecons[ident]) is None:
        raisons.append("unite_absente")
    if genre in GENRES_CHIFFRES:
        if mesure is None:
            raisons.append("mesure_manquante")
        elif not mesure["mesure"]["mesurable"]:
            raisons.append("amelioration_non_mesuree")
        elif mesure["mesure"]["regression"]:
            raisons.append("regression_mesuree")
        elif not mesure["mesure"]["ameliore"]:
            raisons.append("amelioration_insuffisante")
    if garde is None:
        raisons.append("garde_gabarit_manquante")
    elif garde["empreinte_garde"] != empreinte_garde:
        raisons.append("garde_gabarit_perimee")
    else:
        if garde["garde_gabarit"].get("regressions"):
            raisons.append("regression_gabarit")
        if garde["garde_gabarit"].get("bloquants_nouveaux"):
            raisons.append("cas_bloquant_echoue_en_plus")
    return {
        "promouvable": not raisons,
        "raisons": raisons,
        "amelioration_mesurable": bool(mesure and mesure["amelioration_mesurable"]),
        "mesure": None if mesure is None else mesure["mesure"],
        "garde_gabarit": None if garde is None else garde["garde_gabarit"],
    }


# -- décision humaine
# -----------------------------------------------------------------------------------------------------------------
def decider(
    registre: Any,
    ident: str,
    etape: str,
    *,
    acteur: Any,
    motif: str,
    horodatage: str,
    pourcentage: int | None = None,
    empreinte_garde: str,
) -> dict[str, Any]:
    """Une PERSONNE décide : canari, promotion, retour arrière ou refus. Canari et promotion exigent une évaluation
    favorable faite sur le corpus de garde COURANT (`empreinte_garde`)."""
    acteur, motif = _exiger_humain(acteur, motif, horodatage)
    if etape not in promotion.ETAPES:
        raise ErreurMnemo(codes.LECON_TRANSITION, f"étape inconnue « {etape} » : {list(promotion.ETAPES)}")
    if etape != "canari" and pourcentage is not None:
        raise ErreurMnemo(codes.LECON_CANARI, "le pourcentage ne vaut que pour le canari")
    st = etat(registre)
    if ident not in st.lecons:
        raise ErreurMnemo(codes.LECON_INCONNUE, "leçon introuvable")
    if etape in ("canari", "complete"):
        verdict = verdict_evaluation(st, ident, empreinte_garde)
        if not verdict["promouvable"]:
            absent = {"mesure_manquante", "garde_gabarit_manquante", "garde_gabarit_perimee"} & set(verdict["raisons"])
            raise ErreurMnemo(
                codes.LECON_NON_EVALUEE if absent else codes.LECON_REGRESSION,
                f"évaluation insuffisante ou défavorable : {verdict['raisons']} "
                "(mesure : m10_evaluer_lecon ; garde du gabarit : opsys-metier mnemo garde-lecon)",
            )
    entree: dict[str, Any] = {
        "type_entree": TYPE_DECISION,
        "horodatage": horodatage,
        "lecon_id": ident,
        "etape": etape,
        "par": acteur.par,
        "role": acteur.role,
        "source_decision": acteur.source,
        "motif": motif,
    }
    if pourcentage is not None:
        entree["pourcentage"] = pourcentage
    promotion.rejouer(
        [m for m in registre.lire() if m.get("type_entree") in (TYPE_PROPOSEE, TYPE_DECISION)] + [entree],
        type_proposition=TYPE_PROPOSEE,
        type_decision=TYPE_DECISION,
        cle_id="lecon_id",
    )
    registre.ajouter(entree)
    nouvel = etat(registre)
    return {
        "lecon_id": ident,
        "etat": nouvel.promotion.etats[ident],
        "canari": nouvel.promotion.canari,
        "actives": list(nouvel.promotion.pile),
    }


# -- lecture et application
# ---------------------------------------------------------------------------------------------------------------
def _publique(st: EtatLecons, ident: str, empreintes: Mapping[str, str] | None = None) -> dict[str, Any]:
    lc = st.lecons[ident]
    parties = st.evaluations.get(ident, {})
    return {
        "lecon_id": ident,
        "genre": lc["genre"],
        "cible": lc["cible"],
        "cle": lc["cle"],
        "libelle": lc["libelle"],
        "contenu": lc["contenu"],
        "texte_agent": lc["texte_agent"],
        "sources": lc["sources"],
        "etat": st.promotion.etats[ident],
        "propose_le": lc["horodatage"],
        "evaluation": {
            "mesure": parties["mesure"]["mesure"] if "mesure" in parties else None,
            "garde_gabarit": parties["gabarit"]["garde_gabarit"] if "gabarit" in parties else None,
            "evaluee_le": max((p["horodatage"] for p in parties.values()), key=_instant, default=None),
            "verdict": None
            if empreintes is None or lc["cible"] not in empreintes
            else {
                k: v
                for k, v in verdict_evaluation(st, ident, empreintes[lc["cible"]]).items()
                if k in ("promouvable", "raisons")
            },
        },
        "decisions": [
            {k: d[k] for k in ("etape", "par", "role", "motif", "horodatage")} for d in st.decisions.get(ident, [])
        ],
    }


def vue(registre: Any, *, genre: str | None = None, empreintes: Mapping[str, str] | None = None) -> dict[str, Any]:
    """La vue d'ensemble. `empreintes` (département visé -> empreinte du corpus de garde courant) permet de dire si
    chaque
    leçon est promouvable MAINTENANT ; sans elle, le verdict n'est pas calculé (il dépend du corpus courant)."""
    st = etat(registre)
    liste = [_publique(st, i, empreintes) for i in st.lecons if genre is None or st.lecons[i]["genre"] == genre]
    par_etat: dict[str, int] = {}
    for lc in liste:
        par_etat[lc["etat"]] = par_etat.get(lc["etat"], 0) + 1
    return {
        "lecons": liste,
        "par_etat": par_etat,
        "canari": st.promotion.canari,
        "actives": list(st.promotion.pile),
        "avertissement": (
            "Aucune leçon ne s'applique seule : une leçon promue est lisible par le département visé, "
            "qui décide de l'appliquer. Une leçon sans mesure hors ligne le dit."
        ),
    }


def appliquer_a(registre: Any, cible: str, cle_application: str) -> dict[str, Any]:
    """Les leçons promues du département `cible`, plus celle en canari SI `cle_application` tombe dans sa part. Une même
    clé reçoit toujours la même réponse (hachage stable). N'applique rien : le département lit et décide."""
    st = etat(registre)
    retenues = [i for i in st.promotion.pile if st.lecons[i]["cible"] == cible]
    canari = st.promotion.canari
    en_canari = None
    if canari is not None and st.lecons[canari[0]]["cible"] == cible:
        dedans = promotion.dans_le_canari(cle_application, canari[1], graine=canari[0])
        en_canari = {"lecon_id": canari[0], "pourcentage": canari[1], "dans_le_canari": dedans}
        if dedans:
            retenues.append(canari[0])
    return {
        "cible": cible,
        "cle_application": cle_application,
        "canari": en_canari,
        "lecons": [_publique(st, i) for i in retenues],
    }


def surveiller(registre: Any, ecarts_mat: Sequence[Ecart], ecarts_mar: Sequence[Ecart]) -> list[dict[str, Any]]:
    """Après promotion : rejoue chaque leçon chiffrée active sur les chantiers terminés DEPUIS sa promotion."""
    st = etat(registre)
    rapport = []
    for ident in st.promotion.pile:
        lc = st.lecons[ident]
        if lc["genre"] not in GENRES_CHIFFRES:
            continue
        promue = max((d["horodatage"] for d in st.decisions[ident] if d["etape"] == "complete"), key=_instant)
        if lc["genre"] == "ecart_materiau":
            unite = _unite_lecon(lc)
            if unite is None:
                rapport.append(
                    {
                        "lecon_id": ident,
                        "statut": "unite_absente",
                        "raison": "unite_absente",
                        "chantiers_depuis_promotion": 0,
                    }
                )
                continue
            serie = [
                e
                for e in ecarts_mat
                if e.groupe == lc["cle"] and e.unite == unite and _instant(e.quand) > _instant(promue)
            ]
        else:
            serie = [e for e in ecarts_mar if _instant(e.quand) > _instant(promue)]
        if len({e.chantier for e in serie}) < TEST_MIN:
            rapport.append({"lecon_id": ident, "statut": "insuffisant", "chantiers_depuis_promotion": len(serie)})
            continue
        p, neutre = Decimal(lc["contenu"]["parametre"]), NEUTRE[lc["genre"]]
        avant = [x for x in (_erreur(lc["genre"], e, neutre) for e in serie) if x is not None]
        apres = [x for x in (_erreur(lc["genre"], e, p) for e in serie) if x is not None]
        if not avant:
            rapport.append({"lecon_id": ident, "statut": "insuffisant", "chantiers_depuis_promotion": len(serie)})
            continue
        ma, mb = sum(avant) / len(avant), sum(apres) / len(apres)
        regresse = mb > ma
        rapport.append(
            {
                "lecon_id": ident,
                "statut": "regresse" if regresse else "ameliore" if mb < ma else "inchange",
                "erreur_sans_lecon": _q(ma),
                "erreur_avec_lecon": _q(mb),
                "chantiers_depuis_promotion": len(avant),
                "retour_arriere_conseille": regresse,
            }
        )
    return rapport
