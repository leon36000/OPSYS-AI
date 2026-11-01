"""Entrepôt de données de M8 (M8.2) : faits, dimensions et marts DÉRIVÉS des registres, jamais une source de vérité.

Module PUR (ADR-0009) : aucun import d'``opsys`` ni de SQLAlchemy, aucune horloge (``construit_le`` est donné par
l'appelant). Il transforme le contenu des quatre registres de M8 (``faits_chantier``, ``faits_entonnoir``,
``faits_contenus``, ``faits_cash_libre``) en LIGNES de tables d'un schéma en étoile ; ``entrepot_stockage.py``
(adaptateur)
les écrit dans les tables ``m8_ent_*`` de l'instance (migration 0046, portable SQLite et PostgreSQL).

Principes :

1. DÉRIVÉ ET RECONSTRUCTIBLE. Les registres restent la vérité. Détruire l'entrepôt ne perd rien : la reconstruction
repart
   des registres et rend les mêmes lignes (déterministe : mêmes faits, même catalogue, mêmes lignes, même identifiant).
2. VERSIONNÉ. Une construction porte ``version_schema`` (celle de CE module), ``version_catalogue`` (empreinte du
   catalogue) et ``empreinte_registres`` (empreinte du contenu des registres). Une construction dont ces trois valeurs
   sont
   celles de la précédente est ``inchangee`` : rien n'est réécrit.
3. FRAÎCHEUR ET PROVENANCE PAR MESURE. Chaque ligne de ``m8_ent_mesures_courantes`` garde la source gouvernée, la
version
   de la définition, l'instant du dernier fait qui porte la mesure et la fenêtre de fraîcheur DÉCLARÉE. Le STATUT de
   fraîcheur, lui, n'est pas stocké : il dépend de l'heure de la lecture (``fraicheur_mesures``) ; un entrepôt ne fige
   jamais « à jour ».
4. SANS PERSONNE. Ni technicien (le fait ``wct`` en porte un : il n'est pas repris), ni client, ni contact. Des
   identifiants d'affaire, des instants, des comptes et des montants arrêtés par les départements propriétaires.
5. HONNÊTE. Une mesure non calculable reste non calculable (``valeur`` absente) ; un fait absent est une colonne vide,
   jamais un zéro.

Tables : une dimension par chantier (``m8_ent_dim_chantier``) et par lead (``m8_ent_dim_lead``), un fait par devis
(``m8_ent_fait_devis``), deux marts (``m8_ent_mesures_courantes`` : les mesures du catalogue ;
``m8_ent_mart_contenus`` :
ce que chaque contenu a amené), l'historique des mesures par construction (``m8_ent_mesures_hist``) et le journal des
constructions (``m8_ent_constructions``).
"""

from __future__ import annotations

import re
from typing import Any

from . import contenus, encodage, entonnoir, mesures_chantier, moteur_mesures

VERSION_SCHEMA = 1

TABLE_CONSTRUCTIONS = "m8_ent_constructions"
TABLE_MESURES = "m8_ent_mesures_courantes"
TABLE_HISTORIQUE = "m8_ent_mesures_hist"
TABLE_CHANTIER = "m8_ent_dim_chantier"
TABLE_LEAD = "m8_ent_dim_lead"
TABLE_DEVIS = "m8_ent_fait_devis"
TABLE_CONTENUS = "m8_ent_mart_contenus"

# Tables de la construction COURANTE (remplacées en bloc) : l'historique et le journal des constructions s'ajoutent.
_TABLES_COURANTES = (TABLE_MESURES, TABLE_CHANTIER, TABLE_LEAD, TABLE_DEVIS, TABLE_CONTENUS)


def tables_courantes() -> tuple[str, ...]:
    """Les tables de la construction COURANTE (remplacées en bloc)."""
    return _TABLES_COURANTES


