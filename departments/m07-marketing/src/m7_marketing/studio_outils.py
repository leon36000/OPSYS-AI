"""Les outils M7 du studio créatif gouverné (images, logos, matériel imprimable, vidéo courte).

Chaque fonction est une enveloppe mince : elle établit QUI appelle (la plateforme, jamais un argument), assemble le
`studio.service.Studio` depuis le registre durable de M7 et appelle sa méthode. Les registres sont des journaux
append-only à chaîne de hachage de `opsys.stockage` (`briefs_studio`, `jobs_studio`, `provenance_studio`,
`actifs_studio`) ; les fichiers vivent sous `$OPSYS_HOME/studio/`.

Niveaux (ADR-0009) :
  - lectures : T0 ; brief, demande de fond, composition, contrôle, demande de revue, vectorisation d'un logo, export
    d'un visuel DÉJÀ approuvé vers le dossier d'actifs d'un site, rejet ou retrait : N2 (rien ne sort d'OPSYS) ;
  - approuver un visuel ou un logo pour publication ou impression : N3, décision du propriétaire (file d'approbation).
Aucun outil n'appelle un modèle, un réseau, une imprimerie ni un réseau social : « générer » consigne une DEMANDE que
l'exécuteur (`studio.executeur`, hors transaction, non branché à un planificateur dans cette version) traitera ; un
visuel approuvé est CONSIGNÉ (`VISUEL_APPROUVE_NON_PUBLIE`) et devient utilisable par le sas social et le site, qui
refusent tout visuel non composé, non contrôlé ou non approuvé. Aucun rôle d'appareil.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from opsys import stockage
from opsys.outils import Autonomie, Niveau, Outil
from opsys.stockage.moteur import dossier_opsys

from .brand import registre as registre_marque
from .publication_outils import _decideur, _horodatage
from .site import service as site_service
from .studio import actifs, executeur, logos, modeles, ocr, polices, service
from .usine import service as usine_service

STATUT_APPROUVE = "VISUEL_APPROUVE_NON_PUBLIE"
NOM_APPROUVER = "m7_approuver_visuel_studio"
REJ_MARQUE_NON_CONFIGUREE = "REJ-STUDIO-MARQUE-NON-CONFIGUREE"
REJ_MARQUE_FOURNIE = "REJ-STUDIO-BRIEF-MARQUE-FOURNIE"


def _journal(registre: tuple[str, str]):
    return stockage.maillons(*registre)


def _racine() -> Path:
    return dossier_opsys() / "studio"


def _studio(instant: dt.datetime) -> service.Studio:
    cnx = stockage.connexion_courante()
    return service.Studio(
        journaux=service.Journaux(
            briefs=_journal(("m07-marketing", "briefs_studio")),
            jobs=_journal(executeur.REGISTRE),
            provenance=_journal(("m07-marketing", "provenance_studio")),
            actifs=_journal(actifs.REGISTRE),
        ),
        fichiers=service.FichiersStudio(_racine()),
        polices=lambda production: polices.charger_dossier(_racine() / "polices", production=production),
        selection=lambda genre: modeles.selectionner(cnx, genre),
        verdict_licence=lambda fournisseur_id: modeles.verdict_courant(cnx, fournisseur_id),
        lecteurs=ocr.lecteurs_par_defaut,
        vectoriseur=logos.VectoriseurDouble(),
        maintenant=lambda: instant,
        par=usine_service._qui_appelle()[0],
    )


def _refus(code: str, chemin: str, detail: str) -> dict[str, Any]:
    return {"accepte": False, "refus": [{"code": code, "chemin": chemin, "detail": detail}]}


def _avec_studio(horodatage: str, geste) -> dict[str, Any]:
    instant = _horodatage(horodatage)
    if isinstance(instant, dict):
        return instant
    return geste(_studio(instant[1]))


def preparer_brief_creatif(
    brief: dict[str, Any], cle_idempotence: str, horodatage: str, brief_id: str | None = None
) -> dict[str, Any]:
    """N2 : valide et consigne un brief créatif. La marque vient du profil de marque existant, posée ici."""
    if isinstance(brief, dict) and "marque" in brief:
        return _refus(
            REJ_MARQUE_FOURNIE,
            "$.marque",
            "la marque vient du profil de marque du client, posée par l'outil : ne pas la fournir",
        )
    snapshot = registre_marque.lire_snapshot_marque()
    if snapshot.get("statut") != "configure":
        return _refus(
            REJ_MARQUE_NON_CONFIGUREE,
            "$",
            f"profil de marque {snapshot.get('statut')} : le configurer "
            f"d'abord ({snapshot.get('motif') or 'aucune marque'})",
        )
    profil = snapshot["profil"]
    complet = {
        **brief,
        "marque": {
            "nom": profil["name"],
            "couleurs": list(profil["colors"]),
            "langue": profil["langue"],
            "empreinte_profil": snapshot["preuve"]["sha256"],
        },
    }
    return _avec_studio(horodatage, lambda s: s.preparer_brief(complet, cle_idempotence, brief_id))


def demander_fond_studio(brief_id: str, horodatage: str, genre: str = "image", variante: int = 0) -> dict[str, Any]:
    """N2 : consigne une DEMANDE de fond généré (modèle choisi par le registre sous la politique de licence)."""
    resultat = _avec_studio(horodatage, lambda s: s.demander_fond(brief_id, genre, variante))
    if resultat.get("accepte"):
        resultat = {**resultat, "statut": "EN_ATTENTE_EXECUTEUR"}
    return resultat


def composer_visuel_studio(
    brief_id: str,
    horodatage: str,
    fond_actif_id: str | None = None,
    logo_actif_id: str | None = None,
    police_id: str | None = None,
    ppp: int | None = None,
) -> dict[str, Any]:
    """N2 : compose le visuel (gabarit déterministe) : texte, logo et mentions posés par le gabarit."""
    return _avec_studio(horodatage, lambda s: s.composer(brief_id, fond_actif_id, logo_actif_id, police_id, ppp))


def controler_visuel_studio(actif_id: str, horodatage: str) -> dict[str, Any]:
    """N2 : contrôle qualité (lecture de la sortie, contraste, zone de sécurité, impression, licence) ; rapport
    signé."""
    return _avec_studio(horodatage, lambda s: s.controler(actif_id))


def demander_revue_visuel_studio(actif_id: str, horodatage: str) -> dict[str, Any]:
    """N2 : met un visuel contrôlé conforme en revue. Un visuel non conforme ne passe pas en revue."""
    return _avec_studio(horodatage, lambda s: s.demander_revue(actif_id))


def approuver_visuel_studio(
    actif_id: str, composition_empreinte: str, rapport_empreinte: str, attestations: dict[str, Any], horodatage: str
) -> dict[str, Any]:
    """N3 : approbation humaine d'un visuel (ou d'un logo) pour publication ou impression ; consignée, jamais
    exécutée."""
    instant = _horodatage(horodatage)
    if isinstance(instant, dict):
        return instant
    acteur, refus = _decideur(NOM_APPROUVER)
    if acteur is None:
        return refus
    resultat = _studio(instant[1]).approuver(actif_id, composition_empreinte, rapport_empreinte, acteur, attestations)
    if resultat.get("accepte"):
        resultat = {**resultat, "statut": STATUT_APPROUVE}
    return resultat


def retirer_visuel_studio(actif_id: str, action: str, motif: str, horodatage: str) -> dict[str, Any]:
    """N2 : rejette un visuel qui n'est pas approuvé, ou révoque un visuel approuvé (restriction, jamais une
    publication)."""
    if action not in ("rejeter", "revoquer"):
        return _refus("REJ-STUDIO-ACTION", "$.action", "rejeter ou revoquer")
    return _avec_studio(
        horodatage, lambda s: s.rejeter(actif_id, motif) if action == "rejeter" else s.revoquer(actif_id, motif)
    )


def vectoriser_logo_studio(
    fictif: bool,
    horodatage: str,
    fond_actif_id: str | None = None,
    chemins: list[str] | None = None,
    vb_w: float | None = None,
    vb_h: float | None = None,
    seuil: int = 128,
) -> dict[str, Any]:
    """N2 : concept de logo vectoriel (depuis un concept raster, ou des chemins fournis). Aucune protection promise."""
    return _avec_studio(horodatage, lambda s: s.vectoriser_logo(fictif, fond_actif_id, chemins, vb_w, vb_h, seuil))


def exporter_visuel_vers_site(actif_id: str, site_id: str, nom: str, format: str, horodatage: str) -> dict[str, Any]:  # noqa: A002
    """N2 : copie un visuel APPROUVÉ vers le dossier d'actifs d'un site (`images/<nom>.<format>`) ; ne publie rien."""
    return _avec_studio(
        horodatage,
        lambda s: s.exporter_vers_site(
            actif_id, site_id, nom, format, lambda sid: site_service.dossier_site(sid) / "actifs"
        ),
    )


def lire_studio(
    actif_id: str | None = None, brief_id: str | None = None, limite: int = 20, media_sas: bool = False
) -> dict[str, Any]:
    """T0 : briefs et actifs du studio (états, rapports, provenance) ; `media_sas` rend le média d'un visuel
    approuvé."""
    s = _studio(dt.datetime.now(dt.UTC))
    resultat = s.lire(actif_id, brief_id, limite)
    if media_sas and actif_id is not None and resultat.get("accepte"):
        resultat = {**resultat, "media_sas": actifs.media_pour_sas(s.journaux.actifs, actif_id)}
    return resultat


# ---------------------------------------------------------------------------
# Manifeste
# ---------------------------------------------------------------------------
_HORODATAGE = {"type": "string", "description": "ISO 8601 avec fuseau (l'heure du serveur fait foi)."}
_ACTIF = {"type": "string", "description": "Identifiant d'un actif du studio (visuel-…, fond-…, logo-…)."}
_BRIEF_ID = {"type": "string", "description": "Identifiant d'un brief (brief-…) rendu par la préparation."}
_CLE = {"type": "string", "description": "Clé d'idempotence de 16 à 64 caractères [A-Za-z0-9_-] : une clé, un brief."}
_EMPREINTE = {"type": "string", "description": "Empreinte SHA-256 exacte rendue par le studio."}
_BRIEF = {
    "type": "object",
    "description": (
        "Brief créatif (opsys.studio.brief/v1) SANS marque : {schema, fictif, objet, gabarit (carte_affaires|affiche|"
        "banniere_social|couverture), format, canal, langues (['fr'] ou ['fr','en']), textes {titre|sous_titre|"
        "appel_action: {fr, en?}}, elements_critiques [{type: "
        "telephone|courriel|adresse|licence_rbq|neq|prix|site_web, "
        "valeur, source, valide_jusqu_au (prix)}], mentions_obligatoires [texte mot pour mot], fond {mode: uni|degrade|"
        "genere, sujet, ambiance, rendu, graine}, couleur (rvb|cmjn), ppp?, logo_actif_id?}. Les éléments critiques "
        "et les "
        "mentions sont posés tels quels par le gabarit, jamais confiés à un modèle."
    ),
}
_ATTESTATIONS = {
    "type": "object",
    "description": (
        "Attestations de la PERSONNE qui approuve : visuel {elements_critiques_verifies, aucun_visage_ni_plaque_"
        "identifiable, rendu_relu_a_l_ecran : true ; realiste : booléen ; langue_francaise_validee} ; logo "
        "{avertissement_logo_lu : true, note_contribution_humaine (20 à 600 caractères), recherche_anteriorite : faite|"
        "renvoyee_a_un_agent_de_marques}."
    ),
}


def _objet(proprietes: dict[str, Any], requis: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": proprietes, "required": requis, "additionalProperties": False}


def outils() -> tuple[Outil, ...]:
    return (
        Outil(
            nom="m7_preparer_brief_creatif",
            description=(
                "Valide et consigne un BRIEF créatif (objet, gabarit, format, textes, éléments critiques typés, "
                "mentions, "
                "fond). La marque vient du profil de marque existant ; les éléments critiques (téléphone, adresse, "
                "licence RBQ, NEQ, prix) sont des données structurées posées par le gabarit, jamais confiées à un "
                "modèle. Contraintes légales : français nettement prédominant (heuristique). Ne génère rien."
            ),
            parametres=_objet(
                {"brief": _BRIEF, "cle_idempotence": _CLE, "horodatage": _HORODATAGE, "brief_id": _BRIEF_ID},
                ["brief", "cle_idempotence", "horodatage"],
            ),
            fonction=preparer_brief_creatif,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m7_demander_fond_studio",
            description=(
                "Consigne une DEMANDE de fond généré (image ou clip) pour un brief : le modèle est choisi par le "
                "registre "
                "de fournisseurs sous la politique de licence (seuil de revenu, territoire, service à des tiers, usage "
                "commercial) ; aucun repli. L'invite interdit tout texte, logo ou signature. AUCUN modèle n'est "
                "appelé : "
                "un exécuteur hors transaction génère, journalise la provenance (modèle, version, graine, invite, "
                "licence) "
                "et marque le fond « généré par IA »."
            ),
            parametres=_objet(
                {
                    "brief_id": _BRIEF_ID,
                    "horodatage": _HORODATAGE,
                    "genre": {"type": "string", "enum": list(modeles.CAPACITES)},
                    "variante": {"type": "integer", "minimum": 0, "maximum": 99},
                },
                ["brief_id", "horodatage"],
            ),
            fonction=demander_fond_studio,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m7_composer_visuel_studio",
            description=(
                "Compose le visuel d'un brief par un GABARIT déterministe (carte d'affaires, affiche, bannière, "
                "couverture) : "
                "texte, logo et mentions posés par le gabarit, polices OFL épinglées, fond perdu et zone de sécurité ; "
                "l'image générée n'est que le fond. Produit SVG, PNG et (impression) PDF RVB (pas PDF/X, pas CMJN)."
            ),
            parametres=_objet(
                {
                    "brief_id": _BRIEF_ID,
                    "horodatage": _HORODATAGE,
                    "fond_actif_id": _ACTIF,
                    "logo_actif_id": _ACTIF,
                    "police_id": {"type": "string"},
                    "ppp": {"type": "integer", "minimum": 72, "maximum": 600},
                },
                ["brief_id", "horodatage"],
            ),
            fonction=composer_visuel_studio,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m7_controler_visuel_studio",
            description=(
                "Contrôle qualité d'un visuel avant la revue : relit la SORTIE (OCR : zéro écart sur téléphone, "
                "adresse, "
                "licence, prix, mentions ; aucune donnée critique hors du brief), contraste, taille minimale, zone de "
                "sécurité, fond perdu, résolution, reproductibilité, marquage IA, licence revérifiée. Rapport signé "
                "par "
                "empreinte ; la nature du lecteur (réel ou double) est consignée."
            ),
            parametres=_objet({"actif_id": _ACTIF, "horodatage": _HORODATAGE}, ["actif_id", "horodatage"]),
            fonction=controler_visuel_studio,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m7_demander_revue_visuel_studio",
            description=(
                "Met en REVUE un visuel (ou un logo) dont le contrôle est conforme. Un contrôle avec un constat "
                "critique "
                "en échec est refusé : le visuel ne passe pas en revue."
            ),
            parametres=_objet({"actif_id": _ACTIF, "horodatage": _HORODATAGE}, ["actif_id", "horodatage"]),
            fonction=demander_revue_visuel_studio,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom=NOM_APPROUVER,
            description=(
                "DÉCISION DE LA DIRECTION (N3) : approuve un visuel ou un logo pour publication ou impression, par "
                "l'empreinte exacte de la composition ET du rapport de contrôle, avec les attestations de la personne "
                "(éléments critiques vérifiés à la source, aucun visage ni plaque identifiable, allure réaliste ou "
                "non). "
                "Un agent ne peut que la déposer dans la file ; approuvé, le visuel est CONSIGNÉ "
                "(VISUEL_APPROUVE_NON_PUBLIE) et devient utilisable par le sas social et le site ; rien n'est publié "
                "ni "
                "imprimé. Un visuel non fictif exige une lecture par un OCR réel."
            ),
            parametres=_objet(
                {
                    "actif_id": _ACTIF,
                    "composition_empreinte": _EMPREINTE,
                    "rapport_empreinte": _EMPREINTE,
                    "attestations": _ATTESTATIONS,
                    "horodatage": _HORODATAGE,
                },
                ["actif_id", "composition_empreinte", "rapport_empreinte", "attestations", "horodatage"],
            ),
            fonction=approuver_visuel_studio,
            autonomie=Autonomie.T1,
            niveau=Niveau.N3,
        ),
        Outil(
            nom="m7_retirer_visuel_studio",
            description=(
                "Rejette un visuel qui n'est pas approuvé, ou révoque un visuel approuvé (il cesse d'être utilisable "
                "par "
                "les sas). Une publication déjà sortie ne se retire pas d'ici."
            ),
            parametres=_objet(
                {
                    "actif_id": _ACTIF,
                    "action": {"type": "string", "enum": ["rejeter", "revoquer"]},
                    "motif": {"type": "string", "maxLength": 300},
                    "horodatage": _HORODATAGE,
                },
                ["actif_id", "action", "motif", "horodatage"],
            ),
            fonction=retirer_visuel_studio,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m7_vectoriser_logo_studio",
            description=(
                "Produit un CONCEPT de logo vectoriel (depuis un concept raster du studio, ou des chemins M L H V C Q "
                "Z "
                "fournis) avec déclinaisons monochrome et négatif et contrôle de forme. AVERTISSEMENT dans chaque "
                "sortie : "
                "aucune protection juridique n'est promise ; la voie est la marque de commerce (À valider auprès d'un "
                "avocat ou d'un agent de marques). vtracer et svgo ne sont pas installés : plan documenté."
            ),
            parametres=_objet(
                {
                    "fictif": {"type": "boolean"},
                    "horodatage": _HORODATAGE,
                    "fond_actif_id": _ACTIF,
                    "chemins": {"type": "array", "items": {"type": "string"}, "maxItems": 200},
                    "vb_w": {"type": "number"},
                    "vb_h": {"type": "number"},
                    "seuil": {"type": "integer", "minimum": 1, "maximum": 254},
                },
                ["fictif", "horodatage"],
            ),
            fonction=vectoriser_logo_studio,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m7_exporter_visuel_vers_site",
            description=(
                "Copie un visuel APPROUVÉ (PNG ou SVG) vers le dossier d'actifs d'un site (images/<nom>.<format>) et "
                "rend "
                "l'entrée « images » du schéma de site. Le site refuse de toute façon une image du studio non "
                "approuvée. "
                "Ne publie rien."
            ),
            parametres=_objet(
                {
                    "actif_id": _ACTIF,
                    "site_id": {"type": "string"},
                    "nom": {"type": "string"},
                    "format": {"type": "string", "enum": ["png", "svg"]},
                    "horodatage": _HORODATAGE,
                },
                ["actif_id", "site_id", "nom", "format", "horodatage"],
            ),
            fonction=exporter_visuel_vers_site,
            autonomie=Autonomie.T1,
            niveau=Niveau.N2,
        ),
        Outil(
            nom="m7_lire_studio",
            description=(
                "Lit les briefs et les actifs du studio : états, rapports de contrôle, provenance, intégrité des "
                "journaux. "
                "Avec media_sas, rend le média (champs du sas social) d'un visuel APPROUVÉ. Lecture seule."
            ),
            parametres=_objet(
                {
                    "actif_id": _ACTIF,
                    "brief_id": _BRIEF_ID,
                    "limite": {"type": "integer", "minimum": 1, "maximum": 50},
                    "media_sas": {"type": "boolean"},
                },
                [],
            ),
            fonction=lire_studio,
        ),
    )
