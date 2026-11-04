"""Données FICTIVES des estimateurs par service (M3.8b) : barème déclaré + mesures composantes.

Aucune valeur n'est un prix, un taux ni un coefficient réel : ce sont des nombres d'essai, marqués ``fictif``.
Les coefficients d'un estimateur sont DÉCLARÉS dans ``parametres.estimateurs`` du barème (jamais dans le code) ;
les tests fournissent la déclaration de l'entreprise fictive. Importé par ``sys.path`` explicite.
"""

from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

_TESTS = Path(__file__).resolve().parent
if str(_TESTS) not in sys.path:
    sys.path.insert(0, str(_TESTS))
_SRC = Path(__file__).resolve().parents[1] / "src"  # la source de CE département (la copie jetable des mutations)
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

import _commun_bareme as cb  # noqa: E402
from m3_estimation import bareme_registre, mesure_declaree  # noqa: E402

FICTIF = True
LEAD = cb.LEAD
PROPRIO = cb.PROPRIO
ADMIN = cb.ADMIN
VENDEUR = cb.VENDEUR
MAINTENANT = cb.MAINTENANT
JOUR_EFFET = cb.JOUR_EFFET_V1

# Les quatre services de référence du premier client (taxonomie) : les tests d'outils déclarent le profil.
GOUTTIERES = "gouttieres"
REVETEMENT = "revetement"
SOFFITE = "soffite_fascia"
REPARATION = "reparation"


def _ligne(service: str, unite: str, *, cmin: str = "10.00", cmode: str = "12.00", cmax: str = "15.00",
           duree: str | None = "2.5", **extra: Any) -> dict[str, Any]:
    ligne = {
        "service": service, "genre": "ouvrage", "element": "ouvrage fictif", "unite": unite,
        "cout_unitaire_min": cmin, "cout_unitaire_mode": cmode, "cout_unitaire_max": cmax,
        "source_ecrite": f"Feuille de prix fictive {service} 2026-11 (essai)",
    }
    if duree is not None:
        ligne["duree_minutes_par_unite"] = duree
    ligne.update(extra)
    return ligne


def _composante(grandeur: str, unite: str, coefficient: str, *, conversion: str | None = None,
                 source: str | None = None) -> dict[str, Any]:
    composante: dict[str, Any] = {
        "grandeur": grandeur, "unite": unite, "coefficient": coefficient,
        "source_ecrite": source or f"Déclaration fictive du coefficient {grandeur} (essai)",
    }
    if conversion is not None:
        composante["facteur_conversion"] = conversion
    return composante


def estimateurs() -> dict[str, Any]:
    return {
        GOUTTIERES: {
            "unite_ouvrage": "pi.lin",
            "composantes": [
                _composante("longueur_gouttiere", "pi.lin", "1"),
                _composante("longueur_descente", "pi.lin", "1"),
                _composante("coin", "unite", "1", conversion="2.5"),
            ],
            "quantite_minimum": "20",
            "temps_minimum_minutes": "60",
        },
        REVETEMENT: {
            "unite_ouvrage": "pi2",
            "composantes": [
                _composante("surface_brute", "pi2", "1"),
                _composante("ouverture", "pi2", "-1"),
            ],
        },
        SOFFITE: {
            "unite_ouvrage": "pi.lin",
            "composantes": [
                _composante("longueur_soffite", "pi.lin", "1"),
                _composante("longueur_fascia", "pi.lin", "1"),
            ],
        },
        REPARATION: {
            "unite_ouvrage": "heure",
            "composantes": [_composante("heures_reparation", "heure", "1")],
            "quantite_minimum": "1.5",
            "temps_minimum_minutes": "90",
        },
    }


def lignes() -> list[dict[str, Any]]:
    return [
        _ligne(GOUTTIERES, "pi.lin", cmin="9.50", cmode="11.00", cmax="13.00", duree="2"),
        _ligne(REVETEMENT, "pi2", cmin="8.00", cmode="10.00", cmax="14.00", duree="2.5"),
        _ligne(SOFFITE, "pi.lin", cmin="7.00", cmode="9.00", cmax="12.00", duree="3"),
        _ligne(REPARATION, "heure", cmin="60.00", cmode="75.00", cmax="95.00", duree="60"),
    ]


