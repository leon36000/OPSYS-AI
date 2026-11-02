"""Adaptateur des outils d'apprentissage des durées de M3 : lit les registres, applique les modes et les approbations.

Toute la logique d'apprentissage est pure (``apprentissage_durees``, ``apprentissage_journal``) ; ce module choisit le
support durable (le journal ``stockage.maillons("m03-estimation", "apprentissage_durees")``, aucune table nouvelle),
relit les observations certifiées par les voies EXISTANTES (``calibration_raccord`` : WCT de M4 relus au bus, devis
accepté, estimation d'origine, chaîne M3 valide), joint l'équipe pseudonymisée (outil de M4) et la complexité déclarée,
lit la politique déclarée de ``department.yaml`` et le mode EFFECTIF du département, puis déclare les outils.

Règles de mode (``opsys.politiques``) :

* ``ombre`` : la calibration est calculée, journalisée et MONTRÉE (``apprentissage_duree.statut == "ombre"``), mais
  aucune
  mise en vigueur automatique n'a lieu et une version déjà ``auto`` n'est plus appliquée tant que le mode est l'ombre.
  Une version approuvée par une PERSONNE reste appliquée : c'est la décision explicite d'un humain.
* ``supervise`` et ``autonome`` : une candidate ``auto_applicable`` est mise en vigueur sans personne, pour le BROUILLON
  d'estimation seulement ; l'envoi au client reste une décision N4 du propriétaire (inchangée). Toute autre candidate
  (``approbation_requise``) attend ``m3_approuver_calibration_duree`` (N3, une personne, la file d'approbation).

Aucun de ces outils n'est ouvert à un appareil (``roles_appareil`` vide). Aucun événement n'est publié : le journal
est la trace. Les journaux ne contiennent ni nom, ni courriel, ni identifiant de membre d'équipe (pseudonymes).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC
from pathlib import Path
from typing import Any

import yaml

from opsys import approbations, contexte, stockage
from opsys.approbations import approbateur_en_cours
from opsys.outils import Autonomie, Niveau, Outil

from . import apprentissage_durees as ad
from . import apprentissage_journal as aj

_DEPARTEMENT = "m03-estimation"
_MANIFESTE = Path(__file__).resolve().parents[2] / "department.yaml"
_ROLES_DECISION = frozenset({"nathan_owner", "admin"})
_MAX_WCT_M4 = 200
# Ce que le journal garde : les candidates qui appellent une suite. « stable » et « insuffisante » se lisent dans le
# rapport (m3_lire_apprentissage_durees) sans gonfler le journal à chaque calcul.
_DECISIONS_JOURNALISEES = ("auto_applicable", "approbation_requise", "refusee_hors_bornes")


def registre_apprentissage() -> stockage.MaillonsDurables:
    """Journal append-only CAS des versions d'apprentissage des durées (jamais mis en cache)."""
    return stockage.maillons(_DEPARTEMENT, "apprentissage_durees")


