"""Outils M10 de Mnémo : modèle de soi de l'entreprise, graphe de connaissances d'entités, leçons gouvernées.

M10 est le gardien : il propose, mesure et relie ; une PERSONNE confirme ce qui engage. La logique vit dans
`opsys.mnemo`
(socle, comme les bases de connaissances) ; ce module ne fait que l'adaptation : registres durables, droits, événements.
Niveaux (ADR-0009 §4), sans exception :

- lecture (`m10_lire_soi`, `m10_graphe_voisinage`, `m10_graphe_chemin`, `m10_graphe_pourquoi`, `m10_graphe_etat`,
  `m10_lire_lecons`, `m10_surveiller_lecons`) : T0 / N0 ;
- propositions, constructions et mesures internes réversibles, append-only (`m10_construire_soi`,
  `m10_proposer_enonce_soi`, `m10_proposer_arete_graphe`, `m10_synchroniser_graphe`, `m10_extraire_lecons`,
  `m10_evaluer_lecon`) : T1 / **N2** ;
- tout ce qui CONFIRME, REJETTE, RETIRE, DÉCLARE ou DÉCIDE (`m10_confirmer_enonce_soi`, `m10_rejeter_enonce_soi`,
  `m10_retirer_enonce_soi`, `m10_declarer_enonce_direction`, `m10_confirmer_arete_graphe`, `m10_rejeter_arete_graphe`,
  `m10_fermer_arete_graphe`, `m10_decider_lecon`) : T1 / **N3**, une PERSONNE (jeton d'appareil admin, ou approbation
  humaine dans la file). Un agent en mode « supervisé » ou « autonome » reçoit `REJ-MNEMO-HUMAIN-REQUIS`.

Aucun outil n'est ouvert à un appareil (`roles_appareil` vide). Le graphe contient des pseudonymes de clients
(CLIENT_PRIVATE pour M10) : il n'est lu que par les outils `m10_graphe_*` et la console d'administration, jamais par
un paquet de contexte. Ce module n'effectue aucun appel réseau ni aucun appel de modèle.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy import select

from opsys import evenements, stockage
from opsys.mnemo import codes, lecons, registres, service, soi, soi_dimensions, soi_sources
from opsys.mnemo.codes import ErreurMnemo
from opsys.mnemo.graphe import DemandeArete, GrapheSql, NoeudRef, alimentation, schema
from opsys.outils import Autonomie, Niveau, Outil
from opsys.stockage.schema import CONNAISSANCES_VERSIONS

from . import classification, etapes

AGENT = "agent:m10-memoire"
PRODUCTEUR = "m10-memoire"


# -- adaptation
# ---------------------------------------------------------------------------------------------------------------
def _instant() -> str:
    return service.instant_iso(service.maintenant())


def _acteur_humain(nom_outil: str) -> soi.Acteur:
    """La PERSONNE qui décide : `outils._acteur_humain` (jeton d'appareil admin confirmé en base, ou approbation
    humaine en
    cours dans la file). Tout le reste est refusé, y compris un appel d'agent dans un mode sans file."""
    from . import outils  # import tardif : outils.py importe ce module

    acteur, refus = outils._acteur_humain(nom_outil)
    if acteur is None:
        detail = (refus or {}).get("verdict", {}).get("detail") or "une personne identifiée est requise"
        raise ErreurMnemo(codes.HUMAIN_REQUIS, detail)
    return soi.Acteur(acteur["par"], acteur["role"], acteur["source"])


def _registres_sources() -> dict[str, Any]:
    return {
        "evenements": registres.evenements(),
        "affaires": registres.affaires(),
        "faits_analytiques": registres.faits_analytiques(),
    }


def _connaissance_existe(version_id: str) -> bool:
    cnx = service.connexion()
    return (
        cnx.execute(
            select(CONNAISSANCES_VERSIONS.c.version_id).where(CONNAISSANCES_VERSIONS.c.version_id == version_id)
        ).first()
        is not None
    )


def _verificateur(profil: soi_sources.Profil | None = None) -> soi.Verificateur:
    return soi_sources.verificateur(
        _registres_sources(), profil or soi_sources.lire_profil(), connaissance_existe=_connaissance_existe
    )


def _publier(type_evenement: str, evenement_id: str, charge: dict[str, Any]) -> None:
    """Publie sur le bus DANS la transaction de l'appel (hors transaction : rien, comme M8)."""
    if stockage.connexion_courante() is None:
        return
    evenements.publier(type_evenement, PRODUCTEUR, charge, evenement_id=evenement_id)


def _publier_derive(r: dict[str, Any], constate_le: str) -> None:
    dimension, cle = r["dimension"], r["cle"]
    structurante = soi_dimensions.DIMENSIONS[dimension].structurante
    ident = r["enonce_id"] if r["nature"] == "valeur_differente" else f"{r['enonce_id']}-{constate_le[:10]}"
    _publier(
        "m10.soi_revision_proposee",
        f"m10-soi-{r['nature']}-{ident}",
        {
            "enonce_id": r["enonce_id"],
            "dimension": dimension,
            "cle": cle,
            "nature": r["nature"],
            "revise": r.get("revise"),
            "structurante": structurante,
            "constate_le": constate_le,
        },
    )


