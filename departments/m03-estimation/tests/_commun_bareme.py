"""Données FICTIVES communes aux tests du barème et de la mesure déclarés (M3-C1, M3-C2).

Aucune valeur ici n'est un coût réel : ce sont des nombres d'essai, marqués ``fictif``. Le barème de l'entreprise
est une déclaration du propriétaire (jamais inventée par le code) ; les tests fournissent la leur.
Importé par ``sys.path`` explicite (le mode d'import ``importlib`` n'ajoute pas le dossier des tests).
"""

from __future__ import annotations

import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

_SRC = Path(__file__).resolve().parents[1] / "src"  # la source de CE département (la copie jetable des mutations)
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from m3_estimation import bareme_registre, mesure_declaree  # noqa: E402

FICTIF = True
SERVICE = "ravalement"  # type de travaux v1 : aucune taxonomie d'entreprise à déclarer
LEAD = "lead-bareme-001"
PROPRIO = {"personne": "proprio.fictif", "role": "nathan_owner"}
ADMIN = {"personne": "admin.fictif", "role": "admin"}
VENDEUR = {"personne": "vendeur.fictif", "role": "seller"}

MAINTENANT = datetime(2026, 11, 2, 12, 0, 0, tzinfo=UTC)
JOUR_EFFET_V1 = "2026-11-01T00:00:00+00:00"
JOUR_EFFET_V2 = "2026-11-10T00:00:00+00:00"
APRES_V2 = MAINTENANT + timedelta(days=10)


def iso(instant: datetime) -> str:
    return instant.isoformat(timespec="seconds")


def lignes(**surcharges_ouvrage: Any) -> list[dict[str, Any]]:
    ouvrage = {
        "service": SERVICE, "genre": "ouvrage", "element": "pose complète", "unite": "pi2",
        "cout_unitaire_min": "8.00", "cout_unitaire_mode": "10.00", "cout_unitaire_max": "14.00",
        "duree_minutes_par_unite": "2.5", "source_ecrite": "Feuille de prix fictive 2026-10 (essai)",
    }
    ouvrage.update(surcharges_ouvrage)
    materiau = {
        "service": SERVICE, "genre": "materiau", "element": "Revêtement fictif", "unite": "pi2",
        "quantite_par_unite": "1.1", "taux_perte": "0.10", "source_ecrite": "Fiche fournisseur fictive (essai)",
    }
    return [ouvrage, materiau]


PARAMETRES = {
    "plancher_rentable_cad": "9000",
    "taux_marge": {"prudent": "0.40", "normal": "0.30", "agressif": "0.15"},
    "seuils_revue": {"montant_maximal_cad": "50000", "marge_minimale": "0.20"},
    "mesure": {"largeur_relative_revue": "0.15", "largeur_relative_max_prix": "0.50", "validite_jours": 30},
}
SOUMISSION = {
    "exclusions": ["Travaux de fondation et de structure non inclus (texte fictif)."],
    "hypotheses": ["Accès libre aux murs extérieurs (texte fictif)."],
    "validite_jours": 30,
}


_DEFAUT = object()


def declarer(journal: Any, *, bareme_id: str = "bareme-fictif", version_attendue: int = 0, auteur: Any = _DEFAUT,
             horodatage: str = "2026-11-01T09:00:00+00:00", **surcharges: Any) -> tuple[Any, Any]:
    arguments: dict[str, Any] = {
        "bareme_id": bareme_id, "version_attendue": version_attendue, "lignes": lignes(),
        "parametres": deepcopy(PARAMETRES), "soumission": deepcopy(SOUMISSION), "date_effet": JOUR_EFFET_V1,
        "auteur": PROPRIO if auteur is _DEFAUT else auteur, "horodatage": horodatage,
    }
    arguments.update(surcharges)
    return bareme_registre.declarer_version(journal, **arguments)


def declarer_ok(journal: Any, **kwargs: Any) -> dict[str, Any]:
    resultat, verdict = declarer(journal, **kwargs)
    assert verdict is None, verdict
    return resultat["version"]


def ref(version: dict[str, Any], *, avec_empreinte: bool = False) -> dict[str, Any]:
    reference = {"bareme_id": version["bareme_id"], "version": version["version"]}
    if avec_empreinte:
        reference["empreinte"] = version["empreinte"]
    return reference


def mesurer(journal: Any, *, mesure_id: str = "mesure-fictive-1", revision_attendue: int = 0, lead_id: str = LEAD,
            auteur: Any = _DEFAUT, horodatage: str = "2026-11-02T10:00:00+00:00", **surcharges: Any) -> tuple[Any, Any]:
    arguments: dict[str, Any] = {
        "mesure_id": mesure_id, "revision_attendue": revision_attendue, "lead_id": lead_id, "service": SERVICE,
        "grandeur": "surface de revêtement", "valeur": "1200", "unite": "pi2", "borne_basse": "1200",
        "borne_haute": "1200", "methode": "releve_sur_place", "confiance": "elevee",
        "mesure_le": "2026-11-02T09:00:00+00:00", "pieces": ["photo-fictive-1", "croquis-fictif-1"],
        "auteur": ADMIN if auteur is _DEFAUT else auteur, "horodatage": horodatage,
    }
    arguments.update(surcharges)
    return mesure_declaree.declarer(journal, **arguments)


def mesurer_ok(journal: Any, **kwargs: Any) -> dict[str, Any]:
    resultat, verdict = mesurer(journal, **kwargs)
    assert verdict is None, verdict
    return resultat["mesure"]


def code(verdict: Any) -> str:
    assert verdict is not None
    return verdict["code"]
