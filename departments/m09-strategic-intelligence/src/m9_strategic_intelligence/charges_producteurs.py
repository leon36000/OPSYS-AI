"""Validation stricte des charges des producteurs qui publient un CONTRAT (M4, M7, M1) : ce que M9 refuse de citer.

Module pur. Une réponse acceptée par le dispatcher n'est pas encore une charge conforme : ce module rejoue, côté
consommateur, les règles que chaque producteur publie dans son contrat. Il ne corrige JAMAIS une valeur, n'en complète
aucune et ne convertit aucune unité : une charge qui viole son contrat est refusée en bloc (la capture la conserve comme
refus, sans fait citable).

Règles communes :

* les nombres d'argent et d'heures sont des TEXTES décimaux exacts (un flottant, un entier, un signe, un séparateur de
  milliers sont refusés) ;
* une absence est ``null`` accompagné d'un manque nommé, jamais un zéro : un zéro n'est admis que s'il est porté par une
  source déclarée (M7 : un relevé), jamais par défaut ;
* chaque énuméré est fermé (statut, état, unité, devise) ; une valeur inconnue est refusée, pas ignorée ;
* la période ou la semaine rendue doit être celle qui a été demandée (une période décalée n'est pas la bonne donnée) ;
* une clé inconnue est refusée : le contrat est versionné, une extension passe par une nouvelle version.

Les messages d'erreur ne recopient JAMAIS une valeur reçue (injection) : ils nomment le champ et la règle.
"""

from __future__ import annotations

import datetime as dt
import re
from collections.abc import Callable, Mapping
from decimal import ROUND_HALF_UP, Decimal

_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
_MONTANT = re.compile(r"\d{1,12}\.\d{2}")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_MAX_CANAUX = 8
_MAX_LIGNES = 200


def _date(valeur: object) -> dt.date | None:
    if type(valeur) is not str or _DATE.fullmatch(valeur) is None:
        return None
    try:
        return dt.date.fromisoformat(valeur)
    except ValueError:
        return None


def _instant_ok(valeur: object) -> bool:
    if type(valeur) is not str or not valeur or valeur != valeur.strip() or len(valeur) > 64:
        return False
    try:
        analyse = dt.datetime.fromisoformat(valeur[:-1] + "+00:00" if valeur.endswith("Z") else valeur)
    except ValueError:
        return False
    return analyse.utcoffset() is not None


def _meme_instant(a: object, b: object) -> bool:
    if not (_instant_ok(a) and _instant_ok(b)):
        return False
    lire = lambda v: dt.datetime.fromisoformat(v[:-1] + "+00:00" if v.endswith("Z") else v)  # noqa: E731
    return lire(a) == lire(b)  # type: ignore[arg-type]


def _entier(valeur: object, minimum: int = 0, maximum: int = 10**9) -> bool:
    return type(valeur) is int and minimum <= valeur <= maximum


def _cles(objet: object, requises: set[str], permises: set[str], nom: str, erreurs: list[str]) -> bool:
    if not isinstance(objet, Mapping):
        erreurs.append(f"{nom} : objet attendu")
        return False
    manquantes = sorted(requises - set(objet))
    inconnues = sorted(set(objet) - permises)
    if manquantes:
        erreurs.append(f"{nom} : clés manquantes {manquantes}")
    if inconnues:
        erreurs.append(f"{nom} : {len(inconnues)} clé(s) inconnue(s)")
    return not manquantes and not inconnues


# ---------------------------------------------------------------------------------------------------------------------
# M7 — m7.depenses_marketing (schéma opsys.m7.depenses_marketing/v1, charge à la racine du résultat)
# ---------------------------------------------------------------------------------------------------------------------
M7_CANAUX = ("google_ads", "meta")
M7_STATUTS = frozenset({"CONNUE", "PARTIELLE", "NON_BRANCHEE"})
M7_BASES_TAXES = frozenset({"HORS_TAXES", "TAXES_INCLUSES"})
M7_CODES_MANQUE = frozenset(
    {
        "DEPENSES_NON_BRANCHEES",
        "DEPENSES_PERIODE_SANS_RELEVE",
        "RELEVE_DEBORDE_LA_PERIODE",
        "COUVERTURE_PERIODE_INCOMPLETE",
        "BASES_TAXES_DIFFERENTES",
        "DETAIL_CAMPAGNE_SUPERIEUR_AU_TOTAL",
    }
)
_M7_RACINE = {
    "type", "schema", "periode", "devise", "statut", "total_cad", "au_moins_cad", "base_taxes", "canaux_attendus",
    "canaux", "manque", "releve_le_plus_recent", "source_refs", "libelles", "lecture", "observation_source",
}  # fmt: skip
_M7_CANAL = {
    "canal", "statut", "montant_cad", "au_moins_cad", "devise", "base_taxes", "jours_periode", "jours_couverts",
    "releves", "lignes_campagne", "releves_debordants", "manque",
}  # fmt: skip


