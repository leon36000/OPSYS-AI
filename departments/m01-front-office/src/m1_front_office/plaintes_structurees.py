"""Plaintes structurées de M1, en lecture seule (`m1.plaintes_structurees`, contrat v1).

M1 sait déjà reconnaître une plainte (`plaintes.py`) et l'ouvrir en transfert à un humain (`transferts.py`) ; il n'avait
aucune lecture qui le DIT à un consommateur sans passer par un texte (`m1_produire_digest` compte des transferts en
phrases). Ce module projette le registre anti-perte en une lecture structurée, datée et sans donnée personnelle, que le
conseil stratégique (M9) peut citer sans rien déduire de plus que ce que M1 établit.

**Une absence n'est pas un zéro.** La lecture porte un ÉTAT, jamais un simple compte :

- `CONNUE` : au moins un transfert de plainte ou d'urgence est au registre pour la période ;
- `AUCUNE_DECLAREE_PAR_SOURCE` : M1 reçoit (le vocabulaire des plaintes est configuré, des signaux sont au registre) et
  n'a reconnu ni escaladé aucune plainte dans la période. Ce n'est PAS « il n'y a eu aucune plainte » : une plainte que
  les règles ne reconnaissent pas, ou qu'aucun canal de M1 n'a reçue, n'y figure pas (voir `LIMITES`) ;
- `NON_BRANCHEE` : M1 ne peut pas se prononcer (vocabulaire des plaintes absent ou invalide, ou aucun signal reçu au
  registre). Le nombre est alors `null`, jamais 0.

**Lecture datée.** L'appelant fournit `date_reference` (le jour de la lecture, comme `m1_produire_digest` : aucune
horloge ici) et la période se termine ce jour-là, inclus. Tout est lu « tel qu'à la fin de ce jour » : un transfert clos
après ce jour compte encore pour ouvert. `revision` donne de quoi détecter deux lectures du même jour qui ne disent pas
la même chose, sans jamais les fusionner : la même (`date_lecture`, `periode`) avec une `empreinte_contenu` différente
est une CONTRADICTION à signaler, pas à moyenner ; la même empreinte avec une autre tête de registre n'est qu'un
rafraîchissement.

**Loi 25.** Aucune donnée personnelle : ni contact, ni `conversation_id` (une empreinte du numéro), ni `transfert_id`,
ni texte du client, ni résumé (un résumé fourni par l'agent est du texte libre), ni terme du vocabulaire. L'identifiant
d'une plainte est un pseudonyme à sens unique dérivé du transfert (`identifiant_plainte`) : M1 retrouve le transfert, le
lecteur ne retrouve ni la conversation ni la personne. Chaque champ texte est soit un instant, soit une valeur d'un
ensemble fermé : un texte libre (injection comprise) n'a aucun chemin jusqu'à la sortie.

**Gravité.** M1 ne reçoit aucune gravité déclarée par le client ni par une source : `gravite` vaut toujours `null`.
Le niveau d'attente interne (N4/N5) ordonne la file « À voir » ; ce n'est pas une gravité et il n'est pas exposé.

Module pur : aucune horloge, aucun accès à la base ni au réseau.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from opsys import taxonomie

from . import plaintes, transferts

LECTURE = "m1.plaintes_structurees"
SCHEMA_VERSION = 1
DEPARTEMENT = "m01-front-office"
REGISTRE = "principal"

ETAT_CONNUE = "CONNUE"
ETAT_AUCUNE_DECLAREE = "AUCUNE_DECLAREE_PAR_SOURCE"
ETAT_NON_BRANCHEE = "NON_BRANCHEE"
ETATS = (ETAT_CONNUE, ETAT_AUCUNE_DECLAREE, ETAT_NON_BRANCHEE)

MOTIF_PLAINTES_AU_REGISTRE = "TRANSFERTS_DE_PLAINTE_AU_REGISTRE"
MOTIF_REGISTRE_LU_SANS_PLAINTE = "REGISTRE_LU_SANS_TRANSFERT_DE_PLAINTE"
MOTIF_VOCABULAIRE_A_CONFIGURER = "VOCABULAIRE_A_CONFIGURER"
MOTIF_PROFIL_INVALIDE = "PROFIL_INVALIDE"
MOTIF_AUCUN_SIGNAL = "AUCUN_SIGNAL_AU_REGISTRE"

VOCABULAIRE_CONFIGURE = "CONFIGURE"
VOCABULAIRE_A_CONFIGURER = "A_CONFIGURER"
VOCABULAIRE_INVALIDE = "INVALIDE"

STATUT_OUVERT = "ouvert"
STATUT_CLOS = "clos"

JOURS_DEFAUT = 7
JOURS_MAX = 92

# Ensembles fermés des valeurs textuelles de la sortie : tout autre texte du registre est écarté ou ramené à `inconnue`.
SOURCES = ("sms", "courriel", "formulaire", "texte", "telephone")
SOURCE_INCONNUE = "inconnue"
DECLENCHEURS = (transferts.DECLENCHE_PAR_REGLES, transferts.DECLENCHE_PAR_AGENT)
TYPES = (plaintes.TYPE_PLAINTE, plaintes.TYPE_URGENCE)

# Limites ÉCRITES, constantes (aucun texte du registre) : elles accompagnent toute lecture, pour que le consommateur ne
# lise jamais un compte comme une mesure complète de la réputation.
LIMITES = (
    {
        "code": "COMPTE_DES_PLAINTES_RECONNUES",
        "detail": "Seules les plaintes reconnues par les règles de M1 ou escaladées par l'agent y figurent : une "
                  "plainte non reconnue, ou reçue hors des canaux de M1, n'est pas comptée.",
    },
    {
        "code": "SURVENANCE_EST_LA_RECEPTION",
        "detail": "La date de survenance est celle de la réception du message par M1 ; la date du fait reproché n'est "
                  "pas connue.",
    },
    {
        "code": "GRAVITE_NON_DECLAREE",
        "detail": "Aucune source ne déclare de gravité à M1 : `gravite` vaut null, et le niveau d'attente interne n'en "
                  "est pas une.",
    },
    {
        "code": "VOCABULAIRE_LU_A_L_APPEL",
        "detail": "L'état du vocabulaire des plaintes est celui de l'instance au moment de la lecture, pas celui du "
                  "jour de référence.",
    },
    {
        "code": "JOUR_CIVIL_TEL_QU_ECRIT",
        "detail": "Le jour d'un fait est le jour civil écrit dans l'horodatage de la plateforme, comme "
                  "m1_produire_digest.",
    },
    {
        "code": "UNE_PLAINTE_PAR_TRANSFERT",
        "detail": "Une plainte est un transfert ouvert ; les messages qui s'y rattachent ensuite ne sont pas des "
                  "plaintes de plus. Une plainte à plusieurs catégories compte dans chacune : la somme des catégories "
                  "peut dépasser le total.",
    },
)

# Ce que la lecture AFFIRME (et que l'empreinte couvre) : l'état, la période, les plaintes et les comptes. Le nombre de
# signaux reçus (`source`) éclaire l'état mais n'est pas une affirmation sur les plaintes : un message ordinaire de plus
# change la tête du registre, pas l'empreinte.
CLES_DE_L_EMPREINTE = ("etat", "motif", "lecture", "periode", "plaintes", "comptes")

_JOUR = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
_PREFIXE_IDENTIFIANT = "pl-"


def periode_valide(jours: Any) -> bool:
    """Vrai si `jours` est un entier (pas un booléen) de 1 à `JOURS_MAX`."""
    return isinstance(jours, int) and not isinstance(jours, bool) and 1 <= jours <= JOURS_MAX


def identifiant_plainte(transfert_id: str) -> str:
    """Pseudonyme à sens unique d'une plainte : même transfert, même identifiant ; aucun lien lisible avec le
    `transfert_id`, la conversation ou le correspondant."""
    materiau = f"{LECTURE}|v{SCHEMA_VERSION}|{transfert_id}"
    return _PREFIXE_IDENTIFIANT + hashlib.sha256(materiau.encode("utf-8")).hexdigest()[:20]


def _jour(horodatage: Any) -> str | None:
    """Le jour civil écrit en tête d'un horodatage (`AAAA-MM-JJ`), ou `None` s'il n'y en a pas."""
    if not isinstance(horodatage, str) or _JOUR.fullmatch(horodatage[:10]) is None:
        return None
    return horodatage[:10]


