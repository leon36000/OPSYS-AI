"""Outils M10 de lecture et de test des rôles de modèles (docs/architecture/PASSERELLE-DE-MODELES.md).

- `m10_lire_roles_modeles` (T0 / N0) : état des rôles (fournisseur, modèle d'appel, conformité, plafonds, usage du jour,
  mesuré ou non), de la passerelle (SANS aucune valeur de secret) et de la politique d'économie ;
- `m10_tester_role_modele` (T1 / N2) : UN appel minuscule au fournisseur principal d'un rôle (≤ 8 jetons de sortie), au
  plus un test par rôle par minute. Le rôle de raisonnement n'est jamais testable par un agent (console du
  propriétaire).

Aucun outil ne change une affectation, un plafond, une clé ni l'escalade : ces gestes sont humains (console, N3). Aucun
rôle d'appareil, pour aucun des deux. Aucun avis comptable, fiscal ou juridique n'est produit ici.
"""

from __future__ import annotations

from typing import Any

from opsys import stockage
from opsys.contexte import identite_appelante
from opsys.outils import Autonomie, Niveau, Outil
from opsys.roles_modeles import appel, economie, service
from opsys.roles_modeles import roles as lex
from opsys.roles_modeles.codes import ModelesErreur
from opsys.secrets_coffre import masquage

AGENT = "agent:m10-memoire"
DELAI_MIN_TEST_S = 60


def _refuser_appareil() -> None:
    if identite_appelante() is not None:
        raise ModelesErreur("REJ-MODELES-ADMIN-REQUIS", "les rôles de modèles ne sont pas ouverts aux appareils", 403)


def lire_roles_modeles() -> dict[str, Any]:
    _refuser_appareil()
    cnx = stockage.connexion_courante()
    if cnx is None:
        raise ModelesErreur("REJ-MODELES-ADMIN-REQUIS", "aucune transaction de l'instance", 409)
    vue = service.vue_complete(cnx)
    roles = []
    for r in vue["roles"]:
        ligne: dict[str, Any] = {
            "role": r["role"],
            "etat": r["etat"],
            "alias_defaut": r["alias"],
            "classes_de_tache": r["classes"],
        }
        if r["configure"]:
            f = r["fournisseur"] or {}
            ligne.update(
                {
                    "fournisseur": f.get("identifiant"),
                    "mode": f.get("mode"),
                    "modele_appel": r["modele_appel"],
                    "conforme": f.get("conforme"),
                    "refus_politique": f.get("refus"),
                    "replis": [x["fournisseur"] for x in r["replis"]],
                    "plafonds": r["plafonds"],
                    "usage_jour": r["usage_jour"],
                    "plafond_atteint": r["plafond_atteint"],
                    "cout_par_million": r["cout"],
                    "mesure": r["mesure"]["libelle"],
                    "connexion_testee": r["mesure"]["connexion_testee"],
                }
            )
        roles.append(ligne)
    p = vue["passerelle"]
    return masquage.masquer(
        {
            "passerelle": {"configuree": p["configuree"], "mode": p.get("mode"), "url": p.get("url_base")},
            "raisonnement_actif": vue["raisonnement"]["actif"],
            "roles": roles,
            "politique_economie": {
                "version": economie.VERSION_POLITIQUE,
                "statut": economie.vue()["statut"],
                "classes": {n: c["role"] for n, c in economie.CLASSES.items()},
            },
            "note": ("Seul le propriétaire modifie ces réglages (console, geste N3). "
                 "Un rôle sans affectation est inerte."),
        }
    )


def tester_role_modele(role: str) -> dict[str, Any]:
    _refuser_appareil()
    if role not in lex.ROLES:
        raise ModelesErreur("REJ-MODELES-ROLE-INCONNU", f"rôle parmi {', '.join(lex.ROLES)}", 422)
    mesure = appel.tester_role(
        stockage.transaction,
        acteur=AGENT,
        role=role,
        verifier_admin=False,
        interdire_raisonnement=True,
        dans_transaction=True,
        delai_min_s=DELAI_MIN_TEST_S,
    )
    return {"role": role, "mesure": mesure}


def outils_modeles() -> tuple[Outil, ...]:
    return (
        Outil(
            nom="m10_lire_roles_modeles",
            description=(
                "Lit l'état des rôles de modèles (LLM rapide, fort, raisonnement, embeddings, reranker, OCR, vision, "
                "voix, image) : fournisseur et modèle affectés, conformité de licence, plafonds, usage du jour, "
                "état mesuré ou non, passerelle (sans aucune clé) et politique d'économie par classe de tâche. Lecture "
                "pure ; un rôle sans affectation est inerte. Les réglages ne se changent pas par cet outil."
            ),
            parametres={"type": "object", "properties": {}, "additionalProperties": False},
            fonction=lire_roles_modeles,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
        ),
        Outil(
            nom="m10_tester_role_modele",
            description=(
                "Test de connexion d'un rôle de modèle : UN appel minuscule (8 jetons de sortie au plus, un seul "
                "texte pour les embeddings) au fournisseur principal, résultat conservé (latence, dimension). Au plus "
                "un test par rôle par minute ; jamais le rôle de raisonnement. Ne change aucun réglage."
            ),
            parametres={
                "type": "object",
                "properties": {"role": {"type": "string", "enum": list(lex.ROLES)}},
                "required": ["role"],
                "additionalProperties": False,
            },
            fonction=tester_role_modele,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
    )
