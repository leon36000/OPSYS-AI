"""Bac à sable VOCAL TEXTUEL de M1 (M1.19, mode 2 « bac à sable (faux clients) » de la montée en charge de la voix).

CE MODULE NE PROUVE QUE LA POLITIQUE DE DIALOGUE, PAS LA VOIX. Un « faux appel » y est une suite de tours de TEXTE
écrits d'avance (une transcription, une confiance de transcription déjà mesurée, un instant en secondes) : aucun audio,
aucune détection de parole, aucune transcription, aucune synthèse vocale, aucune ligne téléphonique, aucun fournisseur.
Le
canal vocal n'est pas déclaré disponible par ce module (`avatars.CANAUX_REALISES` reste `{messagerie}`) et la matrice
d'exigences M1.2 / M1.19 ne passe pas à FAIT_PROUVE : ce qu'on y apprend, c'est si les RÈGLES de dialogue tiennent
(jamais
un prix, une date, un engagement, un aveu ni un avis légal ; redemander sur faible confiance ; repli sur échecs répétés,
colère, danger, sujet légal ou financier ; messagerie quand personne n'est disponible), avant qu'un moteur vocal ne les
appelle. Latence, accent fr-CA, bruit, interruptions réelles, qualité de la voix : rien de cela n'est mesuré ici.

Ce que le harnais assemble, tout de l'existant, sans rien réinventer :

- la machine d'états d'une session voix du socle (`opsys.avatars_voix.session.SessionVoix` : divulgation « assistant
  virtuel » d'abord, interruption/barge-in, transfert à une personne, durée et quotas) ;
- la politique de dialogue (`politique_dialogue.py`, règles pures) ;
- le garde-fou de sortie de M1 (`garde_fou.verifier_sortie`) sur CHAQUE parole de l'avatar produite par le répondant ;
- la qualification, les plaintes, les transferts avec résumé et le registre anti-perte de M1 (`outils._traiter`), tels
  qu'une transcription de messagerie vocale les traverse.

Déterminisme : aucune horloge système (l'instant de chaque tour vient du script, l'horloge est injectée), aucun hasard,
aucun réseau. Le répondant (ce qui parle quand la politique laisse parler) est un PORT : le double déterministe livré
ici ne
dit que des phrases fixes tirées du profil de l'instance ; un modèle réel ne s'y branche qu'en essai opt-in, jamais
requis, et son texte passe par le même garde-fou.

Sécurité : le harnais écrit au registre de M1. Il REFUSE de tourner sur le registre de production (`REJ-BAC-A-SABLE-
PRODUCTION`) sauf demande explicite d'un test qui a monté sa propre base : un faux appel ne doit jamais devenir un vrai
lead.
Sans consentement `accorde`, la parole de l'appelant n'est pas écrite au registre (même règle qu'un message vocal).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Protocol

from opsys import taxonomie
from opsys.avatars_voix import session as voix
from opsys.avatars_voix.codes import AvatarRefus
from opsys.taxonomie import QuestionQualification

from . import garde_fou, outils, politique_dialogue, qualification, questions, reception, transferts
from . import horodatage as controle_horodatage
from .politique_dialogue import Action, Decision, EtatDialogue, Motif, SeuilsDialogue

PORTEE = politique_dialogue.PORTEE
SOURCE_LEAD = "bac_a_sable_voix"
CANAL_CONTRAT = "telephone"
DEPARTEMENT = "m01-front-office"

ISSUE_LEAD = "lead_cree"
ISSUE_RAPPEL = "rappel_cree"            # demande incomplète : une tâche humaine, rien n'est perdu
ISSUE_TRANSFERT = "transfert_humain"
ISSUE_MESSAGERIE = "messagerie"

CONSIGNE_PLACEHOLDER = "Appel reçu; contenu non conservé faute de consentement explicite."
AUCUNE_PAROLE = "Appel reçu; aucune demande comprise, rappel à faire."


class RefusBacASable(ValueError):
    """Refus typé du harnais (`REJ-BAC-A-SABLE-…`) : le détail dit quoi corriger. Rien n'est écrit."""

    def __init__(self, code: str, detail: str) -> None:
        self.code, self.detail = code, detail
        super().__init__(f"{code}: {detail}")


