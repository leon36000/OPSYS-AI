"""Cash libre réel (M5.5 et M5.14, PLAN T4.16 ; DEFINITION-PRODUIT §7 M5, « Solde bancaire ≠ argent disponible »).

    cash libre = solde du registre
                 - TPS/TVQ à remettre - paies - DAS - comptes à payer - dettes - réserves critiques

« Le système n'affiche jamais un cash disponible sans soustraire les obligations connues. » Ce module pur (ADR-0009,
même règle que `facturation.py` : aucune horloge, aucun réseau, aucun import `opsys`, aucun import d'un autre
département) assemble les sept composantes que `outils.py` (l'adaptateur, seul) lui apporte, lues à leur source.

CHAQUE COMPOSANTE PORTE SA SOURCE ET SA FRAÎCHEUR : d'où vient le chiffre (le registre, sa taille, la tête de sa
chaîne, ou la déclaration du propriétaire et sa date), et l'horodatage de la pièce la plus récente qui le porte.

UNE COMPOSANTE INCONNUE DONNE « NON CALCULABLE, MANQUE X », JAMAIS ZÉRO (AGENTS.md, fail-closed). Un zéro n'est écrit
que si une source le dit : un registre lu qui ne contient rien à retrancher, ou un « 0.00 » déclaré par le
propriétaire avec sa source et sa date. Le solde lui-même est inconnu tant que le registre n'a aucun mouvement (aucun
solde d'ouverture). Dès qu'une composante manque, `cash_libre` est `None` : la réponse nomme ce qui manque et donne, à
titre de repère seulement, un `au_plus` (le solde moins ce qui est connu ; ce qui manque ne peut que le réduire). Ce
n'est PAS un cash disponible.

CE QUI VIENT D'OÙ, aujourd'hui (le reste est « à déclarer », jamais deviné) :
- solde et réserves : le registre des mouvements (le solde ; les mouvements `PROVISION`) ;
- TPS/TVQ à remettre : la taxe des factures clients envoyées (`ENVOYEE`, `PAYEE`), moins les crédits de taxes sur
  intrants des factures fournisseur SAISIES (T4.15), depuis la dernière remise déclarée ;
- comptes à payer : le total de T4.15 (`comptes_a_payer.resume_a_payer`) ;
- paies, DAS, dettes : aucun module ne les porte (M5.4, paie, est absent) : déclarés par le propriétaire, ou « à
  déclarer ».

HYPOTHÈSES DITES (`hypotheses()`) : elles voyagent avec chaque réponse. Toutes vont dans le sens PRUDENT sauf une, que
le CPA doit valider : les crédits de taxes sur intrants sont supposés récupérables à 100 %.

ARRONDI : un seul mode, `ROUND_HALF_UP` (règle citée dans `taxes.py`), appliqué UNE fois, au résultat final ; les
composantes sont des sommes de montants au cent, donc exactes.

CE MODULE NE FAIT JAMAIS : payer, remettre, déclarer, écrire. Il lit et calcule.
`conformite.verifier_aucun_decaissement` le prouve par l'AST (aucune mention d'un mouvement financier, aucun import du
registre des mouvements).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from . import analyse, encodage, validation

__all__ = [
    "calculer_cash_libre",
    "calculer_taxes_nettes",
    "composante_comptes_a_payer",
    "composante_declaree",
    "composante_reserves",
    "composante_solde",
    "composante_taxes",
    "hypotheses",
    "registre_lu",
    "vue_cash_libre",
    "vue_taxes_nettes",
]

_CENT = Decimal("0.01")
_ZERO = Decimal("0")
# Les deux taxes, telles que `taux_fiscaux.v1.yaml` les nomme (ce sont les identifiants du contrat, pas des taux).
_IDS_TAXES = ("tps_federale", "tvq_quebec")
_ETIQUETTE_TAXE = {"tps_federale": "tps", "tvq_quebec": "tvq"}
# Ordre fixe des composantes retranchées : celui de la définition produit.
_ORDRE_COMPOSANTES = ("taxes_a_remettre", "paies", "das", "comptes_a_payer", "dettes", "reserves")
_LIBELLES = {
    "taxes_a_remettre": "TPS/TVQ à remettre",
    "paies": "Paies",
    "das": "Déductions à la source (DAS)",
    "comptes_a_payer": "Comptes à payer",
    "dettes": "Dettes",
    "reserves": "Réserves critiques",
}
_TEXTE_MONTANT = re.compile(r"^[0-9]{1,12}(\.[0-9]{1,2})?$")
_LONGUEUR_SOURCE_MAX = 120
_IDS_ILLISIBLES_MAX = 5
_PO_AFFICHES_MAX = 3
_LONGUEUR_IDENTIFIANT_AFFICHE = 40

_HYPOTHESES = (
    "taxes collectées : factures clients ENVOYEE ou PAYEE datées après la dernière remise, payées ou non (ARC)",
    "crédits de taxes sur intrants : factures fournisseur SAISIES seulement, récupérables à 100 % (à valider par "
    "le CPA)",
    "une taxe nette négative n'est jamais de l'argent ; TPS et TVQ ne se compensent pas (prudent, à confirmer)",
    "les comptes à recevoir ne sont PAS ajoutés : leur argent n'est pas au solde",
    "une réserve posée pour un autre poste (taxes, paies) compte deux fois : aucune catégorie de réserve (prudent)",
    "un fournisseur payé ou une taxe remise reste retranché tant que le registre l'ignore (prudent : sous-estimé)",
)


def hypotheses() -> list[str]:
    """Les hypothèses du calcul, dites avec chaque réponse (le sens de chacune est prudent, sauf les crédits de taxes
    sur intrants, que le CPA valide)."""
    return list(_HYPOTHESES)


def _verdict(code: str, detail: str = "") -> dict[str, Any]:
    return validation.construire_verdict(code, detail=detail)


def _au_cent(valeur: Decimal) -> Decimal:
    return valeur.quantize(_CENT, rounding=ROUND_HALF_UP)


def _court(identifiant: Any) -> str:
    """Un identifiant de pièce, abrégé pour un message : la réponse d'un outil est bornée par le socle."""
    texte = str(identifiant)
    limite = _LONGUEUR_IDENTIFIANT_AFFICHE
    return texte if len(texte) <= limite else texte[: limite - 1] + "…"


