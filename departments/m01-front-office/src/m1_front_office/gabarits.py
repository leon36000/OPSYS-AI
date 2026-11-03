"""Gabarits de messages de M1 (SMS, courriels de rendez-vous) : du texte FIXE, versionné, jamais écrit par un modèle.

Un gabarit a un identifiant, une version, un canal et un modèle de texte à `{variables}` nommées. `rendre` remplace
chaque variable par une valeur contrôlée (jeu de caractères restreint, longueur bornée) et refuse toute variable
manquante ou en trop. Les phrases ajoutées par la boucle d'apprentissage (M1.13) n'entrent qu'après promotion humaine
: elles sont fournies par l'appelant (`phrases_actives`) et passent le même garde-fou de sortie que le reste.

Le garde-fou de sortie est celui du socle (`opsys.garde_fou_texte`) : aucun prix, aucune date d'exécution de chantier,
aucun engagement, aveu ou avis légal. Les dates d'un rendez-vous viennent toujours de M4 (code), jamais du texte.

Module pur : aucune horloge, aucune entrée-sortie.
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterable, Mapping

from opsys import garde_fou_texte as gft

PROFIL_SORTIE = gft.profil(
    "m1_gabarits",
    (
        gft.PRIX_MONTANT,
        gft.DATE_EXECUTION,
        gft.ENGAGEMENT,
        gft.AVEU,
        gft.AVIS_LEGAL,
    ),
)
SMS_LONGUEUR_MAX = 480
_VARIABLE = re.compile(r"\{([a-z_]+)\}")
_VALEUR = re.compile(r"^[\wÀ-ÿ'’ ,.:;()/\-hH]{1,120}$")


class RefusGabarit(ValueError):
    """Refus typé `REJ-M1-GABARIT-…` : le message commence par le code."""


@dataclasses.dataclass(frozen=True)
class Gabarit:
    identifiant: str
    version: int
    canal: str  # sms | courriel
    objet: str | None
    modele: str
    proactif: bool = False  # vrai : il exige un opt-in exprès (SMS) ; faux : réponse à un message du client
    divulgation: bool = False  # vrai : c'est la divulgation « assistant virtuel » exigée en premier

    @property
    def variables(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys(_VARIABLE.findall((self.objet or "") + self.modele)))


GABARITS: Mapping[str, Gabarit] = {
    g.identifiant: g
    for g in (
        Gabarit(
            "sms_divulgation_opt_in",
            1,
            "sms",
            None,
            "Bonjour, ici {avatar}, l'assistant virtuel (intelligence artificielle) de {entreprise}. Pour recevoir "
            "des rappels par texto, répondez OUI. Pour ne plus recevoir de messages, répondez STOP.",
            divulgation=True,
        ),
        Gabarit(
            "sms_appel_manque",
            1,
            "sms",
            None,
            "Bonjour, ici l'assistant virtuel (intelligence artificielle) de {entreprise}. Nous avons manqué votre "
            "appel; une personne vous rappellera. Répondez STOP pour ne plus recevoir de messages.",
            divulgation=True,
        ),
        Gabarit(
            "sms_accuse_photos",
            1,
            "sms",
            None,
            "Merci, nous avons bien reçu vos photos. Une personne de l'équipe de {entreprise} vous reviendra. "
            "Répondez STOP pour ne plus recevoir de messages.",
        ),
        Gabarit(
            "sms_statut_incertain",
            1,
            "sms",
            None,
            "Je vais vérifier avec l'équipe de {entreprise} et une personne vous répondra. Répondez STOP pour ne plus "
            "recevoir de messages.",
        ),
        Gabarit(
            "sms_paiement_par_equipe",
            1,
            "sms",
            None,
            "Pour le paiement de votre facture, l'équipe des finances de {entreprise} vous transmettra les "
            "instructions. Répondez STOP pour ne plus recevoir de messages.",
        ),
        Gabarit(
            "sms_rappel_rdv",
            1,
            "sms",
            None,
            "{entreprise} : rappel de votre rendez-vous le {date_texte} de {debut} à {fin}. Répondez STOP pour ne plus "
            "recevoir de messages.",
            proactif=True,
        ),
        Gabarit(
            "courriel_rdv_confirmation",
            1,
            "courriel",
            "Confirmation de votre rendez-vous",
            "Bonjour,\n\nVotre rendez-vous est confirmé : {date_texte}, de {debut} à {fin}.\nSi cette plage ne vous "
            "convient plus, répondez à ce courriel : une personne de l'équipe vous reviendra.\n\n{entreprise}",
        ),
        Gabarit(
            "courriel_rdv_rappel",
            1,
            "courriel",
            "Rappel de votre rendez-vous",
            "Bonjour,\n\nCeci est un rappel de votre rendez-vous : {date_texte}, de {debut} à {fin}.\n"
            "Si vous ne pouvez pas vous présenter, répondez à ce courriel : une personne de l'équipe vous "
            "reviendra.\n\n{entreprise}",
        ),
    )
}


def _valeur(nom: str, valeur: object) -> str:
    if not isinstance(valeur, str) or not _VALEUR.fullmatch(valeur) or "{" in valeur or "}" in valeur:
        raise RefusGabarit(
            f"REJ-M1-GABARIT-VARIABLE: la variable « {nom} » doit être un texte court sans accolade ni "
            "caractère de contrôle"
        )
    return valeur


def rendre(
    gabarit_id: str, variables: Mapping[str, object], phrases_actives: Iterable[str] = ()
) -> tuple[str | None, str]:
    """`(objet, corps)` ; lève `RefusGabarit` pour un gabarit inconnu, une variable manquante ou en trop, une valeur
    douteuse, un texte trop long ou refusé par le garde-fou de sortie."""
    g = GABARITS.get(gabarit_id)
    if g is None:
        raise RefusGabarit(f"REJ-M1-GABARIT-INCONNU: gabarit inconnu {gabarit_id!r}")
    attendues, fournies = set(g.variables), set(variables)
    if attendues != fournies:
        raise RefusGabarit(
            f"REJ-M1-GABARIT-VARIABLES: variables attendues {sorted(attendues)}, fournies {sorted(fournies)}"
        )
    valeurs = {k: _valeur(k, v) for k, v in variables.items()}

    def remplir(texte: str) -> str:
        return _VARIABLE.sub(lambda m: valeurs[m.group(1)], texte)

    objet = remplir(g.objet) if g.objet else None
    corps = remplir(g.modele)
    ajouts = [p.strip() if p.strip()[-1] in ".!?" else p.strip() + "." for p in phrases_actives if p.strip()]
    if ajouts:
        # Les phrases promues s'insèrent avant la dernière phrase (STOP) ou la signature : jamais après.
        texte_ajout = " ".join(ajouts)
        if g.canal == "courriel":
            haut, _, signature = corps.rpartition("\n\n")
            corps = f"{haut}\n{texte_ajout}\n\n{signature}"
        else:
            haut, _, fin = corps.rpartition(". ")
            corps = f"{haut}. {texte_ajout} {fin}" if haut else f"{texte_ajout} {corps}"
    if g.canal == "sms" and len(corps) > SMS_LONGUEUR_MAX:
        raise RefusGabarit(f"REJ-M1-GABARIT-LONGUEUR: {len(corps)} caractères, {SMS_LONGUEUR_MAX} au plus")
    violation = gft.premiere_violation(corps, PROFIL_SORTIE)
    if violation is not None:
        raise RefusGabarit(f"REJ-M1-GABARIT-GARDE-FOU: {violation.regle} : {violation.detail}")
    return objet, corps


def phrase_admissible(phrase: str) -> bool:
    """Une phrase ajoutée par apprentissage passe le garde-fou de sortie ET n'a ni lien, ni chiffre, ni adresse."""
    return gft.premiere_violation(phrase, PROFIL_SORTIE) is None and not re.search(r"[\d@/\\<>{}\[\]]|https?", phrase)
