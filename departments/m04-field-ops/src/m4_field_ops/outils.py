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

from collections.abc import Callable
from typing import Any

from opsys import approbations, cles_chiffrement, contexte, evenements, fichiers, stockage
from opsys.outils import Autonomie, Niveau, Outil, depuis_couple

from . import (
    acces,
    cedule,
    consentement,
    digest,
    ecarts,
    etats,
    outbox,
    pointage,
    preuves,
    registre,
    retention,
    temps,
    verdicts,
)

# PLAN T4.2 (POLITIQUE-geolocalisation.md §5) : portée des clés de chiffrement GPS dans le coffre
# du socle (opsys.cles_chiffrement) — une seule portée pour tout M4, l'identifiant est le
# technicien_id (une clé par employé, alignée sur l'unité de rétention/purge de la politique,
# jamais par pointage individuel).
_PORTEE_CLES_GPS = "m04-field-ops/gps"

_DEPARTEMENT = "m04-field-ops"
_NOM_REGISTRE = "principal"

_CONTRAT = {"type": "object", "description": "LeadQualifie M2 : sept clés gelées (lead_id, "
            "conversation_id, type_travaux, ville, canal, contact, urgence_declaree)."}
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


def _refus(verdict: dict[str, Any]) -> dict[str, Any]:
    return {"accepte": False, "verdict": verdict}


def outils(registre_cible: registre.Registre | None = None) -> tuple[Outil, ...]:
    """Capacités exposées aux agents, qui partagent le registre du département.

    `registre_cible` : `None` (défaut, utilisé par `charger_outils()` en production) adosse le
    registre au stockage durable de l'instance ; un `registre.Registre()` explicite (tests) reste
    en mémoire, jamais touché à la base.
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
        intervention_pour_cedule = {
            "intervention_id": accuse["intervention_id"],
            "lead_id": contrat["lead_id"],
            "type_travaux": contrat["type_travaux"],
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
    ) -> dict[str, Any]:
        # T1.2-f : photos/description_factuelle/consentement_marketing/client_satisfait sont
        # des faits du CLIENT (Loi 25) — un agent ne peut JAMAIS les affirmer, même principe
        # que ecart_detecte déjà retiré du schéma de cet outil. Ils ne sont acceptés que
        # PENDANT un appel d'appareil (opsys.contexte.horodatage_reception() non None, socle
        # T1.4-b, docs/architecture/IDEMPOTENCE.md) : leur seule PRÉSENCE hors d'un tel appel
        # est un refus nommé — AVANT même de valider les preuves, rien n'est écrit ni publié.
        # PLAN T1.4-k : un employé ne termine que SON intervention (avant toute autre lecture).
        acteur, verdict_acteur = _acteur_appareil()
        if verdict_acteur is not None:
            return _refus(verdict_acteur)
        verdict_acces = acces.controler_intervention(registre_courant(), intervention_id, acteur)
        if verdict_acces is not None:
            return _refus(verdict_acces)

        champs_client_fournis = any(
            v is not outbox.NON_FOURNI
            for v in (photos, description_factuelle, consentement_marketing, client_satisfait)
        )
        if champs_client_fournis and contexte.horodatage_reception() is None:
            return {
                "accepte": False,
                "verdict": verdicts.construire_verdict(
                    "REJ-CHAMPS-CLIENT-HORS-APPAREIL",
                    detail=(
                        "photos/description_factuelle/consentement_marketing/client_satisfait "
                        "ne sont acceptés que pendant un appel d'appareil (Loi 25) : un agent "
                        "ne peut jamais les affirmer à la place du client"
                    ),
                ),
            }

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
        # Un agent ne peut pas affirmer l'absence d'écart : le matériel n'est pas encore comparé
        # au prévu à ce stade. La complétion reste donc à revoir ; completed_verified viendra du
        # code (variance M6 et preuves, PLAN T1.2) ou d'une décision humaine (T1.3).
        reg = registre_courant()
        accuse, verdict = outbox.completer_intervention(
            intervention_id, horodatage, reg, ecart_detecte=True,
            photos=photos, description_factuelle=description_factuelle,
            consentement_marketing=consentement_marketing, client_satisfait=client_satisfait,
        )
        if verdict is not None:
            return {"accepte": False, "verdict": verdict}
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
                "(checklist, photos après, notes, signature si requise, §6/§9.7) ; T1.4-e2 : "
                "chaque référence photos_apres/signature doit désigner un fichier déposé et "
                "complet (m4_deposer_fichier), sinon REJ-PREUVE-FICHIER-INTROUVABLE. Le statut est "
                "toujours completed_pending_review : la vérification se fait ensuite, par la "
                "variance des matériaux et une revue. Calcule la durée réelle depuis les "
                "pointages, nette des pauses ; refuse fail-closed si indéterminable ou si les "
                "preuves manquent. T1.2-f : consentement_marketing, client_satisfait, photos et "
                "description_factuelle sont des faits CLIENT (Loi 25), jamais affirmés par un "
                "agent — acceptés SEULEMENT pendant un appel d'appareil (app mobile) ; les fournir "
                "hors d'un appel est un refus nommé (REJ-CHAMPS-CLIENT-HORS-APPAREIL), rien écrit. "
                "T1.4-k : un employé ne termine que SON intervention (REJ-INTERVENTION-NON-ASSIGNEE)."
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
                            "Consentement explicite du client à un usage marketing (Loi 25), "
                            "jamais déduit. Accepté SEULEMENT pendant un appel d'appareil, "
                            "jamais fourni ni affirmé par un agent."
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
                "Liste les interventions connues (id, statut, lead, type de travaux, devis), "
                "sans aucune donnée de contact. Filtre optionnel par statut. T1.4-e2 (écran "
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
    )


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


def consommateurs() -> dict[str, Callable[[dict], dict]]:
    return {"m6.variance_chantier": _recevoir_variance_chantier}


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
    problème » (fail-closed)."""
    reg = registre.Registre(stockage.maillons(_DEPARTEMENT, _NOM_REGISTRE))
    return [
        {
            "type": "completion_en_revue",
            "id": pendante["intervention_id"],
            "resume": _resume_completion_en_revue(reg, pendante["intervention_id"]),
            "niveau": Niveau.N4.value,
            "depuis": _depuis_pending_review(reg, pendante["intervention_id"]),
            "action_proposee": (
                "m4_resoudre_revue_completion : verifiee (confirme) ou correction (nomme le "
                "problème)"
            ),
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


def _resume_completion_en_revue(reg: registre.Registre, intervention_id: str) -> str:
    base = f"Complétion en revue ({intervention_id})"
    signal = outbox.dernier_signal_variance(reg, intervention_id)
    if signal is None:
        return f"{base} — variance M6 non encore reçue"
    if signal["statut_variance"] != "evaluee":
        return f"{base} — variance M6 non finalisée ({signal['statut_variance']})"
    if signal["signal_critique"] is True:
        return f"{base} — écart matériaux CRITIQUE signalé par M6 (seuil {signal['seuil_pourcentage']})"
    # Atteint seulement si confirmer_verification a, pour une autre raison, échoué à vérifier
    # malgré un signal non critique (défensif : jamais supposé impossible, jamais deviné).
    return f"{base} — variance M6 évaluée sans signal critique"
