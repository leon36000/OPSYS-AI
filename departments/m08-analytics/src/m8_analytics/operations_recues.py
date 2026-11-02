"""Ce que M7, M5, M3, M6, M4, M2 et M1 ont constaté et que M8 range tel quel (interconnexion des départements, bus
d'événements).

Module PUR (ADR-0009) : aucun import d'``opsys``, aucune horloge (« aujourd'hui » vient de l'appelant). ``outils.py``,
seul point de contact avec le socle, reçoit les événements, range les faits au registre ``faits_operations`` et lit ce
registre pour la section « operations_recues » de la vue exécutive.

Quinze types, tous des CONSTATS d'un département propriétaire, que M8 reprend sans les refaire :

- ``m7.signaux_marketing_constates`` : quelle source de données propres a été lue, sur quelle période, avec quelle
  fraîcheur (aucune valeur de mesure : les faits eux-mêmes se lisent chez M7) ;
- ``m7.depenses_marketing_constatees`` : un relevé de dépense (canal, jour, montant en CAD) tel que la plateforme l'a
  donné ;
- ``m7.anomalie_depense_detectee`` : une règle transparente s'est déclenchée (M7 ne propose ni n'exécute aucune
action) ;
- ``m7.conversion_hors_ligne_importee`` : une issue (appel, rendez-vous, soumission signée, vente) rattachée à une
  source normalisée ; elle compte une issue, elle n'explique pas son origine ;
- ``m5.mesures_comptables_constatees`` : les nombres et montants comptés par M5 dans ses propres registres ;
- ``m3.mesure_vision_validee`` : une mesure de vision VALIDÉE (par référence ou par une personne), jamais un candidat ;
- ``m6.reception_enregistree`` : une livraison de matériaux reçue contre un bon de commande (verdict de M6 repris : ni
  fournisseur, ni ligne de prix, ni quantité) ;
- ``m1.commande_courriel_envoyee`` : le courriel d'un bon de commande de M6 est parti (après l'approbation humaine du
  sas de M1) : le bon de commande et l'instant, ni le brouillon ni l'adresse.

Sept types de la phase 2 (D1 à D3 de ``docs/architecture/M8-ENTREPOT-SOURCES.md`` : les producteurs publient des RÉSUMÉS
agrégés, M8 n'appelle aucun de leurs outils et n'a obtenu aucun droit nouveau) :

- ``m5.depense_publicitaire_constatee`` (D1) : ce que le grand livre de M5 a COMPTABILISÉ des dépenses publicitaires
  de M7 sur une période, et ce qui attend encore sa validation ; le plus grand ``sequence`` fait foi ;
- ``m5.facture_emise_constatee`` (D3) : une facture ENVOYÉE (puis payée ou annulée), sans client : l'état le plus avancé
  fait foi ;
- ``m7.performance_signaux_constatee`` : les clics, impressions et visites du SITE d'une source propre pour une période
;
- ``m4.capacite_equipe_constatee`` : les heures d'équipe DÉCLARÉES et les heures de cédule planifiées d'une semaine ;
- ``m2.pipeline_constate`` : les comptes du pipeline commercial, le taux de conversion des résolus, la valeur pondérée ;
- ``m6.disponibilite_constatee`` : cinq comptes de disponibilité du matériel ;
- ``m1.plaintes_constatees`` : l'ÉTAT de la lecture des plaintes et leur nombre seulement s'il est CONNUE.
Pour ces sept types, la version qui fait foi est celle de la publication la plus récente (``publie_le``, donné par le
bus) : l'ordre de livraison n'est pas garanti. Aucun n'entre dans la section « operations_recues » de la vue exécutive ;
ils se lisent par leurs mesures du catalogue.

Principes :

1. TEL QUEL. M8 ne recalcule ni ne corrige un constat. La seule arithmétique est la SOMME des relevés de dépense reçus,
   par canal, en ``Decimal`` : elle est libellée « somme des relevés reçus » (jamais « dépense totale »), refusée quand
   les bases de taxes des relevés diffèrent, et dit les jours que les relevés couvrent. Un jour sans relevé n'est jamais
   un zéro.
2. IDEMPOTENT. Chaque fait a une clé de CONTENU (``cles_unicite``), pas l'identifiant d'événement : le même constat
   rejoué sous un autre ``evenement_id`` n'ajoute rien.
3. SANS PERSONNE. Aucun nom, courriel, téléphone ni identifiant publicitaire : ils ne sont pas dans les charges, et
   la vision ne garde ni la photo ni le modèle. Le ``lead_id`` d'une conversion est un identifiant de M2.
4. FICTIF À PART. Un constat ``fictif`` (compte de démonstration) est rangé mais n'entre dans aucune somme ni liste :
   il est compté dans ``fictifs_ignores``.
5. ABSENT = « manque ». Sans aucun fait, la section n'existe pas (la vue exécutive reste inchangée).
6. PROVENANCE. Chaque fait porte `provenance` : le type d'événement source, l'identifiant d'événement quand la charge
   en porte un, et l'EMPREINTE de la charge reçue (avant toute réduction). Elle ne fait pas partie de la clé de
   contenu : le même constat rejoué sous un autre `evenement_id` n'ajoute toujours rien.

Les mesures d'entreprise du catalogue qui en dérivent (dépenses de M7, créances de M5, réceptions de M6...) sont dans
``mesures_interdepartements.py`` ; la section « operations_recues » de la vue exécutive ne montre ni les réceptions ni
les commandes.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from . import encodage

TYPE_SIGNAUX = "signaux_marketing_constates"
TYPE_DEPENSE = "depense_marketing_constatee"
TYPE_ANOMALIE = "anomalie_depense_detectee"
TYPE_CONVERSION = "conversion_hors_ligne_importee"
TYPE_MESURES_COMPTABLES = "mesures_comptables_constatees"
TYPE_MESURE_VISION = "mesure_vision_validee"
TYPE_RECEPTION = "reception_materiaux"
TYPE_COMMANDE = "commande_envoyee"
TYPE_DEPENSE_COMPTABILISEE = "depense_pub_comptabilisee"
TYPE_FACTURE_EMISE = "facture_emise"
TYPE_PERFORMANCE = "performance_signaux"
TYPE_CAPACITE = "capacite_equipe"
TYPE_PIPELINE = "pipeline_commercial"
TYPE_DISPONIBILITE = "disponibilite_materiel"
TYPE_PLAINTES = "plaintes_constatees"

EVENEMENT_PAR_TYPE = {
    "m7.signaux_marketing_constates": TYPE_SIGNAUX,
    "m7.depenses_marketing_constatees": TYPE_DEPENSE,
    "m7.anomalie_depense_detectee": TYPE_ANOMALIE,
    "m7.conversion_hors_ligne_importee": TYPE_CONVERSION,
    "m5.mesures_comptables_constatees": TYPE_MESURES_COMPTABLES,
    "m3.mesure_vision_validee": TYPE_MESURE_VISION,
    "m6.reception_enregistree": TYPE_RECEPTION,
    "m1.commande_courriel_envoyee": TYPE_COMMANDE,
    "m5.depense_publicitaire_constatee": TYPE_DEPENSE_COMPTABILISEE,
    "m5.facture_emise_constatee": TYPE_FACTURE_EMISE,
    "m7.performance_signaux_constatee": TYPE_PERFORMANCE,
    "m4.capacite_equipe_constatee": TYPE_CAPACITE,
    "m2.pipeline_constate": TYPE_PIPELINE,
    "m6.disponibilite_constatee": TYPE_DISPONIBILITE,
    "m1.plaintes_constatees": TYPE_PLAINTES,
}
_EVENEMENT_DU_TYPE = {type_entree: evenement for evenement, type_entree in EVENEMENT_PAR_TYPE.items()}

MENTION_COMPTABLE = "À valider auprès d'un comptable (CPA) / professionnel qualifié"
_CLES_UNICITE = {
    TYPE_SIGNAUX: (
        "source",
        "compte_ref",
        "flux",
        "periode_debut",
        "periode_fin",
        "derniere_lecture_reussie_le",
    ),
    TYPE_DEPENSE: ("releve_id", "revision"),
    TYPE_ANOMALIE: ("anomalie_id",),
    TYPE_CONVERSION: ("conversion_id",),
    TYPE_MESURES_COMPTABLES: ("date_reference", "version_donnees"),
    TYPE_MESURE_VISION: ("candidat_id",),
    TYPE_RECEPTION: ("po_id", "hash_maillon"),
    TYPE_COMMANDE: ("po_id",),
    # Phase 2. La clé est celle du CONTENU constaté : le même constat rejoué sous un autre `evenement_id` n'ajoute rien
    # ;
    # un retour à une version antérieure des données (autre `sequence`, autre `constate_le`) est un fait de plus.
    TYPE_DEPENSE_COMPTABILISEE: ("periode_debut", "periode_fin", "sequence"),
    TYPE_FACTURE_EMISE: ("facture_id", "statut"),
    TYPE_PERFORMANCE: ("source", "compte_ref", "periode_debut", "periode_fin", "version_donnees"),
    TYPE_CAPACITE: ("semaine_debut", "portee", "version_donnees", "constate_le"),
    TYPE_PIPELINE: ("date_reference", "version_donnees", "constate_le"),
    TYPE_DISPONIBILITE: ("date_reference", "version_donnees", "constate_le"),
    TYPE_PLAINTES: ("date_reference", "jours", "empreinte_contenu"),
}
# Les types dont deux versions du même objet ne s'ordonnent que par l'instant de PUBLICATION donné par le bus
# (`publie_le`).
_TYPES_ORDONNES_PAR_PUBLICATION = frozenset(
    {
        TYPE_MESURES_COMPTABLES,
        TYPE_DEPENSE_COMPTABILISEE,
        TYPE_FACTURE_EMISE,
        TYPE_PERFORMANCE,
        TYPE_CAPACITE,
        TYPE_PIPELINE,
        TYPE_DISPONIBILITE,
        TYPE_PLAINTES,
    }
)
# Phase 2 : ce que M8 garde de chaque résumé, exactement les propriétés fermées du catalogue d'événements (une propriété
# de plus ne traverse jamais : la charge est réduite à cette liste avant d'être rangée).
_CLES_PHASE_2 = {
    TYPE_DEPENSE_COMPTABILISEE: (
        "sequence",
        "date_reference",
        "periode_debut",
        "periode_fin",
        "version_donnees",
        "devise",
        "base_taxes",
        "comptabilise_cad",
        "ecritures_definitives",
        "brouillons_en_attente",
        "brouillons_en_attente_cad",
    ),
    TYPE_FACTURE_EMISE: (
        "facture_id",
        "statut",
        "emise_le",
        "devise",
        "montant_avant_taxes_cad",
        "total_taxes_cad",
        "montant_apres_taxes_cad",
    ),
    TYPE_PERFORMANCE: (
        "source",
        "compte_ref",
        "periode_debut",
        "periode_fin",
        "jours_periode",
        "jours_couverts",
        "clics",
        "impressions",
        "visites",
        "derniere_observation_le",
        "fraicheur_fenetre_h",
        "fictif",
        "version_donnees",
    ),
    TYPE_CAPACITE: (
        "semaine_debut",
        "portee",
        "calculable",
        "heures_disponibles",
        "heures_planifiees",
        "manque",
        "constate_le",
        "version_donnees",
    ),
    TYPE_PIPELINE: (
        "date_reference",
        "constate_le",
        "version_donnees",
        "total",
        "ouverts",
        "par_statut",
        "convertis_un_jour",
        "perdus",
        "resolus",
        "taux_conversion_resolus_pct",
        "valeur_ponderee_cad",
    ),
    TYPE_DISPONIBILITE: (
        "date_reference",
        "constate_le",
        "version_donnees",
        "articles_suivis",
        "articles_en_rupture",
        "articles_sur_reserves",
        "reservations_actives",
        "reservations_incompletes",
    ),
    TYPE_PLAINTES: ("date_reference", "jours", "etat", "nombre", "empreinte_contenu"),
}
# Ce que M8 garde d'une mesure de vision : ni la photo, ni le modèle, ni l'empreinte de décision.
_CLES_VISION = (
    "lead_id",
    "candidat_id",
    "grandeur",
    "unite",
    "valeur_retenue",
    "incertitude_emploi",
    "origine_valeur",
    "voie",
)
# Ce que M8 garde d'une réception de M6 : le bon de commande, l'empreinte du mouvement de stock, l'instant, le verdict
# et le statut du bon. Ni le fournisseur, ni le chantier, ni les lignes (prix et quantités) : la réception se compte,
# elle ne se rejoue pas.
_CLES_RECEPTION = ("po_id", "hash_maillon", "horodatage_reception", "verdict_reception", "statut_po")
# Ce que M8 garde d'une commande envoyée par M1 : le bon de commande et l'instant. Ni le brouillon, ni l'empreinte du
# courriel.
_CLES_COMMANDE = ("po_id", "envoye_le")
TYPES_PHASE_2 = frozenset(_CLES_PHASE_2)
_TYPES_HORS_SECTION = frozenset({TYPE_RECEPTION, TYPE_COMMANDE, *TYPES_PHASE_2})
_ANOMALIES_LISTEES = 5
_ORDRE_SEVERITE = {"critique": 0, "attention": 1, "info": 2}


def fait(type_entree: str, charge: dict[str, Any], publie_le: str | None = None) -> dict[str, Any]:
    """Le fait rangé : la charge validée par le catalogue du socle, avec son type d'entrée. La vision est réduite à
    l'essentiel (ni photo ni modèle). `publie_le` : instant de PUBLICATION donné par le bus, gardé pour les constats
    dont
    deux versions du même objet ne s'ordonnent que par lui (comptables et résumés de la phase 2 : l'ordre de livraison
    n'est
    pas garanti) ; il n'entre dans aucune clé de contenu."""
    if type_entree not in _CLES_UNICITE:
        raise ValueError(f"type d'entrée inconnu : {type_entree!r}")
    provenance = {
        "evenement": _EVENEMENT_DU_TYPE[type_entree],
        "evenement_id": charge.get("evenement_id") if isinstance(charge.get("evenement_id"), str) else None,
        "empreinte": encodage.empreinte(charge),
    }
    if type_entree == TYPE_MESURE_VISION:
        return {"type_entree": type_entree, **{cle: charge[cle] for cle in _CLES_VISION}, "provenance": provenance}
    if type_entree == TYPE_COMMANDE:
        return {"type_entree": type_entree, **{cle: charge[cle] for cle in _CLES_COMMANDE}, "provenance": provenance}
    if type_entree == TYPE_RECEPTION:
        return {"type_entree": type_entree, **{cle: charge[cle] for cle in _CLES_RECEPTION}, "provenance": provenance}
    if type_entree in _CLES_PHASE_2:
        rangee = {
            "type_entree": type_entree,
            **{cle: charge[cle] for cle in _CLES_PHASE_2[type_entree]},
            "provenance": provenance,
        }
    else:
        rangee = {"type_entree": type_entree, **charge, "provenance": provenance}
    if type_entree in _TYPES_ORDONNES_PAR_PUBLICATION and publie_le is not None:
        rangee["publie_le"] = publie_le
    return rangee


