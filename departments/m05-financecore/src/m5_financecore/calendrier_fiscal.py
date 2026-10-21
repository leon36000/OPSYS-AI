"""Calendrier fiscal vivant (M5.5, PLAN T4.16) : les prochaines échéances TPS/TVQ de l'entreprise.

Module pur (ADR-0009, même règle que `taxes.py` et `facturation.py`) : aucune horloge (`aujourd_hui` est fourni par
l'appelant, DA-M5-06), aucun réseau, aucun registre, aucun import d'un autre département (DA-M5-04). Il lit
`contracts/calendrier_fiscal.v1.yaml` (patron de `taux_fiscaux.v1.yaml`) et répond à une question : quelles sont les
échéances de production et de paiement de la TPS et de la TVQ ?

CE QUE CE MODULE NE FAIT JAMAIS : remettre, déclarer ou payer. Il propose des dates. Une remise à Revenu Québec est de
l'argent réel et un acte fiscal (N5, Nathan ET le CPA) : aucune écriture, aucun décaissement, aucun envoi ici, et
`conformite.verifier_aucun_decaissement` le prouve par l'AST.

FAIL-CLOSED, dans cet ordre :
1. Une ANNÉE non déclarée dans le fichier est refusée (`REJ-CALENDRIER-ANNEE-NON-DECLAREE`) : jamais une date calculée
  ou supposée à sa place. L'année d'un tableau est celle de la FIN de la période ; pour répondre à une date du jour de
  l'année Y, les années Y-1 (des échéances de début d'année viennent de périodes terminées l'an d'avant) et Y doivent
  être déclarées.
2. La FRÉQUENCE de production (mensuelle, trimestrielle ou annuelle) est une décision du propriétaire (GATE NATHAN) :
  elle figure sur la confirmation d'inscription de l'entreprise aux fichiers de la TPS et de la TVQ. Sans elle, la
  réponse est `REJ-FISCAL-FREQUENCE-A-DECLARER`, qui dit quoi fournir ; rien n'est supposé. Même règle pour le mois de
  fin d'exercice (trimestrielle et annuelle : il place les périodes) et pour le statut de particulier en affaires
  (annuelle avec exercice au 31 décembre : paiement le 30 avril et production le 15 juin, au lieu de 3 mois après).
3. La date jusqu'à laquelle les taxes sont remises (`taxes_remises_jusqu_au`) est un FAIT que seul un humain établit
  (M5 ne remet rien et ne voit pas les remises). Déclarée, elle doit être la fin d'une période du calendrier de
  l'entreprise (une remise couvre des périodes entières) ; elle permet de nommer un RETARD. Absente, aucun retard
  n'est dit : la réponse le signale au lieu de conclure que tout est à jour.

Les dates du fichier sont TRANSCRITES des calendriers de Revenu Québec publiés par l'administration fiscale (jours
fériés et période des Fêtes compris) ; ce module ne calcule aucun report. Le chargeur vérifie tout de même ce qui se
vérifie sans les inventer : dates réelles, fin de mois, durée de la période, échéance un ou trois mois après la fin (à
six jours de report près), jamais un samedi ni un dimanche.
"""

from __future__ import annotations

import calendar
import re
from collections.abc import Mapping
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

from . import analyse, validation

__all__ = [
    "charger_calendrier_fiscal",
    "lire_configuration_fiscale",
    "lire_taxes_remises",
    "periodes_applicables",
    "prochaines_echeances",
]

_FREQUENCES = ("mensuelle", "trimestrielle", "annuelle")
_MOIS_DE_LA_PERIODE = {"mensuelle": 1, "trimestrielle": 3, "annuelle": 12}
# Échéance : un mois après la fin de la période (mensuelle, trimestrielle), trois mois après (annuelle).
_MOIS_AVANT_ECHEANCE = {"mensuelle": 1, "trimestrielle": 1, "annuelle": 3}
# Report maximal toléré entre la règle (fin de mois, N mois plus tard) et la date publiée : la plus longue suite férié
# + fin de semaine + période des Fêtes des tableaux 2025 et 2026 (31 décembre -> 5 janvier).
_REPORT_MAXIMAL = timedelta(days=6)

