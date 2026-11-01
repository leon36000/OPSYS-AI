"""Parité SQLite / PostgreSQL des comparaisons-échanges sur les ÉTATS append-only (connaissances M10, graphe M10).

Défauts réels trouvés en rejouant la suite sur PostgreSQL (qualification PostgreSQL, 2026-11-01) :

1. `connaissances.etats.ajouter_etat` vérifiait `rowcount != 1` après un `INSERT … SELECT` : sous psycopg, `rowcount` y
   vaut -1, donc TOUTE transition légitime était refusée (« l'état courant n'est plus … »).
2. Corrigé en RETURNING, un défaut plus profond apparaissait : en READ COMMITTED, deux transactions concurrentes lisent
   toutes les deux l'état « attendu » (l'événement de l'autre n'est pas validé) et s'écrivent chacune. Sur SQLite
   l'écrivain unique (`BEGIN IMMEDIATE`) masquait la course. Huit transitions simultanées « brouillon → revu »
   donnaient huit événements « revu » ; une version retirée pouvait redevenir « revue ». Même motif pour les arêtes du
   graphe.

Chaque test tourne sur les deux moteurs (`url_base`). Données fictives, aucun réseau.
"""

from __future__ import annotations

import threading

import pytest
from connaissances_aide import ingerer
from pg_parite import base_pg, serveur_pg, url_base  # noqa: F401  (fixtures pytest)
from sqlalchemy import func, select

from opsys import stockage
from opsys.connaissances import etats
from opsys.connaissances.codes import TRANSITION_INTERDITE, ErreurConnaissances
from opsys.mnemo import codes as codes_mnemo
from opsys.mnemo.codes import ErreurMnemo
from opsys.mnemo.graphe import DemandeArete, GrapheSql, NoeudRef
from opsys.stockage.schema import CONNAISSANCES_ETATS, GRAPHE_ARETES_ETATS

FICTIF = True
T0 = "2026-11-01T12:00:00+00:00"


def _course(moteur, taches):
    """Lance `taches` (appelables prenant une connexion) en même temps, chacune dans SA transaction, qui reste ouverte
    brièvement après l'écriture : sans verrou, la course est alors certaine sur PostgreSQL. Sur SQLite, l'écrivain
    unique
    fait attendre les autres (même résultat, par un autre mécanisme)."""
    barriere = threading.Barrier(len(taches))
    issues = [None] * len(taches)

    def lancer(i):
        try:
            barriere.wait(10)  # avant d'ouvrir la transaction : SQLite prend son verrou d'écriture dès le début
            with moteur.connect() as cnx, cnx.begin():
                taches[i](cnx)
                threading.Event().wait(0.2)
            issues[i] = "ok"
        except (ErreurConnaissances, ErreurMnemo) as exc:
            issues[i] = exc.code
        except Exception as exc:  # noqa: BLE001 — une panne inattendue doit faire échouer le test, pas le masquer
            issues[i] = f"PANNE:{type(exc).__name__}:{exc}"

    fils = [threading.Thread(target=lancer, args=(i,)) for i in range(len(taches))]
    for f in fils:
        f.start()
    for f in fils:
        f.join(30)
    return issues


def test_transition_d_etat_de_connaissance_sans_concurrence_n_est_plus_refusee(url_base):  # noqa: F811
    """Régression du `rowcount == -1` : la transition légitime passe, la rejouée est refusée, sur les deux moteurs."""
    with stockage.transaction(url_base) as cnx:
        version_id = ingerer(cnx)["version_id"]
        etats.ajouter_etat(cnx, version_id, "revu", attendu="brouillon", par="a", mode="agent", role=None,
                           raison=None, controles=None, quand=T0)
        assert etats.etat_courant(cnx, version_id) == "revu"
        with pytest.raises(ErreurConnaissances, match=TRANSITION_INTERDITE), cnx.begin_nested():
            etats.ajouter_etat(cnx, version_id, "revu", attendu="brouillon", par="b", mode="agent", role=None,
                               raison=None, controles=None, quand=T0)
        assert [h["etat"] for h in etats.historique(cnx, version_id)] == ["brouillon", "revu"]