def parametres(**surcharges: Any) -> dict[str, Any]:
    parametres = deepcopy(cb.PARAMETRES)
    # Seuil de revue fictif plus serré que celui de la fixture générale, pour éprouver la revue d'une composante
    # large sans refuser le prix (le seuil « aucun prix » reste 0.50).
    parametres["mesure"] = {"largeur_relative_revue": "0.05", "largeur_relative_max_prix": "0.50",
                            "validite_jours": 30}
    parametres["estimateurs"] = estimateurs()
    parametres.update(surcharges)
    return parametres


def declarer(journal: Any, *, version_attendue: int = 0, **surcharges: Any) -> tuple[Any, Any]:
    arguments: dict[str, Any] = {
        "bareme_id": "bareme-estimateurs-fictif", "version_attendue": version_attendue, "lignes": lignes(),
        "parametres": parametres(), "soumission": deepcopy(cb.SOUMISSION), "date_effet": JOUR_EFFET,
        "auteur": PROPRIO, "horodatage": "2026-11-01T09:00:00+00:00",
    }
    arguments.update(surcharges)
    return bareme_registre.declarer_version(journal, **arguments)


def declarer_ok(journal: Any, **kwargs: Any) -> dict[str, Any]:
    resultat, verdict = declarer(journal, **kwargs)
    assert verdict is None, verdict
    return resultat["version"]


def mesurer(journal: Any, *, mesure_id: str, grandeur: str, valeur: str, unite: str, borne_basse: str,
            borne_haute: str, service: str, lead_id: str = LEAD, revision_attendue: int = 0,
            methode: str = "releve_sur_place", confiance: str = "elevee",
            mesure_le: str = "2026-11-02T09:00:00+00:00", horodatage: str = "2026-11-02T10:00:00+00:00",
            pieces: list[str] | None = None, auteur: Any = ADMIN) -> tuple[Any, Any]:
    return mesure_declaree.declarer(
        journal, mesure_id=mesure_id, revision_attendue=revision_attendue, lead_id=lead_id, service=service,
        grandeur=grandeur, valeur=valeur, unite=unite, borne_basse=borne_basse, borne_haute=borne_haute,
        methode=methode, confiance=confiance, mesure_le=mesure_le, pieces=pieces or ["photo-fictive-1"],
        auteur=auteur, horodatage=horodatage,
    )


def mesurer_ok(journal: Any, **kwargs: Any) -> dict[str, Any]:
    resultat, verdict = mesurer(journal, **kwargs)
    assert verdict is None, verdict
    return resultat["mesure"]


def mesures_gouttieres(journal: Any, *, lead_id: str = LEAD) -> list[dict[str, Any]]:
    return [
        mesurer_ok(journal, mesure_id="mes-gouttiere", grandeur="longueur_gouttiere", valeur="100",
                   unite="pi.lin", borne_basse="98", borne_haute="102", service=GOUTTIERES, lead_id=lead_id),
        mesurer_ok(journal, mesure_id="mes-descente", grandeur="longueur_descente", valeur="40", unite="pi.lin",
                   borne_basse="39", borne_haute="41", service=GOUTTIERES, lead_id=lead_id),
        mesurer_ok(journal, mesure_id="mes-coin", grandeur="coin", valeur="6", unite="unite", borne_basse="6",
                   borne_haute="6", service=GOUTTIERES, lead_id=lead_id),
    ]


def mesures_revetement(journal: Any, *, lead_id: str = LEAD) -> list[dict[str, Any]]:
    return [
        mesurer_ok(journal, mesure_id="mes-surface", grandeur="surface_brute", valeur="1200", unite="pi2",
                   borne_basse="1150", borne_haute="1250", service=REVETEMENT, lead_id=lead_id),
        mesurer_ok(journal, mesure_id="mes-ouverture", grandeur="ouverture", valeur="100", unite="pi2",
                   borne_basse="95", borne_haute="105", service=REVETEMENT, lead_id=lead_id),
    ]


def refs(mesures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"mesure_id": mesure["mesure_id"]} for mesure in mesures]


def ref(version: dict[str, Any], *, avec_empreinte: bool = False) -> dict[str, Any]:
    return cb.ref(version, avec_empreinte=avec_empreinte)


def code(verdict: Any) -> str:
    return cb.code(verdict)
