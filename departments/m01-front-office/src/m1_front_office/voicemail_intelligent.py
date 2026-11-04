"""Messagerie vocale intelligente de M1 (M1.5) : lire une transcription SANS modèle et en tirer des faits bornés.

Ce module est PUR : aucune horloge, aucune base, aucun réseau, aucun audio. Il ne transcrit rien (le STT est une
frontière séparée, `voicemail_stt.py`) et n'écrit nulle part. Son contrat est volontairement étroit :

- **résumé déterministe** : composé de phrases fixes à partir des seuls faits reconnus, jamais d'un extrait du texte
  de l'appelant (une consigne hostile ne peut donc pas devenir le résumé) ;
- **extraction bornée** : nom seulement sur une formule explicite (« je m'appelle », « mon nom est », « c'est »,
  « ici ») suivie de 2 à 4 mots capitalisés ; adresse seulement avec un numéro civique ET un type de voie connu ;
  téléphone mentionné seulement s'il est lisible et différent du numéro de l'appel ; service et ville par la même
  règle que la qualification (`qualification.diagnostiquer`, taxonomie du profil) ; urgence seulement si le texte
  porte un marqueur explicite, jamais inférée ;
- **manquants nommés** : ce que la transcription n'établit pas est dit (`nom`, `service`, `ville`, `adresse`), pour
  qu'une personne sache quoi demander au rappel ;
- **demande de rappel** : reconnue par des formules explicites (`rappelez-moi`, `rappeler`, `retour d'appel`), jamais
  supposée.

Aucune de ces valeurs n'est un prix, une date, un engagement, un avis ou un sentiment : le module ne produit rien de
tel. Une adresse est un renseignement personnel (Loi 25) : elle n'est lue que si le texte a été conservé avec le
consentement `accorde` par l'appelant (`_importer_appel`), et elle reste au registre interne de l'instance, jamais dans
un événement du bus.
"""

from __future__ import annotations

import re
from collections.abc import Sequence, Set
from typing import Any

from . import qualification

MAX_ADRESSE = 120
MAX_NOM = 80
# Une suite d'adresse plus longue qu'une rue et son appartement est coupée : c'est une borne de
# lecture, pas une donnée d'entreprise.
MAX_MOTS_SUITE_ADRESSE = 8
# Types de voie du français québécois courant. C'est du vocabulaire de lecture, pas une donnée d'entreprise : une
# adresse sans type de voie n'est pas reconnue (fail-closed), même si elle contient un numéro civique.
_TYPES_DE_VOIE = (
    "rue|avenue|av\\.?|boulevard|boul\\.?|chemin|ch\\.?|rang|route|mont[ée]e|place|impasse|all[ée]e|croissant|"
    "autoroute|lotissement"
)
_ADRESSE = re.compile(
    rf"\b(?P<numero>\d{{1,6}})(?:\s*[-–]\s*\d{{1,6}})?(?:\s*,\s*|\s+)"
    rf"(?:(?:app(?:artement|art)?\.?\s*)\d+\s+)?"
    rf"(?P<voie>{_TYPES_DE_VOIE})\s+"
    r"(?P<suite>[A-Za-zÀ-ÿ0-9'’.\- ]{2,120})",
    re.IGNORECASE,
)
# Mots après lesquels la suite d'adresse s'arrête : formule de rappel, consigne, conjonction. Sans
# ponctuation (STT), c'est ce qui empêche l'adresse d'avaler la phrase suivante, une consigne ou un
# numéro de téléphone. Liste FERMÉE, vocabulaire de lecture : elle ne décrit aucune rue réelle.
_MOTS_PIVOT_ADRESSE = frozenset(
    {
        "rappelez", "rappeler", "rappelle", "rappel", "ignore", "ignores", "ignorez", "ignorer",
        "oublie", "oublies", "oubliez", "oublier", "envoie", "envoyez", "envoyer", "instructions",
        "instruction", "consignes", "consigne", "prompt", "prompts", "systeme", "system", "et",
        "puis", "mais", "car", "donc", "merci", "bonjour", "svp", "stp",
    }
)
# Verbes d'instruction et mots d'injection : un nom ou une adresse qui en contient un est refusé
# (champ manquant déclaré), jamais recopié dans le résumé. Liste FERMÉE et testée.
_MOTS_INSTRUCTION = frozenset(
    {
        "ignore", "ignores", "ignorez", "ignorer", "oublie", "oublies", "oubliez", "oublier",
        "envoie", "envoyez", "envoyer", "instructions", "instruction", "consignes", "consigne",
        "prompt", "prompts", "systeme", "system",
    }
)
_ABREVIATIONS_ADRESSE = frozenset({"app", "appart", "av", "boul", "ch", "st", "ste"})
_PREPOSITIONS_FIN_ADRESSE = frozenset({"a", "à", "au", "aux"})
_NOM_APRES_FORMULE = re.compile(
    r"(?i:\b(?:je m'appelle|mon nom est|mon nom c'est|ici)\b)\s+"
    r"(?P<nom>[A-ZÀ-ÖØ-Þ][\wÀ-ÿ'’\-]+(?:\s+[A-ZÀ-ÖØ-Þ][\wÀ-ÿ'’\-]+){1,3})"
)
_NOM_APRES_C_EST = re.compile(
    r"(?i:\bc'est\b)\s+"
    r"(?P<nom>[A-ZÀ-ÖØ-Þ][\wÀ-ÿ'’\-]+(?:\s+[A-ZÀ-ÖØ-Þ][\wÀ-ÿ'’\-]+){1,3})"
)
# Mots qui ne sont jamais un nom de personne, même capitalisés en début de phrase.
_MOTS_NON_NOM = frozenset(
    {
        "bonjour", "allo", "allô", "merci", "monsieur", "madame", "mademoiselle", "urgent", "urgence",
        "toiture", "rue", "avenue", "boulevard", "chemin", "rang", "route", "place", "impasse", "allee",
        "allée", "croissant", "autoroute", "laval", "quebec", "québec", "longueuil", "brossard", "terrebonne",
        "repentigny", "mascouche", "blainville", "saint", "sainte",
    }
)
_DEMANDE_RAPPEL = re.compile(
    r"\b(?:rappele[rz](?:[-\s]moi)?|retour\s+d['’]appel|demande\s+(?:une?)\s+rappel)\b", re.IGNORECASE
)
# « Ne me rappelez pas », « sans retour d'appel » : la négation explicite touche la formule.
_NEGATION_AVANT_RAPPEL = re.compile(
    r"(?:\b(?:ne|n['’])\s*(?:me\s+|m['’]\s*|vous\s+|nous\s+|te\s+|t['’]\s*)?"
    r"|\bpas\s+(?:de\s+)?(?:me\s+|m['’]\s*|vous\s+|nous\s+)?"
    r"|\bsans\s+(?:me\s+|m['’]\s*|vous\s+|nous\s+)?"
    r"|\baucun(?:e)?\s+(?:demande\s+de\s+)?)\s*$",
    re.IGNORECASE,
)
_NEGATION_APRES_RAPPEL = re.compile(
    r"^\s*(?:-\s*)?(?:moi\s*)?(?:surtout\s+|vraiment\s+)?(?:pas|plus|jamais)\b", re.IGNORECASE
)


