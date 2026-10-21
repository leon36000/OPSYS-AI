"""Gabarits fixes des cinq variantes (PLAN T4.17) : le texte que le CODE compose, sans modèle.

Le texte ne dit que ce que le chantier et le profil de marque disent : la marque, son accroche, la nature des
travaux et, si le WCT la porte, la ville. Aucun prix, aucune date, aucune garantie, aucun chiffre, aucun nom :
un gabarit qui en contiendrait serait refusé par `controle_texte`, comme tout autre texte (le contrôle ne fait
pas confiance à sa source). C'est le repli quand aucun modèle ne rédige (P10, dégradation gracieuse) et la base
que le modèle peut remplacer plateforme par plateforme (`textes`).

Module pur : aucune entrée-sortie, aucun import `opsys`.
"""

from __future__ import annotations

import dataclasses


@dataclasses.dataclass(frozen=True)
class Matiere:
    """Les faits d'un chantier, tels que le WCT reçu et le profil de marque les donnent.

    `nature` : la nature des travaux, en mots (libellé du service de l'entreprise, ou `type_travaux` d'un lead v1
    sans les soulignés). `ville` : celle du WCT, `None` quand il n'en porte pas (M4 ne la publie pas : jamais
    inventée). `accroche` : la promesse de marque du profil, peut être vide."""

    marque: str
    accroche: str
    nature: str
    ville: str | None = None


def _minuscule_initiale(mots: str) -> str:
    """Première lettre en minuscule, sauf un sigle (« TPS », « RBQ ») : le libellé se glisse dans une phrase."""
    if len(mots) > 1 and mots[1].isupper():
        return mots
    return mots[:1].lower() + mots[1:]


def _majuscule_initiale(mots: str) -> str:
    return mots[:1].upper() + mots[1:]


def _lieu(ville: str | None) -> str:
    return f" à {ville}" if ville else ""


def _de(nom: str) -> str:
    """« de X » ou « d'X » : l'élision devant une voyelle (le h n'est pas traité : muet ou aspiré, le mot le dit)."""
    voyelles = "aeiouyàâäéèêëîïôöùûüœ"
    return f"d'{nom}" if nom[:1].casefold() in voyelles else f"de {nom}"


def _phrase(accroche: str) -> str:
    """L'accroche du profil, terminée par un point si elle n'a pas de ponctuation finale (elle précède une phrase)."""
    propre = accroche.strip()
    return propre if not propre or propre[-1] in ".!?…»" else f"{propre}."


def _accroche(matiere: Matiere) -> str:
    phrase = _phrase(matiere.accroche)
    return f"{phrase}\n\n" if phrase else ""


def _facebook(m: Matiere) -> str:
    return (
        f"Chantier terminé{_lieu(m.ville)} : {_minuscule_initiale(m.nature)}.\n\n"
        f"{_accroche(m)}"
        f"L'équipe {_de(m.marque)} vient de terminer ce projet. Vous avez un projet semblable ? "
        "Écrivez-nous pour demander une soumission."
    )


def _instagram(m: Matiere) -> str:
    return (
        f"{_majuscule_initiale(m.nature)}{_lieu(m.ville)} : projet terminé par l'équipe {_de(m.marque)}.\n\n"
        f"{_accroche(m)}"
        "Un projet semblable en tête ? Le lien pour demander une soumission est dans notre bio."
    )


def _fiche_google(m: Matiere) -> str:
    return (
        f"Nouveau chantier terminé{_lieu(m.ville)} : {_minuscule_initiale(m.nature)}. "
        f"{_phrase(m.accroche) + ' ' if m.accroche.strip() else ''}"
        f"Contactez {m.marque} pour demander une soumission."
    )


def _video_courte(m: Matiere) -> str:
    return (
        f"Accroche : « Chantier terminé{_lieu(m.ville)} : {_minuscule_initiale(m.nature)}. »\n"
        "Scène 1 : plan large du résultat final (photo du chantier terminé).\n"
        "Scène 2 : détail du travail terminé (deuxième photo du chantier).\n"
        f"Scène 3 : le nom {m.marque} à l'écran.\n"
        f"Appel à l'action : « {m.marque} : demandez votre soumission. »"
    )


def _demande_temoignage(m: Matiere) -> str:
    return (
        "Bonjour,\n\n"
        f"Merci d'avoir confié à {m.marque} vos travaux de {_minuscule_initiale(m.nature)}{_lieu(m.ville)}. "
        "Accepteriez-vous de nous écrire deux ou trois phrases sur votre expérience ? "
        "Nous ne publierons rien sans votre accord explicite.\n\n"
        f"Cordialement,\nL'équipe {_de(m.marque)}"
    )


_COMPOSITEURS = {
    "facebook": _facebook,
    "instagram": _instagram,
    "fiche_google": _fiche_google,
    "video_courte": _video_courte,
    "demande_temoignage": _demande_temoignage,
}


def composer(plateforme_code: str, matiere: Matiere) -> str:
    """Le texte du gabarit de cette plateforme ; `KeyError` si le code n'a pas de gabarit."""
    try:
        compositeur = _COMPOSITEURS[plateforme_code]
    except KeyError:
        raise KeyError(f"aucun gabarit pour la plateforme {plateforme_code!r}") from None
    return compositeur(matiere)