# -- modèle de soi
# --------------------------------------------------------------------------------------------------------------
def lire_soi(
    dimension: str | None = None, etats: list[str] | None = None, avec_valeur: bool = False, decalage: int = 0
) -> dict[str, Any]:
    service.refuser_appareil()
    vue = soi.vue(
        registres.soi(),
        lecteur="m10-memoire",
        maintenant=service.maintenant(),
        dimension=dimension,
        etats_voulus=tuple(etats) if etats else ("confirme", "propose"),
        decalage=decalage,
    )
    return soi.avec_pagination(
        service.borner(soi.compacter(vue, avec_valeur=avec_valeur), ("enonces", "revisions_en_attente"))
    )


def construire_soi() -> dict[str, Any]:
    """Propose (jamais ne confirme) les énoncés que les ports de lecture existants permettent de sourcer : profil
    d'onboarding, équipes, pack, faits analytiques de M8, travaux terminés. Rejouer ne change rien."""
    service.connexion()
    maintenant = _instant()
    profil = soi_sources.lire_profil()
    observations, couvertes = soi_sources.observations_profil(profil, maintenant)
    faits = [m for m in registres.faits_analytiques().lire() if m.get("type_entree") == "fait_analytique"]
    observations += soi_sources.observations_marges(faits)
    completions = [
        (m["ligne_id"], m["horodatage_completion"])
        for m in registres.evenements().lire()
        if classification.type_evenement(m) == classification.TYPE_WCT
    ]
    observations += soi_sources.observations_saisonnalite(completions)
    bilan = soi_sources.construire(
        registres.soi(),
        observations,
        couvertes,
        verificateur_sources=_verificateur(profil),
        par=AGENT,
        horodatage=maintenant,
    )
    for r in [*bilan["revisions"], *bilan["sources_disparues"]]:
        _publier_derive(r, maintenant)
    bilan["profil_illisible"] = sorted(profil.erreurs)
    bilan["dimensions_sans_alimentation_automatique"] = sorted(
        nom
        for nom, d in soi_dimensions.DIMENSIONS.items()
        if nom in ("clients_types", "preferences_direction", "regles_direction", "ton_marque")
    )
    bilan["mention"] = (
        "Rien n'est confirmé : un énoncé « propose » attend la confirmation d'une personne (m10_confirmer_enonce_soi)."
    )
    return bilan


def proposer_enonce_soi(
    dimension: str, cle: str, valeur: dict[str, Any], sources: list[dict[str, Any]]
) -> dict[str, Any]:
    service.connexion()
    maintenant = _instant()
    r = soi.proposer(
        registres.soi(),
        dimension=dimension,
        cle=cle,
        valeur=valeur,
        sources=sources,
        par=AGENT,
        horodatage=maintenant,
        verificateur=_verificateur(),
    )
    if r["statut"] == "revision_proposee":
        _publier_derive(
            {
                "enonce_id": r["enonce"]["enonce_id"],
                "dimension": r["enonce"]["dimension"],
                "cle": r["enonce"]["cle"],
                "nature": "valeur_differente",
                "revise": r["revise"],
            },
            maintenant,
        )
    r["mention"] = "Proposé, pas confirmé : seule une personne confirme (m10_confirmer_enonce_soi)."
    return r


def confirmer_enonce_soi(enonce_id: str, motif: str) -> dict[str, Any]:
    acteur = _acteur_humain("m10_confirmer_enonce_soi")
    return soi.confirmer(registres.soi(), enonce_id, acteur=acteur, motif=motif, horodatage=_instant())


def rejeter_enonce_soi(enonce_id: str, motif: str) -> dict[str, Any]:
    acteur = _acteur_humain("m10_rejeter_enonce_soi")
    return soi.rejeter(registres.soi(), enonce_id, acteur=acteur, motif=motif, horodatage=_instant())


def retirer_enonce_soi(enonce_id: str, motif: str) -> dict[str, Any]:
    acteur = _acteur_humain("m10_retirer_enonce_soi")
    return soi.retirer(registres.soi(), enonce_id, acteur=acteur, motif=motif, horodatage=_instant())


def declarer_enonce_direction(dimension: str, cle: str, valeur: dict[str, Any], motif: str) -> dict[str, Any]:
    acteur = _acteur_humain("m10_declarer_enonce_direction")
    return soi.declarer_direction(
        registres.soi(), dimension=dimension, cle=cle, valeur=valeur, acteur=acteur, motif=motif, horodatage=_instant()
    )


# -- graphe
# ---------------------------------------------------------------------------------------------------------------------
def _graphe() -> GrapheSql:
    return GrapheSql(service.connexion())


def _jour(a_la_date: str | None) -> str:
    return a_la_date if a_la_date is not None else service.maintenant().date().isoformat()


def _compact(noeud: Any) -> dict[str, Any]:
    return {"type": noeud.type, "cle": noeud.cle, "libelle": noeud.libelle}


def _arete_compacte(a: Any) -> dict[str, Any]:
    return {
        "arete_id": a.arete_id,
        "type": a.type,
        "de": f"{a.de.type}:{a.de.libelle}",
        "vers": f"{a.vers.type}:{a.vers.libelle}",
        "valide_de": a.valide_de,
        "valide_a": a.valide_a,
        "etat": a.etat,
        "sensible": a.sensible,
        "source": a.source_ref,
    }