def cles_unicite(type_entree: str) -> tuple[str, ...]:
    return _CLES_UNICITE[type_entree]


# Ce qui n'est PAS du contenu constaté : la provenance (son empreinte couvre l'`evenement_id` du bus, qui change à
# chaque rejeu) et l'instant de publication. Deux faits de même clé qui ne diffèrent que par ces champs sont un rejeu.
CHAMPS_NON_COMPARES = ("provenance", "publie_le")


def contenu_compare(fait_range: dict[str, Any]) -> dict[str, Any]:
    """Le contenu d'un fait rangé, sans provenance ni instant de publication (ce que deux livraisons partagent)."""
    return {cle: valeur for cle, valeur in fait_range.items() if cle not in CHAMPS_NON_COMPARES}


def evenement_du_type(type_entree: str) -> str:
    return _EVENEMENT_DU_TYPE[type_entree]


def resume_recu(type_entree: str, fait_range: dict[str, Any]) -> dict[str, Any]:
    """Ce que le reçu du bus garde : l'identifiant du constat, jamais un montant ni une valeur."""
    cle = _CLES_UNICITE[type_entree][0]
    resume = {"type_entree": type_entree, cle: fait_range[cle]}
    if type_entree == TYPE_DEPENSE:
        resume["revision"] = fait_range["revision"]
    return resume