def _entier(valeur: Any) -> int | None:
    """Un entier lu d'un entier ou d'un texte d'entier ; ``None`` sinon (un booléen n'est pas un nombre). Jamais un
    zéro à la place d'une durée absente."""
    if isinstance(valeur, bool):
        return None
    if isinstance(valeur, int):
        return valeur
    # Un seul signe et des chiffres ASCII : `lstrip("-")` retirait tous les signes (« --5 » levait `ValueError`) et
    # `isdigit` accepte les chiffres Unicode.
    if isinstance(valeur, str) and re.fullmatch(r"-?[0-9]+", valeur.strip()):
        return int(valeur.strip())
    return None


def _texte(valeur: Any) -> str | None:
    return None if valeur is None else str(valeur)


def identifiant_construction(version_catalogue: str, empreinte_registres: str, rang_precedent: int) -> str:
    """L'identifiant d'une construction : déterministe (mêmes entrées, même identifiant) et chaîné à la construction qui
    la précède, pour qu'un retour à un état déjà vu reste une construction distincte du journal."""
    return encodage.empreinte("m8-entrepot", VERSION_SCHEMA, version_catalogue, empreinte_registres, rang_precedent)


def meme_etat(construction: dict[str, Any] | None, version_catalogue: str, empreinte_registres: str) -> bool:
    """Vrai si la dernière construction a été faite sur CE schéma, CE catalogue et CES registres : rien à
    reconstruire."""
    return (
        construction is not None
        and construction["version_schema"] == VERSION_SCHEMA
        and construction["version_catalogue"] == version_catalogue
        and construction["empreinte_registres"] == empreinte_registres
    )


# ---------------------------------------------------------------------------
# Lignes
# ---------------------------------------------------------------------------
def _lignes_mesures(mesures: list[dict[str, Any]], construction_id: str) -> list[dict[str, Any]]:
    lignes = []
    for mesure in mesures:
        declaree = mesure["fraicheur_declaree"]
        lignes.append(
            {
                "metric_id": mesure["metric_id"],
                "construction_id": construction_id,
                "nom": mesure["nom"],
                "domaine": mesure["domaine"],
                "sens": mesure["sens"],
                "sensibilite": mesure["sensibilite"],
                "proprietaire": mesure["proprietaire"],
                "unite": mesure["unite"],
                "statut": mesure["statut"],
                "valeur": mesure["valeur"],
                "detail": mesure["detail"],
                "source": mesure["source"],
                "version_definition": mesure["version_definition"],
                "dernier_fait_le": mesure["dernier_fait_le"],
                "fraicheur_attendue_s": declaree.get("fenetre_s"),
                "fraicheur_terminale": declaree.get("terminale") is True,
            }
        )
    return lignes


def _lignes_historique(
    mesures: list[dict[str, Any]],
    construction_id: str,
    construit_le: str,
) -> list[dict[str, Any]]:
    return [
        {
            "construction_id": construction_id,
            "metric_id": mesure["metric_id"],
            "construit_le": construit_le,
            "statut": mesure["statut"],
            "valeur": mesure["valeur"],
            "version_definition": mesure["version_definition"],
            "dernier_fait_le": mesure["dernier_fait_le"],
        }
        for mesure in mesures
    ]


def _lignes_chantiers(faits_chantier: list[dict[str, Any]], construction_id: str) -> list[dict[str, Any]]:
    identifiants: list[str] = []
    for fait in faits_chantier:
        wct_id = fait.get("wct_id")
        if fait.get("type_entree") == "wct" and isinstance(wct_id, str) and wct_id and wct_id not in identifiants:
            identifiants.append(wct_id)
    lignes = []
    for wct_id in identifiants:
        faits = mesures_chantier.assembler_faits(wct_id, faits_chantier)
        if faits is None:  # pragma: no cover - l'identifiant vient d'un fait wct
            continue
        wct, devis, variance, rentabilite = faits["wct"], faits["devis"], faits["variance"], faits["rentabilite"]
        evaluee = variance is not None and variance.get("statut_variance") == "evaluee"
        lignes.append(
            {
                "wct_id": wct_id,
                "construction_id": construction_id,
                "devis_id": wct.get("devis_id"),
                "termine_le": wct["horodatage_completion"],
                "duree_reelle_minutes": _entier(wct.get("duree_reelle_minutes")),
                "duree_estimee_minutes": _entier(devis.get("duree_estimee_minutes")) if devis is not None else None,
                "statut_wct": _texte(wct.get("statut")),
                "variance_statut": _texte(variance.get("statut_variance")) if variance is not None else None,
                "signal_materiaux": variance.get("signal_critique")
                if evaluee and isinstance(variance.get("signal_critique"), bool)
                else None,
                "verdict_marge": _texte(rentabilite.get("verdict")) if rentabilite is not None else None,
                "marge_reelle_cad": _texte(rentabilite.get("marge_reelle_cad")) if rentabilite is not None else None,
            }
        )
    return lignes