def graphe_voisinage(
    type_noeud: str,
    cle: str,
    k: int = 2,
    a_la_date: str | None = None,
    types_arete: list[str] | None = None,
    inclure_brouillons: bool = False,
) -> dict[str, Any]:
    v = _graphe().voisinage(
        NoeudRef(type_noeud, cle),
        k,
        a_la_date=_jour(a_la_date),
        types_arete=types_arete,
        inclure_brouillons=inclure_brouillons,
    )
    reponse = {
        "depart": _compact(v.depart),
        "k": v.k,
        "a_la_date": v.a_la_date,
        "tronque": v.tronque,
        "noeuds": [{**_compact(n), "distance": d} for n, d in v.noeuds if d > 0],
        "aretes": [_arete_compacte(a) for a in v.aretes],
        "mention": (
            "Seules les arêtes confirmées répondent (les brouillons sensibles attendent une personne)."
            if not inclure_brouillons
            else "Brouillons inclus : chaque arête dit son état."
        ),
    }
    return service.borner(reponse, ("noeuds", "aretes"))


def graphe_chemin(
    de_type: str,
    de_cle: str,
    vers_type: str,
    vers_cle: str,
    a_la_date: str | None = None,
    k_max: int = 4,
    inclure_brouillons: bool = False,
) -> dict[str, Any]:
    c = _graphe().chemin(
        NoeudRef(de_type, de_cle),
        NoeudRef(vers_type, vers_cle),
        a_la_date=_jour(a_la_date),
        k_max=k_max,
        inclure_brouillons=inclure_brouillons,
    )
    if c is None:
        return {
            "trouve": False,
            "k_max": k_max,
            "a_la_date": _jour(a_la_date),
            "mention": "Aucun chemin confirmé dans cette limite : le graphe ne devine pas de lien.",
        }
    return service.borner(
        {
            "trouve": True,
            "longueur": c.longueur,
            "noeuds": [_compact(n) for n in c.noeuds],
            "aretes": [_arete_compacte(a) for a in c.aretes],
        },
        ("noeuds", "aretes"),
    )


def graphe_pourquoi(
    arete_id: str | None = None,
    de_type: str | None = None,
    de_cle: str | None = None,
    vers_type: str | None = None,
    vers_cle: str | None = None,
    a_la_date: str | None = None,
) -> dict[str, Any]:
    """Pourquoi ce lien : une arête (provenance, états, qui a confirmé) ou le plus court chemin entre deux nœuds, chaque
    arête expliquée."""
    graphe = _graphe()
    if arete_id is not None:
        return service.borner(graphe.pourquoi(arete_id), ("historique",))
    if None in (de_type, de_cle, vers_type, vers_cle):
        raise ErreurMnemo(codes.ENTREE_INVALIDE, "fournir `arete_id`, ou les deux nœuds (type et clé de chacun)")
    c = graphe.chemin(
        NoeudRef(str(de_type), str(de_cle)), NoeudRef(str(vers_type), str(vers_cle)), a_la_date=_jour(a_la_date)
    )
    if c is None:
        return {"trouve": False, "mention": "Aucun lien confirmé entre ces deux nœuds."}
    return service.borner(
        {
            "trouve": True,
            "longueur": c.longueur,
            "explications": [graphe.pourquoi(a.arete_id)["explication"] for a in c.aretes],
        },
        ("explications",),
    )


def graphe_etat() -> dict[str, Any]:
    graphe = _graphe()
    return service.borner(
        {**graphe.etat(), "en_attente_de_confirmation": [_arete_compacte(a) for a in graphe.en_attente(20)]},
        ("en_attente_de_confirmation",),
    )


def proposer_arete_graphe(
    type_arete: str,
    de_type: str,
    de_cle: str,
    vers_type: str,
    vers_cle: str,
    valide_de: str,
    source_ref: str,
    source_type: str = "agent_m10",
    confiance: str = "moyenne",
    de_libelle: str | None = None,
    vers_libelle: str | None = None,
) -> dict[str, Any]:
    """Une arête PROPOSÉE (brouillon) avec une source VÉRIFIABLE. Sensible (extrémité personnelle) : elle attend une
    personne ; sinon, elle reste brouillon jusqu'à confirmation aussi (l'agent ne confirme rien lui-même)."""
    schema.exiger_source_ref(source_ref)
    if source_ref.split(":")[0] == "bus":
        raise ErreurMnemo(
            codes.SOURCE_INVALIDE, "une source « bus » est posée par l'alimentation, pas par une proposition"
        )
    if not _verificateur()({"ref": source_ref}):
        raise ErreurMnemo(
            codes.SOURCE_INTROUVABLE,
            "la source n'existe pas : une arête se sourcie par une ligne de registre, une décision ou une "
            "version de connaissance existante",
        )
    p = _graphe().proposer_arete(
        DemandeArete(
            type=type_arete,
            de=NoeudRef(de_type, de_cle),
            vers=NoeudRef(vers_type, vers_cle),
            valide_de=valide_de,
            origine="agent",
            source_type=source_type,
            source_ref=source_ref,
            confiance=confiance,
            de_libelle=de_libelle,
            vers_libelle=vers_libelle,
        ),
        par=AGENT,
        quand=_instant(),
    )
    if p.creee and p.arete.sensible:
        _publier_attente(p.arete)
    return {
        "creee": p.creee,
        "arete": _arete_compacte(p.arete),
        "mention": "Proposée, pas confirmée : seule une personne confirme (m10_confirmer_arete_graphe).",
    }