# ================================================================================================ horloge injectée
class HorlogeSimulee:
    """Secondes écoulées depuis le début du faux appel. Aucune horloge système : le script et le harnais l'avancent."""

    def __init__(self, depart: float = 0.0) -> None:
        self.t = float(depart)

    def maintenant(self) -> float:
        return self.t

    def avancer_a(self, t: float) -> float:
        if t < self.t:
            raise RefusBacASable("REJ-BAC-A-SABLE-HORLOGE", f"le temps ne recule pas ({t} < {self.t})")
        self.t = float(t)
        return self.t


# ================================================================================================ le script
@dataclass(frozen=True)
class TourAppelant:
    """Un tour de l'appelant. `texte=None` : silence. `confiance` : celle du moteur de transcription (0 à 1) ;
    absente, elle est traitée comme faible. `interrompt` : l'appelant parle PENDANT la parole de l'avatar (barge-in)."""

    t: float
    texte: str | None
    confiance: float | None = None
    interrompt: bool = False


@dataclass(frozen=True)
class AppelScript:
    appel_id: str
    telephone: str                       # E.164, FICTIF (555) : le numéro que la plateforme aurait donné
    debut: str                           # ISO 8601 avec fuseau : l'heure de l'appel (datation du registre)
    tours: tuple[TourAppelant, ...]
    humain_disponible: bool = True
    consentement_enregistrement: str | None = None   # seul « accorde » écrit la parole au registre


@dataclass(frozen=True)
class ParametresBac:
    """Ce que le harnais exige de l'appelant du test (aucune valeur par défaut inventée)."""

    seuils: SeuilsDialogue
    questions_max: int                   # combien de questions du profil le répondant pose au plus dans un appel
    latence_reponse_s: float             # délai SIMULÉ entre la fin d'un tour de l'appelant et la parole de l'avatar
    nom_avatar: str
    nom_entreprise: str
    autoriser_registre_durable: bool = False


# ================================================================================================ le répondant (port)
@dataclass(frozen=True)
class ContexteRepondant:
    """Ce que le répondant voit : uniquement des tours COMPRIS, jamais le texte brut d'un tour de faible confiance."""

    paroles_comprises: tuple[str, ...]
    service: str | None
    ville: str | None
    libelles_services: Mapping[str, str]
    questions_restantes: tuple[QuestionQualification, ...]
    questions_posees: int
    questions_max: int


@dataclass(frozen=True)
class Reponse:
    """Ce que dit le répondant. `texte=None` : il n'a pas compris (un échec de compréhension de plus). `fin=True` :
    c'est sa
    dernière phrase, l'appel se termine après elle."""

    texte: str | None
    fin: bool = False


class Repondant(Protocol):
    """Ce qui parle quand la politique laisse parler. Son texte est TOUJOURS passé par le garde-fou avant d'être dit."""

    def repondre(self, contexte: ContexteRepondant) -> Reponse: ...


class RepondantDeterministe:
    """Double déterministe : demande le service, puis la ville, puis les questions du profil de l'instance (dans l'ordre
    écrit, au plus `questions_max`), puis clôt. Il ne dit que des phrases fixes ou tirées du PROFIL : jamais de prix,
    de date ni de promesse. Sans question déclarée dans le profil, il ne pose que service et ville : rien n'est
    inventé."""

    def repondre(self, contexte: ContexteRepondant) -> Reponse:
        if contexte.service is None:
            libelles = list(contexte.libelles_services.values())
            question = "Quel service vous intéresse (" + ", ".join(libelles) + ")?" if libelles else "Quel service?"
            return Reponse(question)
        if contexte.ville is None:
            return Reponse("Dans quelle ville se trouve la propriété?")
        if contexte.questions_posees < contexte.questions_max and contexte.questions_restantes:
            return Reponse(contexte.questions_restantes[0].question)
        return Reponse("Merci, j'ai noté votre demande. Elle est transmise à l'équipe.", fin=True)