def _instant(horodatage: Any) -> dt.datetime | None:
    try:
        instant = dt.datetime.fromisoformat(horodatage)
    except (TypeError, ValueError, OverflowError):
        return None
    return instant.astimezone(dt.UTC) if instant.tzinfo is not None else None


def _etat_vocabulaire(
    signaux: Mapping[str, Sequence[str]], verdict_profil: Mapping[str, str] | None
) -> tuple[str, tuple[str, ...]]:
    """`(état du vocabulaire, catégories sans terme)`. Vide ou absent : à configurer ; écrit mais cassé : invalide."""
    if signaux:
        return VOCABULAIRE_CONFIGURE, tuple(c for c in plaintes.CATEGORIES if not signaux.get(c))
    invalide = verdict_profil is not None and verdict_profil.get("code") == taxonomie.VERDICT_PROFIL_INVALIDE
    return (VOCABULAIRE_INVALIDE if invalide else VOCABULAIRE_A_CONFIGURER), plaintes.CATEGORIES


def _plainte(etat: transferts.EtatTransfert, date_lecture: str) -> dict[str, Any]:
    ouverture = etat.ouverture
    categories = [c for c in plaintes.CATEGORIES if c in (ouverture.get("categories") or ())]
    source = ouverture.get("source") or ouverture.get("canal")
    declenche = ouverture.get("declenche_par")
    cloture = etat.cloture
    clos = cloture is not None and (_jour(cloture.get("horodatage")) or "9999-12-31") <= date_lecture
    return {
        "plainte_id": identifiant_plainte(str(ouverture["transfert_id"])),
        "type": ouverture["type_transfert"],
        "categories": categories,
        "gravite": None,
        "date_survenance": _jour(ouverture.get("horodatage")),
        "recue_le": ouverture["horodatage"],
        "lue_le": date_lecture,
        "source": source if source in SOURCES else SOURCE_INCONNUE,
        "declenchee_par": declenche if declenche in DECLENCHEURS else SOURCE_INCONNUE,
        "statut": STATUT_CLOS if clos else STATUT_OUVERT,
        "close_le": cloture["horodatage"] if clos and cloture is not None else None,
    }


