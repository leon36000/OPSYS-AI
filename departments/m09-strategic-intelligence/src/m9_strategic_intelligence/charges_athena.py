"""Validation stricte des charges des producteurs raccordés pour Athéna (M8 synthèse de direction, M2 pipeline et
prévision, M5 calendrier et statut de revue fiscale, M10 faits analytiques).

Module pur, même doctrine que ``charges_producteurs`` : ce que M9 refuse de citer. Une réponse acceptée par le
dispatcher n'est pas encore une charge conforme ; ce module rejoue, côté consommateur, les règles de forme et de
cohérence que chaque producteur annonce. Il ne corrige JAMAIS une valeur, n'en complète aucune et n'estime rien :

* une valeur d'argent, de taux ou de score est un TEXTE décimal exact (jamais un flottant) ;
* « indéterminé », « non calculable », « manquant » et « échantillon insuffisant » sont des états FERMÉS : ils vont avec
  une valeur nulle et jamais avec un chiffre ; l'inverse (un chiffre avec un état d'absence) est refusé ;
* une prévision porte TOUJOURS son intervalle (un point seul est refusé) ;
* un énuméré inconnu est refusé, pas ignoré ; une clé inconnue aussi (contrat versionné) ;
* les messages d'erreur nomment le champ et la règle, jamais la valeur reçue (injection).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation

from .charges_producteurs import _cles, _date, _entier, _instant_ok, _meme_instant

_HEX64 = re.compile(r"[0-9a-f]{64}")
_DECIMAL = re.compile(r"-?\d{1,15}(\.\d{1,6})?")
_METRIQUE = re.compile(r"m8_[a-z0-9_]{1,76}")
_EVENEMENT_M8 = re.compile(r"m8-faits-[0-9a-f]{64}")
_MAX_LIGNES = 200

# --------------------------------------------------------------------------------------------------------- M8
M8_STATUTS_SANTE = ("determine", "indetermine")
M8_RAISONS_MANQUE = frozenset(
    {"mesure_manquante", "mesure_perimee", "fraicheur_inconnue", "bornes_a_configurer", "bornes_invalides"}
)
M8_FRAICHEURS = frozenset({"a_jour", "perime", "inconnu", "manquant", "non_applicable"})
M8_STATUTS_MESURE = ("calculee", "non_calculable")
_M8_RACINE = {
    "type", "schema", "maintenant", "version_catalogue", "empreinte_registres", "sante", "mesures", "avertissements",
    "mention",
}  # fmt: skip
_M8_SANTE = {"statut", "score", "ponderations", "version_definition", "composantes", "manques", "bornes_invalides"}
_M8_COMPOSANTE = {"id", "libelle", "poids", "statut", "score"}
_M8_MESURE = {
    "metric_id", "domaine", "unite", "statut", "valeur", "fraicheur", "age_s", "fenetre_s", "dernier_fait_le",
    "version_definition", "manque",
}  # fmt: skip


def _decimal_ok(valeur: object) -> bool:
    return type(valeur) is str and _DECIMAL.fullmatch(valeur) is not None


def _decimal(valeur: object) -> Decimal | None:
    if not _decimal_ok(valeur):
        return None
    try:
        return Decimal(valeur)  # type: ignore[arg-type]
    except InvalidOperation:
        return None


def _m8_sante(sante: object, erreurs: list[str]) -> None:
    if not _cles(sante, _M8_SANTE, _M8_SANTE, "sante", erreurs):
        return
    statut = sante["statut"]  # type: ignore[index]
    if statut not in M8_STATUTS_SANTE:
        erreurs.append("sante.statut : déterminé ou indéterminé seulement")
        return
    score = sante["score"]  # type: ignore[index]
    if (statut == "determine") != (score is not None):
        erreurs.append("sante.score : présent si et seulement si le statut est déterminé (jamais un faux score)")
    if score is not None:
        valeur = _decimal(score)
        if valeur is None or not Decimal(0) <= valeur <= Decimal(100):
            erreurs.append("sante.score : texte décimal de 0 à 100")
    ponderations = sante["ponderations"]  # type: ignore[index]
    cles_ponderations = {"validee", "declaree_par", "validee_par"}
    if _cles(ponderations, cles_ponderations, cles_ponderations, "sante.ponderations", erreurs) and (
        type(ponderations["validee"]) is not bool
        or ponderations["validee"] != (ponderations["validee_par"] is not None)
    ):
        erreurs.append("sante.ponderations : validée si et seulement si une personne les a validées")
    # type: ignore[index]
    if type(sante["version_definition"]) is not str or _HEX64.fullmatch(sante["version_definition"]) is None:
        erreurs.append("sante.version_definition : condensat attendu")
    composantes = sante["composantes"]  # type: ignore[index]
    if not isinstance(composantes, list) or not 1 <= len(composantes) <= 12:
        erreurs.append("sante.composantes : liste de 1 à 12 composantes")
        return
    ids: set[str] = set()
    somme_poids, toutes_determinees = 0, True
    for rang, composante in enumerate(composantes):
        nom = f"sante.composantes[{rang}]"
        if not _cles(composante, _M8_COMPOSANTE, _M8_COMPOSANTE, nom, erreurs):
            return
        if type(composante["id"]) is not str or not composante["id"] or composante["id"] in ids:
            erreurs.append(f"{nom}.id : identifiant distinct")
        ids.add(str(composante["id"]))
        if not _entier(composante["poids"], 1, 100):
            erreurs.append(f"{nom}.poids : entier de 1 à 100")
        else:
            somme_poids += composante["poids"]
        if composante["statut"] not in M8_STATUTS_SANTE:
            erreurs.append(f"{nom}.statut : déterminé ou indéterminé seulement")
            continue
        if (composante["statut"] == "determine") != (composante["score"] is not None):
            erreurs.append(f"{nom}.score : présent si et seulement si la composante est déterminée")
        elif composante["score"] is not None and _decimal(composante["score"]) is None:
            erreurs.append(f"{nom}.score : texte décimal")
        toutes_determinees &= composante["statut"] == "determine"
    if somme_poids != 100:
        erreurs.append("sante.composantes : les pondérations totalisent 100")
    manques = sante["manques"]  # type: ignore[index]
    if not isinstance(manques, list) or len(manques) > _MAX_LIGNES:
        erreurs.append("sante.manques : liste bornée")
        return
    for rang, manque in enumerate(manques):
        nom = f"sante.manques[{rang}]"
        if not _cles(
            manque, {"composante", "metric_id", "raison"}, {"composante", "metric_id", "raison"}, nom, erreurs
        ):
            return
        if manque["composante"] not in ids:
            erreurs.append(f"{nom}.composante : composante connue")
        if type(manque["metric_id"]) is not str or _METRIQUE.fullmatch(manque["metric_id"]) is None:
            erreurs.append(f"{nom}.metric_id : identifiant de mesure du catalogue")
        if manque["raison"] not in M8_RAISONS_MANQUE:
            erreurs.append(f"{nom}.raison : raison fermée du producteur")
    if statut == "determine" and (manques or not toutes_determinees):
        erreurs.append("sante : un score déterminé n'a ni manque ni composante indéterminée")
    if statut == "indetermine" and not manques:
        erreurs.append("sante : un score indéterminé nomme ce qui manque")
    if not _entier(sante["bornes_invalides"], 0, 1000):  # type: ignore[index]
        erreurs.append("sante.bornes_invalides : entier positif ou nul")


def _m8_mesure(mesure: object, rang: int, erreurs: list[str]) -> None:
    nom = f"mesures[{rang}]"
    if not _cles(mesure, _M8_MESURE, _M8_MESURE, nom, erreurs):
        return
    if type(mesure["metric_id"]) is not str or _METRIQUE.fullmatch(mesure["metric_id"]) is None:  # type: ignore[index]
        erreurs.append(f"{nom}.metric_id : identifiant de mesure du catalogue")
    statut, fraicheur, valeur = mesure["statut"], mesure["fraicheur"], mesure["valeur"]  # type: ignore[index]
    if statut not in M8_STATUTS_MESURE or fraicheur not in M8_FRAICHEURS:
        erreurs.append(f"{nom} : statut et fraîcheur fermés du producteur")
        return
    if (statut == "calculee") != (valeur is not None) or (valeur is not None and not _decimal_ok(valeur)):
        erreurs.append(f"{nom}.valeur : texte décimal si et seulement si la mesure est calculée (jamais un zéro)")
    if (statut == "non_calculable") != (fraicheur == "manquant"):
        erreurs.append(f"{nom}.fraicheur : « manquant » si et seulement si la mesure n'est pas calculable")
    age, fenetre, dernier = mesure["age_s"], mesure["fenetre_s"], mesure["dernier_fait_le"]  # type: ignore[index]
    if fraicheur in ("a_jour", "perime"):
        if not _entier(age, 0, 10**10) or not _instant_ok(dernier):
            erreurs.append(f"{nom} : âge et instant du dernier fait requis pour une mesure à jour ou périmée")
        elif fenetre is not None and ((age <= fenetre) != (fraicheur == "a_jour")):
            erreurs.append(f"{nom}.fraicheur : incohérente avec l'âge et la fenêtre déclarée")
    elif fraicheur == "manquant" and (age is not None or valeur is not None):
        erreurs.append(f"{nom} : une mesure manquante n'a ni âge ni valeur")
    elif fraicheur in ("inconnu", "non_applicable") and dernier is not None and not _instant_ok(dernier):
        erreurs.append(f"{nom}.dernier_fait_le : instant avec fuseau ou null")
    if fenetre is not None and not _entier(fenetre, 1, 315_360_000):
        erreurs.append(f"{nom}.fenetre_s : secondes entières bornées ou null")
    # type: ignore[index]
    if type(mesure["version_definition"]) is not str or not 8 <= len(mesure["version_definition"]) <= 64:
        erreurs.append(f"{nom}.version_definition : empreinte de définition")
    liste = mesure["manque"]  # type: ignore[index]
    if not isinstance(liste, list) or len(liste) > 20 or not all(type(x) is str and 0 < len(x) <= 120 for x in liste):
        erreurs.append(f"{nom}.manque : liste bornée de noms")
    elif statut == "non_calculable" and not liste:
        erreurs.append(f"{nom}.manque : une mesure non calculable nomme son manque")


def valider_m8_synthese(page: object, arguments: Mapping | None) -> list[str]:
    erreurs: list[str] = []
    charge = page.get("resultat") if isinstance(page, Mapping) else None
    if not _cles(charge, _M8_RACINE, _M8_RACINE, "charge", erreurs):
        return erreurs
    # type: ignore[index]
    if charge["type"] != "SYNTHESE_DIRECTION" or charge["schema"] != "opsys.m8.synthese_direction/v1":
        erreurs.append("charge : contrat m8.synthese_direction v1 attendu")
    if not _instant_ok(charge["maintenant"]):  # type: ignore[index]
        erreurs.append("maintenant : instant avec fuseau")
    # type: ignore[index]
    elif arguments is not None and not _meme_instant(charge["maintenant"], arguments.get("maintenant")):
        erreurs.append("maintenant : différent de l'instant demandé")
    for cle in ("version_catalogue", "empreinte_registres"):
        if type(charge[cle]) is not str or _HEX64.fullmatch(charge[cle]) is None:  # type: ignore[index]
            erreurs.append(f"{cle} : condensat attendu")
    _m8_sante(charge["sante"], erreurs)  # type: ignore[index]
    mesures = charge["mesures"]  # type: ignore[index]
    if not isinstance(mesures, list) or not 1 <= len(mesures) <= 80:
        erreurs.append("mesures : liste de 1 à 80 mesures")
    else:
        ids = [m.get("metric_id") if isinstance(m, Mapping) else None for m in mesures]
        if len(set(map(str, ids))) != len(ids):
            erreurs.append("mesures : identifiants distincts")
        for rang, mesure in enumerate(mesures):
            _m8_mesure(mesure, rang, erreurs)
    avertissements = charge["avertissements"]  # type: ignore[index]
    if not isinstance(avertissements, Mapping) or len(avertissements) > 8:
        erreurs.append("avertissements : objet borné")
    if type(charge["mention"]) is not str or "CPA" not in charge["mention"]:  # type: ignore[index]
        erreurs.append("mention : mention comptable (CPA) attendue")
    return erreurs


# --------------------------------------------------------------------------------------------------------- M2
M2_PERIMETRES = frozenset({"tous les leads", "les leads de la personne authentifiée"})
M2_NIVEAUX = (80, 90, 95)
_M2_ANALYSE = {
    "perimetre", "reference", "pipeline", "entonnoir", "taux_conversion_des_resolus", "taux_qualification",
    "delai_de_cycle", "probabilite_de_conversion_par_etape", "valeur_ponderee", "seuils_declares", "avertissements",
    "empreinte_recu",
}  # fmt: skip
_M2_PREVISION = {
    "reference", "serie", "prevision_totale", "par_periode", "erreur_absolue_moyenne_un_pas", "niveau_courant",
    "seuils_declares", "methode", "avertissements", "empreinte_recu",
}  # fmt: skip


def _m2_intervalle(bloc: object, nom: str, erreurs: list[str]) -> None:
    """Un chiffre de M2 qui prétend à une valeur future ou pondérée porte son INTERVALLE : ``{niveau, bas, haut}``."""
    if not _cles(bloc, {"centre", "intervalle"}, {"centre", "intervalle", "methode", "horizon_periodes", "periode"},
                 nom, erreurs):  # fmt: skip
        return
    intervalle = bloc["intervalle"]  # type: ignore[index]
    if not _cles(intervalle, {"niveau", "bas", "haut"}, {"niveau", "bas", "haut"}, f"{nom}.intervalle", erreurs):
        erreurs.append(f"{nom} : un point sans intervalle est refusé")
        return
    # type: ignore[index]
    bas, haut, centre = _decimal(intervalle["bas"]), _decimal(intervalle["haut"]), _decimal(bloc["centre"])
    if intervalle["niveau"] not in M2_NIVEAUX or bas is None or haut is None or centre is None:
        erreurs.append(f"{nom} : niveau (80, 90 ou 95) et bornes en texte décimal")
    elif bas > haut:
        erreurs.append(f"{nom}.intervalle : borne basse au plus égale à la haute")


def _m2_mesure(bloc: object, nom: str, erreurs: list[str]) -> None:
    """Un taux/une probabilité : soit un chiffre avec son effectif ET son seuil atteint, soit un REFUS qui dit
    pourquoi."""
    if not isinstance(bloc, Mapping) or "valeur" not in bloc or not _entier(bloc.get("n"), 0, 10**9):
        erreurs.append(f"{nom} : {{valeur, n, seuil}} attendu")
        return
    seuil = bloc.get("seuil")
    if not _entier(seuil, 1, 10**6):
        erreurs.append(f"{nom}.seuil : entier positif")
        return
    if bloc["valeur"] is None:
        if bloc["n"] >= seuil or type(bloc.get("refus")) is not str or not bloc["refus"]:
            erreurs.append(f"{nom} : sans valeur, l'effectif est sous le seuil et le refus est dit")
    elif not _decimal_ok(bloc["valeur"]) or bloc["n"] < seuil or "refus" in bloc:
        erreurs.append(f"{nom} : un chiffre exige un effectif au seuil et ne porte aucun refus (aucune estimation)")


def valider_m2_analyse(page: object, arguments: Mapping | None) -> list[str]:
    erreurs: list[str] = []
    interne = page.get("resultat") if isinstance(page, Mapping) else None
    charge = interne.get("resultat") if isinstance(interne, Mapping) else None
    if not _cles(charge, _M2_ANALYSE, _M2_ANALYSE, "charge", erreurs):
        return erreurs
    if charge["perimetre"] not in M2_PERIMETRES:  # type: ignore[index]
        erreurs.append("perimetre : périmètre du contrat")
    if not _instant_ok(charge["reference"]) or (  # type: ignore[index]
        # type: ignore[index]
        arguments is not None and not _meme_instant(charge["reference"], arguments.get("horodatage"))
    ):
        erreurs.append("reference : instant demandé avec fuseau")
    # type: ignore[index]
    if type(charge["empreinte_recu"]) is not str or _HEX64.fullmatch(charge["empreinte_recu"]) is None:
        erreurs.append("empreinte_recu : condensat du reçu rejouable")
    pipeline, entonnoir = charge["pipeline"], charge["entonnoir"]  # type: ignore[index]
    if not isinstance(pipeline, Mapping) or not isinstance(pipeline.get("par_statut"), Mapping):
        erreurs.append("pipeline : par_statut attendu")
    else:
        comptes = list(pipeline["par_statut"].values())
        if not all(_entier(c, 0, 10**9) for c in comptes) or pipeline.get("total") != sum(comptes):
            erreurs.append("pipeline : comptes entiers dont la somme est le total")
        if not _entier(pipeline.get("ouverts"), 0, 10**9) or pipeline["ouverts"] > pipeline["total"]:
            erreurs.append("pipeline.ouverts : au plus le total")
    if not isinstance(entonnoir, Mapping) or not all(_entier(v, 0, 10**9) for v in entonnoir.values()):
        erreurs.append("entonnoir : comptes entiers")
    _m2_mesure(charge["taux_conversion_des_resolus"], "taux_conversion_des_resolus", erreurs)  # type: ignore[index]
    _m2_mesure(charge["taux_qualification"], "taux_qualification", erreurs)  # type: ignore[index]
    probas = charge["probabilite_de_conversion_par_etape"]  # type: ignore[index]
    if not isinstance(probas, Mapping) or not probas:
        erreurs.append("probabilite_de_conversion_par_etape : étapes attendues")
    else:
        for etape, bloc in probas.items():
            _m2_mesure(bloc, f"probabilite[{str(etape)[:20]}]", erreurs)
    delai = charge["delai_de_cycle"]  # type: ignore[index]
    if not isinstance(delai, Mapping) or (delai.get("valeurs") is None) == (delai.get("refus") is None):
        erreurs.append("delai_de_cycle : soit des valeurs, soit un refus qui dit pourquoi")
    pondere = charge["valeur_ponderee"]  # type: ignore[index]
    if not isinstance(pondere, Mapping) or "valeur_ponderee" not in pondere:
        erreurs.append("valeur_ponderee : bloc du contrat attendu")
    elif pondere["valeur_ponderee"] is None:
        if type(pondere.get("refus")) is not str or not pondere["refus"]:
            erreurs.append("valeur_ponderee : sans valeur, le refus est dit")
    else:
        _m2_intervalle(pondere["valeur_ponderee"], "valeur_ponderee", erreurs)
    if not isinstance(charge["avertissements"], list) or not charge["avertissements"]:  # type: ignore[index]
        erreurs.append("avertissements : liste non vide")
    return erreurs


def valider_m2_prevision(page: object, arguments: Mapping | None) -> list[str]:
    erreurs: list[str] = []
    interne = page.get("resultat") if isinstance(page, Mapping) else None
    charge = interne.get("resultat") if isinstance(interne, Mapping) else None
    if not _cles(charge, _M2_PREVISION, _M2_PREVISION, "charge", erreurs):
        return erreurs
    if not _instant_ok(charge["reference"]) or (  # type: ignore[index]
        # type: ignore[index]
        arguments is not None and not _meme_instant(charge["reference"], arguments.get("horodatage"))
    ):
        erreurs.append("reference : instant demandé avec fuseau")
    # type: ignore[index]
    if type(charge["empreinte_recu"]) is not str or _HEX64.fullmatch(charge["empreinte_recu"]) is None:
        erreurs.append("empreinte_recu : condensat du reçu rejouable")
    total = charge["prevision_totale"]  # type: ignore[index]
    _m2_intervalle(total, "prevision_totale", erreurs)
    horizon = total.get("horizon_periodes") if isinstance(total, Mapping) else None
    if not _entier(horizon, 1, 8):
        erreurs.append("prevision_totale.horizon_periodes : 1 à 8 périodes")
    periodes = charge["par_periode"]  # type: ignore[index]
    if not isinstance(periodes, list) or (horizon is not None and len(periodes) != horizon):
        erreurs.append("par_periode : une ligne par période de l'horizon")
    else:
        for rang, ligne in enumerate(periodes):
            _m2_intervalle(ligne, f"par_periode[{rang}]", erreurs)
    serie = charge["serie"]  # type: ignore[index]
    if (
        not isinstance(serie, Mapping)
        or not _entier(serie.get("periodes"), 1, 10**6)
        or not _entier(serie.get("evenements"), 0, 10**9)
    ):
        erreurs.append("serie : périodes et événements entiers")
    seuils = charge["seuils_declares"]  # type: ignore[index]
    if isinstance(serie, Mapping) and isinstance(seuils, Mapping):
        if (
            _entier(serie.get("periodes"))
            and _entier(seuils.get("periodes_minimum"))
            and (
                serie["periodes"] < seuils["periodes_minimum"]
                or serie.get("evenements", 0) < seuils.get("evenements_minimum", 0)
            )
        ):
            erreurs.append("serie : une prévision n'existe que sous les seuils d'échantillon déclarés atteints")
    else:
        erreurs.append("seuils_declares : seuils d'échantillon attendus")
    for cle in ("erreur_absolue_moyenne_un_pas", "niveau_courant"):
        if not _decimal_ok(charge[cle]):  # type: ignore[index]
            erreurs.append(f"{cle} : texte décimal")
    if not isinstance(charge["avertissements"], list) or not charge["avertissements"]:  # type: ignore[index]
        erreurs.append("avertissements : liste non vide (le centre n'est pas une promesse)")
    return erreurs


# --------------------------------------------------------------------------------------------------------- M5
M5_STATUTS_OBLIGATION = frozenset(
    {"SOURCE_PERIMEE", "INCOMPLETE", "ECHEANCE_PASSEE_A_VERIFIER", "DOCUMENTEE_A_VALIDER"}
)
M5_STATUTS_ECHEANCE_OBLIGATION = frozenset({"NON_DECLAREE", "PASSEE_A_VERIFIER", "A_VENIR"})
M5_STATUTS_TAXES = frozenset({"DOCUMENTE_A_VALIDER", "NON_CALCULABLE"})
M5_STATUTS_SOURCES = frozenset({"APPROUVE", "ESSAI_NON_APPROUVE", "REGLE_NON_RENSEIGNEE", "SANS_REGLE_REQUISE"})
_M5_OBLIGATION = {
    "id", "nom", "autorite", "periode", "echeance", "montant", "devise", "source_montant", "source_echeance", "annee",
    "version", "montant_utilisable", "echeance_statut", "statut", "manque",
}  # fmt: skip
_M5_RACINE_CAL = {"role", "type", "aujourd_hui", "obligations", "echeances_tps_tvq", "limites", "mention"}


def _taxes_nettes_ok(taxes: object) -> bool:
    """Taxes nettes d'une échéance : ``null`` (non calculables, manque dit par le producteur) ou un bloc dont la
    COUVERTURE est dite. Un montant (même ``0.00``) sans couverture n'est pas un fait : « un zéro ne peut pas être
    confirmé »."""
    if taxes is None:
        return True
    if not isinstance(taxes, Mapping) or not {"a_remettre", "couverture"} <= set(taxes):
        return False
    couverture = taxes["couverture"]
    return (
        _decimal_ok(taxes["a_remettre"])
        and isinstance(couverture, Mapping)
        and couverture.get("statut") in ("PARTIELLE", "COMPLETE")
    )


def valider_m5_calendrier(page: object, arguments: Mapping | None) -> list[str]:
    erreurs: list[str] = []
    interne = page.get("resultat") if isinstance(page, Mapping) else None
    charge = interne.get("resultat") if isinstance(interne, Mapping) else None
    if not _cles(charge, _M5_RACINE_CAL, _M5_RACINE_CAL, "charge", erreurs):
        return erreurs
    if charge["type"] != "CALENDRIER_PREPARATOIRE_M5":  # type: ignore[index]
        erreurs.append("charge : calendrier préparatoire M5 attendu")
    if _date(charge["aujourd_hui"]) is None or (  # type: ignore[index]
        arguments is not None and charge["aujourd_hui"] != arguments.get("aujourd_hui")  # type: ignore[index]
    ):
        erreurs.append("aujourd_hui : jour demandé")
    obligations = charge["obligations"]  # type: ignore[index]
    if not isinstance(obligations, list) or len(obligations) > 20:
        erreurs.append("obligations : liste bornée")
        return erreurs
    for rang, ligne in enumerate(obligations):
        nom = f"obligations[{rang}]"
        if not _cles(ligne, _M5_OBLIGATION, _M5_OBLIGATION, nom, erreurs):
            return erreurs
        if (
            ligne["statut"] not in M5_STATUTS_OBLIGATION
            or ligne["echeance_statut"] not in M5_STATUTS_ECHEANCE_OBLIGATION
        ):  # type: ignore[index]
            erreurs.append(f"{nom} : statuts fermés du producteur")
        # type: ignore[index]
        if ligne["montant"] is not None and (not _decimal_ok(ligne["montant"]) or ligne["devise"] != "CAD"):
            erreurs.append(f"{nom}.montant : texte décimal en CAD ou null")
        # type: ignore[index]
        if ligne["montant"] is None and (ligne["devise"] is not None or ligne["montant_utilisable"] is not None):
            erreurs.append(f"{nom} : sans montant, ni devise ni montant utilisable")
        if ligne["echeance"] is not None and _date(ligne["echeance"]) is None:  # type: ignore[index]
            erreurs.append(f"{nom}.echeance : jour civil ou null")
        if (ligne["echeance"] is None) != (ligne["echeance_statut"] == "NON_DECLAREE"):  # type: ignore[index]
            erreurs.append(f"{nom}.echeance_statut : « non déclarée » si et seulement si l'échéance est absente")
        if ligne["statut"] == "DOCUMENTEE_A_VALIDER" and ligne["manque"]:  # type: ignore[index]
            erreurs.append(f"{nom} : une obligation documentée n'a aucun manque")
        if ligne["statut"] in ("INCOMPLETE", "SOURCE_PERIMEE") and not ligne["manque"]:  # type: ignore[index]
            erreurs.append(f"{nom} : une obligation incomplète nomme ses manques")
        manques = ligne["manque"]  # type: ignore[index]
        if (
            not isinstance(manques, list)
            or len(manques) > 20
            or not all(isinstance(m, Mapping) and type(m.get("code")) is str for m in manques)
        ):
            erreurs.append(f"{nom}.manque : liste bornée de codes")
    taxes = charge["echeances_tps_tvq"]  # type: ignore[index]
    if not isinstance(taxes, Mapping) or taxes.get("statut") not in M5_STATUTS_TAXES:
        erreurs.append("echeances_tps_tvq : statut du producteur")
    elif taxes["statut"] == "DOCUMENTE_A_VALIDER":
        echeances = taxes.get("echeances")
        if not isinstance(echeances, list) or len(echeances) > 40:
            erreurs.append("echeances_tps_tvq.echeances : liste bornée")
        else:
            for rang, e in enumerate(echeances):
                if not (isinstance(e, Mapping) and _date(e.get("limite_paiement")) and _date(e.get("limite_production"))
                        and _date(e.get("periode_debut")) and _date(e.get("periode_fin"))
                        and e.get("statut") in {"A_VENIR", "EN_RETARD"}
                        and _taxes_nettes_ok(e.get("taxes_nettes"))):  # fmt: skip
                    erreurs.append(f"echeances_tps_tvq.echeances[{rang}] : dates, statut et taxes nettes du contrat")
        validation = taxes.get("validation_cpa")
        if (
            not isinstance(validation, Mapping)
            or not validation
            or not all(v in ("A_VALIDER", "VALIDE") for v in validation.values())
        ):
            erreurs.append("echeances_tps_tvq.validation_cpa : statut de validation par année (jamais omis)")
    if type(charge["mention"]) is not str or not charge["mention"]:  # type: ignore[index]
        erreurs.append("mention : mention d'analyse préparatoire attendue")
    return erreurs


_M5_STATUT_RACINE = {"schema", "aujourd_hui", "base", "sujets", "mention", "mention_comptable"}
_M5_BASE = {"parametres_renseignes", "par_statut", "non_renseignes", "empreinte_base"}


def valider_m5_statut_revue(page: object, arguments: Mapping | None) -> list[str]:
    erreurs: list[str] = []
    interne = page.get("resultat") if isinstance(page, Mapping) else None
    charge = interne.get("resultat") if isinstance(interne, Mapping) else None
    if not _cles(charge, _M5_STATUT_RACINE, _M5_STATUT_RACINE, "charge", erreurs):
        return erreurs
    if charge["schema"] != "opsys.m5.statut_revue_fiscale/v1":  # type: ignore[index]
        erreurs.append("charge : contrat m5.statut_revue_fiscale v1 attendu")
    if _date(charge["aujourd_hui"]) is None or (  # type: ignore[index]
        arguments is not None and charge["aujourd_hui"] != arguments.get("aujourd_hui")  # type: ignore[index]
    ):
        erreurs.append("aujourd_hui : jour demandé")
    base = charge["base"]  # type: ignore[index]
    if _cles(base, _M5_BASE, _M5_BASE, "base", erreurs):
        par_statut = base["par_statut"]
        if (
            not isinstance(par_statut, Mapping)
            or set(par_statut) != {"brouillon", "revu_1", "approuve"}
            or not all(_entier(v, 0, 10**6) for v in par_statut.values())
            or sum(par_statut.values()) != base["parametres_renseignes"]
        ):
            erreurs.append("base.par_statut : brouillon, revu_1 et approuve dont la somme est le total renseigné")
        if not _entier(base["non_renseignes"], 0, 10**6):
            erreurs.append("base.non_renseignes : entier positif ou nul")
        if type(base["empreinte_base"]) is not str or _HEX64.fullmatch(base["empreinte_base"]) is None:
            erreurs.append("base.empreinte_base : condensat attendu")
    sujets = charge["sujets"]  # type: ignore[index]
    if not isinstance(sujets, list) or not 1 <= len(sujets) <= 40:
        erreurs.append("sujets : liste de 1 à 40 sujets")
    else:
        cles = {
            "sujet",
            "genre",
            "statut_sources",
            "regles_requises",
            "regles_non_renseignees",
            "regles_non_approuvees",
        }
        for rang, sujet in enumerate(sujets):
            nom = f"sujets[{rang}]"
            if not _cles(sujet, cles, cles, nom, erreurs):
                return erreurs
            # type: ignore[index]
            if sujet["statut_sources"] not in M5_STATUTS_SOURCES or sujet["genre"] not in ("analyse", "piste"):
                erreurs.append(f"{nom} : statut et genre fermés")
                continue
            requises, manquantes, non_approuvees = (
                # type: ignore[index]
                sujet["regles_requises"], sujet["regles_non_renseignees"], sujet["regles_non_approuvees"]
            )  # fmt: skip
            if not all(_entier(v, 0, 1000) for v in (requises, manquantes, non_approuvees)) or (
                manquantes + non_approuvees > requises
            ):
                erreurs.append(f"{nom} : dénombrements cohérents")
                continue
            statut = sujet["statut_sources"]  # type: ignore[index]
            coherent = (
                (statut == "SANS_REGLE_REQUISE" and requises == 0)
                or (statut == "REGLE_NON_RENSEIGNEE" and manquantes > 0)
                or (statut == "ESSAI_NON_APPROUVE" and manquantes == 0 and non_approuvees > 0)
                or (statut == "APPROUVE" and requises > 0 and manquantes == 0 and non_approuvees == 0)
            )
            if not coherent:
                erreurs.append(
                    f"{nom}.statut_sources : incohérent avec les dénombrements (jamais « approuvé » par défaut)"
                )
    if type(charge["mention_comptable"]) is not str or "CPA" not in charge["mention_comptable"]:  # type: ignore[index]
        erreurs.append("mention_comptable : mention CPA attendue")
    return erreurs


# --------------------------------------------------------------------------------------------------------- M10
_M10_RACINE = {"total", "decalage", "limite", "consolidations", "suivant", "confidentialite"}
_M10_CONSOLIDATION = {
    "evenement_id", "consolide_le", "ligne_id", "n_mesures", "changements_definition", "anomalies",
    "premiere_consolidation",
}  # fmt: skip


def valider_m10_faits_analytiques(page: object, arguments: Mapping | None) -> list[str]:
    erreurs: list[str] = []
    charge = page.get("resultat") if isinstance(page, Mapping) else None
    if not _cles(charge, _M10_RACINE, _M10_RACINE, "charge", erreurs):
        return erreurs
    if charge["confidentialite"] != "FINANCIAL":  # type: ignore[index]
        erreurs.append("confidentialite : FINANCIAL attendu (jamais rendu dans un paquet de contexte)")
    total, decalage, limite = charge["total"], charge["decalage"], charge["limite"]  # type: ignore[index]
    if not (_entier(total, 0, 10**7) and _entier(decalage, 0, 10**7) and _entier(limite, 1, 8)):
        erreurs.append("pagination : total, décalage et limite entiers")
        return erreurs
    if arguments is not None and (decalage != arguments.get("decalage", 0)):
        erreurs.append("decalage : différent du décalage demandé")
    lignes = charge["consolidations"]  # type: ignore[index]
    if not isinstance(lignes, list) or len(lignes) > limite or len(lignes) > max(0, total - decalage):
        erreurs.append("consolidations : page bornée par la limite et le total")
        return erreurs
    vus: set[str] = set()
    for rang, ligne in enumerate(lignes):
        nom = f"consolidations[{rang}]"
        if not _cles(ligne, _M10_CONSOLIDATION, _M10_CONSOLIDATION, nom, erreurs):
            return erreurs
        # type: ignore[index]
        if type(ligne["evenement_id"]) is not str or _EVENEMENT_M8.fullmatch(ligne["evenement_id"]) is None:
            erreurs.append(f"{nom}.evenement_id : identifiant de consolidation M8")
        elif ligne["evenement_id"] in vus:  # type: ignore[index]
            erreurs.append(f"{nom}.evenement_id : distinct")
        vus.add(str(ligne["evenement_id"]))
        if not _instant_ok(ligne["consolide_le"]) or not _entier(ligne["n_mesures"], 1, 80):  # type: ignore[index]
            erreurs.append(f"{nom} : instant de consolidation et nombre de mesures")
        if type(ligne["premiere_consolidation"]) is not bool:  # type: ignore[index]
            erreurs.append(f"{nom}.premiere_consolidation : booléen")
        changements, anomalies = ligne["changements_definition"], ligne["anomalies"]  # type: ignore[index]
        if (
            not isinstance(changements, list)
            or len(changements) > 80
            or not all(
                isinstance(c, Mapping)
                and set(c) == {"metric_id", "ancienne", "nouvelle"}
                and _METRIQUE.fullmatch(str(c["metric_id"]))
                for c in changements
            )
        ):
            erreurs.append(f"{nom}.changements_definition : liste bornée de changements du contrat")
        if (
            not isinstance(anomalies, list)
            or len(anomalies) > 160
            or not all(
                isinstance(a, Mapping)
                and set(a) == {"metric_id", "type"}
                and a["type"] in ("devenue_non_calculable", "perimee", "echec_qualite")
                and _METRIQUE.fullmatch(str(a["metric_id"]))
                for a in anomalies
            )
        ):
            erreurs.append(f"{nom}.anomalies : liste bornée d'anomalies du contrat")
    suivant = charge["suivant"]  # type: ignore[index]
    attendu = decalage + limite if decalage + limite < total else None
    if suivant != attendu:
        erreurs.append("suivant : prochain décalage cohérent avec le total (ou null)")
    return erreurs


VALIDATEURS: dict[str, Callable[[object, Mapping | None], list[str]]] = {
    "m8.synthese_direction": valider_m8_synthese,
    "m2.analyse_pipeline": valider_m2_analyse,
    "m2.prevision_pipeline": valider_m2_prevision,
    "m5.calendrier_obligations": valider_m5_calendrier,
    "m5.statut_revue_fiscale": valider_m5_statut_revue,
    "m10.faits_analytiques": valider_m10_faits_analytiques,
}