def _montant_ou_nul(valeur: object) -> bool:
    return valeur is None or (type(valeur) is str and _MONTANT.fullmatch(valeur) is not None)


def _m7_canal(canal: object, position: int, jours: int, erreurs: list[str]) -> tuple[str | None, Decimal | None]:
    nom = f"canaux[{position}]"
    if not _cles(canal, _M7_CANAL, _M7_CANAL, nom, erreurs):
        return None, None
    if canal["canal"] != M7_CANAUX[position]:
        erreurs.append(f"{nom}.canal : canal attendu à ce rang")
    statut = canal["statut"]
    if statut not in M7_STATUTS:
        erreurs.append(f"{nom}.statut : statut du contrat attendu")
        return None, None
    if canal["devise"] != "CAD":
        erreurs.append(f"{nom}.devise : CAD seulement, aucune conversion")
    if not _montant_ou_nul(canal["montant_cad"]) or not _montant_ou_nul(canal["au_moins_cad"]):
        erreurs.append(f"{nom} : montant en texte décimal à deux décimales ou null")
        return None, None
    if (statut == "CONNUE") != (canal["montant_cad"] is not None):
        erreurs.append(f"{nom}.montant_cad : présent si et seulement si le canal est CONNUE")
    if canal["au_moins_cad"] is not None and statut != "PARTIELLE":
        erreurs.append(f"{nom}.au_moins_cad : borne basse réservée au canal PARTIELLE")
    if statut == "PARTIELLE" and canal["montant_cad"] is not None:
        erreurs.append(f"{nom}.montant_cad : un canal PARTIELLE n'a pas de total")
    if canal["base_taxes"] is not None and canal["base_taxes"] not in M7_BASES_TAXES:
        erreurs.append(f"{nom}.base_taxes : base du contrat attendue")
    if canal["jours_periode"] != jours or not _entier(canal["jours_couverts"], 0, jours):
        erreurs.append(f"{nom} : jours de période ou de couverture incohérents")
    for liste in ("releves", "lignes_campagne", "releves_debordants", "manque"):
        if not isinstance(canal[liste], list) or len(canal[liste]) > _MAX_LIGNES:
            erreurs.append(f"{nom}.{liste} : liste bornée attendue")
            return statut, None
    if any(code not in M7_CODES_MANQUE for code in canal["manque"]):
        erreurs.append(f"{nom}.manque : code du contrat attendu")
    somme = Decimal("0.00")
    for releve in canal["releves"]:
        if (
            not isinstance(releve, Mapping)
            or not _montant_ou_nul(releve.get("montant_cad"))
            or releve.get("montant_cad") is None
        ):
            erreurs.append(f"{nom}.releves : montant de relevé en texte décimal requis")
            return statut, None
        if releve.get("devise") != "CAD":
            erreurs.append(f"{nom}.releves : CAD seulement")
        somme += Decimal(releve["montant_cad"])
    if statut == "CONNUE":
        if not canal["releves"]:
            erreurs.append(f"{nom} : un montant connu exige au moins un relevé qui le porte (jamais un zéro implicite)")
        elif Decimal(canal["montant_cad"]) != somme:
            erreurs.append(f"{nom}.montant_cad : différent de la somme des relevés")
        if canal["jours_couverts"] != jours:
            erreurs.append(f"{nom} : un canal CONNUE couvre toute la période")
        if canal["base_taxes"] is None:
            erreurs.append(f"{nom}.base_taxes : requise pour un canal CONNUE")
    if statut == "NON_BRANCHEE" and (canal["montant_cad"] is not None or canal["au_moins_cad"] is not None):
        erreurs.append(f"{nom} : NON_BRANCHEE n'a aucun montant")
    if statut != "CONNUE" and not canal["manque"]:
        erreurs.append(f"{nom}.manque : un canal non connu nomme son manque")
    return statut, Decimal(canal["montant_cad"]) if statut == "CONNUE" and not erreurs else None


