"""Service de l'usine à contenu de chantier : les registres durables et les gestes des outils (PLAN T4.17).

Les modules voisins (`chantier`, `registre`, `decision`, `paquet`, `retrait`, `controle_texte`) sont purs et
décident ; celui-ci lit et écrit `opsys.stockage.maillons` et établit ce que la plateforme seule peut établir :
QUI appelle (la personne d'un jeton d'appareil, confirmée en base à l'instant même), QUI a décidé (un humain),
QUEL WCT M7 a reçu du bus. Rien de tout cela ne vient d'un argument d'outil (AGENTS.md « le LLM orchestre, il
ne fournit jamais un fait »).

Registres (`m07-marketing`, append-only, durables) :
  - `wct_recus`                        les WCT `m4.travaux_termines` reçus (source unique des faits d'un chantier) ;
  - `contenus_chantier`                les propositions : un maillon par contenu et par révision ;
  - `decisions_contenu`                la décision humaine sur un contenu ;
  - `exports_paquet`                   la trace qu'un paquet manuel a été remis (avec sa clé `utm_content`) ;
  - `retraits_consentement_marketing`  le retrait du consentement d'un client, jamais effacé.

Aucun outil de ce service ne publie, n'envoie ni ne programme quoi que ce soit : la publication est manuelle. Un
paquet exporté annonce seulement au bus le fait `m7.contenu_exporte` (PLAN T4.17-e : la clé de mesure du contenu, son
chantier, son canal), pour que M8 compte les leads par contenu ; rien de personnel n'y voyage.
"""

from __future__ import annotations

import json
from typing import Any

from opsys import approbations, evenements, identite, stockage, taxonomie
from opsys import contexte as contexte_appel

from ..brand import profil_client as brand_profil_client
from . import chantier, mesure, paquet, plateformes, registre, retrait, verdicts
from . import decision as regle_decision
from .controle_texte import LIBELLES_REGLES, controler_texte

DEPARTEMENT = "m07-marketing"
# Le seul rôle qu'`m7_decider_contenu` reconnaît à un approbateur de la file (plus strict que la politique du
# département, qui peut s'élargir) : la décision d'un contenu public est celle du propriétaire.
ROLES_QUI_DECIDENT = frozenset({regle_decision.ROLE_DECIDEUR})
REGISTRE_WCT_RECUS = (DEPARTEMENT, "wct_recus")
REGISTRE_CONTENU_PUBLIC = (DEPARTEMENT, "contenu_public")
REGISTRE_CONTENUS_CHANTIER = (DEPARTEMENT, "contenus_chantier")
REGISTRE_DECISIONS_CONTENU = (DEPARTEMENT, "decisions_contenu")
REGISTRE_EXPORTS_PAQUET = (DEPARTEMENT, "exports_paquet")
REGISTRE_RETRAITS = (DEPARTEMENT, "retraits_consentement_marketing")

STATUT_WCT_INCONNU = "wct_inconnu"
STATUT_ANNONCE = "annonce"
STATUT_DEJA_ANNONCE = "deja_annonce"
STATUT_PROFIL_MARQUE_NON_CONFIGURE = "profil_marque_non_configure"
STATUT_OK = "ok"

ORIGINE_BUS = "bus:m4.travaux_termines"
ORIGINE_BUS_RETRAIT = "bus:m1.retrait_consentement"
ORIGINE_AGENT = "agent"

LIMITE_LISTE_DEFAUT = 5
LIMITE_LISTE_MAX = 8
# `Capacites` tronque au-delà de 6 000 caractères : le téléphone ne lirait pas la suite. La liste s'arrête
# avant (un contenu au moins par page), et dit ce qu'il reste (`suivant`, `reste`).
BUDGET_LISTE = 4500
RESUME_ATTENTE_MAX = 200
ACTION_ATTENTE = "lire (m7_lister_contenus_chantier) puis approuver ou rejeter (m7_decider_contenu)"
A_FAIRE_PAQUET_EXPORTE = "retirer à la main les publications déjà faites avec ces paquets exportés"


# -- lecture des registres ---------------------------------------------------------------------------------------
def _lire(registre_nom: tuple[str, str]) -> list[dict[str, Any]]:
    return list(stockage.maillons(*registre_nom))


def wct_recu(wct_id: str) -> dict[str, Any] | None:
    """Le WCT `m4.travaux_termines` déjà reçu pour `wct_id` (registre `wct_recus`, alimenté seulement par le
    consommateur d'événements, jamais par un argument d'outil), ou `None`."""
    for enregistrement in stockage.maillons(*REGISTRE_WCT_RECUS):
        if enregistrement.get("wct_id") == wct_id:
            return enregistrement
    return None