def _premier_par_cle(faits: list[dict[str, Any]], type_entree: str, cle: str) -> dict[str, dict[str, Any]]:
    premiers: dict[str, dict[str, Any]] = {}
    for fait in faits:
        identifiant = fait.get(cle)
        if fait.get("type_entree") == type_entree and isinstance(identifiant, str) and identifiant:
            premiers.setdefault(identifiant, fait)
    return premiers


def _lignes_leads(
    faits_entonnoir: list[dict[str, Any]],
    faits_contenus: list[dict[str, Any]],
    construction_id: str,
) -> list[dict[str, Any]]:
    recus = _premier_par_cle(faits_entonnoir, entonnoir.TYPE_LEAD_RECU, "lead_id")
    qualifies = _premier_par_cle(faits_entonnoir, entonnoir.TYPE_LEAD_QUALIFIE, "lead_id")
    de_m1 = _premier_par_cle(faits_contenus, contenus.TYPE_LEAD_M1, "lead_id")
    identifiants = sorted({*recus, *qualifies, *de_m1})
    return [
        {
            "lead_id": lead_id,
            "construction_id": construction_id,
            "recu_le": recus[lead_id]["horodatage"] if lead_id in recus else None,
            "qualifie_le": qualifies[lead_id]["horodatage"] if lead_id in qualifies else None,
            "utm_content": de_m1[lead_id].get("utm_content") if lead_id in de_m1 else None,
        }
        for lead_id in identifiants
    ]


def _lignes_devis(faits_entonnoir: list[dict[str, Any]], construction_id: str) -> list[dict[str, Any]]:
    envoyes = _premier_par_cle(faits_entonnoir, entonnoir.TYPE_DEVIS_ENVOYE, "devis_id")
    acceptes = _premier_par_cle(faits_entonnoir, entonnoir.TYPE_DEVIS_ACCEPTE, "devis_id")
    constats = _premier_par_cle(faits_entonnoir, entonnoir.TYPE_DEVIS_SANS_REPONSE, "devis_id")
    lignes = []
    for devis_id in sorted({*envoyes, *acceptes, *constats}):
        lead = next((s[devis_id]["lead_id"] for s in (acceptes, envoyes, constats) if devis_id in s), None)
        lignes.append(
            {
                "devis_id": devis_id,
                "construction_id": construction_id,
                "lead_id": lead,
                "envoye_le": envoyes[devis_id]["horodatage"] if devis_id in envoyes else None,
                "accepte_le": acceptes[devis_id]["horodatage"] if devis_id in acceptes else None,
                "prix_total_cad": _texte(acceptes[devis_id].get("prix_total")) if devis_id in acceptes else None,
                "sans_reponse_statut": _texte(constats[devis_id].get("statut")) if devis_id in constats else None,
                "sans_reponse_constate_le": constats[devis_id]["horodatage"] if devis_id in constats else None,
            }
        )
    return lignes