def _cle_de_tri(plainte: Mapping[str, Any]) -> tuple[dt.datetime, str]:
    return _instant(plainte["recue_le"]) or dt.datetime.min.replace(tzinfo=dt.UTC), plainte["plainte_id"]


def _comptes(
    liste: Sequence[Mapping[str, Any]], etat: str, non_configurees: Sequence[str]
) -> dict[str, Any]:
    """Les comptes. `null` = inconnu (jamais 0) : état non branché, ou catégorie sans vocabulaire et sans plainte."""
    if etat == ETAT_NON_BRANCHEE:
        return {
            "declarees": None,
            "par_categorie": dict.fromkeys(plaintes.CATEGORIES),
            "sans_categorie": None,
            "par_type": dict.fromkeys(TYPES),
            "par_statut": {STATUT_OUVERT: None, STATUT_CLOS: None},
        }
    par_categorie: dict[str, int | None] = {}
    for categorie in plaintes.CATEGORIES:
        nombre = sum(1 for p in liste if categorie in p["categories"])
        par_categorie[categorie] = None if nombre == 0 and categorie in non_configurees else nombre
    return {
        "declarees": len(liste),
        "par_categorie": par_categorie,
        "sans_categorie": sum(1 for p in liste if not p["categories"]),
        "par_type": {t: sum(1 for p in liste if p["type"] == t) for t in TYPES},
        "par_statut": {s: sum(1 for p in liste if p["statut"] == s) for s in (STATUT_OUVERT, STATUT_CLOS)},
    }