def _publier_attente(a: Any) -> None:
    """Annonce une arête sensible en attente. L'identifiant d'événement est celui de l'arête : si le même fait est
    rejoué (rejeu du producteur sous un autre `evenement_id`), l'annonce existe déjà avec un autre instant. Ce n'est
    pas un échec du consommateur (il serait mis en quarantaine), c'est la même annonce."""
    try:
        _publier(
            "m10.arete_en_attente",
            f"m10-arete-attente-{a.arete_id}",
            {"arete_id": a.arete_id, "type_arete": a.type, "source_type": a.source_type, "propose_le": _instant()},
        )
    except evenements.ConflitPublication:
        return


def confirmer_arete_graphe(arete_id: str, motif: str) -> dict[str, Any]:
    acteur, motif = soi.exiger_humain(_acteur_humain("m10_confirmer_arete_graphe"), motif, _instant())
    a = _graphe().confirmer_arete(
        arete_id, par=acteur.par, mode="humain", role=acteur.role, raison=motif, quand=_instant()
    )
    return {"arete": _arete_compacte(a)}


def rejeter_arete_graphe(arete_id: str, motif: str) -> dict[str, Any]:
    acteur, motif = soi.exiger_humain(_acteur_humain("m10_rejeter_arete_graphe"), motif, _instant())
    a = _graphe().rejeter_arete(
        arete_id, par=acteur.par, mode="humain", role=acteur.role, raison=motif, quand=_instant()
    )
    return {"arete": _arete_compacte(a)}


def fermer_arete_graphe(arete_id: str, valide_a: str, motif: str) -> dict[str, Any]:
    acteur, motif = soi.exiger_humain(_acteur_humain("m10_fermer_arete_graphe"), motif, _instant())
    a = _graphe().fermer_arete(
        arete_id, valide_a, par=acteur.par, mode="humain", role=acteur.role, raison=motif, quand=_instant()
    )
    return {"arete": _arete_compacte(a)}


def _client_de_lead() -> Callable[[str], str | None]:
    """lead -> client, d'après les `m2.client_associe` que M10 a mémorisés (jamais deviné)."""
    table: dict[str, str] = {}
    for m in registres.evenements().lire():
        if classification.type_evenement(m) == etapes.TYPE_CLIENT_ASSOCIE:
            table[m["lead_id"]] = m["client_id"]
    return table.get


def alimenter_depuis_evenement(type_evenement: str, charge: dict[str, Any], resultat: dict[str, Any]) -> dict[str, Any]:
    """Après que M10 a mémorisé un événement, nourrit le graphe. Un refus de schéma (identifiant hors forme) est noté
    dans
    le résultat, jamais une panne : la mémorisation de l'événement, elle, a réussi et ne se rejoue pas."""
    ligne_id = resultat.get("ligne_id")
    source = alimentation.source_de(type_evenement, charge, ligne_id)
    graphe = _graphe()
    try:
        plan = alimentation.planifier(type_evenement, charge, source_ref=source, client_de_lead=_client_de_lead())
        bilan = alimentation.appliquer(graphe, plan, type_evenement=type_evenement, source_ref=source, quand=_instant())
    except ErreurMnemo as exc:
        return {"refus": exc.code}
    for a in graphe.en_attente(200):
        if a.source_ref == source and a.sensible:
            _publier_attente(a)
    return bilan


def avec_graphe(type_evenement: str, consommateur: Callable[[dict], dict]) -> Callable[[dict], dict]:
    """Enveloppe un consommateur existant : la mémorisation d'abord (inchangée), puis la nourriture du graphe."""

    def recevoir(charge: dict[str, Any]) -> dict[str, Any]:
        resultat = consommateur(charge)
        return {**resultat, "graphe": alimenter_depuis_evenement(type_evenement, charge, resultat)}

    recevoir.__name__ = getattr(consommateur, "__name__", "recevoir") + "_graphe"
    return recevoir


def recevoir_profil_propriete(charge: dict[str, Any]) -> dict[str, Any]:
    """`m2.profil_propriete_confirme` : M10 ne le mémorise nulle part ailleurs ; il ne nourrit que le graphe."""
    bilan = alimenter_depuis_evenement("m2.profil_propriete_confirme", charge, {})
    return {"memorise": False, "graphe": bilan, "producteur": "m02-revenue-crm"}