def test_huit_transitions_simultanees_de_connaissance_n_en_ecrivent_qu_une(url_base):  # noqa: F811
    with stockage.transaction(url_base) as cnx:
        version_id = ingerer(cnx)["version_id"]
    moteur = stockage.moteur(url_base)

    def transition(i):
        def faire(cnx):
            etats.ajouter_etat(cnx, version_id, "revu", attendu="brouillon", par=f"p{i}", mode="agent", role=None,
                               raison=None, controles=None, quand=f"2026-11-01T12:00:0{i}+00:00")
        return faire

    issues = _course(moteur, [transition(i) for i in range(8)])
    assert issues.count("ok") == 1, issues
    assert issues.count(TRANSITION_INTERDITE) == 7, issues
    with stockage.transaction(url_base) as cnx:
        revus = cnx.execute(select(func.count()).select_from(CONNAISSANCES_ETATS).where(
            CONNAISSANCES_ETATS.c.version_id == version_id, CONNAISSANCES_ETATS.c.etat == "revu")).scalar_one()
        assert revus == 1 and etats.etat_courant(cnx, version_id) == "revu"


def test_un_retrait_et_une_revue_simultanes_ne_ressuscitent_pas_la_version(url_base):  # noqa: F811
    """Le cas grave : « retiré » et « revu » issus du même état « brouillon » ne peuvent pas s'écrire tous les deux (la
    version retirée redeviendrait « revue » selon l'ordre d'écriture)."""
    with stockage.transaction(url_base) as cnx:
        version_id = ingerer(cnx)["version_id"]
    moteur = stockage.moteur(url_base)

    def revoir(cnx):
        etats.ajouter_etat(cnx, version_id, "revu", attendu="brouillon", par="r", mode="agent", role=None,
                           raison=None, controles=None, quand=T0)

    def retirer(cnx):
        etats.ajouter_etat(cnx, version_id, "retire", attendu="brouillon", par="x", mode="agent", role=None,
                           raison="Retrait concurrent de démonstration", controles=None, quand=T0)

    issues = _course(moteur, [revoir, retirer])
    assert sorted(issues) == sorted(["ok", TRANSITION_INTERDITE]), issues
    with stockage.transaction(url_base) as cnx:
        historique = [h["etat"] for h in etats.historique(cnx, version_id)]
        assert len(historique) == 2 and historique[0] == "brouillon"  # jamais brouillon, retiré, revu (ressuscitée)


def _demande():
    return DemandeArete(type="utilise", de=NoeudRef("intervention", "I-1"), vers=NoeudRef("materiau", "m1"),
                        valide_de="2026-01-01", origine="agent", source_type="test_fictif", source_ref="test:source")


def test_confirmation_et_rejet_simultanes_d_une_arete_n_en_ecrivent_qu_un(url_base):  # noqa: F811
    with stockage.transaction(url_base) as cnx:
        arete = GrapheSql(cnx).proposer_arete(_demande(), par="agent:m10", quand=T0)
        arete_id = arete.arete.arete_id
    moteur = stockage.moteur(url_base)

    def confirmer(cnx):
        GrapheSql(cnx).confirmer_arete(arete_id, par="direction", mode="humain", role="admin", raison="vérifié",
                                       quand=T0)

    def rejeter(cnx):
        GrapheSql(cnx).rejeter_arete(arete_id, par="direction2", mode="humain", role="admin", raison="faux",
                                     quand=T0)

    issues = _course(moteur, [confirmer, rejeter])
    assert sorted(issues) == sorted(["ok", codes_mnemo.ARETE_TRANSITION]), issues
    with stockage.transaction(url_base) as cnx:
        nombre = cnx.execute(select(func.count()).select_from(GRAPHE_ARETES_ETATS).where(
            GRAPHE_ARETES_ETATS.c.arete_id == arete_id)).scalar_one()
        assert nombre == 2  # brouillon + UNE décision
