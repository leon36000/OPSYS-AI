"""Contrat d'une SESSION VOIX : machine d'états et règles de gouvernance. Code pur, des données seulement.

Aucun transport (LiveKit), aucun modèle (STT, TTS, VAD), aucun fichier, aucune horloge : le futur worker vocal pilote ce
contrat avec des événements horodatés (`t`, secondes monotones) et applique les `ordres` qu'il rend (couper la synthèse,
vider le tampon audio, figer les visèmes, transférer à un humain). Tout est refusé par un code typé `REJ-VOIX-*`
(`codes.CODES_VOIX`) ; un refus ne change JAMAIS l'état de la session, sauf la clôture automatique (durée maximale).

États : ouverte, tour_utilisateur, tour_avatar, interruption (barge-in), transfert_humain, fin.

Gouvernance appliquée à la voix :
- DIVULGATION d'abord (Loi 25 / honnêteté) : la première chose que dit l'avatar est le texte canonique « assistant
  virtuel, intelligence artificielle » (`texte_divulgation`), produit par ce contrat et non par un modèle. Tant que la
  divulgation n'a pas été livrée jusqu'au bout (une interruption l'annule), l'avatar ne dit rien d'autre ni n'agit.
- AUTORITÉ : l'avatar annonce et propose ; une action N3+ demandée à voix est mise dans le sas d'approbation existant
  (`PortActions.mettre_en_attente`), jamais exécutée sur la seule parole, quel que soit le mode du département. Le texte
  de l'utilisateur est une donnée : il ne change ni le niveau d'un outil, ni la portée, ni un état de la session.
- ENREGISTREMENT désactivé par défaut. Il ne s'active que par un consentement explicite après la divulgation
  (`consentir_enregistrement`), avec une rétention bornée (`RETENTION_MAX_JOURS`) ; l'utilisateur peut le retirer.
  Le journal d'événements ne garde jamais le texte : la longueur de la parole de l'utilisateur, la longueur et
  l'empreinte de celle de l'avatar.
- BIOMÉTRIE : aucune identification du locuteur par empreinte vocale (LCCJTI art. 44-45) ; l'ouvrir est refusé.
- LIMITES : durée maximale, tours, actions, sessions simultanées et par jour (`GestionnaireSessions`).
- TRANSFERT À UN HUMAIN : demandable à tout moment tant que la session n'est pas finie ; ensuite l'avatar se tait.
"""

from __future__ import annotations

import dataclasses
import enum
import hashlib
import json
import math
import re
import secrets
from collections.abc import Callable, Mapping
from typing import Any, Protocol

from ..avatars import IdentiteEffective
from ..outils import Niveau
from .codes import AvatarRefus

# -- états et événements -------------------------------------------------------------------------------------------


class Etat(enum.StrEnum):
    OUVERTE = "ouverte"
    TOUR_UTILISATEUR = "tour_utilisateur"
    TOUR_AVATAR = "tour_avatar"
    INTERRUPTION = "interruption"
    TRANSFERT_HUMAIN = "transfert_humain"
    FIN = "fin"


class Evenement(enum.StrEnum):
    DIVULGUER = "divulguer"
    FIN_PAROLE_AVATAR = "fin_parole_avatar"
    PAROLE_AVATAR = "parole_avatar"
    PAROLE_UTILISATEUR = "parole_utilisateur"
    INTERROMPRE = "interrompre"
    DEMANDER_ACTION = "demander_action"
    CONSENTIR_ENREGISTREMENT = "consentir_enregistrement"
    RETIRER_ENREGISTREMENT = "retirer_enregistrement"
    TRANSFERT_HUMAIN = "transfert_humain"
    TERMINER = "terminer"