def valider_m7_depenses(page: object, arguments: Mapping | None) -> list[str]:
    """Erreurs (sans valeur reçue) de la réponse du dispatcher pour ``m7_lire_depenses_marketing``."""
    erreurs: list[str] = []
    charge = page.get("resultat") if isinstance(page, Mapping) else None
    if not _cles(charge, _M7_RACINE, _M7_RACINE, "charge", erreurs):
        return erreurs
    if charge["type"] != "DEPENSES_MARKETING" or charge["schema"] != "opsys.m7.depenses_marketing/v1":
        erreurs.append("charge : contrat m7.depenses_marketing v1 attendu")
    if charge["devise"] != "CAD":
        erreurs.append("devise : CAD seulement, aucune conversion")
    periode = charge["periode"]
    if not isinstance(periode, Mapping) or (
        arguments is not None
        and (periode.get("debut"), periode.get("fin")) != (arguments.get("debut"), arguments.get("fin"))
    ):
        erreurs.append("periode : différente de la période demandée")
        return erreurs
    debut, fin = _date(periode["debut"]), _date(periode["fin"])
    if debut is None or fin is None or fin < debut:
        erreurs.append("periode : dates civiles réelles, fin non antérieure au début")
        return erreurs
    jours = (fin - debut).days + 1
    statut = charge["statut"]
    if statut not in M7_STATUTS:
        erreurs.append("statut : statut du contrat attendu")
        return erreurs
    if not _montant_ou_nul(charge["total_cad"]) or not _montant_ou_nul(charge["au_moins_cad"]):
        erreurs.append("montant : texte décimal à deux décimales ou null")
        return erreurs
    if (statut == "CONNUE") != (charge["total_cad"] is not None):
        erreurs.append("total_cad : présent si et seulement si le statut est CONNUE")
    if charge["au_moins_cad"] is not None and statut != "PARTIELLE":
        erreurs.append("au_moins_cad : borne basse réservée au statut PARTIELLE")
    if charge["canaux_attendus"] != list(M7_CANAUX):
        erreurs.append("canaux_attendus : canaux du contrat attendus")
    if charge["libelles"] != "DONNEES_SAISIES_NON_INTERPRETEES":
        erreurs.append("libelles : déclaration de données non interprétées attendue")
    if charge["releve_le_plus_recent"] is not None and not _instant_ok(charge["releve_le_plus_recent"]):
        erreurs.append("releve_le_plus_recent : instant avec fuseau ou null")
    if statut == "CONNUE" and charge["releve_le_plus_recent"] is None:
        erreurs.append("releve_le_plus_recent : requis pour des dépenses connues")
    canaux = charge["canaux"]
    if not isinstance(canaux, list) or len(canaux) != len(M7_CANAUX) or len(canaux) > _MAX_CANAUX:
        erreurs.append("canaux : un élément par canal attendu")
        return erreurs
    resultats = [_m7_canal(canal, position, jours, erreurs) for position, canal in enumerate(canaux)]
    statuts = {r[0] for r in resultats}
    if statut == "CONNUE":
        if statuts != {"CONNUE"}:
            erreurs.append("statut : CONNUE exige que chaque canal soit CONNUE")
        elif (
            not erreurs
            and charge["total_cad"] is not None
            and Decimal(charge["total_cad"]) != sum((r[1] for r in resultats), Decimal("0.00"))
        ):
            erreurs.append("total_cad : différent de la somme des canaux")
    elif statut == "NON_BRANCHEE" and statuts != {"NON_BRANCHEE"}:
        erreurs.append("statut : NON_BRANCHEE exige que chaque canal soit NON_BRANCHEE")
    elif statut == "PARTIELLE" and statuts == {"NON_BRANCHEE"}:
        erreurs.append("statut : PARTIELLE exige au moins un montant établi")
    manque = charge["manque"]
    if not isinstance(manque, list) or len(manque) > _MAX_LIGNES:
        erreurs.append("manque : liste bornée attendue")
    else:
        portees = {*M7_CANAUX, "total"}
        for element in manque:
            if (
                not isinstance(element, Mapping)
                or element.get("code") not in M7_CODES_MANQUE
                or element.get("portee") not in portees
            ):
                erreurs.append("manque : {portee, code} du contrat attendu")
                break
        if statut != "CONNUE" and not manque:
            erreurs.append("manque : des dépenses non connues nomment leur manque")
    return erreurs


