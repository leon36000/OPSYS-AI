"""Capacités d'agent du département M4 Field Ops.

Chaque outil enveloppe une fonction métier déterministe existante (etats,
cedule, pointage, ecarts, outbox, digest, preuves, temps) : aucune n'est
réécrite. Comme le
registre M4 (`registre.Registre`) est un journal que les fonctions métier
reçoivent en paramètre vivant — jamais un objet JSON-sérialisable —
`outils()` referme par fermeture (closure) sur chaque fonction exposée l'accès
au registre du département : c'est ce qui permet à l'agent d'enchaîner
inscription → pointage → complétion → digest par de simples appels d'outils,
sans jamais manipuler le registre lui-même.

Registre de production (ADR-0009) : par défaut, `outils()` adosse ce registre
au stockage durable de l'instance (`opsys.stockage.maillons`, dans la
transaction que `Capacites.appeler` ouvre pour chaque appel d'outil), relu à
chaque usage car la console et le serveur MCP écrivent la même chaîne —
`registre.py` reste pur (aucun import `opsys`/SQLAlchemy) et ignore que ses
maillons survivent au redémarrage : c'est cet adaptateur, seul, qui fait le
lien. Le paramètre `registre_cible` est le point d'injection : les tests
unitaires du département y passent explicitement un `registre.Registre()` EN
MÉMOIRE (aucune base montée), sans toucher au comportement par défaut utilisé
par `charger_outils()` en production.

`m4_planifier_intervention` compose inscription + cédule en un seul appel
(gain : deux allers-retours évités). Chaque outil unitaire reste disponible
pour les cas où seule une étape est nécessaire (ex. un pointage isolé).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from functools import partial
from typing import Any

from opsys import approbations, cles_chiffrement, contexte, evenements, fichiers, stockage
from opsys import equipes as equipes_entreprise
from opsys.outils import Autonomie, Niveau, Outil, depuis_couple

from . import (
    acces,
    cedule,
    cedule_tournees,
    consentement,
    digest,
    ecarts,
    etats,
    localisation,
    outbox,
    pointage,
    preparation,
    preuves,
    registre,
    retention,
    temps,
    tournees,
    verdicts,
)

# PLAN T4.2 (POLITIQUE-geolocalisation.md §5) : portée des clés de chiffrement GPS dans le coffre
# du socle (opsys.cles_chiffrement) — une seule portée pour tout M4, l'identifiant est le
# technicien_id (une clé par employé, alignée sur l'unité de rétention/purge de la politique,
# jamais par pointage individuel).
_PORTEE_CLES_GPS = "m04-field-ops/gps"

_DEPARTEMENT = "m04-field-ops"
_NOM_REGISTRE = "principal"

_CONTRAT = {"type": "object", "description": "LeadQualifie M2, v1 ou v2 selon la version qu'il déclare "
            "(jamais devinée) : v1, sept clés gelées (lead_id, conversation_id, type_travaux, ville, "
            "canal, contact, urgence_declaree) ; v2, schema_version 2 et service (code déclaré par "
            "l'entreprise) à la place de type_travaux."}
_MARQUEUR = {"type": "object", "description": "Marqueur de readiness signé par M2 (cinq clés)."}
_FIX_GPS = {
    "type": ["object", "null"],
    "description": (
        "{latitude, longitude}, ou null. PLAN T4.2 (POLITIQUE-geolocalisation.md §4) : même fourni "
        "réel, un fix est IGNORÉ si le consentement GPS du technicien n'est pas actif — le pointage "
        "bascule alors en mode manuel (accusé.mode_pointage == 'manuel'), jamais rejeté."
    ),
}
_ATTESTATION = {"type": "object", "description": "{fictif: true, appareil_id} — mode ombre uniquement."}
_FENETRE = {"type": "object", "description": "{debut, fin} ISO-8601 avec fuseau."}
_REFERENTIEL_VILLES = {"type": "object", "description": "{ville_tokenisee: {latitude, longitude, rayon_km}}."}
_PREUVE_CONSENTEMENT = {
    "type": "object",
    "description": (
        "{fictif: true, reference} — référence au formulaire/preuve signé (jamais le document "
        "lui-même). Mode ombre : seule une preuve fictive est supportée (POLITIQUE-geolocalisation.md §4)."
    ),
}
_ADRESSE_CHANTIER = {
    "type": ["object", "string"],
    "description": (
        "Adresse du chantier. Objet {numero_municipal, odonyme, municipalite} obligatoires, plus "
        "suffixe, unite, code_municipalite, code_postal si connus ; ou une ligne « [unité-]numéro "
        "[suffixe] odonyme, municipalité [code postal] ». Jamais complétée ni devinée."
    ),
}
_VERSION_METIER = {"type": "object", "description": "{duree_minutes, perimetre, materiaux}."}
_PREUVES_COMPLETION = {
    "type": "object",
    "description": (
        "{checklist_complete: bool (doit être true), photos_apres: [string,...] non vide, "
        "notes: string, signature: string|null}. Exigé pour clore une intervention (§6/§9.7)."
    ),
}
_PERIODE = {"type": "object", "description": "{debut, fin} AAAA-MM-JJ, bornes incluses."}
_EMPREINTE_SHA256 = {
    "type": "string",
    "pattern": "^[0-9a-f]{64}$",
    "description": "SHA-256 (hexadécimal minuscule) du contenu COMPLET du fichier.",
}

# PLAN T1.5-d : identifiant de la version du texte de consentement que l'app a présenté au client
# (ex. « consentement-client-fr-CA-v1 ») — une étiquette, jamais le texte lui-même ni une donnée
# personnelle : caractères sûrs, bornée.
_FORMAT_VERSION_TEXTE_CONSENTEMENT = r"^[A-Za-z0-9._-]{1,64}$"

# T1.4-e2 : traduction des raisons génériques du dépôt socle (opsys.fichiers, département-
# agnostique) vers le catalogue de verdicts FERMÉ de M4 — aucun autre module ne connaît ces codes.
_RAISON_DEPOT_VERS_CODE = {
    fichiers.RAISON_PARAMETRES_INVALIDES: "REJ-FICHIER-PARAMETRES-INVALIDES",
    fichiers.RAISON_TROP_VOLUMINEUX: "REJ-FICHIER-TROP-VOLUMINEUX",
    fichiers.RAISON_INCOHERENT: "REJ-FICHIER-INCOHERENT",
    fichiers.RAISON_EMPREINTE_DISCORDANTE: "REJ-FICHIER-EMPREINTE-DISCORDANTE",
    fichiers.RAISON_TYPE_NON_PERMIS: "REJ-FICHIER-TYPE-NON-PERMIS",
}
# Types permis pour une référence photos_apres (toute image) et pour une référence signature
# (PNG seulement, T1.4-e2 point 3 du PLAN).
_TYPES_PHOTO_APRES = fichiers.TYPES_MIME_PERMIS
_TYPES_SIGNATURE = ("image/png",)


def _acteur_appareil() -> tuple[acces.Acteur | None, dict[str, Any] | None]:
    """Qui appelle : ``(None, None)`` hors appel d'appareil, ``(acteur, None)`` si l'identité du
    jeton est CONFIRMÉE en base, ``(None, verdict)`` sinon (PLAN T1.4-k).

    ``contexte.identite_appelante()`` ne rend que ce que le core a transmis en `_meta` : la personne
    a pu être désactivée, ou perdre le rôle, depuis l'émission du jeton (le fragment de
    configuration du core n'est régénéré qu'à la demande). On la revérifie donc à chaque appel avec
    la même fonction que la validation humaine au départ (``approbations.signataire_valide``, T1.4-h :
    personne active portant encore ce rôle), au lieu d'une seconde règle qui pourrait diverger.
    Hors transaction (aucune base jointe), rien n'est vérifiable : refus fermé, jamais une identité
    crue sur parole. Ne lit JAMAIS les arguments de l'outil."""
    appelante = contexte.identite_appelante()
    if appelante is None:
        return None, None
    cnx = stockage.connexion_courante()
    confirmee = approbations.signataire_valide(cnx, appelante) if cnx is not None else None
    if confirmee is None:
        return None, verdicts.construire_verdict(
            "REJ-IDENTITE-APPAREIL-INVALIDE",
            detail=(
                f"personne {appelante.personne!r} inconnue, inactive, ou ne porte plus le rôle "
                f"{appelante.role!r} porté par le jeton d'appareil (ou identité non vérifiable "
                "hors transaction)"
            ),
        )
    return acces.acteur_de(confirmee.personne, confirmee.role)


def _lecteur_equipes() -> Callable[[], tuple[dict[str, Any] | None, dict[str, Any] | None]]:
    """Lecture du profil des équipes de l'entreprise (PLAN T4.12), faite UNE fois par appel d'outil : la sélection des
    interventions, la complétion des arguments, la préparation et l'application voient le même profil. Rend
    ``(profil, None)`` ou ``(None, verdict)`` (absent ou invalide) ; ne lève jamais."""
    lecture = equipes_entreprise.charger_equipes()
    return lambda: lecture


