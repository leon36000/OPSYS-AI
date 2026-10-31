"""Requête interne SQLite liée à une livraison qualifiée.

La protection est une convention interne, pas une frontière contre du Python
arbitraire dans le même processus ; aucune politique n’est créée ici.
"""

_SCHEMA = "opsys.core.m4.source-request.v1"
_CONSTRUCTION = object()


def _etat_sqlite(sc, portee):
    if sc._COURANTE.get() is not portee:
        raise sc.RefusAutorite("portée absente ou remplacée")
    portee._verifier()
    if (
        portee.consommateur != sc._CONSOMMATEUR
        or portee.evenement.get("type_evenement") != "m4.travaux_termines"
        or portee.evenement.get("producteur") != "m04-field-ops"
    ):
        raise sc.RefusAutorite("livraison hors périmètre")
    cnx = portee.cnx
    base = sc._base(cnx)
    instance = cnx.execute(
        sc.select(sc.OPSYS_INSTANCE.c.instance_id).where(sc.OPSYS_INSTANCE.c.id == 1)
    ).scalar_one_or_none()
    if type(instance) is not str or not instance or len(instance) > 256:
        raise sc.RefusAutorite("instance absente ou invalide")
    politique = sc._politique(cnx, instance, portee.consommateur)
    if politique is None or not politique.active or politique.expire_le <= sc.time():
        raise sc.RefusAutorite("politique inactive ou expirée")
    ident = portee.evenement.get("evenement_id")
    if type(ident) is not str or not ident or len(ident) > 256:
        raise sc.RefusAutorite("identité de livraison invalide")
    # Le payload reste un indice à vérifier par M4, jamais un fait d'autorité.
    portee._verifier()
    if (
        sc.time() >= politique.expire_le
        or sc._base(cnx) != base
        or sc._politique(cnx, instance, portee.consommateur) != politique
        or cnx.execute(
            sc.select(sc.OPSYS_INSTANCE.c.instance_id).where(sc.OPSYS_INSTANCE.c.id == 1)
        ).scalar_one_or_none()
        != instance
    ):
        raise sc.RefusAutorite("liaison modifiée pendant la vérification")
    return base, instance, politique, ident


def _etat(sc, portee):
    if sc._COURANTE.get() is not portee:
        raise sc.RefusAutorite("portée absente ou remplacée")
    dialecte = portee.cnx.engine.dialect.name
    if dialecte == "sqlite":
        return "sqlite", _etat_sqlite(sc, portee)
    raise sc.RefusAutorite("backend non qualifié")


class _Requete:
    __slots__ = ("_portee", "_empreinte")

    def __init__(self, cle, portee, empreinte):
        from . import service_capability as sc

        if cle is not _CONSTRUCTION:
            raise sc.RefusAutorite("construction interne requise")
        self._portee, self._empreinte = portee, empreinte

    def __copy__(self):
        raise TypeError("copie interdite")

    def __deepcopy__(self, memo):
        raise TypeError("copie interdite")

    def __reduce__(self):
        raise TypeError("sérialisation interdite")

    def _verifier(self):
        """Revalide puis retourne uniquement connexion et identifiants internes.

        Le producteur M4 doit revérifier ses propres sources et conserver la
        portée pendant toute lecture ; aucune preuve M4 n'est créée ici.
        """
        from . import service_capability as sc

        actuel = _etat(sc, self._portee)
        if actuel != self._empreinte:
            raise sc.RefusAutorite("liaison modifiée")
        return self._portee.cnx, _SCHEMA, actuel[1][1], actuel[1][3]


def _requete_pour_portee(portee):
    """Prépare la demande en portée vérifiée ; sans appel M4 ni grant."""
    from . import service_capability as sc

    if portee is None or sc._COURANTE.get() is not portee:
        raise sc.RefusAutorite("aucune livraison")
    etat = _etat(sc, portee)
    requete = _Requete(_CONSTRUCTION, portee, etat)
    requete._verifier()
    return requete