def _refus(verdict: dict[str, Any]) -> dict[str, Any]:
    return {"accepte": False, "verdict": verdict}


# -- qui appelle, qui décide ----------------------------------------------------------------------------------------
def _appelant_confirme() -> contexte_appel.IdentiteAppelante | None:
    """La personne et le rôle du jeton d'appareil, SI la base les confirme à l'instant même (personne active
    portant encore ce rôle) ; `None` pour un appel d'agent, hors transaction, ou une identité périmée."""
    appelante = contexte_appel.identite_appelante()
    cnx = stockage.connexion_courante()
    if appelante is None or cnx is None:
        return None
    return approbations.signataire_valide(cnx, appelante)


def _qui_appelle() -> tuple[str, str]:
    """`(personne, source)` : la personne du jeton confirmé, sinon « agent ». Sert la provenance, jamais un droit."""
    confirmee = _appelant_confirme()
    if confirmee is None:
        return ORIGINE_AGENT, ORIGINE_AGENT
    return confirmee.personne, regle_decision.SOURCE_APPAREIL


def _proprietaire_qui_decide(nom_outil: str) -> tuple[dict[str, str] | None, dict[str, Any] | None]:
    """Qui décide : `({par, role, source}, None)` si c'est le propriétaire, sinon `(None, verdict de refus)`.

    Deux voies, jamais une troisième, et jamais un texte de modèle ni un argument :
    1. un appel d'appareil dont l'identité (posée par le core d'après un jeton vérifié) est CONFIRMÉE en base,
       de rôle `admin`, et dont la PERSONNE porte `nathan_owner` (même plafond que l'app d'approbation du
       socle : un gestionnaire `admin` ne décide pas à la place du propriétaire) ;
    2. l'exécution d'une demande que le propriétaire vient d'approuver dans la file d'approbation : le SOCLE dit qui
       l'a approuvée (`approbations.approbateur_en_cours`, PLAN T4.15-d ; demande relue en base, personne active
       portant encore son rôle), et seul `nathan_owner` compte, même si la politique du département s'élargit. Les
       arguments ne sont pas comparés : `decider` rejoue les arguments EXACTS enregistrés et lui seul pose la
       demande en cours.
    Tout le reste est refusé : un appel d'agent qui n'a pas passé par l'approbation (un département en mode
    `supervise` ou `autonome` exécute un N3 sans file), un appel hors transaction où rien n'est vérifiable."""
    cnx = stockage.connexion_courante()
    appelante = contexte_appel.identite_appelante()
    if appelante is not None:
        confirmee = approbations.signataire_valide(cnx, appelante) if cnx is not None else None
        if confirmee is None:
            return None, verdicts.verdict(
                verdicts.REJ_HUMAIN_IDENTITE_INVALIDE,
                f"personne {appelante.personne!r} inconnue, inactive, ou ne porte plus le rôle "
                f"{appelante.role!r} du jeton d'appareil (ou identité non vérifiable hors transaction)",
            )
        personne = identite.personne_active(cnx, confirmee.personne)
        if confirmee.role != "admin" or personne is None or regle_decision.ROLE_DECIDEUR not in personne.roles:
            return None, verdicts.verdict(
                verdicts.REJ_HUMAIN_ROLE_INSUFFISANT,
                "l'approbation d'un contenu public est réservée au propriétaire (appareil admin de la personne "
                f"portant {regle_decision.ROLE_DECIDEUR})",
            )
        return {
            "par": confirmee.personne, "role": regle_decision.ROLE_DECIDEUR, "source": regle_decision.SOURCE_APPAREIL,
        }, None
    approbateur = approbations.approbateur_en_cours(cnx, nom_outil, DEPARTEMENT, roles=ROLES_QUI_DECIDENT)
    if approbateur is not None:
        return {
            "par": approbateur.personne, "role": approbateur.role, "source": regle_decision.SOURCE_APPROBATION,
        }, None
    return None, verdicts.verdict(
        verdicts.REJ_HUMAIN_REQUIS,
        "approuver ou rejeter un contenu est une décision humaine : un agent ne peut pas la prendre seul. Le "
        "propriétaire la prend depuis l'app admin (section « À voir »), ou approuve la demande dans la console "
        "OPSYS. Ne la présente pas comme faite.",
    )