class _PortSansAction:
    """Le bac à sable n'a aucun outil : toute action demandée à voix serait refusée (outil inconnu)."""

    def decrire(self, departement: str, outil: str):
        return None

    def verifier_arguments(self, departement: str, outil: str, arguments: Mapping[str, Any]) -> list[str]:
        return ["aucune action dans le bac à sable"]

    def executer_autonome(self, departement: str, outil: str, arguments: Mapping[str, Any]) -> Mapping[str, Any]:
        raise RefusBacASable("REJ-BAC-A-SABLE-ACTION", "aucune action n'est exécutable dans le bac à sable")

    def mettre_en_attente(self, departement: str, outil: str, arguments: Mapping[str, Any], motif: str) -> str:
        raise RefusBacASable("REJ-BAC-A-SABLE-ACTION", "aucune action n'est exécutable dans le bac à sable")


# ================================================================================================ le rapport
@dataclass
class ParoleRapportee:
    qui: str                  # "appelant" | "avatar"
    t: float
    texte: str | None         # None : texte de l'appelant non conservé (pas de consentement)
    caracteres: int
    nature: str               # appelant : "comprise" | "faible_confiance" | "silence" | "message_laisse"
    #                           avatar : "divulgation" | "politique" | "repondant" | "remplacement_garde_fou"
    confiance: float | None = None


@dataclass
class RapportAppel:
    appel_id: str
    issue: str
    motif: str
    paroles: list[ParoleRapportee] = field(default_factory=list)
    decisions: list[dict[str, Any]] = field(default_factory=list)
    violations_garde_fou: list[dict[str, str]] = field(default_factory=list)
    echecs_comprehension: int = 0
    lead: dict[str, Any] | None = None
    transfert: dict[str, Any] | None = None
    rappel_a_faire: bool = False
    contexte: dict[str, Any] = field(default_factory=dict)
    resume: str = ""
    session: dict[str, Any] = field(default_factory=dict)
    evenements_session: list[str] = field(default_factory=list)   # types seulement, jamais un texte
    latences_simulees_s: list[float] = field(default_factory=list)
    tours_non_joues: int = 0
    portee: str = PORTEE

    def textes_avatar(self) -> list[str]:
        return [p.texte for p in self.paroles if p.qui == "avatar" and p.texte is not None]

    def vers_json(self) -> dict[str, Any]:
        return {
            "appel_id": self.appel_id, "issue": self.issue, "motif": self.motif,
            "paroles": [vars(p) for p in self.paroles], "decisions": self.decisions,
            "violations_garde_fou": self.violations_garde_fou, "echecs_comprehension": self.echecs_comprehension,
            "lead": self.lead, "transfert": self.transfert, "rappel_a_faire": self.rappel_a_faire,
            "contexte": self.contexte, "resume": self.resume, "session": self.session,
            "evenements_session": self.evenements_session,
            "latences_simulees_s": self.latences_simulees_s, "tours_non_joues": self.tours_non_joues,
            "portee": self.portee,
        }


# ================================================================================================ le harnais
def _valider(script: AppelScript, parametres: ParametresBac) -> None:
    if outils._stockage_durable_actif and not parametres.autoriser_registre_durable:
        raise RefusBacASable(
            "REJ-BAC-A-SABLE-PRODUCTION",
            "le registre de M1 est celui de production : un faux appel ne doit pas y écrire (registre en mémoire, ou "
            "`autoriser_registre_durable=True` dans un test qui a monté sa propre base)")
    if not isinstance(script.tours, tuple) or not script.tours:
        raise RefusBacASable("REJ-BAC-A-SABLE-SCRIPT", "au moins un tour de l'appelant est requis")
    try:
        controle_horodatage.valider_horodatage(script.debut)
    except ValueError as exc:
        raise RefusBacASable("REJ-BAC-A-SABLE-SCRIPT", f"debut : {exc}") from exc
    if not isinstance(script.humain_disponible, bool):
        raise RefusBacASable("REJ-BAC-A-SABLE-SCRIPT", "humain_disponible : un booléen est attendu")
    precedent = 0.0
    for tour in script.tours:
        if isinstance(tour.t, bool) or not isinstance(tour.t, (int, float)) or tour.t < precedent:
            raise RefusBacASable("REJ-BAC-A-SABLE-SCRIPT", "les instants des tours croissent (secondes, nombres)")
        precedent = float(tour.t)
        if tour.interrompt and not (isinstance(tour.texte, str) and tour.texte.strip()):
            raise RefusBacASable("REJ-BAC-A-SABLE-SCRIPT", "un barge-in porte une parole : texte requis")
    if isinstance(parametres.questions_max, bool) or not isinstance(parametres.questions_max, int) \
            or parametres.questions_max < 0:
        raise RefusBacASable("REJ-BAC-A-SABLE-SCRIPT", "questions_max : un entier de 0 ou plus")
    if isinstance(parametres.latence_reponse_s, bool) or not 0 <= parametres.latence_reponse_s <= 30:
        raise RefusBacASable("REJ-BAC-A-SABLE-SCRIPT", "latence_reponse_s : de 0 à 30 secondes (valeur SIMULÉE)")