def _sans_accent(texte: str) -> str:
    return qualification.sans_accent(texte)


def _nom(texte: str, mots_de_services: frozenset[str] = frozenset()) -> str | None:
    exclus = _MOTS_NON_NOM | mots_de_services
    for motif in (_NOM_APRES_FORMULE, _NOM_APRES_C_EST):
        for trouve in motif.finditer(texte):
            mots = trouve.group("nom").split()
            while mots and _sans_accent(mots[-1]).strip(".,;:!?") in exclus:
                mots.pop()
            if len(mots) < 2:
                continue
            nom = " ".join(mots).strip(" .,;:!?")
            if any(_sans_accent(mot).strip(".,;:!?") in _MOTS_INSTRUCTION for mot in mots):
                continue
            if 2 <= len(nom) <= MAX_NOM:
                return nom
    return None


def _suite_adresse(suite: str, zone_desservie: Sequence[str]) -> list[str]:
    """Mots de la suite d'adresse, coupés à la première consigne, ponctuation, ville ou téléphone."""
    villes = {_sans_accent(ville) for ville in zone_desservie}
    mots = []
    for brut in suite.split():
        mot = brut.strip(" ,;:!?")
        if not mot:
            continue
        nu = _sans_accent(mot).strip(".,;:!?")
        if not nu or nu in _PREPOSITIONS_FIN_ADRESSE or nu in _MOTS_PIVOT_ADRESSE or nu in villes:
            break
        chiffres = re.sub(r"\D", "", mot)
        if len(chiffres) >= 3 and not re.search(r"[A-Za-zÀ-ÿ]", mot):
            break
        if mot.endswith((".", "!", "?", ";")) and nu not in _ABREVIATIONS_ADRESSE:
            mots.append(mot.rstrip(".!?;,"))
            break
        if len(mots) >= MAX_MOTS_SUITE_ADRESSE:
            break
        mots.append(mot.rstrip(",;!?"))
    return [mot for mot in mots if mot]


def _adresse(texte: str, zone_desservie: Sequence[str]) -> str | None:
    trouve = _ADRESSE.search(texte)
    if trouve is None:
        return None
    suite = _suite_adresse(trouve.group("suite"), zone_desservie)
    if not suite:
        return None
    adresse = f"{trouve.group('numero')} {trouve.group('voie')} {' '.join(suite)}"
    adresse = re.sub(r"\s+", " ", adresse).strip(" ,;:!?")
    return adresse if 4 <= len(adresse) <= MAX_ADRESSE else None


def _telephone_mentionne(texte: str, telephone: str) -> str | None:
    """Le premier numéro du texte qui n'est pas celui de l'appelant, normalisé en E.164, ou `None`."""
    for brut in qualification.telephones_du_texte(texte):
        chiffres = re.sub(r"\D", "", brut)
        if len(chiffres) == 10:
            chiffres = "1" + chiffres
        if len(chiffres) == 11 and chiffres.startswith("1"):
            normalise = "+" + chiffres
            if normalise != telephone:
                return normalise
    return None