def _horodatage_faisant_foi(horodatage: str) -> str:
    """Pendant un appel d'appareil idempotent, l'heure de RÉCEPTION du serveur fait foi, jamais l'horloge de
    l'appareil ni l'`horodatage` fourni (même patron que `m4_pointer`, T1.4-d, et M10)."""
    reception = contexte_appel.horodatage_reception()
    return reception.recu_le.isoformat() if reception is not None else horodatage


# -- la nature des travaux et le profil de marque -------------------------------------------------------------------
def nature_du_chantier(charge: dict[str, Any]) -> tuple[chantier.Nature | None, str | None]:
    """`(nature, None)` ou `(None, motif)`. Un lead v2 dit son `service` (code de la taxonomie de l'entreprise,
    jamais recopiée ici, résolue en libellé et en termes) ; un lead v1 dit son `type_travaux`. Jamais l'un déduit
    de l'autre, jamais les deux (donnée contradictoire), jamais une nature inventée pour continuer. Le motif ne
    porte que le code du verdict de la taxonomie : son détail nomme un chemin du serveur."""
    if "type_travaux" in charge and "service" in charge:
        return None, "type_travaux ET service dans le même WCT (lead v1 ou v2, jamais les deux) : aucun contenu"
    if "service" in charge:
        service, verdict = taxonomie.valider_service(charge["service"])
        if service is None:
            return None, (
                f"service {charge['service']!r} introuvable ({verdict['code']}) : déclarer les services de "
                "l'entreprise (profil d'entreprise de l'instance)"
            )
        return chantier.Nature(service.libelle, tuple(service.mots_cles)), None
    type_travaux = charge.get("type_travaux")
    if isinstance(type_travaux, str) and type_travaux.strip():
        mots = type_travaux.replace("_", " ").strip()
        return chantier.Nature(mots, (mots,)), None
    return None, "nature des travaux absente du WCT (ni service ni type_travaux) : aucun contenu sans elle"


def _valider_textes(textes: Any) -> dict[str, str]:
    if textes is None:
        return {}
    if not isinstance(textes, dict):
        raise ValueError("textes : un objet {plateforme: texte} est attendu")
    inconnues = sorted(set(textes) - set(plateformes.CODES_PLATEFORMES))
    if inconnues:
        attendues = ", ".join(plateformes.CODES_PLATEFORMES)
        raise ValueError(f"textes : plateforme inconnue {inconnues} (attendu : {attendues})")
    for code, texte in textes.items():
        if not isinstance(texte, str) or not texte.strip():
            raise ValueError(f"textes.{code} : un texte non vide est attendu")
    return dict(textes)


def _pret_a_composer(charge: dict[str, Any]) -> tuple[Any, chantier.Nature | None, dict[str, Any] | None]:
    """Les refus de départ, dans l'ordre de `chantier` puis le profil et la nature : `(profil, nature, None)`
    ou `(None, None, {statut, motif})`. Rien n'est écrit ici."""
    statut, motif = chantier.verifier_chantier(charge, _lire(REGISTRE_RETRAITS))
    if statut is not None:
        return None, None, {"statut": statut, "motif": motif}
    profil, motif = brand_profil_client.charger_profil_client()
    if profil is None:
        return None, None, {"statut": STATUT_PROFIL_MARQUE_NON_CONFIGURE, "motif": motif}
    nature, motif = nature_du_chantier(charge)
    if nature is None:
        return None, None, {"statut": chantier.STATUT_NATURE_INCONNUE, "motif": motif}
    return profil, nature, None


# -- proposer -------------------------------------------------------------------------------------------------------
def proposer_pour_charge(charge: dict[str, Any], textes: dict[str, str] | None, origine: str) -> dict[str, Any]:
    """Compose et enregistre les contenus d'un chantier dont le WCT est déjà reçu. Utilisé par le consommateur
    du bus (`textes` absent : gabarits du code) et par l'outil (`textes` du modèle, contrôlés comme le reste).

    Rend `{statut, motif, contenus}` ; `contenus` dit, par plateforme, ce qui est proposé, déjà là, refusé (avec
    ses règles) ou à récrire. Un refus de départ n'écrit RIEN ; un texte refusé n'écrit rien non plus."""
    profil, nature, refus = _pret_a_composer(charge)
    if refus is not None:
        return {**refus, "contenus": []}
    registre_contenus = stockage.maillons(*REGISTRE_CONTENUS_CHANTIER)
    preparation = chantier.preparer(
        charge, profil, nature, textes, list(registre_contenus), _lire(REGISTRE_DECISIONS_CONTENU), origine,
    )
    registre_contenus.extend(preparation.nouvelles)
    return {"statut": preparation.statut, "motif": None, "contenus": list(preparation.items)}


