"""Entrées DÉCLARÉES d'une estimation : barème référencé + mesure référencée, et leur rejeu (M3-C1 et M3-C2).

``Declaration`` relie les deux registres (``bareme_registre``, ``mesure_declaree``) à l'orchestrateur
(``estimation.orchestrer_estimation``). Elle rend, pour un lead et un service, tout ce que l'orchestrateur recevait
avant en arguments libres :

- le barème au format du moteur (``bareme_registre.compiler``), dont la ``version`` est ``<bareme_id>@v<n>`` ;
- le plancher rentable, les taux de marge des trois scénarios (``taux_marge.normal`` pour le prix recommandé) et les
  seuils de revue d'un devis, tels que le barème les déclare — jamais un argument, jamais une valeur par défaut ;
- la quantité, ses bornes basse et haute et le verdict de suffisance de la mesure (``mesure_declaree.evaluer``).

Ordre des refus, pour dire d'abord ce qui manque le plus en amont : référence de barème (existe, validée, en vigueur),
plancher déclaré, service couvert, mesure référencée, mesure de CE lead, bonne unité, assez précise.

``rejouer`` refait le calcul d'une estimation passée depuis sa charge au registre : la version de barème citée (même
si une révision l'a remplacée depuis), la révision de mesure citée, la graine et le niveau d'alors. Mêmes entrées,
mêmes bornes :
c'est le reçu. Un écart est dit, jamais corrigé en silence.

Module pur (ADR-0009) : aucun import ``opsys``, aucune horloge (l'instant est un paramètre).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from . import bareme_registre, estimation, mesure_declaree, verdicts

__all__ = ["Declaration", "rejouer"]

_SCENARIOS = ("prudent", "normal", "agressif")


class Declaration:
    """Les références à résoudre pour UNE estimation (ou son rejeu) et l'instant de référence."""

    def __init__(
        self, journal_bareme: Any, journal_mesures: Any, bareme_ref: Any, mesure_ref: Any, maintenant: datetime,
        *, rejeu: bool = False,
    ) -> None:
        self._journal_bareme = journal_bareme
        self._journal_mesures = journal_mesures
        self._bareme_ref = bareme_ref
        self._mesure_ref = mesure_ref
        self._maintenant = maintenant
        self._rejeu = rejeu

    def preparer(self, lead_id: str, service: str) -> tuple[dict[str, Any] | None, dict | None]:
        version, verdict = bareme_registre.resoudre(
            self._journal_bareme, self._bareme_ref, self._maintenant, exiger_en_vigueur=not self._rejeu
        )
        if verdict is not None:
            return None, verdict
        parametres = bareme_registre.parametres_de(version)
        if "plancher_rentable_cad" not in parametres:
            return None, verdicts.construire_verdict(
                "REJ-BAREME-INCOMPLET",
                detail=(
                    f"la version {version['version']} du barème {version['bareme_id']!r} ne déclare pas de plancher "
                    "rentable (parametres.plancher_rentable_cad) : on ne le devine pas. À faire : le propriétaire le "
                    "déclare dans une révision du barème (m3_declarer_bareme)"
                ),
            )
        bareme, verdict = bareme_registre.compiler(version, service)
        if verdict is not None:
            return None, verdict
        mesure, verdict = mesure_declaree.resoudre(self._journal_mesures, self._mesure_ref, lead_id, service)
        if verdict is not None:
            return None, verdict
        evaluation, verdict = mesure_declaree.evaluer(
            mesure,
            unite_attendue=bareme["unite"],
            parametres_mesure=parametres.get("mesure", {}),
            maintenant=self._maintenant,
            controler_peremption=not self._rejeu,
        )
        if verdict is not None:
            return None, verdict
        taux = parametres.get("taux_marge", {})
        return {
            "bareme": bareme,
            "bareme_ref": bareme_registre.reference_de(version),
            "version_bareme": version,
            "plancher_rentable": float(Decimal(parametres["plancher_rentable_cad"])),
            "plancher_rentable_cad": parametres["plancher_rentable_cad"],
            "taux_marge_prix_recommande": taux.get("normal"),
            "taux_scenarios": {nom: taux.get(nom) for nom in _SCENARIOS},
            "seuils_revue": dict(parametres.get("seuils_revue", {})),
            "mesure": mesure,
            "mesure_ref": {
                "mesure_id": mesure["mesure_id"], "revision": mesure["revision"], "empreinte": mesure["empreinte"],
            },
            "evaluation": evaluation,
            "quantite": float(Decimal(evaluation["quantite"])),
            "quantite_basse": float(Decimal(evaluation["quantite_basse"])),
            "quantite_haute": float(Decimal(evaluation["quantite_haute"])),
        }, None


def rejouer(
    charge: Any, journal_bareme: Any, journal_mesures: Any, maintenant: datetime,
) -> tuple[dict[str, Any] | None, dict | None]:
    """Refait le calcul d'une estimation DÉCLARÉE depuis sa charge au registre et le confronte à ce qui était gardé.

    Rend ``({"identique", "ecarts", "stocke", "recalcule", "bareme_ref", "mesure_ref", "bareme_toujours_en_vigueur"},
    None)``. Une estimation dont le prix était bloqué n'a rien à rejouer (aucun intervalle n'a été calculé)."""
    bloc = charge.get("declaration") if isinstance(charge, dict) else None
    if not isinstance(bloc, dict) or bloc.get("version") != estimation.VERSION_BLOC_DECLARATION:
        return None, verdicts.construire_verdict(
            "REJ-REJEU-IMPOSSIBLE",
            detail=(
                "cette estimation ne porte pas de barème ni de mesure déclarés (estimation d'essai ou antérieure à "
                "M3-C1) : son calcul ne peut pas être rejoué depuis une source écrite"
            ),
        )
    if bloc["intervalle_confiance"] is None:
        return None, verdicts.construire_verdict(
            "REJ-REJEU-IMPOSSIBLE",
            detail="le prix de cette estimation était bloqué : aucun intervalle n'avait été calculé, rien à rejouer",
        )
    declaration = Declaration(
        journal_bareme, journal_mesures, bloc["bareme_ref"], bloc["mesure_ref"], maintenant, rejeu=True
    )
    declare, verdict = declaration.preparer(charge["lead_id"], bloc["service"])
    if verdict is not None:
        return None, verdict
    recalcule, verdict = estimation.enveloppe_de_mesure(
        declare["bareme"], bloc["service"], declare["quantite_basse"], declare["quantite_haute"],
        charge["graine_monte_carlo"], bloc["niveau_statistique"],
    )
    if verdict is not None:
        return None, verdict
    stocke = bloc["intervalle_confiance"]
    ecarts = [
        cle for cle in ("borne_basse", "borne_haute", "niveau")
        if stocke.get(cle) != recalcule[cle]
    ]
    if declare["evaluation"]["quantite"] != bloc["quantite"]:
        ecarts.append("quantite")
    _, courant = bareme_registre.resoudre(journal_bareme, bloc["bareme_ref"], maintenant)
    return {
        "identique": not ecarts,
        "ecarts": ecarts,
        "stocke": dict(stocke),
        "recalcule": recalcule,
        "bareme_ref": dict(bloc["bareme_ref"]),
        "mesure_ref": dict(bloc["mesure_ref"]),
        "bareme_toujours_en_vigueur": courant is None,
    }, None