# ---------------------------------------------------------------------------
# Lecture
# ---------------------------------------------------------------------------
def _de_type(faits: list[dict[str, Any]], type_entree: str) -> list[dict[str, Any]]:
    return [f for f in faits if f.get("type_entree") == type_entree]


_PLUS_ANCIEN = datetime.min.replace(tzinfo=UTC)


def _instant(texte: Any) -> datetime | None:
    try:
        quand = datetime.fromisoformat(texte) if isinstance(texte, str) else None
    except ValueError:
        return None
    return quand if quand is not None and quand.tzinfo is not None else None


def _signaux(faits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    derniers: dict[str, tuple[datetime, dict[str, Any]]] = {}
    for f in _de_type(faits, TYPE_SIGNAUX):
        quand = _instant(f.get("derniere_lecture_reussie_le"))
        if quand is None or f.get("fictif") is True:
            continue
        actuel = derniers.get(f["source"])
        if actuel is None or quand >= actuel[0]:
            derniers[f["source"]] = (quand, f)
    return [
        {
            "source": source,
            "periode_fin": f["periode_fin"],
            "donnees_jusqu_au": f["donnees_jusqu_au"],
            "derniere_lecture_reussie_le": f["derniere_lecture_reussie_le"],
            "fraicheur_fenetre_h": f["fraicheur_fenetre_h"],
            "mode": f["mode"],
        }
        for source, (_, f) in sorted(derniers.items())
    ]


def _depenses(faits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Par canal, la somme des DERNIÈRES révisions de chaque relevé (un relevé révisé remplace le sien, jamais ne
    s'additionne à lui). Bases de taxes mixtes : pas de somme, la raison est dite."""
    dernieres: dict[str, dict[str, Any]] = {}
    for f in _de_type(faits, TYPE_DEPENSE):
        actuelle = dernieres.get(f["releve_id"])
        if actuelle is None or f["revision"] > actuelle["revision"]:
            dernieres[f["releve_id"]] = f
    par_canal: dict[str, list[dict[str, Any]]] = {}
    for f in dernieres.values():
        par_canal.setdefault(f["canal"], []).append(f)
    sortie = []
    for canal, releves in sorted(par_canal.items()):
        bases = sorted({r["base_taxes"] for r in releves})
        ligne: dict[str, Any] = {
            "canal": canal,
            "releves": len(releves),
            "periode_debut": min(r["periode_debut"] for r in releves),
            "periode_fin": max(r["periode_fin"] for r in releves),
            "libelle": "somme des relevés reçus (les jours sans relevé ne sont pas des zéros)",
        }
        if len(bases) != 1:
            ligne["somme_cad"] = None
            ligne["raison"] = "bases de taxes différentes entre les relevés : aucune somme"
        else:
            try:
                ligne["somme_cad"] = str(sum((Decimal(r["montant_cad"]) for r in releves), Decimal("0")))
            except InvalidOperation:  # pragma: no cover — le catalogue du socle a validé le format
                ligne["somme_cad"] = None
                ligne["raison"] = "montant illisible"
            ligne["base_taxes"] = bases[0]
        sortie.append(ligne)
    return sortie


def _anomalies(faits: list[dict[str, Any]]) -> dict[str, Any]:
    vues = [f for f in _de_type(faits, TYPE_ANOMALIE) if f.get("fictif") is not True]
    par_severite = Counter(f["severite"] for f in vues)
    ordonnees = sorted(vues, key=lambda f: (_ORDRE_SEVERITE.get(f["severite"], 9), f["jour_fin"], f["anomalie_id"]))
    return {
        "total": len(vues),
        "par_severite": dict(sorted(par_severite.items())),
        "plus_graves": [
            {
                "anomalie_id": f["anomalie_id"],
                "canal": f["canal"],
                "regle": f["regle"],
                "severite": f["severite"],
                "jour_fin": f["jour_fin"],
            }
            for f in ordonnees[:_ANOMALIES_LISTEES]
        ],
        "reste": max(0, len(ordonnees) - _ANOMALIES_LISTEES),
    }


def _conversions(faits: list[dict[str, Any]]) -> dict[str, Any]:
    vues = _de_type(faits, TYPE_CONVERSION)
    return {
        "total": len(vues),
        "par_type": dict(sorted(Counter(f["type"] for f in vues).items())),
        "par_source": dict(sorted(Counter(f["utm_source"] or "source_inconnue" for f in vues).items())),
        "avec_source_normalisee": sum(1 for f in vues if f["source_normalisee"] is True),
    }


def dernier_constat_comptable(faits: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Le dernier constat des mesures comptables de M5 : la plus grande date de référence, puis la publication la plus
    récente (`publie_le`, donné par le bus), puis le dernier reçu. Quel que soit l'ordre de livraison du bus.
    ``None`` sans constat. Une seule règle, pour la vue exécutive comme pour les mesures du catalogue."""
    constats = _de_type(faits, TYPE_MESURES_COMPTABLES)
    if not constats:
        return None
    # Le dernier constat : la plus grande date de référence, puis la publication la plus récente (une version nouvelle
    # le même jour est un nouveau constat ; la livraison n'est pas ordonnée), puis le dernier reçu.
    indice = max(
        range(len(constats)),
        key=lambda i: (constats[i]["date_reference"], _instant(constats[i].get("publie_le")) or _PLUS_ANCIEN, i),
    )
    return constats[indice]


def _mesures_comptables(faits: list[dict[str, Any]], aujourd_hui: str | None) -> dict[str, Any] | None:
    constats = _de_type(faits, TYPE_MESURES_COMPTABLES)
    dernier = dernier_constat_comptable(faits)
    if dernier is None:
        return None
    age = None
    if aujourd_hui is not None:
        try:
            age = (datetime.fromisoformat(aujourd_hui) - datetime.fromisoformat(dernier["date_reference"])).days
        except ValueError:
            age = None
    return {
        "constats_recus": len(constats),
        "dernier": {
            cle: dernier[cle]
            for cle in (
                "date_reference",
                "version_donnees",
                "creances",
                "relances_en_brouillon",
                "brouillons_en_attente",
                "ecritures_definitives",
                "derniere_periode_close",
                "rapprochements",
            )
        },
        "age_jours": age,
        "mention": MENTION_COMPTABLE,
    }


def section(faits: list[dict[str, Any]], aujourd_hui: str | None = None) -> dict[str, Any] | None:
    """La section « operations_recues » de la vue exécutive, ou ``None`` sans aucun fait (la vue reste inchangée). Les
    réceptions de matériaux de M6, les commandes envoyées et les résumés de la phase 2 n'y figurent pas : ils se lisent
    par
    leurs mesures du catalogue."""
    faits = [f for f in faits if f.get("type_entree") not in _TYPES_HORS_SECTION]
    if not faits:
        return None
    visions = _de_type(faits, TYPE_MESURE_VISION)
    fictifs = sum(1 for f in faits if f.get("fictif") is True and f.get("type_entree") in (TYPE_SIGNAUX, TYPE_ANOMALIE))
    resultat: dict[str, Any] = {
        "source": "constats de M7, M5 et M3 par le bus, repris tels quels",
        "devise": "CAD",
        "constats_recus": len(faits),
        "marketing": {
            "signaux_par_source": _signaux(faits),
            "depenses_par_canal": _depenses(faits),
            "anomalies": _anomalies(faits),
        },
    }
    conversions = _conversions(faits)
    if conversions["total"]:
        resultat["marketing"]["conversions_hors_ligne"] = conversions
    if visions:
        resultat["mesures_vision_validees"] = {
            "total": len(visions),
            "par_origine": dict(sorted(Counter(f["origine_valeur"] for f in visions).items())),
        }
    if fictifs:
        resultat["fictifs_ignores"] = fictifs
    comptables = _mesures_comptables(faits, aujourd_hui)
    if comptables is not None:
        resultat["comptabilite"] = comptables
    return resultat


def reduire(section_lue: dict[str, Any]) -> bool:
    """Dernier recours de la borne de sortie du socle, quand il ne reste plus aucune liste à raccourcir : retire un
    niveau
    de détail de la section et le DIT (``omis``), jamais en silence. Échelle, du moins au plus important : les anomalies
    les plus graves (leur nombre reste), le détail des relevés de dépense (la somme reste), les sources de signaux (leur
    nombre reste), le détail du constat comptable (date, version et total des créances restent), puis la section
    elle-même (réduite à son compte et à un renvoi). Rend faux quand il n'y a plus rien à retirer."""
    if "marketing" not in section_lue:
        return False  # déjà réduite à son compte
    marketing = section_lue["marketing"]
    omis = section_lue.setdefault("omis", [])
    anomalies = marketing["anomalies"]
    if "plus_graves" in anomalies:
        anomalies["plus_graves_omises"] = len(anomalies.pop("plus_graves"))
        omis.append("anomalies.plus_graves")
        return True
    if any("libelle" in ligne for ligne in marketing["depenses_par_canal"]):
        for ligne in marketing["depenses_par_canal"]:
            ligne.pop("libelle", None)
            ligne.pop("periode_debut", None)
            ligne.pop("periode_fin", None)
        omis.append("depenses_par_canal.libelle_et_periode")
        return True
    if isinstance(marketing["signaux_par_source"], list):
        marketing["signaux_par_source"] = len(marketing["signaux_par_source"])
        omis.append("signaux_par_source.detail")
        return True
    dernier = section_lue.get("comptabilite", {}).get("dernier")
    if dernier is not None and "rapprochements" in dernier:
        section_lue["comptabilite"]["dernier"] = {
            "date_reference": dernier["date_reference"],
            "version_donnees": dernier["version_donnees"],
            "creances": {"nombre": dernier["creances"]["nombre"], "total": dernier["creances"]["total"]},
        }
        omis.append("comptabilite.dernier.detail")
        return True
    if "marketing" in section_lue:
        # Dernier niveau : la section entière cède la place à son compte, dit et jamais silencieux. La vue exécutive de
        # base ne doit JAMAIS échouer à cause d'une section d'interconnexion.
        recus = section_lue["constats_recus"]
        section_lue.clear()
        section_lue.update(
            {
                "omise_pour_tenir_sous_la_borne": True,
                "constats_recus": recus,
                "a_lire": "les registres de M7, M5 et M3 (leurs outils de lecture)",
            }
        )
        return True
    return False


__all__ = [
    "EVENEMENT_PAR_TYPE",
    "MENTION_COMPTABLE",
    "TYPE_ANOMALIE",
    "TYPE_CONVERSION",
    "TYPE_DEPENSE",
    "TYPE_MESURES_COMPTABLES",
    "TYPE_MESURE_VISION",
    "TYPE_CAPACITE",
    "TYPE_COMMANDE",
    "TYPE_DEPENSE_COMPTABILISEE",
    "TYPE_DISPONIBILITE",
    "TYPE_FACTURE_EMISE",
    "TYPE_PERFORMANCE",
    "TYPE_PIPELINE",
    "TYPE_PLAINTES",
    "TYPE_RECEPTION",
    "TYPE_SIGNAUX",
    "TYPES_PHASE_2",
    "cles_unicite",
    "dernier_constat_comptable",
    "fait",
    "reduire",
    "resume_recu",
    "section",
]