class _Appel:
    """L'état d'UN faux appel, pour que `jouer` reste lisible."""

    def __init__(self, script: AppelScript, parametres: ParametresBac, repondant: Repondant,
                 horloge: HorlogeSimulee) -> None:
        self.script, self.p, self.repondant, self.horloge = script, parametres, repondant, horloge
        self.rapport = RapportAppel(script.appel_id, issue="", motif="")
        self.session = voix.SessionVoix(
            session_id=f"bac-{hashlib.sha256(script.appel_id.encode()).hexdigest()[:12]}",
            departement=DEPARTEMENT, avatar=parametres.nom_avatar, canal="voix", entreprise=parametres.nom_entreprise,
            t=0.0, parametres=voix.ParametresSession(), port=_PortSansAction())
        self.etat = EtatDialogue()
        self.comprises: list[str] = []         # tours COMPRIS : ce que le répondant voit
        # ce qui entre au registre (avec consentement) : tours compris, déclencheur d'une tâche, message laissé
        self.enregistrables: list[str] = []
        self.questions_posees: set[str] = set()
        self.messagerie: Decision | None = None
        self.cloture = False                   # le répondant a dit sa dernière phrase
        self.decision_finale: Decision | None = None
        self.consentement = script.consentement_enregistrement == "accorde"
        self._consenti = False
        services, verdict_services = taxonomie.charger_services()
        zone, verdict_zone = taxonomie.charger_zone_desservie()
        if verdict_services is not None or verdict_zone is not None:
            verdict = verdict_services or verdict_zone
            raise RefusBacASable("REJ-BAC-A-SABLE-PROFIL", f"{verdict['code']}: {verdict['detail']}")
        self.services, self.zone = services, list(zone)
        self.signaux, self.verdict_signaux = taxonomie.charger_signaux_plainte()

    # -- parole de l'avatar --------------------------------------------------------------------------------------
    def _dire(self, texte: str, nature: str) -> None:
        """L'avatar parle. La divulgation d'abord si elle n'a pas été livrée jusqu'au bout (une interruption l'annule) ;
        une parole précédente non interrompue est finie avant la suivante."""
        if not self.session.divulgation_livree and self.session.etat is not voix.Etat.TOUR_AVATAR:
            self._divulguer()
        if self.session.etat is voix.Etat.TOUR_AVATAR:
            self.session.fin_parole_avatar(self.horloge.maintenant())
        self._appliquer_consentement()
        self.session.parole_avatar(self.horloge.maintenant(), texte)
        self.rapport.paroles.append(ParoleRapportee("avatar", self.horloge.maintenant(), texte, len(texte), nature))

    def _appliquer_consentement(self) -> None:
        """Le consentement que le script déclare (collecté APRÈS la divulgation, avant toute parole de fond) entre dans
        la
        session du socle : sans lui, elle ne conserve rien. Applicable seulement entre deux tours, divulgation
        livrée."""
        if (self.consentement and not self._consenti and self.session.divulgation_livree
                and self.session.etat is voix.Etat.TOUR_UTILISATEUR):
            self.session.consentir_enregistrement(self.horloge.maintenant(), portee=("transcription",))
            self._consenti = True

    def _divulguer(self) -> None:
        _, texte = self.session.divulguer(self.horloge.maintenant())
        self.rapport.paroles.append(
            ParoleRapportee("avatar", self.horloge.maintenant(), texte, len(texte), "divulgation"))

    def _garder(self, texte: str) -> str:
        """Le texte du répondant tel qu'il peut être dit : le garde-fou de sortie en dernier recours. Une violation
        n'est
        JAMAIS dite ; elle est consignée (hachage et code, pas le texte) et remplacée par une phrase sûre fixe."""
        verdict = garde_fou.verifier_sortie(texte)
        if verdict["code"] == "OK":
            return texte
        self.rapport.violations_garde_fou.append(
            {"sha256": hashlib.sha256(texte.encode()).hexdigest(), "code": verdict["code"]})
        return politique_dialogue.TEXTES["sur_repli"]

    # -- tour de l'appelant ---------------------------------------------------------------------------------------
    def _ouvrir_tour(self, tour: TourAppelant) -> None:
        # Un appelant qui parle avant la fin de la réponse simulée (barge-in) ne fait pas reculer le temps.
        self.horloge.avancer_a(max(tour.t, self.horloge.maintenant()))
        t = self.horloge.maintenant()
        if self.session.etat is voix.Etat.TOUR_AVATAR:
            if tour.interrompt:
                self.session.interrompre(t)
            else:
                self.session.fin_parole_avatar(t)
        self._appliquer_consentement()
        if isinstance(tour.texte, str) and tour.texte.strip():
            self.session.parole_utilisateur(t, tour.texte)

    def _contexte(self) -> ContexteRepondant:
        contenu = " ".join(self.comprises)
        diagnostic = qualification.diagnostiquer(contenu, self.zone, self.services,
                                                 {"telephone": self.script.telephone}) if contenu else {
            "service": None, "ville": None}
        service = diagnostic["service"]
        restantes: tuple[QuestionQualification, ...] = ()
        if service is not None:
            liste, verdict = taxonomie.charger_questions_du_service(service)
            etat = questions.evaluer(service, liste, verdict, contenu)
            restantes = tuple(q for q in etat.restantes if q.code not in self.questions_posees)
        return ContexteRepondant(
            tuple(self.comprises), service, diagnostic["ville"], {s.code: s.libelle for s in self.services},
            restantes, len(self.questions_posees), self.p.questions_max)

    def _repondre(self, etat_avant: EtatDialogue) -> tuple[Decision | None, bool]:
        """Le répondant parle sous garde-fou. Rend `(nouvelle décision, fin)` : une décision seulement s'il n'a pas
        compris
        (échec compté À LA SUITE de ceux d'avant ce tour, pas depuis le tour « compris » de la politique)."""
        reponse = self.repondant.repondre(self._contexte())
        if not isinstance(reponse, Reponse):
            raise RefusBacASable("REJ-BAC-A-SABLE-REPONDANT", "le répondant rend une `Reponse`")
        if reponse.texte is None:
            return politique_dialogue.echec_de_comprehension(
                etat_avant, self.p.seuils, self.script.humain_disponible, Motif.INCOMPREHENSION), False
        if not isinstance(reponse.texte, str) or not reponse.texte.strip():
            raise RefusBacASable("REJ-BAC-A-SABLE-REPONDANT", "le répondant rend un texte non vide, ou None")
        contexte = self._contexte()
        dit = self._garder(reponse.texte)
        self._dire(dit, "repondant" if dit == reponse.texte else "remplacement_garde_fou")
        if (contexte.service is not None and contexte.ville is not None and contexte.questions_restantes
                and dit == contexte.questions_restantes[0].question):
            self.questions_posees.add(contexte.questions_restantes[0].code)
        return None, reponse.fin

    def _enregistrer_decision(self, decision: Decision, tour: TourAppelant) -> None:
        self.rapport.decisions.append({
            "t": tour.t, "action": decision.action.value, "motif": decision.motif.value,
            "type_transfert": decision.type_transfert, "categories": list(decision.categories),
            "echecs": decision.etat.echecs})

    def jouer_tour(self, tour: TourAppelant) -> bool:
        """Joue un tour ; rend `True` quand l'appel est terminé (transfert, clôture)."""
        self._ouvrir_tour(tour)
        parle = isinstance(tour.texte, str) and bool(tour.texte.strip())
        if self.messagerie is not None:
            # Messagerie : l'appelant laisse son message ; la politique ne répond plus rien.
            if parle:
                self.enregistrables.append(tour.texte)
                self.rapport.paroles.append(self._parole_appelant(tour, "message_laisse"))
            return False
        # Le délai de réponse est SIMULÉ (valeur injectée) : l'avatar ne parle jamais à l'instant même.
        self.horloge.avancer_a(self.horloge.maintenant() + self.p.latence_reponse_s)
        self.rapport.latences_simulees_s.append(self.p.latence_reponse_s)
        etat_avant = self.etat
        decision = politique_dialogue.decider(
            tour.texte, tour.confiance, etat_avant, seuils=self.p.seuils, signaux_profil=self.signaux,
            verdict_profil=self.verdict_signaux, humain_disponible=self.script.humain_disponible)
        self._noter_parole(tour, decision)
        fin = False
        if decision.action in (Action.CONTINUER, Action.REPONSE_SURE):
            self.comprises.append(tour.texte)
            self.enregistrables.append(tour.texte)
        if decision.action is Action.CONTINUER:
            nouvelle, fin = self._repondre(etat_avant)
            if nouvelle is not None:       # le répondant n'a pas compris : un échec de compréhension de plus
                self.comprises.pop()
                self.enregistrables.pop()
                decision = nouvelle
        elif decision.ouvre_une_tache and parle and self._declencheur_enregistrable(decision, tour):
            self.enregistrables.append(tour.texte)   # ce qui a déclenché la tâche est lu par la personne
        self.etat = decision.etat
        self._enregistrer_decision(decision, tour)
        if decision.action is Action.CONTINUER:
            self.cloture = fin
            return fin
        self._dire(decision.texte, "politique")
        if decision.action is Action.MESSAGERIE:
            self.messagerie = decision
            return False
        if decision.action is Action.TRANSFERER:
            self.decision_finale = decision
            self.session.transferer_humain(self.horloge.maintenant(), decision.motif.value)
            return True
        return False

    def _declencheur_enregistrable(self, decision: Decision, tour: TourAppelant) -> bool:
        """Le texte qui a déclenché une tâche humaine entre au registre si une personne doit le lire. Jamais un texte
        peu sûr
        qui pourrait ouvrir un lead (sujets légal, financier, demande d'une personne, ou échecs répétés) ; la colère, la
        menace et le danger y entrent toujours (la plainte prime : aucun lead ne s'ouvre)."""
        if decision.motif in (Motif.URGENCE_SECURITE, Motif.MENACE_JURIDIQUE, Motif.PLAINTE):
            return True
        return decision.motif is not Motif.ECHECS_REPETES and politique_dialogue.confiance_suffisante(
            tour.confiance, self.p.seuils)

    def _parole_appelant(self, tour: TourAppelant, nature: str) -> ParoleRapportee:
        texte = tour.texte if self.consentement else None
        return ParoleRapportee("appelant", tour.t, texte, len(tour.texte or ""), nature,
                               None if tour.confiance is None else float(tour.confiance))

    def _noter_parole(self, tour: TourAppelant, decision: Decision) -> None:
        if not (isinstance(tour.texte, str) and tour.texte.strip()):
            nature = "silence"
        elif decision.motif is Motif.FAIBLE_CONFIANCE or (
                decision.motif is Motif.ECHECS_REPETES and tour.confiance is not None
                and Decimal(str(tour.confiance)) < self.p.seuils.confiance_minimale):
            nature = "faible_confiance"
        else:
            nature = "comprise"
        self.rapport.paroles.append(self._parole_appelant(tour, nature))
        if decision.etat.echecs > self.rapport.echecs_comprehension:
            self.rapport.echecs_comprehension = decision.etat.echecs


