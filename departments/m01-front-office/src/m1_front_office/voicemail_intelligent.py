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
from collections.abc import Sequence
from typing import Any

from . import qualification

MAX_ADRESSE = 120
MAX_NOM = 80
# Types de voie du français québécois courant. C'est du vocabulaire de lecture, pas une donnée d'entreprise : une
# adresse sans type de voie n'est pas reconnue (fail-closed), même si elle contient un numéro civique.
_TYPES_DE_VOIE = (
    "rue|avenue|av\\.?|boulevard|boul\\.?|chemin|ch\\.?|rang|route|mont[ée]e|place|impasse|all[ée]e|croissant|"
    "autoroute|lotissement"
)
_ADRESSE = re.compile(
    rf"\b(?P<numero>\d{{1,6}})(?:\s*[-–]\s*\d{{1,6}})?\s+"
    rf"(?:(?:app(?:artement|art)?\.?\s*)\d+\s+)?"
    rf"(?P<voie>{_TYPES_DE_VOIE})\s+"
    r"(?P<suite>[A-Za-zÀ-ÿ0-9'’\- ]{2,70})",
    re.IGNORECASE,
)
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
    r"\b(?:rappele[rz]|rappel|rappelle|retour\s+d['’]appel|demande\s+un\s+rappel)\b", re.IGNORECASE
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
            if 2 <= len(nom) <= MAX_NOM:
                return nom
    return None


def _adresse(texte: str, zone_desservie: Sequence[str]) -> str | None:
    trouve = _ADRESSE.search(texte)
    if trouve is None:
        return None
    suite = trouve.group("suite").strip(" ,;:!?")
    # « 123 rue des Lilas à Laval » : la ville est un fait séparé, pas le nom de la rue.
    for ville in sorted(zone_desservie, key=len, reverse=True):
        suite = re.split(
            rf"\s+(?:à|a|au|aux)\s+{re.escape(ville)}\b.*$", suite, maxsplit=1, flags=re.IGNORECASE
        )[0].strip(" ,;:!?")
    if not suite:
        return None
    adresse = f"{trouve.group('numero')} {trouve.group('voie')} {suite}"
    adresse = re.sub(r"\s+", " ", adresse).strip(" ,;:!?")
    return adresse if 4 <= len(adresse) <= MAX_ADRESSE else None


def _telephone_mentionne(texte: str, telephone: str) -> str | None:
    contact = qualification.contact_du_texte(texte) or {}
    brut = contact.get("telephone")
    if not isinstance(brut, str) or not brut.strip():
        return None
    chiffres = re.sub(r"\D", "", brut)
    if len(chiffres) == 10:
        chiffres = "1" + chiffres
    if not (len(chiffres) == 11 and chiffres.startswith("1")):
        return None
    normalise = "+" + chiffres
    return None if normalise == telephone else normalise


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


def analyser(
    transcription: str,
    *,
    telephone: str,
    services: Sequence[Any],
    zone_desservie: Sequence[str],
) -> dict[str, Any]:
    """Ce que la transcription établit, sans rien inventer. Lève `ValueError` sur une entrée inutilisable.

    `services` : les services DÉCLARÉS par le profil (`opsys.taxonomie.Service`), jamais une liste locale.
    `zone_desservie` : les villes de la zone déclarée par le profil, requise et non vide.
    """
    if not isinstance(transcription, str) or not transcription.strip():
        raise ValueError("REJ-VOICEMAIL-TRANSCRIPTION-VIDE: une transcription non vide est requise")
    if not isinstance(telephone, str) or not re.fullmatch(r"\+[1-9][0-9]{6,14}", telephone):
        raise ValueError("REJ-VOICEMAIL-TELEPHONE: un numéro E.164 de l'appel est requis")
    if not zone_desservie:
        raise ValueError("REJ-VOICEMAIL-ZONE: la zone desservie du profil est requise")
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
    demande_rappel = _DEMANDE_RAPPEL.search(transcription) is not None
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