def proposer_contenus_chantier(wct_id: str, textes: dict[str, str] | None = None) -> dict[str, Any]:
    """Outil `m7_proposer_contenus_chantier` : voir `proposer_pour_charge`. Le WCT vient du registre `wct_recus`,
    jamais d'un argument ; un `wct_id` inconnu refuse (`wct_inconnu`), il n'invente rien."""
    charge = wct_recu(wct_id)
    if charge is None:
        return {
            "statut": STATUT_WCT_INCONNU, "contenus": [],
            "motif": f"wct_id inconnu : {wct_id!r} — aucun m4.travaux_termines reçu pour ce wct_id",
        }
    textes_valides = _valider_textes(textes)
    personne, source = _qui_appelle()
    origine = f"{source}:{personne}" if source == regle_decision.SOURCE_APPAREIL else ORIGINE_AGENT
    return proposer_pour_charge(charge, textes_valides, origine)


def lire_matiere_chantier(wct_id: str) -> dict[str, Any]:
    """Outil `m7_lire_matiere_chantier` (T0) : ce dont le modèle a besoin pour rédiger, et ce qui le refusera.
    Les mêmes refus que `proposer_contenus_chantier` (inutile de rédiger pour un chantier refusé). La note du
    chantier n'est montrée que si elle passe le contrôle des textes publics."""
    charge = wct_recu(wct_id)
    if charge is None:
        return {
            "statut": STATUT_WCT_INCONNU,
            "motif": f"wct_id inconnu : {wct_id!r} — aucun m4.travaux_termines reçu pour ce wct_id",
        }
    profil, nature, refus = _pret_a_composer(charge)
    if refus is not None:
        return refus
    matiere, avertissements = chantier.matiere_du_chantier(charge, profil, nature)
    description, motif_description = chantier.description_utilisable(charge, profil)
    ton = profil.get("tone")
    return {
        "statut": STATUT_OK,
        "matiere": {
            "marque": matiere.marque,
            "accroche": matiere.accroche or None,
            "ton": ton if isinstance(ton, str) and not ton.casefold().startswith(chantier.MARQUEUR_NON_CONFIGURE)
            else None,
            "nature": matiere.nature,
            "ville": matiere.ville,
            "note_du_chantier": description,
            "photos": len([p for p in (charge.get("photos") or []) if isinstance(p, str)]),
            "mots_clics": list(chantier.mots_clics(nature, matiere.ville, profil)),
            "garanties_validees": [g for g in (profil.get("garanties_validees") or []) if isinstance(g, str)],
        },
        "plateformes": [
            {"code": p.code, "libelle": p.libelle, "public": p.public, "longueur_max": p.longueur_max,
             "media": p.media}
            for p in plateformes.PLATEFORMES
        ],
        "regles": dict(LIBELLES_REGLES),
        "avertissements": [*avertissements, *([motif_description] if motif_description else [])],
    }


# -- lire la file --------------------------------------------------------------------------------------------------
def _ligne_contenu(vue: dict[str, Any]) -> dict[str, Any]:
    preuve = vue["preuve_consentement"]
    return {
        "contenu_id": vue["contenu_id"], "wct_id": vue["wct_id"], "plateforme": vue["plateforme"],
        "revision": vue["revision"], "approval_status": vue["approval_status"], "exporte": vue["exporte"],
        "texte": vue["texte"], "origine_texte": vue["origine_texte"], "mots_clics": vue["mots_clics"],
        "lien_utm": vue["lien_utm"], "avertissements": vue["avertissements"],
        "decision": vue["decision"],
        "consentement": {
            "recueilli_par": preuve["recueilli_par"], "recueilli_le": preuve["recueilli_le"],
            "version_texte": preuve["version_texte"],
        },
    }