E, V = Etat, Evenement
_NON_TERMINAUX = (E.OUVERTE, E.TOUR_UTILISATEUR, E.TOUR_AVATAR, E.INTERRUPTION)
# Table des transitions LÉGALES : tout couple absent est refusé (REJ-VOIX-TRANSITION-ILLEGALE).
TRANSITIONS: Mapping[tuple[Etat, Evenement], Etat] = {
    (E.OUVERTE, V.DIVULGUER): E.TOUR_AVATAR,
    (E.TOUR_AVATAR, V.FIN_PAROLE_AVATAR): E.TOUR_UTILISATEUR,
    (E.TOUR_AVATAR, V.INTERROMPRE): E.INTERRUPTION,
    (E.INTERRUPTION, V.PAROLE_UTILISATEUR): E.TOUR_UTILISATEUR,
    (E.TOUR_UTILISATEUR, V.PAROLE_UTILISATEUR): E.TOUR_UTILISATEUR,
    (E.TOUR_UTILISATEUR, V.DIVULGUER): E.TOUR_AVATAR,  # seulement si la divulgation n'a pas été livrée
    (E.TOUR_UTILISATEUR, V.PAROLE_AVATAR): E.TOUR_AVATAR,
    (E.TOUR_UTILISATEUR, V.DEMANDER_ACTION): E.TOUR_UTILISATEUR,
    (E.TOUR_UTILISATEUR, V.CONSENTIR_ENREGISTREMENT): E.TOUR_UTILISATEUR,
    (E.TOUR_UTILISATEUR, V.RETIRER_ENREGISTREMENT): E.TOUR_UTILISATEUR,
    **{(etat, V.TRANSFERT_HUMAIN): E.TRANSFERT_HUMAIN for etat in _NON_TERMINAUX},
    **{(etat, V.TERMINER): E.FIN for etat in (*_NON_TERMINAUX, E.TRANSFERT_HUMAIN)},
}

ORDRES: Mapping[Evenement, tuple[str, ...]] = {
    V.DIVULGUER: ("jouer_divulgation",),
    V.PAROLE_AVATAR: ("synthetiser",),
    V.FIN_PAROLE_AVATAR: ("ecouter",),
    V.INTERROMPRE: ("couper_tts", "vider_tampon_audio", "figer_visemes", "ecouter"),
    V.TRANSFERT_HUMAIN: ("couper_tts", "vider_tampon_audio", "figer_visemes", "transferer_vers_humain"),
    V.TERMINER: ("couper_tts", "vider_tampon_audio", "fermer_salle"),
}

GENRES_PAROLE = ("reponse", "proposition", "annonce")
PORTEES_ENREGISTREMENT = ("audio", "transcription")
TEXTE_MAX = 4000
RETENTION_DEFAUT_JOURS = 30
RETENTION_MAX_JOURS = 90
DUREE_MAX_ABSOLUE_S = 3600
_MESSAGE_ATTENTE = ("J'ai transmis la demande : elle doit être approuvée par une personne autorisée. Rien n'est "
                    "exécuté pour l'instant.")
NIVEAU_SAS = Niveau.N3  # à partir de N3, jamais d'exécution sur la seule parole
_RANG = {niveau: rang for rang, niveau in enumerate(Niveau)}

# Affirmation qu'une action est faite (heuristique de COMPLÉMENT : la garde est que rien n'est exécuté sans décision).
_VERBES = (r"envoy[ée]|pay[ée]|vir[ée]|transf[ée]r[ée]|publi[ée]|sign[ée]|supprim[ée]|approuv[ée]|ex[ée]cut[ée]"
           r"|effectu[ée]|r[ée]gl[ée]|annul[ée]|enregistr[ée]")
_AFFIRMATION = re.compile(
    rf"(c['’]est\s+(?:d[ée]j[àa]\s+)?(?:fait|{_VERBES})"
    rf"|\b(?:j['’]ai|je\s+viens\s+de|nous\s+avons|on\s+a)\s+(?:d[ée]j[àa]\s+)?(?:{_VERBES}|fait)"
    rf"|\b(?:est|sont|a\s+[ée]t[ée]|ont\s+[ée]t[ée])\s+(?:maintenant\s+|bien\s+|d[ée]j[àa]\s+)?(?:{_VERBES})(?:e|s|es)?\b)",
    re.IGNORECASE)