def _empreinte(contenu: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(contenu, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _dernier_horodatage(lignes: Sequence[Mapping[str, Any]]) -> str | None:
    """L'horodatage le plus récent du registre, comparé comme INSTANT (jamais comme texte), ou `None`."""
    meilleur: tuple[dt.datetime, str] | None = None
    for ligne in lignes:
        horodatage = ligne.get("horodatage")
        instant = _instant(horodatage)
        if instant is not None and (meilleur is None or (instant, horodatage) > meilleur):
            meilleur = (instant, horodatage)
    return None if meilleur is None else meilleur[1]


def lire(
    lignes: Iterable[Mapping[str, Any]],
    *,
    date_reference: str,
    jours: int = JOURS_DEFAUT,
    signaux: Mapping[str, Sequence[str]],
    verdict_profil: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """La lecture `m1.plaintes_structurees` du registre pour les `jours` jours civils finissant à `date_reference`.

    `date_reference` : `AAAA-MM-JJ` valide (l'appelant le contrôle) ; `jours` : voir `periode_valide`. `signaux`,
    `verdict_profil` : le résultat de `taxonomie.charger_signaux_plainte()` (l'appelant lit le profil, ce module reste
    pur). Même registre, mêmes arguments : même sortie, octet pour octet.
    """
    lignes = list(lignes)
    fin = dt.date.fromisoformat(date_reference)
    debut = (fin - dt.timedelta(days=jours - 1)).isoformat()

    vocabulaire, non_configurees = _etat_vocabulaire(signaux, verdict_profil)
    liste = sorted(
        (
            _plainte(etat, date_reference)
            for etat in transferts.lire(lignes)
            if etat.ouverture.get("type_transfert") in TYPES
            and (jour := _jour(etat.ouverture.get("horodatage"))) is not None
            and debut <= jour <= date_reference
        ),
        key=_cle_de_tri,
    )
    jours_des_signaux = [_jour(ligne.get("horodatage")) for ligne in lignes if ligne.get("type_entree") == "signal"]
    signaux_jusqua = sum(1 for j in jours_des_signaux if j is not None and j <= date_reference)
    signaux_periode = sum(1 for j in jours_des_signaux if j is not None and debut <= j <= date_reference)

    if liste:
        etat, motif = ETAT_CONNUE, MOTIF_PLAINTES_AU_REGISTRE
    elif vocabulaire != VOCABULAIRE_CONFIGURE:
        etat = ETAT_NON_BRANCHEE
        motif = MOTIF_PROFIL_INVALIDE if vocabulaire == VOCABULAIRE_INVALIDE else MOTIF_VOCABULAIRE_A_CONFIGURER
    elif signaux_jusqua == 0:
        etat, motif = ETAT_NON_BRANCHEE, MOTIF_AUCUN_SIGNAL
    else:
        etat, motif = ETAT_AUCUNE_DECLAREE, MOTIF_REGISTRE_LU_SANS_PLAINTE

    contenu: dict[str, Any] = {
        "etat": etat,
        "motif": motif,
        "lecture": {"date_lecture": date_reference},
        "periode": {"debut": debut, "fin": date_reference, "jours": jours},
        "source": {
            "departement": DEPARTEMENT,
            "registre": REGISTRE,
            "vocabulaire": vocabulaire,
            "categories_sans_vocabulaire": list(non_configurees),
            "signaux_recus_jusqua_la_lecture": signaux_jusqua,
            "signaux_recus_dans_la_periode": signaux_periode,
        },
        "plaintes": liste,
        "comptes": _comptes(liste, etat, non_configurees),
    }
    revendications = {cle: contenu[cle] for cle in CLES_DE_L_EMPREINTE}
    return {
        "contrat": LECTURE,
        "schema_version": SCHEMA_VERSION,
        **contenu,
        "revision": {
            "empreinte_contenu": _empreinte(revendications),
            "registre_sequence": len(lignes),
            "registre_tete": lignes[-1].get("ligne_id") if lignes else None,
            "registre_dernier_horodatage": _dernier_horodatage(lignes),
        },
        "limites": [dict(limite) for limite in LIMITES],
    }