def _texte(valeur: Decimal | None) -> str | None:
    """Un montant en texte positionnel (jamais de notation scientifique) ; `None` reste `None`."""
    return None if valeur is None else format(valeur, "f")


def _date(valeur: Any) -> date | None:
    if not isinstance(valeur, str) or re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", valeur) is None:
        return None
    try:
        return date.fromisoformat(valeur)
    except ValueError:
        return None


def registre_lu(nom: str, maillons: list[Mapping[str, Any]]) -> dict[str, Any]:
    """La source d'un chiffre : un registre lu, sa taille et la tête de sa chaîne."""
    return {"registre": nom, "taille": len(maillons), "tete": maillons[-1]["ligne_id"] if maillons else None}


def _composante(
    id_composante: str, *, montant: Decimal | None, source: str, registres: Iterable[Mapping[str, Any]] = (),
    derniere_piece: str | None = None, pieces: int = 0, manque: Iterable[Mapping[str, Any]] = (),
    reserves: Iterable[str] = (), plancher: Decimal | None = None, detail: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Une composante, toujours de la même forme : montant (ou `None` : non calculable), statut, source, fraîcheur,
    manque, réserves, plancher (le certain, si le total est inconnu) et détail."""
    return {
        "id": id_composante,
        "libelle": _LIBELLES.get(id_composante, id_composante),
        "statut": "CALCULE" if montant is not None else "NON_CALCULABLE",
        "montant": montant,
        "plancher": plancher if montant is None else None,
        "source": {"description": source, "registres": [dict(r) for r in registres]},
        "fraicheur": {"derniere_piece": derniere_piece, "pieces": pieces},
        "manque": [dict(m) for m in manque],
        "reserves": list(reserves),
        "detail": dict(detail) if detail is not None else None,
    }


# ------------------------------------------------------------------------------------------- le solde
def composante_solde(solde: Decimal, mouvements: Mapping[str, Any]) -> dict[str, Any]:
    """Le point de départ : le solde du registre des mouvements (`soldes.calculer_solde`,
    `soldes.decrire_mouvements`).

    Un registre sans aucun mouvement n'a pas de solde connu : aucun solde d'ouverture n'a été enregistré, et un solde
    à zéro serait inventé (`REJ-CASH-SOLDE-ABSENT`)."""
    registres = [{"registre": "mouvements", "taille": mouvements["taille_registre"], "tete": mouvements["tete"]}]
    source = "registre des mouvements de M5 (somme signée, hors réserves)"
    if mouvements["nombre"] == 0:
        return _composante(
            "solde", montant=None, source=source, registres=registres,
            manque=[_verdict(
                "REJ-CASH-SOLDE-ABSENT",
                "aucun mouvement au registre : le solde d'ouverture n'a pas été enregistré, le solde n'est pas connu",
            )],
        )
    return _composante(
        "solde", montant=solde, source=source, registres=registres,
        derniere_piece=mouvements["derniere_piece"], pieces=mouvements["nombre"],
    )


# ---------------------------------------------------------------------------------- les taxes à remettre
def _montants_de_taxes(facture: Mapping[str, Any]) -> dict[str, Decimal] | None:
    """La taxe de chaque type (TPS, TVQ) d'une facture, ou `None` si elle n'est pas lisible : une facture dont la taxe
    ne se lit pas n'entre jamais au total avec un montant inventé."""
    taxes = facture.get("taxes")
    if not isinstance(taxes, (list, tuple)):
        return None
    par_id: dict[str, Decimal] = {}
    for ligne in taxes:
        if not isinstance(ligne, Mapping) or ligne.get("id") not in _IDS_TAXES or ligne["id"] in par_id:
            return None
        montant = ligne.get("montant")
        if not isinstance(montant, Decimal) or not montant.is_finite() or montant < _ZERO:
            return None
        par_id[ligne["id"]] = montant
    return par_id if set(par_id) == set(_IDS_TAXES) else None


def _jour_d_envoi(facture: Mapping[str, Any]) -> date | None:
    envoi = facture.get("date_envoi")
    if not isinstance(envoi, str):
        return None
    try:
        return datetime.fromisoformat(envoi).date()
    except ValueError:
        return None


def calculer_taxes_nettes(
    clients: Iterable[Mapping[str, Any]], fournisseurs: Iterable[Mapping[str, Any]], *, apres: date,
    jusqu_a: date | None = None,
) -> dict[str, Any]:
    """La TPS et la TVQ nettes des factures datées APRÈS `apres` (et au plus tard `jusqu_a`, si donné).

    - `clients` : les états des factures clients ENVOYEE ou PAYEE (un brouillon n'est pas envoyé, une annulée n'est
      plus due) ; la date est celle de l'envoi ; la taxe est celle qui a été calculée à la création de la facture.
    - `fournisseurs` : les factures fournisseur SAISIES (T4.15) ; la date est celle de la facture ; un attendu non
      facturé ne donne aucun crédit (un crédit exige la facture).

    Par taxe : collectée, crédits de taxes sur intrants, nette, et à remettre = la nette si elle est positive, sinon
    zéro (un remboursement n'est jamais de l'argent disponible). Une facture illisible (date ou taxe) est listée dans
    `illisibles` et n'entre pas dans les sommes : l'appelant doit alors dire « non calculable »."""
    collectee = {taxe: _ZERO for taxe in _IDS_TAXES}
    credits = {taxe: _ZERO for taxe in _IDS_TAXES}
    illisibles: list[str] = []
    nombre_clients = nombre_fournisseurs = 0
    plus_recente: date | None = None

    def dans_la_fenetre(jour: date) -> bool:
        return jour > apres and (jusqu_a is None or jour <= jusqu_a)

    for facture in clients:
        jour = _jour_d_envoi(facture)
        if jour is None:
            illisibles.append(str(facture.get("facture_id")))
        elif dans_la_fenetre(jour):
            montants = _montants_de_taxes(facture)
            if montants is None:
                illisibles.append(str(facture.get("facture_id")))
                continue
            nombre_clients += 1
            plus_recente = jour if plus_recente is None else max(plus_recente, jour)
            for taxe in _IDS_TAXES:
                collectee[taxe] += montants[taxe]
    for facture in fournisseurs:
        jour = _date(facture.get("date_facture"))
        if jour is None:
            illisibles.append(str(facture.get("facture_fournisseur_id")))
        elif dans_la_fenetre(jour):
            montants = _montants_de_taxes(facture)
            if montants is None:
                illisibles.append(str(facture.get("facture_fournisseur_id")))
                continue
            nombre_fournisseurs += 1
            plus_recente = jour if plus_recente is None else max(plus_recente, jour)
            for taxe in _IDS_TAXES:
                credits[taxe] += montants[taxe]
    nette = {taxe: collectee[taxe] - credits[taxe] for taxe in _IDS_TAXES}
    a_remettre = {taxe: max(nette[taxe], _ZERO) for taxe in _IDS_TAXES}
    return {
        "collectee": collectee,
        "credits": credits,
        "nette": nette,
        "a_remettre": a_remettre,
        "total_a_remettre": _au_cent(sum(a_remettre.values(), _ZERO)),
        "factures_clients": nombre_clients,
        "factures_fournisseurs": nombre_fournisseurs,
        "illisibles": illisibles,
        "derniere_piece": plus_recente.isoformat() if plus_recente is not None else None,
    }


def vue_taxes_nettes(taxes: Mapping[str, Any]) -> dict[str, Any]:
    """Les taxes nettes en texte, au cent, par taxe (tps, tvq), avec ce qui est retranché."""
    return {
        "a_remettre": _texte(taxes["total_a_remettre"]),
        **{
            _ETIQUETTE_TAXE[taxe]: {
                "collectee": _texte(_au_cent(taxes["collectee"][taxe])),
                "credits_intrants": _texte(_au_cent(taxes["credits"][taxe])),
                "nette": _texte(_au_cent(taxes["nette"][taxe])),
                "a_remettre": _texte(_au_cent(taxes["a_remettre"][taxe])),
            }
            for taxe in _IDS_TAXES
        },
        "factures_clients": taxes["factures_clients"],
        "factures_fournisseurs": taxes["factures_fournisseurs"],
    }


def composante_taxes(
    clients: list[Mapping[str, Any]], fournisseurs: list[Mapping[str, Any]], remises_jusqu_au: date | None,
    verdict_remise: Mapping[str, Any] | None, registres: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """La TPS/TVQ à remettre : ce que les factures clients envoyées ont collecté, moins les crédits de taxes sur
    intrants des factures fournisseur saisies, depuis la dernière remise (`remises_jusqu_au`).

    Sans date de dernière remise (`remises_jusqu_au` nul, avec le `verdict_remise` qui dit quoi déclarer), on ne sait
    pas quelles taxes sont déjà sorties du compte : non calculable, jamais zéro. Une facture illisible rend aussi la
    composante non calculable (`REJ-CASH-FACTURE-ILLISIBLE`)."""
    source = (
        "factures clients ENVOYEE ou PAYEE et factures fournisseur saisies, taxes calculées à la création de chaque "
        "pièce (taux versionnés)"
    )
    if remises_jusqu_au is None:
        return _composante(
            "taxes_a_remettre", montant=None, source=source, registres=registres,
            manque=[verdict_remise if verdict_remise is not None else _verdict(
                "REJ-FISCAL-REMISE-A-DECLARER", "la date de dernière remise de TPS/TVQ n'est pas connue")],
        )
    taxes = calculer_taxes_nettes(clients, fournisseurs, apres=remises_jusqu_au)
    detail = {"depuis": (remises_jusqu_au + timedelta(days=1)).isoformat(), **vue_taxes_nettes(taxes)}
    pieces = taxes["factures_clients"] + taxes["factures_fournisseurs"]
    if taxes["illisibles"]:
        return _composante(
            "taxes_a_remettre", montant=None, source=source, registres=registres, pieces=pieces,
            derniere_piece=taxes["derniere_piece"], detail=detail,
            manque=[_verdict(
                "REJ-CASH-FACTURE-ILLISIBLE",
                f"{len(taxes['illisibles'])} facture(s) dont la date ou la taxe est illisible, donc ni comptée ni "
                f"ignorée : {', '.join(_court(i) for i in taxes['illisibles'][:_IDS_ILLISIBLES_MAX])}",
            )],
        )
    return _composante(
        "taxes_a_remettre", montant=taxes["total_a_remettre"], source=source, registres=registres, pieces=pieces,
        derniere_piece=taxes["derniere_piece"], detail=detail,
    )


# ------------------------------------------------------------------------------------ comptes à payer
def composante_comptes_a_payer(
    resume: Mapping[str, Any] | None, verdict: Mapping[str, Any] | None, registres: Iterable[Mapping[str, Any]]
) -> dict[str, Any]:
    """Les comptes à payer de T4.15 (`comptes_a_payer.resume_a_payer`) : l'« à payer » après taxes de tous les PO
    reçus (facturé + attendu non facturé). Un PO dont l'attendu n'est pas calculable (prix du PO absent, devise autre
    que CAD) rend la composante non calculable, avec le plancher connu (les factures déjà saisies) ; `verdict` est le
    refus de `resume_a_payer` (un taux fiscal manquant), qui rend tout non calculable."""
    source = "comptes à payer de M5 (réceptions de M6, factures fournisseur saisies), T4.15"
    if resume is None:
        return _composante(
            "comptes_a_payer", montant=None, source=source, registres=registres,
            manque=[verdict if verdict is not None else _verdict(
                "REJ-CASH-COMPTES-A-PAYER-INCOMPLETS", "les comptes à payer n'ont pas pu être lus")],
        )
    detail = {"nombre_po": resume["nombre_po"]}
    if resume["complet"]:
        return _composante(
            "comptes_a_payer", montant=resume["a_payer_apres_taxes"], source=source, registres=registres,
            derniere_piece=resume["derniere_piece"], pieces=resume["pieces"], reserves=resume["reserves"],
            detail=detail,
        )
    detail["a_payer_connu"] = _texte(resume["a_payer_connu_apres_taxes"])
    detail["po_non_calculables"] = [
        {"po_id": _court(po["po_id"]), "manque": list(po["manque"])}
        for po in resume["non_calculables_po"][:_PO_AFFICHES_MAX]
    ]
    return _composante(
        "comptes_a_payer", montant=None, plancher=resume["a_payer_connu_apres_taxes"], source=source,
        registres=registres, derniere_piece=resume["derniere_piece"], pieces=resume["pieces"],
        reserves=resume["reserves"], detail=detail,
        manque=[_verdict(
            "REJ-CASH-COMPTES-A-PAYER-INCOMPLETS",
            f"{resume['non_calculables']} PO dont l'à payer n'est pas calculable (pièce absente) : le total connu de "
            f"{_texte(resume['a_payer_connu_apres_taxes'])} $ n'est qu'un plancher",
        )],
    )


# ------------------------------------------------------- paies, DAS, dettes, réserves : déclarés ou à déclarer
_A_DECLARER = {
    "paies": ("REJ-CASH-PAIE-A-DECLARER", "aucun module de paie (M5.4 absent) : les paies dues ne se calculent pas"),
    "das": ("REJ-CASH-DAS-A-DECLARER", "aucun module de paie (M5.4 absent) : les DAS dues ne se calculent pas"),
    "dettes": ("REJ-CASH-DETTES-A-DECLARER", "aucun registre de dettes : les versements exigibles ne se calculent pas"),
    "reserves": (
        "REJ-CASH-RESERVES-A-DECLARER",
        "aucune réserve posée ni déclarée : la cible de réserve est une décision du propriétaire (GATE NATHAN)",
    ),
}
_CHAMPS_DECLARATION = frozenset({"montant", "source", "au"})


def composante_declaree(id_composante: str, declaration: Any) -> dict[str, Any]:
    """Une composante que rien ne calcule encore (paies, DAS, dettes ; réserves sans mouvement de réserve), telle que
    le propriétaire l'a DÉCLARÉE dans `department.yaml` (`configuration.obligations_declarees.<id>`) : `montant`
    (texte décimal, au cent, zéro ou plus), `source` (d'où vient le chiffre : un relevé, un contrat, le CPA) et `au`
    (la date du chiffre, sa fraîcheur).

    Absente : non calculable, avec ce qu'il faut déclarer. Illisible : non calculable aussi
    (`REJ-CASH-DECLARATION-INVALIDE`) : jamais un chiffre corrigé en silence. Un « 0.00 » déclaré est un zéro connu :
    c'est la seule façon d'en écrire un pour ces composantes, et il a sa source et sa date."""
    code, cause = _A_DECLARER[id_composante]
    cle = f"configuration.obligations_declarees.{id_composante}"
    if declaration is None:
        return _composante(
            id_composante, montant=None, source="aucune source",
            manque=[_verdict(code, f"{cause}. Déclarer {cle} (montant, source, au).")],
        )
    montant = jour = None
    if isinstance(declaration, Mapping) and set(declaration) == _CHAMPS_DECLARATION:
        texte, source, au = declaration["montant"], declaration["source"], declaration["au"]
        if isinstance(texte, str) and _TEXTE_MONTANT.fullmatch(texte):
            montant = Decimal(texte)
        jour = _date(au)
        source_ok = isinstance(source, str) and 0 < len(source.strip()) <= _LONGUEUR_SOURCE_MAX
    else:
        source_ok = False
    if montant is None or jour is None or not source_ok:
        return _composante(
            id_composante, montant=None, source="déclaration illisible",
            manque=[_verdict(
                "REJ-CASH-DECLARATION-INVALIDE",
                f"{cle} : exactement montant (texte décimal, 2 décimales au plus, zéro ou plus), source (texte non "
                f"vide, {_LONGUEUR_SOURCE_MAX} caractères au plus) et au (AAAA-MM-JJ, entre guillemets) sont exigés",
            )],
        )
    return _composante(
        id_composante, montant=_au_cent(montant), pieces=1, derniere_piece=jour.isoformat(),
        source=f"déclaration du propriétaire ({cle}) : {source.strip()}",
    )


def composante_reserves(
    total_provisions: Decimal, nombre_provisions: int, derniere_piece: str | None,
    mouvements: Mapping[str, Any], declaration: Any,
) -> dict[str, Any]:
    """Les réserves critiques : les mouvements de réserve du registre (`soldes.calculer_provisions`), déjà mis de côté
    sans sortir du solde. S'il n'y en a aucun, la déclaration du propriétaire (`composante_declaree`, « 0.00 »
    compris) ou, faute de mieux, « à déclarer » : aucune réserve posée n'est pas une décision de n'en avoir aucune."""
    if nombre_provisions > 0:
        return _composante(
            "reserves", montant=_au_cent(total_provisions), pieces=nombre_provisions, derniere_piece=derniere_piece,
            source="registre des mouvements de M5 (réserves déjà mises de côté, hors solde)",
            registres=[{"registre": "mouvements", "taille": mouvements["taille_registre"], "tete": mouvements["tete"]}],
        )
    return composante_declaree("reserves", declaration)


# ------------------------------------------------------------------------------------ l'assemblage
def calculer_cash_libre(solde: Mapping[str, Any], composantes: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Le cash libre : le solde moins les six composantes, dans l'ordre de la définition produit.

    `cash_libre` est `None` (non calculable) dès que le solde ou une composante l'est ; `manque` dit alors quoi
    demander. `au_plus` (le solde moins les montants connus, et les planchers connus des composantes non calculables)
    n'existe que si le solde est connu : un repère, jamais un cash disponible. Un résultat négatif est un DÉFICIT réel
    (`en_deficit`), rendu tel quel, jamais ramené à zéro.

    Lève `ValueError` sur une erreur d'assemblage du code (composantes manquantes, dans le désordre, ou un montant
    négatif ou non fini) : ce n'est pas une donnée de l'entreprise, c'est un défaut à corriger."""
    liste = list(composantes)
    if [c["id"] for c in liste] != list(_ORDRE_COMPOSANTES):
        raise ValueError(f"composantes attendues, dans l'ordre : {list(_ORDRE_COMPOSANTES)}")
    for composante in liste:
        montant = composante["montant"]
        if montant is not None and (not isinstance(montant, Decimal) or not montant.is_finite() or montant < _ZERO):
            raise ValueError(f"{composante['id']} : montant retranché fini et non négatif exigé")
    montant_solde = solde["montant"]
    if montant_solde is not None and (not isinstance(montant_solde, Decimal) or not montant_solde.is_finite()):
        raise ValueError("solde : montant fini exigé")

    manque = [
        {"composante": c["id"], "code": m["code"]} for c in [solde, *liste] for m in c["manque"]
    ]
    calculable = montant_solde is not None and all(c["montant"] is not None for c in liste)
    cash_libre = au_plus = None
    if calculable:
        cash_libre = _au_cent(montant_solde - sum((c["montant"] for c in liste), _ZERO))
    elif montant_solde is not None:
        connu = sum(
            (c["montant"] if c["montant"] is not None else (c["plancher"] or _ZERO) for c in liste), _ZERO
        )
        au_plus = _au_cent(montant_solde - connu)
    reserves = sorted({code for c in [solde, *liste] for code in c["reserves"]})
    contenu = {
        "type": "CASH_LIBRE",
        "cash_libre": cash_libre,
        "calculable": calculable,
        "au_plus": au_plus,
        "solde": solde,
        "composantes": liste,
        "manque": manque,
        "reserves": reserves,
    }
    return {**contenu, "cash_libre_id": encodage.empreinte(contenu)}


def _lecture(resultat: Mapping[str, Any]) -> str:
    if resultat["calculable"]:
        cash = resultat["cash_libre"]
        phrase = f"Cash libre : {format(cash, 'f')} $ (solde moins toutes les obligations ci-dessous)."
        if cash < _ZERO:
            phrase += " C'est un déficit : les obligations connues dépassent le solde."
        if resultat["reserves"]:
            phrase += f" Sous réserve : {', '.join(resultat['reserves'])}."
        return phrase
    if resultat["au_plus"] is None:
        return "Cash libre non calculable : le solde n'est pas connu (voir manque). Aucun chiffre n'est donné."
    return (
        f"Cash libre non calculable : {len(resultat['manque'])} manque(s) (voir manque). Au plus "
        f"{format(resultat['au_plus'], 'f')} $ : le solde moins ce qui est connu ; ce qui manque ne peut que le "
        "réduire. "
        "Ce n'est PAS de l'argent disponible."
    )


_LONGUEUR_TETE_AFFICHEE = 16


def _vue_composante(composante: Mapping[str, Any]) -> dict[str, Any]:
    """Une composante en vue JSON, compacte : `outils.py` la rend dans une réponse bornée à 6 000 caractères par le
    socle. La tête d'un registre n'est montrée que par ses 16 premiers caractères (l'empreinte du cash libre porte le
    reste)."""
    source = {"de": composante["source"]["description"]}
    if composante["source"]["registres"]:
        source["registres"] = [
            {**registre, "tete": None if registre["tete"] is None else registre["tete"][:_LONGUEUR_TETE_AFFICHEE]}
            for registre in composante["source"]["registres"]
        ]
    vue = {
        "id": composante["id"],
        "statut": composante["statut"],
        "montant": _texte(composante["montant"]),
        "source": source,
        "fraicheur": composante["fraicheur"],
    }
    if composante["plancher"] is not None:
        vue["plancher"] = _texte(composante["plancher"])
    for cle in ("manque", "reserves", "detail"):
        if composante[cle]:
            vue[cle] = composante[cle]
    return vue


def vue_cash_libre(resultat: Mapping[str, Any]) -> dict[str, Any]:
    """Le cash libre tel que la réponse d'un outil le porte : tout en texte (montants) ou en valeurs simples, avec sa
    lecture en une phrase, ses hypothèses, la mention obligatoire et son empreinte. Aucun chiffre n'est produit ici :
    seulement rendu."""
    vue = {
        "type": resultat["type"],
        "cash_libre": _texte(resultat["cash_libre"]),
        "calculable": resultat["calculable"],
        "en_deficit": (resultat["cash_libre"] < _ZERO) if resultat["calculable"] else None,
        "au_plus": _texte(resultat["au_plus"]),
        "lecture": _lecture(resultat),
        "solde": _vue_composante(resultat["solde"]),
        "composantes": [_vue_composante(c) for c in resultat["composantes"]],
        "manque": [f"{m['composante']} : {m['code']}" for m in resultat["manque"]],
        "reserves": resultat["reserves"],
        "hypotheses": hypotheses(),
        "cash_libre_id": resultat["cash_libre_id"],
    }
    return analyse.avec_mention(vue)