def texte_divulgation(nom_avatar: str, nom_entreprise: str) -> str:
    """Texte CANONIQUE de l'ouverture : l'avatar est un assistant virtuel (une IA), l'enregistrement est désactivé
    sauf consentement, un humain reste joignable. Produit ici, jamais par un modèle de langage."""
    return (f"Bonjour, ici {nom_avatar}, un assistant virtuel de {nom_entreprise}. Je suis une intelligence "
            "artificielle, pas une personne. Cette conversation n'est pas enregistrée à moins que vous n'y "
            "consentiez. Vous pouvez demander à parler à une personne en tout temps.")


# -- paramètres, ports, résultats ------------------------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class ParametresSession:
    duree_max_s: int = 900
    tours_max: int = 200
    actions_max: int = 3

    def __post_init__(self) -> None:
        def entier(valeur: Any, bas: int, haut: int) -> bool:
            return type(valeur) is int and bas <= valeur <= haut

        if not (entier(self.duree_max_s, 30, DUREE_MAX_ABSOLUE_S) and entier(self.tours_max, 1, 500)
                and entier(self.actions_max, 0, 20)):
            raise AvatarRefus(
                "REJ-VOIX-PARAMETRES-INVALIDES",
                f"duree_max_s 30 à {DUREE_MAX_ABSOLUE_S}, tours_max 1 à 500, actions_max 0 à 20 (entiers)", 422)


@dataclasses.dataclass(frozen=True)
class LimitesVoix:
    simultanees_par_departement: int = 2
    simultanees_total: int = 10
    sessions_par_jour_par_departement: int = 200

    def __post_init__(self) -> None:
        if not all(type(v) is int and v >= 1 for v in dataclasses.astuple(self)):
            raise AvatarRefus("REJ-VOIX-PARAMETRES-INVALIDES", "les limites sont des entiers positifs", 422)


@dataclasses.dataclass(frozen=True)
class DescriptionOutil:
    niveau: Niveau
    dans_perimetre: bool


class PortActions(Protocol):
    """Ce que la session sait faire d'une action demandée. L'adaptateur réel (`actions.PortCapacites`) s'appuie sur le
    registre d'outils et le sas d'approbation du socle ; les tests en injectent un autre."""

    def decrire(self, departement: str, outil: str) -> DescriptionOutil | None: ...

    def verifier_arguments(self, departement: str, outil: str, arguments: Mapping[str, Any]) -> list[str]: ...

    def executer_autonome(self, departement: str, outil: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]: ...

    def mettre_en_attente(self, departement: str, outil: str, arguments: Mapping[str, Any], motif: str) -> str: ...


@dataclasses.dataclass(frozen=True)
class Transition:
    evenement: str
    avant: str
    apres: str
    ordres: tuple[str, ...]


@dataclasses.dataclass(frozen=True)
class EvenementSession:
    rang: int
    t: float
    type: str
    avant: str
    apres: str
    detail: Mapping[str, Any]