def lister_contenus_chantier(
    wct_id: str | None = None, statut: str | None = None, limite: int = LIMITE_LISTE_DEFAUT, decalage: int = 0,
) -> dict[str, Any]:
    """Outil `m7_lister_contenus_chantier` (T0, `admin`) : les contenus du moment (la dernière révision de
    chaque plateforme de chaque chantier), les plus récents d'abord, avec leur statut, leur texte ENTIER (on ne
    décide pas ce qu'on n'a pas lu), leur décision et la preuve du consentement. Bornée : `Capacites` tronque
    à 6 000 caractères ; `suivant` est le `decalage` de la page suivante, `null` quand rien ne suit."""
    if isinstance(limite, bool) or not isinstance(limite, int) or not 1 <= limite <= LIMITE_LISTE_MAX:
        raise ValueError(f"limite : un entier de 1 à {LIMITE_LISTE_MAX} est attendu")
    if isinstance(decalage, bool) or not isinstance(decalage, int) or decalage < 0:
        raise ValueError("decalage : un entier de 0 ou plus est attendu")
    if statut is not None and statut not in registre.STATUTS:
        raise ValueError(f"statut : {', '.join(registre.STATUTS)} (ou absent)")
    decisions, exports = _lire(REGISTRE_DECISIONS_CONTENU), _lire(REGISTRE_EXPORTS_PAQUET)
    retraits = _lire(REGISTRE_RETRAITS)
    courantes = registre.dernieres_revisions(_lire(REGISTRE_CONTENUS_CHANTIER), wct_id)
    vues = [registre.vue(p, decisions, exports, retraits) for p in reversed(courantes)]
    if statut is not None:
        vues = [v for v in vues if v["approval_status"] == statut]
    lignes: list[dict[str, Any]] = []
    taille = 0
    for vue in vues[decalage:decalage + limite]:
        ligne = _ligne_contenu(vue)
        cout = len(json.dumps(ligne, ensure_ascii=False))
        if lignes and taille + cout > BUDGET_LISTE:
            break
        lignes.append(ligne)
        taille += cout
    apres = decalage + len(lignes)
    return {
        "total": len(vues), "contenus": lignes, "decalage": decalage,
        "suivant": apres if lignes and apres < len(vues) else None, "reste": max(0, len(vues) - apres),
    }


# -- décider ---------------------------------------------------------------------------------------------------------
def _contexte_du_contenu(proposition: dict[str, Any], profil: dict[str, Any]) -> Any:
    charge = wct_recu(proposition["wct_id"]) or {"wct_id": proposition["wct_id"]}
    return chantier.contexte_controle(charge, profil, plateformes.plateforme(proposition["plateforme"]).longueur_max)


def _refus_texte(proposition: dict[str, Any]) -> dict[str, Any] | None:
    """Le texte enregistré passe-t-il encore le contrôle ? (défense en profondeur : à l'approbation comme à
    l'export, jamais seulement à la proposition.) `None` s'il passe ; sinon le refus, qui nomme les règles."""
    profil, motif = brand_profil_client.charger_profil_client()
    if profil is None:
        return _refus(verdicts.verdict(verdicts.REJ_PROFIL_MARQUE, str(motif)))
    violations = controler_texte(proposition["texte"], _contexte_du_contenu(proposition, profil))
    if not violations:
        return None
    return _refus(chantier.verdict_texte_non_conforme([v.regle for v in violations]))


def decider_contenu(contenu_id: str, decision: str, horodatage: str, motif: str = "") -> dict[str, Any]:
    """Outil `m7_decider_contenu` : le propriétaire approuve ou rejette un contenu proposé (N3, « À voir »).

    Ordre (chaque refus intervient avant toute écriture) : qui décide (un humain, le propriétaire) ; le contenu
    existe ; son consentement n'est pas retiré ; c'est la dernière révision ; il est encore `PROPOSE` ; pour une
    approbation, son texte passe encore le contrôle. La décision porte l'empreinte du texte décidé."""
    acteur, refus = _proprietaire_qui_decide("m7_decider_contenu")
    if acteur is None:
        return _refus(refus or verdicts.verdict(verdicts.REJ_HUMAIN_REQUIS, "acteur humain introuvable"))
    propositions = _lire(REGISTRE_CONTENUS_CHANTIER)
    proposition = registre.proposition_par_id(propositions, contenu_id)
    if proposition is None:
        return _refus(verdicts.verdict(verdicts.REJ_CONTENU_INCONNU, f"contenu inconnu : {contenu_id!r}"))
    decisions, retraits = _lire(REGISTRE_DECISIONS_CONTENU), _lire(REGISTRE_RETRAITS)
    statut = registre.statut(proposition, decisions, retraits)
    if statut == registre.STATUT_RETIRE:
        return _refus(verdicts.verdict(
            verdicts.REJ_CONSENTEMENT_RETIRE, "le client a retiré son consentement marketing : rien à décider",
        ))
    if not registre.est_derniere_revision(proposition, propositions):
        return _refus(verdicts.verdict(verdicts.REJ_CONTENU_PERIME, "une révision plus récente existe pour ce contenu"))
    if statut != registre.STATUT_PROPOSE:
        return _refus(verdicts.verdict(verdicts.REJ_CONTENU_DEJA_TRANCHE, f"contenu déjà tranché ({statut})"))
    if decision == regle_decision.DECISION_APPROUVER:
        refus_texte = _refus_texte(proposition)
        if refus_texte is not None:
            return refus_texte
    maillon, verdict = regle_decision.construire_decision(
        proposition, decision, acteur["par"], acteur["role"], acteur["source"], motif,
        _horodatage_faisant_foi(horodatage),
    )
    if verdict is not None:
        return _refus(verdict)
    stockage.maillons(*REGISTRE_DECISIONS_CONTENU).append(maillon)
    approuve = maillon["decision"] == registre.STATUT_APPROUVE
    return {"accepte": True, "resultat": {
        "contenu_id": contenu_id, "plateforme": proposition["plateforme"], "approval_status": maillon["decision"],
        "par": maillon["par"], "source": maillon["source"], "horodatage": maillon["horodatage"],
        "empreinte_texte": maillon["empreinte_texte"],
        "prochaine_etape": "m7_exporter_paquet_manuel : le paquet à publier toi-même" if approuve
        else "un nouveau texte (textes de m7_proposer_contenus_chantier) crée une révision",
    }}