def _manifeste() -> dict[str, Any]:
    try:
        brut = yaml.safe_load(_MANIFESTE.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return brut if isinstance(brut, dict) else {}


def _politique_brute() -> Any:
    """``configuration.apprentissage_durees`` de ``department.yaml``, tel quel (les tests le remplacent)."""
    configuration = _manifeste().get("configuration")
    return configuration.get("apprentissage_durees") if isinstance(configuration, dict) else None


def _mode_manifeste() -> str:
    mode = _manifeste().get("mode")
    return mode if isinstance(mode, str) else "ombre"


def mode_effectif() -> str:
    """Mode du département : celui fixé depuis le tableau de bord s'il existe, sinon celui du manifeste. Sans
    connexion (hors transaction), le plus prudent : l'ombre."""
    cnx = stockage.connexion_courante()
    if cnx is None:
        return "ombre"
    try:
        return approbations.mode_effectif(cnx, _DEPARTEMENT, _mode_manifeste())
    except ValueError:
        return "ombre"


def _maintenant(horodatage: Any) -> tuple[str | None, str | None]:
    if not isinstance(horodatage, str) or ad.instant_utc(horodatage) is None:
        return None, "horodatage_utc_invalide"
    return horodatage, None


# --------------------------------------------------------------------------------------- observations
def _equipes_par_wct(wct_ids: list[str]) -> dict[str, str | None]:
    """Équipe pseudonymisée de chaque WCT (outil de M4, sous l'identité de M3). Toute indisponibilité rend un
    dictionnaire vide : les observations restent, sans équipe, donc hors des agrégats d'équipe."""
    if not wct_ids:
        return {}
    try:
        from opsys.capacites import Capacites
        from opsys.departements import charger_departements

        departements = charger_departements()
        cibles = {nom: departements[nom] for nom in (_DEPARTEMENT, "m04-field-ops")}
        capacites = Capacites(cibles, stockage.transaction, appelant=_DEPARTEMENT, limite_sortie=200_000, memoire=False)
        sortie: dict[str, str | None] = {}
        for debut in range(0, len(wct_ids), _MAX_WCT_M4):
            reponse = capacites.appeler("m4_lire_equipes_faits_m3", {"wct_ids": wct_ids[debut:debut + _MAX_WCT_M4]})
            resultat = reponse.get("resultat") if isinstance(reponse, dict) and reponse.get("ok") else None
            if not isinstance(resultat, dict):
                return {}
            for ligne in resultat.get("equipes", []):
                if isinstance(ligne, dict) and isinstance(ligne.get("wct_id"), str):
                    sortie[ligne["wct_id"]] = ligne.get("equipe_ref")
        return sortie
    except (ImportError, KeyError, ValueError, TypeError):
        return {}


def observations_enrichies(
    rapport_cohortes: Callable[..., dict[str, Any]], journal: Any, maintenant_utc: str,
) -> tuple[list[dict[str, Any]], dict[str, Any], str | None]:
    """``(observations, baselines par cohorte, raison)``. Les observations sont celles de la jointure existante
    (statut vérifié par M4, liaison exacte au devis accepté, chaîne M3 valide), complétées de l'équipe pseudonymisée et
    de la complexité déclarée. ``baselines`` : le taux du barème en vigueur lors de la plus récente estimation de
    chaque cohorte (le ``taux_minutes_par_unite_source`` de la trace, jamais le taux déjà calibré)."""
    rapport = rapport_cohortes(maintenant_utc, _inclure_observations=True)
    if rapport.get("statut") not in ("candidate", "insuffisant"):
        return [], {}, "source_observations_refusee:" + ",".join(map(str, rapport.get("raisons", ["inconnue"])))
    brutes = list(rapport.get("observations_qualifiees", []))
    contenu, raison = aj.etat(journal)
    if raison or contenu is None:
        return [], {}, raison or "journal_illisible"
    equipes = _equipes_par_wct(sorted({o["wct_id"] for o in brutes if isinstance(o, dict) and "wct_id" in o}))
    baselines: dict[tuple[str, str], tuple[str, Any]] = {}
    enrichies = []
    for brute in brutes:
        enrichie = dict(brute)
        enrichie["equipe_ref"] = equipes.get(brute["wct_id"])
        enrichie["complexite"] = contenu["complexites"].get(aj.empreinte_chantier_id(brute["chantier_id"]))
        enrichies.append(enrichie)
        cle = (brute["type_service"], brute["unite_quantite"])
        source = brute.get("taux_minutes_par_unite_source")
        fin = brute.get("horodatage_completion")
        if source is not None and (cle not in baselines or fin >= baselines[cle][0]):
            baselines[cle] = (fin, source)
    return enrichies, {cle: format(valeur[1], "f") for cle, valeur in baselines.items()}, None


# ------------------------------------------------------------------------------------------- calcul
def _courant(journal: Any, type_service: str, unite: str, baseline: str) -> tuple[dict[str, Any] | None, str | None]:
    """Version en vigueur de la cohorte, seulement si elle a été décidée contre le MÊME barème qu'aujourd'hui."""
    actif, raison = aj.version_active(journal, type_service, unite)
    if raison:
        return None, raison
    if actif is None or ad.controler_application(
        actif, type_service=type_service, unite_quantite=unite, taux_baseline=baseline,
    ) is not None:
        return None, None
    return actif, None


def calculer(
    rapport_cohortes: Callable[..., dict[str, Any]], *, horodatage: str, ecrire: bool,
) -> dict[str, Any]:
    """Calcule les candidates de toutes les cohortes et l'instantané des équipes. ``ecrire=False`` : lecture seule (rien
    n'est inscrit, rien n'est mis en vigueur). ``ecrire=True`` : inscrit au journal, puis met en vigueur les candidates
    ``auto_applicable`` si, et seulement si, le mode n'est pas l'ombre."""
    maintenant, refus = _maintenant(horodatage)
    if refus:
        return {"statut": "refuse", "raisons": [refus]}
    politique, verdict = ad.lire_politique(_politique_brute())
    if verdict is not None or politique is None:
        return {"statut": "refuse", "raisons": ["politique_apprentissage_absente"], "verdict": verdict}
    journal = registre_apprentissage()
    mode = mode_effectif()
    observations, baselines, raison = observations_enrichies(rapport_cohortes, journal, maintenant or horodatage)
    if raison:
        return {"statut": "refuse", "raisons": [raison]}
    preparees = ad.preparer_observations(observations, maintenant_utc=horodatage, politique=politique)
    if preparees["statut"] != "ok":
        return {"statut": "refuse", "raisons": preparees["raisons"]}
    cohortes = []
    for (type_service, unite), baseline in sorted(baselines.items()):
        courant, raison = _courant(journal, type_service, unite, baseline)
        if raison:
            return {"statut": "refuse", "raisons": [raison]}
        rapport = ad.calculer_cohorte(
            preparees["lignes"], type_service=type_service, unite_quantite=unite, taux_baseline=baseline,
            taux_courant=None if courant is None else courant["taux_applique"],
            regime_depuis_utc=None if courant is None else courant.get("regime_depuis_utc"), politique=politique,
        )
        entree: dict[str, Any] = {"rapport": rapport, "mode": mode, "ecrit": False, "active": False}
        if ecrire and rapport["decision"] in _DECISIONS_JOURNALISEES:
            inscription = aj.enregistrer_calcul(
                journal, rapport, politique_sha256=politique["empreinte"], maintenant_utc=horodatage, mode=mode,
            )
            if inscription["statut"] == "refuse":
                return {"statut": "refuse", "raisons": inscription["raisons"]}
            version = inscription["version"]
            entree.update({"ecrit": inscription["statut"] == "inscrite", "version_id": version["version_id"]})
            if rapport["decision"] == "auto_applicable":
                activation = aj.activer(
                    journal, version["version_id"], mode_activation="auto", approbateur=None,
                    maintenant_utc=horodatage, auto_autorise=mode != "ombre",
                )
                entree["active"] = activation["accepte"] is True
                entree["activation"] = activation
        cohortes.append(entree)
    equipes = ad.performance_equipes(preparees["lignes"], politique=politique)
    instantane = None
    if ecrire and equipes.get("statut") == "ok" and (equipes["equipes"] or equipes["strates"]):
        instantane = aj.enregistrer_performance(
            journal, equipes, politique_sha256=politique["empreinte"], maintenant_utc=horodatage,
        )
    return {
        "statut": "ok", "mode": mode, "calcule_le": horodatage, "politique_sha256": politique["empreinte"],
        "observations": {"retenues": len(preparees["lignes"]), "exclusions": preparees["exclusions"],
                         "rejeux": preparees["rejeux"]},
        "cohortes": cohortes, "equipes": equipes, "instantane_equipes": instantane, "ecrit": ecrire,
    }


# --------------------------------------------------------------------------------- application à une demande
def version_pour_demande(
    type_service: str, unite: Any, taux_baseline: Any,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    """``(version à appliquer, candidate à montrer en ombre, raison)`` pour une demande d'estimation. Lecture seule.

    * mode ombre : jamais de version ``auto`` appliquée ; la plus récente candidate activable est MONTRÉE ;
    * sinon : la version en vigueur de la cohorte (auto ou approuvée par une personne) ;
    * journal altéré : rien n'est appliqué et la raison est rendue (l'estimation, elle, ne dépend pas du journal)."""
    if not isinstance(unite, str) or not unite:
        return None, None, None
    journal = registre_apprentissage()
    if len(journal) == 0:
        return None, None, None
    contenu, raison = aj.etat(journal)
    if raison or contenu is None:
        return None, None, raison or "journal_apprentissage_invalide"
    actif, raison = aj.version_active(journal, type_service, unite)
    if raison:
        return None, None, raison
    if mode_effectif() != "ombre":
        return actif, None, None
    if actif is not None:
        # Mode ombre : une version approuvée par une personne reste appliquée ; une version automatique est gelée et
        # seulement montrée.
        return (actif, None, None) if actif["mode_activation"] == "humain" else (None, actif, None)
    pile = contenu["piles"].get(f"{type_service}\x1f{unite}", [])
    parent = pile[-1]["version_id"] if pile else None
    candidates = [
        v for v in contenu["versions"].values()
        if v["cohorte"] == {"type_service": type_service, "unite_quantite": unite}
        and v["decision"] in ("auto_applicable", "approbation_requise") and v["parent_version_id"] == parent
    ]
    return (None, {**candidates[-1], "mode_activation": None}, None) if candidates else (None, None, None)


# ------------------------------------------------------------------------------------------------ outils
def construire(*, rapport_cohortes: Callable[..., dict[str, Any]]) -> tuple[Outil, ...]:
    def lire(horodatage: str) -> dict[str, Any]:
        return calculer(rapport_cohortes, horodatage=horodatage, ecrire=False)

    def calculer_et_inscrire(horodatage: str) -> dict[str, Any]:
        return calculer(rapport_cohortes, horodatage=horodatage, ecrire=True)

    def approuver(version_id: str) -> dict[str, Any]:
        cnx = stockage.connexion_courante()
        signataire = approbateur_en_cours(cnx, "m3_approuver_calibration_duree", _DEPARTEMENT, roles=_ROLES_DECISION)
        instant = approbations.instant_de_la_decision_en_cours(cnx)
        if signataire is None or instant is None:
            return {"accepte": False, "raisons": ["approbateur_humain_requis"]}
        return aj.activer(
            registre_apprentissage(), version_id, mode_activation="humain", approbateur=signataire.personne,
            maintenant_utc=instant.astimezone(UTC).isoformat().replace("+00:00", "Z"), auto_autorise=False,
        )

    def annuler(type_service: str, unite_quantite: str, version_attendue: str, raison: str) -> dict[str, Any]:
        cnx = stockage.connexion_courante()
        signataire = approbateur_en_cours(cnx, "m3_annuler_calibration_duree", _DEPARTEMENT, roles=_ROLES_DECISION)
        instant = approbations.instant_de_la_decision_en_cours(cnx)
        if signataire is None or instant is None:
            return {"accepte": False, "raisons": ["approbateur_humain_requis"]}
        return aj.retirer(
            registre_apprentissage(), {"type_service": type_service, "unite_quantite": unite_quantite},
            version_attendue=version_attendue, par=signataire.personne, raison=raison,
            maintenant_utc=instant.astimezone(UTC).isoformat().replace("+00:00", "Z"),
        )

    def declarer_complexite(chantier_id: str, complexite: str, horodatage: str) -> dict[str, Any]:
        maintenant, refus = _maintenant(horodatage)
        if refus:
            return {"accepte": False, "raisons": [refus]}
        politique, verdict = ad.lire_politique(_politique_brute())
        if verdict is not None or politique is None:
            return {"accepte": False, "raisons": ["politique_apprentissage_absente"], "verdict": verdict}
        cnx = stockage.connexion_courante()
        signataire = approbateur_en_cours(cnx, "m3_declarer_complexite_chantier", _DEPARTEMENT, roles=_ROLES_DECISION)
        origine = contexte.departement_origine_appelante() or _DEPARTEMENT
        auteur = signataire.personne if signataire is not None else origine
        return aj.declarer_complexite(
            registre_apprentissage(), chantier_id=chantier_id, complexite=complexite, par=auteur,
            maintenant_utc=maintenant or horodatage, echelle=politique["complexites"],
        )

    def lire_performance(type_service: str) -> dict[str, Any]:
        origine = contexte.departement_origine_appelante()
        if origine not in ("m04-field-ops", _DEPARTEMENT):
            return {"statut": "refuse", "raisons": ["departement_appelant_non_autorise"], "equipes": []}
        instantane, raison = aj.derniere_performance(registre_apprentissage())
        if raison:
            return {"statut": "refuse", "raisons": [raison], "equipes": []}
        if instantane is None:
            return {"statut": "aucun_instantane", "equipes": [],
                    "a_faire": "calculer avec m3_calculer_apprentissage_durees (politique à déclarer au préalable)"}
        return {
            "statut": "ok", "calcule_le": instantane["calcule_le"], "politique_sha256": instantane["politique_sha256"],
            "equipes": [e for e in instantane["equipes"] if e.get("type_service") == type_service],
            "limite": "Agrégat d'équipe par type de travaux, jamais une note de personne ; l'humain affecte.",
        }

    horodatage = {"type": "string", "format": "date-time", "maxLength": 40,
                  "description": "instant ISO 8601 en UTC (Z) du calcul, fourni par l'appelant"}
    return (
        Outil(
            nom="m3_lire_apprentissage_durees",
            description=(
                "Montre ce que le terrain apprend sur les durées SUR SITE (jamais le déplacement), sans rien écrire : "
                "par type de travaux, taux appris en minutes par unité, intervalle, nombre de chantiers, dérive, "
                "décision (stable, insuffisante, auto_applicable, approbation_requise, refusee_hors_bornes) et indices "
                "de rapidité par équipe et type (jamais par personne). Exige la politique déclarée dans "
                "department.yaml/configuration/apprentissage_durees ; sans elle, dit quoi déclarer."
            ),
            parametres={"type": "object", "properties": {"horodatage": horodatage}, "required": ["horodatage"],
                        "additionalProperties": False},
            fonction=lire, autonomie=Autonomie.T0,
        ),
        Outil(
            nom="m3_calculer_apprentissage_durees",
            description=(
                "Calcule les candidates d'apprentissage des durées depuis les temps certifiés du terrain, les inscrit "
                "au journal append-only et, hors mode ombre, met en vigueur les petits ajustements dans les bornes "
                "déclarées (brouillon d'estimation seulement ; l'envoi au client reste approuvé par le propriétaire). "
                "Dérive ou variation au-delà du palier : la candidate attend m3_approuver_calibration_duree. En mode "
                "ombre : calculé et montré, jamais appliqué. Ne change ni prix, ni coût, ni marge."
            ),
            parametres={"type": "object", "properties": {"horodatage": horodatage}, "required": ["horodatage"],
                        "additionalProperties": False},
            fonction=calculer_et_inscrire, autonomie=Autonomie.T1, niveau=Niveau.N2,
        ),
        Outil(
            nom="m3_approuver_calibration_duree",
            description=(
                "Met en vigueur une candidate d'apprentissage des durées qui exige une personne (dérive ou variation "
                "au-delà du palier). Décision N3 prise par une personne dans la file d'approbation : l'appel demande "
                "l'approbation, il n'active rien. Les estimations passées ne sont pas réécrites."
            ),
            parametres={"type": "object", "properties": {"version_id": {"type": "string", "minLength": 64,
                                                                         "maxLength": 64}},
                        "required": ["version_id"], "additionalProperties": False},
            fonction=approuver, autonomie=Autonomie.T1, niveau=Niveau.N3,
        ),
        Outil(
            nom="m3_annuler_calibration_duree",
            description=(
                "Retour arrière en une opération : retire la version en vigueur d'un type de travaux (celle qu'on "
                "nomme) et rétablit la précédente, ou le barème. Décision N3 d'une personne ; le journal garde tout."
            ),
            parametres={"type": "object", "properties": {
                "type_service": {"type": "string", "minLength": 1, "maxLength": 128},
                "unite_quantite": {"type": "string", "minLength": 1, "maxLength": 128},
                "version_attendue": {"type": "string", "minLength": 64, "maxLength": 64},
                "raison": {"type": "string", "minLength": 1, "maxLength": 300},
            }, "required": ["type_service", "unite_quantite", "version_attendue", "raison"],
                "additionalProperties": False},
            fonction=annuler, autonomie=Autonomie.T1, niveau=Niveau.N3,
        ),
        Outil(
            nom="m3_declarer_complexite_chantier",
            description=(
                "Déclare la difficulté d'un chantier dans l'échelle de l'entreprise (department.yaml/configuration/"
                "apprentissage_durees/complexites). Sert seulement à comparer les équipes à difficulté égale : sans "
                "elle, la complexité est « inconnue ». Décision N3 : une déclaration influence un indice d'équipe."
            ),
            parametres={"type": "object", "properties": {
                "chantier_id": {"type": "string", "minLength": 1, "maxLength": 128},
                "complexite": {"type": "string", "minLength": 1, "maxLength": 30}, "horodatage": horodatage,
            }, "required": ["chantier_id", "complexite", "horodatage"], "additionalProperties": False},
            fonction=declarer_complexite, autonomie=Autonomie.T1, niveau=Niveau.N3,
        ),
        Outil(
            nom="m3_lire_performance_equipes",
            description=(
                "Dernier instantané des indices de rapidité par COUPLE (équipe pseudonymisée, type de travaux), "
                "à difficulté comparable, avec intervalle et nombre de chantiers. Réservé à M4 (indice d'adéquation) "
                "et à M3. Équipe sans historique suffisant : non évaluable, jamais zéro. Aucune note de personne."
            ),
            parametres={"type": "object", "properties": {"type_service": {"type": "string", "minLength": 1,
                                                                           "maxLength": 128}},
                        "required": ["type_service"], "additionalProperties": False},
            fonction=lire_performance, autonomie=Autonomie.T0,
        ),
    )
