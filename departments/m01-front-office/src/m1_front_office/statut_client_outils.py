"""Outil `m1_statut_client` (M1.10, chantier M1-G) : le statut d'un dossier APRÈS vérification d'identité.

Chaîne, et rien de plus :

1. la vérification d'identité est relue au registre `verifications_identite` et rejouée à l'instant fourni ; sans
   état `verifie`, ou sans le niveau que la finalité exige, la réponse est le repli exact « Je vais vérifier avec
   l'équipe. » et AUCUNE lecture n'est faite chez un autre département ;
2. le lead de la conversation est celui des lignes `lead_emis` de M1 (aucun identifiant n'est accepté de l'appelant) ;
3. une lecture T0, par le port privé `lecteur_statut_client` (`Capacites._lecteur_statut_client`) : M2 pour le
   dossier, M3 pour la soumission, M4 pour la visite, M5 pour la facture. Le port n'ouvre que ces quatre lectures et
   seulement dans le contexte de M1 ; il revérifie le niveau T0/N0 ;
4. le statut est traduit par `statut_client.py` (table fermée) et rendu par le gabarit fixe `statut_client`.

Aucune donnée financière ne sort, à aucun niveau : le module ne lit que le statut (`m3_lire_devis` est demandé dans la
vue `employe`, sans coût ni marge ni prix ; `m5_lire_plan_facturation` n'est projeté que sur ses statuts de facture).
Un devis, une visite ou une facture d'un AUTRE lead rend le même repli qu'une référence inconnue : aucune existence
n'est révélée. Aucun texte libre n'est accepté ni produit.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from opsys import stockage
from opsys.outils import Autonomie, Niveau, Outil

from . import horodatage as controle_horodatage
from . import identite_client as ic
from . import outils as _o
from . import statut_client as sc

DEPARTEMENT = "m01-front-office"
REGISTRE = "verifications_identite"
ACTEUR = "m01-front-office"
Lecteur = Callable[[str, Mapping[str, Any]], Mapping[str, Any]]
_PAGES_VISITES_MAX = 10
_TAILLE_PAGE_VISITES = 50


def _reg() -> Any:
    return stockage.maillons(DEPARTEMENT, REGISTRE)


def _refus(code: str, detail: str) -> Any:
    raise ValueError(f"{code}: {detail}")


def _instant(horodatage: str) -> str:
    quand = _o._horodatage_faisant_foi(horodatage)
    controle_horodatage.valider_horodatage(quand)
    return quand


def _ouverture(verification_id: str) -> Mapping[str, Any] | None:
    return next(
        (m for m in _reg() if m.get("type_entree") == ic.TYPE_OUVERTE and m.get("verification_id") == verification_id),
        None,
    )


def _projection(verification_id: str, maintenant: str) -> ic.Projection:
    return ic.projeter(list(_reg()), verification_id, maintenant)


def _lead_de_la_conversation(cle: str) -> tuple[str | None, str | None]:
    """Le lead de la conversation vérifiée, ou `(None, motif)`. Aucun identifiant ne vient de l'appelant."""
    leads: set[str] = set()
    for ligne in _o._obtenir_registre().lire():
        if ligne.get("type_entree") != "lead_emis" or ligne.get("conversation_id") != cle:
            continue
        lead = ligne.get("lead")
        if isinstance(lead, Mapping) and isinstance(lead.get("lead_id"), str) and lead["lead_id"]:
            leads.add(lead["lead_id"])
    if not leads:
        return None, sc.MOTIF_LEAD_INTROUVABLE
    if len(leads) > 1:
        return None, sc.MOTIF_LEAD_AMBIGU
    return next(iter(leads)), None


def _repli(motif: str, sujet: str, verification_id: str) -> dict[str, Any]:
    """Le repli exact, avec la même forme que la réponse établie : aucun détail du dossier, juste la source et la
    vérification qui a servi (ou manqué)."""
    return {"accepte": True, "resultat": {
        **sc.repli(motif, sujet=sujet),
        "verification_id": verification_id,
        "source": sc.SOURCES[sujet],
    }}


def _lire(lecteur: Lecteur | None, outil: str, arguments: Mapping[str, Any]) -> tuple[Any, str | None]:
    """`(charge, None)` ou `(None, motif)`. Une lecture qui plante, refuse ou rend autre chose qu'un objet accepté est
    un repli nommé, jamais une valeur par défaut ni une exception offerte au client."""
    if lecteur is None:
        return None, sc.MOTIF_LECTEUR_INDISPONIBLE
    try:
        reponse = lecteur(outil, dict(arguments))
    except Exception:  # noqa: BLE001 — le port est privé ; toute panne devient un repli nommé
        return None, sc.MOTIF_LECTEUR_INDISPONIBLE
    if not isinstance(reponse, Mapping) or reponse.get("ok") is not True:
        return None, sc.MOTIF_LECTEUR_INDISPONIBLE
    interne = reponse.get("resultat")
    if not isinstance(interne, Mapping) or interne.get("accepte") is not True:
        # Un refus du département (référence inconnue, plan absent) ne se distingue jamais d'une référence d'un autre
        # client : même motif, aucune existence révélée.
        return None, sc.MOTIF_REFERENCE_INCONNUE
    return interne.get("resultat"), None