@dataclasses.dataclass(frozen=True)
class DecisionAction:
    """Issue d'une action demandée à voix. `message_avatar` est ce que l'avatar peut dire : jamais « c'est fait »
    pour une action en attente."""

    statut: str  # execute | en_attente_approbation | refuse
    outil: str
    niveau: str
    demande_id: str | None
    message_avatar: str

    def vers_json(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def _empreinte(valeur: Any) -> str:
    return hashlib.sha256(json.dumps(valeur, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _texte(valeur: Any) -> str:
    if not isinstance(valeur, str) or not valeur.strip() or len(valeur) > TEXTE_MAX:
        raise AvatarRefus("REJ-VOIX-TEXTE-INVALIDE", f"texte non vide de {TEXTE_MAX} caractères au plus attendu", 422)
    return valeur


class SessionVoix:
    """Une session voix. Les méthodes publiques sont les seuls événements ; chacune rend une `Transition`
    (ou une `DecisionAction`) ou lève `AvatarRefus` sans rien changer."""

    def __init__(self, *, session_id: str, departement: str, avatar: str, canal: str, entreprise: str, t: float,
                 parametres: ParametresSession, port: PortActions) -> None:
        self.session_id = session_id
        self.departement = departement
        self.avatar = avatar
        self.canal = canal
        self.parametres = parametres
        self._port = port
        self._entreprise = entreprise
        self._t0 = t
        self._dernier_t = t
        self.etat: Etat = Etat.OUVERTE
        self.raison_fin: str | None = None
        self.divulgation_livree = False
        self._tour_divulgation = False
        self._tours = 0
        self.actions: list[dict[str, Any]] = []
        self.evenements: list[EvenementSession] = []
        self._enregistrement: dict[str, Any] = {"actif": False, "retention_jours": None, "portee": (),
                                                "purge_demandee": False}

    # -- lecture ------------------------------------------------------------------------------------------------
    @property
    def termine(self) -> bool:
        return self.etat is Etat.FIN

    @property
    def tours(self) -> int:
        return self._tours

    def conservation(self) -> dict[str, Any]:
        """Ce que le worker a le droit de conserver : RIEN, sauf consentement explicite, et pour une durée bornée."""
        e = self._enregistrement
        return {"audio": e["actif"] and "audio" in e["portee"],
                "transcription": e["actif"] and "transcription" in e["portee"],
                "retention_jours": e["retention_jours"] if e["actif"] else None, "purge_demandee": e["purge_demandee"]}

    def vers_json(self) -> dict[str, Any]:
        return {"session_id": self.session_id, "departement": self.departement, "avatar": self.avatar,
                "canal": self.canal, "etat": self.etat.value, "divulgation_livree": self.divulgation_livree,
                "tours": self._tours, "actions": list(self.actions), "conservation": self.conservation(),
                "raison_fin": self.raison_fin, "evenements": len(self.evenements)}

    # -- noyau --------------------------------------------------------------------------------------------------
    def _verifier_horloge(self, t: Any) -> float:
        if isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) or t < self._dernier_t:
            raise AvatarRefus("REJ-VOIX-HORLOGE-INVALIDE", "t doit être un nombre fini qui ne recule jamais", 422)
        return float(t)

    def _clore(self, t: float, raison: str, detail: Mapping[str, Any] | None = None) -> None:
        self._noter(t, "cloture", self.etat, Etat.FIN, {"raison": raison, **(detail or {})})
        self.etat, self.raison_fin = Etat.FIN, raison

    def _noter(self, t: float, type_: str, avant: Etat, apres: Etat, detail: Mapping[str, Any]) -> None:
        self._dernier_t = t
        self.evenements.append(EvenementSession(len(self.evenements) + 1, t, type_, avant.value, apres.value,
                                                dict(detail)))

    def _ouvrir_evenement(self, evenement: Evenement, t: Any) -> tuple[float, Etat]:
        """Garde commune : session non finie, horloge, durée maximale, transition légale. Ne change rien."""
        if self.etat is Etat.FIN:
            raise AvatarRefus("REJ-VOIX-SESSION-TERMINEE", "la session est terminée : aucun événement n'est accepté",
                              409)
        instant = self._verifier_horloge(t)
        if evenement is not Evenement.TERMINER and instant - self._t0 > self.parametres.duree_max_s:
            self._clore(instant, "duree_max")
            raise AvatarRefus("REJ-VOIX-DUREE-MAX", f"durée maximale de {self.parametres.duree_max_s} s dépassée : "
                              "la session est terminée", 409)
        suivant = TRANSITIONS.get((self.etat, evenement))
        if suivant is None:
            raise AvatarRefus("REJ-VOIX-TRANSITION-ILLEGALE",
                              f"« {evenement.value} » est illégal dans l'état « {self.etat.value} »", 409)
        return instant, suivant

    def _valider(self, evenement: Evenement, instant: float, suivant: Etat, detail: Mapping[str, Any]) -> Transition:
        avant = self.etat
        self._noter(instant, evenement.value, avant, suivant, detail)
        self.etat = suivant
        return Transition(evenement.value, avant.value, suivant.value, ORDRES.get(evenement, ()))

    def _exiger_divulgation(self) -> None:
        if not self.divulgation_livree:
            raise AvatarRefus("REJ-VOIX-DIVULGATION-REQUISE",
                              "l'avatar doit d'abord livrer la divulgation « assistant virtuel » jusqu'au bout", 409)

    def _compter_tour(self, instant: float) -> None:
        if self._tours >= self.parametres.tours_max:
            self._clore(instant, "quota_tours")
            raise AvatarRefus("REJ-VOIX-QUOTA-TOURS", f"{self.parametres.tours_max} tours de l'avatar atteints : "
                              "la session est terminée", 409)
        self._tours += 1

    # -- événements ---------------------------------------------------------------------------------------------
    def divulguer(self, t: float) -> tuple[Transition, str]:
        """L'avatar livre la divulgation canonique (premier acte obligatoire). Rend aussi le texte à synthétiser."""
        instant, suivant = self._ouvrir_evenement(Evenement.DIVULGUER, t)
        if self.divulgation_livree:
            raise AvatarRefus("REJ-VOIX-TRANSITION-ILLEGALE", "la divulgation a déjà été livrée", 409)
        self._compter_tour(instant)
        self._tour_divulgation = True
        return (self._valider(Evenement.DIVULGUER, instant, suivant, {"divulgation": True}),
                texte_divulgation(self.avatar, self._entreprise))

    def parole_avatar(self, t: float, texte: str, genre: str = "reponse") -> Transition:
        """L'avatar prend la parole (réponse, proposition, annonce). Refusé tant que la divulgation n'est pas
        livrée, et refusé s'il affirme qu'une action est faite alors qu'elle est en attente ou refusée."""
        instant, suivant = self._ouvrir_evenement(Evenement.PAROLE_AVATAR, t)
        self._exiger_divulgation()
        if genre not in GENRES_PAROLE:
            raise AvatarRefus("REJ-VOIX-TEXTE-INVALIDE", f"genre de parole parmi {', '.join(GENRES_PAROLE)}", 422)
        _texte(texte)
        if any(a["statut"] != "execute" for a in self.actions) and _AFFIRMATION.search(texte):
            raise AvatarRefus("REJ-VOIX-AFFIRMATION-NON-FONDEE",
                              "l'avatar ne peut pas présenter comme faite une action en attente d'approbation ou "
                              "refusée", 409)
        self._compter_tour(instant)
        self._tour_divulgation = False
        return self._valider(Evenement.PAROLE_AVATAR, instant, suivant,
                             {"genre": genre, "sha256": _empreinte(texte), "caracteres": len(texte)})

    def fin_parole_avatar(self, t: float) -> Transition:
        """Le tour de l'avatar s'est terminé sans interruption ; une divulgation menée à terme est livrée."""
        instant, suivant = self._ouvrir_evenement(Evenement.FIN_PAROLE_AVATAR, t)
        if self._tour_divulgation:
            self.divulgation_livree = True
            self._tour_divulgation = False
        return self._valider(Evenement.FIN_PAROLE_AVATAR, instant, suivant, {})

    def interrompre(self, t: float) -> Transition:
        """Barge-in : l'utilisateur parle pendant le tour de l'avatar. Une divulgation interrompue est à refaire."""
        instant, suivant = self._ouvrir_evenement(Evenement.INTERROMPRE, t)
        annulee = self._tour_divulgation
        self._tour_divulgation = False
        return self._valider(Evenement.INTERROMPRE, instant, suivant, {"divulgation_annulee": annulee})

    def parole_utilisateur(self, t: float, texte: str) -> Transition:
        """Transcription de l'utilisateur : une DONNÉE. Elle ne change que le tour de parole ; le journal n'en garde que
        la longueur."""
        instant, suivant = self._ouvrir_evenement(Evenement.PAROLE_UTILISATEUR, t)
        _texte(texte)
        return self._valider(Evenement.PAROLE_UTILISATEUR, instant, suivant, {"caracteres": len(texte)})

    def consentir_enregistrement(self, t: float, retention_jours: int = RETENTION_DEFAUT_JOURS,
                                 portee: tuple[str, ...] = ("audio",)) -> Transition:
        """Consentement EXPLICITE de l'utilisateur à l'enregistrement, après la divulgation. Rétention bornée. Jamais
        déduit d'une transcription : seul le worker, sur la réponse explicite de la personne, appelle ceci."""
        instant, suivant = self._ouvrir_evenement(Evenement.CONSENTIR_ENREGISTREMENT, t)
        self._exiger_divulgation()
        if self._enregistrement["actif"]:
            raise AvatarRefus("REJ-VOIX-TRANSITION-ILLEGALE", "l'enregistrement est déjà consenti", 409)
        if type(retention_jours) is not int or not 1 <= retention_jours <= RETENTION_MAX_JOURS:
            raise AvatarRefus("REJ-VOIX-RETENTION-INVALIDE",
                              f"rétention de 1 à {RETENTION_MAX_JOURS} jours (entier)", 422)
        if (not isinstance(portee, (tuple, list)) or not portee
                or any(not isinstance(p, str) or p not in PORTEES_ENREGISTREMENT for p in portee)):
            raise AvatarRefus("REJ-VOIX-ENREGISTREMENT-NON-CONSENTI",
                              f"portée de l'enregistrement parmi {', '.join(PORTEES_ENREGISTREMENT)}", 422)
        elements = tuple(sorted(set(portee)))
        self._enregistrement = {"actif": True, "retention_jours": retention_jours, "portee": elements,
                                "purge_demandee": False}
        return self._valider(Evenement.CONSENTIR_ENREGISTREMENT, instant, suivant,
                             {"retention_jours": retention_jours, "portee": list(elements)})

    def retirer_enregistrement(self, t: float) -> Transition:
        """L'utilisateur retire son consentement : l'enregistrement s'arrête et la purge de ce qui a été gardé
        est demandée."""
        instant, suivant = self._ouvrir_evenement(Evenement.RETIRER_ENREGISTREMENT, t)
        if not self._enregistrement["actif"]:
            raise AvatarRefus("REJ-VOIX-ENREGISTREMENT-NON-CONSENTI", "aucun enregistrement n'est consenti", 409)
        self._enregistrement = {"actif": False, "retention_jours": None, "portee": (), "purge_demandee": True}
        return self._valider(Evenement.RETIRER_ENREGISTREMENT, instant, suivant, {})

    def demander_action(self, t: float, outil: str, arguments: Mapping[str, Any]) -> DecisionAction:
        """Une action demandée à voix (l'appel d'outil que le modèle émet d'après la parole). N0 à N2 : exécutée par le
        registre d'outils sous sa propre gouvernance ; N3 et plus : mise dans le sas d'approbation, JAMAIS exécutée
        ici. Le niveau vient du registre d'outils, pas du texte. Le résultat dit quoi annoncer."""
        instant, suivant = self._ouvrir_evenement(Evenement.DEMANDER_ACTION, t)
        self._exiger_divulgation()
        if not isinstance(outil, str) or not isinstance(arguments, Mapping):
            raise AvatarRefus("REJ-VOIX-ACTION-ARGUMENTS-INVALIDES", "outil (texte) et arguments (objet) attendus", 422)
        empreinte_arguments = _empreinte(dict(arguments))
        deja = next((a for a in self.actions if a["outil"] == outil and a["arguments_sha256"] == empreinte_arguments
                     and a["statut"] == "en_attente_approbation"), None)
        if deja is not None:
            # Double soumission (« vire 5000 $ » dit deux fois) : la demande en attente est rappelée, pas dupliquée.
            self._valider(Evenement.DEMANDER_ACTION, instant, suivant, {"outil": outil, "repetee": True})
            return DecisionAction("en_attente_approbation", outil, deja["niveau"], deja["demande_id"],
                                  _MESSAGE_ATTENTE)
        if len(self.actions) >= self.parametres.actions_max:
            raise AvatarRefus("REJ-VOIX-QUOTA-ACTIONS",
                              f"{self.parametres.actions_max} actions par session atteintes", 409)
        description = self._port.decrire(self.departement, outil)
        if description is None:
            raise AvatarRefus("REJ-VOIX-ACTION-INCONNUE", "outil inconnu du registre", 404)
        if not description.dans_perimetre:
            raise AvatarRefus("REJ-VOIX-ACTION-HORS-PERIMETRE",
                              f"{outil} n'est pas dans la portée du département {self.departement}", 403)
        erreurs = self._port.verifier_arguments(self.departement, outil, arguments)
        if erreurs:
            raise AvatarRefus("REJ-VOIX-ACTION-ARGUMENTS-INVALIDES", "; ".join(erreurs)[:300], 422)
        niveau = description.niveau
        if _RANG[niveau] >= _RANG[NIVEAU_SAS]:
            demande = self._port.mettre_en_attente(
                self.departement, outil, arguments,
                f"Demandé à voix (session {self.session_id}, avatar {self.avatar}) : décision humaine requise ; "
                "rien n'est exécuté sur la seule parole.")
            if not isinstance(demande, str) or not demande:
                raise AvatarRefus("REJ-VOIX-AUTORITE-CONTOURNEE",
                                  "le sas d'approbation n'a pas confirmé la mise en attente : action non annoncée", 500)
            decision = DecisionAction("en_attente_approbation", outil, niveau.value, demande, _MESSAGE_ATTENTE)
        else:
            reponse = self._port.executer_autonome(self.departement, outil, arguments)
            if reponse.get("statut") == "en_attente_approbation":  # le registre a lui-même exigé une décision
                decision = DecisionAction("en_attente_approbation", outil, niveau.value, reponse.get("demande_id"),
                                          _MESSAGE_ATTENTE)
            else:
                ok = bool(reponse.get("ok"))
                decision = DecisionAction(
                    "execute" if ok else "refuse", outil, niveau.value, None,
                    "C'est fait." if ok else "Je n'ai pas pu faire cette action ; une personne peut la reprendre.")
        self.actions.append({"outil": outil, "niveau": decision.niveau, "statut": decision.statut,
                             "demande_id": decision.demande_id, "arguments_sha256": empreinte_arguments})
        self._valider(Evenement.DEMANDER_ACTION, instant, suivant,
                      {"outil": outil, "niveau": decision.niveau, "statut": decision.statut})
        return decision

    def transferer_humain(self, t: float, raison: str = "demande_utilisateur") -> Transition:
        """Passe la main à une personne ; l'avatar se tait ensuite. Légal à tout moment avant la fin."""
        instant, suivant = self._ouvrir_evenement(Evenement.TRANSFERT_HUMAIN, t)
        self._tour_divulgation = False
        return self._valider(Evenement.TRANSFERT_HUMAIN, instant, suivant, {"raison": str(raison)[:60]})

    def terminer(self, t: float, raison: str = "fin_normale") -> Transition:
        instant, suivant = self._ouvrir_evenement(Evenement.TERMINER, t)
        transition = self._valider(Evenement.TERMINER, instant, suivant, {"raison": str(raison)[:60]})
        self.raison_fin = str(raison)[:60]
        return transition


# -- gestionnaire (quotas) -----------------------------------------------------------------------------------------


class GestionnaireSessions:
    """Ouvre les sessions voix et applique les quotas. Le canal du département doit être « disponible » au sens de la
    politique (`verifier_canal`, un `politique.Verdict`) : tant qu'aucun runtime n'est livré, aucune session ne s'ouvre.
    En mémoire seulement : la persistance viendra avec le gateway."""

    def __init__(self, *, verifier_canal: Callable[[str, str], Any], port: PortActions, nom_entreprise: str,
                 limites: LimitesVoix | None = None) -> None:
        if (not isinstance(nom_entreprise, str) or not 1 <= len(nom_entreprise) <= 80
                or not nom_entreprise.isprintable()):
            raise AvatarRefus("REJ-VOIX-PARAMETRES-INVALIDES",
                              "nom d'entreprise : texte imprimable de 1 à 80 caractères", 422)
        self._verifier_canal = verifier_canal
        self._port = port
        self._entreprise = nom_entreprise
        self.limites = limites or LimitesVoix()
        self._sessions: dict[str, SessionVoix] = {}
        self._par_jour: dict[tuple[str, str], int] = {}

    def ouvertes(self, departement: str | None = None) -> list[SessionVoix]:
        return [s for s in self._sessions.values()
                if not s.termine and (departement is None or s.departement == departement)]

    def ouvrir(self, identite: IdentiteEffective, *, canal: str = "voix", t: float, jour: str,
               parametres: ParametresSession | None = None, identification_locuteur: bool = False) -> SessionVoix:
        if identification_locuteur:
            raise AvatarRefus("REJ-VOIX-BIOMETRIE-INTERDITE",
                              "l'identification du locuteur par empreinte vocale est interdite (biométrie, Loi 25 : "
                              "consentement exprès et déclaration à la CAI requis)", 403)
        if not isinstance(jour, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", jour):
            raise AvatarRefus("REJ-VOIX-PARAMETRES-INVALIDES", "jour AAAA-MM-JJ attendu", 422)
        verdict = self._verifier_canal(identite.departement, canal)
        if not verdict.conforme:
            raise AvatarRefus("REJ-VOIX-CANAL-NON-DISPONIBLE",
                              f"le canal « {canal} » de {identite.departement} n'est pas disponible",
                              409, verdict.codes or ("REJ-VOIX-CANAL-NON-DISPONIBLE",))
        if len(self.ouvertes(identite.departement)) >= self.limites.simultanees_par_departement:
            raise AvatarRefus("REJ-VOIX-QUOTA-SIMULTANE", "sessions simultanées du département atteintes", 429)
        if len(self.ouvertes()) >= self.limites.simultanees_total:
            raise AvatarRefus("REJ-VOIX-QUOTA-SIMULTANE", "sessions simultanées de l'instance atteintes", 429)
        cle = (identite.departement, jour)
        if self._par_jour.get(cle, 0) >= self.limites.sessions_par_jour_par_departement:
            raise AvatarRefus("REJ-VOIX-QUOTA-JOUR", "sessions du jour atteintes pour ce département", 429)
        session = SessionVoix(
            session_id=secrets.token_hex(8), departement=identite.departement, avatar=identite.nom, canal=canal,
            entreprise=self._entreprise, t=t, parametres=parametres or ParametresSession(), port=self._port)
        self._par_jour[cle] = self._par_jour.get(cle, 0) + 1
        self._sessions[session.session_id] = session
        return session

    def session(self, session_id: str) -> SessionVoix | None:
        return self._sessions.get(session_id)

    def reverifier(self, t: float) -> list[str]:
        """À appeler quand un consentement est révoqué ou un moteur modifié : termine les sessions dont le canal n'est
        plus conforme. Rend les identifiants fermés."""
        fermees = []
        for session in self.ouvertes():
            if not self._verifier_canal(session.departement, session.canal).conforme:
                instant = max(t, session._dernier_t)
                if session.etat is not Etat.TRANSFERT_HUMAIN:
                    session.transferer_humain(instant, "canal_suspendu")
                session.terminer(instant, "canal_suspendu")
                fermees.append(session.session_id)
        return fermees