def synchroniser_graphe(decalage: int = 0, limite: int = 500) -> dict[str, Any]:
    """Rattrape le graphe depuis les événements déjà mémorisés (idempotent), une page de `limite` maillons à la fois."""
    if type(decalage) is not int or type(limite) is not int or decalage < 0 or not 1 <= limite <= 1000:
        raise ErreurMnemo(codes.ENTREE_INVALIDE, "decalage entier ≥ 0, limite de 1 à 1000")
    graphe = _graphe()
    maillons = registres.evenements().lire()
    page = maillons[decalage : decalage + limite]
    resume = {
        "examines": len(page),
        "noeuds": 0,
        "aretes_proposees": 0,
        "aretes_confirmees_systeme": 0,
        "en_attente_confirmation": 0,
        "deja_connues": 0,
        "refus": 0,
    }
    client = _client_de_lead()
    for m in page:
        genre = classification.type_evenement(m)
        if genre == classification.TYPE_WCT:
            type_evenement, charge = "m4.travaux_termines", m
        elif genre == classification.TYPE_VARIANCE:
            type_evenement, charge = "m6.variance_chantier", m
        elif genre == etapes.TYPE_CLIENT_ASSOCIE:
            type_evenement, charge = "m2.client_associe", m
        else:
            continue
        source = alimentation.source_de(type_evenement, charge, m["ligne_id"])
        try:
            plan = alimentation.planifier(type_evenement, charge, source_ref=source, client_de_lead=client)
            bilan = alimentation.appliquer(
                graphe, plan, type_evenement=type_evenement, source_ref=source, quand=_instant()
            )
        except ErreurMnemo:
            resume["refus"] += 1
            continue
        for cle in (
            "noeuds",
            "aretes_proposees",
            "aretes_confirmees_systeme",
            "en_attente_confirmation",
            "deja_connues",
        ):
            resume[cle] += bilan[cle]
        resume["refus"] += len(bilan["refus"])
    resume["suivant"] = decalage + limite if decalage + limite < len(maillons) else None
    return resume


# -- leçons
# ---------------------------------------------------------------------------------------------------------------------
def _refus_recurrents() -> list[dict[str, Any]]:
    """Les refus d'outil répétés dans des affaires DISTINCTES, d'après les faits candidats du POSTFLIGHT (fermés et
    validés au dépôt). Ce sont des comptes : ni cause ni jugement."""
    groupes: dict[tuple[str, str, str], dict[str, Any]] = {}
    for m in registres.affaires().lire():
        if m.get("type_entree") != "fait_candidat" or m.get("resultat") != "refus" or not m.get("code"):
            continue
        g = groupes.setdefault(
            (m["departement_source"], m["outil"], m["code"]), {"affaires": set(), "lignes": [], "observations": 0}
        )
        g["affaires"].add(m["affaire_id"])
        g["lignes"].append(m["ligne_id"])
        g["observations"] += 1
    return [
        {
            "departement": d,
            "outil": o,
            "code": c,
            "affaires_distinctes": len(g["affaires"]),
            "observations": g["observations"],
            "lignes": sorted(g["lignes"])[:5],
        }
        for (d, o, c), g in sorted(groupes.items())
    ]


def _ecarts() -> tuple[list[lecons.Ecart], list[lecons.Ecart]]:
    maillons = registres.evenements().lire()
    return lecons.ecarts_materiaux(maillons), lecons.ecarts_marge(maillons)


def extraire_lecons() -> dict[str, Any]:
    service.connexion()
    mat, mar = _ecarts()
    bilan = lecons.extraire(
        registres.lecons(),
        ecarts_mat=mat,
        ecarts_mar=mar,
        refus=_refus_recurrents(),
        rejets=soi.rejets_par_dimension(registres.soi()),
        par=AGENT,
        horodatage=_instant(),
    )
    bilan["mention"] = (
        "Des leçons PROPOSÉES, pas évaluées ni décidées : m10_evaluer_lecon, la garde du gabarit "
        "(opsys-metier mnemo garde-lecon), puis la décision d'une personne (m10_decider_lecon)."
    )
    return bilan


def evaluer_lecon(lecon_id: str) -> dict[str, Any]:
    """La MESURE hors ligne (chantiers tenus à l'écart). La garde du gabarit monte une instance fictive : elle ne
    tourne pas dans un appel d'outil, c'est `opsys-metier mnemo garde-lecon`."""
    service.connexion()
    mat, mar = _ecarts()
    r = lecons.evaluer_mesure(
        registres.lecons(), lecon_id, ecarts_mat=mat, ecarts_mar=mar, horodatage=_instant(), par=AGENT
    )
    r["reste_a_faire"] = "Garde du gabarit commun : opsys-metier mnemo garde-lecon --lecon " + lecon_id
    return r


def decider_lecon(lecon_id: str, etape: str, motif: str, pourcentage: int | None = None) -> dict[str, Any]:
    acteur = _acteur_humain("m10_decider_lecon")
    empreinte = _empreinte_garde_de(lecon_id)
    maintenant = _instant()
    r = lecons.decider(
        registres.lecons(),
        lecon_id,
        etape,
        acteur=acteur,
        motif=motif,
        horodatage=maintenant,
        pourcentage=pourcentage,
        empreinte_garde=empreinte,
    )
    lc = lecons.etat(registres.lecons()).lecons[lecon_id]
    _publier(
        "m10.lecon_decidee",
        f"m10-lecon-{lecon_id}-{etape}",
        {
            "lecon_id": lecon_id,
            "genre": lc["genre"],
            "cible": lc["cible"],
            "etape": etape,
            "etat": r["etat"],
            "pourcentage": pourcentage,
            "decide_le": maintenant,
        },
    )
    return r