_CHAMPS_ANNEE = frozenset(
    {"annee", "version", "validation_cpa", "sources", "periodes", "annuelle_particulier_decembre"}
)
_CHAMPS_SOURCE = frozenset({"organisme", "titre", "url", "consulte_le"})
_CHAMPS_PERIODE = frozenset({"debut", "fin", "limite_paiement"})
_CHAMPS_PERIODE_PARTICULIER = _CHAMPS_PERIODE | {"limite_production"}
_VALIDATIONS_CPA = ("A_VALIDER", "VALIDE_PAR_LE_CPA")
_DATE_ISO = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")

_LIMITE_PAR_DEFAUT = 4
_LIMITE_MAXIMALE = 12

_HORS_PERIMETRE = (
    "acomptes provisionnels de TPS/TVQ d'un inscrit à période annuelle (quatre versements) : dates et montants à "
    "confirmer par le CPA",
    "acomptes provisionnels d'impôt, DAS, T4, RL-1 et CNESST : aucune date n'est déclarée ici",
)


def _verdict(code: str, detail: str = "") -> dict[str, Any]:
    return validation.construire_verdict(code, detail=detail)


# ---------------------------------------------------------------------------------------- dates
def _date(valeur: Any) -> date | None:
    """Une date `AAAA-MM-JJ` (texte), ou `None`. Un objet `date` déjà converti par YAML est refusé : le fichier écrit
    ses dates entre guillemets, un texte n'est jamais réinterprété."""
    if not isinstance(valeur, str) or _DATE_ISO.fullmatch(valeur) is None:
        return None
    try:
        return date.fromisoformat(valeur)
    except ValueError:
        return None


def _fin_de_mois(annee: int, mois: int) -> date:
    return date(annee, mois, calendar.monthrange(annee, mois)[1])


