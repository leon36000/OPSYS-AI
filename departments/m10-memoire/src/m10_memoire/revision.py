from . import contrats, humain, validation

_TYPE_ENTREE_REVISION = "revision_signalee"
_STATUT_INITIAL = "en_attente"

REJ_REVISION_LIGNES_IDENTIQUES = "REJ-REVISION-LIGNES-IDENTIQUES"
REJ_REVISION_LIGNE_INTROUVABLE = "REJ-REVISION-LIGNE-INTROUVABLE"
REJ_REVISION_STATUT_INCONNU = "REJ-REVISION-STATUT-INCONNU"
REJ_REVISION_SIGNALEMENT_INTROUVABLE = "REJ-REVISION-SIGNALEMENT-INTROUVABLE"


def _retrouver_maillon(registre_cible, ligne_id):
    for maillon in registre_cible.lire():
        if maillon.get("ligne_id") == ligne_id:
            return maillon
    raise RuntimeError("Maillon ajouté introuvable.")


def _signalement_existe(registre_cible, revision_ligne_id):
    """Vrai SSI ``revision_ligne_id`` désigne un SIGNALEMENT réellement écrit.

    Un maillon d'arbitrage porte aussi ``type_entree == "revision_signalee"``
    mais a ``ligne_id_a is None`` (cf. ``arbitrer_revision`` ci-dessous) : seul
    un signalement (``ligne_id_a`` non None, écrit par ``signaler_revision``)
    est une cible légitime d'arbitrage.
    """
    for maillon in registre_cible.lire():
        if (
            maillon.get("type_entree") == _TYPE_ENTREE_REVISION
            and maillon.get("ligne_id") == revision_ligne_id
            and maillon.get("ligne_id_a") is not None
        ):
            return True
    return False


def signaler_revision(registre_cible, ligne_id_a, ligne_id_b, horodatage):
    if ligne_id_a == ligne_id_b:
        return None, REJ_REVISION_LIGNES_IDENTIQUES

    ligne_ids_existants = {
        maillon.get("ligne_id") for maillon in registre_cible.lire()
    }
    if ligne_id_a not in ligne_ids_existants or ligne_id_b not in ligne_ids_existants:
        return None, REJ_REVISION_LIGNE_INTROUVABLE

    ligne_id = registre_cible.ajouter(
        {
            "type_entree": _TYPE_ENTREE_REVISION,
            "horodatage": horodatage,
            "ligne_id_a": ligne_id_a,
            "ligne_id_b": ligne_id_b,
            "statut": _STATUT_INITIAL,
            "revision_ligne_id": None,
        }
    )
    return _retrouver_maillon(registre_cible, ligne_id), None


def arbitrer_revision(registre_cible, revision_ligne_id, statut, horodatage, acteur=None):
    # None conserve le contrat historique des appels purs à quatre arguments.
    if acteur is not None and (
        not isinstance(acteur, dict)
        or not humain.acteur_valide(acteur.get("par"), acteur.get("role"), acteur.get("source"))
    ):
        return None, validation.construire_verdict(
            humain.REJ_HUMAIN_ACTEUR_INVALIDE, "l'arbitrage exige un acteur humain identifié"
        )
    if statut not in contrats.STATUT_REVISION:
        return None, REJ_REVISION_STATUT_INCONNU

    if not _signalement_existe(registre_cible, revision_ligne_id):
        return None, REJ_REVISION_SIGNALEMENT_INTROUVABLE

    ligne_id = registre_cible.ajouter(
        {
            "type_entree": _TYPE_ENTREE_REVISION,
            "horodatage": horodatage,
            "ligne_id_a": None,
            "ligne_id_b": None,
            "statut": statut,
            "revision_ligne_id": revision_ligne_id,
            **(
                {"par": acteur["par"], "role": acteur["role"], "source_decision": acteur["source"]}
                if acteur is not None else {}
            ),
        }
    )
    return _retrouver_maillon(registre_cible, ligne_id), None


def statut_revision(registre_cible, revision_ligne_id):
    signalement = None
    arbitrage = None

    for maillon in registre_cible.lire():
        if maillon.get("type_entree") != _TYPE_ENTREE_REVISION:
            continue
        if maillon.get("revision_ligne_id") == revision_ligne_id:
            arbitrage = maillon.get("statut")
        if maillon.get("ligne_id") == revision_ligne_id:
            signalement = maillon.get("statut")

    if arbitrage is not None:
        return arbitrage
    return signalement