def _empreinte_garde_de(lecon_id: str) -> str:
    """Empreinte du corpus de garde COURANT du département visé par la leçon (celui qu'une évaluation doit avoir vu)."""
    from opsys.departements import charger_departements, racine_departements
    from opsys.mnemo import garde_gabarit

    st = lecons.etat(registres.lecons())
    if lecon_id not in st.lecons:
        raise ErreurMnemo(codes.LECON_INCONNUE, "leçon introuvable")
    return garde_gabarit.empreinte_garde(charger_departements(racine_departements()), st.lecons[lecon_id]["cible"])


def lire_lecons(genre: str | None = None) -> dict[str, Any]:
    service.refuser_appareil()
    return service.borner(lecons.vue(registres.lecons(), genre=genre), ("lecons",))


def surveiller_lecons() -> dict[str, Any]:
    service.refuser_appareil()
    mat, mar = _ecarts()
    return {
        "surveillance": lecons.surveiller(registres.lecons(), mat, mar),
        "mention": "La surveillance ne retire rien : si une leçon régresse, une personne décide du retour arrière.",
    }


# -- déclarations
# ----------------------------------------------------------------------------------------------------------------
def _nom_enum(valeurs: Any) -> list[str]:
    return list(valeurs)


def _p(**proprietes: Any) -> dict[str, Any]:
    return {"type": "object", "properties": proprietes, "additionalProperties": False}