# -- exporter -------------------------------------------------------------------------------------------------------
def exporter_paquet_manuel(contenu_id: str, horodatage: str) -> dict[str, Any]:
    """Outil `m7_exporter_paquet_manuel` : le paquet manuel d'un contenu APPROUVÉ. Ne publie rien, n'appelle
    aucune API : il remet au propriétaire le texte, les mots-clics, le lien, les médias (« à flouter à la
    main »), l'heure suggérée du profil, les instructions. Refuse un contenu non approuvé, un chantier dont le
    consentement est retiré, un texte modifié depuis l'approbation ou qui ne passe plus le contrôle. La trace de
    l'export s'écrit une seule fois ; un second appel rend le même paquet (`deja_exporte`)."""
    propositions = _lire(REGISTRE_CONTENUS_CHANTIER)
    proposition = registre.proposition_par_id(propositions, contenu_id)
    if proposition is None:
        return _refus(verdicts.verdict(verdicts.REJ_CONTENU_INCONNU, f"contenu inconnu : {contenu_id!r}"))
    decisions, exports = _lire(REGISTRE_DECISIONS_CONTENU), _lire(REGISTRE_EXPORTS_PAQUET)
    retraits = _lire(REGISTRE_RETRAITS)
    contenu = registre.vue(proposition, decisions, exports, retraits)
    if contenu["approval_status"] == registre.STATUT_RETIRE:
        return _refus(verdicts.verdict(
            verdicts.REJ_CONSENTEMENT_RETIRE, "le client a retiré son consentement marketing : aucun export",
        ))
    if contenu["approval_status"] != registre.STATUT_APPROUVE:
        return _refus(verdicts.verdict(
            verdicts.REJ_CONTENU_NON_APPROUVE,
            f"contenu {contenu['approval_status']} : le propriétaire l'approuve d'abord (m7_decider_contenu)",
        ))
    approbation = registre.decision_de(contenu_id, decisions)
    if approbation is None or approbation["empreinte_texte"] != proposition["empreinte_texte"]:
        return _refus(verdicts.verdict(
            verdicts.REJ_CONTENU_MODIFIE, "le texte n'est plus celui que le propriétaire a approuvé : aucun export",
        ))
    refus_texte = _refus_texte(proposition)
    if refus_texte is not None:
        return refus_texte
    utm_content, refus_mesure = mesure.identifiant_de_mesure(proposition)
    if utm_content is None:
        return _refus(refus_mesure or verdicts.verdict(verdicts.REJ_CONTENU_SANS_IDENTIFIANT, "clé de mesure absente"))
    contenu = {**contenu, "utm_content": utm_content}
    profil, _ = brand_profil_client.charger_profil_client()
    charge = wct_recu(proposition["wct_id"]) or {}
    composition = paquet.composer_paquet(contenu, charge, _lire(REGISTRE_CONTENU_PUBLIC), profil or {})
    export = registre.export_de(contenu_id, exports)
    deja_exporte = export is not None
    if export is None:
        personne, _source = _qui_appelle()
        maillon, verdict = paquet.construire_export(contenu, personne, _horodatage_faisant_foi(horodatage))
        if verdict is not None:
            return _refus(verdict)
        stockage.maillons(*REGISTRE_EXPORTS_PAQUET).append(maillon)
        export = maillon
    return {"accepte": True, "resultat": {
        **composition, "deja_exporte": deja_exporte,
        "mesure": _annoncer_contenu_exporte(proposition, utm_content, export["horodatage"]),
    }}