def _lignes_contenus(
    faits_contenus: list[dict[str, Any]],
    faits_entonnoir: list[dict[str, Any]],
    construction_id: str,
) -> list[dict[str, Any]]:
    """Une ligne par contenu exporté. Un décompte est ``None`` quand la mesure est non calculable ou que le contenu ne
    se mesure pas (``sans_lien``, ``ambigu``) : jamais un zéro à la place de ce qu'on ne sait pas (même règle que
    ``contenus.lignes``)."""
    attribution = contenus.attribuer(faits_contenus, faits_entonnoir)
    chaine_lue = bool(attribution["contenus"]) and attribution["leads"]["n_recus"] > 0
    devis_lus = chaine_lue and not attribution["entonnoir_vide"]
    lignes = []
    for contenu in attribution["contenus"]:
        cle = contenu.get("utm_content")
        suivi = contenus.suivi_du_contenu(contenu, attribution["cles_ambigues"])
        mesurable = suivi == contenus.SUIVI_LIEN
        lignes.append(
            {
                "contenu_id": contenu["contenu_id"],
                "construction_id": construction_id,
                "utm_content": cle,
                "canal": contenu.get("canal"),
                "wct_id": contenu.get("wct_id"),
                "exporte_le": contenu.get("horodatage"),
                "suivi": suivi,
                "leads": attribution["leads_par_cle"][cle] if mesurable and chaine_lue else None,
                "devis_envoyes": attribution["devis_envoyes"]["par_cle"][cle] if mesurable and devis_lus else None,
                "devis_acceptes": attribution["devis_acceptes"]["par_cle"][cle] if mesurable and devis_lus else None,
            }
        )
    return sorted(lignes, key=lambda ligne: ligne["contenu_id"])


def construire(
    registres: dict[str, Any],
    catalogue: dict[str, Any],
    *,
    construit_le: str,
    rang_precedent: int,
) -> dict[str, Any]:
    """Toutes les lignes d'une construction : ``{construction, tables}``. ``construit_le`` est l'instant de l'appelant
    (RFC 3339 avec fuseau, refusé sinon). Pure et déterministe : les mêmes registres, le même catalogue et le même rang
    précédent donnent les mêmes lignes et le même identifiant."""
    if entonnoir.instant_lu(construit_le) is None:
        raise ValueError(
            f"REJ-ENTREPOT-INSTANT-INVALIDE : construit_le doit être un instant RFC 3339 avec fuseau "
            f"(reçu {construit_le!r})"
        )
    if type(rang_precedent) is not int or rang_precedent < 0:
        raise ValueError("REJ-ENTREPOT-RANG-INVALIDE : le rang de la construction précédente est un entier ≥ 0")
    lus = moteur_mesures.normaliser_registres(registres)
    empreinte = moteur_mesures.empreinte_registres(lus)
    construction_id = identifiant_construction(catalogue["version_catalogue"], empreinte, rang_precedent)
    mesures = moteur_mesures.lire(lus, catalogue)
    tables = {
        TABLE_MESURES: _lignes_mesures(mesures, construction_id),
        TABLE_CHANTIER: _lignes_chantiers(lus["chantier"], construction_id),
        TABLE_LEAD: _lignes_leads(lus["entonnoir"], lus["contenus"], construction_id),
        TABLE_DEVIS: _lignes_devis(lus["entonnoir"], construction_id),
        TABLE_CONTENUS: _lignes_contenus(lus["contenus"], lus["entonnoir"], construction_id),
        TABLE_HISTORIQUE: _lignes_historique(mesures, construction_id, construit_le),
    }
    return {
        "construction": {
            "construction_id": construction_id,
            "version_schema": VERSION_SCHEMA,
            "version_catalogue": catalogue["version_catalogue"],
            "empreinte_registres": empreinte,
            "construit_le": construit_le,
            "nb_mesures": len(mesures),
            "comptes": {nom: len(lignes) for nom, lignes in tables.items()},
        },
        "tables": tables,
    }


__all__ = [
    "TABLE_CHANTIER",
    "TABLE_CONSTRUCTIONS",
    "TABLE_CONTENUS",
    "TABLE_DEVIS",
    "TABLE_HISTORIQUE",
    "TABLE_LEAD",
    "TABLE_MESURES",
    "VERSION_SCHEMA",
    "construire",
    "identifiant_construction",
    "meme_etat",
    "tables_courantes",
]