def _dossier(lecteur: Lecteur | None, lead_id: str) -> tuple[Any, str | None]:
    client, motif = _lire(lecteur, "m2_trouver_client_de_lead", {"lead_id": lead_id})
    if motif is not None:
        return None, motif
    client_id = client.get("client_id") if isinstance(client, Mapping) else None
    if not isinstance(client_id, str) or not client_id:
        return None, sc.MOTIF_REFERENCE_INCONNUE
    vue, motif = _lire(lecteur, "m2_obtenir_client_360", {"client_id": client_id})
    if motif is not None:
        return None, motif
    opportunites = vue.get("opportunites") if isinstance(vue, Mapping) else None
    if not isinstance(opportunites, list):
        return None, sc.MOTIF_REFERENCE_INCONNUE
    trouvees = [
        o for o in opportunites
        if isinstance(o, Mapping) and o.get("lead_id") == lead_id
    ]
    if len(trouvees) != 1:
        return None, sc.MOTIF_LEAD_INTROUVABLE if not trouvees else sc.MOTIF_LEAD_AMBIGU
    return trouvees[0].get("statut"), None


def _soumission(lecteur: Lecteur | None, lead_id: str, reference: str) -> tuple[Any, str | None]:
    devis, motif = _lire(lecteur, "m3_lire_devis", {"devis_id": reference, "role": "employe"})
    if motif is not None:
        return None, motif
    if not isinstance(devis, Mapping) or devis.get("lead_id") != lead_id:
        return None, sc.MOTIF_REFERENCE_INCONNUE
    return devis.get("statut"), None


def _visite(lecteur: Lecteur | None, lead_id: str, reference: str) -> tuple[Any, str | None]:
    curseur: Any = None
    for _ in range(_PAGES_VISITES_MAX):
        page, motif = _lire(
            lecteur,
            "m4_lister_interventions",
            {"statut": None, "curseur": curseur, "taille_page": _TAILLE_PAGE_VISITES},
        )
        if motif is not None:
            return None, motif
        if not isinstance(page, Mapping):
            return None, sc.MOTIF_REFERENCE_INCONNUE
        interventions = page.get("interventions")
        if not isinstance(interventions, list):
            return None, sc.MOTIF_REFERENCE_INCONNUE
        for intervention in interventions:
            if not isinstance(intervention, Mapping) or intervention.get("intervention_id") != reference:
                continue
            if intervention.get("lead_id") != lead_id:
                return None, sc.MOTIF_REFERENCE_INCONNUE
            return intervention.get("statut"), None
        info = page.get("page")
        curseur = info.get("curseur_suivant") if isinstance(info, Mapping) else None
        if not isinstance(curseur, str) or not curseur:
            break
    return None, sc.MOTIF_REFERENCE_INCONNUE


def _facture(
    lecteur: Lecteur | None, lead_id: str, reference: str, facture_id: str | None
) -> tuple[Any, str | None]:
    # La soumission prouve l'appartenance AVANT que M5 ne soit lu : une facture d'un autre dossier ne se distingue
    # pas d'une facture inconnue.
    devis, motif = _lire(lecteur, "m3_lire_devis", {"devis_id": reference, "role": "employe"})
    if motif is not None:
        return None, motif
    if not isinstance(devis, Mapping) or devis.get("lead_id") != lead_id:
        return None, sc.MOTIF_REFERENCE_INCONNUE
    plan, motif = _lire(lecteur, "m5_lire_plan_facturation", {"devis_id": reference})
    if motif is not None:
        return None, motif
    jalons = plan.get("jalons") if isinstance(plan, Mapping) else None
    if not isinstance(jalons, list):
        return None, sc.MOTIF_REFERENCE_INCONNUE
    avec_facture = [
        j for j in jalons
        if isinstance(j, Mapping) and isinstance(j.get("facture_id"), str) and j["facture_id"]
    ]
    if facture_id is not None:
        avec_facture = [
            j for j in avec_facture
            if j.get("facture_id") == facture_id or j.get("numero_facture") == facture_id
        ]
    if len(avec_facture) != 1:
        return None, sc.MOTIF_REFERENCE_INCONNUE
    return avec_facture[0].get("statut"), None


