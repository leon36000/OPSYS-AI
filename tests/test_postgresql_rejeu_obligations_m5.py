"""Rejeu PostgreSQL : obligations M5 préparées par un administrateur d'appareil (validation au départ), dont les deux
appels simultanés qui visent le même plafond (défaut L11 : le perdant recevait `EcritureConcurrente` au lieu du
refus)."""

from pg_rejeu import installer, module

INJECTES = installer(
    globals(),
    "test_obligations_preparees_appareil_atomiques.py",
)


def test_deux_validations_qui_se_croisent_au_point_d_ecriture_le_perdant_recoit_le_refus_et_non_une_exception(
    session, monkeypatch,
):
    """Défaut L11, rendu DÉTERMINISTE : les deux appels sont tenus au point d'ajout du maillon jusqu'à ce que les
    deux l'aient atteint. Sans le verrou d'écriture de console, les deux lisent le même état puis écrivent le même rang
    (clé en double). Avec lui, le second attend la fin du premier et rend le refus de plafond que rend SQLite (le point
    de rencontre n'est alors atteint que par un appel : la barrière expire et ne bloque personne)."""
    import contextlib
    import importlib
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, BrokenBarrierError, get_ident

    from opsys import contexte

    maillons = importlib.import_module("opsys.stockage.maillons")

    t = module("test_obligations_preparees_appareil_atomiques.py")
    with session() as cnx:
        t._admin(cnx)
        avant = t._tables(cnx)
    barriere = Barrier(2)
    passes: set[int] = set()
    original = maillons.MaillonsDurables.append

    def croise(self, *args, **kwargs):
        if self.registre == "obligations_preparees" and get_ident() not in passes:
            passes.add(get_ident())
            with contextlib.suppress(BrokenBarrierError):
                barriere.wait(timeout=2)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(maillons.MaillonsDurables, "append", croise)

    def appeler(n):
        identite = contexte.IdentiteAppelante(t.ACTEUR, "admin", source="appareil")
        with contexte.appele_par_appareil(identite):
            return t._cap().appeler(t.WRITER, t._args(), meta=t._meta("00000000-0000-4000-8000-00000000000" + str(n)))

    with ThreadPoolExecutor(max_workers=2) as pool:
        resultats = list(pool.map(appeler, [1, 2]))
    assert sum(r.get("rejoue") is False and r.get("resultat", {}).get("accepte") is True for r in resultats) == 1
    assert sum(r.get("resultat", {}).get("accepte") is False for r in resultats) == 1
    with session() as cnx:
        apres = t._tables(cnx)
    assert len(apres["registres_maillons"]) == len(avant["registres_maillons"]) + 1
