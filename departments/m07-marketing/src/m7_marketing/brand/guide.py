"""Guide de ton et de marque généré à partir du profil (M7-MARQUE) : ce que la rédaction peut dire, ne doit jamais
dire, et ce
qui manque.

Le guide est une PROJECTION déterministe du profil déclaré : aucune phrase n'est inventée, aucun modèle n'écrit.
Chaque ligne
est soit une valeur du profil, soit une règle fixe de la porte qualité (`conformite`). Il respecte la doctrine du
profil :

  - un énoncé positif (promesse, avantages, valeurs, zones, preuve sociale, objections) n'y figure que s'il a été
  VALIDÉ par le
    propriétaire ; sinon il est listé « à faire valider » par son NOM seulement (jamais son texte : on ne propose pas
    à la
    rédaction ce que personne n'a assumé) ;
  - les restrictions déclarées (mots et messages interdits, voix, style) y figurent dès leur déclaration ;
  - ce que le profil ne dit pas est listé sous « à fournir », jamais comblé ;
  - toute valeur est une donnée sur UNE ligne (les valeurs v1 du profil sont réduites à une ligne et bornées ici) : une
    consigne glissée dans un champ du profil ne devient pas une instruction.

Module pur.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..usine import controle_texte, plateformes
from . import profil_v2

VERSION_GUIDE = "guide-marque/v1"
_MARQUEURS_NON_CONFIGURE = ("à configurer", "à confirmer")
_BORNE_V1 = 200


def _une_ligne(valeur: Any, borne: int = _BORNE_V1) -> str | None:
    """Une valeur v1 réduite à une ligne bornée ; `None` si vide ou encore au repère « à configurer/confirmer »."""
    if not isinstance(valeur, str):
        return None
    propre = " ".join(valeur.split())
    if not propre or propre.casefold().startswith(_MARQUEURS_NON_CONFIGURE):
        return None
    return propre if len(propre) <= borne else propre[: borne - 1] + "…"


def _puces(lignes: list[str]) -> list[str]:
    return [f"- {ligne}" for ligne in lignes]


def generer(profil: dict[str, Any]) -> dict[str, Any]:
    """Le guide du profil `profil` (déjà validé) : `{guide_id, version, sections, texte, completude}`."""
    completude = profil_v2.completude(profil)
    sections: list[dict[str, Any]] = []

    identite = [f"Nom commercial : {_une_ligne(profil.get('name')) or 'à fournir'}"]
    accroche = _une_ligne(profil.get("tagline"))
    ton = _une_ligne(profil.get("tone"))
    identite.append(f"Accroche : {accroche}" if accroche else "Accroche : à fournir par le propriétaire")
    identite.append(f"Ton général : {ton}" if ton else "Ton général : à fournir par le propriétaire")
    sections.append({"titre": "Identité", "lignes": identite})

    voix = profil.get("voix") if isinstance(profil.get("voix"), dict) else {}
    lignes_voix = []
    if "adresse" in voix:
        lignes_voix.append("Vouvoiement (« vous »)" if voix["adresse"] == "vous" else "Tutoiement (« tu »)")
    if "exclamations_max" in voix:
        lignes_voix.append(f"Points d'exclamation : {voix['exclamations_max']} au plus par texte")
    if "majuscules_max_pct" in voix:
        lignes_voix.append(f"Majuscules : {voix['majuscules_max_pct']} % des lettres au plus")
    if "emojis_max" in voix:
        lignes_voix.append(f"Émojis : {voix['emojis_max']} au plus par texte")
    sections.append({"titre": "Voix déclarée", "lignes": lignes_voix or ["Aucune voix déclarée : à fournir."]})

    peut_dire: list[str] = []
    a_valider: list[str] = []
    for champ, libelle in (
        ("promesse", "Promesse"),
        ("avantages", "Avantages"),
        ("valeurs", "Valeurs"),
        ("zones_desservies", "Zones desservies"),
        ("preuve_sociale", "Preuve sociale"),
    ):
        etat = completude["champs"][champ]
        valeur = profil.get(champ)
        if etat == profil_v2.ETAT_VALIDE:
            peut_dire.append(
                f"{libelle} : {valeur}" if isinstance(valeur, str) else f"{libelle} : " + " ; ".join(valeur)
            )
        elif etat == profil_v2.ETAT_A_VALIDER:
            a_valider.append(champ)
    if completude["champs"]["objections_frequentes"] == profil_v2.ETAT_VALIDE:
        for item in profil["objections_frequentes"]:
            peut_dire.append(f"Si on objecte « {item['objection']} » : {item['reponse']}")
    elif completude["champs"]["objections_frequentes"] == profil_v2.ETAT_A_VALIDER:
        a_valider.append("objections_frequentes")
    garanties = [g for g in profil.get("garanties_validees") or [] if isinstance(g, str)]
    if garanties:
        peut_dire.extend(f"Garantie validée (mot pour mot) : {g}" for g in garanties)
    sections.append(
        {"titre": "Ce que la marque peut dire", "lignes": peut_dire or ["Aucun énoncé validé : à faire valider."]}
    )
    sections.append(
        {
            "titre": "À faire valider par le propriétaire (ne pas citer)",
            "lignes": [f"{nom}" for nom in a_valider] or ["Rien en attente."],
        }
    )

    interdits: list[str] = []
    interdits.extend(f"Mot interdit : {m}" for m in profil.get("mots_interdits") or [])
    interdits.extend(f"Message interdit : {m}" for m in profil.get("messages_interdits") or [])
    interdits.extend(f"Garantie non validée, ne jamais la citer : {g}" for g in profil.get("garanties_a_valider") or [])
    interdits.extend(f"Règle de la porte qualité : {libelle}" for libelle in controle_texte.LIBELLES_REGLES.values())
    sections.append({"titre": "À ne jamais dire", "lignes": interdits})

    par_plateforme = []
    style = profil.get("style_plateforme") if isinstance(profil.get("style_plateforme"), dict) else {}
    for plateforme in plateformes.PLATEFORMES:
        regles = style.get(plateforme.code, {})
        morceaux = [f"{plateforme.longueur_max} caractères au plus (plafond interne)"]
        if "longueur_min" in regles:
            morceaux.append(f"{regles['longueur_min']} au moins")
        if "longueur_max" in regles:
            morceaux.append(f"{regles['longueur_max']} au plus pour cette marque")
        if "hashtags_max" in regles:
            morceaux.append(f"{regles['hashtags_max']} mots-clics au plus")
        if "emojis_max" in regles:
            morceaux.append(f"{regles['emojis_max']} émojis au plus")
        par_plateforme.append(f"{plateforme.libelle} : " + ", ".join(morceaux))
    sections.append({"titre": "Par plateforme", "lignes": par_plateforme})

    mentions = profil.get("mentions_requises") or []
    if mentions:
        validee = profil_v2.est_valide(profil, "mentions_requises")
        lignes_mentions = [f"Mention requise sur tout contenu public : {m}" for m in mentions]
        if not validee:
            lignes_mentions.append("Ces mentions sont à faire valider : les gabarits ne les ajoutent pas avant.")
    else:
        lignes_mentions = ["Aucune mention requise déclarée."]
    sections.append({"titre": "Mentions", "lignes": lignes_mentions})

    sections.append(
        {"titre": "À fournir par le propriétaire", "lignes": completude["a_fournir"] or ["Rien ne manque."]}
    )

    texte = "\n\n".join(f"{s['titre']}\n" + "\n".join(_puces(s["lignes"])) for s in sections)
    empreinte = hashlib.sha256(json.dumps(sections, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    return {
        "version": VERSION_GUIDE,
        "guide_id": empreinte[:16],
        "sections": sections,
        "texte": texte,
        "completude": completude,
    }
