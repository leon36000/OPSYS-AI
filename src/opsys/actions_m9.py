"""Port privé M9 vers la file d'approbation native : PROPOSER une action à un humain, jamais l'exécuter.

M9 (Direction IA) ne dispose d'aucun moyen d'exécuter l'action d'un autre département. Ce port ne fait que deux choses :

* ``proposer`` enregistre, dans la file ``approbations`` du socle, une demande ``en_attente`` pour un outil de la liste
  blanche ``ACTIONS_AUTORISEES`` (T1 exigeant une approbation, niveau N3 au moins) avec les arguments EXACTS fournis,
  validés contre le schéma de l'outil cible. L'approbation humaine (rôles de la politique du département cible) exécute
  ensuite l'outil avec ces arguments, jamais d'autres (``approbations.decider``) ;
* ``lire`` rend l'état natif d'une demande (statut, décideur, succès déclaré par le producteur, empreintes), sans les
  arguments en clair.

Seul l'admin authentifié agissant via M9 peut s'en servir (même contrôle que ``opsys.lecteurs_m9``). Le port n'ajoute
aucun droit : la liste blanche est une borne de plus, pas une autorisation ; ajouter une action exige une revue humaine.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager
from typing import Any

from sqlalchemy import Connection, select

from . import approbations, identite, stockage
from . import contexte as contexte_appel
from .idempotence import empreinte_arguments
from .outils import Autonomie, Niveau, valider_arguments
from .stockage.schema import APPROBATIONS

DEPARTEMENT_M9 = "m09-strategic-intelligence"
ACTIONS_AUTORISEES: dict[str, frozenset[str]] = {
    "m02-revenue-crm": frozenset({"m2_preparer_relance", "m2_reassigner_lead"}),
    "m04-field-ops": frozenset({"m4_planifier_intervention", "m4_creer_demande_ecart"}),
}
STATUTS_NATIFS = frozenset({"en_attente", "en_cours", "refusee", "executee", "echec"})
MAX_ARGUMENTS_OCTETS = 8_192


def _refus(erreur: str, details: str) -> dict[str, Any]:
    return {"ok": False, "erreur": erreur, "details": details}


def _verifier_admin_via_m9() -> dict[str, Any] | None:
    appelante = contexte_appel.identite_appelante()
    if (
        appelante is None
        or appelante.role != "admin"
        or appelante.source not in {"console", "appareil"}
        or contexte_appel.DEPARTEMENT_APPELANT.get() != DEPARTEMENT_M9
        or contexte_appel.departement_origine_appelante() != DEPARTEMENT_M9
    ):
        return _refus("identite_admin_requise", "le port d'actions exige l'admin authentifié via M9")
    cnx = stockage.connexion_courante()
    personne = identite.personne_active(cnx, appelante.personne) if cnx is not None else None
    if personne is None or "admin" not in personne.roles:
        return _refus("identite_admin_requise", "personne active portant encore le rôle admin requise")
    return None


def construire_proposeur(
    departements: Mapping[str, Any],
    cnx_factory: Callable[[], AbstractContextManager[Connection]],
) -> Callable[..., dict[str, Any]]:
    """Port ``(operation, **valeurs) -> réponse`` ; opérations ``proposer`` et ``lire``, refus structurés."""
    from .capacites import Capacites  # import tardif : capacites construit ce port

    cibles = {dep for dep in ACTIONS_AUTORISEES if dep in departements}
    index = (
        Capacites(departements, cnx_factory, filtre=cibles, memoire=False).index if cibles else {}
    )  # lecture des définitions d'outils seulement : rien n'est exécuté par ce port

    def proposer(departement: str, outil: str, arguments: Any, motif: str) -> dict[str, Any]:
        if departement not in cibles or outil not in ACTIONS_AUTORISEES.get(departement, frozenset()):
            return _refus("action_non_autorisee", "outil absent de la liste blanche des actions proposables par M9")
        entree = index.get(outil)
        if entree is None or entree[0] is None or entree[0].id != departement:
            return _refus("producteur_indisponible", "l'outil cible n'est pas chargé")
        definition = entree[1]
        if definition.autonomie is not Autonomie.T1 or definition.niveau_effectif not in (
            Niveau.N3,
            Niveau.N4,
            Niveau.N5,
        ):
            return _refus("action_non_approuvable", "seul un outil T1 de niveau N3 ou plus passe par une approbation")
        if not isinstance(arguments, Mapping) or len(json.dumps(arguments, ensure_ascii=False)) > MAX_ARGUMENTS_OCTETS:
            return _refus("arguments_invalides", "arguments objet bornés requis")
        erreurs = valider_arguments(definition.parametres, dict(arguments))
        if erreurs:
            return _refus("arguments_invalides", "; ".join(str(e) for e in erreurs)[:500])
        cnx = stockage.connexion_courante()
        if cnx is None:
            return _refus("transaction_requise", "aucune transaction métier ouverte")
        ident = approbations.creer_demande(
            cnx, departement, outil, dict(arguments), niveau=definition.niveau_effectif, motif=(motif or "")[:300]
        )
        return {
            "ok": True,
            "demande_id": ident,
            "niveau": definition.niveau_effectif.value,
            "arguments_sha256": empreinte_arguments(dict(arguments)),
        }

    def lire(demande_id: str) -> dict[str, Any]:
        cnx = stockage.connexion_courante()
        if cnx is None or type(demande_id) is not str or not demande_id:
            return _refus("arguments_invalides", "identifiant de demande et transaction requis")
        ligne = cnx.execute(select(APPROBATIONS).where(APPROBATIONS.c.id == demande_id)).mappings().fetchone()
        if ligne is None:
            return {"ok": True, "trouvee": False}
        if ligne["outil"] not in ACTIONS_AUTORISEES.get(ligne["departement"], frozenset()):
            return _refus("demande_hors_perimetre", "cette demande n'est pas une action proposable par M9")
        resultat = json.loads(ligne["resultat"]) if ligne["resultat"] else None
        return {
            "ok": True,
            "trouvee": True,
            "statut": ligne["statut"] if ligne["statut"] in STATUTS_NATIFS else "inconnu",
            "departement": ligne["departement"],
            "outil": ligne["outil"],
            "niveau": ligne["niveau"],
            "arguments_sha256": empreinte_arguments(json.loads(ligne["arguments"])),
            "decide_par": ligne["decide_par"],
            "decide_role": ligne["decide_role"],
            "decide_le": ligne["decide_le"],
            "succes_declare": approbations.execution_reussie(resultat) if isinstance(resultat, Mapping) else None,
            "resultat_sha256": empreinte_arguments(resultat) if isinstance(resultat, Mapping) else None,
        }

    def port(operation: str, **valeurs: Any) -> dict[str, Any]:
        refus = _verifier_admin_via_m9()
        if refus is not None:
            return refus
        if operation == "proposer":
            return proposer(
                valeurs.get("departement", ""),
                valeurs.get("outil", ""),
                valeurs.get("arguments"),
                valeurs.get("motif", ""),
            )
        if operation == "lire":
            return lire(valeurs.get("demande_id"))  # type: ignore[arg-type]
        return _refus("operation_inconnue", "operations admises : proposer, lire")

    return port