def outils_mnemo() -> tuple[Outil, ...]:
    dimension = {
        "type": "string",
        "enum": _nom_enum(soi_dimensions.DIMENSIONS),
        "description": "dimension du modèle de soi",
    }
    source = {
        "type": "object",
        "description": "{type, ref, observe_le (+ departement pour un fait de département)} : la ref "
        "se VÉRIFIE (registre:<nom>:<ligne_id>, entreprise:<partie>:<empreinte>, pack:<id>:<empreinte>, decision:<id>, "
        "connaissance:<version>) ; type parmi fait_departement, onboarding, correction_humaine",
    }
    motif = {
        "type": "string",
        "description": "pourquoi, 10 à 500 caractères (écrit avec le nom de la personne qui décide)",
    }
    noeud_type = {"type": "string", "enum": _nom_enum(schema.TYPES_NOEUD)}
    jour = {"type": "string", "description": "AAAA-MM-JJ"}

    def lecture(nom: str, description: str, parametres: dict[str, Any], fonction: Callable[..., Any]) -> Outil:
        return Outil(
            nom=nom,
            description=description,
            parametres=parametres,
            fonction=fonction,
            autonomie=Autonomie.T0,
            niveau=Niveau.N0,
        )

    def ecriture(
        nom: str, description: str, parametres: dict[str, Any], fonction: Callable[..., Any], niveau: Niveau
    ) -> Outil:
        return Outil(
            nom=nom,
            description=description,
            parametres=parametres,
            fonction=fonction,
            autonomie=Autonomie.T1,
            niveau=niveau,
        )

    return (
        lecture(
            "m10_lire_soi",
            "Lit le MODÈLE DE SOI de l'entreprise (services, zones, équipes, capacité, marges observées, saisonnalité, "
            "règles et préférences de la direction, vocabulaire, ton) : chaque énoncé porte sa source, sa confiance "
            "calculée, "
            "son âge et son état (proposé, confirmé, obsolète) ; les révisions en attente et les dimensions "
            "inconnues sont "
            "dites. Seul un énoncé confirmé a été validé par une personne.",
            _p(
                dimension=dimension,
                etats={"type": "array", "items": {"type": "string", "enum": _nom_enum(soi.ETATS)}},
                avec_valeur={"type": "boolean", "description": "joindre la valeur structurée de chaque énoncé"},
                decalage={"type": "integer", "minimum": 0, "description": "reprendre à ce rang (voir `suivant`)"},
            ),
            lire_soi,
        ),
        ecriture(
            "m10_construire_soi",
            "Construit les énoncés du modèle de soi que les lectures existantes permettent de sourcer (profil "
            "d'onboarding, "
            "équipes, pack, faits analytiques de M8, travaux terminés) : tout est PROPOSÉ, rien n'est confirmé. Un "
            "fait qui "
            "contredit un énoncé confirmé devient une révision proposée (jamais un écrasement) ; une source disparue "
            "ouvre "
            "un signal. Rejouer ne change rien. Une partie illisible du profil ne fait rien disparaître.",
            _p(),
            construire_soi,
            Niveau.N2,
        ),
        ecriture(
            "m10_proposer_enonce_soi",
            "Propose UN énoncé du modèle de soi avec 1 à 5 sources vérifiables (une source inventée est refusée). "
            "Nouveau : "
            "proposé ; contredit un confirmé : révision proposée ; identique : corroboration. La confirmation est "
            "humaine.",
            {
                "type": "object",
                "properties": {
                    "dimension": dimension,
                    "cle": {"type": "string"},
                    "valeur": {"type": "object"},
                    "sources": {"type": "array", "items": source, "minItems": 1, "maxItems": 5},
                },
                "required": ["dimension", "cle", "valeur", "sources"],
                "additionalProperties": False,
            },
            proposer_enonce_soi,
            Niveau.N2,
        ),
        ecriture(
            "m10_confirmer_enonce_soi",
            "Confirmation HUMAINE d'un énoncé proposé (ou d'une révision : l'ancien devient obsolète dans la même "
            "écriture), "
            "au nom de la personne qui approuve et avec son motif.",
            {
                "type": "object",
                "properties": {"enonce_id": {"type": "string"}, "motif": motif},
                "required": ["enonce_id", "motif"],
                "additionalProperties": False,
            },
            confirmer_enonce_soi,
            Niveau.N3,
        ),
        ecriture(
            "m10_rejeter_enonce_soi",
            "Rejet HUMAIN d'un énoncé proposé ou d'une révision : il devient obsolète avec le motif ; l'énoncé "
            "confirmé reste.",
            {
                "type": "object",
                "properties": {"enonce_id": {"type": "string"}, "motif": motif},
                "required": ["enonce_id", "motif"],
                "additionalProperties": False,
            },
            rejeter_enonce_soi,
            Niveau.N3,
        ),
        ecriture(
            "m10_retirer_enonce_soi",
            "Retrait HUMAIN d'un énoncé confirmé (obsolète avec le motif ; il reste lisible pour l'audit).",
            {
                "type": "object",
                "properties": {"enonce_id": {"type": "string"}, "motif": motif},
                "required": ["enonce_id", "motif"],
                "additionalProperties": False,
            },
            retirer_enonce_soi,
            Niveau.N3,
        ),
        ecriture(
            "m10_declarer_enonce_direction",
            "Déclaration HUMAINE de la direction (règle, préférence, correction d'un fait) : l'énoncé naît confirmé, "
            "avec "
            "la décision pour source, et remplace l'énoncé confirmé de la même clé sans rien effacer.",
            {
                "type": "object",
                "properties": {
                    "dimension": dimension,
                    "cle": {"type": "string"},
                    "valeur": {"type": "object"},
                    "motif": motif,
                },
                "required": ["dimension", "cle", "valeur", "motif"],
                "additionalProperties": False,
            },
            declarer_enonce_direction,
            Niveau.N3,
        ),
        lecture(
            "m10_graphe_voisinage",
            "Voisinage d'un nœud du graphe de connaissances à 1 à 4 sauts (client, propriété, intervention, matériau, "
            "fournisseur, équipe, document, décision), à une date : seules les arêtes confirmées et valides à cette "
            "date "
            "répondent. Borné ; `tronque` dit si le plafond a coupé.",
            {
                "type": "object",
                "properties": {
                    "type_noeud": noeud_type,
                    "cle": {"type": "string"},
                    "k": {"type": "integer", "minimum": 1, "maximum": 4},
                    "a_la_date": jour,
                    "types_arete": {
                        "type": "array",
                        "items": {"type": "string", "enum": _nom_enum(schema.TYPES_ARETE)},
                    },
                    "inclure_brouillons": {"type": "boolean"},
                },
                "required": ["type_noeud", "cle"],
                "additionalProperties": False,
            },
            graphe_voisinage,
        ),
        lecture(
            "m10_graphe_chemin",
            "Plus court chemin entre deux nœuds du graphe (4 sauts au plus), à une date. Aucun chemin : il le dit, "
            "sans "
            "deviner de lien.",
            {
                "type": "object",
                "properties": {
                    "de_type": noeud_type,
                    "de_cle": {"type": "string"},
                    "vers_type": noeud_type,
                    "vers_cle": {"type": "string"},
                    "a_la_date": jour,
                    "k_max": {"type": "integer", "minimum": 1, "maximum": 4},
                    "inclure_brouillons": {"type": "boolean"},
                },
                "required": ["de_type", "de_cle", "vers_type", "vers_cle"],
                "additionalProperties": False,
            },
            graphe_chemin,
        ),
        lecture(
            "m10_graphe_pourquoi",
            "Pourquoi ce lien : pour une arête (`arete_id`), sa provenance, son origine, ses états et qui l'a "
            "confirmée ; "
            "pour deux nœuds, le plus court chemin avec l'explication de chaque arête.",
            {
                "type": "object",
                "properties": {
                    "arete_id": {"type": "string"},
                    "de_type": noeud_type,
                    "de_cle": {"type": "string"},
                    "vers_type": noeud_type,
                    "vers_cle": {"type": "string"},
                    "a_la_date": jour,
                },
                "additionalProperties": False,
            },
            graphe_pourquoi,
        ),
        lecture(
            "m10_graphe_etat",
            "État du graphe : nœuds par type, arêtes par état, arêtes sensibles en attente de confirmation (la file "
            "de la "
            "direction).",
            _p(),
            graphe_etat,
        ),
        ecriture(
            "m10_proposer_arete_graphe",
            "Propose une arête du graphe (schéma fermé : possede, demande, realisee_sur, realisee_par, utilise, "
            "fourni_par, "
            "documente, justifie, concerne, precede) avec une source VÉRIFIABLE. Elle naît en brouillon ; seule une "
            "personne "
            "la confirme. Un client ou une propriété ne se désigne que par son pseudonyme, jamais par un nom ni une "
            "adresse.",
            {
                "type": "object",
                "properties": {
                    "type_arete": {"type": "string", "enum": _nom_enum(schema.TYPES_ARETE)},
                    "de_type": noeud_type,
                    "de_cle": {"type": "string"},
                    "de_libelle": {"type": "string"},
                    "vers_type": noeud_type,
                    "vers_cle": {"type": "string"},
                    "vers_libelle": {"type": "string"},
                    "valide_de": jour,
                    "source_ref": {"type": "string"},
                    "source_type": {"type": "string"},
                    "confiance": {"type": "string", "enum": _nom_enum(schema.CONFIANCES)},
                },
                "required": ["type_arete", "de_type", "de_cle", "vers_type", "vers_cle", "valide_de", "source_ref"],
                "additionalProperties": False,
            },
            proposer_arete_graphe,
            Niveau.N2,
        ),
        ecriture(
            "m10_confirmer_arete_graphe",
            "Confirmation HUMAINE d'une arête en brouillon (obligatoire pour une arête sensible : donnée personnelle).",
            {
                "type": "object",
                "properties": {"arete_id": {"type": "string"}, "motif": motif},
                "required": ["arete_id", "motif"],
                "additionalProperties": False,
            },
            confirmer_arete_graphe,
            Niveau.N3,
        ),
        ecriture(
            "m10_rejeter_arete_graphe",
            "Rejet HUMAIN d'une arête en brouillon (elle ne répondra jamais à une requête ; elle reste lisible pour "
            "l'audit).",
            {
                "type": "object",
                "properties": {"arete_id": {"type": "string"}, "motif": motif},
                "required": ["arete_id", "motif"],
                "additionalProperties": False,
            },
            rejeter_arete_graphe,
            Niveau.N3,
        ),
        ecriture(
            "m10_fermer_arete_graphe",
            "Fermeture HUMAINE de la validité d'une arête confirmée à une date (la relation a cessé) : rien n'est "
            "réécrit, "
            "l'historique reste.",
            {
                "type": "object",
                "properties": {"arete_id": {"type": "string"}, "valide_a": jour, "motif": motif},
                "required": ["arete_id", "valide_a", "motif"],
                "additionalProperties": False,
            },
            fermer_arete_graphe,
            Niveau.N3,
        ),
        ecriture(
            "m10_synchroniser_graphe",
            "Rattrape le graphe depuis les événements déjà mémorisés (travaux terminés, variances de matériaux, "
            "clients "
            "associés) : brouillons d'arêtes sensibles, arêtes non sensibles confirmées par le système. Idempotent, "
            "par pages.",
            _p(decalage={"type": "integer", "minimum": 0}, limite={"type": "integer", "minimum": 1, "maximum": 1000}),
            synchroniser_graphe,
            Niveau.N2,
        ),
        lecture(
            "m10_lire_lecons",
            "Lit les leçons apprises (proposées, évaluées, en canari, promues, retirées, refusées) avec leur source, "
            "leur "
            "évaluation hors ligne et les décisions humaines. Aucune leçon ne s'applique seule.",
            _p(genre={"type": "string", "enum": _nom_enum(lecons.GENRES)}),
            lire_lecons,
        ),
        ecriture(
            "m10_extraire_lecons",
            "Tire des leçons candidates de ce que M10 a mémorisé (écarts de quantité de matériaux, écarts de marge, "
            "refus "
            "d'outils répétés, rejets répétés du modèle de soi) : calcul déterministe, support minimal, signe "
            "cohérent. "
            "Elles sont PROPOSÉES, ni évaluées ni décidées.",
            _p(),
            extraire_lecons,
            Niveau.N2,
        ),
        ecriture(
            "m10_evaluer_lecon",
            "Mesure hors ligne d'une leçon chiffrée sur des chantiers tenus à l'écart (erreur avant / après, pire "
            "dégradation). "
            "La garde du gabarit commun se lance par `opsys-metier mnemo garde-lecon`. Ne décide rien.",
            {
                "type": "object",
                "properties": {"lecon_id": {"type": "string"}},
                "required": ["lecon_id"],
                "additionalProperties": False,
            },
            evaluer_lecon,
            Niveau.N2,
        ),
        ecriture(
            "m10_decider_lecon",
            "Décision HUMAINE sur une leçon : canari (1 à 50 % des cas), promotion complète, retour arrière ou "
            "refus. Canari et "
            "promotion exigent une évaluation favorable sur le corpus de garde courant. Une leçon promue est lisible, "
            "jamais appliquée seule.",
            {
                "type": "object",
                "properties": {
                    "lecon_id": {"type": "string"},
                    "etape": {"type": "string", "enum": ["canari", "complete", "retour_arriere", "refusee"]},
                    "motif": motif,
                    "pourcentage": {"type": "integer", "minimum": 1, "maximum": 50},
                },
                "required": ["lecon_id", "etape", "motif"],
                "additionalProperties": False,
            },
            decider_lecon,
            Niveau.N3,
        ),
        lecture(
            "m10_surveiller_lecons",
            "Rejoue chaque leçon chiffrée promue sur les chantiers terminés depuis sa promotion : améliore, régresse "
            "ou "
            "données insuffisantes. Ne retire rien : si elle régresse, une personne décide du retour arrière.",
            _p(),
            surveiller_lecons,
        ),
    )
