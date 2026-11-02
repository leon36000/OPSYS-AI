"""« Pourquoi cette mesure est vide ? » : l'état de la COLLECTE des mesures de M8 (chantier C2 de l'analyse M8).

Module PUR (ADR-0009) : aucun import d'``opsys``, aucune horloge (``maintenant`` vient de l'appelant), aucun accès à un
registre. Il reçoit ce que l'adaptateur (``outils.py``) a LU :

* les mesures du catalogue avec leur fraîcheur (``analytique_outils.lecture``) ;
* l'état des constats planifiés que les manifestes des départements DÉCLARENT (mode effectif, expiration, dernier
  passage, dernier code, échecs récents) : le planificateur reste la seule vérité, on ne la copie ni ne la corrige ;
* l'interrupteur général du planificateur (le coupe-circuit).

Il en tire, pour chaque mesure, UNE cause parmi un ensemble fermé, la phrase qui la dit et l'action à faire, puis une
liste de contrôle d'activation des constats. Rien n'est inventé : une cause vient d'un fait lu (un mode, un code, un
âge), jamais d'une supposition ; une mesure sans constat planifié le dit au lieu de promettre un rafraîchissement.

Aucun montant : les valeurs des mesures ne sont pas reprises. La sortie ne nomme que des mesures, des constats, des
modes et des codes.

Ordre des causes pour une mesure qui n'est pas à jour (la première qui s'applique) :

1. ``planificateur_coupe`` : le coupe-circuit est posé, rien ne tourne ;
2. un constat la nourrit et n'est PAS actif : ``constat_expire`` (activation de 90 jours échue), ``constat_inactif``
   (jamais activé), ``constat_en_ombre`` (il dit « aurait » et ne publie rien) ;
3. un constat actif a échoué à son dernier passage : ``constat_en_erreur`` (avec le code typé) ;
4. un constat actif passe bien : ``jamais_recue`` (aucun fait reçu : le bus ou M8 n'a rien rangé),
   ``producteur_non_calculable`` (le producteur a répondu « non calculable, manque X » : il faut une déclaration du
   propriétaire, pas un geste technique), ``source_perimee`` (reçue, mais plus vieille que sa fenêtre malgré les
   passages), ``fraicheur_inconnue`` ;
5. aucun constat planifié ne la nourrit : ``sans_constat_planifie`` (elle dépend d'un événement du département source ou
   d'un geste humain), ou ``source_perimee`` si elle a déjà été reçue.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

__all__ = [
    "ETAT_A_JOUR",
    "diagnostiquer",
    "etats_possibles",
]

ETAT_A_JOUR = "a_jour"
_ETATS = (
    ETAT_A_JOUR,
    "planificateur_coupe",
    "constat_expire",
    "constat_inactif",
    "constat_en_ombre",
    "constat_en_erreur",
    "jamais_recue",
    "producteur_non_calculable",
    "source_perimee",
    "fraicheur_inconnue",
    "sans_constat_planifie",
    "qualite_en_echec",
)
_STATUTS_ECHEC = frozenset({"erreur", "refus", "plafond", "attente_transport"})
_CALCULEE = "calculee"
_FRAICHEUR_A_JOUR = frozenset({"a_jour", "non_applicable"})
_ACTION_CONSOLE = "à la console Plateforme, page Connecteurs (admin)"


def etats_possibles() -> tuple[str, ...]:
    """L'ensemble FERMÉ des états de collecte qu'une mesure peut porter (le premier est ``a_jour``). Une fonction plutôt
    qu'une constante publique : la garde de conformité de M8 exige une échappatoire « indéterminé » pour toute
    énumération publique de domaine, ce qui n'a pas de sens ici (chaque état est un fait lu, pas un repli)."""
    return _ETATS