def _annoncer_contenu_exporte(proposition: dict[str, Any], utm_content: str, exporte_le: str) -> dict[str, str]:
    """Annonce au bus `m7.contenu_exporte`, dans la transaction de l'export (PLAN T4.17-e). L'identifiant du fait est
    celui du contenu : un export rejoué republie le même, un no-op de l'outbox. Republier à chaque appel rattrape un
    paquet exporté avant l'existence du fait (le ré-exporter, c'est l'annoncer), sans jamais annoncer deux fois."""
    evenement_id = mesure.evenement_id(proposition["contenu_id"])
    deja_annonce = evenements.deja_publie(evenement_id)
    evenements.publier(
        mesure.TYPE_EVENEMENT, DEPARTEMENT, mesure.charge_contenu_exporte(proposition, utm_content, exporte_le),
        evenement_id=evenement_id,
    )
    return {"fait": mesure.TYPE_EVENEMENT, "statut": STATUT_DEJA_ANNONCE if deja_annonce else STATUT_ANNONCE}


# -- retirer le consentement ----------------------------------------------------------------------------------
def enregistrer_retrait_consentement_marketing(wct_id: str, canal: str, horodatage: str) -> dict[str, Any]:
    """Outil `m7_enregistrer_retrait_consentement_marketing` (Loi 25) : le client a retiré son consentement à
    l'usage de son chantier en contenu public. Écrit une fois, ne se lève pas ; bloque à l'instant toute tâche
    de contenu de ce chantier (et des chantiers du même lead), y compris un paquet déjà proposé ou approuvé.
    Idempotent. La réponse dit ce qui est bloqué et ce qui, exporté, doit être retiré à la main."""
    charge = wct_recu(wct_id) if isinstance(wct_id, str) else None
    lead_id = charge.get("lead_id") if charge is not None else None
    personne, source = _qui_appelle()
    maillon, verdict = retrait.construire_retrait(
        wct_id, lead_id, canal, personne, source, _horodatage_faisant_foi(horodatage),
    )
    if verdict is not None:
        return _refus(verdict)
    retraits = _lire(REGISTRE_RETRAITS)
    existant = next((r for r in retraits if r["retrait_id"] == maillon["retrait_id"]), None)
    if existant is None:
        stockage.maillons(*REGISTRE_RETRAITS).append(maillon)
        existant = maillon
    contenus_bloques, deja_exportes = _contenus_touches_par([existant])
    a_faire = []
    if deja_exportes:
        a_faire.append(A_FAIRE_PAQUET_EXPORTE)
    if charge is None:
        a_faire.append(
            "wct_id inconnu de M7 : le retrait est enregistré et bloquera ce chantier s'il arrive ; vérifier le wct_id"
        )
    return {"accepte": True, "resultat": {
        "retrait_id": existant["retrait_id"], "wct_id": existant["wct_id"], "lead_id": existant["lead_id"],
        "wct_connu": charge is not None, "deja_enregistre": existant is not maillon,
        "contenus_bloques": contenus_bloques, "contenus_deja_exportes": deja_exportes,
        "a_faire": a_faire,
    }}