def _statut_client(
    lecteur: Lecteur | None,
    verification_id: str,
    sujet: str,
    horodatage: str,
    reference: str | None = None,
    facture_id: str | None = None,
) -> dict[str, Any]:
    """Le statut borné d'un dossier après vérification d'identité, ou le repli exact.

    Refus (rien n'est lu, aucun dossier n'est révélé) : sujet hors ensemble, référence mal formée, référence fournie
    pour un dossier ou absente pour les autres, `facture_id` hors d'une facture. Sinon : identité non vérifiée,
    niveau insuffisant, port absent, lead introuvable/ambigu, référence inconnue ou statut inconnu rendent le repli.
    """
    if sujet not in sc.SUJETS:
        _refus("REJ-M1-STATUT-SUJET", f"sujet parmi {', '.join(sc.SUJETS)}")
    if not sc.reference_valide(sujet, reference):
        _refus(
            "REJ-M1-STATUT-REFERENCE-INVALIDE",
            "une référence interne bornée est requise pour une soumission, une visite ou une facture ; aucune pour "
            "un dossier",
        )
    if facture_id is not None and (sujet != sc.SUJET_FACTURE or not sc.facture_id_valide(facture_id)):
        _refus("REJ-M1-STATUT-FACTURE-INVALIDE", "facture_id ne s'applique qu'à une facture, sous la même forme bornée")
    quand = _instant(horodatage)
    ouverture = _ouverture(verification_id)
    if ouverture is None:
        return _repli(sc.MOTIF_IDENTITE_NON_VERIFIEE, sujet, verification_id)
    projection = _projection(verification_id, quand)
    if projection.etat != "verifie":
        return _repli(sc.MOTIF_IDENTITE_NON_VERIFIEE, sujet, verification_id)
    if not ic.exiger_niveau(projection, sc.finalite(sujet)):
        return _repli(sc.MOTIF_NIVEAU_INSUFFISANT, sujet, verification_id)
    lead_id, motif = _lead_de_la_conversation(str(ouverture["cle"]))
    if motif is not None:
        return _repli(motif, sujet, verification_id)
    if sujet == sc.SUJET_DOSSIER:
        brut, motif = _dossier(lecteur, lead_id)
    elif sujet == sc.SUJET_SOUMISSION:
        brut, motif = _soumission(lecteur, lead_id, reference)  # type: ignore[arg-type]
    elif sujet == sc.SUJET_VISITE:
        brut, motif = _visite(lecteur, lead_id, reference)  # type: ignore[arg-type]
    else:
        brut, motif = _facture(lecteur, lead_id, reference, facture_id)  # type: ignore[arg-type]
    if motif is not None:
        return _repli(motif, sujet, verification_id)
    resultat = sc.repondre(sujet, brut)
    return {"accepte": True, "resultat": {
        **resultat, "verification_id": verification_id, "source": sc.SOURCES[sujet],
    }}


def statut_client(
    verification_id: str,
    sujet: str,
    horodatage: str,
    reference: str | None = None,
    facture_id: str | None = None,
) -> dict[str, Any]:
    """Appel direct sans port : la lecture est indisponible, donc repli. Les tests d'abus l'utilisent pour prouver
    qu'aucun chemin implicite ne lit un dossier."""
    return _statut_client(None, verification_id, sujet, horodatage, reference, facture_id)


def outils_statut_client(lecteur_statut_client: Lecteur | None = None) -> tuple[Outil, ...]:
    def statut(verification_id, sujet, horodatage, reference=None, facture_id=None):
        return _statut_client(lecteur_statut_client, verification_id, sujet, horodatage, reference, facture_id)

    return (
        Outil(
            nom="m1_statut_client",
            description=(
                "Statut borné d'un dossier APRÈS vérification d'identité : dossier (M2), soumission (M3), visite (M4) "
                "ou facture (M5), par une lecture T0 privée. La réponse est un GABARIT FIXE (aucun texte libre, aucun "
                "montant) ou le repli exact « Je vais vérifier avec l'équipe. ». Référence : devis_id pour une "
                "soumission, intervention_id pour une visite, devis_id pour une facture (facture_id facultatif) ; "
                "aucune référence pour un dossier. Identité non vérifiée, niveau insuffisant, référence inconnue ou "
                "d'un autre client : même repli, aucune existence révélée. Lecture seule, rien n'est envoyé."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "verification_id": {"type": "string", "pattern": "^vi-[0-9a-f]{16}$"},
                    "sujet": {"type": "string", "enum": list(sc.SUJETS)},
                    "reference": {
                        "type": ["string", "null"], "maxLength": 128,
                        "description": "Référence interne (devis_id, intervention_id) ; aucune pour un dossier.",
                    },
                    "facture_id": {
                        "type": ["string", "null"], "maxLength": 128,
                        "description": "Facultatif, seulement pour une facture : facture_id ou numéro de facture.",
                    },
                    "horodatage": {"type": "string", "description": "ISO-8601 avec fuseau ; l'heure relue fait foi."},
                },
                "required": ["verification_id", "sujet", "horodatage"],
                "additionalProperties": False,
            },
            fonction=statut,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
            # Aucun rôle d'appareil : le client passe par le lien tokenisé du core, jamais par un appareil apparié.
        ),
    )