def _texte_enregistre(appel: _Appel) -> str:
    """Ce qui entre au registre : la parole comprise (et le message laissé) SEULEMENT avec le consentement `accorde`."""
    if not appel.consentement:
        return CONSIGNE_PLACEHOLDER
    return " ".join(appel.enregistrables) if appel.enregistrables else AUCUNE_PAROLE


def _finaliser(appel: _Appel, decision: Decision | None) -> None:
    """Écrit l'issue de l'appel avec les mêmes pièces que la messagerie vocale : un signal au registre (qualification,
    plainte et transfert selon les règles du profil), puis, si la politique l'a décidé ou que la demande reste
    incomplète,
    une tâche humaine avec résumé. Rien n'est envoyé au client."""
    script, rapport = appel.script, appel.rapport
    reg = outils._obtenir_registre()
    conversation_id = reception.identifiant_de_conversation("sms", script.telephone)
    signal_id = f"appel-bac-a-sable:{script.appel_id}"
    fenetre, verdict_fenetre = taxonomie.charger_fenetre_conversation()
    if verdict_fenetre is not None and verdict_fenetre["code"] != taxonomie.VERDICT_FENETRE_NON_CONFIGUREE:
        raise RefusBacASable("REJ-BAC-A-SABLE-PROFIL", f"{verdict_fenetre['code']}: {verdict_fenetre['detail']}")
    resultat = outils._traiter(
        _texte_enregistre(appel), CANAL_CONTRAT, conversation_id, signal_id, script.debut, list(appel.zone),
        script.consentement_enregistrement if appel.consentement else None, SOURCE_LEAD, None, None,
        contact_canal={"telephone": script.telephone}, fenetre_minutes=fenetre)
    rapport.contexte = {
        "decision_m1": resultat.get("decision"), "tours_comprises": len(appel.comprises),
        "echecs_comprehension": rapport.echecs_comprehension,
        "consentement_enregistrement": appel.consentement,
        "champs_manquants": list(resultat.get("champs_manquants", [])),
        "questions_posees": sorted(appel.questions_posees),
    }
    if resultat.get("qualifie") is True:
        rapport.lead = resultat["lead"]
    if "questions" in resultat:
        rapport.contexte["questions_repondues"] = list(resultat["questions"].get("repondues", []))
        rapport.contexte["questions_restantes"] = [q["code"] for q in resultat["questions"].get("restantes", [])]

    lignes = reg.lire()
    ouverts = transferts.ouverts_de(transferts.lire(lignes), conversation_id)
    type_voulu = None if decision is None else decision.type_transfert
    if decision is None and rapport.lead is None and not ouverts:
        type_voulu = politique_dialogue.TYPE_VENTES   # demande incomplète : jamais perdue, une personne la reprend
        rapport.rappel_a_faire = True
    existant = [e for e in ouverts if type_voulu is None or e.ouverture["type_transfert"] == type_voulu]
    if type_voulu is not None and not existant:
        signal = next(ligne for ligne in lignes
                      if ligne.get("type_entree") == "signal" and ligne.get("signal_id") == signal_id)
        destinataire, verdict_destinataire = taxonomie.charger_destinataire_du_transfert(type_voulu)
        ligne, refus = transferts.preparer_ouverture(
            lignes, type_transfert=type_voulu, categories=decision.categories if decision else (), termes={},
            declenche_par=transferts.DECLENCHE_PAR_REGLES, canal=CANAL_CONTRAT, source=SOURCE_LEAD,
            conversation_id=conversation_id, message_courant=signal, contact={"telephone": script.telephone},
            contact_source="numéro transmis par le bac à sable (faux appel)", destinataire=destinataire,
            verdict_destinataire=verdict_destinataire, fenetre_minutes=None)
        if ligne is None:
            raise RefusBacASable("REJ-BAC-A-SABLE-TRANSFERT", f"{refus['code']}: {refus['detail']}")
        reg.ajouter(ligne)
        existant = [transferts.EtatTransfert(ligne, None, ())]
    if existant:
        ouverture = existant[0].ouverture
        rapport.transfert = {
            "transfert_id": ouverture["transfert_id"], "type_transfert": ouverture["type_transfert"],
            "niveau": ouverture["niveau"], "destinataire": ouverture["destinataire"],
            "verdict_destinataire": ouverture["verdict_destinataire"], "resume": ouverture["resume"],
            "categories": list(ouverture["categories"]), "contact_present": ouverture["contact"] is not None}