def _contenus_touches_par(retraits: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """`(contenus bloqués, dont déjà exportés)` : les contenus courants que ces retraits bloquent, par chantier ou
    par lead. Un paquet exporté a pu être publié à la main : M7 ne publie jamais, il le dit."""
    concernes = [
        p for p in registre.dernieres_revisions(_lire(REGISTRE_CONTENUS_CHANTIER))
        if any(retrait.retrait_applicable(p["wct_id"], p.get("lead_id"), [r]) is not None for r in retraits)
    ]
    exports = _lire(REGISTRE_EXPORTS_PAQUET)
    deja_exportes = [p["contenu_id"] for p in concernes if registre.export_de(p["contenu_id"], exports) is not None]
    return [p["contenu_id"] for p in concernes], deja_exportes


def enregistrer_retrait_de_leads(charge: dict[str, Any]) -> dict[str, Any]:
    """Consommateur `m1.retrait_consentement` (PLAN T4.17-c) : le client a écrit STOP à M1, qui dit au bus quels leads
    il avait ouverts pour lui. M7 inscrit UN retrait par lead (`retraits_consentement_marketing`, sans `wct_id`) : tout
    chantier de ces leads est bloqué, celui déjà reçu comme celui qui arrivera, paquet exporté compris (même
    registre, mêmes blocages que `m7_enregistrer_retrait_consentement_marketing`).

    Idempotent (un retrait par lead, identifiant déterministe) : une relivraison n'écrit rien. Fail-closed : une charge
    que M7 ne sait pas lire lève, l'événement est rejoué puis mis en quarantaine, visible ; un retrait n'est jamais
    ignoré en silence. Le résumé ne porte que des identifiants et des comptes : jamais un contact."""
    canal, horodatage = charge.get("canal"), charge.get("horodatage")
    lead_ids = charge.get("lead_ids")
    if not isinstance(lead_ids, list) or not lead_ids:
        raise ValueError(f"{verdicts.REJ_RETRAIT_INVALIDE}: lead_ids : au moins un lead est attendu")
    # Tout est validé avant la première écriture : un lead illisible ne laisse pas les autres à moitié inscrits.
    maillons: dict[str, dict[str, Any]] = {}
    for lead_id in lead_ids:
        maillon, verdict = retrait.construire_retrait_de_lead(
            lead_id, canal, ORIGINE_BUS_RETRAIT, ORIGINE_BUS_RETRAIT, horodatage,
        )
        if verdict is not None:
            raise ValueError(f"{verdict['code']}: {verdict['detail']}")
        maillons.setdefault(maillon["retrait_id"], maillon)
    journal = stockage.maillons(*REGISTRE_RETRAITS)
    connus = {r["retrait_id"] for r in journal}
    ecrits = [m for retrait_id, m in maillons.items() if retrait_id not in connus]
    for maillon in ecrits:
        journal.append(maillon)
    deja_enregistres = len(maillons) - len(ecrits)
    contenus_bloques, deja_exportes = _contenus_touches_par(ecrits)
    return {
        "traite": True, "retraits_ecrits": len(ecrits), "deja_enregistres": deja_enregistres,
        "contenus_bloques": contenus_bloques, "contenus_deja_exportes": deja_exportes,
        "a_faire": [A_FAIRE_PAQUET_EXPORTE] if deja_exportes else [],
    }


# -- « À voir » ----------------------------------------------------------------------------------------------------
def _resume_attente(proposition: dict[str, Any]) -> str:
    plateforme = plateformes.plateforme(proposition["plateforme"])
    lieu = f" à {proposition['ville']}" if proposition.get("ville") else ""
    une_ligne = " ".join(proposition["texte"].split())
    debut = f"{plateforme.libelle} — {proposition['nature']}{lieu} : « "
    reste = RESUME_ATTENTE_MAX - len(debut) - 2
    extrait = une_ligne if len(une_ligne) <= reste else une_ligne[: max(reste - 1, 0)] + "…"
    return f"{debut}{extrait} »"


def attentes() -> list[dict[str, Any]]:
    """La section « À voir » du propriétaire (ADR-0009 §5) : un contenu de chantier `PROPOSE` attend sa décision
    (N3). Lecture seule : ne décide ni n'exporte rien. Les contenus dont le consentement est retiré n'y sont plus."""
    decisions, retraits = _lire(REGISTRE_DECISIONS_CONTENU), _lire(REGISTRE_RETRAITS)
    return [
        {
            "type": "contenu_a_approuver",
            "id": proposition["contenu_id"],
            "resume": _resume_attente(proposition),
            "niveau": "N3",
            "depuis": proposition["propose_le"],
            "action_proposee": ACTION_ATTENTE,
        }
        for proposition in registre.dernieres_revisions(_lire(REGISTRE_CONTENUS_CHANTIER))
        if registre.statut(proposition, decisions, retraits) == registre.STATUT_PROPOSE
    ]


# -- retrait et contenu public (T4.3) -----------------------------------------------------------------------
def retrait_bloquant(charge: dict[str, Any]) -> dict[str, Any] | None:
    """Le retrait du consentement marketing qui bloque ce chantier, ou `None` : consulté par tout outil de
    contenu public, dont `m7_preparer_contenu_public` (T4.3)."""
    bloquant = retrait.retrait_applicable(charge.get("wct_id"), charge.get("lead_id"), _lire(REGISTRE_RETRAITS))
    return None if bloquant is None else dict(bloquant)