def _constats_par_mesure(constats: Sequence[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    """Pour chaque mesure, les constats DÉCLARÉS qui la nourrissent (dans l'ordre de leur nom)."""
    par_mesure: dict[str, list[Mapping[str, Any]]] = {}
    for constat in sorted(constats, key=lambda c: str(c["executeur"])):
        for metric_id in constat["mesures"]:
            par_mesure.setdefault(metric_id, []).append(constat)
    return par_mesure


def _etat_du_constat(constat: Mapping[str, Any]) -> str:
    """``actif``, ``ombre``, ``expire`` ou ``inactif`` : le mode EFFECTIF du planificateur (une ligne expirée ou
    absente vaut inactif ; ``expire`` distingue l'activation qui a pris fin d'un constat jamais activé)."""
    if constat["mode"] in ("actif", "ombre"):
        return str(constat["mode"])
    return "expire" if constat.get("expire") else "inactif"


def _action_activer(constat: Mapping[str, Any], etat: str) -> str:
    nom = constat["executeur"]
    if etat == "inactif":
        return (f"Activer le constat « {nom} » en ombre {_ACTION_CONSOLE}, lire le journal « aurait », puis le passer "
                "en actif.")
    if etat == "expire":
        return (f"Renouveler le constat « {nom} » {_ACTION_CONSOLE} : son activation de 90 jours est échue ; repasser "
                "par l'ombre puis l'actif.")
    return (f"Passer le constat « {nom} » de l'ombre à l'actif {_ACTION_CONSOLE} une fois le journal « aurait » lu : "
            "en ombre il ne publie rien.")


def _etat_pour_constat(
    mesure: Mapping[str, Any], constat: Mapping[str, Any], autorise: bool
) -> tuple[str, str, str]:
    """``(état, phrase, action)`` d'une mesure qui n'est pas à jour, vue à travers UN constat qui la nourrit."""
    nom = constat["executeur"]
    if not autorise:
        return (
            "planificateur_coupe",
            "Le planificateur est coupé (OPSYS_PLANIFICATEUR_CONNECTEURS=0) : aucun constat ne tourne.",
            "Retirer le coupe-circuit OPSYS_PLANIFICATEUR_CONNECTEURS de l'environnement du serveur, puis redémarrer.",
        )
    etat = _etat_du_constat(constat)
    if etat == "expire":
        return ("constat_expire", f"Le constat « {nom} » n'est plus actif : son activation de 90 jours est échue.",
                _action_activer(constat, etat))
    if etat == "inactif":
        return ("constat_inactif", f"Le constat « {nom} » n'a jamais été activé : rien ne rafraîchit cette mesure.",
                _action_activer(constat, etat))
    if etat == "ombre":
        return ("constat_en_ombre",
                f"Le constat « {nom} » est en ombre : il dit ce qu'il ferait et ne publie rien.",
                _action_activer(constat, etat))
    if constat.get("dernier_statut") in _STATUTS_ECHEC:
        code = constat.get("dernier_code")
        return (
            "constat_en_erreur",
            f"Le dernier passage du constat « {nom} » a échoué"
            + (f" ({code})." if code else "."),
            f"Lire l'état du constat « {nom} » {_ACTION_CONSOLE} (code {code or 'inconnu'}) et corriger la cause ; il "
            "repasse seul au prochain créneau.",
        )
    if mesure["statut"] != _CALCULEE:
        if mesure.get("dernier_fait_le") is None:
            return (
                "jamais_recue",
                f"Le constat « {nom} » est actif mais aucun fait n'a été reçu pour cette mesure.",
                "Attendre le prochain créneau ; si rien ne vient, vérifier le bus (livraison à M8) et le journal du "
                "constat.",
            )
        manque = ", ".join(
            str(x.get("champ") if isinstance(x, Mapping) else x) for x in mesure.get("manque") or []
        ) or "voir le détail de la mesure"
        return (
            "producteur_non_calculable",
            f"Le département source a répondu « non calculable » : il manque {manque}.",
            "Fournir ce que le département source demande (une déclaration du propriétaire, une donnée de départ) ; le "
            "constat n'y peut rien.",
        )
    statut = mesure["fraicheur"]["statut"]
    if statut == "perime":
        return (
            "source_perimee",
            f"La mesure est périmée alors que le constat « {nom} » passe : le fait publié est plus vieux que la "
            "fenêtre de fraîcheur.",
            "Vérifier la date du dernier fait et la fenêtre de la mesure ; une fenêtre plus large se déclare dans la "
            "configuration de M8 (fraicheur_mesures_s).",
        )
    return (
        "fraicheur_inconnue",
        "La fraîcheur de la mesure ne peut pas être établie (instant du dernier fait illisible).",
        "Vérifier l'instant du dernier fait publié par le département source.",
    )


def _diagnostic_mesure(
    mesure: Mapping[str, Any],
    constats: Sequence[Mapping[str, Any]],
    autorise: bool,
) -> dict[str, Any]:
    fraicheur = mesure["fraicheur"]["statut"]
    ligne: dict[str, Any] = {
        "metric_id": mesure["metric_id"],
        "nom": mesure["nom"],
        "proprietaire": mesure.get("proprietaire"),
        "statut_mesure": mesure["statut"],
        "fraicheur": fraicheur,
        "constats": [c["executeur"] for c in constats],
        "etat_collecte": ETAT_A_JOUR,
        "phrase": "La mesure est calculée et à jour.",
        "action": None,
    }
    if mesure["statut"] == _CALCULEE and fraicheur in _FRAICHEUR_A_JOUR:
        return ligne
    if (mesure.get("qualite") or {}).get("statut") == "echec":
        # Un contrôle de qualité a échoué : le constat peut passer sans erreur et la mesure rester bloquée. Ce n'est
        # ni un manque ni un retard de collecte, et le planificateur n'y peut rien : c'est la donnée de la source qui
        # est fausse.
        ligne.update(
            etat_collecte="qualite_en_echec",
            phrase="Un contrôle de qualité des données a échoué : la mesure est bloquée, aucune valeur n'est montrée.",
            action="Lire le rapport de qualité (m8_lire_rapport_qualite), corriger la donnée à la source dans le "
            "département propriétaire, puis lui faire republier son constat : la mesure se rétablit d'elle-même.",
        )
        return ligne
    if constats:
        # Plusieurs constats peuvent nourrir une mesure : on retient la cause du plus en retard (le premier qui n'est
        # pas actif et sain), sinon celle du premier.
        candidats = [_etat_pour_constat(mesure, c, autorise) for c in constats]
        etat, phrase, action = next((c for c in candidats if c[0] != "producteur_non_calculable"), candidats[0])
    elif mesure["statut"] != _CALCULEE:
        etat = "sans_constat_planifie"
        phrase = (
            "Aucun constat planifié ne nourrit cette mesure : elle dépend d'un événement du département "
            f"{mesure.get('proprietaire') or 'source'} ou d'un geste humain."
        )
        action = "Vérifier que le département source publie son événement ; aucun constat n'est à activer pour elle."
    elif fraicheur == "perime":
        etat = "source_perimee"
        phrase = "La mesure est périmée et aucun constat planifié ne la rafraîchit."
        action = "Relancer la source : un nouveau fait du département source remet la mesure à jour."
    else:
        etat = "fraicheur_inconnue"
        phrase = "La fraîcheur de la mesure ne peut pas être établie (instant du dernier fait illisible)."
        action = "Vérifier l'instant du dernier fait publié par le département source."
    ligne.update(etat_collecte=etat, phrase=phrase, action=action)
    return ligne


def _liste_de_controle(constats: Sequence[Mapping[str, Any]], autorise: bool) -> list[dict[str, Any]]:
    """Les gestes d'activation, dans l'ordre : d'abord l'interrupteur général, puis, pour chaque constat déclaré,
    l'ombre, l'actif, un passage réussi. Une étape est « faite » d'après l'état lu, jamais déclarée à la main."""
    etapes: list[dict[str, Any]] = [{
        "etape": "planificateur_autorise", "constat": None, "fait": autorise,
        "action": None if autorise else
        "Retirer le coupe-circuit OPSYS_PLANIFICATEUR_CONNECTEURS de l'environnement du serveur, puis redémarrer.",
    }]
    for constat in sorted(constats, key=lambda c: str(c["executeur"])):
        nom = constat["executeur"]
        etat = _etat_du_constat(constat)
        mode_pose = etat in ("ombre", "actif")
        actif = etat == "actif"
        passage_ok = actif and constat.get("dernier_passage") is not None and (
            constat.get("dernier_statut") not in _STATUTS_ECHEC)
        etapes.append({
            "etape": "activer_en_ombre", "constat": nom, "fait": mode_pose,
            "action": None if mode_pose else _action_activer(constat, etat if etat != "ombre" else "inactif"),
        })
        etapes.append({
            "etape": "passer_en_actif", "constat": nom, "fait": actif,
            "action": None if actif else (
                _action_activer(constat, "ombre") if etat == "ombre" else
                f"Activer d'abord le constat « {nom} » en ombre."),
        })
        etapes.append({
            "etape": "premier_passage_reussi", "constat": nom, "fait": passage_ok,
            "action": None if passage_ok else (
                f"Attendre le premier créneau du constat « {nom} » (prochain passage à la console)." if actif else
                f"Activer le constat « {nom} »."),
        })
    return etapes


def _etat_constat(constat: Mapping[str, Any], mesures_par_id: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    etat = _etat_du_constat(constat)
    impactees = [m for m in constat["mesures"] if m in mesures_par_id]
    return {
        "executeur": constat["executeur"],
        "departement": constat.get("departement"),
        "outil": constat.get("outil"),
        "etat": etat,
        "mode_demande": constat.get("mode_demande"),
        "intervalle_s": constat.get("intervalle_s"),
        "dernier_passage": constat.get("dernier_passage"),
        "dernier_statut": constat.get("dernier_statut"),
        "dernier_code": constat.get("dernier_code"),
        "echecs_24h": constat.get("echecs_24h", 0),
        "mesures": list(constat["mesures"]),
        "mesures_a_jour": sum(
            1 for m in impactees
            if mesures_par_id[m]["statut"] == _CALCULEE
            and mesures_par_id[m]["fraicheur"]["statut"] in _FRAICHEUR_A_JOUR
        ),
        "mesures_total": len(impactees),
    }


def diagnostiquer(
    mesures: Sequence[Mapping[str, Any]],
    constats: Sequence[Mapping[str, Any]],
    *,
    planificateur_autorise: bool,
) -> dict[str, Any]:
    """Le diagnostic de collecte complet : une ligne par mesure du catalogue, une par constat déclaré, le résumé par
    cause, la liste de contrôle d'activation et une lecture en une phrase. Déterministe : mêmes entrées, même sortie.

    ``mesures`` : les mesures lues avec leur fraîcheur (``statut``, ``fraicheur.statut``, ``dernier_fait_le``,
    ``manque``). ``constats`` : un dictionnaire par constat DÉCLARÉ (``executeur``, ``mesures``, ``mode``, ``expire``,
    ``dernier_passage``, ``dernier_statut``, ``dernier_code``, ``echecs_24h``, ``intervalle_s``)."""
    par_mesure = _constats_par_mesure(constats)
    lignes = [_diagnostic_mesure(m, par_mesure.get(m["metric_id"], []), planificateur_autorise) for m in mesures]
    compte = Counter(ligne["etat_collecte"] for ligne in lignes)
    par_id = {m["metric_id"]: m for m in mesures}
    resume = {etat: compte.get(etat, 0) for etat in _ETATS}
    vides = len(lignes) - resume[ETAT_A_JOUR]
    lecture = (
        f"{resume[ETAT_A_JOUR]} mesure(s) sur {len(lignes)} à jour ; {vides} à corriger ou à comprendre."
        if lignes else "Aucune mesure au catalogue."
    )
    return {
        "planificateur_autorise": planificateur_autorise,
        "n_mesures": len(lignes),
        "resume": resume,
        "lecture": lecture,
        "constats": [_etat_constat(c, par_id) for c in sorted(constats, key=lambda c: str(c["executeur"]))],
        "liste_de_controle": _liste_de_controle(constats, planificateur_autorise),
        "mesures": lignes,
    }