def _fin_de_mois_apres(fin: date, mois: int) -> date:
    """Le dernier jour du mois situé `mois` mois après le mois de `fin` (avant), ou avant (négatif)."""
    total = fin.year * 12 + (fin.month - 1) + mois
    return _fin_de_mois(total // 12, total % 12 + 1)


# ----------------------------------------------------------------------------------- le chargeur
def _periode(brute: Any, frequence: str, annee: int, particulier: bool) -> tuple[dict[str, Any] | None, str | None]:
    """Une période validée (dates en `date`), ou le texte de l'erreur."""
    champs = _CHAMPS_PERIODE_PARTICULIER if particulier else _CHAMPS_PERIODE
    if not isinstance(brute, Mapping) or set(brute) != champs:
        return None, f"clés non conformes (attendu {sorted(champs)})"
    debut, fin, paiement = _date(brute["debut"]), _date(brute["fin"]), _date(brute["limite_paiement"])
    if debut is None or fin is None or paiement is None:
        return None, "dates AAAA-MM-JJ (entre guillemets) exigées"
    production = paiement
    if particulier:
        production = _date(brute["limite_production"])
        if production is None:
            return None, "limite_production : date AAAA-MM-JJ exigée"
    mois = 12 if particulier else _MOIS_DE_LA_PERIODE[frequence]
    if fin.year != annee or fin != _fin_de_mois(fin.year, fin.month):
        return None, f"fin {fin} : dernier jour d'un mois de l'année {annee} exigé"
    if debut != _fin_de_mois_apres(fin, -mois) + timedelta(days=1):
        return None, f"début {debut} : la période de {mois} mois commence le lendemain de la fin du mois précédent"
    delai = 3 if frequence == "annuelle" and not particulier else _MOIS_AVANT_ECHEANCE[frequence]
    regle_paiement = date(fin.year + 1, 4, 30) if particulier else _fin_de_mois_apres(fin, delai)
    regle_production = date(fin.year + 1, 6, 15) if particulier else _fin_de_mois_apres(fin, delai)
    for nom, jour, regle in (
        ("limite_paiement", paiement, regle_paiement),
        ("limite_production", production, regle_production),
    ):
        if not regle <= jour <= regle + _REPORT_MAXIMAL:
            return None, f"{nom} {jour} : attendu la règle du {regle}, reportée de six jours au plus"
        if jour.weekday() >= 5:
            return None, f"{nom} {jour} : un samedi ou un dimanche n'est jamais une échéance publiée"
    return {"frequence": frequence, "debut": debut, "fin": fin, "limite_paiement": paiement,
            "limite_production": production}, None


def _annee(brute: Any, chemin: Any) -> tuple[dict[str, Any] | None, list[str]]:
    erreurs: list[str] = []
    if not isinstance(brute, Mapping) or set(brute) != _CHAMPS_ANNEE:
        return None, [f"année invalide : clés non conformes ({chemin})"]
    annee = brute["annee"]
    if isinstance(annee, bool) or not isinstance(annee, int):
        return None, [f"année invalide : 'annee' doit être un entier ({chemin})"]
    etiquette = f"année {annee}"
    if not isinstance(brute["version"], str) or not brute["version"]:
        erreurs.append(f"{etiquette} : version texte non vide exigée")
    if brute["validation_cpa"] not in _VALIDATIONS_CPA:
        erreurs.append(f"{etiquette} : validation_cpa parmi {list(_VALIDATIONS_CPA)}")
    sources = brute["sources"]
    if not isinstance(sources, list) or not sources:
        erreurs.append(f"{etiquette} : au moins une source officielle citée")
    else:
        for index, source in enumerate(sources):
            if not isinstance(source, Mapping) or set(source) != _CHAMPS_SOURCE:
                erreurs.append(f"{etiquette} : source {index} : clés non conformes")
            elif (
                any(not isinstance(source[champ], str) or not source[champ] for champ in _CHAMPS_SOURCE)
                or not source["url"].startswith("https://")
                or _date(source["consulte_le"]) is None
            ):
                erreurs.append(
                    f"{etiquette} : source {index} : organisme, titre, adresse https et date de consultation exigés"
                )
    periodes = brute["periodes"]
    resultat: dict[str, list[dict[str, Any]]] = {}
    if not isinstance(periodes, Mapping) or set(periodes) != set(_FREQUENCES):
        erreurs.append(f"{etiquette} : periodes doit porter exactement {list(_FREQUENCES)}")
    else:
        for frequence in _FREQUENCES:
            lignes = periodes[frequence]
            if not isinstance(lignes, list) or len(lignes) != 12:
                erreurs.append(f"{etiquette} {frequence} : douze périodes (une par mois de fin) exigées")
                continue
            validees = []
            for index, ligne in enumerate(lignes):
                periode, erreur = _periode(ligne, frequence, annee, particulier=False)
                if erreur is not None:
                    erreurs.append(f"{etiquette} {frequence} ligne {index} : {erreur}")
                else:
                    validees.append(periode)
            if len(validees) == 12 and [p["fin"].month for p in validees] != list(range(1, 13)):
                erreurs.append(
                    f"{etiquette} {frequence} : une période par mois de fin, de janvier à décembre, dans l'ordre"
                )
            resultat[frequence] = validees
    particulier, erreur = _periode(brute["annuelle_particulier_decembre"], "annuelle", annee, particulier=True)
    if erreur is not None:
        erreurs.append(f"{etiquette} annuelle_particulier_decembre : {erreur}")
    elif particulier["fin"] != date(annee, 12, 31):
        erreurs.append(f"{etiquette} annuelle_particulier_decembre : exercice au 31 décembre exigé")
    if erreurs:
        return None, erreurs
    return {
        "annee": annee,
        "version": brute["version"],
        "validation_cpa": brute["validation_cpa"],
        "sources": [dict(source) for source in sources],
        "periodes": resultat,
        "annuelle_particulier_decembre": particulier,
    }, []


def charger_calendrier_fiscal(chemin: str | Path) -> tuple[dict[int, dict[str, Any]], list[str]]:
    """`({année: année validée}, erreurs)` : même patron que `taux_fiscaux.charger_taux_fiscaux`. Une année invalide
    est absente du dictionnaire et nommée dans les erreurs ; l'appelant refuse le fichier dès qu'il y a une erreur
    (`REJ-CALENDRIER-INVALIDE`), jamais un calendrier à moitié lu."""
    try:
        contenu = yaml.safe_load(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, yaml.YAMLError) as erreur:
        return {}, [f"calendrier illisible : {chemin} ({erreur})"]
    if not isinstance(contenu, Mapping) or contenu.get("schema_version") != 1:
        return {}, [f"schema_version invalide : {chemin}"]
    annees = contenu.get("annees")
    if not isinstance(annees, list) or not annees:
        return {}, [f"clé 'annees' absente ou invalide : {chemin}"]
    calendrier: dict[int, dict[str, Any]] = {}
    erreurs: list[str] = []
    for brute in annees:
        validee, erreurs_annee = _annee(brute, chemin)
        erreurs.extend(erreurs_annee)
        if validee is None:
            continue
        if validee["annee"] in calendrier:
            erreurs.append(f"année dupliquée {validee['annee']} : {chemin}")
            continue
        calendrier[validee["annee"]] = validee
    return calendrier, erreurs


# ------------------------------------------------------------------- ce que l'entreprise a décidé
def lire_configuration_fiscale(brut: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """`(configuration, None)` ou `(None, verdict)` : ce que le propriétaire a déclaré (`configuration.fiscal` de
    `department.yaml`), sans rien supposer. Le verdict est celui de la PREMIÈRE information qui manque, et il dit quoi
    fournir. `configuration` : `frequence`, `mois_fin_exercice` (trimestrielle et annuelle seulement, sinon `None`),
    `particulier` (annuelle avec exercice au 31 décembre seulement, sinon `None`)."""
    if not isinstance(brut, Mapping) or brut.get("frequence_tps_tvq") is None:
        return None, _verdict(
            "REJ-FISCAL-FREQUENCE-A-DECLARER",
            "la fréquence de production TPS/TVQ (mensuelle, trimestrielle ou annuelle, celle de la confirmation "
            "d'inscription) est une décision du propriétaire (GATE NATHAN) : la déclarer dans configuration.fiscal."
            "frequence_tps_tvq ; rien n'est supposé",
        )
    frequence = brut["frequence_tps_tvq"]
    if frequence not in _FREQUENCES:
        return None, _verdict(
            "REJ-FISCAL-CONFIGURATION-INVALIDE",
            f"frequence_tps_tvq : {frequence!r} inconnue (attendu {list(_FREQUENCES)})",
        )
    mois = None
    if frequence != "mensuelle":
        mois = brut.get("mois_fin_exercice")
        if mois is None:
            return None, _verdict(
                "REJ-FISCAL-FIN-EXERCICE-A-DECLARER",
                f"la fréquence {frequence} place les périodes selon le mois de fin d'exercice (1 à 12) : le "
                "déclarer dans configuration.fiscal.mois_fin_exercice ; rien n'est supposé",
            )
        if isinstance(mois, bool) or not isinstance(mois, int) or not 1 <= mois <= 12:
            return None, _verdict(
                "REJ-FISCAL-CONFIGURATION-INVALIDE", f"mois_fin_exercice : entier de 1 à 12 exigé, reçu {mois!r}"
            )
    particulier = None
    if frequence == "annuelle" and mois == 12:
        particulier = brut.get("particulier_en_affaires")
        if particulier is None:
            return None, _verdict(
                "REJ-FISCAL-STATUT-INSCRIT-A-DECLARER",
                "période annuelle et exercice au 31 décembre : un particulier en affaires paie au 30 avril et produit "
                "au 15 juin, les autres au 31 mars : déclarer configuration.fiscal.particulier_en_affaires (vrai ou "
                "faux) ; rien n'est supposé",
            )
        if not isinstance(particulier, bool):
            return None, _verdict(
                "REJ-FISCAL-CONFIGURATION-INVALIDE",
                f"particulier_en_affaires : vrai ou faux exigé, reçu {particulier!r}",
            )
    return {"frequence": frequence, "mois_fin_exercice": mois, "particulier": particulier}, None


def periodes_applicables(
    calendrier: Mapping[int, Mapping[str, Any]], configuration: Mapping[str, Any], annees: Any
) -> list[dict[str, Any]]:
    """Les périodes de déclaration de l'entreprise pour ces années (de fin de période), les plus anciennes d'abord.

    Mensuelle : les douze. Trimestrielle : celles dont le mois de fin est le mois de fin d'exercice, à trois mois
    d'intervalle. Annuelle : celle du mois de fin d'exercice ; au 31 décembre, celle du particulier en affaires si
    l'entreprise l'est. Une année absente du calendrier ne donne rien (l'appelant l'a refusée avant)."""
    frequence, mois_fin = configuration["frequence"], configuration["mois_fin_exercice"]
    trouvees: list[dict[str, Any]] = []
    for annee in sorted(annees):
        donnees = calendrier.get(annee)
        if donnees is None:
            continue
        for periode in donnees["periodes"][frequence]:
            if frequence == "trimestrielle" and (periode["fin"].month - mois_fin) % 3 != 0:
                continue
            if frequence == "annuelle" and periode["fin"].month != mois_fin:
                continue
            if frequence == "annuelle" and mois_fin == 12 and configuration["particulier"]:
                periode = donnees["annuelle_particulier_decembre"]
            trouvees.append(dict(periode))
    return trouvees


def _annees_requises(jour: date) -> tuple[int, int]:
    return jour.year - 1, jour.year


def _annees_manquantes(calendrier: Mapping[int, Any], requises: Any) -> dict[str, Any] | None:
    absentes = [annee for annee in requises if annee not in calendrier]
    if not absentes:
        return None
    return _verdict(
        "REJ-CALENDRIER-ANNEE-NON-DECLAREE",
        f"année(s) {absentes} absente(s) du calendrier fiscal (déclarées : {sorted(calendrier)}) : aucune échéance "
        "n'est calculée ni supposée ; ajouter l'année à contracts/calendrier_fiscal.v1.yaml depuis les tableaux "
        "officiels de Revenu Québec, puis la faire valider par le CPA",
    )


def lire_taxes_remises(
    fiscal: Any, calendrier: Mapping[int, Mapping[str, Any]], configuration: Mapping[str, Any]
) -> tuple[date | None, dict[str, Any] | None]:
    """`(date, None)` : la fin de la dernière période dont les taxes sont remises (`configuration.fiscal.
    taxes_remises_jusqu_au`, un fait établi par un humain, avec le CPA) ; ou `(None, verdict)` : absente, illisible,
    d'une année non déclarée, ou qui n'est pas la fin d'une période du calendrier de l'entreprise (une remise couvre
    des périodes entières : une date au milieu d'une période fausserait le calcul en silence)."""
    brut = fiscal.get("taxes_remises_jusqu_au") if isinstance(fiscal, Mapping) else None
    if brut is None:
        return None, _verdict(
            "REJ-FISCAL-REMISE-A-DECLARER",
            "aucune date de dernière remise : déclarer configuration.fiscal.taxes_remises_jusqu_au (la fin de la "
            "dernière période TPS/TVQ remise, avec le CPA) ; sans elle, on ne sait pas quelles taxes sont déjà remises",
        )
    jour = _date(brut)
    if jour is None:
        return None, _verdict(
            "REJ-FISCAL-DATE-INVALIDE",
            f"taxes_remises_jusqu_au : date AAAA-MM-JJ, entre guillemets, exigée (reçu {brut!r})",
        )
    manque = _annees_manquantes(calendrier, (jour.year,))
    if manque is not None:
        return None, manque
    if not any(periode["fin"] == jour for periode in periodes_applicables(calendrier, configuration, (jour.year,))):
        return None, _verdict(
            "REJ-FISCAL-REMISE-HORS-PERIODE",
            f"taxes_remises_jusqu_au {jour} n'est la fin d'aucune période {configuration['frequence']} de "
            "l'entreprise : une remise couvre des périodes entières",
        )
    return jour, None


# ------------------------------------------------------------------------ les prochaines échéances
def _echeance(periode: Mapping[str, Any], aujourd_hui: date, en_retard: bool) -> dict[str, Any]:
    return {
        "periode_debut": periode["debut"].isoformat(),
        "periode_fin": periode["fin"].isoformat(),
        "periode_terminee": periode["fin"] < aujourd_hui,
        "limite_paiement": periode["limite_paiement"].isoformat(),
        "limite_production": periode["limite_production"].isoformat(),
        "jours_avant_paiement": (periode["limite_paiement"] - aujourd_hui).days,
        "jours_avant_production": (periode["limite_production"] - aujourd_hui).days,
        "statut": "EN_RETARD" if en_retard else "A_VENIR",
    }


def prochaines_echeances(
    calendrier: Mapping[int, Mapping[str, Any]], aujourd_hui: Any, fiscal: Any, *, limite: Any = None
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """`(échéances, None)` ou `(None, verdict)` : les prochaines échéances TPS/TVQ de l'entreprise à partir de
    `aujourd_hui` (texte `AAAA-MM-JJ`, fourni par l'appelant : M5 n'a pas d'horloge).

    `fiscal` est `configuration.fiscal` de `department.yaml`, tel que le propriétaire l'a écrit (`None` s'il ne l'a
    pas fait). Refus nommés, sans rien rendre : date invalide, fréquence (ou fin d'exercice, ou statut) à déclarer,
    année non déclarée, `taxes_remises_jusqu_au` invalide ou dans le futur, `limite` hors de 1 à 12.

    Chaque échéance porte sa période, ses deux limites (paiement, production), les jours restants (négatifs si la
    limite est passée) et son statut : `EN_RETARD` seulement si la date de dernière remise est déclarée, que la
    période finit après elle et que sa limite de paiement est passée ; sinon `A_VENIR`. Sans date de dernière remise,
    seules les périodes dont une limite n'est pas passée sont nommées, et la réponse dit que les retards ne peuvent
    pas être détectés. La réponse cite ses sources, sa version, l'absence de validation du CPA, ce qui est hors de ce
    calendrier, et porte la mention obligatoire."""
    jour = _date(aujourd_hui)
    if jour is None:
        return None, _verdict(
            "REJ-FISCAL-DATE-INVALIDE", f"aujourd_hui : date AAAA-MM-JJ exigée (reçu {aujourd_hui!r})"
        )
    if limite is None:
        limite = _LIMITE_PAR_DEFAUT
    if isinstance(limite, bool) or not isinstance(limite, int) or not 1 <= limite <= _LIMITE_MAXIMALE:
        return None, _verdict(
            "REJ-FISCAL-LIMITE-INVALIDE", f"limite : entier de 1 à {_LIMITE_MAXIMALE} exigé (reçu {limite!r})"
        )
    configuration, verdict = lire_configuration_fiscale(fiscal)
    if verdict is not None:
        return None, verdict
    requises = _annees_requises(jour)
    manque = _annees_manquantes(calendrier, requises)
    if manque is not None:
        return None, manque
    remises = None
    manques: list[dict[str, Any]] = []
    if isinstance(fiscal, Mapping) and fiscal.get("taxes_remises_jusqu_au") is not None:
        remises, verdict = lire_taxes_remises(fiscal, calendrier, configuration)
        if verdict is not None:
            return None, verdict
        if remises >= jour:
            return None, _verdict(
                "REJ-FISCAL-CONFIGURATION-INVALIDE",
                f"taxes_remises_jusqu_au {remises} : une période remise a fini avant le {jour}",
            )
        # Une période échue depuis la dernière remise ne doit échapper à aucune année : toutes celles qui séparent la
        # remise d'aujourd'hui sont exigées, sans quoi un retard passerait inaperçu.
        requises = tuple(range(min(requises[0], remises.year), requises[1] + 1))
        manque = _annees_manquantes(calendrier, requises)
        if manque is not None:
            return None, manque
    else:
        manques.append(_verdict(
            "REJ-FISCAL-REMISE-A-DECLARER",
            "sans la date de dernière remise (configuration.fiscal.taxes_remises_jusqu_au), aucun retard n'est "
            "détectable : une période échue peut être déjà remise ou oubliée",
        ))

    candidates = []
    for periode in periodes_applicables(calendrier, configuration, requises):
        if remises is not None:
            if periode["fin"] <= remises:
                continue
            candidates.append((periode, periode["limite_paiement"] < jour))
        elif max(periode["limite_paiement"], periode["limite_production"]) >= jour:
            candidates.append((periode, False))
    candidates.sort(key=lambda couple: (couple[0]["limite_paiement"], couple[0]["fin"]))
    retenues = candidates[:limite]
    annees_declarees = sorted(calendrier)
    derniere_limite = max(
        periode["limite_production"] for periode in periodes_applicables(calendrier, configuration, annees_declarees)
    )
    return {
        "type": "ECHEANCES_FISCALES",
        "aujourd_hui": jour.isoformat(),
        "frequence": configuration["frequence"],
        "mois_fin_exercice": configuration["mois_fin_exercice"],
        "particulier_en_affaires": configuration["particulier"],
        "taxes_remises_jusqu_au": remises.isoformat() if remises is not None else None,
        "echeances": [_echeance(periode, jour, en_retard) for periode, en_retard in retenues],
        "non_affichees": len(candidates) - len(retenues),
        "manque": manques,
        "annees_declarees": annees_declarees,
        "connu_jusqu_au": derniere_limite.isoformat(),
        "avertissement_couverture": (
            f"aucune échéance n'est connue après le {derniere_limite.isoformat()} : l'année "
            f"{annees_declarees[-1] + 1} n'est pas déclarée dans le calendrier"
        ),
        "versions": {str(annee): calendrier[annee]["version"] for annee in requises},
        "validation_cpa": {str(annee): calendrier[annee]["validation_cpa"] for annee in requises},
        "sources": [dict(source) for source in calendrier[jour.year]["sources"]],
        "hors_perimetre": list(_HORS_PERIMETRE),
        "mention": analyse.MENTION_ANALYSE_PREPARATOIRE,
    }, None