def _issue(appel: _Appel, decision: Decision | None) -> tuple[str, str]:
    rapport = appel.rapport
    if appel.messagerie is not None:
        return ISSUE_MESSAGERIE, appel.messagerie.motif.value
    if decision is not None and decision.action is Action.TRANSFERER:
        return ISSUE_TRANSFERT, decision.motif.value
    if rapport.lead is not None:
        return ISSUE_LEAD, Motif.ORDINAIRE.value
    return ISSUE_RAPPEL, Motif.ORDINAIRE.value


def _resume(rapport: RapportAppel) -> str:
    """Un résumé composé par le code (jamais par un modèle), sans texte de l'appelant ni coordonnée."""
    parties = [f"Faux appel {rapport.appel_id} : issue {rapport.issue} (motif {rapport.motif})",
               f"{sum(1 for p in rapport.paroles if p.qui == 'appelant')} tour(s) de l'appelant, "
               f"{rapport.echecs_comprehension} échec(s) de compréhension consécutif(s) au plus récent"]
    if rapport.lead is not None:
        parties.append(f"lead {rapport.lead['service']} à {rapport.lead['ville']} transmis à M2")
    if rapport.transfert is not None:
        t = rapport.transfert
        parties.append(f"tâche humaine {t['type_transfert']} (niveau {t['niveau']}, destinataire "
                       f"{t['destinataire'] or 'à configurer'})")
    manquants = rapport.contexte.get("champs_manquants") or rapport.contexte.get("questions_restantes")
    if manquants:
        parties.append("à obtenir : " + ", ".join(manquants))
    if rapport.violations_garde_fou:
        parties.append(f"{len(rapport.violations_garde_fou)} parole(s) du répondant bloquée(s) par le garde-fou")
    parties.append("bac à sable : politique de dialogue seulement, aucune voix")
    return ". ".join(parties) + "."


