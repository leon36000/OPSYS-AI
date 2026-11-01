"""Rejeu PostgreSQL : catalogue, prix, fournisseurs M6 de la console (écritures humaines, deux écrivains)."""

from pg_rejeu import installer, module

INJECTES = installer(
    globals(),
    "test_console_catalogue_m6.py",
    "test_console_prix_m6.py",
    "test_console_fournisseurs_m6.py",
)


def test_deux_correcteurs_dont_le_second_ecrit_apres_le_commit_du_premier_une_seule_modification(
    catalogue, session, monkeypatch,
):
    """Mise à jour perdue, rendue DÉTERMINISTE : la fiche fournisseur est lue puis un maillon est AJOUTÉ par une
    instruction distincte (`len` puis `INSERT` du rang suivant, sans clé qui protège la lecture). Les deux correcteurs
    lisent la même source, puis le second est retardé jusqu'après le commit du premier : sans verrou d'écriture de
    console, il ajoute son maillon au rang suivant et les deux corrections sont acceptées. Avec le verrou, le second
    n'arrive pas à l'ajout (la source a changé : `SOURCE-MODIFIEE`)."""
    import importlib
    import time
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, BrokenBarrierError, Lock

    maillons = importlib.import_module("opsys.stockage.maillons")
    t = module("test_console_fournisseurs_m6.py")
    premier = t.direct(session, t.args())["resultat"]
    deps, depart, rencontre, verrou, arrivees = t.charger_departements(), Barrier(2), Barrier(2), Lock(), []
    original = maillons.MaillonsDurables.append

    def append_retarde(self, *args, **kwargs):
        if self.registre == "fournisseurs":
            with verrou:
                rang_d_arrivee = len(arrivees)
                arrivees.append(rang_d_arrivee)
            try:
                rencontre.wait(timeout=2)  # les deux ont lu la même source avant que personne n'écrive
            except BrokenBarrierError:
                pass
            if rang_d_arrivee == 1:
                time.sleep(1.5)  # le premier a validé quand le second écrit
        return original(self, *args, **kwargs)

    monkeypatch.setattr(maillons.MaillonsDurables, "append", append_retarde)

    def corriger(i):
        depart.wait(timeout=5)
        return t.c.executer(session, t.ECRIRE, t.args(modifications={"nom": f"Nom FICTIF {i}"},
                            source_attendue=premier["source_empreinte"]), f"croise-{i}", deps=deps)["resultat"]

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(corriger, i) for i in range(2)]
        resultats = [f.result(timeout=30) for f in futures]
    assert sum(r["accepte"] for r in resultats) == 1, resultats
    assert [r["raison"] for r in resultats if not r["accepte"]] == ["SOURCE-MODIFIEE"]
    with session():
        assert len(t.stockage.maillons("m06-material-control", "fournisseurs")) == 2