def _preuve_consentement_client(
    acteur: acces.Acteur | None, consentement_marketing: Any, consentement_demande_avis: Any,
    version_texte: Any,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """PLAN T1.5-d : la PREUVE des consentements que l'employé a recueillis auprès du client, ou le
    verdict qui dit ce qui manque. ``({}, None)`` quand aucun consentement n'est envoyé : rien à
    prouver, rien n'est posé (ni personne ni heure), et un consentement n'existe jamais par défaut.

    Ces consentements portent la PAROLE DU CLIENT, recueillie par l'employé authentifié : M4 les
    prend tels qu'envoyés (un agent, lui, ne le peut jamais, voir plus haut), mais ne prend de
    l'appareil que ce qu'il sait vraiment, la version du texte qu'il a montré. Le reste est posé
    par le SERVEUR, jamais par les arguments :
      - ``consentement_recueilli_par`` : la personne du jeton, CONFIRMÉE en base (``acteur``) ;
      - ``consentement_recueilli_le`` : l'heure de RÉCEPTION du serveur, pas l'horloge du téléphone.
    Sans personne confirmée, personne n'a recueilli ce consentement : refus (fail-closed), plutôt
    qu'un consentement dont on ne saurait dire qui l'a obtenu. Sans version du texte, on ne saurait
    pas dire à quoi le client a consenti : refus aussi. Le WCT est écrit dans le registre de M4
    (chaîne immuable) : c'est la preuve durable, relue par M7 sur le bus."""
    consentement_fourni = (
        consentement_marketing is not outbox.NON_FOURNI
        or consentement_demande_avis is not outbox.NON_FOURNI
    )
    if not consentement_fourni:
        if version_texte is not outbox.NON_FOURNI:
            return {}, verdicts.construire_verdict(
                "REJ-CONSENTEMENT-INVALIDE",
                detail="consentement_version_texte sans aucun consentement : rien à prouver",
            )
        return {}, None
    if (
        not isinstance(version_texte, str)
        or re.fullmatch(_FORMAT_VERSION_TEXTE_CONSENTEMENT, version_texte) is None
    ):
        return {}, verdicts.construire_verdict(
            "REJ-CONSENTEMENT-INVALIDE",
            detail=(
                "consentement_version_texte requis avec un consentement client : l'identifiant "
                "(1 à 64 caractères, lettres, chiffres, point, tiret) de la version du texte "
                "présentée au client, sans quoi on ne sait pas à quoi il a consenti"
            ),
        )
    if acteur is None:
        return {}, verdicts.construire_verdict(
            "REJ-IDENTITE-APPAREIL-INVALIDE",
            detail=(
                "un consentement client exige la personne authentifiée qui l'a recueilli : "
                "aucune identité confirmée pour cet appel"
            ),
        )
    reception = contexte.horodatage_reception()
    if reception is None:  # déjà refusé plus haut ; défense en profondeur, jamais une heure inventée
        return {}, verdicts.construire_verdict(
            "REJ-CHAMPS-CLIENT-HORS-APPAREIL",
            detail="un consentement client n'est daté que par l'heure de réception d'un appel d'appareil",
        )
    return {
        "consentement_recueilli_par": acteur.personne,
        "consentement_recueilli_le": reception.recu_le.isoformat(),
        "consentement_version_texte": version_texte,
    }, None


def _refus(verdict: dict[str, Any]) -> dict[str, Any]:
    return {"accepte": False, "verdict": verdict}


def outils(
    registre_cible: registre.Registre | None = None, fournisseur_matrice: Any = None,
) -> tuple[Outil, ...]:
    """Capacités exposées aux agents, qui partagent le registre du département.

    `registre_cible` : `None` (défaut, utilisé par `charger_outils()` en production) adosse le
    registre au stockage durable de l'instance ; un `registre.Registre()` explicite (tests) reste
    en mémoire, jamais touché à la base.

    `fournisseur_matrice` : port `distances.FournisseurMatrice` (palier 1, routage) que la cédule par
    tournées consulte ; `None` (défaut, production tant qu'aucun sidecar de routage n'est déployé) donne le
    palier 0, distances approximatives affichées « mode bridé ». Jamais un argument d'outil : l'adresse du
    service ne vient pas d'un agent.
    """
    if registre_cible is None:
        def registre_courant() -> registre.Registre:
            # Neuf à chaque usage : relu depuis la base dans la transaction de l'appel, il ne
            # garde jamais l'empreinte d'un état qu'un autre processus a depuis prolongé.
            return registre.Registre(stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
    else:
        def registre_courant() -> registre.Registre:
            return registre_cible

    def _cnx_durable():
        """Connexion durable RÉELLE, ou None (PLAN T4.2). Contrairement à ``stockage.
        connexion_courante() is not None`` seul (garde historique de ``completer_intervention``
        pour ``evenements.publier``, jamais mise en défaut jusqu'ici), ce coffre a besoin d'une
        garde plus stricte : ``registre_cible is None`` (donc production, adossée au stockage
        durable) EST exigé en plus d'une transaction active — un test qui fournit un
        ``registre.Registre()`` EN MÉMOIRE explicite peut malgré tout être enveloppé par
        ``executer_atomique`` (ex. ``test_evenements_m4.py::test_completion_hors_transaction_...``,
        qui migre pourtant AUCUNE base) ; sans cette double condition, ``cles_chiffrement.
        obtenir_ou_creer`` tenterait d'écrire dans une table qui n'existe pas.
        """
        if registre_cible is not None:
            return None
        return stockage.connexion_courante()

    # -- fonctions enveloppes (closures sur registre_courant) ---------------

    def planifier_intervention(
        contrat: dict[str, Any], marqueur: dict[str, Any], horodatage: str, sel: str,
        techniciens_disponibles: list[str], fenetres_disponibles: list[dict[str, Any]],
        devis_id: str | None = None,
    ) -> dict[str, Any]:
        """Inscrit l'intervention PUIS calcule sa cédule en un seul appel."""
        accuse, verdict = etats.inscrire_intervention(
            contrat, marqueur, registre_courant(), horodatage, sel, devis_id=devis_id,
        )
        if verdict is not None:
            return {"etape": "inscription", "accepte": False, "verdict": verdict}
        # PLAN T0.13-b : la cédule reçoit la nature des travaux sous la clé de la version du lead
        # (v2 : `service`, sinon `type_travaux`), jamais l'une déduite de l'autre.
        cle_travaux = etats.CLE_SERVICE if "schema_version" in contrat else etats.CLE_TYPE_TRAVAUX
        intervention_pour_cedule = {
            "intervention_id": accuse["intervention_id"],
            "lead_id": contrat["lead_id"],
            cle_travaux: contrat[cle_travaux],
            "ville": contrat["ville"],
        }
        cedule_resultat, verdict_cedule = cedule.generer_cedule(
            [intervention_pour_cedule], techniciens_disponibles, fenetres_disponibles, sel
        )
        if verdict_cedule is not None:
            return {
                "etape": "cedule", "accepte": True, "intervention_id": accuse["intervention_id"],
                "statut": accuse["statut"], "assignation": None,
                "avertissement_cedule": verdict_cedule,
            }
        assignations = cedule_resultat["assignations"]
        assignation = assignations[0] if assignations else None
        if assignation is not None:
            # PLAN T1.4-k : la cédule dit À QUI est l'intervention ; sans ce maillon, l'assignation
            # n'entrait au registre qu'avec le départ (en_route) et aucune intervention n'était
            # « à quelqu'un » avant. Entrées déjà validées par l'inscription et la cédule ci-dessus :
            # un refus ici trahirait une incohérence interne, jamais un cas d'usage — on lève plutôt
            # que de laisser une inscription orpheline (l'appel atomique annule alors les deux).
            _, verdict_assignation = etats.assigner_technicien(
                accuse["intervention_id"], assignation["technicien_id"], registre_courant(), horodatage,
            )
            if verdict_assignation is not None:
                raise RuntimeError(
                    f"assignation refusée après une inscription valide : {verdict_assignation['code']}"
                )
        return {
            "etape": "complet", "accepte": True, "intervention_id": accuse["intervention_id"],
            "statut": accuse["statut"], "tete_chaine": accuse["tete_chaine"],
            "assignation": assignation,
            "non_cedulee": assignation is None,
        }

    def demarrer_route(intervention_id: str, technicien_id: str, horodatage: str) -> dict[str, Any]:
        # PLAN T1.4-k : un employé ne part que sous son identifiant, sur SON intervention.
        acteur, verdict_acteur = _acteur_appareil()
        if verdict_acteur is not None:
            return _refus(verdict_acteur)
        verdict_acces = acces.controler_technicien(acteur, technicien_id) or acces.controler_intervention(
            registre_courant(), intervention_id, acteur)
        if verdict_acces is not None:
            return _refus(verdict_acces)
        # PLAN T4.2 — même patron que m4_pointer (T1.4-d, R12 §4) : pendant un appel d'appareil,
        # l'heure de RÉCEPTION DU SERVEUR fait foi, jamais l'horloge de l'appareil ni la valeur
        # `horodatage` fournie par l'appelant ; l'heure d'appareil reste lisible À CÔTÉ, sur
        # l'accusé, jamais consultée pour un calcul (`etats.transitionner` reste inchangé : la
        # décision appartient à cet adaptateur seul, comme pour tous les outils T1.4-d de M4).
        # Hors appel d'appareil : comportement strictement inchangé.
        horodatage_appareil_ctx = contexte.horodatage_reception()
        if horodatage_appareil_ctx is not None:
            horodatage_faisant_foi = horodatage_appareil_ctx.recu_le.isoformat()
            horodatage_appareil = horodatage_appareil_ctx.horodatage_appareil.isoformat()
        else:
            horodatage_faisant_foi = horodatage
            horodatage_appareil = None
        reponse = depuis_couple(etats.transitionner(
            intervention_id, "en_route", registre_courant(), horodatage_faisant_foi,
            assignation={"intervention_id": intervention_id, "technicien_id": technicien_id},
        ))
        if horodatage_appareil is not None and reponse["accepte"]:
            reponse["resultat"]["horodatage_appareil"] = horodatage_appareil
        return reponse

    def signaler_report(intervention_id: str, motif: str, horodatage: str) -> dict[str, Any]:
        acteur, verdict_acteur = _acteur_appareil()
        if verdict_acteur is not None:
            return _refus(verdict_acteur)
        verdict_acces = acces.controler_intervention(registre_courant(), intervention_id, acteur)
        if verdict_acces is not None:
            return _refus(verdict_acces)
        return depuis_couple(
            etats.transitionner(intervention_id, "reportee", registre_courant(), horodatage, motif=motif)
        )

    def annuler_intervention(intervention_id: str, horodatage: str) -> dict[str, Any]:
        return depuis_couple(etats.transitionner(intervention_id, "annulee", registre_courant(), horodatage))

    def statut_intervention(intervention_id: str) -> dict[str, Any]:
        acteur, verdict_acteur = _acteur_appareil()
        if verdict_acteur is not None:
            raise ValueError(f"{verdict_acteur['code']} : {verdict_acteur['detail']}")
        reg = registre_courant()
        # PLAN T1.4-k : l'intervention d'un autre n'est pas montrée à un employé — la réponse est
        # celle d'une intervention INCONNUE (statut null), donc indiscernable d'elle.
        if acces.controler_intervention(reg, intervention_id, acteur) is not None:
            return {"intervention_id": intervention_id, "statut": None}
        statut = etats.statut_courant(reg, intervention_id)
        return {"intervention_id": intervention_id, "statut": statut}

    def pointer(
        intervention_id: str, technicien_id: str, action: str, horodatage: str,
        fix_gps: dict[str, Any] | None, attestation: dict[str, Any], fenetre_travail: dict[str, Any],
        referentiel_villes: dict[str, Any], ville: str, sel: str,
    ) -> dict[str, Any]:
        # PLAN T1.4-k : AVANT toute lecture du consentement et toute clé de chiffrement créée (cette
        # dernière écrit) — un employé ne pointe que sous son identifiant, sur SON intervention.
        acteur, verdict_acteur = _acteur_appareil()
        if verdict_acteur is not None:
            return _refus(verdict_acteur)
        verdict_acces = acces.controler_technicien(acteur, technicien_id) or acces.controler_intervention(
            registre_courant(), intervention_id, acteur)
        if verdict_acces is not None:
            return _refus(verdict_acces)

        # T1.4-d (R12 §4, docs/architecture/IDEMPOTENCE.md §5) : pendant un appel d'appareil,
        # l'heure de RÉCEPTION DU SERVEUR fait foi pour la paie — jamais l'horloge de l'appareil
        # (potentiellement déréglée), ni la valeur `horodatage` fournie par l'appelant. L'heure de
        # l'appareil reste lisible À CÔTÉ (affichage seulement, jamais un calcul — pointage.py ne
        # la consulte jamais). Hors appel d'appareil (agent, console) : comportement inchangé,
        # `horodatage` fait foi comme avant T1.4-b. Aucune horloge n'est consultée ici : ces deux
        # valeurs sont déjà celles que la plateforme a fixées (contexte.receptionne_de), jamais le
        # modèle.
        horodatage_appareil_ctx = contexte.horodatage_reception()
        if horodatage_appareil_ctx is not None:
            horodatage_faisant_foi = horodatage_appareil_ctx.recu_le.isoformat()
            horodatage_appareil = horodatage_appareil_ctx.horodatage_appareil.isoformat()
        else:
            horodatage_faisant_foi = horodatage
            horodatage_appareil = None

        # PLAN T4.2 (POLITIQUE-geolocalisation.md §4) : un fix GPS n'est JAMAIS enregistré sans
        # consentement ACTIF — même si l'appelant en fournit un réel, il est ici IGNORÉ (jamais
        # laissé au bon vouloir du client/agent) et le pointage bascule en mode manuel (§4 : « le
        # retrait désactive immédiatement le punch géorépéré ; un mode manuel est proposé »). Le
        # retrait prend donc effet IMMÉDIATEMENT : aucun état mis en cache, `consentement_actif`
        # rejoue le registre à chaque appel.
        reg = registre_courant()
        fix_gps_retenu = fix_gps if consentement.consentement_actif(reg, technicien_id) else None

        # PLAN T4.2 (§5) : le fix retenu est chiffré avant d'entrer dans le registre append-only
        # (retention.py explique pourquoi), avec une clé par technicien obtenue du coffre du
        # socle. Hors registre durable (tests unitaires avec un Registre() en mémoire) : aucune
        # clé disponible, comportement historique préservé (fix en clair) — voir `_cnx_durable`.
        cle_chiffrement_gps = None
        cnx = _cnx_durable()
        if fix_gps_retenu is not None and cnx is not None:
            cle_chiffrement_gps = cles_chiffrement.obtenir_ou_creer(
                cnx, _PORTEE_CLES_GPS, technicien_id, horodatage_faisant_foi,
            )

        return depuis_couple(pointage.enregistrer_pointage(
            intervention_id, technicien_id, action, horodatage_faisant_foi, fix_gps_retenu, attestation,
            {"intervention_id": intervention_id, "technicien_id": technicien_id},
            fenetre_travail, referentiel_villes, ville, sel, reg,
            horodatage_appareil=horodatage_appareil,
            cle_chiffrement_gps=cle_chiffrement_gps,
        ))

    def definir_consentement_gps(
        technicien_id: str, action: str, horodatage: str, version_politique: str, preuve: dict[str, Any],
    ) -> dict[str, Any]:
        # PLAN T1.4-k (POLITIQUE-geolocalisation §4, §7) : l'employé donne ou retire SON consentement
        # depuis l'app, jamais celui d'un autre ; l'admin, lui, consigne celui d'un technicien
        # (consentement « par écrit »). Le retrait prend effet immédiatement, sur la valeur d'un
        # appareil comme sur celle d'un agent (consentement.consentement_actif rejoue le registre).
        acteur, verdict_acteur = _acteur_appareil()
        if verdict_acteur is not None:
            return _refus(verdict_acteur)
        verdict_acces = acces.controler_technicien(acteur, technicien_id)
        if verdict_acces is not None:
            return _refus(verdict_acces)
        # T1.4-d (même patron que m4_pointer) : pendant un appel d'appareil, l'heure de RÉCEPTION DU
        # SERVEUR fait foi — un retrait de consentement prend effet à cet instant, pas à l'heure
        # d'une horloge d'appareil qui peut avoir dérivé. Hors appel d'appareil : `horodatage` fait foi.
        reception = contexte.horodatage_reception()
        horodatage_faisant_foi = reception.recu_le.isoformat() if reception is not None else horodatage
        return depuis_couple(consentement.enregistrer_consentement(
            technicien_id, action, horodatage_faisant_foi, version_politique, preuve, registre_courant(),
        ))

    def lire_position_gps(ligne_id: str, accede_par: str, horodatage: str) -> dict[str, Any]:
        """§7 (droit d'accès) : déchiffre un fix déjà écrit tant que sa clé existe. §6 : journalise
        CET accès (succès ou non) dans le même registre append-only, jamais la position elle-même."""
        # PLAN T1.4-k (§6) : le journal d'accès nomme la personne AUTHENTIFIÉE qui consulte, jamais
        # celle qu'un appelant écrit dans `accede_par`.
        acteur, verdict_acteur = _acteur_appareil()
        if verdict_acteur is not None:
            return _refus(verdict_acteur)
        verdict_acces = acces.controler_consultant(acteur, accede_par)
        if verdict_acces is not None:
            return _refus(verdict_acces)
        reg = registre_courant()
        maillon = next(
            (m for m in reg.lire()
             if m.get("ligne_id") == ligne_id and m.get("type_entree") == pointage.TYPE_POINTAGE),
            None,
        )
        if maillon is None:
            return {"accepte": False, "verdict": verdicts.construire_verdict(
                "REJ-POSITION-INTROUVABLE", detail=f"ligne_id introuvable ou pas un pointage : {ligne_id}")}

        technicien_id = maillon["technicien_id"]
        if maillon.get("gps_chiffre") is not True:
            resultat_journal = "introuvable"
            reponse: dict[str, Any] = {"accepte": False, "verdict": verdicts.construire_verdict(
                "REJ-POSITION-INTROUVABLE",
                detail="ce maillon ne porte aucune position chiffrée (mode manuel, ou pointage en clair)")}
        else:
            cnx = _cnx_durable()
            cle = cles_chiffrement.lire(cnx, _PORTEE_CLES_GPS, technicien_id) if cnx is not None else None
            if cle is None:
                resultat_journal = "position_detruite"
                reponse = {"accepte": False, "verdict": verdicts.construire_verdict(
                    "REJ-POSITION-DETRUITE",
                    detail="clé détruite par une purge de rétention (POLITIQUE-geolocalisation.md §5)")}
            else:
                nonce = retention.nonce_position(
                    maillon["intervention_id"], technicien_id, maillon["action"], maillon["horodatage"])
                lat, lon = retention.dechiffrer_position(cle, nonce, maillon["position_chiffree"])
                resultat_journal = "dechiffre"
                reponse = {"accepte": True, "resultat": {"latitude": lat, "longitude": lon}}
        reg.ajouter(retention.construire_maillon_acces(
            technicien_id, ligne_id, accede_par, horodatage, resultat_journal))
        return reponse

    def purger_retention_gps(
        technicien_id: str, fin_contrat_travail: str, horodatage: str, motif: str,
    ) -> dict[str, Any]:
        """N5 (ADR-0009 §4/§5, AGENTS.md « frontières humaines T3 ») : PROPOSE seulement — une
        suppression définitive ne s'exécute jamais pour un agent seul, voir ``m4_purger_retention_gps``
        ci-dessous (Autonomie.T3) et ``opsys.approbations.decider`` (signature nathan_owner PLUS
        attestation du professionnel concerné)."""
        reg = registre_courant()
        accuse_eligibilite, verdict = retention.evaluer_eligibilite_purge(
            reg, technicien_id, fin_contrat_travail, horodatage)
        if verdict is not None:
            return {"accepte": False, "verdict": verdict}
        if not isinstance(motif, str) or motif.strip() == "":
            return {"accepte": False, "verdict": verdicts.construire_verdict(
                "REJ-CHAMP-VIDE", detail="motif obligatoire : pourquoi cette purge maintenant")}
        cnx = _cnx_durable()
        if cnx is None:
            # Ne devrait jamais survenir en production (executer_atomique/decider ouvrent toujours
            # une transaction sur le registre durable) : fail-closed plutôt qu'une purge qui ne
            # détruirait rien en silence.
            return {"accepte": False, "verdict": verdicts.construire_verdict(
                "REJ-CONTRAT-INVALIDE", detail="aucune connexion durable : purge refusée")}
        cle_detruite = cles_chiffrement.detruire(cnx, _PORTEE_CLES_GPS, technicien_id)
        reg.ajouter(retention.construire_maillon_purge(
            technicien_id, fin_contrat_travail, horodatage, motif, cle_detruite))
        return {"accepte": True, "resultat": {**accuse_eligibilite, "motif": motif, "cle_detruite": cle_detruite}}

    def creer_demande_ecart(
        intervention_id: str, version_prevue: dict[str, Any], version_declaree: dict[str, Any], horodatage: str,
    ) -> dict[str, Any]:
        acteur, verdict_acteur = _acteur_appareil()
        if verdict_acteur is not None:
            return _refus(verdict_acteur)
        verdict_acces = acces.controler_intervention(registre_courant(), intervention_id, acteur)
        if verdict_acces is not None:
            return _refus(verdict_acces)
        return depuis_couple(ecarts.creer_demande_ecart(
            intervention_id, version_prevue, version_declaree, horodatage, registre_courant()
        ))

    def resoudre_demande(demande_id: str, decision: str, horodatage: str, motif: str | None = None) -> dict[str, Any]:
        return depuis_couple(ecarts.resoudre_demande(demande_id, decision, horodatage, registre_courant(), motif=motif))

    def resoudre_revue_completion(
        intervention_id: str, decision: str, horodatage: str, motif: str,
    ) -> dict[str, Any]:
        # PLAN T1.3-b : niveau N4 (déclaré sur l'Outil ci-dessous) — un agent PROPOSE, la
        # signature (personne, rôle) appartient au socle (opsys.approbations.decider), jamais à
        # cette fonction pure : voir outbox.resoudre_revue_completion.
        return depuis_couple(outbox.resoudre_revue_completion(
            intervention_id, decision, horodatage, registre_courant(), motif=motif,
        ))

    def lister_pending_review(type_demande: str | None = None) -> list[dict[str, Any]]:
        return ecarts.lister_pending_review(registre_courant(), type_demande=type_demande)

    def volumetrie_pending_review() -> dict[str, Any]:
        return ecarts.volumetrie_pending_review(registre_courant())

    def deposer_fichier(
        empreinte_sha256: str, taille_octets: int, type_mime: str,
        index_bloc: int, nombre_blocs: int, bloc_base64: str,
    ) -> dict[str, Any]:
        # T1.4-e2 : dépôt de fichiers adressé par contenu (opsys.fichiers, socle, département-
        # agnostique). Idempotence de l'appareil (T1.4-b) : chaque bloc est un appel d'outil
        # distinct — s'il porte sa propre `opsys/idempotencyKey`, le socle (Capacites.
        # _appeler_idempotent) réclame et rejoue AUTOUR de cet appel, sans rien changer ici ;
        # `opsys.fichiers.deposer_bloc` reste idempotent de son propre chef pour un renvoi qui
        # arriverait sans cette clé (reprise après redémarrage de l'app, ex.).
        # PLAN T1.4-k : ce dépôt ne porte AUCUNE intervention (un fichier est adressé par son contenu,
        # opsys.fichiers) — il n'y a donc pas d'assignation à contrôler ici ; on exige seulement que
        # l'identité du jeton soit confirmée en base, pour qu'une personne désactivée ne dépose plus.
        _, verdict_acteur = _acteur_appareil()
        if verdict_acteur is not None:
            return _refus(verdict_acteur)
        cnx = stockage.connexion_courante()
        if cnx is None:
            # Ne devrait jamais survenir en production (executer_atomique ouvre toujours une
            # transaction sur le registre durable, même patron que purger_retention_gps
            # ci-dessus) : fail-closed plutôt qu'un dépôt qui n'écrirait rien en silence.
            return {"accepte": False, "verdict": verdicts.construire_verdict(
                "REJ-CONTRAT-INVALIDE", detail="aucune connexion durable : dépôt de fichier refusé")}
        resultat = fichiers.deposer_bloc(
            cnx, empreinte_sha256, taille_octets, type_mime, index_bloc, nombre_blocs, bloc_base64,
            recu_le=_horodatage_depot_fichier(),
        )
        return _depuis_depot_fichier(resultat)

    def etat_fichier(empreinte_sha256: str) -> dict[str, Any]:
        _, verdict_acteur = _acteur_appareil()  # PLAN T1.4-k : identité confirmée, comme le dépôt
        if verdict_acteur is not None:
            return _refus(verdict_acteur)
        if not fichiers.empreinte_valide(empreinte_sha256):
            return {"accepte": False, "verdict": verdicts.construire_verdict(
                "REJ-FICHIER-PARAMETRES-INVALIDES",
                detail="empreinte_sha256 doit être 64 caractères hexadécimaux minuscules")}
        # Lecture pure : contrairement à deposer_fichier (une écriture, fail-closed sans
        # connexion), un point de sauvegarde imbriqué sur une transaction déjà ouverte, ou une
        # transaction fraîche sinon (stockage.transaction() gère les deux), suffit toujours.
        with stockage.transaction() as cnx:
            etat_lu = fichiers.etat(cnx, empreinte_sha256)
        return {"accepte": True, "resultat": {
            "existe": etat_lu.existe, "complet": etat_lu.complet,
            "blocs_recus": list(etat_lu.blocs_recus), "reference": etat_lu.reference,
        }}

    def completer_intervention(
        intervention_id: str, horodatage: str,
        preuves_completion: dict[str, Any], signature_requise: bool = False,
        photos: Any = outbox.NON_FOURNI, description_factuelle: Any = outbox.NON_FOURNI,
        consentement_marketing: Any = outbox.NON_FOURNI, client_satisfait: Any = outbox.NON_FOURNI,
        consentement_demande_avis: Any = outbox.NON_FOURNI,
        consentement_version_texte: Any = outbox.NON_FOURNI,
    ) -> dict[str, Any]:
        # T1.2-f : photos/description_factuelle/consentement_marketing/client_satisfait sont
        # des faits du CLIENT (Loi 25) — un agent ne peut JAMAIS les affirmer, même principe
        # que ecart_detecte déjà retiré du schéma de cet outil. Ils ne sont acceptés que
        # PENDANT un appel d'appareil (opsys.contexte.horodatage_reception() non None, socle
        # T1.4-b, docs/architecture/IDEMPOTENCE.md) : leur seule PRÉSENCE hors d'un tel appel
        # est un refus nommé — AVANT même de valider les preuves, rien n'est écrit ni publié.
        # PLAN T1.5-d : il en va de même de consentement_demande_avis (le client accepte qu'on lui
        # demande un avis) et de consentement_version_texte (le texte que l'app lui a présenté).
        # PLAN T1.4-k : un employé ne termine que SON intervention (avant toute autre lecture).
        acteur, verdict_acteur = _acteur_appareil()
        if verdict_acteur is not None:
            return _refus(verdict_acteur)
        verdict_acces = acces.controler_intervention(registre_courant(), intervention_id, acteur)
        if verdict_acces is not None:
            return _refus(verdict_acces)

        champs_client_fournis = any(
            v is not outbox.NON_FOURNI
            for v in (
                photos, description_factuelle, consentement_marketing, client_satisfait,
                consentement_demande_avis, consentement_version_texte,
            )
        )
        if champs_client_fournis and contexte.horodatage_reception() is None:
            return {
                "accepte": False,
                "verdict": verdicts.construire_verdict(
                    "REJ-CHAMPS-CLIENT-HORS-APPAREIL",
                    detail=(
                        "photos/description_factuelle/consentement_marketing/client_satisfait/"
                        "consentement_demande_avis/consentement_version_texte "
                        "ne sont acceptés que pendant un appel d'appareil (Loi 25) : un agent "
                        "ne peut jamais les affirmer à la place du client"
                    ),
                ),
            }
        preuve_consentement, verdict_consentement = _preuve_consentement_client(
            acteur, consentement_marketing, consentement_demande_avis, consentement_version_texte,
        )
        if verdict_consentement is not None:
            return _refus(verdict_consentement)

        # Contrat PreuvesCompletion (T1.1-b#3) : validé AVANT tout appel à
        # l'outbox — aucune écriture si le dossier de preuves est incomplet.
        ok, verdict = preuves.valider_preuves_completion(preuves_completion, signature_requise)
        if not ok:
            return {"accepte": False, "verdict": verdict}
        # T1.4-e2 : chaque référence de preuve (photos_apres, et signature si requise) doit
        # désigner un fichier RÉELLEMENT déposé et complet — une chaîne inventée passait avant ce
        # point. Fail-closed, APRÈS la validation structurelle (ordre épinglé comme dans
        # preuves.py), toujours AVANT l'outbox : aucune écriture si une référence ne résout à rien.
        verdict = _verifier_preuves_fichiers(preuves_completion, signature_requise)
        if verdict is not None:
            return {"accepte": False, "verdict": verdict}
        # PLAN T1.5-c — même patron que m4_pointer et m4_demarrer_route (T1.4-d, R12 §4) : pendant
        # un appel d'appareil, l'heure de RÉCEPTION DU SERVEUR date la complétion, jamais l'horloge
        # (potentiellement déréglée) de l'appareil ni la valeur `horodatage` fournie. Le `wct_id`
        # (empreinte de l'intervention et de cette heure) ne dépend donc plus du téléphone. L'heure
        # d'appareil reste lisible À CÔTÉ, sur l'accusé, jamais consultée pour un calcul. Hors
        # appel d'appareil (agent, console) : `horodatage` fait foi, comportement inchangé.
        reception = contexte.horodatage_reception()
        if reception is not None:
            horodatage_faisant_foi = reception.recu_le.isoformat()
            horodatage_appareil = reception.horodatage_appareil.isoformat()
        else:
            horodatage_faisant_foi = horodatage
            horodatage_appareil = None

        # PLAN T1.5-c — deux faits distincts, jamais confondus :
        #  - la vérification n'est pas terminée : le matériel n'est pas encore comparé au prévu à ce
        #    stade (le formulaire des matériaux suit, §9.7) et un agent ne peut pas affirmer que tout
        #    est conforme. La complétion reste donc à revoir (DEFINITION-PRODUIT §6 : « s'il manque
        #    quelque chose ») ; completed_verified viendra du code (variance M6 et preuves, PLAN T1.2)
        #    ou d'une décision humaine (T1.3). C'est `verification_en_attente`, toujours vrai ici ;
        #  - un écart MÉTIER est connu : une demande d'écart ouverte sur cette intervention, lue au
        #    registre (`ecarts.ecart_metier_ouvert`). Seule source d'écart que M4 possède à cet
        #    instant : la variance des matériaux, elle, n'existe pas encore (M6, après la complétion).
        #    `wct.ecart_signale` ne vaut donc plus vrai « par précaution ».
        reg = registre_courant()
        accuse, verdict = outbox.completer_intervention(
            intervention_id, horodatage_faisant_foi, reg,
            ecart_detecte=ecarts.ecart_metier_ouvert(reg, intervention_id),
            verification_en_attente=True,
            photos=photos, description_factuelle=description_factuelle,
            consentement_marketing=consentement_marketing, client_satisfait=client_satisfait,
            consentement_demande_avis=consentement_demande_avis, **preuve_consentement,
        )
        if verdict is not None:
            return {"accepte": False, "verdict": verdict}
        if horodatage_appareil is not None:
            accuse["horodatage_appareil"] = horodatage_appareil
        # T1.2-b : publie m4.travaux_termines DANS LA MÊME TRANSACTION que le WCT qui vient
        # d'être écrit ci-dessus — `evenements.publier` ouvre un POINT DE SAUVEGARDE sur la
        # transaction déjà ouverte par `executer_atomique` (ADR-0009), jamais une transaction
        # indépendante ; un refus plus loin dans l'appelant annule les deux écritures ensemble.
        # Gardé par `stockage.connexion_courante() is not None` (même garde que
        # `m6_material_control.outils._registre_de_l_appel`) : seule la production (registre
        # durable, appel enveloppé par `executer_atomique`/`Capacites.appeler`) publie ; les
        # tests unitaires de ce fichier, qui injectent un `registre.Registre()` EN MÉMOIRE et
        # appellent `executer()` sans transaction, ne touchent jamais la base — publier quand
        # même y ouvrirait une transaction hors de propos pour un WCT qui n'existe que dans un
        # objet Python local, jamais dans `evenements_sortants`.
        if stockage.connexion_courante() is not None:
            wct = next(
                m[outbox.CLE_WCT] for m in reg.lire()
                if m.get("ligne_id") == accuse["ligne_id"]
            )
            evenements.publier(
                "m4.travaux_termines", _DEPARTEMENT, wct, evenement_id=wct["wct_id"],
            )
        return {"accepte": True, "resultat": accuse}

    def lire_outbox(depuis_index: int = 0) -> list[dict[str, Any]]:
        return [{"index": i, "wct": w} for i, w in outbox.lire_outbox(registre_courant(), depuis_index)]

    def notifier_client_completion(intervention_id: str) -> dict[str, Any]:
        """Prépare le brouillon de message client (T2) : jamais GPS/technicien/lead_id en clair."""
        wct = None
        for _, candidat in outbox.lire_outbox(registre_courant()):
            if candidat["intervention_id"] == intervention_id:
                wct = candidat
        if wct is None:
            raise ValueError(f"aucun WCT trouvé pour l'intervention {intervention_id}")
        return {
            "intervention_id": intervention_id,
            "message_client": (
                "Votre intervention est terminée. Merci de votre confiance."
            ),
            "horodatage_completion": wct["horodatage_completion"],
            "duree_reelle_minutes": wct["duree_reelle_minutes"],
        }

    def produire_digest(date_cible: str, horodatage_reference: str) -> dict[str, Any]:
        return depuis_couple(digest.produire_digest(registre_courant(), date_cible, horodatage_reference))

    def lister_interventions(statut: str | None = None) -> list[dict[str, Any]]:
        acteur, verdict_acteur = _acteur_appareil()
        if verdict_acteur is not None:
            raise ValueError(f"{verdict_acteur['code']} : {verdict_acteur['detail']}")
        # PLAN T1.4-k : l'employé ne voit que les interventions qui lui sont assignées ; l'admin et
        # les agents voient toutes (hors appel d'appareil : comportement inchangé).
        return acces.interventions_visibles(
            etats.lister_interventions(registre_courant(), statut=statut), acteur)

    def produire_brouillon_temps(
        periode: dict[str, Any], seuil_minutes: int | None = None,
    ) -> dict[str, Any]:
        return depuis_couple(
            temps.produire_brouillon_temps(registre_courant(), periode, seuil_minutes=seuil_minutes)
        )

    def proposer_localisation(adresse: Any, chantier_id: str | None = None) -> dict[str, Any]:
        """Lecture seule : cherche l'adresse dans l'index RQA LOCAL (aucun réseau) et PROPOSE, sans rien
        écrire. Rien n'est une confirmation : la position n'entre au registre que par
        ``m4_confirmer_localisation``."""
        acteur, verdict_acteur = _acteur_appareil()
        if verdict_acteur is not None:
            return _refus(verdict_acteur)
        verdict_role = acces.controler_administrateur(acteur)
        if verdict_role is not None:
            return _refus(verdict_role)
        if chantier_id is not None and (not isinstance(chantier_id, str) or chantier_id.strip() == ""):
            return _refus(verdicts.construire_verdict("REJ-CHAMP-VIDE", detail="chantier_id vide"))
        # Adresse d'abord : une adresse illisible se dit telle, même quand l'index manque aussi.
        _, verdict_adresse = localisation.analyser_adresse(adresse)
        if verdict_adresse is not None:
            return _refus(verdict_adresse)
        index, verdict_index = localisation.ouvrir_index(_chemin_index_rqa())
        if verdict_index is not None:
            return _refus(verdict_index)
        try:
            resultat, verdict = localisation.proposer(index, adresse)
        finally:
            index.fermer()
        if verdict is not None:
            reponse: dict[str, Any] = {"accepte": False, "verdict": verdict, **(resultat or {})}
        else:
            reponse = {"accepte": True, "resultat": resultat}
        if chantier_id is not None:
            # Métadonnées seulement (version, source, précision, signataire) : aucune coordonnée déchiffrée.
            reponse["confirmation_actuelle"] = localisation.confirmation_courante(registre_courant(), chantier_id)
        return reponse

    def confirmer_localisation(
        chantier_id: str, action: str, horodatage: str, confirme_par: str,
        adresse: Any = None, source: str | None = None, rqa_identifiant: str | None = None,
        latitude_microdegres: int | None = None, longitude_microdegres: int | None = None, motif: str = "",
    ) -> dict[str, Any]:
        """Écrit le maillon ``localisation_chantier`` (coordonnées chiffrées, versionné). Toutes les
        vérifications précèdent la moindre écriture, clé de chiffrement comprise : un refus ne laisse rien."""
        acteur, verdict_acteur = _acteur_appareil()
        if verdict_acteur is not None:
            return _refus(verdict_acteur)
        verdict_acces = acces.controler_administrateur(acteur) or acces.controler_confirmant(acteur, confirme_par)
        if verdict_acces is not None:
            return _refus(verdict_acces)
        # Même patron que m4_pointer (T1.4-d) : pendant un appel d'appareil, l'heure de RÉCEPTION DU
        # SERVEUR fait foi, jamais l'horloge de l'appareil ni l'`horodatage` fourni.
        reception = contexte.horodatage_reception()
        horodatage_faisant_foi = reception.recu_le.isoformat() if reception is not None else horodatage
        index = None
        if action == "confirmee" and source == "rqa":
            index, verdict_index = localisation.ouvrir_index(_chemin_index_rqa())
            if verdict_index is not None:
                return _refus(verdict_index)
        cnx = _cnx_durable()
        # Sans base durable, aucune clé ne peut exister : la confirmation est refusée (jamais écrite en clair).
        fournir_cle = None if cnx is None else partial(
            cles_chiffrement.obtenir_ou_creer, cnx, localisation.PORTEE_CLES_LOCALISATION, chantier_id,
            horodatage_faisant_foi,
        )
        try:
            reponse = depuis_couple(localisation.confirmer(
                registre_courant(), chantier_id, action, horodatage_faisant_foi, confirme_par,
                adresse=adresse, source=source, rqa_identifiant=rqa_identifiant,
                latitude_microdegres=latitude_microdegres, longitude_microdegres=longitude_microdegres,
                motif=motif, index=index, fournir_cle=fournir_cle,
            ))
        finally:
            if index is not None:
                index.fermer()
        if reception is not None and reponse["accepte"]:
            reponse["resultat"]["horodatage_appareil"] = reception.horodatage_appareil.isoformat()
        return reponse

    def proposer_cedule(
        horodatage: str, equipes: list[dict[str, Any]] | None = None,
        durees_par_type_travaux: dict[str, Any] | None = None,
        competences_par_type_travaux: dict[str, Any] | None = None,
        chantiers: list[dict[str, Any]] | None = None, parametres: dict[str, Any] | None = None,
        intervention_ids: list[str] | None = None, moteur: str = "auto",
        durees_par_service: dict[str, Any] | None = None,
        competences_par_service: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Propose un plan de tournées et le range au registre (maillon ``cedule_proposee``) : un brouillon,
        aucune assignation. Équipes, dépôt, quarts, durées et réglages viennent du profil des équipes de
        l'entreprise (PLAN T4.12) ; un argument donné le REMPLACE (surcharge tracée dans ``provenance``). Ce que ni le
        profil ni un argument ne donne est un verdict « à fournir » qui dit aussi où le déclarer."""
        acteur, verdict_acteur = _acteur_appareil()
        if verdict_acteur is not None:
            return _refus(verdict_acteur)
        verdict_role = acces.controler_administrateur(acteur)
        if verdict_role is not None:
            return _refus(verdict_role)
        # Même patron que m4_confirmer_localisation : l'heure de RÉCEPTION DU SERVEUR fait foi.
        reception = contexte.horodatage_reception()
        horodatage_faisant_foi = reception.recu_le.isoformat() if reception is not None else horodatage
        reponse = depuis_couple(cedule_tournees.proposer(
            registre_courant(),
            {
                "equipes": equipes, "durees_par_type_travaux": durees_par_type_travaux,
                "competences_par_type_travaux": competences_par_type_travaux,
                "durees_par_service": durees_par_service,
                "competences_par_service": competences_par_service, "chantiers": chantiers,
                "parametres": parametres, "intervention_ids": intervention_ids,
            },
            lire_localisation_confirmee, horodatage_faisant_foi,
            propose_par=None if acteur is None else acteur.personne,
            fournisseur=fournisseur_matrice, moteur=moteur, lire_equipes=_lecteur_equipes(),
        ))
        if reception is not None and reponse["accepte"]:
            reponse["resultat"]["horodatage_appareil"] = reception.horodatage_appareil.isoformat()
        return reponse

    def appliquer_cedule(plan_id: str, horodatage: str, confirme_par: str) -> dict[str, Any]:
        """Applique un plan PROPOSÉ par ``etats.assigner_technicien``, après avoir revérifié l'état, les
        coordonnées d'aujourd'hui et ``tournees.verifier_plan``. Toutes les vérifications précèdent la
        première écriture ; un refus ne laisse rien."""
        acteur, verdict_acteur = _acteur_appareil()
        if verdict_acteur is not None:
            return _refus(verdict_acteur)
        verdict_acces = acces.controler_administrateur(acteur) or acces.controler_confirmant(acteur, confirme_par)
        if verdict_acces is not None:
            return _refus(verdict_acces)
        reception = contexte.horodatage_reception()
        horodatage_faisant_foi = reception.recu_le.isoformat() if reception is not None else horodatage
        reponse = depuis_couple(cedule_tournees.appliquer(
            registre_courant(), plan_id, lire_localisation_confirmee, horodatage_faisant_foi, confirme_par,
            fournisseur=fournisseur_matrice, lire_equipes=_lecteur_equipes(),
        ))
        if reception is not None and reponse["accepte"]:
            reponse["resultat"]["horodatage_appareil"] = reception.horodatage_appareil.isoformat()
        return reponse

    def verifier_preparation(intervention_id: str) -> dict[str, Any]:
        """Lecture seule : la préparation d'une intervention (M4.6), volet par volet, avec ce qui manque. Rien n'est
        écrit ; aucun volet non vérifié n'est présenté comme prêt."""
        acteur, verdict_acteur = _acteur_appareil()
        if verdict_acteur is not None:
            return _refus(verdict_acteur)
        verdict_role = acces.controler_administrateur(acteur)
        if verdict_role is not None:
            return _refus(verdict_role)
        return depuis_couple(
            preparation.evaluer(
                registre_courant(), intervention_id, lire_localisation_confirmee, _lecteur_equipes(),
            )
        )

    return (
        Outil(
            nom="m4_planifier_intervention",
            description=(
                "Inscrit une intervention à partir d'un lead M2 qualifié PUIS calcule sa cédule "
                "(technicien, fenêtre horaire) en un seul appel. Bloque avec un verdict nommé si "
                "le contrat ou le marqueur de readiness est invalide. T1.4-k : le technicien de la "
                "cédule est CONSIGNÉ au registre (maillon assignation_technicien) ; c'est lui, et "
                "lui seul parmi les employés, qui pourra partir, pointer et terminer. Pour un "
                "employé, techniciens_disponibles contient donc des identifiants de PERSONNES OPSYS "
                "(l'identifiant de technicien EST celui de la personne)."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "contrat": _CONTRAT, "marqueur": _MARQUEUR,
                    "horodatage": {"type": "string"}, "sel": {"type": "string"},
                    "techniciens_disponibles": {"type": "array", "items": {"type": "string"}},
                    "fenetres_disponibles": {"type": "array", "items": _FENETRE},
                    "devis_id": {
                        "type": ["string", "null"],
                        "description": "Identifiant du devis M3 accepté, si déjà connu. Omis, reste null.",
                    },
                },
                "required": ["contrat", "marqueur", "horodatage", "sel",
                             "techniciens_disponibles", "fenetres_disponibles"],
                "additionalProperties": False,
            },
            fonction=planifier_intervention,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m4_demarrer_route",
            description=(
                "Fait passer une intervention planifiee -> en_route : exige l'assignation "
                "effective d'un technicien (PRD §4), jamais un départ fictif. T1.4-k, appel "
                "d'appareil d'un employé : seulement sur une intervention qui lui est assignée "
                "(REJ-INTERVENTION-NON-ASSIGNEE) et sous son propre identifiant ; un technicien_id "
                "différent de la personne authentifiée est refusé (REJ-IDENTITE-FOURNIE-DIFFERENTE), "
                "jamais remplacé en silence. L'admin dispatche pour les autres."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "intervention_id": {"type": "string"}, "technicien_id": {"type": "string"},
                    "horodatage": {"type": "string"},
                },
                "required": ["intervention_id", "technicien_id", "horodatage"],
                "additionalProperties": False,
            },
            fonction=demarrer_route,
            autonomie=Autonomie.T1,
            # §9.3 exécution (« en route »). Employé : sa propre intervention, sous son identifiant (T1.4-k).
            roles_appareil=frozenset({"employee", "admin"}),
        ),
        Outil(
            nom="m4_signaler_report",
            description=(
                "Reporte une intervention (client_absent, meteo ou decision_admin). T1.4-k, appel "
                "d'appareil d'un employé : seulement sur une intervention qui lui est assignée "
                "(REJ-INTERVENTION-NON-ASSIGNEE)."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "intervention_id": {"type": "string"},
                    "motif": {"type": "string", "enum": list(etats.MOTIFS_REPORT)},
                    "horodatage": {"type": "string"},
                },
                "required": ["intervention_id", "motif", "horodatage"],
                "additionalProperties": False,
            },
            fonction=signaler_report,
            autonomie=Autonomie.T1,
            # §9.3 exécution (client absent, météo) ; le motif `decision_admin` reste celui de l'admin.
            roles_appareil=frozenset({"employee", "admin"}),
        ),
        Outil(
            nom="m4_annuler_intervention",
            description="Annule une intervention planifiee ou en_route (avant tout pointage validé).",
            parametres={
                "type": "object",
                "properties": {"intervention_id": {"type": "string"}, "horodatage": {"type": "string"}},
                "required": ["intervention_id", "horodatage"],
                "additionalProperties": False,
            },
            fonction=annuler_intervention,
            autonomie=Autonomie.T1,
        ),
        Outil(
            nom="m4_statut_intervention",
            description=(
                "Lit le statut courant d'une intervention (rejoue le registre). T1.4-k, appel "
                "d'appareil d'un employé : une intervention qui n'est pas la sienne rend statut null, "
                "comme une intervention inconnue (indiscernable, aucune existence révélée)."
            ),
            parametres={
                "type": "object",
                "properties": {"intervention_id": {"type": "string"}},
                "required": ["intervention_id"],
                "additionalProperties": False,
            },
            fonction=statut_intervention,
            autonomie=Autonomie.T0,
            # §9.3 (chantiers du jour).
            roles_appareil=frozenset({"employee", "admin"}),
        ),
        Outil(
            nom="m4_pointer",
            description=(
                "Enregistre un pointage terrain (arrivee/depart) horodaté et géolocalisé. "
                "Vérifie la cohérence GPS contre le référentiel des villes ET l'assignation "
                "contre celle réellement envoyée en_route (registre) — jamais la seule "
                "déclaration de l'appelant. Route automatiquement vers sur_site ou en_revue. "
                "Pendant un appel d'appareil (T1.4-d) : l'heure de réception du serveur fait foi "
                "pour la paie, quelle que soit la valeur de horodatage fournie ; l'heure de "
                "l'appareil reste lisible mais n'est jamais utilisée pour un calcul. T1.4-k, appel "
                "d'appareil d'un employé : seulement sur SON intervention "
                "(REJ-INTERVENTION-NON-ASSIGNEE) et sous son propre identifiant "
                "(technicien_id différent de la personne authentifiée : REJ-IDENTITE-FOURNIE-DIFFERENTE)."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "intervention_id": {"type": "string"}, "technicien_id": {"type": "string"},
                    "action": {"type": "string", "enum": list(pointage.ACTIONS)},
                    "horodatage": {"type": "string"}, "fix_gps": _FIX_GPS, "attestation": _ATTESTATION,
                    "fenetre_travail": _FENETRE, "referentiel_villes": _REFERENTIEL_VILLES,
                    "ville": {"type": "string"}, "sel": {"type": "string"},
                },
                "required": ["intervention_id", "technicien_id", "action", "horodatage", "fix_gps",
                             "attestation", "fenetre_travail", "referentiel_villes", "ville", "sel"],
                "additionalProperties": False,
            },
            fonction=pointer,
            autonomie=Autonomie.T1,
            # §9.3 (punch). Employé : SON intervention et SON identifiant (T1.4-k, acces.py) ; l'admin
            # pointe pour autrui (dispatch).
            roles_appareil=frozenset({"employee", "admin"}),
        ),
        Outil(
            nom="m4_creer_demande_ecart",
            description=(
                "Ouvre une demande d'écart métier (durée/périmètre/matériaux prévu vs déclaré). "
                "T1.4-k, appel d'appareil d'un employé : seulement sur une intervention qui lui est "
                "assignée (REJ-INTERVENTION-NON-ASSIGNEE)."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "intervention_id": {"type": "string"}, "version_prevue": _VERSION_METIER,
                    "version_declaree": _VERSION_METIER, "horodatage": {"type": "string"},
                },
                "required": ["intervention_id", "version_prevue", "version_declaree", "horodatage"],
                "additionalProperties": False,
            },
            fonction=creer_demande_ecart,
            autonomie=Autonomie.T1,
            # §9.3 (demande de support ou de changement) ; c'est l'admin qui l'arbitre.
            roles_appareil=frozenset({"employee", "admin"}),
        ),
        Outil(
            nom="m4_resoudre_demande",
            description=(
                "Arbitre une demande en attente. validee sur un écart métier complète "
                "l'intervention (WCT) ; validee sur une anomalie de pointage reprend sur_site "
                "(PRD §4) ; rejetee annule toujours l'intervention."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "demande_id": {"type": "string"},
                    "decision": {"type": "string", "enum": list(ecarts.DECISIONS)},
                    "horodatage": {"type": "string"}, "motif": {"type": ["string", "null"]},
                },
                "required": ["demande_id", "decision", "horodatage"],
                "additionalProperties": False,
            },
            fonction=resoudre_demande,
            autonomie=Autonomie.T1,
            # §9.5 M4 (approbation des complétions) ; « validee » sur un écart complète l'intervention.
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m4_resoudre_revue_completion",
            description=(
                "Revue HUMAINE d'une complétion completed_pending_review (PLAN T1.3-b), jamais "
                "un agent seul : decision=verifiee confirme (-> completed_verified, comme le "
                "ferait un signal M6 sans dépassement, mais décidé par une personne) ; "
                "decision=correction NOMME un problème SANS rouvrir le chantier (-> "
                "completed_pending_review, nouveau maillon d'audit ; motif obligatoire, la "
                "décision cite toujours pourquoi). Niveau N4 (écriture finale, ADR-0009 §4) : "
                "cet appel passe par la file d'approbation du socle — il PROPOSE seulement ; "
                "seule une personne dont le rôle figure dans department.yaml/approbations.n4 "
                "peut l'exécuter (opsys approbations decider, signé personne + rôle)."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "intervention_id": {"type": "string"},
                    "decision": {"type": "string", "enum": list(outbox.DECISIONS_REVUE)},
                    "horodatage": {"type": "string"},
                    "motif": {
                        "type": "string",
                        "description": (
                            "Pourquoi cette décision : la confirmation, ou — pour une correction "
                            "— ce qui doit être corrigé. Jamais vide."
                        ),
                    },
                },
                "required": ["intervention_id", "decision", "horodatage", "motif"],
                "additionalProperties": False,
            },
            fonction=resoudre_revue_completion,
            # T1 (écriture interne, registre) : autonomie descriptive. Niveau EXPLICITE N4 plutôt
            # que le défaut T1->N3 (ADR-0009 §4, opsys.outils.niveau_par_defaut) — justification :
            # cette décision produit une ÉCRITURE FINALE (« engagement... écriture finale » de la
            # table ADR-0009 §4) — elle clôt définitivement, ou rouvre nommément, la vérification
            # d'une complétion déjà publiée aux 6 départements consommateurs (m4.travaux_termines) ;
            # contrairement aux autres outils T1 de M4 (pointer, compléter…), qui restent des
            # écritures INTERNES NON FINALES (N3), celle-ci ne l'est jamais : le niveau le plus
            # élevé de la paire l'emporte, pour les DEUX issues (verifiee ET correction), le
            # niveau étant fixé sur l'outil entier, jamais par argument.
            autonomie=Autonomie.T1,
            niveau=Niveau.N4,
            # §9.5 M4 (approbation des complétions), N4 : propose seulement.
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m4_lister_pending_review",
            description="Liste les demandes de revue en attente (écarts métier et anomalies de pointage).",
            parametres={
                "type": "object",
                "properties": {
                    "type_demande": {"type": ["string", "null"], "enum": list(ecarts.TYPES_DEMANDE) + [None]},
                },
                "additionalProperties": False,
            },
            fonction=lister_pending_review,
            autonomie=Autonomie.T0,
            # §9.5 M4 (file de complétion) ; liste les anomalies de pointage de tous : jamais l'employé.
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m4_volumetrie_pending_review",
            description="Compte les demandes en attente, par type (CA-M4-14).",
            parametres={"type": "object", "properties": {}, "additionalProperties": False},
            fonction=volumetrie_pending_review,
            autonomie=Autonomie.T0,
            # §9.5 M4 (file de complétion).
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m4_deposer_fichier",
            description=(
                "Dépose un bloc d'un fichier adressé par contenu (photo après-chantier ou "
                "signature client, T1.4-e2). Idempotent : renvoyer un bloc déjà reçu, à "
                f"l'identique, est un no-op accepté. Bloc de taille FIXE ({fichiers.TAILLE_BLOC_OCTETS} "
                "octets décodés), sauf le dernier bloc du fichier. Quand tous les blocs annoncés "
                "sont là, le contenu assemblé est vérifié (taille, SHA-256, octets magiques du "
                "type annoncé) avant d'être marqué complet ; toute discordance efface les blocs "
                "déjà reçus pour cette empreinte (à redéposer intégralement)."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "empreinte_sha256": _EMPREINTE_SHA256,
                    "taille_octets": {
                        "type": "integer", "minimum": 1, "maximum": fichiers.TAILLE_MAX_OCTETS,
                        "description": "Taille totale déclarée du fichier COMPLET, en octets.",
                    },
                    "type_mime": {"type": "string", "enum": list(fichiers.TYPES_MIME_PERMIS)},
                    "index_bloc": {
                        "type": "integer", "minimum": 0,
                        "description": "Position de ce bloc, 0-indexée, strictement < nombre_blocs.",
                    },
                    "nombre_blocs": {
                        "type": "integer", "minimum": 1, "maximum": fichiers.NOMBRE_BLOCS_MAX,
                    },
                    "bloc_base64": {
                        "type": "string", "description": "Contenu de CE bloc, en base64 standard.",
                    },
                },
                "required": ["empreinte_sha256", "taille_octets", "type_mime", "index_bloc",
                             "nombre_blocs", "bloc_base64"],
                "additionalProperties": False,
            },
            fonction=deposer_fichier,
            autonomie=Autonomie.T1,
            # N2 « tâche interne » (ADR-0009 §4, automatique) et non le défaut T1 -> N3 : déposer
            # un bloc de preuve ne décide rien et n'engage personne ; c'est la complétion qui s'en
            # sert (m4_completer_intervention) qui reste soumise aux approbations. En N3, le mode
            # ombre mettrait chaque bloc d'une photo en attente d'approbation.
            niveau=Niveau.N2,
            # §9.3 (photos, signature du client : les preuves du chantier). Ne porte aucune intervention
            # (adressé par contenu) : T1.4-k n'y contrôle que l'identité confirmée en base.
            roles_appareil=frozenset({"employee", "admin"}),
        ),
        Outil(
            nom="m4_etat_fichier",
            description=(
                "État d'un dépôt de fichier par empreinte SHA-256 (T1.4-e2) : blocs déjà reçus, "
                "complétude, référence si complet — pour reprendre un envoi interrompu sans "
                "retransmettre ce qui est déjà là."
            ),
            parametres={
                "type": "object",
                "properties": {"empreinte_sha256": _EMPREINTE_SHA256},
                "required": ["empreinte_sha256"],
                "additionalProperties": False,
            },
            fonction=etat_fichier,
            autonomie=Autonomie.T0,
            # §9.3 (reprise d'un dépôt de preuve interrompu).
            roles_appareil=frozenset({"employee", "admin"}),
        ),
        Outil(
            nom="m4_completer_intervention",
            description=(
                "Termine une intervention et émet le Work Completion Trigger dans l'outbox, "
                "en une seule écriture atomique (CA-M4-11). Exige le dossier PreuvesCompletion "
                "(checklist, photos après, notes, signature si requise, §6/§9.7) ; chaque "
                "référence photos_apres/signature doit désigner un fichier déposé et complet "
                "(m4_deposer_fichier), sinon REJ-PREUVE-FICHIER-INTROUVABLE. Statut toujours "
                "completed_pending_review (vérification ensuite : variance M6, revue). "
                "En appel d'appareil, l'heure de réception du serveur date la complétion. Durée "
                "réelle tirée des pointages, nette des pauses. Faits CLIENT (Loi 25) : "
                "consentement_marketing, consentement_demande_avis, client_satisfait, photos, "
                "description_factuelle, consentement_version_texte, acceptés SEULEMENT en appel "
                "d'appareil (sinon REJ-CHAMPS-CLIENT-HORS-APPAREIL) ; tout consentement exige la "
                "version du texte, le serveur pose seul qui l'a recueilli et quand. Un employé ne "
                "termine que SON intervention (REJ-INTERVENTION-NON-ASSIGNEE)."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "intervention_id": {"type": "string"}, "horodatage": {"type": "string"},
                    "preuves_completion": _PREUVES_COMPLETION,
                    "signature_requise": {"type": "boolean", "description": "Défaut : faux."},
                    "photos": {
                        "type": "array", "items": {"type": "string"},
                        "description": (
                            "Références de photos après-chantier (jamais de binaire). Fait "
                            "CLIENT (Loi 25) : accepté SEULEMENT pendant un appel d'appareil "
                            "(app mobile), jamais fourni par un agent."
                        ),
                    },
                    "description_factuelle": {
                        "type": "string",
                        "description": (
                            "Description factuelle du chantier. Fait CLIENT (Loi 25) : accepté "
                            "SEULEMENT pendant un appel d'appareil, jamais fourni par un agent."
                        ),
                    },
                    "consentement_marketing": {
                        "type": "boolean",
                        "description": (
                            "Consentement explicite du client à un usage marketing de photos "
                            "(Loi 25), jamais déduit. Accepté SEULEMENT pendant un appel "
                            "d'appareil, jamais fourni ni affirmé par un agent. Exige "
                            "consentement_version_texte."
                        ),
                    },
                    "consentement_demande_avis": {
                        "type": "boolean",
                        "description": (
                            "Consentement explicite du client à être contacté pour laisser un "
                            "avis (Loi 25), DISTINCT de consentement_marketing, jamais déduit "
                            "de l'un ni de l'autre. Accepté SEULEMENT pendant un appel "
                            "d'appareil. Absent = non consenti. Exige consentement_version_texte."
                        ),
                    },
                    "consentement_version_texte": {
                        "type": "string",
                        "pattern": _FORMAT_VERSION_TEXTE_CONSENTEMENT,
                        "description": (
                            "Identifiant de la version du texte de consentement présenté au "
                            "client. Exigé avec tout consentement, refusé sans. Qui l'a recueilli "
                            "et quand : posés par le serveur (personne authentifiée, heure de "
                            "réception), jamais fournis ici."
                        ),
                    },
                    "client_satisfait": {
                        "type": ["boolean", "null"],
                        "description": (
                            "Signal de satisfaction du client ; null si demandé mais non "
                            "recueilli (jamais inventé). Fait CLIENT (Loi 25) : accepté "
                            "SEULEMENT pendant un appel d'appareil, jamais fourni par un agent."
                        ),
                    },
                },
                "required": ["intervention_id", "horodatage", "preuves_completion"],
                "additionalProperties": False,
            },
            fonction=completer_intervention,
            autonomie=Autonomie.T1,
            # §9.3 et §9.7 (« Terminer »).
            roles_appareil=frozenset({"employee", "admin"}),
        ),
        Outil(
            nom="m4_lire_outbox",
            description="Lit les Work Completion Trigger émis depuis un index (pour les modules aval).",
            parametres={
                "type": "object",
                "properties": {"depuis_index": {"type": "integer"}},
                "additionalProperties": False,
            },
            fonction=lire_outbox,
            autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m4_notifier_client_completion",
            description=(
                "Prépare le message de confirmation de fin de travaux pour le client, à partir "
                "du WCT (jamais de GPS, technicien ou identifiant interne exposé). Action externe "
                "réversible : approbation requise en mode ombre/supervisé."
            ),
            parametres={
                "type": "object",
                "properties": {"intervention_id": {"type": "string"}},
                "required": ["intervention_id"],
                "additionalProperties": False,
            },
            fonction=notifier_client_completion,
            autonomie=Autonomie.T2,
        ),
        Outil(
            nom="m4_produire_digest",
            description=(
                "Digest quotidien déterministe (interventions complétées, en revue, volumétrie "
                "de la file) pour une date cible, hash-chaîné."
            ),
            parametres={
                "type": "object",
                "properties": {"date_cible": {"type": "string"}, "horodatage_reference": {"type": "string"}},
                "required": ["date_cible", "horodatage_reference"],
                "additionalProperties": False,
            },
            fonction=produire_digest,
            autonomie=Autonomie.T0,
            # §9.5 M4 (dispatch du jour, retards, file de complétion).
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m4_lister_interventions",
            description=(
                "Liste les interventions connues (id, statut, lead, type de travaux ou service, "
                "devis), sans aucune donnée de contact. Filtre optionnel par statut. T1.4-e2 (écran "
                "« chantiers du jour ») : porte aussi technicien_assigne (dernier technicien_id "
                "d'une transition en_route, ou celui de la cédule consignée par "
                "m4_planifier_intervention s'il est plus récent, sinon null) et fenetre_planifiee "
                "(toujours null aujourd'hui : le registre ne la porte pas encore, jamais inventée). "
                "T1.4-k, appel d'appareil d'un employé : SEULEMENT les interventions qui lui sont "
                "assignées ; l'admin (et un agent) voient toutes."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "statut": {"type": ["string", "null"], "enum": list(etats.ETATS) + [None]},
                },
                "additionalProperties": False,
            },
            fonction=lister_interventions,
            autonomie=Autonomie.T0,
            # §9.3 (chantiers du jour). Employé : filtré à SES interventions (T1.4-k, acces.py) ; l'admin
            # voit toutes celles du dispatch.
            roles_appareil=frozenset({"employee", "admin"}),
        ),
        Outil(
            nom="m4_produire_brouillon_temps",
            description=(
                "Brouillon de temps agrégé par intervention complétée, pour une période "
                "(minutes travaillées, déplacement, pause) — aucun taux ni montant, M5 validera "
                "la paie. Signale un dépassement d'heures par technicien si seuil_minutes est fourni. "
                "Calcule depuis l'heure qui fait foi de chaque pointage (T1.4-d) : quand un "
                "pointage a été reçu pendant un appel d'appareil, c'est l'heure de réception du "
                "serveur, jamais l'horloge de l'appareil, qui a déjà été retenue à l'écriture."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "periode": _PERIODE,
                    "seuil_minutes": {"type": ["integer", "null"]},
                },
                "required": ["periode"],
                "additionalProperties": False,
            },
            fonction=produire_brouillon_temps,
            autonomie=Autonomie.T0,
            # §9.5 (feuille de temps envoyée à M5) ; agrège le temps de tous les techniciens : jamais l'employé.
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m4_definir_consentement_gps",
            description=(
                "Enregistre le consentement GPS d'un technicien : donné (activation du punch "
                "géorépéré) ou retiré (POLITIQUE-geolocalisation.md §4). Le retrait prend effet "
                "IMMÉDIATEMENT : dès ce maillon écrit, m4_pointer bascule ce technicien en mode "
                "manuel (aucun fix GPS enregistré), quelle que soit la position fournie par la suite. "
                "T1.4-k, appel d'appareil : un employé ne donne ni ne retire que SON consentement "
                "(technicien_id différent de la personne authentifiée : "
                "REJ-IDENTITE-FOURNIE-DIFFERENTE), l'admin consigne celui d'un technicien. Pendant un "
                "appel d'appareil, l'heure de réception du serveur fait foi (T1.4-d), pas horodatage."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "technicien_id": {"type": "string"},
                    "action": {"type": "string", "enum": list(consentement.ACTIONS_CONSENTEMENT)},
                    "horodatage": {"type": "string"},
                    "version_politique": {
                        "type": "string",
                        "description": "Version du document présenté à l'employé — jamais devinée.",
                    },
                    "preuve": _PREUVE_CONSENTEMENT,
                },
                "required": ["technicien_id", "action", "horodatage", "version_politique", "preuve"],
                "additionalProperties": False,
            },
            fonction=definir_consentement_gps,
            autonomie=Autonomie.T1,
            # POLITIQUE-geolocalisation §4 (« l'employé peut retirer son consentement via l'app employé ») et
            # §7 (droit de retrait à tout moment) : l'employé pour SA personne seulement (T1.4-k, acces.py :
            # jamais celui d'un autre) ; l'admin consigne aussi un consentement ou un retrait « par écrit ».
            roles_appareil=frozenset({"employee", "admin"}),
        ),
        Outil(
            nom="m4_lire_position_gps",
            description=(
                "Déchiffre un fix GPS déjà enregistré par m4_pointer (droit d'accès, "
                "POLITIQUE-geolocalisation.md §7), à partir du ligne_id du maillon de pointage. "
                "Journalise CET accès dans le registre (§6), jamais la position elle-même. Verdict "
                "nommé (jamais une exception) si le maillon ne porte aucun fix chiffré, ou si sa "
                "clé a été détruite par une purge de rétention antérieure (§5) : dans ce dernier "
                "cas, le refus EST la preuve que la destruction a fonctionné."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "ligne_id": {"type": "string"},
                    "accede_par": {
                        "type": "string",
                        "description": (
                            "Identifiant de la personne qui consulte (§6 : tracé nommément). Pendant un "
                            "appel d'appareil (T1.4-k), doit être la personne authentifiée, sinon refus "
                            "REJ-IDENTITE-FOURNIE-DIFFERENTE."
                        ),
                    },
                    "horodatage": {"type": "string"},
                },
                "required": ["ligne_id", "accede_par", "horodatage"],
                "additionalProperties": False,
            },
            fonction=lire_position_gps,
            # Écriture interne (le journal d'accès, §6) au sens de l'ADR-0009 §4 : T1, pas T0,
            # même si son propos premier est une lecture — voir Autonomie.T1 dans opsys.outils.
            autonomie=Autonomie.T1,
            # §9.2 (« accès admin journalisé »), POLITIQUE-geolocalisation §6. `accede_par` doit être la
            # personne authentifiée pour un appel d'appareil (T1.4-k, acces.controler_consultant).
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m4_purger_retention_gps",
            description=(
                "Détruit la clé de chiffrement des fixes GPS d'un technicien une fois l'échéance "
                "de rétention atteinte (POLITIQUE-geolocalisation.md §5 : 12 mois après la fin du "
                "contrat de travail ou le dernier punch, selon la plus longue des deux périodes — "
                "fail-closed si fin_contrat_travail est inconnue, ou si l'échéance n'est pas "
                "atteinte : aucune destruction). Suppression DÉFINITIVE d'une donnée personnelle "
                "(AGENTS.md, frontière T3) : cet outil ne fait que PROPOSER — seul nathan_owner, "
                "avec l'attestation du professionnel concerné (ADR-0009 §5, Niveau N5), peut "
                "l'exécuter. Écrit toujours un maillon d'audit (jamais la position détruite)."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "technicien_id": {"type": "string"},
                    "fin_contrat_travail": {
                        "type": "string",
                        "description": "Horodatage RFC 3339 de fin de contrat (donnée RH, jamais devinée).",
                    },
                    "horodatage": {"type": "string"},
                    "motif": {"type": "string", "description": "Pourquoi cette purge maintenant."},
                },
                "required": ["technicien_id", "fin_contrat_travail", "horodatage", "motif"],
                "additionalProperties": False,
            },
            fonction=purger_retention_gps,
            # T3 (ADR-0009 §4) : « frontière humaine ... suppression » -> N5 par défaut
            # (niveau_par_defaut), jamais configurable par department.yaml (opsys.departements.
            # DEFAUT_ROLES_NIVEAU, vérifié par test_department_yaml_declare_n3_n4_manager_admin_
            # nathan_owner ci-contre dans test_approbations_m4.py) : nathan_owner seul, PLUS
            # l'attestation du professionnel (approbations._valider_attestation), jamais automatique.
            autonomie=Autonomie.T3,
        ),
        Outil(
            nom="m4_proposer_localisation",
            description=(
                "Cherche l'adresse d'un chantier dans l'index LOCAL du Référentiel québécois des adresses "
                "(RQA, aucun réseau) et PROPOSE des coordonnées : correspondance EXACTE unique et de bonne "
                "qualité seulement. Sinon, verdict REJ-COORDONNEES-A-CONFIRMER (« coordonnées manquantes : "
                "à confirmer », jamais une position inventée) avec la raison et les candidats à montrer à "
                "l'humain, ou REJ-INDEX-RQA-ABSENT si l'index n'est pas importé. Lecture seule : rien "
                "n'est écrit ni confirmé. Afficher `attribution` (CC-BY 4.0). `chantier_id` optionnel : "
                "ajoute le résumé de la confirmation actuelle, sans coordonnées."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "adresse": _ADRESSE_CHANTIER,
                    "chantier_id": {
                        "type": ["string", "null"],
                        "description": "Identifiant du chantier (v1 : le lead_id).",
                    },
                },
                "required": ["adresse"],
                "additionalProperties": False,
            },
            fonction=proposer_localisation,
            autonomie=Autonomie.T0,
            # §9.5 (dispatch) : l'admin confirme la localisation d'un chantier depuis son téléphone et doit
            # voir la proposition. Aucune donnée du registre ni d'autrui n'est lue (adresse fournie,
            # référentiel public) ; l'employé et le vendeur n'ont aucun besoin d'une adresse à géocoder.
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m4_confirmer_localisation",
            description=(
                "CONFIRME (ou retire) la localisation d'un chantier : écrit le maillon localisation_chantier, "
                "versionné (le dernier gagne, l'historique reste), coordonnées chiffrées avec une clé par "
                "chantier, adresse jamais en clair (empreinte seulement). source=rqa : rqa_identifiant d'une "
                "adresse de l'index qui correspond EXACTEMENT à `adresse` (coordonnées lues dans l'index, "
                "jamais des arguments) ; source=manuel : coordonnées en microdegrés saisies par l'humain, "
                "marquées manuel. `motif` obligatoire pour remplacer, retirer, ou confirmer une position de "
                "qualité faible ou une adresse non certifiée. Aucune coordonnée n'entre au solveur de "
                "tournées sans cette confirmation humaine. Pour un appel d'appareil, `confirme_par` doit "
                "être la personne authentifiée (REJ-IDENTITE-FOURNIE-DIFFERENTE sinon)."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "chantier_id": {"type": "string", "description": "Identifiant du chantier (v1 : le lead_id)."},
                    "action": {"type": "string", "enum": list(localisation.ACTIONS_LOCALISATION)},
                    "horodatage": {"type": "string"},
                    "confirme_par": {"type": "string", "description": "Personne qui confirme, nommément."},
                    "adresse": _ADRESSE_CHANTIER,
                    "source": {"type": ["string", "null"], "enum": list(localisation.SOURCES_LOCALISATION) + [None]},
                    "rqa_identifiant": {"type": ["string", "null"], "description": "Identifiant RQA (source rqa)."},
                    "latitude_microdegres": {
                        "type": ["integer", "null"], "description": "Degrés × 1 000 000 (source manuel).",
                    },
                    "longitude_microdegres": {
                        "type": ["integer", "null"], "description": "Degrés × 1 000 000 (source manuel).",
                    },
                    "motif": {"type": "string", "description": "Pourquoi (obligatoire dans les cas listés)."},
                },
                "required": ["chantier_id", "action", "horodatage", "confirme_par"],
                "additionalProperties": False,
            },
            fonction=confirmer_localisation,
            autonomie=Autonomie.T1,
            # Niveau : N3, le défaut de T1 (ADR-0009 §4, « modification interne non finale, validation humaine
            # au départ »), laissé implicite comme pour les autres écritures internes de M4. Ce n'est PAS N2 :
            # N2 est automatique, or R15 §3 exige une confirmation humaine avant qu'une coordonnée entre au
            # solveur. En N3, un appel d'agent en mode ombre part en file d'approbation ; un appel de l'admin
            # depuis son téléphone s'exécute sur-le-champ (validation au départ par la personne qui agit,
            # addendum T1.4-h) et `confirme_par` porte son nom. Ce n'est pas N4 : le geste est versionné et se
            # corrige (`retiree`), il n'engage rien hors de l'entreprise. Limite : en `supervise` et `autonome`,
            # un N3 s'exécute sans file (ROLES.md, « Ce qui reste »).
            # §9.5 (dispatch) : réservé à l'admin ; l'employé ne confirme pas une adresse de client.
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m4_proposer_cedule",
            description=(
                "Propose une cédule par tournées (PyVRP, ou repli exact jusqu'à 12 chantiers) : regroupe les "
                "chantiers proches, respecte fenêtres du client, quarts, durées, compétences et créneaux déjà "
                "confirmés. Range un plan PROPOSÉ : brouillon, aucune assignation. Sans argument, équipes, dépôt, "
                "quarts, durées, compétences, réglages viennent du PROFIL DES ÉQUIPES de l'entreprise (opsys equipes "
                "declarer) ; un argument donné le REMPLACE (surcharge) et la provenance de chaque valeur est rendue. "
                "Lit les interventions planifiees et les a_planifier PRÊTES (m4_verifier_preparation ; les autres "
                "sont rendues dans non_pretes), leur urgence_declaree (vrai vaut 1, sinon 0) et les coordonnées "
                "CONFIRMÉES. Ni profil ni argument : un verdict REJ-CHAMP-MANQUANT qui dit quoi fournir et où le "
                "déclarer, jamais une valeur par défaut. Rend plan_id, mode_bride, non_cedulees et leurs raisons. "
                "Pour appliquer : m4_appliquer_cedule."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "horodatage": {"type": "string"},
                    "equipes": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": (
                            "Surcharge du profil. [{id (= technicien_id de l'assignation), competences: [string], "
                            "depot: {id, latitude_microdegres, longitude_microdegres} (lieu de l'entreprise), "
                            "quarts: [{jour, debut_min, fin_min}]}]. jour : numéro de journée de la cédule. Omis : "
                            "les équipes du profil."
                        ),
                    },
                    "durees_par_type_travaux": {
                        "type": "object",
                        "description": (
                            "{type_travaux: minutes entières}, un pour chaque type à planifier (leads v1, sans "
                            "équivalent dans le profil). Exigé seulement si une intervention à planifier vient "
                            "d'un lead v1."
                        ),
                    },
                    "competences_par_type_travaux": {
                        "type": "object",
                        "description": (
                            "{type_travaux: [compétence]}, liste vide si aucune, pour chaque type (leads v1, sans "
                            "équivalent dans le profil). Exigé seulement si une intervention à planifier vient "
                            "d'un lead v1."
                        ),
                    },
                    "durees_par_service": {
                        "type": "object",
                        "description": (
                            "Surcharge du profil. {service: minutes entières}, un pour chaque service à planifier "
                            "(code déclaré par l'entreprise). Omis : les durées du profil."
                        ),
                    },
                    "competences_par_service": {
                        "type": "object",
                        "description": (
                            "Surcharge du profil. {service: [compétence]}, liste vide si aucune, pour chaque "
                            "service. Omis : les compétences du profil."
                        ),
                    },
                    "chantiers": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": (
                            "Une entrée par intervention : {intervention_id, fenetre: {jours: [int], debut_min, "
                            "fin_min}, creneau_fige: null si aucun, sinon {equipe, jour, debut_min} (créneau déjà "
                            "confirmé au client : jamais déplacé)}. Exigée pour une intervention planifiee. Une "
                            "intervention a_planifier sans entrée prend la fenêtre par défaut du profil et aucun "
                            "créneau figé (aucun créneau n'a pu être promis avant la cédule)."
                        ),
                    },
                    "parametres": {
                        "type": "object",
                        "description": (
                            "Surcharge du profil. Réglages de la cédule, tous obligatoires : "
                            "facteur_detour_milliemes (1300 pour 1,3), vitesse_moyenne_kmh, "
                            "marge_par_trajet_secondes, iterations, cout_non_cedule_m. graine optionnelle (réglage "
                            "technique). Omis : les réglages du profil."
                        ),
                    },
                    "intervention_ids": {
                        "type": ["array", "null"],
                        "items": {"type": "string"},
                        "description": (
                            "Restreint aux interventions nommées (une a_planifier non prête est refusée, "
                            "REJ-CEDULE-PREPARATION-NON-PRETE) ; omis : toutes les planifiees et les a_planifier "
                            "prêtes."
                        ),
                    },
                    "moteur": {"type": "string", "enum": list(tournees.MOTEURS)},
                },
                "required": ["horodatage"],
                "additionalProperties": False,
            },
            fonction=proposer_cedule,
            autonomie=Autonomie.T1,
            # N1 « brouillon » (ADR-0009 §4, automatique) et non le défaut T1 -> N3 : la proposition ne change
            # aucune vérité (aucune assignation, aucun statut) ; c'est son application qui est N3. En N3, le
            # mode ombre mettrait chaque simulation de l'admin en attente d'une approbation.
            niveau=Niveau.N1,
            # §9.5 (dispatch du jour) : l'admin voit la proposition depuis son téléphone. Les tournées
            # regroupent des chantiers de clients : jamais l'employé ni le vendeur, qui n'écrivent pas au
            # registre de cédule.
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m4_appliquer_cedule",
            description=(
                "APPLIQUE un plan proposé (plan_id de m4_proposer_cedule) : assigne chaque technicien. Une "
                "intervention a_planifier que le plan place passe à planifiee (verdict de préparation « prêt » "
                "recalculé, porte d'empreinte de T4.10) avant d'être assignée ; une autre reste a_planifier. "
                "Refuse, sans rien écrire, si une préparation n'est plus prête, si l'état des interventions, le "
                "profil des équipes ou une coordonnée confirmée a changé depuis la proposition "
                "(REJ-CEDULE-ENTREE-CHANGEE : proposer de nouveau), ou si le plan échoue à verifier_plan. Un créneau "
                "déjà confirmé n'est jamais déplacé. Idempotent : le même plan_id deux fois n'écrit rien de plus. "
                "Pour un appel d'appareil, confirme_par doit être la personne authentifiée."
            ),
            parametres={
                "type": "object",
                "properties": {
                    "plan_id": {"type": "string", "description": "Identifiant rendu par m4_proposer_cedule."},
                    "horodatage": {"type": "string"},
                    "confirme_par": {"type": "string", "description": "Personne qui applique, nommément."},
                },
                "required": ["plan_id", "horodatage", "confirme_par"],
                "additionalProperties": False,
            },
            fonction=appliquer_cedule,
            autonomie=Autonomie.T1,
            # Niveau : N3, le défaut de T1 (ADR-0009 §4, « modification interne non finale, validation humaine
            # au départ »), laissé implicite comme m4_confirmer_localisation. Ce n'est pas N4 : une assignation
            # ne s'engage pas hors de l'entreprise (le client n'est pas averti ici) et se corrige par une
            # nouvelle proposition. En N3, un appel d'agent en mode ombre part en file ; l'admin qui applique
            # depuis son téléphone valide « au départ » (T1.4-h) et `confirme_par` porte son nom. Limite : en
            # `supervise` et `autonome`, un N3 s'exécute sans file (ROLES.md, « Ce qui reste »).
            # §9.5 (dispatch du jour) : réservé à l'admin ; l'employé ne dispatche pas.
            roles_appareil=frozenset({"admin"}),
        ),
        Outil(
            nom="m4_verifier_preparation",
            description=(
                "Lecture seule (M4.6) : dit si une intervention peut être planifiée, VOLET PAR VOLET, et NOMME ce "
                "qui manque. Volets : soumission (devis accepté), adresse (coordonnées CONFIRMÉES), équipe "
                "admissible (calculée depuis le profil des équipes : compétences du service et quart assez long ; "
                "sans profil, manque dit quoi déclarer), matériel, météo. Chaque volet est ok (lu à sa source), "
                "manque (attendu et absent) ou non_verifiable (matériel et météo aujourd'hui : aucune intervention "
                "n'est encore prête). pret SEULEMENT si tous les volets sont ok, jamais par défaut. Ne rend ni "
                "coordonnée, ni contact, ni prix, et ne promet aucune date. Refus (REJ-TRANSITION-ILLEGALE) : "
                "intervention inconnue, ou hors de a_planifier, planifiee et reportee. Réservé à l'admin."
            ),
            parametres={
                "type": "object",
                "properties": {"intervention_id": {"type": "string"}},
                "required": ["intervention_id"],
                "additionalProperties": False,
            },
            fonction=verifier_preparation,
            autonomie=Autonomie.T0,
            # §9.5 M4 « dispatch du jour » : l'admin voit ce qui bloque un chantier avant de le cédule. Ni l'employé
            # ni le vendeur : c'est l'état d'un chantier de client (adresse confirmée ou non). Refusé aussi dans
            # l'outil (`acces.controler_administrateur`).
            roles_appareil=frozenset({"admin"}),
        ),
    )