def _demande_rappel(texte: str) -> bool:
    """Vrai si une formule explicite de rappel est présente et qu'aucune négation ne la touche."""
    for trouve in _DEMANDE_RAPPEL.finditer(texte):
        avant = re.split(r"[.!?;,\n]", texte[: trouve.start()])[-1]
        if _NEGATION_AVANT_RAPPEL.search(avant):
            continue
        if _NEGATION_APRES_RAPPEL.match(texte[trouve.end():]):
            continue
        return True
    return False


def _composer_resume(
    *, nom: str | None, service: str | None, services_evoques: Sequence[str], ville: str | None,
    adresse: str | None, urgence: bool, manquants: Sequence[str], demande_rappel: bool,
) -> str:
    phrases = [f"Message vocal de {nom}." if nom else "Message vocal d'un appelant non identifié."]
    if service is not None:
        phrases.append(f"Service reconnu : {service}.")
    elif services_evoques:
        phrases.append(f"Plusieurs services évoqués ({', '.join(services_evoques)}) : demander lequel.")
    else:
        phrases.append("Aucun service déclaré n'est reconnu.")
    phrases.append(f"Ville : {ville}." if ville else "Ville non reconnue.")
    if adresse:
        phrases.append(f"Adresse : {adresse}.")
    phrases.append("Urgence déclarée." if urgence else "Urgence non déclarée.")
    if manquants:
        phrases.append("À obtenir : " + ", ".join(manquants) + ".")
    if demande_rappel:
        phrases.append("Rappel demandé.")
    return " ".join(phrases)


def _valider_zone(zone_desservie: Sequence[str]) -> list[str]:
    """La zone du profil : une séquence (liste, tuple, ensemble) de noms de villes non vides, jamais une chaîne."""
    if isinstance(zone_desservie, (str, bytes)) or not isinstance(zone_desservie, (Sequence, Set)):
        raise ValueError(
            "REJ-VOICEMAIL-ZONE: la zone desservie du profil doit être une séquence de villes non vides "
            "(liste, tuple ou ensemble de chaînes), jamais une chaîne ni un itérable unique"
        )
    villes = list(zone_desservie)
    if not villes or any(not isinstance(ville, str) or not ville.strip() for ville in villes):
        raise ValueError(
            "REJ-VOICEMAIL-ZONE: la zone desservie du profil est requise et chaque ville doit être une chaîne non vide"
        )
    return villes


def analyser(
    transcription: str,
    *,
    telephone: str,
    services: Sequence[Any],
    zone_desservie: Sequence[str],
) -> dict[str, Any]:
    """Ce que la transcription établit, sans rien inventer. Lève `ValueError` sur une entrée inutilisable.

    `services` : les services DÉCLARÉS par le profil (`opsys.taxonomie.Service`), jamais une liste locale.
    `zone_desservie` : les villes de la zone déclarée par le profil, requise et non vide (liste, tuple ou
    ensemble de chaînes ; une chaîne est refusée plutôt que lue lettre par lettre).
    """
    if not isinstance(transcription, str) or not transcription.strip():
        raise ValueError("REJ-VOICEMAIL-TRANSCRIPTION-VIDE: une transcription non vide est requise")
    if not isinstance(telephone, str) or not re.fullmatch(r"\+[1-9][0-9]{6,14}", telephone):
        raise ValueError("REJ-VOICEMAIL-TELEPHONE: un numéro E.164 de l'appel est requis")
    zone_desservie = _valider_zone(zone_desservie)
    diagnostic = qualification.diagnostiquer(
        transcription, zone_desservie, services, contact_canal={"telephone": telephone}
    )
    mots_de_services = frozenset(
        forme
        for service in services
        for mot in getattr(service, "mots_cles", ())
        for forme in (_sans_accent(mot), _sans_accent(mot) + "s")
    )
    nom = _nom(transcription, mots_de_services)
    adresse = _adresse(transcription, zone_desservie)
    extraction = {
        "nom": nom,
        "telephone": telephone,
        "telephone_mentionne": _telephone_mentionne(transcription, telephone),
        "service": diagnostic["service"],
        "ville": diagnostic["ville"],
        "adresse": adresse,
        "urgence": diagnostic["urgence_declaree"],
    }
    manquants = [champ for champ in ("nom", "service", "ville", "adresse") if extraction[champ] is None]
    demande_rappel = _demande_rappel(transcription)
    return {
        "extraction": extraction,
        "services_evoques": list(diagnostic["services_evoques"]),
        "champs_manquants": manquants,
        "demande_rappel": demande_rappel,
        "resume": _composer_resume(
            nom=nom,
            service=diagnostic["service"],
            services_evoques=diagnostic["services_evoques"],
            ville=diagnostic["ville"],
            adresse=adresse,
            urgence=diagnostic["urgence_declaree"],
            manquants=manquants,
            demande_rappel=demande_rappel,
        ),
    }


__all__ = ["MAX_ADRESSE", "MAX_NOM", "analyser"]