def jouer(
    script: AppelScript,
    parametres: ParametresBac,
    repondant: Repondant | None = None,
    horloge: HorlogeSimulee | None = None,
) -> RapportAppel:
    """Joue un faux appel du début à la fin et rend son rapport. Déterministe : mêmes entrées, même rapport."""
    _valider(script, parametres)
    horloge = horloge or HorlogeSimulee()
    appel = _Appel(script, parametres, repondant or RepondantDeterministe(), horloge)
    try:
        appel._divulguer()
        joues = 0
        for tour in script.tours:
            joues += 1
            if appel.jouer_tour(tour):
                break
        appel.rapport.tours_non_joues = len(script.tours) - joues
        decision = appel.decision_finale or appel.messagerie   # la tâche humaine voulue par la politique
        _finaliser(appel, decision)
        appel.rapport.issue, appel.rapport.motif = _issue(appel, decision)
        if not appel.session.termine:
            if appel.messagerie is not None:
                raison = "messagerie"
            elif decision is not None:
                raison = decision.motif.value
            else:
                raison = "cloture" if appel.cloture else "appelant_raccroche"
            appel.session.terminer(horloge.maintenant(), raison)
    except AvatarRefus as exc:  # une règle de la session voix du socle : jamais passée sous silence
        raise RefusBacASable("REJ-BAC-A-SABLE-SESSION", f"{exc.code} : {exc}") from exc
    appel.rapport.session = appel.session.vers_json()
    appel.rapport.evenements_session = [e.type for e in appel.session.evenements]
    appel.rapport.resume = _resume(appel.rapport)
    return appel.rapport


__all__ = ["AppelScript", "ContexteRepondant", "HorlogeSimulee", "ParametresBac", "PORTEE", "RapportAppel",
           "RefusBacASable", "Reponse", "Repondant", "RepondantDeterministe", "TourAppelant", "jouer"]