def lire_localisation_confirmee(
    registre_cible: registre.Registre, chantier_id: str, adresse: Any = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Lecture pour le solveur de tournées (T4.1-c) : ``(position, None)`` avec les coordonnées
    confirmées en microdegrés, ou ``(None, verdict)`` : ``REJ-COORDONNEES-A-CONFIRMER`` (jamais
    confirmée, retirée, ou adresse changée), ``REJ-LOCALISATION-DETRUITE`` (clé détruite). Le dernier
    maillon gagne. À appeler dans l'appel d'outil en cours (la clé est lue dans sa transaction) ; hors
    transaction, une lecture s'ouvre pour l'occasion. ``adresse`` optionnelle : si elle diffère de
    celle qui a été confirmée, la position n'est pas rendue."""
    cnx = stockage.connexion_courante()
    if cnx is not None:
        cle = cles_chiffrement.lire(cnx, localisation.PORTEE_CLES_LOCALISATION, chantier_id)
    else:
        with stockage.transaction() as cnx_lecture:
            cle = cles_chiffrement.lire(cnx_lecture, localisation.PORTEE_CLES_LOCALISATION, chantier_id)
    return localisation.position_confirmee(registre_cible, chantier_id, cle, adresse=adresse)


def _chemin_index_rqa():
    """Index RQA de l'instance : ``<OPSYS_HOME>/rqa/index.sqlite`` (``localisation.importer_rqa``)."""
    return stockage.dossier_opsys() / localisation.SOUS_DOSSIER_INDEX / localisation.NOM_FICHIER_INDEX


# ---------------------------------------------------------------------------------------------
# Dépôt de fichiers (T1.4-e2) : traduction socle -> catalogue M4, et vérification des références
# utilisées par `completer_intervention` ci-dessus. Fonctions module-level (comme
# `_depuis_pending_review`/`_resume_completion_en_revue` plus bas) : aucune n'a besoin de
# `registre_courant()`, seulement de la connexion durable de l'appel en cours.
# ---------------------------------------------------------------------------------------------
def _horodatage_depot_fichier() -> str | None:
    """Heure de réception qui fait foi (T1.4-d/IDEMPOTENCE.md §5) : celle de l'appel d'appareil en
    cours quand il y en a un, sinon ``None`` — `m4_deposer_fichier` ne porte aucun paramètre
    d'horodatage (contrat fixe) et un département ne lit JAMAIS l'horloge lui-même (garde AST
    `digest.garde_absence_horloge`) : `opsys.fichiers.deposer_bloc` lit l'heure courante à la
    frontière impure du socle quand `recu_le` est `None`, jamais ici."""
    ctx = contexte.horodatage_reception()
    return ctx.recu_le.isoformat() if ctx is not None else None


def _depuis_depot_fichier(resultat: fichiers.DepotResultat) -> dict[str, Any]:
    if resultat.accepte:
        return {
            "accepte": True,
            "resultat": {
                "reference": resultat.reference,
                "complet": resultat.complet,
                "blocs_recus": list(resultat.blocs_recus),
            },
        }
    code = _RAISON_DEPOT_VERS_CODE[resultat.raison]
    return {"accepte": False, "verdict": verdicts.construire_verdict(code, detail=resultat.detail)}


def _verifier_reference_fichier(reference: Any, types_permis: tuple[str, ...], champ: str) -> dict | None:
    """``None`` si `reference` désigne, dans le dépôt, un fichier COMPLET d'un type permis ;
    sinon un verdict ``REJ-PREUVE-FICHIER-INTROUVABLE`` nommé — fail-closed, jamais une exception
    ni une acceptation optimiste. `champ` identifie l'origine dans le détail du verdict (agent :
    quoi corriger). Lecture pure (comme `etat_fichier` ci-dessus) : `stockage.transaction()`
    fournit une connexion, imbriquée sur celle déjà ouverte par `completer_intervention` en
    production (executer_atomique), fraîche sinon — jamais besoin d'une connexion ambiante déjà
    posée par l'appelant."""
    empreinte = fichiers.empreinte_depuis_reference(reference)
    if empreinte is None:
        return verdicts.construire_verdict(
            "REJ-PREUVE-FICHIER-INTROUVABLE",
            detail=f"{champ} : forme de référence invalide (attendu fichier:sha256:<hex>), reçu {reference!r}",
        )
    with stockage.transaction() as cnx:
        etat_fichier = fichiers.etat(cnx, empreinte)
    if not etat_fichier.complet:
        return verdicts.construire_verdict(
            "REJ-PREUVE-FICHIER-INTROUVABLE",
            detail=f"{champ} : aucun fichier complet pour cette référence dans le dépôt ({reference!r})",
        )
    if etat_fichier.type_mime not in types_permis:
        return verdicts.construire_verdict(
            "REJ-PREUVE-FICHIER-INTROUVABLE",
            detail=(
                f"{champ} : type {etat_fichier.type_mime!r} non permis ici "
                f"(attendu {types_permis}), référence {reference!r}"
            ),
        )
    return None


def _verifier_preuves_fichiers(preuves_completion: dict[str, Any], signature_requise: bool) -> dict | None:
    """Vérifie CHAQUE référence de `photos_apres` (toujours) et `signature` (si requise, T1.4-e2
    point 3 du PLAN) contre le dépôt de fichiers. Structure déjà garantie par
    `preuves.valider_preuves_completion`, appelé avant cette fonction : `photos_apres` est ici une
    liste de chaînes non vide, `signature` une chaîne non vide quand `signature_requise`."""
    for index, reference in enumerate(preuves_completion["photos_apres"]):
        verdict = _verifier_reference_fichier(reference, _TYPES_PHOTO_APRES, f"photos_apres[{index}]")
        if verdict is not None:
            return verdict
    if signature_requise:
        verdict = _verifier_reference_fichier(preuves_completion["signature"], _TYPES_SIGNATURE, "signature")
        if verdict is not None:
            return verdict
    return None


# ---------------------------------------------------------------------------------------------
# Consommateurs d'événements (ADR-0009 §3, PLAN T1.2, point 4)
# ---------------------------------------------------------------------------------------------
# Même module que `outils()` (docs/architecture/DEPARTEMENTS.md) : seul cet adaptateur connaît
# `opsys`/`opsys.evenements` ; toute la logique de décision reste dans `outbox.confirmer_verification`
# (module pur, gardé par l'AST comme le WCT). Le répartiteur (`opsys.evenements.repartir`) n'appelle
# ces fonctions que dans une transaction déjà ouverte : le registre durable fait donc TOUJOURS
# autorité ici, sans le mode « en mémoire » des tests unitaires de `outils()` ci-dessus.
def _recevoir_variance_chantier(charge: dict[str, Any]) -> dict[str, Any]:
    """Consomme `m6.variance_chantier` : SEUL chemin qui fait passer une intervention de
    `completed_pending_review` à `completed_verified` (PLAN T1.2, point 4). DÉTERMINISTE :
    applique tel quel le verdict déjà calculé par M6 (statut_variance, signal_critique),
    n'invente rien. Les preuves de complétion sont déjà garanties par
    `m4_completer_intervention` (T1.1-b#3) : cette fonction n'a rien à revérifier de ce côté,
    la complétion n'existe pas sans elles.

    Idempotente à deux niveaux : le bus ne livre jamais deux fois le même `evenement_id`
    (`evenements_recus`, ADR-0009 §3) et, en plus, `confirmer_verification` lui-même est un
    no-op si l'intervention est déjà `completed_verified` — une redélivrance ou un second
    événement pour le même WCT ne change jamais rien.

    PLAN T1.3-b : quand ce signal ne mène PAS à une vérification automatique (branche
    ci-dessous), il est TRACÉ dans le registre de M4 (`outbox.enregistrer_signal_variance`) —
    sans ce maillon, `attentes()` (file du propriétaire) n'aurait aucun moyen de savoir, en ne
    lisant que le registre de M4, qu'un signal critique attend une revue humaine
    (`m4_resoudre_revue_completion`).
    """
    reg = registre.Registre(stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
    intervention_id = charge["intervention_id"]

    # Seul le code décide : `evaluee` + `signal_critique` explicitement faux, rien d'autre
    # (jamais une absence de signal traitée comme faux — le schéma du catalogue impose déjà
    # `signal_critique` non nul seulement quand `statut_variance == "evaluee"`).
    if charge["statut_variance"] != "evaluee" or charge["signal_critique"] is not False:
        outbox.enregistrer_signal_variance(intervention_id, charge, reg)
        return {
            "traite": True, "verifie": False,
            "intervention_id": intervention_id, "raison": charge["statut_variance"],
        }

    accuse, verdict = outbox.confirmer_verification(
        intervention_id, charge["horodatage_completion"], reg,
        evenement_id_variance=charge["evenement_id"],
    )
    if verdict is not None:
        return {
            "traite": True, "verifie": False,
            "intervention_id": intervention_id, "raison": verdict["code"],
        }
    return {
        "traite": True, "verifie": not accuse["deja_verifie"],
        "intervention_id": intervention_id, "statut": accuse["statut"],
    }


# ---------------------------------------------------------------------------------------------
# Consommateur `m3.devis_accepte` (ADR-0009 §3, PLAN T4.10-b) : « soumission acceptée -> M4 planifie »
# ---------------------------------------------------------------------------------------------
# DEFINITION-PRODUIT §6, flux principal, et §7 M4.5 « Réception d'un job depuis M2/M3 (soumission acceptée) » :
# M4 n'avait aucun état avant `planifiee` et personne ne lui disait qu'un devis venait d'être accepté. Le devis
# accepté fait maintenant naître une intervention `a_planifier`, sans import de M2 ni de M3 (décision #109).
#
# Ce que le devis porte : `devis_id` et `lead_id`. Ce qu'il ne porte pas : le service, la ville, l'urgence du
# chantier. M4 ne les reçoit d'aucun appelant et ne les devine pas : il les relit À LA SOURCE DU BUS, dans le
# `m1.lead_qualifie` que M1 a publié pour ce lead (`evenements.charge_publiee`, même patron que M3 pour
# `m2.lead_assigne`). Un fait absent lève une erreur nommée qui dit ce qui manque : le répartiteur réessaie, puis
# met l'événement en quarantaine, visible d'un humain (`opsys evenements etat`) ; le devis reste au bus.
_TYPE_EVENEMENT_LEAD_QUALIFIE = "m1.lead_qualifie"
# Sel de la ville tokenisée d'une intervention née du bus : aucun appelant n'en fournit (contrairement à
# `m4_planifier_intervention`). Un secret par instance, dans le coffre du socle, jamais dans le code ni au registre.
_PORTEE_SEL_VILLE = "m04-field-ops/sel-ville"
_IDENTIFIANT_SEL_VILLE = "instance"


class FaitDeLeadManquant(LookupError):
    """m3.devis_accepte : le service, la ville et l'urgence du chantier n'ont pas de source au bus (aucun
    `m1.lead_qualifie` publié pour ce `lead_id`, ou charge d'un autre lead). M4 n'invente ni service ni ville :
    un lead qui n'est pas passé par M1 (saisi directement dans M2) se planifie par `m4_planifier_intervention`,
    avec son contrat complet. Jamais un refus métier normal : le répartiteur réessaie puis met en quarantaine."""


class InscriptionDevisRefusee(ValueError):
    """m3.devis_accepte : le lead publié par M1 ou le devis ne passe pas la validation de M4 (service retiré du
    profil d'entreprise depuis la qualification, contrat invalide, horodatage invalide). Aucune écriture."""


def _lead_de_la_source(lead_id: str) -> dict[str, Any]:
    """Le LeadQualifie v2 que M1 a publié pour ce lead, relu à la source du bus."""
    charge = evenements.charge_publiee(_TYPE_EVENEMENT_LEAD_QUALIFIE, f"m1-lead-qualifie-{lead_id}")
    lead = None if charge is None else charge.get("lead")
    if not isinstance(lead, dict) or lead.get("lead_id") != lead_id:
        raise FaitDeLeadManquant(
            "m3.devis_accepte : service, ville et urgence du chantier introuvables : aucun "
            f"{_TYPE_EVENEMENT_LEAD_QUALIFIE} publié pour le lead {lead_id!r} "
            f"(attendu : evenement_id m1-lead-qualifie-{lead_id}). "
            "M4 ne les devine pas : planifier par m4_planifier_intervention, ou republier l'événement une fois "
            "le lead connu de M1."
        )
    return lead


def _sel_de_la_ville(cree_le: str) -> str:
    cnx = stockage.connexion_courante()
    if cnx is None:
        raise InscriptionDevisRefusee(
            "m3.devis_accepte : aucune base jointe, le sel de tokenisation de la ville n'est pas lisible"
        )
    return cles_chiffrement.obtenir_ou_creer(cnx, _PORTEE_SEL_VILLE, _IDENTIFIANT_SEL_VILLE, cree_le).hex()


def _recevoir_devis_accepte(charge: dict[str, Any]) -> dict[str, Any]:
    """Consomme `m3.devis_accepte` : inscrit l'intervention `a_planifier` qui naît du devis accepté.

    Idempotent à deux niveaux : le répartiteur n'appelle cette fonction qu'une fois par (evenement_id,
    consommateur) traité ; et une intervention qui porte déjà ce `devis_id` (le même devis republié sous un autre
    `evenement_id`, ou une intervention inscrite avant par `m4_planifier_intervention`) est reconnue avant toute
    lecture : `deja_applique`, aucune seconde intervention. Aucun prix, coût ni marge du devis n'est lu ni gardé
    (`frontieres.py`) ; aucune date ni créneau n'est fixé : l'intervention attend sa préparation
    (`preparation.py`) et sa cédule. Rien du contact du client n'entre au registre (la ville y est tokenisée)."""
    devis_id = charge["devis_id"]
    lead_id = charge["lead_id"]
    reg = registre.Registre(stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
    existante = etats.intervention_du_devis(reg, devis_id)
    if existante is not None:
        return {
            "traite": True, "devis_id": devis_id, "lead_id": lead_id,
            "intervention_id": existante, "deja_applique": True,
        }
    lead = _lead_de_la_source(lead_id)
    horodatage = charge["horodatage_acceptation"]
    accuse, verdict = etats.inscrire_depuis_devis(reg, devis_id, lead, _sel_de_la_ville(horodatage), horodatage)
    if verdict is not None:
        raise InscriptionDevisRefusee(
            f"m3.devis_accepte : intervention refusée pour le devis {devis_id!r} : "
            f"{verdict['code']} : {verdict['detail']}"
        )
    return {
        "traite": True, "devis_id": devis_id, "lead_id": lead_id,
        "intervention_id": accuse["intervention_id"], "statut": accuse["statut"], "service": lead["service"],
    }


def consommateurs() -> dict[str, Callable[[dict], dict]]:
    return {
        "m6.variance_chantier": _recevoir_variance_chantier,
        "m3.devis_accepte": _recevoir_devis_accepte,
    }


# ---------------------------------------------------------------------------------------------
# Attentes du propriétaire (ADR-0009 §5, PLAN T1.3-b)
# ---------------------------------------------------------------------------------------------
# Même mécanisme de découverte que `consommateurs()` (`opsys.departements.Departement.
# charger_attentes`) : fonction module-level, sans argument, appelée par
# `approbations.file_proprietaire` DANS SA transaction déjà ouverte — jamais construite en dehors
# de cet appel (aucune connexion garantie ailleurs, `departements.py`).
def attentes() -> list[dict[str, Any]]:
    """Une entrée par intervention actuellement `completed_pending_review` : la complétion
    existe déjà (WCT écrit, preuves garanties par `m4_completer_intervention`, T1.1-b#3), reste
    à vérifier ou à corriger par une personne autorisée (`m4_resoudre_revue_completion`, jamais
    un agent seul). Le résumé porte le signal de variance critique de M6 QUAND il existe
    (`outbox.dernier_signal_variance`, tracé par `_recevoir_variance_chantier` ci-dessus) — son
    absence est dite telle quelle (« pas encore de nouvelles »), jamais traitée comme « pas de
    problème » (fail-closed).

    PLAN T1.5-c, décision écrite : entre « Terminer » et le formulaire des matériaux, la
    complétion est DÉJÀ `completed_pending_review`, et c'est juste. DEFINITION-PRODUIT §6 : « s'il
    manque quelque chose ou si le matériel diffère du prévu, le statut devient
    completed_pending_review » — le matériel utilisé manque, et §9.7 ne le compare qu'à la
    soumission du formulaire. L'information est donc VRAIE et reste dans « À voir » : la retirer
    rendrait invisible une déclaration jamais faite, faute d'horloge (un département ne lit
    jamais l'heure) pour distinguer « en cours » de « en retard ». Ce qui était FAUX, c'était de
    la présenter comme une revue à trancher : tant que la variance de M6 n'est pas là (rien reçu,
    ou `declaration_absente`), il n'y a rien à décider, et `verifiee` court-circuiterait la
    comparaison de M6. Le résumé dit alors qu'on attend le formulaire, sans écart signalé, et le
    geste proposé n'offre pas `verifiee`. L'alerte d'écart (§9.7, étape 5) reste celle du signal
    critique de M6, inchangée."""
    reg = registre.Registre(stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
    return [
        {
            "type": "completion_en_revue",
            "id": pendante["intervention_id"],
            "resume": _resume_completion_en_revue(reg, pendante["intervention_id"]),
            "niveau": Niveau.N4.value,
            "depuis": _depuis_pending_review(reg, pendante["intervention_id"]),
            "action_proposee": _geste_completion_en_revue(reg, pendante["intervention_id"]),
        }
        for pendante in etats.lister_interventions(reg, statut="completed_pending_review")
    ]


def _depuis_pending_review(reg: registre.Registre, intervention_id: str) -> str:
    """Horodatage du DERNIER maillon `completed_pending_review` de l'intervention — l'entrée en
    revue, ou la dernière correction nommée si une ou plusieurs ont déjà eu lieu. Jamais une
    horloge consultée ici (même garde d'esprit que `digest.py`) : uniquement des horodatages déjà
    écrits au registre. Ne peut pas être `None` : `attentes()` n'appelle cette fonction que pour
    une intervention dont `etats.lister_interventions` vient de constater ce statut courant, donc
    au moins un tel maillon existe forcément."""
    dernier = None
    for maillon in reg.lire():
        if (maillon.get("type_entree") == etats.TYPE_TRANSITION
                and maillon.get("intervention_id") == intervention_id
                and maillon.get("statut") == "completed_pending_review"):
            dernier = maillon["horodatage"]
    return dernier


_GESTE_REVUE = (
    "m4_resoudre_revue_completion : verifiee (confirme) ou correction (nomme le "
    "problème)"
)
_GESTE_ATTENTE_FORMULAIRE = (
    "Rien à décider : la vérification suit le formulaire des matériaux de l'employé. S'il "
    "n'arrive pas : m4_resoudre_revue_completion (correction)"
)


def _ecart_metier_signale_a_la_completion(reg: registre.Registre, intervention_id: str) -> bool:
    """Le WCT de l'intervention dit-il qu'un écart métier était ouvert à la complétion ?
    (`wct.ecart_signale`, T1.5-c : vrai seulement dans ce cas.)"""
    return any(
        wct["intervention_id"] == intervention_id and wct["ecart_signale"] is True
        for _, wct in outbox.lire_outbox(reg)
    )


def _attend_le_formulaire(
    reg: registre.Registre, intervention_id: str, signal: dict[str, Any] | None,
) -> bool:
    """Vrai tant qu'il n'y a rien à décider : aucun écart métier ouvert à la complétion, et la
    variance de M6 n'a pas de quoi être évaluée du côté du terrain (aucun signal reçu, ou
    `declaration_absente` : l'employé n'a pas encore rempli le formulaire). Les autres statuts
    (`prevu_absent`, `seuil_absent`, `evaluee`) et tout écart métier demandent une personne."""
    if _ecart_metier_signale_a_la_completion(reg, intervention_id):
        return False
    return signal is None or signal["statut_variance"] == "declaration_absente"


def _geste_completion_en_revue(reg: registre.Registre, intervention_id: str) -> str:
    signal = outbox.dernier_signal_variance(reg, intervention_id)
    if _attend_le_formulaire(reg, intervention_id, signal):
        return _GESTE_ATTENTE_FORMULAIRE
    return _GESTE_REVUE


def _resume_completion_en_revue(reg: registre.Registre, intervention_id: str) -> str:
    base = f"Complétion en revue ({intervention_id})"
    signal = outbox.dernier_signal_variance(reg, intervention_id)
    # Jamais « aucun écart » quand le WCT dit le contraire : le constat vient du WCT lui-même.
    constat = (
        "écart métier ouvert à la complétion"
        if _ecart_metier_signale_a_la_completion(reg, intervention_id)
        else "aucun écart signalé"
    )
    if signal is None:
        return f"{base} — variance M6 non encore reçue, {constat} à ce stade"
    if signal["statut_variance"] == "declaration_absente":
        return (
            f"{base} — variance M6 non finalisée (declaration_absente) : formulaire des matériaux "
            f"de l'employé attendu, {constat}"
        )
    if signal["statut_variance"] != "evaluee":
        return f"{base} — variance M6 non finalisée ({signal['statut_variance']})"
    if signal["signal_critique"] is True:
        return f"{base} — écart matériaux CRITIQUE signalé par M6 (seuil {signal['seuil_pourcentage']})"
    # Atteint seulement si confirmer_verification a, pour une autre raison, échoué à vérifier
    # malgré un signal non critique (défensif : jamais supposé impossible, jamais deviné).
    return f"{base} — variance M6 évaluée sans signal critique"