# ---------------------------------------------------------------------------------------------------------------------
# M4 — m4.capacite_equipe (contrat v1, charge dans ``resultat.resultat`` du dispatcher)
# ---------------------------------------------------------------------------------------------------------------------
M4_UNITE = "heures_declarees"
M4_PORTEE = "journees_datees_seulement"
M4_MINUTES_MAX = 7 * 24 * 60  # une semaine de 24 h : borne dure d'une équipe sur des journées datées
_M4_IDENTIFIANT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}")
_M4_MANQUE = re.compile(r"[a-z_]{1,64}(?::[A-Za-z0-9][A-Za-z0-9._:-]{0,63}){0,2}")
_M4_HEURES = re.compile(r"\d{1,9}\.\d{2,4}")
_M4_RACINE = {
    "contrat", "version", "semaine_debut", "fuseau", "unite", "portee", "lu_a", "calculable", "manque", "equipes",
    "jours_dates", "sources", "avertissements", "heures_disponibles", "heures_planifiees", "minutes_disponibles",
    "minutes_planifiees",
}  # fmt: skip
_M4_REQUISES = _M4_RACINE - {"heures_disponibles", "heures_planifiees", "minutes_disponibles", "minutes_planifiees"}
_M4_TOTAUX = {"heures_disponibles", "heures_planifiees", "minutes_disponibles", "minutes_planifiees"}
_M4_EQUIPE = {"equipe_id", "heures_disponibles", "heures_planifiees", "minutes_disponibles", "minutes_planifiees"}
_M4_SOURCES = {
    "profil_empreinte", "registre_tete", "plans_appliques", "plans_proposes_non_appliques", "cedule_revision_max",
    "cedule_confirmee_le",
}  # fmt: skip


