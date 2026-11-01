"""Attribution SIMPLE et honnête : compter les conversions par source, dire ce que l'on ne sait pas, ne rien expliquer.

Règle unique et documentée : une conversion appartient à la SOURCE NORMALISÉE qu'elle porte (`utm_source` de la
conversion hors ligne importée, telle que M2 l'a connue pour le lead) — « dernière source connue », sans
multi-touche, sans pondération, sans modèle. Une conversion sans source est comptée à part (`sans_source`) et JAMAIS
redistribuée aux autres.

Ce que le rapport donne :
- le nombre et la part de chaque source, avec l'intervalle de Wilson de la part (le dénominateur contient
`sans_source`) ; - des NIVEAUX : deux sources dont les intervalles se chevauchent sont `indistinguables`, aucun
classement entre elles ; - le coût par conversion d'un canal payant UNIQUEMENT quand sa dépense
(`m7.depenses_marketing`, relevés sourcés) est `CONNUE`
  sur toute la période : sinon `inconnu`, avec le statut (`PARTIELLE`, `NON_BRANCHEE`) et, au plus, la borne basse
  déjà établie. Seules les conversions `cpc` d'une source payante comptent pour ce coût (google -> google_ads ;
  facebook, instagram -> meta).

`causalite` vaut toujours `non_etablie` : l'attribution compte, elle n'explique pas.

Module pur : les conversions et les dépenses sont fournies par l'appelant.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from . import statistiques as st
from .verdicts import construire_verdict

REGLE = (
    "Dernière source connue : chaque conversion appartient à l'utm_source normalisée qu'elle porte ; sans source, "
    "elle reste « sans_source » et n'est jamais redistribuée."
)
TEXTE_CAUSALITE = (
    "Attribution descriptive : elle compte, elle n'explique pas. Sans test marche-arrêt ou géographique "
    "préenregistré, aucun effet causal n'est affirmé."
)
CANAL_DE_SOURCE: Mapping[str, str] = {"google": "google_ads", "facebook": "meta", "instagram": "meta"}
MEDIUM_PAYANT = "cpc"


def _part(k: int, n: int) -> str:
    return st.texte(Decimal(k) / Decimal(n))


def _cout(depense: Mapping[str, Any] | None, canal: str, conversions_payantes: int) -> dict[str, Any]:
    ligne = None
    if depense is not None:
        ligne = next((c for c in depense.get("canaux", []) if c.get("canal") == canal), None)
    if ligne is None:
        return {
            "canal": canal,
            "statut_depense": "NON_BRANCHEE",
            "conversions_payantes": conversions_payantes,
            "cout_par_conversion_cad": None,
            "inconnu": "aucune dépense fournie pour ce canal",
        }
    base = {
        "canal": canal,
        "statut_depense": ligne["statut"],
        "conversions_payantes": conversions_payantes,
        "base_taxes": ligne.get("base_taxes"),
        "depense_cad": ligne.get("montant_cad"),
        "depense_au_moins_cad": ligne.get("au_moins_cad"),
    }
    if ligne["statut"] != "CONNUE":
        return {
            **base,
            "cout_par_conversion_cad": None,
            "inconnu": f"dépense {ligne['statut']} sur la période : un coût par conversion serait une invention",
        }
    if conversions_payantes == 0:
        return {
            **base,
            "cout_par_conversion_cad": None,
            "inconnu": "aucune conversion payante : coût par conversion indéfini",
        }
    cout = (Decimal(ligne["montant_cad"]) / Decimal(conversions_payantes)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    return {**base, "cout_par_conversion_cad": format(cout, "f"), "inconnu": None}


def attribuer(
    conversions: Sequence[Mapping[str, Any]],
    debut: date,
    fin: date,
    depenses: Mapping[str, Any] | None = None,
    niveau: str = "0.95",
) -> dict[str, Any]:
    """L'attribution descriptive des `conversions` (enregistrements courants du registre) dont le jour est dans la "
    "période."""
    if (
        not isinstance(debut, date)
        or not isinstance(fin, date)
        or isinstance(debut, datetime)
        or isinstance(fin, datetime)
        or debut > fin
    ):
        return {
            "accepte": False,
            "refus": [
                {
                    "code": "REJ-MESURE-ATTRIBUTION-INVALIDE",
                    "chemin": "$.periode",
                    "detail": "période : dates civiles, début <= fin",
                }
            ],
        }
    try:
        niv = Decimal(niveau)
    except Exception:  # noqa: BLE001
        niv = None
    if niv not in st.NIVEAUX_PERMIS:
        return {
            "accepte": False,
            "refus": [
                {
                    "code": "REJ-MESURE-ATTRIBUTION-INVALIDE",
                    "chemin": "$.niveau",
                    "detail": f"niveau parmi {[str(n) for n in st.NIVEAUX_PERMIS]}",
                }
            ],
        }
    bas, haut = debut.isoformat(), fin.isoformat()
    retenues = [c for c in conversions if bas <= c["convertie_le"] <= haut]
    total = len(retenues)
    base = {
        "accepte": True,
        "periode": {"debut": bas, "fin": haut},
        "regle": REGLE,
        "causalite": "non_etablie",
        "avertissement_causalite": TEXTE_CAUSALITE,
        "niveau_confiance": st.texte(niv),
        "total_conversions": total,
    }
    if total == 0:
        return {
            **base,
            "statut": "AUCUNE_CONVERSION",
            "sources": [],
            "sans_source": {"conversions": 0, "part": None},
            "niveaux": [],
            "couts_par_conversion": [],
            "lecture": "Aucune conversion hors ligne importée pour "
            "la période : "
            "ce n'est pas une preuve d'absence de ventes, seulement d'absence d'import.",
        }
    par_source: dict[str, int] = {}
    sans = 0
    payantes: dict[str, int] = {}
    for c in retenues:
        source = c.get("utm_source")
        if source is None:
            sans += 1
            continue
        par_source[source] = par_source.get(source, 0) + 1
        if c.get("utm_medium") == MEDIUM_PAYANT and source in CANAL_DE_SOURCE:
            canal = CANAL_DE_SOURCE[source]
            payantes[canal] = payantes.get(canal, 0) + 1
    lignes = []
    for source, k in sorted(par_source.items(), key=lambda t: (-t[1], t[0])):
        b, h = st.wilson(k, total, niv)
        lignes.append(
            {
                "source": source,
                "conversions": k,
                "part": _part(k, total),
                "borne_basse": st.texte(b),
                "borne_haute": st.texte(h),
                "_b": b,
                "_h": h,
            }
        )
    # Niveaux : une source rejoint le niveau courant si son intervalle chevauche celui de la tête du niveau.
    niveaux: list[list[dict[str, Any]]] = []
    for ligne in lignes:
        if niveaux and ligne["_h"] >= niveaux[-1][0]["_b"] and ligne["_b"] <= niveaux[-1][0]["_h"]:
            niveaux[-1].append(ligne)
        else:
            niveaux.append([ligne])
    sortie_niveaux = [
        {"rang": i + 1, "sources": [m["source"] for m in groupe], "indistinguables": len(groupe) > 1}
        for i, groupe in enumerate(niveaux)
    ]
    for ligne in lignes:
        del ligne["_b"], ligne["_h"]
    couts = [_cout(depenses, canal, payantes.get(canal, 0)) for canal in sorted(set(CANAL_DE_SOURCE.values()))]
    lecture = "Comptes par source, sans classement entre sources indistinguables."
    if len(sortie_niveaux) == 1 and len(lignes) > 1:
        lecture = "Aucune source ne se distingue des autres à ce niveau de confiance : pas de classement."
    return {
        **base,
        "statut": "CALCULEE",
        "sources": lignes,
        "sans_source": {"conversions": sans, "part": _part(sans, total)},
        "niveaux": sortie_niveaux,
        "couts_par_conversion": couts,
        "lecture": lecture,
    }


def verdict_invalide(detail: str) -> dict[str, str]:
    return construire_verdict("REJ-MESURE-ATTRIBUTION-INVALIDE", detail=detail)


__all__ = ["CANAL_DE_SOURCE", "REGLE", "TEXTE_CAUSALITE", "attribuer", "verdict_invalide"]