def heures_texte(minutes: int) -> str:
    """Texte des heures d'une durée en minutes, comme M4 l'écrit : minutes/60 au dix-millième, au moins deux
    décimales."""
    valeur = (Decimal(minutes) / Decimal(60)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    entier, decimales = format(valeur, "f").split(".")
    return f"{entier}.{decimales.rstrip('0').ljust(2, '0')}"


def _m4_valeur(porteur: Mapping, cle: str, nom: str, erreurs: list[str]) -> int | None:
    """Minutes entières bornées et heures en texte qui en sont exactement la conversion annoncée."""
    minutes, heures = porteur[cle], porteur[cle.replace("minutes", "heures")]
    if not _entier(minutes, 0, M4_MINUTES_MAX):
        erreurs.append(f"{nom}.{cle} : entier de minutes borné attendu")
        return None
    if type(heures) is not str or _M4_HEURES.fullmatch(heures) is None or heures != heures_texte(minutes):
        erreurs.append(f"{nom}.{cle.replace('minutes', 'heures')} : texte décimal exact des minutes attendu")
        return None
    return minutes


def valider_m4_capacite(page: object, arguments: Mapping | None) -> list[str]:
    """Erreurs (sans valeur reçue) de la réponse du dispatcher pour ``m4_lire_capacite_equipe``."""
    erreurs: list[str] = []
    interne = page.get("resultat") if isinstance(page, Mapping) else None
    charge = interne.get("resultat") if isinstance(interne, Mapping) else None
    if not _cles(charge, _M4_REQUISES, _M4_RACINE, "charge", erreurs):
        return erreurs
    if charge["contrat"] != "m4.capacite_equipe" or charge["version"] != 1:
        erreurs.append("charge : contrat m4.capacite_equipe v1 attendu")
    if charge["unite"] != M4_UNITE:
        erreurs.append("unite : heures_declarees seulement, aucune conversion")
    if charge["portee"] != M4_PORTEE:
        erreurs.append("portee : journees_datees_seulement seulement")
    if charge["fuseau"] != "America/Montreal":
        erreurs.append("fuseau : America/Montreal seulement")
    lundi = _date(charge["semaine_debut"])
    if lundi is None or lundi.weekday() != 0:
        erreurs.append("semaine_debut : lundi réel attendu")
        return erreurs
    if arguments is not None:
        if charge["semaine_debut"] != arguments.get("debut_semaine"):
            erreurs.append("semaine_debut : différente de la semaine demandée")
        demande = arguments.get("horodatage_reference")
        if (charge["lu_a"] is None) != (demande is None) or (
            demande is not None and not _meme_instant(charge["lu_a"], demande)
        ):
            erreurs.append("lu_a : doit être l'instant de lecture demandé, ou null s'il n'a pas été demandé")
    elif charge["lu_a"] is not None and not _instant_ok(charge["lu_a"]):
        erreurs.append("lu_a : instant avec fuseau ou null")
    calculable, manque, equipes = charge["calculable"], charge["manque"], charge["equipes"]
    if type(calculable) is not bool:
        erreurs.append("calculable : booléen attendu")
        return erreurs
    if (
        not isinstance(manque, list)
        or len(manque) > 50
        or not all(type(m) is str and _M4_MANQUE.fullmatch(m) is not None for m in manque)
    ):
        erreurs.append("manque : liste bornée de codes du contrat attendue")
        return erreurs
    jours = charge["jours_dates"]
    if not isinstance(jours, list) or len(jours) > 7:
        erreurs.append("jours_dates : liste de 7 dates au plus attendue")
    else:
        dates = [_date(j) for j in jours]
        if any(d is None or not 0 <= (d - lundi).days <= 6 for d in dates) or dates != sorted(set(dates)):  # type: ignore[type-var]
            erreurs.append("jours_dates : dates distinctes, triées, dans la semaine")
    sources = charge["sources"]
    if _cles(sources, _M4_SOURCES, _M4_SOURCES, "sources", erreurs):
        if sources["profil_empreinte"] is not None and (
            type(sources["profil_empreinte"]) is not str or _HEX64.fullmatch(sources["profil_empreinte"]) is None
        ):
            erreurs.append("sources.profil_empreinte : condensat ou null")
        if sources["registre_tete"] is not None and (
            type(sources["registre_tete"]) is not str
            or not sources["registre_tete"]
            or len(sources["registre_tete"]) > 128
        ):
            erreurs.append("sources.registre_tete : identifiant texte ou null")
        if not _entier(sources["plans_appliques"]) or not _entier(sources["plans_proposes_non_appliques"]):
            erreurs.append("sources : comptes de plans entiers positifs ou nuls")
        if sources["cedule_revision_max"] is not None and not _entier(sources["cedule_revision_max"]):
            erreurs.append("sources.cedule_revision_max : entier positif ou null")
        if sources["cedule_confirmee_le"] is not None and not _instant_ok(sources["cedule_confirmee_le"]):
            erreurs.append("sources.cedule_confirmee_le : instant avec fuseau ou null")
    avertissements = charge["avertissements"]
    if (
        not isinstance(avertissements, list)
        or len(avertissements) > 20
        or not all(type(a) is str and len(a) <= 600 for a in avertissements)
    ):
        erreurs.append("avertissements : liste bornée de textes attendue")
    if not isinstance(equipes, list) or len(equipes) > 100:
        erreurs.append("equipes : liste bornée attendue")
        return erreurs
    presents = _M4_TOTAUX & set(charge)
    if not calculable:
        if not manque:
            erreurs.append("calculable faux : une cause nommée est requise")
        if equipes or presents:
            erreurs.append("calculable faux : aucune valeur n'est admise (absence n'est pas zéro)")
        return erreurs
    if manque:
        erreurs.append("calculable vrai : aucun manque n'est admis")
    if not equipes or presents != _M4_TOTAUX or not jours:
        erreurs.append("calculable vrai : équipes, totaux et journées datées requis")
        return erreurs
    if isinstance(sources, Mapping) and (
        sources.get("profil_empreinte") is None or sources.get("plans_appliques") == 0
    ):
        erreurs.append("sources : un profil et une cédule appliquée sont requis pour un calcul")
    identifiants, somme = [], {"minutes_disponibles": 0, "minutes_planifiees": 0}
    for position, ligne in enumerate(equipes):
        nom = f"equipes[{position}]"
        if not _cles(ligne, _M4_EQUIPE, _M4_EQUIPE, nom, erreurs):
            return erreurs
        if type(ligne["equipe_id"]) is not str or _M4_IDENTIFIANT.fullmatch(ligne["equipe_id"]) is None:
            erreurs.append(f"{nom}.equipe_id : identifiant sobre attendu")
        else:
            identifiants.append(ligne["equipe_id"])
        for cle in somme:
            minutes = _m4_valeur(ligne, cle, nom, erreurs)
            somme[cle] += minutes or 0
    if len(set(identifiants)) != len(identifiants):
        erreurs.append("equipes : equipe_id en double")
    for cle, total in somme.items():
        if charge[cle] != total or charge[cle.replace("minutes", "heures")] != heures_texte(total):
            erreurs.append(f"{cle} : le total n'est pas la somme des équipes")
    return erreurs


# ---------------------------------------------------------------------------------------------------------------------
# M1 — m1.plaintes_structurees (contrat v1, charge dans ``resultat.resultat``)
# ---------------------------------------------------------------------------------------------------------------------
M1_CATEGORIES = ("insatisfaction", "degat", "garantie", "avocat", "securite")
M1_ETATS = frozenset({"CONNUE", "AUCUNE_DECLAREE_PAR_SOURCE", "NON_BRANCHEE"})
_M1_MOTIFS = {
    "CONNUE": {"TRANSFERTS_DE_PLAINTE_AU_REGISTRE"},
    "AUCUNE_DECLAREE_PAR_SOURCE": {"REGISTRE_LU_SANS_TRANSFERT_DE_PLAINTE"},
    "NON_BRANCHEE": {"VOCABULAIRE_A_CONFIGURER", "PROFIL_INVALIDE", "AUCUN_SIGNAL_AU_REGISTRE"},
}
_M1_RACINE = {
    "contrat", "schema_version", "etat", "motif", "lecture", "periode", "source", "plaintes", "comptes", "revision",
    "limites",
}  # fmt: skip
_M1_PLAINTE = {
    "plainte_id", "type", "categories", "gravite", "date_survenance", "recue_le", "lue_le", "source", "declenchee_par",
    "statut", "close_le",
}  # fmt: skip
_M1_COMPTES = {"declarees", "par_categorie", "sans_categorie", "par_type", "par_statut"}
_M1_SOURCE = {
    "departement", "registre", "vocabulaire", "categories_sans_vocabulaire", "signaux_recus_jusqua_la_lecture",
    "signaux_recus_dans_la_periode",
}  # fmt: skip
_M1_REVISION = {"empreinte_contenu", "registre_sequence", "registre_tete", "registre_dernier_horodatage"}
_M1_PSEUDONYME = re.compile(r"pl-[0-9a-f]{20}")
_M1_MAX_PLAINTES = 5000
M1_JOURS_PAR_DEFAUT = 7


def _m1_comptes(charge: Mapping, etat: str, erreurs: list[str]) -> None:
    comptes = charge["comptes"]
    if not _cles(comptes, _M1_COMPTES, _M1_COMPTES, "comptes", erreurs):
        return
    par_categorie, par_type, par_statut = comptes["par_categorie"], comptes["par_type"], comptes["par_statut"]
    if not _cles(par_categorie, set(M1_CATEGORIES), set(M1_CATEGORIES), "comptes.par_categorie", erreurs) or not _cles(
        par_type, {"plainte", "urgence"}, {"plainte", "urgence"}, "comptes.par_type", erreurs
    ) or not _cles(par_statut, {"ouvert", "clos"}, {"ouvert", "clos"}, "comptes.par_statut", erreurs):
        return
    tous = [comptes["declarees"], comptes["sans_categorie"], *par_categorie.values(), *par_type.values(),
            *par_statut.values()]  # fmt: skip
    plaintes = charge["plaintes"]
    sans_vocabulaire = charge["source"]["categories_sans_vocabulaire"]
    if etat == "NON_BRANCHEE":
        if any(valeur is not None for valeur in tous):
            erreurs.append("comptes : NON_BRANCHEE n'a aucun compte (null, jamais zéro)")
        return
    if not all(_entier(valeur, 0, _M1_MAX_PLAINTES) for valeur in tous if valeur is not None):
        erreurs.append("comptes : entiers positifs ou nuls bornés (ou null)")
        return
    if any(comptes[c] is None for c in ("declarees", "sans_categorie")) or any(
        v is None for v in (*par_type.values(), *par_statut.values())
    ):
        erreurs.append("comptes : les totaux d'une source branchée sont des entiers")
        return
    declarees = comptes["declarees"]
    if sum(par_type.values()) != declarees or sum(par_statut.values()) != declarees:
        erreurs.append("comptes : types et statuts doivent totaliser les plaintes déclarées")
    for categorie, valeur in par_categorie.items():
        if valeur is None and categorie not in sans_vocabulaire:
            erreurs.append("comptes.par_categorie : inconnu (null) seulement pour une catégorie sans vocabulaire")
        elif valeur is not None and valeur > declarees:
            erreurs.append("comptes.par_categorie : une catégorie ne dépasse pas le total déclaré")
    if etat == "AUCUNE_DECLAREE_PAR_SOURCE":
        if declarees != 0 or plaintes:
            erreurs.append("comptes : AUCUNE_DECLAREE_PAR_SOURCE n'a ni plainte ni compte non nul")
        return
    if declarees != len(plaintes):
        erreurs.append("comptes.declarees : différent du nombre de plaintes listées")
        return
    for type_ in ("plainte", "urgence"):
        if par_type[type_] != sum(1 for p in plaintes if p["type"] == type_):
            erreurs.append("comptes.par_type : différent des plaintes listées")
    for statut in ("ouvert", "clos"):
        if par_statut[statut] != sum(1 for p in plaintes if p["statut"] == statut):
            erreurs.append("comptes.par_statut : différent des plaintes listées")
    if comptes["sans_categorie"] != sum(1 for p in plaintes if not p["categories"]):
        erreurs.append("comptes.sans_categorie : différent des plaintes listées")
    for categorie, valeur in par_categorie.items():
        if valeur is not None and valeur != sum(1 for p in plaintes if categorie in p["categories"]):
            erreurs.append("comptes.par_categorie : différent des plaintes listées")


def _m1_plaintes(charge: Mapping, fin: dt.date, debut: dt.date, erreurs: list[str]) -> None:
    plaintes = charge["plaintes"]
    identifiants = []
    for position, plainte in enumerate(plaintes):
        nom = f"plaintes[{position}]"
        if not _cles(plainte, _M1_PLAINTE, _M1_PLAINTE, nom, erreurs):
            return
        if type(plainte["plainte_id"]) is not str or _M1_PSEUDONYME.fullmatch(plainte["plainte_id"]) is None:
            erreurs.append(f"{nom}.plainte_id : pseudonyme du contrat attendu")
        else:
            identifiants.append(plainte["plainte_id"])
        if plainte["type"] not in ("plainte", "urgence"):
            erreurs.append(f"{nom}.type : plainte ou urgence")
        categories = plainte["categories"]
        if not isinstance(categories, list) or len(set(map(str, categories))) != len(categories) or not all(
            c in M1_CATEGORIES for c in categories
        ):
            erreurs.append(f"{nom}.categories : catégories fermées du contrat")
        if plainte["gravite"] is not None:
            erreurs.append(f"{nom}.gravite : toujours null en v1 (aucune source ne la déclare)")
        survenance = _date(plainte["date_survenance"])
        if survenance is None or not debut <= survenance <= fin:
            erreurs.append(f"{nom}.date_survenance : jour réel de la période")
        if not _instant_ok(plainte["recue_le"]):
            erreurs.append(f"{nom}.recue_le : instant avec fuseau")
        if plainte["lue_le"] != charge["periode"]["fin"]:
            erreurs.append(f"{nom}.lue_le : jour de lecture")
        if plainte["source"] not in ("sms", "courriel", "formulaire", "texte", "telephone", "inconnue"):
            erreurs.append(f"{nom}.source : canal fermé du contrat")
        if plainte["declenchee_par"] not in ("regles", "agent", "inconnue"):
            erreurs.append(f"{nom}.declenchee_par : valeur fermée du contrat")
        if plainte["statut"] not in ("ouvert", "clos"):
            erreurs.append(f"{nom}.statut : ouvert ou clos")
        elif plainte["statut"] == "ouvert" and plainte["close_le"] is not None:
            erreurs.append(f"{nom}.close_le : null pour une plainte ouverte")
        if plainte["close_le"] is not None and not _instant_ok(plainte["close_le"]):
            erreurs.append(f"{nom}.close_le : instant avec fuseau ou null")
    if len(set(identifiants)) != len(identifiants):
        erreurs.append("plaintes : pseudonyme en double")


def valider_m1_plaintes(page: object, arguments: Mapping | None) -> list[str]:
    """Erreurs (sans valeur reçue) de la réponse du dispatcher pour ``m1_lire_plaintes_structurees``."""
    erreurs: list[str] = []
    interne = page.get("resultat") if isinstance(page, Mapping) else None
    charge = interne.get("resultat") if isinstance(interne, Mapping) else None
    if not _cles(charge, _M1_RACINE, _M1_RACINE, "charge", erreurs):
        return erreurs
    if charge["contrat"] != "m1.plaintes_structurees" or charge["schema_version"] != 1:
        erreurs.append("charge : contrat m1.plaintes_structurees v1 attendu")
    etat = charge["etat"]
    if etat not in M1_ETATS:
        erreurs.append("etat : état du contrat attendu")
        return erreurs
    if charge["motif"] not in _M1_MOTIFS[etat]:
        erreurs.append("motif : motif cohérent avec l'état attendu")
    lecture, periode, source = charge["lecture"], charge["periode"], charge["source"]
    if not (_cles(lecture, {"date_lecture"}, {"date_lecture"}, "lecture", erreurs)
            and _cles(periode, {"debut", "fin", "jours"}, {"debut", "fin", "jours"}, "periode", erreurs)
            and _cles(source, _M1_SOURCE, _M1_SOURCE, "source", erreurs)):  # fmt: skip
        return erreurs
    fin, debut = _date(periode["fin"]), _date(periode["debut"])
    jours = periode["jours"]
    if fin is None or debut is None or not _entier(jours, 1, 92) or (fin - debut).days + 1 != jours:
        erreurs.append("periode : jours de 1 à 92, début et fin inclus cohérents")
        return erreurs
    if lecture["date_lecture"] != periode["fin"]:
        erreurs.append("lecture.date_lecture : égale à la fin de période")
    if arguments is not None and (
        periode["fin"] != arguments.get("date_reference") or jours != arguments.get("jours", M1_JOURS_PAR_DEFAUT)
    ):
        erreurs.append("periode : différente de la période demandée")
    if source["departement"] != "m01-front-office" or source["registre"] != "principal":
        erreurs.append("source : département et registre du contrat")
    if source["vocabulaire"] not in ("CONFIGURE", "A_CONFIGURER", "INVALIDE"):
        erreurs.append("source.vocabulaire : valeur fermée du contrat")
    sans = source["categories_sans_vocabulaire"]
    if not isinstance(sans, list) or not all(c in M1_CATEGORIES for c in sans) or len(set(map(str, sans))) != len(sans):
        erreurs.append("source.categories_sans_vocabulaire : catégories fermées distinctes")
        return erreurs
    if not _entier(source["signaux_recus_jusqua_la_lecture"]) or not _entier(source["signaux_recus_dans_la_periode"]):
        erreurs.append("source : comptes de signaux entiers positifs ou nuls")
    plaintes = charge["plaintes"]
    if not isinstance(plaintes, list) or len(plaintes) > _M1_MAX_PLAINTES:
        erreurs.append("plaintes : liste bornée attendue")
        return erreurs
    if etat == "CONNUE" and not plaintes:
        erreurs.append("plaintes : CONNUE exige au moins une plainte")
    if etat != "CONNUE" and plaintes:
        erreurs.append("plaintes : vide hors de l'état CONNUE")
    _m1_plaintes(charge, fin, debut, erreurs)
    _m1_comptes(charge, etat, erreurs)
    revision = charge["revision"]
    if _cles(revision, _M1_REVISION, _M1_REVISION, "revision", erreurs):
        if type(revision["empreinte_contenu"]) is not str or _HEX64.fullmatch(revision["empreinte_contenu"]) is None:
            erreurs.append("revision.empreinte_contenu : condensat attendu")
        if not _entier(revision["registre_sequence"]):
            erreurs.append("revision.registre_sequence : entier positif ou nul")
        if revision["registre_tete"] is not None and (
            type(revision["registre_tete"]) is not str or not 0 < len(revision["registre_tete"]) <= 128
        ):
            erreurs.append("revision.registre_tete : identifiant texte ou null")
        if revision["registre_dernier_horodatage"] is not None and not _instant_ok(
            revision["registre_dernier_horodatage"]
        ):
            erreurs.append("revision.registre_dernier_horodatage : instant avec fuseau ou null")
    limites = charge["limites"]
    if not isinstance(limites, list) or len(limites) > 50 or not all(
        isinstance(x, Mapping) and set(x) == {"code", "detail"} for x in limites
    ):
        erreurs.append("limites : liste de {code, detail}")
    return erreurs


VALIDATEURS: dict[str, Callable[[object, Mapping | None], list[str]]] = {
    "m1.plaintes_structurees": valider_m1_plaintes,
    "m4.capacite_equipe": valider_m4_capacite,
    "m7.depenses_marketing": valider_m7_depenses,
}


def valider(lecture_id: str, page: object, arguments: Mapping | None) -> list[str]:
    """Erreurs de conformité de la réponse d'une lecture à contrat ; liste vide si conforme (ou sans contrat à rejouer).
    ``arguments`` ``None`` : la période ou la semaine rendue n'est pas comparée à une demande (validation hors
    capture)."""
    validateur = VALIDATEURS.get(lecture_id)
    if validateur is None:
        return []
    try:
        return validateur(page, arguments)
    except (KeyError, TypeError, ValueError, ArithmeticError, AttributeError):  # défense : jamais une exception
        return ["charge : forme illisible"]
